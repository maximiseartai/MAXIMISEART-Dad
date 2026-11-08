"""Plik metryk (``MetricsStore``): jedyne miejsce zapisu rekordu Uruchomienia procesu na dysk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rozliczenia import settlement_process
from rozliczenia.telemetry import MetricsStore, metric_record
from rozliczenia.write_routes import Route, TemplateKind
from tests.fixtures.message_samples import PREPARATION_SAMPLES, SETTLEMENT_SAMPLES, Samples
from atrapy.preparation import PERIOD

SETTLEMENT_COUNTERS = settlement_process.PROCESS.counter_names


def completed_record() -> dict[str, Any]:
    return metric_record(
        mode="RUN",
        period=PERIOD,
        started_at="2026-09-15T08:00:00+00:00",
        total_duration_ms=1000,
        phase_durations_ms={},
        ending="OK",
        counters=dict.fromkeys(SETTLEMENT_COUNTERS, 1),
        routes={(TemplateKind.COLLECTIVE_FILE, Route.OPENPYXL): 1, (TemplateKind.WORKER_SETTLEMENT, Route.COPY): 2},
    )


def stopped_record(stop: Any) -> dict[str, Any]:
    return metric_record(
        mode="DRY-RUN",
        period=PERIOD,
        started_at="2026-09-15T08:00:00+00:00",
        total_duration_ms=400,
        phase_durations_ms={},
        ending=stop,
        counters=dict.fromkeys(SETTLEMENT_COUNTERS, 0),
        routes={},
    )


def test_plik_metryk_czyta_rekordy_wersji_1_bez_rodzaju_zatrzymania_i_wersji_2_bez_drogi_zapisu(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    old_completed = {**completed_record(), "schema_version": 1}
    old_stopped = {**stopped_record(None), "schema_version": 1}
    del old_completed["stop"], old_stopped["stop"], old_completed["routes"], old_stopped["routes"]
    without_routes = {**stopped_record({"kind": "for_maks", "code": "BLAD_NIEOCZEKIWANY"}), "schema_version": 2}
    del without_routes["routes"]
    metrics_path.write_text(
        "".join(json.dumps(record) + "\n" for record in (old_completed, old_stopped, without_routes)), encoding="utf-8"
    )

    MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(stopped_record({"kind": "for_tata", "code": "ZLE_SKUTECZNE"}))

    assert MetricsStore(metrics_path, SETTLEMENT_COUNTERS).read() == [
        old_completed,
        old_stopped,
        without_routes,
        stopped_record({"kind": "for_tata", "code": "ZLE_SKUTECZNE"}),
    ]


def test_rekord_metryk_liczy_zapisane_pliki_kazdego_rodzaju_kazdej_drogi_zapisu() -> None:
    assert completed_record()["routes"] == {
        "worker_settlement": {"kopia": 2, "openpyxl": 0},
        "collective_file": {"kopia": 0, "openpyxl": 1},
        "internal_settlement": {"kopia": 0, "openpyxl": 0},
    }
    assert stopped_record(None)["routes"] == dict.fromkeys(
        ("worker_settlement", "collective_file", "internal_settlement"), {"kopia": 0, "openpyxl": 0}
    )


NO_FILES = {"kopia": 0, "openpyxl": 0}


@pytest.mark.parametrize(
    "routes",
    [
        {"worker_settlement": NO_FILES, "collective_file": NO_FILES, "internal_settlement": NO_FILES, "Anna Testowa": NO_FILES},
        {"worker_settlement": NO_FILES, "collective_file": NO_FILES},
        {"worker_settlement": NO_FILES, "collective_file": NO_FILES, "internal_settlement": {"kopia": 1}},
        {"worker_settlement": {**NO_FILES, "Anna Testowa": 1}, "collective_file": NO_FILES, "internal_settlement": NO_FILES},
        {"worker_settlement": NO_FILES, "collective_file": NO_FILES, "internal_settlement": {"kopia": -1, "openpyxl": 0}},
        {"worker_settlement": NO_FILES, "collective_file": NO_FILES, "internal_settlement": {"kopia": True, "openpyxl": 0}},
        {"worker_settlement": NO_FILES, "collective_file": NO_FILES, "internal_settlement": ["kopia", "openpyxl"]},
        ["worker_settlement", "collective_file", "internal_settlement"],
        "brak",
    ],
    ids=["nazwa-wykonawcy", "bez-rodzaju", "bez-drogi", "nazwa-wykonawcy-obok-drog", "ujemna", "nie-liczba", "drogi-lista", "lista", "bez-pola"],
)
def test_plik_metryk_odrzuca_rekord_bez_licznika_kazdej_drogi_zapisu(tmp_path: Path, routes: Any) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    if routes == "brak":
        del record["routes"]
    else:
        record["routes"] = routes

    with pytest.raises(ValueError, match="Niepoprawny rekord metryk"):
        MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)
    metrics_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    assert MetricsStore(metrics_path, SETTLEMENT_COUNTERS).read() == []


@pytest.mark.parametrize(
    "stop",
    [
        {"kind": "for_tata", "code": "C:\\Users\\tata\\Rejestr.xlsx"},
        {"kind": "for_tata", "code": "ZLE_SKUTECZNE ul. Syntetyczna 1"},
        {"kind": "for_tata", "code": "zle_skuteczne"},
        {"kind": "for_tata", "code": ""},
        {"kind": "repeated", "code": "ZLE_SKUTECZNE"},
        {"kind": "for_tata", "code": "ZLE_SKUTECZNE", "what": "Braki w SKUTECZNE."},
        None,
    ],
    ids=["sciezka", "dane-klienta", "male-litery", "pusty-kod", "powtorka", "tresc-komunikatu", "bez-zatrzymania"],
)
def test_plik_metryk_odrzuca_zatrzymanie_bez_rodzaju_i_kodu_komunikatu(tmp_path: Path, stop: Any) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = stopped_record(stop)
    # Rekord wersji 2 (bez dróg zapisu) z pliku metryk taty sprzed tej wersji narzędzia sprawdza się tak samo.
    from_older_tool = {key: value for key, value in record.items() if key != "routes"} | {"schema_version": 2}

    with pytest.raises(ValueError, match="Niepoprawny rekord metryk"):
        MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)
    metrics_path.write_text(json.dumps(record) + "\n" + json.dumps(from_older_tool) + "\n", encoding="utf-8")

    assert MetricsStore(metrics_path, SETTLEMENT_COUNTERS).read() == []


def test_plik_metryk_odrzuca_zatrzymanie_w_zakonczonym_uruchomieniu(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Niepoprawny rekord metryk"):
        MetricsStore(tmp_path / "metrics.jsonl", SETTLEMENT_COUNTERS).append(
            {**completed_record(), "stop": {"kind": "for_tata", "code": "ZLE_SKUTECZNE"}}
        )


@pytest.mark.parametrize("catalog", [PREPARATION_SAMPLES, SETTLEMENT_SAMPLES], ids=["przygotowanie", "przebieg"])
def test_kazdy_kod_komunikatu_procesu_miesci_sie_w_rekordzie_metryk(tmp_path: Path, catalog: Samples) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    codes = sorted({sample().code for samples in catalog.values() for sample in samples})

    for code in codes:
        MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(stopped_record({"kind": "for_tata", "code": code}))

    assert [record["stop"]["code"] for record in MetricsStore(metrics_path, SETTLEMENT_COUNTERS).read()] == codes


def test_plik_metryk_odrzuca_rekord_ze_sciezka(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)

    with pytest.raises(ValueError, match="Niepoprawny rekord metryk"):
        MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append({**record, "source_path": str(tmp_path / PERIOD)})

    assert MetricsStore(metrics_path, SETTLEMENT_COUNTERS).read() == [record]
    assert metrics_path.read_text(encoding="utf-8").count("\n") == 1


@pytest.mark.parametrize(
    "torn",
    [b'{"schema_version":1', b'{"schema_version":1\n', b"\xff\n"],
    ids=["bez-konca-linii", "z-koncem-linii", "nie-utf8"],
)
def test_plik_metryk_naprawia_ucieta_ostatnia_linie(tmp_path: Path, torn: bytes) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)
    with metrics_path.open("ab") as stream:
        stream.write(torn)

    MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)

    assert [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()] == [record, record]
    assert metrics_path.read_bytes().endswith(b"\n")


@pytest.mark.parametrize("line_end", [b"\n", b""], ids=["z-koncem-linii", "bez-konca-linii"])
def test_plik_metryk_zachowuje_pelny_rekord_innej_wersji_narzedzia(tmp_path: Path, line_end: bytes) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    record = completed_record()
    other_version = {**record, "counters": {**record["counters"], "nowy_licznik": 3}}
    MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)
    with metrics_path.open("ab") as stream:
        stream.write(json.dumps(other_version).encode("utf-8") + line_end)

    MetricsStore(metrics_path, SETTLEMENT_COUNTERS).append(record)

    assert [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()] == [
        record,
        other_version,
        record,
    ]
    assert MetricsStore(metrics_path, SETTLEMENT_COUNTERS).read() == [record, record]
