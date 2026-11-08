"""Wpis procesu w katalogu procesów i Uruchomienie procesu gotowe do startu, to samo dla każdego gospodarza.

Wpis (``ProcessKind``) deklaruje to, o co Centrum pyta proces poza budową karty przed startem i wejścia: klucz procesu,
widok Uruchomienia, rdzeń procesu i jego domyślny plik metryk, Ustawienia taty, bez których proces nie startuje,
czytane Wzorce i sprawdzenia Diagnozy w kolejności wyjaśniania. Diagnoza, Logi Uruchomienia, karty z Logów, Metryki,
Konfiguracja i start pytają wpis zamiast rozgałęziać się po kluczu procesu. Wpisy zbiera katalog (``catalog``).

Centrum rozliczeń (``runs.Run``), Skrypt dla maszyn (``tools/uruchom_proces.py``) i odtworzenie z Logów
(``tools/lib/odtworzenie.py``) dostają ``PreparedRun`` z katalogu (``Catalog.prepared``) i prowadzą je przez
``PreparedRun.conduct``: ten sam rdzeń, widok, plik metryk i Kontekst Uruchomienia. Gospodarz daje tylko rozmówcę.

Moduł nie wczytuje ``runs``, Diagnozy, Konfiguracji, Tablicy okresów, okna efenix ani FastAPI, także przez inne moduły
(``tests/test_granice_importow.py``): każdy moduł Centrum i gospodarze bez serwera biorą go bez cyklu.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Generic, Literal, TypeVar

from rozliczenia import preparation_messages
from rozliczenia.centrum import contract
from rozliczenia.centrum.run_view import PeriodProcessView, ProcessView, Shown, WarnedSummary
from rozliczenia.centrum.settings import Settings
from rozliczenia.input_copy import InputCopy
from rozliczenia.message import Message
from rozliczenia.process_run import Interlocutor, Outcome, Process, ProcessInputs, run_process
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.run_context import RunContext
from rozliczenia.telemetry import MetricsStore

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
    "worker_config",
]


@dataclass(frozen=True)
class PeriodFolderCheck:
    """„Folder okresu”; ``collective_file_missing``: proces czyta Plik zbiorczy okresu, a jego brak to przyczyna."""

    collective_file_missing: Callable[[Path], Message] | None


CheckStep = SimpleCheck | PeriodFolderCheck


def first_choose(missing: Sequence[NeededSetting]) -> str:
    """Zdanie odmowy „Najpierw wskaż …” z nazwami niewskazanych Ustawień ``missing``."""

    return f"Najpierw wskaż {' i '.join(setting.name for setting in missing)}."


PERIODS_DIRECTORY: Final = NeededSetting(
    "folder okresów", "periods_directory", preparation_messages.periods_directory_missing
)
# Ogon każdej Diagnozy, po plikach taty: nowsze Wydanie wyjaśnia tylko bez innej przyczyny, bo przyczyny w plikach
# taty nowa wersja nie usuwa (ADR 0009); Token do Zgłoszeń nigdy nie wyjaśnia, tylko idzie do Zgłoszenia; dziennik
# idzie ostatni, po wpisach o sprawdzeniach, które same się nie udały.
TAIL: Final[tuple[CheckStep, ...]] = ("tool_freshness", "report_key", "centrum_log")


@dataclass(frozen=True, kw_only=True)
class ProcessKind(Generic[InputsT, SummaryT]):
    """Wpis katalogu procesów: wszystko, o co Centrum pyta proces poza budową karty przed startem i wejścia.

    ``core`` to rdzeń procesu (testy podmieniają go przez ``Catalog.steered``), a ``default_metrics`` plik metryk
    procesu w katalogu narzędzia (testy i ``--metrics`` podmieniają go przez ``Catalog.with_metrics``); oba czyta się
    przez katalog. ``settings`` to potrzebne Ustawienia taty w kolejności odmowy i Diagnozy, ``templates`` czytane
    Wzorce, a ``checks`` sprawdzenia Diagnozy w kolejności wyjaśniania: pierwsze, które nie przeszło, wyjaśnia
    Zatrzymanie.
    """

    key: contract.ProcessKey
    view: ProcessView[InputsT, SummaryT]
    core: Process[InputsT, SummaryT, RunContext]
    default_metrics: Path
    settings: tuple[NeededSetting, ...]
    templates: tuple[TemplateRole, ...]
    checks: tuple[CheckStep, ...]

    @property
    def title(self) -> str:
        """Nazwa procesu z GLOSSARY, ta sama na karcie, w Logach, Diagnozie i Metrykach co w rdzeniu."""

        return self.core.name

    @property
    def preview_hint(self) -> str | None:
        """Podpowiedź „Podgląd bez zapisu”; ``None``: proces bez Podglądu bez zapisu."""

        return self.view.preview_hint if isinstance(self.view, PeriodProcessView) else None

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
class PeriodProcessKind(ProcessKind[InputsT, SummaryT]):
    """Wpis procesu, który tata uruchamia z okresem na karcie okresów; Podgląd bez zapisu ma proces, którego widok to
    ``run_view.PeriodProcessView`` (Wycena w efenix go nie ma)."""

    key: contract.PeriodProcessKey


@dataclass(frozen=True)
class PreparedRun(Generic[InputsT, SummaryT]):
    """Uruchomienie procesu gotowe do startu: wpis procesu z katalogu (z rdzeniem katalogu), okres, wejście, Kontekst
    Uruchomienia (``run_context.RunContexts.new``) i historia metryk procesu z katalogu. ``pricing``: tryb Wyceny
    w efenix (``None``: proces bez trybów). Powstaje tylko w ``Catalog.prepared``.
    """

    kind: ProcessKind[InputsT, SummaryT]
    period: str
    inputs: InputsT
    context: RunContext
    metrics: MetricsStore
    pricing: contract.Pricing | None = None

    @property
    def dry_run(self) -> bool:
        return self.inputs.dry_run

    @property
    def input_copy(self) -> InputCopy | None:
        """Kopia wejścia, którą czytniki procesu wypełniają w trakcie Uruchomienia; ``None``: Uruchomienie bez Kopii."""

        return self.context.files.copy

    def info(self, run_id: str) -> contract.RunInfo:
        """Uruchomienie ``run_id`` na karcie: na żywo w Centrum i w Logach odtworzenia ta sama reguła wpisu procesu."""

        return self.kind.run_info(run_id=run_id, period=self.period, dry_run=self.dry_run, pricing=self.pricing)

    def conduct(self, interlocutor: Interlocutor) -> Outcome[Shown[SummaryT]]:
        """Uruchomienie przez rdzeń z rozmówcą ``interlocutor`` i plikiem metryk procesu."""

        return run_process(
            self.kind.core,
            self.inputs,
            interlocutor,
            view=self.kind.view.shown,
            metrics_path=self.metrics.path,
            context=self.context,
        )

    def progress_view(self, snapshot: ProgressSnapshot) -> contract.Progress:
        return self.kind.view.progress(snapshot, dry_run=self.dry_run)
