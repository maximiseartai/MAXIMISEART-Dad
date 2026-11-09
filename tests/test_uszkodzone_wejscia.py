"""Uszkodzony plik taty, który czyta Centrum rozliczeń, nie kończy się ogólnym Komunikatem.

Macierz: plik × uszkodzenie × wejście Centrum. Świat taty (Rejestr zleceń, trzy Wzorce, Plik
zbiorczy, Konfiguracja wykonawców, Ustawienia, metryki, dziennik, Logi Uruchomienia i pliki
Zgłoszeń) powstaje raz, a każdy przypadek dostaje jego kopię z jednym uszkodzonym plikiem albo folderem.
Ogólny Komunikat to 500 „nieoczekiwany błąd”, Uruchomienie zakończone nieoczekiwanym wyjątkiem
albo sprawdzenie Diagnozy „nieoczekiwany błąd”. Odmowa 500 z własnym tekstem jest zamierzona.
Plik albo folder bez dostępu jest niedostępny: żaden Komunikat nie nazywa go uszkodzonym ani niepoprawnym.
Wejścia to operacje kontraktu Centrum; operacja spoza macierzy ma w ``NOT_SWEPT`` powód.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from datetime import date, datetime
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import zipfile
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rozliczenia import period_folder
from rozliczenia.centrum.clock import ALARM_THREAD
from rozliczenia.domain import RunMode
from rozliczenia.centrum.github import HttpRequest, HttpResponse
from rozliczenia.centrum.outbox import QUEUE_THREAD
from rozliczenia.centrum.report_box import GitHubReportBox

from tests.fixtures.centrum import (
    CentrumClient,
    FakePlatform,
    ToolDirectory,
    centrum_app,
    finished_view,
    join_threads_since,
)
from tests.fixtures.centrum_processes import Engines
from tests.fixtures.linie_watkow import new_line, threads_since
from atrapy.preparation import PERIOD, write_collective_template, write_internal_template, write_register
from atrapy.settlement import CellValue, write_quantity_source, write_template

TODAY = date(2026, 9, 16)
NOW = datetime(2026, 9, 16, 8, 30)
SETTLEMENT_PERIOD = "01_07_09_2026"
# Wiersze danych Pliku zbiorczego Przebiegu rozliczeń: znane URZĄDZENIA, nieznane (wiersz bez reguły) i prewencja.
HEALTHY_COLLECTIVE_ROWS: tuple[dict[str, CellValue], ...] = (
    {"D": "nokia zte", "G": datetime(2026, 9, 2, 10, 0), "N": 1},
    {"D": "przeniesienie", "G": datetime(2026, 9, 3, 10, 0), "H": "dariusz.fikcyjny2", "N": 2},
    {"D": "prewencja", "G": datetime(2026, 9, 4, 10, 0), "N": 3},
)
# Słowa Komunikatu o zepsutym pliku; plik bez dostępu jest cały i tata nie ma go naprawiać w Excelu.
# Spacja odróżnia je od ścieżek tmp_path, które zawierają nazwę testu.
DAMAGED = (" uszkodzon", " niepoprawn")
WORKER_CONFIG_INACCESSIBLE = "Nie można teraz odczytać konfiguracji wykonawców. Plik może być zajęty przez inny program."
GENERIC_500 = "W Centrum rozliczeń wystąpił nieoczekiwany błąd. Odśwież kartę i spróbuj ponownie."
DIAGNOSIS_UNEXPECTED = "Nie udało się sprawdzić: nieoczekiwany błąd."

TEXT, LINES, XLSX, FOLDER = "tekst", "wiersze", "xlsx", "folder"
# Kopia INTERMAX, którą Konfiguracja wymienia i przywraca: Rejestr zleceń świata sprzed dnia świata.
INTERMAX_COPY = "INTERMAX przed uporządkowaniem 2026-09-15 08-00-00.xlsx"
# Układ folderów taty: Foldery okresu obu procesów w folderze INEA miesiąca.
MONTH = "Załączniki/Rozliczenia 2026/09_Wrzesien_2026"
FILES: dict[str, tuple[str, str]] = {
    "ustawienia": ("config/centrum-ustawienia.yaml", TEXT),
    "konfiguracja_wykonawcow": ("config/worker_mapping.yaml", TEXT),
    "klucz_zgloszen": ("config/zgloszenia-klucz.txt", TEXT),
    "sprawy_taty": ("config/sprawy-taty.json", TEXT),
    "wyslane_zgloszenia": ("config/zgloszenia-wyslane.json", TEXT),
    "uwagi_taty": ("config/uwagi-taty.json", TEXT),
    "przeczytane_powiadomienia": ("config/powiadomienia.json", TEXT),
    "uruchomienia_centrum": ("config/centrum-uruchomienia.jsonl", LINES),
    "adresy_skrzynki": ("config/skrzynka-adresy.jsonl", LINES),
    "dziennik_centrum": ("logs/centrum-rozliczen.log", LINES),
    "logi_uruchomien": ("logs/uruchomienia", FOLDER),
    "metryki_przygotowania": (".przygotowanie-pliku-zbiorczego-metrics.jsonl", LINES),
    "metryki_przebiegu": (".rozliczenia-metrics.jsonl", LINES),
    "metryki_uporzadkowania": (".uporzadkowanie-intermax-metrics.jsonl", LINES),
    "rejestr": ("ZLECENIA INTERMAX OD 08_11_2021.xlsx", XLSX),
    "kopia_intermax": (f"Kopie INTERMAX/{INTERMAX_COPY}", XLSX),
    "folder_kopii_intermax": ("Kopie INTERMAX", FOLDER),
    "wzorzec_wewnetrzny": ("config/Wzorzec rozliczenia wewnętrznego.xlsx", XLSX),
    "wzorzec_zbiorczy": ("config/Wzorzec pliku zbiorczego.xlsx", XLSX),
    "wzorzec_pracownika": ("config/Wzorzec rozliczenia pracownika.xlsx", XLSX),
    "plik_zbiorczy": (f"{MONTH}/INEA/{SETTLEMENT_PERIOD}/Rozliczenie {SETTLEMENT_PERIOD} - zbiorcze.xlsx", XLSX),
    "folder_okresow": ("Załączniki", FOLDER),
    "folder_miesiaca": (MONTH, FOLDER),
    "folder_okresu": (f"{MONTH}/INEA/{SETTLEMENT_PERIOD}", FOLDER),
    "folder_okresu_przygotowania": (f"{MONTH}/INEA/{PERIOD}", FOLDER),
    "folder_zgloszen": ("config/zgloszenia", FOLDER),
}
# Pliki sprzed Spraw taty: Centrum czyta je tylko przy starcie bez pliku Spraw taty, czyli przy pierwszym starcie
# u taty po aktualizacji.
OLD_DAD_CASES = ("wyslane_zgloszenia", "uwagi_taty")
# Pliki, które Centrum czyta raz, przy starcie: przypadek psuje je przed startem Centrum, a nie po nim.
READ_AT_START = ("sprawy_taty", *OLD_DAD_CASES)


def _empty(path: Path) -> None:
    path.write_bytes(b"")


def _bom(path: Path) -> None:
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())


def _ansi(path: Path) -> None:
    path.write_bytes(path.read_text(encoding="utf-8").encode("cp1250"))


def _truncated(path: Path) -> None:
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])


def _torn_last_line(path: Path) -> None:
    data = path.read_bytes().rstrip(b"\n")
    start = data.rfind(b"\n") + 1
    multibyte = next((index for index, byte in enumerate(data[start:]) if byte >= 0xC0), None)
    path.write_bytes(data[: start + (multibyte + 1 if multibyte is not None else max(1, (len(data) - start) // 2))])


def _random_bytes(path: Path) -> None:
    path.write_bytes(random.Random(path.name).randbytes(4096))


def _rewrite_zip(path: Path, change: Callable[[str, bytes], bytes | None]) -> None:
    with zipfile.ZipFile(path) as source:
        entries = [(entry.filename, source.read(entry)) for entry in source.infolist()]
    with zipfile.ZipFile(path, "w") as damaged:
        for name, data in entries:
            changed = change(name, data)
            if changed is not None:
                damaged.writestr(name, changed)


def _truncated_sheet_xml(path: Path) -> None:
    _rewrite_zip(path, lambda name, data: data[: len(data) // 2] if name.startswith("xl/worksheets/") else data)


def _without_sheets(path: Path) -> None:
    _rewrite_zip(path, lambda name, data: None if name.startswith("xl/worksheets/") else data)


def _folder_instead_of_file(path: Path) -> None:
    path.unlink()
    path.mkdir()


def _file_instead_of_folder(path: Path) -> None:
    shutil.rmtree(path)
    path.write_bytes(b"")


def _inaccessible(path: Path) -> None:
    if sys.platform == "win32":  # chmod w Windows zmienia tylko atrybut „tylko do odczytu”
        subprocess.run(["icacls", str(path), "/deny", f"{os.environ['USERNAME']}:(RD)"], check=True, capture_output=True)
    else:
        path.chmod(0)
    with pytest.raises(PermissionError):
        list(path.iterdir()) if path.is_dir() else path.open("rb").close()


def _open_in_excel(path: Path) -> None:
    """Skoroszyt otwarty w Excelu: plik blokady ``~$…`` obok, jak zostawia go Excel taty."""

    path.with_name(f"~${path.name}").write_bytes(b"\x00" * 165)


def _readable_again(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(["icacls", str(path), "/remove:d", os.environ["USERNAME"]], check=True, capture_output=True)
    else:
        path.chmod(0o755)


DAMAGES: dict[str, tuple[tuple[str, ...], Callable[[Path], None]]] = {
    "pusty": ((TEXT, LINES, XLSX), _empty),
    "bom": ((TEXT, LINES), _bom),
    "ansi": ((TEXT, LINES), _ansi),
    "uciety": ((TEXT, LINES, XLSX), _truncated),
    "urwana_linia": ((LINES,), _torn_last_line),
    "losowe_bajty": ((TEXT, LINES, XLSX), _random_bytes),
    "xlsx_uciety_xml": ((XLSX,), _truncated_sheet_xml),
    "zip_bez_arkusza": ((XLSX,), _without_sheets),
    "katalog_zamiast_pliku": ((TEXT, LINES, XLSX), _folder_instead_of_file),
    "plik_zamiast_folderu": ((FOLDER,), _file_instead_of_folder),
    "bez_odczytu": ((TEXT, LINES, XLSX, FOLDER), _inaccessible),
    "otwarty_w_excelu": ((XLSX,), _open_in_excel),
}


@dataclass
class World:
    root: Path

    def path(self, name: str) -> Path:
        return self.root / FILES[name][0]

    @cached_property
    def engines(self) -> Engines:
        return Engines(ToolDirectory(self.root).metrics)

    def app(self) -> FastAPI:
        # Drugie wskazanie dostaje wejście chooseRegister albo choosePeriodsDirectory po _remembering_choices.
        platform = FakePlatform(
            chosen_files=[self.path("rejestr")] * 2, chosen_folders=[self.path("folder_okresow")] * 2
        )
        return centrum_app(
            ToolDirectory(self.root),
            platform=platform,
            today=TODAY,
            now=lambda: NOW,
            catalog=self.engines.catalog(),
            report_box=GitHubReportBox(transport=_offline_like_urllib),
        )

    def client(self) -> CentrumClient:
        return CentrumClient(self.app())


def _remembering_choices(world: World) -> CentrumClient:
    """Centrum, w którym tata wskazał Rejestr zleceń i folder okresów tej kopii świata."""

    client = world.client()
    assert client.post("/api/settings/register/choose").status_code == 200
    assert client.post("/api/settings/periods-directory/choose").status_code == 200
    return client


def _offline_like_urllib(request: HttpRequest) -> HttpResponse:
    for name, value in request.headers.items():
        f"{name}: {value}".encode("latin-1")  # http.client.putheader koduje nagłówki w latin-1
    raise OSError("brak sieci u taty")


def _build(root: Path) -> None:
    world = World(root)
    world.path("folder_okresu").mkdir(parents=True)
    world.path("folder_okresu_przygotowania").mkdir()
    world.path("folder_zgloszen").mkdir(parents=True)
    write_register(world.path("rejestr"))
    world.path("folder_kopii_intermax").mkdir()
    shutil.copyfile(world.path("rejestr"), world.path("kopia_intermax"))
    write_internal_template(world.path("wzorzec_wewnetrzny"))
    write_collective_template(world.path("wzorzec_zbiorczy"))
    write_template(world.path("wzorzec_pracownika"))
    # Plik zbiorczy z nagłówkami Wzorca, więc wejście getQuantitiesToFill przy innym zepsutym pliku czyta zdrowy plik.
    write_quantity_source(world.path("plik_zbiorczy"), HEALTHY_COLLECTIVE_ROWS)
    world.path("konfiguracja_wykonawcow").write_text(
        "# Wykonawcy zespołu z Łodzi\nschema_version: 1\nworkers:\n"
        "  adrian.testowy: Adrian Testowy\n  dariusz.fikcyjny2: Darek Fikcyjny\n  kamil.syntetyczny: Kamil Syntetyczny\n",
        encoding="utf-8",
    )
    world.path("klucz_zgloszen").write_text("github_pat_SYNTETYCZNY123\n", encoding="utf-8")
    # „Wyślij” Uwagi poniżej przenosi sprawy z obu starych plików do pliku Spraw taty.
    world.path("wyslane_zgloszenia").write_text(json.dumps([SENT_REPORT], ensure_ascii=False) + "\n", encoding="utf-8")
    world.path("uwagi_taty").write_text(
        json.dumps({"schema_version": 1, "uwagi": [SENT_DAD_NOTE]}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    world.path("przeczytane_powiadomienia").write_text(
        json.dumps({"schema_version": 1, "przeczytane": [READ_NOTIFICATION]}) + "\n", encoding="utf-8"
    )
    client = _remembering_choices(world)
    assert client.post("/api/dad-notes", json=DAD_NOTE).json() == {"state": "waiting", "waits_for": "internet"}
    assert client.get(f"/api/periods/{SETTLEMENT_PERIOD}/quantities-to-fill").json()["state"] == "ready"
    for process, period in (("preparation", PERIOD), ("settlement", SETTLEMENT_PERIOD)):
        started = client.post("/api/runs", json={"process": process, "period": period, "mode": "DRY-RUN"})
        assert started.status_code == 200, started.json()
        assert finished_view(client)["result"]["ending"] == "finished"
    # Wiersze Rejestru zleceń świata to zlecenia kilku dni bez wyglądu INTERMAX, więc Uporządkowanie INTERMAX zatrzymuje
    # się dla taty bez zapisu; jego Logi i metryki powstają jak po każdym Uruchomieniu.
    assert client.post("/api/intermax/run").status_code == 200
    ordering = finished_view(client)["result"]
    assert (ordering["ending"], ordering["stop_kind"]) == ("stop", "for_tata"), ordering["stops"]
    remembered = world.path("uruchomienia_centrum").read_text(encoding="utf-8").splitlines()
    world.path("adresy_skrzynki").write_text(
        "".join(
            json.dumps({"run_id": json.loads(line)["run_id"], "label": "logi-uruchomienia", "url": url}) + "\n"
            for line, url in zip(remembered, LOGS_COMMENTS, strict=True)
        ),
        encoding="utf-8",
    )
    for name in (
        "metryki_przygotowania",
        "metryki_przebiegu",
        "metryki_uporzadkowania",
        "uruchomienia_centrum",
        "dziennik_centrum",
        "sprawy_taty",
    ):
        assert world.path(name).stat().st_size > 0, name
    assert len(list(world.path("logi_uruchomien").iterdir())) == 3, "Logi Uruchomienia obu podglądów i Uporządkowania"


Problems = list[str]
Seen = list[tuple[str, str]]  # (wejście, tekst odpowiedzi): to, co tata zobaczyłby w Centrum


def _http(response: Any, where: str, seen: Seen) -> Problems:
    seen.append((where, response.text))
    if response.status_code < 500:
        return []
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if body.get("message") == GENERIC_500:
        return [f"{where}: ogólne 500"]
    return []


@dataclass(frozen=True)
class Entry:
    operations: tuple[str, ...]  # operationId kontraktu Centrum, które wejście wywołuje
    call: Callable[[TestClient, Seen], Problems]


def _route(operation: str, method: str, path: str, body: object = None) -> Entry:
    def call(client: TestClient, seen: Seen) -> Problems:
        return _http(client.request(method, path, json=body), operation, seen)

    return Entry((operation,), call)


def _start(client: TestClient, process: str, period: str, *, dry_run: bool) -> Any:
    """Start Uruchomienia: proces z okresem przez ``startRun``, Uporządkowanie INTERMAX przez ``startIntermax``."""

    if process == "intermax":
        return client.post("/api/intermax/run")
    return client.post("/api/runs", json={"process": process, "period": period, "mode": RunMode.of(dry_run=dry_run)})


def _start_operation(process: str) -> str:
    return "startIntermax" if process == "intermax" else "startRun"


def _process_run(process: str, period: str, *, saving: bool = False) -> Entry:
    """Uruchomienie procesu do wyniku: Podgląd bez zapisu albo Uruchomienie z zapisem.

    Po Uruchomieniu z zapisem Przebieg rozliczeń zapisuje też Kontrolę ilości w kolejce.
    """

    where = "Uruchomienie z zapisem" if saving else "Podgląd bez zapisu"

    def call(client: TestClient, seen: Seen) -> Problems:
        started = _start(client, process, period, dry_run=not saving)
        problems = _http(started, _start_operation(process), seen)
        if started.status_code != 200:
            return problems
        result = finished_view(client)["result"]
        seen.append((where, json.dumps(result, ensure_ascii=False)))
        if result["ending"] in ("unexpected", "after_engine"):
            problems.append(f"{where}: ogólny Komunikat ({result['ending']})")
        return problems + _http(client.get("/api/runs/current"), "getCurrentRun", seen)

    return Entry((_start_operation(process), "streamRunEvents", "getCurrentRun"), call)


def _diagnosis(process: str, period: str, *, report: bool) -> Entry:
    def call(client: TestClient, seen: Seen) -> Problems:
        run_id = _run_with_diagnosis(client, process, period)
        if run_id is None:
            return []
        diagnosis = client.post(f"/api/runs/{run_id}/diagnosis")
        problems = _http(diagnosis, "diagnoseRun", seen)
        if DIAGNOSIS_UNEXPECTED in diagnosis.text:
            problems.append("Diagnoza: sprawdzenie zakończone nieoczekiwanym błędem")
        if report and diagnosis.status_code == 200:
            problems += _http(client.post(f"/api/runs/{run_id}/report"), "reportRun", seen)
        return problems

    return Entry((_start_operation(process), "streamRunEvents", "diagnoseRun") + (("reportRun",) if report else ()), call)


def _pinned_dad_note() -> Entry:
    def call(client: TestClient, seen: Seen) -> Problems:
        runs = client.get("/api/dad-notes/runs")
        problems = _http(runs, "getDadNoteRuns", seen)
        if runs.status_code != 200 or not runs.json():
            return problems
        pinned = {**DAD_NOTE, "run_id": runs.json()[0]["run_id"]}
        return problems + _http(client.post("/api/dad-notes/draft", json=pinned), "draftDadNote", seen)

    return Entry(("getDadNoteRuns", "draftDadNote"), call)


def _run_with_diagnosis(client: TestClient, process: str, period: str) -> str | None:
    for _ in range(2):  # drugi raz to Powtórka, gdy pierwsze Zatrzymanie jest „dla taty”
        started = _start(client, process, period, dry_run=True)
        if started.status_code != 200:
            return None
        view = finished_view(client)
        if view["result"]["diagnosis"] is not None:
            return str(view["run"]["id"])
    return None


DAD_NOTE = {"title": "Plik zbiorczy otwiera się długo", "body": "Excel myśli przy nim minutę."}
SENT_REPORT = {
    "fingerprint": "syntetyczny-ślad",
    "number": 7,
    "commit": None,
    "what": "Nie znaleziono Wzorca pliku zbiorczego.",
    "sent_at": "2026-09-15T08:00:00+00:00",
    "closure": {"reason": "completed", "at": "2026-09-16T08:00:00+00:00"},
}
SENT_DAD_NOTE = {
    "id": "5e1f0c2d3b4a49e8b7c6d5e4f3a2b1c0",
    "title": "Brakuje ilości przy montażu",
    "commit": None,
    "written_at": "2026-09-15T09:00:00+00:00",
    "number": 8,
    "closure": None,
    "run_id": None,
}
READ_NOTIFICATION = "zgloszenie-7-rozwiazana"
LOGS_COMMENTS = [
    "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/3#issuecomment-1",
    "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/4#issuecomment-2",
    "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/5#issuecomment-3",
]
VIEW_TIMING = {"kind": "navigation", "page": "okresy", "ready_ms": 120, "fcp_ms": None, "skeleton_ms": 40, "requests": []}
ENTRIES: dict[str, Entry] = {
    "getSettings": _route("getSettings", "GET", "/api/settings"),
    "chooseRegister": _route("chooseRegister", "POST", "/api/settings/register/choose"),
    "choosePeriodsDirectory": _route("choosePeriodsDirectory", "POST", "/api/settings/periods-directory/choose"),
    "openRegister": _route("openRegister", "POST", "/api/settings/register/open"),
    "changeTheme": _route("changeTheme", "PUT", "/api/settings/theme", {"theme": "light"}),
    "getPeriodBoard": _route("getPeriodBoard", "GET", "/api/periods"),
    "openPeriodPath": _route(
        "openPeriodPath", "POST", f"/api/periods/{SETTLEMENT_PERIOD}/open", {"target": "collective_file"}
    ),
    "getQuantitiesToFill": _route("getQuantitiesToFill", "GET", f"/api/periods/{SETTLEMENT_PERIOD}/quantities-to-fill"),
    "getCollectiveFileVersion": _route(
        "getCollectiveFileVersion", "GET", f"/api/periods/{SETTLEMENT_PERIOD}/collective-file-version"
    ),
    "getWithoutQuantity": _route("getWithoutQuantity", "GET", f"/api/periods/{SETTLEMENT_PERIOD}/without-quantity"),
    "getKindTable": _route("getKindTable", "GET", f"/api/periods/{SETTLEMENT_PERIOD}/quantities-to-fill/without_rule"),
    # Rozliczenia pracownika w świecie nie ma, bo zatrzymałoby Przebieg rozliczeń; operacja go nie czyta, a ścieżkę
    # wylicza z tych samych Ustawień, Folderu okresów i Folderu okresu, które macierz psuje.
    "openWorkerSettlement": _route(
        "openWorkerSettlement",
        "POST",
        f"/api/periods/{SETTLEMENT_PERIOD}/worker-settlements/open",
        {"worker": "Adrian Testowy"},
    ),
    "getRunSetup": _route("getRunSetup", "GET", "/api/runs/setup"),
    "getIntermaxSetup": _route("getIntermaxSetup", "GET", "/api/intermax"),
    "getIntermaxDays": _route("getIntermaxDays", "GET", "/api/intermax/days"),
    "getIntermaxCopies": _route("getIntermaxCopies", "GET", "/api/intermax/copies"),
    "restoreIntermaxCopy": _route(
        "restoreIntermaxCopy", "POST", "/api/intermax/copies/restore", {"name": INTERMAX_COPY}
    ),
    "getMetrics": _route("getMetrics", "GET", "/api/metrics"),
    "getConfiguration": _route("getConfiguration", "GET", "/api/configuration"),
    "getNotifications": _route("getNotifications", "GET", "/api/notifications"),
    "markNotificationsRead": _route(
        "markNotificationsRead", "POST", "/api/notifications/read", {"ids": [READ_NOTIFICATION]}
    ),
    "getToolUpdate": _route("getToolUpdate", "GET", "/api/tool-update"),
    "recordViewTiming": _route("recordViewTiming", "POST", "/api/view-timings", VIEW_TIMING),
    "draftDadNote": _route("draftDadNote", "POST", "/api/dad-notes/draft", DAD_NOTE),
    "sendDadNote": _route("sendDadNote", "POST", "/api/dad-notes", DAD_NOTE),
    "uwaga-przypieta": _pinned_dad_note(),
    "podglad[przygotowanie]": _process_run("preparation", PERIOD),
    "podglad[przebieg]": _process_run("settlement", SETTLEMENT_PERIOD),
    "zapis[przebieg]": _process_run("settlement", SETTLEMENT_PERIOD, saving=True),
    "zapis[uporzadkowanie]": _process_run("intermax", "", saving=True),
    "diagnoza[przygotowanie]": _diagnosis("preparation", PERIOD, report=True),
    "diagnoza[przebieg]": _diagnosis("settlement", SETTLEMENT_PERIOD, report=False),
    "diagnoza[uporzadkowanie]": _diagnosis("intermax", "", report=True),
}
DIAGNOSIS_ENTRIES = ("diagnoza[przygotowanie]", "diagnoza[przebieg]", "diagnoza[uporzadkowanie]")
# Operacja kontraktu poza macierzą i powód; nowa operacja trafia do ENTRIES albo tutaj.
NOT_SWEPT: dict[str, str] = {
    "getHealth": "tożsamość Centrum, nie czyta plików taty",
    "decideRun": "Decyzja taty tylko wznawia Uruchomienie, którego odczyty sprawdzają podglądy",
    "getRunCard": "czyta tylko Logi Uruchomienia, pliki Centrum, nie pliki taty; zepsute Logi: test_centrum_karta_z_logow",
    "startToolUpdate": "aktualizacja zmienia katalog narzędzia, nie pliki taty (test_centrum_aktualizacja)",
    "reportToolUpdate": "wymaga nieudanej aktualizacji; klucz i wysłane Zgłoszenia sprawdza reportRun",
    "closeCentrum": "kończy Centrum testu",
}


def _cases() -> list[Any]:
    return [
        pytest.param(entry, damage, name, id=f"{entry}-{damage}-{name}")
        for entry in ENTRIES
        for damage, (kinds, _) in DAMAGES.items()
        for name, (_, kind) in FILES.items()
        if kind in kinds
    ]


@pytest.fixture(scope="session")
def world_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("swiat-taty")
    _build(root)
    return root


@pytest.mark.parametrize(("entry", "damage", "name"), _cases())
def test_uszkodzony_plik_nie_konczy_sie_ogolnym_komunikatem(
    world_template: Path, tmp_path: Path, entry: str, damage: str, name: str
) -> None:
    world = World(tmp_path / "swiat")
    shutil.copytree(world_template, world.root)
    if name in OLD_DAD_CASES:
        world.path("sprawy_taty").unlink()
    client = None if name in READ_AT_START else _remembering_choices(world)
    target = world.path(name)
    if damage == "ansi" and target.read_text(encoding="utf-8").isascii():
        pytest.skip("ANSI nie zmienia pliku bez polskich znaków")
    DAMAGES[damage][1](target)
    if entry in DIAGNOSIS_ENTRIES:
        world.engines.fail_summary = True
    seen: Seen = []
    try:
        problems = ENTRIES[entry].call(client or _remembering_choices(world), seen)
    finally:
        if damage == "bez_odczytu":
            _readable_again(target)
    if damage == "bez_odczytu":
        problems += [
            f"{where}: niedostępny nazwany uszkodzonym albo niepoprawnym"
            for where, text in seen
            if any(word in text for word in DAMAGED)
        ]

    assert problems == []


def test_centrum_swiata_bez_sieci_nie_zostawia_po_tescie_wysylki_ani_budzika_skrzynki(
    world_template: Path, tmp_path: Path
) -> None:
    """Uwaga taty czeka w kolejce Skrzynki na internet, a po teście nie żyje żaden wątek Skrzynki tego Centrum.

    Wątki Centrum to wątki z linii, które wątek testu zaczął od ``since``: budzik Centrum innego testu w tym samym
    workerze do nich nie należy, nawet gdy dzwoni w trakcie tego testu.
    """

    since = new_line()
    world = World(tmp_path / "swiat")
    shutil.copytree(world_template, world.root)

    sent = _remembering_choices(world).post("/api/dad-notes", json=DAD_NOTE).json()
    join_threads_since(since, named=QUEUE_THREAD)

    assert sent == {"state": "waiting", "waits_for": "internet"}
    assert [thread.name for thread in threads_since(since) if thread.name in (ALARM_THREAD, QUEUE_THREAD)] == []


def test_macierz_obejmuje_kazda_operacje_kontraktu_centrum(tmp_path: Path) -> None:
    contract = World(tmp_path).app().openapi()
    operations = {operation["operationId"] for methods in contract["paths"].values() for operation in methods.values()}
    swept = {operation for entry in ENTRIES.values() for operation in entry.operations}

    assert operations - swept - NOT_SWEPT.keys() == set(), "dodaj wejście do ENTRIES albo powód do NOT_SWEPT"
    assert (swept | NOT_SWEPT.keys()) - operations == set(), "ENTRIES albo NOT_SWEPT ma operację spoza kontraktu"


@pytest.mark.parametrize(
    ("folder", "named"),
    [("folder_okresow", "Załączniki"), ("folder_miesiaca", "09_Wrzesien_2026")],
    ids=["folder-okresow", "folder-miesiaca"],
)
def test_folder_okresow_bez_odczytu_nazywa_folder_w_kazdym_wejsciu(
    world_template: Path, tmp_path: Path, folder: str, named: str
) -> None:
    world = World(tmp_path / "swiat")
    shutil.copytree(world_template, world.root)
    client = _remembering_choices(world)
    periods = world.path(folder)
    _inaccessible(periods)
    try:
        board = client.get("/api/periods")
        preview = client.post("/api/runs", json={"process": "preparation", "period": PERIOD, "mode": "DRY-RUN"})
        stopped = finished_view(client)["result"]
        world.engines.fail_summary = True
        run_id = _run_with_diagnosis(client, "preparation", PERIOD)
        diagnosis = client.post(f"/api/runs/{run_id}/diagnosis").json()
    finally:
        _readable_again(periods)

    assert board.status_code == 500
    assert f"folderu {named}." in board.json()["message"]
    assert preview.status_code == 200
    assert stopped["stop_kind"] == "for_tata"
    assert stopped["stops"][0]["what"].startswith("Nie można teraz odczytać folderu.")
    assert stopped["stops"][0]["where"].endswith(named)
    assert diagnosis["explanation"] == stopped["stops"][0]


@pytest.mark.parametrize(("process", "period"), [("preparation", PERIOD), ("settlement", SETTLEMENT_PERIOD)])
def test_konfiguracja_wykonawcow_bez_odczytu_jest_niedostepna_w_zatrzymaniu_diagnozie_i_na_karcie(
    world_template: Path, tmp_path: Path, process: str, period: str
) -> None:
    world = World(tmp_path / "swiat")
    shutil.copytree(world_template, world.root)
    client = _remembering_choices(world)
    config = world.path("konfiguracja_wykonawcow")
    _inaccessible(config)
    try:
        card = client.get("/api/configuration").json()["workers"]
        run_id = _run_with_diagnosis(client, process, period)
        stop = finished_view(client)["result"]["stops"][0]
        diagnosis = client.post(f"/api/runs/{run_id}/diagnosis").json()
    finally:
        _readable_again(config)

    where = "plik worker_mapping.yaml, folder config"
    assert (stop["what"], stop["where"]) == (WORKER_CONFIG_INACCESSIBLE, where)
    assert (diagnosis["explanation"], diagnosis["confirms_stop"]) == (stop, True)
    assert (card["state"], card["message"]["what"], card["message"]["where"]) == (
        "unreadable",
        WORKER_CONFIG_INACCESSIBLE,
        where,
    )


def test_folder_miesiaca_znikajacy_w_trakcie_listowania_jest_pominiety(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    periods = tmp_path / "Załączniki"
    gone = periods / "Rozliczenia 2026" / "08_Sierpien_2026"
    (gone / "INEA").mkdir(parents=True)
    kept = periods / "Rozliczenia 2026" / "09_Wrzesien_2026" / "INEA"
    (kept / SETTLEMENT_PERIOD).mkdir(parents=True)
    scandir = os.scandir

    def vanishing(path: Any) -> Any:
        if Path(path) == gone:  # OneDrive zabrał folder miesiąca między listowaniem roku a listowaniem miesiąca
            raise FileNotFoundError(path)
        return scandir(path)

    monkeypatch.setattr(os, "scandir", vanishing)

    scanned = period_folder.scan_period_folders(periods)

    assert [path for paths in scanned.locations.values() for path in paths] == [kept]
