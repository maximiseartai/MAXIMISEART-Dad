from __future__ import annotations

import html
import math
import posixpath
import re
import zipfile
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import cached_property, lru_cache
from io import BytesIO
from itertools import pairwise
from types import MappingProxyType
from typing import Final, NoReturn
from xml.etree import ElementTree
from xml.parsers import expat

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import column_index_from_string

SPREADSHEET_NS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MAIN: Final = f"{{{SPREADSHEET_NS}}}"
OFFICE_REL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

_WITHOUT_LEADING_R: Final = re.compile(rb'<(?:c|row)(?=[\s>/])(?! r=")')
_ROW_START_OR_IRREGULAR: Final = re.compile(rb'<(?:row r="(\d+)"|!|(?:c|row)(?=[\s>/])(?! r="))')
_IRREGULAR_IN_ROW: Final = re.compile(rb"-->|\]\]>|</?sheetData")
_WORKSHEET: Final = re.compile(rb"\s*(?:<\?xml[^>]*\?>\s*)?<worksheet[\s>]")
_SHARED_FORMULA_MASTER: Final = re.compile(rb'<f\b[^>]*\bt="shared"[^>]*(?<!/)>')
_TYPE: Final = re.compile(rb"""\st=["']([^"']*)["']""")
_VALUE: Final = re.compile(rb"<v\b[^>]*>([^<]*)</v>")
# ZEWNĘTRZNE: openpyxl daje datę tylko z liczby w komórce bez typu albo z t="n" ze stylem daty, a z t="d" tekst ISO zamieniony na datę (openpyxl/worksheet/_reader.py, WorkSheetParser.parse_cell)
_NUMBER_TYPES: Final = (None, b"n")
WORKSHEET_ROOT: Final = re.compile(rb"<((?:[\w.-]+:)?)worksheet\b[^>]*>")
STYLE_XF: Final = re.compile(rb"<xf\b[^>]*?(?:/>|>.*?</xf>)", re.S)


class UnsupportedShape(Exception):
    """Skoroszyt ma kształt, którego ręczny zapis XML nie przenosi; ``str`` mówi który, bez treści pliku."""


@contextmanager
def package_parts(content: bytes) -> Iterator[Mapping[str, bytes]]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        yield _ZipParts(archive)


@lru_cache(maxsize=1)
def unpacked(content: bytes) -> tuple[tuple[zipfile.ZipInfo, ...], Mapping[str, bytes]]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        infos = tuple(archive.infolist())
        return infos, MappingProxyType({info.filename: archive.read(info) for info in infos})


class _ZipParts(Mapping[str, bytes]):
    def __init__(self, archive: zipfile.ZipFile) -> None:
        self._archive = archive

    def __getitem__(self, name: str) -> bytes:
        return self._archive.read(name)

    def __contains__(self, name: object) -> bool:
        try:
            self._archive.getinfo(str(name))
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(self._archive.namelist())

    def __len__(self) -> int:
        return len(self._archive.infolist())


@dataclass(frozen=True)
class Relationship:
    kind: str
    target: str
    external: bool


def relationships_part(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", f"{name}.rels")


def relationships(parts: Mapping[str, bytes], part: str) -> dict[str, Relationship]:
    rels = relationships_part(part)
    if rels not in parts:
        return {}
    folder = posixpath.dirname(part)
    found: dict[str, Relationship] = {}
    for relationship in ElementTree.fromstring(parts[rels]).iter(PACKAGE_REL):
        target = relationship.get("Target", "")
        external = relationship.get("TargetMode") == "External"
        if not external:
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        found[relationship.get("Id", "")] = Relationship(relationship.get("Type", ""), target, external)
    return found


def office_document(parts: Mapping[str, bytes]) -> str | None:
    for relationship in ElementTree.fromstring(parts["_rels/.rels"]).iter(PACKAGE_REL):
        if relationship.get("Type", "").endswith("/officeDocument"):
            return relationship.get("Target", "").lstrip("/")
    return None


def sheet_part(parts: Mapping[str, bytes], title: str) -> str:
    workbook = office_document(parts) or ""
    sheets = ElementTree.fromstring(parts[workbook]).iter(f"{MAIN}sheet")
    identifier = next((sheet.get(f"{{{OFFICE_REL}}}id", "") for sheet in sheets if sheet.get("name") == title), "")
    return relationships(parts, workbook)[identifier].target


@dataclass(frozen=True)
class ActiveSheet:
    part: str
    title: str
    position: int
    visible: bool
    worksheet: bool


def active_sheet(parts: Mapping[str, bytes], workbook: str) -> ActiveSheet:
    root = ElementTree.fromstring(parts[workbook])
    rels = relationships(parts, workbook)
    loaded: list[ActiveSheet] = []
    for position, sheet in enumerate(root.iterfind(f"{MAIN}sheets/{MAIN}sheet")):
        identifier = sheet.get(f"{{{OFFICE_REL}}}id")
        if not identifier:
            continue
        relationship = rels.get(identifier)
        if relationship is None:
            raise UnsupportedShape("aktywna karta")
        if relationship.target in parts:
            visible = sheet.get("state", "visible") == "visible"
            worksheet = relationship.kind.endswith("/worksheet")
            loaded.append(ActiveSheet(relationship.target, sheet.get("name", ""), position, visible, worksheet))
    view = root.find(f"{MAIN}bookViews/{MAIN}workbookView")
    try:
        return loaded[int(view.get("activeTab", "0")) if view is not None else 0]
    except (ValueError, IndexError):
        raise UnsupportedShape("aktywna karta") from None


def style_list(xml: bytes, tag: bytes) -> re.Match[bytes]:
    found = re.search(rb"<" + tag + rb"\b([^>]*)>(.*?)</" + tag + rb">", xml, re.S)
    if found is None:
        raise UnsupportedShape(f"style: {tag.decode('ascii')}")
    return found


def appended(xml: bytes, tag: bytes, entries: Sequence[bytes], existing: int) -> bytes:
    if not entries:
        return xml
    block = style_list(xml, tag)
    attributes = re.sub(rb'\scount="\d+"', b"", block.group(1))
    opening = b"<" + tag + b' count="%d"' % (existing + len(entries)) + attributes + b">"
    return xml[: block.start()] + opening + block.group(2) + b"".join(entries) + b"</" + tag + b">" + xml[block.end() :]


def with_style_attribute(xf: bytes, name: bytes, value: int, apply: bytes) -> bytes:
    tag_end = xf.index(b">")
    tag = re.sub(rb"\s" + name + rb'="\d+"', b"", xf[:tag_end])
    tag = re.sub(rb"\s" + apply + rb'="\w+"', b"", tag).rstrip(b"/ ")
    closing = b"/>" if xf[tag_end - 1 : tag_end] == b"/" else xf[tag_end:]
    return tag[:3] + b" " + name + b'="%d"' % value + tag[3:] + b" " + apply + b'="1"' + closing


class IrregularSheetData(Exception):
    ...


@dataclass(frozen=True)
class SheetRow:
    number: int
    start: int
    end: int


@dataclass(frozen=True)
class SheetData:
    start: int
    end: int
    rows: list[SheetRow]

    @classmethod
    def of(cls, xml: bytes) -> SheetData:
        start, end = _sheet_data_bounds(xml)
        return cls(start, end, _sheet_rows(xml, start, end))

    @cached_property
    def _starts(self) -> list[int]:
        return [row.start for row in self.rows]

    def row_index(self, position: int) -> int:
        return bisect_right(self._starts, position) - 1


def _sheet_data_bounds(xml: bytes) -> tuple[int, int]:
    start = xml.find(b"<sheetData>")
    end = xml.find(b"</sheetData>")
    if start < 0 or end < start or xml.count(b"<sheetData") != 1:
        raise IrregularSheetData("sheetData")
    return start + len(b"<sheetData>"), end


class RowsFromBottom:
    def __init__(self, xml: bytes) -> None:
        start, end = xml.find(b"<sheetData>"), xml.rfind(b"</sheetData>")
        if start < 0 or end < start:
            raise IrregularSheetData("sheetData")
        self.xml = xml
        self.start, self.end = start + len(b"<sheetData>"), end
        self._rows: list[SheetRow] = []
        self._divided_from = self.end

    def __iter__(self) -> Iterator[SheetRow]:
        index = 0
        while index < len(self._rows) or self._divide_more():
            yield self._rows[index]
            index += 1

    def above(self, number: int) -> list[SheetRow]:
        rows: list[SheetRow] = []
        for row in self:
            if row.number <= number:
                break
            rows.append(row)
        return rows[::-1]

    def row(self, number: int) -> SheetRow:
        for row in self:
            if row.number == number:
                return row
            if row.number < number:
                break
        raise KeyError(number)

    def _divide_more(self) -> bool:
        end = self._divided_from
        if end <= self.start:
            return False
        begin = max(self.start, self.xml.rfind(b"<row", self.start, end))
        if _IRREGULAR_IN_ROW.search(self.xml, begin, end):
            raise IrregularSheetData("komentarz, CDATA albo drugi sheetData")
        rows = _sheet_rows(self.xml, begin, end)
        if self._rows and rows and rows[-1].number >= self._rows[-1].number:
            raise IrregularSheetData("kolejność wierszy")
        self._rows.extend(reversed(rows))
        self._divided_from = begin
        return bool(rows)


def _sheet_rows(xml: bytes, start: int, end: int) -> list[SheetRow]:
    rows: list[SheetRow] = []
    for match in _ROW_START_OR_IRREGULAR.finditer(xml, start, end):
        if match.group(1) is None:
            _raise_irregular(xml, start, end)
        number = int(match.group(1))
        if rows and number <= rows[-1].number:
            _raise_irregular(xml, start, end, "kolejność wierszy")
        tag_end = xml.index(b">", match.end())
        row_end = tag_end + 1 if xml[tag_end - 1 : tag_end] == b"/" else xml.index(b"</row>", tag_end) + len(b"</row>")
        rows.append(SheetRow(number, match.start(), row_end))
    return rows


def _raise_irregular(xml: bytes, start: int, end: int, otherwise: str = "") -> NoReturn:
    if xml.find(b"<!", start, end) >= 0:
        raise IrregularSheetData("komentarz albo CDATA")
    if _WITHOUT_LEADING_R.search(xml, start, end):
        raise IrregularSheetData("r")
    raise IrregularSheetData(otherwise)


_XML_CELL: Final = re.compile(rb'<c r="([A-Z]{1,3})(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_XML_CELL_STYLE: Final = re.compile(rb'\ss="(\d+)"')
_XML_CELL_TYPE: Final = re.compile(rb'\st="(\w+)"')
_XML_CELL_VALUE: Final = re.compile(rb"<v(?:\s[^>]*)?>([^<]*)</v>")
_ROW_ATTRIBUTE: Final = re.compile(rb'\s([\w:]+)="([^"]*)"')


@dataclass(frozen=True)
class SheetCell:
    column: int
    attributes: bytes
    content: bytes | None

    @property
    def style(self) -> int:
        found = _XML_CELL_STYLE.search(self.attributes)
        return int(found.group(1)) if found else 0

    @property
    def kind(self) -> bytes | None:
        found = _XML_CELL_TYPE.search(self.attributes)
        return found.group(1) if found else None

    @property
    def unstyled(self) -> bytes:
        return _XML_CELL_STYLE.sub(b"", self.attributes)

    @property
    def value(self) -> bytes | None:
        found = _XML_CELL_VALUE.search(self.content or b"")
        return None if found is None else found.group(1)

    @property
    def valued(self) -> bool:
        return self.value is not None or b"<is>" in (self.content or b"")

    def xml(self, column: int, row: int, attributes: bytes | None = None) -> bytes:
        reference = get_column_letter(column).encode("ascii") + b"%d" % row
        attributes = self.attributes if attributes is None else attributes
        if self.content is None:
            return b'<c r="' + reference + b'"' + attributes + b"/>"
        return b'<c r="' + reference + b'"' + attributes + b">" + self.content + b"</c>"


def sheet_cells(row_xml: bytes) -> list[SheetCell]:
    return [
        SheetCell(column_index_from_string(found.group(1).decode("ascii")), found.group(3), found.group(4))
        for found in _XML_CELL.finditer(row_xml)
    ]


def row_tag(xml: bytes, row: SheetRow) -> bytes:
    return xml[row.start : xml.index(b">", row.start) + 1]


_SHARED_TEXT: Final = re.compile(rb"<t(?:\s[^>]*)?>([^<]*)</t>")
_PHONETIC: Final = re.compile(rb"<rPh\b.*?</rPh>", re.S)


class SharedStrings:
    def __init__(self, xml: bytes) -> None:
        self._xml = xml
        try:
            self._items = shared_string_spans(xml)
        except UnsupportedShape as error:
            raise ValueError(str(error)) from error
        self._texts: dict[int, str] = {}

    def __getitem__(self, index: int) -> str:
        if index not in self._texts:
            item = _PHONETIC.sub(b"", self._xml[slice(*self._items[index])])
            self._texts[index] = html.unescape(b"".join(_SHARED_TEXT.findall(item)).decode("utf-8"))
        return self._texts[index]


def column_texts(xml: bytes, column: int, first_row: int, shared: SharedStrings) -> Iterator[tuple[int, str]]:
    start, end = _sheet_data_bounds(xml)
    if xml.find(b"<!", start, end) >= 0:
        raise IrregularSheetData("komentarz albo CDATA")
    if _WITHOUT_LEADING_R.search(xml, start, end):
        raise IrregularSheetData("r")
    cell = re.compile(rb'<c r="' + get_column_letter(column).encode("ascii") + rb'(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
    for found in cell.finditer(xml, start, end):
        row = int(found.group(1))
        if row < first_row:
            continue
        text = _cell_text(SheetCell(column, found.group(2), found.group(3)), shared)
        if text is not None:
            yield row, text


def _cell_text(cell: SheetCell, shared: SharedStrings) -> str | None:
    if cell.kind == b"inlineStr":
        return html.unescape(b"".join(_SHARED_TEXT.findall(cell.content or b"")).decode("utf-8"))
    raw = cell.value
    if raw is None:
        return None
    if cell.kind == b"s":
        return shared[int(raw)]
    return html.unescape(raw.decode("utf-8"))


def row_attributes(tag: bytes) -> dict[bytes, bytes]:
    return dict(_ROW_ATTRIBUTE.findall(tag))


_Narrow = Callable[[bytes], bytes]
_Choose = Callable[[str, bytes], _Narrow | None]


def rows_with_input(content: bytes, input_columns: int) -> bytes:
    letters = b"|".join(get_column_letter(column).encode("ascii") for column in range(1, input_columns + 1))
    with_input = re.compile(rb'<c r="(?:' + letters + rb')[0-9]+"[^>]*(?<!/)>')

    def narrow(xml: bytes) -> bytes:
        sheet = SheetData.of(xml)
        cells = with_input.finditer(xml, sheet.start, sheet.end)
        return _with_rows(xml, sheet, {sheet.row_index(cell.start()) for cell in cells})

    def every_worksheet(_: Mapping[str, bytes]) -> _Choose:
        return lambda _, xml: narrow if _WORKSHEET.match(xml) else None

    return _rewritten(content, every_worksheet)


def rows_dated_between(
    content: bytes, date_columns: Mapping[str, int], low: float, high: float
) -> tuple[bytes, dict[str, range]]:
    ranges: dict[str, range] = {}
    days = b"|".join(b"%d" % day for day in range(math.floor(low) - 1, math.floor(high) + 1))
    outside = rb"""(?:(?!\st=["'](?!n["']))[^>])*><v>(?!0*(?:""" + days + rb""")(?:\.\d+)?</v>)\d+(?:\.\d+)?</v>"""

    def dated(title: str, column: int) -> _Narrow:
        letter = get_column_letter(column).encode("ascii")
        date_cell = re.compile(rb'<c r="' + letter + rb'(\d+)"(?!' + outside + rb")([^>]*)(?<!/)>(.*?)</c>", re.DOTALL)

        def narrow(xml: bytes) -> bytes:
            start, end = _sheet_data_bounds(xml)
            dated = [
                (int(found.group(1)), found.start())
                for found in date_cell.finditer(xml, start, end)
                if _is_number_between(found.group(2), found.group(3), low, high)
            ]
            rows = _first_row(xml, start, end)
            kept = range(0)
            if dated:
                begin, finish = _window(xml, start, end, dated)
                rows |= {(begin, finish)} | _master_rows(xml, start, begin) | _master_rows(xml, finish, end)
                kept = range(min(dated)[0], max(dated)[0] + 1)
            ranges[title] = kept
            return b"".join([xml[:start], *(xml[begin:finish] for begin, finish in sorted(rows)), xml[end:]])

        return narrow

    def by_title(parts: Mapping[str, bytes]) -> _Choose:
        narrowing = {sheet_part(parts, title): dated(title, column) for title, column in date_columns.items()}
        return lambda name, _: narrowing.get(name)

    return _rewritten(content, by_title, used_strings_only=True), ranges


def _rewritten(content: bytes, choose: Callable[[Mapping[str, bytes]], _Choose], *, used_strings_only: bool = False) -> bytes:
    reduced = BytesIO()
    infos, unpacked_parts = unpacked(content)
    with zipfile.ZipFile(reduced, "w", zipfile.ZIP_STORED) as target:
        narrowing = choose(unpacked_parts)
        parts: list[tuple[str, bytes]] = []
        for info in infos:
            data = unpacked_parts[info.filename]
            narrow = narrowing(info.filename, data)
            if narrow is not None:
                with suppress(IrregularSheetData):
                    data = narrow(data)
            parts.append((info.filename, data))
        replaced = _used_strings_only(dict(parts)) if used_strings_only else {}
        for name, data in parts:
            target.writestr(name, replaced.get(name, data))
    return reduced.getvalue()


def _window(xml: bytes, start: int, end: int, dated: Sequence[tuple[int, int]]) -> tuple[int, int]:
    begin = xml.rfind(b"<row", start, min(dated)[1])
    finish = xml.find(b"</row>", max(dated)[1], end)
    if begin < 0 or finish < 0 or _IRREGULAR_IN_ROW.search(xml, begin, finish):
        raise IrregularSheetData("komentarz, CDATA albo drugi sheetData")
    return begin, finish + len(b"</row>")


def _first_row(xml: bytes, start: int, end: int) -> set[tuple[int, int]]:
    begin = xml.find(b"<row", start, end)
    if begin < 0 or not xml.startswith(b'<row r="1"', begin):
        return set()
    tag_end = xml.index(b">", begin)
    finish = tag_end + 1 if xml[tag_end - 1 : tag_end] == b"/" else xml.index(b"</row>", tag_end) + len(b"</row>")
    return {(begin, finish)}


def _master_rows(xml: bytes, start: int, end: int) -> set[tuple[int, int]]:
    rows: set[tuple[int, int]] = set()
    for found in _SHARED_FORMULA_MASTER.finditer(xml, start, end):
        begin = xml.rfind(b"<row", start, found.start())
        if begin >= 0:
            rows.add((begin, xml.index(b"</row>", found.end(), end) + len(b"</row>")))
    return rows


def _with_rows(xml: bytes, sheet: SheetData, kept: Iterable[int]) -> bytes:
    masters = (sheet.row_index(found.start()) for found in _SHARED_FORMULA_MASTER.finditer(xml, sheet.start, sheet.end))
    indices = sorted({*kept, *masters} - {-1})
    expat.ParserCreate().Parse(xml, True)
    rows = sheet.rows
    return b"".join([xml[: sheet.start], *(xml[rows[index].start : rows[index].end] for index in indices), xml[sheet.end :]])


def _is_number_between(attributes: bytes, content: bytes, low: float, high: float) -> bool:
    found_type = _TYPE.search(attributes)
    cell_type = found_type.group(1) if found_type else None
    if cell_type == b"d":
        raise IrregularSheetData("data tekstem ISO")
    if cell_type not in _NUMBER_TYPES:
        return False
    value = _VALUE.search(content)
    if value is None:
        return False
    try:
        number = float(value.group(1))
    except ValueError:
        raise IrregularSheetData("wartość liczbowa") from None
    return low <= number <= high


_SHARED_STRINGS_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
_CONTENT_TYPE_OVERRIDE: Final = "{http://schemas.openxmlformats.org/package/2006/content-types}Override"
_STRINGS_ROOT: Final = re.compile(
    rb"(?:<\?xml[^>]*\?>)?\s*<(?:[\w.-]+:)?[\w.-]+((?:\s+[\w.:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>\s*"
)
_MAIN_DEFAULT: Final = re.compile(rb"""\sxmlns\s*=\s*(["'])""" + re.escape(SPREADSHEET_NS.encode("ascii")) + rb"\1")
_STRING_ITEMS: Final = re.compile(
    rb"(?:<si(?:\s+(?!xmlns)[\w.:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*+\s*+"
    rb"(?:/>|>[^<]*+(?:<(?![!?]|/?(?:[\w.-]+:)?si)[^<]*+)*+</si\s*+>)\s*+)*+"
)
"""Kwantyfikatory bez cofania, bo odrzucenie tabeli z dziesiątkami tysięcy tekstów z cofaniem trwałoby długo."""
_STRING_START: Final = re.compile(rb"<si")
_CELL: Final = f"{SPREADSHEET_NS} c"
_CELL_VALUE: Final = f"{SPREADSHEET_NS} v"


def _used_strings_only(parts: Mapping[str, bytes]) -> dict[str, bytes]:
    strings = next(
        (
            override.get("PartName", "")[1:]
            for override in ElementTree.fromstring(parts["[Content_Types].xml"]).iter(_CONTENT_TYPE_OVERRIDE)
            if override.get("ContentType") == _SHARED_STRINGS_TYPE
        ),
        "",
    )
    if strings not in parts:
        return {}
    table = parts[strings]
    try:
        items = shared_string_spans(table)
        cells = {part: _shared_cells(parts[part]) for part in _sheet_parts(parts)}
    except (UnsupportedShape, expat.ExpatError):
        return {}
    used = sorted({index for found in cells.values() for _, _, index in found})
    if not items or (used and used[-1] >= len(items)):
        return {}
    renumbered = {index: number for number, index in enumerate(used)}
    kept = (table[slice(*items[index])] for index in used)
    replaced = {strings: b"".join([table[: items[0][0]], *kept, table[items[-1][1] :]])}
    for part, found in cells.items():
        xml = parts[part]
        pieces: list[bytes] = []
        last = 0
        for start, end, index in found:
            pieces += [xml[last:start], b"%d" % renumbered[index]]
            last = end
        replaced[part] = b"".join([*pieces, xml[last:]])
    return replaced


@lru_cache(maxsize=1)
def shared_string_spans(table: bytes) -> tuple[tuple[int, int], ...]:
    """W poprawnym XML bez komentarzy, CDATA i instrukcji przetwarzania każdy ``<`` zaczyna znacznik, więc każdy ``<si>``
    jest wtedy dzieckiem korzenia z przestrzeni nazw arkusza, tak jak liczy go openpyxl, a każde ``<si`` w treści
    korzenia zaczyna tekst."""

    expat.ParserCreate(namespace_separator=" ").Parse(table, True)
    root = _STRINGS_ROOT.match(table)
    if root is not None and root.group(2):
        return ()
    end = table.rfind(b"</")
    if root is None or not _MAIN_DEFAULT.search(root.group(1)) or not _STRING_ITEMS.fullmatch(table, root.end(), end):
        raise UnsupportedShape("teksty wspólne")
    starts = [found.start() for found in _STRING_START.finditer(table, root.end(), end)]
    return tuple(pairwise([*starts, end]))


def _sheet_parts(parts: Mapping[str, bytes]) -> set[str]:
    workbook = office_document(parts) or ""
    rels = relationships(parts, workbook)
    sheets = ElementTree.fromstring(parts[workbook]).iter(f"{MAIN}sheet")
    return {rel.target for sheet in sheets if (rel := rels.get(sheet.get(f"{{{OFFICE_REL}}}id", ""))) is not None}


def _shared_cells(xml: bytes) -> list[tuple[int, int, int]]:
    """openpyxl czyta numer z ``<v>`` dziecka komórki; ``<v>`` głębiej dostaje nowy numer tak samo, więc nie zmienia
    tego, co openpyxl czyta. Tekst ``<v>`` zaczyna się za pierwszym ``>`` za ``<v``, a gdyby ``>`` stał w atrybucie,
    tekst ma znaki spoza cyfr."""

    parser = expat.ParserCreate(namespace_separator=" ")
    cells: list[tuple[int, int, int]] = []
    depth = value_depth = value_start = 0
    shared = False

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal depth, shared, value_depth, value_start
        depth += 1
        if name == _CELL:
            shared = attributes.get("t") == "s"
        elif name == _CELL_VALUE and shared:
            value_depth, value_start = depth, xml.index(b">", parser.CurrentByteIndex) + 1

    def end(_: str) -> None:
        nonlocal depth, value_depth
        if value_depth == depth:
            digits = xml[value_start : parser.CurrentByteIndex]
            if not digits.isdigit():
                raise UnsupportedShape("komórka tekstu wspólnego")
            cells.append((value_start, parser.CurrentByteIndex, int(digits)))
            value_depth = 0
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(xml, True)
    return cells
