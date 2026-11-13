"""Przypomnienia o raporcie w pliku ``przypomnienia.yaml`` (schemat 1): czy idą, od którego dnia, pory, godzina
pierwszego przypomnienia, pierwsze zdanie treści i stopka taty (ADR 0032, zmienia ADR 0030).

Kształt pliku sprawdza ``parse`` (mapa, schemat, znane pola, typy, godziny ``GG:MM``), a reguły ustawień przypomnień
``ReminderSettings.of``, ta sama budowa co w rdzeniu raportów. Brak pliku i pole, którego w pliku nie ma, to wartości
domyślne z ADR 0030 (``DEFAULT_REMINDERS``): bez pliku przypomnienia są wyłączone, tak jak przed Wydaniem bez dnia
wdrożenia. Godziny stoją w pliku jako tekst w cudzysłowie, bo YAML czyta ``08:00`` bez cudzysłowu jako liczbę.

Klucz Historii to ``przypomnienia.<pole>``, a pora ma wartość ``08:00–17:00``. Zgłoszenie podaje wartości wszystkich pól
oprócz stopki, która ma imię i telefon taty: przy niej tylko, że się zmieniła.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, time
import re
from typing import Final

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldName, FieldPath, FieldProblem, KeyChange, SettingsFile, settings_yaml
from rozliczenia.worker_reports import (
    DEFAULT_REMINDERS,
    ReminderProblem,
    ReminderProblemKind,
    ReminderSchedule,
    ReminderSettings,
    TimeRange,
)

REMINDERS_FILE: Final = "przypomnienia.yaml"
"""Plik Przypomnień o raporcie w ``config``; czyta go i pisze tylko ``rozliczenia.centrum.settings``."""

SECTION: Final = "przypomnienia"
_SCHEMA_VERSION: Final = 1
ENABLED: Final[FieldName] = "wlaczone"
SINCE: Final[FieldName] = "wlaczone_od"
MORNING: Final[FieldName] = "pora_poranna"
EVENING: Final[FieldName] = "pora_wieczorna"
FIRST: Final[FieldName] = "pierwsze_przypomnienie"
TEXT: Final[FieldName] = "tresc"
FOOTER: Final[FieldName] = "stopka"
START: Final[FieldName] = "od"
END: Final[FieldName] = "do"
_KEYS: Final = (ENABLED, SINCE, MORNING, EVENING, FIRST, TEXT, FOOTER)
_TIME: Final = re.compile(r"(?P<hour>[01]?[0-9]|2[0-3]):(?P<minute>[0-5][0-9])")
"""Godzina z pliku albo formularza: ``08:00`` i ``8:00`` (tata pisze godzinę bez zera), w pliku zawsze ``GG:MM``."""
_RANGE: Final = " – "
"""Między początkiem a końcem pory w wartości klucza Historii (``08:00 – 17:00``)."""


def parse(data: bytes | None) -> ReminderSettings | FieldProblem:
    """Przypomnienia z bajtów pliku; ``None`` (brak pliku) to wartości domyślne, zła treść to pierwszy problem."""

    if data is None:
        return DEFAULT_REMINDERS
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(REMINDERS_FILE))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(REMINDERS_FILE))
    if not isinstance(document, dict):
        return FieldProblem(None, messages.damaged(REMINDERS_FILE))
    if document.get("schema_version") != _SCHEMA_VERSION:
        return FieldProblem(None, messages.other_schema(REMINDERS_FILE))
    unknown = next((place for place, key in enumerate(document, 1) if key != "schema_version" and key not in _KEYS), None)
    if unknown is not None:
        return FieldProblem(None, messages.unknown_key(REMINDERS_FILE, unknown))
    return _settings(document)


def _settings(document: Mapping[object, object]) -> ReminderSettings | FieldProblem:
    default = DEFAULT_REMINDERS
    enabled = document.get(ENABLED, default.enabled)
    if not isinstance(enabled, bool):
        return _bad(FieldPath(ENABLED))
    since = document.get(SINCE, default.since)
    if since is not None and type(since) is not date:
        return _bad(FieldPath(SINCE))
    morning = _range(document.get(MORNING, _range_document(default.schedule.morning)), MORNING)
    if isinstance(morning, FieldProblem):
        return morning
    evening = _range(document.get(EVENING, _range_document(default.schedule.evening)), EVENING)
    if isinstance(evening, FieldProblem):
        return evening
    first = parse_time(document.get(FIRST, _shown_time(default.schedule.first)), FieldPath(FIRST))
    if isinstance(first, FieldProblem):
        return first
    text, footer = document.get(TEXT, default.text), document.get(FOOTER, default.footer)
    if not isinstance(text, str):
        return _bad(FieldPath(TEXT))
    if not isinstance(footer, str):
        return _bad(FieldPath(FOOTER))
    return settings_of(enabled, since, ReminderSchedule(morning, evening, first), text, footer)


def settings_of(
    enabled: bool, since: date | None, schedule: ReminderSchedule, text: str, footer: str
) -> ReminderSettings | FieldProblem:
    """``ReminderSettings.of`` z problemem jako polem pliku i zdaniem dla taty: ta sama reguła dla pliku i formularza."""

    built = ReminderSettings.of(enabled, since, schedule, text, footer)
    if isinstance(built, ReminderProblem):
        place, sentence = _PROBLEMS[built.kind]
        return FieldProblem(place, sentence())
    return built


_PROBLEMS: Final[Mapping[ReminderProblemKind, tuple[FieldPath, Callable[[], str]]]] = {
    "empty_morning": (FieldPath(MORNING, END), messages.reminders_empty_morning),
    "empty_evening": (FieldPath(EVENING, END), messages.reminders_empty_evening),
    "overlap": (FieldPath(EVENING, START), messages.reminders_overlap),
    "empty_text": (FieldPath(TEXT), messages.reminders_empty_text),
    "unknown_field": (FieldPath(TEXT), messages.reminders_unknown_field),
    "enabled_without_since": (FieldPath(SINCE), messages.reminders_without_since),
}


def parse_time(value: object, place: FieldPath) -> time | FieldProblem:
    """Godzina ``GG:MM`` (także ``G:MM``) z pliku albo formularza; inna wartość to zdanie przy polu ``place``."""

    found = _TIME.fullmatch(value.strip()) if isinstance(value, str) else None
    if found is None:
        return FieldProblem(place, messages.reminders_time())
    return time(int(found["hour"]), int(found["minute"]))


def parse_range(start: object, end: object, key: FieldName) -> TimeRange | FieldProblem:
    """Pora z godzin początku i końca; godzina, która nie jest ``GG:MM``, to zdanie przy jej polu."""

    found_start = parse_time(start, FieldPath(key, START))
    if isinstance(found_start, FieldProblem):
        return found_start
    found_end = parse_time(end, FieldPath(key, END))
    if isinstance(found_end, FieldProblem):
        return found_end
    return TimeRange(found_start, found_end)


def _range(value: object, key: FieldName) -> TimeRange | FieldProblem:
    if not isinstance(value, dict) or set(value) != {START, END}:
        return _bad(FieldPath(key))
    return parse_range(value[START], value[END], key)


def _bad(place: FieldPath) -> FieldProblem:
    return FieldProblem(place, messages.bad_field(REMINDERS_FILE, place))


def _shown_time(moment: time) -> str:
    return f"{moment:%H:%M}"


def _range_document(found: TimeRange) -> dict[str, str]:
    return {START: _shown_time(found.start), END: _shown_time(found.end)}


def dump(settings: ReminderSettings) -> str:
    schedule = settings.schedule
    document = {
        "schema_version": _SCHEMA_VERSION,
        ENABLED: settings.enabled,
        SINCE: settings.since,
        MORNING: _range_document(schedule.morning),
        EVENING: _range_document(schedule.evening),
        FIRST: _shown_time(schedule.first),
        TEXT: settings.text,
        FOOTER: settings.footer,
    }
    return settings_yaml(document)


def _values(settings: ReminderSettings) -> dict[str, str | None]:
    schedule = settings.schedule
    return {
        ENABLED: "tak" if settings.enabled else "nie",
        SINCE: None if settings.since is None else settings.since.isoformat(),
        MORNING: _shown_range(schedule.morning),
        EVENING: _shown_range(schedule.evening),
        FIRST: _shown_time(schedule.first),
        TEXT: settings.text,
        FOOTER: settings.footer or None,
    }


def _shown_range(found: TimeRange) -> str:
    return f"{_shown_time(found.start)}{_RANGE}{_shown_time(found.end)}"


def diff(before: ReminderSettings, after: ReminderSettings) -> tuple[KeyChange, ...]:
    old, new = _values(before), _values(after)
    return tuple(KeyChange(f"{SECTION}.{key}", old[key], new[key]) for key in _KEYS if old[key] != new[key])


def restore(settings: ReminderSettings, changes: tuple[KeyChange, ...]) -> ReminderSettings:
    """``settings`` z każdym kluczem ``changes`` ustawionym na wartość sprzed zmiany; nieznany klucz i wartość, której
    nie da się przeczytać, zostają bez zmian, a całość sprawdza właściciel jak każdą zmianę."""

    restored = settings
    for change in changes:
        section, _, key = change.key.partition(".")
        if section == SECTION:
            restored = _restored(restored, key, change.before)
    return restored


def _restored(settings: ReminderSettings, key: str, value: str | None) -> ReminderSettings:
    schedule = settings.schedule
    match key:
        case "wlaczone":
            return replace(settings, enabled=value == "tak")
        case "wlaczone_od":
            try:
                return replace(settings, since=None if value is None else date.fromisoformat(value))
            except ValueError:
                return settings
        case "pora_poranna" | "pora_wieczorna" if value is not None:
            start, _, end = value.partition(_RANGE)
            found = parse_range(start, end, MORNING)
            if isinstance(found, FieldProblem):
                return settings
            changed = replace(schedule, morning=found) if key == MORNING else replace(schedule, evening=found)
            return replace(settings, schedule=changed)
        case "pierwsze_przypomnienie":
            first = parse_time(value, FieldPath(FIRST))
            return settings if isinstance(first, FieldProblem) else replace(settings, schedule=replace(schedule, first=first))
        case "tresc" if value is not None:
            return replace(settings, text=value)
        case "stopka":
            return replace(settings, footer=value or "")
        case _:
            return settings


def reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu: wartości wprost, a stopka, która ma dane taty, samym znacznikiem zmiany."""

    if change.key == f"{SECTION}.{FOOTER}":
        return f"{change.key}: zmieniono"
    return f"{change.key}: {_reported_value(change.before)} → {_reported_value(change.after)}"


def _reported_value(value: str | None) -> str:
    return "nie ustawiono" if value is None else value


REMINDERS: Final = SettingsFile(
    name=REMINDERS_FILE,
    parse=parse,
    dump=dump,
    diff=diff,
    restore=restore,
    reported=reported,
    default=DEFAULT_REMINDERS,
)
