"""Exhaustively break each request of a Wycena w efenix and check the Zatrzymanie and the efenix state.

The checker runs the real process (``run_process`` with ``efenix_process.PROCESS``, the window ``efenix_browser.window``
in Playwright's Chromium, ``pace=None``) on the Atrapa efenix (``tests/fixtures/atrapa_efenix.py``) with two orders of a
synthetic Plik zbiorczy: order 1 (row 18) has an empty pricing, Emmett gives O and the process adds T and AG, so it ends
gotowe with a Znacznik efenix; order 2 (row 19) has an empty pricing and an Emmett that contradicts the file in T, so it
ends with an Ostrzeżenie Emmetta. Between the window and the Atrapa sits the proxy of ``awarie_efenix.py``.

First a run without a fault (the reference) gives the window's requests, which must be exactly ``EXPECTED_CALLS``
(otherwise the space is stale: ``LUKA MODELU``), and the state of the Atrapa, the Plik zbiorczy, the Ślad Wyceny Emmetta
and the dziennik before and after each request, which is what a killed tool leaves (``Fault.KILLED``, checked as it
is). Then each request gets each other ``Fault`` in its own run. The second Uruchomienie after a stop, with and without
Dad's changes in efenix, is the model's (``verify-wznowienie-wyceny-efenix``), not this checker's.

The invariants (``Rule``), each with the domain sentence it comes from:

- PRZYCZYNA: a Zatrzymanie names the fault the way the docstrings of ``efenix_browser`` and ``efenix_pricing.StopCause``
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
- BEZ_DANYCH: the Logi (orders, Zatrzymanie, Komunikaty), the dziennik and the Ślad have no order number, efenix
  identifier or address.
- BEZ_WYJATKU: a run ends with a result or a Zatrzymanie of the window, never with an unexpected error.

Run ``--doctor`` first. ``--variant`` picks fault axes, ``--rola`` request roles; CI splits the cases into parts with
``MUTACJE_CZESC=k/n`` (``part``). The last line is the verdict.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
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
    AheadNotSaved,
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
from tests.fixtures.efenix import Order, number_in_trace, write_collective_file
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
EMMETT: Final[tuple[Mapping[str, int], ...]] = ({"012": 1}, {"012": 1, "019": 5})
"""Emmett of order 2 gives 5 in T, the file has 2: an Ostrzeżenie Emmetta."""
DAYS: Final = (date(2026, 9, 1), date(2026, 9, 2))
ADDRESSES: Final = ("UL. KASZTANOWA 7/1", "UL. LIPOWA 3/9")
EFENIX_ADDRESSES: Final = ("Sopot-Centrum ul.Kasztanowa 7 Lokal 1", "Sopot-Centrum ul.Lipowa 3 Lokal 9")
FORBIDDEN_TEXT: Final = (*NUMBERS, *IDENTIFIERS, "kasztanow", "lipow", "sopot")
"""Text of the orders that no Logi, dziennik or Ślad may hold (compared without letter case)."""


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
"""Domain expectation of one run without a fault (``GLOSSARY.md``, Wycena w efenix): order 1 gets the date, Emmett and
the file's quantities in the positions empty at Emmett; order 2 gets the date and Emmett and nothing more."""
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
ALLOWED_PATHS: Final = frozenset(call.path for call, _role, _order in EXPECTED_CALLS) | {"page_login.php"}
"""Paths the window may reach: the reference requests and the login page an expired session redirects to."""

# --- Expected outcome of each fault: the domain table ---------------------------------------------------------------


class Cause(enum.Enum):
    """Domain category of a Zatrzymanie, from the docstrings of ``efenix_browser`` and ``StopCause``."""

    NETWORK = "błąd przeglądarki z nazwanym działaniem (sieć albo czas okna)"
    TIMEOUT = "czas okna minął (TimeoutError z nazwanym działaniem)"
    UNREACHABLE = "efenix nie otworzył się przy starcie (EfenixUnreachable)"
    HTTP = "strona błędu HTTP (HttpStatus ze statusem awarii)"
    LOGIN = "wylogowanie (LoggedOut albo formularz logowania)"
    CLOSED = "zamknięte okno (WindowClosed)"
    SHAPE = "strona w innej budowie (ElementCount, OtherShape)"
    NOT_LOADED = "efenix nie załadował Wyceny Emmetta po odpowiedzi 2xx (OtherShape EMMETT_NOT_LOADED)"
    UNNAMED = "błąd przeglądarki bez nazwanego działania"
    TRACE = "Ślad Wyceny Emmetta nie zapisał ilości z wyprzedzeniem (EFENIX_SLAD_NIEZAPISANY)"


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
    answer it never reads: amount 0 after an Emmett dialog that showed a proposal is ``Shape.EMMETT_NOT_LOADED``, a
    Zatrzymanie of the window, not a logout (``efenix_browser``: „Strona z kwotą 0 po oknie Emmetta, które coś
    pokazało, to UnexpectedPage z Shape.EMMETT_NOT_LOADED”); an expired session stays a logout. An answer to „Załaduj
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
        case Fault.REFUSED:
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
    zlecenia” (#889, ``EmmettRefusal.NOK`` of the Atrapa); a ``result: nok`` of the quantity save is the expired
    session, which ``LOGGED_OUT`` gives there."""

    match fault:
        case Fault.LOGIN_PAGE:
            return role in _ORDER_PAGES
        case Fault.REFUSED:
            return role is Role.LOAD
        case Fault.LOGIN_LATER | Fault.LOGIN_CLOSED | Fault.LOGIN_ERROR:
            return role is Role.LIST_START
        case _:
            return True


TRACE_NOT_SAVED: Final = "EFENIX_SLAD_NIEZAPISANY"
"""Komunikat of the Zatrzymanie after a failed write ahead of a quantity (``efenix_messages.emmett_trace_not_saved``)."""


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
    ``UnexpectedPage`` does, so its Komunikat tells them apart. A failed write of the Ślad ahead of a quantity stops
    the Wycena outside a page of efenix with ``AheadNotSaved`` (``efenix_pricing._WrittenAhead``); no fault of this
    checker touches the disk, so it is never the expected cause."""

    match facts.cause:
        case AheadNotSaved():
            return Cause.TRACE
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
        case AheadNotSaved(position):
            cause = f"AheadNotSaved({position})"
    return f"{part}, {cause}"


def code_of(facts: PricingStopped) -> str:
    """Komunikat of a Zatrzymanie (``efenix_pricing._efenix_stops``): a failed write of the Ślad is „Ślad
    niezapisany”, a sign of logout „wylogowany”, a closed window „okno zamknięte”, a browser failure at the list
    before it opened „niedostępny”, the rest „okno zatrzymane”."""

    match facts.cause:
        case AheadNotSaved():
            return TRACE_NOT_SAVED
        case LoginSign():
            return "EFENIX_WYLOGOWANY"
        case Closed():
            return "EFENIX_OKNO_ZAMKNIETE"
        case _:
            return "EFENIX_OKNO_ZATRZYMANE"

# --- Known findings -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A broken invariant ``rule`` in ``case``; ``tag`` names the kind of break for known findings."""

    rule: str
    tag: str
    case: str
    detail: str
    fault: Fault | None = None
    role: Role | None = None


@dataclass(frozen=True)
class Known:
    """A violation the code has today, which ``matches`` recognises. ``after``: the first runs (``Case.name``) after
    which it always shows, so a run, or a part of one, that ran one of them without it reports it gone; ``flaky``: a
    race that names none, because no run is sure to show it, so its absence is no sign it is gone."""

    name: str
    story: str
    matches: Callable[[Violation], bool]
    after: tuple[str, ...]
    flaky: bool = False

    def __post_init__(self) -> None:
        if self.flaky == bool(self.after):
            raise ValueError(f"znane ustalenie {self.name} nazywa przypadki, po których występuje, albo jest flaky")


KNOWN_FINDINGS: Final[tuple[Known, ...]] = ()
# --- Observing a run -------------------------------------------------------------------------------------------


def marked(source: Path) -> tuple[int, ...]:
    """Rows of the Plik zbiorczy whose ``ADRES`` has the Znacznik efenix, read the way Przebieg rozliczeń reads them."""

    rows = []
    for row in read_data_rows(source, despite_excel_lock=True).rows:
        fill = row.cells[1].highlights.fill
        if isinstance(fill, PatternFill) and fill.patternType == "solid" and str(fill.fgColor.rgb)[-6:].upper() == MARK_RGB:
            rows.append(row.number)
    return tuple(rows)


def trace_states(files: Mapping[str, bytes]) -> dict[str, object]:
    """The Ślad Wyceny Emmetta of the period from the files of its folder, by order number: ``"gotowe"`` or, for
    „Emmett załadowany”, ``{"emmett": {...}, "entering": {...}}`` with Emmett's quantities and the quantities the tool
    started entering.

    Read with its key (HMAC-SHA256 of the number), not through ``efenix_emmett_trace``. As its docstring says, a trace
    that cannot be read or has another shape is no trace, also one with a „Emmett załadowany” without ``entering``
    (the format before the write ahead)."""

    try:
        secret = bytes.fromhex(files["klucz"].decode("utf-8"))
        orders = json.loads(files[f"{PERIOD}.json"].decode("utf-8"))["orders"]
        entries = sorted(orders.items())
    except (KeyError, ValueError, TypeError, AttributeError):
        return {}
    if not all(_trace_entry(entry) for _key, entry in entries):
        return {}
    by_key = {hmac.new(secret, number.encode(), hashlib.sha256).hexdigest(): number for number in NUMBERS}
    return {by_key.get(key, f"nieznany {key[:8]}"): entry for key, entry in entries}


def _trace_entry(entry: object) -> bool:
    if entry == "gotowe":
        return True
    return (
        isinstance(entry, dict)
        and entry.keys() == {"emmett", "entering"}
        and all(isinstance(quantities, dict) and all(type(quantity) is int for quantity in quantities.values()) for quantities in entry.values())
    )


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
    """What a run leaves on disk and in efenix: Atrapa orders, the Plik zbiorczy, the Ślad folder and the dziennik."""

    orders: tuple[AtrapaOrder, ...]
    source: bytes
    traces: Mapping[str, bytes]
    journal: bytes

    @property
    def state(self) -> tuple[Priced, ...]:
        return tuple(priced(order) for order in self.orders)

def read_files(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    files = {}
    for path in sorted(directory.iterdir()):
        try:
            files[path.name] = path.read_bytes()
        except OSError:
            continue
    return files


@dataclass
class Run:
    """One Uruchomienie on the proxy: what the checker needs after it."""

    outcome: Outcome[PricingSummary] | None
    before: tuple[Priced, ...]
    after: Disk
    calls: list[Call]
    actions: list[str]
    status_changes: int
    forbidden_clicks: int
    marked: tuple[int, ...]
    traces: dict[str, object]
    logs: str
    error: str | None = None
    snapshots: dict[str, Disk] = field(default_factory=dict)
    injected: bool = True
    """The browser side did what the fault asks before the run ended (``TAB_CLOSED``, ``LOGIN_*``); a case whose fault
    did not take effect in ``RETRIES`` more tries is ``LUKA MODELU``, never a pass."""


@dataclass(frozen=True)
class Place:
    """Files of one run: Plik zbiorczy in its Folder okresu, the Ślad folder and the dziennik."""

    root: Path

    @property
    def source(self) -> Path:
        return self.root / "plik" / PERIOD / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"

    @property
    def traces(self) -> Path:
        return self.root / "slad"

    @property
    def journal(self) -> Path:
        return self.root / "dziennik.jsonl"

    def prepare(self, source: bytes) -> None:
        """The Plik zbiorczy ``source`` without a Ślad and with an empty dziennik, as before the first Uruchomienie."""

        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(source)
        self.traces.mkdir()
        self.journal.write_bytes(b"")

    def disk(self, orders: Sequence[AtrapaOrder]) -> Disk:
        return Disk(tuple(copy.deepcopy(list(orders))), self.source.read_bytes(), read_files(self.traces), _read(self.journal))


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def logs_text(outcome: Outcome[PricingSummary] | None, journal: bytes, traces: Mapping[str, bytes]) -> str:
    """The Logi of the run as Centrum writes them for a Wycena w efenix (orders, Zatrzymanie, Komunikaty), the dziennik
    and the Ślad files, one text for the BEZ_DANYCH check."""

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


def run_once(browser: Browser, place: Place, plan: Plan, *, snapshots: bool = False) -> Run:
    """One Uruchomienie on a new Atrapa with ``efenix_orders()`` behind the proxy with ``plan``, on the files in ``place``.

    The Atrapa reloads the page after „Załaduj do zlecenia” as late as efenix does (``EFENIX_EMMETT_RELOAD_MS``), not
    as early as its tests do, so the window meets that reload when it would at Dad's."""

    taken: dict[str, Disk] = {}
    with atrapa_efenix(efenix_orders(), emmett_reload_ms=EFENIX_EMMETT_RELOAD_MS) as atrapa:

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
        actions=[f"{entry.at:7.2f} s  {entry.call}{'  ← ' + entry.action if entry.action else ''}" for entry in seen],
        status_changes=status_changes,
        forbidden_clicks=clicks,
        marked=marked(place.source),
        traces=trace_states(after.traces),
        logs=logs_text(outcome, after.journal, after.traces),
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
        EfenixInputs(place.source, open_efenix, pace=None, trace_directory=place.traces, journal=Journal(place.journal)),
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


def common_checks(name: str, run: Run, extra: Mapping[str, object]) -> list[Violation]:
    """BEZ_ZMIANY_STATUSU, ZMIANA_ZE_SLADEM and BEZ_DANYCH of any run, which starts from ``INITIAL``."""

    found: list[Violation] = []

    def add(rule: str, tag: str, detail: str) -> None:
        found.append(Violation(rule, tag, name, detail, **extra))  # type: ignore[arg-type]

    after = run.after.state
    if run.status_changes or run.forbidden_clicks:
        add("BEZ_ZMIANY_STATUSU", "status", f"zmiany statusu {run.status_changes}, kliknięcia spoza listy {run.forbidden_clicks}")
    if outside := sorted({call.path for call in run.calls} - ALLOWED_PATHS):
        add("BEZ_ZMIANY_STATUSU", "żądanie spoza listy", f"okno wysłało żądania spoza listy dozwolonych: {', '.join(outside)}")
    if [state.status for state in after] != [state.status for state in INITIAL]:
        add("BEZ_ZMIANY_STATUSU", "status", f"status zlecenia zmienił się: {[str(state) for state in after]}")
    steps = _steps(run.outcome)
    begun = Journal.begun_rows(run.after.journal.decode("utf-8", "replace"))
    for index, (was, now) in enumerate(zip(INITIAL, after, strict=True)):
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
        if isinstance(outcome.ending, Stop) and "W efenix nic się nie zmieniło." in outcome.ending.message.what and tuple(after) != INITIAL:
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
        add("BEZ_DANYCH", "dane zleceń", f"Logi, dziennik albo Ślad mają: {', '.join(leaked)}")
    return found


def leaks(run: Run) -> list[str]:
    """BEZ_DANYCH: order numbers, efenix identifiers and address words in the Logi, the dziennik or the Ślad."""

    text = run.logs.casefold()
    leaked = [word for word in FORBIDDEN_TEXT if word.casefold() in text]
    trace_text = "\n".join(content.decode("utf-8", "replace") for content in run.after.traces.values())
    leaked += [f"{number} w Śladzie" for number in NUMBERS if number_in_trace(number, trace_text)]
    leaked += [f"{word} w Śladzie" for word in FORBIDDEN_TEXT if word not in NUMBERS and word.casefold() in trace_text.casefold()]
    return leaked


def killed_run(snapshot: Disk, source: Path) -> Run:
    """What the tool killed at the moment of ``snapshot`` leaves, as a run without an outcome: no Logi, no Komunikat,
    only efenix, the Plik zbiorczy (written to ``source`` to read its Znaczniki), the Ślad and the dziennik."""

    source.write_bytes(snapshot.source)
    return Run(
        outcome=None,
        before=INITIAL,
        after=snapshot,
        calls=[],
        actions=[],
        status_changes=0,
        forbidden_clicks=0,
        marked=marked(source),
        traces=trace_states(snapshot.traces),
        logs=logs_text(None, snapshot.journal, snapshot.traces),
    )


def check_killed(name: str, case: Case, run: Run) -> list[Violation]:
    """ZMIANA_ZE_SLADEM, BEZ_ZMIANY_STATUSU and BEZ_DANYCH of what a tool killed at ``case`` leaves: no order changed
    its status; every order changed in efenix has its „zaczynam” entry in the dziennik (``pricing_journal``: „zaczynam
    zlecenie” … „przed pierwszym działaniem okna efenix przy zleceniu, więc przed każdym zapisem w efenix”); the Plik
    zbiorczy has no Znacznik efenix, because Zapisywanie sets them at its end (``efenix_pricing``: „na końcu Znaczniki
    efenix”); an order the dziennik ended gotowe has the file's quantities, ``Kwota`` (AU) and the date in efenix; and
    the dziennik and the Ślad have no order data."""

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
        add("BEZ_DANYCH", "dane zleceń", f"dziennik albo Ślad mają: {', '.join(leaked)}")
    return found


def check_first(case: Case, run: Run) -> list[Violation]:
    """PRZYCZYNA, BEZ_WYJATKU and the common checks of a run with ``case``."""

    extra: dict[str, object] = {"fault": case.fault, "role": case.role}
    found = common_checks(case.name, run, extra)

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
    "odpowiedzi": (Fault.HTTP_4XX, Fault.HTTP_5XX, Fault.LOGGED_OUT, Fault.REDIRECT, Fault.REFUSED, Fault.HUNG, Fault.LOGIN_PAGE),
    "granica-czasu": (Fault.LATE_BEFORE, Fault.LATE_AFTER),
    "zamkniete-okno": (Fault.TAB_CLOSED,),
    "logowanie": (Fault.LOGIN_LATER, Fault.LOGIN_CLOSED, Fault.LOGIN_ERROR),
    "zabity-proces": (Fault.KILLED,),
}
"""Fault axes, the ``--variant`` names."""


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
    gaps: list[str] = field(default_factory=list)
    ran: set[str] = field(default_factory=set)
    """Names of the first runs whose fault took effect."""


def sort_violations(violations: Sequence[Violation], report: Report) -> None:
    for violation in violations:
        if known := next((known for known in KNOWN_FINDINGS if known.matches(violation)), None):
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
    blank = write_collective_file(run_root / "wzor", file_orders()).read_bytes()
    counter = iter(range(1_000_000))

    def place() -> Place:
        prepared = Place(run_root / f"run-{next(counter):05d}")
        prepared.prepare(blank)
        return prepared

    def task(case: Case | None, *, snapshots: bool = False) -> Callable[[Browser], object]:
        return lambda browser: run_once(browser, place(), plan_of(case), snapshots=snapshots)

    [reference] = in_pool(
        [task(None, snapshots=True)],
        1,
        lambda _index: "przebieg bez awarii",
    )
    if not isinstance(reference, Run):
        report.gaps.append(f"przebieg bez awarii nie przeszedł: {reference!r}")
        return report
    (evidence / "przebieg-bez-awarii.txt").write_text("\n".join(reference.actions) + "\n", encoding="utf-8")
    broken = reference_violations(reference) + common_checks("przebieg bez awarii", reference, {})
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
    report.lines.append(
        f"{VERDICT} | {len(first)} przebiegów z awarią, {2 * len(killed)} stanów po zabiciu | "
        f"{time.monotonic() - started:.0f} s, {workers} przeglądarki"
    )
    return report


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


def _keep(evidence: Path, name: str, run: Run, violations: Sequence[Violation]) -> None:
    """Counterexample of each case with a violation: what broke, the requests and the states."""

    if not violations:
        return
    folder = evidence / "kontrprzyklady"
    folder.mkdir(exist_ok=True)
    slug = "".join(char if char.isalnum() else "-" for char in name)[:150]
    ending = None if run.outcome is None else run.outcome.ending
    content = {
        "przypadek": name,
        "naruszenia": [f"{violation.rule} | {violation.detail}" for violation in violations],
        "zakończenie": None
        if ending is None
        else {"kod": ending.message.code, "przyczyna": describe(ending.facts) if isinstance(ending, Stop) and isinstance(ending.facts, PricingStopped) else None}
        if isinstance(ending, Stop)
        else "wynik",
        "efenix przed": [str(state) for state in run.before],
        "efenix po": [str(state) for state in run.after.state],
        "Znaczniki": list(run.marked),
        "Ślad": run.traces,
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
