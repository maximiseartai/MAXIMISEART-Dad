"""Legenda czynności z Wydania w Pliku zbiorczym z Przygotowania pliku zbiorczego (ADR 0038).

Każdy przypadek to jedno Zlecenie skuteczne syntetycznego Rejestru z ``CZYNNOŚCI ZREALIZOWANE``, a oczekiwane Ilości
usług, kwota w ``AS`` i kolory pochodzą z maila taty z 15.11.2026, ADR 0038, ADR 0039 i ADR 0041, nie z kodu: zwykły
opis obok kodów nie zmienia tego, co kody wyznaczają, a opis bez żadnego kodu i opis z Błędem opisu nie dostaje od
legendy nic. Wzorce mają kształt Wzorców taty (``tools/syntetyczne_wzorce.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import pytest

from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.collective_layout import PHOTO_COLUMNS, QUANTITY_COLUMNS

from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, write_synthetic_templates
from atrapy.preparation import PreparationFixture, make_preparation_fixture, register_order
from tests.fixtures.operacje import run_preparation
from tests.fixtures.wyglad_komorek import wyglady
from atrapy.workbooks import active_worksheet, refused_by_copy

LETTERS = [get_column_letter(column) for column in (*QUANTITY_COLUMNS, 43, 44, 45)]
"""Kolumny Ilości usług N:AP i AQ:AS, w tym ``AS`` (Uwagi - kwota)."""
PHOTO_LETTERS = [get_column_letter(column) for column in PHOTO_COLUMNS]
GREEN, RED = "FF92D050", "FFFF0000"
DEVICES_ONLY_V = {"V": 1}
"""``dekoder`` (składnik spoza Listy Urządzeń) daje z Reguł ilości z Wydania tylko V (instrukcja taty)."""


@dataclass(frozen=True)
class Case:
    completed: str
    values: dict[str, int]
    """Ilości usług i kwota w ``AS`` poza wartościami Wzorca, razem z wartością Reguł ilości."""
    fills: dict[str, str | None] = field(default_factory=dict)
    devices: str = "dekoder"


MAIL: list[Case] = [
    Case("inst20m", DEVICES_ONLY_V | {"Y": 1}),
    Case("inst5m", DEVICES_ONLY_V | {"Y": 1}),
    Case("inst25m", DEVICES_ONLY_V | {"Y": 1}),
    Case("inst40m", DEVICES_ONLY_V | {"Y": 1}),
    Case("instmdik", DEVICES_ONLY_V | {"Y": 1}),
    Case("instutp1m", DEVICES_ONLY_V | {"AL": 1}),
    Case("instutp15m", DEVICES_ONLY_V | {"AL": 1}),
    Case("instutp16m", DEVICES_ONLY_V | {"AJ": 1}),
    Case("instutp30m", DEVICES_ONLY_V | {"AJ": 1}),
    Case("instwewrg610m", DEVICES_ONLY_V | {"AK": 1}),
    Case("instwewrg611m", DEVICES_ONLY_V | {"AL": 1}),
    Case("instwewrg615m", DEVICES_ONLY_V | {"AL": 1}),
    Case("instwewrg616m", DEVICES_ONLY_V | {"AJ": 1}),
    Case("rt2", DEVICES_ONLY_V | {"AM": 1}, {"AM": RED, "AF": GREEN}),
    Case("bypas2m", DEVICES_ONLY_V | {"AM": 1}),
    Case("spawgnd", DEVICES_ONLY_V | {"AD": 1}),
    Case("spawpg", DEVICES_ONLY_V | {"AB": 1, "AS": 70}, {"AS": RED}),
    Case("spawez", DEVICES_ONLY_V | {"AB": 1}),
    Case("spawmufakan", DEVICES_ONLY_V | {"AB": 1, "AS": 70}),
    Case("spawmufaziem", DEVICES_ONLY_V | {"AC": 1}),
    Case("dzielnik1/2", DEVICES_ONLY_V | {"AS": 50}),
    Case("pz20m", DEVICES_ONLY_V | {"AS": 480}),
    Case("pz15m", DEVICES_ONLY_V | {"AS": 480}),
    Case("instwew15m", DEVICES_ONLY_V, {"AF": GREEN}),
]
SUMS: list[Case] = [
    Case("inst25m instutp17m", DEVICES_ONLY_V | {"Y": 1, "AJ": 1}),
    Case("spawpg dzielnik1/2", DEVICES_ONLY_V | {"AB": 1, "AS": 120}, {"AS": RED}),
    Case("dzielnik1/2, dzielnik1/2", DEVICES_ONLY_V | {"AS": 100}),
    Case("instwewrg65m", {"O": 1, "S": 1, "Z": 1, "AK": 2, "V": 1}, devices="technicolor"),
    Case("rt2", {"AM": 2, "V": 1}, {"AM": RED, "AF": GREEN}, devices="zmiana instalacji w lokalu abonenta"),
]
SPELLING: list[Case] = [
    Case("INST20M", DEVICES_ONLY_V | {"Y": 1}),
    Case("tak, Inst20M.", DEVICES_ONLY_V | {"Y": 1}),
    Case("SpawPG\nnie", DEVICES_ONLY_V | {"AB": 1, "AS": 70}, {"AS": RED}),
]
BESIDE_PLAIN: list[Case] = [
    Case("20 m patchcord dzielnik1/2", DEVICES_ONLY_V | {"AS": 50}),
    Case("spawpg montaż", DEVICES_ONLY_V | {"AB": 1, "AS": 70}, {"AS": RED}),
    Case("Podłączyłem lokal, rt2 i instmdic.", DEVICES_ONLY_V | {"AM": 1}, {"AM": RED, "AF": GREEN}),
]
WITHOUT_CODE: list[Case] = [
    Case("spawanie gniazda", DEVICES_ONLY_V),
    Case("instalacja 20m", DEVICES_ONLY_V),
    Case("xinst20m", DEVICES_ONLY_V),
    Case("rt25", DEVICES_ONLY_V),
    Case("instmdic", DEVICES_ONLY_V),
    Case("dzielnika1/2", DEVICES_ONLY_V),
    Case("utp18m", DEVICES_ONLY_V),
    Case("tak, Inst 20 m", DEVICES_ONLY_V),
    Case("Spaw PG", DEVICES_ONLY_V),
    Case("20 m patchcord dzielnik 1/2", DEVICES_ONLY_V),
]
DESCRIPTION_ERRORS: list[Case] = [
    Case("instutp40m", DEVICES_ONLY_V),
    Case("instutp0m", DEVICES_ONLY_V),
    Case("instwewrg631m", DEVICES_ONLY_V),
    Case("montaż instutp40m spawpg", DEVICES_ONLY_V),
    Case("inst20m inst20m", DEVICES_ONLY_V),
    Case("instmdik inst20m", DEVICES_ONLY_V),
    Case("rt2 bypas5m", DEVICES_ONLY_V),
    Case("Podłączyłem lokal: inst20m, inst30m.", DEVICES_ONLY_V),
]
CASES = [*MAIL, *SUMS, *SPELLING, *BESIDE_PLAIN, *WITHOUT_CODE, *DESCRIPTION_ERRORS]


def _fixture(tmp_path: Path, cases: list[Case]) -> PreparationFixture:
    start = datetime(2026, 9, 8, 8, 0)
    rows: list[dict[str, object] | None] = [
        register_order(number, start + timedelta(minutes=number))
        | {"URZĄDZENIA": case.devices, "UMOWA": "pr", "CZYNNOŚCI ZREALIZOWANE": case.completed}
        for number, case in enumerate(cases, start=1)
    ]
    templates = write_synthetic_templates(tmp_path / "wzorce")
    (tmp_path / "okres").mkdir()
    return replace(
        make_preparation_fixture(tmp_path / "okres", rows),
        internal_template_path=templates / INTERNAL_TEMPLATE,
        collective_template_path=templates / COLLECTIVE_TEMPLATE,
    )


def _values(path: Path, count: int) -> list[dict[str, object]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return [{letter: sheet[f"{letter}{row}"].value for letter in LETTERS} for row in range(18, 18 + count)]
    finally:
        workbook.close()


def _fills(path: Path, count: int) -> list[dict[str, str | None]]:
    """Kolor wypełnienia jednolitego każdej komórki N:AS; ``None``: komórka bez wypełnienia jednolitego."""

    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return [
            {
                letter: str(cell.fill.fgColor.rgb) if cell.fill.patternType == "solid" else None
                for letter in LETTERS
                for cell in (sheet[f"{letter}{row}"],)
            }
            for row in range(18, 18 + count)
        ]
    finally:
        workbook.close()


def test_kazdy_kod_z_maila_taty_daje_w_pliku_zbiorczym_swoje_ilosci_kwote_as_i_kolory(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, CASES)
    register = fixture.register_path.read_bytes()

    preview = run_preparation(fixture, dry_run=True)
    summary = run_preparation(fixture)

    assert replace(preview, phase_durations_ms={}, routes={}) == replace(summary, phase_durations_ms={}, routes={})
    template_values = _values(fixture.collective_template_path, len(CASES))
    template_fills = _fills(fixture.collective_template_path, len(CASES))
    assert {GREEN, RED}.isdisjoint(fill for row in template_fills for fill in row.values())
    expected_values = [cells | case.values for cells, case in zip(template_values, CASES, strict=True)]
    expected_fills = [fills | case.fills for fills, case in zip(template_fills, CASES, strict=True)]
    written_values = _values(fixture.collective_file_path, len(CASES))
    written_fills = _fills(fixture.collective_file_path, len(CASES))
    assert [
        (case.completed, {letter: (row[letter], want[letter]) for letter in row if row[letter] != want[letter]})
        for case, row, want in zip(CASES, written_values, expected_values, strict=True)
        if row != want
    ] == []
    assert [
        (case.completed, {letter: (row[letter], want[letter]) for letter in row if row[letter] != want[letter]})
        for case, row, want in zip(CASES, written_fills, expected_fills, strict=True)
        if row != want
    ] == []
    assert fixture.register_path.read_bytes() == register


@pytest.mark.parametrize("code", ["inst30m", "spawpg", "rt2", "instutp17m dzielnik1/2"])
def test_kod_ze_zwyklym_opisem_obok_daje_w_pliku_zbiorczym_te_same_komorki_co_sam_kod(tmp_path: Path, code: str) -> None:
    described = f"{code} Podłączyłem lokal, klient zadowolony, wymiana gniazda."
    cases = [Case(code, {}), Case(described, {}), Case(f"Na miejscu: {code}", {})]
    fixture = _fixture(tmp_path, cases)

    run_preparation(fixture)

    values, fills = _values(fixture.collective_file_path, 3), _fills(fixture.collective_file_path, 3)
    assert (values[1], fills[1]) == (values[0], fills[0])
    assert (values[2], fills[2]) == (values[0], fills[0])


def test_kolor_bez_wartosci_nie_robi_ze_zlecenia_zlecenia_ze_zdjeciami(tmp_path: Path) -> None:
    """Zlecenie ze zdjęciami to wartość inna niż 0 w kolumnach zdjęć (GLOSSARY); zielone ``AF`` z ``instwew15m`` jej nie
    daje."""

    cases = [Case("instwew15m", DEVICES_ONLY_V, {"AF": GREEN})]
    fixture = _fixture(tmp_path, cases)

    run_preparation(fixture)

    [row] = _values(fixture.collective_file_path, 1)
    assert {letter: row[letter] for letter in PHOTO_LETTERS if row[letter] not in (None, 0)} == {}
    assert _fills(fixture.collective_file_path, 1)[0]["AF"] == GREEN


RT2_OUTSIDE_FAULTS = ActivityLegend(
    tuple(replace(code, counts_in_fault=False) if code.id == "rt2" else code for code in DEFAULT_ACTIVITY_LEGEND.codes)
)
FAULT = "usterka"


def test_rt2_w_usterce_nic_nie_wyznacza_a_poza_usterka_daje_am_z_kolorami(tmp_path: Path) -> None:
    cases = [
        Case("", {}, devices=FAULT),
        Case("rt2", {}, devices=FAULT),
        Case("Wymiana kabla, rt2.", {}, devices=FAULT),
        Case("bypas5m", {}, devices=FAULT),
        Case("rt2 bypas5m", {}, devices=FAULT),
        Case("rt2", DEVICES_ONLY_V | {"AM": 1}, {"AM": RED, "AF": GREEN}),
    ]
    fixture = _fixture(tmp_path, cases)

    summary = run_preparation(fixture, legend=RT2_OUTSIDE_FAULTS)

    values, fills = _values(fixture.collective_file_path, len(cases)), _fills(fixture.collective_file_path, len(cases))
    assert values[0]["AI"], "Reguły ilości z Wydania dają usterce Ilość usług w AI"
    assert [(values[index], fills[index]) for index in (1, 2)] == [(values[0], fills[0])] * 2
    assert (values[4], fills[4]) == (values[3], fills[3])
    assert values[3]["AM"] == 1
    assert "BLEDY_OPISU" not in [warning.code for warning in summary.warnings]
    template = _values(fixture.collective_template_path, len(cases))[5]
    assert (values[5], {letter: fills[5][letter] for letter in ("AM", "AF")}) == (template | cases[5].values, cases[5].fills)


def test_legenda_z_kopii_wzorca_jest_taka_jak_z_openpyxl(tmp_path: Path) -> None:
    (tmp_path / "kopia").mkdir()
    (tmp_path / "openpyxl").mkdir()
    by_copy = _fixture(tmp_path / "kopia", CASES)
    by_openpyxl = _fixture(tmp_path / "openpyxl", CASES)
    refused_by_copy(by_openpyxl.collective_template_path)

    run_preparation(by_copy)
    run_preparation(by_openpyxl)

    created, reference = by_copy.collective_file_path, by_openpyxl.collective_file_path
    assert _values(created, len(CASES)) == _values(reference, len(CASES))
    assert _looks(created, len(CASES)) == _looks(reference, len(CASES))


def _looks(path: Path, count: int) -> dict[str, object]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return dict(wyglady(cell for row in sheet.iter_rows(min_row=18, max_row=17 + count, min_col=14, max_col=45) for cell in row))
    finally:
        workbook.close()
