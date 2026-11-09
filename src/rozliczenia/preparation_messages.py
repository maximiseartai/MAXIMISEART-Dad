"""Katalog Komunikatów Przygotowania pliku zbiorczego dla taty (zasady treści i wyjątek
``invalid_successful_values``: zob. ``message``).

Komunikaty są po polsku, bez żargonu i numerów zleceń, i wskazują wyłącznie plik, arkusz, nagłówek, numer wiersza albo
adres komórki.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from itertools import groupby
from pathlib import Path
from typing import Final, assert_never

from .message import IF_ERROR_RETURNS, Message, file_label, folder_label, refer_if
from .period_folder import PeriodFolderLookupError, month_folder_label
from .text import plural, row_range
from . import workbook_messages
from .workbook_files import WORKER_HEADER, LayoutFault, MergedCells, MissingHeader, WorkbookError
from .workbook_messages import DadWorkbook, WorkbookMessages

# Napisy Decyzji taty o niepełnym okresie; jej Komunikat to ``incomplete_period``, odmowa ``incomplete_period_refused``.
INCOMPLETE_PERIOD_QUESTION: Final = "Kontynuować mimo niepełnego okresu?"
# Liczby zleceń na dzień okresu, w Decyzji i w podsumowaniu; etykieta dnia to np. „wt 08.09.2026”.
ORDERS_PER_DAY: Final = "Zlecenia na dzień"
_NOTHING_CREATED: Final = "Nie utworzono żadnego pliku."
_STAGING_LEFT: Final = "Obok Folderu okresu został folder tymczasowy, którego nie udało się usunąć."


def period_file_exists(period_directory: Path, filename: str) -> Message:
    """Nienadpisywanie: plik okresu już istnieje w Folderze okresu."""

    return Message(
        code="PLIK_OKRESU_ISTNIEJE",
        what=f"Plik tego okresu już istnieje, więc nie został nadpisany. {_NOTHING_CREATED}",
        where=f"{folder_label(period_directory)}, plik {filename}",
        action=(
            "Sprawdź, czy wybrano właściwy okres. Jeśli plik ma powstać od nowa, "
            "przenieś albo usuń istniejący plik i uruchom ponownie."
        ),
    )


def invalid_period_token(token: str) -> Message:
    """Token okresu nie opisuje przedziału od wtorku do poniedziałku."""

    return Message(
        code="ZLY_TOKEN_OKRESU",
        what="Okres nie ma postaci dd_dd_mm_rrrr od wtorku do poniedziałku.",
        where=f"okres {token!r}",
        action=(
            "Wpisz okres jak w nazwie folderu, np. 08_14_09_2026 (wtorek 8, poniedziałek 14 września 2026). "
            "Na przełomie miesięcy miesiąc i rok są z poniedziałku, np. 27_02_11_2026 "
            "(wtorek 27 października – poniedziałek 2 listopada 2026)."
        ),
    )


def template_unusable(error: WorkbookError) -> Message:
    return workbook_messages.unusable(error, _TEMPLATE)


def _template_missing(template_path: Path) -> Message:
    return Message.to_maintainer(
        code="BRAK_WZORCA",
        what=f"Nie znaleziono wzorca, z którego powstają pliki okresu. {_NOTHING_CREATED}",
        where=file_label(template_path),
    )


def _template_open_in_excel(template_path: Path) -> Message:
    """Wzorzec ma obok plik blokady Excela ``~$…``; narzędzie go nie usuwa."""

    return Message(
        code="WZORZEC_OTWARTY",
        what=f"Wzorzec jest otwarty w Excelu. {_NOTHING_CREATED}",
        where=file_label(template_path),
        action=(
            "Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. "
            f"{workbook_messages.lock_hint(template_path, 'uruchom ponownie')}"
        ),
    )


def _template_inaccessible(template_path: Path) -> Message:
    """System nie oddał bajtów wzorca (np. plik zajęty przez inny program albo folder bez dostępu); to nie uszkodzenie.

    Wzorce leżą w ``config`` na dysku C, więc tata rzadko sam usunie przyczynę: Komunikat idzie do Maksa.
    """

    return Message.to_maintainer(
        code="NIEDOSTEPNY_WZORZEC",
        what=(
            f"Nie można teraz odczytać wzorca. Plik może być zajęty przez inny program. {_NOTHING_CREATED}"
        ),
        where=file_label(template_path),
    )


def _template_unreadable(template_path: Path) -> Message:
    return Message.to_maintainer(
        code="USZKODZONY_WZORZEC",
        what=(
            "Nie można odczytać wzorca. Plik jest uszkodzony "
            f"albo nie jest skoroszytem .xlsx. {_NOTHING_CREATED}"
        ),
        where=file_label(template_path),
    )


def _template_without_header(template_path: Path, sheet: str, row: int, header: str) -> Message:
    """Wzorzec nie ma oczekiwanego nagłówka, więc nie wiadomo, gdzie wpisać zlecenia."""

    return Message.to_maintainer(
        code="ZLY_WZORZEC",
        what=(
            f"We wzorcu brakuje nagłówka {header}, więc nie wiadomo, gdzie wpisać zlecenia. "
            f"{_NOTHING_CREATED}"
        ),
        where=f"plik {template_path.name}, arkusz {sheet}, wiersz {row}",
    )


def _template_with_worker_outside_h(template_path: Path, sheet: str, column: str) -> Message:
    """Wzorzec pliku zbiorczego ma WYKONAWCA poza H17, a Przebieg rozliczeń czyta Wykonawcę z H17."""

    worker_column = WORKER_HEADER.column
    header_row = WORKER_HEADER.row
    return Message(
        code="WYKONAWCA_POZA_H",
        what=(
            f"Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie {column} "
            f"zamiast w {worker_column} (wiersz {header_row}). {_NOTHING_CREATED}"
        ),
        where=f"plik {template_path.name}, arkusz {sheet}, wiersz {header_row}",
        action=f"Przenieś WYKONAWCA do kolumny {worker_column} we wzorcu i uruchom ponownie.",
    )


def _template_with_merged_cells(template_path: Path, sheet: str, cell_range: str) -> Message:
    """Komórki wzorca, do których trafiają zlecenia, są scalone."""

    return Message.to_maintainer(
        code="SCALONE_KOMORKI_WZORCA",
        what=(
            "We wzorcu są scalone komórki tam, gdzie trafiają zlecenia, więc nie można ich wpisać. "
            f"{_NOTHING_CREATED}"
        ),
        where=f"plik {template_path.name}, arkusz {sheet}, komórki {cell_range}",
    )


def _template_with_bad_layout(template_path: Path, fault: LayoutFault | None) -> Message:
    """Wzorzec bez nagłówka na swoim miejscu albo ze scalonymi komórkami tam, gdzie trafiają zlecenia."""

    match fault:
        case MissingHeader(sheet=sheet, found_in=str(column)):
            return _template_with_worker_outside_h(template_path, sheet, column)
        case MissingHeader(sheet=sheet, row=row, header=header):
            return _template_without_header(template_path, sheet, row, header)
        case MergedCells(sheet=sheet, cells=cells):
            return _template_with_merged_cells(template_path, sheet, cells)
        case None:
            return _template_unreadable(template_path)
        case _:
            assert_never(fault)


_TEMPLATE = WorkbookMessages(
    missing=_template_missing,
    open_in_excel=_template_open_in_excel,
    inaccessible=_template_inaccessible,
    unreadable=_template_unreadable,
    layout=_template_with_bad_layout,
)


def register_unusable(error: WorkbookError) -> Message:
    return workbook_messages.unusable(error, _REGISTER_MESSAGES)


def register_missing(register_path: Path) -> Message:
    return Message(
        code="BRAK_REJESTRU",
        what=f"Nie znaleziono Rejestru zleceń. {_NOTHING_CREATED}",
        where=file_label(register_path),
        action="Wybierz właściwy plik Rejestru zleceń i uruchom ponownie.",
    )


def _register_unreadable(register_path: Path) -> Message:
    return Message(
        code="USZKODZONY_REJESTR",
        dad_file="order_register",
        what=(
            "Nie można odczytać Rejestru zleceń. Plik jest uszkodzony "
            f"albo nie jest skoroszytem .xlsx. {_NOTHING_CREATED}"
        ),
        where=file_label(register_path),
        action=(
            "Sprawdź, czy Rejestr zleceń otwiera się w Excelu i jest zapisany jako .xlsx, "
            f"zamknij go i uruchom ponownie. {refer_if('Jeśli błąd wraca', request='przekaż to')}"
        ),
    )


_REGISTER = DadWorkbook("Rejestr zleceń", "Rejestru zleceń", "order_register", _NOTHING_CREATED, "uruchom ponownie")
_REGISTER_MESSAGES = WorkbookMessages(
    missing=register_missing,
    open_in_excel=lambda path: workbook_messages.open_in_excel("REJESTR_OTWARTY", path, _REGISTER),
    inaccessible=lambda path: workbook_messages.not_synced("NIEDOSTEPNY_REJESTR", path, _REGISTER),
    unreadable=_register_unreadable,
)


def _header_list(headers: Sequence[str]) -> str:
    return ", ".join(headers)


def register_without_headers(register_path: Path, sheet: str, headers: Sequence[str]) -> Message:
    """Arkusz ze zleceniami nie ma w pierwszym wierszu wszystkich wymaganych nagłówków."""

    single = len(headers) == 1
    noun = "wymaganego nagłówka" if single else "wymaganych nagłówków"
    fix = "nagłówek" if single else "nagłówki"
    return Message(
        code="BRAK_NAGLOWKA_REJESTRU",
        dad_file="order_register",
        what=f"W Rejestrze zleceń brakuje {noun} {_header_list(headers)}. {_NOTHING_CREATED}",
        where=f"plik {register_path.name}, arkusz {sheet}, wiersz 1",
        action=(
            f"Dopisz albo popraw {fix} {_header_list(headers)} w pierwszym wierszu arkusza ze zleceniami, "
            "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
        ),
    )


def register_with_duplicated_headers(register_path: Path, sheet: str, headers: Sequence[str]) -> Message:
    """Wymagany nagłówek występuje w pierwszym wierszu arkusza ze zleceniami więcej niż raz."""

    single = len(headers) == 1
    return Message(
        code="POWTORZONY_NAGLOWEK_REJESTRU",
        dad_file="order_register",
        what=(
            f"W Rejestrze zleceń {'nagłówek' if single else 'nagłówki'} {_header_list(headers)} "
            f"{'występuje' if single else 'występują'} więcej niż raz, "
            f"więc nie wiadomo, z której kolumny brać dane. {_NOTHING_CREATED}"
        ),
        where=f"plik {register_path.name}, arkusz {sheet}, wiersz 1",
        action=(
            f"Zostaw {'nagłówek' if single else 'każdy z nagłówków'} {_header_list(headers)} "
            "tylko w jednej kolumnie, zapisz i zamknij Rejestr zleceń i uruchom ponownie."
        ),
    )


def register_without_data_sheet(register_path: Path, required_headers: Sequence[str]) -> Message:
    """Żaden arkusz Rejestru nie ma wymaganych nagłówków w pierwszym wierszu."""

    return Message(
        code="BRAK_ARKUSZA_ZLECEN",
        dad_file="order_register",
        what=(
            "W Rejestrze zleceń nie znaleziono arkusza ze zleceniami, czyli arkusza "
            f"z wymaganymi nagłówkami w pierwszym wierszu. {_NOTHING_CREATED}"
        ),
        where=f"plik {register_path.name}",
        action=(
            "Sprawdź, czy wybrano właściwy plik Rejestru zleceń. Pierwszy wiersz arkusza "
            f"ze zleceniami musi zawierać nagłówki: {_header_list(required_headers)}."
        ),
    )


def period_orders_in_many_sheets(register_path: Path, sheets: Sequence[str], period: str) -> Message:
    """Zlecenia okresu leżą w więcej niż jednym arkuszu ze zleceniami."""

    return Message(
        code="ZLECENIA_W_WIELU_ARKUSZACH",
        dad_file="order_register",
        what=(
            "Zlecenia tego okresu są w więcej niż jednym arkuszu Rejestru zleceń, "
            f"więc nie wiadomo, który arkusz jest właściwy. {_NOTHING_CREATED}"
        ),
        where=f"plik {register_path.name}, arkusze {', '.join(sheets)}, okres {period}",
        action=(
            "Zostaw zlecenia tego okresu tylko w jednym arkuszu, "
            "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
        ),
    )


def raw_orders_not_ordered(register_path: Path, sheet: str, first_row: int, last_row: int) -> Message:
    """Okres może mieć Surowe zlecenia: wklejone zlecenia na dole arkusza zleceń nie są jeszcze uporządkowane."""

    rows = row_range(first_row, last_row)
    return Message(
        code="SUROWE_ZLECENIA_W_OKRESIE",
        what=(
            "Wklejone zlecenia na dole Rejestru zleceń nie są jeszcze uporządkowane, "
            f"a mogą należeć do tego okresu. {_NOTHING_CREATED}"
        ),
        where=f"{_register_location(register_path, sheet)}, {rows}",
        action="Najpierw uporządkuj INTERMAX w Centrum rozliczeń, potem uruchom ponownie.",
    )


def periods_directory_missing(periods_directory: Path) -> Message:
    """Wybrany folder okresów nie istnieje; narzędzie go nie zakłada."""

    return Message(
        code="BRAK_FOLDERU_OKRESOW",
        what=f"Nie znaleziono folderu okresów. {_NOTHING_CREATED}",
        where=folder_label(periods_directory),
        action=(
            "Wybierz istniejący folder okresów, w którym są foldery poprzednich tygodni, "
            "i uruchom ponownie."
        ),
    )


def folder_inaccessible(folder: Path) -> Message:
    """Folderu okresów albo Folderu okresu nie da się odczytać, np. brak dostępu albo OneDrive nie działa."""

    return Message(
        code="NIEDOSTEPNY_FOLDER",
        what=f"Nie można teraz odczytać folderu. {_NOTHING_CREATED}",
        where=folder_label(folder),
        action="Sprawdź, czy folder otwiera się w Eksploratorze plików i czy OneDrive działa, potem uruchom ponownie.",
    )


def period_folder_lookup_problem(error: PeriodFolderLookupError) -> Message:
    """Układ folderów taty: Folderu okresu nie ma w żadnym miesiącu albo jest w kilku."""

    token = error.period.token
    if not error.locations:
        return Message(
            code="BRAK_FOLDERU_OKRESU",
            what=f"Nie znaleziono folderu {token} w żadnym folderze miesiąca. {_NOTHING_CREATED}",
            where=f"foldery INEA w folderze {error.periods_directory.name}",
            action=f"Załóż folder {token} w folderze INEA właściwego miesiąca i uruchom ponownie.",
        )
    return Message(
        code="POWTORZONY_FOLDER_OKRESU",
        what=(
            f"Folder {token} jest w więcej niż jednym folderze miesiąca, "
            f"więc nie wiadomo, gdzie zapisać pliki. {_NOTHING_CREATED}"
        ),
        where=", ".join(month_folder_label(error.periods_directory, location) for location in error.locations),
        action=f"Zostaw folder {token} tylko w jednym folderze miesiąca: drugi usuń albo zmień mu nazwę. Potem uruchom ponownie.",
    )


_LISTED_ROWS = 10


def _rows_label(row_numbers: Sequence[int]) -> str:
    """Numery wierszy; przy długiej liście tylko pierwsze i liczba pozostałych."""

    if len(row_numbers) == 1:
        return f"wiersz {row_numbers[0]}"
    listed = ", ".join(str(row) for row in row_numbers[:_LISTED_ROWS])
    rest = len(row_numbers) - _LISTED_ROWS
    return f"wiersze {listed}" + (f" i {rest} kolejnych" if rest > 0 else "")


def _register_location(register_path: Path, sheet: str) -> str:
    return f"plik {register_path.name}, arkusz {sheet}"


def rows_without_date(register_path: Path, sheet: str, row_numbers: Sequence[int]) -> Message:
    """Wiersz z danymi bez poprawnej daty leży między pierwszym a ostatnim zleceniem okresu."""

    subject = "jest wiersz z danymi" if len(row_numbers) == 1 else "są wiersze z danymi"
    return Message(
        code="WIERSZ_BEZ_DATY",
        dad_file="order_register",
        what=(
            f"Między zleceniami okresu {subject} bez poprawnej daty w kolumnie DATA GODZ. POCZ. "
            f"{_NOTHING_CREATED}"
        ),
        where=f"{_register_location(register_path, sheet)}, {_rows_label(row_numbers)}",
        action=(
            "Wpisz poprawną datę w kolumnie DATA GODZ. POCZ. we wskazanych wierszach Rejestru zleceń "
            "albo wyczyść wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, i uruchom ponownie."
        ),
    )


@dataclass(frozen=True)
class CellContent:
    """Komórka ``SKUTECZNE`` z wartością inną niż ``tak`` i ``nie``: numer wiersza Rejestru i odczytana zawartość."""

    row_number: int
    value: object


def invalid_successful_values(
    register_path: Path,
    sheet: str,
    column: str,
    empty_rows: Sequence[int],
    other_values: Sequence[CellContent],
) -> Message:
    """Zlecenia okresu bez ``tak`` ani ``nie`` w ``SKUTECZNE``: puste komórki i komórki z inną wartością.

    Wyjątek od reguły katalogu: komórka z inną wartością pokazuje dokładną
    zawartość. Lista jest pełna, a kolejne wiersze grupy są sklejone w zakres.
    """

    count = len(empty_rows) + len(other_values)
    groups: list[str] = []
    if empty_rows:
        groups.append("puste: " + ", ".join(_cell_ranges(column, empty_rows)))
    if other_values:
        labels = [
            f"{cells} („{text}”)"
            for text, same_text in groupby(other_values, key=lambda cell: _shown_content(cell.value))
            for cells in _cell_ranges(column, [cell.row_number for cell in same_text])
        ]
        groups.append("inna wartość: " + ", ".join(labels))
    return Message(
        code="ZLE_SKUTECZNE",
        dad_file="order_register",
        what=f"{count} {plural(count, 'zlecenie okresu nie ma', 'zlecenia okresu nie mają', 'zleceń okresu nie ma')} tak ani nie w SKUTECZNE. {_NOTHING_CREATED}",
        where=f"{_register_location(register_path, sheet)}, {'; '.join(groups)}",
        action=(
            "Wpisz tak albo nie we wskazanych komórkach Rejestru zleceń. "
            "Zapisz i zamknij Rejestr, i uruchom ponownie."
        ),
    )


def _shown_content(value: object) -> str:
    """Zawartość komórki w jednej linii, żeby Komunikat został w trzech liniach."""

    return " ".join(str(value).splitlines())


def _cell_ranges(column: str, row_numbers: Sequence[int]) -> list[str]:
    """Adresy komórek kolumny w kolejności Rejestru; kolejne wiersze są sklejone w zakres, np. ``L3–L5``."""

    labels: list[str] = []
    for _, run in groupby(enumerate(row_numbers), key=lambda item: item[1] - item[0]):
        rows = [row for _, row in run]
        labels.append(f"{column}{rows[0]}" if len(rows) == 1 else f"{column}{rows[0]}–{column}{rows[-1]}")
    return labels


def unknown_workers(
    register_path: Path,
    sheet: str,
    config_path: Path,
    workers: Sequence[tuple[str, Sequence[int]]],
) -> Message:
    """Zlecenie skuteczne ma wykonawcę spoza konfiguracji wykonawców Przebiegu rozliczeń.

    ``workers`` to pary: identyfikator wykonawcy i numery wierszy Rejestru z tym wykonawcą.
    """

    identifiers = ", ".join(identifier for identifier, _ in workers)
    subject = (
        "Zlecenie skuteczne ma wykonawcę"
        if len(workers) == 1 and len(workers[0][1]) == 1
        else "Zlecenia skuteczne mają wykonawców"
    )
    rows = "; ".join(f"{identifier}: {_rows_label(row_numbers)}" for identifier, row_numbers in workers)
    return Message(
        code="NIEZNANY_WYKONAWCA",
        dad_file="order_register",
        what=f"{subject} spoza konfiguracji wykonawców: {identifiers}. {_NOTHING_CREATED}",
        where=f"{_register_location(register_path, sheet)}, {rows}",
        action=(
            f"Dopisz identyfikator wykonawcy do konfiguracji wykonawców ({config_path.name}), "
            "tej samej co w Przebiegu rozliczeń, albo popraw WYKONAWCA we wskazanych wierszach "
            "Rejestru zleceń. Zapisz i zamknij Rejestr, i uruchom ponownie."
        ),
    )


def no_period_orders(register_path: Path, sheet: str, period: str) -> Message:
    """W Rejestrze nie ma żadnego zlecenia z wybranego okresu."""

    return Message(
        code="BRAK_ZLECEN_OKRESU",
        dad_file="order_register",
        what=f"W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu. {_NOTHING_CREATED}",
        where=f"{_register_location(register_path, sheet)}, okres {period}",
        action=(
            "Sprawdź, czy wybrano właściwy okres i czy eksport zleceń do Rejestru został "
            "zrobiony i zapisany, i uruchom ponownie."
        ),
    )


def too_few_zero_rows(
    collective_filename: str,
    successful_count: int,
    zero_row_count: int,
    first_row_without_zeros: int,
) -> Message:
    """Ostrzeżenie: Zleceń skutecznych jest więcej niż wierszy Wzorca pliku zbiorczego z zerami."""

    last_row = first_row_without_zeros + successful_count - zero_row_count - 1
    rows = row_range(first_row_without_zeros, last_row)
    return Message(
        code="MALO_WIERSZY_Z_ZERAMI",
        what=(
            f"Zleceń skutecznych: {successful_count}, wierszy przygotowanych zerami we Wzorcu pliku "
            f"zbiorczego: {zero_row_count}. Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości."
        ),
        where=f"plik {collective_filename}, {rows}",
        action=(
            "Sprawdź te wiersze jak pozostałe: narzędzie wpisało w nich ilości tak samo, a puste komórki liczą się "
            "jak 0. "
            f"{refer_if('Jeśli zdarza się to często', request='przekaż to', then=', żeby dodała wiersze z zerami we Wzorcu pliku zbiorczego')}"
        ),
    )


def unknown_devices(collective_filename: str, row_numbers: Sequence[int]) -> Message:
    """Ostrzeżenie: Reguły ilości nie znają składnika ``URZĄDZENIA``, więc wiersz ma tylko ilości od niego niezależne."""

    return Message(
        code="NIEZNANE_URZADZENIA",
        what=(
            "Narzędzie nie zna urządzenia z kolumny URZĄDZENIA, więc w tych wierszach Pliku zbiorczego wpisało "
            "tylko ilości niezależne od urządzeń (V, T i N)."
        ),
        where=f"plik {collective_filename}, {_rows_label(row_numbers)}",
        action=(
            "Uzupełnij pozostałe ilości w tych wierszach ręcznie przed Przebiegiem rozliczeń. "
            f"{refer_if('Jeśli to nowe urządzenie, które będzie wracać', request='powiedz o nim')}"
        ),
    )


def rows_from_description(collective_filename: str, row_numbers: Sequence[int]) -> Message:
    """Ostrzeżenie: wiersze rozliczane z opisu (prewencja, niedostępność usług, puste ``URZĄDZENIA``) bez ilości."""

    return Message(
        code="WIERSZE_Z_OPISU",
        what=(
            "Te wiersze Pliku zbiorczego rozlicza się z opisu technika (prewencja, niedostępność usług albo puste "
            "URZĄDZENIA), więc narzędzie nie wpisało w nich żadnych ilości."
        ),
        where=f"plik {collective_filename}, {_rows_label(row_numbers)}",
        action=(
            "Wpisz ilości w tych wierszach według opisu technika w CZYNNOŚCI ZREALIZOWANE przed Przebiegiem "
            "rozliczeń."
        ),
    )


def columns_from_description(collective_filename: str, columns: Sequence[str]) -> Message:
    """Ostrzeżenie zawsze po Planowaniu: kolumn z opisu technika (``columns``) Reguły ilości nie wypełniają."""

    return Message(
        code="KOLUMNY_Z_OPISU",
        what="Ilości, które wynikają z opisu technika (CZYNNOŚCI ZREALIZOWANE), narzędzie zostawia do uzupełnienia.",
        where=f"plik {collective_filename}, kolumny {', '.join(columns[:-1])} i {columns[-1]}",
        action=(
            "Przejrzyj opis technika w każdym wierszu Pliku zbiorczego i uzupełnij ilości w tych kolumnach przed "
            "Przebiegiem rozliczeń."
        ),
    )


# Dzień tygodnia w dopełniaczu, z przyimkiem (``date.weekday()``: 0 = poniedziałek).
_FROM_WEEKDAY = ("z poniedziałku", "z wtorku", "ze środy", "z czwartku", "z piątku", "z soboty", "z niedzieli")


def incomplete_period(
    register_path: Path, sheet: str, period: str, last_order_day: date, monday: date
) -> Message:
    """Ostrzeżenie: ostatnie zlecenie okresu jest sprzed poniedziałku okresu."""

    return Message(
        code="NIEPELNY_OKRES",
        what=(
            f"Ostatnie zlecenie okresu jest {_FROM_WEEKDAY[last_order_day.weekday()]} {last_order_day:%d.%m.%Y}, "
            f"a okres kończy się w poniedziałek {monday:%d.%m.%Y}. Rejestr zleceń może nie mieć jeszcze "
            "wszystkich zleceń tego okresu."
        ),
        where=f"{_register_location(register_path, sheet)}, okres {period}",
        action=(
            "Sprawdź liczby zleceń na dzień. Jeśli brakuje zleceń, przerwij, uzupełnij eksport w Rejestrze "
            "zleceń, zapisz go i uruchom ponownie. Jeśli okres jest pełny, kontynuuj."
        ),
    )


def incomplete_period_refused(period: str, continue_hint: str) -> Message:
    """Tata nie zgodził się kontynuować po ostrzeżeniu o niepełnym okresie."""

    return Message(
        code="PRZERWANO_NIEPELNY_OKRES",
        dad_file="order_register",
        what=f"Przerwano z powodu niepełnego okresu, zgodnie z odpowiedzią. {_NOTHING_CREATED}",
        where=f"okres {period}",
        action=(
            "Uzupełnij eksport zleceń w Rejestrze zleceń, zapisz go, zamknij i uruchom ponownie. "
            f"Jeśli okres jest pełny, {continue_hint}."
        ),
    )


def write_failed(period_directory: Path) -> Message:
    """Zapis lub publikacja plików okresu nie powiodły się."""

    return Message(
        code="BLAD_ZAPISU",
        what=f"Nie udało się zapisać plików okresu. {_NOTHING_CREATED}",
        where=folder_label(period_directory),
        action=(
            "Sprawdź, czy folder jest dostępny i czy pliki okresu nie są otwarte, "
            f"i uruchom ponownie. {IF_ERROR_RETURNS}"
        ),
    )


def staging_left(message: Message, periods_directory: Path, staging_prefix: str) -> Message:
    """Zatrzymanie ``message`` przy zapisie, po którym obok Folderu okresu został folder tymczasowy.

    Folderu nie dało się usunąć, np. bo jego pliki trzyma OneDrive. Komunikat podaje stały początek nazwy, a nie
    losową nazwę folderu, żeby ten sam problem w kolejnym Uruchomieniu miał ten sam odcisk problemu (Powtórka).
    """

    what = (
        message.what.replace(_NOTHING_CREATED, _STAGING_LEFT)
        if _NOTHING_CREATED in message.what
        else f"{message.what} {_STAGING_LEFT}"
    )
    return replace(
        message,
        what=what,
        action=(
            f"Usuń z folderu {periods_directory.name} każdy folder, którego nazwa zaczyna się od „{staging_prefix}”. "
            "To foldery tymczasowe, nie Folder okresu. "
            f"Jeśli któregoś nie daje się usunąć, odczekaj chwilę. {message.action}"
        ),
    )


def write_failed_with_file_left(period_directory: Path, filename: str) -> Message:
    """Publikacja nie powiodła się, a już opublikowanego pliku okresu nie udało się usunąć."""

    return Message(
        code="BLAD_ZAPISU_POZOSTAL_PLIK",
        what="Zapisano tylko jeden z dwóch plików okresu i nie udało się go usunąć.",
        where=f"{folder_label(period_directory)}, plik {filename}",
        action=(
            "Usuń wskazany plik, bo bez drugiego pliku okresu jest niepełny, i uruchom ponownie. "
            "Jeśli nie daje się go usunąć, odczekaj chwilę. "
            f"{refer_if('Jeśli błąd wraca', request='przekaż komunikat')}"
        ),
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_NOTHING_CREATED}",
        where="Przygotowanie pliku zbiorczego",
        action=f"Uruchom ponownie. {IF_ERROR_RETURNS}",
    )


def summary_not_shown() -> Message:
    """Pliki okresu powstały, ale podsumowania nie dało się pokazać; treść wyjątku nie trafia do taty."""

    return Message.to_maintainer(
        code="BLAD_PODSUMOWANIA",
        what="Pliki okresu powstały, ale nie udało się pokazać podsumowania.",
        where="Przygotowanie pliku zbiorczego",
        before="Nie uruchamiaj ponownie: oba pliki okresu już są.",
        check="Folder okresu",
    )


def plan_not_shown() -> Message:
    """DRY-RUN skończył się, ale planu nie dało się pokazać; nic nie zapisano."""

    return Message.to_maintainer(
        code="BLAD_PLANU",
        what="Nie udało się pokazać planu. Nic nie zapisano.",
        where="Przygotowanie pliku zbiorczego",
    )
