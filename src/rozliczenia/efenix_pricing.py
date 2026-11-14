"""Wycena w efenix: wycena każdego zlecenia z zakresu Pliku zbiorczego uzupełniona w efenix, w sesji, którą otworzył tata.

Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty na Komunikaty: Sprawdzanie (Plik zbiorczy jest, nie
trzyma go Excel i daje się otworzyć okno efenix z listą zleceń), Odczyt danych (zakres z ``efenix_orders``), Planowanie
(Zatrzymanie, gdy Plik zbiorczy nie ma kwot AU policzonych przez Excel) i Zapisywanie, w którym idzie przez zlecenia z
zakresu po kolei, a na końcu raz oznacza gotowe Znacznikiem efenix. Najpierw to, co widać bez efenix: numer, data i
ilości, które da się przepisać (``efenix_positions``). Potem zlecenie znajduje po ``Numer dokumentu`` równym
``NUMER ZL.`` i sprawdza je z listą efenix (``efenix_checks``). Pierwsza niezgodność to błąd zlecenia, w efenix nic się
nie zmienia i proces idzie dalej. Zlecenia rozliczonego (``Settled``) ani Zlecenia przekazanego (``Forwarded``) proces
nie otwiera, a Zlecenie przekazane dostaje w Pliku zbiorczym Znacznik przekazania w obu trybach. Każdy odczyt strony
zlecenia musi mieć pozycje, w których plik ma ilość (``missing_positions``).

Wycenę zlecenia proces dokańcza do Pliku zbiorczego tylko w górę (ADR 0026, ``completion``). Najpierw, z ilościami na
stronie albo bez, ustawia datę wykonania z ``DATA``, gdy jest pusta, i sprawdza ją na ponownie otwartej stronie (dzień,
którego kalendarz efenix nie przyjął albo którego efenix nie zapisał, to błąd zlecenia ``DateRefused`` bez Emmetta i bez
zmian ilości), żeby gotowe zlecenie nie zostało bez daty wykonania. Strona bez żadnej ilości nie ma wyceny: proces
ładuje do niej Wycenę Emmetta, a czy efenix ją załadował, rozstrzyga z obserwacji okna (``EmmettLoad``): strona po
przeładowaniu bez żadnej ilości to odmowa „Załaduj do zlecenia” i Zatrzymanie, chyba że Emmett nic nie zaproponował
(``_emmett``). Strona z ilościami ma już wycenę, zaczętą przez proces, przez tatę albo samą Wycenę Emmetta: proces nie
ładuje do niej Wyceny Emmetta, bo „Załaduj do zlecenia” czyści wycenę. Potem w obu przypadkach proces dokańcza wycenę
(``completion``): zlecenie z pozycją, w której strona ma więcej niż plik, to Ostrzeżenie Emmetta z pozycją i obiema
ilościami, choć resztę ilości proces i tak wpisał. Zlecenie bez takiej pozycji jest gotowe, gdy kwota końcowa, którą
odesłał efenix, jest równa ``Kwota`` (AU), a w przeciwnym razie to błąd z obiema kwotami. Ponowne uruchomienie dokańcza
więc każde zlecenie, które przerwało Zatrzymanie albo zgaśnięcie Centrum, tak samo jak zlecenie zaczęte przez tatę.

Tryb Wyceny (``PricingMode``, domyślnie ``FILL``) rozstrzyga, co dzieje się z gotowym zleceniem. W trybie bez
Przekazania (``FILL``) dostaje Znacznik efenix, a Przekazanie do akceptacji zostaje tacie. W trybie z Przekazaniem
(``FORWARD``) proces przekazuje je do akceptacji (``Efenix.forward_to_accept``) i szuka go ponownie: lista ze statusem
„Do akceptacji” (``listing``) daje Zlecenie przekazane, a każda inna lista błąd ``OrderProblem.NOT_FORWARDED`` bez
Znacznika. Odmowa efenix przy Przekazaniu (``ForwardRefusal``) to błąd zlecenia bez Znacznika i bez ponownego szukania,
a proces idzie do następnego zlecenia. Błędu ani Ostrzeżenia Emmetta proces nie przekazuje w żadnym trybie. Strona
logowania, efenix, którego okno nie otworzyło, zamknięte okno efenix i działanie okna, którego okno nie dokończyło, to
Zatrzymanie (``LoggedOut``, ``EfenixUnreachable``, ``WindowClosed``, ``UnexpectedPage``), a Komunikat Zatrzymania mówi,
czy przed nim proces zmienił już coś w efenix: rozstrzyga to Wycena ze śladu zleceń i z działania, przy którym okno
stanęło (``_kept``), a nie okno. Zatrzymanie z okna niesie w ``StopError.facts`` fakty dla Logów Uruchomienia
(``PricingStopped``).
Okno, które czeka, aż tata się zaloguje, robi to w ``Login`` od silnika, który na ten czas wstrzymuje zegar
Uruchomienia: czas logowania nie wlicza się do czasów etapów ani do ``Czas uruchomienia``. Postęp Zapisywania to kroki (``PhaseRunner.step``):
logowanie, zlecenia z Wykonawcą i liczbą sprawdzonych z wszystkich, na końcu Znaczniki efenix; ślad działań okna przy
każdym zleceniu (``efenix_trace``) trafia do jego wyniku, a stamtąd do Logów Uruchomienia. Dziennik Wyceny w efenix
(``OrderJournal``, w Centrum ``centrum.logs_disk.Journal``) dostaje wpis o każdym zleceniu przed pierwszym działaniem okna przy
nim, więc przed każdym zapisem w efenix, i wpis z wynikiem zaraz po nim, zanim proces przejdzie do następnego zlecenia.

Po ostatnim zleceniu, a także przy Zatrzymaniu w trakcie, ``efenix_marking`` raz zapisuje Plik zbiorczy: komórka
``ADRES`` każdego gotowego zlecenia dostaje Znacznik efenix, a każdego Zlecenia przekazanego Znacznik przekazania. Gdy
zapis się nie udaje (Excel trzyma plik, plik zmienił się od odczytu, zapis nieudany), przebieg kończy się Zatrzymaniem z
prośbą o ponowne uruchomienie, a wycena w efenix zostaje; przy Zatrzymaniu z efenix zostaje jego Komunikat, bo ponowne
uruchomienie i tak jest potrzebne. Ponowne uruchomienie dokańcza oznaczanie: gotowe zlecenia mają już wycenę zgodną z
plikiem, więc proces je tylko czyta. Wynik nie zawiera numerów zleceń, adresów ani loginów, tylko numery wierszy Pliku
zbiorczego.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from . import efenix_messages as messages
from . import efenix_trace, workbook_files
from .client_data import ForbiddenColumn, ForbiddenValues
from .domain import ProgressPhase
from .efenix_checks import DateRefused, Forwarded, OrderProblem, Settled, date_problem, listing, searched_number
from .efenix_mark import Mark
from .efenix_marking import Refusal, mark_orders
from .efenix_orders import (
    AmountsNotComputed,
    CollectiveOrder,
    MissingColumns,
    PricingScope,
    read_scope,
)
from .efenix_pace import Pace, Pacing
from .efenix_positions import (
    Excess,
    FileQuantities,
    NotWholeQuantities,
    OrderFault,
    OtherAmount,
    PageRead,
    UnpairedColumns,
    completion,
    file_quantities,
    missing_positions,
    same_amount,
)
from .efenix_trace import OrderTrace, TraceStep
from .efenix_window import (
    BrowserNotStarted,
    Efenix,
    EfenixUnreachable,
    EmmettLoad,
    ListedOrder,
    LoggedOut,
    OpenEfenix,
    OrderPricing,
    OtherShape,
    PagePart,
    Proposal,
    Shape,
    UnexpectedPage,
    WindowCause,
    WindowClosed,
    WindowStop,
)
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .workbook_files import WorkbookError
from .period_folder import collective_period_token
from .run_context import RunContext

__all__ = [
    "NO_JOURNAL",
    "EfenixInputs",
    "EmmettWarning",
    "OrderError",
    "OrderJournal",
    "OrderKind",
    "OrderResult",
    "PricingMode",
    "PricingStopped",
    "PricingSummary",
    "Ready",
    "StoppedOrder",
    "price_orders",
]


class PricingMode(enum.Enum):
    """Tryb Wyceny w efenix, który wybiera tata: co dzieje się z gotowym zleceniem."""

    FILL = "bez Przekazania"
    """Uzupełnia wycenę i oznacza gotowe zlecenie Znacznikiem efenix; Przekazanie do akceptacji zostaje tacie."""
    FORWARD = "z Przekazaniem"
    """Uzupełnia wycenę i gotowe zlecenie przekazuje do akceptacji (zielony „Zapisz”)."""


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
    """Ostrzeżenie Emmetta: efenix ma w pozycjach ``excess`` więcej niż Plik zbiorczy, więc proces ich nie zmienił, a
    pozostałe ilości pliku wpisał."""

    excess: tuple[Excess, ...]


Outcome = Ready | Settled | Forwarded | OrderError | EmmettWarning
"""Wynik zlecenia w Wycenie w efenix."""


class OrderKind(enum.Enum):
    """Wynik zlecenia dla taty; wartość to stały klucz wyniku w Logach Uruchomienia, a kolejność członków to kolejność
    wyników na karcie Uruchomienia."""

    READY = "gotowe"
    FORWARDED = "przekazane"
    SETTLED = "rozliczone"
    ERROR = "błąd"
    WARNING = "ostrzeżenie Emmetta"

    @property
    def left_for_tata(self) -> bool:
        """Zlecenie zostało tacie z Komunikatem: błąd zlecenia albo Ostrzeżenie Emmetta."""

        return self in (OrderKind.ERROR, OrderKind.WARNING)


@dataclass(frozen=True)
class OrderResult:
    """Wynik zlecenia; ``steps``: ślad działań okna efenix przy nim, po kolei (``efenix_trace``), ``message``: Komunikat
    zlecenia, które zostało tacie (``OrderKind.left_for_tata``; ``None`` przy każdym innym), a ``file``: ilości Pliku
    zbiorczego po kodach pozycji (``None``, gdy nie dało się ich przepisać)."""

    order: CollectiveOrder
    outcome: Outcome
    steps: tuple[TraceStep, ...]
    message: Message | None
    file: Mapping[str, int] | None

    def __post_init__(self) -> None:
        if (self.message is not None) != self.kind.left_for_tata:
            raise ValueError(f"wynik {self.kind.value} z Komunikatem: {self.message is not None}")

    @property
    def kind(self) -> OrderKind:
        match self.outcome:
            case Ready():
                return OrderKind.READY
            case Forwarded():
                return OrderKind.FORWARDED
            case Settled():
                return OrderKind.SETTLED
            case OrderError():
                return OrderKind.ERROR
            case EmmettWarning():
                return OrderKind.WARNING


@dataclass
class PricingSummary:
    """Podsumowanie Wyceny w efenix: wynik każdego zlecenia z zakresu po kolei i liczby pominiętych Wierszy danych."""

    results: tuple[OrderResult, ...]
    with_photos: int
    defects: int
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def warnings(self) -> list[Message]:
        """Komunikat każdego zlecenia, które zostało tacie, po kolei, z numerem wiersza Pliku zbiorczego."""

        return [result.message for result in self.results if result.message is not None]

    def count(self, kind: OrderKind) -> int:
        return sum(result.kind is kind for result in self.results)

    @property
    def not_found(self) -> int:
        """Błędy zleceń, których efenix nie zna po numerze z ``NUMER ZL.``."""

        return sum(
            isinstance(result.outcome, OrderError) and result.outcome.problem is OrderProblem.UNKNOWN_NUMBER
            for result in self.results
        )


@dataclass(frozen=True)
class StoppedOrder:
    """Zlecenie, przy którym okno efenix stanęło: wiersz Pliku zbiorczego, miejsce w przebiegu (``place`` z ``total``, od
    1), udane działania okna przy nim po kolei i działanie, które się nie udało (``failed``, z samym rodzajem i czasem;
    ``None``, gdy ślad zlecenia nie ma nieudanego działania).
    """

    row: int
    place: int
    total: int
    steps: tuple[TraceStep, ...]
    failed: TraceStep | None


@dataclass(frozen=True)
class PricingStopped:
    """Fakty Zatrzymania okna efenix dla Logów Uruchomienia (``StopError.facts``): część strony (``None`` poza stronami efenix), przyczyna techniczna, wynik każdego zlecenia sprzed
    Zatrzymania (``summary``, z Komunikatami jak po przebiegu) i zlecenie, przy którym Wycena stanęła (``None``: przed
    pierwszym zleceniem, przy otwieraniu okna albo logowaniu)."""

    part: PagePart | None
    cause: WindowCause
    summary: PricingSummary
    stopped_at: StoppedOrder | None


class OrderJournal(Protocol):
    """Dziennik Wyceny w efenix w trakcie przebiegu: proces woła go na wątku przebiegu, zlecenie po zleceniu.

    Wpis nie może zatrzymać przebiegu: dziennik, który nie zapisał wpisu, sam to zgłasza i wraca.
    """

    def begun(self, row: int, place: int, total: int) -> None:
        """Zaczynam zlecenie z wiersza ``row`` Pliku zbiorczego, ``place`` z ``total`` w przebiegu (od 1), przed pierwszym
        działaniem okna efenix przy nim."""
        ...

    def ended(self, result: OrderResult) -> None:
        """Zlecenie skończone z wynikiem ``result``."""
        ...


class _NoJournal:
    """Przebieg bez dziennika (Skrypt dla maszyn, testy silnika)."""

    def begun(self, row: int, place: int, total: int) -> None:
        return None

    def ended(self, result: OrderResult) -> None:
        return None


NO_JOURNAL: Final[OrderJournal] = _NoJournal()


@dataclass(frozen=True)
class EfenixInputs:
    """Wejście procesu Wyceny w efenix: Plik zbiorczy okresu i okno efenix w sesji taty.

    Okres wynika z nazwy Pliku zbiorczego (``nieznany``, gdy się nie da). Wycena w efenix nie ma podglądu bez zapisu.
    ``pace``: tempo ludzkie okna; ``None`` wyłącza przerwy. ``journal``: dziennik Wyceny w efenix w trakcie przebiegu;
    Centrum podaje swój (``centrum.logs_disk.Journal``), a Skrypt dla maszyn przebiega bez niego. ``mode``: tryb Wyceny,
    domyślnie bez Przekazania do akceptacji.
    """

    source: Path
    open_efenix: OpenEfenix
    pace: Pace | None
    journal: OrderJournal = field(default=NO_JOURNAL, compare=False)
    mode: PricingMode = PricingMode.FILL

    @property
    def period(self) -> str:
        return collective_period_token(self.source)


# Kroki Zapisywania na karcie Uruchomienia.
_LOGIN: Final = "Zaloguj się w oknie efenix"
_ORDERS: Final = "Zlecenia"
_MARKING: Final = "Znaczniki efenix w Pliku zbiorczym"


def price_orders(inputs: EfenixInputs, context: RunContext) -> PricingSummary:
    """Uzupełnia w efenix wycenę każdego zlecenia z zakresu Pliku zbiorczego ``inputs.source`` i oznacza w nim gotowe
    zlecenia.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie. Zegar Uruchomienia ``context.clock`` liczy czasy etapów i
    śladu zleceń i stoi na czas czekania na logowanie taty. Plik zbiorczy czyta uchwyt plików taty ``context.files``:
    komórki zakazanych kolumn Pliku zbiorczego i dane adresowe z listy wyników efenix zna pamięć reguły danych (ADR
    0025), a odczyt Pliku zbiorczego Kopia wejścia Uruchomienia (#841).
    """

    phases = PhaseRunner(context.observer, clock=context.clock.now)
    source = inputs.source.expanduser().resolve()
    open_efenix, pace, journal, mode = inputs.open_efenix, inputs.pace, inputs.journal, inputs.mode
    files, clock = context.files, context.clock.now
    forbidden = files.forbidden

    def check() -> None:
        try:
            workbook_files.ensure_available(source)
        except WorkbookError as error:
            raise StopError(messages.source_unusable(error)) from error

    phases.check(check)

    def read() -> PricingScope | AmountsNotComputed | MissingColumns:
        try:
            return read_scope(source, files)
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
        with context.clock.hold():
            phases.step(_LOGIN)
            yield

    def save() -> tuple[OrderResult, ...]:
        results: list[OrderResult] = []
        pacing = None if pace is None else Pacing(pace)
        total = len(scope.orders)
        current: tuple[int, CollectiveOrder, OrderTrace] | None = None

        def stopped(part: PagePart | None, cause: WindowCause) -> PricingStopped:
            before = tuple(results)
            summary = PricingSummary(before, scope.with_photos, scope.defects)
            at = (
                None
                if current is None
                else StoppedOrder(current[1].row, current[0] + 1, total, tuple(current[2].steps), current[2].failed)
            )
            return PricingStopped(part, cause, summary, at)

        try:
            with _efenix_stops(lambda _error: False, stopped), open_efenix(login) as efenix:
                with _efenix_stops(lambda error: _kept(results, None if current is None else current[2], error), stopped):
                    for done, order in enumerate(scope.orders):
                        phases.step(_ORDERS, worker=order.worker, done=done, total=total)
                        trace = OrderTrace()
                        current = (done, order, trace)
                        journal.begun(order.row, done + 1, total)
                        window = efenix_trace.traced(efenix, order, trace, clock)
                        file = file_quantities(order)
                        outcome = _outcome(order, file, window if pacing is None else pacing.window(window), forbidden, mode)
                        result = _result(source, order, outcome, tuple(trace.steps), file)
                        results.append(result)
                        journal.ended(result)
                        current = None
        except StopError:
            phases.step(_MARKING)
            _mark(source, scope, results)
            raise
        phases.step(_MARKING)
        if (refusal := _mark(source, scope, results)) is not None:
            raise StopError(messages.marks_not_saved(source, refusal))
        return tuple(results)

    results = phases.save(save)
    return PricingSummary(results, scope.with_photos, scope.defects, phases.durations_ms())


def _mark(source: Path, scope: PricingScope, results: Sequence[OrderResult]) -> Refusal | None:
    marks: dict[int, Mark] = {}
    for result in results:
        match result.outcome:
            case Ready():
                marks[result.order.row] = Mark.READY
            case Forwarded():
                marks[result.order.row] = Mark.FORWARDED
            case Settled() | OrderError() | EmmettWarning():
                pass
    return mark_orders(source, scope.content, scope.address_column, marks)


def _result(
    source: Path, order: CollectiveOrder, outcome: Outcome, steps: tuple[TraceStep, ...], file: FileQuantities
) -> OrderResult:
    message: Message | None
    match outcome:
        case Ready() | Settled() | Forwarded():
            message = None
        case OrderError(problem):
            message = messages.order_error(source, order.row, problem, changed=any(step.sent for step in steps))
        case EmmettWarning(excess):
            message = messages.emmett_warning(source, order.row, excess)
    return OrderResult(order, outcome, steps, message, file if isinstance(file, Mapping) else None)


@contextmanager
def _efenix_stops(
    changed: Callable[[WindowStop], bool], stopped: Callable[[PagePart | None, WindowCause], PricingStopped]
) -> Iterator[None]:
    """Wyjątek okna to Zatrzymanie z Komunikatem procesu, a fakty Zatrzymania dla Logów Uruchomienia daje ``stopped``.

    ``changed``: czy przed Zatrzymaniem z wyjątku okna proces zmienił już coś w efenix.
    """

    try:
        yield
    except LoggedOut as error:
        raise StopError(messages.logged_out(kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except UnexpectedPage as error:
        raise StopError(messages.window_stopped(error.part, kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except WindowClosed as error:
        raise StopError(messages.window_closed(kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except EfenixUnreachable as error:
        raise StopError(messages.efenix_unreachable(kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except BrowserNotStarted as error:
        raise StopError(messages.browser_not_started(), facts=stopped(error.part, error.cause)) from error


def _kept(results: Sequence[OrderResult], current: OrderTrace | None, error: WindowStop) -> bool:
    """Czy przed Zatrzymaniem z wyjątku okna ``error`` proces mógł coś zmienić w efenix: udany zapis w śladzie zleceń
    ``results`` albo zlecenia ``current``, przy którym okno stanęło, albo działanie, które przed wyjątkiem kliknęło już
    przycisk zmiany zlecenia (``WindowStop.sent``)."""

    done = [step for result in results for step in result.steps]
    if current is not None:
        done.extend(current.steps)
    return error.sent or any(step.sent for step in done)


def _outcome(
    order: CollectiveOrder, file: FileQuantities, efenix: Efenix, forbidden: ForbiddenValues | None, mode: PricingMode
) -> Outcome:
    outcome = _priced_outcome(order, file, efenix, forbidden)
    if mode is PricingMode.FORWARD and isinstance(outcome, Ready):
        return _forwarded(order, outcome.listed, efenix, forbidden)
    return outcome


def _forwarded(order: CollectiveOrder, ready: ListedOrder, efenix: Efenix, forbidden: ForbiddenValues | None) -> Forwarded | OrderError:
    """Gotowe zlecenie ``order`` (wiersz listy ``ready``) przekazane do akceptacji i potwierdzone ponownym szukaniem:
    lista ze statusem „Do akceptacji” i realizatorem i adresem z pliku (``listing``); każda inna to ``NOT_FORWARDED``, a
    odmowa efenix przy Przekazaniu błąd z jej przyczyną."""

    if (refusal := efenix.forward_to_accept()) is not None:
        return OrderError(refusal)
    confirmed = listing(order, _searched(efenix, ready.number, forbidden))
    return confirmed if isinstance(confirmed, Forwarded) else OrderError(OrderProblem.NOT_FORWARDED)


def _searched(efenix: Efenix, number: str, forbidden: ForbiddenValues | None) -> Sequence[ListedOrder]:
    """Wiersze listy po szukaniu ``number``; ich dane adresowe poznaje reguła danych ``forbidden`` (``None``: praca bez
    wysyłki)."""

    found = efenix.search(number)
    if forbidden is not None:
        for listed in found:
            forbidden.remember_value(ForbiddenColumn.ADDRESS, listed.address)
    return found


def _priced_outcome(
    order: CollectiveOrder, file: FileQuantities, efenix: Efenix, forbidden: ForbiddenValues | None
) -> Outcome:
    searched = searched_number(order)
    if isinstance(searched, OrderProblem):
        return OrderError(searched)
    number, day = searched
    if isinstance(file, (UnpairedColumns, NotWholeQuantities)):
        return OrderError(file)
    hit = listing(order, _searched(efenix, number, forbidden))
    if isinstance(hit, OrderProblem):
        return OrderError(hit)
    if isinstance(hit, Settled | Forwarded):
        return hit
    opened = efenix.open_order(hit)
    if (missing := missing_positions(file, opened.quantities, PageRead.OPENED)) is not None:
        return OrderError(missing)
    if (problem := date_problem(order, opened.execution_date)) is not None:
        return OrderError(problem)
    if opened.execution_date is None:
        dated = _dated(hit, efenix, file, day)
        if isinstance(dated, OrderError):
            return dated
        opened = dated
    if not _priced(opened):
        opened = efenix.load_emmett(_emmett)
        if (missing := missing_positions(file, opened.quantities, PageRead.AFTER_EMMETT)) is not None:
            return OrderError(missing)
    return _completed(order, hit, efenix, file, opened)


def _priced(page: OrderPricing) -> bool:
    """Strona zlecenia ma wycenę: co najmniej jedną ilość (ADR 0026). Proces ładuje Wycenę Emmetta tylko do strony bez
    wyceny, a strona po niej ma wycenę, gdy efenix ją załadował. Kwocie końcowej proces tu nie wierzy, bo karta ceny
    wpisywanej (pole ``.wycena-cena`` bez pola Ilość) daje kwotę różną od 0 także stronie bez ilości, a pozycja w cenie 0
    daje kwotę 0 stronie z ilością."""

    return any(page.quantities.values())


def _emmett(load: EmmettLoad) -> OrderPricing:
    """Strona zlecenia z Wyceną Emmetta, którą efenix załadował: strona po przeładowaniu ma wycenę (``_priced``) albo
    Emmett nic nie zaproponował (``Proposal.NOTHING``), bo proces ładuje Wycenę Emmetta tylko do strony bez wyceny.

    Strona bez ilości po każdej innej propozycji, także po pustym oknie Emmetta po padniętej propozycji, to
    ``UnexpectedPage`` z ``Shape.EMMETT_NOT_LOADED``: efenix odmówił „Załaduj do zlecenia” odpowiedzią 2xx (#877, #889), a
    skrypt efenix i tak przeładował stronę. Postaci propozycji ani treści tej odpowiedzi nikt nie zmierzył, więc werdykt ich
    nie czyta. Prawdziwy efenix dał stronę z ilością i kwotą różną od 0 po każdym ze 108 załadowań przebiegu z 4.11.2026
    (Logi Uruchomienia Wydania 0.4.2), więc Zatrzymanie przy pustej propozycji, którą efenix pokazałby czymś, zdarza się
    najwyżej rzadko.

    Emmett, który zaproponowałby same pozycje bez pola Ilość (karta ceny wpisywanej), dałby stronę bez ilości i
    Zatrzymanie, choć efenix go załadował. Takiej propozycji nikt nie zmierzył, a Zatrzymanie jest tu stroną bezpieczną, bo
    po nim proces nie wpisuje ilości z pliku. Każde następne Uruchomienie znowu otworzy jednak tę samą stronę bez ilości,
    znowu załaduje Emmetta i znowu zatrzyma się na tym zleceniu, dopóki tata sam nie wpisze ilości.
    """

    if load.proposal is not Proposal.NOTHING and not _priced(load.page):
        raise WindowStop.of(PagePart.EMMETT, OtherShape(Shape.EMMETT_NOT_LOADED))
    return load.page


def _dated(hit: ListedOrder, efenix: Efenix, file: Mapping[str, int], day: date) -> OrderPricing | OrderError:
    """Strona zlecenia ``hit`` z pustą datą wykonania po ustawieniu ``day``, otwarta ponownie, z ilościami albo bez.

    Dzień, którego kalendarz efenix nie przyjął albo którego efenix nie zapisał, to błąd ``DateRefused``, a ponownie
    otwarta strona bez pozycji z ilością w pliku to błąd ``missing_positions``; ilości proces wtedy nie zmienia."""

    if not efenix.set_execution_date(day):
        return OrderError(DateRefused.OUT_OF_RANGE)
    reopened = efenix.open_order(hit)
    if (missing := missing_positions(file, reopened.quantities, PageRead.AFTER_DATE)) is not None:
        return OrderError(missing)
    if reopened.execution_date != day:
        return OrderError(DateRefused.NOT_SAVED)
    return reopened


def _completed(
    order: CollectiveOrder, hit: ListedOrder, efenix: Efenix, file: Mapping[str, int], on_page: OrderPricing
) -> Ready | OrderError | EmmettWarning:
    plan = completion(file, on_page.quantities)
    amount = on_page.amount
    for position, quantity in plan.to_enter.items():
        amount = efenix.enter_quantity(position, quantity)
    if plan.excess:
        return EmmettWarning(plan.excess)
    return Ready(hit) if same_amount(amount, order.amount) else OrderError(OtherAmount(amount, order.amount))
