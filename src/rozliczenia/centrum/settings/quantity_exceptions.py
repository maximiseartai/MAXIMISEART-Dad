"""Wyjątki Kontroli ilości w pliku ``wyjatki-ilosci.yaml`` (ADR 0033): różnice z Kontroli ilości, które tata oznaczył
w sekcji Reguły ilości „To był wyjątek”, więc lista „Tu wpisałeś inaczej niż reguła” ich już nie pokazuje.

Wyjątek to jedna komórka jednego Wiersza danych: okres, numer wiersza Pliku zbiorczego, kolumna i wpis taty, a do tego
odcisk (``fingerprint``) tych pól razem z treścią wiersza, którą czytają Reguły ilości (``UMOWA``, ``URZĄDZENIA``,
``CZYNNOŚCI``, dzień tygodnia i godzina z ``DATA``). Odcisk jest id wyjątku: ta sama różnica po kolejnym Przebiegu,
po restarcie i po zmianie reguły (wartość reguły do odcisku nie wchodzi) daje to samo id, a inny wpis taty, zmieniona
treść wiersza albo wiersz przesunięty w pliku dają inne, więc taka różnica wraca na listę. Id nie bierze się z licznika,
więc nigdy nie przechodzi na inny wyjątek: „Cofnij” starego wiersza Historii rusza tylko swój wyjątek, a zapis nie
potrzebuje kluczy Historii.

Plik ma tylko okres, numer wiersza, literę, liczbę taty i odcisk SHA-256, więc Historia Ustawień, Logi Centrum i
Zgłoszenie nie dostają treści wiersza, adresu ani numerów. Brak pliku to brak wyjątków. Klucz Historii to
``wyjatki.<odcisk>``, a wartość to wpis jako JSON (``EntriesById``).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Final

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import EntriesById, FieldName, FieldPath, FieldProblem, KeyChange, SettingsFile, settings_yaml
from rozliczenia.collective_layout import QUANTITY_LETTERS
from rozliczenia.order_facts import NON_NUMERIC, TataValue
from rozliczenia.quantity_engine import OrderContent
from rozliczenia.settlement_period import PERIOD_TOKEN_PATTERN

EXCEPTIONS_FILE: Final = "wyjatki-ilosci.yaml"
"""Plik wyjątków Kontroli ilości w ``config``; czyta go i pisze tylko ``rozliczenia.centrum.settings``."""

SECTION: Final[FieldName] = "wyjatki"
_SCHEMA_VERSION: Final = 1
PERIOD: Final[FieldName] = "okres"
ROW: Final[FieldName] = "wiersz"
COLUMN: Final[FieldName] = "kolumna"
TATA: Final[FieldName] = "tata"
FINGERPRINT: Final[FieldName] = "odcisk"
_FIELDS: Final = (PERIOD, ROW, COLUMN, TATA, FINGERPRINT)
_FINGERPRINT: Final = re.compile(r"[0-9a-f]{16}")


@dataclass(frozen=True)
class QuantityException:
    """Różnica Kontroli ilości w jednej komórce, którą tata oznaczył „To był wyjątek”."""

    period: str
    row: int
    column: str
    tata: TataValue
    fingerprint: str

    @property
    def id(self) -> str:
        return self.fingerprint


def exception_of(period: str, row: int, column: str, tata: TataValue, order: OrderContent) -> QuantityException:
    """Wyjątek różnicy w kolumnie ``column`` Wiersza danych ``row`` okresu ``period``, w którym tata wpisał ``tata``, a
    Reguły ilości czytają ``order`` (zawsze z porą z ``DATA``: wiersz bez niej nie ma różnic)."""

    assert order.started is not None, "wiersz bez daty i godziny w DATA nie ma różnic Kontroli ilości"
    fields = [
        period,
        row,
        column,
        tata,
        order.contract,
        order.devices,
        order.activities,
        order.started.weekday,
        f"{order.started.at:%H:%M}",
    ]
    digest = hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()
    return QuantityException(period, row, column, tata, digest[:16])


def parse(data: bytes | None) -> tuple[QuantityException, ...] | FieldProblem:
    """Wyjątki z bajtów pliku; ``None`` (brak pliku) to brak wyjątków, zła treść to pierwszy problem."""

    if data is None:
        return ()
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(EXCEPTIONS_FILE))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(EXCEPTIONS_FILE))
    if not isinstance(document, dict):
        return FieldProblem(None, messages.damaged(EXCEPTIONS_FILE))
    if document.get("schema_version") != _SCHEMA_VERSION:
        return FieldProblem(None, messages.other_schema(EXCEPTIONS_FILE))
    unknown = next((place for place, key in enumerate(document, 1) if key not in ("schema_version", SECTION)), None)
    if unknown is not None:
        return FieldProblem(None, messages.unknown_key(EXCEPTIONS_FILE, unknown))
    entries = document.get(SECTION, [])
    if not isinstance(entries, list):
        return _bad(FieldPath(SECTION))
    found: list[QuantityException] = []
    for index, entry in enumerate(entries):
        exception = _exception(entry, index)
        if isinstance(exception, FieldProblem):
            return exception
        if any(known.id == exception.id for known in found):
            return _bad(FieldPath(SECTION, index, FINGERPRINT))
        found.append(exception)
    return tuple(found)


def _exception(entry: object, index: int) -> QuantityException | FieldProblem:
    if not isinstance(entry, dict) or set(entry) != set(_FIELDS):
        return _bad(FieldPath(SECTION, index))
    period, row, column, tata, fingerprint = (entry[field] for field in _FIELDS)
    if not isinstance(period, str) or re.fullmatch(PERIOD_TOKEN_PATTERN, period) is None:
        return _bad(FieldPath(SECTION, index, PERIOD))
    if type(row) is not int or row < 1:
        return _bad(FieldPath(SECTION, index, ROW))
    if column not in QUANTITY_LETTERS:
        return _bad(FieldPath(SECTION, index, COLUMN))
    if not (type(tata) is int or tata == NON_NUMERIC):
        return _bad(FieldPath(SECTION, index, TATA))
    if not isinstance(fingerprint, str) or _FINGERPRINT.fullmatch(fingerprint) is None:
        return _bad(FieldPath(SECTION, index, FINGERPRINT))
    return QuantityException(period, row, str(column), tata, fingerprint)


def _bad(place: FieldPath) -> FieldProblem:
    return FieldProblem(place, messages.bad_field(EXCEPTIONS_FILE, place, messages.SAVE_AGAIN))


def _entry(exception: QuantityException) -> dict[str, object]:
    return {
        PERIOD: exception.period,
        ROW: exception.row,
        COLUMN: exception.column,
        TATA: exception.tata,
        FINGERPRINT: exception.fingerprint,
    }


def entry_of(entry: object) -> QuantityException | None:
    """Wyjątek z wpisu pliku (także z wartości klucza Historii); ``None``: wpisu nie da się odczytać."""

    found = _exception(entry, 0)
    return None if isinstance(found, FieldProblem) else found


def dump(exceptions: tuple[QuantityException, ...]) -> str:
    return settings_yaml({"schema_version": _SCHEMA_VERSION, SECTION: [_entry(exception) for exception in exceptions]})


def described(exception: QuantityException) -> str:
    """Wyjątek w Zgłoszeniu i Logach: okres, wiersz, kolumna i wpis taty, bez treści wiersza."""

    return f"okres {exception.period}, wiersz {exception.row}, {exception.column}, wpis taty {exception.tata}"


def reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu: dodany albo usunięty wyjątek opisem z samego wpisu, a wartość, której nie da się odczytać,
    samym kluczem."""

    before, after = _from_json(change.before), _from_json(change.after)
    if change.before is None and after is not None:
        return f"dodano wyjątek: {described(after)}"
    if change.after is None and before is not None:
        return f"usunięto wyjątek: {described(before)}"
    if before is not None and after is not None:
        return f"zmieniono wyjątek: {described(before)} → {described(after)}"
    return f"{change.key}: zmieniono"


def _from_json(value: str | None) -> QuantityException | None:
    if value is None:
        return None
    try:
        return entry_of(json.loads(value))
    except ValueError:
        return None


_ENTRIES: Final = EntriesById[QuantityException](SECTION, _entry, entry_of)

EXCEPTIONS: Final = SettingsFile[tuple[QuantityException, ...]](
    name=EXCEPTIONS_FILE,
    parse=parse,
    dump=dump,
    diff=_ENTRIES.diff,
    restore=_ENTRIES.restore,
    reported=reported,
    default=(),
)
