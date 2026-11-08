"""Procesy Centrum rozliczeń: rdzeń każdego procesu (seam ``Process``) z jego plikiem metryk.

Uruchomienia i Metryki biorą rdzeń procesu i jego plik metryk (``Process.metrics_path``) tylko stąd.
"""

from __future__ import annotations

from dataclasses import dataclass

from rozliczenia import efenix_process, intermax_process, preparation_process, settlement_process
from rozliczenia.collective_preparation import PreparationInputs, PreparationSummary
from rozliczenia.engine import SettlementInputs, SettlementSummary
from rozliczenia.efenix_pricing import EfenixInputs, PricingSummary
from rozliczenia.intermax_ordering import OrderingInputs, OrderingSummary
from rozliczenia.process_run import Process
from rozliczenia.run_context import RunContext


@dataclass(frozen=True)
class Processes:
    """Rdzenie czterech procesów; pola zamiast słownika, bo wpis procesu buduje wejście konkretnego typu."""

    preparation: Process[PreparationInputs, PreparationSummary, RunContext]
    settlement: Process[SettlementInputs, SettlementSummary, RunContext]
    efenix: Process[EfenixInputs, PricingSummary, RunContext]
    intermax: Process[OrderingInputs, OrderingSummary, RunContext]

    @classmethod
    def default(cls) -> Processes:
        return cls(preparation_process.PROCESS, settlement_process.PROCESS, efenix_process.PROCESS, intermax_process.PROCESS)
