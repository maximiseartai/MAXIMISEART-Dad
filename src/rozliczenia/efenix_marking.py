"""Znaczniki efenix w Pliku zbiorczym: jedyny zapis, którym Wycena w efenix zmienia Plik zbiorczy.

Jedyną operacją jest ``mark_ready()``. Dostaje bajty Pliku zbiorczego z odczytu zakresu, kolumnę ``ADRES`` i numery
wierszy gotowych zleceń. Komórka ``ADRES`` każdego z tych wierszy dostaje styl, który od jej dotychczasowego różni się
tylko wypełnieniem: jednolitym w kolorze ``efenix_mark.MARK_RGB``. Zmieniają się tylko:

- atrybut ``s`` tych komórek w XML arkusza, który czyta odczyt zakresu (aktywnego, ``activeTab``);
- w ``xl/styles.xml`` listy ``fills`` i ``cellXfs``: wypełnienie Znacznika i każdy nowy styl komórki (kopia
  dotychczasowego z innym ``fillId`` i ``applyFill="1"``) stoją na ich końcu. Wypełnienie Znacznika (``is_mark``) i styl,
  które plik już ma, np. z poprzedniego przebiegu, zapis bierze zamiast nowych.

Każda inna część zip zostaje bajt w bajt, bez openpyxl: wartości policzone przez Excel, ``xl/externalLinks/*``,
``xl/calcChain.xml``, szerokości kolumn i czcionka komórki ``ADRES``. Komórka, która ma już Znacznik, zostaje bez zmian, a
gdy żadna się nie zmienia, plik nie jest zapisywany.

Plik zbiorczy zmienia się tylko wtedy, gdy tuż przed zapisem są na dysku dalej bajty z odczytu zakresu i nie ma przy nim
pliku blokady Excela, przez atomową podmianę (``workbook_save.write_atomically``). Gdy się nie zmienia, ``mark_ready``
oddaje fakt ``Refusal``, a plik i jego folder są takie, jak były. Arkusz spoza kształtu ``SheetData``, gotowy wiersz bez
komórki ``ADRES`` i styl, którego zapis nie umie skopiować, to ``UnsupportedShape``: Excel takiego pliku nie zapisuje,
więc to błąd w kodzie, nie stan pliku taty.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Collection
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Final, cast
from xml.etree import ElementTree
from xml.parsers import expat

from openpyxl.styles.fills import Fill

from . import workbook_files
from .efenix_mark import MARK_RGB, is_mark
from .workbook_files import Problem, WorkbookError
from .workbook_parts import (
    MAIN,
    STYLE_XF,
    IrregularSheetData,
    SheetData,
    UnsupportedShape,
    active_sheet,
    appended,
    office_document,
    relationships,
    style_list,
    with_style_attribute,
)
from .workbook_save import SaveProblem, WorkbookSaveError, write_atomically

__all__ = ["Refusal", "mark_ready"]

_MARK_FILL: Final = (
    b'<fill><patternFill patternType="solid"><fgColor rgb="FF' + MARK_RGB.encode("ascii") + b'"/>'
    b'<bgColor indexed="64"/></patternFill></fill>'
)
"""Wypełnienie Znacznika tak, jak Excel taty zapisuje jednolite wypełnienie (``bgColor`` 64)."""
_STYLE: Final = re.compile(rb'\ss="(\d+)"')


class Refusal(Enum):
    """Fakt, przez który Znaczniki efenix nie trafiły do Pliku zbiorczego; plik jest taki, jak był."""

    OPEN_IN_EXCEL = "Excel trzyma Plik zbiorczy"
    """Plik blokady Excela przy odczycie tuż przed zapisem."""
    CHANGED = "Plik zbiorczy zmienił się od odczytu"
    """Na dysku są inne bajty niż te, z których pochodzi zakres, więc numery wierszy mogą wskazywać inne zlecenia."""
    WRITE_FAILED = "zapis nieudany"
    """Pliku nie ma, nie da się go odczytać, pliku tymczasowego nie da się utworzyć ani zapisać albo system odmówił
    podmiany (np. Excel albo OneDrive trzyma plik bez pliku blokady)."""


def mark_ready(path: Path, content: bytes, column: str, rows: Collection[int]) -> Refusal | None:
    """Stawia Znacznik efenix w komórce ``column`` (litera ``ADRES``) wierszy ``rows`` Pliku zbiorczego ``path``.

    ``content``: bajty pliku, z których pochodzą numery ``rows``. ``None``, gdy każda z tych komórek ma Znacznik w pliku na
    dysku; inaczej ``Refusal``, a plik się nie zmienia.
    """

    marked = _marked(content, column, rows)
    if marked == content:
        return None
    try:
        if workbook_files.workbook_content(path) != content:
            return Refusal.CHANGED
    except WorkbookError as error:
        return Refusal.OPEN_IN_EXCEL if error.problem is Problem.OPEN_IN_EXCEL else Refusal.WRITE_FAILED

    def write(temporary: Path) -> None:
        try:
            temporary.write_bytes(marked)
        except OSError as error:
            raise WorkbookSaveError(path, SaveProblem.CONTENT) from error

    try:
        write_atomically(path, write)
    except WorkbookSaveError:  # plik tymczasowy, jego zapis albo podmiana
        return Refusal.WRITE_FAILED
    return None


def _marked(content: bytes, column: str, rows: Collection[int]) -> bytes:
    """Bajty skoroszytu ``content`` ze Znacznikiem efenix w komórce ``column`` wierszy ``rows``."""

    if not rows:
        return content
    with zipfile.ZipFile(BytesIO(content)) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
    workbook = office_document(parts)
    if workbook is None:
        raise UnsupportedShape("skoroszyt")
    rels = relationships(parts, workbook)
    styles_part = next((rel.target for rel in rels.values() if rel.kind.endswith("/styles")), None)
    if styles_part is None:
        raise UnsupportedShape("style")
    sheet = active_sheet(parts, workbook)
    styles = _Styles(parts[styles_part])
    marked = _marked_sheet(parts[sheet.part], column, rows, styles)
    if marked == parts[sheet.part]:
        return content
    changed = {sheet.part: marked, styles_part: styles.xml()}
    for xml in changed.values():
        expat.ParserCreate().Parse(xml, True)
    written = BytesIO()
    with zipfile.ZipFile(written, "w") as target:
        for info in infos:
            target.writestr(info, changed.get(info.filename, parts[info.filename]))
    return written.getvalue()


def _marked_sheet(xml: bytes, column: str, rows: Collection[int], styles: _Styles) -> bytes:
    try:
        data = SheetData.of(xml)
    except IrregularSheetData as error:
        raise UnsupportedShape(f"arkusz: {error}") from error
    found = {row.number: row for row in data.rows}
    pieces: list[bytes] = []
    position = 0
    for number in sorted(rows):
        row = found.get(number)
        reference = column.encode("ascii") + b"%d" % number
        cell = None if row is None else re.compile(rb'<c r="' + reference + rb'"([^>]*?)(/?>)').search(xml, row.start, row.end)
        if cell is None:
            raise UnsupportedShape(f"brak komórki w wierszu {number}")
        attributes = cell.group(1)
        style = _STYLE.search(attributes)
        old = int(style.group(1)) if style else 0
        new = b' s="%d"' % styles.marked(old)
        attributes = _STYLE.sub(new, attributes) if style else new + attributes
        pieces += [xml[position : cell.start()], b'<c r="' + reference + b'"' + attributes + cell.group(2)]
        position = cell.end()
    return b"".join([*pieces, xml[position:]])


class _Styles:
    """Listy ``fills`` i ``cellXfs`` z ``xl/styles.xml`` i wpisy, które zapis Znaczników dopisuje na ich końcu."""

    def __init__(self, xml: bytes) -> None:
        self._xml = xml
        root = ElementTree.fromstring(xml)
        fills = [cast(Fill, Fill.from_tree(cast(Any, fill))) for fill in root.iterfind(f"{MAIN}fills/{MAIN}fill")]
        self._marks = {index for index, fill in enumerate(fills) if is_mark(fill)}
        self._fill_count = len(fills)
        self._fill_ids = [int(xf.get("fillId", "0")) for xf in root.iterfind(f"{MAIN}cellXfs/{MAIN}xf")]
        self._xfs = STYLE_XF.findall(style_list(xml, b"cellXfs").group(2))
        if len(self._xfs) != len(self._fill_ids):
            raise UnsupportedShape("cellXfs")
        self._added_fill = False
        self._added_xfs: list[bytes] = []

    def marked(self, style: int) -> int:
        """Styl ``style`` z wypełnieniem Znacznika; ``style``, gdy już je ma."""

        if style >= len(self._xfs):
            raise UnsupportedShape("styl komórki")
        if self._fill_ids[style] in self._marks:
            return style
        xf = with_style_attribute(self._xfs[style], b"fillId", self._mark_fill(), b"applyFill")
        known = [*self._xfs, *self._added_xfs]
        if xf not in known:
            self._added_xfs.append(xf)
            known.append(xf)
        return known.index(xf)

    def _mark_fill(self) -> int:
        if self._marks:
            return min(self._marks)
        self._added_fill = True
        return self._fill_count

    def xml(self) -> bytes:
        xml = appended(self._xml, b"fills", [_MARK_FILL] if self._added_fill else [], self._fill_count)
        return appended(xml, b"cellXfs", self._added_xfs, len(self._xfs))
