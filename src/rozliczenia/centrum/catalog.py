"""Katalog procesów Centrum rozliczeń: jeden wpis na każdy proces, który Centrum uruchamia, jako dane.

Wpis deklaruje to, o co Centrum pyta proces poza samym startem: klucz i nazwę procesu, widok Uruchomienia
(``run_view``), rdzeń procesu w ``Processes``, Ustawienia taty, bez których proces nie startuje, czytane Wzorce
i sprawdzenia Diagnozy w kolejności wyjaśniania. Diagnoza, Logi Uruchomienia, karty z Logów, Metryki, Konfiguracja
i start pytają wpis zamiast rozgałęziać się po kluczu procesu, a pliki procesu wynikają z jego Ustawień i Wzorców.

Kartę przed startem i wejście procesu buduje adapter startu procesu (``*_run.py``), jedyny czytelnik tej wiedzy:
proces z okresem przez ``runs.ProcessEntry``, Uporządkowanie INTERMAX własną kartą poza okresami (ADR 0019).

Moduł leży nisko w grafie importów: nie importuje ``runs``, ``diagnosis``, ``configuration`` ani FastAPI, więc
każdy moduł Centrum może go czytać bez cyklu.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Generic, Literal, TypeVar

from rozliczenia import (
    efenix_messages,
    efenix_process,
    intermax_messages,
    intermax_process,
    preparation_messages,
    preparation_process,
    settlement_messages,
    settlement_process,
)
from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.run_view import WarnedSummary
from rozliczenia.input_checks import WorkerConfigExplanation
from rozliczenia.message import Message
from rozliczenia.process_run import Process, ProcessInputs
from rozliczenia.settings import Settings

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=WarnedSummary)

SettingField = Literal["register", "periods_directory"]
# Wzorzec, który proces czyta; Konfiguracja wymienia każdy pod jego rolą.
TemplateRole = Literal["internal", "collective", "worker"]


@dataclass(frozen=True)
class NeededSetting:
    """Ścieżka z Ustawień taty, bez której proces nie startuje.

    ``name`` to nazwa dla taty w karcie, odmowie startu i Diagnozie, a ``missing`` Komunikat procesu o ścieżce
    wskazanej, której już nie ma.
    """

    name: str
    field: SettingField
    missing: Callable[[Path], Message]

    def chosen(self, settings: Settings) -> Path | None:
        match self.field:
            case "register":
                return settings.register
            case "periods_directory":
                return settings.periods_directory

    def existing(self, settings: Settings) -> Path | None:
        match self.field:
            case "register":
                return settings.existing_register
            case "periods_directory":
                return settings.existing_periods_directory


# Sprawdzenia Diagnozy jako dane: Diagnoza zamienia każdy krok na swoje sprawdzenie, a jego treść zostaje w niej.
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
]


@dataclass(frozen=True)
class WorkerConfigCheck:
    """„Konfiguracja wykonawców” Komunikatem ``explain``, którym zatrzymuje się proces."""

    explain: WorkerConfigExplanation


@dataclass(frozen=True)
class PeriodFolderCheck:
    """„Folder okresu”; ``collective_file_missing``: proces czyta Plik zbiorczy okresu, a jego brak to przyczyna."""

    collective_file_missing: Callable[[Path], Message] | None


CheckStep = SimpleCheck | WorkerConfigCheck | PeriodFolderCheck


def first_choose(missing: Sequence[NeededSetting]) -> str:
    """Zdanie odmowy „Najpierw wskaż …” z nazwami niewskazanych Ustawień ``missing``."""

    return f"Najpierw wskaż {' i '.join(setting.name for setting in missing)}."


@dataclass(frozen=True, kw_only=True)
class ProcessDeclaration(Generic[InputsT, SummaryT]):
    """Wpis katalogu procesów: wszystko, o co Centrum pyta proces poza budową karty przed startem i wejścia.

    ``title`` to nazwa rdzenia procesu, ``core`` wskazuje rdzeń w ``Processes`` (testy podmieniają rdzenie),
    ``settings`` to potrzebne Ustawienia taty w kolejności odmowy i Diagnozy, ``templates`` czytane Wzorce, a
    ``checks`` sprawdzenia Diagnozy w kolejności wyjaśniania: pierwsze, które nie przeszło, wyjaśnia Zatrzymanie.
    """

    key: contract.ProcessKey
    title: str
    view: run_view.ProcessView[InputsT, SummaryT]
    core: Callable[[Processes], Process[InputsT, SummaryT]]
    settings: tuple[NeededSetting, ...]
    templates: tuple[TemplateRole, ...]
    checks: tuple[CheckStep, ...]

    @property
    def reads_register(self) -> bool:
        """Rejestr zleceń jest plikiem procesu: proces go czyta."""

        return any(setting.field == "register" for setting in self.settings)

    @property
    def reads_period_folder(self) -> bool:
        """Proces należy do okresu: czyta i zapisuje pliki Folderu okresu."""

        return any(setting.field == "periods_directory" for setting in self.settings)

    def run_info(
        self, *, run_id: str, period: str, dry_run: bool, pricing: contract.Pricing | None
    ) -> contract.RunInfo:
        """Uruchomienie procesu na karcie: ta sama reguła na żywo i dla karty z Logów Uruchomienia.

        ``pricing`` ``None`` w procesie z trybami to Logi sprzed trybów, a wtedy Wycena w efenix biegła w pierwszym,
        domyślnym trybie; proces bez trybów nie ma trybu.
        """

        modes = self.view.pricing_modes
        return contract.RunInfo(
            id=run_id,
            process=self.key,
            title=self.title,
            period=period,
            dry_run=dry_run,
            pricing=None if not modes else modes[0] if pricing is None else pricing,
            confirms_readiness=self.view.confirms_readiness,
            register_name=self.view.register_name,
        )

    def settings_blocker(self, settings: Settings) -> str | None:
        """„Najpierw wskaż …” z nazwami niewskazanych Ustawień procesu; ``None``, gdy wszystkie są wskazane."""

        missing = [setting for setting in self.settings if setting.chosen(settings) is None]
        return first_choose(missing) if missing else None

    def required_paths(self, settings: Settings) -> Mapping[SettingField, Path]:
        """Wskazane ścieżki Ustawień procesu; ``contract.Refusal`` ze zdaniem ``settings_blocker``, gdy czegoś brakuje."""

        blocker = self.settings_blocker(settings)
        if blocker is not None:
            raise contract.Refusal(409, blocker)
        return {setting.field: path for setting in self.settings if (path := setting.chosen(settings)) is not None}


@dataclass(frozen=True, kw_only=True)
class PeriodProcessDeclaration(ProcessDeclaration[InputsT, SummaryT]):
    """Wpis procesu, który tata uruchamia z okresem na karcie okresów; Podgląd bez zapisu ma proces, którego widok to
    ``run_view.PeriodProcessView`` (Wycena w efenix go nie ma)."""

    key: contract.PeriodProcessKey


PERIODS_DIRECTORY: Final = NeededSetting(
    "folder okresów", "periods_directory", preparation_messages.periods_directory_missing
)
# Ogon każdej Diagnozy, po plikach taty: nowsze Wydanie wyjaśnia tylko bez innej przyczyny, bo przyczyny w plikach
# taty nowa wersja nie usuwa (ADR 0009); Token do Zgłoszeń nigdy nie wyjaśnia, tylko idzie do Zgłoszenia; dziennik
# idzie ostatni, po wpisach o sprawdzeniach, które same się nie udały.
_TAIL: Final[tuple[CheckStep, ...]] = ("tool_freshness", "report_key", "centrum_log")

# OneDrive idzie przed sprawdzeniami, które otwierają Rejestr zleceń, Wzorce i pliki okresu: plik tylko w chmurze
# może się nie otworzyć, a wtedy przyczyną jest OneDrive, nie uszkodzony plik.
PREPARATION: Final = PeriodProcessDeclaration(
    key="preparation",
    title=preparation_process.PROCESS.name,
    view=run_view.PREPARATION,
    core=lambda processes: processes.preparation,
    settings=(
        NeededSetting(run_view.PREPARATION.register_name, "register", preparation_messages.register_missing),
        PERIODS_DIRECTORY,
    ),
    templates=("internal", "collective"),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        "register",
        "templates",
        WorkerConfigCheck(preparation_messages.worker_config_problem),
        PeriodFolderCheck(collective_file_missing=None),
        "period_files_in_excel",
        *_TAIL,
    ),
)
SETTLEMENT: Final = PeriodProcessDeclaration(
    key="settlement",
    title=settlement_process.PROCESS.name,
    view=run_view.SETTLEMENT,
    core=lambda processes: processes.settlement,
    settings=(PERIODS_DIRECTORY,),
    templates=("worker",),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        "templates",
        WorkerConfigCheck(settlement_messages.worker_config_problem),
        PeriodFolderCheck(collective_file_missing=settlement_messages.collective_file_missing),
        "period_files_in_excel",
        *_TAIL,
    ),
)
# Wycena w efenix czyta Plik zbiorczy okresu i wycenia jego zlecenia w efenix; nie ma Podglądu bez zapisu ani Wzorców.
EFENIX: Final = PeriodProcessDeclaration(
    key="efenix",
    title=efenix_process.PROCESS.name,
    view=run_view.EFENIX,
    core=lambda processes: processes.efenix,
    settings=(PERIODS_DIRECTORY,),
    templates=(),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        PeriodFolderCheck(collective_file_missing=efenix_messages.collective_file_missing),
        "period_files_in_excel",
        *_TAIL,
    ),
)
# Uporządkowanie INTERMAX porządkuje dzień, nie okres (ADR 0019): czyta tylko INTERMAX z Ustawień taty.
INTERMAX: Final = ProcessDeclaration(
    key="intermax",
    title=intermax_process.PROCESS.name,
    view=run_view.INTERMAX,
    core=lambda processes: processes.intermax,
    settings=(NeededSetting(run_view.INTERMAX.register_name, "register", intermax_messages.register_missing),),
    templates=(),
    checks=("tata_settings", "files_in_onedrive", "intermax", *_TAIL),
)

# Kolejność statystyk w Metrykach.
CATALOG: Final[tuple[ProcessDeclaration[Any, Any], ...]] = (PREPARATION, SETTLEMENT, EFENIX, INTERMAX)
_BY_KEY: Final[Mapping[contract.ProcessKey, ProcessDeclaration[Any, Any]]] = {
    declaration.key: declaration for declaration in CATALOG
}


def declaration_of(key: contract.ProcessKey) -> ProcessDeclaration[Any, Any]:
    """Wpis procesu ``key``; klucz z dysku (Logi, plik ostatniego startu) zwalidował już kontrakt."""

    return _BY_KEY[key]
