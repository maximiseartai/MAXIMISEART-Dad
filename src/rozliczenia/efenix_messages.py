"""Katalog Komunikatów Wyceny w efenix dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się stało, gdzie, co zrobić. Zatrzymanie to
``raise StopError(fabryka(...))``. Komunikaty wskazują Plik zbiorczy i numer wiersza, bez numerów zleceń, adresów,
loginów Wykonawców i treści stron efenix, bo trafiają też do Logów Uruchomienia.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from .efenix_checks import DateRefused, OrderProblem
from .efenix_marking import Refusal
from .efenix_positions import Conflict, NotWholeQuantities, OrderFault, OtherAmount, PricedDifferently, UnpairedColumns, column_of
from .message import REPORT_TO_MAINTAINER, Message, file_label
from .workbook_files import Problem, WorkbookError

_PROCESS: Final = "Wycena w efenix"
_UNCHANGED: Final = "W efenix nic się nie zmieniło."
_KEPT: Final = "Wycena zleceń sprzed zatrzymania została w efenix."
_EFENIX: Final = "okno efenix"


def source_unusable(error: WorkbookError) -> Message:
    """Plik zbiorczy, którego nie da się użyć; ``error`` mówi dlaczego."""

    match error.problem:
        case Problem.MISSING:
            return _source_missing(error.path)
        case Problem.OPEN_IN_EXCEL:
            return _source_open_in_excel(error.path)
        case Problem.INACCESSIBLE:
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


def _source_open_in_excel(source: Path) -> Message:
    return Message(
        code="EFENIX_PLIK_ZBIORCZY_OTWARTY",
        dad_file="collective_file",
        what=f"Plik zbiorczy jest otwarty w Excelu, a {_PROCESS} oznacza w nim gotowe zlecenia Znacznikiem efenix. {_UNCHANGED}",
        where=file_label(source),
        action="Zapisz i zamknij Plik zbiorczy w Excelu, potem uruchom ponownie.",
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


def logged_out(*, kept: bool) -> Message:
    """Okno efenix pokazało stronę logowania; ``kept``: przed Zatrzymaniem proces zmienił już coś w efenix."""

    return Message(
        code="EFENIX_WYLOGOWANY",
        what=f"efenix pokazał stronę logowania, więc {_PROCESS} się zatrzymała. {_after_stop(kept=kept)}",
        where=_EFENIX,
        action="Zaloguj się w efenix i uruchom ponownie.",
    )


def efenix_changed(*, kept: bool) -> Message:
    """Strona efenix wygląda inaczej, niż zna ją narzędzie; ``kept`` jak w ``logged_out``."""

    return Message(
        code="EFENIX_ZMIENIONY",
        what=(
            "Strona efenix wygląda inaczej niż zwykle, więc narzędzie zatrzymało się i dalej niczego w niej nie klika. "
            f"{_after_stop(kept=kept)}"
        ),
        where=_EFENIX,
        action=REPORT_TO_MAINTAINER,
    )


def efenix_unreachable(*, kept: bool) -> Message:
    """Okno nie otworzyło efenix; ``kept`` jak w ``logged_out``."""

    return Message(
        code="EFENIX_NIEDOSTEPNY",
        what=f"Nie udało się otworzyć efenix. {_after_stop(kept=kept)}",
        where=_EFENIX,
        action=(
            "Sprawdź połączenie z internetem i czy efenix otwiera się w przeglądarce, potem uruchom ponownie. Jeśli błąd "
            "wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def _after_stop(*, kept: bool) -> str:
    return _KEPT if kept else _UNCHANGED


def marks_not_saved(source: Path, refusal: Refusal) -> Message:
    """Gotowe zlecenia nie dostały Znacznika efenix, bo Plik zbiorczy się nie zmienił z powodu ``refusal``."""

    match refusal:
        case Refusal.OPEN_IN_EXCEL:
            code, why, action = (
                "EFENIX_ZNACZNIKI_PLIK_OTWARTY",
                "Plik zbiorczy jest otwarty w Excelu",
                "Zapisz i zamknij Plik zbiorczy w Excelu, potem uruchom ponownie.",
            )
        case Refusal.CHANGED:
            code, why, action = (
                "EFENIX_ZNACZNIKI_PLIK_ZMIENIONY",
                "Plik zbiorczy zmienił się w trakcie Wyceny w efenix",
                "Zamknij Plik zbiorczy w Excelu i uruchom ponownie.",
            )
        case Refusal.WRITE_FAILED:
            code, why, action = (
                "EFENIX_ZNACZNIKI_NIEZAPISANE",
                "nie udało się zapisać Pliku zbiorczego",
                (
                    "Zamknij Plik zbiorczy w Excelu, poczekaj, aż OneDrive skończy synchronizację, i uruchom ponownie. Jeśli "
                    "błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
                ),
            )
    return Message(
        code=code,
        dad_file="collective_file",
        what=(
            f"Gotowe zlecenia nie dostały Znacznika efenix, bo {why}. Ich wycena została w efenix. Ponowne uruchomienie "
            "oznaczy je bez zmian w efenix i pokaże listę błędów i ostrzeżeń."
        ),
        where=file_label(source),
        action=action,
    )


def order_error(source: Path, row: int, problem: OrderFault) -> Message:
    """Zlecenie z wiersza ``row`` Pliku zbiorczego, które proces zostawia tacie, bo ``problem``.

    Kwota inna niż AU po dopisaniu ilości i data, której efenix nie zapisał po „Potwierdź”, to jedyne błędy, przy których
    proces mógł już coś zmienić w zleceniu w efenix.
    """

    code, what, action = _order_error(problem)
    unchanged = "" if isinstance(problem, OtherAmount) or problem is DateRefused.NOT_SAVED else " Zlecenie zostało w efenix bez zmian."
    return Message(
        code=code,
        dad_file="collective_file",
        what=f"{what}{unchanged}",
        where=f"{file_label(source)}, wiersz {row}",
        action=action,
    )


def emmett_conflict(source: Path, row: int, conflicts: Sequence[Conflict]) -> Message:
    """Emmett wpisał w zleceniu z wiersza ``row`` ilości inne niż Plik zbiorczy, więc proces niczego nie dopisał."""

    listed = "; ".join(f"{_position(conflict.position)}: Emmett {conflict.emmett}, plik {conflict.file}" for conflict in conflicts)
    return Message(
        code="EFENIX_SPRZECZNOSC_Z_EMMETTEM",
        dad_file="collective_file",
        what=(
            f"Wycena Emmetta ma inne ilości niż Plik zbiorczy: {listed}. Wycena Emmetta jest załadowana, a narzędzie niczego "
            "do niej nie dopisało."
        ),
        where=f"{file_label(source)}, wiersz {row}",
        action="Rozstrzygnij, czy rację ma Emmett, czy Plik zbiorczy, i popraw wycenę w efenix sam.",
    )


_PRICE_YOURSELF: Final = "Sprawdź zlecenie w efenix i wyceń je sam."


def _position(position: str) -> str:
    column = column_of(position)
    return f"pozycja INDEKS_{position} ({'bez kolumny w Pliku zbiorczym' if column is None else f'kolumna {column}'})"


def _amount(amount: Decimal) -> str:
    return f"{amount:.2f}".replace(".", ",") + " zł"


def _order_error(problem: OrderFault) -> tuple[str, str, str]:
    match problem:
        case UnpairedColumns(columns):
            return (
                "EFENIX_KOLUMNA_BEZ_POZYCJI",
                f"Zlecenie ma ilość w kolumnach, które nie mają pozycji w efenix: {', '.join(columns)}.",
                _PRICE_YOURSELF,
            )
        case NotWholeQuantities(columns):
            return (
                "EFENIX_ILOSC_NIECALKOWITA",
                f"Ilość usług nie jest liczbą całkowitą większą od 0 w kolumnach: {', '.join(columns)}.",
                "Popraw ilość w Pliku zbiorczym albo wyceń zlecenie w efenix sam.",
            )
        case PricedDifferently(efenix_amount, file_amount, positions):
            different = f" Inne ilości: {', '.join(_position(position) for position in positions)}." if positions else ""
            return (
                "EFENIX_WYCENA_INNA",
                (
                    f"Zlecenie ma już wycenę w efenix i różni się ona od Pliku zbiorczego: kwota w efenix {_amount(efenix_amount)},"
                    f" Kwota (AU) {_amount(file_amount)}.{different}"
                ),
                "Sprawdź wycenę w efenix i Plik zbiorczy, popraw tę, która jest błędna, i uruchom ponownie.",
            )
        case OtherAmount(efenix_amount, file_amount):
            return (
                "EFENIX_INNA_KWOTA",
                (
                    f"Po dopisaniu ilości z Pliku zbiorczego kwota w efenix to {_amount(efenix_amount)}, a Kwota (AU)"
                    f" {_amount(file_amount)}. Ilości z pliku są już wpisane w efenix."
                ),
                "Sprawdź wycenę w efenix i Plik zbiorczy, popraw tę, która jest błędna, i uruchom ponownie.",
            )
        case DateRefused.OUT_OF_RANGE:
            return (
                "EFENIX_DATA_POZA_ZAKRESEM",
                (
                    "Dzień z DATA jest poza zakresem dat wykonania, który przyjmuje efenix (od pierwszego dnia poprzedniego"
                    " miesiąca do dziś), więc narzędzie nie ustawiło daty wykonania ani nie wyceniło zlecenia."
                ),
                (
                    "Sprawdź DATA w Pliku zbiorczym. Jeśli jest błędna, popraw ją i uruchom ponownie. Jeśli jest dobra, okres"
                    " jest za stary dla efenix: ustaw datę wykonania i wyceń zlecenie w efenix sam."
                ),
            )
        case DateRefused.NOT_SAVED:
            return (
                "EFENIX_DATA_NIEZAPISANA",
                (
                    "efenix nie zapisał daty wykonania z DATA: po ponownym otwarciu zlecenia nie ma jej na stronie. Narzędzie"
                    " nie załadowało Wyceny Emmetta i nie wpisało ilości."
                ),
                "Ustaw datę wykonania w efenix sam i uruchom ponownie.",
            )
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
        what=f"{_PROCESS} zatrzymała się przez nieoczekiwany błąd. Część zleceń mogła zostać już wyceniona w efenix.",
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
