"""Katalog Komunikatów Uzupełnienia pliku zbiorczego: Plik zbiorczy, którego Centrum nie odczytało.

Strona Uzupełnienia tylko czyta Plik zbiorczy, więc każdy Komunikat kończy się odświeżeniem strony, a nie
ponownym Uruchomieniem procesu. Plik otwarty w Excelu nie jest tu problemem (ADR 0016).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from rozliczenia.message import KEEP_ON_DEVICE, OTHERWISE_REFER, Message, file_label
from rozliczenia.workbook_files import WORKER_HEADER, HEADER_ROW, Problem, WorkbookError

_REFRESH: Final = "odśwież stronę"


def collective_file_unusable(error: WorkbookError) -> Message:
    """Plik zbiorczy, którego nie da się odczytać; ``error`` mówi dlaczego."""

    # Bez ``case _``: nowy ``Problem`` bez przypadku mypy odrzuca jako brak ``return``.
    match error.problem:
        case Problem.MISSING:
            return _missing(error.path)
        case Problem.OPEN_IN_EXCEL | Problem.INACCESSIBLE:
            return _inaccessible(error.path)
        case Problem.UNREADABLE | Problem.HAS_DATA:
            return _damaged(error.path)
        case Problem.LAYOUT:
            return _without_worker_header(error.path)


def _missing(source: Path) -> Message:
    return Message(
        code="BRAK_PLIKU_ZBIORCZEGO",
        what="Nie ma Pliku zbiorczego tego okresu.",
        where=file_label(source),
        action=(
            "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy. Jeśli Plik zbiorczy ma inną "
            f"nazwę albo leży w innym folderze, przywróć go pod tą nazwą do Folderu okresu i {_REFRESH}."
        ),
    )


def _inaccessible(source: Path) -> Message:
    """System nie oddał bajtów Pliku zbiorczego (np. zajęty przez inny program albo OneDrive bez sieci)."""

    return Message(
        code="NIEDOSTEPNY_PLIK_ZBIORCZY",
        what=(
            "Nie można teraz odczytać Pliku zbiorczego. Plik może być zajęty przez inny program "
            "albo czekać na pobranie z OneDrive."
        ),
        where=file_label(source),
        action=(
            f"Poczekaj, aż OneDrive skończy synchronizację, i {_REFRESH}. Jeśli komunikat wraca, zapisz i zamknij "
            f"Plik zbiorczy w Excelu i {_REFRESH}."
        ),
    )


def _damaged(source: Path) -> Message:
    """Plik zbiorczy nie daje się odczytać jako skoroszyt .xlsx."""

    return Message(
        code="USZKODZONY_PLIK_ZBIORCZY",
        what="Plik zbiorczy jest uszkodzony albo nie jest skoroszytem Excela.",
        where=file_label(source),
        action=(
            f"Sprawdź, czy Plik zbiorczy otwiera się w Excelu. Jeśli się otwiera, zapisz go w Excelu i {_REFRESH}. "
            f"{OTHERWISE_REFER}"
        ),
    )


def _without_worker_header(source: Path) -> Message:
    """Plik zbiorczy nie ma nagłówka WYKONAWCA w H17, po którym odczyt rozpoznaje układ arkusza."""

    return headers_missing(source, ("WYKONAWCA",), cell=str(WORKER_HEADER))


def headers_missing(source: Path, headers: tuple[str, ...], *, cell: str | None = None) -> Message:
    """W wierszu nagłówków Pliku zbiorczego brakuje nagłówków ``headers``; ``cell`` to komórka jedynego nagłówka."""

    place = f"w komórce {cell}" if cell else f"w wierszu {HEADER_ROW}"
    return Message(
        code="BRAK_NAGLOWKA_PLIKU_ZBIORCZEGO",
        what=f"Brakuje nagłówka w Pliku zbiorczym: {' i '.join(headers)} {place}.",
        where=file_label(source),
        action=f"Przywróć nagłówek w Excelu tak jak w Wzorcu pliku zbiorczego, zapisz plik i {_REFRESH}.",
    )


def only_in_cloud(source: Path) -> Message:
    """Plik zbiorczy jest w OneDrive tylko w chmurze (atrybut „tylko online”), bez kopii na komputerze taty."""

    return Message(
        code="PLIK_ZBIORCZY_W_CHMURZE",
        what="Plik zbiorczy jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.",
        where=file_label(source),
        action=f"{KEEP_ON_DEVICE} i {_REFRESH}.",
    )
