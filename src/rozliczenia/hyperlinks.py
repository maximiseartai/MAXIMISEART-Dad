"""Hiperłącza komórek: adres poza skoroszytem, który komórka otwiera po kliknięciu (GLOSSARY „Hiperłącze”).

Przygotowanie pliku zbiorczego przenosi je z komórek Rejestru zleceń do obu
plików okresu, a Przebieg rozliczeń z każdej komórki A:AT Wiersza danych Pliku
zbiorczego do tej samej komórki Rozliczenia pracownika. Każdy zapis zastępuje
nimi hiperłącza komórek Wzorca w zapisywanych wierszach.

``read_sheet_hyperlinks`` czyta Hiperłącza jednego arkusza z bajtów skoroszytu:
blok ``<hyperlinks>``, który w schemacie arkusza leży za ``</sheetData>``, i
relacje arkusza (``workbook_parts``), bez parsowania wierszy. Skoroszyt otwarty
przez openpyxl tylko do odczytu (Plik zbiorczy, Rejestr zleceń) hiperłączy nie daje.

Hiperłączem jest tylko odnośnik ``r:id`` do relacji ``…/hyperlink`` z
``TargetMode="External"``; jego adres to ``Target``, a przy ``location`` także
``#location``. Odnośnik do miejsca w tym samym skoroszycie (samo ``location``),
brak części relacji albo brak relacji o tym ``Id`` nie dają Hiperłącza. Zakres
``F18:F20`` daje Hiperłącze każdej komórce, a przy kilku odnośnikach do jednej
komórki wygrywa ostatni w pliku, jak w openpyxl. Komórka bez wartości nie niesie
Hiperłącza: openpyxl wpisałby adres jako jej wartość.

Adres to treść wiersza (np. numer sprawy klienta), więc ``repr`` go nie pokazuje.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final
from xml.etree import ElementTree

from openpyxl.utils.cell import range_boundaries

from .workbook_parts import MAIN, OFFICE_REL, WORKSHEET_ROOT, package_parts, relationships, sheet_part

_BLOCK: Final = re.compile(rb"<((?:[\w.-]+:)?)hyperlinks\b[^>]*?(/?)>")
_LAST_ROW: Final = 1_048_576
_LAST_COLUMN: Final = 16_384


@dataclass(frozen=True)
class Hyperlink:
    """Hiperłącze komórki: adres poza skoroszytem."""

    address: str = field(repr=False)


_NONE: Final[Mapping[int, Hyperlink]] = MappingProxyType({})


@dataclass(frozen=True)
class _Range:
    min_column: int
    min_row: int
    max_column: int
    max_row: int
    order: int
    link: Hyperlink


class SheetHyperlinks:
    """Hiperłącza jednego arkusza: pojedyncze komórki po wierszu, zakresy po granicach, z kolejnością w pliku."""

    def __init__(self, cells: dict[int, dict[int, tuple[int, Hyperlink]]], ranges: list[_Range]) -> None:
        self._cells = cells
        self._ranges = ranges

    def row(self, number: int, values: Sequence[object]) -> Mapping[int, Hyperlink]:
        """Hiperłącza wiersza ``number`` o wartościach ``values`` (od kolumny A): kolumna od 1 → Hiperłącze."""

        found = self._cells.get(number)
        if found is None and not self._ranges:
            return _NONE
        candidates = dict(found or {})
        for span in self._ranges:
            if span.min_row <= number <= span.max_row:
                for column in range(span.min_column, min(span.max_column, len(values)) + 1):
                    if column not in candidates or candidates[column][0] < span.order:
                        candidates[column] = (span.order, span.link)
        links = {
            column: link
            for column, (_, link) in candidates.items()
            if column <= len(values) and values[column - 1] not in (None, "")
        }
        return links or _NONE


NO_HYPERLINKS: Final = SheetHyperlinks({}, [])


def read_sheet_hyperlinks(content: bytes, sheet_title: str) -> SheetHyperlinks:
    """Hiperłącza arkusza ``sheet_title`` skoroszytu ``content`` (.xlsx).

    Zepsuty XML bloku albo relacji to ``ElementTree.ParseError``, brakująca część skoroszytu ``KeyError``, a zepsuty
    zip błąd ``zipfile``.
    """

    with package_parts(content) as parts:
        return _sheet_hyperlinks(parts, sheet_part(parts, sheet_title))


def _sheet_hyperlinks(parts: Mapping[str, bytes], part: str) -> SheetHyperlinks:
    xml = parts[part]
    root = WORKSHEET_ROOT.search(xml)
    block = _BLOCK.search(xml, max(xml.rfind(b"sheetData"), 0))
    if root is None or block is None or block.group(2):
        return NO_HYPERLINKS
    closing = b"</" + block.group(1) + b"hyperlinks>"
    end = xml.find(closing, block.end())
    if end < 0:
        raise ElementTree.ParseError("hyperlinks")
    document = root.group(0) + xml[block.start() : end + len(closing)] + b"</" + root.group(1) + b"worksheet>"
    elements = ElementTree.fromstring(document).iter(f"{MAIN}hyperlink")
    targets = _external_hyperlinks(parts, part)
    cells: dict[int, dict[int, tuple[int, Hyperlink]]] = {}
    ranges: list[_Range] = []
    for order, element in enumerate(elements):
        target = targets.get(element.get(f"{{{OFFICE_REL}}}id", ""))
        bounds = _bounds(element.get("ref", ""))
        if target is None or bounds is None:
            continue
        location = element.get("location")
        link = Hyperlink(target + f"#{location}" if location else target)
        min_column, min_row, max_column, max_row = bounds
        if (min_column, min_row) == (max_column, max_row):
            cells.setdefault(min_row, {})[min_column] = (order, link)
        else:
            ranges.append(_Range(min_column, min_row, max_column, max_row, order, link))
    return SheetHyperlinks(cells, ranges)


def _bounds(reference: str) -> tuple[int, int, int, int] | None:
    try:
        min_column, min_row, max_column, max_row = range_boundaries(reference)
    except (TypeError, ValueError):
        return None
    return min_column or 1, min_row or 1, max_column or _LAST_COLUMN, max_row or _LAST_ROW


def _external_hyperlinks(parts: Mapping[str, bytes], part: str) -> dict[str, str]:
    return {
        identifier: relationship.target
        for identifier, relationship in relationships(parts, part).items()
        if relationship.kind.endswith("/hyperlink") and relationship.external
    }
