"""Gramatyka tematu Raportu wykonawcy: dzień zleceń z tematu ``Raport dd.mm.rrrr``."""

from __future__ import annotations

from datetime import date
import re
from typing import Final

from ._model import SUBJECT_WORD

_SUBJECT: Final = re.compile(rf"{re.escape(SUBJECT_WORD.capitalize())} ([0-9]{{2}})\.([0-9]{{2}})\.([0-9]{{4}})")


def day_of(subject: str) -> date | None:
    """Dzień zleceń z tematu w dokładnej postaci ``Raport dd.mm.rrrr``; ``None``, gdy temat ma inną postać albo data
    nie jest dniem."""

    found = _SUBJECT.fullmatch(subject)
    if found is None:
        return None
    day, month, year = (int(part) for part in found.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
