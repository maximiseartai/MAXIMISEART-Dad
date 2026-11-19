from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import windows_desktop

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import Parser, RunRootError, remove_run_root, require_run_root

OPIS = """Stop what one run started and remove its run root; the evidence stays.

    py -3 .agents\\skills\\verify-centrum-na-windowsie\\scripts\\windows_cleanup.py --root <run root>

Stops only processes whose command line contains the run root (Centrum from the run's tool, the restart guardian,
Git and pip below it), never by process name. Closes the Explorer windows on the run's folders. Prints
``CLEANUP OK | stopped=[…] | removed=true`` or ``CLEANUP FAIL | …``.
"""


def _remove(root: Path) -> bool:
    deadline = time.monotonic() + 30
    while root.exists():
        try:
            remove_run_root(root)
        except OSError:
            if time.monotonic() > deadline:
                return False
            time.sleep(1)  # a process that just ended may still hold a file for a moment
    return True


def cleanup(root: Path) -> str:
    if sys.platform != "win32":
        return "CLEANUP FAIL | this skill drives Windows only"
    if not root.is_dir():
        return f"CLEANUP OK | stopped=[] | removed=true | {root} did not exist"
    try:
        require_run_root(root)
    except RunRootError as error:
        return f"CLEANUP FAIL | {error}"
    own = {os.getpid(), os.getppid()}
    stopped = []
    for _ in range(3):  # the guardian may start a Centrum while the first pass stops it
        found = [process for process in windows_desktop.processes_mentioning(str(root)) if process.pid not in own]
        for process in found:
            windows_desktop.stop(process.pid)
            stopped.append(process.pid)
        if not found:
            break
        time.sleep(1)
    periods = root / "dane" / "INEA"
    names = tuple(path.name for path in periods.iterdir()) if periods.is_dir() else ()
    for window in windows_desktop.visible_windows():
        if window.cls == windows_desktop.EXPLORER and any(name in window.title for name in names):
            windows_desktop.close(window)
    try:
        removed = _remove(root)
    except RunRootError as error:
        return f"CLEANUP FAIL | stopped={sorted(set(stopped))} | {error}"
    verdict = "CLEANUP OK" if removed else "CLEANUP FAIL"
    return f"{verdict} | stopped={sorted(set(stopped))} | removed={str(removed).lower()}"


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=OPIS)
    parser.add_root("run root of this Windows run")
    verdict = cleanup(parser.parse_args(argv).root)
    print(verdict, flush=True)
    return 0 if verdict.startswith("CLEANUP OK") else 1


if __name__ == "__main__":
    raise SystemExit(main())
