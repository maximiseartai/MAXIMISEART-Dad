"""Widok Uruchomienia: to, co karta Uruchomienia pokazuje ze snapshotu postępu i z podsumowania procesu.

Jedyne miejsce prezentacji procesów w Centrum rozliczeń. Projekcja postępu pozostaje jedynym
interpretatorem Zdarzeń przebiegu (ADR 0002); widok tylko wybiera i nazywa jej fakty, a przeglądarka
renderuje go bez rozróżniania procesów (ADR 0004). Kontrakt niesie wyłącznie to, co karta pokazuje.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Generic, Protocol, TypeVar

from rozliczenia.centrum import contract
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.domain import SettlementSummary
from rozliczenia.efenix_pricing import PricingSummary
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.intermax_process import OrderingInputs
from rozliczenia.message import Message
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import ProcessInputs
from rozliczenia.quantity_rules import WEEKDAY_LABELS
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.settlement_process import SettlementInputs


class WarnedSummary(Protocol):
    """Podsumowanie procesu z ostrzeżeniami, które karta Uruchomienia pokazuje z kodami Komunikatów."""

    @property
    def warnings(self) -> Sequence[Message]: ...


InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=WarnedSummary)


@dataclass(frozen=True)
class Shown(Generic[SummaryT]):
    """Wynik zakończonego procesu: podsumowanie albo plan w kształcie kontraktu i ostrzeżenia z kodami Komunikatów.

    ``engine_summary`` to podsumowanie silnika, z którego powstał, dla działań po wyniku (Kontrola ilości).
    """

    summary: contract.RunSummary
    warnings: tuple[Message, ...]
    engine_summary: SummaryT


@dataclass(frozen=True)
class ResultView(Generic[InputsT, SummaryT]):
    """Liczby na żywo i wynik jednego procesu w kształcie kontraktu, te same w Skrypcie dla maszyn i na karcie."""

    _figures: Callable[[ProgressSnapshot, bool], list[contract.Figure]]
    _summary: Callable[[SummaryT, bool], contract.RunSummary]

    def progress(self, snapshot: ProgressSnapshot, *, dry_run: bool) -> contract.Progress:
        """Etapy, postęp Szablonów pracowników i liczby na żywo z jednego snapshotu projekcji."""

        return contract.Progress(
            phases=[
                contract.PhaseProgress(
                    phase=phase.value, state=state.value, duration_ms=snapshot.phase_durations_ms.get(phase, 0)
                )
                for phase, state in snapshot.phase_states.items()
            ],
            template_total=snapshot.template_total,
            templates_completed=snapshot.templates_completed,
            current_worker=snapshot.current_worker,
            figures=self._figures(snapshot, dry_run),
        )

    def shown(self, inputs: InputsT, summary: SummaryT) -> Shown[SummaryT]:
        """Wynik zakończonego procesu; rdzeń woła go w swojej osłonie (``run_process(view=...)``)."""

        return Shown(self._summary(summary, inputs.dry_run), tuple(summary.warnings), summary)


@dataclass(frozen=True, kw_only=True)
class ProcessView(ResultView[InputsT, SummaryT]):
    """Widok Uruchomienia procesu na karcie Centrum: deklaracja procesu obok liczb i wyniku.

    Deklaracja procesu: ``reminder`` to przypomnienie przed uruchomieniem, ``confirms_readiness``
    mówi, czy „Uruchom” potwierdza Gotowość Pliku zbiorczego, ``done`` to tytuł wyniku po zapisie,
    ``result_action`` otwiera to, co proces zapisał, jako akcja po wyniku, a ``register_name`` to nazwa
    Rejestru zleceń z Komunikatów procesu, pod którą karta proponuje go otworzyć.
    """

    reminder: str
    confirms_readiness: bool
    done: str
    result_action: contract.ResultAction
    register_name: str = "Rejestr zleceń"

    @property
    def modes(self) -> tuple[contract.RunMode, ...]:
        """Tryby Uruchomienia procesu: bez Podglądu bez zapisu tylko zapis."""

        return ("RUN",)

    def start_reminder(self, *, data_file_open: bool, template_open: bool) -> str | None:
        """Przypomnienie w stopce karty startu; znika, gdy „Uruchom” blokuje tylko Wzorzec otwarty w Excelu.

        Przypomnienie mówi o pliku danych procesu, a zdanie karty o Wzorcu mówi już, co zrobić.
        """

        return None if template_open and not data_file_open else self.reminder


@dataclass(frozen=True, kw_only=True)
class PeriodProcessView(ProcessView[InputsT, SummaryT]):
    """Widok procesu, który tata uruchamia z okresem: ``preview_hint`` to podpowiedź „Podgląd bez zapisu”."""

    preview_hint: str

    @property
    def modes(self) -> tuple[contract.RunMode, ...]:
        return ("RUN", "DRY-RUN")


def _count(label: str, value: int) -> contract.Figure:
    return contract.Figure(label=label, value=value, unit="count")


# Etykiety Przebiegu rozliczeń wspólne dla liczb na żywo i wyniku.
_ROWS: Final = "Wiersze danych"
_PLANNED: Final = "Planowane szablony"
_WRITTEN: Final = "Zapisane szablony"
_EMPTY: Final = "Puste szablony"


def _settlement_figures(snapshot: ProgressSnapshot, dry_run: bool) -> list[contract.Figure]:
    counters = snapshot.metric_counters()
    return [
        _count(_ROWS, snapshot.rows),
        _count(_PLANNED, counters["planned"]) if dry_run else _count(_WRITTEN, counters["written"]),
        _count(_EMPTY, counters["empty"]),
        _count("Problemy", snapshot.issue_count),
    ]


def _settlement_summary(summary: SettlementSummary, dry_run: bool) -> contract.RunSummary:
    figures = (
        [
            _count(_ROWS, summary.total_rows),
            _count(_PLANNED, summary.planned_count),
            _count(_EMPTY, summary.empty_count),
        ]
        if dry_run
        else [
            _count(_WRITTEN, summary.written_count),
            _count(_EMPTY, summary.empty_count),
        ]
    )
    return contract.RunSummary(
        figures=figures,
        counts=None,
        files=[],
        worker_settlements=[
            contract.WorkerSettlement(
                worker=result.worker_name,
                file=result.output_file.name,
                orders=result.rows,
                empty=result.status == "PUSTY_SZABLON",
            )
            for result in summary.results
        ],
    )


def _preparation_figures(snapshot: ProgressSnapshot, _dry_run: bool) -> list[contract.Figure]:
    return [
        _count("Ostrzeżenia", snapshot.issue_count),
        contract.Figure(label="Czas uruchomienia", value=snapshot.total_elapsed_ms, unit="ms"),
    ]


def _preparation_summary(summary: PreparationSummary, _dry_run: bool) -> contract.RunSummary:
    return contract.RunSummary(
        figures=[
            _count("Zlecenia okresu", summary.period_order_count),
            _count("Zlecenia skuteczne", summary.successful_order_count),
            _count("Pominięte puste wiersze", summary.skipped_empty_rows),
        ],
        counts=contract.CountGroup(
            title="Zlecenia na dzień",
            counts=[
                contract.Count(label=label, count=count) for label, count in summary.labeled_orders_per_day()
            ],
        ),
        files=[
            contract.PeriodFile(name=summary.internal_settlement_file.name, kind="internal_settlement"),
            contract.PeriodFile(name=summary.collective_file.name, kind="collective_file"),
        ],
        worker_settlements=None,
    )


SETTLEMENT: Final[PeriodProcessView[SettlementInputs, SettlementSummary]] = PeriodProcessView(
    reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
    confirms_readiness=True,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
    done="Rozliczenia pracowników gotowe",
    result_action="open_worker_settlements_folder",
    _figures=_settlement_figures,
    _summary=_settlement_summary,
)
PREPARATION: Final[PeriodProcessView[PreparationInputs, PreparationSummary]] = PeriodProcessView(
    reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
    confirms_readiness=False,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
    done="Plik zbiorczy przygotowany",
    result_action="open_collective_file",
    _figures=_preparation_figures,
    _summary=_preparation_summary,
)


def _ordering_figures(snapshot: ProgressSnapshot, _dry_run: bool) -> list[contract.Figure]:
    return [contract.Figure(label="Czas uruchomienia", value=snapshot.total_elapsed_ms, unit="ms")]


def _ordering_summary(summary: OrderingSummary, _dry_run: bool) -> contract.RunSummary:
    day = f"{WEEKDAY_LABELS[summary.day.weekday()]} {summary.day:%d.%m.%Y}"
    return contract.RunSummary(
        figures=[_count("Zlecenia", summary.order_count), _count("Wykonawcy", summary.worker_count)],
        counts=contract.CountGroup(title="Uporządkowany dzień", counts=[contract.Count(label=day, count=summary.order_count)]),
        files=[],
        worker_settlements=None,
        intermax_copy=summary.copy_name,
    )


INTERMAX: Final[ProcessView[OrderingInputs, OrderingSummary]] = ProcessView(
    reminder="Zapisz i zamknij INTERMAX w Excelu",
    confirms_readiness=False,
    done="INTERMAX uporządkowany",
    result_action="open_order_register",
    register_name="INTERMAX",
    _figures=_ordering_figures,
    _summary=_ordering_summary,
)


def _pricing_figures(snapshot: ProgressSnapshot, _dry_run: bool) -> list[contract.Figure]:
    return [contract.Figure(label="Czas uruchomienia", value=snapshot.total_elapsed_ms, unit="ms")]


def _pricing_summary(summary: PricingSummary, _dry_run: bool) -> contract.RunSummary:
    return contract.RunSummary(
        figures=[
            _count("Zlecenia w zakresie", len(summary.results)),
            _count("Znalezione w efenix", summary.found_count),
            _count("Błędy zleceń", summary.error_count),
            _count("Pominięte ze zdjęciami", summary.with_photos),
            _count("Pominięte usterki", summary.defects),
        ],
        counts=None,
        files=[],
        worker_settlements=None,
    )


# Wycena w efenix nie ma jeszcze karty w Centrum rozliczeń (#750): tylko liczby na żywo i wynik Skryptu dla maszyn.
EFENIX: Final[ResultView[EfenixInputs, PricingSummary]] = ResultView(
    _figures=_pricing_figures,
    _summary=_pricing_summary,
)
