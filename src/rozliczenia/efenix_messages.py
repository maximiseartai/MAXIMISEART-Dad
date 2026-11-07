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

from .collective_layout import HEADER_ROW
from .efenix_checks import DATE_TOLERANCE, DateRefused, OrderProblem
from .efenix_window import ForwardRefusal, PagePart
from .efenix_marking import Refusal
from .efenix_positions import (
    Excess,
    MissingPositions,
    NotWholeQuantities,
    OrderFault,
    OtherAmount,
    PageRead,
    UnpairedColumns,
    column_of,
)
from .message import IF_ERROR_RETURNS, Message, file_label, refer_if
from .workbook_files import Problem, WorkbookError

_PROCESS: Final = "Wycena w efenix"
_UNCHANGED: Final = "W efenix nic się nie zmieniło."
_KEPT: Final = "Wycena zleceń sprzed zatrzymania została w efenix."
_EFENIX: Final = "okno efenix"


def source_unusable(error: WorkbookError) -> Message:
    """Plik zbiorczy, którego nie da się użyć; ``error`` mówi dlaczego."""

    match error.problem:
        case Problem.MISSING:
            return collective_file_missing(error.path)
        case Problem.OPEN_IN_EXCEL:
            return _source_open_in_excel(error.path)
        case Problem.INACCESSIBLE:
            return _source_inaccessible(error.path)
        case Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return _source_unreadable(error.path)


def collective_file_missing(source: Path) -> Message:
    """Nie ma Pliku zbiorczego okresu ``source``; ten sam Komunikat w procesie i w Diagnozie."""

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
        action=f"Poczekaj, aż OneDrive skończy synchronizację, i uruchom ponownie. {IF_ERROR_RETURNS}",
    )


def _source_unreadable(source: Path) -> Message:
    return Message(
        code="EFENIX_NIECZYTELNY_PLIK_ZBIORCZY",
        dad_file="collective_file",
        what=f"Plik zbiorczy jest uszkodzony albo nie ma układu Pliku zbiorczego. {_UNCHANGED}",
        where=file_label(source),
        action=f"Otwórz Plik zbiorczy w Excelu i sprawdź, czy otwiera się poprawnie. {refer_if('Jeśli tak')}",
    )


def missing_columns(source: Path, headers: Sequence[str]) -> Message:
    """W wierszu 17 Pliku zbiorczego brakuje nagłówków kolumn, które Wycena w efenix porównuje z efenix."""

    listed = ", ".join(headers)
    return Message(
        code="EFENIX_BRAK_NAGLOWKOW",
        dad_file="collective_file",
        what=f"W Pliku zbiorczym brakuje nagłówków: {listed}. {_UNCHANGED}",
        where=f"{file_label(source)}, wiersz {HEADER_ROW}",
        action=f"Przywróć nagłówki w wierszu {HEADER_ROW} Pliku zbiorczego, zapisz plik i uruchom ponownie.",
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
        what=f"efenix wylogował i pokazał stronę logowania, więc {_PROCESS} się zatrzymała. {_after_stop(kept=kept)}",
        where=_EFENIX,
        action="Zaloguj się w efenix i uruchom ponownie. Gotowe zlecenia narzędzie tylko sprawdzi, a resztę wyceni dalej.",
    )


def window_closed(*, kept: bool) -> Message:
    """Okno albo karta efenix zamknęły się w trakcie przebiegu; ``kept`` jak w ``logged_out``."""

    return Message(
        code="EFENIX_OKNO_ZAMKNIETE",
        what=f"Okno efenix zostało zamknięte, więc {_PROCESS} się zatrzymała. {_after_stop(kept=kept)}",
        where=_EFENIX,
        action="Uruchom ponownie i zostaw okno efenix otwarte do końca. Gotowe zlecenia narzędzie tylko sprawdzi.",
    )


def window_stopped(part: PagePart, *, kept: bool) -> Message:
    """Okno efenix nie dokończyło kroku w części ``part`` strony; ``kept`` jak w ``logged_out``.

    Komunikat nie zgaduje przyczyny (zerwane połączenie, wolny albo zmieniony efenix): to Zatrzymanie „do Maksa”, więc
    Centrum daje przy nim Diagnozę i Zgłoszenie, a Maks ustala przyczynę z nich i z Logów Uruchomienia. „Gdzie” nazywa
    tylko część strony, bez treści strony.
    """

    return Message.to_maintainer(
        code="EFENIX_OKNO_ZATRZYMANE",
        what=f"{_PROCESS} się zatrzymała, Maks już wie. {_after_stop(kept=kept)}",
        where=f"{_EFENIX}, {part.value}",
        before=(
            "Uruchom ponownie: gotowe zlecenia narzędzie tylko sprawdzi, a resztę wyceni dalej. Jeśli Wycena zatrzyma się "
            "znowu, wyceń pozostałe zlecenia w efenix sam albo poczekaj na poprawkę narzędzia."
        ),
    )


def efenix_unreachable(*, kept: bool) -> Message:
    """Okno nie otworzyło efenix; ``kept`` jak w ``logged_out``."""

    return Message(
        code="EFENIX_NIEDOSTEPNY",
        what=f"Nie udało się otworzyć efenix. {_after_stop(kept=kept)}",
        where=_EFENIX,
        action=(
            "Sprawdź połączenie z internetem i czy efenix otwiera się w przeglądarce, potem uruchom ponownie. "
            f"{IF_ERROR_RETURNS}"
        ),
    )


def browser_not_started() -> Message:
    """Przeglądarka okna efenix nie wystartowała, więc proces nie otworzył efenix."""

    return Message(
        code="EFENIX_BRAK_PRZEGLADARKI",
        what=f"Nie udało się otworzyć przeglądarki Google Chrome z oknem efenix. {_UNCHANGED}",
        where=_EFENIX,
        action=(
            "Zamknij okno efenix, jeśli zostało otwarte z poprzedniej Wyceny w efenix, i uruchom ponownie. "
            f"{refer_if('Jeśli na komputerze nie ma Google Chrome albo błąd wraca')}"
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
                    "Zamknij Plik zbiorczy w Excelu, poczekaj, aż OneDrive skończy synchronizację, i uruchom ponownie. "
                    f"{IF_ERROR_RETURNS}"
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


def order_error(source: Path, row: int, problem: OrderFault, *, changed: bool) -> Message:
    """Zlecenie z wiersza ``row`` Pliku zbiorczego, które proces zostawia tacie, bo ``problem``; ``changed``: przy tym
    zleceniu proces wysłał już do efenix zmianę (Wycena ze śladu działań okna).

    Bez zmiany Komunikat mówi, że zlecenie zostało w efenix bez zmian, poza kwotą inną niż AU (``OtherAmount``) i
    odmową Przekazania (``ForwardRefusal``): ich Komunikat sam mówi, że ilości albo wycena z pliku są już w efenix,
    także wtedy, gdy wpisało je wcześniejsze Uruchomienie.
    """

    code, what, action = _order_error(problem)
    unchanged = "" if changed or isinstance(problem, OtherAmount | ForwardRefusal) else " Zlecenie zostało w efenix bez zmian."
    return Message(
        code=code,
        dad_file="collective_file",
        what=f"{what}{unchanged}",
        where=f"{file_label(source)}, wiersz {row}",
        action=action,
    )


def emmett_warning(source: Path, row: int, excess: Sequence[Excess]) -> Message:
    """Ostrzeżenie Emmetta: efenix ma w zleceniu z wiersza ``row`` w pozycjach ``excess`` więcej niż Plik zbiorczy, więc
    proces ich nie obniżył, a pozostałe ilości z pliku wpisał."""

    listed = "; ".join(f"{_position(more.position)}: efenix {more.efenix}, plik {more.file}" for more in excess)
    return Message(
        code="EFENIX_WIECEJ_NIZ_PLIK",
        dad_file="collective_file",
        what=(
            f"efenix ma więcej niż Plik zbiorczy: {listed}. Narzędzie tych ilości nie zmieniło, a pozostałe ilości z pliku"
            " wpisało."
        ),
        where=f"{file_label(source)}, wiersz {row}",
        action=(
            "Jeśli rację ma efenix, popraw Plik zbiorczy i uruchom ponownie. Jeśli rację ma plik, zmniejsz tę ilość w efenix"
            " sam."
        ),
    )


_PRICE_YOURSELF: Final = "Sprawdź zlecenie w efenix i wyceń je sam."
_REFUSED: Final = "efenix nie przyjął Przekazania do akceptacji"
_REFUSAL_PRICED: Final = "Wycena z Pliku zbiorczego jest już uzupełniona w efenix."
_FORWARD_AGAIN: Final = "przekaż zlecenie do akceptacji sam albo uruchom ponownie przyciskiem „Uzupełnij i zapisz”."
_MISSING_FOR_FORWARD: Final = {
    ForwardRefusal.NO_PHOTOS: (
        "do wyceny nie są dołączone żadne zdjęcia, a są wymagane przy pracach ziemnych i zleceniu UST",
        "Dołącz zdjęcia do wyceny w efenix",
    ),
    ForwardRefusal.NO_LENGTH: ("zlecenie nie ma długości przyłącza", "Podaj długość przyłącza w efenix"),
    ForwardRefusal.NO_PRICING: ("nie widzi w zleceniu wyceny", "Sprawdź wycenę zlecenia w efenix"),
    ForwardRefusal.NO_DATE: ("zlecenie nie ma daty wykonania", "Ustaw datę wykonania w efenix"),
}
"""Czego efenix brakuje do Przekazania do akceptacji przy każdej znanej odmowie i co tata ma uzupełnić."""


def _position(position: str) -> str:
    column = column_of(position)
    return f"pozycja INDEKS_{position} ({'bez kolumny w Pliku zbiorczym' if column is None else f'kolumna {column}'})"


def _amount(amount: Decimal) -> str:
    return f"{amount:.2f}".replace(".", ",") + " zł"


_MISSING_AFTER: Final = {
    PageRead.OPENED: "",
    PageRead.AFTER_DATE: (
        " Narzędzie ustawiło już datę wykonania z DATA, ale nie załadowało Wyceny Emmetta i nie wpisało ilości."
    ),
    PageRead.AFTER_EMMETT: " Wycena Emmetta jest już załadowana, a narzędzie niczego do niej nie dopisało.",
}
"""Co proces zmienił już w zleceniu w efenix, zanim odczyt strony pokazał brak pozycji."""


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
        case MissingPositions(positions, read):
            return (
                "EFENIX_BRAK_POZYCJI",
                (
                    "Strona zlecenia w efenix nie ma pozycji, w których Plik zbiorczy ma ilość:"
                    f" {', '.join(_position(position) for position in positions)}.{_MISSING_AFTER[read]}"
                ),
                "Sprawdź ilości w tych kolumnach Pliku zbiorczego i pozycje zlecenia w efenix, a potem wyceń zlecenie w efenix sam.",
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
            return (
                "EFENIX_INNA_DATA",
                f"Data wykonania zlecenia w efenix różni się od dnia z DATA w Pliku zbiorczym o więcej niż {DATE_TOLERANCE.days} dni.",
                _PRICE_YOURSELF,
            )
        case ForwardRefusal.OTHER_TEXT:
            return (
                "EFENIX_ODMOWA_PRZEKAZANIA",
                f"{_REFUSED} i pokazał informację, której narzędzie nie zna. {_REFUSAL_PRICED}",
                "Otwórz zlecenie w efenix, sprawdź, czego efenix brakuje do Przekazania, i przekaż je do akceptacji sam.",
            )
        case ForwardRefusal():
            missing, fix = _MISSING_FOR_FORWARD[problem]
            return "EFENIX_ODMOWA_PRZEKAZANIA", f"{_REFUSED}: {missing}. {_REFUSAL_PRICED}", f"{fix}, a potem {_FORWARD_AGAIN}"
        case OrderProblem.NOT_FORWARDED:
            return (
                "EFENIX_NIEPRZEKAZANE",
                (
                    "Narzędzie przekazało zlecenie do akceptacji, ale efenix nie pokazuje go potem ze statusem „Do"
                    " akceptacji”. Wycena z Pliku zbiorczego jest już wpisana w efenix."
                ),
                "Sprawdź zlecenie w efenix i, jeśli nie jest przekazane, przekaż je do akceptacji sam.",
            )


def unexpected_failure() -> Message:
    """Nieoczekiwany błąd przed końcem procesu."""

    return Message.to_maintainer(
        code="EFENIX_BLAD_NIEOCZEKIWANY",
        what=f"{_PROCESS} zatrzymała się przez nieoczekiwany błąd. Część zleceń mogła zostać już wyceniona w efenix.",
        where=_PROCESS,
    )


def plan_not_shown() -> Message:
    """Wycena w efenix nie ma podglądu bez zapisu; Komunikat rdzenia dla trybu bez zapisu."""

    return Message.to_maintainer(
        code="EFENIX_PLAN_NIEPOKAZANY",
        what=f"{_PROCESS} skończyła się, ale nie udało się pokazać planu. {_UNCHANGED}",
        where=_PROCESS,
    )


def summary_not_shown() -> Message:
    """Proces skończył się, ale nie udało się zbudować podsumowania."""

    return Message.to_maintainer(
        code="EFENIX_PODSUMOWANIE_NIEPOKAZANE",
        what=f"{_PROCESS} skończyła się, ale nie udało się pokazać wyniku.",
        where=_PROCESS,
    )
