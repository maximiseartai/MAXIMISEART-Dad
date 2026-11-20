from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Literal, Protocol, TextIO

FileTypes = Sequence[tuple[str, str]]


class Platform(Protocol):
    def open_path(self, path: Path) -> None:
        ...

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        ...

    def choose_folder(self, title: str) -> Path | None:
        ...


AutostartState = Literal["on", "off", "unsupported"]


class Autostart(Protocol):
    def state(self) -> AutostartState:
        ...

    def enable(self) -> None:
        ...

    def disable(self) -> None:
        ...


class _NoAutostart:
    def state(self) -> AutostartState:
        return "unsupported"

    def enable(self) -> None:
        raise OSError("Ten komputer nie ma Autostartu Windows.")

    def disable(self) -> None:
        raise OSError("Ten komputer nie ma Autostartu Windows.")


NO_AUTOSTART: Final[Autostart] = _NoAutostart()

# ZEWNĘTRZNE: program konsolowy uruchomiony przez proces bez konsoli, jak Centrum ze skrótu pod pythonw, dostaje od Windows własne okno konsoli, chyba że ma flagę CREATE_NO_WINDOW (Microsoft Learn: Creation of a Console, Process Creation Flags)
NO_CONSOLE_WINDOW: Final = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ConsoleRun(Protocol):
    def __call__(
        self, command: Sequence[str], *, timeout_s: float, cwd: Path | None = None, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        ...


def run_console_program(
    command: Sequence[str], *, timeout_s: float, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=timeout_s,
        check=False,
        creationflags=NO_CONSOLE_WINDOW,
    )


def has_console() -> bool:
    # ZEWNĘTRZNE: proces uruchomiony przez pythonw ma sys.stdout i sys.stderr równe None (dokumentacja Pythona, sys.__stdout__)
    return not any(stream is None or _null_device(stream) for stream in (sys.stdout, sys.stderr))


def _null_device(stream: TextIO) -> bool:
    try:
        descriptor = stream.fileno()
    except (OSError, ValueError):
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        # ZEWNĘTRZNE: NUL to w Windows urządzenie znakowe jak konsola, więc os.fstat ich nie odróżnia, a tryb konsoli ma tylko konsola (Microsoft Learn: GetFileType, GetConsoleMode)
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
        file_type_char = 0x0002
        kernel32 = ctypes.windll.kernel32
        return bool(
            kernel32.GetFileType(handle) == file_type_char
            and not kernel32.GetConsoleMode(handle, ctypes.byref(wintypes.DWORD()))
        )
    else:
        return os.path.samestat(os.fstat(descriptor), Path(os.devnull).stat())


def show_start_problem(title: str, text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        mb_iconerror, mb_setforeground, mb_topmost = 0x10, 0x10000, 0x40000
        ctypes.windll.user32.MessageBoxW(None, text, title, mb_iconerror | mb_setforeground | mb_topmost)
    elif sys.platform == "darwin":
        script = (
            f"display dialog {_applescript_text(text)} with title {_applescript_text(title)} "
            'buttons {"OK"} default button "OK" with icon stop'
        )
        subprocess.run(["osascript", "-e", script], capture_output=True, check=False)
    else:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        try:
            root.withdraw()
            messagebox.showerror(title, text, parent=root)
        finally:
            root.destroy()


def system_platform() -> Platform:
    if sys.platform == "darwin":
        # ZEWNĘTRZNE: tkinter na macOS otwiera okna tylko w wątku głównym, a serwer Centrum obsługuje żądania w wątkach roboczych (Apple, Threading Programming Guide: Thread Safety Summary)
        return _MacPlatform()
    else:
        return _TkPlatform()


class _TkPlatform:
    def __init__(self) -> None:
        self._dialog_lock = threading.Lock()

    def open_path(self, path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        return self._ask(
            lambda dialog, parent: dialog.askopenfilename(parent=parent, title=title, filetypes=list(filetypes))
        )

    def choose_folder(self, title: str) -> Path | None:
        return self._ask(lambda dialog, parent: dialog.askdirectory(parent=parent, title=title, mustexist=True))

    def _ask(self, ask: Callable[[ModuleType, Any], object]) -> Path | None:
        import tkinter
        from tkinter import filedialog

        with self._dialog_lock:
            root = tkinter.Tk()
            try:
                root.withdraw()
                root.attributes("-topmost", True)
                chosen = ask(filedialog, root)
            finally:
                root.destroy()
        return Path(chosen) if isinstance(chosen, str) and chosen else None


class _MacPlatform:
    def open_path(self, path: Path) -> None:
        subprocess.run(["open", str(path)], check=False)

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        return self._choose(f"choose file with prompt {_applescript_text(title)}")

    def choose_folder(self, title: str) -> Path | None:
        return self._choose(f"choose folder with prompt {_applescript_text(title)}")

    def _choose(self, command: str) -> Path | None:
        result = subprocess.run(
            ["osascript", "-e", f"POSIX path of ({command})"],
            capture_output=True,
            text=True,
            check=False,
        )
        chosen = result.stdout.strip()
        return Path(chosen) if result.returncode == 0 and chosen else None


def _applescript_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
