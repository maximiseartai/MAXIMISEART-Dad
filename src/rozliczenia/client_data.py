from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
import re
import threading
from typing import Final, TypeVar, final, overload
import weakref

from . import register_columns
from .order_kind import OrderKind, order_kind
from .text import normalize_text

MIN_VALUE: Final = 5
"""Najkrótsza wartość zakazanej kolumny (po zwinięciu odstępów, od pierwszego słowa), której strażnik szuka w tekście."""

_Position = TypeVar("_Position")


class _ReadValues: ...


READ_VALUES: Final = _ReadValues()



class ForbiddenColumn(Enum):
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

_WORD: Final = re.compile(r"\w+")
_PHONE: Final = re.compile(
    r"(?<![\w+#])(?:(?:\+|00)?48[ -]?)?(?!0)(?:\d{3}[ -]?\d{3}[ -]?\d{3}|\d{2}[ -]\d{3}[ -]\d{2}[ -]\d{2})(?!\w)"
)
_STREET: Final = re.compile(
    r"(?<!\w)(?:ul|os|al|pl)\.[ \t]*(?:\w[\w-]*\.?[ \t]+){1,4}?\d+[^\W\d_]?(?:[ \t]*(?:/|m\.?)[ \t]*\d+[^\W\d_]?)?(?!\w)",
    re.IGNORECASE,
)
"""„ul.”, „os.”, „al.” albo „pl.” z nazwą do czterech słów i numerem domu (z lokalem po ``/`` albo ``m``)."""
_PHONE_MASK: Final = "[telefon]"
_STREET_MASK: Final = "[ulica]"
MASKS: Final = (*_MASKS.values(), _PHONE_MASK, _STREET_MASK)


_PASSED: Final = object()


_REFUSALS: Final[dict[type, str]] = {}


class WithoutSubclasses(type):
    """Metaklasa klasy bez podklas: klasa podaje odmowę w nagłówku
    (``class K(metaclass=WithoutSubclasses, refusal=…)``), a ``__new__`` metaklasy sam rzuca ``TypeError`` z tą odmową,
    gdy któraś baza nowej klasy ma tę metaklasę. Python wybiera metaklasę po bazach, więc odmawia ``class``, ``type()``
    i ``types.new_class`` przy każdej kolejności baz, a baza z własnym ``__init_subclass__`` stojąca przed klasą bez
    podklas tego nie przesłania. Odmawia tylko wywołanie tego ``__new__``: klasa zrobiona z jego pominięciem i relacja
    podklasy przypisana w trakcie działania powstają, więc regułę klasy trzyma jeszcze kontrola w chwili jej użycia."""

    def __new__(
        mcs, name: str, bases: tuple[type, ...], namespace: dict[str, object], /, *, refusal: str | None = None, **kwargs: object
    ) -> WithoutSubclasses:
        for base in bases:
            if isinstance(base, WithoutSubclasses):
                raise TypeError(next((_REFUSALS[k] for k in base.__mro__ if k in _REFUSALS), f"{base.__qualname__} nie ma podklas."))
        if refusal is None:
            raise TypeError("Klasa bez podklas podaje odmowę: class K(metaclass=WithoutSubclasses, refusal=…).")
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        _REFUSALS[cls] = refusal
        return cls


_NO_OUTGOING_SUBCLASSES: Final = "Tekst do wysyłki nie ma podklas."
_NO_LOGS_TEXT_SUBCLASSES: Final = "Tekst pliku Logów nie ma podklas."


@final
class Outgoing(str, metaclass=WithoutSubclasses, refusal=_NO_OUTGOING_SUBCLASSES):
    """Tekst, który może wyjść z komputera taty: po strażniku, tekst narzędzia (``tool``) albo sklejenie takich tekstów.

    Konstruktor bez dowodu ``_PASSED`` rzuca ``TypeError``. Podklasie przy tworzeniu odmawia metaklasa
    (``WithoutSubclasses``; ``class`` z własną metaklasą, która woła ``type.__new__`` wprost, ją omija), a przy
    ``type.__new__`` z jej pominięciem ``__init_subclass__``, chyba że przesłania go baza bez ``super()`` przed typem. To
    wcześniejszy błąd, a regułę trzyma plik kolejki, który bierze tylko dokładny typ (``outbox._queue_text``). Inna metoda ``str`` (wycinek,
    f-napis, ``join``, ``+`` z gołym ``str`` albo z podklasą) daje ``str``, którego kolejka nie przyjmuje.
    """

    __slots__ = ()

    def __new__(cls, text: str, proof: object) -> Outgoing:
        if proof is not _PASSED:
            raise TypeError("Tekst do wysyłki daje tylko rozliczenia.client_data: guarded albo tool.")
        return super().__new__(cls, text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_OUTGOING_SUBCLASSES)

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
class LogsText(str, metaclass=WithoutSubclasses, refusal=_NO_LOGS_TEXT_SUBCLASSES):
    """Znaki pliku Logów po strażniku Logów (``run_logs_guard.GuardedLogs.text``), jedyny tekst pliku w Archiwum Logów
    okresu (``outbox.ArchiveFile.text``), z ``logs_text``. To nie jest ``Outgoing``: pola Logów z wartością narzędzia
    strażnik przepuszcza bez maski, więc inny cel wysyłki tego tekstu nie bierze."""

    __slots__ = ()

    def __new__(cls, text: str, proof: object) -> LogsText:
        if proof is not _PASSED:
            raise TypeError("Tekst pliku Logów daje tylko rozliczenia.client_data.logs_text.")
        return super().__new__(cls, text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_LOGS_TEXT_SUBCLASSES)


def logs_text(text: str) -> LogsText:
    """Tekst pliku do Archiwum Logów okresu: Logi po strażniku albo ten plik z własnego pliku kolejki."""

    return LogsText(text, _PASSED)


@dataclass(frozen=True)
class Guarded:
    text: Outgoing
    notes: tuple[str, ...]


_NO_SUBCLASSES: Final = "Pamięć reguły danych nie ma podklas: maskowanie i uwagi techniczne daje tylko client_data.guarded."


@final
class ForbiddenValues(metaclass=WithoutSubclasses, refusal=_NO_SUBCLASSES):
    """Zakazane wartości przeczytane w jednej pracy Centrum i strażnik, który je maskuje w każdej wysyłce.

    Wartość to krotka jej słów bez wielkości liter. Pierwsze słowo daje długości (w słowach) wartości, które od niego
    się zaczynają, od najdłuższej, więc strażnik w każdym miejscu tekstu sprawdza tylko kilka krotek, ile by wartości
    nie było. Czytniki z wątków Uruchomień i producenci z wątków Centrum dzielą ją pod jednym zamkiem.
    """

    __slots__ = ("__weakref__",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_SUBCLASSES)

    def __init__(self, proof: object) -> None:
        if proof is not _PASSED:
            raise TypeError("Pamięć reguły danych daje tylko rozliczenia.client_data.empty_memory.")
        _WORDS[self] = _Words()

    def remember_value(self, column: ForbiddenColumn, value: object) -> None:
        words = _value_words(value)
        if words is None:
            return
        memory = _WORDS[self]
        with memory.lock:
            if words in memory.columns:
                return
            memory.columns[words] = column
            lengths = memory.lengths.get(words[0], ())
            if len(words) not in lengths:
                memory.lengths[words[0]] = tuple(sorted((*lengths, len(words)), reverse=True))


class _Words:
    __slots__ = ("columns", "lengths", "lock")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.columns: dict[tuple[str, ...], ForbiddenColumn] = {}
        self.lengths: dict[str, tuple[int, ...]] = {}


_WORDS: Final[weakref.WeakKeyDictionary[ForbiddenValues, _Words]] = weakref.WeakKeyDictionary()


def guarded(forbidden: ForbiddenValues, text: str, place: str) -> Guarded:
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


def _masked(memory: _Words, text: str) -> tuple[str, set[ForbiddenColumn]]:
    words = list(_WORD.finditer(text))
    folded = [word.group(0).casefold() for word in words]
    pieces: list[str] = []
    masked: set[ForbiddenColumn] = set()
    position = index = 0
    with memory.lock:
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


def _longest(memory: _Words, folded: Sequence[str], index: int) -> tuple[int, ForbiddenColumn] | None:
    for length in memory.lengths.get(folded[index], ()):
        if index + length <= len(folded):
            column = memory.columns.get(tuple(folded[index : index + length]))
            if column is not None:
                return length, column
    return None

def remembered(forbidden: ForbiddenValues) -> int:
    """Ile wartości zna pamięć ``forbidden``. Pamięć tylko rośnie, więc ta sama liczba to ta sama pamięć, a wynik strażnika
    dla tego samego tekstu się nie zmienia (``template_archive.TemplateChecks`` nie sprawdza drugi raz tekstów Wzorca)."""

    memory = _memory(forbidden)
    with memory.lock:
        return len(memory.columns)


def empty_memory() -> ForbiddenValues:
    return ForbiddenValues(_PASSED)


def _memory(forbidden: ForbiddenValues) -> _Words:
    if type(forbidden) is not ForbiddenValues:
        raise TypeError(f"Strażnik reguły danych bierze tylko pamięć ForbiddenValues z empty_memory, nie {type(forbidden).__name__}.")
    return _WORDS[forbidden]


def forbidden_columns(header: Mapping[str, _Position]) -> tuple[tuple[ForbiddenColumn, _Position], ...]:
    return tuple((_HEADERS[name], position) for name, position in header.items() if name in _HEADERS)


def free_text(text: str) -> str:
    return _PHONE.sub(_PHONE_MASK, _STREET.sub(_STREET_MASK, text))


def shown(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _ordered(columns: Iterable[ForbiddenColumn]) -> list[ForbiddenColumn]:
    return sorted(columns, key=lambda column: column.value)


def _notes(columns: Iterable[ForbiddenColumn], place: str) -> tuple[str, ...]:
    return tuple(f"Reguła danych: zamaskowano wartość kolumny {column.value} w: {place}." for column in _ordered(columns))


def _value_words(value: object) -> tuple[str, ...] | None:
    if value is None or isinstance(value, (bool, datetime, date, time)) or order_kind(value) is not OrderKind.OTHER:
        return None
    text = " ".join(shown(value).split())
    first = _WORD.search(text)
    if first is None or len(text) - first.start() < MIN_VALUE:
        return None
    return tuple(word.casefold() for word in _WORD.findall(text))
