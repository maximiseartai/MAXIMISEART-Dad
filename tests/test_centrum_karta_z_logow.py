"""Karta Uruchomienia z Logów Uruchomienia (#427) przez HTTP API Centrum, jak ją widzi przeglądarka.

Ponowny start to nowa aplikacja Centrum na tych samych katalogach (``restart()``), jak po zamknięciu Centrum i
kliknięciu skrótu na pulpicie taty.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import threading
from typing import Any

import pytest

from rozliczenia.centrum.run_logs import RunLogs
from rozliczenia.centrum.run_origins import CentrumRuns
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
from tests.fixtures.potomne import wait_for
from tests.fixtures.preparation import PERIOD
from tests.fixtures.run_cards import first_view, restored

INTERRUPTED = "Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku."
PREVIEW_ADVICE = "Podgląd niczego nie zapisał. Uruchom go ponownie."
WRITE_ADVICE = "Uruchom ponownie. Pliki okresu, które zdążyły powstać, Centrum zostawi i powie, co z nimi zrobić."


def log_paths(centrum: PreparingCentrum | SettlingCentrum) -> list[Path]:
    return sorted((centrum.log_path.parent / "uruchomienia").glob("*.json"))


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


@pytest.mark.parametrize(("dry_run", "action"), [(True, PREVIEW_ADVICE), (False, WRITE_ADVICE)], ids=["podglad", "zapis"])
def test_uruchomienie_przerwane_zamknieciem_centrum_jest_nazwane_po_starcie(
    tmp_path: Path, dry_run: bool, action: str
) -> None:
    held = HeldRegister()
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(readers=held.readers()))
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
    reached, released = held_before(monkeypatch, RunLogs, "run_ended")
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
    """Rekord metryk spoza Centrum (np. ze skryptu dla maszyn) jak ``record``, z wynikiem OK i startem ``started_at``."""

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
    start_file = json.loads((centrum.log_path.parent / "ostatnie-uruchomienie.json").read_text(encoding="utf-8"))
    started_at = datetime.fromisoformat(start_file["started_at"])
    processes = centrum.engines.processes()
    preparation, settlement = processes.preparation.counter_names, processes.settlement.counter_names
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
    reached, released = held_before(monkeypatch, RunLogs, "run_ended")
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
    reached, released = held_before(monkeypatch, RunLogs, "run_ended")
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
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(readers=held.readers()))
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
    (centrum.log_path.parent / "ostatnie-uruchomienie.json").mkdir(parents=True)

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
    """Karta każdego wiersza Historii z identyfikatorem Uruchomienia, tak jak otwiera ją przeglądarka."""

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


def as_schema_1(record: dict[str, Any]) -> dict[str, Any]:
    """Logi tego Uruchomienia tak, jak zapisało je Centrum sprzed #839: bez godzin kroków i dziennika działań taty."""

    old = {key: value for key, value in record.items() if key != "dad_actions"} | {"schema_version": 1}
    old["phases"] = [{key: phase[key] for key in ("phase", "state", "duration_ms")} for phase in record["phases"]]
    old["templates"] = [
        {key: value for key, value in template.items() if key not in ("started_at", "ended_at")}
        for template in record["templates"]
    ]
    return old


def test_karta_po_starcie_i_wiersz_historii_otwieraja_logi_schematu_1_i_2(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    preview = run_to_end(centrum, dry_run=True)
    saved = run_to_end(centrum, dry_run=False)
    centrum.client.stop()
    paths = {record["run_id"]: path for path, record in zip(log_paths(centrum), logged(centrum), strict=True)}
    records = {run_id: json.loads(path.read_text(encoding="utf-8")) for run_id, path in paths.items()}
    assert {record["schema_version"] for record in records.values()} == {2}
    saved_id = saved["run"]["id"]
    paths[saved_id].write_text(json.dumps(as_schema_1(records[saved_id]), ensure_ascii=False), encoding="utf-8")

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
