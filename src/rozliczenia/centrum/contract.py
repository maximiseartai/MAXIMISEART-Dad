"""Kontrakt serwer ↔ przeglądarka: modele odpowiedzi i żądań Centrum rozliczeń.

Z tych modeli powstaje OpenAPI, a z niego schematy zod i typy w
``frontend/src/api/generated`` (``npm run contract`` w ``frontend/``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from rozliczenia import domain
from rozliczenia.message import DadFile, Message as ProcessMessage
from rozliczenia.period_folder import PeriodPlace, PeriodStatus
from rozliczenia.process_run import StopEnding
from rozliczenia.quantities_to_fill import CellSource, FillKind, RowState


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Problem(_Model):
    """Odmowa wykonania żądania z bezpiecznym komunikatem dla taty, bez tekstu wyjątku."""

    message: str


class Refusal(Exception):
    """Serwer odmawia żądania; ``create_app`` zamienia odmowę na odpowiedź ``Problem``."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# Odmowy akcji na zasobie w OpenAPI: brak zasobu (404) albo zły stan (409), obie jako ``Problem``.
NOT_FOUND_OR_CONFLICT: dict[int | str, dict[str, object]] = {404: {"model": Problem}, 409: {"model": Problem}}


class Health(_Model):
    """Tożsamość działającego Centrum.

    ``commit`` to skrócony commit narzędzia, z którego Centrum wystartowało, jak na Konfiguracji (``None`` poza
    klonem Gita); po nim launcher i opiekun ponownego startu rozpoznają wersję działającego Centrum, a karta
    pokazuje go w „Zaktualizowano”. ``instance`` to losowy identyfikator tego startu Centrum: po ponownym starcie
    jest inny, także gdy commit się nie zmienił.
    """

    service: Literal["centrum-rozliczen"]
    commit: str | None
    instance: str


class Closing(_Model):
    """Centrum przyjęło prośbę o zamknięcie i kończy pracę po tej odpowiedzi."""

    state: Literal["closing"]


class NotSetPath(_Model):
    """Ścieżka jeszcze niewskazana albo plik ustawień nieczytelny."""

    state: Literal["not_set"]


class MissingPath(_Model):
    """Zapamiętana ścieżka, pod którą nie ma już pliku albo folderu."""

    state: Literal["missing"]
    path: str
    name: str


class ReadyPath(_Model):
    state: Literal["ready"]
    path: str
    name: str


PathSetting = Annotated[NotSetPath | MissingPath | ReadyPath, Field(discriminator="state")]
Theme = Literal["dark", "light"]


class Settings(_Model):
    order_register: PathSetting
    periods_directory: PathSetting
    theme: Theme


class Choice(_Model):
    """Ustawienia po natywnym oknie wyboru: wybór zapisuje ścieżkę, anulowanie niczego nie zmienia."""

    settings: Settings


class ThemeChange(_Model):
    theme: Theme


# Każdy proces ma klucz, ten sam w Uruchomieniach i w Metrykach.
ProcessKey = Literal["preparation", "settlement", "efenix", "intermax"]
# Proces, którego Uruchomienie tata wybiera z okresem; Uporządkowanie INTERMAX ma własną kartę poza okresami.
PeriodProcessKey = Literal["preparation", "settlement", "efenix"]
# Krok okresu, który robi proces.
StepAction = Literal["prepare_collective_file", "price_in_efenix", "create_worker_settlements"]


class ProcessStep(_Model):
    """Krok okresu, który robi proces ``process``; ``preview_hint`` to podpowiedź „Podgląd bez zapisu” tego procesu, a
    ``None`` ma proces bez podglądu (Wycena w efenix)."""

    action: StepAction
    process: PeriodProcessKey
    label: str
    hint: str
    preview_hint: str | None


class FillStep(_Model):
    """Uzupełnienie w Excelu: tata robi je w Excelu, Centrum prowadzi na podsumowanie Uzupełnienia pliku zbiorczego;
    ``then`` to krok po nim, Wycena w efenix."""

    action: Literal["fill_collective_file"]
    label: str
    hint: str
    then: ProcessStep


class ClosedStep(_Model):
    """Okres jest zamknięty: następnego kroku nie robi żaden proces."""

    action: Literal["none"]
    label: str
    hint: str


NextStep = Annotated[ProcessStep | FillStep | ClosedStep, Field(discriminator="action")]

PathStage = Literal["done", "now", "later", "not_done"]


class PathStep(_Model):
    """Krok Drogi okresu: ``now`` to pierwszy niezrobiony krok okresu otwartego, ``not_done`` krok, którego okres
    zamknięty nie zrobił (Wycena w efenix bez wyniku OK)."""

    label: str
    stage: PathStage


class PeriodRow(_Model):
    """Jeden okres Tablicy okresów, wyliczony przy każdym odczycie z plików i z Historii Wyceny w efenix."""

    token: str
    tuesday: date
    monday: date
    status: PeriodStatus
    status_label: str
    period_folder_exists: bool
    internal_settlement_exists: bool
    collective_file_exists: bool
    worker_settlements_folder_exists: bool
    worker_settlement_count: int
    last_complete: bool
    fillable: bool
    """Plik zbiorczy jest przygotowany, więc „Uzupełnij” prowadzi na podsumowanie jego Uzupełnienia."""
    path: list[PathStep]
    next_step: NextStep
    secondary_step: ProcessStep | None
    """Krok osiągalny obok następnego: Przebieg rozliczeń przed zaliczoną Wyceną w efenix; ``None``: żadnego."""


class BoardNotSet(_Model):
    state: Literal["not_set"]


class BoardMissing(_Model):
    state: Literal["missing"]
    name: str


class BoardReady(_Model):
    """Okresy od najnowszego; ``last_prepared_period`` to najnowszy okres z Plikiem zbiorczym."""

    state: Literal["ready"]
    periods: list[PeriodRow]
    last_prepared_period: str | None


PeriodBoard = Annotated[BoardNotSet | BoardMissing | BoardReady, Field(discriminator="state")]

class OpenRequest(_Model):
    """Co otworzyć w okresie; ścieżkę wylicza serwer z folderu okresów, nigdy z żądania."""

    target: PeriodPlace


class WorkerSettlementRequest(_Model):
    """Którego Wykonawcy Rozliczenie pracownika otworzyć; ścieżkę wylicza serwer z Folderu okresu."""

    worker: str


class Opened(_Model):
    name: str


RunMode = Literal["RUN", "DRY-RUN"]
Pricing = Literal["bez Przekazania", "z Przekazaniem"]
"""Tryb Wyceny w efenix (wartości ``efenix_pricing.PricingMode``, ADR 0027): bez Przekazania do akceptacji gotowych
zleceń albo z nim."""
DEFAULT_PRICING: Final[Pricing] = "bez Przekazania"
"""Tryb startu, w którym nikt trybu nie wybrał: proces bez trybów i żądanie bez pola (ADR 0027)."""
RunResult = Literal["OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"]
# Rodzaj Zatrzymania zapisany w metrykach, bez powtórki, którą Centrum pamięta tylko do zamknięcia.
RecordedStopKind = domain.StopKind


class PhaseDuration(_Model):
    phase: str
    duration_ms: int


class ProcessRun(_Model):
    """Jedno Uruchomienie procesu z pliku metryk; ``BLAD_KRYTYCZNY`` to przerwane, z czasami etapów do przerwania.

    ``origin`` mówi, skąd wystartowało: ``centrum`` to Centrum rozliczeń, ``cmd`` każde inne źródło
    rekordu: Uruchomienia z dawnych launcherów ``.cmd`` i CLI oraz ze skryptu dla maszyn.
    ``stop_kind`` to Rodzaj Zatrzymania przerwanego; ``None`` przy ukończonym i przy przerwanym ze starego
    rekordu, który rodzaju nie zapisał. ``run_id`` to identyfikator Uruchomienia z Centrum, ten sam co w jego
    Logach Uruchomienia, po którym okno Uwagi taty przypina do niego Uwagę; ``None`` przy ``cmd`` i przy
    Uruchomieniu z Centrum sprzed #322, które identyfikatora nie zapamiętało.
    """

    process: ProcessKey
    process_label: str
    started_at: datetime
    mode: RunMode
    period: str
    result: RunResult
    total_duration_ms: int
    phase_durations: list[PhaseDuration]
    origin: Literal["cmd", "centrum"]
    stop_kind: RecordedStopKind | None
    run_id: str | None


class PinnableRun(_Model):
    """Uruchomienie z Centrum, do którego tata może przypiąć Uwagę: to, co o nim mówi wiersz okna Uwagi i stopka.

    Pola jak w ``ProcessRun``, z którego powstaje; identyfikator jest zawsze, bo bez niego nie ma czego przypiąć.
    """

    run_id: str
    process_label: str
    started_at: datetime
    mode: RunMode
    period: str
    result: RunResult
    stop_kind: RecordedStopKind | None


class PhasePercentiles(_Model):
    phase: str
    p50_ms: int
    p95_ms: int


class Percentiles(_Model):
    """P50 i P95 czasu całego Uruchomienia procesu i każdego etapu, w milisekundach."""

    p50_ms: int
    p95_ms: int
    phases: list[PhasePercentiles]


class ResultCounts(_Model):
    """Wyniki Uruchomień procesu; przerwane dzielą się na ``stopped`` i ``failed``.

    ``stopped``: Zatrzymania „dla taty” i przerwane ze starych rekordów bez rodzaju. ``failed``: Zatrzymania
    „do Maksa”, także nieoczekiwany wyjątek.
    """

    ok: int
    needs_review: int
    stopped: int
    failed: int


class ModeStatistics(_Model):
    """Statystyki jednego procesu w jednym trybie; bez ``percentiles`` poniżej minimum ukończonych obserwacji."""

    process: ProcessKey
    mode: RunMode
    completed_runs: int
    percentiles: Percentiles | None
    results: ResultCounts


class RecentResults(_Model):
    """Wyniki Uruchomień procesu obu procesów z ostatnich ``weeks`` tygodni."""

    weeks: int
    results: ResultCounts


class ProcessFacts(_Model):
    """Proces w Metrykach: klucz i krótka nazwa w filtrach."""

    process: ProcessKey
    label: str


class Metrics(_Model):
    """Historia Uruchomień procesu z obu plików metryk, czytanych przy każdym odczycie, od najnowszego.

    ``processes``: procesy w kolejności statystyk; pierwszy jest wybrany w filtrze."""

    processes: list[ProcessFacts]
    phases: list[str]
    minimum_completed_runs: int
    runs: list[ProcessRun]
    statistics: list[ModeStatistics]
    recent: RecentResults


# Uruchomienia procesu.
PhaseName = Literal["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]


class PeriodChoice(_Model):
    """Okres do wyboru przy starcie, ze Statusem okresu wyliczonym z plików."""

    token: str
    tuesday: date
    monday: date
    status_label: str
    last_complete: bool
    # W historii metryk jest udany podgląd bez zapisu tego procesu i okresu.
    previewed: bool
    # Nazwa Pliku zbiorczego okresu, gdy proces go czyta (Przebieg rozliczeń); tata go nie wskazuje.
    collective_file: str | None
    # Zdania o skoroszytach wejściowych procesu otwartych w Excelu: najpierw plik danych, potem Wzorce.
    open_in_excel: list[str]
    # Przypomnienie w stopce karty startu przy tym okresie; brak, gdy „Uruchom” blokuje tylko otwarty Wzorzec.
    reminder: str | None


class ProcessSetup(_Model):
    """Co tata wybiera przed Uruchomieniem procesu; ``blocker`` mówi, czego jeszcze brakuje w ustawieniach.

    ``reminder``, ``confirms_readiness`` i ``preview_hint`` deklaruje proces: przypomnienie przed
    uruchomieniem, czy „Uruchom” potwierdza Gotowość, i podpowiedź „Podgląd bez zapisu” (``None``: proces nie ma
    podglądu bez zapisu, jak Wycena w efenix). ``pricing_modes``: tryby Wyceny w efenix, z których tata wybiera
    przyciskiem przy każdym starcie, w kolejności przycisków (pusta lista: proces bez trybów i z jednym „Uruchom”).
    ``reads``: plik danych procesu, Rejestr zleceń z Ustawień albo Plik zbiorczy wybranego okresu.
    """

    process: PeriodProcessKey
    title: str
    creates: str
    reads: Literal["register", "collective_file"]
    reminder: str
    confirms_readiness: bool
    preview_hint: str | None
    pricing_modes: list[Pricing]
    periods: list[PeriodChoice]
    preselected_period: str
    blocker: str | None


class RunSetup(_Model):
    processes: list[ProcessSetup]


class RunRequest(_Model):
    """Start Uruchomienia procesu; pliki wejściowe wylicza serwer z ustawień i okresu.

    ``pricing``: tryb Wyceny w efenix, który tata wybrał przyciskiem; proces bez trybów przyjmuje tylko domyślny.
    """

    process: PeriodProcessKey
    period: str
    dry_run: bool
    pricing: Pricing = DEFAULT_PRICING


class PhaseProgress(_Model):
    phase: PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int


class Figure(_Model):
    """Liczba karty Uruchomienia z etykietą; ``unit`` ``ms`` to czas, który przeglądarka pokazuje w sekundach."""

    label: str
    value: int
    unit: Literal["count", "ms"]


class ProgressStep(_Model):
    """Krok Zapisywania procesu bez Szablonów pracowników (Wycena w efenix): co trwa, u którego Wykonawcy i ile z ilu.

    ``total`` 0: krok bez liczenia (logowanie, Znaczniki efenix), który karta pokazuje jako trwający.
    """

    label: str
    worker: str | None
    done: int
    total: int


class Progress(_Model):
    """Wyświetlany podzbiór snapshotu jedynej projekcji postępu (ADR 0002): etapy, Szablony pracowników i liczby.

    ``step``: ostatni krok Zapisywania procesu bez Szablonów pracowników; ``None`` w innych procesach i przed nim.
    """

    phases: list[PhaseProgress]
    template_total: int
    templates_completed: int
    current_worker: str | None
    figures: list[Figure]
    step: ProgressStep | None = None


class RunInfo(_Model):
    """Uruchomienie procesu; ``confirms_readiness`` i ``register_name`` deklaruje proces.

    ``confirms_readiness``: „Uruchom” potwierdza Gotowość. ``register_name``: nazwa Rejestru zleceń z Komunikatów
    procesu, pod którą karta proponuje otworzyć go przy Zatrzymaniu. ``pricing``: tryb Wyceny w efenix tego
    Uruchomienia (``None``: proces bez trybów).
    """

    id: str
    process: ProcessKey
    title: str
    period: str
    dry_run: bool
    pricing: Pricing | None
    confirms_readiness: bool
    register_name: str

    @property
    def mode(self) -> RunMode:
        """Tryb tego Uruchomienia w dzienniku Centrum i w Zgłoszeniu: podgląd bez zapisu albo zapis."""

        return "DRY-RUN" if self.dry_run else "RUN"


class Message(_Model):
    """Komunikat w trzech częściach (Co się stało, Gdzie, Co zrobić) bez kodu."""

    what: str
    where: str
    action: str

    @classmethod
    def of(cls, message: ProcessMessage) -> Message:
        return cls(what=message.what, where=message.where, action=message.action)


class RowToFill(_Model):
    """Wiersz Pliku zbiorczego z Ilościami do uzupełnienia: numer wiersza i jego stan (zrobiony, do uzupełnienia, bez ilości)."""

    row: int
    state: RowState


class KindToFill(_Model):
    """Rodzaj Ilości do uzupełnienia z listą wierszy; ``done``: każdy wiersz zrobiony, także gdy wierszy nie ma."""

    kind: FillKind
    rows: list[RowToFill]
    done: bool


class DescriptionColumn(_Model):
    """Kolumna z opisu technika i liczba wierszy, w których tata coś w niej wpisał."""

    column: str
    rows: int


class CollectiveFileRead(_Model):
    """Odczyt Pliku zbiorczego za widokiem: znacznik zapisu przed odczytem i godzina odczytu.

    ``retrying``: późniejsze odczyty się nie udały, więc to ostatni dobry stan, a strona ponawia odczyt.
    """

    version: str | None
    read_at: datetime
    retrying: bool


class QuantitiesToFillReady(_Model):
    """Ilości do uzupełnienia okresu przeliczone z zapisanego Pliku zbiorczego; ``kinds`` ma każdy rodzaj z listą.

    ``settled``: Przebieg rozliczeń okresu się odbył (Status okresu Rozliczenia pracowników gotowe), więc strona jest
    podglądem bez „Gotowe, rozlicz pracowników”, a wiersz bez wpisu taty jest „bez ilości”.
    """

    state: Literal["ready"]
    read: CollectiveFileRead
    settled: bool
    kinds: list[KindToFill]
    description_columns: list[DescriptionColumn]


class QuantitiesToFillProblem(_Model):
    """Pliku zbiorczego nie udało się odczytać; Komunikat go nazywa, a ``version`` to znacznik zapisu przed odczytem.

    ``collective_file_exists``: plik jest w Folderze okresu, więc „Otwórz Plik zbiorczy” ma co otworzyć.
    """

    state: Literal["problem"]
    message: Message
    version: str | None
    collective_file_exists: bool


class CollectiveFileVersion(_Model):
    """Znacznik zapisu Pliku zbiorczego (czas zmiany i rozmiar); ``None``, gdy pliku nie widać."""

    version: str | None


QuantitiesToFill = Annotated[QuantitiesToFillReady | QuantitiesToFillProblem, Field(discriminator="state")]


class WithoutQuantityRead(_Model):
    """Wiersze z listą (bez reguły, z opisu), w których tata nic jeszcze nie wpisał, rosnąco.

    ``sentence`` to zdanie okna „Uruchomić z zapisem?”, np. „3 wiersze bez ilości: 118, 203, 244”; ``None`` bez wierszy.
    """

    state: Literal["read"]
    sentence: str | None


class WithoutQuantityUnread(_Model):
    """Pliku zbiorczego nie udało się odczytać, więc nie wiadomo, które wiersze są bez ilości; start zostaje możliwy."""

    state: Literal["unread"]


WithoutQuantity = Annotated[WithoutQuantityRead | WithoutQuantityUnread, Field(discriminator="state")]


class KindTableCell(_Model):
    """Komórka N:AP wiersza na stronie rodzaju: wartość z pliku w kolumnie narzędzia, wpis taty, który robi wiersz, albo nic (0)."""

    source: CellSource
    value: int | Literal["nieliczbowa"]


class KindTableRow(_Model):
    """Wiersz strony rodzaju: numer wiersza Pliku zbiorczego, teksty, po których tata go rozpoznaje, i komórki N:AP.

    Nigdy adres, numer zlecenia ani ``UMOWA`` (ADR 0016).
    """

    row: int
    state: RowState
    worker: str
    devices: str
    activities: str
    completed: str
    cells: list[KindTableCell]


class PriceListItem(_Model):
    """Kolumna N:AP i nazwa pozycji cennika z wiersza 17 Pliku zbiorczego."""

    column: str
    name: str


class KindTableReady(_Model):
    """Wiersze jednego rodzaju Ilości do uzupełnienia rosnąco po numerze; ``columns`` to N:AP po kolei.

    ``settled`` jak w ``QuantitiesToFillReady``.
    """

    state: Literal["ready"]
    read: CollectiveFileRead
    settled: bool
    columns: list[PriceListItem]
    rows: list[KindTableRow]


KindTable = Annotated[KindTableReady | QuantitiesToFillProblem, Field(discriminator="state")]


class Count(_Model):
    label: str
    count: int


class CountGroup(_Model):
    """Liczby z etykietami pod tytułem; ``zero_warns``: zero to sygnał dla taty (dzień bez zleceń), a nie zwykła liczba
    (zlecenia pominięte przez Wycenę w efenix)."""

    title: str
    counts: list[Count]
    zero_warns: bool = True


class Decision(_Model):
    """Pytanie do taty z części decyzji procesu: komunikat w trzech częściach i liczby (np. Zlecenia na dzień)."""

    question: str
    message: Message
    counts: CountGroup


class PeriodFile(_Model):
    """Plik okresu z wyniku, sama nazwa: Rozliczenie wewnętrzne albo Plik zbiorczy."""

    name: str
    kind: Literal["internal_settlement", "collective_file"]


class WorkerSettlement(_Model):
    """Rozliczenie pracownika jednego Wykonawcy: nazwa pliku, liczba jego zleceń w okresie i czy szablon jest pusty."""

    worker: str
    file: str
    orders: int
    empty: bool


class RunSummary(_Model):
    """Podsumowanie albo plan (DRY-RUN) procesu tak, jak pokazuje je karta Uruchomienia, bez danych klientów.

    Liczby wyniku, potem szczegóły: kafelki liczb (np. Zlecenia na dzień), pliki okresu i Rozliczenia
    pracowników: plan po podglądzie, zapisane po uruchomieniu (``None``, gdy proces ich nie tworzy).
    """

    figures: list[Figure]
    counts: CountGroup | None
    files: list[PeriodFile]
    worker_settlements: list[WorkerSettlement] | None
    intermax_copy: str | None = None
    """Nazwa Kopii INTERMAX sprzed zapisu Uporządkowania INTERMAX; ``None`` w innych procesach i w Logach sprzed niej."""


class ReportDraft(_Model):
    """Dokładna treść Zgłoszenia, które „Wyślij do Maksa” wyśle do skrzynki Zgłoszeń: tytuł i treść Markdown."""

    title: str
    body: str


class ReportReady(_Model):
    """Zgłoszenia tego problemu jeszcze nie wysłano; „Wyślij do Maksa” wyśle podgląd z Diagnozy."""

    state: Literal["ready"]


class ReportSent(_Model):
    """Zgłoszenie tego problemu wysłano z tego uchwytu (albo kolejka dostarczyła je później); czeka na naprawę."""

    state: Literal["sent"]


class ReportWaiting(_Model):
    """Zgłoszenie tego problemu wysłano wcześniej i jest otwarte: czeka na naprawę, drugie nie powstaje."""

    state: Literal["waiting"]


# Na co czeka wysyłka taty w Kolejce wysyłki: ``internet`` albo ``key``, czyli Token do Zgłoszeń od Maksa (brak
# tokenu albo token, którego Skrzynka Zgłoszeń odmówiła).
WaitsFor = Literal["internet", "key"]


class ReportQueued(_Model):
    """Zgłoszenie czeka w Kolejce wysyłki na tym komputerze i wyjdzie samo, gdy będzie to, na co czeka."""

    state: Literal["queued"]
    waits_for: WaitsFor


class ReportRejected(_Model):
    """Skrzynka Zgłoszeń odrzuciła treść tego Zgłoszenia: ani internet, ani Token do Zgłoszeń tego nie naprawią.

    Plik zostaje w Kolejce wysyłki, która spróbuje go dopiero przy następnym starcie Centrum, więc Centrum niczego nie
    obiecuje, tylko każe skontaktować się z Maksem.
    """

    state: Literal["rejected"]


class ReportNotQueued(_Model):
    """Zgłoszenia nie udało się zapisać w kolejce, więc nic go nie wyśle; ``message`` mówi, co zrobić."""

    state: Literal["not_queued"]
    message: Message


ReportState = Annotated[
    ReportReady | ReportSent | ReportWaiting | ReportQueued | ReportRejected | ReportNotQueued,
    Field(discriminator="state"),
]


# Rodzaj Zatrzymania: ``for_tata`` usuwa tata sam według Komunikatu, ``for_maks`` każe przekazać Komunikat
# osobie utrzymującej narzędzie (także nieoczekiwany wyjątek), ``repeated`` to ten sam Komunikat „dla taty”
# drugi raz z rzędu w tym samym procesie. Przy ``for_maks`` i ``repeated`` Centrum proponuje Diagnozę.
# ``declined`` to Zatrzymanie po odmowie w Decyzji taty: w metrykach „dla taty”, nigdy Powtórka ani błąd.
StopKind = Literal[RecordedStopKind, "repeated", "declined"]
# Diagnoza przy Zatrzymaniu: ``on_request`` to przycisk „Diagnoza” zamiast następnej akcji, ``automatic`` to
# nieoczekiwany wyjątek, przy którym przeglądarka zaczyna Diagnozę od razu po pokazaniu wyniku.
DiagnosisOffer = Literal["on_request", "automatic"]
# Otwarcie tego, co proces zapisał: akcja po wyniku z zapisem, którą deklaruje proces (``run_view``).
ResultAction = Literal["open_collective_file", "open_worker_settlements_folder", "open_order_register"]
NextAction = Literal["run", "rerun", ResultAction]
Ending = Literal["finished", StopEnding]
"""Sposób zakończenia Uruchomienia: ``finished`` albo Zatrzymaniem (``process_run.StopEnding``, znaczenia przy ``Stop``)."""


class LoggedOutcome(_Model):
    """Wynik Uruchomienia procesu taki, jak niosą go Logi Uruchomienia: to, co karta pokazuje także po zamknięciu Centrum.

    Zatrzymania i ostrzeżenia w trzech częściach, uwagi techniczne i podsumowanie. ``ending`` mówi, jak się
    skończyło (``Ending``).
    ``next_action`` to akcja, którą Centrum proponuje po wyniku, a ``headline`` to tytuł banera wyniku; oba
    wylicza z wyniku jedna reguła (``runs.verdict``). ``stop_kind`` to Rodzaj Zatrzymania (``None`` bez
    Zatrzymania).
    """

    result: RunResult
    headline: str
    ending: Ending
    next_action: NextAction
    stop_kind: StopKind | None
    stops: list[Message]
    warnings: list[Message]
    technical_notes: list[str]
    summary: RunSummary | None


class OrderNote(_Model):
    """Zlecenie Wyceny w efenix na karcie bieżącego Uruchomienia: wiersz Pliku zbiorczego, numer zlecenia, Wykonawca i
    zdanie „Co się stało” Komunikatu zlecenia, które zostało tacie (``None`` przy każdym innym).

    Numer zlecenia (``None``: pusty ``NUMER ZL.``) i Wykonawcę widzi tylko tata na swoim komputerze: Logi Uruchomienia ich
    nie mają.
    """

    row: int
    order: str | None
    worker: str
    what: str | None


class OrderNotes(_Model):
    """Zlecenia Wyceny w efenix z jednym wynikiem na karcie bieżącego Uruchomienia: nazwa wyniku (``title``, ta sama co
    jego liczba), ``done``: tata nie ma przy nich nic do zrobienia (Zlecenia przekazane i rozliczone)."""

    title: str
    done: bool
    notes: list[OrderNote]


class RunOutcome(LoggedOutcome):
    """Wynik bieżącego Uruchomienia tej pracy Centrum: ``LoggedOutcome`` i to, czego Logi Uruchomienia nie niosą.

    ``diagnosis`` to Diagnoza, którą Centrum z niego proponuje (``None``: bez Zatrzymania i przy Zatrzymaniu „dla
    taty”), a ``report`` stan Zgłoszenia do Maksa tego problemu (``None``, gdy Centrum nie proponuje Diagnozy).
    ``files_unchanged``: Uruchomienie nie zmieniło plików taty (podgląd bez zapisu albo koniec przed
    Zapisywaniem), więc karta może to tacie powiedzieć. ``opens`` to plik taty, w którym jest poprawka
    Zatrzymania, a karta proponuje go otworzyć (``None``: żaden). ``order_notes``: zlecenia Wyceny w efenix, które
    zostały tacie, Zlecenia przekazane i Zlecenia rozliczone, po wyniku, z numerami zleceń i Wykonawcami, które karta pokazuje zamiast ostrzeżeń w
    trzech częściach (``None``: inny proces albo wynik bez podsumowania).
    """

    diagnosis: DiagnosisOffer | None
    report: ReportState | None
    files_unchanged: bool
    opens: DadFile | None
    order_notes: list[OrderNotes] | None = None


class RunRestored(_Model):
    """Karta zakończonego Uruchomienia z jego Logów Uruchomienia: nic, czego w nich nie ma.

    ``run`` ma tytuł procesu i ``confirms_readiness`` z deklaracji procesu, jak przy starcie, a ``started_at`` to
    start z Logów, ten sam co data wiersza Historii. Diagnozy i Zgłoszenia nie ma: żyją tylko przy Zatrzymaniu
    bieżącego Uruchomienia tej pracy Centrum.
    """

    state: Literal["restored"]
    run: RunInfo
    started_at: datetime
    phases: list[PhaseProgress]
    result: LoggedOutcome


class RunInterrupted(_Model):
    """Urwane Uruchomienie: Centrum zamknęło się w jego trakcie, więc nie ma jego wyniku.

    Nie ma wyniku ani rekordu metryk. ``advice`` mówi w trzech częściach, co się stało i co zrobić, osobno dla podglądu
    (nic nie zapisał) i zapisu. ``orders``: zlecenia Wyceny w efenix skończone przed zamknięciem Centrum, z każdym
    wynikiem, z Logów Urwanego Uruchomienia, które start Centrum zamknął z dziennika Wyceny w efenix (``None``: inny
    proces albo Logów nie ma).
    """

    state: Literal["interrupted"]
    run: RunInfo
    started_at: datetime
    advice: Message
    orders: CountGroup | None = None


class RunRecorded(_Model):
    """Uruchomienie z wynikiem w Historii, ale bez Logów Uruchomienia: Centrum zamknęło się po zapisie rekordu metryk,
    a przed zapisem Logów.

    Karta zna tylko to, co wiersz Historii: ``result`` i ``started_at`` są z niego, a ``headline`` i ``next_action``
    wylicza z nich ta sama reguła co na żywo (``runs.verdict``). Komunikatów, etapów ani podsumowania nie ma.
    """

    state: Literal["recorded"]
    run: RunInfo
    started_at: datetime
    result: RunResult
    headline: str
    next_action: NextAction


# Ostatnie Uruchomienie sprzed tego startu Centrum, z dysku.
PastRun = Annotated[RunRestored | RunRecorded | RunInterrupted, Field(discriminator="state")]


class RunIdle(_Model):
    """W tej pracy Centrum nie było jeszcze Uruchomienia procesu.

    ``previous`` to ostatnie Uruchomienie przed tym startem Centrum; ``None``: nie było żadnego albo jego plików nie
    da się odczytać.
    """

    state: Literal["idle"]
    previous: PastRun | None


class RunRunning(_Model):
    state: Literal["running"]
    run: RunInfo
    progress: Progress
    progress_stale: bool


class RunAwaitingDecision(_Model):
    """Uruchomienie czeka na decyzję taty; czas czekania nie wlicza się do czasu ani do metryk."""

    state: Literal["awaiting_decision"]
    run: RunInfo
    progress: Progress
    decision: Decision


class RunFinished(_Model):
    state: Literal["finished"]
    run: RunInfo
    progress: Progress
    progress_stale: bool
    result: RunOutcome


RunView = Annotated[RunIdle | RunRunning | RunAwaitingDecision | RunFinished, Field(discriminator="state")]


class RunCardMissing(_Model):
    """Karty tego Uruchomienia nie ma: nie wystartowało z Centrum, nie ma jego Logów albo nie da się ich odczytać."""

    state: Literal["missing"]


# Karta Uruchomienia z wiersza Historii.
RunCard = Annotated[RunRestored | RunCardMissing, Field(discriminator="state")]


class IntermaxSetup(_Model):
    """Karta „Uporządkuj INTERMAX” poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty.

    ``reminder`` to przypomnienie przed uruchomieniem, ``blocker`` mówi, czego brakuje w Ustawieniach taty,
    ``open_in_excel`` to zdanie o INTERMAX otwartym w Excelu, a ``last`` to karta ostatniego Uporządkowania
    INTERMAX z jego Logów Uruchomienia (``None``: żadnego albo jego Logów nie da się odczytać).
    """

    title: str
    reminder: str
    blocker: str | None
    open_in_excel: list[str]
    last: RunRestored | None


class IntermaxDay(_Model):
    """Dzień na karcie „Uporządkuj INTERMAX”: data, jej skrót z dniem tygodnia, czy to dziś i czy jest uporządkowany."""

    day: date
    label: str
    today: bool
    ordered: bool


class IntermaxDays(_Model):
    """Dziś i 6 dni wstecz oraz późniejsze Dni uporządkowane INTERMAX, po kolei.

    ``problem`` to Komunikat, gdy INTERMAX nie da się odczytać; ``days`` jest wtedy puste, tak jak bez wskazanego
    Rejestru zleceń.
    """

    days: list[IntermaxDay]
    problem: Message | None


# Przed czym powstała Kopia INTERMAX: przed Uporządkowaniem INTERMAX albo przed przywróceniem innej Kopii.
IntermaxCopyBefore = Literal["ordering", "restore"]


class IntermaxCopy(_Model):
    """Kopia INTERMAX w folderze Kopii: nazwa pliku, chwila z nazwy i to, przed czym powstała."""

    name: str
    taken_at: datetime
    before: IntermaxCopyBefore


class IntermaxCopies(_Model):
    """Kopie INTERMAX w Konfiguracji, od najnowszej.

    ``problem`` to Komunikat, gdy folderu Kopii nie da się odczytać; ``copies`` jest wtedy puste.
    """

    copies: list[IntermaxCopy]
    problem: Message | None


class IntermaxRestoreRequest(_Model):
    """Przywrócenie Kopii INTERMAX ``name``, którą wymieniła lista Kopii."""

    name: str


class IntermaxRestored(_Model):
    """INTERMAX ma bajty Kopii ``restored``, a jego stan sprzed przywrócenia leży jako nowa Kopia na liście Kopii.

    ``warnings``: Komunikaty o tym, czego przywrócenie nie dokończyło (starsze Kopie zostały).
    """

    state: Literal["restored"]
    restored: IntermaxCopy
    warnings: list[Message]


class IntermaxRestoreRefused(_Model):
    """Przywrócenie odmówiło z Komunikatem; INTERMAX i Kopie zostały takie, jak były."""

    state: Literal["refused"]
    message: Message


IntermaxRestore = Annotated[IntermaxRestored | IntermaxRestoreRefused, Field(discriminator="state")]


class RunEvent(_Model):
    """Jedno zdarzenie strumienia SSE: kolejny numer i pełny widok bieżącego Uruchomienia procesu."""

    sequence: int
    view: RunView


class DecisionAnswer(_Model):
    answer: Literal["continue", "abort"]


CheckState = Literal["passed", "failed", "not_checked"]
"""Wynik sprawdzenia Diagnozy; ten sam w Logach Uruchomienia (``run_logs.LoggedCheck``)."""


class DiagnosisCheck(_Model):
    """Jedno sprawdzenie Diagnozy: co sprawdzono, czy przeszło i krótko dlaczego, bez pełnych ścieżek."""

    label: str
    state: CheckState
    detail: str


DiagnosisNextAction = Literal["rerun", "update", "report"]


class Diagnosis(_Model):
    """Wynik Diagnozy Zatrzymania: wyjaśnienie w trzech częściach i każde sprawdzenie po kolei.

    ``explanation`` to Komunikat pierwszego sprawdzenia, które nie przeszło, albo „Nie znalazłem
    przyczyny na tym komputerze”. ``next_action`` ``rerun``: przyczynę tata usuwa sam i uruchamia
    ponownie; ``update``: przyczyną jest nowsza wersja narzędzia, więc tata klika „Zaktualizuj
    narzędzie”; ``report``: przyczynę usuwa Maks. ``report`` to podgląd: dokładnie to Zgłoszenie wyśle
    „Wyślij do Maksa” (przy ``rerun`` jako drugi przycisk). ``confirms_stop``: wyjaśnienie to ten sam
    Komunikat (kod i trzy części) co Zatrzymanie, więc przeglądarka go nie powtarza.
    ``update_proposal``: jest nowsza wersja narzędzia, ale wyjaśnieniem jest inna przyczyna, więc
    Diagnoza proponuje Aktualizację narzędzia tylko pod wyjaśnieniem.
    """

    explanation: Message
    confirms_stop: bool
    next_action: DiagnosisNextAction
    update_proposal: bool
    checks: list[DiagnosisCheck]
    report: ReportDraft


class TemplateReady(_Model):
    """Wzorzec jest na miejscu, nie jest otwarty i przechodzi Sprawdzanie."""

    state: Literal["ready"]
    label: str
    file_name: str


TemplateProblemKind = Literal["missing", "open_in_excel", "unreadable"]


class TemplateProblem(_Model):
    """Wzorca nie ma, jest otwarty w Excelu albo nie przechodzi Sprawdzania."""

    state: Literal["problem"]
    label: str
    file_name: str
    problem: TemplateProblemKind
    message: Message


TemplateStatus = Annotated[TemplateReady | TemplateProblem, Field(discriminator="state")]


class WorkersReady(_Model):
    """Nazwy Wykonawców w kolejności z konfiguracji wykonawców."""

    state: Literal["ready"]
    names: list[str]


class WorkersUnreadable(_Model):
    state: Literal["unreadable"]
    message: Message


Workers = Annotated[WorkersReady | WorkersUnreadable, Field(discriminator="state")]


# Token do Zgłoszeń na tym komputerze: ``ready`` („Zgłoszenia: gotowe”: jest, a Skrzynka go nie odrzuciła, także
# bez sieci), ``missing_key`` albo ``refused_key`` (Skrzynka Zgłoszeń odmówiła tego tokenu); nigdy jego wartość.
ReportKeyState = Literal["ready", "missing_key", "refused_key"]


# Aktualność narzędzia: ``current`` (commit narzędzia zawiera najnowsze Wydanie), ``newer`` (jest nowsze Wydanie),
# ``not_checked`` (brak sieci, brak Wydania albo narzędzie bez commitu Gita).
ToolFreshnessState = Literal["current", "newer", "not_checked"]


class ToolVersion(_Model):
    """Wersja narzędzia, z której działa Centrum: skrót commitu i dzień, od którego narzędzie jest na tym commicie."""

    commit: str
    since: date | None


class Configuration(_Model):
    """Konfiguracja tylko do odczytu, wyliczana z katalogu konfiguracji przy każdym odczycie.

    ``version`` jest ``None``, gdy narzędzie nie leży w klonie Gita; ``freshness`` to Aktualność tej wersji
    względem najnowszego Wydania na GitHubie (ADR 0014), sprawdzana jak w Diagnozie. ``update_offered`` mówi,
    czy Konfiguracja proponuje Aktualizację narzędzia: tylko przy nowszym Wydaniu (``tool_freshness.offers_update``).
    """

    version: ToolVersion | None
    freshness: ToolFreshnessState
    update_offered: bool
    templates: list[TemplateStatus]
    workers: Workers
    reports: ReportKeyState


# Krok Aktualizacji narzędzia: pobieranie nowej wersji, instalowanie bibliotek, ponowne uruchamianie Centrum.
ToolUpdateStep = Literal["fetching", "installing", "restarting"]


class ToolUpdateIdle(_Model):
    """Od startu Centrum tata nie zlecił Aktualizacji narzędzia."""

    state: Literal["idle"]


class ToolUpdateRunning(_Model):
    state: Literal["running"]
    step: ToolUpdateStep


class ToolUpdateUpToDate(_Model):
    """Narzędzie już było w najnowszej wersji; nic się nie zmieniło."""

    state: Literal["up_to_date"]


class ToolUpdateUpdated(_Model):
    """Narzędzie jest w nowej wersji; to Centrum wystartowało już w niej (jej commit jest w ``Health``)."""

    state: Literal["updated"]


class ToolUpdateFailed(_Model):
    """Aktualizacja narzędzia się nie udała; narzędzie zostało w wersji sprzed kliknięcia.

    ``next_action`` ``retry``: tata klika „Zaktualizuj narzędzie” jeszcze raz (np. gdy wróci internet);
    ``report``: sprawę przejmuje Maks. ``draft`` to Zgłoszenie z faktami dziennika tej aktualizacji, które
    wyśle „Wyślij do Maksa”, a ``report`` jego stan. ``after_restart``: porażkę zastało to Centrum przy starcie, od
    opiekuna ponownego startu (np. nowa wersja nie wystartowała), a nie z kliknięcia w tym Centrum.
    """

    state: Literal["failed"]
    message: Message
    next_action: Literal["retry", "report"]
    report: ReportState
    draft: ReportDraft
    after_restart: bool


ToolUpdate = Annotated[
    ToolUpdateIdle | ToolUpdateRunning | ToolUpdateUpToDate | ToolUpdateUpdated | ToolUpdateFailed,
    Field(discriminator="state"),
]


DAD_NOTE_TITLE_MAX_LENGTH = 120
DAD_NOTE_BODY_MAX_LENGTH = 10_000
# Tytuł Uwagi taty to jedna linia: issue w Skrzynce Zgłoszeń i Powiadomienie nazywają ją tym tytułem.
DadNoteTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=DAD_NOTE_TITLE_MAX_LENGTH, pattern=r"^[^\r\n]*$")
]
DadNoteBody = Annotated[str, StringConstraints(strip_whitespace=True, max_length=DAD_NOTE_BODY_MAX_LENGTH)]


class DadNoteText(_Model):
    """Tytuł i treść Uwagi taty w trakcie pisania, do podglądu „Maks dostanie”; tytuł może być jeszcze pusty.

    ``run_id`` to Uruchomienie z Centrum (``ProcessRun.run_id``), do którego tata przypina Uwagę; ``None``: ogólna.
    """

    title: DadNoteTitle
    body: DadNoteBody = ""
    run_id: str | None = None


class DadNoteRequest(_Model):
    """Uwaga taty do wysłania: tytuł wymagany, treść nie jest konieczna; białe znaki na brzegach znikają.

    ``run_id`` jak w ``DadNoteText``: Uruchomienie, do którego Uwaga jest przypięta; ``None``: ogólna.
    """

    title: Annotated[DadNoteTitle, StringConstraints(min_length=1)]
    body: DadNoteBody = ""
    run_id: str | None = None


class DadNoteDraft(_Model):
    """Dokładnie to, co dostanie Maks: tytuł i treść issue Uwagi taty w Skrzynce Zgłoszeń."""

    title: str
    body: str


class DadNoteSent(_Model):
    """Skrzynka Zgłoszeń przyjęła Uwagę taty."""

    state: Literal["sent"]


class DadNoteWaiting(_Model):
    """Uwaga taty czeka w Kolejce wysyłki i wyjdzie sama, także po następnym starcie, gdy będzie to, na co czeka."""

    state: Literal["waiting"]
    waits_for: WaitsFor


class DadNoteRejected(_Model):
    """Skrzynka Zgłoszeń odrzuciła treść Uwagi taty; jak ``ReportRejected``, Centrum niczego nie obiecuje."""

    state: Literal["rejected"]


DadNoteState = Annotated[DadNoteSent | DadNoteWaiting | DadNoteRejected, Field(discriminator="state")]


# Stan sprawy taty (Uwagi albo Zgłoszenia) w Powiadomieniu: wysłana, czeka w Kolejce wysyłki na internet albo na
# Token do Zgłoszeń, odrzucona (Skrzynka odrzuciła jej treść), rozwiązana (Maks zamknął issue jako ``completed``:
# będzie w następnej wersji) albo przeczytana (``not_planned``: bez zmian).
CaseState = Literal["wyslana", "czeka_na_internet", "czeka_na_token", "odrzucona", "rozwiazana", "przeczytana"]


class _Notification(_Model):
    """Wspólne pola Powiadomienia: ``id`` sprawy w jej stanie (nowy stan to nowe Powiadomienie) albo Wydania, ``at``
    czas tego stanu (zamknięcie przez Maksa, wysłanie przez tatę, publikacja Wydania) i ``unread``, czy tata go
    jeszcze nie widział."""

    id: str
    at: datetime
    unread: bool


class DadNoteNotification(_Notification):
    """Powiadomienie o Uwadze taty, nazwanej jej tytułem."""

    kind: Literal["uwaga"]
    title: str
    state: CaseState


class ReportNotification(_Notification):
    """Powiadomienie o Zgłoszeniu, nazwanym „Co się stało” jego Komunikatu, bez kodu."""

    kind: Literal["zgloszenie"]
    what: str
    state: CaseState


class SolvedCase(_Model):
    """Sprawa wysłana z tego komputera, którą Wydanie rozwiązuje: Uwaga taty nazwana tytułem, Zgłoszenie jego
    „Co się stało”."""

    kind: Literal["uwaga", "zgloszenie"]
    title: str


class ReleaseNotification(_Notification):
    """Powiadomienie o nowej wersji: numer Wydania (``0.2.0``), notka „Co nowego” jako zdanie wstępu i punkty
    (``release_notes.whats_new``; notka bez punktów to sam wstęp), sprawy taty, które rozwiązuje, i czy Centrum
    proponuje Aktualizację narzędzia (``tool_freshness.offers_update``, tylko przy najnowszym Wydaniu)."""

    kind: Literal["nowa_wersja"]
    version: str
    intro: str
    points: list[str]
    solved: list[SolvedCase]
    update_offered: bool


class PricingNotification(_Notification):
    """Powiadomienie o zakończonej Wycenie w efenix, także po Zatrzymaniu: tytuł wyniku jak na karcie Uruchomienia
    (``headline``), okres, tryb (jak ``RunInfo.pricing``), liczba zleceń z każdym wynikiem pod jego nazwą, jak na karcie (``None``: Zatrzymanie przed podsumowaniem), i „Co się stało”
    Komunikatu Zatrzymania (``None`` bez Zatrzymania). ``run_id`` otwiera kartę tego Uruchomienia z jego Logów."""

    kind: Literal["wycena_w_efenix"]
    run_id: str
    headline: str
    period: str
    pricing: Pricing | None
    orders: list[Count] | None
    stopped: str | None


Notification = Annotated[
    DadNoteNotification | ReportNotification | ReleaseNotification | PricingNotification, Field(discriminator="kind")
]


class Notifications(_Model):
    """Powiadomienia od najnowszego, liczba nieprzeczytanych (kropka na dzwonku) i Komunikat o pliku stanu, którego
    Centrum nie może zapisać (``None``: wszystko zapisane)."""

    unread: int
    items: list[Notification]
    message: Message | None


class NotificationsRead(_Model):
    """Powiadomienia, które tata zobaczył w widoku Powiadomienia (ich ``id``)."""

    ids: Annotated[list[str], Field(max_length=1_000)]


# Strony Centrum (`frontend/src/pages.tsx`): z bocznego menu i widok Powiadomienia; identyfikator to adres `#/<id>` strony.
PageId = Literal["okresy", "uruchomienia", "metryki", "konfiguracja", "powiadomienia", "uzupelnienie"]
# Zimny start strony (otwarcie albo odświeżenie karty) albo przejście w menu.
ViewKind = Literal["cold_start", "navigation"]
# Operacje API, które przeglądarka mierzy: nazwy (`operation_id`) zamiast adresu z tokenem okresu. Trasy spoza
# tej listy, każda z powodem, wymienia `OUTSIDE_TIMING` w tools/ci/export_openapi.py, który pilnuje obu stron.
ApiOperation = Literal[
    "getHealth",
    "getSettings",
    "chooseRegister",
    "openRegister",
    "choosePeriodsDirectory",
    "changeTheme",
    "getPeriodBoard",
    "openPeriodPath",
    "getQuantitiesToFill",
    "getCollectiveFileVersion",
    "getWithoutQuantity",
    "getKindTable",
    "openWorkerSettlement",
    "getRunSetup",
    "startRun",
    "getIntermaxSetup",
    "getIntermaxDays",
    "startIntermax",
    "getIntermaxCopies",
    "restoreIntermaxCopy",
    "decideRun",
    "diagnoseRun",
    "reportRun",
    "getRunCard",
    "getNotifications",
    "markNotificationsRead",
    "getMetrics",
    "getConfiguration",
    "startToolUpdate",
    "getToolUpdate",
    "reportToolUpdate",
    "getDadNoteRuns",
    "draftDadNote",
    "sendDadNote",
    "closeCentrum",
]
# Do 10 minut: dłuższy czas to uśpiona karta, nie pomiar.
Milliseconds = Annotated[int, Field(ge=0, le=600_000)]
MAX_TIMED_REQUESTS = 20


class ApiTiming(_Model):
    """Jedno zapytanie API widoku: czas w przeglądarce i czas serwera z ``Server-Timing`` (``None``: brak nagłówka)."""

    operation: ApiOperation
    browser_ms: Milliseconds
    server_ms: Milliseconds | None


class ViewTiming(_Model):
    """Pomiar gotowego widoku z przeglądarki: same liczby i nazwy z kontraktu, bez adresów i treści.

    ``ready_ms`` to czas do gotowej treści, ``fcp_ms`` pierwsze malowanie treści
    (tylko przy zimnym starcie), ``skeleton_ms`` czas widocznego szkieletu.
    """

    kind: ViewKind
    page: PageId
    ready_ms: Milliseconds
    fcp_ms: Milliseconds | None
    skeleton_ms: Milliseconds
    requests: Annotated[list[ApiTiming], Field(max_length=MAX_TIMED_REQUESTS)]
