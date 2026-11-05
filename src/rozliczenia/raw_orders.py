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
Uporządkowania niesie, a ``shifts`` przesunięcia wierszy: wiersz, którego komórki rozpoznanie czyta dwie kolumny na
lewo od swojego nagłówka, i wiersze z dwoma położeniami, w których komórki mogą stać przesunięte albo nie.

Przesunięty przychodzi tylko pierwszy wklejony wiersz (fakt domeny od Maksa, 5.11.2026; kopia INTERMAX taty: 1 z 84
wklejonych wierszy). Prywatność na nim nie stoi: dwa położenia ma każdy wiersz z wyglądem z aplikacji i każdy wiersz
uporządkowany ze śladem przesunięcia (``shift_traces``). Fakt domeny daje tylko sygnał: wiersz ze śladem poza
pierwszym wierszem bloku łamie go (``Shifts.traced``).

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
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from itertools import chain, groupby
from types import MappingProxyType
from typing import Final

from .worker_config import normalize_text

SHIFT: Final = 2
"""O tyle kolumn w lewo przychodzi pierwszy wiersz wklejenia."""
_ORDERED_FACE: Final = ("Calibri", 8.0)
_BLANK_ROWS_WITHOUT_YELLOW: Final = 10
_EARLIER_ROWS: Final = 10
"""Tyle kolejnych uporządkowanych wierszy z wcześniejszym dniem kończy przegląd nad blokiem."""
_COMPANY_SUFFIX: Final = re.compile(r"[\s-]+S\.?\s*A\.?\s*$", re.IGNORECASE)
"""Dopisek ``S.A.`` za nazwą operatora (także ``SA``, ``S.A``), oddzielony spacją albo myślnikiem."""


@dataclass(frozen=True)
class OrderColumns:
    """Kolumny arkusza zleceń (od 1) po nagłówkach z wiersza 1: kolumny zlecenia od ``first`` do ``last`` (UWAGI).

    ``devices``, ``activities`` i ``contract_number`` to ``URZĄDZENIA``, ``CZYNNOŚCI`` i ``NUMER UMOWY``, w których
    staje Kolor operatora, a ``number`` to ``NUMER ZL.``, w którym stoi Hiperłącze wiersza z aplikacji.
    """

    first: int
    date: int
    worker: int
    last: int
    devices: int
    activities: int
    contract_number: int
    number: int


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


def order_kind(devices: object) -> OrderKind:
    """Rodzaj Surowego zlecenia z wartości ``URZĄDZENIA`` (``_KINDS``); tekst ``OrderKind.value`` daje ten sam rodzaj."""

    return _KINDS.get(_name(devices), OrderKind.OTHER)


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
    """Wiersz arkusza: numer, komórki po kolumnie od 1 (tylko te, które są w pliku), żółte wypełnienie stylu wiersza i
    kolumny komórek z wartością i Hiperłączem (``None``: Hiperłączy arkusza nie dało się przeczytać)."""

    number: int
    cells: Mapping[int, CellFacts]
    yellow: bool
    links: frozenset[int] | None = frozenset()

    def value(self, column: int) -> object:
        cell = self.cells.get(column)
        return None if cell is None else cell.value

    @property
    def blank(self) -> bool:
        return all(cell.value is None for cell in self.cells.values())


@dataclass(frozen=True)
class RawOrder:
    """Surowe zlecenie: wiersz arkusza, przesunięcie pierwszego wiersza, data z godziną, Wykonawca, operator i rodzaj.

    ``operator`` to nazwa operatora z ``CZYNNOŚCI`` taka, jak z aplikacji, bez spacji na brzegach (``None``: puste),
    a ``kind`` rodzaj zlecenia z ``URZĄDZENIA``.
    """

    row: int
    shifted: bool
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
    above = None if ordered is None else _above(ordered, rows, columns, days[0] if days else None)[0]
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
    return frozenset(day for day in _above(first, rows, columns, since)[1] if day >= since)


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


@dataclass(frozen=True)
class AbovePaste:
    """Wiersze nad wklejeniem, od których ``recognize`` liczy wiersz dnia (``RawBlock.anchor``): ostatni uporządkowany
    wiersz (``None``: bez niego dzień staje pod nagłówkiem) i żółty wiersz między nim a wklejeniem (``None``: bez
    żółtego wiersza)."""

    last_ordered: int | None
    yellow: int | None


def above_paste(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> AbovePaste:
    """Ostatni uporządkowany i żółty wiersz z tego samego rozpoznania dołu arkusza co ``recognize``, same numery
    wierszy: Kopia wejścia niesie je, żeby odtworzenie Uruchomienia postawiło dzień w tych samych wierszach (#847)."""

    _, yellow, _, ordered = _bottom(iter(rows_from_bottom), columns)
    return AbovePaste(None if ordered is None else ordered.number, yellow)


class ShiftTrace(Enum):
    """Silny ślad przesunięcia wiersza czytanego pod nagłówkami: rzecz, której wiersz na miejscu nie ma, a wiersz
    przesunięty o ``SHIFT`` kolumn w lewo (w całości albo w części) z aplikacji firmowej ma; ``value`` to opis w uwadze
    Logów. Brak daty pod ``DATA GODZ. POCZ.`` i mieszany krój śladem nie są: u taty ma je 740 wierszy na miejscu (#966)."""

    LEFT_OF_DATE = "data z godziną dwie kolumny na lewo od DATA GODZ. POCZ."
    LINK = "Hiperłącze poza NUMER ZL."
    LINKS_UNREADABLE = "Hiperłącza arkusza nieczytelne"


def shift_traces(*, left_of_date: object, links: Collection[int] | None, number: int) -> tuple[ShiftTrace, ...]:
    """Silne ślady przesunięcia wiersza czytanego pod nagłówkami, po kolei jak w ``ShiftTrace``.

    ``left_of_date``: wartość ``SHIFT`` kolumn na lewo od ``DATA GODZ. POCZ.`` (u taty kolumna A bez nagłówka; ``None``:
    pusta albo poza arkuszem), ``links``: kolumny (od 1) z Hiperłączem (``None``: nieczytelne), ``number``: kolumna
    ``NUMER ZL.``.
    """

    found: list[ShiftTrace] = []
    if _is_date(left_of_date):
        found.append(ShiftTrace.LEFT_OF_DATE)
    if links is None:
        found.append(ShiftTrace.LINKS_UNREADABLE)
    elif any(column != number for column in links):
        found.append(ShiftTrace.LINK)
    return tuple(found)


def primary_offset(*, left_of_date: object, links: Collection[int] | None, number: int) -> int:
    """Położenie podstawowe wiersza z dwoma położeniami, którego wartości pamięć reguły danych maskuje wszędzie:
    ``SHIFT``, gdy wiersz ma podpis przesunięcia w lewo (data z godziną dwie kolumny na lewo od ``DATA GODZ. POCZ.``
    albo Hiperłącze dwie kolumny na lewo od ``NUMER ZL.``), a inaczej 0 (na miejscu). Pamięć zna wartości obu położeń,
    ale wartość z drugiego ma wąski zakres opcji 3 (ADR 0025), poza pierwszym wierszem bloku bez przesunięcia
    potwierdzonego trzema faktami (``Shifts.everywhere``). Gdy w innym wierszu podpis nie mówi prawdy o zakazanej
    kolumnie (data w A albo Hiperłącze pod ``URZĄDZENIA`` na wierszu na miejscu, częściowe przesunięcie, brak podpisu w
    wierszu przesuniętym), prawdziwy adres albo numer Orange wychodzi tam, gdzie ta sama wartość stoi w zwykłej kolumnie
    innego wiersza; w pierwszym wierszu tylko wtedy, gdy kłamią naraz wszystkie trzy fakty ``confirmed_shift``. Wybór
    zmienia więc wyciek w tej granicy, a nie tylko koszt maski."""

    if _is_date(left_of_date) or (links is not None and number - SHIFT in links):
        return SHIFT
    return 0


def in_place_from(*, left_of_date: object, date: object, links: Collection[int] | None, number: int) -> int | None:
    """Kolumna, od której wiersz z dwoma położeniami na pewno stoi na miejscu: ``NUMER ZL.``, gdy jedyne Hiperłącze
    wiersza stoi pod nim, pod ``DATA GODZ. POCZ.`` jest data z godziną, a dwie kolumny na lewo od niej nic; ``None``:
    któregoś z tych trzech faktów brak.

    Hiperłącze z aplikacji firmowej idzie z komórką ``NUMER ZL.``, a przesunięcie w lewo, w całości albo w części,
    przesuwa wiersz od lewej: ``NUMER ZL.`` na miejscu znaczy, że wszystko od niego w prawo też. Samo Hiperłącze może
    stać w złym miejscu (sondy #917 r3: przesunięty wiersz z Hiperłączem pod ``NUMER ZL.``), więc potwierdzają je data
    na miejscu i pusta kolumna, w której przesunięty wiersz ma datę. U taty tak wygląda 83 z 83 wklejonych wierszy na
    miejscu. Granice: przesunięcie w prawo, wpis taty w komórkę z Hiperłączem i przesunięty wiersz z pustą datą z
    aplikacji, ``ADRES`` jako datą z godziną i Hiperłączem przeniesionym pod ``NUMER ZL.``.
    """

    if links is None or set(links) != {number} or not _is_date(date) or not _blank(left_of_date):
        return None
    return number


def confirmed_shift(*, left_of_date: object, date: object, links: Collection[int] | None, number: int) -> bool:
    """Przesunięcie wiersza w lewo potwierdzone trzema faktami naraz: data z godziną ``SHIFT`` kolumn na lewo od
    ``DATA GODZ. POCZ.``, pod nią brak daty z godziną i jedyne Hiperłącze wiersza ``SHIFT`` kolumn na lewo od ``NUMER
    ZL.``. Tak wygląda przesunięty pierwszy wklejony wiersz z aplikacji u taty, a wiersz na miejscu musiałby skłamać we
    wszystkich trzech naraz (wariant B, ADR 0025)."""

    return _is_date(left_of_date) and not _is_date(date) and links is not None and set(links) == {number - SHIFT}


@dataclass(frozen=True)
class Shifts:
    """O ile kolumn na lewo od swojego nagłówka stoją w pliku komórki wierszy arkusza zleceń (``shifts``).

    ``shifted_row``: pierwszy wiersz bloku Surowych zleceń, który rozpoznanie czyta przesunięty o ``SHIFT`` kolumn w
    lewo; ``None``: bez niego. Dwa położenia (``possible``) ma każdy wiersz z wyglądem z aplikacji (każdy wiersz bloku i
    wiersz nad uporządkowanymi), bo przesunięty może być każdy, i wiersz uporządkowany ze śladem przesunięcia
    (``shift_traces``). Wiersz uporządkowany bez śladu ma jedno położenie: pod nagłówkiem.
    """

    shifted_row: int | None
    columns: OrderColumns
    first_row: int | None
    """Pierwszy wiersz bloku Surowych zleceń; ``None``: bez bloku."""

    def read(self, row: int) -> int:
        """Przesunięcie, z którym rozpoznanie czyta wiersz ``row``: ``SHIFT`` w ``shifted_row``, inaczej 0."""

        return SHIFT if row == self.shifted_row else 0

    def possible(self, row: RowFacts) -> tuple[int, ...]:
        """Przesunięcia, przy których komórki wiersza mogą stać w pliku: przy jednym położeniu ``read``, a przy dwóch
        najpierw położenie podstawowe (``primary_offset``), potem drugie."""

        if _is_ordered(row, self.columns) and not self._traces(row):
            return (self.read(row.number),)
        columns = self.columns
        primary = primary_offset(left_of_date=row.value(columns.date - SHIFT), links=row.links, number=columns.number)
        return (primary, SHIFT - primary)

    def in_place_from(self, row: RowFacts) -> int | None:
        """Kolumna, od której wiersz na pewno stoi na miejscu (``in_place_from``)."""

        columns = self.columns
        return in_place_from(
            left_of_date=row.value(columns.date - SHIFT),
            date=row.value(columns.date),
            links=row.links,
            number=columns.number,
        )

    def everywhere(self, row: RowFacts) -> bool:
        """Czy pamięć reguły danych zna wartości obu położeń wiersza wszędzie, a nie wartość z drugiego wąsko: tak dla
        pierwszego wiersza bloku bez przesunięcia potwierdzonego trzema faktami (``confirmed_shift``), bo przy nim
        podpis przesunięcia może kłamać (przegląd #966 r2, decyzja Maksa 5.11.2026)."""

        if row.number != self.first_row:
            return False
        columns = self.columns
        return not confirmed_shift(
            left_of_date=row.value(columns.date - SHIFT),
            date=row.value(columns.date),
            links=row.links,
            number=columns.number,
        )

    def traced(self, row: RowFacts) -> tuple[ShiftTrace, ...]:
        """Ślady przesunięcia wiersza poza pierwszym wierszem bloku: każdy łamie fakt domeny, bo przesunięty przychodzi
        tylko pierwszy wklejony wiersz."""

        return () if row.number == self.first_row else self._traces(row)

    def _traces(self, row: RowFacts) -> tuple[ShiftTrace, ...]:
        columns = self.columns
        return shift_traces(left_of_date=row.value(columns.date - SHIFT), links=row.links, number=columns.number)


def shifts(rows_from_bottom: Iterable[RowFacts], columns: OrderColumns) -> Shifts:
    """Przesunięcia wierszy arkusza zleceń z tego samego rozpoznania bloku co w ``recognize`` i ``pasted``."""

    raw = _bottom(iter(rows_from_bottom), columns)[0]
    return Shifts(_shifted(raw, columns), columns, raw[0].number if raw else None)


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
    return [_order(row, columns, row.number == shifted) for row in raw]


def _shifted(raw: list[RowFacts], columns: OrderColumns) -> int | None:
    """Pierwszy wiersz bloku bez daty w ``DATA GODZ. POCZ.`` jest przesunięty; z datą na miejscu ktoś go już przesunął."""

    return raw[0].number if raw and not _is_date(raw[0].value(columns.date)) else None


def plan_day(block: RawBlock, rows_from_bottom: Iterable[RowFacts], columns: OrderColumns, today: date) -> DayPlan:
    """Docelowe wiersze dnia: segmenty Wykonawców alfabetycznie, w segmencie po godzinie, z jednym pustym między nimi.

    ``rows_from_bottom`` to wiersze arkusza od ostatniego w górę, jak dla ``recognize``: z wierszy nad ``anchor`` i
    z nowego dnia plan wyznacza wiersz widoku na dzień ``today`` (``_view_row``).
    """

    def worker_key(order: RawOrder) -> str:
        return normalize_text(order.worker)

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
    """Wiersze nad ``anchor`` z datą z godziną, od dołu: numer i data."""

    for row in rows_from_bottom:
        when = row.value(columns.date)
        if row.number <= anchor and isinstance(when, datetime):
            yield row.number, when


def _order(row: RowFacts, columns: OrderColumns, shifted: bool) -> RawOrder | Undated | WithoutWorker:
    offset = SHIFT if shifted else 0
    when = row.value(columns.date - offset)
    if not isinstance(when, datetime):
        return Undated(row.number, columns.date - offset)
    worker = row.value(columns.worker - offset)
    if worker is None:
        return WithoutWorker(row.number, columns.worker - offset)
    operator = row.value(columns.activities - offset)
    kind = order_kind(row.value(columns.devices - offset))
    return RawOrder(row.number, shifted, when, str(worker), None if operator is None else str(operator).strip(), kind)


def _name(value: object) -> str:
    """Nazwa bez wielkości liter, spacji i myślników: ``T-Mobile`` i ``TMOBILE`` to ``tmobile``."""

    return re.sub(r"[\W_]+", "", str(value).casefold())


def _operator(text: str) -> str:
    """Nazwa operatora z ``CZYNNOŚCI`` jak ``_name``, a do tego bez dopisku ``S.A.``: ``Netia S.A.`` to ``netia``."""

    return _name(_COMPANY_SUFFIX.sub("", text))


def _above(
    first: RowFacts, rows: Iterator[RowFacts], columns: OrderColumns, day: date | None
) -> tuple[AboveOrdered | None, set[date]]:
    """Przegląd od ostatniego uporządkowanego wiersza ``first`` w górę: wiersz z wyglądem z aplikacji nad nim i dni.

    Dni to uporządkowane dni przeglądu: dzień dwóch kolejnych wierszy z datą albo wiersza, pod którym nie ma
    wcześniejszego dnia. Przegląd kończy ``_EARLIER_ROWS`` kolejnych wierszy z dniem wcześniejszym niż ``day`` (bez
    niego: dzień pierwszego wiersza z datą).
    """

    below = first.number
    days: set[date] = set()
    earlier = 0
    previous: date | None = None
    lowest: date | None = None
    for row in chain([first], rows):
        if row.blank:
            continue
        if not _is_ordered(row, columns):
            return AboveOrdered(row.number, below), days
        below = row.number
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
    return None, days


def _is_date(value: object) -> bool:
    return isinstance(value, datetime)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _order_cells(row: RowFacts, columns: OrderColumns) -> list[CellFacts]:
    return [
        cell
        for column, cell in row.cells.items()
        if columns.first <= column <= columns.last and column != columns.worker and cell.value is not None
    ]


def ordered_look(faces: Iterable[tuple[str | None, float | None]]) -> bool:
    """Wygląd wiersza uporządkowanego z kroju i rozmiaru czcionki (``faces``) jego komórek z wartością w kolumnach
    zlecenia bez ``WYKONAWCA``: choć jedna jest w Calibri 8."""

    return _ORDERED_FACE in faces


def _is_ordered(row: RowFacts, columns: OrderColumns) -> bool:
    return ordered_look(cell.face for cell in _order_cells(row, columns))


def _is_yellow(row: RowFacts, columns: OrderColumns) -> bool:
    span = range(columns.first, columns.last + 1)
    yellow = sum(1 for column in span if (cell.yellow if (cell := row.cells.get(column)) is not None else row.yellow))
    return 2 * yellow >= len(span)
