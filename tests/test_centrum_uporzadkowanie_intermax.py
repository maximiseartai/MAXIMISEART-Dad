"""Uporządkowanie INTERMAX z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka (#470).

Karta „Uporządkuj INTERMAX” stoi poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty, a okres Uruchomienia to
okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
import pytest

from rozliczenia import intermax_copies, workbook_files
from rozliczenia.centrum.run_logs import RunLog

from tests.fixtures.centrum import finished_view, phase_states, views_until
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
from tests.fixtures.intermax import (
    ADDRESS,
    CONTRACT_NUMBER,
    DEVICES,
    FIRST,
    HEADERS,
    LAST,
    NUMBER,
    ORDER_SHEET,
    Intermax,
    Order,
    rewrite_parts,
)
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
    older = "xl/worksheets/sheet2.xml"
    rewrite_parts(centrum.register, lambda name, data: data.replace(b"<sheetData>", b"<sheetData><!-- x -->") if name == older else data)

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
    assert (run["process"], run["title"], run["period"], run["dry_run"], run["confirms_readiness"]) == (
        "intermax",
        "Uporządkowanie INTERMAX",
        PERIOD,
        False,
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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY123\n", encoding="utf-8")
    open_in_excel(centrum.register)

    run_id = _stopped(centrum)["run"]["id"]

    [logs] = centrum.run_logs()
    assert (logs["run_id"], logs["process"], logs["mode"], logs["period"]) == (run_id, "intermax", "zapis", PERIOD)
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
        "Ustawienia taty",
        "Pliki w OneDrive",
        "INTERMAX",
        "Aktualność narzędzia",
        "Token do Zgłoszeń",
        "Dziennik Centrum rozliczeń",
    ]
    assert checks["Ustawienia taty"] == ("passed", "INTERMAX jest na miejscu.")
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
    assert (states["Ustawienia taty"], states["INTERMAX"]) == ("failed", "not_checked")


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
    collective = periods / PERIOD / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
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

    [path] = (centrum.tmp_path / "logs" / "uruchomienia").glob(f"*-{like}.json")
    record = RunLog.model_validate_json(path.read_text(encoding="utf-8"))
    started_at = record.started_at.replace(microsecond=0) + later
    times = {"started_at": started_at, "ended_at": started_at + (record.ended_at - record.started_at)}
    other = record.model_copy(update={"run_id": uuid4().hex, **times, **changes})
    other_path = path.with_name(other.file_name)
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
    [intermax_logs] = (centrum.tmp_path / "logs" / "uruchomienia").glob(f"*-{ordered}.json")
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
    [path] = (centrum.tmp_path / "logs" / "uruchomienia").glob(f"*-{ordered}.json")
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
    [path] = (tmp_path / "logs" / "uruchomienia").glob("*.json")
    text = path.read_text(encoding="utf-8")
    for order in raw:
        for column, value in order.values().items():
            if column in (ADDRESS, CONTRACT_NUMBER) or column > LAST:
                assert str(value) not in text, value
    assert "akt pętli" not in text and "nokia" not in text, "bez wartości Wpisu"


def test_karta_wraca_z_logow_uporzadkowania_sprzed_wpisow_intermax(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    ordered = centrum.run_to_end()["run"]["id"]
    [path] = (tmp_path / "logs" / "uruchomienia").glob(f"*-{ordered}.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["intermax_entries"]
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    centrum.restart()

    last = centrum.setup()["last"]
    assert (last["run"]["id"], last["result"]["summary"]) == (ordered, SUMMARY)


def test_start_z_okresem_nie_przyjmuje_uporzadkowania_intermax(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)

    refused = centrum.client.post("/api/runs", json={"process": "intermax", "period": PERIOD, "dry_run": False})

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


A_TYPED = datetime(2026, 10, 26, 11)
"""Data z godziną, którą tata wpisał w kolumnę A wklejonego wiersza na miejscu."""


def test_logi_uporzadkowania_maja_wklejone_wiersze_bez_adresu_i_numeru_umowy_oraz_odcisk_przeczytanego_intermax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kopia wejścia Uporządkowania to każdy arkusz zleceń INTERMAX z nagłówkami bez ``ADRES`` i ``NUMER UMOWY`` i z
    wklejonymi wierszami, które Planowanie rozpoznaje, a nie z uporządkowanymi dniami nad nimi ani starszym arkuszem bez
    wklejenia, z komórkami od A do ``UWAGI``, które Uporządkowanie przenosi do dnia. Przesunięty pierwszy wiersz ma
    komórki pod ich nagłówkiem, bez kolumn z aplikacji, które w pliku wpadły pod ``ZWROT`` i ``UWAGI``, a jako pierwszy
    wiersz wklejenia ma dwa położenia, więc nie ma też ``URZĄDZENIA`` i ``CZYNNOŚCI ZREALIZOWANE``, które w położeniu bez
    przesunięcia stałyby pod ``ADRES`` i ``NUMER UMOWY`` (ADR 0025). Każdy inny wklejony wiersz też ma dwa położenia, a
    że jego jedyne Hiperłącze stoi pod ``NUMER ZL.``, pod ``DATA GODZ. POCZ.`` jest data z godziną, a kolumna A jest
    pusta, ma w Kopii wszystkie komórki. Wiersz z datą z godziną w kolumnie A ma ślad przesunięcia, więc ma datę spod
    ``DATA GODZ. POCZ.``, ale nie ``NUMER ZL.``, a Logi mówią, że fakt domeny jest złamany. Z dołu arkusza nad
    wklejeniem Kopia ma tylko numery ostatniego uporządkowanego i żółtego wiersza, od których Planowanie liczy
    wiersz dnia (#847). Odcisk to rozmiar i skrót bajtów, które
    Uporządkowanie przeczytało, choć zaraz po odczycie OneDrive albo Autozapis Excela zapisał INTERMAX z innymi
    bajtami, i chwila zmiany sprzed odczytu."""

    pasted = list(Intermax().raw)
    pasted[2] = replace(pasted[2], cells=((1, A_TYPED),))
    centrum = ordering_centrum(tmp_path, Intermax(older_sheet=True, raw=pasted))
    os.utime(centrum.register, (READ_AT.timestamp(), READ_AT.timestamp()))
    content = centrum.register.read_bytes()
    file_bytes = workbook_files._file_bytes
    saved_again: list[bytes] = []

    def read_then_saved(path: Path) -> bytes:
        read = file_bytes(path)
        if path == centrum.register and read == content:
            rewrite_parts(path, lambda name, data: data.replace(b">komentarz<", b">komentarz zapisany znowu<"))
            os.utime(path, (SAVED_AGAIN_AT.timestamp(), SAVED_AGAIN_AT.timestamp()))
            saved_again.append(path.read_bytes())
        return read

    # Jedyny odczyt bajtów skoroszytu w src/ (tests/test_jeden_odczyt_skoroszytu.py).
    monkeypatch.setattr(workbook_files, "_file_bytes", read_then_saved)

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
        "order_kinds": {},
    }
    first = centrum.layout.first_raw
    assert (sheet["sheet"], sheet["header_row"], sheet["columns"], sheet["empty_rows"]) == (ORDER_SHEET, 1, COPY_COLUMNS, [])
    assert sheet["shifted_row"] == first
    assert centrum.layout.yellow is not None
    assert (sheet["last_ordered_row"], sheet["yellow_row"]) == (centrum.layout.last_ordered, centrum.layout.yellow)
    assert sheet["rows"][2]["cells"]["A"] == {"type": "datetime", "text": A_TYPED.isoformat()}
    # W drugim położeniu pod ADRES i NUMER UMOWY stałyby: w przesuniętym pierwszym wierszu URZĄDZENIA i CZYNNOŚCI
    # ZREALIZOWANE, a w wierszu z datą w A NUMER ZL. (ZWROT i UWAGI za UWAGI). Wiersz na miejscu z jedynym Hiperłączem
    # pod NUMER ZL., datą pod DATA i pustą kolumną A ma NUMER ZL. i wszystko na prawo od niego na miejscu.
    second_position = {0: {"G", "M"}, 2: {"I", "N", "O"}}
    assert sheet["rows"] == [
        {
            "row": first + index,
            "cells": {
                letter: value
                for letter, value in _copied_cells(order).items()
                if letter not in second_position.get(index, set())
            },
        }
        for index, order in enumerate(centrum.layout.raw)
    ]
    assert (sheet["uncertain_rows"], sheet["order_kinds"]) == (list(centrum.layout.raw_rows), {})
    assert logs["input_copy_notes"] == [
        f"Fakt domeny złamany: wiersz {first + 2} arkusza {ORDER_SHEET} w {REGISTER_NAME} ma ślad przesunięcia (data z "
        "godziną dwie kolumny na lewo od DATA GODZ. POCZ.), a nie jest pierwszym wierszem bloku wklejenia; pamięć reguły "
        "danych zna go w obu położeniach (ADR 0025)."
    ]


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
        Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 103, cells=((13, PHONE_WITH_PREFIX),)),
    )
    centrum = ordering_centrum(tmp_path, Intermax(raw=raw))
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")

    view = centrum.run_to_end()

    assert view["result"]["result"] == "OK", view["result"]["stops"]
    sent = _sent(centrum)
    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    [sheet] = copied["sheets"]
    cells = [row["cells"] for row in sheet["rows"]]
    assert [letter for row in cells for letter in ("E", "K") if letter in row] == []
    assert (cells[0]["O"], cells[1]["M"], cells[2]["M"]) == ("[numer Orange]", MASKED, "[telefon]")
    note = "Reguła danych: zamaskowano wartość kolumny {} w: input_copy[0].sheets[0].rows[{}].cells.[…]."
    assert logs["input_copy_notes"] == [
        note.format("NUMER UMOWY/ZLECENIA ORANGE", 0),
        note.format("ADRES", 1),
        note.format("NUMER UMOWY/ZLECENIA ORANGE", 1),
    ]
    assert any(MASKED in part for part in sent), "Kopia wejścia w pliku Logów w Archiwum"
    texts = [path.read_text(encoding="utf-8") for path in sorted((tmp_path / "logs" / "uruchomienia").glob("*"))] + sent
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
    older = "xl/worksheets/sheet2.xml"
    rewrite_parts(centrum.register, lambda name, data: data.replace(b"<sheetData>", b"<sheetData><!-- x -->") if name == older else data)
    content = centrum.register.read_bytes()

    result = _stopped(centrum)["result"]

    assert (result["stop_kind"], result["stops"][0]["where"]) == ("for_maks", f"plik {REGISTER_NAME}, folder OneDrive, arkusz {OLDER_SHEET}")
    assert result["stops"][0]["what"] == "Wklejone zlecenia mają układ, którego narzędzie nie porządkuje. INTERMAX nie został zmieniony."
    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    assert copied["fingerprint"]["sha256"] == hashlib.sha256(content).hexdigest()
    [sheet] = copied["sheets"]
    assert (sheet["sheet"], [row["cells"]["M"] for row in sheet["rows"] if "M" in row["cells"]]) == (ORDER_SHEET, ["montaż [adres]"])
    [path] = (tmp_path / "logs" / "uruchomienia").glob("*.json")
    assert ADDRESS_VALUE not in path.read_text(encoding="utf-8")


# --- Położenia wklejonego wiersza (#842, #913) ---------------------------------------------------------------------------
# Tabela położeń z opisu PR #905 i tabela decyzji opcji 3 (#913, ADR 0025): wiersz próbny niesie syntetyczny adres i
# numer Orange tam, gdzie w pliku stoją jego kolumny ``ADRES`` i ``NUMER UMOWY``, ostatnie zlecenie wklejenia cytuje je
# w ``CZYNNOŚCI ZREALIZOWANE``, a tata potem w Uwadze, więc strażnik musi je znać, gdziekolwiek stały. Dwa położenia
# ma każdy wiersz z wyglądem z aplikacji (każdy wklejony i wiersz nad uporządkowanymi), choć fakt domeny mówi, że
# przesunięty przychodzi tylko pierwszy wklejony; Kopia ma z niego tylko komórki dozwolone w obu położeniach i datę z
# godziną spod ``DATA GODZ. POCZ.``, gdy położenie podstawowe to położenie odczytu, a pamięć reguły danych zna oba.
# ``NUMER ZL.`` uporządkowanego wiersza, który stoi tam, gdzie numer Orange przesuniętego, cytowany w tym samym tekście
# zostaje: może wyjść (ADR 0025).

PROBE_ADDRESS = "Przemiatana Wrzosowa 12 Kórnik"
PROBE_ORANGE = "4809876543"
ORDERED = (
    Order(datetime(2026, 10, 19, 9), "anna.kowalska", 1001),
    Order(datetime(2026, 10, 19, 12), "anna.kowalska", 1002),
    Order(datetime(2026, 10, 20, 8), "jan.nowak", 1003),
)
ECHO = f"montaż {PROBE_ADDRESS} umowa {PROBE_ORANGE} po ZL-1003"
ECHO_MASKED = "montaż [adres] umowa [numer Orange] po ZL-1003"
NOTE = {"title": "Pytanie", "body": f"Klient {PROBE_ADDRESS}, umowa {PROBE_ORANGE}"}
"""Uwaga taty po Uruchomieniu cytuje adres i numer Orange wiersza próbnego."""
DONE = 13
"""``CZYNNOŚCI ZREALIZOWANE`` (M), wolny tekst technika."""
PASTED = (
    Order(datetime(2026, 10, 26, 14), "jan.nowak", 101),
    Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102),
    Order(datetime(2026, 10, 26, 16), "anna.kowalska", 103),
    Order(datetime(2026, 10, 26, 8), "jan.nowak", 104),
    Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 105, cells=((DONE, ECHO),)),
)
LEFT_OF_DATE = 1
"""Kolumna A bez nagłówka, dwie na lewo od ``DATA GODZ. POCZ.``: w wierszu na miejscu pusta."""


def _probe(
    order: Order, *cells: tuple[int, datetime | str | int], shifted: bool = False, app_look: bool = False, **changes: Any
) -> Order:
    """Zlecenie ``order`` jako wiersz próbny: adres i numer Orange w kolumnach ``ADRES`` i ``NUMER UMOWY``."""

    return replace(
        order,
        cells=((ADDRESS, PROBE_ADDRESS), (CONTRACT_NUMBER, PROBE_ORANGE), *cells),
        shifted=shifted,
        app_look=app_look,
        **changes,
    )


def _pasted(index: int, probe: Order) -> tuple[Order, ...]:
    return (*PASTED[:index], probe, *PASTED[index + 1 :])


def _older_sheet_unsupported(register: Path) -> None:
    """Starszy arkusz zleceń, którego wierszy nie da się rozdzielić: Planowanie staje na nim, zanim dojdzie do wklejenia."""

    older = "xl/worksheets/sheet2.xml"
    rewrite_parts(
        register, lambda name, data: data.replace(b"<sheetData>", b"<sheetData><!-- x -->") if name == older else data
    )


def _hyperlinks_unclosed(register: Path) -> None:
    """Zepsuty blok Hiperłączy arkusza zleceń: bez ``</hyperlinks>``."""

    rewrite_parts(register, lambda name, data: data.replace(b"</hyperlinks>", b"", 1) if name.startswith("xl/worksheets/") else data)


@dataclass(frozen=True)
class Position:
    """Wiersz tabeli położeń: INTERMAX z wierszem próbnym i to, co tabela mówi o nim w Kopii wejścia.

    ``probe``: arkusz i indeks wiersza próbnego w ``raw`` albo ``older_raw``; ``None``: wiersza nie ma w Kopii.
    ``letters``: kolumny wiersza próbnego w Kopii (każdy wklejony wiersz ma dwa położenia), ``stop``: kod
    Zatrzymania (``None``: Uporządkowanie kończy się wynikiem OK), ``sheets``: arkusze w Kopii, ``address_in_file``:
    adres wiersza próbnego stoi w pliku jako tekst (bez tego ``ADRES`` to data z godziną, a pilnuje się numeru Orange),
    ``echo``: ``CZYNNOŚCI ZREALIZOWANE`` ostatniego zlecenia w Kopii po strażniku, ``broken``: ile wierszy Kopii ma uwagę,
    że fakt domeny jest złamany (silny ślad przesunięcia poza pierwszym wierszem bloku).
    """

    intermax: Intermax
    probe: tuple[str, int] | None
    letters: str
    stop: str | None
    sheets: tuple[str, ...] = (ORDER_SHEET,)
    edit: Callable[[Path], None] | None = None
    address_in_file: bool = True
    echo: str = ECHO_MASKED
    broken: int = 0

    @property
    def secrets(self) -> tuple[str, ...]:
        return (PROBE_ADDRESS, PROBE_ORANGE) if self.address_in_file else (PROBE_ORANGE,)


SAME_CLIENT = replace(
    PASTED[2], cells=((ADDRESS, PROBE_ADDRESS), (NUMBER, PROBE_ORANGE), (CONTRACT_NUMBER, "")), links=()
)
"""Zlecenie tego samego klienta co wiersz próbny, w którym numer Orange stoi pod ``NUMER ZL.``, bez Hiperłącza."""
TEXT_DATE = (3, "26.10.2026 11:00")
"""``DATA GODZ. POCZ.`` jako tekst, nie data z godziną."""
A_DATE = (LEFT_OF_DATE, datetime(2026, 10, 26, 11))
"""Data z godziną w kolumnie A, dwie na lewo od ``DATA GODZ. POCZ.``, jak w przesuniętym wierszu."""
POSITIONS = {
    # U1 tabeli decyzji: wiersz na miejscu bez śladu ma dwa położenia, a jego jedyne Hiperłącze pod NUMER ZL. (z
    # datą pod DATA i pustą kolumną A) zostawia w Kopii NUMER ZL. i wszystko od niego w prawo
    "zwykly_wiersz": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1]))), (ORDER_SHEET, 1), "CDFGHIJ", None
    ),
    # U9: pierwszy wiersz wklejenia ma dwa położenia, także przesunięty z datą w A
    "przesuniety_pierwszy_wiersz_wklejenia": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0]))), (ORDER_SHEET, 0), "CDFHIJ", None
    ),
    # U10 (repro 1 z #913): pierwszy wiersz kolejnego wklejenia, ślad: data w A i brak daty pod DATA
    "przesuniety_pierwszy_wiersz_kolejnego_wklejenia": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True))),
        (ORDER_SHEET, 2),
        "ABDFGH",
        "SUROWE_ZLECENIE_BEZ_DATY",
        broken=1,
    ),
    # U15: ten sam bez Hiperłącza (ślad zostaje w datach)
    "przesuniety_pierwszy_wiersz_kolejnego_wklejenia_bez_hiperlacza": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True, links=()))),
        (ORDER_SHEET, 2),
        "ABDFGH",
        "SUROWE_ZLECENIE_BEZ_DATY",
        broken=1,
    ),
    # U8 (repro 2): pierwszy wiersz z datą jako tekstem na miejscu
    "pierwszy_wiersz_z_data_jako_tekst_na_miejscu": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], TEXT_DATE)), shifted=False),
        (ORDER_SHEET, 0),
        "FHIJL",
        "SUROWE_ZLECENIE_BEZ_DATY",
    ),
    # U7 (T9 z #917): pierwszy wiersz na miejscu z datą w A i słowem pod DATA, czytany przesunięty
    "pierwszy_wiersz_na_miejscu_z_data_w_A_i_slowem_pod_data": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], (3, "brak"), A_DATE)), shifted=False),
        (ORDER_SHEET, 0),
        "CFHIJL",
        None,
    ),
    # U3: ślad, brak daty z godziną pod DATA
    "wiersz_z_data_jako_tekst": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], TEXT_DATE))),
        (ORDER_SHEET, 1),
        "DFGHJ",
        "SUROWE_ZLECENIE_BEZ_DATY",
    ),
    # U4 (W1 z #917): ślad, data z godziną dwie kolumny przed DATA w wierszu na miejscu
    "wiersz_z_data_z_godzina_takze_dwie_kolumny_przed_data": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], A_DATE))), (ORDER_SHEET, 1), "ACDFGHJ", None,
        broken=1,
    ),
    # U6: ślad, Hiperłącze NUMER ZL. pod URZĄDZENIA w wierszu na miejscu
    "wiersz_z_hiperlaczem_pod_urzadzenia": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], links=(7,)))), (ORDER_SHEET, 1), "CDFGHJ", None,
        broken=1,
    ),
    # U6b, U6c (D2 z przeglądu #966 r2): Hiperłącze pod NUMER UMOWY albo pod ADRES to też ślad
    "wiersz_z_hiperlaczem_pod_numer_umowy": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], links=(CONTRACT_NUMBER,)))),
        (ORDER_SHEET, 1),
        "CDFGHJ",
        None,
        broken=1,
    ),
    "wiersz_z_hiperlaczem_pod_adres": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1], links=(ADDRESS,)))),
        (ORDER_SHEET, 1),
        "CDFGHJ",
        None,
        broken=1,
    ),
    # U11 (W3 z #917): przesunięty z ADRES jako datą z godziną i datą jako tekstem w A
    "przesuniety_z_adresem_jako_data_i_tekstem_daty_w_A": Position(
        Intermax(
            ordered=ORDERED,
            raw=_pasted(2, _probe(PASTED[2], (3, "26.10.2026 11:00"), (ADDRESS, datetime(2026, 10, 26, 12)), shifted=True)),
        ),
        (ORDER_SHEET, 2),
        "ABCDFGH",
        "SUROWE_ZLECENIE_BEZ_WYKONAWCY",
        address_in_file=False,
        echo=f"montaż {PROBE_ADDRESS} umowa [numer Orange] po ZL-1003",
        broken=1,
    ),
    # U12: przesunięty z ADRES jako datą z godziną i pustą DATA: ślad tylko w Hiperłączu pod URZĄDZENIA
    "przesuniety_z_adresem_jako_data_i_pusta_data": Position(
        Intermax(
            ordered=ORDERED,
            raw=_pasted(2, _probe(PASTED[2], (3, ""), (ADDRESS, datetime(2026, 10, 26, 12)), shifted=True)),
        ),
        (ORDER_SHEET, 2),
        "BCDFGH",
        "SUROWE_ZLECENIE_BEZ_WYKONAWCY",
        address_in_file=False,
        echo=f"montaż {PROBE_ADDRESS} umowa [numer Orange] po ZL-1003",
        broken=1,
    ),
    # U13: przesunięty, na miejscu od ADRES (tata wstawił dwie komórki w C:D)
    "przesuniety_na_miejscu_od_adres": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True, in_place_from=ADDRESS))),
        (ORDER_SHEET, 2),
        "ABFGHJ",
        "SUROWE_ZLECENIE_BEZ_DATY",
        broken=1,
    ),
    # U14 (W4 z #917 r3): przesunięty, na miejscu od WYKONAWCA, Hiperłącze zostaje pod URZĄDZENIA
    "przesuniety_na_miejscu_od_wykonawca": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True, in_place_from=10))),
        (ORDER_SHEET, 2),
        "ABDFGJ",
        "SUROWE_ZLECENIE_BEZ_DATY",
        broken=1,
    ),
    # U21: przesunięty pierwszy wiersz wklejenia, na miejscu od NUMER UMOWY (na main wyciek numeru Orange)
    "przesuniety_pierwszy_wiersz_na_miejscu_od_numer_umowy": Position(
        Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], in_place_from=CONTRACT_NUMBER))),
        (ORDER_SHEET, 0),
        "CDFHIJ",
        None,
    ),
    # U16: zepsuty blok Hiperłączy, więc ślad w każdym wierszu arkusza, także uporządkowanym, którego NUMER ZL. stoi
    # tam, gdzie numer Orange przesuniętego; Zatrzymanie jak bez Kopii
    "zepsuty_blok_hiperlaczy": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(PASTED[1]))),
        (ORDER_SHEET, 1),
        "CDFGHJ",
        "NIEOBSLUGIWANY_UKLAD_INTERMAX",
        edit=_hyperlinks_unclosed,
        echo="montaż [adres] umowa [numer Orange] po [numer Orange]",
        broken=len(PASTED) - 1,
    ),
    # U24 (W3 z przeglądu #966): przesunięty w środku wklejenia bez śladu (pusta DATA z aplikacji, ADRES jako data z
    # godziną, bez Hiperłącza): chroni go same dwa położenia każdego wklejonego wiersza; granica: Kopia niesie ADRES
    # jako datę z godziną pod DATA GODZ. POCZ., bo położenie podstawowe to położenie odczytu
    "przesuniety_w_srodku_bez_sladu": Position(
        Intermax(
            ordered=ORDERED,
            raw=_pasted(2, _probe(PASTED[2], (3, ""), (ADDRESS, datetime(2026, 10, 26, 12)), shifted=True, links=())),
        ),
        (ORDER_SHEET, 2),
        "BCDFGH",
        "SUROWE_ZLECENIE_BEZ_WYKONAWCY",
        address_in_file=False,
        echo=f"montaż {PROBE_ADDRESS} umowa [numer Orange] po ZL-1003",
    ),
    # U25 (D1 z przeglądu #966): adres i numer Orange pierwszego wiersza na miejscu w zwykłej kolumnie innego wiersza:
    # położenie podstawowe (na miejscu) pamięć zna wszędzie
    "adres_pierwszego_wiersza_na_miejscu_pod_urzadzenia_innego_wiersza": Position(
        Intermax(
            ordered=ORDERED,
            raw=(_probe(PASTED[0]), PASTED[1], replace(PASTED[2], cells=((DEVICES, PROBE_ADDRESS),)), *PASTED[3:]),
            shifted=False,
        ),
        (ORDER_SHEET, 0),
        "CDFGHIJ",
        None,
    ),
    "numer_orange_pierwszego_wiersza_na_miejscu_pod_numer_zl_innego_wiersza": Position(
        Intermax(
            ordered=ORDERED,
            raw=(_probe(PASTED[0]), PASTED[1], replace(PASTED[2], cells=((NUMBER, PROBE_ORANGE),)), *PASTED[3:]),
            shifted=False,
        ),
        (ORDER_SHEET, 0),
        "CDFGHIJ",
        None,
    ),
    # U26: ten sam klient w innym wierszu, a w nim NUMER UMOWY pod NUMER ZL. bez Hiperłącza (granica 2 z ADR 0025)
    "numer_umowy_pod_numer_zl_u_klienta_pierwszego_wiersza_na_miejscu": Position(
        Intermax(ordered=ORDERED, raw=(_probe(PASTED[0]), PASTED[1], SAME_CLIENT, *PASTED[3:]), shifted=False),
        (ORDER_SHEET, 0),
        "CDFGHIJ",
        None,
    ),
    "numer_umowy_pod_numer_zl_u_klienta_przesunietego_pierwszego_wiersza": Position(
        Intermax(ordered=ORDERED, raw=(_probe(PASTED[0]), PASTED[1], SAME_CLIENT, *PASTED[3:])),
        (ORDER_SHEET, 0),
        "CDFHIJ",
        None,
    ),
    # U27 (K2 z przeglądu #966): adres przesuniętego pierwszego wiersza pod URZĄDZENIA innego wiersza: położenie
    # podstawowe (przesunięte, data w A) pamięć zna wszędzie
    "adres_przesunietego_pierwszego_wiersza_pod_urzadzenia_innego_wiersza": Position(
        Intermax(ordered=ORDERED, raw=(_probe(PASTED[0]), PASTED[1], replace(PASTED[2], cells=((DEVICES, PROBE_ADDRESS),)), *PASTED[3:])),
        (ORDER_SHEET, 0),
        "CDFHIJ",
        None,
    ),
    # U28: wiersz uporządkowany (Calibri 8) nad wklejeniem, przesunięty, z datą w A: ślad daje mu dwa położenia
    "przesuniety_wiersz_uporzadkowany_nad_wklejeniem": Position(
        Intermax(
            ordered=(*ORDERED, _probe(Order(datetime(2026, 10, 20, 12), "jan.nowak", 203), shifted=True, links=())),
            raw=PASTED,
        ),
        None,
        "",
        None,
    ),
    "pusty_wiersz_nad_kolejnym_wklejeniem": Position(
        Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], shifted=True)), blank_in_paste=frozenset({2})),
        (ORDER_SHEET, 2),
        "ABDFGH",
        "SUROWE_ZLECENIE_BEZ_DATY",
        broken=1,
    ),
    # U2 (D2 z #913): wiersz bez Wykonawcy ma datę z godziną w Kopii
    "wiersz_bez_wykonawcy": Position(
        Intermax(ordered=ORDERED, raw=_pasted(1, _probe(replace(PASTED[1], worker="")))),
        (ORDER_SHEET, 1),
        "CDFGHI",
        "SUROWE_ZLECENIE_BEZ_WYKONAWCY",
    ),
    # U17
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
        "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
    ),
    # U17: ten sam bez śladu (pusta DATA, ADRES jako data z godziną, bez Hiperłącza): chroni go sama reguła wiersza z
    # wyglądem z aplikacji nad uporządkowanymi
    "przesuniety_wiersz_z_aplikacji_nad_uporzadkowanymi_bez_sladu": Position(
        Intermax(
            ordered=(
                *ORDERED,
                _probe(
                    Order(datetime(2026, 10, 20, 12), "jan.nowak", 202),
                    (3, ""),
                    (ADDRESS, datetime(2026, 10, 20, 13)),
                    shifted=True,
                    app_look=True,
                    links=(),
                ),
                Order(datetime(2026, 10, 20, 14), "jan.nowak", 1004),
            ),
            raw=PASTED,
        ),
        None,
        "",
        "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
        address_in_file=False,
        echo=f"montaż {PROBE_ADDRESS} umowa [numer Orange] po ZL-1003",
    ),
    # U22
    "zatrzymanie_zanim_planowanie_doszlo_do_wklejenia": Position(
        Intermax(ordered=ORDERED, older_sheet=True, raw=_pasted(2, _probe(PASTED[2], shifted=True))),
        (ORDER_SHEET, 2),
        "ABDFGH",
        "NIEOBSLUGIWANY_UKLAD_INTERMAX",
        edit=_older_sheet_unsupported,
        broken=1,
    ),
    "wklejenie_z_kilku_dni": Position(
        Intermax(
            ordered=ORDERED,
            raw=(replace(PASTED[0], when=datetime(2026, 10, 27, 14)), *_pasted(1, _probe(PASTED[1]))[1:]),
        ),
        (ORDER_SHEET, 1),
        "CDFGHIJ",
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
        "CDFHIJ",
        "SUROWE_ZLECENIA_W_KILKU_ARKUSZACH",
        sheets=(OLDER_SHEET, ORDER_SHEET),
    ),
}


@pytest.mark.parametrize("position", POSITIONS.values(), ids=POSITIONS.keys())
def test_adres_i_numer_orange_wklejonego_wiersza_nie_wychodza_w_zadnym_polozeniu_wiersza(
    tmp_path: Path, position: Position
) -> None:
    """Każde położenie wklejonego wiersza z tabeli położeń (opis PR #905) i tabeli decyzji opcji 3 (#913): adres i numer
    Orange wiersza próbnego nie wychodzą do pliku Logów, do Skrzynki Zgłoszeń ani w Uwadze taty, także zacytowane w
    ``CZYNNOŚCI ZREALIZOWANE`` innego zlecenia, które strażnik maskuje. Kopia ma tylko wiersze wklejenia, bez pustych, a
    wiersz próbny w niej kolumny z tabeli; każdy wklejony wiersz ma dwa położenia, więc jest w ``uncertain_rows`` swojego
    arkusza. Uporządkowanie kończy się tak, jak bez Kopii."""

    centrum = ordering_centrum(tmp_path, position.intermax)
    if position.edit is not None:
        position.edit(centrum.register)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")

    result = centrum.run_to_end()["result"]
    note = centrum.client.post("/api/dad-notes/draft", json=NOTE).json()

    sent = _sent(centrum)
    [logs] = centrum.run_logs()
    assert [message["code"] for message in logs["messages"] if message["kind"] == "stop"] == (
        [] if position.stop is None else [position.stop]
    ), result
    texts = [path.read_text(encoding="utf-8") for path in sorted((tmp_path / "logs" / "uruchomienia").glob("*"))] + sent
    assert [value for value in position.secrets if any(value in text for text in texts)] == []
    address = "[adres]" if position.address_in_file else PROBE_ADDRESS
    assert note["body"].splitlines()[0] == f"Klient {address}, umowa [numer Orange]"
    [copied] = logs["input_copy"]
    sheets = {sheet["sheet"]: sheet for sheet in copied["sheets"]}
    layout = centrum.layout
    pasted_rows = {ORDER_SHEET: list(layout.raw_rows), OLDER_SHEET: list(layout.older_raw_rows)}
    assert {name: ([row["row"] for row in sheet["rows"]], sheet["empty_rows"]) for name, sheet in sheets.items()} == {
        name: (pasted_rows[name], []) for name in position.sheets
    }
    [echo] = [row["cells"] for row in sheets[ORDER_SHEET]["rows"] if row["row"] == layout.raw_rows[-1]]
    assert echo["M"] == position.echo
    if position.probe is not None:
        name, index = position.probe
        probe_row = pasted_rows[name][index]
        [cells] = [row["cells"] for row in sheets[name]["rows"] if row["row"] == probe_row]
        assert "".join(sorted(cells)) == position.letters
    assert {name: sheet["uncertain_rows"] for name, sheet in sheets.items()} == {
        name: pasted_rows[name] for name in position.sheets
    }
    broken = [note for note in logs["input_copy_notes"] if note.startswith("Fakt domeny złamany: wiersz ")]
    assert len(broken) == position.broken, logs["input_copy_notes"]


# --- Adres i numer Orange także w zwykłej kolumnie innego wiersza (W1 z przeglądu #966 r2, wariant B) ----------------
# Wartość wiersza próbnego stoi też pod URZĄDZENIA innego wiersza, a podpis przesunięcia kłamie albo go brak. Pierwszy
# wiersz bloku bez przesunięcia potwierdzonego trzema faktami (data z godziną w A, pod DATA bez niej, jedyne Hiperłącze
# pod URZĄDZENIA, ``raw_orders.confirmed_shift``) pamięć reguły danych zna w obu położeniach wszędzie, więc ta komórka
# wychodzi zamaskowana (decyzja Maksa z 5.11.2026, ADR 0025). Kontrole C1 i C2 to te same wiersze bez kolizji.

STALE_ADDRESS = (2, PROBE_ADDRESS)
"""``AKCJE`` (B) z adresem: tata skopiował przesunięty wiersz dwie kolumny w prawo, zamiast go przenieść."""
UNDER_DEVICES = (DEVICES,)
"""Jedyne Hiperłącze wiersza pod ``URZĄDZENIA``, dwie kolumny na lewo od ``NUMER ZL.``."""
KNOWN_UNTIL = date(2027, 2, 5)
"""Termin przeglądu granic wariantu B: po nim przypadki z ``KNOWN`` znów padają."""
KNOWN = {
    name: "Granica wariantu B (zgoda Maksa 5.11.2026, ADR 0025): " + reason
    for names, reason in (
        (
            ("P3", "P4", "P6", "P7", "P8", "P9"),
            "wiersz, który nie jest pierwszy w bloku, a podpis przesunięcia kłamie albo go brak, wbrew faktowi domeny; "
            "u taty 84 z 84 podpisów zgodnych z położeniem odczytu i 0 kolizji",
        ),
        (("T3",), "pierwszy wiersz na miejscu, w którym naraz kłamią wszystkie trzy fakty confirmed_shift"),
    )
    for name in names
}
"""Znane przypadki: powód, termin i zgoda Maksa. Po terminie przypadek znów pada, a naprawiony pada od razu (strict)."""


def _colliding(index: int, probe: Order, other: int, value: str) -> tuple[Order, ...]:
    """Wklejenie z wierszem próbnym ``probe`` na miejscu ``index`` i wartością ``value`` pod ``URZĄDZENIA`` wiersza
    ``other``."""

    rows = list(_pasted(index, probe))
    rows[other] = replace(PASTED[other], cells=((DEVICES, value),))
    return tuple(rows)


COLLISIONS = {
    # sondy W1 z przeglądu #966 r2 dla pierwszego wiersza: podpis kłamie (P1, P2) albo go brak (P5)
    "P1a": Intermax(ordered=ORDERED, raw=_colliding(0, _probe(PASTED[0], A_DATE), 2, PROBE_ADDRESS), shifted=False),
    "P1b": Intermax(ordered=ORDERED, raw=_colliding(0, _probe(PASTED[0], A_DATE), 2, PROBE_ORANGE), shifted=False),
    "P1c": Intermax(
        ordered=ORDERED, raw=_colliding(0, _probe(PASTED[0], A_DATE, STALE_ADDRESS), 2, PROBE_ADDRESS), shifted=False
    ),
    "P2": Intermax(
        ordered=ORDERED, raw=_colliding(0, _probe(PASTED[0], links=UNDER_DEVICES), 2, PROBE_ADDRESS), shifted=False
    ),
    "P5": Intermax(ordered=ORDERED, raw=_colliding(0, _probe(PASTED[0], TEXT_DATE, links=()), 2, PROBE_ADDRESS)),
    # pierwszy wiersz na miejscu z dwoma z trzech faktów: brak daty w A, data pod DATA, Hiperłącze pod NUMER ZL. albo
    # drugie Hiperłącze obok tego pod URZĄDZENIA
    "T2_bez_daty_w_A": Intermax(
        ordered=ORDERED,
        raw=_colliding(0, _probe(PASTED[0], TEXT_DATE, links=UNDER_DEVICES), 2, PROBE_ADDRESS),
        shifted=False,
    ),
    "T2_z_data_pod_DATA": Intermax(
        ordered=ORDERED,
        raw=_colliding(0, _probe(PASTED[0], A_DATE, links=UNDER_DEVICES), 2, PROBE_ADDRESS),
        shifted=False,
    ),
    "T2_z_hiperlaczem_pod_NUMER_ZL": Intermax(
        ordered=ORDERED, raw=_colliding(0, _probe(PASTED[0], A_DATE, TEXT_DATE), 2, PROBE_ADDRESS), shifted=False
    ),
    "T2_z_dwoma_hiperlaczami": Intermax(
        ordered=ORDERED,
        raw=_colliding(0, _probe(PASTED[0], A_DATE, TEXT_DATE, links=(DEVICES, NUMBER)), 2, PROBE_ADDRESS),
        shifted=False,
    ),
    "C1": Intermax(ordered=ORDERED, raw=_pasted(0, _probe(PASTED[0], A_DATE)), shifted=False),
    "C2": Intermax(ordered=ORDERED, raw=_pasted(2, _probe(PASTED[2], TEXT_DATE, shifted=True, links=()))),
    # granice: środek bloku (sondy W1 P3, P4, P6–P9) i pierwszy wiersz na miejscu z trzema kłamiącymi faktami
    "P3": Intermax(ordered=ORDERED, raw=_colliding(1, _probe(PASTED[1], A_DATE), 3, PROBE_ADDRESS)),
    "P4": Intermax(ordered=ORDERED, raw=_colliding(1, _probe(PASTED[1], links=UNDER_DEVICES), 3, PROBE_ORANGE)),
    "P6": Intermax(
        ordered=ORDERED, raw=_colliding(2, _probe(PASTED[2], TEXT_DATE, shifted=True, links=()), 3, PROBE_ADDRESS)
    ),
    "P7": Intermax(
        ordered=ORDERED, raw=_colliding(2, _probe(PASTED[2], (3, ""), shifted=True, links=()), 3, PROBE_ORANGE)
    ),
    "P8": Intermax(
        ordered=ORDERED, raw=_colliding(2, _probe(PASTED[2], shifted=True, in_place_from=10), 3, PROBE_ORANGE)
    ),
    "P9": Intermax(
        ordered=ORDERED, raw=_colliding(2, _probe(PASTED[2], shifted=True, in_place_from=ADDRESS), 3, PROBE_ADDRESS)
    ),
    "T3": Intermax(
        ordered=ORDERED,
        raw=_colliding(0, _probe(PASTED[0], A_DATE, TEXT_DATE, links=UNDER_DEVICES), 2, PROBE_ADDRESS),
        shifted=False,
    ),
}


def _known(name: str) -> tuple[pytest.MarkDecorator, ...]:
    reason = KNOWN.get(name)
    if reason is None or datetime.now().astimezone().date() > KNOWN_UNTIL:
        return ()
    return (pytest.mark.xfail(strict=True, reason=reason),)


@pytest.mark.parametrize(
    "intermax", [pytest.param(intermax, id=name, marks=_known(name)) for name, intermax in COLLISIONS.items()]
)
def test_adres_i_numer_orange_pierwszego_wiersza_bloku_nie_wychodza_takze_z_tej_samej_wartosci_pod_urzadzenia_innego(
    tmp_path: Path, intermax: Intermax
) -> None:
    """Pierwszy wiersz bloku wklejenia, którego podpis przesunięcia kłamie albo go brak, z adresem albo numerem Orange
    także pod ``URZĄDZENIA`` innego wiersza: adres i numer Orange nie wychodzą do pliku Logów, do Skrzynki Zgłoszeń ani
    w Uwadze taty, bo bez trzech faktów przesunięcia pamięć zna oba położenia wszędzie."""

    centrum = ordering_centrum(tmp_path, intermax)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")

    centrum.run_to_end()
    note = centrum.client.post("/api/dad-notes/draft", json=NOTE).json()

    texts = [path.read_text(encoding="utf-8") for path in sorted((tmp_path / "logs" / "uruchomienia").glob("*"))]
    leaked = [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if any(value in text for text in [*texts, *_sent(centrum)])]
    assert leaked == []
    assert note["body"].splitlines()[0] == "Klient [adres], umowa [numer Orange]"


# --- Koszt reguły danych w zwykłych kolumnach (opcja 3, #913, #918) ----------------------------------------------------
# Wartość z wiersza z dwoma położeniami strażnik maskuje w jej komórce, pod ADRES i NUMER UMOWY, w wolnym tekście i w
# innych plikach, ale nie w zwykłej kolumnie innego wiersza tego samego pliku (ADR 0025). Tak samo ``URZĄDZENIA`` z
# aplikacji („Instalacja”) w każdym wierszu i ``NUMER ZL.`` wklejonych wierszy wychodzą bez maski, choć pamięć zna je
# jako możliwy adres albo numer Orange.

DEVICES_LETTER = "G"
"""``URZĄDZENIA`` w Kopii wejścia."""
NUMBER_LETTER = "I"
"""``NUMER ZL.`` w Kopii wejścia."""


def test_po_wierszu_z_dwoma_polozeniami_nastepne_uporzadkowanie_ma_urzadzenia_kazdego_wiersza_bez_maski(
    tmp_path: Path,
) -> None:
    """Repro 1 z #913: pierwszy wiersz kolejnego wklejenia stoi przesunięty, więc ma dwa położenia, a pamięć reguły
    danych zna jego ``URZĄDZENIA`` (w położeniu bez przesunięcia stoi pod ``ADRES``) jako możliwy adres. Tata stawia go na
    miejsce, a następne Uporządkowanie w tej samej pracy Centrum ma ``URZĄDZENIA`` każdego wklejonego wiersza w Kopii bez
    maski. To samo słowo w wolnym tekście (``CZYNNOŚCI ZREALIZOWANE``) dalej jest zamaskowane."""

    devices = PASTED[0].kind
    free_text = f"montaż {devices} zakończony"
    pasted = _pasted(4, replace(PASTED[4], cells=((DONE, free_text),)))
    stopped = _pasted(2, _probe(PASTED[2], shifted=True))
    centrum = ordering_centrum(tmp_path, Intermax(ordered=ORDERED, raw=(*stopped[:4], pasted[4])))
    assert centrum.run_to_end()["result"]["result"] != "OK"
    Intermax(ordered=ORDERED, raw=pasted).write(centrum.register)

    view = centrum.run_to_end()

    assert view["result"]["result"] == "OK", view["result"]["stops"]
    logs = centrum.run_logs()
    [repaired] = [record for record in logs if record["result"] == "OK"]
    [first] = [record for record in logs if record is not repaired]
    [sheet] = repaired["input_copy"][0]["sheets"]
    cells = {row["row"]: row["cells"] for row in sheet["rows"]}
    first_row, *rest = centrum.layout.raw_rows
    assert {row: cells[row][DEVICES_LETTER] for row in rest} == {row: devices for row in rest}
    assert DEVICES_LETTER not in cells[first_row], "URZĄDZENIA pierwszego wiersza wklejenia w drugim położeniu to ADRES"
    assert cells[rest[-1]]["M"] == "montaż [adres] zakończony"
    assert first["input_copy"][0]["sheets"][0]["uncertain_rows"] == [first_row, *rest]


def test_po_diagnozie_przygotowania_uporzadkowanie_ma_numer_zl_i_urzadzenia_wklejonych_wierszy_bez_maski(
    tmp_path: Path,
) -> None:
    """Koszt z #918: Diagnoza Przygotowania czyta cały Rejestr zleceń, także wklejenie z aplikacji na dole, a każdy
    wklejony wiersz ma w nim dwa położenia. ``NUMER ZL.`` wiersza na miejscu z jedynym Hiperłączem pod nim nie jest
    możliwym numerem Orange, a ``URZĄDZENIA`` przesuniętego pierwszego wiersza (drugie położenie) nie maskuje zwykłych
    kolumn innych wierszy, więc Uporządkowanie w tej samej pracy Centrum ma Kopię bez żadnej maski, z ``URZĄDZENIA`` i
    ``NUMER ZL.`` każdego wiersza na miejscu, a adres wklejonego wiersza, który tata cytuje w Uwadze po Diagnozie, jest
    zamaskowany."""

    periods = tmp_path / "okresy"
    periods.mkdir()
    centrum = ordering_centrum(tmp_path, Intermax(), periods_directory=periods)
    started = centrum.client.post("/api/runs", json={"process": "preparation", "period": PERIOD, "dry_run": True})
    assert started.status_code == 200, started.json()
    stopped = finished_view(centrum.client)
    diagnosis = centrum.client.post(f"/api/runs/{stopped['run']['id']}/diagnosis")
    assert diagnosis.status_code == 200, diagnosis.json()
    second = centrum.layout.raw[1]
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": f"Klient Ulica {second.number}"})

    view = centrum.run_to_end()

    assert note.json()["body"].splitlines()[0] == "Klient [adres]"
    assert view["result"]["result"] == "OK", view["result"]["stops"]
    [logs] = [record for record in centrum.run_logs() if record["process"] == "intermax"]
    [sheet] = logs["input_copy"][0]["sheets"]
    cells = {row["row"]: row["cells"] for row in sheet["rows"]}
    first_row, *rest = centrum.layout.raw_rows
    raw = centrum.layout.raw
    assert {row: (cells[row][DEVICES_LETTER], cells[row][NUMBER_LETTER]) for row in rest} == {
        row: (order.kind, f"ZL-{order.number}") for row, order in zip(rest, raw[1:], strict=True)
    }
    assert cells[first_row][NUMBER_LETTER] == f"ZL-{raw[0].number}"
    assert [value for row in cells.values() for value in row.values() if isinstance(value, str) and "[" in value] == []
