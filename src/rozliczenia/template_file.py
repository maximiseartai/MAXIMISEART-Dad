"""Plik z Wzorca: Sprawdzanie, Planowanie i zapis Wierszy danych w kopii Wzorca jednego z trzech plików (ADR 0008).

Rozliczenie pracownika, Plik zbiorczy i Rozliczenie wewnętrzne powstają z Wzorca przez ``TemplateFile``, którego
konstruktor wybiera plik: ``check`` to Sprawdzanie, ``plan`` to Planowanie, a ``create`` zapisuje plik atomowo
(``workbook_save``). Układ arkusza Wzorca opisuje jeden ``SheetLayout``, z którego czytają obie drogi zapisu: kopia
bajtów Wzorca (``template_copy``), gdy przyjmuje kształt Wzorca i wierszy, a inaczej openpyxl; obie dają ten sam
plik. Wzorzec czyta moduł skoroszytu (``workbook_files``) z jego klasyfikacją uszkodzeń, a zły układ to
``WorkbookError`` z miejscem.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager, suppress
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Never, cast

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles.fills import Fill
from openpyxl.styles.fonts import Font
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.exceptions import IllegalCharacterError
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.worksheet import Worksheet

from .highlights import PLAIN
from .register_columns import TARGET_HEADERS
from .quantity_rules import QuantityColumn
from .row_look import GENERAL, RowLook, wraps
from .template_copy import InvalidValue, Package, Recalculation, Row, SheetLayout, TemplateCopy
from .collective_layout import DATA_ROW_COLUMNS, FIRST_DATA_ROW, HEADER_ROW, INPUT_COLUMNS, LOOK_COLUMNS, QUANTITY_COLUMNS
from .workbook_files import (
    DataRow,
    MergedCells,
    MissingHeader,
    Problem,
    RegisterRow,
    WorkbookError,
    check_worker_header,
    header_columns,
    is_blank,
    open_workbook,
    template_content,
)
from .workbook_parts import UnsupportedShape
from .workbook_save import SaveProblem, WorkbookSaveError, save_from_template, write_atomically
from .text import normalize_text
from .write_routes import Route, TemplateKind


_INTERNAL_LOOK_COLUMNS = range(1, 14)  # A:M Rozliczenia wewnętrznego, z ``zwrot`` i ``UWAGI``


@dataclass(frozen=True)
class _Rules:
    """Układ Wzorca jednego pliku: jego arkusz (``SheetLayout``, ten sam dla kopii i drogi przez openpyxl) i reguły,
    którymi zapis tego pliku różni się od pozostałych."""

    sheet: SheetLayout
    kind: TemplateKind
    worker_header: bool
    """Nagłówek w kolumnach danych wejściowych z WYKONAWCA w H; bez niego nagłówek to cały wiersz."""
    headers: tuple[str, ...] = ()
    """Nagłówki docelowe pliku okresu, pod którymi stają komórki wiersza Rejestru zleceń; szukane w wierszu nagłówka
    Wzorca bez względu na wielkość liter i spacje. Rozliczenie pracownika ich nie ma: komórka kolumny Pliku
    zbiorczego trafia do tej samej kolumny."""

    @property
    def last_header_column(self) -> int | None:
        """Ostatnia kolumna nagłówka; ``None``: cały wiersz nagłówka."""

        return self.sheet.input_columns if self.worker_header else None


_WORKER_SETTLEMENT = _Rules(
    SheetLayout(
        header_row=HEADER_ROW,
        first_data_row=FIRST_DATA_ROW,
        input_columns=INPUT_COLUMNS[-1],
        data_columns=DATA_ROW_COLUMNS[-1],
        look_columns=LOOK_COLUMNS[-1],
        period_file=False,
        recalculation=Recalculation.FORCED,
    ),
    kind=TemplateKind.WORKER_SETTLEMENT,
    worker_header=True,
)
_COLLECTIVE_FILE = _Rules(
    SheetLayout(
        header_row=HEADER_ROW,
        first_data_row=FIRST_DATA_ROW,
        input_columns=INPUT_COLUMNS[-1],
        data_columns=INPUT_COLUMNS[-1],
        look_columns=LOOK_COLUMNS[-1],
        period_file=True,
        recalculation=Recalculation.FORCED,
        quantity_columns=QUANTITY_COLUMNS,
    ),
    kind=TemplateKind.COLLECTIVE_FILE,
    worker_header=True,
    headers=TARGET_HEADERS,
)
_INTERNAL_SETTLEMENT = _Rules(
    SheetLayout(
        header_row=1,
        first_data_row=2,
        input_columns=INPUT_COLUMNS[-1],
        data_columns=INPUT_COLUMNS[-1],
        look_columns=_INTERNAL_LOOK_COLUMNS[-1],
        period_file=True,
        recalculation=Recalculation.ON_LOAD,
    ),
    kind=TemplateKind.INTERNAL_SETTLEMENT,
    worker_header=False,
    headers=TARGET_HEADERS,
)


def _is_value(cell: Cell | MergedCell) -> bool:
    return cell.value is not None and cell.data_type != "f"


def _is_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


@dataclass(frozen=True)
class _Outline:
    """Wzorzec pliku okresu w tym, czego potrzebują Sprawdzanie i Planowanie."""

    title: str
    header: Sequence[object]
    """Wartości wiersza nagłówka od kolumny A."""
    merged_ranges: tuple[CellRange, ...]
    """Scalenia aktywnego arkusza w kolejności, w jakiej daje je openpyxl."""
    zero_row_count: int
    """Liczba kolejnych Wierszy danych z zerami w kolumnach Ilości usług (``SheetLayout.quantity_columns``)."""


def _zero_row_count(sheet: Worksheet, layout: SheetLayout) -> int:
    if not layout.quantity_columns:
        return 0
    zero_row_count = 0
    for values in sheet.iter_rows(
        min_row=layout.first_data_row,
        min_col=layout.quantity_columns[0],
        max_col=layout.quantity_columns[-1],
        values_only=True,
    ):
        if not any(_is_zero(value) for value in values):
            break
        zero_row_count += 1
    return zero_row_count


@dataclass(frozen=True)
class TemplatePlan:
    """Planowanie Wierszy danych we Wzorcu: wiersze, do których trafią, ile kolejnych Wierszy danych ma zera w N:AP
    i który wiersz jest za nimi."""

    data_rows: range
    zero_row_count: int
    first_row_without_zeros: int


class TemplateFile:
    """Wzorzec jednego układu: jego Sprawdzanie, Planowanie i pliki z Wierszami danych (ADR 0008).

    Powstaje dla jednego z trzech plików: ``worker_settlement`` z Wierszy danych Pliku zbiorczego (``DataRow``),
    ``collective_file`` albo ``internal_settlement`` z wierszy Rejestru zleceń (``RegisterRow``), których komórki
    stają pod nagłówkami docelowymi pliku okresu. Utworzenie nie czyta dysku. Plik powstaje kopią bajtów Wzorca,
    gdy kopia przyjmuje kształt Wzorca i wierszy, a inaczej przez openpyxl; obie drogi dają ten sam plik.
    Pierwszy plik czyta bajty Wzorca ponownie: Wzorzec zmieniony albo otwarty w Excelu po Sprawdzaniu działa tak,
    jakby był czytany dopiero wtedy, a kolejne pliki powstają z tych samych bajtów. Wzorzec na dysku pozostaje
    niezmieniony.
    """

    def __init__(self, path: Path, rules: _Rules) -> None:
        self.path = path
        self._rules = rules
        self._content: bytes | None = None
        self._copy: TemplateCopy | None = None
        self._copy_read = False
        self._outline: _Outline | None = None
        self._read_for_files = False

    @classmethod
    def worker_settlement(cls, path: Path) -> TemplateFile:
        """Wzorzec rozliczenia pracownika: bez danych w Wierszach danych, sprawdzany też przed każdym plikiem."""

        return cls(path, _WORKER_SETTLEMENT)

    @classmethod
    def collective_file(cls, path: Path) -> TemplateFile:
        """Wzorzec pliku zbiorczego z nagłówkami docelowymi w A17:K17 i Ilościami usług w N:AP."""

        return cls(path, _COLLECTIVE_FILE)

    @classmethod
    def internal_settlement(cls, path: Path) -> TemplateFile:
        """Wzorzec rozliczenia wewnętrznego z nagłówkami docelowymi w wierszu 1."""

        return cls(path, _INTERNAL_SETTLEMENT)

    @property
    def kind(self) -> TemplateKind:
        return self._rules.kind

    def check(self) -> None:
        """Sprawdzanie bez zapisu: ``WorkbookError``, gdy Wzorzec nie może posłużyć jako wzór.

        Powód to brak pliku, otwarcie w Excelu, nieczytelny skoroszyt, brak nagłówka docelowego albo
        WYKONAWCA poza H17 (zły układ z ``MissingHeader``), a we Wzorcu rozliczenia pracownika także
        wartości w Wierszach danych (``HAS_DATA``).
        """

        if self._rules.sheet.period_file:
            outline = self._read_outline()
            self._target_columns(outline.title, outline.header)
            if self._rules.worker_header:
                check_worker_header(self.path, outline.title, outline.header)
            return
        self._read()
        copy = self._template_copy()
        if copy is not None:
            self._check_settlement_template(copy.title, copy.header, copy.has_input_data)
            return
        with self._openpyxl_workbook() as workbook:
            sheet = _active_worksheet(self.path, workbook)
            self._check_settlement_template(sheet.title, self._header(sheet), self._has_input_data(sheet))

    def plan(self, row_count: int) -> TemplatePlan:
        """Planowanie ``row_count`` Wierszy danych: nagłówki docelowe jak przy Sprawdzaniu, a scalenie w
        komórkach, do których trafią, to zły układ z ``MergedCells``."""

        outline = self._read_outline()
        columns = self._written_columns(self._target_columns(outline.title, outline.header))
        _ensure_unmerged(self.path, outline.title, outline.merged_ranges, self._rules.sheet, columns, row_count)
        first_row = self._rules.sheet.first_data_row
        return TemplatePlan(
            range(first_row, first_row + row_count), outline.zero_row_count, first_row + outline.zero_row_count
        )

    def create(self, target: Path, rows: Sequence[DataRow] | Sequence[RegisterRow]) -> Route:
        """Zapisuje atomowo pod ``target`` plik z Wzorca z ``rows`` od pierwszego Wiersza danych i podaje drogę zapisu.

        Wpisana komórka dostaje Hiperłącze wiersza albo żadne i wartość; w kolumnach wyglądu Wygląd Wiersza
        danych (``row_look``), a dalej Wyróżnienia na czcionce i wypełnieniu komórki Wzorca. Formuły,
        ``calcChain`` kopii, reszta formatowania i ``xl/externalLinks/*`` zostają z Wzorca. ``WorkbookError``,
        gdy Wzorca nie da się już użyć, brak nagłówka albo komórki zapisu są scalone;
        ``WorkbookSaveError``, gdy zapis się nie uda, także przez znak niedozwolony w XML. W obu przypadkach ``target`` nie powstaje.
        """

        if not self._read_for_files:
            self._read()
            self._read_for_files = True
        copy = self._template_copy()
        if copy is not None:
            # Nagłówki docelowe kopii są szukane w jej kolumnach danych wejściowych od A, więc zajmują je wszystkie.
            target_columns = self._target_columns(copy.title, copy.header)
            if not self._rules.sheet.period_file:
                self._check_settlement_template(copy.title, copy.header, copy.has_input_data)
            try:
                package = copy.with_rows(_in_columns(rows, target_columns))
            except InvalidValue as exc:
                raise WorkbookSaveError(target, SaveProblem.INVALID_VALUE) from exc
            except UnsupportedShape:
                pass
            else:
                write_atomically(target, _package_writer(package, target))
                return Route.COPY
        self._create_with_openpyxl(target, rows)
        return Route.OPENPYXL

    def _read(self) -> None:
        """Czyta bajty Wzorca; wczytany Wzorzec zostaje, jeśli plik się nie zmienił."""

        content = template_content(self.path)
        if content != self._content:
            self._content = content
            self._copy = None
            self._copy_read = False
            self._outline = None

    def _read_outline(self) -> _Outline:
        """Wzorzec pliku okresu do Sprawdzania i Planowania z bajtów czytanych od nowa; niczego nie zapisuje.

        Zarys pochodzi z tego samego odczytu co kopia (``TemplateCopy``), więc Wzorzec jest parsowany raz na
        Uruchomienie, a zmieniony po Sprawdzaniu jest czytany od nowa. Wzorzec, którego kształtu kopia nie przyjmuje,
        czyta pełne wczytanie przez openpyxl z jego klasyfikacją uszkodzeń.
        """

        self._read()
        if self._outline is None:
            copy = self._template_copy()
            if copy is not None:
                # Ten sam zbiór, którym openpyxl trzyma scalenia arkusza, więc i ta sama kolejność.
                merged_ranges = tuple(MultiCellRange([CellRange(reference) for reference in copy.merged_cells]).ranges)
                self._outline = _Outline(copy.title, copy.header, merged_ranges, copy.zero_row_count)
            else:
                with self._openpyxl_workbook() as workbook:
                    sheet = _active_worksheet(self.path, workbook)
                    self._outline = _Outline(
                        sheet.title,
                        self._header(sheet),
                        tuple(sheet.merged_cells.ranges),
                        _zero_row_count(sheet, self._rules.sheet),
                    )
        return self._outline

    def _template_copy(self) -> TemplateCopy | None:
        """Wzorzec do kopii z podmienionymi Wierszami danych; ``None``, gdy jego kształt wymaga openpyxl (ADR 0008).

        Kopia wpisuje pod nagłówkiem docelowym z kolumn danych wejściowych, a droga przez openpyxl pod jego ostatnim
        wystąpieniem w całym wierszu (``_header``, ``header_columns``), więc kopia przyjmuje Wzorzec pliku okresu tylko
        wtedy, gdy oba wskazują dla każdego nagłówka docelowego tę samą kolumnę.
        """

        if not self._copy_read:
            self._copy_read = True
            self._copy = None
            with suppress(UnsupportedShape):
                copy = TemplateCopy.of(self._loaded(), self._rules.sheet)
                found, whole = header_columns(copy.header), header_columns(copy.whole_header)
                if all(found.get(normalize_text(target)) == whole.get(normalize_text(target)) for target in self._rules.headers):
                    self._copy = copy
        return self._copy

    def _openpyxl_workbook(self) -> AbstractContextManager[Workbook]:
        """Pełne wczytanie Wzorca przez openpyxl z jego klasyfikacją uszkodzeń: droga, gdy kopia nie przyjmuje kształtu
        Wzorca (ADR 0008)."""

        return open_workbook(self.path, self._loaded(), read_only=False)

    def _create_with_openpyxl(self, target: Path, rows: Sequence[DataRow] | Sequence[RegisterRow]) -> None:
        with self._openpyxl_workbook() as workbook:
            sheet = _active_worksheet(self.path, workbook)
            header = self._header(sheet)
            target_columns = self._target_columns(sheet.title, header)
            columns = self._written_columns(target_columns)
            if self._rules.sheet.period_file:
                _ensure_unmerged(
                    self.path, sheet.title, tuple(sheet.merged_cells.ranges), self._rules.sheet, columns, len(rows)
                )
            else:
                self._check_settlement_template(sheet.title, header, self._has_input_data(sheet))
                _ensure_unmerged(
                    self.path, sheet.title, tuple(sheet.merged_cells.ranges), self._rules.sheet, columns, len(rows)
                )
            try:
                _write_rows(sheet, self._rules.sheet, _in_columns(rows, target_columns), columns)
            except IllegalCharacterError as exc:
                raise WorkbookSaveError(target, SaveProblem.INVALID_VALUE) from exc
            _request_recalculation(workbook, self._rules.sheet.recalculation)
            save_from_template(workbook, target, self._loaded())

    def _header(self, sheet: Worksheet) -> list[object]:
        """Wartości wiersza nagłówka od kolumny A."""

        last_column = self._rules.last_header_column or sheet.max_column
        return [sheet.cell(self._rules.sheet.header_row, column).value for column in range(1, last_column + 1)]

    def _has_input_data(self, sheet: Worksheet) -> bool:
        """Wiersze danych mają wartość w A:K; formuły Wzorca nie są danymi."""

        for row in range(self._rules.sheet.first_data_row, sheet.max_row + 1):
            if any(_is_value(sheet.cell(row, column)) for column in INPUT_COLUMNS):
                return True
        return False

    def _check_settlement_template(self, sheet: str, header: Sequence[object], has_input_data: bool) -> None:
        """Kontrole Szablonu pracownika na Wzorcu: WYKONAWCA w H17, potem brak wartości w Wierszach danych."""

        check_worker_header(self.path, sheet, header)
        if has_input_data:
            raise WorkbookError(self.path, Problem.HAS_DATA)

    def _target_columns(self, sheet: str, header: Sequence[object]) -> Mapping[str, int]:
        """Kolumna Wzorca pod każdym nagłówkiem docelowym; brak nagłówka to zły układ z ``MissingHeader``."""

        found = header_columns(header)
        columns: dict[str, int] = {}
        for target in self._rules.headers:
            column = found.get(normalize_text(target))
            if column is None:
                raise WorkbookError(self.path, Problem.LAYOUT, MissingHeader(sheet, self._rules.sheet.header_row, target))
            columns[target] = column
        return columns

    def _written_columns(self, target_columns: Mapping[str, int]) -> Collection[int]:
        """Kolumny, do których trafiają komórki wiersza: pod nagłówkami docelowymi, a w Rozliczeniu pracownika A:AT."""

        return target_columns.values() if self._rules.headers else DATA_ROW_COLUMNS

    def _loaded(self) -> bytes:
        assert self._content is not None, "Wzorzec jest czytany przed użyciem"
        return self._content


def _ensure_unmerged(
    path: Path, sheet: str, merged_ranges: Sequence[CellRange], layout: SheetLayout, columns: Collection[int], row_count: int
) -> None:
    """Zły układ z ``MergedCells``, gdy komórki ``row_count`` zapisanych Wierszy danych są scalone."""

    if row_count == 0:
        return
    first_row, last_row = layout.first_data_row, layout.first_data_row + row_count - 1
    last_column = max(_last_written_column(layout, columns), layout.quantity_columns.stop - 1)
    for merged in merged_ranges:
        if merged.min_row <= last_row and merged.max_row >= first_row and merged.min_col <= last_column:
            raise WorkbookError(path, Problem.LAYOUT, MergedCells(sheet, merged.coord))


def _last_written_column(layout: SheetLayout, columns: Collection[int]) -> int:
    return max(layout.look_columns, *columns)


_NO_QUANTITIES: MappingProxyType[QuantityColumn, Never] = MappingProxyType({})


def _in_columns(rows: Sequence[DataRow] | Sequence[RegisterRow], target_columns: Mapping[str, int]) -> list[Row]:
    """Komórka Wiersza danych Pliku zbiorczego w swojej kolumnie, a komórka wiersza Rejestru pod nagłówkiem docelowym."""

    return [
        Row(dict(enumerate(row.cells, start=1)), _NO_QUANTITIES)
        if isinstance(row, DataRow)
        else Row({target_columns[header]: cell for header, cell in row.cells.items()}, row.quantities)
        for row in rows
    ]


def _write_rows(sheet: Worksheet, layout: SheetLayout, rows: Sequence[Row], columns: Collection[int]) -> None:
    """Jedyny zapis Wierszy danych przez openpyxl: komórka wiersza trafia do swojej kolumny z ``columns``.

    Komórka kolumny wyglądu dostaje Wygląd Wiersza danych, a bez komórki w wierszu sam wygląd i treść Wzorca; w
    pliku okresu wygląd ma każda zapisana kolumna. Dalsze komórki dostają Wyróżnienia na stylu Wzorca. Zapisany
    wiersz traci wysokość z Wzorca.
    """

    last_column = _last_written_column(layout, columns)
    look_columns = last_column if layout.period_file else layout.look_columns
    look = RowLook([cast(Font, sheet.cell(layout.header_row, column).font) for column in range(1, look_columns + 1)])
    for index, row in enumerate(rows):
        number = layout.first_data_row + index
        dimension = sheet.row_dimensions.get(number)  # bez tworzenia wymiaru, którego nie ma we Wzorcu
        if dimension is not None:
            dimension.ht = None
        for column in range(1, last_column + 1):
            cell = sheet.cell(number, column)
            data = row.cells.get(column)
            if data is None:
                look.cell(column, PLAIN, GENERAL, wrapped=False).apply(cell)
                continue
            value, highlights, number_format, link = data
            # Przed wartością: openpyxl wpisuje adres jako wartość pustej komórki.
            cell.hyperlink = None if link is None else link.address
            cell.value = value
            if column <= look.columns:
                look.cell(column, highlights, number_format, wrapped=wraps(value)).apply(cell)
            else:
                # font_over zawsze zwraca kopię, a fill_over może zwrócić wypełnienie, które dostał.
                cell.font = highlights.font_over(cast(Font, cell.font))
                cell.fill = highlights.fill_over(cast(Fill, copy(cell.fill)))
        for letter, quantity in row.quantities.items():
            sheet.cell(number, column_index_from_string(letter)).value = quantity
    if layout.period_file:
        _set_autofilter(sheet, layout.header_row, len(rows))


def _set_autofilter(sheet: Worksheet, header_row: int, row_count: int) -> None:
    """Autofiltr na nagłówek i faktyczne Wiersze danych; zakres zapisany we Wzorcu jest ignorowany."""

    columns = [column for column, cell in enumerate(sheet[header_row], start=1) if not is_blank(cell.value)]
    first_column, last_column = get_column_letter(min(columns)), get_column_letter(max(columns))
    sheet.auto_filter = AutoFilter(ref=f"{first_column}{header_row}:{last_column}{header_row + row_count}")


def _package_writer(package: Package, target: Path) -> Callable[[Path], None]:
    def write(path: Path) -> None:
        try:
            with path.open("wb") as out:
                package.write(out)
        except OSError as exc:
            raise WorkbookSaveError(target, SaveProblem.CONTENT) from exc

    return write


def _active_worksheet(path: Path, workbook: Workbook) -> Worksheet:
    worksheet = workbook.active
    if not isinstance(worksheet, Worksheet):
        raise WorkbookError(path, Problem.UNREADABLE)
    return worksheet


def _request_recalculation(workbook: Workbook, recalculation: Recalculation) -> None:
    """Flagi przeliczania układu w ``calcPr``, te same co w kopii; openpyxl nie zapisuje wyników formuł."""

    calculation = getattr(workbook, "calculation", None)
    if calculation is not None:
        for flag, value in recalculation.value:
            setattr(calculation, flag, value)
