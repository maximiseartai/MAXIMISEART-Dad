"""Pliki Wpisania raportów w ``config`` (ADR 0028): jedyny moduł, który zna ich format. Każdy plik ma jednego pisarza.

- ``wpisanie-raportow-stan.json``, ``{schema_version: 1, rollout, own: [{number, day, worker, column, value}]}``: dzień
  wdrożenia i komórki, które Wpisanie raportów samo wpisało. Pisze go tylko proces po udanym zapisie INTERMAX.
- ``wpisanie-raportow-wynik.json``, ``{schema_version: 1, clicked_at, days, workers, problems}``: wynik ostatniego
  udanego kliknięcia dla widoku Raporty, z liczbami Wykonawców, zdaniem o każdym problemie (``reasons.reason``) i
  adresem nieznanego nadawcy, który poza widokiem Raporty nigdzie nie trafia. Pisze go tylko proces, po pamięci.
- ``wpisanie-raportow-decyzje.json``, ``{schema_version: 1, kept: [{number, day, worker, column, reported}]}``: decyzje
  taty „Zostaw moją”. Pisze go tylko żądanie API „Zostaw moją” (``keep``); proces czyta go przy Sprawdzaniu razem z
  pamięcią jako migawkę, a widok Raporty łączy go z wynikiem przy odczycie, więc wspólnej blokady procesu i API nie ma.

Każdy plik zapisuje się atomowo (``atomic_file.StateFile``); treść, której nie dało się zapisać, czeka w pamięci tej
pracy Centrum i wygrywa przy następnym odczycie. Plik, którego nie da się odczytać (zły JSON, nieznana wersja, zły
wpis), to ``StateUnreadable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import threading
from typing import Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, ValidationError

from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.intermax_cells import CellsWritten
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import ClickResult, SavedState, StateUnreadable
from rozliczenia.tool_files import REPORT_ENTERING_DECISIONS, REPORT_ENTERING_RESULT, REPORT_ENTERING_STATE
from rozliczenia.worker_reports import (
    ForeignOrder,
    Kept,
    Login,
    ManualDifference,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    OtherDay,
    OwnEntries,
    OwnEntry,
    RepeatedOrder,
    ReportProblem,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
)
from rozliczenia.worker_reports.reasons import reason

_SCHEMA_VERSION: Final = 1

Column = Literal["SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Own(_Record):
    number: str
    day: date
    worker: str
    column: Column
    value: str


class _State(_Record):
    schema_version: Literal[1]
    rollout: date
    own: list[_Own]


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


class _Worker(_Record):
    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: list[str]


class _Problem(_Record):
    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: _Kept | None


class _Result(_Record):
    schema_version: Literal[1]
    clicked_at: datetime
    days: list[date]
    workers: list[_Worker]
    problems: list[_Problem]


@dataclass(frozen=True)
class ShownWorker:
    """Liczby Wykonawcy ``worker`` z dnia ``day`` z ostatniego kliknięcia: zlecenia, wpisane (``tak`` albo ``nie`` w
    ``SKUTECZNE`` po kliknięciu), Raporty wykonawcy i numery zleceń bez żadnego Wpisu."""

    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: tuple[str, ...]


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
class ShownResult:
    """Wynik ostatniego udanego kliknięcia dla widoku Raporty (bez decyzji „Zostaw moją”: łączy je widok)."""

    clicked_at: datetime
    days: tuple[date, ...]
    workers: tuple[ShownWorker, ...]
    problems: tuple[ShownProblem, ...]


@dataclass
class _TextFile:
    """Plik stanu z ostatnią treścią zapisaną przez tę pracę Centrum: ``text`` daje ją, dopóki plik jest niedostępny."""

    file: StateFile
    _written: str | None = field(default=None, repr=False)

    def text(self) -> str | None:
        """Treść pliku; ``None``, gdy go nie ma, a ``StateUnreadable``, gdy nie da się go odczytać."""

        self.file.retry()
        if self.file.unavailable and self._written is not None:
            return self._written
        try:
            return self.file.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as error:
            raise StateUnreadable from error

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
        def file(name: str, where: str) -> _TextFile:
            return _TextFile(StateFile(work.config / name, work.log, where=where, pause=work.pause))

        return cls(
            file(REPORT_ENTERING_STATE, "pamięć Wpisania raportów"),
            file(REPORT_ENTERING_RESULT, "wynik Wpisania raportów"),
            file(REPORT_ENTERING_DECISIONS, "decyzje „Zostaw moją”"),
        )

    def load(self) -> SavedState:
        text = self.memory.text()
        kept = self.kept()
        if text is None:
            return SavedState(None, OwnEntries.EMPTY, kept)
        try:
            state = _State.model_validate_json(text)
            entries = frozenset(
                OwnEntry(
                    OrderKey(OrderNumber(own.number), own.day, Login(own.worker)), ReportColumn(own.column), own.value
                )
                for own in state.own
            )
            return SavedState(state.rollout, OwnEntries(entries), kept)
        except (ValidationError, ValueError) as error:
            raise StateUnreadable from error

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
        return self.memory.write(_State(schema_version=_SCHEMA_VERSION, rollout=rollout, own=own))

    def save_result(self, written: CellsWritten, result: ClickResult) -> None:
        workers = [
            _Worker(
                day=worker.day,
                worker=worker.worker,
                orders=worker.orders,
                entered=worker.entered,
                mails=worker.mails,
                without_report=list(worker.without_report),
            )
            for worker in result.workers
        ]
        self.result.write(
            _Result(
                schema_version=_SCHEMA_VERSION,
                clicked_at=result.clicked_at,
                days=list(result.days),
                workers=workers,
                problems=[_problem(problem) for problem in result.problems],
            )
        )

    def shown(self) -> ShownResult | None:
        """Wynik ostatniego udanego kliknięcia; ``None`` przed pierwszym."""

        text = self.result.text()
        if text is None:
            return None
        try:
            result = _Result.model_validate_json(text)
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
        )

    def kept(self) -> frozenset[Kept]:
        """Decyzje taty „Zostaw moją”."""

        text = self.decisions.text()
        if text is None:
            return frozenset()
        try:
            return frozenset(decision.kept() for decision in _Decisions.model_validate_json(text).kept)
        except ValidationError as error:
            raise StateUnreadable from error

    def keep(self, kept: Kept) -> None:
        """Dopisuje decyzję „Zostaw moją” ``kept`` do pliku decyzji; ``StateUnreadable``, gdy pliku nie da się
        odczytać, bo zapis bez dawnych decyzji przywróciłby ich różnice."""

        with self._deciding:
            decisions = sorted(self.kept() | {kept}, key=lambda decision: (decision.key, decision.column.value, decision.reported))
            self.decisions.write(
                _Decisions(schema_version=_SCHEMA_VERSION, kept=[_Kept.of(decision) for decision in decisions])
            )


def _problem(problem: ReportProblem) -> _Problem:
    """Problem w pliku wyniku: miejsce w widoku Raporty, numer zlecenia, zdanie dla taty, a przy nieznanym nadawcy jego
    adres (jedyne miejsce, do którego trafia, ADR 0028)."""

    said = reason(problem)
    match problem:
        case UnreadableSubject(worker=worker, arrived=arrived):
            return _Problem(day=arrived.date(), worker=worker, number=None, reason=said, sender=None, difference=None)
        case UnknownSender(sender=sender, day=day):
            return _Problem(day=day, worker=None, number=None, reason=said, sender=sender.shown(), difference=None)
        case MissingVerdict() | UnknownNumber() | ForeignOrder() | OtherDay() | RepeatedOrder():
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
