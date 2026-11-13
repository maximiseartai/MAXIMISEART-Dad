"""Zdanie dla taty o problemie i o informacji Wpisania raportów, do widoku Raporty.

Zdanie nie ma adresu nadawcy: adres spoza listy widok Raporty pokazuje osobno (``SenderAddress.shown``, ADR 0028).
"""

from __future__ import annotations

from datetime import date
from typing import assert_never

from . import (
    ADDED_DIGITS,
    AddBar,
    Added,
    ConflictingVerdicts,
    HandedOver,
    ManualDifference,
    MissingVerdict,
    MoveBar,
    MovedFrom,
    MovedTo,
    RefusedMove,
    RepeatedNumber,
    RepeatedOrder,
    ReportEntry,
    ReportNote,
    ReportProblem,
    SubjectFault,
    SubjectLost,
    TakenOver,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    VerdictFault,
)

__all__ = ["note", "reason"]


def reason(problem: ReportProblem) -> str:
    match problem:
        case UnreadableSubject(worker=worker, arrived=arrived, fault=fault):
            return (
                f"Mail od {worker} z {arrived:%d.%m.%Y, %H:%M} ma w temacie słowo „Raport”, ale {_subject(fault)}, "
                "więc Centrum go nie wpisało."
            )
        case UnknownSender(day=day):
            return (
                f"Raport wykonawcy z {_day(day)} przyszedł z adresu, którego nie ma na Liście Wykonawców, więc Centrum "
                "go nie wpisało. Przypisz ten adres Wykonawcy, a następne kliknięcie go wpisze."
            )
        case MissingVerdict(worker=worker, day=day, number=number, fault=fault):
            return f"Wpis zlecenia {number} od {worker} z {_day(day)} {_verdict(fault)}, więc Centrum go nie wpisało."
        case ConflictingVerdicts(worker=worker, day=day, number=number, arrived=arrived, entries=entries):
            said = " i ".join(f"„{_said(entry)}”" for entry in entries)
            return (
                f"Raport wykonawcy od {worker} z {_day(day)}, który przyszedł {arrived:%d.%m.%Y o %H:%M}, ma dla zlecenia "
                f"{number} różne Wpisy: {said}, więc Centrum nie zmieniło tego zlecenia przy tym kliknięciu. Sprawdź z "
                "Wykonawcą, który Wpis jest dobry, i wpisz go ręcznie albo poczekaj na poprawiony mail."
            )
        case UnknownNumber():
            return _unknown(problem)
        case RepeatedOrder(worker=worker, day=day, number=number):
            return (
                f"Zlecenie {number} jest dwa razy w dniu {_day(day)} u {worker}, więc Centrum niczego do niego nie "
                "wpisało."
            )
        case RepeatedNumber(worker=worker, day=day, number=number, places=places):
            where = ", ".join(f"u {owner} z {_day(order_day)}" for order_day, owner in places)
            if len(places) == 1:
                where += (
                    " i w wierszu, z którego Centrum nie robi zlecenia (bez WYKONAWCA albo daty z godziną, Surowe "
                    "zlecenie albo zlecenie sprzed dni, które Centrum czyta)"
                )
            return (
                f"Zlecenie {number} jest w INTERMAX więcej niż raz: {where}. Centrum nie wie, którego z nich dotyczy "
                f"Wpis od {worker} z {_day(day)}, więc nie zmieniło żadnego z nich przy tym kliknięciu."
            )
        case RefusedMove(worker=worker, day=day, number=number, order_day=order_day, target=target, bar=bar):
            return (
                f"Wpis zlecenia {number} od {worker} ma w temacie {_day(day)}, a INTERMAX ma to zlecenie w "
                f"{_day(order_day)}. Centrum go nie przeniosło i nie wpisało, bo {_bar(bar, target, order_day)}."
            )
        case ManualDifference(key=key, column=column, manual=manual, reported=reported):
            return (
                f"Zlecenie {key.number} od {key.worker} z {_day(key.day)} ma w {column.value} ręczną wartość "
                f"„{manual}”, a Wpis raportu mówi „{reported}”. Ręczna wartość zostaje."
            )
        case _:
            assert_never(problem)


def note(found: ReportNote) -> str:
    """Informacja dla taty przy dniu Wykonawcy, krótko, bo stoi przy numerze zlecenia: tylko drugi Wykonawca albo drugi
    dzień."""

    match found:
        case TakenOver(previous=previous):
            return f"przejęte od {previous}"
        case HandedOver(successor=successor):
            return f"przekazane {successor}"
        case MovedFrom(origin_day=origin_day):
            return f"przeniesione z {_short(origin_day)}"
        case MovedTo(target_day=target_day):
            return f"przeniesione na {_short(target_day)}"
        case SubjectLost(order_day=order_day):
            return f"pomylony temat: wpisane do zlecenia z {_short(order_day)}"
        case Added():
            return "dopisane z raportu, uzupełnij resztę"
        case _:
            assert_never(found)


def _day(day: date) -> str:
    return f"{day:%d.%m.%Y}"


def _short(day: date) -> str:
    """Dzień bez roku i bez zera na początku, jak „4.11” w okienku dnia."""

    return f"{day.day}.{day.month:02d}"


def _bar(bar: MoveBar, target: date, order_day: date) -> str:
    """Powód odmowy Przeniesienia: dzień, na który Wpis przeniósłby zlecenie (``target``), albo dzień zlecenia."""

    match bar:
        case MoveBar.NOT_ORDERED:
            return f"dzień {_day(target)} nie jest jeszcze uporządkowany w INTERMAX"
        case MoveBar.OTHER_SHEET:
            return f"dzień {_day(target)} jest uporządkowany w innym arkuszu zleceń"
        case MoveBar.CLOSED_TARGET:
            return f"okres z dniem {_day(target)} ma już Plik zbiorczy"
        case MoveBar.CLOSED_SOURCE:
            return f"okres z dniem {_day(order_day)} ma już Plik zbiorczy"
        case MoveBar.AFTER_TODAY:
            return f"dzień {_day(order_day)} jeszcze nie nadszedł"


def _unknown(problem: UnknownNumber) -> str:
    number, worker, day = problem.number, problem.worker, problem.day
    missing = f"Numeru {number} z Wpisu od {worker} z {_day(day)} nie ma w uporządkowanych zleceniach INTERMAX"
    match problem.bar:
        case AddBar.IN_INTERMAX:
            return (
                f"Zlecenie {number} z Wpisu od {worker} z {_day(day)} jest już w INTERMAX, ale nie jako uporządkowane "
                "zlecenie z dniem i Wykonawcą: jego wiersz nie ma WYKONAWCA albo daty z godziną, jest Surowym zleceniem "
                "albo stoi nad wierszem wklejonym z aplikacji. Centrum niczego do niego nie wpisało i nie dopisało go "
                "drugi raz; uzupełnij ten wiersz albo uporządkuj INTERMAX i kliknij jeszcze raz."
            )
        case AddBar.BEFORE_WINDOW:
            return (
                f"Zlecenie {number} z Wpisu od {worker} z {_day(day)} jest już w INTERMAX, ale z dniem sprzed dni, których "
                "zlecenia Centrum czyta przy tym kliknięciu (sprzed dnia wdrożenia albo ponad tydzień przed pierwszym "
                "dniem otwartym). Centrum niczego do niego nie wpisało, nie przeniosło go i nie dopisało drugi raz; "
                "jeśli Wpis go dotyczy, popraw ten wiersz ręcznie według maila."
            )
        case AddBar.FORM:
            return (
                f"{missing}, a Centrum go nie dopisało, bo dopisuje tylko numer z {ADDED_DIGITS} cyframi, jak numer z "
                "aplikacji firmowej."
            )
        case AddBar.MISTAKEN_SUBJECT:
            return (
                f"{missing}, a Centrum go nie dopisało, bo Raport wykonawcy ma pomylony temat (co najmniej dwa zlecenia "
                "z innego dnia)."
            )
        case AddBar.NOT_ORDERED:
            return f"{missing}, a Centrum go nie dopisało, bo dzień {_day(day)} nie jest jeszcze uporządkowany w INTERMAX."


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
    """Wpis tak, jak go napisał Wykonawca: znak (``tak``, ``t``, ``nieskuteczne``) i czynności."""

    return " ".join(part for part in (entry.mark, entry.activities) if part)


def _verdict(fault: VerdictFault) -> str:
    match fault:
        case VerdictFault.MISSING:
            return "nie ma „tak” ani „nie”"
        case VerdictFault.LETTER_YES:
            return "ma samą literę „t” zamiast „tak”"
        case VerdictFault.LETTER_NO:
            return "ma samą literę „n” zamiast „nie”"
        case VerdictFault.WORD_YES:
            return "ma „skuteczne” zamiast „tak”"
        case VerdictFault.WORD_NO:
            return "ma „nieskuteczne” zamiast „nie”"
