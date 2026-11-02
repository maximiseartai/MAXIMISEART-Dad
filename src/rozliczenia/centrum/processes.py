"""Procesy Centrum rozliczeń: rdzeń każdego procesu (seam ``Process``) z jego plikiem metryk.

Uruchomienia i Metryki biorą rdzeń procesu i jego plik metryk (``Process.metrics_path``) tylko stąd.
"""

from __future__ import annotations

from dataclasses import dataclass

from rozliczenia import efenix_process, intermax_process, preparation_process, settlement_process
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.domain import SettlementSummary
from rozliczenia.efenix_pricing import PricingSummary
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.intermax_process import OrderingInputs
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import Process
from rozliczenia.settlement_process import SettlementInputs


@dataclass(frozen=True)
class Processes:
    """Rdzenie czterech procesów; pola zamiast słownika, bo wpis procesu buduje wejście konkretnego typu."""

    preparation: Process[PreparationInputs, PreparationSummary]
    settlement: Process[SettlementInputs, SettlementSummary]
    efenix: Process[EfenixInputs, PricingSummary]
    intermax: Process[OrderingInputs, OrderingSummary]

    @classmethod
    def default(cls) -> Processes:
        return cls(preparation_process.PROCESS, settlement_process.PROCESS, efenix_process.PROCESS, intermax_process.PROCESS)
