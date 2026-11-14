"""Akcje systemowe komputera taty za jednym adapterem: otwarcie pliku albo folderu i okna wyboru.

U taty (Windows) plik otwiera skojarzony program, czyli Excel, a okna wyboru
to okna tkinter. Przy rozwoju na macOS działają odpowiedniki
systemu: ``open`` i ``osascript``, bo tkinter na macOS działa tylko w wątku
głównym, a serwer obsługuje żądania w wątkach roboczych. Testy API podają
własny adapter do ``create_app``; serwer dostaje ``system_platform()``.

Przed startem serwera (``launcher``) są jeszcze dwie akcje systemowe:
``has_console()`` i ``show_start_problem()``, czyli natywne okienko z
komunikatem startu, gdy Centrum uruchomiono skrótem bez konsoli. Moduł używa
tylko biblioteki standardowej.

Autostart Windows to osobny port (``Autostart``): skrót „Centrum rozliczeń” w
folderze Autostart taty, który przełącznik w Ustawieniach zakłada albo usuwa.
Na Windows obsługuje go ``shortcut.StartupShortcut`` (``shortcut.system_autostart``),
a komputer bez Windows go nie ma (``NO_AUTOSTART``).
"""

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
"""Typy plików okna wyboru pliku: pary (opis, wzorzec nazwy)."""


class Platform(Protocol):
    def open_path(self, path: Path) -> None:
        """Otwiera plik w domyślnym programie (Excel) albo folder w menedżerze plików."""

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        """Natywne okno wyboru pliku; ``None``, gdy tata anulował."""

    def choose_folder(self, title: str) -> Path | None:
        """Natywne okno wyboru folderu; ``None``, gdy tata anulował."""


AutostartState = Literal["on", "off", "unsupported"]
"""Skrót Centrum w folderze Autostart jest, nie ma go albo komputer nie ma Autostartu Windows."""


class Autostart(Protocol):
    def state(self) -> AutostartState:
        """Czy skrót Centrum jest w folderze Autostart; ``OSError``, gdy folderu nie da się teraz sprawdzić."""

    def enable(self) -> None:
        """Zakłada albo nadpisuje skrót Centrum w folderze Autostart; ``OSError``, gdy się nie udało."""

    def disable(self) -> None:
        """Usuwa skrót Centrum z folderu Autostart (brak skrótu to nie błąd); ``OSError``, gdy się nie udało."""


class _NoAutostart:
    """Komputer bez Autostartu Windows: stan ``unsupported``, a zmiany nie dochodzą tu, bo odmawia ich właściciel
    Ustawień."""

    def state(self) -> AutostartState:
        return "unsupported"

    def enable(self) -> None:
        raise OSError("Ten komputer nie ma Autostartu Windows.")

    def disable(self) -> None:
        raise OSError("Ten komputer nie ma Autostartu Windows.")


NO_AUTOSTART: Final[Autostart] = _NoAutostart()

NO_CONSOLE_WINDOW: Final = getattr(subprocess, "CREATE_NO_WINDOW", 0)
"""Flaga Windows, z którą program konsolowy uruchomiony z Centrum nie otwiera tacie okna konsoli; poza Windows 0.

Centrum ze skrótu działa pod ``pythonw``, bez konsoli, więc każdy program konsolowy (PowerShell, pip, Git) dostałby
od Windows własne okno, które mignie tacie i zabierze fokus przeglądarce. Programy czekające na wynik Centrum
uruchamia przez ``run_console_program``, a ``Popen`` z innymi flagami dokłada do nich tę."""


class ConsoleRun(Protocol):
    def __call__(
        self, command: Sequence[str], *, timeout_s: float, cwd: Path | None = None, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Uruchamia program konsolowy i czeka na niego; ``subprocess.TimeoutExpired`` po ``timeout_s``."""


def run_console_program(
    command: Sequence[str], *, timeout_s: float, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Program konsolowy bez okna konsoli i bez wejścia, z wyjściem jako tekst UTF-8; wynik czyta wołający po kodzie.

    Po ``timeout_s`` zabija program i rzuca ``subprocess.TimeoutExpired``, więc zawieszony program nie trzyma
    wołającego (np. blokady Ustawień) bez końca.
    """

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
    """Czy ktoś zobaczy, co Centrum wypisze: konsola, potok albo plik.

    ``pythonw`` ze skrótu „Centrum rozliczeń” nie daje procesowi ``sys.stdout`` ani ``sys.stderr``, a opiekun
    ponownego startu daje je, ale na urządzenie puste.
    """

    return not any(stream is None or _null_device(stream) for stream in (sys.stdout, sys.stderr))


def _null_device(stream: TextIO) -> bool:
    """Czy ``stream`` pisze na urządzenie puste. Strumień bez deskryptora (np. przechwycony w testach) ktoś czyta, więc
    nie jest pusty. Na Windows NUL to urządzenie znakowe jak konsola, ale bez trybu konsoli, a ``os.fstat`` ich nie
    odróżnia."""

    try:
        descriptor = stream.fileno()
    except (OSError, ValueError):
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
        file_type_char = 0x0002
        kernel32 = ctypes.windll.kernel32
        return bool(
            kernel32.GetFileType(handle) == file_type_char
            and not kernel32.GetConsoleMode(handle, ctypes.byref(wintypes.DWORD()))
        )
    return os.path.samestat(os.fstat(descriptor), Path(os.devnull).stat())


def show_start_problem(title: str, text: str) -> None:
    """Natywne okienko błędu nad innymi oknami; wraca, gdy tata je zamknie."""

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
        return _MacPlatform()
    return _TkPlatform()


class _TkPlatform:
    """Windows u taty (Linux przy rozwoju): okna tkinter w wątku żądania, jedno naraz, nad przeglądarką."""

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
