"""Gramatyka tematu Raportu wykonawcy: dzień zleceń z tematu ``Raport dd.mm.rrrr`` albo powód, dla którego temat ze
słowem ``raport`` go nie daje."""

from __future__ import annotations

from datetime import date
import re
from typing import Final

from ._model import SUBJECT_WORD, SubjectFault

_REPLY: Final = re.compile(r"\s*(?:re|fwd?|odp|pd)\s*:")
_NUMBER: Final = re.compile(r"[0-9]+")
_SHAPE: Final = re.compile(rf"\s*{re.escape(SUBJECT_WORD)}\s*(?P<date>[0-9]+(?:(?:[^\w]|_)+[0-9]+)*)(?:\s*r\.?)?\s*")
_SEPARATORS: Final = frozenset("._/")


def read(subject: str) -> date | SubjectFault | None:
    """Dzień zleceń z tematu Raportu wykonawcy, powód, gdy temat ze słowem ``raport`` nie daje dnia, albo ``None``, gdy
    mail nie jest Raportem wykonawcy: temat bez tego słowa albo odpowiedź i przekazanie dalej (``Re:``, ``Fwd:``,
    ``Fw:``, z Outlooka po polsku ``Odp:`` i ``PD:``).

    Temat to słowo ``raport`` w dowolnej wielkości liter i data dzień, miesiąc, rok: dzień i miesiąc z zerem albo bez,
    rok z dwiema albo czterema cyframi (``26`` to 2026), z dopiskiem ``r.`` albo bez, między nimi ``.``, ``_`` albo ``/``, a wokół słowa, daty i
    separatorów dowolne białe znaki. Inny temat ze słowem dostaje pierwszy powód z kolejności ``SubjectFault``.
    """

    text = subject.casefold()
    if SUBJECT_WORD not in text or _REPLY.match(text):
        return None
    if _NUMBER.search(text) is None:
        return SubjectFault.NO_DATE
    shape = _SHAPE.fullmatch(text)
    if shape is None:
        return SubjectFault.OTHER_TEXT
    match _NUMBER.findall(shape["date"]):
        case [_, _]:
            return SubjectFault.NO_YEAR
        case [day, month, year] if len(day) <= 2 and len(month) <= 2:
            separators = _NUMBER.split(shape["date"])[1:-1]
            return _day(day, month, year, [separator.strip() for separator in separators])
        case _:
            return SubjectFault.DATE_FORM


def _day(day: str, month: str, year: str, separators: list[str]) -> date | SubjectFault:
    if any(separator not in _SEPARATORS for separator in separators):
        return SubjectFault.SEPARATOR
    if len(year) not in (2, 4):
        return SubjectFault.YEAR_DIGITS
    try:
        return date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
    except ValueError:
        return SubjectFault.NOT_A_DAY
