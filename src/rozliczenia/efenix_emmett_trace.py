"""Ślad Wyceny Emmetta: stan wyceny zleceń okresu, do których Wycena w efenix sama załadowała Wycenę Emmetta, na komputerze
taty.

Strona efenix nie mówi, kto zaczął wycenę zlecenia ani kto wpisał w nim ilość, więc wycenę, którą narzędzie samo zaczęło
i której nie skończyło, ponowne uruchomienie odróżnia od każdej innej tylko tym śladem. Zlecenie ma w nim jeden z dwóch
stanów:

- „Emmett załadowany” (``loaded``): narzędzie kliknęło „Załaduj do zlecenia”, strona zlecenia przeładowała się, a narzędzie
  odczytało z niej Wycenę Emmetta; ślad trzyma jej ilości i ilości, które narzędzie zaczęło wpisywać w pozycjach pustych
  u Emmetta. Przed przyciskiem Emmetta i przed „Załaduj” narzędzie niczego nie zapisuje, więc przerwanie przed odczytem
  strony po „Załaduj” nie zostawia tego stanu.
- „gotowe” (``finished``): zlecenie, które było w stanie „Emmett załadowany”, skończyło się wynikiem: gotowe, ostrzeżenie
  Emmetta albo błąd.

Ilość ślad zapisuje z wyprzedzeniem (``entering``): zanim okno wpisze ją w efenix, plik śladu ma już jej pozycję i ilość,
a zapis, który się nie udał, każe jej nie wpisywać. Plik śladu ma więc każdą ilość, którą narzędzie mogło wpisać w efenix,
także gdy przerwanie przyszło po zapisie ilości w efenix, a przed odpowiedzią. Pozycję, której efenix na pewno nie zapisał
(okno zgłosiło wylogowanie), ślad wycofuje (``not_entered``).

Wycenę Emmetta do dokończenia (``emmett``) i ilości, które narzędzie zaczęło wpisywać (``entered``), daje tylko zlecenie w
stanie „Emmett załadowany”. Zlecenie gotowe, zlecenie spoza śladu i każde zlecenie śladu, którego nie da się przeczytać,
ponowne uruchomienie tylko porównuje.

Ślad jednego okresu to plik ``<okres>.json`` w ``config/slad-wyceny-emmetta/`` katalogu narzędzia, na dysku lokalnym, poza
OneDrive i poza Gitem, obok innych plików Centrum (ADR 0015). Zlecenie jest w nim pod HMAC-SHA256 ``Numer dokumentu`` z
losowym kluczem z pliku ``klucz`` w tym samym folderze, wspólnym dla okresów i zapisanym przy pierwszym zapisie śladu.
Plik śladu nie ma więc numerów zleceń ani skrótów, którymi bez klucza dałoby się sprawdzić zgadnięty numer, a adresów i
loginów nie ma wcale. Kto ma oba pliki, sprawdzi zgadnięty numer, tak jak przeczyta go z Pliku zbiorczego na tym samym
dysku. Ślad niczego nie wysyła.

Każdy zapis zastępuje plik atomowo (plik tymczasowy i zamiana), więc przerwanie w trakcie zostawia poprzedni ślad. Brak
pliku albo klucza i plik, którego nie da się przeczytać albo który ma inną budowę, to brak śladu; także plik wersji sprzed
zapisu z wyprzedzeniem, w którym „Emmett załadowany” nie ma ilości, które narzędzie zaczęło wpisywać. Zapis, który się nie
udał, zwraca ``False``, ślad zostaje w pamięci, a narzędzie usuwa plik śladu z dysku, bo poprzedni ślad mógłby mieć
„Emmett załadowany” przy zleceniu, które jest już gotowe. Następny udany zapis zapisuje cały ślad z pamięci. Gdy pliku nie
da się ani zastąpić, ani usunąć, zostaje na dysku poprzedni ślad; ma on każdą ilość, którą narzędzie wpisało w efenix.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from types import MappingProxyType
from typing import Final, TypedDict

from . import TOOL_ROOT

__all__ = ["EmmettTrace", "default_directory"]

_FINISHED: Final = "gotowe"
_SECRET_NAME: Final = "klucz"
_SECRET_BYTES: Final = 32


def default_directory() -> Path:
    """Folder śladów Wyceny Emmetta w ``config/`` katalogu narzędzia na dysku lokalnym."""

    return TOOL_ROOT / "config" / "slad-wyceny-emmetta"


class _Loaded(TypedDict):
    """Zlecenie w stanie „Emmett załadowany”: ilości Wyceny Emmetta i ilości, które narzędzie zaczęło wpisywać (kod
    ``NNN`` → ilość)."""

    emmett: dict[str, int]
    entering: dict[str, int]


class EmmettTrace:
    """Ślad Wyceny Emmetta jednego okresu w pliku ``path``, przeczytany raz przy utworzeniu."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._secret_path = path.with_name(_SECRET_NAME)
        secret = _read_secret(self._secret_path)
        self._secret_saved = secret is not None
        self._secret = secrets.token_bytes(_SECRET_BYTES) if secret is None else secret
        self._orders = {} if secret is None else _read(path)

    @property
    def path(self) -> Path:
        """Plik śladu okresu."""

        return self._path

    def emmett(self, number: str) -> Mapping[str, int] | None:
        """Wycena Emmetta zlecenia o ``Numer dokumentu`` równym ``number`` w stanie „Emmett załadowany” (kod ``NNN`` →
        ilość, pusta to 0); ``None``, gdy zlecenia nie ma w śladzie albo jest już gotowe."""

        loaded = self._loaded(number)
        return None if loaded is None else MappingProxyType(dict(loaded["emmett"]))

    def entered(self, number: str) -> Mapping[str, int]:
        """Ilości, które narzędzie zaczęło wpisywać w zleceniu ``number`` w stanie „Emmett załadowany” (kod ``NNN`` →
        ilość); efenix mógł każdą z nich zapisać albo nie. Puste, gdy zlecenia nie ma w śladzie albo jest już gotowe."""

        loaded = self._loaded(number)
        return MappingProxyType({} if loaded is None else dict(loaded["entering"]))

    def loaded(self, number: str, emmett: Mapping[str, int]) -> None:
        """Zapisuje stan „Emmett załadowany” zlecenia ``number`` z ilościami Wyceny Emmetta, które narzędzie odczytało ze
        strony przeładowanej po „Załaduj do zlecenia”."""

        self._orders[self._key(number)] = {"emmett": dict(emmett), "entering": {}}
        self._save()

    def entering(self, number: str, position: str, quantity: int) -> bool:
        """Zapis z wyprzedzeniem: zlecenie ``number`` w stanie „Emmett załadowany” dostaje ilość ``quantity`` pozycji
        ``position``, którą okno zaraz wpisze w efenix. ``False``, gdy zapis pliku śladu się nie udał albo zlecenia nie ma
        w tym stanie: wtedy narzędzie tej ilości nie wpisuje."""

        loaded = self._loaded(number)
        if loaded is None:
            return False
        loaded["entering"][position] = quantity
        return self._save()

    def not_entered(self, number: str, position: str) -> None:
        """Wycofuje ze zlecenia ``number`` w stanie „Emmett załadowany” pozycję ``position``, której efenix na pewno nie
        zapisał."""

        loaded = self._loaded(number)
        if loaded is not None:
            loaded["entering"].pop(position, None)
            self._save()

    def finished(self, number: str) -> None:
        """Zlecenie ``number`` w stanie „Emmett załadowany” przechodzi w stan „gotowe”; zlecenia spoza śladu nie zapisuje."""

        key = self._key(number)
        if isinstance(self._orders.get(key), dict):
            self._orders[key] = _FINISHED
            self._save()

    def _loaded(self, number: str) -> _Loaded | None:
        entry = self._orders.get(self._key(number))
        return entry if isinstance(entry, dict) else None

    def _key(self, number: str) -> str:
        return hmac.new(self._secret, number.encode("utf-8"), hashlib.sha256).hexdigest()

    def _save(self) -> bool:
        """Cały ślad z pamięci w pliku śladu; ``False`` (i plik śladu usunięty, gdy się da), gdy zapis się nie udał."""

        if not self._secret_saved:
            self._secret_saved = _replace(self._secret_path, self._secret.hex())
        if self._secret_saved and _replace(self._path, json.dumps({"orders": self._orders}, sort_keys=True)):
            return True
        with suppress(OSError):
            self._path.unlink(missing_ok=True)
        return False


def _replace(path: Path, text: str) -> bool:
    """Zastępuje plik ``path`` tekstem ``text`` atomowo; ``False``, gdy się nie udało (plik tymczasowy nie zostaje)."""

    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        return False
    return True


def _read_secret(path: Path) -> bytes | None:
    """Klucz HMAC z pliku ``path``; ``None``, gdy pliku nie ma, nie da się go przeczytać albo nie ma w nim klucza."""

    try:
        secret = bytes.fromhex(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return secret if len(secret) == _SECRET_BYTES else None


def _read(path: Path) -> dict[str, _Loaded | str]:
    """Ślad z pliku ``path``; pusty, gdy pliku nie ma, nie da się go przeczytać albo ma inną budowę: każde zlecenie to
    ``"gotowe"`` albo ``{"emmett": {kod: ilość}, "entering": {kod: ilość}}`` z ilościami jako liczbami całkowitymi (klucze
    obiektu JSON są zawsze tekstem)."""

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    orders = content.get("orders") if isinstance(content, dict) else None
    if not isinstance(orders, dict) or not all(_is_entry(entry) for entry in orders.values()):
        return {}
    return orders


def _is_entry(entry: object) -> bool:
    if entry == _FINISHED:
        return True
    if not isinstance(entry, dict) or entry.keys() != {"emmett", "entering"}:
        return False
    return all(
        isinstance(quantities, dict) and all(type(quantity) is int for quantity in quantities.values())
        for quantities in entry.values()
    )
