"""Atrapa efenix z odczytów stron w Logach Wyceny w efenix: zlecenia, ceny i dzień, które okno efenix zobaczy w
odtworzeniu Uruchomienia (#847, ``odtworzenie``).

Logi nie niosą numeru zlecenia ani danych adresowych (reguła danych, ADR 0025), więc zlecenie Atrapy ma numer z
``NUMER ZL.`` odtworzonego Pliku zbiorczego (``ScopedOrder``, ten sam odczyt zakresu co w procesie), a ``Dane
adresowe`` to syntetyczny ``ADRES`` tego wiersza (``file_addresses``) zmieniony w częściach, którymi według Logów się
od niego różniły (``LoggedResult.address``). Lista wyników to pierwsze szukanie zlecenia w Logach: wiersz z
``same_number`` ma numer z pliku, a każdy inny numer z pliku z dopiskiem, który szukanie po części numeru też znajduje;
status i login realizatora są z Logów. Zlecenie, którego stronę okno otworzyło, ma stan strony z pierwszego otwarcia
(data wykonania, ilości i pozycje na stronie), a propozycję Emmetta z odczytu strony po Wycenie Emmetta.

Ceny pozycji wynikają z kwot w Logach (``_prices``): zmiana kwoty końcowej po wpisaniu ilości to cena pozycji razy
zmiana jej ilości, a kwota strony, na której tylko jedna pozycja z ilością ma nieznaną cenę, daje tę cenę. Cena, której
Logi nie wyznaczają, zostaje ceną Atrapy, a ``Fed.limits`` nazywa ją granicą, gdy pozycja ma gdzieś ilość.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from rozliczenia.centrum.run_logs import (
    LoggedOrder,
    LoggedQuantity,
    LoggedResult,
    LoggedStep,
)
from rozliczenia.efenix_address import AddressPart, address_differences
from rozliczenia.efenix_window import WindowAction

from model_efenix import CATALOG, PRICES, EfenixOrder

from tests.fixtures.atrapa_efenix import AtrapaEfenix, atrapa_efenix

SYNTHETIC_ADDRESS: Final = "ul. Odtworzeniowa {row}"
"""``ADRES`` wiersza odtworzonego pliku, który reguła adresu efenix rozbiera (rodzaj, nazwa ulicy, numer)."""
_UNREAD_FILE_ADDRESS: Final = "Odtworzeniowa bez rodzaju {row}"
"""``ADRES`` wiersza, którego reguła adresu w Logach nie rozebrała: bez rodzaju ulicy."""
_UNREAD_EFENIX_ADDRESS: Final = "Dane adresowe bez rodzaju {row}"
_OTHER_STREET: Final = "Inna"
_FLAT: Final = " Lokal 7"
_CODES: Final = frozenset(position.code for position in CATALOG)


@dataclass(frozen=True)
class ScopedOrder:
    """Zlecenie odtworzonego Pliku zbiorczego tak, jak je czyta Wycena (``efenix_orders.CollectiveOrder``): wiersz,
    ``NUMER ZL.`` i ``ADRES``."""

    row: int
    number: str | None
    address: str


@dataclass(frozen=True)
class Fed:
    """Atrapa z Logów: zlecenia, cena każdej pozycji po kodzie i granice (tekst, czy blokuje)."""

    orders: tuple[EfenixOrder, ...]
    prices: Mapping[str, Decimal]
    limits: tuple[tuple[str, bool], ...]


def file_addresses(orders: Sequence[LoggedOrder]) -> dict[int, str]:
    """``ADRES`` wiersza Pliku zbiorczego, którego reguła adresu u taty nie rozebrała (część ``ADRES bez rozbioru``);
    każdy inny wiersz ma ``SYNTHETIC_ADDRESS``."""

    return {
        order.row: _UNREAD_FILE_ADDRESS.format(row=order.row)
        for order in orders
        if any(AddressPart.FILE_UNREAD.value in result.address for result in _results(order))
    }


def unread(orders: Sequence[LoggedOrder]) -> list[str]:
    """Granice blokujące: szukanie z trafieniami bez odczytu wierszy listy (Logi sprzed #843)."""

    if any(
        step.action is WindowAction.SEARCH and step.found and step.results is None for order in orders for step in order.steps
    ):
        return [
            "Logi Wyceny w efenix nie mają odczytu wierszy listy po szukaniu (Logi sprzed #843), więc Atrapa nie wie, co pokazać"
        ]
    return []


def fed(orders: Sequence[LoggedOrder], scoped: Sequence[ScopedOrder]) -> Fed:
    """Zlecenia Atrapy dla śladu ``orders`` z Logów i zakresu ``scoped`` odtworzonego Pliku zbiorczego."""

    by_row = {order.row: order for order in scoped}
    atrapa: list[EfenixOrder] = []
    limits: list[tuple[str, bool]] = []
    for order in orders:
        results = _results(order)
        if not results:
            continue
        collective = by_row.get(order.row)
        if collective is None or collective.number is None:
            limits.append(
                (
                    f"wiersz {order.row} Pliku zbiorczego nie ma w odtworzeniu zlecenia z NUMER ZL.",
                    False,
                )
            )
            continue
        for index, result in enumerate(results, start=1):
            listed, problem = _listed(order, collective, result, index)
            atrapa.append(listed)
            if problem is not None:
                limits.append((problem, False))
    prices, unknown = _prices(orders)
    if unknown:
        limits.append(
            (
                f"ceny pozycji {', '.join(sorted(unknown))} nie wynikają z kwot w Logach: Atrapa liczy je swoimi cenami",
                False,
            )
        )
    outside = sorted(
        {code for order in orders for step in order.steps for code in (step.quantities or {}) if code not in _CODES}
    )
    if outside:
        limits.append((f"pozycji {', '.join(outside)} nie ma na stronach Atrapy efenix", False))
    return Fed(tuple(atrapa), prices, tuple(dict.fromkeys(limits)))


@contextmanager
def started(fed: Fed, today: date) -> Iterator[AtrapaEfenix]:
    """Atrapa efenix ze zleceniami i cenami ``fed`` i dzisiejszym dniem kalendarza ``today`` na czas bloku."""

    with atrapa_efenix(fed.orders, today=today, prices=fed.prices) as atrapa:
        yield atrapa


def _results(order: LoggedOrder) -> list[LoggedResult]:
    search = next((step for step in order.steps if step.action is WindowAction.SEARCH), None)
    return [] if search is None or search.results is None else list(search.results)


def _listed(
    order: LoggedOrder, collective: ScopedOrder, result: LoggedResult, index: int
) -> tuple[EfenixOrder, str | None]:
    """Wiersz listy wyników ``index`` zlecenia ``order`` w Atrapie i granica, gdy Atrapa nie odda tej samej różnicy
    adresu co efenix taty."""

    assert collective.number is not None
    number = collective.number if result.same_number else f"{collective.number}-{index}"
    address = _efenix_address(result.address, order.row)
    opened = _first(order.steps, WindowAction.OPEN) if result.same_number else None
    emmett = _first(order.steps, WindowAction.EMMETT) if result.same_number else None
    listed = EfenixOrder(
        order_id=f"{order.row}-{index}",
        number=number,
        realizator=result.realizator or "",
        address=address,
        status=result.status,
        execution_date=None if opened is None else opened.execution_date,
        quantities={} if opened is None else _nonzero(opened.quantities),
        emmett={} if emmett is None else _nonzero(emmett.quantities),
        without=frozenset() if opened is None or opened.quantities is None else _CODES - set(opened.quantities),
    )
    differences = [part.value for part in address_differences(collective.address, address)]
    if differences != result.address:
        return (
            listed,
            f"wiersz {order.row}: Atrapa nie umie pokazać różnicy adresu {result.address}",
        )
    return listed, None


def _efenix_address(parts: Sequence[str], row: int) -> str:
    """``Dane adresowe``, które różnią się od ``SYNTHETIC_ADDRESS`` wiersza ``row`` dokładnie częściami ``parts``; przy
    ``ADRES`` bez rozbioru (``file_addresses``) to ten syntetyczny adres."""

    if AddressPart.EFENIX_UNREAD.value in parts:
        return _UNREAD_EFENIX_ADDRESS.format(row=row)
    street = f"Odtworzeniowa {_OTHER_STREET}" if AddressPart.STREET.value in parts else "Odtworzeniowa"
    number = str(row + 1000) if AddressPart.NUMBER.value in parts else str(row)
    flat = _FLAT if AddressPart.FLAT.value in parts else ""
    return f"ul. {street} {number}{flat}"


def _first(steps: Sequence[LoggedStep], action: WindowAction) -> LoggedStep | None:
    return next((step for step in steps if step.action is action), None)


def _nonzero(quantities: Mapping[str, LoggedQuantity] | None) -> dict[str, int]:
    return {code: quantity for code, quantity in (quantities or {}).items() if isinstance(quantity, int) and quantity}


def _prices(orders: Sequence[LoggedOrder]) -> tuple[dict[str, Decimal], set[str]]:
    """Ceny pozycji z kwot w Logach i kody pozycji z ilością, których ceny Logi nie wyznaczają."""

    known: dict[str, Decimal] = {}
    pages: list[tuple[Decimal, dict[str, int]]] = []
    for order in orders:
        page: dict[str, int] | None = None
        amount: Decimal | None = None
        for step in order.steps:
            if step.quantities is not None and step.amount is not None:
                page, amount = _whole(step.quantities), step.amount
                pages.append((amount, dict(page)))
            elif step.action is WindowAction.QUANTITY and page is not None and amount is not None and step.position is not None:
                if not isinstance(step.quantity, int) or step.amount is None:
                    continue
                change = step.quantity - page.get(step.position, 0)
                if change:
                    known.setdefault(step.position, (step.amount - amount) / change)
                page[step.position] = step.quantity
                amount = step.amount
                pages.append((amount, dict(page)))
    solved = True
    while solved:
        solved = False
        for amount, quantities in pages:
            unknown = [code for code, quantity in quantities.items() if quantity and code not in known]
            if len(unknown) == 1:
                [code] = unknown
                rest = sum(
                    (known[other] * quantity for other, quantity in quantities.items() if other != code and quantity),
                    Decimal(0),
                )
                known[code] = (amount - rest) / quantities[code]
                solved = True
    used = {code for _, quantities in pages for code, quantity in quantities.items() if quantity}
    prices = {code: known.get(code, price) for code, price in PRICES.items()}
    return prices, {code for code in used if code not in known and code in _CODES}


def _whole(quantities: Mapping[str, LoggedQuantity]) -> dict[str, int]:
    return {code: quantity for code, quantity in quantities.items() if isinstance(quantity, int)}
