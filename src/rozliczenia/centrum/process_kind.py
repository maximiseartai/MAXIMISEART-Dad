from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Generic, Literal, Protocol, TypeGuard, TypeVar, final, get_args

from rozliczenia import preparation_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.domain import RunMode
from rozliczenia.centrum.run_logs import ProcessLogs
from rozliczenia.centrum.run_view import PeriodProcessView, ProcessView, Shown, WarnedSummary
from rozliczenia.centrum.settings.folders import FolderSettings, SettingState
from rozliczenia.centrum.settings.owner import SettingsSnapshot
from rozliczenia.centrum.settings_at_start import SettingNeed, SettingsAtStart, unreadable
from rozliczenia.client_data import WithoutSubclasses
from rozliczenia.efenix_pace import Pace
from rozliczenia.efenix_pricing import NO_JOURNAL, OrderJournal
from rozliczenia.efenix_window import OpenEfenix
from rozliczenia.input_copy import InputCopy
from rozliczenia.intermax_replace import LOCAL_DISK, Disk, Waiting
from rozliczenia.message import Message
from rozliczenia.quantity_check import CheckResult
from rozliczenia.period_folder import PeriodStatus
from rozliczenia.process_run import Interlocutor, Outcome, Process, ProcessInputs
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.report_entering import ReportEnteringParts
from rozliczenia.run_context import RunContext
from rozliczenia.telemetry import MetricsStore
from rozliczenia.wall_clock import local_now

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=WarnedSummary)

SettingField = Literal["register", "periods_directory"]
TemplateRole = Literal["internal", "collective", "worker"]
TemplateNeed = Literal["internal_template", "collective_template", "worker_template"]
ConfigurationNeed = TemplateNeed
PathNeed = Literal["register", "periods_directory", "collective_file", "copies_directory", ConfigurationNeed]
Need = PathNeed | SettingNeed | Literal["period", "efenix_window", "worker_report_inbox", "order_base"]


def _is_path(need: Need) -> TypeGuard[PathNeed]:
    return need in get_args(PathNeed)


def _is_configuration(need: Need) -> TypeGuard[ConfigurationNeed]:
    return need in get_args(ConfigurationNeed)


_TEMPLATE_ROLES: Final[Mapping[TemplateNeed, TemplateRole]] = {
    "internal_template": "internal",
    "collective_template": "collective",
    "worker_template": "worker",
}


@dataclass(frozen=True)
class Start:
    paths: Mapping[PathNeed, Path]
    period: str | None
    dry_run: bool
    pricing: runs_contract.Pricing | None = None
    settings: SettingsAtStart = field(kw_only=True)
    order_base: Path | None = field(default=None, kw_only=True)

    def path(self, need: PathNeed) -> Path:
        return self.paths[need]

    def token(self) -> str:
        assert self.period is not None, "Catalog.prepared sprawdza potrzebę period"
        return self.period


def start_from_settings(
    kind: ProcessKind[Any, Any],
    settings: SettingsSnapshot,
    paths: Mapping[PathNeed, Path],
    *,
    period: str | None,
    dry_run: bool,
    pricing: runs_contract.Pricing | None = None,
    order_base: Path | None = None,
) -> Start:
    return Start(
        paths,
        period=period,
        dry_run=dry_run,
        pricing=pricing,
        settings=SettingsAtStart.of_snapshot(settings, kind.needs),
        order_base=order_base,
    )


def chosen_settings(
    settings: SettingsSnapshot, needed: Sequence[NeededSetting], needs: Sequence[Need]
) -> dict[SettingField, Path] | Refusal:
    try:
        folders = settings.folders
    except Refusal as folders_unreadable:
        return folders_unreadable
    if (refused := unreadable(settings, needs)) is not None:
        return refused
    missing = [setting.name for setting in needed if setting.chosen(folders) is None]
    if missing:
        return refusal.first_choose(missing)
    return {setting.field: path for setting in needed if (path := setting.chosen(folders)) is not None}


@dataclass(frozen=True)
class EfenixOpening:
    open: OpenEfenix
    pace: Pace | None


@dataclass(frozen=True)
class HostParts:
    efenix: EfenixOpening | None = None
    journal: OrderJournal = NO_JOURNAL
    now: Callable[[], datetime] = local_now
    waiting: Waiting = field(default_factory=Waiting)
    disk: Disk = LOCAL_DISK
    reports: ReportEnteringParts | None = None

    def window(self) -> EfenixOpening:
        assert self.efenix is not None, "Catalog.prepared sprawdza potrzebę efenix_window"
        return self.efenix

    def report_entering(self) -> ReportEnteringParts:
        assert self.reports is not None, "Catalog.prepared sprawdza potrzebę worker_report_inbox"
        return self.reports


@dataclass(frozen=True)
class NeededSetting:
    name: str
    field: SettingField
    missing: Callable[[Path], Message]

    def chosen(self, settings: FolderSettings) -> Path | None:
        match self.field:
            case "register":
                return settings.register
            case "periods_directory":
                return settings.periods_directory

    def state(self, settings: FolderSettings) -> SettingState:
        match self.field:
            case "register":
                return settings.register_state
            case "periods_directory":
                return settings.periods_directory_state


SimpleCheck = Literal[
    "tata_settings",
    "files_in_onedrive",
    "register",
    "intermax",
    "templates",
    "period_files_in_excel",
    "tool_freshness",
    "report_key",
    "centrum_log",
    "worker_list",
]


@dataclass(frozen=True)
class PeriodFolderCheck:
    collective_file_missing: Callable[[Path], Message] | None


CheckStep = SimpleCheck | PeriodFolderCheck


PERIODS_DIRECTORY: Final = NeededSetting(
    "folder okresów", "periods_directory", preparation_messages.periods_directory_missing
)
TAIL: Final[tuple[CheckStep, ...]] = ("tool_freshness", "report_key", "centrum_log")


@dataclass(frozen=True)
class ByStatus:
    statuses: frozenset[PeriodStatus]
    none_ready: str


@dataclass(frozen=True)
class RecentWeeks:
    weeks: int


@dataclass(frozen=True)
class PeriodStart:
    creates: str
    chooser: ByStatus | RecentWeeks
    no_preview: Refusal | None = None


@dataclass(frozen=True, kw_only=True)
class ProcessKind(Generic[InputsT, SummaryT]):
    key: common_contract.ProcessKey
    short_title: str
    view: ProcessView[SummaryT]
    core: Process[InputsT, SummaryT, RunContext]
    default_metrics: Path
    needs: tuple[Need, ...]
    inputs: Callable[[Start, HostParts], InputsT]
    settings: tuple[NeededSetting, ...]
    checks: tuple[CheckStep, ...]
    journaled: bool = False
    logs: Callable[[SummaryT | None, object], ProcessLogs] = lambda _summary, _facts: ProcessLogs()
    quantity_check: Callable[[SummaryT], CheckResult] | None = None

    def __post_init__(self) -> None:
        modes = self.view.pricing_modes
        assert not modes or modes[0] == runs_contract.DEFAULT_PRICING, f"{self.key}: pierwszy tryb to {runs_contract.DEFAULT_PRICING}"

    @property
    def title(self) -> str:
        return self.core.name

    @property
    def preview_hint(self) -> str | None:
        return self.view.preview_hint if isinstance(self.view, PeriodProcessView) else None

    @property
    def path_needs(self) -> tuple[PathNeed, ...]:
        return tuple(need for need in self.needs if _is_path(need))

    @property
    def configuration_needs(self) -> tuple[ConfigurationNeed, ...]:
        return tuple(need for need in self.needs if _is_configuration(need))

    @property
    def templates(self) -> tuple[TemplateRole, ...]:
        return tuple(role for need, role in _TEMPLATE_ROLES.items() if need in self.needs)

    @property
    def reads_register(self) -> bool:
        return any(setting.field == "register" for setting in self.settings)

    @property
    def reads_period_folder(self) -> bool:
        return any(setting.field == "periods_directory" for setting in self.settings)

    def pricing_of(self, chosen: runs_contract.Pricing | None) -> runs_contract.Pricing | None:
        modes = self.view.pricing_modes
        if chosen is not None and chosen not in modes:
            raise ValueError(f"{self.title} nie ma trybu {chosen}")
        return None if not modes else modes[0] if chosen is None else chosen

    def run_info(
        self, *, run_id: str, period: str, mode: RunMode, pricing: runs_contract.Pricing | None
    ) -> runs_contract.RunInfo:
        return runs_contract.RunInfo(
            id=run_id,
            process=self.key,
            title=self.title,
            period=period,
            mode=mode,
            pricing=self.pricing_of(pricing),
            confirms_readiness=self.view.confirms_readiness,
            register_name=self.view.register_name,
        )

    def settings_blocker(self, settings: SettingsSnapshot) -> str | None:
        chosen = chosen_settings(settings, self.settings, self.needs)
        return chosen.message if isinstance(chosen, Refusal) else None

    def required_paths(self, settings: SettingsSnapshot) -> Mapping[SettingField, Path]:
        chosen = chosen_settings(settings, self.settings, self.needs)
        if isinstance(chosen, Refusal):
            raise chosen
        return chosen


@dataclass(frozen=True, kw_only=True)
class PeriodProcessKind(ProcessKind[InputsT, SummaryT]):
    key: common_contract.PeriodProcessKey
    start: PeriodStart

    def __post_init__(self) -> None:
        super().__post_init__()
        assert (self.start.no_preview is None) is (self.core.preview is not None), (
            f"{self.key}: odmowa startu bez zapisu wtedy i tylko wtedy, gdy rdzeń nie ma Podglądu bez zapisu"
        )


class Engine(Protocol):
    def __call__(
        self,
        process: Process[Any, Any, RunContext],
        inputs: ProcessInputs,
        interlocutor: Interlocutor,
        /,
        *,
        view: Callable[[Any, Any], Any],
        metrics_path: Path,
        context: RunContext,
    ) -> Outcome[Any]: ...


@final
class _Catalog:
    __slots__ = ()


_CATALOG: Final = _Catalog()


_NO_SUBCLASSES: Final = (
    "Uruchomienie gotowe do startu nie ma podklas: składa je tylko Catalog.prepared, a rdzeń, plik metryk i silnik "
    "procesu podmienia Catalog.steered, Catalog.with_metrics i Catalog.with_engine."
)


@final
class PreparedRun(Generic[InputsT, SummaryT], metaclass=WithoutSubclasses, refusal=_NO_SUBCLASSES):
    __slots__ = (
        "context",
        "engine",
        "inputs",
        "kind",
        "metrics",
        "period",
        "pricing",
        "settings",
    )

    def __init__(
        self,
        kind: ProcessKind[InputsT, SummaryT],
        period: str,
        inputs: InputsT,
        context: RunContext,
        metrics: MetricsStore,
        pricing: runs_contract.Pricing | None,
        engine: Engine,
        proof: _Catalog,
        settings: SettingsAtStart,
    ) -> None:
        self.kind: Final = kind
        self.period: Final = period
        self.inputs: Final = inputs
        self.context: Final = context
        self.metrics: Final = metrics
        self.pricing: Final = pricing
        self.engine: Final = engine
        self.settings: Final = settings

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(f"{_NO_SUBCLASSES} Podklasa: {cls.__qualname__}.")

    @property
    def dry_run(self) -> bool:
        return self.kind.core.dry_run(self.inputs)

    @property
    def input_copy(self) -> InputCopy | None:
        return self.context.files.copy

    def info(self, run_id: str) -> runs_contract.RunInfo:
        return self.kind.run_info(
            run_id=run_id, period=self.period, mode=RunMode.of(dry_run=self.dry_run), pricing=self.pricing
        )

    def conduct(self, interlocutor: Interlocutor) -> Outcome[Shown[SummaryT]]:
        startable(self)
        return self.engine(
            self.kind.core,
            self.inputs,
            interlocutor,
            view=lambda _inputs, summary: self.kind.view.shown(summary, dry_run=self.dry_run),
            metrics_path=self.metrics.path,
            context=self.context,
        )

    def progress_view(self, snapshot: ProgressSnapshot) -> runs_contract.Progress:
        return self.kind.view.progress(snapshot, dry_run=self.dry_run)


def startable(run: PreparedRun[Any, Any]) -> PreparedRun[Any, Any]:
    if type(run) is not PreparedRun:
        raise TypeError(f"{_NO_SUBCLASSES} Start dostał {type(run).__qualname__}.")
    return run
