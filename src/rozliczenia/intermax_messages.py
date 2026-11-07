"""Katalog Komunikatów Uporządkowania INTERMAX dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się stało, gdzie, co zrobić.
Zatrzymanie to ``raise StopError(fabryka(...))``. Komunikaty wskazują tylko plik, folder i arkusz, bez adresów,
numerów zleceń, numerów umów i loginów Wykonawców.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from .message import REPORT_TO_MAINTAINER, Message, file_label, folder_label
from .register_columns import ORDERED_FONT, ORDERED_SIZE
from .text import row_range
from .workbook_files import Problem, WorkbookError

_PROCESS = "Uporządkowanie INTERMAX"
_UNCHANGED = "INTERMAX nie został zmieniony."


def register_unusable(error: WorkbookError) -> Message:
    """INTERMAX, którego nie da się użyć; ``error`` mówi dlaczego."""

    match error.problem:
        case Problem.MISSING:
            return register_missing(error.path)
        case Problem.OPEN_IN_EXCEL:
            return register_open(error.path)
        case Problem.INACCESSIBLE:
            return _register_inaccessible(error.path)
        case Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return _register_unreadable(error.path)


def register_missing(register: Path) -> Message:
    """Nie ma INTERMAX pod ścieżką z Ustawień taty."""

    return Message(
        code="BRAK_INTERMAX",
        what=f"Nie znaleziono INTERMAX. {_UNCHANGED}",
        where=file_label(register),
        action="Wybierz w Ustawieniach właściwy plik INTERMAX i uruchom ponownie.",
    )


def register_open(register: Path) -> Message:
    """INTERMAX jest otwarty w Excelu: plik blokady obok przed Kopią INTERMAX albo przy odmowie podmiany pliku."""

    return Message(
        code="INTERMAX_OTWARTY",
        dad_file="order_register",
        what=f"INTERMAX jest otwarty w Excelu. {_UNCHANGED}",
        where=file_label(register),
        action=(
            "Zapisz i zamknij INTERMAX w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat "
            f"wraca, usuń z tego samego folderu pozostawiony plik ~${register.name} i uruchom ponownie."
        ),
    )


def _register_inaccessible(register: Path) -> Message:
    return Message(
        code="NIEDOSTEPNY_INTERMAX",
        dad_file="order_register",
        what=(
            "Nie można teraz odczytać INTERMAX. Plik może być zajęty przez inny program albo czekać na pobranie "
            f"z OneDrive. {_UNCHANGED}"
        ),
        where=file_label(register),
        action=(
            "Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy INTERMAX otwiera się w Excelu. Zamknij go "
            "i uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def _register_unreadable(register: Path) -> Message:
    return Message(
        code="NIECZYTELNY_INTERMAX",
        dad_file="order_register",
        what=f"Nie można odczytać INTERMAX jako skoroszytu Excela. {_UNCHANGED}",
        where=file_label(register),
        action=(
            "Otwórz INTERMAX w Excelu i sprawdź, czy się otwiera. Jeśli tak, zapisz go, zamknij i uruchom ponownie. "
            "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def no_order_sheet(register: Path) -> Message:
    """Żaden arkusz INTERMAX nie ma w wierszu 1 nagłówków zleceń od ``AKCJE`` do ``UWAGI``."""

    return Message(
        code="BRAK_ARKUSZA_ZLECEN",
        dad_file="order_register",
        what=f"W INTERMAX nie ma arkusza zleceń z nagłówkami od AKCJE do UWAGI w wierszu 1. {_UNCHANGED}",
        where=file_label(register),
        action="Sprawdź nagłówki arkusza zleceń w wierszu 1 i uruchom ponownie.",
    )


def no_raw_orders(register: Path, sheet: str) -> Message:
    """Na dole arkusza zleceń nie ma Surowych zleceń; nic nie zapisano."""

    return Message(
        code="BRAK_SUROWYCH_ZLECEN",
        dad_file="order_register",
        what=f"Na dole arkusza zleceń nie ma wklejonych zleceń do uporządkowania. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
        action="Wklej zlecenia dnia z aplikacji na dół arkusza zleceń, zapisz i zamknij INTERMAX i uruchom ponownie.",
    )


def raw_orders_in_several_sheets(register: Path, sheets: Sequence[str]) -> Message:
    """Wklejone zlecenia są w więcej niż jednym arkuszu zleceń, więc narzędzie nie wybiera, który porządkować."""

    return Message(
        code="SUROWE_ZLECENIA_W_KILKU_ARKUSZACH",
        dad_file="order_register",
        what=f"Wklejone zlecenia są w więcej niż jednym arkuszu zleceń. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusze {', '.join(sheets)}",
        action=(
            "Zostaw wklejone zlecenia tylko na dole jednego arkusza zleceń, a z pozostałych je usuń. Zapisz i zamknij "
            "INTERMAX i uruchom ponownie."
        ),
    )


def raw_order_above_ordered(register: Path, sheet: str, row: int, ordered_row: int) -> Message:
    """Wiersz z wyglądem wklejonego zlecenia stoi nad uporządkowanym wierszem, więc nie jest na dole arkusza."""

    return Message(
        code="SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
        dad_file="order_register",
        what=(
            f"Wiersz {row} wygląda jak wklejone zlecenie, ale stoi nad uporządkowanym wierszem {ordered_row}. "
            f"{_UNCHANGED}"
        ),
        where=f"{file_label(register)}, arkusz {sheet}, wiersz {row}",
        action=(
            "Przenieś wklejone zlecenia na dół arkusza zleceń, pod ostatni uporządkowany wiersz. Jeśli wiersz "
            f"{row} jest już uporządkowany, nadaj mu czcionkę {ORDERED_FONT} {ORDERED_SIZE}. Zapisz i zamknij INTERMAX i uruchom ponownie."
        ),
    )


def raw_order_without_value(register: Path, sheet: str, row: int, column: str, *, worker: bool) -> Message:
    """Wklejone zlecenie bez daty z godziną albo bez Wykonawcy (``worker``) w komórce ``column`` wiersza ``row``."""

    missing = "Wykonawcy" if worker else "daty z godziną"
    entered = "Wykonawcę" if worker else "datę z godziną"
    return Message(
        code="SUROWE_ZLECENIE_BEZ_WYKONAWCY" if worker else "SUROWE_ZLECENIE_BEZ_DATY",
        dad_file="order_register",
        what=f"Wklejone zlecenie w wierszu {row} nie ma {missing} w kolumnie {column}. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}, komórka {column}{row}",
        action=f"Wpisz {entered} w komórce {column}{row}, zapisz i zamknij INTERMAX i uruchom ponownie.",
    )


def several_days(register: Path, sheet: str, days: Sequence[date], first_row: int, last_row: int) -> Message:
    """Wklejone zlecenia są z więcej niż jednego dnia."""

    return Message(
        code="WKLEJENIE_Z_KILKU_DNI",
        dad_file="order_register",
        what=f"Wklejone zlecenia są z więcej niż jednego dnia: {', '.join(map(_day, days))}. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}, {row_range(first_row, last_row)}",
        action=(
            "Zostaw na dole arkusza zleceń zlecenia jednego dnia, a pozostałe usuń. Zapisz i zamknij INTERMAX i "
            "uruchom ponownie, a następny dzień wklej i uporządkuj osobno."
        ),
    )


def day_already_ordered(register: Path, sheet: str, day: date, first_row: int, last_row: int) -> Message:
    """Wklejone zlecenia są z dnia, który już jest uporządkowany; drugie wklejenie nie dubluje dnia."""

    return Message(
        code="DZIEN_JUZ_UPORZADKOWANY",
        dad_file="order_register",
        what=f"Dzień {_day(day)} jest już uporządkowany. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}, {_pasted(first_row, last_row)}",
        action="Nowe zlecenia na ten dzień dopisz ręcznie, a wklejone usuń.",
    )


def _pasted(first_row: int, last_row: int) -> str:
    return f"{'wklejony' if first_row == last_row else 'wklejone'} {row_range(first_row, last_row)}"


def _day(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def unsupported_shape(register: Path, sheet: str) -> Message:
    """Wklejone zlecenia mają kształt, którego zapis nie przenosi (formuła, scalenie, zakres)."""

    return Message(
        code="NIEOBSLUGIWANY_UKLAD_INTERMAX",
        what=f"Wklejone zlecenia mają układ, którego narzędzie nie porządkuje. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
        action=REPORT_TO_MAINTAINER,
    )


def register_syncing(register: Path) -> Message:
    """System odmawia podmiany INTERMAX po krótkiej ponownej próbie, a Excel go nie trzyma: OneDrive synchronizuje."""

    return Message(
        code="INTERMAX_SYNCHRONIZOWANY",
        what=f"OneDrive jeszcze synchronizuje INTERMAX. {_UNCHANGED}",
        where=file_label(register),
        action="Spróbuj za chwilę: poczekaj, aż OneDrive skończy synchronizację, i uruchom ponownie.",
    )


def write_check_failed(register: Path) -> Message:
    """Sprawdzenie zapisu wykryło różnicę poza uporządkowanym dniem; INTERMAX nie został podmieniony."""

    return Message(
        code="ZAPIS_INTERMAX_NIEZGODNY",
        what=f"Sprawdzenie zapisu wykazało różnicę, więc zapis został odrzucony. {_UNCHANGED}",
        where=file_label(register),
        action=REPORT_TO_MAINTAINER,
    )


def register_write_failed(register: Path) -> Message:
    """Nie dało się zapisać pliku tymczasowego obok INTERMAX albo podmienić INTERMAX z innego powodu niż Excel i
    OneDrive, np. brak miejsca na dysku; INTERMAX nie został podmieniony."""

    return Message(
        code="ZAPIS_INTERMAX_NIEUDANY",
        what=f"Nie udało się zapisać INTERMAX. {_UNCHANGED}",
        where=file_label(register),
        action=(
            "Sprawdź, czy na dysku jest wolne miejsce, i uruchom ponownie. "
            "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def copy_failed(directory: Path) -> Message:
    """Nie powstała Kopia INTERMAX, więc INTERMAX nie został podmieniony."""

    return Message(
        code="KOPIA_INTERMAX_NIEUDANA",
        what=f"Nie udało się zrobić Kopii INTERMAX. {_UNCHANGED}",
        where=folder_label(directory),
        action=(
            "Sprawdź, czy na dysku jest wolne miejsce, i uruchom ponownie. "
            "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    )


def old_copies_kept(directory: Path) -> Message:
    """Ostrzeżenie: INTERMAX jest uporządkowany, ale starsze Kopie INTERMAX nie zostały usunięte."""

    return Message(
        code="STARE_KOPIE_INTERMAX",
        what="INTERMAX został uporządkowany, ale nie udało się usunąć starszych Kopii INTERMAX.",
        where=folder_label(directory),
        action=(
            "Nie musisz nic robić teraz. Jeśli któraś Kopia INTERMAX jest otwarta w Excelu, zamknij ją. "
            "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
        ),
    )


_AGAIN = "przywróć kopię jeszcze raz"
_IF_IT_RETURNS = "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."


def copies_unreadable(directory: Path) -> Message:
    """Folderu Kopii INTERMAX nie da się odczytać: Konfiguracja nie pokaże Kopii, a przywrócenie nie zacznie."""

    return Message(
        code="KOPIE_INTERMAX_NIEDOSTEPNE",
        what=f"Nie można teraz odczytać folderu Kopii INTERMAX. {_UNCHANGED}",
        where=folder_label(directory),
        action=f"Odśwież Konfigurację za chwilę. {_IF_IT_RETURNS}",
    )


def copy_missing(directory: Path, name: str) -> Message:
    """Wybranej Kopii INTERMAX nie ma już w folderze Kopii (np. usunęło ją nowsze Uporządkowanie)."""

    return Message(
        code="BRAK_KOPII_INTERMAX",
        what=f"Tej Kopii INTERMAX już nie ma. {_UNCHANGED}",
        where=f"{folder_label(directory)}, {name}",
        action="Odśwież Konfigurację i wybierz kopię z listy.",
    )


def copy_unusable(error: WorkbookError) -> Message:
    """Wybranej Kopii INTERMAX nie da się odczytać; ``error`` mówi dlaczego."""

    match error.problem:
        case Problem.MISSING:
            return copy_missing(error.path.parent, error.path.name)
        case Problem.OPEN_IN_EXCEL:
            return Message(
                code="KOPIA_INTERMAX_OTWARTA",
                what=f"Ta Kopia INTERMAX jest otwarta w Excelu. {_UNCHANGED}",
                where=file_label(error.path),
                action=f"Zamknij ją w Excelu bez zapisywania zmian, potem {_AGAIN}.",
            )
        case Problem.INACCESSIBLE | Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return Message(
                code="KOPIA_INTERMAX_NIEDOSTEPNA",
                what=f"Nie można teraz odczytać tej Kopii INTERMAX. {_UNCHANGED}",
                where=file_label(error.path),
                action=f"Spróbuj za chwilę: {_AGAIN}. {_IF_IT_RETURNS}",
            )


def copy_damaged(copy: Path) -> Message:
    """Wybrana Kopia INTERMAX nie jest skoroszytem Excela, więc przywrócenie zepsułoby INTERMAX."""

    return Message(
        code="KOPIA_INTERMAX_USZKODZONA",
        what=f"Ta Kopia INTERMAX jest uszkodzona, więc nie została przywrócona. {_UNCHANGED}",
        where=file_label(copy),
        action="Wybierz inną kopię z listy.",
    )


def restore_register_unusable(error: WorkbookError) -> Message:
    """INTERMAX, którego przywrócenie nie może zastąpić: brak pliku, otwarty w Excelu albo niedostępny."""

    match error.problem:
        case Problem.MISSING:
            return Message(
                code="PRZYWRACANIE_BRAK_INTERMAX",
                what=f"Nie znaleziono INTERMAX. {_UNCHANGED}",
                where=file_label(error.path),
                action=f"Wybierz w Ustawieniach właściwy plik INTERMAX, potem {_AGAIN}.",
            )
        case Problem.OPEN_IN_EXCEL:
            return restore_register_open(error.path)
        case Problem.INACCESSIBLE | Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return Message(
                code="PRZYWRACANIE_NIEDOSTEPNY_INTERMAX",
                dad_file="order_register",
                what=(
                    "Nie można teraz odczytać INTERMAX. Plik może być zajęty przez inny program albo czekać na "
                    f"pobranie z OneDrive. {_UNCHANGED}"
                ),
                where=file_label(error.path),
                action=f"Poczekaj, aż OneDrive skończy synchronizację, potem {_AGAIN}. {_IF_IT_RETURNS}",
            )


def restore_register_open(register: Path) -> Message:
    """INTERMAX jest otwarty w Excelu, więc przywrócenie Kopii odmawia."""

    return Message(
        code="PRZYWRACANIE_INTERMAX_OTWARTY",
        dad_file="order_register",
        what=f"INTERMAX jest otwarty w Excelu. {_UNCHANGED}",
        where=file_label(register),
        action=(
            f"Zapisz i zamknij INTERMAX w Excelu, potem {_AGAIN}. Jeśli Excel jest zamknięty, a komunikat wraca, "
            f"usuń z tego samego folderu pozostawiony plik ~${register.name}."
        ),
    )


def restore_register_syncing(register: Path) -> Message:
    """System odmawia podmiany INTERMAX po krótkiej ponownej próbie, a Excel go nie trzyma: OneDrive synchronizuje."""

    return Message(
        code="PRZYWRACANIE_INTERMAX_SYNCHRONIZOWANY",
        what=f"OneDrive jeszcze synchronizuje INTERMAX. {_UNCHANGED}",
        where=file_label(register),
        action=f"Poczekaj, aż OneDrive skończy synchronizację, potem {_AGAIN}.",
    )


def restore_copy_failed(directory: Path) -> Message:
    """Nie powstała Kopia stanu bieżącego, więc przywrócenie niczego nie podmieniło."""

    return Message(
        code="PRZYWRACANIE_KOPIA_NIEUDANA",
        what=f"Nie udało się zrobić Kopii obecnego INTERMAX, więc kopia nie została przywrócona. {_UNCHANGED}",
        where=folder_label(directory),
        action=f"Sprawdź, czy na dysku jest wolne miejsce, potem {_AGAIN}. {_IF_IT_RETURNS}",
    )


def restored_moment_ago(directory: Path) -> Message:
    """Kopia stanu bieżącego z tej samej sekundy już jest: przed chwilą przywrócono kopię, np. w drugiej karcie."""

    return Message(
        code="PRZYWRACANIE_PRZED_CHWILA",
        what="Przed chwilą przywrócono już kopię INTERMAX, więc ta kopia nie została przywrócona.",
        where=folder_label(directory),
        action=f"Odśwież Konfigurację i sprawdź listę kopii. Jeśli nadal trzeba, {_AGAIN}.",
    )


def restore_failed(register: Path) -> Message:
    """Plik tymczasowy obok INTERMAX nie powstał, nie ma bajtów Kopii albo podmiana nie udała się z innego powodu niż
    Excel i OneDrive; INTERMAX nie został podmieniony."""

    return Message(
        code="PRZYWRACANIE_NIEUDANE",
        what=f"Nie udało się przywrócić kopii. {_UNCHANGED}",
        where=file_label(register),
        action=f"Sprawdź, czy na dysku jest wolne miejsce, potem {_AGAIN}. {_IF_IT_RETURNS}",
    )


def old_copies_kept_after_restore(directory: Path) -> Message:
    """Ostrzeżenie: Kopia jest przywrócona, ale starsze Kopie INTERMAX nie zostały usunięte."""

    return Message(
        code="PRZYWRACANIE_STARE_KOPIE",
        what="Kopia została przywrócona, ale nie udało się usunąć starszych Kopii INTERMAX.",
        where=folder_label(directory),
        action=(
            "Nie musisz nic robić teraz. Jeśli któraś Kopia INTERMAX jest otwarta w Excelu, zamknij ją. "
            "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
        ),
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_UNCHANGED}",
        where=_PROCESS,
        action="Uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie.",
    )


def summary_not_shown() -> Message:
    """INTERMAX jest uporządkowany, ale podsumowania nie dało się pokazać."""

    return Message(
        code="BLAD_PODSUMOWANIA",
        what="INTERMAX został uporządkowany, ale nie udało się pokazać podsumowania.",
        where=_PROCESS,
        action="Nie uruchamiaj ponownie. Sprawdź INTERMAX i przekaż ten komunikat osobie utrzymującej narzędzie.",
    )


def plan_not_shown() -> Message:
    """Uporządkowanie nie ma podglądu bez zapisu; rdzeń wymaga Komunikatu na każdy rodzaj zakończenia."""

    return Message(
        code="BLAD_PLANU",
        what=f"Nie udało się pokazać planu. {_UNCHANGED}",
        where=_PROCESS,
        action=REPORT_TO_MAINTAINER,
    )
