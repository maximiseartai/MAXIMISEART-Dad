"""Wpisanie raportów dla Uruchomienia procesu: tak/nie i czynności z Raportów wykonawców do INTERMAX (ADR 0028).

Operacją procesu jest ``enter_from_mail()``. Silnik sekwencjonuje kroki i jako jedyny tłumaczy ich fakty na
Komunikaty, a reguły zna rdzeń raportów (``worker_reports.enter_reports``):

- Sprawdzanie: plik dostępu do Skrzynki raportów, Konfiguracja wykonawców, plik adresów Wykonawców, pamięć własnych
  wpisów (``ReportState.load``) i INTERMAX zamknięty w Excelu;
- Odczyt danych: INTERMAX (``register_file.read``), w każdym obszarze wklejania uporządkowane wiersze z dni od
  pierwszego dnia okna (``raw_orders.ordered_rows``, w Kopii wejścia przez ``PasteArea.copy_rows``), a dopiero potem
  maile ze Skrzynki raportów, więc przy INTERMAX otwartym w Excelu skrzynka nie jest czytana;
- Planowanie: rdzeń raportów;
- Zapisywanie: komórki bez Kopii INTERMAX (``intermax_cells.write_cells``), a po udanym zapisie pamięć własnych wpisów
  z dniem wdrożenia, także przy zerze wpisanych komórek.

Okno dni zaczyna się od dnia wdrożenia z pamięci (przed pierwszym udanym kliknięciem: dziś). Proces nie należy do
okresu: Uruchomienie ma okres dzisiejszej daty z zegara procesu (ADR 0019). Zatrzymanie po rdzeniu niesie fakty
(``EnteringFacts``), więc Logi mają zmiany i problemy także wtedy. Plik dostępu, który zniknie albo zepsuje się między
Sprawdzaniem a odczytem skrzynki, daje to samo Zatrzymanie co w Sprawdzaniu. Adres, temat ani treść maila nie
wychodzą z rdzenia do faktów: ``MailRead`` ich nie ma, a adres nieznanego nadawcy ma tylko problem w pamięci.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, assert_never

from . import intermax_messages, raw_orders, register_file, worker_addresses, workbook_files
from . import report_entering_messages as messages
from .domain import ProgressPhase
from .input_checks import workers
from .intermax_cells import CellsWritten, Rejected, write_cells
from .intermax_ordering import local_now, paste_areas
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Waiting
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .register_columns import COMPLETED, DATE, ORDER_NUMBER, SUCCESSFUL, WORKER
from .register_file import OrderSheets, RegisterFile
from .report_cells import CellChange, OrderRow
from .run_context import RunContext
from .settlement_period import period_of
from .workbook_files import WorkbookError
from .workbook_parts import UnsupportedShape
from .worker_addresses import AddressesError
from .worker_report_inbox import InboxUnreachable, Mails, PasswordRejected, WorkerReportInbox
from .worker_reports import (
    MailRead,
    OrderKey,
    OwnEntries,
    OwnEntry,
    ReadReport,
    RegisterOrder,
    ReportInputs,
    ReportMail,
    ReportProblem,
    Window,
    WorkerAddresses,
    enter_reports,
)

__all__ = [
    "EnteringFacts",
    "EnteringInputs",
    "EnteringSummary",
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
    wpisy."""

    rollout: date | None
    memory: OwnEntries


class StateUnreadable(Exception):
    """Pamięci własnych wpisów nie da się odczytać: zły JSON albo nieznana wersja. Pusta pamięć cofnęłaby dzień wdrożenia
    i zrobiłaby z własnych wpisów ręczne, więc to Zatrzymanie."""


class ReportState(Protocol):
    def load(self) -> SavedState:
        """Pamięć z ostatniego udanego zapisu; ``StateUnreadable``, gdy jej nie da się odczytać."""
        ...

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        """Zapisuje dzień wdrożenia i pamięć po udanym zapisie INTERMAX (``written`` to dowód zapisu); ``False``, gdy
        zapis na dysku się nie udał i czeka na następną próbę."""
        ...


@dataclass
class ReportStateInMemory:
    """Pamięć bez pliku: Skrypt dla maszyn i testy. ``saved`` to stan, a ``save_memory`` go zastępuje."""

    saved: SavedState = field(default_factory=lambda: SavedState(None, OwnEntries.EMPTY))

    def load(self) -> SavedState:
        return self.saved

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        self.saved = SavedState(rollout, memory)
        return True


@dataclass(frozen=True)
class ReportEnteringParts:
    """Zależności Wpisania raportów od gospodarza: Skrzynka raportów i pamięć własnych wpisów."""

    inbox: WorkerReportInbox
    state: ReportState


@dataclass(frozen=True)
class EnteringInputs:
    """Wejście Wpisania raportów: INTERMAX z Ustawień taty, Konfiguracja wykonawców, plik adresów, zależności gospodarza
    i zegar procesu. ``period`` jak w ``OrderingInputs``: okres dzisiejszej daty przy starcie (ADR 0019)."""

    register_path: Path
    worker_config: Path
    worker_addresses: Path
    parts: ReportEnteringParts
    now: Callable[[], datetime] = local_now
    waiting: Waiting = field(default_factory=Waiting)
    disk: Disk = LOCAL_DISK
    period: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", period_of(self.now().date()).token)


@dataclass(frozen=True)
class EnteringFacts:
    """Fakty kliknięcia od rdzenia raportów, bez adresów, tematów i treści maili.

    ``rollout_before``: dzień wdrożenia z pamięci przed kliknięciem (``None``: pierwsze), ``rollout``: dzień wdrożenia
    tego kliknięcia. ``memory_before``: zapamiętane własne wpisy zleceń, które mają Wpis w tym kliknięciu. ``skipped``:
    maile, których Skrzynka raportów nie umiała przeczytać.
    """

    today: date
    rollout_before: date | None
    rollout: date
    memory_before: tuple[OwnEntry, ...]
    skipped: int
    mails: tuple[MailRead, ...]
    problems: tuple[ReportProblem, ...]
    changes: tuple[CellChange, ...]


@dataclass
class EnteringSummary:
    """Podsumowanie Wpisania raportów: fakty kliknięcia i liczba wpisanych komórek (``written``)."""

    facts: EnteringFacts
    written: int
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def entered(self) -> int:
        """Zlecenia, do których kliknięcie coś wpisało: tyle Wpisów raportu tata już nie przepisuje."""

        return len({change.order for change in self.facts.changes}) if self.written else 0

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
        found = workers(inputs.worker_config)
        if isinstance(found, Message):
            raise StopError(found)
        try:
            addresses = worker_addresses.load(inputs.worker_addresses, workers=found)
        except AddressesError as error:
            raise StopError(messages.addresses_unusable(inputs.worker_addresses, error.problem)) from error
        with _stops(messages.state_unreadable, StateUnreadable):
            saved = parts.state.load()
        with _stops_unusable():
            workbook_files.ensure_available(register_path)
        return addresses, saved

    addresses, saved = phases.check(check)
    window = Window.of(inputs.now().date(), saved.rollout)

    def read() -> tuple[RegisterFile, tuple[RegisterOrder, ...], int, tuple[ReportMail, ...]]:
        with _stops_unusable():
            register = register_file.read(register_path, files)
        orders = _orders(register, window.first, copy=files.copy is not None)
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
                return register, orders, outcome.skipped, outcome.mails
        assert_never(outcome)

    register, orders, skipped, mails = phases.read(read)

    def plan() -> tuple[EnteringFacts, OwnEntries]:
        found = enter_reports(
            ReportInputs(
                mails=mails, addresses=addresses, orders=orders, window=window, memory=saved.memory, kept=frozenset()
            )
        )
        reported = {
            OrderKey(entry.number, read.day, read.worker)
            for read in found.mails
            if isinstance(read, ReadReport)
            for entry in read.entries
        }
        before = tuple(
            sorted(
                (entry for entry in saved.memory.entries if entry.key in reported),
                key=lambda entry: (entry.key, entry.column.value),
            )
        )
        planned = EnteringFacts(
            window.today, saved.rollout, window.rollout, before, skipped, found.mails, found.problems, found.changes
        )
        return planned, found.memory

    facts, memory = phases.plan(plan, issue_count=lambda planned: len(planned[0].problems))

    def save() -> CellsWritten:
        with (
            _stops(lambda: messages.unsupported_shape(register_path, _sheet(facts)), UnsupportedShape, facts=facts),
            _stops_unusable(facts),
        ):
            written = write_cells(register, facts.changes, waiting=inputs.waiting, disk=inputs.disk)
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
    summary = EnteringSummary(facts, written.count, warnings)
    return replace(summary, phase_durations_ms=phases.durations_ms())


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
    """Arkusz pierwszej zmiany: tam zapis trafił na kształt, którego nie przenosi."""

    return facts.changes[0].order.sheet if facts.changes else ""


def _orders(register: RegisterFile, since: date, *, copy: bool) -> tuple[RegisterOrder, ...]:
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
            )
            if order is not None:
                orders.append(order)
    return tuple(orders)
