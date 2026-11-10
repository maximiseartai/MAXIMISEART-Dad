"""Zdanie dla taty o problemie Wpisania raportów, do widoku Raporty.

Zdanie nie ma adresu nadawcy: adres spoza listy widok Raporty pokazuje osobno (``SenderAddress.shown``, ADR 0028).
"""

from __future__ import annotations

from datetime import date
from typing import assert_never

from . import (
    ConflictingVerdicts,
    ForeignOrder,
    ManualDifference,
    MissingVerdict,
    OtherDay,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    SubjectFault,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    VerdictFault,
)

__all__ = ["reason"]


def reason(problem: ReportProblem) -> str:
    match problem:
        case UnreadableSubject(worker=worker, arrived=arrived, fault=fault):
            return (
                f"Mail od {worker} z {arrived:%d.%m.%Y, %H:%M} ma w temacie słowo „Raport”, ale {_subject(fault)}, "
                "więc Centrum go nie wpisało."
            )
        case UnknownSender(day=day):
            return (
                f"Raport wykonawcy z {_day(day)} przyszedł z adresu spoza listy adresów Wykonawców, więc Centrum go nie "
                "wpisało. Powiedz Maksowi, czyj to adres."
            )
        case MissingVerdict(worker=worker, day=day, number=number, fault=fault):
            return f"Wpis zlecenia {number} od {worker} z {_day(day)} {_verdict(fault)}, więc Centrum go nie wpisało."
        case ConflictingVerdicts(worker=worker, day=day, number=number, arrived=arrived, entries=entries):
            said = " i ".join(f"„{_said(entry)}”" for entry in entries)
            return (
                f"Raport wykonawcy od {worker} z {_day(day)}, który przyszedł {arrived:%d.%m.%Y o %H:%M}, ma dla zlecenia "
                f"{number} różne Wpisy: {said}, więc Centrum nic do tego zlecenia nie wpisało. Sprawdź z Wykonawcą, który "
                "Wpis jest dobry, i wpisz go ręcznie albo poczekaj na poprawiony mail."
            )
        case UnknownNumber(worker=worker, day=day, number=number):
            return f"Numer {number} nie jest zleceniem {worker} z {_day(day)}."
        case ForeignOrder(worker=worker, day=day, number=number, owner=owner):
            return (
                f"Zlecenie {number} z {_day(day)} jest zleceniem {owner}, a Wpis przysłał {worker}, więc Centrum go "
                "nie wpisało."
            )
        case OtherDay(worker=worker, day=day, number=number, order_days=order_days):
            days = ", ".join(_day(order_day) for order_day in order_days)
            return (
                f"Zlecenie {number} od {worker} jest z {days}, a temat Raportu wykonawcy ma {_day(day)}, więc Centrum "
                "go nie wpisało."
            )
        case RepeatedOrder(worker=worker, day=day, number=number):
            return (
                f"Zlecenie {number} jest dwa razy w dniu {_day(day)} u {worker}, więc Centrum niczego do niego nie "
                "wpisało."
            )
        case ManualDifference(key=key, column=column, manual=manual, reported=reported):
            return (
                f"Zlecenie {key.number} od {key.worker} z {_day(key.day)} ma w {column.value} ręczną wartość "
                f"„{manual}”, a Wpis raportu mówi „{reported}”. Ręczna wartość zostaje."
            )
        case _:
            assert_never(problem)


def _day(day: date) -> str:
    return f"{day:%d.%m.%Y}"


def _subject(fault: SubjectFault) -> str:
    match fault:
        case SubjectFault.NO_DATE:
            return "nie ma w nim daty dnia zleceń"
        case SubjectFault.OTHER_TEXT:
            return "poza tym słowem i datą temat ma inny tekst"
        case SubjectFault.NO_YEAR:
            return "data nie ma roku"
        case SubjectFault.DATE_FORM:
            return "data nie ma postaci dzień, miesiąc, rok"
        case SubjectFault.SEPARATOR:
            return "dzień, miesiąc i rok nie są rozdzielone kropką, podkreśleniem ani ukośnikiem"
        case SubjectFault.YEAR_DIGITS:
            return "rok w dacie nie ma dwóch ani czterech cyfr"
        case SubjectFault.NOT_A_DAY:
            return "data nie jest prawdziwym dniem"


def _said(entry: ReportEntry) -> str:
    """Wpis tak, jak go napisał Wykonawca: ``tak`` albo ``nie`` i czynności."""

    mark = "" if entry.verdict is None else entry.verdict.value
    return " ".join(part for part in (mark, entry.activities) if part)


def _verdict(fault: VerdictFault) -> str:
    match fault:
        case VerdictFault.MISSING:
            return "nie ma „tak” ani „nie”"
        case VerdictFault.LETTER:
            return "ma samą literę „t” albo „n” zamiast „tak” albo „nie”"
        case VerdictFault.WORD:
            return "ma „skuteczne” albo „nieskuteczne” zamiast „tak” albo „nie”"
