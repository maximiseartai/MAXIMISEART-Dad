"""Atrapa efenix z odczytów stron w Logach Wyceny w efenix: zlecenia, ceny i dzień, które okno efenix zobaczy w
odtworzeniu Uruchomienia (#847, ``odtworzenie``).

Logi nie niosą numeru zlecenia ani danych adresowych (reguła danych, ADR 0025), więc zlecenie Atrapy ma numer z
``NUMER ZL.`` odtworzonego Pliku zbiorczego (``ScopedOrder``, ten sam odczyt zakresu co w procesie), a ``Dane
adresowe`` to syntetyczny ``ADRES`` tego wiersza (``Fed.addresses``) zmieniony w częściach, którymi według Logów się
od niego różniły (``LoggedResult.address``). Lista wyników to pierwsze szukanie zlecenia w Logach: wiersz z
``same_number`` ma numer z pliku, a każdy inny numer z pliku z dopiskiem, który szukanie po części numeru też znajduje;
status i login realizatora są z Logów. Numer, który Atrapa ma już z wcześniejszego wiersza Pliku zbiorczego, to w efenix
to samo zlecenie, więc Atrapa nie dodaje go drugi raz: jego stan zmienia się w trakcie Uruchomienia (po Przekazaniu
późniejszy wiersz widzi „Do akceptacji”), a ``ADRES`` późniejszego wiersza różni się od ``Dane adresowe`` tego zlecenia
częściami z jego Logów. Zlecenie, którego stronę okno otworzyło, ma stan strony z pierwszego otwarcia
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

from atrapy.atrapa_efenix import AtrapaEfenix, atrapa_efenix
from atrapy.model_efenix import CATALOG, PRICES, EfenixOrder

SYNTHETIC_ADDRESS: Final = "ul. Odtworzeniowa {row}"
"""``ADRES`` wiersza odtworzonego pliku, który reguła adresu efenix rozbiera (rodzaj, nazwa ulicy, numer)."""
_UNREAD_FILE_ADDRESS: Final = "ul. Odtworzeniowa/bez rozbioru {row}"
"""``ADRES`` wiersza, którego reguła adresu w Logach nie rozebrała: z ukośnikiem w nazwie ulicy."""
_UNREAD_EFENIX_ADDRESS: Final = "Dane adresowe bez rodzaju {row}"
_OTHER_STREET: Final = "Inna"
_FLAT: Final = " Lokal 7"
_CODES: Final = frozenset(position.code for position in CATALOG)


@dataclass(frozen=True)
class ScopedOrder:
    """Zlecenie odtworzonego Pliku zbiorczego tak, jak je czyta Wycena (``efenix_orders.CollectiveOrder``): wiersz i
    ``NUMER ZL.``."""

    row: int
    number: str | None


@dataclass(frozen=True)
class Fed:
    """Atrapa z Logów: zlecenia, cena każdej pozycji po kodzie, granice (tekst, czy blokuje) i ``ADRES`` wierszy
    Pliku zbiorczego, które nie mają ``SYNTHETIC_ADDRESS``."""

    orders: tuple[EfenixOrder, ...]
    prices: Mapping[str, Decimal]
    limits: tuple[tuple[str, bool], ...]
    addresses: Mapping[int, str]


@dataclass(frozen=True)
class _Synthetic:
    """Adres syntetyczny po częściach reguły adresu: druga nazwa ulicy, numer domu i lokal."""

    other_street: bool
    number: int
    flat: bool

    @classmethod
    def of(cls, row: int) -> _Synthetic:
        """``SYNTHETIC_ADDRESS`` wiersza ``row``."""

        return cls(other_street=False, number=row, flat=False)

    @property
    def text(self) -> str:
        street = f"Odtworzeniowa {_OTHER_STREET}" if self.other_street else "Odtworzeniowa"
        return f"ul. {street} {self.number}{_FLAT if self.flat else ''}"

    def differing(self, parts: Sequence[str]) -> _Synthetic:
        """Adres, który różni się od tego dokładnie częściami ``parts`` spośród ulicy, numeru domu i lokalu."""

        return _Synthetic(
            other_street=self.other_street != (AddressPart.STREET.value in parts),
            number=self.number + 1000 if AddressPart.NUMBER.value in parts else self.number,
            flat=self.flat != (AddressPart.FLAT.value in parts),
        )


def unread(orders: Sequence[LoggedOrder]) -> list[str]:
    """Granice blokujące: szukanie z trafieniami bez odczytu wierszy listy (Logi sprzed #843)."""

    if any(
        step.action is WindowAction.SEARCH and step.found and step.results is None for order in orders for step in order.steps
    ):
        return [
            "Logi Wyceny w efenix nie mają odczytu wierszy listy po szukaniu (Logi sprzed #843), więc Atrapa nie wie, co pokazać"
        ]
    return []


@dataclass(frozen=True)
class _Shown:
    """``Dane adresowe`` zlecenia Atrapy: tekst i części (``None``: bez rozbioru)."""

    text: str
    parts: _Synthetic | None

    @classmethod
    def of(cls, file: _Synthetic, differences: Sequence[str], row: int) -> _Shown:
        """``Dane adresowe``, które różnią się od ``ADRES`` ``file`` wiersza ``row`` częściami ``differences`` z Logów;
        przy ``ADRES`` bez rozbioru to ``file``."""

        if AddressPart.EFENIX_UNREAD.value in differences:
            return cls(_UNREAD_EFENIX_ADDRESS.format(row=row), None)
        parts = file.differing(differences)
        return cls(parts.text, parts)


def fed(orders: Sequence[LoggedOrder], scoped: Sequence[ScopedOrder]) -> Fed:
    numbers = {order.row: order.number for order in scoped}
    atrapa: list[EfenixOrder] = []
    shown: dict[str, _Shown] = {}
    addresses: dict[int, str] = {}
    limits: list[tuple[str, bool]] = []
    for order in orders:
        results = _results(order)
        if not results:
            continue
        number = numbers.get(order.row)
        if number is None:
            limits.append(
                (
                    f"wiersz {order.row} Pliku zbiorczego nie ma w odtworzeniu zlecenia z NUMER ZL.",
                    False,
                )
            )
            continue
        earlier = dict(shown)
        file = _file_address(order.row, results, earlier.get(number))
        file_text = (
            _UNREAD_FILE_ADDRESS.format(row=order.row)
            if any(AddressPart.FILE_UNREAD.value in result.address for result in results)
            else file.text
        )
        if file_text != SYNTHETIC_ADDRESS.format(row=order.row):
            addresses[order.row] = file_text
        for index, result in enumerate(results, start=1):
            listed_number = number if result.same_number else f"{number}-{index}"
            if listed_number not in earlier:
                shown[listed_number] = _Shown.of(file, result.address, order.row)
                atrapa.append(_listed(order, result, index, listed_number, shown[listed_number].text))
            if [part.value for part in address_differences(file_text, shown[listed_number].text)] != result.address:
                limits.append((f"wiersz {order.row}: Atrapa nie umie pokazać różnicy adresu {result.address}", False))
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
    return Fed(tuple(atrapa), prices, tuple(dict.fromkeys(limits)), addresses)


@contextmanager
def started(fed: Fed, today: date) -> Iterator[AtrapaEfenix]:
    with atrapa_efenix(fed.orders, today=today, prices=fed.prices) as atrapa:
        yield atrapa


def _results(order: LoggedOrder) -> list[LoggedResult]:
    search = next((step for step in order.steps if step.action is WindowAction.SEARCH), None)
    return [] if search is None or search.results is None else list(search.results)


def _file_address(row: int, results: Sequence[LoggedResult], shown: _Shown | None) -> _Synthetic:
    """``ADRES`` wiersza ``row`` po częściach: ``SYNTHETIC_ADDRESS`` wiersza, a gdy jego numer Atrapa pokazuje już z
    wcześniejszego wiersza (``shown``) z rozebranymi ``Dane adresowe``, adres różny od nich częściami wyniku z tym
    numerem w Logach."""

    same = next((result for result in results if result.same_number), None)
    if shown is None or shown.parts is None or same is None:
        return _Synthetic.of(row)
    return shown.parts.differing(same.address)


def _listed(order: LoggedOrder, result: LoggedResult, index: int, number: str, address: str) -> EfenixOrder:
    """Wiersz listy wyników ``index`` zlecenia ``order`` w Atrapie: zlecenie ``number`` z ``Dane adresowe``
    ``address``."""

    opened = _first(order.steps, WindowAction.OPEN) if result.same_number else None
    emmett = _first(order.steps, WindowAction.EMMETT) if result.same_number else None
    return EfenixOrder(
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
