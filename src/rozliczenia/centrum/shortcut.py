"""Jednorazowy krok instalacji: skrót „Centrum rozliczeń” z ikoną na pulpicie taty i w jego Autostarcie Windows.

Skrót uruchamia ``run_centrum.py`` przez ``pythonw.exe`` tego samego Pythona,
którym zainstalowano zależności (``py -3``), więc Centrum startuje bez okna
konsoli. Skrót w Autostarcie (``shell:startup``) dodaje flagę ``--no-browser``:
po zalogowaniu taty Centrum startuje bez karty, żeby Przypomnienia o raporcie
szły bez jego kliknięcia (ADR 0030), a skrót z pulpitu otwiera kartę.
Skrót zapisuje PowerShell przez WScript.Shell, bez dodatkowych bibliotek, a
folder pulpitu i Autostartu podaje mu API Windows
(``Environment.GetFolderPath``). Ścieżki trafiają do PowerShella w zmiennych
środowiskowych, nie w treści skryptu, więc spacje i polskie znaki nie wymagają
cytowania. Ponowne uruchomienie kroku nadpisuje oba skróty, np. po
przeniesieniu folderu narzędzia, a nie dokłada nowych.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import subprocess
import sys

from rozliczenia.file_state import file_state
from rozliczenia.message import refer_if
from rozliczenia.tool_files import NO_BROWSER_FLAG, TOOL_ROOT, centrum_script

SHORTCUT_NAME = "Centrum rozliczeń"
ICON = Path(__file__).resolve().parent / "centrum-rozliczen.ico"


class Folder(StrEnum):
    """Folder Windows skrótu; wartość to nazwa folderu w ``Environment.SpecialFolder``."""

    DESKTOP = "Desktop"
    STARTUP = "Startup"


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
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$folder = $env:CENTRUM_SKROT_FOLDER
if (-not $folder) { $folder = [Environment]::GetFolderPath($env:CENTRUM_SKROT_MIEJSCE) }
$path = Join-Path $folder ($env:CENTRUM_SKROT_NAZWA + '.lnk')
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$link.TargetPath = $env:CENTRUM_SKROT_PROGRAM
$link.Arguments = $env:CENTRUM_SKROT_ARGUMENTY
$link.WorkingDirectory = $env:CENTRUM_SKROT_FOLDER_ROBOCZY
$link.IconLocation = $env:CENTRUM_SKROT_IKONA
$link.Description = $env:CENTRUM_SKROT_NAZWA
$link.Save()
Write-Output $path
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
    windowless_python = Path(sys.executable).with_name("pythonw.exe")
    if file_state(windowless_python) != "file":
        print(
            "Co się stało: Nie utworzono skrótu, bo ten Python nie ma programu pythonw.exe.\n"
            f"Gdzie: folder {windowless_python.parent}\n"
            "Co zrobić: Zainstaluj Python ze strony python.org i uruchom ten krok ponownie."
        )
        return 1
    chosen = {Folder.DESKTOP: args.folder, Folder.STARTUP: args.folder_autostartu}
    for shortcut in shortcuts(TOOL_ROOT):
        if not _write(shortcut, windowless_python, chosen[shortcut.folder]):
            return 1
    return 0


def _write(shortcut: Shortcut, windowless_python: Path, folder: Path | None) -> bool:
    """Zapisuje (albo nadpisuje) ``<folder>\\Centrum rozliczeń.lnk`` i drukuje wynik; ``False`` po porażce."""

    environment = os.environ | {
        # Pusty folder: PowerShell pyta API Windows o folder ``CENTRUM_SKROT_MIEJSCE``.
        "CENTRUM_SKROT_FOLDER": str(folder.resolve()) if folder else "",
        "CENTRUM_SKROT_MIEJSCE": shortcut.folder.value,
        "CENTRUM_SKROT_NAZWA": SHORTCUT_NAME,
        "CENTRUM_SKROT_PROGRAM": str(windowless_python),
        # Cudzysłów wokół każdego argumentu: ścieżka narzędzia może mieć spację, a nazwa pliku Windows nie ma cudzysłowu.
        "CENTRUM_SKROT_ARGUMENTY": " ".join(f'"{argument}"' for argument in shortcut.arguments),
        "CENTRUM_SKROT_FOLDER_ROBOCZY": str(TOOL_ROOT),
        "CENTRUM_SKROT_IKONA": f"{ICON},0",
    }
    script = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", script],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(
            "Co się stało: Nie udało się utworzyć skrótu „Centrum rozliczeń”.\n"
            f"Gdzie: {_WHERE[shortcut.folder]}\n"
            f"Co zrobić: Uruchom ten krok ponownie. {refer_if('Jeśli komunikat wraca', request='przekaż go')}"
        )
        return False
    print(f"{_CREATED[shortcut.folder]}: {result.stdout.strip()}")
    return True
