"""Katalog Komunikatów Przebiegu rozliczeń: zatrzymania i ostrzeżenia podsumowania dla taty.

Każda fabryka zwraca Komunikat (``message.Message``) w trzech częściach: co się
stało, gdzie, co zrobić. Zatrzymanie to ``raise StopError(fabryka(...))``.
Części nie zawierają pełnych ścieżek ani treści wierszy: wskazują tylko nazwę
pliku, folder okresu, kolumnę, numer wiersza albo Wykonawcę z konfiguracji wykonawców.
Wyjątek (ADR 0015): ``unmapped_worker`` i ``unmapped_worker_warning`` podają w „co się
stało” identyfikator z kolumny WYKONAWCA spoza konfiguracji, bez numeru wiersza.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final

from .message import IF_ERROR_RETURNS, OTHERWISE_REFER, Message, file_label, folder_label
from .period_folder import FolderNotNamedAfterPeriod, NotPeriodToken, PeriodFolderError, collective_file_name_with
from . import workbook_messages
from .workbook_files import WORKER_HEADER, LayoutFault, WorkbookError
from .workbook_messages import DadWorkbook, WorkbookMessages
from .worker_config import ContentProblem, SameWorkerFile, WorkerConfigError

_NOTHING_CREATED: Final = "Nie utworzono żadnego pliku pracownika."
_STAGING_LEFT: Final = "W Folderze okresu został folder tymczasowy, którego nie udało się usunąć."
_RETRY: Final = f"Uruchom ponownie. {IF_ERROR_RETURNS}"
_PREVIEW_PROBLEMS: Final = "Uruchom Podgląd bez zapisu: lista problemów pokaże wiersze."
_SAVE_AND_RETRY: Final = "Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie."
_FIX_UNMAPPED_WORKER: Final = (
    f"Popraw WYKONAWCĘ w kolumnie {WORKER_HEADER.column} albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
    "do konfiguracji wykonawców."
)
_LEGACY_WORKER_TEMPLATE_NAME: Final = "placeholder.xlsx"


def collective_file_unusable(error: WorkbookError) -> Message:
    """Plik zbiorczy, którego nie da się użyć; ``error`` mówi dlaczego."""

    return workbook_messages.unusable(error, _COLLECTIVE_FILE_MESSAGES)


def collective_file_missing(source: Path) -> Message:
    return Message(
        code="BRAK_PLIKU_ZBIORCZEGO",
        what=f"Nie znaleziono Pliku zbiorczego tego okresu. {_NOTHING_CREATED}",
        where=file_label(source),
        action=(
            "Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod tą nazwą, i uruchom ponownie. "
            "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy."
        ),
    )


def collective_file_invalid(source: Path, error: PeriodFolderError) -> Message:
    """Nazwa albo folder Pliku zbiorczego nie pasują do Folderu okresu; ``error`` mówi, co jest nie tak."""

    match error.problem:
        case "internal_settlement":
            detail = "Plik Rozliczenie wew. jest poza zakresem tego procesu."
        case "not_collective_file_name":
            detail = f"Wybierz plik nazwany dokładnie: {collective_file_name_with('{dd}_{dd}_{mm}_{rrrr}')}."
        case NotPeriodToken(token=token):
            detail = (
                f"Okres {token} w nazwie pliku nie jest okresem od wtorku do poniedziałku "
                "(przykład okresu: 08_14_09_2026)."
            )
        case FolderNotNamedAfterPeriod(token=token):
            detail = f"Folder pliku musi nazywać się tak samo jak okres: {token}."
    return _collective_file_unfit(source, detail)


def _collective_file_unfit(source: Path, detail: str) -> Message:
    """Nazwa, folder albo układ Pliku zbiorczego; ``detail`` mówi, co jest nie tak."""

    return Message(
        code="ZLY_PLIK_ZBIORCZY",
        dad_file="collective_file",
        what=f"Plik zbiorczy nie nadaje się do Przebiegu rozliczeń. {detail}",
        where=file_label(source),
        action=f"Popraw Plik zbiorczy w Excelu. {_SAVE_AND_RETRY} {IF_ERROR_RETURNS}",
    )


def _collective_file_unreadable(source: Path) -> Message:
    """Plik zbiorczy nie daje się odczytać jako skoroszyt .xlsx."""

    return _collective_file_unfit(
        source,
        f"Nie można odczytać Pliku zbiorczego {source.name}. Sprawdź, czy plik otwiera się w Excelu i nie jest uszkodzony.",
    )


def _collective_file_without_worker_header(source: Path) -> Message:
    """Plik zbiorczy nie ma nagłówka WYKONAWCA w H17, skąd Przebieg rozliczeń czyta Wykonawcę."""

    return _collective_file_unfit(
        source, f"W wierszu {WORKER_HEADER.row} nie znaleziono nagłówka WYKONAWCA w kolumnie {WORKER_HEADER.column}."
    )


_COLLECTIVE_FILE = DadWorkbook("Plik zbiorczy", "Pliku zbiorczego", "collective_file", _NOTHING_CREATED, "uruchom ponownie")
_COLLECTIVE_FILE_MESSAGES = WorkbookMessages(
    missing=collective_file_missing,
    open_in_excel=lambda source: workbook_messages.open_in_excel("PLIK_ZBIORCZY_OTWARTY", source, _COLLECTIVE_FILE),
    inaccessible=lambda source: workbook_messages.not_synced("NIEDOSTEPNY_PLIK_ZBIORCZY", source, _COLLECTIVE_FILE),
    unreadable=_collective_file_unreadable,
    layout=lambda source, _fault: _collective_file_without_worker_header(source),
)


def worker_settlements_exist(target_directory: Path) -> Message:
    """Nienadpisywanie: Folder rozliczeń pracowników okresu już istnieje."""

    return Message(
        code="FOLDER_ROZLICZEN_ISTNIEJE",
        what=f"Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=(
            "Sprawdź, czy wybrano właściwy okres. Rozliczenia pracowników tego okresu już są w Folderze okresu. "
            "Jeśli trzeba je utworzyć od nowa, najpierw przenieś Folder rozliczeń pracowników poza Folder okresu i uruchom ponownie."
        ),
    )


def worker_config_problem(config_path: Path, error: WorkerConfigError) -> Message:
    """Konfiguracji wykonawców nie da się użyć; Komunikat mówi, czy pliku brak, czy co jest nie tak z jego treścią."""

    match error.reason:
        case "inaccessible":
            return _worker_config_inaccessible(config_path)
        case "missing":
            detail = "Nie można odczytać pliku konfiguracji."
        case content:
            detail = _worker_config_content(content)
    return Message.to_maintainer(
        code="ZLA_KONFIGURACJA_WYKONAWCOW",
        what=f"Konfiguracja wykonawców jest niepoprawna. {detail}",
        where=file_label(config_path),
    )


def _worker_config_content(problem: ContentProblem) -> str:
    """Co jest nie tak z treścią konfiguracji wykonawców, bez ścieżki pliku."""

    match problem:
        case "not_utf8":
            return "Plik nie jest zapisany w kodowaniu UTF-8."
        case "not_yaml":
            return "Plik nie jest poprawnym YAML."
        case "not_mapping":
            return "Konfiguracja musi być mapą z sekcją workers."
        case "unsupported_version":
            return "Nieobsługiwana wersja konfiguracji."
        case "no_workers":
            return "Konfiguracja workers musi zawierać co najmniej jeden wpis."
        case "not_text_entry":
            return "Konfiguracja zawiera niepoprawny identyfikator lub nazwę pracownika."
        case "empty_entry":
            return "Konfiguracja zawiera pusty identyfikator lub nazwę pracownika."
        case "repeated_id":
            return "Konfiguracja zawiera powtórzony identyfikator pracownika."
        case "invalid_worker_name":
            return "Konfiguracja zawiera nazwę pracownika nieprawidłową dla nazwy pliku."
        case "too_long_worker_name":
            return "Konfiguracja zawiera nazwę pracownika zbyt długą dla nazwy pliku."
        case SameWorkerFile(first=first, second=second):
            return f"Dwóch identyfikatorów wskazuje ten sam plik pracownika: {first} / {second}"


def _worker_config_inaccessible(config_path: Path) -> Message:
    """System nie oddał konfiguracji wykonawców (np. plik zajęty przez inny program albo bez dostępu); to nie zła treść.

    Konfiguracja leży w ``config`` na dysku C jak Wzorce, więc tata rzadko sam usunie przyczynę: Komunikat idzie do Maksa.
    """

    return Message.to_maintainer(
        code="NIEDOSTEPNA_KONFIGURACJA_WYKONAWCOW",
        what="Nie można teraz odczytać konfiguracji wykonawców. Plik może być zajęty przez inny program.",
        where=file_label(config_path),
    )


def worker_template_unusable(error: WorkbookError) -> Message:
    """Wzorzec rozliczenia pracownika nie przeszedł Sprawdzania; ``error`` mówi dlaczego."""

    return workbook_messages.unusable(error, _WORKER_TEMPLATE_MESSAGES)


def _worker_template_unusable(template_path: Path, detail: str, otherwise: str = OTHERWISE_REFER) -> Message:
    """Jeden Komunikat o Wzorcu rozliczenia pracownika; ``detail`` mówi, co jest nie tak."""

    return Message(
        code="ZLY_WZORZEC_PRACOWNIKA",
        what=f"Nie można użyć Wzorca rozliczenia pracownika. {detail}",
        where=file_label(template_path),
        action=f"Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania zmian i uruchom ponownie. {otherwise}",
    )


def _worker_template_missing(template_path: Path) -> Message:
    """Wzorca rozliczenia pracownika nie ma; obok może leżeć jego dawna nazwa ``placeholder.xlsx``."""

    detail = f"Nie znaleziono Wzorca rozliczenia pracownika: {template_path.name}."
    if template_path.with_name(_LEGACY_WORKER_TEMPLATE_NAME).is_file():
        detail += f" Zmień nazwę pliku {_LEGACY_WORKER_TEMPLATE_NAME} w tym samym folderze na „{template_path.name}”."
    return _worker_template_unusable(template_path, detail)


_WORKER_TEMPLATE_UNREADABLE: Final = "Nie można odczytać Wzorca rozliczenia pracownika."
_WORKER_TEMPLATE_MESSAGES = WorkbookMessages(
    missing=_worker_template_missing,
    open_in_excel=lambda path: _worker_template_unusable(
        path,
        "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany.",
        workbook_messages.lock_hint(path, "uruchom ponownie"),
    ),
    inaccessible=lambda path: _worker_template_unusable(path, _WORKER_TEMPLATE_UNREADABLE),
    unreadable=lambda path: _worker_template_unusable(path, _WORKER_TEMPLATE_UNREADABLE),
    layout=lambda path, _fault: _worker_template_unusable(
        path, f"Wzorzec rozliczenia pracownika nie ma nagłówka WYKONAWCA w {WORKER_HEADER.column}:{WORKER_HEADER.row}."
    ),
    has_data=lambda path: _worker_template_unusable(
        path, "Wzorzec rozliczenia pracownika zawiera dane i nie może być użyty jako wzór."
    ),
)


def unmapped_worker(source: Path, workers: Sequence[str]) -> Message:
    """RUN: identyfikatory ``workers`` z kolumny WYKONAWCA Pliku zbiorczego nie mają wpisu w konfiguracji wykonawców."""

    subject = "jest WYKONAWCA" if len(workers) == 1 else "są WYKONAWCY"
    return Message(
        code="NIEZNANY_WYKONAWCA",
        dad_file="collective_file",
        what=f"W Pliku zbiorczym {subject} spoza konfiguracji wykonawców: {', '.join(workers)}. {_NOTHING_CREATED}",
        where=f"{file_label(source)}, kolumna {WORKER_HEADER.column}",
        action=f"{_FIX_UNMAPPED_WORKER} {_SAVE_AND_RETRY}",
    )


def rows_without_worker(source: Path) -> Message:
    """RUN: Wiersz danych bez WYKONAWCY."""

    return Message(
        code="WIERSZE_BEZ_WYKONAWCY",
        dad_file="collective_file",
        what=f"Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ. {_NOTHING_CREATED}",
        where=f"{file_label(source)}, kolumna {WORKER_HEADER.column}",
        action=(
            f"{_PREVIEW_PROBLEMS} Wpisz WYKONAWCĘ w kolumnie {WORKER_HEADER.column} tych wierszy. {_SAVE_AND_RETRY}"
        ),
    )


def unmapped_worker_warning(source: Path, worker: str) -> Message:
    """DRY-RUN: identyfikator ``worker`` z kolumny WYKONAWCA Pliku zbiorczego nie ma wpisu w konfiguracji wykonawców."""

    return Message(
        code="BRAK_MAPOWANIA",
        what=f"Nieznany identyfikator WYKONAWCA: {worker}. Nie ma go w konfiguracji wykonawców.",
        where=file_label(source),
        action=f"{_FIX_UNMAPPED_WORKER} {_SAVE_AND_RETRY}",
    )


def row_without_worker_warning(source: Path, row: int) -> Message:
    """DRY-RUN: Wiersz danych ``row`` bez WYKONAWCY."""

    return Message(
        code="BRAK_WYKONAWCY",
        what=f"Wiersz {row} ma dane, ale nie ma wykonawcy w kolumnie {WORKER_HEADER.column}.",
        where=file_label(source),
        action=f"Wpisz WYKONAWCĘ w kolumnie {WORKER_HEADER.column} tego wiersza. {_SAVE_AND_RETRY}",
    )


def worker_file_failed(target_directory: Path, worker_name: str) -> Message:
    return Message(
        code="BLAD_SZABLONU_PRACOWNIKA",
        what=f"Nie udało się przygotować skoroszytu pracownika {worker_name}. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=_RETRY,
    )


def worker_template_unusable_in_saving(target_directory: Path, worker_name: str, error: WorkbookError) -> Message:
    """Wzorzec rozliczenia pracownika zmieniony po Sprawdzaniu, przy skoroszycie pracownika ``worker_name``."""

    def changed(_path: Path, _fault: LayoutFault | None = None) -> Message:
        return worker_file_failed(target_directory, worker_name)

    return workbook_messages.unusable(
        error,
        WorkbookMessages(
            missing=_worker_files_not_copied,
            open_in_excel=_worker_files_not_copied,
            inaccessible=_worker_files_not_copied,
            unreadable=_worker_files_not_copied,
            layout=changed,
            has_data=changed,
        ),
    )


def _worker_files_not_copied(template_path: Path) -> Message:
    return Message(
        code="BLAD_KOPII_WZORCA",
        what=f"Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika. {_NOTHING_CREATED}",
        where=file_label(template_path),
        action=_RETRY,
    )


def publish_failed(target_directory: Path) -> Message:
    return Message(
        code="BLAD_PUBLIKACJI",
        what=f"Nie można opublikować gotowego Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
    )


def write_failed(target_directory: Path) -> Message:
    return Message(
        code="BLAD_ZAPISU",
        what=f"Nie można przygotować Folderu rozliczeń pracowników. {_NOTHING_CREATED}",
        where=folder_label(target_directory),
        action=f"Sprawdź, czy Folder okresu jest dostępny. {_RETRY}",
    )


def staging_left(message: Message, staging_prefix: str) -> Message:
    """Zatrzymanie ``message``, po którym w Folderze okresu został folder tymczasowy.

    Folderu nie dało się usunąć, np. bo jego pliki trzyma OneDrive. Komunikat
    podaje stały początek nazwy, a nie losową nazwę folderu, żeby ten sam
    problem w kolejnym Uruchomieniu miał ten sam odcisk problemu (Powtórka).
    """

    return replace(
        message,
        what=message.what.replace(_NOTHING_CREATED, _STAGING_LEFT),
        action=(
            f"Usuń z Folderu okresu każdy folder, którego nazwa zaczyna się od „{staging_prefix}”. "
            "To foldery tymczasowe, nie Folder rozliczeń pracowników. "
            f"Jeśli któregoś nie daje się usunąć, odczekaj chwilę. {message.action}"
        ),
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_NOTHING_CREATED}",
        where="Przebieg rozliczeń",
        action=_RETRY,
    )


def summary_not_shown() -> Message:
    """Folder rozliczeń pracowników powstał, ale podsumowania nie dało się pokazać."""

    return Message.to_maintainer(
        code="BLAD_PODSUMOWANIA",
        what="Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania.",
        where="Przebieg rozliczeń",
        before="Nie uruchamiaj ponownie: Folder rozliczeń pracowników już jest.",
        check="Folder okresu",
    )


def plan_not_shown() -> Message:
    """DRY-RUN skończył się, ale planu nie dało się pokazać; nic nie zapisano."""

    return Message.to_maintainer(
        code="BLAD_PLANU",
        what="Nie udało się pokazać planu. Nic nie zapisano.",
        where="Przebieg rozliczeń",
    )
