"""Legenda czynności (ADR 0038, 0039): Ilości usług, kwota w ``AS`` i Wyróżnienia z Kodów czynności w ``CZYNNOŚCI ZREALIZOWANE``.

Jedyną operacją jest ``ActivityLegend.read(text)``, czysta funkcja bez plików i bez Centrum rozliczeń; liczą nią
Przygotowanie pliku zbiorczego, Ilości do uzupełnienia, Kontrola ilości, podgląd zmiany legendy i brama. Niezmienniki
legendy sprawdza sam typ ``ActivityLegend`` przy tworzeniu, więc legenda z błędem nie powstaje (``LegendRefused`` z
polem i zdaniem). Plik legendy ↔ typy: ``activity_legend_file``.

Zapis Kodu czynności to małe litery, cyfry i ``/`` bez spacji, od litery, z co najwyżej jednym miejscem na liczbę
``{n}`` (``inst{n}m``, ``instwewrg6{n}m``, ``dzielnik1/2``). Opis technika to same Kody czynności, a każde odstępstwo
to Błąd opisu, także opis bez żadnego kodu. Rachunek tekstu:

1. Słowo to ciąg liter, cyfr i ``/`` z co najmniej jedną literą albo cyfrą; słowa rozdziela każdy inny znak (spacja,
   przecinek, kropka, nowy wiersz), a sam ``/`` między słowami też.
2. Słowo jest Kodem czynności, gdy małymi literami (``casefold``) jest w całości zapisem kodu, a ``{n}`` to ciąg cyfr.
   Gdy pasują zapisy dwóch kodów, słowo należy do pierwszego w legendzie. Słowa ``tak`` i ``nie`` nie są niczym.
   Każde inne słowo to Błąd opisu (``NotACode``): zwykły opis, własny zapis pracownika (``utp18m``, ``instmdic``), kod
   ze spacją w środku (``inst 20m``), kody sklejone (``spawpgspawez``) i kod w dłuższym słowie (``xinst20m``).
3. Kod z przedziałami wybiera kolumnę liczbą z zapisu, a kod z liczbą spoza przedziałów to Błąd opisu (``NumberOutOfRange``).
   Kod bez przedziałów liczby nie czyta.
4. W kolumnę Ilości usług wpisuje najwyżej jeden kod: drugi, także ten sam kod drugi raz, to Błąd opisu
   (``ColumnTwice``). Kwoty w ``AS`` się sumują. Kolumna, którą kody wypełniają dwoma różnymi kolorami, to Błąd opisu
   (``TwoColours``); ten sam kolor z dwóch kodów nie.
5. Wynik to ``NoCodes`` (opis pusty albo z samych ``tak`` i ``nie``), ``CodesOnly`` (same poprawne kody z tym, co
   wyznaczają) albo ``DescriptionError`` z każdym powodem: najpierw słowa w kolejności z opisu, potem kolumny w
   kolejności arkusza. Błąd opisu niczego nie wyznacza w wierszu, nawet za poprawne kody obok.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
import re
from types import MappingProxyType
from typing import ClassVar, Final

from .collective_layout import QUANTITY_LETTERS, REMARKS_AMOUNT, letter
from .quantity_engine import BUILT_IN_COLUMNS, MAX_VALUE, Quantities

NUMBER: Final = "{n}"
"""Miejsce na liczbę w zapisie Kodu czynności."""
SHOWN_NUMBER: Final = "#"
"""Miejsce na liczbę w zapisie pokazanym tacie: w zdaniach kodów, w odmowach i w formularzu kodu."""
AMOUNT_COLUMN: Final = letter(REMARKS_AMOUNT)
"""``AS`` (Uwagi - kwota): kolumna kwoty Kodu czynności, nigdy kolumna jego Ilości usług."""
COLUMNS: Final = tuple(column for column in QUANTITY_LETTERS if column not in BUILT_IN_COLUMNS)
"""Kolumny, w które kod wpisuje Ilość usług: ``N:AP`` bez wbudowanych rachunków P, Q i S."""
FILL_COLUMNS: Final = (*COLUMNS, AMOUNT_COLUMN)
"""Kolumny, które kod wypełnia kolorem."""
YES_NO: Final = frozenset({"tak", "nie"})
"""Słowa, które mogą stać w opisie obok kodów i nie są Błędem opisu."""


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
    _spellings: re.Pattern[str] = field(init=False, repr=False, compare=False)
    """Zapisy kodów w kolejności legendy, każdy w swojej grupie."""

    def __post_init__(self) -> None:
        owners: dict[str, ActivityCode] = {}
        ids: set[str] = set()
        for code in self.codes:
            _check_code(code, ids, owners)
        patterns = tuple(_Pattern(code, spelling) for code in self.codes for spelling in code.spellings)
        object.__setattr__(self, "_patterns", patterns)
        object.__setattr__(self, "_spellings", re.compile("|".join(_alternative(index, pattern.spelling) for index, pattern in enumerate(patterns))))

    def read(self, text: str) -> DescriptionRead:
        """Wynik legendy dla opisu technika ``text`` (zob. rachunek w opisie modułu)."""

        found: list[tuple[FoundCode, ActivityCode]] = []
        problems: list[DescriptionProblem] = []
        for word in (word for word in _WORD.findall(text) if word.strip("/")):
            folded = word.casefold()
            if folded in YES_NO:
                continue
            match = self._spellings.fullmatch(folded)
            if match is None:
                problems.append(NotACode(word))
                continue
            index = _index(match)
            pattern = self._patterns[index]
            number = int(match[f"{_NUMBER_GROUP}{index}"]) if NUMBER in pattern.spelling else None
            column = _column(pattern.code.column, number)
            if isinstance(pattern.code.column, ColumnByNumber) and column is None:
                assert number is not None, "kod z przedziałami ma w każdym zapisie miejsce na liczbę"
                problems.append(NumberOutOfRange(pattern.code.id, pattern.spelling, number))
                continue
            found.append((FoundCode(pattern.code.id, pattern.spelling, number, column), pattern.code))
        hits = [(written.column, code) for written, code in found if written.column is not None]
        fills = [(fill, code.id) for _, code in found for fill in code.fills]
        problems.extend(
            ColumnTwice(column, codes)
            for column in QUANTITY_LETTERS
            if len(codes := tuple(code.id for hit, code in hits if hit == column)) > 1
        )
        problems.extend(
            TwoColours(column, tuple(code for fill, code in fills if fill.column == column))
            for column in FILL_COLUMNS
            if len({fill.colour for fill, _ in fills if fill.column == column}) > 1
        )
        if problems:
            return DescriptionError(tuple(dict.fromkeys(problems)))
        if not found:
            return NO_CODES
        values = {column: code.value for column, code in hits}
        colours = {fill.column: fill.colour for fill, _ in fills}
        return CodesOnly(
            found=tuple(written for written, _ in found),
            quantities=MappingProxyType({column: values[column] for column in QUANTITY_LETTERS if column in values}),
            amount=sum(code.amount or 0 for _, code in found),
            fills=MappingProxyType({column: colours[column] for column in FILL_COLUMNS if column in colours}),
        )


@dataclass(frozen=True)
class FoundCode:
    """Kod czynności w opisie: identyfikator kodu, zapis, którym pasuje, liczba z zapisu (``None``: zapis bez ``{n}``) i
    kolumna Ilości usług, w którą wpisuje (``None``: kod bez kolumny)."""

    code: str
    spelling: str
    number: int | None
    column: str | None


@dataclass(frozen=True)
class NoCodes:
    """Opis pusty albo z samych ``tak`` i ``nie``: bez kodu i bez Błędu opisu, więc legenda nic w nim nie wpisuje, a wiersz
    zostaje tacie."""


@dataclass(frozen=True)
class CodesOnly:
    """Opis z samych poprawnych Kodów czynności, więc legenda wpisuje w wierszu swoje, a wiersz nie czeka na tatę w
    kolumnach z opisu technika.

    ``found``: kody w kolejności z opisu. ``quantities``: kolumna → Ilość usług, w kolejności kolumn. ``amount``: suma
    kwot w ``AS`` (0: bez kwoty). ``fills``: kolumna → kolor wypełnienia, w kolejności arkusza.
    """

    found: tuple[FoundCode, ...]
    quantities: Quantities
    amount: int
    fills: Mapping[str, FillColour]


@dataclass(frozen=True)
class NotACode:
    """Słowo opisu, które nie jest zapisem żadnego Kodu czynności ani ``tak`` czy ``nie``, tak jak w opisie."""

    word: str
    reason: ClassVar[str] = "słowo inne niż zapis kodu"


@dataclass(frozen=True)
class NumberOutOfRange:
    """Kod czynności ``code`` w zapisie ``spelling`` z liczbą ``number`` spoza przedziałów kodu."""

    code: str
    spelling: str
    number: int
    reason: ClassVar[str] = "kod z liczbą spoza przedziałów"

    @property
    def detail(self) -> str:
        """Kod z liczbą w miejscu ``{n}`` (``instutp40m``): z zapisu legendy, nie z tekstu technika."""

        return self.spelling.replace(NUMBER, str(self.number))


@dataclass(frozen=True)
class ColumnTwice:
    """W kolumnę Ilości usług ``column`` wpisuje więcej niż jeden kod: ``codes`` w kolejności z opisu, z powtórzeniami."""

    column: str
    codes: tuple[str, ...]
    reason: ClassVar[str] = "kolumna Ilości usług trafiona drugi raz"

    @property
    def detail(self) -> str:
        return f"{self.column}: {', '.join(self.codes)}"


@dataclass(frozen=True)
class TwoColours:
    """Kody ``codes`` (w kolejności z opisu) wypełniają kolumnę ``column`` różnymi kolorami."""

    column: str
    codes: tuple[str, ...]
    reason: ClassVar[str] = "kolumna wypełniona dwoma kolorami"

    @property
    def detail(self) -> str:
        return f"{self.column}: {', '.join(self.codes)}"


DescriptionProblem = NotACode | NumberOutOfRange | ColumnTwice | TwoColours
"""Powód Błędu opisu: ``reason`` to rodzaj powodu. Tylko ``NotACode.word`` niesie tekst technika; ``detail`` pozostałych
to kod z liczbą albo kolumna z identyfikatorami kodów."""
REASONS: Final = tuple(kind.reason for kind in (NotACode, NumberOutOfRange, ColumnTwice, TwoColours))
"""Rodzaje powodów Błędu opisu w stałej kolejności."""


@dataclass(frozen=True)
class DescriptionError:
    """Błąd opisu: opis technika nie jest z samych poprawnych Kodów czynności, więc legenda nic w wierszu nie wpisuje, a
    wiersz zostaje tacie. ``problems``: każdy powód raz (zob. opis modułu, punkt 5)."""

    problems: tuple[DescriptionProblem, ...]


DescriptionRead = NoCodes | CodesOnly | DescriptionError
"""Wynik Legendy czynności dla opisu technika ``CZYNNOŚCI ZREALIZOWANE``."""

NO_CODES: Final = NoCodes()


def problem_text(problem: DescriptionProblem) -> str:
    """Powód Błędu opisu słowami, ten sam dla taty i Maksa (``kod z liczbą spoza przedziałów (instutp40m)``), bez tekstu
    technika: słowo inne niż zapis kodu to sam rodzaj powodu. Słowo osobno ominęłoby strażnika reguły danych, który maskuje
    wartość tylko z jej słowami po kolei, więc pokazuje je opis technika obok powodu."""

    match problem:
        case NotACode():
            return problem.reason
        case NumberOutOfRange() | ColumnTwice() | TwoColours():
            return f"{problem.reason} ({problem.detail})"


def shown_spelling(spelling: str) -> str:
    """Zapis Kodu czynności tak, jak widzi go tata: miejsce na liczbę to ``#`` (``inst#m``)."""

    return spelling.replace(NUMBER, SHOWN_NUMBER)


_SPELLING_GROUP: Final = "zapis"
_NUMBER_GROUP: Final = "liczba"
_WORD: Final = re.compile(r"(?:[^\W_]|/)+")
_SPELLING: Final = re.compile(r"[^\W\d_](?:[^\W_]|/|\{n\})*")


def _column(choice: ColumnChoice | None, number: int | None) -> str | None:
    match choice:
        case None:
            return None
        case FixedColumn(column=column):
            return column
        case ColumnByNumber():
            return None if number is None else choice.column(number)


def _alternative(index: int, spelling: str) -> str:
    """Wzorzec zapisu numer ``index`` w alternatywie legendy: znaki zapisu, a ``{n}`` jako liczba w grupie
    ``liczba<index>``."""

    atoms = [rf"(?P<{_NUMBER_GROUP}{index}>[0-9]+)" if part == NUMBER else re.escape(part) for part in re.split(r"(\{n\})", spelling) if part]
    return rf"(?P<{_SPELLING_GROUP}{index}>" + "".join(atoms) + ")"


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
    for index, spelling in enumerate(code.spellings):
        _require(
            _SPELLING.fullmatch(spelling) is not None and spelling == spelling.casefold() and spelling.count(NUMBER) <= 1,
            f"{path}.zapisy[{index}]",
            f"Zapis „{shown_spelling(spelling)}” wpisz małymi literami, cyframi i „/”, bez spacji, od litery, z co najwyżej "
            f"jednym miejscem na liczbę ({SHOWN_NUMBER}).",
        )
        owner = owners.setdefault(spelling, code)
        _require(
            owner is code,
            f"{path}.zapisy[{index}]",
            f"Zapis „{shown_spelling(spelling)}” ma już kod „{shown_spelling(owner.spellings[0])}”.",
        )
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
    for index, fill in enumerate(code.fills):
        where = f"{path}.wypelnienia[{index}]"
        _require(fill.column in FILL_COLUMNS, where, f"Kolumny {fill.column} kod nie wypełnia: wybierz kolumnę N:AP bez P, Q i S albo AS.")
        _require(fill.column not in filled, where, f"Kolumna {fill.column} ma już kolor.")
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
            for index, spelling in enumerate(code.spellings):
                _require(
                    NUMBER in spelling,
                    f"{path}.zapisy[{index}]",
                    f"Zapis „{spelling}” potrzebuje miejsca na liczbę ({SHOWN_NUMBER}), bo przedziały wybierają kolumnę "
                    "liczbą z zapisu.",
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
