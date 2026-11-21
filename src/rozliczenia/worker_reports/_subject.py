"""Gramatyka tematu Raportu wykonawcy: dzień zleceń z tematu ``Raport dd.mm.rrrr``, z odpowiedzi na Przypomnienie o
raporcie albo z poprawki raportu w odpowiedzi, albo powód, dla którego temat zaczęty słowem ``raport`` go nie daje, z
dniem z tematu obok błędu, gdy da się go przeczytać; a także temat Przypomnienia o raporcie, który pisze Centrum
(``reminder_subject``) i czyta z „Wysłanych” (``reminder_day``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from typing import Final

from ._model import SUBJECT_WORD, SubjectFault

_REPLY: Final = re.compile(r"(?:\s*(?:re|odp)\s*:)+", re.IGNORECASE)
_NUMBER: Final = re.compile(r"[0-9]+")
_WORD: Final = re.compile(r"(?P<before>[\W_]*?)(?P<word>[^\W\d_]+)")
_LETTER: Final = re.compile(r"[^\W\d_]")
_TAIL: Final = re.compile(r"(?:[\W_]*r)?[\W_]*\Z")
_DATE: Final = re.compile(r"\s*(?P<date>[0-9]+(?:[\W_]+[0-9]+)*)")
_DAY_BESIDE: Final = re.compile(
    r"(?<![0-9])(?P<day>[0-9]{1,2})[\W_]+(?P<month>[0-9]{1,2})(?:[\W_]+(?P<year>[0-9]{4}|[0-9]{2}))?(?![0-9])"
)
"""Pierwsza data w temacie z błędem obok daty: dzień i miesiąc z rokiem albo bez, rozdzielone jak w temacie, który
gramatyka wybacza."""
_DAY_BESIDE_FAULTS: Final = frozenset({SubjectFault.OTHER_WORDS, SubjectFault.OTHER_TEXT, SubjectFault.NO_YEAR})
_BEFORE: Final = timedelta(days=302)
_AFTER: Final = timedelta(days=62)
"""Dzień z tematu Raportu wykonawcy leży od ``_BEFORE`` przed dniem przyjścia maila do ``_AFTER`` po nim; razem 365 dni,
więc każdy dzień z miesiącem wypada w nich najwyżej raz. ``_AFTER`` to dwa miesiące, żeby literówka w miesiącu
(``Raport 10.11`` za 10.10) nie stała się dniem sprzed roku, tylko jak dotąd czekała na swój dzień."""
_REMINDER: Final = "Przypomnienie: raport za dzień {day}"
_REMINDER_SHAPE: Final = re.compile(r"Przypomnienie: raport za dzień (\d{2})\.(\d{2})\.(\d{4})")


@dataclass(frozen=True)
class FaultySubject:
    """Temat Raportu wykonawcy, który nie daje dnia zleceń wprost (błąd tematu, ADR 0041): powód ``fault`` i dzień z
    tematu ``day``, gdy błąd stoi obok daty (``None``: temat bez daty albo z datą, która nie jest dniem)."""

    fault: SubjectFault
    day: date | None


@dataclass(frozen=True)
class _DayMonth:
    """Dzień i miesiąc z poprawki raportu w odpowiedzi bez roku: rok daje dopiero dzień przyjścia maila."""

    day: int
    month: int


def reminder_subject(day: date) -> str:
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
    """Czy mail z tematem ``subject`` może być Raportem wykonawcy: ``read`` daje dla niego dzień albo powód, a ``None``
    tylko dla poprawki raportu w odpowiedzi bez roku, której dzień nie leży w granicach od dnia przyjścia. Po nim port
    skrzynki wybiera maile, których treść pobiera."""

    return _read(subject) is not None


def read(subject: str, arrived: date) -> date | FaultySubject | None:
    """Dzień zleceń z tematu Raportu wykonawcy, błąd tematu, gdy temat Raportu wykonawcy nie daje dnia, albo ``None``, gdy
    mail nie jest Raportem wykonawcy: pierwsze słowo tematu różni się od ``raport`` o więcej niż jedną literę
    (``Montaże …``, ``Zdjęcia do raportu …``, ``Re:``, ``Fwd:``, z Outlooka po polsku ``Odp:`` i ``PD:``), poza
    odpowiedzią.

    Odpowiedź to ``Re:`` albo ``Odp:``, raz albo więcej, w dowolnej wielkości liter i z dowolnymi białymi znakami wokół,
    przed tematem, który daje dzień: tematem, z którego ``reminder_day`` czyta dzień (odpowiedź na Przypomnienie o
    raporcie, ADR 0030), albo tematem, który zaczyna się od tematu Raportu wykonawcy z dniem, a po nim ma dowolny dopisek
    (poprawka raportu w odpowiedzi, ADR 0041: ``Re: Raport 16.11.2026 - BŁĘDY PROSZĘ POPRAW``); temat Raportu
    wykonawcy kończy wtedy trzecia liczba po słowie, a gdy do niej nie daje dnia, druga liczba: temat bez roku
    (``Re: Raport 16.11 - popraw``) daje dzień i miesiąc w roku, w którym leżą w granicach ``_BEFORE`` i ``_AFTER`` od
    dnia przyjścia (decyzja Maksa 17.11.2026), a bez takiego roku (``Re: Raport 31.11``) nie jest Raportem wykonawcy.
    Inna odpowiedź (``Re: Zmiana w raportach …``, ``Re: Raport popraw``, ``Re: Raport za 16.11.2026``), ``Fwd:``,
    ``Fw:`` albo ``PD:`` gdziekolwiek przed tematem i temat przypomnienia bez przedrostka nie są Raportem wykonawcy.

    Temat Raportu wykonawcy (ADR 0041) zaczyna słowo ``raport`` w dowolnej wielkości liter, z jedną literówką albo bez
    (zamiana, przestawienie sąsiednich, brak albo nadmiar jednej litery: ``Rapotr``, ``Rapor``, ``Raportt``), a po nim
    data dzień, miesiąc, rok: dzień i miesiąc z zerem albo bez, rok z dwiema albo czterema cyframi (``26`` to 2026),
    między nimi dowolne znaki niebędące literą ani cyfrą, także sama spacja, a po dacie ``r``, ``r.`` i interpunkcja.
    Białe znaki wokół słowa i daty nic nie zmieniają. Inny temat zaczęty tym słowem dostaje pierwszy powód z kolejności
    ``SubjectFault`` i dzień z tematu, gdy błąd stoi obok daty (inne słowa, znak przed datą, data bez roku): pierwszy
    dzień i miesiąc po słowie, z rokiem z dwiema albo czterema cyframi albo bez roku, rozdzielone dowolnymi znakami
    niebędącymi literą ani cyfrą (``Raport 13.11.2026 Kowalski``, ``Raport za 04.11.2026 2 montaże``, ``raport 02.11``).
    Dzień bez roku leży w tych samych granicach co data z rokiem pomylonym niżej, a bez dnia w nich nie ma dnia z tematu.

    Rok z tematu jest literówką Wykonawcy, gdy data leży ponad ``_BEFORE`` przed dniem przyjścia maila ``arrived`` albo
    ponad ``_AFTER`` po nim (``Raport 10.11.2016`` w mailu z 10.11.2026, ``Raport 29.12.2027`` z 2.01.2027): dniem
    zleceń jest wtedy ten sam dzień i miesiąc w roku, w którym wypada w tych granicach. Gdy w żadnym roku nie wypada w
    granicach (29 lutego bez roku przestępnego w nich albo, gdy granice obejmują 29 lutego, dzień tuż poza nimi), zostaje
    data z tematu.
    """

    found = _read(subject)
    match found:
        case date():
            return _near(found, arrived)
        case _DayMonth(day=day, month=month):
            return _without_year(day, month, arrived)
        case (SubjectFault() as fault, str() as rest):
            return FaultySubject(fault, _day_beside(rest, arrived) if fault in _DAY_BESIDE_FAULTS else None)
        case None:
            return None


def _read(subject: str) -> date | _DayMonth | tuple[SubjectFault, str] | None:
    """Dzień z tematu przed poprawką roku, dzień i miesiąc poprawki w odpowiedzi bez roku, powód z tekstem po słowie
    raportu albo ``None``, gdy to nie raport."""

    reply = _REPLY.match(subject)
    if reply is not None:
        return _replied(subject[reply.end() :])
    return _report(subject)


def _replied(subject: str) -> date | _DayMonth | None:
    """Dzień z tematu po przedrostkach odpowiedzi: z tematu przypomnienia albo z tematu Raportu wykonawcy do trzeciej
    liczby, gdy daje dzień, a nie błąd, a inaczej dzień i miesiąc z tematu do drugiej liczby, gdy to temat bez roku."""

    if (day := reminder_day(subject)) is not None:
        return day
    ends = [found.end() for found in _NUMBER.finditer(subject)][:3]
    if len(ends) == 3 and isinstance(found := _report(subject[: ends[2]]), date):
        return found
    if len(ends) < 2:
        return None
    match _report(subject[: ends[1]]):
        case (SubjectFault.NO_YEAR, str() as rest):
            day, month = _NUMBER.findall(rest)
            return _DayMonth(int(day), int(month))
        case _:
            return None


def _report(subject: str) -> date | tuple[SubjectFault, str] | None:
    text = subject.casefold()
    first = _WORD.match(text)
    if first is None or not _one_edit(first["word"], SUBJECT_WORD):
        return None
    rest = text[first.end() :]
    if _NUMBER.search(rest) is None:
        return SubjectFault.NO_DATE, rest
    body = _TAIL.sub("", rest, count=1)
    if _LETTER.search(body):
        return SubjectFault.OTHER_WORDS, rest
    shape = _DATE.fullmatch(body)
    if shape is None or first["before"].strip():
        return SubjectFault.OTHER_TEXT, rest
    match _NUMBER.findall(shape["date"]):
        case [_, _]:
            return SubjectFault.NO_YEAR, rest
        case [day, month, year] if len(day) <= 2 and len(month) <= 2:
            found = _day(day, month, year)
            return found if isinstance(found, date) else (found, rest)
        case _:
            return SubjectFault.DATE_FORM, rest


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


def _day_beside(rest: str, arrived: date) -> date | None:
    """Pierwsza data w tekście tematu po słowie raportu, z rokiem poprawionym jak w ``read``, a bez roku w granicach
    ``_BEFORE`` i ``_AFTER`` od dnia przyjścia; ``None``, gdy daty nie ma albo nie jest dniem."""

    found = _DAY_BESIDE.search(rest)
    if found is None:
        return None
    if found["year"] is not None:
        day = _day(found["day"], found["month"], found["year"])
        return _near(day, arrived) if isinstance(day, date) else None
    return _without_year(int(found["day"]), int(found["month"]), arrived)


def _without_year(day: int, month: int, arrived: date) -> date | None:
    for year in (arrived.year - 1, arrived.year, arrived.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if arrived - _BEFORE <= candidate <= arrived + _AFTER:
            return candidate
    return None


def _near(found: date, arrived: date) -> date:
    for year in (found.year, arrived.year - 1, arrived.year, arrived.year + 1):
        try:
            candidate = found.replace(year=year)
        except ValueError:
            continue
        if arrived - _BEFORE <= candidate <= arrived + _AFTER:
            return candidate
    return found
