"""Wygląd komórek skoroszytu tak, jak go rozwiązuje openpyxl, do porównania skoroszytów z dwóch dróg zapisu."""

from __future__ import annotations

from collections.abc import Iterable
from copy import copy
from typing import NamedTuple, Protocol, cast

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles.cell_style import StyleArray


class Wyglad(NamedTuple):
    number_format: str
    font: object
    fill: object
    border: object
    alignment: object
    protection: object


class _Styled(Protocol):
    """Komórka openpyxl z indeksami stylu, których openpyxl nie daje inaczej niż przez atrybut prywatny."""

    _style: StyleArray | None


def wyglad(cell: Cell | MergedCell) -> Wyglad:
    return Wyglad(
        cell.number_format,
        copy(cell.font),
        copy(cell.fill),
        copy(cell.border),
        copy(cell.alignment),
        copy(cell.protection),
    )


def wyglady(cells: Iterable[Cell | MergedCell]) -> dict[str, Wyglad]:
    """Wygląd każdej komórki jednego skoroszytu po jej współrzędnej, liczony raz na każdy różny ``StyleArray``.

    openpyxl rozwiązuje wygląd tylko ze ``StyleArray`` komórki i tabel stylów jej skoroszytu, a kopia stylów każdej
    komórki osobno była większością czasu porównań wyglądu w testach. Pamięć żyje jedno wywołanie, bo numery w
    ``StyleArray`` znaczą co innego w innym skoroszycie.
    """

    per_style: dict[tuple[int, ...] | None, Wyglad] = {}
    looks: dict[str, Wyglad] = {}
    for cell in cells:
        style = cast(_Styled, cell)._style
        key = None if style is None else tuple(style)
        if key not in per_style:
            per_style[key] = wyglad(cell)
        looks[cell.coordinate] = per_style[key]
    return looks
