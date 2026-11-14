"""Wpis procesu w katalogu procesów i Uruchomienie procesu gotowe do startu, to samo dla każdego gospodarza.

Wpis (``ProcessKind``) deklaruje wszystko, o co gospodarze pytają proces, więc Diagnoza, Logi Uruchomienia, karty
z Logów, Metryki, Konfiguracja i start pytają wpis zamiast rozgałęziać się po kluczu procesu. Wpisy zbiera katalog
(``catalog``).

Centrum rozliczeń (``period_start``, ``intermax_run``), Skrypt dla maszyn (``tools/uruchom_proces.py``) i odtworzenie
z Logów (``tools/lib/odtworzenie.py``) mówią, co mają, w języku potrzeb (``Start``, ``HostParts``), dostają
``PreparedRun`` z katalogu (``Catalog.prepared``) i prowadzą je przez ``PreparedRun.conduct``: to samo wejście, rdzeń,
widok, plik metryk i Kontekst Uruchomienia. Gospodarz daje tylko rozmówcę.

Granicę importów modułu opisuje i sprawdza ``tests/test_granice_importow.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Generic, Literal, Protocol, TypeGuard, TypeVar, final, get_args

from rozliczenia import preparation_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum import diagnosis_messages, refusal
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.domain import RunMode
from rozliczenia.centrum.run_logs import ProcessLogs
from rozliczenia.centrum.run_view import PeriodProcessView, ProcessView, Shown, WarnedSummary
from rozliczenia.centrum.settings.files import Bad, Read, Unreadable, usable
from rozliczenia.centrum.settings.folders import FolderSettings, SettingState
from rozliczenia.centrum.settings.owner import SettingsSnapshot
from rozliczenia.client_data import WithoutSubclasses
from rozliczenia.efenix_pace import Pace
from rozliczenia.efenix_pricing import NO_JOURNAL, OrderJournal
from rozliczenia.efenix_window import OpenEfenix
from rozliczenia.input_copy import InputCopy
from rozliczenia.intermax_replace import LOCAL_DISK, Disk, Waiting
from rozliczenia.message import Message
from rozliczenia.quantity_check import CheckResult
from rozliczenia.quantity_engine import QuantityRules
from rozliczenia.period_folder import PeriodStatus
from rozliczenia.process_run import Interlocutor, Outcome, Process, ProcessInputs
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.report_entering import ReportEnteringParts
from rozliczenia.run_context import RunContext
from rozliczenia.telemetry import MetricsStore
from rozliczenia.wall_clock import local_now
from rozliczenia.worker_list import WorkerList

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=WarnedSummary)

SettingField = Literal["register", "periods_directory"]
TemplateRole = Literal["internal", "collective", "worker"]
"""Wzorzec, który proces czyta; Konfiguracja wymienia każdy pod jego rolą."""
TemplateNeed = Literal["internal_template", "collective_template", "worker_template"]
ConfigurationNeed = TemplateNeed
"""Plik Konfiguracji (``configuration.ConfigurationFiles``): Wzorzec."""
PathNeed = Literal["register", "periods_directory", "collective_file", "copies_directory", ConfigurationNeed]
Need = PathNeed | Literal["period", "workers", "efenix_window", "worker_report_inbox"]
"""Czego wejście procesu potrzebuje od gospodarza, wspólnie dla trzech gospodarzy: Centrum wie, skąd wziąć każdą
ścieżkę (``period_start``, ``intermax_run``, ``report_entering_run``), Skrypt dla maszyn ma na nią flagę, a odtworzenie
odbudowuje ją z Logów. ``period``: token okresu (``Start.period``), ``workers``: Lista Wykonawców (``Start.workers``),
``efenix_window``: okno efenix gospodarza
(``HostParts.efenix``), ``worker_report_inbox``: Skrzynka raportów i pamięć własnych wpisów (``HostParts.reports``)."""


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
    """Start jednego Uruchomienia w języku potrzeb, ten sam dla Centrum, Skryptu dla maszyn i odtworzenia.

    ``paths`` ma ścieżkę każdej potrzeby-pliku procesu (sprawdza ``Catalog.prepared``). ``period``: token okresu, gdy
    gospodarz go zna (karta, ``--period``, Logi); ``None``: okres wynika z wejścia. ``pricing``: tryb Wyceny w efenix
    wybrany przy starcie; ``None``: nikt nie wybrał (proces bez trybów, Skrypt bez ``--z-przekazaniem`` albo Logi sprzed
    trybów), a tryb Uruchomienia daje ``ProcessKind.pricing_of``. ``settings``: migawka Ustawień Centrum z chwili
    startu, z której Logi Uruchomienia biorą pliki procesu, a Diagnoza Zatrzymania pliki i Listę Wykonawców; ``None``:
    gospodarz bez Ustawień Centrum (Skrypt dla maszyn, odtworzenie). ``workers``: Lista Wykonawców z chwili startu
    (Centrum: migawka Ustawień, Skrypt dla maszyn: plik ``--wykonawcy``, odtworzenie: lista z Logów); ``None``: proces
    jej nie potrzebuje. ``quantity_rules``: Reguły ilości, którymi liczy Uruchomienie, z migawki Ustawień Centrum z
    chwili startu; gospodarz bez Ustawień Centrum podaje Reguły ilości z Wydania. ``warnings``: ostrzeżenia startu na
    kartę i do Logów, fakt startu jak Lista Wykonawców (Centrum: ``start_from_settings`` z migawki Ustawień, Skrypt dla
    maszyn: brak, odtworzenie: ostrzeżenia startu z Logów). Ani ``quantity_rules``, ani ``warnings`` nie mają wartości
    domyślnej, więc każdy gospodarz mówi, skąd je ma.
    """

    paths: Mapping[PathNeed, Path]
    period: str | None
    dry_run: bool
    pricing: runs_contract.Pricing | None = None
    settings: SettingsSnapshot | None = None
    workers: WorkerList | None = None
    quantity_rules: QuantityRules = field(kw_only=True)
    warnings: tuple[Message, ...] = field(kw_only=True)

    def path(self, need: PathNeed) -> Path:
        return self.paths[need]

    def worker_list(self) -> WorkerList:
        assert self.workers is not None, "Catalog.prepared sprawdza potrzebę workers"
        return self.workers

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
) -> Start:
    """Start Uruchomienia z Centrum z migawki Ustawień z chwili startu (ADR 0032): migawka dla Logów i Diagnozy, Lista
    Wykonawców procesu, który jej potrzebuje (ostatnia dobra przy złym pliku; ``Refusal``, gdy jej nie ma), Reguły
    ilości i ostrzeżenia startu. Ścieżki, okres i tryb wybiera gospodarz."""

    return Start(
        paths, period=period, dry_run=dry_run, pricing=pricing, settings=settings,
        workers=_workers_at_start(settings.workers) if "workers" in kind.needs else None,
        quantity_rules=settings.quantity_rules, warnings=_start_warnings(settings, kind.needs),
    )


def _workers_at_start(workers: Read[WorkerList] | Unreadable) -> WorkerList:
    """Lista Wykonawców dla startu Uruchomienia z migawki Ustawień: dobra, a przy złym ustawieniu ostatnia dobra;
    ``Refusal``, gdy ostatniej dobrej nie ma albo pliku nie da się teraz przeczytać."""

    found = usable(workers)
    if found is None:
        raise refusal.workers_unusable(workers.problem if isinstance(workers, Bad) else None)
    return found


def _start_warnings(settings: SettingsSnapshot, needs: Sequence[Need]) -> tuple[Message, ...]:
    """Ostrzeżenia startu Uruchomienia procesu o potrzebach ``needs`` z migawki Ustawień Centrum (``Start.warnings``):
    proces z Listą Wykonawców biegnie na ostatniej dobrej liście, bo plik ma złe ustawienie."""

    workers = settings.workers
    if "workers" in needs and isinstance(workers, Bad) and workers.usable is not None:
        return (diagnosis_messages.worker_list_last_good(workers.problem.sentence),)
    return ()


@dataclass(frozen=True)
class EfenixOpening:
    """Okno efenix od gospodarza: jak je otworzyć i tempo ludzkie (``None``: bez przerw, tylko Atrapa efenix)."""

    open: OpenEfenix
    pace: Pace | None


@dataclass(frozen=True)
class HostParts:
    """Zależności jednego procesu, które daje gospodarz raz na swoje życie; domyślne to komputer bez Centrum.

    Centrum: okno efenix taty z tempem, dziennik Wyceny w efenix z Logów (``logs_disk.Journal``), zegar Centrum, przerwa
    ponownej próby podmiany INTERMAX, kroki podmiany na dysku oraz Skrzynka raportów w Gmailu z pamięcią własnych wpisów
    w ``config``. Skrypt dla maszyn i odtworzenie: okno Atrapy efenix (``efenix_chrome.atrapa_opening``), Skrzynka
    raportów z folderu maili ``.eml`` z pamięcią bez pliku, reszta domyślna (odtworzenie: ``now`` z Logów).
    """

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
    """Ścieżka z Ustawień Centrum, bez której proces nie startuje.

    ``name`` to nazwa dla taty w karcie, odmowie startu i Diagnozie, a ``missing`` Komunikat procesu o ścieżce
    wskazanej, której już nie ma.
    """

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
"""Sprawdzenia Diagnozy jako dane: Diagnoza zamienia każdy krok na swoje sprawdzenie, a jego treść zostaje w niej."""


@dataclass(frozen=True)
class PeriodFolderCheck:
    """„Folder okresu”; ``collective_file_missing``: proces czyta Plik zbiorczy okresu, a jego brak to przyczyna."""

    collective_file_missing: Callable[[Path], Message] | None


CheckStep = SimpleCheck | PeriodFolderCheck


PERIODS_DIRECTORY: Final = NeededSetting(
    "folder okresów", "periods_directory", preparation_messages.periods_directory_missing
)
TAIL: Final[tuple[CheckStep, ...]] = ("tool_freshness", "report_key", "centrum_log")
"""Ogon każdej Diagnozy, po plikach taty: nowsze Wydanie wyjaśnia tylko bez innej przyczyny, bo przyczyny w plikach
taty nowa wersja nie usuwa (ADR 0009); Token do Zgłoszeń nigdy nie wyjaśnia, tylko idzie do Zgłoszenia; dziennik idzie
ostatni, po wpisach o sprawdzeniach, które same się nie udały."""


@dataclass(frozen=True)
class ByStatus:
    """Okresy z Tablicy okresów o Statusie okresu z ``statuses``; ``none_ready``: blokada karty, gdy żadnego nie ma."""

    statuses: frozenset[PeriodStatus]
    none_ready: str


@dataclass(frozen=True)
class RecentWeeks:
    """Ostatnie ``weeks`` pełnych okresów ze Statusem z Folderu okresu: proces, który dopiero tworzy pliki okresu."""

    weeks: int


@dataclass(frozen=True)
class PeriodStart:
    """Karta startu procesu, który tata uruchamia z okresem: co powstaje (``creates``), jak wybrać okresy
    (``chooser``) i odmowa startu bez zapisu (``no_preview``)."""

    creates: str
    chooser: ByStatus | RecentWeeks
    no_preview: Refusal | None = None


@dataclass(frozen=True, kw_only=True)
class ProcessKind(Generic[InputsT, SummaryT]):
    """Wpis katalogu procesów: wszystko, o co gospodarze pytają proces.

    ``core`` to rdzeń procesu (testy podmieniają go przez ``Catalog.steered``), a ``default_metrics`` plik metryk
    procesu w katalogu narzędzia (testy i ``--metrics`` podmieniają go przez ``Catalog.with_metrics``); oba czyta się
    przez katalog. ``needs`` to potrzeby wejścia procesu, a ``inputs`` jedyna budowa wejścia z nich: czysta funkcja
    startu i zależności gospodarza, bez I/O. ``settings`` to potrzebne Ustawienia Centrum w kolejności odmowy i Diagnozy,
    a ``checks`` sprawdzenia Diagnozy w kolejności wyjaśniania: pierwsze, które nie przeszło, wyjaśnia Zatrzymanie.
    ``journaled``: proces pisze dziennik Wyceny w efenix (``logs_disk.LogsOnDisk``). ``short_title``: krótka nazwa
    procesu w filtrach Metryk. ``logs``: dodatki Logów Uruchomienia procesu (``run_logs.ProcessLogs``) z podsumowania
    silnika (``None``: Uruchomienie bez wyniku) i faktów Zatrzymania (``process_run.Stop.facts``; ``None`` bez nich).
    ``quantity_check``: Kontrola ilości Zleceń z podsumowania Regułami ilości tego Uruchomienia, po zapisie (ADR 0013);
    ``None``: proces bez Kontroli ilości. ``quantity_rules``: proces liczy Regułami ilości ze startu (``Start``), więc
    jego Uruchomienie ma je w Logach (``PreparedRun.quantity_rules``), a odtworzenie z Logów liczy nimi.
    """

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
    quantity_rules: bool = False

    def __post_init__(self) -> None:
        """Pierwszy tryb Wyceny to ``DEFAULT_PRICING``: Logi sprzed trybów nie mają trybu, a Wycena biegła wtedy bez
        Przekazania (ADR 0027)."""

        modes = self.view.pricing_modes
        assert not modes or modes[0] == runs_contract.DEFAULT_PRICING, f"{self.key}: pierwszy tryb to {runs_contract.DEFAULT_PRICING}"

    @property
    def title(self) -> str:
        """Nazwa procesu z GLOSSARY, ta sama na karcie, w Logach, Diagnozie i Metrykach co w rdzeniu."""

        return self.core.name

    @property
    def preview_hint(self) -> str | None:
        """Podpowiedź „Podgląd bez zapisu”; ``None``: proces bez Podglądu bez zapisu."""

        return self.view.preview_hint if isinstance(self.view, PeriodProcessView) else None

    @property
    def path_needs(self) -> tuple[PathNeed, ...]:
        """Potrzeby-pliki procesu: klucze ``Start.paths``."""

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
        """Proces należy do okresu: czyta i zapisuje pliki Folderu okresu."""

        return any(setting.field == "periods_directory" for setting in self.settings)

    def pricing_of(self, chosen: runs_contract.Pricing | None) -> runs_contract.Pricing | None:
        """Tryb Wyceny w efenix Uruchomienia, jedna reguła na żywo, w Skrypcie dla maszyn i dla Logów.

        Proces bez trybów nie ma trybu. ``chosen`` ``None`` w procesie z trybami (Logi sprzed trybów, Skrypt bez
        ``--z-przekazaniem``) to pierwszy, domyślny tryb. ``ValueError`` (błąd gospodarza), gdy ``chosen`` nie jest
        trybem procesu: odmowę dla taty daje wcześniej karta startu.
        """

        modes = self.view.pricing_modes
        if chosen is not None and chosen not in modes:
            raise ValueError(f"{self.title} nie ma trybu {chosen}")
        return None if not modes else modes[0] if chosen is None else chosen

    def run_info(
        self, *, run_id: str, period: str, mode: RunMode, pricing: runs_contract.Pricing | None
    ) -> runs_contract.RunInfo:
        """Uruchomienie procesu na karcie: ta sama reguła na żywo i dla karty z Logów Uruchomienia."""

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

    def settings_blocker(self, settings: FolderSettings) -> str | None:
        """„Najpierw wskaż …” z nazwami niewskazanych Ustawień procesu; ``None``, gdy wszystkie są wskazane."""

        unchosen = self._unchosen(settings)
        return None if unchosen is None else unchosen.message

    def _unchosen(self, settings: FolderSettings) -> Refusal | None:
        missing = [setting.name for setting in self.settings if setting.chosen(settings) is None]
        return refusal.first_choose(missing) if missing else None

    def required_paths(self, settings: FolderSettings) -> Mapping[SettingField, Path]:
        """Wskazane ścieżki Ustawień procesu; ``Refusal`` ze zdaniem ``settings_blocker``, gdy czegoś brakuje."""

        unchosen = self._unchosen(settings)
        if unchosen is not None:
            raise unchosen
        return {setting.field: path for setting in self.settings if (path := setting.chosen(settings)) is not None}


@dataclass(frozen=True, kw_only=True)
class PeriodProcessKind(ProcessKind[InputsT, SummaryT]):
    """Wpis procesu, który tata uruchamia z okresem z karty Uruchomień: ``start`` to polityka jego karty startu.

    Podgląd bez zapisu ma proces, którego widok to ``run_view.PeriodProcessView`` (Wycena w efenix go nie ma).
    """

    key: common_contract.PeriodProcessKey
    start: PeriodStart

    def __post_init__(self) -> None:
        super().__post_init__()
        assert (self.start.no_preview is None) is (self.core.preview is not None), (
            f"{self.key}: odmowa startu bez zapisu wtedy i tylko wtedy, gdy rdzeń nie ma Podglądu bez zapisu"
        )


class Engine(Protocol):
    """``process_run.run_process`` w tym, czego używa ``PreparedRun.conduct``."""

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
    """Typ dowodu, że Uruchomienie gotowe do startu złożył katalog procesów (``_CATALOG``)."""

    __slots__ = ()


_CATALOG: Final = _Catalog()
"""Dowód katalogu procesów: ``PreparedRun`` bez niego to błąd mypy (brak argumentu albo zły typ). Bierze go tylko
``Catalog.prepared``: poza tym modułem i ``catalog.py`` (prawo właściciela w ``pyproject.toml``) ruff (``TID251`` w ``pyproject.toml``)
odrzuca ``from … import _CATALOG`` (także z aliasem) i atrybut modułu (``process_kind._CATALOG``, także przez alias albo
pełną ścieżkę), tak samo ``_Catalog``.

``PreparedRun`` nie jest dataclassą, więc mypy odrzuca też ``dataclasses.replace`` gotowego Uruchomienia, np. z innym
plikiem metryk (``type-var``), a przypisanie jego pola (``Final``). Konstruktor ``PreparedRun`` poza ``catalog.py``
łapie po nazwie ``PreparedRun``, nazwie z importu albo atrybucie ``tests/test_granice_importow.py``, a odmowy podklasy
opisuje docstring ``PreparedRun`` (metaklasa przy tworzeniu, ``startable`` przy użyciu). Granice tych mechanizmów
pokazują tam próbki ``ZNANE_LUKI_KATALOGU``, każda za klasą nazwaną w swojej nazwie."""


_NO_SUBCLASSES: Final = (
    "Uruchomienie gotowe do startu nie ma podklas: składa je tylko Catalog.prepared, a rdzeń, plik metryk i silnik "
    "procesu podmienia Catalog.steered, Catalog.with_metrics i Catalog.with_engine."
)


@final
class PreparedRun(Generic[InputsT, SummaryT], metaclass=WithoutSubclasses, refusal=_NO_SUBCLASSES):
    """Uruchomienie procesu gotowe do startu: wpis procesu z katalogu (z rdzeniem katalogu), okres, wejście, Kontekst
    Uruchomienia (``run_context.RunContexts.new``) i historia metryk procesu z katalogu. ``pricing``: tryb Wyceny
    w efenix (``None``: proces bez trybów), ``settings``: migawka Ustawień Centrum ze startu (``Start.settings``),
    ``quantity_rules``: Reguły ilości ze startu (``Start.quantity_rules``) procesu, który nimi liczy
    (``ProcessKind.quantity_rules``; inny ma ``None``), dla Logów Uruchomienia,
    ``warnings``: ostrzeżenia startu na kartę i do Logów (``Start.warnings``), ``engine``: silnik z katalogu
    (``run_process``; inny daje tylko wyrocznia ``verify-jedno-uruchomienie-naraz`` przez ``Catalog.with_engine``).
    Powstaje tylko w ``Catalog.prepared`` (``_CATALOG``).

    Nie ma podklas: podklasa z własnym ``__init__`` albo ``conduct`` składałaby się sama, bez katalogu. Przy tworzeniu
    odmawia metaklasa (``client_data.WithoutSubclasses``) pod każdą nazwą i przy każdej kolejności baz, a
    ``__init_subclass__`` klasie zrobionej z pominięciem ``__new__`` metaklasy, gdy żadna wcześniejsza baza w MRO nie
    przesłania jego odmowy. Tworzenie nie zamyka klasy zrobionej z pominięciem ``__new__`` metaklasy ani relacji
    podklasy przypisanej w trakcie działania, więc regułę trzyma kontrola w chwili użycia (``startable``: typ dokładnie
    ``PreparedRun``, bez względu na to, jak powstała klasa obiektu): przed ``conduct`` w każdym miejscu, które go woła
    (``runs.Run.work``, Skrypt dla maszyn ``tools/uruchom_proces.py``, odtworzenie z Logów
    ``tools/lib/odtworzenie.py``), i na początku samego ``conduct``; ``startable`` w ``runs.Run.__init__`` mówi ją
    wcześniej, przy starcie w Centrum. Typ ``PreparedRun[…]`` w adnotacji podklasy nie robi. Odmowy przy tworzeniu
    i przy użyciu pokazują ``PODKLASY_GOTOWEGO_URUCHOMIENIA`` i ``URUCHOMIENIA_OBOK_KATALOGU``, a znane luki kontroli
    w chwili użycia próbki ``ZNANE_LUKI_STARTU`` w ``tests/test_katalog_procesow.py``.
    """

    __slots__ = (
        "context",
        "engine",
        "inputs",
        "kind",
        "metrics",
        "period",
        "pricing",
        "quantity_rules",
        "settings",
        "warnings",
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
        settings: SettingsSnapshot | None,
        warnings: tuple[Message, ...],
        quantity_rules: QuantityRules | None,
    ) -> None:
        self.kind: Final = kind
        self.period: Final = period
        self.inputs: Final = inputs
        self.context: Final = context
        self.metrics: Final = metrics
        self.pricing: Final = pricing
        self.engine: Final = engine
        self.settings: Final = settings
        self.warnings: Final = warnings
        self.quantity_rules: Final = quantity_rules

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(f"{_NO_SUBCLASSES} Podklasa: {cls.__qualname__}.")

    @property
    def dry_run(self) -> bool:
        return self.kind.core.dry_run(self.inputs)

    @property
    def input_copy(self) -> InputCopy | None:
        """Kopia wejścia, którą czytniki procesu wypełniają w trakcie Uruchomienia; ``None``: Uruchomienie bez Kopii."""

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
    """``run``, gdy w chwili tego wywołania jego typ to dokładnie ``PreparedRun``; obiekt podklasy, jakkolwiek powstała,
    także z ``__class__`` podmienionym przed tym wywołaniem, daje ``TypeError`` z drogą naprawy. Ta kontrola trzyma
    regułę „bez podklas”, bo odmowa metaklasy przy tworzeniu nie zamyka klasy zrobionej z pominięciem jej ``__new__``
    ani relacji podklasy przypisanej w trakcie działania. Miejsca, które wołają ``conduct``, wołają je na wyniku tej
    funkcji (``startable(run).conduct(…)``)."""

    if type(run) is not PreparedRun:
        raise TypeError(f"{_NO_SUBCLASSES} Start dostał {type(run).__qualname__}.")
    return run
