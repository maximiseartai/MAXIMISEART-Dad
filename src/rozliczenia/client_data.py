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

Strażnik (``guarded``) przed zapisem pliku Logów i przed każdą wysyłką maskuje w tekście każdą znaną
wartość jako ``[adres]`` albo ``[numer Orange]`` i oddaje uwagę techniczną z nazwą kolumny i miejscem w tekście, bez
wartości. Wartość to ciąg jej słów: tekst ją zawiera, gdy ma te słowa po kolei, całe i bez wielkości liter, a między
nimi dowolne znaki spoza słów. Wartość w kilku liniach komórki, z „⏎” albo „\\|” tabeli Markdown, w cudzysłowie albo
z innymi odstępami jest więc zamaskowana tak samo, choć producent zapisał ją po swojemu przed strażnikiem. Z kilku
wartości od tego samego słowa wygrywa najdłuższa. Wartość krótsza niż ``MIN_VALUE`` znaków jest pomijana: nie
wskazuje klienta, a pasowałaby do zwykłych słów i liczb. Czas strażnika zależy od długości tekstu, nie od liczby
zapamiętanych wartości. Maskowanie wolnego tekstu (``free_text``) uwagi nie daje, bo telefon i ulica w opisie
technika to zwykła treść, nie wyciek kolumny.

Komórka, którą Excel trzyma jako liczbę (numer Orange albo telefon wpisany bez innego tekstu), ma tekst, który Excel
pokazuje (``shown``): liczba całkowita zapisana jako ułamek to jej cyfry. Tak ją zapamiętuje pamięć i tak ją sprawdza
strażnik liczby (``guarded_number``), który maskuje całą liczbę, bo jej cyfry to cała wartość. Format
General gubi ``+`` i zera z przodu, więc telefon ``+48600123456`` albo ``0048600123456`` to w komórce liczba
``48600123456``, a strażnik zna ją jako telefon. Tabela form telefonu z wynikiem strażnika i znane granice są w ADR 0025.

Tekst, który kolejka Skrzynki Zgłoszeń przyjmuje (nagłówek, części i każde pole tekstowe celu wysyłki), ma typ
``Outgoing``, a ``Outgoing`` daje tylko ten moduł: tekst po strażniku (``Guarded.text``), tekst narzędzia (``tool``)
i ich sklejenie (``+``). Goły ``str`` z pliku taty podany kolejce bez strażnika to błąd mypy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
import re
import threading
from typing import Final, TypeVar, final, overload

from . import register_columns
from .text import normalize_text

MIN_VALUE: Final = 5
"""Najkrótsza wartość zakazanej kolumny (po zwinięciu odstępów, od pierwszego słowa), której strażnik szuka w tekście."""

_Position = TypeVar("_Position")


class _ReadValues:
    """Znacznik pola Logów Uruchomienia (``Annotated``), które niesie wartości przeczytane z komórek pliku taty albo ze
    strony efenix, także liczby: strażnik Logów sprawdza w nim liczbę (``guarded_number``) i maskuje ją z zakazaną
    wartością albo telefonem jak tekst. Każda inna liczba Logów (numer wiersza, rozmiar, czas, liczba zleceń) to liczba,
    którą policzyło narzędzie."""


READ_VALUES: Final = _ReadValues()


class ForbiddenColumn(Enum):
    """Kolumna, której wartość nigdy nie wychodzi z komputera taty; ``value`` to jej nazwa w uwadze technicznej."""

    ADDRESS = register_columns.ADDRESS.target_header
    ORANGE = register_columns.CONTRACT_NUMBER.target_header

    @property
    def mask(self) -> str:
        return _MASKS[self]


_MASKS: Final = {ForbiddenColumn.ADDRESS: "[adres]", ForbiddenColumn.ORANGE: "[numer Orange]"}
_HEADERS: Final = {
    normalize_text(header): forbidden
    for forbidden, column in (
        (ForbiddenColumn.ADDRESS, register_columns.ADDRESS),
        (ForbiddenColumn.ORANGE, register_columns.CONTRACT_NUMBER),
    )
    for header in (column.target_header, *column.register_headers)
}
"""Nagłówek kolumny po ``normalize_text`` (Plik zbiorczy, Rejestr zleceń, INTERMAX i starsza kopia Rejestru)."""

_WORD: Final = re.compile(r"\w+")
_PHONE: Final = re.compile(
    r"(?<![\w+#])(?:(?:\+|00)?48[ -]?)?(?:\d{3}[ -]?\d{3}[ -]?\d{3}|\d{2}[ -]\d{3}[ -]\d{2}[ -]\d{2})(?!\w)"
)
"""Polski numer telefonu: komórkowy 3-3-3 (ze spacjami, myślnikami albo bez) i stacjonarny 2-3-2-2, z numerem
kierunkowym ``+48``, ``0048`` albo ``48`` albo bez. ``48`` bez ``+`` i zer to numer, któremu Excel zgubił je w komórce
(``+48600123456`` to liczba ``48600123456``).

Cyfry zaraz po ``#`` to ``NUMER ZL.`` (``#`` i numer), który może wyjść, więc nie są telefonem. Formy telefonu, których
wzorzec nie zna, to znane granice z ADR 0025.
"""
_STREET: Final = re.compile(
    r"(?<!\w)(?:ul|os|al|pl)\.[ \t]*(?:\w[\w-]*\.?[ \t]+){1,4}?\d+[^\W\d_]?(?:[ \t]*(?:/|m\.?)[ \t]*\d+[^\W\d_]?)?(?!\w)",
    re.IGNORECASE,
)
"""„ul.”, „os.”, „al.” albo „pl.” z nazwą do czterech słów i numerem domu (z lokalem po ``/`` albo ``m``)."""
_PHONE_MASK: Final = "[telefon]"
_STREET_MASK: Final = "[ulica]"
MASKS: Final = (*_MASKS.values(), _PHONE_MASK, _STREET_MASK)
"""Każda maska, którą strażnik wpisuje w miejsce wartości taty."""


_PASSED: Final = object()
"""Dowód, że ``Outgoing`` albo ``LogsText`` powstał w tym module; poza nim ruff (``TID251``) odrzuca jego import i atrybut modułu."""


@final
class Outgoing(str):
    """Tekst, który może wyjść z komputera taty: po strażniku, tekst narzędzia (``tool``) albo sklejenie takich tekstów.

    Konstruktor bez dowodu ``_PASSED`` rzuca ``TypeError``, a podklasy nie ma. Inna metoda ``str`` (wycinek, f-napis,
    ``join``, ``+`` z gołym ``str`` albo z podklasą) daje ``str``, którego kolejka nie przyjmuje.
    """

    __slots__ = ()

    def __new__(cls, text: str, proof: object) -> Outgoing:
        if proof is not _PASSED:
            raise TypeError("Tekst do wysyłki daje tylko rozliczenia.client_data: guarded albo tool.")
        return super().__new__(cls, text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("Tekst do wysyłki nie ma podklas.")

    @overload
    def __add__(self, other: Outgoing, /) -> Outgoing: ...
    @overload
    def __add__(self, other: str, /) -> str: ...
    def __add__(self, other: str, /) -> str:
        joined = str(self) + other
        return Outgoing(joined, _PASSED) if type(self) is Outgoing and type(other) is Outgoing else joined


def tool(text: str) -> Outgoing:
    """Tekst narzędzia do wysyłki: stałe, liczby, identyfikatory, tokeny okresu i uwagi techniczne, bez treści plików taty."""

    return Outgoing(text, _PASSED)


@final
class LogsText(str):
    """Znaki pliku Logów po strażniku Logów (``run_logs_guard.GuardedLogs.text``), jedyny tekst pliku w Archiwum Logów
    okresu (``outbox.ArchiveFile.text``), z ``logs_text``. To nie jest ``Outgoing``: pola Logów z wartością narzędzia
    (``run_logs_guard.TOOL_FIELDS``) strażnik przepuszcza bez maski, więc inny cel wysyłki tego tekstu nie bierze."""

    __slots__ = ()

    def __new__(cls, text: str, proof: object) -> LogsText:
        if proof is not _PASSED:
            raise TypeError("Tekst pliku Logów daje tylko rozliczenia.client_data.logs_text.")
        return super().__new__(cls, text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("Tekst pliku Logów nie ma podklas.")


def logs_text(text: str) -> LogsText:
    """Tekst pliku do Archiwum Logów okresu: Logi po strażniku albo ten plik z własnego pliku kolejki."""

    return LogsText(text, _PASSED)


@dataclass(frozen=True)
class Guarded:
    """Tekst po strażniku i uwagi techniczne o każdej zamaskowanej wartości (kolumna i miejsce, bez wartości)."""

    text: Outgoing
    notes: tuple[str, ...]


_NO_SUBCLASSES: Final = "Pamięć reguły danych nie ma podklas: maskowanie i uwagi techniczne daje tylko client_data.guarded."


class _WithoutSubclasses(type):
    """Metaklasa ``ForbiddenValues``: odmawia klasy z jej bazą, bo Python wybiera metaklasę po bazach, więc odmowy nie
    przesłania baza z własnym ``__init_subclass__`` stojąca przed ``ForbiddenValues``."""

    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, object], /, **kwargs: object) -> _WithoutSubclasses:
        if any(isinstance(base, _WithoutSubclasses) for base in bases):
            raise TypeError(_NO_SUBCLASSES)
        return super().__new__(mcs, name, bases, namespace, **kwargs)


@final
class ForbiddenValues(metaclass=_WithoutSubclasses):
    """Zakazane wartości przeczytane w jednej pracy Centrum i strażnik, który je maskuje w każdej wysyłce.

    Wartość to krotka jej słów bez wielkości liter. Pierwsze słowo daje długości (w słowach) wartości, które od niego
    się zaczynają, od najdłuższej, więc strażnik w każdym miejscu tekstu sprawdza tylko kilka krotek, ile by wartości
    nie było. Czytniki z wątków Uruchomień i producenci z wątków Centrum dzielą ją pod jednym zamkiem.

    Maskowanie i uwagi techniczne daje tylko strażnik modułu, ``guarded`` i ``guarded_number``: pamięć nie ma własnej
    metody strażnika, więc mypy odrzuca jej wywołanie (``attr-defined``), a oba tuż przed maskowaniem odmawiają obiektu
    innego typu niż dokładnie ``ForbiddenValues`` (``_memory``). Pamięć nie ma też podklas ani przypisanej metody: mypy
    odrzuca ``class`` (``final``), metaklasa odmawia podklasy w biegu pod każdą nazwą i przy każdej kolejności baz (także
    ``type()`` i ``types.new_class``), ``__init_subclass__`` odmawia podklasy zrobionej przez ``type.__new__`` z tą
    metaklasą, a ``__slots__`` odmawia przypisania metody pamięci (``setattr``, ``object.__setattr__``). Postaci, które
    przechodzą, pokazują próbki ``ZNANE_LUKI_UWAG`` i ``ZNANE_LUKI_PAMIECI`` w ``tests/test_regula_danych.py``.
    """

    __slots__ = ("_columns", "_lengths", "_lock")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_SUBCLASSES)

    def __init__(self, proof: object) -> None:
        if proof is not _PASSED:
            raise TypeError("Pamięć reguły danych daje tylko rozliczenia.client_data.empty_memory.")
        self._lock = threading.Lock()
        self._columns: dict[tuple[str, ...], ForbiddenColumn] = {}
        self._lengths: dict[str, tuple[int, ...]] = {}

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


def guarded(forbidden: ForbiddenValues, text: str, place: str) -> Guarded:
    """Tekst bez zakazanych wartości i z zamaskowanym wolnym tekstem; ``place`` nazywa miejsce w uwadze technicznej.

    Tekst bez zakazanych wartości, telefonów i ulic wraca bez zmian i bez uwag.
    """

    masked, columns = _masked(_memory(forbidden), str.__str__(text))
    return Guarded(Outgoing(free_text(masked), _PASSED), _notes(columns, place))


def guarded_number(forbidden: ForbiddenValues, value: int | float, place: str) -> Guarded | None:
    """Liczba z komórki pliku taty albo ze strony efenix po strażniku, w tekście, który pokazuje Excel (``shown``).

    ``None``: tekst liczby nie ma zakazanej wartości ani telefonu. Inaczej cała liczba staje się maską: zakazanej
    kolumny z uwagą techniczną jak w ``guarded`` albo ``[telefon]`` bez uwagi, więc z liczby nie zostaje żadna cyfra.
    Telefonem jest tylko liczba całkowita (także zapisana jako ułamek), bo telefon wpisany w komórkę nie ma części
    ułamkowej: 9 cyfr albo ``48`` i 9 cyfr, gdy Excel zgubił ``+`` albo ``00`` przed ``48``.
    """

    text = shown(value)
    _, columns = _masked(_memory(forbidden), text)
    if columns:
        return Guarded(Outgoing(" ".join(column.mask for column in _ordered(columns)), _PASSED), _notes(columns, place))
    if (isinstance(value, int) or value.is_integer()) and _PHONE.search(text):
        return Guarded(Outgoing(_PHONE_MASK, _PASSED), ())
    return None


def _masked(memory: ForbiddenValues, text: str) -> tuple[str, set[ForbiddenColumn]]:
    words = list(_WORD.finditer(text))
    folded = [word.group(0).casefold() for word in words]
    pieces: list[str] = []
    masked: set[ForbiddenColumn] = set()
    position = index = 0
    with memory._lock:
        while index < len(words):
            hit = _longest(memory, folded, index)
            if hit is None:
                index += 1
                continue
            length, column = hit
            pieces += [text[position : words[index].start()], column.mask]
            masked.add(column)
            position = words[index + length - 1].end()
            index += length
    pieces.append(text[position:])
    return "".join(pieces), masked


def _longest(memory: ForbiddenValues, folded: Sequence[str], index: int) -> tuple[int, ForbiddenColumn] | None:
    """Najdłuższa zapamiętana wartość od słowa ``index``: jej długość w słowach i kolumna."""

    for length in memory._lengths.get(folded[index], ()):
        if index + length <= len(folded):
            column = memory._columns.get(tuple(folded[index : index + length]))
            if column is not None:
                return length, column
    return None

def empty_memory() -> ForbiddenValues:
    """Pusta pamięć jednej pracy Centrum (``app.create_app``, ``CentrumWork.forbidden``) albo odtworzenia Uruchomienia."""

    return ForbiddenValues(_PASSED)


def _memory(forbidden: ForbiddenValues) -> ForbiddenValues:
    """Pamięć tuż przed wywołaniem strażnika: obiekt, którego typ nie jest dokładnie ``ForbiddenValues`` (atrapa albo owijka
    podana przez ``cast`` lub ``Any``, obiekt z przypisaną obcą klasą, podklasa), daje ``TypeError``, bo jego ``_masked``
    dałby własne maskowanie i uwagi techniczne."""

    if type(forbidden) is not ForbiddenValues:
        raise TypeError(f"Strażnik reguły danych bierze tylko pamięć ForbiddenValues z empty_memory, nie {type(forbidden).__name__}.")
    return forbidden


def forbidden_columns(header: Mapping[str, _Position]) -> tuple[tuple[ForbiddenColumn, _Position], ...]:
    """Zakazane kolumny nagłówka (nagłówek po ``normalize_text`` → położenie kolumny) z ich położeniem."""

    return tuple((_HEADERS[name], position) for name, position in header.items() if name in _HEADERS)


def free_text(text: str) -> str:
    """Wolny tekst z zamaskowanymi telefonami (``[telefon]``) i wzmiankami ulic (``[ulica]``)."""

    return _PHONE.sub(_PHONE_MASK, _STREET.sub(_STREET_MASK, text))


def shown(value: object) -> str:
    """Tekst komórki tak, jak ją pokazuje Excel: liczba całkowita zapisana przez Excel jako ułamek (``4801234567.0``)
    to jej cyfry, a każda inna wartość jej zapis (``str``)."""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _ordered(columns: Iterable[ForbiddenColumn]) -> list[ForbiddenColumn]:
    return sorted(columns, key=lambda column: column.value)


def _notes(columns: Iterable[ForbiddenColumn], place: str) -> tuple[str, ...]:
    return tuple(f"Reguła danych: zamaskowano wartość kolumny {column.value} w: {place}." for column in _ordered(columns))


def _value_words(value: object) -> tuple[str, ...] | None:
    """Słowa komórki do szukania, bez wielkości liter, w tekście, który pokazuje Excel (``shown``); ``None``: nie ma
    czego szukać albo wartość jest za krótka."""

    if value is None or isinstance(value, (bool, datetime, date, time)):
        return None
    text = " ".join(shown(value).split())
    first = _WORD.search(text)
    if first is None or len(text) - first.start() < MIN_VALUE:
        return None
    return tuple(word.casefold() for word in _WORD.findall(text))
