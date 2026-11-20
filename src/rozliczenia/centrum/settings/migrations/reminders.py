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
    pass


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
    lines = [] if text is None else text.split()
    try:
        return date.fromisoformat(lines[0]) if len(lines) == 1 and len(lines[0]) == len("rrrr-mm-dd") else None
    except ValueError:
        return None


CHANGE: Final = ReleaseChange(id="2026-11-przypomnienia", file=REMINDERS, propose=propose)
