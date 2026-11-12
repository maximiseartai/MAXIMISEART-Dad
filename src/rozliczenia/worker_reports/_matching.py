"""Dopasowanie Wpisów raportu do zleceń (ADR 0029): zlecenie nadawcy z dnia z tematu, jedyne zlecenie tego numeru u
innego Wykonawcy w tym dniu (Przeniesienie zlecenia), jedyne zlecenie tego numeru z innego dnia (Przeniesienie na
dzień z tematu albo pomylony temat) albo, bez zlecenia tego numeru, Zlecenie dopisane z raportu, a przy kilku Wpisach
najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..report_cells import OrderRow
from ._model import (
    ADDED_DIGITS,
    AddBar,
    ConflictingVerdicts,
    ForeignOrder,
    Login,
    MailId,
    MissingVerdict,
    MoveBar,
    OrderedDay,
    OrderKey,
    OrderNumber,
    OtherDay,
    OwnEntries,
    ReadReport,
    RefusedMove,
    RegisterOrder,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    SubjectLost,
    UnknownNumber,
    Verdict,
    VerdictFault,
    Window,
    may_move,
    memories_of,
)

MISTAKEN_SUBJECT = 2
"""Od tylu niezgodnych Wpisów w jednym Raporcie wykonawcy temat jest pomylony, a wygrywa dzień z INTERMAX (ADR 0029)."""


@dataclass(frozen=True)
class Addition:
    """Zwycięski Wpis numeru ``number``, którego INTERMAX nie ma, z ``tak``/``nie`` ``verdict`` i czynnościami
    ``activities``, od Wykonawcy ``worker`` z dniem z tematu ``day``, z maila ``mail``, który przyszedł ``arrived``:
    Zlecenie dopisane z raportu w arkuszu zleceń ``sheet``."""

    sheet: str
    day: date
    worker: Login
    number: OrderNumber
    verdict: Verdict
    activities: str
    arrived: datetime
    mail: MailId


@dataclass(frozen=True)
class Matched:
    """Wynik dopasowania: zwycięski Wpis każdego zlecenia po kluczu, który zlecenie ma po kliknięciu (``targets``),
    zlecenie każdego zwycięskiego Wpisu z nadawcą, dniem po kliknięciu i chwilą przyjścia maila (``accepted``; zlecenie
    w innym miejscu przechodzi do nadawcy i na ten dzień), Zlecenia dopisane z raportu (``added``, po numerze), problemy
    Wpisów bez jednego zlecenia i informacje o przegranym temacie zwycięskich Wpisów (``lost``)."""

    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]]
    accepted: tuple[tuple[RegisterOrder, Login, date, datetime], ...]
    problems: list[ReportProblem]
    lost: tuple[SubjectLost, ...]
    added: tuple[Addition, ...]


@dataclass(frozen=True)
class _Placed:
    """Zlecenie z dniem i Wykonawcą sprzed Przeniesień Centrum (``day``, ``worker``): z pamięci, gdy INTERMAX ma je tam,
    gdzie postawiło je Centrum, a inaczej z INTERMAX."""

    order: RegisterOrder
    day: date
    worker: Login


@dataclass(frozen=True)
class _New:
    """Wpisy ``entries`` Raportu wykonawcy ``report`` dopisują numer ``number`` w arkuszu zleceń ``sheet``."""

    sheet: str
    number: OrderNumber
    report: ReadReport
    entries: tuple[ReportEntry, ...]


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
    Centrum, numery zleceń dni zamkniętych z ``Window.start`` (``closed``), Przeniesienia z pamięci, Dni uporządkowane i
    numery Surowych zleceń (``pasted``).

    Dzień i Wykonawca sprzed Przeniesień Centrum sprawiają, że Wpis liczy się do progu pomylonego tematu tak samo przed
    Przeniesieniem i po nim, więc kolejne kliknięcia dają to samo co jedno. Czy Wpis może zmienić dzień albo Wykonawcę
    zlecenia, mówi reguła ``may_move`` dla pamięci zlecenia (``_movable``), a czy może dopisać numer, którego INTERMAX
    już nie ma, ta sama reguła dla każdej pamięci tego numeru (``_addable``); gdy nie może, nic się nie dzieje, bez
    problemu (ADR 0029 „Ręczna zmiana dalej wygrywa”).
    """

    def __init__(
        self,
        orders: Sequence[RegisterOrder],
        closed: Iterable[RegisterOrder],
        memory: OwnEntries,
        window: Window,
        ordered_days: frozenset[OrderedDay],
        pasted: frozenset[OrderNumber] = frozenset(),
    ) -> None:
        self._memory = tuple(move for move in memory.moves if window.opens(move.day))
        self._pasted = pasted
        self._orders = tuple(orders)
        self._places = frozenset((order.key.number, order.key.day) for order in orders)
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
        ``closed``), a nieznany, gdy nie ma go nigdzie (``UnknownNumber``). Zgodny Wpis trafia do zlecenia nadawcy, a
        bez niego do jedynego zlecenia innego Wykonawcy z dnia D (Przeniesienie zlecenia), jak w ``_same_day``. Niezgodny
        Wpis trafia do jedynego zlecenia z innego dnia (najpierw zlecenia nadawcy): jeden niezgodny Wpis w raporcie
        przenosi je na dzień D, a co najmniej ``MISTAKEN_SUBJECT`` to pomylony temat i zlecenie zostaje w swoim dniu, z
        informacją ``SubjectLost`` (``_other_day``). Wykonawca zmienia się na nadawcę zawsze. Raport z dniem D w okresie
        z Plikiem zbiorczym daje tylko niezgodne Wpisy: pomylony temat wpisuje się do zleceń z ich dnia, a jeden Wpis
        to ``RefusedMove``. Zwycięski Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict`` zamiast celu, bo nie wiadomo,
        co Wykonawca miał na myśli, a zwycięski mail z Wpisami numeru o przeciwnym zamiarze (``_entries.entries``) to
        ``ConflictingVerdicts``; w obu zlecenie zostaje, gdzie stoi.

        Wpis numeru, którego nie ma w żadnym odczytanym dniu, z Raportu wykonawcy z dniem otwartym to Zlecenie dopisane
        z raportu (``_unknown``), a przy kilku takich Wpisach jednego numeru dopisuje najpóźniejszy mail, także od
        innego Wykonawcy i z innym dniem z tematu; jego Wpis bez ``tak`` ani ``nie`` daje ``MissingVerdict``, a z
        przeciwnym zamiarem ``ConflictingVerdicts``, bez dopisania.
        """

        latest: dict[OrderRow, _Claim] = {}
        newest: dict[OrderNumber, _New] = {}
        problems: list[ReportProblem] = []
        for report in reports:
            said: dict[OrderNumber, list[ReportEntry]] = {}
            for entry in report.entries:
                said.setdefault(entry.number, []).append(entry)
            other_day = [number for number in said if self._other_day_number(number, report.day)]
            mistaken = len(other_day) >= MISTAKEN_SUBJECT
            for number, written in said.items():
                found: _Claim | _New | list[ReportProblem]
                if number in other_day:
                    found = self._other_day(report, number, mistaken)
                elif not self._window.opens(report.day):
                    continue
                elif self._numbered.get(number):
                    found = self._same_day(report, number)
                else:
                    found = self._unknown(report, number, mistaken)
                if isinstance(found, _Claim):
                    latest[found.order.row] = _Claim(found.order, found.day, report, tuple(written), found.lost)
                elif isinstance(found, _New):
                    newest[number] = _New(found.sheet, number, report, tuple(written))
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
        added: list[Addition] = []
        for number, new in newest.items():
            report = new.report
            match new.entries:
                case (ReportEntry(verdict=Verdict() as verdict, activities=activities),):
                    added.append(
                        Addition(new.sheet, report.day, report.worker, number, verdict, activities, report.arrived, report.mail)
                    )
                case (ReportEntry(fault=VerdictFault() as fault),):
                    problems.append(MissingVerdict(report.worker, report.day, number, fault))
                case _:
                    problems.append(
                        ConflictingVerdicts(report.worker, report.day, number, report.mail, report.arrived, new.entries)
                    )
        return Matched(targets, tuple(accepted), problems, tuple(lost), tuple(added))

    def _other_day_number(self, number: OrderNumber, day: date) -> bool:
        """Numer, którego zlecenia nie ma w dniu ``day`` (dzień sprzed Przeniesień Centrum), a jest w innym dniu."""

        placed = self._numbered.get(number, [])
        if any(found.day == day for found in placed) or day in self._closed.get(number, ()):
            return False
        return bool(placed) or bool(self._closed.get(number))

    def _same_day(self, report: ReadReport, number: OrderNumber) -> _Claim | list[ReportProblem]:
        """Zgodny Wpis z dniem otwartym: zlecenie nadawcy z tego dnia (dwa to ``RepeatedOrder``), a bez niego jedyne
        zlecenie innego Wykonawcy z tego dnia, chyba że nadawca ma ten numer w innym dniu (``OtherDay``); kilka zleceń
        innych Wykonawców to ``ForeignOrder`` z każdym."""

        placed = self._numbered.get(number, [])
        same_day = [found for found in placed if found.day == report.day]
        own = [found for found in same_day if found.worker == report.worker]
        if len(own) > 1:
            return [RepeatedOrder(report.worker, report.day, number)]
        if own:
            return self._claim(own[0], report, report.day, None)
        own_days = sorted({found.day for found in placed if found.worker == report.worker})
        if own_days:
            return [OtherDay(report.worker, report.day, number, tuple(own_days))]
        if len(same_day) == 1:
            return self._claim(same_day[0], report, report.day, None)
        owners = sorted({found.worker for found in same_day})
        return [ForeignOrder(report.worker, report.day, number, owner) for owner in owners]

    def _unknown(self, report: ReadReport, number: OrderNumber, mistaken: bool) -> _New | list[ReportProblem]:
        """Wpis numeru, którego nie ma w żadnym odczytanym dniu, z Raportu wykonawcy z dniem otwartym: Zlecenie dopisane
        z raportu w arkuszu ``_sheet``, a gdy nie wolno, ``UnknownNumber`` z pierwszym powodem z ``AddBar`` (Surowe
        zlecenie, numer bez ``ADDED_DIGITS`` cyfr, pomylony temat, dzień, który nie jest Dniem uporządkowanym). Surowe
        zlecenie nie liczy się do progu pomylonego tematu, bo jego dnia rdzeń nie zna. Numer, który Centrum już
        dopisało albo zmieniło, a tata go usunął, wraca tylko z mailem, który ``may_move`` przyjmuje dla każdej pamięci
        tego numeru (świeższym niż ``since``); inaczej nic, bez problemu."""

        if number in self._pasted:
            bar = AddBar.PASTED
        elif len(number) != ADDED_DIGITS:
            bar = AddBar.FORM
        elif mistaken:
            bar = AddBar.MISTAKEN_SUBJECT
        elif (sheet := self._sheet(report)) is None:
            bar = AddBar.NOT_ORDERED
        elif self._addable(number, report):
            return _New(sheet, number, report, ())
        else:
            return []
        return [UnknownNumber(report.worker, report.day, number, bar)]

    def _sheet(self, report: ReadReport) -> str | None:
        """Arkusz zleceń dopisania: z arkuszy, w których dzień z tematu jest Dniem uporządkowanym, pierwszy po nazwie z
        zleceniem nadawcy w tym dniu, bez niego pierwszy z jakimkolwiek zleceniem tego dnia, a bez niego pierwszy;
        ``None``, gdy dzień nie jest Dniem uporządkowanym w żadnym arkuszu."""

        sheets = sorted({found.sheet for found in self._ordered if found.day == report.day})
        day = [order for order in self._orders if order.key.day == report.day and order.row.sheet in sheets]
        own = [order for order in day if order.key.worker == report.worker]
        chosen = sorted(order.row.sheet for order in own or day) or sheets
        return chosen[0] if chosen else None

    def _addable(self, number: OrderNumber, report: ReadReport) -> bool:
        found = [memory for memory in self._memory if memory.number == number]
        return all(may_move(memory, report.worker, report.day, report.arrived) for memory in found)

    def _other_day(self, report: ReadReport, number: OrderNumber, mistaken: bool) -> _Claim | list[ReportProblem]:
        """Niezgodny Wpis: jedyne zlecenie nadawcy z innego dnia otwartego, a bez niego jedyne zlecenie tego numeru;
        kilka to ``OtherDay`` ze wszystkimi ich dniami. Pomylony temat (``mistaken``) zostawia zlecenie w jego dniu,
        jeden niezgodny Wpis przenosi je na dzień z tematu. Numer tylko w dniach zamkniętych to ``RefusedMove`` z
        ``CLOSED_SOURCE`` przy jednym niezgodnym Wpisie z dniem otwartym, a inaczej nic, bo okres z Plikiem zbiorczym jest
        zamknięty. Raport z dniem zamkniętym nie daje innych problemów niż ``RefusedMove``, bo jego dnia tata nie widzi."""

        placed = self._numbered.get(number, [])
        own = [found for found in placed if found.worker == report.worker]
        candidates = own or placed
        opens = self._window.opens(report.day)
        if len(candidates) > 1:
            days = tuple(sorted({found.day for found in candidates}))
            return [OtherDay(report.worker, report.day, number, days)] if opens else []
        if not candidates:
            if mistaken or not opens:
                return []
            return [RefusedMove(report.worker, report.day, number, min(self._closed[number]), MoveBar.CLOSED_SOURCE)]
        [found] = candidates
        if not mistaken:
            return self._claim(found, report, report.day, None)
        shown = report.day if opens else found.day
        return self._claim(found, report, found.day, SubjectLost(shown, report.worker, number, found.day))

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
        """Czy Wpis ``report`` może zmienić Wykonawcę albo dzień zlecenia ``order``: ``may_move`` dla każdej pamięci
        tego zlecenia (``memories_of``), a gdy jej nie ma, ``may_move`` bez pamięci."""

        key = order.key
        found = memories_of(self._memory, key, self._places)
        return all(may_move(memory, key.worker, key.day, report.arrived) for memory in found or (None,))

    def _bar(self, order: RegisterOrder, day: date) -> MoveBar | None:
        if not self._window.opens(day):
            return MoveBar.CLOSED_TARGET
        if OrderedDay(order.row.sheet, day) in self._ordered:
            return None
        return MoveBar.OTHER_SHEET if day in self._ordered_anywhere else MoveBar.NOT_ORDERED
