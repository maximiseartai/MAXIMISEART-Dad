"""Operacje procesów w testach na syntetycznych plikach taty z ``tools/lib/atrapy``: Przygotowanie pliku zbiorczego na
fixture, obserwator postępu Przebiegu rozliczeń i ostrzeżenia Przygotowania bez ostrzeżeń ilości."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from atrapy.preparation import PERIOD, PreparationFixture
from atrapy.settlement import worker_list
from rozliczenia.collective_preparation import (
    PreparationInputs,
    PreparationSummary,
    prepare_collective_file,
)
from rozliczenia.dad_files import DadFiles
from rozliczenia.decision import Conversation
from rozliczenia.domain import ProgressEvent, ProgressObserver
from rozliczenia.message import Message
from rozliczenia.progress import ProgressProjection
from rozliczenia.run_context import UNASKED, RunContext

QUANTITY_WARNINGS = frozenset({"NIEZNANE_URZADZENIA", "WIERSZE_Z_OPISU", "KOLUMNY_Z_OPISU"})
"""Kody ostrzeżeń o Ilościach usług do uzupełnienia (``tests/test_ostrzezenia_ilosci.py``)."""


def projected(projection: ProgressProjection) -> ProgressObserver:
    def observer(event: ProgressEvent) -> None:
        projection.update(event)

    return observer


def run_preparation(
    fixture: PreparationFixture,
    period: str = PERIOD,
    *,
    dry_run: bool = False,
    observer: ProgressObserver | None = None,
    conversation: Conversation = UNASKED,
    files: DadFiles | None = None,
) -> PreparationSummary:
    """Przygotowanie ``fixture`` w okresie ``period``; ``files``: uchwyt plików taty z Kopią wejścia (``None``: bez
    Kopii)."""

    inputs = PreparationInputs(
        fixture.register_path,
        fixture.periods_directory,
        period,
        worker_list(),
        fixture.internal_template_path,
        fixture.collective_template_path,
        dry_run,
    )
    context = RunContext(observer=observer, conversation=conversation)
    return prepare_collective_file(inputs, context if files is None else replace(context, files=files))


def other_warnings(warnings: Sequence[Message]) -> list[Message]:
    """Ostrzeżenia Przygotowania bez ostrzeżeń ilości, które ma każdy okres (``tests/test_ostrzezenia_ilosci.py``)."""

    return [warning for warning in warnings if warning.code not in QUANTITY_WARNINGS]
