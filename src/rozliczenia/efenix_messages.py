"""Katalog Komunikatów Wyceny w efenix dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się stało, gdzie, co zrobić. Zatrzymanie to
``raise StopError(fabryka(...))``. Komunikaty wskazują Plik zbiorczy i numer wiersza, bez numerów zleceń, adresów,
loginów Wykonawców i treści stron efenix, bo trafiają też do Logów Uruchomienia.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .efenix_checks import OrderProblem
from .message import REPORT_TO_MAINTAINER, Message, file_label
from .workbook_files import Problem, WorkbookError

_PROCESS: Final = "Wycena w efenix"
_UNCHANGED: Final = "W efenix nic się nie zmieniło."
_EFENIX: Final = "okno efenix"


def source_unusable(error: WorkbookError) -> Message:
    """Plik zbiorczy, którego nie da się użyć; ``error`` mówi dlaczego."""

    match error.problem:
        case Problem.MISSING:
            return _source_missing(error.path)
        case Problem.INACCESSIBLE | Problem.OPEN_IN_EXCEL:
            return _source_inaccessible(error.path)
        case Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return _source_unreadable(error.path)


def _source_missing(source: Path) -> Message:
    return Message(
        code="EFENIX_BRAK_PLIKU_ZBIORCZEGO",
        what=f"Nie znaleziono Pliku zbiorczego. {_UNCHANGED}",
        where=file_label(source),
        action="Sprawdź, czy Plik zbiorczy okresu jest w Folderze okresu, i uruchom ponownie.",
    )


def _source_inaccessible(source: Path) -> Message:
    return Message(
        code="EFENIX_NIEDOSTEPNY_PLIK_ZBIORCZY",
        dad_file="collective_file",
        what=(
            "Nie można teraz odczytać Pliku zbiorczego. Plik może być zajęty przez inny program albo czekać na pobranie "
            f"z OneDrive. {_UNCHANGED}"
        ),
        where=file_label(source),
        action=(
            "Poczekaj, aż OneDrive skończy synchronizację, i uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat "
            "osobie utrzymującej narzędzie."
        ),
    )


def _source_unreadable(source: Path) -> Message:
    return Message(
        code="EFENIX_NIECZYTELNY_PLIK_ZBIORCZY",
        dad_file="collective_file",
        what=f"Plik zbiorczy jest uszkodzony albo nie ma układu Pliku zbiorczego. {_UNCHANGED}",
        where=file_label(source),
        action=(
            "Otwórz Plik zbiorczy w Excelu i sprawdź, czy otwiera się poprawnie. Jeśli tak, przekaż ten komunikat "
            "osobie utrzymującej narzędzie."
        ),
    )


def missing_columns(source: Path, headers: Sequence[str]) -> Message:
    """W wierszu 17 Pliku zbiorczego brakuje nagłówków kolumn, które Wycena w efenix porównuje z efenix."""

    listed = ", ".join(headers)
    return Message(
        code="EFENIX_BRAK_NAGLOWKOW",
        dad_file="collective_file",
        what=f"W Pliku zbiorczym brakuje nagłówków: {listed}. {_UNCHANGED}",
        where=f"{file_label(source)}, wiersz 17",
        action="Przywróć nagłówki w wierszu 17 Pliku zbiorczego, zapisz plik i uruchom ponownie.",
    )


def amounts_not_computed(source: Path, row: int) -> Message:
    """Plik zbiorczy nie ma ``Kwota`` (AU) policzonych przez Excel, więc nie wiadomo, z czym porównać wycenę."""

    return Message(
        code="EFENIX_KWOTY_NIEPOLICZONE",
        dad_file="collective_file",
        what=f"Plik zbiorczy nie ma kwot w kolumnie AU policzonych przez Excel. {_UNCHANGED}",
        where=f"{file_label(source)}, kolumna AU, wiersz {row}",
        action="Otwórz i zapisz Plik zbiorczy w Excelu, potem zamknij go i uruchom ponownie.",
    )


def logged_out() -> Message:
    """Okno efenix pokazało stronę logowania."""

    return Message(
        code="EFENIX_WYLOGOWANY",
        what=f"efenix pokazał stronę logowania, więc {_PROCESS} się zatrzymała. {_UNCHANGED}",
        where=_EFENIX,
        action="Zaloguj się w efenix i uruchom ponownie.",
    )


def efenix_changed() -> Message:
    """Strona efenix wygląda inaczej, niż zna ją narzędzie."""

    return Message(
        code="EFENIX_ZMIENIONY",
        what=f"Strona efenix wygląda inaczej niż zwykle, więc narzędzie niczego w niej nie kliknęło. {_UNCHANGED}",
        where=_EFENIX,
        action=REPORT_TO_MAINTAINER,
    )


def efenix_unreachable() -> Message:
    """Okno nie otworzyło efenix."""

    return Message(
        code="EFENIX_NIEDOSTEPNY",
        what=f"Nie udało się otworzyć efenix. {_UNCHANGED}",
        where=_EFENIX,
        action=(
            "Sprawdź połączenie z internetem i czy efenix otwiera się w przeglądarce, potem uruchom ponownie. Jeśli błąd "
            "wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def order_error(source: Path, row: int, problem: OrderProblem) -> Message:
    """Zlecenie z wiersza ``row`` Pliku zbiorczego, którego proces nie ruszył w efenix, bo ``problem``."""

    code, what, action = _order_error(problem)
    return Message(
        code=code,
        dad_file="collective_file",
        what=f"{what} Zlecenie zostało w efenix bez zmian.",
        where=f"{file_label(source)}, wiersz {row}",
        action=action,
    )


_PRICE_YOURSELF: Final = "Sprawdź zlecenie w efenix i wyceń je sam."


def _order_error(problem: OrderProblem) -> tuple[str, str, str]:
    match problem:
        case OrderProblem.NO_NUMBER:
            return "EFENIX_BRAK_NUMERU", "Wiersz nie ma numeru zlecenia w NUMER ZL.", "Uzupełnij NUMER ZL. w Pliku zbiorczym albo wyceń zlecenie w efenix sam."
        case OrderProblem.NO_DATE:
            return "EFENIX_BRAK_DATY", "Wiersz nie ma daty w DATA.", "Uzupełnij DATA w Pliku zbiorczym albo wyceń zlecenie w efenix sam."
        case OrderProblem.UNKNOWN_NUMBER:
            return "EFENIX_NIEZNANY_NUMER", "efenix nie zna zlecenia o numerze z NUMER ZL.", "Sprawdź NUMER ZL. w Pliku zbiorczym i zlecenie w efenix."
        case OrderProblem.SEVERAL_FOUND:
            return "EFENIX_KILKA_ZLECEN", "efenix ma kilka zleceń o numerze z NUMER ZL.", _PRICE_YOURSELF
        case OrderProblem.OTHER_STATUS:
            return "EFENIX_INNY_STATUS", "Zlecenie w efenix nie ma statusu „Do wyceny”.", "Sprawdź status zlecenia w efenix."
        case OrderProblem.OTHER_REALIZATOR:
            return "EFENIX_INNY_REALIZATOR", "Realizator zlecenia w efenix jest inny niż WYKONAWCA w Pliku zbiorczym.", _PRICE_YOURSELF
        case OrderProblem.OTHER_ADDRESS:
            return "EFENIX_INNY_ADRES", "Dane adresowe zlecenia w efenix są inne niż ADRES w Pliku zbiorczym.", _PRICE_YOURSELF
        case OrderProblem.OTHER_DATE:
            return "EFENIX_INNA_DATA", "Data wykonania zlecenia w efenix jest inna niż dzień z DATA w Pliku zbiorczym.", _PRICE_YOURSELF


def unexpected_failure() -> Message:
    """Nieoczekiwany błąd przed końcem procesu."""

    return Message(
        code="EFENIX_BLAD_NIEOCZEKIWANY",
        what=f"{_PROCESS} zatrzymała się przez nieoczekiwany błąd. Część zleceń mogła zostać sprawdzona.",
        where=_PROCESS,
        action=REPORT_TO_MAINTAINER,
    )


def plan_not_shown() -> Message:
    """Wycena w efenix nie ma podglądu bez zapisu; Komunikat rdzenia dla trybu bez zapisu."""

    return Message(
        code="EFENIX_PLAN_NIEPOKAZANY",
        what=f"{_PROCESS} skończyła się, ale nie udało się pokazać planu. {_UNCHANGED}",
        where=_PROCESS,
        action=REPORT_TO_MAINTAINER,
    )


def summary_not_shown() -> Message:
    """Proces skończył się, ale nie udało się zbudować podsumowania."""

    return Message(
        code="EFENIX_PODSUMOWANIE_NIEPOKAZANE",
        what=f"{_PROCESS} skończyła się, ale nie udało się pokazać wyniku.",
        where=_PROCESS,
        action=REPORT_TO_MAINTAINER,
    )
