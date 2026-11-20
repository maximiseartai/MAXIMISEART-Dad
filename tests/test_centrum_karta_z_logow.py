from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import shutil
import sys
import threading
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
import pytest

from rozliczenia.centrum import diagnosis_messages
from rozliczenia.centrum.contract.common import Message, ProcessKey
from rozliczenia.centrum.contract.metrics import ProcessRun
from rozliczenia.domain import RunMode
from rozliczenia.efenix_checks import Settled
from rozliczenia.efenix_orders import CollectiveOrder
from rozliczenia.efenix_pricing import OrderKind, OrderResult
from rozliczenia.efenix_window import ListedOrder
from rozliczenia.activity_legend import LegendProblem
from rozliczenia.message import Message as EngineMessage
from rozliczenia.quantity_engine import RulesProblem
from rozliczenia.centrum.dad_actions import DadActions
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import LAST_STARTED_FILE, Found, LogsOnDisk, Missing, Refused, Unreadable, name_of
from rozliczenia.centrum.run_cards import RunCards
from rozliczenia.centrum.run_comments import LeftBehindClosed, RunComments
from rozliczenia.centrum.run_logs import (
    RUN_LOGS_DIRECTORY,
    Environment,
    LoggedActivityLegend,
    LoggedInterruption,
    LoggedMessage,
    LoggedOrder,
    LoggedQuantityRules,
    RunLog,
    StartFacts,
    Tool,
)
from rozliczenia.centrum.pricing_progress import OrderDone, PricingProgress
from rozliczenia.centrum.run_origins import CentrumRuns
from tests.fixtures.schemat_logow import Fakty, fakty, niezapisane, wczytaj, zwezenia
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.settlement_messages import unmapped_worker_warning
from rozliczenia.telemetry import MetricsStore
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, without_access
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
from atrapy.dziennik_wyceny import begun_line, journal_path, left_journal, start_line
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


def append_record_outside_centrum(path: Path, counter_names: frozenset[str], record: dict[str, Any], started_at: datetime) -> None:
    counters = dict.fromkeys(counter_names, 0)
    other = {**record, "started_at": started_at.isoformat(), "result": "OK", "stop": None, "counters": counters}
    MetricsStore(path, counter_names).append(other)


def test_centrum_zamkniete_przed_zapamietaniem_uruchomienia_daje_karte_z_wynikiem_z_historii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    append_record_outside_centrum(centrum.metrics_path, preparation, record, started_at - timedelta(hours=1))
    append_record_outside_centrum(centrum.engines.metrics.settlement, settlement, record, started_at)
    append_record_outside_centrum(centrum.metrics_path, preparation, record, started_at + timedelta(hours=1))

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
    assert centrum.client.get("/api/runs/current").json()["previous"] == expected[saved["run"]["id"]]


MODE_WORDS_BEFORE_SCHEMA_3 = {"RUN": "zapis", "DRY-RUN": "podgląd"}


def as_schema_2(record: dict[str, Any]) -> dict[str, Any]:
    actions = record["dad_actions"]
    entries = [entry | {"mode": MODE_WORDS_BEFORE_SCHEMA_3[entry["mode"]]} if entry.get("mode") else entry for entry in actions["entries"]]
    return record | {"schema_version": 2, "mode": MODE_WORDS_BEFORE_SCHEMA_3[record["mode"]], "dad_actions": actions | {"entries": entries}}


def as_schema_1(record: dict[str, Any]) -> dict[str, Any]:
    old = {key: value for key, value in as_schema_2(record).items() if key != "dad_actions"} | {"schema_version": 1}
    old["phases"] = [{key: phase[key] for key in ("phase", "state", "duration_ms")} for phase in record["phases"]]
    old["templates"] = [
        {key: value for key, value in template.items() if key not in ("started_at", "ended_at")}
        for template in record["templates"]
    ]
    return old


def with_configuration_view(record: dict[str, Any]) -> dict[str, Any]:
    actions = record["dad_actions"]
    view = {"at": record["started_at"], "action": "widok", "page": "konfiguracja", "kind": "navigation"}
    return record | {"dad_actions": actions | {"entries": [view, *actions["entries"]]}}


@pytest.mark.parametrize(
    "schema",
    [as_schema_1, as_schema_2, with_configuration_view],
    ids=["schemat-1", "schemat-2", "widok-konfiguracja"],
)
def test_karta_po_starcie_i_wiersz_historii_otwieraja_logi_kazdego_schematu(
    tmp_path: Path, schema: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    centrum = settling_centrum(tmp_path)
    preview = run_to_end(centrum, dry_run=True)
    saved = run_to_end(centrum, dry_run=False)
    centrum.client.stop()
    paths = {record["run_id"]: path for path, record in zip(log_paths(centrum), logged(centrum), strict=True)}
    records = {run_id: json.loads(path.read_text(encoding="utf-8")) for run_id, path in paths.items()}
    assert {record["schema_version"] for record in records.values()} == {3}
    assert {record["mode"] for record in records.values()} == {"RUN", "DRY-RUN"}
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


RUN_ID = "0123456789abcdef0123456789abcdef"
SECOND = datetime(2026, 10, 23, 14, 5, 7, tzinfo=timezone.utc)


def start(run_id: str = RUN_ID, *, process: ProcessKey = "efenix", started_at: datetime = SECOND) -> StartFacts:
    return StartFacts(run_id=run_id, process=process, mode=RunMode.RUN, period=PERIOD, started_at=started_at)


def interrupted_logs(started: StartFacts) -> RunLog:
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
    started = start(started_at=SECOND.replace(microsecond=654321))
    record = interrupted_logs(started)
    written(tmp_path, record)
    unfinished_write = interrupted_logs(start("f" * 32, started_at=SECOND + timedelta(hours=1)))
    written(tmp_path, unfinished_write, name_of(unfinished_write.start) + ".tmp")
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


def test_identyfikator_spoza_centrum_nie_ma_logow_bez_zagladania_do_katalogu_logow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / RUN_LOGS_DIRECTORY
    directory.mkdir()
    disk = on_disk(tmp_path)

    asked = ["../x", "A" * 32, RUN_ID.upper(), f"{RUN_ID}.json", "*", ""]
    with unlisted(monkeypatch, directory):
        answers = [disk.logs(run_id) for run_id in asked]
        refused = disk.logs(RUN_ID)
    assert (answers, isinstance(refused, Refused)) == ([Missing()] * len(asked), True)


def test_plik_z_krotszym_identyfikatorem_w_nazwie_nie_jest_logami_uruchomienia(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start("abc")))
    disk = on_disk(tmp_path)

    assert (disk.logs("abc"), disk.newest("efenix")) == (Missing(), None)


def test_dziennik_wyceny_sprzed_schematu_3_ze_slowem_trybu_ma_ten_sam_start(tmp_path: Path) -> None:
    started = start()
    path = journal_path(tmp_path, started)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(start_line(started) | {"mode": "zapis"}) + "\n", encoding="utf-8")

    [left] = on_disk(tmp_path).left_behind()

    assert left.journal is not None and left.journal.started == started


def test_plik_w_miejscu_katalogu_logow_to_brak_logow_a_nie_odmowa(tmp_path: Path) -> None:
    (tmp_path / RUN_LOGS_DIRECTORY).write_text("", encoding="utf-8")
    left_journal(tmp_path, start())
    disk = on_disk(tmp_path)

    assert (disk.logs(RUN_ID), [left.logs for left in disk.left_behind()]) == (Missing(), [Missing()])


def test_katalog_logow_ktorego_system_nie_daje_wylistowac_to_odmowa_a_nie_brak_logow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_najnowsze_logi_procesu_sa_z_najpozniejszej_sekundy_startu_choc_identyfikator_starszych_jest_dalej_w_alfabecie(
    tmp_path: Path,
) -> None:
    older = interrupted_logs(start("f" * 32, started_at=SECOND - timedelta(days=1)))
    newer = interrupted_logs(start("0" * 32, started_at=SECOND))
    for record in (older, newer):
        written(tmp_path, record)

    assert on_disk(tmp_path).newest("efenix") == newer


def test_nieczytelne_najnowsze_logi_procesu_nie_ustepuja_miejsca_starszym(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start("0" * 32, started_at=SECOND - timedelta(days=1))))
    written(tmp_path, interrupted_logs(start("f" * 32, started_at=SECOND))).write_text("{", encoding="utf-8")

    assert on_disk(tmp_path).newest("efenix") is None


def test_widok_logow_liczy_sie_raz_na_wersje_pliku(tmp_path: Path) -> None:
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
    newer = interrupted_logs(start("0" * 32, started_at=SECOND))
    older = interrupted_logs(start("f" * 32, started_at=SECOND - timedelta(days=1)))
    for record in (older, newer):
        written(tmp_path, record)

    assert on_disk(tmp_path).viewed(lambda logs: logs.run_id).of("efenix") == ["0" * 32, "f" * 32]


def test_widok_ktory_pomija_logi_liczy_sie_raz_na_wersje_pliku_jak_kazdy_inny(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start()))
    written(tmp_path, interrupted_logs(start("f" * 32, started_at=SECOND + timedelta(hours=1)))).write_text("{", encoding="utf-8")
    seen: list[str] = []

    def skipping(logs: RunLog) -> str | None:
        seen.append(logs.run_id)
        return None

    viewed = on_disk(tmp_path).viewed(skipping)

    assert (viewed.of("efenix"), viewed.of("efenix"), seen) == ([], [], [RUN_ID])


@pytest.mark.skipif(sys.platform == "win32", reason="dowiązanie w Windows wymaga uprawnień administratora")
def test_widoki_logow_pomijaja_plik_ktorego_nie_ma_juz_po_wylistowaniu_katalogu(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start()))
    gone = tmp_path / RUN_LOGS_DIRECTORY / name_of(start("f" * 32, started_at=SECOND + timedelta(hours=1)))
    gone.symlink_to(tmp_path / "usuniety-plik-logow.json")

    assert on_disk(tmp_path).viewed(lambda logs: logs.run_id).of("efenix") == [RUN_ID]


def test_start_centrum_czyta_pozostawione_dzienniki_od_najwczesniejszego_startu(tmp_path: Path) -> None:
    later = start("0" * 32, started_at=SECOND + timedelta(hours=1))
    earlier = start("f" * 32, started_at=SECOND)
    for started in (later, earlier):
        left_journal(tmp_path, started)

    read = [left.journal.started for left in on_disk(tmp_path).left_behind() if left.journal is not None]

    assert read == [earlier, later]


def test_dziennik_zostawiony_przez_poprzednia_prace_ma_liczbe_zlecen_z_wpisu_zaczynam_zlecenie(tmp_path: Path) -> None:
    left_journal(tmp_path, start(), begun_line(SECOND + timedelta(minutes=1), row=7, place=1, total=3))

    [left] = on_disk(tmp_path).left_behind()

    assert left.journal is not None and (left.journal.total, left.journal.progress.total) == (3, 3)


def test_postep_z_dziennika_ma_tylko_uruchomienie_ktore_go_pisze(tmp_path: Path) -> None:
    disk = on_disk(tmp_path)
    disk.started(start())

    assert (disk.journal.progress("f" * 32), disk.journal.progress(RUN_ID) is not None) == (None, True)


def _settled(row: int) -> OrderResult:
    order = CollectiveOrder(row, f"99{row}", "adrian.testowy", "UL. TESTOWA 1", None, {}, Decimal(0))
    return OrderResult(order, Settled(ListedOrder(f"99{row}", "Rozliczone", "adrian.testowy", "UL. TESTOWA 1", "1")), (), None, None)


def test_postep_wyceny_ma_zlecenia_skonczone_po_kolei_a_miedzy_zleceniami_zadnego_w_trakcie(tmp_path: Path) -> None:
    disk = on_disk(tmp_path)
    disk.started(start())
    journal = disk.journal

    journal.begun(18, 1, 2)
    journal.ended(_settled(18))
    between = journal.progress(RUN_ID)
    journal.begun(19, 2, 2)
    journal.ended(_settled(19))

    assert (between, journal.progress(RUN_ID)) == (
        PricingProgress(start(), (OrderDone(18, OrderKind.SETTLED, None),), 2, None),
        PricingProgress(start(), (OrderDone(18, OrderKind.SETTLED, None), OrderDone(19, OrderKind.SETTLED, None)), 2, None),
    )


@NO_ACCESS_ON_WINDOWS
def test_dziennik_ktorego_start_centrum_nie_moze_usunac_zostaje_na_dysku_z_linia_dziennika_centrum(tmp_path: Path) -> None:
    path = left_journal(tmp_path, start())
    disk = on_disk(tmp_path)
    [left] = disk.left_behind()

    with without_access(path.parent):
        disk.remove_journal(left.key)

    lines = (tmp_path / "centrum.log").read_text(encoding="utf-8").splitlines()
    assert (path.exists(), [line.split(" ", 1)[1] for line in lines]) == (
        True,
        ["dziennik-wyceny-niedostepny typ=PermissionError miejsce=start"],
    )


def test_plik_ostatniego_startu_z_trescia_ktora_nie_jest_startem_daje_start_bez_ostatniego_uruchomienia(
    tmp_path: Path,
) -> None:
    (tmp_path / LAST_STARTED_FILE).write_text("{", encoding="utf-8")
    disk = on_disk(tmp_path)

    assert (disk.last_start(), RunCards(disk, list).last(LeftBehindClosed())) == (None, None)


def test_logi_urwanego_uruchomienia_nie_sa_karta_ostatniego_uruchomienia_procesu(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start(process="intermax")))

    assert RunCards(on_disk(tmp_path), list).latest("intermax") is None


def test_logi_urwanego_uruchomienia_nie_daja_karty_wiersza_historii_ani_zakonczonego_uruchomienia(tmp_path: Path) -> None:
    written(tmp_path, interrupted_logs(start()))
    cards = RunCards(on_disk(tmp_path), list)

    assert (cards.card(RUN_ID).state, cards.ended("efenix")) == ("missing", [])


def test_logi_ostatniego_startu_ktorych_system_nie_daje_odczytac_to_start_bez_karty(tmp_path: Path) -> None:
    disk = on_disk(tmp_path)
    disk.started(start(process="settlement"))
    (tmp_path / RUN_LOGS_DIRECTORY / name_of(start(process="settlement"))).mkdir(parents=True)

    assert RunCards(disk, list).last(LeftBehindClosed()) is None


def test_wiersz_historii_ze_startem_w_chwili_startu_uruchomienia_to_jego_wynik(tmp_path: Path) -> None:
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
    order = LoggedOrder(row=18, outcome=OrderKind.READY, code=None, file={}, file_amount=Decimal(0), steps=[])
    stopped = interrupted_logs(start()).model_copy(
        update={"ending": "stop", "result": "BLAD_KRYTYCZNY", "stop_kind": "for_maks", "efenix_orders": [order]}
    )
    written(tmp_path, stopped)

    [ended] = RunCards(on_disk(tmp_path), list).ended("efenix")

    assert ended.orders is None


def test_zero_zlecen_przed_zamknieciem_centrum_nie_ostrzega(tmp_path: Path) -> None:
    disk = on_disk(tmp_path)
    disk.started(start())
    written(tmp_path, interrupted_logs(start()))

    previous = RunCards(disk, list).last(LeftBehindClosed())

    assert previous is not None and previous.state == "interrupted" and previous.orders is not None
    assert ({count.count for count in previous.orders.counts}, previous.orders.zero_warns) == ({0}, False)


def test_komunikat_bez_sekcji_ustawien_i_spoza_startu_ma_w_pliku_logow_tylko_pola_sprzed_nich() -> None:
    message = EngineMessage.to_maintainer("BRAK_WZORCA", "Co.", "Gdzie.")

    assert set(json.loads(LoggedMessage.of("warning", message).model_dump_json())) == {"kind", "code", "what", "where", "action"}


def test_regul_ilosci_i_legendy_z_logow_ktore_nie_sa_tekstem_json_nie_da_sie_odczytac() -> None:
    rules = LoggedQuantityRules(rules="[adres]", devices="{}").value()
    legend = LoggedActivityLegend(legend="[adres]").value()

    assert (type(rules), type(legend)) == (RulesProblem, LegendProblem)


def test_logi_kazdego_wydania_przechodza_dzisiejszy_schemat_logow() -> None:
    znalezione = zwezenia(wczytaj(), fakty(RunLog.model_json_schema()))

    assert znalezione == [], (
        "Plik Logów starszego Wydania nie przejdzie schematu, więc u taty nie da karty z Historii, a u Maksa "
        "odtworzenia. Zostaw w schemacie dawną wartość albo pole (jak StoredPageId w dad_actions.py) albo daj nowemu "
        f"polu wartość domyślną: {znalezione}"
    )


def test_zapis_wydan_ma_kazdy_fakt_dzisiejszego_schematu_logow() -> None:
    braki = niezapisane(wczytaj(), fakty(RunLog.model_json_schema()))

    assert braki == [], (
        "Zapis faktów Wydań nie ma nowych wartości albo pól schematu Logów, więc nie złapie ich usunięcia w następnym "
        f"Wydaniu: uruchom .venv/bin/python -m tests.fixtures.schemat_logow --zapisz i dołącz zmieniony plik: {braki}"
    )


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Widok(_Model):
    action: Literal["widok"]
    page: Literal["okresy", "konfiguracja"]


class _Przycisk(_Model):
    action: Literal["przycisk"]
    process: str | None = None


class _Dawne(_Model):
    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int


class _BezWartosci(_Model):
    class _Widok(_Model):
        action: Literal["widok"]
        page: Literal["okresy"]

    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int


class _BezPola(_Model):
    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]


class _NowePoleWymagane(_Model):
    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int
    source: str


class _OpcjonalneWymagane(_Model):
    class _Przycisk(_Model):
        action: Literal["przycisk"]
        process: str | None

    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int


class _BezWariantu(_Model):
    entries: list[_Przycisk]
    omitted: int


class _Szersze(_Model):
    class _Widok(_Model):
        action: Literal["widok"]
        page: Literal["okresy", "konfiguracja", "raporty"]

    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int
    note: str | None = None


PRZYPADKI: list[tuple[str, type[BaseModel], bool]] = [
    ("usunięta wartość zamkniętej listy", _BezWartosci, True),
    ("usunięte pole", _BezPola, True),
    ("nowe pole wymagane", _NowePoleWymagane, True),
    ("pole opcjonalne staje się wymagane", _OpcjonalneWymagane, True),
    ("usunięty wariant unii z polem rozróżniającym", _BezWariantu, True),
    ("nowa wartość i nowe pole opcjonalne", _Szersze, False),
]


def _fakty(model: type[BaseModel]) -> Fakty:
    return fakty(model.model_json_schema())


@pytest.mark.parametrize(("zmiana", "teraz", "lapie"), PRZYPADKI, ids=[zmiana for zmiana, _, _ in PRZYPADKI])
def test_straznik_schematu_logow_lapie_kazda_zmiane_z_tabeli(zmiana: str, teraz: type[BaseModel], lapie: bool) -> None:
    assert bool(zwezenia(_fakty(_Dawne), _fakty(teraz))) is lapie, zmiana


class _Tekst(_Model):
    value: str


class _Liczba(_Model):
    value: int


class _Krotki(_Model):
    value: Annotated[str, Field(max_length=3)]


class _Walidator(_Model):
    value: str

    @field_validator("value")
    @classmethod
    def _tylko_cyfry(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError(value)
        return value


ZNANE_LUKI: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "węższy typ otwartego pola: str na int": (_Tekst, _Liczba),
    "węższe ograniczenie: max_length": (_Tekst, _Krotki),
    "walidator, którego schemat JSON nie pokazuje: field_validator": (_Tekst, _Walidator),
}


@pytest.mark.parametrize("luka", ZNANE_LUKI)
def test_znane_luki_straznika_schematu_logow_przechodza_przez_niego(luka: str) -> None:
    dawne, teraz = ZNANE_LUKI[luka]
    dawny_plik = dawne(value="abcd").model_dump_json()

    with pytest.raises(ValueError, match="validation error"):
        teraz.model_validate_json(dawny_plik)
    assert zwezenia(_fakty(dawne), _fakty(teraz)) == [], f"strażnik łapie już „{luka}”: przenieś ją do PRZYPADKI"
