from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, cast
from xml.etree import ElementTree

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, from_excel
from openpyxl.workbook.properties import WorkbookProperties

from .workbook_files import is_blank
from .workbook_parts import MAIN, Relationship, SharedStrings, SheetCell, sheet_cells

__all__ = ["CellValues"]

_HEADER_ROW: Final = re.compile(rb'<row r="1"[^>]*?(?:/>|>.*?</row>)', re.S)
_TEXT: Final = re.compile(rb"<t(?:\s[^>]*)?>([^<]*)</t>")
# ZEWNĘTRZNE: Excel pokazuje liczbę w formacie daty jako datę tylko od 0 do 31.12.9999, a ujemną i późniejszą jako ####### (Microsoft Learn: Excel specifications and limits, Latest date allowed for calculation)
_LAST_MOMENT: Final = datetime(9999, 12, 31, 23, 59, 59, 999000)
_DAY: Final = timedelta(days=1)


@dataclass(frozen=True)
class CellValues:
    number_formats: tuple[int, ...]
    date_formats: frozenset[int]
    shared: SharedStrings
    epoch: datetime

    @classmethod
    def of(cls, parts: Mapping[str, bytes], workbook: str, rels: Mapping[str, Relationship]) -> CellValues:
        styles = next((rel.target for rel in rels.values() if rel.kind.endswith("/styles")), None)
        if styles is None:
            raise KeyError("styles")
        strings = next((rel.target for rel in rels.values() if rel.kind.endswith("/sharedStrings")), None)
        properties = ElementTree.fromstring(parts[workbook]).find(f"{MAIN}workbookPr")
        date1904 = properties is not None and cast(WorkbookProperties, WorkbookProperties.from_tree(cast(Any, properties))).date1904
        root = ElementTree.fromstring(parts[styles])
        codes = {int(item.get("numFmtId", "0")): item.get("formatCode", "") for item in root.iter(f"{MAIN}numFmt")}
        number_formats = tuple(int(xf.get("numFmtId", "0")) for xf in root.iterfind(f"{MAIN}cellXfs/{MAIN}xf"))
        return cls(
            number_formats=number_formats,
            date_formats=frozenset(
                number for number in number_formats if is_date_format(codes.get(number) or BUILTIN_FORMATS.get(number, ""))
            ),
            shared=SharedStrings(parts[strings] if strings else b"<sst/>"),
            epoch=MAC_EPOCH if date1904 else WINDOWS_EPOCH,
        )

    def value(self, cell: SheetCell) -> object:
        kind = cell.kind or b"n"
        if kind == b"inlineStr":
            text: object = html.unescape(b"".join(_TEXT.findall(cell.content or b"")).decode("utf-8"))
        else:
            found = cell.value
            if found is None:
                return None
            raw = found.decode("utf-8")
            if kind == b"s":
                text = self.shared[int(raw)]
            elif kind == b"n":
                number = float(raw)
                if self.number_formats[cell.style] in self.date_formats and 0 <= number <= (_LAST_MOMENT - self.epoch) / _DAY:
                    return from_excel(number, self.epoch)
                return number
            else:
                text = html.unescape(raw)
        return None if is_blank(text) else text

    def header(self, xml: bytes) -> list[object]:
        header_row = _HEADER_ROW.search(xml)
        if header_row is None:
            return []
        cells = sheet_cells(header_row.group(0))
        header: list[object] = [None] * max((cell.column for cell in cells), default=0)
        for cell in cells:
            header[cell.column - 1] = self.value(cell)
        return header
