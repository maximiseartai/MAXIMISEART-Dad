"""Reguła adresu Wyceny w efenix: czy ``Dane adresowe`` zlecenia w efenix to ten sam adres co ``ADRES`` w Pliku zbiorczym.

Jedyną operacją jest ``same_address()``. Obie strony przechodzą przez jeden rozbiór (``_parse``): bez wielkości liter,
zbędnych spacji i interpunkcji, rodzaj (``ul``, ``os``, ``al``, ``pl``), zbiór słów nazwy ulicy w dowolnej kolejności,
numer budynku i lokal. Lokal to część po ``/`` przy numerze (``12A/24``, zapis Pliku zbiorczego) albo słowo po
``Lokal`` (``12A Lokal 24``, zapis efenix). Wszystko przed rodzajem (w efenix miejscowość z dzielnicą) się pomija.
Adres, którego nie da się tak rozebrać (bez rodzaju, bez numeru, z czymś po lokalu), nie jest równy żadnemu.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

__all__ = ["same_address"]

_KINDS: Final = frozenset({"ul", "os", "al", "pl"})
_FLAT_WORD: Final = "lokal"
_SLASH: Final = re.compile(r"\s*/\s*")
# Interpunkcja i każdy inny znak, który nie jest literą, cyfrą, ``/`` ani odstępem, dzieli słowa.
_SEPARATORS: Final = re.compile(r"[^\w/\s]|_")


@dataclass(frozen=True)
class _Address:
    kind: str
    street: frozenset[str]
    number: str
    flat: str | None


def same_address(collective: str, efenix: str) -> bool:
    """``ADRES`` z Pliku zbiorczego i ``Dane adresowe`` z efenix (bez linii województwa) to ten sam adres."""

    left, right = _parse(collective), _parse(efenix)
    return left is not None and left == right


def _parse(text: str) -> _Address | None:
    words = _SEPARATORS.sub(" ", _SLASH.sub("/", text.casefold())).split()
    kinds = [index for index, word in enumerate(words) if word in _KINDS]
    if not kinds:
        return None
    words = words[kinds[0] :]
    kind, rest = words[0], words[1:]
    flat: str | None = None
    if _FLAT_WORD in rest:
        at = rest.index(_FLAT_WORD)
        if len(rest) != at + 2:
            return None
        rest, flat = rest[:at], rest[at + 1]
    if len(rest) < 2:
        return None
    *street, number = rest
    if "/" in number:
        if flat is not None:
            return None
        number, _, flat = number.partition("/")
        if not flat or "/" in flat:
            return None
    if not number[:1].isdigit() or "/" in "".join(street):
        return None
    return _Address(kind, frozenset(street), number, flat)
