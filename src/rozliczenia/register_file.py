"""Rejestr zleceń (INTERMAX) czytany raz: rozpoznanie arkuszy zleceń i dwa obiektywy tych samych bajtów, fakty wierszy
od dołu bez openpyxl i wiersze okresu w openpyxl.

Skoroszyt bez dokumentu skoroszytu, bez części stylów albo bez arkusza jest nieczytelny (``WorkbookError``), jak zepsuty
zip albo XML: Excel takiego nie zapisuje, a openpyxl go nie otwiera.

Arkusz zleceń rozpoznaje jedna reguła dla obu procesów (``recognize``): komplet nagłówków ``COLUMNS`` w wierszu 1
(każdy w którymś przyjmowanym zapisie) i żaden z nich więcej niż raz. Wynik to wartość, a nie wyjątek: arkusze zleceń
(``OrderSheets``) albo problem nagłówków (``HeadersProblem``), który każdy proces tłumaczy na swój Komunikat. Arkusz
zleceń z ``AKCJE`` i ``UWAGI`` ma obszar wklejania (``PasteArea``), do którego aplikacja firmowa wkleja Surowe zlecenia
i który porządkuje Uporządkowanie INTERMAX. Arkusz starszego układu, bez tych kolumn, obszaru nie ma
(``OrderSheet.paste`` to ``None``): aplikacja do niego nie wkleja, więc Surowych zleceń nikt w nim nie szuka.

Obszar wklejania daje swoje wiersze od dołu jako fakty (``raw_orders.RowFacts``): ~42 tys. wierszy taty to dziesiątki MB
XML, a rozpoznanie potrzebuje tylko dołu arkusza. Komórki ``ADRES`` i ``NUMER UMOWY`` każdego oddanego wiersza poznaje
pamięć reguły danych uchwytu (ADR 0025) w jego położeniach (``raw_orders.row_positions``). Zakazane kolumny to te z
nagłówkiem zakazanej kolumny w wierszu 1 (``client_data.forbidden_columns``): INTERMAX nie ma stałego układu kolumn,
więc kolumnę zna się po nagłówku, tak jak kolumny ``COLUMNS``.

Wiersze okresu (``OrderSheets.period_rows``) czyta openpyxl ze skoroszytu zawężonego do okresu po kolumnach daty z
rozpoznania (``workbook_parts.rows_dated_between``), bo wartości, Wyróżnienia, formaty i Hiperłącza tych wierszy
Przygotowanie pliku zbiorczego przenosi do plików okresu. Ich pamięć i Kopię prowadzi ta sama reguła położenia, a
pierwszy wiersz bloku daje ``raw_orders.first_in_block`` na wierszach okna od dołu.

Kopia wejścia Uruchomienia z Centrum (#841, #842) dostaje bajty Rejestru z chwilą zmiany sprzed odczytu zaraz po
odczycie, a z każdego obszaru wklejania nagłówki i wklejenie (``raw_orders.pasted_rows``): te same fakty wierszy, które
rozpoznaje Planowanie, nie cały Rejestr. Wiersz ma w Kopii komórki od A do ``UWAGI``, te, które Uporządkowanie przenosi
do dnia, pod nagłówkiem, pod którym czyta je rozpoznanie, także przesunięty pierwszy wiersz, bez zakazanych kolumn
(``input_copy.SheetCopy.row``). Wiersz z siatki (``row_positions.RowPositions.uncertain``) ma w Kopii tylko komórki
dozwolone w obu położeniach i datę z godziną spod ``DATA GODZ. POCZ.``, a wiersz ze śladem przesunięcia arkusz ma w
faktach wklejenia (``input_copy.PasteFacts.traced_rows``). Kolumn z aplikacji za ``UWAGI`` Kopia nie ma: Uporządkowanie
ich nie zapisuje, nie mają nagłówka, a jedna z nich u taty niesie części adresu ze słowami sklejonymi ``_``, których
strażnik nie rozpozna jako wartości ``ADRES``. Nad wklejeniem Kopia ma tylko numery ostatniego uporządkowanego i żółtego
wiersza (``raw_orders.above_paste``), od których Planowanie liczy wiersz dnia, bez ich treści (#847). Wpisanie raportów
daje Kopii zamiast wklejenia uporządkowane wiersze, które przeczytało (``PasteArea.copy_rows``), w tych samych kolumnach
i bez zakazanych kolumn.

Części paczki (``RegisterPackage``) czyta tylko pisarz dnia Uporządkowania (``intermax_file``), który przepisuje je
w zapisie.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property, lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, NamedTuple, cast
from xml.etree import ElementTree

from openpyxl.styles.fonts import Font
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, from_excel
from openpyxl.workbook.properties import WorkbookProperties
from openpyxl.worksheet.worksheet import Worksheet

from . import client_data, raw_orders, workbook_files
from .dad_files import DadFiles, ReadFile, SheetMemory
from .highlights import LookReader
from .hyperlinks import read_sheet_hyperlinks
from .raw_orders import SHIFT, CellFacts, OrderColumns, RowFacts, RowLook
from .register_columns import ACTIVITIES, COLUMNS, CONTRACT_NUMBER, DATE, DAY_FILL, DEVICES, TARGET_HEADERS, WORKER, Column
from .row_look import GENERAL
from .row_positions import RowPositions
from .settlement_period import SettlementPeriod
from .text import normalize_text
from .workbook_files import DataCell, RegisterRow, header_columns, is_blank
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
    rows_dated_between,
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
    "RegisterSheet",
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
    """Arkusz zleceń: nazwa, kolumna (od 1) każdej kolumny ``COLUMNS``, wartości wiersza 1 od kolumny A i obszar
    wklejania (``None``: starszy układ bez ``AKCJE`` i ``UWAGI``, do którego aplikacja firmowa nie wkleja, więc Surowych
    zleceń nikt w nim nie szuka)."""

    name: str
    positions: Mapping[Column, int]
    header: tuple[object, ...] = field(repr=False)
    paste: PasteArea | None

    @property
    def look_columns(self) -> frozenset[int]:
        """Kolumny, z których krój wiersza mówi, czy jest uporządkowany: ``OrderColumns.look_columns`` obszaru
        wklejania, a w starszym układzie kolumny ``COLUMNS`` bez ``WYKONAWCA``."""

        if self.paste is not None:
            return self.paste.columns.look_columns
        return frozenset(self.positions.values()) - {self.positions[WORKER]}


@dataclass(frozen=True, eq=False)
class OrderSheets:
    """Arkusze zleceń Rejestru w kolejności skoroszytu (co najmniej jeden) z obu obiektywów: obszary wklejania od dołu
    (``paste_areas``) i wiersze okresu (``period_rows``)."""

    sheets: tuple[OrderSheet, ...]
    _file: ReadFile = field(repr=False)
    _epoch: datetime = field(repr=False)

    def paste_areas(self) -> tuple[PasteArea, ...]:
        return tuple(sheet.paste for sheet in self.sheets if sheet.paste is not None)

    def period_rows(self, period: SettlementPeriod | None) -> tuple[RegisterSheet, ...]:
        """Arkusze zleceń z wierszami od pierwszego do ostatniego, którego data może leżeć w ``period``; bez ``period``
        z każdym wierszem od 2. ``WorkbookError``, gdy openpyxl nie przeczyta skoroszytu albo wiersza.

        Każdy wiersz z danymi zna pamięć reguły danych uchwytu w położeniach z ``raw_orders.row_positions``, z pierwszym
        wierszem bloku wklejenia z ``raw_orders.first_in_block`` na wierszach odczytu od dołu, więc wiersz na górze
        odczytu bez wiersza nad nim jest pierwszy. Kopia wejścia ma nagłówki wiersza 1 kolumn wklejenia od A do
        ``UWAGI`` (w starszym układzie do ostatniej kolumny ``COLUMNS``) i każdy wiersz z danymi z komórkami kolumn
        ``COLUMNS`` według jego położeń (``input_copy.SheetCopy.row``): komórka wiersza z siatki albo przesuniętego
        pierwszego wiersza jest w Kopii, gdy w każdym jego położeniu stoi w kolumnie wklejenia, tak jak w
        Uporządkowaniu, a nie pod zakazaną kolumną. Kopia ma też puste wiersze odczytanego zakresu i wiersze ze śladem
        przesunięcia.
        """

        file = self._file
        sheets = tuple(
            (sheet.name, tuple(sheet.positions[column] for column in COLUMNS), tuple(sorted(sheet.look_columns)))
            for sheet in self.sheets
        )
        if period is None:
            windows = _windows(file.path, file.content, sheets, {})
        else:
            windows = _period_read(file.path, file.content, sheets, self._epoch, period)
        for sheet, window in zip(self.sheets, windows, strict=True):
            positions = sheet.positions
            header = sheet.header
            last = header_columns(header).get(normalize_text(_LAST), max(positions.values()))
            span = range(1, max(last, *positions.values()) + 1)
            witnessed = file.sheet(
                sheet.name,
                1,
                {column: header[column - 1] for column in span if column <= len(header)},
                _forbidden_positions(positions),
                copied_columns=positions.values(),
                date_column=positions[DATE],
                span=span,
            )
            for row in window.rows:
                witnessed.row(row.number, row.values, row.positions)
            witnessed.empty_rows(window.sheet.empty_rows)
        return tuple(window.sheet for window in windows)


@dataclass(frozen=True, eq=False)
class RegisterFile:
    """Rejestr zleceń przeczytany raz: plik z uchwytu (``content`` to jego bajty), rozpoznanie i części paczki."""

    path: Path
    content: bytes = field(repr=False)
    order_sheets: OrderSheets | HeadersProblem
    package: RegisterPackage = field(repr=False)


def read(path: Path, files: DadFiles, *, despite_excel_lock: bool = False) -> RegisterFile:
    """Rejestr ``path`` uchwytem ``files``; ``WorkbookError``, gdy go nie ma, jest otwarty w Excelu, niedostępny albo
    nieczytelny. ``despite_excel_lock``: Rejestr otwarty w Excelu to jego ostatnia zapisana wersja, a nie
    ``WorkbookError``. Przeczytany Rejestr jest w Kopii wejścia uchwytu (bajty z chwilą zmiany sprzed odczytu), także bez
    arkuszy zleceń, więc Logi Uruchomienia zatrzymanego na nim mają jego odcisk."""

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
        if not sheets:
            raise KeyError("sheet")
        headers = [values.header(parts[part]) for _, part in sheets]
    package = RegisterPackage(infos, parts, workbook, styles, tuple(part for _, part in sheets))
    file.enter_copy()
    recognized = recognize((name, header) for (name, _), header in zip(sheets, headers, strict=True))
    if not isinstance(recognized, tuple):
        return RegisterFile(file.path, file.content, recognized, package)
    by_name = {name: (part, header) for (name, part), header in zip(sheets, headers, strict=True)}
    order_sheets = tuple(
        OrderSheet(
            sheet.name,
            sheet.positions,
            tuple(by_name[sheet.name][1]),
            _paste_area(sheet, *by_name[sheet.name], parts, values, file),
        )
        for sheet in recognized
    )
    return RegisterFile(file.path, file.content, OrderSheets(order_sheets, file, values.epoch), package)


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
        """XML arkusza z wierszami od dołu; ``UnsupportedShape``, gdy ``<sheetData>`` jest nie jeden."""

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

        Pamięć reguły danych uchwytu zna każdy oddany wiersz w położeniach z ``raw_orders.row_positions``, z pierwszym
        wierszem każdego bloku wklejenia z ``raw_orders.first_in_block``, także nad uporządkowanymi.
        ``UnsupportedShape``, gdy przeczytanych wierszy nie da się rozdzielić.
        """

        memory, columns, shifted = self._memory, self.columns, self._shifted_row
        for facts, first in raw_orders.first_in_block(self._facts_from_bottom(), lambda row: raw_orders.look(row, columns)):
            memory.remember(_values(facts), self._positions(facts, first, shifted))
            yield facts

    def copy_paste(self) -> None:
        """Arkusz w Kopii wejścia uchwytu: nagłówki, wklejone wiersze i numery wierszy nad wklejeniem (zob. docstring
        modułu).

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
            above=above,
        )
        for facts in pasted:
            sheet.row(facts.number, _values(facts), self._positions(facts, facts is pasted[0], shifted))

    def copy_rows(self, rows: Sequence[RowFacts]) -> None:
        """Arkusz w Kopii wejścia uchwytu z nagłówkami i wierszami ``rows`` (uporządkowanymi wierszami, które
        przeczytało Wpisanie raportów), w kolumnach od A do ``UWAGI`` bez zakazanych kolumn (ADR 0025)."""

        columns = self.columns
        copied = range(1, columns.last + 1)
        header = self._header
        sheet = self._file.sheet(
            self.sheet,
            1,
            {column: header[column - 1] for column in copied if column <= len(header)},
            self._forbidden_columns,
            copied_columns=copied,
            date_column=columns.date,
        )
        for facts in rows:
            sheet.row(facts.number, _values(facts), self._positions(facts, False, None))

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


# --- obiektyw okresu ----------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterSheet:
    """Arkusz zleceń w Odczycie danych Przygotowania: wiersze z danymi i numery całkowicie pustych wierszy z odczytanego
    zakresu."""

    name: str
    register_rows: tuple[RegisterRow, ...]
    """Wiersze z danymi; komórki pod nagłówkiem docelowym."""
    empty_rows: tuple[int, ...]
    _positions: tuple[int, ...]  # numery kolumn ``COLUMNS`` w arkuszu (od 1)

    def column_letter(self, column: Column) -> str:
        """Litera kolumny arkusza z nagłówkiem ``column``, np. ``L`` dla ``SKUTECZNE``."""

        return get_column_letter(self._positions[COLUMNS.index(column)])

    @property
    def positions(self) -> dict[Column, int]:
        """Kolumna ``COLUMNS`` → jej numer w arkuszu (od 1)."""

        return dict(zip(COLUMNS, self._positions, strict=True))


_SheetsKey = tuple[tuple[str, tuple[int, ...], tuple[int, ...]], ...]
"""Arkusze zleceń: nazwa, numery kolumn ``COLUMNS`` (od 1) i kolumny wyglądu (``OrderSheet.look_columns``)."""


class _ReadRow(NamedTuple):
    """Wiersz okna: wartości całego wiersza od A, wiersz z komórkami pod nagłówkiem docelowym i czy ma wygląd
    uporządkowany."""

    values: tuple[object, ...]
    row: RegisterRow
    ordered: bool


@dataclass(frozen=True)
class _WindowRow:
    number: int
    values: tuple[object, ...]
    positions: RowPositions


@dataclass(frozen=True)
class _Window:
    """Arkusz okna i jego wiersze z danymi z położeniami, które poznają pamięć i Kopia."""

    sheet: RegisterSheet
    rows: tuple[_WindowRow, ...]


# Centrum robi Podgląd, a potem RUN tego samego okresu w jednym procesie. Okno zależy tylko od bajtów Rejestru, arkuszy
# zleceń i okresu, więc niezmieniony Rejestr nie jest drugi raz zawężany ani parsowany, a zmieniony jest czytany od nowa.
# Uruchomienia w różnych wątkach dostają ten sam wynik, więc jest z krotek, zamrożonych dataclass i map w
# ``MappingProxyType``. Wyjątek to wypełnienie i kolor Wyróżnień: obiekty openpyxl, których nie da się zamrozić, więc
# Zapis nakłada tylko ich kopie (``Highlights.font_over``, ``Highlights.fill_over``, ``RowLook``).
@lru_cache(maxsize=2)
def _period_read(
    path: Path, content: bytes, sheets: _SheetsKey, epoch: datetime, period: SettlementPeriod
) -> tuple[_Window, ...]:
    # Liczba dni od początku systemu dat skoroszytu (1900 albo 1904), z dniem zapasu z obu stron: openpyxl
    # zaokrągla część dnia do milisekund. Wiersz zakresu z datą spoza przedziału czytający i tak pomija.
    day = timedelta(days=1)
    low, high = ((moment - epoch) / day for moment in (period.start - day, period.end + day))
    dates = {name: columns[COLUMNS.index(DATE)] for name, columns, _ in sheets}
    with workbook_files.unreadable_as_error(path):
        narrowed, ranges = rows_dated_between(content, dates, low, high)
    return _windows(path, narrowed, sheets, ranges)


def _windows(path: Path, content: bytes, sheets: _SheetsKey, ranges: Mapping[str, range]) -> tuple[_Window, ...]:
    """Okno każdego arkusza zleceń w openpyxl z bajtów ``content``: wiersze z ``ranges`` (od 2), a arkusz bez zakresu
    od wiersza 2 do końca."""

    with workbook_files.open_workbook(path, content, read_only=True) as workbook:  # noqa: TID251 - okna arkuszy zleceń Rejestru z bajtów, które przeczytał uchwyt
        windows = []
        for name, columns, look_columns in sheets:
            with workbook_files.unreadable_as_error(path):
                sheet = cast(Worksheet, workbook[name])
            read = list(workbook_files.classified(path, _read_rows(content, sheet, columns, look_columns, ranges.get(name))))
            windows.append(_window(name, columns, read))
        return tuple(windows)


def _read_rows(
    content: bytes, sheet: Worksheet, columns: Sequence[int], look_columns: Sequence[int], rows: range | None
) -> Iterator[_ReadRow]:
    """Wiersze arkusza od 2 (w zakresie ``rows``, gdy jest): komórki ``COLUMNS`` z wartością, Wyróżnieniami tej samej
    reguły co w Pliku zbiorczym (``highlights.LookReader``), formatem liczby (ogólnym dla brakującej komórki) i
    Hiperłączem, a wiersz z tym, czy jest uporządkowany (``raw_orders.ordered_look`` na komórkach z wartością w
    ``look_columns``)."""

    min_row, max_row = 2, None
    if rows is not None:
        min_row, max_row = max(min_row, rows.start), rows.stop - 1
        if min_row > max_row:
            return
    targets = {header: columns[index] for index, header in enumerate(TARGET_HEADERS)}
    links = read_sheet_hyperlinks(content, sheet.title)
    highlights = LookReader()
    for number, cells in enumerate(sheet.iter_rows(min_row=min_row, max_row=max_row), start=min_row):
        values = tuple(getattr(cell, "value", None) for cell in cells)
        row_links = links.row(number, values)
        picked = {header: cells[column - 1] if column <= len(cells) else None for header, column in targets.items()}
        looks = {header: highlights.of(cell) for header, cell in picked.items()}
        row = RegisterRow(
            number,
            MappingProxyType(
                {
                    header: DataCell(
                        getattr(cell, "value", None),
                        looks[header],
                        getattr(cell, "number_format", None) or GENERAL,
                        row_links.get(targets[header]),
                    )
                    for header, cell in picked.items()
                }
            ),
        )
        faces = (
            highlights.look(cells[column - 1])[1]
            for column in look_columns
            if column <= len(cells) and not is_blank(values[column - 1])
        )
        yield _ReadRow(values, row, raw_orders.ordered_look(faces))


def _window(name: str, columns: Sequence[int], read: Sequence[_ReadRow]) -> _Window:
    looks = {found.row.number: _look(found) for found in read}
    firsts = {
        found.row.number: first
        for found, first in raw_orders.first_in_block(reversed(read), lambda found: looks[found.row.number])
    }
    date = columns[COLUMNS.index(DATE)]
    rows = [found for found in read if looks[found.row.number] is not RowLook.BLANK]
    return _Window(
        RegisterSheet(
            name,
            tuple(found.row for found in rows),
            tuple(found.row.number for found in read if looks[found.row.number] is RowLook.BLANK),
            tuple(columns),
        ),
        tuple(
            _WindowRow(
                found.row.number,
                found.values,
                raw_orders.row_positions(
                    first=firsts[found.row.number],
                    left_of_date=_value_at(found.values, date - SHIFT),
                    date=_value_at(found.values, date),
                ),
            )
            for found in rows
        ),
    )


def _look(found: _ReadRow) -> RowLook:
    if all(is_blank(value) for value in found.values):
        return RowLook.BLANK
    return RowLook.ORDERED if found.ordered else RowLook.APP


def _forbidden_positions(positions: Mapping[Column, int]) -> tuple[tuple[client_data.ForbiddenColumn, int], ...]:
    """Zakazane kolumny arkusza zleceń wśród kolumn ``COLUMNS`` z ich numerem w arkuszu."""

    return client_data.forbidden_columns({normalize_text(column.target_header): positions[column] for column in COLUMNS})


def _value_at(values: Sequence[object], column: int) -> object:
    return values[column - 1] if 1 <= column <= len(values) else None


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
