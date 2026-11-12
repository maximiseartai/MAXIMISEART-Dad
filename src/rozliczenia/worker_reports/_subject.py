"""Gramatyka tematu Raportu wykonawcy: dzień zleceń z tematu ``Raport dd.mm.rrrr`` albo z odpowiedzi na Przypomnienie o
raporcie, albo powód, dla którego temat ze słowem ``raport`` go nie daje; a także temat Przypomnienia o raporcie, który
pisze Centrum (``reminder_subject``) i czyta z „Wysłanych” (``reminder_day``)."""

from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Final

from ._model import SUBJECT_WORD, SubjectFault

_REPLY: Final = re.compile(r"\s*(?:re|fwd?|odp|pd)\s*:")
_REMINDER_REPLY: Final = re.compile(r"(?:\s*(?:re|odp)\s*:)+", re.IGNORECASE)
"""Przedrostki odpowiedzi przed tematem przypomnienia: ``Re:`` i z Outlooka po polsku ``Odp:``, raz albo więcej."""
_NUMBER: Final = re.compile(r"[0-9]+")
_SHAPE: Final = re.compile(rf"\s*{re.escape(SUBJECT_WORD)}\s*(?P<date>[0-9]+(?:(?:[^\w]|_)+[0-9]+)*)(?:\s*r\.?)?\s*")
_SEPARATORS: Final = frozenset("._/")
_BEFORE: Final = timedelta(days=302)
_AFTER: Final = timedelta(days=62)
"""Dzień z tematu Raportu wykonawcy leży od ``_BEFORE`` przed dniem przyjścia maila do ``_AFTER`` po nim; razem 365 dni,
więc każdy dzień z miesiącem wypada w nich najwyżej raz. ``_AFTER`` to dwa miesiące, żeby literówka w miesiącu
(``Raport 10.11`` za 10.10) nie stała się dniem sprzed roku, tylko jak dotąd czekała na swój dzień."""
_REMINDER: Final = "Przypomnienie: raport za dzień {day}"
_REMINDER_SHAPE: Final = re.compile(r"Przypomnienie: raport za dzień (\d{2})\.(\d{2})\.(\d{4})")


def reminder_subject(day: date) -> str:
    """Temat Przypomnienia o raporcie za dzień ``day``: ``Przypomnienie: raport za dzień dd.mm.rrrr``."""

    return _REMINDER.format(day=f"{day:%d.%m.%Y}")


def reminder_day(subject: str) -> date | None:
    """Dzień z tematu, który napisał ``reminder_subject``; ``None`` dla każdej innej postaci (także innej wielkości
    liter, daty bez zer i tematu z dopiskiem), bo temat pisze tylko Centrum."""

    found = _REMINDER_SHAPE.fullmatch(subject.strip())
    if found is None:
        return None
    try:
        return date(int(found[3]), int(found[2]), int(found[1]))
    except ValueError:
        return None


def read(subject: str, arrived: date) -> date | SubjectFault | None:
    """Dzień zleceń z tematu Raportu wykonawcy, powód, gdy temat ze słowem ``raport`` nie daje dnia, albo ``None``, gdy
    mail nie jest Raportem wykonawcy: temat bez tego słowa albo odpowiedź i przekazanie dalej (``Re:``, ``Fwd:``,
    ``Fw:``, z Outlooka po polsku ``Odp:`` i ``PD:``) poza odpowiedzią na Przypomnienie o raporcie.

    Odpowiedź na Przypomnienie o raporcie (ADR 0030) to ``Re:`` albo ``Odp:``, raz albo więcej, w dowolnej wielkości
    liter i z dowolnymi białymi znakami wokół, przed tematem, z którego ``reminder_day`` czyta dzień; daje ten dzień.
    ``Fwd:``, ``Fw:`` albo ``PD:`` gdziekolwiek przed tematem przypomnienia i temat przypomnienia bez przedrostka to
    granica: pierwsze nie jest Raportem wykonawcy, drugie daje ``SubjectFault.OTHER_TEXT``.

    Temat to słowo ``raport`` w dowolnej wielkości liter i data dzień, miesiąc, rok: dzień i miesiąc z zerem albo bez,
    rok z dwiema albo czterema cyframi (``26`` to 2026), z dopiskiem ``r.`` albo bez, między nimi ``.``, ``_`` albo ``/``, a wokół słowa, daty i
    separatorów dowolne białe znaki. Inny temat ze słowem dostaje pierwszy powód z kolejności ``SubjectFault``.

    Rok z tematu jest literówką Wykonawcy, gdy data leży ponad ``_BEFORE`` przed dniem przyjścia maila ``arrived`` albo
    ponad ``_AFTER`` po nim (``Raport 10.11.2016`` w mailu z 10.11.2026, ``Raport 29.12.2027`` z 2.01.2027): dniem
    zleceń jest wtedy ten sam dzień i miesiąc w roku, w którym wypada w tych granicach. Gdy w żadnym nie wypada (29
    lutego), zostaje data z tematu.
    """

    reply = _REMINDER_REPLY.match(subject)
    if reply is not None and (day := reminder_day(subject[reply.end() :])) is not None:
        return day
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
            found = _day(day, month, year, [separator.strip() for separator in separators])
            return _near(found, arrived) if isinstance(found, date) else found
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


def _near(found: date, arrived: date) -> date:
    for year in (found.year, arrived.year - 1, arrived.year, arrived.year + 1):
        try:
            candidate = found.replace(year=year)
        except ValueError:
            continue
        if arrived - _BEFORE <= candidate <= arrived + _AFTER:
            return candidate
    return found
