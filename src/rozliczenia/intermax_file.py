"""Pisarz INTERMAX: bajty Rejestru zleceń z uporządkowanym dniem (Uporządkowanie INTERMAX) albo z komórkami Wpisania
raportów i ich sprawdzenie.

Komórki Wpisania raportów (``with_cells``, ``check_cells``) zmieniają tylko tekst wskazanych komórek arkusza zleceń, z
wyglądem uporządkowanego wiersza (``_Looks.text``), a Przeniesienia i Zlecenia dopisane z raportu
(``raw_orders.MovePlan``) dodatkowo numery wierszy od pierwszego bloku dnia do końca arkusza i nowe wiersze; reszta
pliku zostaje bajt w bajt (opis w ``with_cells``). Dalej o dniu Uporządkowania.

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
from decimal import ROUND_FLOOR, Decimal
import struct
import zipfile
import zlib
from collections.abc import Callable, Mapping, Sequence
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
from .raw_orders import (
    AddedRow,
    DayPlan,
    IntermaxEntry,
    MovePlan,
    NewOrder,
    NewSeparator,
    OperatorColor,
    OrderColumns,
    RawBlock,
)
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

__all__ = ["Cells", "check", "check_cells", "ordered", "with_cells"]

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
_CELL: Final = re.compile(rb'<c r="([A-Z]{1,3})\d+"([^>]*?)(?:/>|>.*?</c>)', re.S)
_STYLE: Final = re.compile(rb'\ss="\d+"')
_INLINE_TEXT: Final = re.compile(rb"<t(?:\s[^>]*)?>([^<]*)</t>")
_VALUE: Final = re.compile(rb"<v>([^<]*)</v>")
_MERGED: Final = re.compile(r'<mergeCell\b[^>]*?\sref="([^"]*)"')
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
    """Style komórek z ``xl/styles.xml``, do których zapis dopisuje wygląd dnia."""

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
    looks = _Looks(write_styles)
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


Cells = Mapping[PasteArea, Mapping[tuple[int, int], str]]
"""Komórki Wpisania raportów: obszar wklejania arkusza zleceń → (wiersz, kolumna od 1) → tekst."""

Moves = Mapping[PasteArea, MovePlan]
"""Przeniesienia i dopisania zleceń Wpisania raportów: obszar wklejania arkusza zleceń → plan jego wierszy
(``raw_orders.plan_moves``)."""


def with_cells(register: RegisterFile, cells: Cells, moves: Moves | None = None) -> bytes:
    """Bajty INTERMAX, w których zmieniają się tylko komórki ``cells`` i wiersze Przeniesień ``moves`` (Wpisanie
    raportów, ADR 0028 i 0029).

    Komórka dostaje tekst wbudowany (``inlineStr``), jak Wpis urządzenia i czynności INTERMAX. Komórka, która jest w
    pliku, zachowuje swój styl, a komórka, której nie ma, dostaje styl tekstu uporządkowanego wiersza
    (``_Looks.text``), dopisany do ``xl/styles.xml`` tylko wtedy, gdy go tam nie ma. Potem Przeniesienia (``_moved``):
    wiersze od ``MovePlan.first`` do końca arkusza stają w kolejności planu, przeniesione zlecenie dostaje tekst
    ``WYKONAWCA``, a przeniesione na inny dzień nowy dzień w ``DATA GODZ. POCZ.`` (``_shifted``), nowy pusty wiersz
    między segmentami wygląd z Uporządkowania INTERMAX, a dopisane zlecenie (``_added_row``) swoje wartości z wyglądem
    Uporządkowania bez Koloru operatora. Każda inna część i każdy inny
    bajt arkusza zostają, także widok i aktywna karta. ``UnsupportedShape``, gdy komórka ma formułę albo leży w
    scaleniu, gdy przesuwany wiersz ma formułę albo gdy zakres (poza Hiperłączem jednej komórki) sięga przesuwanych
    wierszy, a ``WorkbookError``, gdy stylów nie da się odczytać.
    """

    package = register.package
    styles = package.parts[package.styles_part]
    with workbook_files.unreadable_as_error(register.path):
        looks = _Looks(_WriteStyles.of(styles))
    parts = {area.part: _sheet_with_cells(area.sheet_xml, targets, looks) for area, targets in cells.items()}
    for area, plan in (moves or {}).items():
        sheet = RowsFromBottom(parts.get(area.part, area.sheet_xml.xml))
        parts[area.part] = _moved(sheet, area.columns, plan, looks)
    parts[package.styles_part] = looks.styles(styles)
    return _archive([(info, parts.get(info.filename, package.parts[info.filename])) for info in package.infos])


def check_cells(register: RegisterFile, written: bytes, cells: Cells, moves: Moves | None = None) -> None:
    """``WriteMismatch``, gdy ``written`` różni się od INTERMAX czymś więcej niż tekstem komórek ``cells``, wierszami
    Przeniesień ``moves`` i stylami dopisanymi na końcu list ``xl/styles.xml``.

    Arkusz z Przeniesieniami sprawdza najpierw komórki na arkuszu przed przesunięciem wierszy, a potem każdy wiersz
    pod nowym numerem (``_check_moved``). Uszkodzenie ``written`` zgłasza jak odczyt skoroszytu
    (``workbook_files.unreadable_as_error``).
    """

    package = register.package
    with zipfile.ZipFile(BytesIO(written)) as archive:
        names = [info.filename for info in archive.infolist()]
        parts = {name: archive.read(name) for name in names}
    if names != [info.filename for info in package.infos]:
        raise WriteMismatch("części")
    plans = moves or {}
    changed = {area.part: area for area in (*cells, *plans)}
    for name in names:
        if name not in changed and name != package.styles_part and parts[name] != package.parts[name]:
            raise WriteMismatch(name)
    _check_styles(package.parts[package.styles_part], parts[package.styles_part])
    styles = package.parts[package.styles_part]
    for name, area in changed.items():
        targets = cells.get(area, {})
        plan = plans.get(area)
        if plan is None:
            _check_sheet_cells(area.sheet_xml, parts[name], targets)
            continue
        with workbook_files.unreadable_as_error(register.path):
            looks = _Looks(_WriteStyles.of(styles))
        before = _sheet_with_cells(area.sheet_xml, targets, looks) if targets else area.sheet_xml.xml
        _check_sheet_cells(area.sheet_xml, before, targets)
        _check_moved(RowsFromBottom(before), parts[name], area.columns, plan)


def _rows_of(targets: Mapping[tuple[int, int], str]) -> dict[int, dict[int, str]]:
    rows: dict[int, dict[int, str]] = {}
    for (row, column), text in targets.items():
        rows.setdefault(row, {})[column] = text
    return rows


def _sheet_with_cells(sheet: RowsFromBottom, targets: Mapping[tuple[int, int], str], looks: _Looks) -> bytes:
    xml = sheet.xml
    merged = [range_boundaries(reference) for reference in _MERGED.findall(xml[sheet.end :].decode("utf-8"))]

    def inside(row: int, column: int, left: int | None, top: int | None, right: int | None, bottom: int | None) -> bool:
        """Komórka w zakresie scalenia; brak granicy to cała kolumna albo cały wiersz."""

        return (left or 1) <= column <= (right or column) and (top or 1) <= row <= (bottom or row)

    def written(row: int, row_xml: bytes, texts: Mapping[int, str]) -> bytes:
        if any(inside(row, column, *bounds) for column in texts for bounds in merged):
            raise UnsupportedShape("scalenie")
        return _row_with_cells(row_xml, row, texts, looks)

    return _rows_changed(sheet, xml, _rows_of(targets), written)


def _rows_changed(
    sheet: RowsFromBottom,
    xml: bytes,
    rows: Mapping[int, Mapping[int, str]],
    change: Callable[[int, bytes, Mapping[int, str]], bytes],
) -> bytes:
    """XML arkusza ``xml`` (wiersze w ``sheet``) z każdym wierszem ``rows`` zmienionym przez ``change``; reszta bajt w
    bajt. ``KeyError``, gdy wiersza nie ma."""

    pieces: list[bytes] = []
    position = 0
    for row in sorted((sheet.row(number) for number in rows), key=lambda row: row.start):
        pieces += [xml[position : row.start], change(row.number, xml[row.start : row.end], rows[row.number])]
        position = row.end
    pieces.append(xml[position:])
    return b"".join(pieces)


def _row_with_cells(row_xml: bytes, number: int, texts: Mapping[int, str], looks: _Looks) -> bytes:
    """Wiersz ``<row>`` z tekstem ``texts`` w ich kolumnach: komórka, która jest, dostaje tekst ze swoim stylem, a
    brakująca staje przed pierwszą komórką na prawo od niej; reszta wiersza zostaje bajt w bajt."""

    pending = sorted(texts)
    position = row_xml.index(b">") + 1
    out = [row_xml[:position]]
    for found in _CELL.finditer(row_xml, position):
        column = _column(found)
        while pending and pending[0] < column:
            out += [row_xml[position : found.start()], _text_cell(pending[0], number, looks.text(), texts[pending[0]])]
            position = found.start()
            pending.pop(0)
        if pending and pending[0] == column:
            if _FORMULA.search(found.group(0)):
                raise UnsupportedShape("formuła")
            style = _STYLE.search(found.group(2))
            out += [row_xml[position : found.start()], _text_cell(column, number, style, texts[column])]
            position = found.end()
            pending.pop(0)
    end = row_xml.rindex(b"</row>")
    out.append(row_xml[position:end])
    out += [_text_cell(column, number, looks.text(), texts[column]) for column in pending]
    out.append(row_xml[end:])
    return b"".join(out)


def _text_cell(column: int, row: int, style: int | re.Match[bytes] | None, text: str) -> bytes:
    """Komórka z tekstem wbudowanym; ``style``: numer stylu nowej komórki, atrybut ``s`` komórki, która była, albo
    ``None``, gdy ta go nie miała."""

    match style:
        case int():
            attributes = b' s="%d"' % style
        case re.Match():
            attributes = style.group(0)
        case None:
            attributes = b""
    content = b"<is><t>%s</t></is>" % html.escape(text, quote=False).encode("utf-8")
    return SheetCell(column, b"", content).xml(column, row, attributes + b' t="inlineStr"')


_ROW_NUMBER: Final = re.compile(rb'^<row r="\d+"')
_CELL_NUMBER: Final = re.compile(rb'(<c r="[A-Z]{1,3})\d+"')


def _renumbered(row_xml: bytes, number: int) -> bytes:
    """Wiersz ``<row>`` pod numerem ``number``: ``r`` wiersza i każdej jego komórki; reszta bajt w bajt."""

    row_xml = _ROW_NUMBER.sub(b'<row r="%d"' % number, row_xml, count=1)
    return _CELL_NUMBER.sub(rb'\g<1>%d"' % number, row_xml)


def _row_look(row_xml: bytes) -> bytes:
    """Atrybuty wyglądu ``<row>`` (styl wiersza, wysokość) wiersza ``row_xml``, jak ``_RowLooks``."""

    attributes = row_attributes(row_xml[: row_xml.index(b">") + 1])
    return b"".join(b' %s="%s"' % (name, attributes[name]) for name in _ROW_LOOK if name in attributes)


def _new_numbers(plan: MovePlan) -> dict[int, int]:
    """Wiersz sprzed zapisu → jego numer po zapisie, dla wierszy planu."""

    return {slot: plan.first + index for index, slot in enumerate(plan.rows) if isinstance(slot, int)}


def _moved(sheet: RowsFromBottom, columns: OrderColumns, plan: MovePlan, looks: _Looks) -> bytes:
    """XML arkusza z wierszami od ``plan.first`` w kolejności planu.

    Wiersz, który zostaje pod swoim numerem i nie jest przenoszony, zostaje bajt w bajt. Inny dostaje nowy numer
    (``_renumbered``), a przeniesione zlecenie tekst ``WYKONAWCA`` w stylu swojej komórki (``_row_with_cells``) i, na
    inny dzień, liczbę daty większą o ``MovePlan.shifts`` (``_shifted``). Nowy
    pusty wiersz między segmentami ma puste komórki od A do ``UWAGI`` z wyglądem Uporządkowania (``_order_row``) i
    wygląd ``<row>`` przeniesionego zlecenia. Hiperłącza przesuwanych wierszy idą z nimi, a ``<dimension>`` sięga
    ostatniego wiersza, gdy arkusz urósł.
    """

    xml = sheet.xml
    region = sheet.above(plan.first - 1)
    by_number = {row.number: row for row in region}
    tail_at = sheet.end + len(b"</sheetData>")
    _require_writable(xml[tail_at:], plan.first - 1)
    rows: list[bytes] = []
    for index, slot in enumerate(plan.rows):
        number = plan.first + index
        if isinstance(slot, NewSeparator):
            model = by_number[slot.model]
            look = _row_look(xml[model.start : model.end])
            rows.append(_order_row(b"", number, 0, columns, looks, look, OperatorColor(), {}))
            continue
        if isinstance(slot, NewOrder):
            model = by_number[slot.model]
            model_xml = xml[model.start : model.end]
            cells = _added_cells(model_xml, columns, plan.added[slot.added], slot.days)
            rows.append(_added_row(number, columns, looks, _row_look(model_xml), cells))
            continue
        found = by_number.get(slot)
        if found is None:
            continue
        row_xml = xml[found.start : found.end]
        if slot == number and slot not in plan.workers:
            rows.append(row_xml)
            continue
        if _FORMULA.search(row_xml):
            raise UnsupportedShape("formuła")
        row_xml = _renumbered(row_xml, number)
        if slot in plan.shifts:
            row_xml = _shifted(row_xml, columns.date, plan.shifts[slot])
        if slot in plan.workers:
            row_xml = _row_with_cells(row_xml, number, {columns.worker: plan.workers[slot]}, looks)
        rows.append(row_xml)
    last = plan.first + len(plan.rows) - 1
    head = _with_dimension(xml[: sheet.start], last, columns.last)
    start = region[0].start if region else sheet.end
    end = region[-1].end if region else sheet.end
    tail = _renumbered_hyperlinks(xml[tail_at:], _new_numbers(plan), plan.first)
    return b"".join((head, xml[sheet.start : start], *rows, xml[end:tail_at], tail))


def _added_cells(model_xml: bytes, columns: OrderColumns, row: AddedRow, days: int) -> dict[int, SheetCell]:
    """Komórki z wartością dopisanego zlecenia bez stylu (poza datą): ``WYKONAWCA`` i teksty ``row`` tekstem
    wbudowanym, liczby liczbą, a ``DATA GODZ. POCZ.`` część dnia liczby daty wiersza ``model_xml`` większa o ``days``,
    z atrybutami (styl, rodzaj) komórki daty tego wiersza; ``UnsupportedShape``, gdy ta komórka nie jest liczbą."""

    model = next((cell for cell in sheet_cells(model_xml) if cell.column == columns.date), None)
    if model is None or model.value is None or model.kind not in (None, b"n"):
        raise UnsupportedShape("data")
    serial = format(Decimal(model.value.decode("ascii")).to_integral_value(ROUND_FLOOR) + days, "f").encode("ascii")
    cells = {columns.date: SheetCell(columns.date, model.attributes, b"<v>%s</v>" % serial)}
    for column, value in {**row.cells, columns.worker: row.worker}.items():
        if isinstance(value, int):
            cells[column] = SheetCell(column, b"", b"<v>%d</v>" % value)
        else:
            text = html.escape(value, quote=False).encode("utf-8")
            cells[column] = SheetCell(column, b' t="inlineStr"', b"<is><t>%s</t></is>" % text)
    return cells


def _added_row(number: int, columns: OrderColumns, looks: _Looks, row_look: bytes, cells: Mapping[int, SheetCell]) -> bytes:
    """Wiersz ``<row>`` dopisanego zlecenia pod numerem ``number`` z wyglądem ``row_look``: komórki od A do ``UWAGI``
    (i komórki ``cells`` za nią) w wyglądzie Uporządkowania bez Koloru operatora (``_Looks.style``), z wartościami
    ``cells``; data zostaje w stylu komórki daty wiersza dnia."""

    written: list[bytes] = []
    for column in sorted({*range(1, columns.last + 1), *cells}):
        cell = cells.get(column, SheetCell(column, b"", None))
        if column == columns.date and column in cells:
            written.append(cell.xml(column, number))
        else:
            style = looks.style(columns, column, 0, None)
            written.append(cell.xml(column, number, cell.unstyled + b' s="%d"' % style))
    return b'<row r="%d"%s>' % (number, row_look) + b"".join(written) + b"</row>"


def _shifted(row_xml: bytes, column: int, days: int) -> bytes:
    """Wiersz z liczbą daty Excela w kolumnie ``column`` większą o ``days`` (dzień się zmienia, godzina, typ i styl
    komórki zostają); ``UnsupportedShape``, gdy komórka nie jest liczbą."""

    for found in _CELL.finditer(row_xml):
        if _column(found) != column:
            continue
        cell = found.group(0)
        value = _VALUE.search(cell)
        kind = SheetCell(column, found.group(2), None).kind
        if value is None or kind not in (None, b"n"):
            break
        shifted = cell[: value.start(1)] + _serial(value.group(1), days) + cell[value.end(1) :]
        return row_xml[: found.start()] + shifted + row_xml[found.end() :]
    raise UnsupportedShape("data")


def _serial(value: bytes, days: int) -> bytes:
    """Liczba daty Excela ``value`` większa o ``days`` dni, z tą samą częścią godziny co do cyfry."""

    return format(Decimal(value.decode("ascii")) + days, "f").encode("ascii")


def _renumbered_hyperlinks(tail: bytes, numbers: Mapping[int, int], first: int) -> bytes:
    """Ogon arkusza z Hiperłączami przesuwanych wierszy pod nowymi numerami; Hiperłącze na kilka komórek albo w wierszu,
    który zniknął, to ``UnsupportedShape``."""

    def moved(found: re.Match[bytes]) -> bytes:
        reference = found.group(2).decode("ascii")
        column, number = coordinate_from_string(reference.split(":")[0])
        if number < first:
            return found.group(0)
        if ":" in reference or number not in numbers:
            raise UnsupportedShape("Hiperłącze")
        return found.group(1) + f"{column}{numbers[number]}".encode("ascii") + found.group(3)

    return _HYPERLINK_REF.sub(moved, tail)


def _check_moved(before: RowsFromBottom, written: bytes, columns: OrderColumns, plan: MovePlan) -> None:
    """``WriteMismatch``, gdy arkusz ``written`` różni się od ``before`` (arkusza z komórkami, przed przesunięciem)
    czymś więcej niż wierszami ``plan`` pod nowymi numerami: każdy wiersz planu ma te same komórki (treść, rodzaj i styl),
    przeniesione zlecenie ``WYKONAWCA`` z planu, a na inny dzień ``DATA GODZ. POCZ.`` większą o dni z planu w tym samym
    typie i stylu, nowy pusty wiersz żadnej wartości, a dopisane zlecenie dokładnie wartości z planu (treść i rodzaj, a
    data także styl komórki daty wiersza dnia); bajty nad ``plan.first`` się nie zmieniają."""

    try:
        data = RowsFromBottom(written)
        written_rows = {row.number: row for row in data.above(plan.first - 1)}
        source_rows = {row.number: row for row in before.above(plan.first - 1)}
    except IrregularSheetData as error:
        raise WriteMismatch("arkusz") from error
    first_source = min(source_rows.values(), key=lambda row: row.start, default=None)
    first_written = min(written_rows.values(), key=lambda row: row.start, default=None)
    if (first_source is None) != (first_written is None):
        raise WriteMismatch("wiersze")
    above = before.xml[before.start : first_source.start if first_source else before.end]
    if _DIMENSION.sub(b"", before.xml[: before.start]) != _DIMENSION.sub(b"", written[: data.start]) or (
        above != written[data.start : first_written.start if first_written else data.end]
    ):
        raise WriteMismatch("wiersze nad Przeniesieniem")
    expected: set[int] = set()
    for index, slot in enumerate(plan.rows):
        number = plan.first + index
        found = written_rows.get(number)
        if isinstance(slot, NewSeparator):
            if found is None or any(cell.valued for cell in sheet_cells(written[found.start : found.end])):
                raise WriteMismatch(f"wiersz {number}")
            expected.add(number)
            continue
        if isinstance(slot, NewOrder):
            model = source_rows[slot.model]
            wanted = _added_cells(before.xml[model.start : model.end], columns, plan.added[slot.added], slot.days)
            got = {cell.column: cell for cell in sheet_cells(written[found.start : found.end])} if found else {}
            valued = {column for column, cell in got.items() if cell.valued}
            date_cell = got.get(columns.date)
            if (
                valued != set(wanted)
                or any((got[column].content, got[column].kind) != (cell.content, cell.kind) for column, cell in wanted.items())
                or date_cell is None
                or date_cell.style != wanted[columns.date].style
            ):
                raise WriteMismatch(f"wiersz {number}")
            expected.add(number)
            continue
        source = source_rows.get(slot)
        if source is None:
            continue
        expected.add(number)
        if found is None:
            raise WriteMismatch(f"wiersz {number}")
        old = {cell.column: cell for cell in sheet_cells(before.xml[source.start : source.end])}
        new = {cell.column: cell for cell in sheet_cells(written[found.start : found.end])}
        if slot in plan.workers:
            cell = new.pop(columns.worker, None)
            old.pop(columns.worker, None)
            if cell is None or cell.kind != b"inlineStr" or _inline_text(cell) != plan.workers[slot]:
                raise WriteMismatch(f"wiersz {number}")
        if slot in plan.shifts:
            was, cell = old.pop(columns.date, None), new.pop(columns.date, None)
            if (
                was is None
                or cell is None
                or was.value is None
                or (cell.kind, cell.style) != (was.kind, was.style)
                or cell.value != _serial(was.value, plan.shifts[slot])
            ):
                raise WriteMismatch(f"wiersz {number}")
        if {column: (cell.content, cell.kind, cell.style) for column, cell in old.items()} != {
            column: (cell.content, cell.kind, cell.style) for column, cell in new.items()
        }:
            raise WriteMismatch(f"wiersz {number}")
    if set(written_rows) != expected:
        raise WriteMismatch("wiersze Przeniesienia")
    tail = before.xml[before.end :]
    if _renumbered_hyperlinks(tail, _new_numbers(plan), plan.first) != written[data.end :]:
        raise WriteMismatch("ogon arkusza")


def _check_sheet_cells(original: RowsFromBottom, written: bytes, targets: Mapping[tuple[int, int], str]) -> None:
    """``WriteMismatch``, gdy arkusz ``written`` bez komórek ``targets`` różni się od oryginału bez nich albo gdy któraś
    z tych komórek nie ma swojego tekstu wbudowanego."""

    rows = _rows_of(targets)

    def without(_number: int, row_xml: bytes, texts: Mapping[int, str]) -> bytes:
        return _CELL.sub(lambda found: b"" if _column(found) in texts else found.group(0), row_xml)

    try:
        data = RowsFromBottom(written)
        same = _rows_changed(original, original.xml, rows, without) == _rows_changed(data, written, rows, without)
        cells = {number: sheet_cells(written[data.row(number).start : data.row(number).end]) for number in rows}
    except (IrregularSheetData, KeyError) as error:
        raise WriteMismatch("arkusz") from error
    if not same:
        raise WriteMismatch("arkusz poza komórkami")
    for number, texts in rows.items():
        found = {cell.column: cell for cell in cells[number]}
        for column, text in texts.items():
            cell = found.get(column)
            if cell is None or cell.kind != b"inlineStr" or _inline_text(cell) != text:
                raise WriteMismatch(f"komórka {get_column_letter(column)}{number}")


def _column(found: re.Match[bytes]) -> int:
    return column_index_from_string(found.group(1).decode("ascii"))


def _inline_text(cell: SheetCell) -> str:
    return html.unescape(b"".join(_INLINE_TEXT.findall(cell.content or b"")).decode("utf-8"))


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

    def __init__(self, styles: _WriteStyles) -> None:
        self._styles = styles
        self._fonts: list[Font] = []
        self._fills: list[Fill] = []
        self._borders: list[Border] = []
        self._xfs: list[bytes] = []
        self._style_ids: dict[tuple[bool, int, str | None], int] = {}

    def style(self, columns: OrderColumns, column: int, number_format: int, fill: str | None) -> int:
        """Styl komórki kolumny zlecenia ``column`` arkusza o kolumnach ``columns``: Calibri 8 (WYKONAWCA pogrubiony
        Calibri 9), czarna, cienka ramka, do lewej i środka.

        ``fill``: wypełnienie RGB z Koloru operatora, jak to, które nadaje Excel; ``None``: bez wypełnienia.
        """

        if column == columns.date:
            number_format = _DATE_FORMAT
        return self._style(column == columns.worker, number_format, fill)

    def text(self) -> int:
        """Styl komórki tekstu uporządkowanego wiersza poza datą i ``WYKONAWCA``, bez wypełnienia: ten, który
        Uporządkowanie daje pustej kolumnie zlecenia bez Koloru operatora."""

        return self._style(False, 0, None)

    def _style(self, worker: bool, number_format: int, fill: str | None) -> int:
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
    fills = {columns.activities: color.activities, columns.contract_number: color.contract_number, columns.devices: color.devices}
    written: dict[int, bytes] = {}
    for source in sheet_cells(row_xml):
        column = source.column + offset
        if column > columns.last:
            continue
        cell = entry.get(column, source)
        style = looks.style(columns, column, looks.number_format(source.style), fills.get(column))
        written[column] = cell.xml(column, number, cell.unstyled + b' s="%d"' % style)
    for column in range(1, columns.last + 1):
        if column not in written:
            style = looks.style(columns, column, 0, fills.get(column))
            written[column] = SheetCell(column, b"", None).xml(column, number, b' s="%d"' % style)
    cells = b"".join(written[column] for column in sorted(written))
    return b'<row r="%d"%s>' % (number, row_look) + cells + b"</row>"


def _entry_cells(entry: IntermaxEntry | None, columns: OrderColumns) -> dict[int, SheetCell]:
    if entry is None:
        return {}
    return {
        column: SheetCell(column, b' t="inlineStr"', b"<is><t>%s</t></is>" % html.escape(text, quote=False).encode("utf-8"))
        for column, text in ((columns.devices, entry.devices), (columns.activities, entry.activities))
    }


def _with_dimension(head: bytes, last_row: int, last_column: int) -> bytes:
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
