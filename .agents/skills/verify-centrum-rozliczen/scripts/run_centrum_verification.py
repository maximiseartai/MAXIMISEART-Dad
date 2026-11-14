"""One-command proof of Centrum rozliczeń: fixture, launch, doctor, drive in Chromium, cleanup, self-test.

Prints ``VERIFY OK | features=… | evidence=… | scratch_removed=true`` or
``VERIFY FAIL | …``. Scratch lives in ``<run dir>/runs/centrum-<id>`` and is
removed; evidence lives in ``<run dir>/evidence/centrum-<id>`` and is kept.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from collections.abc import Mapping, Sequence
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from drive import ALL, DEFAULT_REPEATS, FEATURES, broken_rules, feature
from harness import SLOW_RUNNER, File
from import_dynamiczny import jest_modul
from quiet_machine import MachineBusy, QuietMachine
from skrypt_skilla import Parser, child_environment, new_run, part

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[3]
STEP_TIMEOUT_SECONDS = 300
# A drive of several features gets this much per feature: `all` (22 features) drove 280-305 s on windows-latest on
# 26.10 and timed out at a fixed STEP_TIMEOUT_SECONDS (CI runs 40309201075 and 40322305317), so its limit grows with
# each feature it drives.
DRIVE_SECONDS_PER_FEATURE = 40
# A measurement (wydajnosc) repeats every scenario in two CPU profiles, so its drive takes minutes.
PERFORMANCE_TIMEOUT_SECONDS = 1800
REQUIRED_EVIDENCE = (
    "fixture.txt",
    "server.txt",
    "doctor.txt",
    "drive.txt",
    "cleanup.txt",
    "self-test.txt",
)
class VerificationFailure(Exception):
    pass


def driven(feature: str, environment: Mapping[str, str] = os.environ) -> tuple[str, ...]:
    """The features a run of ``--feature feature`` drives, in order: ``all`` is every feature but a measurement,
    or in CI the part ``MUTACJE_CZESC=k/n`` of them (``skrypt_skilla.part``)."""

    return part(ALL, environment) if feature == "all" else (feature,)


def drive_timeout_s(features: Sequence[str]) -> int:
    if any(feature(name).measurement for name in features):
        return PERFORMANCE_TIMEOUT_SECONDS
    return max(STEP_TIMEOUT_SECONDS, DRIVE_SECONDS_PER_FEATURE * len(features))


def _run_step(name: str, arguments: list[str], evidence: Path, timeout: int = STEP_TIMEOUT_SECONDS) -> None:
    command = [sys.executable, *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        (evidence / f"{name}.txt").write_text(f"command: {command}\ntimed out\n", encoding="utf-8")
        raise VerificationFailure(f"{name} timed out") from exc
    (evidence / f"{name}.txt").write_text(
        f"command: {command}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}\nexit_code={completed.returncode}\n",
        encoding="utf-8",
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise VerificationFailure(f"{name} returned {completed.returncode}")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _launch(run_root: Path, evidence: Path) -> tuple[subprocess.Popen[bytes], str]:
    log = (evidence / "server.txt").open("wb")
    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS / "serve_centrum.py"), "--root", str(run_root), "--port", str(_free_port())],
        cwd=REPO_ROOT,
        env=child_environment(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 30
    server_file = File.SERVER.file(run_root)
    while True:
        if process.poll() is not None:
            raise VerificationFailure(f"Centrum exited with {process.returncode} before it was ready; see server.txt")
        if server_file.exists():
            url = str(json.loads(server_file.read_text(encoding="utf-8"))["url"])
            try:
                with urllib.request.urlopen(url + "api/health", timeout=2):
                    return process, url
            except OSError:
                pass
        if time.monotonic() > deadline:
            raise VerificationFailure("Centrum was not ready within 30 seconds; see server.txt")
        time.sleep(0.1)


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _preflight() -> None:
    if broken := broken_rules(FEATURES):
        raise VerificationFailure("; ".join(broken))
    if not (REPO_ROOT / "src" / "rozliczenia" / "centrum" / "static" / "index.html").exists():
        raise VerificationFailure("the built frontend is missing; run `npm ci && npm run build` in frontend/")
    if not jest_modul("playwright"):
        raise VerificationFailure(
            "Playwright for Python is missing; run `pip install playwright` and `python -m playwright install chromium`"
        )


def _verify(features: tuple[str, ...], performance: list[str], run_dir: Path) -> Path:
    run = new_run(run_dir, f"centrum-{uuid.uuid4().hex}")
    run_root, evidence = run.root, run.evidence
    print(f"EVIDENCE {evidence}", flush=True)
    process: subprocess.Popen[bytes] | None = None
    try:
        _preflight()
        variants = sorted({fixture for name in features if (fixture := feature(name).fixture) is not None})
        variant = ["--wariant", *variants] if variants else []
        _run_step("fixture", [str(SCRIPTS / "create_centrum_fixture.py"), "--root", str(run_root), *variant], evidence)
        process, url = _launch(run_root, evidence)
        _run_step("doctor", [str(SCRIPTS / "centrum_doctor.py"), "--root", str(run_root)], evidence)
        _run_step(
            "drive",
            [str(SCRIPTS / "drive_centrum.py"), "--root", str(run_root), "--url", url,
             "--evidence", str(evidence), "--feature", *features, *performance],
            evidence,
            drive_timeout_s(features),
        )
    finally:
        if process is not None:
            _stop(process)
        _run_step("cleanup", [str(SCRIPTS / "centrum_cleanup.py"), "--root", str(run_root)], evidence)
    if run_root.exists():
        raise VerificationFailure(f"scratch was not removed: {run_root}")
    missing = [name for name in REQUIRED_EVIDENCE[:-1] if not (evidence / name).exists()]
    missing += [f"{shot}.png" for name in features for shot in feature(name).screenshots if not (evidence / "screenshots" / f"{shot}.png").exists()]
    missing += [path for name in features for path in feature(name).evidence if not (evidence / path).exists()]
    if missing:
        raise VerificationFailure(f"evidence is missing: {', '.join(missing)}")
    _run_step("self-test", [str(SCRIPTS / "centrum_self_test.py"), "--evidence-root", str(evidence)], evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_run_dir()
    parser.add_argument("--feature", choices=("all", *(each.name for each in FEATURES)), default="all")
    parser.add_argument("--baseline", help="wydajnosc: compare with this baseline instead of the skill's.")
    parser.add_argument(
        "--powtorzenia", type=int, help=f"wydajnosc: repetitions per scenario and profile (default {DEFAULT_REPEATS})."
    )
    parser.add_argument(
        "--wolny-runner",
        action="store_true",
        help="Slow animations, late writes of the tab and a late API, as a slow runner (features/README.md); not in CI.",
    )
    args = parser.parse_args(argv)
    if args.wolny_runner:
        os.environ[SLOW_RUNNER] = "1"
    # The drive's Polish output in UTF-8 whatever the code page: an English Windows pipe (1252) cannot encode it.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    performance = [] if args.baseline is None else ["--baseline", str(Path(args.baseline).resolve())]
    performance += [] if args.powtorzenia is None else ["--powtorzenia", str(args.powtorzenia)]
    try:
        features = driven(args.feature)
    except ValueError as exc:
        print(f"VERIFY FAIL | features={args.feature} | {exc}", file=sys.stderr)
        return 1
    shown = args.feature if features == driven(args.feature, {}) else ",".join(features)
    machine = QuietMachine()
    # A measurement holds the machine alone; every other run waits only for a measurement in progress.
    hold = machine.measurement() if args.feature != "all" and feature(args.feature).measurement else machine.run()
    try:
        with hold as waited:
            if waited >= 1:
                print(f"MASZYNA WOLNA | czekano {waited:.0f} s", flush=True)
            evidence = _verify(features, performance, args.run_dir)
    except (VerificationFailure, MachineBusy) as exc:
        print(f"VERIFY FAIL | features={shown} | {exc}", file=sys.stderr)
        return 1
    print(f"VERIFY OK | features={shown} | evidence={evidence} | scratch_removed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
