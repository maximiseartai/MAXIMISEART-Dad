"""Reguła adresu Wyceny w efenix: czy ``Dane adresowe`` zlecenia w efenix to ten sam adres co ``ADRES`` w Pliku zbiorczym.

Jedyną operacją jest ``same_address()``. Obie strony przechodzą przez jeden rozbiór (``_parse``): bez wielkości liter,
zbędnych spacji i interpunkcji, rodzaj (``ul``, ``os``, ``al``, ``pl``), zbiór słów nazwy ulicy w dowolnej kolejności,
numer budynku i lokal. Numer budynku to jedna część (``12A``) albo dwie po ``/`` (``13/14``), każda od cyfry.
Lokal to słowo po ``Lokal`` zaraz za numerem (``12A Lokal 24``, ``13/14 Lokal 16``, zapis efenix) albo część po
ostatnim ``/`` przy numerze bez ``Lokal`` (``12A/24``, ``13/14/16``, zapis Pliku zbiorczego); jeden ``/`` bez
``Lokal`` dzieli więc numer i lokal, a nie dwie części numeru. ``Lokal`` gdzie indziej to słowo nazwy ulicy.
Wszystko przed rodzajem (w efenix miejscowość z dzielnicą) się pomija.
Adres, którego nie da się tak rozebrać (bez rodzaju, bez nazwy ulicy, bez numeru, z numerem budynku z więcej niż
dwiema częściami albo z pustą częścią numeru), nie jest równy żadnemu, nawet samemu sobie. Słowa po ``Lokal N`` czyta
jak resztę nazwy ulicy z numerem na końcu; lista efenix nic po lokalu nie pisze.
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
    # ``Lokal`` zaraz za numerem to lokal, a w każdym innym miejscu słowo nazwy ulicy (``ul.Lokal 1``).
    if len(rest) >= 3 and rest[-2] == _FLAT_WORD and rest[-3][:1].isdigit():
        rest, flat = rest[:-2], rest[-1]
    if len(rest) < 2:
        return None
    *street, number = rest
    building = number.split("/")
    if flat is None and len(building) > 1:
        *building, flat = building
    if flat == "" or len(building) > 2 or not all(part[:1].isdigit() for part in building) or "/" in "".join(street):
        return None
    return _Address(kind, frozenset(street), "/".join(building), flat)
