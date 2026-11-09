"""Kontrakt Metryk: Historia Uruchomień procesu, statystyki czasu i wyniki."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import computed_field

from rozliczenia import domain
from rozliczenia.centrum.contract.common import Model, ProcessKey
from rozliczenia.centrum.contract.runs import ResultTone, result_tone, result_word
from rozliczenia.domain import RunMode
from rozliczenia.process_run import RunResult


class PhaseDuration(Model):
    phase: str
    duration_ms: int


class ProcessRun(Model):
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
    stop_kind: domain.StopKind | None
    run_id: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tone(self) -> ResultTone:
        """Ton wyniku (``runs.result_tone``): plakietka w Historii i kolor przerwanego w Metrykach."""

        return result_tone(self.result, self.stop_kind)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def result_word(self) -> str:
        """Wynik słowem małą literą (``runs.result_word``), np. „zatrzymano” przy przerwanym w Metrykach."""

        return result_word(self.tone)


class PhasePercentiles(Model):
    phase: str
    p50_ms: int
    p95_ms: int


class Percentiles(Model):
    """P50 i P95 czasu całego Uruchomienia procesu i każdego etapu, w milisekundach."""

    p50_ms: int
    p95_ms: int
    phases: list[PhasePercentiles]


class ResultCounts(Model):
    """Liczba Uruchomień procesu z każdym tonem wyniku (``runs.result_tone``)."""

    ok: int
    needs_review: int
    stopped: int
    failed: int


class ModeStatistics(Model):
    """Statystyki jednego procesu w jednym trybie; bez ``percentiles`` poniżej minimum ukończonych obserwacji."""

    process: ProcessKey
    mode: RunMode
    completed_runs: int
    percentiles: Percentiles | None
    results: ResultCounts


class RecentResults(Model):
    """Wyniki Uruchomień procesu obu procesów z ostatnich ``weeks`` tygodni."""

    weeks: int
    results: ResultCounts


class ProcessFacts(Model):
    """Proces w Metrykach: klucz i krótka nazwa w filtrach."""

    process: ProcessKey
    label: str


class Metrics(Model):
    """Historia Uruchomień procesu z obu plików metryk, czytanych przy każdym odczycie, od najnowszego.

    ``processes``: procesy w kolejności statystyk; pierwszy jest wybrany w filtrze."""

    processes: list[ProcessFacts]
    phases: list[str]
    minimum_completed_runs: int
    runs: list[ProcessRun]
    statistics: list[ModeStatistics]
    recent: RecentResults
