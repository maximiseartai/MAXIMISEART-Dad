"""Reguła danych (ADR 0025): co z treści plików taty może wyjść z jego komputera do Skrzynki Zgłoszeń.

Nigdy nie wychodzą wartości kolumn ``ADRES`` i ``NUMER UMOWY/ZLECENIA ORANGE`` (w Rejestrze zleceń i INTERMAX także
``adres`` i ``NUMER UMOWY``), bo wskazują klienta. Każda inna kolumna może wyjść, a wolny tekst idzie w całości z
zamaskowanymi numerami telefonów (``[telefon]``) i wzmiankami ulic („ul.”, „os.”, „al.”, „pl.” z nazwą i numerem,
``[ulica]``).

Zakazane wartości zna ten moduł z odczytu: każdy czytnik Wierszy danych (``workbook_files`` dla Pliku zbiorczego i
Rejestru zleceń, ``intermax_file`` dla INTERMAX) oddaje mu przy odczycie komórki zakazanych kolumn (``remember``).
Pamięć jest jedna na proces, jak pamięć podręczna odczytu Rejestru, i tylko rośnie: strażnik Centrum chroni więc
każdą wysyłkę przed wartością z każdego pliku, który ta praca Centrum przeczytała, także Uwagę taty, która nie ma
swojego Uruchomienia, i Zgłoszenie z Diagnozy, która czyta Rejestr z pamięci podręcznej. Pamięć nie trafia na dysk.

Strażnik (``guard``) przed zapisem pliku Logów i przed każdą wysyłką maskuje w tekście każdą znaną wartość (bez
wielkości liter, z dowolnymi odstępami między słowami, jako całe słowa) jako ``[adres]`` albo ``[numer Orange]`` i
oddaje uwagę techniczną z nazwą kolumny i miejscem w tekście, bez wartości. Wartość krótsza niż ``MIN_VALUE``
znaków jest pomijana: nie wskazuje klienta, a pasowałaby do zwykłych słów i liczb. Maskowanie wolnego tekstu
(``free_text``) uwagi nie daje, bo telefon i ulica w opisie technika to zwykła treść, nie wyciek kolumny.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from functools import lru_cache
import re
import threading
from typing import Final

from .worker_config import normalize_text

MIN_VALUE: Final = 5
"""Najkrótsza wartość zakazanej kolumny (po zwinięciu odstępów), której strażnik szuka w tekście."""


class ForbiddenColumn(Enum):
    """Kolumna, której wartość nigdy nie wychodzi z komputera taty; ``value`` to jej nazwa w uwadze technicznej."""

    ADDRESS = "ADRES"
    ORANGE = "NUMER UMOWY/ZLECENIA ORANGE"

    @property
    def mask(self) -> str:
        return _MASKS[self]


_MASKS: Final = {ForbiddenColumn.ADDRESS: "[adres]", ForbiddenColumn.ORANGE: "[numer Orange]"}
_HEADERS: Final = {
    normalize_text("ADRES"): ForbiddenColumn.ADDRESS,
    normalize_text("NUMER UMOWY/ZLECENIA ORANGE"): ForbiddenColumn.ORANGE,
    normalize_text("NUMER UMOWY"): ForbiddenColumn.ORANGE,
}
"""Nagłówek kolumny po ``normalize_text`` (Plik zbiorczy, Rejestr zleceń, INTERMAX i starsza kopia Rejestru)."""

_WORD: Final = re.compile(r"\w+")
_PHONE: Final = re.compile(
    r"(?<![\w+])(?:(?:\+|00)48[ -]?)?(?:\d{3}[ -]?\d{3}[ -]?\d{3}|\d{2}[ -]\d{3}[ -]\d{2}[ -]\d{2})(?!\w)"
)
"""Polski numer telefonu: komórkowy 3-3-3 (ze spacjami, myślnikami albo bez) i stacjonarny 2-3-2-2, z +48 albo bez."""
_STREET: Final = re.compile(
    r"(?<!\w)(?:ul|os|al|pl)\.[ \t]*(?:\w[\w-]*\.?[ \t]+){1,4}?\d+[^\W\d_]?(?:[ \t]*(?:/|m\.?)[ \t]*\d+[^\W\d_]?)?(?!\w)",
    re.IGNORECASE,
)
"""„ul.”, „os.”, „al.” albo „pl.” z nazwą do czterech słów i numerem domu (z lokalem po ``/`` albo ``m``)."""


@dataclass(frozen=True)
class Guarded:
    """Tekst po strażniku i uwagi techniczne o każdej zamaskowanej wartości (kolumna i miejsce, bez wartości)."""

    text: str
    notes: tuple[str, ...]


class _Known:
    """Zakazane wartości przeczytane w tym procesie: pierwsze słowo wartości → (wartość, kolumna)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_first_word: dict[str, set[tuple[str, ForbiddenColumn]]] = {}

    def add(self, column: ForbiddenColumn, value: object) -> None:
        text = _value_text(value)
        if text is None:
            return
        first = _WORD.search(text)
        if first is None:
            return
        with self._lock:
            self._by_first_word.setdefault(first.group(0).casefold(), set()).add((text, column))

    def candidates(self, word: str) -> tuple[tuple[str, ForbiddenColumn], ...]:
        with self._lock:
            found = self._by_first_word.get(word.casefold())
            return () if found is None else tuple(found)


_KNOWN: Final = _Known()


def forbidden_columns(header: Mapping[str, int]) -> tuple[tuple[ForbiddenColumn, int], ...]:
    """Zakazane kolumny nagłówka (nagłówek po ``normalize_text`` → kolumna od 1) z numerem kolumny od 1."""

    return tuple((_HEADERS[name], column) for name, column in header.items() if name in _HEADERS)


def remember(columns: Iterable[tuple[ForbiddenColumn, int]], values: Sequence[object]) -> None:
    """Zapamiętuje komórki zakazanych ``columns`` (numer od 1) wiersza ``values`` przeczytanego z pliku taty."""

    for column, number in columns:
        if number <= len(values):
            _KNOWN.add(column, values[number - 1])


def remember_value(column: ForbiddenColumn, value: object) -> None:
    """Zapamiętuje jedną komórkę zakazanej ``column`` przeczytaną z pliku taty."""

    _KNOWN.add(column, value)


def free_text(text: str) -> str:
    """Wolny tekst z zamaskowanymi telefonami (``[telefon]``) i wzmiankami ulic (``[ulica]``)."""

    return _PHONE.sub("[telefon]", _STREET.sub("[ulica]", text))


def guard(text: str, place: str) -> Guarded:
    """Tekst bez zakazanych wartości i z zamaskowanym wolnym tekstem; ``place`` nazywa miejsce w uwadze technicznej.

    Tekst bez zakazanych wartości, telefonów i ulic wraca bez zmian i bez uwag.
    """

    pieces: list[str] = []
    masked: list[ForbiddenColumn] = []
    position = 0
    for word in _WORD.finditer(text):
        if word.start() < position:
            continue
        hit = _longest(text, word.start(), _KNOWN.candidates(word.group(0)))
        if hit is None:
            continue
        end, column = hit
        pieces += [text[position : word.start()], column.mask]
        masked.append(column)
        position = end
    pieces.append(text[position:])
    columns = sorted(set(masked), key=lambda column: column.value)
    notes = tuple(f"Reguła danych: zamaskowano wartość kolumny {column.value} w: {place}." for column in columns)
    return Guarded(free_text("".join(pieces)), notes)


def _longest(text: str, start: int, candidates: Sequence[tuple[str, ForbiddenColumn]]) -> tuple[int, ForbiddenColumn] | None:
    best: tuple[int, ForbiddenColumn] | None = None
    for value, column in candidates:
        found = _pattern(value).match(text, start)
        if found is not None and (best is None or found.end() > best[0]):
            best = (found.end(), column)
    return best


@lru_cache(maxsize=4096)
def _pattern(value: str) -> re.Pattern[str]:
    """Wartość jako całe słowa, bez wielkości liter i z dowolnymi odstępami (także końcem linii) między słowami."""

    return re.compile(r"\s+".join(map(re.escape, value.split())) + r"(?!\w)", re.IGNORECASE)


def _value_text(value: object) -> str | None:
    """Tekst komórki do szukania: odstępy zwinięte, bez brzegowych znaków spoza słów; ``None``: nie ma czego szukać."""

    if value is None or isinstance(value, (bool, datetime, date, time)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    start = _WORD.search(text)
    if start is None:
        return None
    text = text[start.start() :]
    return text if len(text) >= MIN_VALUE else None
