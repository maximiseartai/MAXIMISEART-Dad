"""Reguła adresu Wyceny w efenix: czy ``Dane adresowe`` zlecenia w efenix to ten sam adres co ``ADRES`` w Pliku zbiorczym.

Operacją jest ``address_differences()``: części adresu, którymi oba adresy się różnią (``AddressPart``), a
``same_address()`` to adresy bez różnicy. Obie strony przechodzą przez jeden rozbiór (``_readings``): bez wielkości liter,
zbędnych spacji i interpunkcji, rodzaj (``ul``, ``os``, ``al``, ``pl``), zbiór słów nazwy ulicy w dowolnej kolejności,
numer budynku i lokal. Numer budynku to jedna część (``12A``) albo dwie po ``/`` (``13/14``), każda od cyfry.
Lokal to słowo po ``Lokal`` zaraz za numerem (``12A Lokal 24``, ``13/14 Lokal 16``, ``8B Lokal 27/3``, zapis efenix)
albo część po ``/`` przy numerze bez ``Lokal`` (zapis Pliku zbiorczego): jeden ``/`` (``12A/24``) dzieli numer i lokal,
a nie dwie części numeru. Dwa ``/`` bez ``Lokal`` mają dwa odczyty, bo tata pisze tak oba adresy: budynek ``13/14`` z
lokalem ``16`` (``13/14/16``, #829) i budynek ``8B`` z lokalem ``27/3`` (``8B/27/3``, Uwaga taty z 7.11.2026). Który
to podział, wie efenix, więc adres jest równy, gdy pasuje którykolwiek odczyt. ``Lokal`` gdzie indziej to słowo nazwy ulicy.
Wszystko przed rodzajem (w efenix miejscowość z dzielnicą) się pomija.
Adres, którego nie da się tak rozebrać (bez rodzaju, bez nazwy ulicy, bez numeru, z numerem budynku z więcej niż
dwiema częściami albo z pustą częścią numeru), nie jest równy żadnemu, nawet samemu sobie, a jego różnica to strona
bez rozbioru, nie część adresu. Części to ulica (rodzaj i słowa nazwy), numer domu i lokal; miejscowości reguła nie
porównuje, więc nie jest częścią różnicy. Nazwy części, bez wartości, idą do Logów Uruchomienia (``efenix_trace``). Słowa po ``Lokal N`` czyta
jak resztę nazwy ulicy z numerem na końcu; lista efenix nic po lokalu nie pisze.
"""

from __future__ import annotations

from dataclasses import dataclass
import enum
import re
from typing import Final

__all__ = ["AddressPart", "address_differences", "readable", "same_address"]


class AddressPart(enum.Enum):
    """Część adresu, którą różnią się ``ADRES`` i ``Dane adresowe``; wartość to jej nazwa w Logach Uruchomienia."""

    STREET = "ulica"
    """Rodzaj (``ul``, ``os``, ``al``, ``pl``) albo zbiór słów nazwy ulicy."""
    NUMBER = "numer domu"
    FLAT = "lokal"
    FILE_UNREAD = "ADRES bez rozbioru"
    """``ADRES`` z Pliku zbiorczego, którego reguła nie rozbiera, więc nie jest równy żadnemu adresowi."""
    EFENIX_UNREAD = "Dane adresowe bez rozbioru"
    """``Dane adresowe`` z efenix, których reguła nie rozbiera."""

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

    return not address_differences(collective, efenix)


def readable(address: str) -> bool:
    """Reguła rozbiera ``address`` na rodzaj, nazwę ulicy, numer domu i lokal; narzędzie zgodności efenix sprawdza tak
    ``Dane adresowe`` z prawdziwego efenix."""

    return bool(_readings(address))


def address_differences(collective: str, efenix: str) -> tuple[AddressPart, ...]:
    """Części, którymi ``ADRES`` z Pliku zbiorczego i ``Dane adresowe`` z efenix się różnią, w kolejności ``AddressPart``;
    pusta krotka to ten sam adres. Strona, której reguła nie rozbiera, to jej ``…_UNREAD`` zamiast części. Gdy strona ma
    dwa odczyty (``X/Y/Z`` bez ``Lokal``), różnica to ta z pary odczytów, która różni się najmniej, przy remisie
    pierwsza."""

    lefts, rights = _readings(collective), _readings(efenix)
    if not lefts or not rights:
        return tuple(part for part, read in ((AddressPart.FILE_UNREAD, lefts), (AddressPart.EFENIX_UNREAD, rights)) if not read)
    return min((_differences(left, right) for left in lefts for right in rights), key=len)


def _differences(left: _Address, right: _Address) -> tuple[AddressPart, ...]:
    differs = {
        AddressPart.STREET: (left.kind, left.street) != (right.kind, right.street),
        AddressPart.NUMBER: left.number != right.number,
        AddressPart.FLAT: left.flat != right.flat,
    }
    return tuple(part for part, different in differs.items() if different)


def _readings(text: str) -> tuple[_Address, ...]:
    """Każdy odczyt adresu ``text``, po kolei; pusty, gdy reguła go nie rozbiera."""

    words = _SEPARATORS.sub(" ", _SLASH.sub("/", text.casefold())).split()
    kinds = [index for index, word in enumerate(words) if word in _KINDS]
    if not kinds:
        return ()
    words = words[kinds[0] :]
    kind, rest = words[0], words[1:]
    flat: str | None = None
    # ``Lokal`` zaraz za numerem to lokal, a w każdym innym miejscu słowo nazwy ulicy (``ul.Lokal 1``).
    if len(rest) >= 3 and rest[-2] == _FLAT_WORD and rest[-3][:1].isdigit():
        rest, flat = rest[:-2], rest[-1]
    if len(rest) < 2:
        return ()
    *street, number = rest
    if "/" in "".join(street):
        return ()
    parts = number.split("/")
    if flat is not None or len(parts) == 1:
        splits = [(parts, flat)]
    else:
        splits = [(parts[:-1], parts[-1])]
        if len(parts) == 3:
            splits.append((parts[:1], "/".join(parts[1:])))
    return tuple(
        _Address(kind, frozenset(street), "/".join(building), flat)
        for building, flat in splits
        if len(building) <= 2
        and all(part[:1].isdigit() for part in building)
        and (flat is None or all(flat.split("/")))
    )
