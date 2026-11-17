"""Reguła tego samego adresu Historii adresu: które wiersze Bazy zleceń mają ten sam adres co zlecenie.

Jedynym wejściem jest indeks adresów (``AddressIndex``): powstaje z adresów wierszy Bazy, a pytany adresem zlecenia
oddaje wiersze z tym samym adresem, w kolejności, w jakiej przyszły. Indeks szuka po kluczu adresu, więc nie porównuje
zlecenia z każdym wierszem.

Klucz adresu to nazwa ulicy, numer budynku i numer mieszkania albo jego brak. Z tekstu adresu znika najpierw miasto
przed pierwszym przecinkiem (``Poznań,Lipowa 018/``), potem kropki, a wielkość liter i wielokrotne odstępy się nie
liczą. Na początku znika przedrostek ``UL``, ``OS``, ``AL`` albo ``PL``. Na końcu stoi numer budynku: cyfry z
opcjonalną literą, bez zer wiodących, a za nim opcjonalnie ``/`` i numer mieszkania w tej samej postaci; ukośnik bez
mieszkania (``018/``) to adres bez mieszkania. Nazwa ulicy to słowa przed numerem budynku. Ten sam adres ma ten sam
klucz: adres bez mieszkania jest tym samym tylko dla adresu bez mieszkania. Tekst, w którym na końcu nie stoi numer
budynku (pusty, sama ulica, coś za numerem mieszkania), nie ma klucza i nie daje trafienia.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final, Generic, TypeVar

__all__ = ["AddressIndex"]

_Row = TypeVar("_Row")

_PREFIXES: Final = frozenset({"ul", "os", "al", "pl"})
_NUMBER: Final = r"0*(\d+[^\W\d_]?)"
_ADDRESS: Final = re.compile(rf"(?P<street>.*?)\s*\b{_NUMBER}(?:\s*/\s*(?:{_NUMBER})?)?", re.S)

_Key = tuple[tuple[str, ...], str, str | None]
"""Klucz adresu: słowa nazwy ulicy, numer budynku i numer mieszkania (``None``: bez mieszkania)."""


class AddressIndex(Generic[_Row]):
    """Wiersze Bazy zleceń po kluczu adresu; ``matching`` oddaje wiersze z tym samym adresem co zlecenie."""

    def __init__(self, rows: Iterable[tuple[object, _Row]]) -> None:
        """Indeks z par (adres z kolumny A Bazy, wiersz); wiersz bez klucza adresu nie trafia do indeksu."""

        self._rows: dict[_Key, list[_Row]] = {}
        for address, row in rows:
            key = _key(address)
            if key is not None:
                self._rows.setdefault(key, []).append(row)

    def matching(self, address: object) -> tuple[_Row, ...]:
        """Wiersze z tym samym adresem co ``address`` (``ADRES`` zlecenia), w kolejności z indeksu."""

        key = _key(address)
        return () if key is None else tuple(self._rows.get(key, ()))


def _key(address: object) -> _Key | None:
    if not isinstance(address, str):
        return None
    text = address.partition(",")[2] if "," in address else address
    words = text.replace(".", " ").casefold().split()
    if words and words[0] in _PREFIXES:
        words = words[1:]
    found = _ADDRESS.fullmatch(" ".join(words))
    if found is None or not found.group("street"):
        return None
    street, building, apartment = found.group("street", 2, 3)
    return tuple(street.split()), building, apartment
