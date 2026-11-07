"""Jednorazowy krok instalacji: skrót „Centrum rozliczeń” z ikoną na pulpicie taty.

Skrót uruchamia ``run_centrum.py`` przez ``pythonw.exe`` tego samego Pythona,
którym zainstalowano zależności (``py -3``), więc Centrum startuje bez okna
konsoli. Skrót zapisuje PowerShell przez WScript.Shell, bez dodatkowych
bibliotek. Ścieżki trafiają do PowerShella w zmiennych środowiskowych, nie w
treści skryptu, więc spacje i polskie znaki nie wymagają cytowania. Ponowne
uruchomienie kroku nadpisuje skrót, np. po przeniesieniu folderu narzędzia.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys

from rozliczenia.tool_files import TOOL_ROOT, centrum_script

SHORTCUT_NAME = "Centrum rozliczeń"
ICON = Path(__file__).resolve().parent / "centrum-rozliczen.ico"

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$folder = $env:CENTRUM_SKROT_FOLDER
if (-not $folder) { $folder = [Environment]::GetFolderPath('Desktop') }
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
    parser = argparse.ArgumentParser(description="Tworzy skrót „Centrum rozliczeń” (Windows).")
    parser.add_argument("--folder", type=Path, help="Folder skrótu; domyślnie pulpit.")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("Skrót „Centrum rozliczeń” powstaje tylko na Windows. Przy rozwoju uruchom: python run_centrum.py")
        return 1
    windowless_python = Path(sys.executable).with_name("pythonw.exe")
    if not windowless_python.is_file():
        print(
            "Co się stało: Nie utworzono skrótu, bo ten Python nie ma programu pythonw.exe.\n"
            f"Gdzie: folder {windowless_python.parent}\n"
            "Co zrobić: Zainstaluj Python ze strony python.org i uruchom ten krok ponownie."
        )
        return 1
    folder = {"CENTRUM_SKROT_FOLDER": str(args.folder.resolve())} if args.folder else {}
    environment = os.environ | folder | {
        "CENTRUM_SKROT_NAZWA": SHORTCUT_NAME,
        "CENTRUM_SKROT_PROGRAM": str(windowless_python),
        "CENTRUM_SKROT_ARGUMENTY": f'"{centrum_script(TOOL_ROOT)}"',
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
            "Gdzie: pulpit tego komputera\n"
            "Co zrobić: Uruchom ten krok ponownie. Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
        )
        return 1
    print(f"Utworzono skrót „Centrum rozliczeń”: {result.stdout.strip()}")
    return 0
