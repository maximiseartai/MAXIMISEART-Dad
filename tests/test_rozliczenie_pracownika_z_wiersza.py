from __future__ import annotations

from openpyxl.utils import column_index_from_string

from rozliczenia.quantity_engine import DeviceList, LeaveEmpty, QuantityRule, QuantityRules, Scope
from rozliczenia.workbook_files import header_columns
from rozliczenia.worker_settlement import for_worker
from tests.fixtures.data_rows import data_row

ZAWSZE_PUSTE_AK = QuantityRules((QuantityRule("inea", (), Scope.EVERY, LeaveEmpty(("AK",))),), DeviceList(()))


def test_bez_naglowka_urzadzen_regula_zostaw_pusta_nie_czysci_nic_choc_przy_naglowku_czysci_kazdy_wiersz() -> None:
    wiersz = data_row((None,) * (column_index_from_string("AK") - 1) + (3,))
    z_urzadzeniami = header_columns([None, None, None, "URZĄDZENIA"])

    bez, wyczyszczone_bez = for_worker(header_columns([]), [wiersz], ZAWSZE_PUSTE_AK)
    przy, wyczyszczone_przy = for_worker(z_urzadzeniami, [wiersz], ZAWSZE_PUSTE_AK)

    assert ([row.value("AK") for row in bez], dict(wyczyszczone_bez)) == ([3], {"AK": 0})
    assert ([row.value("AK") for row in przy], dict(wyczyszczone_przy)) == ([None], {"AK": 1})
