"""Postać kanoniczna Raportu wykonawcy: mail, z którego rdzeń czyta z powrotem ten sam odczyt (``MailRead``), dla
``WindowMails.canonical``.

Odtworzenie Uruchomienia z Logów ma z maila tylko odczyt, bez adresu, tematu i treści, więc buduje z niego mail
w postaci kanonicznej: temat ``Raport dd.mm.rrrr``, jedna linia ``<numer> <znak> <czynności>`` na Wpis raportu, a pod
nimi pusta linia i ``_CLOSING``. Raport z błędem tematu ma temat z tym samym powodem i tym samym dniem z tematu albo bez
niego i te same linie Wpisów. Rdzeń czyta z tego maila ten sam odczyt, poza tematem
dla taty, którego Logi nie mają, dla każdego powodu tematu poza ``SubjectFault.SEPARATOR`` (``_unreadable``).
"""

from __future__ import annotations

from datetime import date
from typing import assert_never

from ._model import (
    SUBJECT_WORD,
    MailRead,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    ReportEntry,
    ReportMail,
    SenderAddress,
    SubjectFault,
)

_WORD = SUBJECT_WORD.capitalize()
_CLOSING = "\n\nPozdrawiam"
"""Koniec treści pod Wpisami: tekst pod przerwą, którego rdzeń nie czyta, a przez który stopka w środku ostatniej linii
(``_entries._last_end``) nie biegnie do końca treści. Bez niego czynności ostatniego Wpisu z ``wysłano z …`` w środku,
które w oryginale stały przed dalszym tekstem albo przed Wpisem, który się nie liczy, rdzeń uciąłby jak stopkę."""


def as_mail(read: MailRead, sender: SenderAddress) -> ReportMail:
    """Mail od ``sender``, z którego ``enter_reports`` czyta odczyt ``read``: ten sam mail, chwilę przyjścia, dzień albo
    powód tematu i Wpisy raportu. ``sender`` ma być adresem Wykonawcy ``read.worker`` w adresach wejścia rdzenia, a przy
    ``ReadStranger`` adresem spoza nich."""

    match read:
        case ReadReport(day=day, entries=entries):
            return ReportMail(read.mail, sender, _subject(day), "\n".join(map(_line, entries)) + _CLOSING, read.arrived)
        case ReadStranger(day=day):
            return ReportMail(read.mail, sender, _subject(day), "", read.arrived)
        case ReadUnreadable(fault=fault, entries=entries, day=day):
            return ReportMail(read.mail, sender, _unreadable(fault, day), "\n".join(map(_line, entries)) + _CLOSING, read.arrived)
        case _:
            assert_never(read)


def _subject(day: date) -> str:
    return f"{_WORD} {day:%d.%m.%Y}"


def _unreadable(fault: SubjectFault, day: date | None) -> str:
    """Temat zaczęty słowem Raportu wykonawcy z powodem ``fault``, z którego ``_subject.read`` czyta dzień ``day`` obok
    błędu (dzień bez roku leży w granicach od dnia przyjścia, więc ``dd.mm`` daje ten sam dzień) albo żadnego dnia.
    ``SEPARATOR`` jest tylko w Logach sprzed tolerancji tematu (ADR 0041), a jego temat (``Raport 08-11-2026``) rdzeń
    czyta dziś jako dzień, tak jak prawdziwy temat z takim separatorem."""

    match fault:
        case SubjectFault.NO_DATE:
            return _WORD
        case SubjectFault.OTHER_WORDS:
            return f"{_WORD} z 8" if day is None else f"{_WORD} {day:%d.%m.%Y} z"
        case SubjectFault.OTHER_TEXT:
            return f"{_WORD}: 8" if day is None else f"{_WORD}: {day:%d.%m.%Y}"
        case SubjectFault.NO_YEAR:
            return f"{_WORD} 31.02" if day is None else f"{_WORD} {day:%d.%m}"
        case SubjectFault.DATE_FORM:
            return f"{_WORD} 2026.11.08"
        case SubjectFault.SEPARATOR:
            return f"{_WORD} 08-11-2026"
        case SubjectFault.YEAR_DIGITS:
            return f"{_WORD} 08.11.202"
        case SubjectFault.NOT_A_DAY:
            return f"{_WORD} 31.02.2026"
        case _:
            assert_never(fault)


def _line(entry: ReportEntry) -> str:
    return " ".join(part for part in (entry.number, entry.mark, entry.activities) if part)
