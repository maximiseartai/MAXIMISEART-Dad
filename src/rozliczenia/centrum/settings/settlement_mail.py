"""Temat i treść Maila z rozliczeniem w pliku ``wysylka-rozliczen.yaml`` (schemat 1), Ustawienie Centrum taty (ADR 0040,
zmienia ADR 0032).

Kształt pliku sprawdza ``parse`` (mapa, schemat, znane pola, tekst), a reguły tematu i treści
``SettlementMailSettings.of``, ta sama budowa co w Wysyłce rozliczeń. Brak pliku i pole, którego w pliku nie ma, to
wartości domyślne (``DEFAULT_SETTLEMENT_MAIL``). Stopki ten plik nie ma: Mail z rozliczeniem kończy się stopką
Przypomnień o raporcie, jednym podpisem taty.

Klucz Historii to ``wysylka_rozliczen.<pole>``. Zgłoszenie nie podaje ich wartości, tylko że się zmieniły, bo temat i
treść tata pisze do swoich Wykonawców (ADR 0040).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Final

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldName, FieldPath, FieldProblem, KeyChange, SettingsFile, settings_yaml
from rozliczenia.settlement_mailing import DEFAULT_SETTLEMENT_MAIL, MailProblem, MailProblemKind, SettlementMailSettings

SETTLEMENT_MAIL_FILE: Final = "wysylka-rozliczen.yaml"
"""Plik tematu i treści Maila z rozliczeniem w ``config``; czyta go i pisze tylko ``rozliczenia.centrum.settings``."""

SECTION: Final = "wysylka_rozliczen"
_SCHEMA_VERSION: Final = 1
SUBJECT: Final[FieldName] = "temat"
TEXT: Final[FieldName] = "tresc"
_KEYS: Final = (SUBJECT, TEXT)


def parse(data: bytes | None) -> SettlementMailSettings | FieldProblem:
    """Temat i treść z bajtów pliku; ``None`` (brak pliku) to wartości domyślne, zła treść to pierwszy problem."""

    if data is None:
        return DEFAULT_SETTLEMENT_MAIL
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(SETTLEMENT_MAIL_FILE))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(SETTLEMENT_MAIL_FILE))
    if not isinstance(document, dict):
        return FieldProblem(None, messages.damaged(SETTLEMENT_MAIL_FILE))
    if document.get("schema_version") != _SCHEMA_VERSION:
        return FieldProblem(None, messages.other_schema(SETTLEMENT_MAIL_FILE))
    unknown = next((place for place, key in enumerate(document, 1) if key != "schema_version" and key not in _KEYS), None)
    if unknown is not None:
        return FieldProblem(None, messages.unknown_key(SETTLEMENT_MAIL_FILE, unknown))
    subject = document.get(SUBJECT, DEFAULT_SETTLEMENT_MAIL.subject)
    if not isinstance(subject, str):
        return _bad(FieldPath(SUBJECT))
    text = document.get(TEXT, DEFAULT_SETTLEMENT_MAIL.text)
    if not isinstance(text, str):
        return _bad(FieldPath(TEXT))
    return settings_of(subject, text)


def settings_of(subject: str, text: str) -> SettlementMailSettings | FieldProblem:
    """``SettlementMailSettings.of`` z problemem jako polem pliku i zdaniem dla taty: ta sama reguła dla pliku i
    formularza."""

    built = SettlementMailSettings.of(subject, text)
    if isinstance(built, MailProblem):
        place, sentence = _PROBLEMS[built.kind]
        return FieldProblem(FieldPath(place), sentence())
    return built


_PROBLEMS: Final[Mapping[MailProblemKind, tuple[FieldName, Callable[[], str]]]] = {
    "empty_subject": (SUBJECT, messages.settlement_mail_empty_subject),
    "subject_lines": (SUBJECT, messages.settlement_mail_subject_lines),
    "subject_report": (SUBJECT, messages.settlement_mail_report_subject),
    "subject_unknown_field": (SUBJECT, messages.settlement_mail_unknown_field),
    "empty_text": (TEXT, messages.settlement_mail_empty_text),
    "text_unknown_field": (TEXT, messages.settlement_mail_unknown_field),
}


def _bad(place: FieldPath) -> FieldProblem:
    return FieldProblem(place, messages.bad_field(SETTLEMENT_MAIL_FILE, place, messages.SAVE_AGAIN))


def dump(settings: SettlementMailSettings) -> bytes:
    return settings_yaml({"schema_version": _SCHEMA_VERSION, SUBJECT: settings.subject, TEXT: settings.text})


def _values(settings: SettlementMailSettings) -> dict[str, str]:
    return {SUBJECT: settings.subject, TEXT: settings.text}


def diff(before: SettlementMailSettings, after: SettlementMailSettings) -> tuple[KeyChange, ...]:
    old, new = _values(before), _values(after)
    return tuple(KeyChange(f"{SECTION}.{key}", old[key], new[key]) for key in _KEYS if old[key] != new[key])


def restore(settings: SettlementMailSettings, changes: tuple[KeyChange, ...]) -> SettlementMailSettings:
    """``settings`` z każdym kluczem ``changes`` ustawionym na wartość sprzed zmiany; nieznany klucz zostaje bez zmian,
    a całość sprawdza właściciel jak każdą zmianę."""

    restored = settings
    for change in changes:
        section, _, key = change.key.partition(".")
        if section != SECTION or change.before is None:
            continue
        if key == SUBJECT:
            restored = replace(restored, subject=change.before)
        elif key == TEXT:
            restored = replace(restored, text=change.before)
    return restored


def reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu samym znacznikiem zmiany: temat i treść tata pisze do Wykonawców (ADR 0040)."""

    return f"{change.key}: zmieniono"


SETTLEMENT_MAIL: Final = SettingsFile(
    name=SETTLEMENT_MAIL_FILE,
    parse=parse,
    dump=dump,
    diff=diff,
    restore=restore,
    reported=reported,
    default=DEFAULT_SETTLEMENT_MAIL,
)
