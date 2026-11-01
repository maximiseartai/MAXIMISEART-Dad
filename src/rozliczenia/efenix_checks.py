"""Sprawdzenia zlecenia Wyceny w efenix: czyste reguły porównania zlecenia z Pliku zbiorczego z tym, co pokazał efenix.

Kolejność sprawdzeń to kolejność ``OrderProblem``, a pierwsza niezgodność jest błędem zlecenia: numer i data w Pliku
zbiorczym (``searched_number``), potem wiersze listy efenix po szukaniu (``listing``): dokładnie jedno zlecenie o
``Numer dokumentu`` równym numerowi, status „Do wyceny”, realizator równy ``WYKONAWCA`` bez wielkości liter i ``Dane
adresowe`` równe ``ADRES`` (``efenix_address``), a na końcu data wykonania pusta albo równa dniowi z ``DATA``
(``date_problem``). Pustą datę wykonania proces ustawia z ``DATA``, a dzień, którego efenix nie przyjął, to
``DateRefused``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
import enum
from typing import Final

from .efenix_address import same_address
from .efenix_orders import CollectiveOrder

__all__ = ["PRICING_STATUS", "DateRefused", "ListedOrder", "OrderProblem", "date_problem", "listing", "searched_number"]

PRICING_STATUS: Final = "Do wyceny"


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


class DateRefused(enum.Enum):
    """efenix nie przyjął dnia z ``DATA`` jako daty wykonania, więc proces nie ładuje Wyceny Emmetta ani nie wpisuje ilości."""

    OUT_OF_RANGE = enum.auto()
    """Kalendarz efenix zamienił dzień na dzisiejszy (dzień po dziś albo przed pierwszym dniem poprzedniego miesiąca), więc
    narzędzie niczego nie wysłało."""
    NOT_SAVED = enum.auto()
    """Po „Potwierdź” ponownie otwarta strona zlecenia nie ma tego dnia jako daty wykonania."""


@dataclass(frozen=True)
class ListedOrder:
    """Wiersz listy zleceń efenix po szukaniu: ``Numer dokumentu``, status, realizator (login, ``None`` bez niego),
    ``Dane adresowe`` bez linii województwa i identyfikator, którym otwiera się stronę zlecenia."""

    number: str
    status: str
    realizator: str | None
    address: str
    order_id: str


def searched_number(order: CollectiveOrder) -> tuple[str, date] | OrderProblem:
    """Numer, po którym proces szuka zlecenia, i dzień z ``DATA`` albo niezgodność, którą widać bez efenix: wiersz bez
    ``NUMER ZL.`` albo bez daty w ``DATA``."""

    if order.number is None:
        return OrderProblem.NO_NUMBER
    if order.day is None:
        return OrderProblem.NO_DATE
    return order.number, order.day


def listing(order: CollectiveOrder, listed: Sequence[ListedOrder]) -> ListedOrder | OrderProblem:
    """Jedyne zlecenie listy o numerze ``order`` zgodne z Plikiem zbiorczym albo pierwsza niezgodność.

    Wiersz listy o innym ``Numer dokumentu`` (szukanie po części numeru) nie jest trafieniem.
    """

    hits = [candidate for candidate in listed if candidate.number == order.number]
    if not hits:
        return OrderProblem.UNKNOWN_NUMBER
    if len(hits) > 1:
        return OrderProblem.SEVERAL_FOUND
    [hit] = hits
    if hit.status.casefold().split() != PRICING_STATUS.casefold().split():
        return OrderProblem.OTHER_STATUS
    if hit.realizator is None or hit.realizator.casefold() != order.worker.casefold():
        return OrderProblem.OTHER_REALIZATOR
    if not same_address(order.address, hit.address):
        return OrderProblem.OTHER_ADDRESS
    return hit


def date_problem(order: CollectiveOrder, executed: date | None) -> OrderProblem | None:
    """Data wykonania z efenix jest inna niż dzień z ``DATA``; pusta data wykonania nie jest niezgodnością."""

    return OrderProblem.OTHER_DATE if executed is not None and executed != order.day else None
