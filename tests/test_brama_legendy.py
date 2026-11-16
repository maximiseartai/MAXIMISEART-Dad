"""Brama Legendy czynności na Pliku zbiorczym wypełnionym przez tatę: zgodność wierszy z kodem, same liczby i kody.

Plik zbiorczy powstaje z Przygotowania pliku zbiorczego z legendą z Wydania na syntetycznym Rejestrze i Wzorcach w
kształcie Wzorców taty, a potem „tata” zmienia w nim kilka komórek. Oczekiwane wartości legendy pochodzą z maila taty z
15.11.2026 (ADR 0038), a plik Logów Wyceny w efenix z prawdziwej Kopii wejścia tego Pliku zbiorczego.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import gzip
import json
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook
from openpyxl.styles import PatternFill

from rozliczenia.centrum.logged_input_copy import LoggedInputFile
from rozliczenia.centrum.settings.activity_legend import LEGEND_FILE
from rozliczenia.dad_files import DadFiles
from rozliczenia.input_copy import InputCopy
from rozliczenia.workbook_files import read_computed_rows

from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, write_synthetic_templates
from atrapy.preparation import PreparationFixture, make_preparation_fixture, register_order
from tests.fixtures.operacje import run_preparation
from atrapy.workbooks import active_worksheet

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "brama_legendy.py"
ORDERS = [
    ("inst20m", "dekoder"),
    ("spawpg", "dekoder"),
    ("technicolor: instwewrg65m", "technicolor"),
    ("rt2", "dekoder"),
    ("20 m patchcord dzielnik 1/2", "dekoder"),
    ("instutp40m", "dekoder"),
    ("kabel SYN-OPIS 15 m", "dekoder"),
    ("instmdik dzielnik1/2", "dekoder"),
    ("", "technicolor"),
]
"""``CZYNNOŚCI ZREALIZOWANE`` i ``URZĄDZENIA`` zleceń; ``dekoder`` daje z Reguł ilości z Wydania tylko V, a
``technicolor`` także 1 w AK, do którego legenda dodaje swoje 1 z ``instwewrg65m``, a bez kodu to 1 nie jest wpisem
taty."""


def _filled_by_dad(tmp_path: Path) -> PreparationFixture:
    start = datetime(2026, 9, 8, 8, 0)
    rows: list[dict[str, object] | None] = [
        register_order(number, start + timedelta(minutes=number))
        | {"URZĄDZENIA": devices, "UMOWA": "pr", "CZYNNOŚCI ZREALIZOWANE": completed}
        for number, (completed, devices) in enumerate(ORDERS, start=1)
    ]
    templates = write_synthetic_templates(tmp_path / "wzorce")
    (tmp_path / "okres").mkdir()
    fixture = replace(
        make_preparation_fixture(tmp_path / "okres", rows),
        internal_template_path=templates / INTERNAL_TEMPLATE,
        collective_template_path=templates / COLLECTIVE_TEMPLATE,
    )
    run_preparation(fixture)
    workbook = load_workbook(fixture.collective_file_path)
    try:
        sheet = active_worksheet(workbook)
        for cell in ("AF21", "AM21"):
            sheet[cell].fill = PatternFill()
        sheet["AM21"] = None
        sheet["AK21"] = 1
        sheet["Y22"] = 1
        sheet["AJ23"] = 1
        sheet["Y24"] = 1
        sheet["AS24"] = 30
        sheet["AS25"] = 100
        workbook.save(fixture.collective_file_path)
    finally:
        workbook.close()
    return fixture


def _efenix_logs(collective: Path, target: Path) -> Path:
    """Plik Logów Wyceny w efenix z polami, które brama czyta (proces i Kopia wejścia ``collective``, jak ją pisze
    Centrum), spakowany jak w Archiwum Logów okresu."""

    files = DadFiles(copy=InputCopy())
    read_computed_rows(collective, files)
    assert files.copy is not None
    copied = [LoggedInputFile.of(file).model_dump(mode="json") for file in files.copy.files()]
    target.write_bytes(gzip.compress(json.dumps({"process": "efenix", "input_copy": copied}).encode("utf-8")))
    return target


def _gate(*arguments: str | Path) -> list[str]:
    result = subprocess.run(
        [sys.executable, str(TOOL), *map(str, arguments)], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout.splitlines()


def test_brama_liczy_zgodnosc_wierszy_z_kodem_z_tata_z_dysku_i_z_logow_wyceny_bez_tresci_opisow(tmp_path: Path) -> None:
    fixture = _filled_by_dad(tmp_path)
    collective = fixture.collective_file_path
    logs = _efenix_logs(collective, tmp_path / "20260915T081000Z-efenix-brama.json.gz")
    described = tmp_path / "notatki" / "opisy.txt"

    lines = _gate(collective, logs, "--opisy", described)

    disk = lines.index(f"== {collective.name} | porównane: Y AB AC AD AJ AK AL AM, AS, kolory AF AM AS")
    assert lines[disk + 1 : disk + 10] == [
        "wiersze danych: 9 | z kodem: 6 | z samych kodów: 4 | kod obok opisu: 2 | DATA nie jest datą: 0",
        "zgodne z tatą wiersze z kodem: 3/6 (50.0%) | z samych kodów: 2/4 (50.0%) | kod obok opisu: 1/2 (50.0%)",
        "kody (wiersze): dzielnik1/2=2 inst=1 spawpg=1 instwewrg6=1 rt2=1 instmdik=1",
        "-- różnice (wiersze | wiersz | kody | kolumna: legenda, tata): 3 klas",
        "1 | kod obok opisu | dzielnik1/2 | Y: legenda 0, tata 1",
        "1 | z samych kodów | instmdik, dzielnik1/2 | AS: legenda 50, tata 100",
        "1 | z samych kodów | rt2 | AK: legenda 0, tata 1; AM: legenda 1, tata 0;"
        " kolor AF: legenda zielony, tata brak; kolor AM: legenda czerwony, tata brak",
        "-- kody spoza przedziałów (kod liczba → wiersze): instutp 40→1",
        "-- wiersze bez kodu z wpisem taty: 2 | Y=1 AJ=1 AS=1",
    ]
    copied = lines.index(f"== {collective.name} (Logi {logs.name}) | porównane: Y AB AC AD AJ AK AL AM (Logi: bez AS i kolorów)")
    assert lines[copied + 2 : copied + 10] == [
        "zgodne z tatą wiersze z kodem: 4/6 (66.7%) | z samych kodów: 3/4 (75.0%) | kod obok opisu: 1/2 (50.0%)",
        "kody (wiersze): dzielnik1/2=2 inst=1 spawpg=1 instwewrg6=1 rt2=1 instmdik=1",
        "-- różnice (wiersze | wiersz | kody | kolumna: legenda, tata): 2 klas",
        "1 | kod obok opisu | dzielnik1/2 | Y: legenda 0, tata 1",
        "1 | z samych kodów | rt2 | AK: legenda 0, tata 1; AM: legenda 1, tata 0",
        "-- kody spoza przedziałów (kod liczba → wiersze): instutp 40→1",
        "-- wiersze bez kodu z wpisem taty: 2 | Y=1 AJ=1",
        "== razem: 2 plików",
    ]
    assert lines[lines.index("== razem: 2 plików") + 2] == "zgodne z tatą wiersze z kodem: 7/12 (58.3%) | z samych kodów: 5/8 (62.5%) | kod obok opisu: 2/4 (50.0%)"
    assert "SYN" not in "\n".join(lines)
    assert "patchcord" not in "\n".join(lines)
    notes = described.read_text(encoding="utf-8")
    assert f"{collective.name} | wiersz 22 | różnica | kod obok opisu | dzielnik1/2 | Y: legenda 0, tata 1 | 20 m patchcord dzielnik 1/2" in notes
    assert f"{collective.name} | wiersz 24 | bez kodu z wpisem taty | Y=1 AS=30 | kabel SYN-OPIS 15 m" in notes
    assert f"{collective.name} | wiersz 23 | spoza przedziałów | instutp 40 | instutp40m" in notes


def test_brama_liczy_legenda_z_ustawien_a_opisow_nie_zapisuje_w_repozytorium(tmp_path: Path) -> None:
    fixture = _filled_by_dad(tmp_path)
    legend = tmp_path / LEGEND_FILE
    legend.write_text("schema_version: 1\nkody:\n  - {id: rt2, zapisy: [rt2], kolumna: AK}\n", encoding="utf-8")

    lines = _gate(fixture.collective_file_path, "--legenda", legend)

    assert lines[0] == f"Legenda czynności: {LEGEND_FILE} | Reguły ilości: z Wydania"
    assert lines[1].endswith("| porównane: AK, AS, kolory brak")
    assert lines[2:4] == [
        "wiersze danych: 9 | z kodem: 1 | z samych kodów: 1 | kod obok opisu: 0 | DATA nie jest datą: 0",
        "zgodne z tatą wiersze z kodem: 1/1 (100.0%) | z samych kodów: 1/1 (100.0%) | kod obok opisu: 0/0",
    ]
    inside = ROOT / "opisy-brama.txt"
    refused = subprocess.run(
        [sys.executable, str(TOOL), str(fixture.collective_file_path), "--opisy", str(inside)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert refused.returncode == 2
    assert "leży w repozytorium" in refused.stderr
    assert not inside.exists()
