"""Syntetyczny INTERMAX (Rejestr zleceń) w kształcie pliku taty dla testów Uporządkowania INTERMAX.

Arkusz zleceń ma nagłówki od ``AKCJE`` (B) do ``UWAGI`` (O) w wierszu 1 i kolumny z aplikacji za nimi do AK,
zamrożony nagłówek, uporządkowane dni w Calibri 8 (WYKONAWCA Calibri 9) z datą ``m/d/yy h:mm`` i cienką ramką, a
na dole Surowe zlecenia z wyglądem z aplikacji (Roboto 4, białe i szare tła) z pierwszym wierszem przesuniętym o
dwie kolumny w lewo i Hiperłączem w ``NUMER ZL.``. Wiersze wyglądają jak u taty: wiersz zlecenia ma styl wiersza
z ramką i wysokość 12, pusty wiersz między segmentami ma puste komórki z ramką, pod dniem są przygotowane puste
wiersze z ramką (styl wiersza bez komórek, wysokość 11,25), a żółty wiersz to styl całego wiersza bez komórek
(albo, w osobnym przypadku, żółte komórki). Zapis jak w Excelu: teksty wspólne (``UWAGI`` jako tekst z
fragmentami i podpowiedzią wymowy), liczby bez ``t="n"`` i ``x14ac:dyDescent`` w wierszach z wysokością. Obok są ukryty arkusz, lista i komentarze. Wartości
są syntetyczne.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils.datetime import CALENDAR_MAC_1904
from openpyxl.worksheet.worksheet import Worksheet

ORDER_SHEET = "ZLECENIA OD 06_2025"
HEADERS = (
    "AKCJE",
    "DATA GODZ. POCZ.",
    "MIASTO",
    "ADRES",
    "UMOWA",
    "URZĄDZENIA",
    "CZYNNOŚCI",
    "NUMER ZL.",
    "WYKONAWCA",
    "NUMER UMOWY",
    "SKUTECZNE",
    "CZYNNOŚCI ZREALIZOWANE",
    "ZWROT",
    "UWAGI",
)
FIRST = 2  # B: AKCJE
DATE = 3  # C
ADDRESS = 5  # E: ADRES
DEVICES = 7  # G: URZĄDZENIA
ACTIVITIES = 8  # H: CZYNNOŚCI
NUMBER = 9  # I: NUMER ZL.
WORKER = 10  # J
CONTRACT_NUMBER = 11  # K: NUMER UMOWY
LAST = 15  # O: UWAGI
APP_LAST = 37  # AK: ostatnia kolumna z aplikacji
DATE_FORMAT = "m/d/yy h:mm"
APP_DATE_FORMAT = "yyyy-mm-dd hh:mm"
_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_APP_FONT = Font(name="Roboto", sz=4, b=True, color="FF333333")
_APP_FILLS = (PatternFill("solid", fgColor="FFFFFFFF"), PatternFill("solid", fgColor="FFD9D9D9"))
YELLOW = PatternFill("solid", fgColor="FFFFFF00")
_WHITE = PatternFill("solid", fgColor="FFFFFFFF")
ORDER_HEIGHT = 12.0
"""Wysokość wiersza zlecenia i pustego wiersza między segmentami w uporządkowanych dniach."""
BLANK_HEIGHT = 11.25
"""Wysokość przygotowanego pustego wiersza pod dniem."""


@dataclass(frozen=True)
class Order:
    """Zlecenie syntetyczne: chwila, Wykonawca i numer, z którego powstają pozostałe wartości wiersza.

    ``operator`` stoi w ``CZYNNOŚCI`` (``None``: pusta komórka), a ``kind`` w ``URZĄDZENIA``, jak z aplikacji.
    ``cells``: kolumna (od 1, nieprzesunięta) → wartość w miejsce wartości z numeru, np. liczba w ``NUMER UMOWY``.
    ``shifted``: wiersz stoi dwie kolumny na lewo od nagłówków, jak pierwszy wiersz każdego wklejenia (pierwszy wiersz
    ``Intermax.raw`` przesuwa ``Intermax.shifted``), a ``app_look``: wiersz w ``Intermax.ordered`` ma wygląd z
    aplikacji (Roboto 4), jak zlecenie wklejone nad uporządkowanymi.
    """

    when: datetime
    worker: str
    number: int
    operator: str | None = "INEA"
    kind: str = "Instalacja"
    cells: tuple[tuple[int, datetime | str | int], ...] = ()
    shifted: bool = False
    app_look: bool = False

    def values(self) -> dict[int, datetime | str | int]:
        """Wartości kolumn od B do AK na swoim miejscu (nieprzesunięte)."""

        values: dict[int, datetime | str | int] = {
            DATE: self.when,
            4: "Miasto",
            ADDRESS: f"Ulica {self.number}",
            6: "Umowa",
            DEVICES: self.kind,
            NUMBER: f"ZL-{self.number}",
            WORKER: self.worker,
            CONTRACT_NUMBER: f"UM-{self.number}",
        }
        if self.operator is not None:
            values[ACTIVITIES] = self.operator
        values.update({column: f"APP{column}-{self.number}" for column in range(LAST + 1, APP_LAST + 1)})
        values.update(self.cells)
        return values

    @property
    def link(self) -> str:
        return f"https://example.invalid/zlecenie/{self.number}"


@dataclass(frozen=True)
class Layout:
    """Gdzie fixture postawiła wiersze: ostatni uporządkowany, żółty i pierwszy Surowy, a ``raw_rows`` i
    ``older_raw_rows`` wiersz każdego zlecenia ``Intermax.raw`` i ``Intermax.older_raw``."""

    last_ordered: int
    yellow: int | None
    first_raw: int
    raw: tuple[Order, ...]
    raw_rows: tuple[int, ...] = ()
    older_raw_rows: tuple[int, ...] = ()


@dataclass
class Intermax:
    """Opis syntetycznego INTERMAX do zapisania przez ``write``."""

    ordered: Sequence[Order] = field(
        default_factory=lambda: (
            Order(datetime(2026, 10, 19, 9), "anna.kowalska", 1),
            Order(datetime(2026, 10, 19, 12), "anna.kowalska", 2),
            Order(datetime(2026, 10, 20, 8), "jan.nowak", 3),
        )
    )
    raw: Sequence[Order] = field(
        default_factory=lambda: (
            Order(datetime(2026, 10, 26, 14), "jan.nowak", 101),
            Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102),
            Order(datetime(2026, 10, 26, 16), "anna.kowalska", 103),
            Order(datetime(2026, 10, 26, 8), "jan.nowak", 104),
            Order(datetime(2026, 10, 26, 10), "anna.kowalska", 105),
            Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 106),
        )
    )
    yellow: Literal["row", "cells"] | None = "row"
    """Żółty wiersz taty: styl całego wiersza bez komórek, żółte komórki od B (``yellow_cells``) albo brak."""
    yellow_cells: int = LAST - FIRST
    above_yellow: int = 1
    """Puste wiersze między ostatnim uporządkowanym wierszem a żółtym."""
    shifted: bool = True
    gap: int = 3
    """Puste wiersze między ostatnim uporządkowanym (albo żółtym) wierszem a wklejeniem."""
    grid: bool = True
    """Przygotowane puste wiersze taty z ramką pod dniem, do końca wklejenia i 5 wierszy niżej."""
    older_sheet: bool = False
    """Starszy arkusz zleceń z samymi uporządkowanymi dniami przed arkuszem z wklejeniem."""
    older_ordered: Sequence[Order] | None = None
    """Uporządkowane zlecenia starszego arkusza zleceń; bez nich te same co ``ordered``."""
    older_raw: Sequence[Order] = ()
    """Wklejenie na dole starszego arkusza zleceń, ``gap`` pustych wierszy pod jego uporządkowanymi zleceniami."""
    blank_in_paste: frozenset[int] = frozenset()
    """Indeksy zleceń ``raw``, nad którymi w wklejeniu stoi pusty wiersz taty."""
    epoch_1904: bool = False
    excel: bool = True
    raw_date_format: str = APP_DATE_FORMAT
    """Format daty Surowych zleceń: własny format aplikacji albo wbudowany format Excela."""
    active_sheet: str = ORDER_SHEET
    """Arkusz, który tata zostawił aktywny i zaznaczony przy ostatnim zapisie."""
    frozen: bool = True
    """Zamrożony nagłówek arkusza zleceń, jak u taty; bez niego widok bez panelu."""
    """Zapis jak w Excelu (teksty wspólne, liczby bez ``t``); bez tego teksty wbudowane z openpyxl."""

    def write(self, path: Path) -> Layout:
        workbook = Workbook()
        if self.epoch_1904:
            workbook.epoch = CALENDAR_MAC_1904
        hidden = workbook.active
        assert isinstance(hidden, Worksheet)
        hidden.title = "Arkusz1"
        hidden.sheet_state = "hidden"
        older_raw_rows: tuple[int, ...] = ()
        if self.older_sheet:
            older = self.ordered if self.older_ordered is None else self.older_ordered
            older_sheet = _order_sheet(workbook, "ZLECENIA OD 08_11_2021")
            older_last = _ordered_days(older_sheet, older)
            older_raw_rows = self._paste(older_sheet, self.older_raw, older_last + 1 + self.gap, frozenset())
        sheet = _order_sheet(workbook, ORDER_SHEET, frozen=self.frozen)
        workbook.active = len(workbook.worksheets) - 1
        last_ordered = _ordered_days(sheet, self.ordered)
        yellow = None
        if self.yellow is not None:
            yellow = last_ordered + self.above_yellow + 1
            if self.yellow == "row":
                sheet.row_dimensions[yellow].fill = YELLOW
                sheet.row_dimensions[yellow].height = BLANK_HEIGHT
            else:
                for column in range(FIRST, FIRST + self.yellow_cells):
                    sheet.cell(yellow, column).fill = YELLOW
            row = yellow + 1
        else:
            row = last_ordered + 1
        first_raw = row + self.gap
        if self.grid:
            for number in range(last_ordered + 1, first_raw + len(self.raw) + len(self.blank_in_paste) + 5):
                if number != yellow:
                    _grid_row(sheet, number)
        raw_rows = self._paste(sheet, self.raw, first_raw, self.blank_in_paste)
        lists = workbook.create_sheet("LISTA OD 08.11.2021.")
        lists["A1"] = "lista"
        notes = workbook.create_sheet("komentarze")
        notes["B1"] = "komentarz"
        workbook.active = workbook[self.active_sheet]
        for worksheet in workbook.worksheets:
            worksheet.sheet_view.tabSelected = True if worksheet.title == self.active_sheet else None
        workbook.save(path)
        if self.excel:
            like_excel(path)
        return Layout(last_ordered, yellow, first_raw, tuple(self.raw), raw_rows, older_raw_rows)

    def _paste(self, sheet: Worksheet, raw: Sequence[Order], first: int, blank_before: frozenset[int]) -> tuple[int, ...]:
        """Wklejenie ``raw`` od wiersza ``first`` z wyglądem z aplikacji, z pustym wierszem nad zleceniami
        ``blank_before``; wiersz każdego zlecenia."""

        rows: list[int] = []
        number = first
        for index, order in enumerate(raw):
            if index in blank_before:
                number += 1
            shift = 2 if (self.shifted and index == 0) or order.shifted else 0
            for column in range(1, APP_LAST + 1):
                cell = sheet.cell(number, column)
                cell.font = _APP_FONT
                cell.fill = _APP_FILLS[index % 2]
            for column, value in order.values().items():
                cell = sheet.cell(number, column - shift, value)
                if column == DATE:
                    cell.number_format = self.raw_date_format
                if column == NUMBER:
                    cell.hyperlink = order.link
            rows.append(number)
            number += 1
        return tuple(rows)


_INLINE = re.compile(rb'<c ([^>]*?)t="inlineStr"([^>]*)><is><t[^>]*>([^<]*)</t></is></c>')
_MAIN_NAMESPACE = b'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_X14AC = (
    b' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="x14ac"'
    b' xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"'
)
_RICH = {"UWAGI": b'<si><r><t>UW</t></r><r><t/></r><r><t>AGI</t></r><rPh sb="0" eb="1"><t>X</t></rPh></si>'}


def like_excel(path: Path) -> None:
    """Skoroszyt z openpyxl zapisany tak jak Excel: teksty wspólne zamiast wbudowanych i liczby bez ``t="n"``."""

    strings: list[bytes] = []

    def shared(found: re.Match[bytes]) -> bytes:
        text = html.unescape(found.group(3).decode("utf-8"))
        entry = _RICH.get(text, b"<si><t>" + found.group(3) + b"</t></si>")
        if entry not in strings:
            strings.append(entry)
        return b"<c " + found.group(1) + b't="s"' + found.group(2) + b"><v>%d</v></c>" % strings.index(entry)

    def sheet(xml: bytes) -> bytes:
        xml = _INLINE.sub(shared, xml).replace(b' t="n"', b"")
        xml = re.sub(rb'(<row [^>]*?ht="[^"]*")', rb'\g<1> x14ac:dyDescent="0.2"', xml)
        return xml.replace(_MAIN_NAMESPACE, _MAIN_NAMESPACE + _X14AC, 1)

    rewrite_parts(path, lambda name, data: sheet(data) if name.startswith("xl/worksheets/sheet") else data)
    table = b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="%d" uniqueCount="%d">' % (
        len(strings),
        len(strings),
    )
    relationship = (
        b'<Relationship Id="rIdSst" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        b'sharedStrings" Target="sharedStrings.xml"/></Relationships>'
    )
    override = (
        b'<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        b'spreadsheetml.sharedStrings+xml"/></Types>'
    )
    rewrite_parts(
        path,
        lambda name, data: {
            "xl/_rels/workbook.xml.rels": data.replace(b"</Relationships>", relationship),
            "[Content_Types].xml": data.replace(b"</Types>", override),
        }.get(name, data),
        added={"xl/sharedStrings.xml": table + b"".join(strings) + b"</sst>"},
    )


def rewrite_parts(path: Path, change: Callable[[str, bytes], bytes], added: dict[str, bytes] | None = None) -> None:
    """Skoroszyt ``path`` z częściami zmienionymi przez ``change(nazwa, bajty)`` i ``added`` dopisanymi na końcu."""

    with zipfile.ZipFile(path) as source:
        entries = [(info, change(info.filename, source.read(info))) for info in source.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for info, data in entries:
            target.writestr(info, data)
        for name, data in (added or {}).items():
            target.writestr(name, data)


def _order_sheet(workbook: Workbook, title: str, *, frozen: bool = True) -> Worksheet:
    sheet = workbook.create_sheet(title)
    assert isinstance(sheet, Worksheet)
    if frozen:
        sheet.freeze_panes = "A2"
    for column, header in enumerate(HEADERS, start=FIRST):
        sheet.cell(1, column, header).font = Font(name="Calibri", sz=11, b=True)
    for column, header in enumerate(("BOS", "TYP", "STATUS 1"), start=LAST + 1):
        sheet.cell(1, column, header)
    return sheet


def _grid_row(sheet: Worksheet, number: int) -> None:
    """Wiersz z wyglądem taty: styl wiersza Calibri 8 z ramką i białym tłem."""

    look = sheet.row_dimensions[number]
    look.font, look.border, look.fill = Font(name="Calibri", sz=8), _BORDER, _WHITE
    look.height = BLANK_HEIGHT


def _ordered_days(sheet: Worksheet, ordered: Sequence[Order]) -> int:
    """Uporządkowane zlecenia od wiersza 2 z pustym wierszem między Wykonawcami; ostatni uporządkowany wiersz."""

    row = 2
    for index, order in enumerate(ordered):
        if index and ordered[index - 1].worker != order.worker:
            _grid_row(sheet, row)
            sheet.row_dimensions[row].height = ORDER_HEIGHT
            for column in range(FIRST, LAST + 1):
                sheet.cell(row, column).border = _BORDER
            row += 1
        _grid_row(sheet, row)
        sheet.row_dimensions[row].height = ORDER_HEIGHT
        for column, value in order.values().items():
            cell = sheet.cell(row, column - (2 if order.shifted else 0), value)
            if column <= LAST:
                cell.font = _APP_FONT if order.app_look else Font(name="Calibri", sz=9 if column == WORKER else 8)
                cell.border = _BORDER
            if column == DATE:
                cell.number_format = DATE_FORMAT
            if column == NUMBER:
                cell.hyperlink = order.link
        row += 1
    return row - 1


def parts(path: Path) -> dict[str, bytes]:
    """Części zip skoroszytu po nazwie, rozpakowane."""

    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def order_rows(path: Path, first: int, last: int) -> list[tuple[object, ...] | None]:
    """Wiersze arkusza zleceń od ``first`` do ``last``: wartości B:AK albo ``None`` dla pustego wiersza."""

    sheet = load_workbook(path).worksheets[1]
    rows: list[tuple[object, ...] | None] = []
    for number in range(first, last + 1):
        values = tuple(sheet.cell(number, column).value for column in range(1, APP_LAST + 1))
        rows.append(None if all(value is None for value in values) else values)
    return rows
