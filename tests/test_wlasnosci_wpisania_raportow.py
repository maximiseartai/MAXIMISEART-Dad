"""Wpisanie raportów (GLOSSARY.md: Wpisanie raportów, Wpis raportu, Przeniesienie zlecenia; ADR 0028 i ADR 0029) jako
własności Hypothesis na wygenerowanych stanach INTERMAX, pamięci własnych wpisów i Raportach wykonawców.

Przeglądy PR-ów Wpisania raportów (#1238–#1374) raz za razem wymyślały przypadek, którego testy autora nie miały: dzień
po dziś, wiersz bez ``WYKONAWCA``, pamięć z pliku Wydania v0.7.0/v0.8.0, ten sam Message-ID w dwóch mailach,
Przeniesienie, pomylony temat, opis Wpisu w kilku liniach i podpis pod nim. Tu takie stany buduje generator, a każdy
przypadek z rundy FAIL przeglądu jest jawnym przykładem (``@example``).

Kliknięcie idzie drogą procesu ``report_entering.enter_from_mail`` bez Excela i bez skrzynki: uporządkowane wiersze i
Dni uporządkowane z modelu arkusza zleceń (``raw_orders.ordered_rows`` i ``raw_orders.ordered_days`` od
``Window.start``, jak ``report_entering._orders`` i ``_ordered_days``), ``NUMER ZL.`` każdego czytanego wiersza
(``raw_orders.numbered_rows`` od ``Window.numbers_since``, jak ``report_entering._present``), pamięć z pliku sprzed
wersji 4 przez ``OlderOwnEntries.upgraded``, rdzeń ``enter_reports``, plan Przeniesień i Zleceń dopisanych z raportu
``raw_orders.plan_moves`` (jak ``intermax_cells.write_cells``) i zapis do modelu arkusza według ``MovePlan``. Model zna tożsamość każdego wiersza,
której Excel nie ma, więc wyrocznie biorą regułę wprost z ADR i GLOSSARY, a nie z kodu.

Przykłady są deterministyczne (``derandomize=True``, bez bazy przykładów), więc każdy przebieg i CI sprawdzają te same.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from itertools import pairwise

from hypothesis import example, given, settings
from hypothesis import strategies as st

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
    ReportInputs,
    ReportMail,
    ReportsOutcome,
    SenderAddress,
    UnknownNumber,
    Window,
    WorkerAddresses,
    enter_reports,
    order_number,
)

SHEET = "ZLECENIA OD 06_2025"
COLUMNS = OrderColumns(
    first=1, date=2, worker=3, last=9, devices=4, activities=5, contract_number=6
)
NUMBER_COLUMN, SUCCESSFUL_COLUMN, COMPLETED_COLUMN = 7, 8, 9
ORDERED_FACE = (ORDERED_FONT, float(ORDERED_SIZE))
APP_FACE = ("Arial", 10.0)

UNREAD = date(2026, 10, 29)
"""Dzień przed dniem wdrożenia: proces nie robi z niego zleceń, ale czyta jego numery (``NUMBERS_SINCE``)."""
CLOSED_DAY = date(2026, 10, 31)
"""Dzień okresu 27.10–2.11, który ma Plik zbiorczy."""
SIXTH, SEVENTH, EIGHTH, NINTH = (date(2026, 11, day) for day in (6, 7, 8, 9))
DAYS = (UNREAD, CLOSED_DAY, SIXTH, SEVENTH, EIGHTH, NINTH)
ORDER_DAYS = (*DAYS, SIXTH, SEVENTH, SEVENTH, EIGHTH, EIGHTH, EIGHTH)
"""Dni wierszy INTERMAX, najczęściej otwarte."""
MAIL_DAYS = (CLOSED_DAY, SIXTH, SEVENTH, SEVENTH, EIGHTH, EIGHTH, EIGHTH, NINTH)
"""Dni z tematu maila, najczęściej otwarte."""
ROLLOUT = date(2026, 10, 30)
NUMBERS_SINCE = date(2026, 10, 27)
"""Tydzień przed pierwszym dniem otwartym (3.11, pierwszy dzień po okresie z Plikiem zbiorczym): od niego Wpisanie
raportów czyta numer każdego wiersza, także sprzed dnia wdrożenia (ADR 0029, „Numer bez zlecenia to Zlecenie dopisane z
raportu”)."""
CLOSED = (period_of(CLOSED_DAY).token,)
CLOSED_PERIOD = (date(2026, 10, 27), date(2026, 11, 2))
"""Okres rozliczeniowy dnia ``CLOSED_DAY``, od wtorku do poniedziałku (GLOSSARY: Okres rozliczeniowy)."""
TAPA = timezone(timedelta(hours=1))
FIRST_CLICK = datetime(2026, 11, 8, 17, tzinfo=TAPA)
"""Dziś przy pierwszym kliknięciu jest 8.11; ``nowy dzień`` robi dziś z 9.11, czyli z jutra."""
NEXT_DAY = datetime(2026, 11, 9, 17, tzinfo=TAPA)

ADAM, EWA, JAN = Login("adam.inny"), Login("ewa.probna"), Login("jan.testowy")
WORKERS = (ADAM, EWA, JAN)
SPELLING = {ADAM: "Adam.Inny", EWA: "Ewa.Probna", JAN: "Jan.Testowy"}
"""``WYKONAWCA`` w pisowni taty."""
ADDRESS = {
    ADAM: "adam@przyklad.invalid",
    EWA: "ewa@przyklad.invalid",
    JAN: "jan@przyklad.invalid",
}
STRANGERS = ("obcy@inny.invalid", "ktos@inny.invalid")
NUMBERS = ("40000001", "40000002", "40000003", "40000004")
TYPO = "400000011"
"""Literówka w numerze z maila: 9 cyfr, czyli nie postać numeru z aplikacji firmowej (ADR 0029)."""
ADDED_DIGITS = 8
"""Tyle cyfr ma numer z aplikacji firmowej, a tylko taki numer staje się Zleceniem dopisanym z raportu (ADR 0029)."""


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
"""Opisy Wpisów: bez cyfr, bez ``tak``/``nie``, pożegnań i słów przed numerem, więc granice opisu daje tylko układ."""
TAGS = ("", "alfa", "beta", "gamma", "delta")
"""Słowo na końcu opisu, które zwykle odróżnia opisy dwóch maili, a bez niego opis bywa równy ręcznej wartości taty."""
MARKS: dict[str, str | None] = {
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
"""Znak Wpisu tak, jak go pisze Wykonawca → ``SKUTECZNE`` (GLOSSARY: Wpis raportu); ``None``: brak ``tak``/``nie``."""
ENDINGS = (
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
"""Koniec maila po ostatnim Wpisie: podpis po pustej linii, pożegnanie, separator podpisu, stopka i cytat."""
TATA_SUCCESSFUL = (None, None, "tak", "nie")
TATA_COMPLETED = (None, None, "montaż taty", "wymiana routera")
"""Ręczne wartości taty, także równe opisowi z maila."""


class _Look(Enum):
    """Wygląd wiersza arkusza zleceń: uporządkowany, Surowe zlecenie pod żółtym wierszem, wiersz z wyglądem z aplikacji
    między uporządkowanymi, pusty i żółty."""

    ORDERED = "uporządkowany"
    RAW = "surowy"
    AMONG = "z aplikacji między uporządkowanymi"
    BLANK = "pusty"
    YELLOW = "żółty"


@dataclass
class _Line:
    """Wiersz modelu arkusza zleceń. ``ident``: tożsamość zlecenia, której Excel nie zna (0: wiersz bez zlecenia)."""

    look: _Look
    ident: int = 0
    number: int | None = None
    day: date | None = None
    text_date: bool = False
    worker: str | None = None
    successful: str | None = None
    completed: str | None = None

    @property
    def started(self) -> datetime | str | None:
        """``DATA GODZ. POCZ.``: data z godziną, a w wierszu z datą tekstem jej zapis."""

        if self.day is None:
            return None
        if self.text_date:
            return f"{self.day:%d.%m.%Y} 09:30"
        return datetime(self.day.year, self.day.month, self.day.day, 9, 30)

    @property
    def dated(self) -> bool:
        """Uporządkowany wiersz z datą z godziną: tylko taki proces czyta jako zlecenie dnia."""

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
    """Wiedza wyroczni o wierszu: wartości, które Centrum (albo Wydanie v0.7.0/v0.8.0) wpisało do jego komórek, a od
    tamtej pory nikt ich nie zmienił (``written``), najmniejsza możliwa chwila najświeższego maila, którego opis Centrum
    wpisało do tego wiersza (``since``), oraz z tabeli przejść #1358: miejsce (Wykonawca i dzień) sprzed pierwszego
    Przeniesienia Centrum (``origin``), miejsce, w którym Centrum postawiło zlecenie (``placed``; ``None``: Centrum go nie
    przeniosło albo przeniosło z powrotem na ``origin``) i czy tata przeniósł je potem gdzie indziej (``overridden``)."""

    written: dict[ReportColumn, str] = field(default_factory=dict)
    since: datetime | None = None
    origin: tuple[Login, date] | None = None
    placed: tuple[Login, date] | None = None
    overridden: bool = False


@dataclass(frozen=True)
class _Sent:
    """Mail w skrzynce, jego Wykonawca (``None``: obcy adres) i Wpisy, które Wykonawca miał na myśli: numer,
    ``tak``/``nie`` (``None``: bez nich) i opis."""

    mail: ReportMail
    sender: Login | None
    said: tuple[tuple[str, str | None, str], ...]


def _facts(lines: Sequence[_Line]) -> tuple[RowFacts, ...]:
    """Wiersze arkusza od ostatniego w górę, bez wiersza nagłówków (wiersz 1), jak ``PasteArea.rows_from_bottom``."""

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
    """Arkusz po ręcznych zmianach taty w układzie Uporządkowania INTERMAX: dni po kolei, w dniu segmenty Wykonawców
    alfabetycznie (wiersz bez ``WYKONAWCA`` to segment bez nazwy) z jednym pustym wierszem między nimi, w segmencie
    zlecenia w dotychczasowej kolejności, potem wiersze z datą tekstem i z wyglądem z aplikacji, pusty wiersz po dniu,
    żółty wiersz i Surowe zlecenia na dole."""

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
    """Odczyt danych procesu: uporządkowane zlecenia i Dni uporządkowane od ``Window.start`` oraz ``NUMER ZL.`` każdego
    czytanego wiersza od ``Window.numbers_since`` (``ReportInputs.present``)."""

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
    )


def _read(lines: Sequence[_Line], window: Window) -> _Read:
    rows = _facts(lines)
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
        ReportInputs(
            tuple(mails),
            ADDRESSES,
            read.orders,
            window,
            memory,
            kept,
            read.present,
            read.ordered,
        )
    )


def _released(memory: OwnEntries, orders: tuple[RegisterOrder, ...]) -> OwnEntries:
    """Pamięć z pliku stanu Wydania v0.7.0/v0.8.0 (wersja 1) tak, jak ją dostaje rdzeń: proces czyta ją jako
    ``OlderOwnEntries`` i zamienia przy odczytanych zleceniach."""

    return OlderOwnEntries(memory).upgraded(orders)


def _planned(lines: Sequence[_Line], outcome: ReportsOutcome) -> MovePlan | MissingDays:
    """Plan Przeniesień i Zleceń dopisanych z raportu zapisu INTERMAX na arkuszu, który przeczytał proces, z wierszem
    dopisanego zlecenia jak ``intermax_cells._added_row``."""

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
    return plan_moves(_facts(lines), COLUMNS, moves, added)


APPLIED = frozenset({"changes", "moves", "added"})
"""Pola ``ReportsOutcome``, które zmieniają INTERMAX: model arkusza zapisuje każde (``_written``)."""
NOT_WRITTEN = frozenset({"problems", "workers", "mails", "memory", "notes"})


def _moved(lines: Sequence[_Line], plan: MovePlan, fresh: int) -> list[_Line]:
    """Arkusz po Przeniesieniach i dopisaniach według ``MovePlan``: wiersze od ``plan.first`` w kolejności planu, nowy
    pusty wiersz zamiast ``NewSeparator``, nowy ``WYKONAWCA`` i dzień przesunięty o ``shifts`` z tą samą godziną, a
    zamiast ``NewOrder`` nowy uporządkowany wiersz z tożsamością ``fresh`` plus jego miejsce na liście dopisań, z
    komórkami ``AddedRow`` i dniem wiersza ``model`` sprzed zapisu przesuniętym o ``days``."""

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
    """Arkusz po zapisie INTERMAX: komórki z ``changes``, potem wiersze przeniesione i dopisane według planu
    (``_moved``; Zlecenie dopisane z raportu ``outcome.added[i]`` dostaje tożsamość ``fresh + i``)."""

    after = [replace(line) for line in lines]
    for change in outcome.changes:
        after[change.order.row - 2].set(change.column, change.value)
    if not outcome.moves and not outcome.added:
        return after
    plan = _planned(lines, outcome)
    assert isinstance(plan, MovePlan)
    return _moved(after, plan, fresh)


@dataclass
class _Register:
    """INTERMAX taty w modelu arkusza i to, czego Excel nie wie: tożsamość wierszy i wiedza wyroczni o nich, oraz
    skrzynka raportów, pamięć Wpisania raportów (``released``: pamięć z pliku Wydania przed pierwszym kliknięciem),
    decyzje „Zostaw moją”, dzisiejszy dzień i zegar taty."""

    lines: list[_Line] = field(default_factory=list)
    truth: defaultdict[int, _Truth] = field(default_factory=lambda: defaultdict(_Truth))
    released: OwnEntries | None = None
    sent: list[_Sent] = field(default_factory=list)
    memory: OwnEntries = OwnEntries.EMPTY
    kept: frozenset[Kept] = frozenset()
    clock: datetime = FIRST_CLICK
    last: ReportsOutcome | None = None
    alone: dict[str, int] = field(default_factory=dict)
    """Wiersz każdego numeru, który odczytane zlecenia miały raz przy poprzednim kliknięciu."""
    touched: set[str] = field(default_factory=set)
    """Numery, które Centrum przeniosło albo dopisało: ich dzień sprzed Przeniesień zna tylko pamięć Centrum."""
    removed: dict[int | None, datetime] = field(default_factory=dict)
    """Numer jedynego wiersza, który tata usunął, a do którego Centrum wpisało opis maila, z chwilą najświeższego
    takiego maila (``_Truth.since``)."""
    changed: bool = False
    """Tata zmienił Wykonawcę, dzień albo wiersze od poprzedniego kliknięcia, więc arkusz trzeba ułożyć."""

    def pick(self, which: int) -> _Line | None:
        found = sorted(
            (line for line in self.lines if line.ident), key=lambda line: line.ident
        )
        return found[which % len(found)] if found else None

    def add(self, seed: tuple[object, ...]) -> _Line:
        """Wiersz z ``seed``: rodzaj, numer, dzień, Wykonawca, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``."""

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
        name = None if kind == "bez wykonawcy" else SPELLING[Login(worker)]
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
        self.changed = True
        return line

    def report_day(self, sent: _Sent, today: date) -> date | None:
        """Dzień z tematu Raportu wykonawcy od Wykonawcy z dniem od wdrożenia do dziś (dni, z których rdzeń czyta Wpisy,
        ADR 0028); ``None`` dla innego maila."""

        if sent.sender is None:
            return None
        return next(
            (
                day
                for day in MAIL_DAYS
                if ROLLOUT <= day <= today and sent.mail.subject in _subjects(day)[:4]
            ),
            None,
        )

    def said(self, number: int | None) -> list[tuple[_Sent, str | None, str]]:
        """Wpisy numeru ``number`` ze wszystkich maili skrzynki: mail, ``tak``/``nie`` i opis."""

        return [
            (sent, verdict, text)
            for sent in self.sent
            for found, verdict, text in sent.said
            if found == str(number)
        ]


def _start(seeds: Sequence[tuple[object, ...]], released: Iterable[int]) -> _Register:
    """INTERMAX z wierszy ``seeds`` w układzie Uporządkowania; w wierszach ``released`` niepuste komórki wpisało
    Wydanie v0.7.0/v0.8.0 i zapisało je w pamięci (plik w wersji 1) pod kluczem wiersza, także gdy numer miał drugie
    zlecenie, a przy dwóch wierszach z tym samym kluczem tylko w pierwszym, bo plik ma jeden wpis na komórkę. Wydanie
    pisało tylko do uporządkowanych zleceń z dniem od dnia wdrożenia do dnia pierwszego kliknięcia. Które z tych wartości
    Centrum liczy jako własne, rozstrzyga dopiero pierwsze kliknięcie (``_carry_identity``)."""

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
    register.lines, register.changed = _laid(register.lines), False
    return register


def _alone(orders: Iterable[RegisterOrder], lines: Sequence[_Line]) -> dict[str, int]:
    """Wiersz każdego numeru, który odczytane zlecenia mają raz."""

    found: defaultdict[str, list[int]] = defaultdict(list)
    for order in orders:
        found[order.key.number].append(lines[order.row.row - 2].ident)
    return {number: idents[0] for number, idents in found.items() if len(idents) == 1}


def _carry_identity(register: _Register, orders: tuple[RegisterOrder, ...]) -> None:
    """Tożsamość wiersza, którą Centrum przyjmuje, bo Excel nie odróżnia jej od zmiany Wykonawcy albo dnia (ADR 0029,
    „Numer w kilku zleceniach się nie przenosi”): numer z jednym zleceniem przy poprzednim kliknięciu i jednym teraz ma
    ten sam wiersz, także gdy tata usunął go i wkleił numer na nowo. Wpis pamięci z pliku Wydania liczy się tylko przy
    jedynym zleceniu numeru z tym samym dniem i Wykonawcą."""

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
        before = register.alone.get(number)
        if before is not None and before != ident:
            old = register.truth[before]
            register.truth[ident] = replace(old, written=dict(old.written))


def _open(day: date | None, today: date) -> bool:
    """Dzień otwarty dla Wpisania raportów wprost z ADR 0028: od dnia wdrożenia do dziś, bez okresu z Plikiem
    zbiorczym."""

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
    """Obserwacja kliknięcia z tabeli przejść #1358 (ADR 0029, „Ręczna zmiana dalej wygrywa”): gdy żadne odczytane
    zlecenie numeru nie stoi tam, gdzie Centrum postawiło przeniesione zlecenie, tata przeniósł je gdzie indziej."""

    for line in register.lines:
        truth = register.truth[line.ident] if line.ident else None
        if truth is not None and truth.placed is not None and not truth.overridden:
            places = {
                (order.key.worker, order.key.day)
                for order in orders
                if order.key.number == str(line.number)
            }
            truth.overridden = truth.placed not in places


def _known(lines: Iterable[_Line]) -> set[int | None]:
    """Numery, które INTERMAX ma w wierszu, który Wpisanie raportów czyta (ADR 0029, „Numer bez zlecenia to Zlecenie
    dopisane z raportu”): w Surowym zleceniu i w każdym wierszu z dniem od ``NUMBERS_SINCE``, także bez ``WYKONAWCA``, z
    datą tekstem, z wyglądem z aplikacji, sprzed dnia wdrożenia i na jutro."""

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
    """Niezmienniki kliknięcia przed zapisem, każdy z regułą, z której pochodzi:

    - N0 (ADR 0028, okres z Plikiem zbiorczym; ADR 0029, „Okno mówi, gdzie wolno pisać”): Centrum zmienia komórki,
      przenosi i dopisuje tylko zlecenia z dni otwartych i tylko na dzień otwarty;
    - N1 (GLOSSARY: Wpisanie raportów, „ręczna wartość taty zawsze wygrywa”): komórka zmienia się tylko, gdy jest pusta
      albo ma wartość, którą Centrum wpisało do tego wiersza, a od tamtej pory nikt jej nie zmienił;
    - N2 (ADR 0029, „Numer w kilku zleceniach się nie przenosi”): Centrum przenosi tylko zlecenie, którego numer
      odczytane dni (także po dziś i zamknięte) mają raz, a numer, który odczytane dni mają, nie jest nieznany;
    - N3 (ADR 0029, „Ręczna zmiana dalej wygrywa”): wiersz przenosi tylko mail nowego Wykonawcy z jego numerem,
      świeższy niż każdy mail, którego opis Centrum wpisało do tego wiersza, więc stary mail nie cofa zmiany taty, a
      zlecenia, które tata przeniósł gdzie indziej po Przeniesieniu Centrum, Centrum nie przenosi drugi raz;
    - N6 (zapis INTERMAX): zmiany trafiają tylko w uporządkowane wiersze, każda komórka raz, a Przeniesienie zaczyna się
      w uporządkowanym wierszu z datą i idzie, tak jak Zlecenie dopisane z raportu, do dnia arkusza zleceń, pod którego
      zlecenia plan zapisu może je postawić;
    - N8 (ADR 0029, „Numer bez zlecenia to Zlecenie dopisane z raportu”): Centrum dopisuje tylko numer, którego nie ma
      w żadnym czytanym wierszu (``_known``), każdy najwyżej raz;
    - N9 (GLOSSARY: Wpis raportu, Zlecenie dopisane z raportu): wpisana wartość to ``tak``/``nie`` i opis jednego Wpisu z
      maila o numerze tego wiersza, a pusta komórka zlecenia, któremu Centrum wpisało ten Wpis, dostaje też jego drugą
      wartość; Zlecenie dopisane z raportu ma ``WYKONAWCA`` nadawcy, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` jednego
      Wpisu z jego maila z tym numerem.
    """

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
                f"N6: zmiana poza uporządkowanym wierszem albo dwa razy w komórce: {change}"
            )
            continue
        if not (line.dated and _open(line.day, today)):
            faults.append(
                f"N0: zmiana komórki zlecenia z dnia, który nie jest otwarty: {change}, {line}"
            )
        current, written = (
            line.cell(change.column),
            register.truth[line.ident].written.get(change.column),
        )
        if current is not None and current != written:
            faults.append(
                f"N1: Centrum nadpisało ręczną wartość taty {current!r}: {change}, {line}"
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
                f"N9: wpisane wartości nie są jednym Wpisem z maila o numerze wiersza: {changed}, {line}"
            )
    sources = Counter(move.order.row for move in outcome.moves)
    for move in outcome.moves:
        line = lines[move.order.row - 2]
        if not line.dated or sources[move.order.row] > 1:
            faults.append(
                f"N6: Przeniesienie spoza uporządkowanego wiersza z datą: {move}"
            )
            continue
        if not (_open(line.day, today) and _open(move.day, today)):
            faults.append(
                f"N0: Przeniesienie z dnia albo na dzień, który nie jest otwarty: {move}, {line}"
            )
        if counted[OrderNumber(str(line.number))] != 1:
            faults.append(
                f"N2: Przeniesienie numeru, który odczytane dni mają {counted[OrderNumber(str(line.number))]} razy: {move}"
            )
        since, worker = register.truth[line.ident].since, Login(move.worker.lower())
        if not any(
            sent.sender == worker and (since is None or sent.mail.arrived > since)
            for sent, _, _ in register.said(line.number)
        ):
            faults.append(
                f"N3: Przeniesienie bez maila nowego Wykonawcy świeższego niż wpisany do wiersza ({since}): {move}"
            )
        if register.truth[line.ident].overridden:
            faults.append(
                f"N3: Przeniesienie zlecenia, które tata przeniósł po Przeniesieniu Centrum: {move}, {line}"
            )
    faults += [
        f"N2: numer, który odczytane dni mają, jako nieznany: {problem}"
        for problem in outcome.problems
        if isinstance(problem, UnknownNumber) and counted[problem.number]
    ]
    rows = {
        order.key: lines[order.row.row - 2]
        for order in orders
        if counted[order.key.number] == 1
    }
    faults += [
        f"N1: wartość, którą Centrum wpisało, a nikt jej nie zmienił, pokazana jako ręczna wartość taty: {problem}"
        for problem in outcome.problems
        if isinstance(problem, ManualDifference)
        and problem.key in rows
        and register.truth[rows[problem.key].ident].written.get(problem.column)
        == problem.manual
    ]
    known, added = _known(lines), Counter(order.number for order in outcome.added)
    for order in outcome.added:
        if order.sheet != SHEET:
            faults.append(
                f"N6: Zlecenie dopisane z raportu poza arkuszem zleceń: {order}"
            )
        if not _open(order.day, today):
            faults.append(
                f"N0: Zlecenie dopisane z raportu do dnia, który nie jest otwarty: {order}"
            )
        if (
            int(order.number) in known
            or added[order.number] > 1
            or len(order.number) != ADDED_DIGITS
        ):
            faults.append(
                f"N8: dopisany numer, który INTERMAX ma w czytanym wierszu, dopisany dwa razy albo nie z 8 cyfr: {order}"
            )
        faults += _added_faults(register, today, orders, order)
    if outcome.moves or outcome.added:
        plan = _planned(lines, outcome)
        if isinstance(plan, MissingDays):
            faults.append(
                f"N6: zapis odrzuca Przeniesienie albo dopisanie na dzień bez uporządkowanych zleceń: {plan}, {outcome}"
            )
    return faults


def _added_faults(
    register: _Register,
    today: date,
    orders: tuple[RegisterOrder, ...],
    order: OrderAdded,
) -> list[str]:
    """Niezmienniki Zlecenia dopisanego z raportu ``order`` (GLOSSARY: Zlecenie dopisane z raportu; ADR 0029), każdy w
    postaci ostrożnej: mail, który mógł je dopisać (``sources``), to mail nadawcy z jego numerem i jego wartościami, a
    zarzut stoi, gdy dotyczy każdego takiego maila.

    - N9: zlecenie ma ``WYKONAWCA`` nadawcy, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` jednego Wpisu z jego maila;
    - N8 („Nie powstaje, gdy temat raportu jest pomyłką”): mail nie ma co najmniej dwóch Wpisów numerów, które odczytane
      zlecenia mają tylko w innym dniu niż dzień dopisania, a których Centrum nie przenosiło ani nie dopisało;
    - N8 („… Wykonawca poprawił raport późniejszym mailem bez tego numeru”): nie ma późniejszego Raportu wykonawcy
      nadawcy z tym samym dniem, bez tego numeru, z każdym innym numerem maila, który ma Wpis do zlecenia nadawcy z tego
      dnia;
    - N8 („… albo najpóźniejszy mail z tym numerem go nie dopisuje”): żaden Raport wykonawcy z tym numerem nie przyszedł
      później;
    - N3 („Ręczna zmiana dalej wygrywa”): numer jedynego wiersza, który tata usunął po wpisie Centrum, wraca tylko z
      mailem świeższym niż każdy, którego opis Centrum wpisało do tego wiersza.
    """

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
            f"N9: Zlecenie dopisane z raportu nie jest jednym Wpisem z maila nadawcy z tym numerem: {order}"
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
                and all(at.key.day != order.day for at in placed[found])
                and found not in register.touched
                for found in others(sent)
            )
            >= 2
        )

    def corrected(sent: _Sent) -> bool:
        own = {
            found
            for found in others(sent)
            if found not in register.touched
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
        faults.append(f"N8: Zlecenie dopisane z raportu z pomylonym tematem: {order}")
    if all(corrected(sent) for sent in sources):
        faults.append(
            f"N8: Zlecenie dopisane z raportu, który Wykonawca poprawił późniejszym mailem: {order}"
        )
    if any(
        later.mail.arrived > newest and register.report_day(later, today) is not None
        for later, _, _ in register.said(number)
    ):
        faults.append(
            f"N8: Zlecenie dopisane starszym mailem niż najpóźniejszy Raport wykonawcy z tym numerem: {order}"
        )
    if number in register.removed and newest <= register.removed[number]:
        faults.append(
            f"N3: tata usunął wiersz numeru po wpisie Centrum, a stary mail dopisał go z powrotem: {order}"
        )
    return faults


def _layout_faults(lines: Sequence[_Line], received: dict[int, str]) -> list[str]:
    """N7 (GLOSSARY: Przeniesienie zlecenia; ADR 0029, „Wiersz idzie za zleceniem”): po zapisie każdy dzień ma układ
    Uporządkowania INTERMAX, który miał przed kliknięciem: każdy Wykonawca ma jeden segment, segmenty stoją
    alfabetycznie z jednym pustym wierszem między nimi, a zlecenie przeniesione do Wykonawcy (``received``: tożsamość →
    Wykonawca) stoi pod zleceniami, które ten Wykonawca miał w tym dniu."""

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
                    f"N7: dzień {day} rozdzielony wierszami {previous + 3}–{index + 1}"
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
                f"N7: dzień {day} ma segmenty {keys}, a nie jeden segment każdego Wykonawcy alfabetycznie"
            )
        for segment in segments:
            came = [line.ident in received for line in segment]
            if True in came and not all(came[came.index(True) :]):
                faults.append(
                    f"N7: zlecenie przeniesione w dniu {day} nie stoi pod zleceniami Wykonawcy: {segment}"
                )
    return faults


def _click(register: _Register) -> None:
    """Kliknięcie taty z wyroczniami N0–N9 (``_faults``, ``_layout_faults``) i zapis do modelu arkusza:

    - N4 (ADR 0028, „Każde kliknięcie liczy od nowa”): drugie kliknięcie bez nowych zdarzeń nic nie zmienia, a pamięć
      zostaje ta sama;
    - N5 (docstring ``enter_reports``): te same maile w odwrotnej kolejności dają ten sam wynik;
    - N8 (ADR 0029, „Numer bez zlecenia to Zlecenie dopisane z raportu” i „Okno mówi, gdzie wolno pisać”): kliknięcie
      nie dodaje wiersza numeru, który INTERMAX ma w czytanym wierszu (``_known``), a numerowi Zlecenia dopisanego z
      raportu dodaje jeden wiersz w dniu i u Wykonawcy z wyniku; model arkusza zapisuje każde pole wyniku, które
      zmienia INTERMAX.
    """

    if register.changed:
        register.lines, register.changed = _laid(register.lines), False
    window = Window.of(register.clock.date(), ROLLOUT, CLOSED)
    read = _read(register.lines, window)
    orders = read.orders
    _carry_identity(register, orders)
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
            f"N5: wynik zależy od kolejności maili: {outcome} wobec {reversed_outcome}"
        )
    unapplied = {found.name for found in fields(ReportsOutcome)} - APPLIED - NOT_WRITTEN
    if unapplied:
        faults.append(
            f"N8: wynik rdzenia ma pola {sorted(unapplied)}, których model arkusza w tym teście nie zapisuje"
        )
    assert not faults, "\n".join(faults)

    known = _known(register.lines)
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
            truth.since = arrived if truth.since is None else max(truth.since, arrived)
    for move in outcome.moves:
        line = register.lines[move.order.row - 2]
        truth, here, target = (
            register.truth[line.ident],
            _place(line),
            (Login(move.worker.lower()), move.day),
        )
        origin = (
            truth.origin if truth.placed is not None and truth.placed == here else here
        )
        truth.origin, truth.placed, truth.overridden = (
            origin,
            None if target == origin else target,
            False,
        )
    register.lines = _written(register.lines, outcome, fresh)
    faults = _layout_faults(register.lines, received)
    after = Counter(line.number for line in register.lines if line.ident)
    faults += [
        f"N8: numer {number} ma po kliknięciu {after[number]} wierszy, a miał {before[number]}"
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
                f"N8: zapis nie dopisał zlecenia {order} w jego dniu i u jego Wykonawcy: {new}"
            )
    again_read = _read(register.lines, window)
    again = _core(mails, again_read, window, outcome.memory, register.kept)
    if (again.changes, again.moves, again.added, again.memory) != (
        (),
        (),
        (),
        outcome.memory,
    ):
        faults.append(
            f"N4: powtórne kliknięcie zmienia INTERMAX albo pamięć: {again.changes}, {again.moves}, {again.added}"
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
    register.alone = _alone(again_read.orders, register.lines)
    register.touched |= {
        str(line.number) for line in register.lines if line.ident in received
    }
    for order in outcome.added:
        register.removed.pop(int(order.number), None)
    register.memory, register.released, register.last = outcome.memory, None, outcome
    register.clock += timedelta(hours=1)


Start = tuple[tuple[tuple[object, ...], ...], frozenset[int]]
"""Wiersze INTERMAX przed pierwszym kliknięciem (rodzaj, numer, dzień, Wykonawca, ``SKUTECZNE``, ``CZYNNOŚCI
ZREALIZOWANE``) i numery tych, do których wpisało Wydanie v0.7.0/v0.8.0."""


def _play(start: Start, events: Sequence[tuple[object, ...]]) -> _Register:
    """Zdarzenia po kolei: mail w skrzynce (także poprawiony), ręczne zmiany taty w INTERMAX (komórka, przepisanie Wpisu
    z maila, Wykonawca, dzień, usunięcie i wklejenie wiersza), „Zostaw moją”, nowy dzień i kliknięcie; daje INTERMAX po
    ostatnim zdarzeniu."""

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
                    line.worker, register.changed = SPELLING[Login(login)], True
            case ("dzień", int(which), date() as day):
                line = register.pick(which)
                if line is not None:
                    line.day, register.changed = day, True
            case ("usuwa", int(which)):
                line = register.pick(which)
                if line is not None:
                    register.lines.remove(line)
                    register.changed = True
                    since = register.truth[line.ident].since
                    if since is not None and all(
                        other.number != line.number for other in register.lines
                    ):
                        register.removed[line.number] = since
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


@st.composite
def _body(
    draw: st.DrawFn, numbers: Sequence[str] = NUMBERS
) -> tuple[str, tuple[tuple[str, str | None, str], ...]]:
    """Treść Raportu wykonawcy tak, jak piszą Wykonawcy, i Wpisy, które Wykonawca miał na myśli: 1–3 Wpisy z ``#`` albo
    bez, ze znakiem w dowolnej wielkości liter i z interpunkcją albo bez znaku, ze słowem przed numerem (``Zlecenie``,
    ``Nr``, ``zl.``) albo znacznikiem listy, z opisem łamanym w dowolnym miejscu, w jednej linii albo w kilku, z
    powitaniem i z podpisem, pożegnaniem, stopką albo cytatem na końcu (``_entries``: granice opisu). Wpis bez znaku
    zaczyna linię, bo tylko tak numer bez znaku zaczyna Wpis."""

    chosen = draw(
        st.lists(st.sampled_from(numbers), min_size=1, max_size=3, unique=True)
    )
    parts = [draw(st.sampled_from(("", "Dzień dobry,\n", "Witam\n\n")))]
    said = []
    for index, number in enumerate(chosen):
        mark = draw(st.sampled_from(tuple(MARKS)))
        phrase = draw(st.sampled_from(("", *PHRASES)))
        words = [*phrase.split(), draw(st.sampled_from(TAGS))] if phrase else []
        words = [word for word in words if word]
        if index:
            parts.append(
                draw(st.sampled_from(("\n", "\n\n", " ") if mark else ("\n", "\n\n")))
            )
        if mark:
            if not parts[-1] or parts[-1].endswith("\n"):
                parts.append(draw(st.sampled_from(("", "1. ", "- "))))
            parts.append(draw(st.sampled_from(("", "Zlecenie ", "Nr ", "zl. "))))
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
        said.append((number, MARKS[mark], " ".join(words)))
    parts.append(draw(st.sampled_from(ENDINGS)))
    return "".join(parts), tuple(said)


def _subjects(day: date) -> tuple[str, ...]:
    """Tematy maila z dniem ``day``: Raport wykonawcy w kilku zapisach daty, odpowiedź na Przypomnienie o raporcie, a
    także odpowiedź na raport, która Raportem wykonawcy nie jest."""

    return (
        f"Raport {day:%d.%m.%Y}",
        f"raport {day.day}.{day.month}.{day:%y}",
        f"RAPORT {day:%d_%m_%Y} r.",
        f"Re: Przypomnienie: raport za dzień {day:%d.%m.%Y}",
        f"Re: Raport {day:%d.%m.%Y}",
    )


UNREADABLE = ("Raport", "Raport za wczoraj", "Raport 08.11")
"""Tematy ze słowem ``raport`` bez dnia zleceń."""


@st.composite
def _mail(draw: st.DrawFn) -> tuple[object, ...]:
    """Mail w skrzynce, najczęściej Raport wykonawcy z dniem otwartym od Wykonawcy, a też z obcego adresu, z tematem
    dnia zamkniętego, sprzed wdrożenia i jutra, w innym zapisie daty, odpowiedź albo temat nieczytelny. Minuta
    przyjścia jest jedną z dwóch, a Message-ID co trzeci mail ma wspólny, więc dwa maile często przychodzą w tej samej
    chwili albo mają ten sam Message-ID (ustawia go nadawca)."""

    who = draw(st.sampled_from((*WORKERS, *WORKERS, *STRANGERS)))
    day = draw(st.sampled_from(MAIL_DAYS))
    forms = _subjects(day)
    unreadable = UNREADABLE[draw(st.integers(0, len(UNREADABLE) - 1))]
    subject = draw(
        st.sampled_from((*(forms[0],) * 5, *forms[1:], unreadable, unreadable))
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
"""Poprawiony mail (GLOSSARY: Zlecenie dopisane z raportu, „Wykonawca poprawił raport późniejszym mailem”): ten sam
nadawca i temat co jeden z maili w skrzynce, jego Wpisy bez jednego, czasem z innym numerem z ``tak`` zamiast niego."""


def _seeds(numbers: Sequence[str]) -> st.SearchStrategy[tuple[object, ...]]:
    """Wiersz INTERMAX: rodzaj (zwykle uporządkowane zlecenie), numer, dzień, Wykonawca i ręczne wartości taty."""

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
"""Rundy: zmiany taty, maile (także poprawione) i kliknięcie."""


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
            _order("40000011", UNREAD, ADAM),
            *(_order(f"400000{index}", UNREAD, ADAM) for index in range(12, 22)),
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
def test_wlasnosc_kazde_klikniecie_wpisania_raportow_trzyma_reguly_adr_0028_i_0029(
    start: Start, events: list[tuple[object, ...]]
) -> None:
    """Cel Maksa (ADR 0028 i 0029, GLOSSARY: Wpisanie raportów): dowolny INTERMAX z dniami okresu z Plikiem zbiorczym,
    otwartymi, dziś i jutro, z wierszami bez ``WYKONAWCA``, z datą tekstem, z wyglądem z aplikacji i Surowymi
    zleceniami, z pamięcią z pliku Wydania albo bez niej, dowolne maile Wykonawców i obcych adresów (ten sam Message-ID
    i ta sama chwila, nieczytelny i pomylony temat, odpowiedź na Przypomnienie) i dowolne ręczne zmiany taty między
    kliknięciami dają po każdym kliknięciu niezmienniki N0–N9 (``_click``)."""

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
def test_wlasnosc_wpisy_raportu_napisane_jak_pisza_wykonawcy_trafiaja_do_swoich_komorek(
    body: tuple[str, tuple[tuple[str, str | None, str], ...]],
) -> None:
    """GLOSSARY: Raport wykonawcy, Wpis raportu (US 19–26): Raport wykonawcy za dzień z jego zleceniami, napisany w
    dowolnym układzie z ``_body``, wpisuje każdemu zleceniu dokładnie ``tak``/``nie`` i opis Wpisu, który Wykonawca miał
    na myśli, a Wpis bez ``tak`` ani ``nie`` nie wpisuje niczego."""

    text, said = body
    register = _start(
        tuple(_order(number, EIGHTH, JAN) for number in NUMBERS), frozenset()
    )
    window = Window.of(EIGHTH, ROLLOUT, CLOSED)
    read = _read(register.lines, window)
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
    """ADR 0029 (przegląd #1374 r5): dzień Zlecenia dopisanego z raportu dał raport, a nie tata, więc nie liczy się do
    pomylonego tematu innych raportów. Dwa zlecenia dopisane do 8.11, które Jan potem zgłasza w raporcie za 7.11 obok
    zlecenia z 7.11, to dwa Przeniesienia na 7.11, a nie pomylony temat. Własność kliknięcia tego nie sprawdza, bo jej
    wyrocznie mówią tylko, czego Centrum zrobić nie wolno."""

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
