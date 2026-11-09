"""Kontrakt Uzupełnienia pliku zbiorczego: Ilości do uzupełnienia, strona rodzaju i wiersze bez ilości."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Message, Model
from rozliczenia.quantities_to_fill import CellSource, FillKind, RowState


class RowToFill(Model):
    """Wiersz Pliku zbiorczego z Ilościami do uzupełnienia: numer wiersza i jego stan (zrobiony, do uzupełnienia, bez ilości)."""

    row: int
    state: RowState


class KindToFill(Model):
    """Rodzaj Ilości do uzupełnienia z listą wierszy; ``done``: każdy wiersz zrobiony, także gdy wierszy nie ma."""

    kind: FillKind
    rows: list[RowToFill]
    done: bool


class DescriptionColumn(Model):
    """Kolumna z opisu technika i liczba wierszy, w których tata coś w niej wpisał."""

    column: str
    rows: int


class CollectiveFileRead(Model):
    """Odczyt Pliku zbiorczego za widokiem: znacznik zapisu przed odczytem i godzina odczytu.

    ``retrying``: późniejsze odczyty się nie udały, więc to ostatni dobry stan, a strona ponawia odczyt.
    """

    version: str | None
    read_at: datetime
    retrying: bool


class QuantitiesToFillReady(Model):
    """Ilości do uzupełnienia okresu przeliczone z zapisanego Pliku zbiorczego; ``kinds`` ma każdy rodzaj z listą.

    ``settled``: Przebieg rozliczeń okresu się odbył (Status okresu Rozliczenia pracowników gotowe), więc strona jest
    podglądem bez „Gotowe, rozlicz pracowników”, a wiersz bez wpisu taty jest „bez ilości”.
    """

    state: Literal["ready"]
    read: CollectiveFileRead
    settled: bool
    kinds: list[KindToFill]
    description_columns: list[DescriptionColumn]


class QuantitiesToFillProblem(Model):
    """Pliku zbiorczego nie udało się odczytać; Komunikat go nazywa, a ``version`` to znacznik zapisu przed odczytem.

    ``collective_file_exists``: plik jest w Folderze okresu, więc „Otwórz Plik zbiorczy” ma co otworzyć.
    """

    state: Literal["problem"]
    message: Message
    version: str | None
    collective_file_exists: bool


class CollectiveFileVersion(Model):
    """Znacznik zapisu Pliku zbiorczego (czas zmiany i rozmiar); ``None``, gdy pliku nie widać."""

    version: str | None


QuantitiesToFill = Annotated[QuantitiesToFillReady | QuantitiesToFillProblem, Field(discriminator="state")]


class WithoutQuantityRead(Model):
    """Wiersze z listą (bez reguły, z opisu), w których tata nic jeszcze nie wpisał, rosnąco.

    ``sentence`` to zdanie okna „Uruchomić z zapisem?”, np. „3 wiersze bez ilości: 118, 203, 244”; ``None`` bez wierszy.
    """

    state: Literal["read"]
    sentence: str | None


class WithoutQuantityUnread(Model):
    """Pliku zbiorczego nie udało się odczytać, więc nie wiadomo, które wiersze są bez ilości; start zostaje możliwy."""

    state: Literal["unread"]


WithoutQuantity = Annotated[WithoutQuantityRead | WithoutQuantityUnread, Field(discriminator="state")]


class KindTableCell(Model):
    """Komórka N:AP wiersza na stronie rodzaju: wartość z pliku w kolumnie narzędzia, wpis taty, który robi wiersz, albo nic (0)."""

    source: CellSource
    value: int | Literal["nieliczbowa"]


class KindTableRow(Model):
    """Wiersz strony rodzaju: numer wiersza Pliku zbiorczego, teksty, po których tata go rozpoznaje, i komórki N:AP.

    Nigdy adres, numer zlecenia ani ``UMOWA`` (ADR 0016).
    """

    row: int
    state: RowState
    worker: str
    devices: str
    activities: str
    completed: str
    cells: list[KindTableCell]


class PriceListItem(Model):
    """Kolumna N:AP i nazwa pozycji cennika z wiersza 17 Pliku zbiorczego."""

    column: str
    name: str


class KindTableReady(Model):
    """Wiersze jednego rodzaju Ilości do uzupełnienia rosnąco po numerze; ``columns`` to N:AP po kolei.

    ``settled`` jak w ``QuantitiesToFillReady``.
    """

    state: Literal["ready"]
    read: CollectiveFileRead
    settled: bool
    columns: list[PriceListItem]
    rows: list[KindTableRow]


KindTable = Annotated[KindTableReady | QuantitiesToFillProblem, Field(discriminator="state")]
