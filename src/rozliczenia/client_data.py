"""Reguła danych (ADR 0025): co z treści plików taty może wyjść z jego komputera do Skrzynki Zgłoszeń.

Nigdy nie wychodzą wartości kolumn ``ADRES`` i ``NUMER UMOWY/ZLECENIA ORANGE`` (w Rejestrze zleceń i INTERMAX także
``adres`` i ``NUMER UMOWY``) ani dane adresowe ze strony zlecenia efenix, bo wskazują klienta. Każda inna kolumna
może wyjść, a wolny tekst idzie w całości z zamaskowanymi numerami telefonów (``[telefon]``) i wzmiankami ulic
(„ul.”, „os.”, „al.”, „pl.” z nazwą i numerem, ``[ulica]``).

Zakazane wartości zna pamięć jednej pracy Centrum (``ForbiddenValues``): Centrum tworzy ją przy starcie i daje
każdemu czytnikowi Wierszy danych, który czyta dla niego plik taty, i każdemu producentowi wysyłki. Czytnik oddaje
jej przy odczycie komórki zakazanych kolumn (``remember``, ``remember_value``), a Wycena w efenix dane adresowe
każdego wiersza listy wyników jako wartość ``ADRES``. Pamięć tylko rośnie i nie trafia na dysk, więc strażnik
chroni każdą wysyłkę przed wartością z każdego pliku, który ta praca Centrum przeczytała, także Uwagę taty, która nie
ma swojego Uruchomienia. Proces bez Centrum (Skrypt dla maszyn) nie ma pamięci, bo niczego nie wysyła.

Strażnik (``ForbiddenValues.guard``) przed zapisem pliku Logów i przed każdą wysyłką maskuje w tekście każdą znaną
wartość jako ``[adres]`` albo ``[numer Orange]`` i oddaje uwagę techniczną z nazwą kolumny i miejscem w tekście, bez
wartości. Wartość to ciąg jej słów: tekst ją zawiera, gdy ma te słowa po kolei, całe i bez wielkości liter, a między
nimi dowolne znaki spoza słów. Wartość w kilku liniach komórki, z „⏎” albo „\\|” tabeli Markdown, w cudzysłowie albo
z innymi odstępami jest więc zamaskowana tak samo, choć producent zapisał ją po swojemu przed strażnikiem. Z kilku
wartości od tego samego słowa wygrywa najdłuższa. Wartość krótsza niż ``MIN_VALUE`` znaków jest pomijana: nie
wskazuje klienta, a pasowałaby do zwykłych słów i liczb. Czas strażnika zależy od długości tekstu, nie od liczby
zapamiętanych wartości. Maskowanie wolnego tekstu (``free_text``) uwagi nie daje, bo telefon i ulica w opisie
technika to zwykła treść, nie wyciek kolumny.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
import re
import threading
from typing import Final, TypeVar

from .worker_config import normalize_text

MIN_VALUE: Final = 5
"""Najkrótsza wartość zakazanej kolumny (po zwinięciu odstępów, od pierwszego słowa), której strażnik szuka w tekście."""

_Position = TypeVar("_Position")


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
    r"(?<![\w+#])(?:(?:\+|00)48[ -]?)?(?:\d{3}[ -]?\d{3}[ -]?\d{3}|\d{2}[ -]\d{3}[ -]\d{2}[ -]\d{2})(?!\w)"
)
"""Polski numer telefonu: komórkowy 3-3-3 (ze spacjami, myślnikami albo bez) i stacjonarny 2-3-2-2, z +48 albo bez.

Cyfry zaraz po ``#`` to ``NUMER ZL.`` (``#`` i numer), który może wyjść, więc nie są telefonem.
"""
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


class ForbiddenValues:
    """Zakazane wartości przeczytane w jednej pracy Centrum i strażnik, który je maskuje w każdej wysyłce.

    Wartość to krotka jej słów bez wielkości liter. Pierwsze słowo daje długości (w słowach) wartości, które od niego
    się zaczynają, od najdłuższej, więc strażnik w każdym miejscu tekstu sprawdza tylko kilka krotek, ile by wartości
    nie było. Czytniki z wątków Uruchomień i producenci z wątków Centrum dzielą ją pod jednym zamkiem.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._columns: dict[tuple[str, ...], ForbiddenColumn] = {}
        self._lengths: dict[str, tuple[int, ...]] = {}

    def remember(self, columns: Iterable[tuple[ForbiddenColumn, int]], values: Sequence[object]) -> None:
        """Zapamiętuje komórki zakazanych ``columns`` (numer od 1) wiersza ``values`` przeczytanego z pliku taty."""

        for column, number in columns:
            if number <= len(values):
                self.remember_value(column, values[number - 1])

    def remember_value(self, column: ForbiddenColumn, value: object) -> None:
        """Zapamiętuje jedną komórkę zakazanej ``column`` przeczytaną z pliku taty; ta sama wartość zostaje przy
        kolumnie, pod którą przyszła pierwsza."""

        words = _value_words(value)
        if words is None:
            return
        with self._lock:
            if words in self._columns:
                return
            self._columns[words] = column
            lengths = self._lengths.get(words[0], ())
            if len(words) not in lengths:
                self._lengths[words[0]] = tuple(sorted((*lengths, len(words)), reverse=True))

    def guard(self, text: str, place: str) -> Guarded:
        """Tekst bez zakazanych wartości i z zamaskowanym wolnym tekstem; ``place`` nazywa miejsce w uwadze technicznej.

        Tekst bez zakazanych wartości, telefonów i ulic wraca bez zmian i bez uwag.
        """

        words = list(_WORD.finditer(text))
        folded = [word.group(0).casefold() for word in words]
        pieces: list[str] = []
        masked: set[ForbiddenColumn] = set()
        position = index = 0
        with self._lock:
            while index < len(words):
                hit = self._longest(folded, index)
                if hit is None:
                    index += 1
                    continue
                length, column = hit
                pieces += [text[position : words[index].start()], column.mask]
                masked.add(column)
                position = words[index + length - 1].end()
                index += length
        pieces.append(text[position:])
        notes = tuple(
            f"Reguła danych: zamaskowano wartość kolumny {column.value} w: {place}."
            for column in sorted(masked, key=lambda column: column.value)
        )
        return Guarded(free_text("".join(pieces)), notes)

    def _longest(self, folded: Sequence[str], index: int) -> tuple[int, ForbiddenColumn] | None:
        """Najdłuższa zapamiętana wartość od słowa ``index``: jej długość w słowach i kolumna."""

        for length in self._lengths.get(folded[index], ()):
            if index + length <= len(folded):
                column = self._columns.get(tuple(folded[index : index + length]))
                if column is not None:
                    return length, column
        return None


def forbidden_columns(header: Mapping[str, _Position]) -> tuple[tuple[ForbiddenColumn, _Position], ...]:
    """Zakazane kolumny nagłówka (nagłówek po ``normalize_text`` → położenie kolumny) z ich położeniem."""

    return tuple((_HEADERS[name], position) for name, position in header.items() if name in _HEADERS)


def forbidden_column(header: object) -> ForbiddenColumn | None:
    """Zakazana kolumna o nagłówku ``header`` (komórka nagłówka albo nagłówek docelowy); ``None``: kolumna może wyjść."""

    return None if header is None else _HEADERS.get(normalize_text(header))


def free_text(text: str) -> str:
    """Wolny tekst z zamaskowanymi telefonami (``[telefon]``) i wzmiankami ulic (``[ulica]``)."""

    return _PHONE.sub("[telefon]", _STREET.sub("[ulica]", text))


def _value_words(value: object) -> tuple[str, ...] | None:
    """Słowa komórki do szukania, bez wielkości liter; ``None``: nie ma czego szukać albo wartość jest za krótka.

    Liczba całkowita zapisana przez Excel jako ułamek (``4801234567.0``) to jej cyfry, tak jak ją pokazuje Excel.
    """

    if value is None or isinstance(value, (bool, datetime, date, time)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    first = _WORD.search(text)
    if first is None or len(text) - first.start() < MIN_VALUE:
        return None
    return tuple(word.casefold() for word in _WORD.findall(text))
