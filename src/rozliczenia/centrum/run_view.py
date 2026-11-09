"""Widok Uruchomienia: to, co karta Uruchomienia pokazuje ze snapshotu postępu i z podsumowania procesu.

Tu są typy widoku i liczby wspólne dla procesów; widok każdego procesu leży przy jego wpisie w katalogu procesów
(``centrum/processes/<proces>.py``). Projekcja postępu pozostaje jedynym interpretatorem Zdarzeń przebiegu
(ADR 0002); widok tylko wybiera i nazywa jej fakty, a przeglądarka renderuje go bez rozróżniania procesów (ADR 0004).
Kontrakt niesie wyłącznie to, co karta pokazuje.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.domain import RunMode
from rozliczenia.efenix_pricing import OrderKind
from rozliczenia.message import Message
from rozliczenia.process_run import ProcessSummary
from rozliczenia.progress import ProgressSnapshot


class WarnedSummary(ProcessSummary, Protocol):
    """Podsumowanie procesu z ostrzeżeniami, które karta Uruchomienia pokazuje z kodami Komunikatów."""

    @property
    def warnings(self) -> Sequence[Message]: ...


SummaryT = TypeVar("SummaryT", bound=WarnedSummary)


@dataclass(frozen=True)
class Shown(Generic[SummaryT]):
    """Wynik zakończonego procesu: podsumowanie albo plan w kształcie kontraktu i ostrzeżenia z kodami Komunikatów.

    ``engine_summary`` to podsumowanie silnika, z którego powstał, dla działań po wyniku (Kontrola ilości). ``notes``:
    zlecenia, które zostały tacie, Zlecenia przekazane i rozliczone, z numerami zleceń i Wykonawcami, tylko na kartę bieżącego
    Uruchomienia.
    """

    summary: runs_contract.RunSummary
    warnings: tuple[Message, ...]
    engine_summary: SummaryT
    notes: list[runs_contract.OrderNotes] | None = None


@dataclass(frozen=True)
class ResultView(Generic[SummaryT]):
    """Liczby na żywo i wynik jednego procesu w kształcie kontraktu, te same w Skrypcie dla maszyn i na karcie.

    ``_notes``: zlecenia z podsumowania, które zostały tacie, Zlecenia przekazane i rozliczone (Wycena w efenix); inne procesy ich
    nie mają.
    """

    _figures: Callable[[ProgressSnapshot, bool], list[runs_contract.Figure]]
    _summary: Callable[[SummaryT, bool], runs_contract.RunSummary]
    _notes: Callable[[SummaryT], list[runs_contract.OrderNotes] | None] = lambda _summary: None

    def progress(self, snapshot: ProgressSnapshot, *, dry_run: bool) -> runs_contract.Progress:
        """Etapy, postęp Szablonów pracowników, krok Zapisywania i liczby na żywo z jednego snapshotu projekcji."""

        step = snapshot.step

        return runs_contract.Progress(
            phases=[
                runs_contract.PhaseProgress(
                    phase=phase, state=state.value, duration_ms=snapshot.phase_durations_ms.get(phase, 0)
                )
                for phase, state in snapshot.phase_states.items()
            ],
            template_total=snapshot.template_total,
            templates_completed=snapshot.templates_completed,
            current_worker=snapshot.current_worker,
            figures=self._figures(snapshot, dry_run),
            step=None
            if step is None
            else runs_contract.ProgressStep(label=step.label, worker=step.worker, done=step.done, total=step.total),
        )

    def shown(self, summary: SummaryT, *, dry_run: bool) -> Shown[SummaryT]:
        """Wynik zakończonego procesu; rdzeń woła go w swojej osłonie (``run_process(view=...)``)."""

        return Shown(self._summary(summary, dry_run), tuple(summary.warnings), summary, self._notes(summary))


@dataclass(frozen=True, kw_only=True)
class ProcessView(ResultView[SummaryT]):
    """Widok Uruchomienia procesu na karcie Centrum: deklaracja procesu obok liczb i wyniku.

    Deklaracja procesu: ``reminder`` to przypomnienie przed uruchomieniem, ``confirms_readiness``
    mówi, czy „Uruchom” potwierdza Gotowość Pliku zbiorczego, ``done`` to tytuł wyniku po zapisie,
    ``result_action`` otwiera to, co proces zapisał, jako akcja po wyniku, a ``register_name`` to nazwa
    Rejestru zleceń z Komunikatów procesu, pod którą karta proponuje go otworzyć. ``pricing_modes`` to tryby Wyceny w
    efenix, które tata wybiera przyciskiem przy każdym starcie, pierwszy domyślny (pusta krotka: proces bez trybów).
    ``prepares_collective_file``: wynik procesu z zapisem przygotowuje Plik zbiorczy okresu (Przygotowanie; Wycena w
    efenix też proponuje go otworzyć, ale go nie tworzy).
    """

    reminder: str
    confirms_readiness: bool
    done: str
    result_action: runs_contract.ResultAction
    register_name: str = "Rejestr zleceń"
    pricing_modes: tuple[runs_contract.Pricing, ...] = ()
    prepares_collective_file: bool = False

    @property
    def modes(self) -> tuple[RunMode, ...]:
        """Tryby Uruchomienia procesu: bez Podglądu bez zapisu tylko zapis."""

        return (RunMode.RUN,)

    def collective_file_prepared(self, *, ending: runs_contract.Ending, dry_run: bool) -> bool:
        """Wynik przygotował Plik zbiorczy okresu: proces go przygotowuje i skończył się z zapisem bez Zatrzymania; jedna
        reguła dla karty na żywo i karty z Logów (``runs_contract.LoggedOutcome.collective_file_prepared``)."""

        return self.prepares_collective_file and ending == "finished" and not dry_run

    def start_reminder(self, *, data_file_open: bool, template_open: bool) -> str | None:
        """Przypomnienie w stopce karty startu; znika, gdy „Uruchom” blokuje tylko Wzorzec otwarty w Excelu.

        Przypomnienie mówi o pliku danych procesu, a zdanie karty o Wzorcu mówi już, co zrobić.
        """

        return None if template_open and not data_file_open else self.reminder


@dataclass(frozen=True, kw_only=True)
class PeriodProcessView(ProcessView[SummaryT]):
    """Widok procesu, który tata uruchamia z okresem: ``preview_hint`` to podpowiedź „Podgląd bez zapisu”."""

    preview_hint: str

    @property
    def modes(self) -> tuple[RunMode, ...]:
        return (RunMode.RUN, RunMode.DRY_RUN)


def count_figure(label: str, value: int) -> runs_contract.Figure:
    """Liczba na karcie Uruchomienia pod nazwą ``label``."""

    return runs_contract.Figure(label=label, value=value, unit="count")


def elapsed_figure(snapshot: ProgressSnapshot) -> runs_contract.Figure:
    return runs_contract.Figure(label="Czas uruchomienia", value=snapshot.total_elapsed_ms, unit="ms")


def elapsed_only(snapshot: ProgressSnapshot, _dry_run: bool) -> list[runs_contract.Figure]:
    """Liczby na żywo procesu, który pokazuje w trakcie tylko czas uruchomienia."""

    return [elapsed_figure(snapshot)]


def order_label(kind: OrderKind) -> str:
    """Nazwa wyniku zlecenia Wyceny w efenix dla taty: liczba na karcie Uruchomienia, z Logów i w Powiadomieniu oraz
    lista zleceń na karcie."""

    match kind:
        case OrderKind.READY:
            return "Gotowe do przekazania"
        case OrderKind.FORWARDED:
            return "Przekazane do akceptacji"
        case OrderKind.SETTLED:
            return "Rozliczone"
        case OrderKind.ERROR:
            return "Błędy zleceń"
        case OrderKind.WARNING:
            return "Ostrzeżenia Emmetta"


def order_counts(counted: Counter[OrderKind]) -> list[runs_contract.Count]:
    """Liczba zleceń z każdym wynikiem pod jego nazwą, w kolejności ``OrderKind``."""

    return [runs_contract.Count(label=order_label(kind), count=counted[kind]) for kind in OrderKind]
