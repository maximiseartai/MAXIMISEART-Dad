from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Final, assert_never

from rozliczenia.activity_legend import (
    NUMBER,
    SHOWN_NUMBER,
    ActivityCode,
    ActivityLegend,
    CellFill,
    ColumnByNumber,
    ColumnChoice,
    FillColour,
    FixedColumn,
    LegendRefused,
    NumberRange,
    shown_spelling,
)
from rozliczenia.centrum.contract import activity_legend as contract
from rozliczenia.centrum.settings.files import FieldName, FieldPath, FieldProblem

_COLOURS: Final[Mapping[FillColour, contract.FillColourName]] = {FillColour.GREEN: "zielony", FillColour.RED: "czerwony"}
_CODE_FIELD: Final = re.compile(
    r"(?P<list>zapisy|przedzialy|wypelnienia)(?:\[(?P<index>\d+)\](?:\.(?P<range_field>kolumna))?)?"
    r"|(?P<field>kolumna|wartosc|kwota)"
)
_NAMES: Final[Mapping[str, FieldName]] = {
    "zapisy": "zapisy",
    "przedzialy": "przedzialy",
    "wypelnienia": "wypelnienia",
    "kolumna": "kolumna",
    "wartosc": "wartosc",
    "kwota": "kwota",
}


@dataclass(frozen=True)
class UnknownCode:
    ...


def form_of(code: ActivityCode) -> contract.ActivityCodeForm:
    return contract.ActivityCodeForm(
        spellings=[shown_spelling(spelling) for spelling in code.spellings],
        column=_column_form(code.column),
        value=code.value,
        amount=code.amount,
        fills=[contract.FillForm(column=fill.column, colour=colour_name(fill.colour)) for fill in code.fills],
        counts_in_fault=code.counts_in_fault,
    )


def edited(
    codes: tuple[ActivityCode, ...], edit: contract.ActivityCodeEdit, used: frozenset[str]
) -> tuple[ActivityCode, ...] | FieldProblem | UnknownCode:
    match edit:
        case contract.AddActivityCode(code=form):
            built, places = _code(form, _new_id(codes, form, used))
            return _checked((*codes, built), codes, built, places)
        case contract.ChangeActivityCode(code_id=identifier, code=form):
            if identifier not in {code.id for code in codes}:
                return UnknownCode()
            built, places = _code(form, identifier)
            others = tuple(code for code in codes if code.id != identifier)
            return _checked(tuple(built if code.id == identifier else code for code in codes), others, built, places)
        case contract.RemoveActivityCode(code_id=identifier):
            if identifier not in {code.id for code in codes}:
                return UnknownCode()
            return tuple(code for code in codes if code.id != identifier)
        case _:
            assert_never(edit)


def dad_legend(
    codes: tuple[ActivityCode, ...], edit: contract.ActivityCodeEdit, used: frozenset[str]
) -> tuple[ActivityCode, ...] | FieldProblem:
    changed = edited(codes, edit, used)
    return codes if isinstance(changed, UnknownCode) else changed


def _checked(
    after: tuple[ActivityCode, ...], others: tuple[ActivityCode, ...], built: ActivityCode, places: tuple[int, ...]
) -> tuple[ActivityCode, ...] | FieldProblem:
    try:
        ActivityLegend((*others, built))
    except LegendRefused as refused:
        prefix = f"kody[{built.id}]."
        place = refused.problem.field.removeprefix(prefix) if refused.problem.field.startswith(prefix) else None
        return FieldProblem(None if place is None else _field(place, places), refused.problem.message)
    return after


def _field(place: str, places: tuple[int, ...]) -> FieldPath | None:
    found = _CODE_FIELD.fullmatch(place)
    if found is None:
        return None
    if found["field"] is not None:
        return FieldPath(_NAMES[found["field"]])
    listed: FieldName = _NAMES[found["list"]]
    if found["index"] is None:
        return FieldPath(listed, 0) if listed == "zapisy" else FieldPath(listed)
    index = int(found["index"])
    if listed == "zapisy":
        return FieldPath(listed, places[index])
    return FieldPath(listed, index) if found["range_field"] is None else FieldPath(listed, index, "kolumna")


def _code(form: contract.ActivityCodeForm, identifier: str) -> tuple[ActivityCode, tuple[int, ...]]:
    spellings: dict[str, int] = {}
    for index, typed in enumerate(form.spellings):
        spelling = _spelling(typed)
        if spelling:
            spellings.setdefault(spelling, index)
    column = _column(form.column)
    code = ActivityCode(
        identifier,
        tuple(spellings),
        column,
        1 if column is None else form.value,
        form.amount,
        tuple(CellFill(fill.column, _colour(fill.colour)) for fill in form.fills),
        form.counts_in_fault,
    )
    return code, tuple(spellings.values())


def _spelling(typed: str) -> str:
    return "".join(typed.split()).casefold().replace(SHOWN_NUMBER, NUMBER)


def _column(form: contract.FixedColumnForm | contract.RangesForm | None) -> ColumnChoice | None:
    match form:
        case None:
            return None
        case contract.FixedColumnForm(column=column):
            return FixedColumn(column)
        case contract.RangesForm(ranges=ranges):
            return ColumnByNumber(tuple(NumberRange(found.low, found.high, found.column) for found in ranges))
        case _:
            assert_never(form)


def _column_form(choice: ColumnChoice | None) -> contract.FixedColumnForm | contract.RangesForm | None:
    match choice:
        case None:
            return None
        case FixedColumn(column=column):
            return contract.FixedColumnForm(kind="fixed", column=column)
        case ColumnByNumber(ranges=ranges):
            return contract.RangesForm(
                kind="ranges", ranges=[contract.RangeForm(low=found.low, high=found.high, column=found.column) for found in ranges]
            )
        case _:
            assert_never(choice)


def colour_name(colour: FillColour) -> contract.FillColourName:
    return _COLOURS[colour]


def _colour(name: contract.FillColourName) -> FillColour:
    return next(colour for colour, shown in _COLOURS.items() if shown == name)


def _new_id(codes: tuple[ActivityCode, ...], form: contract.ActivityCodeForm, used: frozenset[str]) -> str:
    first = next((spelling for spelling in map(_spelling, form.spellings) if spelling), "")
    base = first.partition(NUMBER)[0] or "kod"
    taken = {code.id for code in codes} | used
    return next(
        candidate
        for candidate in (base, *(f"{base}-{number}" for number in range(2, len(taken) + 3)))
        if candidate not in taken
    )
