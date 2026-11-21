from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, get_args

import pytest

from rozliczenia import period_folder
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodStatus,
    check_worker_name,
    collective_period_token,
    layout_root,
    month_folder_label,
    period_status_label,
    scan_period_folders,
)
from rozliczenia.settlement_period import UNKNOWN_PERIOD, parse_period_token

GLOSSARY = Path(__file__).resolve().parents[1] / "GLOSSARY.md"
PERIOD = parse_period_token("08_14_09_2026")
NAME_UNITS_WITHOUT_WORKER = len("Rozliczenie 08_14_09_2026 - .xlsx")
ASTRAL = chr(0x1D409)


@pytest.mark.parametrize(
    ("worker", "expected"),
    [
        pytest.param("J" * (255 - NAME_UNITS_WITHOUT_WORKER), "fine", id="255-jednostek"),
        pytest.param("J" * (256 - NAME_UNITS_WITHOUT_WORKER), "too_long", id="256-jednostek"),
        pytest.param(ASTRAL * ((255 - NAME_UNITS_WITHOUT_WORKER) // 2) + "J" * ((255 - NAME_UNITS_WITHOUT_WORKER) % 2), "fine", id="255-jednostek-utf-16"),
        pytest.param(ASTRAL * ((256 - NAME_UNITS_WITHOUT_WORKER) // 2) + "J" * ((256 - NAME_UNITS_WITHOUT_WORKER) % 2), "too_long", id="256-jednostek-utf-16"),
        pytest.param("Jan\ud800Testowy", "too_long", id="bez-zapisu-w-utf-16"),
        pytest.param("Jan\tTestowy", "invalid", id="znak-sterujacy"),
        pytest.param("Jan Testowy ", "invalid", id="spacja-na-koncu"),
    ],
)
def test_nazwa_wykonawcy_jest_nazwa_pliku_rozliczenia_pracownika_do_255_jednostek_utf_16_bez_znakow_niedozwolonych_w_windows(
    worker: str, expected: str
) -> None:
    assert check_worker_name(worker) == expected


def _settlements(tmp_path: Path) -> PeriodFolder:
    folder = PeriodFolder(tmp_path, PERIOD)
    folder.worker_settlements.mkdir(parents=True)
    for name in ("Bartek Testowy", "Adrian Testowy"):
        folder.worker_settlement(name).write_bytes(b"syntetyczny skoroszyt")
    for name in (
        f"~${folder.worker_settlement('Adrian Testowy').name}",
        f".{folder.worker_settlement('Celina Testowa').name}",
        "Rozliczenie 08_14_09_2026 -.xlsx",
        "Rozliczenie 08_14_09_2026 - .xlsx",
        "Rozliczenie 01_07_09_2026 - Darek Testowy.xlsx",
    ):
        (folder.worker_settlements / name).write_bytes(b"syntetyczny plik")
    folder.worker_settlement("Edward Testowy").mkdir()
    return folder


def test_rozliczenia_pracownika_to_pliki_okresu_z_nazwa_wykonawcy_po_nazwie_bez_blokady_excela_wzorca_i_folderow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _settlements(tmp_path)
    scandir = os.scandir

    def listing_against_name_order(path: Any) -> Any:
        return _Reversed(sorted(scandir(path), key=lambda entry: entry.name, reverse=True))

    monkeypatch.setattr(os, "scandir", listing_against_name_order)

    assert [path.name for path in folder.worker_settlement_files()] == [
        "Rozliczenie 08_14_09_2026 - Adrian Testowy.xlsx",
        "Rozliczenie 08_14_09_2026 - Bartek Testowy.xlsx",
    ]
    assert folder.observe().worker_settlement_count == 2


def test_rozliczenia_pracownika_z_listowania_maja_wykonawce_z_nazwy_pliku_i_chwile_zmiany_w_utc(tmp_path: Path) -> None:
    folder = _settlements(tmp_path)
    modified = datetime(2026, 9, 15, 6, 30, tzinfo=timezone.utc)
    os.utime(folder.worker_settlement("Adrian Testowy"), (modified.timestamp(), modified.timestamp()))

    entries = folder.worker_settlement_entries()

    assert [(entry.path.name, entry.worker) for entry in entries] == [
        ("Rozliczenie 08_14_09_2026 - Adrian Testowy.xlsx", "Adrian Testowy"),
        ("Rozliczenie 08_14_09_2026 - Bartek Testowy.xlsx", "Bartek Testowy"),
    ]
    assert entries[0].modified_at == modified


class _Reversed(list[os.DirEntry[str]]):
    def __enter__(self) -> _Reversed:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _dad_layout(tmp_path: Path, *months: str) -> Path:
    attachments = tmp_path / "Załączniki"
    for month in months:
        (attachments / "Rozliczenia 2026" / month / "INEA").mkdir(parents=True)
    return attachments


def test_okres_w_dwoch_miesiacach_jest_raz_w_pierwszym_miesiacu_a_szukanie_podaje_oba_po_kolei_lat_i_miesiecy(
    tmp_path: Path,
) -> None:
    attachments = _dad_layout(tmp_path, "10_Październik_2026", "09_Wrzesień_2026")
    (attachments / "Rozliczenia 2025" / "12_Grudzień_2025" / "INEA").mkdir(parents=True)
    december = attachments / "Rozliczenia 2025" / "12_Grudzień_2025" / "INEA"
    september = attachments / "Rozliczenia 2026" / "09_Wrzesień_2026" / "INEA"
    october = attachments / "Rozliczenia 2026" / "10_Październik_2026" / "INEA"
    for month in (october, september, december):
        (month / PERIOD.token).mkdir()
    (attachments / "15_21_09_2026").write_bytes(b"syntetyczny plik o nazwie okresu")

    folders = scan_period_folders(attachments)

    assert [(found.periods_directory, found.period) for found in folders.found()] == [(december, PERIOD)]
    with pytest.raises(period_folder.PeriodFolderLookupError) as raised:
        folders.locate(PERIOD)
    assert (raised.value.periods_directory, raised.value.locations) == (attachments, (december, september, october))


def test_folder_okresu_wprost_w_folderze_okresow_jest_przed_miesiacami_i_ma_jego_nazwe(tmp_path: Path) -> None:
    attachments = _dad_layout(tmp_path, "09_Wrzesień_2026")
    september = attachments / "Rozliczenia 2026" / "09_Wrzesień_2026" / "INEA"
    for parent in (september, attachments):
        (parent / PERIOD.token).mkdir()

    folders = scan_period_folders(attachments)

    assert folders.locations[PERIOD] == (attachments, september)
    assert [month_folder_label(attachments, parent) for parent in folders.locations[PERIOD]] == [
        "Załączniki",
        "Rozliczenia 2026\\09_Wrzesień_2026\\INEA",
    ]


def test_tydzien_przeniesiony_przez_tate_dalej_prowadzi_do_zalacznikow(tmp_path: Path) -> None:
    attachments = _dad_layout(tmp_path, "09_Wrzesień_2026")
    moved_week = attachments / "Rozliczenia 2026" / "08_Sierpień_2026" / "INEA" / PERIOD.token

    assert layout_root(moved_week) == period_folder.LayoutRoot(attachments, by_years=True)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="chmod 0 nie odbiera dostępu w Windows ani rootowi")
def test_brak_folderu_okresow_w_rozliczeniach_roku_to_brak_takze_przy_miesiacu_bez_dostepu(tmp_path: Path) -> None:
    attachments = _dad_layout(tmp_path, "08_Sierpień_2026", "09_Wrzesień_2026")
    locked = attachments / "Rozliczenia 2026" / "08_Sierpień_2026"
    locked.chmod(0)
    try:
        folders = scan_period_folders(attachments / "Rozliczenia 2026" / "10_Październik_2026" / "INEA")
    finally:
        locked.chmod(0o755)

    assert folders.periods_directory_missing


@pytest.mark.parametrize(
    "name",
    ["Kopia Rozliczenie 08_14_09_2026 - zbiorcze.xlsx", "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx.bak"],
    ids=["przedrostek", "przyrostek"],
)
def test_plik_zbiorczy_to_tylko_dokladna_nazwa_pliku_zbiorczego(tmp_path: Path, name: str) -> None:
    with pytest.raises(period_folder.PeriodFolderError) as raised:
        PeriodFolder.from_collective_file(tmp_path / PERIOD.token / name)

    assert raised.value.problem == "not_collective_file_name"


def test_folder_rozliczen_pracownikow_przy_pliku_zbiorczym_to_rozliczenia_pracownikow_gotowe(tmp_path: Path) -> None:
    folder = PeriodFolder(tmp_path, PERIOD)
    folder.worker_settlements.mkdir(parents=True)
    folder.collective_file.write_bytes(b"syntetyczny plik zbiorczy")

    observed = folder.observe()

    assert (observed.status, observed.settled) == ("worker_settlements_ready", True)


def test_nazwy_statusow_okresu_to_nazwy_z_glossary() -> None:
    glossary = GLOSSARY.read_text(encoding="utf-8")
    entry = glossary.split("## Status okresu\n", 1)[1].split("\n## ", 1)[0]

    assert [label for label in map(period_status_label, get_args(PeriodStatus)) if label not in entry] == []


def test_token_okresu_do_metryk_to_nieznany_dla_sciezki_spoza_pliku_zbiorczego_w_folderze_okresu(tmp_path: Path) -> None:
    folder = PeriodFolder(tmp_path, PERIOD)

    assert [collective_period_token(path) for path in (folder.collective_file, folder.internal_settlement)] == [
        PERIOD.token,
        UNKNOWN_PERIOD,
    ]
