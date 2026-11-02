"""Microsoft Excel for Mac through AppleScript: open a workbook without any dialog, read and type cells, save, close.

Used as a module by ``run_excel_verification.py`` and ``excel_doctor.py``, and as a command for cleanup:

    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py status
    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py close-under --root DESK_DIRECTORY

Excel is sandboxed. A file outside its container opened from AppleScript waits on the sandbox "Otwórz"
panel; opened through Finder (``open -a``) it asks whether to update external links. Both wait for a
human. A workbook on the desk (``DESK``, inside Excel's own container) opened from AppleScript with
``update links do not update links`` asks nothing, so every workbook this skill drives sits on the desk.

Every workbook is addressed by its full path, never by position, so the user's own workbooks in the same
Excel are never read, changed, or closed. Calls name addresses and counts, never a cell value.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import Parser

APP = "Microsoft Excel"
BUNDLE_ID = "com.microsoft.Excel"
DESK = Path.home() / "Library" / "Containers" / BUNDLE_ID / "Data" / "maximiseart-weryfikacja"
# One Excel per Mac, so one lock per Mac beside every worktree's desks, never inside a worktree.
LOCK = DESK / "excel.lock"
WINDOWS_SCRIPT = Path(__file__).with_name("excel_windows.js")
EVENT_TIMEOUT_SECONDS = 60
# Excel answers "missing value" for its workbooks while a modal dialog (repair, links, same name) is up.
DIALOG_ANSWER = "missing value"

ENCODE = """
on enc(v)
  if v is missing value then return "m:"
  set c to class of v
  if c is real or c is integer then return "n:" & (v as text)
  if c is date then return "d:" & (v as «class isot» as string)
  if c is boolean then return "b:" & (v as text)
  return "s:" & (v as text)
end enc

on findBook(p)
  tell application "Microsoft Excel"
    repeat with i from 1 to count of workbooks
      if full name of workbook i is p then return workbook i
    end repeat
  end tell
  error "workbook not open" number 4001
end findBook
"""

SEPARATOR_CELL = "\x1f"
SEPARATOR_ROW = "\x1e"


class ExcelError(RuntimeError):
    """Excel did not do what was asked."""


class ExcelDialog(ExcelError):
    """Excel shows a modal dialog (repair, external links, same name) and answers no workbook calls."""


class ExcelNotPermitted(ExcelError):
    """macOS does not let the app running the agent control Excel (Automatyzacja)."""


class ExcelBusy(ExcelError):
    """Another verification run drives this Mac's Excel."""


AUTOMATION_SETTING = "System Settings → Prywatność i ochrona → Automatyzacja"
APPLESCRIPT_ERRORS: dict[int, tuple[type[ExcelError], str]] = {
    -1712: (ExcelDialog, "Excel did not answer within {timeout} s (AppleEvent timeout -1712): a dialog is up or Excel is busy"),
    -1708: (ExcelDialog, "Excel refuses AppleScript calls (-1708), as it does while a modal dialog is up"),
    -1743: (
        ExcelNotPermitted,
        f"macOS denies control of Microsoft Excel (-1743): switch Microsoft Excel on for the app running the agent "
        f"in {AUTOMATION_SETTING}",
    ),
}
APPLESCRIPT_ERROR_NUMBER = re.compile(r"\((-\d+)\)$")


@dataclass(frozen=True)
class Cell:
    """One cell as Excel holds it: kind ``n`` number, ``s`` text, ``d`` date (ISO), ``b`` boolean, ``m`` empty."""

    kind: str
    text: str

    @property
    def number(self) -> float:
        if self.kind != "n":
            raise ExcelError(f"cell is {self.kind}, not a number")
        return float(self.text.replace(",", "."))

    @property
    def empty(self) -> bool:
        return self.kind == "m" or (self.kind == "s" and self.text == "")


def _osascript(script: str, *arguments: str, timeout: int = EVENT_TIMEOUT_SECONDS) -> str:
    wrapped = f"{ENCODE}\non run argv\nwith timeout of {timeout} seconds\n{script}\nend timeout\nend run\n"
    try:
        completed = subprocess.run(
            ["osascript", "-", *arguments],
            input=wrapped,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout + 15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExcelDialog(f"Excel did not answer within {timeout} s") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip()
        last_line = message.splitlines()[-1] if message else f"osascript exit {completed.returncode}"
        number = APPLESCRIPT_ERROR_NUMBER.search(last_line)
        known = APPLESCRIPT_ERRORS.get(int(number.group(1))) if number else None
        if known is None:
            raise ExcelError(last_line)
        error, text = known
        raise error(text.format(timeout=timeout))
    return completed.stdout.rstrip("\n")


def running() -> bool:
    result = subprocess.run(
        ["osascript", "-e", f'return application id "{BUNDLE_ID}" is running'],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() == "true"


def installed_version() -> str | None:
    plist = Path("/Applications/Microsoft Excel.app/Contents/Info.plist")
    if not plist.is_file():
        return None
    result = subprocess.run(
        ["defaults", "read", str(plist), "CFBundleShortVersionString"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or None


def open_paths(timeout: int = 10) -> list[str]:
    """Full paths of every workbook open in Excel; raises ``ExcelDialog`` while a modal dialog is up."""

    output = _osascript(
        """
tell application "Microsoft Excel"
  set out to ""
  repeat with i from 1 to count of workbooks
    set out to out & (full name of workbook i) & linefeed
  end repeat
  return out
end tell
""",
        timeout=timeout,
    )
    if output.strip() == DIALOG_ANSWER:
        raise ExcelDialog("Excel answers 'missing value' for its workbooks: a modal dialog is up")
    return [line for line in output.splitlines() if line]


def windows() -> list[str]:
    """Excel's on-screen windows as ``layer | title | WxH``; a dialog has no title.

    Titles need Screen Recording for the app running the agent; without it every window comes back untitled.
    """

    completed = subprocess.run(
        ["osascript", "-l", "JavaScript", str(WINDOWS_SCRIPT)], capture_output=True, text=True, check=False
    )
    return [line for line in completed.stdout.splitlines() if line]


def dialogs() -> list[str]:
    """Excel windows without a title: alerts and sheets such as repair, external links, or the Otwórz panel."""

    panels = {"Otwórz", "Open"}
    return [window for window in windows() if window.split(" | ")[1] in ("", *panels)]


def open_file(path: Path, *, timeout: int = 180) -> float:
    """Open a workbook from the desk without updating its links; returns the seconds Excel took.

    A modal dialog makes Excel miss the deadline; the ``ExcelDialog`` then names Excel's untitled windows.
    """

    if not path.is_relative_to(DESK):
        raise ExcelError(f"{path.name} is not on the desk {DESK}; Excel would wait on its sandbox panel")
    if str(path) in _open_paths_quietly():
        raise ExcelError(f"{path.name} is already open in Excel")
    started = time.monotonic()
    try:
        opened = _osascript(
            """
tell application "Microsoft Excel"
  set wb to open workbook workbook file name (item 1 of argv) update links do not update links
  return full name of wb
end tell
""",
            str(path),
            timeout=timeout,
        )
    except ExcelDialog as exc:
        raise ExcelDialog(f"{path.name}: {exc}; Excel dialogs: {dialogs() or 'none on screen'}") from exc
    if opened != str(path):
        raise ExcelError(f"Excel opened {Path(opened).name} instead of {path.name}")
    return round(time.monotonic() - started, 1)


def _open_paths_quietly() -> list[str]:
    if not running():
        return []
    try:
        return open_paths()
    except ExcelError:
        return []


def pid() -> int | None:
    """Process id of Excel, or ``None`` when no Excel runs; raises ``ExcelError`` unless ``pgrep`` names one process.

    ``pgrep`` prints one id per line. ``lsappinfo`` changed its output in macOS 27.2 (``pid = 733 !cgsConnection …``),
    and its old parser found no id, so every cold start waited out the limit of ``launch`` (#780).
    """

    completed = subprocess.run(["pgrep", "-x", APP], capture_output=True, text=True, check=False)
    ids = completed.stdout.split()
    if completed.returncode == 1 and not ids:
        return None
    if completed.returncode != 0 or len(ids) != 1 or not ids[0].isdigit():
        raise ExcelError(f"pgrep -x {APP!r} exited {completed.returncode} with {ids}, not one process id")
    return int(ids[0])


def rss_mb() -> int | None:
    """Resident memory of Excel's process in MB, or ``None`` when Excel is not running.

    One Excel process grows with every workbook it opened and closed (2.4 GB to 4.2 GB with no workbook open
    within 1.5 hours of runs on 2026-10-24, and it hung at about 10 GB), so runs record it before and after.
    A note only: ``None`` also when Excel's process is not known (``pid`` raises).
    """

    try:
        process_id = pid()
    except ExcelError:
        return None
    if process_id is None:
        return None
    completed = subprocess.run(["ps", "-o", "rss=", "-p", str(process_id)], capture_output=True, text=True, check=False)
    kilobytes = completed.stdout.strip()
    return round(int(kilobytes) / 1024) if kilobytes.isdigit() else None


def launch(*, timeout: float = 90) -> int:
    """Start Excel without restoring windows of an earlier session; returns its process id.

    After Excel was stopped with workbooks open, macOS reopens them at the next start, and each one may
    ask about its links. ``-ApplePersistenceIgnoreState YES`` starts Excel empty.
    """

    subprocess.run(["open", "-g", "-a", APP, "--args", "-ApplePersistenceIgnoreState", "YES"], check=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            open_paths(timeout=5)
        except ExcelNotPermitted:
            raise
        except ExcelError:
            continue
        process_id = pid()
        if process_id is not None:
            return process_id
    raise ExcelDialog(f"Excel did not answer within {timeout:.0f} s of starting; dialogs: {dialogs()}")


def claim(*, owner: str) -> TextIO:
    """Hold this Mac's Excel for one run until the returned file is closed or the process ends.

    The lock is an ``flock``, which the kernel drops when its process dies, so a killed run blocks no one.
    The file keeps the last holder's pid and ``owner`` for the refusal message.
    """

    if sys.platform == "win32":
        raise ExcelError("this skill drives Excel for Mac")
    # Imported here, so the module imports on Windows, where the cleanup tests run in CI's mutation job.
    import fcntl

    if not DESK.parent.is_dir():
        raise ExcelError(f"Excel's container {DESK.parent} does not exist; start Excel once by hand")
    DESK.mkdir(exist_ok=True)
    handle = LOCK.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        holder = handle.read().strip() or "holder unknown"
        handle.close()
        raise ExcelBusy(f"another Excel verification drives this Mac's Excel ({holder})") from None
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid {os.getpid()}, {owner}")
    handle.flush()
    return handle


def terminate(process_id: int) -> bool:
    """Stop the Excel this run started when a dialog keeps it from quitting; returns whether it ended.

    The stop leaves its windows in macOS's saved state, so Excel is started once more without them and
    quit normally, and the next start, also by Dad's double click, opens nothing of this run.
    """

    if pid() != process_id:
        return False
    os.kill(process_id, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while running() and time.monotonic() < deadline:
        time.sleep(0.5)
    if running():
        return False
    launch()
    return quit_if_idle()


def read(path: Path, address: str, *, sheet: int = 1) -> list[list[Cell]]:
    """Values of a rectangular range, row by row, as Excel holds them after its own calculation."""

    output = _osascript(
        f"""
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  set v to value of range (item 2 of argv) of worksheet {sheet} of wb
end tell
if class of v is not list then set v to {{{{v}}}}
set rowsOut to {{}}
repeat with r in v
  set cellsOut to {{}}
  repeat with x in r
    set end of cellsOut to enc(contents of x)
  end repeat
  set AppleScript's text item delimiters to (character id 31)
  set end of rowsOut to cellsOut as text
end repeat
set AppleScript's text item delimiters to (character id 30)
return rowsOut as text
""",
        str(path),
        address,
    )
    return [
        [Cell(item[0], item[2:]) for item in row.split(SEPARATOR_CELL)]
        for row in output.split(SEPARATOR_ROW)
    ]


def formulas_r1c1(path: Path, address: str, *, sheet: int = 1) -> list[str]:
    """Formulas of a one-row range in R1C1 notation, so rows of the same formula compare equal."""

    output = _osascript(
        f"""
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  set f to formula r1c1 of range (item 2 of argv) of worksheet {sheet} of wb
end tell
if class of f is not list then set f to {{{{f}}}}
set AppleScript's text item delimiters to (character id 31)
return (item 1 of f) as text
""",
        str(path),
        address,
    )
    return output.split(SEPARATOR_CELL)


def error_cells(path: Path, address: str, *, sheet: int = 1) -> str | None:
    """Address of every cell in ``address`` that Excel shows as an error (#N/D, #ARG!, …), or ``None``."""

    output = _osascript(
        f"""
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  set ws to worksheet {sheet} of wb
  try
    set found to special cells (range (item 2 of argv) of ws) type cell type formulas value errors
    return get address of found
  on error number n
    return ""
  end try
end tell
""",
        str(path),
        address,
    )
    return output or None


def link_names(path: Path) -> list[str]:
    """File names of the external workbooks Excel links this workbook to."""

    output = _osascript(
        """
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  set ls to link sources wb type link type Excel links
end tell
if ls is missing value then return ""
if class of ls is not list then set ls to {ls}
set AppleScript's text item delimiters to linefeed
return ls as text
""",
        str(path),
    )
    return [line.replace("\\", "/").rsplit("/", 1)[-1] for line in output.splitlines() if line]


def fill(path: Path, address: str, *, sheet: int = 1) -> tuple[int, int, bool, bool]:
    """Interior color, font color, bold, italic of one cell, as Excel shows it."""

    output = _osascript(
        f"""
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  set r to range (item 2 of argv) of worksheet {sheet} of wb
  set ic to color of interior object of r
  set fc to color of font object of r
  set b to bold of font object of r
  set itl to italic of font object of r
end tell
set AppleScript's text item delimiters to ","
return ({{(item 1 of ic) * 65536 + (item 2 of ic) * 256 + (item 3 of ic), (item 1 of fc) * 65536 + (item 2 of fc) * 256 + (item 3 of fc), b, itl}}) as text
""",
        str(path),
        address,
    )
    interior, font, bold, italic = output.split(",")
    return int(interior), int(font), bold == "true", italic == "true"


def row_heights(path: Path, first: int, last: int, *, sheet: int = 1) -> list[float]:
    """Height in points of rows ``first``..``last`` as Excel lays them out, after its own auto-fit."""

    output = _osascript(
        f"""
set wb to findBook(item 1 of argv)
set hs to {{}}
tell application "Microsoft Excel"
  set ws to worksheet {sheet} of wb
  repeat with r from ({first}) to ({last})
    set end of hs to (row height of row r of ws) as text
  end repeat
end tell
set AppleScript's text item delimiters to (character id 31)
return hs as text
""",
        str(path),
    )
    return [float(height.replace(",", ".")) for height in output.split(SEPARATOR_CELL)]


def standard_height(path: Path, *, sheet: int = 1) -> float:
    """Height in points of a row with one line of text in the sheet's default font, as Excel computes it."""

    output = _osascript(
        f"""
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  return (standard height of worksheet {sheet} of wb) as text
end tell
""",
        str(path),
    )
    return float(output.replace(",", "."))


def shown_text(path: Path, address: str, *, sheet: int = 1) -> str:
    """The value of one cell as text in its number format (Excel's ``string value``; a too narrow column's ``#####``
    does not show here)."""

    return _osascript(
        f"""
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  return string value of range (item 2 of argv) of worksheet {sheet} of wb
end tell
""",
        str(path),
        address,
    )


def type_row(path: Path, address: str, texts: list[str], *, sheet: int = 1) -> None:
    """Enter one row of cells like typing them: Excel parses each text itself, then recalculates once.

    Numbers use a decimal point (``formula`` is Excel's English input, as in VBA), so ``"25.5"`` is a number
    whatever the system locale; text that is not a number stays text. One range per call, because every
    entry recalculates the workbook, and Dad's Wzorce hold some 50 000 formulas.
    """

    _osascript(
        f"""
set wb to findBook(item 1 of argv)
set texts to items 3 thru -1 of argv
tell application "Microsoft Excel"
  set formula of range (item 2 of argv) of worksheet {sheet} of wb to {{texts}}
end tell
return ""
""",
        str(path),
        address,
        *texts,
        timeout=180,
    )


def save(path: Path) -> None:
    """Save like Cmd+S. ``save wb`` from AppleScript silently does nothing; ``tell wb to save`` saves."""

    output = _osascript(
        """
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  tell wb to save
  return saved of wb
end tell
""",
        str(path),
    )
    if output != "true":
        raise ExcelError(f"{path.name} still has unsaved changes after saving")


def close(path: Path, *, timeout: float = 30) -> None:
    """Close without saving and wait until Excel removed its ``~$`` lock file."""

    _osascript(
        """
set wb to findBook(item 1 of argv)
tell application "Microsoft Excel"
  tell wb to close saving no
end tell
return ""
""",
        str(path),
    )
    lock = path.with_name(f"~${path.name}")
    deadline = time.monotonic() + timeout
    while lock.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    if lock.exists():
        raise ExcelError(f"{lock.name} still exists after closing")


def close_under(root: Path) -> list[str]:
    """Close, without saving, every workbook below ``root``; returns their file names.

    Raises ``ExcelDialog`` while a dialog keeps Excel from listing its workbooks, so a caller never takes
    "nothing closed" for "nothing open".
    """

    closed: list[str] = []
    for full_path in open_paths() if running() else []:
        candidate = Path(full_path)
        if candidate.is_relative_to(root):
            close(candidate)
            closed.append(candidate.name)
    return closed


def quit_if_idle() -> bool:
    """Quit Excel only when it answers and holds no workbook at all; returns whether it quit.

    Excel behind a dialog hides its workbooks, so it stays, as does Excel with any workbook, the user's too.
    """

    if not running():
        return False
    try:
        held = open_paths()
    except ExcelError:
        return False
    if held:
        return False
    _osascript('tell application "Microsoft Excel" to quit\nreturn ""')
    deadline = time.monotonic() + 30
    while running() and time.monotonic() < deadline:
        time.sleep(0.5)
    return not running()


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="say whether Excel runs, answers, and how many workbooks it holds")
    closer = commands.add_parser("close-under", help="close every workbook below a run root, without saving")
    closer.add_root("directory whose workbooks Excel closes")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            if not running():
                print(f"EXCEL not running | version={installed_version()}")
                return 0
            print(f"EXCEL running | version={installed_version()} | workbooks={len(open_paths())}")
            return 0
        names = close_under(args.root)
        print(f"EXCEL CLOSED | workbooks={len(names)}")
        return 0
    except ExcelError as exc:
        print(f"EXCEL FAIL | {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
