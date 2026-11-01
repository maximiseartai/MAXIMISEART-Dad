"""Wycena w efenix: zlecenia z zakresu Pliku zbiorczego znalezione i sprawdzone w efenix, w sesji, którą otworzył tata.

Jedyną operacją publiczną jest ``price_orders()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty na
Komunikaty: Sprawdzanie (Plik zbiorczy jest i daje się otworzyć okno efenix z listą zleceń), Odczyt danych (zakres z
``efenix_orders``), Planowanie (Zatrzymanie, gdy Plik zbiorczy nie ma kwot AU policzonych przez Excel) i Zapisywanie, w
którym idzie przez zlecenia z zakresu po kolei. Każde zlecenie znajduje po ``Numer dokumentu`` równym ``NUMER ZL.`` i
sprawdza: dokładnie jedno trafienie, status „Do wyceny”, realizator równy ``WYKONAWCA``, ``Dane adresowe`` równe
``ADRES`` (``efenix_address``) i datę wykonania pustą albo równą dniowi z ``DATA``. Pierwsza niezgodność to błąd
zlecenia (``OrderProblem``) i proces idzie dalej. W efenix nic się nie zmienia: okno efenix (``Efenix``) zna tylko
szukanie i odczyt daty wykonania. Strona logowania i strona o innej budowie to Zatrzymanie (``LoggedOut``,
``UnexpectedPage``). Wynik nie zawiera numerów zleceń, adresów ani loginów, tylko numery wierszy Pliku zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import date
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
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .workbook_files import WorkbookError

__all__ = [
    "Efenix",
    "EfenixUnreachable",
    "Found",
    "ListedOrder",
    "LoggedOut",
    "OpenEfenix",
    "OrderError",
    "OrderProblem",
    "OrderResult",
    "PagePart",
    "PricingSummary",
    "UnexpectedPage",
    "price_orders",
]

class LoggedOut(Exception):
    """efenix pokazał stronę logowania zamiast strony, o którą prosiło okno."""


class PagePart(enum.Enum):
    """Część strony efenix, którą czyta okno."""

    LIST = "lista zleceń z polem Numer"
    RESULTS = "tabela wyników szukania"
    ORDER = "strona zlecenia z datą wykonania"


class UnexpectedPage(Exception):
    """Strona efenix nie ma budowy, którą zna okno; ``part`` to część, w której jej zabrakło (bez treści strony)."""

    def __init__(self, part: PagePart) -> None:
        super().__init__(part.name)
        self.part = part


class EfenixUnreachable(Exception):
    """Okno nie otworzyło strony efenix: adres nie odpowiada albo nie ma połączenia."""


class Efenix(Protocol):
    """Okno efenix w sesji taty z listą dozwolonych działań; nie ma w nim żadnego działania, które zmienia zlecenie.

    Każde działanie zgłasza ``LoggedOut`` na stronie logowania i ``UnexpectedPage`` na stronie o innej budowie.
    """

    def search(self, number: str) -> Sequence[ListedOrder]:
        """Wiersze listy zleceń po szukaniu po ``Numer``."""
        ...

    def execution_date(self, order: ListedOrder) -> date | None:
        """Data wykonania ze strony zlecenia; ``None``, gdy jej nie ma."""
        ...


OpenEfenix = Callable[[], AbstractContextManager[Efenix]]
"""Otwiera okno efenix z listą zleceń na czas Zapisywania; ``EfenixUnreachable``, ``LoggedOut`` albo ``UnexpectedPage``."""


@dataclass(frozen=True)
class Found:
    """Zlecenie jest w efenix dokładnie raz i zgadza się z Plikiem zbiorczym."""

    listed: ListedOrder


@dataclass(frozen=True)
class OrderError:
    """Zlecenie, które proces zostawia tacie: pierwsza niezgodność z efenix."""

    problem: OrderProblem


@dataclass(frozen=True)
class OrderResult:
    order: CollectiveOrder
    outcome: Found | OrderError


@dataclass
class PricingSummary:
    """Podsumowanie Wyceny w efenix: wynik każdego zlecenia z zakresu po kolei i liczby pominiętych Wierszy danych.

    ``warnings``: Komunikat każdego błędu zlecenia, z numerem wiersza Pliku zbiorczego.
    """

    results: tuple[OrderResult, ...]
    with_photos: int
    defects: int
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def found_count(self) -> int:
        return sum(isinstance(result.outcome, Found) for result in self.results)

    @property
    def error_count(self) -> int:
        return len(self.results) - self.found_count


def price_orders(
    source: Path,
    open_efenix: OpenEfenix,
    *,
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> PricingSummary:
    """Znajduje i sprawdza w efenix każde zlecenie z zakresu Pliku zbiorczego ``source``; plik i efenix zostają bez zmian.

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
            return tuple(OrderResult(order, _checked(order, efenix)) for order in scope.orders)

    results = phases.save(save)
    return PricingSummary(
        results,
        scope.with_photos,
        scope.defects,
        [messages.order_error(source, result.order.row, result.outcome.problem) for result in results if isinstance(result.outcome, OrderError)],
        phases.durations_ms(),
    )


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


def _checked(order: CollectiveOrder, efenix: Efenix) -> Found | OrderError:
    number = searched_number(order)
    if isinstance(number, OrderProblem):
        return OrderError(number)
    hit = listing(order, efenix.search(number))
    if isinstance(hit, OrderProblem):
        return OrderError(hit)
    if (problem := date_problem(order, efenix.execution_date(hit))) is not None:
        return OrderError(problem)
    return Found(hit)
