"""Sprawdzanie plików taty w obu procesach, to samo w Diagnozie i Konfiguracji Centrum rozliczeń.

Wzorce sprawdza Sprawdzanie Wzorca (``run_context.TemplateCheck``), które proces i Centrum dostają jako zależność, a
bajty plików taty czyta uchwyt plików taty (``dad_files.DadFiles``). Błąd czytnika (``WorkbookError``, ``PeriodFolderError``, ``WorkerConfigError``) moduł
sam tłumaczy na Komunikat procesu, który z tego pliku korzysta: proces zatrzymuje się nim (``StopError``), a Diagnoza i
Konfiguracja pokazują go jako przyczynę albo problem pliku. Rejestr zleceń Przygotowania czyta i tłumaczy jego widok
Rejestru (``preparation_register``), a tu Sprawdzanie sprawdza tylko, że Rejestr jest dostępny.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from . import preparation_files, settlement_files, settlement_messages, workbook_files
from . import worker_config_messages
from . import preparation_messages as messages
from .message import Message, StopError
from .period_folder import (
    PeriodFolder,
    PeriodFolderError,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    locate_period_folder,
)
from .preparation_files import PeriodFiles
from .run_context import TemplateCheck
from .settlement_period import SettlementPeriod, parse_period_token
from .template_file import TemplateFile
from .workbook_files import Problem, WorkbookError
from .worker_config import WorkerConfigError, load_worker_mapping


# Dawna nazwa Wzorca rozliczenia pracownika, zmieniona 18.10.2026 przed pierwszym Wydaniem (v0.1.0). Usuń ją razem z
# ``_worker_template_unusable``, gdy Log Uruchomienia taty pokaże Przebieg rozliczeń, którego Sprawdzanie przeszło
# Wzorzec pod obecną nazwą: podpowiedź pomaga tylko temu, komu Wzorca pod obecną nazwą brakuje (D3 rozplątania 7.11).
_OLD_WORKER_TEMPLATE_NAME: Final = "placeholder.xlsx"


def _worker_template_unusable(error: WorkbookError) -> Message:
    """Komunikat o Wzorcu rozliczenia pracownika z podpowiedzią zmiany nazwy, gdy brakuje go, a obok leży plik pod
    dawną nazwą."""

    return settlement_messages.worker_template_unusable(error, _old_worker_template_beside(error))


def _old_worker_template_beside(error: WorkbookError) -> str | None:
    """Dawna nazwa Wzorca, gdy Wzorca brakuje, a plik o niej leży obok.

    Dysk pyta tylko przy brakującym Wzorcu: przy innym problemie folder Wzorca może być bez dostępu, a ``Path.is_file``
    na Pythonie do 3.13 rzuca wtedy ``PermissionError``.
    """

    if error.problem is not Problem.MISSING:
        return None
    old = error.path.with_name(_OLD_WORKER_TEMPLATE_NAME)
    return old.name if old.is_file() else None


@dataclass(frozen=True)
class TemplateProblem:
    """Wzorzec nie przechodzi Sprawdzania."""

    problem: Problem
    message: Message


@dataclass(frozen=True)
class ProcessTemplate:
    """Wzorzec, z którego proces tworzy pliki, z Komunikatem tego procesu o Wzorcu, którego nie da się użyć."""

    file: TemplateFile
    _explain: Callable[[WorkbookError], Message]

    @classmethod
    def internal(cls, path: Path) -> ProcessTemplate:
        return cls(TemplateFile.internal_settlement(path), messages.template_unusable)

    @classmethod
    def collective(cls, path: Path) -> ProcessTemplate:
        return cls(TemplateFile.collective_file(path), messages.template_unusable)

    @classmethod
    def worker(cls, path: Path) -> ProcessTemplate:
        return cls(TemplateFile.worker_settlement(path), _worker_template_unusable)

    def problem(self, check: TemplateCheck) -> TemplateProblem | None:
        """``None``, gdy Wzorzec przechodzi Sprawdzanie ``check``."""

        try:
            check(self.file)
        except WorkbookError as error:
            return TemplateProblem(error.problem, self._explain(error))
        return None

    def checked(self, check: TemplateCheck) -> TemplateFile:
        """Wzorzec po Sprawdzaniu ``check``, z którego Zapisywanie tworzy pliki; zatrzymanie, gdy go nie przechodzi."""

        found = self.problem(check)
        if found is not None:
            raise StopError(found.message)
        return self.file


def check_preparation(
    register: Path,
    periods_directory: Path,
    period: str,
    config: Path,
    *,
    internal_template: Path,
    collective_template: Path,
    template_check: TemplateCheck,
) -> tuple[PeriodFiles, dict[str, str]]:
    """Sprawdzanie Przygotowania pliku zbiorczego: pliki okresu i Wykonawcy albo zatrzymanie."""

    settlement_period = _parse_period(period)
    with _stops(messages.register_unusable):
        workbook_files.ensure_available(register)
    internal = ProcessTemplate.internal(internal_template).checked(template_check)
    collective = ProcessTemplate.collective(collective_template).checked(template_check)
    if not periods_directory.is_dir():
        raise StopError(messages.periods_directory_missing(periods_directory))
    files = PeriodFiles(internal, collective, _locate_period_folder(periods_directory, settlement_period))
    preparation_files.ensure_period_files_absent(files)
    return files, _worker_mapping(config)


def check_settlement(
    source: Path, config: Path, worker_template: Path, template_check: TemplateCheck
) -> tuple[PeriodFolder, dict[str, str], TemplateFile]:
    """Sprawdzanie Przebiegu rozliczeń: Folder okresu Pliku zbiorczego, Wykonawcy i sprawdzony Wzorzec albo zatrzymanie."""

    with _stops(settlement_messages.collective_file_unusable):
        workbook_files.ensure_available(source)
    try:
        folder = PeriodFolder.from_collective_file(source)
    except PeriodFolderError as error:
        raise StopError(settlement_messages.collective_file_invalid(source, error)) from error
    settlement_files.ensure_worker_settlements_absent(folder.worker_settlements)
    mapping = _worker_mapping(config)
    return folder, mapping, ProcessTemplate.worker(worker_template).checked(template_check)


def workers(config: Path) -> dict[str, str] | Message:
    """Wykonawcy z konfiguracji wykonawców albo Komunikat, którym zatrzymałby się na niej każdy proces."""

    try:
        return _worker_mapping(config)
    except StopError as stop:
        return stop.message


@contextmanager
def _stops(explain: Callable[[WorkbookError], Message]) -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(explain(error)) from error


def _worker_mapping(config: Path) -> dict[str, str]:
    try:
        return load_worker_mapping(config)
    except WorkerConfigError as error:
        raise StopError(worker_config_messages.worker_config_problem(config, error)) from error


def _parse_period(token: str) -> SettlementPeriod:
    try:
        return parse_period_token(token)
    except ValueError as error:
        raise StopError(messages.invalid_period_token(token)) from error


def _locate_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    try:
        return locate_period_folder(periods_directory, period)
    except PeriodFolderLookupError as error:
        raise StopError(messages.period_folder_lookup_problem(error)) from error
    except PeriodFolderInaccessible as error:
        raise StopError(messages.folder_inaccessible(error.folder)) from error
