"""Exhaustively break each request of a Wycena w efenix and check the Zatrzymanie, the efenix state and the resume.

The checker runs the real process (``run_process`` with ``efenix_process.PROCESS``, the window ``efenix_browser.window``
in Playwright's Chromium, ``pace=None``) on the Atrapa efenix (``tests/fixtures/atrapa_efenix.py``) with two orders of a
synthetic Plik zbiorczy: order 1 (row 18) has an empty pricing, Emmett gives O as the file and T one less than the
file, and the process enters T over Emmett's and adds AG, so it ends gotowe with a Znacznik efenix; order 2 (row 19) has
an empty pricing and an Emmett with more than the file in T, so it ends with an Ostrzeżenie Emmetta (ADR 0026). Between the window and the Atrapa sits the proxy of ``awarie_efenix.py``.

First a run without a fault (the reference) gives the window's requests, which must be exactly ``EXPECTED_CALLS``
(otherwise the space is stale: ``LUKA MODELU``), and the state of the Atrapa, the Plik zbiorczy and the dziennik before
and after each request, which is what a killed tool leaves (``Fault.KILLED``, checked as it
is). Then each request gets each other ``Fault`` in its own run (run 1), and every run that stopped or was killed gets a
second Uruchomienie (run 2) after Dad logs in and the network is back, once as it is and once after each change Dad
could make by hand in efenix between them (``Edit``): he finishes the order himself, removes a quantity Emmett gave,
removes a quantity the process added, or prices the empty order himself without Emmett. Second runs from the same state
that broke in the place and way of the same accepted risks (``RiskShape.window``, none today) are run once.

The invariants (``Rule``), each with the domain sentence it comes from:

- PRZYCZYNA: a Zatrzymanie names the fault the way the docstrings of ``efenix_browser`` and ``efenix_pricing.WindowCause``
  sort it, at the order of the faulted request: a broken network or a late answer is a browser failure with a named
  operation (or ``EfenixUnreachable`` before the list opened), an error page of the order page is ``HttpStatus``, a
  login is ``LoggedOut``, a closed tab is ``WindowClosed``, a „Załaduj do zlecenia” efenix answered with 2xx without
  loading Emmett is ``Shape.EMMETT_NOT_LOADED``; only a page efenix really sent in another shape may be a shape
  (``ElementCount``, ``OtherShape``). A run that does not stop ends like the reference, or leaves the faulted order to
  Dad; it never makes another order gotowe than the reference does.
- BEZ_ZMIANY_STATUSU: the window never changes an order's status and never clicks a button outside its list.
- ZMIANA_ZE_SLADEM: every order that changed in efenix has the action that changed it in its trace in the result or the
  Zatrzymanie (and a ``begun`` entry in the dziennik), a Komunikat that says nothing changed is true, the Znaczniki
  efenix are exactly the gotowe orders, and a gotowe order has the file's quantities, the AU amount and the date.
  What a killed tool leaves has a „zaczynam” entry in the dziennik for each order changed in efenix, no Znaczniki
  efenix, and the file's pricing in efenix for each order the dziennik ended gotowe.
- WZNOWIENIE: the promises of ``verify-wznowienie-wyceny-efenix`` and the Wycena w efenix of ``GLOSSARY.md`` (ADR
  0026): a second run never loads Emmett into an order with a quantity (NieCzysciWycenyTaty), never lowers or clears a
  quantity in efenix (NieObnizaIlosci), completes every order to the file only upwards, so an order Dad changed ends as
  ``completed`` says (ZmianaTatyZostaje), and ends every order Dad did not change like one run
  (BladTylkoPoZmianieTaty).
- BEZ_DANYCH: the Logi (orders, Zatrzymanie, Komunikaty) and the dziennik have no order number, efenix identifier or
  address.
- BEZ_WYJATKU: a run ends with a result or a Zatrzymanie of the window, never with an unexpected error, and a second run
  ends with a result.

Run ``--doctor`` first. ``--variant`` picks fault axes, ``--rola`` request roles; CI splits the cases into parts with
``MUTACJE_CZESC=k/n`` (``part``). The last line is the verdict.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
import queue
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import enum
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from openpyxl.styles import PatternFill
from playwright.sync_api import Browser, Page, Request, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from awarie_efenix import DAD, DAD_LOGINS, FORBIDDEN_CLICK, LOGOUTS, OUTAGES, Call, Counter, Fault, Plan, Proxy, call_kind
from rozliczenia import efenix_browser, efenix_process
from rozliczenia.centrum.run_logs import LoggedMessage, LoggedOrder, LoggedWindowStop
from rozliczenia.efenix_mark import MARK_RGB
from rozliczenia.efenix_pricing import (
    BrowserFailure,
    Closed,
    Efenix,
    ElementCount,
    EmmettWarning,
    HttpStatus,
    Login,
    LoginSign,
    OrderError,
    OrderResult,
    OtherShape,
    PagePart,
    PricingStopped,
    PricingSummary,
    Ready,
    Settled,
    Shape,
)
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.message import Message
from rozliczenia.process_run import Outcome, Stop, run_process
from rozliczenia.workbook_files import read_data_rows
from skrypt_skilla import Parser, create_run_root, new_run, part, remove_run_root
from tests.fixtures.atrapa_efenix import EFENIX_EMMETT_RELOAD_MS, AtrapaOrder, amount_of, atrapa_efenix
from tests.fixtures.efenix import Order, write_collective_file
from tests.fixtures.interlocutor import Tata
from tests.fixtures.settlement import PERIOD

VERDICT: Final = "WYCENA EFENIX"
LIMIT_MS: Final = 3_000 + EFENIX_EMMETT_RELOAD_MS
"""The window's time limit in the checker: the 3 s of the sweep of ``tests/test_wycena_efenix.py`` and the reload the
efenix script makes after „Załaduj do zlecenia”, which the window waits for in the same time limit as its answer, so an
answer to it just before the limit (``early_s``) comes as late as one to any other request."""
EARLY_S: Final = 0.6
"""How long before the end of the window's wait an answer ``Fault.LATE_BEFORE`` comes (``Plan.early_s``)."""
RETRIES: Final = 3
"""Runs again a case whose fault the browser side did not inject (``Run.injected``) at most this many times."""
CLOSE_WAIT_MS: Final = 5_000
"""How long the checker waits after a run for the tab Dad closed to be closed."""
LOGIN_LIMIT_MS: Final = 4_000
"""How long the window waits for Dad's login in the checker (``efenix_browser.LOGIN_TIMEOUT_MS`` at Dad's)."""
CASE_LIMIT_S: Final = 45.0
"""A run that takes longer hangs: the checker ends with a violation."""
FIRST_ROW: Final = 18

# --- The scenario: two orders of the Plik zbiorczy and the same orders in the Atrapa efenix -------------------------

NUMBERS: Final = ("5287401", "5287402")
IDENTIFIERS: Final = ("a5kx1", "a5kx2")
FILE: Final[tuple[Mapping[str, int], ...]] = ({"012": 1, "019": 2, "015": 1}, {"012": 1, "019": 2})
"""Quantities of the Plik zbiorczy by position: O→012, T→019, AG→015 (spec #741)."""
CELLS: Final[tuple[Mapping[str, int], ...]] = ({"O": 1, "T": 2, "AG": 1}, {"O": 1, "T": 2})
EMMETT: Final[tuple[Mapping[str, int], ...]] = ({"012": 1, "019": 1}, {"012": 1, "019": 5})
"""Emmett of order 1 gives 1 in T, the file has 2: the process enters 2 over it (#960). Emmett of order 2 gives 5 in T, the
file has 2: the process leaves it and gives an Ostrzeżenie Emmetta."""
DAYS: Final = (date(2026, 9, 1), date(2026, 9, 2))
ADDRESSES: Final = ("UL. KASZTANOWA 7/1", "UL. LIPOWA 3/9")
EFENIX_ADDRESSES: Final = ("Sopot-Centrum ul.Kasztanowa 7 Lokal 1", "Sopot-Centrum ul.Lipowa 3 Lokal 9")
FORBIDDEN_TEXT: Final = (*NUMBERS, *IDENTIFIERS, "kasztanow", "lipow", "sopot")
"""Text of the orders that no Logi or dziennik may hold (compared without letter case)."""


def file_orders() -> list[Order]:
    return [
        Order(
            f"#{NUMBERS[index]}",
            address=ADDRESSES[index],
            day=DAYS[index],
            cells=dict(CELLS[index]),
            amount=float(amount_of(FILE[index])),
            efenix_address=EFENIX_ADDRESSES[index],
            emmett=dict(EMMETT[index]),
        )
        for index in range(2)
    ]


def efenix_orders() -> list[AtrapaOrder]:
    return [order.in_efenix(IDENTIFIERS[index]) for index, order in enumerate(file_orders())]


@dataclass(frozen=True)
class Priced:
    """State of one order in the Atrapa: quantities (code → quantity other than 0), date, Emmett loads, status."""

    quantities: tuple[tuple[str, int], ...]
    day: date | None
    emmett_loads: int
    status: str

    @property
    def amount(self) -> Decimal:
        return amount_of(dict(self.quantities))

    def __str__(self) -> str:
        quantities = ", ".join(f"{code}={quantity}" for code, quantity in self.quantities) or "pusta"
        return f"wycena [{quantities}], data {self.day or 'pusta'}, Emmett {self.emmett_loads}x, {self.status}"


def priced(order: AtrapaOrder) -> Priced:
    return Priced(tuple(sorted(order.quantities.items())), order.execution_date, order.emmett_loads, order.status)


INITIAL: Final = tuple(priced(order) for order in efenix_orders())
"""Domain expectation of one run without a fault (``GLOSSARY.md``, Wycena w efenix, ADR 0026): order 1 gets the date,
Emmett and the file's quantity in each position where Emmett has less; order 2 gets the date and Emmett, whose T stays
above the file, and nothing more, because its other position equals the file."""
REFERENCE_FINAL: Final = (
    Priced(tuple(sorted(FILE[0].items())), DAYS[0], 1, "Do wyceny"),
    Priced(tuple(sorted(EMMETT[1].items())), DAYS[1], 1, "Do wyceny"),
)
REFERENCE_OUTCOMES: Final = ("gotowe", "ostrzeżenie Emmetta")
REFERENCE_MARKED: Final = (FIRST_ROW,)

# --- The window's requests in one run without a fault -----------------------------------------------------------


class Role(enum.Enum):
    """What a request is for the window; the value is its ``--rola`` name."""

    LIST_START = "lista-na-starcie"
    LIST_FILE_START = "plik-listy-na-starcie"
    SEARCH = "szukanie"
    LIST_AGAIN = "lista-ponownie"
    LIST_FILE_AGAIN = "plik-listy-ponownie"
    BY_LIST = "szukanie-listy"
    ORDER_OPEN = "strona-zlecenia"
    ORDER_FILE = "plik-strony-zlecenia"
    DATE = "data-wykonania"
    ORDER_DATED = "strona-po-dacie"
    DATED_FILE = "plik-strony-po-dacie"
    PROPOSAL = "propozycja-emmetta"
    LOAD = "zaladuj-do-zlecenia"
    RELOADED = "strona-po-emmetcie"
    RELOADED_FILE = "plik-strony-po-emmetcie"
    QUANTITY = "ilosc"


PAGE_OF: Final = {
    Role.LIST_FILE_START: Role.LIST_START,
    Role.LIST_FILE_AGAIN: Role.LIST_AGAIN,
    Role.ORDER_FILE: Role.ORDER_OPEN,
    Role.DATED_FILE: Role.ORDER_DATED,
    Role.RELOADED_FILE: Role.RELOADED,
}
"""The page of each role of a page's file: the window's step that loads them (``step``)."""


def step(role: Role) -> Role:
    """The window's step a request of ``role`` belongs to: its action, or the page, with that page's files."""

    return PAGE_OF.get(role, role)


_LIST = "index.php"
_ORDER = "page_order_edit.php"
_CSS = "css/efenix.css"


def _page(path: str, script: str, role: Role, file_role: Role) -> list[tuple[str, str, str, Role]]:
    return [("GET", path, "", role), ("GET", _CSS, "", file_role), ("GET", script, "", file_role)]


def _order_calls(quantities: int) -> list[tuple[str, str, str, Role]]:
    script = "js/page_order_edit.js"
    return [
        *_page(_ORDER, script, Role.ORDER_OPEN, Role.ORDER_FILE),
        ("POST", "action_set_date_of_instalation.php", "", Role.DATE),
        *_page(_ORDER, script, Role.ORDER_DATED, Role.DATED_FILE),
        ("POST", "action_fill_emmett.php", "", Role.PROPOSAL),
        ("POST", "action_load_emmett.php", "", Role.LOAD),
        *_page(_ORDER, script, Role.RELOADED, Role.RELOADED_FILE),
        *[("POST", "action_save_index.php", "", Role.QUANTITY)] * quantities,
    ]


def _expected_calls() -> tuple[tuple[Call, Role, int], ...]:
    """Each request of the reference run with its role and its order (0 or 1), from the window's docstring: the list
    with its files, the search, then per order the order page, the date and the page again, Emmett's proposal and „Załaduj
    do zlecenia” with the page reloaded by the efenix script, and one quantity per position empty at Emmett; the second
    order opens the list again, which searches the previous number by itself."""

    script = "js/index.js"
    plan = [
        [*_page(_LIST, script, Role.LIST_START, Role.LIST_FILE_START), ("POST", "action_fill_orders.php", "okno", Role.SEARCH), *_order_calls(2)],
        [
            *_page(_LIST, script, Role.LIST_AGAIN, Role.LIST_FILE_AGAIN),
            ("POST", "action_fill_orders.php", "lista", Role.BY_LIST),
            ("POST", "action_fill_orders.php", "okno", Role.SEARCH),
            *_order_calls(0),
        ],
    ]
    counter = Counter()
    return tuple((counter.next((method, path, search)), role, index) for index, calls in enumerate(plan) for method, path, search, role in calls)


EXPECTED_CALLS: Final = _expected_calls()
ROLE_OF: Final = {call: (role, order) for call, role, order in EXPECTED_CALLS}
LOGIN_PAGE: Final = "page_login.php"
ALLOWED_PATHS: Final = frozenset(call.path for call, _role, _order in EXPECTED_CALLS) | {LOGIN_PAGE}
"""Paths the window may reach: the reference requests and the login page an expired session redirects to."""

# --- Expected outcome of each fault: the domain table ---------------------------------------------------------------


class Cause(enum.Enum):
    """Domain category of a Zatrzymanie, from the docstrings of ``efenix_browser`` and ``WindowCause``."""

    NETWORK = "błąd przeglądarki z nazwanym działaniem (sieć albo czas okna)"
    TIMEOUT = "czas okna minął (TimeoutError z nazwanym działaniem)"
    UNREACHABLE = "efenix nie otworzył się przy starcie (EfenixUnreachable)"
    HTTP = "strona błędu HTTP (HttpStatus ze statusem awarii)"
    LOGIN = "wylogowanie (LoggedOut albo formularz logowania)"
    CLOSED = "zamknięte okno (WindowClosed)"
    SHAPE = "strona w innej budowie (ElementCount, OtherShape)"
    NOT_LOADED = "efenix nie załadował Wyceny Emmetta po odpowiedzi 2xx (OtherShape EMMETT_NOT_LOADED)"
    UNNAMED = "błąd przeglądarki bez nazwanego działania"


@dataclass(frozen=True)
class Expect:
    """Allowed outcomes of one fault at one request: a Zatrzymanie of one of ``stops``, a run that ends like the
    reference (``same``) or one that leaves the faulted order to Dad and ends the rest like the reference (``left``)."""

    stops: frozenset[Cause] = frozenset()
    same: bool = False
    left: bool = False


_START = {Role.LIST_START, Role.LIST_FILE_START}
_ORDER_PAGES = {Role.ORDER_OPEN, Role.ORDER_DATED, Role.RELOADED}
_LISTS = {Role.LIST_START, Role.LIST_AGAIN}
_FILES = {Role.LIST_FILE_START, Role.LIST_FILE_AGAIN, Role.ORDER_FILE, Role.DATED_FILE, Role.RELOADED_FILE}


def _tail() -> frozenset[Call]:
    """Requests after the last action of the run: the files of the last page, which nothing reads afterwards."""

    actions = [index for index, (_call, role, _order) in enumerate(EXPECTED_CALLS) if role not in _FILES]
    return frozenset(call for call, _role, _order in EXPECTED_CALLS[actions[-1] + 1 :])


def expected(fault: Fault, call: Call, role: Role) -> Expect:
    """The domain table; see ``_expected``. A fault at a file of the last page, after which the window needs nothing of
    efenix, may also end like the reference."""

    expect = _expected(fault, call, role)
    return replace(expect, same=True) if call in TAIL and fault is not Fault.TAB_CLOSED and expect.stops else expect


def _expected(fault: Fault, call: Call, role: Role) -> Expect:
    """The domain table. Network faults and late answers name the network or the time limit, never a page shape, and
    before the list opened may be ``EfenixUnreachable`` (``efenix_browser``: „Lista zleceń, której okno nie otworzyło
    przy starcie … to EfenixUnreachable”; „Czy to zerwane połączenie, wolny czy zmieniony efenix, okno nie zgaduje”).
    An HTTP error page names its status (``HttpStatus``) and never a shape, because efenix did not change. A redirect
    elsewhere is a page efenix sent instead, which the docstring lets the window call a page in another shape. The
    search the list sends by itself is not the window's, and a stylesheet does not carry the page, so one broken answer
    to them ends like the reference. A date that efenix did not save is an order error (``DateRefused.NOT_SAVED``).
    A login form under the address of the order page is a logout (``Shape.LOGIN_FORM``), and so is a login that never
    comes; a tab closed while the window waits for Dad's login is a closed window at once (``Closed.DURING_LOGIN``,
    #758), and a login in that time lets the run go on. The answer to the list's own search goes into the page
    (``efenix_browser``: „jej odpowiedź trafia do #wyniki w dowolnej chwili”), so a redirect that puts the list page
    there may give the list another shape. A „Załaduj do zlecenia” efenix answers with 200 and ``result: nok`` in a
    valid session leaves the order without Wycena Emmetta, and the window tells it from the reloaded page, not from the
    answer it never reads: amount 0 is ``Shape.EMMETT_NOT_LOADED``, a Zatrzymanie of the window, not a logout, unless
    Emmett proposed nothing, which the window knows only from an empty Emmett dialog after a proposal that came whole
    with 2xx; an empty dialog after a failed proposal (``REFUSED_NO_PROPOSAL``: its proposal is HTTP 500) is not that
    (``efenix_browser``: „Strona z kwotą 0 po każdej innej propozycji, także po pustym oknie Emmetta po padniętej
    propozycji, to UnexpectedPage z Shape.EMMETT_NOT_LOADED”, #908); an expired session stays a logout. An answer to „Załaduj
    do zlecenia” just before the end of the window's wait, which includes the reload the efenix script makes after it
    (``early_s``), ends like the reference: the window waits for the answer and the reload within its time limit."""

    start = {Cause.UNREACHABLE} if role in _START else set()
    style = call.path.endswith(".css")
    match fault:
        case Fault.CUT | Fault.TORN:
            return Expect(frozenset({Cause.NETWORK, *start}))
        case Fault.STALLED | Fault.SLOW:
            return Expect(frozenset({Cause.TIMEOUT, *start}))
        case Fault.HUNG | Fault.LATE_AFTER:
            return Expect(frozenset({Cause.TIMEOUT, *start}), same=role is Role.BY_LIST)
        case Fault.LATE_BEFORE if role is Role.LOAD:
            return Expect(same=True)
        case Fault.LATE_BEFORE:
            return Expect(frozenset({Cause.TIMEOUT, *start}), same=True)
        case Fault.HTTP_4XX | Fault.HTTP_5XX:
            executed = fault is Fault.HTTP_5XX
            if role in _ORDER_PAGES:
                return Expect(frozenset({Cause.HTTP}))
            if role in _LISTS:
                return Expect(frozenset({Cause.HTTP, *start}))
            if role is Role.BY_LIST or (role in _FILES and style):
                return Expect(same=True)
            if role in _FILES:
                return Expect(frozenset({Cause.TIMEOUT}), same=role is Role.RELOADED_FILE)
            if role is Role.DATE:
                return Expect(frozenset({Cause.HTTP, Cause.NETWORK}), same=executed, left=True)
            if role in (Role.PROPOSAL, Role.LOAD):
                return Expect(frozenset({Cause.HTTP, Cause.NETWORK}), same=executed or role is Role.PROPOSAL, left=True)
            return Expect(frozenset({Cause.HTTP, Cause.NETWORK}), left=role is Role.QUANTITY)
        case Fault.LOGGED_OUT:
            return Expect(frozenset({Cause.LOGIN}), same=role in _FILES)
        case Fault.REDIRECT:
            if role is Role.BY_LIST:
                return Expect(frozenset({Cause.SHAPE}), same=True)
            if role in _LISTS or (role in _FILES and style):
                return Expect(same=True)
            if role in _FILES:
                return Expect(frozenset({Cause.TIMEOUT}), same=role is Role.RELOADED_FILE)
            other = frozenset({Cause.SHAPE, Cause.NETWORK})
            if role in (Role.DATE, Role.LOAD, Role.QUANTITY, Role.PROPOSAL):
                return Expect(other, same=role is Role.PROPOSAL, left=True)
            return Expect(other)
        case Fault.LOGIN_PAGE:
            return Expect(frozenset({Cause.LOGIN}))
        case Fault.REFUSED | Fault.REFUSED_NO_PROPOSAL:
            return Expect(frozenset({Cause.NOT_LOADED}))
        case Fault.TAB_CLOSED | Fault.LOGIN_CLOSED:
            return Expect(frozenset({Cause.CLOSED}))
        case Fault.LOGIN_LATER:
            return Expect(same=True)
        case Fault.LOGIN_ERROR:
            return Expect(frozenset({Cause.HTTP}))
        case Fault.KILLED:
            return Expect()


TAIL: Final = _tail()
PARTS: Final[Mapping[Role, frozenset[PagePart]]] = {
    Role.LIST_START: frozenset({PagePart.LIST}),
    Role.LIST_FILE_START: frozenset({PagePart.LIST, PagePart.RESULTS}),
    Role.SEARCH: frozenset({PagePart.RESULTS}),
    Role.LIST_AGAIN: frozenset({PagePart.LIST}),
    Role.LIST_FILE_AGAIN: frozenset({PagePart.LIST, PagePart.RESULTS}),
    Role.BY_LIST: frozenset({PagePart.LIST, PagePart.RESULTS}),
    Role.ORDER_OPEN: frozenset({PagePart.ORDER}),
    Role.ORDER_FILE: frozenset({PagePart.ORDER, PagePart.DATE}),
    Role.DATE: frozenset({PagePart.DATE}),
    Role.ORDER_DATED: frozenset({PagePart.ORDER}),
    Role.DATED_FILE: frozenset({PagePart.ORDER, PagePart.EMMETT}),
    Role.PROPOSAL: frozenset({PagePart.EMMETT}),
    Role.LOAD: frozenset({PagePart.EMMETT, PagePart.ORDER}),
    Role.RELOADED: frozenset({PagePart.EMMETT, PagePart.ORDER}),
    Role.RELOADED_FILE: frozenset({PagePart.EMMETT, PagePart.ORDER, PagePart.QUANTITY}),
    Role.QUANTITY: frozenset({PagePart.QUANTITY}),
}
"""Part of the page whose action a fault of a single answer stops (a network fault may stop a later action)."""


def applies(fault: Fault, role: Role) -> bool:
    """A login page without a redirect comes only instead of an order page (#808: efenix shows its login form there),
    Dad meets the login only when the window opens the list, and efenix refuses with 200 ``result: nok`` the „Załaduj do
    zlecenia” (#889, ``EmmettRefusal.NOK`` of the Atrapa), also after the proposal of the same order failed (#908,
    ``REFUSED_NO_PROPOSAL``); a ``result: nok`` of the quantity save is the expired session, which ``LOGGED_OUT`` gives
    there."""

    match fault:
        case Fault.LOGIN_PAGE:
            return role in _ORDER_PAGES
        case Fault.REFUSED | Fault.REFUSED_NO_PROPOSAL:
            return role is Role.LOAD
        case Fault.LOGIN_LATER | Fault.LOGIN_CLOSED | Fault.LOGIN_ERROR:
            return role is Role.LIST_START
        case _:
            return True


_RELOAD_WAIT = {Role.LOAD, Role.RELOADED, Role.RELOADED_FILE}
"""Requests the window waits for in the time limit of „Załaduj do zlecenia”, which runs from its click to the end of the
reload (``efenix_browser.load_emmett``: ``expect_navigation`` around the answer)."""


def early_s(role: Role) -> float:
    """How long before the window's time limit an answer ``LATE_BEFORE`` to a request of ``role`` comes: the answer to
    „Załaduj do zlecenia”, the reloaded page and its files share one time limit with the reload the efenix script starts
    1 s after that answer (``EFENIX_EMMETT_RELOAD_MS``), so their answer comes earlier by the reload."""

    return EARLY_S + (EFENIX_EMMETT_RELOAD_MS / 1000 if role in _RELOAD_WAIT else 0)


def plan_of(case: Case | None) -> Plan:
    if case is None:
        return Plan(limit_s=LIMIT_MS / 1000, early_s=EARLY_S)
    return Plan(case.fault, case.call, LIMIT_MS / 1000, early_s=early_s(case.role))


def classify(facts: PricingStopped, code: str) -> Cause:
    """Category of a Zatrzymanie from its facts; ``EfenixUnreachable`` carries a browser failure at the list like
    ``UnexpectedPage`` does, so its Komunikat tells them apart."""

    match facts.cause:
        case LoginSign():
            return Cause.LOGIN
        case Closed():
            return Cause.CLOSED
        case HttpStatus():
            return Cause.HTTP
        case OtherShape(shape=Shape.LOGIN_FORM):
            return Cause.LOGIN
        case OtherShape(shape=Shape.EMMETT_NOT_LOADED):
            return Cause.NOT_LOADED
        case BrowserFailure(operation=None):
            return Cause.UNNAMED
        case BrowserFailure() if code == "EFENIX_NIEDOSTEPNY":
            return Cause.UNREACHABLE
        case BrowserFailure(error_type=error_type) if error_type.rpartition(".")[2] == "TimeoutError":
            return Cause.TIMEOUT
        case BrowserFailure():
            return Cause.NETWORK
        case _:
            return Cause.SHAPE


def allows(expect: Expect, cause: Cause) -> bool:
    return cause in expect.stops or (cause is Cause.TIMEOUT and Cause.NETWORK in expect.stops)


def describe(facts: PricingStopped) -> str:
    part = "poza stroną" if facts.part is None else facts.part.name
    match facts.cause:
        case BrowserFailure(error_type, operation):
            cause = f"BrowserFailure({error_type.rpartition('.')[2]}, {None if operation is None else operation.name})"
        case ElementCount(selector, count):
            cause = f"ElementCount({selector}, {count})"
        case OtherShape(shape, _position):
            cause = f"OtherShape({shape.name})"
        case HttpStatus(status):
            cause = f"HttpStatus({status})"
        case LoginSign() | Closed():
            cause = f"{type(facts.cause).__name__}.{facts.cause.name}"
    return f"{part}, {cause}"


def code_of(facts: PricingStopped) -> str:
    """Komunikat of a Zatrzymanie (``efenix_pricing._efenix_stops``): a sign of logout „wylogowany”, a closed window
    „okno zamknięte”, a browser failure at the list before it opened „niedostępny”, the rest „okno zatrzymane”."""

    match facts.cause:
        case LoginSign():
            return "EFENIX_WYLOGOWANY"
        case Closed():
            return "EFENIX_OKNO_ZAMKNIETE"
        case _:
            return "EFENIX_OKNO_ZATRZYMANE"


# --- Dad's changes between the two runs ---------------------------------------------------------------------------


class Edit(enum.Enum):
    NONE = "bez zmian taty"
    FINISHED = "tata dokończył wycenę sam"
    REMOVED_EMMETT = "tata usunął ilość Emmetta"
    REMOVED_ADDED = "tata usunął ilość dopisaną przez proces"
    OWN = "tata zaczął sam wyceniać puste zlecenie, bez Emmetta"


def edited(state: Priced, index: int, edit: Edit) -> Priced | None:
    """``state`` of order ``index`` after Dad's ``edit``; ``None`` when the edit does not apply to it."""

    quantities = dict(state.quantities)
    emmett_positions = sorted(code for code in quantities if EMMETT[index].get(code))
    added_positions = sorted(code for code in quantities if not EMMETT[index].get(code))
    match edit:
        case Edit.NONE:
            return state
        case Edit.FINISHED:
            return replace(state, quantities=tuple(sorted(FILE[index].items())), day=DAYS[index])
        case Edit.REMOVED_EMMETT if emmett_positions:
            quantities.pop(emmett_positions[0])
            return replace(state, quantities=tuple(sorted(quantities.items())))
        case Edit.REMOVED_ADDED if added_positions:
            quantities.pop(added_positions[0])
            return replace(state, quantities=tuple(sorted(quantities.items())))
        case Edit.OWN if state.amount == 0:
            # A position Emmett leaves empty, or else the file's last one: Dad types the file's quantity, not Emmett's.
            own = next((code for code in sorted(FILE[index]) if not EMMETT[index].get(code)), sorted(FILE[index])[-1])
            return replace(state, quantities=((own, FILE[index][own]),), day=DAYS[index])
        case _:
            return None


class Interruption(enum.Enum):
    """What ended run 1: a Zatrzymanie of a logout (``LoggedOut``, ``LoginSign``), or any other Zatrzymanie or a killed
    tool (``Zatrzymanie``, ``Zgasniecie`` of ``verify-wznowienie-wyceny-efenix``), the way an accepted risk names it."""

    LOGOUT = "wylogowanie"
    OTHER = "inne Zatrzymanie albo zabicie"


def interruption(ending: Stop) -> Interruption:
    facts = ending.facts
    return Interruption.LOGOUT if isinstance(facts, PricingStopped) and isinstance(facts.cause, LoginSign) else Interruption.OTHER


# --- Known findings and accepted risks -------------------------------------------------------------------------


@dataclass(frozen=True)
class Resumed:
    """What a second run that did not end order ``index`` like one run, although Dad did not change it
    (BladTylkoPoZmianieTaty), resumed and did, each part of an accepted risk's shape (``RiskShape``): where run 1 broke
    (``at``, ``None`` when the proxy cannot tell), how (``interruption``), what it left of the order in efenix
    (``page``), and the order after the second run (``now``) with the fault of its error (``problem``, ``None`` without
    one)."""

    at: Role | None
    interruption: Interruption
    index: int
    page: Priced
    now: Priced
    problem: object


@dataclass(frozen=True)
class Violation:
    """A broken invariant ``rule`` in ``case``; ``tag`` names the kind of break. Only a violation of
    BladTylkoPoZmianieTaty has ``resumed``, and only it can be an accepted risk or a known finding."""

    rule: str
    tag: str
    case: str
    detail: str
    fault: Fault | None = None
    role: Role | None = None
    edit: Edit | None = None
    resumed: Resumed | None = None


@dataclass(frozen=True)
class RiskShape:
    """The exact shape of an accepted risk or a known finding, each part taken from its story and each required, so an
    entry cannot match on fewer of them (#920):

    - ``at``: the window's steps at which run 1 broke (``interrupted_at``), the place of the story;
    - ``interruptions``: how it broke (``Interruption``);
    - ``left``: what run 1 left of the order, its page in efenix, and its index;
    - ``second``: how the second run ended the order: its page before and after, and the fault of its error.

    Each part has in ``check_wycena_efenix_mutations.BOUNDARIES`` a broken variant just outside it, which must give a
    new violation (``tests/test_mutacje_skilli.py``). A part that admits every member of its enum restricts nothing and
    has none. ``ROLE_OF`` tells a request by its occurrence (``Counter``), so ``interrupted_at`` gives ``None`` for a
    request of an earlier step sent again later, which stays outside every step, as does a step the proxy cannot tell."""

    at: frozenset[Role]
    interruptions: frozenset[Interruption]
    left: Callable[[Priced, int], bool]
    second: Callable[[Priced, Priced, object], bool]

    def __post_init__(self) -> None:
        if not self.at or not self.interruptions:
            raise ValueError("kształt bez miejsca albo rodzaju przerwania")

    def window(self, at: Role | None, interruption: Interruption) -> bool:
        """Whether run 1 broke in this shape's place and way: what second runs may share (``_resumes``)."""

        return at in self.at and interruption in self.interruptions

    def holds(self, resumed: Resumed) -> bool:
        return (
            self.window(resumed.at, resumed.interruption)
            and self.left(resumed.page, resumed.index)
            and self.second(resumed.page, resumed.now, resumed.problem)
        )


@dataclass(frozen=True)
class Risk:
    """A violation the report lists apart from new ones: a second run that broke BladTylkoPoZmianieTaty in ``shape``."""

    name: str
    story: str
    shape: RiskShape

    def matches(self, violation: Violation) -> bool:
        return violation.resumed is not None and self.shape.holds(violation.resumed)


@dataclass(frozen=True)
class Known(Risk):
    """A violation the code has today. ``after``: the first runs (``Case.name``) after which it always shows, so a
    run, or a part of one, that ran one of them without it reports it gone; ``flaky``: a race that names none, because
    no run is sure to show it, so its absence is no sign it is gone."""

    after: tuple[str, ...]
    flaky: bool = False

    def __post_init__(self) -> None:
        if self.flaky == bool(self.after):
            raise ValueError(f"znane ustalenie {self.name} nazywa przypadki, po których występuje, albo jest flaky")


KNOWN_FINDINGS: Final[tuple[Known, ...]] = ()
ACCEPTED_RISKS: Final[tuple[Risk, ...]] = ()
"""None since #960: the second run completes every order to the file (ADR 0026), so the model's accepted findings
``przerwanie-po-zaladuj`` (#774) and ``przerwanie-przed-zapisem-ilosci`` (#864), which came from the Ślad Wyceny Emmetta,
are gone."""
# --- Observing a run -------------------------------------------------------------------------------------------


def marked(source: Path) -> tuple[int, ...]:
    """Rows of the Plik zbiorczy whose ``ADRES`` has the Znacznik efenix, read the way Przebieg rozliczeń reads them."""

    rows = []
    for row in read_data_rows(source, despite_excel_lock=True).rows:
        fill = row.cells[1].highlights.fill
        if isinstance(fill, PatternFill) and fill.patternType == "solid" and str(fill.fgColor.rgb)[-6:].upper() == MARK_RGB:
            rows.append(row.number)
    return tuple(rows)


class Journal:
    """Dziennik Wyceny w efenix of a run, as Centrum writes it (``efenix_pricing.OrderJournal``): one line per entry."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def begun(self, row: int, place: int, total: int) -> None:
        self._write({"begun": row, "place": place, "total": total})

    def ended(self, result: OrderResult, message: Message | None) -> None:
        self._write({"ended": json.loads(LoggedOrder.of(result, None if message is None else message.code).model_dump_json())})

    def _write(self, entry: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            file.flush()

    @staticmethod
    def begun_rows(text: str) -> set[int]:
        rows = set()
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("begun"), int):
                rows.add(entry["begun"])
        return rows

    @staticmethod
    def ended_outcomes(text: str) -> dict[int, str]:
        """Outcome of each order the dziennik has ended („zlecenie skończone”), by its row."""

        outcomes = {}
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            ended = entry.get("ended") if isinstance(entry, dict) else None
            if isinstance(ended, dict) and isinstance(ended.get("row"), int) and isinstance(ended.get("outcome"), str):
                outcomes[ended["row"]] = ended["outcome"]
        return outcomes


@dataclass(frozen=True)
class Disk:
    """What a run leaves on disk and in efenix: Atrapa orders, the Plik zbiorczy and the dziennik."""

    orders: tuple[AtrapaOrder, ...]
    source: bytes
    journal: bytes

    @property
    def state(self) -> tuple[Priced, ...]:
        return tuple(priced(order) for order in self.orders)

    def key(self) -> str:
        """Same key, same second run: Atrapa state and Plik zbiorczy bytes. A second run starts with a new dziennik, so
        the dziennik is not part of it."""

        return json.dumps([[str(state) for state in self.state], hashlib.sha256(self.source).hexdigest()], sort_keys=True, default=str)


@dataclass
class Run:
    """One Uruchomienie on the proxy: what the checker needs after it."""

    outcome: Outcome[PricingSummary] | None
    before: tuple[Priced, ...]
    after: Disk
    calls: list[Call]
    faulted: dict[Call, str]
    """The calls the fault hit with its name: one, or each from its own on for a fault of the network (``OUTAGES``)."""
    actions: list[str]
    status_changes: int
    forbidden_clicks: int
    marked: tuple[int, ...]
    logs: str
    error: str | None = None
    snapshots: dict[str, Disk] = field(default_factory=dict)
    injected: bool = True
    """The browser side did what the fault asks before the run ended (``TAB_CLOSED``, ``LOGIN_*``); a case whose fault
    did not take effect in ``RETRIES`` more tries is ``LUKA MODELU``, never a pass."""


@dataclass(frozen=True)
class Place:
    """Files of one run: Plik zbiorczy in its Folder okresu and the dziennik."""

    root: Path

    @property
    def source(self) -> Path:
        return self.root / "plik" / PERIOD / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"

    @property
    def journal(self) -> Path:
        return self.root / "dziennik.jsonl"

    def prepare(self, disk: Disk) -> None:
        """The Plik zbiorczy ``disk`` left, with a new dziennik, as each Uruchomienie has its own."""

        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(disk.source)
        self.journal.write_bytes(b"")

    def disk(self, orders: Sequence[AtrapaOrder]) -> Disk:
        return Disk(tuple(copy.deepcopy(list(orders))), self.source.read_bytes(), _read(self.journal))


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def logs_text(outcome: Outcome[PricingSummary] | None, journal: bytes) -> str:
    """The Logi of the run as Centrum writes them for a Wycena w efenix (orders, Zatrzymanie, Komunikaty) and the
    dziennik, one text for the BEZ_DANYCH check."""

    parts: list[str] = [journal.decode("utf-8", "replace")]
    if outcome is not None:
        summary: PricingSummary | None = outcome.view
        messages: list[Message] = [] if outcome.view is None else list(outcome.view.warnings)
        if isinstance(outcome.ending, Stop):
            messages.append(outcome.ending.message)
            facts = outcome.ending.facts
            if isinstance(facts, PricingStopped):
                summary = facts.summary
                parts.append(LoggedWindowStop.of(facts).model_dump_json())
        if summary is not None:
            parts += [order.model_dump_json() for order in LoggedOrder.all_of(summary)]
        parts += [LoggedMessage.of("warning", message).model_dump_json() for message in messages]
    return "\n".join(parts)


def run_once(browser: Browser, place: Place, orders: Sequence[AtrapaOrder], plan: Plan, *, snapshots: bool = False) -> Run:
    """One Uruchomienie on a new Atrapa with ``orders`` behind the proxy with ``plan``, on the files in ``place``.

    The Atrapa reloads the page after „Załaduj do zlecenia” as late as efenix does (``EFENIX_EMMETT_RELOAD_MS``), not
    as early as its tests do, so the window meets that reload when it would at Dad's."""

    taken: dict[str, Disk] = {}
    with atrapa_efenix(orders, emmett_reload_ms=EFENIX_EMMETT_RELOAD_MS) as atrapa:

        def snapshot(moment: str) -> Callable[[Call], None]:
            def take(call: Call) -> None:
                if snapshots:
                    taken[f"{moment} {call}"] = place.disk(atrapa.state()[0])

            return take

        proxy = Proxy(atrapa.url, plan, atrapa.expire_session, after_executed=snapshot("po"), before_executed=snapshot("przed"))
        with proxy:
            before = tuple(priced(order) for order in atrapa.state()[0])
            context = browser.new_context()
            page = context.new_page()
            acted = _dad(page, plan, atrapa.log_in)
            outcome, error = None, None
            try:
                outcome = _price(place, page, proxy.url)
            except Exception as failure:  # noqa: BLE001 - BEZ_WYJATKU names any error that escapes run_process
                error = "".join(traceback.format_exception_only(failure)).strip()
            finally:
                closing = plan.fault in (Fault.TAB_CLOSED, Fault.LOGIN_CLOSED)
                if closing and acted.is_set() and not page.is_closed():
                    # The window may stop on the navigation error before Playwright reports the tab closed.
                    with suppress(PlaywrightError):
                        page.wait_for_event("close", timeout=CLOSE_WAIT_MS)
                injected = (plan.fault is not Fault.TAB_CLOSED and plan.fault not in DAD_LOGINS) or (
                    acted.is_set() and (page.is_closed() or not closing)
                )
                # The tab goes first: a held answer closed under an open tab makes Chromium send the request again.
                context.close()
                proxy.release()
            orders_after = atrapa.state()[0]
            seen = list(proxy.seen)
            status_changes, clicks = atrapa.status_changes(), proxy.forbidden_clicks
    after = place.disk(orders_after)
    return Run(
        outcome=outcome,
        before=before,
        after=after,
        calls=[entry.call for entry in seen],
        faulted={entry.call: entry.action for entry in seen if entry.action},
        actions=[f"{entry.at:7.2f} s  {entry.call}{'  ← ' + entry.action if entry.action else ''}" for entry in seen],
        status_changes=status_changes,
        forbidden_clicks=clicks,
        marked=marked(place.source),
        logs=logs_text(outcome, after.journal),
        error=error,
        snapshots=taken,
        injected=injected,
    )


def _dad(page: Page, plan: Plan, log_in: Callable[[], None]) -> threading.Event:
    """Dad in the browser: closes the tab when it sends ``plan.target`` (``TAB_CLOSED``), and on the login page logs in
    (``LOGIN_LATER``, ``LOGIN_ERROR``) or closes the tab (``LOGIN_CLOSED``) when it sends ``DAD``. The event is set when
    he starts it.

    The tab closes in the route of ``plan.target``, which Chromium holds until its handler answers: the ``request``
    event of the reload that the efenix script starts after „Załaduj do zlecenia” sometimes reached Playwright only when
    the context closed, and a ``page.close()`` sent while that navigation went on sometimes took effect only then too
    (2026-11-05: 2 of 4 runs of ``--rola strona-po-emmetcie`` without a close, 2 of 15 with a close after
    ``route.continue_()``). So a navigation closes while held and never reaches efenix, and any other request reaches
    efenix first, as before."""

    counter = Counter()
    acted = threading.Event()

    def close() -> None:
        acted.set()
        if not page.is_closed():
            page.close()

    def on_request(request: Request) -> None:
        kind = call_kind(request.method, request.url, request.post_data or "")
        if kind[1] == FORBIDDEN_CLICK:
            return
        if kind[1] == DAD:
            if plan.fault in (Fault.LOGIN_LATER, Fault.LOGIN_ERROR):
                log_in()
                acted.set()
            elif plan.fault is Fault.LOGIN_CLOSED:
                close()
            return

    def on_route(route: Route) -> None:
        request = route.request
        kind = call_kind(request.method, request.url, request.post_data or "")
        if kind[1] in (FORBIDDEN_CLICK, DAD) or counter.next(kind) != plan.target:
            route.continue_()
        elif request.is_navigation_request():
            # A close sent while Chromium goes on with a navigation sometimes waits for the context to close; held, it
            # does not. A page's GET changes nothing in efenix, so it need not reach it.
            close()
            with suppress(PlaywrightError):
                route.abort()
        else:
            route.continue_()
            close()

    page.on("request", on_request)
    if plan.fault is Fault.TAB_CLOSED:
        page.route("**/*", on_route)
    return acted


def _price(place: Place, page: Page, url: str) -> Outcome[PricingSummary]:
    @contextmanager
    def open_efenix(login: Login) -> Iterator[Efenix]:
        with efenix_browser.window(page, url, timeout_ms=LIMIT_MS, login=login, login_timeout_ms=LOGIN_LIMIT_MS) as efenix:
            yield efenix

    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(place.source, open_efenix, pace=None, journal=Journal(place.journal)),
        Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=place.root / "metryki.jsonl",
    )


# --- The checks ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One fault at one request of the reference run."""

    fault: Fault
    call: Call
    role: Role
    order: int

    @property
    def name(self) -> str:
        return f"{self.fault.name} przy {self.call} [{self.role.value}]"


@dataclass(frozen=True)
class Resume:
    """A second run from what ``source`` left after it broke at ``at`` by its ``interruption``, after Dad's ``edit``
    of order ``order``."""

    source: str
    disk: Disk
    order: int
    edit: Edit
    case: Case
    at: Role | None
    interruption: Interruption
    shared: list[str] = field(default_factory=list)
    """The other first runs that left the same state and broke in the same risks' window, so this second run is theirs
    too (``_resumes``)."""

    @property
    def name(self) -> str:
        return f"{self.source} → ponownie, {self.edit.value} (zlecenie {self.order + 1})"


def interrupted_at(case: Case, run: Run, order: int) -> Role | None:
    """The window's step (``step``) at which run 1 that stopped at order ``order`` broke: that of its last request, as
    the proxy saw it, or of the faulted one when the browser side held it before the proxy (a tab closed at a
    navigation). The last request, not the faulted one, because the window goes on after some faults and breaks further
    on: after a network fault at a page's file or at Emmett's proposal, or after a logout at the page after Emmett,
    which it meets at its first quantity; when the page's script did not load, its save sends nothing, and the window
    breaks there with that page as its last step.

    Not the window's own: a page's files, which come in any order with a request Chromium sends again among them (so
    they count as their page), a request Chromium sends again right after its connection was cut, and what efenix sent
    the browser to (the page after a redirect, the login page and what follows it). ``None`` when the step is not one
    of the reference run at ``order``, so no accepted risk takes it."""

    redirected = next((index for index, call in enumerate(run.calls) if run.faulted.get(call) == Fault.REDIRECT.name), None)
    login = next((index for index, call in enumerate(run.calls) if call.path == LOGIN_PAGE), len(run.calls))
    calls = [call for call in run.calls[: min(login, len(run.calls) if redirected is None else redirected + 1)] if not call.is_file]
    sent = calls[:1] + [call for previous, call in itertools.pairwise(calls) if not (previous in run.faulted and previous.kind == call.kind)]
    role, at_order = ROLE_OF.get(sent[-1] if sent else case.call, (None, None))
    return step(role) if role is not None and at_order == order else None


def _problems(summary: PricingSummary | None) -> dict[int, object]:
    """The fault of each order (0, 1) the run left to Dad with an error (``OrderError.problem``)."""

    return {
        result.order.row - FIRST_ROW: result.outcome.problem
        for result in (() if summary is None else summary.results)
        if isinstance(result.outcome, OrderError)
    }


def _outcomes(summary: PricingSummary | None) -> dict[int, str]:
    """Outcome of each order (0, 1) by its row: gotowe, rozliczone, błąd or ostrzeżenie Emmetta."""

    names: dict[int, str] = {}
    for result in () if summary is None else summary.results:
        match result.outcome:
            case Ready():
                name = "gotowe"
            case Settled():
                name = "rozliczone"
            case OrderError():
                name = "błąd"
            case EmmettWarning():
                name = "ostrzeżenie Emmetta"
        names[result.order.row - FIRST_ROW] = name
    return names


def _summary(outcome: Outcome[PricingSummary] | None) -> PricingSummary | None:
    if outcome is None:
        return None
    if isinstance(outcome.ending, Stop) and isinstance(outcome.ending.facts, PricingStopped):
        return outcome.ending.facts.summary
    return outcome.view


def _steps(outcome: Outcome[PricingSummary] | None) -> dict[int, set[str]]:
    """Actions of the window at each order (0, 1): its trace in the result, and at the Zatrzymanie the order it stopped
    at with its failed action."""

    actions: dict[int, set[str]] = {}
    summary = _summary(outcome)
    for result in () if summary is None else summary.results:
        actions.setdefault(result.order.row - FIRST_ROW, set()).update(step.action for step in result.steps)
    if outcome is not None and isinstance(outcome.ending, Stop) and isinstance(outcome.ending.facts, PricingStopped):
        at = outcome.ending.facts.stopped_at
        if at is not None:
            done = actions.setdefault(at.row - FIRST_ROW, set())
            done.update(step.action for step in at.steps)
            if at.failed is not None:
                done.add(at.failed.action)
    return actions


def _changes(before: Priced, after: Priced) -> set[str]:
    """Actions of the window that explain the change of one order: the date, Emmett, or a quantity."""

    needed = set()
    if before.day != after.day:
        needed.add("data wykonania")
    if before.emmett_loads != after.emmett_loads:
        needed.add("Wycena Emmetta")
    elif before.quantities != after.quantities:
        needed.add("ilość")
    return needed


def common_checks(name: str, run: Run, before: Sequence[Priced], extra: Mapping[str, object]) -> list[Violation]:
    """BEZ_ZMIANY_STATUSU, ZMIANA_ZE_SLADEM and BEZ_DANYCH of any run, with ``before`` the state it started from."""

    found: list[Violation] = []

    def add(rule: str, tag: str, detail: str) -> None:
        found.append(Violation(rule, tag, name, detail, **extra))  # type: ignore[arg-type]

    after = run.after.state
    if run.status_changes or run.forbidden_clicks:
        add("BEZ_ZMIANY_STATUSU", "status", f"zmiany statusu {run.status_changes}, kliknięcia spoza listy {run.forbidden_clicks}")
    if outside := sorted({call.path for call in run.calls} - ALLOWED_PATHS):
        add("BEZ_ZMIANY_STATUSU", "żądanie spoza listy", f"okno wysłało żądania spoza listy dozwolonych: {', '.join(outside)}")
    if [state.status for state in after] != [state.status for state in before]:
        add("BEZ_ZMIANY_STATUSU", "status", f"status zlecenia zmienił się: {[str(state) for state in after]}")
    steps = _steps(run.outcome)
    begun = Journal.begun_rows(run.after.journal.decode("utf-8", "replace"))
    for index, (was, now) in enumerate(zip(before, after, strict=True)):
        if was == now:
            continue
        missing = _changes(was, now) - steps.get(index, set())
        if missing:
            add(
                "ZMIANA_ZE_SLADEM",
                "zmiana bez śladu",
                f"zlecenie {index + 1} zmieniło się w efenix ({was} → {now}), a wynik i Zatrzymanie nie mają działania: "
                f"{', '.join(sorted(missing))}",
            )
        if run.outcome is not None and FIRST_ROW + index not in begun:
            add("ZMIANA_ZE_SLADEM", "zmiana bez dziennika", f"zlecenie {index + 1} zmieniło się w efenix bez wpisu „zaczynam” w dzienniku")
    outcome = run.outcome
    if outcome is not None:
        if isinstance(outcome.ending, Stop) and "W efenix nic się nie zmieniło." in outcome.ending.message.what and tuple(after) != tuple(before):
            add("ZMIANA_ZE_SLADEM", "komunikat bez zmian", "Komunikat mówi, że w efenix nic się nie zmieniło, a zmieniło się")
        outcomes = _outcomes(_summary(outcome))
        ready = tuple(sorted(FIRST_ROW + index for index, name in outcomes.items() if name == "gotowe"))
        if run.marked != ready:
            add("ZMIANA_ZE_SLADEM", "znaczniki", f"Znaczniki efenix w wierszach {list(run.marked)}, a gotowe są {list(ready)}")
        for index, name in outcomes.items():
            state = after[index]
            full = state.quantities == tuple(sorted(FILE[index].items())) and state.day == DAYS[index]
            if name == "gotowe" and not (full and state.amount == amount_of(FILE[index])):
                add("ZMIANA_ZE_SLADEM", "gotowe bez wyceny pliku", f"zlecenie {index + 1} jest gotowe, a w efenix ma {state}")
    if leaked := leaks(run):
        add("BEZ_DANYCH", "dane zleceń", f"Logi albo dziennik mają: {', '.join(leaked)}")
    return found


def leaks(run: Run) -> list[str]:
    """BEZ_DANYCH: order numbers, efenix identifiers and address words in the Logi or the dziennik."""

    text = run.logs.casefold()
    return [word for word in FORBIDDEN_TEXT if word.casefold() in text]


def killed_run(snapshot: Disk, source: Path) -> Run:
    """What the tool killed at the moment of ``snapshot`` leaves, as a run without an outcome: no Logi, no Komunikat,
    only efenix, the Plik zbiorczy (written to ``source`` to read its Znaczniki) and the dziennik."""

    source.write_bytes(snapshot.source)
    return Run(
        outcome=None,
        before=INITIAL,
        after=snapshot,
        calls=[],
        faulted={},
        actions=[],
        status_changes=0,
        forbidden_clicks=0,
        marked=marked(source),
        logs=logs_text(None, snapshot.journal),
    )


def check_killed(name: str, case: Case, run: Run) -> list[Violation]:
    """ZMIANA_ZE_SLADEM, BEZ_ZMIANY_STATUSU and BEZ_DANYCH of what a tool killed at ``case`` leaves: no order changed
    its status; every order changed in efenix has its „zaczynam” entry in the dziennik (``pricing_journal``: „zaczynam
    zlecenie” … „przed pierwszym działaniem okna efenix przy zleceniu, więc przed każdym zapisem w efenix”); the Plik
    zbiorczy has no Znacznik efenix, because Zapisywanie sets them at its end (``efenix_pricing``: „na końcu Znaczniki
    efenix”); an order the dziennik ended gotowe has the file's quantities, ``Kwota`` (AU) and the date in efenix; and
    the dziennik has no order data."""

    found: list[Violation] = []

    def add(rule: str, tag: str, detail: str) -> None:
        found.append(Violation(rule, tag, name, detail, case.fault, case.role))

    after = run.after.state
    if [state.status for state in after] != [state.status for state in INITIAL]:
        add("BEZ_ZMIANY_STATUSU", "status", f"status zlecenia zmienił się: {[str(state) for state in after]}")
    journal = run.after.journal.decode("utf-8", "replace")
    begun, ended = Journal.begun_rows(journal), Journal.ended_outcomes(journal)
    for index, (was, now) in enumerate(zip(INITIAL, after, strict=True)):
        if was != now and FIRST_ROW + index not in begun:
            add("ZMIANA_ZE_SLADEM", "zmiana bez dziennika", f"zlecenie {index + 1} zmieniło się w efenix ({was} → {now}) bez wpisu „zaczynam” w dzienniku")
        full = now.quantities == tuple(sorted(FILE[index].items())) and now.day == DAYS[index] and now.amount == amount_of(FILE[index])
        if ended.get(FIRST_ROW + index) == "gotowe" and not full:
            add("ZMIANA_ZE_SLADEM", "gotowe bez wyceny pliku", f"dziennik ma zlecenie {index + 1} jako gotowe, a w efenix ma {now}")
    if run.marked:
        add("ZMIANA_ZE_SLADEM", "znaczniki", f"Znaczniki efenix w wierszach {list(run.marked)} przed końcem Zapisywania")
    if leaked := leaks(run):
        add("BEZ_DANYCH", "dane zleceń", f"dziennik ma: {', '.join(leaked)}")
    return found


def check_first(case: Case, run: Run) -> list[Violation]:
    """PRZYCZYNA, BEZ_WYJATKU and the common checks of a run with ``case``."""

    extra: dict[str, object] = {"fault": case.fault, "role": case.role}
    found = common_checks(case.name, run, INITIAL, extra)

    def add(rule: str, tag: str, detail: str) -> None:
        found.append(Violation(rule, tag, case.name, detail, case.fault, case.role))

    if run.error is not None or run.outcome is None:
        add("BEZ_WYJATKU", "wyjątek", f"Uruchomienie skończyło się wyjątkiem: {run.error}")
        return found
    expect = expected(case.fault, case.call, case.role)
    ending = run.outcome.ending
    if isinstance(ending, Stop):
        facts = ending.facts if isinstance(ending.facts, PricingStopped) else None
        code = ending.message.code
        if ending.kind != "stop" or facts is None:
            add("BEZ_WYJATKU", "nieoczekiwany błąd", f"Zatrzymanie {code} bez faktów okna efenix")
            return found
        cause = classify(facts, code)
        shown = f"Zatrzymanie {code} ({describe(facts)})"
        if not allows(expect, cause):
            allowed = [category.value for category in sorted(expect.stops, key=lambda item: item.name)]
            if expect.same:
                allowed.append("przebieg jak bez awarii")
            if expect.left:
                allowed.append("zlecenie zostawione tacie")
            add("PRZYCZYNA", f"{cause.name} zamiast {'/'.join(sorted(item.name for item in expect.stops)) or 'wyniku'}",
                f"{shown}: {cause.value}; oczekiwane: {'; '.join(allowed)}")
        unreachable = facts is not None and isinstance(facts.cause, BrowserFailure) and facts.stopped_at is None
        codes = {code_of(facts)} | ({"EFENIX_NIEDOSTEPNY"} if unreachable else set())
        if code not in codes:
            add("PRZYCZYNA", "komunikat", f"{shown}: przyczyna wymaga Komunikatu {' albo '.join(sorted(codes))}")
        rows = {FIRST_ROW + case.order} | ({None} if case.role in _START else set())
        row = None if facts.stopped_at is None else facts.stopped_at.row
        if row not in rows:
            add("PRZYCZYNA", "wiersz", f"{shown} przy wierszu {row}, a awaria dotyczy zlecenia z wiersza {FIRST_ROW + case.order}")
        one_answer = case.fault not in OUTAGES and case.fault not in LOGOUTS
        if one_answer and facts.part is not None and facts.part not in PARTS[case.role]:
            add("PRZYCZYNA", "część strony", f"{shown}: część {facts.part.name}, a {case.role.value} to {sorted(part.name for part in PARTS[case.role])}")
        return found
    outcomes = _outcomes(run.outcome.view)
    after = run.after.state
    like_reference = tuple(outcomes.get(index) for index in range(2)) == REFERENCE_OUTCOMES and after == REFERENCE_FINAL
    others = [index for index in range(2) if index != case.order]
    left = outcomes.get(case.order) in ("błąd", "ostrzeżenie Emmetta") and all(
        outcomes.get(index) == REFERENCE_OUTCOMES[index] and after[index] == REFERENCE_FINAL[index] for index in others
    )
    if not ((expect.same and like_reference) or (expect.left and left)):
        shown = "; ".join(f"zlecenie {index + 1}: {outcomes.get(index)}, {after[index]}" for index in range(2))
        allowed = [category.value for category in sorted(expect.stops, key=lambda item: item.name)]
        if expect.same:
            allowed.append("przebieg jak bez awarii")
        if expect.left:
            allowed.append("zlecenie zostawione tacie")
        tag = "gotowe inne niż bez awarii" if outcomes.get(case.order) == "gotowe" else "przebieg bez Zatrzymania"
        add("PRZYCZYNA", tag, f"przebieg bez Zatrzymania ({shown}); oczekiwane: {'; '.join(allowed) or 'Zatrzymanie'}")
    return found


@dataclass(frozen=True)
class Completed:
    """Order ``index`` after a second run that started from ``was``, as the rule of ADR 0026 gives it: a page without a
    quantity gets the date and Wycena Emmetta first; then each position where efenix has less than the file gets the
    file's quantity, and a position with more stays. ``outcome``: an Ostrzeżenie Emmetta with such a position, and
    gotowe without it (the file's quantities give ``Kwota`` (AU))."""

    state: Priced
    outcome: str


def completed(was: Priced, index: int) -> Completed:
    """``Completed`` of order ``index`` from ``was`` (``GLOSSARY.md``, Wycena w efenix and Ostrzeżenie Emmetta)."""

    priced_before = bool(was.quantities)
    base = dict(was.quantities) if priced_before else dict(EMMETT[index])
    file = FILE[index]
    quantities = {code: max(base.get(code, 0), file.get(code, 0)) for code in base.keys() | file.keys()}
    excess = any(quantity > file.get(code, 0) for code, quantity in base.items())
    state = replace(
        was,
        quantities=tuple(sorted((code, quantity) for code, quantity in quantities.items() if quantity)),
        day=was.day if priced_before or was.day is not None else DAYS[index],
        emmett_loads=was.emmett_loads + (0 if priced_before else 1),
    )
    return Completed(state, "ostrzeżenie Emmetta" if excess else "gotowe")


def check_resume(resume: Resume, run: Run) -> list[Violation]:
    """WZNOWIENIE, BEZ_WYJATKU and the common checks of a second run. Each expectation comes from a promise of the model
    ``verify-wznowienie-wyceny-efenix`` or from ``GLOSSARY.md`` (ADR 0026), never from a run:

    - NieCzysciWycenyTaty („the tool loads Wycena Emmetta only into an order with no quantity”): an order with a
      quantity gets no new „Załaduj do zlecenia”.
    - NieObnizaIlosci („the tool never lowers or clears a quantity in efenix”): no quantity of the order is lower after
      the second run than before it.
    - ZmianaTatyZostaje („an order in which Dad changed a quantity by hand ends with an Ostrzeżenie Emmetta when it
      holds more than the file, and is gotowe otherwise”): the order Dad changed ends as ``completed`` gives it.
    - BladTylkoPoZmianieTaty („an order the tool started, also one a Zatrzymanie or a switch-off cut, the next
      Uruchomienie finishes as gotowe”): every order Dad did not change ends like one run (``REFERENCE_FINAL``,
      ``REFERENCE_OUTCOMES``). Its violation carries ``Resumed``, so an entry of ``ACCEPTED_RISKS`` could take it only
      in its whole shape.
    """

    extra: dict[str, object] = {"fault": resume.case.fault, "role": resume.case.role, "edit": resume.edit}
    start = run.before
    found = common_checks(resume.name, run, start, extra)

    def add(rule: str, tag: str, detail: str, resumed: Resumed | None = None) -> None:
        found.append(Violation(rule, tag, resume.name, detail, resumed=resumed, **extra))  # type: ignore[arg-type]

    if run.error is not None or run.outcome is None:
        add("BEZ_WYJATKU", "wyjątek", f"ponowne Uruchomienie skończyło się wyjątkiem: {run.error}")
        return found
    if isinstance(run.outcome.ending, Stop):
        add("BEZ_WYJATKU", "zatrzymanie", f"ponowne Uruchomienie zatrzymało się: {run.outcome.ending.message.code}")
        return found
    outcomes, problems = _outcomes(run.outcome.view), _problems(run.outcome.view)
    final = run.after.state
    for index in range(2):
        was, now = start[index], final[index]
        if was.quantities and now.emmett_loads != was.emmett_loads:
            add("WZNOWIENIE", "Emmett do wyceny, która już jest", f"załadował Emmetta do zlecenia {index + 1} z ilościami: {was} → {now}")
        lowered = sorted(code for code, quantity in was.quantities if dict(now.quantities).get(code, 0) < quantity)
        if lowered:
            add("WZNOWIENIE", "obniżona ilość", f"obniżył albo wyczyścił w zleceniu {index + 1} pozycje {lowered}: {was} → {now}")
        if resume.edit is not Edit.NONE and index == resume.order:
            expected_now = completed(was, index)
            if (now, outcomes.get(index)) != (expected_now.state, expected_now.outcome):
                add("WZNOWIENIE", "nie dokończone do pliku po tacie",
                    f"zlecenie {index + 1} po zmianie taty ({resume.edit.value}): {was} → {now} ({outcomes.get(index)}), "
                    f"a z pliku tylko w górę: {expected_now.state} ({expected_now.outcome})")
        elif (now, outcomes.get(index)) != (REFERENCE_FINAL[index], REFERENCE_OUTCOMES[index]):
            # Where run 1 broke is a fact of the order it broke at, not of the other one.
            at_order = resume.at if index == resume.order else None
            at = "?" if at_order is None else at_order.value
            add("WZNOWIENIE", "nie jak jeden przebieg",
                f"zlecenie {index + 1} po ponownym uruchomieniu po {resume.interruption.value} przy [{at}], bez zmian taty "
                f"w nim: {now} ({outcomes.get(index)}), po jednym przebiegu: {REFERENCE_FINAL[index]}",
                Resumed(at_order, resume.interruption, index, was, now, problems.get(index)))
    return found


# --- Running the space --------------------------------------------------------------------------------------------


def cases(variants: Sequence[str], roles: Sequence[str] | None) -> list[Case]:
    axes = {axis: faults for axis, faults in AXES.items() if axis in variants}
    chosen = [fault for faults in axes.values() for fault in faults]
    return [
        Case(fault, call, role, order)
        for call, role, order in EXPECTED_CALLS
        if roles is None or role.value in roles
        for fault in chosen
        if applies(fault, role)
    ]


AXES: Final[Mapping[str, tuple[Fault, ...]]] = {
    "odciecia": (Fault.CUT, Fault.TORN, Fault.STALLED, Fault.SLOW),
    "odpowiedzi": (Fault.HTTP_4XX, Fault.HTTP_5XX, Fault.LOGGED_OUT, Fault.REDIRECT, Fault.REFUSED, Fault.REFUSED_NO_PROPOSAL, Fault.HUNG, Fault.LOGIN_PAGE),
    "granica-czasu": (Fault.LATE_BEFORE, Fault.LATE_AFTER),
    "zamkniete-okno": (Fault.TAB_CLOSED,),
    "logowanie": (Fault.LOGIN_LATER, Fault.LOGIN_CLOSED, Fault.LOGIN_ERROR),
    "zabity-proces": (Fault.KILLED,),
}
"""Fault axes, the ``--variant`` names; second runs with Dad's changes follow every axis."""


class Hang(Exception):
    """A run took longer than ``CASE_LIMIT_S``."""


def in_pool(tasks: Sequence[Callable[[Browser], object]], workers: int, label: Callable[[int], str]) -> list[object]:
    """Each task with a browser of one of ``workers`` threads, each with its own Playwright; a task that takes longer
    than ``CASE_LIMIT_S`` ends the checker with a violation (the browser of a hung run cannot be taken back)."""

    results: list[object] = [None] * len(tasks)
    work: queue.Queue[int] = queue.Queue()
    for index in range(len(tasks)):
        work.put(index)
    running: dict[int, tuple[int, float]] = {}
    lock = threading.Lock()

    def worker(number: int) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**efenix_browser.launch_options(playwright))
            try:
                while True:
                    try:
                        index = work.get_nowait()
                    except queue.Empty:
                        return
                    with lock:
                        running[number] = (index, time.monotonic())
                    try:
                        results[index] = tasks[index](browser)
                    except Exception as error:  # noqa: BLE001 - the report names a checker error per task
                        results[index] = error
                    with lock:
                        running.pop(number, None)
            finally:
                browser.close()

    threads = [threading.Thread(target=worker, args=(number,), name=f"przeglad-{number}", daemon=True) for number in range(workers)]
    for thread in threads:
        thread.start()
    while any(thread.is_alive() for thread in threads):
        for thread in threads:
            thread.join(timeout=1.0)
        with lock:
            hung = [index for index, began in running.values() if time.monotonic() - began > CASE_LIMIT_S]
        if hung:
            print(f"NOWE NARUSZENIE BEZ_WYJATKU | {label(hung[0])} | przebieg trwa dłużej niż {CASE_LIMIT_S:.0f} s", flush=True)
            print(f"{VERDICT}: NOWE NARUSZENIE (zawieszenie)", flush=True)
            os._exit(1)
    return results


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    new: list[Violation] = field(default_factory=list)
    known: dict[str, list[Violation]] = field(default_factory=dict)
    accepted: dict[str, list[Violation]] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    ran: set[str] = field(default_factory=set)
    """Names of the first runs whose fault took effect."""


def sort_violations(violations: Sequence[Violation], report: Report) -> None:
    for violation in violations:
        if risk := next((risk for risk in ACCEPTED_RISKS if risk.matches(violation)), None):
            report.accepted.setdefault(risk.name, []).append(violation)
        elif known := next((known for known in KNOWN_FINDINGS if known.matches(violation)), None):
            report.known.setdefault(known.name, []).append(violation)
        else:
            report.new.append(violation)


def known_gaps() -> list[str]:
    """Each case a known finding names in ``after`` is a case of the space, or its absence would go unseen."""

    space = {case.name for case in cases(list(AXES), None)}
    return [f"znane ustalenie {known.name} nazywa przypadek spoza przestrzeni: {name}" for known in KNOWN_FINDINGS for name in known.after if name not in space]


def explore(run_root: Path, evidence: Path, variants: Sequence[str], roles: Sequence[str] | None, workers: int) -> Report:
    report = Report(gaps=known_gaps())
    if report.gaps:
        return report
    started = time.monotonic()
    blank = Disk(tuple(efenix_orders()), write_collective_file(run_root / "wzor", file_orders()).read_bytes(), b"")
    counter = iter(range(1_000_000))

    def place(disk: Disk) -> Place:
        prepared = Place(run_root / f"run-{next(counter):05d}")
        prepared.prepare(disk)
        return prepared

    def task(case: Case | None, disk: Disk = blank, *, snapshots: bool = False) -> Callable[[Browser], object]:
        return lambda browser: run_once(browser, place(disk), disk.orders, plan_of(case), snapshots=snapshots)

    [reference] = in_pool(
        [task(None, snapshots=True)],
        1,
        lambda _index: "przebieg bez awarii",
    )
    if not isinstance(reference, Run):
        report.gaps.append(f"przebieg bez awarii nie przeszedł: {reference!r}")
        return report
    (evidence / "przebieg-bez-awarii.txt").write_text("\n".join(reference.actions) + "\n", encoding="utf-8")
    broken = reference_violations(reference) + common_checks("przebieg bez awarii", reference, INITIAL, {})
    if broken:
        _keep(evidence, "przebieg bez awarii", reference, broken)
        report.new += broken
        return report
    report.gaps += reference_gaps(reference)
    if report.gaps:
        return report
    selected = list(part(cases(variants, roles)))
    first = [case for case in selected if case.fault is not Fault.KILLED]
    runs = in_pool([task(case) for case in first], workers, lambda index: first[index].name)
    for _attempt in range(RETRIES):
        again = [index for index, run in enumerate(runs) if isinstance(run, Run) and not run.injected]
        repeated = in_pool(
            [task(first[index]) for index in again],
            workers,
            lambda number: first[again[number]].name,
        )
        for index, run in zip(again, repeated, strict=True):
            runs[index] = run
    report.gaps += [f"awaria nie zadziałała w {RETRIES + 1} próbach: {case.name}" for case, run in zip(first, runs, strict=True) if isinstance(run, Run) and not run.injected]
    resumes: dict[str, Resume] = {}
    for case, run in zip(first, runs, strict=True):
        if isinstance(run, Run) and not run.injected:
            continue
        if not isinstance(run, Run):
            report.new.append(Violation("BEZ_WYJATKU", "błąd sprawdzenia", case.name, f"sprawdzenie nie przeszło: {run!r}", case.fault, case.role))
            continue
        report.ran.add(case.name)
        violations = check_first(case, run)
        sort_violations(violations, report)
        _keep(evidence, case.name, run, violations)
        ending = None if run.outcome is None else run.outcome.ending
        if isinstance(ending, Stop) and isinstance(ending.facts, PricingStopped):
            stopped = ending.facts.stopped_at
            order = 0 if stopped is None else stopped.row - FIRST_ROW
            _resumes(resumes, case.name, run.after, order, case, interrupted_at(case, run, order), interruption(ending))
    killed = [case for case in selected if case.fault is Fault.KILLED]
    for case in killed:
        for moment in ("przed", "po"):
            name = f"{case.name}, {moment} wykonaniem"
            snapshot = reference.snapshots.get(f"{moment} {case.call}")
            if snapshot is None:
                report.gaps.append(f"brak stanu przebiegu {moment} {case.call}")
                continue
            left = killed_run(snapshot, run_root / f"zabicie-{next(counter):05d}.xlsx")
            report.ran.add(name)
            violations = check_killed(name, case, left)
            sort_violations(violations, report)
            _keep(evidence, name, left, violations)
            _resumes(resumes, name, snapshot, case.order, case, step(case.role), Interruption.OTHER)
    unique = list(resumes.values())
    second = in_pool([task(None, resume.disk) for resume in unique], workers, lambda index: unique[index].name)
    for resume, run in zip(unique, second, strict=True):
        if not isinstance(run, Run):
            report.new.append(Violation("BEZ_WYJATKU", "błąd sprawdzenia", resume.name, f"sprawdzenie nie przeszło: {run!r}"))
            continue
        violations = check_resume(resume, run)
        sort_violations(violations, report)
        _keep(evidence, resume.name, run, violations, resume.shared)
    report.lines.append(
        f"{VERDICT} | {len(first)} przebiegów z awarią, {2 * len(killed)} stanów po zabiciu, {len(unique)} ponownych "
        f"uruchomień | {time.monotonic() - started:.0f} s, {workers} przeglądarki"
    )
    return report


def _resumes(resumes: dict[str, Resume], name: str, disk: Disk, order: int, case: Case, at: Role | None, ended: Interruption) -> None:
    """A second run from ``disk`` after each ``Edit`` of order ``order`` that applies to it. First runs that left the
    same state share it only when they broke in the place and way of the same accepted risks and known findings
    (``RiskShape.window``): the same state from a break outside a risk's window is a new violation, so it never shares
    the second run, nor its risk, with a break inside it."""

    windows = [risk.name for risk in (*ACCEPTED_RISKS, *KNOWN_FINDINGS) if risk.shape.window(at, ended)]

    for edit in Edit:
        state = edited(disk.state[order], order, edit)
        if state is None:
            continue
        orders = [copy.deepcopy(item) for item in disk.orders]
        orders[order].quantities = dict(state.quantities)
        orders[order].execution_date = state.day
        changed = replace(disk, orders=tuple(orders))
        resume = resumes.setdefault(f"{changed.key()} {edit.name} {order} {windows}", Resume(name, changed, order, edit, case, at, ended))
        if resume.source != name:
            resume.shared.append(name)


def reference_violations(reference: Run) -> list[Violation]:
    """BEZ_AWARII: one run without a fault ends as ``GLOSSARY.md`` says (``REFERENCE_FINAL``, ``REFERENCE_OUTCOMES``)."""

    outcomes = _outcomes(None if reference.outcome is None else reference.outcome.view)
    shown = (
        f"{reference.error or [outcomes.get(index) for index in range(2)]}, efenix {[str(state) for state in reference.after.state]}, "
        f"Znaczniki {list(reference.marked)}"
    )
    if (
        reference.error is None
        and tuple(outcomes.get(index) for index in range(2)) == REFERENCE_OUTCOMES
        and reference.after.state == REFERENCE_FINAL
        and reference.marked == REFERENCE_MARKED
    ):
        return []
    return [Violation("BEZ_AWARII", "przebieg bez awarii", "przebieg bez awarii", f"kończy się inaczej niż w domenie: {shown}")]


def reference_gaps(reference: Run) -> list[str]:
    """The reference run must send exactly ``EXPECTED_CALLS``, or the space of requests is stale."""

    expected_calls = sorted(str(call) for call, _role, _order in EXPECTED_CALLS)
    got = sorted(str(call) for call in reference.calls)
    if got == expected_calls:
        return []
    extra = sorted(set(got) - set(expected_calls))
    missing = sorted(set(expected_calls) - set(got))
    return [f"okno wysyła inne żądania niż EXPECTED_CALLS: nowe {extra}, brakujące {missing}"]


def _keep(evidence: Path, name: str, run: Run, violations: Sequence[Violation], shared: Sequence[str] = ()) -> None:
    """Counterexample of each case with a violation: what broke, the requests and the states, and for a second run the
    other first runs it resumes (``shared``)."""

    if not violations:
        return
    folder = evidence / "kontrprzyklady"
    folder.mkdir(exist_ok=True)
    slug = "".join(char if char.isalnum() else "-" for char in name)[:150]
    ending = None if run.outcome is None else run.outcome.ending
    content = {
        "przypadek": name,
        "także po": list(shared),
        "naruszenia": [f"{violation.rule} | {violation.detail}" for violation in violations],
        "zakończenie": None
        if ending is None
        else {"kod": ending.message.code, "przyczyna": describe(ending.facts) if isinstance(ending, Stop) and isinstance(ending.facts, PricingStopped) else None}
        if isinstance(ending, Stop)
        else "wynik",
        "efenix przed": [str(state) for state in run.before],
        "efenix po": [str(state) for state in run.after.state],
        "Znaczniki": list(run.marked),
        "żądania": run.actions,
        "Logi": run.logs.splitlines(),
    }
    (folder / f"{slug}.json").write_text(json.dumps(content, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def gone_findings(report: Report) -> dict[str, list[str]]:
    """Each known finding with the cases of its ``after`` that this run or part ran and after which it did not show:
    each such case on its own, so a fix of one case gives it away while the finding still shows after the others."""

    gone: dict[str, list[str]] = {}
    for known in KNOWN_FINDINGS:
        shown = {violation.case for violation in report.known.get(known.name, [])}
        if missing := sorted(name for name in report.ran.intersection(known.after) if name not in shown):
            gone[known.name] = missing
    return gone


def summarize(report: Report) -> list[str]:
    lines = list(report.lines)
    groups: dict[tuple[str, str], list[Violation]] = {}
    for violation in report.new:
        groups.setdefault((violation.rule, violation.tag), []).append(violation)
    for (rule, tag), group in sorted(groups.items()):
        lines.append(f"NOWE NARUSZENIE {rule} ({tag}): {len(group)} przypadków")
        lines += [f"  {violation.case} | {violation.detail}" for violation in group[:3]]
    for name, group in sorted(report.known.items()):
        lines.append(f"znane ustalenie {name}: {len(group)} przypadków, np. {group[0].case} | {group[0].detail}")
    for name, group in sorted(report.accepted.items()):
        lines.append(f"zaakceptowane ryzyko {name}: {len(group)} przypadków, np. {group[0].case}")
    gone = gone_findings(report)
    lines += [
        f"ZNALEZISKO ZNIKNĘŁO {name} po {', '.join(missing)}: zawęź je w KNOWN_FINDINGS i w SKILL.md do przypadków, po "
        "których dalej występuje, albo je usuń"
        for name, missing in gone.items()
    ]
    if report.gaps:
        lines += [f"LUKA MODELU: {gap}" for gap in report.gaps]
        lines.append(f"{VERDICT}: LUKA MODELU ({len(report.gaps)})")
    elif report.new:
        lines.append(f"{VERDICT}: NOWE NARUSZENIE ({len({violation.case for violation in report.new})})")
    elif gone:
        lines.append(f"{VERDICT}: ZNALEZISKO ZNIKNĘŁO ({len(gone)})")
    else:
        lines.append(f"{VERDICT} OK")
    return lines


def doctor() -> list[str]:
    """Read-only check that a run is worth starting: Chromium of Playwright starts, the Atrapa and the proxy answer."""

    problems = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**efenix_browser.launch_options(playwright))
            try:
                with atrapa_efenix(efenix_orders(), emmett_reload_ms=EFENIX_EMMETT_RELOAD_MS) as atrapa, Proxy(atrapa.url, Plan(), atrapa.expire_session) as proxy:
                    page = browser.new_page()
                    response = page.goto(proxy.url, wait_until="load", timeout=10_000)
                    if response is None or not response.ok or page.locator("#field_numer").count() != 1:
                        problems.append("Atrapa efenix przez pośrednika nie pokazuje listy zleceń")
                    if [call.path for call in proxy.calls()][:1] != ["index.php"]:
                        problems.append("pośrednik nie widzi żądań okna")
            finally:
                browser.close()
    except Exception as error:  # noqa: BLE001 - the doctor names what does not start
        problems.append(f"Chromium Playwrighta albo Atrapa nie startuje: {type(error).__name__}: {error}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = Parser(description=__doc__.splitlines()[0])
    parser.add_run_dir()
    parser.add_variants(AXES, default="all", every=AXES)
    parser.add_argument("--rola", nargs="+", choices=[role.value for role in Role], help="tylko żądania tych ról")
    parser.add_argument("--rownolegle", type=int, default=min(4, os.cpu_count() or 1), help="przeglądarki naraz")
    parser.add_argument("--doctor", action="store_true", help="tylko sprawdź, czy przebieg ma sens")
    parser.add_argument("--zostaw-run", action="store_true", help="nie usuwaj katalogu runu (pliki przebiegów)")
    parser.add_argument("--lista", action="store_true", help="tylko wypisz przypadki tej części, bez przeglądarki")
    args = parser.parse_args(argv)
    if args.lista:
        print("\n".join(case.name for case in part(cases(args.variant, args.rola))))
        return 0
    if args.doctor:
        problems = doctor()
        print("\n".join(problems) or "DOCTOR OK: Chromium Playwrighta, Atrapa efenix i pośrednik działają")
        return 1 if problems else 0
    name = f"wycena-efenix-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{os.getpid()}"
    run = new_run(args.run_dir, name)
    create_run_root(run.root)
    try:
        report = explore(run.root, run.evidence, args.variant, args.rola, max(1, args.rownolegle))
    finally:
        if not args.zostaw_run:
            remove_run_root(run.root)
    lines = summarize(report)
    lines.insert(0, f"dowody: {run.evidence}")
    (run.evidence / "raport.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0 if lines[-1] == f"{VERDICT} OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
