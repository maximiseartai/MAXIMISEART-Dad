"""Wycena w efenix: wycena każdego zlecenia z zakresu Pliku zbiorczego uzupełniona w efenix, w sesji, którą otworzył tata.

Jedyną operacją publiczną jest ``price_orders()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty na
Komunikaty: Sprawdzanie (Plik zbiorczy jest i daje się otworzyć okno efenix z listą zleceń), Odczyt danych (zakres z
``efenix_orders``), Planowanie (Zatrzymanie, gdy Plik zbiorczy nie ma kwot AU policzonych przez Excel) i Zapisywanie, w
którym idzie przez zlecenia z zakresu po kolei. Najpierw to, co widać bez efenix: numer, data i ilości, które da się
przepisać (``efenix_positions``). Potem zlecenie znajduje po ``Numer dokumentu`` równym ``NUMER ZL.`` i sprawdza:
dokładnie jedno trafienie, status „Do wyceny”, realizator równy ``WYKONAWCA``, ``Dane adresowe`` równe ``ADRES``
(``efenix_address``) i datę wykonania pustą albo równą dniowi z ``DATA``. Pierwsza niezgodność to błąd zlecenia, w efenix
nic się nie zmienia i proces idzie dalej.

Zlecenie z kwotą w efenix różną od 0 ma już wycenę: proces tylko ją porównuje i jest „gotowe”, gdy każda ilość i kwota
zgadzają się z plikiem, a w przeciwnym razie to błąd „wycena już jest i się różni”. Przy kwocie 0 proces ustawia pustą
datę wykonania z ``DATA``, ładuje Wycenę Emmetta i czyta jej ilości: sprzeczność z plikiem to ostrzeżenie bez dopisywania,
a w przeciwnym razie wpisuje ilości pliku w pozycjach pustych u Emmetta i porównuje kwotę końcową, którą odesłał efenix,
z ``Kwota`` (AU). Okno efenix (``Efenix``) nie ma działania, które przekazuje zlecenie do akceptacji, anuluje je albo
zmienia jego status. Strona logowania i strona o innej budowie, także bez pozycji z przypisania kolumn, to Zatrzymanie
(``LoggedOut``, ``UnexpectedPage``). Wynik nie zawiera numerów zleceń, adresów ani loginów, tylko numery wierszy Pliku
zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import enum
from pathlib import Path
import time
from types import MappingProxyType
from typing import Protocol

from . import efenix_messages as messages
from . import workbook_files
from .domain import ProgressObserver, ProgressPhase
from .efenix_checks import ListedOrder, OrderProblem, date_problem, listing, searched_number
from .efenix_orders import AmountsNotComputed, CollectiveOrder, MissingColumns, PricingScope, read_scope
from .efenix_positions import (
    Conflict,
    NotWholeQuantities,
    OrderFault,
    OtherAmount,
    UnpairedColumns,
    emmett_conflicts,
    file_quantities,
    missing_positions,
    priced_differently,
    same_amount,
    to_enter,
)
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .workbook_files import WorkbookError

__all__ = [
    "Efenix",
    "EfenixUnreachable",
    "EmmettWarning",
    "ListedOrder",
    "LoggedOut",
    "OpenEfenix",
    "OrderError",
    "OrderPricing",
    "OrderProblem",
    "OrderResult",
    "PagePart",
    "PricingSummary",
    "Ready",
    "UnexpectedPage",
    "price_orders",
]


class LoggedOut(Exception):
    """efenix pokazał stronę logowania zamiast strony, o którą prosiło okno."""


class PagePart(enum.Enum):
    """Część strony efenix, którą czyta okno."""

    LIST = "lista zleceń z polem Numer"
    RESULTS = "tabela wyników szukania"
    ORDER = "strona zlecenia z datą wykonania i wyceną"
    DATE = "okno daty wykonania"
    EMMETT = "Wycena Emmetta"
    QUANTITY = "pole Ilość i kwota końcowa"


class UnexpectedPage(Exception):
    """Strona efenix nie ma budowy, którą zna okno; ``part`` to część, w której jej zabrakło (bez treści strony)."""

    def __init__(self, part: PagePart) -> None:
        super().__init__(part.name)
        self.part = part


class EfenixUnreachable(Exception):
    """Okno nie otworzyło strony efenix: adres nie odpowiada albo nie ma połączenia."""


@dataclass(frozen=True)
class OrderPricing:
    """Strona zlecenia efenix w tym, co porównuje proces: data wykonania (``None``, gdy pusta), kwota końcowa i ilość
    każdej pozycji wyceny (kod ``NNN`` → ilość, pole puste to 0)."""

    execution_date: date | None
    amount: Decimal
    quantities: Mapping[str, int]


class Efenix(Protocol):
    """Okno efenix w sesji taty z listą dozwolonych działań: szukanie, otwarcie zlecenia, data wykonania, Wycena Emmetta i
    pola „Ilość”. Przekazania do akceptacji, anulowania ani zmiany statusu zlecenia w nim nie ma.

    Działania po ``open_order`` dotyczą otwartego zlecenia. Każde działanie zgłasza ``LoggedOut`` na stronie logowania i
    ``UnexpectedPage`` na stronie o innej budowie.
    """

    def search(self, number: str) -> Sequence[ListedOrder]:
        """Wiersze listy zleceń po szukaniu po ``Numer``."""
        ...

    def open_order(self, order: ListedOrder) -> OrderPricing:
        """Otwiera stronę zlecenia i czyta jego datę wykonania i wycenę."""
        ...

    def set_execution_date(self, day: date) -> None:
        """Ustawia datę wykonania otwartego zlecenia."""
        ...

    def load_emmett(self) -> OrderPricing:
        """Ładuje do otwartego zlecenia Wycenę Emmetta (efenix czyści wtedy dotychczasową wycenę) i czyta stronę od nowa."""
        ...

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        """Wpisuje ``quantity`` w pole „Ilość” pozycji ``position`` otwartego zlecenia; kwota końcowa, którą odesłał efenix."""
        ...


OpenEfenix = Callable[[], AbstractContextManager[Efenix]]
"""Otwiera okno efenix z listą zleceń na czas Zapisywania; ``EfenixUnreachable``, ``LoggedOut`` albo ``UnexpectedPage``."""


@dataclass(frozen=True)
class Ready:
    """Wycena zlecenia w efenix zgadza się z Plikiem zbiorczym, a kwota końcowa jest równa ``Kwota`` (AU)."""

    listed: ListedOrder


@dataclass(frozen=True)
class OrderError:
    """Zlecenie, które proces zostawia tacie: pierwsza niezgodność z efenix albo kwota inna niż AU."""

    problem: OrderFault


@dataclass(frozen=True)
class EmmettWarning:
    """Emmett wpisał w pozycjach ilości inne niż Plik zbiorczy, więc proces niczego nie dopisał."""

    conflicts: tuple[Conflict, ...]


@dataclass(frozen=True)
class OrderResult:
    order: CollectiveOrder
    outcome: Ready | OrderError | EmmettWarning


@dataclass
class PricingSummary:
    """Podsumowanie Wyceny w efenix: wynik każdego zlecenia z zakresu po kolei i liczby pominiętych Wierszy danych.

    ``warnings``: Komunikat każdego błędu zlecenia i każdego ostrzeżenia Emmetta, z numerem wiersza Pliku zbiorczego.
    """

    results: tuple[OrderResult, ...]
    with_photos: int
    defects: int
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def ready_count(self) -> int:
        return sum(isinstance(result.outcome, Ready) for result in self.results)

    @property
    def error_count(self) -> int:
        return sum(isinstance(result.outcome, OrderError) for result in self.results)

    @property
    def warning_count(self) -> int:
        return sum(isinstance(result.outcome, EmmettWarning) for result in self.results)


def price_orders(
    source: Path,
    open_efenix: OpenEfenix,
    *,
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> PricingSummary:
    """Uzupełnia w efenix wycenę każdego zlecenia z zakresu Pliku zbiorczego ``source``; plik zostaje bez zmian.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie. ``clock`` to zegar w sekundach, z którego liczone są
    czasy etapów.
    """

    phases = PhaseRunner(observer, clock=clock)
    source = source.expanduser().resolve()

    def check() -> None:
        try:
            workbook_files.ensure_available(source, despite_excel_lock=True)
        except WorkbookError as error:
            raise StopError(messages.source_unusable(error)) from error

    phases.check(check)

    def read() -> PricingScope | AmountsNotComputed | MissingColumns:
        try:
            return read_scope(source)
        except WorkbookError as error:
            raise StopError(messages.source_unusable(error)) from error

    read_outcome = phases.read(read)

    def plan() -> PricingScope:
        match read_outcome:
            case MissingColumns(headers):
                raise StopError(messages.missing_columns(source, headers))
            case AmountsNotComputed(row):
                raise StopError(messages.amounts_not_computed(source, row))
            case PricingScope():
                return read_outcome

    scope = phases.plan(plan, issue_count=lambda _: 0)

    def save() -> tuple[OrderResult, ...]:
        with _efenix_stops(), open_efenix() as efenix:
            return tuple(OrderResult(order, _priced(order, efenix)) for order in scope.orders)

    results = phases.save(save)
    return PricingSummary(
        results,
        scope.with_photos,
        scope.defects,
        [warning for result in results if (warning := _warning(source, result)) is not None],
        phases.durations_ms(),
    )


def _warning(source: Path, result: OrderResult) -> Message | None:
    match result.outcome:
        case Ready():
            return None
        case OrderError(problem):
            return messages.order_error(source, result.order.row, problem)
        case EmmettWarning(conflicts):
            return messages.emmett_conflict(source, result.order.row, conflicts)


@contextmanager
def _efenix_stops() -> Iterator[None]:
    """Strona logowania, nieznana budowa strony i brak połączenia z efenix to Zatrzymanie z Komunikatem procesu."""

    try:
        yield
    except LoggedOut as error:
        raise StopError(messages.logged_out()) from error
    except UnexpectedPage as error:
        raise StopError(messages.efenix_changed()) from error
    except EfenixUnreachable as error:
        raise StopError(messages.efenix_unreachable()) from error


def _priced(order: CollectiveOrder, efenix: Efenix) -> Ready | OrderError | EmmettWarning:
    searched = searched_number(order)
    if isinstance(searched, OrderProblem):
        return OrderError(searched)
    number, day = searched
    file = file_quantities(order)
    if isinstance(file, (UnpairedColumns, NotWholeQuantities)):
        return OrderError(file)
    hit = listing(order, efenix.search(number))
    if isinstance(hit, OrderProblem):
        return OrderError(hit)
    opened = _known_positions(efenix.open_order(hit))
    if (problem := date_problem(order, opened.execution_date)) is not None:
        return OrderError(problem)
    if opened.amount != 0:
        differs = priced_differently(file, opened.quantities, opened.amount, order.amount)
        return Ready(hit) if differs is None else OrderError(differs)
    if opened.execution_date is None:
        efenix.set_execution_date(day)
    emmett = _known_positions(efenix.load_emmett())
    if conflicts := emmett_conflicts(file, emmett.quantities):
        return EmmettWarning(conflicts)
    amount = emmett.amount
    for position, quantity in to_enter(file, emmett.quantities).items():
        amount = efenix.enter_quantity(position, quantity)
    return Ready(hit) if same_amount(amount, order.amount) else OrderError(OtherAmount(amount, order.amount))


def _known_positions(pricing: OrderPricing) -> OrderPricing:
    """Strona zlecenia bez którejś pozycji z przypisania kolumn to efenix o innej budowie, niż zna narzędzie."""

    if missing_positions(pricing.quantities):
        raise UnexpectedPage(PagePart.ORDER)
    return pricing
