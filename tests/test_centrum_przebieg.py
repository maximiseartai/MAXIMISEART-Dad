"""Przebieg rozliczeń z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, NoReturn

from fastapi.testclient import TestClient
import pytest

from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import PeriodFolder, collective_file_name_with
from rozliczenia import settlement_process
from rozliczenia.centrum import run_view
from rozliczenia.telemetry import MetricsStore

from tests.fixtures.centrum import centrum as bare_centrum, finished_view, phase_states, run_events
from tests.fixtures.centrum_processes import (
    TODAY,
    WORKER_SETTLEMENTS,
    SettlingCentrum,
    run_to_end,
    settling_centrum,
)
from atrapy.settlement import PERIOD, SOURCE_NAME
from atrapy.workbooks import replace_cells

# Syntetyczny Plik zbiorczy: dwa zlecenia Adriana, jedno Darka, a Kamil bez zleceń ma pusty szablon.
WORKER_SETTLEMENT_ROWS = [
    {"worker": "Adrian Testowy", "file": f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx", "orders": 2, "empty": False},
    {"worker": "Darek Fikcyjny", "file": f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx", "orders": 1, "empty": False},
    {"worker": "Kamil Syntetyczny", "file": f"Rozliczenie {PERIOD} - Kamil Syntetyczny.xlsx", "orders": 0, "empty": True},
]


def test_podglad_bez_zapisu_pokazuje_plan_plikow_na_wykonawce_bez_folderu_rozliczen_pracownikow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    started = centrum.start(dry_run=True)
    assert (started.status_code, started.json()["state"]) == (200, "running")
    finished = finished_view(centrum.client)

    assert (finished["run"]["process"], finished["run"]["title"]) == ("settlement", "Przebieg rozliczeń")
    assert finished["run"]["confirms_readiness"] is True
    result = finished["result"]
    assert (result["result"], result["ending"], result["next_action"]) == ("OK", "finished", "run")
    assert result["headline"] == "Podgląd gotowy · nic nie zapisano"
    assert result["summary"] == {
        "figures": [
            {"label": "Wiersze danych", "value": 3, "unit": "count"},
            {"label": "Planowane szablony", "value": 2, "unit": "count"},
            {"label": "Puste szablony", "value": 1, "unit": "count"},
        ],
        "counts": None,
        "files": [],
        "worker_settlements": WORKER_SETTLEMENT_ROWS,
        "intermax_copy": None,
    }
    assert (result["stops"], result["warnings"]) == ([], [])
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["period"], record["result"]) == ("DRY-RUN", PERIOD, "OK")
    phases = finished["progress"]["phases"]
    assert [phase["phase"] for phase in phases] == ["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]
    assert {phase["phase"]: phase["duration_ms"] for phase in phases} == record["phase_durations_ms"]


def test_uruchom_publikuje_folder_rozliczen_pracownikow_i_zmienia_status_okresu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    result = run_to_end(centrum, dry_run=False)["result"]
    board = centrum.client.get("/api/periods").json()

    assert (result["result"], result["ending"], result["next_action"]) == ("OK", "finished", "open_worker_settlements_folder")
    assert result["headline"] == "Rozliczenia pracowników gotowe"
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Zapisane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME, WORKER_SETTLEMENTS]
    assert result["summary"]["worker_settlements"] == WORKER_SETTLEMENT_ROWS
    assert sorted(path.name for path in centrum.worker_settlements.iterdir()) == [
        file["file"] for file in WORKER_SETTLEMENT_ROWS
    ]
    [row] = [row for row in board["periods"] if row["token"] == PERIOD]
    [folder] = [file for file in row["files"] if file["target"] == "worker_settlements_folder"]
    assert (row["status_label"], folder["count"]) == ("Rozliczenia pracowników gotowe", 3)
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"], record["counters"]["written"]) == ("RUN", "OK", 2)


def test_w_ukladzie_folderow_taty_uruchom_publikuje_rozliczenia_pracownikow_w_folderze_miesiaca(
    tmp_path: Path,
) -> None:
    centrum = settling_centrum(tmp_path, dad_layout=True)

    setup = settlement_setup(centrum.client)
    result = run_to_end(centrum, dry_run=False)["result"]

    assert [choice["token"] for choice in setup["periods"]] == [PERIOD]
    assert result["headline"] == "Rozliczenia pracowników gotowe"
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME, WORKER_SETTLEMENTS]


def test_w_ukladzie_folderow_taty_okres_bez_folderu_okresu_jest_odrzucony(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path, dad_layout=True)

    refused = centrum.start(dry_run=True, period="15_21_09_2026")

    assert (refused.status_code, refused.json()) == (
        404,
        {
            "message": "Nie ma folderu 15_21_09_2026 w żadnym folderze miesiąca. "
            "Załóż go w folderze INEA właściwego miesiąca."
        },
    )


def test_nieoczekiwany_wyjatek_pokazuje_komunikat_z_katalogu_bez_tekstu_wyjatku(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.engines.fail_engine = True

    result = run_to_end(centrum, dry_run=False)["result"]
    shown = json.dumps(result, ensure_ascii=False)

    assert (result["result"], result["ending"], result["headline"]) == ("BLAD_KRYTYCZNY", "unexpected", "Błąd")
    assert result["stops"] == [
        {
            "what": "Wystąpił nieoczekiwany błąd. Nie utworzono żadnego pliku pracownika.",
            "where": "Przebieg rozliczeń",
            "action": "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie.",
        }
    ]
    assert "SYN-" not in shown
    assert "RuntimeError" not in shown
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"]) == ("RUN", "BLAD_KRYTYCZNY")


def test_wynik_ktorego_nie_da_sie_pokazac_to_niepokazane_podsumowanie_z_tym_samym_wynikiem_co_w_metrykach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)

    def broken_view(*args: object, **kwargs: object) -> NoReturn:
        raise ValueError("synthetic summary failure SYN-001")

    # Psuje widok wyniku Centrum, nie rdzeń procesu: tylko tak test widzi, że karta oddaje widok do osłony rdzenia.
    monkeypatch.setattr(run_view.ProcessView, "shown", broken_view)

    result = run_to_end(centrum, dry_run=False)["result"]

    assert (result["ending"], result["headline"], result["next_action"]) == ("after_engine", "Błąd", "open_worker_settlements_folder")
    assert result["stops"] == [
        {
            "what": "Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania.",
            "where": "Przebieg rozliczeń",
            "action": (
                "Nie uruchamiaj ponownie: Folder rozliczeń pracowników już jest. "
                "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
            ),
        }
    ]
    assert (result["summary"], result["warnings"]) == (None, [])
    assert "SYN-" not in json.dumps(result, ensure_ascii=False)
    assert centrum.worker_settlements.is_dir()
    [record] = centrum.metric_records()
    assert record["result"] == result["result"] == "BLAD_KRYTYCZNY"


def test_strumien_pokazuje_postep_szablonow_pracownikow_z_biezacym_wykonawca(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    seen: list[tuple[str | None, int, int]] = []

    for event in run_events(centrum.client):
        view = event["view"]
        if view["state"] == "idle":
            centrum.start(dry_run=False)
            continue
        progress = view["progress"]
        shown = (progress["current_worker"], progress["templates_completed"], progress["template_total"])
        if view["state"] == "running" and progress["template_total"] > 0 and (not seen or seen[-1] != shown):
            seen.append(shown)
        if view["state"] == "finished":
            break

    assert seen == [
        (None, 0, 3),
        ("Adrian Testowy", 0, 3),
        (None, 1, 3),
        ("Darek Fikcyjny", 1, 3),
        (None, 2, 3),
        ("Kamil Syntetyczny", 2, 3),
        (None, 3, 3),
    ]


def test_strumien_pokazuje_liczniki_szablonow_pracownikow_na_biezaco(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    seen: list[list[tuple[str, int]]] = []

    for event in run_events(centrum.client):
        view = event["view"]
        if view["state"] == "idle":
            centrum.start(dry_run=False)
            continue
        shown = [(figure["label"], figure["value"]) for figure in view["progress"]["figures"]]
        if view["state"] == "running" and (not seen or seen[-1] != shown):
            seen.append(shown)
        if view["state"] == "finished":
            break

    labels = ["Wiersze danych", "Zapisane szablony", "Puste szablony", "Problemy"]
    assert seen == [
        list(zip(labels, [0, 0, 0, 0], strict=True)),
        list(zip(labels, [2, 1, 0, 0], strict=True)),
        list(zip(labels, [3, 2, 0, 0], strict=True)),
        list(zip(labels, [3, 2, 1, 0], strict=True)),
    ]


def test_podglad_z_nieznanym_wykonawca_wymaga_sprawdzenia_inaczej_niz_sukces(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path, include_unmapped=True)

    view = run_to_end(centrum, dry_run=True)
    result = view["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("WYMAGA_SPRAWDZENIA", "finished", "rerun")
    assert result["headline"] == "Podgląd wymaga sprawdzenia · nic nie zapisano"
    assert result["warnings"] == [
        {
            "what": "Nieznany identyfikator WYKONAWCA: andrzej.nieznany2. Nie ma go w konfiguracji wykonawców.",
            "where": f"plik {SOURCE_NAME}, folder {PERIOD}",
            "action": (
                "Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
                "do konfiguracji wykonawców. Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie."
            ),
        }
    ]
    assert [(figure["label"], figure["value"], figure["unit"]) for figure in view["progress"]["figures"]] == [
        ("Wiersze danych", 3, "count"),
        ("Planowane szablony", 2, "count"),
        ("Puste szablony", 1, "count"),
        ("Problemy", 1, "count"),
    ]
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"]) == ("DRY-RUN", "WYMAGA_SPRAWDZENIA")


PROMISES_ROWS = "Uruchom Podgląd bez zapisu: lista problemów pokaże wiersze."
NAMES_ROW = re.compile(r"\bWiersz \d+\b")


def with_unmapped_worker(tmp_path: Path) -> SettlingCentrum:
    return settling_centrum(tmp_path, include_unmapped=True)


def with_data_row_without_worker(tmp_path: Path) -> SettlingCentrum:
    centrum = settling_centrum(tmp_path)
    replace_cells(centrum.collective_file, {"H20": '<c r="H20"/>'})
    return centrum


@pytest.mark.parametrize(
    ("source", "action"),
    [
        pytest.param(
            with_unmapped_worker,
            "Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
            "do konfiguracji wykonawców. Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie.",
            id="nieznany-wykonawca",
        ),
        pytest.param(
            with_data_row_without_worker,
            f"{PROMISES_ROWS} Wpisz WYKONAWCĘ w kolumnie H tych wierszy. "
            "Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie.",
            id="wiersz-bez-wykonawcy",
        ),
    ],
)
def test_zatrzymanie_odsyla_do_podgladu_po_wiersze_tylko_gdy_podglad_tego_pliku_je_podaje(
    tmp_path: Path, source: Callable[[Path], SettlingCentrum], action: str
) -> None:
    centrum = source(tmp_path)

    [stop] = run_to_end(centrum, dry_run=False)["result"]["stops"]
    warnings = run_to_end(centrum, dry_run=True)["result"]["warnings"]

    assert stop["action"] == action
    assert any(NAMES_ROW.search(warning["what"]) for warning in warnings) is (PROMISES_ROWS in action)


def test_nienadpisywanie_zatrzymuje_bez_zmiany_istniejacego_folderu_rozliczen_pracownikow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.worker_settlements.mkdir()
    corrected = centrum.worker_settlements / f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx"
    corrected.write_bytes(b"reczne poprawki taty")

    view = run_to_end(centrum, dry_run=False)
    result = view["result"]

    assert (result["ending"], result["next_action"]) == ("stop", "rerun")
    assert result["stops"] == [
        {
            "what": (
                "Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany. "
                "Nie utworzono żadnego pliku pracownika."
            ),
            "where": f"folder {PERIOD}\\{WORKER_SETTLEMENTS}",
            "action": (
                "Sprawdź, czy wybrano właściwy okres. Rozliczenia pracowników tego okresu już są w Folderze okresu. "
                "Jeśli trzeba je utworzyć od nowa, najpierw przenieś Folder rozliczeń pracowników poza Folder okresu i uruchom ponownie."
            ),
        }
    ]
    assert phase_states(view)["Sprawdzanie"] == "failed"
    assert [path.name for path in centrum.worker_settlements.iterdir()] == [corrected.name]
    assert corrected.read_bytes() == b"reczne poprawki taty"


def test_zatrzymanie_pokazuje_nazwe_pliku_bez_pelnej_sciezki(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (centrum.period_directory / SOURCE_NAME).unlink()

    result = run_to_end(centrum, dry_run=False)["result"]

    assert result["stops"] == [
        {
            "what": "Nie znaleziono Pliku zbiorczego tego okresu. Nie utworzono żadnego pliku pracownika.",
            "where": f"plik {SOURCE_NAME}, folder {PERIOD}",
            "action": (
                "Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod tą nazwą, i uruchom ponownie. "
                "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy."
            ),
        }
    ]
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_centrum_dopisuje_rekord_do_pliku_metryk_procesu_i_rozpoznaje_swoje_uruchomienie(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    view = run_to_end(centrum, dry_run=True)
    store = MetricsStore(centrum.metrics_path, settlement_process.PROCESS.counter_names)
    [own] = store.read()
    later = (datetime.fromisoformat(own["started_at"]) + timedelta(seconds=1)).isoformat()

    store.append({**own, "started_at": later})
    history = centrum.client.get("/api/metrics").json()["runs"]

    assert (own["mode"], own["result"]) == ("DRY-RUN", "OK")
    assert [(run["process"], run["origin"], run["run_id"]) for run in history] == [
        ("settlement", "cmd", None),
        ("settlement", "centrum", view["run"]["id"]),
    ]


def settlement_setup(client: TestClient) -> dict[str, Any]:
    processes = client.get("/api/runs/setup").json()["processes"]
    [setup] = [setup for setup in processes if setup["process"] == "settlement"]
    assert isinstance(setup, dict)
    return setup


def test_wybor_okresu_to_okresy_z_przygotowanym_plikiem_zbiorczym(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    older = centrum.periods_directory / "01_07_09_2026"
    older.mkdir()
    (older / collective_file_name_with("01_07_09_2026")).touch()
    PeriodFolder(centrum.periods_directory, parse_period_token("25_31_08_2026")).worker_settlements.mkdir(parents=True)

    setup = settlement_setup(centrum.client)

    assert (setup["title"], setup["creates"], setup["blocker"]) == ("Przebieg rozliczeń", "Rozliczenia pracowników", None)
    assert setup["reminder"] == "Zapisz i zamknij Plik zbiorczy w Excelu"
    assert (setup["confirms_readiness"], setup["preview_hint"]) == (
        True,
        "Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
    )
    assert setup["preselected_period"] == PERIOD
    assert [(choice["token"], choice["last_complete"], choice["collective_file"]) for choice in setup["periods"]] == [
        (PERIOD, True, SOURCE_NAME),
        ("01_07_09_2026", False, collective_file_name_with("01_07_09_2026")),
    ]


def test_karta_przebiegu_proponuje_ostatni_pelny_okres_przed_nowszym_i_zaznacza_okres_z_udanym_podgladem(
    tmp_path: Path,
) -> None:
    """Bieżący tydzień też ma Plik zbiorczy, a ostatni pełny okres ma udany Podgląd bez zapisu: karta proponuje ostatni
    pełny okres, choć nowszy stoi wyżej, i zaznacza Podgląd tylko przy nim (przegląd #1134 r1, Drobne 2)."""

    centrum = settling_centrum(tmp_path)
    newer = centrum.periods_directory / "15_21_09_2026"
    newer.mkdir()
    (newer / collective_file_name_with("15_21_09_2026")).touch()
    run_to_end(centrum, dry_run=True)

    setup = settlement_setup(centrum.client)

    assert setup["preselected_period"] == PERIOD
    assert [(choice["token"], choice["previewed"]) for choice in setup["periods"]] == [
        ("15_21_09_2026", False),
        (PERIOD, True),
    ]


def test_karta_startu_mowi_ktore_pliki_przebiegu_sa_otwarte_w_excelu_az_do_ich_zamkniecia(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path, dad_layout=True)
    older = centrum.period_parent / "01_07_09_2026"
    older.mkdir()
    (older / collective_file_name_with("01_07_09_2026")).touch()
    configuration = centrum.configuration
    workbooks = (
        centrum.collective_file,
        configuration.worker_template,
        configuration.internal_template,
        configuration.collective_template,
    )
    locks = [path.with_name(f"~${path.name}") for path in workbooks]

    def open_in_excel() -> dict[str, list[str]]:
        return {choice["token"]: choice["open_in_excel"] for choice in settlement_setup(centrum.client)["periods"]}

    for lock in locks:
        lock.touch()
    opened = open_in_excel()
    for lock in locks:
        lock.unlink()

    template_open = (
        "Wzorzec rozliczenia pracownika jest otwarty w Excelu. Zamknij go bez zapisywania zmian. Jeśli Excel jest "
        f"zamknięty, usuń z tego samego folderu pozostawiony plik ~${configuration.worker_template.name}."
    )
    collective_open = (
        "Plik zbiorczy jest otwarty w Excelu. Zapisz go i zamknij. Jeśli Excel jest zamknięty, usuń z tego samego "
        f"folderu pozostawiony plik ~${centrum.collective_file.name}."
    )
    assert opened == {
        PERIOD: [collective_open, template_open],
        "01_07_09_2026": [template_open],
    }
    assert open_in_excel() == {PERIOD: [], "01_07_09_2026": []}


@pytest.mark.parametrize(
    ("workbooks", "reminder"),
    [
        ((), "Zapisz i zamknij Plik zbiorczy w Excelu"),
        (("collective_file",), "Zapisz i zamknij Plik zbiorczy w Excelu"),
        (("collective_file", "worker_template"), "Zapisz i zamknij Plik zbiorczy w Excelu"),
        (("worker_template",), None),
    ],
)
def test_stopka_karty_startu_nie_kaze_zamknac_pliku_zbiorczego_gdy_uruchom_blokuje_tylko_wzorzec(
    tmp_path: Path, workbooks: tuple[str, ...], reminder: str | None
) -> None:
    centrum = settling_centrum(tmp_path)
    paths = {"collective_file": centrum.collective_file, "worker_template": centrum.configuration.worker_template}
    for workbook in workbooks:
        path = paths[workbook]
        path.with_name(f"~${path.name}").touch()

    [choice] = settlement_setup(centrum.client)["periods"]

    assert choice["reminder"] == reminder


@pytest.mark.parametrize("workbook", ["collective_file", "worker_template"])
def test_rada_karty_startu_i_zatrzymania_nazywa_ten_sam_pozostawiony_plik_blokady(tmp_path: Path, workbook: str) -> None:
    centrum = settling_centrum(tmp_path)
    path = {"collective_file": centrum.collective_file, "worker_template": centrum.configuration.worker_template}[workbook]
    leftover = f"pozostawiony plik ~${path.name}"
    path.with_name(f"~${path.name}").touch()
    [card] = [choice["open_in_excel"] for choice in settlement_setup(centrum.client)["periods"]]

    [stop] = run_to_end(centrum, dry_run=True)["result"]["stops"]

    assert len(card) == 1
    assert leftover in card[0]
    assert leftover in stop["action"]


def test_bez_okresu_z_plikiem_zbiorczym_przebieg_mowi_czego_brakuje(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (centrum.period_directory / SOURCE_NAME).unlink()
    client = bare_centrum(tmp_path / "bez-ustawien", today=TODAY).client

    without_periods = settlement_setup(centrum.client)
    without_settings = settlement_setup(client)
    refused = client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "DRY-RUN"})

    assert without_periods["blocker"] == (
        "Żaden okres nie ma Statusu „Plik zbiorczy przygotowany”. Najpierw przygotuj plik zbiorczy."
    )
    assert without_settings["blocker"] == "Najpierw wskaż folder okresów."
    assert (refused.status_code, refused.json()) == (409, {"message": "Najpierw wskaż folder okresów."})
