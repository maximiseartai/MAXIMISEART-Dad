"""Run the complete disposable verification workflow as one command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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

from skrypt_skilla import SKIPPED, Parser, new_run

from atrapy.scenariusz_rozliczen import (
    COLLECTIVE_TEMPLATE_NAME,
    INTERNAL_TEMPLATE_NAME,
    PERIODS_DIRECTORY,
    REGISTER_NAME,
    TEMPLATES_DIRECTORY,
    WORKER_SETTLEMENTS_DIRECTORY,
    WORKER_TEMPLATE_NAME,
)
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
    """A process the workflow runs: its workflow (variant, run root, evidence root, real Wzorce or ``None``), the steps
    of the process and the helper steps whose evidence a successful run leaves, and the real Wzorce it copies."""

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
    worker_template = run_root / WORKER_TEMPLATE_NAME
    excel_lock(worker_template).touch()


def _create_existing_output(run_root: Path) -> None:
    target_directory = run_root / PERIOD / WORKER_SETTLEMENTS_DIRECTORY
    target_directory.mkdir()
    (target_directory / "existing-synthetic.txt").write_text("preserve", encoding="utf-8")


def _utf8_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    # A stale .pyc from an earlier mutation must never stand in for the current source.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _main_checkout_config() -> Path | None:
    """``config/`` of the main checkout; a worktree shares its git directory but not its git-ignored Wzorce."""

    try:
        common_directory = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return config_dir((REPO_ROOT / common_directory).resolve().parent)


def _default_templates_directory() -> Path:
    local = config_dir(REPO_ROOT)
    candidates = [local]
    main_config = _main_checkout_config()
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

    environment = _utf8_environment()
    source = run_root / PERIOD / SOURCE_NAME
    config = run_root / "worker_mapping.yaml"
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
        "--config",
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
        "--config",
        str(config_directory / "worker_mapping.yaml"),
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

    environment = _utf8_environment()
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

    environment = _utf8_environment()
    config_directory = run_root / TEMPLATES_DIRECTORY
    settlement_metrics = run_root / "settlement-metrics.jsonl"
    templates: Literal["synthetic", "config"] = "synthetic" if templates_directory is None else "config"
    settlement_arguments = [
        "settlement",
        "--source",
        str(run_root / PERIODS_DIRECTORY / PERIOD / SOURCE_NAME),
        "--config",
        str(config_directory / "worker_mapping.yaml"),
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

    environment = _utf8_environment()
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


SETTLEMENT = WorkflowProcess(_run_settlement_workflow, ("dry-run", "run"), ("fixture", "doctor", "cleanup"))
PREPARATION = WorkflowProcess(
    _run_preparation_workflow, ("dry-run", "run"), ("fixture", "doctor", "cleanup"), PREPARATION_TEMPLATE_NAMES
)
CHAIN = WorkflowProcess(
    _run_chain_workflow,
    ("preparation-dry-run", "preparation-run", "settlement-dry-run", "settlement-run"),
    ("fixture", "doctor", "readiness", "cleanup"),
    (*PREPARATION_TEMPLATE_NAMES, WORKER_TEMPLATE_NAME),
)
# Uporządkowanie INTERMAX has no preview without saving, so one run; its Sprawdzanie is the preflight.
INTERMAX = WorkflowProcess(_run_intermax_workflow, ("run",), ("fixture", "cleanup"))
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
        expected_stop_what="spoza konfiguracji wykonawców: unknown.synthetic.",
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
    variant_config = WORKFLOW_VARIANTS[variant]
    run = new_run(run_dir, f"rozliczenia-{uuid.uuid4().hex}")
    run_root, evidence_root = run.root, run.evidence
    failure: BaseException | None = None
    cleanup_failure: BaseException | None = None
    try:
        _run_workflow(variant, run_root, evidence_root, templates_directory)
    except Exception as exc:  # noqa: BLE001 - granica weryfikacji: błąd trafia do VERIFY FAIL po sprzątaniu
        failure = exc
    finally:
        cleanup_environment = os.environ.copy()
        cleanup_environment["PYTHONUTF8"] = "1"
        cleanup_environment["PYTHONIOENCODING"] = "utf-8"
        try:
            _run_step(
                "cleanup",
                [
                    str(HELPER_DIRECTORY / "cleanup.py"),
                    "--root",
                    str(run_root),
                ],
                evidence_root,
                cleanup_environment,
                expected_exit=0,
            )
        except (VerificationFailure, OSError) as exc:
            cleanup_failure = exc

    if failure is not None or cleanup_failure is not None:
        details = [f"workflow={failure}" if failure else "workflow=ok"]
        details.append(f"cleanup={cleanup_failure}" if cleanup_failure else "cleanup=ok")
        print(f"VERIFY FAIL | variant={variant} | evidence={evidence_root} | " + "; ".join(details), file=sys.stderr)
        return 1
    if run_root.exists():
        print(f"VERIFY FAIL | scratch root remains: {run_root}", file=sys.stderr)
        return 1
    required = set(variant_config.evidence_names)
    missing = sorted(name for name in required if not (evidence_root / name).is_file())
    if missing:
        print(f"VERIFY FAIL | missing evidence: {', '.join(missing)}", file=sys.stderr)
        return 1

    self_test_environment = os.environ.copy()
    self_test_environment["PYTHONUTF8"] = "1"
    self_test_environment["PYTHONIOENCODING"] = "utf-8"
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
            self_test_environment,
            expected_exit=0,
        )
    except (VerificationFailure, OSError) as exc:
        print(f"VERIFY FAIL | self-test={exc} | evidence={evidence_root}", file=sys.stderr)
        return 1

    required.add("self-test.txt")
    missing = sorted(name for name in required if not (evidence_root / name).is_file())
    if missing:
        print(f"VERIFY FAIL | missing evidence: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"VERIFY OK | variant={variant} | evidence={evidence_root} | scratch_removed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
