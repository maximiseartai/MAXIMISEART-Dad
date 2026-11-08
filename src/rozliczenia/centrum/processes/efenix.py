"""Wycena w efenix w katalogu procesów: wpis i widok Uruchomienia.

Wycena czyta Plik zbiorczy okresu i wycenia jego zlecenia w efenix; nie ma Podglądu bez zapisu ani Wzorców.
"""

from __future__ import annotations

from typing import Final

from rozliczenia import efenix_messages, efenix_process
from rozliczenia.centrum import contract
from rozliczenia.centrum.process_kind import PERIODS_DIRECTORY, TAIL, PeriodFolderCheck, PeriodProcessKind
from rozliczenia.centrum.run_view import ProcessView, count_figure, elapsed_only, order_label
from rozliczenia.efenix_pricing import EfenixInputs, OrderKind, PricingSummary
from rozliczenia.tool_files import EFENIX_METRICS

# Listy zleceń na karcie bieżącego Uruchomienia: najpierw te, które zostały tacie.
_NOTED: Final = (OrderKind.ERROR, OrderKind.WARNING, OrderKind.FORWARDED, OrderKind.SETTLED)


def _summary(summary: PricingSummary, _dry_run: bool) -> contract.RunSummary:
    return contract.RunSummary(
        figures=[
            count_figure("Zlecenia w zakresie", len(summary.results)),
            *(count_figure(order_label(kind), summary.count(kind)) for kind in OrderKind),
        ],
        counts=contract.CountGroup(
            title="Pominięte",
            counts=[
                contract.Count(label="Ze zdjęciami", count=summary.with_photos),
                contract.Count(label="Usterki", count=summary.defects),
                contract.Count(label="Nieznalezione w efenix", count=summary.not_found),
            ],
            zero_warns=False,
        ),
        files=[],
        worker_settlements=None,
    )


def _notes(summary: PricingSummary) -> list[contract.OrderNotes]:
    return [
        contract.OrderNotes(
            title=order_label(kind),
            done=not kind.left_for_tata,
            notes=[
                contract.OrderNote(
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


KIND: Final[PeriodProcessKind[EfenixInputs, PricingSummary]] = PeriodProcessKind(
    key="efenix",
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
    settings=(PERIODS_DIRECTORY,),
    templates=(),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        PeriodFolderCheck(collective_file_missing=efenix_messages.collective_file_missing),
        "period_files_in_excel",
        *TAIL,
    ),
)
