from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise, product
import re
from types import MappingProxyType
from typing import ClassVar, Final, NamedTuple

from .collective_layout import QUANTITY_LETTERS, REMARKS_AMOUNT, letter
from .quantity_engine import BUILT_IN_COLUMNS, MAX_VALUE, Quantities

NUMBER: Final = "{n}"
SHOWN_NUMBER: Final = "#"
AMOUNT_COLUMN: Final = letter(REMARKS_AMOUNT)
COLUMNS: Final = tuple(column for column in QUANTITY_LETTERS if column not in BUILT_IN_COLUMNS)
FILL_COLUMNS: Final = (*COLUMNS, AMOUNT_COLUMN)
YES_NO: Final = frozenset({"tak", "nie"})


class FillColour(StrEnum):
    GREEN = "zielony"
    RED = "czerwony"

    @property
    def argb(self) -> str:
        return _ARGB[self]


_ARGB: Final[Mapping[FillColour, str]] = {FillColour.GREEN: "FF92D050", FillColour.RED: "FFFF0000"}


@dataclass(frozen=True)
class FixedColumn:
    column: str


@dataclass(frozen=True)
class NumberRange:
    low: int
    high: int
    column: str


@dataclass(frozen=True)
class ColumnByNumber:
    ranges: tuple[NumberRange, ...]

    def column(self, number: int) -> str | None:
        return next((found.column for found in self.ranges if found.low <= number <= found.high), None)


ColumnChoice = FixedColumn | ColumnByNumber


@dataclass(frozen=True)
class CellFill:
    column: str
    colour: FillColour


@dataclass(frozen=True)
class ActivityCode:
    id: str
    spellings: tuple[str, ...]
    column: ColumnChoice | None = None
    value: int = 1
    amount: int | None = None
    fills: tuple[CellFill, ...] = ()
    counts_in_fault: bool = True


@dataclass(frozen=True)
class LegendProblem:
    field: str
    message: str


class LegendRefused(ValueError):
    def __init__(self, problem: LegendProblem) -> None:
        super().__init__(f"{problem.field}: {problem.message}")
        self.problem = problem


@dataclass(frozen=True)
class _Pattern:
    owner: ActivityCode
    spelling: str


@dataclass(frozen=True)
class ActivityLegend:
    codes: tuple[ActivityCode, ...]
    _patterns: tuple[_Pattern, ...] = field(init=False, repr=False, compare=False)
    _spellings: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        ids: set[str] = set()
        earlier: list[_Pattern] = []
        for code in self.codes:
            _check_code(code, ids, earlier)
        patterns = tuple(earlier)
        object.__setattr__(self, "_patterns", patterns)
        object.__setattr__(self, "_spellings", re.compile("|".join(_alternative(index, pattern.spelling) for index, pattern in enumerate(patterns))))

    def read(self, text: str, *, fault: bool) -> DescriptionRead:
        found: list[tuple[FoundCode, ActivityCode | None]] = []
        spelled: list[str] = []
        problems: list[DescriptionProblem] = []
        for word in (word for word in _WORD.findall(text) if word.strip("/")):
            match = self._spellings.fullmatch(word.casefold())
            if match is None:
                continue
            index = _index(match)
            pattern = self._patterns[index]
            number = int(match[f"{_NUMBER_GROUP}{index}"]) if NUMBER in pattern.spelling else None
            column = _column(pattern.owner.column, number)
            written = FoundCode(pattern.owner.id, pattern.spelling, number, column)
            spelled.append(written.spelled)
            if fault and not pattern.owner.counts_in_fault:
                found.append((written, None))
                continue
            if isinstance(pattern.owner.column, ColumnByNumber) and column is None:
                assert number is not None, "kod z przedziałami ma w każdym zapisie miejsce na liczbę"
                problems.append(NumberOutOfRange(pattern.owner.id, pattern.spelling, number))
                continue
            found.append((written, pattern.owner))
        counted = [(written, code) for written, code in found if code is not None]
        hits = [(written.column, code) for written, code in counted if written.column is not None]
        fills = [(fill, code.id) for _, code in counted for fill in code.fills]
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
            return DescriptionError(tuple(dict.fromkeys(problems)), tuple(spelled))
        if not found:
            return NO_CODES
        values = {column: code.value for column, code in hits}
        colours = {fill.column: fill.colour for fill, _ in fills}
        return WithCodes(
            found=tuple(written for written, _ in found),
            quantities=MappingProxyType({column: values[column] for column in QUANTITY_LETTERS if column in values}),
            amount=sum(code.amount or 0 for _, code in counted),
            fills=MappingProxyType({column: colours[column] for column in FILL_COLUMNS if column in colours}),
        )


@dataclass(frozen=True)
class FoundCode:
    code: str
    spelling: str
    number: int | None
    column: str | None

    @property
    def spelled(self) -> str:
        return self.spelling if self.number is None else self.spelling.replace(NUMBER, str(self.number))


@dataclass(frozen=True)
class NoCodes:
    spelled: ClassVar[tuple[str, ...]] = ()


@dataclass(frozen=True)
class WithCodes:
    found: tuple[FoundCode, ...]
    quantities: Quantities
    amount: int
    fills: Mapping[str, FillColour]

    @property
    def spelled(self) -> tuple[str, ...]:
        return tuple(found.spelled for found in self.found)


@dataclass(frozen=True)
class NumberOutOfRange:
    code: str
    spelling: str
    number: int
    reason: ClassVar[str] = "kod z liczbą spoza przedziałów"

    @property
    def detail(self) -> str:
        return self.spelling.replace(NUMBER, str(self.number))


@dataclass(frozen=True)
class ColumnTwice:
    column: str
    codes: tuple[str, ...]
    reason: ClassVar[str] = "kolumna Ilości usług trafiona drugi raz"

    @property
    def detail(self) -> str:
        return f"{self.column}: {', '.join(self.codes)}"


@dataclass(frozen=True)
class TwoColours:
    column: str
    codes: tuple[str, ...]
    reason: ClassVar[str] = "kolumna wypełniona dwoma kolorami"

    @property
    def detail(self) -> str:
        return f"{self.column}: {', '.join(self.codes)}"


DescriptionProblem = NumberOutOfRange | ColumnTwice | TwoColours
REASONS: Final = tuple(kind.reason for kind in (NumberOutOfRange, ColumnTwice, TwoColours))


@dataclass(frozen=True)
class DescriptionError:
    problems: tuple[DescriptionProblem, ...]
    spelled: tuple[str, ...]


DescriptionRead = NoCodes | WithCodes | DescriptionError

NO_CODES: Final = NoCodes()


def problem_text(problem: DescriptionProblem) -> str:
    return f"{problem.reason} ({problem.detail})"


def shown_spelling(spelling: str) -> str:
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
    atoms = [rf"(?P<{_NUMBER_GROUP}{index}>[0-9]+)" if part == NUMBER else re.escape(part) for part in re.split(r"(\{n\})", spelling) if part]
    return rf"(?P<{_SPELLING_GROUP}{index}>" + "".join(atoms) + ")"


def _index(match: re.Match[str]) -> int:
    # ZEWNĘTRZNE: lastgroup to nazwa grupy, która domknęła się ostatnia, więc przy grupie liczby w środku grupy zapisu to nazwa grupy zapisu (dokumentacja Pythona, re.Match.lastindex i re.Match.lastgroup)
    assert match.lastgroup is not None, "każdy zapis legendy ma swoją grupę"
    return int(match.lastgroup.removeprefix(_SPELLING_GROUP))


def _require(holds: bool, path: str, message: str) -> None:
    if not holds:
        raise LegendRefused(LegendProblem(path, message))


def _is_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_code(code: ActivityCode, ids: set[str], earlier: list[_Pattern]) -> None:
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
        _require(
            spelling not in YES_NO,
            f"{path}.zapisy[{index}]",
            f"Zapis „{spelling}” to słowo, które w opisie może stać obok kodów i nie jest kodem, więc ten zapis nigdy "
            "niczego nie wpisze.",
        )
        pattern = _Pattern(code, spelling)
        for before in earlier:
            if (word := _shortest_common_word(before.spelling, spelling)) is not None:
                raise LegendRefused(LegendProblem(f"{path}.zapisy[{index}]", _shared_word(before, pattern, word)))
        earlier.append(pattern)
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


def _shared_word(before: _Pattern, pattern: _Pattern, word: str) -> str:
    spelling, other = shown_spelling(pattern.spelling), shown_spelling(before.spelling)
    name = shown_spelling(before.owner.spellings[0])
    if before.spelling == pattern.spelling:
        return f"Zapis „{spelling}” jest w tym kodzie dwa razy." if before.owner is pattern.owner else f"Zapis „{spelling}” ma już kod „{name}”."
    whose = "tego kodu" if before.owner is pattern.owner else f"kodu „{name}”"
    return (
        f"Zapis „{spelling}” i zapis „{other}” {whose} pasują do tego samego słowa „{word}”, a słowo w opisie może "
        "pasować tylko do jednego zapisu."
    )


class _State(NamedTuple):
    atom: int
    has_digit: bool


_DIGITS: Final = "1234567890"


def _shortest_common_word(first: str, second: str) -> str | None:
    atoms = (_atoms(first), _atoms(second))
    start = (_State(0, False), _State(0, False))
    words = {start: ""}
    queue = deque([start])
    while queue:
        pair = queue.popleft()
        if _ends(atoms[0], pair[0]) and _ends(atoms[1], pair[1]):
            return words[pair]
        for char in dict.fromkeys(char for state in _closure(pair[0]) for char in _readable(atoms[0], state)):
            for after in product(_after(atoms[0], pair[0], char), _after(atoms[1], pair[1], char)):
                if after not in words:
                    words[after] = words[pair] + char
                    queue.append(after)
    return None


def _atoms(spelling: str) -> tuple[str, ...]:
    return tuple(atom for part in re.split(r"(\{n\})", spelling) for atom in ((part,) if part == NUMBER else part))


def _closure(state: _State) -> tuple[_State, ...]:
    return (state, _State(state.atom + 1, False)) if state.has_digit else (state,)


def _readable(atoms: tuple[str, ...], state: _State) -> str:
    if state.atom == len(atoms):
        return ""
    return _DIGITS if atoms[state.atom] == NUMBER else atoms[state.atom]


def _after(atoms: tuple[str, ...], state: _State, char: str) -> tuple[_State, ...]:
    return tuple(
        _State(place, True) if atoms[place] == NUMBER else _State(place + 1, False)
        for place, _ in _closure(state)
        if char in _readable(atoms, _State(place, False))
    )


def _ends(atoms: tuple[str, ...], state: _State) -> bool:
    return _State(len(atoms), False) in _closure(state)


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
