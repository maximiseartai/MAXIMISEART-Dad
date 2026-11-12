"""Pliki Wpisania raportów w ``config`` (ADR 0028): jedyny moduł, który zna ich format. Każdy plik ma jednego pisarza.

- ``wpisanie-raportow-stan.json``, ``{schema_version: 3, rollout, own: [{number, day, worker, column, value}], moves:
  [{number, day, worker, origin_day, origin_worker, origin_name, since, overridden}]}``: dzień wdrożenia, komórki,
  które Wpisanie raportów samo wpisało, i pamięć zleceń, na które samo zadziałało Przeniesieniem albo Wpisem
  (``OwnMove``, ADR 0029). Pisze go tylko proces po udanym zapisie INTERMAX.
  Plik w wersji 1 (sprzed Przeniesień, v0.7.0) dalej się czyta, bez pamięci zleceń, dopóki następne kliknięcie nie
  zapisze wersji 3. Wersja 2 była tylko na gałęzi #1358 (bez ``overridden``, w pierwszej rundzie też bez
  ``origin_name`` i ``since``) i nigdy w Wydaniu: czyta się jak wersja 1, zamiast Zatrzymania.
- ``wpisanie-raportow-wynik.json``, ``{schema_version: 3, clicked_at, days, workers, problems, notes}``: wynik
  ostatniego udanego kliknięcia dla widoku Raporty, z liczbami i zleceniami dnia każdego Wykonawcy (``orders_detail``:
  numer, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` po kliknięciu i czy zlecenie ma Wpis), zdaniem o każdym problemie
  (``reasons.reason``), adresem nieznanego nadawcy i informacjami o Przeniesieniach (``notes``: dzień, Wykonawca, numer
  i zdanie z ``reasons.note``); zlecenia i adres poza widokiem Raporty nigdzie nie trafiają. Pisze go tylko proces, po
  pamięci. Plik w wersji 1, sprzed listy zleceń, dalej się czyta, bez zleceń dnia (``ShownResult.detailed``), a pliki w
  wersjach 1 i 2 bez informacji, dopóki następne kliknięcie nie zapisze wersji 3.
- ``wpisanie-raportow-decyzje.json``, ``{schema_version: 1, kept: [{number, day, worker, column, reported}]}``: decyzje
  taty „Zostaw moją”. Pisze go tylko żądanie API „Zostaw moją” (``keep``); proces czyta go przy Sprawdzaniu razem z
  pamięcią jako migawkę, a widok Raporty łączy go z wynikiem przy odczycie, więc wspólnej blokady procesu i API nie ma.

Każdy plik zapisuje się atomowo (``atomic_file.StateFile``); treść, której nie dało się zapisać, czeka w pamięci tej
pracy Centrum i wygrywa przy następnym odczycie. Plik, którego nie da się odczytać (zły JSON, nieznana wersja, zły
wpis), to ``StateUnreadable``, a plik decyzji ``DecisionsUnreadable``, żeby Komunikat wskazał plik, który zawinił.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import threading
from typing import Annotated, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.intermax_cells import CellsWritten
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import ClickResult, DecisionsUnreadable, SavedState, StateUnreadable
from rozliczenia.tool_files import REPORT_ENTERING_DECISIONS, REPORT_ENTERING_RESULT, REPORT_ENTERING_STATE
from rozliczenia.worker_reports import (
    ConflictingVerdicts,
    ForeignOrder,
    Kept,
    Login,
    ManualDifference,
    MissingVerdict,
    OrderDetail,
    OrderKey,
    OrderNumber,
    OtherDay,
    OwnEntries,
    OwnEntry,
    OwnMove,
    RepeatedOrder,
    ReportNote,
    ReportProblem,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
)
from rozliczenia.worker_reports.reasons import note, reason

_DECISIONS_VERSION: Final = 1
_STATE_VERSION: Final = 3
"""Wersja pliku pamięci: 3 dodała pamięć zleceń z Przeniesień (#1347); 2 była tylko na gałęzi #1347."""
_RESULT_VERSION: Final = 3
"""Wersja pliku wyniku: 2 dodała zlecenia dnia Wykonawcy (#1322), 3 informacje o Przeniesieniach (#1347)."""

Column = Literal["SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Own(_Record):
    number: str
    day: date
    worker: str
    column: Column
    value: str


class _Move(_Record):
    number: str
    day: date
    worker: str
    origin_day: date
    origin_worker: str
    origin_name: str
    since: datetime
    overridden: bool


class _StateV1(_Record):
    """Plik pamięci sprzed Przeniesień (#1347): czyta go tylko ``load``."""

    schema_version: Literal[1]
    rollout: date
    own: list[_Own]


class _StateV2(_Record):
    """Plik pamięci z gałęzi #1347 sprzed jej trzeciej rundy, w obu postaciach ``moves``: czyta go tylko ``load``, bez
    pamięci zleceń."""

    schema_version: Literal[2]
    rollout: date
    own: list[_Own]
    moves: list[dict[str, object]]


class _State(_Record):
    schema_version: Literal[3]
    rollout: date
    own: list[_Own]
    moves: list[_Move]


class _AnyState(RootModel[Annotated[_StateV1 | _StateV2 | _State, Field(discriminator="schema_version")]]):
    """Plik pamięci w którejkolwiek wersji, rozpoznanej po ``schema_version``."""


class _Kept(_Record):
    number: str
    day: date
    worker: str
    column: Column
    reported: str

    @classmethod
    def of(cls, kept: Kept) -> _Kept:
        key = kept.key
        return cls(number=key.number, day=key.day, worker=key.worker, column=kept.column.value, reported=kept.reported)

    def kept(self) -> Kept:
        key = OrderKey(OrderNumber(self.number), self.day, Login(self.worker))
        return Kept(key, ReportColumn(self.column), self.reported)


class _Decisions(_Record):
    schema_version: Literal[1]
    kept: list[_Kept]


class _WorkerV1(_Record):
    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: list[str]


class _Order(_Record):
    number: str
    successful: str | None
    activities: str | None
    reported: bool


class _Worker(_WorkerV1):
    orders_detail: list[_Order]


class _Problem(_Record):
    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: _Kept | None


class _Note(_Record):
    day: date
    worker: str
    number: str
    text: str


class _ResultV1(_Record):
    """Plik wyniku sprzed zleceń dnia (#1322): czyta go tylko ``shown``."""

    schema_version: Literal[1]
    clicked_at: datetime
    days: list[date]
    workers: list[_WorkerV1]
    problems: list[_Problem]


class _ResultV2(_Record):
    """Plik wyniku sprzed informacji o Przeniesieniach (#1347): czyta go tylko ``shown``."""

    schema_version: Literal[2]
    clicked_at: datetime
    days: list[date]
    workers: list[_Worker]
    problems: list[_Problem]


class _Result(_Record):
    schema_version: Literal[3]
    clicked_at: datetime
    days: list[date]
    workers: list[_Worker]
    problems: list[_Problem]
    notes: list[_Note]


class _AnyResult(RootModel[Annotated[_ResultV1 | _ResultV2 | _Result, Field(discriminator="schema_version")]]):
    """Plik wyniku w którejkolwiek wersji, rozpoznanej po ``schema_version``."""


@dataclass(frozen=True)
class ShownWorker:
    """Liczby Wykonawcy ``worker`` z dnia ``day`` z ostatniego kliknięcia: zlecenia, wpisane (``tak`` albo ``nie`` w
    ``SKUTECZNE`` po kliknięciu), Raporty wykonawcy, numery zleceń bez żadnego Wpisu i zlecenia dnia w kolejności z
    INTERMAX (``None``: plik wyniku sprzed zleceń dnia)."""

    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: tuple[str, ...]
    orders_detail: tuple[OrderDetail, ...] | None


@dataclass(frozen=True)
class ShownProblem:
    """Problem z ostatniego kliknięcia w widoku Raporty: dzień i Wykonawca, przy którym stoi (``None``: nieznany
    nadawca), numer zlecenia, jeśli problem go ma, zdanie dla taty, adres nieznanego nadawcy i komórka różnicy z ręczną
    wartością, przy której tata może kliknąć „Zostaw moją”."""

    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: Kept | None


@dataclass(frozen=True)
class ShownNote:
    """Informacja z ostatniego kliknięcia przy dniu ``day`` Wykonawcy ``worker``: numer zlecenia i zdanie dla taty."""

    day: date
    worker: str
    number: str
    text: str


@dataclass(frozen=True)
class ShownResult:
    """Wynik ostatniego udanego kliknięcia dla widoku Raporty (bez decyzji „Zostaw moją”: łączy je widok);
    ``detailed``: plik ma zlecenia dnia (wersja 2 i nowsza), ``notes``: informacje o Przeniesieniach (pusto w pliku
    sprzed wersji 3)."""

    clicked_at: datetime
    days: tuple[date, ...]
    workers: tuple[ShownWorker, ...]
    problems: tuple[ShownProblem, ...]
    detailed: bool
    notes: tuple[ShownNote, ...] = ()


@dataclass
class _TextFile:
    """Plik stanu z ostatnią treścią zapisaną przez tę pracę Centrum: ``text`` daje ją, dopóki plik jest niedostępny.
    ``unreadable``: wyjątek pliku, którego nie da się odczytać."""

    file: StateFile
    unreadable: type[Exception]
    _written: str | None = field(default=None, repr=False)

    def text(self) -> str | None:
        """Treść pliku; ``None``, gdy go nie ma, a ``unreadable``, gdy nie da się go odczytać."""

        self.file.retry()
        if self.file.unavailable and self._written is not None:
            return self._written
        try:
            return self.file.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as error:
            raise self.unreadable from error

    def write(self, record: BaseModel) -> bool:
        self._written = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        self.file.write(self._written)
        return not self.file.unavailable


@dataclass
class FileReportState:
    """Pliki Wpisania raportów w ``config`` pracy Centrum: pamięć własnych wpisów, wynik dla widoku Raporty i decyzje
    „Zostaw moją”. Decyzje zapisuje ``keep`` pod blokadą, więc dwa kliknięcia „Zostaw moją” naraz nie gubią żadnej."""

    memory: _TextFile
    result: _TextFile
    decisions: _TextFile
    _deciding: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def of_work(cls, work: CentrumWork) -> FileReportState:
        def file(name: str, where: str, unreadable: type[Exception] = StateUnreadable) -> _TextFile:
            return _TextFile(StateFile(work.config / name, work.log, where=where, pause=work.pause), unreadable)

        return cls(
            file(REPORT_ENTERING_STATE, "pamięć Wpisania raportów"),
            file(REPORT_ENTERING_RESULT, "wynik Wpisania raportów"),
            file(REPORT_ENTERING_DECISIONS, "decyzje „Zostaw moją”", DecisionsUnreadable),
        )

    def load(self) -> SavedState:
        """Pamięć i decyzje „Zostaw moją”: najpierw cała pamięć (``StateUnreadable``), potem decyzje
        (``DecisionsUnreadable``), więc błąd decyzji znaczy, że pamięć jest poprawna."""

        text = self.memory.text()
        if text is None:
            return SavedState(None, OwnEntries.EMPTY, self.kept())
        try:
            state = _AnyState.model_validate_json(text).root
            entries = frozenset(
                OwnEntry(
                    OrderKey(OrderNumber(own.number), own.day, Login(own.worker)), ReportColumn(own.column), own.value
                )
                for own in state.own
            )
            moves = frozenset(
                OwnMove(
                    OrderNumber(move.number),
                    move.day,
                    Login(move.worker),
                    move.origin_day,
                    Login(move.origin_worker),
                    move.origin_name,
                    move.since,
                    move.overridden,
                )
                for move in (state.moves if isinstance(state, _State) else ())
            )
            memory = OwnEntries(entries, moves)
        except (ValidationError, ValueError) as error:
            raise StateUnreadable from error
        return SavedState(state.rollout, memory, self.kept())

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        own = [
            _Own(
                number=entry.key.number,
                day=entry.key.day,
                worker=entry.key.worker,
                column=entry.column.value,
                value=entry.value,
            )
            for entry in sorted(memory.entries, key=lambda entry: (entry.key, entry.column.value, entry.value))
        ]
        moves = [
            _Move(
                number=move.number,
                day=move.day,
                worker=move.worker,
                origin_day=move.origin_day,
                origin_worker=move.origin_worker,
                origin_name=move.origin_name,
                since=move.since,
                overridden=move.overridden,
            )
            for move in sorted(memory.moves, key=lambda move: (move.day, move.number))
        ]
        return self.memory.write(_State(schema_version=_STATE_VERSION, rollout=rollout, own=own, moves=moves))

    def save_result(self, written: CellsWritten, result: ClickResult) -> None:
        workers = [
            _Worker(
                day=worker.day,
                worker=worker.worker,
                orders=worker.orders,
                entered=worker.entered,
                mails=worker.mails,
                without_report=list(worker.without_report),
                orders_detail=[
                    _Order(
                        number=order.number,
                        successful=order.successful,
                        activities=order.activities,
                        reported=order.reported,
                    )
                    for order in worker.orders_detail
                ],
            )
            for worker in result.workers
        ]
        self.result.write(
            _Result(
                schema_version=_RESULT_VERSION,
                clicked_at=result.clicked_at,
                days=list(result.days),
                workers=workers,
                problems=[_problem(problem) for problem in result.problems],
                notes=[_note(found) for found in result.notes],
            )
        )

    def shown(self) -> ShownResult | None:
        """Wynik ostatniego udanego kliknięcia; ``None`` przed pierwszym."""

        text = self.result.text()
        if text is None:
            return None
        try:
            result = _AnyResult.model_validate_json(text).root
        except ValidationError as error:
            raise StateUnreadable from error
        return ShownResult(
            result.clicked_at,
            tuple(result.days),
            tuple(
                ShownWorker(
                    worker.day,
                    worker.worker,
                    worker.orders,
                    worker.entered,
                    worker.mails,
                    tuple(worker.without_report),
                    _orders(worker),
                )
                for worker in result.workers
            ),
            tuple(
                ShownProblem(
                    problem.day,
                    problem.worker,
                    problem.number,
                    problem.reason,
                    problem.sender,
                    None if problem.difference is None else problem.difference.kept(),
                )
                for problem in result.problems
            ),
            detailed=not isinstance(result, _ResultV1),
            notes=tuple(
                ShownNote(found.day, found.worker, found.number, found.text)
                for found in (result.notes if isinstance(result, _Result) else ())
            ),
        )

    def kept(self) -> frozenset[Kept]:
        """Decyzje taty „Zostaw moją”; ``DecisionsUnreadable``, gdy pliku decyzji nie da się odczytać."""

        text = self.decisions.text()
        if text is None:
            return frozenset()
        try:
            return frozenset(decision.kept() for decision in _Decisions.model_validate_json(text).kept)
        except ValidationError as error:
            raise DecisionsUnreadable from error

    def keep(self, kept: Kept) -> None:
        """Dopisuje decyzję „Zostaw moją” ``kept`` do pliku decyzji; ``DecisionsUnreadable``, gdy pliku nie da się
        odczytać, bo zapis bez dawnych decyzji przywróciłby ich różnice."""

        with self._deciding:
            decisions = sorted(self.kept() | {kept}, key=lambda decision: (decision.key, decision.column.value, decision.reported))
            self.decisions.write(
                _Decisions(schema_version=_DECISIONS_VERSION, kept=[_Kept.of(decision) for decision in decisions])
            )


def _orders(worker: _WorkerV1) -> tuple[OrderDetail, ...] | None:
    if not isinstance(worker, _Worker):
        return None
    return tuple(
        OrderDetail(OrderNumber(order.number), order.successful, order.activities, order.reported)
        for order in worker.orders_detail
    )


def _note(found: ReportNote) -> _Note:
    """Informacja w pliku wyniku: dzień i Wykonawca kafelka, numer zlecenia i zdanie dla taty, bez treści maili."""

    return _Note(day=found.day, worker=found.worker, number=found.number, text=note(found))


def _problem(problem: ReportProblem) -> _Problem:
    """Problem w pliku wyniku: miejsce w widoku Raporty, numer zlecenia, zdanie dla taty, a przy nieznanym nadawcy jego
    adres (jedyne miejsce, do którego trafia, ADR 0028)."""

    said = reason(problem)
    match problem:
        case UnreadableSubject(worker=worker, arrived=arrived):
            return _Problem(day=arrived.date(), worker=worker, number=None, reason=said, sender=None, difference=None)
        case UnknownSender(sender=sender, day=day):
            return _Problem(day=day, worker=None, number=None, reason=said, sender=sender.shown(), difference=None)
        case MissingVerdict() | ConflictingVerdicts() | UnknownNumber() | ForeignOrder() | OtherDay() | RepeatedOrder():
            return _Problem(
                day=problem.day, worker=problem.worker, number=problem.number, reason=said, sender=None, difference=None
            )
        case ManualDifference(key=key, column=column, reported=reported):
            difference = _Kept.of(Kept(key, column, reported))
            return _Problem(
                day=key.day, worker=key.worker, number=key.number, reason=said, sender=None, difference=difference
            )
        case _:
            assert_never(problem)
