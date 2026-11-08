"""Pisarz dnia Uporządkowania INTERMAX: bajty Rejestru zleceń (INTERMAX) z uporządkowanym dniem i ich sprawdzenie.

Rejestr czyta ``register_file``; pisarz bierze z niego części paczki (``RegisterPackage``) i XML obszaru wklejania
(``PasteArea.sheet_xml``), a style zapisu (czcionki, wypełnienia, obramowanie) czyta sam, dopiero przy zapisie.

``ordered`` daje bajty INTERMAX z planem dnia (ADR 0019, wzorem kopii Wzorca z ADR 0008). Zmieniają się
tylko:

- w XML arkusza zleceń wiersze pod wierszem, pod którym staje dzień (``RawBlock.anchor``): wiersz zlecenia
  dostaje komórki Surowego zlecenia (w przesuniętym pierwszym wierszu o dwie kolumny w prawo) w kolumnach od A
  do ``UWAGI`` z wyglądem reszty INTERMAX i Kolorem operatora z planu dnia, a kolumny z aplikacji za ``UWAGI``
  znikają; zlecenie z Wpisem urządzenia i czynności INTERMAX ma w ``URZĄDZENIA`` i ``CZYNNOŚCI`` tekst Wpisu
  zamiast wartości z aplikacji; pusty wiersz między segmentami ma puste komórki od A do ``UWAGI`` z tym
  samym wyglądem; inny pusty wiersz, który był pusty, zostaje bajt w bajt, a wiersz, z którego zlecenie odeszło, i
  wiersz, którego nie było, są pustym wierszem taty; wygląd ``<row>`` (styl wiersza, wysokość) daje ``_RowLooks``;
- ``ref`` Hiperłączy z tych wierszy, które idą razem ze swoją komórką, i ``<dimension>``, gdy dzień sięga dalej;
- widok arkusza zleceń (``<sheetViews>``): karta zaznaczona, a górny wiersz widoku pod zamrożonym nagłówkiem i
  zaznaczenie na wierszu widoku z planu dnia (``DayPlan.view_row``);
- aktywna karta skoroszytu (``activeTab`` w ``xl/workbook.xml``) na arkuszu zleceń i znacznik zaznaczenia karty
  (``tabSelected``) zdjęty z pozostałych arkuszy;
- w ``xl/styles.xml`` czcionki, wypełnienia, obramowanie i style komórek dopisane na końcu swoich list.

Każda inna część pliku i każdy bajt nad tymi wierszami zostają. Arkusz, w którego zmienianych wierszach jest
formuła albo zakres (scalenie, formatowanie warunkowe, sprawdzanie poprawności, autofiltr, Hiperłącze na kilka
komórek albo za ``UWAGI``), to ``UnsupportedShape``. ``check`` porównuje odczytany zapis z oryginałem, a
komórki Wpisu z Wpisem z planu dnia; różnica to ``WriteMismatch``. Bajty zapisuje podmiana INTERMAX
(``intermax_replace``), która przed podmianą sprawdza nimi plik tymczasowy obok INTERMAX.
"""

from __future__ import annotations

import html
import re
import struct
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Final, cast
from xml.etree import ElementTree

from openpyxl.styles.borders import Border
from openpyxl.styles.colors import Color
from openpyxl.styles.fills import Fill, PatternFill
from openpyxl.styles.fonts import Font
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter, range_boundaries

from . import workbook_files
from .intermax_replace import WriteMismatch
from .raw_orders import DayPlan, IntermaxEntry, OperatorColor, OrderColumns, RawBlock
from .register_columns import ORDERED_FONT, ORDERED_SIZE, WORKER_SIZE
from .register_file import PasteArea, RegisterFile, RegisterPackage
from .row_look import BORDER
from .workbook_parts import (
    MAIN,
    STYLE_XF,
    IrregularSheetData,
    RowsFromBottom,
    SheetCell,
    UnsupportedShape,
    appended,
    row_attributes,
    row_tag,
    sheet_cells,
    style_list,
)

__all__ = ["check", "ordered"]

_DATE_FORMAT: Final = 22  # m/d/yy h:mm, format daty uporządkowanych dni
_BLACK: Final = "FF000000"

_FORMULA = re.compile(rb"<f[\s>/]")
_DIMENSION = re.compile(rb'<dimension ref="([^"]*)"\s*/>')
_HYPERLINK_REF = re.compile(rb'(<hyperlink\b[^>]*?\sref=")([^"]*)(")')
_HYPERLINKS = re.compile(rb"<hyperlinks>.*?</hyperlinks>", re.S)
_RANGES = re.compile(rb'\s(?:ref|sqref)="([^"]*)"')
_ROW_LOOK: Final = (b"s", b"customFormat", b"ht", b"customHeight", b"x14ac:dyDescent")
"""Atrybuty ``<row>``, które dają wiersz wygląd: styl wiersza i wysokość; ``x14ac`` deklaruje arkusz taty."""
_SHEET_VIEWS: Final = re.compile(rb"<sheetViews\b.*?</sheetViews>", re.S)
_SHEET_VIEW: Final = re.compile(rb"<sheetView\b([^>]*?)(?:/>|>.*?</sheetView>)", re.S)
_PANE: Final = re.compile(rb"<pane\b([^>]*?)\s*/>")
_TAB_SELECTED: Final = re.compile(rb'(<sheetView\b[^>]*?)\stabSelected="(?:1|true)"')
_WORKBOOK_VIEW: Final = re.compile(rb"<workbookView\b([^>]*?)(/?>)")
_COMPRESSION: Final = 1
"""Poziom zlib zapisu: arkusz zleceń taty (dziesiątki MB XML) zajmuje przy nim tyle co po zapisie w Excelu, a domyślny
poziom 6 kompresuje go kilka razy dłużej i był większością czasu Uporządkowania INTERMAX u taty."""
_DEFLATE_CHUNK: Final = 1 << 21
"""Bajty części, które jeden wątek kompresuje naraz: arkusz zleceń taty to kilkadziesiąt kawałków."""
_LOCAL, _CENTRAL, _END = 0x04034B50, 0x02014B50, 0x06054B50
"""Sygnatury nagłówka części, wpisu katalogu i końca katalogu zip (APPNOTE 4.3)."""
_VERSION: Final = 20
"""Wersja zip potrzebna do odczytu deflate, ta sama, którą wpisuje ``zipfile``."""
_UTF8_NAME: Final = 0x800
_FINAL_BLOCK: Final = b"\x03\x00"
"""Pusty blok końcowy deflate (stałe kody Huffmana), ten sam, który zlib daje na ``Z_FINISH`` po ``Z_SYNC_FLUSH``."""
_STYLE_LISTS: Final = (b"fonts", b"fills", b"borders", b"cellXfs")
"""Listy ``xl/styles.xml``, na których końcu zapis dopisuje wpisy."""


@dataclass(frozen=True)
class _WriteStyles:
    """Style komórek z ``xl/styles.xml``, do których zapis dopisuje wygląd dnia: formaty liczb stylów i listy czcionek,
    wypełnień, obramowań i stylów komórek."""

    number_formats: tuple[int, ...]
    fonts: tuple[Font, ...]
    fills: tuple[Fill, ...]
    borders: tuple[Border, ...]
    xfs: tuple[bytes, ...]

    @classmethod
    def of(cls, xml: bytes) -> _WriteStyles:
        root = ElementTree.fromstring(xml)
        return cls(
            number_formats=tuple(int(xf.get("numFmtId", "0")) for xf in root.iterfind(f"{MAIN}cellXfs/{MAIN}xf")),
            fonts=tuple(Font.from_tree(cast(Any, font)) for font in root.iterfind(f"{MAIN}fonts/{MAIN}font")),
            fills=tuple(cast(Fill, Fill.from_tree(cast(Any, fill))) for fill in root.iterfind(f"{MAIN}fills/{MAIN}fill")),
            borders=tuple(cast(Border, Border.from_tree(cast(Any, border))) for border in root.iterfind(f"{MAIN}borders/{MAIN}border")),
            xfs=tuple(STYLE_XF.findall(style_list(xml, b"cellXfs").group(2))),
        )


def ordered(register: RegisterFile, area: PasteArea, block: RawBlock, plan: DayPlan) -> bytes:
    """Bajty INTERMAX z uporządkowanym dniem w obszarze ``area``; ``UnsupportedShape``, gdy arkusza nie da się tak
    zapisać, a ``WorkbookError``, gdy stylów, które zapis rozszerza, nie da się odczytać."""

    package = register.package
    styles = package.parts[package.styles_part]
    with workbook_files.unreadable_as_error(register.path):
        write_styles = _WriteStyles.of(styles)
    looks = _Looks(write_styles, area.columns)
    sheet_xml = _ordered_sheet(area.sheet_xml, area.columns, block, plan, looks)
    parts = {**_tabs(package, area.part), area.part: sheet_xml, package.styles_part: looks.styles(styles)}
    return _archive([(info, parts.get(info.filename, package.parts[info.filename])) for info in package.infos])


def check(register: RegisterFile, written: bytes, area: PasteArea, block: RawBlock, plan: DayPlan) -> None:
    """``WriteMismatch``, gdy ``written`` różni się od INTERMAX czymś więcej niż dniem z ``plan`` w obszarze ``area``.

    Uszkodzenie ``written`` zgłasza jak odczyt skoroszytu (``workbook_files.unreadable_as_error``).
    """

    package = register.package
    with zipfile.ZipFile(BytesIO(written)) as archive:
        names = [info.filename for info in archive.infolist()]
        parts = {name: archive.read(name) for name in names}
    if names != [info.filename for info in package.infos]:
        raise WriteMismatch("części")
    tabs = _tabs(package, area.part)
    for name in names:
        if name not in (area.part, package.styles_part) and parts[name] != tabs.get(name, package.parts[name]):
            raise WriteMismatch(name)
    _check_styles(package.parts[package.styles_part], parts[package.styles_part])
    _check_sheet(area.sheet_xml, parts[area.part], area.columns, block, plan)


def _tabs(package: RegisterPackage, part: str) -> dict[str, bytes]:
    """Części, które zapis zmienia poza arkuszem zleceń: arkusz ``part`` jako aktywna karta i inne karty bez
    zaznaczenia.

    Znacznik zaznaczenia karty (``<sheetView tabSelected>``) może stać tylko w arkuszu.
    """

    parts = package.parts
    return {
        **{other: _TAB_SELECTED.sub(rb"\1", parts[other]) for other in package.sheet_parts if other != part},
        package.workbook_part: _with_active_tab(parts[package.workbook_part], package.sheet_parts.index(part)),
    }


def _with_active_tab(xml: bytes, index: int) -> bytes:
    """``xl/workbook.xml`` z aktywną kartą ``index`` (od 0) w każdym widoku skoroszytu."""

    tab = b' activeTab="%d"' % index

    def active(found: re.Match[bytes]) -> bytes:
        attributes, replaced = re.subn(rb'\sactiveTab="[^"]*"', tab, found.group(1))
        return b"<workbookView" + attributes + (b"" if replaced else tab) + found.group(2)

    return _WORKBOOK_VIEW.sub(active, xml)


def _with_view(head: bytes, row: int, column: int) -> bytes:
    """Nagłówek arkusza z kartą zaznaczoną, górnym wierszem widoku ``row`` i zaznaczeniem komórki ``column`` w nim.

    Zamrożony nagłówek (``<pane>``) zostaje, a zmienia się jego ``topLeftCell``; bez niego ``topLeftCell`` widoku.
    Widok zaczyna się od kolumny A (u taty nie ma zamrożonych kolumn) i ma potem tylko ``<pane>`` i jedno
    zaznaczenie, w aktywnym panelu.
    """

    cell = f"{get_column_letter(column)}{row}".encode("ascii")

    def top(attributes: bytes) -> bytes:
        return re.sub(rb'\stopLeftCell="[^"]*"', b"", attributes) + b' topLeftCell="A%d"' % row

    def view(found: re.Match[bytes]) -> bytes:
        attributes = re.sub(rb'\stabSelected="[^"]*"', b"", found.group(1))
        pane = _PANE.search(found.group(0))
        if pane is None:
            attributes, panes, name = top(attributes), b"", b""
        else:
            active = re.search(rb'\sactivePane="(\w+)"', pane.group(1))
            panes = b"<pane" + top(pane.group(1)) + b"/>"
            name = b' pane="%s"' % (active.group(1) if active else b"topLeft")
        selection = b'<selection%s activeCell="%s" sqref="%s"/>' % (name, cell, cell)
        return b'<sheetView tabSelected="1"' + attributes + b">" + panes + selection + b"</sheetView>"

    return _SHEET_VIEW.sub(view, head)


class _Looks:
    """Style wyglądu reszty INTERMAX dla kolumn zlecenia, dopisane do ``xl/styles.xml`` tylko raz każdy."""

    def __init__(self, styles: _WriteStyles, columns: OrderColumns) -> None:
        self._styles = styles
        self._columns = columns
        self._fonts: list[Font] = []
        self._fills: list[Fill] = []
        self._borders: list[Border] = []
        self._xfs: list[bytes] = []
        self._style_ids: dict[tuple[bool, int, str | None], int] = {}

    def style(self, column: int, number_format: int, fill: str | None) -> int:
        """Styl komórki kolumny zlecenia ``column``: Calibri 8 (WYKONAWCA pogrubiony Calibri 9), czarna, cienka ramka,
        do lewej i środka.

        ``fill``: wypełnienie RGB z Koloru operatora, jak to, które nadaje Excel; ``None``: bez wypełnienia.
        """

        if column == self._columns.date:
            number_format = _DATE_FORMAT
        worker = column == self._columns.worker
        key = (worker, number_format, fill)
        if key not in self._style_ids:
            size, bold = (WORKER_SIZE, True) if worker else (ORDERED_SIZE, None)
            font = _index(self._styles.fonts, self._fonts, Font(name=ORDERED_FONT, sz=size, b=bold, color=_BLACK, family=2))
            fill_id = 0 if fill is None else _index(self._styles.fills, self._fills, _solid(fill))
            border = _index(self._styles.borders, self._borders, BORDER)
            xf = (
                b'<xf numFmtId="%d" fontId="%d" fillId="%d" borderId="%d" xfId="0" applyNumberFormat="1" applyFont="1" '
                b'applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
                % (number_format, font, fill_id, border)
            )
            if xf in self._styles.xfs:
                self._style_ids[key] = self._styles.xfs.index(xf)
            else:
                self._xfs.append(xf)
                self._style_ids[key] = len(self._styles.xfs) + len(self._xfs) - 1
        return self._style_ids[key]

    def number_format(self, style: int) -> int:
        return self._styles.number_formats[style]

    def styles(self, xml: bytes) -> bytes:
        styles = self._styles
        xml = appended(xml, b"fonts", [ElementTree.tostring(font.to_tree()) for font in self._fonts], len(styles.fonts))
        xml = appended(xml, b"fills", [ElementTree.tostring(fill.to_tree()) for fill in self._fills], len(styles.fills))
        borders = [ElementTree.tostring(border.to_tree()) for border in self._borders]
        xml = appended(xml, b"borders", borders, len(styles.borders))
        return appended(xml, b"cellXfs", self._xfs, len(styles.xfs))


def _solid(rgb: str) -> PatternFill:
    """Pełne wypełnienie ``rgb`` tak, jak zapisuje je Excel taty (``bgColor`` 64)."""

    return PatternFill(patternType="solid", fgColor=Color(rgb=f"FF{rgb}"), bgColor=Color(indexed=64))


def _index(existing: Sequence[object], added: list[Any], item: object) -> int:
    if item in existing:
        return list(existing).index(item)
    if item not in added:
        added.append(item)
    return len(existing) + added.index(item)


@dataclass(frozen=True)
class _RowLooks:
    """Wygląd ``<row>`` wierszy nowego dnia z ostatniego uporządkowanego dnia taty; jedyne miejsce tej decyzji.

    Wiersz zlecenia i pusty wiersz między segmentami mają atrybuty ostatniego uporządkowanego wiersza
    (``RawBlock.last_ordered``), a inny pusty wiersz atrybuty pustego wiersza taty pod nim (``RawBlock.blank_row``),
    bez niego te same co wiersz zlecenia. Bez uporządkowanego wiersza nowe wiersze nie mają atrybutów wyglądu.
    """

    order: bytes
    blank: bytes

    @classmethod
    def of(cls, rows: RowsFromBottom, block: RawBlock) -> _RowLooks:
        def look(number: int) -> bytes:
            attributes = row_attributes(row_tag(rows.xml, rows.row(number)))
            return b"".join(b' %s="%s"' % (name, attributes[name]) for name in _ROW_LOOK if name in attributes)

        order = look(block.last_ordered) if block.last_ordered > 1 else b""
        return cls(order, order if block.blank_row is None else look(block.blank_row))


def _ordered_sheet(sheet: RowsFromBottom, columns: OrderColumns, block: RawBlock, plan: DayPlan, looks: _Looks) -> bytes:
    xml = sheet.xml
    region = sheet.above(block.anchor)
    by_number = {row.number: row for row in region}
    row_looks = _RowLooks.of(sheet, block)
    raw = {order.row for order in block.orders}
    tail_at = sheet.end + len(b"</sheetData>")
    _require_writable(xml[tail_at:], block.anchor)
    for number in raw:
        if _FORMULA.search(xml, by_number[number].start, by_number[number].end):
            raise UnsupportedShape("formuła")
    placed = {placement.row: placement for placement in plan.placements}
    separators = set(range(plan.placements[0].row, plan.placements[-1].row)) - set(placed)
    last = max([*placed, *(row.number for row in region)])
    rows: list[bytes] = []
    for number in range(block.anchor + 1, last + 1):
        placement = placed.get(number)
        if placement is not None:
            source = by_number[placement.order.row]
            rows.append(
                _order_row(
                    xml[source.start : source.end],
                    number,
                    placement.order.offset,
                    columns,
                    looks,
                    row_looks.order,
                    placement.color,
                    _entry_cells(placement.entry, columns),
                )
            )
        elif number in separators:
            rows.append(_order_row(b"", number, 0, columns, looks, row_looks.order, OperatorColor(), {}))
        elif number in by_number and number not in raw:
            rows.append(xml[by_number[number].start : by_number[number].end])
        else:
            rows.append(b'<row r="%d"%s/>' % (number, row_looks.blank))
    head = _with_view(_with_dimension(xml[: sheet.start], last, columns.last), plan.view_row, columns.first)
    above, below = memoryview(xml)[sheet.start : region[0].start], memoryview(xml)[region[-1].end : tail_at]
    return b"".join((head, above, *rows, below, _moved_hyperlinks(xml[tail_at:], columns, block, plan)))


def _order_row(
    row_xml: bytes,
    number: int,
    offset: int,
    columns: OrderColumns,
    looks: _Looks,
    row_look: bytes,
    color: OperatorColor,
    entry: Mapping[int, SheetCell],
) -> bytes:
    """Wiersz zlecenia ``number`` z komórek Surowego zlecenia od A do ``UWAGI``, w kolumnach ``entry`` z komórkami
    Wpisu, z Kolorem operatora ``color`` i wyglądem ``row_look``."""

    fills = {columns.activities: color.activities, columns.contract_number: color.contract_number, columns.devices: color.devices}
    written: dict[int, bytes] = {}
    for source in sheet_cells(row_xml):
        column = source.column + offset
        if column > columns.last:
            continue
        cell = entry.get(column, source)
        style = looks.style(column, looks.number_format(source.style), fills.get(column))
        written[column] = cell.xml(column, number, cell.unstyled + b' s="%d"' % style)
    for column in range(1, columns.last + 1):
        if column not in written:
            style = looks.style(column, 0, fills.get(column))
            written[column] = SheetCell(column, b"", None).xml(column, number, b' s="%d"' % style)
    cells = b"".join(written[column] for column in sorted(written))
    return b'<row r="%d"%s>' % (number, row_look) + cells + b"</row>"


def _entry_cells(entry: IntermaxEntry | None, columns: OrderColumns) -> dict[int, SheetCell]:
    """Komórki Wpisu urządzenia i czynności INTERMAX po kolumnie: tekst w ``URZĄDZENIA`` i ``CZYNNOŚCI``; bez Wpisu
    żadnych."""

    if entry is None:
        return {}
    return {
        column: SheetCell(column, b' t="inlineStr"', b"<is><t>%s</t></is>" % html.escape(text, quote=False).encode("utf-8"))
        for column, text in ((columns.devices, entry.devices), (columns.activities, entry.activities))
    }


def _with_dimension(head: bytes, last_row: int, last_column: int) -> bytes:
    """Nagłówek arkusza z ``<dimension>`` sięgającym co najmniej ``last_row`` i ``last_column``."""

    found = _DIMENSION.search(head)
    if found is None:
        return head
    corners = found.group(1).decode("ascii").split(":")
    column, row = coordinate_from_string(corners[-1])
    end = f"{get_column_letter(max(column_index_from_string(column), last_column))}{max(row, last_row)}"
    return head[: found.start(1)] + f"{corners[0]}:{end}".encode("ascii") + head[found.end(1) :]


def _require_writable(tail: bytes, anchor: int) -> None:
    """Zakresy za ``sheetData`` (poza Hiperłączami) nie sięgają wierszy pod ``anchor``."""

    for found in _RANGES.finditer(_HYPERLINKS.sub(b"", tail)):
        for reference in found.group(1).decode("ascii").split():
            _, _, _, max_row = range_boundaries(reference)
            if max_row is None or max_row > anchor:
                raise UnsupportedShape("zakres")


def _moves(plan: DayPlan) -> dict[int, tuple[int, int]]:
    """Wiersz Surowego zlecenia → (przesunięcie kolumn, docelowy wiersz)."""

    return {placement.order.row: (placement.order.offset, placement.row) for placement in plan.placements}


def _moved_hyperlinks(tail: bytes, columns: OrderColumns, block: RawBlock, plan: DayPlan) -> bytes:
    moves = _moves(plan)

    def moved(found: re.Match[bytes]) -> bytes:
        reference = found.group(2).decode("ascii")
        first = reference.split(":")[0]
        column, number = coordinate_from_string(first)
        if number <= block.anchor:
            return found.group(0)
        if reference != first or number not in moves:
            raise UnsupportedShape("Hiperłącze")
        offset, row = moves[number]
        moved_column = column_index_from_string(column) + offset
        if moved_column > columns.last:
            raise UnsupportedShape("Hiperłącze")
        return found.group(1) + f"{get_column_letter(moved_column)}{row}".encode("ascii") + found.group(3)

    return _HYPERLINK_REF.sub(moved, tail)


def _check_styles(original: bytes, written: bytes) -> None:
    """``WriteMismatch``, gdy arkusz stylów ``written`` to coś więcej niż ``original`` z wpisami na końcu list."""

    for tag in _STYLE_LISTS:
        try:
            before, after = style_list(original, tag), style_list(written, tag)
        except UnsupportedShape as error:
            raise WriteMismatch(str(error)) from error
        if not after.group(2).startswith(before.group(2)):
            raise WriteMismatch(f"style: {tag.decode('ascii')}")
        written = written[: after.start()] + before.group(0) + written[after.end() :]
    if written != original:
        raise WriteMismatch("style")


def _check_sheet(original: RowsFromBottom, written: bytes, columns: OrderColumns, block: RawBlock, plan: DayPlan) -> None:
    try:
        data = RowsFromBottom(written)
        written_region = data.above(block.anchor)
    except IrregularSheetData as error:
        raise WriteMismatch("arkusz") from error
    xml, region = original.xml, original.above(block.anchor)
    start = region[0].start if region else original.end
    new_start = written_region[0].start if written_region else data.end
    if _without_view(xml[: original.start]) != _without_view(written[: data.start]) or (
        xml[original.start : start] != written[data.start : new_start]
    ):
        raise WriteMismatch("wiersze nad dniem")
    tail, new_tail = xml[original.end :], written[data.end :]
    if _moved_hyperlinks(tail, columns, block, plan) != new_tail:
        raise WriteMismatch("ogon arkusza")
    rows = {row.number: row for row in written_region}
    sources = {row.number: row for row in region}
    raw = {order.row for order in block.orders}
    kept = {number: xml[row.start : row.end] for number, row in sources.items() if number not in raw}
    placed = {placement.row: placement for placement in plan.placements}
    for number, row in rows.items():
        cells = sheet_cells(written[row.start : row.end])
        valued = {cell.column: cell for cell in cells if cell.valued}
        placement = placed.get(number)
        if placement is None:
            if valued and written[row.start : row.end] != kept.get(number):
                raise WriteMismatch(f"wiersz {number}")
            continue
        source = sources[placement.order.row]
        offset = placement.order.offset
        moved = ((cell.column + offset, cell) for cell in sheet_cells(xml[source.start : source.end]))
        expected = {column: cell for column, cell in moved if column <= columns.last}
        expected.update(_entry_cells(placement.entry, columns))
        if {column for column, cell in expected.items() if cell.valued} != set(valued):
            raise WriteMismatch(f"wiersz {number}")
        found = {cell.column: cell for cell in cells}
        if any(column > columns.last for column in found):
            raise WriteMismatch(f"wiersz {number}")
        for column, cell in expected.items():
            new = found.get(column)
            if new is None or new.content != cell.content or new.kind != cell.kind:
                raise WriteMismatch(f"wiersz {number}")
    if set(placed) - set(rows):
        raise WriteMismatch("brak zlecenia")


def _without_view(head: bytes) -> bytes:
    """Nagłówek arkusza zleceń bez tego, co zmienia zapis: ``<dimension>`` i widoku arkusza.

    Oba stoją według schematu arkusza przed ``<sheetData>``, więc nagłówek to bajty przed nim, a nie dziesiątki MB
    wierszy nad dniem.
    """

    return _SHEET_VIEWS.sub(b"", _DIMENSION.sub(b"", head))


def _deflated(data: bytes, pool: ThreadPoolExecutor) -> bytes:
    """Surowy strumień deflate ``data``, kompresowany kawałkami naraz w wątkach (zlib zwalnia GIL), jak pigz.

    Każdy kawałek kończy się ``Z_SYNC_FLUSH`` (blok niekońcowy, do pełnego bajtu), a strumień pusty blok końcowy, więc
    złączone kawałki są jednym pełnym strumieniem. Odwołania nie sięgają przez granicę kawałka, co na arkuszu zleceń
    taty kosztuje 0,05% rozmiaru.
    """

    def chunk(start: int) -> bytes:
        compressor = zlib.compressobj(_COMPRESSION, zlib.DEFLATED, -zlib.MAX_WBITS)
        return compressor.compress(data[start : start + _DEFLATE_CHUNK]) + compressor.flush(zlib.Z_SYNC_FLUSH)

    return b"".join(pool.map(chunk, range(0, len(data), _DEFLATE_CHUNK))) + _FINAL_BLOCK


def _archive(entries: Sequence[tuple[zipfile.ZipInfo, bytes]]) -> bytes:
    """Zip z częściami ``entries`` po kolei, każdą w deflate: nazwa, data, system i atrybuty z ``ZipInfo`` oryginału,
    treść ``bytes``.

    ``zipfile`` kompresuje część tylko w jednym wątku, więc nagłówki pisze tu ``struct`` według APPNOTE (bez ZIP64:
    INTERMAX ma kilkanaście MB). Sumy CRC32 liczą te same wątki co kompresję, bo zlib na Windows liczy je bez SIMD.
    """

    out = bytearray()
    central = bytearray()
    with ThreadPoolExecutor() as pool:
        checksums = [pool.submit(zlib.crc32, data) for _, data in entries]
        streams = [_deflated(data, pool) for _, data in entries]
        crcs = [checksum.result() for checksum in checksums]
    for (info, data), stored, crc in zip(entries, streams, crcs, strict=True):
        name = info.filename.encode("utf-8")
        flags = 0 if name.isascii() else _UTF8_NAME
        year, month, day, hour, minute, second = info.date_time
        time_and_date = (hour << 11 | minute << 5 | second // 2, (year - 1980) << 9 | month << 5 | day)
        sizes = (crc, len(stored), len(data), len(name))
        offset = len(out)
        out += struct.pack("<IHHH2H3IHH", _LOCAL, _VERSION, flags, zipfile.ZIP_DEFLATED, *time_and_date, *sizes, 0)
        out += name + stored
        central += struct.pack(
            "<IBBHHH2H3IHHHHHII",
            _CENTRAL,
            info.create_version,
            info.create_system,
            _VERSION,
            flags,
            zipfile.ZIP_DEFLATED,
            *time_and_date,
            *sizes,
            0,
            0,
            0,
            0,
            info.external_attr,
            offset,
        )
        central += name
    end = struct.pack("<IHHHHIIH", _END, 0, 0, len(entries), len(entries), len(central), len(out), 0)
    return bytes(out + central + end)
