"""Wycena w efenix w katalogu procesów: wpis i widok Uruchomienia.

Wycena wycenia zlecenia Pliku zbiorczego okresu w efenix w oknie efenix gospodarza, a Status okresu się nie zmienia.
Tryb Wyceny (ADR 0027) tata wybiera przy każdym starcie jednym z dwóch przycisków i Centrum go nie pamięta. Wejście ma
dziennik Wyceny w efenix gospodarza (w Centrum ``logs_disk.Journal``), który przeżywa nagłe zgaśnięcie Centrum.
"""

from __future__ import annotations

from typing import Final

from rozliczenia import efenix_messages, efenix_process
from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import (
    PERIODS_DIRECTORY,
    TAIL,
    ByStatus,
    HostParts,
    PeriodFolderCheck,
    PeriodProcessKind,
    PeriodStart,
    Start,
)
from rozliczenia.centrum.run_logs import LoggedOrder, LoggedWindowStop, ProcessLogs
from rozliczenia.centrum.run_view import ProcessView, count_figure, elapsed_only, order_label
from rozliczenia.efenix_pricing import EfenixInputs, OrderKind, PricingMode, PricingStopped, PricingSummary
from rozliczenia.tool_files import EFENIX_METRICS

_NOTED: Final = (OrderKind.ERROR, OrderKind.WARNING, OrderKind.FORWARDED, OrderKind.SETTLED)
"""Listy zleceń na karcie bieżącego Uruchomienia: najpierw te, które zostały tacie."""


def _summary(summary: PricingSummary, _dry_run: bool) -> runs_contract.RunSummary:
    return runs_contract.RunSummary(
        figures=[
            count_figure("Zlecenia w zakresie", len(summary.results)),
            *(count_figure(order_label(kind), summary.count(kind)) for kind in OrderKind),
        ],
        counts=runs_contract.CountGroup(
            title="Pominięte",
            counts=[
                runs_contract.Count(label="Ze zdjęciami", count=summary.with_photos),
                runs_contract.Count(label="Usterki", count=summary.defects),
                runs_contract.Count(label="Nieznalezione w efenix", count=summary.not_found),
            ],
            zero_warns=False,
        ),
        files=[],
        worker_settlements=None,
    )


def _notes(summary: PricingSummary) -> list[runs_contract.OrderNotes]:
    return [
        runs_contract.OrderNotes(
            title=order_label(kind),
            done=not kind.left_for_tata,
            notes=[
                runs_contract.OrderNote(
                    row=result.order.row,
                    order=result.order.number,
                    worker=result.order.worker,
                    what=None if result.message is None else result.message.what,
                )
                for result in summary.results
                if result.kind is kind
            ],
        )
        for kind in _NOTED
    ]


def _logs(summary: PricingSummary | None, facts: object) -> ProcessLogs:
    """Ślad zleceń z podsumowania, a po Zatrzymaniu okna efenix (``PricingStopped``) ślad zleceń sprzed niego i samo
    Zatrzymanie."""

    stopped = facts if isinstance(facts, PricingStopped) else None
    priced = summary if stopped is None else stopped.summary
    return ProcessLogs(
        efenix_orders=None if priced is None else LoggedOrder.all_of(priced),
        efenix_stop=None if stopped is None else LoggedWindowStop.of(stopped),
    )


def _inputs(start: Start, parts: HostParts) -> EfenixInputs:
    window = parts.window()
    return EfenixInputs(
        start.path("collective_file"), window.open, window.pace, journal=parts.journal, mode=PricingMode(start.pricing)
    )


KIND: Final[PeriodProcessKind[EfenixInputs, PricingSummary]] = PeriodProcessKind(
    key="efenix",
    short_title="efenix",
    view=ProcessView(
        reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
        confirms_readiness=False,
        done="Wycena w efenix gotowa",
        result_action="open_collective_file",
        pricing_modes=("bez Przekazania", "z Przekazaniem"),
        _figures=elapsed_only,
        _summary=_summary,
        _notes=_notes,
    ),
    core=efenix_process.PROCESS,
    default_metrics=EFENIX_METRICS,
    needs=("collective_file", "efenix_window"),
    inputs=_inputs,
    start=PeriodStart(
        creates="Wyceny zleceń i Znaczniki efenix",
        chooser=ByStatus(
            frozenset({"collective_file_prepared", "worker_settlements_ready"}),
            "Żaden okres nie ma Pliku zbiorczego. Najpierw przygotuj plik zbiorczy.",
        ),
        no_preview=refusal.pricing_without_preview(),
    ),
    settings=(PERIODS_DIRECTORY,),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        PeriodFolderCheck(collective_file_missing=efenix_messages.collective_file_missing),
        "period_files_in_excel",
        *TAIL,
    ),
    journaled=True,
    logs=_logs,
)
