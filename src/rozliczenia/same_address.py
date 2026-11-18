"""Reguła tego samego adresu Historii adresu: które wiersze Bazy zleceń mają ten sam adres co zlecenie.

Jedynym wejściem jest indeks adresów (``AddressIndex``): powstaje z adresów i miast wierszy Bazy, a pytany adresem i
miastem zlecenia oddaje wiersze z tym samym adresem, w kolejności, w jakiej przyszły.

Adres to nazwa ulicy, numer budynku, numer mieszkania albo jego brak i miasto albo jego brak. Z tekstu adresu znika
najpierw miasto przed pierwszym przecinkiem (``Poznań,Lipowa 018/``), potem kropki, a wielkość liter i wielokrotne
odstępy się nie liczą. Na początku znika przedrostek ``UL``, ``OS``, ``AL`` albo ``PL``. Na końcu stoi numer budynku:
cyfry z opcjonalną literą, bez zer wiodących, a za nim opcjonalnie ``/`` i numer mieszkania w tej samej postaci;
ukośnik bez mieszkania (``018/``) to adres bez mieszkania. Nazwa ulicy to słowa przed numerem budynku. Tekst, w którym
na końcu nie stoi numer budynku (pusty, sama ulica, coś za numerem mieszkania), nie jest adresem i nie daje trafienia.
Miasto to wartość ``MIASTO`` wiersza, a bez niej miasto przed przecinkiem, obie bez wielkości liter, kodu pocztowego i
dzielnicy po myślniku między słowami (``Poznań-Jeżyce`` to Poznań, decyzja Maksa z 18.11.2026).

Ten sam adres ma ten sam numer budynku i mieszkania (adres bez mieszkania jest tym samym tylko dla adresu bez
mieszkania), nazwę ulicy, której krótsza jest końcem dłuższej od granicy słowa (``KOWALSKIEGO`` i ``JANA
KOWALSKIEGO``, ale nie ``SKIEGO``), i to samo miasto, gdy mają je oba. Indeks trzyma więc wiersze pod ostatnim słowem
nazwy ulicy, numerem budynku i mieszkania, równymi w każdym tym samym adresie, a resztę reguły sprawdza tylko na
wierszach spod klucza zlecenia, nie na każdym wierszu Bazy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Generic, TypeVar

from .text import normalize_text

__all__ = ["AddressIndex"]

_Row = TypeVar("_Row")

_PREFIXES: Final = frozenset({"ul", "os", "al", "pl"})
_NUMBER: Final = r"0*(\d+[^\W\d_]?)"
_ADDRESS: Final = re.compile(rf"(?P<street>.*?)\s*\b{_NUMBER}(?:\s*/\s*(?:{_NUMBER})?)?", re.S)

_DASHES: Final = frozenset("-–—")
_CITY_TOKENS: Final = re.compile(r"[^\W\d_]+|\d+|[-–—]")
"""Słowa, liczby i myślniki zapisu miasta; reszta (odstępy, nawiasy, kropki) ich nie oddziela."""

_Key = tuple[str, str, str | None]
"""Klucz indeksu: ostatnie słowo nazwy ulicy, numer budynku i numer mieszkania (``None``: bez mieszkania)."""


@dataclass(frozen=True)
class _Address:
    """Adres: słowa nazwy ulicy (co najmniej jedno), numer budynku, numer mieszkania i miasto (``None``: bez)."""

    street: tuple[str, ...]
    building: str
    apartment: str | None
    city: str | None

    @property
    def key(self) -> _Key:
        return self.street[-1], self.building, self.apartment

    def same_street_and_city(self, other: _Address) -> bool:
        shorter, longer = sorted((self.street, other.street), key=len)
        cities = self.city is None or other.city is None or self.city == other.city
        return cities and longer[-len(shorter) :] == shorter


class AddressIndex(Generic[_Row]):
    """Wiersze Bazy zleceń pod kluczem adresu; ``matching`` oddaje wiersze z tym samym adresem co zlecenie."""

    def __init__(self, rows: Iterable[tuple[object, object, _Row]]) -> None:
        """Indeks z trójek (adres z kolumny A Bazy, ``MIASTO`` wiersza albo ``None``, wiersz); wiersz, którego adres nie
        jest adresem, nie trafia do indeksu."""

        self._rows: dict[_Key, list[tuple[_Address, _Row]]] = {}
        for address, city, row in rows:
            found = _address(address, city)
            if found is not None:
                self._rows.setdefault(found.key, []).append((found, row))

    def matching(self, address: object, city: object) -> tuple[_Row, ...]:
        """Wiersze z tym samym adresem co zlecenie z ``ADRES`` ``address`` i ``MIASTO`` ``city``, w kolejności z
        indeksu."""

        order = _address(address, city)
        if order is None:
            return ()
        return tuple(row for found, row in self._rows.get(order.key, ()) if order.same_street_and_city(found))


def _address(address: object, city: object) -> _Address | None:
    if not isinstance(address, str):
        return None
    prefix, comma, text = address.partition(",")
    if not comma:
        prefix, text = "", address
    words = text.replace(".", " ").casefold().split()
    if words and words[0] in _PREFIXES:
        words = words[1:]
    found = _ADDRESS.fullmatch(" ".join(words))
    if found is None or not found.group("street"):
        return None
    street, building, apartment = found.group("street", 2, 3)
    return _Address(tuple(street.split()), building, apartment, _city(normalize_text(city)) or _city(normalize_text(prefix)))


def _city(text: str) -> str | None:
    """Nazwa miasta (słowa przed myślnikiem dzielnicy, bez cyfr), cały zapis przy myślniku nierozpoznanym albo ``None``.

    O roli myślnika (także półpauzy i pauzy) decydują najbliższe znaki obok niego w samym zapisie, bez odstępów:
    cyfry po obu stronach to kod pocztowy (``11-111``, ``11 - 111``), który znika z cyframi, a litery po obu stronach
    to dzielnica (``Poznań-Jeżyce``, ``Poznań - Jeżyce``), przed którą kończy się nazwa. Zapis z każdym innym
    myślnikiem (``-Dzielnica``, ``PL-11-111``, ``Miastko 11-111 - Dzielnica``) nie ma pewnej nazwy, więc miastem jest
    cały zapis: zawiera myślnik, którego nazwa nigdy nie ma, więc równa się tylko temu samemu zapisowi. ``None``
    (brak miasta) zostaje dla zapisu bez słowa i bez takiego myślnika (sam kod pocztowy)."""

    words: list[str] = []
    for found in _CITY_TOKENS.finditer(text):
        token = found.group()
        if token not in _DASHES:
            if not token.isdigit():
                words.append(token)
            continue
        left, right = text[: found.start()].rstrip()[-1:], text[found.end() :].lstrip()[:1]
        if left.isdigit() and right.isdigit():
            continue
        if left.isalpha() and right.isalpha():
            break
        return text
    return " ".join(words) or None
