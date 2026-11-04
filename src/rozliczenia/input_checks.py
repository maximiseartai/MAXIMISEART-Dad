"""Sprawdzanie plików taty w obu procesach, to samo w Diagnozie i Konfiguracji Centrum rozliczeń.

Rejestr zleceń i Wzorce czytają czytniki (``Readers``), które proces i Centrum dostają jako zależność. Błąd
czytnika (``WorkbookError``, ``PeriodFolderError``, ``WorkerConfigError``) moduł sam tłumaczy na Komunikat
procesu, który z tego pliku korzysta: proces zatrzymuje się nim (``StopError``), a Diagnoza i Konfiguracja
pokazują go jako przyczynę albo problem pliku.

Sprawdzanie Przygotowania pliku zbiorczego szuka też Surowych zleceń na dole każdego arkusza zleceń
(``raw_orders_in_period``) tym samym rozpoznaniem bloku i odczytem arkusza co Uporządkowanie INTERMAX
(``raw_orders.pasted`` na ``intermax_file.Register``) i oddaje je jako fakt, który Przygotowanie tłumaczy na
Zatrzymanie.

Komórki zakazanych kolumn przeczytanych arkuszy Rejestru i Surowych zleceń zna pamięć reguły danych pracy Centrum
(``forbidden``, ADR 0025), którą Centrum podaje obok czytników; proces bez Centrum jej nie ma. Wiersze Rejestru z
Odczytu danych zna też Kopia wejścia Uruchomienia (``copy``, #841).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from . import client_data, input_copy, preparation_files, preparation_register, raw_orders, settlement_files, settlement_messages, workbook_files
from . import preparation_messages as messages
from .intermax_file import Register, UnsupportedShape
from .message import Message, StopError
from .period_folder import (
    PeriodFolder,
    PeriodFolderError,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    locate_period_folder,
)
from .preparation_files import PeriodFiles
from .preparation_register import TARGET_HEADERS, RegisterSheet
from .settlement_period import SettlementPeriod, parse_period_token
from .template_file import TemplateFile
from .workbook_files import Problem, WorkbookError
from .worker_config import WorkerConfigError, load_worker_mapping, normalize_text


@dataclass(frozen=True)
class Readers:
    """Czytniki Rejestru zleceń i Wzorców; błąd pliku zgłaszają jako ``WorkbookError``.

    Produkcyjne czytają pliki (``FILE_READERS``), a test i weryfikacja podstawiają czytnik, który się psuje.
    Ten sam obiekt dostają Uruchomienie procesu i Diagnoza, więc usterka czytnika trafia do obu.
    """

    register: Callable[[Path, SettlementPeriod | None], list[RegisterSheet]]
    """Arkusze ze zleceniami Rejestru, z ``period`` tylko wiersze, których data może leżeć w okresie.

    Rejestr, którego nie ma albo który jest otwarty w Excelu, to też ``WorkbookError``.
    """
    template: Callable[[TemplateFile], None]
    """Sprawdzanie Wzorca: istnieje, nie jest otwarty, daje się odczytać i ma układ swojego pliku."""


FILE_READERS: Final = Readers(register=preparation_register.read_register, template=TemplateFile.check)

WorkerConfigExplanation: TypeAlias = Callable[[Path, WorkerConfigError], Message]
"""Komunikat procesu o konfiguracji wykonawców, której nie da się użyć."""


@dataclass(frozen=True)
class TemplateProblem:
    """Wzorzec nie przechodzi Sprawdzania: rodzaj problemu i Komunikat procesu, który z niego tworzy pliki."""

    problem: Problem
    message: Message


@dataclass(frozen=True)
class ProcessTemplate:
    """Wzorzec, z którego proces tworzy pliki, z Komunikatem tego procesu o Wzorcu, którego nie da się użyć."""

    file: TemplateFile
    _explain: Callable[[WorkbookError], Message]

    @classmethod
    def internal(cls, path: Path) -> ProcessTemplate:
        return cls(preparation_files.internal_template(path), messages.template_unusable)

    @classmethod
    def collective(cls, path: Path) -> ProcessTemplate:
        return cls(preparation_files.collective_template(path), messages.template_unusable)

    @classmethod
    def worker(cls, path: Path) -> ProcessTemplate:
        return cls(TemplateFile.worker_settlement(path), settlement_messages.worker_template_unusable)

    def problem(self, readers: Readers) -> TemplateProblem | None:
        """``None``, gdy Wzorzec przechodzi Sprawdzanie."""

        try:
            readers.template(self.file)
        except WorkbookError as error:
            return TemplateProblem(error.problem, self._explain(error))
        return None

    def checked(self, readers: Readers) -> TemplateFile:
        """Wzorzec po Sprawdzaniu, z którego Zapisywanie tworzy pliki; zatrzymanie, gdy go nie przechodzi."""

        found = self.problem(readers)
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
    readers: Readers,
) -> tuple[PeriodFiles, dict[str, str]]:
    """Sprawdzanie Przygotowania pliku zbiorczego: pliki okresu i Wykonawcy albo zatrzymanie."""

    settlement_period = _parse_period(period)
    with _stops(messages.register_unusable):
        workbook_files.ensure_available(register)
    internal = ProcessTemplate.internal(internal_template).checked(readers)
    collective = ProcessTemplate.collective(collective_template).checked(readers)
    if not periods_directory.is_dir():
        raise StopError(messages.periods_directory_missing(periods_directory))
    files = PeriodFiles(internal, collective, _locate_period_folder(periods_directory, settlement_period))
    preparation_files.ensure_period_files_absent(files)
    return files, _worker_mapping(config, messages.worker_config_problem)


def read_register(
    register: Path,
    period: SettlementPeriod | None,
    readers: Readers,
    forbidden: client_data.ForbiddenValues | None = None,
    copy: input_copy.InputCopy | None = None,
) -> list[RegisterSheet]:
    """Arkusze ze zleceniami Rejestru zleceń albo zatrzymanie, gdy Rejestru nie da się odczytać albo nie ma nagłówków.

    ``forbidden`` poznaje komórki zakazanych kolumn każdego przeczytanego wiersza, a ``copy`` każdy przeczytany wiersz
    (``_copied``).
    """

    with _stops(messages.register_unusable):
        sheets = readers.register(register, period)
    if forbidden is not None:
        for sheet in sheets:
            for row in sheet.register_rows:
                for column, header in _FORBIDDEN_HEADERS:
                    forbidden.remember_value(column, row.cells[header].value)
    if copy is not None:
        _copied(register, sheets, copy)
    return sheets


def _copied(register: Path, sheets: Sequence[RegisterSheet], copy: input_copy.InputCopy) -> None:
    """Arkusze Rejestru z odczytu w Kopii wejścia: komórki każdej kolumny ``COLUMNS`` w jej kolumnie arkusza pod
    nagłówkiem Rejestru (wiersz 1) i puste wiersze z odczytanego zakresu.

    Czytnik Rejestru nie oddaje bajtów, więc odcisk jest z bajtów przeczytanych zaraz po nim; Rejestru, którego w tej
    chwili już nie da się przeczytać, Kopia nie ma, a Uruchomienie idzie dalej z tym, co czytnik oddał.
    """

    try:
        content = workbook_files.saved_workbook_content(register)
    except WorkbookError:
        return
    workbook = copy.workbook(register, content)
    for sheet in sheets:
        positions = sheet.positions
        copied = workbook.sheet(sheet.name, 1, {number: column.register_header for column, number in positions.items()})
        for row in sheet.register_rows:
            copied.row(row.number, {number: row.cells[column.target_header].value for column, number in positions.items()})
        copied.empty_rows(sheet.empty_rows)


_FORBIDDEN_HEADERS: Final = client_data.forbidden_columns({normalize_text(header): header for header in TARGET_HEADERS})
"""Zakazane kolumny wiersza Rejestru (``RegisterRow``) z nagłówkiem docelowym, pod którym stoi ich komórka."""


@dataclass(frozen=True)
class RawOrders:
    """Surowe zlecenia, które mogą należeć do okresu: arkusz zleceń i jego wiersze od ``first_row`` do ``last_row``."""

    sheet: str
    first_row: int
    last_row: int


def raw_orders_in_period(
    register: Path, period: SettlementPeriod, forbidden: client_data.ForbiddenValues | None = None
) -> RawOrders | None:
    """Surowe zlecenia na dole arkusza zleceń z dniem w ``period`` albo z dniem, którego nie da się ustalić.

    Dzień nie daje się ustalić, gdy Surowe zlecenie nie ma daty albo Wykonawcy: wtedy to Uporządkowanie INTERMAX
    mówi, co poprawić. Wiersz z wyglądem z aplikacji nad uporządkowanymi bez bloku na dole nie jest Surowym
    zleceniem i Przygotowania nie zatrzymuje. Zatrzymanie przy nieczytelnym Rejestrze.
    """

    with _stops(messages.register_unusable), workbook_files.unreadable_as_error(register):
        intermax = Register.read(register, forbidden=forbidden)
        for sheet in intermax.order_sheets:
            try:
                pasted = raw_orders.pasted(sheet.rows_from_bottom(), sheet.columns)
            except UnsupportedShape as error:
                raise WorkbookError(register, Problem.UNREADABLE) from error
            found = _raw_rows_in_period(pasted, period)
            if found is not None:
                return RawOrders(sheet.name, *found)
    return None


def _raw_rows_in_period(
    pasted: Sequence[raw_orders.RawOrder | raw_orders.Undated | raw_orders.WithoutWorker], period: SettlementPeriod
) -> tuple[int, int] | None:
    undetermined = next((order for order in pasted if not isinstance(order, raw_orders.RawOrder)), None)
    if undetermined is not None:
        return undetermined.row, undetermined.row
    in_period = any(
        period.tuesday <= order.when.date() <= period.monday for order in pasted if isinstance(order, raw_orders.RawOrder)
    )
    return (pasted[0].row, pasted[-1].row) if in_period else None


def register_problem(
    register: Path, readers: Readers, forbidden: client_data.ForbiddenValues | None = None
) -> Message | None:
    """Komunikat, którym Przygotowanie zatrzymałoby się na Rejestrze zleceń: otwarty w Excelu, nieczytelny, bez nagłówków."""

    try:
        read_register(register, None, readers, forbidden)
    except StopError as stop:
        return stop.message
    return None


def check_settlement(
    source: Path, config: Path, worker_template: Path, readers: Readers
) -> tuple[PeriodFolder, dict[str, str], TemplateFile]:
    """Sprawdzanie Przebiegu rozliczeń: Folder okresu Pliku zbiorczego, Wykonawcy i sprawdzony Wzorzec albo zatrzymanie."""

    with _stops(settlement_messages.collective_file_unusable):
        workbook_files.ensure_available(source)
    try:
        folder = PeriodFolder.from_collective_file(source)
    except PeriodFolderError as error:
        raise StopError(settlement_messages.collective_file_invalid(source, error)) from error
    settlement_files.ensure_worker_settlements_absent(folder.worker_settlements)
    mapping = _worker_mapping(config, settlement_messages.worker_config_problem)
    return folder, mapping, ProcessTemplate.worker(worker_template).checked(readers)


def workers(config: Path, explain: WorkerConfigExplanation) -> dict[str, str] | Message:
    """Wykonawcy z konfiguracji wykonawców albo Komunikat ``explain``, którym zatrzymałby się na niej proces."""

    try:
        return _worker_mapping(config, explain)
    except StopError as stop:
        return stop.message


@contextmanager
def _stops(explain: Callable[[WorkbookError], Message]) -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(explain(error)) from error


def _worker_mapping(config: Path, explain: WorkerConfigExplanation) -> dict[str, str]:
    try:
        return load_worker_mapping(config)
    except WorkerConfigError as error:
        raise StopError(explain(config, error)) from error


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
