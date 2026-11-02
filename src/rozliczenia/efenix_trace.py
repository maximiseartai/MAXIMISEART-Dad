"""Ślad Wyceny Emmetta: zlecenia okresu, do których Wycena w efenix sama załadowała Wycenę Emmetta, na komputerze taty.

Strona efenix nie mówi, kto zaczął wycenę zlecenia, więc ponowne uruchomienie odróżnia wycenę, którą narzędzie samo
przerwało, od wyceny zaczętej przez tatę tylko tym śladem. Przed kliknięciem „Załaduj do zlecenia” narzędzie zapisuje, że
ładuje Wycenę Emmetta (``loading``), a po odczycie strony jej ilości (``loaded``). Ślad jednego okresu to plik
``<okres>.json`` w ``config/slad-wyceny-emmetta/`` katalogu narzędzia, na dysku lokalnym, poza OneDrive i poza Gitem,
obok innych plików Centrum (ADR 0015). Zlecenie jest w nim pod skrótem SHA-256 ``Numer dokumentu``, więc plik nie ma
numerów zleceń, adresów ani loginów i niczego nie wysyła.

Każdy zapis zastępuje plik atomowo (plik tymczasowy i zamiana), więc przerwanie w trakcie zostawia poprzedni ślad. Brak
pliku i plik, którego nie da się przeczytać albo który ma inną budowę, to brak śladu: ponowne uruchomienie tylko porównuje
wycenę, która już jest. Zapis, który się nie udał, nie zatrzymuje Wyceny w efenix: ślad zostaje w pamięci do końca
przebiegu, a na dysku poprzedni. Bez zapisu „ładuje” ponowne uruchomienie tylko porówna wycenę tego zlecenia, a bez
zapisu ilości weźmie za Wycenę Emmetta ilości strony, które poza nią mają tylko ilości pliku.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType

from . import TOOL_ROOT

__all__ = ["EmmettTrace", "Loaded", "default_directory"]


def default_directory() -> Path:
    """Folder śladów Wyceny Emmetta w ``config/`` katalogu narzędzia na dysku lokalnym."""

    return TOOL_ROOT / "config" / "slad-wyceny-emmetta"


@dataclass(frozen=True)
class Loaded:
    """Narzędzie załadowało do zlecenia Wycenę Emmetta: ``emmett`` to jej ilości (kod ``NNN`` → ilość, pusta to 0), a
    ``None``, gdy przebieg przerwał się przed ich odczytem, więc ilości na stronie to wciąż Wycena Emmetta."""

    emmett: Mapping[str, int] | None


class EmmettTrace:
    """Ślad Wyceny Emmetta jednego okresu w pliku ``path``, przeczytany raz przy utworzeniu."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._orders = _read(path)

    def of(self, number: str) -> Loaded | None:
        """Ślad zlecenia o ``Numer dokumentu`` równym ``number``; ``None``, gdy narzędzie nie ładowało do niego Emmetta."""

        if (key := _key(number)) not in self._orders:
            return None
        emmett = self._orders[key]
        return Loaded(None if emmett is None else MappingProxyType(dict(emmett)))

    def loading(self, number: str) -> None:
        """Zapisuje, zanim narzędzie kliknie „Załaduj do zlecenia”, że ładuje Wycenę Emmetta do zlecenia ``number``."""

        self._orders[_key(number)] = None
        self._save()

    def loaded(self, number: str, emmett: Mapping[str, int]) -> None:
        """Zapisuje ilości Wyceny Emmetta, które narzędzie odczytało po jej załadowaniu do zlecenia ``number``."""

        self._orders[_key(number)] = dict(emmett)
        self._save()

    def _save(self) -> None:
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"orders": self._orders}, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self._path)
        except OSError:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _key(number: str) -> str:
    return hashlib.sha256(number.encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, dict[str, int] | None]:
    """Ślad z pliku ``path``; pusty, gdy pliku nie ma, nie da się go przeczytać albo ma inną budowę (klucze obiektu JSON
    są zawsze tekstem, więc budowa to ilości jako liczby całkowite albo ``null``)."""

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    orders = content.get("orders") if isinstance(content, dict) else None
    if not isinstance(orders, dict) or not all(_is_entry(emmett) for emmett in orders.values()):
        return {}
    return orders


def _is_entry(emmett: object) -> bool:
    return emmett is None or (isinstance(emmett, dict) and all(type(quantity) is int for quantity in emmett.values()))
