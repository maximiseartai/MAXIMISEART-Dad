"""Postać kanoniczna Raportu wykonawcy: mail, z którego rdzeń czyta z powrotem ten sam odczyt (``MailRead``).

Odtworzenie Uruchomienia z Logów (#1233) ma z maila tylko odczyt, bez adresu, tematu i treści, więc buduje z niego mail
w postaci kanonicznej: temat ``Raport dd.mm.rrrr``, jedna linia ``<numer> <znak> <czynności>`` na Wpis raportu, a pod
nimi pusta linia i ``_CLOSING``.
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
        case ReadUnreadable(fault=fault):
            return ReportMail(read.mail, sender, _unreadable(fault), "", read.arrived)
        case _:
            assert_never(read)


def _subject(day: date) -> str:
    return f"{_WORD} {day:%d.%m.%Y}"


def _unreadable(fault: SubjectFault) -> str:
    """Temat ze słowem Raportu wykonawcy, który nie daje dnia z powodu ``fault``."""

    match fault:
        case SubjectFault.NO_DATE:
            return _WORD
        case SubjectFault.OTHER_TEXT:
            return f"{_WORD} z 08.11.2026"
        case SubjectFault.NO_YEAR:
            return f"{_WORD} 08.11"
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
