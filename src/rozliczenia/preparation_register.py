"""Rejestr zleceń w Przygotowaniu pliku zbiorczego: dostępność i odczyt (etap Odczyt danych).

Rejestr jest tylko czytany, przez moduł skoroszytu. Arkusze ze zleceniami są rozpoznawane po komplecie
wymaganych nagłówków w pierwszym wierszu, a komórki z wartościami, Wyróżnieniami i Hiperłączami
są zwracane pod nagłówkiem docelowym każdej kolumny ``COLUMNS``. Dla okresu czytane są tylko wiersze
od pierwszego do ostatniego, którego data może leżeć w okresie. ``read_register`` to produkcyjny czytnik
Rejestru dla ``input_checks.Readers``, który tłumaczy jego ``WorkbookError``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from openpyxl.utils import get_column_letter

from . import preparation_messages as messages
from . import workbook_files
from .message import StopError
from .settlement_period import SettlementPeriod
from .workbook_files import ReadWorkbook, RegisterRow, header_columns, is_blank
from .worker_config import normalize_text


@dataclass(frozen=True)
class Column:
    """Kolumna przenoszona z Rejestru zleceń; nagłówek docelowy jest szukany we wzorcach.

    Pary różniące się zapisem są jawne; nagłówek Rejestru nigdy nie zastępuje
    nagłówka docelowego. ``register_header`` to zapis z nowego Rejestru taty;
    kolumna może mieć w Rejestrze drugi przyjmowany zapis ze starszej kopii.
    Nagłówki są porównywane bez względu na wielkość liter, więc zapis różniący
    się tylko nią (``adres``) nie jest osobną alternatywą.
    """

    register_header: str
    target_header: str
    alternative_register_headers: tuple[str, ...] = ()

    @property
    def register_headers(self) -> tuple[str, ...]:
        return (self.register_header, *self.alternative_register_headers)

    @property
    def label(self) -> str:
        """Nagłówek w komunikacie: wszystkie przyjmowane zapisy."""

        return " albo ".join(self.register_headers)


DATE = Column("DATA GODZ. POCZ.", "DATA")
ADDRESS = Column("ADRES", "ADRES")
WORKER = Column("WYKONAWCA", "WYKONAWCA")
SUCCESSFUL = Column("SKUTECZNE", "SKUTECZNE")
CONTRACT = Column("UMOWA", "UMOWA")
DEVICES = Column("URZĄDZENIA", "URZĄDZENIA")
ACTIVITIES = Column("CZYNNOŚCI", "CZYNNOŚCI")
COMPLETED = Column("CZYNNOŚCI ZREALIZOWANE", "CZYNNOŚCI ZREALIZOWANE")
COLUMNS: tuple[Column, ...] = (
    DATE,
    Column("MIASTO", "MIASTO"),
    ADDRESS,
    CONTRACT,
    DEVICES,
    ACTIVITIES,
    Column("NUMER ZL.", "NUMER ZL.", ("nr zlecenia",)),
    WORKER,
    Column("NUMER UMOWY", "NUMER UMOWY/ZLECENIA ORANGE", ("NUMER UMOWY/ZLECENIA ORANGE",)),
    SUCCESSFUL,
    Column("CZYNNOŚCI ZREALIZOWANE", "CZYNNOŚCI ZREALIZOWANE"),
)
TARGET_HEADERS: tuple[str, ...] = tuple(column.target_header for column in COLUMNS)
"""Nagłówki docelowe obu plików okresu, pod którymi stają komórki wiersza Rejestru."""


@dataclass(frozen=True)
class RegisterSheet:
    """Arkusz ze zleceniami: wiersze z danymi i numery całkowicie pustych wierszy z odczytanego zakresu."""

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


@dataclass(frozen=True)
class RegisterRead:
    """Odczyt Rejestru zleceń: arkusze ze zleceniami i bajty pliku, z których czytnik je przeczytał (odcisk w Kopii
    wejścia, ``input_copy``)."""

    sheets: list[RegisterSheet]
    content: bytes = field(repr=False)


def cell_value(row: RegisterRow, column: Column) -> object:
    """Wartość komórki Rejestru pod nagłówkiem ``column`` w wierszu ``row``."""

    return row.cells[column.target_header].value


def read_register(register_path: Path, period: SettlementPeriod | None = None) -> RegisterRead:
    """Arkusze ze zleceniami z bajtami Rejestru, z których je przeczytał; ``WorkbookError``, gdy Rejestru nie da się
    odczytać, i zatrzymanie, gdy nie ma nagłówków.

    Z ``period`` arkusz ma tylko wiersze od pierwszego do ostatniego, którego data
    może leżeć w okresie: Planowanie szuka zleceń okresu i wierszy bez daty tylko
    między pierwszym a ostatnim zleceniem okresu. Bez ``period`` ma wszystkie wiersze.
    """

    content = workbook_files.workbook_content(register_path)
    if period is None:
        with workbook_files.read_workbook(register_path, content) as workbook:
            return RegisterRead(_read_register_sheets(workbook, _order_sheet_positions(register_path, workbook)), content)
    return RegisterRead(list(_period_sheets(register_path, content, period)), content)


# Centrum robi Podgląd, a potem RUN tego samego okresu w jednym procesie. Arkusze okresu zależą tylko od bajtów
# Rejestru i okresu, więc niezmieniony Rejestr nie jest drugi raz zawężany ani parsowany, a zmieniony jest
# czytany od nowa. Uruchomienia w różnych wątkach dostają ten sam wynik, więc jest z krotek, zamrożonych dataclass
# i map w ``MappingProxyType``. Wyjątek to wypełnienie i kolor Wyróżnień: obiekty openpyxl, których nie da się
# zamrozić, więc Zapis nakłada tylko ich kopie (``Highlights.font_over``, ``Highlights.fill_over``, ``RowLook``).
@lru_cache(maxsize=2)
def _period_sheets(register_path: Path, content: bytes, period: SettlementPeriod) -> tuple[RegisterSheet, ...]:
    with workbook_files.read_workbook(register_path, content) as workbook:
        positions = _order_sheet_positions(register_path, workbook)
        date_columns = {title: columns[COLUMNS.index(DATE)] for title, columns in positions.items()}
        with workbook.narrowed(date_columns, period.start, period.end) as narrowed:
            return tuple(_read_register_sheets(narrowed, positions))


def _register_position(column: Column, columns: dict[str, int]) -> int | None:
    return next(
        (columns[name] for name in map(normalize_text, column.register_headers) if name in columns),
        None,
    )


def _missing_headers(header: Sequence[object]) -> list[str]:
    columns = header_columns(header)
    return [column.label for column in COLUMNS if _register_position(column, columns) is None]


def _duplicated_headers(header: Sequence[object]) -> list[str]:
    """Kolumny, których nagłówek, w dowolnym przyjmowanym zapisie, występuje więcej niż raz."""

    normalized = [normalize_text(value) for value in header if not is_blank(value)]
    return [
        column.label
        for column in COLUMNS
        if sum(normalized.count(name) for name in set(map(normalize_text, column.register_headers))) > 1
    ]


def _order_sheet_positions(register_path: Path, workbook: ReadWorkbook) -> dict[str, list[int]]:
    """Arkusze Rejestru rozpoznane po komplecie wymaganych nagłówków w pierwszym wierszu: tytuł → numery kolumn ``COLUMNS``.

    Arkusze bez większości wymaganych nagłówków (listy, komentarze, ukryte) są pomijane.
    Arkusz z większością, ale nie kompletem nagłówków, wskazuje brakujący nagłówek.
    """

    sheets: dict[str, list[int]] = {}
    closest: tuple[str, list[str]] | None = None  # arkusz z najmniejszą liczbą braków
    for sheet in workbook.sheets():
        header = next(sheet.values(min_row=1, max_row=1), ())
        missing = _missing_headers(header)
        if missing:
            if len(missing) < len(COLUMNS) / 2 and (closest is None or len(missing) < len(closest[1])):
                closest = (sheet.title, missing)
            continue
        duplicated = _duplicated_headers(header)
        if duplicated:
            raise StopError(messages.register_with_duplicated_headers(register_path, sheet.title, duplicated))
        columns = header_columns(header)
        sheets[sheet.title] = [
            position for column in COLUMNS if (position := _register_position(column, columns)) is not None
        ]
    if sheets:
        return sheets
    if closest is not None:
        raise StopError(messages.register_without_headers(register_path, *closest))
    raise StopError(messages.register_without_data_sheet(register_path, [column.label for column in COLUMNS]))


def _read_register_sheets(workbook: ReadWorkbook, positions: dict[str, list[int]]) -> list[RegisterSheet]:
    """Wiersze z danymi i puste wiersze arkuszy ``positions`` w kolejności skoroszytu."""

    sheets: list[RegisterSheet] = []
    for sheet in workbook.sheets():
        if sheet.title not in positions:
            continue
        columns = positions[sheet.title]
        read = [
            (all(is_blank(cell) for cell in whole_row), row)
            for whole_row, row in sheet.data_rows(
                min_row=2, columns={header: columns[index] for index, header in enumerate(TARGET_HEADERS)}
            )
        ]
        rows = tuple(row for empty, row in read if not empty)
        empty_rows = tuple(row.number for empty, row in read if empty)
        sheets.append(RegisterSheet(sheet.title, rows, empty_rows, tuple(columns)))
    return sheets
