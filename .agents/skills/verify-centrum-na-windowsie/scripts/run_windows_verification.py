"""Verify Centrum rozliczeń on Windows the way Dad starts and uses it, in one command (Windows only).

    py -3 .agents\\skills\\verify-centrum-na-windowsie\\scripts\\run_windows_verification.py [--feature all|<feature>]

Creates ``<run dir>/runs/windows-<id>`` (``windows_tool.prepare``; ``--run-dir``, default ``.verification``), drives the features of
``windows_drive.FEATURES`` (a single feature runs its prerequisites first, reported as preparation), runs the doctor
after each start, keeps the evidence in ``<run dir>/evidence/windows-<id>``, and cleans up. Success prints
``VERIFY OK | features=… | evidence=… | scratch_removed=true``; anything else is ``VERIFY FAIL | …``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import io
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from typing import TextIO, cast

from playwright.sync_api import Page, sync_playwright

from windows_drive import FEATURES, PREREQUISITES
from windows_drive import aktualizacja, instalacja, komunikat_startu, start_skrotem, wskazanie_folderow
from windows_drive.common import Run
import windows_cleanup
import windows_desktop
import windows_doctor
import windows_tool
from skrypt_skilla import Parser, new_run

REPO_ROOT = windows_tool.REPO_ROOT
STATIC = REPO_ROOT / "src" / "rozliczenia" / "centrum" / "static" / "index.html"


class _Tee(io.TextIOBase):
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)


@contextmanager
def _teed(path: Path) -> Iterator[None]:
    with path.open("a", encoding="utf-8") as log:
        stdout = sys.stdout
        sys.stdout = cast(TextIO, _Tee(stdout, log))
        try:
            yield
        finally:
            sys.stdout = stdout


def _preflight(port: int) -> str | None:
    if sys.platform != "win32":
        return "this skill drives Windows only; from macOS use run_on_github.py"
    if not STATIC.is_file():
        return f"no built frontend at {STATIC}; run npm ci and npm run build in frontend/"
    if not Path(sys.executable).with_name("pythonw.exe").is_file():
        return f"{sys.executable} has no pythonw.exe beside it (a uv or venv Python is not Dad's)"
    owner = windows_desktop.port_owner(port)
    if owner is not None:
        return f"port {port} is held by pid {owner}: Dad's port must be free; never drive a Centrum this run did not start"
    return None


def _doctor(run: Run, when: str) -> None:
    verdict = windows_doctor.diagnose(run.root)
    (run.evidence / f"doctor-{when}.txt").write_text(verdict + "\n", encoding="utf-8")
    run.check(verdict.startswith("DOCTOR OK"), f"doctor after {when}: {verdict}")


def _drive(run: Run, page: Page, feature: str) -> None:
    if feature == "instalacja":
        instalacja.drive(run)
    elif feature == "komunikat-startu":
        komunikat_startu.drive(run)
    elif feature == "start-skrotem":
        start_skrotem.drive(run, page)
        _doctor(run, "start-skrotem")
    elif feature == "wskazanie-folderow":
        wskazanie_folderow.drive(run, page)
    elif feature == "aktualizacja":
        aktualizacja.drive(run, page)
        _doctor(run, "aktualizacja")


def _plan(feature: str) -> tuple[list[str], list[str]]:
    """Features driven as preparation, then the features verified."""

    if feature == "all":
        return [], list(FEATURES)
    return list(PREREQUISITES[feature]), [feature]


def _keep_state(run: Run) -> None:
    state = run.evidence / "state"
    for source, name in (
        (run.log, "centrum-rozliczen.log"),
        (run.tool / "config" / "centrum-ustawienia.yaml", "centrum-ustawienia.yaml"),
        (Path(run.facts["opened"]), "otwarte-adresy.txt"),
        (run.root / windows_tool.FACTS, windows_tool.FACTS),
    ):
        if source.is_file():
            shutil.copy2(source, state / name)
    if (run.tool / ".git").is_dir():
        (state / "git-log.txt").write_text(run.git("log", "--oneline", "-5") + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_run_dir()
    parser.add_argument("--feature", choices=("all", *FEATURES), default="all")
    args = parser.parse_args(argv)
    # The harness's own output is UTF-8 whatever the code page; Centrum keeps the machine's.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    paths = new_run(args.run_dir, f"windows-{run_id}")
    root, evidence = paths.root, paths.evidence
    prepared, verified = _plan(args.feature)
    failure: str | None = None
    with _teed(evidence / "drive.txt"):
        problem = _preflight(windows_tool.PORT)
        if problem is not None:
            print(f"VERIFY FAIL | preflight | {problem} | evidence={evidence}", flush=True)
            return 1
        try:
            facts = windows_tool.prepare(root)
            print(f"PREPARED | root={root} | tool={facts['tool']} | versions={facts['versions']}", flush=True)
            os.environ.update(windows_tool.boundaries(facts))
            run = Run(root, evidence)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="pl-PL")
                page = context.new_page()
                try:
                    for feature in prepared:
                        print(f"PRZYGOTOWANIE {feature}", flush=True)
                        _drive(run, page, feature)
                    for feature in verified:
                        print(f"FEATURE {feature}", flush=True)
                        _drive(run, page, feature)
                except Exception:
                    try:
                        page.screenshot(path=str(evidence / "screenshots" / "zz-failure.png"), full_page=True)
                        windows_desktop.screenshot(evidence / "pulpit" / "zz-failure.png")
                    except Exception as capture_failure:  # noqa: BLE001 - the failure below is the verdict
                        print(f"  (no failure capture: {capture_failure})", flush=True)
                    raise
                finally:
                    browser.close()
        except Exception as error:  # noqa: BLE001 - every failure becomes the VERIFY FAIL verdict
            traceback.print_exc(file=sys.stdout)
            failure = f"{type(error).__name__}: {error}"
        finally:
            if (root / windows_tool.FACTS).is_file():
                try:
                    _keep_state(Run(root, evidence))
                except Exception as keep_failure:  # noqa: BLE001 - state is evidence, not the verdict
                    print(f"  (state not kept: {keep_failure})", flush=True)
            cleaned = windows_cleanup.cleanup(root)
            (evidence / "cleanup.txt").write_text(cleaned + "\n", encoding="utf-8")
            print(cleaned, flush=True)
        scratch_removed = not root.exists()
        kept = (evidence / "drive.txt").is_file()
        if failure is None and scratch_removed and kept:
            print(
                f"VERIFY OK | features={','.join(verified)} | przygotowanie={','.join(prepared) or '-'} "
                f"| evidence={evidence} | scratch_removed=true",
                flush=True,
            )
            return 0
        print(
            f"VERIFY FAIL | {failure or 'cleanup'} | evidence={evidence} | scratch_removed={str(scratch_removed).lower()}",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
