"""Pozycje wyceny efenix: przypisanie kolumn Ilości usług do kodów pozycji i czyste reguły porównania ilości i kwot.

Przypisanie (``POSITION_OF_COLUMN``) to konfiguracja narzędzia ze specyfikacji #741, wersjonowana z narzędziem, nie
dane taty: kolumna Pliku zbiorczego → kod pozycji efenix (``NNN`` z ``INDEKS_NNN``). Kolumny Ilości usług bez pary to
``UNPAIRED_COLUMNS``. Pozycja efenix bez kolumny ma w Pliku zbiorczym ilość 0. Reguły biorą ilości pliku po kodach
(``file_quantities``) i ilości ze strony zlecenia (kod → ilość, pole puste to 0).
Wycenę zlecenia proces dokańcza do Pliku zbiorczego tylko w górę (ADR 0026, ``completion``): w każdej pozycji, w której
strona ma mniej niż plik, wpisuje ilość z pliku, także w miejsce ilości Emmetta, a pozycji, w której strona ma więcej niż
plik (także ilość w pozycji z 0 w pliku albo bez kolumny), nie obniża i nie czyści, tylko zgłasza ją jako nadmiar.
Strona zlecenia efenix bywa bez części pozycji z przypisania: brak pozycji, w której plik ma 0 albo pustą komórkę, nie
przeszkadza, bo ta pozycja i tak zostałaby w efenix pusta, a brak pozycji, w której plik ma ilość, to błąd zlecenia
(``missing_positions``). Kwota końcowa efenix i ``Kwota`` (AU) są równe co do grosza (``same_amount``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import enum
from types import MappingProxyType
from typing import Final

from .efenix_checks import DateRefused, OrderProblem
from .efenix_orders import PRICED_COLUMNS, CollectiveOrder
from .efenix_window import ForwardRefusal
from .order_facts import NON_NUMERIC

__all__ = [
    "POSITION_OF_COLUMN",
    "UNPAIRED_COLUMNS",
    "Completion",
    "Excess",
    "FileQuantities",
    "MissingPositions",
    "NotWholeQuantities",
    "OrderFault",
    "OtherAmount",
    "PageRead",
    "UnpairedColumns",
    "column_of",
    "completion",
    "file_quantities",
    "missing_positions",
    "same_amount",
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
UNPAIRED_COLUMNS: Final = tuple(column for column in PRICED_COLUMNS if column not in POSITION_OF_COLUMN)
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


FileQuantities = Mapping[str, int] | UnpairedColumns | NotWholeQuantities
"""Ilości zlecenia z Pliku zbiorczego po kodach pozycji efenix albo kolumny, których nie da się przepisać."""

OrderFault = OrderProblem | DateRefused | UnpairedColumns | NotWholeQuantities | MissingPositions | OtherAmount | ForwardRefusal
"""Powód, dla którego zlecenie zostaje tacie jako błąd; ``ForwardRefusal`` to gotowe zlecenie, któremu efenix odmówił
Przekazania do akceptacji."""


@dataclass(frozen=True)
class Excess:
    """Pozycja ``position``, w której efenix ma ilość ``efenix`` większą niż ``file`` z Pliku zbiorczego (0 w pozycji bez
    ilości w pliku albo bez kolumny)."""

    position: str
    efenix: int
    file: int


@dataclass(frozen=True)
class Completion:
    """Dokończenie wyceny zlecenia do Pliku zbiorczego: ilości pliku do wpisania w pozycjach, w których strona ma mniej
    niż plik (``to_enter``, rosnąco po kodzie), i pozycje, w których strona ma więcej niż plik (``excess``, rosnąco po
    kodzie), których proces nie zmienia."""

    to_enter: Mapping[str, int]
    excess: tuple[Excess, ...]


def column_of(position: str) -> str | None:
    """Kolumna Pliku zbiorczego pozycji efenix ``position``; ``None`` dla pozycji bez kolumny."""

    return _COLUMN_OF_POSITION.get(position)


def file_quantities(order: CollectiveOrder) -> FileQuantities:
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


def completion(file: Mapping[str, int], on_page: Mapping[str, int]) -> Completion:
    """Dokończenie wyceny strony ``on_page`` do pliku ``file`` tylko w górę: ilość pliku w każdej pozycji, w której strona
    ma mniej, i nadmiar w każdej pozycji, w której strona ma więcej. Pozycja z równą ilością nie trafia do żadnego z nich,
    więc wycena zgodna z plikiem daje dokończenie puste."""

    to_enter = {position: quantity for position, quantity in sorted(file.items()) if on_page.get(position, 0) < quantity}
    excess = tuple(
        Excess(position, quantity, file.get(position, 0))
        for position, quantity in sorted(on_page.items())
        if quantity > file.get(position, 0)
    )
    return Completion(MappingProxyType(to_enter), excess)
