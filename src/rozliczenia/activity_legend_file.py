"""Plik Legendy czynności (ADR 0038) ↔ typy ``activity_legend``.

Dokument YAML ze ``schema_version: 1`` i listą ``kody``: ``legenda-czynnosci.yaml`` taty w ``config``.
``parse_activity_legend`` bierze dokument po ``yaml.safe_load`` i daje ``ActivityLegend`` albo pierwszy problem z
polem (``LegendProblem``): nieznany klucz, brak klucza, zły rodzaj wartości i każdy niezmiennik typu legendy.
``dump_activity_legend`` daje dokument, który ``parse_activity_legend`` czyta z powrotem w ten sam typ.

Wpis kodu: ``id``, ``zapisy``, co najwyżej jedno z ``kolumna`` (stała kolumna) i ``przedzialy`` (lista ``od``, ``do``,
``kolumna``), ``wartosc`` (Ilość usług przy kolumnie, bez pola 1), ``kwota`` (w ``AS``) i ``wypelnienia`` (lista
``kolumna``, ``kolor``).

``DEFAULT_ACTIVITY_LEGEND`` to Legenda czynności z Wydania: plik ``legenda_czynnosci_domyslna.yaml`` obok tego modułu,
czytany tym samym parserem.
"""

from __future__ import annotations

from importlib import resources
from typing import Final

import yaml

from .activity_legend import (
    ActivityCode,
    ActivityLegend,
    CellFill,
    ColumnByNumber,
    ColumnChoice,
    FillColour,
    FixedColumn,
    LegendProblem,
    LegendRefused,
    NumberRange,
)

SCHEMA_VERSION: Final = 1


class _Malformed(Exception):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(path, message)
        self.problem = LegendProblem(path, message)


def parse_activity_legend(document: object) -> ActivityLegend | LegendProblem:
    """Legenda czynności z dokumentu pliku ``legenda-czynnosci.yaml`` albo pierwszy problem."""

    try:
        entries = _mapping(document, "", required={"schema_version", "kody"})
        if entries["schema_version"] != SCHEMA_VERSION or isinstance(entries["schema_version"], bool):
            raise _Malformed("schema_version", f"Plik ma inną wersję zapisu niż {SCHEMA_VERSION}.")
        return ActivityLegend(tuple(_code(entry, f"kody[{index}]") for index, entry in enumerate(_list(entries["kody"], "kody"))))
    except _Malformed as malformed:
        return malformed.problem
    except LegendRefused as refused:
        return refused.problem


def dump_activity_legend(legend: ActivityLegend) -> dict[str, object]:
    return dump_codes(legend.codes)


def dump_codes(codes: tuple[ActivityCode, ...]) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "kody": [dump_code(code) for code in codes]}


def parse_code(entry: object) -> ActivityCode | LegendProblem:
    """Jeden kod w postaci wpisu pliku (``dump_code``) albo problem jego pól, bez niezmienników całej legendy."""

    try:
        return _code(entry, "kody[0]")
    except _Malformed as malformed:
        return malformed.problem


def _code(entry: object, path: str) -> ActivityCode:
    fields = _mapping(entry, path, required={"id", "zapisy"}, optional={"kolumna", "przedzialy", "wartosc", "kwota", "wypelnienia"})
    identifier = _text(fields["id"], f"{path}.id")
    path = f"kody[{identifier}]"
    if "kolumna" in fields and "przedzialy" in fields:
        raise _Malformed(f"{path}.przedzialy", "Kod ma stałą kolumnę albo przedziały, nie oba naraz.")
    column: ColumnChoice | None = None
    if "kolumna" in fields:
        column = FixedColumn(_text(fields["kolumna"], f"{path}.kolumna"))
    elif "przedzialy" in fields:
        where = f"{path}.przedzialy"
        column = ColumnByNumber(tuple(_range(found, f"{where}[{index}]") for index, found in enumerate(_list(fields["przedzialy"], where))))
    return ActivityCode(
        identifier,
        tuple(_text(spelling, f"{path}.zapisy") for spelling in _list(fields["zapisy"], f"{path}.zapisy")),
        column,
        _number(fields["wartosc"], f"{path}.wartosc") if "wartosc" in fields else 1,
        _number(fields["kwota"], f"{path}.kwota") if "kwota" in fields else None,
        tuple(_fill(fill, f"{path}.wypelnienia[{index}]") for index, fill in enumerate(_list(fields.get("wypelnienia", []), f"{path}.wypelnienia"))),
    )


def _range(entry: object, path: str) -> NumberRange:
    fields = _mapping(entry, path, required={"od", "do", "kolumna"})
    return NumberRange(_number(fields["od"], f"{path}.od"), _number(fields["do"], f"{path}.do"), _text(fields["kolumna"], f"{path}.kolumna"))


def _fill(entry: object, path: str) -> CellFill:
    fields = _mapping(entry, path, required={"kolumna", "kolor"})
    colour = next((member for member in FillColour if fields["kolor"] == member.value), None)
    if colour is None:
        raise _Malformed(f"{path}.kolor", f"Kolor musi być jednym z: {', '.join(member.value for member in FillColour)}.")
    return CellFill(_text(fields["kolumna"], f"{path}.kolumna"), colour)


def dump_code(code: ActivityCode) -> dict[str, object]:
    dumped: dict[str, object] = {"id": code.id, "zapisy": list(code.spellings)}
    match code.column:
        case FixedColumn(column=column):
            dumped["kolumna"] = column
        case ColumnByNumber(ranges=ranges):
            dumped["przedzialy"] = [{"od": found.low, "do": found.high, "kolumna": found.column} for found in ranges]
        case None:
            pass
    if code.value != 1:
        dumped["wartosc"] = code.value
    if code.amount is not None:
        dumped["kwota"] = code.amount
    if code.fills:
        dumped["wypelnienia"] = [{"kolumna": fill.column, "kolor": str(fill.colour)} for fill in code.fills]
    return dumped


def _mapping(entry: object, path: str, *, required: set[str], optional: frozenset[str] | set[str] = frozenset()) -> dict[str, object]:
    where = path or "plik"
    if not isinstance(entry, dict):
        raise _Malformed(where, "Tu powinny być pola „klucz: wartość”.")
    for key in entry:
        if key not in required and key not in optional:
            raise _Malformed(f"{path}.{key}" if path else str(key), f"Nieznane pole „{key}”.")
    for key in sorted(required):
        if key not in entry:
            raise _Malformed(f"{path}.{key}" if path else key, f"Brakuje pola „{key}”.")
    return {str(key): value for key, value in entry.items()}


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise _Malformed(path, "Tu powinna być lista.")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise _Malformed(path, "Tu powinien być tekst.")
    return value


def _number(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Malformed(path, "Tu powinna być liczba całkowita.")
    return value


def _default() -> ActivityLegend:
    text = resources.files(__package__).joinpath("legenda_czynnosci_domyslna.yaml").read_text(encoding="utf-8")
    legend = parse_activity_legend(yaml.safe_load(text))
    assert isinstance(legend, ActivityLegend), legend
    return legend


DEFAULT_ACTIVITY_LEGEND: Final = _default()
"""Legenda czynności z Wydania: mail taty z 15.11.2026 (ADR 0038)."""
