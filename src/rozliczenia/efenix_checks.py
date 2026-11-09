"""Sprawdzenia zlecenia Wyceny w efenix: czyste reguły porównania zlecenia z Pliku zbiorczego z tym, co pokazał efenix.

Kolejność sprawdzeń to kolejność ``OrderProblem``, a pierwsza niezgodność jest błędem zlecenia: numer i data w Pliku
zbiorczym (``searched_number``), potem wiersze listy efenix po szukaniu (``listing``): dokładnie jedno zlecenie o
``Numer dokumentu`` równym numerowi, status „Do wyceny”, „Rozliczone” albo „Do akceptacji”, realizator równy ``WYKONAWCA``
po ``normalize_text``, jak Przebieg rozliczeń grupuje ``WYKONAWCA``, i ``Dane adresowe`` równe ``ADRES`` (``efenix_address``), a na końcu data wykonania pusta albo różna od dnia z ``DATA``
najwyżej o ``DATE_TOLERANCE`` w którąkolwiek stronę (``date_problem``; tata, po runie z 4.11.2026, #961). Datę w tej
tolerancji proces zostawia w efenix bez zmian. Zlecenie „Rozliczone” zgodne z plikiem nie jest niezgodnością, tylko Zleceniem rozliczonym
(``Settled``), a zlecenie „Do akceptacji” zgodne z plikiem Zleceniem przekazanym (``Forwarded``); żadnego z nich proces
nie otwiera. Pustą datę wykonania proces ustawia z ``DATA``, a dzień, którego efenix nie
przyjął, to ``DateRefused``. Odczyt wiersza listy dla Logów Uruchomienia to ``ListedRead``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
import enum
from typing import Final

from .efenix_address import AddressPart, address_differences, same_address
from .efenix_orders import CollectiveOrder
from .efenix_window import ACCEPTANCE_STATUS, ListedOrder
from .text import normalize_text

__all__ = [
    "DATE_TOLERANCE",
    "PRICING_STATUS",
    "SETTLED_STATUS",
    "DateRefused",
    "Forwarded",
    "ListedRead",
    "OrderProblem",
    "Settled",
    "date_problem",
    "listing",
    "read_listed",
    "searched_number",
]

PRICING_STATUS: Final = "Do wyceny"
SETTLED_STATUS: Final = "Rozliczone"
DATE_TOLERANCE: Final = timedelta(days=3)
"""Największa różnica między datą wykonania w efenix a dniem z ``DATA``, w obie strony, która nie jest niezgodnością."""


class OrderProblem(enum.Enum):
    """Niezgodność zlecenia z efenix, w kolejności sprawdzeń."""

    NO_NUMBER = enum.auto()
    NO_DATE = enum.auto()
    UNKNOWN_NUMBER = enum.auto()
    SEVERAL_FOUND = enum.auto()
    OTHER_STATUS = enum.auto()
    OTHER_REALIZATOR = enum.auto()
    OTHER_ADDRESS = enum.auto()
    OTHER_DATE = enum.auto()
    NOT_FORWARDED = enum.auto()
    """Po Przekazaniu do akceptacji ponowne szukanie nie pokazuje zlecenia ze statusem „Do akceptacji”."""


class DateRefused(enum.Enum):
    """efenix nie przyjął dnia z ``DATA`` jako daty wykonania, więc proces nie ładuje Wyceny Emmetta ani nie wpisuje ilości."""

    OUT_OF_RANGE = enum.auto()
    """Kalendarz efenix zamienił dzień na dzisiejszy (dzień po dziś albo przed pierwszym dniem poprzedniego miesiąca), więc
    narzędzie niczego nie wysłało."""
    NOT_SAVED = enum.auto()
    """Po „Potwierdź” ponownie otwarta strona zlecenia nie ma tego dnia jako daty wykonania."""


@dataclass(frozen=True)
class ListedRead:
    """Wiersz listy zleceń po szukaniu tak, jak trafia do Logów Uruchomienia, bez danych adresowych i bez numeru:
    ``Numer dokumentu`` równy ``NUMER ZL.`` z pliku (``same_number``), status i login realizatora jak na liście
    (``realizator`` ``None`` bez loginu) i części adresu, którymi ``Dane adresowe`` różnią się od ``ADRES`` z pliku
    (``address``, pusta krotka to ten sam adres)."""

    same_number: bool
    status: str
    realizator: str | None
    address: tuple[AddressPart, ...]


def read_listed(order: CollectiveOrder, listed: ListedOrder) -> ListedRead:
    return ListedRead(
        same_number=listed.number == order.number,
        status=listed.status,
        realizator=listed.realizator,
        address=address_differences(order.address, listed.address),
    )


@dataclass(frozen=True)
class Settled:
    """Zlecenie rozliczone: zlecenie listy zgodne z Plikiem zbiorczym ma w efenix status „Rozliczone”, więc proces go nie
    otwiera, niczego w nim nie zmienia i nie stawia mu Znacznika efenix."""

    listed: ListedOrder


@dataclass(frozen=True)
class Forwarded:
    """Zlecenie przekazane: zlecenie listy zgodne z Plikiem zbiorczym ma w efenix status „Do akceptacji”, bo przekazał je
    ten przebieg, wcześniejszy albo tata, więc proces niczego w nim nie zmienia, a w Pliku zbiorczym dostaje Znacznik
    przekazania."""

    listed: ListedOrder


def searched_number(order: CollectiveOrder) -> tuple[str, date] | OrderProblem:
    """Numer, po którym proces szuka zlecenia, i dzień z ``DATA`` albo niezgodność, którą widać bez efenix: wiersz bez
    ``NUMER ZL.`` albo bez daty w ``DATA``."""

    if order.number is None:
        return OrderProblem.NO_NUMBER
    if order.day is None:
        return OrderProblem.NO_DATE
    return order.number, order.day


def listing(order: CollectiveOrder, listed: Sequence[ListedOrder]) -> ListedOrder | Settled | Forwarded | OrderProblem:
    """Jedyne zlecenie listy o numerze ``order`` zgodne z Plikiem zbiorczym albo pierwsza niezgodność; zgodne zlecenie o
    statusie „Rozliczone” to ``Settled``, a o statusie „Do akceptacji” ``Forwarded``.

    Wiersz listy o innym ``Numer dokumentu`` (szukanie po części numeru) nie jest trafieniem. Zlecenie „Rozliczone” i „Do
    akceptacji” też musi mieć realizatora i ``Dane adresowe`` z pliku, bo inaczej ``NUMER ZL.`` wskazuje inne zlecenie.
    """

    hits = [candidate for candidate in listed if candidate.number == order.number]
    if not hits:
        return OrderProblem.UNKNOWN_NUMBER
    if len(hits) > 1:
        return OrderProblem.SEVERAL_FOUND
    [hit] = hits
    settled = _is_status(hit, SETTLED_STATUS)
    forwarded = _is_status(hit, ACCEPTANCE_STATUS)
    if not (settled or forwarded or _is_status(hit, PRICING_STATUS)):
        return OrderProblem.OTHER_STATUS
    if hit.realizator is None or normalize_text(hit.realizator) != normalize_text(order.worker):
        return OrderProblem.OTHER_REALIZATOR
    if not same_address(order.address, hit.address):
        return OrderProblem.OTHER_ADDRESS
    if settled:
        return Settled(hit)
    return Forwarded(hit) if forwarded else hit


def _is_status(hit: ListedOrder, status: str) -> bool:
    return hit.status.casefold().split() == status.casefold().split()


def date_problem(order: CollectiveOrder, executed: date | None) -> OrderProblem | None:
    """Data wykonania z efenix różni się od dnia z ``DATA`` o więcej niż ``DATE_TOLERANCE``; pusta data wykonania nie jest
    niezgodnością."""

    if executed is None:
        return None
    return OrderProblem.OTHER_DATE if order.day is None or abs(executed - order.day) > DATE_TOLERANCE else None
