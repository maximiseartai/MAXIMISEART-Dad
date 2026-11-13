"""Centrum rozliczeń przez jego HTTP API, tak jak widzi je przeglądarka taty."""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, get_args

from fastapi.testclient import TestClient
import pytest

from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import collective_file_name_with
from rozliczenia.period_folder import PeriodFolder, PeriodFolderInaccessible
from rozliczenia import efenix_process
from rozliczenia.centrum import app
from rozliczenia.centrum.app import STATIC_DIRECTORY
from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.centrum.dad_action_journal import DAD_ACTIONS_FILE
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, OLD_NOTES_FILE, OLD_REPORTS_FILE
from rozliczenia.centrum.notifications import NOTIFICATIONS_FILE
from rozliczenia.centrum.outbox import ADDRESSES_FILE, QUEUE_DIRECTORY
from rozliczenia.centrum.keyed_box import REPORT_KEY_FILE
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY
from rozliczenia.centrum.run_origins import CENTRUM_RUNS_FILE
from rozliczenia.telemetry import CompletedResult, MetricsStore, RecordedStop, metric_record
from rozliczenia.tool_files import CONFIG_DIR, LOG_PATH
from rozliczenia.centrum.settings import history as history_module
from rozliczenia.centrum.settings.folders import FOLDERS, SETTINGS_FILE, FolderSettings
from rozliczenia.centrum.settings.history import HISTORY_FILE
from rozliczenia.centrum.settings.memory import APPLIED_FILE, MEMORY_DIRECTORY, settings_bytes
from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.centrum.settings.release_changes import (
    Edit,
    Later,
    Nothing,
    Proposal,
    Refuse,
    ReleaseChange,
    ReleaseInputs,
)
from rozliczenia.centrum.tool_freshness import ToolFreshness
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS, without_access
from tests.fixtures.centrum import (
    CENTRUM,
    TOOL_COMMIT,
    Centrum,
    CentrumClient,
    FakePlatform,
    ROOT,
    ToolDirectory,
    centrum,
    centrum_app,
    view_timing,
)
from tests.fixtures.tool_clone import tool_repository

import export_openapi


def test_health_przedstawia_centrum_rozliczen_ze_skroconym_commitem_i_identyfikatorem_startu(tmp_path: Path) -> None:
    first = centrum(tmp_path).client.get("/api/health")
    again = centrum(tmp_path).client.get("/api/health")

    assert first.status_code == 200
    health = first.json()
    assert health | {"instance": None} == {
        "service": "centrum-rozliczen",
        "commit": TOOL_COMMIT[:7],
        "instance": None,
    }
    assert len(health["instance"]) == 32
    assert again.json()["instance"] != health["instance"]


def test_ten_sam_serwer_podaje_zbudowane_centrum_bez_node(tmp_path: Path) -> None:
    response = centrum(tmp_path).client.get("/")

    assert response.status_code == 200
    assert "<title>Centrum rozliczeń</title>" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_po_aktualizacji_narzedzia_przegladarka_dostaje_nowy_pakiet_pod_ta_sama_nazwa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = tmp_path / "static"
    shutil.copytree(STATIC_DIRECTORY, static)
    monkeypatch.setattr(app, "STATIC_DIRECTORY", static)
    client = centrum(tmp_path).client
    page = client.get("/")
    bundle = client.get("/assets/index.js")

    unchanged = client.get("/assets/index.js", headers={"If-None-Match": bundle.headers["etag"]})
    (static / "assets" / "index.js").write_bytes(b"console.log('po aktualizacji')\n")
    updated = client.get("/assets/index.js", headers={"If-None-Match": bundle.headers["etag"]})

    assert '<script type="module" crossorigin src="/assets/index.js">' in page.text
    assert {page.headers["cache-control"], bundle.headers["cache-control"]} == {"no-cache"}
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (updated.status_code, updated.content) == (200, b"console.log('po aktualizacji')\n")


def _exported_contract(tmp_path: Path) -> dict[str, Any]:
    assert export_openapi.main(output=tmp_path / "openapi.json") == 0
    return dict(json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8")))


def test_kontrakt_ma_trasy_i_schematy_po_kolei_wiec_dwie_nowe_trasy_nie_zmieniaja_tego_samego_miejsca(tmp_path: Path) -> None:
    contract = _exported_contract(tmp_path)
    schemas = contract["components"]["schemas"]

    assert (list(contract["paths"]), list(schemas)) == (sorted(contract["paths"]), sorted(schemas))


def _committed_contract() -> dict[str, Any]:
    return dict(json.loads((ROOT / "frontend" / "src" / "api" / "openapi.json").read_text(encoding="utf-8")))


def test_frontend_parsuje_odpowiedzi_kontraktem_ktory_serwer_naprawde_eksportuje(tmp_path: Path) -> None:
    """Frontend parsuje każdą odpowiedź serwera schematami wygenerowanymi z ``frontend/src/api/openapi.json``."""

    assert _exported_contract(tmp_path) == _committed_contract()


def _state_changing_actions() -> list[tuple[str, str]]:
    """Każda trasa kontraktu poza GET; odmowa Host i Origin zapada przed routingiem, więc parametr ścieżki
    może być byle jaki."""

    return [
        (method, re.sub(r"\{[^}]+\}", "x", path))
        for path, operations in _committed_contract()["paths"].items()
        for method in operations
        if method != "get"
    ]


def _passed_through(app: Centrum, headers: dict[str, str]) -> list[tuple[str, str]]:
    """Akcje z ``_state_changing_actions()``, które z ``headers`` nie dostały 403, i wpisy dziennika działań taty.

    Dziennik dostaje wpis za każdą akcję, zanim zadziała jej trasa, więc pusty dziennik znaczy, że odrzucone żądanie
    nie doszło do routingu. Pomiar widoku dostaje poprawne ciało: bez niego dziennik nic by nie wpisał."""

    allowed = []
    for method, path in _state_changing_actions():
        body = view_timing() if path == "/api/view-timings" else None
        if app.client.request(method, path, headers=headers, json=body).status_code != 403:
            allowed.append((method, path))
    journal = app.log_path.parent / DAD_ACTIONS_FILE
    entries = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
    return allowed + [("dziennik", entry) for entry in entries]


# Trasy, których przeglądarka nie mierzy przez `call` (frontend/src/api/client.ts), każda z powodem.
OUTSIDE_TIMING = {
    "streamRunEvents": "strumień SSE (EventSource) otwarty przez całe życie karty, nie zapytanie z odpowiedzią",
    "recordViewTiming": "sam pomiar widoku, wysyłany po pomiarze; odpowiedź 204 bez treści",
    "getCurrentRun": "przeglądarka bierze bieżące Uruchomienie ze strumienia; trasę czytają testy i weryfikacja",
}


def test_kazda_trasa_api_jest_operacja_pomiaru_widoku_albo_ma_powod_poza_pomiarem(tmp_path: Path) -> None:
    """``ApiOperation`` to dokładnie trasy API poza ``OUTSIDE_TIMING``; dziennik działań taty zapisuje przycisk tylko
    pod operacją z ``ApiOperation``, więc jedyna trasa poza nią, która coś zmienia, to sam pomiar widoku."""

    paths = _exported_contract(tmp_path)["paths"].values()
    methods = {operation["operationId"]: method for path in paths for method, operation in path.items()}
    listed = get_args(timing_contract.ApiOperation)

    assert sorted(listed) == sorted(methods.keys() - OUTSIDE_TIMING.keys())
    assert len(set(listed)) == len(listed)
    assert OUTSIDE_TIMING.keys() <= methods.keys()
    assert {name for name in OUTSIDE_TIMING if methods[name] != "get"} == {"recordViewTiming"}


def test_zadanie_z_obcym_naglowkiem_host_jest_odrzucone(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    # Origin zgodny z obcym Host: tak wygląda zapytanie strony obcej domeny przemapowanej w DNS na 127.0.0.1.
    foreign = {"Host": "zly.example:47811", "Origin": "http://zly.example:47811"}

    response = app.client.get("/api/health", headers=foreign)
    allowed = _passed_through(app, foreign)

    assert response.status_code == 403
    assert "commit" not in response.text
    assert allowed == []


def test_localhost_jest_dozwolonym_naglowkiem_host(tmp_path: Path) -> None:
    client = centrum(tmp_path).client

    response = client.get("/api/health", headers={"Host": "localhost:47811"})

    assert response.status_code == 200


NOT_SET = {"state": "not_set"}
UNREADABLE = {"state": "unreadable"}
DAMAGED = "Plik centrum-ustawienia.yaml w folderze config ma uszkodzoną treść. Zapisz Ustawienia jeszcze raz."
REGISTER_PATH = "Rejestr zleceń to plik Excel .xlsx podany pełną ścieżką. Wybierz go oknem wyboru."
PERIODS_PATH = "Folder okresów trzeba podać pełną ścieżką. Wybierz go oknem wyboru."


def test_brak_pliku_ustawien_znaczy_nie_ustawiono(tmp_path: Path) -> None:
    response = centrum(tmp_path).client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {"order_register": NOT_SET, "periods_directory": NOT_SET, "theme": "dark", "folders_problem": None}


def test_wskazany_rejestr_zlecen_i_folder_okresow_sa_zapamietane(tmp_path: Path) -> None:
    register = tmp_path / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    register.touch()
    periods = tmp_path / "INEA"
    periods.mkdir()
    first = centrum(tmp_path)
    first.platform.chosen_files.append(register)
    first.platform.chosen_folders.append(periods)

    register_choice = first.client.post("/api/settings/register/choose")
    periods_choice = first.client.post("/api/settings/periods-directory/choose")
    after_restart = centrum(tmp_path).client.get("/api/settings").json()

    assert register_choice.json()["settings"]["order_register"]["path"] == str(register)
    assert periods_choice.json()["settings"] == after_restart
    assert after_restart["order_register"] == {
        "state": "ready",
        "path": str(register),
        "name": "ZLECENIA INTERMAX OD 08_11_2021.xlsx",
    }
    assert after_restart["periods_directory"] == {"state": "ready", "path": str(periods), "name": "INEA"}
    assert first.platform.dialog_titles == ["Wybierz plik Rejestru zleceń", "Wybierz folder okresów (np. Załączniki albo INEA)"]


def test_anulowane_okno_wyboru_nie_zmienia_ustawien(tmp_path: Path) -> None:
    periods = tmp_path / "INEA"
    periods.mkdir()
    app = centrum(tmp_path)
    app.platform.chosen_folders.extend([periods, None])
    app.client.post("/api/settings/periods-directory/choose")

    response = app.client.post("/api/settings/periods-directory/choose")

    assert response.json()["settings"]["periods_directory"]["path"] == str(periods)


def test_uszkodzony_plik_ustawien_bez_dobrej_tresci_to_zle_ustawienie_z_wartosciami_domyslnymi(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.settings_path.parent.mkdir(parents=True)
    app.settings_path.write_text("rejestr: [nie zamknięta lista\n", encoding="utf-8")

    response = app.client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "order_register": NOT_SET,
        "periods_directory": NOT_SET,
        "theme": "dark",
        "folders_problem": {"field": None, "message": DAMAGED},
    }


def test_nieistniejacy_zapamietany_folder_okresow_jest_wyraznie_oznaczony(tmp_path: Path) -> None:
    periods = tmp_path / "INEA"
    periods.mkdir()
    app = centrum(tmp_path)
    app.platform.chosen_folders.append(periods)
    app.client.post("/api/settings/periods-directory/choose")
    periods.rmdir()

    response = app.client.get("/api/settings")

    assert response.json()["periods_directory"] == {"state": "missing", "path": str(periods), "name": "INEA"}


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_rejestr_zlecen_i_folder_okresow_w_folderze_bez_dostepu_sa_nieczytelne_a_nie_brakujace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    """Ustawienia taty mówią o nich to, co Diagnoza („Nie da się teraz odczytać”), a nie „Nie ma już” ani błąd."""

    onedrive = tmp_path / "OneDrive"
    register = onedrive / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    periods = onedrive / "INEA"
    periods.mkdir(parents=True)
    register.touch()
    app = centrum(tmp_path)
    app.platform.chosen_files.append(register)
    app.platform.chosen_folders.append(periods)
    app.client.post("/api/settings/register/choose")
    app.client.post("/api/settings/periods-directory/choose")
    path_checks(monkeypatch)

    with without_access(onedrive):
        response = app.client.get("/api/settings")

    assert (response.status_code, response.json()) == (
        200,
        {
            "order_register": {"state": "inaccessible", "path": str(register), "name": register.name},
            "periods_directory": {"state": "inaccessible", "path": str(periods), "name": "INEA"},
            "theme": "dark",
            "folders_problem": None,
        },
    )


@NO_ACCESS_ON_WINDOWS
def test_niedostepny_plik_ustawien_nie_udaje_niewskazanych_sciezek(tmp_path: Path) -> None:
    """Plik Ustawień taty trzymany np. przez antywirus: wskazanych ścieżek nie widać, ale nie są „nie wskazano”."""

    app, _ = with_periods_directory(tmp_path)

    app.settings_path.chmod(0)
    try:
        response = app.client.get("/api/settings")
    finally:
        app.settings_path.chmod(0o644)

    assert (response.status_code, response.json()) == (
        200,
        {"order_register": UNREADABLE, "periods_directory": UNREADABLE, "theme": "dark", "folders_problem": None},
    )


@NO_ACCESS_ON_WINDOWS
@pytest.mark.parametrize("choice", ["register/choose", "periods-directory/choose"])
def test_anulowane_okno_wyboru_przy_niedostepnym_pliku_ustawien_nie_udaje_niewskazanych_sciezek(
    tmp_path: Path, choice: str
) -> None:
    app, _ = with_periods_directory(tmp_path)
    app.platform.chosen_files.append(None)
    app.platform.chosen_folders.append(None)

    app.settings_path.chmod(0)
    try:
        response = app.client.post(f"/api/settings/{choice}")
    finally:
        app.settings_path.chmod(0o644)

    assert (response.status_code, response.json()["settings"]) == (
        200,
        {"order_register": UNREADABLE, "periods_directory": UNREADABLE, "theme": "dark", "folders_problem": None},
    )


@pytest.mark.parametrize(
    "local_file",
    [
        CONFIG_DIR / SETTINGS_FILE,
        CONFIG_DIR / HISTORY_FILE,
        CONFIG_DIR / MEMORY_DIRECTORY / f"{SETTINGS_FILE}.json",
        LOG_PATH,
        CONFIG_DIR / CENTRUM_RUNS_FILE,
        CONFIG_DIR / REPORT_KEY_FILE,
        CONFIG_DIR / DAD_CASES_FILE,
        CONFIG_DIR / OLD_REPORTS_FILE,
        CONFIG_DIR / UNSENT_DIRECTORY / QUEUE_DIRECTORY / "20261024T101500000000Z-0001-zgloszenie-3f2a9c1b.json",
        CONFIG_DIR / OLD_NOTES_FILE,
        CONFIG_DIR / NOTIFICATIONS_FILE,
        CONFIG_DIR / ADDRESSES_FILE,
        CONFIG_DIR / "plik-z-przyszlej-wersji.json",
    ],
    ids=[
        "ustawienia-centrum",
        "historia-ustawien",
        "pamiec-ustawien",
        "dziennik-centrum",
        "dziennik-uruchomien-z-centrum",
        "klucz-do-zgloszen",
        "sprawy-taty",
        "wyslane-zgloszenia",
        "zgloszenie-w-kolejce",
        "uwagi-taty",
        "przeczytane-powiadomienia",
        "adresy-w-skrzynce",
        "kazdy-nowy-plik-w-config",
    ],
)
def test_lokalne_pliki_taty_sa_poza_gitem(local_file: Path) -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", str(local_file.relative_to(ROOT))], cwd=ROOT, check=False
    )

    assert ignored.returncode == 0


def test_motyw_jasny_jest_zapamietany(tmp_path: Path) -> None:
    centrum(tmp_path).client.put("/api/settings/theme", json={"theme": "light"})

    response = centrum(tmp_path).client.get("/api/settings")

    assert response.json()["theme"] == "light"


SETTINGS_NOT_SAVED = (
    "Nie udało się zapisać Ustawień taty w folderze config. Sprawdź, czy folder otwiera się w Eksploratorze plików, "
    "nie jest tylko do odczytu i czy OneDrive działa, potem spróbuj ponownie."
)


@pytest.mark.parametrize(
    "content",
    [
        "schema_version: 2\nrejestr_zlecen: Rejestr.xlsx\nfolder_okresow: INEA\n".encode(),
        "rejestr: [nie zamknięta lista\n".encode(),
        b"schema_version: 1\nmotyw: \xff\n",
    ],
    ids=["nowszy-schemat", "uszkodzony-yaml", "nie-utf-8"],
)
def test_zmiana_motywu_nadpisuje_plik_ustawien_ktorego_tresci_nie_da_sie_uzyc(tmp_path: Path, content: bytes) -> None:
    """Tata po cofnięciu Aktualizacji albo z uszkodzonym plikiem wskazuje Ustawienia jeszcze raz i pracuje dalej."""

    app = centrum(tmp_path)
    app.settings_path.parent.mkdir(parents=True)
    app.settings_path.write_bytes(content)

    changed = app.client.put("/api/settings/theme", json={"theme": "light"})

    assert changed.status_code == 200
    assert app.client.get("/api/settings").json() == {
        "order_register": NOT_SET,
        "periods_directory": NOT_SET,
        "theme": "light",
        "folders_problem": None,
    }


@NO_ACCESS_ON_WINDOWS
def test_zmiana_motywu_przy_niedostepnym_pliku_ustawien_nie_wymazuje_folderu_okresow(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    saved = app.settings_path.read_text(encoding="utf-8")

    app.settings_path.chmod(0)
    try:
        refused = app.client.put("/api/settings/theme", json={"theme": "light"})
    finally:
        app.settings_path.chmod(0o644)
    kept = app.settings_path.read_text(encoding="utf-8")
    again = app.client.put("/api/settings/theme", json={"theme": "light"})

    assert (refused.status_code, refused.json()) == (500, {"message": SETTINGS_NOT_SAVED})
    assert kept == saved
    assert "ustawienia-bez-zapisu przyczyna=dostep" in app.log_path.read_text(encoding="utf-8")
    assert (again.json()["theme"], again.json()["periods_directory"]["path"]) == ("light", str(periods))


@NO_ACCESS_ON_WINDOWS
def test_plik_ustawien_niedostepny_na_chwile_przyjmuje_zmiane_po_ponowieniu(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    periods = tmp_path / "INEA"
    periods.mkdir()
    pauses: list[float] = []

    def access_back(seconds: float) -> None:
        pauses.append(seconds)
        tool.settings.chmod(0o644)

    client = CentrumClient(centrum_app(tool, platform=FakePlatform(chosen_folders=[periods]), pause=access_back))
    client.post("/api/settings/periods-directory/choose")
    tool.settings.chmod(0)
    try:
        changed = client.put("/api/settings/theme", json={"theme": "light"})
    finally:
        tool.settings.chmod(0o644)

    assert (changed.json()["theme"], changed.json()["periods_directory"]["path"]) == ("light", str(periods))
    assert len(pauses) == 1


def history_rows(app: Centrum) -> list[dict[str, Any]]:
    response = app.client.get("/api/settings/history")
    assert response.status_code == 200
    rows: list[dict[str, Any]] = response.json()["rows"]
    return rows


def changes(rows: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    return [(row["source"], row["changes"]) for row in rows]


def test_zmiana_folderow_rejestru_i_motywu_ma_wiersz_historii_z_wartoscia_przed_i_po_a_w_dzienniku_bez_wartosci(
    tmp_path: Path,
) -> None:
    register = tmp_path / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    register.touch()
    periods = tmp_path / "INEA"
    periods.mkdir()
    app = centrum(tmp_path)
    app.platform.chosen_files.append(register)

    chosen = app.client.post("/api/settings/register/choose")
    saved = app.client.put("/api/settings/folders", json={"order_register": str(register), "periods_directory": str(periods)})
    app.client.put("/api/settings/theme", json={"theme": "light"})
    rows = history_rows(app)

    assert [(row["source"], row["section"], row["changes"], row["undoable"]) for row in rows] == [
        ("tata", "wyglad", [{"key": "wyglad.motyw", "before": "dark", "after": "light"}], True),
        ("tata", "foldery", [{"key": "foldery.folder_okresow", "before": None, "after": str(periods)}], True),
        ("tata", "foldery", [{"key": "foldery.rejestr_zlecen", "before": None, "after": str(register)}], True),
    ]
    assert [chosen.json()["change"], saved.json()["change"]] == [rows[2]["id"], rows[1]["id"]]
    log = app.log_path.read_text(encoding="utf-8")
    assert "ustawienia-zmiana plik=centrum-ustawienia.yaml klucze=foldery.folder_okresow zrodlo=tata" in log
    assert (str(periods) in log, register.name in log) == (False, False)


def test_zapis_bez_zmiany_nie_ma_wiersza_historii(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    same = app.client.put("/api/settings/theme", json={"theme": "dark"})

    assert (same.status_code, history_rows(app), app.settings_path.exists()) == (200, [], False)


def test_cofniecie_przywraca_wartosc_jako_nowy_wiersz_a_cofniecie_cofniecia_przywraca_zmiane(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.client.put("/api/settings/theme", json={"theme": "light"})
    [changed] = history_rows(app)

    undone = app.client.post(f"/api/settings/history/{changed['id']}/undo")
    redone = app.client.post(f"/api/settings/history/{undone.json()['change']}/undo")
    rows = history_rows(app)

    assert (undone.json()["settings"]["theme"], redone.json()["settings"]["theme"]) == ("dark", "light")
    assert [(row["undoes"], row["changes"]) for row in rows] == [
        (undone.json()["change"], [{"key": "wyglad.motyw", "before": "dark", "after": "light"}]),
        (changed["id"], [{"key": "wyglad.motyw", "before": "light", "after": "dark"}]),
        (None, [{"key": "wyglad.motyw", "before": "dark", "after": "light"}]),
    ]
    assert app.client.get("/api/settings").json()["theme"] == "light"


def test_cofniecie_zmiany_ktorej_nie_ma_w_historii_jest_odmowa(tmp_path: Path) -> None:
    refused = centrum(tmp_path).client.post("/api/settings/history/nie-ma-takiej/undo")

    assert (refused.status_code, refused.json()) == (
        404,
        {"message": "Tej zmiany nie ma w Historii Ustawień. Odśwież okno Ustawień."},
    )


@pytest.mark.parametrize(
    ("register", "periods", "problem"),
    [
        ("ZLECENIA INTERMAX.xlsx", None, {"message": REGISTER_PATH, "field": "rejestr_zlecen"}),
        ("rejestr.csv", None, {"message": REGISTER_PATH, "field": "rejestr_zlecen"}),
        (None, "INEA", {"message": PERIODS_PATH, "field": "folder_okresow"}),
    ],
    ids=["rejestr-bez-pelnej-sciezki", "rejestr-nie-xlsx", "folder-bez-pelnej-sciezki"],
)
def test_zla_wartosc_folderow_sie_nie_zapisuje_a_odmowa_ma_pole_i_zdanie(
    tmp_path: Path, register: str | None, periods: str | None, problem: dict[str, str]
) -> None:
    app, chosen = with_periods_directory(tmp_path)
    saved = app.settings_path.read_bytes()
    full = {"rejestr.csv": str(tmp_path / "rejestr.csv")}

    refused = app.client.put(
        "/api/settings/folders",
        json={"order_register": full.get(register or "", register), "periods_directory": periods or str(chosen)},
    )

    assert (refused.status_code, refused.json()) == (422, problem)
    assert (app.settings_path.read_bytes(), len(history_rows(app))) == (saved, 1)


def test_reczna_zmiana_pliku_ustawien_ma_jeden_wiersz_spoza_centrum_z_wartoscia_przed_i_po(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    other = tmp_path / "Załączniki"
    other.mkdir()
    app.settings_path.write_text(f"schema_version: 1\nfolder_okresow: '{other}'\nmotyw: light\n", encoding="utf-8")

    read = app.client.get("/api/settings")
    again = app.client.get("/api/settings")
    rows = history_rows(app)

    assert (read.status_code, read.json()["periods_directory"]["path"], read.json()["theme"]) == (200, str(other), "light")
    assert again.json() == read.json()
    assert changes(rows) == [
        (
            "outside",
            [
                {"key": "foldery.folder_okresow", "before": str(periods), "after": str(other)},
                {"key": "wyglad.motyw", "before": "dark", "after": "light"},
            ],
        ),
        ("tata", [{"key": "foldery.folder_okresow", "before": None, "after": str(periods)}]),
    ]
    assert rows[0]["undoable"] is True
    assert "ustawienia-spoza plik=centrum-ustawienia.yaml wynik=zapisano" in app.log_path.read_text(encoding="utf-8")


def test_historia_otwarta_zaraz_po_recznej_zmianie_pliku_ustawien_pokazuje_jej_wiersz(tmp_path: Path) -> None:
    """Tata otwiera Historię w oknie Ustawień, zanim cokolwiek innego przeczytało Ustawienia po zmianie Maksa."""

    app, periods = with_periods_directory(tmp_path)
    other = tmp_path / "Załączniki"
    other.mkdir()
    app.settings_path.write_text(f"schema_version: 1\nfolder_okresow: '{other}'\n", encoding="utf-8")

    assert changes(history_rows(app))[0] == (
        "outside",
        [{"key": "foldery.folder_okresow", "before": str(periods), "after": str(other)}],
    )


def test_zla_tresc_pliku_po_dobrej_to_zle_ustawienie_z_ostatnia_dobra_wartoscia_i_jednym_wierszem_bez_cofniecia(
    tmp_path: Path,
) -> None:
    app, periods = with_periods_directory(tmp_path)
    app.settings_path.write_text("schema_version: 1\nfolder_okresow: INEA\n", encoding="utf-8")

    first = app.client.get("/api/settings")
    second = app.client.get("/api/settings")
    rows = history_rows(app)
    undo = app.client.post(f"/api/settings/history/{rows[0]['id']}/undo")

    assert (first.status_code, first.json()) == (
        200,
        {
            "order_register": NOT_SET,
            "periods_directory": {"state": "ready", "path": str(periods), "name": "INEA"},
            "theme": "dark",
            "folders_problem": {"field": "folder_okresow", "message": PERIODS_PATH},
        },
    )
    assert second.json() == first.json()
    assert [(row["source"], row["refused"], row["undoable"], row["reason"]) for row in rows] == [
        ("outside", True, False, PERIODS_PATH),
        ("tata", False, True, None),
    ]
    assert (undo.status_code, undo.json()) == (404, {"message": "Tej zmiany nie da się cofnąć."})
    log = app.log_path.read_text(encoding="utf-8")
    assert log.count("ustawienia-zle plik=centrum-ustawienia.yaml pole=folder_okresow") == 1


def test_reczne_przepisanie_pliku_ustawien_z_tymi_samymi_wartosciami_ma_wiersz_bez_cofniecia(tmp_path: Path) -> None:
    app, _ = with_periods_directory(tmp_path)
    app.settings_path.write_bytes(b"# kopia Maksa\n" + app.settings_path.read_bytes())

    app.client.get("/api/settings")
    rows = history_rows(app)
    undo = app.client.post(f"/api/settings/history/{rows[0]['id']}/undo")

    assert [(row["source"], row["changes"], row["undoable"]) for row in rows[:1]] == [("outside", [], False)]
    assert (undo.status_code, undo.json()) == (404, {"message": "Tej zmiany nie da się cofnąć."})


def test_migawka_narzedzi_przy_zlej_tresci_pliku_ustawien_ma_ostatni_dobry_folder(tmp_path: Path) -> None:
    """``tools/proba_przypomnien.py`` czyta Ustawienia bez Centrum: zepsuty ręcznie plik nie zabiera mu folderu okresów."""

    app, periods = with_periods_directory(tmp_path)
    app.settings_path.write_text("schema_version: 1\nfolder_okresow: INEA\n", encoding="utf-8")

    assert read_snapshot(app.tool.config).folders.periods_directory == periods


def test_zla_tresc_potem_dobra_i_znow_ta_sama_zla_tresc_maja_po_wierszu_spoza_centrum(tmp_path: Path) -> None:
    """Maks psuje plik, naprawia go innym folderem i psuje tak samo jak za pierwszym razem: Historia mówi o każdym."""

    app, periods = with_periods_directory(tmp_path)
    other = tmp_path / "Załączniki"
    other.mkdir()
    bad = "schema_version: 1\nfolder_okresow: INEA\n"
    for content in (bad, f"schema_version: 1\nfolder_okresow: '{other}'\n", bad):
        app.settings_path.write_text(content, encoding="utf-8")
        view = app.client.get("/api/settings").json()
    rows = history_rows(app)

    assert (view["periods_directory"]["path"], view["folders_problem"]) == (
        str(other),
        {"field": "folder_okresow", "message": PERIODS_PATH},
    )
    assert [(row["source"], row["refused"], row["changes"]) for row in rows] == [
        ("outside", True, []),
        ("outside", False, [{"key": "foldery.folder_okresow", "before": str(periods), "after": str(other)}]),
        ("outside", True, []),
        ("tata", False, [{"key": "foldery.folder_okresow", "before": None, "after": str(periods)}]),
    ]


def test_plik_ustawien_usuniety_i_przywrocony_z_kopii_poza_centrum_ma_dwa_wiersze(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    saved = app.settings_path.read_bytes()

    app.settings_path.unlink()
    removed = app.client.get("/api/settings").json()
    app.settings_path.write_bytes(saved)
    restored = app.client.get("/api/settings").json()
    rows = history_rows(app)

    assert (removed["periods_directory"], restored["periods_directory"]["path"]) == (NOT_SET, str(periods))
    assert [(row["source"], row["removed"], row["changes"]) for row in rows[:2]] == [
        ("outside", False, [{"key": "foldery.folder_okresow", "before": None, "after": str(periods)}]),
        ("outside", True, [{"key": "foldery.folder_okresow", "before": str(periods), "after": None}]),
    ]


def test_cofniecie_usuniecia_pliku_ustawien_poza_centrum_przywraca_folder(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    app.settings_path.unlink()
    app.client.get("/api/settings")
    removal = history_rows(app)[0]

    undone = app.client.post(f"/api/settings/history/{removal['id']}/undo")

    assert (undone.status_code, undone.json()["settings"]["periods_directory"]["path"]) == (200, str(periods))
    assert [(row["source"], row["undoes"]) for row in history_rows(app)[:2]] == [
        ("tata", removal["id"]),
        ("outside", None),
    ]


def test_plik_ustawien_sprzed_wydania_jest_stanem_wyjsciowym_a_pozniejsza_reczna_zmiana_ma_wiersz(
    tmp_path: Path,
) -> None:
    """Pierwszy start wersji z Historią zastaje plik taty bez pamięci: przyjmuje go bez wiersza, a dalej już widzi zmiany."""

    periods = tmp_path / "INEA"
    other = tmp_path / "Załączniki"
    periods.mkdir()
    other.mkdir()
    app = centrum(tmp_path)
    app.settings_path.parent.mkdir(parents=True)
    app.settings_path.write_text(f"schema_version: 1\nfolder_okresow: '{periods}'\n", encoding="utf-8")

    first = app.client.get("/api/settings").json()
    rows_after_first = history_rows(app)
    app.settings_path.write_text(f"schema_version: 1\nfolder_okresow: '{other}'\n", encoding="utf-8")
    app.client.get("/api/settings")

    assert (first["periods_directory"]["path"], rows_after_first) == (str(periods), [])
    assert changes(history_rows(app)) == [
        ("outside", [{"key": "foldery.folder_okresow", "before": str(periods), "after": str(other)}])
    ]


def test_zapis_taty_przy_zlej_tresci_pliku_zmienia_ostatnia_dobra_wartosc(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    app.settings_path.write_text("schema_version: 1\nfolder_okresow: INEA\n", encoding="utf-8")

    changed = app.client.put("/api/settings/theme", json={"theme": "light"})

    assert (changed.status_code, changed.json()["periods_directory"]["path"], changed.json()["folders_problem"]) == (
        200,
        str(periods),
        None,
    )
    assert changes(history_rows(app))[0] == ("tata", [{"key": "wyglad.motyw", "before": "dark", "after": "light"}])


def test_zmiana_ktorej_wiersza_historii_nie_da_sie_dopisac_zostawia_plik_ustawien_bez_zmiany(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    saved = app.settings_path.read_bytes()
    history = app.tool.config / HISTORY_FILE
    history.unlink()
    history.mkdir()

    refused = app.client.put("/api/settings/theme", json={"theme": "light"})

    assert (refused.status_code, refused.json()) == (500, {"message": SETTINGS_NOT_SAVED})
    assert app.settings_path.read_bytes() == saved
    history.rmdir()
    assert app.client.get("/api/settings").json()["theme"] == "dark"
    assert history_rows(app) == []


def test_pierwszy_wybor_taty_ktorego_wiersza_historii_nie_da_sie_dopisac_nie_zostawia_pliku_ustawien(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    history = app.tool.config / HISTORY_FILE
    history.mkdir(parents=True)

    refused = app.client.put("/api/settings/theme", json={"theme": "light"})
    history.rmdir()
    after = app.client.get("/api/settings").json()

    assert (refused.status_code, refused.json()) == (500, {"message": SETTINGS_NOT_SAVED})
    assert (app.settings_path.exists(), after["theme"], history_rows(app)) == (False, "dark", [])


@pytest.mark.parametrize("bad", [False, True], ids=["dobra-tresc", "zla-tresc"])
def test_reczna_zmiana_przy_historii_ktorej_nie_da_sie_dopisac_dostaje_wiersz_przy_nastepnym_odczycie(
    tmp_path: Path, bad: bool
) -> None:
    """OneDrive albo antywirus trzyma Historię, gdy Maks zmienia plik ręcznie: zmiana działa, a wiersz dochodzi później."""

    app, periods = with_periods_directory(tmp_path)
    other = tmp_path / "Załączniki"
    other.mkdir()
    history = app.tool.config / HISTORY_FILE
    kept = history.read_bytes()
    history.unlink()
    history.mkdir()
    app.settings_path.write_text(f"schema_version: 1\nfolder_okresow: '{'INEA' if bad else other}'\n", encoding="utf-8")

    held = app.client.get("/api/settings").json()
    history.rmdir()
    history.write_bytes(kept)
    app.client.get("/api/settings")
    app.client.get("/api/settings")
    rows = history_rows(app)

    assert held["periods_directory"]["path"] == str(periods if bad else other)
    assert [(row["source"], row["refused"]) for row in rows] == [("outside", bad), ("tata", False)]
    assert rows[0]["changes"] == (
        [] if bad else [{"key": "foldery.folder_okresow", "before": str(periods), "after": str(other)}]
    )


@NO_ACCESS_ON_WINDOWS
def test_reczna_zmiana_przy_nieczytelnej_pamieci_ustawien_dostaje_wiersz_gdy_pamiec_wroci(tmp_path: Path) -> None:
    """Pamięci, której system nie daje czytać, Centrum nie zgaduje: zapis taty czeka, a ręczna zmiana nie ginie."""

    app, periods = with_periods_directory(tmp_path)
    other = tmp_path / "Załączniki"
    other.mkdir()
    memory = app.tool.config / MEMORY_DIRECTORY / f"{SETTINGS_FILE}.json"
    app.settings_path.write_text(f"schema_version: 1\nfolder_okresow: '{other}'\n", encoding="utf-8")

    memory.chmod(0)
    try:
        read = app.client.get("/api/settings")
        refused = app.client.put("/api/settings/theme", json={"theme": "light"})
    finally:
        memory.chmod(0o644)
    app.client.get("/api/settings")

    assert (read.json()["periods_directory"]["path"], refused.status_code) == (str(other), 500)
    assert changes(history_rows(app)) == [
        ("outside", [{"key": "foldery.folder_okresow", "before": str(periods), "after": str(other)}]),
        ("tata", [{"key": "foldery.folder_okresow", "before": None, "after": str(periods)}]),
    ]


@NO_ACCESS_ON_WINDOWS
def test_plik_historii_zajety_na_chwile_przyjmuje_wiersz_po_ponowieniu(tmp_path: Path) -> None:
    """Antywirus trzyma Historię Ustawień przez chwilę: zmiana taty wchodzi z wierszem, a nie kończy się odmową."""

    tool = ToolDirectory(tmp_path)
    periods = tmp_path / "INEA"
    periods.mkdir()
    history = tool.config / HISTORY_FILE
    pauses: list[float] = []

    def access_back(seconds: float) -> None:
        pauses.append(seconds)
        history.chmod(0o644)

    client = CentrumClient(centrum_app(tool, platform=FakePlatform(chosen_folders=[periods]), pause=access_back))
    client.post("/api/settings/periods-directory/choose")
    history.chmod(0)
    try:
        changed = client.put("/api/settings/theme", json={"theme": "light"})
    finally:
        history.chmod(0o644)
    rows = client.get("/api/settings/history").json()["rows"]

    assert (changed.status_code, changed.json()["theme"]) == (200, "light")
    assert [row["changes"][0]["key"] for row in rows] == ["wyglad.motyw", "foldery.folder_okresow"]
    assert len(pauses) == 1


def test_urwana_linia_historii_jest_pominieta_i_policzona(tmp_path: Path) -> None:
    app, _ = with_periods_directory(tmp_path)
    with (app.tool.config / HISTORY_FILE).open("a", encoding="utf-8") as history:
        history.write('{"v":1,"id":"urwa')

    app.client.put("/api/settings/theme", json={"theme": "light"})
    read = app.client.get("/api/settings/history").json()

    assert ([row["changes"][0]["key"] for row in read["rows"]], read["skipped"]) == (
        ["wyglad.motyw", "foldery.folder_okresow"],
        1,
    )


def config_bytes(config: Path) -> dict[str, bytes]:
    """Każdy plik folderu ``config`` z jego bajtami, po ścieżce względem ``config``."""

    return {path.relative_to(config).as_posix(): path.read_bytes() for path in sorted(config.rglob("*")) if path.is_file()}


def started(tool: ToolDirectory, changes: tuple[ReleaseChange[Any], ...], **options: Any) -> CentrumClient:
    """Centrum uruchomione jak u taty na katalogu narzędzia ``tool``, z Wydaniem, które niesie zmiany ``changes``."""

    client = CentrumClient(centrum_app(tool, release_changes=changes, **options))
    client.start()
    return client


def light_theme(_inputs: ReleaseInputs[FolderSettings]) -> Edit[FolderSettings]:
    return Edit(lambda current: replace(current, theme="light"))


LIGHT_THEME = ReleaseChange("2026-11-motyw-jasny", FOLDERS, light_theme)


def test_start_centrum_z_wydania_bez_zmian_ustawien_zostawia_pliki_config_bajt_w_bajt(tmp_path: Path) -> None:
    app, _ = with_periods_directory(tmp_path)
    app.client.put("/api/settings/theme", json={"theme": "light"})
    app.client.stop()
    before = config_bytes(app.tool.config)

    started(app.tool, ()).stop()
    started(app.tool, ()).stop()

    assert config_bytes(app.tool.config) == before


def test_zmiana_ustawien_z_wydania_wchodzi_raz_z_numerem_wydania_w_historii_a_tata_ja_cofa(tmp_path: Path) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    freshness = ToolFreshness.of_clone(repository.clone, repository.github_releases, repository.published)
    tool = ToolDirectory(tmp_path / "narzedzie-taty")

    first = started(tool, (LIGHT_THEME,), tool_freshness=freshness)
    [applied] = first.get("/api/settings/history").json()["rows"]
    theme = first.get("/api/settings").json()["theme"]
    first.stop()
    second = started(tool, (LIGHT_THEME,), tool_freshness=freshness)
    undone = second.post(f"/api/settings/history/{applied['id']}/undo")
    second.stop()
    after_undo = config_bytes(tool.config)
    third = started(tool, (LIGHT_THEME,), tool_freshness=freshness)
    rows = third.get("/api/settings/history").json()["rows"]
    third_theme = third.get("/api/settings").json()["theme"]
    third.stop()

    assert theme == "light"
    assert (applied["source"], applied["release"], applied["changes"], applied["undoable"]) == (
        "release",
        {"version": "0.1.0", "commit": repository.head()[:7], "change": "2026-11-motyw-jasny"},
        [{"key": "wyglad.motyw", "before": "dark", "after": "light"}],
        True,
    )
    assert (undone.status_code, undone.json()["settings"]["theme"]) == (200, "dark")
    assert [(row["source"], row["undoes"]) for row in rows] == [("tata", applied["id"]), ("release", None)]
    assert (third_theme, config_bytes(tool.config)) == ("dark", after_undo)
    log = tool.log_path.read_text(encoding="utf-8")
    assert "ustawienia-zmiana plik=centrum-ustawienia.yaml klucze=wyglad.motyw zrodlo=wydanie" in log
    assert log.count("ustawienia-wydanie zmiana=2026-11-motyw-jasny wynik=zastosowano") == 1


def test_uszkodzona_pamiec_zmian_z_wydan_wstrzymuje_zmiany_zeby_cofnieta_nie_weszla_drugi_raz(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    memory = tool.config / MEMORY_DIRECTORY / APPLIED_FILE
    memory.parent.mkdir(parents=True)
    memory.write_text('{"schema_version": 1, "zmiany": {"2026-11-motyw-jas', encoding="utf-8")

    client = started(tool, (LIGHT_THEME,))
    theme = client.get("/api/settings").json()["theme"]
    rows = client.get("/api/settings/history").json()["rows"]
    client.stop()

    assert (theme, rows) == ("dark", [])
    assert "ustawienia-wydanie zmiana=2026-11-motyw-jasny wynik=bez-pamieci" in tool.log_path.read_text(encoding="utf-8")


def test_zmiana_ustawien_z_wydania_bez_cofniecia_nie_ma_cofnij(tmp_path: Path) -> None:
    def migrated(_inputs: ReleaseInputs[FolderSettings]) -> Edit[FolderSettings]:
        return Edit(lambda current: replace(current, theme="light"), undoable=False)

    client = started(ToolDirectory(tmp_path), (ReleaseChange("2026-11-migracja", FOLDERS, migrated),))
    [row] = client.get("/api/settings/history").json()["rows"]
    undo = client.post(f"/api/settings/history/{row['id']}/undo")

    assert (row["source"], row["undoable"]) == ("release", False)
    assert (undo.status_code, undo.json()) == (404, {"message": "Tej zmiany nie da się cofnąć."})


def bad_periods_directory(_inputs: ReleaseInputs[FolderSettings]) -> Edit[FolderSettings]:
    return Edit(lambda current: replace(current, periods_directory=Path("INEA")))


WORKERS_MISSING = "Listy Wykonawców nie ma, bo pliku identyfikatorów nie da się przeczytać."


def refused(_inputs: ReleaseInputs[FolderSettings]) -> Refuse:
    return Refuse(WORKERS_MISSING)


@pytest.mark.parametrize(
    ("propose", "reason"),
    [(bad_periods_directory, PERIODS_PATH), (refused, WORKERS_MISSING)],
    ids=["zla-wartosc", "odmowa-zmiany"],
)
def test_zmiana_ustawien_z_wydania_ktora_nie_przechodzi_sprawdzen_nie_wchodzi_a_historia_mowi_dlaczego(
    tmp_path: Path, propose: Callable[[ReleaseInputs[FolderSettings]], Proposal[FolderSettings]], reason: str
) -> None:
    app, _ = with_periods_directory(tmp_path)
    app.client.stop()
    saved = app.settings_path.read_bytes()
    change = ReleaseChange("2026-11-zla-zmiana", FOLDERS, propose)

    started(app.tool, (change,)).stop()
    again = started(app.tool, (change,))
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert app.settings_path.read_bytes() == saved
    assert [(row["source"], row["refused"], row["undoable"], row["reason"]) for row in rows] == [
        ("release", True, False, reason),
        ("tata", False, True, None),
    ]
    assert rows[0]["release"]["change"] == "2026-11-zla-zmiana"
    assert "ustawienia-wydanie zmiana=2026-11-zla-zmiana wynik=odrzucono" in app.log_path.read_text(encoding="utf-8")


def test_zmiana_ustawien_z_wydania_odlozona_na_pozniej_wraca_przy_nastepnym_starcie(tmp_path: Path) -> None:
    attachments = tmp_path / "Załączniki"

    def periods_from_attachments(_inputs: ReleaseInputs[FolderSettings]) -> Proposal[FolderSettings]:
        if not attachments.is_dir():
            return Later("OneDrive nie oddał jeszcze folderu Załączniki")
        return Edit(lambda current: replace(current, periods_directory=attachments))

    tool = ToolDirectory(tmp_path / "narzedzie-taty")
    change = ReleaseChange("2026-11-folder-zalaczniki", FOLDERS, periods_from_attachments)

    started(tool, (change,)).stop()
    later = config_bytes(tool.config)
    attachments.mkdir()
    again = started(tool, (change,))
    rows = again.get("/api/settings/history").json()["rows"]
    periods = again.get("/api/settings").json()["periods_directory"]
    again.stop()

    assert [name for name in (SETTINGS_FILE, HISTORY_FILE, f"{MEMORY_DIRECTORY}/{APPLIED_FILE}") if name in later] == []
    assert ([row["source"] for row in rows], periods["path"]) == (["release"], str(attachments))
    assert "ustawienia-wydanie zmiana=2026-11-folder-zalaczniki wynik=pozniej" in tool.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "proposal",
    [Nothing(), Edit(lambda current: replace(current, theme="dark"))],
    ids=["nic-do-zmiany", "edycja-bez-roznicy"],
)
def test_zmiana_ustawien_z_wydania_bez_niczego_do_zmiany_nie_wraca_i_nie_ma_wiersza(
    tmp_path: Path, proposal: Proposal[FolderSettings]
) -> None:
    asked: list[str] = []

    def nothing(_inputs: ReleaseInputs[FolderSettings]) -> Proposal[FolderSettings]:
        asked.append("zapytana")
        return proposal

    tool = ToolDirectory(tmp_path)
    change = ReleaseChange("2026-11-nic", FOLDERS, nothing)

    started(tool, (change,)).stop()
    again = started(tool, (change,))
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (asked, rows) == (["zapytana"], [])
    assert "ustawienia-wydanie zmiana=2026-11-nic wynik=bez-zmian" in tool.log_path.read_text(encoding="utf-8")


def test_zmiana_ustawien_z_wydania_ktorej_nie_da_sie_zapisac_wraca_przy_nastepnym_starcie(tmp_path: Path) -> None:
    app, _ = with_periods_directory(tmp_path)
    app.client.stop()
    saved = app.settings_path.read_bytes()
    history = app.tool.config / HISTORY_FILE
    rows_before = history.read_bytes()
    history.unlink()
    history.mkdir()

    started(app.tool, (LIGHT_THEME,)).stop()
    blocked = app.settings_path.read_bytes()
    history.rmdir()
    history.write_bytes(rows_before)
    again = started(app.tool, (LIGHT_THEME,))
    theme = again.get("/api/settings").json()["theme"]
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (blocked, theme) == (saved, "light")
    assert [row["source"] for row in rows] == ["release", "tata"]
    log = app.log_path.read_text(encoding="utf-8")
    assert log.index("zmiana=2026-11-motyw-jasny wynik=bez-zapisu") < log.index("zmiana=2026-11-motyw-jasny wynik=zastosowano")


@contextmanager
def read_only_memory(tool: ToolDirectory) -> Iterator[None]:
    """Folder pamięci Ustawień tylko do odczytu do końca bloku: żaden zapis pamięci się nie udaje."""

    memory = tool.config / MEMORY_DIRECTORY
    memory.mkdir(parents=True, exist_ok=True)
    memory.chmod(0o555)
    try:
        yield
    finally:
        memory.chmod(0o755)


@contextmanager
def unreadable_history(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Do końca bloku system nie daje czytać pliku Historii (jak plik trzymany przez OneDrive), a dopisanie wiersza działa:
    zmiana z Wydania, która mimo to by weszła, zapisuje się, więc widać ją w motywie i w wierszach Historii."""

    def locked(path: Path) -> bytes | None | OSError:
        if path.name == HISTORY_FILE:
            return PermissionError(errno.EACCES, "plik trzymany przez system", str(path))
        return settings_bytes(path)

    with monkeypatch.context() as patch:
        patch.setattr(history_module, "settings_bytes", locked)
        yield


def applied_and_undone(tool: ToolDirectory) -> tuple[dict[str, Any], str]:
    """Start, w którym zmiana z Wydania ``LIGHT_THEME`` wchodzi, a tata ją cofa: jej wiersz Historii i motyw po cofnięciu."""

    first = started(tool, (LIGHT_THEME,))
    [applied] = first.get("/api/settings/history").json()["rows"]
    undone: str = first.post(f"/api/settings/history/{applied['id']}/undo").json()["settings"]["theme"]
    first.stop()
    return applied, undone


@NO_ACCESS_ON_WINDOWS
def test_zmiana_z_wydania_z_wierszem_historii_bez_pamieci_nie_wraca_po_cofnieciu_przez_tate(tmp_path: Path) -> None:
    """Wiersz Historii idzie przed pamięcią zmian z Wydań, więc nieudany zapis pamięci nie puszcza zmiany drugi raz."""

    tool = ToolDirectory(tmp_path)
    with read_only_memory(tool):
        applied, undone = applied_and_undone(tool)
    again = started(tool, (LIGHT_THEME,))
    theme = again.get("/api/settings").json()["theme"]
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (applied["source"], undone, theme) == ("release", "dark", "dark")
    assert [row["source"] for row in rows] == ["tata", "release"]
    assert "ustawienia-wydanie zmiana=2026-11-motyw-jasny wynik=bez-pamieci" in tool.log_path.read_text(encoding="utf-8")


@NO_ACCESS_ON_WINDOWS
def test_historia_bez_dostepu_przy_starcie_wstrzymuje_zmiane_z_wydania_ktora_tata_cofnal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historia, której system przy starcie nie daje czytać, nie jest pustą Historią: zmiana z Wydania, którą tata cofnął,
    a której pamięć nie ma, nie wchodzi drugi raz."""

    tool = ToolDirectory(tmp_path)
    with read_only_memory(tool):
        applied_and_undone(tool)
    with unreadable_history(monkeypatch):
        again = started(tool, (LIGHT_THEME,))
    theme = again.get("/api/settings").json()["theme"]
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (theme, [row["source"] for row in rows]) == ("dark", ["tata", "release"])
    assert "ustawienia-wydanie zmiana=2026-11-motyw-jasny wynik=bez-historii" in tool.log_path.read_text(encoding="utf-8")


def test_zmiana_z_wydania_wstrzymana_przez_historie_bez_dostepu_wchodzi_przy_nastepnym_starcie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = with_periods_directory(tmp_path)
    app.client.stop()

    with unreadable_history(monkeypatch):
        held = started(app.tool, (LIGHT_THEME,))
        held_theme = held.get("/api/settings").json()["theme"]
        held.stop()
    again = started(app.tool, (LIGHT_THEME,))
    theme = again.get("/api/settings").json()["theme"]
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (held_theme, theme) == ("dark", "light")
    assert [row["source"] for row in rows] == ["release", "tata"]


@NO_ACCESS_ON_WINDOWS
def test_historia_ustawien_bez_dostepu_to_odmowa_okna_i_cofniecia_a_nie_pusta_historia(tmp_path: Path) -> None:
    app, _ = with_periods_directory(tmp_path)
    [row] = app.client.get("/api/settings/history").json()["rows"]
    saved = app.settings_path.read_bytes()

    with without_access(app.tool.config / HISTORY_FILE):
        history = app.client.get("/api/settings/history")
        undo = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert (history.status_code, history.json()) == (
        500,
        {"message": "Nie udało się odczytać Historii Ustawień. Odśwież okno Ustawień za chwilę."},
    )
    assert (undo.status_code, app.settings_path.read_bytes()) == (500, saved)
    assert "ustawienia-bez-zapisu przyczyna=historia" in app.log_path.read_text(encoding="utf-8")


@NO_ACCESS_ON_WINDOWS
def test_odrzucona_zmiana_z_wydania_z_wierszem_historii_bez_pamieci_nie_wraca(tmp_path: Path) -> None:
    asked: list[str] = []

    def refused_once(_inputs: ReleaseInputs[FolderSettings]) -> Refuse:
        asked.append("zapytana")
        return Refuse(WORKERS_MISSING)

    tool = ToolDirectory(tmp_path)
    change = ReleaseChange("2026-11-odmowa", FOLDERS, refused_once)

    with read_only_memory(tool):
        started(tool, (change,)).stop()
    again = started(tool, (change,))
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (asked, [(row["source"], row["refused"]) for row in rows]) == (["zapytana"], [("release", True)])


def test_odrzucona_zmiana_z_wydania_bez_wiersza_historii_wraca_przy_nastepnym_starcie(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    history = tool.config / HISTORY_FILE
    history.mkdir(parents=True)
    change = ReleaseChange("2026-11-zla-zmiana", FOLDERS, refused)

    started(tool, (change,)).stop()
    history.rmdir()
    again = started(tool, (change,))
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert [(row["source"], row["reason"]) for row in rows] == [("release", WORKERS_MISSING)]
    log = tool.log_path.read_text(encoding="utf-8")
    assert log.index("zmiana=2026-11-zla-zmiana wynik=bez-zapisu") < log.index("zmiana=2026-11-zla-zmiana wynik=odrzucono")


def test_wyjatek_w_zmianie_ustawien_z_wydania_nie_zatrzymuje_startu_centrum_a_zmiana_wraca(tmp_path: Path) -> None:
    asked: list[str] = []

    def failing(_inputs: ReleaseInputs[FolderSettings]) -> Nothing:
        asked.append("zapytana")
        raise KeyError("pole")

    tool = ToolDirectory(tmp_path)
    change = ReleaseChange("2026-11-z-bledem", FOLDERS, failing)

    started(tool, (change,)).stop()
    again = started(tool, (change,))
    health = again.get("/api/health")
    again.stop()

    assert (health.status_code, asked) == (200, ["zapytana", "zapytana"])
    log = tool.log_path.read_text(encoding="utf-8")
    assert log.count('nieoczekiwany-wyjatek typ=KeyError miejsce="zmiana Ustawień z Wydania 2026-11-z-bledem"') == 2


def test_chwila_wiersza_historii_idzie_do_przegladarki_w_utc_takze_na_komputerze_w_strefie_taty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Schemat przeglądarki przyjmuje tylko chwilę w UTC („Z”); na komputerze w UTC każda chwila tak wygląda.
    if sys.platform == "win32":
        pytest.skip("time.tzset jest tylko w systemach POSIX")
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    try:
        app = centrum(tmp_path)
        app.client.put("/api/settings/theme", json={"theme": "light"})
        [row] = history_rows(app)
    finally:
        monkeypatch.undo()
        time.tzset()

    assert row["at"].endswith("Z")


def test_akcja_zmieniajaca_stan_wymaga_origin_centrum(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    allowed = _passed_through(app, {"Origin": "http://zly.example"})
    other_port = app.client.put(
        "/api/settings/theme", json={"theme": "light"}, headers={"Origin": "http://127.0.0.1:3000"}
    )

    assert (allowed, other_port.status_code) == ([], 403)
    assert app.client.get("/api/settings").json()["theme"] == "dark"


def test_akcja_bez_origin_jest_odrzucona(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    no_origin = TestClient(app.client.app, base_url=CENTRUM)

    response = no_origin.post("/api/settings/register/choose")

    assert response.status_code == 403
    assert app.platform.dialog_titles == []


def with_periods_directory(tmp_path: Path, *, today: date = date(2026, 10, 19)) -> tuple[Centrum, Path]:
    periods = tmp_path / "INEA"
    periods.mkdir(exist_ok=True)
    app = centrum(tmp_path, today=today)
    app.platform.chosen_folders.append(periods)
    app.client.post("/api/settings/periods-directory/choose")
    return app, periods


def write_period_files(periods: Path, token: str) -> Path:
    folder = PeriodFolder(periods, parse_period_token(token))
    folder.directory.mkdir()
    folder.internal_settlement.touch()
    folder.collective_file.touch()
    return folder.directory


def write_worker_settlements(period_folder: Path, token: str, workers: Sequence[str]) -> Path:
    folder = PeriodFolder(period_folder.parent, parse_period_token(token))
    folder.worker_settlements.mkdir()
    for worker in workers:
        folder.worker_settlement(worker).touch()
    return folder.worker_settlements


def period_files(row: dict[str, object]) -> dict[str, dict[str, Any]]:
    files = row["files"]
    assert isinstance(files, list)
    return {file["target"]: file for file in files}


def worker_settlement_count(row: dict[str, object]) -> int | None:
    """Liczba Rozliczeń pracownika na przycisku Folderu rozliczeń pracowników okresu ``row``."""

    count: int | None = period_files(row)["worker_settlements_folder"]["count"]
    return count


def board_rows(app: Centrum) -> list[dict[str, object]]:
    response = app.client.get("/api/periods")
    assert response.status_code == 200
    board = response.json()
    assert board["state"] == "ready"
    rows = board["periods"]
    assert isinstance(rows, list)
    return rows


def test_tablica_okresow_bez_folderu_okresow_prosi_o_jego_wskazanie(tmp_path: Path) -> None:
    response = centrum(tmp_path).client.get("/api/periods")

    assert response.json() == {"state": "not_set"}


def test_tablica_okresow_z_nieistniejacym_folderem_okresow_mowi_o_tym_wprost(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    periods.rmdir()

    response = app.client.get("/api/periods")

    assert response.json() == {"state": "missing", "name": "INEA"}


def test_plik_folderu_okresu_spoza_listowania_bez_dostepu_to_folder_niedostepny_a_nie_brak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = PeriodFolder(tmp_path, parse_period_token("22_28_09_2026"))
    folder.directory.mkdir()
    real_stat = Path.stat

    def stat(path: Path, **kwargs: Any) -> os.stat_result:
        if path == folder.collective_file:
            raise PermissionError(errno.EACCES, "Odmowa dostępu")
        return real_stat(path, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)

    with pytest.raises(PeriodFolderInaccessible) as raised:
        folder.observe()

    assert raised.value.folder == folder.directory


def test_tablica_okresow_pokazuje_status_okresu_kazdego_folderu_okresu_od_najnowszego(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    ready = write_period_files(periods, "22_28_09_2026")
    worker_folder = write_worker_settlements(ready, "22_28_09_2026", ["Anna Testowa", "Jan Próbny"])
    (worker_folder / "~$Rozliczenie 22_28_09_2026 - Anna Testowa.xlsx").touch()
    (worker_folder / "Rozliczenie 22_28_09_2026 -.xlsx").touch()
    (worker_folder / "Rozliczenie 22_28_09_2026 - .xlsx").touch()
    write_period_files(periods, "29_05_10_2026")
    (periods / "15_21_09_2026").mkdir()
    (periods / "Archiwum").mkdir()
    (periods / "00_01_01_0001").mkdir()
    (periods / ".13_19_10_2026.staging-abc").mkdir()
    (periods / "notatki.txt").touch()

    rows = board_rows(app)

    assert [(row["token"], row["status"], worker_settlement_count(row)) for row in rows] == [
        ("06_12_10_2026", "no_period_files", None),
        ("29_05_10_2026", "collective_file_prepared", None),
        ("22_28_09_2026", "worker_settlements_ready", 2),
        ("15_21_09_2026", "no_period_files", None),
    ]
    assert [row["status_label"] for row in rows[1:]] == [
        "Plik zbiorczy przygotowany",
        "Rozliczenia pracowników gotowe",
        "Brak plików okresu",
    ]
    assert [row["next_step"]["action"] for row in rows] == [  # type: ignore[index]
        "prepare_collective_file",
        "fill_collective_file",
        "none",
        "prepare_collective_file",
    ]
    assert [row["next_step"].get("preview_hint") for row in rows] == [  # type: ignore[attr-defined]
        "Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
        None,
        None,
        "Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
    ]
    assert [stages(row) for row in rows] == [
        ["now", "later", "later", "later"],
        ["done", "now", "later", "later"],
        ["done", "done", "not_done", "done"],
        ["now", "later", "later", "later"],
    ]


def with_dad_layout(tmp_path: Path, chosen_month: str | None = None) -> tuple[Centrum, Path]:
    """Centrum w układzie folderów taty ``Załączniki``: Rozliczenia {rok}\\{miesiąc}\\INEA.

    Folder okresów to ``Załączniki`` albo, z ``chosen_month``, folder ``INEA`` tego miesiąca.
    """

    root = tmp_path / "Załączniki"
    for month in ("12_Grudzień_2025",):
        (root / "Rozliczenia 2025" / month / "INEA").mkdir(parents=True)
    for month in ("09_Wrzesień_2026", "10_Październik_2026", "11_Listopad_2026"):
        (root / "Rozliczenia 2026" / month / "INEA").mkdir(parents=True)
    (root / "Rozliczenia 2026" / "Nowe rozliczenia wzór od 01_2026" / "Podpisane").mkdir(parents=True)
    app = centrum(tmp_path)
    app.platform.chosen_folders.append(root if chosen_month is None else inea(root, chosen_month))
    app.client.post("/api/settings/periods-directory/choose")
    return app, root


def inea(root: Path, month: str, year: int = 2026) -> Path:
    return root / f"Rozliczenia {year}" / month / "INEA"


def test_w_ukladzie_folderow_taty_tablica_okresow_widzi_tygodnie_ze_wszystkich_miesiecy(tmp_path: Path) -> None:
    app, root = with_dad_layout(tmp_path)
    write_period_files(inea(root, "10_Październik_2026"), "06_12_10_2026")
    (inea(root, "10_Październik_2026") / "13_19_10_2026").mkdir()
    write_period_files(inea(root, "10_Październik_2026"), "29_05_10_2026")
    (inea(root, "10_Październik_2026") / "Podpisane").mkdir()
    (inea(root, "11_Listopad_2026") / "27_02_11_2026").mkdir()
    ready = write_period_files(inea(root, "09_Wrzesień_2026"), "22_28_09_2026")
    write_worker_settlements(ready, "22_28_09_2026", ["Anna Testowa"])
    (inea(root, "09_Wrzesień_2026") / "28_30_09_2026 tylko dawid").mkdir()
    (inea(root, "12_Grudzień_2025", year=2025) / "16_22_12_2025").mkdir()
    (root / "Rozliczenia 26" / "10_Październik_2026" / "INEA" / "20_26_10_2026").mkdir(parents=True)

    rows = board_rows(app)

    assert [(row["token"], row["status"], row["last_complete"]) for row in rows] == [
        ("27_02_11_2026", "no_period_files", False),
        ("13_19_10_2026", "no_period_files", False),
        ("06_12_10_2026", "collective_file_prepared", True),
        ("29_05_10_2026", "collective_file_prepared", False),
        ("22_28_09_2026", "worker_settlements_ready", False),
        ("16_22_12_2025", "no_period_files", False),
    ]
    assert app.client.get("/api/periods").json()["last_prepared_period"] == "06_12_10_2026"


def test_w_ukladzie_folderow_taty_tablica_okresow_z_folderu_inea_miesiaca_widzi_tygodnie_wszystkich_miesiecy(
    tmp_path: Path,
) -> None:
    app, root = with_dad_layout(tmp_path, "10_Październik_2026")
    write_period_files(inea(root, "09_Wrzesień_2026"), "22_28_09_2026")
    write_period_files(inea(root, "10_Październik_2026"), "06_12_10_2026")
    write_period_files(inea(root, "11_Listopad_2026"), "27_02_11_2026")

    rows = board_rows(app)

    assert [row["token"] for row in rows if row["status"] == "collective_file_prepared"] == [
        "27_02_11_2026",
        "06_12_10_2026",
        "22_28_09_2026",
    ]


def test_w_ukladzie_folderow_taty_pliki_okresu_otwieraja_sie_z_folderu_miesiaca(tmp_path: Path) -> None:
    app, root = with_dad_layout(tmp_path)
    period_folder = write_period_files(inea(root, "10_Październik_2026"), "06_12_10_2026")

    response = app.client.post("/api/periods/06_12_10_2026/open", json={"target": "collective_file"})

    assert response.json() == {"name": collective_file_name_with("06_12_10_2026")}
    assert app.platform.opened == [period_folder / collective_file_name_with("06_12_10_2026")]


@pytest.mark.parametrize("chosen_month", [None, "10_Październik_2026"], ids=["zalaczniki", "inea-pazdziernika"])
def test_w_ukladzie_folderow_taty_tydzien_w_dwoch_miesiacach_nie_jest_otwierany(
    tmp_path: Path, chosen_month: str | None
) -> None:
    app, root = with_dad_layout(tmp_path, chosen_month)
    write_period_files(inea(root, "09_Wrzesień_2026"), "29_05_10_2026")
    write_period_files(inea(root, "10_Październik_2026"), "29_05_10_2026")

    rows = board_rows(app)
    response = app.client.post("/api/periods/29_05_10_2026/open", json={"target": "collective_file"})

    assert [row["token"] for row in rows].count("29_05_10_2026") == 1
    assert response.status_code == 409
    assert response.json() == {
        "message": "Folder 29_05_10_2026 jest w więcej niż jednym folderze miesiąca "
        "(Rozliczenia 2026\\09_Wrzesień_2026\\INEA, Rozliczenia 2026\\10_Październik_2026\\INEA). "
        "Zostaw go tylko w jednym."
    }
    assert app.platform.opened == []


def stages(row: dict[str, object]) -> list[str]:
    """Stany kroków Drogi okresu wiersza; ich nazwy sprawdza test pełnego wiersza."""

    path = row["path"]
    assert isinstance(path, list)
    return [step["stage"] for step in path]


def write_pricing(app: Centrum, token: str, *started: tuple[int, CompletedResult | RecordedStop]) -> None:
    """Uruchomienia Wyceny w efenix okresu ``token`` w Historii, w kolejności zapisu: (godzina startu 13.10, wynik)."""

    store = MetricsStore(app.metrics.efenix, efenix_process.PROCESS.counter_names)
    for hour, ending in started:
        store.append(
            metric_record(
                mode="RUN",
                period=token,
                started_at=f"2026-10-13T{hour:02d}:00:00+02:00",
                total_duration_ms=1000,
                phase_durations_ms={},
                ending=ending,
                counters=dict.fromkeys(efenix_process.PROCESS.counter_names, 0),
            )
        )


PRICE = {
    "action": "price_in_efenix",
    "process": "efenix",
    "label": "Wyceń w efenix",
    "hint": "Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.",
    "preview_hint": None,
}
PRICE_AGAIN = PRICE | {
    "hint": "Ostatnia Wycena w efenix nie skończyła się wynikiem OK. Sprawdź jej wynik i uruchom ją ponownie."
}
SETTLE = {
    "action": "create_worker_settlements",
    "process": "settlement",
    "label": "Utwórz rozliczenia pracowników",
    "hint": "Wycena w efenix skończyła się wynikiem OK. Teraz rozliczenia pracowników z Pliku zbiorczego.",
    "preview_hint": "Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
}
SETTLE_BEFORE_PRICING = SETTLE | {
    "hint": "Możesz je utworzyć także bez Wyceny w efenix, na przykład gdy efenix nie działa."
}
FILL = {
    "action": "fill_collective_file",
    "label": "Uzupełnij plik zbiorczy",
    "hint": "Uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.",
    "then": PRICE,
}
CLOSED = {"action": "none", "label": "Okres zamknięty", "hint": "Rozliczenia pracowników są w Folderze okresu."}
STOPPED: RecordedStop = {"kind": "for_tata", "code": "EFENIX_NIE_ODPOWIADA"}


@pytest.mark.parametrize(
    ("settled", "pricing", "path", "next_step", "secondary_step"),
    [
        (False, [], ["done", "now", "later", "later"], FILL, SETTLE_BEFORE_PRICING),
        (False, [(11, "OK"), (10, "WYMAGA_SPRAWDZENIA")], ["done", "done", "done", "now"], SETTLE, None),
        (False, [(10, "OK"), (11, "WYMAGA_SPRAWDZENIA")], ["done", "done", "now", "later"], PRICE_AGAIN, SETTLE_BEFORE_PRICING),
        (False, [(10, "OK"), (11, STOPPED)], ["done", "done", "now", "later"], PRICE_AGAIN, SETTLE_BEFORE_PRICING),
        (True, [], ["done", "done", "not_done", "done"], CLOSED, None),
        (True, [(10, "WYMAGA_SPRAWDZENIA")], ["done", "done", "not_done", "done"], CLOSED, None),
        (True, [(10, "OK")], ["done", "done", "done", "done"], CLOSED, None),
    ],
    ids=[
        "bez-wyceny",
        "wycena-ok",
        "wycena-wymaga-sprawdzenia",
        "wycena-zatrzymana",
        "rozliczenia-gotowe-bez-wyceny",
        "rozliczenia-gotowe-po-wycenie-do-sprawdzenia",
        "rozliczenia-gotowe-po-wycenie-ok",
    ],
)
def test_droga_okresu_i_nastepny_krok_ida_przez_wycene_w_efenix_zaliczona_ostatnim_uruchomieniem_z_wynikiem_ok(
    tmp_path: Path,
    settled: bool,
    pricing: list[tuple[int, CompletedResult | RecordedStop]],
    path: list[str],
    next_step: dict[str, object],
    secondary_step: dict[str, object] | None,
) -> None:
    """Droga okresu: Plik zbiorczy → Uzupełnienie w Excelu → Wycena w efenix → Rozliczenia pracowników. Wycena jest
    zaliczona, gdy ostatnie (najpóźniej wystartowane) jej Uruchomienie okresu ma wynik OK; Wymaga sprawdzenia i
    Zatrzymanie zostawiają ją w toku. Następny krok to bieżący krok Drogi: przed Wyceną Uzupełnij plik zbiorczy, po
    nim Wyceń w efenix. Przebieg rozliczeń nie czeka na Wycenę, tylko stoi po niej, a Status okresu się nie zmienia.
    Wycena innego okresu nic tu nie zalicza."""

    app, periods = with_periods_directory(tmp_path)
    folder = write_period_files(periods, "29_05_10_2026")
    if settled:
        write_worker_settlements(folder, "29_05_10_2026", ["Anna Testowa"])
    write_pricing(app, "29_05_10_2026", *pricing)
    write_pricing(app, "22_28_09_2026", (12, "OK"))

    row = board_rows(app)[1]

    assert row["token"] == "29_05_10_2026"
    assert (row["status"], row["fillable"]) == (
        ("worker_settlements_ready", False) if settled else ("collective_file_prepared", True)
    )
    assert (stages(row), row["next_step"], row["secondary_step"]) == (path, next_step, secondary_step)


def test_tablica_okresow_wskazuje_ostatni_przygotowany_okres_z_plikiem_zbiorczym(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    before = app.client.get("/api/periods").json()["last_prepared_period"]
    write_worker_settlements(write_period_files(periods, "22_28_09_2026"), "22_28_09_2026", ["Anna Testowa"])
    write_period_files(periods, "15_21_09_2026")
    (periods / "29_05_10_2026").mkdir()

    after = app.client.get("/api/periods").json()["last_prepared_period"]

    assert (before, after) == (None, "22_28_09_2026")


def test_ostatni_pelny_okres_jest_wyrozniony_takze_bez_folderu_okresu(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    write_period_files(periods, "29_05_10_2026")

    rows = board_rows(app)

    assert rows[0] == {
        "token": "06_12_10_2026",
        "tuesday": "2026-10-06",
        "monday": "2026-10-12",
        "status": "no_period_files",
        "status_label": "Brak plików okresu",
        "files": [
            {"target": "internal_settlement", "label": "Rozliczenie wewnętrzne", "exists": False, "count": None},
            {"target": "collective_file", "label": "Plik zbiorczy", "exists": False, "count": None},
            {"target": "period_folder", "label": "Folder okresu", "exists": False, "count": None},
            {"target": "worker_settlements_folder", "label": "Folder rozliczeń pracowników", "exists": False, "count": None},
        ],
        "last_complete": True,
        "board_place": "recent",
        "fillable": False,
        "path": [
            {"label": "Plik zbiorczy", "stage": "now"},
            {"label": "Uzupełnienie w Excelu", "stage": "later"},
            {"label": "Wycena w efenix", "stage": "later"},
            {"label": "Rozliczenia pracowników", "stage": "later"},
        ],
        "next_step": {
            "action": "prepare_collective_file",
            "process": "preparation",
            "label": "Przygotuj plik zbiorczy",
            "hint": "Z Rejestru zleceń powstaną Rozliczenie wewnętrzne i Plik zbiorczy.",
            "preview_hint": "Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
        },
        "secondary_step": None,
    }
    assert [row["last_complete"] for row in rows] == [True, False]


def _around_boundary(before: str, crossing: str, after: str, crossing_monday: date) -> list[tuple[date, str]]:
    week = timedelta(days=7)
    return [
        (crossing_monday, before),
        *[(crossing_monday + timedelta(days=offset), crossing) for offset in range(1, 8)],
        (crossing_monday + week + timedelta(days=1), after),
    ]


@pytest.mark.parametrize(
    ("today", "token"),
    [
        *[(date(2026, 9, 15) + timedelta(days=offset), "08_14_09_2026") for offset in range(7)],
        # Na przełomie miesięcy i lat token ma miesiąc i rok poniedziałku.
        *_around_boundary("20_26_10_2026", "27_02_11_2026", "03_09_11_2026", date(2026, 11, 2)),
        *_around_boundary("22_28_12_2026", "29_04_01_2027", "05_11_01_2027", date(2027, 1, 4)),
    ],
)
def test_ostatni_pelny_okres_konczy_sie_przed_dzisiejszym_dniem(tmp_path: Path, today: date, token: str) -> None:
    app, _periods = with_periods_directory(tmp_path, today=today)

    assert [row["token"] for row in board_rows(app) if row["last_complete"]] == [token]


def test_tablica_okresow_pokazuje_od_razu_biezacy_okres_i_4_poprzednie_starsze_po_rozwinieciu_a_przyszle_nigdy(
    tmp_path: Path,
) -> None:
    app, periods = with_periods_directory(tmp_path, today=date(2026, 10, 19))
    for token in (
        "27_02_11_2026",
        "20_26_10_2026",
        "13_19_10_2026",
        "29_05_10_2026",
        "22_28_09_2026",
        "15_21_09_2026",
        "08_14_09_2026",
        "01_07_09_2026",
    ):
        (periods / token).mkdir()

    rows = board_rows(app)

    assert [(row["token"], row["board_place"]) for row in rows] == [
        ("27_02_11_2026", "not_started"),
        ("20_26_10_2026", "not_started"),
        ("13_19_10_2026", "recent"),
        ("06_12_10_2026", "recent"),
        ("29_05_10_2026", "recent"),
        ("22_28_09_2026", "recent"),
        ("15_21_09_2026", "recent"),
        ("08_14_09_2026", "older"),
        ("01_07_09_2026", "older"),
    ]


@pytest.mark.parametrize(
    ("today", "place"),
    [(date(2026, 10, 19), "not_started"), (date(2026, 10, 20), "recent"), (date(2026, 10, 26), "recent")],
)
def test_okres_zaczyna_sie_na_tablicy_okresow_w_swoj_wtorek(tmp_path: Path, today: date, place: str) -> None:
    app, periods = with_periods_directory(tmp_path, today=today)
    (periods / "20_26_10_2026").mkdir()

    rows = board_rows(app)

    assert [row["board_place"] for row in rows if row["token"] == "20_26_10_2026"] == [place]


def test_przy_pieciu_zaczetych_okresach_tablica_okresow_nie_ma_nic_po_rozwinieciu(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path, today=date(2026, 10, 19))
    for token in ("20_26_10_2026", "13_19_10_2026", "29_05_10_2026", "22_28_09_2026", "15_21_09_2026"):
        (periods / token).mkdir()

    rows = board_rows(app)

    assert [row["board_place"] for row in rows] == ["not_started", *["recent"] * 5]


def test_istniejacy_folder_ostatniego_pelnego_okresu_nie_jest_powtorzony(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path, today=date(2026, 10, 6))
    write_period_files(periods, "29_05_10_2026")

    rows = board_rows(app)

    assert [(row["token"], row["last_complete"], row["status"]) for row in rows] == [
        ("29_05_10_2026", True, "collective_file_prepared")
    ]


def test_status_okresu_odzwierciedla_zmiany_na_dysku_przy_kazdym_odczycie(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    before = board_rows(app)[0]["status"]

    period_folder = write_period_files(periods, "06_12_10_2026")
    prepared = board_rows(app)[0]
    write_worker_settlements(period_folder, "06_12_10_2026", ["Anna Testowa"])
    ready = board_rows(app)[0]

    assert (before, prepared["status"], ready["status"]) == (
        "no_period_files",
        "collective_file_prepared",
        "worker_settlements_ready",
    )
    assert {target: (file["exists"], file["count"]) for target, file in period_files(prepared).items()} == {
        "internal_settlement": (True, None),
        "collective_file": (True, None),
        "period_folder": (True, None),
        "worker_settlements_folder": (False, None),
    }
    assert worker_settlement_count(ready) == 1


def test_odczyt_tablicy_okresow_nie_sprawdza_osobno_kazdego_rozliczenia_pracownika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Folder okresów taty leży w OneDrive, gdzie każde sprawdzenie pliku z osobna jest drogie.
    app, periods = with_periods_directory(tmp_path)
    worker_folder = write_worker_settlements(
        write_period_files(periods, "29_05_10_2026"), "29_05_10_2026", ["Anna Testowa"]
    )
    checked: list[object] = []
    stat = os.stat

    # Tylko ścieżki pod folderem okresów: wątek w tle poprzedniego testu w tym workerze (np. wpis dziennika
    # Centrum) też woła os.stat.
    def counted_stat(path: str | os.PathLike[str], *args: Any, **kwargs: Any) -> os.stat_result:
        if isinstance(path, str | os.PathLike) and Path(path).is_relative_to(periods):
            checked.append(path)
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", counted_stat)

    def checks_and_count() -> tuple[int, object]:
        checked.clear()
        count = worker_settlement_count(next(row for row in board_rows(app) if row["token"] == "29_05_10_2026"))
        return len(checked), count

    checks_and_count()  # pierwsze żądanie dokańcza leniwe importy
    one_worker = checks_and_count()
    for number in range(20):
        (worker_folder / f"Rozliczenie 29_05_10_2026 - Wykonawca {number}.xlsx").touch()
    many_workers = checks_and_count()

    assert (one_worker[1], many_workers[1]) == (1, 21)
    assert many_workers[0] == one_worker[0]


def test_pliki_i_foldery_okresu_otwieraja_sie_jednym_kliknieciem(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    period_folder = write_period_files(periods, "22_28_09_2026")
    worker_folder = write_worker_settlements(period_folder, "22_28_09_2026", ["Anna Testowa"])
    targets = ["internal_settlement", "collective_file", "period_folder", "worker_settlements_folder"]

    responses = [
        app.client.post("/api/periods/22_28_09_2026/open", json={"target": target}) for target in targets
    ]

    assert [response.json() for response in responses] == [
        {"name": "Rozliczenie wew. 22_28_09_2026.xlsx"},
        {"name": "Rozliczenie 22_28_09_2026 - zbiorcze.xlsx"},
        {"name": "22_28_09_2026"},
        {"name": "Rozliczenie pracowników 22_28_09_2026"},
    ]
    assert app.platform.opened == [
        period_folder / "Rozliczenie wew. 22_28_09_2026.xlsx",
        period_folder / "Rozliczenie 22_28_09_2026 - zbiorcze.xlsx",
        period_folder,
        worker_folder,
    ]


@pytest.mark.parametrize(
    ("target", "name"),
    [
        ("internal_settlement", "Rozliczenie wewnętrzne okresu"),
        ("collective_file", "Plik zbiorczy okresu"),
        ("period_folder", "Folder okresu"),
        ("worker_settlements_folder", "Folder rozliczeń pracowników okresu"),
    ],
)
def test_nieistniejacy_plik_okresu_nie_jest_otwierany_a_odmowa_nazywa_go_jak_glossary(
    tmp_path: Path, target: str, name: str
) -> None:
    app, periods = with_periods_directory(tmp_path)
    if target != "period_folder":
        (periods / "22_28_09_2026").mkdir()

    response = app.client.post("/api/periods/22_28_09_2026/open", json={"target": target})

    assert (response.status_code, response.json()) == (404, {"message": f"{name} 22_28_09_2026 jeszcze nie istnieje."})
    assert app.platform.opened == []


def test_otwierane_sa_tylko_sciezki_wyliczone_z_folderu_okresow(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    write_period_files(periods, "22_28_09_2026")
    (periods / "Archiwum").mkdir()
    (tmp_path / "poza.xlsx").touch()

    attempts = [
        app.client.post("/api/periods/Archiwum/open", json={"target": "period_folder"}),
        app.client.post("/api/periods/../open", json={"target": "period_folder"}),
        app.client.post("/api/periods/%2E%2E/open", json={"target": "period_folder"}),
        app.client.post("/api/periods/23_29_09_2026/open", json={"target": "period_folder"}),
        app.client.post(
            "/api/periods/22_28_09_2026/open",
            json={"target": "collective_file", "path": str(tmp_path / "poza.xlsx")},
        ),
        app.client.post("/api/periods/22_28_09_2026/open", json={"target": "../../poza.xlsx"}),
    ]

    assert all(400 <= attempt.status_code < 500 for attempt in attempts)
    assert app.platform.opened == []


def unreadable_folder(name: str) -> dict[str, str]:
    return {
        "message": f"Nie udało się odczytać folderu {name}. Sprawdź, czy folder otwiera się w Eksploratorze plików i "
        "czy OneDrive działa, potem odśwież kartę."
    }


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_plik_okresu_w_folderze_okresu_bez_dostepu_jest_nieczytelny_a_nie_brakujacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    app, periods = with_periods_directory(tmp_path)
    period_folder = write_period_files(periods, "22_28_09_2026")
    write_worker_settlements(period_folder, "22_28_09_2026", ["Anna Testowa"])
    path_checks(monkeypatch)

    with without_access(period_folder):
        responses = [
            app.client.post("/api/periods/22_28_09_2026/open", json={"target": "collective_file"}),
            app.client.post("/api/periods/22_28_09_2026/open", json={"target": "worker_settlements_folder"}),
            app.client.post("/api/periods/22_28_09_2026/worker-settlements/open", json={"worker": "Anna Testowa"}),
        ]

    assert [(response.status_code, response.json()) for response in responses] == [
        (500, unreadable_folder("22_28_09_2026"))
    ] * 3
    assert app.platform.opened == []


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_folder_okresow_w_folderze_bez_dostepu_jest_nieczytelny_a_nie_niewskazany(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    onedrive = tmp_path / "OneDrive"
    periods = onedrive / "INEA"
    periods.mkdir(parents=True)
    app = centrum(tmp_path)
    app.platform.chosen_folders.append(periods)
    app.client.post("/api/settings/periods-directory/choose")
    write_period_files(periods, "22_28_09_2026")
    path_checks(monkeypatch)

    with without_access(onedrive):
        response = app.client.post("/api/periods/22_28_09_2026/open", json={"target": "collective_file"})

    assert (response.status_code, response.json()) == (500, unreadable_folder("INEA"))
    assert app.platform.opened == []


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_tablica_okresow_z_folderem_okresow_w_folderze_bez_dostepu_jest_nieczytelna_a_nie_brakujaca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    onedrive = tmp_path / "OneDrive"
    periods = onedrive / "INEA"
    periods.mkdir(parents=True)
    app = centrum(tmp_path)
    app.platform.chosen_folders.append(periods)
    app.client.post("/api/settings/periods-directory/choose")
    path_checks(monkeypatch)

    with without_access(onedrive):
        response = app.client.get("/api/periods")

    assert (response.status_code, response.json()) == (500, unreadable_folder("INEA"))


@NO_ACCESS_ON_WINDOWS
def test_tablica_okresow_bez_folderu_okresow_mowi_o_braku_choc_folder_innego_miesiaca_jest_bez_dostepu(
    tmp_path: Path,
) -> None:
    year = tmp_path / "Załączniki" / "Rozliczenia 2026"
    (year / "10_Październik_2026" / "INEA").mkdir(parents=True)
    periods = year / "11_Listopad_2026" / "INEA"
    periods.mkdir(parents=True)
    app = centrum(tmp_path)
    app.platform.chosen_folders.append(periods)
    app.client.post("/api/settings/periods-directory/choose")
    periods.rmdir()

    with without_access(year / "10_Październik_2026"):
        board = app.client.get("/api/periods")
        settings = app.client.get("/api/settings")

    assert (board.status_code, board.json()) == (200, {"state": "missing", "name": "INEA"})
    assert settings.json()["periods_directory"]["state"] == "missing"


# Obie trasy wołają requested_folder osobno, więc każda ma swój wiersz (#1452 r1).
@pytest.mark.parametrize(
    ("route", "body"),
    [("open", {"target": "period_folder"}), ("worker-settlements/open", {"worker": "Anna Testowa"})],
    ids=["folder-okresu", "rozliczenie-pracownika"],
)
def test_otwieranie_bez_wskazanego_folderu_okresow_prosi_o_jego_wskazanie(
    tmp_path: Path, route: str, body: dict[str, str]
) -> None:
    app = centrum(tmp_path)

    response = app.client.post(f"/api/periods/22_28_09_2026/{route}", json=body)

    assert response.status_code == 409
    assert response.json() == {"message": "Najpierw wskaż folder okresów."}
    assert app.platform.opened == []


def with_register(tmp_path: Path) -> tuple[Centrum, Path]:
    """Centrum, w którym tata wybrał w Ustawieniach Rejestr zleceń z folderu „Rejestr”."""

    register = tmp_path / "Rejestr" / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    register.parent.mkdir()
    register.touch()
    app = centrum(tmp_path)
    app.platform.chosen_files.append(register)
    assert app.client.post("/api/settings/register/choose").status_code == 200
    return app, register


def test_rejestr_zlecen_z_ustawien_otwiera_sie_jednym_kliknieciem(tmp_path: Path) -> None:
    app, register = with_register(tmp_path)

    response = app.client.post("/api/settings/register/open")

    assert response.json() == {"name": "ZLECENIA INTERMAX OD 08_11_2021.xlsx"}
    assert app.platform.opened == [register]


def test_otwieranie_rejestru_bez_wyboru_w_ustawieniach_prosi_o_wybor(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/settings/register/open")

    assert response.status_code == 409
    assert response.json() == {"message": "Najpierw wybierz Rejestr zleceń w Ustawieniach."}
    assert app.platform.opened == []


@pytest.mark.parametrize("gone", ["usuniety", "folder-zamiast-pliku", "bez-folderu"])
def test_nieistniejacy_rejestr_nie_jest_otwierany(tmp_path: Path, gone: str) -> None:
    app, register = with_register(tmp_path)
    register.unlink()
    if gone == "folder-zamiast-pliku":
        register.mkdir()
    if gone == "bez-folderu":
        register.parent.rmdir()
        register.parent.write_bytes(b"")

    response = app.client.post("/api/settings/register/open")

    assert response.status_code == 404
    assert response.json() == {
        "message": "Nie ma Rejestru zleceń ZLECENIA INTERMAX OD 08_11_2021.xlsx. Wybierz właściwy plik w Ustawieniach."
    }
    assert app.platform.opened == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows sprawdza plik bez prawa odczytu jego folderu")
def test_rejestr_w_folderze_bez_dostepu_jest_niedostepny_a_nie_uszkodzony(tmp_path: Path) -> None:
    app, register = with_register(tmp_path)
    register.parent.chmod(0)
    try:
        response = app.client.post("/api/settings/register/open")
    finally:
        register.parent.chmod(0o755)

    assert response.status_code == 409
    assert response.json()["message"].startswith(
        "Rejestr zleceń ZLECENIA INTERMAX OD 08_11_2021.xlsx jest teraz niedostępny."
    )
    assert app.platform.opened == []


def test_rozliczenie_pracownika_otwiera_sie_po_nazwie_wykonawcy(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    worker_folder = write_worker_settlements(
        write_period_files(periods, "22_28_09_2026"), "22_28_09_2026", ["Anna Testowa", "Bartek Fikcyjny"]
    )

    response = app.client.post(
        "/api/periods/22_28_09_2026/worker-settlements/open", json={"worker": "Bartek Fikcyjny"}
    )

    assert (response.status_code, response.json()) == (200, {"name": "Rozliczenie 22_28_09_2026 - Bartek Fikcyjny.xlsx"})
    assert app.platform.opened == [worker_folder / "Rozliczenie 22_28_09_2026 - Bartek Fikcyjny.xlsx"]


def test_wykonawca_bez_rozliczenia_pracownika_w_okresie_dostaje_odmowe(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    write_worker_settlements(write_period_files(periods, "22_28_09_2026"), "22_28_09_2026", ["Anna Testowa"])
    write_worker_settlements(write_period_files(periods, "29_05_10_2026"), "29_05_10_2026", ["Celina Inna"])

    response = app.client.post("/api/periods/22_28_09_2026/worker-settlements/open", json={"worker": "Celina Inna"})

    assert (response.status_code, response.json()) == (
        404,
        {"message": "Rozliczenia pracownika Celina Inna nie ma w okresie 22_28_09_2026."},
    )
    assert app.platform.opened == []


@pytest.mark.parametrize("worker", ["x/../../../poza", "a/b", "..\\poza", "..", ""])
def test_nazwa_wykonawcy_nie_wyprowadza_poza_folder_rozliczen_pracownikow(tmp_path: Path, worker: str) -> None:
    app, periods = with_periods_directory(tmp_path)
    worker_folder = write_worker_settlements(write_period_files(periods, "22_28_09_2026"), "22_28_09_2026", [])
    # Pliki, które otworzyłaby ścieżka sklejona z nazwą bez sprawdzenia: poza folderem i w podfolderze.
    (worker_folder / "Rozliczenie 22_28_09_2026 - x").mkdir()
    (periods / "poza.xlsx").touch()
    (worker_folder / "Rozliczenie 22_28_09_2026 - a").mkdir()
    (worker_folder / "Rozliczenie 22_28_09_2026 - a" / "b.xlsx").touch()

    response = app.client.post("/api/periods/22_28_09_2026/worker-settlements/open", json={"worker": worker})

    assert response.status_code == 404
    assert app.platform.opened == []


def log_lines(app: Centrum) -> list[str]:
    """Wpisy dziennika Centrum bez znacznika czasu."""

    if not app.log_path.exists():
        return []
    return [line.split(" ", 1)[1] for line in app.log_path.read_text(encoding="utf-8").splitlines()]


def test_zamkniecie_centrum_z_karty_jest_przyjete_i_zapisane_w_dzienniku(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/shutdown")

    assert response.status_code == 202
    assert response.json() == {"state": "closing"}
    assert log_lines(app) == ['zamkniecie z="karta Centrum"']


def test_nieoczekiwany_wyjatek_daje_bezpieczny_komunikat_i_wpis_bez_tekstu_wyjatku(tmp_path: Path) -> None:
    app, periods = with_periods_directory(tmp_path)
    write_period_files(periods, "22_28_09_2026")
    secret = f"{periods / '22_28_09_2026'} ul. Syntetyczna 1 CENTRUM-SYN-ROW"
    app.platform.failure = RuntimeError(secret)

    response = app.client.post("/api/periods/22_28_09_2026/open", json={"target": "collective_file"})

    assert response.status_code == 500
    assert response.json() == {
        "message": "W Centrum rozliczeń wystąpił nieoczekiwany błąd. Odśwież kartę i spróbuj ponownie."
    }
    assert log_lines(app) == [
        "ustawienia-zmiana plik=centrum-ustawienia.yaml klucze=foldery.folder_okresow zrodlo=tata",
        'nieoczekiwany-wyjatek typ=RuntimeError miejsce="POST /api/periods/{token}/open"',
    ]
    log = app.log_path.read_text(encoding="utf-8")
    assert "Syntetyczna" not in log and "CENTRUM-SYN-ROW" not in log and str(periods) not in log
