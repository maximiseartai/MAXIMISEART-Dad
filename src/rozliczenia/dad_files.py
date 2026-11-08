"""Uchwyt plików taty: jedyna droga czytnika do wartości pliku taty (ADR 0025, #841).

Każdy plik taty czyta ``DadFiles.read``: najpierw sprawdza, że plik jest na dysku i nie jest otwarty w Excelu, potem
bierze chwilę zmiany pliku, a dopiero potem jego bajty ze źródła uchwytu (``source``), więc plik zapisany znowu zaraz po
odczycie (Autozapis Excela, OneDrive) nie zmienia chwili w odcisku Kopii wejścia. Zapis między tą chwilą a początkiem
odczytu daje w odcisku chwilę wcześniejszej wersji; o wersji rozstrzyga skrót.

Wiersz pliku trafia do procesu dopiero przez świadka arkusza: ``WitnessedSheet.row`` zapisuje go jednym wywołaniem w
pamięci reguły danych (``forbidden``) i w Kopii wejścia (``copy``), więc Kopia nie ma wiersza, którego nie zna pamięć.
``SheetMemory`` zapisuje wiersz tylko w pamięci: wiersze, które czytnik czyta tylko do przeglądu (nad wklejeniem
INTERMAX), nie należą do Kopii. Pamięć jest w każdym uchwycie, a Kopia tylko w uchwycie Uruchomienia z Logami
(``DadFiles.for_run``); pamięci Skryptu dla maszyn nic nie czyta, bo Skrypt nic nie wysyła.

Uchwyt jest niezmienny i dzielony między wątkami pracy Centrum; zmienny stan to pamięć (``ForbiddenValues`` ma zamek) i
Kopia jednego Uruchomienia.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from . import workbook_files
from .client_data import ForbiddenColumn, ForbiddenValues
from .input_copy import InputCopy, SheetCopy, Values, WorkbookCopy
from .raw_orders import UNDER_HEADER, RowPositions
from .workbook_files import ByteSource

ForbiddenPositions = Sequence[tuple[ForbiddenColumn, int]]
"""Zakazane kolumny arkusza (reguła danych) z numerem kolumny od 1, z nagłówka arkusza."""


@dataclass(frozen=True)
class DadFiles:
    """Pliki taty jednej pracy: źródło bajtów, pamięć reguły danych i Kopia wejścia Uruchomienia (``None``: bez Logów)."""

    source: ByteSource = workbook_files.file_bytes
    forbidden: ForbiddenValues = field(default_factory=ForbiddenValues)
    copy: InputCopy | None = None

    def for_run(self) -> DadFiles:
        """Uchwyt jednego Uruchomienia z Logami: to samo źródło i ta sama pamięć pracy, z nową Kopią wejścia."""

        return replace(self, copy=InputCopy())

    def read(self, path: Path, *, despite_excel_lock: bool = False) -> ReadFile:
        """Plik ``path`` przeczytany raz; ``WorkbookError``, gdy go nie ma, jest otwarty w Excelu (chyba że
        ``despite_excel_lock``: jego ostatnia zapisana wersja, ADR 0016) albo system nie oddał jego bajtów."""

        workbook_files.ensure_available(path, despite_excel_lock=despite_excel_lock)
        modified = _modified_at(path)
        return ReadFile(path, self.source(path), modified, self.forbidden, self.copy)


def _modified_at(path: Path) -> datetime | None:
    """Chwila zmiany pliku ``path`` teraz (UTC); ``None``, gdy system jej nie oddał."""

    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


@dataclass(eq=False)
class ReadFile:
    """Przeczytany plik taty: bajty i chwila zmiany pliku sprzed ich odczytu (UTC; ``None``: system jej nie oddał), z
    pamięcią i Kopią swojego uchwytu. Tworzy go tylko ``DadFiles.read``."""

    path: Path
    content: bytes = field(repr=False)
    modified_at: datetime | None
    _forbidden: ForbiddenValues = field(repr=False)
    _copy: InputCopy | None = field(repr=False)
    _copied: WorkbookCopy | None = field(default=None, init=False, repr=False)

    def enter_copy(self) -> None:
        """Plik w Kopii wejścia raz, także bez arkuszy: odcisk pliku, na którym proces się zatrzymał."""

        if self._copy is not None and self._copied is None:
            self._copied = self._copy.workbook(self.path, self.content, self.modified_at)

    def memory(self, forbidden: ForbiddenPositions) -> SheetMemory:
        """Pamięć arkusza bez Kopii; ``forbidden``: zakazane kolumny arkusza."""

        return SheetMemory(self._forbidden, tuple(forbidden))

    def sheet(
        self,
        name: str,
        header_row: int,
        header: Values,
        forbidden: ForbiddenPositions,
        *,
        copied_columns: Collection[int] | None = None,
        date_column: int | None = None,
        last_ordered_row: int | None = None,
        yellow_row: int | None = None,
    ) -> WitnessedSheet:
        """Arkusz ``name`` w pamięci i, gdy uchwyt ma Kopię, w Kopii wejścia (``input_copy.WorkbookCopy.sheet``)."""

        self.enter_copy()
        copied = None
        if self._copied is not None:
            copied = self._copied.sheet(
                name,
                header_row,
                header,
                {column for _, column in forbidden},
                copied_columns=copied_columns,
                date_column=date_column,
                last_ordered_row=last_ordered_row,
                yellow_row=yellow_row,
            )
        return WitnessedSheet(self._forbidden, tuple(forbidden), copied)


@dataclass(frozen=True)
class SheetMemory:
    """Pamięć reguły danych jednego arkusza: komórki jego zakazanych kolumn."""

    _forbidden: ForbiddenValues
    _columns: tuple[tuple[ForbiddenColumn, int], ...]

    def remember(self, values: Values, positions: RowPositions = UNDER_HEADER) -> None:
        """Komórki zakazanych kolumn wiersza ``values`` w każdym jego położeniu (kolumna − przesunięcie z ``known``)."""

        for offset in positions.known:
            for column, number in self._columns:
                self._forbidden.remember_value(column, _value_at(values, number - offset))


@dataclass(frozen=True)
class WitnessedSheet(SheetMemory):
    """Świadek arkusza: wiersz trafia jednym wywołaniem do pamięci i do Kopii wejścia (gdy uchwyt ją ma)."""

    _copied: SheetCopy | None = None

    def row(self, number: int, values: Values, positions: RowPositions = UNDER_HEADER) -> None:
        """Wiersz ``number`` z wartościami ``values`` w położeniach ``positions`` w pamięci i w Kopii."""

        self.remember(values, positions)
        if self._copied is not None:
            self._copied.row(number, values, positions)

    def empty_rows(self, numbers: Sequence[int]) -> None:
        """Puste wiersze z przeczytanego zakresu, które proces liczy (``input_copy.SheetCopy.empty_rows``)."""

        if self._copied is not None:
            self._copied.empty_rows(numbers)


def _value_at(values: Values, column: int) -> object:
    if isinstance(values, Mapping):
        return values.get(column)
    return values[column - 1] if 1 <= column <= len(values) else None
