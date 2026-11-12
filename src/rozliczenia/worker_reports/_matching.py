"""Dopasowanie Wpisów raportu do zleceń (ADR 0029): jedyne zlecenie numeru w odczytanych dniach u nadawcy w dniu z
tematu, u innego Wykonawcy w tym dniu (Przeniesienie zlecenia) albo z innego dnia (Przeniesienie na dzień z tematu albo
pomylony temat); numer w kilku zleceniach tylko do zlecenia nadawcy z dnia z tematu, bez Przeniesienia; przy kilku
Wpisach najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
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
    informacja o przegranym temacie, gdy to Wpis pomylonego tematu; ``refused``: Przeniesienie, do którego nie wolno,
    więc ten Wpis, gdy jest najpóźniejszy, niczego nie zmienia."""

    order: RegisterOrder
    day: date
    report: ReadReport
    entries: tuple[ReportEntry, ...]
    lost: SubjectLost | None
    refused: RefusedMove | None = None


class Board:
    """Zlecenia kliknięcia do dopasowania: każde zlecenie, które proces odczytał z INTERMAX (``orders``: dni od
    ``Window.start``, zamknięte, otwarte i po dziś), z dniem i Wykonawcą sprzed Przeniesień Centrum, Przeniesienia z
    pamięci i Dni uporządkowane. Które numery są w INTERMAX i ile mają zleceń, mówią wszystkie odczytane dni; okno mówi
    tylko, do których zleceń wolno pisać i które przenosić (dni otwarte).

    Dzień i Wykonawca sprzed Przeniesień Centrum sprawiają, że Wpis liczy się do progu pomylonego tematu tak samo przed
    Przeniesieniem i po nim, więc kolejne kliknięcia dają to samo co jedno. Miejsce zmienia tylko jedyne zlecenie
    numeru w odczytanych dniach, a czy Wpis może zmienić jego dzień albo Wykonawcę, mówi reguła ``may_move`` dla pamięci
    tego numeru (``_movable``); gdy nie może, nic się nie dzieje, bez problemu (ADR 0029 „Ręczna zmiana dalej
    wygrywa”). Numer w kilku zleceniach odczytanych dni, także z dniem zamkniętym albo po dziś, nie zmienia miejsca
    żadnego z nich (``_repeated``), bo Excel nie mówi, które z nich tata przeniósł, więc pamięć numeru nie wie, do
    którego należy.
    """

    def __init__(
        self, orders: Sequence[RegisterOrder], memory: OwnEntries, window: Window, ordered_days: frozenset[OrderedDay]
    ) -> None:
        self._memory = tuple(move for move in memory.moves if window.opens(move.day))
        standing = {OrderKey(move.number, move.day, move.worker): move for move in self._memory}
        self._numbered: defaultdict[OrderNumber, list[_Placed]] = defaultdict(list)
        for order in orders:
            place = standing.get(order.key)
            day, worker = (order.key.day, order.key.worker) if place is None else (place.origin_day, place.origin_worker)
            self._numbered[order.key.number].append(_Placed(order, day, worker))
        self._window = window
        self._ordered = ordered_days
        self._ordered_anywhere = frozenset(found.day for found in ordered_days)

    def match(self, reports: Iterable[ReadReport]) -> Matched:
        """Zlecenie i zwycięski Wpis dla każdego zlecenia z Wpisami oraz problemy Wpisów bez jednego zlecenia.

        ``reports`` idą w kolejności przyjścia, więc późniejszy mail zastępuje Wpisy wcześniejszego, także mail innego
        Wykonawcy i mail z innym dniem z tematu. Wpis każdego numeru Raportu wykonawcy z dniem z tematu D jest zgodny,
        gdy zlecenie tego numeru stoi w dniu D, niezgodny, gdy stoi tylko w innych odczytanych dniach (otwartych,
        zamkniętych albo po dziś), a nieznany, gdy nie ma go nigdzie (``UnknownNumber``). Numer z jednym zleceniem:
        zgodny Wpis trafia do niego, u nadawcy albo u innego Wykonawcy z dnia D (Przeniesienie zlecenia, ``_same_day``),
        a niezgodny Wpis trafia do niego w innym dniu otwartym: jeden niezgodny Wpis w raporcie przenosi je na dzień D,
        a co najmniej ``MISTAKEN_SUBJECT`` to pomylony temat i zlecenie zostaje w swoim dniu, z informacją
        ``SubjectLost`` (``_other_day``); Wykonawca zmienia się na nadawcę zawsze. Jedyne zlecenie z dnia zamkniętego
        albo po dziś Wpis nie zmienia (``RefusedMove``). Numer z kilkoma zleceniami trafia tylko do jedynego zlecenia
        nadawcy w dniu D, bez Przeniesienia, a inaczej daje ``RepeatedOrder`` albo ``RepeatedNumber`` (``_repeated``);
        liczy się do progu jak każdy niezgodny Wpis. Raport z dniem D w okresie z Plikiem zbiorczym daje tylko
        niezgodne Wpisy: pomylony temat wpisuje się do zleceń z ich dnia, a jeden Wpis to ``RefusedMove``. Zwycięski
        Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict`` zamiast celu, bo nie wiadomo, co Wykonawca miał na myśli,
        zwycięski mail z Wpisami numeru o przeciwnym zamiarze (``_entries.entries``) to ``ConflictingVerdicts``, a
        zwycięski Wpis z Przeniesieniem, do którego nie wolno, to ``RefusedMove``; we wszystkich zlecenie zostaje, gdzie
        stoi, a wcześniejszy mail go nie zmienia. Tak samo przy odmowie, bo Dzień uporządkowany przestaje nim być, gdy
        Przeniesienie Centrum zabierze z niego ostatnie zlecenie, a powtórne kliknięcie ma nic nie zmienić.
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
                    latest[found.order.row] = replace(found, entries=tuple(written))
                else:
                    problems += found
        targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]] = {}
        accepted: list[tuple[RegisterOrder, Login, date, datetime]] = []
        lost: list[SubjectLost] = []
        for claim in latest.values():
            order, report = claim.order, claim.report
            shown = report.day if self._window.opens(report.day) else claim.day
            if claim.refused is not None:
                problems.append(claim.refused)
                continue
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
        """Numer, którego zlecenia nie ma w dniu ``day`` (dzień sprzed Przeniesień Centrum), a jest w innym odczytanym
        dniu."""

        placed = self._numbered.get(number, [])
        return bool(placed) and all(found.day != day for found in placed)

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
        """Niezgodny Wpis: jedyne zlecenie numeru z innego dnia. Pomylony temat (``mistaken``) zostawia je w jego dniu,
        jeden niezgodny Wpis przenosi je na dzień z tematu. Zlecenia z dnia zamkniętego albo po dziś Wpis nie zmienia:
        ``RefusedMove`` przy raporcie z dniem otwartym, z dnia zamkniętego tylko przy jednym niezgodnym Wpisie (pomylony
        temat zostawia je w zamkniętym okresie bez problemu), a z dnia po dziś zawsze, bo tata ma je przed sobą. Raport
        z dniem zamkniętym nie daje innych problemów niż ``RefusedMove``, bo jego dnia tata nie widzi."""

        [found] = placed
        opens = self._window.opens(report.day)
        order_day = found.order.key.day
        if not self._window.opens(order_day):
            closed = order_day <= self._window.today
            if not opens or (mistaken and closed):
                return []
            bar = MoveBar.CLOSED_SOURCE if closed else MoveBar.AFTER_TODAY
            return [RefusedMove(report.worker, report.day, number, order_day, order_day, bar)]
        if not mistaken:
            return self._claim(found, report, report.day, None)
        shown = report.day if opens else found.day
        return self._claim(found, report, found.day, SubjectLost(shown, report.worker, number, found.day))

    def _repeated(self, report: ReadReport, number: OrderNumber, placed: Sequence[_Placed]) -> _Claim | list[ReportProblem]:
        """Numer w kilku zleceniach odczytanych dni: Wpis z dniem otwartym trafia tylko do jedynego zlecenia nadawcy,
        które INTERMAX ma w dniu z tematu, bez Przeniesienia. Kilka takich zleceń to ``RepeatedOrder``, a żadne to
        ``RepeatedNumber`` z miejscem każdego zlecenia numeru; raport z dniem zamkniętym nic nie zmienia i nie daje
        problemu, bo jego dnia tata nie widzi."""

        if not self._window.opens(report.day):
            return []
        here = [found for found in placed if (found.order.key.day, found.order.key.worker) == (report.day, report.worker)]
        if len(here) == 1:
            return _Claim(here[0].order, report.day, report, (), None)
        if here:
            return [RepeatedOrder(report.worker, report.day, number)]
        places = tuple(sorted((found.order.key.day, found.order.key.worker) for found in placed))
        return [RepeatedNumber(report.worker, report.day, number, places)]

    def _claim(self, found: _Placed, report: ReadReport, day: date, lost: SubjectLost | None) -> _Claim | list[ReportProblem]:
        """Wpis stawia zlecenie ``found`` w dniu ``day`` u nadawcy, gdy wolno: bez zmiany miejsca zawsze, a ze zmianą
        tylko zlecenie bez ręcznej zmiany taty po Przeniesieniu Centrum (inaczej Wpis się nie liczy, tabela przejść
        #1358) i tylko do Dnia uporządkowanego arkusza zlecenia poza okresem z Plikiem zbiorczym (inaczej Wpis liczy się
        z odmową ``RefusedMove``)."""

        order = found.order
        if (day, report.worker) == (order.key.day, order.key.worker):
            return _Claim(order, day, report, (), lost)
        if not self._movable(order, report):
            return []
        bar = None if day == order.key.day else self._bar(order, day)
        refused = None if bar is None else RefusedMove(report.worker, report.day, order.key.number, order.key.day, day, bar)
        return _Claim(order, day, report, (), lost, refused)

    def _movable(self, order: RegisterOrder, report: ReadReport) -> bool:
        """Czy Wpis ``report`` może zmienić Wykonawcę albo dzień jedynego zlecenia numeru ``order``: ``may_move`` z
        pamięcią jego numeru (``memories_of``)."""

        key = order.key
        return may_move(memories_of(self._memory, key.number), key.worker, key.day, report.arrived)

    def _bar(self, order: RegisterOrder, day: date) -> MoveBar | None:
        if not self._window.opens(day):
            return MoveBar.CLOSED_TARGET
        if OrderedDay(order.row.sheet, day) in self._ordered:
            return None
        return MoveBar.OTHER_SHEET if day in self._ordered_anywhere else MoveBar.NOT_ORDERED
