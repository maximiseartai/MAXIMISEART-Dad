"""Wpisanie raportów (GLOSSARY.md: Wpisanie raportów, Wpis raportu, Przeniesienie zlecenia; ADR 0028 i ADR 0029) jako
własności Hypothesis na wygenerowanych stanach INTERMAX, pamięci własnych wpisów i Raportach wykonawców.

Przeglądy PR-ów Wpisania raportów (#1238–#1374) raz za razem wymyślały przypadek, którego testy autora nie miały: dzień
po dziś, wiersz bez ``WYKONAWCA``, pamięć z pliku Wydania v0.7.0/v0.8.0, ten sam Message-ID w dwóch mailach,
Przeniesienie, pomylony temat, opis Wpisu w kilku liniach i podpis pod nim. Tu takie stany buduje generator, a każdy
przypadek z rundy FAIL przeglądu jest jawnym przykładem (``@example``).

Kliknięcie idzie drogą procesu ``report_entering.enter_from_mail`` bez Excela i bez skrzynki: uporządkowane wiersze i
Dni uporządkowane z modelu arkusza zleceń (``raw_orders.ordered_rows`` i ``raw_orders.ordered_days`` od
``Window.start``, jak ``report_entering._orders`` i ``_ordered_days``), pamięć z pliku sprzed wersji 4 przez
``OlderOwnEntries.upgraded``, rdzeń ``enter_reports``, plan Przeniesień ``raw_orders.plan_moves`` (jak
``intermax_cells.write_cells``) i zapis do modelu arkusza według ``MovePlan``. Model zna tożsamość każdego wiersza,
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
    MovePlan,
    NewSeparator,
    OrderColumns,
    RowFacts,
    ordered_days,
    ordered_rows,
    plan_moves,
    segment_key,
)
from rozliczenia.register_columns import ORDERED_FONT, ORDERED_SIZE
from rozliczenia.report_cells import OrderRow, ReportColumn
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
    RegisterOrder,
    ReportInputs,
    ReportMail,
    ReportsOutcome,
    SenderAddress,
    UnknownNumber,
    Window,
    WorkerAddresses,
    enter_reports,
)

SHEET = "ZLECENIA OD 06_2025"
COLUMNS = OrderColumns(first=1, date=2, worker=3, last=9, devices=4, activities=5, contract_number=6)
NUMBER_COLUMN, SUCCESSFUL_COLUMN, COMPLETED_COLUMN = 7, 8, 9
ORDERED_FACE = (ORDERED_FONT, float(ORDERED_SIZE))
APP_FACE = ("Arial", 10.0)

UNREAD = date(2026, 10, 29)
"""Dzień przed dniem wdrożenia: proces go nie czyta."""
CLOSED_DAY = date(2026, 10, 31)
"""Dzień okresu 27.10–2.11, który ma Plik zbiorczy."""
SIXTH, SEVENTH, EIGHTH, NINTH = (date(2026, 11, day) for day in (6, 7, 8, 9))
DAYS = (UNREAD, CLOSED_DAY, SIXTH, SEVENTH, EIGHTH, NINTH)
ORDER_DAYS = (*DAYS, SIXTH, SEVENTH, SEVENTH, EIGHTH, EIGHTH, EIGHTH)
"""Dni wierszy INTERMAX, najczęściej otwarte."""
MAIL_DAYS = (CLOSED_DAY, SIXTH, SEVENTH, SEVENTH, EIGHTH, EIGHTH, EIGHTH, NINTH)
"""Dni z tematu maila, najczęściej otwarte."""
ROLLOUT = date(2026, 10, 30)
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
ADDRESS = {ADAM: "adam@przyklad.invalid", EWA: "ewa@przyklad.invalid", JAN: "jan@przyklad.invalid"}
STRANGERS = ("obcy@inny.invalid", "ktos@inny.invalid")
NUMBERS = ("40000001", "40000002", "40000003", "40000004")


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

        return self.look is _Look.ORDERED and self.day is not None and not self.text_date

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
        cells = {column: CellFacts(value, face, False) for column, value in values.items() if value is not None}
        found.append(RowFacts(index, cells, False))
    return tuple(reversed(found))


def _laid(lines: Iterable[_Line]) -> list[_Line]:
    """Arkusz po ręcznych zmianach taty w układzie Uporządkowania INTERMAX: dni po kolei, w dniu segmenty Wykonawców
    alfabetycznie (wiersz bez ``WYKONAWCA`` to segment bez nazwy) z jednym pustym wierszem między nimi, w segmencie
    zlecenia w dotychczasowej kolejności, potem wiersze z datą tekstem i z wyglądem z aplikacji, pusty wiersz po dniu,
    żółty wiersz i Surowe zlecenia na dole."""

    orders = [line for line in lines if line.ident]
    sheet: list[_Line] = []
    for day in sorted({line.day for line in orders if line.look is not _Look.RAW and line.day is not None}):
        mine = [line for line in orders if line.day == day and line.look is not _Look.RAW]
        straight = [line for line in mine if line.dated]
        for index, key in enumerate(sorted({segment_key(line.worker) for line in straight})):
            sheet += [_Line(_Look.BLANK)] * bool(index) + [line for line in straight if segment_key(line.worker) == key]
        for line in mine:
            if not line.dated:
                sheet += [_Line(_Look.BLANK), line]
        sheet.append(_Line(_Look.BLANK))
    return [*sheet, _Line(_Look.YELLOW), *(line for line in orders if line.look is _Look.RAW)]


def _read(lines: Sequence[_Line], window: Window) -> tuple[tuple[RegisterOrder, ...], frozenset[OrderedDay]]:
    """Odczyt danych procesu: uporządkowane zlecenia i Dni uporządkowane od ``window.start``."""

    rows = _facts(lines)
    orders = []
    for row in ordered_rows(rows, COLUMNS, window.start):
        order = RegisterOrder.of(
            OrderRow(SHEET, row.number),
            number=row.value(NUMBER_COLUMN),
            started=row.value(COLUMNS.date),
            worker=row.value(COLUMNS.worker),
            successful=row.value(SUCCESSFUL_COLUMN),
            completed=row.value(COMPLETED_COLUMN),
        )
        if order is not None:
            orders.append(order)
    return tuple(orders), frozenset(OrderedDay(SHEET, day) for day in ordered_days(rows, COLUMNS, window.start))


def _core(
    mails: Sequence[ReportMail],
    orders: tuple[RegisterOrder, ...],
    window: Window,
    memory: OwnEntries,
    kept: frozenset[Kept],
    ordered: frozenset[OrderedDay],
) -> ReportsOutcome:
    return enter_reports(ReportInputs(tuple(mails), ADDRESSES, orders, window, memory, kept, ordered))


def _released(memory: OwnEntries, orders: tuple[RegisterOrder, ...]) -> OwnEntries:
    """Pamięć z pliku stanu Wydania v0.7.0/v0.8.0 (wersja 1) tak, jak ją dostaje rdzeń: proces czyta ją jako
    ``OlderOwnEntries`` i zamienia przy odczytanych zleceniach."""

    return OlderOwnEntries(memory).upgraded(orders)


def _planned(lines: Sequence[_Line], moves: dict[int, tuple[str, date]]) -> MovePlan | MissingDays:
    """Plan Przeniesień zapisu INTERMAX na arkuszu, który przeczytał proces."""

    return plan_moves(_facts(lines), COLUMNS, moves)


APPLIED = frozenset({"changes", "moves"})
"""Pola ``ReportsOutcome``, które zmieniają INTERMAX: model arkusza zapisuje każde (``_written``)."""
NOT_WRITTEN = frozenset({"problems", "workers", "mails", "memory", "notes"})


def _moved(lines: Sequence[_Line], plan: MovePlan) -> list[_Line]:
    """Arkusz po Przeniesieniach według ``MovePlan``: wiersze od ``plan.first`` w kolejności planu, nowy pusty wiersz
    zamiast ``NewSeparator``, nowy ``WYKONAWCA`` i dzień przesunięty o ``shifts`` z tą samą godziną."""

    after = list(lines[: plan.first - 2])
    for slot in plan.rows:
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


def _written(lines: Sequence[_Line], outcome: ReportsOutcome) -> list[_Line]:
    """Arkusz po zapisie INTERMAX: komórki z ``changes``, potem wiersze przeniesione według planu Przeniesień."""

    after = [replace(line) for line in lines]
    for change in outcome.changes:
        after[change.order.row - 2].set(change.column, change.value)
    if not outcome.moves:
        return after
    plan = _planned(lines, {move.order.row: (move.worker, move.day) for move in outcome.moves})
    assert isinstance(plan, MovePlan)
    return _moved(after, plan)


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
    changed: bool = False
    """Tata zmienił Wykonawcę, dzień albo wiersze od poprzedniego kliknięcia, więc arkusz trzeba ułożyć."""

    def pick(self, which: int) -> _Line | None:
        found = sorted((line for line in self.lines if line.ident), key=lambda line: line.ident)
        return found[which % len(found)] if found else None

    def add(self, seed: tuple[object, ...]) -> _Line:
        """Wiersz z ``seed``: rodzaj, numer, dzień, Wykonawca, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``."""

        kind, number, day, worker, successful, completed = seed
        assert isinstance(kind, str) and isinstance(number, str) and isinstance(day, date) and isinstance(worker, str)
        assert (successful is None or isinstance(successful, str)) and (completed is None or isinstance(completed, str))
        look = {"surowe": _Look.RAW, "z aplikacji": _Look.AMONG}.get(kind, _Look.ORDERED)
        name = None if kind == "bez wykonawcy" else SPELLING[Login(worker)]
        ident = max(self.truth, default=0) + 1
        line = _Line(look, ident, int(number), day, kind == "data tekstem", name, successful, completed)
        self.lines.append(line)
        self.truth[ident] = _Truth()
        self.changed = True
        return line

    def said(self, number: int | None) -> list[tuple[_Sent, str | None, str]]:
        """Wpisy numeru ``number`` ze wszystkich maili skrzynki: mail, ``tak``/``nie`` i opis."""

        return [
            (sent, verdict, text) for sent in self.sent for found, verdict, text in sent.said if found == str(number)
        ]


def _start(seeds: Sequence[tuple[object, ...]], released: Iterable[int]) -> _Register:
    """INTERMAX z wierszy ``seeds`` w układzie Uporządkowania; w wierszach ``released`` niepuste komórki wpisało
    Wydanie v0.7.0/v0.8.0 i zapisało je w pamięci (plik w wersji 1) pod kluczem wiersza, także gdy numer miał drugie
    zlecenie, a przy dwóch wierszach z tym samym kluczem tylko w pierwszym, bo plik ma jeden wpis na komórkę. Wydanie
    pisało tylko do uporządkowanych zleceń z dniem od dnia wdrożenia do dnia pierwszego kliknięcia."""

    register = _Register()
    lines = [register.add(seed) for seed in seeds]
    entries: dict[tuple[OrderKey, ReportColumn], OwnEntry] = {}
    for index in sorted(set(released)):
        line = lines[index % len(lines)]
        if not line.dated or line.day is None or line.worker is None or not ROLLOUT <= line.day <= FIRST_CLICK.date():
            continue
        key = OrderKey(OrderNumber(str(line.number)), line.day, Login(line.worker.lower()))
        for column in ReportColumn:
            value = line.cell(column)
            if value is not None and (key, column) not in entries:
                entries[key, column] = OwnEntry(key, column, value)
                register.truth[line.ident].written[column] = value
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
        keys = {order.key: register.lines[order.row.row - 2].ident for order in orders if order.key.number in now}
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

    return day is not None and ROLLOUT <= day <= today and not CLOSED_PERIOD[0] <= day <= CLOSED_PERIOD[1]


def _place(line: _Line) -> tuple[Login, date] | None:
    return None if line.worker is None or line.day is None else (Login(line.worker.lower()), line.day)


def _observe(register: _Register, orders: tuple[RegisterOrder, ...]) -> None:
    """Obserwacja kliknięcia z tabeli przejść #1358 (ADR 0029, „Ręczna zmiana dalej wygrywa”): gdy żadne odczytane
    zlecenie numeru nie stoi tam, gdzie Centrum postawiło przeniesione zlecenie, tata przeniósł je gdzie indziej."""

    for line in register.lines:
        truth = register.truth[line.ident] if line.ident else None
        if truth is not None and truth.placed is not None and not truth.overridden:
            places = {(order.key.worker, order.key.day) for order in orders if order.key.number == str(line.number)}
            truth.overridden = truth.placed not in places


def _faults(register: _Register, today: date, orders: tuple[RegisterOrder, ...], outcome: ReportsOutcome) -> list[str]:
    """Niezmienniki kliknięcia przed zapisem, każdy z regułą, z której pochodzi:

    - N0 (ADR 0028, okres z Plikiem zbiorczym; ADR 0029, „Okno mówi, gdzie wolno pisać”): Centrum zmienia komórki i
      przenosi tylko zlecenia z dni otwartych i tylko na dzień otwarty;
    - N1 (GLOSSARY: Wpisanie raportów, „ręczna wartość taty zawsze wygrywa”): komórka zmienia się tylko, gdy jest pusta
      albo ma wartość, którą Centrum wpisało do tego wiersza, a od tamtej pory nikt jej nie zmienił;
    - N2 (ADR 0029, „Numer w kilku zleceniach się nie przenosi”): Centrum przenosi tylko zlecenie, którego numer
      odczytane dni (także po dziś i zamknięte) mają raz, a numer, który odczytane dni mają, nie jest nieznany;
    - N3 (ADR 0029, „Ręczna zmiana dalej wygrywa”): wiersz przenosi tylko mail nowego Wykonawcy z jego numerem,
      świeższy niż każdy mail, którego opis Centrum wpisało do tego wiersza, więc stary mail nie cofa zmiany taty, a
      zlecenia, które tata przeniósł gdzie indziej po Przeniesieniu Centrum, Centrum nie przenosi drugi raz;
    - N6 (zapis INTERMAX): zmiany trafiają tylko w uporządkowane wiersze, każda komórka raz, a Przeniesienie zaczyna się
      w uporządkowanym wierszu z datą i idzie do dnia, pod którego zlecenia plan zapisu może je postawić;
    - N9 (GLOSSARY: Wpis raportu): wpisana wartość to ``tak``/``nie`` i opis jednego Wpisu z maila o numerze tego
      wiersza, a pusta komórka zlecenia, któremu Centrum wpisało ten Wpis, dostaje też jego drugą wartość.
    """

    lines = register.lines
    faults: list[str] = []
    counted = Counter(order.key.number for order in orders)
    cells = Counter((change.order.row, change.column) for change in outcome.changes)
    by_row: defaultdict[int, dict[ReportColumn, str]] = defaultdict(dict)
    for change in outcome.changes:
        line = lines[change.order.row - 2]
        by_row[change.order.row][change.column] = change.value
        if change.order.sheet != SHEET or line.look is not _Look.ORDERED or cells[change.order.row, change.column] > 1:
            faults.append(f"N6: zmiana poza uporządkowanym wierszem albo dwa razy w komórce: {change}")
            continue
        if not (line.dated and _open(line.day, today)):
            faults.append(f"N0: zmiana komórki zlecenia z dnia, który nie jest otwarty: {change}, {line}")
        current, written = line.cell(change.column), register.truth[line.ident].written.get(change.column)
        if current is not None and current != written:
            faults.append(f"N1: Centrum nadpisało ręczną wartość taty {current!r}: {change}, {line}")
    for row, changed in by_row.items():
        line = lines[row - 2]
        if not any(
            verdict is not None
            and changed.get(ReportColumn.SUCCESSFUL, verdict) == verdict
            and changed.get(ReportColumn.COMPLETED, text) == text
            and (ReportColumn.SUCCESSFUL in changed or line.successful is not None)
            and (ReportColumn.COMPLETED in changed or not text or line.completed is not None)
            for _, verdict, text in register.said(line.number)
        ):
            faults.append(f"N9: wpisane wartości nie są jednym Wpisem z maila o numerze wiersza: {changed}, {line}")
    sources = Counter(move.order.row for move in outcome.moves)
    for move in outcome.moves:
        line = lines[move.order.row - 2]
        if not line.dated or sources[move.order.row] > 1:
            faults.append(f"N6: Przeniesienie spoza uporządkowanego wiersza z datą: {move}")
            continue
        if not (_open(line.day, today) and _open(move.day, today)):
            faults.append(f"N0: Przeniesienie z dnia albo na dzień, który nie jest otwarty: {move}, {line}")
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
            faults.append(f"N3: Przeniesienie zlecenia, które tata przeniósł po Przeniesieniu Centrum: {move}, {line}")
    faults += [
        f"N2: numer, który odczytane dni mają, jako nieznany: {problem}"
        for problem in outcome.problems
        if isinstance(problem, UnknownNumber) and counted[problem.number]
    ]
    if outcome.moves:
        plan = _planned(lines, {move.order.row: (move.worker, move.day) for move in outcome.moves})
        if isinstance(plan, MissingDays):
            faults.append(
                f"N6: zapis odrzuca Przeniesienie na dzień bez uporządkowanych zleceń: {plan}, {outcome.moves}"
            )
    return faults


def _layout_faults(lines: Sequence[_Line], received: dict[int, str]) -> list[str]:
    """N7 (GLOSSARY: Przeniesienie zlecenia; ADR 0029, „Wiersz idzie za zleceniem”): po zapisie każdy dzień ma układ
    Uporządkowania INTERMAX, który miał przed kliknięciem: każdy Wykonawca ma jeden segment, segmenty stoją
    alfabetycznie z jednym pustym wierszem między nimi, a zlecenie przeniesione do Wykonawcy (``received``: tożsamość →
    Wykonawca) stoi pod zleceniami, które ten Wykonawca miał w tym dniu."""

    faults = []
    for day in sorted({line.day for line in lines if line.dated and line.day is not None}):
        at = [index for index, line in enumerate(lines) if line.dated and line.day == day]
        segments: list[list[_Line]] = [[lines[at[0]]]]
        for previous, index in pairwise(at):
            if index == previous + 1:
                segments[-1].append(lines[index])
                continue
            if index != previous + 2 or lines[previous + 1].look is not _Look.BLANK:
                faults.append(f"N7: dzień {day} rozdzielony wierszami {previous + 3}–{index + 1}")
            segments.append([lines[index]])
        keys = [sorted({segment_key(line.worker) for line in segment}) for segment in segments]
        if any(len(found) > 1 for found in keys) or [found[0] for found in keys] != sorted(
            {found[0] for found in keys}
        ):
            faults.append(f"N7: dzień {day} ma segmenty {keys}, a nie jeden segment każdego Wykonawcy alfabetycznie")
        for segment in segments:
            came = [line.ident in received for line in segment]
            if True in came and not all(came[came.index(True) :]):
                faults.append(f"N7: zlecenie przeniesione w dniu {day} nie stoi pod zleceniami Wykonawcy: {segment}")
    return faults


def _click(register: _Register) -> None:
    """Kliknięcie taty z wyroczniami N0–N9 (``_faults``, ``_layout_faults``) i zapis do modelu arkusza:

    - N4 (ADR 0028, „Każde kliknięcie liczy od nowa”): drugie kliknięcie bez nowych zdarzeń nic nie zmienia, a pamięć
      zostaje ta sama;
    - N5 (docstring ``enter_reports``): te same maile w odwrotnej kolejności dają ten sam wynik;
    - N8 (ADR 0029, „Numer bez zlecenia to Zlecenie dopisane z raportu” i „Okno mówi, gdzie wolno pisać”): kliknięcie
      nie dodaje wiersza numeru, który INTERMAX ma w wierszu czytanym od ``Window.start`` (tu od dnia wdrożenia) albo w
      Surowym zleceniu, a model arkusza zapisuje każde pole wyniku, które zmienia INTERMAX.
    """

    if register.changed:
        register.lines, register.changed = _laid(register.lines), False
    window = Window.of(register.clock.date(), ROLLOUT, CLOSED)
    orders, ordered = _read(register.lines, window)
    _carry_identity(register, orders)
    _observe(register, orders)
    memory = register.memory if register.released is None else _released(register.released, orders)
    mails = [sent.mail for sent in register.sent]
    outcome = _core(mails, orders, window, memory, register.kept, ordered)
    faults = _faults(register, register.clock.date(), orders, outcome)
    reversed_outcome = _core(mails[::-1], orders, window, memory, register.kept, ordered)
    if reversed_outcome != outcome:
        faults.append(f"N5: wynik zależy od kolejności maili: {outcome} wobec {reversed_outcome}")
    unapplied = {found.name for found in fields(ReportsOutcome)} - APPLIED - NOT_WRITTEN
    if unapplied:
        faults.append(f"N8: wynik rdzenia ma pola {sorted(unapplied)}, których model arkusza w tym teście nie zapisuje")
    assert not faults, "\n".join(faults)

    known = {
        line.number
        for line in register.lines
        if line.ident and (line.look is _Look.RAW or (line.day is not None and line.day >= ROLLOUT))
    }
    before = Counter(line.number for line in register.lines if line.ident)
    received = {register.lines[move.order.row - 2].ident: move.worker for move in outcome.moves}
    for change in outcome.changes:
        line = register.lines[change.order.row - 2]
        truth = register.truth[line.ident]
        truth.written[change.column] = change.value
        if change.column is ReportColumn.COMPLETED:
            arrived = min(sent.mail.arrived for sent, _, text in register.said(line.number) if text == change.value)
            truth.since = arrived if truth.since is None else max(truth.since, arrived)
    for move in outcome.moves:
        line = register.lines[move.order.row - 2]
        truth, here, target = register.truth[line.ident], _place(line), (Login(move.worker.lower()), move.day)
        origin = truth.origin if truth.placed is not None and truth.placed == here else here
        truth.origin, truth.placed, truth.overridden = origin, None if target == origin else target, False
    register.lines = _written(register.lines, outcome)
    faults = _layout_faults(register.lines, received)
    after = Counter(line.number for line in register.lines if line.ident)
    faults += [
        f"N8: numer {number} ma po kliknięciu {after[number]} wierszy, a miał {before[number]}"
        for number in known
        if after[number] > before[number]
    ]
    again_orders, again_ordered = _read(register.lines, window)
    again = _core(mails, again_orders, window, outcome.memory, register.kept, again_ordered)
    if (again.changes, again.moves, again.memory) != ((), (), outcome.memory):
        faults.append(f"N4: powtórne kliknięcie zmienia INTERMAX albo pamięć: {again.changes}, {again.moves}")
    assert not faults, "\n".join(faults)

    for line in register.lines:
        if line.ident:
            truth = register.truth[line.ident]
            truth.written = {column: value for column, value in truth.written.items() if line.cell(column) == value}
    register.alone = _alone(again_orders, register.lines)
    register.memory, register.released, register.last = outcome.memory, None, outcome
    register.clock += timedelta(hours=1)


Start = tuple[tuple[tuple[object, ...], ...], frozenset[int]]
"""Wiersze INTERMAX przed pierwszym kliknięciem (rodzaj, numer, dzień, Wykonawca, ``SKUTECZNE``, ``CZYNNOŚCI
ZREALIZOWANE``) i numery tych, do których wpisało Wydanie v0.7.0/v0.8.0."""


def _play(start: Start, events: Sequence[tuple[object, ...]]) -> None:
    """Zdarzenia po kolei: mail w skrzynce, ręczne zmiany taty w INTERMAX (komórka, przepisanie Wpisu z maila,
    Wykonawca, dzień, usunięcie i wklejenie wiersza), „Zostaw moją”, nowy dzień i kliknięcie."""

    register = _start(*start)
    for event in events:
        match event:
            case ("mail", str(who), str(subject), int(minute), str(message_id), str(text), tuple(said)):
                sender = Login(who) if who in ADDRESS else None
                address = _address(ADDRESS[Login(who)] if sender is not None else who)
                mail_id = MailId.of(message_id or f"<{len(register.sent)}@przyklad.invalid>")
                mail = ReportMail(mail_id, address, subject, text, register.clock + timedelta(minutes=minute))
                register.sent.append(_Sent(mail, sender, said))
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


@st.composite
def _body(draw: st.DrawFn) -> tuple[str, tuple[tuple[str, str | None, str], ...]]:
    """Treść Raportu wykonawcy tak, jak piszą Wykonawcy, i Wpisy, które Wykonawca miał na myśli: 1–3 Wpisy z ``#`` albo
    bez, ze znakiem w dowolnej wielkości liter i z interpunkcją albo bez znaku, ze słowem przed numerem (``Zlecenie``,
    ``Nr``, ``zl.``) albo znacznikiem listy, z opisem łamanym w dowolnym miejscu, w jednej linii albo w kilku, z
    powitaniem i z podpisem, pożegnaniem, stopką albo cytatem na końcu (``_entries``: granice opisu). Wpis bez znaku
    zaczyna linię, bo tylko tak numer bez znaku zaczyna Wpis."""

    numbers = draw(st.lists(st.sampled_from(NUMBERS), min_size=1, max_size=3, unique=True))
    parts = [draw(st.sampled_from(("", "Dzień dobry,\n", "Witam\n\n")))]
    said = []
    for index, number in enumerate(numbers):
        mark = draw(st.sampled_from(tuple(MARKS)))
        phrase = draw(st.sampled_from(("", *PHRASES)))
        words = [*phrase.split(), draw(st.sampled_from(TAGS))] if phrase else []
        words = [word for word in words if word]
        if index:
            parts.append(draw(st.sampled_from(("\n", "\n\n", " ") if mark else ("\n", "\n\n"))))
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
                parts.append(draw(st.sampled_from((" ", ", ", " - ", "\n"))) if mark else " ")
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
    subject = draw(st.sampled_from((*(forms[0],) * 5, *forms[1:], unreadable, unreadable)))
    text, said = draw(_body())
    message_id = draw(st.sampled_from(("", "", "<a@przyklad.invalid>")))
    return ("mail", who, subject, draw(st.integers(0, 1)), message_id, text, said)


def _seeds(numbers: Sequence[str]) -> st.SearchStrategy[tuple[object, ...]]:
    """Wiersz INTERMAX: rodzaj (zwykle uporządkowane zlecenie), numer, dzień, Wykonawca i ręczne wartości taty."""

    kinds = ("zlecenie", "zlecenie", "zlecenie", "zlecenie", "bez wykonawcy", "data tekstem", "z aplikacji", "surowe")
    return st.tuples(
        st.sampled_from(kinds),
        st.sampled_from(numbers),
        st.sampled_from(ORDER_DAYS),
        st.sampled_from(WORKERS),
        st.sampled_from(TATA_SUCCESSFUL),
        st.sampled_from(TATA_COMPLETED),
    )


_START = st.tuples(
    st.lists(_seeds(NUMBERS), min_size=2, max_size=7).map(tuple), st.frozensets(st.integers(0, 5), max_size=3)
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
_EVENTS = st.lists(st.tuples(st.lists(_TATA, max_size=3), st.lists(_mail(), max_size=3)), min_size=1, max_size=5).map(
    lambda rounds: [event for tata, mails in rounds for event in (*tata, *mails, ("klik",))]
)
"""Rundy: zmiany taty, maile i kliknięcie."""


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
    number: str, day: date, worker: str, successful: str | None = None, completed: str | None = None
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
).via("przegląd #1238 r2 Ważne 1: dwa obce adresy z jednym Message-ID wywracały całe Wpisanie raportów")
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(JAN, "Raport", "40000001 tak wymiana", ((ONE, "tak", "wymiana"),), message_id=SAME_ID),
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
).via("przegląd #1302 r1 Ważne 1: ostrzeżenie o nieczytelnym temacie zależało od kolejności maili z jednym Message-ID")
@example(
    ((_order(ONE, EIGHTH, ADAM), _order(TWO, EIGHTH, EWA), _order(THREE, EIGHTH, EWA)), frozenset()),
    [
        _sent(EWA, "Raport 08.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),)),
        _sent(JAN, "Raport 08.11.2026", "40000002 tak brak klienta", ((TWO, "tak", "brak klienta"),)),
        ("klik",),
    ],
).via("przegląd #1358 r1 Ważne 1: dwa Przeniesienia w jednym dniu dzieliły segment Wykonawcy na dwa")
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(JAN, "Raport 08.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),)),
        ("klik",),
        ("wykonawca", 0, EWA),
        ("klik",),
    ],
).via("przegląd #1358 r1 Ważne 2: ręczna zmiana WYKONAWCA po wpisie cofana tym samym starym mailem")
@example(
    ((_order(ONE, SEVENTH, ADAM), _order(THREE, EIGHTH, ADAM), _order(TWO, EIGHTH, JAN)), frozenset()),
    [
        _sent(ADAM, "Raport 08.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),)),
        _sent(JAN, "Raport 07.11.2026", "40000002 tak brak klienta", ((TWO, "tak", "brak klienta"),)),
        ("klik",),
    ],
).via("przegląd #1367 r1 Ważne 1: Przeniesienie na dzień, który zapis uznawał za pusty, zatrzymywało całe kliknięcie")
@example(
    ((_order(ONE, SIXTH, EWA), _order(ONE, SEVENTH, JAN), _order(TWO, SEVENTH, ADAM)), frozenset()),
    [
        _sent(JAN, "Raport 07.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),)),
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
    ((_order(ONE, SEVENTH, JAN), _order(ONE, SIXTH, EWA, "tak", "montaż taty")), frozenset()),
    [
        _sent(EWA, "Raport 06.11.2026", "40000001 nie brak klienta", ((ONE, "nie", "brak klienta"),)),
        _sent(JAN, "Raport 07.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),), minute=1),
        ("klik",),
        ("zostaw",),
        ("usuwa", 0),
        ("klik",),
    ],
).via("przegląd #1367 r3 Ważne 1: wpisy Jana przeszły na zlecenie Ewy, a stary mail nadpisał ręczne „tak” taty")
@example(
    ((_order(ONE, SIXTH, JAN), _order(ONE, SEVENTH, EWA, "tak", "montaż taty")), frozenset()),
    [
        _sent(EWA, "Raport 07.11.2026", "40000001 nie brak klienta", ((ONE, "nie", "brak klienta"),)),
        _sent(JAN, "Raport 06.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),), minute=1),
        ("klik",),
        ("zostaw",),
        ("usuwa", 0),
        ("klik",),
    ],
).via("przegląd #1367 r3 Ważne 1 z wierszem Jana nad wierszem Ewy: wpisy Jana nie przechodzą na zlecenie Ewy")
@example(
    ((_order(ONE, EIGHTH, JAN),), frozenset()),
    [
        _sent(EWA, "Raport 08.11.2026", "40000001 tak wymiana routera", ((ONE, "tak", "wymiana routera"),)),
        ("klik",),
        ("wykonawca", 0, JAN),
        ("klik",),
        _sent(EWA, "Raport 08.11.2026", "40000001 nie brak klienta", ((ONE, "nie", "brak klienta"),)),
        ("klik",),
    ],
).via("ADR 0029: zlecenia, które tata przeniósł z powrotem po Przeniesieniu Centrum, świeższy mail nie przenosi")
@example(
    ((_order(ONE, SEVENTH, JAN), _order(ONE, NINTH, JAN), _order(TWO, EIGHTH, EWA)), frozenset()),
    [
        _sent(
            JAN,
            "Raport 08.11.2026",
            "40000001 tak montaż gniazda w salonie",
            ((ONE, "tak", "montaż gniazda w salonie"),),
        ),
        ("klik",),
    ],
).via("przegląd #1367 r3 Ważne 2: duplikat z jutra był niewidoczny, więc Centrum przeniosło zlecenie z 7.11")
@example(
    (
        (_order(ONE, EIGHTH, JAN, "tak", "wymiana routera"), _order(ONE, SEVENTH, ADAM, "tak", "montaż taty")),
        frozenset({0}),
    ),
    [
        ("usuwa", 0),
        _sent(ADAM, "Raport 07.11.2026", "40000001 nie brak klienta", ((ONE, "nie", "brak klienta"),)),
        ("klik",),
    ],
).via("przegląd #1367 r4 Ważne 1: pamięć z pliku v0.8.0 przeszła na inne zlecenie numeru i nadpisała ręczne „tak” taty")
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
            ((ONE, "tak", "wymiana routera"), (TWO, "tak", "brak klienta"), (THREE, "tak", "klient nieobecny")),
        ),
        ("klik",),
    ],
).via(
    "przegląd #1374 r2 Ważne 1: numer z wiersza bez WYKONAWCA, z datą tekstem i z wyglądem z aplikacji dopisany drugi raz"
)
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
        ((ONE, "tak", "wymiana routera"), (TWO, "nie", "brak klienta"), (THREE, "tak", "montaż gniazda w salonie")),
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
@example(("40000001 tak wymiana routera\n\nDziekuje\nJan", ((ONE, "tak", "wymiana routera"),))).via(
    "przegląd #1247 r2 W1: pożegnanie bez polskich liter trafiało do opisu"
)
def test_wlasnosc_wpisy_raportu_napisane_jak_pisza_wykonawcy_trafiaja_do_swoich_komorek(
    body: tuple[str, tuple[tuple[str, str | None, str], ...]],
) -> None:
    """GLOSSARY: Raport wykonawcy, Wpis raportu (US 19–26): Raport wykonawcy za dzień z jego zleceniami, napisany w
    dowolnym układzie z ``_body``, wpisuje każdemu zleceniu dokładnie ``tak``/``nie`` i opis Wpisu, który Wykonawca miał
    na myśli, a Wpis bez ``tak`` ani ``nie`` nie wpisuje niczego."""

    text, said = body
    register = _start(tuple(_order(number, EIGHTH, JAN) for number in NUMBERS), frozenset())
    window = Window.of(EIGHTH, ROLLOUT, CLOSED)
    orders, ordered = _read(register.lines, window)
    mail = ReportMail(MailId.of(SAME_ID), _address(ADDRESS[JAN]), "Raport 08.11.2026", text, FIRST_CLICK)
    rows = {str(line.number): row for row, line in enumerate(register.lines, start=2) if line.ident}

    outcome = _core([mail], orders, window, OwnEntries.EMPTY, frozenset(), ordered)

    expected = {(rows[number], ReportColumn.SUCCESSFUL, verdict) for number, verdict, _ in said if verdict is not None}
    expected |= {
        (rows[number], ReportColumn.COMPLETED, text) for number, verdict, text in said if verdict is not None and text
    }
    assert {(change.order.row, change.column, change.value) for change in outcome.changes} == expected, text
