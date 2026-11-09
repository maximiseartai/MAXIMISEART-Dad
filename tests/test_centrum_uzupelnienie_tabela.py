"""Strona rodzaju Uzupełnienia pliku zbiorczego (#418, ADR 0016) przez HTTP API Centrum, jak przeglądarka.

Każdy test przygotowuje Plik zbiorczy z syntetycznego Rejestru zleceń w Centrum, potem zmienia go jak tata w
Excelu (openpyxl) i pyta Centrum o tabelę jednego rodzaju Ilości do uzupełnienia.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.fixtures.centrum import view_timing
from tests.fixtures.centrum_processes import PreparingCentrum, filling_centrum, run_logs_handled, run_to_end
from atrapy.preparation import PERIOD

URL = f"/api/periods/{PERIOD}/quantities-to-fill"
N_AP = (
    *("N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"),
    *("AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN", "AO", "AP"),
)
WORKER = "adrian.testowy"


def _completed(row: int) -> str:
    return f"wymiana gniazdka OPIS-SYN-{row}"


def _prepared(tmp_path: Path) -> PreparingCentrum:
    return filling_centrum(
        tmp_path,
        columns=lambda index, row: {
            "WYKONAWCA": WORKER,
            "UMOWA": f"u UM-SYN-{index:03d}",
            "CZYNNOŚCI ZREALIZOWANE": _completed(row),
        },
    )


def _table(centrum: PreparingCentrum, kind: str) -> dict[str, Any]:
    return centrum.view(f"{URL}/{kind}")


def _write(centrum: PreparingCentrum, cells: dict[str, int | str | None]) -> None:
    path = centrum.fixture.collective_file_path
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for cell, value in cells.items():
        sheet[cell] = value
    workbook.save(path)


def _shown(row: dict[str, Any]) -> dict[str, tuple[str, int | str]]:
    """Komórki wiersza, które coś pokazują: litera kolumny → (czyja wartość, wartość)."""

    assert len(row["cells"]) == len(N_AP)
    return {
        column: (cell["source"], cell["value"])
        for column, cell in zip(N_AP, row["cells"], strict=True)
        if cell != {"source": "empty", "value": 0}
    }


def _texts(table: dict[str, Any], row: dict[str, Any]) -> dict[str, str]:
    return dict(zip(table["text_columns"], row["texts"], strict=True))


def test_tabela_wierszy_bez_reguly_ma_teksty_wierszy_i_szare_wartosci_narzedzia(tmp_path: Path) -> None:
    table = _table(_prepared(tmp_path), "without_rule")

    assert table["state"] == "ready"
    assert table["hint"] == "Dopisz ilości poza V, T i N."
    assert [row["row"] for row in table["rows"]] == [19, 22]
    first = table["rows"][0]
    assert table["text_columns"] == ["WYKONAWCA", "URZĄDZENIA", "CZYNNOŚCI", "CZYNNOŚCI ZREALIZOWANE"]
    assert (first["state"], first["texts"]) == ("to_fill", [WORKER, "przeniesienie", "instalacja", _completed(19)])
    # Dojazd w V i drukowanie umowy „u” w T; usterki po godzinach nie ma, więc N narzędzia to 0.
    assert _shown(first) == {"N": ("tool", 0), "T": ("tool", 1), "V": ("tool", 1)}


def test_naglowek_ma_kazda_kolumne_n_ap_z_nazwa_pozycji_cennika_z_wiersza_17(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"O17": "  Instalacja i aktywacja   Internet "})

    columns = _table(centrum, "from_description")["columns"]

    names = {column["column"]: column["name"] for column in columns}
    assert [column["column"] for column in columns] == list(N_AP)
    # Syntetyczny Wzorzec ma nazwy tylko w N i AP; O dopisał tata.
    assert names == dict.fromkeys(N_AP, "") | {
        "N": "instalacja",
        "O": "Instalacja i aktywacja Internet",
        "AP": "demontaż",
    }


def test_wartosc_taty_wraca_zielona_i_robi_wiersz_a_zero_nie(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"O19": 2, "AE22": 0, "Y22": "0"})

    rows = {row["row"]: row for row in _table(centrum, "without_rule")["rows"]}

    assert (rows[19]["state"], _shown(rows[19])["O"]) == ("done", ("tata", 2))
    assert rows[22]["state"] == "to_fill"
    assert "AE" not in _shown(rows[22])
    assert "Y" not in _shown(rows[22])


def test_wartosc_taty_w_kolumnie_narzedzia_wraca_z_pliku_szara_i_nie_robi_wiersza(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"V19": 5, "N22": 45, "T22": 0})

    rows = {row["row"]: row for row in _table(centrum, "without_rule")["rows"]}

    assert [rows[19]["state"], rows[22]["state"]] == ["to_fill", "to_fill"]
    assert _shown(rows[19])["V"] == ("tool", 5)
    assert (_shown(rows[22])["N"], _shown(rows[22])["T"]) == (("tool", 45), ("tool", 0))


def test_wiersz_z_opisu_nie_ma_wartosci_narzedzia_a_tekst_taty_jest_nieliczbowy(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"N20": 45, "AB21": "dwa"})

    table = _table(centrum, "from_description")

    rows = {row["row"]: row for row in table["rows"]}
    assert list(rows) == [20, 21]
    assert (rows[20]["state"], _shown(rows[20])) == ("done", {"N": ("tata", 45)})
    assert (rows[21]["state"], _shown(rows[21])) == ("done", {"AB": ("tata", "nieliczbowa")})
    assert _texts(table, rows[21])["URZĄDZENIA"] == ""


def test_plik_bez_odczytu_daje_komunikat_na_stronie_rodzaju(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.write_bytes(b"")

    table = _table(centrum, "without_rule")

    assert table["state"] == "problem"
    assert table["message"]["what"]


def test_nieznany_rodzaj_jest_odrzucony(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    assert centrum.client.get(f"{URL}/description_columns").status_code == 422


def test_strona_rodzaju_nie_niesie_adresu_numeru_zlecenia_ani_umowy(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    for kind in ("without_rule", "from_description"):
        shown = centrum.client.get(f"{URL}/{kind}").text
        # Każdy adres, NUMER ZL., UMOWA i NUMER UMOWY syntetycznego Rejestru ma znacznik „SYN-”.
        assert "SYN-" not in shown.replace("OPIS-SYN-", "")
        assert "OPIS-SYN-" in shown


def test_po_odczycie_strony_rodzaju_teksty_wierszy_nie_wychodza_z_komputera(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    for kind in ("without_rule", "from_description"):
        _table(centrum, kind)
    timing = view_timing(
        page="uzupelnienie", requests=[{"operation": "getKindTable", "browser_ms": 310, "server_ms": 280}]
    )
    assert centrum.client.post("/api/view-timings", json=timing).status_code == 204
    centrum.engines.fail_engine = True
    second = run_to_end(centrum, dry_run=True)["run"]["id"]
    run_logs_handled(centrum)
    diagnosis = centrum.client.post(f"/api/runs/{second}/diagnosis")
    assert diagnosis.status_code == 200, diagnosis.text
    draft = diagnosis.json()["report"]

    run_logs = sorted(centrum.tool.run_logs.glob("*"))
    assert run_logs, "Uruchomienia mają Logi Uruchomienia"
    log = centrum.log_path.read_text(encoding="utf-8")
    assert "getKindTable:310/280" in log
    # Kopia wejścia niesie wiersze, które Uruchomienie Przygotowania przeczytało z Rejestru (reguła danych, ADR 0025, #841),
    # a nie odczyt strony rodzaju, więc poza nią w Logach tekstów wierszy nie ma.
    logs = [{**json.loads(path.read_text(encoding="utf-8")), "input_copy": None} for path in run_logs]
    for text in (log, draft["title"] + draft["body"], *(json.dumps(record, ensure_ascii=False) for record in logs)):
        assert "SYN-" not in text
        assert WORKER not in text


def test_tekst_wiersza_jest_bez_spacji_na_brzegach(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"K19": "  wymiana gniazdka  "})

    table = _table(centrum, "without_rule")
    [first, _] = table["rows"]

    assert _texts(table, first)["CZYNNOŚCI ZREALIZOWANE"] == "wymiana gniazdka"


def test_bez_naglowka_czynnosci_zrealizowane_tabela_ma_pusty_opis(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"K17": None})

    table = _table(centrum, "without_rule")

    assert table["state"] == "ready"
    assert [
        (row["row"], _texts(table, row)["CZYNNOŚCI ZREALIZOWANE"], _texts(table, row)["URZĄDZENIA"]) for row in table["rows"]
    ] == [
        (19, "", "przeniesienie"),
        (22, "", "router x9"),
    ]
