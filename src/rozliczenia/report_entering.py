"""Wpisanie raportów dla Uruchomienia procesu: tak/nie i czynności z Raportów wykonawców do INTERMAX (ADR 0028).

Operacją procesu jest ``enter_from_mail()``. Silnik sekwencjonuje kroki i jako jedyny tłumaczy ich fakty na
Komunikaty, a reguły zna rdzeń raportów (``worker_reports.enter_reports``):

- Sprawdzanie: plik dostępu do Skrzynki raportów, pamięć własnych
  wpisów (``ReportState.load``), brak kopii konfliktu OneDrive obok INTERMAX (``onedrive_conflicts.beside``) i INTERMAX
  zamknięty w Excelu, więc przy kopii konfliktu albo INTERMAX otwartym w Excelu skrzynka nie jest czytana;
- Odczyt danych: Pliki zbiorcze okresów okna (``scan_period_folders``), bo okres z Plikiem zbiorczym jest zamknięty, potem
  maile ze Skrzynki raportów od pierwszego dnia otwartego, a dopiero potem INTERMAX (``register_file.read``) i w każdym obszarze
  wklejania uporządkowane wiersze z dni od ``Window.start`` (tydzień przed pierwszym dniem otwartym, nie przed dniem
  wdrożenia: ``raw_orders.ordered_rows``, w Kopii wejścia przez ``PasteArea.copy_rows``; z ``ADRES`` rdzeń dostaje
  tylko to, czy ma wartość), numer zlecenia z każdego przeczytanego wiersza z dni od ``Window.numbers_since`` (tydzień
  przed pierwszym dniem otwartym, także przed dniem wdrożenia: ``raw_orders.numbered_rows``, także Surowe zlecenia z
  dołu arkusza i wiersze, z których nie powstało zlecenie), którego rdzeń nigdy nie dopisuje, oraz Dni
  uporządkowane (``raw_orders.ordered_days``). Zapis INTERMAX przez tatę albo jego pracownika między odczytem INTERMAX a podmianą
  przepada (``intermax_replace`` porównuje bajty z dyskiem dopiero po odmowie podmiany), więc odczyt przez sieć nie
  stoi w tym oknie;
- Planowanie: rdzeń raportów, z pamięcią z pliku sprzed wersji 4 zamienioną przy odczytanych zleceniach
  (``OlderOwnEntries.upgraded``), bo rdzeń przyjmuje tylko ``OwnEntries``;
- Zapisywanie: komórki, Przeniesienia zleceń i Zlecenia dopisane z raportu bez Kopii INTERMAX
  (``intermax_cells.write_cells``), a po udanym zapisie
  pamięć własnych wpisów
  z dniem wdrożenia, także przy zerze wpisanych komórek; kopia konfliktu OneDrive, która pojawiła się obok INTERMAX do
  końca zapisu, zatrzymuje kliknięcie już po zapisie pamięci i wyniku dla widoku Raporty, z podsumowaniem w faktach
  Zatrzymania. Wynik dla widoku Raporty (``ClickResult``) proces zapisuje tylko po udanym zapisie INTERMAX, bo jego
  liczby zakładają wpisane komórki.

Decyzje taty „Zostaw moją” proces bierze w Sprawdzaniu jako migawkę (``SavedState.kept``), razem z pamięcią: decyzja
kliknięta w trakcie Uruchomienia działa od następnego kliknięcia, a widok Raporty pokazuje ją od razu.

Okno dni zaczyna się od dnia wdrożenia z pamięci (przed pierwszym udanym kliknięciem: dziś) i nie ma dni okresów z
Plikiem zbiorczym w folderze okresów; bez folderu okresów albo bez dostępu do niego skrzynka nie jest czytana. Proces nie należy do
okresu: Uruchomienie ma okres dzisiejszej daty z zegara procesu (ADR 0019). Zatrzymanie po rdzeniu niesie fakty
(``EnteringFacts``), a Zatrzymanie po zapisie całe podsumowanie (``EnteringSummary``), więc Logi mają zmiany i problemy
także wtedy. Plik dostępu, który zniknie albo zepsuje się między
Sprawdzaniem a odczytem skrzynki, daje to samo Zatrzymanie co w Sprawdzaniu. Adres, temat ani treść maila nie
wychodzą z rdzenia do faktów: ``MailRead`` ich nie ma, a adres nieznanego nadawcy ma tylko problem w pamięci.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, assert_never

from . import intermax_messages, onedrive_conflicts, raw_orders, register_file, workbook_files
from . import report_entering_messages as messages
from .domain import ProgressPhase
from .intermax_cells import CellsWritten, Rejected, write_cells
from .intermax_ordering import paste_areas
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Waiting
from .message import Message, StopError
from .period_folder import PeriodFolder, PeriodFolderInaccessible, scan_period_folders
from .phase_runner import PhaseRunner
from .register_columns import ADDRESS, COMPLETED, DATE, ORDER_NUMBER, SUCCESSFUL, WORKER
from .register_file import OrderSheets, RegisterFile
from .report_cells import CellChange, OrderAdded, OrderMove, OrderRow
from .run_context import RunContext
from .settlement_period import SettlementPeriod, period_of
from .workbook_files import WorkbookError
from .workbook_parts import UnsupportedShape
from .worker_report_inbox import InboxUnreachable, Mails, PasswordRejected, WorkerReportInbox
from .worker_reports import (
    Kept,
    MailRead,
    OlderOwnEntries,
    OrderKey,
    OrderNumber,
    OrderedDay,
    OwnEntries,
    OwnEntry,
    OwnMove,
    ReadNumber,
    ReadReport,
    RegisterOrder,
    ReportInputs,
    ReportMail,
    ReportNote,
    ReportProblem,
    Window,
    WorkerAddresses,
    WorkerDay,
    enter_reports,
    order_number,
)
from .wall_clock import local_now
from .worker_list import WorkerList

__all__ = [
    "ClickResult",
    "DecisionsUnreadable",
    "EnteringFacts",
    "EnteringInputs",
    "EnteringSummary",
    "Orderless",
    "ReportEnteringParts",
    "ReportState",
    "ReportStateInMemory",
    "SavedState",
    "StateUnreadable",
    "enter_from_mail",
]

@dataclass(frozen=True)
class SavedState:
    """Pamięć z ostatniego udanego zapisu: dzień wdrożenia (``None``: jeszcze żadnego udanego kliknięcia) i własne
    wpisy (``OlderOwnEntries`` z pliku sprzed wersji 4), a do tego decyzje taty „Zostaw moją” (``kept``)."""

    rollout: date | None
    memory: OwnEntries | OlderOwnEntries
    kept: frozenset[Kept] = frozenset()


@dataclass(frozen=True)
class ClickResult:
    """Wynik kliknięcia dla widoku Raporty: chwila kliknięcia, dni otwarte okna od pierwszego do dziś, liczby i
    zlecenia Wykonawców z dni, problemy rdzenia raportów, z adresem nieznanego nadawcy (ADR 0028), i informacje o
    Przeniesieniach zleceń (ADR 0029)."""

    clicked_at: datetime
    days: tuple[date, ...]
    workers: tuple[WorkerDay, ...]
    problems: tuple[ReportProblem, ...]
    notes: tuple[ReportNote, ...] = ()


class StateUnreadable(Exception):
    """Pamięci własnych wpisów nie da się odczytać: zły JSON albo nieznana wersja. Pusta pamięć cofnęłaby dzień wdrożenia
    i zrobiłaby z własnych wpisów ręczne, więc to Zatrzymanie."""


class DecisionsUnreadable(Exception):
    """Decyzji taty „Zostaw moją” nie da się odczytać, choć pamięć własnych wpisów jest poprawna. Bez decyzji różnice,
    które tata zostawił, wróciłyby, więc to Zatrzymanie, z Komunikatem o tym pliku, a nie o pamięci."""


class ReportState(Protocol):
    def load(self) -> SavedState:
        """Pamięć z ostatniego udanego zapisu; ``StateUnreadable``, gdy jej nie da się odczytać, a
        ``DecisionsUnreadable``, gdy pamięć jest poprawna, ale decyzji „Zostaw moją” nie da się odczytać."""
        ...

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        """Zapisuje dzień wdrożenia i pamięć po udanym zapisie INTERMAX (``written`` to dowód zapisu); ``False``, gdy
        zapis na dysku się nie udał i czeka na następną próbę."""
        ...

    def save_result(self, written: CellsWritten, result: ClickResult) -> None:
        """Zapisuje wynik kliknięcia dla widoku Raporty po udanym zapisie INTERMAX (``written``); nieudany zapis czeka na
        następną próbę, a widok do tego czasu pokazuje go z pamięci."""
        ...


@dataclass
class ReportStateInMemory:
    """Pamięć bez pliku: Skrypt dla maszyn i testy. ``saved`` to stan, a ``save_memory`` go zastępuje z tymi samymi
    decyzjami; ``result`` to ostatni wynik dla widoku Raporty."""

    saved: SavedState = field(default_factory=lambda: SavedState(None, OwnEntries.EMPTY))
    result: ClickResult | None = None

    def load(self) -> SavedState:
        return self.saved

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        self.saved = SavedState(rollout, memory, self.saved.kept)
        return True

    def save_result(self, written: CellsWritten, result: ClickResult) -> None:
        self.result = result


@dataclass(frozen=True)
class ReportEnteringParts:
    """Zależności Wpisania raportów od gospodarza: Skrzynka raportów i pamięć własnych wpisów."""

    inbox: WorkerReportInbox
    state: ReportState


@dataclass(frozen=True)
class EnteringInputs:
    """Wejście Wpisania raportów: INTERMAX, folder okresów i Lista Wykonawców z Ustawień Centrum,
    zależności gospodarza i zegar procesu. ``period`` jak w ``OrderingInputs``: okres dzisiejszej daty przy starcie
    (ADR 0019)."""

    register_path: Path
    periods_directory: Path
    workers: WorkerList
    parts: ReportEnteringParts
    now: Callable[[], datetime] = local_now
    waiting: Waiting = field(default_factory=Waiting)
    disk: Disk = LOCAL_DISK
    period: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", period_of(self.now().date()).token)


@dataclass(frozen=True)
class Orderless:
    """Numer ``number`` z Wpisem w kliknięciu, który INTERMAX ma w przeczytanym wierszu arkusza ``sheet``, z którego
    rdzeń nie zrobił zlecenia: Surowe zlecenie, wiersz bez ``WYKONAWCA`` albo bez daty z godziną, wiersz z wyglądem z
    aplikacji między uporządkowanymi i nad nim albo zlecenie z dniem sprzed ``Window.start``, także obok zlecenia tego
    numeru. ``day``: dzień zlecenia, gdy każdy przeczytany wiersz numeru to zlecenie z dniem sprzed ``Window.start``
    (``AddBar.BEFORE_WINDOW``), a inaczej ``None``."""

    sheet: str
    number: OrderNumber
    day: date | None


@dataclass(frozen=True)
class EnteringFacts:
    """Fakty kliknięcia od rdzenia raportów, bez adresów, tematów i treści maili.

    ``rollout_before``: dzień wdrożenia z pamięci przed kliknięciem (``None``: pierwsze), ``rollout``: dzień wdrożenia
    tego kliknięcia, ``closed``: tokeny okresów okna z Plikiem zbiorczym, po kolei. ``memory_before``: zapamiętane własne
    wpisy numerów, które mają Wpis w tym kliknięciu, z każdego dnia, pod każdym Wykonawcą, bo wpisy idą za wierszem, tak
    jak je dostał rdzeń (z pliku sprzed wersji 4 po ``OlderOwnEntries.upgraded``), więc odtworzenie z Logów daje ten sam
    wynik, a
    ``kept``: decyzje „Zostaw moją” zleceń z Wpisem z migawki kliknięcia, ``moves_before``: pamięć zleceń (``OwnMove``)
    numerów, które mają Wpis w tym kliknięciu, z każdego dnia, bo zlecenie mogło przejść na inny dzień, a pamięć zostaje
    pod dniem, w którym zostawiło je Centrum. ``skipped``: maile, których Skrzynka raportów nie umiała przeczytać.
    ``moves``: Przeniesienia zleceń do zapisu, ``added``: Zlecenia dopisane z raportu do zapisu, ``notes``: informacje
    dla taty, ``orderless``: numery z Wpisem w tym kliknięciu, które INTERMAX ma w przeczytanym wierszu bez zlecenia
    (``Orderless``): odtworzenie z Logów stawia je w INTERMAX.
    """

    today: date
    rollout_before: date | None
    rollout: date
    closed: tuple[str, ...]
    memory_before: tuple[OwnEntry, ...]
    kept: tuple[Kept, ...]
    skipped: int
    mails: tuple[MailRead, ...]
    problems: tuple[ReportProblem, ...]
    changes: tuple[CellChange, ...]
    moves: tuple[OrderMove, ...] = ()
    notes: tuple[ReportNote, ...] = ()
    moves_before: tuple[OwnMove, ...] = ()
    added: tuple[OrderAdded, ...] = ()
    orderless: tuple[Orderless, ...] = ()


@dataclass
class EnteringSummary:
    """Podsumowanie Wpisania raportów: fakty kliknięcia i liczba wpisanych komórek (``written``)."""

    facts: EnteringFacts
    written: int
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def entered(self) -> int:
        """Zlecenia, do których kliknięcie coś wpisało, z Zleceniami dopisanymi z raportu: tyle Wpisów raportu tata już
        nie przepisuje."""

        return len({change.order for change in self.facts.changes}) + len(self.facts.added)

    @property
    def reports(self) -> int:
        """Raporty wykonawców od Wykonawców z listy adresów, które kliknięcie przeczytało."""

        return sum(isinstance(read, ReadReport) for read in self.facts.mails)


@contextmanager
def _stops(explain: Callable[[], Message], *errors: type[Exception], facts: EnteringFacts | None = None) -> Iterator[None]:
    try:
        yield
    except errors as error:
        raise StopError(explain(), facts=facts) from error


def enter_from_mail(inputs: EnteringInputs, context: RunContext) -> EnteringSummary:
    """Wpisuje Raporty wykonawców ze Skrzynki raportów do pustych ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` INTERMAX
    ``inputs.register_path``; zgłasza ``StopError``, gdy nie można działać bezpiecznie, a INTERMAX zostaje wtedy
    nietknięty. INTERMAX czyta uchwyt plików taty ``context.files``: zakazane kolumny przeczytanych wierszy zna pamięć
    reguły danych, a przeczytane uporządkowane wiersze i odcisk INTERMAX Kopia wejścia Uruchomienia."""

    phases = PhaseRunner(context.observer, clock=context.clock.now)
    register_path = inputs.register_path.expanduser().resolve()
    parts, files = inputs.parts, context.files

    def check() -> tuple[WorkerAddresses, SavedState]:
        _ensure_access(parts.inbox.access())
        addresses = inputs.workers.addresses()
        with (
            _stops(messages.state_unreadable, StateUnreadable),
            _stops(messages.decisions_unreadable, DecisionsUnreadable),
        ):
            saved = parts.state.load()
        if copies := onedrive_conflicts.beside(register_path):
            raise StopError(messages.conflict_copy(copies[0]))
        with _stops_unusable():
            workbook_files.ensure_available(register_path)
        return addresses, saved

    addresses, saved = phases.check(check)
    clicked_at = inputs.now()
    today = clicked_at.date()

    def read() -> tuple[
        Window,
        RegisterFile,
        tuple[RegisterOrder, ...],
        frozenset[OrderedDay],
        tuple[tuple[str, ReadNumber], ...],
        int,
        tuple[ReportMail, ...],
    ]:
        closed = closed_periods(inputs.periods_directory, Window.periods(today, saved.rollout))
        window = Window.of(today, saved.rollout, closed)
        outcome = parts.inbox.mails_since(window.first)
        match outcome:
            case PasswordRejected():
                raise StopError(messages.password_rejected())
            case InboxUnreachable(cause="missing"):
                raise StopError(messages.inbox_access_missing())
            case InboxUnreachable(cause="unreadable"):
                raise StopError(messages.inbox_access_unreadable())
            case InboxUnreachable():
                raise StopError(messages.inbox_unreachable())
            case Mails():
                pass
            case _:
                assert_never(outcome)
        with _stops_unusable():
            register = register_file.read(register_path, files)
        orders = register_orders(register, window.start, copy=files.copy is not None)
        ordered = _ordered_days(register, window.start)
        return window, register, orders, ordered, _present(register, window.numbers_since), outcome.skipped, outcome.mails

    window, register, orders, ordered_days, present, skipped, mails = phases.read(read)

    def plan() -> tuple[EnteringFacts, OwnEntries, tuple[WorkerDay, ...]]:
        remembered = saved.memory.upgraded(orders) if isinstance(saved.memory, OlderOwnEntries) else saved.memory
        found = enter_reports(
            ReportInputs(
                mails=mails,
                addresses=addresses,
                orders=orders,
                window=window,
                memory=remembered,
                kept=saved.kept,
                ordered_days=ordered_days,
                present=tuple(read for _, read in present),
            )
        )
        reported = {
            OrderKey(entry.number, read.day, read.worker)
            for read in found.mails
            if isinstance(read, ReadReport)
            for entry in read.entries
        }
        numbers = {key.number for key in reported}
        before = tuple(
            sorted(
                (entry for entry in remembered.entries if entry.key.number in numbers),
                key=lambda entry: (entry.key, entry.column.value),
            )
        )
        kept = tuple(sorted((decision for decision in saved.kept if decision.key in reported), key=_kept_order))
        moves_before = tuple(
            sorted(
                (move for move in remembered.moves if move.number in numbers),
                key=lambda move: (move.day, move.number),
            )
        )
        closed = tuple(period.token for period in Window.periods(today, saved.rollout) if period.token in window.closed)
        orderless = _orderless(present, orders, numbers, window.start)
        planned = EnteringFacts(
            window.today,
            saved.rollout,
            window.rollout,
            closed,
            before,
            kept,
            skipped,
            found.mails,
            found.problems,
            found.changes,
            found.moves,
            found.notes,
            moves_before,
            found.added,
            orderless,
        )
        return planned, found.memory, found.workers

    facts, memory, figures = phases.plan(plan, issue_count=lambda planned: len(planned[0].problems))

    def save() -> CellsWritten:
        with (
            _stops(lambda: messages.unsupported_shape(register_path, _sheet(facts)), UnsupportedShape, facts=facts),
            _stops_unusable(facts),
        ):
            written = write_cells(
                register, facts.changes, facts.moves, facts.added, waiting=inputs.waiting, disk=inputs.disk
            )
        match written:
            case Refusal():
                message = intermax_messages.refused(written, register_path, register_path.parent, intermax_messages.ENTERING)
                raise StopError(message, facts=facts)
            case Rejected():
                raise StopError(messages.cells_rejected(), facts=facts)
            case CellsWritten():
                return written
            case _:
                assert_never(written)

    written = phases.save(save)
    warnings = [] if parts.state.save_memory(written, window.rollout, memory) else [messages.memory_not_saved()]
    parts.state.save_result(written, ClickResult(clicked_at, _open_days(window), figures, facts.problems, facts.notes))
    summary = replace(EnteringSummary(facts, written.count, warnings), phase_durations_ms=phases.durations_ms())
    if copies := onedrive_conflicts.beside(register_path):
        raise StopError(messages.conflict_after_save(copies[0]), facts=summary)
    return summary


def _kept_order(kept: Kept) -> tuple[OrderKey, str, str]:
    return kept.key, kept.column.value, kept.reported


def _open_days(window: Window) -> tuple[date, ...]:
    """Dni otwarte okna od pierwszego do dziś: między nimi tata przełącza widok Raporty."""

    count = (window.today - window.first).days + 1
    return tuple(day for offset in range(count) if window.opens(day := window.first + timedelta(days=offset)))


def closed_periods(periods_directory: Path, periods: tuple[SettlementPeriod, ...]) -> tuple[str, ...]:
    """Tokeny okresów ``periods`` z Plikiem zbiorczym w ich Folderze okresu, po kolei.

    Folder okresu w kilku miesiącach (układ folderów taty) zamyka okres, gdy Plik zbiorczy jest w którymkolwiek z nich, bo
    Wpisanie raportów nigdy nie zmienia okresu z Plikiem zbiorczym. Okres bez Folderu okresu jest otwarty.
    """

    directory = periods_directory.expanduser().resolve()
    try:
        folders = scan_period_folders(directory)
        if folders.periods_directory_missing:
            raise StopError(messages.periods_directory_missing(directory))
        return tuple(
            period.token
            for period in periods
            if any(
                PeriodFolder(parent, period).observe().collective_file_exists
                for parent in folders.locations.get(period, ())
            )
        )
    except PeriodFolderInaccessible as error:
        raise StopError(messages.periods_folder_inaccessible(error.folder)) from error


def _ensure_access(access: str) -> None:
    match access:
        case "ready":
            return
        case "missing":
            raise StopError(messages.inbox_access_missing())
        case _:
            raise StopError(messages.inbox_access_unreadable())


@contextmanager
def _stops_unusable(facts: EnteringFacts | None = None) -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(intermax_messages.register_unusable(error, intermax_messages.ENTERING), facts=facts) from error


def _sheet(facts: EnteringFacts) -> str:
    """Arkusz pierwszej zmiany, pierwszego Przeniesienia albo pierwszego dopisania: tam zapis trafił na kształt, którego
    nie przenosi."""

    if facts.changes:
        return facts.changes[0].order.sheet
    if facts.moves:
        return facts.moves[0].order.sheet
    return facts.added[0].sheet if facts.added else ""


def _ordered_days(register: RegisterFile, since: date) -> frozenset[OrderedDay]:
    """Dni uporządkowane od ``since`` w każdym obszarze wklejania (``raw_orders.ordered_days``, ta sama reguła co karta
    Uporządkowania INTERMAX), każdy z arkuszem: tylko do nich rdzeń przenosi zlecenie z tego arkusza (ADR 0029)."""

    found: set[OrderedDay] = set()
    for area in paste_areas(register):
        with _stops(lambda: messages.unsupported_shape(register.path, area.sheet), UnsupportedShape):
            found |= {OrderedDay(area.sheet, day) for day in raw_orders.ordered_days(area.rows_from_bottom(), area.columns, since)}
    return frozenset(found)


def _present(register: RegisterFile, since: date) -> tuple[tuple[str, ReadNumber], ...]:
    """``NUMER ZL.`` każdego wiersza, który Wpisanie raportów czyta w każdym obszarze wklejania, z dniem od ``since``
    (``Window.numbers_since``) i do ``raw_orders._EARLIER_ROWS`` wierszy wcześniej (``raw_orders.numbered_rows``), z
    nazwą arkusza, raz na wiersz i numer: rdzeń nie dopisuje numeru, który INTERMAX już ma, także w wierszu, z którego
    nie powstało zlecenie, i nie przenosi zlecenia numeru z kilku wierszy. Numer z każdego położenia, w którym wiersz
    może stać (``RowPositions.known``, np. przesunięty pierwszy wiersz wklejenia ``raw_orders.SHIFT`` kolumn w lewo), z
    dniem zlecenia czytanym w tym samym położeniu (``RegisterOrder.of``)."""

    assert isinstance(register.order_sheets, OrderSheets), "paste_areas zatrzymuje Rejestr bez arkuszy zleceń"
    positions = {sheet.name: sheet.positions for sheet in register.order_sheets.sheets}
    found: list[tuple[str, ReadNumber]] = []
    for area in paste_areas(register):
        with _stops(lambda: messages.unsupported_shape(register.path, area.sheet), UnsupportedShape):
            rows = raw_orders.numbered_rows(area.rows_from_bottom(), area.columns, since)
        at = positions[area.sheet]
        for row, place in rows:
            read: dict[OrderNumber, date | None] = {}
            for shift in place.known:
                number = order_number(row.value(at[ORDER_NUMBER] - shift))
                if number is None:
                    continue
                order = RegisterOrder.of(
                    OrderRow(area.sheet, row.number),
                    number=number,
                    started=row.value(at[DATE] - shift),
                    worker=row.value(at[WORKER] - shift),
                    successful=None,
                    completed=None,
                    address=None,
                )
                read.setdefault(number, None if order is None else order.key.day)
            found += [(area.sheet, ReadNumber(number, day)) for number, day in read.items()]
    return tuple(found)


def _orderless(
    present: tuple[tuple[str, ReadNumber], ...],
    orders: tuple[RegisterOrder, ...],
    numbers: set[OrderNumber],
    start: date,
) -> tuple[Orderless, ...]:
    """Numery z Wpisem (``numbers``), które INTERMAX ma w więcej przeczytanych wierszach niż zleceń rdzenia, z
    arkuszem pierwszego takiego wiersza i dniem zlecenia, gdy każdy wiersz numeru to zlecenie sprzed ``start``: tyle
    odtworzenie z Logów potrzebuje, żeby rdzeń dał ten sam powód i tę samą regułę numeru z kilku wierszy."""

    ordered = Counter(order.key.number for order in orders)
    rows: dict[OrderNumber, list[tuple[str, date | None]]] = {}
    for sheet, read in present:
        rows.setdefault(read.number, []).append((sheet, read.order_day))
    found = []
    for number, places in rows.items():
        if number not in numbers or len(places) <= ordered[number]:
            continue
        days = [day for _, day in places]
        earlier = all(day is not None and day < start for day in days)
        found.append(Orderless(places[0][0], number, max(day for day in days if day is not None) if earlier else None))
    return tuple(sorted(found, key=lambda logged: (logged.sheet, logged.number)))


def register_orders(register: RegisterFile, since: date, *, copy: bool) -> tuple[RegisterOrder, ...]:
    """Uporządkowane zlecenia z dni od ``since`` w każdym obszarze wklejania, każdy przeczytany wiersz w Kopii wejścia
    (``copy``)."""

    areas = paste_areas(register)
    assert isinstance(register.order_sheets, OrderSheets), "paste_areas zatrzymuje Rejestr bez arkuszy zleceń"
    positions = {sheet.name: sheet.positions for sheet in register.order_sheets.sheets}
    orders: list[RegisterOrder] = []
    for area in areas:
        with _stops(lambda: messages.unsupported_shape(register.path, area.sheet), UnsupportedShape):
            rows = raw_orders.ordered_rows(area.rows_from_bottom(), area.columns, since)
        if copy:
            area.copy_rows(rows)
        at = positions[area.sheet]
        for row in rows:
            order = RegisterOrder.of(
                OrderRow(area.sheet, row.number),
                number=row.value(at[ORDER_NUMBER]),
                started=row.value(at[DATE]),
                worker=row.value(at[WORKER]),
                successful=row.value(at[SUCCESSFUL]),
                completed=row.value(at[COMPLETED]),
                address=row.value(at[ADDRESS]),
            )
            if order is not None:
                orders.append(order)
    return tuple(orders)
