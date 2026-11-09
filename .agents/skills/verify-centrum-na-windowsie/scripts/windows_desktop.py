"""Dad's Windows desktop as the drive sees it: native windows, processes, the port owner, and screenshots.

Native windows (the start problem's message box, the tkinter pickers, Explorer) are found and answered through
user32 with ctypes, by window class, title and owning process, never by coordinates. Processes and the port owner
come from PowerShell (``Get-CimInstance Win32_Process``, ``Get-NetTCPConnection``), so the drive needs no library
beyond Playwright. Every function works only on Windows.
"""

from __future__ import annotations

from collections.abc import Iterable
import ctypes
import functools
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

DIALOG = "#32770"  # a message box and the Vista file dialog of tkinter
EXPLORER = "CabinetWClass"
CONSOLE = "ConsoleWindowClass"
# Control ids of the file dialog: the box around its file name and the button that confirms it.
_FILE_NAME_BOX = 1148
_CONFIRM = 1
# Bands of the file dialog whose edits are not the name box: the address bar and the search box.
_BANDS = frozenset({"Address Band Root", "Breadcrumb Parent", "ReBarWindow32", "UniversalSearchBand", "SearchEditBoxWrapperClass"})

_WM_SETTEXT = 0x000C
_WM_GETTEXT = 0x000D
_WM_GETTEXTLENGTH = 0x000E
_WM_CLOSE = 0x0010
_BM_CLICK = 0x00F5


@dataclass(frozen=True)
class Window:
    handle: int
    pid: int
    cls: str
    title: str


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    name: str
    executable: str
    command_line: str


@functools.cache
def _user32() -> Any:
    """user32 with the argument types of every function the drive calls, so 64-bit handles pass intact."""

    if sys.platform != "win32":
        raise RuntimeError("Native windows exist only on Windows.")
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handle, text, number = wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
    signatures: dict[str, tuple[list[Any], Any]] = {
        "IsWindowVisible": ([handle], wintypes.BOOL),
        "IsWindow": ([handle], wintypes.BOOL),
        "GetWindowThreadProcessId": ([handle, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        "GetClassNameW": ([handle, text, number], number),
        "SendMessageW": ([handle, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
        "PostMessageW": ([handle, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        "GetDlgCtrlID": ([handle], number),
        "GetDlgItem": ([handle, number], handle),
        "GetParent": ([handle], handle),
        "GetWindow": ([handle, wintypes.UINT], handle),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(user32, name)
        function.argtypes = arguments
        function.restype = result
    return user32


def _children_or_windows(parent: int | None) -> list[int]:
    if sys.platform != "win32":
        raise RuntimeError("Native windows exist only on Windows.")
    from ctypes import wintypes

    user32 = _user32()
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(handle: int, _: int) -> bool:
        found.append(int(handle or 0))
        return True

    callback = callback_type(collect)
    if parent is None:
        user32.EnumWindows(callback, 0)
    else:
        user32.EnumChildWindows(wintypes.HWND(parent), callback, 0)
    return found


def _describe(handle: int) -> Window:
    if sys.platform != "win32":
        raise RuntimeError("Native windows exist only on Windows.")
    from ctypes import wintypes

    user32 = _user32()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(handle, name, 256)
    return Window(handle, int(pid.value), name.value, text_of(handle))


def text_of(handle: int) -> str:
    """The window's text through ``WM_GETTEXT``, which also reads controls of another process."""

    if sys.platform != "win32":
        raise RuntimeError("Native windows exist only on Windows.")
    user32 = _user32()
    length = int(user32.SendMessageW(handle, _WM_GETTEXTLENGTH, 0, 0))
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(handle, _WM_GETTEXT, length + 1, ctypes.addressof(buffer))
    return buffer.value


def visible_windows(pids: Iterable[int] | None = None) -> list[Window]:
    """Visible top-level windows, only of ``pids`` when given."""

    user32 = _user32()
    wanted = None if pids is None else set(pids)
    windows = []
    for handle in _children_or_windows(None):
        if not user32.IsWindowVisible(handle):
            continue
        window = _describe(handle)
        if wanted is None or window.pid in wanted:
            windows.append(window)
    return windows


def controls(window: Window) -> list[Window]:
    """Every descendant control of ``window`` with its class and text."""

    return [_describe(handle) for handle in _children_or_windows(window.handle)]


def wait_until_gone(window: Window, *, timeout_s: float) -> bool:
    user32 = _user32()
    deadline = time.monotonic() + timeout_s
    while user32.IsWindow(window.handle):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    return True


def close(window: Window) -> None:
    """``WM_CLOSE``: what the title bar's X does; a message box with only OK closes as OK."""

    _user32().PostMessageW(window.handle, _WM_CLOSE, 0, 0)


def _ancestors(handle: int, dialog: int) -> list[tuple[str, int]]:
    user32 = _user32()
    chain = []
    ancestor = user32.GetParent(handle)
    while ancestor and int(ancestor) != dialog:
        chain.append((_describe(int(ancestor)).cls, int(user32.GetDlgCtrlID(ancestor))))
        ancestor = user32.GetParent(ancestor)
    return chain


def _name_box(dialog: Window) -> Window:
    """The box where Dad types a name or a path: ``File name`` (inside control 1148) or ``Folder`` in a folder dialog.

    The address bar and the search box are edits too, inside their own bands; they are never the name box.
    """

    user32 = _user32()
    candidates = []
    for control in controls(dialog):
        if control.cls != "Edit" or not user32.IsWindowVisible(control.handle):
            continue
        chain = _ancestors(control.handle, dialog.handle)
        if any(cls in _BANDS for cls, _ in chain):
            continue
        candidates.append((0 if any(ident == _FILE_NAME_BOX for _, ident in chain) else 1, control))
    if not candidates:
        described = [(c.cls, int(user32.GetDlgCtrlID(c.handle)), c.title) for c in controls(dialog)]
        raise LookupError(f"The dialog {dialog.title!r} has no name box; its controls: {described}")
    return min(candidates, key=lambda candidate: candidate[0])[1]


def answer_file_dialog(dialog: Window, name: str) -> None:
    """Types ``name`` (a full path) into the dialog's name box and presses its confirm button, as Dad would."""

    if sys.platform != "win32":
        raise RuntimeError("Native windows exist only on Windows.")
    user32 = _user32()
    box = _name_box(dialog)
    text = ctypes.create_unicode_buffer(name)
    user32.SendMessageW(box.handle, _WM_SETTEXT, 0, ctypes.addressof(text))
    confirm = user32.GetDlgItem(dialog.handle, _CONFIRM)
    if not confirm:
        raise LookupError(f"The dialog {dialog.title!r} has no confirm button.")
    user32.PostMessageW(confirm, _BM_CLICK, 0, 0)


def ansi_code_page() -> int:
    """The system's ANSI code page (Dad's Polish Windows: 1250), which ``WScript.Shell`` uses for shortcut paths."""

    if sys.platform != "win32":
        raise RuntimeError("Code pages exist only on Windows.")
    return int(ctypes.WinDLL("kernel32").GetACP())


def _powershell(script: str, environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        env=os.environ | (environment or {}),
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


_UTF8 = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; "


def processes() -> list[Process]:
    output = _powershell(
        _UTF8 + "@(Get-CimInstance Win32_Process | ForEach-Object { @{pid=[int]$_.ProcessId; "
        "parent=[int]$_.ParentProcessId; name=[string]$_.Name; executable=[string]$_.ExecutablePath; "
        "command_line=[string]$_.CommandLine} }) | ConvertTo-Json -Compress -Depth 2"
    )
    rows = json.loads(output or "[]")
    return [Process(row["pid"], row["parent"], row["name"], row["executable"], row["command_line"]) for row in rows]


def processes_mentioning(text: str) -> list[Process]:
    needle = text.lower()
    return [process for process in processes() if needle in process.command_line.lower() and process.pid != os.getpid()]


def port_owner(port: int) -> int | None:
    """The pid listening on ``port``, or ``None``."""

    output = _powershell(
        f"@(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
        "ForEach-Object { [int]$_.OwningProcess }) | ConvertTo-Json -Compress"
    ).strip()
    owners = json.loads(output) if output else []
    owners = owners if isinstance(owners, list) else [owners]
    return int(owners[0]) if owners else None


def stop(pid: int) -> None:
    _powershell(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")


def start_shortcut(link: Path) -> None:
    """Opens the ``.lnk`` like Dad's double click: the shell starts its target in this process's environment."""

    if sys.platform != "win32":
        raise RuntimeError("Shortcuts start only on Windows.")
    os.startfile(link)


def read_shortcut(link: Path) -> dict[str, str]:
    output = _powershell(
        _UTF8 + "$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SKROT); "
        "@{TargetPath=$l.TargetPath; Arguments=$l.Arguments; WorkingDirectory=$l.WorkingDirectory; "
        "IconLocation=$l.IconLocation} | ConvertTo-Json -Compress",
        {"SKROT": str(link)},
    )
    shortcut = json.loads(output)
    assert isinstance(shortcut, dict)
    return {str(key): str(value) for key, value in shortcut.items()}


def screenshot(path: Path) -> None:
    """The whole desktop as Dad sees it, with native windows that a browser screenshot cannot show."""

    path.parent.mkdir(parents=True, exist_ok=True)
    _powershell(
        "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
        "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
        "$i = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($i); "
        "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $i.Size); "
        "$i.Save($env:ZRZUT, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $i.Dispose()",
        {"ZRZUT": str(path)},
    )
