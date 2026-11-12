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
                f"Raport wykonawcy z {_day(day)} przyszedł z adresu spoza listy adresów Wykonawców, więc Centrum go nie "
                "wpisało. Powiedz Maksowi, czyj to adres."
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
        case UnknownNumber(worker=worker, day=day, number=number, bar=bar):
            return (
                f"Numeru {number} z Wpisu od {worker} z {_day(day)} nie ma w uporządkowanych zleceniach INTERMAX, a "
                f"Centrum go nie dopisało, bo {_add_bar(bar, day)}."
            )
        case RepeatedOrder(worker=worker, day=day, number=number):
            return (
                f"Zlecenie {number} jest dwa razy w dniu {_day(day)} u {worker}, więc Centrum niczego do niego nie "
                "wpisało."
            )
        case RepeatedNumber(worker=worker, day=day, number=number, places=places):
            where = ", ".join(f"u {owner} z {_day(order_day)}" for order_day, owner in places)
            return (
                f"Zlecenie {number} jest w INTERMAX więcej niż raz: {where}. Centrum nie wie, którego z nich dotyczy "
                f"Wpis od {worker} z {_day(day)}, więc nie zmieniło żadnego z nich przy tym kliknięciu."
            )
        case RefusedMove(worker=worker, day=day, number=number, order_day=order_day, bar=bar):
            return (
                f"Wpis zlecenia {number} od {worker} ma w temacie {_day(day)}, a INTERMAX ma to zlecenie w "
                f"{_day(order_day)}. Centrum go nie przeniosło i nie wpisało, bo {_bar(bar, day, order_day)}."
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


def _bar(bar: MoveBar, day: date, order_day: date) -> str:
    match bar:
        case MoveBar.NOT_ORDERED:
            return f"dzień {_day(day)} nie jest jeszcze uporządkowany w INTERMAX"
        case MoveBar.OTHER_SHEET:
            return f"dzień {_day(day)} jest uporządkowany w innym arkuszu zleceń"
        case MoveBar.CLOSED_TARGET:
            return f"okres z dniem {_day(day)} ma już Plik zbiorczy"
        case MoveBar.CLOSED_SOURCE:
            return f"okres z dniem {_day(order_day)} ma już Plik zbiorczy"
        case MoveBar.AFTER_TODAY:
            return f"dzień {_day(order_day)} jeszcze nie nadszedł"


def _add_bar(bar: AddBar, day: date) -> str:
    match bar:
        case AddBar.PASTED:
            return "INTERMAX ma go jako Surowe zlecenie: uporządkuj INTERMAX i kliknij jeszcze raz"
        case AddBar.FORM:
            return f"dopisuje tylko numer z {ADDED_DIGITS} cyframi, jak numer z aplikacji firmowej"
        case AddBar.MISTAKEN_SUBJECT:
            return "Raport wykonawcy ma pomylony temat (co najmniej dwa zlecenia z innego dnia)"
        case AddBar.NOT_ORDERED:
            return f"dzień {_day(day)} nie jest jeszcze uporządkowany w INTERMAX"


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
