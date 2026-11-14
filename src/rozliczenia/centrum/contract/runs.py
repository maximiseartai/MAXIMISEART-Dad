"""Kontrakt Uruchomień procesu: start, postęp, Decyzja taty, wynik, karta i strumień zdarzeń."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Final, Literal, assert_never

from pydantic import Field, computed_field

from rozliczenia import domain
from rozliczenia.centrum.contract.common import Message, Model, PeriodProcessKey, ProcessKey
from rozliczenia.centrum.contract.diagnosis import ReportState
from rozliczenia.domain import ProgressPhase, RunMode
from rozliczenia.message import DadFile
from rozliczenia.process_run import RunResult, StopEnding


Pricing = Literal["bez Przekazania", "z Przekazaniem"]
"""Tryb Wyceny w efenix (wartości ``efenix_pricing.PricingMode``, ADR 0027): bez Przekazania do akceptacji gotowych
zleceń albo z nim."""


DEFAULT_PRICING: Final[Pricing] = "bez Przekazania"
"""Tryb startu, w którym nikt trybu nie wybrał: proces bez trybów i żądanie bez pola (ADR 0027)."""


PhaseName = Literal[ProgressPhase.CHECKING, ProgressPhase.READING, ProgressPhase.PLANNING, ProgressPhase.SAVING]


class PeriodChoice(Model):
    """Okres do wyboru przy starcie, ze Statusem okresu wyliczonym z plików."""

    token: str
    tuesday: date
    monday: date
    status_label: str
    last_complete: bool
    previewed: bool
    """W historii metryk jest udany podgląd bez zapisu tego procesu i okresu."""
    collective_file: str | None
    """Nazwa Pliku zbiorczego okresu, gdy proces go czyta (Przebieg rozliczeń); tata go nie wskazuje."""
    open_in_excel: list[str]
    """Zdania o skoroszytach wejściowych procesu otwartych w Excelu: najpierw plik danych, potem Wzorce."""
    reminder: str | None
    """Przypomnienie w stopce karty startu przy tym okresie; brak, gdy „Uruchom” blokuje tylko otwarty Wzorzec."""


class ProcessSetup(Model):
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


class RunSetup(Model):
    processes: list[ProcessSetup]


class RunRequest(Model):
    """Start Uruchomienia procesu; pliki wejściowe wylicza serwer z ustawień i okresu.

    ``pricing``: tryb Wyceny w efenix, który tata wybrał przyciskiem; proces bez trybów przyjmuje tylko domyślny.
    """

    process: PeriodProcessKey
    period: str
    mode: RunMode
    pricing: Pricing = DEFAULT_PRICING


class PhaseProgress(Model):
    phase: PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int


class Figure(Model):
    """Liczba karty Uruchomienia z etykietą; ``unit`` ``ms`` to czas, który przeglądarka pokazuje w sekundach."""

    label: str
    value: int
    unit: Literal["count", "ms"]


class ProgressStep(Model):
    """Krok Zapisywania procesu bez Szablonów pracowników (Wycena w efenix): co trwa, u którego Wykonawcy i ile z ilu.

    ``total`` 0: krok bez liczenia (logowanie, Znaczniki efenix), który karta pokazuje jako trwający.
    """

    label: str
    worker: str | None
    done: int
    total: int


class Progress(Model):
    """Wyświetlany podzbiór snapshotu jedynej projekcji postępu (ADR 0002): etapy, Szablony pracowników i liczby.

    ``step``: ostatni krok Zapisywania procesu bez Szablonów pracowników; ``None`` w innych procesach i przed nim.
    """

    phases: list[PhaseProgress]
    template_total: int
    templates_completed: int
    current_worker: str | None
    figures: list[Figure]
    step: ProgressStep | None = None


class RunInfo(Model):
    """Uruchomienie procesu; ``confirms_readiness`` i ``register_name`` deklaruje proces.

    ``confirms_readiness``: „Uruchom” potwierdza Gotowość. ``register_name``: nazwa Rejestru zleceń z Komunikatów
    procesu, pod którą karta proponuje otworzyć go przy Zatrzymaniu. ``pricing``: tryb Wyceny w efenix tego
    Uruchomienia (``None``: proces bez trybów).
    """

    id: str
    process: ProcessKey
    title: str
    period: str
    mode: RunMode
    pricing: Pricing | None
    confirms_readiness: bool
    register_name: str


class Count(Model):
    label: str
    count: int


class CountGroup(Model):
    """Liczby z etykietami pod tytułem; ``zero_warns``: zero to sygnał dla taty (dzień bez zleceń), a nie zwykła liczba
    (zlecenia pominięte przez Wycenę w efenix)."""

    title: str
    counts: list[Count]
    zero_warns: bool = True


class Decision(Model):
    """Pytanie do taty z części decyzji procesu: komunikat w trzech częściach i liczby (np. Zlecenia na dzień)."""

    question: str
    message: Message
    counts: CountGroup


CONTINUE_HINT: Final = "przy decyzji wybierz „Kontynuuj”"
"""Jak w Centrum wyraża się zgodę w Decyzji taty (``Conversation.continue_hint``); ten sam tekst ma Komunikat po
odmowie w Uruchomieniu odtworzonym z Logów (``tools/odtworz_uruchomienie.py``)."""


class PeriodFile(Model):
    """Plik okresu z wyniku, sama nazwa: Rozliczenie wewnętrzne albo Plik zbiorczy."""

    name: str
    kind: Literal["internal_settlement", "collective_file"]


class WorkerSettlement(Model):
    """Rozliczenie pracownika jednego Wykonawcy: nazwa pliku, liczba jego zleceń w okresie i czy szablon jest pusty."""

    worker: str
    file: str
    orders: int
    empty: bool


class RunSummary(Model):
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


StopKind = Literal[domain.StopKind, "repeated", "declined"]
"""Rodzaj Zatrzymania: ``for_tata`` usuwa tata sam według Komunikatu, ``for_maks`` każe przekazać Komunikat Maksowi
(także nieoczekiwany wyjątek), ``repeated`` to ten sam Komunikat „dla taty” drugi raz z rzędu w tym samym procesie.
Przy ``for_maks`` i ``repeated`` Centrum proponuje Diagnozę. ``declined`` to Zatrzymanie po odmowie w Decyzji taty:
w metrykach „dla taty”, nigdy Powtórka ani błąd."""


ResultTone = Literal["ok", "needs_review", "stopped", "failed"]
"""Ton wyniku Uruchomienia procesu, w którym Centrum go pokazuje: plakietka, baner Zatrzymania, Metryki i stopka Uwagi."""


def result_tone(result: RunResult, stop_kind: StopKind | None) -> ResultTone:
    """Błąd (``failed``) to tylko Zatrzymanie „do Maksa”, także nieoczekiwany wyjątek; każde inne przerwane, także bez
    rodzaju ze starego rekordu metryk, jest zatrzymane (``stopped``)."""

    match result:
        case "OK":
            return "ok"
        case "WYMAGA_SPRAWDZENIA":
            return "needs_review"
        case "BLAD_KRYTYCZNY":
            return "failed" if stop_kind == "for_maks" else "stopped"
        case _:
            assert_never(result)


_RESULT_WORDS: Final[dict[ResultTone, str]] = {
    "ok": "OK",
    "needs_review": "do sprawdzenia",
    "stopped": "zatrzymano",
    "failed": "błąd",
}


def result_word(tone: ResultTone) -> str:
    """Wynik słowem małą literą, jak w stopce Uwagi taty i w Metrykach: „OK”, „do sprawdzenia”, „zatrzymano”, „błąd”."""

    return _RESULT_WORDS[tone]


DiagnosisOffer = Literal["on_request", "automatic"]
"""Diagnoza przy Zatrzymaniu: ``on_request`` to przycisk „Diagnoza” zamiast następnej akcji, ``automatic`` to
nieoczekiwany wyjątek, przy którym przeglądarka zaczyna Diagnozę od razu po pokazaniu wyniku."""


ResultAction = Literal[
    "open_collective_file", "open_worker_settlements_folder", "open_order_register", "open_reports_view"
]
"""Otwarcie tego, co proces zapisał: akcja po wyniku z zapisem, którą deklaruje proces (``run_view``)."""


NextAction = Literal["run", "rerun", ResultAction]


Ending = Literal["finished", StopEnding]
"""Sposób zakończenia Uruchomienia: ``finished`` albo Zatrzymaniem (``process_run.StopEnding``, znaczenia przy ``Stop``)."""


class LoggedOutcome(Model):
    """Wynik Uruchomienia procesu taki, jak niosą go Logi Uruchomienia: to, co karta pokazuje także po zamknięciu Centrum.

    Zatrzymania i ostrzeżenia w trzech częściach, uwagi techniczne i podsumowanie. ``ending`` mówi, jak się
    skończyło (``Ending``).
    ``next_action`` to akcja, którą Centrum proponuje po wyniku, a ``headline`` to tytuł banera wyniku; oba
    wylicza z wyniku jedna reguła (``runs.verdict``). ``stop_kind`` to Rodzaj Zatrzymania (``None`` bez
    Zatrzymania), a ``stop_note`` zdanie pod tytułem Zatrzymania (``runs.stop_note``; ``None``: bez niego).
    ``collective_file_prepared``: wynik przygotował Plik zbiorczy okresu, więc karta pokazuje pod nim
    Uzupełnienie pliku zbiorczego (``run_view.ProcessView.collective_file_prepared``).
    """

    result: RunResult
    headline: str
    ending: Ending
    next_action: NextAction
    stop_kind: StopKind | None
    stop_note: str | None
    stops: list[Message]
    warnings: list[Message]
    technical_notes: list[str]
    summary: RunSummary | None
    collective_file_prepared: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tone(self) -> ResultTone:
        """Ton wyniku (``result_tone``): czerwony baner Zatrzymania tylko przy ``failed``."""

        return result_tone(self.result, self.stop_kind)


class OrderNote(Model):
    """Zlecenie Wyceny w efenix na karcie bieżącego Uruchomienia: wiersz Pliku zbiorczego, numer zlecenia, Wykonawca i
    zdanie „Co się stało” Komunikatu zlecenia, które zostało tacie (``None`` przy każdym innym).

    Numer zlecenia (``None``: pusty ``NUMER ZL.``) i Wykonawcę widzi tylko tata na swoim komputerze: Logi Uruchomienia ich
    nie mają.
    """

    row: int
    order: str | None
    worker: str
    what: str | None


class OrderNotes(Model):
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


class RunRestored(Model):
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


class RunInterrupted(Model):
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


class RunRecorded(Model):
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


PastRun = Annotated[RunRestored | RunRecorded | RunInterrupted, Field(discriminator="state")]
"""Ostatnie Uruchomienie sprzed tego startu Centrum, z dysku."""


class RunIdle(Model):
    """W tej pracy Centrum nie było jeszcze Uruchomienia procesu.

    ``previous`` to ostatnie Uruchomienie przed tym startem Centrum; ``None``: nie było żadnego albo jego plików nie
    da się odczytać.
    """

    state: Literal["idle"]
    previous: PastRun | None


class RunRunning(Model):
    state: Literal["running"]
    run: RunInfo
    progress: Progress
    progress_stale: bool


class RunAwaitingDecision(Model):
    """Uruchomienie czeka na decyzję taty; czas czekania nie wlicza się do czasu ani do metryk."""

    state: Literal["awaiting_decision"]
    run: RunInfo
    progress: Progress
    decision: Decision


class RunFinished(Model):
    state: Literal["finished"]
    run: RunInfo
    progress: Progress
    progress_stale: bool
    result: RunOutcome


RunView = Annotated[RunIdle | RunRunning | RunAwaitingDecision | RunFinished, Field(discriminator="state")]


class RunCardMissing(Model):
    """Karty tego Uruchomienia nie ma: nie wystartowało z Centrum, nie ma jego Logów albo nie da się ich odczytać."""

    state: Literal["missing"]


RunCard = Annotated[RunRestored | RunCardMissing, Field(discriminator="state")]
"""Karta Uruchomienia z wiersza Historii."""


class RunEvent(Model):
    """Jedno zdarzenie strumienia SSE: kolejny numer i pełny widok bieżącego Uruchomienia procesu."""

    sequence: int
    view: RunView


class DecisionAnswer(Model):
    answer: Literal["continue", "abort"]
