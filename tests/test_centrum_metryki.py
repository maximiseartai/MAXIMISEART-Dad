"""Metryki i historia Uruchomień procesu w Centrum rozliczeń, przez HTTP API jak w przeglądarce."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.centrum import Centrum, centrum

PREPARATION_COUNTERS = {"period_orders": 3, "successful_orders": 2, "skipped_empty_rows": 1, "warnings": 0}
SETTLEMENT_COUNTERS = {
    "templates_total": 2,
    "templates_completed": 2,
    "rows": 4,
    "written": 2,
    "empty": 0,
    "planned": 2,
    "skipped": 0,
    "issues": 0,
}


FOR_TATA = {"kind": "for_tata", "code": "ZLE_SKUTECZNE"}


def record(
    started_at: str,
    *,
    counters: dict[str, int],
    mode: str = "RUN",
    period: str = "08_14_09_2026",
    result: str = "OK",
    total: int = 1000,
    phases: tuple[int, int, int, int] = (100, 200, 300, 400),
    stop: dict[str, str] | None = None,
) -> dict[str, object]:
    """Rekord w schemacie metryk 2, jak zapisuje go rdzeń; ze ``stop`` rekord przerwanego Uruchomienia."""

    stopped = stop is not None
    return {
        "schema_version": 2,
        "started_at": started_at,
        "mode": mode,
        "period": period,
        "completed": not stopped,
        "result": "BLAD_KRYTYCZNY" if stopped else result,
        "total_duration_ms": total,
        "phase_durations_ms": dict(zip(("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"), phases, strict=True)),
        "counters": dict.fromkeys(counters, 0) if stopped else counters,
        "stop": stop,
    }


def old(new_record: dict[str, object]) -> dict[str, object]:
    """Ten sam rekord w schemacie metryk 1, sprzed Rodzaju Zatrzymania w rekordzie."""

    return {key: value for key, value in new_record.items() if key != "stop"} | {"schema_version": 1}


def preparation(started_at: str, **fields: Any) -> dict[str, object]:
    return record(started_at, counters=PREPARATION_COUNTERS, **fields)


def settlement(started_at: str, **fields: Any) -> dict[str, object]:
    return record(started_at, counters=SETTLEMENT_COUNTERS, **fields)


def write_lines(path: Path, *lines: dict[str, object] | str) -> None:
    with path.open("a", encoding="utf-8") as file:
        for line in lines:
            file.write((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)) + "\n")


def metrics(app: Centrum) -> dict[str, object]:
    response = app.client.get("/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_bez_plikow_metryk_historia_uruchomien_procesu_jest_pusta(tmp_path: Path) -> None:
    body = metrics(centrum(tmp_path))

    assert body["runs"] == []
    assert body["processes"] == [
        {"process": "preparation", "label": "Przygotowanie"},
        {"process": "settlement", "label": "Przebieg"},
        {"process": "efenix", "label": "efenix"},
        {"process": "intermax", "label": "INTERMAX"},
    ]
    assert body["phases"] == ["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]
    assert body["minimum_completed_runs"] == 5


def test_historia_obejmuje_uruchomienia_procesu_obu_procesow_od_najnowszego(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        preparation("2026-10-06T06:21:00+00:00", period="29_05_10_2026", total=11_200),
        preparation("2026-10-06T06:12:00+00:00", mode="DRY-RUN", period="29_05_10_2026", total=8_100),
    )
    write_lines(
        app.metrics.settlement,
        settlement("2026-10-01T17:46:00+02:00", period="22_28_09_2026", result="WYMAGA_SPRAWDZENIA", total=12_700),
    )

    runs = metrics(app)["runs"]

    assert runs == [
        {
            "process": "preparation",
            "process_label": "Przygotowanie pliku zbiorczego",
            "started_at": "2026-10-06T06:21:00Z",
            "mode": "RUN",
            "period": "29_05_10_2026",
            "result": "OK",
            "total_duration_ms": 11_200,
            "phase_durations": [
                {"phase": "Sprawdzanie", "duration_ms": 100},
                {"phase": "Odczyt danych", "duration_ms": 200},
                {"phase": "Planowanie", "duration_ms": 300},
                {"phase": "Zapisywanie", "duration_ms": 400},
            ],
            "origin": "cmd",
            "stop_kind": None,
            "run_id": None,
        },
        {
            "process": "preparation",
            "process_label": "Przygotowanie pliku zbiorczego",
            "started_at": "2026-10-06T06:12:00Z",
            "mode": "DRY-RUN",
            "period": "29_05_10_2026",
            "result": "OK",
            "total_duration_ms": 8_100,
            "phase_durations": [
                {"phase": "Sprawdzanie", "duration_ms": 100},
                {"phase": "Odczyt danych", "duration_ms": 200},
                {"phase": "Planowanie", "duration_ms": 300},
                {"phase": "Zapisywanie", "duration_ms": 400},
            ],
            "origin": "cmd",
            "stop_kind": None,
            "run_id": None,
        },
        {
            "process": "settlement",
            "process_label": "Przebieg rozliczeń",
            "started_at": "2026-10-01T15:46:00Z",
            "mode": "RUN",
            "period": "22_28_09_2026",
            "result": "WYMAGA_SPRAWDZENIA",
            "total_duration_ms": 12_700,
            "phase_durations": [
                {"phase": "Sprawdzanie", "duration_ms": 100},
                {"phase": "Odczyt danych", "duration_ms": 200},
                {"phase": "Planowanie", "duration_ms": 300},
                {"phase": "Zapisywanie", "duration_ms": 400},
            ],
            "origin": "cmd",
            "stop_kind": None,
            "run_id": None,
        },
    ]


def statistics(body: dict[str, object], process: str, mode: str) -> dict[str, object]:
    entries = body["statistics"]
    assert isinstance(entries, list)
    [entry] = [entry for entry in entries if (entry["process"], entry["mode"]) == (process, mode)]
    assert isinstance(entry, dict)
    return entry


def runs_of(body: dict[str, object]) -> list[dict[str, Any]]:
    runs = body["runs"]
    assert isinstance(runs, list)
    return runs


def test_p50_i_p95_dopiero_od_pieciu_ukonczonych_obserwacji_tego_samego_trybu(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        *(
            preparation(f"2026-09-0{day}T08:00:00+00:00", total=total, phases=(total // 10, total // 5, 0, 0))
            for day, total in zip(range(1, 6), (5000, 1000, 4000, 2000, 3000), strict=True)
        ),
        *(preparation(f"2026-09-1{day}T08:00:00+00:00", mode="DRY-RUN") for day in range(4)),
        preparation("2026-09-20T08:00:00+00:00", mode="DRY-RUN", stop=FOR_TATA),
    )

    body = metrics(app)

    assert statistics(body, "preparation", "RUN") == {
        "process": "preparation",
        "mode": "RUN",
        "completed_runs": 5,
        "percentiles": {
            "p50_ms": 3000,
            "p95_ms": 4800,
            "phases": [
                {"phase": "Sprawdzanie", "p50_ms": 300, "p95_ms": 480},
                {"phase": "Odczyt danych", "p50_ms": 600, "p95_ms": 960},
                {"phase": "Planowanie", "p50_ms": 0, "p95_ms": 0},
                {"phase": "Zapisywanie", "p50_ms": 0, "p95_ms": 0},
            ],
        },
        "results": {"ok": 5, "needs_review": 0, "stopped": 0, "failed": 0},
    }
    # Cztery ukończone DRY-RUN i jedno przerwane to za mało: przerwane nie jest ukończoną obserwacją.
    dry_run = statistics(body, "preparation", "DRY-RUN")
    assert (dry_run["completed_runs"], dry_run["percentiles"]) == (4, None)
    assert dry_run["results"] == {"ok": 4, "needs_review": 0, "stopped": 1, "failed": 0}
    assert statistics(body, "settlement", "RUN")["percentiles"] is None


def test_wymaga_sprawdzenia_jest_ukonczona_obserwacja_i_osobnym_wynikiem(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.settlement,
        *(settlement(f"2026-09-0{day}T08:00:00+00:00") for day in range(1, 4)),
        *(settlement(f"2026-09-1{day}T08:00:00+00:00", result="WYMAGA_SPRAWDZENIA") for day in range(2)),
        settlement("2026-09-20T08:00:00+00:00", stop=FOR_TATA),
    )

    run = statistics(metrics(app), "settlement", "RUN")

    assert run["completed_runs"] == 5
    assert run["results"] == {"ok": 3, "needs_review": 2, "stopped": 1, "failed": 0}
    assert run["percentiles"] is not None


def test_zatrzymanie_dla_taty_i_stary_rekord_bez_rodzaju_to_zatrzymane_a_do_maksa_to_blad(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        old(preparation("2026-10-06T08:00:00+00:00", stop=FOR_TATA)),
        preparation("2026-10-07T08:00:00+00:00", stop=FOR_TATA),
        preparation("2026-10-08T08:00:00+00:00", stop={"kind": "for_maks", "code": "BLAD_NIEOCZEKIWANY"}),
        preparation("2026-10-09T08:00:00+00:00"),
    )

    body = metrics(app)

    assert [(run["result"], run["stop_kind"]) for run in runs_of(body)] == [
        ("OK", None),
        ("BLAD_KRYTYCZNY", "for_maks"),
        ("BLAD_KRYTYCZNY", "for_tata"),
        ("BLAD_KRYTYCZNY", None),
    ]
    expected = {"ok": 1, "needs_review": 0, "stopped": 2, "failed": 1}
    assert statistics(body, "preparation", "RUN")["results"] == expected
    assert body["recent"] == {"weeks": 8, "results": expected}


def test_niepoprawne_rekordy_metryk_sa_pomijane(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(
        app.metrics.preparation,
        preparation("2026-09-01T08:00:00+00:00", period="01_07_09_2026"),
        "{nie json",
        preparation("2026-09-02T08:00:00"),  # czas bez strefy
        preparation("2026-09-03T08:00:00+00:00", total=True),
        {**preparation("2026-09-04T08:00:00+00:00"), "schema_version": 4},  # wersja nowszego narzędzia
        settlement("2026-09-05T08:00:00+00:00"),  # liczniki Przebiegu rozliczeń w pliku Przygotowania
        '{"schema_version":1,"started_at":"2026-09-06T08:00:00+00:00","mode":"RUN"',
    )
    write_lines(app.metrics.settlement, preparation("2026-09-07T08:00:00+00:00"))

    runs = runs_of(metrics(app))

    assert [(run["process"], run["period"]) for run in runs] == [("preparation", "01_07_09_2026")]


def test_rozklad_wynikow_z_ostatnich_osmiu_tygodni_obejmuje_oba_procesy(tmp_path: Path) -> None:
    app = centrum(tmp_path)  # dziś poniedziałek 19.10.2026
    write_lines(
        app.metrics.preparation,
        preparation("2026-08-23T12:00:00+00:00"),  # przed ostatnimi ośmioma tygodniami
        preparation("2026-08-25T12:00:00+00:00"),
        preparation("2026-10-06T12:00:00+00:00", stop=FOR_TATA),
    )
    write_lines(app.metrics.settlement, settlement("2026-10-01T12:00:00+00:00", result="WYMAGA_SPRAWDZENIA"))

    recent = metrics(app)["recent"]

    assert recent == {"weeks": 8, "results": {"ok": 1, "needs_review": 1, "stopped": 1, "failed": 0}}


def test_rekord_zapisany_spoza_centrum_pojawia_sie_bez_restartu_centrum(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    assert metrics(app)["runs"] == []

    write_lines(app.metrics.preparation, preparation("2026-09-15T08:00:00+00:00", mode="DRY-RUN", stop=FOR_TATA))

    [run] = runs_of(metrics(app))
    assert (run["process"], run["mode"], run["period"], run["result"], run["origin"]) == (
        "preparation",
        "DRY-RUN",
        "08_14_09_2026",
        "BLAD_KRYTYCZNY",
        "cmd",
    )


def test_odczyt_metryk_niczego_nie_zmienia_w_plikach_metryk(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    write_lines(app.metrics.settlement, settlement("2026-09-01T08:00:00+00:00"), "{urwany")
    before = app.metrics.settlement.read_bytes()

    metrics(app)

    assert app.metrics.settlement.read_bytes() == before
    assert not app.metrics.preparation.exists()


def test_nieczytelny_plik_metryk_daje_bezpieczny_komunikat(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.metrics.preparation.mkdir()

    response = app.client.get("/api/metrics")

    assert response.status_code == 500
    assert response.json() == {"message": "Nie udało się odczytać plików metryk. Odśwież kartę."}
