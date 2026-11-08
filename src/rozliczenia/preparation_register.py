"""Rejestr zleceń w Przygotowaniu pliku zbiorczego: dostępność i odczyt (etap Odczyt danych).

Rejestr jest tylko czytany, przez moduł skoroszytu. Arkusze ze zleceniami są rozpoznawane po komplecie
wymaganych nagłówków w pierwszym wierszu, a komórki z wartościami, Wyróżnieniami i Hiperłączami
są zwracane pod nagłówkiem docelowym każdej kolumny ``register_columns.COLUMNS``. Pierwszy wiersz bloku wklejenia z aplikacji firmowej
stoi przesunięty, a wiersz ze śladem przesunięcia może tak stać, więc arkusz oddaje je też z wartościami całego wiersza
(``RegisterSheet.shifted_rows``, ``RegisterSheet.both_rows``). Dla okresu
czytane są tylko wiersze od pierwszego do ostatniego, którego data może leżeć w okresie. ``read_register`` to
produkcyjny czytnik Rejestru dla ``input_checks.Readers``, który czyta arkusze z pliku przeczytanego uchwytem plików
taty (``dad_files.ReadFile``) i tłumaczy jego ``WorkbookError``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache, partial
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from openpyxl.utils import get_column_letter

from . import preparation_messages as messages
from . import raw_orders, workbook_files
from .message import StopError
from .register_columns import COLUMNS, DATE, TARGET_HEADERS, WORKER, Column
from .settlement_period import SettlementPeriod
from .text import normalize_text
from .workbook_files import ReadRow, ReadWorkbook, RegisterRow, header_columns, is_blank

if TYPE_CHECKING:
    from .dad_files import ReadFile


@dataclass(frozen=True)
class RegisterSheet:
    """Arkusz ze zleceniami: wiersze z danymi i numery całkowicie pustych wierszy z odczytanego zakresu."""

    name: str
    register_rows: tuple[RegisterRow, ...]
    """Wiersze z danymi; komórki pod nagłówkiem docelowym."""
    empty_rows: tuple[int, ...]
    _positions: tuple[int, ...]  # numery kolumn ``COLUMNS`` w arkuszu (od 1)
    shifted_rows: Mapping[int, Mapping[int, object]] = field(default_factory=lambda: MappingProxyType({}))
    """Pierwsze wiersze bloków wklejenia → wartości całego wiersza po numerze kolumny (od 1): wiersz bez wyglądu
    uporządkowanego (``raw_orders.ordered_look``), nad którym najbliższy wiersz z danymi odczytu ma ten wygląd albo nie
    ma żadnego, jak w INTERMAX (``raw_orders.first_in_block``). Z aplikacji firmowej przychodzi on zawsze
    ``raw_orders.SHIFT`` kolumn na lewo od nagłówków (fakt domeny, ADR 0025), więc pamięć reguły danych zna jego
    ``ADRES`` i ``NUMER UMOWY`` tylko tam (#918), gdy jego przesunięcie widać (``raw_orders.shift_visible``). Pierwszy
    wiersz bez widocznego przesunięcia jest w ``both_rows``, np. wiersz na górze odczytu okresu ze środka arkusza, bo
    zawężenie zaczyna się od daty z godziną pod ``DATA GODZ. POCZ.``."""
    both_rows: Mapping[int, Mapping[int, object]] = field(default_factory=lambda: MappingProxyType({}))
    """Wiersze z danymi z siatki (``raw_orders.both_positions``: pierwszy wiersz bloku bez widocznego przesunięcia i
    inny wiersz ze śladem przesunięcia) → wartości całego wiersza: pamięć zna je w obu położeniach (ADR 0025)."""
    traced_rows: frozenset[int] = frozenset()
    """Wiersze z ``both_rows`` ze śladem przesunięcia, które nie są pierwszym wierszem bloku: Logi mają o nich uwagę."""

    def column_letter(self, column: Column) -> str:
        """Litera kolumny arkusza z nagłówkiem ``column``, np. ``L`` dla ``SKUTECZNE``."""

        return get_column_letter(self._positions[COLUMNS.index(column)])

    @property
    def positions(self) -> dict[Column, int]:
        """Kolumna ``COLUMNS`` → jej numer w arkuszu (od 1)."""

        return dict(zip(COLUMNS, self._positions, strict=True))


def cell_value(row: RegisterRow, column: Column) -> object:
    """Wartość komórki Rejestru pod nagłówkiem ``column`` w wierszu ``row``."""

    return row.cells[column.target_header].value


def read_register(file: ReadFile, period: SettlementPeriod | None = None) -> list[RegisterSheet]:
    """Arkusze ze zleceniami przeczytanego Rejestru ``file``; ``WorkbookError``, gdy Rejestru nie da się odczytać, i
    zatrzymanie, gdy nie ma nagłówków.

    Z ``period`` arkusz ma tylko wiersze od pierwszego do ostatniego, którego data
    może leżeć w okresie: Planowanie szuka zleceń okresu i wierszy bez daty tylko
    między pierwszym a ostatnim zleceniem okresu. Bez ``period`` ma wszystkie wiersze.
    """

    if period is None:
        with workbook_files.read_workbook(file.path, file.content) as workbook:
            return _read_register_sheets(workbook, _order_sheet_positions(file.path, _headers(workbook)))
    return list(_period_sheets(file.path, file.content, period))


# Centrum robi Podgląd, a potem RUN tego samego okresu w jednym procesie. Arkusze okresu zależą tylko od bajtów
# Rejestru i okresu, więc niezmieniony Rejestr nie jest drugi raz zawężany ani parsowany, a zmieniony jest
# czytany od nowa. Uruchomienia w różnych wątkach dostają ten sam wynik, więc jest z krotek, zamrożonych dataclass
# i map w ``MappingProxyType``. Wyjątek to wypełnienie i kolor Wyróżnień: obiekty openpyxl, których nie da się
# zamrozić, więc Zapis nakłada tylko ich kopie (``Highlights.font_over``, ``Highlights.fill_over``, ``RowLook``).
# Rejestr jest od razu zawężony po kolumnach daty z wiersza 1 czytanego bez openpyxl (``_guessed_date_columns``), a
# nagłówki rozpoznaje wiersz 1 zawężonego Rejestru w openpyxl; zawężenie powtarza się tylko, gdy rozpoznał inne kolumny.
@lru_cache(maxsize=2)
def _period_sheets(register_path: Path, content: bytes, period: SettlementPeriod) -> tuple[RegisterSheet, ...]:
    dated = (partial(_guessed_date_columns, register_path), period.start, period.end)
    with workbook_files.read_workbook(register_path, content, dated) as workbook:
        positions = _order_sheet_positions(register_path, _headers(workbook))
        with workbook.narrowed(_date_columns(positions), period.start, period.end) as narrowed:
            return tuple(_read_register_sheets(narrowed, positions))


def _guessed_date_columns(register_path: Path, headers: Mapping[str, Sequence[object]]) -> dict[str, int]:
    """Kolumny daty arkuszy, które ``_order_sheet_positions`` rozpoznaje po wierszach 1 ``headers``; żadne, gdy z nich
    Przygotowanie się zatrzymuje, bo wtedy zatrzymanie daje wiersz 1 z openpyxl, zanim cokolwiek jest zawężane."""

    try:
        return _date_columns(_order_sheet_positions(register_path, headers.items()))
    except StopError:
        return {}


def _date_columns(positions: Mapping[str, list[int]]) -> dict[str, int]:
    return {title: columns[COLUMNS.index(DATE)] for title, columns in positions.items()}


def _headers(workbook: ReadWorkbook) -> Iterator[tuple[str, Sequence[object]]]:
    """Tytuł i wartości wiersza 1 każdego arkusza, czytane arkusz po arkuszu."""

    for sheet in workbook.sheets():
        yield sheet.title, next(sheet.values(min_row=1, max_row=1), ())


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


def _order_sheet_positions(register_path: Path, headers: Iterable[tuple[str, Sequence[object]]]) -> dict[str, list[int]]:
    """Arkusze Rejestru rozpoznane po komplecie wymaganych nagłówków w pierwszym wierszu (``headers``: tytuł i wartości
    wiersza 1 każdego arkusza): tytuł → numery kolumn ``COLUMNS``.

    Arkusze bez większości wymaganych nagłówków (listy, komentarze, ukryte) są pomijane.
    Arkusz z większością, ale nie kompletem nagłówków, wskazuje brakujący nagłówek.
    """

    sheets: dict[str, list[int]] = {}
    closest: tuple[str, list[str]] | None = None  # arkusz z najmniejszą liczbą braków
    for title, header in headers:
        missing = _missing_headers(header)
        if missing:
            if len(missing) < len(COLUMNS) / 2 and (closest is None or len(missing) < len(closest[1])):
                closest = (title, missing)
            continue
        duplicated = _duplicated_headers(header)
        if duplicated:
            raise StopError(messages.register_with_duplicated_headers(register_path, title, duplicated))
        columns = header_columns(header)
        sheets[title] = [
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
            (all(is_blank(cell) for cell in found.values), found)
            for found in sheet.data_rows(
                min_row=2, columns={header: columns[index] for index, header in enumerate(TARGET_HEADERS)}
            )
        ]
        rows = tuple(found.row for empty, found in read if not empty)
        empty_rows = tuple(found.row.number for empty, found in read if empty)
        left = columns[COLUMNS.index(DATE)] - raw_orders.SHIFT
        shifted: dict[int, Mapping[int, object]] = {}
        both: dict[int, Mapping[int, object]] = {}
        traced: set[int] = set()
        above: bool | None = None  # wygląd uporządkowany najbliższego wiersza z danymi nad wierszem; None: nie ma go
        for empty, found in read:
            if empty:
                continue
            ordered = _ordered_look(found)
            first = not ordered and above is not False
            values = MappingProxyType(dict(enumerate(found.values, start=1)))
            left_of_date = found.values[left - 1] if 1 <= left <= len(found.values) else None
            if raw_orders.both_positions(first=first, left_of_date=left_of_date, date=found.row.cells[DATE.target_header].value):
                both[found.row.number] = values
                if not first:
                    traced.add(found.row.number)
            elif first:
                shifted[found.row.number] = values
            above = ordered
        sheets.append(
            RegisterSheet(
                sheet.title,
                rows,
                empty_rows,
                tuple(columns),
                MappingProxyType(shifted),
                MappingProxyType(both),
                frozenset(traced),
            )
        )
    return sheets


def _ordered_look(found: ReadRow) -> bool:
    """Wiersz z wyglądem uporządkowanym (``raw_orders.ordered_look``) w komórkach z wartością spod nagłówków ``COLUMNS``
    poza ``WYKONAWCA``. To część kolumn zlecenia, więc wiersz z tym wyglądem tutaj ma go też w Uporządkowaniu, a wiersz,
    który ma go tylko w ``AKCJE``, ``ZWROT`` albo ``UWAGI``, tutaj go nie ma."""

    return raw_orders.ordered_look(
        face
        for header, face in found.faces.items()
        if header != WORKER.target_header and not is_blank(found.row.cells[header].value)
    )
