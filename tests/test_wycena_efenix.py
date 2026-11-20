from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
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
from typing import Any, TypeVar, cast
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import urlopen
import zipfile

from atrapy.model_efenix import Action, StanEfenix
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection

from playwright.sync_api import Browser, Error as PlaywrightError, Locator, Page, Request as PlaywrightRequest, Route
from playwright.sync_api import Response as PlaywrightResponse, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
import pytest

from rozliczenia.period_folder import PeriodFolder
from rozliczenia import tool_files
from rozliczenia.dad_files import DadFiles
from rozliczenia import efenix_browser, efenix_process, efenix_trace
from rozliczenia.domain import ProgressPhase
from rozliczenia.efenix_mark import Mark
from rozliczenia.efenix_pace import KEEPALIVE_S, Pace
from rozliczenia.efenix_address import AddressPart
from rozliczenia.efenix_checks import ListedRead
from rozliczenia.efenix_pricing import (
    EfenixInputs,
    OrderKind,
    PricingMode,
    PricingStopped,
    PricingSummary,
)
from rozliczenia.efenix_window import (
    BrowserFailure,
    StatusChangeBlocked,
    Closed,
    Efenix,
    EfenixUnreachable,
    ElementCount,
    EmmettLoad,
    ForwardRefusal,
    HttpStatus,
    ListedOrder,
    LoggedOut,
    Login,
    LoginSign,
    OpenEfenix,
    Operation,
    OrderPricing,
    OtherShape,
    PagePart,
    Shape,
    UnexpectedPage,
    WindowAction,
    WindowCause,
    WindowClosed,
    WindowStop,
)
from rozliczenia.efenix_marking import mark_orders
from rozliczenia.efenix_orders import CollectiveOrder
from rozliczenia.efenix_page import EmmettWindow, ResultsTable, emmett_window, emmett_window_fault, read_order
from rozliczenia.efenix_page import read_results, results_table, search_warning
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.process_run import Finished, Outcome, Stop, run_process
from rozliczenia.progress import PhaseState, ProgressSnapshot, SavingStep
from rozliczenia.tool_files import TOOL_ROOT
from rozliczenia.workbook_files import excel_lock_file, read_computed_rows, read_data_rows
from rozliczenia.workbook_parts import UnsupportedShape
from rozliczenia.run_clock import RunClock
from rozliczenia.run_context import RunContext

from atrapy.atrapa_efenix import (
    CHANGE_STATUS,
    LIST_PAGE,
    LIST_SCRIPT,
    LOAD_EMMETT,
    LOGIN_PAGE,
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
    StatusChange,
    amount_of,
    atrapa_efenix,
)
from atrapy.efenix import ADDRESS, DAY, Order, write_collective_file
from atrapy.interlocutor import Tata
from tests.fixtures.okno_w_procesie import OknoWProcesie, okno
from tests.fixtures.przegladarka import chromium, page_of
from atrapy.settlement import PERIOD, worker_list, write_template
from atrapy.workbooks import active_worksheet, rewrite_parts

READ_ONLY_REQUESTS = {("GET", LIST_PAGE), ("POST", SEARCH), ("GET", ORDER_PAGE), ("GET", LIST_SCRIPT), ("GET", ORDER_SCRIPT)}
Priced = Outcome[PricingSummary]
_USED_TABS: weakref.WeakSet[Page] = weakref.WeakSet()
_T = TypeVar("_T")


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with chromium() as launched:
        yield launched


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
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
    mode: PricingMode = PricingMode.FILL,
    hurried_start: bool = False,
) -> Priced:
    assert page not in _USED_TABS, (
        "następne Uruchomienie w nowej karcie: _next_tab(page); skrypt strony efenix zostawionej przez Zatrzymanie"
        " przeładowuje ją jeszcze po odmowie „Załaduj do zlecenia” i przerywa w tej karcie otwarcie listy"
    )
    _USED_TABS.add(page)

    @contextmanager
    def open_efenix(_login: Login) -> Iterator[Efenix]:
        try:
            tab = page if hurried_start else _unhurried_start(page)
            with efenix_browser.window(tab, url, timeout_ms=timeout_ms) as efenix:
                yield window(efenix)
        except Exception as error:
            print("Błąd okna efenix:", "".join(traceback.format_exception(error)), sep="\n", file=sys.stderr)
            raise
        meanwhile()

    return _launched(source, open_efenix, pace=pace, clock=clock, tata=tata, mode=mode)


def _run_in_process(
    source: Path,
    stan: StanEfenix[AtrapaOrder],
    *,
    mode: PricingMode = PricingMode.FILL,
    pace: Pace | None = None,
    meanwhile: Callable[[], None] = lambda: None,
) -> Priced:
    @contextmanager
    def open_efenix(login: Login) -> Iterator[Efenix]:
        with okno(stan, login) as efenix:
            yield efenix
        meanwhile()

    return _launched(source, open_efenix, mode=mode, pace=pace)


def _price_in_process(tmp_path: Path, stan: StanEfenix[AtrapaOrder], orders: Sequence[Order]) -> Priced:
    return _run_in_process(write_collective_file(tmp_path, orders), stan)


def _launched(
    source: Path,
    open_efenix: OpenEfenix,
    *,
    pace: Pace | None = None,
    clock: Callable[[], float] = time.perf_counter,
    tata: Tata | None = None,
    mode: PricingMode = PricingMode.FILL,
) -> Priced:
    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(source, open_efenix, pace=pace, mode=mode),
        tata or Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=source.parent.parent / "metryki.jsonl",
        context=RunContext(clock=RunClock(clock)),
    )


def _changes(stan: StanEfenix[AtrapaOrder]) -> list[int]:
    return [stan.count(action) for action in Action if action not in (Action.SEARCH, Action.OPEN)]


def _read_only(stan: StanEfenix[AtrapaOrder]) -> bool:
    return not any(_changes(stan))


# ZEWNĘTRZNE: pierwsza nawigacja nowej karty Chromium pod obciążeniem pytest-xdist trwa na runnerze CI ponad 2 s, dłużej niż krótki czas okna testu (pomiar w GitHub Actions)
class _UnhurriedStart:
    def __init__(self, page: Page) -> None:
        self._page = page
        self._started = False

    def goto(self, url: str, **options: Any) -> object:
        if not self._started:
            self._started = True
            options["timeout"] = efenix_browser.TIMEOUT_MS
        return self._page.goto(url, **options)

    def __getattr__(self, name: str) -> object:
        return getattr(self._page, name)


def _unhurried_start(page: Page) -> Page:
    return cast(Page, _UnhurriedStart(page))


def _next_tab(page: Page) -> Page:
    assert page in _USED_TABS and not page.is_closed(), (
        "_next_tab dostaje kartę ostatniego Uruchomienia, jeszcze otwartą: inaczej jej przeładowanie po „Załaduj do"
        " zlecenia” trafia do Atrapy efenix w trakcie następnego Uruchomienia"
    )
    browser = page.context.browser
    assert browser is not None
    # ZEWNĘTRZNE: page.close() wysłane, gdy skrypt strony zaczyna przeładowanie, kończy się dopiero z zamknięciem kontekstu przeglądarki (pomiar na Chromium Playwrighta)
    page.context.close()
    return browser.new_context().new_page()


# ZEWNĘTRZNE: synchroniczny Playwright nie startuje w wątku, w którym już działa inny, a wątek testu może mieć już Playwright przeglądarki testów (Playwright, Sync API: „using Playwright Sync API inside the asyncio loop”)
def _on_own_playwright_thread(call: Callable[..., _T], *args: object, timeout: float | None = None) -> _T:
    with ThreadPoolExecutor(max_workers=1) as own_thread:
        return own_thread.submit(call, *args).result(timeout=timeout)


def _figures(outcome: Priced) -> dict[str, int]:
    assert isinstance(outcome.ending, Finished), _ending(outcome)
    assert outcome.view is not None
    summary = outcome.view
    return {
        "zakres": len(summary.results),
        "gotowe": summary.count(OrderKind.READY),
        "przekazane": summary.count(OrderKind.FORWARDED),
        "rozliczone": summary.count(OrderKind.SETTLED),
        "błędy": summary.count(OrderKind.ERROR),
        "ostrzeżenia": summary.count(OrderKind.WARNING),
        "ze zdjęciami": summary.with_photos,
        "usterki": summary.defects,
    }


def _ending(outcome: Priced) -> str:
    if isinstance(outcome.ending, Stop):
        return f"Zatrzymanie {outcome.ending.message.code} | {outcome.ending.message.where}"
    return repr(outcome.ending)


def _errors(outcome: Priced) -> list[tuple[str, str]]:
    assert outcome.view is not None
    return [(warning.code, warning.where.rpartition(", ")[2]) for warning in outcome.view.warnings]


def _what(outcome: Priced) -> list[str]:
    assert outcome.view is not None
    return [warning.what for warning in outcome.view.warnings]


def _pricing(efenix: AtrapaEfenix | StanEfenix[AtrapaOrder]) -> dict[str, tuple[dict[str, int], date | None, int]]:
    orders, _logged_in = efenix.state()
    return {order.number: (order.quantities, order.execution_date, order.emmett_loads) for order in orders}


def _stop(outcome: Priced) -> str:
    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert outcome.ending.kind == "stop"
    return outcome.ending.message.code


def _kept(outcome: Priced) -> bool:
    assert isinstance(outcome.ending, Stop), outcome.ending
    what = outcome.ending.message.what
    kept, unchanged = "Wycena zleceń sprzed zatrzymania została w efenix." in what, "W efenix nic się nie zmieniło." in what
    assert kept != unchanged, what
    return kept


def _figures_of(
    orders: int, ready: int, warnings: int = 0, photos: int = 0, defects: int = 0, settled: int = 0, forwarded: int = 0
) -> dict[str, int]:
    return {
        "zakres": orders,
        "gotowe": ready,
        "przekazane": forwarded,
        "rozliczone": settled,
        "błędy": orders - ready - warnings - settled - forwarded,
        "ostrzeżenia": warnings,
        "ze zdjęciami": photos,
        "usterki": defects,
    }


def _au(quantities: dict[str, int]) -> float:
    return float(amount_of(quantities))


def test_zlecenie_z_wycena_zgodna_z_plikiem_jest_gotowe_a_efenix_dostaje_tylko_szukanie_i_otwarcie_zlecenia(
    tmp_path: Path, page: Page
) -> None:
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
    assert set(requested) <= READ_ONLY_REQUESTS
    assert requested.count(("GET", ORDER_PAGE)) == 3


_RUN_4_11_CELLS = {"O": 1, "S": 3, "Y": 2, "Z": 1}
_RUN_4_11_FILE = {"012": 1, "016": 3, "009": 2, "010": 1}


@pytest.mark.parametrize(
    ("in_efenix", "entered"),
    [
        pytest.param({"012": 1, "016": 2}, {"016": 3, "009": 2, "010": 1}, id="sama-wycena-emmetta-z-S-o-1-mniejszym-bez-Y-i-Z"),
        pytest.param({"012": 1, "016": 3}, {"009": 2, "010": 1}, id="niepełna-wycena-bez-Y-i-Z"),
    ],
)
def test_wycena_ktora_juz_jest_z_mniejsza_iloscia_niz_plik_proces_dokancza_iloscia_z_pliku_bez_wyceny_emmetta(
    tmp_path: Path, in_efenix: dict[str, int], entered: dict[str, int]
) -> None:
    order = Order("#5101", cells=_RUN_4_11_CELLS, amount=_au(_RUN_4_11_FILE), quantities=in_efenix, emmett={"012": 1, "016": 2})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([order.in_efenix("901")])
    outcome = _run_in_process(source, efenix)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (_pricing(efenix), _marked(source)) == ({"5101": (_RUN_4_11_FILE, DAY, 0)}, [18])
    assert [efenix.count(action) for action in (Action.PROPOSAL, Action.EMMETT, Action.DATE, Action.QUANTITY)] == [0, 0, 0, len(entered)]


@pytest.mark.parametrize(
    ("in_efenix", "entered"),
    [
        pytest.param({"012": 1, "016": 1, "009": 1}, 3, id="mniej-niż-plik"),
        pytest.param(_RUN_4_11_FILE, 0, id="zgodna-z-plikiem"),
    ],
)
def test_wycena_ktora_juz_jest_bez_daty_wykonania_dostaje_date_z_data_a_potem_ilosci_z_pliku_bez_wyceny_emmetta(
    tmp_path: Path, in_efenix: dict[str, int], entered: int
) -> None:
    executed = date(2026, 9, 3)
    order = Order("#5103", day=executed, cells=_RUN_4_11_CELLS, amount=_au(_RUN_4_11_FILE), quantities=in_efenix, emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([replace(order.in_efenix("901"), execution_date=None)])
    outcome = _run_in_process(source, efenix)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (_pricing(efenix), _marked(source)) == ({"5103": (_RUN_4_11_FILE, executed, 0)}, [18])
    assert [efenix.count(action) for action in (Action.PROPOSAL, Action.EMMETT, Action.DATE, Action.QUANTITY)] == [0, 0, 1, entered]


@pytest.mark.parametrize(
    ("day", "refuse_dates", "error", "set_date"),
    [
        pytest.param(date(2026, 10, 13), False, "EFENIX_DATA_POZA_ZAKRESEM", 0, id="dzień-poza-kalendarzem"),
        pytest.param(DAY, True, "EFENIX_DATA_NIEZAPISANA", 1, id="dzień-niezapisany"),
    ],
)
def test_data_wykonania_odrzucona_przy_wycenie_ktora_juz_jest_to_blad_bez_zmiany_ilosci(
    tmp_path: Path, day: date, refuse_dates: bool, error: str, set_date: int
) -> None:
    in_efenix = {"012": 1, "016": 1}
    order = Order("#5104", day=day, cells=_RUN_4_11_CELLS, amount=_au(_RUN_4_11_FILE), quantities=in_efenix)
    efenix = StanEfenix([replace(order.in_efenix("901"), execution_date=None)], today=date(2026, 10, 12), refuse_dates=refuse_dates)
    outcome = _price_in_process(tmp_path, efenix, [order])

    assert (outcome.result, _errors(outcome), _pricing(efenix)) == ("WYMAGA_SPRAWDZENIA", [(error, "wiersz 18")], {"5104": (in_efenix, None, 0)})
    assert [efenix.count(action) for action in (Action.DATE, Action.EMMETT, Action.QUANTITY)] == [set_date, 0, 0]


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
    ],
)
def test_pozycja_z_wieksza_iloscia_w_efenix_niz_w_pliku_zostaje_a_reszta_zlecenia_jest_dopisana_z_ostrzezeniem_emmetta(
    tmp_path: Path, in_efenix: dict[str, int], emmett: dict[str, int], excess: str, after: dict[str, int]
) -> None:
    order = Order("#5401", cells={"O": 1, "P": 0, "T": 2}, amount=_au({"012": 1, "019": 2}), quantities=in_efenix, emmett=emmett)
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([replace(order.in_efenix("901"), execution_date=DAY)])
    outcome = _run_in_process(source, efenix)
    pricing = _pricing(efenix)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(1, 0, warnings=1),
        [("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 18")],
    )
    assert _what(outcome) == [
        f"efenix ma więcej niż Plik zbiorczy: {excess}. Narzędzie tych ilości nie zmieniło, a pozostałe ilości z pliku wpisało."
    ]
    assert (pricing, _marked(source)) == ({"5401": (after, DAY, int(not in_efenix))}, [])


def test_wycena_ktora_juz_jest_z_iloscmi_pliku_a_kwota_inna_niz_au_to_blad_z_obiema_kwotami_bez_zmian(tmp_path: Path) -> None:
    order =Order("#5102", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}) + 1, quantities={"012": 1, "019": 2})
    efenix = StanEfenix([replace(order.in_efenix("901"), execution_date=DAY)])
    before = efenix.state()
    outcome = _price_in_process(tmp_path, efenix, [order])

    assert (outcome.result, _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", [("EFENIX_INNA_KWOTA", "wiersz 18")])
    [what] = _what(outcome)
    efenix_amount = amount_of({"012": 1, "019": 2})
    assert f"kwota w efenix to {efenix_amount:.2f} zł, a Kwota (AU) {efenix_amount + 1:.2f} zł".replace(".", ",") in what
    assert what.endswith(" zł. Ilości z pliku są już wpisane w efenix."), what
    assert (efenix.state(), _read_only(efenix)) == (before, True)


_EXCEL_SUM_BINARY_FRACTION = 1e-9


def test_pusta_wycena_dostaje_date_z_data_wycene_emmetta_i_ilosci_z_pliku_w_pustych_pozycjach_a_kwota_rowna_au_daje_gotowe(
    tmp_path: Path, page: Page
) -> None:
    filled = {"012": 1, "019": 2, "015": 1}
    orders = [
        Order("#5201", day=date(2026, 9, 3), cells={"O": 1, "T": 2, "AG": 1, "Z": 0}, amount=_au(filled), emmett={"012": 1}),
        Order("#5202", cells={"O": 2}, amount=_au({"012": 2}) + _EXCEL_SUM_BINARY_FRACTION, emmett={"012": 2}),
    ]
    with atrapa_efenix([orders[0].in_efenix("901"), replace(orders[1].in_efenix("902"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        pricing = _pricing(atrapa)
        requested = atrapa.requested()
        changes = atrapa.status_changes()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 2), [])
    assert pricing == {"5201": (filled, date(2026, 9, 3), 1), "5202": ({"012": 2}, DAY, 1)}
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", SAVE_QUANTITY)), changes) == (1, 2, 0)


def test_kwota_efenix_inna_niz_au_po_dopisaniu_ilosci_to_blad_z_obiema_kwotami(tmp_path: Path) -> None:
    order = Order("#5301", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}) + 0.4, emmett={"012": 1})
    efenix = StanEfenix([order.in_efenix("901")])
    outcome = _price_in_process(tmp_path, efenix, [order])
    pricing = _pricing(efenix)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [("EFENIX_INNA_KWOTA", "wiersz 18")])
    assert pricing == {"5301": ({"012": 1, "019": 2}, DAY, 1)}
    [what] = _what(outcome)
    efenix_amount, au = amount_of({"012": 1, "019": 2}), amount_of({"012": 1, "019": 2}) + Decimal("0.40")
    assert f"kwota w efenix to {efenix_amount:.2f} zł, a Kwota (AU) {au:.2f} zł".replace(".", ",") in what


def test_dzien_z_data_spoza_zakresu_kalendarza_efenix_to_blad_bez_zapisu_daty_bez_emmetta_i_bez_ilosci(tmp_path: Path, page: Page) -> None:
    order = Order("#5601", day=date(2026, 10, 13), cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("901")], today=date(2026, 10, 12)) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        after = _pricing(atrapa)
        requested = atrapa.requested()
        dialog_hidden = page.locator("#dialog_select_date").is_hidden()

    assert (outcome.result, _errors(outcome), after, dialog_hidden) == (
        "WYMAGA_SPRAWDZENIA",
        [("EFENIX_DATA_POZA_ZAKRESEM", "wiersz 18")],
        {"5601": ({}, None, 0)},
        True,
    )
    assert requested.count(("POST", SET_DATE)) == 0


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
    days: int,
    result: str,
    errors: list[tuple[str, str]],
    pricing: tuple[dict[str, int], int],
) -> None:
    executed = DAY + timedelta(days=days)
    order = Order("#5651", cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 1})
    efenix = StanEfenix([replace(order.in_efenix("901"), execution_date=executed)])
    outcome = _price_in_process(tmp_path, efenix, [order])

    quantities, emmett_loads = pricing
    assert (outcome.result, _errors(outcome), _pricing(efenix)) == (result, errors, {"5651": (quantities, executed, emmett_loads)})
    assert efenix.count(Action.DATE) == 0


def test_data_wykonania_ktorej_efenix_nie_zapisal_po_potwierdz_to_blad_bez_emmetta_i_bez_ilosci(tmp_path: Path) -> None:
    order = Order("#5701", cells={"O": 1}, amount=_au({"012": 1}))
    efenix = StanEfenix([order.in_efenix("901")], refuse_dates=True)
    outcome = _price_in_process(tmp_path, efenix, [order])

    assert (outcome.result, _errors(outcome), _pricing(efenix)) == (
        "WYMAGA_SPRAWDZENIA",
        [("EFENIX_DATA_NIEZAPISANA", "wiersz 18")],
        {"5701": ({}, None, 0)},
    )
    assert [efenix.count(action) for action in (Action.DATE, Action.EMMETT, Action.QUANTITY)] == [1, 0, 0]


def test_ilosc_emmetta_mniejsza_niz_w_pliku_proces_zastepuje_iloscia_z_pliku_a_zlecenie_jest_gotowe(tmp_path: Path) -> None:
    filled = {"012": 1, "016": 3, "019": 2}
    order = Order("#5402", cells={"O": 1, "S": 3, "T": 2}, amount=_au(filled), emmett={"012": 1, "016": 1})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([order.in_efenix("901")])
    outcome = _run_in_process(source, efenix)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (_pricing(efenix), _marked(source)) == ({"5402": (filled, DAY, 1)}, [18])
    assert [efenix.count(action) for action in (Action.EMMETT, Action.QUANTITY)] == [1, 2]


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
    tmp_path: Path, cells: dict[str, int | str], error: str
) -> None:
    orders = [Order("#5501", cells=cells, amount=100.0), Order("#5502")]
    efenix = StanEfenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)])
    outcome = _price_in_process(tmp_path, efenix, orders)

    assert (_figures(outcome), _errors(outcome), efenix.searched()) == (_figures_of(2, 1), [(error, "wiersz 18")], ["5502"])


ASSEMBLY_POSITIONS = frozenset({"012", "013", "014", "015", "016", "017", "018", "019", "020", "021", "022", "023", "024", "025", "027", "028"})


def test_strona_zlecenia_bez_pozycji_z_zerem_w_pliku_dostaje_wycene_emmetta_i_ilosci_pliku_a_nastepne_zlecenie_jest_wyceniane(
    tmp_path: Path,
) -> None:
    filled = {"029": 1, "009": 2, "010": 1}
    orders = [
        Order("#5601", day=date(2026, 9, 3), cells={"V": 1, "Y": 2, "Z": 1, "O": 0}, amount=_au(filled), emmett={"029": 1}),
        Order("#5602", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    efenix = StanEfenix([replace(orders[0].in_efenix("901"), without=ASSEMBLY_POSITIONS), orders[1].in_efenix("902")])
    outcome = _price_in_process(tmp_path, efenix, orders)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 2), [])
    assert _pricing(efenix) == {"5601": (filled, date(2026, 9, 3), 1), "5602": ({"012": 1}, date(2026, 9, 4), 1)}


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
    after_date: bool,
    after_emmett: bool,
    pricing: tuple[dict[str, int], date | None, int],
    done: str,
) -> None:
    orders = [
        Order("#5701", day=date(2026, 9, 3), cells={"O": 1, "T": 2, "V": 1}, amount=_au({"012": 1, "019": 2, "029": 1}), emmett={"029": 1}),
        Order("#5702", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    in_efenix = [replace(orders[0].in_efenix("901"), without=ASSEMBLY_POSITIONS, after_date=after_date, after_emmett=after_emmett), orders[1].in_efenix("902")]
    efenix = StanEfenix(in_efenix)
    outcome = _price_in_process(tmp_path, efenix, orders)
    after, changes = _pricing(efenix), efenix.count(Action.STATUS)

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
def test_wycena_ktora_juz_jest_na_stronie_bez_pozycji_z_zerem_w_pliku_jest_dokonczona_do_pliku(tmp_path: Path, file: int, saved: int) -> None:
    order = Order("#5801", cells={"V": file}, amount=_au({"029": file}), quantities={"029": 1})
    efenix = StanEfenix([replace(order.in_efenix("901"), execution_date=DAY, without=ASSEMBLY_POSITIONS)])
    outcome = _price_in_process(tmp_path, efenix, [order])

    assert (_figures(outcome), _errors(outcome)) == (_figures_of(1, 1), [])
    assert (_pricing(efenix), efenix.count(Action.QUANTITY)) == ({"5801": ({"029": file}, DAY, 0)}, saved)


def test_szukanie_ktore_lista_efenix_wysyla_sama_po_powrocie_ze_strony_zlecenia_nie_zmienia_wynikow_szukania(
    tmp_path: Path, page: Page
) -> None:
    orders = [Order("#5101"), Order("#5102"), Order("#5103")]
    with atrapa_efenix([order.in_efenix(f"91{index}") for index, order in enumerate(orders)], answer_delay_s=0.3) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched, by_list = atrapa.searched(), atrapa.searched_by_list()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(3, 3), [])
    assert (searched, by_list) == (["5101", "5102", "5103"], ["5101", "5102"])


def test_zlecenia_ze_zdjeciami_i_usterki_sa_pominiete_i_policzone_a_wiersz_z_samymi_zerami_jest_w_zakresie(tmp_path: Path) -> None:
    photo_columns = ["AB", "AC", "AD", "AE", "AF", "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AS"]
    orders = [
        *(Order(f"#60{index:02}", cells={column: 1}) for index, column in enumerate(photo_columns)),
        Order("#6101", cells={"AJ": "tak"}),
        Order("#6201", cells={"AI": 1}),
        Order("#6301", cells=dict.fromkeys([*photo_columns, "AI"], 0)),
        Order("#6302", cells=dict.fromkeys([*photo_columns, "AI"], "0")),
        Order("#6401", cells={"H": None}),
    ]
    efenix = StanEfenix([order.in_efenix(f"9{index:02}") for index, order in enumerate(orders)])
    outcome = _price_in_process(tmp_path, efenix, orders)

    assert (outcome.result, _figures(outcome), efenix.searched()) == ("OK", _figures_of(2, 2, photos=14, defects=1), ["6301", "6302"])


def test_zlecenia_ida_po_wykonawcach_alfabetycznie_a_u_kazdego_od_najstarszej_daty(tmp_path: Path) -> None:
    orders = [
        Order("#7001", worker="zenon.testowy", day=date(2026, 9, 8)),
        Order("#7002", worker="adrian.testowy", day=date(2026, 9, 12)),
        Order("#7003", worker="Bogdan.testowy", day=date(2026, 9, 10)),
        Order("#7004", worker="adrian.testowy", day=date(2026, 9, 9)),
        Order("#7005", worker="zenon.testowy", day=date(2026, 9, 7)),
    ]
    efenix = StanEfenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)])
    outcome = _price_in_process(tmp_path, efenix, orders)

    assert (outcome.result, efenix.searched()) == ("OK", ["7004", "7002", "7003", "7005", "7001"])


def test_kazda_niezgodnosc_z_efenix_to_blad_zlecenia_z_powodem_a_proces_idzie_dalej(tmp_path: Path) -> None:
    orders = [
        Order(""),
        Order("#8002", day=None),
        Order("#8003"),
        Order("#8010"),
        Order("#8004"),
        Order("#8005"),
        Order("#8006"),
        Order("#8007"),
        Order("#8008"),
        Order("#8009", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
    ]
    efenix = [
        orders[1].in_efenix("902"),
        replace(orders[2].in_efenix("903"), number="80031"),
        orders[4].in_efenix("904"),
        orders[4].in_efenix("914"),
        replace(orders[5].in_efenix("905"), status="Anulowane"),
        replace(orders[6].in_efenix("906"), realizator="zenon.testowy"),
        replace(orders[7].in_efenix("907"), address="Miasto-Dzielnica ul.Testowa 14 Lokal 3"),
        replace(orders[8].in_efenix("908"), execution_date=date(2026, 9, 13)),
        replace(orders[9].in_efenix("909"), execution_date=DAY),
    ]
    stan = StanEfenix(efenix)
    before = stan.state()
    outcome = _price_in_process(tmp_path, stan, orders)
    after = stan.state()

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(10, 1))
    assert _errors(outcome) == [
        ("EFENIX_BRAK_NUMERU", "wiersz 18"),
        ("EFENIX_NIEZNANY_NUMER", "wiersz 20"),
        ("EFENIX_NIEZNANY_NUMER", "wiersz 21"),
        ("EFENIX_KILKA_ZLECEN", "wiersz 22"),
        ("EFENIX_INNY_STATUS", "wiersz 23"),
        ("EFENIX_INNY_REALIZATOR", "wiersz 24"),
        ("EFENIX_INNY_ADRES", "wiersz 25"),
        ("EFENIX_INNA_DATA", "wiersz 26"),
        ("EFENIX_BRAK_DATY", "wiersz 19"),
    ], "wiersz bez daty w DATA idzie na koniec zleceń swojego Wykonawcy"
    assert after == before


def test_zlecenie_rozliczone_w_efenix_nie_jest_bledem_a_proces_go_nie_otwiera_i_nie_stawia_mu_znacznika(tmp_path: Path) -> None:
    orders = [
        Order("#8101", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 2}),
        Order("#8102", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    efenix = StanEfenix([replace(orders[0].in_efenix("901"), status=" rozliczone ", execution_date=DAY), orders[1].in_efenix("902")])
    before = efenix.state()
    outcome = _run_in_process(source, efenix)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 1, settled=1), [])
    assert (efenix.state(), _read_only(efenix), efenix.count(Action.OPEN)) == (before, True, 1)
    assert _marked(source) == [19]


def test_realizator_efenix_rowny_wykonawcy_innym_zapisem_tych_samych_liter_to_ten_sam_realizator(tmp_path: Path) -> None:
    order = Order("#8301", worker="Jo\u0301zef.Testowy", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    efenix = StanEfenix([replace(order.in_efenix("901"), realizator="j\u00f3zef.testowy", execution_date=DAY)])

    outcome = _price_in_process(tmp_path, efenix, [order])

    assert (outcome.result, _errors(outcome)) == ("OK", [])


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
        pytest.param(
            lambda order: replace(order, status="Do akceptacji", realizator="zenon.testowy"),
            "EFENIX_INNY_REALIZATOR",
            id="przekazane-inny-realizator",
        ),
        pytest.param(
            lambda order: replace(order, status="Do akceptacji", address="Miasto-Dzielnica ul.Testowa 14 Lokal 3"),
            "EFENIX_INNY_ADRES",
            id="przekazane-inny-adres",
        ),
        pytest.param(
            lambda order: replace(order, status="Do akceptacji Maksa"), "EFENIX_INNY_STATUS", id="status-dłuższy-niż-do-akceptacji"
        ),
    ],
)
def test_zlecenie_rozliczone_albo_przekazane_innego_wykonawcy_albo_adresu_to_blad_zlecenia(
    tmp_path: Path, changed: Callable[[AtrapaOrder], AtrapaOrder], code: str
) -> None:
    order = Order("#8201")
    outcome = _price_in_process(tmp_path, StanEfenix([changed(order.in_efenix("901"))]), [order])

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [(code, "wiersz 18")])



# --- Przekazanie do akceptacji (ADR 0027) -----------------------------------------------------------------------------

FORWARDED_RGB = Mark.FORWARDED.value


def _statuses(stan: StanEfenix[AtrapaOrder]) -> dict[str, str]:
    orders, _logged_in = stan.state()
    return {order.number: order.status for order in orders}


def test_w_trybie_z_przekazaniem_gotowe_zlecenie_jest_przekazane_do_akceptacji_ze_znacznikiem_przekazania_a_blad_i_ostrzezenie_emmetta_nie(
    tmp_path: Path,
) -> None:
    orders = [
        Order("#8301", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#8302", cells={"O": 1}, amount=_au({"012": 1}) + 5, quantities={"012": 1}),
        Order("#8303", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 2}),
        Order("#8304", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    stan = StanEfenix(
        [
            *(replace(order.in_efenix(f"90{index}"), execution_date=DAY) for index, order in enumerate(orders[:3])),
            replace(orders[3].in_efenix("903"), execution_date=DAY, status="Do akceptacji"),
        ]
    )
    outcome = _run_in_process(source, stan, mode=PricingMode.FORWARD)

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(4, 0, warnings=1, forwarded=2))
    assert _errors(outcome) == [("EFENIX_INNA_KWOTA", "wiersz 19"), ("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 20")]
    assert _statuses(stan) == {"8301": "Do akceptacji", "8302": "Do wyceny", "8303": "Do wyceny", "8304": "Do akceptacji"}
    assert stan.count(Action.STATUS) == 1
    assert _address_fills(source) == {18: FORWARDED_RGB, 19: None, 20: None, 21: FORWARDED_RGB}
    assert outcome.view is not None
    assert [[step.action for step in result.steps] for result in outcome.view.results] == [
        [WindowAction.SEARCH, WindowAction.OPEN, WindowAction.FORWARD, WindowAction.SEARCH],
        [WindowAction.SEARCH, WindowAction.OPEN],
        [WindowAction.SEARCH, WindowAction.OPEN],
        [WindowAction.SEARCH],
    ]


def test_przekazanie_ktorego_efenix_nie_pokazuje_potem_jako_do_akceptacji_to_blad_zlecenia_bez_znacznika(tmp_path: Path) -> None:
    order = Order("#8311", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order])
    stan = StanEfenix([replace(order.in_efenix("901"), execution_date=DAY, keeps_status=True)])
    outcome = _run_in_process(source, stan, mode=PricingMode.FORWARD)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [("EFENIX_NIEPRZEKAZANE", "wiersz 18")])
    assert (stan.count(Action.STATUS), _address_fills(source)) == (1, {18: None})


def test_w_trybie_bez_przekazania_proces_niczego_nie_przekazuje_a_zlecenie_do_akceptacji_jest_przekazane_bez_otwierania(tmp_path: Path) -> None:
    orders = [
        Order("#8321", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#8322", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    stan = StanEfenix(
        [
            replace(orders[0].in_efenix("901"), execution_date=DAY),
            replace(orders[1].in_efenix("902"), execution_date=DAY, status="Do akceptacji"),
        ]
    )
    before = stan.state()
    outcome = _run_in_process(source, stan)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 1, forwarded=1), [])
    assert (stan.state(), _read_only(stan), stan.count(Action.OPEN)) == (before, True, 1)
    assert _address_fills(source) == {18: READY_RGB, 19: FORWARDED_RGB}


@pytest.mark.parametrize("mode", list(PricingMode), ids=lambda mode: mode.name.lower())
def test_znacznik_przekazania_zastepuje_znacznik_efenix_a_znacznik_efenix_nigdy_nie_zastepuje_znacznika_przekazania(
    tmp_path: Path, mode: PricingMode
) -> None:
    orders = [
        Order("#8331", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_fill=READY_RGB),
        Order("#8332", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_fill=FORWARDED_RGB),
    ]
    source = write_collective_file(tmp_path, orders)
    stan = StanEfenix(
        [
            replace(orders[0].in_efenix("901"), execution_date=DAY, status="Do akceptacji"),
            replace(orders[1].in_efenix("902"), execution_date=DAY),
        ]
    )
    outcome = _run_in_process(source, stan, mode=mode)

    assert outcome.result == "OK"
    assert _address_fills(source) == {18: FORWARDED_RGB, 19: FORWARDED_RGB}


def test_zlecenie_do_akceptacji_z_adresem_juz_w_kolorze_znacznika_przekazania_zostaje_a_plik_sie_nie_zmienia(tmp_path: Path) -> None:
    order = Order("#8333", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_fill=FORWARDED_RGB)
    source = write_collective_file(tmp_path, [order])
    _packed_like_excel(source)
    before = source.read_bytes()
    outcome = _run_in_process(source, StanEfenix([replace(order.in_efenix("901"), execution_date=DAY, status="Do akceptacji")]))

    assert (outcome.result, _address_fills(source), source.read_bytes() == before) == ("OK", {18: FORWARDED_RGB}, True)


class _Before:
    def __init__(self, efenix: Efenix, before: Callable[[WindowAction], None]) -> None:
        self._efenix = efenix
        self._before = before

    def search(self, number: str) -> Sequence[ListedOrder]:
        self._before(WindowAction.SEARCH)
        return self._efenix.search(number)

    def open_order(self, order: ListedOrder) -> OrderPricing:
        self._before(WindowAction.OPEN)
        return self._efenix.open_order(order)

    def set_execution_date(self, day: date) -> bool:
        self._before(WindowAction.DATE)
        return self._efenix.set_execution_date(day)

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        self._before(WindowAction.EMMETT)
        return self._efenix.load_emmett(verdict)

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        self._before(WindowAction.QUANTITY)
        return self._efenix.enter_quantity(position, quantity)

    def forward_to_accept(self) -> ForwardRefusal | None:
        self._before(WindowAction.FORWARD)
        return self._efenix.forward_to_accept()


def test_w_tempie_ludzkim_przekazanie_to_zapis_z_przerwa_a_potwierdzajace_szukanie_idzie_bez_przerwy(tmp_path: Path) -> None:
    filled = {"012": 1, "019": 2}
    orders = [Order(f"#834{index}", cells={"O": 1, "T": 2}, amount=_au(filled), emmett={"012": 1}) for index in (1, 2)]
    source = write_collective_file(tmp_path, orders)
    stan = StanEfenix([replace(order.in_efenix(f"90{index}"), execution_date=DAY) for index, order in enumerate(orders)])
    log: list[str] = []
    clock = _FakeTime()

    def sleep(seconds: float) -> None:
        log.append(f"przerwa {seconds:g} s")
        clock.pause(seconds)

    @contextmanager
    def logged_window(login: Login) -> Iterator[Efenix]:
        with okno(stan, login) as efenix:
            yield _Before(efenix, lambda action: log.append(action.name))

    outcome = _launched(source, logged_window, pace=Pace(sleep=sleep, clock=clock), mode=PricingMode.FORWARD)

    assert outcome.result == "OK"
    one_order = ["SEARCH", "OPEN", "przerwa 2 s", "EMMETT", "przerwa 2 s", "QUANTITY", "przerwa 2 s", "FORWARD", "SEARCH"]
    assert log == [*one_order, "przerwa 14 s", *one_order]


def test_jedno_okno_przegladarki_przekazuje_kazde_gotowe_zlecenie_po_kolei_jednym_zadaniem_zmiany_statusu_na_do_akceptacji(
    tmp_path: Path, page: Page
) -> None:
    orders = [Order(number, cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}) for number in ("#8351", "#8352")]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [replace(order.in_efenix(order_id), execution_date=DAY) for order, order_id in zip(orders, ("901", "902"), strict=True)]
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=PricingMode.FORWARD)
        requests = atrapa.status_requests()
        forwarded, _logged_in = atrapa.state()

    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(2, 0, forwarded=2))
    assert requests == 2 * [("POST", "Do akceptacji")]
    assert ([order.status for order in forwarded], _address_fills(source)) == (2 * ["Do akceptacji"], {18: FORWARDED_RGB, 19: FORWARDED_RGB})


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        pytest.param(
            "Rozliczyłeś prace ziemne lub rozliczasz zlecenie UST - Nie dołączyłeś do wyceny żadnych zdjęć !", ForwardRefusal.NO_PHOTOS, id="no_photos"
        ),
        pytest.param("Podaj długość przyłącza !", ForwardRefusal.NO_LENGTH, id="no_length"),
        pytest.param("Nie wprowadziłeś wyceny zlecenia !", ForwardRefusal.NO_PRICING, id="no_pricing"),
        pytest.param("Brak wypełnionej daty wykonania !", ForwardRefusal.NO_DATE, id="no_date"),
        pytest.param("Zlecenie zablokowane przez administratora !", ForwardRefusal.OTHER_TEXT, id="tekst-spoza-listy"),
    ],
)
def test_odmowa_przekazania_przez_efenix_to_blad_zlecenia_bez_znacznika_a_nastepne_gotowe_zlecenie_jest_przekazane(
    tmp_path: Path, page: Page, text: str, refusal: ForwardRefusal
) -> None:
    orders = [Order(number, cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}) for number in ("#8371", "#8372")]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [
        replace(orders[0].in_efenix("901"), execution_date=DAY, forward_refusal=text),
        replace(orders[1].in_efenix("902"), execution_date=DAY),
    ]
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=PricingMode.FORWARD, timeout_ms=3_000)
        requests = atrapa.status_requests()
        after, _logged_in = atrapa.state()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(2, 0, forwarded=1),
        [("EFENIX_ODMOWA_PRZEKAZANIA", "wiersz 18")],
    )
    assert isinstance(outcome.ending, Finished)
    assert (outcome.ending.counters["ready"], outcome.ending.counters["errors"]) == (0, 1)
    assert (requests, [order.status for order in after]) == ([("POST", "Do akceptacji")], ["Do wyceny", "Do akceptacji"])
    assert _address_fills(source) == {18: None, 19: FORWARDED_RGB}
    assert outcome.view is not None
    assert [(step.action, step.refusal) for step in outcome.view.results[0].steps] == [
        (WindowAction.SEARCH, None),
        (WindowAction.OPEN, None),
        (WindowAction.FORWARD, refusal),
    ]


def test_odmowa_przekazania_w_oknie_informacji_ze_spinnerem_i_skonczona_animacja_to_blad_zlecenia_a_nie_zatrzymanie(
    tmp_path: Path, page: Page
) -> None:
    order = Order("#8391", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("901"), execution_date=DAY, forward_refusal=ForwardRefusal.NO_LENGTH.value)
    with atrapa_efenix([in_efenix], changed=Changed.OTHER_ANIMATIONS_IN_INFO) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=PricingMode.FORWARD, timeout_ms=3_000)
        requests = atrapa.status_requests()

    assert (outcome.result, _errors(outcome), requests) == ("WYMAGA_SPRAWDZENIA", [("EFENIX_ODMOWA_PRZEKAZANIA", "wiersz 18")], [])


def test_odmowa_przekazania_nie_jest_zmiana_w_efenix_w_komunikacie_pozniejszego_zatrzymania(tmp_path: Path) -> None:
    orders = [Order(number, cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}) for number in ("#8381", "#8382")]
    source = write_collective_file(tmp_path, orders)
    stan = StanEfenix(
        [
            replace(orders[0].in_efenix("901"), execution_date=DAY, forward_refusal=ForwardRefusal.NO_LENGTH.value),
            replace(orders[1].in_efenix("902"), execution_date=DAY),
        ],
        expire_after=(Action.OPEN, 1),
    )
    outcome = _run_in_process(source, stan, mode=PricingMode.FORWARD)

    assert (_stop(outcome), _kept(outcome), _read_only(stan)) == ("EFENIX_WYLOGOWANY", False, True)


def test_przycisk_przekazania_ktorego_tak_wysyla_anulowane_nie_dochodzi_do_efenix_a_wycena_zatrzymuje_sie_do_maksa(
    tmp_path: Path, page: Page
) -> None:
    order = Order("#8361", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)], status_change=StatusChange.FORWARD_CANCELS) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=PricingMode.FORWARD, timeout_ms=3_000)
        requests = atrapa.status_requests()
        [in_efenix], _logged_in = atrapa.state()

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        "for_maks",
        PagePart.FORWARD,
        StatusChangeBlocked.OTHER_STATUS,
    )
    assert (requests, in_efenix.status, _address_fills(source)) == ([], "Do wyceny", {18: None})


@pytest.mark.parametrize(
    ("status_change", "cause", "reached", "status"),
    [
        pytest.param(StatusChange.FORWARD_OTHER_ORDER, StatusChangeBlocked.OTHER_ORDER, [], "Do wyceny", id="inne-zlecenie"),
        pytest.param(StatusChange.FORWARD_TWO_ORDERS, StatusChangeBlocked.OTHER_ORDER, [], "Do wyceny", id="dwa-zlecenia"),
        pytest.param(StatusChange.FORWARD_ORDER_IN_URL, StatusChangeBlocked.OTHER_ORDER, [], "Do wyceny", id="inne-zlecenie-w-adresie"),
        pytest.param(StatusChange.FORWARD_GET, StatusChangeBlocked.OTHER_STATUS, [], "Do wyceny", id="get"),
        pytest.param(StatusChange.FORWARD_TWO_STATUSES, StatusChangeBlocked.OTHER_STATUS, [], "Do wyceny", id="dwa-statusy"),
        pytest.param(StatusChange.FORWARD_STATUS_IN_URL, StatusChangeBlocked.OTHER_STATUS, [], "Do wyceny", id="status-w-adresie"),
        pytest.param(StatusChange.FORWARD_EMPTY_STATUS_IN_URL, StatusChangeBlocked.OTHER_STATUS, [], "Do wyceny", id="pusty-status-w-adresie"),
        pytest.param(StatusChange.FORWARD_EMPTY_ORDER, StatusChangeBlocked.OTHER_ORDER, [], "Do wyceny", id="puste-zlecenie-w-tresci"),
        pytest.param(StatusChange.FORWARD_UNREADABLE, StatusChangeBlocked.OTHER_STATUS, [], "Do wyceny", id="tresc-nie-tekst"),
        pytest.param(
            StatusChange.FORWARD_TWICE,
            StatusChangeBlocked.OUTSIDE_FORWARD,
            [("POST", "Do akceptacji")],
            "Do akceptacji",
            id="drugie-zadanie",
        ),
    ],
)
def test_w_przekazaniu_do_efenix_dochodzi_tylko_jedno_zadanie_post_do_akceptacji_otwartego_zlecenia(
    tmp_path: Path, page: Page, status_change: StatusChange, cause: StatusChangeBlocked, reached: list[tuple[str, str]], status: str
) -> None:
    order = Order("#8381", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order])
    in_efenix = [replace(order.in_efenix("901"), execution_date=DAY), Order("#8382").in_efenix("902")]
    with atrapa_efenix(in_efenix, status_change=status_change) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=PricingMode.FORWARD, timeout_ms=3_000)
        requests = atrapa.status_requests()
        [opened, other], _logged_in = atrapa.state()

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.cause) == ("EFENIX_OKNO_ZATRZYMANE", "for_maks", cause)
    assert (requests, opened.status, other.status, other.quantities) == (reached, status, "Do wyceny", {})
    assert _address_fills(source) == {18: None}


def test_zmiana_statusu_po_ostatnim_dzialaniu_okna_nie_dochodzi_do_efenix_a_okno_konczy_sie_zatrzymaniem(page: Page) -> None:
    with atrapa_efenix([Order("#8391").in_efenix("901")]) as atrapa:
        with pytest.raises(UnexpectedPage) as stopped:
            with efenix_browser.window(page, atrapa.url):
                page.evaluate(
                    "() => fetch('action_change_status.php', {method: 'POST', body: 'order_id=901&xstatus=Anulowane'})"
                    ".catch(() => 'przerwane')"
                )
        requests = atrapa.status_requests()

    assert (stopped.value.cause, requests) == (StatusChangeBlocked.OUTSIDE_FORWARD, [])


def test_zmiana_statusu_przerwana_miedzy_dzialaniami_okna_zatrzymuje_nastepne_dzialanie_zanim_dojdzie_do_efenix(page: Page) -> None:
    def search_after_blocked_change(url: str) -> None:
        with efenix_browser.window(page, url) as efenix:
            page.evaluate(
                "() => fetch('action_change_status.php', {method: 'POST', body: 'order_id=901&xstatus=Anulowane'})"
                ".catch(() => 'przerwane')"
            )
            efenix.search("#8392")

    with atrapa_efenix([Order("#8392").in_efenix("901")]) as atrapa:
        with pytest.raises(UnexpectedPage) as stopped:
            search_after_blocked_change(atrapa.url)
        searched = atrapa.searched()

    assert (stopped.value.part, stopped.value.cause, searched) == (PagePart.RESULTS, StatusChangeBlocked.OUTSIDE_FORWARD, [])


def test_przekazanie_otwartego_zlecenia_wyslane_przez_strone_po_udanym_przekazaniu_nie_dochodzi_do_efenix_a_okno_konczy_sie_zatrzymaniem(
    page: Page,
) -> None:
    def forward_then_page_forwards_again(url: str) -> None:
        with efenix_browser.window(page, url) as efenix:
            [listed] = efenix.search("8399")
            efenix.open_order(listed)
            assert efenix.forward_to_accept() is None
            page.evaluate(
                "() => fetch('action_change_status.php', {method: 'POST', body: 'order_id=901&xstatus=Do%20akceptacji&comment='})"
                ".catch(() => 'przerwane')"
            )

    order = Order("#8399", cells={"O": 1}, quantities={"012": 1})
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        with pytest.raises(UnexpectedPage) as stopped:
            forward_then_page_forwards_again(atrapa.url)
        requests = atrapa.status_requests()

    assert (stopped.value.cause, requests) == (StatusChangeBlocked.OUTSIDE_FORWARD, [("POST", "Do akceptacji")])


@pytest.mark.parametrize(
    ("mode", "status_change"),
    [
        pytest.param(PricingMode.FILL, StatusChange.ON_LOAD, id="on_load-fill"),
        pytest.param(PricingMode.FORWARD, StatusChange.POPUP, id="popup-forward"),
    ],
)
def test_zmiana_statusu_ktorej_okno_nie_wyslalo_w_przekazaniu_nie_dochodzi_do_efenix_takze_z_nowego_okna_strony(
    tmp_path: Path, page: Page, mode: PricingMode, status_change: StatusChange
) -> None:
    order = Order("#8371", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)], status_change=status_change) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=mode, timeout_ms=3_000)
        requests = atrapa.status_requests()
        [in_efenix], _logged_in = atrapa.state()

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.cause) == ("EFENIX_OKNO_ZATRZYMANE", "for_maks", StatusChangeBlocked.OUTSIDE_FORWARD)
    assert (requests, in_efenix.status, _address_fills(source)) == ([], "Do wyceny", {18: None})


def test_zmiana_statusu_przy_wczytaniu_strony_zlecenia_w_innej_budowie_to_zatrzymanie_o_zmianie_statusu(tmp_path: Path, page: Page) -> None:
    order = Order("#8373", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    in_efenix = replace(order.in_efenix("901"), execution_date=DAY, changed=Changed.DATE_FORMAT)
    with atrapa_efenix([in_efenix], status_change=StatusChange.ON_LOAD) as atrapa:
        outcome = _run(write_collective_file(tmp_path, [order]), page, atrapa.url, timeout_ms=3_000)
        requests = atrapa.status_requests()

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), facts.part, facts.cause, requests) == ("EFENIX_OKNO_ZATRZYMANE", PagePart.ORDER, StatusChangeBlocked.OUTSIDE_FORWARD, [])


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


def test_numer_zl_liczba_niecalkowita_to_numer_z_czescia_ulamkowa_a_nie_numer_innego_zlecenia(tmp_path: Path) -> None:
    whole = Order("#9121", cells={"F": 9121.0})
    fraction = Order("#9122", cells={"F": 9122.5})
    efenix = StanEfenix([whole.in_efenix("912"), fraction.in_efenix("913")])
    outcome = _price_in_process(tmp_path, efenix, [whole, fraction])

    assert (efenix.searched(), _errors(outcome)) == (["9121", "9122.5"], [("EFENIX_NIEZNANY_NUMER", "wiersz 19")])


@pytest.mark.parametrize(
    ("expire_after", "searched", "kept"),
    [
        pytest.param(None, [], False, id="przed-szukaniem"),
        pytest.param((Action.OPEN, 0), ["9201"], False, id="przy-otwarciu-pierwszego-zlecenia"),
        pytest.param((Action.SEARCH, 1), ["9201", "9202"], True, id="przy-szukaniu"),
    ],
)
def test_wylogowanie_przed_szukaniem_albo_w_trakcie_zatrzymuje_wycene_a_komunikat_mowi_czy_cos_zmienila(
    tmp_path: Path, expire_after: tuple[Action, int] | None, searched: list[str], kept: bool
) -> None:
    orders = [Order(f"#920{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    efenix = StanEfenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)], expire_after=expire_after)
    if expire_after is None:
        efenix.expire_session()
    outcome = _price_in_process(tmp_path, efenix, orders)

    assert (_stop(outcome), efenix.searched(), _kept(outcome)) == ("EFENIX_WYLOGOWANY", searched, kept)


def test_wylogowanie_w_odpowiedzi_na_date_wykonania_zatrzymuje_wycene_bez_ponownego_otwarcia_zlecenia(tmp_path: Path, page: Page) -> None:
    order = Order("#9211", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("921")], expire_after=(SET_DATE, 0)) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        requested = atrapa.requested()

    assert (_stop(outcome), requested.count(("POST", SET_DATE)), requested.count(("GET", ORDER_PAGE))) == ("EFENIX_WYLOGOWANY", 1, 1)


TIMEOUT = "playwright._impl._errors.TimeoutError"
PLAYWRIGHT_ERROR = "playwright._impl._errors.Error"
CHANGED: dict[Changed, tuple[PagePart, WindowCause, WindowAction]] = {
    Changed.STATUS_HEADER: (PagePart.RESULTS, OtherShape(Shape.COLUMNS), WindowAction.SEARCH),
    Changed.ORDER_LINK: (PagePart.RESULTS, OtherShape(Shape.ROW_CELLS), WindowAction.SEARCH),
    Changed.RESULTS_WARNING: (PagePart.RESULTS, OtherShape(Shape.NO_TABLE), WindowAction.SEARCH),
    Changed.DATE_FORMAT: (PagePart.ORDER, OtherShape(Shape.DATE_TEXT), WindowAction.OPEN),
    Changed.DATE_DIGITS: (PagePart.ORDER, OtherShape(Shape.DATE_TEXT), WindowAction.OPEN),
    Changed.SIGNED_AMOUNT: (PagePart.ORDER, OtherShape(Shape.AMOUNT_TEXT), WindowAction.OPEN),
    Changed.DATE_DIALOG: (PagePart.DATE, BrowserFailure(TIMEOUT, Operation.ELEMENT), WindowAction.DATE),
    Changed.EMMETT_BUTTON: (PagePart.EMMETT, ElementCount("#button_emmett", 0), WindowAction.EMMETT),
    Changed.HIDDEN_EMMETT: (PagePart.EMMETT, BrowserFailure(TIMEOUT, Operation.CLICK), WindowAction.EMMETT),
    Changed.STALE_AMOUNT: (PagePart.QUANTITY, BrowserFailure(TIMEOUT, Operation.AMOUNT), WindowAction.QUANTITY),
    Changed.QUANTITY_ANSWER: (PagePart.QUANTITY, OtherShape(Shape.ANSWER_NOT_JSON, "012"), WindowAction.QUANTITY),
    Changed.QUANTITY_RESULT: (PagePart.QUANTITY, OtherShape(Shape.ANSWER_RESULT, "012"), WindowAction.QUANTITY),
    Changed.QUANTITY_VALUE: (PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, "012"), WindowAction.OPEN),
    Changed.SECOND_NUMBER_FIELD: (PagePart.LIST, ElementCount("#field_numer", 2), WindowAction.SEARCH),
    Changed.NUMBER_FIELD_GONE: (PagePart.LIST, ElementCount("#field_numer", 0), WindowAction.SEARCH),
    Changed.SECOND_EMMETT_DIALOG: (PagePart.EMMETT, ElementCount("#dialog_emmett", 2), WindowAction.EMMETT),
}


_WAITING_WHOLE_WINDOW_TIME = (Changed.DATE_DIALOG, Changed.HIDDEN_EMMETT, Changed.STALE_AMOUNT, Changed.NUMBER_FIELD_GONE)


@pytest.mark.parametrize("changed", [changed for changed in Changed if changed is not Changed.OTHER_ANIMATIONS_IN_INFO])
def test_inna_budowa_tabeli_wynikow_albo_strony_zlecenia_zatrzymuje_wycene_do_maksa_z_czescia_strony(
    tmp_path: Path, page: Page, changed: Changed
) -> None:
    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    in_efenix = replace(order.in_efenix("901"), execution_date=None if changed is Changed.DATE_DIALOG else DAY)
    timeout_ms = 1_000 if changed in _WAITING_WHOLE_WINDOW_TIME else 3_000
    with atrapa_efenix([in_efenix], changed=changed) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=timeout_ms)
        changes = atrapa.status_changes()

    assert (_stop(outcome), changes, _kept(outcome)) == ("EFENIX_OKNO_ZATRZYMANE", 0, changed in (Changed.STALE_AMOUNT, Changed.QUANTITY_ANSWER, Changed.QUANTITY_RESULT))
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
    assert stopped_at.duration_ms < 2 * timeout_ms, stopped_at


def _without_calendar(page: Page) -> Callable[[Efenix], Efenix]:
    before = _scripts(page, {WindowAction.DATE: "() => { window.jQuery = () => ({}); }"})
    return lambda efenix: _Before(efenix, before)


def _answering(path: str, answer: Callable[[Route], None]) -> Callable[[Page], Callable[[Efenix], Efenix]]:
    def prepare(page: Page) -> Callable[[Efenix], Efenix]:
        page.route(f"**/{path}", answer)
        return lambda efenix: efenix

    return prepare


def _to_login(route: Route) -> None:
    route.fulfill(status=HTTPStatus.FOUND, headers={"Location": LOGIN_PAGE})


_EMPTY = Order("#9511", cells={"O": 1}, amount=_au({"012": 1}))
_READY = Order("#9512", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
ANSWERED = {
    "pole-daty-bez-kalendarza": (
        _EMPTY,
        _EMPTY.in_efenix("951"),
        PricingMode.FILL,
        _without_calendar,
        ("EFENIX_OKNO_ZATRZYMANE", PagePart.DATE, OtherShape(Shape.NO_CALENDAR), WindowAction.DATE),
    ),
    "zapis-ilosci-przekierowany-na-logowanie": (
        _EMPTY,
        replace(_EMPTY.in_efenix("951"), execution_date=DAY),
        PricingMode.FILL,
        _answering(SAVE_QUANTITY, _to_login),
        ("EFENIX_WYLOGOWANY", PagePart.QUANTITY, LoginSign.REDIRECT, WindowAction.QUANTITY),
    ),
    "przekazanie-przekierowane-na-logowanie": (
        _READY,
        _READY.in_efenix("952"),
        PricingMode.FORWARD,
        _answering(CHANGE_STATUS, _to_login),
        ("EFENIX_WYLOGOWANY", PagePart.FORWARD, LoginSign.REDIRECT, WindowAction.FORWARD),
    ),
    "przekazanie-ze-statusem-400": (
        _READY,
        _READY.in_efenix("952"),
        PricingMode.FORWARD,
        _answering(CHANGE_STATUS, lambda route: route.fulfill(status=HTTPStatus.BAD_REQUEST)),
        ("EFENIX_OKNO_ZATRZYMANE", PagePart.FORWARD, HttpStatus(HTTPStatus.BAD_REQUEST), WindowAction.FORWARD),
    ),
}


@pytest.mark.parametrize(("order", "in_efenix", "mode", "prepare", "stopped"), ANSWERED.values(), ids=ANSWERED.keys())
def test_dzialanie_okna_bez_kalendarza_bez_odpowiedzi_albo_z_przekierowaniem_na_logowanie_zatrzymuje_wycene_z_przyczyna(
    tmp_path: Path,
    page: Page,
    order: Order,
    in_efenix: AtrapaOrder,
    mode: PricingMode,
    prepare: Callable[[Page], Callable[[Efenix], Efenix]],
    stopped: tuple[str, PagePart, WindowCause, WindowAction],
) -> None:
    with atrapa_efenix([in_efenix]) as atrapa:
        outcome = _run(write_collective_file(tmp_path, [order]), page, atrapa.url, timeout_ms=3_000, window=prepare(page), mode=mode)

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped) and facts.stopped_at is not None
    failed = facts.stopped_at.failed
    assert failed is not None
    assert (_stop(outcome), facts.part, facts.cause, failed.action) == stopped


def test_zerwane_zadanie_przekazania_zatrzymuje_wycene_od_razu_a_nie_po_czasie_okna(tmp_path: Path, page: Page) -> None:
    with atrapa_efenix([_READY.in_efenix("952")]) as atrapa:
        outcome = _run(
            write_collective_file(tmp_path, [_READY]),
            page,
            atrapa.url,
            timeout_ms=efenix_browser.TIMEOUT_MS,
            window=_answering(CHANGE_STATUS, lambda route: route.abort())(page),
            mode=PricingMode.FORWARD,
        )

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped) and facts.stopped_at is not None
    failed = facts.stopped_at.failed
    assert failed is not None
    assert (facts.cause, failed.action) == (OtherShape(Shape.STATUS_NOT_ANSWERED), WindowAction.FORWARD)
    assert (_stop(outcome), facts.part) == ("EFENIX_OKNO_ZATRZYMANE", PagePart.FORWARD)
    assert failed.duration_ms < efenix_browser.TIMEOUT_MS / 2, failed


_ANSWER_LOST = [
    pytest.param(SEARCH, Outage.CUT, PagePart.RESULTS, WindowAction.SEARCH, id="szukanie-zerwane"),
    pytest.param(SET_DATE, Outage.CUT, PagePart.DATE, WindowAction.DATE, id="zapis-daty-zerwany"),
    pytest.param(LOAD_EMMETT, Outage.CUT, PagePart.EMMETT, WindowAction.EMMETT, id="zaladuj-do-zlecenia-zerwane"),
    pytest.param(SAVE_QUANTITY, Outage.CUT, PagePart.QUANTITY, WindowAction.QUANTITY, id="zapis-ilosci-zerwany"),
    pytest.param(SAVE_QUANTITY, Outage.TORN, PagePart.QUANTITY, WindowAction.QUANTITY, id="zapis-ilosci-zerwany-w-polowie"),
]


@pytest.mark.parametrize(("path", "outage", "part", "action"), _ANSWER_LOST)
def test_zerwane_zadanie_na_ktorego_odpowiedz_czeka_okno_zatrzymuje_wycene_od_razu_a_nie_po_czasie_okna(
    tmp_path: Path, page: Page, path: str, outage: Outage, part: PagePart, action: WindowAction
) -> None:
    [order] = _two_orders()[:1]
    with atrapa_efenix([order.in_efenix("990")], outage_from=(outage, WHOLE_RUN.index(("POST", path)))) as atrapa:
        outcome = _run(write_collective_file(tmp_path, [order]), page, atrapa.url, timeout_ms=efenix_browser.TIMEOUT_MS)

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped) and facts.stopped_at is not None
    failed = facts.stopped_at.failed
    assert failed is not None
    assert (_stop(outcome), outcome.ending.stop_kind) == ("EFENIX_OKNO_ZATRZYMANE", "for_maks")
    assert (facts.part, facts.cause, failed.action) == (part, BrowserFailure(PLAYWRIGHT_ERROR, Operation.ANSWER), action)
    assert failed.duration_ms < efenix_browser.TIMEOUT_MS / 2, failed


_REPEATED_SEARCH = "powtorzone"
_ELSEWHERE = "http://zasoby.invalid/czcionka.woff2"
_SEARCHES_REPEATED_ON_ENTER = f"""
document.addEventListener('keypress', (event) => {{
  if (event.key !== 'Enter' || event.target.id !== 'field_numer') return;
  for (let powtorzenie = 0; powtorzenie < 2; powtorzenie++) {{
    const body = new URLSearchParams({{numer: event.target.value, rodzaj: '{_REPEATED_SEARCH}'}});
    fetch('{SEARCH}', {{method: 'POST', body: body}}).catch(() => {{}});
  }}
  fetch('{_ELSEWHERE}', {{mode: 'no-cors'}}).catch(() => {{}});
}}, true);
"""


def test_przerwane_szukania_z_tym_samym_numerem_i_zerwany_zasob_spoza_efenix_nie_zatrzymuja_okna_ktore_czeka_na_swoje_szukanie(
    tmp_path: Path, page: Page
) -> None:
    ended: list[Route] = []
    held: list[Route] = []

    def end(route: Route, error_code: str) -> None:
        route.abort(error_code)
        ended.append(route)
        if len(ended) == 3:
            for search in held:
                search.fallback()

    def search(route: Route) -> None:
        if parse_qs(route.request.post_data or "").get("rodzaj") == [_REPEATED_SEARCH]:
            end(route, "aborted")
        elif len(ended) == 3:
            route.fallback()
        else:
            held.append(route)

    failures: list[tuple[str, str | None]] = []
    page.on("requestfailed", lambda request: failures.append((request.url.rpartition("/")[2], request.failure)))
    page.add_init_script(_SEARCHES_REPEATED_ON_ENTER)
    page.route(f"**/{SEARCH}", search)
    page.route(_ELSEWHERE, lambda route: end(route, "connectionrefused"))
    with atrapa_efenix([_READY.in_efenix("952")], answer_delay_s=0.5) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [_READY], timeout_ms=3_000)
        searched = atrapa.searched()

    assert sorted(failures) == sorted(
        [(SEARCH, "net::ERR_ABORTED"), (SEARCH, "net::ERR_ABORTED"), (_ELSEWHERE.rpartition("/")[2], "net::ERR_CONNECTION_REFUSED")]
    )
    assert (outcome.result, _figures(outcome), searched) == ("OK", _figures_of(1, 1), ["9512"])


def test_wylogowanie_zaraz_po_przekazaniu_zatrzymuje_wycene_na_przekazaniu_a_zlecenie_jest_juz_do_akceptacji(
    tmp_path: Path, page: Page
) -> None:
    order = Order("#8396", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)], expire_after=(ORDER_PAGE, 1)) as atrapa:
        outcome = _run(source, page, atrapa.url, mode=PricingMode.FORWARD, timeout_ms=3_000)
        [in_efenix], _logged_in = atrapa.state()

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), facts.part, facts.cause, in_efenix.status) == ("EFENIX_WYLOGOWANY", PagePart.FORWARD, LoginSign.PAGE, "Do akceptacji")


_DIALOG = '<div id="dialog_emmett">{}</div>'
_PROPOSAL = '<div id="emmett-propozycja">{}</div>'


@pytest.mark.parametrize(
    ("body", "window", "fault"),
    [
        pytest.param(_DIALOG.format(_PROPOSAL.format("<ul><li>012: 1</li></ul>")), EmmettWindow(1, 1, True), None, id="propozycja"),
        pytest.param(_DIALOG.format(_PROPOSAL.format(" \n ")), EmmettWindow(1, 1, False), None, id="pusta-propozycja"),
        pytest.param(_PROPOSAL.format("012: 1"), EmmettWindow(0, 0, False), ElementCount("#dialog_emmett", 0), id="bez-okna"),
        pytest.param(
            _DIALOG.format(_PROPOSAL.format("012: 1")) + _DIALOG.format(""),
            EmmettWindow(2, 1, True),
            ElementCount("#dialog_emmett", 2),
            id="dwa-okna",
        ),
        pytest.param(
            _DIALOG.format(_PROPOSAL.format("012: 1") * 2),
            EmmettWindow(1, 2, False),
            ElementCount("#dialog_emmett #emmett-propozycja", 2),
            id="dwie-propozycje",
        ),
        pytest.param(_DIALOG.format(""), EmmettWindow(1, 0, False), ElementCount("#dialog_emmett #emmett-propozycja", 0), id="bez-propozycji"),
        pytest.param(
            '<div id="host"></div><script>document.getElementById("host").attachShadow({mode: "open"}).innerHTML ='
            f" '{_DIALOG.format(_PROPOSAL.format('012: 1'))}';</script>" + _DIALOG.format(_PROPOSAL.format("012: 1")),
            EmmettWindow(2, 2, False),
            ElementCount("#dialog_emmett", 2),
            id="drugie-okno-w-shadow-dom",
        ),
    ],
)
def test_okno_emmetta_ma_dokladnie_jedno_okno_a_w_nim_dokladnie_jedna_propozycje_regula_wspolna_wyceny_i_narzedzia(
    page: Page, body: str, window: EmmettWindow, fault: ElementCount | None
) -> None:
    page.set_content(body)
    observed = emmett_window(page)

    assert (observed, emmett_window_fault(observed)) == (window, fault)


def test_puste_pole_ilosc_na_stronie_zlecenia_to_ilosc_zero_pozycji(page: Page) -> None:
    page.set_content(
        '<span id="data_install"></span><span id="cena_all2">12.50</span>'
        '<input class="wycena-ilosc" id="INDEKS_012_078" value=""><input class="wycena-ilosc" id="INDEKS_019_078" value="3">'
    )

    assert read_order(page) == (
        OrderPricing(None, Decimal("12.50"), {"012": 0, "019": 3}),
        {"012": "INDEKS_012_078", "019": "INDEKS_019_078"},
    )


def _order_page(page: Page, html: str) -> object:
    page.set_content(html)
    return read_order(page)


_ORDER = '<span id="data_install">{}</span><span id="cena_all2">12.50</span><input class="wycena-ilosc" id="{}" value="1">'
_RESULTS = (
    "<table><thead><tr><th>Numer dokumentu</th><th>Status</th><th>Wykonawca (login)</th><th>Dane adresowe</th></tr></thead>"
    f'<tbody><tr><td></td><td>Do wyceny</td><td>Fikcyjny</td><td><a href="{ORDER_PAGE}?id=951">Otwórz</a></td></tr></tbody></table>'
)
UNREAD = {
    "pole-ilosc-o-id-spoza-indeksu": (_ORDER.format("", "ILOSC_012"), _order_page, PagePart.ORDER, OtherShape(Shape.QUANTITY_ID)),
    "data-wykonania-dnia-ktorego-nie-ma": (
        _ORDER.format("2026-02-30", "INDEKS_012_078"),
        _order_page,
        PagePart.ORDER,
        OtherShape(Shape.DATE_TEXT),
    ),
    "kod-pozycji-w-dwoch-polach-ilosc": (
        _ORDER.format("", "INDEKS_012_078") + '<input class="wycena-ilosc" id="INDEKS_012_079" value="1">',
        _order_page,
        PagePart.ORDER,
        OtherShape(Shape.POSITION_TWICE, "012"),
    ),
    "data-wykonania-dwa-razy": (
        _ORDER.format("", "INDEKS_012_078") + '<span id="data_install"></span>',
        _order_page,
        PagePart.ORDER,
        ElementCount("#data_install", 2),
    ),
    "wiersz-wynikow-bez-numeru": (_RESULTS, read_results, PagePart.RESULTS, OtherShape(Shape.ROW_EMPTY)),
}


@pytest.mark.parametrize(("html", "read", "part", "cause"), UNREAD.values(), ids=UNREAD.keys())
def test_strona_zlecenia_albo_wiersz_wynikow_w_innej_budowie_to_inna_strona_z_czescia_i_przyczyna(
    page: Page, html: str, read: Callable[[Page, str], object], part: PagePart, cause: WindowCause
) -> None:
    with pytest.raises(UnexpectedPage) as raised:
        read(page, html)

    assert (raised.value.part, raised.value.cause) == (part, cause)


def test_zmieniona_strona_efenix_oznacza_gotowe_przed_nia_a_komunikat_do_maksa_nie_ma_numeru_adresu_ani_loginu(
    tmp_path: Path, page: Page
) -> None:
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
    seconds: float = 0.0

    def __call__(self) -> float:
        return self.seconds

    def pause(self, seconds: float) -> None:
        self.seconds += seconds


def _closing_window(page: Page, clock: _FakeTime, at_pause: int) -> Pace:
    pauses = 0

    def sleep(seconds: float) -> None:
        nonlocal pauses
        clock.pause(seconds)
        pauses += 1
        if pauses == at_pause:
            page.close()

    return Pace(sleep=sleep, clock=clock)


def _closing_before(page: Page, action: WindowAction, occurrence: int) -> Callable[[WindowAction], None]:
    occurrences = itertools.count(1)

    def close(current: WindowAction) -> None:
        if current is action and next(occurrences) == occurrence:
            page.close()

    return close


@pytest.mark.parametrize(
    ("before", "in_pause", "kept", "marked"),
    [
        pytest.param((WindowAction.SEARCH, 1), 0, False, [], id="przy-szukaniu-na-liście"),
        pytest.param((WindowAction.SEARCH, 2), 0, False, [18], id="między-zleceniami"),
        pytest.param(None, 1, False, [18], id="przy-dacie-wykonania"),
        pytest.param((WindowAction.OPEN, 3), 0, True, [18], id="po-dacie-wykonania"),
    ],
)
def test_zamkniete_okno_efenix_zatrzymuje_wycene_z_komunikatem_dla_taty_a_gotowe_przed_nim_maja_znacznik(
    tmp_path: Path, page: Page, before: tuple[WindowAction, int] | None, in_pause: int, kept: bool, marked: list[int]
) -> None:
    orders = [
        Order("#9701", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9702", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    source = write_collective_file(tmp_path, orders)
    clock = _FakeTime()
    closing: Callable[[WindowAction], None] = (lambda _action: None) if before is None else _closing_before(page, *before)
    with atrapa_efenix([order.in_efenix(f"97{index}") for index, order in enumerate(orders)], clock=clock) as atrapa:
        outcome = _run(
            source,
            page,
            atrapa.url,
            pace=_closing_window(page, clock, in_pause),
            window=lambda efenix: _Before(efenix, closing),
        )

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), outcome.ending.stop_kind, _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZAMKNIETE", "for_tata", kept, marked)


@pytest.mark.parametrize(
    ("first", "execution_date", "kept", "marked"),
    [
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
    orders = [first, Order("#9712", day=date(2026, 10, 14), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [replace(first.in_efenix("971"), execution_date=execution_date), orders[1].in_efenix("972")]
    with atrapa_efenix(in_efenix, today=date(2026, 10, 12)) as atrapa:
        outcome = _run(source, page, atrapa.url, window=lambda efenix: _Before(efenix, _closing_before(page, WindowAction.SEARCH, 2)))

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZAMKNIETE", kept, marked)


# ZEWNĘTRZNE: Playwright przerywa nawigację karty, którą zamknięto w jej trakcie, błędem, zanim poda zamknięcie karty, a Page.is_closed mówi o nim dopiero po następnym pytaniu przeglądarki (pomiar na Chromium: błąd przed zamknięciem w 89 na 100 zamknięć)
class _CloseReportedLate:
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


NAVIGATIONS = {
    "lista-na-starcie": (LIST_PAGE, 1, PagePart.LIST),
    "strona-zlecenia": (ORDER_PAGE, 1, PagePart.ORDER),
    "przeladowanie-po-emmetcie": (ORDER_PAGE, 3, PagePart.EMMETT),
    "lista-ponownie": (LIST_PAGE, 2, PagePart.LIST),
}


def _full_and_ready() -> list[Order]:
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


@pytest.mark.parametrize(
    ("closed", "error_answer", "code"),
    [
        pytest.param(True, None, "EFENIX_OKNO_ZAMKNIETE", id="karta-zamknieta-przy-przeladowaniu"),
        pytest.param(False, (LOAD_EMMETT, 1, HTTPStatus.INTERNAL_SERVER_ERROR), "EFENIX_OKNO_ZATRZYMANE", id="strona-bledu-serwera"),
    ],
)
def test_zatrzymanie_w_zaladuj_do_zlecenia_zlecenia_z_data_wykonania_mowi_o_zmianie_w_efenix(
    tmp_path: Path, page: Page, closed: bool, error_answer: tuple[str, int, HTTPStatus] | None, code: str
) -> None:
    order = Order("#9721", cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 1})
    with atrapa_efenix([replace(order.in_efenix("972"), execution_date=DAY)], error_answer=error_answer) as atrapa:
        window = cast(Page, _CloseReportedLate(page, ORDER_PAGE, 2)) if closed else page
        outcome = _price(tmp_path, window, atrapa.url, [order])

    assert (_stop(outcome), _kept(outcome)) == (code, True)


def test_komunikat_zamknietego_okna_mowi_o_zmianie_w_efenix_z_kazdego_zlecenia_przed_nim_nie_tylko_z_ostatniego(
    tmp_path: Path, page: Page
) -> None:
    orders = [
        Order("#9731", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 1}),
        Order("#9732", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9733", day=date(2026, 9, 5), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [replace(orders[0].in_efenix("973"), execution_date=orders[0].day), *(order.in_efenix(f"97{index}") for index, order in enumerate(orders[1:], 4))]
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _run(source, page, atrapa.url, window=lambda efenix: _Before(efenix, _closing_before(page, WindowAction.SEARCH, 3)))

    assert (_stop(outcome), _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZAMKNIETE", True, [18, 19])


def test_cala_przegladarka_zamknieta_w_trakcie_otwierania_strony_zlecenia_to_zamkniete_okno(tmp_path: Path) -> None:
    orders = _full_and_ready()

    def priced_in_own_browser(url: str) -> Priced:
        with chromium() as own:
            page = own.new_page()
            browser_session = own.new_browser_cdp_session()

            def close_browser(request: PlaywrightRequest) -> None:
                if urlparse(request.url).path.endswith("/" + ORDER_PAGE):
                    with suppress(PlaywrightError):
                        browser_session.send("Browser.close")

            page.on("request", close_browser)
            return _price(tmp_path, page, url, orders)

    with atrapa_efenix(_full_and_ready_in_efenix(orders)) as atrapa:
        outcome = _on_own_playwright_thread(priced_in_own_browser, atrapa.url)

    assert isinstance(outcome.ending, Stop)
    facts = outcome.ending.facts
    assert isinstance(facts, PricingStopped)
    assert (_stop(outcome), outcome.ending.stop_kind, facts.part, facts.cause) == (
        "EFENIX_OKNO_ZAMKNIETE",
        "for_tata",
        PagePart.ORDER,
        Closed.DURING_ACTION,
    )


def _scripts(page: Page, scripts: Mapping[WindowAction, str]) -> Callable[[WindowAction], None]:
    def prepare(action: WindowAction) -> None:
        if (script := scripts.get(action)) is not None:
            page.evaluate(script)

    return prepare


_SLOW_DATE_CLOSE = """() => document.querySelectorAll('#dialog_select_date [data-dismiss="modal"]').forEach((button) =>
    button.addEventListener('click', () => {
        const dialog = document.getElementById('dialog_select_date');
        dialog.style.display = 'block';
        setTimeout(() => { dialog.style.display = 'none'; }, 200);
    }))"""
_SLOW_AMOUNT = """() => {
    const json = Response.prototype.json;
    Response.prototype.json = function () { return new Promise((resolve) => setTimeout(() => resolve(json.call(this)), 200)); };
}"""


def test_okno_czeka_na_efenix_swoim_czasem_takze_w_karcie_z_krotszym_domyslnym_limitem_playwrighta(tmp_path: Path, page: Page) -> None:
    filled = {"012": 1, "019": 2}
    orders = [
        Order("#8381", cells={"O": 1, "T": 2}, amount=_au(filled), emmett={"012": 1}),
        Order("#8382", day=date(2026, 8, 31), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    source = write_collective_file(tmp_path, orders)
    page.set_default_timeout(1)
    page.set_default_navigation_timeout(1)
    with atrapa_efenix([orders[0].in_efenix("901"), orders[1].in_efenix("902")], today=date(2026, 10, 12)) as atrapa:
        slow = {WindowAction.DATE: _SLOW_DATE_CLOSE, WindowAction.QUANTITY: _SLOW_AMOUNT}
        outcome = _run(source, page, atrapa.url, window=lambda efenix: _Before(efenix, _scripts(page, slow)))
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(2, 1),
        [("EFENIX_DATA_POZA_ZAKRESEM", "wiersz 19")],
    )
    assert pricing == {"8381": (filled, DAY, 1), "8382": ({}, None, 0)}


def _filled_in_t() -> tuple[list[Order], list[AtrapaOrder]]:
    order = Order("#8386", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), quantities={"012": 1})
    return [order], [replace(order.in_efenix("901"), execution_date=DAY)]


_COVERED = "document.body.insertAdjacentHTML('beforeend', '<div style=\"position: fixed; inset: 0; z-index: 9999\"></div>')"
_OTHER_SAVE = """() => document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const other = [...document.querySelectorAll('.wycena-ilosc')].find((field) => field !== event.target);
    const saving = new XMLHttpRequest();
    saving.open('POST', 'action_save_index.php', false);
    saving.send(new URLSearchParams({order_id: other.getAttribute('order_id'), index: other.id, rodzaj: 'ILOSC', parametr: other.value}));
}, {capture: true, once: true})"""


def test_pole_ilosc_zasloniete_na_stronie_zlecenia_to_zatrzymanie_okna_bez_wpisania_ilosci(tmp_path: Path, page: Page) -> None:
    orders, in_efenix = _filled_in_t()
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _run(
            write_collective_file(tmp_path, orders),
            page,
            atrapa.url,
            timeout_ms=1_000,
            window=lambda efenix: _Before(efenix, _scripts(page, {WindowAction.QUANTITY: _COVERED})),
        )
        pricing = _pricing(atrapa)

    assert isinstance(outcome.ending, Stop) and isinstance(outcome.ending.facts, PricingStopped), _ending(outcome)
    facts = outcome.ending.facts
    assert (_stop(outcome), facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        PagePart.QUANTITY,
        BrowserFailure(TIMEOUT, Operation.CLICK),
    )
    assert pricing == {"8386": ({"012": 1}, DAY, 0)}


def test_kwota_po_wpisaniu_ilosci_jest_z_odpowiedzi_na_zapis_tej_pozycji_a_nie_innej_zapisanej_w_tym_samym_czasie(
    tmp_path: Path, page: Page
) -> None:
    orders, in_efenix = _filled_in_t()
    with atrapa_efenix(in_efenix) as atrapa:
        outcome = _run(
            write_collective_file(tmp_path, orders),
            page,
            atrapa.url,
            window=lambda efenix: _Before(efenix, _scripts(page, {WindowAction.QUANTITY: _OTHER_SAVE})),
        )
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (pricing, requested.count(("POST", SAVE_QUANTITY))) == ({"8386": ({"012": 1, "019": 2}, DAY, 0)}, 2)


def test_strona_ktora_nie_odpowiada_konczy_dzialanie_okna_zatrzymaniem_w_czasie_okna(tmp_path: Path, page: Page) -> None:
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


def test_koniec_bloku_okna_nie_czeka_na_strone_ktorej_skrypt_nie_odpowiada(page: Page) -> None:
    with atrapa_efenix([]) as atrapa:
        with efenix_browser.window(_unhurried_start(page), atrapa.url, timeout_ms=2_000):
            page.evaluate("setTimeout(() => { const end = Date.now() + 20_000; while (Date.now() < end) {} }, 0)")
            with pytest.raises(PlaywrightError, match="Timeout"):
                page.locator(":root").wait_for(state="attached", timeout=1_000)

        with pytest.raises(PlaywrightError, match="Timeout"):
            page.locator(":root").wait_for(state="attached", timeout=1_000)


def test_tabela_wynikow_szukania_czyta_sie_bez_skryptow_i_obslugi_zdarzen_odpowiedzi(page: Page) -> None:
    html = (
        "<table><thead><tr><th>Numer dokumentu</th></tr></thead><tbody><tr>"
        '<td>8001<img src="data:," onerror="window.uruchomione = true"></td></tr></tbody></table>'
    )

    table = results_table(page, html)

    assert isinstance(table, ResultsTable) and table.headers == ("Numer dokumentu",)
    with pytest.raises(PlaywrightTimeoutError):
        page.wait_for_function("() => window.uruchomione === true", timeout=1_000)


def test_odpowiedz_szukania_z_tabela_nie_jest_ostrzezeniem_efenix_takze_z_tekstem_ostrzezenia(page: Page) -> None:
    answer = "<table><tbody><tr><td>Ostrzeżenie: Twoja sesja wygasła - zaloguj się ponownie !</td></tr></tbody></table>"

    assert search_warning(page, answer) is None


ERROR_ANSWERS = {
    "lista-na-starcie": (LIST_PAGE, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.LIST),
    "lista-ponownie": (LIST_PAGE, 2, HTTPStatus.NOT_FOUND, PagePart.LIST),
    "szukanie": (SEARCH, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.RESULTS),
    "data-wykonania": (SET_DATE, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.DATE),
    "zaladuj-do-zlecenia": (LOAD_EMMETT, 1, HTTPStatus.INTERNAL_SERVER_ERROR, PagePart.EMMETT),
    "ilosc-400": (SAVE_QUANTITY, 1, HTTPStatus.BAD_REQUEST, PagePart.QUANTITY),
}


@pytest.mark.parametrize(("path", "number", "status", "part"), ERROR_ANSWERS.values(), ids=ERROR_ANSWERS.keys())
def test_strona_bledu_serwera_efenix_na_kazde_zadanie_okna_zatrzymuje_wycene_do_maksa_ze_statusem_http(
    tmp_path: Path, page: Page, path: str, number: int, status: HTTPStatus, part: PagePart
) -> None:
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


def test_strona_zlecenia_ze_statusem_bledu_ktora_okno_przeczytalo_to_strona_zlecenia_a_zlecenie_jest_gotowe(
    tmp_path: Path, page: Page
) -> None:
    def with_error_status(route: Route) -> None:
        route.fulfill(response=route.fetch(), status=HTTPStatus.INTERNAL_SERVER_ERROR)

    page.route(lambda url: urlparse(url).path.endswith(f"/{ORDER_PAGE}"), with_error_status)
    with atrapa_efenix([_READY.in_efenix("952")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [_READY], timeout_ms=3_000)

    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(1, 1))


def _window_moments(atrapa: AtrapaEfenix, path: str, since: int = 0) -> list[float]:
    return [request.at for request in atrapa.requests[since:] if request.path == path and not request.by_list]


def test_w_tempie_ludzkim_zlecenie_z_zapisem_trwa_20_s_samo_sprawdzenie_idzie_bez_przerw_a_przerwa_nie_przekracza_progu_podtrzymania_sesji(
    tmp_path: Path, page: Page
) -> None:
    emmett = {"O": 1, "T": 2, "AG": 1}
    filled = _au({"012": 1, "019": 2, "015": 1})
    many = {column: 1 for column in ("O", "P", "Q", "R", "S", "T", "U", "V", "Y", "Z")}
    orders = [
        Order("#9801", day=date(2026, 9, 3), cells=emmett, amount=filled, emmett={"012": 1}),
        Order("#9802", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9803", day=date(2026, 9, 5), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9804", day=date(2026, 9, 6), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 2}),
        Order("#9805", day=date(2026, 9, 7), cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 2}),
        Order("#9806", day=date(2026, 9, 8), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9807", day=date(2026, 9, 9), cells=emmett, amount=filled, emmett={"012": 1}),
        Order("#9808", day=date(2026, 9, 10), cells=emmett, amount=filled, emmett={"012": 1}),
        Order("#9809", day=date(2026, 9, 11), cells=many, amount=_au({code: 1 for code in ("012", "013", "014", "017", "016", "019", "027", "029", "009", "010")}), emmett={"012": 1}),
        Order("#9810", day=date(2026, 9, 12), cells={"O": 1}, amount=_au({"012": 1})),
        Order("#9811", day=date(2026, 9, 13), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
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
    assert _window_moments(atrapa, SEARCH) == [0, 20, 20, 20, 20, 37, 37, 57, 77, 101, 118]
    assert _window_moments(atrapa, ORDER_PAGE) == [0, 2, 4, 20, 20, 20, 22, 37, 37, 39, 41, 57, 59, 61, 77, 79, 81, 101, 103, 118]
    assert _window_moments(atrapa, SET_DATE) == [2, 39, 59, 79, 103]
    assert _window_moments(atrapa, LOAD_EMMETT) == [4, 22, 41, 61, 81]
    assert _window_moments(atrapa, SAVE_QUANTITY) == [6, 8, 43, 45, 63, 65, *range(83, 100, 2)]
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


def test_strona_efenix_ze_statusem_2xx_bez_pola_numer_pod_adresem_listy_to_element_listy_a_nie_status_http(
    tmp_path: Path, page: Page
) -> None:
    orders = [Order("#9302")]
    with atrapa_efenix([orders[0].in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url.replace(LIST_PAGE, f"{ORDER_PAGE}?id=901"), orders, timeout_ms=3_000)

    assert isinstance(outcome.ending, Stop) and isinstance(outcome.ending.facts, PricingStopped), _ending(outcome)
    facts = outcome.ending.facts
    assert (_stop(outcome), facts.part, facts.cause) == ("EFENIX_OKNO_ZATRZYMANE", PagePart.LIST, ElementCount("#field_numer", 0))



YELLOW = "FFFF00"
READY_RGB = Mark.READY.value
CHANGED_PARTS = {"xl/worksheets/sheet1.xml", "xl/styles.xml"}


def _parts(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def _address_fills(source: Path) -> dict[int, str | None]:
    fills: dict[int, str | None] = {}
    for row in read_data_rows(source, DadFiles(), despite_excel_lock=True).rows:
        fill = row.cells[1].highlights.fill
        solid = isinstance(fill, PatternFill) and fill.patternType == "solid"
        fills[row.number] = str(fill.fgColor.rgb)[-6:].upper() if solid and isinstance(fill, PatternFill) else None
    return fills


def _marked(source: Path) -> list[int]:
    return [row for row, rgb in _address_fills(source).items() if rgb == READY_RGB]


def _address_looks(source: Path) -> dict[int, tuple[Font, Border, Protection, Alignment, str]]:
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
    return {row.number: row.value("AU") for row in read_computed_rows(source, DadFiles()).rows}


def _without_address_styles(xml: bytes, rows: Sequence[int]) -> bytes:
    def neutral(found: re.Match[bytes]) -> bytes:
        return found.group(1) if int(found.group(2)) in rows else found.group(0)

    return re.sub(rb'(<c r="B(\d+)")(?: s="\d+")?', neutral, xml)


STYLE_LISTS = {b"fills": b"fill", b"cellXfs": b"xf"}


def _style_list(styles: bytes, tag: bytes) -> re.Match[bytes]:
    found = re.search(rb"<" + tag + rb'\b[^>]*?count="(\d+)"[^>]*>(.*?)</' + tag + rb">", styles, re.S)
    assert found is not None, tag
    return found


def _style_counts(styles: bytes) -> dict[bytes, int]:
    counts = {}
    for tag, entry in STYLE_LISTS.items():
        found = _style_list(styles, tag)
        counts[tag] = len(re.findall(rb"<" + entry + rb"[\s>/]", found.group(2)))
        assert int(found.group(1)) == counts[tag], tag
    return counts


def _without_appended_styles(written: bytes, original: bytes) -> bytes:
    for tag in STYLE_LISTS:
        before, after = _style_list(original, tag), _style_list(written, tag)
        assert after.group(2).startswith(before.group(2)), tag
        written = written[: after.start()] + before.group(0) + written[after.end() :]
    return written


def _marking_orders() -> list[Order]:
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


def test_metryki_wyceny_licza_zlecenia_gotowe_bledy_ostrzezenia_emmetta_i_pominiete(tmp_path: Path) -> None:
    other_amount = [Order(number, cells={"O": 1}, amount=_au({"012": 1}) + 5) for number in ("#7707", "#7708")]
    orders = [order for order in _marking_orders() if order.number != "#7706"] + other_amount
    outcome = _run_in_process(write_collective_file(tmp_path, orders), StanEfenix(_marking_efenix(orders)))

    assert isinstance(outcome.ending, Finished), _ending(outcome)
    assert (outcome.ending.result, outcome.ending.counters) == (
        "WYMAGA_SPRAWDZENIA",
        {"orders": 6, "ready": 2, "errors": 3, "emmett_warnings": 1, "with_photos": 1, "defects": 0},
    )


def test_znacznik_efenix_staje_tylko_w_adresie_gotowych_zlecen_a_reszta_pliku_zostaje_bajt_w_bajt(tmp_path: Path) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    parts, looks, amounts = _parts(source), _address_looks(source), _amounts(source)
    outcome = _run_in_process(source, StanEfenix(_marking_efenix(orders)))

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(5, 2, warnings=1, photos=1))
    assert _address_fills(source) == {18: READY_RGB, 19: READY_RGB, 20: None, 21: None, 22: None, 23: YELLOW}
    assert _address_looks(source) == looks
    font, border, protection = looks[18][:3]
    assert (font.color.rgb if font.color else None, font.b, font.i) == ("FFFF0000", True, True)
    sides = (border.left, border.right, border.top, border.bottom)
    assert ([side.style if side else None for side in sides], protection.locked) == (["thin"] * 4, False)
    assert _amounts(source) == amounts
    written = _parts(source)
    assert [name for name, _ in written] == [name for name, _ in parts]
    before, after = dict(parts), dict(written)
    assert {name for name in before if before[name] != after[name]} == CHANGED_PARTS
    assert any(name.startswith("xl/externalLinks/") for name in before)
    sheet = "xl/worksheets/sheet1.xml"
    assert _without_address_styles(after[sheet], [18, 19]) == _without_address_styles(before[sheet], [18, 19])
    assert _without_appended_styles(after["xl/styles.xml"], before["xl/styles.xml"]) == before["xl/styles.xml"]
    counts, original = _style_counts(after["xl/styles.xml"]), _style_counts(before["xl/styles.xml"])
    assert (counts[b"fills"] - original[b"fills"], counts[b"cellXfs"] - original[b"cellXfs"]) == (1, 2)


def test_nastepny_przebieg_na_pliku_ze_znacznikami_czyta_kwoty_au_ma_te_same_gotowe_i_niczego_nie_zmienia(tmp_path: Path) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    efenix = StanEfenix(_marking_efenix(orders))
    first = _run_in_process(source, efenix)
    assert _figures(first) == _figures_of(5, 2, warnings=1, photos=1)
    marked, saved, state, changes = source.read_bytes(), source.stat().st_mtime_ns, efenix.state(), _changes(efenix)
    second = _run_in_process(source, efenix)

    assert (_figures(second), _marked(source), _amounts(source)[18]) == (_figures_of(5, 2, warnings=1, photos=1), [18, 19], _au({"012": 1}))
    assert [error for error in _errors(second) if error[1] in {"wiersz 20", "wiersz 21"}] == [
        ("EFENIX_INNA_KWOTA", "wiersz 20"),
        ("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 21"),
    ]
    assert (source.read_bytes() == marked, source.stat().st_mtime_ns == saved) == (True, True), (
        "Plik zbiorczy ze wszystkimi Znacznikami zapisany od nowa: OneDrive dostałby jego nową wersję"
    )
    assert (efenix.state() == state, _changes(efenix) == changes) == (True, True)


def test_kolejne_uruchomienie_oznacza_nowe_gotowe_zlecenie_wypelnieniem_i_stylem_z_poprzedniego(
    tmp_path: Path, page: Page
) -> None:
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
    with zipfile.ZipFile(source) as archive:
        parts = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for info, data in parts:
            archive.writestr(info.filename, data)


def _replaced(part: str, old: bytes, new: bytes) -> Callable[[dict[str, bytes]], dict[str, bytes]]:
    def change(parts: dict[str, bytes]) -> dict[str, bytes]:
        changed, count = re.subn(old, new, parts[part], count=1)
        assert count == 1, (part, old)
        return {part: changed}

    return change


def _address_style_past_cell_xfs(parts: dict[str, bytes]) -> dict[str, bytes]:
    count = int(_style_list(parts["xl/styles.xml"], b"cellXfs").group(1))
    return _replaced("xl/worksheets/sheet1.xml", rb'(<c r="B18") s="\d+"', rb'\1 s="%d"' % count)(parts)


def _shaped(tmp_path: Path, order: Order, shape: Callable[[dict[str, bytes]], dict[str, bytes]]) -> Path:
    source = write_collective_file(tmp_path, [order])
    changed = shape(dict(_parts(source)))
    rewrite_parts(source, lambda name, data: changed.get(name, data))
    return source


PRICED_UNMARKABLE_SHAPES = {
    "bez-relacji-skoroszytu": _replaced("_rels/.rels", rb'relationships/officeDocument"', b'relationships/document"'),
    "bez-relacji-stylow": _replaced("xl/_rels/workbook.xml.rels", rb'relationships/styles"', b'relationships/stylez"'),
    "komentarz-w-cellxfs": _replaced("xl/styles.xml", rb'<cellXfs count="\d+">', rb"\g<0><!--<xf/>-->"),
    "styl-adresu-za-cellxfs": _address_style_past_cell_xfs,
}

@pytest.mark.parametrize(
    ("shape", "extra", "ending"),
    [
        *(
            pytest.param(shape, 0, ("BLAD_KRYTYCZNY", "rozliczenia.workbook_parts.UnsupportedShape"), id=f"gotowe-zlecenie-{name}")
            for name, shape in PRICED_UNMARKABLE_SHAPES.items()
        ),
        pytest.param(PRICED_UNMARKABLE_SHAPES["bez-relacji-skoroszytu"], 1, ("WYMAGA_SPRAWDZENIA", None), id="bez-gotowych-zlecen"),
    ],
)
def test_wycena_pliku_w_ksztalcie_ktorego_zapis_znacznikow_nie_przenosi_to_blad_kodu_bez_zmiany_pliku(
    tmp_path: Path, shape: Callable[[dict[str, bytes]], dict[str, bytes]], extra: int, ending: tuple[str, str | None]
) -> None:
    order = Order("#7451", cells={"O": 1}, amount=_au({"012": 1}) + extra, quantities={"012": 1})
    source = _shaped(tmp_path, order, shape)
    before = source.read_bytes()
    outcome = _run_in_process(source, StanEfenix([order.in_efenix("751")]))

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
    source = _shaped(tmp_path, Order("#7451", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}), shape)
    content = source.read_bytes()

    with pytest.raises(UnsupportedShape):
        mark_orders(source, content, column, dict.fromkeys(rows, Mark.READY))
    assert source.read_bytes() == content


def test_znacznik_efenix_staje_na_arkuszu_ktory_czyta_odczyt_zakresu_takze_za_arkuszem_bez_relacji(tmp_path: Path) -> None:
    order = Order("#7461", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order], notes_sheet_first=True)
    without_id = _replaced("xl/workbook.xml", rb"<(\w+:)?sheets>", rb'\g<0><\1sheet name="Stary" sheetId="9" />')
    changed = without_id(dict(_parts(source)))
    rewrite_parts(source, lambda name, data: changed.get(name, data))
    notes = dict(_parts(source))["xl/worksheets/sheet1.xml"]

    refusal = mark_orders(source, source.read_bytes(), "B", {18: Mark.READY})

    with pytest.warns(UserWarning, match="invalid specification"):
        marked = _marked(source)
    assert (refusal, marked, dict(_parts(source))["xl/worksheets/sheet1.xml"] == notes) == (None, [18], True)


@contextmanager
def _excel_open(source: Path) -> Iterator[Callable[[], None]]:
    lock = excel_lock_file(source)
    def open_in_excel() -> None:
        lock.write_bytes(b"")

    yield open_in_excel
    lock.unlink(missing_ok=True)


@contextmanager
def _saved_in_excel(source: Path) -> Iterator[Callable[[], None]]:
    def save() -> None:
        rewrite_parts(source, lambda name, data: data.replace(b">MIASTO<", b">MIASTA<") if name == "xl/worksheets/sheet1.xml" else data)

    yield save


@contextmanager
def _read_only_folder(source: Path) -> Iterator[Callable[[], None]]:
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
    tmp_path: Path, obstacle: Callable[[Path], AbstractContextManager[Callable[[], None]]], code: str
) -> None:
    orders = [
        Order("#7801", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#7802", cells={"O": 1}, amount=_au({"012": 1})),
        Order("#7803", cells={"O": 1}, amount=_au({"012": 1}) + 5),
    ]
    source = write_collective_file(tmp_path, orders)
    efenix = StanEfenix([order.in_efenix(f"78{index}") for index, order in enumerate(orders)])
    with obstacle(source) as meanwhile:
        stopped = _run_in_process(source, efenix, meanwhile=meanwhile)
        unmarked = source.read_bytes()
        assert (_stop(stopped), _marked(source)) == (code, [])
    priced, changes = efenix.state(), _changes(efenix)
    assert source.read_bytes() == unmarked
    again = _run_in_process(source, efenix)

    assert {order.number: (order.quantities, order.execution_date, order.emmett_loads) for order in priced[0]} == {
        "7801": ({"012": 1}, DAY, 0),
        "7802": ({"012": 1}, DAY, 1),
        "7803": ({"012": 1}, DAY, 1),
    }
    assert (again.result, _figures(again), _marked(source)) == ("WYMAGA_SPRAWDZENIA", _figures_of(3, 2), [18, 19])
    assert (efenix.state() == priced, _changes(efenix) == changes) == (True, True)


@pytest.mark.parametrize(
    ("expire_after", "marked"),
    [
        pytest.param((Action.QUANTITY, 1), [18], id="po-pierwszym-gotowym"),
        pytest.param((Action.QUANTITY, 0), [], id="przed-pierwszym-gotowym"),
    ],
)
def test_zatrzymanie_w_polowie_przebiegu_oznacza_zlecenia_gotowe_przed_nim(
    tmp_path: Path, expire_after: tuple[Action, int], marked: list[int]
) -> None:
    orders = [Order(f"#790{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    source = write_collective_file(tmp_path, orders)
    unmarked = source.read_bytes()
    efenix = StanEfenix([order.in_efenix(f"79{index}") for index, order in enumerate(orders)], expire_after=expire_after)
    outcome = _run_in_process(source, efenix)

    assert (_stop(outcome), _marked(source)) == ("EFENIX_WYLOGOWANY", marked)
    assert (source.read_bytes() == unmarked) == (not marked)
    assert outcome.progress.step == SavingStep("Znaczniki efenix w Pliku zbiorczym", None, 0, 0)


def test_zapis_zatrzymania_wyceny_nie_pokazuje_numerow_zlecen_ani_adresow_ktore_niosa_jego_fakty_dla_logow(tmp_path: Path) -> None:
    orders = [Order(f"#791{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2)]
    stan = StanEfenix([order.in_efenix(f"79{index}") for index, order in enumerate(orders)], expire_after=(Action.QUANTITY, 1))
    outcome = _price_in_process(tmp_path, stan, orders)

    assert isinstance(outcome.ending, Stop) and isinstance(outcome.ending.facts, PricingStopped), _ending(outcome)
    assert _stop(outcome) == "EFENIX_WYLOGOWANY"
    shown = repr(outcome.ending)
    assert [text for text in ("7911", "7912", ADDRESS) if text in shown] == []


def _resumed_orders() -> list[Order]:
    cells, filled = {"O": 1, "T": 2, "AG": 1}, {"012": 1, "019": 2, "015": 1}
    return [Order(f"#990{index}", day=date(2026, 9, index), cells=cells, amount=_au(filled), emmett={"012": 1}) for index in (1, 2, 3)]


_ONE_ORDER = (
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", SET_DATE),
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", FILL_EMMETT), ("POST", LOAD_EMMETT),
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", SAVE_QUANTITY), ("POST", SAVE_QUANTITY),
)
WHOLE_RUN = (
    ("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), *_ONE_ORDER,
    ("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), ("POST", SEARCH), *_ONE_ORDER,
)
_LIST_ON_START = WHOLE_RUN.index(("POST", SEARCH))
_READ_BY_WINDOW = tuple(WHOLE_RUN.index(("POST", path)) for path in (SEARCH, FILL_EMMETT, SAVE_QUANTITY))
_SECOND_ORDER_PAGE_REPEATS_FIRST = WHOLE_RUN.index(("GET", ORDER_PAGE), WHOLE_RUN.index(("GET", LIST_PAGE), 1))
_WRITES = {("POST", path) for path in (SET_DATE, LOAD_EMMETT, SAVE_QUANTITY)}
_FULL_SWEEP_BEFORE_WINDOW_OR_OUTAGE_CHANGE = os.environ.get("PELNY_PRZEGLAD_EFENIX") == "1"
SWEEP = [
    pytest.param(first, outage, id=f"{first:02d}-{path.replace('/', '-')}-{outage.name}")
    for first, (method, path) in enumerate(WHOLE_RUN)
    for outage in Outage
    if _FULL_SWEEP_BEFORE_WINDOW_OR_OUTAGE_CHANGE
    or (outage is Outage.CUT and (first < _SECOND_ORDER_PAGE_REPEATS_FIRST or (method, path) in _WRITES))
    or first in _READ_BY_WINDOW
]


@dataclass(frozen=True)
class _WholeRun:
    original: Path
    source: Path
    pricing: dict[str, tuple[dict[str, int], date | None, int]]


def _two_orders() -> list[Order]:
    return _resumed_orders()[:2]


def _two_in_efenix() -> list[AtrapaOrder]:
    return [order.in_efenix(f"99{index}") for index, order in enumerate(_two_orders())]


@pytest.fixture(scope="module")
def whole_run(tmp_path_factory: pytest.TempPathFactory, browser: Browser) -> _WholeRun:
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
    resumed = tmp_path / PERIOD / whole_run.original.name
    resumed.parent.mkdir(parents=True)
    shutil.copy2(whole_run.original, resumed)
    timeout_ms = 2_000
    with atrapa_efenix(_two_in_efenix(), outage_from=(outage, first)) as atrapa:
        untouched = _pricing(atrapa)
        with page_of(browser) as window:
            stopped = _run(resumed, window, atrapa.url, timeout_ms=timeout_ms, hurried_start=first < _LIST_ON_START)
        after_stop = _pricing(atrapa)
        atrapa.reconnect()
        with page_of(browser) as window:
            again = _run(resumed, window, atrapa.url)
        priced_again, status_changes = _pricing(atrapa), atrapa.status_changes()

    assert isinstance(stopped.ending, Stop), _ending(stopped)
    not_opened, window_stop = ("EFENIX_NIEDOSTEPNY", "for_tata"), ("EFENIX_OKNO_ZATRZYMANE", "for_maks")
    list_page, list_script = WHOLE_RUN.index(("GET", LIST_PAGE)), WHOLE_RUN.index(("GET", LIST_SCRIPT))
    allowed = {list_page: [not_opened], list_script: [not_opened, window_stop]}.get(first, [window_stop])
    assert (stopped.ending.message.code, stopped.ending.stop_kind) in allowed, (
        "bez strony listy przy starcie okno nie otworzyło efenix, a bez jej skryptu otwarcie kończy się albo nie,"
        " zależnie od tego, czy przeglądarka czekała na skrypt do końca czasu okna"
    )
    facts = stopped.ending.facts
    assert isinstance(facts, PricingStopped)
    assert not isinstance(facts.cause, BrowserFailure) or facts.cause.operation is not None, facts.cause
    if WHOLE_RUN[first] == ("POST", FILL_EMMETT) and outage in (Outage.CUT, Outage.TORN):
        assert facts.part is PagePart.EMMETT and isinstance(facts.cause, BrowserFailure), (facts.part, facts.cause)
        assert facts.cause.operation is Operation.ANSWER, facts.cause
    if WHOLE_RUN[first] == ("GET", LIST_PAGE) and outage is Outage.CUT:
        assert (facts.part, facts.cause) == (PagePart.LIST, BrowserFailure(PLAYWRIGHT_ERROR, Operation.OPEN))
    early: dict[int, list[int | None]] = {0: [None], 1: [None, 18]}
    rows = early.get(first, [18] if first < WHOLE_RUN.index(("GET", LIST_PAGE), 1) else [19])
    at = facts.stopped_at
    assert (None if at is None else at.row) in rows, (at, rows)
    if at is not None:
        assert (at.place, at.total) == (at.row - 17, 2), at
        assert at.failed is not None and at.failed.duration_ms < 2 * timeout_ms, at
    assert [result.order.row for result in facts.summary.results] == list(range(18, 18 if at is None else at.row))
    assert _kept(stopped) or after_stop == untouched, (after_stop, untouched)
    assert status_changes == 0
    assert (_figures(again), _errors(again), priced_again) == (_figures_of(2, 2), [], whole_run.pricing)
    assert (_parts(resumed), _marked(resumed)) == (_parts(whole_run.source), [18, 19])


_T_FOR_FREE = {**PRICES, "019": Decimal("0.00")}


@pytest.mark.parametrize(
    ("refusal", "code", "cause", "prices"),
    [
        pytest.param(EmmettRefusal.FORBIDDEN, "EFENIX_OKNO_ZATRZYMANE", HttpStatus(403), PRICES, id="403-bez-zaladowania"),
        pytest.param(EmmettRefusal.SERVER_ERROR, "EFENIX_OKNO_ZATRZYMANE", HttpStatus(500), PRICES, id="500-po-zaladowaniu"),
        pytest.param(EmmettRefusal.LOGGED_OUT, "EFENIX_WYLOGOWANY", LoginSign.REDIRECT, PRICES, id="przekierowanie-na-logowanie"),
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
    tmp_path: Path, refusal: EmmettRefusal, code: str, cause: WindowCause, prices: dict[str, Decimal]
) -> None:
    orders = [
        Order("#9701", day=date(2026, 9, 1), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9702", day=date(2026, 9, 2), cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"019": 5}),
    ]
    source = write_collective_file(tmp_path, orders)
    efenix = StanEfenix([orders[0].in_efenix("971"), replace(orders[1].in_efenix("972"), emmett_refusal=refusal)], prices=prices)
    stopped = _run_in_process(source, efenix)
    refused = _pricing(efenix)["9702"]
    marked = _marked(source)
    efenix.log_in()
    efenix.edit("9702", lambda order: setattr(order, "emmett_refusal", None))
    again = _run_in_process(source, efenix)
    resumed = _pricing(efenix)["9702"]

    loaded = refusal is EmmettRefusal.SERVER_ERROR
    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    facts = stopped.ending.facts
    assert (_stop(stopped), _kept(stopped), facts.part, facts.cause) == (code, True, PagePart.EMMETT, cause)
    assert facts.stopped_at is not None and facts.stopped_at.failed is not None, facts.stopped_at
    assert ([step.action for step in facts.stopped_at.steps], facts.stopped_at.failed.action) == (
        [WindowAction.SEARCH, WindowAction.OPEN, WindowAction.DATE, WindowAction.OPEN],
        WindowAction.EMMETT,
    )
    assert (refused, marked) == (({"019": 5} if loaded else {}, date(2026, 9, 2), int(loaded)), [18])
    assert (_errors(again), _marked(source)) == ([("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 19")], [18])
    assert resumed == ({"012": 1, "019": 5}, date(2026, 9, 2), 1)


def test_odmowa_zaladuj_do_zlecenia_po_propozycji_emmetta_w_polach_bez_tekstu_zatrzymuje_wycene_bez_znacznika(
    tmp_path: Path, page: Page
) -> None:
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
        [WindowAction.SEARCH, WindowAction.OPEN],
        True,
    )
    assert (pricing, _marked(source)) == ({"9741": ({}, DAY, 0)}, [])



@pytest.mark.parametrize("failure", list(ProposalFailure), ids=lambda failure: failure.name)
def test_propozycja_emmetta_ktora_padla_zostawia_okno_emmetta_puste_jak_w_efenix_a_zaladuj_do_zlecenia_i_tak_laduje(
    tmp_path: Path, page: Page, failure: ProposalFailure
) -> None:
    order = Order("#9721", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    in_efenix = replace(order.in_efenix("9721"), emmett_proposal_failure=failure)
    proposal: list[int | str] = []
    page.on("response", lambda response: proposal.append(response.status) if response.url.endswith(FILL_EMMETT) else None)
    page.on("requestfailed", lambda request: proposal.append("zerwana") if request.url.endswith(FILL_EMMETT) else None)
    with atrapa_efenix([in_efenix]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert proposal == {ProposalFailure.SERVER_ERROR: [500], ProposalFailure.TORN: [200, "zerwana"], ProposalFailure.CUT: ["zerwana"]}[failure], (
        "przeglądarka nie dostała propozycji tak, jak padła, więc test sprawdzałby propozycję, która przyszła cała"
    )
    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(1, 1), [])
    assert (pricing, _marked(source)) == ({"9721": ({"012": 1, "019": 2}, DAY, 1)}, [18])


def test_propozycja_emmetta_ktora_padla_a_potem_odmowa_zaladuj_do_zlecenia_2xx_zatrzymuje_wycene_bez_ilosci_i_znacznika(
    tmp_path: Path,
) -> None:
    order = Order("#9721", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([replace(order.in_efenix("9721"), emmett_proposal_failure=ProposalFailure.CUT, emmett_refusal=EmmettRefusal.OTHER)])
    stopped = _run_in_process(source, efenix)
    pricing = _pricing(efenix)

    assert isinstance(stopped.ending, Stop) and isinstance(stopped.ending.facts, PricingStopped), _ending(stopped)
    facts = stopped.ending.facts
    assert (_stop(stopped), facts.part, facts.cause) == (
        "EFENIX_OKNO_ZATRZYMANE",
        PagePart.EMMETT,
        OtherShape(Shape.EMMETT_NOT_LOADED),
    )
    assert (pricing, _marked(source)) == ({"9721": ({}, DAY, 0)}, [])


# ZEWNĘTRZNE: Chromium porzuca treść odpowiedzi poprzedniego dokumentu, gdy przeładowanie strony wyprzedzi jej odczyt, co na wolnym komputerze wypada po „Załaduj do zlecenia” (pomiar na runnerze Windows w CI)
@dataclass
class _ReloadFirst:
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
        pytest.param((Action.EMMETT, 0), id="przy-zaladuj-do-zlecenia"),
        pytest.param((Action.OPEN, 1), id="po-dacie-przed-emmettem"),
    ],
)
def test_przerwanie_przed_wycena_emmetta_a_potem_wycena_zaczeta_przez_tate_ponowne_uruchomienie_dokancza_bez_emmetta(
    tmp_path: Path, expire_after: tuple[Action, int]
) -> None:
    filled = {"012": 1, "019": 2}
    order = Order("#5201", cells={"O": 1, "T": 2}, amount=_au(filled), emmett={"012": 1, "019": 5})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([order.in_efenix("921")], expire_after=expire_after)
    stopped = _run_in_process(source, efenix)
    efenix.log_in()
    efenix.edit("5201", lambda edited: edited.quantities.update({"012": 1}))
    again = _run_in_process(source, efenix)
    pricing = _pricing(efenix)

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
    tmp_path: Path, amount: float, errors: list[tuple[str, str]]
) -> None:
    order = Order("#5301", cells={"O": 1, "T": 2}, amount=amount, emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([order.in_efenix("931")])
    priced = _run_in_process(source, efenix)
    efenix.edit("5301", lambda edited: edited.quantities.pop("019"))
    again = _run_in_process(source, efenix)
    pricing = _pricing(efenix)

    assert (_errors(priced), _errors(again)) == (errors, errors)
    assert pricing == {"5301": ({"012": 1, "019": 2}, DAY, 1)}


def _interrupted(source: Path, orders: Sequence[Order]) -> StanEfenix[AtrapaOrder]:
    efenix = StanEfenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=(Action.QUANTITY, 3))
    assert _stop(_run_in_process(source, efenix)) == "EFENIX_WYLOGOWANY"
    assert _pricing(efenix)["9902"][0] == {"012": 1, "015": 1}, "wylogowanie w połowie ilości zlecenia 2: O od Emmetta i AG, bez T"
    efenix.log_in()
    return efenix


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
        pytest.param(
            lambda order: order.quantities.update({"019": 2}), {"012": 1, "015": 1, "019": 2}, [], id="ilość-pliku-w-pozycji-pustej-u-emmetta"
        ),
    ],
)
def test_przerwana_wycena_ktora_tata_zmienil_potem_w_efenix_ponowne_uruchomienie_dokancza_tylko_w_gore(
    tmp_path: Path, change: Callable[[AtrapaOrder], object], after: dict[str, int], errors: list[tuple[str, str]]
) -> None:
    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    efenix = _interrupted(source, orders)
    efenix.edit("9902", change)
    again = _run_in_process(source, efenix)
    pricing = _pricing(efenix)["9902"]

    assert (_figures(again), _errors(again)) == (_figures_of(3, 3 - len(errors), warnings=len(errors)), errors)
    assert (pricing, _marked(source)) == ((after, date(2026, 9, 2), 1), [18, 19, 20] if not errors else [18, 20])


def test_przerwana_wycena_po_zmianie_pliku_przez_tate_ponowne_uruchomienie_dokancza_do_nowego_pliku(tmp_path: Path) -> None:
    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    filled = {"012": 2, "019": 2, "015": 1}
    changed = replace(orders[1], cells={**orders[1].cells, "O": 2}, amount=_au(filled))
    efenix = _interrupted(source, orders)
    write_collective_file(tmp_path, [orders[0], changed, orders[2]])
    again = _run_in_process(source, efenix)
    after = _pricing(efenix)["9902"]

    assert (again.result, _figures(again), _errors(again)) == ("OK", _figures_of(3, 3), [])
    assert after == (filled, date(2026, 9, 2), 1)


def test_po_ostrzezeniu_emmetta_tata_poprawia_plik_a_ponowne_uruchomienie_stawia_znacznik_bez_zmian_w_efenix(tmp_path: Path) -> None:
    order = Order("#9601", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 2})
    source = write_collective_file(tmp_path, [order])
    efenix = StanEfenix([order.in_efenix("961")])
    first = _run_in_process(source, efenix)
    warned = _pricing(efenix)
    write_collective_file(tmp_path, [replace(order, cells={"O": 2, "T": 2}, amount=_au({"012": 2, "019": 2}))])
    since = _changes(efenix)
    again = _run_in_process(source, efenix)

    assert [_errors(outcome) for outcome in (first, again)] == [[("EFENIX_WIECEJ_NIZ_PLIK", "wiersz 18")], []]
    assert (warned, _pricing(efenix), _marked(source)) == ({"9601": ({"012": 2, "019": 2}, DAY, 1)},) * 2 + ([18],)
    assert _changes(efenix) == since



LOGIN_STEP = SavingStep("Zaloguj się w oknie efenix", None, 0, 0)


def test_okno_na_stronie_logowania_czeka_az_tata_sie_zaloguje_a_czas_czekania_nie_liczy_sie_do_czasow_uruchomienia(
    tmp_path: Path, page: Page
) -> None:
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
            EfenixInputs(source, lambda login: efenix_browser.window(page, atrapa.url, login=login), pace=None),
            LoggingIn(),
            view=lambda _inputs, summary: summary,
            metrics_path=metrics,
            context=RunContext(clock=RunClock(lambda: now[0])),
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
    orders = [Order("#5501", cells={"O": 1}, amount=_au({"012": 1}))]
    with atrapa_efenix([orders[0].in_efenix("551")]) as atrapa:
        atrapa.expire_session()
        not_logged_in = _run_with(
            write_collective_file(tmp_path / "bez-logowania", orders),
            lambda login: efenix_browser.window(page, atrapa.url, login=login, login_timeout_ms=1),
        )
        no_browser = _on_own_playwright_thread(
            _run_with,
            write_collective_file(tmp_path / "bez-chrome", orders),
            lambda login: efenix_browser.chrome(atrapa.url, tmp_path / "profil", login, channel="chrome-niezainstalowany"),
        )
        requested = atrapa.requested()

    assert (_stop(not_logged_in), _stop(no_browser)) == ("EFENIX_WYLOGOWANY", "EFENIX_BRAK_PRZEGLADARKI")
    assert (_kept(not_logged_in), _kept(no_browser)) == (False, False)
    assert set(requested) <= READ_ONLY_REQUESTS | {("GET", "page_login.php")}


def test_chromium_skryptu_dla_maszyn_ktory_nie_wystartowal_zatrzymuje_wycene_jak_okno_taty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "bez-przegladarek"))
    source = write_collective_file(tmp_path / "bez-chromium", [Order("#5501", cells={"O": 1}, amount=_au({"012": 1}))])
    outcome = _on_own_playwright_thread(_run_with, source, lambda _login: efenix_browser.chromium("http://127.0.0.1:9/"))

    assert (_stop(outcome), _kept(outcome)) == ("EFENIX_BRAK_PRZEGLADARKI", False)
    assert isinstance(outcome.ending, Stop) and isinstance(outcome.ending.facts, PricingStopped), _ending(outcome)
    assert outcome.ending.facts.cause == BrowserFailure(PLAYWRIGHT_ERROR, Operation.START)


def test_okno_taty_otwiera_liste_zlecen_w_jedynej_karcie_przegladarki(tmp_path: Path) -> None:
    profile = tmp_path / "profil"

    def tabs(url: str) -> list[str]:
        with efenix_browser.chrome(url, profile, nullcontext, channel=None, headless=True, arguments=["--remote-debugging-port=0"]):
            port = (profile / "DevToolsActivePort").read_text(encoding="utf-8").split()[0]
            with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as answer:
                return [target["url"] for target in json.load(answer) if target["type"] == "page"]

    with atrapa_efenix([]) as atrapa:
        shown = _on_own_playwright_thread(tabs, atrapa.url, timeout=120)

    assert shown == [atrapa.url]


def test_przegladarka_okna_ktora_nie_zalozyla_profilu_nie_zostawia_dziennika_w_katalogu_roboczym(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "katalog-roboczy"
    working.mkdir()
    profile = tmp_path / "przegladarka-efenix"
    profile.write_text("", encoding="utf-8")
    monkeypatch.chdir(working)

    def start() -> None:
        with pytest.raises(WindowStop), efenix_browser.chrome("http://127.0.0.1:9/", profile, nullcontext, channel=None, headless=True):
            pass

    _on_own_playwright_thread(start, timeout=120)

    # ZEWNĘTRZNE: chromium-headless-shell na Windows pisze dziennik błędu startu debug.log w katalogu roboczym procesu, gdy nie dostanie innego miejsca (pomiar na runnerze Windows w CI)
    assert sorted(path.name for path in working.iterdir()) == []


def test_strona_efenix_w_oknie_taty_ma_rozmiar_okna_przegladarki(tmp_path: Path) -> None:
    profile = tmp_path / "profil"

    def size(url: str) -> list[int]:
        arguments = ["--remote-debugging-port=0", "--window-size=900,700"]
        with efenix_browser.chrome(url, profile, nullcontext, channel=None, headless=True, arguments=arguments):
            port = (profile / "DevToolsActivePort").read_text(encoding="utf-8").split()[0]
            return _on_own_playwright_thread(outside_size, port, url, timeout=60)

    def outside_size(port: str, url: str) -> list[int]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            [page] = [page for context in browser.contexts for page in context.pages if page.url == url]
            return cast(list[int], page.evaluate("[innerWidth, innerHeight]"))

    with atrapa_efenix([]) as atrapa:
        shown = _on_own_playwright_thread(size, atrapa.url, timeout=120)

    assert shown == [900, 700]


def test_okno_czeka_na_logowanie_taty_15_minut_a_potem_daje_wylogowanie(page: Page) -> None:
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
    _opened_at_start, _dads_tab_after_login, window_question = 1, 2, 3
    with atrapa_efenix([], error_answer=(LIST_PAGE, window_question, HTTPStatus.INTERNAL_SERVER_ERROR)) as atrapa:
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
    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()

        @contextmanager
        def walking_away() -> Iterator[None]:
            page.goto(urljoin(atrapa.url, LIST_SCRIPT))
            yield

        with pytest.raises(LoggedOut), efenix_browser.window(page, atrapa.url, login=walking_away, login_timeout_ms=500):
            pass
        asked = _session_question_moments(atrapa)

    assert len(asked) == 2, asked
    assert asked[1] - asked[0] >= efenix_browser.LOGIN_POLL_MS / 1000


def _session_question_moments(atrapa: AtrapaEfenix) -> list[float]:
    _opened_at_start, *questions = [request.at for request in atrapa.requests if request.path == LIST_PAGE]
    return questions


def _session_questions(atrapa: AtrapaEfenix) -> int:
    return len(_session_question_moments(atrapa))


def test_karta_na_stronie_logowania_bez_logowania_taty_pyta_efenix_o_sesje_co_login_poll_ms_az_do_limitu(page: Page) -> None:
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


def test_lista_ktora_nie_odpowiada_w_czasie_czekania_na_logowanie_nie_konczy_czekania_a_po_limicie_to_niedostepny_efenix(
    page: Page,
) -> None:
    page.context.set_default_timeout(2 * efenix_browser.LOGIN_POLL_MS)
    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()

        @contextmanager
        def efenix_silent() -> Iterator[None]:
            atrapa.outage = Outage.SLOW
            yield

        with (
            pytest.raises(EfenixUnreachable) as stopped,
            efenix_browser.window(
                _unhurried_start(page),
                atrapa.url,
                timeout_ms=efenix_browser.LOGIN_POLL_MS // 4,
                login=efenix_silent,
                login_timeout_ms=efenix_browser.LOGIN_POLL_MS * 3 // 2,
            ),
        ):
            pass
        questions = _session_questions(atrapa)

    assert questions >= 2
    assert (stopped.value.part, stopped.value.cause, type(stopped.value.__cause__)) == (
        PagePart.LIST,
        BrowserFailure(TIMEOUT, Operation.OPEN),
        PlaywrightTimeoutError,
    )


@pytest.mark.parametrize(
    ("unanswered", "stop", "questions"),
    [
        pytest.param((898.0,), LoggedOut, 2, id="jedno-zerwanie-tuz-przed-limitem"),
        pytest.param((840.5,), LoggedOut, 2, id="cisza-krotsza-niz-dwa-czasy-okna"),
        pytest.param((840.0,), EfenixUnreachable, 2, id="cisza-przez-dwa-czasy-okna"),
        pytest.param((850.0, 882.0, 914.0), EfenixUnreachable, 3, id="efenix-wisi-a-ostatnie-pytanie-konczy-sie-po-limicie"),
    ],
)
def test_po_limicie_czekania_na_logowanie_niedostepny_efenix_tylko_gdy_efenix_milczal_przez_dwa_czasy_okna(
    page: Page, unanswered: tuple[float, ...], stop: type[Exception], questions: int
) -> None:
    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()
        readings = iter([0.0, *unanswered])

        def clock() -> float:
            reading = next(readings, efenix_browser.LOGIN_TIMEOUT_MS / 1000)
            if reading == unanswered[0]:
                atrapa.outage = Outage.CUT
            return reading

        with pytest.raises(stop), efenix_browser.window(page, atrapa.url, login=nullcontext, clock=clock):
            pass
        asked = _session_questions(atrapa)

    assert asked == questions


def test_przegladarka_zamknieta_przed_pytaniem_o_sesje_na_granicy_limitu_to_zamkniete_okno(page: Page) -> None:
    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()
        before_first_question = False
        closed_by_tata = asked_document = False
        is_closed, locator = page.is_closed, page.locator

        def closing_unnoticed() -> bool:
            nonlocal before_first_question, closed_by_tata
            if before_first_question:
                before_first_question = False
                page.context.close()
                closed_by_tata = True
                return False
            return is_closed() and (asked_document or not closed_by_tata)

        def asking(selector: str, **options: Any) -> Locator:
            nonlocal asked_document
            asked_document = asked_document or (closed_by_tata and selector == ":root")
            return locator(selector, **options)

        readings = iter([0.0])

        def clock() -> float:
            nonlocal before_first_question
            reading = next(readings, 3600.0)
            before_first_question = reading == 0.0
            return reading

        page.is_closed = closing_unnoticed  # type: ignore[method-assign]
        page.locator = asking  # type: ignore[method-assign]
        with pytest.raises(WindowClosed) as stopped, efenix_browser.window(page, atrapa.url, login=nullcontext, clock=clock):
            pass

    assert (stopped.value.part, stopped.value.cause) == (PagePart.LIST, Closed.DURING_LOGIN)


def test_siec_ktora_znika_w_czasie_czekania_na_logowanie_i_wraca_przed_limitem_a_tata_sie_nie_loguje_daje_wylogowanie(
    tmp_path: Path, page: Page
) -> None:
    orders = [Order("#5701", cells={"O": 1}, amount=_au({"012": 1}))]
    with atrapa_efenix([orders[0].in_efenix("571")]) as atrapa:
        atrapa.expire_session()
        readings = iter([0.0, 1.0])

        def clock() -> float:
            reading = next(readings, 3600.0)
            if reading == 1.0:
                atrapa.reconnect()
            return reading

        def network_gone(login: Login) -> Login:
            @contextmanager
            def waiting() -> Iterator[None]:
                with login():
                    atrapa.outage = Outage.CUT
                    yield

            return waiting

        outcome = _run_with(
            write_collective_file(tmp_path, orders),
            lambda login: efenix_browser.window(page, atrapa.url, login=network_gone(login), clock=clock),
        )
        questions = _session_questions(atrapa)

    assert (_stop(outcome), _kept(outcome), questions) == ("EFENIX_WYLOGOWANY", False, 2)


def test_profil_przegladarki_okna_efenix_lezy_w_katalogu_narzedzia_poza_gitem() -> None:
    profile = efenix_browser.default_profile()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", str(profile / "Default" / "Cookies")], cwd=TOOL_ROOT, check=False
    )

    assert (profile.parent, ignored.returncode) == (TOOL_ROOT, 0)


_FIRST_LAUNCH_OPTIONS_OF_A_PROCESS = """
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from rozliczenia.efenix_browser import launch_options

with sync_playwright() as playwright:
    launch_options(playwright)
    print(sorted(path.name for path in Path(sys.argv[1]).iterdir()))
"""


def test_argumenty_okna_efenix_nie_zostawiaja_otwartej_przegladarki_z_ktorej_wziely_liste_playwrighta(tmp_path: Path) -> None:
    temporary = tmp_path / "tymczasowy"
    temporary.mkdir()
    folders = {"TMPDIR": str(temporary), "TEMP": str(temporary), "TMP": str(temporary)}
    listed = subprocess.run(
        [sys.executable, "-c", _FIRST_LAUNCH_OPTIONS_OF_A_PROCESS, str(temporary)],
        env={**os.environ, **folders, "PYTHONPATH": str(TOOL_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=100,
        check=True,
    )

    # ZEWNĘTRZNE: Playwright trzyma profil przeglądarki uruchomionej bez okna w folderze tymczasowym systemu, dopóki jej nie zamknie (Playwright, katalog playwright_chromiumdev_profile-*)
    assert listed.stdout.strip() == "[]"


def _run_with(source: Path, open_efenix: Callable[[Login], AbstractContextManager[efenix_browser.BrowserEfenix]]) -> Priced:
    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(source, open_efenix, pace=None),
        Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=source.parent.parent / "metryki.jsonl",
        context=RunContext(),
    )


@dataclass
class _OpensInExcelAfterChecking(Tata):
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
    orders = [Order("#7601", cells={"O": 1}, amount=_au({"012": 1}))]
    source = write_collective_file(tmp_path, orders)
    if not after_checking:
        excel_lock_file(source).write_bytes(b"")
    with atrapa_efenix([orders[0].in_efenix("761")]) as atrapa:
        outcome = _run(source, page, atrapa.url, tata=_OpensInExcelAfterChecking(source=source) if after_checking else None)
        requested = atrapa.requested()

    assert (_stop(outcome), requested, _kept(outcome)) == ("EFENIX_PLIK_ZBIORCZY_OTWARTY", [], False)
    assert [phase for phase, state in outcome.progress.phase_states.items() if state is PhaseState.FAILED] == [failed]


def test_plik_zbiorczy_ze_znacznikami_daje_w_przebiegu_rozliczen_rozliczenie_pracownika_bez_nich(tmp_path: Path) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    _run_in_process(source, StanEfenix(_marking_efenix(orders)))
    template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(template)
    assert _marked(source) == [18, 19]

    summary = run_settlements(
        SettlementInputs(source, worker_list(), template),
        RunContext(),
    )

    assert summary.written_count == 1
    written = PeriodFolder.from_collective_file(source).worker_settlement("Adrian Testowy")
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


def test_slad_zlecenia_ma_chwile_rozpoczecia_kazdego_dzialania_okna_efenix_takze_tego_ktore_sie_nie_udalo() -> None:
    time = _FakeTime(seconds=1.0)
    trace = efenix_trace.OrderTrace()
    order = CollectiveOrder(18, "9901", "adrian.testowy", "UL. TESTOWA 1", DAY, {}, Decimal(0))

    def slow(action: WindowAction) -> None:
        time.pause(3.0)
        if action is WindowAction.OPEN:
            raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))

    efenix = _Before(OknoWProcesie(StanEfenix([AtrapaOrder("1", "9901", "", "", status="Nowe")])), slow)
    window = efenix_trace.traced(efenix, order, trace, time, lambda: _TRACE_START + timedelta(seconds=time.seconds))

    [listed] = window.search("9901")
    time.pause(1.0)
    with pytest.raises(UnexpectedPage):
        window.open_order(listed)

    read = ListedRead(same_number=True, status="Nowe", realizator=None, address=(AddressPart.EFENIX_UNREAD,))
    assert trace.steps == [efenix_trace.TraceStep(WindowAction.SEARCH, _TRACE_START + timedelta(seconds=1), 3000, found=1, results=(read,))]
    assert trace.failed == efenix_trace.TraceStep(WindowAction.OPEN, _TRACE_START + timedelta(seconds=5), 3000)




class _SwitchedOff(BaseException):
    pass


def test_zgasniecie_centrum_w_przerwie_tempa_przed_iloscia_daje_wznowienie_ktore_konczy_zlecenie_jak_jeden_przebieg(
    tmp_path: Path, page: Page
) -> None:
    filled = {"012": 1, "019": 2}
    order = Order("#5501", cells={"O": 1, "T": 2}, amount=_au(filled), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    clock = _FakeTime()
    pauses = 0

    def switching_off_before_quantity(seconds: float) -> None:
        nonlocal pauses
        clock.pause(seconds)
        pauses += 1
        pause_before_t = 3
        if pauses == pause_before_t:
            raise _SwitchedOff

    with atrapa_efenix([order.in_efenix("951")], clock=clock) as atrapa:
        with pytest.raises(_SwitchedOff):
            _run(source, page, atrapa.url, pace=Pace(sleep=switching_off_before_quantity, clock=clock))
        switched_off = _pricing(atrapa)["5501"]
        again = _run(source, _next_tab(page), atrapa.url)
        pricing = _pricing(atrapa)

    assert switched_off == ({"012": 1}, DAY, 1)
    assert (again.result, _errors(again), pricing, _marked(source)) == ("OK", [], {"5501": (filled, DAY, 1)}, [18])
