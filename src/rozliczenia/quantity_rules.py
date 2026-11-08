"""Reguły ilości: Ilości usług z treści zlecenia (ADR 0012).

Jedyną operacją jest ``evaluate()``. Moduł nie zna skoroszytów, Komunikatów ani Centrum rozliczeń, bo używają go
Przygotowanie pliku zbiorczego (Wiersz danych Rejestru zleceń) i Kontrola ilości (Wiersz danych Pliku zbiorczego).
Oba dają mu wartości komórek, a treść zlecenia robi z nich tylko ``OrderContent.of``, więc świeżo przygotowany
Plik zbiorczy daje Kontroli ilości te same Ilości usług, które Przygotowanie w nim zapisało (ADR 0013).

``URZĄDZENIA`` są czytane jako składniki po normalizacji: małe litery, przecinki jak spacje, zwinięte spacje,
bez ``xg`` (także doklejonego, ``nokia zteXG``). Składnik może mieć krotność ``n*`` (``3*fut``, ``2* fut``).
Ilości powstają ze złożenia składników, więc nowa kombinacja znanych składników nie wymaga nowej reguły. Nowy
składnik to nowy wpis w ``_COMPONENTS``. Od składników zależą też liczba sztuk z ``CZYNNOŚCI`` (instalacja ręczna,
wizja), ilości z frazy ``CZYNNOŚCI`` w zleceniu bez routera (samo ``nokia`` z ``akt int``) i dodatek za usterkę po
godzinach według dnia i godziny ``DATA``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum, StrEnum, auto
from types import MappingProxyType
from typing import Final


class QuantityColumn(StrEnum):
    """Kolumna Ilości usług Pliku zbiorczego, w której Reguły ilości coś wpisują."""

    N = "N"
    O = "O"  # noqa: E741  (litera kolumny Pliku zbiorczego)
    P = "P"
    Q = "Q"
    S = "S"
    T = "T"
    V = "V"
    Z = "Z"
    AE = "AE"
    AG = "AG"
    AI = "AI"
    AK = "AK"
    AM = "AM"
    AN = "AN"
    AO = "AO"
    AP = "AP"


# Kolumny Ilości usług z opisu technika (CZYNNOŚCI ZREALIZOWANE); AK i AM Reguły ilości wypełniają tylko częściowo.
DESCRIPTION_COLUMNS: Final = ("Y", "AB", "AD", "AJ", "AK", "AL", "AM")

Quantities = Mapping[QuantityColumn, int]
"""Ilości usług zlecenia: kolumna → liczba, tylko różne od zera."""

_NONE: Final[Quantities] = MappingProxyType({})


@dataclass(frozen=True, order=True)
class WeekTime:
    """Dzień tygodnia i godzina z ``DATA`` bez daty dziennej: wszystko, co Reguły ilości czytają z daty zlecenia.

    ``weekday``: 0 to poniedziałek. Reguły nie dostają daty dziennej, więc nie mogą od niej zależeć.
    """

    weekday: int
    at: time


@dataclass(frozen=True)
class OrderContent:
    """Treść zlecenia, z której Reguły ilości wyznaczają Ilości usług: tekst komórek i pora zlecenia."""

    contract: str
    """``UMOWA``; pusta komórka to ``""``."""
    devices: str
    """``URZĄDZENIA``, dokładny tekst."""
    activities: str
    """``CZYNNOŚCI`` (kolumna wejścia, nigdy ``CZYNNOŚCI ZREALIZOWANE``)."""
    started: WeekTime
    """``DATA``: dzień tygodnia i godzina początku zlecenia."""

    @classmethod
    def of(cls, contract: object, devices: object, activities: object, started: datetime) -> OrderContent:
        """Treść zlecenia z wartości komórek Wiersza danych i daty z ``DATA``: komórka jako tekst, pusta to ``""``."""

        return cls(
            _cell_text(contract),
            _cell_text(devices),
            _cell_text(activities),
            WeekTime(started.weekday(), started.time().replace(second=0, microsecond=0)),
        )


@dataclass(frozen=True)
class ServiceQuantities:
    """Reguły ilości znają każdy składnik ``URZĄDZENIA``."""

    quantities: Quantities


@dataclass(frozen=True)
class FromDescription:
    """Zlecenie rozliczane z opisu (prewencja, niedostępność usług, puste ``URZĄDZENIA``): bez żadnych ilości."""

    quantities: Quantities = field(default_factory=lambda: _NONE, init=False)


@dataclass(frozen=True)
class WithoutRule:
    """``URZĄDZENIA`` mają składnik, którego Reguły ilości nie znają: tylko V, T i dodatek za usterkę po godzinach."""

    quantities: Quantities


RuleResult = ServiceQuantities | FromDescription | WithoutRule


class _Kind(Enum):
    ROUTER = auto()
    TV = auto()
    EXTENDER = auto()
    FAULT = auto()
    """Usterka: po godzinach dostaje dodatek 45 zł."""
    PIECES = auto()
    """Składnik liczony w sztukach z ``CZYNNOŚCI`` zamiast krotności ``n*``."""
    OTHER = auto()


@dataclass(frozen=True)
class _Component:
    """Składnik ``URZĄDZENIA``: jego ilości na sztukę i rodzaj, od którego zależą ilości całego zlecenia.

    Ilości składnika zastępują ilości niezależne od ``URZĄDZENIA`` w tej samej kolumnie (V instalacji ręcznej).
    """

    quantities: Mapping[QuantityColumn, int]
    kind: _Kind = _Kind.OTHER
    with_extender: Mapping[QuantityColumn, int] = field(default_factory=dict)
    """Ilości na sztukę dodawane, gdy w zleceniu jest też wzmacniacz wifi."""
    without_router: tuple[str, Mapping[QuantityColumn, int]] | None = None
    """Fraza ``CZYNNOŚCI`` (małe litery, pojedyncze spacje) i ilości dodawane raz na zlecenie, bez względu na liczbę
    sztuk składnika, gdy zlecenie bez routera ma tę frazę w ``CZYNNOŚCI`` jako fragment tekstu; nie liczą się do S."""


_Q = QuantityColumn
_NOKIA_ROUTER = _Component({_Q.O: 1, _Q.Z: 1}, _Kind.ROUTER)
_GATEWAY = _Component({_Q.O: 1}, _Kind.ROUTER, with_extender={_Q.AO: 1})
_TV = _Component({}, _Kind.TV)
_FAULT = _Component({_Q.AI: 1}, _Kind.FAULT)
_MANUAL_INSTALLATION = _Component({_Q.AN: 1, _Q.V: 1}, _Kind.PIECES)

# Klucze po normalizacji jak ``URZĄDZENIA``. Urządzenia TV nie mają własnych ilości: przy routerze pierwsze idzie
# do P (TV), a pozostałe do Q (multiroom); bez routera wszystkie do Q.
_COMPONENTS: Final[Mapping[str, _Component]] = {
    "nokia": _Component({_Q.Z: 1}, without_router=("akt int", {_Q.O: 1})),
    "nokia zte": _NOKIA_ROUTER,
    "nokia getewayhomebox": _NOKIA_ROUTER,
    "technicolor": _Component({_Q.O: 1, _Q.Z: 1, _Q.AK: 1}, _Kind.ROUTER),
    "gateway": _GATEWAY,
    "zyxel": _GATEWAY,
    "fut": _TV,
    "globo": _TV,
    "stb2": _TV,
    "wifi6extra": _Component({_Q.AG: 1}, _Kind.EXTENDER),
    "usterka": _FAULT,
    "usterka hurt": _FAULT,
    "usterka wew": _FAULT,
    "gniazdo": _Component({_Q.AE: 1, _Q.AP: 1}),
    "zmiana instalacji w lokalu abonenta": _Component({_Q.AM: 1}),
    "instalacja ręczna": _MANUAL_INSTALLATION,
    "wizja": _MANUAL_INSTALLATION,
}
# Dodatek 45 zł za usterkę, w N jako ilość pozycji o koszcie 1 zł: dzień tygodnia (0 = poniedziałek) → godzina
# ``DATA``, od której się należy. W niedziele i święta firma nie pracuje.
_LATE_FAULT_FROM: Final[Mapping[int, time]] = {**dict.fromkeys(range(5), time(17)), 5: time.min}
_LATE_FAULT_SURCHARGE: Final = 45
_LONGEST_COMPONENT = max(len(name.split()) for name in _COMPONENTS)
_FROM_DESCRIPTION: Final = frozenset({"prewencja", "niedostępność usług"})

_SEPARATORS = re.compile(r"[\s,]+")
_MULTIPLIER = re.compile(r"\s*\*\s*")
_COUNTED = re.compile(r"([1-9][0-9]*)\*(.+)")
_PIECES = re.compile(r"([1-9][0-9]*)\s*szt", re.IGNORECASE)
_PRINTING_CONTRACT = "u"


def evaluate(order: OrderContent) -> RuleResult:
    """Ilości usług zlecenia według Reguł ilości taty."""

    words = _words(order.devices)
    if not words or " ".join(words) in _FROM_DESCRIPTION:
        return FromDescription()
    quantities = Counter({_Q.V: 1})
    if _first_word(order.contract) == _PRINTING_CONTRACT:
        quantities[_Q.T] = 1
    components, all_known = _components(words)
    if _is_late(order.started) and any(component.kind is _Kind.FAULT for component, _ in components):
        quantities[_Q.N] = _LATE_FAULT_SURCHARGE
    if not all_known:
        return WithoutRule(_nonzero(quantities))
    return ServiceQuantities(_nonzero({**quantities, **_device_quantities(components, order.activities)}))


def _cell_text(value: object) -> str:
    return "" if value is None else str(value)


def _words(devices: str) -> list[str]:
    text = devices.casefold().replace("xg", "")
    return [word for word in _SEPARATORS.split(_MULTIPLIER.sub("*", text)) if word]


def _first_word(contract: str) -> str:
    words = contract.casefold().split()
    return words[0] if words else ""


def _is_late(started: WeekTime) -> bool:
    late_from = _LATE_FAULT_FROM.get(started.weekday)
    return late_from is not None and started.at >= late_from


def _pieces(activities: str) -> int:
    """Liczba sztuk z ``CZYNNOŚCI`` (``6 szt``, ``7szt``); bez liczby 1."""

    counted = _PIECES.search(activities)
    return int(counted[1]) if counted else 1


def _components(words: list[str]) -> tuple[list[tuple[_Component, int]], bool]:
    """Znane składniki z krotnością, najdłuższe dopasowanie od lewej, i czy Reguły ilości znają każde słowo."""

    found: list[tuple[_Component, int]] = []
    all_known = True
    position = 0
    while position < len(words):
        counted = _COUNTED.fullmatch(words[position])
        count, first = (int(counted[1]), counted[2]) if counted else (1, words[position])
        for length in range(min(_LONGEST_COMPONENT, len(words) - position), 0, -1):
            component = _COMPONENTS.get(" ".join([first, *words[position + 1 : position + length]]))
            if component is not None:
                found.append((component, count))
                position += length
                break
        else:
            all_known = False
            position += 1
    return found, all_known


def _device_quantities(components: list[tuple[_Component, int]], activities: str) -> Counter[QuantityColumn]:
    pieces = _pieces(activities)
    quantities: Counter[QuantityColumn] = Counter()
    count_of = Counter[_Kind]()
    for component, count in components:
        count_of[component.kind] += count
        per_order = pieces if component.kind is _Kind.PIECES else count
        quantities.update({column: value * per_order for column, value in component.quantities.items()})
    if count_of[_Kind.EXTENDER]:
        for component, count in components:
            quantities.update({column: value * count for column, value in component.with_extender.items()})
    tv_devices = count_of[_Kind.TV]
    if tv_devices and count_of[_Kind.ROUTER]:
        quantities[_Q.P] += 1
        quantities[_Q.Q] += tv_devices - 1
    else:
        quantities[_Q.Q] += tv_devices
    quantities[_Q.S] = quantities[_Q.O] + quantities[_Q.P] + quantities[_Q.Q] + quantities[_Q.AG]
    if not count_of[_Kind.ROUTER]:
        phrases = " ".join(activities.casefold().split())
        once = dict(component.without_router for component, _ in components if component.without_router is not None)
        for phrase, added in once.items():
            if phrase in phrases:
                quantities.update(added)
    return quantities


def _nonzero(quantities: Mapping[QuantityColumn, int]) -> Quantities:
    return MappingProxyType({column: value for column, value in quantities.items() if value})
