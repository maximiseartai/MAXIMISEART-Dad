"""Centrum rozliczeń przez jego HTTP API, tak jak widzi je przeglądarka taty."""

from __future__ import annotations

import base64
import codecs
import errno
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, get_args
import imaplib

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from hypothesis import example, given, settings
from hypothesis import strategies as st
import yaml
import pytest

from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import collective_file_name_with
from rozliczenia.period_folder import PeriodFolder, PeriodFolderInaccessible
from rozliczenia import efenix_process, intermax_messages
from rozliczenia.centrum import app, diagnosis_messages
from rozliczenia.centrum.app import STATIC_DIRECTORY
from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.centrum.contract.common import Message
from rozliczenia.centrum.dad_action_journal import DAD_ACTIONS_FILE
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, OLD_NOTES_FILE, OLD_REPORTS_FILE
from rozliczenia.centrum.notifications import NOTIFICATIONS_FILE
from rozliczenia.centrum.outbox import ADDRESSES_FILE, QUEUE_DIRECTORY
from rozliczenia.centrum.keyed_box import REPORT_KEY_FILE
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY
from rozliczenia.centrum.run_origins import CENTRUM_RUNS_FILE
from rozliczenia.centrum.shortcut import SHORTCUT_FILE, StartupShortcut, system_autostart
from rozliczenia.telemetry import CompletedResult, MetricsStore, RecordedStop, metric_record
from rozliczenia.tool_files import CONFIG_DIR, LOG_PATH
from rozliczenia.centrum.settings import history as history_module
from rozliczenia.centrum.settings.files import FieldPath
from rozliczenia.centrum.settings.folders import FOLDERS, SETTINGS_FILE, FolderSettings
from rozliczenia.centrum.settings.history import HISTORY_FILE
from rozliczenia.centrum.settings.memory import APPLIED_FILE, MEMORY_DIRECTORY, settings_bytes
from rozliczenia.centrum.settings.migrations.reminders import OLD_FOOTER_FILE, OLD_ROLLOUT_FILE
from rozliczenia.centrum.settings.migrations.workers import OLD_ADDRESSES_FILE, OLD_MAPPING_FILE
from rozliczenia.centrum.rule_forms import form_of
from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.centrum.settings.proposal import (
    Edit,
    Later,
    Nothing,
    Proposal,
    Refuse,
    ReleaseChange,
    ReleaseInputs,
)
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.centrum.tool_freshness import ToolFreshness
from rozliczenia.worker_list import UnmatchedLogin, WorkerEntry, WorkerList
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE
from rozliczenia.worker_reports import Login, SenderAddress
from rozliczenia.centrum.settings import quantity_rules as settings_quantity_rules
from rozliczenia.centrum.settings.quantity_rules import DEVICES, DEVICES_FILE, DEVICES_SECTION, RULES, RULES_FILE
from rozliczenia.quantity_engine import Component, ContainsComponent, DeviceList, Fill, QuantityRules, QuantityRulesRefused, RulesProblem
from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES, parse_rule
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS, without_access, without_reading
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
from tests.fixtures.centrum_processes import (
    PERIOD_MONDAY,
    PreparingCentrum,
    SettlingCentrum,
    Surroundings,
    on_register_read,
    preparing_centrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
    write_dad_quantity_rules,
)
from tests.fixtures.tool_clone import tool_repository

from atrapy.pliki_taty import REGISTER_NAME
from atrapy.settlement import PERIOD, worker_list, write_source, write_worker_list
from atrapy.settlement import WORKERS as SETTLEMENT_WORKERS
from atrapy.workbooks import rewrite_parts
from atrapy.skrzynka_raportow import AtrapaImap
from atrapy.preparation import (
    OLD_REGISTER_HEADERS,
    REGISTER_HEADERS,
    RegisterRow,
    register_order,
    write_collective_template,
    write_register,
)

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
# Sekcja Wykonawcy bez pliku Listy Wykonawców: pusta lista jest dobra (DESIGN D10).
NO_WORKERS: dict[str, object] = {"state": "good", "workers": [], "unresolved": [], "problem": None}
DAMAGED = "Plik centrum-ustawienia.yaml w folderze config ma uszkodzoną treść. Zapisz Ustawienia jeszcze raz."
REGISTER_PATH = "Rejestr zleceń to plik Excel .xlsx podany pełną ścieżką. Wybierz go oknem wyboru."
PERIODS_PATH = "Folder okresów trzeba podać pełną ścieżką. Wybierz go oknem wyboru."
NO_INBOX: dict[str, object] = {"inbox": {"address": None, "password": False}, "inbox_problem": None}
ADR_0030_REMINDERS: dict[str, object] = {
    "morning": {"start": "08:00", "end": "17:00"},
    "evening": {"start": "18:00", "end": "22:00"},
    "first": "08:00",
    "text": "Poproszę o wysłanie raportu za dzień {dzień}.",
    "footer": "",
}
"""Formularz sekcji Przypomnienia z wartościami z ADR 0030 i speca #1344: pory 8:00–17:00 i 18:00–22:00, pierwsze
przypomnienie od 8:00 dnia następnego, pierwsze zdanie ze speca, bez stopki."""
# Sekcja Przypomnienia bez pliku przypomnień: wartości z ADR 0030, wyłączone (DESIGN D2).
NO_REMINDERS: dict[str, object] = {**ADR_0030_REMINDERS, "state": "good", "enabled": False, "since": None, "problem": None}
"""Skrzynka raportów bez pliku dostępu: bez adresu i bez hasła (#1469)."""


def test_brak_pliku_ustawien_znaczy_nie_ustawiono(tmp_path: Path) -> None:
    response = centrum(tmp_path).client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "order_register": NOT_SET,
        "periods_directory": NOT_SET,
        "periods_all_years": False,
        "theme": "dark",
        "folders_problem": None,
        "workers": NO_WORKERS,
        **NO_INBOX,
        "autostart": AUTOSTART_SHOWN_OFF,
        "reminders": NO_REMINDERS,
    }


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


def test_nieznane_pole_pliku_ustawien_ma_numer_od_gory_a_nie_nazwe_z_pliku(tmp_path: Path) -> None:
    """Nazwa pola to tekst z pliku (np. login wpisany ręcznie w złe miejsce), a zdanie trafia do Logów Centrum i do
    Zgłoszenia, więc mówi tylko, które to pole od góry (przegląd #1529 r2, D2)."""

    app = centrum(tmp_path)
    app.settings_path.parent.mkdir(parents=True)
    app.settings_path.write_text(f"schema_version: 1\nmotyw: light\n{LEAKED_LOGIN}: {LEAKED_NAME}\n", encoding="utf-8")

    response = app.client.get("/api/settings")

    assert response.json()["folders_problem"] == {"field": None, "message": settings_messages.unknown_key(SETTINGS_FILE, 3)}
    assert LEAKED_LOGIN not in response.text + app.tool.log_path.read_text(encoding="utf-8")


def test_uszkodzony_plik_ustawien_bez_dobrej_tresci_to_zle_ustawienie_z_wartosciami_domyslnymi(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.settings_path.parent.mkdir(parents=True)
    app.settings_path.write_text("rejestr: [nie zamknięta lista\n", encoding="utf-8")

    response = app.client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "order_register": NOT_SET,
        "periods_directory": NOT_SET,
        "periods_all_years": False,
        "theme": "dark",
        "folders_problem": {"field": None, "message": DAMAGED},
        "workers": NO_WORKERS,
        **NO_INBOX,
        "autostart": AUTOSTART_SHOWN_OFF,
        "reminders": NO_REMINDERS,
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
    """Ustawienia Centrum mówią o nich to, co Diagnoza („Nie da się teraz odczytać”), a nie „Nie ma już” ani błąd."""

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
            "periods_all_years": False,
            "theme": "dark",
            "folders_problem": None,
            "workers": NO_WORKERS,
            **NO_INBOX,
            "autostart": AUTOSTART_SHOWN_OFF,
            "reminders": NO_REMINDERS,
        },
    )


@NO_ACCESS_ON_WINDOWS
def test_niedostepny_plik_ustawien_nie_udaje_niewskazanych_sciezek(tmp_path: Path) -> None:
    """Plik Ustawień Centrum trzymany np. przez antywirus: wskazanych ścieżek nie widać, ale nie są „nie wskazano”."""

    app, _ = with_periods_directory(tmp_path)

    app.settings_path.chmod(0)
    try:
        response = app.client.get("/api/settings")
    finally:
        app.settings_path.chmod(0o644)

    assert (response.status_code, response.json()) == (
        200,
        {
            "order_register": UNREADABLE,
            "periods_directory": UNREADABLE,
            "periods_all_years": False,
            "theme": "dark",
            "folders_problem": None,
            "workers": NO_WORKERS,
            **NO_INBOX,
            "autostart": AUTOSTART_SHOWN_OFF,
            "reminders": NO_REMINDERS,
        },
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
        {
            "order_register": UNREADABLE,
            "periods_directory": UNREADABLE,
            "periods_all_years": False,
            "theme": "dark",
            "folders_problem": None,
            "workers": NO_WORKERS,
            **NO_INBOX,
            "autostart": AUTOSTART_SHOWN_OFF,
            "reminders": NO_REMINDERS,
        },
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
    "Nie udało się zapisać Ustawień Centrum w folderze config. Sprawdź, czy folder otwiera się w Eksploratorze plików, "
    "nie jest tylko do odczytu i czy OneDrive działa, potem spróbuj ponownie."
)
AUTOSTART_NOT_CHANGED = (
    "Nie udało się zmienić startu Centrum razem z Windows. Spróbuj ponownie. "
    "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
)
AUTOSTART_UNSUPPORTED = "Start razem z Windows działa tylko na komputerze z Windows."
AUTOSTART_SHOWN_OFF = {"state": "off", "reason": None}
AUTOSTART_UNREADABLE = "Nie da się teraz sprawdzić folderu Autostart. Odśwież okno za chwilę."


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
        "periods_all_years": False,
        "theme": "light",
        "folders_problem": None,
        "workers": NO_WORKERS,
        **NO_INBOX,
        "autostart": AUTOSTART_SHOWN_OFF,
        "reminders": NO_REMINDERS,
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
    assert (again.json()["settings"]["theme"], again.json()["settings"]["periods_directory"]["path"]) == (
        "light",
        str(periods),
    )


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

    assert (changed.json()["settings"]["theme"], changed.json()["settings"]["periods_directory"]["path"]) == (
        "light",
        str(periods),
    )
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
    themed = app.client.put("/api/settings/theme", json={"theme": "light"})
    rows = history_rows(app)

    assert [(row["source"], row["section"], row["changes"], row["undoable"]) for row in rows] == [
        ("tata", "wyglad", [{"key": "wyglad.motyw", "before": "dark", "after": "light"}], True),
        ("tata", "foldery", [{"key": "foldery.folder_okresow", "before": None, "after": str(periods)}], True),
        ("tata", "foldery", [{"key": "foldery.rejestr_zlecen", "before": None, "after": str(register)}], True),
    ]
    assert [chosen.json()["change"], saved.json()["change"], themed.json()["change"]] == [row["id"] for row in rows[::-1]]
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


QUANTITY_RULES_URL = "/api/settings/quantity-rules"


def rule_sentences(app: Centrum) -> dict[str, str]:
    """Zdanie każdej reguły z odpowiedzi sekcji Reguły ilości; kolumna jako „nazwa (litera)” albo sama litera."""

    response = app.client.get(QUANTITY_RULES_URL)
    assert response.status_code == 200, response.text
    return {
        rule["id"]: "".join(
            part["text"] if part["kind"] == "text" else part["letter"] if part["name"] is None else f"{part['name']} ({part['letter']})"
            for part in rule["sentence"]
        )
        for rule in response.json()["rules"]
    }


def test_kazda_regula_ilosci_z_wydania_ma_w_ustawieniach_zdanie_jesli_to_a_bez_wzorca_kolumna_to_litera(tmp_path: Path) -> None:
    response = centrum(tmp_path).client.get(QUANTITY_RULES_URL).json()
    sentences = rule_sentences(centrum(tmp_path))

    assert [(rule["id"], rule["scope"]) for rule in response["rules"]] == [
        (rule.id, {"znane": "known", "nieznane": "unknown", "kazde": "every"}[rule.scope.value])
        for rule in DEFAULT_QUANTITY_RULES.rules
    ]
    assert all(sentence[0].isupper() and sentence.endswith(".") for sentence in sentences.values())
    assert (response["rules_problem"], response["devices_problem"]) == (None, None)
    # Zdania wybranych reguł, po jednej na każdy rodzaj warunku, działania i mnożnika (ADR 0033).
    assert {rule: sentences[rule] for rule in RULE_SENTENCES} == RULE_SENTENCES


RULE_SENTENCES = {
    "z-opisu-puste": "Jeśli URZĄDZENIA są puste, to nic nie wpisuj w tym zleceniu.",
    "z-opisu-prewencja": "Jeśli URZĄDZENIA to dokładnie „prewencja”, to nic nie wpisuj w tym zleceniu.",
    "v-znane": "Wpisz 1 w V, ale nie gdy URZĄDZENIA zawierają „instalacja ręczna”.",
    "v-nieznane": "Wpisz 1 w V.",
    "t-umowa-u": "Jeśli UMOWA zaczyna się od słowa „u”, to wpisz 1 w T.",
    "dodatek-usterka-pn-pt": "Jeśli URZĄDZENIA zawierają „usterka” i DATA to poniedziałek–piątek od 17:00, to wpisz 45 w N.",
    "dodatek-usterka-sobota": "Jeśli URZĄDZENIA zawierają „usterka” i DATA to sobota od 0:00, to wpisz 45 w N.",
    "nokia-bez-routera-akt-int": (
        "Jeśli URZĄDZENIA zawierają „nokia” i CZYNNOŚCI zawierają „akt int”, "
        "ale nie gdy zlecenie ma urządzenie z grupy router, to wpisz 1 w O."
    ),
    "technicolor": "Jeśli URZĄDZENIA zawierają „technicolor”, to wpisz liczbę „technicolor” w O, Z i AK.",
    "gateway-z-extenderem": (
        "Jeśli URZĄDZENIA zawierają „gateway” i zlecenie ma urządzenie z grupy extender, to wpisz liczbę „gateway” w AO."
    ),
    "instalacja-reczna": (
        "Jeśli URZĄDZENIA zawierają „instalacja ręczna”, to wpisz „N szt” z CZYNNOŚCI za każde „instalacja ręczna” w AN i V."
    ),
    "inea-gniazdo": "Jeśli URZĄDZENIA zawierają tekst „gniazdo”, to zostaw AP pustą w Rozliczeniu pracownika.",
}


def test_kolumna_reguly_ilosci_ma_nazwe_pozycji_cennika_z_wiersza_17_wzorca_pliku_zbiorczego(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.tool.config.mkdir(parents=True)
    template = write_collective_template(app.tool.configuration.collective_template)
    workbook = load_workbook(template)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet["Z17"], sheet["AK17"] = "ONT  Nokia\nz montażem", "Technicolor (opis)"
    workbook.save(template)

    sentences = rule_sentences(app)

    assert sentences["technicolor"] == (
        "Jeśli URZĄDZENIA zawierają „technicolor”, to wpisz liczbę „technicolor” w O, ONT Nokia z montażem (Z) "
        "i Technicolor (opis) (AK)."
    )
    assert sentences["inea-gniazdo"] == "Jeśli URZĄDZENIA zawierają tekst „gniazdo”, to zostaw demontaż (AP) pustą w Rozliczeniu pracownika."


def test_lista_urzadzen_w_ustawieniach_ma_kazdy_skladnik_z_innymi_zapisami_i_grupa(tmp_path: Path) -> None:
    devices = centrum(tmp_path).client.get(QUANTITY_RULES_URL).json()["devices"]

    assert [device["id"] for device in devices] == [component.id for component in DEFAULT_QUANTITY_RULES.devices.components]
    shown = {device["id"]: (device["name"], device["other_spellings"], device["group"]) for device in devices}
    assert (shown["gateway"], shown["usterka"], shown["fut"]) == (
        ("gateway", ["zyxel"], "router"),
        ("usterka", ["usterka hurt", "usterka wew"], None),
        ("fut", [], "tv"),
    )


NOKIA_Z = "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia}"
MANUAL_INSTALLATION = "  - {id: instalacja-reczna, zapisy: [instalacja ręczna, wizja]}\n"
NEW_COMPONENT = "  - {id: nowy, zapisy: [nowy]}\n"


def test_lista_urzadzen_bez_skladnika_regul_ilosci_to_zle_ustawienie_listy_a_procesy_licza_ostatnia_dobra_para(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("wartosc: 1", "wartosc: 2"))
    rule_sentences(app)
    write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, "")

    response = app.client.get(QUANTITY_RULES_URL).json()

    assert (response["rules_problem"], response["devices_problem"]) == (
        None,
        {
            "field": None,
            "message": f"Plik {DEVICES_FILE} w folderze config nie ma składnika „instalacja ręczna”, którego potrzebują "
            "Reguły ilości, więc Centrum liczy ostatnią dobrą Listą Urządzeń.",
        },
    )
    assert "instalacja-reczna" in [device["id"] for device in response["devices"]]
    assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 2 × liczbę „nokia” w Z."
    tools_see = read_snapshot(app.tool.config).quantity_rules
    assert (tools_see.devices, tools_see.rules == DEFAULT_QUANTITY_RULES.rules) == (DEFAULT_QUANTITY_RULES.devices, False)
    assert [(row["file"], row["refused"]) for row in history_rows(app)] == [(DEVICES_FILE, True)]


def test_lista_urzadzen_bez_skladnika_taty_z_reguly_nazywa_go_tak_jak_sekcja_urzadzenia(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + "  - {id: ont-x, zapisy: [ont x]}\n")
    write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: ont-x"))
    rule_sentences(app)
    write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION)

    response = app.client.get(QUANTITY_RULES_URL).json()

    assert response["devices_problem"] == {
        "field": None,
        "message": f"Plik {DEVICES_FILE} w folderze config nie ma składnika „ont x”, którego potrzebują Reguły ilości, "
        "więc Centrum liczy ostatnią dobrą Listą Urządzeń.",
    }
    assert {device["id"]: device["name"] for device in response["devices"]}["ont-x"] == "ont x"


def test_uszkodzona_lista_urzadzen_to_zle_ustawienie_listy_a_widac_ostatnia_dobra_liste(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    devices = write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + NEW_COMPONENT)
    rule_sentences(app)
    devices.write_text("urzadzenia: [", encoding="utf-8")

    response = app.client.get(QUANTITY_RULES_URL).json()

    assert (response["rules_problem"], response["devices_problem"]) == (
        None,
        {"field": None, "message": f"Plik {DEVICES_FILE} w folderze config ma uszkodzoną treść. Zapisz Ustawienia jeszcze raz."},
    )
    assert "nowy" in [device["id"] for device in response["devices"]]


DEVICES_URL = "/api/settings/devices"


def device_form(app: Centrum | PreparingCentrum, device_id: str) -> dict[str, Any]:
    """Składnik z sekcji Urządzenia jako formularz zapisu: nazwa, inne zapisy i grupa."""

    device = next(device for device in app.client.get(QUANTITY_RULES_URL).json()["devices"] if device["id"] == device_id)
    return {"name": device["name"], "other_spellings": device["other_spellings"], "group": device["group"]}


def test_zapis_dopisany_do_skladnika_ma_wiersz_historii_zdaniem_przed_i_po_a_cofniecie_go_usuwa(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    form = device_form(app, "gateway")
    ids = [device["id"] for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]]

    saved = app.client.put(f"{DEVICES_URL}/gateway", json={**form, "other_spellings": [*form["other_spellings"], " Nowy,Router "]})
    [row] = history_rows(app)
    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert saved.status_code == 200, saved.text
    # Zmieniony składnik zostaje na swoim miejscu listy.
    assert [device["id"] for device in saved.json()["quantity_rules"]["devices"]] == ids
    shown = {device["id"]: device for device in saved.json()["quantity_rules"]["devices"]}
    assert (shown["gateway"]["other_spellings"], saved.json()["change"]) == (["zyxel", "nowy router"], row["id"])
    assert (row["source"], row["file"], row["section"]) == ("tata", DEVICES_FILE, "urzadzenia")
    assert [(change["key"], _text(change["before"]), _text(change["after"])) for change in row["rules"]] == [
        (
            "urzadzenia.gateway",
            "Składnik „gateway”, też „zyxel”, grupa router.",
            "Składnik „gateway”, też „zyxel”, „nowy router”, grupa router.",
        )
    ]
    assert undone.status_code == 200, undone.text
    assert device_form(app, "gateway") == form


def test_nowy_skladnik_z_grupa_staje_na_koncu_listy_urzadzen_a_historia_mowi_dodano(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    saved = app.client.post(DEVICES_URL, json={"name": "ONT X", "other_spellings": ["ont-x2", ""], "group": "extender"})

    assert saved.status_code == 200, saved.text
    assert saved.json()["quantity_rules"]["devices"][-1] == {
        "id": "ont-x",
        "name": "ont x",
        "other_spellings": ["ont-x2"],
        "group": "extender",
    }
    [row] = history_rows(app)
    assert [(change["key"], change["before"], _text(change["after"])) for change in row["rules"]] == [
        ("urzadzenia.ont-x", None, "Składnik „ont x”, też „ont-x2”, grupa extender.")
    ]
    assert "ont-x" in [component.id for component in read_snapshot(app.tool.config).quantity_rules.devices.components]


@pytest.mark.parametrize(
    ("request_line", "body", "refusal"),
    [
        (
            ("put", "nokia"),
            {"name": "nokia", "other_spellings": ["ZYXEL"], "group": None},
            {"field": "zapisy[0]", "message": "Zapis „zyxel” ma już składnik „gateway”. Jeden zapis należy do jednego składnika."},
        ),
        (
            ("post", None),
            {"name": "Fut", "other_spellings": [], "group": "tv"},
            {"field": "nazwa", "message": "Zapis „fut” ma już składnik „fut”. Jeden zapis należy do jednego składnika."},
        ),
        (
            ("post", None),
            {"name": " , ", "other_spellings": ["nowy"], "group": None},
            {"field": "nazwa", "message": "Wpisz nazwę składnika tak, jak stoi w URZĄDZENIA."},
        ),
        (
            ("put", "fut"),
            {"name": "fut", "other_spellings": ["fut*2"], "group": "tv"},
            {"field": "zapisy[0]", "message": "Zapis „fut*2” nie może mieć gwiazdki: w URZĄDZENIA gwiazdka to liczba sztuk, np. 2*fut."},
        ),
    ],
)
def test_zly_skladnik_z_sekcji_urzadzenia_sie_nie_zapisuje_a_odmowa_ma_pole_i_zdanie(
    tmp_path: Path, request_line: tuple[str, str | None], body: dict[str, Any], refusal: dict[str, str]
) -> None:
    app = centrum(tmp_path)
    method, device = request_line

    refused = app.client.request(method.upper(), DEVICES_URL if device is None else f"{DEVICES_URL}/{device}", json=body)

    assert (refused.status_code, refused.json()) == (422, refusal)
    assert ((app.tool.config / DEVICES_FILE).exists(), history_rows(app)) == (False, [])


def test_usuniecie_skladnika_potrzebnego_regule_jest_odmowa_ze_zdaniem_tej_reguly_a_innego_wchodzi_do_historii(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)

    refused = app.client.delete(f"{DEVICES_URL}/technicolor")
    removed = app.client.delete(f"{DEVICES_URL}/globo")

    assert (refused.status_code, refused.json()) == (
        422,
        {
            "message": "Składnika „technicolor” potrzebuje reguła: Jeśli URZĄDZENIA zawierają „technicolor”, to wpisz liczbę "
            "„technicolor” w O, Z i AK. Najpierw zmień albo usuń tę regułę w sekcji Reguły ilości."
        },
    )
    assert removed.status_code == 200, removed.text
    ids = [device["id"] for device in removed.json()["quantity_rules"]["devices"]]
    assert ("technicolor" in ids, "globo" in ids) == (True, False)
    [row] = history_rows(app)
    assert [(change["key"], _text(change["before"]), change["after"]) for change in row["rules"]] == [
        ("urzadzenia.globo", "Składnik „globo”, grupa TV.", None)
    ]


@pytest.mark.parametrize(("name", "expected_id"), [("ont/stb", "ont-stb"), ("wizja #2?", "wizja-2"), ("..", "skladnik")])
def test_nowy_skladnik_ze_znakami_adresu_w_nazwie_ma_id_bez_nich_a_jego_zmiana_i_usuniecie_dzialaja(
    tmp_path: Path, name: str, expected_id: str
) -> None:
    app = centrum(tmp_path)

    added = app.client.post(DEVICES_URL, json={"name": name, "other_spellings": [], "group": None})
    identifier = added.json()["quantity_rules"]["devices"][-1]["id"]
    changed = app.client.put(f"{DEVICES_URL}/{identifier}", json={"name": name, "other_spellings": ["ont stb"], "group": "tv"})
    removed = app.client.delete(f"{DEVICES_URL}/{identifier}")

    assert (added.status_code, identifier) == (200, expected_id), added.text
    assert (changed.status_code, removed.status_code) == (200, 200), (changed.text, removed.text)
    assert new_components(app) == {}


def test_zmiana_albo_usuniecie_skladnika_ktorego_juz_nie_ma_to_odmowa_bez_zapisu(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    changed = app.client.put(f"{DEVICES_URL}/nie-ma", json={"name": "x", "other_spellings": [], "group": None})
    removed = app.client.delete(f"{DEVICES_URL}/nie-ma")

    unknown = {"message": "Tego składnika już nie ma na Liście Urządzeń. Odśwież okno Ustawień."}
    assert [(changed.status_code, changed.json()), (removed.status_code, removed.json())] == [(404, unknown)] * 2
    assert history_rows(app) == []


DEVICE_FORMS: dict[str, dict[str, Any]] = {
    "X": {"name": "ont x", "other_spellings": ["ont-x2"], "group": None},
    "X2": {"name": "ont x", "other_spellings": [], "group": "extender"},
    "Y": {"name": "ont y", "other_spellings": [], "group": None},
}


def _component_sentence(form: dict[str, Any]) -> str:
    also = "".join(f", też „{spelling}”" if index == 0 else f", „{spelling}”" for index, spelling in enumerate(form["other_spellings"]))
    group = "" if form["group"] is None else f", grupa {form['group']}"
    return f"Składnik „{form['name']}”{also}{group}."


def new_components(app: Centrum) -> dict[str, str]:
    """Składniki spoza Listy Urządzeń z Wydania jako zdania, po id."""

    default = {component.id for component in DEFAULT_QUANTITY_RULES.devices.components}
    return {
        device["id"]: _component_sentence(device)
        for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]
        if device["id"] not in default
    }


def test_skladnik_dodany_znowu_po_usunieciu_ma_nowe_id_a_cofniecie_usuniecia_pierwszego_nie_rusza_nowego(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    first = app.client.post(DEVICES_URL, json=DEVICE_FORMS["X"]).json()["quantity_rules"]["devices"][-1]["id"]
    assert app.client.delete(f"{DEVICES_URL}/{first}").status_code == 200
    again = app.client.post(DEVICES_URL, json=DEVICE_FORMS["X2"])
    [_, removed, _] = reversed(history_rows(app))

    restored = app.client.post(f"/api/settings/history/{removed['id']}/undo")

    second = again.json()["quantity_rules"]["devices"][-1]["id"]
    assert first != second
    # Oba składniki mają zapis „ont x”, więc usunięty nie wraca obok nowego: odmowa ze zdaniem, a nowy zostaje, jak był.
    assert (restored.status_code, bool(restored.json()["message"])) == (422, True), restored.text
    assert new_components(app) == {second: _component_sentence(DEVICE_FORMS["X2"])}


def test_nowy_skladnik_przy_historii_bez_odczytu_to_odmowa_bez_zapisu_a_dodany_potem_ma_nowe_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tata dodaje składnik i go usuwa, a potem dodaje go znowu, gdy system nie daje czytać Historii Ustawień (plik trzyma
    OneDrive): bez kluczy Historii nowy dostałby id usuniętego i zniknąłby po „Cofnij” usunięcia, więc zapis jest odmową
    bez zmian w plikach. Dodany, gdy Historia znów się czyta, ma własne id."""

    app = centrum(tmp_path)
    first = app.client.post(DEVICES_URL, json=DEVICE_FORMS["X"]).json()["quantity_rules"]["devices"][-1]["id"]
    assert app.client.delete(f"{DEVICES_URL}/{first}").status_code == 200
    devices_before, rows_before = (app.tool.config / DEVICES_FILE).read_bytes(), history_rows(app)

    with unreadable_history(monkeypatch):
        refused = app.client.post(DEVICES_URL, json=DEVICE_FORMS["X2"])
    devices_after, rows_after = (app.tool.config / DEVICES_FILE).read_bytes(), history_rows(app)
    second = app.client.post(DEVICES_URL, json=DEVICE_FORMS["X2"]).json()["quantity_rules"]["devices"][-1]["id"]

    assert (refused.status_code, refused.json()) == (500, {"message": SETTINGS_NOT_SAVED})
    assert (devices_after, rows_after) == (devices_before, rows_before)
    assert second != first


# Krok taty w sekcji Urządzenia: zapis składnika (także nowego, gdy Historii nie da się przeczytać) albo „Cofnij” wiersza
# Historii Listy Urządzeń; liczba wybiera składnik albo wiersz.
_DEVICE_STEP = st.one_of(
    st.tuples(st.just("dodaj"), st.sampled_from(sorted(DEVICE_FORMS))),
    st.tuples(st.just("zmien"), st.integers(0, 9), st.sampled_from(sorted(DEVICE_FORMS))),
    st.tuples(st.just("usun"), st.integers(0, 9)),
    st.tuples(st.just("cofnij"), st.integers(0, 9)),
    st.tuples(st.just("dodaj bez historii"), st.sampled_from(sorted(DEVICE_FORMS))),
)


def test_po_dowolnych_zapisach_listy_urzadzen_i_cofnieciach_kazdy_nowy_skladnik_ma_wlasne_id_a_cofniecie_zmienia_tylko_jego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Po dowolnych zapisach taty w sekcji Urządzenia i cofnięciach z Historii: nowy składnik dostaje id, którego nie
    miał żaden składnik przed nim, a „Cofnij” wiersza zmienia tylko składnik tego wiersza; cofnięcie, którego nie da się
    wykonać, nie zmienia żadnego składnika i mówi zdaniem dlaczego. Zapis z zapisem innego składnika to odmowa 422, a
    nowy składnik, gdy Historii nie da się przeczytać, to odmowa bez zmiany listy."""

    examples = itertools.count()
    forms = {_component_sentence(form): form for form in DEVICE_FORMS.values()}

    def spellings(form: dict[str, Any]) -> set[str]:
        return {form["name"], *form["other_spellings"]}

    def taken(expected: dict[str, str], form: dict[str, Any], own: str | None) -> bool:
        return any(spellings(form) & spellings(forms[sentence]) for device, sentence in expected.items() if device != own)

    @settings(derandomize=True, database=None, deadline=None, max_examples=25)
    @given(st.lists(_DEVICE_STEP, min_size=3, max_size=8))
    def steps_hold(steps: list[tuple[Any, ...]]) -> None:
        app = centrum(tmp_path / str(next(examples)))
        expected: dict[str, str] = {}
        given_ids: set[str] = set()
        for step in steps:
            ids = list(expected)
            match step:
                case ("dodaj", name):
                    form = DEVICE_FORMS[name]
                    response = app.client.post(DEVICES_URL, json=form)
                    if taken(expected, form, None):
                        assert response.status_code == 422, (steps, response.text)
                    else:
                        added = response.json()["quantity_rules"]["devices"][-1]["id"]
                        assert added not in given_ids, f"id {added} usuniętego składnika wróciło do nowego"
                        given_ids.add(added)
                        expected[added] = _component_sentence(form)
                case ("dodaj bez historii", name):
                    with unreadable_history(monkeypatch):
                        response = app.client.post(DEVICES_URL, json=DEVICE_FORMS[name])
                    assert response.status_code in (422, 500), (steps, response.text)
                case ("zmien", index, name) if ids:
                    device = ids[index % len(ids)]
                    form = DEVICE_FORMS[name]
                    response = app.client.put(f"{DEVICES_URL}/{device}", json=form)
                    if taken(expected, form, device):
                        assert response.status_code == 422, (steps, response.text)
                    else:
                        expected[device] = _component_sentence(form)
                case ("usun", index) if ids:
                    device = ids[index % len(ids)]
                    response = app.client.delete(f"{DEVICES_URL}/{device}")
                    del expected[device]
                case ("cofnij", index):
                    rows = [row for row in history_rows(app) if row["section"] == DEVICES_SECTION]
                    if not rows:
                        continue
                    row = rows[index % len(rows)]
                    [component] = row["rules"]
                    response = app.client.post(f"/api/settings/history/{row['id']}/undo")
                    if response.status_code == 200:
                        device = component["key"].removeprefix(f"{DEVICES_SECTION}.")
                        expected.pop(device, None)
                        if component["before"] is not None:
                            expected[device] = str(_text(component["before"]))
                    else:
                        assert response.json()["message"], response.text
                case _:
                    continue
            assert response.status_code in (200, 409, 422, 500), response.text
            assert new_components(app) == expected, steps

    steps_hold()


def _previous_release() -> QuantityRules:
    """Wcześniejsze Wydanie: Reguły ilości i Lista Urządzeń z Wydania bez składnika „instalacja ręczna” i bez reguł, które
    go potrzebują."""

    devices = DeviceList(tuple(component for component in DEFAULT_QUANTITY_RULES.devices.components if component.id != "instalacja-reczna"))

    def fits(rule: Any) -> bool:
        try:
            QuantityRules((rule,), devices)
        except QuantityRulesRefused:
            return False
        return True

    return QuantityRules(tuple(rule for rule in DEFAULT_QUANTITY_RULES.rules if fits(rule)), devices)


def _released(monkeypatch: pytest.MonkeyPatch, rules: QuantityRules) -> None:
    """Centrum z Regułami ilości i Listą Urządzeń z Wydania ``rules``, jak po Aktualizacji do tego Wydania."""

    monkeypatch.setattr(settings_quantity_rules, "DEFAULT_QUANTITY_RULES", rules)
    settings_quantity_rules._parse_rules.cache_clear()
    settings_quantity_rules._parse_devices.cache_clear()


@pytest.fixture
def release_without_manual_installation(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], None]]:
    """Wcześniejsze Wydanie (``_previous_release``). Wywołanie zwrócone przez fixture to Aktualizacja do dzisiejszego
    Wydania (reguły znów potrzebują składnika „instalacja ręczna”)."""

    _released(monkeypatch, _previous_release())
    yield lambda: _released(monkeypatch, DEFAULT_QUANTITY_RULES)
    monkeypatch.undo()
    settings_quantity_rules._parse_rules.cache_clear()
    settings_quantity_rules._parse_devices.cache_clear()


def test_wydanie_z_regulami_potrzebujacymi_skladnika_spoza_listy_taty_zostawia_liste_taty_i_mowi_co_zrobic(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    app = centrum(tmp_path)
    nokia = device_form(app, "nokia")
    assert app.client.put(f"{DEVICES_URL}/nokia", json={**nokia, "other_spellings": ["ont nokia"]}).status_code == 200

    release_without_manual_installation()
    response = app.client.get(QUANTITY_RULES_URL).json()

    assert (response["rules_problem"], response["devices_problem"]) == (
        None,
        {
            "field": None,
            "message": "Reguły ilości z Wydania potrzebują składnika „instalacja ręczna”, którego nie ma na Liście Urządzeń, "
            "więc Centrum bierze go z Listy Urządzeń z Wydania. Żeby został na liście, zapisz go: ołówek przy nim, potem "
            "„Zapisz”.",
        },
    )
    shown = {device["id"]: device["other_spellings"] for device in response["devices"]}
    assert (shown["nokia"], shown["instalacja-reczna"], list(shown)[-1]) == (["ont nokia"], ["wizja"], "instalacja-reczna")
    tools_see = read_snapshot(app.tool.config).quantity_rules
    assert tools_see.rules == DEFAULT_QUANTITY_RULES.rules
    assert [component.spellings for component in tools_see.devices.components if component.id in ("nokia", "instalacja-reczna")] == [
        ("nokia", "ont nokia"),
        ("instalacja ręczna", "wizja"),
    ]


def test_lista_taty_zapisana_po_wydaniu_z_nowym_skladnikiem_regul_ma_go_i_znow_pasuje_do_regul(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    app = centrum(tmp_path)
    nokia = device_form(app, "nokia")
    app.client.put(f"{DEVICES_URL}/nokia", json={**nokia, "other_spellings": ["ont nokia"]})
    release_without_manual_installation()

    saved = app.client.put(f"{DEVICES_URL}/instalacja-reczna", json=device_form(app, "instalacja-reczna"))

    assert saved.status_code == 200, saved.text
    assert saved.json()["quantity_rules"]["devices_problem"] is None
    dad_list = DEVICES.parse((app.tool.config / DEVICES_FILE).read_bytes())
    assert isinstance(dad_list, tuple) and "instalacja-reczna" in [component.id for component in dad_list]
    assert [change["key"] for change in history_rows(app)[0]["changes"]] == ["urzadzenia.instalacja-reczna"]


def _dad_list(app: Centrum) -> tuple[Component, ...] | None:
    """Lista Urządzeń z pliku taty; ``None``: tata nie ma pliku."""

    data = settings_bytes(app.tool.config / DEVICES_FILE)
    if not isinstance(data, bytes):
        return None
    dad_list = DEVICES.parse(data)
    assert isinstance(dad_list, tuple)
    return dad_list


def test_skladnik_wydania_zmieniony_w_sekcji_przed_zapisaniem_na_liscie_taty_zapisuje_sie_ze_zmiana(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    """Składnik z Wydania, którego lista taty jeszcze nie ma, sekcja pokazuje na liście, więc tata zmienia go jak każdy
    inny: dopisany zapis trafia na listę taty razem ze składnikiem i liczy się w procesach."""

    app = centrum(tmp_path)
    nokia = device_form(app, "nokia")
    assert app.client.put(f"{DEVICES_URL}/nokia", json={**nokia, "other_spellings": ["ont nokia"]}).status_code == 200
    release_without_manual_installation()
    form = device_form(app, "instalacja-reczna")

    saved = app.client.put(f"{DEVICES_URL}/instalacja-reczna", json={**form, "other_spellings": [*form["other_spellings"], "ont x"]})

    assert saved.status_code == 200, saved.text
    dad_list = _dad_list(app)
    assert dad_list is not None and Component("instalacja-reczna", ("instalacja ręczna", "wizja", "ont x")) in dad_list
    assert [component.id for component, _ in read_snapshot(app.tool.config).quantity_rules.devices.find(["ont", "x"])[0]] == [
        "instalacja-reczna"
    ]


def _collective_cell(centrum: PreparingCentrum, cell: str) -> object:
    workbook = load_workbook(centrum.fixture.collective_file_path, read_only=True)
    try:
        return workbook.worksheets[0][cell].value
    finally:
        workbook.close()


def test_zapis_taty_ktory_nastepne_wydanie_daje_nowemu_skladnikowi_zostaje_u_taty_a_przygotowanie_liczy_lista_taty(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    """Tata dopisał „ont nokia” do „nokia” i dodał z podpowiedzi składnik „instalacja ręczna”, a następne Wydanie daje
    ten zapis nowemu składnikowi reguł (zapisy „instalacja ręczna” i „wizja”). Zapis taty wygrywa: Przygotowanie liczy
    listą taty, składnik z Wydania dochodzi z zapisem, którego tata nie ma, a zapisanie go zdaniem sekcji i usunięcie
    własnego składnika przechodzą."""

    orders = ((1, "ont nokia"), (2, "wizja"))
    centrum = preparing_centrum(tmp_path, [{**register_order(number, PERIOD_MONDAY), "URZĄDZENIA": devices} for number, devices in orders])
    nokia = device_form(centrum, "nokia")
    assert centrum.client.put(f"{DEVICES_URL}/nokia", json={**nokia, "other_spellings": ["ont nokia"]}).status_code == 200
    added = centrum.client.post(DEVICES_URL, json={"name": "instalacja ręczna", "other_spellings": [], "group": None})
    own = added.json()["quantity_rules"]["devices"][-1]["id"]

    release_without_manual_installation()
    shown = centrum.client.get(QUANTITY_RULES_URL).json()
    run_to_end(centrum, dry_run=False)

    devices = {device["id"]: device for device in shown["devices"]}
    assert (devices["nokia"]["other_spellings"], devices[own]["name"]) == (["ont nokia"], "instalacja ręczna")
    assert devices["instalacja-reczna"] == {"id": "instalacja-reczna", "name": "wizja", "other_spellings": [], "group": None}
    assert shown["devices_problem"] == {"field": None, "message": settings_messages.needed_by_release_rules("wizja")}
    # „ont nokia” liczy reguła „nokia” (Z), a „wizja” reguła składnika z Wydania (AN).
    assert (_collective_cell(centrum, "Z18"), _collective_cell(centrum, "AN19")) == (1, 1)
    saved = centrum.client.put(f"{DEVICES_URL}/instalacja-reczna", json=device_form(centrum, "instalacja-reczna"))
    assert (saved.status_code, saved.json()["quantity_rules"]["devices_problem"]) == (200, None), saved.text
    assert centrum.client.delete(f"{DEVICES_URL}/{own}").status_code == 200


def test_skladnik_wydania_bez_zapisu_spoza_listy_taty_liczy_sie_jakby_go_nie_bylo_a_zwolnienie_zapisu_go_przywraca(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    """Tata ma oba zapisy nowego składnika następnego Wydania w swoim składniku: składnik z Wydania nie dochodzi, a reguły z
    Wydania liczą tak, jakby żadne zlecenie go nie miało (reguła „zawierają” odpada, „nie zawierają” zawsze zachodzi). Lista
    taty zostaje cała, a sekcja mówi, jak zwolnić zapis; zwolniony składnik z Wydania dochodzi i liczą się wszystkie reguły."""

    app = centrum(tmp_path)
    nokia = device_form(app, "nokia")
    assert app.client.put(f"{DEVICES_URL}/nokia", json={**nokia, "other_spellings": ["ont nokia"]}).status_code == 200
    added = app.client.post(DEVICES_URL, json={"name": "instalacja ręczna", "other_spellings": ["wizja"], "group": None})
    own = added.json()["quantity_rules"]["devices"][-1]["id"]
    dad_list = DEVICES.parse((app.tool.config / DEVICES_FILE).read_bytes())
    assert isinstance(dad_list, tuple)

    release_without_manual_installation()
    shown = app.client.get(QUANTITY_RULES_URL).json()
    counted = read_snapshot(app.tool.config).quantity_rules

    assert [device["id"] for device in shown["devices"]] == [component.id for component in dad_list]
    assert shown["devices_problem"] == {
        "field": None,
        "message": "Reguły ilości z Wydania mają składnik „instalacja ręczna”, ale ten zapis ma już składnik „instalacja "
        "ręczna” z listy, więc Centrum liczy bez niego. Żeby liczyło z nim, zmień nazwę składnika „instalacja ręczna”: "
        "ołówek przy nim, potem „Zapisz”.",
    }
    assert counted.devices.components == dad_list
    rules = {rule.id: rule for rule in counted.rules}
    assert ("instalacja-reczna" in rules, rules["v-znane"].conditions) == (False, ())
    freed = app.client.put(f"{DEVICES_URL}/{own}", json={"name": "wizja", "other_spellings": [], "group": None})
    assert (freed.status_code, freed.json()["quantity_rules"]["devices_problem"]) == (200, None), freed.text
    assert device_form(app, "instalacja-reczna") == {"name": "instalacja ręczna", "other_spellings": [], "group": None}
    assert read_snapshot(app.tool.config).quantity_rules.rules == DEFAULT_QUANTITY_RULES.rules


def test_narzedzia_licza_lista_taty_zmieniona_poza_centrum_gdy_skladnik_wydania_ma_tylko_jej_zapisy(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    """Lista taty z oboma zapisami nowego składnika Wydania jest dobra także dla narzędzi: zmieniona poza Centrum, zanim
    Centrum ją przeczyta, liczy się od razu, a nie ostatnia dobra lista z pamięci."""

    app = centrum(tmp_path)
    app.client.post(DEVICES_URL, json={"name": "instalacja ręczna", "other_spellings": ["wizja"], "group": None})
    release_without_manual_installation()
    path = app.tool.config / DEVICES_FILE
    dad_list = DEVICES.parse(path.read_bytes())
    assert isinstance(dad_list, tuple)
    path.write_text(DEVICES.dump((*dad_list, Component("ont-x", ("ont x",)))), encoding="utf-8")

    assert "ont-x" in read_snapshot(app.tool.config).quantity_rules.devices.ids()


def test_narzedzia_licza_regulami_z_wydania_gdy_plik_regul_taty_zniknal_poza_centrum(tmp_path: Path) -> None:
    """Tata ma reguły bez reguł składnika „instalacja ręczna” i listę bez niego, a plik reguł znika poza Centrum, zanim
    Centrum go przeczyta: narzędzia liczą Regułami ilości z Wydania ze składnikiem z Listy Urządzeń z Wydania, jak
    procesy, a nie ostatnimi dobrymi regułami taty."""

    app = centrum(tmp_path)
    devices = tuple(component for component in DEVICES.default if component.id != "instalacja-reczna")
    rules = tuple(rule for rule in RULES.default if rule.id not in {"v-znane", "instalacja-reczna"})
    app.tool.config.mkdir(parents=True, exist_ok=True)
    (app.tool.config / DEVICES_FILE).write_text(DEVICES.dump(devices), encoding="utf-8")
    (app.tool.config / RULES_FILE).write_text(RULES.dump(rules), encoding="utf-8")
    accepted = app.client.get(QUANTITY_RULES_URL).json()
    assert (accepted["rules_problem"], accepted["devices_problem"], len(accepted["rules"])) == (None, None, len(rules))
    (app.tool.config / RULES_FILE).unlink()

    counted = read_snapshot(app.tool.config).quantity_rules

    assert counted.rules == DEFAULT_QUANTITY_RULES.rules
    assert "instalacja-reczna" in counted.devices.ids()


@pytest.mark.parametrize(
    ("changed", "old", "new"),
    [
        (DEVICES_FILE, NEW_COMPONENT, ""),
        (RULES_FILE, "skladnik: nowy", "skladnik: ont-x"),
    ],
    ids=["lista-bez-skladnika-reguly", "regula-ze-skladnikiem-spoza-listy"],
)
def test_narzedzia_licza_ostatnia_dobra_para_gdy_plik_taty_zmieniony_poza_centrum_nie_pasuje_do_drugiego(
    tmp_path: Path, changed: str, old: str, new: str
) -> None:
    """Tata ma składnik „nowy” spoza Listy Urządzeń z Wydania i regułę z nim, oba przyjęte; potem jeden z plików zmienia
    się poza Centrum tak, że nie pasuje do drugiego, zanim Centrum go przeczyta: narzędzia liczą ostatnią dobrą parą."""

    app = centrum(tmp_path)
    devices = write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + NEW_COMPONENT)
    rules = write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: nowy"))
    rule_sentences(app)
    accepted = read_snapshot(app.tool.config).quantity_rules
    assert "nowy" in accepted.devices.ids()
    path = {DEVICES_FILE: devices, RULES_FILE: rules}[changed]
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")

    assert read_snapshot(app.tool.config).quantity_rules == accepted


@pytest.mark.parametrize("others", [["wizja"], []], ids=["oba-zapisy-u-taty", "jeden-zapis-u-taty"])
def test_cofniecie_dodania_skladnika_taty_z_zapisem_skladnika_wydania_oddaje_skladnikowi_wydania_jego_zapisy(
    tmp_path: Path, release_without_manual_installation: Callable[[], None], others: list[str]
) -> None:
    """Tata dodał składnik „instalacja ręczna” (z zapisem „wizja” albo bez), a następne Wydanie daje te zapisy nowemu
    składnikowi reguł. „Cofnij” dodania przechodzi za pierwszym razem: składnik taty znika, a składnik z Wydania dostaje
    oba zapisy, w pliku taty i w procesach, i sekcja nie ma już zdania."""

    app = centrum(tmp_path)
    app.client.post(DEVICES_URL, json={"name": "instalacja ręczna", "other_spellings": others, "group": None})
    [added] = history_rows(app)
    release_without_manual_installation()

    undone = app.client.post(f"/api/settings/history/{added['id']}/undo")

    assert undone.status_code == 200, undone.text
    assert app.client.get(QUANTITY_RULES_URL).json()["devices_problem"] is None
    dad_list = _dad_list(app)
    assert dad_list is not None and [component.spellings for component in dad_list if "instalacja ręczna" in component.spellings] == [
        ("instalacja ręczna", "wizja")
    ]
    counted = read_snapshot(app.tool.config).quantity_rules
    assert counted.devices.find(["instalacja", "ręczna"]) == ([(Component("instalacja-reczna", ("instalacja ręczna", "wizja")), 1)], True)
    assert counted.rules == DEFAULT_QUANTITY_RULES.rules


def _nokia_rule(app: Centrum, value: int) -> dict[str, Any]:
    """Formularz reguły „nokia” z sekcji Reguły ilości z wartością ``value``: zmiana, której nic nie łączy ze składnikiem
    z Wydania."""

    rule = next(rule for rule in app.client.get(QUANTITY_RULES_URL).json()["rules"] if rule["id"] == "nokia")["rule"]
    assert isinstance(rule, dict)
    return {**rule, "action": {**rule["action"], "writes": [{**rule["action"]["writes"][0], "value": value}]}}


def test_zmiana_reguly_przy_skladniku_wydania_ktorego_zapisy_ma_tata_czeka_na_zwolniony_zapis_tak_samo_w_podgladzie(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    """Tata ma oba zapisy nowego składnika następnego Wydania w swoim składniku, więc reguły z Wydania liczą bez niego.
    Sekcja Reguły ilości mówi, że zmiana reguł czeka na zwolniony zapis, a zapis i podgląd zmiany reguły odmawiają tym
    samym zdaniem, bez pliku reguł. Po działaniu ze zdania zmiana reguły się zapisuje, a sekcja ma regułę składnika z
    Wydania."""

    app = centrum(tmp_path)
    added = app.client.post(DEVICES_URL, json={"name": "instalacja ręczna", "other_spellings": ["wizja"], "group": None})
    own = added.json()["quantity_rules"]["devices"][-1]["id"]
    release_without_manual_installation()
    rule = _nokia_rule(app, 2)
    waiting = settings_messages.rules_wait_for_release_component("instalacja ręczna", "instalacja ręczna", "nazwa")

    shown = app.client.get(QUANTITY_RULES_URL).json()
    saved = app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=rule)
    previewed = app.client.post(f"{QUANTITY_RULES_URL}/preview", json={"kind": "change", "rule_id": "nokia", "rule": rule})

    assert shown["rules_problem"] == {"field": None, "message": waiting}
    assert "instalacja-reczna" not in [shown_rule["id"] for shown_rule in shown["rules"]]
    assert (saved.status_code, saved.json()["message"]) == (422, waiting)
    assert (previewed.status_code, previewed.json()["message"]) == (422, waiting)
    assert settings_bytes(app.tool.config / RULES_FILE) is None
    # Działanie ze zdania: zmiana nazwy składnika taty zwalnia zapis „instalacja ręczna”, a „wizja” zostaje u taty.
    freed = app.client.put(f"{DEVICES_URL}/{own}", json={"name": "ręczna", "other_spellings": ["wizja"], "group": None})
    assert freed.status_code == 200, freed.text
    saved = app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=rule)
    assert saved.status_code == 200, saved.text
    assert saved.json()["quantity_rules"]["rules_problem"] is None
    assert "instalacja-reczna" in [shown_rule["id"] for shown_rule in saved.json()["quantity_rules"]["rules"]]


@pytest.mark.parametrize("others", [["wizja"], []], ids=["zderzenie", "skladnik-do-dodania"])
def test_cofniecie_zmiany_reguly_po_usunieciu_pliku_regul_przy_skladniku_wydania_idzie_ta_sama_droga_co_zapis_reguly(
    tmp_path: Path, release_without_manual_installation: Callable[[], None], others: list[str]
) -> None:
    """Tata zmienił regułę dwa razy, Maks usunął jego plik reguł, a Wydanie daje nowy składnik reguł. „Cofnij” drugiej
    zmiany zapisuje pierwszy plik reguł taty tak jak edytor: przy zderzeniu odmawia tym samym zdaniem bez zmiany plików,
    a przy składniku z Wydania z wolnym zapisem zapisuje go najpierw na liście taty."""

    app = centrum(tmp_path)
    app.client.post(DEVICES_URL, json={"name": "instalacja ręczna", "other_spellings": others, "group": None})
    for value in (2, 3):
        assert app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=_nokia_rule(app, value)).status_code == 200
    [second, *_] = [row for row in history_rows(app) if row["file"] == RULES_FILE]
    (app.tool.config / RULES_FILE).unlink()
    release_without_manual_installation()
    devices_before = settings_bytes(app.tool.config / DEVICES_FILE)

    undone = app.client.post(f"/api/settings/history/{second['id']}/undo")

    if others:
        waiting = settings_messages.rules_wait_for_release_component("instalacja ręczna", "instalacja ręczna", "nazwa")
        assert (undone.status_code, undone.json()["message"]) == (422, waiting)
        assert (settings_bytes(app.tool.config / RULES_FILE), settings_bytes(app.tool.config / DEVICES_FILE)) == (None, devices_before)
    else:
        assert undone.status_code == 200, undone.text
        assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 2 × liczbę „nokia” w Z."
        dad_list = _dad_list(app)
        assert dad_list is not None and Component("instalacja-reczna", ("wizja",)) in dad_list


def test_zmiana_reguly_przy_skladniku_wydania_spoza_listy_taty_zapisuje_go_na_liscie_taty_osobnym_wierszem(
    tmp_path: Path, release_without_manual_installation: Callable[[], None]
) -> None:
    """Lista taty bez nowego składnika następnego Wydania (procesy biorą go z listy z Wydania). Pierwsza zmiana reguły
    taty zapisuje się z listą, do której pasuje: najpierw składnik z Wydania na liście taty (wiersz jak „ołówek, Zapisz”
    przy nim), potem reguła; podgląd tej zmiany przechodzi tak samo."""

    app = centrum(tmp_path)
    nokia = device_form(app, "nokia")
    assert app.client.put(f"{DEVICES_URL}/nokia", json={**nokia, "other_spellings": ["ont nokia"]}).status_code == 200
    release_without_manual_installation()
    rule = _nokia_rule(app, 2)

    previewed = app.client.post(f"{QUANTITY_RULES_URL}/preview", json={"kind": "change", "rule_id": "nokia", "rule": rule})
    saved = app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=rule)

    assert previewed.status_code == 200, previewed.text
    assert saved.status_code == 200, saved.text
    assert (saved.json()["quantity_rules"]["rules_problem"], saved.json()["quantity_rules"]["devices_problem"]) == (None, None)
    assert [(row["file"], [change["key"] for change in row["changes"]]) for row in history_rows(app)[:2]] == [
        (RULES_FILE, ["reguly.nokia"]),
        (DEVICES_FILE, ["urzadzenia.instalacja-reczna"]),
    ]


# Zapisy, które tata daje w sekcji Urządzenia przed Wydaniem: oba zapisy składnika „instalacja ręczna”, który daje dopiero
# następne Wydanie, i zapisy spoza obu list.
_DAD_SPELLINGS = ("instalacja ręczna", "wizja", "ont nokia", "ont x")
# Krok taty przed Wydaniem: nowy składnik z zapisami z puli, zapis z puli dopisany do składnika z listy albo jedyny zapis
# składnika z listy (reguły z Wydania dalej go potrzebują).
_DAD_LIST_STEP = st.one_of(
    st.tuples(st.just("dodaj"), st.lists(st.sampled_from(_DAD_SPELLINGS), min_size=1, max_size=2, unique=True)),
    st.tuples(st.sampled_from(("dopisz", "zastap")), st.sampled_from(("nokia", "fut", "gateway")), st.sampled_from(_DAD_SPELLINGS)),
)


def _proposed(app: Centrum, message: str) -> tuple[str, str, dict[str, Any] | None]:
    """Działanie, które proponuje zdanie sekcji Urządzenia ``message``, tak jak je wykona formularz: metoda, adres i
    formularz. Zapis usuwa się tylko × przy innym zapisie (nazwy formularz nie usuwa), a składnik „Usuń składnik"."""

    for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]:
        url = f"{DEVICES_URL}/{device['id']}"
        form = {"name": device["name"], "other_spellings": device["other_spellings"], "group": device["group"]}
        if message == settings_messages.needed_by_release_rules(device["name"]):
            return "PUT", url, form
        for spelling in (device["name"], *device["other_spellings"]):
            proposals: dict[settings_messages.TakenAction, tuple[str, str, dict[str, Any] | None]] = {
                "skladnik": ("DELETE", url, None),
                "nazwa": ("PUT", url, {**form, "name": "zapis taty"}),
            }
            if spelling in device["other_spellings"]:
                proposals["zapis"] = ("PUT", url, {**form, "other_spellings": [kept for kept in device["other_spellings"] if kept != spelling]})
            for how, proposal in proposals.items():
                if message == settings_messages.release_component_taken(spelling, device["name"], how):
                    return proposal
    raise AssertionError(f"zdanie bez działania, które ma formularz: {message}")


def _holds_dad_spellings(app: Centrum, context: object) -> None:
    """Każdy zapis listy taty należy w procesach do składnika, któremu dał go tata: nigdy cała para z Wydania."""

    counted = read_snapshot(app.tool.config).quantity_rules
    for component in _dad_list(app) or ():
        for spelling in component.spellings:
            assert counted.devices.find(spelling.split()) == ([(component, 1)], True), (context, spelling)


def _release_rule_components() -> frozenset[str]:
    """Identyfikatory składników, których potrzebują Reguły ilości z Wydania (warunek „zawierają” albo wpis razy składnik)."""

    needed = {condition.component for rule in DEFAULT_QUANTITY_RULES.rules for condition in rule.conditions if isinstance(condition, ContainsComponent)}
    needed |= {
        write.component
        for rule in DEFAULT_QUANTITY_RULES.rules
        if isinstance(rule.action, Fill)
        for write in rule.action.writes
        if write.component is not None
    }
    return frozenset(needed)


def _undo_holds(app: Centrum, row: dict[str, Any], context: object) -> None:
    """„Cofnij” wiersza Listy Urządzeń przechodzi albo odmawia bez zmiany pliku zdaniem, które jest prawdą: przywrócony
    składnik ma zapis, który ma już inny składnik listy taty (każdy zapis należy do jednego składnika), albo „Cofnij” usuwa
    składnik, którego potrzebują Reguły ilości z Wydania, a Lista Urządzeń z Wydania oddałaby go taki sam, więc zmiana
    nic by nie zmieniła (zdanie reguły z jego nazwą z sekcji)."""

    before = settings_bytes(app.tool.config / DEVICES_FILE)
    shown = {device["id"]: device for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]}
    restored = {component.id: component.spellings for component in _dad_list(app) or ()}
    removed: set[str] = set()
    for change in row["changes"]:
        identifier = change["key"].removeprefix(f"{DEVICES_SECTION}.")
        restored.pop(identifier, None)
        if change["before"] is not None:
            restored[identifier] = tuple(json.loads(change["before"])["zapisy"])
        elif identifier in shown:
            removed.add(identifier)
    owners = Counter(spelling for spellings in restored.values() for spelling in spellings)
    shared = sorted(spelling for spelling, count in owners.items() if count > 1)
    release = {component.id: component for component in DEFAULT_QUANTITY_RULES.devices.components}
    same_back = [
        identifier
        for identifier in sorted(removed & _release_rule_components())
        if (tuple(spelling for spelling in release[identifier].spellings if spelling not in owners), release[identifier].group)
        == ((shown[identifier]["name"], *shown[identifier]["other_spellings"]), shown[identifier]["group"])
    ]
    truthful = [f"Zapis „{spelling}” ma już składnik „" for spelling in shared] + [
        f"Składnika „{shown[identifier]['name']}” potrzebuje reguła: " for identifier in same_back
    ]

    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    if undone.status_code == 200:
        return
    assert undone.status_code == 422, (context, undone.text)
    assert any(undone.json()["message"].startswith(sentence) for sentence in truthful), (context, truthful, undone.text)
    assert settings_bytes(app.tool.config / DEVICES_FILE) == before, context


def test_po_dowolnej_liscie_taty_wydanie_z_nowym_skladnikiem_regul_liczy_kazdy_jej_zapis_a_zdanie_sekcji_i_cofniecie_przechodza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tata zmienia Listę Urządzeń, także zapisami składnika, który daje dopiero następne Wydanie, a potem Wydanie daje
    reguły z tym składnikiem i tata cofa w Historii swoje zmiany listy. Każdy zapis listy taty należy w procesach dalej do
    składnika, któremu dał go tata (nigdy cała para z Wydania). „Cofnij” przechodzi albo odmawia bez zmiany zdaniem, które
    jest prawdą, a działanie, które sekcja Urządzenia proponuje zdaniem, przechodzi i zmienia listę; po tych działaniach
    liczą się wszystkie Reguły ilości z Wydania."""

    examples = itertools.count()

    @settings(derandomize=True, database=None, deadline=None, max_examples=30)
    @given(st.lists(_DAD_LIST_STEP, min_size=1, max_size=4), st.lists(st.integers(min_value=0, max_value=4), max_size=3))
    @example([("dodaj", ["instalacja ręczna"])], [])
    @example([("dodaj", ["instalacja ręczna", "wizja"])], [])
    @example([("dodaj", ["instalacja ręczna"]), ("dodaj", ["wizja"])], [])
    @example([("zastap", "fut", "instalacja ręczna"), ("dopisz", "nokia", "wizja")], [])
    # Zapis ma składnik, którego potrzebuje reguła: zdanie każe zmienić jego nazwę, nie usunąć go.
    @example([("zastap", "nokia", "instalacja ręczna"), ("dopisz", "gateway", "wizja")], [])
    # Sonda recenzenta r2: „Cofnij” dodania własnego składnika taty z zapisami składnika z Wydania i bez jednego z nich.
    @example([("dodaj", ["instalacja ręczna", "wizja"])], [0])
    @example([("dodaj", ["instalacja ręczna"])], [0])
    # „Cofnij” zmiany „fut”, gdy jego dawny zapis ma już nowy składnik taty: odmowa, która jest prawdą.
    @example([("zastap", "fut", "instalacja ręczna"), ("dodaj", ["fut"])], [1])
    # „Cofnij” cofnięcia dodania: składnik taty wraca, a składnik z Wydania dochodzi z wolnym zapisem, inny niż był.
    @example([("dodaj", ["instalacja ręczna"])], [0, 0])
    def list_holds(steps: list[tuple[Any, ...]], undos: list[int]) -> None:
        _released(monkeypatch, _previous_release())
        app = centrum(tmp_path / str(next(examples)))
        for step in steps:
            match step:
                case ("dodaj", spellings):
                    response = app.client.post(DEVICES_URL, json={"name": spellings[0], "other_spellings": spellings[1:], "group": None})
                case (how, device, spelling):
                    form = device_form(app, device)
                    changed = {"other_spellings": [*form["other_spellings"], spelling]} if how == "dopisz" else {"name": spelling, "other_spellings": []}
                    response = app.client.put(f"{DEVICES_URL}/{device}", json={**form, **changed})
                case _:
                    raise AssertionError(step)
            assert response.status_code in (200, 422), response.text
        if _dad_list(app) is None:
            return

        _released(monkeypatch, DEFAULT_QUANTITY_RULES)
        counted = read_snapshot(app.tool.config).quantity_rules
        shown = [device["id"] for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]]

        assert shown == [component.id for component in counted.devices.components], steps
        _holds_dad_spellings(app, steps)
        # „Cofnij” zmian listy sprzed Wydania, potem działania ze zdań sekcji, a drugi raz „Cofnij” także tych działań.
        for _ in range(2):
            for undo in undos:
                rows = [row for row in history_rows(app) if row["file"] == DEVICES_FILE and row["undoable"] and not row["refused"]]
                _undo_holds(app, rows[undo % len(rows)], (steps, undos))
                _holds_dad_spellings(app, (steps, undos))
            for _ in range(4):
                problem = app.client.get(QUANTITY_RULES_URL).json()["devices_problem"]
                if problem is None:
                    break
                method, url, body = _proposed(app, problem["message"])
                response = app.client.request(method, url, json=body)
                assert response.status_code == 200, (steps, undos, problem, response.text)
                assert response.json()["change"] is not None, (steps, undos, problem)
            assert app.client.get(QUANTITY_RULES_URL).json()["devices_problem"] is None, (steps, undos)
            assert read_snapshot(app.tool.config).quantity_rules.rules == DEFAULT_QUANTITY_RULES.rules, (steps, undos)

    list_holds()


def _rule_with(component: str) -> dict[str, Any]:
    """Formularz reguły „Jeśli URZĄDZENIA zawierają składnik, to wpisz 3 × jego liczbę w Z” dla składnika ``component``."""

    return {
        "scope": "known",
        "conditions": [{"kind": "component", "component": component, "negated": False}],
        "action": {"kind": "fill", "writes": [{"column": "Z", "value": 3, "multiplier": "component", "component": component}]},
    }


ONT_Y_RULE = "Jeśli URZĄDZENIA zawierają „ont y”, to wpisz 3 × liczbę „ont y” w Z."


def test_cofniecie_dodania_skladnika_potrzebnego_regule_taty_odmawia_zdaniem_tej_reguly_tak_samo_jak_usuniecie_w_sekcji(
    tmp_path: Path,
) -> None:
    """Sonda przeglądu #1577 r3, składnik: tata ma własny plik reguł, dodał składnik „ont y” i regułę z nim. „Usuń
    składnik” i „Cofnij” dodania to ta sama zmiana, więc obie odmawiają tym samym zdaniem reguły z nazwą składnika, a nie
    zdaniem o pliku, który jest dobry."""

    app = centrum(tmp_path)
    assert app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=_nokia_rule(app, 2)).status_code == 200
    added = app.client.post(DEVICES_URL, json={"name": "ont y", "other_spellings": [], "group": None})
    own = added.json()["quantity_rules"]["devices"][-1]["id"]
    [add_row] = [row for row in history_rows(app) if row["file"] == DEVICES_FILE]
    assert app.client.post(QUANTITY_RULES_URL, json=_rule_with(own)).status_code == 200
    files = (settings_bytes(app.tool.config / DEVICES_FILE), settings_bytes(app.tool.config / RULES_FILE))

    removed = app.client.delete(f"{DEVICES_URL}/{own}")
    undone = app.client.post(f"/api/settings/history/{add_row['id']}/undo")

    refused = {
        "message": f"Składnika „ont y” potrzebuje reguła: {ONT_Y_RULE} Najpierw zmień albo usuń tę regułę w sekcji Reguły ilości."
    }
    assert [(removed.status_code, removed.json()), (undone.status_code, undone.json())] == [(422, refused)] * 2
    assert (settings_bytes(app.tool.config / DEVICES_FILE), settings_bytes(app.tool.config / RULES_FILE)) == files
    section = app.client.get(QUANTITY_RULES_URL).json()
    assert (section["devices_problem"], section["rules_problem"]) == (None, None)


def test_cofniecie_usuniecia_reguly_ze_skladnikiem_usunietym_potem_odmawia_zdaniem_reguly_z_nazwa_skladnika_jak_edytor(
    tmp_path: Path,
) -> None:
    """Sonda przeglądu #1577 r3, reguła: tata usunął regułę ze składnikiem „ont y”, potem sam składnik. „Cofnij” usunięcia
    reguły i ta sama reguła z edytora to ta sama zmiana: obie odmawiają zdaniem reguły ze składnikiem nazwanym tak, jak
    tata go widział na liście (nie jego identyfikatorem), a edytor stawia je przy polu składnika."""

    app = centrum(tmp_path)
    added = app.client.post(DEVICES_URL, json={"name": "ont y", "other_spellings": [], "group": None})
    own = added.json()["quantity_rules"]["devices"][-1]["id"]
    saved = app.client.post(QUANTITY_RULES_URL, json=_rule_with(own))
    rule_id = next(rule["id"] for rule in saved.json()["quantity_rules"]["rules"] if rule["rule"] == _rule_with(own))
    assert app.client.delete(f"{QUANTITY_RULES_URL}/{rule_id}").status_code == 200
    [remove_row, *_] = [row for row in history_rows(app) if row["file"] == RULES_FILE]
    assert app.client.delete(f"{DEVICES_URL}/{own}").status_code == 200
    files = (settings_bytes(app.tool.config / DEVICES_FILE), settings_bytes(app.tool.config / RULES_FILE))

    undone = app.client.post(f"/api/settings/history/{remove_row['id']}/undo")
    again = app.client.post(QUANTITY_RULES_URL, json=_rule_with(own))

    sentence = f"Reguła potrzebuje składnika „ont y”, którego nie ma na Liście Urządzeń: {ONT_Y_RULE} Najpierw dodaj ten składnik w sekcji Urządzenia."
    assert (undone.status_code, undone.json()) == (422, {"message": sentence})
    assert (again.status_code, again.json()) == (422, {"message": sentence, "field": "jesli[0].skladnik"})
    assert (settings_bytes(app.tool.config / DEVICES_FILE), settings_bytes(app.tool.config / RULES_FILE)) == files


# Formularze składnika w teście równoważności: „ont z” bierze zapis „ont x”, a „ont w” zapis „ont y”.
_PAIR_FORMS: dict[str, dict[str, Any]] = {
    "ont x": {"name": "ont x", "other_spellings": ["ont-x2"], "group": None},
    "ont y": {"name": "ont y", "other_spellings": [], "group": None},
    "ont z": {"name": "ont z", "other_spellings": ["ont x"], "group": "tv"},
    "ont w": {"name": "ont w", "other_spellings": ["ont y"], "group": None},
}
# Formularz, który bierze zapis składnika taty z ``_PAIR_FORMS``.
_PAIR_PARTNER: dict[str, str] = {"ont x": "ont z", "ont z": "ont x", "ont y": "ont w", "ont w": "ont y"}
# Zmiana taty z formularza sekcji Urządzenia albo Reguły ilości, albo „Cofnij” wiersza Historii. Składnik wskazuje jego
# nazwa w sekcji (składniki taty z ``_PAIR_FORMS`` i „nokia” z Wydania), regułę jej miejsce od końca listy (reguły taty
# stoją na końcu), a wiersz Historii liczba. Kroki złożone to kilka formularzy po kolei na składniku taty, który dodają,
# gdy go nie ma: „składnik z regułą” (reguła z nim), „reguła bez składnika” (reguła z nim, ta reguła zmieniona na „nokia”,
# usunięcie składnika) i „zastąp składnik” (usunięcie go i dodanie składnika, który bierze jego zapis). Po każdym z nich
# „Cofnij” jednego z wierszy należy się odmowa, a Hypothesis zaczyna od pierwszych wyborów, więc stoją one pierwsze.
_PAIR_FORM = st.sampled_from(("ont y", "ont x", "ont z", "ont w"))
_PAIR_TARGET = st.sampled_from(("ont y", "ont x", "ont z", "ont w", "nokia"))
_PAIR_RULE = st.integers(1, 3)
_PAIR_STEP = st.one_of(
    st.tuples(st.just("składnik z regułą"), _PAIR_FORM),
    st.tuples(st.just("reguła bez składnika"), _PAIR_FORM),
    st.tuples(st.just("zastąp składnik"), _PAIR_FORM),
    st.tuples(st.just("dodaj składnik"), _PAIR_FORM),
    st.tuples(st.just("usuń składnik"), _PAIR_TARGET),
    st.tuples(st.just("zmień składnik"), _PAIR_TARGET, _PAIR_FORM),
    st.tuples(st.just("dodaj regułę"), _PAIR_TARGET),
    st.tuples(st.just("zmień regułę"), _PAIR_RULE, _PAIR_TARGET),
    st.tuples(st.just("usuń regułę"), _PAIR_RULE),
    st.tuples(st.just("cofnij"), st.integers(0, 9)),
)


def _compound(app: Centrum, kind: str, component: str, form: str) -> int:
    """Krok złożony testu równoważności na składniku taty ``component`` z formularza ``form``: status ostatniego
    formularza, który doszedł do skutku albo odmówił."""

    if kind == "zastąp składnik":
        response = app.client.delete(f"{DEVICES_URL}/{component}")
        if response.status_code == 200:
            response = app.client.post(DEVICES_URL, json=_PAIR_FORMS[_PAIR_PARTNER[form]])
        return response.status_code
    response = app.client.post(QUANTITY_RULES_URL, json=_rule_with(component))
    if kind == "reguła bez składnika" and response.status_code == 200:
        added = response.json()["quantity_rules"]["rules"][-1]["id"]
        response = app.client.put(f"{QUANTITY_RULES_URL}/{added}", json=_rule_with("nokia"))
        if response.status_code == 200:
            response = app.client.delete(f"{DEVICES_URL}/{component}")
    return response.status_code


def _pair_state(app: Centrum) -> tuple[object, ...]:
    """Stan sekcji Urządzenia i Reguły ilości bez identyfikatorów, które formularz nadaje inaczej niż „Cofnij”: składniki
    (nazwa, inne zapisy, grupa), zdania reguł i zdania obu sekcji."""

    section = app.client.get(QUANTITY_RULES_URL).json()
    devices = sorted((device["name"], tuple(device["other_spellings"]), device["group"] or "") for device in section["devices"])
    return devices, sorted(rule_sentences(app).values()), section["devices_problem"], section["rules_problem"]


def _form_doing(app: Centrum, change: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None] | None:
    """Żądanie formularza, które robi na bieżącym stanie tę samą zmianę co „Cofnij” zmiany ``change``: klucz wraca do
    wartości sprzed niej (``None``: zmiana nic by nie zrobiła, bo wpisu już nie ma)."""

    section, _, identifier = change["key"].partition(".")
    shown = app.client.get(QUANTITY_RULES_URL).json()
    present = identifier in {entry["id"] for entry in shown["devices" if section == DEVICES_SECTION else "rules"]}
    url = f"{DEVICES_URL if section == DEVICES_SECTION else QUANTITY_RULES_URL}"
    if change["before"] is None:
        return ("DELETE", f"{url}/{identifier}", None) if present else None
    entry = json.loads(change["before"])
    if section == DEVICES_SECTION:
        form: dict[str, Any] = {"name": entry["zapisy"][0], "other_spellings": entry["zapisy"][1:], "group": entry.get("grupa")}
    else:
        # Formularz reguły tak, jak edytor dostaje ją z sekcji Reguły ilości (``rule`` reguły w odpowiedzi).
        rule = parse_rule(entry)
        assert not isinstance(rule, RulesProblem), entry
        form = form_of(rule).model_dump(mode="json")
    return ("PUT", f"{url}/{identifier}", form) if present else ("POST", url, form)


def _rule_components(form: Mapping[str, Any]) -> list[str]:
    """Składniki, których potrzebuje reguła z formularza ``form``, w kolejności pól: warunki, potem wpisy."""

    conditions = [condition.get("component") for condition in form["conditions"]]
    writes = [write.get("component") for write in (form["action"] or {}).get("writes", [])]
    return [component for component in conditions + writes if component is not None]


def _due_refusal(app: Centrum, request: tuple[str, str, dict[str, Any] | None], names: Mapping[str, str]) -> str | None:
    """Początek zdania odmowy, która należy się zmianie ``request`` taty z plikiem reguł, z modelu stanu sekcji, nie z
    kodu: usunięcie składnika, którego potrzebuje reguła, zapis, który ma już inny składnik, albo reguła ze składnikiem
    spoza listy, nazwanym tak, jak tata go ostatnio widział (``names``); ``None``: zmiana przechodzi."""

    method, url, form = request
    shown = app.client.get(QUANTITY_RULES_URL).json()
    devices = {device["id"]: (device["name"], *device["other_spellings"]) for device in shown["devices"]}
    needed = {component for rule in shown["rules"] for component in _rule_components(rule["rule"])}
    identifier = url.rpartition("/")[2]
    if url.startswith(DEVICES_URL):
        if method == "DELETE":
            return f"Składnika „{devices[identifier][0]}” potrzebuje reguła: " if identifier in needed else None
        assert form is not None
        for spelling in dict.fromkeys((form["name"], *form["other_spellings"])):
            owner = next((spellings[0] for other, spellings in devices.items() if other != identifier and spelling in spellings), None)
            if owner is not None:
                return f"Zapis „{spelling}” ma już składnik „{owner}”. Jeden zapis należy do jednego składnika."
        return None
    if method == "DELETE":
        return None
    assert form is not None
    missing = next((component for component in _rule_components(form) if component not in devices), None)
    return None if missing is None else f"Reguła potrzebuje składnika „{names[missing]}”, którego nie ma na Liście Urządzeń: "


def test_cofniecie_zmiany_taty_listy_urzadzen_albo_regul_ilosci_daje_to_samo_co_formularz_robiacy_ta_sama_zmiane(
    tmp_path: Path,
) -> None:
    """Reguła równoważności granicy (przegląd #1577 r3): po dowolnych zmianach taty z formularzy sekcji Urządzenia i Reguły
    ilości (dodaj, zmień, usuń składnik albo regułę) i „Cofnij” każdy wiersz Historii takiej zmiany cofa się na kopii stanu
    tak samo jak formularz, który robi na tym samym stanie tę samą zmianę: ten sam status i to samo zdanie odmowy, albo
    ten sam stan obu sekcji. Z plikiem reguł taty model stanu sekcji mówi też, czy odmowa się należy i jakim zdaniem:
    usunięcie składnika, którego potrzebuje reguła, zapis u dwóch składników i reguła ze składnikiem spoza listy, zawsze
    z nazwą, którą tata widział, a nie identyfikatorem."""

    examples = itertools.count()

    @settings(derandomize=True, database=None, deadline=None, max_examples=25)
    @given(st.booleans(), st.lists(_PAIR_STEP, min_size=1, max_size=7))
    # Sonda przeglądu #1577 r3: „Cofnij” dodania składnika, którego potrzebuje reguła taty, i „Cofnij” usunięcia reguły
    # po usunięciu jej składnika.
    @example(True, [("składnik z regułą", "ont y")])
    @example(False, [("dodaj składnik", "ont y"), ("dodaj regułę", "ont y"), ("usuń regułę", 1), ("usuń składnik", "ont y")])
    # „Cofnij” usunięcia składnika, którego zapis ma już nowy składnik, i zmiany reguły na składnik usunięty potem.
    @example(True, [("zastąp składnik", "ont x")])
    @example(True, [("reguła bez składnika", "ont y")])
    # „Cofnij” zmiany składnika, której zapis ma już inny składnik.
    @example(True, [("dodaj składnik", "ont y"), ("zmień składnik", "ont y", "ont x"), ("zmień składnik", "nokia", "ont w")])
    def pair_holds(own_rules: bool, steps: list[tuple[Any, ...]]) -> None:
        root = tmp_path / str(next(examples))
        app = centrum(root / "centrum")
        names: dict[str, str] = {}

        def seen() -> None:
            names.update({device["id"]: device["name"] for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]})

        def own(form: str) -> str | None:
            """Id składnika taty ``form`` w sekcji; dodaje go formularzem, gdy go nie ma (``None``: odmowa dodania)."""

            found: dict[str, str] = {device["name"]: device["id"] for device in app.client.get(QUANTITY_RULES_URL).json()["devices"]}
            if form in found:
                return found[form]
            added = app.client.post(DEVICES_URL, json=_PAIR_FORMS[form])
            seen()
            return str(added.json()["quantity_rules"]["devices"][-1]["id"]) if added.status_code == 200 else None

        if own_rules:
            assert app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=_nokia_rule(app, 2)).status_code == 200
        seen()
        for step in steps:
            shown = app.client.get(QUANTITY_RULES_URL).json()
            devices = {device["name"]: device["id"] for device in shown["devices"]}
            rules = [rule["id"] for rule in shown["rules"]]
            if step[0] in ("składnik z regułą", "reguła bez składnika", "zastąp składnik"):
                component = own(step[1])
                if component is not None:
                    assert _compound(app, step[0], component, step[1]) in (200, 422), (steps, step)
                seen()
                continue
            match step:
                case ("dodaj składnik", form):
                    response = app.client.post(DEVICES_URL, json=_PAIR_FORMS[form])
                case ("zmień składnik", target, form) if target in devices:
                    response = app.client.put(f"{DEVICES_URL}/{devices[target]}", json=_PAIR_FORMS[form])
                case ("usuń składnik", target) if target in devices:
                    response = app.client.delete(f"{DEVICES_URL}/{devices[target]}")
                case ("dodaj regułę", target) if target in devices:
                    response = app.client.post(QUANTITY_RULES_URL, json=_rule_with(devices[target]))
                case ("zmień regułę", rule, target) if target in devices:
                    response = app.client.put(f"{QUANTITY_RULES_URL}/{rules[-rule]}", json=_rule_with(devices[target]))
                case ("usuń regułę", rule):
                    response = app.client.delete(f"{QUANTITY_RULES_URL}/{rules[-rule]}")
                case ("cofnij", index):
                    undoable = [row for row in history_rows(app) if row["undoable"] and not row["refused"]]
                    if not undoable:
                        continue
                    response = app.client.post(f"/api/settings/history/{undoable[index % len(undoable)]['id']}/undo")
                case _:
                    continue
            assert response.status_code in (200, 422), (steps, step, response.text)
            seen()

        rows = [
            row
            for row in history_rows(app)
            if row["source"] == "tata" and row["undoable"] and not row["refused"] and len(row["changes"]) == 1
            and row["file"] in (DEVICES_FILE, RULES_FILE)
        ]
        # Dwa Centra na kopii stanu: jedno cofa wiersz, drugie robi tę samą zmianę formularzem.
        twins = [centrum(root / "cofnij"), centrum(root / "formularz")]
        undo_side, form_side = twins
        for row in rows:
            [change] = row["changes"]
            request = _form_doing(app, change)
            if request is None:
                continue
            due = _due_refusal(app, request, names) if settings_bytes(app.tool.config / RULES_FILE) is not None else None
            context = (own_rules, steps, change, request)
            for twin in twins:
                shutil.rmtree(twin.tool.config, ignore_errors=True)
                shutil.copytree(app.tool.config, twin.tool.config)
            undone = undo_side.client.post(f"/api/settings/history/{row['id']}/undo")
            method, url, body = request
            formed = form_side.client.request(method, url, json=body)

            assert undone.status_code == formed.status_code, (context, undone.text, formed.text)
            if undone.status_code == 200:
                assert _pair_state(undo_side) == _pair_state(form_side), context
            else:
                assert undone.json()["message"] == formed.json()["message"], context
                assert "folderze config" not in undone.json()["message"], context
            if settings_bytes(app.tool.config / RULES_FILE) is not None:
                assert undone.status_code == (200 if due is None else 422), (context, due, undone.text)
                assert due is None or undone.json()["message"].startswith(due), (context, due, undone.text)
        for twin in (*twins, app):
            twin.client.stop()

    pair_holds()


def _rules_changed_under_damaged_dad_list(app: Centrum) -> Path:
    """Lista Urządzeń taty ze składnikiem spoza listy z Wydania i reguła z tym składnikiem, obie przyjęte; potem lista
    się psuje, a reguła zmienia wartość: pasuje tylko do ostatniej dobrej listy z pamięci, nie do listy z Wydania."""

    devices = write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + NEW_COMPONENT)
    write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: nowy"))
    rule_sentences(app)
    devices.write_text("urzadzenia: [", encoding="utf-8")
    rule_sentences(app)
    return write_dad_quantity_rules(
        app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: nowy").replace("wartosc: 1", "wartosc: 2")
    )


def test_regula_pasujaca_do_ostatniej_dobrej_listy_urzadzen_taty_przy_uszkodzonej_liscie_dziala_od_razu(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    _rules_changed_under_damaged_dad_list(app)

    response = app.client.get(QUANTITY_RULES_URL).json()

    assert response["rules_problem"] is None
    assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 2 × liczbę „nowy” w Z."


def test_narzedzia_licza_regula_pasujaca_do_ostatniej_dobrej_listy_urzadzen_taty_przy_uszkodzonej_liscie(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    rules = _rules_changed_under_damaged_dad_list(app)

    tools_see = read_snapshot(app.tool.config).quantity_rules

    assert tools_see.rules == RULES.parse(rules.read_bytes())
    assert "nowy" in [component.id for component in tools_see.devices.components]


@NO_ACCESS_ON_WINDOWS
def test_reguly_ze_skladnikiem_listy_ktorej_nie_da_sie_przeczytac_sa_zle_a_procesy_licza_regulami_z_wydania(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    devices = write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + NEW_COMPONENT)
    write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: nowy"))
    rule_sentences(app)

    with without_access(devices):
        response = app.client.get(QUANTITY_RULES_URL).json()

    assert (response["rules_problem"]["message"], response["devices_problem"]["message"]) == (
        f"Plik {RULES_FILE} w folderze config: Składnika „nowy” nie ma na Liście Urządzeń.",
        f"Pliku {DEVICES_FILE} w folderze config nie da się teraz przeczytać. Do tego czasu Centrum bierze jego treść z Wydania.",
    )
    assert [device["id"] for device in response["devices"]] == [component.id for component in DEFAULT_QUANTITY_RULES.devices.components]


def test_regula_ze_skladnikiem_spoza_listy_jest_zla_a_po_dopisaniu_skladnika_dziala_z_wierszem_historii(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    rule_sentences(app)
    write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: nowy"))

    refused = app.client.get(QUANTITY_RULES_URL).json()["rules_problem"]
    write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + NEW_COMPONENT)

    assert refused == {
        "field": None,
        "message": f"Plik {RULES_FILE} w folderze config: Składnika „nowy” nie ma na Liście Urządzeń.",
    }
    assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nowy” w Z."
    assert [(row["file"], row["refused"], [change["key"] for change in row["changes"]]) for row in history_rows(app)] == [
        (DEVICES_FILE, False, ["urzadzenia.nowy"]),
        (RULES_FILE, False, ["reguly.nokia"]),
        (RULES_FILE, True, []),
    ]


def test_cofniecie_po_ktorym_regula_ma_skladnik_spoza_listy_urzadzen_jest_odmowa_i_nic_sie_nie_zapisuje(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    rule_sentences(app)
    devices = write_dad_quantity_rules(app.tool, DEVICES_FILE, MANUAL_INSTALLATION, MANUAL_INSTALLATION + NEW_COMPONENT)
    rule_sentences(app)
    rules = write_dad_quantity_rules(app.tool, RULES_FILE, NOKIA_Z, NOKIA_Z.replace("skladnik: nokia", "skladnik: nowy"))
    rule_sentences(app)
    rows = history_rows(app)
    files = (devices.read_bytes(), rules.read_bytes())
    [devices_row] = [row for row in rows if row["file"] == DEVICES_FILE]

    undone = app.client.post(f"/api/settings/history/{devices_row['id']}/undo")
    removed = app.client.delete(f"{DEVICES_URL}/nowy")

    # „Cofnij” dodania składnika to jego usunięcie: odmowa mówi o tej zmianie tak jak formularz, nie o pliku, który jest dobry.
    refused = {
        "message": "Składnika „nowy” potrzebuje reguła: Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nowy” w Z. "
        "Najpierw zmień albo usuń tę regułę w sekcji Reguły ilości."
    }
    assert [(undone.status_code, undone.json()), (removed.status_code, removed.json())] == [(422, refused)] * 2
    assert (devices.read_bytes(), rules.read_bytes(), history_rows(app)) == (*files, rows)
    assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nowy” w Z."


def test_zly_plik_regul_ilosci_to_zle_ustawienie_a_procesy_licza_ostatnimi_dobrymi(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    good = write_dad_quantity_rules(
        app.tool, RULES_FILE, "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia}", "{kolumna: Z, wartosc: 2, razy: liczba, skladnik: nokia}"
    )
    rule_sentences(app)
    good.write_text(good.read_text(encoding="utf-8").replace("wartosc: 2", "wartosc: 0"), encoding="utf-8")

    response = app.client.get(QUANTITY_RULES_URL).json()

    assert response["rules_problem"] == {
        "field": None,
        "message": f"Plik {RULES_FILE} w folderze config: Wartość musi być liczbą całkowitą od 1 do 999.",
    }
    assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 2 × liczbę „nokia” w Z."
    assert [(row["source"], row["refused"]) for row in history_rows(app)] == [("outside", True)]


def test_regula_ilosci_zmieniona_poza_centrum_dziala_od_razu_ma_wiersz_historii_i_da_sie_ja_cofnac(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    rule_sentences(app)
    write_dad_quantity_rules(
        app.tool, RULES_FILE, "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia}", "{kolumna: Z, wartosc: 2, razy: liczba, skladnik: nokia}"
    )

    changed = rule_sentences(app)["nokia"]
    [row] = history_rows(app)
    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert changed == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 2 × liczbę „nokia” w Z."
    assert (row["source"], row["file"], row["section"], [change["key"] for change in row["changes"]]) == (
        "outside",
        RULES_FILE,
        "reguly",
        ["reguly.nokia"],
    )
    assert undone.status_code == 200, undone.text
    assert rule_sentences(app)["nokia"] == "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nokia” w Z."
    assert read_snapshot(app.tool.config).quantity_rules.rules == DEFAULT_QUANTITY_RULES.rules


def test_regula_ilosci_usunieta_poza_centrum_po_cofnieciu_wraca_na_koniec_listy(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    rule_sentences(app)
    contract_rule = "  - {id: t-umowa-u, zakres: kazde, jesli: [{rodzaj: umowa, slowo: u}], to: {rodzaj: wpisz, wpisy: [{kolumna: T, wartosc: 1, razy: raz}]}}\n"
    write_dad_quantity_rules(app.tool, RULES_FILE, contract_rule, "")
    rule_sentences(app)
    [row] = history_rows(app)

    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert undone.status_code == 200, undone.text
    others = [rule.id for rule in DEFAULT_QUANTITY_RULES.rules if rule.id != "t-umowa-u"]
    assert list(rule_sentences(app)) == [*others, "t-umowa-u"]


# Reguła z edytora: wpisz 2 w AA (pozostała kolumna N:AP), gdy URZĄDZENIA zawierają „gniazdo” i CZYNNOŚCI „montaż”.
EDITOR_RULE: dict[str, Any] = {
    "scope": "known",
    "conditions": [
        {"kind": "component", "component": "gniazdo", "negated": False},
        {"kind": "activities", "text": "montaż", "negated": False},
    ],
    "action": {"kind": "fill", "writes": [{"column": "AA", "value": 2, "multiplier": "once", "component": None}]},
}


def test_regula_dodana_w_edytorze_ma_zdanie_wiersz_historii_ze_zdaniem_a_cofniecie_przywraca_poprzednie_reguly(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)

    saved = app.client.post(QUANTITY_RULES_URL, json=EDITOR_RULE)
    [row] = history_rows(app)
    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert saved.status_code == 200, saved.text
    sentence = "Jeśli URZĄDZENIA zawierają „gniazdo” i CZYNNOŚCI zawierają „montaż”, to wpisz 2 w AA."
    added = saved.json()["quantity_rules"]["rules"][-1]
    assert (added["id"], added["rule"], saved.json()["change"]) == ("regula-1", EDITOR_RULE, row["id"])
    assert (row["source"], row["file"], row["changes"][0]["key"]) == ("tata", RULES_FILE, "reguly.regula-1")
    assert [(rule["key"], rule["before"], _text(rule["after"])) for rule in row["rules"]] == [
        ("reguly.regula-1", None, sentence)
    ]
    assert undone.status_code == 200, undone.text
    assert "regula-1" not in rule_sentences(app)
    assert read_snapshot(app.tool.config).quantity_rules.rules == DEFAULT_QUANTITY_RULES.rules


def _text(parts: list[dict[str, Any]] | None) -> str | None:
    if parts is None:
        return None
    return "".join(part["text"] if part["kind"] == "text" else part["letter"] for part in parts)


def test_zmiana_reguly_w_edytorze_zostaje_na_jej_miejscu_a_historia_mowi_zdaniem_przed_i_po(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    nokia = next(rule for rule in app.client.get(QUANTITY_RULES_URL).json()["rules"] if rule["id"] == "nokia")
    changed = json.loads(json.dumps(nokia["rule"]))
    changed["action"]["writes"][0]["value"] = 2

    saved = app.client.put(f"{QUANTITY_RULES_URL}/nokia", json=changed)

    assert saved.status_code == 200, saved.text
    assert list(rule_sentences(app)) == [rule.id for rule in DEFAULT_QUANTITY_RULES.rules]
    [row] = history_rows(app)
    assert [(rule["key"], _text(rule["before"]), _text(rule["after"])) for rule in row["rules"]] == [
        (
            "reguly.nokia",
            "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nokia” w Z.",
            "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 2 × liczbę „nokia” w Z.",
        )
    ]


def test_regula_usunieta_w_edytorze_znika_a_historia_ma_jej_zdanie_przed(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    removed = app.client.delete(f"{QUANTITY_RULES_URL}/t-umowa-u")

    assert removed.status_code == 200, removed.text
    assert "t-umowa-u" not in rule_sentences(app)
    [row] = history_rows(app)
    assert [(_text(rule["before"]), rule["after"]) for rule in row["rules"]] == [
        ("Jeśli UMOWA zaczyna się od słowa „u”, to wpisz 1 w T.", None)
    ]


def _editor_rule(column: str, value: int) -> dict[str, Any]:
    """Reguła z edytora: przy „montaż” w CZYNNOŚCIACH wpisz ``value`` w ``column``."""

    return {
        "scope": "every",
        "conditions": [{"kind": "activities", "text": "montaż", "negated": False}],
        "action": {"kind": "fill", "writes": [{"column": column, "value": value, "multiplier": "once", "component": None}]},
    }


# Reguły taty z edytora po nazwie w sekwencji: każda ma inne zdanie.
EDITED = {"A": _editor_rule("AA", 2), "A2": _editor_rule("AA", 4), "B": _editor_rule("AC", 5), "C": _editor_rule("AB", 1)}


def _edits(app: Centrum, sequence: tuple[tuple[str, ...], ...]) -> dict[str, str]:
    """Zapisy taty w edytorze po kolei: ``("dodaj", A)``, ``("zmien", A, A2)``, ``("usun", A)``; daje id reguły po nazwie."""

    ids: dict[str, str] = {}
    for step in sequence:
        match step:
            case ("dodaj", name):
                response = app.client.post(QUANTITY_RULES_URL, json=EDITED[name])
                ids[name] = response.json()["quantity_rules"]["rules"][-1]["id"]
            case ("zmien", name, other):
                response = app.client.put(f"{QUANTITY_RULES_URL}/{ids[name]}", json=EDITED[other])
                ids[other] = ids[name]
            case ("usun", name):
                response = app.client.delete(f"{QUANTITY_RULES_URL}/{ids[name]}")
            case _:
                raise AssertionError(step)
        assert response.status_code == 200, response.text
    return ids


def test_cofniecie_usuniecia_reguly_przywraca_ja_obok_reguly_dodanej_po_niej_a_cofniecie_dodania_jej_nie_rusza(
    tmp_path: Path,
) -> None:
    """Tata dodaje regułę A, usuwa ją i dodaje regułę B: B ma inne id niż usunięta A, więc „Cofnij” usunięcia A
    przywraca A obok B, a „Cofnij” dodania A zdejmuje tylko A."""

    app = centrum(tmp_path)
    ids = _edits(app, (("dodaj", "A"), ("usun", "A"), ("dodaj", "B")))
    added_a, removed_a, _ = reversed(history_rows(app))
    a = "Jeśli CZYNNOŚCI zawierają „montaż”, to wpisz 2 w AA."
    b = "Jeśli CZYNNOŚCI zawierają „montaż”, to wpisz 5 w AC."

    restored = app.client.post(f"/api/settings/history/{removed_a['id']}/undo")
    after_restore = rule_sentences(app)
    taken_back = app.client.post(f"/api/settings/history/{added_a['id']}/undo")

    assert ids["A"] != ids["B"]
    assert (restored.status_code, taken_back.status_code) == (200, 200), (restored.text, taken_back.text)
    assert (after_restore.get(ids["A"]), after_restore.get(ids["B"])) == (a, b)
    assert {rule: sentence for rule, sentence in rule_sentences(app).items() if rule.startswith("regula-")} == {ids["B"]: b}


def test_nowa_regula_przy_historii_bez_odczytu_to_odmowa_bez_zapisu_a_cofniecie_usuniecia_nie_rusza_reguly_dodanej_potem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tata dodaje regułę A i ją usuwa, a potem dodaje B, gdy system nie daje czytać Historii Ustawień (plik trzyma
    OneDrive), choć dopisanie wiersza działa. Bez kluczy Historii B mogłaby dostać id usuniętej A i zniknąć po „Cofnij”
    usunięcia A, więc zapis jest odmową ze zdaniem i nic się nie zapisuje. B dodana, gdy Historia znów się czyta, ma
    własne id, a „Cofnij” usunięcia A przywraca A obok niej."""

    app = centrum(tmp_path)
    ids = _edits(app, (("dodaj", "A"), ("usun", "A")))
    rules_before, rows_before = (app.tool.config / RULES_FILE).read_bytes(), history_rows(app)

    with unreadable_history(monkeypatch):
        refused = app.client.post(QUANTITY_RULES_URL, json=EDITED["B"])
    rules_after, rows_after = (app.tool.config / RULES_FILE).read_bytes(), history_rows(app)
    b = _edits(app, (("dodaj", "B"),))["B"]
    restored = app.client.post(f"/api/settings/history/{rows_before[0]['id']}/undo")

    assert (refused.status_code, refused.json()) == (500, {"message": SETTINGS_NOT_SAVED})
    assert (rules_after, rows_after) == (rules_before, rows_before)
    assert b != ids["A"]
    assert restored.status_code == 200, restored.text
    assert {rule: sentence for rule, sentence in rule_sentences(app).items() if rule.startswith("regula-")} == {
        ids["A"]: _sentence(EDITED["A"]),
        b: _sentence(EDITED["B"]),
    }


# Krok taty w oknie Ustawień: zapis w edytorze (także nowej reguły, gdy Historii nie da się przeczytać) albo „Cofnij”
# wiersza Historii; liczba wybiera regułę albo wiersz.
_STEP = st.one_of(
    st.tuples(st.just("dodaj"), st.sampled_from(sorted(EDITED))),
    st.tuples(st.just("zmien"), st.integers(0, 9), st.sampled_from(sorted(EDITED))),
    st.tuples(st.just("usun"), st.integers(0, 9)),
    st.tuples(st.just("cofnij"), st.integers(0, 9)),
    st.tuples(st.just("dodaj bez historii"), st.sampled_from(sorted(EDITED))),
)


def test_po_dowolnych_zapisach_edytora_i_cofnieciach_kazda_regula_ma_wlasne_id_a_cofniecie_zmienia_tylko_regule_wiersza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Po dowolnych zapisach taty w edytorze i cofnięciach z Historii: nowa reguła dostaje id, którego nie miała żadna
    reguła przed nią, a „Cofnij” wiersza zmienia tylko regułę tego wiersza (usuwa ją albo przywraca jej zdanie
    „przed”), każda inna reguła zostaje, jak była; cofnięcie, którego nie da się wykonać, nie zmienia żadnej reguły i
    mówi zdaniem dlaczego. Nowa reguła, gdy Historii nie da się przeczytać, to odmowa ze zdaniem bez zmiany reguł."""

    examples = itertools.count()

    @settings(derandomize=True, database=None, deadline=None, max_examples=25)
    @given(st.lists(_STEP, min_size=3, max_size=8))
    def steps_hold(steps: list[tuple[Any, ...]]) -> None:
        app = centrum(tmp_path / str(next(examples)))
        expected: dict[str, str] = {}
        given_ids: set[str] = set()
        for step in steps:
            ids = list(expected)
            match step:
                case ("dodaj", name):
                    response = app.client.post(QUANTITY_RULES_URL, json=EDITED[name])
                    added = response.json()["quantity_rules"]["rules"][-1]["id"]
                    assert added not in given_ids, f"id {added} usuniętej reguły wróciło do nowej"
                    given_ids.add(added)
                    expected[added] = _sentence(EDITED[name])
                case ("dodaj bez historii", name):
                    with unreadable_history(monkeypatch):
                        response = app.client.post(QUANTITY_RULES_URL, json=EDITED[name])
                    assert (response.status_code, response.json()) == (500, {"message": SETTINGS_NOT_SAVED}), steps
                case ("zmien", index, name) if ids:
                    rule_id = ids[index % len(ids)]
                    response = app.client.put(f"{QUANTITY_RULES_URL}/{rule_id}", json=EDITED[name])
                    expected[rule_id] = _sentence(EDITED[name])
                case ("usun", index) if ids:
                    rule_id = ids[index % len(ids)]
                    response = app.client.delete(f"{QUANTITY_RULES_URL}/{rule_id}")
                    del expected[rule_id]
                case ("cofnij", index):
                    rows = [row for row in history_rows(app) if row["rules"]]
                    if not rows:
                        continue
                    [rule] = rows[index % len(rows)]["rules"]
                    response = app.client.post(f"/api/settings/history/{rows[index % len(rows)]['id']}/undo")
                    if response.status_code == 200:
                        rule_id = rule["key"].removeprefix("reguly.")
                        expected.pop(rule_id, None)
                        if rule["before"] is not None:
                            expected[rule_id] = str(_text(rule["before"]))
                    else:
                        assert response.json()["message"], response.text
                case _:
                    continue
            assert response.status_code in (200, 409, 422) or step[0] == "dodaj bez historii", response.text
            shown = {rule_id: sentence for rule_id, sentence in rule_sentences(app).items() if rule_id.startswith("regula-")}
            assert shown == expected, steps

    steps_hold()


def _sentence(rule: dict[str, Any]) -> str:
    [write] = rule["action"]["writes"]
    return f"Jeśli CZYNNOŚCI zawierają „montaż”, to wpisz {write['value']} w {write['column']}."


@pytest.mark.parametrize(
    ("rule", "field", "message"),
    [
        ({**EDITOR_RULE, "action": None}, "to", settings_messages.rule_without_action()),
        (
            {**EDITOR_RULE, "action": {"kind": "fill", "writes": [{"column": "AT", "value": 1, "multiplier": "once", "component": None}]}},
            "to.wpisy[0].kolumna",
            "Kolumna „AT” nie jest kolumną Ilości usług N:AP.",
        ),
        (
            {**EDITOR_RULE, "action": {"kind": "fill", "writes": [{"column": "S", "value": 1, "multiplier": "once", "component": None}]}},
            "to.wpisy[0].kolumna",
            "Kolumnę S liczy narzędzie samo: P i Q z urządzeń TV, S z liczby urządzeń.",
        ),
        (
            {**EDITOR_RULE, "action": {"kind": "leave_empty", "columns": ["AU"]}},
            "to.kolumny",
            "Kolumna „AU” nie jest kolumną Ilości usług N:AP.",
        ),
        (
            {**EDITOR_RULE, "conditions": [{"kind": "activities", "text": "Akt  Int", "negated": False}]},
            "jesli[0].tekst",
            "Tekst wpisz małymi literami, z pojedynczymi spacjami.",
        ),
        (
            {**EDITOR_RULE, "conditions": [{"kind": "date", "days": [0], "since": "17", "negated": False}]},
            "jesli[0].od",
            settings_messages.rule_hour(),
        ),
        (
            {**EDITOR_RULE, "conditions": [{"kind": "component", "component": "nie-ma-takiego", "negated": False}]},
            "jesli[0].skladnik",
            # Składnika nie było nigdy na liście ani w Historii, więc nazwy nie ma: zostaje identyfikator.
            "Reguła potrzebuje składnika „nie-ma-takiego”, którego nie ma na Liście Urządzeń: Jeśli URZĄDZENIA zawierają "
            "„nie-ma-takiego”, to wpisz 2 w AA. Najpierw dodaj ten składnik w sekcji Urządzenia.",
        ),
    ],
    ids=["bez-dzialania", "kolumna-spoza-n-ap", "kolumna-wbudowana", "pusta-spoza-n-ap", "tekst-nie-malymi", "godzina", "skladnik"],
)
def test_zla_regula_z_edytora_sie_nie_zapisuje_a_odmowa_ma_pole_formularza_i_zdanie(
    tmp_path: Path, rule: dict[str, Any], field: str, message: str
) -> None:
    app = centrum(tmp_path)

    refused = app.client.post(QUANTITY_RULES_URL, json=rule)
    previewed = app.client.post(f"{QUANTITY_RULES_URL}/preview", json={"kind": "add", "rule": rule})

    assert (refused.status_code, refused.json()) == (422, {"message": message, "field": field})
    assert (previewed.status_code, previewed.json()) == (422, {"message": message, "field": field})
    assert not (app.tool.config / RULES_FILE).exists()
    assert history_rows(app) == []


@pytest.mark.skipif(sys.platform == "win32", reason="Plik bez prawa odczytu daje się tak zrobić tylko poza Windows.")
def test_podglad_nowej_reguly_dziala_takze_gdy_historii_ustawien_nie_da_sie_przeczytac_a_zapis_sie_nie_udaje(
    tmp_path: Path,
) -> None:
    """Historia, której nie da się przeczytać, nie daje id do pominięcia: podgląd i tak pokazuje regułę, a zapis
    odmawia, więc inne id w podglądzie niż przy zapisie nigdy nie trafia do pliku."""

    app = centrum(tmp_path)
    assert app.client.put("/api/settings/theme", json={"theme": "light"}).status_code == 200
    history = app.tool.config / HISTORY_FILE
    assert history.exists()
    history.chmod(0)
    try:
        previewed = app.client.post(f"{QUANTITY_RULES_URL}/preview", json={"kind": "add", "rule": EDITOR_RULE})
        saved = app.client.post(QUANTITY_RULES_URL, json=EDITOR_RULE)
    finally:
        history.chmod(0o644)

    assert previewed.status_code == 200, previewed.json()
    assert saved.status_code == 500
    assert not (app.tool.config / RULES_FILE).exists()


def test_zmiana_albo_usuniecie_reguly_ktorej_juz_nie_ma_to_odmowa_bez_zapisu(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    changed = app.client.put(f"{QUANTITY_RULES_URL}/nie-ma-takiej", json=EDITOR_RULE)
    removed = app.client.delete(f"{QUANTITY_RULES_URL}/nie-ma-takiej")

    unknown = {"message": "Tej reguły już nie ma w Regułach ilości. Odśwież okno Ustawień."}
    assert [(changed.status_code, changed.json()), (removed.status_code, removed.json())] == [(404, unknown)] * 2
    assert history_rows(app) == []


def test_kolumny_edytora_to_n_ap_z_nazwa_cennika_a_p_q_i_s_regula_tylko_zostawia_puste(tmp_path: Path) -> None:
    columns = centrum(tmp_path).client.get(QUANTITY_RULES_URL).json()["columns"]

    n_to_ap = range(column_index_from_string("N"), column_index_from_string("AP") + 1)
    assert [column["letter"] for column in columns] == [get_column_letter(index) for index in n_to_ap]
    assert [column["letter"] for column in columns if not column["writable"]] == ["P", "Q", "S"]


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
            "periods_all_years": False,
            "theme": "dark",
            "folders_problem": {"field": "folder_okresow", "message": PERIODS_PATH},
            "workers": NO_WORKERS,
            **NO_INBOX,
            "autostart": AUTOSTART_SHOWN_OFF,
            "reminders": NO_REMINDERS,
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

    assert (changed.status_code, changed.json()["settings"]["periods_directory"]["path"], changed.json()["settings"]["folders_problem"]) == (
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

    assert (changed.status_code, changed.json()["settings"]["theme"]) == (200, "light")
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


# --- Lista Wykonawców (#1473, ADR 0032): przeniesienie starych plików i reguły pliku ------------------------------------

JAN = "jan.testowy@przyklad.invalid"
ANNA = "anna.przyklad@przyklad.invalid"
OBCY = "obcy@przyklad.invalid"
OLD_MAPPING = "schema_version: 1\nworkers:\n  Jan.Testowy: Jan Testowy\n  anna.przyklad: Anna Przykład\n  ewa.bez: Ewa Bez\n"
OLD_ADDRESSES = (
    f"schema_version: 1\nwykonawcy:\n  jan.testowy: [{JAN}]\n  anna.przyklad: [{ANNA}]\n  obcy.login: [{OBCY}]\n"
)


def listed(logins: list[str], name: str, addresses: list[str]) -> dict[str, object]:
    """Wykonawca w sekcji Wykonawcy: aktywny, z przypomnieniami, tak jak przenosi go przeniesienie."""

    return {"logins": logins, "name": name, "addresses": addresses, "active": True, "reminders": True}


def old_files(tool: ToolDirectory, mapping: str | bytes | None, addresses: str | bytes | None) -> dict[str, bytes]:
    """Stare pliki Wykonawców w ``config`` taty sprzed Wydania z Listą Wykonawców; ``None``: pliku nie ma."""

    tool.config.mkdir(parents=True, exist_ok=True)
    written: dict[str, bytes] = {}
    for name, content in ((OLD_MAPPING_FILE, mapping), (OLD_ADDRESSES_FILE, addresses)):
        if content is not None:
            data = content.encode("utf-8") if isinstance(content, str) else content
            (tool.config / name).write_bytes(data)
            written[name] = data
    return written


def migrated(tool: ToolDirectory) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Sekcja Wykonawcy i Historia Ustawień po pierwszym starcie Wydania z Listą Wykonawców."""

    client = started(tool, RELEASE_CHANGES)
    workers = client.get("/api/settings").json()["workers"]
    rows = client.get("/api/settings/history").json()["rows"]
    client.stop()
    return workers, rows


def test_przeniesienie_laczy_konfiguracje_i_adresy_w_liste_wykonawcow_a_adres_spoza_konfiguracji_zostaje_dla_taty(
    tmp_path: Path,
) -> None:
    """DESIGN §4.2: login z adresami i login bez adresów przechodzą jako aktywni Wykonawcy z przypomnieniami, adres przy
    loginie spoza Konfiguracji wykonawców tata widzi do rozstrzygnięcia, a stare pliki zostają bajt w bajt."""

    tool = ToolDirectory(tmp_path)
    old = old_files(tool, OLD_MAPPING, OLD_ADDRESSES)

    workers, rows = migrated(tool)

    assert workers == {
        "state": "good",
        "workers": [
            listed(["jan.testowy"], "Jan Testowy", [JAN]),
            listed(["anna.przyklad"], "Anna Przykład", [ANNA]),
            listed(["ewa.bez"], "Ewa Bez", []),
        ],
        "unresolved": [{"reason": "login_bez_wykonawcy", "login": "obcy.login", "addresses": [OBCY]}],
        "problem": None,
    }
    [row] = rows
    assert (row["source"], row["release"]["change"], row["file"], row["section"], row["undoable"], row["refused"]) == (
        "release",
        "2026-11-lista-wykonawcow",
        WORKERS_FILE,
        "wykonawcy",
        False,
        False,
    )
    assert {name: (tool.config / name).read_bytes() for name in old} == old


@pytest.mark.parametrize(
    ("addresses", "reason"),
    [
        pytest.param("wykonawcy: [", "plik nie jest poprawnym YAML", id="zly-yaml"),
        pytest.param(f"schema_version: 1\nwykonawcy:\n  jan.testowy: [{JAN}, {JAN}]\n", "ten sam adres stoi dwa razy", id="adres-dwa-razy"),
        pytest.param(b"\xff\xfe nie UTF-8", "plik nie jest zapisany w UTF-8", id="spoza-utf-8"),
    ],
)
def test_zly_plik_adresow_przenosi_wykonawcow_bez_adresow_i_mowi_tacie_dlaczego(
    tmp_path: Path, addresses: str | bytes, reason: str
) -> None:
    tool = ToolDirectory(tmp_path)
    old_files(tool, OLD_MAPPING, addresses)

    workers, _ = migrated(tool)

    assert [worker["addresses"] for worker in workers["workers"]] == [[], [], []]
    assert workers["unresolved"] == [
        {"reason": "adresy_nieprzeniesione", "message": settings_messages.addresses_not_moved(OLD_ADDRESSES_FILE, reason)}
    ]


@pytest.mark.parametrize(
    ("mapping", "reason"),
    [
        pytest.param("workers: [", "plik nie jest poprawnym YAML", id="zly-yaml"),
        pytest.param("schema_version: 2\nworkers:\n  a: A\n", "plik nie ma schema_version: 1", id="inna-wersja"),
        pytest.param("schema_version: 1\nworkers:\n  a: A\n  A: B\n", "identyfikator Wykonawcy stoi dwa razy", id="login-dwa-razy"),
    ],
)
def test_zly_stary_plik_wykonawcow_nie_daje_listy_a_historia_ma_powod_odrzucenia(
    tmp_path: Path, mapping: str, reason: str
) -> None:
    """Odrzucone przeniesienie to zły stan Listy Wykonawców bez ostatniej dobrej, także przy następnym starcie, nigdy
    pusta dobra lista: tata nie może pomyśleć, że Wykonawców nie ma (przegląd #1529 r1, D1)."""

    tool = ToolDirectory(tmp_path)
    old_files(tool, mapping, OLD_ADDRESSES)

    workers, rows = migrated(tool)
    after_restart, _ = migrated(tool)

    assert not tool.worker_list.exists()
    assert workers == after_restart == {
        "state": "bad",
        "workers": [],
        "unresolved": [],
        "problem": {"field": None, "message": settings_messages.worker_list_not_created()},
    }
    assert [(row["source"], row["refused"], row["reason"]) for row in rows] == [
        ("release", True, settings_messages.workers_not_moved(OLD_MAPPING_FILE, reason))
    ]


def test_konfiguracja_wykonawcow_ktorej_reguly_nie_przechodza_na_liscie_jest_odrzucona_z_powodem(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    old_files(tool, "schema_version: 1\nworkers:\n  a: Ten Sam\n  b: ten sam\n", None)

    _, rows = migrated(tool)

    assert not tool.worker_list.exists()
    assert [(row["refused"], row["reason"]) for row in rows] == [
        (True, settings_messages.workers_not_moved(OLD_MAPPING_FILE, "Wykonawcy z adresami łamią reguły Listy Wykonawców"))
    ]


def test_same_adresy_bez_konfiguracji_wykonawcow_czekaja_na_tate_zamiast_zniknac(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    old_files(tool, None, OLD_ADDRESSES)

    workers, _ = migrated(tool)

    assert workers["workers"] == []
    assert [item["login"] for item in workers["unresolved"]] == ["jan.testowy", "anna.przyklad", "obcy.login"]


@pytest.mark.parametrize("existing", [False, True], ids=["bez-starych-plikow", "lista-juz-jest"])
def test_przeniesienie_bez_starych_plikow_albo_po_liscie_niczego_nie_pisze(tmp_path: Path, existing: bool) -> None:
    tool = ToolDirectory(tmp_path)
    if existing:
        old_files(tool, OLD_MAPPING, OLD_ADDRESSES)
        write_worker_list(tool.worker_list, worker_list({"kamil.syntetyczny": "Kamil Syntetyczny"}))
    before = tool.worker_list.read_bytes() if existing else None

    workers, rows = migrated(tool)

    assert rows == []
    assert (tool.worker_list.read_bytes() if tool.worker_list.exists() else None) == before
    assert [worker["name"] for worker in workers["workers"]] == (["Kamil Syntetyczny"] if existing else [])
    assert (workers["state"], workers["problem"]) == ("good", None), "zły stan bez pliku tylko po odrzuconym przeniesieniu"


WAITING_SENTENCE = settings_messages.worker_list_waiting()
WAITING = {"field": None, "message": WAITING_SENTENCE}


def unusable(sentence: str) -> str:
    """Odmowa startu procesu bez użytecznej Listy Wykonawców ze zdaniem złego ustawienia ``sentence``."""

    return f"Lista Wykonawców ma złe ustawienie: {sentence} Szczegóły są w Ustawieniach, w sekcji Wykonawcy."


@NO_ACCESS_ON_WINDOWS
@pytest.mark.parametrize("locked", [OLD_MAPPING_FILE, OLD_ADDRESSES_FILE])
def test_stary_plik_wykonawcow_bez_prawa_odczytu_czeka_na_nastepny_start_zamiast_zostawic_tate_bez_wykonawcow(
    tmp_path: Path, locked: str
) -> None:
    """DESIGN §4.2: stary plik, którego system nie daje teraz czytać, nie jest ani zły, ani brakujący. Przeniesienie
    czeka bez Listy Wykonawców i bez wiersza Historii, a następny start z czytelnym plikiem przenosi Wykonawców z
    adresami (odmowa zostałaby zapamiętana na zawsze, a brak pliku dałby listę bez Wykonawców albo bez adresów)."""

    tool = ToolDirectory(tmp_path)
    old_files(tool, OLD_MAPPING, OLD_ADDRESSES)
    with without_access(tool.config / locked):
        locked_workers, locked_rows = migrated(tool)
        listed_while_locked = tool.worker_list.exists()

    workers, rows = migrated(tool)

    assert (listed_while_locked, locked_rows) == (False, [])
    assert locked_workers == {"state": "bad", "workers": [], "unresolved": [], "problem": WAITING}
    assert workers["workers"] == [
        listed(["jan.testowy"], "Jan Testowy", [JAN]),
        listed(["anna.przyklad"], "Anna Przykład", [ANNA]),
        listed(["ewa.bez"], "Ewa Bez", []),
    ]
    assert [(row["source"], row["refused"]) for row in rows] == [("release", False)]


@NO_ACCESS_ON_WINDOWS
def test_proces_nie_startuje_na_pustej_liscie_gdy_przeniesienie_czeka_na_stary_plik_wykonawcow(tmp_path: Path) -> None:
    """Przegląd #1569 r1, D2: gdy przeniesienie czeka na stary plik, którego system nie daje czytać, Przebieg
    rozliczeń nie startuje na pustej liście, tak jak po odrzuconym przeniesieniu."""

    tool = settling_centrum(tmp_path).tool
    tool.worker_list.unlink()
    old_files(tool, OLD_MAPPING, OLD_ADDRESSES)
    with without_access(tool.config / OLD_MAPPING_FILE):
        client = started(tool, RELEASE_CHANGES)
        refused = client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "DRY-RUN"})
        client.stop()

    assert (refused.status_code, refused.json()) == (409, {"message": unusable(WAITING_SENTENCE)})


@contextmanager
def held_release_changes(tool: ToolDirectory, monkeypatch: pytest.MonkeyPatch, fault: str) -> Iterator[None]:
    """Do końca bloku start Centrum wstrzymuje zmiany z Wydania: system nie daje czytać Historii Ustawień
    (``bez-historii``) albo pamięć zmian z Wydań ma uszkodzoną treść (``bez-pamieci``)."""

    if fault == "bez-pamieci":
        memory = tool.config / MEMORY_DIRECTORY / APPLIED_FILE
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text('{"schema_version": 1, "zmiany": {"2026-11-lista-wyk', encoding="utf-8")
        yield
        return
    with unreadable_history(monkeypatch):
        yield


@pytest.mark.parametrize(
    ("mapping", "addresses"),
    [(OLD_MAPPING, OLD_ADDRESSES), (OLD_MAPPING, None), (None, OLD_ADDRESSES)],
    ids=["oba-stare-pliki", "tylko-wykonawcy", "tylko-adresy"],
)
@pytest.mark.parametrize("fault", ["bez-historii", "bez-pamieci"])
def test_przeniesienie_wstrzymane_przy_starcie_ze_starym_plikiem_wykonawcow_czeka_zamiast_pustej_dobrej_listy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, mapping: str | None, addresses: str | None
) -> None:
    """Przegląd #1569 r2, D2: start, który przy pierwszym starcie Wydania z Listą Wykonawców wstrzymuje przeniesienie,
    bo nie da się przeczytać Historii Ustawień albo pamięci zmian z Wydań, a któryś stary plik Wykonawców leży w
    ``config``, daje sekcji Wykonawcy to samo złe ustawienie co stary plik bez prawa odczytu, a Przebieg rozliczeń nie
    startuje na pustej liście."""

    tool = settling_centrum(tmp_path).tool
    tool.worker_list.unlink()
    old_files(tool, mapping, addresses)
    with held_release_changes(tool, monkeypatch, fault):
        client = started(tool, RELEASE_CHANGES)
        workers = client.get("/api/settings").json()["workers"]
        refused = client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "DRY-RUN"})
        client.stop()

    assert (tool.worker_list.exists(), workers) == (False, {"state": "bad", "workers": [], "unresolved": [], "problem": WAITING})
    assert (refused.status_code, refused.json()) == (409, {"message": unusable(WAITING_SENTENCE)})


@pytest.mark.parametrize("fault", ["bez-historii", "bez-pamieci"])
def test_przeniesienie_wstrzymane_przy_starcie_bez_starych_plikow_wykonawcow_to_pusta_dobra_lista(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """Bez starych plików Wykonawców przeniesienie nie ma czego przenieść, więc wstrzymane przy starcie nie jest
    złym ustawieniem: sekcja Wykonawcy ma pustą dobrą listę, jak po przeniesieniu bez starych plików."""

    tool = ToolDirectory(tmp_path)
    tool.config.mkdir(parents=True)
    with held_release_changes(tool, monkeypatch, fault):
        client = started(tool, RELEASE_CHANGES)
        workers = client.get("/api/settings").json()["workers"]
        client.stop()

    assert (workers["state"], workers["workers"], workers["problem"]) == ("good", [], None)


WORKER ="  - {nazwa: Jan Testowy, loginy: [jan.testowy], adresy: [" + JAN + "]}\n"


@pytest.mark.parametrize(
    ("entries", "field", "sentence"),
    [
        pytest.param("  - {nazwa: 'Jan/Testowy', loginy: [jan]}\n", "wykonawcy[0].nazwa", settings_messages.worker_name_invalid(), id="nazwa-nie-do-pliku"),
        pytest.param("  - {nazwa: 'Jan Testowy.', loginy: [jan]}\n", "wykonawcy[0].nazwa", settings_messages.worker_name_invalid(), id="kropka-na-koncu"),
        pytest.param(f"  - {{nazwa: {'J' * 300}, loginy: [jan]}}\n", "wykonawcy[0].nazwa", settings_messages.worker_name_too_long(), id="nazwa-za-dluga"),
        pytest.param(WORKER + "  - {nazwa: Jan Drugi, loginy: [Jan.Testowy]}\n", "wykonawcy[1].loginy[0]", settings_messages.worker_login_repeated(), id="powtorzony-login"),
        pytest.param(WORKER + "  - {nazwa: 'jan  testowy', loginy: [jan.drugi]}\n", "wykonawcy[1].nazwa", settings_messages.worker_same_file(), id="dwie-nazwy-jeden-plik"),
        pytest.param(WORKER + "  - {nazwa: Anna, loginy: [anna], adresy: [" + JAN.upper() + "]}\n", "wykonawcy[1].adresy[0]", settings_messages.worker_address_repeated(), id="adres-u-dwoch-wykonawcow"),
        pytest.param("  - {nazwa: Jan, loginy: [jan], adresy: [jan]}\n", "wykonawcy[0].adresy[0]", settings_messages.worker_address_invalid(), id="nie-adres"),
        pytest.param("  - {nazwa: Jan, loginy: [jan], adresy: ['Jan <" + JAN + ">']}\n", "wykonawcy[0].adresy[0]", settings_messages.worker_address_invalid(), id="adres-z-nazwa"),
        pytest.param("  - {nazwa: Jan, loginy: []}\n", "wykonawcy[0].loginy", settings_messages.worker_without_login(), id="bez-loginu"),
        pytest.param("  - {nazwa: '', loginy: [jan]}\n", "wykonawcy[0].nazwa", settings_messages.worker_name_empty(), id="pusta-nazwa"),
    ],
)
def test_lista_wykonawcow_lamiaca_regule_to_zle_ustawienie_z_polem_bez_nazwy_loginu_i_adresu(
    tmp_path: Path, entries: str, field: str, sentence: str
) -> None:
    """Sprawdzenia dzisiejszego czytnika Konfiguracji wykonawców (nazwa jako nazwa pliku, długość, powtórzony login, dwie
    nazwy na jeden plik) i adresów działają na Liście Wykonawców, a nowa reguła odrzuca adres u dwóch Wykonawców."""

    app = centrum(tmp_path)
    app.tool.config.mkdir(parents=True)
    app.tool.worker_list.write_text(f"schema_version: 1\nwykonawcy:\n{entries}", encoding="utf-8")

    workers = app.client.get("/api/settings").json()["workers"]

    assert workers == {"state": "bad", "workers": [], "unresolved": [], "problem": {"field": field, "message": sentence}}


LEAKED_LOGIN, LEAKED_NAME, LEAKED_ADDRESS = "kamil.wyciek", "Kamil Wyciek", "kamil.wyciek@przyklad.invalid"


@pytest.mark.parametrize(
    ("content", "field", "sentence"),
    [
        pytest.param(
            f"wykonawcy:\n  - {LEAKED_LOGIN}: {LEAKED_NAME}\n",
            "wykonawcy[0]",
            settings_messages.worker_unknown_key(WORKERS_FILE, 1, 1),
            id="stary-ksztalt-wpisu",
        ),
        pytest.param(
            f"{LEAKED_LOGIN}: {LEAKED_NAME}\nwykonawcy: []\n",
            None,
            settings_messages.unknown_key(WORKERS_FILE, 2, settings_messages.MAKS_FIXES),
            id="login-na-gorze-pliku",
        ),
        pytest.param(
            f"wykonawcy:\n  - {{nazwa: {LEAKED_NAME}, loginy: [{LEAKED_LOGIN}], {LEAKED_ADDRESS}: tak}}\n",
            "wykonawcy[0]",
            settings_messages.worker_unknown_key(WORKERS_FILE, 1, 3),
            id="adres-w-miejscu-pola",
        ),
        pytest.param(
            f"wykonawcy:\n  - {{nazwa: {LEAKED_NAME}, loginy: {LEAKED_LOGIN}}}\n",
            "wykonawcy[0].loginy",
            settings_messages.bad_field(WORKERS_FILE, FieldPath("wykonawcy", 0, "loginy"), settings_messages.MAKS_FIXES),
            id="login-zamiast-listy",
        ),
        pytest.param(
            f"wykonawcy:\n  - {{nazwa: {LEAKED_NAME}, loginy: [{LEAKED_LOGIN}], aktywny: {LEAKED_NAME}}}\n",
            "wykonawcy[0].aktywny",
            settings_messages.bad_field(WORKERS_FILE, FieldPath("wykonawcy", 0, "aktywny"), settings_messages.MAKS_FIXES),
            id="nazwa-zamiast-tak-nie",
        ),
        pytest.param(
            f"do_rozstrzygniecia:\n  - {{login: {LEAKED_LOGIN}, adresy: [{LEAKED_ADDRESS}], powod: {LEAKED_NAME}}}\n",
            "do_rozstrzygniecia[0]",
            settings_messages.bad_field(WORKERS_FILE, FieldPath("do_rozstrzygniecia", 0), settings_messages.MAKS_FIXES),
            id="zly-wpis-do-rozstrzygniecia",
        ),
        pytest.param(
            f"wykonawcy:\n  - {{nazwa: '{LEAKED_NAME}/', loginy: [{LEAKED_LOGIN}], adresy: [{LEAKED_ADDRESS}]}}\n",
            "wykonawcy[0].nazwa",
            settings_messages.worker_name_invalid(),
            id="nazwa-nie-do-pliku",
        ),
    ],
)
def test_zly_plik_listy_wykonawcow_mowi_wpis_po_numerze_bez_loginu_nazwy_i_adresu_w_logach_i_zgloszeniu(
    tmp_path: Path, content: str, field: str | None, sentence: str
) -> None:
    """Pole problemu składa się tylko ze znanych nazw pól i numerów, więc tekst z pliku (stary kształt wpisu ``login:
    Nazwa``, klucz-adres, wartość nie tego typu) nie trafia do odpowiedzi, Logów Centrum ani Zgłoszenia (przegląd #1529
    r1, W3)."""

    centrum_ = settling_centrum(tmp_path)
    centrum_.client.get("/api/settings")
    centrum_.tool.worker_list.write_text(f"schema_version: 1\n{content}", encoding="utf-8")

    settings = centrum_.client.get("/api/settings")
    run_id = stopped_for_maks(centrum_)
    report = centrum_.client.post(f"/api/runs/{run_id}/diagnosis").json()["report"]["body"]

    assert settings.json()["workers"]["problem"] == {"field": field, "message": sentence}
    seen = {
        "odpowiedź": settings.text,
        "Logi Centrum": centrum_.tool.log_path.read_text(encoding="utf-8"),
        "Zgłoszenie": report,
    }
    assert sentence in report
    leaks = [(where, secret) for where, text in seen.items() for secret in (LEAKED_LOGIN, LEAKED_NAME, LEAKED_ADDRESS) if secret in text]
    assert leaks == []


def test_proces_przy_zlej_liscie_wykonawcow_biegnie_na_ostatniej_dobrej_z_ostrzezeniem_na_karcie(tmp_path: Path) -> None:
    """DESIGN §4.3: karta i Logi Uruchomienia mówią, że proces użył ostatniej dobrej listy, z linkiem do sekcji
    Wykonawcy (przegląd #1529 r1, D2)."""

    centrum_ = settling_centrum(tmp_path)
    centrum_.client.get("/api/settings")
    centrum_.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")

    view = run_to_end(centrum_, dry_run=True)

    warning = Message.of(diagnosis_messages.worker_list_last_good(settings_messages.damaged(WORKERS_FILE, settings_messages.MAKS_FIXES))).model_dump()
    assert (view["result"]["result"], view["result"]["ending"]) == ("OK", "finished")
    assert (view["result"]["warnings"][0], warning["setting"]) == (warning, "wykonawcy")


def test_diagnoza_zatrzymania_opisuje_liste_wykonawcow_ze_startu_uruchomienia_a_nie_pozniejsza(tmp_path: Path) -> None:
    """D9: Diagnoza wyjaśnia to Uruchomienie, więc zła lista ze startu zostaje w Diagnozie po naprawie pliku, a lista
    zepsuta po starcie do niej nie trafia (przegląd #1529 r1, D2)."""

    centrum_ = settling_centrum(tmp_path)
    centrum_.client.get("/api/settings")
    good = centrum_.tool.worker_list.read_bytes()
    centrum_.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")
    bad_at_start = stopped_for_maks(centrum_)
    centrum_.tool.worker_list.write_bytes(good)
    fixed_later = centrum_.client.post(f"/api/runs/{bad_at_start}/diagnosis").json()

    [worker_list] = [check for check in fixed_later["checks"] if check["label"] == "Lista Wykonawców"]
    assert (worker_list["state"], worker_list["detail"]) == (
        "failed",
        diagnosis_messages.worker_list_bad(settings_messages.damaged(WORKERS_FILE, settings_messages.MAKS_FIXES)).what,
    )


def test_proces_bez_dobrej_listy_wykonawcow_nie_startuje_a_odmowa_mowi_co_poprawic(tmp_path: Path) -> None:
    """Zła Lista Wykonawców bez ostatniej dobrej (po usunięciu pliku nie ma już dobrej treści) odmawia startu procesu."""

    centrum_ = settling_centrum(tmp_path)
    centrum_.tool.worker_list.unlink()
    centrum_.client.get("/api/settings")
    centrum_.tool.worker_list.write_text("schema_version: 1\nwykonawcy:\n  - {nazwa: Jan, loginy: []}\n", encoding="utf-8")

    started_run = centrum_.client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "DRY-RUN"})

    assert (started_run.status_code, started_run.json()) == (
        409,
        {
            "message": unusable(settings_messages.worker_without_login()),
            "field": "wykonawcy[0].loginy",
        },
    )


def test_reczna_zmiana_listy_wykonawcow_ma_wiersz_historii_z_wpisem_do_cofniecia_a_dziennik_bez_danych_osobowych(
    tmp_path: Path,
) -> None:
    """„Cofnij” usuwa dopisaną ręcznie Wykonawczynię, bo jej loginu nie ma w Rejestrze zleceń ani w żadnym okresie."""

    app = centrum(tmp_path)
    write_worker_list(app.tool.worker_list, worker_list({"jan.testowy": "Jan Testowy"}, {"jan.testowy": [JAN]}))
    app.client.get("/api/settings")
    register = register_of(tmp_path)
    register.parent.mkdir()
    write_orders(register, ["jan.testowy"])
    app.platform.chosen_files.append(register)
    app.platform.chosen_folders.append(tmp_path / "INEA")
    (tmp_path / "INEA").mkdir()
    app.client.post("/api/settings/register/choose")
    app.client.post("/api/settings/periods-directory/choose")
    write_worker_list(app.tool.worker_list, worker_list({"jan.testowy": "Jan Nowak", "anna.przyklad": "Anna Przykład"}))

    [row] = [row for row in history_rows(app) if row["file"] == WORKERS_FILE]
    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert [(change["key"], change["before"] is None, change["after"] is None) for change in row["changes"]] == [
        ("wykonawcy[jan.testowy]", False, False),
        ("wykonawcy[anna.przyklad]", True, False),
    ]
    assert row["section"] == "wykonawcy"
    assert [worker["name"] for worker in undone.json()["settings"]["workers"]["workers"]] == ["Jan Testowy"]
    assert undone.json()["settings"]["workers"]["workers"][0]["addresses"] == [JAN]
    log = app.tool.log_path.read_text(encoding="utf-8")
    assert "ustawienia-spoza plik=wykonawcy.yaml wynik=zapisano" in log
    assert "ustawienia-zmiana plik=wykonawcy.yaml klucze=wykonawcy zrodlo=tata" in log
    for secret in ("jan.testowy", "Jan Nowak", "anna.przyklad", JAN):
        assert secret not in log, secret


# --- Lista Wykonawców: tata zmienia ją w sekcji Wykonawcy (#1474, ADR 0032) ---------------------------------------------

WORKERS_API = "/api/settings/workers"
# Syntetyczny Plik zbiorczy okresu ``PERIOD`` ma zlecenia adrian.testowy i dariusz.fikcyjny2; kamil.syntetyczny jest na
# Liście Wykonawców bez zleceń w tym okresie.
EARLIER_PERIOD = "01_07_09_2026"


def listed_workers(client: CentrumClient) -> dict[str, dict[str, Any]]:
    """Wykonawcy sekcji Wykonawcy po pierwszym loginie."""

    return {worker["logins"][0]: worker for worker in client.get("/api/settings").json()["workers"]["workers"]}


def worker_form(logins: list[str], name: str, addresses: list[str] | None = None) -> dict[str, object]:
    return {"logins": logins, "name": name, "addresses": addresses or []}


def settling_with_register(
    tmp_path: Path, logins: Sequence[str] | None, surroundings: Surroundings | None = None
) -> SettlingCentrum:
    """Centrum ze wskazanym syntetycznym Rejestrem zleceń (``register_of``), w którym zlecenia mają Wykonawców
    ``logins``; ``None``: tata nie wskazał Rejestru."""

    register = None
    if logins is not None:
        register = register_of(tmp_path)
        register.parent.mkdir()
        write_orders(register, logins)
    return settling_centrum(tmp_path, register=register, surroundings=surroundings)


def register_of(tmp_path: Path) -> Path:
    return tmp_path / "Rejestr" / REGISTER_NAME


def write_orders(register: Path, logins: Sequence[str], headers: tuple[str, ...] = REGISTER_HEADERS) -> None:
    """Rejestr zleceń ze zleceniem każdego z ``logins`` w kolumnie ``WYKONAWCA`` i nagłówkami ``headers``."""

    orders: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 8, 10), worker=login) for number, login in enumerate(logins, start=1)
    ]
    write_register(register, orders, headers=headers)


def test_tata_dodaje_wykonawce_a_adres_innego_wykonawcy_i_nazwa_na_ten_sam_plik_sa_odmowa_przy_polu(tmp_path: Path) -> None:
    """US 23, 28, 30: nowy Wykonawca z loginem, nazwą i adresem trafia na listę jako aktywny z przypomnieniami i ma
    wiersz Historii; adres, który ma już inny Wykonawca, i nazwa, która daje ten sam plik Rozliczenia pracownika, nie
    zapisują się, a odmowa wskazuje pole formularza."""

    centrum_ = settling_centrum(tmp_path)
    client = centrum_.client

    added = client.post(WORKERS_API, json=worker_form(["Bartek.Nowy"], "Bartek Nowy", [JAN]))
    file_after_add = centrum_.tool.worker_list.read_bytes()
    same_address = client.post(WORKERS_API, json=worker_form(["ewa.nowa"], "Ewa Nowa", [JAN.upper()]))
    same_file = client.post(WORKERS_API, json=worker_form(["ewa.nowa"], "bartek  NOWY"))

    assert added.status_code == 200, added.json()
    assert listed_workers(client)["bartek.nowy"] == listed(["bartek.nowy"], "Bartek Nowy", [JAN])
    [row] = history_rows_of(client)
    assert (row["section"], [change["key"] for change in row["changes"]], row["undoable"]) == (
        "wykonawcy",
        ["wykonawcy[bartek.nowy]"],
        True,
    )
    assert (same_address.status_code, same_address.json()) == (
        422,
        {"message": settings_messages.worker_address_repeated(), "field": "adresy[0]"},
    )
    assert (same_file.status_code, same_file.json()) == (
        422,
        {"message": settings_messages.worker_same_file(), "field": "nazwa"},
    )
    assert centrum_.tool.worker_list.read_bytes() == file_after_add
    assert len(history_rows_of(client)) == 1


WORKER_SUGGESTIONS_API = f"{WORKERS_API}/suggestions"


def test_login_ze_zlecen_ostatnich_okresow_spoza_listy_jest_podpowiedzia_ktora_znika_po_dodaniu_wykonawcy(
    tmp_path: Path,
) -> None:
    """US 24: login z ``WYKONAWCA`` uporządkowanych zleceń bieżącego okresu i 4 poprzednich (okresy, które Tablica okresów
    pokazuje od razu), którego nie ma żaden Wykonawca, także Nieaktywny i także jako drugi login, ani sprawa „login bez
    Wykonawcy”, jest podpowiedzią z liczbą tych zleceń, od najczęstszej; login tylko ze starszych zleceń i zlecenie z
    pustym ``WYKONAWCA`` nie są (D2 #1650 r1). Odpowiedź ma sam login
    i liczbę, bez treści Rejestru, a odczyt niczego nie zapisuje. Po dodaniu Wykonawcy z loginem podpowiedzi podpowiedź
    znika."""

    # Dziś (TODAY) jest środa 16.09.2026 w okresie od wtorku 15.09, więc 4 poprzednie okresy zaczynają się we wtorek 18.08.
    register = register_of(tmp_path)
    register.parent.mkdir()
    orders = [
        ("stary.login", datetime(2026, 8, 17, 10)),
        ("brzeg.okna", datetime(2026, 8, 18, 10)),
        ("adrian.testowy", datetime(2026, 9, 8, 9)),
        ("kamil.syntetyczny", datetime(2026, 9, 8, 10)),
        ("kamil.drugi", datetime(2026, 9, 8, 10, 30)),
        ("Nowy.Login", datetime(2026, 9, 8, 11)),
        ("", datetime(2026, 9, 8, 12)),
        ("sprawa.login", datetime(2026, 9, 9, 9)),
        ("nowy.login ", datetime(2026, 9, 9, 10)),
    ]
    write_register(
        register, [register_order(number, started, worker=login) for number, (login, started) in enumerate(orders, start=1)]
    )
    centrum_ = settling_centrum(tmp_path, register=register)
    client = centrum_.client
    address = SenderAddress.of("sprawa@przyklad.invalid")
    assert address is not None
    with_case = WorkerList.of(
        [
            WorkerEntry([login, "kamil.drugi"] if login == "kamil.syntetyczny" else [login], name)
            for login, name in SETTLEMENT_WORKERS.items()
        ],
        [UnmatchedLogin(Login("sprawa.login"), (address,))],
    )
    assert isinstance(with_case, WorkerList), with_case
    write_worker_list(centrum_.tool.worker_list, with_case)
    assert client.put(f"{WORKERS_API}/kamil.syntetyczny/switches", json={"active": False}).status_code == 200
    listed_before = centrum_.tool.worker_list.read_bytes()

    first = client.get(WORKER_SUGGESTIONS_API)
    listed_after_read = centrum_.tool.worker_list.read_bytes()
    added = client.post(WORKERS_API, json=worker_form(["nowy.login"], "Nowy Login"))
    second = client.get(WORKER_SUGGESTIONS_API)

    assert (first.status_code, first.json()) == (
        200,
        {
            "state": "read",
            "suggestions": [{"login": "nowy.login", "orders": 2}, {"login": "brzeg.okna", "orders": 1}],
            "message": None,
        },
    )
    assert listed_after_read == listed_before, "podpowiedzi niczego nie zapisują"
    assert added.status_code == 200, added.json()
    assert second.json()["suggestions"] == [{"login": "brzeg.okna", "orders": 1}]


# Zdanie „Co się stało” Komunikatu procesów wklejania o Rejestrze bez obszaru wklejania; nie zależy od ścieżki Rejestru.
NO_ORDER_SHEET = intermax_messages.no_order_sheet(Path(REGISTER_NAME)).what


def _register_unreadable_rows(centrum_: SettlingCentrum) -> None:
    """Arkusz zleceń, którego wierszy nie da się rozdzielić przy czytaniu od dołu (komentarz pod ostatnim wierszem)."""

    rewrite_parts(
        register_of(centrum_.tmp_path),
        lambda name, data: data.replace(b"</sheetData>", b"<!-- x --></sheetData>") if name.startswith("xl/worksheets/") else data,
    )


@pytest.mark.parametrize(
    ("register", "damage", "state", "message"),
    [
        pytest.param(None, None, "not_set", settings_messages.worker_suggestions_not_set(), id="bez-rejestru"),
        pytest.param(
            ["nowy.login"],
            lambda centrum_: register_of(centrum_.tmp_path).unlink(),
            "unreadable",
            settings_messages.worker_suggestions_unreadable(),
            id="rejestru-nie-ma",
        ),
        pytest.param(
            ["nowy.login"],
            lambda centrum_: register_of(centrum_.tmp_path).write_bytes(b"to nie jest skoroszyt"),
            "unreadable",
            settings_messages.worker_suggestions_unreadable(),
            id="nie-skoroszyt",
        ),
        pytest.param(
            ["nowy.login"],
            lambda centrum_: register_without_order_sheets(centrum_),
            "unreadable",
            NO_ORDER_SHEET,
            id="rejestr-bez-arkuszy-zlecen",
        ),
        pytest.param(
            ["nowy.login"],
            lambda centrum_: write_orders(register_of(centrum_.tmp_path), ["nowy.login"], OLD_REGISTER_HEADERS),
            "unreadable",
            NO_ORDER_SHEET,
            id="starszy-uklad-bez-obszaru-wklejania",
        ),
        pytest.param(
            ["nowy.login"],
            _register_unreadable_rows,
            "unreadable",
            settings_messages.worker_suggestions_unreadable(),
            id="wiersze-nie-do-rozdzielenia",
        ),
    ],
)
def test_bez_wskazanego_albo_czytelnego_rejestru_sekcja_wykonawcy_mowi_zdaniem_dlaczego_nie_ma_podpowiedzi(
    tmp_path: Path,
    register: list[str] | None,
    damage: Callable[[SettlingCentrum], None] | None,
    state: str,
    message: str,
) -> None:
    """US 24, W2 #1577 r1: niewskazany Rejestr zleceń albo Rejestr, którego nie da się przeczytać, to zdanie dla taty w
    sekcji Wykonawcy, a nie pusta lista, która wygląda jak „brak nowych loginów”. Rejestr bez obszaru wklejania (bez
    arkusza zleceń albo w starszym układzie bez AKCJE i UWAGI, z którego Przebieg czyta loginy) ma zdanie „Co się
    stało” tego samego Komunikatu, którym zatrzymują się na nim procesy wklejania (D1 #1650 r1)."""

    centrum_ = settling_with_register(tmp_path, register)
    if damage is not None:
        damage(centrum_)

    answer = centrum_.client.get(WORKER_SUGGESTIONS_API)

    assert (answer.status_code, answer.json()) == (200, {"state": state, "suggestions": [], "message": message})


def history_rows_of(client: CentrumClient) -> list[dict[str, Any]]:
    """Wiersze Historii Ustawień o Liście Wykonawców, od najnowszego."""

    return [row for row in client.get("/api/settings/history").json()["rows"] if row["file"] == WORKERS_FILE]


def kept(sentence: str) -> str:
    """Odmowa usunięcia: zdanie, dlaczego Wykonawca albo login zostaje, i propozycja Nieaktywnego."""

    return (
        f"{sentence} Gdy Wykonawca już nie pracuje, oznacz go jako nieaktywnego: nie dostanie przypomnień, a jego okresy "
        "dalej się rozliczą."
    )


def earlier_collective_file_damaged(centrum_: SettlingCentrum) -> None:
    earlier = centrum_.period_parent / EARLIER_PERIOD
    earlier.mkdir()
    (earlier / collective_file_name_with(EARLIER_PERIOD)).write_bytes(b"to nie jest skoroszyt")


def periods_directory_gone(centrum_: SettlingCentrum) -> None:
    """Folder okresów, który tata wskazał, zniknął (przeniesiony albo OneDrive odłączony)."""

    centrum_.periods_directory.rename(centrum_.tmp_path / "INEA przeniesione")


def register_without_order_sheets(centrum_: SettlingCentrum) -> None:
    """Rejestr zleceń, którego żaden arkusz nie ma nagłówków zleceń, choć login stoi pod ``WYKONAWCA``."""

    headers = tuple(f"{header} STARY" if header else header for header in REGISTER_HEADERS)
    write_orders(register_of(centrum_.tmp_path), ["adrian.testowy", "kamil.syntetyczny"], headers)


@pytest.mark.parametrize(
    ("register", "removed", "damage", "answer"),
    [
        pytest.param(
            ["adrian.testowy", "kamil.syntetyczny"],
            "kamil.syntetyczny",
            None,
            kept("Wykonawca ma zlecenia w Rejestrze zleceń, więc zostaje na Liście Wykonawców."),
            id="w-rejestrze",
        ),
        pytest.param(
            ["adrian.testowy"],
            "dariusz.fikcyjny2",
            None,
            kept(f"Wykonawca ma zlecenia w okresie {PERIOD}, więc zostaje na Liście Wykonawców."),
            id="tylko-w-pliku-zbiorczym",
        ),
        pytest.param(
            ["adrian.testowy"],
            "kamil.syntetyczny",
            earlier_collective_file_damaged,
            kept(
                f"Nie da się teraz przeczytać Pliku zbiorczego okresu {EARLIER_PERIOD}, więc nie wiadomo, czy Wykonawca "
                "ma w nim zlecenia."
            ),
            id="nieczytelny-plik-zbiorczy",
        ),
        pytest.param(
            None,
            "kamil.syntetyczny",
            None,
            kept("Nie wiadomo, czy Wykonawca ma zlecenia w okresach: najpierw wskaż Rejestr zleceń i folder okresów."),
            id="bez-rejestru",
        ),
        pytest.param(
            ["adrian.testowy"],
            "kamil.syntetyczny",
            register_without_order_sheets,
            kept("Nie da się teraz przeczytać Rejestru zleceń, więc nie wiadomo, czy Wykonawca ma w nim zlecenia."),
            id="rejestr-bez-arkuszy-zlecen",
        ),
        pytest.param(
            ["adrian.testowy"],
            "kamil.syntetyczny",
            periods_directory_gone,
            kept("Nie da się teraz odczytać folderu okresów, więc nie wiadomo, czy Wykonawca ma zlecenia w okresach."),
            id="bez-folderu-okresow",
        ),
    ],
)
def test_usuniecie_wykonawcy_z_loginem_w_okresie_jest_odmowa_z_propozycja_nieaktywnego(
    tmp_path: Path,
    register: list[str] | None,
    removed: str,
    damage: Callable[[SettlingCentrum], None] | None,
    answer: str,
) -> None:
    """ADR 0032, US 34, 36: Wykonawcy, którego login stoi w Rejestrze zleceń albo w Pliku zbiorczym okresu, nie da się
    usunąć, tak samo gdy któregoś pliku nie da się przeczytać, Rejestr nie ma arkuszy zleceń, folderu okresów nie ma
    albo Rejestr nie jest wskazany; odmowa proponuje Nieaktywnego, a lista i Historia zostają bez zmiany. Propozycja
    działa: Nieaktywny zostaje na liście."""

    centrum_ = settling_with_register(tmp_path, register)
    if damage is not None:
        damage(centrum_)
    before = centrum_.tool.worker_list.read_bytes()

    refused_ = centrum_.client.delete(f"{WORKERS_API}/{removed}")
    after_refusal = centrum_.tool.worker_list.read_bytes()
    inactive = centrum_.client.put(f"{WORKERS_API}/{removed}/switches", json={"active": False})

    assert (refused_.status_code, refused_.json()) == (409, {"message": answer})
    assert after_refusal == before
    assert inactive.status_code == 200
    assert listed_workers(centrum_.client)[removed]["active"] is False
    assert [change["key"] for row in history_rows_of(centrum_.client) for change in row["changes"]] == [
        f"wykonawcy[{removed}]"
    ], "odmowa nie ma wiersza Historii, przełącznik ma"


@PATH_CHECKS
@pytest.mark.parametrize(
    ("folder", "answer"),
    [
        pytest.param(
            lambda centrum_: centrum_.periods_directory,
            "Nie da się teraz odczytać folderu okresów, więc nie wiadomo, czy Wykonawca ma zlecenia w okresach.",
            id="folder-okresow",
        ),
        pytest.param(
            lambda centrum_: centrum_.period_directory,
            f"Nie da się teraz przeczytać Pliku zbiorczego okresu {PERIOD}, więc nie wiadomo, czy Wykonawca ma w nim "
            "zlecenia.",
            id="folder-okresu",
        ),
    ],
)
def test_usuniecie_wykonawcy_gdy_folderu_z_okresami_nie_da_sie_wylistowac_jest_odmowa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_checks: Callable[[pytest.MonkeyPatch], None],
    folder: Callable[[SettlingCentrum], Path],
    answer: str,
) -> None:
    """Folder okresów albo Folder okresu, którego system nie daje teraz wylistować (odebrane prawo odczytu, OneDrive,
    który nie działa), nie znaczy, że loginu w nim nie ma: usunięcie Wykonawcy jest odmową, a lista zostaje."""

    centrum_ = settling_with_register(tmp_path, ["adrian.testowy"])
    before = centrum_.tool.worker_list.read_bytes()
    path_checks(monkeypatch)

    with without_reading(folder(centrum_)):
        refused_ = centrum_.client.delete(f"{WORKERS_API}/kamil.syntetyczny")

    assert (refused_.status_code, refused_.json()) == (409, {"message": kept(answer)})
    assert centrum_.tool.worker_list.read_bytes() == before


def test_drugie_usuniecie_widzi_plik_zbiorczy_zmieniony_po_pierwszym(tmp_path: Path) -> None:
    """Sprawdzenie okresów pamięta Wykonawców przeczytanych Plików zbiorczych, ale nie odpowiada starym stanem: zlecenie,
    które po pierwszym usunięciu doszło Wykonawcy w Pliku zbiorczym, zatrzymuje usunięcie tego Wykonawcy."""

    centrum_ = settling_with_register(tmp_path, ["adrian.testowy"])
    client = centrum_.client
    client.post(WORKERS_API, json=worker_form(["pomylka.login"], "Pomyłka Testowa"))
    client.post(WORKERS_API, json=worker_form(["andrzej.nieznany2"], "Andrzej Nowy"))
    first = client.delete(f"{WORKERS_API}/pomylka.login")
    write_source(centrum_.collective_file, include_unmapped=True)

    second = client.delete(f"{WORKERS_API}/andrzej.nieznany2")

    assert first.status_code == 200, first.json()
    assert (second.status_code, second.json()) == (
        409,
        {"message": kept(f"Wykonawca ma zlecenia w okresie {PERIOD}, więc zostaje na Liście Wykonawców.")},
    )
    assert "andrzej.nieznany2" in listed_workers(client)


def with_second_login(workers_file: Path, login: str, second: str) -> None:
    """Ręczna zmiana pliku Listy Wykonawców: Wykonawca z loginem ``login`` dostaje login ``second``."""

    document = yaml.safe_load(workers_file.read_text(encoding="utf-8"))
    next(entry for entry in document["wykonawcy"] if login in entry["loginy"])["loginy"].append(second)
    workers_file.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")


def test_login_dopisany_w_trakcie_sprawdzania_okresow_zatrzymuje_usuniecie_wykonawcy(tmp_path: Path) -> None:
    """Okresy sprawdza się poza blokadą Ustawień, bo pierwsze sprawdzenie czyta Plik zbiorczy każdego okresu. Login,
    który Wykonawca dostał w tym czasie (tu ręczna zmiana pliku Listy Wykonawców), nie był sprawdzony, więc usunięcie
    jest odmową, a Wykonawca zostaje z oboma loginami."""

    workers_file = ToolDirectory(tmp_path).worker_list
    steps: list[str] = []

    def second_login(_register: Path) -> None:
        if steps == ["usuwanie"]:
            steps.append("dopisany")
            with_second_login(workers_file, "kamil.syntetyczny", "kamil.drugi")

    centrum_ = settling_with_register(tmp_path, ["adrian.testowy"], Surroundings(source=on_register_read(second_login)))
    steps.append("usuwanie")

    refused_ = centrum_.client.delete(f"{WORKERS_API}/kamil.syntetyczny")

    assert steps == ["usuwanie", "dopisany"], "login doszedł w trakcie sprawdzania okresów"
    assert (refused_.status_code, refused_.json()["message"]) == (422, settings_messages.worker_list_changed())
    assert listed_workers(centrum_.client)["kamil.syntetyczny"]["logins"] == ["kamil.syntetyczny", "kamil.drugi"]


def test_wykonawce_bez_loginu_w_zadnym_okresie_tata_usuwa_a_historia_pozwala_go_przywrocic(tmp_path: Path) -> None:
    """US 36: Wykonawca dodany przez pomyłkę (loginu nie ma w Rejestrze zleceń ani w żadnym Pliku zbiorczym) znika z
    listy po pełnym sprawdzeniu, a „Cofnij” z Historii przywraca go z adresami."""

    centrum_ = settling_with_register(tmp_path, ["adrian.testowy"])
    centrum_.client.post(WORKERS_API, json=worker_form(["pomylka.login"], "Pomyłka Testowa", [OBCY]))

    removed = centrum_.client.delete(f"{WORKERS_API}/pomylka.login")
    after_remove = listed_workers(centrum_.client)
    undone = centrum_.client.post(f"/api/settings/history/{removed.json()['change']}/undo")

    assert removed.status_code == 200, removed.json()
    assert "pomylka.login" not in after_remove and "kamil.syntetyczny" in after_remove
    assert undone.status_code == 200
    assert listed_workers(centrum_.client)["pomylka.login"] == listed(["pomylka.login"], "Pomyłka Testowa", [OBCY])


def settings_files(centrum_: SettlingCentrum) -> dict[str, bytes]:
    """Lista Wykonawców, Historia Ustawień i pamięć Ustawień, bajt w bajt."""

    config = centrum_.tool.config
    paths = [config / WORKERS_FILE, config / HISTORY_FILE, *(config / MEMORY_DIRECTORY).rglob("*")]
    return {path.relative_to(config).as_posix(): path.read_bytes() for path in paths if path.is_file()}


@pytest.mark.parametrize(
    ("register", "change", "answer"),
    [
        pytest.param(
            ["adrian.testowy", "nowy.login"],
            ("POST", WORKERS_API, worker_form(["nowy.login"], "Nowy Testowy")),
            kept("Wykonawca ma zlecenia w Rejestrze zleceń, więc zostaje na Liście Wykonawców."),
            id="dodanie-wykonawcy",
        ),
        pytest.param(
            ["adrian.testowy", "adrian.drugi"],
            ("PUT", f"{WORKERS_API}/adrian.testowy", worker_form(["adrian.testowy", "adrian.drugi"], "Adrian Testowy")),
            kept("Ten login ma zlecenia w Rejestrze zleceń, więc zostaje przy Wykonawcy."),
            id="dopisanie-loginu",
        ),
    ],
)
def test_cofnij_zmiany_ktora_dala_login_ze_zleceniami_jest_odmowa_jak_usuniecie(
    tmp_path: Path, register: list[str], change: tuple[str, str, dict[str, object]], answer: str
) -> None:
    """ADR 0032: „Cofnij” w Historii i w powiadomieniu „Zapisano · Cofnij” usuwa to, co zmiana dodała, więc przechodzi
    to samo sprawdzenie okresów co „Usuń Wykonawcę” i formularz: login, który ma już zlecenia w Rejestrze zleceń,
    zostaje, a odmowa mówi dlaczego i proponuje Nieaktywnego, bez zmiany pliku, Historii i pamięci Ustawień."""

    centrum_ = settling_with_register(tmp_path, register)
    method, url, form = change
    saved = centrum_.client.request(method, url, json=form)
    before = settings_files(centrum_)

    undone = centrum_.client.post(f"/api/settings/history/{saved.json()['change']}/undo")

    assert saved.status_code == 200, saved.json()
    assert (undone.status_code, undone.json()) == (409, {"message": answer})
    assert settings_files(centrum_) == before
    assert [row["undoable"] for row in history_rows_of(centrum_.client)] == [True]


def test_zapisanego_loginu_nie_da_sie_przepisac_gdy_ma_zlecenia_a_drugi_login_tata_dopisuje(tmp_path: Path) -> None:
    """US 29, 38: formularz, w którym zapisany login z zleceniami w okresie zastąpiono innym, nie zapisuje się, bo
    zmieniłby po cichu, czyje zlecenia trafiają do kogo; dopisany drugi login obok zapisanego się zapisuje."""

    centrum_ = settling_with_register(tmp_path, ["kamil.syntetyczny"])
    before = centrum_.tool.worker_list.read_bytes()

    rewritten = centrum_.client.put(
        f"{WORKERS_API}/adrian.testowy", json=worker_form(["adrian.nowy"], "Adrian Testowy")
    )
    unchanged = centrum_.tool.worker_list.read_bytes()
    second = centrum_.client.put(
        f"{WORKERS_API}/adrian.testowy", json=worker_form(["adrian.testowy", "Adrian.Nowy"], "Adrian Testowy")
    )

    assert (rewritten.status_code, rewritten.json()) == (
        409,
        {"message": kept(f"Ten login ma zlecenia w okresie {PERIOD}, więc zostaje przy Wykonawcy.")},
    )
    assert unchanged == before
    assert second.status_code == 200, second.json()
    assert listed_workers(centrum_.client)["adrian.testowy"]["logins"] == ["adrian.testowy", "adrian.nowy"]


def test_ostrzezenie_o_starej_nazwie_tylko_gdy_rozliczenie_pracownika_z_nia_lezy_w_okresie(tmp_path: Path) -> None:
    """US 31–32: zmiana nazwy Wykonawcy, którego Rozliczenie pracownika leży już w Folderze rozliczeń pracowników,
    niczego nie zapisuje bez potwierdzenia i mówi, że stary plik zostaje; potwierdzona zapisuje nazwę i nie rusza
    plików taty. Wykonawca bez takiego pliku zmienia nazwę od razu."""

    centrum_ = settling_centrum(tmp_path)
    folder = write_worker_settlements(centrum_.period_directory, PERIOD, ["Adrian Testowy"])
    files_before = sorted(path.name for path in folder.iterdir())
    client = centrum_.client

    asked = client.put(f"{WORKERS_API}/adrian.testowy", json=worker_form(["adrian.testowy"], "Adrian Nowak"))
    name_after_ask = listed_workers(client)["adrian.testowy"]["name"]
    confirmed = client.put(
        f"{WORKERS_API}/adrian.testowy",
        json=worker_form(["adrian.testowy"], "Adrian Nowak") | {"rename_confirmed": True},
    )
    without_file = client.put(f"{WORKERS_API}/kamil.syntetyczny", json=worker_form(["kamil.syntetyczny"], "Kamil Nowy"))

    assert (asked.status_code, asked.json()["change"], asked.json()["rename_warning"]) == (
        200,
        None,
        settings_messages.worker_rename_old_files((PERIOD,)),
    )
    assert name_after_ask == "Adrian Testowy"
    assert (confirmed.json()["rename_warning"], confirmed.json()["change"] is not None) == (None, True)
    assert (without_file.json()["rename_warning"], without_file.json()["change"] is not None) == (None, True)
    assert {login: worker["name"] for login, worker in listed_workers(client).items()} == {
        "adrian.testowy": "Adrian Nowak",
        "dariusz.fikcyjny2": "Darek Fikcyjny",
        "kamil.syntetyczny": "Kamil Nowy",
    }
    assert sorted(path.name for path in folder.iterdir()) == files_before


def test_wykonawca_dodany_w_ustawieniach_z_drugim_loginem_trafia_do_rozliczenia_pracownika_w_nastepnym_przebiegu(
    tmp_path: Path,
) -> None:
    """US 23, 29: Przebieg rozliczeń zatrzymuje się na loginie spoza Listy Wykonawców; po dodaniu Wykonawcy w
    Ustawieniach i dopisaniu mu tego loginu jako drugiego następny Przebieg daje jego Rozliczenie pracownika."""

    centrum_ = settling_centrum(tmp_path, include_unmapped=True)
    stopped = run_to_end(centrum_, dry_run=False)
    centrum_.client.post(WORKERS_API, json=worker_form(["andrzej.nowy"], "Andrzej Nowy"))
    centrum_.client.put(
        f"{WORKERS_API}/andrzej.nowy", json=worker_form(["andrzej.nowy", "andrzej.nieznany2"], "Andrzej Nowy")
    )

    settled = run_to_end(centrum_, dry_run=False)

    assert stopped["result"]["result"] == "BLAD_KRYTYCZNY"
    assert settled["result"]["result"] == "OK", settled["result"]
    folder = PeriodFolder(centrum_.period_parent, parse_period_token(PERIOD))
    assert folder.worker_settlement("Andrzej Nowy").is_file()


def test_kazda_zmiana_wykonawcy_ma_wiersz_historii_a_zgloszenie_nie_ma_loginu_nazwy_ani_adresu(tmp_path: Path) -> None:
    """Każda zmiana z sekcji Wykonawcy (dodanie, formularz, przełącznik, usunięcie) ma wiersz Historii taty z „Cofnij”,
    a Zgłoszenie mówi tylko, co się zmieniło, bez loginu, nazwy i adresu (D4 projektu Ustawień)."""

    centrum_ = settling_with_register(tmp_path, ["adrian.testowy"])
    client = centrum_.client
    client.post(WORKERS_API, json=worker_form([LEAKED_LOGIN], LEAKED_NAME, [LEAKED_ADDRESS]))
    client.put(f"{WORKERS_API}/{LEAKED_LOGIN}", json=worker_form([LEAKED_LOGIN], f"{LEAKED_NAME} Drugi", [LEAKED_ADDRESS]))
    client.put(f"{WORKERS_API}/{LEAKED_LOGIN}/switches", json={"reminders": False})
    client.delete(f"{WORKERS_API}/{LEAKED_LOGIN}")

    rows = history_rows_of(client)
    report = client.post(f"/api/runs/{stopped_for_maks(centrum_)}/diagnosis").json()["report"]["body"]

    assert [(row["source"], row["section"], row["undoable"], row["refused"]) for row in rows] == [
        ("tata", "wykonawcy", True, False)
    ] * 4
    for line in ("usunięto Wykonawcę", "zmieniono Wykonawcę (pola: przypomnienia)", "zmieniono Wykonawcę (pola: nazwa)", "dodano Wykonawcę"):
        assert line in report, line
    seen = {"Zgłoszenie": report, "Logi Centrum": centrum_.tool.log_path.read_text(encoding="utf-8")}
    leaks = [(where, secret) for where, text in seen.items() for secret in (LEAKED_LOGIN, LEAKED_NAME, LEAKED_ADDRESS) if secret in text]
    assert leaks == []


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


# --- Przypomnienia o raporcie (#1476, ADR 0032 zmienia ADR 0030): formularz, przełącznik, przeniesienie z plików Maksa --

def reminders_form(**changes: object) -> dict[str, object]:
    return {**ADR_0030_REMINDERS, **changes}


def test_przypomnienia_bez_pliku_sa_wylaczone_z_porami_i_trescia_z_adr_0030_i_nie_zakladaja_pliku(tmp_path: Path) -> None:
    """D2 projektu Ustawień: brak pliku przypomnień to dzisiejsze wartości z ADR 0030 jako domyślne, a przypomnienia są
    wyłączone jak przed Wydaniem bez dnia wdrożenia; odczyt pliku nie zakłada."""

    app = centrum(tmp_path)

    reminders = app.client.get("/api/settings").json()["reminders"]

    assert reminders == NO_REMINDERS
    assert not (app.tool.config / REMINDERS_FILE).exists()


@pytest.mark.parametrize(
    ("changes", "field", "sentence"),
    [
        pytest.param({"morning": {"start": "08:00", "end": "18:30"}}, "pora_wieczorna.od", settings_messages.reminders_overlap(), id="pory-zachodza"),
        pytest.param({"evening": {"start": "07:00", "end": "07:30"}}, "pora_wieczorna.od", settings_messages.reminders_overlap(), id="wieczorna-przed-poranna"),
        pytest.param({"morning": {"start": "08:00", "end": "08:00"}}, "pora_poranna.do", settings_messages.reminders_empty_morning(), id="pusta-poranna"),
        pytest.param({"evening": {"start": "22:00", "end": "18:00"}}, "pora_wieczorna.do", settings_messages.reminders_empty_evening(), id="odwrocona-wieczorna"),
        pytest.param({"morning": {"start": "", "end": "17:00"}}, "pora_poranna.od", settings_messages.reminders_time(), id="pusta-godzina"),
        pytest.param({"evening": {"start": "18:00", "end": "24:00"}}, "pora_wieczorna.do", settings_messages.reminders_time(), id="godzina-24"),
        pytest.param({"first": "7.30"}, "pierwsze_przypomnienie", settings_messages.reminders_time(), id="godzina-z-kropka"),
        pytest.param({"text": "  \n"}, "tresc", settings_messages.reminders_empty_text(), id="puste-zdanie"),
        pytest.param({"text": "Raport za {dzien}."}, "tresc", settings_messages.reminders_unknown_field(), id="pole-bez-polskiej-litery"),
        pytest.param({"text": "Raport za {dzień} od {wykonawca}."}, "tresc", settings_messages.reminders_unknown_field(), id="nieznane-pole"),
        pytest.param({"text": "Raport za {dzień}}."}, "tresc", settings_messages.reminders_unknown_field(), id="samotny-nawias"),
    ],
)
def test_zla_pora_godzina_albo_tresc_przypomnien_jest_odrzucona_zdaniem_przy_polu_bez_zapisu_i_bez_podgladu(
    tmp_path: Path, changes: dict[str, object], field: str, sentence: str
) -> None:
    """US 44: pory, które na siebie zachodzą albo są puste, godzina inna niż ``GG:MM`` i treść bez zdania albo z polem
    innym niż ``{dzień}`` dają odmowę z polem i jednym zdaniem; nic się nie zapisuje, a podgląd odmawia tak samo."""

    app = centrum(tmp_path)

    saved = app.client.put("/api/settings/reminders", json=reminders_form(**changes))
    preview = app.client.post("/api/settings/reminders/preview", json=reminders_form(**changes))

    assert [(response.status_code, response.json()) for response in (saved, preview)] == [
        (422, {"message": sentence, "field": field})
    ] * 2
    assert not (app.tool.config / REMINDERS_FILE).exists()
    assert history_rows(app) == []


def test_pory_stykajace_sie_godzina_i_tresc_z_polem_dnia_zapisuja_sie_od_razu(tmp_path: Path) -> None:
    """Poranna pora może kończyć się dokładnie wtedy, gdy zaczyna się wieczorna, a godzina pierwszego przypomnienia nie
    musi leżeć w porze (D11 projektu Ustawień)."""

    app = centrum(tmp_path)
    form = reminders_form(
        morning={"start": "07:00", "end": "15:00"},
        evening={"start": "15:00", "end": "21:30"},
        first="06:45",
        text="Proszę o raport za {dzień}, dziękuję za {dzień}.",
        footer="Pozdrawiam\nTata Testowy\n",
    )

    saved = app.client.put("/api/settings/reminders", json=form)

    assert saved.status_code == 200
    assert saved.json()["settings"]["reminders"] == {**form, "state": "good", "enabled": False, "since": None, "problem": None}


def test_godzina_przypomnien_bez_zera_na_poczatku_zapisuje_sie_jako_gg_mm(tmp_path: Path) -> None:
    """Tata pisze godzinę tak, jak ją mówi („8:00”): przyjmuje ją podgląd i zapis, a sekcja i plik mają ją jako ``GG:MM``."""

    app = centrum(tmp_path)
    form = reminders_form(morning={"start": "7:30", "end": "15:00"}, first="8:00")

    preview = app.client.post("/api/settings/reminders/preview", json=form)
    saved = app.client.put("/api/settings/reminders", json=form)

    assert (preview.status_code, saved.status_code) == (200, 200)
    shown = saved.json()["settings"]["reminders"]
    assert (shown["morning"], shown["first"]) == ({"start": "07:30", "end": "15:00"}, "08:00")
    assert yaml.safe_load((app.tool.config / REMINDERS_FILE).read_text(encoding="utf-8"))["pora_poranna"] == {"od": "07:30", "do": "15:00"}


def test_przelacznik_przypomnien_przy_pierwszym_wlaczeniu_zapisuje_dzien_wdrozenia_a_ponowne_go_zostawia(
    tmp_path: Path,
) -> None:
    """US 40: pierwsze włączenie ustawia dzień wdrożenia na dziś taty, a wyłączenie i ponowne włączenie innego dnia go
    zostawia, bo okno dni i tak kończy się na okresach z Plikiem zbiorczym (DESIGN §5.1)."""

    first = centrum(tmp_path, today=date(2026, 11, 12))
    on = first.client.put("/api/settings/reminders/enabled", json={"enabled": True})
    off = first.client.put("/api/settings/reminders/enabled", json={"enabled": False})
    first.client.stop()
    later = centrum(tmp_path, today=date(2026, 11, 20))
    again = later.client.put("/api/settings/reminders/enabled", json={"enabled": True})

    shown = [(response.json()["settings"]["reminders"]["enabled"], response.json()["settings"]["reminders"]["since"]) for response in (on, off, again)]
    assert shown == [(True, "2026-11-12"), (False, "2026-11-12"), (True, "2026-11-12")]


def test_zmiana_przypomnien_ma_wiersz_historii_z_porami_przed_i_po_a_cofniecie_przywraca_pory(tmp_path: Path) -> None:
    """US 80–81 dla sekcji Przypomnienia: wiersz Historii ma pory i stopkę przed i po, Logi Centrum tylko klucze, a
    cofnięcie przywraca poprzednie pory i stopkę."""

    app = centrum(tmp_path)
    changed = reminders_form(morning={"start": "07:00", "end": "12:00"}, footer="Pozdrawiam\nTata Testowy")

    saved = app.client.put("/api/settings/reminders", json=changed)
    [row] = history_rows(app)
    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert (saved.status_code, saved.json()["change"], row["section"], row["undoable"]) == (200, row["id"], "przypomnienia", True)
    assert row["changes"] == [
        {"key": "przypomnienia.pora_poranna", "before": "08:00 – 17:00", "after": "07:00 – 12:00"},
        {"key": "przypomnienia.stopka", "before": None, "after": "Pozdrawiam\nTata Testowy"},
    ]
    assert undone.status_code == 200
    assert {key: undone.json()["settings"]["reminders"][key] for key in ADR_0030_REMINDERS} == ADR_0030_REMINDERS
    log = app.tool.log_path.read_text(encoding="utf-8")
    assert "ustawienia-zmiana plik=przypomnienia.yaml klucze=przypomnienia.pora_poranna,przypomnienia.stopka zrodlo=tata" in log
    assert "Tata Testowy" not in log


def test_reczny_plik_przypomnien_z_porami_zachodzacymi_to_zle_ustawienie_z_polem_i_ostatnimi_dobrymi_porami(
    tmp_path: Path,
) -> None:
    """US 91: plik przypomnień zmieniony ręcznie z porami, które na siebie zachodzą, nie zatrzymuje Centrum: sekcja ma
    zdanie przy polu i ostatnie dobre pory, a Historia wiersz odrzuconej zmiany spoza Centrum."""

    app = centrum(tmp_path)
    app.client.put("/api/settings/reminders", json=reminders_form(first="07:30"))
    content = (app.tool.config / REMINDERS_FILE).read_text(encoding="utf-8").replace("'17:00'", "'19:00'")
    (app.tool.config / REMINDERS_FILE).write_text(content, encoding="utf-8")

    reminders = app.client.get("/api/settings").json()["reminders"]

    assert (reminders["state"], reminders["problem"]) == (
        "bad",
        {"field": "pora_wieczorna.od", "message": settings_messages.reminders_overlap()},
    )
    assert (reminders["morning"], reminders["first"]) == ({"start": "08:00", "end": "17:00"}, "07:30")
    assert [(row["source"], row["refused"]) for row in history_rows(app)][:1] == [("outside", True)]


def test_zla_wartosc_pola_pliku_przypomnien_kaze_zapisac_ustawienia_a_zapis_taty_ja_naprawia(tmp_path: Path) -> None:
    """Plik przypomnień tata zmienia w oknie Ustawień, więc zdanie złej wartości pola mówi „Zapisz Ustawienia jeszcze
    raz.”, a nie „Poprawia go Maks.”, i zapis sekcji przez tatę naprawia plik (przegląd #1568 r4, D1)."""

    app = centrum(tmp_path)
    app.client.put("/api/settings/reminders", json=reminders_form(first="07:30"))
    path = app.tool.config / REMINDERS_FILE
    content = path.read_text(encoding="utf-8").replace("pora_wieczorna:\n  od: '18:00'\n  do: '22:00'", "pora_wieczorna: wieczorem")
    path.write_text(content, encoding="utf-8")

    bad = app.client.get("/api/settings").json()["reminders"]
    saved = app.client.put("/api/settings/reminders", json=reminders_form(first="08:00"))
    after = app.client.get("/api/settings").json()["reminders"]

    assert (bad["state"], bad["problem"]) == (
        "bad",
        {
            "field": "pora_wieczorna",
            "message": settings_messages.bad_field(REMINDERS_FILE, FieldPath("pora_wieczorna"), settings_messages.SAVE_AGAIN),
        },
    )
    assert (saved.status_code, after["state"], after["first"]) == (200, "good", "08:00")


def migrated_reminders(tool: ToolDirectory) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Sekcja Przypomnienia i Historia Ustawień po pierwszym starcie Wydania z Przypomnieniami w Ustawieniach."""

    client = started(tool, RELEASE_CHANGES)
    reminders = client.get("/api/settings").json()["reminders"]
    rows = client.get("/api/settings/history").json()["rows"]
    client.stop()
    return reminders, [row for row in rows if row["file"] == REMINDERS_FILE]


@pytest.mark.parametrize(
    ("rollout", "footer", "enabled", "since", "kept"),
    [
        pytest.param(b"2026-11-09\n", "Pozdrawiam\nTata\n".encode(), True, "2026-11-09", "Pozdrawiam\nTata\n", id="oba-pliki"),
        pytest.param(codecs.BOM_UTF8 + b"2026-11-09\r\n", "Pozdrawiam\r\nTata\r\n".encode("utf-16"), True, "2026-11-09", "Pozdrawiam\r\nTata\r\n", id="notatnik-i-powershell"),
        pytest.param(b"2026-11-09\n", None, True, "2026-11-09", "", id="bez-stopki"),
        pytest.param(b"od wtorku\n", "Pozdrawiam\n".encode(), False, None, "Pozdrawiam\n", id="zly-dzien-wylacza-jak-dotad"),
        pytest.param(None, "Pozdrawiam\n".encode(), False, None, "Pozdrawiam\n", id="bez-dnia-wdrozenia"),
        pytest.param(b"2026-11-09\n", b" \n", True, "2026-11-09", "", id="pusta-stopka"),
        pytest.param(b"2026-11-09\n", "Pozdrawiam\u0085Tata\n".encode(), True, "2026-11-09", "Pozdrawiam\u0085Tata\n", id="stopka-ze-znakiem-nel"),
        pytest.param(b"2026-11-09\n2026-11-10\n", "Pozdrawiam\n".encode(), False, None, "Pozdrawiam\n", id="kilka-dni-wylacza-jak-dotad"),
    ],
)
def test_przeniesienie_przypomnien_z_plikow_maksa_daje_dzien_wdrozenia_i_stopke_bez_cofnij_a_stare_pliki_zostaja(
    tmp_path: Path, rollout: bytes | None, footer: bytes | None, enabled: bool, since: str | None, kept: str
) -> None:
    """Po Aktualizacji dzień wdrożenia z ``przypomnienia-od.txt`` włącza przypomnienia od tego dnia, a inna treść albo
    brak pliku zostawia je wyłączone jak dotąd; stopka przechodzi tekstem bez zmian (także z BOM i w UTF-16), pory i treść
    to wartości domyślne. Przeniesienie ma wiersz z Wydania bez „Cofnij” (D8), a stare pliki zostają bajt w bajt."""

    tool = ToolDirectory(tmp_path)
    tool.config.mkdir(parents=True)
    old = {name: content for name, content in ((OLD_ROLLOUT_FILE, rollout), (OLD_FOOTER_FILE, footer)) if content is not None}
    for name, content in old.items():
        (tool.config / name).write_bytes(content)

    reminders, [row] = migrated_reminders(tool)
    _, again = migrated_reminders(tool)

    assert reminders == {**ADR_0030_REMINDERS, "footer": kept, "state": "good", "enabled": enabled, "since": since, "problem": None}
    assert (row["source"], row["release"]["change"], row["undoable"], row["refused"]) == ("release", "2026-11-przypomnienia", False, False)
    assert len(again) == 1, "przeniesienie wchodzi raz"
    assert {name: (tool.config / name).read_bytes() for name in old} == old


def test_bez_starych_plikow_przypomnien_przeniesienie_nie_zaklada_pliku_ani_wiersza(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)

    reminders, rows = migrated_reminders(tool)

    assert (reminders["enabled"], rows, (tool.config / REMINDERS_FILE).exists()) == (False, [], False)


@NO_ACCESS_ON_WINDOWS
def test_stary_plik_stopki_bez_prawa_odczytu_czeka_na_nastepny_start_zamiast_zgubic_stopke(tmp_path: Path) -> None:
    """Stary plik, którego system nie daje teraz czytać, nie jest ani pusty, ani brakujący: przeniesienie czeka bez
    pliku przypomnień i bez wiersza, a następny start przenosi stopkę."""

    tool = ToolDirectory(tmp_path)
    tool.config.mkdir(parents=True)
    (tool.config / OLD_ROLLOUT_FILE).write_text("2026-11-09\n", encoding="utf-8")
    (tool.config / OLD_FOOTER_FILE).write_text("Pozdrawiam\n", encoding="utf-8")
    with without_access(tool.config / OLD_FOOTER_FILE):
        locked, locked_rows = migrated_reminders(tool)
        written_while_locked = (tool.config / REMINDERS_FILE).exists()

    reminders, rows = migrated_reminders(tool)

    assert (written_while_locked, locked_rows, locked["enabled"]) == (False, [], False)
    assert (reminders["enabled"], reminders["footer"], len(rows)) == (True, "Pozdrawiam\n", 1)


AUTOSTART_ON = {"key": "narzedzie.autostart", "before": "wylaczony", "after": "wlaczony"}
AUTOSTART_OFF = {"key": "narzedzie.autostart", "before": "wlaczony", "after": "wylaczony"}


def autostart(app: Centrum, enabled: bool) -> Any:
    return app.client.put("/api/settings/autostart", json={"enabled": enabled})


def test_przelacznik_autostartu_dwa_razy_wlaczony_daje_jeden_skrot_a_wylaczony_go_usuwa(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    before = app.client.get("/api/settings").json()["autostart"]["state"]

    enabled, again = autostart(app, True), autostart(app, True)
    shortcuts_after_two = sorted(path.name for path in app.autostart.folder.iterdir())
    disabled = autostart(app, False)
    rows = history_rows(app)

    assert before == "off"
    assert (enabled.json()["settings"]["autostart"]["state"], again.json()["settings"]["autostart"]["state"]) == ("on", "on")
    assert shortcuts_after_two == [SHORTCUT_FILE]
    assert (again.json()["change"], app.autostart.enabled) == (None, 1)
    assert (disabled.json()["settings"]["autostart"]["state"], list(app.autostart.folder.iterdir())) == ("off", [])
    assert [(row["source"], row["section"], row["changes"], row["undoable"]) for row in rows] == [
        ("tata", "narzedzie", [AUTOSTART_OFF], True),
        ("tata", "narzedzie", [AUTOSTART_ON], True),
    ]
    assert [enabled.json()["change"], disabled.json()["change"]] == [row["id"] for row in rows[::-1]]
    assert "ustawienia-zmiana plik=autostart klucze=narzedzie.autostart zrodlo=tata" in app.log_path.read_text(
        encoding="utf-8"
    )


def test_skrot_autostartu_z_instalacji_jest_stanem_wyjsciowym_a_usuniety_recznie_to_wylaczony_z_wierszem_spoza_centrum(
    tmp_path: Path,
) -> None:
    """Polecenie instalacji założyło skrót przed Wydaniem z Ustawieniami; potem ktoś usuwa go z folderu Autostart."""

    app = centrum(tmp_path)
    app.autostart.enable()
    installed = app.client.get("/api/settings").json()["autostart"]["state"]
    rows_after_install = history_rows(app)

    app.autostart.disable()
    removed = app.client.get("/api/settings").json()["autostart"]["state"]
    again = app.client.get("/api/settings").json()["autostart"]["state"]
    [outside] = history_rows(app)
    undone = app.client.post(f"/api/settings/history/{outside['id']}/undo")

    assert (installed, rows_after_install) == ("on", [])
    assert (removed, again) == ("off", "off")
    assert (outside["source"], outside["changes"], outside["undoable"], outside["removed"]) == (
        "outside",
        [AUTOSTART_OFF],
        True,
        False,
    )
    assert (undone.json()["settings"]["autostart"]["state"], [path.name for path in app.autostart.folder.iterdir()]) == (
        "on",
        [SHORTCUT_FILE],
    )
    assert "ustawienia-spoza plik=autostart wynik=zapisano" in app.log_path.read_text(encoding="utf-8")


def test_wlaczenie_autostartu_ktorego_wiersza_historii_nie_da_sie_dopisac_nie_zostawia_skrotu(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.client.get("/api/settings")
    history = app.tool.config / HISTORY_FILE
    history.mkdir(parents=True)

    refused = autostart(app, True)
    history.rmdir()

    assert (refused.status_code, refused.json()) == (500, {"message": AUTOSTART_NOT_CHANGED})
    assert (list(app.autostart.folder.iterdir()), app.client.get("/api/settings").json()["autostart"]) == ([], AUTOSTART_SHOWN_OFF)
    assert history_rows(app) == []


def test_skrot_autostartu_ktorego_system_nie_daje_zalozyc_zostawia_stan_bez_zmiany_i_bez_wiersza(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.autostart.failure = PermissionError(errno.EACCES, "Odmowa dostępu")

    refused = autostart(app, True)
    app.autostart.failure = None

    assert (refused.status_code, refused.json()) == (500, {"message": AUTOSTART_NOT_CHANGED})
    assert (app.client.get("/api/settings").json()["autostart"], history_rows(app)) == (AUTOSTART_SHOWN_OFF, [])


def test_folder_autostartu_ktorego_nie_da_sie_sprawdzic_to_zdanie_przy_przelaczniku_a_nie_skrot_usuniety(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    autostart(app, True)
    app.autostart.unreadable = True

    shown = app.client.get("/api/settings").json()["autostart"]
    refused = autostart(app, False)
    app.autostart.unreadable = False

    assert shown == {"state": "unreadable", "reason": AUTOSTART_UNREADABLE}
    assert (refused.status_code, refused.json()) == (500, {"message": AUTOSTART_NOT_CHANGED})
    assert ([path.name for path in app.autostart.folder.iterdir()], len(history_rows(app))) == ([SHORTCUT_FILE], 1)


class PowerShellWithCodePage1252:
    """PowerShell z WScript.Shell na Windows ze stroną kodową ANSI 1252 (angielski Windows, runner CI): zapisuje skrót
    pod nazwą przepuszczoną przez tę stronę kodową, w której nie ma „ń”, więc ``ń`` zostaje ``n``.

    ``takes_s``: tyle sekund PowerShell pisze skrót; dłużej niż limit czasu wołającego to ``TimeoutExpired`` jak w
    ``platform.run_console_program``, po zapisaniu skrótu. ``exit_code``: kod wyjścia PowerShella po zapisaniu skrótu,
    np. 1, gdy ``Save()`` zapisał część pliku i padł.
    """

    def __init__(self) -> None:
        self.takes_s = 1.0
        self.exit_code = 0

    def __call__(
        self, command: Sequence[str], *, timeout_s: float, cwd: Path | None = None, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        assert env is not None
        link = Path(env["CENTRUM_SKROT_PLIK"])
        in_code_page = unicodedata.normalize("NFKD", link.name).encode("cp1252", errors="ignore").decode("cp1252")
        (link.parent / in_code_page).write_bytes(b"skrot")
        if self.takes_s > timeout_s:
            raise subprocess.TimeoutExpired(list(command), timeout_s)
        return subprocess.CompletedProcess(list(command), self.exit_code, "", "")


def startup_shortcut(tmp_path: Path, powershell: PowerShellWithCodePage1252) -> tuple[CentrumClient, Path]:
    folder, windowless_python = tmp_path / "autostart", tmp_path / "pythonw.exe"
    folder.mkdir()
    windowless_python.write_bytes(b"")
    autostart = StartupShortcut(folder, program=windowless_python, run=powershell)
    return CentrumClient(centrum_app(ToolDirectory(tmp_path), autostart=autostart)), folder


def test_przelacznik_autostartu_zaklada_skrot_centrum_rozliczen_lnk_takze_gdy_strona_kodowa_windows_nie_ma_litery_n(
    tmp_path: Path,
) -> None:
    client, folder = startup_shortcut(tmp_path, PowerShellWithCodePage1252())

    enabled = client.put("/api/settings/autostart", json={"enabled": True})
    after_enable = sorted(path.name for path in folder.iterdir())
    disabled = client.put("/api/settings/autostart", json={"enabled": False})

    assert (enabled.status_code, enabled.json()["settings"]["autostart"]["state"]) == (200, "on"), enabled.text
    assert after_enable == ["Centrum rozliczeń.lnk"]
    assert (disabled.json()["settings"]["autostart"]["state"], list(folder.iterdir())) == ("off", [])


def test_powershell_ktory_nie_zapisze_skrotu_w_limicie_czasu_to_odmowa_bez_skrotu_a_ustawienia_dalej_odpowiadaja(
    tmp_path: Path,
) -> None:
    powershell = PowerShellWithCodePage1252()
    client, folder = startup_shortcut(tmp_path, powershell)
    powershell.takes_s = 60  # zawieszony na minutę, a blokada Ustawień nie czeka tyle

    refused = client.put("/api/settings/autostart", json={"enabled": True})
    powershell.takes_s = 1.0
    after_refusal = list(folder.iterdir())
    shown = client.get("/api/settings").json()["autostart"]
    enabled = client.put("/api/settings/autostart", json={"enabled": True})

    assert (refused.status_code, refused.json()) == (500, {"message": AUTOSTART_NOT_CHANGED})
    assert (shown, after_refusal) == (AUTOSTART_SHOWN_OFF, [])
    assert enabled.json()["settings"]["autostart"]["state"] == "on"
    assert [path.name for path in folder.iterdir()] == ["Centrum rozliczeń.lnk"]


def test_powershell_ktory_skonczy_bledem_po_zapisaniu_czesci_skrotu_to_odmowa_bez_skrotu_w_autostarcie(tmp_path: Path) -> None:
    powershell = PowerShellWithCodePage1252()
    client, folder = startup_shortcut(tmp_path, powershell)
    powershell.exit_code = 1

    refused = client.put("/api/settings/autostart", json={"enabled": True})

    assert (refused.status_code, refused.json()) == (500, {"message": AUTOSTART_NOT_CHANGED})
    assert (client.get("/api/settings").json()["autostart"], list(folder.iterdir())) == (AUTOSTART_SHOWN_OFF, [])


def test_plik_przerwanego_zapisu_skrotu_nie_zostaje_w_autostarcie_przy_przelaczniku_wylaczonym(tmp_path: Path) -> None:
    """Centrum zgasło w trakcie PowerShella, który potem dokończył zapis pod nazwą pośrednią: Windows uruchomiłby z
    niego Centrum po zalogowaniu, choć przełącznik mówi „off”."""

    client, folder = startup_shortcut(tmp_path, PowerShellWithCodePage1252())
    client.put("/api/settings/autostart", json={"enabled": True})
    client.put("/api/settings/autostart", json={"enabled": False})
    (folder / "Centrum rozliczen (zapis).lnk").write_bytes(b"skrot")

    shown = client.get("/api/settings").json()["autostart"]

    assert (shown, list(folder.iterdir())) == (AUTOSTART_SHOWN_OFF, [])
    assert [row["source"] for row in client.get("/api/settings/history").json()["rows"]] == ["tata", "tata"]


@pytest.mark.skipif(sys.platform == "win32", reason="Autostart Windows jest tylko na Windows; tu komputer bez niego.")
def test_na_komputerze_bez_windows_przelacznik_autostartu_jest_nieaktywny_z_jednym_zdaniem(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    client = CentrumClient(centrum_app(tool, autostart=system_autostart()))

    shown = client.get("/api/settings").json()["autostart"]
    refused = client.put("/api/settings/autostart", json={"enabled": True})
    history = client.get("/api/settings/history").json()

    assert shown == {"state": "unsupported", "reason": AUTOSTART_UNSUPPORTED}
    assert (refused.status_code, refused.json()) == (422, {"message": AUTOSTART_UNSUPPORTED, "field": "autostart"})
    assert (history["rows"], (tool.config / MEMORY_DIRECTORY / "autostart.json").exists()) == ([], False)


# --- Hasło skrzynki raportów (#1469): pole bez starego hasła, jedna próba logowania, Historia bez wartości -------------

SKRZYNKA = "raporty@przyklad.invalid"
STARE_HASLO = "stare haslo maksa"
NOWE_HASLO = "nowe haslo taty"
"""Hasło aplikacji tak, jak je wpisuje tata (Google pokazuje je w czwórkach ze spacjami); plik dostaje je bez spacji."""


def _inbox_centrum(tmp_path: Path, imap: AtrapaImap | None = None) -> tuple[CentrumClient, ToolDirectory]:
    """Centrum z plikiem skrzynki napisanym przez Maksa w Notatniku (BOM UTF-8, CRLF); bez ``imap`` skrzynka bez sieci."""

    tool = ToolDirectory(tmp_path)
    tool.config.mkdir(parents=True, exist_ok=True)
    (tool.config / INBOX_ACCESS_FILE).write_bytes(f"{SKRZYNKA}\r\n{STARE_HASLO}\r\n".encode("utf-8-sig"))
    if imap is None:
        return CentrumClient(centrum_app(tool)), tool
    return CentrumClient(centrum_app(tool, inbox_connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port))), tool


def _files_with_password(tool: ToolDirectory, passwords: Sequence[str]) -> list[str]:
    """Pliki katalogu narzędzia poza plikiem skrzynki, w których jest któreś z ``passwords`` otwartym tekstem.

    Hasło szuka się też bez spacji, bo tak trafia do pliku skrzynki; rekurencyjnie, więc i w pamięci odrzuconych.
    """

    secrets = {form.encode() for password in passwords for form in (password, password.replace(" ", ""))}
    access = tool.config / INBOX_ACCESS_FILE
    files = [path for path in sorted(tool.root.rglob("*")) if path.is_file() and path != access]
    return [path.relative_to(tool.root).as_posix() for path in files if any(secret in path.read_bytes() for secret in secrets)]


@pytest.mark.parametrize(
    ("haslo_skrzynki", "zerwanie", "wynik", "polecenia"),
    [
        (NOWE_HASLO.replace(" ", ""), None, "accepted", ["LOGIN", "LOGOUT"]),
        ("inne haslo w gmailu", None, "rejected", ["LOGIN", "LOGOUT"]),
        (NOWE_HASLO.replace(" ", ""), "greeting", "no_network", []),
    ],
    ids=["przyjete", "odrzucone", "brak-sieci"],
)
def test_nowe_haslo_skrzynki_zastepuje_tylko_linie_hasla_a_jedna_proba_logowania_mowi_czy_skrzynka_je_przyjela(
    tmp_path: Path, haslo_skrzynki: str, zerwanie: Literal["greeting"] | None, wynik: str, polecenia: list[str]
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=haslo_skrzynki, cut=zerwanie) as imap:
        client, tool = _inbox_centrum(tmp_path, imap)
        saved = client.put("/api/settings/inbox-password", json={"password": NOWE_HASLO})
        # ``imaplib`` 3.11 pyta o ``CAPABILITY`` osobno, a 3.14 bierze je z powitania: to nie decyzja portu.
        commands = [command for command in imap.commands if command != "CAPABILITY"]

    assert (saved.status_code, saved.json()["login"]) == (200, wynik)
    assert commands == polecenia
    assert saved.json()["settings"]["inbox"] == {"address": SKRZYNKA, "password": True}
    assert (tool.config / INBOX_ACCESS_FILE).read_bytes() == f"{SKRZYNKA}\r\nnowehaslotaty\r\n".encode("utf-8-sig")


def test_haslo_skrzynki_nie_wychodzi_w_odpowiedzi_historii_logach_ani_pamieci_a_historia_ma_wiersz_bez_cofniecia(
    tmp_path: Path,
) -> None:
    client, tool = _inbox_centrum(tmp_path)
    shown = client.get("/api/settings")

    saved = client.put("/api/settings/inbox-password", json={"password": NOWE_HASLO})
    again = client.put("/api/settings/inbox-password", json={"password": NOWE_HASLO})
    read = client.get("/api/settings")
    history = client.get("/api/settings/history")
    [row] = history.json()["rows"]
    undo = client.post(f"/api/settings/history/{row['id']}/undo")
    client.stop()

    assert (saved.json()["login"], saved.json()["change"], again.json()["change"]) == ("no_network", row["id"], None)
    assert (row["source"], row["section"], row["secret"], row["undoable"]) == ("tata", "skrzynka", True, False)
    assert row["changes"] == [{"key": "skrzynka.haslo", "before": None, "after": None}]
    assert undo.status_code == 404
    responses = [shown, saved, again, read, history, undo]
    secrets = [secret for value in (STARE_HASLO, NOWE_HASLO) for secret in (value, value.replace(" ", ""))]
    assert [secret for secret in secrets for response in responses if secret.encode() in response.content] == []
    assert _files_with_password(tool, [STARE_HASLO, NOWE_HASLO]) == []
    assert tool.log_path.is_file()
    # Pamięć zapisuje bajty jako base64, którego `_files_with_password` nie rozpozna, więc sam odcisk sprawdza się wprost.
    remembered = json.loads((tool.config / MEMORY_DIRECTORY / f"{INBOX_ACCESS_FILE}.json").read_bytes())
    access = (tool.config / INBOX_ACCESS_FILE).read_bytes()
    assert (base64.urlsafe_b64decode(remembered["widziany"]), remembered["dobry"]) == (hashlib.sha256(access).digest(), None)


def test_zmiana_pliku_skrzynki_spoza_centrum_ma_wiersz_bez_wartosci(tmp_path: Path) -> None:
    client, tool = _inbox_centrum(tmp_path)
    client.get("/api/settings")
    (tool.config / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\nhaslo od maksa\n", encoding="utf-8")

    rows = client.get("/api/settings/history").json()["rows"]
    again = client.get("/api/settings/history").json()["rows"]

    assert [(row["source"], row["changes"], row["secret"], row["undoable"]) for row in rows] == [
        ("outside", [{"key": "skrzynka.dostep", "before": None, "after": None}], True, False)
    ]
    assert again == rows
    assert b"haslo" not in client.get("/api/settings/history").content


@pytest.mark.parametrize(
    ("plik", "haslo", "pole"),
    [
        (f"{SKRZYNKA}\r\n{STARE_HASLO}\r\n", "   ", "haslo"),
        (f"{SKRZYNKA}\r\n{STARE_HASLO}\r\n", "hasło taty", "haslo"),
        ("\r\n\r\n", NOWE_HASLO, "adres"),
        (None, NOWE_HASLO, "adres"),
    ],
    ids=["puste", "polskie-znaki", "plik-bez-adresu", "bez-pliku"],
)
def test_haslo_ktorego_skrzynka_nie_uzyje_jest_odmowa_przy_polu_bez_zapisu_i_bez_logowania(
    tmp_path: Path, plik: str | None, haslo: str, pole: str
) -> None:
    client, tool = _inbox_centrum(tmp_path)
    access = tool.config / INBOX_ACCESS_FILE
    if plik is None:
        access.unlink()
    else:
        access.write_text(plik, encoding="utf-8")
    before = access.read_bytes() if plik is not None else None

    refused = client.put("/api/settings/inbox-password", json={"password": haslo})

    assert (refused.status_code, refused.json()["field"]) == (422, pole)
    assert (access.read_bytes() if access.exists() else None) == before
    assert client.get("/api/settings/history").json()["rows"] == []


ZLE_ADRES = "Adres skrzynki raportów w pliku skrzynka-raportow.txt jest zły. Poprawia go Maks."
ZLE_HASLO = "Hasło aplikacji ma tylko litery i cyfry, bez polskich znaków."
NIE_TEKST = "Plik skrzynka-raportow.txt w folderze config nie jest tekstem. Poproś Maksa o nowy plik."


@pytest.mark.parametrize(
    ("plik", "skrzynka", "problem", "zapis"),
    [
        (
            f"{SKRZYNKA}\r\nstarehasło\r\n".encode("utf-8-sig"),
            {"address": SKRZYNKA, "password": True},
            {"field": "haslo", "message": ZLE_HASLO},
            f"{SKRZYNKA}\r\nnowehaslotaty\r\n".encode("utf-8-sig"),
        ),
        (
            f"Skrzynka <{SKRZYNKA}>\r\n{STARE_HASLO}\r\n".encode(),
            {"address": None, "password": True},
            {"field": "adres", "message": ZLE_ADRES},
            None,
        ),
        (b"\xff\xfe\x00\xd8", {"address": None, "password": False}, {"field": None, "message": NIE_TEKST}, None),
    ],
    ids=["zle-stare-haslo", "zly-adres", "nie-tekst"],
)
def test_zly_plik_skrzynki_ma_zdanie_w_ustawieniach_a_nowe_haslo_taty_naprawia_tylko_zle_stare_haslo(
    tmp_path: Path, plik: bytes, skrzynka: dict[str, object], problem: dict[str, object], zapis: bytes | None
) -> None:
    client, tool = _inbox_centrum(tmp_path)
    access = tool.config / INBOX_ACCESS_FILE
    access.write_bytes(plik)

    shown = client.get("/api/settings").json()
    put = client.put("/api/settings/inbox-password", json={"password": NOWE_HASLO})
    rows = client.get("/api/settings/history").json()["rows"]

    assert (shown["inbox"], shown["inbox_problem"]) == (skrzynka, problem)
    if zapis is None:
        refused = put.json()
        assert (put.status_code, refused.get("field"), refused["message"]) == (422, problem["field"], problem["message"])
        assert (access.read_bytes(), rows) == (plik, [])
    else:
        assert (put.status_code, put.json()["settings"]["inbox"], put.json()["settings"]["inbox_problem"]) == (
            200,
            {"address": SKRZYNKA, "password": True},
            None,
        )
        assert access.read_bytes() == zapis
        assert [change["key"] for row in rows for change in row["changes"]] == ["skrzynka.haslo"]
    assert _files_with_password(tool, ["starehasło", STARE_HASLO, NOWE_HASLO]) == []


@pytest.mark.parametrize(
    ("plik", "zapis"),
    [
        (f"{SKRZYNKA}\nstare\n# notatka maksa\n".encode(), f"{SKRZYNKA}\nnowehaslotaty\n# notatka maksa\n".encode()),
        (f"{SKRZYNKA}\r\nstare\r\n".encode("utf-16"), f"{SKRZYNKA}\r\nnowehaslotaty\r\n".encode()),
    ],
    ids=["lf-i-dalsze-linie", "utf-16"],
)
def test_nowe_haslo_zostawia_znak_konca_linii_i_dalsze_linie_pliku_maksa(tmp_path: Path, plik: bytes, zapis: bytes) -> None:
    client, tool = _inbox_centrum(tmp_path)
    access = tool.config / INBOX_ACCESS_FILE
    access.write_bytes(plik)

    put = client.put("/api/settings/inbox-password", json={"password": NOWE_HASLO})

    assert (put.status_code, access.read_bytes()) == (200, zapis)


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

    root = dad_layout(tmp_path)
    app = centrum(tmp_path)
    app.platform.chosen_folders.append(root if chosen_month is None else inea(root, chosen_month))
    app.client.post("/api/settings/periods-directory/choose")
    return app, root


def dad_layout(tmp_path: Path) -> Path:
    """Układ folderów taty ``Załączniki``: Rozliczenia {rok}\\{miesiąc}\\INEA z folderem obok miesięcy."""

    root = tmp_path / "Załączniki"
    for month in ("12_Grudzień_2025",):
        (root / "Rozliczenia 2025" / month / "INEA").mkdir(parents=True)
    for month in ("09_Wrzesień_2026", "10_Październik_2026", "11_Listopad_2026"):
        (root / "Rozliczenia 2026" / month / "INEA").mkdir(parents=True)
    (root / "Rozliczenia 2026" / "Nowe rozliczenia wzór od 01_2026" / "Podpisane").mkdir(parents=True)
    return root


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


# Folder wskazany w środku układu folderów taty, względem ``Załączniki`` (#1472).
INSIDE_DAD_LAYOUT = [
    pytest.param(("Rozliczenia 2026", "11_Listopad_2026", "INEA", "27_02_11_2026"), id="tydzien"),
    pytest.param(("Rozliczenia 2026", "10_Październik_2026", "INEA"), id="inea-miesiaca"),
    pytest.param(("Rozliczenia 2026", "10_Październik_2026"), id="miesiac"),
    pytest.param(("Rozliczenia 2025",), id="rok"),
]


def choose_periods_directory(app: Centrum, folder: Path, way: str) -> dict[str, Any]:
    """Ustawienia po wskazaniu ``folder`` oknem wyboru (``okno``) albo ścieżką wpisaną w sekcji Foldery (``wpisana``)."""

    if way == "okno":
        app.platform.chosen_folders.append(folder)
        response = app.client.post("/api/settings/periods-directory/choose")
    else:
        response = app.client.put("/api/settings/folders", json={"order_register": None, "periods_directory": str(folder)})
    assert response.status_code == 200
    return dict(response.json()["settings"])


@pytest.mark.parametrize("way", ["okno", "wpisana"])
@pytest.mark.parametrize("inside", INSIDE_DAD_LAYOUT)
def test_folder_wskazany_w_srodku_ukladu_folderow_taty_zapisuje_sie_jako_zalaczniki_wszystkich_lat(
    tmp_path: Path, inside: tuple[str, ...], way: str
) -> None:
    root = dad_layout(tmp_path)
    pointed = root.joinpath(*inside)
    pointed.mkdir(exist_ok=True)
    app = centrum(tmp_path)

    settings = choose_periods_directory(app, pointed, way)
    [row] = app.client.get("/api/settings/history").json()["rows"]
    after_restart = centrum(tmp_path).client.get("/api/settings").json()

    assert (settings["periods_directory"], settings["periods_all_years"]) == (
        {"state": "ready", "path": str(root), "name": "Załączniki"},
        True,
    )
    assert after_restart == settings
    assert row["changes"] == [{"key": "foldery.folder_okresow", "before": None, "after": str(root)}]


@pytest.mark.parametrize("way", ["okno", "wpisana"])
@pytest.mark.parametrize("inside", [(), ("22_28_09_2026",)], ids=["folder-okresow", "folder-okresu"])
def test_folder_wskazany_w_ukladzie_plaskim_zapisuje_sie_taki_jak_wskazany(
    tmp_path: Path, inside: tuple[str, ...], way: str
) -> None:
    periods = tmp_path / "INEA"
    periods.mkdir()
    write_period_files(periods, "22_28_09_2026")
    pointed = periods.joinpath(*inside)
    app = centrum(tmp_path)

    settings = choose_periods_directory(app, pointed, way)

    assert (settings["periods_directory"], settings["periods_all_years"]) == (
        {"state": "ready", "path": str(pointed), "name": pointed.name},
        False,
    )


@NO_ACCESS_ON_WINDOWS
@pytest.mark.parametrize("way", ["okno", "wpisana"])
def test_folder_bez_dostepu_wskazany_w_srodku_ukladu_zapisuje_sie_taki_jak_wskazany(tmp_path: Path, way: str) -> None:
    """Układu nad folderem bez dostępu nie widać, więc zapisuje się wskazany folder, a nie błąd wyboru."""

    root = dad_layout(tmp_path)
    week = inea(root, "11_Listopad_2026") / "27_02_11_2026"
    week.mkdir()
    app = centrum(tmp_path)

    with without_access(week):
        settings = choose_periods_directory(app, week, way)

    assert settings["periods_directory"]["path"] == str(week)


def test_rejestr_zmieniony_w_sekcji_foldery_zostawia_folder_okresow_cofniety_do_tygodnia(tmp_path: Path) -> None:
    """Formularz sekcji odsyła obie ścieżki, więc zapisany już folder okresów zostaje, nawet w środku układu."""

    root = dad_layout(tmp_path)
    week = inea(root, "11_Listopad_2026") / "27_02_11_2026"
    week.mkdir()
    register = tmp_path / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    register.touch()
    app = centrum(tmp_path)
    write_folder_settings(app.tool, FolderSettings(periods_directory=week))

    settings = app.client.put(
        "/api/settings/folders", json={"order_register": str(register), "periods_directory": str(week)}
    ).json()["settings"]

    assert (settings["order_register"]["path"], settings["periods_directory"]["path"]) == (str(register), str(week))


def write_folder_settings(tool: ToolDirectory, folders: FolderSettings) -> None:
    """Plik Ustawień Centrum zapisany przed Wydaniem, np. z folderem okresów wskazanym w środku układu."""

    tool.settings.parent.mkdir(parents=True, exist_ok=True)
    tool.settings.write_text(FOLDERS.dump(folders), encoding="utf-8")


PERIODS_FROM_ATTACHMENTS = "2026-11-folder-okresow-od-zalacznikow"


@pytest.mark.parametrize("inside", [*INSIDE_DAD_LAYOUT[:3], pytest.param(None, id="tydzien-przeniesiony")])
def test_folder_okresow_zapisany_w_srodku_ukladu_zamienia_sie_raz_na_zalaczniki_jako_zmiana_z_wydania_z_cofnij(
    tmp_path: Path, inside: tuple[str, ...] | None
) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    freshness = ToolFreshness.of_clone(repository.clone, repository.github_releases, repository.published)
    root = dad_layout(tmp_path)
    saved = inea(root, "11_Listopad_2026") / "27_02_11_2026" if inside is None else root.joinpath(*inside)
    if inside is not None:
        saved.mkdir(exist_ok=True)
    tool = ToolDirectory(tmp_path / "narzedzie-taty")
    write_folder_settings(tool, FolderSettings(periods_directory=saved))

    first = started(tool, RELEASE_CHANGES, tool_freshness=freshness)
    [applied] = first.get("/api/settings/history").json()["rows"]
    periods = first.get("/api/settings").json()["periods_directory"]
    first.stop()
    after_update = config_bytes(tool.config)
    second = started(tool, RELEASE_CHANGES, tool_freshness=freshness)
    second.stop()
    unchanged = config_bytes(tool.config)
    third = started(tool, RELEASE_CHANGES, tool_freshness=freshness)
    undone = third.post(f"/api/settings/history/{applied['id']}/undo").json()["settings"]["periods_directory"]
    third.stop()
    fourth = started(tool, RELEASE_CHANGES, tool_freshness=freshness)
    after_undo = fourth.get("/api/settings").json()["periods_directory"]
    rows = fourth.get("/api/settings/history").json()["rows"]
    fourth.stop()

    assert periods == {"state": "ready", "path": str(root), "name": "Załączniki"}
    assert (applied["source"], applied["release"], applied["changes"], applied["undoable"]) == (
        "release",
        {"version": "0.1.0", "commit": repository.head()[:7], "change": PERIODS_FROM_ATTACHMENTS},
        [{"key": "foldery.folder_okresow", "before": str(saved), "after": str(root)}],
        True,
    )
    assert unchanged == after_update
    assert (undone["path"], after_undo["path"]) == (str(saved), str(saved))
    assert [row["source"] for row in rows] == ["tata", "release"]


@pytest.mark.parametrize(
    "saved",
    [
        pytest.param(("Załączniki",), id="zalaczniki"),
        pytest.param(("INEA",), id="uklad-plaski"),
        pytest.param(("INEA", "22_28_09_2026"), id="folder-okresu-w-ukladzie-plaskim"),
        pytest.param(None, id="nie-wskazano"),
    ],
)
def test_folder_okresow_od_korzenia_ukladu_zostaje_po_aktualizacji_bez_wiersza_i_bez_zmiany_pliku(
    tmp_path: Path, saved: tuple[str, ...] | None
) -> None:
    dad_layout(tmp_path)
    (tmp_path / "INEA" / "22_28_09_2026").mkdir(parents=True)
    tool = ToolDirectory(tmp_path / "narzedzie-taty")
    write_folder_settings(tool, FolderSettings(periods_directory=None if saved is None else tmp_path.joinpath(*saved)))
    before = tool.settings.read_bytes()

    started(tool, RELEASE_CHANGES).stop()
    again = started(tool, RELEASE_CHANGES)
    rows = again.get("/api/settings/history").json()["rows"]
    again.stop()

    assert (tool.settings.read_bytes(), rows) == (before, [])
    assert tool.log_path.read_text(encoding="utf-8").count(f"zmiana={PERIODS_FROM_ATTACHMENTS} wynik=bez-zmian") == 1


@pytest.mark.parametrize(
    "obstacle", [pytest.param("bez-dostepu", marks=NO_ACCESS_ON_WINDOWS), "onedrive-nie-oddal-zalacznikow"]
)
def test_folder_okresow_nieczytelny_przy_starcie_po_aktualizacji_zamienia_sie_na_zalaczniki_przy_nastepnym(
    tmp_path: Path, obstacle: str
) -> None:
    """Folder bez dostępu albo folder, którego nie ma, a nad nim nie widać układu: zmiana czeka, a nie kończy się
    „nic do zmiany”, bo wtedy tydzień zostałby zapisany na zawsze."""

    root = tmp_path / "Załączniki"
    month = inea(root, "10_Październik_2026")
    tool = ToolDirectory(tmp_path / "narzedzie-taty")
    write_folder_settings(tool, FolderSettings(periods_directory=month))

    if obstacle == "bez-dostepu":
        dad_layout(tmp_path)
        with without_access(root):
            started(tool, RELEASE_CHANGES).stop()
    else:
        started(tool, RELEASE_CHANGES).stop()
        dad_layout(tmp_path)
    later = tool.settings.read_bytes()
    again = started(tool, RELEASE_CHANGES)
    periods = again.get("/api/settings").json()["periods_directory"]
    again.stop()

    assert FOLDERS.parse(later) == FolderSettings(periods_directory=month)
    assert periods["path"] == str(root)
    assert f"zmiana={PERIODS_FROM_ATTACHMENTS} wynik=pozniej" in tool.log_path.read_text(encoding="utf-8")


def test_zly_plik_ustawien_z_tygodniem_zostaje_po_aktualizacji_bajt_w_bajt_a_zmiana_wchodzi_po_naprawie(
    tmp_path: Path,
) -> None:
    """Przy złym pliku Centrum zna ostatnią dobrą wartość, ale zmiana z Wydania nie nadpisuje nią pliku taty."""

    root = dad_layout(tmp_path)
    week = inea(root, "11_Listopad_2026") / "27_02_11_2026"
    week.mkdir()
    tool = ToolDirectory(tmp_path / "narzedzie-taty")
    write_folder_settings(tool, FolderSettings(periods_directory=week))
    started(tool, ()).stop()
    bad = FOLDERS.dump(FolderSettings(periods_directory=week)) + "nieznany_klucz: 1\n"
    tool.settings.write_text(bad, encoding="utf-8")

    while_bad = started(tool, RELEASE_CHANGES)
    problem = while_bad.get("/api/settings").json()["folders_problem"]
    while_bad.stop()
    after_bad = tool.settings.read_text(encoding="utf-8")
    write_folder_settings(tool, FolderSettings(periods_directory=week))
    repaired = started(tool, RELEASE_CHANGES)
    periods = repaired.get("/api/settings").json()["periods_directory"]
    repaired.stop()

    assert problem is not None
    assert after_bad == bad
    assert f"zmiana={PERIODS_FROM_ATTACHMENTS} wynik=pozniej" in tool.log_path.read_text(encoding="utf-8")
    assert periods["path"] == str(root)


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
    app = centrum(tmp_path)
    write_folder_settings(app.tool, FolderSettings(periods_directory=periods))  # zapis sprzed #1472, w środku układu

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
