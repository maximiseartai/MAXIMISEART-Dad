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

from rozliczenia.call_trace import exception_type
from rozliczenia.centrum.platform import NO_AUTOSTART, Autostart, AutostartState, ConsoleRun, run_console_program
from rozliczenia.file_state import file_state
from rozliczenia.message import refer_if
from rozliczenia.tool_files import NO_BROWSER_FLAG, TOOL_ROOT, centrum_script

SHORTCUT_NAME = "Centrum rozliczeń"
SHORTCUT_FILE = f"{SHORTCUT_NAME}.lnk"
ICON = Path(__file__).resolve().parent / "centrum-rozliczen.ico"
# ZEWNĘTRZNE: WScript.Shell zapisuje ścieżkę skrótu w stronie kodowej ANSI systemu, a strona angielskiego Windows (1252) nie ma „ń”, więc nazwa zapisu jest w ASCII, a znak spoza strony kodowej w folderze skrótu kończy zapis błędem (verify-centrum-na-windowsie, funkcja instalacja: GetACP na runnerze GitHuba)
_WRITTEN_NAME = "Centrum rozliczen (zapis).lnk"
_POWERSHELL_TIMEOUT_S = 30.0


# ZEWNĘTRZNE: wartość członu to numer CSIDL folderu w SHGetFolderPathW: 0x0010 to CSIDL_DESKTOPDIRECTORY, ten sam folder co Environment.GetFolderPath('Desktop'), a 0x0007 to CSIDL_STARTUP, czyli shell:startup (Microsoft Learn: CSIDL)
class Folder(IntEnum):
    DESKTOP = 0x0010
    STARTUP = 0x0007


def shortcut_file(folder: Path) -> Path:
    return folder / SHORTCUT_FILE


def _written_file(folder: Path) -> Path:
    return folder / _WRITTEN_NAME


@dataclass(frozen=True)
class Shortcut:
    folder: Folder
    arguments: tuple[str, ...]


def shortcuts(root: Path) -> tuple[Shortcut, ...]:
    script = str(centrum_script(root))
    return (Shortcut(Folder.DESKTOP, (script,)), Shortcut(Folder.STARTUP, (script, NO_BROWSER_FLAG)))


_WHERE = {Folder.DESKTOP: "pulpit tego komputera", Folder.STARTUP: "folder Autostart tego komputera"}
_CREATED = {
    Folder.DESKTOP: "Utworzono skrót „Centrum rozliczeń”",
    Folder.STARTUP: "Utworzono skrót „Centrum rozliczeń” w Autostarcie (start po zalogowaniu, bez karty)",
}

class ShortcutNotWritten(OSError):
    ...


class PowerShellTimedOut(ShortcutNotWritten):
    ...


class PowerShellFailed(ShortcutNotWritten):
    ...


class ShortcutNotMoved(ShortcutNotWritten):
    ...


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
    else:
        return _create(args.folder, args.folder_autostartu)


def _create(desktop: Path | None, startup: Path | None) -> int:
    windowless_python = _windowless_python()
    if file_state(windowless_python) != "file":
        print(
            "Co się stało: Nie utworzono skrótu, bo ten Python nie ma programu pythonw.exe.\n"
            f"Gdzie: folder {windowless_python.parent}\n"
            "Co zrobić: Zainstaluj Python ze strony python.org i uruchom ten krok ponownie."
        )
        return 1
    chosen = {Folder.DESKTOP: desktop, Folder.STARTUP: startup}
    for shortcut in shortcuts(TOOL_ROOT):
        try:
            path = _write(shortcut, windowless_python, chosen[shortcut.folder], run_console_program)
        except OSError as failure:
            print(
                "Co się stało: Nie udało się utworzyć skrótu „Centrum rozliczeń”.\n"
                f"Gdzie: {_WHERE[shortcut.folder]}\n"
                f"Co zrobić: Uruchom ten krok ponownie. {refer_if('Jeśli komunikat wraca', request='przekaż go')}"
            )
            print(f"Przyczyna techniczna: {exception_type(failure)}", file=sys.stderr)
            return 1
        print(f"{_CREATED[shortcut.folder]}: {path}")
    return 0


def _windowless_python() -> Path:
    return Path(sys.executable).with_name("pythonw.exe")


@dataclass(frozen=True)
class StartupShortcut:
    folder: Path | None = None
    program: Path = field(default_factory=_windowless_python)
    run: ConsoleRun = run_console_program

    def state(self) -> AutostartState:
        folder = self._folder()
        # ZEWNĘTRZNE: Windows uruchamia po zalogowaniu każdy skrót z folderu Autostart, także plik pośredni zapisu, który PowerShell dokończył po zgaśnięciu Centrum (Microsoft Learn: CSIDL, CSIDL_STARTUP)
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
    return StartupShortcut() if sys.platform == "win32" else NO_AUTOSTART


def _system_folder(folder: Folder) -> Path:
    if sys.platform != "win32":
        raise OSError("Pulpit i folder Autostart dla skrótu są tylko na Windows.")
    else:
        import ctypes
        from ctypes import wintypes

        path = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, folder.value, None, 0, path) != 0:
            raise OSError(f"Windows nie podał folderu {folder.name}.")
        return Path(path.value)


def _write(shortcut: Shortcut, windowless_python: Path, folder: Path | None, run: ConsoleRun) -> Path:
    target = shortcut_file(folder.resolve() if folder is not None else _system_folder(shortcut.folder))
    written = _written_file(target.parent)
    # ZEWNĘTRZNE: ścieżka wpisana w treść skryptu PowerShella wymaga cytowania apostrofu, znaku $ i grawisu, a wartość zmiennej środowiskowej nie (Microsoft Learn: about_Quoting_Rules)
    environment = os.environ | {
        "CENTRUM_SKROT_PLIK": str(written),
        "CENTRUM_SKROT_NAZWA": SHORTCUT_NAME,
        "CENTRUM_SKROT_PROGRAM": str(windowless_python),
        # ZEWNĘTRZNE: nazwa pliku Windows nie może mieć cudzysłowu, więc argument w cudzysłowie przenosi spację ścieżki narzędzia (Microsoft Learn: Naming Files, Paths, and Namespaces)
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
            raise PowerShellTimedOut(f"PowerShell nie zapisał skrótu w {_POWERSHELL_TIMEOUT_S:.0f} s.") from late
        if result.returncode != 0:
            raise PowerShellFailed(f"PowerShell nie zapisał skrótu (kod {result.returncode}).")
        try:
            os.replace(written, target)
        except OSError as error:
            raise ShortcutNotMoved("Windows nie przeniósł zapisanego skrótu pod jego nazwę.") from error
    finally:
        with suppress(OSError):
            written.unlink(missing_ok=True)
    return target
