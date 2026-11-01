"""Plik zbiorczy w Przebiegu rozliczeń: Wiersze danych z Wykonawcą, numery wierszy bez niego i treść dozwolona.

Skoroszyt czyta moduł skoroszytu (``workbook_files``), właściciel układu
arkusza; jego ``WorkbookError`` przechodzi do procesu, który tłumaczy go na
Komunikat. Moduł nie zna mapowania Wykonawców ani nazw plików okresu
(``period_folder``). Z tego samego odczytu każdy Wiersz danych, także bez
Wykonawcy, przechodzi przez filtr prywatności (``order_facts``) dla Kontroli ilości, zanim Wiersze danych z
Wykonawcą stracą Ilości tylko dla INEA (``inea_only_quantities``, ADR 0018) i Znacznik efenix (``efenix_mark``).
Ten sam odczyt i filtr dają Ilości do uzupełnienia (``read_numbered_orders``), także z pliku otwartego w Excelu, a
obok filtra teksty wiersza i nazwy pozycji cennika dla strony rodzaju, które nie wychodzą z komputera (ADR 0016).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import workbook_files
from .efenix_mark import without_efenix_mark
from .inea_only_quantities import Cleared, without_inea_only
from .order_facts import CollectiveOrders, MissingHeaders, collective_orders
from .preparation_register import ACTIVITIES, COMPLETED, DEVICES, Column
from .quantities_to_fill import NumberedOrder, RowTexts
from .workbook_files import DataRow
from .worker_config import normalize_text


@dataclass(frozen=True)
class CollectiveRows:
    rows: list[DataRow]
    """Wiersze danych z Wykonawcą w kolejności z pliku, bez Ilości tylko dla INEA i bez Znacznika efenix."""
    without_worker: list[int]
    """Numery Wierszy danych bez Wykonawcy w kolejności z pliku."""
    orders: CollectiveOrders
    """Dozwolona treść każdego Wiersza danych odczytu, z Ilościami tylko dla INEA."""
    inea_only: Cleared
    """Liczba komórek z wartością, które Wiersze danych z Wykonawcą straciły jako Ilości tylko dla INEA."""


def read_data_rows(path: Path) -> CollectiveRows:
    """Wiersze danych Pliku zbiorczego jednym odczytem; plik jest tylko czytany."""

    read = workbook_files.read_data_rows(path)
    rows: list[DataRow] = []
    without_worker: list[int] = []
    for row in read.rows:
        if not str(row.worker or "").split():
            without_worker.append(row.number)
            continue
        rows.append(row)
    rows, inea_only = without_inea_only(read.header, without_efenix_mark(read.header, rows))
    return CollectiveRows(rows, without_worker, collective_orders(read.header, read.rows), inea_only)


@dataclass(frozen=True)
class NumberedOrders:
    rows: tuple[NumberedOrder, ...]
    """Każdy Wiersz danych w kolejności z pliku."""
    price_list: Mapping[str, str]
    """Litera kolumny N:AP → nazwa pozycji cennika z wiersza 17."""


def read_numbered_orders(path: Path) -> NumberedOrders | MissingHeaders:
    """Dozwolona treść każdego Wiersza danych z jego numerem wiersza i tekstami; plik jest tylko czytany.

    Plik otwarty w Excelu też jest czytany: jego ostatnia zapisana wersja (ADR 0016).
    """

    read = workbook_files.read_data_rows(path, despite_excel_lock=True)
    orders = collective_orders(read.header, read.rows)
    if isinstance(orders, MissingHeaders):
        return orders
    texts = [_texts(read.header, row) for row in read.rows]
    return NumberedOrders(
        tuple(map(NumberedOrder, (row.number for row in read.rows), orders, texts)), read.price_list
    )


def _texts(header: Mapping[str, int], row: DataRow) -> RowTexts:
    def text(value: object) -> str:
        return "" if value is None else str(value).strip()

    def under(column: Column) -> str:
        position = header.get(normalize_text(column.target_header))
        return "" if position is None else text(row.cells[position - 1].value)

    return RowTexts(text(row.worker), under(DEVICES), under(ACTIVITIES), under(COMPLETED))
