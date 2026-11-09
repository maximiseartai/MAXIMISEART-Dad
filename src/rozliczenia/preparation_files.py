"""Wzorce i pliki okresu w Przygotowaniu pliku zbiorczego.

Moduł bierze oba Wzorce sprawdzone w ``input_checks`` (``PeriodFiles``), ocenia,
czy zlecenia zmieszczą się we wzorcach, i podaje fakty o wierszach Pliku zbiorczego (Planowanie), a potem zapisuje
Rozliczenie wewnętrzne oraz Plik zbiorczy razem do Folderu okresu (Zapisywanie). Planowanie i Zapisywanie
zatrzymują się ``StopError``. Moduł wewnętrzny Przygotowania pliku zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from . import preparation_messages as messages
from . import staged_publication
from .file_state import path_taken
from .message import StopError
from .period_folder import PeriodFolder
from .preparation_plan import CollectiveRow, PeriodOrder
from .quantity_rules import FromDescription, WithoutRule
from .template_file import TemplateFile
from .workbook_files import RegisterRow, WorkbookError
from .workbook_save import WorkbookSaveError
from .write_routes import Route, RouteCounts, TemplateKind


@dataclass(frozen=True)
class PeriodFiles:
    """Oba wzorce po Sprawdzaniu i Folder okresu, w którym powstają oba pliki okresu.

    Planowanie i Zapisywanie używają tych samych Wzorców, które przeszły Sprawdzanie.
    """

    internal_template: TemplateFile
    collective_template: TemplateFile
    folder: PeriodFolder

    @property
    def filenames(self) -> tuple[str, str]:
        """Rozliczenie wewnętrzne i Plik zbiorczy, w kolejności publikacji."""

        return (self.folder.internal_settlement.name, self.folder.collective_file.name)


def ensure_period_files_absent(files: PeriodFiles) -> None:
    """Nienadpisywanie: żaden z dwóch plików okresu nie istnieje jeszcze w Folderze okresu."""

    folder = files.folder
    try:
        for target in (folder.internal_settlement, folder.collective_file):
            if path_taken(target):
                raise StopError(messages.period_file_exists(folder.directory, target.name))
    except OSError as exc:
        raise StopError(messages.folder_inaccessible(folder.directory)) from exc


@dataclass(frozen=True)
class CollectiveFilePlan:
    """Fakty Planowania o Pliku zbiorczym, z numerami jego wierszy (nie wierszy Rejestru zleceń).

    ``rows_without_rule`` mają składnik ``URZĄDZENIA`` nieznany Regułom ilości, a ``rows_from_description`` rozlicza
    się z opisu technika.
    """

    successful_count: int
    zero_row_count: int
    first_row_without_zeros: int
    rows_without_rule: tuple[int, ...]
    rows_from_description: tuple[int, ...]

    @property
    def too_few_zero_rows(self) -> bool:
        """Wzorca pliku zbiorczego nie wydłużamy, więc dolne Zlecenia skuteczne trafiają do wierszy bez zer."""

        return self.successful_count > self.zero_row_count


def plan_period_files(
    files: PeriodFiles, order_count: int, collective_rows: Sequence[CollectiveRow]
) -> CollectiveFilePlan:
    """Planowanie: zlecenia zmieszczą się we wzorcach; scalone komórki w ich wierszach są zatrzymaniem."""

    with _template_stops():
        files.internal_template.plan(order_count)
        collective = files.collective_template.plan(len(collective_rows))
    numbered = list(zip(collective.data_rows, collective_rows, strict=True))
    return CollectiveFilePlan(
        successful_count=len(collective_rows),
        zero_row_count=collective.zero_row_count,
        first_row_without_zeros=collective.first_row_without_zeros,
        rows_without_rule=tuple(number for number, row in numbered if isinstance(row.rule_result, WithoutRule)),
        rows_from_description=tuple(
            number for number, row in numbered if isinstance(row.rule_result, FromDescription)
        ),
    )


def _create_file(template: TemplateFile, target: Path, rows: Sequence[RegisterRow]) -> Route:
    return template.create(target, rows)


@dataclass(frozen=True)
class Disk:
    """Kroki Zapisywania poza publikacją; ``LOCAL_DISK`` to prawdziwe, a sprawdzenie ``verify-publikacja-plikow-okresu``
    podaje własne, żeby prowadzić je na dysku w pamięci bez łatania modułu.

    ``create_file``: plik okresu ``target`` z Wzorca z Wierszami danych i jego droga zapisu (ADR 0008).
    ``staging``: kroki folderu tymczasowego (``staged_publication.Disk``).
    """

    create_file: Callable[[TemplateFile, Path, Sequence[RegisterRow]], Route] = _create_file
    staging: staged_publication.Disk = staged_publication.LOCAL_DISK


LOCAL_DISK: Final = Disk()


def write_period_files(
    files: PeriodFiles,
    orders: Sequence[PeriodOrder],
    collective_rows: Sequence[CollectiveRow],
    *,
    disk: Disk = LOCAL_DISK,
) -> RouteCounts:
    """Zapisywanie: przygotowuje oba pliki w folderze tymczasowym, publikuje je razem i podaje ich drogi zapisu.

    Folder tymczasowy leży obok Folderu okresu. Błąd nie zostawia żadnego z plików ani nowo założonego Folderu
    okresu, chyba że zatrzymanie wskazuje plik, którego nie udało się usunąć. Folder tymczasowy, którego po
    zatrzymaniu nie da się usunąć (np. trzyma jego pliki OneDrive), zostaje, a Komunikat podaje początek jego nazwy,
    jak w Przebiegu rozliczeń. Po publikacji oba pliki już są, więc resztę folderu tymczasowego zostawia bez
    Komunikatu.
    """

    folder = files.folder
    failed = messages.write_failed(folder.directory)

    def publish(staging: Path) -> RouteCounts:
        try:
            return _write_and_publish(staging, files, orders, collective_rows, disk)
        except WorkbookSaveError as exc:
            raise StopError(failed) from exc

    return staged_publication.publish_staged(
        folder.periods_directory,
        folder.period.token,
        publish,
        failed=failed,
        left=lambda message, prefix: messages.staging_left(message, folder.periods_directory, prefix),
        disk=disk.staging,
    )


def _write_and_publish(
    staging: Path,
    files: PeriodFiles,
    orders: Sequence[PeriodOrder],
    collective_rows: Sequence[CollectiveRow],
    disk: Disk,
) -> RouteCounts:
    staged_directory = staging / files.folder.directory.name
    staged_directory.mkdir()
    internal_name, collective_name = files.filenames
    routes = Counter(
        (
            _write_period_file(
                disk,
                files.internal_template,
                staged_directory / internal_name,
                [order.register_row for order in orders],
            ),
            _write_period_file(
                disk,
                files.collective_template,
                staged_directory / collective_name,
                [_with_quantities(row) for row in collective_rows],
            ),
        )
    )
    _publish(staged_directory, files)
    return routes


@contextmanager
def _template_stops() -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(messages.template_unusable(error)) from error


def _write_period_file(
    disk: Disk, template: TemplateFile, target: Path, rows: Sequence[RegisterRow]
) -> tuple[TemplateKind, Route]:
    """Plik z Wzorca z Wierszami danych od pierwszego Wiersza danych, jego rodzaj i droga zapisu (ADR 0008)."""

    with _template_stops():
        return template.kind, disk.create_file(template, target, rows)


def _with_quantities(row: CollectiveRow) -> RegisterRow:
    return replace(row.order.register_row, quantities=row.rule_result.quantities)


def _publish(staged_directory: Path, files: PeriodFiles) -> None:
    """Przenosi oba pliki do Folderu okresu razem; przy błędzie nie zostawia żadnego.

    Jeśli już przeniesionego pliku nie da się usunąć, zatrzymanie wskazuje ten plik.
    """

    ensure_period_files_absent(files)
    period_directory = files.folder.directory
    if not period_directory.exists():
        staged_directory.rename(period_directory)
        return
    published: list[Path] = []
    try:
        for filename in files.filenames:
            target = period_directory / filename
            os.rename(staged_directory / filename, target)
            published.append(target)
    except OSError:
        for target in published:
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc
        raise
