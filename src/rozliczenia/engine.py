"""Deterministyczne rozdzielanie pliku zbiorczego do szablonów pracowników."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from . import collective_file, input_checks, settlement_files, settlement_messages
from .domain import ProgressPhase
from .dad_files import DadFiles
from .inea_only_quantities import Cleared
from .message import Message, StopError
from .order_facts import CollectiveOrders
from .phase_runner import PhaseRunner
from .workbook_files import DataRow, WorkbookError
from .workbook_save import WorkbookSaveError
from .text import normalize_text
from .write_routes import Route, RouteCounts, TemplateKind
from .period_folder import collective_period_token
from .run_context import RunContext


@dataclass(frozen=True)
class SettlementInputs:
    """Wejście procesu Przebiegu rozliczeń, gotowe przed startem silnika.

    Okres wynika z nazwy Pliku zbiorczego (``nieznany``, gdy się nie da).
    """

    source: Path
    config_path: Path
    worker_template_path: Path
    dry_run: bool = False

    @property
    def period(self) -> str:
        return collective_period_token(self.source)


@dataclass(frozen=True)
class PlannedWorkerResult:
    """Bezpieczny wynik dla jednego szablonu w Podglądzie bez zapisu: nic nie powstało, więc bez drogi zapisu."""

    worker_name: str
    output_file: Path
    rows: int

    @property
    def status(self) -> Literal["PLAN", "PUSTY_SZABLON"]:
        return "PLAN" if self.rows else "PUSTY_SZABLON"


@dataclass(frozen=True)
class SavedWorkerResult:
    """Bezpieczny wynik dla jednego zapisanego szablonu; ``route`` to droga zapisu Rozliczenia pracownika."""

    worker_name: str
    output_file: Path
    rows: int
    route: Route

    @property
    def status(self) -> Literal["ZAPISANO", "PUSTY_SZABLON"]:
        return "ZAPISANO" if self.rows else "PUSTY_SZABLON"


WorkerResult = PlannedWorkerResult | SavedWorkerResult
"""Wynik Przetworzenia Szablonu pracownika."""


@dataclass
class SettlementSummary:
    """Podsumowanie operacyjne; z treści Wierszy danych tylko kolumny dozwolone regułą prywatności (``order_facts``)."""

    period: str
    source_file: Path
    target_directory: Path
    orders: CollectiveOrders = ()
    """Dozwolona treść każdego Wiersza danych, który Przebieg wczytał: dla Kontroli ilości w Centrum."""
    inea_only_cleared: Cleared = field(default_factory=lambda: MappingProxyType({}))
    """Liczba wyczyszczonych komórek Ilości tylko dla INEA w każdej kolumnie: tylko dla Logów Uruchomienia."""
    results: list[WorkerResult] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)
    """Ostrzeżenia Podglądu bez zapisu z katalogu Przebiegu rozliczeń; Przebieg z zapisem zatrzymuje się na nich."""
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def written_count(self) -> int:
        return sum(result.status == "ZAPISANO" for result in self.results)

    @property
    def planned_count(self) -> int:
        return sum(result.status == "PLAN" for result in self.results)

    @property
    def empty_count(self) -> int:
        return sum(result.status == "PUSTY_SZABLON" for result in self.results)

    @property
    def total_rows(self) -> int:
        return sum(result.rows for result in self.results)

    @property
    def template_count(self) -> int:
        return len(self.results)

    @property
    def routes(self) -> RouteCounts:
        return Counter(
            (TemplateKind.WORKER_SETTLEMENT, result.route)
            for result in self.results
            if isinstance(result, SavedWorkerResult)
        )

    @property
    def ok(self) -> bool:
        return not self.warnings


def _read_source_rows(
    source_path: Path, files: DadFiles
) -> tuple[dict[str, list[DataRow]], list[int], CollectiveOrders, Cleared]:
    """Wiersze danych bez Wykonawcy nie trafiają do grup; zostają ich numery. W grupach nie ma Ilości tylko dla INEA."""

    try:
        read = collective_file.read_data_rows(source_path, files)
    except WorkbookError as error:
        raise StopError(settlement_messages.collective_file_unusable(error)) from error
    rows_by_worker: defaultdict[str, list[DataRow]] = defaultdict(list)
    for row in read.rows:
        rows_by_worker[normalize_text(row.worker)].append(row)
    return dict(rows_by_worker), read.without_worker, read.orders, read.inea_only


@dataclass(frozen=True)
class _Plan:
    rows_by_target: dict[str, list[DataRow]]
    unmapped_workers: tuple[str, ...]
    """Identyfikatory WYKONAWCA spoza Konfiguracji wykonawców, każdy raz, w pisowni i kolejności Pliku zbiorczego."""
    rows_without_worker: tuple[int, ...]


def _plan_rows(mapping: dict[str, str], rows_by_worker: dict[str, list[DataRow]], without_worker: list[int]) -> _Plan:
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
    if not dry_run and plan.unmapped_workers:
        raise StopError(settlement_messages.unmapped_worker(source_path, plan.unmapped_workers))
    if not dry_run and plan.rows_without_worker:
        raise StopError(settlement_messages.rows_without_worker(source_path))
    return [
        *(settlement_messages.row_without_worker_warning(source_path, number) for number in plan.rows_without_worker),
        *(settlement_messages.unmapped_worker_warning(source_path, worker) for worker in plan.unmapped_workers),
    ]


def run_settlements(inputs: SettlementInputs, context: RunContext) -> SettlementSummary:
    """Uruchamia pełny proces z ochroną przed błędną lokalizacją i duplikacją."""

    phases = PhaseRunner(context.observer, clock=context.clock.now)
    files, readers, dry_run = context.files, context.readers, inputs.dry_run
    source_path = inputs.source.expanduser().resolve()
    config_path = inputs.config_path.expanduser().resolve()
    worker_template_path = inputs.worker_template_path.expanduser().resolve()

    folder, mapping, worker_template = phases.check(
        lambda: input_checks.check_settlement(source_path, config_path, worker_template_path, readers)
    )
    target_directory = folder.worker_settlements
    worker_names = list(mapping.values())
    rows_by_worker, without_worker, orders, inea_only = phases.read(
        lambda: _read_source_rows(source_path, files),
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
        name = folder.worker_settlement(worker_name).name
        rows = rows_by_target.get(normalize_text(worker_name), [])
        if dry_run:
            return PlannedWorkerResult(worker_name, target_directory / name, len(rows))
        try:
            route = worker_template.create(directory / name, rows)
        except WorkbookError as error:
            raise StopError(
                settlement_messages.worker_template_unusable_in_saving(target_directory, worker_name, error)
            ) from error
        except (OSError, WorkbookSaveError) as exc:
            raise StopError(settlement_messages.worker_file_failed(target_directory, worker_name)) from exc
        return SavedWorkerResult(worker_name, target_directory / name, len(rows), route)

    def save_templates(directory: Path) -> list[WorkerResult]:
        return phases.each_template(lambda worker_name: settle(directory, worker_name))

    def save_all() -> None:
        if dry_run:
            summary.results = save_templates(target_directory)
        else:
            summary.results = settlement_files.write_worker_settlements(target_directory, save_templates)

    phases.save(save_all)
    return replace(summary, phase_durations_ms=phases.durations_ms())
