"""Jednorazowy krok instalacji: skrót „Centrum rozliczeń” z ikoną na pulpicie taty i w jego Autostarcie Windows.

Skrót uruchamia ``run_centrum.py`` przez ``pythonw.exe`` tego samego Pythona,
którym zainstalowano zależności (``py -3``), więc Centrum startuje bez okna
konsoli. Skrót w Autostarcie (``shell:startup``) dodaje flagę ``--no-browser``:
po zalogowaniu taty Centrum startuje bez karty, żeby Przypomnienia o raporcie
szły bez jego kliknięcia (ADR 0030), a skrót z pulpitu otwiera kartę.
Skrót zapisuje PowerShell przez WScript.Shell, bez dodatkowych bibliotek, a
folder pulpitu i Autostartu podaje API Windows (``SHGetFolderPathW``). Ścieżki
trafiają do PowerShella w zmiennych środowiskowych, nie w treści skryptu, więc
spacje i polskie znaki nie wymagają cytowania. WScript.Shell zapisuje ścieżkę
skrótu w stronie kodowej ANSI systemu (u taty 1250, na angielskim Windows 1252
bez „ń”), więc PowerShell zapisuje skrót pod nazwą ASCII, a Python przenosi go
pod nazwę ``Centrum rozliczeń.lnk``; folder skrótu nadal musi dać się zapisać w
tej stronie kodowej, inaczej zapis kończy się błędem, nie innym plikiem.
Ponowne uruchomienie kroku nadpisuje oba skróty, np. po przeniesieniu folderu
narzędzia, a nie dokłada nowych.

Przełącznik „Uruchamiaj Centrum razem z Windows” w Ustawieniach Centrum zakłada
albo usuwa ten sam skrót z Autostartu (``StartupShortcut``), a jego stan to
obecność pliku skrótu, więc skrót usunięty ręcznie Centrum widzi jako wyłączony. Plik pośredni zapisu, który zostaje,
gdy Centrum zgaśnie w trakcie PowerShella, odczyt stanu usuwa, bo Windows uruchomiłby z niego Centrum przy stanie „off”.
Centrum ze skrótu działa pod ``pythonw``, więc PowerShell biegnie przez
``platform.run_console_program``: bez okna konsoli i z limitem czasu, bo zapis
skrótu trzyma blokadę Ustawień.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import IntEnum
import os
from pathlib import Path
import subprocess
import sys

from rozliczenia.centrum.platform import NO_AUTOSTART, Autostart, AutostartState, ConsoleRun, run_console_program
from rozliczenia.file_state import file_state
from rozliczenia.message import refer_if
from rozliczenia.tool_files import NO_BROWSER_FLAG, TOOL_ROOT, centrum_script

SHORTCUT_NAME = "Centrum rozliczeń"
SHORTCUT_FILE = f"{SHORTCUT_NAME}.lnk"
ICON = Path(__file__).resolve().parent / "centrum-rozliczen.ico"
_WRITTEN_NAME = "Centrum rozliczen (zapis).lnk"
"""Nazwa, pod którą WScript.Shell zapisuje skrót: sam ASCII, więc ta sama w każdej stronie kodowej ANSI."""
_POWERSHELL_TIMEOUT_S = 30.0
"""PowerShell z WScript.Shell zapisuje skrót w kilka sekund; zawieszony nie trzyma blokady Ustawień dłużej niż tyle."""


class Folder(IntEnum):
    """Folder Windows skrótu; wartość to jego numer CSIDL w ``SHGetFolderPathW``."""

    DESKTOP = 0x0010
    """``CSIDL_DESKTOPDIRECTORY``, ten sam folder co ``Environment.GetFolderPath('Desktop')``."""
    STARTUP = 0x0007
    """``CSIDL_STARTUP``, czyli ``shell:startup``."""


def shortcut_file(folder: Path) -> Path:
    """Plik skrótu „Centrum rozliczeń” w ``folder``: ten sam dla zapisu, stanu przełącznika i usuwania."""

    return folder / SHORTCUT_FILE


def _written_file(folder: Path) -> Path:
    """Plik pośredni zapisu skrótu w ``folder``: zostaje po nim, gdy Centrum zgaśnie w trakcie PowerShella, który
    potem kończy ``Save()``, a Windows uruchamia Centrum także z niego."""

    return folder / _WRITTEN_NAME


@dataclass(frozen=True)
class Shortcut:
    """Skrót, który zakłada krok instalacji: jego folder i argumenty ``pythonw.exe``."""

    folder: Folder
    arguments: tuple[str, ...]


def shortcuts(root: Path) -> tuple[Shortcut, ...]:
    """Skróty kroku instalacji dla klonu narzędzia ``root``: z pulpitu z kartą, z Autostartu bez karty."""

    script = str(centrum_script(root))
    return (Shortcut(Folder.DESKTOP, (script,)), Shortcut(Folder.STARTUP, (script, NO_BROWSER_FLAG)))


_WHERE = {Folder.DESKTOP: "pulpit tego komputera", Folder.STARTUP: "folder Autostart tego komputera"}
_CREATED = {
    Folder.DESKTOP: "Utworzono skrót „Centrum rozliczeń”",
    Folder.STARTUP: "Utworzono skrót „Centrum rozliczeń” w Autostarcie (start po zalogowaniu, bez karty)",
}

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CENTRUM_SKROT_PLIK)
$link.TargetPath = $env:CENTRUM_SKROT_PROGRAM
$link.Arguments = $env:CENTRUM_SKROT_ARGUMENTY
$link.WorkingDirectory = $env:CENTRUM_SKROT_FOLDER_ROBOCZY
$link.IconLocation = $env:CENTRUM_SKROT_IKONA
$link.Description = $env:CENTRUM_SKROT_NAZWA
$link.Save()
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tworzy skrót „Centrum rozliczeń” na pulpicie i w Autostarcie (Windows).")
    parser.add_argument("--folder", type=Path, help="Folder skrótu z pulpitu; domyślnie pulpit.")
    parser.add_argument(
        "--folder-autostartu",
        type=Path,
        help="Folder skrótu z Autostartu; domyślnie folder Autostart Windows (shell:startup).",
    )
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("Skrót „Centrum rozliczeń” powstaje tylko na Windows. Przy rozwoju uruchom: python run_centrum.py")
        return 1
    windowless_python = _windowless_python()
    if file_state(windowless_python) != "file":
        print(
            "Co się stało: Nie utworzono skrótu, bo ten Python nie ma programu pythonw.exe.\n"
            f"Gdzie: folder {windowless_python.parent}\n"
            "Co zrobić: Zainstaluj Python ze strony python.org i uruchom ten krok ponownie."
        )
        return 1
    chosen = {Folder.DESKTOP: args.folder, Folder.STARTUP: args.folder_autostartu}
    for shortcut in shortcuts(TOOL_ROOT):
        try:
            path = _write(shortcut, windowless_python, chosen[shortcut.folder], run_console_program)
        except OSError:
            print(
                "Co się stało: Nie udało się utworzyć skrótu „Centrum rozliczeń”.\n"
                f"Gdzie: {_WHERE[shortcut.folder]}\n"
                f"Co zrobić: Uruchom ten krok ponownie. {refer_if('Jeśli komunikat wraca', request='przekaż go')}"
            )
            return 1
        print(f"{_CREATED[shortcut.folder]}: {path}")
    return 0


def _windowless_python() -> Path:
    """``pythonw.exe`` tego samego Pythona: uruchamia Centrum bez okna konsoli."""

    return Path(sys.executable).with_name("pythonw.exe")


@dataclass(frozen=True)
class StartupShortcut:
    """Autostart Windows Centrum: skrót z Autostartu kroku instalacji, ten sam program, argumenty, ikona i folder
    roboczy, więc dwa włączenia nadpisują jeden plik skrótu.

    ``folder``: folder Autostart; ``None`` to folder Autostart taty z API Windows, ten sam co w kroku instalacji.
    ``program``: program skrótu, domyślnie ``pythonw.exe`` tego Pythona. ``run``: uruchamia PowerShell, domyślnie bez
    okna konsoli i z limitem czasu.
    """

    folder: Path | None = None
    program: Path = field(default_factory=_windowless_python)
    run: ConsoleRun = run_console_program

    def state(self) -> AutostartState:
        """Stan skrótu; najpierw usuwa plik pośredni zapisu (``_written_file``), więc stan mówi, czy Windows uruchomi
        Centrum po zalogowaniu. Zapis i odczyt idą pod blokadą Ustawień, więc to nigdy nie plik trwającego zapisu, a
        ten odczyt zawsze poprzedza wyłączenie, więc ``disable`` nie sprząta pliku pośredniego drugi raz."""

        folder = self._folder()
        _written_file(folder).unlink(missing_ok=True)
        match file_state(shortcut_file(folder)):
            case "file":
                return "on"
            case "missing":
                return "off"
            case "inaccessible":
                raise OSError("Nie da się teraz sprawdzić folderu Autostart.")

    def enable(self) -> None:
        if file_state(self.program) != "file":
            raise OSError("Ten Python nie ma programu pythonw.exe.")
        [startup] = [shortcut for shortcut in shortcuts(TOOL_ROOT) if shortcut.folder is Folder.STARTUP]
        _write(startup, self.program, self._folder(), self.run)

    def disable(self) -> None:
        shortcut_file(self._folder()).unlink(missing_ok=True)

    def _folder(self) -> Path:
        return self.folder if self.folder is not None else _system_folder(Folder.STARTUP)


def system_autostart() -> Autostart:
    """Autostart tego komputera: skrót w folderze Autostart Windows albo żaden."""

    return StartupShortcut() if sys.platform == "win32" else NO_AUTOSTART


def _system_folder(folder: Folder) -> Path:
    """Pulpit albo folder Autostart taty z API Windows, jak ``Environment.GetFolderPath``."""

    if sys.platform != "win32":
        raise OSError("Pulpit i folder Autostart dla skrótu są tylko na Windows.")
    import ctypes
    from ctypes import wintypes

    path = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    if ctypes.windll.shell32.SHGetFolderPathW(None, folder.value, None, 0, path) != 0:
        raise OSError(f"Windows nie podał folderu {folder.name}.")
    return Path(path.value)


def _write(shortcut: Shortcut, windowless_python: Path, folder: Path | None, run: ConsoleRun) -> Path:
    """Zapisuje (albo nadpisuje) skrót „Centrum rozliczeń” w ``folder`` (``None``: folder systemu) i daje jego ścieżkę.

    WScript.Shell zapisuje pod nazwą ASCII, a Python przenosi plik pod ``shortcut_file``, więc nazwa nie zależy od
    strony kodowej ANSI systemu. ``OSError``, gdy PowerShell padł, przekroczył limit czasu albo plik się nie przeniósł.
    Pod nazwą ASCII nic nie zostaje: po porażce plik znika, a po udanym przeniesieniu już go tam nie ma. Każdy argument
    skrótu stoi w cudzysłowie, bo ścieżka narzędzia może mieć spację, a nazwa pliku Windows nie ma cudzysłowu.
    """

    target = shortcut_file(folder.resolve() if folder is not None else _system_folder(shortcut.folder))
    written = _written_file(target.parent)
    environment = os.environ | {
        "CENTRUM_SKROT_PLIK": str(written),
        "CENTRUM_SKROT_NAZWA": SHORTCUT_NAME,
        "CENTRUM_SKROT_PROGRAM": str(windowless_python),
        "CENTRUM_SKROT_ARGUMENTY": " ".join(f'"{argument}"' for argument in shortcut.arguments),
        "CENTRUM_SKROT_FOLDER_ROBOCZY": str(TOOL_ROOT),
        "CENTRUM_SKROT_IKONA": f"{ICON},0",
    }
    script = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", script]
    try:
        try:
            result = run(command, env=environment, timeout_s=_POWERSHELL_TIMEOUT_S)
        except subprocess.TimeoutExpired as late:
            raise OSError(f"PowerShell nie zapisał skrótu w {_POWERSHELL_TIMEOUT_S:.0f} s.") from late
        if result.returncode != 0:
            raise OSError(f"PowerShell nie zapisał skrótu (kod {result.returncode}).")
        os.replace(written, target)
    finally:
        with suppress(OSError):
            written.unlink(missing_ok=True)
    return target
