"""Przygotowanie pliku zbiorczego z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka."""

from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path
import sys
import threading
import time
from typing import Any, NoReturn

from openpyxl import load_workbook
import pytest

from rozliczenia import tool_files
from rozliczenia import preparation_process
from rozliczenia.telemetry import MetricsStore, metric_record
from rozliczenia.centrum import run_view
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.runs import RUN_THREAD_PREFIX
from rozliczenia.centrum.settings.quantity_rules import RULES_FILE

from tests.fixtures.centrum import centrum as bare_centrum, finished_view, phase_states, run_events, views_until
from atrapy.preparation import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    RegisterRow,
    incomplete_period_rows,
    register_order,
)
from tests.fixtures.centrum_processes import (
    PERIOD_MONDAY,
    TODAY,
    PreparingCentrum,
    Surroundings,
    on_register_read,
    preparing_centrum,
    run_to_end,
    write_dad_quantity_rules,
)
from tests.fixtures.potomne import wait_for

# Podsumowanie wyniku na domyślnym syntetycznym Rejestrze zleceń, takie samo w podglądzie i przy Uruchom.
SUMMARY: dict[str, Any] = {
    "figures": [
        {"label": "Zlecenia okresu", "value": 4, "unit": "count"},
        {"label": "Zlecenia skuteczne", "value": 3, "unit": "count"},
        {"label": "Pominięte puste wiersze", "value": 5, "unit": "count"},
    ],
    "counts": {
        "title": "Zlecenia na dzień",
        "counts": [
            {"label": "wt 08.09.2026", "count": 1},
            {"label": "śr 09.09.2026", "count": 1},
            {"label": "czw 10.09.2026", "count": 0},
            {"label": "pt 11.09.2026", "count": 0},
            {"label": "sob 12.09.2026", "count": 1},
            {"label": "niedz 13.09.2026", "count": 0},
            {"label": "pon 14.09.2026", "count": 1},
        ],
        "zero_warns": True,
    },
    "files": [
        {"name": INTERNAL_SETTLEMENT_NAME, "kind": "internal_settlement"},
        {"name": COLLECTIVE_FILE_NAME, "kind": "collective_file"},
    ],
    "worker_settlements": None,
    "intermax_copy": None,
}
# Domyślny syntetyczny Rejestr ma w URZĄDZENIA tylko urządzenia nieznane Regułom ilości.
QUANTITY_WARNINGS_WHERE = [
    f"plik {COLLECTIVE_FILE_NAME}, wiersze 18, 19, 20",
    f"plik {COLLECTIVE_FILE_NAME}, kolumny Y, AB, AD, AJ, AK, AL i AM",
]


def test_podglad_bez_zapisu_pokazuje_plan_i_nie_tworzy_plikow_ani_folderu_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    started = centrum.start(dry_run=True)
    finished = finished_view(centrum.client)

    assert started.status_code == 200
    assert started.json()["state"] == "running"
    assert finished["run"]["process"] == "preparation"
    assert (finished["run"]["period"], finished["run"]["mode"]) == (PERIOD, "DRY-RUN")
    assert finished["run"]["confirms_readiness"] is False
    result = finished["result"]
    assert (result["result"], result["ending"], result["next_action"]) == ("OK", "finished", "run")
    assert result["headline"] == "Podgląd gotowy · nic nie zapisano"
    assert result["collective_file_prepared"] is False
    assert result["summary"] == SUMMARY
    assert result["stops"] == []
    assert [warning["where"] for warning in result["warnings"]] == QUANTITY_WARNINGS_WHERE
    assert [(figure["label"], figure["unit"]) for figure in finished["progress"]["figures"]] == [
        ("Ostrzeżenia", "count"),
        ("Czas uruchomienia", "ms"),
    ]
    assert list(centrum.fixture.periods_directory.iterdir()) == []
    [record] = centrum.metric_records()
    assert (record["mode"], record["period"], record["result"]) == ("DRY-RUN", PERIOD, "OK")


def test_uruchom_publikuje_oba_pliki_okresu_i_zmienia_status_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    centrum.start(dry_run=False)
    result = finished_view(centrum.client)["result"]
    board = centrum.client.get("/api/periods").json()

    assert (result["result"], result["next_action"]) == ("WYMAGA_SPRAWDZENIA", "open_collective_file")
    assert result["headline"] == "Plik zbiorczy przygotowany · wymaga sprawdzenia"
    assert result["summary"] == SUMMARY
    assert [warning["where"] for warning in result["warnings"]] == QUANTITY_WARNINGS_WHERE
    assert sorted(path.name for path in centrum.fixture.period_directory.iterdir()) == [
        COLLECTIVE_FILE_NAME,
        INTERNAL_SETTLEMENT_NAME,
    ]
    [row] = [row for row in board["periods"] if row["token"] == PERIOD]
    assert row["status_label"] == "Plik zbiorczy przygotowany"
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"], record["counters"]["successful_orders"]) == (
        "RUN",
        "WYMAGA_SPRAWDZENIA",
        3,
    )


def awaiting_decision(tmp_path: Path) -> tuple[PreparingCentrum, dict[str, Any]]:
    """Uruchom na niepełnym okresie, które czeka na decyzję taty."""

    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    centrum.start(dry_run=False)
    return centrum, views_until(centrum.client, "awaiting_decision")[-1]


def decide(centrum: PreparingCentrum, view: dict[str, Any], answer: str) -> Any:
    return centrum.client.post(f"/api/runs/{view['run']['id']}/decision", json={"answer": answer})


INCOMPLETE_ORDERS_PER_DAY = [
    {"label": "wt 08.09.2026", "count": 1},
    {"label": "śr 09.09.2026", "count": 1},
    {"label": "czw 10.09.2026", "count": 0},
    {"label": "pt 11.09.2026", "count": 0},
    {"label": "sob 12.09.2026", "count": 1},
    {"label": "niedz 13.09.2026", "count": 0},
    {"label": "pon 14.09.2026", "count": 0},
]


def test_niepelny_okres_czeka_na_decyzje_taty_z_zleceniami_na_dzien(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    assert view["decision"] == {
        "question": "Kontynuować mimo niepełnego okresu?",
        "message": {
            "what": (
                "Ostatnie zlecenie okresu jest z soboty 12.09.2026, a okres kończy się w poniedziałek 14.09.2026. "
                "Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu."
            ),
            "where": f"plik {centrum.fixture.register_path.name}, arkusz ZLECENIA, okres {PERIOD}",
            "action": (
                "Sprawdź liczby zleceń na dzień. Jeśli brakuje zleceń, przerwij, uzupełnij eksport w Rejestrze "
                "zleceń, zapisz go i uruchom ponownie. Jeśli okres jest pełny, kontynuuj."
            ),
        },
        "counts": {"title": "Zlecenia na dzień", "counts": INCOMPLETE_ORDERS_PER_DAY, "zero_warns": True},
    }
    assert [phase["state"] for phase in view["progress"]["phases"]] == ["completed", "completed", "completed", "pending"]
    assert list(centrum.fixture.periods_directory.iterdir()) == []
    decide(centrum, view, "abort")


def test_kontynuuj_przy_niepelnym_okresie_publikuje_pliki_z_ostrzezeniem(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    decided = decide(centrum, view, "continue")
    result = finished_view(centrum.client)["result"]

    assert (decided.status_code, decided.json()["state"]) == (200, "running")
    assert (result["result"], result["ending"]) == ("WYMAGA_SPRAWDZENIA", "finished")
    assert [warning["what"] for warning in result["warnings"]][:1] == [view["decision"]["message"]["what"]]
    assert len(result["warnings"]) == 3
    assert result["summary"]["counts"] == {"title": "Zlecenia na dzień", "counts": INCOMPLETE_ORDERS_PER_DAY, "zero_warns": True}
    assert centrum.fixture.collective_file_path.is_file()
    assert centrum.fixture.internal_settlement_path.is_file()


def test_przerwij_bez_zapisu_zatrzymuje_z_trzema_czesciami_dla_centrum(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    decide(centrum, view, "abort")
    finished = finished_view(centrum.client)
    result = finished["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("BLAD_KRYTYCZNY", "declined", "rerun")
    assert (result["headline"], result["stop_kind"], result["diagnosis"], result["report"]) == (
        "Przerwano",
        "declined",
        None,
        None,
    )
    assert (result["files_unchanged"], result["opens"], finished["run"]["register_name"]) == (
        True,
        "order_register",
        "Rejestr zleceń",
    )
    assert result["stops"] == [
        {
            "what": "Przerwano z powodu niepełnego okresu, zgodnie z odpowiedzią. Nie utworzono żadnego pliku.",
            "where": f"okres {PERIOD}",
            "action": (
                "Uzupełnij eksport zleceń w Rejestrze zleceń, zapisz go, zamknij i uruchom ponownie. "
                "Jeśli okres jest pełny, przy decyzji wybierz „Kontynuuj”."
            ),
        }
    ]
    assert list(centrum.fixture.periods_directory.iterdir()) == []
    [record] = centrum.metric_records()
    assert (record["result"], record["phase_durations_ms"]["Zapisywanie"]) == ("BLAD_KRYTYCZNY", 0)
    assert record["stop"] == {"kind": "for_tata", "code": "PRZERWANO_NIEPELNY_OKRES"}


def test_czas_czekania_na_decyzje_nie_wlicza_sie_do_czasu_ani_metryk(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    waited_ms = 300

    started = time.perf_counter()
    centrum.start(dry_run=False)
    view = views_until(centrum.client, "awaiting_decision")[-1]
    time.sleep(waited_ms / 1000)
    decide(centrum, view, "continue")
    views = views_until(centrum.client, "finished")
    not_waiting_ms = (time.perf_counter() - started) * 1000 - waited_ms

    [record] = centrum.metric_records()
    assert record["total_duration_ms"] <= not_waiting_ms
    assert all(shown_time(view) <= not_waiting_ms for view in views if view["state"] == "running")


def shown_time(view: dict[str, Any]) -> int:
    """„Czas uruchomienia” z liczb na żywo Przygotowania pliku zbiorczego, w ms."""

    [time_ms] = [figure["value"] for figure in view["progress"]["figures"] if figure["label"] == "Czas uruchomienia"]
    assert isinstance(time_ms, int)
    return time_ms


def test_decyzja_czeka_po_ponownym_podlaczeniu_i_odswiezeniu_karty(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    [first_after_reconnect] = views_until(centrum.client, "awaiting_decision")
    after_refresh = centrum.client.get("/api/runs/current").json()

    assert first_after_reconnect == view
    assert after_refresh == view
    decide(centrum, view, "abort")


def test_drugie_uruchomienie_w_trakcie_dostaje_bezpieczny_komunikat_trwa_juz(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    second = centrum.start(dry_run=True)

    assert second.status_code == 409
    assert second.json() == {
        "message": (
            f"Trwa już Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
            "Poczekaj na jego wynik w Uruchomieniach."
        )
    }
    assert centrum.client.get("/api/runs/current").json() == view
    decide(centrum, view, "abort")
    assert finished_view(centrum.client)["state"] == "finished"
    assert centrum.start(dry_run=True).status_code == 200


def test_wynik_trafia_na_karte_gdy_druga_karta_klika_uruchom_zaraz_po_koncu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Druga karta ze starym widokiem klika Uruchom, gdy wątek pierwszego Uruchomienia buduje widok jego wyniku (#723).

    Pierwsza karta śledzi strumień i dostaje wynik obu Uruchomień, choć druga klika ponownie od razu po odmowie.
    """

    centrum = preparing_centrum(tmp_path)
    building = threading.Event()
    go = threading.Event()

    class HeldResult(runs_contract.RunFinished):
        """Widok wyniku, którego budowa w wątku pierwszego Uruchomienia czeka na kliknięcie drugiej karty."""

        def __init__(self, **data: Any) -> None:
            if threading.current_thread().name.startswith(RUN_THREAD_PREFIX) and not go.is_set():
                building.set()
                assert go.wait(30)
            super().__init__(**data)

    monkeypatch.setattr(runs_contract, "RunFinished", HeldResult)
    first = centrum.start(dry_run=True).json()["run"]["id"]
    seen: list[tuple[str, str]] = []
    reading = threading.Event()

    def first_tab() -> None:
        for event in run_events(centrum.client):
            view = event["view"]
            seen.append((view["state"], view["run"]["id"]))
            reading.set()
            if view["state"] == "finished" and view["run"]["id"] != first:
                return

    reader = threading.Thread(target=first_tab, daemon=True)
    reader.start()
    assert reading.wait(30)
    assert building.wait(30)
    clicks = [centrum.start(dry_run=True)]
    go.set()

    def accepted() -> bool:
        if clicks[-1].status_code != 200:
            clicks.append(centrum.start(dry_run=True))
        return bool(clicks[-1].status_code == 200)

    assert wait_for(accepted)
    second = clicks[-1].json()["run"]["id"]
    reader.join(30)

    assert not reader.is_alive()
    assert ("finished", first) in seen
    assert ("finished", second) in seen
    assert {run["run_id"] for run in centrum.client.get("/api/metrics").json()["runs"]} == {first, second}


def test_decyzja_poza_oczekiwaniem_jest_odrzucona(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)
    decide(centrum, view, "abort")
    finished_view(centrum.client)

    again = decide(centrum, view, "continue")
    unknown = centrum.client.post("/api/runs/nieznane/decision", json={"answer": "continue"})

    assert (again.status_code, again.json()) == (409, {"message": "To Uruchomienie procesu nie czeka na decyzję."})
    assert (unknown.status_code, unknown.json()) == (404, {"message": "Nie ma takiego Uruchomienia procesu."})


def test_strumien_pokazuje_etapy_po_kolei_z_licznikami_i_decyzja_miedzy_planowaniem_a_zapisywaniem(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    seen: list[tuple[str, tuple[str, ...], list[str], int]] = []

    for event in run_events(centrum.client):
        view = event["view"]
        if view["state"] == "idle":
            centrum.start(dry_run=False)
            continue
        figures = view["progress"]["figures"]
        shown = (
            view["state"],
            tuple(phase_states(view).values()),
            [figure["label"] for figure in figures],
            figures[0]["value"],
        )
        if not seen or seen[-1] != shown:
            seen.append(shown)
        if view["state"] == "awaiting_decision":
            decide(centrum, view, "continue")
        if view["state"] == "finished":
            break

    labels = ["Ostrzeżenia", "Czas uruchomienia"]
    pending, running, completed = "pending", "running", "completed"
    assert seen == [
        ("running", (pending, pending, pending, pending), labels, 0),
        ("running", (running, pending, pending, pending), labels, 0),
        ("running", (completed, pending, pending, pending), labels, 0),
        ("running", (completed, running, pending, pending), labels, 0),
        ("running", (completed, completed, pending, pending), labels, 0),
        ("running", (completed, completed, running, pending), labels, 0),
        ("running", (completed, completed, completed, pending), labels, 0),
        ("running", (completed, completed, completed, pending), labels, 3),
        ("awaiting_decision", (completed, completed, completed, pending), labels, 3),
        ("running", (completed, completed, completed, pending), labels, 3),
        ("running", (completed, completed, completed, running), labels, 3),
        ("running", (completed, completed, completed, completed), labels, 3),
        ("finished", (completed, completed, completed, completed), labels, 3),
    ]


def test_nienadpisywanie_zatrzymuje_bez_zmiany_istniejacego_pliku_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.period_directory.mkdir()
    centrum.fixture.collective_file_path.write_bytes(b"reczne poprawki taty")

    centrum.start(dry_run=False)
    view = finished_view(centrum.client)
    result = view["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("BLAD_KRYTYCZNY", "stop", "rerun")
    assert (result["headline"], result["files_unchanged"], result["opens"]) == ("Do poprawy", True, None)
    [stop] = result["stops"]
    assert stop["what"].startswith("Plik tego okresu już istnieje, więc nie został nadpisany.")
    assert stop["where"] == f"folder INEA\\{PERIOD}, plik {COLLECTIVE_FILE_NAME}"
    assert stop["action"].startswith("Sprawdź, czy wybrano właściwy okres.")
    assert phase_states(view)["Sprawdzanie"] == "failed"
    assert centrum.fixture.collective_file_path.read_bytes() == b"reczne poprawki taty"
    assert not centrum.fixture.internal_settlement_path.exists()
    [record] = centrum.metric_records()
    assert (record["completed"], record["result"]) == (False, "BLAD_KRYTYCZNY")


def test_nieoczekiwany_wyjatek_pokazuje_trzy_czesci_bez_tekstu_wyjatku_i_danych_klientow(tmp_path: Path) -> None:
    def fail_unexpectedly(path: Path) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(source=on_register_read(fail_unexpectedly)))

    centrum.start(dry_run=False)
    view = finished_view(centrum.client)
    shown = json.dumps(view, ensure_ascii=False)

    assert (view["result"]["ending"], view["result"]["headline"]) == ("unexpected", "Błąd")
    assert view["result"]["stops"] == [
        {
            "what": "Wystąpił nieoczekiwany błąd. Nie utworzono żadnego pliku.",
            "where": "Przygotowanie pliku zbiorczego",
            "action": "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie.",
        }
    ]
    assert phase_states(view)["Sprawdzanie"] == "failed"
    assert "SYN-" not in shown
    assert "RuntimeError" not in shown
    assert list(centrum.fixture.periods_directory.iterdir()) == []


def test_niepokazane_podsumowanie_po_zapisie_mowi_zeby_nie_uruchamiac_ponownie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.engines.fail_summary = True

    centrum.start(dry_run=False)
    result = finished_view(centrum.client)["result"]

    assert (result["ending"], result["next_action"], result["summary"]) == ("after_engine", "open_collective_file", None)
    assert result["stops"] == [
        {
            "what": "Pliki okresu powstały, ale nie udało się pokazać podsumowania.",
            "where": "Przygotowanie pliku zbiorczego",
            "action": (
                "Nie uruchamiaj ponownie: oba pliki okresu już są. "
                "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
            ),
        }
    ]
    assert "SYN-" not in json.dumps(result, ensure_ascii=False)
    assert centrum.fixture.collective_file_path.is_file()


def test_wybor_okresu_proponuje_ostatni_pelny_okres_i_starsze_ze_statusem_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.period_directory.mkdir()
    centrum.fixture.collective_file_path.touch()

    processes = centrum.client.get("/api/runs/setup").json()["processes"]
    setup = processes[0]

    assert [(process["process"], process["reads"]) for process in processes] == [
        ("preparation", "register"),
        ("efenix", "collective_file"),
        ("settlement", "collective_file"),
    ]
    assert (setup["process"], setup["title"], setup["blocker"]) == ("preparation", "Przygotowanie pliku zbiorczego", None)
    assert setup["reminder"] == "Zapisz i zamknij Rejestr zleceń w Excelu"
    assert (setup["confirms_readiness"], setup["preview_hint"]) == (
        False,
        "Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
    )
    assert setup["preselected_period"] == PERIOD
    assert [(choice["token"], choice["last_complete"]) for choice in setup["periods"][:3]] == [
        (PERIOD, True),
        ("01_07_09_2026", False),
        ("25_31_08_2026", False),
    ]
    assert len(setup["periods"]) == 8
    assert setup["periods"][0]["status_label"] == "Plik zbiorczy przygotowany"
    assert setup["periods"][1]["status_label"] == "Brak plików okresu"


def test_wybor_okresu_pamieta_udany_podglad_bez_zapisu_takze_po_odswiezeniu_karty(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    def previewed() -> dict[str, bool]:
        setup, _efenix, _settlement = centrum.client.get("/api/runs/setup").json()["processes"]
        return {choice["token"]: choice["previewed"] for choice in setup["periods"][:2]}

    before = previewed()
    centrum.start(dry_run=True)
    finished_view(centrum.client)

    assert before == {PERIOD: False, "01_07_09_2026": False}
    assert previewed() == {PERIOD: True, "01_07_09_2026": False}


def test_uruchom_bez_podgladu_i_podglad_wymagajacy_sprawdzenia_nie_sa_udanym_podgladem(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    MetricsStore(centrum.metrics_path, preparation_process.PROCESS.counter_names).append(
        metric_record(
            mode="DRY-RUN",
            period="01_07_09_2026",
            started_at="2026-09-08T08:00:00+00:00",
            total_duration_ms=1000,
            phase_durations_ms={},
            ending={"kind": "for_tata", "code": "ZLE_SKUTECZNE"},
            counters=dict.fromkeys(preparation_process.PROCESS.counter_names, 0),
        )
    )

    centrum.start(dry_run=False)
    finished_view(centrum.client)
    setup, _efenix, _settlement = centrum.client.get("/api/runs/setup").json()["processes"]

    assert [choice["previewed"] for choice in setup["periods"][:2]] == [False, False]


def test_awaria_adaptera_po_rdzeniu_trafia_do_dziennika_bez_tekstu_wyjatku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ostatnia siatka Centrum: rdzeń skończył i zapisał metryki, ale adapter nie zbudował wyniku dla przeglądarki."""

    centrum = preparing_centrum(tmp_path)
    run_outcome = runs_contract.RunOutcome
    built: list[str] = []

    def broken_once(**fields: Any) -> runs_contract.RunOutcome:
        built.append(fields["ending"])
        if len(built) == 1:
            raise ValueError("synthetic contract failure SYN-001")
        return run_outcome(**fields)

    monkeypatch.setattr(runs_contract, "RunOutcome", broken_once)

    centrum.start(dry_run=True)
    result = finished_view(centrum.client)["result"]
    log = centrum.log_path.read_text(encoding="utf-8")

    assert (result["result"], result["ending"], result["next_action"]) == ("BLAD_KRYTYCZNY", "after_engine", "rerun")
    assert result["stops"] == [
        {
            "what": "Nie udało się pokazać wyniku Uruchomienia procesu.",
            "where": "Centrum rozliczeń",
            "action": "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie.",
        }
    ]
    assert 'nieoczekiwany-wyjatek typ=ValueError miejsce="wynik Uruchomienia procesu"' in log
    assert "SYN-" not in log
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"]) == ("DRY-RUN", "OK")


def test_karta_startu_mowi_ktore_pliki_przygotowania_sa_otwarte_w_excelu_az_do_ich_zamkniecia(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    fixture = centrum.fixture
    worker_template = tool_files.config_dir(tmp_path) / tool_files.WORKER_TEMPLATE.name
    workbooks = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path, worker_template)
    locks = [path.with_name(f"~${path.name}") for path in workbooks]

    def open_in_excel() -> set[tuple[str, ...]]:
        setup, _efenix, _settlement = centrum.client.get("/api/runs/setup").json()["processes"]
        return {tuple(choice["open_in_excel"]) for choice in setup["periods"]}

    for lock in locks:
        lock.touch()
    opened = open_in_excel()
    for lock in locks:
        lock.unlink()

    assert opened == {
        (
            "Rejestr zleceń jest otwarty w Excelu. Zapisz go i zamknij. Jeśli Excel jest zamknięty, usuń z tego "
            f"samego folderu pozostawiony plik ~${fixture.register_path.name}.",
            "Wzorzec rozliczenia wewnętrznego jest otwarty w Excelu. Zamknij go bez zapisywania zmian. Jeśli Excel "
            f"jest zamknięty, usuń z tego samego folderu pozostawiony plik ~${fixture.internal_template_path.name}.",
            "Wzorzec pliku zbiorczego jest otwarty w Excelu. Zamknij go bez zapisywania zmian. Jeśli Excel jest "
            f"zamknięty, usuń z tego samego folderu pozostawiony plik ~${fixture.collective_template_path.name}.",
        )
    }
    assert open_in_excel() == {()}


@pytest.mark.parametrize(
    ("workbooks", "reminder"),
    [
        ((), "Zapisz i zamknij Rejestr zleceń w Excelu"),
        (("register_path",), "Zapisz i zamknij Rejestr zleceń w Excelu"),
        (("register_path", "collective_template_path"), "Zapisz i zamknij Rejestr zleceń w Excelu"),
        (("internal_template_path",), None),
        (("collective_template_path",), None),
    ],
)
def test_stopka_karty_startu_nie_kaze_zamknac_rejestru_zlecen_gdy_uruchom_blokuje_tylko_wzorzec(
    tmp_path: Path, workbooks: tuple[str, ...], reminder: str | None
) -> None:
    centrum = preparing_centrum(tmp_path)
    for workbook in workbooks:
        path: Path = getattr(centrum.fixture, workbook)
        path.with_name(f"~${path.name}").touch()

    setup, _efenix, _settlement = centrum.client.get("/api/runs/setup").json()["processes"]

    assert {choice["reminder"] for choice in setup["periods"]} == {reminder}


@pytest.mark.parametrize("workbook", ["register_path", "internal_template_path", "collective_template_path"])
def test_rada_karty_startu_i_zatrzymania_nazywa_ten_sam_pozostawiony_plik_blokady(
    tmp_path: Path, workbook: str
) -> None:
    centrum = preparing_centrum(tmp_path)
    path: Path = getattr(centrum.fixture, workbook)
    leftover = f"pozostawiony plik ~${path.name}"
    path.with_name(f"~${path.name}").touch()
    setup, _efenix, _settlement = centrum.client.get("/api/runs/setup").json()["processes"]

    [stop] = run_to_end(centrum, dry_run=True)["result"]["stops"]

    assert {len(choice["open_in_excel"]) for choice in setup["periods"]} == {1}
    assert all(leftover in choice["open_in_excel"][0] for choice in setup["periods"])
    assert leftover in stop["action"]


@pytest.mark.skipif(sys.platform == "win32", reason="chmod w Windows zmienia tylko atrybut „tylko do odczytu”")
def test_rejestr_zlecen_w_folderze_bez_dostepu_nie_psuje_karty_startu(tmp_path: Path) -> None:
    centrum = bare_centrum(tmp_path, today=TODAY)
    folder = tmp_path / "OneDrive"
    folder.mkdir()
    register = folder / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    register.touch()
    register.with_name(f"~${register.name}").touch()
    centrum.platform.chosen_files.append(register)
    centrum.client.post("/api/settings/register/choose")
    folder.chmod(0)
    try:
        answer = centrum.client.get("/api/runs/setup")
    finally:
        folder.chmod(0o755)

    assert answer.status_code == 200
    setup, _efenix, _settlement = answer.json()["processes"]
    assert {tuple(choice["open_in_excel"]) for choice in setup["periods"]} == {()}


def test_bez_wskazanego_rejestru_zlecen_uruchomienie_jest_odrzucone(tmp_path: Path) -> None:
    client = bare_centrum(tmp_path, today=TODAY).client

    setup, _efenix, _settlement = client.get("/api/runs/setup").json()["processes"]
    refused = client.post("/api/runs", json={"process": "preparation", "period": PERIOD, "mode": "DRY-RUN"})

    assert setup["blocker"] == "Najpierw wskaż Rejestr zleceń i folder okresów."
    assert (refused.status_code, refused.json()) == (409, {"message": "Najpierw wskaż Rejestr zleceń i folder okresów."})
    assert client.get("/api/runs/current").json() == {"state": "idle", "previous": None}


def test_okres_spoza_kalendarza_okresow_jest_odrzucony(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    refused = centrum.start(dry_run=True, period="08_14_9_2026")

    assert (refused.status_code, refused.json()) == (404, {"message": "Nie ma takiego okresu."})
    assert not centrum.metrics_path.exists()


def test_awaria_podgladu_na_zywo_nie_zmienia_wyniku_zapisu_ani_metryk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Decyzja taty zatrzymuje Uruchomienie po awarii podglądu, więc karta widzi je w trakcie także pod obciążeniem.
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    shown_before_start = run_view.ProcessView.progress
    calls = itertools.count()

    def broken_after_start(view: Any, *args: Any, **kwargs: Any) -> Any:
        if next(calls) == 0:
            return shown_before_start(view, *args, **kwargs)
        raise ValueError("synthetic Centrum view failure")

    monkeypatch.setattr(run_view.ProcessView, "progress", broken_after_start)

    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]
    running = decide(centrum, waiting, "continue").json()
    finished = finished_view(centrum.client)
    result = finished["result"]

    assert (running["state"], running["progress_stale"]) == ("running", True)
    assert finished["progress_stale"] is True
    assert (result["result"], result["ending"]) == ("WYMAGA_SPRAWDZENIA", "finished")
    assert result["technical_notes"] == ["Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."]
    assert centrum.fixture.collective_file_path.is_file()
    [record] = centrum.metric_records()
    assert (record["result"], record["completed"]) == ("WYMAGA_SPRAWDZENIA", True)


def test_zamkniecie_centrum_w_trakcie_uruchomienia_procesu_jest_odrzucone(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    refused = centrum.client.post("/api/shutdown")
    decide(centrum, view, "abort")
    finished_view(centrum.client)
    accepted = centrum.client.post("/api/shutdown")

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                f"Trwa Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
                "Poczekaj na jego wynik w Uruchomieniach, potem zamknij Centrum rozliczeń."
            )
        },
    )
    assert accepted.status_code == 202


def test_dziennik_centrum_ma_poczatek_i_koniec_uruchomienia_z_wynikiem_bez_danych_klientow(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    centrum.start(dry_run=False)
    finished_view(centrum.client)

    log = centrum.log_path.read_text(encoding="utf-8")
    events = [line.split(" ", 1)[1] for line in log.splitlines()]
    assert [event for event in events if event.startswith("uruchomienie-")] == [
        f"uruchomienie-start proces=preparation tryb=RUN okres={PERIOD}",
        f"uruchomienie-koniec proces=preparation tryb=RUN okres={PERIOD} wynik=WYMAGA_SPRAWDZENIA koniec=finished",
    ]
    assert "SYN-" not in log
    assert str(centrum.fixture.periods_directory) not in log


NOKIA_ROUTER_Z = "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia-router}"


def test_przygotowanie_liczy_ilosci_regulami_z_ustawien_z_chwili_startu_a_zmiana_w_trakcie_dziala_od_nastepnego(
    tmp_path: Path,
) -> None:
    def tata_changes_rules(_path: Path) -> None:
        write_dad_quantity_rules(centrum.tool, RULES_FILE, NOKIA_ROUTER_Z, NOKIA_ROUTER_Z.replace("wartosc: 1", "wartosc: 3"))

    rows: list[RegisterRow] = [{**register_order(1, PERIOD_MONDAY), "URZĄDZENIA": "nokia zte"}]
    centrum = preparing_centrum(tmp_path, rows, surroundings=Surroundings(source=on_register_read(tata_changes_rules)))

    run_to_end(centrum, dry_run=False)
    during = _quantity(centrum, "Z18")
    shutil.rmtree(centrum.fixture.period_directory)
    run_to_end(centrum, dry_run=False)

    assert (during, _quantity(centrum, "Z18")) == (1, 3)


def _quantity(centrum: PreparingCentrum, cell: str) -> object:
    workbook = load_workbook(centrum.fixture.collective_file_path, read_only=True)
    try:
        return workbook.active[cell].value  # type: ignore[index]
    finally:
        workbook.close()
