"""Gramatyka tematu Raportu wykonawcy: dzień zleceń z tematu ``Raport dd.mm.rrrr`` albo z odpowiedzi na Przypomnienie o
raporcie, albo powód, dla którego temat zaczęty słowem ``raport`` go nie daje; a także temat Przypomnienia o raporcie, który
pisze Centrum (``reminder_subject``) i czyta z „Wysłanych” (``reminder_day``)."""

from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Final

from ._model import SUBJECT_WORD, SubjectFault

_REMINDER_REPLY: Final = re.compile(r"(?:\s*(?:re|odp)\s*:)+", re.IGNORECASE)
"""Przedrostki odpowiedzi przed tematem przypomnienia: ``Re:`` i z Outlooka po polsku ``Odp:``, raz albo więcej."""
_NUMBER: Final = re.compile(r"[0-9]+")
_WORD: Final = re.compile(r"(?P<before>[\W_]*?)(?P<word>[^\W\d_]+)")
_LETTER: Final = re.compile(r"[^\W\d_]")
_TAIL: Final = re.compile(r"(?:[\W_]*r)?[\W_]*\Z")
"""Koniec tematu po dacie, który temat wybacza: ``r`` albo ``r.`` i interpunkcja."""
_DATE: Final = re.compile(r"\s*(?P<date>[0-9]+(?:[\W_]+[0-9]+)*)")
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


def reads_as_report(subject: str) -> bool:
    """Czy mail z tematem ``subject`` może być Raportem wykonawcy: ``read`` daje dla niego dzień albo powód, a nie
    ``None``. Po nim port skrzynki wybiera maile, których treść pobiera."""

    return _read(subject) is not None


def read(subject: str, arrived: date) -> date | SubjectFault | None:
    """Dzień zleceń z tematu Raportu wykonawcy, powód, gdy temat Raportu wykonawcy nie daje dnia, albo ``None``, gdy
    mail nie jest Raportem wykonawcy: pierwsze słowo tematu różni się od ``raport`` o więcej niż jedną literę
    (``Montaże …``, ``Zdjęcia do raportu …``, ``Re:``, ``Fwd:``, z Outlooka po polsku ``Odp:`` i ``PD:``), poza
    odpowiedzią na Przypomnienie o raporcie.

    Odpowiedź na Przypomnienie o raporcie (ADR 0030) to ``Re:`` albo ``Odp:``, raz albo więcej, w dowolnej wielkości
    liter i z dowolnymi białymi znakami wokół, przed tematem, z którego ``reminder_day`` czyta dzień; daje ten dzień.
    ``Fwd:``, ``Fw:`` albo ``PD:`` gdziekolwiek przed tematem przypomnienia i temat przypomnienia bez przedrostka nie są
    Raportem wykonawcy.

    Temat Raportu wykonawcy (ADR 0041) zaczyna słowo ``raport`` w dowolnej wielkości liter, z jedną literówką albo bez
    (zamiana, przestawienie sąsiednich, brak albo nadmiar jednej litery: ``Rapotr``, ``Rapor``, ``Raportt``), a po nim
    data dzień, miesiąc, rok: dzień i miesiąc z zerem albo bez, rok z dwiema albo czterema cyframi (``26`` to 2026),
    między nimi dowolne znaki niebędące literą ani cyfrą, także sama spacja, a po dacie ``r``, ``r.`` i interpunkcja.
    Białe znaki wokół słowa i daty nic nie zmieniają. Inny temat zaczęty tym słowem dostaje pierwszy powód z kolejności
    ``SubjectFault``.

    Rok z tematu jest literówką Wykonawcy, gdy data leży ponad ``_BEFORE`` przed dniem przyjścia maila ``arrived`` albo
    ponad ``_AFTER`` po nim (``Raport 10.11.2016`` w mailu z 10.11.2026, ``Raport 29.12.2027`` z 2.01.2027): dniem
    zleceń jest wtedy ten sam dzień i miesiąc w roku, w którym wypada w tych granicach. Gdy w żadnym roku nie wypada w
    granicach (29 lutego bez roku przestępnego w nich albo, gdy granice obejmują 29 lutego, dzień tuż poza nimi), zostaje
    data z tematu.
    """

    found = _read(subject)
    return _near(found, arrived) if isinstance(found, date) else found


def _read(subject: str) -> date | SubjectFault | None:
    reply = _REMINDER_REPLY.match(subject)
    if reply is not None and (day := reminder_day(subject[reply.end() :])) is not None:
        return day
    text = subject.casefold()
    first = _WORD.match(text)
    if first is None or not _one_edit(first["word"], SUBJECT_WORD):
        return None
    rest = text[first.end() :]
    if _NUMBER.search(rest) is None:
        return SubjectFault.NO_DATE
    body = _TAIL.sub("", rest, count=1)
    if _LETTER.search(body):
        return SubjectFault.OTHER_WORDS
    shape = _DATE.fullmatch(body)
    if shape is None or first["before"].strip():
        return SubjectFault.OTHER_TEXT
    match _NUMBER.findall(shape["date"]):
        case [_, _]:
            return SubjectFault.NO_YEAR
        case [day, month, year] if len(day) <= 2 and len(month) <= 2:
            return _day(day, month, year)
        case _:
            return SubjectFault.DATE_FORM


def _one_edit(word: str, target: str) -> bool:
    """Czy ``word`` to ``target`` albo ``target`` z jedną zamianą, przestawieniem sąsiednich, brakiem albo nadmiarem
    litery."""

    if len(word) == len(target):
        different = [index for index, (left, right) in enumerate(zip(word, target, strict=True)) if left != right]
        match different:
            case [] | [_]:
                return True
            case [first, second]:
                return second == first + 1 and (word[first], word[second]) == (target[second], target[first])
            case _:
                return False
    shorter, longer = sorted((word, target), key=len)
    return len(longer) - len(shorter) == 1 and any(longer[:index] + longer[index + 1 :] == shorter for index in range(len(longer)))


def _day(day: str, month: str, year: str) -> date | SubjectFault:
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
