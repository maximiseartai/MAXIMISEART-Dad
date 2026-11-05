"""Pozycje wyceny efenix: przypisanie kolumn Ilości usług do kodów pozycji i czyste reguły porównania ilości i kwot.

Przypisanie (``POSITION_OF_COLUMN``) to konfiguracja narzędzia ze specyfikacji #741, wersjonowana z narzędziem, nie
dane taty: kolumna Pliku zbiorczego → kod pozycji efenix (``NNN`` z ``INDEKS_NNN``). Kolumny Ilości usług bez pary to
``UNPAIRED_COLUMNS``. Pozycja efenix bez kolumny ma w Pliku zbiorczym ilość 0, więc ilość wpisana w niej w efenix
zawsze różni się od pliku. Reguły biorą ilości pliku po kodach (``file_quantities``) i ilości ze strony zlecenia
(kod → ilość, pole puste to 0): wycena, która już jest, różni się od pliku ilością albo kwotą (``priced_differently``); Wycena Emmetta
jest sprzeczna z plikiem w pozycjach, w których Emmett wpisał ilość inną niż plik (``emmett_conflicts``); dopisać
trzeba ilości pliku w pozycjach pustych u Emmetta (``to_enter``), a pozycja pusta u Emmetta przy 0 w pliku zostaje pusta.
Strona zlecenia efenix bywa bez części pozycji z przypisania: brak pozycji, w której plik ma 0 albo pustą komórkę, nie
przeszkadza, bo ta pozycja i tak zostałaby w efenix pusta, a brak pozycji, w której plik ma ilość, to błąd zlecenia
(``missing_positions``).
Strona zlecenia jest taka, jaką narzędzie zostawia po Wycenie Emmetta (``as_left_after_emmett``), gdy ma dokładnie
ilości Emmetta i ilości, które narzędzie zaczęło wpisywać (Ślad Wyceny Emmetta), a każda inna pozycja jest pusta. Kwota
końcowa efenix i ``Kwota`` (AU) są równe co do grosza (``same_amount``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import enum
from types import MappingProxyType
from typing import Final

from .efenix_checks import DateRefused, OrderProblem
from .efenix_orders import QUANTITY_COLUMNS, CollectiveOrder
from .order_facts import NON_NUMERIC

__all__ = [
    "POSITION_OF_COLUMN",
    "UNPAIRED_COLUMNS",
    "Conflict",
    "MissingPositions",
    "NotWholeQuantities",
    "OrderFault",
    "OtherAmount",
    "PageRead",
    "PricedDifferently",
    "UnpairedColumns",
    "as_left_after_emmett",
    "column_of",
    "emmett_conflicts",
    "file_quantities",
    "missing_positions",
    "priced_differently",
    "same_amount",
    "to_enter",
]

POSITION_OF_COLUMN: Final[Mapping[str, str]] = MappingProxyType(
    {
        "O": "012",
        "P": "013",
        "Q": "014",
        "R": "017",
        "S": "016",
        "T": "019",
        "U": "027",
        "V": "029",
        "Y": "009",
        "Z": "010",
        "AD": "007",
        "AE": "008",
        "AG": "015",
        "AH": "018",
        "AJ": "023",
        "AK": "024",
        "AL": "025",
        "AM": "026",
        "AN": "028",
        "AP": "021",
    }
)
"""Pary pewne ze specyfikacji #741 (zgadzają się ceny); tata potwierdza je raz przed pierwszym przebiegiem."""
UNPAIRED_COLUMNS: Final = tuple(column for column in QUANTITY_COLUMNS if column not in POSITION_OF_COLUMN)
"""Kolumny Ilości usług bez pewnej pozycji efenix; ilość w nich to błąd zlecenia."""
_COLUMN_OF_POSITION: Final = {position: column for column, position in POSITION_OF_COLUMN.items()}


@dataclass(frozen=True)
class UnpairedColumns:
    """Zlecenie ma ilość w kolumnach bez pozycji efenix, więc narzędzie nie wie, gdzie ją wpisać."""

    columns: tuple[str, ...]


@dataclass(frozen=True)
class NotWholeQuantities:
    """Zlecenie ma w kolumnach z pozycją efenix ilość, która nie jest liczbą całkowitą większą od 0."""

    columns: tuple[str, ...]


@dataclass(frozen=True)
class PricedDifferently:
    """Wycena w efenix już jest i różni się od Pliku zbiorczego: obie kwoty i pozycje z inną ilością (rosnąco)."""

    efenix_amount: Decimal
    file_amount: Decimal
    positions: tuple[str, ...]


class PageRead(enum.Enum):
    """Odczyt strony zlecenia w Wycenie w efenix, po którym proces sprawdza, czy są na niej pozycje z ilością w pliku."""

    OPENED = "otwarcie zlecenia"
    AFTER_DATE = "ponowne otwarcie zlecenia po ustawieniu daty wykonania"
    AFTER_EMMETT = "strona po załadowaniu Wyceny Emmetta"


@dataclass(frozen=True)
class MissingPositions:
    """Strona zlecenia nie ma pozycji, w których Plik zbiorczy ma ilość (rosnąco po kodzie); ``read``: odczyt strony,
    który to pokazał, więc i to, co proces zmienił już w zleceniu w efenix."""

    positions: tuple[str, ...]
    read: PageRead


@dataclass(frozen=True)
class OtherAmount:
    """Kwota końcowa, którą efenix odesłał po dopisaniu ilości, różni się od ``Kwota`` (AU)."""

    efenix_amount: Decimal
    file_amount: Decimal


OrderFault = OrderProblem | DateRefused | UnpairedColumns | NotWholeQuantities | MissingPositions | PricedDifferently | OtherAmount
"""Powód, dla którego zlecenie zostaje tacie jako błąd."""


@dataclass(frozen=True)
class Conflict:
    """Pozycja, w której Emmett wpisał ilość inną niż Plik zbiorczy."""

    position: str
    emmett: int
    file: int


def column_of(position: str) -> str | None:
    """Kolumna Pliku zbiorczego pozycji efenix ``position``; ``None`` dla pozycji bez kolumny."""

    return _COLUMN_OF_POSITION.get(position)


def file_quantities(order: CollectiveOrder) -> Mapping[str, int] | UnpairedColumns | NotWholeQuantities:
    """Ilości zlecenia z Pliku zbiorczego po kodach pozycji efenix, albo kolumny, których nie da się przepisać.

    Kolumny bez pary sprawdzane są pierwsze, bo z ilością w nich wycena nie może się zgodzić z ``Kwota`` (AU).
    """

    unpaired = tuple(column for column in UNPAIRED_COLUMNS if column in order.quantities)
    if unpaired:
        return UnpairedColumns(unpaired)
    not_whole = tuple(
        column for column, value in order.quantities.items() if value == NON_NUMERIC or (isinstance(value, int) and value < 0)
    )
    if not_whole:
        return NotWholeQuantities(not_whole)
    return {POSITION_OF_COLUMN[column]: value for column, value in order.quantities.items() if isinstance(value, int)}


def missing_positions(file: Mapping[str, int], on_page: Mapping[str, int], read: PageRead) -> MissingPositions | None:
    """Pozycje, w których plik ``file`` (``file_quantities``: tylko ilości różne od 0) ma ilość, a strona zlecenia z
    odczytu ``read`` ich nie ma; ``None``, gdy strona ma każdą z nich. Pozycji z 0 w pliku strona mieć nie musi: zostaje
    w efenix pusta, jak gdyby była."""

    positions = tuple(sorted(position for position in file if position not in on_page))
    return MissingPositions(positions, read) if positions else None


def same_amount(efenix: Decimal, file: Decimal) -> bool:
    """Kwota z efenix jest równa kwocie z pliku co do grosza (AU policzona przez Excel bywa ułamkiem binarnym)."""

    cent = Decimal("0.01")
    return efenix.quantize(cent) == file.quantize(cent)


def priced_differently(
    file: Mapping[str, int], on_page: Mapping[str, int], efenix_amount: Decimal, file_amount: Decimal
) -> PricedDifferently | None:
    """Wycena, która już jest w efenix, różni się od pliku ilością którejś pozycji albo kwotą; ``None``, gdy się zgadza."""

    positions = tuple(sorted(position for position in file.keys() | on_page.keys() if file.get(position, 0) != on_page.get(position, 0)))
    if positions or not same_amount(efenix_amount, file_amount):
        return PricedDifferently(efenix_amount, file_amount, positions)
    return None


def emmett_conflicts(file: Mapping[str, int], emmett: Mapping[str, int]) -> tuple[Conflict, ...]:
    """Pozycje, w których Emmett wpisał ilość, a plik ma inną (także 0), rosnąco po kodzie."""

    return tuple(
        Conflict(position, quantity, file.get(position, 0))
        for position, quantity in sorted(emmett.items())
        if quantity != 0 and quantity != file.get(position, 0)
    )


def as_left_after_emmett(emmett: Mapping[str, int], entered: Mapping[str, int], on_page: Mapping[str, int]) -> bool:
    """Strona ``on_page`` ma tylko ilości, które zostawia narzędzie po Wycenie Emmetta ``emmett``: w każdej pozycji, w
    której Emmett wpisał ilość, tę samą ilość, w każdej pozycji, w której narzędzie zaczęło wpisywać ilość (``entered``),
    tę ilość, a w każdej innej nic.

    Ilość w innej pozycji wpisał ktoś inny niż narzędzie. Pusta pozycja z ``entered`` to ilość usunięta w efenix albo
    taka, której efenix nie zapisał przed przerwaniem; strona ich nie odróżnia, więc obie to wycena inna niż po narzędziu.
    """

    left = {position: quantity for position, quantity in (*emmett.items(), *entered.items()) if quantity}
    return {position: quantity for position, quantity in on_page.items() if quantity} == left


def to_enter(file: Mapping[str, int], emmett: Mapping[str, int]) -> dict[str, int]:
    """Ilości pliku do wpisania w pozycjach pustych u Emmetta; pozycji z 0 w pliku ``file`` nie ma, więc zostaje pusta."""

    return {position: quantity for position, quantity in sorted(file.items()) if emmett.get(position, 0) == 0}
