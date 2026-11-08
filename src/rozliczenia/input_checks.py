"""Sprawdzanie plików taty w obu procesach, to samo w Diagnozie i Konfiguracji Centrum rozliczeń.

Rejestr zleceń i Wzorce czytają czytniki (``Readers``), które proces i Centrum dostają jako zależność. Błąd
czytnika (``WorkbookError``, ``PeriodFolderError``, ``WorkerConfigError``) moduł sam tłumaczy na Komunikat
procesu, który z tego pliku korzysta: proces zatrzymuje się nim (``StopError``), a Diagnoza i Konfiguracja
pokazują go jako przyczynę albo problem pliku.

Sprawdzanie Przygotowania pliku zbiorczego szuka też Surowych zleceń na dole każdego arkusza zleceń
(``raw_orders_in_period``) tym samym rozpoznaniem bloku i odczytem arkusza co Uporządkowanie INTERMAX
(``raw_orders.pasted`` na ``intermax_file.Register``) i oddaje je jako fakt, który Przygotowanie tłumaczy na
Zatrzymanie.

Rejestr czyta uchwyt plików taty (``dad_files.DadFiles``) ze źródłem bajtów czytników (``Readers.source``). Komórki
zakazanych kolumn przeczytanych arkuszy Rejestru i Surowych zleceń zna pamięć reguły danych uchwytu (ADR 0025). Wiersz
Rejestru bez wyglądu uporządkowanego może być przesuniętym pierwszym wierszem wklejenia, więc pamięć zna jego komórki w
obu położeniach (#918). Wiersze Rejestru z Odczytu danych zna też Kopia wejścia Uruchomienia (#841).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from . import client_data, input_copy, preparation_files, preparation_register, raw_orders, settlement_files, settlement_messages, workbook_files
from . import worker_config_messages
from . import preparation_messages as messages
from .dad_files import DadFiles, ReadFile
from .intermax_file import Register
from .message import Message, StopError
from .period_folder import (
    PeriodFolder,
    PeriodFolderError,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    locate_period_folder,
)
from .preparation_files import PeriodFiles
from .preparation_register import RegisterSheet
from .register_columns import TARGET_HEADERS
from .settlement_period import SettlementPeriod, parse_period_token
from .template_file import TemplateFile
from .workbook_files import ByteSource, Problem, WorkbookError
from .text import normalize_text
from .workbook_parts import UnsupportedShape
from .worker_config import WorkerConfigError, load_worker_mapping


@dataclass(frozen=True)
class Readers:
    """Czytniki Rejestru zleceń i Wzorców i źródło bajtów plików taty; błąd pliku zgłaszają jako ``WorkbookError``.

    Produkcyjne czytają pliki (``FILE_READERS``), a test i weryfikacja podstawiają czytnik, który się psuje, albo
    źródło bajtów, które się psuje, czeka, liczy odczyty albo zapisuje plik zaraz po odczycie. Ten sam obiekt dostają
    Uruchomienie procesu i Diagnoza, więc usterka czytnika trafia do obu.
    """

    register: Callable[[ReadFile, SettlementPeriod | None], list[RegisterSheet]]
    """Arkusze ze zleceniami przeczytanego Rejestru; z ``period`` tylko wiersze, których data może leżeć w okresie."""
    template: Callable[[TemplateFile], None]
    """Sprawdzanie Wzorca: istnieje, nie jest otwarty, daje się odczytać i ma układ swojego pliku."""
    source: ByteSource = workbook_files.file_bytes
    """Bajty plików taty, które czyta uchwyt plików taty (``dad_files.DadFiles.source``): Rejestru zleceń, INTERMAX w
    Diagnozie i na karcie dni i Pliku zbiorczego w Przebiegu rozliczeń i Uzupełnieniu."""


FILE_READERS: Final = Readers(register=preparation_register.read_register, template=TemplateFile.check)

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
        return cls(TemplateFile.internal_settlement(path), messages.template_unusable)

    @classmethod
    def collective(cls, path: Path) -> ProcessTemplate:
        return cls(TemplateFile.collective_file(path), messages.template_unusable)

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
    return files, _worker_mapping(config)


def read_register(
    register: Path, period: SettlementPeriod | None, readers: Readers, files: DadFiles
) -> list[RegisterSheet]:
    """Arkusze ze zleceniami Rejestru zleceń albo zatrzymanie, gdy Rejestru nie da się odczytać albo nie ma nagłówków.

    Rejestr czyta uchwyt ``files``. Jego pamięć reguły danych poznaje komórki zakazanych kolumn każdego przeczytanego
    wiersza w jednym położeniu (ADR 0025): pierwszego wiersza bloku wklejenia z widocznym przesunięciem
    (``RegisterSheet.shifted_rows``) ``raw_orders.SHIFT`` kolumn na lewo od nagłówka, wiersza z siatki
    (``RegisterSheet.both_rows``) w obu, a każdego innego pod nim (#918). Jego Kopia wejścia poznaje każdy przeczytany
    wiersz (``_copied``), wiersze ze śladem przesunięcia i chwilę zmiany Rejestru sprzed jego odczytu.
    """

    with _stops(messages.register_unusable):
        file = files.read(register)
        sheets = readers.register(file, period)
    # Pamięć i Kopia Rejestru w Przygotowaniu poza świadkiem arkusza do N5b-1 (jedna reguła położenia, R7).
    for sheet in sheets:
        numbers = {column.target_header: number for column, number in sheet.positions.items()}
        for row in sheet.register_rows:
            shifted = sheet.shifted_rows.get(row.number)
            moved = shifted if shifted is not None else sheet.both_rows.get(row.number)
            for column, header in _FORBIDDEN_HEADERS:
                if shifted is None:
                    files.forbidden.remember_value(column, row.cells[header].value)
                if moved is not None:
                    files.forbidden.remember_value(column, moved.get(numbers[header] - raw_orders.SHIFT))
    if files.copy is not None:
        _copied(file, sheets, files.copy)
    return sheets


def _copied(file: ReadFile, sheets: Sequence[RegisterSheet], copy: input_copy.InputCopy) -> None:
    """Odczyt Rejestru w Kopii wejścia: bajty, z których czytnik przeczytał arkusze, z chwilą zmiany sprzed odczytu,
    komórki każdej kolumny ``COLUMNS`` bez zakazanych (``_FORBIDDEN_HEADERS``) w jej kolumnie arkusza pod nagłówkiem
    Rejestru (wiersz 1), puste wiersze z odczytanego zakresu i wiersze ze śladem przesunięcia
    (``RegisterSheet.traced_rows``); bez drugiego odczytu pliku, więc Kopia nie zatrzymuje Przygotowania. Kopia
    Przygotowania ma każdy wiersz pod jego nagłówkami, także wiersz z siatki (do N5b-1, R7)."""

    workbook = copy.workbook(file.path, file.content, file.modified_at)
    forbidden = {header for _, header in _FORBIDDEN_HEADERS}
    for sheet in sheets:
        positions = sheet.positions
        copied = workbook.sheet(
            sheet.name,
            1,
            {number: column.register_header for column, number in positions.items()},
            {number for column, number in positions.items() if column.target_header in forbidden},
        )
        for row in sheet.register_rows:
            copied.row(
                row.number,
                {number: row.cells[column.target_header].value for column, number in positions.items()},
                raw_orders.RowPositions(traced=row.number in sheet.traced_rows),
            )
        copied.empty_rows(sheet.empty_rows)


_FORBIDDEN_HEADERS: Final = client_data.forbidden_columns({normalize_text(header): header for header in TARGET_HEADERS})
"""Zakazane kolumny wiersza Rejestru (``RegisterRow``) z nagłówkiem docelowym, pod którym stoi ich komórka."""


@dataclass(frozen=True)
class RawOrders:
    """Surowe zlecenia, które mogą należeć do okresu: arkusz zleceń i jego wiersze od ``first_row`` do ``last_row``."""

    sheet: str
    first_row: int
    last_row: int


def raw_orders_in_period(register: Path, period: SettlementPeriod, files: DadFiles) -> RawOrders | None:
    """Surowe zlecenia na dole arkusza zleceń z dniem w ``period`` albo z dniem, którego nie da się ustalić.

    Dzień nie daje się ustalić, gdy Surowe zlecenie nie ma daty albo Wykonawcy: wtedy to Uporządkowanie INTERMAX
    mówi, co poprawić. Wiersz z wyglądem z aplikacji nad uporządkowanymi bez bloku na dole nie jest Surowym
    zleceniem i Przygotowania nie zatrzymuje. Zatrzymanie przy nieczytelnym Rejestrze.
    """

    with _stops(messages.register_unusable), workbook_files.unreadable_as_error(register):
        intermax = Register.read(register, files)
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
    in_period = any(period.contains(order.when) for order in pasted if isinstance(order, raw_orders.RawOrder))
    return (pasted[0].row, pasted[-1].row) if in_period else None


def register_problem(register: Path, readers: Readers, files: DadFiles) -> Message | None:
    """Komunikat, którym Przygotowanie zatrzymałoby się na Rejestrze zleceń: otwarty w Excelu, nieczytelny, bez nagłówków."""

    try:
        read_register(register, None, readers, files)
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
    mapping = _worker_mapping(config)
    return folder, mapping, ProcessTemplate.worker(worker_template).checked(readers)


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
