"""Surowe zlecenia na dole arkusza zleceń Rejestru zleceń: rozpoznanie i plan dnia, czyste funkcje faktów arkusza.

Rozpoznanie (``recognize``) dostaje wiersze arkusza zleceń od dołu i oddaje blok Surowych zleceń (``RawBlock``),
przeszkodę, przez którą bloku nie da się uporządkować (``Obstacle``), albo ``None``, gdy na dole arkusza nie ma
wierszy z wyglądem z aplikacji ani nie ma ich nad ostatnimi uporządkowanymi wierszami. Wiersz uporządkowany ma w
kolumnach zlecenia (od ``AKCJE`` do ``UWAGI``, bez ``WYKONAWCA``, którą tata pisze też Calibri 9) choć jedną
komórkę z wartością w Calibri 8; wiersz z wartościami bez niej ma wygląd z aplikacji. Blok to wiersze z
wartościami pod ostatnim uporządkowanym wierszem. Pierwszy wiersz bloku jest przesunięty o dwie kolumny w lewo,
gdy w ``DATA GODZ. POCZ.`` nie ma daty; gdy data stoi na miejscu (ktoś przesunął wiersz ręcznie), wiersz się nie
przesuwa. Miejsce dnia wyznacza żółty wiersz, którym tata oddziela dni: najniższy pusty wiersz między
ostatnim uporządkowanym a blokiem, w którym co najmniej połowa kolumn zlecenia ma żółte wypełnienie. Kolumna bez
komórki ma wypełnienie stylu wiersza: u taty żółty wiersz to zwykle styl całego wiersza bez żadnej komórki.
Sam blok, bez przeglądu nad nim i bez przeszkód, oddaje ``pasted``: z niego Przygotowanie pliku zbiorczego wie,
z których dni są Surowe zlecenia. Ten sam blok daje ``pasted_rows``: jego wiersze jako fakty, które Kopia wejścia
Uporządkowania niesie, a ``shifted_row`` wiersz, którego komórki rozpoznanie czyta dwie kolumny na lewo od swojego
nagłówka.

Pamięć reguły danych zna każdy wiersz w jednym położeniu (decyzja Maksa z 5.11.2026, ADR 0025): pierwszy wiersz bloku
wklejenia (``first_in_block``) przesunięty o ``SHIFT`` kolumn w lewo, bo tak przychodzi z aplikacji firmowej zawsze (fakt
domeny: przesunięty jest tylko pierwszy wklejony wiersz), a każdy inny pod nagłówkiem. Siatka (``both_positions``) daje
oba położenia pierwszemu wierszowi bloku, którego przesunięcia nie widać (``shift_visible``), i innemu wierszowi ze
śladem przesunięcia, a o tym drugim (``RowPositions.traced``) Logi mówią, że fakt jest złamany. Położenia wiersza
daje jedna reguła (``row_positions``).

Przeszkody: wiersz z wyglądem z aplikacji nad uporządkowanym wierszem, Surowe zlecenie bez daty z godziną albo bez
Wykonawcy i blok z więcej niż jednego dnia. Pierwsza wymaga przeglądu nad blokiem (``_above``): od ostatniego
uporządkowanego wiersza w górę, aż ``_EARLIER_ROWS`` kolejnych uporządkowanych wierszy ma dzień wcześniejszy niż
granica przeglądu, tu dzień bloku (bez bloku: dzień ostatniego uporządkowanego wiersza z datą). Pojedyncze
wcześniejsze dni (usterka z poprzedniego dnia dopisana pod dniem) nie kończą przeglądu. Ten sam przegląd z granicą
``since`` daje w ``ordered_days`` Dni uporządkowane arkusza: dzień, którego w przeglądzie stoją dwa kolejne
uporządkowane wiersze z jego datą albo jeden, pod którym nie ma wiersza wcześniejszego dnia; zlecenie na jutro
wpisane w dzisiejszym dniu nie czyni jutra uporządkowanym. Granicę i arkusze, w których się ich szuka, wybiera
``intermax_ordering`` jednakowo dla Planowania i karty Uporządkowania INTERMAX w Centrum rozliczeń.

Plan dnia (``plan_day``) z bloku wyznacza docelowe wiersze zleceń: jeden pusty wiersz pod żółtym wierszem albo
10 pustych pod ostatnim uporządkowanym zleceniem, segmenty Wykonawców w kolejności alfabetycznej z jednym
pustym wierszem między nimi, w segmencie od najwcześniejszej godziny, a przy tej samej godzinie w kolejności z
aplikacji. Operatora rozpoznaje jedno rozpoznanie nazwy w ``CZYNNOŚCI`` (``_operator``): bez wielkości liter,
spacji, myślników i dopisku ``S.A.``. Każde zlecenie dostaje Kolor operatora z tabeli ``_OPERATOR_COLORS``, a
usterka (``URZĄDZENIA``) różowe ``URZĄDZENIA``. Instalacja hurt operatora z tabeli ``_ENTRY_RULES`` dostaje Wpis
urządzenia i czynności INTERMAX: ``URZĄDZENIA`` z tabeli i dopisek za nazwą operatora z aplikacji w ``CZYNNOŚCI``.
Plan wyznacza też wiersz widoku po otwarciu: pierwsze zlecenie dzisiejszego dnia, a bez zleceń dziś pierwsze
zlecenie ostatniego wcześniejszego dnia ze zleceniami, szukane od dołu tak jak przegląd nad blokiem. Fakty nie
zawierają treści wierszy poza datą i Wykonawcą potrzebnymi do kolejności oraz nazwą operatora i rodzajem zlecenia.

Plan Przeniesień zleceń Wpisania raportów (``plan_moves``, ADR 0029) stawia przeniesione i dopisane zlecenie w układzie
uporządkowanego dnia tą samą regułą segmentów (``segment_key``): pod ostatnim zleceniem segmentu nowego Wykonawcy
albo w nowym segmencie na miejscu alfabetycznym, z jednym pustym wierszem między segmentami.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from functools import cached_property
from itertools import chain, groupby
from types import MappingProxyType
from typing import Final, TypeVar

from .register_columns import ORDERED_FONT, ORDERED_SIZE
from .row_positions import AbovePaste, RowPositions
from .text import normalize_text

SHIFT: Final = 2
"""O tyle kolumn w lewo przychodzi pierwszy wiersz wklejenia."""
_BLANK_ROWS_WITHOUT_YELLOW: Final = 10
_EARLIER_ROWS: Final = 10
"""Tyle kolejnych uporządkowanych wierszy z wcześniejszym dniem kończy przegląd nad blokiem."""
_COMPANY_SUFFIX: Final = re.compile(r"[\s-]*S\.?\s*A\.?\s*$", re.IGNORECASE)
"""Dopisek ``S.A.`` za nazwą operatora (także ``SA``, ``S.A``), oddzielony spacją, myślnikiem albo niczym: ``NetiaSA``."""
_Row = TypeVar("_Row")


@dataclass(frozen=True)
class OrderColumns:
    """Kolumny arkusza zleceń (od 1) po nagłówkach z wiersza 1: kolumny zlecenia od ``first`` do ``last`` (UWAGI).

    ``devices``, ``activities`` i ``contract_number`` to ``URZĄDZENIA``, ``CZYNNOŚCI`` i ``NUMER UMOWY``, w których
    staje Kolor operatora.
    """

    first: int
    date: int
    worker: int
    last: int
    devices: int
    activities: int
    contract_number: int

    @cached_property
    def look_columns(self) -> frozenset[int]:
        """Kolumny, z których krój wiersza mówi, czy jest uporządkowany (``look``): od ``first`` do ``last`` bez
        ``worker``, którą tata pisze też Calibri 9."""

        return frozenset(range(self.first, self.last + 1)) - {self.worker}


@dataclass(frozen=True)
class OperatorColor:
    """Kolor operatora zlecenia: wypełnienie (RGB) ``CZYNNOŚCI``, ``NUMER UMOWY`` i ``URZĄDZENIA``; ``None``: bez."""

    activities: str | None = None
    contract_number: str | None = None
    devices: str | None = None


_OPERATOR_COLORS: Final[Mapping[str | None, OperatorColor]] = MappingProxyType(
    {
        "tmobile": OperatorColor("99FF66", "99FF66"),
        "orange": OperatorColor("FFC000", "FFC000"),
        "netia": OperatorColor("69D8FF", "00FFFF"),
        "inea": OperatorColor(),
        None: OperatorColor(),
    }
)
"""Operator z ``CZYNNOŚCI`` (``_operator``; ``None``: puste) → Kolor operatora; każdy inny to ``_OTHER_OPERATOR``."""
_OTHER_OPERATOR: Final = OperatorColor("00FFFF", "00FFFF")
_FAULT: Final = OperatorColor(devices="E89CA7")
"""Kolor zamiast Koloru operatora przy usterce (``OrderKind.FAULT``)."""


class OrderKind(Enum):
    """Rodzaj Surowego zlecenia z ``URZĄDZENIA``: usterka (także hurt), instalacja hurt albo inny."""

    FAULT = "usterka"
    WHOLESALE_INSTALLATION = "instalacja hurt"
    OTHER = "inny"


_KINDS: Final[Mapping[str, OrderKind]] = MappingProxyType(
    {
        "usterka": OrderKind.FAULT,
        "usterkahurt": OrderKind.FAULT,
        "instalacjahurt": OrderKind.WHOLESALE_INSTALLATION,
    }
)
"""``URZĄDZENIA`` (``_name``) → rodzaj zlecenia; każda inna wartość to ``OrderKind.OTHER``."""


@dataclass(frozen=True)
class _EntryRule:
    """Reguła taty dla instalacji hurt operatora: jego nazwa w regule, ``URZĄDZENIA`` i dopisek w ``CZYNNOŚCI``."""

    operator: str
    devices: str
    suffix: str


_ENTRY_RULES: Final[Mapping[str, _EntryRule]] = MappingProxyType(
    {
        "netia": _EntryRule("Netia", "nokia", " - akt pętli"),
        "p4": _EntryRule("P4", "nokia", " - akt pętli"),
        "plus": _EntryRule("Plus", "nokia", " - akt pętli"),
        "vectra": _EntryRule("VECTRA", "nokia", " - akt pętli"),
        "systemia": _EntryRule("SYSTEMIA", "nokia", " - akt pętli"),
        "orange": _EntryRule("ORANGE", "gniazdo", " - akt pętli LLU"),
        "tmobile": _EntryRule("TMOBILE", "nokia getewayHomeBox", " - akt int"),
    }
)
"""Operator z ``CZYNNOŚCI`` (``_operator``) → reguła taty dla Wpisu urządzenia i czynności INTERMAX."""


@dataclass(frozen=True)
class CellFacts:
    """Komórka arkusza: wartość (``None``: pusta), krój i rozmiar czcionki oraz żółte wypełnienie."""

    value: object
    face: tuple[str | None, float | None]
    yellow: bool


@dataclass(frozen=True)
class RowFacts:
    """Wiersz arkusza: numer, komórki po kolumnie od 1 (tylko te, które są w pliku) i żółte wypełnienie stylu wiersza."""

    number: int
    cells: Mapping[int, CellFacts]
    yellow: bool

    def value(self, column: int) -> object:
        cell = self.cells.get(column)
        return None if cell is None else cell.value

    @property
    def blank(self) -> bool:
        return all(cell.value is None for cell in self.cells.values())


@dataclass(frozen=True)
class RawOrder:
    """Surowe zlecenie: wiersz arkusza, przesunięcie, data z godziną, Wykonawca, operator i rodzaj.

    ``offset``: o tyle kolumn na lewo od swoich nagłówków stoją komórki wiersza (``SHIFT`` w przesuniętym pierwszym
    wierszu bloku, inaczej 0). ``operator`` to nazwa operatora z ``CZYNNOŚCI`` taka, jak z aplikacji, bez spacji na
    brzegach (``None``: puste), a ``kind`` rodzaj zlecenia z ``URZĄDZENIA``.
    """

    row: int
    offset: int
    when: datetime
    worker: str
    operator: str | None
    kind: OrderKind


@dataclass(frozen=True)
class RawBlock:
    """Blok Surowych zleceń w kolejności z aplikacji i wiersz, pod którym staje dzień.

    ``last_ordered`` to ostatni uporządkowany wiersz, a bez niego nagłówek. ``anchor`` to żółty wiersz
    (``under_yellow``) albo ``last_ordered``. Zmieniają się tylko wiersze pod ``anchor``. ``blank_row`` to
    najwyższy pusty, nieżółty wiersz pod ``last_ordered`` (u taty przygotowana siatka), jeśli jest w pliku.
    """

    orders: tuple[RawOrder, ...]
    anchor: int
    under_yellow: bool
    last_ordered: int
    blank_row: int | None

    @property
    def day(self) -> date:
        """Dzień bloku: ``recognize`` oddaje blok tylko z jednego dnia."""

        return self.orders[0].when.date()


@dataclass(frozen=True)
class AboveOrdered:
    """Wiersz z wyglądem z aplikacji (``row``) nad uporządkowanym wierszem (``ordered_row``, najbliższym pod nim)."""

    row: int
    ordered_row: int


@dataclass(frozen=True)
class Undated:
    """Surowe zlecenie bez daty z godziną: wiersz i kolumna (od 1), w której jej szukano."""

    row: int
    column: int


@dataclass(frozen=True)
class WithoutWorker:
    """Surowe zlecenie bez Wykonawcy: wiersz i kolumna (od 1), w której go szukano."""

    row: int
    column: int


@dataclass(frozen=True)
class SeveralDays:
    """Blok Surowych zleceń z więcej niż jednego dnia: dni po kolei i wiersze bloku od ``first_row`` do ``last_row``."""

    days: tuple[date, ...]
    first_row: int
    last_row: int


Obstacle = AboveOrdered | Undated | WithoutWorker | SeveralDays
"""Przeszkoda, przez którą Surowych zleceń nie da się bezpiecznie uporządkować."""


@dataclass(frozen=True)
class IntermaxEntry:
    """Wpis urządzenia i czynności INTERMAX: operator z reguły taty, ``URZĄDZENIA`` i ``CZYNNOŚCI`` po Wpisie."""

    operator: str
    devices: str
    activities: str


@dataclass(frozen=True)
class Placement:
    """Surowe zlecenie na docelowym wierszu dnia z Kolorem operatora i Wpisem (``None``: bez Wpisu)."""

    order: RawOrder
    row: int
    color: OperatorColor
    entry: IntermaxEntry | None


@dataclass(frozen=True)
class DayPlan:
    """Uporządkowany dzień: zlecenia na docelowych wierszach, po kolei; reszta wierszy pod ``anchor`` jest pusta.

    ``view_row`` to wiersz, na którym INTERMAX otwiera się po zapisie (górny wiersz widoku i zaznaczenie).
    """

    day: date
    placements: tuple[Placement, ...]
    worker_count: int
    view_row: int


def recognize(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> RawBlock | Obstacle | None:
    """Blok Surowych zleceń z wierszy arkusza zleceń od ostatniego w górę (bez nagłówka), przeszkoda albo ``None``.

    ``None``: ani na dole arkusza, ani nad ostatnimi uporządkowanymi wierszami nie ma wierszy z wyglądem z aplikacji.
    """

    rows = iter(rows_from_bottom)
    raw, yellow, blank, ordered = _bottom(rows, columns)
    found = _pasted(raw, columns)
    orders = [order for order in found if isinstance(order, RawOrder)]
    days = sorted({order.when.date() for order in orders})
    above = None if ordered is None else _above(ordered, rows, columns, days[0] if days else None).obstacle
    if above is not None:
        return above
    if not raw:
        return None
    missing = next((order for order in found if not isinstance(order, RawOrder)), None)
    if missing is not None:
        return missing
    if len(days) > 1:
        return SeveralDays(tuple(days), raw[0].number, raw[-1].number)
    anchor = 1 if ordered is None else ordered.number
    return RawBlock(tuple(orders), yellow if yellow is not None else anchor, yellow is not None, anchor, blank)


def ordered_days(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns, since: date) -> frozenset[date]:
    """Dni uporządkowane od ``since`` z wierszy arkusza zleceń od ostatniego w górę.

    Przegląd (``_above``) zaczyna się od ostatniego uporządkowanego wiersza nad Surowymi zleceniami, tak jak nad blokiem
    w ``recognize``, i kończy go ``_EARLIER_ROWS`` kolejnych wierszy z dniem wcześniejszym niż ``since``, więc
    sięga do każdego dnia od ``since`` uporządkowanego do przodu nad wcześniejszymi dniami.
    """

    rows = iter(rows_from_bottom)
    first = _bottom(rows, columns)[3]
    if first is None:
        return frozenset()
    return frozenset(day for day in _above(first, rows, columns, since).days if day >= since)


def ordered_rows(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns, since: date) -> tuple[RowFacts, ...]:
    """Uporządkowane wiersze z dniem od ``since`` z wierszy arkusza zleceń od ostatniego w górę, od dołu.

    Ten sam przegląd co w ``ordered_days``: od ostatniego uporządkowanego wiersza nad Surowymi zleceniami w górę, do
    ``_EARLIER_ROWS`` kolejnych wierszy z dniem wcześniejszym niż ``since``. Surowych zleceń na dole przegląd nie oddaje,
    a kończy go też wiersz z wyglądem z aplikacji nad uporządkowanymi, więc uporządkowane zlecenia nad takim blokiem nie
    wchodzą, jak w Dniu uporządkowanym. Wiersz bez daty w ``DATA GODZ. POCZ.`` nie wchodzi.
    """

    rows = iter(rows_from_bottom)
    first = _bottom(rows, columns)[3]
    if first is None:
        return ()
    dated = ((row, row.value(columns.date)) for row in _above(first, rows, columns, since).rows)
    return tuple(row for row, when in dated if isinstance(when, datetime) and when.date() >= since)


def pasted(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> tuple[RawOrder | Undated | WithoutWorker, ...]:
    """Wiersze z wartościami pod ostatnim uporządkowanym wierszem jako Surowe zlecenia, w kolejności z aplikacji.

    To blok Surowych zleceń bez przeglądu nad nim, więc bez wiersza z wyglądem z aplikacji nad uporządkowanymi;
    pusta krotka, gdy na dole arkusza nic nie jest wklejone.
    """

    return tuple(_pasted(_bottom(iter(rows_from_bottom), columns)[0], columns))


def pasted_rows(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> tuple[RowFacts, ...]:
    """Wiersze z wartościami pod ostatnim uporządkowanym wierszem, od góry: wklejenie, z którego ``recognize`` i
    ``pasted`` biorą blok Surowych zleceń, bez pustych i żółtych wierszy między nimi; pusta krotka bez wklejenia."""

    return tuple(_bottom(iter(rows_from_bottom), columns)[0])


def above_paste(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> AbovePaste:
    """Ostatni uporządkowany i żółty wiersz z tego samego rozpoznania dołu arkusza co ``recognize``, same numery
    wierszy: Kopia wejścia niesie je, żeby odtworzenie Uruchomienia postawiło dzień w tych samych wierszach (#847)."""

    _, yellow, _, ordered = _bottom(iter(rows_from_bottom), columns)
    return AbovePaste(None if ordered is None else ordered.number, yellow)


def row_positions(*, first: bool, left_of_date: object, date: object, read: int = 0) -> RowPositions:
    """Jedyna reguła położenia wiersza arkusza zleceń: wiersz z siatki (``both_positions``) pamięć zna w obu położeniach,
    pierwszy wiersz bloku wklejenia (``first``) tylko przesunięty o ``SHIFT``, każdy inny tylko pod nagłówkiem.
    ``left_of_date``: wartość ``SHIFT`` kolumn na lewo od ``DATA GODZ. POCZ.``, ``date``: wartość pod nią, ``read``:
    przesunięcie, z którym proces czyta wiersz (``RowPositions.read``)."""

    if both_positions(first=first, left_of_date=left_of_date, date=date):
        known: tuple[int, ...] = (0, SHIFT)
    else:
        known = (SHIFT,) if first else (0,)
    return RowPositions(read, known, not first and shift_traced(left_of_date))


def shift_traced(left_of_date: object) -> bool:
    """Ślad przesunięcia wiersza czytanego pod nagłówkami: data z godziną ``SHIFT`` kolumn na lewo od ``DATA GODZ.
    POCZ.`` (``left_of_date``; u taty kolumna A bez nagłówka). Wiersz na miejscu jej tam nie ma, a przesunięty wiersz z
    aplikacji ma tam swoją datę."""

    return _is_date(left_of_date)


def shift_visible(left_of_date: object, date: object) -> bool:
    """Przesunięcie wiersza widać: ślad przesunięcia (``shift_traced``), a pod ``DATA GODZ. POCZ.`` (``date``) nie ma
    daty z godziną. Tak stoi u taty każdy przesunięty pierwszy wiersz z aplikacji."""

    return shift_traced(left_of_date) and not _is_date(date)


def both_positions(*, first: bool, left_of_date: object, date: object) -> bool:
    """Siatka reguły położenia (ADR 0025): czy pamięć reguły danych zna wiersz w obu położeniach, a nie w jednym.
    ``first``: wiersz jest pierwszym wierszem swojego bloku wklejenia, ``left_of_date``: wartość ``SHIFT`` kolumn na
    lewo od ``DATA GODZ. POCZ.``, ``date``: wartość pod nią.

    Pierwszy wiersz bloku pamięć zna tylko przesunięty, gdy jego przesunięcie widać (``shift_visible``). Każdy inny
    pierwszy wiersz (z datą z godziną pod ``DATA GODZ. POCZ.``, z datą tekstem, bez daty) zna w obu, bez uwagi w Logach,
    bo sam kształt treści nie mówi, gdzie wiersz stoi. Tak wygląda wiersz, który uchodzi za pierwszy, bo tata wpisał coś
    w Calibri 8 w wiersz nad nim (przegląd #984 r1 i r2); granica bloku zostaje z kroju, bo reguła wyglądu z większości
    komórek przestawia u taty granice dziesiątek bloków. Inny wiersz pamięć zna w obu, gdy ma ślad przesunięcia
    (``shift_traced``), czyli widocznie łamie fakt domeny; tylko o nim Logi mają uwagę (``RowPositions.traced``).
    """

    if first:
        return not shift_visible(left_of_date, date)
    return shift_traced(left_of_date)


def shifted_row(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> int | None:
    """Wiersz, którego komórki rozpoznanie czyta ``SHIFT`` kolumn na lewo od nagłówków (``RawOrder.offset``): pierwszy
    wiersz bloku Surowych zleceń z tego samego rozpoznania co w ``recognize`` i ``pasted``, gdy pod ``DATA GODZ. POCZ.``
    nie ma daty z godziną; ``None``: bez niego."""

    return _shifted(_bottom(iter(rows_from_bottom), columns)[0], columns)


class RowLook(Enum):
    """Wygląd wiersza arkusza zleceń, z którego ``first_in_block`` poznaje granice bloku wklejenia."""

    BLANK = "pusty"
    ORDERED = "uporządkowany"
    APP = "z aplikacji"


def look(row: RowFacts, columns: OrderColumns) -> RowLook:
    """Wygląd wiersza: pusty bez wartości, uporządkowany z choć jedną komórką z wartością w Calibri 8 w
    ``OrderColumns.look_columns`` (bez ``WYKONAWCA``), inaczej z aplikacji."""

    if row.blank:
        return RowLook.BLANK
    return RowLook.ORDERED if _is_ordered(row, columns) else RowLook.APP


def first_in_block(rows_from_bottom: Iterable[_Row], look: Callable[[_Row], RowLook]) -> Iterator[tuple[_Row, bool]]:
    """Wiersze arkusza zleceń od ostatniego w górę, każdy z tym, czy jest pierwszym wierszem swojego bloku wklejenia:
    wiersz z wyglądem z aplikacji, nad którym najbliższy wiersz z wartościami ma wygląd uporządkowany albo nie ma
    żadnego. To pierwszy wiersz bloku na dole arkusza i każdego bloku nad uporządkowanymi. Wiersz z wyglądem z aplikacji
    wychodzi dopiero po przeczytaniu najbliższego wiersza z wartościami nad nim, więc odczyt sięga o jeden taki wiersz
    dalej niż ten, kto przestaje czytać. Wiersz może być dowolnego typu, bo jego wygląd daje ``look``."""

    waiting: list[_Row] = []  # wiersz z wyglądem z aplikacji i puste wiersze nad nim
    for row in rows_from_bottom:
        found = look(row)
        if found is RowLook.BLANK:
            if waiting:
                waiting.append(row)
            else:
                yield row, False
            continue
        ordered = found is RowLook.ORDERED
        if waiting:
            yield waiting[0], ordered
            yield from ((blank, False) for blank in waiting[1:])
            waiting = []
        if ordered:
            yield row, False
        else:
            waiting = [row]
    if waiting:
        yield waiting[0], True
        yield from ((blank, False) for blank in waiting[1:])


def _bottom(rows: Iterator[RowFacts], columns: OrderColumns) -> tuple[list[RowFacts], int | None, int | None, RowFacts | None]:
    """Dół arkusza do ostatniego uporządkowanego wiersza: wiersze z wartościami pod nim (od góry), żółty i pusty wiersz, on sam."""

    raw: list[RowFacts] = []
    yellow: int | None = None
    blank: int | None = None
    ordered: RowFacts | None = None
    for row in rows:
        if row.blank:
            if not _is_yellow(row, columns):
                blank = row.number
            elif yellow is None:
                yellow = row.number
            continue
        if _is_ordered(row, columns):
            ordered = row
            break
        yellow = None
        raw.append(row)
    raw.reverse()
    return raw, yellow, blank, ordered


def _pasted(raw: list[RowFacts], columns: OrderColumns) -> list[RawOrder | Undated | WithoutWorker]:
    shifted = _shifted(raw, columns)
    return [_order(row, columns, SHIFT if row.number == shifted else 0) for row in raw]


def _shifted(raw: list[RowFacts], columns: OrderColumns) -> int | None:
    """Pierwszy wiersz bloku bez daty w ``DATA GODZ. POCZ.`` jest przesunięty; z datą na miejscu ktoś go już przesunął."""

    return raw[0].number if raw and not _is_date(raw[0].value(columns.date)) else None


def plan_day(block: RawBlock, rows_from_bottom: Iterable[RowFacts], columns: OrderColumns, today: date) -> DayPlan:
    """Docelowe wiersze dnia: segmenty Wykonawców alfabetycznie, w segmencie po godzinie, z jednym pustym między nimi.

    ``rows_from_bottom`` to wiersze arkusza od ostatniego w górę, jak dla ``recognize``: z wierszy nad ``anchor`` i
    z nowego dnia plan wyznacza wiersz widoku na dzień ``today`` (``_view_row``).
    """

    def worker_key(order: RawOrder) -> str:
        return segment_key(order.worker)

    ordered = sorted(block.orders, key=lambda order: (worker_key(order), order.when))
    row = block.anchor + (2 if block.under_yellow else _BLANK_ROWS_WITHOUT_YELLOW + 1)
    placements: list[Placement] = []
    segments = 0
    for _, segment in groupby(ordered, key=worker_key):
        if segments:
            row += 1
        segments += 1
        for order in segment:
            placements.append(Placement(order, row, _operator_color(order), _entry(order)))
            row += 1
    view_row = _view_row(placements, rows_from_bottom, columns, block.anchor, today)
    return DayPlan(block.day, tuple(placements), segments, view_row)


def segment_key(worker: object) -> str:
    """Klucz segmentu Wykonawcy w uporządkowanym dniu: ``WYKONAWCA`` po ``normalize_text``; segmenty stoją w jego
    kolejności alfabetycznej."""

    return normalize_text(worker)


@dataclass(frozen=True)
class NewSeparator:
    """Nowy pusty wiersz między segmentami z wyglądem ``<row>`` wiersza ``model`` (przeniesionego zlecenia albo wiersza
    dnia, do którego idzie dopisane zlecenie)."""

    model: int


@dataclass(frozen=True)
class AddedRow:
    """Zlecenie dopisane do dnia ``day`` Wykonawcy ``worker`` (tekst ``WYKONAWCA``) z wartościami ``cells`` (kolumna od
    1 → tekst albo liczba) poza ``DATA GODZ. POCZ.``, którą daje plan (``NewOrder``)."""

    worker: str
    day: date
    cells: Mapping[int, str | int]


@dataclass(frozen=True)
class NewOrder:
    """Nowy wiersz zlecenia dopisanego (``added``: jego miejsce na liście dopisań planu) z wyglądem ``<row>`` i stylem
    ``DATA GODZ. POCZ.`` wiersza ``model`` sprzed zapisu (uporządkowanego zlecenia, które było albo jest w dniu
    dopisania), a jako datą częścią dnia liczby daty ``model`` większą o ``days`` dni (bez godziny)."""

    added: int
    model: int
    days: int


@dataclass(frozen=True)
class MovePlan:
    """Przeniesienia i dopisania zleceń w arkuszu zleceń: wiersze od ``first`` do końca arkusza po zapisie, po kolei.

    Każdy wiersz to numer wiersza sprzed zapisu (także wiersz, którego nie ma w pliku, jest pusty), nowy pusty wiersz
    między segmentami (``NewSeparator``) albo nowy wiersz dopisanego zlecenia (``NewOrder``, z ``added``). ``workers``:
    wiersz przeniesionego zlecenia sprzed zapisu → tekst ``WYKONAWCA`` po zapisie, ``shifts``: wiersz zlecenia
    przeniesionego na inny dzień → o ile dni zmienia się jego ``DATA GODZ. POCZ.`` (godzina zostaje). Wiersz, którego
    nie ma w ``rows``, był pustym wierszem obok segmentu, który zniknął.
    """

    first: int
    rows: tuple[int | NewSeparator | NewOrder, ...]
    workers: Mapping[int, str]
    shifts: Mapping[int, int] = field(default_factory=lambda: MappingProxyType({}))
    added: tuple[AddedRow, ...] = ()


@dataclass(frozen=True)
class _Vacated:
    """Miejsce bloku dnia ``day``, z którego w planie odeszło ostatnie zlecenie (wiersz ``model`` sprzed zapisu):
    pierwsze zlecenie przeniesione albo dopisane na ten dzień staje tutaj. Plan go nie oddaje."""

    day: date
    model: int


_Slot = int | NewSeparator | NewOrder | _Vacated
"""Miejsce wiersza w planie Przeniesień w trakcie planowania."""


@dataclass(frozen=True)
class MissingDays:
    """Dni, na które Przeniesienia idą, a arkusz nie ma w nich uporządkowanego zlecenia, pod które wiersz mógłby stanąć."""

    days: frozenset[date]


def plan_moves(
    rows_from_bottom: Iterable[RowFacts],
    columns: OrderColumns,
    moves: Mapping[int, tuple[str, date]],
    added: Sequence[AddedRow] = (),
) -> MovePlan | MissingDays:
    """Plan Przeniesień ``moves`` (wiersz uporządkowanego zlecenia → ``WYKONAWCA`` i dzień po zapisie) i dopisań
    ``added``.

    Dzień docelowy musi mieć uporządkowany wiersz w arkuszu przed zapisem (``MissingDays``, gdy go nie ma), także
    wiersz, który w tym samym planie odchodzi, bo rdzeń liczy Dni uporządkowane z INTERMAX przed kliknięciem.

    Blok dnia to uporządkowane wiersze z jego datą wokół wiersza, z pojedynczymi pustymi wierszami (nie żółtymi) między
    nimi; segment to ciąg wierszy bloku z wartościami bez pustego wiersza. Przeniesienia idą po wierszach od góry, a
    klucz segmentu daje ``WYKONAWCA`` jego pierwszego wiersza w tej chwili planu: wiersz już przeniesiony ma nowego
    Wykonawcę, a wiersz, którego Przeniesienie przyjdzie później, dalej tego z pliku. Wiersz odchodzi ze swojego miejsca, a segment, który zostaje bez wierszy, traci pusty wiersz pod sobą (nad sobą,
    gdy był ostatni w bloku). W tym samym dniu wiersz staje w bloku, z którego wyszedł, a na inny dzień w bloku dnia
    docelowego wokół jego najniższego wiersza w tej chwili planu (także wiersza, którego Przeniesienie przyjdzie
    później): pod ostatnim wierszem ostatniego segmentu z kluczem ``segment_key`` nowego Wykonawcy, a bez takiego
    segmentu w nowym segmencie, z pustym wierszem pod sobą przed pierwszym segmentem z kluczem większym albo z pustym
    wierszem nad sobą za ostatnim segmentem; w bloku bez innych wierszy staje na swoim miejscu. Blok, z którego na inny
    dzień odszedł ostatni wiersz, zostawia swoje miejsce (``_Vacated``), a pierwszy wiersz przeniesiony na jego dzień
    staje tam, więc dzień, którego wszystkie zlecenia odchodzą, a inne przychodzą, zostaje na swoim miejscu w arkuszu.
    Dopisania idą po Przeniesieniach, po kolei, tą samą regułą co Przeniesienie na inny dzień: w bloku dnia wokół jego
    najniższego wiersza w tej chwili planu (także wiersza przeniesionego albo dopisanego wcześniej w tym planie), pod
    ostatnim wierszem segmentu Wykonawcy albo w nowym segmencie, a na miejscu opuszczonego bloku (``_Vacated``), gdy z
    dnia odeszły wszystkie wiersze. Wiersz dopisanego zlecenia (``NewOrder``) bierze wygląd i datę z tego najniższego
    wiersza dnia (``model``).
    Wiersze od pierwszego bloku do końca arkusza dostają kolejne numery, więc wiersze pod blokami przesuwają się o tyle,
    o ile urósł albo zmalał blok. Odczyt od dołu kończy pierwszy wiersz z wartościami nad najwyższym przenoszonym
    wierszem (bez Przeniesień: nad dołem arkusza), który nie jest z dnia żadnego z nich ani z dnia docelowego, gdy
    arkusz ma już uporządkowany wiersz każdego dnia docelowego.
    """

    lowest = min(moves, default=None)
    facts: dict[int, RowFacts] = {}
    days: set[date | None] = set()
    targets = {day for _, day in moves.values()} | {row.day for row in added}
    missing = set(targets)
    for row in rows_from_bottom:
        facts[row.number] = row
        day = _day_of(row, columns)
        if row.number in moves:
            days.add(day)
        if day in missing and not row.blank and look(row, columns) is RowLook.ORDERED:
            missing.discard(day)
        below = lowest is None or row.number < lowest
        if below and not row.blank and day not in days and day not in targets and not missing:
            break
    if missing:
        return MissingDays(frozenset(day for day in missing if day is not None))
    base, last = min(facts), max(facts)
    placed: dict[int, date] = {}

    def blank(slot: _Slot) -> bool:
        if isinstance(slot, (_Vacated, NewOrder)):
            return False
        if isinstance(slot, NewSeparator):
            return True
        found = facts.get(slot)
        return found is None or (found.blank and not _is_yellow(found, columns))

    def of_day(slot: _Slot, day: date | None) -> bool:
        if isinstance(slot, _Vacated):
            return slot.day == day
        if isinstance(slot, NewOrder):
            return added[slot.added].day == day
        if isinstance(slot, NewSeparator) or (found := facts.get(slot)) is None or found.blank:
            return False
        return look(found, columns) is RowLook.ORDERED and placed.get(slot, _day_of(found, columns)) == day

    def block(slots: Sequence[_Slot], at: int, day: date | None) -> tuple[int, int]:
        """Pierwszy i ostatni wiersz bloku dnia ``day`` wokół miejsca ``at`` w ``slots``."""

        def step(at: int, direction: int) -> int:
            """O ile blok rośnie od ``at`` w stronę ``direction``: wiersz dnia (1), pusty i wiersz dnia (2), koniec (0)."""

            near, far = at + direction, at + 2 * direction
            if 0 <= near < len(slots) and of_day(slots[near], day):
                return 1
            if 0 <= far < len(slots) and blank(slots[near]) and of_day(slots[far], day):
                return 2
            return 0

        top = bottom = at
        while grow := step(top, -1):
            top -= grow
        while grow := step(bottom, 1):
            bottom += grow
        return top, bottom

    def anchor(slots: Sequence[_Slot], day: date) -> int | None:
        """Najniższy uporządkowany wiersz dnia ``day`` w ``slots`` w tej chwili planu albo miejsce opuszczonego bloku."""

        found = [index for index, slot in enumerate(slots) if of_day(slot, day)]
        return max(found) if found else None

    read: list[_Slot] = list(range(base, last + 1))
    tops = [block(read, source - base, _day_of(facts[source], columns))[0] for source in moves]
    for day in targets:
        at = anchor(read, day)
        if at is not None:
            tops.append(block(read, at, day)[0])
    first = base + min(tops)
    slots: list[_Slot] = list(range(first, last + 1))
    shifts: dict[int, int] = {}
    done: set[int] = set()

    def worker_now(slot: int | NewOrder) -> object:
        """``WYKONAWCA`` wiersza w tej chwili planu: dopisanego zlecenia jego, po zaplanowanym Przeniesieniu nowy, przed
        nim ten z pliku."""

        if isinstance(slot, NewOrder):
            return added[slot.added].worker
        return moves[slot][0] if slot in done else facts[slot].value(columns.worker)

    def insert(slots: list[_Slot], top: int, bottom: int, target: date, worker: str, slot: int | NewOrder, model: int) -> None:
        """Wiersz ``slot`` Wykonawcy ``worker`` w bloku dnia ``target`` od ``top`` do ``bottom``: pod ostatnim wierszem
        ostatniego segmentu z jego kluczem, a bez takiego segmentu w nowym segmencie przed pierwszym segmentem z kluczem
        większym albo za ostatnim, z nowym pustym wierszem z wyglądem wiersza ``model``."""

        segments: list[tuple[str, int, int]] = []
        for index in range(top, bottom + 1):
            found = slots[index]
            if isinstance(found, (NewSeparator, _Vacated)) or not of_day(found, target):
                continue
            if segments and segments[-1][2] == index - 1:
                segments[-1] = (segments[-1][0], segments[-1][1], index)
            else:
                segments.append((segment_key(worker_now(found)), index, index))
        wanted = segment_key(worker)
        same = [end for key, _, end in segments if key == wanted]
        later = [start for key, start, _ in segments if key > wanted]
        if same:
            slots.insert(same[-1] + 1, slot)
        elif later:
            slots[later[0] : later[0]] = [slot, NewSeparator(model)]
        else:
            end = segments[-1][2]
            slots[end + 1 : end + 1] = [NewSeparator(model), slot]

    for source in sorted(moves):
        worker, target = moves[source]
        day = _day_of(facts[source], columns)
        at = slots.index(source)
        top, bottom = block(slots, at, day)
        alone = not (at > top and of_day(slots[at - 1], day)) and not (at < bottom and of_day(slots[at + 1], day))
        del slots[at]
        bottom -= 1
        if alone and at <= bottom and blank(slots[at]):
            del slots[at]
            bottom -= 1
        elif alone and at - 1 >= top and blank(slots[at - 1]):
            del slots[at - 1]
            at, bottom = at - 1, bottom - 1
        left = [index for index in range(top, bottom + 1) if of_day(slots[index], day)]
        if target == day:
            if not left:
                slots.insert(at, source)
                done.add(source)
                continue
            top, bottom = block(slots, left[0], day)
        else:
            if not left and day is not None:
                slots.insert(at, _Vacated(day, source))
            found = anchor(slots, target)
            if found is None:
                return MissingDays(frozenset({target}))
            top, bottom = block(slots, found, target)
            shifts[source] = (target - day).days if day is not None else 0
            placed[source] = target
            if isinstance(slots[found], _Vacated):
                slots[found] = source
                done.add(source)
                continue
        insert(slots, top, bottom, target, worker, source, source)
        done.add(source)
    for index, order in enumerate(added):
        spot = anchor(slots, order.day)
        if spot is None:
            return MissingDays(frozenset({order.day}))
        lowest_slot = slots[spot]
        model = lowest_slot.model if isinstance(lowest_slot, (_Vacated, NewOrder)) else lowest_slot
        assert isinstance(model, int), "anchor daje tylko wiersz dnia, miejsce opuszczonego bloku albo dopisanie"
        model_day = _day_of(facts[model], columns)
        new = NewOrder(index, model, 0 if model_day is None else (order.day - model_day).days)
        if isinstance(lowest_slot, _Vacated):
            slots[spot] = new
            continue
        top, bottom = block(slots, spot, order.day)
        insert(slots, top, bottom, order.day, order.worker, new, model)
    workers = {source: worker for source, (worker, _) in moves.items()}
    kept = tuple(slot for slot in slots if not isinstance(slot, _Vacated))
    return MovePlan(first, kept, MappingProxyType(workers), MappingProxyType(shifts), tuple(added))


def _day_of(row: RowFacts, columns: OrderColumns) -> date | None:
    when = row.value(columns.date)
    return when.date() if isinstance(when, datetime) else None


def _operator_color(order: RawOrder) -> OperatorColor:
    if order.kind is OrderKind.FAULT:
        return _FAULT
    return _OPERATOR_COLORS.get(None if order.operator is None else _operator(order.operator), _OTHER_OPERATOR)


def _entry(order: RawOrder) -> IntermaxEntry | None:
    if order.kind is not OrderKind.WHOLESALE_INSTALLATION or order.operator is None:
        return None
    rule = _ENTRY_RULES.get(_operator(order.operator))
    return None if rule is None else IntermaxEntry(rule.operator, rule.devices, order.operator + rule.suffix)


def _view_row(
    placements: list[Placement], rows_from_bottom: Iterable[RowFacts], columns: OrderColumns, anchor: int, today: date
) -> int:
    """Pierwsze zlecenie dnia ``today``, a bez niego ostatniego wcześniejszego dnia ze zleceniami.

    Od dołu nowego dnia w górę: dzień widoku to najpóźniejszy dzień nie późniejszy niż ``today``, a jego pierwsze
    zlecenie to najwyższy wiersz z jego datą, zanim ``_EARLIER_ROWS`` kolejnych wierszy ma dzień wcześniejszy.
    Zlecenia na późniejsze dni (nowy dzień na jutro) pomija. Bez żadnego dnia do ``today`` to pierwsze zlecenie
    nowego dnia.
    """

    dated = chain(((placement.row, placement.order.when) for placement in reversed(placements)), _dated(rows_from_bottom, columns, anchor))
    day: date | None = None
    first = placements[0].row
    earlier = 0
    for number, when in dated:
        if when.date() > today:
            continue
        if day is None or when.date() >= day:
            day, first, earlier = when.date(), number, 0
        else:
            earlier += 1
            if earlier == _EARLIER_ROWS:
                break
    return first


def _dated(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns, anchor: int) -> Iterator[tuple[int, datetime]]:
    for row in rows_from_bottom:
        when = row.value(columns.date)
        if row.number <= anchor and isinstance(when, datetime):
            yield row.number, when


def _order(row: RowFacts, columns: OrderColumns, offset: int) -> RawOrder | Undated | WithoutWorker:
    when = row.value(columns.date - offset)
    if not isinstance(when, datetime):
        return Undated(row.number, columns.date - offset)
    worker = row.value(columns.worker - offset)
    if worker is None:
        return WithoutWorker(row.number, columns.worker - offset)
    operator = row.value(columns.activities - offset)
    kind = _KINDS.get(_name(row.value(columns.devices - offset)), OrderKind.OTHER)
    return RawOrder(row.number, offset, when, str(worker), None if operator is None else str(operator).strip(), kind)


def _name(value: object) -> str:
    """Nazwa bez wielkości liter, spacji i myślników: ``T-Mobile`` i ``TMOBILE`` to ``tmobile``."""

    return re.sub(r"[\W_]+", "", str(value).casefold())


def _operator(text: str) -> str:
    """Nazwa operatora z ``CZYNNOŚCI`` jak ``_name``, a do tego bez dopisku ``S.A.``: ``Netia S.A.`` i ``NetiaSA`` to ``netia``."""

    return _name(_COMPANY_SUFFIX.sub("", text))


@dataclass(frozen=True)
class _Above:
    """Wynik przeglądu nad blokiem: wiersz z wyglądem z aplikacji nad uporządkowanymi (``obstacle``), uporządkowane dni
    i uporządkowane wiersze z wartościami, które przegląd przeszedł, od dołu."""

    obstacle: AboveOrdered | None
    days: set[date]
    rows: tuple[RowFacts, ...]


def _above(first: RowFacts, rows: Iterator[RowFacts], columns: OrderColumns, day: date | None) -> _Above:
    """Przegląd od ostatniego uporządkowanego wiersza ``first`` w górę: wiersz z wyglądem z aplikacji nad nim, dni i
    przejrzane uporządkowane wiersze.

    Dni to uporządkowane dni przeglądu: dzień dwóch kolejnych wierszy z datą albo wiersza, pod którym nie ma
    wcześniejszego dnia. Przegląd kończy ``_EARLIER_ROWS`` kolejnych wierszy z dniem wcześniejszym niż ``day`` (bez
    niego: dzień pierwszego wiersza z datą).
    """

    below = first.number
    days: set[date] = set()
    seen: list[RowFacts] = []
    earlier = 0
    previous: date | None = None
    lowest: date | None = None
    for row in chain([first], rows):
        if row.blank:
            continue
        if not _is_ordered(row, columns):
            return _Above(AboveOrdered(row.number, below), days, tuple(seen))
        below = row.number
        seen.append(row)
        when = row.value(columns.date)
        if not isinstance(when, datetime):
            continue
        if day is None:
            day = when.date()
        lowest = when.date() if lowest is None else min(lowest, when.date())
        if when.date() in (previous, lowest):
            days.add(when.date())
        previous = when.date()
        if when.date() < day:
            earlier += 1
            if earlier == _EARLIER_ROWS:
                break
        else:
            earlier = 0
    return _Above(None, days, tuple(seen))


def _is_date(value: object) -> bool:
    return isinstance(value, datetime)


def _order_cells(row: RowFacts, columns: OrderColumns) -> list[CellFacts]:
    span = columns.look_columns
    return [cell for column, cell in row.cells.items() if column in span and cell.value is not None]


def ordered_look(faces: Iterable[tuple[str | None, float | None]]) -> bool:
    """Wygląd wiersza uporządkowanego z kroju i rozmiaru czcionki (``faces``) jego komórek z wartością w kolumnach
    wyglądu (``OrderColumns.look_columns``): choć jedna jest w Calibri 8."""

    return (ORDERED_FONT, ORDERED_SIZE) in faces


def _is_ordered(row: RowFacts, columns: OrderColumns) -> bool:
    return ordered_look(cell.face for cell in _order_cells(row, columns))


def _is_yellow(row: RowFacts, columns: OrderColumns) -> bool:
    span = range(columns.first, columns.last + 1)
    yellow = sum(1 for column in span if (cell.yellow if (cell := row.cells.get(column)) is not None else row.yellow))
    return 2 * yellow >= len(span)
