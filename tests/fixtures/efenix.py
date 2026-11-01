"""Wycena w efenix w testach: syntetyczny Plik zbiorczy z kwotami AU policzonymi „przez Excel” i zgodne z nim zlecenia
Atrapy efenix. Wszystkie numery, adresy i loginy są wymyślone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re
import zipfile

from openpyxl import Workbook

from tests.fixtures.atrapa_efenix import AtrapaOrder
from tests.fixtures.settlement import COLLECTIVE_HEADERS, PERIOD, CellValue
from tests.fixtures.workbooks import active_worksheet

SOURCE_NAME = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
DAY = date(2026, 9, 9)


@dataclass(frozen=True)
class Order:
    """Zlecenie w obu miejscach naraz: Wiersz danych Pliku zbiorczego i to samo zlecenie w Atrapie efenix.

    ``cells``: dodatkowe komórki wiersza (litera → wartość), np. Ilości usług albo ilości w kolumnach Zlecenia ze
    zdjęciami. ``amount``: ``Kwota`` (AU), którą „policzył Excel”, domyślnie 0 jak w zleceniu bez Ilości usług; ``None``
    zostawia formułę bez policzonej wartości. ``quantities``: wycena, która już jest w efenix (kod → ilość), ``emmett``:
    propozycja Emmetta w tym samym kształcie.
    """

    number: str
    worker: str = "adrian.testowy"
    address: str = "UL. TESTOWA 12/3"
    day: date | None = DAY
    cells: Mapping[str, CellValue] = field(default_factory=dict)
    amount: float | None = 0.0
    efenix_address: str = "Miasto-Dzielnica ul.Testowa 12 Lokal 3"
    quantities: Mapping[str, int] = field(default_factory=dict)
    emmett: Mapping[str, int] = field(default_factory=dict)

    def in_efenix(self, order_id: str) -> AtrapaOrder:
        """To zlecenie w Atrapie z identyfikatorem ``order_id``, zgodne z Plikiem zbiorczym, z jego wyceną i Emmettem."""

        return AtrapaOrder(
            order_id=order_id,
            number=self.number.removeprefix("#"),
            realizator=self.worker,
            address=self.efenix_address,
            quantities=dict(self.quantities),
            emmett=dict(self.emmett),
        )


def write_collective_file(directory: Path, orders: Sequence[Order]) -> Path:
    """Plik zbiorczy okresu ``PERIOD`` w ``directory/PERIOD`` z nagłówkami Wzorca i Wierszem danych każdego zlecenia od 18.

    ``Kwota`` (AU) to formuła sumy z wartością policzoną przy „zapisie w Excelu”, jak w pliku taty.
    """

    folder = directory / PERIOD
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SOURCE_NAME
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    for column, header in enumerate(COLLECTIVE_HEADERS, start=1):
        sheet.cell(17, column).value = header
    sheet["AU17"] = "Kwota"
    computed: dict[int, float] = {}
    for number, order in enumerate(orders, start=18):
        moment = None if order.day is None else datetime(order.day.year, order.day.month, order.day.day, 10, 30)
        cells: dict[str, CellValue] = {
            "A": "MIASTO",
            "B": order.address,
            "F": order.number,
            "G": moment,
            "H": order.worker,
            "J": "tak",
            **order.cells,
        }
        for letter, value in cells.items():
            sheet[f"{letter}{number}"] = value
        sheet[f"AU{number}"] = f"=SUM(N{number}:AS{number})"
        if order.amount is not None:
            computed[number] = order.amount
    workbook.save(path)
    _compute_amounts(path, computed)
    return path


def _compute_amounts(path: Path, amounts: Mapping[int, float]) -> None:
    """Wpisuje do komórek AU wartość, którą Excel zapisuje przy formule (``<v>``), tak jak po zapisie w Excelu."""

    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    sheet = parts["xl/worksheets/sheet1.xml"].decode("utf-8")
    for row, amount in amounts.items():
        sheet, count = re.subn(
            rf'(<c r="AU{row}"[^>]*><f>[^<]*</f>)<v ?/>', rf"\g<1><v>{amount}</v>", sheet
        )
        assert count == 1, f"AU{row}"
    parts["xl/worksheets/sheet1.xml"] = sheet.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
