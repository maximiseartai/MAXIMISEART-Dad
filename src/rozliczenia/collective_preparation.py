"""Przygotowanie pliku zbiorczego: z Rejestru zleceń do Rozliczenia wewnętrznego i Pliku zbiorczego.

Silnik nie proponuje okresu; pyta tylko o Decyzję taty o niepełnym okresie, przez
rozmowę od rdzenia Uruchomienia procesu (``decision.Conversation``), i sam
zatrzymuje się po odmowie. Zatrzymania zgłasza jako ``StopError`` z
Komunikatem dla taty, a wynik nie zawiera danych klientów.

Ten moduł sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty planu na ostrzeżenia i Decyzję taty o niepełnym
okresie, o którą pyta między Planowaniem a Zapisywaniem, a fakt Sprawdzania o Surowych zleceniach w okresie na
Zatrzymanie przed odczytem i zapisem.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from types import MappingProxyType

from . import input_checks, preparation_files, preparation_plan, preparation_register
from . import preparation_messages as messages
from .decision import Decision, Declined
from .domain import ProgressPhase
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .preparation_files import CollectiveFilePlan
from .preparation_plan import IncompletePeriod, Plan
from .quantity_rules import DESCRIPTION_COLUMNS
from .register_file import RegisterFile
from .text import day_label
from .write_routes import RouteCounts
from .run_context import RunContext

__all__ = [
    "PreparationInputs",
    "PreparationSummary",
    "prepare_collective_file",
]


@dataclass(frozen=True)
class PreparationInputs:
    """Wejście procesu Przygotowania pliku zbiorczego, gotowe przed startem silnika."""

    register_path: Path
    periods_directory: Path
    period: str
    config_path: Path
    internal_template_path: Path
    collective_template_path: Path
    dry_run: bool = False


@dataclass
class PreparationSummary:
    """Podsumowanie Przygotowania pliku zbiorczego bez danych klientów.

    Przy ``dry_run`` to plan: ścieżki plików są docelowe, ale nic nie istnieje.
    ``orders_per_day`` ma dokładnie siedem kluczy, każdy dzień okresu od wtorku
    do poniedziałku w kolejności dat, także dni bez zleceń (wartość ``0``).
    ``skipped_empty_rows`` to całkowicie puste wiersze Rejestru od pierwszego do
    ostatniego zlecenia okresu. ``routes``: ile zapisanych plików okresu każdego rodzaju powstało każdą drogą zapisu (ADR 0008).
    """

    internal_settlement_file: Path
    collective_file: Path
    period_order_count: int
    successful_order_count: int
    skipped_empty_rows: int
    orders_per_day: dict[date, int] = field(default_factory=dict)
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))
    routes: RouteCounts = field(default_factory=lambda: MappingProxyType({}))

    def labeled_orders_per_day(self) -> list[tuple[str, int]]:
        """``Zlecenia na dzień`` z etykietami dni dla taty, np. ``("wt 08.09.2026", 1)``, w kolejności dat."""

        return [
            (day_label(day), count) for day, count in self.orders_per_day.items()
        ]


def _incomplete_period_warning(register_path: Path, plan: Plan, incomplete: IncompletePeriod) -> Message:
    return messages.incomplete_period(
        register_path, plan.sheet, plan.period.token, incomplete.last_order_day, incomplete.monday
    )


def _plan_warnings(
    register_path: Path, files: preparation_files.PeriodFiles, plan: Plan, collective: CollectiveFilePlan
) -> list[Message]:
    collective_filename = files.folder.collective_file.name
    warnings: list[Message] = []
    if plan.incomplete_period is not None:
        warnings.append(_incomplete_period_warning(register_path, plan, plan.incomplete_period))
    if collective.too_few_zero_rows:
        warnings.append(
            messages.too_few_zero_rows(
                collective_filename,
                collective.successful_count,
                collective.zero_row_count,
                collective.first_row_without_zeros,
            )
        )
    if collective.rows_without_rule:
        warnings.append(messages.unknown_devices(collective_filename, collective.rows_without_rule))
    if collective.rows_from_description:
        warnings.append(messages.rows_from_description(collective_filename, collective.rows_from_description))
    warnings.append(messages.columns_from_description(collective_filename, DESCRIPTION_COLUMNS))
    return warnings


def _incomplete_period_decision(register_path: Path, plan: Plan, summary: PreparationSummary) -> Decision | None:
    if plan.incomplete_period is None:
        return None
    return Decision(
        message=_incomplete_period_warning(register_path, plan, plan.incomplete_period),
        counts_title=messages.ORDERS_PER_DAY,
        counts=summary.labeled_orders_per_day(),
        question=messages.INCOMPLETE_PERIOD_QUESTION,
    )


def prepare_collective_file(inputs: PreparationInputs, context: RunContext) -> PreparationSummary:
    """Tworzy w Folderze okresu razem Rozliczenie wewnętrzne i Plik zbiorczy.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie; wtedy nie
    powstaje żaden plik ani nowy Folder okresu, chyba że komunikat wskazuje plik
    okresu, którego po nieudanym zapisie nie udało się usunąć. Rejestr zleceń i
    wzorce są tylko czytane.

    ``dry_run=True`` wykonuje te same sprawdzenia, odczyt i planowanie, a etap
    Zapisywanie kończy bez tworzenia czegokolwiek (także Folderu okresu). Wynik
    jest wtedy planem z tymi samymi liczbami, ostrzeżeniami i nazwami plików.

    ``context.conversation`` to rozmowa z tatą od rdzenia Uruchomienia procesu. Przy
    zapisie, gdy plan ma ostrzeżenie o niepełnym okresie, Przygotowanie po
    Planowaniu, a przed Zapisywaniem pyta przez nią o Decyzję taty; odmowa to
    ``Declined`` bez zapisu, z podpowiedzią zgody tego rozmówcy. Czas
    czekania na Decyzję wstrzymuje zegar Uruchomienia, więc nie wlicza się do czasów etapów. Bez rozmówcy
    (``run_context.UNASKED``) Przygotowanie o nic nie pyta. Rejestr zleceń czyta raz w Sprawdzaniu uchwyt plików taty
    ``context.files`` (zob. ``preparation_register``).
    """

    phases = PhaseRunner(context.observer, clock=context.clock.now)
    dad_files, readers, conversation = context.files, context.readers, context.conversation
    period, dry_run = inputs.period, inputs.dry_run
    register_path = inputs.register_path.expanduser().resolve()
    periods_directory = inputs.periods_directory.expanduser().resolve()
    config_path = inputs.config_path.expanduser().resolve()
    internal_template = inputs.internal_template_path.expanduser().resolve()
    collective_template = inputs.collective_template_path.expanduser().resolve()

    def check() -> tuple[preparation_files.PeriodFiles, dict[str, str], RegisterFile]:
        files, worker_mapping = input_checks.check_preparation(
            register_path,
            periods_directory,
            period,
            config_path,
            internal_template=internal_template,
            collective_template=collective_template,
            readers=readers,
        )
        register = preparation_register.read(register_path, dad_files)
        raw = preparation_register.raw_orders_in_period(register, files.folder.period)
        if raw is not None:
            raise StopError(messages.raw_orders_not_ordered(register_path, raw.sheet, raw.first_row, raw.last_row))
        return files, worker_mapping, register

    files, worker_mapping, register = phases.check(check)
    folder = files.folder
    sheets = phases.read(lambda: preparation_register.period_sheets(register, folder.period))

    def plan_orders() -> tuple[Plan, CollectiveFilePlan, list[Message]]:
        plan = preparation_plan.plan_period_orders(register_path, sheets, folder.period, config_path, worker_mapping)
        collective = preparation_files.plan_period_files(files, len(plan.orders), plan.collective_rows)
        return plan, collective, _plan_warnings(register_path, files, plan, collective)

    plan, collective, warnings = phases.plan(plan_orders, issue_count=lambda planned: len(planned[2]))
    summary = PreparationSummary(
        internal_settlement_file=folder.internal_settlement,
        collective_file=folder.collective_file,
        period_order_count=len(plan.orders),
        successful_order_count=len(plan.collective_rows),
        skipped_empty_rows=plan.skipped_empty_rows,
        orders_per_day=plan.orders_per_day,
        warnings=warnings,
    )
    if not dry_run:
        decision = _incomplete_period_decision(register_path, plan, summary)
        if decision is not None and not conversation.confirm(decision):
            raise Declined(messages.incomplete_period_refused(period, conversation.continue_hint))

    def save_both() -> RouteCounts:
        if dry_run:
            return {}
        return preparation_files.write_period_files(files, plan.orders, plan.collective_rows)

    routes = phases.save(save_both)
    return replace(summary, phase_durations_ms=phases.durations_ms(), routes=routes)
