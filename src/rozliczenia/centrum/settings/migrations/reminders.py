"""Przeniesienie dnia wdrożenia przypomnień (``przypomnienia-od.txt``) i stopki taty (``stopka-przypomnien.txt``) do
Ustawień Centrum (``przypomnienia.yaml``): zmiana z Wydania ``2026-11-przypomnienia`` (ADR 0032, zmienia ADR 0030).

Po Aktualizacji bez zmian Wykonawcy dostają te same przypomnienia co dotąd: dzień wdrożenia z pliku Maksa włącza
przypomnienia od tego dnia, stopka przechodzi tekstem bez zmian, a pory, godzina pierwszego przypomnienia i treść mają
wartości domyślne, czyli dawne stałe. Pliki czyta ta sama reguła co dotąd: tekst w UTF-8 (z BOM z Notatnika) albo
UTF-16 (z PowerShell 5.1), dzień jako jedyna linia ``rrrr-mm-dd``; inna treść albo brak pliku dnia wdrożenia to
przypomnienia wyłączone, a pusta albo nieczytelna stopka to przypomnienia bez stopki, tak jak przed Wydaniem.
Plik, którego system nie daje teraz czytać (np. trzyma go antywirus), to ``Later``: treść jest nieznana, a nie zła.

Bez żadnego starego pliku edycja daje wartości domyślne, czyli to samo co brak pliku, więc właściciel nie pisze pliku
ani wiersza Historii. Stare pliki zostają w ``config``; ten moduł jest ich jedynym czytelnikiem.
"""

from __future__ import annotations

import codecs
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Final

from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Proposal, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings.reminders import REMINDERS, REMINDERS_FILE
from rozliczenia.file_state import file_state
from rozliczenia.worker_reports import ReminderSettings

OLD_ROLLOUT_FILE: Final = "przypomnienia-od.txt"
OLD_FOOTER_FILE: Final = "stopka-przypomnien.txt"


class _Unreadable(Exception):
    """Starego pliku nie dało się teraz przeczytać, choć jest."""


def propose(inputs: ReleaseInputs[ReminderSettings]) -> Proposal[ReminderSettings]:
    config = inputs.config
    if file_state(config / REMINDERS_FILE) != "missing":
        return Nothing()
    try:
        rollout = _rollout(_text(config / OLD_ROLLOUT_FILE))
        footer = _text(config / OLD_FOOTER_FILE)
    except _Unreadable:
        return Later("stary plik przypomnień jest, ale system nie daje go teraz czytać")
    kept = footer if footer is not None and footer.strip() else ""
    return Edit(
        lambda current: replace(current, enabled=rollout is not None, since=rollout, footer=kept), undoable=False
    )


def _text(path: Path) -> str | None:
    """Tekst starego pliku (BOM UTF-8 z Notatnika, UTF-16 z PowerShell 5.1); ``None`` bez pliku albo przy treści, która
    nie jest tekstem. ``_Unreadable``, gdy plik jest, a system go nie oddaje."""

    try:
        content = path.read_bytes()
    except OSError as error:
        if file_state(path) == "missing":
            return None
        raise _Unreadable from error
    encoding = "utf-16" if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    try:
        return content.decode(encoding)
    except UnicodeError:
        return None


def _rollout(text: str | None) -> date | None:
    """Dzień wdrożenia z jedynej linii ``rrrr-mm-dd``; ``None`` bez pliku albo przy innej treści."""

    lines = [] if text is None else text.split()
    try:
        return date.fromisoformat(lines[0]) if len(lines) == 1 and len(lines[0]) == len("rrrr-mm-dd") else None
    except ValueError:
        return None


CHANGE: Final = ReleaseChange(id="2026-11-przypomnienia", file=REMINDERS, propose=propose)
"""Przypomnienia ze starych plików, bez „Cofnij”: cofnięcie wyłączyłoby przypomnienia i zgubiło stopkę (D8)."""
