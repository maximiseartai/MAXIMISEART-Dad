from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
import threading
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import tool_files
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.activity_legend import LEGEND, LEGEND_FILE
from rozliczenia.centrum.settings.folders import FOLDERS, SETTINGS_FILE, FolderSettings
from rozliczenia.centrum.settings.history import ByDad, History, HistoryRow, RowChange
from rozliczenia.centrum.settings.memory import Memory, Remembered
from rozliczenia.centrum.settings.owner import REPORTED_CHANGES, CentrumSettings, read_snapshot
from rozliczenia.centrum.settings.proposal import Edit, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings.quantity_exceptions import EXCEPTIONS, EXCEPTIONS_FILE
from rozliczenia.centrum.settings.quantity_rules import DEVICES_FILE, RULES_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.wall_clock import local_now
from rozliczenia.workbook_files import file_bytes
from tests.fixtures.bez_dostepu import without_reading
from tests.fixtures.centrum import Centrum, CentrumClient, FakeGitHub, FakeOneDrive, ToolDirectory, centrum_app, finished_view
from tests.fixtures.centrum import centrum as fresh_centrum
from tests.fixtures.centrum_processes import (
    FILLING_DEVICES,
    WORKER_SETTLEMENTS,
    PreparingCentrum,
    Surroundings,
    filling_centrum,
    preparing_centrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
    write_dad_quantity_rules,
)
from atrapy.pliki_taty import REGISTER_NAME
from atrapy.preparation import COLLECTIVE_FILE_NAME, PERIOD, register_order, write_collective_template, write_register
from atrapy.settlement import CellValue, write_quantity_source, write_template

URL = f"/api/periods/{PERIOD}/quantities-to-fill"
LOG_EVENT = "uzupelnienie-odczyt-nieudany"
DESCRIPTION = ("Y", "AB", "AD", "AJ", "AK", "AL", "AM")


def _prepared(
    tmp_path: Path, devices: dict[int, str] = FILLING_DEVICES, *, surroundings: Surroundings | None = None
) -> PreparingCentrum:
    return filling_centrum(
        tmp_path, devices, columns=lambda index, _row: {"UMOWA": f"u UM-SYN-{index:03d}"}, surroundings=surroundings
    )


def _kinds(view: dict[str, Any]) -> dict[str, list[tuple[int, bool]]]:
    return {kind["kind"]: [(row["row"], row["state"] == "done") for row in kind["rows"]] for kind in view["kinds"]}


def _states(view: dict[str, Any]) -> dict[str, list[tuple[int, str]]]:
    return {kind["kind"]: [(row["row"], row["state"]) for row in kind["rows"]] for kind in view["kinds"]}


def _kind_done(view: dict[str, Any]) -> dict[str, bool]:
    return {kind["kind"]: kind["done"] for kind in view["kinds"]}


def _description(view: dict[str, Any]) -> dict[str, int]:
    return {column["column"]: column["rows"] for column in view["description_columns"]}


def _edit(path: Path, change: Callable[[Worksheet, dict[str, str]], None]) -> None:
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    header = {str(cell.value): get_column_letter(cell.column) for cell in sheet[17] if cell.value is not None}
    change(sheet, header)
    workbook.save(path)


def _write(path: Path, cells: dict[str, int | float | str | None]) -> None:
    def change(sheet: Worksheet, _header: dict[str, str]) -> None:
        for cell, value in cells.items():
            sheet[cell] = value

    _edit(path, change)


def _collective_file(centrum: PreparingCentrum) -> Path:
    return centrum.fixture.collective_file_path


def test_po_przygotowaniu_wiersze_bez_reguly_i_z_opisu_czekaja_na_tate(tmp_path: Path) -> None:
    view = _prepared(tmp_path).view(URL)

    assert view["state"] == "ready"
    assert _kinds(view) == {
        "without_rule": [(19, False), (22, False)],
        "from_description": [(20, False), (21, False)],
    }
    assert _kind_done(view) == {"without_rule": False, "from_description": False}
    assert {kind["kind"]: kind["hint"] for kind in view["kinds"]} == {
        "without_rule": "Dopisz ilości poza V, T i N.",
        "from_description": "Wpisz ilości według opisu technika.",
    }
    assert _description(view) == dict.fromkeys(DESCRIPTION, 0)


def test_uzupelnienie_liczy_regulami_ilosci_z_ustawien_wiec_nowy_skladnik_zdejmuje_wiersz_bez_reguly_a_t_po_usunietej_regule_jest_wpisem_taty(
    tmp_path: Path,
) -> None:
    centrum = _prepared(tmp_path)
    write_dad_quantity_rules(centrum.tool, DEVICES_FILE, "  - {id: fut, zapisy: [fut], grupa: tv}\n", "  - {id: przeniesienie, zapisy: [przeniesienie]}\n")
    write_dad_quantity_rules(
        centrum.tool,
        RULES_FILE,
        "  - {id: t-umowa-u, zakres: kazde, jesli: [{rodzaj: umowa, slowo: u}], to: {rodzaj: wpisz, wpisy: [{kolumna: T, wartosc: 1, razy: raz}]}}\n",
        "",
    )

    view = centrum.view(URL)
    table = centrum.view(f"{URL}/without_rule")
    window = centrum.view(f"/api/periods/{PERIOD}/without-quantity")

    assert _kinds(view)["without_rule"] == [(22, True)]
    assert [(row["row"], row["state"]) for row in table["rows"]] == [(22, "done")]
    assert (_hints(view)["without_rule"], table["hint"]) == ("Dopisz ilości poza V i N.", "Dopisz ilości poza V i N.")
    assert window["sentence"] == "2 wiersze bez ilości: 20, 21"


def _hints(view: dict[str, Any]) -> dict[str, str]:
    return {kind["kind"]: kind["hint"] for kind in view["kinds"]}


def test_ilosc_taty_poza_v_t_i_n_robi_wiersz_bez_reguly_a_dowolna_w_n_ap_wiersz_z_opisu(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"O19": 1, "AP21": 2})

    view = centrum.view(URL)

    assert _kinds(view) == {
        "without_rule": [(19, True), (22, False)],
        "from_description": [(20, False), (21, True)],
    }


def test_v_t_i_n_nie_robia_wiersza_bez_reguly_ale_robia_wiersz_z_opisu(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"N19": 45, "T22": 1, "V22": 1, "N20": 45})

    view = centrum.view(URL)

    assert _kinds(view)["without_rule"] == [(19, False), (22, False)]
    assert _kinds(view)["from_description"] == [(20, True), (21, False)]


def test_zero_i_pusta_komorka_to_to_samo(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"O19": 0, "Y20": "0", "AB21": None, "AE22": 0.0})

    view = centrum.view(URL)

    assert _kinds(view) == {
        "without_rule": [(19, False), (22, False)],
        "from_description": [(20, False), (21, False)],
    }
    assert _description(view) == dict.fromkeys(DESCRIPTION, 0)


def test_rodzaj_jest_zrobiony_gdy_kazdy_jego_wiersz_jest_zrobiony(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"O19": 1, "Z22": "dwa", "Y20": 1})

    view = centrum.view(URL)

    assert _kind_done(view) == {"without_rule": True, "from_description": False}


def test_rodzaj_bez_wierszy_jest_zrobiony(tmp_path: Path) -> None:
    view = _prepared(tmp_path, {18: "nokia zte", 19: "gniazdo"}).view(URL)

    assert _kinds(view) == {"without_rule": [], "from_description": []}
    assert _kind_done(view) == {"without_rule": True, "from_description": True}


def test_kolumny_z_opisu_licza_wiersze_z_wpisem_taty_w_kazdej_kolumnie(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"Y18": 1, "Y19": 2, "Y20": 0, "AB21": 1, "AM22": "dwa", "AK18": 1})

    view = centrum.view(URL)

    assert _description(view) == {"Y": 2, "AB": 1, "AD": 0, "AJ": 0, "AK": 1, "AL": 0, "AM": 1}


def test_ak_wyznaczone_przez_regule_nie_liczy_sie_jak_wpis_taty(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path, {18: "technicolor", 19: "przeniesienie"})
    _write(_collective_file(centrum), {"AK19": 1})

    view = centrum.view(URL)

    assert _description(view)["AK"] == 1


def test_usuniecie_wiersza_w_excelu_przenumerowuje_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"O22": 1})
    _edit(_collective_file(centrum), lambda sheet, _header: sheet.delete_rows(19))

    view = centrum.view(URL)

    assert _kinds(view) == {
        "without_rule": [(21, True)],
        "from_description": [(19, False), (20, False)],
    }


def test_wyczyszczony_wiersz_nie_przesuwa_numerow_pozostalych(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    def change(sheet: Worksheet, _header: dict[str, str]) -> None:
        for cell in sheet[19]:
            cell.value = None

    _edit(_collective_file(centrum), change)

    view = centrum.view(URL)

    assert _kinds(view) == {
        "without_rule": [(22, False)],
        "from_description": [(20, False), (21, False)],
    }


def test_zmiana_urzadzen_przenosi_wiersz_miedzy_rodzajami_a_v_i_t_z_przygotowania_robia_z_niego_zrobiony_wiersz_z_opisu(
    tmp_path: Path,
) -> None:
    centrum = _prepared(tmp_path)

    def change(sheet: Worksheet, header: dict[str, str]) -> None:
        sheet[f"{header['URZĄDZENIA']}19"] = "prewencja"
        sheet[f"{header['URZĄDZENIA']}20"] = "zyxel"
        sheet[f"{header['URZĄDZENIA']}21"] = "pralka"

    _edit(_collective_file(centrum), change)

    view = centrum.view(URL)

    assert _kinds(view) == {
        "without_rule": [(21, False), (22, False)],
        "from_description": [(19, True)],
    }


def test_wiersz_bez_daty_w_data_nie_ma_rodzaju_a_jego_kolumny_z_opisu_sie_licza(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    def change(sheet: Worksheet, header: dict[str, str]) -> None:
        sheet[f"{header['DATA']}19"] = "wtorek"
        sheet["Y19"] = 1

    _edit(_collective_file(centrum), change)

    view = centrum.view(URL)

    assert _kinds(view)["without_rule"] == [(22, False)]
    assert _description(view)["Y"] == 1


def test_plik_otwarty_w_excelu_jest_czytany(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = _collective_file(centrum)
    _write(path, {"O19": 1})
    path.with_name(f"~${path.name}").write_bytes(b"blokada Excela")

    view = centrum.view(URL)

    assert _kinds(view)["without_rule"] == [(19, True), (22, False)]
    assert centrum.log_lines(LOG_EVENT) == []


def test_odpowiedz_i_dziennik_nie_niosa_tresci_wierszy(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    shown = centrum.client.get(URL).text
    path = _collective_file(centrum)
    path.write_bytes(b"")
    centrum.client.get(URL)
    logged = "\n".join(centrum.log_lines(LOG_EVENT))

    for text in (shown, logged):
        assert "SYN-" not in text
        assert "przeniesienie" not in text
        assert "prewencja" not in text
    assert logged != ""


def _problem(centrum: PreparingCentrum, *, collective_file_exists: bool) -> dict[str, str]:
    view = centrum.view(URL)
    assert (view["state"], view["collective_file_exists"]) == ("problem", collective_file_exists)
    message: dict[str, str] = view["message"]
    return message


def test_uszkodzony_plik_zbiorczy_daje_komunikat_i_wpis_w_dzienniku(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = _collective_file(centrum)
    path.write_bytes(b"to nie jest skoroszyt")
    path.with_name(f"~${path.name}").write_bytes(b"blokada Excela")

    message = _problem(centrum, collective_file_exists=True)

    assert message["what"] == "Plik zbiorczy jest uszkodzony albo nie jest skoroszytem Excela."
    assert message["where"] == f"plik {COLLECTIVE_FILE_NAME}, folder {PERIOD}"
    [line] = centrum.log_lines(LOG_EVENT)
    assert f"okres={PERIOD} przyczyna=USZKODZONY_PLIK_ZBIORCZY excel=tak typ=BadZipFile" in line


@pytest.mark.skipif(sys.platform == "win32", reason="chmod w Windows nie odbiera prawa odczytu")
def test_niedostepny_plik_zbiorczy_nie_jest_nazwany_uszkodzonym(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = _collective_file(centrum)
    path.chmod(0)
    try:
        message = _problem(centrum, collective_file_exists=True)
    finally:
        path.chmod(0o644)

    assert message["what"].startswith("Nie można teraz odczytać Pliku zbiorczego.")
    assert message["where"] == f"plik {COLLECTIVE_FILE_NAME}, folder {PERIOD}"
    assert "uszkodzon" not in message["what"] + message["action"]
    [line] = centrum.log_lines(LOG_EVENT)
    assert "przyczyna=NIEDOSTEPNY_PLIK_ZBIORCZY excel=nie typ=PermissionError" in line


@pytest.mark.skipif(sys.platform == "win32", reason="chmod w Windows nie odbiera prawa odczytu")
def test_folder_okresu_bez_odczytu_daje_komunikat_bez_stanu_blokady(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    folder = _collective_file(centrum).parent
    folder.chmod(0)
    try:
        message = _problem(centrum, collective_file_exists=False)
    finally:
        folder.chmod(0o755)

    assert message["what"].startswith("Nie można teraz odczytać Pliku zbiorczego.")
    [line] = centrum.log_lines(LOG_EVENT)
    assert "excel=nieznany" in line


def test_plik_tylko_w_chmurze_daje_komunikat_onedrive(tmp_path: Path) -> None:
    onedrive = FakeOneDrive()
    centrum = _prepared(tmp_path, surroundings=Surroundings(onedrive=onedrive))
    path = _collective_file(centrum)
    onedrive.online_only.add(path)
    path.write_bytes(b"")

    message = _problem(centrum, collective_file_exists=True)

    assert message["what"] == "Plik zbiorczy jest tylko w OneDrive w chmurze, bez kopii na tym komputerze."
    assert message["where"] == f"plik {COLLECTIVE_FILE_NAME}, folder {PERIOD}"


def test_brak_pliku_zbiorczego_daje_komunikat(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _collective_file(centrum).unlink()

    message = _problem(centrum, collective_file_exists=False)

    assert message["what"] == "Nie ma Pliku zbiorczego tego okresu."
    [line] = centrum.log_lines(LOG_EVENT)
    assert "przyczyna=BRAK_PLIKU_ZBIORCZEGO excel=nie typ=-" in line


def test_brak_naglowka_urzadzen_nazywa_naglowek(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    def change(sheet: Worksheet, header: dict[str, str]) -> None:
        sheet[f"{header['URZĄDZENIA']}17"] = None
        sheet[f"{header['UMOWA']}17"] = None

    _edit(_collective_file(centrum), change)

    message = _problem(centrum, collective_file_exists=True)

    assert message["what"] == "Brakuje nagłówka w Pliku zbiorczym: UMOWA i URZĄDZENIA w wierszu 17."
    [line] = centrum.log_lines(LOG_EVENT)
    assert "przyczyna=BRAK_NAGLOWKA_PLIKU_ZBIORCZEGO" in line


def test_brak_naglowka_wykonawca_nazywa_komorke(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(_collective_file(centrum), {"H17": None})

    message = _problem(centrum, collective_file_exists=True)

    assert message["what"] == "Brakuje nagłówka w Pliku zbiorczym: WYKONAWCA w komórce H17."


def test_okres_bez_folderu_okresu_daje_komunikat_o_braku_pliku_zbiorczego(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    view = centrum.client.get("/api/periods/15_21_09_2026/quantities-to-fill").json()

    assert (view["state"], view["collective_file_exists"]) == ("problem", False)
    assert view["message"]["what"] == "Nie ma Pliku zbiorczego tego okresu."


@pytest.mark.parametrize("unreadable", [RULES_FILE, DEVICES_FILE, LEGEND_FILE])
def test_plik_regul_ilosci_listy_urzadzen_albo_legendy_bez_odczytu_to_odmowa_uzupelnienia_a_nie_plik_z_wydania(
    tmp_path: Path, unreadable: str
) -> None:
    centrum = _prepared(tmp_path)
    write_dad_quantity_rules(centrum.tool, DEVICES_FILE, "  - {id: fut, zapisy: [fut], grupa: tv}\n", "  - {id: przeniesienie, zapisy: [przeniesienie]}\n")
    write_dad_quantity_rules(
        centrum.tool,
        RULES_FILE,
        "  - {id: t-umowa-u, zakres: kazde, jesli: [{rodzaj: umowa, slowo: u}], to: {rodzaj: wpisz, wpisy: [{kolumna: T, wartosc: 1, razy: raz}]}}\n",
        "",
    )
    (tool_files.config_dir(tmp_path) / LEGEND_FILE).write_bytes(LEGEND.dump(DEFAULT_ACTIVITY_LEGEND.codes))
    window_url = f"/api/periods/{PERIOD}/without-quantity"
    assert (centrum.view(URL)["state"], centrum.view(window_url)["state"]) == ("ready", "read")
    sentence = {"message": f"Pliku {unreadable} w folderze config nie da się teraz przeczytać. Zamknij program, który może trzymać plik, i spróbuj ponownie."}

    with without_reading(tool_files.config_dir(tmp_path) / unreadable):
        summary = centrum.client.get(URL)
        table = centrum.client.get(f"{URL}/without_rule")
        window = centrum.client.get(window_url)

    assert (summary.status_code, summary.json(), table.status_code, table.json()) == (409, sentence, 409, sentence)
    assert window.json() == {"state": "unread"}


def test_zly_token_okresu_i_brak_folderu_okresow_sa_odmowa(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    wrong = centrum.client.get("/api/periods/nie-okres/quantities-to-fill")
    centrum.fixture.periods_directory.rename(tmp_path / "przeniesiony")
    without_periods = centrum.client.get(URL)

    assert (wrong.status_code, wrong.json()["message"]) == (404, "Nie ma takiego okresu.")
    assert (without_periods.status_code, without_periods.json()["message"]) == (409, "Najpierw wskaż folder okresów.")


def test_po_przebiegu_rozliczen_wiersze_bez_wpisu_taty_sa_bez_ilosci_na_kazdej_stronie(tmp_path: Path) -> None:
    centrum = filling_centrum(tmp_path)
    write_template(tool_files.config_dir(tmp_path) / tool_files.WORKER_TEMPLATE.name)
    path = _collective_file(centrum)
    _write(path, {"O19": 1})
    before = centrum.view(URL)

    started = centrum.client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "RUN"})
    assert started.status_code == 200, started.text
    assert finished_view(centrum.client)["result"]["result"] == "OK"
    assert (path.parent / WORKER_SETTLEMENTS).is_dir()
    after = centrum.view(URL)
    table = centrum.view(f"{URL}/without_rule")
    window = centrum.view(f"/api/periods/{PERIOD}/without-quantity")

    assert (before["settled"], _states(before)) == (
        False,
        {"without_rule": [(19, "done"), (22, "to_fill")], "from_description": [(20, "to_fill"), (21, "to_fill")]},
    )
    assert (after["settled"], _states(after)) == (
        True,
        {
            "without_rule": [(19, "done"), (22, "without_quantity")],
            "from_description": [(20, "without_quantity"), (21, "without_quantity")],
        },
    )
    assert _kind_done(after) == {"without_rule": False, "from_description": False}
    assert (table["settled"], [(row["row"], row["state"]) for row in table["rows"]]) == (
        True,
        [(19, "done"), (22, "without_quantity")],
    )
    assert window["sentence"] == "3 wiersze bez ilości: 20, 21, 22"


QUANTITY_RULES_URL = "/api/settings/quantity-rules"
DIFFERENCES_URL = f"{QUANTITY_RULES_URL}/differences"
DEVICES_URL = "/api/settings/devices"
WORKERS_URL = "/api/settings/workers"
EDITOR_RULE: dict[str, Any] = {
    "scope": "known",
    "conditions": [
        {"kind": "component", "component": "gniazdo", "negated": False},
        {"kind": "activities", "text": "montaż", "negated": False},
    ],
    "action": {"kind": "fill", "writes": [{"column": "AA", "value": 2, "multiplier": "once", "component": None}]},
}
CONTRACT_RULE = "  - {id: t-umowa-u, zakres: kazde, jesli: [{rodzaj: umowa, slowo: u}], to: {rodzaj: wpisz, wpisy: [{kolumna: T, wartosc: 1, razy: raz}]}}\n"
FAULT_ROW: dict[str, CellValue] = {"C": "pr", "D": "usterka", "G": datetime(2026, 9, 11, 16, 30), "V": 1, "AI": 1, "N": 45}


def _history(client: CentrumClient) -> list[dict[str, Any]]:
    response = client.get("/api/settings/history")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["rows"]
    return rows


def _rule_ids(client: CentrumClient) -> list[str]:
    return [rule["id"] for rule in client.get(QUANTITY_RULES_URL).json()["rules"]]


def _config_files(config: Path) -> dict[str, bytes]:
    return {path.relative_to(config).as_posix(): path.read_bytes() for path in sorted(config.rglob("*")) if path.is_file()}


def _added_rule_row(app: Centrum) -> str:
    saved = app.client.post(QUANTITY_RULES_URL, json=EDITOR_RULE)
    assert saved.status_code == 200, saved.text
    return str(saved.json()["change"])


@pytest.mark.parametrize(
    ("method", "url"),
    [
        pytest.param("PUT", lambda _row: f"{QUANTITY_RULES_URL}/regula-1", id="zmiana-reguly"),
        pytest.param("DELETE", lambda _row: f"{QUANTITY_RULES_URL}/regula-1", id="usuniecie-reguly"),
        pytest.param("POST", lambda row: f"/api/settings/history/{row}/undo", id="cofniecie-dodania-reguly"),
    ],
)
def test_zmiana_reguly_taty_przy_pliku_regul_bez_odczytu_to_409_o_tym_pliku_a_nie_odpowiedz_z_regul_z_wydania(
    tmp_path: Path, method: str, url: Any
) -> None:
    app = fresh_centrum(tmp_path)
    row = _added_rule_row(app)
    rules = app.tool.config / RULES_FILE
    before = rules.read_bytes()

    with without_reading(rules):
        response = app.client.request(method, url(row), json=EDITOR_RULE if method == "PUT" else None)

    assert (response.status_code, response.json()) == (409, {"message": settings_messages.unreadable(RULES_FILE)})
    assert rules.read_bytes() == before


def test_cofniecie_recznego_utworzenia_pliku_ustawien_spoza_centrum_przywraca_brak_pliku(tmp_path: Path) -> None:
    app = fresh_centrum(tmp_path)
    assert app.client.get("/api/settings").status_code == 200
    app.settings_path.write_bytes(FOLDERS.dump(replace(FOLDERS.default, theme="light")))
    [row] = _history(app.client)

    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert (row["source"], row["undoable"]) == ("outside", True)
    assert undone.status_code == 200, undone.text
    assert not app.settings_path.exists()


def test_reguly_zmienione_poza_centrum_przy_liscie_urzadzen_bez_odczytu_okno_pokazuje_ostatnie_dobre_reguly_taty(
    tmp_path: Path,
) -> None:
    app = fresh_centrum(tmp_path)
    assert app.client.post(DEVICES_URL, json={"name": "ont y", "other_spellings": [], "group": None}).status_code == 200
    _added_rule_row(app)
    write_dad_quantity_rules(app.tool, RULES_FILE, "", "")

    with without_reading(app.tool.config / DEVICES_FILE):
        shown = _rule_ids(app.client)

    assert "regula-1" in shown


def test_przy_pamieci_listy_wykonawcow_ktorej_tresci_regula_juz_nie_przyjmuje_zla_lista_nie_ma_ostatniej_dobrej_i_proces_nie_startuje(
    tmp_path: Path,
) -> None:
    centrum_ = settling_centrum(tmp_path)
    assert centrum_.client.get("/api/settings").status_code == 200
    refused = b"schema_version: 1\nwykonawcy:\n  - {nazwa: Jan, loginy: []}\n"
    centrum_.tool.worker_list.write_bytes(refused)
    Memory(centrum_.tool.config, lambda _: None).write(WORKERS_FILE, Remembered(seen=refused, good=refused))

    started_run = centrum_.client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "DRY-RUN"})

    assert (started_run.status_code, started_run.json()) == (
        409,
        {
            "message": f"Lista Wykonawców ma złe ustawienie: {settings_messages.worker_without_login()} Szczegóły są w "
            "Ustawieniach, w sekcji Wykonawcy.",
            "field": "wykonawcy[0].loginy",
        },
    )


def _light_theme(_inputs: ReleaseInputs[FolderSettings]) -> Edit[FolderSettings]:
    return Edit(lambda current: replace(current, theme="light"))


def test_start_centrum_pyta_o_wersje_narzedzia_tylko_gdy_ma_zmiane_z_wydania_do_zastosowania(tmp_path: Path) -> None:
    asked: list[str] = []

    def wydanie(local: str) -> None:
        asked.append(local)

    freshness = replace(FakeGitHub().freshness(), wydanie=wydanie)
    tool = ToolDirectory(tmp_path / "narzedzie-taty")
    change = ReleaseChange("2026-11-motyw-jasny-proba", FOLDERS, _light_theme)
    counts = []
    for _start in range(2):
        client = CentrumClient(centrum_app(tool, tool_freshness=freshness, release_changes=(change,)))
        client.start()
        client.stop()
        counts.append(len(asked))

    assert counts == [1, 1]


def test_zgloszenie_podaje_najwyzej_tyle_najnowszych_zmian_ustawien_ile_mowi_jego_limit(tmp_path: Path) -> None:
    centrum_ = preparing_centrum(tmp_path)
    history = History(centrum_.tool.config, lambda _: None)
    for number in range(1, REPORTED_CHANGES + 2):
        history.append(
            HistoryRow(
                id=f"wiersz-{number:02d}",
                at=local_now() - timedelta(minutes=REPORTED_CHANGES + 2 - number),
                source=ByDad(),
                undoes=None,
                file=SETTINGS_FILE,
                section="foldery",
                changes=(RowChange(key="foldery.folder_okresow", before=None, after=str(tmp_path / f"Folder-{number:02d}")),),
                secret=False,
                undoable=True,
                result="zapisano",
                reason=None,
                created=False,
                removed=False,
            )
        )
    run_id = stopped_for_maks(centrum_)

    response = centrum_.client.post(f"/api/runs/{run_id}/diagnosis")

    assert response.status_code == 200, response.text
    lines = response.json()["report"]["body"].splitlines()
    start = lines.index("## Zmiany Ustawień (30 dni)") + 2
    section = lines[start : lines.index("", start)]
    assert [line.rsplit(" ", 1)[1] for line in section] == [f"Folder-{number:02d}" for number in range(REPORTED_CHANGES + 1, 1, -1)]


def test_odmowa_reguly_ze_skladnikiem_spoza_listy_urzadzen_nazywa_kolumne_pozycja_cennika_z_wzorca(tmp_path: Path) -> None:
    app = fresh_centrum(tmp_path)
    app.tool.config.mkdir(parents=True)
    template = write_collective_template(app.tool.configuration.collective_template)
    workbook = load_workbook(template)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet["Z17"] = "ONT  Nokia\nz montażem"
    workbook.save(template)
    rule = {
        "scope": "known",
        "conditions": [{"kind": "component", "component": "ont q", "negated": False}],
        "action": {"kind": "fill", "writes": [{"column": "Z", "value": 3, "multiplier": "component", "component": "ont q"}]},
    }

    refused = app.client.post(QUANTITY_RULES_URL, json=rule)

    assert (refused.status_code, refused.json()) == (
        422,
        {
            "message": "Reguła potrzebuje składnika „ont q”, którego nie ma na Liście Urządzeń: Jeśli URZĄDZENIA zawierają "
            "„ont q”, to wpisz 3 × liczbę „ont q” w ONT Nokia z montażem (Z). Najpierw dodaj ten składnik w sekcji Urządzenia.",
            "field": "jesli[0].skladnik",
        },
    )


def test_migawka_narzedzi_maksa_niczego_nie_zapisuje_wiec_centrum_dalej_widzi_reczna_zmiane_jako_zmiane_spoza_centrum(
    tmp_path: Path,
) -> None:
    app = fresh_centrum(tmp_path)
    assert app.client.get("/api/settings").status_code == 200
    app.settings_path.write_bytes(FOLDERS.dump(replace(FOLDERS.default, theme="light")))
    before = _config_files(app.tool.config)

    snapshot = read_snapshot(app.tool.config)

    assert snapshot.folders.theme == "light"
    assert _config_files(app.tool.config) == before
    assert [row["source"] for row in _history(app.client)] == ["outside"]


def test_regula_dodana_i_usunieta_poza_centrum_zostawia_swoje_id_w_historii_wiec_cofniecie_usuniecia_nie_rusza_reguly_dodanej_potem(
    tmp_path: Path,
) -> None:
    app = fresh_centrum(tmp_path)
    assert app.client.get(QUANTITY_RULES_URL).status_code == 200
    outside_rule = CONTRACT_RULE.replace("t-umowa-u", "regula-1").replace("slowo: u}", "slowo: proba}")
    write_dad_quantity_rules(app.tool, RULES_FILE, CONTRACT_RULE, CONTRACT_RULE + outside_rule)
    assert "regula-1" in _rule_ids(app.client)
    write_dad_quantity_rules(app.tool, RULES_FILE, "", "")
    [removed, _added] = _history(app.client)

    saved = app.client.post(QUANTITY_RULES_URL, json=EDITOR_RULE)
    undone = app.client.post(f"/api/settings/history/{removed['id']}/undo")

    assert saved.status_code == 200, saved.text
    assert saved.json()["quantity_rules"]["rules"][-1]["id"] == "regula-2"
    assert undone.status_code == 200, undone.text
    assert {"regula-1", "regula-2"} <= set(_rule_ids(app.client))


def test_plik_wyjatkow_kontroli_ilosci_bez_odczytu_ma_zdanie_o_tresci_z_wydania_a_nie_odmowie(tmp_path: Path) -> None:
    app = fresh_centrum(tmp_path)
    exceptions = app.tool.config / EXCEPTIONS_FILE
    exceptions.parent.mkdir(parents=True)
    exceptions.write_bytes(EXCEPTIONS.dump(()))

    with without_reading(exceptions):
        response = app.client.get(DIFFERENCES_URL)

    assert response.status_code == 200, response.text
    assert response.json()["exceptions_problem"] == {"field": None, "message": settings_messages.unavailable(EXCEPTIONS_FILE)}


def test_zly_plik_wyjatkow_kontroli_ilosci_dalej_ukrywa_roznice_wyjatkiem_z_ostatniego_dobrego_pliku(tmp_path: Path) -> None:
    centrum_ = settling_centrum(tmp_path)
    write_quantity_source(centrum_.collective_file, [FAULT_ROW])
    run_to_end(centrum_, dry_run=False)
    [difference] = centrum_.client.get(DIFFERENCES_URL).json()["differences"]
    marked = centrum_.client.post(f"{DIFFERENCES_URL}/{difference['id']}/exception")
    assert marked.status_code == 200, marked.text
    (centrum_.tool.config / EXCEPTIONS_FILE).write_bytes(b"wyjatki: [")

    found = centrum_.client.get(DIFFERENCES_URL).json()

    assert (found["differences"], found["exceptions"]) == ([], 1)
    assert found["exceptions_problem"] == {"field": None, "message": settings_messages.damaged(EXCEPTIONS_FILE)}


def test_okresy_przy_usuwaniu_wykonawcy_sprawdzaja_sie_poza_blokada_ustawien_wiec_okno_ustawien_nie_czeka_na_pliki_zbiorcze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owners: list[CentrumSettings] = []
    readers: list[threading.Thread] = []
    read_while_checking: list[bool] = []

    def source(path: Path) -> bytes:
        if owners and not readers:
            reader = threading.Thread(target=owners[0].view, daemon=True)
            readers.append(reader)
            reader.start()
            reader.join(timeout=5)
            read_while_checking.append(not reader.is_alive())
        return file_bytes(path)

    change_workers = CentrumSettings.change_workers

    def captured(settings: CentrumSettings, edit: Any) -> Any:
        owners.append(settings)
        return change_workers(settings, edit)

    register = tmp_path / "Rejestr" / REGISTER_NAME
    register.parent.mkdir()
    write_register(register, [register_order(1, datetime(2026, 9, 8, 10), worker="adrian.testowy")])
    centrum_ = settling_centrum(tmp_path, surroundings=Surroundings(source=source), register=register)
    monkeypatch.setattr(CentrumSettings, "change_workers", captured)

    removed = centrum_.client.delete(f"{WORKERS_URL}/kamil.syntetyczny")
    for reader in readers:
        reader.join(timeout=5)

    assert removed.status_code == 200, removed.text
    assert read_while_checking == [True]
