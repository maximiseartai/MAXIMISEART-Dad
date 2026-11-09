"""Centrum rozliczeń przez jego HTTP API, tak jak widzi je przeglądarka taty."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any, get_args

from fastapi.testclient import TestClient
import pytest

from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import collective_file_name_with
from rozliczenia.period_folder import PeriodFolder
from rozliczenia import efenix_process
from rozliczenia.centrum import app
from rozliczenia.centrum.app import STATIC_DIRECTORY
from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, OLD_NOTES_FILE, OLD_REPORTS_FILE
from rozliczenia.centrum.notifications import NOTIFICATIONS_FILE
from rozliczenia.centrum.outbox import ADDRESSES_FILE, QUEUE_DIRECTORY
from rozliczenia.centrum.keyed_box import REPORT_KEY_FILE
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY
from rozliczenia.centrum.run_origins import CENTRUM_RUNS_FILE
from rozliczenia.telemetry import CompletedResult, MetricsStore, RecordedStop, metric_record
from rozliczenia.tool_files import LOG_PATH, SETTINGS
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.settings import Settings, SettingsStore
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS, without_access
from tests.fixtures.centrum import (
    CENTRUM,
    TOOL_COMMIT,
    Centrum,
    ROOT,
    centrum,
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


def _exported_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Kontrakt OpenAPI, który eksportuje ``tools/ci/export_openapi.py`` z bieżącego kodu serwera."""

    monkeypatch.setattr(export_openapi, "OUTPUT", tmp_path / "openapi.json")
    assert export_openapi.main() == 0
    return dict(json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8")))


def test_kontrakt_ma_trasy_i_schematy_po_kolei_wiec_dwie_nowe_trasy_nie_zmieniaja_tego_samego_miejsca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _exported_contract(tmp_path, monkeypatch)
    schemas = contract["components"]["schemas"]

    assert (list(contract["paths"]), list(schemas)) == (sorted(contract["paths"]), sorted(schemas))


def test_frontend_parsuje_odpowiedzi_kontraktem_ktory_serwer_naprawde_eksportuje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frontend parsuje każdą odpowiedź serwera schematami wygenerowanymi z ``frontend/src/api/openapi.json``."""

    committed = json.loads((ROOT / "frontend" / "src" / "api" / "openapi.json").read_text(encoding="utf-8"))

    assert _exported_contract(tmp_path, monkeypatch) == committed


# Trasy, których przeglądarka nie mierzy przez `call` (frontend/src/api/client.ts), każda z powodem.
OUTSIDE_TIMING = {
    "streamRunEvents": "strumień SSE (EventSource) otwarty przez całe życie karty, nie zapytanie z odpowiedzią",
    "recordViewTiming": "sam pomiar widoku, wysyłany po pomiarze; odpowiedź 204 bez treści",
    "getCurrentRun": "przeglądarka bierze bieżące Uruchomienie ze strumienia; trasę czytają testy i weryfikacja",
}


def test_kazda_trasa_api_jest_operacja_pomiaru_widoku_albo_ma_powod_poza_pomiarem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ApiOperation`` to dokładnie trasy API poza ``OUTSIDE_TIMING``; dziennik działań taty zapisuje przycisk tylko
    pod operacją z ``ApiOperation``, więc jedyna trasa poza nią, która coś zmienia, to sam pomiar widoku."""

    paths = _exported_contract(tmp_path, monkeypatch)["paths"].values()
    methods = {operation["operationId"]: method for path in paths for method, operation in path.items()}
    listed = get_args(timing_contract.ApiOperation)

    assert sorted(listed) == sorted(methods.keys() - OUTSIDE_TIMING.keys())
    assert len(set(listed)) == len(listed)
    assert OUTSIDE_TIMING.keys() <= methods.keys()
    assert {name for name in OUTSIDE_TIMING if methods[name] != "get"} == {"recordViewTiming"}


def test_zadanie_z_obcym_naglowkiem_host_jest_odrzucone(tmp_path: Path) -> None:
    client = centrum(tmp_path).client

    response = client.get("/api/health", headers={"Host": "zly.example:47811"})

    assert response.status_code == 403
    assert "commit" not in response.text


def test_localhost_jest_dozwolonym_naglowkiem_host(tmp_path: Path) -> None:
    client = centrum(tmp_path).client

    response = client.get("/api/health", headers={"Host": "localhost:47811"})

    assert response.status_code == 200


NOT_SET = {"state": "not_set"}
UNREADABLE = {"state": "unreadable"}


def test_brak_pliku_ustawien_znaczy_nie_ustawiono(tmp_path: Path) -> None:
    response = centrum(tmp_path).client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {"order_register": NOT_SET, "periods_directory": NOT_SET, "theme": "dark"}


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


def test_uszkodzony_plik_ustawien_znaczy_nie_ustawiono(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.settings_path.parent.mkdir(parents=True)
    app.settings_path.write_text("rejestr: [nie zamknięta lista\n", encoding="utf-8")

    response = app.client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {"order_register": NOT_SET, "periods_directory": NOT_SET, "theme": "dark"}


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
        {"order_register": UNREADABLE, "periods_directory": UNREADABLE, "theme": "dark"},
    )


@pytest.mark.parametrize(
    "local_file",
    [
        SETTINGS,
        LOG_PATH,
        SETTINGS.parent / CENTRUM_RUNS_FILE,
        SETTINGS.parent / REPORT_KEY_FILE,
        SETTINGS.parent / DAD_CASES_FILE,
        SETTINGS.parent / OLD_REPORTS_FILE,
        SETTINGS.parent / UNSENT_DIRECTORY / QUEUE_DIRECTORY / "20261024T101500000000Z-0001-zgloszenie-3f2a9c1b.json",
        SETTINGS.parent / OLD_NOTES_FILE,
        SETTINGS.parent / NOTIFICATIONS_FILE,
        SETTINGS.parent / ADDRESSES_FILE,
        SETTINGS.parent / "plik-z-przyszlej-wersji.json",
    ],
    ids=[
        "ustawienia-taty",
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
    path = tmp_path / "config" / "ustawienia.yaml"
    pauses: list[float] = []

    def access_back(seconds: float) -> None:
        pauses.append(seconds)
        path.chmod(0o644)

    store = SettingsStore(path, log=CentrumLog(tmp_path / "dziennik.log"), pause=access_back)
    store.update(periods_directory=tmp_path / "INEA")
    path.chmod(0)
    try:
        updated = store.update(theme="light")
    finally:
        path.chmod(0o644)

    assert updated == store.load() == Settings(periods_directory=tmp_path / "INEA", theme="light")
    assert len(pauses) == 1


def test_akcja_zmieniajaca_stan_wymaga_origin_centrum(tmp_path: Path) -> None:
    client = centrum(tmp_path).client

    foreign = client.put("/api/settings/theme", json={"theme": "light"}, headers={"Origin": "http://zly.example"})
    other_port = client.put(
        "/api/settings/theme", json={"theme": "light"}, headers={"Origin": "http://127.0.0.1:3000"}
    )

    assert (foreign.status_code, other_port.status_code) == (403, 403)
    assert client.get("/api/settings").json()["theme"] == "dark"


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
    """Pliki okresu ``row`` z Tablicy okresów po miejscu (``target``)."""

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


def test_otwieranie_bez_wskazanego_folderu_okresow_prosi_o_jego_wskazanie(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/periods/22_28_09_2026/open", json={"target": "period_folder"})

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


def test_otwieranie_rozliczenia_pracownika_bez_wskazanego_folderu_okresow_prosi_o_jego_wskazanie(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/periods/22_28_09_2026/worker-settlements/open", json={"worker": "Anna Testowa"})

    assert (response.status_code, response.json()) == (409, {"message": "Najpierw wskaż folder okresów."})
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


def test_zamkniecie_centrum_z_obcej_strony_jest_odrzucone(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/shutdown", headers={"Origin": "http://zly.example"})

    assert response.status_code == 403
    assert log_lines(app) == []


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
    assert log_lines(app) == ['nieoczekiwany-wyjatek typ=RuntimeError miejsce="POST /api/periods/{token}/open"']
    log = app.log_path.read_text(encoding="utf-8")
    assert "Syntetyczna" not in log and "CENTRUM-SYN-ROW" not in log and str(periods) not in log
