"""Wpisy raportu z treści Raportu wykonawcy: jedna linia ``<numer> tak|nie <opis>``."""

from __future__ import annotations

import re
from typing import Final

from . import OrderNumber, ReportEntry, Verdict

_ENTRY: Final = re.compile(r"([0-9]+) (tak|nie)(?: (\S.*))?")


def entries(text: str) -> tuple[ReportEntry, ...]:
    """Wpis z treści, która poza białymi znakami na brzegach jest jedną linią ``<numer> tak|nie <opis>``; opis może
    być pusty. Inna treść nie daje Wpisu."""

    found = _ENTRY.fullmatch(text.strip())
    if found is None:
        return ()
    number, verdict, activities = found.groups()
    return (ReportEntry(OrderNumber(number), Verdict(verdict), None, activities or ""),)
