from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rozliczenia import order_base
from rozliczenia.client_data import empty_memory, guarded
from rozliczenia.dad_files import DadFiles
from rozliczenia.order_base import HistoryBlock, OrderBase
from rozliczenia.workbook_files import WorkbookError

from atrapy.baza_zlecen import FIVE, TWELVE, BaseSheet, Visit, write_order_base
from atrapy.intermax import like_excel

GRABOWA = "UL. GRABOWA 2"


def _base(tmp_path: Path, sheets: tuple[BaseSheet, ...]) -> Path:
    path = tmp_path / order_base.ORDER_BASE_NAME
    write_order_base(path, sheets)
    return path


def _read(path: Path) -> OrderBase:
    base = order_base.read(path, DadFiles())
    assert isinstance(base, OrderBase), base
    return base


def test_wiersz_bazy_z_numerem_zlecenia_pod_naglowkiem_nr_zle_nie_jest_w_historii_adresu(tmp_path: Path) -> None:
    own = Visit("Miastko,Grabowa 2", datetime(2019, 10, 1), 501, "własny")
    other = Visit("Miastko,Grabowa 2", datetime(2019, 9, 1), 777, "inny")
    path = _base(tmp_path, (BaseSheet("10_12_2018-01_08_2020", FIVE, [own, other]),))

    assert _read(path).history(GRABOWA, None, "ZL-501") == (HistoryBlock(other.values(FIVE)),)


def test_zlecenie_bez_cyfr_w_numerze_ma_w_historii_adresu_wiersz_bez_cyfr_w_numerze(tmp_path: Path) -> None:
    visit = Visit("GRABOWA 2", datetime(2025, 1, 1), "nr ?", "bez numeru")
    path = _base(tmp_path, (BaseSheet("19_12_2025-17_11_2026", TWELVE, [visit]),))

    assert _read(path).history(GRABOWA, None, "brak numeru") == (HistoryBlock(visit.values(TWELVE)),)


def test_blok_historii_adresu_konczy_sie_na_ostatnim_naglowku_a_nie_na_pustej_komorce_wiersza_1_za_nim(
    tmp_path: Path,
) -> None:
    visit = Visit("GRABOWA 2", datetime(2025, 1, 1), 9000, "wizyta")
    path = _base(tmp_path, (BaseSheet("19_12_2025-17_11_2026", TWELVE, [visit]),))
    workbook = load_workbook(path)
    workbook.worksheets[0].cell(1, len(TWELVE.headers) + 3).value = ""
    workbook.save(path)
    like_excel(path)

    assert _read(path).history(GRABOWA, None, "ZL-1") == (HistoryBlock(visit.values(TWELVE)),)


def test_komorka_wiersza_bazy_bez_zapisu_w_arkuszu_to_none_w_historii_adresu(tmp_path: Path) -> None:
    visit = Visit("GRABOWA 2", datetime(2025, 1, 1), 9000, "wizyta")
    path = _base(tmp_path, (BaseSheet("19_12_2025-17_11_2026", TWELVE, [visit]),))
    umowa = TWELVE.headers.index("UMOWA") + 1
    workbook = load_workbook(path)
    sheet = workbook.worksheets[0]
    sheet.delete_cols(umowa)
    sheet.insert_cols(umowa)
    sheet.cell(1, umowa, "UMOWA")
    workbook.save(path)
    like_excel(path)

    [block] = _read(path).history(GRABOWA, None, "ZL-1")

    assert block == HistoryBlock(visit.values(TWELVE))
    assert block.values[umowa - 1] is None


def test_arkusz_wykresu_w_bazie_nie_jest_arkuszem_bazy(tmp_path: Path) -> None:
    visit = Visit("GRABOWA 2", datetime(2025, 1, 1), 9000, "wizyta")
    path = _base(tmp_path, (BaseSheet("19_12_2025-17_11_2026", TWELVE, [visit]),))
    workbook = load_workbook(path)
    workbook.create_chartsheet("Wykres", 0)
    workbook.save(path)
    like_excel(path)

    base = _read(path)

    assert (base.sheet_count, base.history(GRABOWA, None, "ZL-1")) == (1, (HistoryBlock(visit.values(TWELVE)),))


def test_paczka_bez_dokumentu_skoroszytu_to_baza_nieczytelna(tmp_path: Path) -> None:
    path = tmp_path / order_base.ORDER_BASE_NAME
    with zipfile.ZipFile(path, "w") as written:
        written.writestr("[Content_Types].xml", "<Types/>")
        written.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')

    with pytest.raises(WorkbookError):
        order_base.read(path, DadFiles())


def test_pamiec_reguly_danych_zna_adresy_wierszy_bazy_a_nie_naglowek_kolumny_a(tmp_path: Path) -> None:
    visit = Visit("Miastko,Grabowa 2", datetime(2019, 10, 1), 501, "wizyta")
    path = _base(tmp_path, (BaseSheet("10_12_2018-01_08_2020", FIVE, [visit]),))
    memory = empty_memory()

    order_base.read(path, DadFiles(forbidden=memory).for_run())

    assert guarded(memory, "Miastko,Grabowa 2 w uwadze", "Uwaga taty").notes
    assert guarded(memory, "adres w uwadze", "Uwaga taty").notes == ()
