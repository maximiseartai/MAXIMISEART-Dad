"""Dopasowanie Wpisów raportu do zleceń (ADR 0029): jedyne zlecenie numeru w dniach otwartych u nadawcy w dniu z tematu,
u innego Wykonawcy w tym dniu (Przeniesienie zlecenia) albo z innego dnia (Przeniesienie na dzień z tematu albo pomylony
temat); numer w kilku zleceniach tylko do zlecenia nadawcy z dnia z tematu, bez Przeniesienia; przy kilku Wpisach
najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..report_cells import OrderRow
from ._model import (
    ConflictingVerdicts,
    Login,
    MissingVerdict,
    MoveBar,
    OrderedDay,
    OrderKey,
    OrderNumber,
    OwnEntries,
    ReadReport,
    RefusedMove,
    RegisterOrder,
    RepeatedNumber,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    SubjectLost,
    UnknownNumber,
    VerdictFault,
    Window,
    may_move,
    memories_of,
)

MISTAKEN_SUBJECT = 2
"""Od tylu niezgodnych Wpisów w jednym Raporcie wykonawcy temat jest pomylony, a wygrywa dzień z INTERMAX (ADR 0029)."""


@dataclass(frozen=True)
class Matched:
    """Wynik dopasowania: zwycięski Wpis każdego zlecenia po kluczu, który zlecenie ma po kliknięciu (``targets``),
    zlecenie każdego zwycięskiego Wpisu z nadawcą, dniem po kliknięciu i chwilą przyjścia maila (``accepted``; zlecenie
    w innym miejscu przechodzi do nadawcy i na ten dzień), problemy
    Wpisów bez jednego zlecenia i informacje o przegranym temacie zwycięskich Wpisów (``lost``)."""

    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]]
    accepted: tuple[tuple[RegisterOrder, Login, date, datetime], ...]
    problems: list[ReportProblem]
    lost: tuple[SubjectLost, ...]


@dataclass(frozen=True)
class _Placed:
    """Zlecenie z dniem i Wykonawcą sprzed Przeniesień Centrum (``day``, ``worker``): z pamięci, gdy INTERMAX ma je tam,
    gdzie postawiło je Centrum, a inaczej z INTERMAX."""

    order: RegisterOrder
    day: date
    worker: Login


@dataclass(frozen=True)
class _Claim:
    """Wpisy ``entries`` Raportu wykonawcy ``report`` stawiają zlecenie ``order`` w dniu ``day`` u nadawcy; ``lost``:
    informacja o przegranym temacie, gdy to Wpis pomylonego tematu."""

    order: RegisterOrder
    day: date
    report: ReadReport
    entries: tuple[ReportEntry, ...]
    lost: SubjectLost | None


class Board:
    """Zlecenia kliknięcia do dopasowania: zlecenia dni otwartych (``orders``) z dniem i Wykonawcą sprzed Przeniesień
    Centrum, numery zleceń dni zamkniętych z ``Window.start`` (``closed``), Przeniesienia z pamięci i Dni uporządkowane.

    Dzień i Wykonawca sprzed Przeniesień Centrum sprawiają, że Wpis liczy się do progu pomylonego tematu tak samo przed
    Przeniesieniem i po nim, więc kolejne kliknięcia dają to samo co jedno. Miejsce zmienia tylko jedyne zlecenie
    numeru w dniach otwartych, a czy Wpis może zmienić jego dzień albo Wykonawcę, mówi reguła ``may_move`` dla każdej
    pamięci tego numeru (``_movable``); gdy nie może, nic się nie dzieje, bez problemu (ADR 0029 „Ręczna zmiana dalej
    wygrywa”). Numer w kilku zleceniach dni otwartych nie zmienia miejsca żadnego z nich (``_repeated``), bo Excel nie
    mówi, które z nich tata przeniósł, więc pamięć numeru nie wie, do którego należy.
    """

    def __init__(
        self,
        orders: Sequence[RegisterOrder],
        closed: Iterable[RegisterOrder],
        memory: OwnEntries,
        window: Window,
        ordered_days: frozenset[OrderedDay],
    ) -> None:
        self._memory = tuple(move for move in memory.moves if window.opens(move.day))
        standing = {OrderKey(move.number, move.day, move.worker): move for move in self._memory}
        self._numbered: defaultdict[OrderNumber, list[_Placed]] = defaultdict(list)
        for order in orders:
            place = standing.get(order.key)
            day, worker = (order.key.day, order.key.worker) if place is None else (place.origin_day, place.origin_worker)
            self._numbered[order.key.number].append(_Placed(order, day, worker))
        self._closed: defaultdict[OrderNumber, set[date]] = defaultdict(set)
        for order in closed:
            self._closed[order.key.number].add(order.key.day)
        self._window = window
        self._ordered = ordered_days
        self._ordered_anywhere = frozenset(found.day for found in ordered_days)

    def match(self, reports: Iterable[ReadReport]) -> Matched:
        """Zlecenie i zwycięski Wpis dla każdego zlecenia z Wpisami oraz problemy Wpisów bez jednego zlecenia.

        ``reports`` idą w kolejności przyjścia, więc późniejszy mail zastępuje Wpisy wcześniejszego, także mail innego
        Wykonawcy i mail z innym dniem z tematu. Wpis każdego numeru Raportu wykonawcy z dniem z tematu D jest zgodny,
        gdy zlecenie tego numeru stoi w dniu D, niezgodny, gdy stoi tylko w innych dniach (otwartych albo zamkniętych z
        ``closed``), a nieznany, gdy nie ma go nigdzie (``UnknownNumber``). Numer z jednym zleceniem w dniach otwartych:
        zgodny Wpis trafia do niego, u nadawcy albo u innego Wykonawcy z dnia D (Przeniesienie zlecenia, ``_same_day``),
        a niezgodny Wpis trafia do niego w innym dniu: jeden niezgodny Wpis w raporcie przenosi je na dzień D, a co
        najmniej ``MISTAKEN_SUBJECT`` to pomylony temat i zlecenie zostaje w swoim dniu, z informacją ``SubjectLost``
        (``_other_day``); Wykonawca zmienia się na nadawcę zawsze. Numer z kilkoma zleceniami w dniach otwartych trafia
        tylko do jedynego zlecenia nadawcy w dniu D, bez Przeniesienia, a inaczej daje ``RepeatedOrder`` albo
        ``RepeatedNumber`` (``_repeated``); liczy się do progu jak każdy niezgodny Wpis. Raport z dniem D w okresie z
        Plikiem zbiorczym daje tylko niezgodne Wpisy: pomylony temat wpisuje się do zleceń z ich dnia, a jeden Wpis
        to ``RefusedMove``. Zwycięski Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict`` zamiast celu, bo nie wiadomo,
        co Wykonawca miał na myśli, a zwycięski mail z Wpisami numeru o przeciwnym zamiarze (``_entries.entries``) to
        ``ConflictingVerdicts``; w obu zlecenie zostaje, gdzie stoi.
        """

        latest: dict[OrderRow, _Claim] = {}
        problems: list[ReportProblem] = []
        for report in reports:
            said: dict[OrderNumber, list[ReportEntry]] = {}
            for entry in report.entries:
                said.setdefault(entry.number, []).append(entry)
            other_day = [number for number in said if self._other_day_number(number, report.day)]
            mistaken = len(other_day) >= MISTAKEN_SUBJECT
            for number, written in said.items():
                placed = self._numbered.get(number, [])
                if number not in other_day and not self._window.opens(report.day):
                    continue
                if len(placed) > 1:
                    found = self._repeated(report, number, placed)
                elif number in other_day:
                    found = self._other_day(report, number, placed, mistaken)
                else:
                    found = self._same_day(report, number, placed)
                if isinstance(found, _Claim):
                    latest[found.order.row] = _Claim(found.order, found.day, report, tuple(written), found.lost)
                else:
                    problems += found
        targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]] = {}
        accepted: list[tuple[RegisterOrder, Login, date, datetime]] = []
        lost: list[SubjectLost] = []
        for claim in latest.values():
            order, report = claim.order, claim.report
            shown = report.day if self._window.opens(report.day) else claim.day
            match claim.entries:
                case (ReportEntry(fault=None) as entry,):
                    targets[OrderKey(order.key.number, claim.day, report.worker)] = (order, entry)
                    accepted.append((order, report.worker, claim.day, report.arrived))
                    if claim.lost is not None:
                        lost.append(claim.lost)
                case (ReportEntry(fault=VerdictFault() as fault),):
                    problems.append(MissingVerdict(report.worker, shown, order.key.number, fault))
                case _:
                    problems.append(
                        ConflictingVerdicts(
                            report.worker, shown, order.key.number, report.mail, report.arrived, claim.entries
                        )
                    )
        return Matched(targets, tuple(accepted), problems, tuple(lost))

    def _other_day_number(self, number: OrderNumber, day: date) -> bool:
        """Numer, którego zlecenia nie ma w dniu ``day`` (dzień sprzed Przeniesień Centrum), a jest w innym dniu."""

        placed = self._numbered.get(number, [])
        if any(found.day == day for found in placed) or day in self._closed.get(number, ()):
            return False
        return bool(placed) or bool(self._closed.get(number))

    def _same_day(self, report: ReadReport, number: OrderNumber, placed: Sequence[_Placed]) -> _Claim | list[ReportProblem]:
        """Zgodny Wpis z dniem otwartym: jedyne zlecenie numeru, u nadawcy albo u innego Wykonawcy z tego dnia
        (Przeniesienie zlecenia), a numer bez zlecenia to ``UnknownNumber``."""

        match placed:
            case [found]:
                return self._claim(found, report, report.day, None)
            case _:
                return [UnknownNumber(report.worker, report.day, number)]

    def _other_day(
        self, report: ReadReport, number: OrderNumber, placed: Sequence[_Placed], mistaken: bool
    ) -> _Claim | list[ReportProblem]:
        """Niezgodny Wpis: jedyne zlecenie numeru z innego dnia otwartego. Pomylony temat (``mistaken``) zostawia je w
        jego dniu, jeden niezgodny Wpis przenosi je na dzień z tematu. Numer tylko w dniach zamkniętych to
        ``RefusedMove`` z ``CLOSED_SOURCE`` przy jednym niezgodnym Wpisie z dniem otwartym, a inaczej nic, bo okres z
        Plikiem zbiorczym jest zamknięty. Raport z dniem zamkniętym nie daje innych problemów niż ``RefusedMove``, bo
        jego dnia tata nie widzi."""

        opens = self._window.opens(report.day)
        match placed:
            case [found]:
                if not mistaken:
                    return self._claim(found, report, report.day, None)
                shown = report.day if opens else found.day
                return self._claim(found, report, found.day, SubjectLost(shown, report.worker, number, found.day))
            case _:
                if mistaken or not opens:
                    return []
                return [RefusedMove(report.worker, report.day, number, min(self._closed[number]), MoveBar.CLOSED_SOURCE)]

    def _repeated(self, report: ReadReport, number: OrderNumber, placed: Sequence[_Placed]) -> _Claim | list[ReportProblem]:
        """Numer w kilku zleceniach dni otwartych: Wpis trafia tylko do jedynego zlecenia nadawcy, które INTERMAX ma w
        dniu z tematu, bez Przeniesienia. Kilka takich zleceń to ``RepeatedOrder``, a żadne to ``RepeatedNumber`` z
        miejscem każdego zlecenia numeru; raport z dniem zamkniętym nie daje problemu, bo jego dnia tata nie widzi."""

        here = [found for found in placed if (found.order.key.day, found.order.key.worker) == (report.day, report.worker)]
        if len(here) == 1:
            return _Claim(here[0].order, report.day, report, (), None)
        if not self._window.opens(report.day):
            return []
        if here:
            return [RepeatedOrder(report.worker, report.day, number)]
        places = tuple(sorted((found.order.key.day, found.order.key.worker) for found in placed))
        return [RepeatedNumber(report.worker, report.day, number, places)]

    def _claim(self, found: _Placed, report: ReadReport, day: date, lost: SubjectLost | None) -> _Claim | list[ReportProblem]:
        """Wpis stawia zlecenie ``found`` w dniu ``day`` u nadawcy, gdy wolno: bez zmiany miejsca zawsze, a ze zmianą
        tylko zlecenie bez ręcznej zmiany taty po Przeniesieniu Centrum (inaczej nic) i tylko do Dnia uporządkowanego
        arkusza zlecenia poza okresem z Plikiem zbiorczym (inaczej ``RefusedMove``)."""

        order = found.order
        if (day, report.worker) == (order.key.day, order.key.worker):
            return _Claim(order, day, report, (), lost)
        if not self._movable(order, report):
            return []
        if day != order.key.day:
            bar = self._bar(order, day)
            if bar is not None:
                return [RefusedMove(report.worker, report.day, order.key.number, order.key.day, bar)]
        return _Claim(order, day, report, (), lost)

    def _movable(self, order: RegisterOrder, report: ReadReport) -> bool:
        """Czy Wpis ``report`` może zmienić Wykonawcę albo dzień jedynego zlecenia numeru ``order``: ``may_move`` dla
        każdej pamięci tego zlecenia (``memories_of``), a gdy jej nie ma, ``may_move`` bez pamięci."""

        key = order.key
        found = memories_of(self._memory, key, alone=True)
        return all(may_move(memory, key.worker, key.day, report.arrived) for memory in found or (None,))

    def _bar(self, order: RegisterOrder, day: date) -> MoveBar | None:
        if not self._window.opens(day):
            return MoveBar.CLOSED_TARGET
        if OrderedDay(order.row.sheet, day) in self._ordered:
            return None
        return MoveBar.OTHER_SHEET if day in self._ordered_anywhere else MoveBar.NOT_ORDERED
