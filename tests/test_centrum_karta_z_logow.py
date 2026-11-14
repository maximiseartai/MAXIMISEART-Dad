"""Karta Uruchomienia z Logów Uruchomienia (#427) przez HTTP API Centrum, jak ją widzi przeglądarka.

Ponowny start to nowa aplikacja Centrum na tych samych katalogach (``restart()``), jak po zamknięciu Centrum i
kliknięciu skrótu na pulpicie taty.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import shutil
import threading
from collections.abc import Callable
from typing import Any

import pytest

from rozliczenia.centrum import diagnosis_messages
from rozliczenia.centrum.contract.common import Message, ProcessKey
from rozliczenia.centrum.contract.metrics import ProcessRun
from rozliczenia.domain import RunMode
from rozliczenia.efenix_pricing import OrderKind
from rozliczenia.centrum.dad_actions import DadActions
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import LAST_STARTED_FILE, Found, LogsOnDisk, Missing, Refused, Unreadable, name_of
from rozliczenia.centrum.run_cards import RunCards
from rozliczenia.centrum.run_comments import LeftBehindClosed, RunComments
from rozliczenia.centrum.run_logs import (
    RUN_LOGS_DIRECTORY,
    Environment,
    LoggedInterruption,
    LoggedOrder,
    RunLog,
    StartFacts,
    Tool,
)
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.settlement_messages import unmapped_worker_warning
from rozliczenia.telemetry import MetricsStore
from tests.fixtures.centrum import finished_view, without_times
from tests.fixtures.centrum_processes import (
    HeldRegister,
    PreparingCentrum,
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from atrapy.dziennik_wyceny import journal_path, left_journal, start_line
from tests.fixtures.potomne import wait_for
from atrapy.preparation import PERIOD
from tests.fixtures.run_cards import first_view, restored, unlisted

INTERRUPTED = "Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku."
PREVIEW_ADVICE = "Podgląd niczego nie zapisał. Uruchom go ponownie."
WRITE_ADVICE = "Uruchom ponownie. Pliki okresu, które zdążyły powstać, Centrum zostawi i powie, co z nimi zrobić."


def log_paths(centrum: PreparingCentrum | SettlingCentrum) -> list[Path]:
    return sorted(centrum.tool.run_logs.glob("*.json"))


def logged(centrum: PreparingCentrum | SettlingCentrum) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in log_paths(centrum)]


def test_karta_po_starcie_idzie_za_plikiem_logow_bez_ustawien_metryk_i_folderu_okresu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path, include_unmapped=True)
    live = run_to_end(centrum, dry_run=True)
    centrum.client.stop()
    [path] = log_paths(centrum)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["messages"][0]["what"] = "Ostrzeżenie zmienione w pliku Logów."
    record["summary"]["figures"][0]["value"] = 999
    path.write_text(json.dumps(record), encoding="utf-8")
    shutil.rmtree(tmp_path / "config")
    centrum.metrics_path.unlink()
    shutil.rmtree(centrum.period_directory)

    centrum.restart()

    expected = restored(live, record["started_at"])
    expected["result"]["warnings"][0]["what"] = "Ostrzeżenie zmienione w pliku Logów."
    expected["result"]["summary"]["figures"][0]["value"] = 999
    assert centrum.client.get("/api/runs/current").json()["previous"] == expected


def test_karta_po_starcie_i_w_historii_ma_ostrzezenie_startu_przed_ostrzezeniem_wyniku_jak_na_zywo(tmp_path: Path) -> None:
    """Karta z Logów ma ostrzeżenia w tej samej kolejności co na żywo (``EndedRun.warnings``): najpierw ostrzeżenie
    startu (ostatnia dobra Lista Wykonawców), potem ostrzeżenie wyniku (nieznany WYKONAWCA)."""

    centrum = settling_centrum(tmp_path, include_unmapped=True)
    centrum.client.get("/api/settings")
    centrum.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")
    live = run_to_end(centrum, dry_run=True)
    centrum.client.stop()

    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    card = centrum.client.get(f"/api/runs/{live['run']['id']}/card").json()
    start = diagnosis_messages.worker_list_last_good(settings_messages.damaged(WORKERS_FILE, settings_messages.MAKS_FIXES))
    result = unmapped_worker_warning(centrum.collective_file, "andrzej.nieznany2")
    assert live["result"]["warnings"] == [Message.of(start).model_dump(), Message.of(result).model_dump()]
    assert (previous, card) == (restored(live, previous["started_at"]),) * 2


@pytest.mark.parametrize(("dry_run", "action"), [(True, PREVIEW_ADVICE), (False, WRITE_ADVICE)], ids=["podglad", "zapis"])
def test_uruchomienie_przerwane_zamknieciem_centrum_jest_nazwane_po_starcie(
    tmp_path: Path, dry_run: bool, action: str
) -> None:
    held = HeldRegister()
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(source=held.source()))
    running = centrum.start(dry_run=dry_run).json()
    assert wait_for(held.reading.is_set)
    closed = centrum.client

    centrum.restart()

    current = centrum.client.get("/api/runs/current").json()
    nothing_left = (logged(centrum), centrum.metrics_path.exists())
    held.released.set()
    finished_view(closed)
    [record] = logged(centrum)
    assert nothing_left == ([], False), "bez Logów i rekordu metryk"
    assert current == {
        "state": "idle",
        "previous": {
            "state": "interrupted",
            "run": running["run"],
            "started_at": record["started_at"],
            "advice": {"what": INTERRUPTED, "where": f"Przygotowanie pliku zbiorczego, okres {PERIOD}", "action": action},
            "orders": None,
        },
    }
    assert first_view(centrum.client) == current


def held_before(monkeypatch: pytest.MonkeyPatch, owner: type, name: str) -> tuple[threading.Event, threading.Event]:
    """Metoda ``name`` klasy ``owner`` czeka, aż test ją puści: ponowny start Centrum w tym czasie to Centrum zamknięte
    tuż przed nią. Daje parę (doszło, puść); puszczona metoda robi swoje w poprzednim Centrum."""

    reached, released = threading.Event(), threading.Event()
    real = getattr(owner, name)

    def held(*args: Any) -> Any:
        reached.set()
        released.wait()
        return real(*args)

    monkeypatch.setattr(owner, name, held)
    return reached, released


def test_centrum_zamkniete_po_zapisie_wyniku_w_historii_daje_karte_z_wynikiem_z_historii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Centrum zamyka się po rekordzie metryk, a przed Logami Uruchomienia: karta po starcie nie przeczy Historii (#722)."""

    centrum = preparing_centrum(tmp_path)
    reached, released = held_before(monkeypatch, RunComments, "run_ended")
    running = centrum.start(dry_run=False).json()
    assert wait_for(reached.is_set)
    closed = centrum.client

    centrum.restart()

    current = centrum.client.get("/api/runs/current").json()
    shown = first_view(centrum.client)
    [row] = centrum.client.get("/api/metrics").json()["runs"]
    without_logs = logged(centrum)
    released.set()
    finished_view(closed)
    assert (without_logs, row["run_id"], row["result"]) == ([], running["run"]["id"], "WYMAGA_SPRAWDZENIA")
    assert current == shown == {
        "state": "idle",
        "previous": {
            "state": "recorded",
            "run": running["run"],
            "started_at": row["started_at"],
            "result": "WYMAGA_SPRAWDZENIA",
            "headline": "Plik zbiorczy przygotowany · wymaga sprawdzenia",
            "next_action": "open_collective_file",
        },
    }


def append_record(path: Path, counter_names: frozenset[str], record: dict[str, Any], started_at: datetime) -> None:
    """Rekord metryk spoza Centrum (np. ze skryptu dla maszyn) jak ``record``."""

    counters = dict.fromkeys(counter_names, 0)
    other = {**record, "started_at": started_at.isoformat(), "result": "OK", "stop": None, "counters": counters}
    MetricsStore(path, counter_names).append(other)


def test_centrum_zamkniete_przed_zapamietaniem_uruchomienia_daje_karte_z_wynikiem_z_historii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiersz Historii nie ma jeszcze identyfikatora Uruchomienia (``CentrumRuns.remember``), a karta i tak go znajduje:
    pierwszy wiersz tego procesu od startu Uruchomienia (#722)."""

    centrum = preparing_centrum(tmp_path)
    reached, released = held_before(monkeypatch, CentrumRuns, "remember")
    running = centrum.start(dry_run=False).json()
    assert wait_for(reached.is_set)
    closed = centrum.client
    [record] = centrum.metric_records()
    start_file = json.loads(centrum.tool.last_started.read_text(encoding="utf-8"))
    started_at = datetime.fromisoformat(start_file["started_at"])
    catalog = centrum.engines.catalog()
    preparation, settlement = catalog.metrics("preparation").counter_names, catalog.metrics("settlement").counter_names
    append_record(centrum.metrics_path, preparation, record, started_at - timedelta(hours=1))
    append_record(centrum.engines.metrics.settlement, settlement, record, started_at)
    append_record(centrum.metrics_path, preparation, record, started_at + timedelta(hours=1))

    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    rows = centrum.client.get("/api/metrics").json()["runs"]
    released.set()
    finished_view(closed)
    [row] = [row for row in rows if row["result"] == "WYMAGA_SPRAWDZENIA"]
    assert (len(rows), row["run_id"]) == (4, None)
    assert previous == {
        "state": "recorded",
        "run": running["run"],
        "started_at": row["started_at"],
        "result": "WYMAGA_SPRAWDZENIA",
        "headline": "Plik zbiorczy przygotowany · wymaga sprawdzenia",
        "next_action": "open_collective_file",
    }


def test_karta_z_historii_po_zatrzymaniu_ma_tytul_i_akcje_jak_na_zywo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.engines.fail_summary = True
    reached, released = held_before(monkeypatch, RunComments, "run_ended")
    running = centrum.start(dry_run=True).json()
    assert wait_for(reached.is_set)
    closed = centrum.client

    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    released.set()
    live = finished_view(closed)["result"]
    assert live["stop_kind"] == "for_maks"
    assert (previous["state"], previous["run"], previous["result"]) == ("recorded", running["run"], live["result"])
    assert (previous["headline"], previous["next_action"]) == (live["headline"], live["next_action"])


def test_karta_z_historii_po_zatrzymaniu_po_zapisie_proponuje_ponowne_uruchomienie_bo_wiersz_nie_wie_o_silniku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiersz Historii nie mówi, czy Zatrzymanie przyszło po silniku, więc karta z niego po zapisie proponuje ponowne
    Uruchomienie, a nie otwarcie pliku, które pokazała karta na żywo; ponowne Uruchomienie mówi, co z plikami zrobić."""

    centrum = preparing_centrum(tmp_path)
    centrum.engines.fail_summary = True
    reached, released = held_before(monkeypatch, RunComments, "run_ended")
    centrum.start(dry_run=False)
    assert wait_for(reached.is_set)
    closed = centrum.client

    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    released.set()
    live = finished_view(closed)["result"]
    assert (live["stop_kind"], live["next_action"]) == ("for_maks", "open_collective_file")
    assert (previous["state"], previous["headline"], previous["next_action"]) == ("recorded", live["headline"], "rerun")


def test_centrum_zamkniete_przed_zapisem_wyniku_w_historii_daje_urwane_uruchomienie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiersz wcześniejszego Uruchomienia w Historii nie jest wynikiem Urwanego."""

    centrum = preparing_centrum(tmp_path)
    earlier = run_to_end(centrum, dry_run=True)
    reached, released = held_before(monkeypatch, MetricsStore, "append")
    running = centrum.start(dry_run=False).json()
    assert wait_for(reached.is_set)
    closed = centrum.client

    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    history = centrum.client.get("/api/metrics").json()["runs"]
    released.set()
    finished_view(closed)
    assert [row["run_id"] for row in history] == [earlier["run"]["id"]]
    assert (previous["state"], previous["run"]) == ("interrupted", running["run"])


def test_nieczytelna_historia_bez_logow_daje_urwane_uruchomienie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Historii nie da się odczytać, więc nie pokaże wyniku, któremu karta mogłaby przeczyć."""

    centrum = preparing_centrum(tmp_path)
    reached, released = held_before(monkeypatch, RunComments, "run_ended")
    running = centrum.start(dry_run=False).json()
    assert wait_for(reached.is_set)
    closed = centrum.client
    centrum.metrics_path.unlink()
    centrum.metrics_path.mkdir()

    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    released.set()
    finished_view(closed)
    assert (previous["state"], previous["run"]) == ("interrupted", running["run"])


def test_karta_po_starcie_to_ostatni_start_takze_po_przerwanym(tmp_path: Path) -> None:
    held = HeldRegister()
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(source=held.source()))
    centrum.start(dry_run=True)
    assert wait_for(held.reading.is_set)
    closed = centrum.client
    centrum.restart()
    held.released.set()
    finished_view(closed)

    live = run_to_end(centrum, dry_run=False)
    centrum.restart()

    previous = centrum.client.get("/api/runs/current").json()["previous"]
    assert (previous["state"], previous["run"]) == ("restored", live["run"])


def test_nieczytelne_logi_ostatniego_uruchomienia_daja_start_bez_karty(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_to_end(centrum, dry_run=True)
    [path] = log_paths(centrum)
    path.write_text("{", encoding="utf-8")

    centrum.restart()

    assert centrum.client.get("/api/runs/current").json() == {"state": "idle", "previous": None}


def test_nieudany_zapis_startu_nie_zmienia_uruchomienia(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.tool.last_started.mkdir(parents=True)

    view = run_to_end(centrum, dry_run=False)

    expected = run_to_end(settling_centrum(tmp_path / "bez-blokady"), dry_run=False)
    assert without_times(view["result"]) == without_times(expected["result"])
    assert 'miejsce="start Uruchomienia procesu"' in centrum.log_path.read_text(encoding="utf-8")
    centrum.restart()
    assert centrum.client.get("/api/runs/current").json() == {"state": "idle", "previous": None}


def test_diagnoza_karty_z_logow_jest_odrzucona(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)

    centrum.restart()

    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert (response.status_code, response.json()) == (404, {"message": "Nie ma takiego Uruchomienia procesu."})


def history_cards(centrum: SettlingCentrum) -> dict[str, Any]:
    runs = centrum.client.get("/api/metrics").json()["runs"]
    return {run["run_id"]: centrum.client.get(f"/api/runs/{run['run_id']}/card").json() for run in runs}


def test_wiersz_historii_otwiera_karte_swojego_uruchomienia_takze_po_ponownym_starcie(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    preview = run_to_end(centrum, dry_run=True)
    saved = run_to_end(centrum, dry_run=False)
    started = {record["run_id"]: record["started_at"] for record in logged(centrum)}

    before = history_cards(centrum)
    centrum.restart()
    after = history_cards(centrum)

    expected = {live["run"]["id"]: restored(live, started[live["run"]["id"]]) for live in (preview, saved)}
    assert before == after == expected


OLD_WORDS = {"RUN": "zapis", "DRY-RUN": "podgląd"}
"""Tryb w plikach Centrum sprzed schematu Logów 3."""


def as_schema_2(record: dict[str, Any]) -> dict[str, Any]:
    """Logi tego Uruchomienia tak, jak zapisało je Centrum sprzed schematu 3: tryb, także przy starcie w dzienniku
    działań taty, słowem."""

    actions = record["dad_actions"]
    entries = [entry | {"mode": OLD_WORDS[entry["mode"]]} if entry.get("mode") else entry for entry in actions["entries"]]
    return record | {"schema_version": 2, "mode": OLD_WORDS[record["mode"]], "dad_actions": actions | {"entries": entries}}


def as_schema_1(record: dict[str, Any]) -> dict[str, Any]:
    """Logi tego Uruchomienia tak, jak zapisało je Centrum sprzed #839: bez godzin kroków i dziennika działań taty."""

    old = {key: value for key, value in as_schema_2(record).items() if key != "dad_actions"} | {"schema_version": 1}
    old["phases"] = [{key: phase[key] for key in ("phase", "state", "duration_ms")} for phase in record["phases"]]
    old["templates"] = [
        {key: value for key, value in template.items() if key not in ("started_at", "ended_at")}
        for template in record["templates"]
    ]
    return old


@pytest.mark.parametrize("schema", [as_schema_1, as_schema_2, None], ids=["schemat-1", "schemat-2", "schemat-3"])
def test_karta_po_starcie_i_wiersz_historii_otwieraja_logi_kazdego_schematu(
    tmp_path: Path, schema: Callable[[dict[str, Any]], dict[str, Any]] | None
) -> None:
    centrum = settling_centrum(tmp_path)
    preview = run_to_end(centrum, dry_run=True)
    saved = run_to_end(centrum, dry_run=False)
    centrum.client.stop()
    paths = {record["run_id"]: path for path, record in zip(log_paths(centrum), logged(centrum), strict=True)}
    records = {run_id: json.loads(path.read_text(encoding="utf-8")) for run_id, path in paths.items()}
    assert {record["schema_version"] for record in records.values()} == {3}
    assert {record["mode"] for record in records.values()} == {"RUN", "DRY-RUN"}
    if schema is not None:
        for run_id, path in paths.items():
            path.write_text(json.dumps(schema(records[run_id]), ensure_ascii=False), encoding="utf-8")
        start_file = centrum.tool.last_started
        started = json.loads(start_file.read_text(encoding="utf-8"))
        assert (started["schema_version"], started["mode"]) == (2, "RUN")
        start_file.write_text(
            json.dumps(started | {"schema_version": 1, "mode": "zapis"}, ensure_ascii=False), encoding="utf-8"
        )
    saved_id = saved["run"]["id"]

    centrum.restart()

    expected = {live["run"]["id"]: restored(live, records[live["run"]["id"]]["started_at"]) for live in (preview, saved)}
    assert centrum.client.get("/api/runs/current").json()["previous"] == expected[saved_id]
    assert history_cards(centrum) == expected


def test_uruchomienie_bez_logow_nie_ma_karty(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    asked = ["0123456789abcdef0123456789abcdef", f"settlement-{run_id}", run_id.upper(), f"{run_id}.json", "*"]

    answers = [centrum.client.get(f"/api/runs/{asked_id}/card") for asked_id in asked]
    [path] = log_paths(centrum)
    path.write_text("{", encoding="utf-8")
    broken = centrum.client.get(f"/api/runs/{run_id}/card")

    missing = (200, {"state": "missing"})
    assert [(answer.status_code, answer.json()) for answer in answers] == [missing] * len(asked)
    assert (broken.status_code, broken.json()) == missing


# --- Logi na dysku (``logs_disk``): jedna odpowiedź o Logach Uruchomienia dla kart i dla startu Centrum ----------------

RUN_ID = "0123456789abcdef0123456789abcdef"
SECOND = datetime(2026, 10, 23, 14, 5, 7, tzinfo=timezone.utc)


def start(run_id: str = RUN_ID, *, process: ProcessKey = "efenix", started_at: datetime = SECOND) -> StartFacts:
    return StartFacts(run_id=run_id, process=process, mode=RunMode.RUN, period=PERIOD, started_at=started_at)


def interrupted_logs(started: StartFacts) -> RunLog:
    """Logi Urwanego Uruchomienia ``started`` bez zleceń, jakie start Centrum zamyka z dziennika Wyceny w efenix."""

    return RunLog.interrupted(
        started,
        ended_at=started.started_at + timedelta(minutes=5),
        orders=[],
        interruption=LoggedInterruption(row=None, place=None, total=None, omitted=0),
        tool=Tool(wydanie=None, commit=None),
        environment=Environment(system="Windows-11", python="3.12.7", files=None),
        dad_actions=DadActions(entries=[], omitted=0),
    )


def on_disk(directory: Path) -> LogsOnDisk:
    return LogsOnDisk(CentrumLog(directory / "centrum.log"), journaled="efenix")


def written(directory: Path, record: RunLog, name: str | None = None) -> Path:
    path = directory / RUN_LOGS_DIRECTORY / (name or name_of(record.start))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.text, encoding="utf-8")
    return path


def test_nazwa_pliku_logow_to_sekunda_startu_w_utc_proces_i_identyfikator_a_dysk_znajduje_po_niej_logi(
    tmp_path: Path,
) -> None:
    """Plik po zapisie, który się nie skończył (``.tmp``), ma inną nazwę, więc nie jest Logami Uruchomienia."""

    started = start(started_at=SECOND.replace(microsecond=654321))
    record = interrupted_logs(started)
    written(tmp_path, record)
    later = interrupted_logs(start("f" * 32, started_at=SECOND + timedelta(hours=1)))
    written(tmp_path, later, name_of(later.start) + ".tmp")
    disk = on_disk(tmp_path)

    assert name_of(started) == f"20261023T140507Z-efenix-{RUN_ID}.json"
    assert (disk.logs(RUN_ID), disk.logs("f" * 32), disk.newest("efenix")) == (Found(record), Missing(), record)


@pytest.mark.parametrize(
    ("content", "read"),
    [(None, Missing()), (b"{", Unreadable()), ("Logi".encode("utf-16"), Unreadable())],
    ids=["bez-pliku", "zly-json", "nie-utf-8"],
)
def test_logi_uruchomienia_bez_pliku_albo_nieczytelne(tmp_path: Path, content: bytes | None, read: object) -> None:
    if content is not None:
        path = tmp_path / RUN_LOGS_DIRECTORY / name_of(start())
        path.parent.mkdir()
        path.write_bytes(content)

    assert on_disk(tmp_path).logs(RUN_ID) == read


def test_logi_ktorych_system_nie_daje_odczytac_to_odmowa_a_nie_nieczytelne(tmp_path: Path) -> None:
    (tmp_path / RUN_LOGS_DIRECTORY / name_of(start())).mkdir(parents=True)

    assert isinstance(on_disk(tmp_path).logs(RUN_ID), Refused)


def test_identyfikator_spoza_centrum_nie_ma_logow_choc_nazwa_pliku_sie_nim_konczy(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start()))
    disk = on_disk(tmp_path)

    asked = [f"efenix-{RUN_ID}", RUN_ID.upper(), f"{RUN_ID}.json", "*", ""]
    assert [disk.logs(run_id) for run_id in asked] == [Missing()] * len(asked)


def test_identyfikator_spoza_centrum_nie_ma_logow_bez_zagladania_do_katalogu_logow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identyfikator z adresu karty, którego Centrum nie nadaje (np. ``../``), nie dochodzi do dysku: przy katalogu Logów,
    którego system nie daje wylistować, jest dalej bez Logów, a nie odmową."""

    directory = tmp_path / RUN_LOGS_DIRECTORY
    directory.mkdir()
    disk = on_disk(tmp_path)

    asked = ["../x", "A" * 32, RUN_ID.upper(), f"{RUN_ID}.json", "*", ""]
    with unlisted(monkeypatch, directory):
        answers = [disk.logs(run_id) for run_id in asked]
        refused = disk.logs(RUN_ID)
    assert (answers, isinstance(refused, Refused)) == ([Missing()] * len(asked), True)


def test_plik_z_krotszym_identyfikatorem_w_nazwie_nie_jest_logami_uruchomienia(tmp_path: Path) -> None:
    """Centrum nadaje identyfikator z 32 znaków szesnastkowych (``uuid4().hex``), więc plik z krótszym w nazwie to nie
    Logi Uruchomienia, a o krótszy identyfikator dysk nie pyta."""

    written(tmp_path, interrupted_logs(start("abc")))
    disk = on_disk(tmp_path)

    assert (disk.logs("abc"), disk.newest("efenix")) == (Missing(), None)


def test_dziennik_wyceny_sprzed_schematu_3_ze_slowem_trybu_ma_ten_sam_start(tmp_path: Path) -> None:
    """Dziennik Wyceny w efenix, który zostawiło Centrum sprzed schematu Logów 3, ma w pierwszej linii słowo trybu
    („zapis”), a start Centrum czyta go jako ten sam start Uruchomienia, więc zamyka go Logami Urwanego Uruchomienia."""

    started = start()
    path = journal_path(tmp_path, started)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(start_line(started) | {"mode": "zapis"}) + "\n", encoding="utf-8")

    [left] = on_disk(tmp_path).left_behind()

    assert left.journal is not None and left.journal.started == started


def test_plik_w_miejscu_katalogu_logow_to_brak_logow_a_nie_odmowa(tmp_path: Path) -> None:
    """Plik w miejscu katalogu Logów się nie zmieni, więc to brak Logów, jak bez katalogu: start Centrum zamyka dziennik
    Wyceny jego Uruchomienia wersją zastępczą, zamiast zostawiać go na zawsze jak przy odmowie."""

    (tmp_path / RUN_LOGS_DIRECTORY).write_text("", encoding="utf-8")
    left_journal(tmp_path, start())
    disk = on_disk(tmp_path)

    assert (disk.logs(RUN_ID), [left.logs for left in disk.left_behind()]) == (Missing(), [Missing()])


def test_katalog_logow_ktorego_system_nie_daje_wylistowac_to_odmowa_a_nie_brak_logow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nie wiadomo, czy Logi ostatniego startu są, więc karta po starcie nie mówi, że Uruchomienie urwało się w trakcie,
    tak jak przy Logach, których nie da się odczytać, a Logów procesu nie ma żadnych. Z wylistowanym katalogiem bez pliku
    Logów ostatniego startu to Urwane Uruchomienie."""

    disk = on_disk(tmp_path)
    disk.started(start(process="settlement"))
    record = interrupted_logs(start("f" * 32, process="intermax"))
    written(tmp_path, record)
    cards = RunCards(disk, list)
    viewed = disk.viewed(lambda logs: logs.run_id)

    listed = (disk.logs(RUN_ID), cards.last(LeftBehindClosed()) is None, disk.newest("intermax"), viewed.of("intermax"))
    with unlisted(monkeypatch, tmp_path / RUN_LOGS_DIRECTORY):
        read = disk.logs(RUN_ID)
        refused = (cards.last(LeftBehindClosed()), disk.newest("intermax"), viewed.of("intermax"))
    assert listed == (Missing(), False, record, ["f" * 32])
    assert (isinstance(read, Refused), refused) == (True, (None, None, []))


@pytest.mark.parametrize(
    ("earlier", "later"), [("0" * 32, "f" * 32), ("f" * 32, "0" * 32)], ids=["pozniejszy-dalej", "pozniejszy-blizej"]
)
def test_najnowsze_logi_z_tej_samej_sekundy_to_logi_z_pozniejszym_startem(tmp_path: Path, earlier: str, later: str) -> None:
    older = interrupted_logs(start(started_at=SECOND - timedelta(days=1)))
    first = interrupted_logs(start(earlier, started_at=SECOND.replace(microsecond=100_000)))
    second = interrupted_logs(start(later, started_at=SECOND.replace(microsecond=200_000)))
    for record in (older, first, second):
        written(tmp_path, record)

    assert on_disk(tmp_path).newest("efenix") == second


def test_widok_logow_liczy_sie_raz_na_wersje_pliku(tmp_path: Path) -> None:
    """Diagnoza nadpisuje plik Logów, więc widok tego pliku liczy się znowu, a pliku bez zmian nie."""

    record = interrupted_logs(start())
    path = written(tmp_path, record)
    seen: list[str] = []

    def view(logs: RunLog) -> datetime:
        seen.append(logs.run_id)
        return logs.ended_at

    viewed = on_disk(tmp_path).viewed(view)
    before = (viewed.of("efenix"), viewed.of("efenix"), viewed.of("settlement"))
    diagnosed = record.model_copy(update={"ended_at": record.ended_at + timedelta(minutes=1), "technical_notes": ["Diagnoza"]})
    path.write_text(diagnosed.text, encoding="utf-8")
    after = viewed.of("efenix")

    assert (before, after, seen) == (([record.ended_at], [record.ended_at], []), [diagnosed.ended_at], [RUN_ID] * 2)


def test_widoki_logow_procesu_ida_od_najnowszego_startu(tmp_path: Path) -> None:
    """Zakończone Uruchomienia procesu idą od najnowszego (``RunCards.ended``), także gdy identyfikator starszego jest
    dalej w alfabecie."""

    newer = interrupted_logs(start("0" * 32, started_at=SECOND))
    older = interrupted_logs(start("f" * 32, started_at=SECOND - timedelta(days=1)))
    for record in (older, newer):
        written(tmp_path, record)

    assert on_disk(tmp_path).viewed(lambda logs: logs.run_id).of("efenix") == ["0" * 32, "f" * 32]


def test_plik_ostatniego_startu_z_trescia_ktora_nie_jest_startem_daje_start_bez_ostatniego_uruchomienia(
    tmp_path: Path,
) -> None:
    """Plik ostatniego startu, którego treść nie jest faktami startu (np. zmienił go inny program), to start Centrum bez
    ostatniego Uruchomienia, jak bez pliku, a nie błąd."""

    (tmp_path / LAST_STARTED_FILE).write_text("{", encoding="utf-8")
    disk = on_disk(tmp_path)

    assert (disk.last_start(), RunCards(disk, list).last(LeftBehindClosed())) == (None, None)


def test_logi_urwanego_uruchomienia_nie_sa_karta_ostatniego_uruchomienia_procesu(tmp_path: Path) -> None:
    """Karta ostatniego Uporządkowania INTERMAX bierze Logi z wynikiem, a Logi Urwanego Uruchomienia go nie mają."""

    written(tmp_path, interrupted_logs(start(process="intermax")))

    assert RunCards(on_disk(tmp_path), list).latest("intermax") is None


def test_logi_ostatniego_startu_ktorych_system_nie_daje_odczytac_to_start_bez_karty(tmp_path: Path) -> None:
    """Logi są, więc Uruchomienie miało wynik: karta po starcie nie mówi, że urwało się w trakcie (a7ee70d7b)."""

    disk = on_disk(tmp_path)
    disk.started(start(process="settlement"))
    (tmp_path / RUN_LOGS_DIRECTORY / name_of(start(process="settlement"))).mkdir(parents=True)

    assert RunCards(disk, list).last(LeftBehindClosed()) is None


def test_wiersz_historii_ze_startem_w_chwili_startu_uruchomienia_to_jego_wynik(tmp_path: Path) -> None:
    """Zegar Windows tyka co ok. 15 ms, więc rekord metryk może mieć start równy startowi Uruchomienia; to dalej jego
    wiersz (okno od startu jak w ``CentrumRuns.remember``), a nie Urwane Uruchomienie."""

    disk = on_disk(tmp_path)
    disk.started(start())
    row = ProcessRun(
        process="efenix",
        process_label="Wycena w efenix",
        started_at=SECOND,
        mode=RunMode.RUN,
        period=PERIOD,
        result="OK",
        total_duration_ms=60_000,
        phase_durations=[],
        origin="centrum",
        stop_kind=None,
        run_id=RUN_ID,
    )

    previous = RunCards(disk, lambda: [row]).last(LeftBehindClosed())

    assert previous is not None
    assert (previous.state, previous.started_at, previous.run.id) == ("recorded", SECOND, RUN_ID)


def test_wycena_zatrzymana_po_zleceniach_konczy_sie_w_powiadomieniu_bez_liczby_zlecen(tmp_path: Path) -> None:
    """Po Zatrzymaniu Logi Wyceny w efenix mają zlecenia sprzed niego, ale Powiadomienie liczy zlecenia tylko Wyceny
    z podsumowaniem, więc zakończona Zatrzymaniem nie ma ich liczby."""

    order = LoggedOrder(row=18, outcome=OrderKind.READY, code=None, file={}, file_amount=Decimal(0), steps=[])
    stopped = interrupted_logs(start()).model_copy(
        update={"ending": "stop", "result": "BLAD_KRYTYCZNY", "stop_kind": "for_maks", "efenix_orders": [order]}
    )
    written(tmp_path, stopped)

    [ended] = RunCards(on_disk(tmp_path), list).ended("efenix")

    assert (stopped.summary, ended.orders) == (None, None)


def test_zero_zlecen_przed_zamknieciem_centrum_nie_ostrzega(tmp_path: Path) -> None:
    """Karta Urwanej Wyceny liczy zlecenia skończone przed zamknięciem Centrum; zero to zwykła liczba, a nie sygnał dla
    taty jak dzień bez zleceń (``CountGroup.zero_warns``)."""

    disk = on_disk(tmp_path)
    disk.started(start())
    written(tmp_path, interrupted_logs(start()))

    previous = RunCards(disk, list).last(LeftBehindClosed())

    assert previous is not None and previous.state == "interrupted" and previous.orders is not None
    assert ({count.count for count in previous.orders.counts}, previous.orders.zero_warns) == ({0}, False)
