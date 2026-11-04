"""Przygotowanie pliku zbiorczego: z Rejestru zleceń do Rozliczenia wewnętrznego i Pliku zbiorczego.

Jedyną operacją publiczną jest ``prepare_collective_file()``. Silnik nie
proponuje okresu; pyta tylko o Decyzję taty o niepełnym okresie, przez
rozmowę od rdzenia Uruchomienia procesu (``decision.Conversation``), i sam
zatrzymuje się po odmowie. Zatrzymania zgłasza jako ``StopError`` z
Komunikatem dla taty, a wynik nie zawiera danych klientów.

Ten moduł sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty planu na ostrzeżenia i Decyzję taty o niepełnym
okresie, o którą pyta między Planowaniem a Zapisywaniem, a fakt Sprawdzania o Surowych zleceniach w okresie na
Zatrzymanie przed odczytem i zapisem.
Sprawdzanie i odczyt Rejestru zleceń przez czytniki są w ``input_checks``, wybór zleceń okresu i reguły zleceń w ``preparation_plan``,
Ilości usług zleceń w ``quantity_rules`` (wyznaczane w Planowaniu, więc podgląd bez zapisu ma te same ostrzeżenia
ilości co zapis), a wzorce i zapis plików okresu w ``preparation_files``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
import time
from types import MappingProxyType

from . import TOOL_ROOT, input_checks, preparation_files, preparation_plan
from . import preparation_messages as messages
from .client_data import ForbiddenValues
from .decision import Conversation, Decision, Declined
from .domain import ProgressObserver, ProgressPhase
from .input_checks import FILE_READERS, Readers
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .preparation_files import CollectiveFilePlan
from .preparation_plan import IncompletePeriod, Plan
from .quantity_rules import DESCRIPTION_COLUMNS, WEEKDAY_LABELS
from .template_file import RouteCounts

__all__ = [
    "PreparationSummary",
    "default_collective_template_path",
    "default_internal_template_path",
    "prepare_collective_file",
]


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
            (f"{WEEKDAY_LABELS[day.weekday()]} {day:%d.%m.%Y}", count)
            for day, count in self.orders_per_day.items()
        ]


def default_internal_template_path() -> Path:
    """Wzorzec rozliczenia wewnętrznego w katalogu konfiguracji obok Wzorca rozliczenia pracownika."""

    return TOOL_ROOT / "config" / "Wzorzec rozliczenia wewnętrznego.xlsx"


def default_collective_template_path() -> Path:
    """Wzorzec pliku zbiorczego w katalogu konfiguracji obok Wzorca rozliczenia pracownika."""

    return TOOL_ROOT / "config" / "Wzorzec pliku zbiorczego.xlsx"


def _incomplete_period_warning(register_path: Path, plan: Plan, incomplete: IncompletePeriod) -> Message:
    return messages.incomplete_period(
        register_path, plan.sheet, plan.period.token, incomplete.last_order_day, incomplete.monday
    )


def _plan_warnings(
    register_path: Path, files: preparation_files.PeriodFiles, plan: Plan, collective: CollectiveFilePlan
) -> list[Message]:
    """Ostrzeżenia z faktów planu: najpierw o Rejestrze zleceń, potem o wierszach Pliku zbiorczego."""

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
    """Decyzja taty o niepełnym okresie, gdy plan ma taki fakt."""

    if plan.incomplete_period is None:
        return None
    return Decision(
        title=messages.INCOMPLETE_PERIOD_TITLE,
        message=_incomplete_period_warning(register_path, plan, plan.incomplete_period),
        counts_title=messages.ORDERS_PER_DAY,
        counts=summary.labeled_orders_per_day(),
        question=messages.INCOMPLETE_PERIOD_QUESTION,
    )


def prepare_collective_file(
    register_path: Path,
    periods_directory: Path,
    period: str,
    config_path: Path,
    *,
    internal_template_path: Path | None = None,
    collective_template_path: Path | None = None,
    dry_run: bool = False,
    observer: ProgressObserver | None = None,
    conversation: Conversation | None = None,
    clock: Callable[[], float] = time.perf_counter,
    readers: Readers = FILE_READERS,
    forbidden: ForbiddenValues | None = None,
) -> PreparationSummary:
    """Tworzy w Folderze okresu razem Rozliczenie wewnętrzne i Plik zbiorczy.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie; wtedy nie
    powstaje żaden plik ani nowy Folder okresu, chyba że komunikat wskazuje plik
    okresu, którego po nieudanym zapisie nie udało się usunąć. Rejestr zleceń i
    wzorce są tylko czytane.

    ``dry_run=True`` wykonuje te same sprawdzenia, odczyt i planowanie, a etap
    Zapisywanie kończy bez tworzenia czegokolwiek (także Folderu okresu). Wynik
    jest wtedy planem z tymi samymi liczbami, ostrzeżeniami i nazwami plików.

    ``conversation`` to rozmowa z tatą od rdzenia Uruchomienia procesu. Przy
    zapisie, gdy plan ma ostrzeżenie o niepełnym okresie, Przygotowanie po
    Planowaniu, a przed Zapisywaniem pyta przez nią o Decyzję taty; odmowa to
    ``Declined`` bez zapisu, z podpowiedzią zgody tego rozmówcy. Czas
    czekania na Decyzję nie wlicza się do czasów etapów. Bez rozmowy
    Przygotowanie o nic nie pyta. ``clock`` to zegar w sekundach, z którego
    liczone są czasy etapów. ``readers`` czytają Rejestr zleceń i wzorce w Sprawdzaniu i Odczycie danych, a komórki
    zakazanych kolumn Rejestru poznaje ``forbidden`` (reguła danych, ADR 0025).
    """

    phases = PhaseRunner(observer, clock=clock)
    register_path = register_path.expanduser().resolve()
    periods_directory = periods_directory.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    internal_template = (internal_template_path or default_internal_template_path()).expanduser().resolve()
    collective_template = (collective_template_path or default_collective_template_path()).expanduser().resolve()

    def check() -> tuple[preparation_files.PeriodFiles, dict[str, str]]:
        checked = input_checks.check_preparation(
            register_path,
            periods_directory,
            period,
            config_path,
            internal_template=internal_template,
            collective_template=collective_template,
            readers=readers,
        )
        raw = input_checks.raw_orders_in_period(register_path, checked[0].folder.period, forbidden)
        if raw is not None:
            raise StopError(messages.raw_orders_not_ordered(register_path, raw.sheet, raw.first_row, raw.last_row))
        return checked

    files, worker_mapping = phases.check(check)
    folder = files.folder
    register = phases.read(lambda: input_checks.read_register(register_path, folder.period, readers, forbidden))

    def plan_orders() -> tuple[Plan, CollectiveFilePlan, list[Message]]:
        plan = preparation_plan.plan_period_orders(register_path, register, folder.period, config_path, worker_mapping)
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
    if conversation is not None and not dry_run:
        decision = _incomplete_period_decision(register_path, plan, summary)
        if decision is not None:
            with phases.paused():
                consent = conversation.confirm(decision)
            if not consent:
                raise Declined(messages.incomplete_period_refused(period, conversation.continue_hint))

    def save_both() -> RouteCounts:
        if dry_run:
            return {}
        return preparation_files.write_period_files(files, plan.orders, plan.collective_rows)

    routes = phases.save(save_both)
    return replace(summary, phase_durations_ms=phases.durations_ms(), routes=routes)
