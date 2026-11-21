from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from itertools import pairwise

from hypothesis import example, given, settings
from hypothesis import strategies as st

from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.raw_orders import (
    CellFacts,
    MissingDays,
    AddedRow,
    MovePlan,
    NewOrder,
    NewSeparator,
    OrderColumns,
    RowFacts,
    numbered_rows,
    ordered_days,
    ordered_rows,
    plan_moves,
    segment_key,
)
from rozliczenia.register_columns import ORDERED_FONT, ORDERED_SIZE
from rozliczenia.report_cells import OrderAdded, OrderRow, ReportColumn
from rozliczenia.settlement_period import period_of
from rozliczenia.worker_reports import (
    Kept,
    Login,
    MailId,
    ManualDifference,
    OlderOwnEntries,
    OrderedDay,
    OrderKey,
    OrderNumber,
    OwnEntries,
    OwnEntry,
    ReadNumber,
    RegisterOrder,
    ReportMail,
    ReportsOutcome,
    SenderAddress,
    UnknownNumber,
    Window,
    WorkerAddresses,
    order_number,
)
from tests.fixtures.pamiec_wpisania import Given, enter_reports

SHEET = "ZLECENIA OD 06_2025"
NUMBER_COLUMN, SUCCESSFUL_COLUMN, COMPLETED_COLUMN = 7, 8, 9
COLUMNS = OrderColumns(
    first=1, date=2, worker=3, last=9, devices=4, activities=5, contract_number=6, address=1, city=1, number=NUMBER_COLUMN
)
ORDERED_FACE = (ORDERED_FONT, float(ORDERED_SIZE))
N0 = "N0 (ADR 0028, okres z Plikiem zbiorczym; ADR 0029, „Okno mówi, gdzie wolno pisać”)"
N1 = "N1 (GLOSSARY: Wpisanie raportów, ręczna wartość taty zawsze wygrywa)"
N2 = "N2 (ADR 0029, „Numer w kilku zleceniach się nie przenosi”)"
N3 = "N3 (ADR 0029, „Ręczna zmiana dalej wygrywa”)"
N4 = "N4 (ADR 0028, „Każde kliknięcie liczy od nowa”)"
N5 = "N5 (enter_reports: ten sam wynik w dowolnej kolejności maili)"
N6 = "N6 (zapis INTERMAX)"
N7 = "N7 (GLOSSARY: Przeniesienie zlecenia; ADR 0029, „Wiersz idzie za zleceniem”)"
N8 = "N8 (ADR 0029, „Numer bez zlecenia to Zlecenie dopisane z raportu”)"
N9 = "N9 (GLOSSARY: Wpis raportu, Zlecenie dopisane z raportu)"
APP_FACE = ("Arial", 10.0)

BEFORE_ROLLOUT = date(2026, 10, 29)
CLOSED_DAY = date(2026, 10, 31)
SIXTH, SEVENTH, EIGHTH, NINTH = (date(2026, 11, day) for day in (6, 7, 8, 9))
DAYS = (BEFORE_ROLLOUT, CLOSED_DAY, SIXTH, SEVENTH, EIGHTH, NINTH)
ORDER_DAYS = (*DAYS, SIXTH, SEVENTH, SEVENTH, EIGHTH, EIGHTH, EIGHTH)
MAIL_DAYS = (CLOSED_DAY, SIXTH, SEVENTH, SEVENTH, EIGHTH, EIGHTH, EIGHTH, NINTH)
ROLLOUT = date(2026, 10, 30)
NUMBERS_SINCE = date(2026, 10, 27)
CLOSED = (period_of(CLOSED_DAY).token,)
CLOSED_PERIOD = (date(2026, 10, 27), date(2026, 11, 2))
TAPA = timezone(timedelta(hours=1))
FIRST_CLICK = datetime(2026, 11, 8, 17, tzinfo=TAPA)
NEXT_DAY = datetime(2026, 11, 9, 17, tzinfo=TAPA)

ADAM, EWA, JAN = Login("adam.inny"), Login("ewa.probna"), Login("jan.testowy")
WORKERS = (ADAM, EWA, JAN)
TATA_WORKER_SPELLING = {ADAM: "Adam.Inny", EWA: "Ewa.Probna", JAN: "Jan.Testowy"}
ADDRESS = {
    ADAM: "adam@przyklad.invalid",
    EWA: "ewa@przyklad.invalid",
    JAN: "jan@przyklad.invalid",
}
STRANGERS = ("obcy@inny.invalid", "ktos@inny.invalid")
NUMBERS = ("40000001", "40000002", "40000003", "40000004")
TYPO = "400000011"
APP_NUMBER_DIGITS = 8


def _address(text: str) -> SenderAddress:
    found = SenderAddress.of(text)
    assert found is not None
    return found


ADDRESSES = WorkerAddresses({_address(ADDRESS[login]): login for login in WORKERS})

PHRASES = (
    "wymiana routera",
    "brak klienta",
    "montaż gniazda w salonie",
    "klient nieobecny",
    "przełożone na prośbę klienta",
)
TAGS = ("", "alfa", "beta", "gamma", "delta")
SUCCESSFUL_BY_MARK: dict[str, str | None] = {
    "tak": "tak",
    "Tak": "tak",
    "TAK.": "tak",
    "nie": "nie",
    "Nie,": "nie",
    "NIE": "nie",
    "t": None,
    "skuteczne": None,
    "": None,
}
MAIL_ENDS_AFTER_LAST_ENTRY = (
    "",
    "\n\nJan",
    "\n\nJan Testowy\ntel. 600 100 200",
    "\nPozdrawiam\nJan",
    "\nDziekuje",
    ", pozdrawiam Jan",
    "\n-- \nJan Testowy",
    "\nWysłane z iPhone'a",
    " Wysłane z iPhone'a",
    "\n\nW dniu 8.11.2026 o 17:00 Tata <tata@przyklad.invalid> napisał:\n> Przypomnienie: raport za dzień 08.11.2026",
)
TATA_SUCCESSFUL = (None, None, "tak", "nie")
TATA_COMPLETED = (None, None, "montaż taty", "wymiana routera")


class _Look(Enum):
    ORDERED = "uporządkowany"
    RAW = "surowy"
    AMONG = "z aplikacji między uporządkowanymi"
    BLANK = "pusty"
    YELLOW = "żółty"


_NO_ORDER = 0


@dataclass
class _Line:
    look: _Look
    ident: int = _NO_ORDER
    number: int | None = None
    day: date | None = None
    text_date: bool = False
    worker: str | None = None
    successful: str | None = None
    completed: str | None = None

    @property
    def started(self) -> datetime | str | None:
        if self.day is None:
            return None
        if self.text_date:
            return f"{self.day:%d.%m.%Y} 09:30"
        return datetime(self.day.year, self.day.month, self.day.day, 9, 30)

    @property
    def dated(self) -> bool:
        return (
            self.look is _Look.ORDERED and self.day is not None and not self.text_date
        )

    def cell(self, column: ReportColumn) -> str | None:
        return self.successful if column is ReportColumn.SUCCESSFUL else self.completed

    def set(self, column: ReportColumn, value: str | None) -> None:
        if column is ReportColumn.SUCCESSFUL:
            self.successful = value
        else:
            self.completed = value


@dataclass
class _Truth:
    written: dict[ReportColumn, str] = field(default_factory=dict)
    newest_written_mail_at: datetime | None = None
    before_centrum_moves: tuple[Login, date] | None = None
    placed_by_centrum: tuple[Login, date] | None = None
    moved_elsewhere_by_tata: bool = False


@dataclass(frozen=True)
class _Sent:
    mail: ReportMail
    sender: Login | None
    said: tuple[tuple[str, str | None, str], ...]


def _rows_from_bottom(lines: Sequence[_Line]) -> tuple[RowFacts, ...]:
    found: list[RowFacts] = []
    for index, line in enumerate(lines, start=2):
        if line.look in (_Look.BLANK, _Look.YELLOW):
            found.append(RowFacts(index, {}, line.look is _Look.YELLOW))
            continue
        face = ORDERED_FACE if line.look is _Look.ORDERED else APP_FACE
        values = {
            COLUMNS.date: line.started,
            COLUMNS.worker: line.worker,
            NUMBER_COLUMN: line.number,
            SUCCESSFUL_COLUMN: line.successful,
            COMPLETED_COLUMN: line.completed,
        }
        cells = {
            column: CellFacts(value, face, False)
            for column, value in values.items()
            if value is not None
        }
        found.append(RowFacts(index, cells, False))
    return tuple(reversed(found))


def _laid(lines: Iterable[_Line]) -> list[_Line]:
    orders = [line for line in lines if line.ident]
    sheet: list[_Line] = []
    for day in sorted(
        {
            line.day
            for line in orders
            if line.look is not _Look.RAW and line.day is not None
        }
    ):
        mine = [
            line for line in orders if line.day == day and line.look is not _Look.RAW
        ]
        straight = [line for line in mine if line.dated]
        for index, key in enumerate(
            sorted({segment_key(line.worker) for line in straight})
        ):
            sheet += [_Line(_Look.BLANK)] * bool(index) + [
                line for line in straight if segment_key(line.worker) == key
            ]
        for line in mine:
            if not line.dated:
                sheet += [_Line(_Look.BLANK), line]
        sheet.append(_Line(_Look.BLANK))
    return [
        *sheet,
        _Line(_Look.YELLOW),
        *(line for line in orders if line.look is _Look.RAW),
    ]


@dataclass(frozen=True)
class _Read:
    orders: tuple[RegisterOrder, ...]
    ordered: frozenset[OrderedDay]
    present: tuple[ReadNumber, ...]


def _register_order(row: RowFacts, shift: int = 0) -> RegisterOrder | None:
    return RegisterOrder.of(
        OrderRow(SHEET, row.number),
        number=row.value(NUMBER_COLUMN - shift),
        started=row.value(COLUMNS.date - shift),
        worker=row.value(COLUMNS.worker - shift),
        successful=row.value(SUCCESSFUL_COLUMN - shift),
        completed=row.value(COMPLETED_COLUMN - shift),
        address=None,
        contract=None,
        devices=None,
        activities=None,
    )


def _read_like_report_entering(lines: Sequence[_Line], window: Window) -> _Read:
    rows = _rows_from_bottom(lines)
    orders = tuple(
        found
        for row in ordered_rows(rows, COLUMNS, window.start)
        if (found := _register_order(row)) is not None
    )
    present = []
    for row, place in numbered_rows(rows, COLUMNS, window.numbers_since):
        read: dict[OrderNumber, date | None] = {}
        for shift in place.known:
            number = order_number(row.value(NUMBER_COLUMN - shift))
            if number is not None:
                order = _register_order(row, shift)
                read.setdefault(number, None if order is None else order.key.day)
        present += [ReadNumber(number, day) for number, day in read.items()]
    ordered = frozenset(
        OrderedDay(SHEET, day) for day in ordered_days(rows, COLUMNS, window.start)
    )
    return _Read(orders, ordered, tuple(present))


def _core(
    mails: Sequence[ReportMail],
    read: _Read,
    window: Window,
    memory: OwnEntries,
    kept: frozenset[Kept],
) -> ReportsOutcome:
    return enter_reports(
        Given(
            tuple(mails),
            ADDRESSES,
            read.orders,
            window,
            memory,
            kept,
            read.present,
            DEFAULT_ACTIVITY_LEGEND,
            read.ordered,
        )
    )


def _released(memory: OwnEntries, orders: tuple[RegisterOrder, ...]) -> OwnEntries:
    return OlderOwnEntries(memory).upgraded(orders)


def _planned_like_write_cells(lines: Sequence[_Line], outcome: ReportsOutcome) -> MovePlan | MissingDays:
    moves = {move.order.row: (move.worker, move.day) for move in outcome.moves}
    added = []
    for order in outcome.added:
        cells: dict[int, str | int] = {
            NUMBER_COLUMN: int(order.number),
            SUCCESSFUL_COLUMN: order.successful,
        }
        if order.completed is not None:
            cells[COMPLETED_COLUMN] = order.completed
        added.append(AddedRow(order.worker, order.day, cells))
    return plan_moves(_rows_from_bottom(lines), COLUMNS, moves, added)


OUTCOME_FIELDS_WRITTEN_TO_INTERMAX = frozenset({"changes", "moves", "added"})
OUTCOME_FIELDS_NOT_WRITTEN_TO_INTERMAX = frozenset({"problems", "workers", "mails", "memory", "notes", "said"})


def _moved(lines: Sequence[_Line], plan: MovePlan, fresh: int) -> list[_Line]:
    days = [line.day for line in lines]
    after = list(lines[: plan.first - 2])
    for slot in plan.rows:
        if isinstance(slot, NewOrder):
            row, day = plan.added[slot.added], days[slot.model - 2]
            assert day is not None
            successful, completed = (
                row.cells.get(SUCCESSFUL_COLUMN),
                row.cells.get(COMPLETED_COLUMN),
            )
            assert isinstance(successful, str) and (
                completed is None or isinstance(completed, str)
            )
            number = row.cells[NUMBER_COLUMN]
            day += timedelta(days=slot.days)
            after.append(
                _Line(
                    _Look.ORDERED,
                    fresh + slot.added,
                    int(number),
                    day,
                    False,
                    row.worker,
                    successful,
                    completed,
                )
            )
            continue
        if isinstance(slot, NewSeparator) or slot - 2 >= len(lines):
            after.append(_Line(_Look.BLANK))
            continue
        line = lines[slot - 2]
        if slot in plan.workers:
            line.worker = plan.workers[slot]
        if slot in plan.shifts and line.day is not None:
            line.day += timedelta(days=plan.shifts[slot])
        after.append(line)
    return after


def _written(
    lines: Sequence[_Line], outcome: ReportsOutcome, fresh: int
) -> list[_Line]:
    after = [replace(line) for line in lines]
    for change in outcome.changes:
        after[change.order.row - 2].set(change.column, change.value)
    if not outcome.moves and not outcome.added:
        return after
    plan = _planned_like_write_cells(lines, outcome)
    assert isinstance(plan, MovePlan)
    return _moved(after, plan, fresh)


@dataclass
class _Register:
    lines: list[_Line] = field(default_factory=list)
    truth: defaultdict[int, _Truth] = field(default_factory=lambda: defaultdict(_Truth))
    released: OwnEntries | None = None
    sent: list[_Sent] = field(default_factory=list)
    memory: OwnEntries = OwnEntries.EMPTY
    kept: frozenset[Kept] = frozenset()
    clock: datetime = FIRST_CLICK
    last: ReportsOutcome | None = None
    alone_at_last_click: dict[str, int] = field(default_factory=dict)
    moved_or_added_by_centrum: set[str] = field(default_factory=set)
    removed_by_tata_after_centrum: dict[int | None, datetime] = field(default_factory=dict)
    to_lay_out: bool = False

    def pick(self, which: int) -> _Line | None:
        found = sorted(
            (line for line in self.lines if line.ident), key=lambda line: line.ident
        )
        return found[which % len(found)] if found else None

    def add(self, seed: tuple[object, ...]) -> _Line:
        kind, number, day, worker, successful, completed = seed
        assert (
            isinstance(kind, str)
            and isinstance(number, str)
            and isinstance(day, date)
            and isinstance(worker, str)
        )
        assert (successful is None or isinstance(successful, str)) and (
            completed is None or isinstance(completed, str)
        )
        look = {"surowe": _Look.RAW, "z aplikacji": _Look.AMONG}.get(
            kind, _Look.ORDERED
        )
        name = None if kind == "bez wykonawcy" else TATA_WORKER_SPELLING[Login(worker)]
        ident = max(self.truth, default=0) + 1
        line = _Line(
            look,
            ident,
            int(number),
            day,
            kind == "data tekstem",
            name,
            successful,
            completed,
        )
        self.lines.append(line)
        self.truth[ident] = _Truth()
        self.to_lay_out = True
        return line

    def report_day(self, sent: _Sent, today: date) -> date | None:
        if sent.sender is None:
            return None
        return next(
            (
                day
                for day in MAIL_DAYS
                if ROLLOUT <= day <= today and sent.mail.subject in _report_subjects(day)
            ),
            None,
        )

    def said(self, number: int | None) -> list[tuple[_Sent, str | None, str]]:
        return [
            (sent, verdict, text)
            for sent in self.sent
            for found, verdict, text in sent.said
            if found == str(number)
        ]


def _start(seeds: Sequence[tuple[object, ...]], released: Iterable[int]) -> _Register:
    register = _Register()
    lines = [register.add(seed) for seed in seeds]
    entries: dict[tuple[OrderKey, ReportColumn], OwnEntry] = {}
    for index in sorted(set(released)):
        line = lines[index % len(lines)]
        if (
            not line.dated
            or line.day is None
            or line.worker is None
            or not ROLLOUT <= line.day <= FIRST_CLICK.date()
        ):
            continue
        key = OrderKey(
            OrderNumber(str(line.number)), line.day, Login(line.worker.lower())
        )
        for column in ReportColumn:
            value = line.cell(column)
            if value is not None and (key, column) not in entries:
                entries[key, column] = OwnEntry(key, column, value)
    register.released = OwnEntries(frozenset(entries.values())) if entries else None
    register.lines, register.to_lay_out = _laid(register.lines), False
    return register


def _alone(orders: Iterable[RegisterOrder], lines: Sequence[_Line]) -> dict[str, int]:
    found: defaultdict[str, list[int]] = defaultdict(list)
    for order in orders:
        found[order.key.number].append(lines[order.row.row - 2].ident)
    return {number: idents[0] for number, idents in found.items() if len(idents) == 1}


def _carry_identity(register: _Register, orders: tuple[RegisterOrder, ...]) -> None:
    now = _alone(orders, register.lines)
    if register.released is not None:
        keys = {
            order.key: register.lines[order.row.row - 2].ident
            for order in orders
            if order.key.number in now
        }
        for entry in register.released.entries:
            ident = keys.get(entry.key)
            if ident is not None:
                register.truth[ident].written.setdefault(entry.column, entry.value)
        return
    for number, ident in now.items():
        before = register.alone_at_last_click.get(number)
        if before is not None and before != ident:
            old = register.truth[before]
            register.truth[ident] = replace(old, written=dict(old.written))


def _forget_unsure(register: _Register, orders: tuple[RegisterOrder, ...]) -> None:
    counted = Counter(order.key.number for order in orders)
    for line in register.lines:
        if line.ident and counted[OrderNumber(str(line.number))] != 1:
            register.truth[line.ident].written.clear()


def _open(day: date | None, today: date) -> bool:
    return (
        day is not None
        and ROLLOUT <= day <= today
        and not CLOSED_PERIOD[0] <= day <= CLOSED_PERIOD[1]
    )


def _place(line: _Line) -> tuple[Login, date] | None:
    return (
        None
        if line.worker is None or line.day is None
        else (Login(line.worker.lower()), line.day)
    )


def _observe(register: _Register, orders: tuple[RegisterOrder, ...]) -> None:
    for line in register.lines:
        truth = register.truth[line.ident] if line.ident else None
        if truth is not None and truth.placed_by_centrum is not None and not truth.moved_elsewhere_by_tata:
            places = {
                (order.key.worker, order.key.day)
                for order in orders
                if order.key.number == str(line.number)
            }
            truth.moved_elsewhere_by_tata = truth.placed_by_centrum not in places


def _numbers_in_read_rows(lines: Iterable[_Line]) -> set[int | None]:
    return {
        line.number
        for line in lines
        if line.ident
        and (
            line.look is _Look.RAW
            or (line.day is not None and line.day >= NUMBERS_SINCE)
        )
    }


def _faults(
    register: _Register,
    today: date,
    orders: tuple[RegisterOrder, ...],
    outcome: ReportsOutcome,
) -> list[str]:
    lines = register.lines
    faults: list[str] = []
    counted = Counter(order.key.number for order in orders)
    cells = Counter((change.order.row, change.column) for change in outcome.changes)
    by_row: defaultdict[int, dict[ReportColumn, str]] = defaultdict(dict)
    for change in outcome.changes:
        line = lines[change.order.row - 2]
        by_row[change.order.row][change.column] = change.value
        if (
            change.order.sheet != SHEET
            or line.look is not _Look.ORDERED
            or cells[change.order.row, change.column] > 1
        ):
            faults.append(
                f"{N6}: zmiana poza uporządkowanym wierszem albo dwa razy w komórce: {change}"
            )
            continue
        if not (line.dated and _open(line.day, today)):
            faults.append(
                f"{N0}: zmiana komórki zlecenia z dnia, który nie jest otwarty: {change}, {line}"
            )
        current, written = (
            line.cell(change.column),
            register.truth[line.ident].written.get(change.column),
        )
        if current is not None and current != written:
            faults.append(
                f"{N1}: Centrum nadpisało ręczną wartość taty {current!r}: {change}, {line}"
            )
    for row, changed in by_row.items():
        line = lines[row - 2]
        if not any(
            verdict is not None
            and changed.get(ReportColumn.SUCCESSFUL, verdict) == verdict
            and changed.get(ReportColumn.COMPLETED, text) == text
            and (ReportColumn.SUCCESSFUL in changed or line.successful is not None)
            and (
                ReportColumn.COMPLETED in changed
                or not text
                or line.completed is not None
            )
            for _, verdict, text in register.said(line.number)
        ):
            faults.append(
                f"{N9}: wpisane wartości nie są jednym Wpisem z maila o numerze wiersza albo pusta komórka nie dostała drugiej wartości tego Wpisu: {changed}, {line}"
            )
    sources = Counter(move.order.row for move in outcome.moves)
    for move in outcome.moves:
        line = lines[move.order.row - 2]
        if not line.dated or sources[move.order.row] > 1:
            faults.append(
                f"{N6}: Przeniesienie spoza uporządkowanego wiersza z datą: {move}"
            )
            continue
        if not (_open(line.day, today) and _open(move.day, today)):
            faults.append(
                f"{N0}: Przeniesienie z dnia albo na dzień, który nie jest otwarty: {move}, {line}"
            )
        if counted[OrderNumber(str(line.number))] != 1:
            faults.append(
                f"{N2}: Przeniesienie numeru, który odczytane dni mają {counted[OrderNumber(str(line.number))]} razy: {move}"
            )
        since, worker = register.truth[line.ident].newest_written_mail_at, Login(move.worker.lower())
        if not any(
            sent.sender == worker and (since is None or sent.mail.arrived > since)
            for sent, _, _ in register.said(line.number)
        ):
            faults.append(
                f"{N3}: Przeniesienie bez maila nowego Wykonawcy świeższego niż każdy wpisany do wiersza ({since}), więc stary mail cofa zmianę taty: {move}"
            )
        if register.truth[line.ident].moved_elsewhere_by_tata:
            faults.append(
                f"{N3}: Przeniesienie zlecenia, które tata przeniósł po Przeniesieniu Centrum: {move}, {line}"
            )
    faults += [
        f"{N2}: numer, który odczytane dni mają, jako nieznany: {problem}"
        for problem in outcome.problems
        if isinstance(problem, UnknownNumber) and counted[problem.number]
    ]
    rows = {
        order.key: lines[order.row.row - 2]
        for order in orders
        if counted[order.key.number] == 1
    }
    faults += [
        f"{N1}: wartość, którą Centrum wpisało, a nikt jej nie zmienił, pokazana jako ręczna wartość taty: {problem}"
        for problem in outcome.problems
        if isinstance(problem, ManualDifference)
        and problem.key in rows
        and register.truth[rows[problem.key].ident].written.get(problem.column)
        == problem.manual
    ]
    known, added = _numbers_in_read_rows(lines), Counter(order.number for order in outcome.added)
    for order in outcome.added:
        if order.sheet != SHEET:
            faults.append(
                f"{N6}: Zlecenie dopisane z raportu poza arkuszem zleceń: {order}"
            )
        if not _open(order.day, today):
            faults.append(
                f"{N0}: Zlecenie dopisane z raportu do dnia, który nie jest otwarty: {order}"
            )
        if (
            int(order.number) in known
            or added[order.number] > 1
            or len(order.number) != APP_NUMBER_DIGITS
        ):
            faults.append(
                f"{N8}: dopisany numer, który INTERMAX ma w czytanym wierszu, dopisany dwa razy albo nie z {APP_NUMBER_DIGITS} cyfr numeru z aplikacji firmowej: {order}"
            )
        faults += _added_faults(register, today, orders, order)
    if outcome.moves or outcome.added:
        plan = _planned_like_write_cells(lines, outcome)
        if isinstance(plan, MissingDays):
            faults.append(
                f"{N6}: zapis odrzuca Przeniesienie albo dopisanie na dzień bez uporządkowanych zleceń: {plan}, {outcome}"
            )
    return faults


def _added_faults(
    register: _Register,
    today: date,
    orders: tuple[RegisterOrder, ...],
    order: OrderAdded,
) -> list[str]:
    number, worker = int(order.number), Login(order.worker.lower())
    sources = [
        sent
        for sent, verdict, text in register.said(number)
        if sent.sender == worker
        and verdict == order.successful
        and (text or None) == order.completed
    ]
    if not sources:
        return [
            f"{N9}: Zlecenie dopisane z raportu nie jest jednym Wpisem z maila nadawcy z tym numerem: {order}"
        ]
    placed: defaultdict[str, list[RegisterOrder]] = defaultdict(list)
    for found in orders:
        placed[found.key.number].append(found)

    def others(sent: _Sent) -> set[str]:
        return {found for found, _, _ in sent.said if found != order.number}

    def mistaken(sent: _Sent) -> bool:
        return (
            sum(
                bool(placed[found])
                and all(
                    at.key.day != order.day and at.key.worker == worker
                    for at in placed[found]
                )
                and found not in register.moved_or_added_by_centrum
                for found in others(sent)
            )
            >= 2
        )

    def corrected(sent: _Sent) -> bool:
        own = {
            found
            for found in others(sent)
            if found not in register.moved_or_added_by_centrum
            and any(
                (at.key.worker, at.key.day) == (worker, order.day)
                for at in placed[found]
            )
        }
        return bool(own) and any(
            later.sender == worker
            and later.mail.arrived > sent.mail.arrived
            and register.report_day(later, today) == order.day
            and order.number not in {found for found, _, _ in later.said}
            and others(sent) <= {found for found, _, _ in later.said}
            for later in register.sent
        )

    newest = max(sent.mail.arrived for sent in sources)
    faults = []
    if all(mistaken(sent) for sent in sources):
        faults.append(
            f"N8 (GLOSSARY: Zlecenie dopisane z raportu, „Nie powstaje, gdy temat raportu jest pomyłką”; wyrocznia liczy tylko zlecenia "
            f"nadawcy z innego dnia, przy których ADR 0029 i rdzeń dają ten sam wynik): Zlecenie dopisane z raportu z pomylonym tematem: {order}"
        )
    if all(corrected(sent) for sent in sources):
        faults.append(
            f"N8 (GLOSSARY: Zlecenie dopisane z raportu, „Wykonawca poprawił raport późniejszym mailem bez tego numeru”): Zlecenie dopisane z raportu, który Wykonawca poprawił późniejszym mailem: {order}"
        )
    if any(
        later.mail.arrived > newest and register.report_day(later, today) is not None
        for later, _, _ in register.said(number)
    ):
        faults.append(
            f"N8 (GLOSSARY: Zlecenie dopisane z raportu, „najpóźniejszy mail z tym numerem go nie dopisuje”): Zlecenie dopisane starszym mailem niż najpóźniejszy Raport wykonawcy z tym numerem: {order}"
        )
    if number in register.removed_by_tata_after_centrum and newest <= register.removed_by_tata_after_centrum[number]:
        faults.append(
            f"{N3}: tata usunął wiersz numeru po wpisie Centrum, a stary mail dopisał go z powrotem: {order}"
        )
    return faults


def _layout_faults(lines: Sequence[_Line], received: dict[int, str]) -> list[str]:
    faults = []
    for day in sorted(
        {line.day for line in lines if line.dated and line.day is not None}
    ):
        at = [
            index for index, line in enumerate(lines) if line.dated and line.day == day
        ]
        segments: list[list[_Line]] = [[lines[at[0]]]]
        for previous, index in pairwise(at):
            if index == previous + 1:
                segments[-1].append(lines[index])
                continue
            if index != previous + 2 or lines[previous + 1].look is not _Look.BLANK:
                faults.append(
                    f"{N7}: dzień {day} rozdzielony wierszami {previous + 3}–{index + 1}"
                )
            segments.append([lines[index]])
        keys = [
            sorted({segment_key(line.worker) for line in segment})
            for segment in segments
        ]
        if any(len(found) > 1 for found in keys) or [
            found[0] for found in keys
        ] != sorted({found[0] for found in keys}):
            faults.append(
                f"{N7}: dzień {day} ma segmenty {keys}, a nie jeden segment każdego Wykonawcy alfabetycznie"
            )
        for segment in segments:
            came = [line.ident in received for line in segment]
            if True in came and not all(came[came.index(True) :]):
                faults.append(
                    f"{N7}: zlecenie przeniesione w dniu {day} nie stoi pod zleceniami Wykonawcy: {segment}"
                )
    return faults


def _click(register: _Register) -> None:
    if register.to_lay_out:
        register.lines, register.to_lay_out = _laid(register.lines), False
    window = Window.of(register.clock.date(), ROLLOUT, CLOSED)
    read = _read_like_report_entering(register.lines, window)
    orders = read.orders
    _carry_identity(register, orders)
    _forget_unsure(register, orders)
    _observe(register, orders)
    memory = (
        register.memory
        if register.released is None
        else _released(register.released, orders)
    )
    mails = [sent.mail for sent in register.sent]
    outcome = _core(mails, read, window, memory, register.kept)
    faults = _faults(register, register.clock.date(), orders, outcome)
    reversed_outcome = _core(mails[::-1], read, window, memory, register.kept)
    if reversed_outcome != outcome:
        faults.append(
            f"{N5}: wynik zależy od kolejności maili: {outcome} wobec {reversed_outcome}"
        )
    unapplied = {found.name for found in fields(ReportsOutcome)} - OUTCOME_FIELDS_WRITTEN_TO_INTERMAX - OUTCOME_FIELDS_NOT_WRITTEN_TO_INTERMAX
    if unapplied:
        faults.append(
            f"{N8}: wynik rdzenia ma nowe pola {sorted(unapplied)}: pole, które zmienia INTERMAX, dopisz do OUTCOME_FIELDS_WRITTEN_TO_INTERMAX i "
            "zapisz w _written, a inne dopisz do OUTCOME_FIELDS_NOT_WRITTEN_TO_INTERMAX"
        )
    assert not faults, "\n".join(faults)

    known = _numbers_in_read_rows(register.lines)
    before = Counter(line.number for line in register.lines if line.ident)
    received = {
        register.lines[move.order.row - 2].ident: move.worker for move in outcome.moves
    }
    fresh = max(register.truth, default=0) + 1
    for index, order in enumerate(outcome.added):
        received[fresh + index] = order.worker
        written = {ReportColumn.SUCCESSFUL: order.successful}
        if order.completed is not None:
            written[ReportColumn.COMPLETED] = order.completed
        arrived = min(
            sent.mail.arrived
            for sent, verdict, text in register.said(int(order.number))
            if sent.sender == Login(order.worker.lower())
            and (verdict, text or None) == (order.successful, order.completed)
        )
        place = (Login(order.worker.lower()), order.day)
        register.truth[fresh + index] = _Truth(written, arrived, place)
    for change in outcome.changes:
        line = register.lines[change.order.row - 2]
        truth = register.truth[line.ident]
        truth.written[change.column] = change.value
        if change.column is ReportColumn.COMPLETED:
            arrived = min(
                sent.mail.arrived
                for sent, _, text in register.said(line.number)
                if text == change.value
            )
            truth.newest_written_mail_at = arrived if truth.newest_written_mail_at is None else max(truth.newest_written_mail_at, arrived)
    for move in outcome.moves:
        line = register.lines[move.order.row - 2]
        truth, here, target = (
            register.truth[line.ident],
            _place(line),
            (Login(move.worker.lower()), move.day),
        )
        origin = (
            truth.before_centrum_moves if truth.placed_by_centrum is not None and truth.placed_by_centrum == here else here
        )
        truth.before_centrum_moves, truth.placed_by_centrum, truth.moved_elsewhere_by_tata = (
            origin,
            None if target == origin else target,
            False,
        )
    register.lines = _written(register.lines, outcome, fresh)
    faults = _layout_faults(register.lines, received)
    after = Counter(line.number for line in register.lines if line.ident)
    faults += [
        f"{N8}: numer {number} ma po kliknięciu {after[number]} wierszy, a miał {before[number]}"
        for number in known
        if after[number] > before[number]
    ]
    placed = {line.ident: line for line in register.lines if line.ident >= fresh}
    for index, order in enumerate(outcome.added):
        new = placed.get(fresh + index)
        if new is None or (new.number, new.day, new.worker) != (
            int(order.number),
            order.day,
            order.worker,
        ):
            faults.append(
                f"{N8}: zapis nie dopisał zlecenia {order} w jego dniu i u jego Wykonawcy: {new}"
            )
    again_read = _read_like_report_entering(register.lines, window)
    again = _core(mails, again_read, window, outcome.memory, register.kept)
    if (again.changes, again.moves, again.added, again.memory) != (
        (),
        (),
        (),
        outcome.memory,
    ):
        faults.append(
            f"{N4}: powtórne kliknięcie zmienia INTERMAX albo pamięć: {again.changes}, {again.moves}, {again.added}"
        )
    assert not faults, "\n".join(faults)

    for line in register.lines:
        if line.ident:
            truth = register.truth[line.ident]
            truth.written = {
                column: value
                for column, value in truth.written.items()
                if line.cell(column) == value
            }
    register.alone_at_last_click = _alone(again_read.orders, register.lines)
    register.moved_or_added_by_centrum |= {
        str(line.number) for line in register.lines if line.ident in received
    }
    for order in outcome.added:
        register.removed_by_tata_after_centrum.pop(int(order.number), None)
    register.memory, register.released, register.last = outcome.memory, None, outcome
    register.clock += timedelta(hours=1)


Start = tuple[tuple[tuple[object, ...], ...], frozenset[int]]


def _play(start: Start, events: Sequence[tuple[object, ...]]) -> _Register:
    register = _start(*start)
    for event in events:
        match event:
            case (
                "mail",
                str(who),
                str(subject),
                int(minute),
                str(message_id),
                str(text),
                tuple(said),
            ):
                sender = Login(who) if who in ADDRESS else None
                address = _address(ADDRESS[Login(who)] if sender is not None else who)
                mail_id = MailId.of(
                    message_id or f"<{len(register.sent)}@przyklad.invalid>"
                )
                mail = ReportMail(
                    mail_id,
                    address,
                    subject,
                    text,
                    register.clock + timedelta(minutes=minute),
                )
                register.sent.append(_Sent(mail, sender, said))
            case ("poprawka", int(which), int(minute), int(dropped), str(extra)) if (
                register.sent
            ):
                base = register.sent[which % len(register.sent)]
                kept = [
                    entry
                    for index, entry in enumerate(base.said)
                    if index != dropped % (len(base.said) or 1)
                ]
                said = (
                    *kept,
                    *[(extra, "tak", "")]
                    * bool(extra and extra not in {number for number, _, _ in kept}),
                )
                text = "\n".join(
                    " ".join(part for part in (number, verdict or "", words) if part)
                    for number, verdict, words in said
                )
                mail_id = MailId.of(f"<{len(register.sent)}@przyklad.invalid>")
                arrived = register.clock + timedelta(minutes=minute)
                mail = ReportMail(
                    mail_id, base.mail.sender, base.mail.subject, text, arrived
                )
                register.sent.append(_Sent(mail, base.sender, tuple(said)))
            case ("poprawka", *_):
                pass
            case ("komórka", int(which), ReportColumn() as column, value):
                line = register.pick(which)
                assert value is None or isinstance(value, str)
                if line is not None:
                    line.set(column, value)
            case ("przepisuje", int(which)):
                line = register.pick(which)
                entries = [] if line is None else register.said(line.number)
                if line is not None and entries:
                    _, verdict, text = entries[-1]
                    line.successful, line.completed = verdict, text or None
            case ("wykonawca", int(which), str(login)):
                line = register.pick(which)
                if line is not None and line.worker is not None:
                    line.worker, register.to_lay_out = TATA_WORKER_SPELLING[Login(login)], True
            case ("dzień", int(which), date() as day):
                line = register.pick(which)
                if line is not None:
                    line.day, register.to_lay_out = day, True
            case ("usuwa", int(which)):
                line = register.pick(which)
                if line is not None:
                    register.lines.remove(line)
                    register.to_lay_out = True
                    since = register.truth[line.ident].newest_written_mail_at
                    if since is not None and all(
                        other.number != line.number for other in register.lines
                    ):
                        register.removed_by_tata_after_centrum[line.number] = since
            case ("wkleja", tuple(seed)):
                register.add(seed)
            case ("zostaw",):
                found = () if register.last is None else register.last.problems
                register.kept |= {
                    Kept(shown.key, shown.column, shown.reported)
                    for shown in found
                    if isinstance(shown, ManualDifference)
                }
            case ("nowy dzień",):
                register.clock = max(register.clock, NEXT_DAY)
            case ("klik",):
                _click(register)
            case _:
                raise AssertionError(f"Nieznane zdarzenie: {event}")
    return register


BETWEEN_ENTRIES = ("\n", "\n\n", " ")
ONLY_LINE_START_BEGINS_ENTRY_WITHOUT_MARK = ("\n", "\n\n")
ENTRY_PREFIXES = ("", "Zlecenie ", "Nr ", "zl. ")


@st.composite
def _body(
    draw: st.DrawFn, numbers: Sequence[str] = NUMBERS
) -> tuple[str, tuple[tuple[str, str | None, str], ...]]:
    chosen = draw(
        st.lists(st.sampled_from(numbers), min_size=1, max_size=3, unique=True)
    )
    parts = [draw(st.sampled_from(("", "Dzień dobry,\n", "Witam\n\n")))]
    said = []
    for index, number in enumerate(chosen):
        mark = draw(st.sampled_from(tuple(SUCCESSFUL_BY_MARK)))
        phrase = draw(st.sampled_from(("", *PHRASES)))
        words = [*phrase.split(), draw(st.sampled_from(TAGS))] if phrase else []
        words = [word for word in words if word]
        if index:
            parts.append(
                draw(st.sampled_from(BETWEEN_ENTRIES if mark else ONLY_LINE_START_BEGINS_ENTRY_WITHOUT_MARK))
            )
        if mark:
            if not parts[-1] or parts[-1].endswith("\n"):
                parts.append(draw(st.sampled_from(("", "1. ", "- "))))
            parts.append(draw(st.sampled_from(ENTRY_PREFIXES)))
        parts.append(draw(st.sampled_from((number, f"#{number}"))))
        if mark:
            parts.append(draw(st.sampled_from((" ", " - ", ": ", "\n"))) + mark)
        for position, word in enumerate(words):
            if position:
                parts.append(draw(st.sampled_from((" ", " ", "\n"))))
            else:
                parts.append(
                    draw(st.sampled_from((" ", ", ", " - ", "\n"))) if mark else " "
                )
            parts.append(word)
        said.append((number, SUCCESSFUL_BY_MARK[mark], " ".join(words)))
    parts.append(draw(st.sampled_from(MAIL_ENDS_AFTER_LAST_ENTRY)))
    return "".join(parts), tuple(said)


def _report_subjects(day: date) -> tuple[str, ...]:
    return (
        f"Raport {day:%d.%m.%Y}",
        f"raport {day.day}.{day.month}.{day:%y}",
        f"RAPORT {day:%d_%m_%Y} r.",
        f"Re: Przypomnienie: raport za dzień {day:%d.%m.%Y}",
        f"Re: Raport {day:%d.%m.%Y} - BŁĘDY PROSZĘ POPRAW",
    )


def _reply_about_something_else(day: date) -> str:
    return f"Re: Zmiana w raportach {day:%d.%m.%Y}"


SUBJECTS_REPORT_DAY_DOES_NOT_DATE = ("Raport", "Raport za wczoraj", "Raport 08.11")


@st.composite
def _mail(draw: st.DrawFn) -> tuple[object, ...]:
    who = draw(st.sampled_from((*WORKERS, *WORKERS, *STRANGERS)))
    day = draw(st.sampled_from(MAIL_DAYS))
    forms = (*_report_subjects(day), _reply_about_something_else(day))
    undated = SUBJECTS_REPORT_DAY_DOES_NOT_DATE[draw(st.integers(0, len(SUBJECTS_REPORT_DAY_DOES_NOT_DATE) - 1))]
    subject = draw(
        st.sampled_from((*(forms[0],) * 5, *forms[1:], undated, undated))
    )
    text, said = draw(_body((*NUMBERS, TYPO)))
    message_id = draw(st.sampled_from(("", "", "<a@przyklad.invalid>")))
    return ("mail", who, subject, draw(st.integers(0, 1)), message_id, text, said)


_CORRECTION = st.tuples(
    st.just("poprawka"),
    st.integers(0, 7),
    st.integers(0, 1),
    st.integers(0, 2),
    st.sampled_from(("", *NUMBERS)),
)


def _seeds(numbers: Sequence[str]) -> st.SearchStrategy[tuple[object, ...]]:
    kinds = (
        "zlecenie",
        "zlecenie",
        "zlecenie",
        "zlecenie",
        "bez wykonawcy",
        "data tekstem",
        "z aplikacji",
        "surowe",
    )
    return st.tuples(
        st.sampled_from(kinds),
        st.sampled_from(numbers),
        st.sampled_from(ORDER_DAYS),
        st.sampled_from(WORKERS),
        st.sampled_from(TATA_SUCCESSFUL),
        st.sampled_from(TATA_COMPLETED),
    )


_START = st.tuples(
    st.lists(_seeds(NUMBERS), min_size=2, max_size=7).map(tuple),
    st.frozensets(st.integers(0, 5), max_size=3),
)
_TATA = st.one_of(
    st.tuples(
        st.just("komórka"),
        st.integers(0, 7),
        st.sampled_from(tuple(ReportColumn)),
        st.sampled_from((*TATA_SUCCESSFUL, *TATA_COMPLETED)),
    ),
    st.tuples(st.just("przepisuje"), st.integers(0, 7)),
    st.tuples(st.just("wykonawca"), st.integers(0, 7), st.sampled_from(WORKERS)),
    st.tuples(st.just("dzień"), st.integers(0, 7), st.sampled_from(ORDER_DAYS)),
    st.tuples(st.just("usuwa"), st.integers(0, 7)),
    st.tuples(st.just("wkleja"), _seeds(NUMBERS)),
    st.just(("zostaw",)),
    st.just(("nowy dzień",)),
)
_EVENTS = st.lists(
    st.tuples(
        st.lists(_TATA, max_size=3),
        st.lists(st.one_of(_mail(), _mail(), _CORRECTION), max_size=3),
    ),
    min_size=1,
    max_size=5,
).map(
    lambda rounds: [
        event for tata, mails in rounds for event in (*tata, *mails, ("klik",))
    ]
)


def _sent(
    who: str,
    subject: str,
    text: str,
    said: tuple[tuple[str, str | None, str], ...],
    minute: int = 0,
    message_id: str = "",
) -> tuple[object, ...]:
    return ("mail", who, subject, minute, message_id, text, said)


def _order(
    number: str,
    day: date,
    worker: str,
    successful: str | None = None,
    completed: str | None = None,
) -> tuple[object, ...]:
    return ("zlecenie", number, day, worker, successful, completed)


ONE = "40000001"
TWO, THREE, FOUR = NUMBERS[1:]
SAME_ID = "<1@przyklad.invalid>"


@settings(derandomize=True, database=None, deadline=None, max_examples=500)
@given(_START, _EVENTS)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            STRANGERS[0],
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
            message_id=SAME_ID,
        ),
        _sent(
            STRANGERS[1],
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
            message_id=SAME_ID,
        ),
        ("klik",),
    ],
).via(
    "przegląd #1238 r2 Ważne 1: dwa obce adresy z jednym Message-ID wywracały całe Wpisanie raportów"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport",
            "40000001 tak wymiana",
            ((ONE, "tak", "wymiana"),),
            message_id=SAME_ID,
        ),
        _sent(JAN, "Raport", "kurier jutro", (), message_id=SAME_ID),
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana",
            ((ONE, "tak", "wymiana"),),
            minute=1,
            message_id="<2@przyklad.invalid>",
        ),
        ("klik",),
    ],
).via(
    "przegląd #1302 r1 Ważne 1: ostrzeżenie o nieczytelnym temacie zależało od kolejności maili z jednym Message-ID"
)
@example(
    (
        (
            _order(ONE, EIGHTH, ADAM),
            _order(TWO, EIGHTH, EWA),
            _order(THREE, EIGHTH, EWA),
        ),
        frozenset(),
    ),
    [
        _sent(
            EWA,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
        ),
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000002 tak brak klienta",
            ((TWO, "tak", "brak klienta"),),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1358 r1 Ważne 1: dwa Przeniesienia w jednym dniu dzieliły segment Wykonawcy na dwa"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
        ),
        ("klik",),
        ("wykonawca", 0, EWA),
        ("klik",),
    ],
).via(
    "przegląd #1358 r1 Ważne 2: ręczna zmiana WYKONAWCA po wpisie cofana tym samym starym mailem"
)
@example(
    (
        (
            _order(ONE, SEVENTH, ADAM),
            _order(THREE, EIGHTH, ADAM),
            _order(TWO, EIGHTH, JAN),
        ),
        frozenset(),
    ),
    [
        _sent(
            ADAM,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
        ),
        _sent(
            JAN,
            "Raport 07.11.2026",
            "40000002 tak brak klienta",
            ((TWO, "tak", "brak klienta"),),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1367 r1 Ważne 1: Przeniesienie na dzień, który zapis uznawał za pusty, zatrzymywało całe kliknięcie"
)
@example(
    (
        (
            _order(ONE, SIXTH, EWA),
            _order(ONE, SEVENTH, JAN),
            _order(TWO, SEVENTH, ADAM),
        ),
        frozenset(),
    ),
    [
        _sent(
            JAN,
            "Raport 07.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
        ),
        ("klik",),
        ("dzień", 1, EIGHTH),
        ("klik",),
        _sent(
            ADAM,
            "Raport 06.11.2026",
            "40000001 tak montaż gniazda w salonie",
            ((ONE, "tak", "montaż gniazda w salonie"),),
        ),
        ("klik",),
        ("klik",),
    ],
).via(
    "przegląd #1367 r2 Ważne 1: Przeniesienie drugiego zlecenia numeru kasowało pamięć, a stary mail cofał zmianę taty"
)
@example(
    (
        (_order(ONE, SEVENTH, JAN), _order(ONE, SIXTH, EWA, "tak", "montaż taty")),
        frozenset(),
    ),
    [
        _sent(
            EWA,
            "Raport 06.11.2026",
            "40000001 nie brak klienta",
            ((ONE, "nie", "brak klienta"),),
        ),
        _sent(
            JAN,
            "Raport 07.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
            minute=1,
        ),
        ("klik",),
        ("zostaw",),
        ("usuwa", 0),
        ("klik",),
    ],
).via(
    "przegląd #1367 r3 Ważne 1: wpisy Jana przeszły na zlecenie Ewy, a stary mail nadpisał ręczne „tak” taty"
)
@example(
    (
        (_order(ONE, SIXTH, JAN), _order(ONE, SEVENTH, EWA, "tak", "montaż taty")),
        frozenset(),
    ),
    [
        _sent(
            EWA,
            "Raport 07.11.2026",
            "40000001 nie brak klienta",
            ((ONE, "nie", "brak klienta"),),
        ),
        _sent(
            JAN,
            "Raport 06.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
            minute=1,
        ),
        ("klik",),
        ("zostaw",),
        ("usuwa", 0),
        ("klik",),
    ],
).via(
    "przegląd #1367 r3 Ważne 1 z wierszem Jana nad wierszem Ewy: wpisy Jana nie przechodzą na zlecenie Ewy"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            EWA,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
        ),
        ("klik",),
        ("wykonawca", 0, JAN),
        ("klik",),
        _sent(
            EWA,
            "Raport 08.11.2026",
            "40000001 nie brak klienta",
            ((ONE, "nie", "brak klienta"),),
        ),
        ("klik",),
    ],
).via(
    "ADR 0029: zlecenia, które tata przeniósł z powrotem po Przeniesieniu Centrum, świeższy mail nie przenosi"
)
@example(
    (
        (_order(ONE, SEVENTH, JAN), _order(ONE, NINTH, JAN), _order(TWO, EIGHTH, EWA)),
        frozenset(),
    ),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak montaż gniazda w salonie",
            ((ONE, "tak", "montaż gniazda w salonie"),),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1367 r3 Ważne 2: duplikat z jutra był niewidoczny, więc Centrum przeniosło zlecenie z 7.11"
)
@example(
    (
        (
            _order(ONE, EIGHTH, JAN, "tak", "wymiana routera"),
            _order(ONE, SEVENTH, ADAM, "tak", "montaż taty"),
        ),
        frozenset({0}),
    ),
    [
        ("usuwa", 0),
        _sent(
            ADAM,
            "Raport 07.11.2026",
            "40000001 nie brak klienta",
            ((ONE, "nie", "brak klienta"),),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1367 r4 Ważne 1: pamięć z pliku v0.8.0 przeszła na inne zlecenie numeru i nadpisała ręczne „tak” taty"
)
@example(
    ((_order(ONE, NINTH, JAN), _order(TWO, EIGHTH, JAN)), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak montaż gniazda w salonie",
            ((ONE, "tak", "montaż gniazda w salonie"),),
        ),
        ("klik",),
    ],
).via("przegląd #1374 r1 Ważne 1: numer zlecenia na jutro dopisany drugi raz")
@example(
    (
        (
            ("bez wykonawcy", ONE, EIGHTH, JAN, None, None),
            ("data tekstem", TWO, EIGHTH, JAN, None, None),
            ("z aplikacji", THREE, SEVENTH, JAN, None, None),
            _order(FOUR, EIGHTH, JAN),
        ),
        frozenset(),
    ),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera\n40000002 tak brak klienta\n40000003 tak klient nieobecny",
            (
                (ONE, "tak", "wymiana routera"),
                (TWO, "tak", "brak klienta"),
                (THREE, "tak", "klient nieobecny"),
            ),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1374 r2 Ważne 1: numer z wiersza bez WYKONAWCA, z datą tekstem i z wyglądem z aplikacji dopisany drugi raz"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000004 tak wymiana routera",
            ((FOUR, "tak", "wymiana routera"),),
        ),
        ("klik",),
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000004 nie brak klienta",
            ((FOUR, "nie", "brak klienta"),),
        ),
        ("klik",),
    ],
).via(
    "ADR 0029: Zlecenie dopisane z raportu stoi pod zleceniami nadawcy, a jego wartości zmienia późniejszy mail"
)
@example(
    ((_order(ONE, EIGHTH, ADAM), _order(TWO, EIGHTH, JAN)), frozenset()),
    [
        _sent(
            EWA,
            "Raport 08.11.2026",
            "40000004 tak wymiana routera",
            ((FOUR, "tak", "wymiana routera"),),
        ),
        ("klik",),
    ],
).via(
    "ADR 0029: Zlecenie dopisane z raportu w nowym segmencie Wykonawcy na jego miejscu alfabetycznym"
)
@example(
    (
        (
            _order("40000011", BEFORE_ROLLOUT, ADAM),
            *(_order(f"400000{index}", BEFORE_ROLLOUT, ADAM) for index in range(12, 22)),
            _order(ONE, EIGHTH, JAN),
        ),
        frozenset(),
    ),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000011 tak wymiana routera",
            (("40000011", "tak", "wymiana routera"),),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1374 r3: numer zlecenia wklejonego przed dniem wdrożenia, nad dziesięcioma innymi, dopisany drugi raz"
)
@example(
    (
        (
            _order(ONE, SEVENTH, JAN),
            _order(TWO, SEVENTH, JAN),
            _order(THREE, EIGHTH, JAN),
        ),
        frozenset(),
    ),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera\n40000002 tak brak klienta\n40000004 tak klient nieobecny",
            (
                (ONE, "tak", "wymiana routera"),
                (TWO, "tak", "brak klienta"),
                (FOUR, "tak", "klient nieobecny"),
            ),
        ),
        ("klik",),
    ],
).via("ADR 0029: przy pomylonym temacie numer bez zlecenia się nie dopisuje")
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera\n40000004 tak brak klienta",
            ((ONE, "tak", "wymiana routera"), (FOUR, "tak", "brak klienta")),
        ),
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
            minute=1,
        ),
        ("klik",),
    ],
).via(
    "GLOSSARY: numer, którego Wykonawca nie powtórzył w poprawionym raporcie, się nie dopisuje"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000004 tak wymiana routera",
            ((FOUR, "tak", "wymiana routera"),),
        ),
        _sent(
            JAN,
            "Raport 06.11.2026",
            "40000004 nie brak klienta",
            ((FOUR, "nie", "brak klienta"),),
            minute=1,
        ),
        ("klik",),
    ],
).via(
    "GLOSSARY: najpóźniejszy mail z numerem bez zlecenia go nie dopisuje (dzień bez zleceń), więc wcześniejszy też nie"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000004 tak wymiana routera",
            ((FOUR, "tak", "wymiana routera"),),
        ),
        ("klik",),
        ("usuwa", 1),
        ("klik",),
    ],
).via(
    "ADR 0029, „Ręczna zmiana dalej wygrywa”: Zlecenia dopisanego, które tata usunął, stary mail nie dopisuje znowu"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera\n400000011 tak brak klienta",
            ((ONE, "tak", "wymiana routera"), (TYPO, "tak", "brak klienta")),
        ),
        ("klik",),
    ],
).via("ADR 0029: numer bez 8 cyfr numeru z aplikacji firmowej się nie dopisuje")
@example(
    ((_order(ONE, BEFORE_ROLLOUT, ADAM), _order(THREE, SIXTH, ADAM)), frozenset()),
    [
        _sent(
            ADAM,
            "Raport 31.10.2026",
            "40000002 tak 40000003 nie",
            ((TWO, "tak", ""), (THREE, "nie", "")),
        ),
        ("klik",),
        ("wkleja", _order(TWO, SIXTH, ADAM)),
        ("klik",),
        ("wkleja", _order(THREE, CLOSED_DAY, ADAM)),
        ("klik",),
        ("usuwa", 3),
        ("poprawka", 0, 0, 1, THREE),
        ("klik",),
    ],
).via(
    "przegląd #1406 r1 Ważne 1: wpis Centrum przepada, gdy numer ma dwa zlecenia, i liczy się potem jak wartość taty"
)
@example(
    (
        (
            _order(TWO, BEFORE_ROLLOUT, ADAM),
            _order(TWO, BEFORE_ROLLOUT, ADAM),
            _order(FOUR, SIXTH, ADAM),
            ("z aplikacji", TWO, SIXTH, ADAM, None, None),
            _order(ONE, SIXTH, ADAM),
        ),
        frozenset(),
    ),
    [
        _sent(
            EWA,
            "Raport 31.10.2026",
            "40000004 tak\n40000001 tak wymiana routera\n40000002 tak",
            ((FOUR, "tak", ""), (ONE, "tak", "wymiana routera"), (TWO, "tak", "")),
        ),
        ("klik",),
        ("dzień", 0, SEVENTH),
        _sent(
            EWA,
            "Raport 31.10.2026",
            "40000004 tak\n40000001 tak brak klienta",
            ((FOUR, "tak", ""), (ONE, "tak", "brak klienta")),
        ),
        ("poprawka", 0, 0, 0, ""),
        ("klik",),
        ("dzień", 0, BEFORE_ROLLOUT),
        ("klik",),
    ],
).via(
    "przegląd #1406 r1 Ważne 1: wpis Centrum przepada, gdy kliknięcie nie odczytało żadnego zlecenia numeru"
)
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(
            EWA,
            "Raport 08.11.2026",
            "40000001 tak wymiana routera",
            ((ONE, "tak", "wymiana routera"),),
        ),
        ("klik",),
        ("wykonawca", 0, JAN),
        ("klik",),
        ("wykonawca", 0, EWA),
        ("klik",),
        _sent(
            ADAM,
            "Raport 08.11.2026",
            "40000001 nie brak klienta",
            ((ONE, "nie", "brak klienta"),),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1406 r1 Drobne 1: tata oddał zlecenie i postawił je znów u Ewy, a pamięć dalej mówi, że to jego zmiana"
)
def test_wlasnosc_kazde_klikniecie_wpisania_raportow_trzyma_reguly_adr_0028_i_0029(
    start: Start, events: list[tuple[object, ...]]
) -> None:
    _play(start, events)


@settings(derandomize=True, database=None, deadline=None, max_examples=300)
@given(_body())
@example(("40000001 tak\nwymiana routera", ((ONE, "tak", "wymiana routera"),))).via(
    "przegląd #1247 r1 W1: opis Wpisu urywał się na końcu linii"
)
@example(
    (
        "40000001 tak wymiana routera 40000002 nie brak klienta 40000003\ntak montaż gniazda w salonie",
        (
            (ONE, "tak", "wymiana routera"),
            (TWO, "nie", "brak klienta"),
            (THREE, "tak", "montaż gniazda w salonie"),
        ),
    )
).via("przegląd #1247 r1 W1: zawinięcie linii przed tak gubiło Wpis")
@example(
    (
        "40000001 tak wymiana routera\n40000002 nie brak klienta\n\nJan",
        ((ONE, "tak", "wymiana routera"), (TWO, "nie", "brak klienta")),
    )
).via("przegląd #1247 r2 W1: podpis po pustej linii trafiał do CZYNNOŚCI ZREALIZOWANE")
@example(
    (
        "Zlecenie 40000001 tak wymiana routera\nZlecenie 40000002 nie brak klienta",
        ((ONE, "tak", "wymiana routera"), (TWO, "nie", "brak klienta")),
    )
).via("przegląd #1247 r2 W1: słowo przed numerem następnego Wpisu trafiało do opisu")
@example(
    (
        "40000001 tak wymiana routera\n\nDziekuje\nJan",
        ((ONE, "tak", "wymiana routera"),),
    )
).via("przegląd #1247 r2 W1: pożegnanie bez polskich liter trafiało do opisu")
@example(("40000001 nie", ((ONE, "nie", ""),))).via("Wpis bez opisu wpisuje tylko SKUTECZNE")
def test_wlasnosc_wpisy_raportu_napisane_jak_pisza_wykonawcy_trafiaja_do_swoich_komorek(
    body: tuple[str, tuple[tuple[str, str | None, str], ...]],
) -> None:
    text, said = body
    register = _start(
        tuple(_order(number, EIGHTH, JAN) for number in NUMBERS), frozenset()
    )
    window = Window.of(EIGHTH, ROLLOUT, CLOSED)
    read = _read_like_report_entering(register.lines, window)
    mail = ReportMail(
        MailId.of(SAME_ID),
        _address(ADDRESS[JAN]),
        "Raport 08.11.2026",
        text,
        FIRST_CLICK,
    )
    rows = {
        str(line.number): row
        for row, line in enumerate(register.lines, start=2)
        if line.ident
    }

    outcome = _core([mail], read, window, OwnEntries.EMPTY, frozenset())

    expected = {
        (rows[number], ReportColumn.SUCCESSFUL, verdict)
        for number, verdict, _ in said
        if verdict is not None
    }
    expected |= {
        (rows[number], ReportColumn.COMPLETED, text)
        for number, verdict, text in said
        if verdict is not None and text
    }
    assert {
        (change.order.row, change.column, change.value) for change in outcome.changes
    } == expected, text


def test_dzien_zlecen_dopisanych_z_raportu_nie_robi_pomylonego_tematu_kolejnego_raportu() -> (
    None
):
    register = _play(
        ((_order(ONE, EIGHTH, JAN), _order(TWO, SEVENTH, JAN)), frozenset()),
        [
            _sent(
                JAN,
                "Raport 08.11.2026",
                "40000003 tak wymiana routera\n40000004 tak brak klienta",
                ((THREE, "tak", "wymiana routera"), (FOUR, "tak", "brak klienta")),
            ),
            ("klik",),
            _sent(
                JAN,
                "Raport 07.11.2026",
                "40000002 tak montaż gniazda w salonie\n40000003 nie klient nieobecny\n40000004 nie",
                (
                    (TWO, "tak", "montaż gniazda w salonie"),
                    (THREE, "nie", "klient nieobecny"),
                    (FOUR, "nie", ""),
                ),
            ),
            ("klik",),
        ],
    )

    days = {line.number: line.day for line in register.lines if line.ident}
    assert (days[int(THREE)], days[int(FOUR)]) == (SEVENTH, SEVENTH), register.lines


def test_dni_w_przykladach_leza_tam_gdzie_mowia_ich_nazwy() -> None:
    today = FIRST_CLICK.date()

    assert NUMBERS_SINCE <= BEFORE_ROLLOUT < ROLLOUT, "z dnia przed wdrożeniem proces nie robi zleceń, ale czyta jego numery"
    assert CLOSED_PERIOD[0].weekday() == 1 and CLOSED_PERIOD[1] == CLOSED_PERIOD[0] + timedelta(days=6)
    assert CLOSED_PERIOD[0] <= ROLLOUT <= CLOSED_DAY <= CLOSED_PERIOD[1], "okres z Plikiem zbiorczym obejmuje dzień wdrożenia"
    assert NUMBERS_SINCE == CLOSED_PERIOD[1] + timedelta(days=1) - timedelta(days=7), (
        "numery czyta się od tygodnia przed pierwszym dniem otwartym, pierwszym po okresie z Plikiem zbiorczym"
    )
    assert NEXT_DAY.date() == today + timedelta(days=1) == NINTH, "nowy dzień robi dziś z jutra pierwszego kliknięcia"
    assert sum(_open(day, today) for day in ORDER_DAYS) > len(ORDER_DAYS) / 2, "wiersze INTERMAX najczęściej w dniach otwartych"
    assert sum(_open(day, today) for day in MAIL_DAYS) > len(MAIL_DAYS) / 2, "tematy maili najczęściej z dniem otwartym"


def test_numery_w_przykladach_maja_postac_numeru_z_aplikacji_firmowej_a_literowka_nie() -> None:
    assert all(number.isdigit() and len(number) == APP_NUMBER_DIGITS for number in NUMBERS)
    assert TYPO.isdigit() and len(TYPO) != APP_NUMBER_DIGITS


def test_opisy_wpisow_w_przykladach_nie_maja_cyfr_znaku_wpisu_pozegnania_ani_slowa_przed_numerem() -> None:
    words = {word.casefold() for phrase in PHRASES for word in phrase.split()}
    marks = {mark.casefold().strip(".,") for mark in SUCCESSFUL_BY_MARK if mark}
    prefixes = {prefix.strip().casefold() for prefix in ENTRY_PREFIXES if prefix}

    assert not any(character.isdigit() for phrase in PHRASES for character in phrase)
    assert words.isdisjoint(marks | prefixes | {"pozdrawiam", "pozdrowienia", "dziękuję", "dziekuje", "dzięki"}), words


def test_opis_bez_slowa_na_koncu_bywa_w_przykladach_rowny_recznej_wartosci_taty() -> None:
    assert "" in TAGS
    assert set(PHRASES) & set(TATA_COMPLETED)
