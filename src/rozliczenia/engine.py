"""Deterministyczne rozdzielanie pliku zbiorczego do szablonów pracowników."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from . import collective_file, input_checks, settlement_files, settlement_messages
from .domain import PlannedWorkerResult, ProgressObserver, SavedWorkerResult, SettlementSummary, WorkerResult
from .client_data import ForbiddenValues
from .inea_only_quantities import Cleared
from .input_checks import FILE_READERS, Readers
from .message import Message, StopError
from .order_facts import CollectiveOrders
from .phase_runner import PhaseRunner
from .workbook_files import DataRow, WorkbookError
from .workbook_save import WorkbookSaveError
from .worker_config import normalize_text


def default_worker_template_path() -> Path:
    """Wskazuje wspólny Wzorzec rozliczenia pracownika w katalogu konfiguracji."""

    return Path(__file__).resolve().parents[2] / "config" / "Wzorzec rozliczenia pracownika.xlsx"


def _read_source_rows(
    source_path: Path, forbidden: ForbiddenValues | None
) -> tuple[dict[str, list[DataRow]], list[int], CollectiveOrders, Cleared]:
    """Czyta Wiersze danych Pliku zbiorczego z ich Wyróżnieniami i grupuje je po identyfikatorze WYKONAWCA.

    Wiersze danych bez Wykonawcy nie trafiają do grup; zostają ich numery. W grupach nie ma Ilości tylko dla INEA.
    """

    try:
        read = collective_file.read_data_rows(source_path, forbidden)
    except WorkbookError as error:
        raise StopError(settlement_messages.collective_file_unusable(error)) from error
    rows_by_worker: defaultdict[str, list[DataRow]] = defaultdict(list)
    for row in read.rows:
        rows_by_worker[normalize_text(row.worker)].append(row)
    return dict(rows_by_worker), read.without_worker, read.orders, read.inea_only


@dataclass(frozen=True)
class _Plan:
    """Wiersze danych pod nazwą z Konfiguracji wykonawców i fakty o Wierszach danych bez Szablonu pracownika."""

    rows_by_target: dict[str, list[DataRow]]
    unmapped_workers: tuple[str, ...]
    """Identyfikatory WYKONAWCA spoza Konfiguracji wykonawców, każdy raz, w pisowni i kolejności Pliku zbiorczego."""
    rows_without_worker: tuple[int, ...]


def _plan_rows(mapping: dict[str, str], rows_by_worker: dict[str, list[DataRow]], without_worker: list[int]) -> _Plan:
    """Przypisuje Wiersze danych do nazw z Konfiguracji wykonawców."""

    rows_by_target: defaultdict[str, list[DataRow]] = defaultdict(list)
    unmapped: list[str] = []
    for source_worker, rows in rows_by_worker.items():
        target_name = mapping.get(source_worker)
        if target_name is None:
            unmapped.append(str(rows[0].worker).strip())
            continue
        rows_by_target[normalize_text(target_name)].extend(rows)
    return _Plan(dict(rows_by_target), tuple(unmapped), tuple(without_worker))


def _plan_warnings(source_path: Path, plan: _Plan, *, dry_run: bool) -> list[Message]:
    """Przy zapisie każdy fakt planu zatrzymuje Przebieg; Podgląd bez zapisu pokazuje je jako ostrzeżenia."""

    if not dry_run and plan.unmapped_workers:
        raise StopError(settlement_messages.unmapped_worker(source_path, plan.unmapped_workers))
    if not dry_run and plan.rows_without_worker:
        raise StopError(settlement_messages.rows_without_worker(source_path))
    return [
        *(settlement_messages.row_without_worker_warning(source_path, number) for number in plan.rows_without_worker),
        *(settlement_messages.unmapped_worker_warning(source_path, worker) for worker in plan.unmapped_workers),
    ]


def run_settlements(
    source_path: Path,
    config_path: Path,
    *,
    dry_run: bool = False,
    worker_template_path: Path | None = None,
    observer: ProgressObserver | None = None,
    readers: Readers = FILE_READERS,
    forbidden: ForbiddenValues | None = None,
) -> SettlementSummary:
    """Uruchamia pełny proces z ochroną przed błędną lokalizacją i duplikacją.

    Ten moduł tylko sekwencjonuje cztery etapy i rozlicza Szablon pracownika
    jednego Wykonawcy; pętlę po nich ze zdarzeniami Wykonawców prowadzi
    sekwencer etapów. Konfiguracja wykonawców jest w
    ``worker_config``, a folder tymczasowy, Nienadpisywanie i publikacja
    Folderu rozliczeń pracowników w ``settlement_files``, a Sprawdzanie Wzorca czytnikami ``readers``
    w ``input_checks``. Komórki zakazanych kolumn Pliku zbiorczego zna ``forbidden`` (reguła danych, ADR 0025).
    """

    phases = PhaseRunner(observer)
    source_path = source_path.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    worker_template_path = (worker_template_path or default_worker_template_path()).expanduser().resolve()

    folder, mapping, worker_template = phases.check(
        lambda: input_checks.check_settlement(source_path, config_path, worker_template_path, readers)
    )
    target_directory = folder.worker_settlements
    worker_names = list(mapping.values())
    rows_by_worker, without_worker, orders, inea_only = phases.read(
        lambda: _read_source_rows(source_path, forbidden),
        issue_count=lambda read_rows: len(read_rows[1]),
    )

    def plan_rows() -> tuple[dict[str, list[DataRow]], list[Message]]:
        plan = _plan_rows(mapping, rows_by_worker, without_worker)
        return plan.rows_by_target, _plan_warnings(source_path, plan, dry_run=dry_run)

    rows_by_target, warnings = phases.plan(
        plan_rows,
        templates=lambda _planned: worker_names,
        issue_count=lambda planned: len(planned[1]),
    )
    summary = SettlementSummary(
        folder.period.token, source_path, target_directory, orders=orders, inea_only_cleared=inea_only, warnings=warnings
    )

    def settle(directory: Path, worker_name: str) -> WorkerResult:
        target_path = directory / folder.worker_settlement(worker_name).name
        rows = rows_by_target.get(normalize_text(worker_name), [])
        if dry_run:
            return PlannedWorkerResult(worker_name, target_path, len(rows))
        try:
            route = worker_template.create(target_path, rows)
        except WorkbookError as error:
            raise StopError(
                settlement_messages.worker_template_unusable_in_saving(target_directory, worker_name, error)
            ) from error
        except (OSError, WorkbookSaveError) as exc:
            raise StopError(settlement_messages.worker_file_failed(target_directory, worker_name)) from exc
        return SavedWorkerResult(worker_name, target_path, len(rows), route)

    def save_templates(directory: Path) -> list[WorkerResult]:
        return phases.each_template(lambda worker_name: settle(directory, worker_name))

    def save_all() -> None:
        if dry_run:
            summary.results = save_templates(target_directory)
        else:
            summary.results = settlement_files.write_worker_settlements(target_directory, save_templates)

    phases.save(save_all)
    return replace(summary, phase_durations_ms=phases.durations_ms())
