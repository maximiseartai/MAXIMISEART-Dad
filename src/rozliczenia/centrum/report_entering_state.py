"""Pliki Wpisania raportów w ``config`` (ADR 0028): jedyny moduł, który zna ich format. Każdy plik ma jednego pisarza.

- ``wpisanie-raportow-stan.json``, ``{schema_version: 4, rollout, own: [{number, day, worker, column, value}], moves:
  [{number, day, worker, origin_day, origin_worker, origin_name, since, overridden, added}], requested: [{mail, worker,
  day, number, verdict, activities, at}]}``: dzień wdrożenia, komórki, które Wpisanie raportów samo wpisało, pamięć zleceń,
  na które samo zadziałało Przeniesieniem, Wpisem albo dopisaniem (``OwnMove``, ADR 0029), i decyzje taty Wpisu na
  życzenie (``RequestedEntry``, ADR 0041). Pisze go tylko proces po udanym zapisie INTERMAX, także z decyzją z
  kliknięcia Wpisu na życzenie. Wersja 4 to obietnica
  pisarza: ``own`` ma tylko numer, który w chwili zapisu miał w odczytanych dniach jedno zlecenie, pod jego kluczem
  (``OwnEntries``), więc wpisy idą za wierszem. Plik bez ``added`` (sprzed Zleceń dopisanych z raportu) czyta się
  z ``added`` fałszywym, a plik bez ``requested`` (sprzed Wpisu na życzenie) bez decyzji.
  Starsze wersje czyta ``load`` jako ``OlderOwnEntries``, bez Zatrzymania, a ich wpis należy do miejsca z chwili zapisu
  (numer, dzień, Wykonawca), dopóki następne kliknięcie nie zapisze wersji 4: wersja 1 (Wydania v0.7.0 i v0.8.0, sprzed
  Przeniesień) bez pamięci zleceń, wersja 2 (nigdy w Wydaniu, bez ``overridden``, czasem też bez ``origin_name`` i
  ``since``) jak wersja 1, a wersja 3 (nigdy w Wydaniu) z pamięcią zleceń, czasem także z ``added``.
- ``wpisanie-raportow-wynik.json``, ``{schema_version: 3, clicked_at, days, workers, problems, notes}``: wynik
  ostatniego udanego kliknięcia dla widoku Raporty, z liczbami i zleceniami dnia każdego Wykonawcy (``orders_detail``:
  numer, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` po kliknięciu, czy zlecenie ma Wpis, Kody czynności zlecenia ``tak``
  w ``codes``, a plik bez nich, sprzed kodów, czyta się bez kodów, czy ma Wpis w raporcie z błędem tematu, ``faulty``, i
  Wpis na życzenie tego Wpisu, ``request``; plik bez niego czyta się bez przycisku), zdaniem o każdym problemie
  (``reasons.reason``), Wpisem na życzenie przy problemie, przy którym tata może go kliknąć (``request``; plik bez
  niego czyta się bez przycisku), adresem nieznanego nadawcy i informacjami o Przeniesieniach i dopisaniach (``notes``: dzień,
  Wykonawca, numer i zdanie z ``reasons.note``); zlecenia i adres poza widokiem Raporty nigdzie nie trafiają. Przy
  problemie raportu z błędem tematu ma jego temat po strażniku reguły danych pracy Centrum (``guarded``, ADR 0025: bez
  wartości ``ADRES`` i z zamaskowanym telefonem i ulicą), rodzaj błędu (``reasons.subject_fault``), dzień, za który
  Centrum go liczy, chwilę przyjścia maila i skrót maila, po którym widok łączy problem z Wpisami na życzenie tego
  raportu przy zleceniach (``faulty_subject``), a przy dniu Wykonawcy dni z tematu raportów z
  pomylonym tematem za ten dzień (``mistaken``) i zdanie z ``reasons.overtaken`` o każdym raporcie z błędem tematu za
  ten dzień, z którego nie ma już czego wpisać, z jego tematem po tym samym strażniku (``overtaken``); plik bez nich
  czyta się bez nich. Pisze go tylko proces, po pamięci. Plik w wersji 1, sprzed listy zleceń, dalej się czyta, bez zleceń dnia (``ShownResult.detailed``), a pliki w
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
from rozliczenia.client_data import ForbiddenValues, guarded
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.intermax_cells import CellsWritten
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import ClickResult, DecisionsUnreadable, StateUnreadable
from rozliczenia.tool_files import REPORT_ENTERING_DECISIONS, REPORT_ENTERING_RESULT, REPORT_ENTERING_STATE
from rozliczenia.worker_reports import (
    ConflictingVerdicts,
    FaultyDescription,
    Kept,
    Login,
    MailId,
    ManualDifference,
    MissingVerdict,
    Offer,
    OlderOwnEntries,
    OrderDetail,
    OrderKey,
    OrderNumber,
    RefusedMove,
    OwnEntries,
    OwnEntry,
    OwnMove,
    RepeatedNumber,
    RepeatedOrder,
    ReportNote,
    ReportProblem,
    RequestedEntry,
    SavedState,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
)
from rozliczenia.worker_reports.reasons import note, overtaken, reason, subject_fault

_DECISIONS_VERSION: Final = 1
_STATE_VERSION: Final = 4
"""Wersja pliku pamięci: 4 obiecuje wpisy tylko przy jedynym zleceniu numeru, 3 dodała pamięć zleceń z
Przeniesień; 2 nie była w żadnym Wydaniu."""
_RESULT_VERSION: Final = 3
"""Wersja pliku wyniku: 2 dodała zlecenia dnia Wykonawcy, 3 informacje o Przeniesieniach."""

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
    added: bool = False


class _Requested(_Record):
    mail: str
    worker: str
    day: date
    number: str
    verdict: Literal["tak", "nie"]
    activities: str
    at: datetime

    @classmethod
    def of(cls, decision: RequestedEntry) -> _Requested:
        return cls(
            mail=decision.mail.digest,
            worker=decision.worker,
            day=decision.day,
            number=decision.number,
            verdict=decision.verdict.value,
            activities=decision.activities,
            at=decision.at,
        )

    def decision(self) -> RequestedEntry:
        key = MailId(self.mail), Login(self.worker), self.day, OrderNumber(self.number)
        return RequestedEntry(*key, Verdict(self.verdict), self.activities, self.at)


class _StateV1(_Record):
    """Plik pamięci sprzed Przeniesień: czyta go tylko ``load``."""

    schema_version: Literal[1]
    rollout: date
    own: list[_Own]


class _StateV2(_Record):
    """Plik pamięci w wersji 2 (nigdy w Wydaniu), w obu postaciach ``moves``: czyta go tylko ``load``, bez
    pamięci zleceń."""

    schema_version: Literal[2]
    rollout: date
    own: list[_Own]
    moves: list[dict[str, object]]


class _StateV3(_Record):
    """Plik pamięci w wersji 3 (nigdy w Wydaniu), z pamięcią zleceń, ale z wpisami także przy numerze w kilku
    zleceniach: czyta go tylko ``load``."""

    schema_version: Literal[3]
    rollout: date
    own: list[_Own]
    moves: list[_Move]


class _State(_Record):
    schema_version: Literal[4]
    rollout: date
    own: list[_Own]
    moves: list[_Move]
    requested: list[_Requested] = []


class _AnyState(RootModel[Annotated[_StateV1 | _StateV2 | _StateV3 | _State, Field(discriminator="schema_version")]]):
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


class _OrderOffer(_Record):
    """Wpis na życzenie przy zleceniu z Wpisem raportu z błędem tematu: skrót maila i co się wpisze do tego zlecenia
    (``successful`` z czynnościami ``activities``), które po Wpisie stoi w dniu ``order_day`` u ``worker`` (przy
    Przeniesieniu nadawca i dzień z tematu). Dnia decyzji i numeru plik nie ma: oferta przy zleceniu ma numer tego
    zlecenia, a tata decyduje w dniu zlecenia po Wpisie (``Offer``, ``_reading._offers`` rdzenia)."""

    mail: str
    activities: str
    successful: Literal["tak", "nie"]
    worker: str
    order_day: date

    @classmethod
    def of(cls, offer: Offer) -> _OrderOffer:
        return cls(
            mail=offer.mail.digest,
            activities=offer.activities,
            successful=offer.verdict.value,
            worker=offer.worker,
            order_day=offer.order_day,
        )

    def offer(self, number: OrderNumber) -> Offer:
        """Oferta przy zleceniu ``number``."""

        return Offer(
            MailId(self.mail), Login(self.worker), self.order_day, number, Verdict(self.successful), self.activities, self.order_day
        )


class _Order(_Record):
    number: str
    successful: str | None
    activities: str | None
    reported: bool
    codes: list[str] | None = None
    faulty: bool = False
    request: _OrderOffer | None = None


class _Worker(_WorkerV1):
    orders_detail: list[_Order]
    mistaken: list[date] = []
    overtaken: list[str] = []


class _FaultySubject(_Record):
    subject: str
    fault: str
    day: date | None
    arrived: datetime
    mail: str | None = None


class _Offer(_Record):
    """Wpis na życzenie przy problemie: Wpis, przy którym tata klika (skrót maila, Wykonawca, dzień, numer, czynności),
    i co się wpisze (``successful`` z tymi czynnościami do zlecenia z dnia ``order_day``)."""

    mail: str
    worker: str
    day: date
    number: str
    activities: str
    successful: Literal["tak", "nie"]
    order_day: date

    @classmethod
    def of(cls, offer: Offer) -> _Offer:
        return cls(
            mail=offer.mail.digest,
            worker=offer.worker,
            day=offer.day,
            number=offer.number,
            activities=offer.activities,
            successful=offer.verdict.value,
            order_day=offer.order_day,
        )

    def offer(self) -> Offer:
        key = MailId(self.mail), Login(self.worker), self.day, OrderNumber(self.number)
        return Offer(*key, Verdict(self.successful), self.activities, self.order_day)


class _Problem(_Record):
    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: _Kept | None
    request: _Offer | None = None
    faulty_subject: _FaultySubject | None = None


class _Note(_Record):
    day: date
    worker: str
    number: str
    text: str


class _ResultV1(_Record):
    """Plik wyniku sprzed zleceń dnia: czyta go tylko ``shown``."""

    schema_version: Literal[1]
    clicked_at: datetime
    days: list[date]
    workers: list[_WorkerV1]
    problems: list[_Problem]


class _ResultV2(_Record):
    """Plik wyniku sprzed informacji o Przeniesieniach: czyta go tylko ``shown``."""

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
    INTERMAX (``None``: plik wyniku sprzed zleceń dnia), dni z tematu raportów z pomylonym tematem za ten dzień i zdania o
    raportach z błędem tematu za ten dzień, z których nie ma już czego wpisać (``overtaken``)."""

    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: tuple[str, ...]
    orders_detail: tuple[OrderDetail, ...] | None
    mistaken: tuple[date, ...]
    overtaken: tuple[str, ...]


@dataclass(frozen=True)
class ShownFaultySubject:
    """Raport z błędem tematu przy problemie: temat po strażniku reguły danych, rodzaj błędu, dzień, za który Centrum go
    liczy (``None``: problem bez dnia), chwila przyjścia maila i jego skrót, po którym z Wykonawcą problemu widok
    znajduje Wpisy na życzenie tego raportu przy zleceniach (``None``: plik wyniku sprzed Wpisu na życzenie raportu z
    błędem tematu)."""

    subject: str
    fault: str
    day: date | None
    arrived: datetime
    mail: str | None = None


@dataclass(frozen=True)
class ShownProblem:
    """Problem z ostatniego kliknięcia w widoku Raporty: dzień i Wykonawca, przy którym stoi (``None``: nieznany
    nadawca), numer zlecenia, jeśli problem go ma, zdanie dla taty, adres nieznanego nadawcy, komórka różnicy z ręczną
    wartością, przy której tata może kliknąć „Zostaw moją”, przy raporcie z błędem tematu jego temat, rodzaj błędu,
    dzień i chwila przyjścia (``faulty_subject``) i Wpis na życzenie, który tata może kliknąć (``request``)."""

    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: Kept | None
    faulty_subject: ShownFaultySubject | None
    request: Offer | None = None


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

    def offers(self) -> dict[str, Offer]:
        """Każdy Wpis na życzenie, który tata może kliknąć, przy problemie i przy zleceniu dnia, po jego tożsamości
        (``Offer.token``)."""

        at_orders = (order.request for worker in self.workers for order in worker.orders_detail or ())
        found = (*(problem.request for problem in self.problems), *at_orders)
        return {offer.token: offer for offer in found if offer is not None}


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
    „Zostaw moją”, oraz pamięć reguły danych pracy Centrum (``forbidden``), przez której strażnika temat raportu z
    błędem tematu trafia do pliku wyniku. Decyzje zapisuje ``keep`` pod blokadą, więc dwa kliknięcia „Zostaw moją” naraz
    nie gubią żadnej."""

    memory: _TextFile
    result: _TextFile
    decisions: _TextFile
    forbidden: ForbiddenValues
    _deciding: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def of_work(cls, work: CentrumWork) -> FileReportState:
        def file(name: str, where: str, unreadable: type[Exception] = StateUnreadable) -> _TextFile:
            return _TextFile(StateFile(work.config / name, work.log, where=where, pause=work.pause), unreadable)

        return cls(
            file(REPORT_ENTERING_STATE, "pamięć Wpisania raportów"),
            file(REPORT_ENTERING_RESULT, "wynik Wpisania raportów"),
            file(REPORT_ENTERING_DECISIONS, "decyzje „Zostaw moją”", DecisionsUnreadable),
            work.forbidden,
        )

    def load(self) -> SavedState:
        """Pamięć i decyzje „Zostaw moją”: najpierw cała pamięć (``StateUnreadable``), potem decyzje
        (``DecisionsUnreadable``), więc błąd decyzji znaczy, że pamięć jest poprawna. Pamięć z pliku sprzed wersji 4 to
        ``OlderOwnEntries``."""

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
                    move.added,
                )
                for move in (state.moves if isinstance(state, _StateV3 | _State) else ())
            )
            memory = OwnEntries(entries, moves)
        except (ValidationError, ValueError) as error:
            raise StateUnreadable from error
        requested = frozenset(found.decision() for found in (state.requested if isinstance(state, _State) else ()))
        return SavedState(
            state.rollout, memory if isinstance(state, _State) else OlderOwnEntries(memory), self.kept(), requested
        )

    def save_memory(
        self, written: CellsWritten, rollout: date, memory: OwnEntries, requested: frozenset[RequestedEntry]
    ) -> bool:
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
                added=move.added,
            )
            for move in sorted(memory.moves, key=lambda move: (move.day, move.number))
        ]
        decisions = [
            _Requested.of(decision)
            for decision in sorted(
                requested,
                key=lambda decision: (decision.day, decision.worker, decision.number, decision.mail.digest, decision.at),
            )
        ]
        return self.memory.write(
            _State(schema_version=_STATE_VERSION, rollout=rollout, own=own, moves=moves, requested=decisions)
        )

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
                        codes=None if order.codes is None else list(order.codes),
                        faulty=order.faulty,
                        request=None if order.request is None else _OrderOffer.of(order.request),
                    )
                    for order in worker.orders_detail
                ],
                mistaken=list(worker.mistaken),
                overtaken=[
                    overtaken(found, guarded(self.forbidden, found.subject.shown(), "temat Raportu wykonawcy").text)
                    for found in worker.overtaken
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
                problems=[_problem(problem, self.forbidden) for problem in result.problems],
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
                    tuple(worker.mistaken) if isinstance(worker, _Worker) else (),
                    tuple(worker.overtaken) if isinstance(worker, _Worker) else (),
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
                    None
                    if (faulty := problem.faulty_subject) is None
                    else ShownFaultySubject(faulty.subject, faulty.fault, faulty.day, faulty.arrived, faulty.mail),
                    None if problem.request is None else problem.request.offer(),
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
        OrderDetail(
            OrderNumber(order.number),
            order.successful,
            order.activities,
            order.reported,
            None if order.codes is None else tuple(order.codes),
            order.faulty,
            None if order.request is None else order.request.offer(OrderNumber(order.number)),
        )
        for order in worker.orders_detail
    )


def _note(found: ReportNote) -> _Note:
    """Informacja w pliku wyniku: dzień i Wykonawca kafelka, numer zlecenia i zdanie dla taty, bez treści maili."""

    return _Note(day=found.day, worker=found.worker, number=found.number, text=note(found))


def _problem(problem: ReportProblem, forbidden: ForbiddenValues) -> _Problem:
    """Problem w pliku wyniku: miejsce w widoku Raporty, numer zlecenia, zdanie dla taty, przy nieznanym nadawcy jego
    adres, a przy raporcie z błędem tematu jego temat po strażniku reguły danych (jedyne miejsca, do których trafiają,
    ADR 0028 i ADR 0041), rodzaj błędu, dzień, za który Centrum go liczy, i chwila przyjścia maila."""

    said = reason(problem)
    match problem:
        case UnreadableSubject(mail=mail, worker=worker, arrived=arrived, fault=fault, subject=subject, day=day):
            shown = guarded(forbidden, subject.shown(), "temat Raportu wykonawcy").text
            found = _FaultySubject(subject=shown, fault=subject_fault(fault), day=day, arrived=arrived, mail=mail.digest)
            return _Problem(
                day=day or arrived.date(),
                worker=worker,
                number=None,
                reason=said,
                sender=None,
                difference=None,
                faulty_subject=found,
            )
        case UnknownSender(sender=sender, day=day):
            return _Problem(day=day, worker=None, number=None, reason=said, sender=sender.shown(), difference=None)
        case MissingVerdict(offer=offer) if offer is not None:
            return _Problem(
                day=problem.day,
                worker=problem.worker,
                number=problem.number,
                reason=said,
                sender=None,
                difference=None,
                request=_Offer.of(offer),
            )
        case MissingVerdict() | ConflictingVerdicts() | UnknownNumber() | RepeatedOrder() | RepeatedNumber() | FaultyDescription():
            return _Problem(
                day=problem.day, worker=problem.worker, number=problem.number, reason=said, sender=None, difference=None
            )
        case RefusedMove(worker=worker, number=number):
            return _Problem(day=problem.shown, worker=worker, number=number, reason=said, sender=None, difference=None)
        case ManualDifference(key=key, column=column, reported=reported):
            difference = _Kept.of(Kept(key, column, reported))
            return _Problem(
                day=key.day, worker=key.worker, number=key.number, reason=said, sender=None, difference=difference
            )
        case _:
            assert_never(problem)
