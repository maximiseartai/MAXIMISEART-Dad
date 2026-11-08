"""Uruchomienie procesu gotowe do startu, to samo dla każdego gospodarza rdzenia Uruchomienia procesu.

Centrum rozliczeń (``runs.Run``), Skrypt dla maszyn (``tools/uruchom_proces.py``) i odtworzenie z Logów
(``tools/lib/odtworzenie.py``) budują ``PreparedRun`` i prowadzą je przez ``PreparedRun.conduct``: ten sam rdzeń,
widok z wpisu katalogu procesów i Kontekst Uruchomienia. Gospodarz daje tylko rozmówcę, a plik metryk wybiera,
podając rdzeń procesu z jego ``metrics_path``.

Moduł nie importuje ``runs`` ani FastAPI: wątek Uruchomień Centrum i gospodarze bez serwera biorą go bez routera
Uruchomień.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import ProcessDeclaration
from rozliczenia.centrum.run_view import Shown, WarnedSummary
from rozliczenia.input_copy import InputCopy
from rozliczenia.process_run import Interlocutor, Outcome, Process, ProcessInputs, run_process
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.run_context import RunContext

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=WarnedSummary)


@dataclass(frozen=True)
class PreparedRun(Generic[InputsT, SummaryT]):
    """Uruchomienie procesu gotowe do startu: wpis procesu z katalogu, okres, rdzeń procesu, jego wejście i Kontekst
    Uruchomienia (``run_context.RunContexts.new``). ``pricing``: tryb Wyceny w efenix (``None``: proces bez trybów).
    """

    declaration: ProcessDeclaration[InputsT, SummaryT]
    period: str
    process: Process[InputsT, SummaryT, RunContext]
    inputs: InputsT
    context: RunContext
    pricing: contract.Pricing | None = None

    @property
    def dry_run(self) -> bool:
        return self.inputs.dry_run

    @property
    def input_copy(self) -> InputCopy | None:
        """Kopia wejścia, którą czytniki procesu wypełniają w trakcie Uruchomienia; ``None``: Uruchomienie bez Kopii."""

        return self.context.files.copy

    def info(self, run_id: str) -> contract.RunInfo:
        """Uruchomienie ``run_id`` na karcie: na żywo w Centrum i w Logach odtworzenia ta sama reguła wpisu procesu."""

        return self.declaration.run_info(run_id=run_id, period=self.period, dry_run=self.dry_run, pricing=self.pricing)

    def conduct(self, interlocutor: Interlocutor) -> Outcome[Shown[SummaryT]]:
        """Uruchomienie przez rdzeń z rozmówcą ``interlocutor`` i plikiem metryk procesu."""

        return run_process(
            self.process,
            self.inputs,
            interlocutor,
            view=self.declaration.view.shown,
            metrics_path=self.process.metrics_path(),
            context=self.context,
        )

    def progress_view(self, snapshot: ProgressSnapshot) -> contract.Progress:
        return self.declaration.view.progress(snapshot, dry_run=self.dry_run)
