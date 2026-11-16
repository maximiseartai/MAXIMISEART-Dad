"""Legenda czynności (ADR 0038): Ilości usług, kwota w ``AS`` i Wyróżnienia z Kodów czynności w ``CZYNNOŚCI ZREALIZOWANE``.

Jedyną operacją jest ``read_codes(legend, text)``, czysta funkcja bez plików i bez Centrum rozliczeń; liczą nią
Przygotowanie pliku zbiorczego, Ilości do uzupełnienia, Kontrola ilości, podgląd zmiany legendy i brama. Niezmienniki
legendy sprawdza sam typ ``ActivityLegend`` przy tworzeniu, więc legenda z błędem nie powstaje (``LegendRefused`` z
polem i zdaniem). Plik legendy ↔ typy: ``activity_legend_file``.

Zapis Kodu czynności to małe litery, cyfry i ``/`` bez spacji, od litery, z co najwyżej jednym miejscem na liczbę
``{n}`` (``inst{n}m``, ``instwewrg6{n}m``, ``dzielnik1/2``). Rachunek tekstu:

1. Tekst czyta się małymi literami (``casefold``). Zapis pasuje także ze spacjami między znakami (``inst utp17m``,
   ``dzielnik 1 /2``), a ``{n}`` to ciąg cyfr bez spacji. Zapis kończący się cyfrą nie ma po niej cyfry (``rt25`` to nie
   ``rt2``).
2. Zapis nie zaczyna się w środku słowa: przed nim stoi początek tekstu, znak niebędący literą ani cyfrą albo koniec
   innego kodu, więc ``xinst20m`` i ``art2`` to nie kody, a kody sklejone bez spacji liczą się wszystkie
   (``spawpgspawez`` to ``spawpg`` i ``spawez``, w każdej kolejności).
3. Tekst czyta się od lewej. W miejscu, gdzie może zacząć się zapis, pasuje najdłuższy (najwięcej znaków poza ``{n}``),
   przy równej długości pierwszy w legendzie, a czytanie idzie dalej za nim, więc ``instwewrg610m`` jest tylko
   ``instwewrg6``, a nie także ``instwew``.
4. Kod z przedziałami wybiera kolumnę liczbą z zapisu. Liczba spoza przedziałów niczego nie wyznacza: kod jest wtedy w
   ``out_of_range``, a nie w ``found``. Kod bez przedziałów liczby nie czyta.
5. Każde wystąpienie kodu dodaje swoją wartość w kolumnie i swoją kwotę w ``AS``; różne kody się sumują. Wypełnienie
   kolumny daje pierwszy w tekście kod, który ją wypełnia.
6. Tekst z samych kodów (``only_codes``) to tekst z co najmniej jednym kodem w ``found``, bez kodu spoza przedziałów,
   w którym poza kodami stoją najwyżej słowa ``tak`` i ``nie`` oraz znaki niebędące literą ani cyfrą.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
import re
from types import MappingProxyType
from typing import Final

from .collective_layout import QUANTITY_LETTERS, REMARKS_AMOUNT, letter
from .quantity_engine import BUILT_IN_COLUMNS, MAX_VALUE, Quantities

NUMBER: Final = "{n}"
"""Miejsce na liczbę w zapisie Kodu czynności."""
AMOUNT_COLUMN: Final = letter(REMARKS_AMOUNT)
"""``AS`` (Uwagi - kwota): kolumna kwoty Kodu czynności, nigdy kolumna jego Ilości usług."""
COLUMNS: Final = tuple(column for column in QUANTITY_LETTERS if column not in BUILT_IN_COLUMNS)
"""Kolumny, w które kod wpisuje Ilość usług: ``N:AP`` bez wbudowanych rachunków P, Q i S."""
FILL_COLUMNS: Final = (*COLUMNS, AMOUNT_COLUMN)
"""Kolumny, które kod wypełnia kolorem."""
ONLY_CODES_WORDS: Final = frozenset({"tak", "nie"})
"""Słowa, które mogą stać obok kodów w tekście z samych kodów."""


class FillColour(StrEnum):
    """Kolor wypełnienia z plików taty; ``argb`` to zapis koloru w skoroszycie."""

    GREEN = "zielony"
    RED = "czerwony"

    @property
    def argb(self) -> str:
        return _ARGB[self]


_ARGB: Final[Mapping[FillColour, str]] = {FillColour.GREEN: "FF92D050", FillColour.RED: "FFFF0000"}


@dataclass(frozen=True)
class FixedColumn:
    """Kod wpisuje w jedną kolumnę bez względu na liczbę w zapisie."""

    column: str


@dataclass(frozen=True)
class NumberRange:
    """Liczba z zapisu od ``low`` do ``high`` włącznie wybiera kolumnę ``column``."""

    low: int
    high: int
    column: str


@dataclass(frozen=True)
class ColumnByNumber:
    """Kod wybiera kolumnę liczbą z zapisu; przedziały są rozłączne, w kolejności z pliku."""

    ranges: tuple[NumberRange, ...]

    def column(self, number: int) -> str | None:
        return next((found.column for found in self.ranges if found.low <= number <= found.high), None)


ColumnChoice = FixedColumn | ColumnByNumber


@dataclass(frozen=True)
class CellFill:
    """Wypełnienie kolumny kolorem: Wyróżnienie, także bez wartości w komórce."""

    column: str
    colour: FillColour


@dataclass(frozen=True)
class ActivityCode:
    """Kod czynności: stały identyfikator, zapisy tej samej rzeczy i to, co wyznacza w Pliku zbiorczym."""

    id: str
    spellings: tuple[str, ...]
    column: ColumnChoice | None = None
    value: int = 1
    """Ilość usług w kolumnie ``column`` za jedno wystąpienie; bez kolumny 1."""
    amount: int | None = None
    """Kwota w ``AS`` za jedno wystąpienie; ``None``: bez kwoty."""
    fills: tuple[CellFill, ...] = ()


@dataclass(frozen=True)
class LegendProblem:
    """Pierwsza rzecz, przez którą Legenda czynności nie może powstać: pole pliku i zdanie dla taty."""

    field: str
    message: str


class LegendRefused(ValueError):
    def __init__(self, problem: LegendProblem) -> None:
        super().__init__(f"{problem.field}: {problem.message}")
        self.problem = problem


@dataclass(frozen=True)
class _Pattern:
    code: ActivityCode
    spelling: str


@dataclass(frozen=True)
class ActivityLegend:
    """Legenda czynności: identyfikatory kodów są różne, zapis należy do jednego kodu, a każdy kod coś wyznacza."""

    codes: tuple[ActivityCode, ...]
    _patterns: tuple[_Pattern, ...] = field(init=False, repr=False, compare=False)
    _after_boundary: re.Pattern[str] = field(init=False, repr=False, compare=False)
    """Zapis po początku tekstu albo po znaku niebędącym literą ani cyfrą."""
    _after_code: re.Pattern[str] = field(init=False, repr=False, compare=False)
    """Zapis zaraz za końcem innego kodu."""

    def __post_init__(self) -> None:
        owners: dict[str, ActivityCode] = {}
        ids: set[str] = set()
        for code in self.codes:
            _check_code(code, ids, owners)
        patterns = sorted(
            (_Pattern(code, spelling) for code in self.codes for spelling in code.spellings),
            key=lambda pattern: -len(pattern.spelling.replace(NUMBER, "")),
        )
        alternatives = "|".join(_alternative(index, pattern.spelling) for index, pattern in enumerate(patterns))
        object.__setattr__(self, "_patterns", tuple(patterns))
        object.__setattr__(self, "_after_boundary", re.compile(rf"(?<![^\W_])(?:{alternatives})"))
        object.__setattr__(self, "_after_code", re.compile(alternatives))

    def read(self, text: str) -> CodesRead:
        """Wynik legendy dla tekstu; woła go ``read_codes``."""

        folded = text.casefold()
        hits: list[tuple[FoundCode, ActivityCode, str | None]] = []
        between: list[str] = []
        end = 0
        match = self._after_boundary.search(folded)
        while match is not None:
            between.append(folded[end : match.start()])
            index = _index(match)
            pattern = self._patterns[index]
            number = int(match[f"{_NUMBER_GROUP}{index}"]) if NUMBER in pattern.spelling else None
            hits.append((FoundCode(pattern.code.id, pattern.spelling, number), pattern.code, _column(pattern.code.column, number)))
            end = match.end()
            match = self._after_code.match(folded, end) or self._after_boundary.search(folded, end)
        if not hits:
            return NOTHING_READ
        between.append(folded[end:])
        acting = [(found, code, column) for found, code, column in hits if not _outside(code, column)]
        out_of_range = tuple(found for found, code, column in hits if _outside(code, column))
        quantities: Counter[str] = Counter()
        fills: dict[str, FillColour] = {}
        amount = 0
        for _, code, column in acting:
            if column is not None:
                quantities[column] += code.value
            amount += code.amount or 0
            for fill in code.fills:
                fills.setdefault(fill.column, fill.colour)
        words = [word for part in between for word in _WORD.findall(part)]
        return CodesRead(
            found=tuple(found for found, _, _ in acting),
            quantities=MappingProxyType({column: quantities[column] for column in QUANTITY_LETTERS if quantities[column]}),
            amount=amount,
            fills=MappingProxyType({column: fills[column] for column in FILL_COLUMNS if column in fills}),
            out_of_range=out_of_range,
            only_codes=bool(acting) and not out_of_range and all(word in ONLY_CODES_WORDS for word in words),
        )


@dataclass(frozen=True)
class FoundCode:
    """Wystąpienie Kodu czynności w tekście: identyfikator kodu, zapis, którym pasuje, i liczba z zapisu (``None``: zapis
    bez ``{n}``)."""

    code: str
    spelling: str
    number: int | None


@dataclass(frozen=True)
class CodesRead:
    """Wynik Legendy czynności dla tekstu ``CZYNNOŚCI ZREALIZOWANE``.

    ``found``: kody, które coś wyznaczyły, w kolejności z tekstu. ``quantities``: kolumna → suma Ilości usług, tylko
    różne od zera, w kolejności kolumn. ``amount``: suma kwot w ``AS`` (0: bez kwoty). ``fills``: kolumna → kolor
    wypełnienia. ``out_of_range``: kody z liczbą spoza przedziałów, w kolejności z tekstu. ``only_codes``: tekst z samych
    kodów, więc wiersz nie czeka na tatę w kolumnach z opisu technika.
    """

    found: tuple[FoundCode, ...]
    quantities: Quantities
    amount: int
    fills: Mapping[str, FillColour]
    out_of_range: tuple[FoundCode, ...]
    only_codes: bool


NOTHING_READ: Final = CodesRead((), MappingProxyType({}), 0, MappingProxyType({}), (), only_codes=False)
"""Wynik tekstu bez Kodu czynności."""


def read_codes(legend: ActivityLegend, text: str) -> CodesRead:
    """Kody czynności w tekście ``text`` i to, co wyznaczają (zob. rachunek w opisie modułu)."""

    return legend.read(text)


_SPELLING_GROUP: Final = "zapis"
_NUMBER_GROUP: Final = "liczba"
_WORD: Final = re.compile(r"[^\W_]+")
_SPELLING: Final = re.compile(r"[^\W\d_](?:[^\W_]|/|\{n\})*")


def _column(choice: ColumnChoice | None, number: int | None) -> str | None:
    match choice:
        case None:
            return None
        case FixedColumn(column=column):
            return column
        case ColumnByNumber():
            return None if number is None else choice.column(number)


def _outside(code: ActivityCode, column: str | None) -> bool:
    return isinstance(code.column, ColumnByNumber) and column is None


def _alternative(index: int, spelling: str) -> str:
    """Wzorzec zapisu numer ``index`` w alternatywie legendy: znaki zapisu ze spacjami między nimi, ``{n}`` jako liczba w
    grupie ``liczba<index>``, a po zapisie kończącym się cyfrą bez cyfry."""

    atoms = [rf"(?P<{_NUMBER_GROUP}{index}>[0-9]+)" if part == NUMBER else re.escape(part) for part in re.split(r"(\{n\})|", spelling) if part]
    tail = r"(?![0-9])" if spelling[-1].isdigit() else ""
    return rf"(?P<{_SPELLING_GROUP}{index}>" + r"\s*".join(atoms) + tail + ")"


def _index(match: re.Match[str]) -> int:
    """Numer zapisu, który pasuje: grupa zapisu zamyka się po grupie liczby, więc jest ostatnią (``lastgroup``)."""

    assert match.lastgroup is not None, "każdy zapis legendy ma swoją grupę"
    return int(match.lastgroup.removeprefix(_SPELLING_GROUP))


def _require(holds: bool, path: str, message: str) -> None:
    if not holds:
        raise LegendRefused(LegendProblem(path, message))


def _is_number(value: object) -> bool:
    """Liczba całkowita, ale nie ``True`` ani ``False``, które Python liczy jako 1 i 0."""

    return isinstance(value, int) and not isinstance(value, bool)


def _check_code(code: ActivityCode, ids: set[str], owners: dict[str, ActivityCode]) -> None:
    path = f"kody[{code.id}]"
    _require(bool(code.id) and code.id == code.id.strip(), f"{path}.id", "Kod potrzebuje nazwy bez spacji na początku i końcu.")
    _require(code.id not in ids, f"{path}.id", f"Kod „{code.id}” jest w legendzie dwa razy.")
    ids.add(code.id)
    _require(bool(code.spellings), f"{path}.zapisy", "Kod potrzebuje co najmniej jednego zapisu.")
    for spelling in code.spellings:
        _require(
            _SPELLING.fullmatch(spelling) is not None and spelling == spelling.casefold() and spelling.count(NUMBER) <= 1,
            f"{path}.zapisy",
            f"Zapis „{spelling}” wpisz małymi literami, cyframi i „/”, bez spacji, od litery, z co najwyżej jednym {NUMBER}.",
        )
        owner = owners.setdefault(spelling, code)
        _require(owner is code, f"{path}.zapisy", f"Zapis „{spelling}” ma już kod „{owner.id}”.")
    _require(
        code.column is not None or code.amount is not None or bool(code.fills),
        path,
        "Kod musi coś wyznaczać: Ilość usług w kolumnie, kwotę w AS albo kolor.",
    )
    _check_column(code, path)
    _require(
        _is_number(code.value) and 1 <= code.value <= MAX_VALUE and (code.column is not None or code.value == 1),
        f"{path}.wartosc",
        f"Wartość musi być liczbą całkowitą od 1 do {MAX_VALUE} i mieć kolumnę.",
    )
    _require(
        code.amount is None or (_is_number(code.amount) and 1 <= code.amount <= MAX_VALUE),
        f"{path}.kwota",
        f"Kwota w AS musi być liczbą całkowitą od 1 do {MAX_VALUE}.",
    )
    filled: set[str] = set()
    for fill in code.fills:
        _require(fill.column in FILL_COLUMNS, f"{path}.wypelnienia", f"Kolumny {fill.column} kod nie wypełnia: wybierz kolumnę N:AP bez P, Q i S albo AS.")
        _require(fill.column not in filled, f"{path}.wypelnienia", f"Kolumna {fill.column} ma dwa kolory.")
        filled.add(fill.column)


def _check_column(code: ActivityCode, path: str) -> None:
    path_ranges = f"{path}.przedzialy"
    match code.column:
        case None:
            pass
        case FixedColumn(column=column):
            _check_letter(column, f"{path}.kolumna")
        case ColumnByNumber(ranges=ranges):
            _require(bool(ranges), path_ranges, "Wybór kolumny liczbą potrzebuje co najmniej jednego przedziału.")
            _require(
                all(NUMBER in spelling for spelling in code.spellings),
                path_ranges,
                f"Przedziały wybierają kolumnę liczbą z zapisu, więc każdy zapis kodu potrzebuje {NUMBER}.",
            )
            for index, found in enumerate(ranges):
                where = f"{path_ranges}[{index}]"
                _require(
                    _is_number(found.low) and _is_number(found.high) and 1 <= found.low <= found.high,
                    where,
                    "Przedział to liczby całkowite od 1, a „od” nie jest większe niż „do”.",
                )
                _check_letter(found.column, f"{where}.kolumna")
            ordered = sorted(ranges, key=lambda found: found.low)
            for before, after in pairwise(ordered):
                _require(after.low > before.high, path_ranges, f"Przedziały {before.low}–{before.high} i {after.low}–{after.high} zachodzą na siebie.")


def _check_letter(column: str, path: str) -> None:
    _require(column != AMOUNT_COLUMN, path, "AS przyjmuje tylko kwotę: wpisz ją w pole kwoty.")
    _require(column in COLUMNS, path, f"Kolumna „{column}” nie jest kolumną Ilości usług N:AP bez P, Q i S.")
