from __future__ import annotations

from pathlib import Path

from rozliczenia.centrum.legend_sentences import AMOUNT_NAME

from tests.fixtures.centrum import centrum

LEGEND_URL = "/api/settings/activity-legend"


def test_bez_wzorca_pliku_zbiorczego_kolumny_legendy_to_same_litery_a_kwota_ma_swoja_nazwe(tmp_path: Path) -> None:
    legend = centrum(tmp_path).client.get(LEGEND_URL).json()

    columns = [legend["amount_column"], *legend["columns"], *legend["fill_columns"]]
    assert {(column["letter"] == "AS", column["name"]) for column in columns} == {(True, AMOUNT_NAME), (False, None)}


def test_kod_czynnosci_z_ukosnikiem_w_id_da_sie_usunac(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    assert "dzielnik1/2" in {code["id"] for code in app.client.get(LEGEND_URL).json()["codes"]}

    removed = app.client.delete(f"{LEGEND_URL}/dzielnik1/2")

    assert removed.status_code == 200, removed.text
    assert "dzielnik1/2" not in {code["id"] for code in removed.json()["activity_legend"]["codes"]}
