"""Wycena w efenix: wycena każdego zlecenia z zakresu Pliku zbiorczego uzupełniona w efenix, w sesji, którą otworzył tata.

Jedyną operacją publiczną jest ``price_orders()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty na
Komunikaty: Sprawdzanie (Plik zbiorczy jest, nie trzyma go Excel i daje się otworzyć okno efenix z listą zleceń), Odczyt
danych (zakres z ``efenix_orders``), Planowanie (Zatrzymanie, gdy Plik zbiorczy nie ma kwot AU policzonych przez Excel) i
Zapisywanie, w którym idzie przez zlecenia z zakresu po kolei, a na końcu raz oznacza gotowe Znacznikiem efenix. Najpierw to, co widać bez efenix: numer, data i ilości, które da się
przepisać (``efenix_positions``). Potem zlecenie znajduje po ``Numer dokumentu`` równym ``NUMER ZL.`` i sprawdza:
dokładnie jedno trafienie, status „Do wyceny”, realizator równy ``WYKONAWCA``, ``Dane adresowe`` równe ``ADRES``
(``efenix_address``) i datę wykonania pustą albo równą dniowi z ``DATA``. Pierwsza niezgodność to błąd zlecenia, w efenix
nic się nie zmienia i proces idzie dalej.

Zlecenie z kwotą w efenix różną od 0 ma już wycenę: proces tylko ją porównuje i jest „gotowe”, gdy każda ilość i kwota
zgadzają się z plikiem, a w przeciwnym razie to błąd „wycena już jest i się różni”. Wyjątkiem jest wycena, którą proces
sam zaczął i której nie skończył, bo przerwało ją Zatrzymanie: zlecenie w stanie „Emmett załadowany” Śladu Wyceny
Emmetta (``efenix_emmett_trace``) i z datą wykonania proces dokańcza jak po Emmetcie, z ilościami Emmetta ze śladu, gdy
strona ma tylko ilości, które zostawia po Emmetcie (``as_left_after_emmett``): sprzeczność Emmetta ze śladu z plikiem to
ostrzeżenie bez dopisywania. Strona z inną ilością, także z usuniętą ilością Emmetta, i strona bez daty wykonania to
błąd „wycena już jest i się różni” bez zmian. Stan „Emmett załadowany” proces zapisuje dopiero po odczycie Wyceny
Emmetta ze strony przeładowanej po „Załaduj do zlecenia”, a zlecenie z tym stanem, które skończyło się wynikiem (gotowe,
ostrzeżenie Emmetta albo błąd), przechodzi w stan „gotowe” śladu, więc wyceny zaczętej przez tatę ani skończonej przez
proces nigdy nie dokańcza. Przy kwocie 0 proces ustawia pustą datę wykonania z ``DATA`` i sprawdza ją na ponownie
otwartej stronie zlecenia: dzień, którego kalendarz efenix nie przyjął albo którego efenix nie zapisał, to błąd zlecenia
(``DateRefused``) bez Emmetta i bez ilości. Potem ładuje Wycenę Emmetta i zapisuje w śladzie jej ilości; pustej Wyceny
Emmetta zlecenia w stanie „Emmett załadowany” nie ładuje drugi raz. Sprzeczność Emmetta z plikiem to ostrzeżenie bez
dopisywania, a w przeciwnym razie proces wpisuje ilości pliku w pozycjach pustych u Emmetta i porównuje kwotę końcową,
którą odesłał efenix, z ``Kwota`` (AU). Okno efenix (``Efenix``) nie ma działania, które przekazuje zlecenie do
akceptacji, anuluje je albo zmienia jego status. Strona logowania i strona o innej budowie, także bez pozycji z
przypisania kolumn, to Zatrzymanie (``LoggedOut``, ``UnexpectedPage``), tak samo zamknięte okno efenix
(``WindowClosed``) i brak połączenia z efenix, także zerwany albo wolny w trakcie (``EfenixUnreachable``), a Komunikat
Zatrzymania mówi, czy przed nim proces zmienił już coś w efenix. Zmieniona strona efenix to Zatrzymanie „do Maksa” z
częścią strony, której zabrakło, bez treści strony; brak połączenia to Zatrzymanie dla taty, który uruchamia ponownie.
Okno, które czeka, aż tata się zaloguje, robi to w ``Login`` od silnika: ten czas nie wlicza się do czasów etapów ani,
przez ``waiting`` rozmowy rdzenia, do ``Czas uruchomienia``. Postęp Zapisywania to kroki (``PhaseRunner.step``):
logowanie, zlecenia z Wykonawcą i liczbą sprawdzonych z wszystkich, na końcu Znaczniki efenix; ślad działań okna przy
każdym zleceniu (``efenix_trace``) trafia do jego wyniku, a stamtąd do Logów Uruchomienia.

Po ostatnim zleceniu, a także przy Zatrzymaniu w trakcie, ``efenix_marking`` raz zapisuje Plik zbiorczy: komórka ``ADRES``
każdego gotowego zlecenia dostaje Znacznik efenix, a reszta pliku zostaje bajt w bajt. Gdy zapis się nie udaje (Excel trzyma
plik, plik zmienił się od odczytu, zapis nieudany), przebieg kończy się Zatrzymaniem z prośbą o ponowne uruchomienie, a
wycena w efenix zostaje; przy Zatrzymaniu z efenix zostaje jego Komunikat, bo ponowne uruchomienie i tak jest potrzebne.
Ponowne uruchomienie dokańcza oznaczanie: gotowe zlecenia mają już wycenę, więc proces je tylko czyta. Wynik nie zawiera
numerów zleceń, adresów ani loginów, tylko numery wierszy Pliku zbiorczego.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from . import efenix_messages as messages
from . import efenix_trace, workbook_files
from .domain import ProgressObserver, ProgressPhase
from .efenix_checks import (
    DateRefused,
    ListedOrder,
    OrderProblem,
    PagePart,
    date_problem,
    listing,
    searched_number,
)
from .efenix_emmett_trace import EmmettTrace
from .efenix_marking import Refusal, mark_ready
from .efenix_orders import (
    AmountsNotComputed,
    CollectiveOrder,
    MissingColumns,
    PricingScope,
    read_scope,
)
from .efenix_pace import Pace, Pacing
from .efenix_positions import (
    Conflict,
    NotWholeQuantities,
    OrderFault,
    OtherAmount,
    UnpairedColumns,
    as_left_after_emmett,
    emmett_conflicts,
    file_quantities,
    missing_positions,
    priced_differently,
    same_amount,
    to_enter,
)
from .efenix_trace import OrderTrace, TraceStep
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .workbook_files import WorkbookError

__all__ = [
    "BrowserNotStarted",
    "Efenix",
    "EfenixUnreachable",
    "EmmettWarning",
    "ListedOrder",
    "LoggedOut",
    "Login",
    "OpenEfenix",
    "OrderError",
    "OrderPricing",
    "OrderProblem",
    "OrderResult",
    "PagePart",
    "PricingSummary",
    "Ready",
    "UnexpectedPage",
    "WindowClosed",
    "price_orders",
]


class LoggedOut(Exception):
    """efenix pokazał stronę logowania zamiast strony, o którą prosiło okno."""


class UnexpectedPage(Exception):
    """Strona efenix nie ma budowy, którą zna okno; ``part`` to część, w której jej zabrakło (bez treści strony)."""

    def __init__(self, part: PagePart) -> None:
        super().__init__(part.name)
        self.part = part


class EfenixUnreachable(Exception):
    """Brak połączenia z efenix: okno nie otworzyło strony efenix albo żądanie działania okna zerwała sieć lub efenix
    nie odpowiedział na nie w czasie okna."""


class WindowClosed(Exception):
    """Okno albo karta efenix zamknęły się w trakcie przebiegu (tata je zamknął)."""


class BrowserNotStarted(Exception):
    """Przeglądarka okna efenix nie wystartowała: nie ma jej na komputerze albo jej profil trzyma inne okno."""


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

    Działania po ``open_order`` dotyczą otwartego zlecenia. Każde działanie zgłasza ``LoggedOut`` na stronie logowania,
    ``UnexpectedPage`` na stronie o innej budowie, ``EfenixUnreachable`` bez połączenia z efenix i ``WindowClosed`` w
    zamkniętym oknie.
    """

    @property
    def sent_change(self) -> bool:
        """Okno kliknęło już przycisk, który wysyła do efenix zmianę zlecenia (data wykonania, Wycena Emmetta, ilość)."""
        ...

    def search(self, number: str) -> Sequence[ListedOrder]:
        """Wiersze listy zleceń po szukaniu po ``Numer``."""
        ...

    def open_order(self, order: ListedOrder) -> OrderPricing:
        """Otwiera stronę zlecenia i czyta jego datę wykonania i wycenę."""
        ...

    def set_execution_date(self, day: date) -> bool:
        """Wybiera ``day`` w kalendarzu daty wykonania otwartego zlecenia i potwierdza go.

        ``False``, gdy kalendarz efenix zamienił dzień na inny: wtedy okno zamyka kalendarz bez „Potwierdź” i niczego nie
        wysyła. ``True`` znaczy tylko, że efenix odpowiedział na „Potwierdź”; czy zapisał dzień, pokazuje ``open_order``.
        """
        ...

    def load_emmett(self) -> OrderPricing:
        """Ładuje do otwartego zlecenia Wycenę Emmetta (efenix czyści wtedy dotychczasową wycenę) i czyta stronę od nowa."""
        ...

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        """Wpisuje ``quantity`` w pole „Ilość” pozycji ``position`` otwartego zlecenia; kwota końcowa, którą odesłał efenix."""
        ...


Login = Callable[[], AbstractContextManager[None]]
"""Czas, w którym okno czeka, aż tata zaloguje się w efenix; silnik nie liczy go do czasów Uruchomienia."""

OpenEfenix = Callable[[Login], AbstractContextManager[Efenix]]
"""Otwiera okno efenix z listą zleceń na czas Zapisywania, a czekanie na logowanie taty robi w ``Login``;
``BrowserNotStarted``, ``EfenixUnreachable``, ``LoggedOut``, ``UnexpectedPage`` albo ``WindowClosed``."""


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
    """Wynik zlecenia; ``steps``: ślad działań okna efenix przy nim, po kolei (``efenix_trace``)."""

    order: CollectiveOrder
    outcome: Ready | OrderError | EmmettWarning
    steps: tuple[TraceStep, ...] = ()


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

    @property
    def not_found(self) -> int:
        """Błędy zleceń, których efenix nie zna po numerze z ``NUMER ZL.``."""

        return sum(
            isinstance(result.outcome, OrderError) and result.outcome.problem is OrderProblem.UNKNOWN_NUMBER
            for result in self.results
        )

    @property
    def left_for_tata(self) -> tuple[tuple[OrderResult, Message], ...]:
        """Każde zlecenie z błędem albo ostrzeżeniem Emmetta po kolei z Komunikatem z ``warnings``."""

        left = [result for result in self.results if not isinstance(result.outcome, Ready)]
        return tuple(zip(left, self.warnings, strict=True))


# Kroki Zapisywania na karcie Uruchomienia.
_LOGIN: Final = "Zaloguj się w oknie efenix"
_ORDERS: Final = "Zlecenia"
_MARKING: Final = "Znaczniki efenix w Pliku zbiorczym"


def price_orders(
    source: Path,
    open_efenix: OpenEfenix,
    trace_file: Path,
    *,
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
    waiting: Login = nullcontext,
    pace: Pace | None = None,
) -> PricingSummary:
    """Uzupełnia w efenix wycenę każdego zlecenia z zakresu Pliku zbiorczego ``source`` i oznacza w nim gotowe zlecenia.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie. ``trace_file``: plik Śladu Wyceny Emmetta okresu
    (``efenix_emmett_trace``). ``clock`` to zegar w sekundach, z którego liczone są czasy etapów i śladu zleceń, a
    ``waiting`` wstrzymuje zegar rozmówcy na czas czekania na logowanie taty. ``pace``: tempo ludzkie okna
    (``efenix_pace``), ``None`` bez przerw.
    """

    phases = PhaseRunner(observer, clock=clock)
    source = source.expanduser().resolve()

    def check() -> None:
        try:
            workbook_files.ensure_available(source)
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

    @contextmanager
    def login() -> Iterator[None]:
        with phases.waiting(), waiting():
            phases.step(_LOGIN)
            yield

    def save() -> tuple[OrderResult, ...]:
        results: list[OrderResult] = []
        emmett_trace = EmmettTrace(trace_file)
        pacing = None if pace is None else Pacing(pace)
        try:
            with _efenix_stops(lambda: False), open_efenix(login) as efenix:
                with _efenix_stops(lambda: efenix.sent_change):
                    for done, order in enumerate(scope.orders):
                        phases.step(_ORDERS, worker=order.worker, done=done, total=len(scope.orders))
                        trace = OrderTrace()
                        window = efenix_trace.traced(efenix, trace, clock)
                        outcome = _priced(order, window if pacing is None else pacing.window(window), emmett_trace)
                        results.append(OrderResult(order, outcome, tuple(trace.steps)))
        except StopError:
            phases.step(_MARKING)
            _mark(source, scope, results)
            raise
        phases.step(_MARKING)
        if (refusal := _mark(source, scope, results)) is not None:
            raise StopError(messages.marks_not_saved(source, refusal))
        return tuple(results)

    results = phases.save(save)
    return PricingSummary(
        results,
        scope.with_photos,
        scope.defects,
        [warning for result in results if (warning := _warning(source, result)) is not None],
        phases.durations_ms(),
    )


def _mark(source: Path, scope: PricingScope, results: Sequence[OrderResult]) -> Refusal | None:
    """Znacznik efenix w ``ADRES`` każdego gotowego zlecenia z ``results``."""

    ready = [result.order.row for result in results if isinstance(result.outcome, Ready)]
    return mark_ready(source, scope.content, scope.address_column, ready)


def _warning(source: Path, result: OrderResult) -> Message | None:
    match result.outcome:
        case Ready():
            return None
        case OrderError(problem):
            return messages.order_error(source, result.order.row, problem)
        case EmmettWarning(conflicts):
            return messages.emmett_conflict(source, result.order.row, conflicts)


@contextmanager
def _efenix_stops(changed: Callable[[], bool]) -> Iterator[None]:
    """Strona logowania, nieznana budowa strony, zamknięte okno i brak połączenia z efenix to Zatrzymanie z Komunikatem
    procesu.

    ``changed``: czy przed Zatrzymaniem proces zmienił już coś w efenix.
    """

    try:
        yield
    except LoggedOut as error:
        raise StopError(messages.logged_out(kept=changed())) from error
    except UnexpectedPage as error:
        raise StopError(messages.efenix_changed(error.part, kept=changed())) from error
    except WindowClosed as error:
        raise StopError(messages.window_closed(kept=changed())) from error
    except EfenixUnreachable as error:
        raise StopError(messages.efenix_unreachable(kept=changed())) from error
    except BrowserNotStarted as error:
        raise StopError(messages.browser_not_started()) from error


def _priced(order: CollectiveOrder, efenix: Efenix, trace: EmmettTrace) -> Ready | OrderError | EmmettWarning:
    searched = searched_number(order)
    if isinstance(searched, OrderProblem):
        return OrderError(searched)
    number, day = searched
    outcome = _outcome(order, number, day, efenix, trace)
    trace.finished(number)
    return outcome


def _outcome(order: CollectiveOrder, number: str, day: date, efenix: Efenix, trace: EmmettTrace) -> Ready | OrderError | EmmettWarning:
    file = file_quantities(order)
    if isinstance(file, (UnpairedColumns, NotWholeQuantities)):
        return OrderError(file)
    hit = listing(order, efenix.search(number))
    if isinstance(hit, OrderProblem):
        return OrderError(hit)
    opened = _known_positions(efenix.open_order(hit))
    if (problem := date_problem(order, opened.execution_date)) is not None:
        return OrderError(problem)
    emmett = trace.emmett(number)
    if opened.amount != 0:
        differs = priced_differently(file, opened.quantities, opened.amount, order.amount)
        if differs is None:
            return Ready(hit)
        if emmett is None or opened.execution_date is None or not as_left_after_emmett(file, emmett, opened.quantities):
            return OrderError(differs)
        return _after_emmett(order, hit, efenix, file, emmett, opened)
    if opened.execution_date is None:
        if not efenix.set_execution_date(day):
            return OrderError(DateRefused.OUT_OF_RANGE)
        if _known_positions(efenix.open_order(hit)).execution_date != day:
            return OrderError(DateRefused.NOT_SAVED)
    # Pusta Wycena Emmetta ze śladu zostawia kwotę 0, więc jej ponowne załadowanie niczego by nie zmieniło.
    if emmett is None or any(emmett.values()):
        opened = _known_positions(efenix.load_emmett())
        emmett = opened.quantities
        trace.loaded(number, emmett)
    return _after_emmett(order, hit, efenix, file, emmett, opened)


def _after_emmett(
    order: CollectiveOrder, hit: ListedOrder, efenix: Efenix, file: Mapping[str, int], emmett: Mapping[str, int], on_page: OrderPricing
) -> Ready | OrderError | EmmettWarning:
    """Wycena po Wycenie Emmetta ``emmett``: ostrzeżenie, gdy Emmett przeczy plikowi, a inaczej ilości pliku dopisane na
    stronie ``on_page``."""

    if conflicts := emmett_conflicts(file, emmett):
        return EmmettWarning(conflicts)
    return _entered(order, hit, efenix, file, on_page)


def _entered(
    order: CollectiveOrder, hit: ListedOrder, efenix: Efenix, file: Mapping[str, int], on_page: OrderPricing
) -> Ready | OrderError:
    """Ilości pliku wpisane w pozycjach pustych na stronie ``on_page`` i kwota końcowa porównana z ``Kwota`` (AU)."""

    amount = on_page.amount
    for position, quantity in to_enter(file, on_page.quantities).items():
        amount = efenix.enter_quantity(position, quantity)
    return Ready(hit) if same_amount(amount, order.amount) else OrderError(OtherAmount(amount, order.amount))


def _known_positions(pricing: OrderPricing) -> OrderPricing:
    """Strona zlecenia bez którejś pozycji z przypisania kolumn to efenix o innej budowie, niż zna narzędzie."""

    if missing_positions(pricing.quantities):
        raise UnexpectedPage(PagePart.ORDER)
    return pricing
