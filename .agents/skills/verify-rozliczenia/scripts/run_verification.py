"""Run the complete disposable verification workflow as one command."""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Literal, TextIO
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

import repo
from skrypt_skilla import SKIPPED, Parser, Run, child_environment, new_run

from atrapy.scenariusz_rozliczen import (
    COLLECTIVE_TEMPLATE_NAME,
    INTERNAL_TEMPLATE_NAME,
    PERIODS_DIRECTORY,
    REGISTER_NAME,
    TEMPLATES_DIRECTORY,
    UNMAPPED_WORKER,
    WORKER_SETTLEMENTS_DIRECTORY,
    WORKER_TEMPLATE_NAME,
)
from atrapy.pliki_taty import WORKER_LIST_NAME
from atrapy.settlement import PERIOD, SOURCE_NAME
from rozliczenia.tool_files import config_dir
from atrapy.workbooks import excel_lock

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[4]
TIMEOUT_SECONDS = 120
PYTHON_COMMAND = (sys.executable,)
PREPARATION_TEMPLATE_NAMES = (INTERNAL_TEMPLATE_NAME, COLLECTIVE_TEMPLATE_NAME)
HELPER_DIRECTORY = Path(".agents") / "skills" / "verify-rozliczenia" / "scripts"
PROCESS_SCRIPT = str(Path("tools") / "uruchom_proces.py")


Workflow = Callable[["WorkflowVariant", Path, Path, "Path | None"], None]


@dataclass(frozen=True)
class WorkflowProcess:
    """A process the workflow runs: its feature of the map (``features/<feature>.md``), its workflow (variant, run root,
    evidence root, real Wzorce or ``None``), the steps of the process and the helper steps whose evidence a successful
    run leaves, and the real Wzorce it copies."""

    feature: str
    run: Workflow
    process_steps: tuple[str, ...]
    helper_steps: tuple[str, ...]
    template_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowVariant:
    process: WorkflowProcess
    include_unmapped: bool = False
    pre_run_setup: Literal["existing", "locked"] | None = None
    dry_run_exit: int = 0
    run_exit: int = 0
    assertion: Literal["run", "existing-output", "no-publish"] = "run"
    expected_stop: str | None = None
    expected_stop_what: str | None = None
    templates: Literal["synthetic", "config"] = "synthetic"

    @property
    def local_only(self) -> bool:
        """The real Wzorce in ``config/`` are git-ignored, so CI has none to verify against."""

        return self.templates == "config"

    @property
    def evidence_names(self) -> frozenset[str]:
        """Evidence files a successful run of this variant leaves behind, before the self-test."""

        return frozenset(
            {
                *(f"{step}.txt" for step in self.process.helper_steps),
                *(
                    name
                    for step in self.process.process_steps
                    for name in (f"{step}.json", f"{step}-metrics.jsonl", f"assert-{step}.txt")
                ),
            }
        )


class VerificationFailure(RuntimeError):
    """A workflow step failed its expected contract."""


class PlanFailure(RuntimeError):
    """The workflow of a variant did not run to its end as a plan."""


@dataclass(frozen=True)
class PlannedStep:
    """A step of a variant: its name, the command it runs with the run's folders as their ``PLACEHOLDERS``, and the
    exit code it expects; ``None`` for a change the workflow makes to the run root between steps, whose command says
    what it makes."""

    name: str
    command: str
    expected_exit: int | None


@dataclass
class _Record:
    """The steps one ``_verify`` passes through, and whether they only get recorded (a plan) or also run."""

    planning: bool
    folders: dict[str, str]
    steps: list[PlannedStep] = field(default_factory=list)


_record: _Record | None = None
PLACEHOLDERS = {"run root": "<run-root>", "evidence": "<evidence>", "templates": "<templates>", "run dir": "<run-dir>"}


def _noted(name: str, words: list[str], expected_exit: int | None) -> bool:
    """Records the step of the running ``_verify``; ``True`` when it makes a plan, so the caller does not run it."""

    if _record is None:
        return False
    shown = [_shown(word, _record.folders) for word in words]
    command = " ".join(f'"{word}"' if " " in word and expected_exit is not None else word for word in shown)
    _record.steps.append(PlannedStep(name, command, expected_exit))
    return _record.planning


def _shown(word: str, folders: dict[str, str]) -> str:
    """``word`` with a run's folder, the longest that holds it, replaced by its placeholder, in forward slashes: a plan
    and a run, on every system, show the same command."""

    for folder in sorted(folders, key=len, reverse=True):
        if word == folder or word.startswith(folder + os.sep):
            return (folders[folder] + word[len(folder):]).replace(os.sep, "/")
    return word


def plan(variant: str) -> list[PlannedStep]:
    """The steps ``variant`` runs: ``_verify`` runs its workflow, but every step and every change to the run root is
    recorded instead of run, with ``PLACEHOLDERS`` for the run's folders. A workflow that does not reach its end so is a ``PlanFailure``."""

    global _record
    outer, _record = _record, _Record(planning=True, folders={placeholder: placeholder for placeholder in PLACEHOLDERS.values()})
    try:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            ended = _verify(variant, Path(PLACEHOLDERS["templates"]), Path(PLACEHOLDERS["run dir"]))
        if ended != 0:
            raise PlanFailure(f"the plan of {variant} stopped: {output.getvalue().strip()}")
        return _record.steps
    finally:
        _record = outer


def _display_command(arguments: list[str]) -> str:
    return shlex.join([*PYTHON_COMMAND, *arguments])


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _echo(text: str, stream: TextIO) -> None:
    if not text:
        return
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        stream.buffer.write(text.encode("utf-8"))
        stream.flush()


@dataclass(frozen=True)
class _Completed:
    stdout: str
    stderr: str
    exit_code: int | None
    launch_error: str | None = None


def _launch(arguments: list[str], environment: dict[str, str]) -> _Completed:
    try:
        completed = subprocess.run(
            [*PYTHON_COMMAND, *arguments],
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return _Completed(
            _decode(exc.stdout), _decode(exc.stderr), None, f"timed out after {TIMEOUT_SECONDS} seconds"
        )
    except OSError as exc:
        return _Completed("", "", None, f"could not start: {exc}")
    return _Completed(_decode(completed.stdout), _decode(completed.stderr), completed.returncode)


def _finish_step(name: str, completed: _Completed, expected_exit: int) -> None:
    _echo(completed.stdout, sys.stdout)
    _echo(completed.stderr, sys.stderr)
    if completed.launch_error is not None:
        raise VerificationFailure(f"{name} {completed.launch_error}")
    if completed.exit_code != expected_exit:
        raise VerificationFailure(f"{name} returned {completed.exit_code}; expected {expected_exit}")


def _run_step(
    name: str,
    arguments: list[str],
    evidence_root: Path,
    environment: dict[str, str],
    *,
    expected_exit: int,
) -> None:
    if _noted(name, [Path(arguments[0]).name, *arguments[1:]], expected_exit):
        return
    completed = _launch(arguments, environment)
    sections = [f"command: {_display_command(arguments)}", "stdout:", completed.stdout, "stderr:", completed.stderr]
    if completed.launch_error is not None:
        sections.extend(["launch_error:", completed.launch_error])
    if completed.exit_code is not None:
        sections.append(f"exit_code={completed.exit_code}")
    (evidence_root / f"{name}.txt").write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    _finish_step(name, completed, expected_exit)


def _json_or_text(stdout: str) -> object:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return stdout


def _run_process_step(
    name: str,
    arguments: list[str],
    metrics: Path,
    evidence_root: Path,
    environment: dict[str, str],
    *,
    expected_exit: int,
) -> None:
    command = [PROCESS_SCRIPT, *arguments, "--metrics", str(metrics)]
    if _noted(name, [Path(PROCESS_SCRIPT).as_posix(), *command[1:]], expected_exit):
        return
    completed = _launch(command, environment)
    evidence = {
        "command": _display_command(command),
        "exit_code": completed.exit_code,
        "launch_error": completed.launch_error,
        "result": _json_or_text(completed.stdout),
        "stderr": completed.stderr,
    }
    (evidence_root / f"{name}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if metrics.is_file():
        shutil.copy2(metrics, evidence_root / f"{name}-metrics.jsonl")
    _finish_step(name, completed, expected_exit)


def _create_lock(run_root: Path) -> None:
    if _noted("lock", ["the Excel lock of the Wzorzec rozliczenia pracownika"], None):
        return
    worker_template = run_root / WORKER_TEMPLATE_NAME
    excel_lock(worker_template).touch()


def _create_existing_output(run_root: Path) -> None:
    if _noted("existing-output", ["the Folder rozliczeń pracowników with a file in it"], None):
        return
    target_directory = run_root / PERIOD / WORKER_SETTLEMENTS_DIRECTORY
    target_directory.mkdir()
    (target_directory / "existing-synthetic.txt").write_text("preserve", encoding="utf-8")


def _default_templates_directory() -> Path:
    local = config_dir(REPO_ROOT)
    candidates = [local]
    main_config = repo.main_config(REPO_ROOT)
    if main_config is not None and main_config != local.resolve():
        candidates.append(main_config)
    for directory in candidates:
        if any((directory / name).is_file() for name in (*PREPARATION_TEMPLATE_NAMES, WORKER_TEMPLATE_NAME)):
            return directory
    return local


def _run_workflow(variant: str, run_root: Path, evidence_root: Path, templates_directory: Path) -> None:
    variant_config = WORKFLOW_VARIANTS[variant]
    real_templates = templates_directory if variant_config.templates == "config" else None
    variant_config.process.run(variant_config, run_root, evidence_root, real_templates)


def _run_settlement_workflow(
    variant_config: WorkflowVariant, run_root: Path, evidence_root: Path, templates_directory: Path | None
) -> None:
    """Przebieg rozliczeń on a synthetic Plik zbiorczy."""

    environment = child_environment()
    source = run_root / PERIOD / SOURCE_NAME
    config = run_root / WORKER_LIST_NAME
    metrics = run_root / "metrics.jsonl"

    fixture_arguments = [str(HELPER_DIRECTORY / "create_fixture.py"), "--root", str(run_root)]
    if variant_config.include_unmapped:
        fixture_arguments.append("--include-unmapped")
    _run_step("fixture", fixture_arguments, evidence_root, environment, expected_exit=0)

    _run_step(
        "doctor",
        [str(HELPER_DIRECTORY / "doctor.py"), "--root", str(run_root)],
        evidence_root,
        environment,
        expected_exit=0,
    )

    settlement_arguments = [
        "settlement",
        "--source",
        str(source),
        "--wykonawcy",
        str(config),
        "--worker-template",
        str(run_root / WORKER_TEMPLATE_NAME),
    ]

    def assert_arguments(step: str, expectation: str) -> list[str]:
        return [
            str(HELPER_DIRECTORY / "assert_results.py"),
            "--root",
            str(run_root),
            "--expect",
            expectation,
            "--result",
            str(evidence_root / f"{step}.json"),
        ]

    _run_process_step(
        "dry-run",
        [*settlement_arguments, "--dry-run"],
        metrics,
        evidence_root,
        environment,
        expected_exit=variant_config.dry_run_exit,
    )
    _run_step("assert-dry-run", assert_arguments("dry-run", "dry-run"), evidence_root, environment, expected_exit=0)

    if variant_config.pre_run_setup == "existing":
        _create_existing_output(run_root)
    elif variant_config.pre_run_setup == "locked":
        _create_lock(run_root)

    _run_process_step(
        "run", settlement_arguments, metrics, evidence_root, environment, expected_exit=variant_config.run_exit
    )
    run_assert_arguments = assert_arguments("run", variant_config.assertion)
    if variant_config.expected_stop is not None:
        run_assert_arguments.extend(["--expected-stop", variant_config.expected_stop])
    if variant_config.expected_stop_what is not None:
        run_assert_arguments.extend(["--expected-what", variant_config.expected_stop_what])
    _run_step("assert-run", run_assert_arguments, evidence_root, environment, expected_exit=0)


def _fixture_arguments(run_root: Path, templates_directory: Path | None, *extra: str) -> list[str]:
    arguments = [str(HELPER_DIRECTORY / "create_preparation_fixture.py"), "--root", str(run_root), *extra]
    if templates_directory is not None:
        arguments.extend(["--templates-from", str(templates_directory)])
    return arguments


def _run_preparation_stage(
    run_root: Path,
    evidence_root: Path,
    environment: dict[str, str],
    *,
    templates: Literal["synthetic", "config"],
    metrics: Path,
    step_prefix: str = "",
) -> None:
    config_directory = run_root / TEMPLATES_DIRECTORY
    preparation_arguments = [
        "preparation",
        "--register",
        str(run_root / REGISTER_NAME),
        "--periods-directory",
        str(run_root / PERIODS_DIRECTORY),
        "--period",
        PERIOD,
        "--wykonawcy",
        str(config_directory / WORKER_LIST_NAME),
        "--internal-template",
        str(config_directory / INTERNAL_TEMPLATE_NAME),
        "--collective-template",
        str(config_directory / COLLECTIVE_TEMPLATE_NAME),
    ]

    def assert_arguments(mode: str) -> list[str]:
        return [
            str(HELPER_DIRECTORY / "assert_preparation.py"),
            "--root",
            str(run_root),
            "--expect",
            mode,
            "--templates",
            templates,
            "--metrics",
            str(metrics),
            "--result",
            str(evidence_root / f"{step_prefix}{mode}.json"),
        ]

    _run_process_step(
        f"{step_prefix}dry-run", [*preparation_arguments, "--dry-run"], metrics, evidence_root, environment, expected_exit=0
    )
    _run_step(f"assert-{step_prefix}dry-run", assert_arguments("dry-run"), evidence_root, environment, expected_exit=0)
    # Exit 2 (Wymaga sprawdzenia): the written Plik zbiorczy carries the Ilości usług warnings assert_preparation checks.
    _run_process_step(f"{step_prefix}run", preparation_arguments, metrics, evidence_root, environment, expected_exit=2)
    _run_step(f"assert-{step_prefix}run", assert_arguments("run"), evidence_root, environment, expected_exit=0)


def _run_preparation_workflow(
    variant_config: WorkflowVariant, run_root: Path, evidence_root: Path, templates_directory: Path | None
) -> None:
    """Przygotowanie pliku zbiorczego on a synthetic Rejestr.

    With ``templates_directory`` the fixture copies the real Wzorce instead of building synthetic ones.
    """

    environment = child_environment()
    _run_step("fixture", _fixture_arguments(run_root, templates_directory), evidence_root, environment, expected_exit=0)
    _run_step(
        "doctor",
        [str(HELPER_DIRECTORY / "preparation_doctor.py"), "--root", str(run_root)],
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_preparation_stage(
        run_root,
        evidence_root,
        environment,
        templates="synthetic" if templates_directory is None else "config",
        metrics=run_root / "metrics.jsonl",
    )


def _run_chain_workflow(
    variant_config: WorkflowVariant, run_root: Path, evidence_root: Path, templates_directory: Path | None
) -> None:
    """Dad's whole path: Rejestr zleceń, Przygotowanie pliku zbiorczego, Gotowość, then Przebieg rozliczeń.

    The Przebieg rozliczeń reads the Plik zbiorczy that the Przygotowanie wrote, after
    the Gotowość step filled N:AT in some of its Wiersze danych like Dad does by hand.
    With ``templates_directory`` all three Wzorce are byte copies of the real ones.
    """

    environment = child_environment()
    config_directory = run_root / TEMPLATES_DIRECTORY
    settlement_metrics = run_root / "settlement-metrics.jsonl"
    templates: Literal["synthetic", "config"] = "synthetic" if templates_directory is None else "config"
    settlement_arguments = [
        "settlement",
        "--source",
        str(run_root / PERIODS_DIRECTORY / PERIOD / SOURCE_NAME),
        "--wykonawcy",
        str(config_directory / WORKER_LIST_NAME),
        "--worker-template",
        str(config_directory / WORKER_TEMPLATE_NAME),
    ]

    def assert_settlement_arguments(mode: str) -> list[str]:
        return [
            str(HELPER_DIRECTORY / "assert_chain.py"),
            "--root",
            str(run_root),
            "--expect",
            mode,
            "--result",
            str(evidence_root / f"settlement-{mode}.json"),
        ]

    _run_step(
        "fixture",
        _fixture_arguments(run_root, templates_directory, "--with-worker-template"),
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_step(
        "doctor",
        [
            str(HELPER_DIRECTORY / "preparation_doctor.py"),
            "--root",
            str(run_root),
            "--with-worker-template",
        ],
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_preparation_stage(
        run_root,
        evidence_root,
        environment,
        templates=templates,
        metrics=run_root / "preparation-metrics.jsonl",
        step_prefix="preparation-",
    )
    _run_step(
        "readiness",
        [str(HELPER_DIRECTORY / "fill_readiness.py"), "--root", str(run_root)],
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_process_step(
        "settlement-dry-run",
        [*settlement_arguments, "--dry-run"],
        settlement_metrics,
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_step(
        "assert-settlement-dry-run",
        assert_settlement_arguments("dry-run"),
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_process_step(
        "settlement-run", settlement_arguments, settlement_metrics, evidence_root, environment, expected_exit=0
    )
    _run_step(
        "assert-settlement-run",
        assert_settlement_arguments("run"),
        evidence_root,
        environment,
        expected_exit=0,
    )


def _run_intermax_workflow(
    variant_config: WorkflowVariant, run_root: Path, evidence_root: Path, templates_directory: Path | None
) -> None:
    """Uporządkowanie INTERMAX: a synthetic INTERMAX with one pasted day of Surowe zlecenia, then the one write.

    The process always saves, after a Kopia INTERMAX in ``--copies``, so every path stays inside the run root.
    """

    environment = child_environment()
    _run_step(
        "fixture",
        [str(HELPER_DIRECTORY / "create_intermax_fixture.py"), "--root", str(run_root)],
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_process_step(
        "run",
        [
            "intermax",
            "--register",
            str(run_root / REGISTER_NAME),
            "--copies",
            str(run_root / "Kopie INTERMAX"),
        ],
        run_root / "metrics.jsonl",
        evidence_root,
        environment,
        expected_exit=0,
    )
    _run_step(
        "assert-run",
        [
            str(HELPER_DIRECTORY / "assert_intermax.py"),
            "--root",
            str(run_root),
            "--result",
            str(evidence_root / "run.json"),
        ],
        evidence_root,
        environment,
        expected_exit=0,
    )


SETTLEMENT = WorkflowProcess(
    "settlement", _run_settlement_workflow, ("dry-run", "run"), ("fixture", "doctor", "cleanup")
)
PREPARATION = WorkflowProcess(
    "prepare-collective-file",
    _run_preparation_workflow,
    ("dry-run", "run"),
    ("fixture", "doctor", "cleanup"),
    PREPARATION_TEMPLATE_NAMES,
)
CHAIN = WorkflowProcess(
    "prepare-and-settle",
    _run_chain_workflow,
    ("preparation-dry-run", "preparation-run", "settlement-dry-run", "settlement-run"),
    ("fixture", "doctor", "readiness", "cleanup"),
    (*PREPARATION_TEMPLATE_NAMES, WORKER_TEMPLATE_NAME),
)
# Uporządkowanie INTERMAX has no preview without saving, so one run; its Sprawdzanie is the preflight.
INTERMAX = WorkflowProcess("order-intermax", _run_intermax_workflow, ("run",), ("fixture", "cleanup"))
WORKFLOW_VARIANTS = {
    "default": WorkflowVariant(SETTLEMENT),
    "existing": WorkflowVariant(
        SETTLEMENT,
        pre_run_setup="existing",
        run_exit=1,
        assertion="existing-output",
        expected_stop="FOLDER_ROZLICZEN_ISTNIEJE",
    ),
    "locked": WorkflowVariant(
        SETTLEMENT,
        pre_run_setup="locked",
        run_exit=1,
        assertion="no-publish",
        expected_stop="ZLY_WZORZEC_PRACOWNIKA",
        expected_stop_what="Wzorzec rozliczenia pracownika jest otwarty lub zablokowany",
    ),
    "unmapped": WorkflowVariant(
        SETTLEMENT,
        include_unmapped=True,
        dry_run_exit=2,
        run_exit=1,
        assertion="no-publish",
        expected_stop="NIEZNANY_WYKONAWCA",
        expected_stop_what=UNMAPPED_WORKER,
    ),
    "preparation": WorkflowVariant(PREPARATION),
    "preparation-real-templates": WorkflowVariant(PREPARATION, templates="config"),
    "chain": WorkflowVariant(CHAIN),
    "chain-real-templates": WorkflowVariant(CHAIN, templates="config"),
    "intermax": WorkflowVariant(INTERMAX),
}
CI_VARIANTS = tuple(name for name, variant in WORKFLOW_VARIANTS.items() if not variant.local_only)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_variants(WORKFLOW_VARIANTS, default="default", every=CI_VARIANTS)
    parser.add_run_dir()
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=None,
        help=(
            "directory with the real Wzorce for the *-real-templates variants "
            "(default: config/ of this checkout, or of the main checkout when run from a worktree)"
        ),
    )
    args = parser.parse_args(argv)

    templates_directory = (args.templates_dir or _default_templates_directory()).expanduser().resolve()
    passed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for variant in args.variant:
        missing_templates = _missing_templates(variant, templates_directory)
        if missing_templates:
            print(
                f"VERIFY SKIP | variant={variant} | templates_dir={templates_directory} | "
                f"missing={', '.join(missing_templates)}"
            )
            skipped.append(variant)
        elif _verify(variant, templates_directory, args.run_dir) == 0:
            passed.append(variant)
        else:
            failed.append(variant)
    if len(args.variant) == 1:
        return 1 if failed else SKIPPED if skipped else 0
    not_run = f" | skipped={', '.join(skipped)}" if skipped else ""
    if failed:
        print(f"VERIFY FAIL | variants={', '.join(failed)}{not_run}", file=sys.stderr)
        return 1
    if skipped:
        print(f"VERIFY SKIP | ok={', '.join(passed) or '-'}{not_run}")
        return SKIPPED
    print(f"VERIFY OK | variants={', '.join(passed)}")
    return 0


def _missing_templates(variant: str, templates_directory: Path) -> list[str]:
    variant_config = WORKFLOW_VARIANTS[variant]
    if not variant_config.local_only:
        return []
    return [name for name in variant_config.process.template_names if not (templates_directory / name).is_file()]


def _verify(variant: str, templates_directory: Path, run_dir: Path) -> int:
    global _record
    variant_config = WORKFLOW_VARIANTS[variant]
    planning = _record is not None and _record.planning
    if planning:
        run = Run(Path(PLACEHOLDERS["run root"]), Path(PLACEHOLDERS["evidence"]))
    else:
        run = new_run(run_dir, f"rozliczenia-{uuid.uuid4().hex}")
        folders = {run.root: "run root", run.evidence: "evidence", templates_directory: "templates", run_dir: "run dir"}
        _record = _Record(planning=False, folders={str(path): PLACEHOLDERS[key] for path, key in folders.items()})
    ran = _record
    run_root, evidence_root = run.root, run.evidence
    failure: BaseException | None = None
    cleanup_failure: BaseException | None = None
    try:
        _run_workflow(variant, run_root, evidence_root, templates_directory)
    except Exception as exc:  # noqa: BLE001 - granica weryfikacji: błąd trafia do VERIFY FAIL po sprzątaniu
        failure = exc
    finally:
        try:
            _run_step(
                "cleanup",
                [
                    str(HELPER_DIRECTORY / "cleanup.py"),
                    "--root",
                    str(run_root),
                ],
                evidence_root,
                child_environment(),
                expected_exit=0,
            )
        except (VerificationFailure, OSError) as exc:
            cleanup_failure = exc

    if failure is not None or cleanup_failure is not None:
        details = [f"workflow={failure}" if failure else "workflow=ok"]
        details.append(f"cleanup={cleanup_failure}" if cleanup_failure else "cleanup=ok")
        print(f"VERIFY FAIL | variant={variant} | evidence={evidence_root} | " + "; ".join(details), file=sys.stderr)
        return 1
    if not planning and run_root.exists():
        print(f"VERIFY FAIL | scratch root remains: {run_root}", file=sys.stderr)
        return 1
    required = set() if planning else set(variant_config.evidence_names)
    missing = sorted(name for name in required if not (evidence_root / name).is_file())
    if missing:
        print(f"VERIFY FAIL | missing evidence: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        _run_step(
            "self-test",
            [
                str(HELPER_DIRECTORY / "self_test.py"),
                "--evidence-root",
                str(evidence_root),
                "--run-dir",
                str(run_dir),
            ],
            evidence_root,
            child_environment(),
            expected_exit=0,
        )
    except (VerificationFailure, OSError) as exc:
        print(f"VERIFY FAIL | self-test={exc} | evidence={evidence_root}", file=sys.stderr)
        return 1

    required |= set() if planning else {"self-test.txt"}
    missing = sorted(name for name in required if not (evidence_root / name).is_file())
    if missing:
        print(f"VERIFY FAIL | missing evidence: {', '.join(missing)}", file=sys.stderr)
        return 1
    if not planning and ran is not None and ran.steps != (planned := plan(variant)):
        differing = next(f"{a} != {b}" for a, b in zip([*ran.steps, None], [*planned, None], strict=False) if a != b)
        print(f"VERIFY FAIL | variant={variant} | the steps that ran differ from its plan: {differing}", file=sys.stderr)
        return 1
    print(f"VERIFY OK | variant={variant} | evidence={evidence_root} | scratch_removed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
