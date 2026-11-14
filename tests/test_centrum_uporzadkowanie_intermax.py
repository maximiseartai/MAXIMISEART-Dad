"""Uporządkowanie INTERMAX z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka (#470).

Karta „Uporządkuj INTERMAX” stoi poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty, a okres Uruchomienia to
okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
import pytest

from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import PeriodFolder
from rozliczenia import intermax_copies, preparation_register, workbook_files
from rozliczenia.client_data import empty_memory, guarded
from rozliczenia.dad_files import DadFiles
from rozliczenia.centrum.logs_disk import name_of
from rozliczenia.centrum.run_logs import RunLog

from tests.fixtures.centrum import ToolDirectory, phase_states, views_until, write_report_key
from tests.fixtures.centrum_processes import Surroundings
from tests.fixtures.centrum_intermax import (
    NOW,
    PERIOD,
    REGISTER_NAME,
    Clock,
    OrderingCentrum,
    copies,
    open_in_excel,
    ordering_centrum,
)
from atrapy.intermax import (
    ADDRESS,
    CONTRACT_NUMBER,
    FIRST,
    HEADERS,
    LAST,
    ORDER_SHEET,
    Intermax,
    Order,
)
from atrapy.settlement import write_worker_list
from atrapy.workbooks import rewrite_parts
from tests.fixtures.fakt_domeny import known
from tests.fixtures.intermax_disk import denied, failing_replace

COPY = "INTERMAX przed uporządkowaniem 2026-10-26 14-05-07.xlsx"
SUMMARY: dict[str, Any] = {
    "figures": [
        {"label": "Zlecenia", "value": 6, "unit": "count"},
        {"label": "Wykonawcy", "value": 3, "unit": "count"},
    ],
    "counts": {"title": "Uporządkowany dzień", "counts": [{"label": "pon 26.10.2026", "count": 6}], "zero_warns": True},
    "files": [],
    "worker_settlements": None,
    "intermax_copy": COPY,
}
OPEN = (
    "INTERMAX jest otwarty w Excelu. Zapisz go i zamknij. Jeśli Excel jest zamknięty, usuń z tego samego folderu "
    f"pozostawiony plik ~${REGISTER_NAME}."
)


def _stopped(centrum: OrderingCentrum) -> dict[str, Any]:
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "stop", view["result"]
    return view


def test_bez_wskazanego_rejestru_zlecen_karta_mowi_co_ustawic_a_start_jest_odrzucony(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path, chosen=False)

    setup = centrum.setup()
    started = centrum.start()

    assert setup == {
        "title": "Uporządkowanie INTERMAX",
        "reminder": "Zapisz i zamknij INTERMAX w Excelu",
        "blocker": "Najpierw wskaż INTERMAX.",
        "open_in_excel": [],
        "last": None,
    }
    assert (started.status_code, started.json()) == (409, {"message": "Najpierw wskaż INTERMAX."})
    assert centrum.client.get("/api/runs/current").json()["state"] == "idle"
    assert centrum.client.get("/api/intermax/days").json() == {"days": [], "problem": None}


def test_uporzadkowanie_bez_listy_wykonawcow_nie_ostrzega_o_jej_zlym_ustawieniu(tmp_path: Path) -> None:
    """Ostrzeżenie o ostatniej dobrej Liście Wykonawców ma tylko proces, który jej używa (DESIGN §4.3)."""

    centrum = ordering_centrum(tmp_path)
    write_worker_list(centrum.tool.worker_list)
    centrum.client.get("/api/settings")
    centrum.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")

    view = centrum.run_to_end()

    assert view["result"]["ending"] == "finished"
    assert not [warning for warning in view["result"]["warnings"] if warning.get("setting") == "wykonawcy"]


def test_karta_mowi_ze_intermax_jest_otwarty_w_excelu_az_do_jego_zamkniecia(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)

    lock = open_in_excel(centrum.register)
    while_open = centrum.setup()
    lock.unlink()
    closed = centrum.setup()

    assert (while_open["blocker"], while_open["open_in_excel"]) == (None, [OPEN])
    assert closed["open_in_excel"] == []


def _days(centrum: OrderingCentrum) -> list[tuple[str, bool]]:
    """Dni na karcie jako skrót dnia i to, czy jest uporządkowany; dziś ma gwiazdkę."""

    response = centrum.client.get("/api/intermax/days")
    assert response.status_code == 200, response.json()
    found = response.json()
    assert found["problem"] is None, found["problem"]
    return [(day["label"] + ("*" if day["today"] else ""), day["ordered"]) for day in found["days"]]


def test_karta_pokazuje_siedem_dni_z_dniem_uporzadkowanym_a_po_uporzadkowaniu_takze_dzisiejszy_wklejony_dzien(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)

    before = centrum.client.get("/api/intermax/days").json()
    centrum.run_to_end()
    after = _days(centrum)

    assert before["days"][:2] == [
        {"day": "2026-10-20", "label": "wt 20.10", "today": False, "ordered": True},
        {"day": "2026-10-21", "label": "śr 21.10", "today": False, "ordered": False},
    ]
    assert [(day["label"], day["ordered"]) for day in before["days"][2:]] == [
        ("czw 22.10", False),
        ("pt 23.10", False),
        ("sob 24.10", False),
        ("niedz 25.10", False),
        ("pon 26.10", False),
    ]
    assert before["days"][-1]["today"] is True
    assert after[0] == ("wt 20.10", True)
    assert after[-1] == ("pon 26.10*", True)


def test_karta_pokazuje_dzis_i_szesc_dni_wstecz_oraz_pozniejsze_dni_uporzadkowane_a_nie_pozniejszy_wklejony_dzien(
    tmp_path: Path,
) -> None:
    def at(month: int, day: int, hour: int, number: int) -> Order:
        return Order(datetime(2026, month, day, hour), "anna.kowalska", number)

    # Czwartek 29.10: 22.10 to siódmy dzień wstecz, 02.11 wpisane w środku 23.10 nie jest dniem, 31.10 jest wklejony,
    # a przegląd od dołu dochodzi do 23.10 dopiero po jedenastu zleceniach 26.10.
    ordered = (
        *(at(10, 22, 8, 1), at(10, 22, 9, 2), at(10, 23, 8, 3), at(11, 2, 9, 4), at(10, 23, 10, 5)),
        *(at(10, 26, 8 + index, 10 + index) for index in range(11)),
        *(at(10, 30, 8, 6), at(10, 30, 9, 7)),
    )
    clock = Clock([NOW + timedelta(days=3)])
    centrum = ordering_centrum(tmp_path, Intermax(ordered=ordered, raw=(at(10, 31, 8, 101), at(10, 31, 9, 102))), clock=clock)

    days = _days(centrum)

    assert days == [
        ("pt 23.10", True),
        ("sob 24.10", False),
        ("niedz 25.10", False),
        ("pon 26.10", True),
        ("wt 27.10", False),
        ("śr 28.10", False),
        ("czw 29.10*", False),
        ("pt 30.10", True),
    ]


def test_dni_intermax_otwartego_w_excelu_sa_z_jego_ostatniego_zapisu(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    open_in_excel(centrum.register)

    days = _days(centrum)

    assert (days[0], len(days)) == (("wt 20.10", True), 7)


def test_nastepnego_dnia_karta_pokazuje_siedem_dni_do_nowego_dnia_choc_intermax_sie_nie_zmienil(tmp_path: Path) -> None:
    clock = Clock([NOW, NOW + timedelta(days=1)])
    centrum = ordering_centrum(tmp_path, clock=clock)

    monday, tuesday = _days(centrum), _days(centrum)

    assert (monday[0], monday[-1]) == (("wt 20.10", True), ("pon 26.10*", False))
    assert (tuesday[0], tuesday[-2:]) == (("śr 21.10", False), [("pon 26.10", False), ("wt 27.10*", False)])
    assert len(tuesday) == 7


@pytest.mark.parametrize(
    ("online_only", "what"),
    [
        (False, "Nie można odczytać INTERMAX jako skoroszytu Excela. INTERMAX nie został zmieniony."),
        (True, "Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze."),
    ],
    ids=["uszkodzony", "w-chmurze"],
)
def test_dni_intermax_ktorego_nie_da_sie_odczytac_to_komunikat_a_w_onedrive_tylko_online_komunikat_o_chmurze(
    tmp_path: Path, online_only: bool, what: str
) -> None:
    centrum = ordering_centrum(tmp_path)
    centrum.register.write_bytes(b"to nie jest skoroszyt")
    assert centrum.surroundings.onedrive is not None
    if online_only:
        centrum.surroundings.onedrive.online_only.add(centrum.register)

    found = centrum.client.get("/api/intermax/days").json()

    assert (found["days"], found["problem"]["what"]) == ([], what)
    assert REGISTER_NAME in found["problem"]["where"]


def test_dni_intermax_ze_starszym_arkuszem_zlecen_ktorego_wierszy_nie_da_sie_rozdzielic_to_komunikat_z_tym_arkuszem(
    tmp_path: Path,
) -> None:
    centrum = ordering_centrum(tmp_path, Intermax(older_sheet=True))
    _older_sheet_unsupported(centrum.register)

    found = centrum.client.get("/api/intermax/days").json()

    assert (found["days"], found["problem"]["what"]) == (
        [],
        "Wklejone zlecenia mają układ, którego narzędzie nie porządkuje. INTERMAX nie został zmieniony.",
    )
    assert found["problem"]["where"] == f"plik {REGISTER_NAME}, folder OneDrive, arkusz ZLECENIA OD 08_11_2021"


def test_po_chwilowej_porazce_odczytu_karta_czyta_intermax_od_nowa_choc_jego_znacznik_zapisu_sie_nie_zmienil(
    tmp_path: Path,
) -> None:
    # OneDrive w trakcie pobierania: plik chwilowo nieczytelny, a po pobraniu ten sam czas zmiany i rozmiar.
    centrum = ordering_centrum(tmp_path)
    original, saved = centrum.register.read_bytes(), centrum.register.stat()
    centrum.register.write_bytes(bytes(len(original)))
    os.utime(centrum.register, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    failing = centrum.client.get("/api/intermax/days").json()
    centrum.register.write_bytes(original)
    os.utime(centrum.register, ns=(saved.st_atime_ns, saved.st_mtime_ns))

    days = _days(centrum)

    assert failing["problem"] is not None
    assert (days[0], len(days)) == (("wt 20.10", True), 7)


def _orders(day: int, count: int, first: int) -> tuple[Order, ...]:
    return tuple(Order(datetime(2026, 10, day, 8 + index), "anna.kowalska", first + index) for index in range(count))


@pytest.mark.parametrize(
    ("intermax", "day", "ordered"),
    [
        # Tata we wtorek rano wkleja drugi raz poniedziałek, uporządkowany wczoraj w poprzednim okresie.
        (Intermax(ordered=_orders(26, 2, 1), raw=_orders(26, 2, 1)), "pon 26.10", True),
        # Sobota z poprzedniego okresu nad całą niedzielą: niedziela jest wcześniejsza niż wtorek, ale nie niż sobota.
        (Intermax(ordered=_orders(24, 2, 1) + _orders(25, 10, 3), raw=_orders(24, 2, 1)), "sob 24.10", True),
        # Przypadek taty: środa uporządkowana do przodu, pod nią cały wtorek (10 i więcej wierszy wcześniejszego dnia).
        (Intermax(ordered=_orders(28, 2, 1) + _orders(27, 10, 3), raw=_orders(28, 2, 1)), "śr 28.10", True),
        (Intermax(ordered=_orders(28, 2, 1) + _orders(27, 14, 3), raw=_orders(28, 2, 1)), "śr 28.10", True),
        # Środa uporządkowana w starszym arkuszu, a wklejona w nowym.
        (
            Intermax(ordered=_orders(20, 2, 1), raw=_orders(28, 2, 3), older_sheet=True, older_ordered=_orders(28, 2, 3)),
            "śr 28.10",
            True,
        ),
        # Środa nad dziesięcioma wierszami dnia sprzed siedmiu dni karty: przegląd kończy się przed nią.
        (
            Intermax(
                ordered=_orders(20, 2, 1),
                raw=_orders(28, 2, 3),
                older_sheet=True,
                older_ordered=_orders(28, 2, 3) + _orders(20, 10, 5),
            ),
            "śr 28.10",
            False,
        ),
    ],
    ids=[
        "poprzedni-okres",
        "nad-pozniejszym-dniem",
        "do-przodu-nad-wtorkiem",
        "do-przodu-nad-czternastoma-wierszami",
        "w-starszym-arkuszu",
        "w-starszym-arkuszu-za-granica",
    ],
)
def test_wklejony_dzien_karta_pokazuje_jako_uporzadkowany_wtedy_gdy_uporzadkowanie_odmawia_go_jako_uporzadkowanego(
    tmp_path: Path, intermax: Intermax, day: str, ordered: bool
) -> None:
    clock = Clock([NOW + timedelta(days=1)])
    centrum = ordering_centrum(tmp_path, intermax, clock=clock)

    days = _days(centrum)
    view = centrum.run_to_end()

    # Dzień po dzisiejszym karta pokazuje tylko jako uporządkowany, więc nieuporządkowanej środy na niej nie ma.
    assert ((day, True) in days) == ordered
    result = view["result"]
    refusals = [stop for stop in result["stops"] if stop["what"].startswith(f"Dzień {day[-5:]}.2026 jest już uporządkowany.")]
    assert (result["ending"], len(refusals)) == (("stop", 1) if ordered else ("finished", 0))


def test_uporzadkuj_porzadkuje_intermax_z_ustawien_taty_i_pokazuje_liczby_dzien_i_kopie(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    original = centrum.register.read_bytes()

    started = centrum.start()
    views = views_until(centrum.client, "finished")
    finished = views[-1]

    assert started.status_code == 200
    assert started.json()["state"] == "running"
    run = finished["run"]
    assert (run["process"], run["title"], run["period"], run["mode"], run["confirms_readiness"]) == (
        "intermax",
        "Uporządkowanie INTERMAX",
        PERIOD,
        "RUN",
        False,
    )
    result = finished["result"]
    assert (result["result"], result["ending"], result["headline"], result["next_action"]) == (
        "OK",
        "finished",
        "INTERMAX uporządkowany",
        "open_order_register",
    )
    assert result["summary"] == SUMMARY
    assert (result["stops"], result["warnings"], result["files_unchanged"]) == ([], [], False)
    assert phase_states(finished) == dict.fromkeys(("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"), "completed")
    assert copies(centrum) == [COPY]
    assert (centrum.copies / COPY).read_bytes() == original
    assert centrum.register.read_bytes() != original


def test_centrum_bez_wskazanego_folderu_kopii_kladzie_kopie_intermax_w_folderze_narzedzia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = tmp_path / "narzędzie"
    tool.mkdir()
    monkeypatch.setattr(intermax_copies, "TOOL_ROOT", tool)
    centrum = ordering_centrum(tmp_path, tool_copies=True)
    original = centrum.register.read_bytes()

    view = centrum.run_to_end()

    assert view["result"]["headline"] == "INTERMAX uporządkowany"
    assert (tool / "Kopie INTERMAX" / COPY).read_bytes() == original


def test_po_chwilowej_odmowie_onedrive_uporzadkuj_z_centrum_ponawia_podmiane_na_zegarze_centrum(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    centrum.disk.replace, attempts = failing_replace(denied, times=2)
    started_at = centrum.surroundings.clock.seconds

    view = centrum.run_to_end()

    assert (view["result"]["ending"], view["result"]["headline"]) == ("finished", "INTERMAX uporządkowany")
    assert (len(attempts), centrum.surroundings.clock.seconds - started_at) == (3, 1.0)
    assert copies(centrum) == [COPY]


def test_gdy_onedrive_dalej_trzyma_intermax_centrum_mowi_tacie_o_synchronizacji_po_pieciu_sekundach_zegara(
    tmp_path: Path,
) -> None:
    centrum = ordering_centrum(tmp_path)
    original = centrum.register.read_bytes()
    centrum.disk.replace, attempts = failing_replace(denied)
    started_at = centrum.surroundings.clock.seconds

    view = _stopped(centrum)

    result = view["result"]
    assert (result["stop_kind"], result["stops"][0]["what"]) == (
        "for_tata",
        "OneDrive jeszcze synchronizuje INTERMAX. INTERMAX nie został zmieniony.",
    )
    assert (len(attempts), centrum.surroundings.clock.seconds - started_at) == (11, 5.0)
    assert centrum.register.read_bytes() == original
    assert copies(centrum) == []


def test_okres_uruchomienia_to_okres_dnia_startu_takze_gdy_skonczy_sie_po_polnocy(tmp_path: Path) -> None:
    # Poniedziałek tuż przed północą: następne pytania zegara są już we wtorek, w następnym okresie.
    clock = Clock([datetime(2026, 10, 26, 23, 59, 59), datetime(2026, 10, 27, 0, 0, 3)])
    centrum = ordering_centrum(tmp_path, clock=clock)

    view = centrum.run_to_end()

    assert view["run"]["period"] == PERIOD
    assert [record["period"] for record in centrum.metric_records()] == [PERIOD]
    assert [record["period"] for record in centrum.run_logs()] == [PERIOD]
    assert centrum.last_started()["period"] == PERIOD
    assert copies(centrum) == ["INTERMAX przed uporządkowaniem 2026-10-27 00-00-03.xlsx"]


def test_intermax_otwarty_to_zatrzymanie_dla_taty_przed_odczytem_w_okresie_dzisiejszej_daty(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    original = centrum.register.read_bytes()
    open_in_excel(centrum.register)

    view = _stopped(centrum)

    result = view["result"]
    assert (result["result"], result["stop_kind"], result["headline"], result["next_action"]) == (
        "BLAD_KRYTYCZNY",
        "for_tata",
        "Do poprawy",
        "rerun",
    )
    assert result["stops"][0]["what"] == "INTERMAX jest otwarty w Excelu. INTERMAX nie został zmieniony."
    assert result["stops"][0]["where"] == f"plik {REGISTER_NAME}, folder OneDrive"
    assert (result["opens"], result["diagnosis"], result["files_unchanged"]) == ("order_register", None, True)
    # Karta proponuje otworzyć Rejestr zleceń pod nazwą z Komunikatu: „Otwórz INTERMAX”.
    assert view["run"]["register_name"] == "INTERMAX"
    assert phase_states(view)["Sprawdzanie"] == "failed"
    assert view["run"]["period"] == PERIOD
    assert centrum.last_started()["period"] == PERIOD
    assert [(record["period"], record["stop"]["code"]) for record in centrum.metric_records()] == [
        (PERIOD, "INTERMAX_OTWARTY")
    ]
    assert centrum.register.read_bytes() == original
    assert copies(centrum) == []


def test_logi_zatrzymania_przed_odczytem_ida_do_skrzynki_przy_okresie_dzisiejszej_daty(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path), "github_pat_SYNTETYCZNY123")
    open_in_excel(centrum.register)

    run_id = _stopped(centrum)["run"]["id"]

    [logs] = centrum.run_logs()
    assert (logs["run_id"], logs["process"], logs["mode"], logs["period"]) == (run_id, "intermax", "RUN", PERIOD)
    assert [message["code"] for message in logs["messages"]] == ["INTERMAX_OTWARTY"]
    assert [file["name"] for file in logs["environment"]["files"]] == [REGISTER_NAME]
    box = centrum.surroundings.report_box
    line = f"- Logi Uruchomienia okresu: {PERIOD}"
    assert box.wait_until(lambda box: any(line in issue.body and issue.comments for issue in box.background_issues))
    [issue] = box.background_issues
    assert issue.title == f"Logi Uruchomienia {PERIOD}"
    assert run_id in issue.comments[0]


def test_zatrzymanie_do_maksa_prowadzi_do_diagnozy_intermax_i_zgloszenia(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    workbook = load_workbook(centrum.register)
    workbook[ORDER_SHEET].cell(centrum.layout.first_raw + 1, 4).value = "=1+1"
    workbook.save(centrum.register)

    view = _stopped(centrum)
    diagnosis = centrum.client.post(f"/api/runs/{view['run']['id']}/diagnosis")
    report = centrum.client.post(f"/api/runs/{view['run']['id']}/report")

    result = view["result"]
    assert (result["stop_kind"], result["headline"], result["diagnosis"]) == ("for_maks", "Błąd", "on_request")
    assert result["stops"][0]["where"] == f"plik {REGISTER_NAME}, folder OneDrive, arkusz {ORDER_SHEET}"
    assert diagnosis.status_code == 200
    checks = {check["label"]: (check["state"], check["detail"]) for check in diagnosis.json()["checks"]}
    assert list(checks) == [
        "Ustawienia Centrum",
        "Pliki w OneDrive",
        "INTERMAX",
        "Aktualność narzędzia",
        "Token do Zgłoszeń",
        "Dziennik Centrum rozliczeń",
    ]
    assert checks["Ustawienia Centrum"] == ("passed", "INTERMAX jest na miejscu.")
    assert checks["Pliki w OneDrive"] == ("passed", "Sprawdzone pliki są na tym komputerze: 1.")
    assert checks["INTERMAX"] == ("passed", "Nie jest otwarty w Excelu, otwiera się i ma arkusz zleceń.")
    assert diagnosis.json()["next_action"] == "report"
    assert "- Proces: Uporządkowanie INTERMAX" in diagnosis.json()["report"]["body"]
    assert report.status_code == 200
    assert report.json()["state"] in ("sent", "queued")


def test_powtorzone_zatrzymanie_intermax_wyjasnia_diagnoza_intermax(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    open_in_excel(centrum.register)

    _stopped(centrum)
    repeated = _stopped(centrum)
    diagnosis = centrum.client.post(f"/api/runs/{repeated['run']['id']}/diagnosis").json()

    assert (repeated["result"]["stop_kind"], repeated["result"]["diagnosis"]) == ("repeated", "on_request")
    assert diagnosis["confirms_stop"] is True
    assert diagnosis["explanation"] == repeated["result"]["stops"][0]
    assert diagnosis["next_action"] == "rerun"
    assert {check["label"]: check["state"] for check in diagnosis["checks"]}["INTERMAX"] == "failed"


def test_diagnoza_mowi_ktorego_intermax_z_ustawien_taty_nie_ma(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path, Intermax())
    centrum.engines.fail_summary = True
    view = centrum.run_to_end()
    centrum.register.unlink()

    diagnosis = centrum.client.post(f"/api/runs/{view['run']['id']}/diagnosis").json()

    assert view["result"]["stop_kind"] == "for_maks"
    assert diagnosis["explanation"]["what"] == "Nie znaleziono INTERMAX. INTERMAX nie został zmieniony."
    assert diagnosis["next_action"] == "rerun"
    states = {check["label"]: check["state"] for check in diagnosis["checks"]}
    assert (states["Ustawienia Centrum"], states["INTERMAX"]) == ("failed", "not_checked")


@pytest.mark.parametrize(
    ("broken", "what"),
    [
        (lambda register: register.write_bytes(b"to nie jest skoroszyt"), "Nie można odczytać INTERMAX jako skoroszytu Excela. INTERMAX nie został zmieniony."),
        (
            lambda register: Workbook().save(register),
            "W INTERMAX nie ma arkusza zleceń z nagłówkami od AKCJE do UWAGI w wierszu 1. INTERMAX nie został zmieniony.",
        ),
    ],
    ids=["uszkodzony", "bez-arkusza-zlecen"],
)
def test_diagnoza_odczytuje_intermax_i_wskazuje_ten_ktorego_nie_da_sie_uporzadkowac(
    tmp_path: Path, broken: Callable[[Path], None], what: str
) -> None:
    centrum = ordering_centrum(tmp_path)
    centrum.engines.fail_summary = True
    view = centrum.run_to_end()
    broken(centrum.register)

    diagnosis = centrum.client.post(f"/api/runs/{view['run']['id']}/diagnosis").json()

    [intermax] = [check for check in diagnosis["checks"] if check["label"] == "INTERMAX"]
    assert (intermax["state"], intermax["detail"]) == ("failed", what)
    assert diagnosis["explanation"]["what"] == what


def test_diagnoza_intermax_sprawdza_w_onedrive_tylko_intermax_a_nie_pliki_okresu(tmp_path: Path) -> None:
    periods = tmp_path / "INEA"
    collective = PeriodFolder(periods, parse_period_token(PERIOD)).collective_file
    collective.parent.mkdir(parents=True)
    collective.write_bytes(b"tylko w chmurze")
    centrum = ordering_centrum(tmp_path, periods_directory=periods)
    assert centrum.surroundings.onedrive is not None
    centrum.surroundings.onedrive.online_only.add(collective)
    centrum.engines.fail_summary = True
    view = centrum.run_to_end()

    diagnosis = centrum.client.post(f"/api/runs/{view['run']['id']}/diagnosis").json()

    checks = {check["label"]: (check["state"], check["detail"]) for check in diagnosis["checks"]}
    assert checks["Pliki w OneDrive"] == ("passed", "Sprawdzone pliki są na tym komputerze: 1.")


def test_historia_metryki_i_karta_maja_uporzadkowanie_intermax(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    run_id = centrum.run_to_end()["run"]["id"]

    metrics = centrum.client.get("/api/metrics").json()
    card = centrum.client.get(f"/api/runs/{run_id}/card").json()

    [run] = metrics["runs"]
    assert (run["process"], run["process_label"], run["period"], run["mode"]) == (
        "intermax",
        "Uporządkowanie INTERMAX",
        PERIOD,
        "RUN",
    )
    assert (run["result"], run["origin"], run["run_id"]) == ("OK", "centrum", run_id)
    # Uporządkowanie INTERMAX nie ma Podglądu bez zapisu, więc Metryki nie mają jego trybu DRY-RUN.
    assert [(entry["process"], entry["mode"]) for entry in metrics["statistics"]] == [
        ("preparation", "RUN"),
        ("preparation", "DRY-RUN"),
        ("settlement", "RUN"),
        ("settlement", "DRY-RUN"),
        ("efenix", "RUN"),
        ("intermax", "RUN"),
        ("report_entering", "RUN"),
    ]
    assert card["state"] == "restored"
    assert (card["run"]["title"], card["result"]["headline"]) == ("Uporządkowanie INTERMAX", "INTERMAX uporządkowany")
    assert card["result"]["summary"] == SUMMARY
    pinnable = centrum.client.get("/api/dad-notes/runs").json()
    assert [(entry["run_id"], entry["process_label"]) for entry in pinnable] == [(run_id, "Uporządkowanie INTERMAX")]


def test_karta_pokazuje_ostatnie_uporzadkowanie_z_logow_takze_po_ponownym_starcie_centrum(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    after_ordering = centrum.setup()["last"]
    open_in_excel(centrum.register)
    stopped = _stopped(centrum)["run"]["id"]

    centrum.restart()
    last = centrum.setup()["last"]
    previous = centrum.client.get("/api/runs/current").json()["previous"]

    assert (after_ordering["run"]["id"], after_ordering["result"]["summary"]) == (ordered, SUMMARY)
    assert (last["run"]["id"], last["result"]["headline"], last["result"]["stops"][0]["what"]) == (
        stopped,
        "Do poprawy",
        "INTERMAX jest otwarty w Excelu. INTERMAX nie został zmieniony.",
    )
    assert previous == last
    assert last["run"]["register_name"] == "INTERMAX"


def _logs_like(centrum: OrderingCentrum, like: str, later: timedelta, **changes: Any) -> Path:
    """Logi drugiego Uruchomienia jak ``like``, rozpoczętego ``later`` po pełnej sekundzie jego startu.

    Start trafia do nazwy pliku i do Logów; ``changes`` zmienia inne pola Logów.
    """

    [path] = centrum.tool.run_logs.glob(f"*-{like}.json")
    record = RunLog.model_validate_json(path.read_text(encoding="utf-8"))
    started_at = record.started_at.replace(microsecond=0) + later
    times = {"started_at": started_at, "ended_at": started_at + (record.ended_at - record.started_at)}
    other = record.model_copy(update={"run_id": uuid4().hex, **times, **changes})
    other_path = path.with_name(name_of(other.start))
    other_path.write_text(other.model_dump_json(indent=2), encoding="utf-8")
    return other_path


def test_karta_pokazuje_najnowsze_uporzadkowanie_a_nie_starsze_z_logow(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    _logs_like(centrum, ordered, -timedelta(days=7))

    assert centrum.setup()["last"]["run"]["id"] == ordered


def test_karta_bierze_ostatnie_uporzadkowanie_a_nie_pozniejsze_uruchomienie_innego_procesu(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    _logs_like(centrum, ordered, timedelta(hours=1), process="preparation")

    assert centrum.setup()["last"]["run"]["id"] == ordered


def test_bez_logow_uporzadkowania_karta_nie_ma_ostatniego_choc_sa_logi_innego_procesu(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    _logs_like(centrum, ordered, timedelta(hours=1), process="preparation")
    [intermax_logs] = centrum.tool.run_logs.glob(f"*-{ordered}.json")
    intermax_logs.unlink()
    centrum.restart()

    setup = centrum.client.get("/api/intermax")

    assert (setup.status_code, setup.json()["last"]) == (200, None)


@pytest.mark.parametrize(
    ("earlier", "later"), [("0" * 32, "f" * 32), ("f" * 32, "0" * 32)], ids=["pozniejszy-dalej", "pozniejszy-blizej"]
)
def test_z_uporzadkowan_w_tej_samej_sekundzie_karta_pokazuje_pozniejsze(tmp_path: Path, earlier: str, later: str) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    _logs_like(centrum, ordered, timedelta(hours=1, milliseconds=100), run_id=earlier)
    _logs_like(centrum, ordered, timedelta(hours=1, milliseconds=200), run_id=later)

    assert centrum.setup()["last"]["run"]["id"] == later


def test_karta_pomija_nieczytelne_logi_uporzadkowania_z_tej_samej_sekundy(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    _logs_like(centrum, ordered, timedelta(0)).write_text("{", encoding="utf-8")

    assert centrum.setup()["last"]["run"]["id"] == ordered


def test_nieczytelne_najnowsze_logi_uporzadkowania_to_karta_bez_ostatniego_a_nie_starsze(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    _logs_like(centrum, ordered, timedelta(hours=1)).write_text("{", encoding="utf-8")

    assert centrum.setup()["last"] is None


def test_nieczytelne_najnowsze_logi_to_karta_bez_ostatniego_takze_gdy_starsze_sa_z_tej_samej_minuty(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    [path] = centrum.tool.run_logs.glob(f"*-{ordered}.json")
    second = RunLog.model_validate_json(path.read_text(encoding="utf-8")).started_at.second
    # Godzinę później: czytelne Logi w pełnej minucie, a nieczytelne najnowsze pół minuty po nich.
    _logs_like(centrum, ordered, timedelta(hours=1, seconds=-second))
    _logs_like(centrum, ordered, timedelta(hours=1, seconds=30 - second)).write_text("{", encoding="utf-8")

    assert centrum.setup()["last"] is None


def test_logi_uporzadkowania_maja_wiersze_wpisow_na_operatora_i_instalacje_hurt_bez_wpisu_a_karta_sie_nie_zmienia(
    tmp_path: Path,
) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 201, "P4", "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 9), "jan.nowak", 202, "T-Mobile", "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 10), "jan.nowak", 203, "P4", "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 11), "jan.nowak", 204, "INEA S.A.", "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 12), "jan.nowak", 205, None, "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 13), "jan.nowak", 206, "P4", "Usterka"),
    )
    centrum = ordering_centrum(tmp_path, Intermax(raw=raw))
    day = centrum.layout.yellow
    assert day is not None

    view = centrum.run_to_end()

    result = view["result"]
    assert (result["headline"], result["stops"], result["warnings"]) == ("INTERMAX uporządkowany", [], [])
    assert result["summary"] == SUMMARY | {
        "figures": [
            {"label": "Zlecenia", "value": 6, "unit": "count"},
            {"label": "Wykonawcy", "value": 1, "unit": "count"},
        ],
    }
    [logs] = centrum.run_logs()
    assert logs["intermax_entries"] == {
        "rows": {"P4": [day + 2, day + 4], "TMOBILE": [day + 3]},
        "without_entry": [{"row": day + 5, "operator": "INEA S.A."}, {"row": day + 6, "operator": None}],
    }
    [path] = ToolDirectory(tmp_path).run_logs.glob("*.json")
    text = path.read_text(encoding="utf-8")
    for order in raw:
        for column, value in order.values().items():
            if column in (ADDRESS, CONTRACT_NUMBER) or column > LAST:
                assert str(value) not in text, value
    assert "akt pętli" not in text and "nokia" not in text, "bez wartości Wpisu"


def test_karta_wraca_z_logow_uporzadkowania_sprzed_wpisow_intermax(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    [path] = ToolDirectory(tmp_path).run_logs.glob(f"*-{ordered}.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["intermax_entries"]
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    centrum.restart()

    last = centrum.setup()["last"]
    assert (last["run"]["id"], last["result"]["summary"]) == (ordered, SUMMARY)


def test_start_z_okresem_nie_przyjmuje_uporzadkowania_intermax(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)

    refused = centrum.client.post("/api/runs", json={"process": "intermax", "period": PERIOD, "mode": "RUN"})

    assert refused.status_code == 422
    assert copies(centrum) == []


# --- Kopia wejścia (#842) ------------------------------------------------------------------------------------------------
# Logi Uporządkowania INTERMAX niosą wklejone wiersze, które Uporządkowanie przetwarzało, bez kolumn ``ADRES`` i
# ``NUMER UMOWY``, z odciskiem przeczytanych bajtów INTERMAX (reguła danych, ADR 0025).

OLDER_SHEET = "ZLECENIA OD 08_11_2021"
COPY_COLUMNS = {
    get_column_letter(column): header
    for column, header in enumerate(HEADERS, start=FIRST)
    if column not in (ADDRESS, CONTRACT_NUMBER)
}
"""Nagłówki od A do ``UWAGI`` w Kopii wejścia (A go nie ma): bez ``ADRES`` (E) i ``NUMER UMOWY`` (K) i bez kolumn z
aplikacji za ``UWAGI``."""
READ_AT = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
"""Chwila zmiany INTERMAX przed Uruchomieniem, a ``SAVED_AGAIN_AT`` po zapisie zaraz po odczycie."""
SAVED_AGAIN_AT = datetime(2027, 1, 15, 8, 0, tzinfo=timezone.utc)
ADDRESS_VALUE = "Syntetyczna Bursztynowa 14/2 Poznań"
OTHER_ADDRESS = "Syntetyczna Malinowa 7 Swarzędz"
ORANGE_VALUE = "4801234567"
PHONE = "600 123 456"
STREET = "ul. Kwiatowa 5"
PHONE_WITH_PREFIX = 48600123456
"""Telefon wpisany z ``+48``, który format General trzyma jako liczbę bez ``+``."""
FREE_TEXT = f"montaż {ADDRESS_VALUE} umowa {ORANGE_VALUE} tel. {PHONE}, {STREET}"
MASKED = "montaż [adres] umowa [numer Orange] tel. [telefon], [ulica]"


def _copied_cells(order: Order) -> dict[str, object]:
    """Komórki zlecenia w Kopii wejścia: od A do ``UWAGI`` pod nagłówkiem, bez ``ADRES`` i ``NUMER UMOWY``, data z
    godziną z rodzajem."""

    return {
        get_column_letter(column): {"type": "datetime", "text": value.isoformat()} if isinstance(value, datetime) else value
        for column, value in order.values().items()
        if column <= LAST and column not in (ADDRESS, CONTRACT_NUMBER)
    }


def _sent(centrum: OrderingCentrum) -> list[str]:
    """Wszystko, co Maks dostaje w Skrzynce, gdy wyjdą Logi: issue z komentarzami i rozpakowane pliki w Archiwach."""

    box = centrum.surroundings.report_box
    assert box.wait_until(
        lambda fake: any(issue.label == "logi-uruchomienia" and issue.comments for issue in fake.background_issues)
        and any(archive.assets for archive in fake.archives)
    )
    issues = [part for issue in [*box.background_issues, *box.issues] for part in (issue.title, issue.body, *issue.comments)]
    return issues + [asset.text for archive in box.archives for asset in archive.assets]


def test_logi_uporzadkowania_maja_wklejone_wiersze_bez_adresu_i_numeru_umowy_oraz_odcisk_przeczytanego_intermax(
    tmp_path: Path,
) -> None:
    """Kopia wejścia Uporządkowania to każdy arkusz zleceń INTERMAX z nagłówkami bez ``ADRES`` i ``NUMER UMOWY`` i z
    wklejonymi wierszami, które Planowanie rozpoznaje, a nie z uporządkowanymi dniami nad nimi ani starszym arkuszem bez
    wklejenia, z komórkami od A do ``UWAGI``, które Uporządkowanie przenosi do dnia. Przesunięty pierwszy wiersz ma
    komórki pod ich nagłówkiem, bez kolumn z aplikacji, które w pliku wpadły pod ``ZWROT`` i ``UWAGI``. Z dołu arkusza
    nad wklejeniem Kopia ma tylko numery ostatniego uporządkowanego i żółtego wiersza, od których Planowanie liczy
    wiersz dnia (#847). Odcisk to rozmiar i skrót bajtów, które
    Uporządkowanie przeczytało, choć zaraz po odczycie OneDrive albo Autozapis Excela zapisał INTERMAX z innymi
    bajtami, i chwila zmiany sprzed odczytu."""

    pasted = list(Intermax().raw)
    pasted[2] = replace(pasted[2], cells=((1, "A-SYN"),))
    watched: dict[Path, bytes] = {}
    saved_again: list[bytes] = []

    def read_then_saved(path: Path) -> bytes:
        read = workbook_files.file_bytes(path)
        if watched.get(path) == read:
            rewrite_parts(path, lambda name, data: data.replace(b">komentarz<", b">komentarz zapisany znowu<"))
            os.utime(path, (SAVED_AGAIN_AT.timestamp(), SAVED_AGAIN_AT.timestamp()))
            saved_again.append(path.read_bytes())
        return read

    centrum = ordering_centrum(
        tmp_path,
        Intermax(older_sheet=True, raw=pasted),
        surroundings=Surroundings(source=read_then_saved),
    )
    os.utime(centrum.register, (READ_AT.timestamp(), READ_AT.timestamp()))
    content = centrum.register.read_bytes()
    watched[centrum.register] = content

    view = centrum.run_to_end()

    assert view["result"]["result"] == "OK", view["result"]["stops"]
    assert [saved != content for saved in saved_again] == [True], "INTERMAX zapisany znowu raz, z innymi bajtami"
    assert centrum.register.read_bytes() != content, "Uporządkowanie zapisało INTERMAX"
    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    fingerprint = {"size": len(content), "modified_at": READ_AT.isoformat().replace("+00:00", "Z"), "sha256": hashlib.sha256(content).hexdigest()}
    assert (copied["name"], copied["fingerprint"]) == (REGISTER_NAME, fingerprint)
    assert copied["folders"] == [tmp_path.name, "OneDrive"], "folder INTERMAX i folder nad nim; Komunikaty pokazują tylko folder INTERMAX"
    older, sheet = copied["sheets"]
    assert older == {
        "sheet": OLDER_SHEET,
        "header_row": 1,
        "columns": COPY_COLUMNS,
        "rows": [],
        "empty_rows": [],
        "shifted_row": None,
        "uncertain_rows": [],
        "last_ordered_row": centrum.layout.last_ordered,
        "yellow_row": None,
    }
    first = centrum.layout.first_raw
    assert (sheet["sheet"], sheet["header_row"], sheet["columns"], sheet["empty_rows"]) == (ORDER_SHEET, 1, COPY_COLUMNS, [])
    assert sheet["shifted_row"] == first
    assert centrum.layout.yellow is not None
    assert (sheet["last_ordered_row"], sheet["yellow_row"]) == (centrum.layout.last_ordered, centrum.layout.yellow)
    assert sheet["rows"][2]["cells"]["A"] == "A-SYN"
    assert sheet["rows"] == [
        {"row": first + index, "cells": _copied_cells(order)} for index, order in enumerate(centrum.layout.raw)
    ]
    assert logs["input_copy_notes"] == []


def test_adres_i_numer_umowy_z_wklejenia_intermax_nie_wychodza_do_logow_ani_skrzynki_takze_jako_liczba_i_w_przesunietym_wierszu(
    tmp_path: Path,
) -> None:
    """Komórek ``ADRES`` i ``NUMER UMOWY`` nie ma w Kopii wejścia, także w przesuniętym pierwszym wierszu wklejenia,
    gdzie stoją dwie kolumny na lewo od nagłówka. Ich wartości w innej komórce (numer Orange, który Excel trzyma jako
    liczbę, w ``UWAGI``, adres i numer w wolnym tekście ``CZYNNOŚCI ZREALIZOWANE``) strażnik maskuje z uwagą techniczną
    o miejscu w Kopii, a telefon i ulicę bez uwagi; nic z tego nie wychodzi do pliku Logów ani do Skrzynki Zgłoszeń."""

    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, cells=((ADDRESS, ADDRESS_VALUE), (CONTRACT_NUMBER, int(ORANGE_VALUE)), (LAST, int(ORANGE_VALUE)))),
        Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102, cells=((ADDRESS, OTHER_ADDRESS), (13, FREE_TEXT))),
        Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 103, cells=((14, PHONE_WITH_PREFIX),)),
    )
    centrum = ordering_centrum(tmp_path, Intermax(raw=raw))
    write_report_key(ToolDirectory(tmp_path))

    view = centrum.run_to_end()

    assert view["result"]["result"] == "OK", view["result"]["stops"]
    sent = _sent(centrum)
    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    [sheet] = copied["sheets"]
    cells = [row["cells"] for row in sheet["rows"]]
    assert [letter for row in cells for letter in ("E", "K") if letter in row] == []
    assert (cells[0]["O"], cells[1]["M"], cells[2]["N"]) == ("[numer Orange]", MASKED, "[telefon]")
    note = "Reguła danych: zamaskowano wartość kolumny {} w: input_copy[0].sheets[0].rows[{}].cells.[…]."
    assert logs["input_copy_notes"] == [
        note.format("NUMER UMOWY/ZLECENIA ORANGE", 0),
        note.format("ADRES", 1),
        note.format("NUMER UMOWY/ZLECENIA ORANGE", 1),
    ]
    assert any(MASKED in part for part in sent), "Kopia wejścia w pliku Logów w Archiwum"
    texts = [path.read_text(encoding="utf-8") for path in sorted(ToolDirectory(tmp_path).run_logs.glob("*"))] + sent
    leaked = (ADDRESS_VALUE, OTHER_ADDRESS, ORANGE_VALUE, PHONE, STREET, str(PHONE_WITH_PREFIX))
    assert [value for value in leaked if any(value in text for text in texts)] == []


def test_arkusz_zlecen_ktorego_wierszy_nie_da_sie_rozdzielic_zatrzymuje_uporzadkowanie_tym_samym_komunikatem_a_kopia_go_nie_ma(
    tmp_path: Path,
) -> None:
    """Starszy arkusz zleceń, którego wierszy nie da się rozdzielić: Uporządkowanie zatrzymuje się Komunikatem
    Planowania o tym arkuszu, jak bez Kopii wejścia, a Kopia ma odcisk INTERMAX i arkusz z wklejeniem bez tamtego.
    Planowanie nie doszło do wklejenia, a adres z jego wolnego tekstu i tak jest zamaskowany, bo Kopia poznaje
    zakazane komórki wierszy, które niesie."""

    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, cells=((ADDRESS, ADDRESS_VALUE),)),
        Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102, cells=((13, f"montaż {ADDRESS_VALUE}"),)),
    )
    centrum = ordering_centrum(tmp_path, Intermax(older_sheet=True, raw=raw))
    _older_sheet_unsupported(centrum.register)
    content = centrum.register.read_bytes()

    result = _stopped(centrum)["result"]

    assert (result["stop_kind"], result["stops"][0]["where"]) == ("for_maks", f"plik {REGISTER_NAME}, folder OneDrive, arkusz {OLDER_SHEET}")
    assert result["stops"][0]["what"] == "Wklejone zlecenia mają układ, którego narzędzie nie porządkuje. INTERMAX nie został zmieniony."
    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    assert copied["fingerprint"]["sha256"] == hashlib.sha256(content).hexdigest()
    [sheet] = copied["sheets"]
    assert (sheet["sheet"], [row["cells"]["M"] for row in sheet["rows"] if "M" in row["cells"]]) == (ORDER_SHEET, ["montaż [adres]"])
    [path] = ToolDirectory(tmp_path).run_logs.glob("*.json")
    assert ADDRESS_VALUE not in path.read_text(encoding="utf-8")


def test_intermax_bez_arkusza_zlecen_zatrzymuje_uporzadkowanie_dla_taty_a_kopia_ma_odcisk_pliku_bez_arkuszy(
    tmp_path: Path,
) -> None:
    """INTERMAX, którego żaden arkusz nie ma w wierszu 1 nagłówków zleceń: Uporządkowanie zatrzymuje się dla taty, a Kopia
    wejścia ma odcisk pliku, na którym proces się zatrzymał, choć nie ma w niej żadnego arkusza."""

    centrum = ordering_centrum(tmp_path)
    rewrite_parts(centrum.register, lambda name, data: data.replace(b">AKCJE<", b">AKCJE X<"))
    content = centrum.register.read_bytes()

    result = _stopped(centrum)["result"]

    assert (result["stop_kind"], result["stops"][0]["what"]) == (
        "for_tata",
        "W INTERMAX nie ma arkusza zleceń z nagłówkami od AKCJE do UWAGI w wierszu 1. INTERMAX nie został zmieniony.",
    )
    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    assert (copied["name"], copied["fingerprint"]["sha256"], copied["sheets"]) == (
        REGISTER_NAME,
        hashlib.sha256(content).hexdigest(),
        [],
    )


# --- Położenia wklejonego wiersza (#842, #913) ---------------------------------------------------------------------------
# Tabela położeń z opisu PR #905: wiersz próbny niesie syntetyczny adres i numer Orange tam, gdzie w pliku stoją jego
# kolumny ``ADRES`` i ``NUMER UMOWY``, a ostatnie zlecenie wklejenia cytuje je w ``CZYNNOŚCI ZREALIZOWANE``, więc
# strażnik musi je znać tam, gdzie stoją. Każdy wiersz ma jedno położenie (decyzja Maksa z 5.11.2026, ADR 0025):
# pierwszy wiersz bloku wklejenia przesunięty o dwie kolumny w lewo, każdy inny pod nagłówkiem. W obu jest pierwszy
# wiersz bloku, którego przesunięcia nie widać (bez daty z godziną dwie kolumny przed DATA albo z nią także pod DATA),
# bez uwagi, i inny wiersz z datą z godziną dwie kolumny przed DATA (ślad przesunięcia), z uwagą w Logach, że fakt
# domeny jest złamany. ``NUMER ZL.`` uporządkowanego wiersza, który stoi tam, gdzie numer Orange przesuniętego, cytowany w tym samym tekście
# zostaje: może wyjść (ADR 0025). Przypadki, w których fakt domeny nie zachodzi, a ślad go nie zdradza, to ryzyko
# przyjęte przez Maksa (``KNOWN``).

PROBE_ADDRESS = "Przemiatana Wrzosowa 12 Kórnik"
PROBE_ORANGE = "4809876543"
ORDERED = (
    Order(datetime(2026, 10, 19, 9), "anna.kowalska", 1001),
    Order(datetime(2026, 10, 19, 12), "anna.kowalska", 1002),
    Order(datetime(2026, 10, 20, 8), "jan.nowak", 1003),
)
ECHO = f"montaż {PROBE_ADDRESS} umowa {PROBE_ORANGE} po ZL-1003"
ECHO_MASKED = "montaż [adres] umowa [numer Orange] po ZL-1003"
DONE = 13
"""``CZYNNOŚCI ZREALIZOWANE`` (M), wolny tekst technika."""
PASTED = (
    Order(datetime(2026, 10, 26, 14), "jan.nowak", 101),
    Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102),
    Order(datetime(2026, 10, 26, 16), "anna.kowalska", 103),
    Order(datetime(2026, 10, 26, 8), "jan.nowak", 104),
    Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 105, cells=((DONE, ECHO),)),
)


def _probe(
    order: Order, *cells: tuple[int, datetime | str | int], shifted: bool = False, app_look: bool = False
) -> Order:
    """Zlecenie ``order`` jako wiersz próbny: adres i numer Orange w kolumnach ``ADRES`` i ``NUMER UMOWY``."""

    return replace(
        order,
        cells=((ADDRESS, PROBE_ADDRESS), (CONTRACT_NUMBER, PROBE_ORANGE), *cells),
        shifted=shifted,
        app_look=app_look,
    )


def _pasted(index: int, probe: Order) -> tuple[Order, ...]:
    return (*PASTED[:index], probe, *PASTED[index + 1 :])


def _older_sheet_unsupported(register: Path) -> None:
    """Starszy arkusz zleceń, którego wierszy nie da się rozdzielić: Planowanie staje na nim, zanim dojdzie do wklejenia.

    Komentarz stoi pod ostatnim wierszem, bo Uporządkowanie czyta arkusz od dołu i tylko te wiersze, których potrzebuje.
    """

    older = "xl/worksheets/sheet2.xml"
    rewrite_parts(
        register, lambda name, data: data.replace(b"</sheetData>", b"<!-- x --></sheetData>") if name == older else data
    )


@dataclass(frozen=True)
class Position:
    """Wiersz tabeli położeń: INTERMAX z wierszem próbnym i to, co tabela mówi o nim w Kopii wejścia.

    ``probe``: arkusz i indeks wiersza próbnego w ``raw`` albo ``older_raw``; ``None``: wiersza nie ma w Kopii.
    ``letters``: kolumny wiersza próbnego w Kopii, ``uncertain``: wiersz w obu położeniach, ``stop``: kod Zatrzymania
    (``None``: Uporządkowanie kończy się wynikiem OK), ``sheets``: arkusze w Kopii, ``traced``: wiersz w obu położeniach
    ma ślad przesunięcia, więc Logi mają uwagę, że fakt domeny jest złamany (``False``: pierwszy wiersz bloku, którego
    przesunięcia nie widać, bez uwagi), ``known``: klasa ryzyka przyjętego przez Maksa (``KNOWN``).
    """

    intermax: Intermax
    probe: tuple[str, int] | None
    letters: str
    uncertain: bool
    stop: str | None
    sheets: tuple[str, ...] = (ORDER_SHEET,)
    edit: Callable[[Path], None] | None = None
    traced: bool = True
    known: str | None = None


TEXT_DATE = (3, "26.10.2026 11:00")
"""``DATA GODZ. POCZ.`` jako tekst, nie data z godziną."""
A_DATE = (1, datetime(2026, 10, 26, 10))
"""Data z godziną w kolumnie A (dwie kolumny przed ``DATA GODZ. POCZ.``, bez nagłówka) wiersza na miejscu."""
POSITIONS = {
    "zwykly_wiersz": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1]))), (ORDER_SHEET, 1), "CDFGHIJ", False, None
    ),
    "przesuniety_pierwszy_wiersz_wklejenia": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0]))), (ORDER_SHEET, 0), "CDFGHIJ", False, None
    ),
    "przesuniety_pierwszy_wiersz_kolejnego_wklejenia": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True))),
        (ORDER_SHEET, 2),
        "ABDFGH",
        True,
        "SUROWE_ZLECENIE_BEZ_DATY",
    ),
    # pierwszy wiersz bloku na miejscu z datą jako tekstem: przesunięcia nie widać, więc oba położenia bez uwagi, a Kopia
    # ma tylko komórki dozwolone w obu, tam, gdzie czyta je Planowanie (przesunięte, bo pod DATA nie ma daty z godziną)
    "pierwszy_wiersz_z_data_jako_tekst_na_miejscu": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], TEXT_DATE)), shifted=False),
        (ORDER_SHEET, 0),
        "FHIJL",
        True,
        "SUROWE_ZLECENIE_BEZ_DATY",
        traced=False,
    ),
    "wiersz_z_data_jako_tekst": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], TEXT_DATE))),
        (ORDER_SHEET, 1),
        "CDFGHIJ",
        False,
        "SUROWE_ZLECENIE_BEZ_DATY",
    ),
    "przesuniety_wiersz_w_srodku_z_data_jako_tekst": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], TEXT_DATE, shifted=True))),
        (ORDER_SHEET, 2),
        "ABCDFGHINO",
        False,
        "SUROWE_ZLECENIE_BEZ_DATY",
        known="przesuniety_inny_bez_sladu",
    ),
    "pusty_wiersz_nad_kolejnym_wklejeniem": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True)), blank_in_paste=frozenset({2})),
        (ORDER_SHEET, 2),
        "ABDFGH",
        True,
        "SUROWE_ZLECENIE_BEZ_DATY",
    ),
    "wiersz_bez_wykonawcy": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(replace(PASTED[1], worker="")))),
        (ORDER_SHEET, 1),
        "CDFGHI",
        False,
        "SUROWE_ZLECENIE_BEZ_WYKONAWCY",
    ),
    "przesuniety_wiersz_z_aplikacji_nad_uporzadkowanymi": Position(
        Intermax(
            ordered=(
                *ORDERED,
                _probe(Order(datetime(2026, 10, 20, 12), "jan.nowak", 201), shifted=True, app_look=True),
                Order(datetime(2026, 10, 20, 14), "jan.nowak", 1004),
            ),
            raw=PASTED,
        ),
        None,
        "",
        False,
        "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
    ),
    # ten sam z datą jako tekstem, więc bez śladu przesunięcia: pierwszy wiersz bloku, którego przesunięcia nie widać, więc
    # oba położenia
    "przesuniety_wiersz_z_aplikacji_nad_uporzadkowanymi_z_data_jako_tekst": Position(
        Intermax(
            ordered=(
                *ORDERED,
                _probe(Order(datetime(2026, 10, 20, 12), "jan.nowak", 201), TEXT_DATE, shifted=True, app_look=True),
                Order(datetime(2026, 10, 20, 14), "jan.nowak", 1004),
            ),
            raw=PASTED,
        ),
        None,
        "",
        False,
        "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
    ),
    # wiersz z wyglądem z aplikacji w wierszu 2, nad wszystkimi uporządkowanymi, z datą jako tekstem: nic go nie
    # poprzedza, więc jest pierwszym wierszem bloku, a jego przesunięcia nie widać
    "przesuniety_wiersz_z_aplikacji_nad_wszystkimi_uporzadkowanymi": Position(
        Intermax(
            ordered=(
                _probe(Order(datetime(2026, 10, 19, 7), "jan.nowak", 202), TEXT_DATE, shifted=True, app_look=True),
                *ORDERED,
            ),
            raw=PASTED,
        ),
        None,
        "",
        False,
        "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
    ),
    # wiersz na miejscu z datą z godziną także dwie kolumny przed DATA: ślad przesunięcia, więc oba położenia, a Kopia ma
    # jego datę spod DATA
    "wiersz_z_data_z_godzina_takze_dwie_kolumny_przed_data": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], (1, datetime(2026, 10, 26, 11))))),
        (ORDER_SHEET, 1),
        "ACDFGHJ",
        True,
        None,
    ),
    # pierwszy wiersz bloku na miejscu z datą z godziną pod DATA i dwie kolumny przed nią: przesunięcia nie widać, więc
    # oba położenia bez uwagi, choć ma ślad przesunięcia
    "pierwszy_wiersz_z_data_z_godzina_takze_dwie_kolumny_przed_data": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], (1, datetime(2026, 10, 26, 13)))), shifted=False),
        (ORDER_SHEET, 0),
        "ACDFGHJ",
        True,
        None,
        traced=False,
    ),
    # pierwszy wiersz bloku na miejscu z datą z godziną w A, a pod DATA z datą tekstem: przesunięcie widać, więc pamięć
    # zna go tylko przesuniętego (klasa B)
    "pierwszy_wiersz_na_miejscu_z_data_w_kolumnie_a": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], A_DATE, TEXT_DATE)), shifted=False),
        (ORDER_SHEET, 0),
        "CFGHIJLM",
        False,
        None,
        known="pierwszy_na_miejscu",
    ),
    # pierwszy wiersz bloku na miejscu z tekstem w A i datą tekstem pod DATA: przesunięcie widać tylko z daty z godziną,
    # więc oba położenia bez uwagi
    "pierwszy_wiersz_na_miejscu_z_tekstem_w_kolumnie_a": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], (1, "pilne"), TEXT_DATE)), shifted=False),
        (ORDER_SHEET, 0),
        "CFHIJL",
        True,
        "SUROWE_ZLECENIE_BEZ_DATY",
        traced=False,
    ),
    "zatrzymanie_zanim_planowanie_doszlo_do_wklejenia": Position(
        Intermax(ordered=ORDERED, older_sheet=True, raw=_pasted(2, _probe(PASTED[2], shifted=True))),
        (ORDER_SHEET, 2),
        "ABDFGH",
        True,
        "NIEOBSLUGIWANY_UKLAD_INTERMAX",
        edit=_older_sheet_unsupported,
    ),
    "wklejenie_z_kilku_dni": Position(
        Intermax(
            ordered=ORDERED,
            raw=(replace(PASTED[0], when=datetime(2026, 10, 27, 14)), *_pasted(1, _probe(PASTED[1]))[1:]),
        ),
        (ORDER_SHEET, 1),
        "CDFGHIJ",
        False,
        "WKLEJENIE_Z_KILKU_DNI",
    ),
    "przesuniety_pierwszy_wiersz_wklejenia_w_starszym_arkuszu": Position(
        Intermax(
            ordered=ORDERED,
            older_sheet=True,
            older_raw=(
                _probe(Order(datetime(2026, 10, 26, 7), "anna.kowalska", 301)),
                Order(datetime(2026, 10, 26, 8), "jan.nowak", 302),
            ),
            raw=PASTED,
        ),
        (OLDER_SHEET, 0),
        "CDFGHIJ",
        False,
        "SUROWE_ZLECENIA_W_KILKU_ARKUSZACH",
        sheets=(OLDER_SHEET, ORDER_SHEET),
    ),
}


@pytest.mark.parametrize(
    "position", [pytest.param(position, id=name, marks=known(position.known)) for name, position in POSITIONS.items()]
)
def test_adres_i_numer_orange_wklejonego_wiersza_nie_wychodza_w_zadnym_polozeniu_wiersza(
    tmp_path: Path, position: Position
) -> None:
    """Każde położenie wklejonego wiersza z tabeli położeń (opis PR #905): adres i numer Orange wiersza próbnego nie
    wychodzą do pliku Logów ani do Skrzynki Zgłoszeń, także zacytowane w ``CZYNNOŚCI ZREALIZOWANE`` innego zlecenia,
    które strażnik maskuje, ani w Uwadze taty. Kopia ma tylko wiersze wklejenia, bez pustych, a wiersz próbny w niej
    kolumny z tabeli; wiersz w obu położeniach jest w ``uncertain_rows`` swojego arkusza, a ze śladem przesunięcia Logi
    mają o nim uwagę, że fakt domeny jest złamany. Uporządkowanie kończy się tak, jak bez Kopii."""

    centrum = ordering_centrum(tmp_path, position.intermax)
    if position.edit is not None:
        position.edit(centrum.register)
    write_report_key(ToolDirectory(tmp_path))

    result = centrum.run_to_end()["result"]
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": ECHO}).json()["body"]

    sent = _sent(centrum)
    [logs] = centrum.run_logs()
    assert [message["code"] for message in logs["messages"] if message["kind"] == "stop"] == (
        [] if position.stop is None else [position.stop]
    ), result
    texts = [path.read_text(encoding="utf-8") for path in sorted(ToolDirectory(tmp_path).run_logs.glob("*"))] + sent
    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if any(value in text for text in [*texts, note])] == []
    [copied] = logs["input_copy"]
    sheets = {sheet["sheet"]: sheet for sheet in copied["sheets"]}
    layout = centrum.layout
    pasted_rows = {ORDER_SHEET: list(layout.raw_rows), OLDER_SHEET: list(layout.older_raw_rows)}
    assert {name: ([row["row"] for row in sheet["rows"]], sheet["empty_rows"]) for name, sheet in sheets.items()} == {
        name: (pasted_rows[name], []) for name in position.sheets
    }
    [echo] = [row["cells"] for row in sheets[ORDER_SHEET]["rows"] if row["row"] == layout.raw_rows[-1]]
    assert echo["M"] == ECHO_MASKED
    probe_row = None
    if position.probe is not None:
        name, index = position.probe
        probe_row = pasted_rows[name][index]
        [cells] = [row["cells"] for row in sheets[name]["rows"] if row["row"] == probe_row]
        assert "".join(sorted(cells)) == position.letters
    assert {name: sheet["uncertain_rows"] for name, sheet in sheets.items()} == {
        name: [probe_row] if position.uncertain and position.probe is not None and position.probe[0] == name else []
        for name in position.sheets
    }
    broken = [note for note in logs["input_copy_notes"] if note.startswith(f"Fakt domeny złamany: wiersz {probe_row} ")]
    assert len(broken) == (position.uncertain and position.traced), logs["input_copy_notes"]


# --- Wpis taty w Calibri 8 we wklejonym wierszu (przegląd #984 r1, r2 i r3) --------------------------------------------
# Tata wpisuje coś czcionką arkusza (Calibri 8) w jedną komórkę wklejonego wiersza, więc wiersz ma wygląd uporządkowany
# (granica bloku z kroju, bez zmian: reguła z większości komórek przestawia u taty granice dziesiątek bloków), a za
# pierwszy wiersz bloku uchodzi następny, który stoi na miejscu. Gdy w kolumnie A nie ma daty z godziną, jego przesunięcia
# nie widać (z datą z godziną pod DATA, z datą tekstem czy bez daty), więc pamięć zna go w obu położeniach (siatka, ADR
# 0025), bez uwagi w Logach, a adres i numer Orange wiersza próbnego nie wychodzą. Z datą z godziną w A, a bez niej pod
# DATA, przesunięcie widać, choć wiersz stoi na miejscu: pamięć zna go tylko przesuniętego, a wartości wychodzą (klasa C,
# ryzyko przyjęte przez Maksa 6.11.2026, ``KNOWN``).


def _typed_by_tata(order: int, column: int, value: object = None) -> Callable[[Path], None]:
    """Tata wpisuje w komórkę ``column`` wiersza zlecenia ``order`` (albo tylko zmienia jej krój) w Calibri 8."""

    def edit(path: Path) -> None:
        workbook = load_workbook(path)
        try:
            sheet = workbook[ORDER_SHEET]
            rows = enumerate(sheet.iter_rows(), start=1)
            [row] = [number for number, cells in rows if any(cell.value == f"ZL-{order}" for cell in cells)]
            cell = sheet.cell(row, column)
            if value is not None:
                cell.value = value  # type: ignore[assignment]  # syntetyczny wpis taty
            cell.font = Font(name="Calibri", sz=8)
            workbook.save(path)
        finally:
            workbook.close()

    return edit


IN_PLACE = "CDFGHJ"
"""Kolumny w Kopii wiersza w obu położeniach, który Planowanie czyta pod nagłówkami (z datą z godziną pod DATA)."""
READ_SHIFTED = "FHIJL"
"""Kolumny w Kopii wiersza w obu położeniach, który Planowanie czyta przesunięty (bez daty z godziną pod DATA)."""
ABOVE_FIRST = Order(datetime(2026, 10, 19, 10), "anna.kowalska", 201, shifted=True, app_look=True)
"""Przesunięty pierwszy wiersz wklejenia nad uporządkowanymi."""


def _at_bottom(index: int, *cells: tuple[int, datetime | str | int]) -> Intermax:
    return Intermax(ordered=ORDERED, raw=_pasted(index, _probe(PASTED[index], *cells)))


def _on_top(*cells: tuple[int, datetime | str | int]) -> Intermax:
    """Wklejenie od wiersza 2, bez uporządkowanych nad nim, wiersz próbny drugi."""

    return Intermax(ordered=(), yellow=None, gap=0, raw=_pasted(1, _probe(PASTED[1], *cells)))


def _above_ordered(*cells: tuple[int, datetime | str | int]) -> Intermax:
    """Wklejenie nad uporządkowanymi z przesuniętym pierwszym wierszem ``ABOVE_FIRST``, wiersz próbny drugi."""

    probe = _probe(Order(datetime(2026, 10, 19, 11), "anna.kowalska", 202), *cells, app_look=True)
    return Intermax(ordered=(ORDERED[0], ABOVE_FIRST, probe, *ORDERED[1:]), raw=PASTED)


@dataclass(frozen=True)
class Typed:
    """Wpis taty w Calibri 8 we wklejonym wierszu: INTERMAX z wierszem próbnym, wpis taty, indeks wiersza próbnego w
    ``PASTED`` (``None``: wiersz próbny nad uporządkowanymi, poza Kopią), jego kolumny w Kopii i klasa ryzyka przyjętego
    przez Maksa (``KNOWN``)."""

    intermax: Intermax
    edit: Callable[[Path], None]
    probe: int | None
    letters: str
    known: str | None = None


TYPED_BY_TATA = {
    # przesunięty pierwszy wiersz: MIASTO (w nim pod AKCJE) w Calibri 8, wiersz próbny drugi
    "miasto_pierwszego_wiersza": Typed(_at_bottom(1), _typed_by_tata(101, 2), 1, IN_PLACE),
    # przesunięty pierwszy wiersz: uwaga taty w UWAGI w Calibri 8, wiersz próbny drugi
    "uwaga_w_pierwszym_wierszu": Typed(_at_bottom(1), _typed_by_tata(101, LAST, "zadzwonić"), 1, IN_PLACE),
    # trzeci wiersz na miejscu: MIASTO w Calibri 8, wiersz próbny czwarty
    "miasto_trzeciego_wiersza": Typed(_at_bottom(3), _typed_by_tata(103, 4), 3, IN_PLACE),
    "miasto_pierwszego_wiersza_wiersz_probny_z_data_jako_tekst": Typed(
        _at_bottom(1, TEXT_DATE), _typed_by_tata(101, 2), 1, READ_SHIFTED
    ),
    "miasto_trzeciego_wiersza_wiersz_probny_z_data_jako_tekst": Typed(
        _at_bottom(3, TEXT_DATE), _typed_by_tata(103, 4), 3, READ_SHIFTED
    ),
    "blok_na_gorze_arkusza_wiersz_probny_z_data_jako_tekst": Typed(
        _on_top(TEXT_DATE), _typed_by_tata(101, 2), 1, READ_SHIFTED
    ),
    "blok_nad_uporzadkowanymi_wiersz_probny_z_data_jako_tekst": Typed(
        _above_ordered(TEXT_DATE), _typed_by_tata(201, 2), None, ""
    ),
    # sonda C4 z przeglądu #984 r3: jak wyżej, a wiersz próbny ma datę z godziną w kolumnie A
    "blok_nad_uporzadkowanymi_wiersz_probny_z_data_w_kolumnie_a": Typed(
        _above_ordered(A_DATE, TEXT_DATE), _typed_by_tata(201, 2), None, "", known="na_miejscu_z_data_w_a"
    ),
}
"""Sondy I1, I1b, I2 z przeglądu #984 r1, N1, N2, N6t, N5t z r2 i C4 z r3."""


@pytest.mark.parametrize(
    "case", [pytest.param(case, id=name, marks=known(case.known)) for name, case in TYPED_BY_TATA.items()]
)
def test_wpis_taty_w_calibri_8_we_wklejonym_wierszu_nie_wypuszcza_adresu_ani_numeru_orange_nastepnego(
    tmp_path: Path, case: Typed
) -> None:
    """Fakt domeny zachodzi, a tata wpisał coś w Calibri 8 w wiersz wklejenia nad wierszem próbnym: adres i numer Orange
    wiersza próbnego nie wychodzą do pliku Logów, do Skrzynki Zgłoszeń ani w Uwadze taty, a Logi nie mówią o złamanym
    fakcie domeny. Wiersz próbny, który zaczyna blok i stoi na miejscu, Kopia ma w obu położeniach, bez ``NUMER ZL.``
    spod nagłówka."""

    centrum = ordering_centrum(tmp_path, case.intermax)
    case.edit(centrum.register)
    write_report_key(ToolDirectory(tmp_path))

    centrum.run_to_end()
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": ECHO}).json()["body"]

    texts = [path.read_text(encoding="utf-8") for path in sorted(ToolDirectory(tmp_path).run_logs.glob("*"))]
    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if any(value in text for text in [*texts, *_sent(centrum), note])] == []
    [logs] = centrum.run_logs()
    assert [note for note in logs["input_copy_notes"] if note.startswith("Fakt domeny złamany")] == []
    [sheet] = logs["input_copy"][0]["sheets"]
    probe_row = None if case.probe is None else centrum.layout.raw_rows[case.probe]
    cells = [row["cells"] for row in sheet["rows"] if row["row"] == probe_row]
    assert (sheet["uncertain_rows"], ["".join(sorted(found)) for found in cells]) == (
        ([], []) if probe_row is None else ([probe_row], [case.letters])
    )


TYPED_IN_DIAGNOSIS = {
    # sonda D9 z przeglądu #984 r2: MIASTO przesuniętego pierwszego wiersza w Calibri 8
    "miasto_pierwszego_wiersza": (_at_bottom(1, TEXT_DATE), _typed_by_tata(101, 4), None),
    # sonda D10 z r2: wklejenie od wiersza 2, SKUTECZNE przesuniętego pierwszego wiersza w Calibri 8
    "skuteczne_pierwszego_wiersza_na_gorze_arkusza": (_on_top(TEXT_DATE), _typed_by_tata(101, 12, "tak"), None),
    # sondy DC4 i DC5 z r3: jak wyżej, a wiersz próbny ma datę z godziną w kolumnie A
    "miasto_pierwszego_wiersza_wiersz_probny_z_data_w_kolumnie_a": (
        _at_bottom(1, A_DATE, TEXT_DATE),
        _typed_by_tata(101, 4),
        "na_miejscu_z_data_w_a",
    ),
    "skuteczne_pierwszego_wiersza_na_gorze_arkusza_wiersz_probny_z_data_w_kolumnie_a": (
        _on_top(A_DATE, TEXT_DATE),
        _typed_by_tata(101, 12, "tak"),
        "na_miejscu_z_data_w_a",
    ),
}
"""INTERMAX z wierszem próbnym drugim na miejscu, z datą tekstem pod DATA, wpis taty i klasa ryzyka (``KNOWN``)."""


@pytest.mark.parametrize(
    ("intermax", "edit"),
    [
        pytest.param(intermax, edit, id=name, marks=known(klass))
        for name, (intermax, edit, klass) in TYPED_IN_DIAGNOSIS.items()
    ],
)
def test_diagnoza_intermax_zna_adres_i_numer_orange_wiersza_na_miejscu_pod_wpisem_taty_w_calibri_8(
    tmp_path: Path, intermax: Intermax, edit: Callable[[Path], None]
) -> None:
    """Diagnoza czyta cały INTERMAX jako Rejestr zleceń (``preparation_register.register_problem``, jak ``centrum/diagnosis.py``).
    Tata wpisał coś w Calibri 8 w przesunięty pierwszy wiersz wklejenia, więc za pierwszy wiersz bloku uchodzi wiersz
    próbny pod nim, który stoi na miejscu: pamięć reguły danych zna jego adres i numer Orange pod nagłówkami."""

    path = tmp_path / "INTERMAX.xlsx"
    intermax.write(path)
    edit(path)
    memory = empty_memory()

    preparation_register.register_problem(path, DadFiles(forbidden=memory))

    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if not guarded(memory, value, "Uwaga taty").notes] == []
