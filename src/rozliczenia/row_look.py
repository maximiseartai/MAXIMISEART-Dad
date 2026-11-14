"""Wygląd Wiersza danych: jak wygląda każda komórka kolumn wyglądu zapisanego Wiersza danych.

Kolumny wyglądu to A:M Rozliczenia wewnętrznego oraz A:L Pliku zbiorczego i Rozliczenia
pracownika. Wygląd ich komórek nie zależy od tego, co zostało w komórce Wzorca:

- krój i rozmiar czcionki z komórki nagłówka tej kolumny we Wzorcu;
- kolor czcionki, pogrubienie, kursywa i wypełnienie z Wyróżnień;
- wyrównanie do lewej i do środka wysokości, zawijanie tylko tekstu z końcem linii;
- cienkie obramowanie z czterech stron w kolorze automatycznym;
- format liczby komórki źródłowej (Rejestru zleceń albo Pliku zbiorczego), a bez niej ogólny.

Wiersz danych nie ma zapisanej wysokości, więc Excel dopasowuje ją do treści. Wszystkie drogi
zapisu (openpyxl w ``template_file``, kopia Wzorca w ``template_copy``)
biorą wygląd komórki z ``RowLook.cell``, więc dają ten sam wynik.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass, field
from typing import Final, Protocol, cast

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles.alignment import Alignment
from openpyxl.styles.borders import Border, Side
from openpyxl.styles.cell_style import StyleArray
from openpyxl.styles.colors import Color
from openpyxl.styles.fills import Fill, PatternFill
from openpyxl.styles.fonts import Font
from openpyxl.workbook.workbook import Workbook

from .highlights import Highlights

GENERAL: Final = "General"
"""Format liczby komórki bez komórki źródłowej."""

_THIN: Final = Side(style="thin", color=Color(indexed=64))
"""Cienka linia w kolorze automatycznym (indeks 64)."""
BORDER: Final = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN, diagonal=Side())
"""Pusta przekątna jak w obramowaniu zapisanym przez Excel, żeby kopia znalazła je wśród obramowań Wzorca."""
_ALIGNED: Final = Alignment(horizontal="left", vertical="center")
_WRAPPED: Final = Alignment(horizontal="left", vertical="center", wrap_text=True)


@dataclass(frozen=True, eq=False)
class CellLook:
    """Wygląd jednej komórki. ``RowLook`` daje jeden obiekt na wygląd, więc porównanie idzie po tożsamości."""

    font: Font
    fill: Fill
    border: Border
    alignment: Alignment
    number_format: str

    _indexes: dict[int, tuple[Workbook, tuple[int, ...]]] = field(default_factory=dict, init=False, repr=False)
    """Indeksy wyglądu w stylach skoroszytu po ``id`` skoroszytu; wpis trzyma skoroszyt, więc ``id`` się nie powtórzy."""

    def apply(self, cell: Cell | MergedCell) -> None:
        """Nadaje wygląd komórce openpyxl; ochrona i styl nazwany komórki Wzorca zostają.

        openpyxl szuka każdego przypisanego stylu w stylach skoroszytu po skrócie całego obiektu, przy każdej
        komórce od nowa; indeksy wyglądu w danym skoroszycie są stałe, więc liczone są raz na skoroszyt.
        """

        workbook = cast(Workbook, cell.parent.parent)
        styled = cast(_Styled, cell)
        known = self._indexes.get(id(workbook))
        if known is None:
            cell.font = self.font
            cell.fill = self.fill
            cell.border = self.border
            cell.alignment = self.alignment
            cell.number_format = self.number_format
            style = cast(StyleArray, styled._style)
            indexes = (style.fontId, style.fillId, style.borderId, style.alignmentId, style.numFmtId)
            self._indexes[id(workbook)] = (workbook, indexes)
            return
        if styled._style is None:
            styled._style = StyleArray()
        style = styled._style
        style.fontId, style.fillId, style.borderId, style.alignmentId, style.numFmtId = known[1]


class _Styled(Protocol):
    """Komórka openpyxl z indeksami stylu, których openpyxl nie daje inaczej niż przez atrybut prywatny."""

    _style: StyleArray | None


class RowLook:
    """Wygląd Wierszy danych jednego pliku z Wzorca: krój i rozmiar czcionki nagłówka każdej kolumny wyglądu."""

    def __init__(self, header_fonts: Sequence[Font]) -> None:
        self._faces = tuple(
            Font(name=font.name, sz=font.sz, family=font.family, charset=font.charset, scheme=font.scheme)
            for font in header_fonts
        )
        self._looks: dict[tuple[int, Highlights, str, bool], CellLook] = {}

    @property
    def columns(self) -> int:
        """Liczba kolumn wyglądu od A."""

        return len(self._faces)

    def cell(self, column: int, highlights: Highlights, number_format: str, *, wrapped: bool) -> CellLook:
        """Wygląd komórki kolumny ``column`` (od 1) z Wyróżnieniami i formatem liczby komórki źródłowej."""

        key = (column, highlights, number_format, wrapped)
        look = self._looks.get(key)
        if look is None:
            look = self._looks[key] = CellLook(
                font=highlights.font_over(self._faces[column - 1]),
                fill=PatternFill() if highlights.fill is None else copy(highlights.fill),
                border=BORDER,
                alignment=_WRAPPED if wrapped else _ALIGNED,
                number_format=number_format,
            )
        return look


def wraps(value: object) -> bool:
    """Zawijany jest tylko tekst z końcem linii; ``\\r`` też nim jest, bo parser XML czyta je w komórce jako ``\\n``."""

    return isinstance(value, str) and ("\n" in value or "\r" in value)
