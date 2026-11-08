"""Rejestr zleceń (INTERMAX) czytany raz: rozpoznanie arkuszy zleceń i fakty wierszy od dołu, bez openpyxl.

``read`` czyta Rejestr uchwytem plików taty (``dad_files.DadFiles``): części zip, style, teksty wspólne i system dat, a z
wiersza 1 każdego arkusza rozpoznanie arkuszy zleceń. Skoroszyt bez dokumentu skoroszytu albo bez części stylów jest
nieczytelny (``WorkbookError``), jak zepsuty zip albo XML.

Arkusz zleceń rozpoznaje jedna reguła dla obu procesów (``recognize``): komplet nagłówków ``COLUMNS`` w wierszu 1
(każdy w którymś przyjmowanym zapisie) i żaden z nich więcej niż raz. Wynik to wartość, a nie wyjątek: arkusze zleceń
(``OrderSheets``) albo problem nagłówków (``HeadersProblem``), który każdy proces tłumaczy na swój Komunikat. Arkusz
zleceń z ``AKCJE`` i ``UWAGI`` ma obszar wklejania (``PasteArea``), do którego aplikacja firmowa wkleja Surowe zlecenia
i który porządkuje Uporządkowanie INTERMAX. Arkusz starszego układu, bez tych kolumn, obszaru nie ma
(``OrderSheet.paste`` to ``None``): aplikacja do niego nie wkleja, więc Surowych zleceń nikt w nim nie szuka.

Obszar wklejania daje swoje wiersze od dołu jako fakty (``raw_orders.RowFacts``): ~42 tys. wierszy taty to dziesiątki
MB XML, a rozpoznanie potrzebuje tylko dołu arkusza. Komórki ``ADRES`` i ``NUMER UMOWY`` każdego oddanego wiersza poznaje
pamięć reguły danych uchwytu (ADR 0025) w jego położeniach (``raw_orders.row_positions``): pierwszy wiersz bloku
wklejenia dwie kolumny na lewo od nagłówka, każdy inny pod nim, a wiersz z siatki (``raw_orders.both_positions``) w
obu. Zakazane kolumny to te z nagłówkiem zakazanej kolumny w wierszu 1 (``client_data.forbidden_columns``): INTERMAX
nie ma stałego układu kolumn, więc kolumnę zna się po nagłówku, tak jak kolumny ``COLUMNS``.

Kopia wejścia Uruchomienia z Centrum (#842) dostaje bajty Rejestru z chwilą zmiany sprzed odczytu
(``RegisterFile.enter_copy``), a z każdego obszaru wklejania nagłówki i wklejenie (``raw_orders.pasted_rows``): te
same fakty wierszy, które rozpoznaje Planowanie, nie cały Rejestr. Wiersz ma w Kopii komórki od A do ``UWAGI``, te,
które Uporządkowanie przenosi do dnia, pod nagłówkiem, pod którym czyta je rozpoznanie, także przesunięty pierwszy
wiersz, bez zakazanych kolumn (``input_copy.SheetCopy.row``). Wiersz z siatki (``raw_orders.RowPositions.uncertain``)
ma w Kopii tylko komórki dozwolone w obu położeniach i datę z godziną spod ``DATA GODZ. POCZ.``, a wiersz ze śladem
przesunięcia arkusz ma w ``traced_rows``. Kolumn z aplikacji za ``UWAGI`` Kopia nie ma: Uporządkowanie ich nie
zapisuje, nie mają nagłówka, a jedna z nich u taty niesie części adresu ze słowami sklejonymi ``_``, których strażnik
nie rozpozna jako wartości ``ADRES``. Nad wklejeniem Kopia ma tylko numery ostatniego uporządkowanego i żółtego wiersza
(``raw_orders.above_paste``), od których Planowanie liczy wiersz dnia, bez ich treści (#847).

Części paczki (``RegisterPackage``) czyta tylko pisarz dnia Uporządkowania (``intermax_file``), który przepisuje je
w zapisie.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast
from xml.etree import ElementTree

from openpyxl.styles.fonts import Font
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, from_excel
from openpyxl.workbook.properties import WorkbookProperties

from . import client_data, raw_orders, workbook_files
from .dad_files import DadFiles, ReadFile, SheetMemory
from .raw_orders import SHIFT, CellFacts, OrderColumns, RowFacts, RowPositions
from .register_columns import ACTIVITIES, COLUMNS, CONTRACT_NUMBER, DATE, DAY_FILL, DEVICES, WORKER, Column
from .text import normalize_text
from .workbook_files import header_columns, is_blank
from .workbook_parts import (
    MAIN,
    OFFICE_REL,
    IrregularSheetData,
    RowsFromBottom,
    SheetCell,
    UnsupportedShape,
    office_document,
    relationships,
    row_attributes,
    row_tag,
    shared_string_spans,
    sheet_cells,
    unpacked,
)

__all__ = [
    "DuplicatedHeaders",
    "HeadersProblem",
    "MissingHeaders",
    "NoOrderSheet",
    "OrderSheet",
    "OrderSheets",
    "PasteArea",
    "RecognizedSheet",
    "RegisterFile",
    "RegisterPackage",
    "read",
    "recognize",
]

_FIRST: Final = "AKCJE"
_LAST: Final = "UWAGI"
_HEADER_ROW: Final = re.compile(rb'<row r="1"[^>]*?(?:/>|>.*?</row>)', re.S)
_TEXT: Final = re.compile(rb"<t(?:\s[^>]*)?>([^<]*)</t>")
_PHONETIC: Final = re.compile(rb"<rPh\b.*?</rPh>", re.S)


# --- rozpoznanie arkuszy zleceń ----------------------------------------------------------------


@dataclass(frozen=True)
class NoOrderSheet:
    """Żaden arkusz nie ma w wierszu 1 większości wymaganych nagłówków ``COLUMNS``."""


@dataclass(frozen=True)
class MissingHeaders:
    """Arkusz z większością, ale nie kompletem wymaganych nagłówków: ten, któremu brakuje najmniej, i brakujące."""

    sheet: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class DuplicatedHeaders:
    """Pierwszy arkusz z kompletem nagłówków, w którym wymagany nagłówek (w dowolnym przyjmowanym zapisie) stoi więcej
    niż raz: nie wiadomo, z której kolumny brać dane."""

    sheet: str
    labels: tuple[str, ...]


HeadersProblem = NoOrderSheet | MissingHeaders | DuplicatedHeaders
"""Wiersz 1 Rejestru bez arkusza zleceń, który proces tłumaczy na swój Komunikat."""


@dataclass(frozen=True)
class RecognizedSheet:
    """Arkusz zleceń z rozpoznania: nazwa, kolumna (od 1) każdej kolumny ``COLUMNS`` i każdy nagłówek wiersza 1
    (po ``normalize_text``) z kolumną."""

    name: str
    positions: Mapping[Column, int]
    header: Mapping[str, int]


def recognize(sheets: Iterable[tuple[str, Sequence[object]]]) -> tuple[RecognizedSheet, ...] | HeadersProblem:
    """Arkusze zleceń z wierszy 1 arkuszy (nazwa i wartości od kolumny A, w kolejności skoroszytu), w tej kolejności.

    Arkusz bez większości wymaganych nagłówków (listy, komentarze, ukryte) nie jest arkuszem zleceń. Pierwszy arkusz z
    kompletem i powtórzonym nagłówkiem to ``DuplicatedHeaders``, choćby inne arkusze były dobre. Bez arkusza zleceń:
    arkusz z większością, ale nie kompletem (``MissingHeaders``), albo ``NoOrderSheet``.
    """

    found: list[RecognizedSheet] = []
    closest: MissingHeaders | None = None
    for name, values in sheets:
        header = header_columns(values)
        positions = {column: _position(column, header) for column in COLUMNS}
        missing = tuple(column.label for column, position in positions.items() if position is None)
        if missing:
            if len(missing) < len(COLUMNS) / 2 and (closest is None or len(missing) < len(closest.labels)):
                closest = MissingHeaders(name, missing)
            continue
        duplicated = _duplicated(values)
        if duplicated:
            return DuplicatedHeaders(name, duplicated)
        complete = {column: position for column, position in positions.items() if position is not None}
        found.append(RecognizedSheet(name, MappingProxyType(complete), MappingProxyType(header)))
    if found:
        return tuple(found)
    return closest if closest is not None else NoOrderSheet()


def _position(column: Column, header: Mapping[str, int]) -> int | None:
    return next((header[name] for name in map(normalize_text, column.register_headers) if name in header), None)


def _duplicated(values: Sequence[object]) -> tuple[str, ...]:
    """Kolumny ``COLUMNS``, których nagłówek, w dowolnym przyjmowanym zapisie, występuje więcej niż raz."""

    normalized = [normalize_text(value) for value in values if not is_blank(value)]
    return tuple(
        column.label
        for column in COLUMNS
        if sum(normalized.count(name) for name in set(map(normalize_text, column.register_headers))) > 1
    )


# --- odczyt -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterPackage:
    """Części zip Rejestru w kolejności z pliku i części, które zmienia zapis dnia: skoroszyt, style i arkusze."""

    infos: tuple[zipfile.ZipInfo, ...]
    parts: Mapping[str, bytes]
    workbook_part: str
    styles_part: str
    sheet_parts: tuple[str, ...]


@dataclass(frozen=True)
class OrderSheet:
    """Arkusz zleceń: nazwa i obszar wklejania (``None``: starszy układ bez ``AKCJE`` i ``UWAGI``, do którego aplikacja
    firmowa nie wkleja, więc Surowych zleceń nikt w nim nie szuka)."""

    name: str
    paste: PasteArea | None


@dataclass(frozen=True)
class OrderSheets:
    """Arkusze zleceń Rejestru w kolejności skoroszytu (co najmniej jeden)."""

    sheets: tuple[OrderSheet, ...]

    def paste_areas(self) -> tuple[PasteArea, ...]:
        """Obszary wklejania arkuszy zleceń; arkusz starszego układu żadnego nie ma."""

        return tuple(sheet.paste for sheet in self.sheets if sheet.paste is not None)


@dataclass(frozen=True, eq=False)
class RegisterFile:
    """Rejestr zleceń przeczytany raz: plik z uchwytu (``content`` to jego bajty), rozpoznanie i części paczki."""

    path: Path
    content: bytes = field(repr=False)
    order_sheets: OrderSheets | HeadersProblem
    package: RegisterPackage = field(repr=False)
    _file: ReadFile = field(repr=False)

    def enter_copy(self) -> None:
        """Rejestr w Kopii wejścia uchwytu (bajty z chwilą zmiany sprzed odczytu), także bez arkuszy zleceń."""

        self._file.enter_copy()


def read(path: Path, files: DadFiles, *, despite_excel_lock: bool = False) -> RegisterFile:
    """Rejestr ``path`` uchwytem ``files``; ``WorkbookError``, gdy go nie ma, jest otwarty w Excelu, niedostępny albo
    nieczytelny. ``despite_excel_lock``: Rejestr otwarty w Excelu to jego ostatnia zapisana wersja, a nie
    ``WorkbookError``."""

    file = files.read(path, despite_excel_lock=despite_excel_lock)
    with workbook_files.unreadable_as_error(file.path):
        infos, parts = unpacked(file.content)
        workbook = office_document(parts)
        if workbook is None:
            raise KeyError("officeDocument")
        rels = relationships(parts, workbook)
        root = ElementTree.fromstring(parts[workbook])
        styles = next((rel.target for rel in rels.values() if rel.kind.endswith("/styles")), None)
        if styles is None:
            raise KeyError("styles")
        strings = next((rel.target for rel in rels.values() if rel.kind.endswith("/sharedStrings")), None)
        properties = root.find(f"{MAIN}workbookPr")
        date1904 = properties is not None and cast(WorkbookProperties, WorkbookProperties.from_tree(cast(Any, properties))).date1904
        values = _Values(
            _ReadStyles.of(parts[styles]),
            _SharedStrings(parts[strings] if strings else b"<sst/>"),
            MAC_EPOCH if date1904 else WINDOWS_EPOCH,
        )
        sheets = [
            (sheet.get("name", ""), rels[sheet.get(f"{{{OFFICE_REL}}}id", "")].target)
            for sheet in root.iter(f"{MAIN}sheet")
        ]
        headers = [values.header(parts[part]) for _, part in sheets]
    package = RegisterPackage(infos, parts, workbook, styles, tuple(part for _, part in sheets))
    recognized = recognize((name, header) for (name, _), header in zip(sheets, headers, strict=True))
    if not isinstance(recognized, tuple):
        return RegisterFile(file.path, file.content, recognized, package, file)
    by_name = {name: (part, header) for (name, part), header in zip(sheets, headers, strict=True)}
    order_sheets = tuple(
        OrderSheet(sheet.name, _paste_area(sheet, *by_name[sheet.name], parts, values, file)) for sheet in recognized
    )
    return RegisterFile(file.path, file.content, OrderSheets(order_sheets), package, file)


def _paste_area(
    sheet: RecognizedSheet,
    part: str,
    header: Sequence[object],
    parts: Mapping[str, bytes],
    values: _Values,
    file: ReadFile,
) -> PasteArea | None:
    first, last = sheet.header.get(normalize_text(_FIRST)), sheet.header.get(normalize_text(_LAST))
    if first is None or last is None:
        return None
    positions = sheet.positions
    columns = OrderColumns(
        first,
        positions[DATE],
        positions[WORKER],
        last,
        devices=positions[DEVICES],
        activities=positions[ACTIVITIES],
        contract_number=positions[CONTRACT_NUMBER],
    )
    return PasteArea(sheet.name, part, columns, header, parts[part], values, file)


class PasteArea:
    """Obszar wklejania arkusza zleceń (od ``AKCJE`` do ``UWAGI``) czytany od dołu: fakty wierszy, pamięć i Kopia."""

    def __init__(
        self,
        sheet: str,
        part: str,
        columns: OrderColumns,
        header: Sequence[object],
        xml: bytes,
        values: _Values,
        file: ReadFile,
    ) -> None:
        self.sheet = sheet
        self.part = part
        self.columns = columns
        self._header = header
        self._xml = xml
        self._values = values
        self._file = file
        self._facts_read: dict[int, RowFacts] = {}
        """Numer wiersza → fakty wiersza, który któryś przegląd arkusza od dołu już przeczytał, liczone raz."""

    @cached_property
    def sheet_xml(self) -> RowsFromBottom:
        """XML arkusza z wierszami od dołu, dzielonymi raz; ``UnsupportedShape``, gdy ``<sheetData>`` jest nie jeden."""

        try:
            return RowsFromBottom(self._xml)
        except IrregularSheetData as error:
            raise UnsupportedShape(str(error)) from error

    @cached_property
    def _forbidden_columns(self) -> tuple[tuple[client_data.ForbiddenColumn, int], ...]:
        return client_data.forbidden_columns(header_columns(self._header))

    @cached_property
    def _memory(self) -> SheetMemory:
        return self._file.memory(self._forbidden_columns)

    @cached_property
    def _shifted_row(self) -> int | None:
        return raw_orders.shifted_row(self._facts_from_bottom(), self.columns)

    def rows_from_bottom(self) -> Iterator[RowFacts]:
        """Wiersze arkusza od ostatniego do drugiego jako fakty dla rozpoznania Surowych zleceń.

        Komórki ``ADRES`` i ``NUMER UMOWY`` każdego oddanego wiersza poznaje pamięć reguły danych uchwytu w położeniach
        z ``raw_orders.row_positions``: pierwszy wiersz każdego bloku wklejenia (``raw_orders.first_in_block``, także
        nad uporządkowanymi) o ``SHIFT`` kolumn na lewo od nagłówka, każdy inny pod nim, a wiersz z siatki w obu.
        ``UnsupportedShape``, gdy przeczytanych wierszy nie da się rozdzielić.
        """

        memory, columns, shifted = self._memory, self.columns, self._shifted_row
        for facts, first in raw_orders.first_in_block(self._facts_from_bottom(), lambda row: raw_orders.look(row, columns)):
            memory.remember(_values(facts), self._positions(facts, first, shifted))
            yield facts

    def copy_paste(self) -> None:
        """Arkusz w Kopii wejścia uchwytu: nagłówki i wklejone wiersze z komórkami od A do ``UWAGI``, tymi, które
        Uporządkowanie przenosi do dnia, bez zakazanych kolumn (``input_copy.SheetCopy.row``). Z dołu arkusza Kopia
        dostaje też numery ostatniego uporządkowanego i żółtego wiersza (``raw_orders.above_paste``), bez ich treści
        (#847).

        Arkusza, którego wierszy nie da się rozdzielić (``UnsupportedShape``), Kopia nie dostaje wcale: Komunikat o nim
        daje Planowanie, więc Kopia nie zmienia Zatrzymania.
        """

        columns = self.columns
        try:
            shifted = self._shifted_row
            pasted = raw_orders.pasted_rows(self.rows_from_bottom(), columns)
            above = raw_orders.above_paste(self._facts_from_bottom(), columns)
        except UnsupportedShape:
            return
        copied = range(1, columns.last + 1)
        header = self._header
        sheet = self._file.sheet(
            self.sheet,
            1,
            {column: header[column - 1] for column in copied if column <= len(header)},
            self._forbidden_columns,
            copied_columns=copied,
            date_column=columns.date,
            last_ordered_row=above.last_ordered,
            yellow_row=above.yellow,
        )
        for facts in pasted:
            sheet.row(facts.number, _values(facts), self._positions(facts, facts is pasted[0], shifted))

    def _positions(self, facts: RowFacts, first: bool, shifted: int | None) -> RowPositions:
        """Położenia wiersza ``facts`` (``raw_orders.row_positions``); ``first``: pierwszy wiersz bloku wklejenia,
        ``shifted``: wiersz, który rozpoznanie czyta przesunięty (``raw_orders.shifted_row``)."""

        columns = self.columns
        return raw_orders.row_positions(
            first=first,
            left_of_date=facts.value(columns.date - SHIFT),
            date=facts.value(columns.date),
            read=SHIFT if facts.number == shifted else 0,
        )

    def _facts_from_bottom(self) -> Iterator[RowFacts]:
        """Fakty wierszy od dołu; ``UnsupportedShape``, gdy przeczytanych wierszy nie da się rozdzielić."""

        sheet, read = self.sheet_xml, self._facts_read
        try:
            for row in sheet:
                if row.number < 2:
                    return
                facts = read.get(row.number)
                if facts is None:
                    facts = read[row.number] = self._values.facts(
                        row_tag(sheet.xml, row), row.number, sheet_cells(sheet.xml[row.start : row.end])
                    )
                yield facts
        except IrregularSheetData as error:
            raise UnsupportedShape(str(error)) from error


def _values(facts: RowFacts) -> dict[int, object]:
    return {column: cell.value for column, cell in facts.cells.items()}


# --- wartości komórek ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReadStyles:
    """Style komórek z ``xl/styles.xml``, które czyta rozpoznanie: format liczby, czcionka i żółte wypełnienie."""

    number_formats: tuple[int, ...]
    faces: tuple[tuple[str | None, float | None], ...]
    yellow: tuple[bool, ...]
    date_formats: frozenset[int]

    @classmethod
    def of(cls, xml: bytes) -> _ReadStyles:
        root = ElementTree.fromstring(xml)
        codes = {int(item.get("numFmtId", "0")): item.get("formatCode", "") for item in root.iter(f"{MAIN}numFmt")}
        faces = [_face(Font.from_tree(cast(Any, font))) for font in root.iterfind(f"{MAIN}fonts/{MAIN}font")]
        fills = [_is_yellow(fill) for fill in root.iterfind(f"{MAIN}fills/{MAIN}fill")]
        xfs = list(root.iterfind(f"{MAIN}cellXfs/{MAIN}xf"))
        number_formats = tuple(int(xf.get("numFmtId", "0")) for xf in xfs)
        return cls(
            number_formats=number_formats,
            faces=tuple(faces[int(xf.get("fontId", "0"))] for xf in xfs),
            yellow=tuple(fills[int(xf.get("fillId", "0"))] for xf in xfs),
            date_formats=frozenset(
                number for number in number_formats if is_date_format(codes.get(number) or BUILTIN_FORMATS.get(number, ""))
            ),
        )


def _face(font: Font) -> tuple[str | None, float | None]:
    return font.name, font.sz


def _is_yellow(fill: ElementTree.Element) -> bool:
    color = fill.find(f"{MAIN}patternFill[@patternType='solid']/{MAIN}fgColor")
    return color is not None and color.get("rgb", "").upper().endswith(DAY_FILL)


class _SharedStrings:
    """Teksty wspólne bez podpowiedzi wymowy (``rPh``): zwykły tekst albo tekst każdego fragmentu.

    Tekst powstaje dopiero, gdy komórka po niego sięga: INTERMAX taty ma dziesiątki tysięcy tekstów wspólnych, a
    Uporządkowanie czyta kilkaset wierszy z dołu arkusza. Granice ``<si>`` daje ``shared_string_spans``: zepsuta część
    to ``ExpatError``, a tabela w kształcie, którego granic nie zna, ``ValueError``, czyli w obu przypadkach nieczytelny
    INTERMAX.
    """

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
            self._texts[index] = html.unescape(b"".join(_TEXT.findall(item)).decode("utf-8"))
        return self._texts[index]


@dataclass(frozen=True)
class _Values:
    """Wartości i fakty komórek Rejestru: style, teksty wspólne i początek systemu dat skoroszytu."""

    styles: _ReadStyles
    shared: _SharedStrings
    epoch: datetime

    def header(self, xml: bytes) -> list[object]:
        """Wartości wiersza 1 arkusza od kolumny A; arkusz bez wiersza 1 nie ma żadnych."""

        header_row = _HEADER_ROW.search(xml)
        if header_row is None:
            return []
        cells = sheet_cells(header_row.group(0))
        header: list[object] = [None] * max((cell.column for cell in cells), default=0)
        for cell in cells:
            header[cell.column - 1] = self.value(cell)
        return header

    def value(self, cell: SheetCell) -> object:
        """Wartość komórki: tekst (także prawda/fałsz jako 1 i 0), liczba, data w formacie daty; ``None`` dla pustej."""

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
                if self.styles.number_formats[cell.style] in self.styles.date_formats:
                    return from_excel(number, self.epoch)
                return number
            else:
                text = html.unescape(raw)
        return None if is_blank(text) else text

    def facts(self, tag: bytes, number: int, cells: Sequence[SheetCell]) -> RowFacts:
        styles = self.styles
        attributes = row_attributes(tag)
        row_style = attributes.get(b"s") if attributes.get(b"customFormat") == b"1" else None
        return RowFacts(
            number,
            {cell.column: CellFacts(self.value(cell), styles.faces[cell.style], styles.yellow[cell.style]) for cell in cells},
            row_style is not None and styles.yellow[int(row_style)],
        )
