"""Wycena w efenix przez rdzeń Uruchomienia procesu na Atrapie efenix w prawdziwej przeglądarce (spec #741, #743, #746, #747).

Każdy test prowadzi ``run_process`` z opisem procesu ``efenix_process.PROCESS`` i oknem efenix na karcie Chromium, a
sprawdza to, co widać z zewnątrz: wynik, Komunikaty, liczby podsumowania, żądania, które dostała Atrapa efenix, jej
stan po przebiegu (ilości, data wykonania, załadowania Wyceny Emmetta, zmiany statusu) i Plik zbiorczy po przebiegu
(Znaczniki efenix czytane tą samą drogą co Przebieg rozliczeń, ``read_data_rows``, i części zip pliku). Przypisanie kolumn do pozycji
testy piszą literałami ze specyfikacji #741 (O→012, T→019, Z→010, AG→015). Wynik w kształcie karty Uruchomienia
sprawdza Skrypt dla maszyn (``tests/test_uruchom_proces.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from copy import copy
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus
import json
from pathlib import Path
import itertools
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import weakref
from typing import TypeVar, cast
from urllib.parse import urljoin, urlparse
import zipfile

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection

from playwright.sync_api import Browser, Error as PlaywrightError, Page, Request as PlaywrightRequest, Route
from playwright.sync_api import Response as PlaywrightResponse
import pytest

from rozliczenia import TOOL_ROOT, efenix_browser, efenix_process, efenix_trace
from rozliczenia.domain import ProgressPhase
from rozliczenia.efenix_mark import MARK_RGB
from rozliczenia.efenix_pace import KEEPALIVE_S, Pace
from rozliczenia.efenix_address import AddressPart
from rozliczenia.efenix_checks import ListedOrder, ListedRead
from rozliczenia.efenix_marking import UnsupportedShape, mark_ready
from rozliczenia.efenix_orders import CollectiveOrder
from rozliczenia.efenix_pricing import (
    BrowserFailure,
    Closed,
    Efenix,
    ElementCount,
    EmmettLoad,
    HttpStatus,
    LoggedOut,
    Login,
    LoginSign,
    Operation,
    OrderPricing,
    OtherShape,
    PagePart,
    PricingStopped,
    PricingSummary,
    Shape,
    UnexpectedPage,
    WindowCause,
)
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.engine import run_settlements
from rozliczenia.process_run import Finished, Outcome, Stop, run_process
from rozliczenia.progress import PhaseState, ProgressSnapshot, SavingStep
from rozliczenia.workbook_files import excel_lock_file, read_computed_rows, read_data_rows

from tests.fixtures.atrapa_efenix import (
    LIST_PAGE,
    LIST_SCRIPT,
    LOAD_EMMETT,
    ORDER_PAGE,
    ORDER_SCRIPT,
    PRICES,
    FILL_EMMETT,
    SAVE_QUANTITY,
    SEARCH,
    SET_DATE,
    AtrapaEfenix,
    AtrapaOrder,
    Changed,
    EmmettRefusal,
    Outage,
    ProposalFailure,
    amount_of,
    atrapa_efenix,
)
from tests.fixtures.efenix import DAY, Order, write_collective_file
from tests.fixtures.interlocutor import Tata
from tests.fixtures.przegladarka import chromium, page_of
from tests.fixtures.settlement import PERIOD, write_mapping, write_template
from tests.fixtures.workbooks import active_worksheet, rewrite_parts

# Żądania, które niczego w efenix nie zmieniają: lista zleceń, szukanie, strona zlecenia i skrypty obu stron.
READING = {("GET", LIST_PAGE), ("POST", SEARCH), ("GET", ORDER_PAGE), ("GET", LIST_SCRIPT), ("GET", ORDER_SCRIPT)}
Priced = Outcome[PricingSummary]
# Karty, w których biegło już Uruchomienie (``_run``).
_USED_TABS: weakref.WeakSet[Page] = weakref.WeakSet()
_T = TypeVar("_T")


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with chromium() as launched:
        yield launched


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """Karta pierwszego Uruchomienia testu; na końcu testu zamyka się każdy kontekst przeglądarki, także konteksty
    następnych Uruchomień (``_next_tab``)."""

    with page_of(browser) as opened:
        yield opened
    for context in browser.contexts:
        context.close()


def _price(tmp_path: Path, page: Page, url: str, orders: Sequence[Order], *, timeout_ms: int = 10_000) -> Priced:
    return _run(write_collective_file(tmp_path, orders), page, url, timeout_ms=timeout_ms)


def _run(
    source: Path,
    page: Page,
    url: str,
    *,
    timeout_ms: int = 10_000,
    meanwhile: Callable[[], None] = lambda: None,
    pace: Pace | None = None,
    clock: Callable[[], float] = time.perf_counter,
    window: Callable[[Efenix], Efenix] = lambda efenix: efenix,
    tata: Tata | None = None,
) -> Priced:
    """Uruchomienie Wyceny w efenix dla Pliku zbiorczego ``source``; ``meanwhile`` to to, co tata zrobił z plikiem, zanim
    proces skończył ostatnie zlecenie. Tempo ludzkie jest wyłączone, chyba że test poda ``pace``, a ``clock`` to zegar
    czasów etapów i śladu działań okna. ``window`` to okno efenix, które dostaje proces, zbudowane z okna przeglądarki.
    ``tata``: rozmówca, który widzi postęp; bez niego ``Tata()``.

    Karta ``page`` służy jednemu Uruchomieniu, jak przeglądarka okna taty (``efenix_browser.chrome``) i Skryptu dla maszyn
    (``efenix_browser.chromium``), która zamyka się z oknem, więc następne Uruchomienie dostaje nową kartę
    (``_next_tab``). Skrypt strony efenix zostawionej przez Zatrzymanie przeładowuje ją jeszcze po odmowie „Załaduj do
    zlecenia”, na którą okno nie czeka, a to przeładowanie w tej samej karcie przerywało otwarcie listy przez następne
    Uruchomienie (``EFENIX_NIEDOSTEPNY``, #932).

    Błąd okna efenix (np. ``UnexpectedPage``) trafia na stderr testu z treścią wyjątku Playwrighta, której Zatrzymanie w
    wyniku z założenia nie ma (ma tylko typ wyjątku), a porażka testu pokazuje stderr. Z samego Zatrzymania nie dało się
    ustalić przyczyny porażek #767 i #768 na Windows."""

    assert page not in _USED_TABS, "następne Uruchomienie w nowej karcie: _next_tab(page)"
    _USED_TABS.add(page)

    @contextmanager
    def open_efenix(_login: Login) -> Iterator[Efenix]:
        try:
            with efenix_browser.window(page, url, timeout_ms=timeout_ms) as efenix:
                yield window(efenix)
        except Exception as error:
            print("Błąd okna efenix:", "".join(traceback.format_exception(error)), sep="\n", file=sys.stderr)
            raise
        meanwhile()

    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(source, open_efenix, pace=pace, clock=clock),
        tata or Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=source.parent.parent / "metryki.jsonl",
    )


def _next_tab(page: Page) -> Page:
    """Karta następnego Uruchomienia: kontekst karty ``page`` poprzedniego zamyka się, jak przeglądarka okna, więc jej
    skrypt efenix nie wysyła już żądań do efenix w trakcie następnego Uruchomienia (testy porównują jego żądania), a nowa
    karta jest w nowym kontekście tej samej przeglądarki. Atrapa tych testów trzyma logowanie u siebie (bez
    ``cookie_session``), więc nowy kontekst bez ciasteczek widzi tę samą sesję efenix, jak trwały profil okna taty, który
    pamięta logowanie między Uruchomieniami.

    ``page`` to karta, w której biegło Uruchomienie, i jeszcze otwarta: zamknięcie innej karty zostawiało kartę
    przerwanego Uruchomienia otwartą, a jej przeładowanie po „Załaduj do zlecenia” trafiało do Atrapy w trakcie
    ponownego Uruchomienia (#892).

    Zamyka się kontekst, nie sama karta, tak jak okno taty zamyka przeglądarkę (``efenix_browser.chrome``):
    ``page.close()`` wysłane, gdy skrypt strony zaczyna przeładowanie po odmowie „Załaduj do zlecenia”, kończy się
    dopiero z zamknięciem kontekstu, więc test wisiał do limitu pytest (#1003)."""

    assert page in _USED_TABS and not page.is_closed(), "_next_tab dostaje kartę ostatniego Uruchomienia, jeszcze otwartą"
    browser = page.context.browser
    assert browser is not None
    page.context.close()
    return browser.new_context().new_page()


def _figures(outcome: Priced) -> dict[str, int]:
    """Liczby podsumowania: zlecenia w zakresie, gotowe, rozliczone, błędy, ostrzeżenia Emmetta i pominięte."""

    assert isinstance(outcome.ending, Finished), _ending(outcome)
    assert outcome.view is not None
    summary = outcome.view
    return {
        "zakres": len(summary.results),
        "gotowe": summary.ready_count,
        "rozliczone": summary.settled_count,
        "błędy": summary.error_count,
        "ostrzeżenia": summary.warning_count,
        "ze zdjęciami": summary.with_photos,
        "usterki": summary.defects,
    }


def _ending(outcome: Priced) -> str:
    """Zakończenie przebiegu w komunikacie porażki: przy Zatrzymaniu jego kod i „Gdzie” z częścią strony efenix, które
    pełny zapis Zatrzymania w porażce testu ucina (#768)."""

    if isinstance(outcome.ending, Stop):
        return f"Zatrzymanie {outcome.ending.message.code} | {outcome.ending.message.where}"
    return repr(outcome.ending)


def _errors(outcome: Priced) -> list[tuple[str, str]]:
    """Kod i wiersz Pliku zbiorczego każdego błędu zlecenia i ostrzeżenia Emmetta."""

    assert outcome.view is not None
    return [(warning.code, warning.where.rpartition(", ")[2]) for warning in outcome.view.warnings]


def _what(outcome: Priced) -> list[str]:
    assert outcome.view is not None
    return [warning.what for warning in outcome.view.warnings]


def _pricing(atrapa: AtrapaEfenix) -> dict[str, tuple[dict[str, int], date | None, int]]:
    """Stan wyceny każdego zlecenia Atrapy: ilości, data wykonania i liczba załadowań Wyceny Emmetta."""

    orders, _logged_in = atrapa.state()
    return {order.number: (order.quantities, order.execution_date, order.emmett_loads) for order in orders}


def _stop(outcome: Priced) -> str:
    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert outcome.ending.kind == "stop"
    return outcome.ending.message.code


def _kept(outcome: Priced) -> bool:
    """Komunikat Zatrzymania mówi, że wycena zleceń sprzed niego została w efenix (``False``: że nic się nie zmieniło)."""

    assert isinstance(outcome.ending, Stop), outcome.ending
    what = outcome.ending.message.what
    kept, unchanged = "Wycena zleceń sprzed zatrzymania została w efenix." in what, "W efenix nic się nie zmieniło." in what
    assert kept != unchanged, what
    return kept


def _figures_of(
    orders: int, ready: int, warnings: int = 0, photos: int = 0, defects: int = 0, settled: int = 0
) -> dict[str, int]:
    return {
        "zakres": orders,
        "gotowe": ready,
        "rozliczone": settled,
        "błędy": orders - ready - warnings - settled,
        "ostrzeżenia": warnings,
        "ze zdjęciami": photos,
        "usterki": defects,
    }


def _au(quantities: dict[str, int]) -> float:
    """``Kwota`` (AU) zlecenia z ilościami ``quantities`` (kod pozycji → ilość) w cenach Atrapy."""

    return float(amount_of(quantities))


def test_zlecenie_z_wycena_zgodna_z_plikiem_jest_gotowe_a_efenix_dostaje_tylko_szukanie_i_otwarcie_zlecenia(
    tmp_path: Path, page: Page
) -> None:
    """Wycena już jest, z datą wykonania, a każda ilość i kwota zgadzają się z plikiem: proces niczego nie zmienia."""

    orders = [
        Order("#5001", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), quantities={"012": 1, "019": 2}),
        Order("#5002", cells={"AG": 3}, amount=_au({"015": 3}), quantities={"015": 3}, emmett={"015": 1}),
        Order("5003", cells={"Z": 1}, amount=_au({"010": 1}), quantities={"010": 1}),
    ]
    with atrapa_efenix([orders[0].in_efenix("901"), orders[1].in_efenix("902"), orders[2].in_efenix("903")]) as atrapa:
        before = atrapa.state()
        outcome = _price(tmp_path, page, atrapa.url, orders)
        after = atrapa.state()
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(3, 3), [])
    assert after == before
    assert set(requested) <= READING
    assert requested.count(("GET", ORDER_PAGE)) == 3


# Zlecenia z run 4.11.2026 (okres 20_26_10), które zostały tacie, w kształcie z Logów: sama Wycena Emmetta z S (016) o 1
# mniejszym niż plik i bez Y (009) i Z (010), które Emmett zostawia puste, oraz wycena zaczęta wcześniej bez Y i Z
# (wiersze 284, 378, 380). Plik ma ilość w O (012), S (016), Y (009) i Z (010).
_RUN_4_11_CELLS = {"O": 1, "S": 3, "Y": 2, "Z": 1}
_RUN_4_11_FILE = {"012": 1, "016": 3, "009": 2, "010": 1}


@pytest.mark.parametrize(
    ("in_efenix", "entered"),
    [
        pytest.param({"012": 1, "016": 2}, {"016": 3, "009": 2, "010": 1}, id="sama-wycena-emmetta-z-S-o-1-mniejszym-bez-Y-i-Z"),
        pytest.param({"012": 1, "016": 3}, {"009": 2, "010": 1}, id="niepełna-wycena-bez-Y-i-Z"),
        pytest.param({"012": 1, "016": 1, "009": 1}, {"016": 3, "009": 2, "010": 1}, id="mniej-w-kilku-pozycjach"),
    ],
)
def test_wycena_ktora_juz_jest_z_mniejsza_iloscia_niz_plik_proces_dokancza_iloscia_z_pliku_bez_wyceny_emmetta(
    tmp_path: Path, page: Page, in_efenix: dict[str, int], entered: dict[str, int]
) -> None:
    """Wycena już jest (zaczęta przez wcześniejszy run, przez tatę albo sama Wycena Emmetta), a w części pozycji efenix ma
    mniej niż plik: proces wpisuje w nich ilość z pliku (ADR 0026), nie ładuje Wyceny Emmetta, która wyczyściłaby wycenę,
    i nie zmienia daty wykonania, którą zlecenie już ma. Zlecenie ma potem ilości pliku i kwotę równą AU, więc jest gotowe
    i ma Znacznik efenix."""

    order = Order("#5101", cells=_RUN_4_11_CELLS, amount=_au(_RUN_4_11_FILE), quantities=in_efenix, emmett={"012": 1, "016": 2})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (pricing, _marked(source)) == ({"5101": (_RUN_4_11_FILE, DAY, 0)}, [18])
    assert {("POST", FILL_EMMETT), ("POST", LOAD_EMMETT), ("POST", SET_DATE)} & set(requested) == set()
    assert requested.count(("POST", SAVE_QUANTITY)) == len(entered)


@pytest.mark.parametrize(
    ("in_efenix", "entered"),
    [
        pytest.param({"012": 1, "016": 1, "009": 1}, 3, id="mniej-niż-plik"),
        pytest.param(_RUN_4_11_FILE, 0, id="zgodna-z-plikiem"),
    ],
)
def test_wycena_ktora_juz_jest_bez_daty_wykonania_dostaje_date_z_data_a_potem_ilosci_z_pliku_bez_wyceny_emmetta(
    tmp_path: Path, page: Page, in_efenix: dict[str, int], entered: int
) -> None:
    """Decyzja Maksa z 5.11.2026: zlecenie z wyceną, która już jest, ale bez daty wykonania, dostaje datę z ``DATA`` tak
    samo jak zlecenie bez wyceny, zanim proces dokończy je do pliku, żeby gotowe zlecenie ze Znacznikiem efenix nie
    zostało w efenix bez daty. Wyceny Emmetta proces do niego nie ładuje, bo wyczyściłaby wycenę."""

    executed = date(2026, 9, 3)
    order = Order("#5103", day=executed, cells=_RUN_4_11_CELLS, amount=_au(_RUN_4_11_FILE), quantities=in_efenix, emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=None)]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (pricing, _marked(source)) == ({"5103": (_RUN_4_11_FILE, executed, 0)}, [18])
    assert {("POST", FILL_EMMETT), ("POST", LOAD_EMMETT)} & set(requested) == set()
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", SAVE_QUANTITY))) == (1, entered)


@pytest.mark.parametrize(
    ("day", "refuse_dates", "error", "set_date"),
    [
        pytest.param(date(2026, 10, 13), False, "EFENIX_DATA_POZA_ZAKRESEM", 0, id="dzień-poza-kalendarzem"),
        pytest.param(DAY, True, "EFENIX_DATA_NIEZAPISANA", 1, id="dzień-niezapisany"),
    ],
)
def test_data_wykonania_odrzucona_przy_wycenie_ktora_juz_jest_to_blad_bez_zmiany_ilosci(
    tmp_path: Path, page: Page, day: date, refuse_dates: bool, error: str, set_date: int
) -> None:
    """Zlecenie z wyceną mniejszą niż plik i bez daty wykonania: dzień, którego kalendarz efenix nie przyjął albo którego
    efenix nie zapisał, to błąd zlecenia jak przy zleceniu bez wyceny, a ilości w efenix zostają bez zmian."""

    in_efenix = {"012": 1, "016": 1}
    order = Order("#5104", day=day, cells=_RUN_4_11_CELLS, amount=_au(_RUN_4_11_FILE), quantities=in_efenix)
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=None)], today=date(2026, 10, 12), refuse_dates=refuse_dates) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _errors(outcome), pricing) == ("WYMAGA_SPRAWDZENIA", [(error, "wiersz 18")], {"5104": (in_efenix, None, 0)})
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", LOAD_EMMETT)), requested.count(("POST", SAVE_QUANTITY))) == (set_date, 0, 0)


@pytest.mark.parametrize(
    ("in_efenix", "emmett", "excess", "after"),
    [
        pytest.param({"012": 2}, {}, "pozycja INDEKS_012 (kolumna O): efenix 2, plik 1", {"012": 2, "019": 2}, id="wycena-ktora-juz-jest"),
        pytest.param(
            {"012": 1, "013": 1},
            {},
            "pozycja INDEKS_013 (kolumna P): efenix 1, plik 0",
            {"012": 1, "013": 1, "019": 2},
            id="wycena-ktora-juz-jest-0-w-pliku",
        ),
        pytest.param(
            {"012": 1, "005": 1},
            {},
            "pozycja INDEKS_005 (bez kolumny w Pliku zbiorczym): efenix 1, plik 0",
            {"005": 1, "012": 1, "019": 2},
            id="pozycja-bez-kolumny",
        ),
        pytest.param({}, {"012": 2}, "pozycja INDEKS_012 (kolumna O): efenix 2, plik 1", {"012": 2, "019": 2}, id="wycena-emmetta"),
        pytest.param(
            {},
            {"012": 1, "020": 1},
            "pozycja INDEKS_020 (bez kolumny w Pliku zbiorczym): efenix 1, plik 0",
            {"012": 1, "020": 1, "019": 2},
            id="wycena-emmetta-bez-kolumny",
        ),
    ],
)
def test_pozycja_z_wieksza_iloscia_w_efenix_niz_w_pliku_zostaje_a_reszta_zlecenia_jest_dopisana_z_ostrzezeniem_emmetta(
    tmp_path: Path, page: Page, in_efenix: dict[str, int], emmett: dict[str, int], excess: str, after: dict[str, int]
) -> None:
    """Pozycja, w której efenix (wycena, która już jest, albo Wycena Emmetta) ma więcej niż plik, także przy 0 w pliku
    albo bez kolumny, zostaje bez zmian: proces nigdy nie obniża ani nie czyści ilości w efenix (ADR 0026). Pozostałe
    pozycje dostają ilość z pliku, a zlecenie to Ostrzeżenie Emmetta z pozycją, kolumną i obiema ilościami, bez
    Znacznika efenix i bez drugiego błędu o kwocie."""

    order = Order("#5401", cells={"O": 1, "P": 0, "T": 2}, amount=_au({"012": 1, "019": 2}), quantities=in_efenix, emmett=emmett)
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(1, 0, warnings=1),
        [("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 18")],
    )
    assert _what(outcome) == [
        f"efenix ma więcej niż Plik zbiorczy: {excess}. Narzędzie tych ilości nie zmieniło, a pozostałe ilości z pliku wpisało."
    ]
    assert (pricing, _marked(source)) == ({"5401": (after, DAY, int(not in_efenix))}, [])


def test_wycena_ktora_juz_jest_z_iloscmi_pliku_a_kwota_inna_niz_au_to_blad_z_obiema_kwotami_bez_zmian(tmp_path: Path, page: Page) -> None:
    order = Order("#5102", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}) + 1, quantities={"012": 1, "019": 2})
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        before = atrapa.state()
        outcome = _price(tmp_path, page, atrapa.url, [order])
        after = atrapa.state()
        requested = atrapa.requested()

    assert (outcome.result, _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", [("EFENIX_INNA_KWOTA", "wiersz 18")])
    [what] = _what(outcome)
    efenix_amount = amount_of({"012": 1, "019": 2})
    assert f"kwota w efenix to {efenix_amount:.2f} zł, a Kwota (AU) {efenix_amount + 1:.2f} zł".replace(".", ",") in what
    assert (after, set(requested) <= READING) == (before, True)


def test_pusta_wycena_dostaje_date_z_data_wycene_emmetta_i_ilosci_z_pliku_w_pustych_pozycjach_a_kwota_rowna_au_daje_gotowe(
    tmp_path: Path, page: Page
) -> None:
    """Emmett wpisał O (012) zgodnie z plikiem; proces dopisuje T (019) i AG (015), a Z z 0 w pliku zostaje puste.

    Data wykonania jest ustawiana z ``DATA`` tylko w zleceniu, które jej nie miało.
    """

    filled = {"012": 1, "019": 2, "015": 1}
    orders = [
        Order("#5201", day=date(2026, 9, 3), cells={"O": 1, "T": 2, "AG": 1, "Z": 0}, amount=_au(filled), emmett={"012": 1}),
        # AU z ułamkiem binarnym, jaki zostawia suma Excela: równa kwocie efenix co do grosza.
        Order("#5202", cells={"O": 2}, amount=_au({"012": 2}) + 1e-9, emmett={"012": 2}),
    ]
    with atrapa_efenix([orders[0].in_efenix("901"), replace(orders[1].in_efenix("902"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        pricing = _pricing(atrapa)
        requested = atrapa.requested()
        changes = atrapa.status_changes()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 2), [])
    assert pricing == {"5201": (filled, date(2026, 9, 3), 1), "5202": ({"012": 2}, DAY, 1)}
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", SAVE_QUANTITY)), changes) == (1, 2, 0)


def test_kwota_efenix_inna_niz_au_po_dopisaniu_ilosci_to_blad_z_obiema_kwotami(tmp_path: Path, page: Page) -> None:
    """Kwoty różnią się o 40 groszy: równość jest co do grosza, nie co do złotówki."""

    order = Order("#5301", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}) + 0.4, emmett={"012": 1})
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [("EFENIX_INNA_KWOTA", "wiersz 18")])
    assert pricing == {"5301": ({"012": 1, "019": 2}, DAY, 1)}
    [what] = _what(outcome)
    efenix_amount, au = amount_of({"012": 1, "019": 2}), amount_of({"012": 1, "019": 2}) + Decimal("0.40")
    assert f"kwota w efenix to {efenix_amount:.2f} zł, a Kwota (AU) {au:.2f} zł".replace(".", ",") in what


@pytest.mark.parametrize(
    ("day", "result", "errors", "pricing"),
    [
        pytest.param(date(2026, 9, 1), "OK", [], ({"012": 1}, date(2026, 9, 1), 1), id="pierwszy-dzień-poprzedniego-miesiąca"),
        pytest.param(date(2026, 10, 12), "OK", [], ({"012": 1}, date(2026, 10, 12), 1), id="dziś"),
        pytest.param(
            date(2026, 8, 31), "WYMAGA_SPRAWDZENIA", [("EFENIX_DATA_POZA_ZAKRESEM", "wiersz 18")], ({}, None, 0), id="przed-poprzednim-miesiącem"
        ),
        pytest.param(date(2026, 10, 13), "WYMAGA_SPRAWDZENIA", [("EFENIX_DATA_POZA_ZAKRESEM", "wiersz 18")], ({}, None, 0), id="jutro"),
    ],
)
def test_dzien_z_data_spoza_zakresu_kalendarza_efenix_to_blad_bez_zapisu_daty_bez_emmetta_i_bez_ilosci(
    tmp_path: Path,
    page: Page,
    day: date,
    result: str,
    errors: list[tuple[str, str]],
    pricing: tuple[dict[str, int], date | None, int],
) -> None:
    """Kalendarz Atrapy ma za dziś 12 października 2026, więc efenix przyjmuje daty wykonania od 1 września do 12 października.

    Okna „Wybierz datę wykonania” z dniem, którego kalendarz nie przyjął, okno efenix nie zostawia otwartego w efenix taty:
    zamyka je bez „Potwierdź”."""

    order = Order("#5601", day=day, cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("901")], today=date(2026, 10, 12)) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        after = _pricing(atrapa)
        requested = atrapa.requested()
        dialog_hidden = page.locator("#dialog_select_date").is_hidden()

    assert (outcome.result, _errors(outcome), after, dialog_hidden) == (result, errors, {"5601": pricing}, True)
    assert requested.count(("POST", SET_DATE)) == (1 if result == "OK" else 0)


@pytest.mark.parametrize(
    ("days", "result", "errors", "pricing"),
    [
        pytest.param(-3, "OK", [], ({"012": 1}, 1), id="3-dni-przed"),
        pytest.param(2, "OK", [], ({"012": 1}, 1), id="2-dni-po"),
        pytest.param(3, "OK", [], ({"012": 1}, 1), id="3-dni-po"),
        pytest.param(-4, "WYMAGA_SPRAWDZENIA", [("EFENIX_INNA_DATA", "wiersz 18")], ({}, 0), id="4-dni-przed"),
        pytest.param(4, "WYMAGA_SPRAWDZENIA", [("EFENIX_INNA_DATA", "wiersz 18")], ({}, 0), id="4-dni-po"),
    ],
)
def test_data_wykonania_rozna_od_data_najwyzej_o_3_dni_zostaje_w_efenix_a_wieksza_roznica_to_inna_data(
    tmp_path: Path,
    page: Page,
    days: int,
    result: str,
    errors: list[tuple[str, str]],
    pricing: tuple[dict[str, int], int],
) -> None:
    """Tata po runie z 4.11.2026 (#961): data wykonania w efenix różna od dnia z ``DATA`` najwyżej o 3 dni w którąkolwiek
    stronę jest prawidłowa, więc proces wycenia zlecenie dalej i daty nie zmienia."""

    executed = DAY + timedelta(days=days)
    order = Order("#5651", cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 1})
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=executed)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        after = _pricing(atrapa)
        requested = atrapa.requested()

    quantities, emmett_loads = pricing
    assert (outcome.result, _errors(outcome), after) == (result, errors, {"5651": (quantities, executed, emmett_loads)})
    assert requested.count(("POST", SET_DATE)) == 0


def test_data_wykonania_ktorej_efenix_nie_zapisal_po_potwierdz_to_blad_bez_emmetta_i_bez_ilosci(tmp_path: Path, page: Page) -> None:
    """Skrypt strony wpisuje dzień do ``#data_install`` po każdej odpowiedzi, także gdy serwer daty nie zapisał."""

    order = Order("#5701", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("901")], refuse_dates=True) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _errors(outcome), pricing) == ("WYMAGA_SPRAWDZENIA", [("EFENIX_DATA_NIEZAPISANA", "wiersz 18")], {"5701": ({}, None, 0)})
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", LOAD_EMMETT)), requested.count(("POST", SAVE_QUANTITY))) == (1, 0, 0)


def test_ilosc_emmetta_mniejsza_niz_w_pliku_proces_zastepuje_iloscia_z_pliku_a_zlecenie_jest_gotowe(tmp_path: Path, page: Page) -> None:
    """Emmett liczy w S (016) tylko dekodery, a plik każde urządzenie (#960): Emmett wpisał S 1 i O 1, a plik ma S 3, O 1 i
    T 2. Proces wpisuje S z pliku w miejsce ilości Emmetta i dopisuje T, więc kwota końcowa jest równa AU, a zlecenie
    jest gotowe ze Znacznikiem efenix."""

    filled = {"012": 1, "016": 3, "019": 2}
    order = Order("#5402", cells={"O": 1, "S": 3, "T": 2}, amount=_au(filled), emmett={"012": 1, "016": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (pricing, _marked(source)) == ({"5402": (filled, DAY, 1)}, [18])
    assert (requested.count(("POST", LOAD_EMMETT)), requested.count(("POST", SAVE_QUANTITY))) == (1, 2)


@pytest.mark.parametrize(
    ("cells", "error"),
    [
        pytest.param({"O": 1, "N": 1}, "EFENIX_KOLUMNA_BEZ_POZYCJI", id="kolumna-N-bez-pary"),
        pytest.param({"AR": 2}, "EFENIX_KOLUMNA_BEZ_POZYCJI", id="kolumna-AR-bez-pary"),
        pytest.param({"O": "tak"}, "EFENIX_ILOSC_NIECALKOWITA", id="ilość-słowem"),
        pytest.param({"O": -1}, "EFENIX_ILOSC_NIECALKOWITA", id="ilość-ujemna"),
    ],
)
def test_ilosc_ktorej_nie_da_sie_przepisac_do_efenix_to_blad_zlecenia_zanim_proces_go_szuka(
    tmp_path: Path, page: Page, cells: dict[str, int | str], error: str
) -> None:
    orders = [Order("#5501", cells=cells, amount=100.0), Order("#5502")]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched = atrapa.searched()

    assert (_figures(outcome), _errors(outcome), searched) == (_figures_of(2, 1), [(error, "wiersz 18")], ["5502"])


# Strona zlecenia efenix bez części „Montaż urządzeń” (#819): z pozycji przypisania kolumn ma tylko 026, a ma 029, 009 i
# 010 oraz pozycje bez kolumny. Kody z przypisania kolumn ze specyfikacji #741.
WITHOUT_ASSEMBLY = frozenset({"012", "013", "014", "015", "016", "017", "018", "019", "020", "021", "022", "023", "024", "025", "027", "028"})


def test_strona_zlecenia_bez_pozycji_z_zerem_w_pliku_dostaje_wycene_emmetta_i_ilosci_pliku_a_nastepne_zlecenie_jest_wyceniane(
    tmp_path: Path, page: Page
) -> None:
    """Plik ma ilości tylko w V (029), Y (009) i Z (010), a w O (012) 0: brak pozycji 012 i reszty Montażu urządzeń na
    stronie nie przeszkadza, bo te pozycje i tak zostałyby w efenix puste."""

    filled = {"029": 1, "009": 2, "010": 1}
    orders = [
        Order("#5601", day=date(2026, 9, 3), cells={"V": 1, "Y": 2, "Z": 1, "O": 0}, amount=_au(filled), emmett={"029": 1}),
        Order("#5602", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    in_efenix = [replace(orders[0].in_efenix("901"), without=WITHOUT_ASSEMBLY), orders[1].in_efenix("902")]
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 2), [])
    assert pricing == {"5601": (filled, date(2026, 9, 3), 1), "5602": ({"012": 1}, date(2026, 9, 4), 1)}


@pytest.mark.parametrize(
    ("after_date", "after_emmett", "pricing", "done"),
    [
        pytest.param(False, False, ({}, None, 0), " Zlecenie zostało w efenix bez zmian.", id="po-otwarciu"),
        pytest.param(
            True,
            False,
            ({}, date(2026, 9, 3), 0),
            " Narzędzie ustawiło już datę wykonania z DATA, ale nie załadowało Wyceny Emmetta i nie wpisało ilości.",
            id="po-dacie-wykonania",
        ),
        pytest.param(
            False,
            True,
            ({"029": 1}, date(2026, 9, 3), 1),
            " Wycena Emmetta jest już załadowana, a narzędzie niczego do niej nie dopisało.",
            id="po-wycenie-emmetta",
        ),
    ],
)
def test_strona_zlecenia_bez_pozycji_z_iloscia_w_pliku_to_blad_zlecenia_z_pozycja_i_kolumna_a_nastepne_zlecenie_jest_wyceniane(
    tmp_path: Path,
    page: Page,
    after_date: bool,
    after_emmett: bool,
    pricing: tuple[dict[str, int], date | None, int],
    done: str,
) -> None:
    """Plik ma ilość w O (012) i T (019), a strona zlecenia, przy otwarciu albo dopiero przy kolejnym odczycie, nie ma
    pozycji Montażu urządzeń: proces nie wpisuje żadnej ilości, a Komunikat mówi, co zmienił już w efenix."""

    orders = [
        Order("#5701", day=date(2026, 9, 3), cells={"O": 1, "T": 2, "V": 1}, amount=_au({"012": 1, "019": 2, "029": 1}), emmett={"029": 1}),
        Order("#5702", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    in_efenix = [replace(orders[0].in_efenix("901"), without=WITHOUT_ASSEMBLY, after_date=after_date, after_emmett=after_emmett), orders[1].in_efenix("902")]
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        after = _pricing(atrapa)
        changes = atrapa.status_changes()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(2, 1),
        [("EFENIX_BRAK_POZYCJI", "wiersz 18")],
    )
    assert _what(outcome) == [
        "Strona zlecenia w efenix nie ma pozycji, w których Plik zbiorczy ma ilość: pozycja INDEKS_012 (kolumna O),"
        f" pozycja INDEKS_019 (kolumna T).{done}"
    ]
    assert (after, changes) == ({"5701": pricing, "5702": ({"012": 1}, date(2026, 9, 4), 1)}, 0)


@pytest.mark.parametrize(
    ("file", "saved"),
    [
        pytest.param(1, 0, id="zgodna"),
        pytest.param(2, 1, id="mniejsza-w-efenix"),
    ],
)
def test_wycena_ktora_juz_jest_na_stronie_bez_pozycji_z_zerem_w_pliku_jest_dokonczona_do_pliku(
    tmp_path: Path, page: Page, file: int, saved: int
) -> None:
    order = Order("#5801", cells={"V": file}, amount=_au({"029": file}), quantities={"029": 1})
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY, without=WITHOUT_ASSEMBLY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (_figures(outcome), _errors(outcome)) == (_figures_of(1, 1), [])
    assert (pricing, requested.count(("POST", SAVE_QUANTITY))) == ({"5801": ({"029": file}, DAY, 0)}, saved)


def test_szukanie_ktore_lista_efenix_wysyla_sama_po_powrocie_ze_strony_zlecenia_nie_zmienia_wynikow_szukania(
    tmp_path: Path, page: Page
) -> None:
    """Efenix odpowiada wolno, więc szukanie poprzedniego numeru, które lista wysyła sama po wczytaniu, trwa jeszcze,
    gdy okno szuka następnego zlecenia, i jego odpowiedź przychodzi pierwsza."""

    orders = [Order("#5101"), Order("#5102"), Order("#5103")]
    with atrapa_efenix([order.in_efenix(f"91{index}") for index, order in enumerate(orders)], answer_delay_s=0.3) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched, by_list = atrapa.searched(), atrapa.searched_by_list()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(3, 3), [])
    assert (searched, by_list) == (["5101", "5102", "5103"], ["5101", "5102"])


def test_zlecenia_ze_zdjeciami_i_usterki_sa_pominiete_i_policzone_a_wiersz_z_samymi_zerami_jest_w_zakresie(
    tmp_path: Path, page: Page
) -> None:
    photo_columns = ["AB", "AC", "AD", "AE", "AF", "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AS"]
    orders = [
        *(Order(f"#60{index:02}", cells={column: 1}) for index, column in enumerate(photo_columns)),
        Order("#6101", cells={"AJ": "tak"}),
        Order("#6201", cells={"AI": 1}),
        Order("#6301", cells=dict.fromkeys([*photo_columns, "AI"], 0)),
        Order("#6302", cells=dict.fromkeys([*photo_columns, "AI"], "0")),
        Order("#6401", cells={"H": None}),
    ]
    with atrapa_efenix([order.in_efenix(f"9{index:02}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched = atrapa.searched()

    assert (outcome.result, _figures(outcome), searched) == ("OK", _figures_of(2, 2, photos=14, defects=1), ["6301", "6302"])


def test_zlecenia_ida_po_wykonawcach_alfabetycznie_a_u_kazdego_od_najstarszej_daty(tmp_path: Path, page: Page) -> None:
    orders = [
        Order("#7001", worker="zenon.testowy", day=date(2026, 9, 8)),
        Order("#7002", worker="adrian.testowy", day=date(2026, 9, 12)),
        Order("#7003", worker="Bogdan.testowy", day=date(2026, 9, 10)),
        Order("#7004", worker="adrian.testowy", day=date(2026, 9, 9)),
        Order("#7005", worker="zenon.testowy", day=date(2026, 9, 7)),
    ]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched = atrapa.searched()

    assert (outcome.result, searched) == ("OK", ["7004", "7002", "7003", "7005", "7001"])


def test_kazda_niezgodnosc_z_efenix_to_blad_zlecenia_z_powodem_a_proces_idzie_dalej(tmp_path: Path, page: Page) -> None:
    orders = [
        Order(""),  # wiersz 18: bez NUMER ZL.
        Order("#8002", day=None),  # 19: bez daty w DATA
        Order("#8003"),  # 20: efenix go nie zna, a szukanie znajduje zlecenie z dłuższym numerem
        Order("#8010"),  # 21: efenix go nie zna i szukanie odpowiada „Nie znaleziono pasujących wyników”
        Order("#8004"),  # 22: dwa zlecenia o tym numerze
        Order("#8005"),  # 23: inny status
        Order("#8006"),  # 24: inny realizator
        Order("#8007"),  # 25: inny adres
        Order("#8008"),  # 26: data wykonania 4 dni po DATA
        Order("#8009", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # 27: gotowe, po wszystkich błędach
    ]
    efenix = [
        orders[1].in_efenix("902"),
        replace(orders[2].in_efenix("903"), number="80031"),
        orders[4].in_efenix("904"),
        orders[4].in_efenix("914"),
        replace(orders[5].in_efenix("905"), status="Do akceptacji"),
        replace(orders[6].in_efenix("906"), realizator="zenon.testowy"),
        replace(orders[7].in_efenix("907"), address="Miasto-Dzielnica ul.Testowa 14 Lokal 3"),
        replace(orders[8].in_efenix("908"), execution_date=date(2026, 9, 13)),
        replace(orders[9].in_efenix("909"), execution_date=DAY),
    ]
    with atrapa_efenix(efenix) as atrapa:
        before = atrapa.state()
        outcome = _price(tmp_path, page, atrapa.url, orders)
        after = atrapa.state()

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(10, 1))
    # Wiersz bez daty idzie na koniec swojego Wykonawcy, więc błędy są w kolejności wierszy dopiero po sortowaniu.
    assert sorted(_errors(outcome), key=lambda error: error[1]) == [
        ("EFENIX_BRAK_NUMERU", "wiersz 18"),
        ("EFENIX_BRAK_DATY", "wiersz 19"),
        ("EFENIX_NIEZNANY_NUMER", "wiersz 20"),
        ("EFENIX_NIEZNANY_NUMER", "wiersz 21"),
        ("EFENIX_KILKA_ZLECEN", "wiersz 22"),
        ("EFENIX_INNY_STATUS", "wiersz 23"),
        ("EFENIX_INNY_REALIZATOR", "wiersz 24"),
        ("EFENIX_INNY_ADRES", "wiersz 25"),
        ("EFENIX_INNA_DATA", "wiersz 26"),
    ]
    assert after == before


def test_zlecenie_rozliczone_w_efenix_nie_jest_bledem_a_proces_go_nie_otwiera_i_nie_stawia_mu_znacznika(
    tmp_path: Path, page: Page
) -> None:
    """Status „Rozliczone” to Zlecenie rozliczone (#821): bez błędu, bez otwarcia strony zlecenia i bez Znacznika efenix,
    także gdy wycena w efenix jest inna niż w pliku. Wynik to OK, gdy żadne zlecenie nie zostało tacie."""

    orders = [
        Order("#8101", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 2}),  # wiersz 18: rozliczone
        Order("#8102", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # 19: gotowe
    ]
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix(
        [replace(orders[0].in_efenix("901"), status=" rozliczone ", execution_date=DAY), orders[1].in_efenix("902")]
    ) as atrapa:
        before = atrapa.state()
        outcome = _run(source, page, atrapa.url)
        after = atrapa.state()
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 1, settled=1), [])
    assert (after, set(requested) <= READING, requested.count(("GET", ORDER_PAGE))) == (before, True, 1)
    assert _marked(source) == [19]


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        pytest.param(
            lambda order: replace(order, status="Rozliczone", realizator="zenon.testowy"),
            "EFENIX_INNY_REALIZATOR",
            id="inny-realizator",
        ),
        pytest.param(
            lambda order: replace(order, status="Rozliczone", address="Miasto-Dzielnica ul.Testowa 14 Lokal 3"),
            "EFENIX_INNY_ADRES",
            id="inny-adres",
        ),
        pytest.param(
            lambda order: replace(order, status="Rozliczone częściowo"), "EFENIX_INNY_STATUS", id="status-dłuższy-niż-rozliczone"
        ),
    ],
)
def test_zlecenie_rozliczone_innego_wykonawcy_albo_adresu_to_blad_zlecenia(
    tmp_path: Path, page: Page, changed: Callable[[AtrapaOrder], AtrapaOrder], code: str
) -> None:
    """``NUMER ZL.``, pod którym efenix ma rozliczone zlecenie innego realizatora albo pod innym adresem, wskazuje inne
    zlecenie niż wiersz pliku, więc zostaje błędem jak przy statusie „Do wyceny”; status, który tylko zaczyna się od
    „Rozliczone”, to inny status."""

    order = Order("#8201")
    with atrapa_efenix([changed(order.in_efenix("901"))]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [(code, "wiersz 18")])


@pytest.mark.parametrize(
    ("efenix_address", "found"),
    [
        pytest.param("Poznań-Wilda ul.Kowalskiego Jana 12A Lokal 34", True, id="słowa-w-innej-kolejności-i-Lokal"),
        pytest.param("Poznań-Wilda ul.Jana Kowalskiego 12A Lokal 35", False, id="inny-lokal"),
        pytest.param("Poznań-Wilda ul.Jana Kowalskiego 12B Lokal 34", False, id="inny-numer"),
        pytest.param("Poznań-Wilda ul.Jana Kowalskiej 12A Lokal 34", False, id="inne-słowo"),
        pytest.param("Poznań-Wilda os.Jana Kowalskiego 12A Lokal 34", False, id="inny-rodzaj"),
    ],
)
def test_dane_adresowe_efenix_to_adres_z_pliku_w_dowolnej_kolejnosci_slow_z_lokalem_i_tylko_wtedy(
    tmp_path: Path, page: Page, efenix_address: str, found: bool
) -> None:
    order = Order("#9001", address="UL. JANA KOWALSKIEGO 12A/34", efenix_address=efenix_address)
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])

    assert _errors(outcome) == ([] if found else [("EFENIX_INNY_ADRES", "wiersz 18")])


def test_plik_bez_kwot_au_policzonych_przez_excel_zatrzymuje_wycene_zanim_otworzy_efenix(tmp_path: Path, page: Page) -> None:
    orders = [Order("#9101"), Order("#9102", amount=None)]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        requested = atrapa.requested()

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), outcome.ending.message.where.rpartition(", ")[2], requested) == ("EFENIX_KWOTY_NIEPOLICZONE", "wiersz 19", [])
    assert "Otwórz i zapisz Plik zbiorczy w Excelu" in outcome.ending.message.action


@pytest.mark.parametrize(
    ("headers", "code", "missing"),
    [
        pytest.param({"F": None}, "EFENIX_BRAK_NAGLOWKOW", "W Pliku zbiorczym brakuje nagłówków: NUMER ZL.", id="bez-numer-zl"),
        pytest.param(
            {"H": None, "I": "WYKONAWCA"},
            "EFENIX_NIECZYTELNY_PLIK_ZBIORCZY",
            "Plik zbiorczy jest uszkodzony albo nie ma układu Pliku zbiorczego.",
            id="wykonawca-w-i17-a-nie-w-h17",
        ),
    ],
)
def test_plik_bez_naglowka_kolumny_wyceny_albo_z_wykonawca_poza_h17_zatrzymuje_wycene_zanim_otworzy_efenix(
    tmp_path: Path, page: Page, headers: dict[str, str | None], code: str, missing: str
) -> None:
    order = Order("#9111", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("911")]) as atrapa:
        outcome = _run(write_collective_file(tmp_path, [order], headers=headers), page, atrapa.url)
        requested = atrapa.requested()

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), outcome.ending.message.what.startswith(missing), requested) == (code, True, [])


def test_numer_zl_liczba_niecalkowita_to_numer_z_czescia_ulamkowa_a_nie_numer_innego_zlecenia(tmp_path: Path, page: Page) -> None:
    """``NUMER ZL.`` liczbą całkowitą to numer bez ``.0``, a liczba z częścią ułamkową to numer z nią: zlecenie 9122 z
    efenix nie jest zleceniem z ``9122.5`` w Pliku zbiorczym, więc tego numeru efenix nie zna."""

    whole = Order("#9121", cells={"F": 9121.0})
    fraction = Order("#9122", cells={"F": 9122.5})
    with atrapa_efenix([whole.in_efenix("912"), fraction.in_efenix("913")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [whole, fraction])
        searched = atrapa.searched()

    assert (searched, _errors(outcome)) == (["9121", "9122.5"], [("EFENIX_NIEZNANY_NUMER", "wiersz 19")])


@pytest.mark.parametrize(
    ("expire_after", "searched", "kept"),
    [
        pytest.param(None, [], False, id="przed-szukaniem"),
        pytest.param((ORDER_PAGE, 0), ["9201"], False, id="przy-otwarciu-pierwszego-zlecenia"),
        # Szukanie bez sesji efenix nie przekierowuje, tylko odpowiada samym ostrzeżeniem o wygasłej sesji (#828).
        pytest.param((SEARCH, 1), ["9201", "9202"], True, id="przy-szukaniu"),
        # Strona pierwszego zlecenia otwiera się trzy razy: przy otwarciu, po dacie wykonania i po Wycenie Emmetta.
        pytest.param((ORDER_PAGE, 3), ["9201", "9202"], True, id="przy-otwarciu-zlecenia"),
        pytest.param((SET_DATE, 1), ["9201", "9202"], True, id="przy-dacie-wykonania"),
        pytest.param((LOAD_EMMETT, 1), ["9201", "9202"], True, id="przy-wycenie-emmetta"),
        pytest.param((SAVE_QUANTITY, 1), ["9201", "9202"], True, id="przy-zapisie-ilości"),
    ],
)
def test_wylogowanie_przed_szukaniem_albo_w_trakcie_zatrzymuje_wycene_a_komunikat_mowi_czy_cos_zmienila(
    tmp_path: Path, page: Page, expire_after: tuple[str, int] | None, searched: list[str], kept: bool
) -> None:
    orders = [Order(f"#920{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)], expire_after=expire_after) as atrapa:
        if expire_after is None:
            atrapa.expire_session()
        outcome = _price(tmp_path, page, atrapa.url, orders)

        assert (_stop(outcome), atrapa.searched(), _kept(outcome)) == ("EFENIX_WYLOGOWANY", searched, kept)


def test_wylogowanie_w_odpowiedzi_na_date_wykonania_zatrzymuje_wycene_bez_ponownego_otwarcia_zlecenia(tmp_path: Path, page: Page) -> None:
    """Odpowiedź efenix na „Potwierdź” daty wykonania, która przekierowuje na stronę logowania, to wylogowanie: okno nie
    otwiera już strony zlecenia, żeby sprawdzić zapisaną datę."""

    order = Order("#9211", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("921")], expire_after=(SET_DATE, 0)) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        requested = atrapa.requested()

    assert (_stop(outcome), requested.count(("POST", SET_DATE)), requested.count(("GET", ORDER_PAGE))) == ("EFENIX_WYLOGOWANY", 1, 1)


TIMEOUT = "playwright._impl._errors.TimeoutError"
# Część strony, której zabrakło przy każdej zmianie budowy Atrapy (lista, tabela wyników, strona zlecenia, okno daty
# wykonania, Emmett albo kwota), przyczyna techniczna z tabeli decyzji (``tests/test_tabela_zatrzyman_efenix.py``) i działanie
# okna, które się nie udało.
CHANGED: dict[Changed, tuple[PagePart, WindowCause, str]] = {
    Changed.STATUS_HEADER: (PagePart.RESULTS, OtherShape(Shape.COLUMNS), "szukanie"),
    Changed.ORDER_LINK: (PagePart.RESULTS, OtherShape(Shape.ROW_CELLS), "szukanie"),
    Changed.RESULTS_WARNING: (PagePart.RESULTS, OtherShape(Shape.NO_TABLE), "szukanie"),
    Changed.DATE_FORMAT: (PagePart.ORDER, OtherShape(Shape.DATE_TEXT), "otwarcie zlecenia"),
    Changed.DATE_DIGITS: (PagePart.ORDER, OtherShape(Shape.DATE_TEXT), "otwarcie zlecenia"),
    Changed.SIGNED_AMOUNT: (PagePart.ORDER, OtherShape(Shape.AMOUNT_TEXT), "otwarcie zlecenia"),
    Changed.DATE_DIALOG: (PagePart.DATE, BrowserFailure(TIMEOUT, Operation.ELEMENT), "data wykonania"),
    Changed.EMMETT_BUTTON: (PagePart.EMMETT, ElementCount("#button_emmett", 0), "Wycena Emmetta"),
    Changed.HIDDEN_EMMETT: (PagePart.EMMETT, BrowserFailure(TIMEOUT, Operation.CLICK), "Wycena Emmetta"),
    Changed.STALE_AMOUNT: (PagePart.QUANTITY, BrowserFailure(TIMEOUT, Operation.AMOUNT), "ilość"),
    Changed.QUANTITY_ANSWER: (PagePart.QUANTITY, OtherShape(Shape.ANSWER_NOT_JSON, "012"), "ilość"),
    Changed.QUANTITY_VALUE: (PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, "012"), "otwarcie zlecenia"),
    Changed.SECOND_NUMBER_FIELD: (PagePart.LIST, ElementCount("#field_numer", 2), "szukanie"),
    Changed.NUMBER_FIELD_GONE: (PagePart.LIST, ElementCount("#field_numer", 0), "szukanie"),
}


@pytest.mark.parametrize("changed", list(Changed))
def test_inna_budowa_tabeli_wynikow_albo_strony_zlecenia_zatrzymuje_wycene_do_maksa_z_czescia_strony(
    tmp_path: Path, page: Page, changed: Changed
) -> None:
    """Zatrzymanie przychodzi w czasie okna (tu 3 s), także przy elemencie obecnym, ale niewidocznym.

    Tylko zapis ilości (kwota, która się nie odświeża, i odpowiedź w innym zapisie) zatrzymuje wycenę po zmianie w efenix
    (Wycena Emmetta i ilość). To Zatrzymanie okna jak każde inne, „do Maksa”, więc Centrum daje przy nim Diagnozę i
    Zgłoszenie, a „Gdzie” nazywa część strony, której zabrakło. Fakty Zatrzymania dla Logów Uruchomienia mają przyczynę
    techniczną i działanie okna, które się nie udało.
    """

    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    # Okno daty wykonania okno efenix otwiera tylko przy pustej dacie wykonania w efenix.
    in_efenix = replace(order.in_efenix("901"), execution_date=None if changed is Changed.DATE_DIALOG else DAY)
    with atrapa_efenix([in_efenix], changed=changed) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)
        changes = atrapa.status_changes()

    assert (_stop(outcome), changes, _kept(outcome)) == ("EFENIX_OKNO_ZATRZYMANE", 0, changed in (Changed.STALE_AMOUNT, Changed.QUANTITY_ANSWER))
    assert isinstance(outcome.ending, Stop)
    message = outcome.ending.message
    part, cause, failed = CHANGED[changed]
    assert (outcome.ending.stop_kind, message.where) == ("for_maks", f"okno efenix, {part.value}")
    assert message.what.startswith("Wycena w efenix się zatrzymała, Maks już wie.")
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped) and facts.stopped_at is not None
    stopped_at = facts.stopped_at.failed
    assert stopped_at is not None
    assert (facts.part, facts.cause, stopped_at.action) == (part, cause, failed)


def test_zmieniona_strona_efenix_oznacza_gotowe_przed_nia_a_komunikat_do_maksa_nie_ma_numeru_adresu_ani_loginu(
    tmp_path: Path, page: Page
) -> None:
    """Wiersz 18 ma już wycenę zgodną z plikiem, a wiersz 19 czeka na Wycenę Emmetta, której przycisku efenix już nie ma.

    Komunikat Zatrzymania trafia do Zgłoszenia do Maksa i do Logów Uruchomienia, więc nie ma w nim niczego ze zlecenia.
    """

    orders = [
        Order("#9601", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9602", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [order.in_efenix(f"96{index}") for index, order in enumerate(orders)]
    with atrapa_efenix(in_efenix, changed=Changed.EMMETT_BUTTON) as atrapa:
        outcome = _run(source, page, atrapa.url, timeout_ms=3_000)

    assert (_stop(outcome), _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZATRZYMANE", True, [18])
    assert isinstance(outcome.ending, Stop)
    text = outcome.ending.message.text
    private = [
        *(order.number for order in in_efenix),
        *(order.order_id for order in in_efenix),
        *(order.realizator for order in in_efenix),
        "Testowa",
        "TESTOWA",
        "Fikcyjny",
    ]
    assert (outcome.ending.stop_kind, [word for word in private if word in text]) == ("for_maks", [])


@dataclass
class _FakeTime:
    """Udawany czas tempa ludzkiego: stoi, a przesuwa go tylko przerwa (``pause``).

    Nie ``ManualClock`` z ``tests/fixtures/clock.py``: ten plik jest w zmianie wzorcowego PR C bramki, a jego import
    dołożyłby ten plik testów do toru C ponad limit (``tests/test_ksztalt_bramki.py``).
    """

    seconds: float = 0.0

    def __call__(self) -> float:
        return self.seconds

    def pause(self, seconds: float) -> None:
        self.seconds += seconds


def _closing_window(page: Page, clock: _FakeTime, at_pause: int) -> Pace:
    """Tempo na udawanym zegarze, w którym tata zamyka kartę efenix w przerwie numer ``at_pause`` (od 1, 0: nie zamyka)."""

    pauses = 0

    def sleep(seconds: float) -> None:
        nonlocal pauses
        clock.pause(seconds)
        pauses += 1
        if pauses == at_pause:
            page.close()

    return Pace(sleep=sleep, clock=clock)


class _ClosingBeforeAction:
    """Okno efenix ``efenix``, w którym tata zamyka kartę ``page`` tuż przed działaniem okna numer ``at_action`` (od 1, 0:
    nie zamyka)."""

    def __init__(self, efenix: Efenix, page: Page, at_action: int) -> None:
        self._efenix = efenix
        self._page = page
        self._left = at_action

    def search(self, number: str) -> Sequence[ListedOrder]:
        self._before()
        return self._efenix.search(number)

    def open_order(self, order: ListedOrder) -> OrderPricing:
        self._before()
        return self._efenix.open_order(order)

    def set_execution_date(self, day: date) -> bool:
        self._before()
        return self._efenix.set_execution_date(day)

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        self._before()
        return self._efenix.load_emmett(verdict)

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        self._before()
        return self._efenix.enter_quantity(position, quantity)

    def _before(self) -> None:
        self._left -= 1
        if self._left == 0:
            self._page.close()


@pytest.mark.parametrize(
    ("closed_at", "kept", "marked"),
    [
        # Działania okna: 1 szukanie wiersza 18, 2 jego otwarcie, 3 szukanie wiersza 19, 4 jego otwarcie, 5 data
        # wykonania, 6 ponowne otwarcie po dacie, 7 Wycena Emmetta, 8 ilość. Przerwy tempa są tylko przed zapisami: 1 przed
        # datą wykonania, 2 przed Wyceną Emmetta, 3 przed ilością. Przed szukaniem i otwarciem po zleceniu bez zapisu
        # przerwy nie ma, więc tam tata zamyka kartę tuż przed działaniem.
        pytest.param(("działanie", 1), False, [], id="przy-szukaniu-na-liście"),
        pytest.param(("działanie", 3), False, [18], id="między-zleceniami"),
        pytest.param(("przerwa", 1), False, [18], id="przy-dacie-wykonania"),
        pytest.param(("działanie", 6), True, [18], id="po-dacie-wykonania"),
        pytest.param(("przerwa", 2), True, [18], id="przy-wycenie-emmetta"),
        pytest.param(("przerwa", 3), True, [18], id="przy-ilości"),
    ],
)
def test_zamkniete_okno_efenix_zatrzymuje_wycene_z_komunikatem_dla_taty_a_gotowe_przed_nim_maja_znacznik(
    tmp_path: Path, page: Page, closed_at: tuple[str, int], kept: bool, marked: list[int]
) -> None:
    orders = [
        Order("#9701", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9702", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    source = write_collective_file(tmp_path, orders)
    clock = _FakeTime()
    where, number = closed_at
    in_pause, before_action = (number, 0) if where == "przerwa" else (0, number)
    with atrapa_efenix([order.in_efenix(f"97{index}") for index, order in enumerate(orders)], clock=clock) as atrapa:
        outcome = _run(
            source,
            page,
            atrapa.url,
            pace=_closing_window(page, clock, in_pause),
            window=lambda efenix: _ClosingBeforeAction(efenix, page, before_action),
        )

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), outcome.ending.stop_kind, _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZAMKNIETE", "for_tata", kept, marked)


@pytest.mark.parametrize(
    ("first", "execution_date", "kept", "marked"),
    [
        # Kalendarz zamienia dzień spoza zakresu, więc okno zamyka go bez „Potwierdź”: błąd zlecenia bez zmiany w efenix.
        pytest.param(
            Order("#9711", day=date(2026, 10, 13), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
            None,
            False,
            [],
            id="dzień-spoza-kalendarza",
        ),
        pytest.param(
            Order("#9711", cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 1}), DAY, True, [18], id="sama-wycena-emmetta"
        ),
        pytest.param(
            Order("#9711", cells={"O": 2}, amount=_au({"012": 2}), quantities={"012": 1}), DAY, True, [18], id="sama-ilość"
        ),
    ],
)
def test_komunikat_zamknietego_okna_mowi_o_zmianie_w_efenix_po_kazdym_zapisie_a_nie_po_dniu_ktorego_kalendarz_nie_przyjal(
    tmp_path: Path, page: Page, first: Order, execution_date: date | None, kept: bool, marked: list[int]
) -> None:
    """W pierwszym zleceniu okno robi tylko jedno działanie po otwarciu: wybiera dzień, którego kalendarz nie przyjął,
    ładuje Wycenę Emmetta albo wpisuje ilość. Tata zamyka kartę tuż przed szukaniem drugiego zlecenia (działanie 4), więc
    o tym, czy Komunikat mówi, że wycena sprzed Zatrzymania została w efenix, decyduje tylko to jedno działanie. Drugie
    zlecenie ma późniejszy dzień, bo Wycena idzie po zleceniach jednego Wykonawcy w kolejności dni."""

    orders = [first, Order("#9712", day=date(2026, 10, 14), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [replace(first.in_efenix("971"), execution_date=execution_date), orders[1].in_efenix("972")]
    with atrapa_efenix(in_efenix, today=date(2026, 10, 12)) as atrapa:
        outcome = _run(source, page, atrapa.url, window=lambda efenix: _ClosingBeforeAction(efenix, page, 4))

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZAMKNIETE", kept, marked)


class _CloseReportedLate:
    """Karta ``page``, którą tata zamyka, gdy okno czeka na stronę ``path`` po raz ``number`` (od 1): ta strona nie
    odpowiada, więc karta zamyka się w trakcie nawigacji. Playwright podaje oknu zamknięcie karty dopiero przy jego
    następnym pytaniu przeglądarki, po błędzie nawigacji (najgorszy przypadek wyścigu #878; na Chromium bez tej karty
    pomiar dał błąd przed wiadomością o zamknięciu w 89 na 100 zamknięć, więc test bez niej przechodził czasem i przed
    poprawką).
    """

    def __init__(self, page: Page, path: str, number: int) -> None:
        self._page = page
        self._unreported = False
        seen = 0

        def handle(route: Route) -> None:
            nonlocal seen
            if urlparse(route.request.url).path.endswith("/" + path):
                seen += 1
                if seen == number:
                    self._unreported = True
                    page.close()
                    return
            route.continue_()

        page.route("**/*", handle)

    def is_closed(self) -> bool:
        return not self._unreported and self._page.is_closed()

    def __getattr__(self, name: str) -> object:
        self._unreported = False
        return getattr(self._page, name)


# Strona, w trakcie której nawigacji tata zamyka kartę: lista przy starcie i przed szukaniem drugiego zlecenia, strona
# zlecenia przy otwarciu i po dacie wykonania, i przeładowanie po „Załaduj do zlecenia”.
NAVIGATIONS = {
    "lista-na-starcie": (LIST_PAGE, 1, PagePart.LIST),
    "strona-zlecenia": (ORDER_PAGE, 1, PagePart.ORDER),
    "strona-po-dacie": (ORDER_PAGE, 2, PagePart.ORDER),
    "przeladowanie-po-emmetcie": (ORDER_PAGE, 3, PagePart.EMMETT),
    "lista-ponownie": (LIST_PAGE, 2, PagePart.LIST),
}


def _full_and_ready() -> list[Order]:
    """Wiersz 18 dostaje datę wykonania, Wycenę Emmetta i ilość z pliku, a wiersz 19 ma już wycenę zgodną z plikiem."""

    return [
        Order("#9801", day=date(2026, 9, 3), cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1}),
        Order("#9802", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
    ]


def _full_and_ready_in_efenix(orders: Sequence[Order]) -> list[AtrapaOrder]:
    return [orders[0].in_efenix("981"), replace(orders[1].in_efenix("982"), execution_date=DAY)]


@pytest.mark.parametrize(("path", "number", "part"), NAVIGATIONS.values(), ids=NAVIGATIONS.keys())
def test_karta_zamknieta_w_trakcie_nawigacji_okna_to_zamkniete_okno_takze_gdy_blad_nawigacji_przychodzi_pierwszy(
    tmp_path: Path, page: Page, path: str, number: int, part: PagePart
) -> None:
    """Tata zamyka kartę, gdy okno otwiera stronę (#878): Playwright przerywa nawigację błędem, zanim powie o zamknięciu
    karty, a Zatrzymanie to i tak zamknięte okno z Komunikatem dla taty, a nie „okno zatrzymane” do Maksa ani „efenix
    niedostępny” przy starcie."""

    orders = _full_and_ready()
    with atrapa_efenix(_full_and_ready_in_efenix(orders)) as atrapa:
        closing = cast(Page, _CloseReportedLate(page, path, number))
        outcome = _price(tmp_path, closing, atrapa.url, orders)

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.part, facts.cause) == (
        "EFENIX_OKNO_ZAMKNIETE",
        "for_tata",
        part,
        Closed.DURING_ACTION,
    )


def test_cala_przegladarka_zamknieta_w_trakcie_otwierania_strony_zlecenia_to_zamkniete_okno(tmp_path: Path) -> None:
    """Tata zamyka całą przeglądarkę, a nie kartę, gdy okno otwiera stronę zlecenia: pytanie przeglądarki, czy karta jest
    zamknięta (``BrowserEfenix.closed``), kończy się wtedy błędem, a Zatrzymanie to i tak zamknięte okno z Komunikatem
    dla taty, a nie „okno zatrzymane” do Maksa ani wyjątek Playwrighta (#886)."""

    orders = _full_and_ready()

    def priced_in_own_browser(url: str) -> Priced:
        with chromium() as own:
            page = own.new_page()
            browser_session = own.new_browser_cdp_session()

            def close_browser(request: PlaywrightRequest) -> None:
                if urlparse(request.url).path.endswith("/" + ORDER_PAGE):
                    # Przeglądarka zamyka się, zanim odpowie na to pytanie.
                    with suppress(PlaywrightError):
                        browser_session.send("Browser.close")

            page.on("request", close_browser)
            return _price(tmp_path, page, url, orders)

    with atrapa_efenix(_full_and_ready_in_efenix(orders)) as atrapa:
        # Własna przeglądarka, którą test zamyka, startuje własny Playwright, a ten wątek ma już Playwright testów.
        with ThreadPoolExecutor(max_workers=1) as own_thread:
            outcome = own_thread.submit(priced_in_own_browser, atrapa.url).result()

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.part, facts.cause) == (
        "EFENIX_OKNO_ZAMKNIETE",
        "for_tata",
        PagePart.ORDER,
        Closed.DURING_ACTION,
    )


def test_strona_ktora_nie_odpowiada_konczy_dzialanie_okna_zatrzymaniem_w_czasie_okna(tmp_path: Path, page: Page) -> None:
    """Skrypt strony efenix stoi w pętli przez 20 s, więc strona nie odpowiada: działanie okna kończy się po czasie
    czekania okna (tu 1 s) Zatrzymaniem do Maksa, a pytanie, czy karta jest zamknięta (``BrowserEfenix.closed``), ma ten
    sam limit czasu, więc okno w nim nie wisi (#886). Karta testu nie ma domyślnego limitu Playwrighta, więc działanie
    okna bez własnego limitu albo z domyślnym limitem okna (30 s) czekałoby do końca pętli, a strona po Uruchomieniu
    odpowiadałaby już."""

    orders = _full_and_ready()
    page.set_default_timeout(0)

    def hung(efenix: Efenix) -> Efenix:
        page.evaluate("setTimeout(() => { const end = Date.now() + 20_000; while (Date.now() < end) {} }, 0)")
        return efenix

    with atrapa_efenix(_full_and_ready_in_efenix(orders)) as atrapa:
        outcome = _run(write_collective_file(tmp_path, orders), page, atrapa.url, timeout_ms=1_000, window=hung)

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        "for_maks",
        PagePart.LIST,
        BrowserFailure(TIMEOUT, Operation.FILL),
    )
    with pytest.raises(PlaywrightError, match="Timeout"):
        page.locator(":root").wait_for(state="attached", timeout=1_000)


# Żądanie okna, na które efenix odpowiada stroną błędu serwera, numer tego żądania okna, status i część strony, którą
# Zatrzymanie nazywa. Szukania, które lista wysyła sama, okno nie czyta, więc nie ma go tu.
ERROR_ANSWERS = {
    "lista-na-starcie": (LIST_PAGE, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.LIST),
    "lista-ponownie": (LIST_PAGE, 2, HTTPStatus.NOT_FOUND, PagePart.LIST),
    "szukanie": (SEARCH, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.RESULTS),
    "szukanie-404": (SEARCH, 2, HTTPStatus.NOT_FOUND, PagePart.RESULTS),
    "data-wykonania": (SET_DATE, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.DATE),
    "zaladuj-do-zlecenia": (LOAD_EMMETT, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.EMMETT),
    "ilosc": (SAVE_QUANTITY, 1, HTTPStatus.NOT_FOUND, PagePart.QUANTITY),
}


@pytest.mark.parametrize(("path", "number", "status", "part"), ERROR_ANSWERS.values(), ids=ERROR_ANSWERS.keys())
def test_strona_bledu_serwera_efenix_na_kazde_zadanie_okna_zatrzymuje_wycene_do_maksa_ze_statusem_http(
    tmp_path: Path, page: Page, path: str, number: int, status: HTTPStatus, part: PagePart
) -> None:
    """Odpowiedź efenix ze statusem błędu na listę, szukanie, zapis daty, „Załaduj do zlecenia” albo zapis ilości to
    Zatrzymanie okna „do Maksa” z przyczyną ``HttpStatus`` i częścią strony (#878), a nie strona albo odpowiedź w innej
    budowie (pole Numer, którego nie ma, odpowiedź szukania bez tabeli, odpowiedź zapisu ilości, która nie jest JSON) ani
    zlecenie, które idzie dalej, choć efenix nie przyjął zmiany. Przy starcie adres odpowiada, więc to nie „efenix
    niedostępny”."""

    orders = _full_and_ready()
    with atrapa_efenix(_full_and_ready_in_efenix(orders), error_answer=(path, number, status)) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders, timeout_ms=3_000)

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        "for_maks",
        part,
        HttpStatus(status),
    )


def _window_moments(atrapa: AtrapaEfenix, path: str, since: int = 0) -> list[float]:
    """Chwila każdego żądania ``path`` okna od żądania numer ``since``, bez szukania, które lista wysyła sama."""

    return [request.at for request in atrapa.requests[since:] if request.path == path and not request.by_list]


def test_w_tempie_ludzkim_zlecenie_z_zapisem_trwa_20_s_samo_sprawdzenie_idzie_bez_przerw_a_przerwa_nie_przekracza_progu_podtrzymania_sesji(
    tmp_path: Path, page: Page
) -> None:
    """Na udawanym zegarze: przerwy są przed zapisami w efenix (#834). Zlecenie z Wyceną Emmetta trwa od szukania do
    szukania następnego 20 s (spec #741), z przerwą 2 s przed datą wykonania, Wyceną Emmetta i każdą ilością. Zlecenie z
    wyceną, która już jest i niczego nie potrzebuje, Zlecenie rozliczone i zlecenie z błędem nic nie zapisują, więc po nich szukanie następnego i
    otwarcie idą bez przerwy, tak samo jak pierwsze szukanie przebiegu i każde otwarcie strony zlecenia. Żadna przerwa
    nie przekracza progu podtrzymania sesji, także po zleceniu z jednym zapisem, któremu do 20 s brakuje więcej. Czas każdego działania okna w śladzie zlecenia do Logów Uruchomienia nie
    liczy przerwy przed nim, więc na zegarze, który przesuwa tylko przerwa, jest równy 0."""

    emmett = {"O": 1, "T": 2, "AG": 1}
    filled = _au({"012": 1, "019": 2, "015": 1})
    many = {column: 1 for column in ("O", "P", "Q", "R", "S", "T", "U", "V", "Y", "Z")}
    orders = [
        Order("#9801", day=date(2026, 9, 3), cells=emmett, amount=filled, emmett={"012": 1}),
        Order("#9802", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # gotowe
        Order("#9803", day=date(2026, 9, 5), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # rozliczone
        # Wycena, która już jest, ma O większe niż plik: Ostrzeżenie Emmetta bez zapisu.
        Order("#9804", day=date(2026, 9, 6), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 2}),
        # Data wykonania już jest, a Emmett ma O większe niż plik: jedyny zapis to Wycena Emmetta, więc do 20 s od szukania brakuje
        # 18 s, a przerwa przed szukaniem następnego zlecenia to próg podtrzymania sesji.
        Order("#9805", day=date(2026, 9, 7), cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 2}),
        Order("#9806", day=date(2026, 9, 8), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # gotowe
        Order("#9807", day=date(2026, 9, 9), cells=emmett, amount=filled, emmett={"012": 1}),
        Order("#9808", day=date(2026, 9, 10), cells=emmett, amount=filled, emmett={"012": 1}),
        # Po Emmetcie dziewięć ilości: zapisy trwają 22 s od szukania, więc przed szukaniem następnego zostaje najkrótsza przerwa.
        Order("#9809", day=date(2026, 9, 11), cells=many, amount=_au({code: 1 for code in ("012", "013", "014", "017", "016", "019", "027", "029", "009", "010")}), emmett={"012": 1}),
        # Jedyny zapis to data wykonania: po niej strona nie ma pozycji z ilością w pliku, więc to błąd zlecenia.
        Order("#9810", day=date(2026, 9, 12), cells={"O": 1}, amount=_au({"012": 1})),
        Order("#9811", day=date(2026, 9, 13), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # gotowe
    ]
    in_efenix = [order.in_efenix(f"98{index}") for index, order in enumerate(orders)]
    in_efenix[2] = replace(in_efenix[2], status="Rozliczone", execution_date=orders[2].day)
    in_efenix[4] = replace(in_efenix[4], execution_date=orders[4].day)
    in_efenix[9] = replace(in_efenix[9], without=frozenset({"012"}), after_date=True)
    clock = _FakeTime()
    with atrapa_efenix(in_efenix, clock=clock) as atrapa:
        source = write_collective_file(tmp_path, orders)
        outcome = _run(source, page, atrapa.url, pace=Pace(sleep=clock.pause, clock=clock), clock=clock)
        moments = atrapa.moments()

    gaps = [later[0] - earlier[0] for earlier, later in itertools.pairwise(moments)]
    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(11, 7, warnings=2, settled=1),
        [("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 21"), ("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 22"), ("EFENIX_BRAK_POZYCJI", "wiersz 27")],
    )
    # Zlecenie 1 szuka w chwili 0 i zapisuje w 2, 4, 6 i 8, więc szukanie zlecenia 2 czeka do 20. Zlecenia 2, 3 i 4 nic nie
    # zapisują: zlecenie 3 (rozliczone) nie otwiera strony, a szukanie zleceń 3, 4 i 5 jest w tej samej chwili 20. Zlecenie
    # 5 ładuje Emmetta w 22, więc zlecenie 6 szuka w 22 + 15, a zlecenie 7 po gotowym zleceniu 6 w tej samej chwili.
    # Zlecenia 7, 8 i 9 z zapisem idą po sobie: zlecenia 8 i 9 szukają 20 s po poprzednim. Ostatnia ilość zlecenia 9 jest
    # w 99, 22 s po jego szukaniu, więc zlecenie 10 szuka po najkrótszej przerwie w 101. Zlecenie 10 zapisuje tylko datę w
    # 103, więc zlecenie 11 szuka w 103 + 15.
    assert _window_moments(atrapa, SEARCH) == [0, 20, 20, 20, 20, 37, 37, 57, 77, 101, 118]
    assert _window_moments(atrapa, ORDER_PAGE) == [0, 2, 4, 20, 20, 20, 22, 37, 37, 39, 41, 57, 59, 61, 77, 79, 81, 101, 103, 118]
    assert _window_moments(atrapa, SET_DATE) == [2, 39, 59, 79, 103]
    assert _window_moments(atrapa, LOAD_EMMETT) == [4, 22, 41, 61, 81]
    assert _window_moments(atrapa, SAVE_QUANTITY) == [6, 8, 43, 45, 63, 65, *range(83, 100, 2)]
    # Ruch w oknie co kilkanaście sekund (spec #741): próg podtrzymania sesji jest krótszy niż 20 s.
    assert max(gaps) <= KEEPALIVE_S < 20
    assert outcome.view is not None
    durations = [[step.duration_ms for step in result.steps] for result in outcome.view.results]
    assert [len(steps) for steps in durations] == [7, 2, 1, 2, 3, 2, 7, 7, 14, 4, 2]
    assert {duration for steps in durations for duration in steps} == {0}


def test_strona_bez_listy_zlecen_i_adres_bez_efenix_zatrzymuja_wycene(tmp_path: Path, page: Page) -> None:
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{unused.getsockname()[1]}/{LIST_PAGE}"
    with atrapa_efenix([Order("#9301").in_efenix("901")]) as atrapa:
        changed = _price(tmp_path / "zmieniony", page, atrapa.url.replace(LIST_PAGE, "inna_strona.php"), [Order("#9301")])
    unreachable = _price(tmp_path / "niedostepny", _next_tab(page), closed, [Order("#9301")])

    assert (_stop(changed), _stop(unreachable), _kept(changed), _kept(unreachable)) == ("EFENIX_OKNO_ZATRZYMANE", "EFENIX_NIEDOSTEPNY", False, False)


# --- Znacznik efenix w Pliku zbiorczym (#747) ------------------------------------------------------------------------

YELLOW = "FFFF00"
CHANGED_PARTS = {"xl/worksheets/sheet1.xml", "xl/styles.xml"}


def _parts(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def _address_fills(source: Path) -> dict[int, str | None]:
    """RGB jednolitego wypełnienia ``ADRES`` każdego Wiersza danych tak, jak czyta je Przebieg rozliczeń (``None``: bez)."""

    fills: dict[int, str | None] = {}
    for row in read_data_rows(source, despite_excel_lock=True).rows:
        fill = row.cells[1].highlights.fill
        solid = isinstance(fill, PatternFill) and fill.patternType == "solid"
        fills[row.number] = str(fill.fgColor.rgb)[-6:].upper() if solid and isinstance(fill, PatternFill) else None
    return fills


def _marked(source: Path) -> list[int]:
    return [row for row, rgb in _address_fills(source).items() if rgb == MARK_RGB]


def _address_looks(source: Path) -> dict[int, tuple[Font, Border, Protection, Alignment, str]]:
    """Wygląd ``ADRES`` każdego Wiersza danych poza wypełnieniem: czcionka, obramowanie, ochrona, wyrównanie, format."""

    workbook = load_workbook(source)
    try:
        sheet = active_worksheet(workbook)
        return {
            row: (copy(cell.font), copy(cell.border), copy(cell.protection), copy(cell.alignment), cell.number_format)
            for row in range(18, sheet.max_row + 1)
            if (cell := sheet[f"B{row}"]).value is not None
        }
    finally:
        workbook.close()


def _amounts(source: Path) -> dict[int, object]:
    """``Kwota`` (AU) każdego Wiersza danych tak, jak policzył ją Excel."""

    return {row.number: row.value("AU") for row in read_computed_rows(source).rows}


def _without_address_styles(xml: bytes, rows: Sequence[int]) -> bytes:
    """XML arkusza bez atrybutu ``s`` komórek ``ADRES`` wierszy ``rows``."""

    def neutral(found: re.Match[bytes]) -> bytes:
        return found.group(1) if int(found.group(2)) in rows else found.group(0)

    return re.sub(rb'(<c r="B(\d+)")(?: s="\d+")?', neutral, xml)


STYLE_LISTS = {b"fills": b"fill", b"cellXfs": b"xf"}


def _style_list(styles: bytes, tag: bytes) -> re.Match[bytes]:
    found = re.search(rb"<" + tag + rb'\b[^>]*?count="(\d+)"[^>]*>(.*?)</' + tag + rb">", styles, re.S)
    assert found is not None, tag
    return found


def _style_counts(styles: bytes) -> dict[bytes, int]:
    """Liczba wpisów każdej listy ``fills`` i ``cellXfs`` w ``xl/styles.xml``, zgodna z jej atrybutem ``count``."""

    counts = {}
    for tag, entry in STYLE_LISTS.items():
        found = _style_list(styles, tag)
        counts[tag] = len(re.findall(rb"<" + entry + rb"[\s>/]", found.group(2)))
        assert int(found.group(1)) == counts[tag], tag
    return counts


def _without_appended_styles(written: bytes, original: bytes) -> bytes:
    """``xl/styles.xml`` ``written`` z listami ``fills`` i ``cellXfs`` z ``original``, gdy ``written`` tylko dopisał do
    nich wpisy na końcu."""

    for tag in STYLE_LISTS:
        before, after = _style_list(original, tag), _style_list(written, tag)
        assert after.group(2).startswith(before.group(2)), tag
        written = written[: after.start()] + before.group(0) + written[after.end() :]
    return written


def _marking_orders() -> list[Order]:
    """Wiersze 18 i 19 gotowe (wycena już jest; dopisane ilości, ``ADRES`` bez stylu), 20 błąd kwoty, 21 Ostrzeżenie
    Emmetta (Emmett ma O większe niż plik), 22 Zlecenie ze zdjęciami, 23 nieznane efenix z żółtym ``ADRES`` taty.

    Wiersz 19 ma starszą ``DATA``, więc proces kończy go przed wierszem 18.
    """

    red = Font(name="Arial", sz=8, color="FFFF0000", b=True, i=True)
    return [
        Order("#7701", day=date(2026, 9, 10), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_font=red),
        Order("#7702", day=date(2026, 9, 8), cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), address_font=None),
        Order("#7703", cells={"O": 1}, amount=_au({"012": 1}) + 5),
        Order("#7704", cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 2}),
        Order("#7705", cells={"AB": 1}),
        Order("#7706", address_fill=YELLOW),
    ]


def _marking_efenix(orders: Sequence[Order]) -> list[AtrapaOrder]:
    return [order.in_efenix(f"77{index}") for index, order in enumerate(orders) if order.number != "#7706"]


def test_znacznik_efenix_staje_tylko_w_adresie_gotowych_zlecen_a_reszta_pliku_zostaje_bajt_w_bajt(tmp_path: Path, page: Page) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    parts, looks, amounts = _parts(source), _address_looks(source), _amounts(source)
    with atrapa_efenix(_marking_efenix(orders)) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(5, 2, warnings=1, photos=1))
    assert _address_fills(source) == {18: MARK_RGB, 19: MARK_RGB, 20: None, 21: None, 22: None, 23: YELLOW}
    # Poza wypełnieniem komórka ADRES ma swój wygląd, także czerwoną, pogrubioną kursywę taty w wierszu 18.
    assert _address_looks(source) == looks
    font = looks[18][0]
    assert (font.color.rgb if font.color else None, font.b, font.i) == ("FFFF0000", True, True)
    assert _amounts(source) == amounts
    written = _parts(source)
    assert [name for name, _ in written] == [name for name, _ in parts]
    before, after = dict(parts), dict(written)
    assert {name for name in before if before[name] != after[name]} == CHANGED_PARTS
    assert any(name.startswith("xl/externalLinks/") for name in before)
    sheet = "xl/worksheets/sheet1.xml"
    assert _without_address_styles(after[sheet], [18, 19]) == _without_address_styles(before[sheet], [18, 19])
    assert _without_appended_styles(after["xl/styles.xml"], before["xl/styles.xml"]) == before["xl/styles.xml"]
    # Jedno wypełnienie Znacznika i po jednym stylu na dwa dotychczasowe style gotowych ADRES.
    counts, original = _style_counts(after["xl/styles.xml"]), _style_counts(before["xl/styles.xml"])
    assert (counts[b"fills"] - original[b"fills"], counts[b"cellXfs"] - original[b"cellXfs"]) == (1, 2)


def test_nastepny_przebieg_na_pliku_ze_znacznikami_czyta_kwoty_au_ma_te_same_gotowe_i_niczego_nie_zmienia(
    tmp_path: Path, page: Page
) -> None:
    """Drugi przebieg nie ma czego dopisać: błąd kwoty (wiersz 20) i Ostrzeżenie Emmetta (wiersz 21) wracają takie same,
    gotowe wiersze mają już Znaczniki, a w efenix i w Pliku zbiorczym nic się nie zmienia (#767)."""

    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix(_marking_efenix(orders)) as atrapa:
        first = _run(source, page, atrapa.url)
        assert _figures(first) == _figures_of(5, 2, warnings=1, photos=1)
        marked, saved, state, requests = source.read_bytes(), source.stat().st_mtime_ns, atrapa.state(), len(atrapa.requested())
        second = _run(source, _next_tab(page), atrapa.url)
        after, again = atrapa.state(), atrapa.requested()[requests:]

    assert (_figures(second), _marked(source), _amounts(source)[18]) == (_figures_of(5, 2, warnings=1, photos=1), [18, 19], _au({"012": 1}))
    assert [error for error in _errors(second) if error[1] in {"wiersz 20", "wiersz 21"}] == [
        ("EFENIX_INNA_KWOTA", "wiersz 20"),
        ("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 21"),
    ]
    # Plik ze wszystkimi Znacznikami nie jest zapisywany od nowa, więc OneDrive nie dostaje nowej wersji.
    assert (source.read_bytes() == marked, source.stat().st_mtime_ns == saved) == (True, True)
    assert (after == state, set(again) <= READING) == (True, True)


def test_kolejne_uruchomienie_oznacza_nowe_gotowe_zlecenie_wypelnieniem_i_stylem_z_poprzedniego(
    tmp_path: Path, page: Page
) -> None:
    """Wiersz 19 jest gotowy dopiero w drugim przebiegu (w pierwszym efenix go nie zna), a jego ADRES ma ten sam styl co 18."""

    orders = [Order(f"#760{index}", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}) for index in (1, 2)]
    source = write_collective_file(tmp_path, orders)
    original = _style_counts(dict(_parts(source))["xl/styles.xml"])
    with atrapa_efenix([orders[0].in_efenix("761")]) as atrapa:
        first = _run(source, page, atrapa.url)
    marked_first = _marked(source)
    with atrapa_efenix([order.in_efenix(f"76{index}") for index, order in enumerate(orders)]) as atrapa:
        second = _run(source, _next_tab(page), atrapa.url)

    assert (first.result, marked_first, second.result, _marked(source)) == ("WYMAGA_SPRAWDZENIA", [18], "OK", [18, 19])
    counts = _style_counts(dict(_parts(source))["xl/styles.xml"])
    assert (counts[b"fills"] - original[b"fills"], counts[b"cellXfs"] - original[b"cellXfs"]) == (1, 1)


def test_znacznik_efenix_staje_na_aktywnej_karcie_ktora_czyta_wycena_a_inny_arkusz_zostaje(tmp_path: Path, page: Page) -> None:
    order = Order("#7401", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order], notes_sheet_first=True)
    notes = dict(_parts(source))["xl/worksheets/sheet1.xml"]
    with atrapa_efenix([order.in_efenix("741")]) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _marked(source), dict(_parts(source))["xl/worksheets/sheet1.xml"] == notes) == ("OK", [18], True)


def _packed_like_excel(source: Path) -> None:
    """Plik zbiorczy spakowany innym stopniem kompresji niż domyślny ``zipfile`` Pythona, jak plik zapisany przez Excel:
    te same części spakowane od nowa przez ``zipfile`` dają inne bajty."""

    with zipfile.ZipFile(source) as archive:
        parts = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for info, data in parts:
            archive.writestr(info.filename, data)


def test_gotowe_zlecenie_z_adresem_juz_w_kolorze_znacznika_zostaje_a_plik_sie_nie_zmienia(tmp_path: Path, page: Page) -> None:
    order = Order("#7501", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_fill=MARK_RGB)
    source = write_collective_file(tmp_path, [order])
    _packed_like_excel(source)
    before = source.read_bytes()
    with atrapa_efenix([order.in_efenix("751")]) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _marked(source), source.read_bytes() == before) == ("OK", [18], True)


def _replaced(part: str, old: bytes, new: bytes) -> Callable[[dict[str, bytes]], dict[str, bytes]]:
    """Kształt pliku: w części ``part`` jedno wystąpienie ``old`` (wyrażenie regularne) zastąpione ``new``."""

    def change(parts: dict[str, bytes]) -> dict[str, bytes]:
        changed, count = re.subn(old, new, parts[part], count=1)
        assert count == 1, (part, old)
        return {part: changed}

    return change


def _address_style_past_cell_xfs(parts: dict[str, bytes]) -> dict[str, bytes]:
    """Kształt pliku: ``ADRES`` wiersza 18 ma styl o numerze równym liczbie wpisów ``cellXfs``, czyli za ich końcem."""

    count = int(_style_list(parts["xl/styles.xml"], b"cellXfs").group(1))
    return _replaced("xl/worksheets/sheet1.xml", rb'(<c r="B18") s="\d+"', rb'\1 s="%d"' % count)(parts)


def _shaped(tmp_path: Path, order: Order, shape: Callable[[dict[str, bytes]], dict[str, bytes]]) -> Path:
    """Plik zbiorczy z jednym zleceniem ``order`` w kształcie ``shape``."""

    source = write_collective_file(tmp_path, [order])
    changed = shape(dict(_parts(source)))
    rewrite_parts(source, lambda name, data: changed.get(name, data))
    return source


PRICED_SHAPES = {
    "bez-relacji-skoroszytu": _replaced("_rels/.rels", rb'relationships/officeDocument"', b'relationships/document"'),
    "bez-relacji-stylow": _replaced("xl/_rels/workbook.xml.rels", rb'relationships/styles"', b'relationships/stylez"'),
    "komentarz-w-cellxfs": _replaced("xl/styles.xml", rb'<cellXfs count="\d+">', rb"\g<0><!--<xf/>-->"),
    "styl-adresu-za-cellxfs": _address_style_past_cell_xfs,
}
"""Kształty, których Excel nie zapisuje, a które odczyt zakresu Wyceny przyjmuje, więc proces dochodzi z nimi do zapisu
Znaczników."""


@pytest.mark.parametrize("shape", PRICED_SHAPES.values(), ids=PRICED_SHAPES.keys())
@pytest.mark.parametrize(
    ("extra", "ending"),
    [
        pytest.param(0, ("BLAD_KRYTYCZNY", "rozliczenia.efenix_marking.UnsupportedShape"), id="gotowe-zlecenie"),
        pytest.param(1, ("WYMAGA_SPRAWDZENIA", None), id="bez-gotowych-zlecen"),
    ],
)
def test_wycena_pliku_w_ksztalcie_ktorego_zapis_znacznikow_nie_przenosi_to_blad_kodu_bez_zmiany_pliku(
    tmp_path: Path, page: Page, shape: Callable[[dict[str, bytes]], dict[str, bytes]], extra: int, ending: tuple[str, str | None]
) -> None:
    """Gotowe zlecenie w pliku, którego kształtu zapis Znaczników nie przenosi: Uruchomienie kończy się błędem kodu, a
    ślad wywołań w Logach Uruchomienia mówi Maksowi, że to kształt pliku (``UnsupportedShape``), nie inny błąd. Plik
    zostaje bez zmian: nie dostaje stylu, którego Przebieg rozliczeń potem nie odczyta. Bez gotowych zleceń
    (kwota w efenix inna niż AU) zapis Znaczników pliku nie czyta, więc Uruchomienie kończy się zwykłym wynikiem."""

    order = Order("#7451", cells={"O": 1}, amount=_au({"012": 1}) + extra, quantities={"012": 1})
    source = _shaped(tmp_path, order, shape)
    before = source.read_bytes()
    with atrapa_efenix([order.in_efenix("751")]) as atrapa:
        outcome = _run(source, page, atrapa.url)

    trace = outcome.ending.trace if isinstance(outcome.ending, Stop) else None
    assert (outcome.result, trace and trace.exception_type, source.read_bytes() == before) == (*ending, True), _ending(outcome)


UNREACHED_SHAPES = {
    "aktywna-karta-za-ostatnia": (_replaced("xl/workbook.xml", rb'activeTab="0"', b'activeTab="1"'), "B", [18]),
    "aktywna-karta-bez-relacji": (_replaced("xl/workbook.xml", rb'r:id="rId1"', b'r:id="rId9"'), "B", [18]),
    "gotowy-wiersz-poza-arkuszem": (lambda _parts: {}, "B", [99]),
    "gotowy-wiersz-bez-komorki-adresu": (lambda _parts: {}, "C", [18]),
}


@pytest.mark.parametrize(("shape", "column", "rows"), UNREACHED_SHAPES.values(), ids=UNREACHED_SHAPES.keys())
def test_zapis_znacznikow_w_ksztalcie_do_ktorego_wycena_nie_dochodzi_to_blad_kodu_bez_zmiany_pliku(
    tmp_path: Path, shape: Callable[[dict[str, bytes]], dict[str, bytes]], column: str, rows: list[int]
) -> None:
    """Kształt, którego zapis Znaczników nie przenosi, to ``UnsupportedShape`` przed zapisem, a plik zostaje bez zmian.
    Uruchomienie Wyceny tu nie dochodzi, więc test prowadzi sam zapis Znaczników: aktywnej karty bez arkusza odczyt
    zakresu nie czyta (``UNREADABLE``), a numery wierszy i kolumnę ``ADRES`` proces bierze z odczytu tych samych bajtów,
    i gotowe zlecenie ma ``ADRES`` zgodny z efenix, więc jego wiersz i komórka ``ADRES`` zawsze są w arkuszu."""

    source = _shaped(tmp_path, Order("#7451", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}), shape)
    content = source.read_bytes()

    with pytest.raises(UnsupportedShape):
        mark_ready(source, content, column, rows)
    assert source.read_bytes() == content


@contextmanager
def _excel_open(source: Path) -> Iterator[Callable[[], None]]:
    """Tata otwiera Plik zbiorczy w Excelu w trakcie przebiegu (plik blokady ``~$…``), a po przebiegu go zamyka."""

    lock = excel_lock_file(source)
    def open_in_excel() -> None:
        lock.write_bytes(b"")

    yield open_in_excel
    lock.unlink(missing_ok=True)


@contextmanager
def _saved_in_excel(source: Path) -> Iterator[Callable[[], None]]:
    """Tata zapisuje w trakcie przebiegu Plik zbiorczy ze zmienioną komórką."""

    def save() -> None:
        rewrite_parts(source, lambda name, data: data.replace(b">MIASTO<", b">MIASTA<") if name == "xl/worksheets/sheet1.xml" else data)

    yield save


@contextmanager
def _read_only_folder(source: Path) -> Iterator[Callable[[], None]]:
    """Folder okresu przestaje przyjmować nowe pliki w trakcie przebiegu (np. OneDrive go trzyma), a potem znów je przyjmuje."""

    folder = source.parent
    yield lambda: folder.chmod(0o555)
    folder.chmod(0o755)


@pytest.mark.parametrize(
    ("obstacle", "code"),
    [
        pytest.param(_excel_open, "EFENIX_ZNACZNIKI_PLIK_OTWARTY", id="otwarty-w-excelu"),
        pytest.param(_saved_in_excel, "EFENIX_ZNACZNIKI_PLIK_ZMIENIONY", id="zapisany-w-trakcie"),
        pytest.param(
            _read_only_folder,
            "EFENIX_ZNACZNIKI_NIEZAPISANE",
            id="zapis-nieudany",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="chmod folderu nie odbiera zapisu na Windows"),
        ),
    ],
)
def test_plik_ktorego_nie_da_sie_oznaczyc_daje_komunikat_a_ponowne_uruchomienie_stawia_znaczniki_bez_zmian_w_efenix(
    tmp_path: Path, page: Page, obstacle: Callable[[Path], AbstractContextManager[Callable[[], None]]], code: str
) -> None:
    orders = [
        Order("#7801", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#7802", cells={"O": 1}, amount=_au({"012": 1})),
        Order("#7803", cells={"O": 1}, amount=_au({"012": 1}) + 5),
    ]
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix([order.in_efenix(f"78{index}") for index, order in enumerate(orders)]) as atrapa:
        with obstacle(source) as meanwhile:
            stopped = _run(source, page, atrapa.url, meanwhile=meanwhile)
            unmarked = source.read_bytes()
            assert (_stop(stopped), _marked(source)) == (code, [])
        priced, requests = atrapa.state(), len(atrapa.requested())
        assert source.read_bytes() == unmarked
        again = _run(source, _next_tab(page), atrapa.url)
        after, repeated = atrapa.state(), atrapa.requested()[requests:]

    assert {order.number: (order.quantities, order.execution_date, order.emmett_loads) for order in priced[0]} == {
        "7801": ({"012": 1}, DAY, 0),
        "7802": ({"012": 1}, DAY, 1),
        "7803": ({"012": 1}, DAY, 1),
    }
    assert (again.result, _figures(again), _marked(source)) == ("WYMAGA_SPRAWDZENIA", _figures_of(3, 2), [18, 19])
    assert (after == priced, set(repeated) <= READING) == (True, True)


@pytest.mark.parametrize(
    ("expire_after", "marked"),
    [
        pytest.param((SAVE_QUANTITY, 1), [18], id="po-pierwszym-gotowym"),
        pytest.param((SAVE_QUANTITY, 0), [], id="przed-pierwszym-gotowym"),
    ],
)
def test_zatrzymanie_w_polowie_przebiegu_oznacza_zlecenia_gotowe_przed_nim(
    tmp_path: Path, page: Page, expire_after: tuple[str, int], marked: list[int]
) -> None:
    """Po Zatrzymaniu proces stawia Znaczniki efenix gotowym zleceniom, a postęp mówi to tak jak po ostatnim zleceniu:
    ostatni krok Zapisywania to Znaczniki efenix, nie zlecenie, przy którym okno stanęło."""

    orders = [Order(f"#790{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    source = write_collective_file(tmp_path, orders)
    unmarked = source.read_bytes()
    with atrapa_efenix([order.in_efenix(f"79{index}") for index, order in enumerate(orders)], expire_after=expire_after) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (_stop(outcome), _marked(source)) == ("EFENIX_WYLOGOWANY", marked)
    assert (source.read_bytes() == unmarked) == (not marked)
    assert outcome.progress.step == SavingStep("Znaczniki efenix w Pliku zbiorczym", None, 0, 0)


def _resumed_orders() -> list[Order]:
    """Trzy zlecenia z pustą wyceną i datą wykonania: Emmett wpisuje O (012), a proces dopisuje AG (015) i T (019)."""

    cells, filled = {"O": 1, "T": 2, "AG": 1}, {"012": 1, "019": 2, "015": 1}
    return [Order(f"#990{index}", day=date(2026, 9, index), cells=cells, amount=_au(filled), emmett={"012": 1}) for index in (1, 2, 3)]


@pytest.mark.parametrize(
    "expire_after",
    [
        # Zlecenie 1 ma dwa zapisy ilości, więc trzeci to pierwsza ilość zlecenia 2, a czwarty wylogowuje w jego połowie.
        pytest.param((SAVE_QUANTITY, 3), id="w-połowie-ilości-zlecenia"),
        pytest.param((LOAD_EMMETT, 1), id="przy-wycenie-emmetta"),
        pytest.param((SET_DATE, 1), id="przy-dacie-wykonania"),
        # Strona zlecenia 1 otwiera się trzy razy, więc piąte otwarcie to zlecenie 2 po dacie wykonania.
        pytest.param((ORDER_PAGE, 4), id="przy-otwarciu-po-dacie"),
        pytest.param((SEARCH, 1), id="przy-szukaniu"),
    ],
)
def test_przerwanie_wylogowaniem_i_ponowne_uruchomienie_daje_ten_sam_stan_efenix_i_plik_zbiorczy_co_jeden_przebieg(
    tmp_path: Path, page: Page, expire_after: tuple[str, int]
) -> None:
    """Po wylogowaniu tata loguje się z powrotem i uruchamia ponownie; Wycena Emmetta jest najwyżej raz na zlecenie.

    W każdym z tych miejsc zlecenie 2 jest albo bez ilości, więc ponowne uruchomienie ładuje Wycenę Emmetta, albo ma już
    Wycenę Emmetta, więc ponowne uruchomienie ją dokańcza. Biegnie ono w tempie ludzkim na udawanym zegarze: gotowe
    zlecenie 1 przechodzi bez przerw (#834), a zlecenia 2 i 3 dokańcza z przerwami przed zapisami."""

    orders = _resumed_orders()
    original = write_collective_file(tmp_path / "plik", orders)
    whole, resumed = (tmp_path / name / PERIOD / original.name for name in ("pelny", "przerwany"))
    for copy_of in (whole, resumed):
        copy_of.parent.mkdir(parents=True)
        shutil.copy2(original, copy_of)
    def in_efenix() -> list[AtrapaOrder]:
        return [order.in_efenix(f"99{index}") for index, order in enumerate(orders)]

    with atrapa_efenix(in_efenix()) as atrapa:
        once = _run(whole, page, atrapa.url)
        priced_once = (_pricing(atrapa), atrapa.status_changes())
    clock = _FakeTime()
    with atrapa_efenix(in_efenix(), expire_after=expire_after, clock=clock) as atrapa:
        stopped_tab = _next_tab(page)
        stopped = _run(resumed, stopped_tab, atrapa.url)
        again_tab = _next_tab(stopped_tab)
        atrapa.log_in()
        since = len(atrapa.requests)
        again = _run(resumed, again_tab, atrapa.url, pace=Pace(sleep=clock.pause, clock=clock), clock=clock)
        priced_again = (_pricing(atrapa), atrapa.status_changes())
        searched_again, written_again = (
            _window_moments(atrapa, SEARCH, since),
            [at for path in (SET_DATE, LOAD_EMMETT, SAVE_QUANTITY) for at in _window_moments(atrapa, path, since)],
        )

    assert isinstance(stopped.ending, Stop)
    message = stopped.ending.message
    assert (_stop(stopped), stopped.ending.stop_kind, message.what.startswith("efenix wylogował")) == ("EFENIX_WYLOGOWANY", "for_tata", True)
    assert (once.result, again.result, _figures(again)) == ("OK", "OK", _figures_of(3, 3))
    assert priced_again == priced_once
    assert [emmett_loads for _quantities, _day, emmett_loads in priced_again[0].values()] == [1, 1, 1]
    assert (_parts(resumed), _marked(resumed)) == (_parts(whole), [18, 19, 20])
    # Zlecenie 1 jest już gotowe: jego szukanie, otwarcie i szukanie zlecenia 2 są w chwili 0, a każdy zapis zleceń 2 i 3
    # czeka na przerwę, więc szukanie zlecenia 3 jest po przerwie.
    assert (searched_again[:2], searched_again[2] > 0, 0 in written_again) == ([0, 0], True, False)


# Żądania pełnej Wyceny w efenix dwóch zleceń z pustą wyceną po kolei (``_resumed_orders`` bez trzeciego). Okno otwiera
# stronę zlecenia, ustawia datę wykonania i otwiera stronę jeszcze raz, pyta o propozycję Emmetta i ładuje ją do zlecenia, a
# skrypt strony ją przeładowuje, potem zapisuje dwie ilości. Pierwsze zlecenie szuka na liście otwartej przy starcie, a
# kolejne na liście otwartej od nowa, która sama szuka jeszcze raz poprzedniego numeru, zanim okno wyśle swoje szukanie.
_ONE_ORDER = (
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", SET_DATE),
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", FILL_EMMETT), ("POST", LOAD_EMMETT),
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", SAVE_QUANTITY), ("POST", SAVE_QUANTITY),
)
WHOLE_RUN = (
    ("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), *_ONE_ORDER,
    ("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), ("POST", SEARCH), *_ONE_ORDER,
)
# Przegląd w CI: zerwane połączenie od każdego żądania, a pozostałe tryby od pierwszego szukania, pierwszej propozycji
# Emmetta i pierwszego zapisu ilości, odpowiedzi, których treść czyta samo okno. Pełny przegląd, każde żądanie w każdym trybie (116 przypadków, ok. 8 min
# procesora), uruchamiasz przed zmianą okna efenix albo odcięcia Atrapy efenix:
# ``PELNY_PRZEGLAD_EFENIX=1 .venv/bin/python -m pytest tests/test_wycena_efenix.py -n 8 -k od_kazdego_zadania``.
_READ_BY_WINDOW = tuple(WHOLE_RUN.index(("POST", path)) for path in (SEARCH, FILL_EMMETT, SAVE_QUANTITY))
SWEEP = [
    pytest.param(first, outage, id=f"{first:02d}-{path.replace('/', '-')}-{outage.name}")
    for first, (_method, path) in enumerate(WHOLE_RUN)
    for outage in Outage
    if os.environ.get("PELNY_PRZEGLAD_EFENIX") == "1" or outage is Outage.CUT or first in _READ_BY_WINDOW
]


@dataclass(frozen=True)
class _WholeRun:
    """Jeden przebieg Wyceny w efenix bez przerwy: Plik zbiorczy przed nim (``original``) i po nim (``source``) oraz stan
    wyceny Atrapy efenix po nim."""

    original: Path
    source: Path
    pricing: dict[str, tuple[dict[str, int], date | None, int]]


def _two_orders() -> list[Order]:
    return _resumed_orders()[:2]


def _two_in_efenix() -> list[AtrapaOrder]:
    return [order.in_efenix(f"99{index}") for index, order in enumerate(_two_orders())]


@pytest.fixture(scope="module")
def whole_run(tmp_path_factory: pytest.TempPathFactory, browser: Browser) -> _WholeRun:
    """Przebieg bez przerwy, z którym przegląd porównuje ponowne uruchomienie; wysyła dokładnie żądania ``WHOLE_RUN``."""

    root = tmp_path_factory.mktemp("jeden-przebieg")
    original = write_collective_file(root / "plik", _two_orders())
    source = root / "pelny" / PERIOD / original.name
    source.parent.mkdir(parents=True)
    shutil.copy2(original, source)
    with atrapa_efenix(_two_in_efenix()) as atrapa, page_of(browser) as window:
        once = _run(source, window, atrapa.url)
        requested, pricing, status_changes = atrapa.requested(), _pricing(atrapa), atrapa.status_changes()
    assert (once.result, _figures(once), requested, status_changes) == ("OK", _figures_of(2, 2), list(WHOLE_RUN), 0)
    return _WholeRun(original, source, pricing)


@pytest.mark.parametrize(("first", "outage"), SWEEP)
def test_odciecie_efenix_od_kazdego_zadania_wyceny_to_jedno_zatrzymanie_okna_a_ponowne_uruchomienie_konczy_jak_jeden_przebieg(
    tmp_path: Path, browser: Browser, whole_run: _WholeRun, outage: Outage, first: int
) -> None:
    """Sieć zrywa każde żądanie od żądania ``first`` pełnej Wyceny (także w połowie odpowiedzi), odpowiedź staje w połowie
    albo efenix odpowiada wolniej niż czas okna (tu 3 s), aż połączenie wróci. Wycena nigdy nie wisi i nie kończy się
    nieoczekiwanym błędem: lista zleceń, której okno nie otworzyło przy starcie, to „Nie udało się otworzyć efenix” dla
    taty, a każde późniejsze odcięcie to jedno Zatrzymanie okna do Maksa, z Diagnozą i Zgłoszeniem, bez zgadywania
    przyczyny. Logi Uruchomienia mają przyczynę techniczną (przy błędzie przeglądarki z nazwanym działaniem), wiersz
    zlecenia, przy którym okno stanęło, z jego miejscem w przebiegu i działaniem, które się nie udało, oraz ślad każdego
    zlecenia przed nim. Komunikat, że w efenix nic się nie zmieniło, mówi prawdę. Ponowne uruchomienie po powrocie połączenia, w
    nowym oknie efenix jak u taty, kończy się zawsze tym samym stanem efenix i Pliku zbiorczego co jeden przebieg bez
    przerwy, także po odcięciu między „Załaduj do zlecenia” a odczytem przeładowanej strony (dawniej wyjątek #774) i po
    zerwanym zapisie ilości (dawniej #864): zlecenie z Wyceną Emmetta albo z częścią ilości proces dokańcza do pliku bez
    ponownego ładowania Emmetta (ADR 0026)."""

    resumed = tmp_path / PERIOD / whole_run.original.name
    resumed.parent.mkdir(parents=True)
    shutil.copy2(whole_run.original, resumed)
    with atrapa_efenix(_two_in_efenix(), outage_from=(outage, first)) as atrapa:
        untouched = _pricing(atrapa)
        with page_of(browser) as window:
            stopped = _run(resumed, window, atrapa.url, timeout_ms=3_000)
        after_stop = _pricing(atrapa)
        atrapa.reconnect()
        with page_of(browser) as window:
            again = _run(resumed, window, atrapa.url)
        priced_again, status_changes = _pricing(atrapa), atrapa.status_changes()

    assert isinstance(stopped.ending, Stop), _ending(stopped)
    # Lista zleceń przy starcie to żądania 0 (strona) i 1 (jej skrypt): bez strony okno nie otworzyło efenix, a bez skryptu
    # otwarcie skończyło się albo nie, zależnie od tego, czy przeglądarka czekała na skrypt do końca czasu okna.
    not_opened, window_stop = ("EFENIX_NIEDOSTEPNY", "for_tata"), ("EFENIX_OKNO_ZATRZYMANE", "for_maks")
    allowed = [not_opened] if first == 0 else [not_opened, window_stop] if first == 1 else [window_stop]
    assert (stopped.ending.message.code, stopped.ending.stop_kind) in allowed
    facts = stopped.ending.facts
    assert isinstance(facts, PricingStopped)
    assert not isinstance(facts.cause, BrowserFailure) or facts.cause.operation is not None, facts.cause
    if WHOLE_RUN[first] == ("POST", FILL_EMMETT) and outage in (Outage.CUT, Outage.TORN):
        # Skrypt efenix pokazuje okno Emmetta także po zerwanej propozycji (``page_order_edit.js``), więc okno dochodzi do
        # „Załaduj do zlecenia” i staje na jego odpowiedzi, a nie na oknie Emmetta, które się nie pokazało.
        assert facts.part is PagePart.EMMETT and isinstance(facts.cause, BrowserFailure), (facts.part, facts.cause)
        assert facts.cause.operation is Operation.ANSWER, facts.cause
    # Lista zleceń drugiego zlecenia to żądanie 14: odcięcie przed nim zatrzymuje okno przy zleceniu 1 (wiersz 18).
    early: dict[int, list[int | None]] = {0: [None], 1: [None, 18]}
    rows = early.get(first, [18] if first < WHOLE_RUN.index(("GET", LIST_PAGE), 1) else [19])
    at = facts.stopped_at
    assert (None if at is None else at.row) in rows, (at, rows)
    if at is not None:
        assert (at.place, at.total, at.failed is not None) == (at.row - 17, 2, True), at
    assert [result.order.row for result in facts.summary.results] == list(range(18, 18 if at is None else at.row))
    assert _kept(stopped) or after_stop == untouched, (after_stop, untouched)
    assert status_changes == 0
    assert (_figures(again), _errors(again), priced_again) == (_figures_of(2, 2), [], whole_run.pricing)
    assert (_parts(resumed), _marked(resumed)) == (_parts(whole_run.source), [18, 19])


def test_przerwanie_po_zaladuj_do_zlecenia_przed_odczytem_wyceny_emmetta_ponowne_uruchomienie_dokancza_bez_ponownego_emmetta(
    tmp_path: Path, page: Page
) -> None:
    """Wylogowanie przy przeładowaniu strony zlecenia 2 po „Załaduj do zlecenia”: efenix ma samą Wycenę Emmetta, której
    narzędzie nie odczytało (kształt 46 zleceń z runu 4.11). Ponowne uruchomienie widzi zlecenie z ilościami, więc nie
    ładuje Emmetta drugi raz, tylko dopisuje ilości z pliku: wszystkie trzy zlecenia kończą się jak w jednym przebiegu."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    # Szóste otwarcie strony zlecenia to przeładowanie po Wycenie Emmetta zlecenia 2 (każde zlecenie otwiera ją trzy razy).
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=(ORDER_PAGE, 5)) as atrapa:
        stopped = _run(source, page, atrapa.url)
        left = _pricing(atrapa)["9902"]
        atrapa.log_in()
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)

    filled = {"012": 1, "019": 2, "015": 1}
    assert (_stop(stopped), left) == ("EFENIX_WYLOGOWANY", ({"012": 1}, date(2026, 9, 2), 1))
    assert (_figures(again), _errors(again)) == (_figures_of(3, 3), [])
    assert pricing == {f"990{index}": (filled, date(2026, 9, index), 1) for index in (1, 2, 3)}
    assert _marked(source) == [18, 19, 20]


# Ceny Atrapy, w których pozycja T (019) kosztuje 0: Wycena Emmetta z samym T daje stronę z ilością i kwotą 0.
_T_FOR_FREE = {**PRICES, "019": Decimal("0.00")}


@pytest.mark.parametrize(
    ("refusal", "code", "cause", "prices"),
    [
        pytest.param(EmmettRefusal.FORBIDDEN, "EFENIX_OKNO_ZATRZYMANE", HttpStatus(403), PRICES, id="403-bez-zaladowania"),
        pytest.param(EmmettRefusal.SERVER_ERROR, "EFENIX_OKNO_ZATRZYMANE", HttpStatus(500), PRICES, id="500-po-zaladowaniu"),
        pytest.param(
            EmmettRefusal.ELSEWHERE, "EFENIX_OKNO_ZATRZYMANE", OtherShape(Shape.ANSWER_REDIRECT), PRICES, id="przekierowanie-na-liste"
        ),
        pytest.param(EmmettRefusal.LOGGED_OUT, "EFENIX_WYLOGOWANY", LoginSign.REDIRECT, PRICES, id="przekierowanie-na-logowanie"),
        pytest.param(
            EmmettRefusal.NOK, "EFENIX_OKNO_ZATRZYMANE", OtherShape(Shape.EMMETT_NOT_LOADED), PRICES, id="result-nok"
        ),
        pytest.param(
            EmmettRefusal.OTHER, "EFENIX_OKNO_ZATRZYMANE", OtherShape(Shape.EMMETT_NOT_LOADED), PRICES, id="200-inna-tresc"
        ),
        pytest.param(
            EmmettRefusal.OTHER,
            "EFENIX_OKNO_ZATRZYMANE",
            OtherShape(Shape.EMMETT_NOT_LOADED),
            _T_FOR_FREE,
            id="200-inna-tresc-a-po-niej-wycena-emmetta-z-kwota-0",
        ),
    ],
)
def test_odmowa_zaladuj_do_zlecenia_zatrzymuje_wycene_bez_znacznika_i_sladu_a_ponowne_uruchomienie_daje_ostrzezenie_emmetta(
    tmp_path: Path, page: Page, refusal: EmmettRefusal, code: str, cause: WindowCause, prices: dict[str, Decimal]
) -> None:
    """Zlecenie 2 ma pustą wycenę i Emmetta, który ma w T więcej niż plik, a efenix odmawia jego „Załaduj do zlecenia”;
    skrypt strony i tak ją przeładowuje, a strona bez Wyceny Emmetta wygląda jak pusta Wycena Emmetta (#877).

    Odmowa to Zatrzymanie okna z przyczyną z odpowiedzi efenix, a odmowa odpowiedzią 2xx (``result: nok`` w ważnej
    sesji, inna treść, #889) z przeładowanej strony bez wyceny, choć okno Emmetta pokazało propozycję: zlecenie 2 nie
    dostaje ilości z pliku ani Znacznika efenix. Ponowne uruchomienie po odmowie bez załadowania ładuje Emmetta, a po 500,
    po którym efenix ma już Emmetta, dokańcza jego wycenę bez ponownego ładowania: w obu przypadkach zlecenie 2 kończy
    się jak jeden przebieg, z O z pliku, T od Emmetta i Ostrzeżeniem Emmetta. Wycenę Emmetta Wycena poznaje po ilości na
    stronie, a nie po kwocie, więc także wtedy, gdy T kosztuje 0, a strona po niej ma ilość i kwotę 0.

    Logi Zatrzymania mają przy zleceniu 2 udane działania okna aż do Wyceny Emmetta, a Wycenę Emmetta jako działanie,
    które się nie udało, także przy odmowie odpowiedzią 2xx.
    """

    orders = [
        Order("#9701", day=date(2026, 9, 1), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9702", day=date(2026, 9, 2), cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"019": 5}),
    ]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [orders[0].in_efenix("971"), replace(orders[1].in_efenix("972"), emmett_refusal=refusal)]
    with atrapa_efenix(in_efenix, prices=prices) as atrapa:
        stopped = _run(source, page, atrapa.url)
        refused = _pricing(atrapa)["9702"]
        marked = _marked(source)
        atrapa.log_in()
        atrapa.edit("9702", lambda order: setattr(order, "emmett_refusal", None))
        again = _run(source, _next_tab(page), atrapa.url)
        resumed = _pricing(atrapa)["9702"]

    loaded = refusal is EmmettRefusal.SERVER_ERROR
    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    facts = stopped.ending.facts
    assert (_stop(stopped), _kept(stopped), facts.part, facts.cause) == (code, True, PagePart.EMMETT, cause)
    assert facts.stopped_at is not None and facts.stopped_at.failed is not None, facts.stopped_at
    assert ([step.action for step in facts.stopped_at.steps], facts.stopped_at.failed.action) == (
        ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia"],
        "Wycena Emmetta",
    )
    assert (refused, marked) == (({"019": 5} if loaded else {}, date(2026, 9, 2), int(loaded)), [18])
    assert (_errors(again), _marked(source)) == ([("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 19")], [18])
    assert resumed == ({"012": 1, "019": 5}, date(2026, 9, 2), 1)


def test_odmowa_zaladuj_do_zlecenia_po_propozycji_emmetta_w_polach_bez_tekstu_zatrzymuje_wycene_bez_znacznika(
    tmp_path: Path, page: Page
) -> None:
    """Okno Emmetta pokazuje propozycję tylko w polach, bez tekstu (postaci propozycji efenix nikt nie zmierzył), a efenix
    odmawia „Załaduj do zlecenia” odpowiedzią 200 z inną treścią (#889). Pole to też propozycja, więc strona bez ilości po
    przeładowaniu to Zatrzymanie okna, a nie pusta Wycena Emmetta: zlecenie nie dostaje ilości z pliku ani Znacznika."""

    order = Order("#9711", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"019": 5})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("9711"), emmett_refusal=EmmettRefusal.OTHER, emmett_in_fields=True)
    with atrapa_efenix([in_efenix]) as atrapa:
        stopped = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    assert (_stop(stopped), stopped.ending.facts.cause) == ("EFENIX_OKNO_ZATRZYMANE", OtherShape(Shape.EMMETT_NOT_LOADED))
    assert (pricing, _marked(source)) == ({"9711": ({}, DAY, 0)}, [])


def test_odmowa_zaladuj_do_zlecenia_na_stronie_bez_ilosci_z_kwota_z_ceny_wpisywanej_zatrzymuje_wycene_bez_ilosci_z_pliku(
    tmp_path: Path, page: Page
) -> None:
    """Strona zlecenia nie ma żadnej ilości, ale ma kwotę końcową różną od 0 z karty ceny wpisywanej (bez pola Ilość),
    więc proces ładuje do niej Wycenę Emmetta (ADR 0026), a efenix odmawia „Załaduj do zlecenia” odpowiedzią 200 z inną
    treścią (#889). Przeładowana strona dalej nie ma żadnej ilości, choć okno Emmetta pokazało propozycję, więc to
    Zatrzymanie okna, a nie Wycena Emmetta: zlecenie nie dostaje ilości z pliku ani Znacznika efenix."""

    order = Order("#9731", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"019": 5})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("9731"), quantities={"045": 5}, emmett_refusal=EmmettRefusal.OTHER)
    with atrapa_efenix([in_efenix]) as atrapa:
        stopped = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    facts = stopped.ending.facts
    assert (_stop(stopped), facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        PagePart.EMMETT,
        OtherShape(Shape.EMMETT_NOT_LOADED),
    )
    assert (pricing, _marked(source)) == ({"9731": ({"045": 5}, DAY, 0)}, [])


def test_odmowa_zaladuj_do_zlecenia_w_tempie_ludzkim_jako_pierwsza_zmiana_zatrzymuje_wycene_z_komunikatem_ze_wycena_mogla_sie_zmienic(
    tmp_path: Path, page: Page
) -> None:
    """Centrum rozliczeń uruchamia Wycenę w efenix w tempie ludzkim (``efenix_pace``), a efenix odmawia „Załaduj do
    zlecenia” odpowiedzią 200 z inną treścią (#889). Przeładowana strona nie ma żadnej ilości, choć okno Emmetta pokazało
    propozycję, więc i w tempie ludzkim to Zatrzymanie okna, a nie pusta Wycena Emmetta: zlecenie nie dostaje ilości z
    pliku ani Znacznika efenix.

    Zlecenie ma już datę wykonania, więc „Załaduj do zlecenia” to pierwsza zmiana, którą okno wysłało do efenix, a w
    śladzie nie ma żadnego udanego zapisu. Okno kliknęło ją jednak przed Zatrzymaniem, więc Komunikat mówi, że wycena
    sprzed Zatrzymania została w efenix, a nie, że nic się nie zmieniło."""

    order = Order("#9741", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"019": 5})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("9741"), execution_date=DAY, emmett_refusal=EmmettRefusal.OTHER)
    clock = _FakeTime()
    with atrapa_efenix([in_efenix], clock=clock) as atrapa:
        stopped = _run(source, page, atrapa.url, pace=Pace(sleep=clock.pause, clock=clock), clock=clock)
        pricing = _pricing(atrapa)

    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    facts = stopped.ending.facts
    assert facts.stopped_at is not None, facts
    assert (_stop(stopped), facts.part, facts.cause, [step.action for step in facts.stopped_at.steps], _kept(stopped)) == (
        "EFENIX_OKNO_ZATRZYMANE",
        PagePart.EMMETT,
        OtherShape(Shape.EMMETT_NOT_LOADED),
        ["szukanie", "otwarcie zlecenia"],
        True,
    )
    assert (pricing, _marked(source)) == ({"9741": ({}, DAY, 0)}, [])



@pytest.mark.parametrize("failure", list(ProposalFailure), ids=lambda failure: failure.name)
def test_propozycja_emmetta_ktora_padla_zostawia_okno_emmetta_puste_jak_w_efenix_a_zaladuj_do_zlecenia_i_tak_laduje(
    tmp_path: Path, page: Page, failure: ProposalFailure
) -> None:
    """Propozycja Emmetta (``action_fill_emmett.php``) pada błędem serwera, zerwaną treścią albo zerwanym połączeniem, a
    skrypt efenix i tak pokazuje okno Emmetta, puste. „Załaduj do zlecenia” ładuje Wycenę Emmetta, bo efenix bierze ją u
    siebie, a nie z okna, więc strona z kwotą różną od 0 kończy zlecenie jak bez awarii. Przeglądarka dostaje propozycję
    tak, jak padła: 500, nagłówki 200 i zerwaną treść, albo nic (bez tego test zerwanej treści sprawdzałby całą)."""

    order = Order("#9721", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("9721"), emmett_proposal_failure=failure)
    proposal: list[int | str] = []
    page.on("response", lambda response: proposal.append(response.status) if response.url.endswith(FILL_EMMETT) else None)
    page.on("requestfailed", lambda request: proposal.append("zerwana") if request.url.endswith(FILL_EMMETT) else None)
    with atrapa_efenix([in_efenix]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert proposal == {ProposalFailure.SERVER_ERROR: [500], ProposalFailure.TORN: [200, "zerwana"], ProposalFailure.CUT: ["zerwana"]}[failure]
    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (pricing, _marked(source)) == ({"9721": ({"012": 1, "019": 2}, DAY, 1)}, [18])


@pytest.mark.parametrize("failure", list(ProposalFailure), ids=lambda failure: failure.name)
def test_propozycja_emmetta_ktora_padla_a_potem_odmowa_zaladuj_do_zlecenia_2xx_zatrzymuje_wycene_bez_ilosci_i_znacznika(
    tmp_path: Path, page: Page, failure: ProposalFailure
) -> None:
    """Propozycja Emmetta pada (błąd serwera, zerwana treść, zerwane połączenie), więc okno Emmetta jest puste jak przy
    Emmetcie, który nic nie zaproponował, a efenix odmawia „Załaduj do zlecenia” odpowiedzią 2xx i nic nie ładuje (#908,
    dwie awarie naraz). Pustą Wyceną Emmetta jest strona bez ilości tylko po propozycji, która przyszła cała ze statusem
    2xx, więc ta strona to Zatrzymanie okna (``Shape.EMMETT_NOT_LOADED``): zlecenie nie dostaje ilości z pliku ani
    Znacznika efenix i nie jest gotowe bez Wyceny Emmetta (jak #877, #889)."""

    order = Order("#9721", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("9721"), emmett_proposal_failure=failure, emmett_refusal=EmmettRefusal.OTHER)
    with atrapa_efenix([in_efenix]) as atrapa:
        stopped = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    facts = stopped.ending.facts
    assert (_stop(stopped), facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        PagePart.EMMETT,
        OtherShape(Shape.EMMETT_NOT_LOADED),
    )
    assert (pricing, _marked(source)) == ({"9721": ({}, DAY, 0)}, [])


@dataclass
class _ReloadFirst:
    """Karta ``page``, w której każdy odczyt treści odpowiedzi „Załaduj do zlecenia” czeka, aż skrypt efenix przeładuje
    stronę: tak wypada wyścig na wolnym komputerze, bo Chromium porzuca wtedy treść odpowiedzi poprzedniego dokumentu."""

    page: Page
    loads: int = 0
    loads_at_click: int = 0

    def __post_init__(self) -> None:
        self.page.on("load", self._loaded)
        self.page.on("request", self._requested)

    def _loaded(self, _page: Page) -> None:
        self.loads += 1

    def _requested(self, request: PlaywrightRequest) -> None:
        if request.url.endswith("/" + LOAD_EMMETT):
            self.loads_at_click = self.loads

    def late(self, read: Callable[[PlaywrightResponse], _T]) -> Callable[[PlaywrightResponse], _T]:
        def after_reload(response: PlaywrightResponse) -> _T:
            while response.url.endswith("/" + LOAD_EMMETT) and self.loads <= self.loads_at_click:
                self.page.wait_for_event("load")
            return read(response)

        return after_reload


def test_przeladowanie_strony_przed_odczytem_odpowiedzi_zaladuj_do_zlecenia_konczy_wycene_jak_jeden_przebieg(
    tmp_path: Path, page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skrypt efenix przeładowuje stronę po „Załaduj do zlecenia”, zanim okno przeczyta treść odpowiedzi (#895: Windows w
    CI, wolny komputer taty). Test wymusza tę kolejność dla każdego odczytu treści odpowiedzi ``action_load_emmett.php``.

    Bez żadnej awarii efenix Wycena kończy się jak jeden przebieg: każde zlecenie ma Wycenę Emmetta raz, ilości pliku w
    pozycjach pustych u Emmetta i Znacznik efenix, a nie Zatrzymanie po Emmetcie.
    """

    reload_first = _ReloadFirst(page)
    monkeypatch.setattr(PlaywrightResponse, "text", reload_first.late(PlaywrightResponse.text))
    monkeypatch.setattr(PlaywrightResponse, "body", reload_first.late(PlaywrightResponse.body))
    orders = [
        Order("#9801", day=date(2026, 9, 1), cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1}),
        Order("#9802", day=date(2026, 9, 2), cells={"O": 1, "Z": 1}, amount=_au({"012": 1, "010": 1}), emmett={"010": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix([orders[0].in_efenix("981"), orders[1].in_efenix("982")]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 2), []), _ending(outcome)
    assert pricing == {
        "9801": ({"012": 1, "019": 2}, date(2026, 9, 1), 1),
        "9802": ({"010": 1, "012": 1}, date(2026, 9, 2), 1),
    }
    assert _marked(source) == [18, 19]


@pytest.mark.parametrize(
    "expire_after",
    [
        # „Załaduj do zlecenia” trafia na wygasłą sesję, więc efenix Emmetta nie ładuje.
        pytest.param((LOAD_EMMETT, 0), id="przy-zaladuj-do-zlecenia"),
        # Drugie otwarcie strony zlecenia to sprawdzenie daty wykonania, przed przyciskiem Emmetta.
        pytest.param((ORDER_PAGE, 1), id="po-dacie-przed-emmettem"),
    ],
)
def test_przerwanie_przed_wycena_emmetta_a_potem_wycena_zaczeta_przez_tate_ponowne_uruchomienie_dokancza_bez_emmetta(
    tmp_path: Path, page: Page, expire_after: tuple[str, int]
) -> None:
    """Emmett dałby T (019) 5, a plik ma 2. Po Zatrzymaniu tata loguje się i sam, bez Emmetta, wpisuje O (012) 1 jak w
    pliku: zlecenie ma ilość, więc ponowne uruchomienie nie ładuje Emmetta, który wyczyściłby wycenę taty, tylko dopisuje T
    z pliku."""

    filled = {"012": 1, "019": 2}
    order = Order("#5201", cells={"O": 1, "T": 2}, amount=_au(filled), emmett={"012": 1, "019": 5})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("921")], expire_after=expire_after) as atrapa:
        stopped = _run(source, page, atrapa.url)
        atrapa.log_in()
        atrapa.edit("5201", lambda edited: edited.quantities.update({"012": 1}))
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)

    assert (_stop(stopped), again.result, _errors(again)) == ("EFENIX_WYLOGOWANY", "OK", [])
    assert (pricing, _marked(source)) == ({"5201": (filled, DAY, 0)}, [18])


@pytest.mark.parametrize(
    ("amount", "errors"),
    [
        pytest.param(_au({"012": 1, "019": 2}), [], id="gotowe"),
        pytest.param(_au({"012": 1, "019": 2}) + 1, [("EFENIX_INNA_KWOTA", "wiersz 18")], id="błąd-kwoty"),
    ],
)
def test_ilosc_ktora_tata_usunal_w_efenix_po_skonczonym_zleceniu_ponowne_uruchomienie_wpisuje_z_pliku_z_powrotem(
    tmp_path: Path, page: Page, amount: float, errors: list[tuple[str, str]]
) -> None:
    """Proces załadował Emmetta (O), dopisał T (019) i skończył zlecenie; tata usuwa potem w efenix T. Prawdziwy jest
    Plik zbiorczy, a zmiana taty w dół nie jest chroniona (ADR 0026), więc ponowne uruchomienie wpisuje T z pliku z
    powrotem i kończy zlecenie tym samym wynikiem co pierwsze."""

    order = Order("#5301", cells={"O": 1, "T": 2}, amount=amount, emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("931")]) as atrapa:
        priced = _run(source, page, atrapa.url)
        atrapa.edit("5301", lambda edited: edited.quantities.pop("019"))
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)

    assert (_errors(priced), _errors(again)) == (errors, errors)
    assert pricing == {"5301": ({"012": 1, "019": 2}, DAY, 1)}


def _interrupted(source: Path, atrapa: AtrapaEfenix, page: Page) -> None:
    """Przebieg ``_resumed_orders`` przerwany wylogowaniem w połowie ilości zlecenia 2 (wiersz 19); tata loguje się z powrotem."""

    assert _stop(_run(source, page, atrapa.url)) == "EFENIX_WYLOGOWANY"
    atrapa.log_in()


# Zlecenie 1 ``_resumed_orders`` ma dwa zapisy ilości, więc czwarty zapis wylogowuje w połowie ilości zlecenia 2.
_IN_HALF_OF_ORDER_2 = (SAVE_QUANTITY, 3)


@pytest.mark.parametrize(
    ("change", "after", "errors"),
    [
        pytest.param(
            lambda order: order.quantities.update({"012": 3}),
            {"012": 3, "015": 1, "019": 2},
            [("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 19")],
            id="większa-ilość-emmetta",
        ),
        pytest.param(lambda order: order.quantities.pop("012"), {"012": 1, "015": 1, "019": 2}, [], id="usunięta-ilość-emmetta"),
        # T (019) jest pusta u Emmetta, a plik ma 2.
        pytest.param(
            lambda order: order.quantities.update({"019": 5}),
            {"012": 1, "015": 1, "019": 5},
            [("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 19")],
            id="większa-ilość-w-pozycji-pustej-u-emmetta",
        ),
        pytest.param(
            lambda order: order.quantities.update({"019": 2}), {"012": 1, "015": 1, "019": 2}, [], id="ilość-pliku-w-pozycji-pustej-u-emmetta"
        ),
    ],
)
def test_przerwana_wycena_ktora_tata_zmienil_potem_w_efenix_ponowne_uruchomienie_dokancza_tylko_w_gore(
    tmp_path: Path, page: Page, change: Callable[[AtrapaOrder], object], after: dict[str, int], errors: list[tuple[str, str]]
) -> None:
    """Po przerwaniu zlecenie 2 ma O (012) od Emmetta i AG (015) od procesu. Tata zmienia albo usuwa w efenix ilość
    Emmetta albo sam wpisuje T: ponowne uruchomienie wpisuje ilość z pliku w każdej pozycji, w której efenix ma mniej, a
    pozycji, w której ma więcej, nie zmienia i daje Ostrzeżenie Emmetta."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=_IN_HALF_OF_ORDER_2) as atrapa:
        _interrupted(source, atrapa, page)
        atrapa.edit("9902", change)
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)["9902"]

    assert (_figures(again), _errors(again)) == (_figures_of(3, 3 - len(errors), warnings=len(errors)), errors)
    assert (pricing, _marked(source)) == ((after, date(2026, 9, 2), 1), [18, 19, 20] if not errors else [18, 20])


def test_przerwana_wycena_po_zmianie_pliku_przez_tate_ponowne_uruchomienie_dokancza_do_nowego_pliku(tmp_path: Path, page: Page) -> None:
    """Emmett wpisał w zleceniu 2 O (012) 1, proces dopisał AG, a wylogowanie przerwało go przed T. Tata zmienia w Pliku
    zbiorczym O tego zlecenia na 2: ponowne uruchomienie wpisuje O z pliku w miejsce ilości Emmetta i dopisuje T."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    filled = {"012": 2, "019": 2, "015": 1}
    changed = replace(orders[1], cells={**orders[1].cells, "O": 2}, amount=_au(filled))
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=_IN_HALF_OF_ORDER_2) as atrapa:
        _interrupted(source, atrapa, page)
        write_collective_file(tmp_path, [orders[0], changed, orders[2]])
        again = _run(source, _next_tab(page), atrapa.url)
        after = _pricing(atrapa)["9902"]

    assert (again.result, _figures(again), _errors(again)) == ("OK", _figures_of(3, 3), [])
    assert after == (filled, date(2026, 9, 2), 1)


def test_po_ostrzezeniu_emmetta_tata_poprawia_plik_a_ponowne_uruchomienie_stawia_znacznik_bez_zmian_w_efenix(
    tmp_path: Path, page: Page
) -> None:
    """Emmett wpisał O (012) 2, a plik ma 1: O zostaje, T (019) jest dopisane, a zlecenie to Ostrzeżenie Emmetta. Tata
    przyznaje rację efenix i zmienia w Pliku zbiorczym O na 2: ponowne uruchomienie niczego nie wpisuje i stawia
    Znacznik efenix."""

    order = Order("#9601", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 2})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("961")]) as atrapa:
        first = _run(source, page, atrapa.url)
        warned = _pricing(atrapa)
        write_collective_file(tmp_path, [replace(order, cells={"O": 2, "T": 2}, amount=_au({"012": 2, "019": 2}))])
        since = len(atrapa.requested())
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)
        requested_again = atrapa.requested()[since:]

    assert [_errors(outcome) for outcome in (first, again)] == [[("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 18")], []]
    assert (warned, pricing, _marked(source)) == ({"9601": ({"012": 2, "019": 2}, DAY, 1)},) * 2 + ([18],)
    assert set(requested_again) <= READING


# --- Okno efenix taty: logowanie i przeglądarka (#750) ------------------------------------------------------------------

LOGIN_STEP = SavingStep("Zaloguj się w oknie efenix", None, 0, 0)


def test_okno_na_stronie_logowania_czeka_az_tata_sie_zaloguje_a_czas_czekania_nie_liczy_sie_do_czasow_uruchomienia(
    tmp_path: Path, page: Page
) -> None:
    """Tata loguje się 10 minut; każdy inny krok Zapisywania trwa 2 s. ``Czas uruchomienia``, czas Zapisywania i rekord
    metryk mają tylko te 2 s każdego kroku, czas uruchomienia na żywo przy każdym kroku postępu też nie liczy logowania, a
    postęp idzie po Wykonawcach alfabetycznie, potem Znaczniki efenix."""

    # Zegar, który przesuwa tylko tata z testu (ManualClock z tests/fixtures/clock.py wciągnąłby ten plik do bramki C).
    now = [0.0]
    orders = [
        Order("#5402", worker="beata.testowa", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#5401", cells={"T": 1}, amount=_au({"019": 1}), quantities={"019": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    metrics = tmp_path / "metryki.jsonl"
    steps: list[SavingStep] = []
    reached_ms: list[int] = []
    with atrapa_efenix([orders[0].in_efenix("541"), orders[1].in_efenix("542")]) as atrapa:
        atrapa.expire_session()

        class LoggingIn(Tata):
            def show_progress(self, snapshot: ProgressSnapshot) -> None:
                if snapshot.step is None or (steps and steps[-1] == snapshot.step):
                    return
                steps.append(snapshot.step)
                reached_ms.append(snapshot.total_elapsed_ms)
                if snapshot.step == LOGIN_STEP:
                    now[0] += 600
                    atrapa.log_in()
                else:
                    now[0] += 2

        outcome = run_process(
            efenix_process.PROCESS,
            EfenixInputs(
                source,
                lambda login: efenix_browser.window(page, atrapa.url, login=login),
                pace=None,
                clock=lambda: now[0],
            ),
            LoggingIn(),
            view=lambda _inputs, summary: summary,
            metrics_path=metrics,
            clock=lambda: now[0],
        )
    [record] = [json.loads(line) for line in metrics.read_text(encoding="utf-8").splitlines()]

    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(2, 2))
    assert steps == [
        LOGIN_STEP,
        SavingStep("Zlecenia", "adrian.testowy", 0, 2),
        SavingStep("Zlecenia", "beata.testowa", 1, 2),
        SavingStep("Znaczniki efenix w Pliku zbiorczym", None, 0, 0),
    ]
    assert (outcome.total_duration_ms, outcome.progress.phase_durations_ms[ProgressPhase.SAVING]) == (6000, 6000)
    assert reached_ms == [0, 0, 2000, 4000]
    assert (record["total_duration_ms"], record["phase_durations_ms"][ProgressPhase.SAVING]) == (6000, 6000)


def test_okno_bez_logowania_taty_i_przegladarka_ktora_nie_wystartowala_zatrzymuja_wycene_z_komunikatem(
    tmp_path: Path, page: Page
) -> None:
    """Brak logowania w czasie oczekiwania to Zatrzymanie jak po wylogowaniu, a przeglądarka, której nie ma na komputerze
    (tu kanał, którego Playwright nie zna), to Komunikat dla taty, nie nieoczekiwany wyjątek; w efenix nic się nie zmienia."""

    orders = [Order("#5501", cells={"O": 1}, amount=_au({"012": 1}))]
    with atrapa_efenix([orders[0].in_efenix("551")]) as atrapa:
        atrapa.expire_session()
        not_logged_in = _run_with(
            write_collective_file(tmp_path / "bez-logowania", orders),
            lambda login: efenix_browser.window(page, atrapa.url, login=login, login_timeout_ms=1),
        )
        # Okno ``chrome`` startuje własny Playwright, a ten wątek ma już Playwright przeglądarki testów.
        with ThreadPoolExecutor(max_workers=1) as own_thread:
            no_browser = own_thread.submit(
                _run_with,
                write_collective_file(tmp_path / "bez-chrome", orders),
                lambda login: efenix_browser.chrome(atrapa.url, tmp_path / "profil", login, channel="chrome-niezainstalowany"),
            ).result()
        requested = atrapa.requested()

    assert (_stop(not_logged_in), _stop(no_browser)) == ("EFENIX_WYLOGOWANY", "EFENIX_BRAK_PRZEGLADARKI")
    assert (_kept(not_logged_in), _kept(no_browser)) == (False, False)
    assert set(requested) <= READING | {("GET", "page_login.php")}


def test_okno_czeka_na_logowanie_taty_15_minut_a_potem_daje_wylogowanie(page: Page) -> None:
    """Domyślny limit czekania na logowanie to 15 minut: tata, który loguje się w 14. minucie i 59. sekundzie, zaczyna
    Wycenę, a bez logowania okno kończy czekanie w 15. minucie (``LoggedOut``), nie później. Czas czekania mierzy
    zegar okna, który tu przesuwa test: start w 0, potem podana minuta, a każdy następny odczyt godzinę później."""

    seen: list[float] = []

    def waiting(minutes: float, log_in: Callable[[], None] = lambda: None) -> Callable[[], float]:
        seen.clear()
        readings = iter([0.0, minutes * 60])

        def clock() -> float:
            seen.append(next(readings, 3600.0))
            if len(seen) == 2:
                log_in()
            return seen[-1]

        return clock

    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()
        with efenix_browser.window(page, atrapa.url, login=nullcontext, clock=waiting(14 + 59 / 60, atrapa.log_in)):
            logged_in = page.url
        atrapa.expire_session()
        with pytest.raises(LoggedOut), efenix_browser.window(page, atrapa.url, login=nullcontext, clock=waiting(15)):
            pass

    assert (logged_in, max(seen)) == (atrapa.url, 900.0)


def test_lista_ze_statusem_bledu_po_zalogowaniu_taty_zatrzymuje_czekanie_na_logowanie_ze_statusem_http(page: Page) -> None:
    """Tata loguje się, a lista zleceń, o którą okno pyta w sesji przeglądarki, odpowiada stroną błędu serwera: to
    Zatrzymanie okna ze statusem HTTP listy, jak lista przy starcie (#878), a nie pytanie bez końca i po limicie „tata się
    nie zalogował” (#891). Żądania listy: 1 otwarcie przy starcie, 2 karta taty po zalogowaniu, 3 pytanie okna."""

    with atrapa_efenix([], error_answer=(LIST_PAGE, 3, HTTPStatus.INTERNAL_SERVER_ERROR)) as atrapa:
        atrapa.expire_session()

        @contextmanager
        def logging_in() -> Iterator[None]:
            atrapa.log_in()
            page.goto(atrapa.url)
            yield

        with pytest.raises(UnexpectedPage) as stopped, efenix_browser.window(page, atrapa.url, login=logging_in):
            pass

    assert (stopped.value.part, stopped.value.cause) == (PagePart.LIST, HttpStatus(HTTPStatus.INTERNAL_SERVER_ERROR))


def test_czekanie_na_logowanie_pyta_efenix_najwyzej_co_login_poll_ms_takze_gdy_karta_nie_stoi_na_stronie_logowania(
    page: Page,
) -> None:
    """Tata przechodzi ze strony logowania na inną stronę, nie logując się: czekanie, aż karta zejdzie ze strony
    logowania, kończy się od razu, a okno i tak pyta efenix o listę zleceń najwyżej co ``LOGIN_POLL_MS`` (#891), aż minie
    limit czekania."""

    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()

        @contextmanager
        def walking_away() -> Iterator[None]:
            page.goto(urljoin(atrapa.url, LIST_SCRIPT))
            yield

        with pytest.raises(LoggedOut), efenix_browser.window(page, atrapa.url, login=walking_away, login_timeout_ms=500):
            pass
        # Bez otwarcia listy przy starcie.
        asked = [request.at for request in atrapa.requests if request.path == LIST_PAGE][1:]

    assert len(asked) == 2, asked
    assert asked[1] - asked[0] >= efenix_browser.LOGIN_POLL_MS / 1000


def _session_questions(atrapa: AtrapaEfenix) -> int:
    """Ile razy okno pytało efenix o listę zleceń w czasie czekania na logowanie (bez otwarcia listy przy starcie)."""

    return len([request for request in atrapa.requests if request.path == LIST_PAGE][1:])


def test_karta_na_stronie_logowania_bez_logowania_taty_pyta_efenix_o_sesje_co_login_poll_ms_az_do_limitu(page: Page) -> None:
    """Karta stoi na stronie logowania, a tata się nie loguje: okno pyta efenix o sesję co ``LOGIN_POLL_MS``, a nie raz
    na domyślny limit czasu karty, więc logowanie taty w innej karcie tej przeglądarki widzi najwyżej po
    ``LOGIN_POLL_MS``. Limit czekania półtora ``LOGIN_POLL_MS``: pytania na starcie, po ``LOGIN_POLL_MS`` i na końcu
    limitu; domyślny limit karty to dwa ``LOGIN_POLL_MS``."""

    page.set_default_timeout(2 * efenix_browser.LOGIN_POLL_MS)
    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()
        with (
            pytest.raises(LoggedOut),
            efenix_browser.window(
                page, atrapa.url, login=nullcontext, login_timeout_ms=efenix_browser.LOGIN_POLL_MS * 3 // 2
            ),
        ):
            pass
        questions = _session_questions(atrapa)

    assert questions >= 3


def test_lista_ktora_nie_odpowiada_w_czasie_czekania_na_logowanie_nie_konczy_czekania_a_po_limicie_to_wylogowanie(
    page: Page,
) -> None:
    """efenix przestaje odpowiadać, gdy okno czeka na logowanie taty: pytanie o sesję kończy się w czasie okna, okno pyta
    dalej, a po limicie czekania to Zatrzymanie jak bez logowania, nie błąd strony. Czas okna to ćwierć
    ``LOGIN_POLL_MS``, a domyślny limit karty dwa ``LOGIN_POLL_MS``, dłużej niż limit czekania."""

    page.context.set_default_timeout(2 * efenix_browser.LOGIN_POLL_MS)
    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()

        @contextmanager
        def efenix_silent() -> Iterator[None]:
            atrapa.outage = Outage.SLOW
            yield

        with (
            pytest.raises(LoggedOut),
            efenix_browser.window(
                page,
                atrapa.url,
                timeout_ms=efenix_browser.LOGIN_POLL_MS // 4,
                login=efenix_silent,
                login_timeout_ms=efenix_browser.LOGIN_POLL_MS * 3 // 2,
            ),
        ):
            pass
        questions = _session_questions(atrapa)

    assert questions >= 2


def test_profil_przegladarki_okna_efenix_lezy_w_katalogu_narzedzia_poza_gitem() -> None:
    """Katalog narzędzia leży u taty na dysku lokalnym poza OneDrive (``docs/agents/komputer-taty.md``)."""

    profile = efenix_browser.default_profile()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", str(profile / "Default" / "Cookies")], cwd=TOOL_ROOT, check=False
    )

    assert (profile.parent, ignored.returncode) == (TOOL_ROOT, 0)


def _run_with(source: Path, open_efenix: Callable[[Login], AbstractContextManager[efenix_browser.BrowserEfenix]]) -> Priced:
    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(source, open_efenix, pace=None),
        Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=source.parent.parent / "metryki.jsonl",
    )


@dataclass
class _OpensInExcelAfterChecking(Tata):
    """Tata otwiera Plik zbiorczy ``source`` w Excelu (plik blokady ``~$…``), gdy postęp pokazuje skończone Sprawdzanie."""

    source: Path = Path()

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        if snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.COMPLETED:
            excel_lock_file(self.source).touch()


@pytest.mark.parametrize(
    ("after_checking", "failed"),
    [
        pytest.param(False, ProgressPhase.CHECKING, id="przed-sprawdzaniem"),
        pytest.param(True, ProgressPhase.READING, id="miedzy-sprawdzaniem-a-odczytem"),
    ],
)
def test_plik_zbiorczy_otwarty_w_excelu_zatrzymuje_wycene_zanim_otworzy_efenix(
    tmp_path: Path, page: Page, after_checking: bool, failed: ProgressPhase
) -> None:
    """Plik otwarty przed Uruchomieniem zatrzymuje je w Sprawdzaniu, a otwarty tuż po Sprawdzaniu w Odczycie danych."""

    orders = [Order("#7601", cells={"O": 1}, amount=_au({"012": 1}))]
    source = write_collective_file(tmp_path, orders)
    if not after_checking:
        excel_lock_file(source).write_bytes(b"")
    with atrapa_efenix([orders[0].in_efenix("761")]) as atrapa:
        outcome = _run(source, page, atrapa.url, tata=_OpensInExcelAfterChecking(source=source) if after_checking else None)
        requested = atrapa.requested()

    assert (_stop(outcome), requested, _kept(outcome)) == ("EFENIX_PLIK_ZBIORCZY_OTWARTY", [], False)
    assert [phase for phase, state in outcome.progress.phase_states.items() if state is PhaseState.FAILED] == [failed]


def test_plik_zbiorczy_ze_znacznikami_daje_w_przebiegu_rozliczen_rozliczenie_pracownika_bez_nich(tmp_path: Path, page: Page) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix(_marking_efenix(orders)) as atrapa:
        _run(source, page, atrapa.url)
    template = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    write_template(template)
    assert _marked(source) == [18, 19]

    summary = run_settlements(source, write_mapping(tmp_path / "worker_mapping.yaml"), worker_template_path=template)

    assert summary.written_count == 1
    written = source.parent / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx"
    workbook = load_workbook(written)
    try:
        sheet = active_worksheet(workbook)
        fills = {row: sheet[f"B{row}"].fill for row in range(18, 24)}
        font = sheet["B18"].font
    finally:
        workbook.close()
    assert {row: (fill.fill_type, str(fill.fgColor.rgb)[-6:] if fill.fill_type else None) for row, fill in fills.items()} == {
        **{row: (None, None) for row in range(18, 23)},
        23: ("solid", YELLOW),
    }
    assert (font.color.rgb, font.b, font.i) == ("FFFF0000", True, True)


_TRACE_START = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


@dataclass
class _SlowEfenix:
    """Okno efenix, w którym każde działanie trwa ``ACTION_S`` udawanego czasu ``time``, a otwarcie zlecenia po nim
    zgłasza ``UnexpectedPage``."""

    time: _FakeTime
    ACTION_S = 3.0

    def search(self, number: str) -> Sequence[ListedOrder]:
        self.time.pause(self.ACTION_S)
        return [ListedOrder(number, "Nowe", None, "", "1")]

    def open_order(self, order: ListedOrder) -> OrderPricing:
        self.time.pause(self.ACTION_S)
        raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))

    def set_execution_date(self, day: date) -> bool:
        raise AssertionError("ślad nie woła działań, których nie woła przebieg")

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        raise AssertionError("ślad nie woła działań, których nie woła przebieg")

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        raise AssertionError("ślad nie woła działań, których nie woła przebieg")


def test_slad_zlecenia_ma_chwile_rozpoczecia_kazdego_dzialania_okna_efenix_takze_tego_ktore_sie_nie_udalo() -> None:
    """Godzina działania w Logach Uruchomienia to jego start, a nie koniec, także działania, przy którym okno stanęło:
    szukanie zaczyna się w chwili 1 s i trwa 3 s, a nieudane otwarcie zlecenia zaczyna się po przerwie w chwili 5 s."""

    time = _FakeTime(seconds=1.0)
    trace = efenix_trace.OrderTrace()
    order = CollectiveOrder(18, "9901", "adrian.testowy", "UL. TESTOWA 1", DAY, {}, Decimal(0))
    window = efenix_trace.traced(_SlowEfenix(time), order, trace, time, lambda: _TRACE_START + timedelta(seconds=time.seconds))

    [listed] = window.search("9901")
    time.pause(1.0)
    with pytest.raises(UnexpectedPage):
        window.open_order(listed)

    read = ListedRead(same_number=True, status="Nowe", realizator=None, address=(AddressPart.EFENIX_UNREAD,))
    assert trace.steps == [efenix_trace.TraceStep("szukanie", _TRACE_START + timedelta(seconds=1), 3000, found=1, results=(read,))]
    assert trace.failed == efenix_trace.TraceStep("otwarcie zlecenia", _TRACE_START + timedelta(seconds=5), 3000)


# --- Zgaśnięcie Centrum w przerwie tempa ludzkiego (#881) ----------------------------------------------------------------


class _SwitchedOff(BaseException):
    """Centrum zgasło: proces kończy się w miejscu, w którym był, bez Zatrzymania i bez Znaczników efenix."""


def test_zgasniecie_centrum_w_przerwie_tempa_przed_iloscia_daje_wznowienie_ktore_konczy_zlecenie_jak_jeden_przebieg(
    tmp_path: Path, page: Page
) -> None:
    """Emmett wpisuje O (012), a proces ma wpisać T (019). Centrum gaśnie w przerwie tempa ludzkiego przed zapisem T,
    zanim okno wyśle żądanie, więc efenix nie ma T. Ponowne uruchomienie dokańcza zlecenie z samą Wyceną Emmetta bez
    ponownego ładowania Emmetta i daje ten sam stan efenix i Znaczniki co jeden przebieg."""

    filled = {"012": 1, "019": 2}
    order = Order("#5501", cells={"O": 1, "T": 2}, amount=_au(filled), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    clock = _FakeTime()
    pauses = 0

    def switching_off_before_quantity(seconds: float) -> None:
        # Przerwy przed zapisami: 1 przed datą wykonania, 2 przed Wyceną Emmetta, 3 przed ilością T.
        nonlocal pauses
        clock.pause(seconds)
        pauses += 1
        if pauses == 3:
            raise _SwitchedOff

    with atrapa_efenix([order.in_efenix("951")], clock=clock) as atrapa:
        with pytest.raises(_SwitchedOff):
            _run(source, page, atrapa.url, pace=Pace(sleep=switching_off_before_quantity, clock=clock))
        switched_off = _pricing(atrapa)["5501"]
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)

    assert switched_off == ({"012": 1}, DAY, 1)
    assert (again.result, _errors(again), pricing, _marked(source)) == ("OK", [], {"5501": (filled, DAY, 1)}, [18])
