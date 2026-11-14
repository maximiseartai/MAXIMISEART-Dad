"""Katalog procesów Centrum rozliczeń: jeden wpis na każdy proces, który Centrum uruchamia, i jedyny rejestr procesów
w działaniu (``Catalog``).

Wpis procesu (``process_kind.ProcessKind``) leży w ``centrum/processes/<proces>.py``, a ``KINDS`` to jedyna lista
wpisów. ``Catalog`` trzyma wpisy z rdzeniami i plikiem metryk każdego procesu: Uruchomienia, Metryki, Tablica okresów
i karty przed startem biorą rdzeń, historię metryk i silnik procesu tylko stąd, więc test podmienia je jednym obiektem
(``with_metrics``, ``steered``, ``with_engine``), a Skrypt dla maszyn i odtworzenie podają własny plik metryk tak samo.

Wejście procesu buduje tylko ``Catalog.prepared`` z wpisu procesu (``ProcessKind.inputs``), ten sam dla każdego
gospodarza. Kartę przed startem procesu z okresem składa ``period_start.PeriodStarts`` z polityki wpisu
(``PeriodStart``), a Uporządkowanie INTERMAX i Wpisanie raportów mają własne karty poza okresami (``intermax_run``,
ADR 0019, i ``report_entering_run``, ADR 0028).

Moduł nie robi I/O przy wczytaniu, a granicę jego importów opisuje i sprawdza ``tests/test_granice_importow.py``.
Tylko ten moduł importuje dowód katalogu procesów ``process_kind._CATALOG`` (docstring ``_CATALOG``), więc tylko on
składa ``PreparedRun``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.process_kind import Engine, HostParts, PeriodProcessKind, PreparedRun, ProcessKind, Start
from rozliczenia.centrum.process_kind import _CATALOG
from rozliczenia.centrum.processes import efenix, intermax, preparation, report_entering, settlement
from rozliczenia.process_run import Process, run_process
from rozliczenia.run_context import RunContext
from rozliczenia.telemetry import MetricsStore

KINDS: Final[tuple[ProcessKind[Any, Any], ...]] = (
    preparation.KIND,
    settlement.KIND,
    efenix.KIND,
    intermax.KIND,
    report_entering.KIND,
)
"""Kolejność statystyk w Metrykach."""

_BY_KEY: Final[Mapping[common_contract.ProcessKey, ProcessKind[Any, Any]]] = {kind.key: kind for kind in KINDS}
assert sum(kind.journaled for kind in KINDS) == 1, "dziennik Wyceny w efenix w katalogu Logów pisze jeden proces"


@dataclass(frozen=True)
class Catalog:
    kinds: tuple[ProcessKind[Any, Any], ...]
    metrics_paths: Mapping[common_contract.ProcessKey, Path]
    engine: Engine = run_process

    @classmethod
    def default(cls) -> Catalog:
        """Prawdziwe rdzenie i pliki metryk w katalogu narzędzia, bez I/O."""

        return cls(KINDS, {kind.key: kind.default_metrics for kind in KINDS})

    def kind(self, key: common_contract.ProcessKey) -> ProcessKind[Any, Any]:
        """Wpis procesu ``key`` z rdzeniem tego katalogu."""

        return next(kind for kind in self.kinds if kind.key == key)

    def period_kind(self, key: common_contract.PeriodProcessKey) -> PeriodProcessKind[Any, Any]:
        kind = self.kind(key)
        assert isinstance(kind, PeriodProcessKind), f"{key} to proces z okresem (common_contract.PeriodProcessKey)"
        return kind

    @property
    def journaled(self) -> common_contract.ProcessKey:
        return next(kind.key for kind in self.kinds if kind.journaled)

    def metrics(self, key: common_contract.ProcessKey) -> MetricsStore:
        return MetricsStore(self.metrics_paths[key], self.kind(key).core.counter_names)

    def with_metrics(self, paths: Mapping[common_contract.ProcessKey, Path]) -> Catalog:
        return replace(self, metrics_paths={**self.metrics_paths, **paths})

    def steered(self, steer: Callable[[Process[Any, Any, RunContext]], Process[Any, Any, RunContext]]) -> Catalog:
        return replace(self, kinds=tuple(replace(kind, core=steer(kind.core)) for kind in self.kinds))

    def with_engine(self, engine: Engine) -> Catalog:
        """Ten katalog z silnikiem ``engine`` w miejscu ``run_process``: tylko wyrocznia
        ``verify-jedno-uruchomienie-naraz``, której silnik to kroki modelu, a ``PreparedRun.conduct`` zostaje prawdziwe."""

        return replace(self, engine=engine)

    def prepared(
        self, key: common_contract.ProcessKey, start: Start, parts: HostParts, context: RunContext
    ) -> PreparedRun[Any, Any]:
        """Uruchomienie procesu ``key`` gotowe do startu: rdzeń i historia metryk procesu z tego katalogu.

        Okres Uruchomienia to ``start.period``, a bez niego okres z wejścia (Plik zbiorczy, dzień Uporządkowania
        INTERMAX, ADR 0019). ``ValueError`` to błąd gospodarza, nie taty: start bez potrzeby procesu albo Podgląd bez
        zapisu procesu bez niego; odmowy dla taty daje wcześniej karta startu (``period_start``, ``intermax_run``,
        ``report_entering_run``).
        """

        kind = self.kind(key)
        if set(start.paths) != set(kind.path_needs):
            raise ValueError(f"{kind.title} potrzebuje plików {sorted(kind.path_needs)}, a start ma {sorted(start.paths)}")
        if "period" in kind.needs and start.period is None:
            raise ValueError(f"{kind.title} potrzebuje okresu")
        if "workers" in kind.needs and start.workers is None:
            raise ValueError(f"{kind.title} potrzebuje Listy Wykonawców, a start jej nie ma")
        if "efenix_window" in kind.needs and parts.efenix is None:
            raise ValueError(f"{kind.title} potrzebuje okna efenix")
        if "worker_report_inbox" in kind.needs and parts.reports is None:
            raise ValueError(f"{kind.title} potrzebuje Skrzynki raportów")
        if start.dry_run and kind.core.preview is None:
            raise ValueError(f"{kind.title} nie ma Podglądu bez zapisu")
        pricing = kind.pricing_of(start.pricing)
        inputs = kind.inputs(replace(start, pricing=pricing), parts)
        period = inputs.period if start.period is None else start.period
        return PreparedRun(
            kind,
            period,
            inputs,
            context,
            self.metrics(key),
            pricing,
            self.engine,
            _CATALOG,
            start.settings,
            start.warnings,
            start.quantity_rules if kind.quantity_rules else None,
        )


CATALOG: Final = Catalog.default()


def declaration_of(key: common_contract.ProcessKey) -> ProcessKind[Any, Any]:
    """Wpis procesu ``key`` z prawdziwym rdzeniem; klucz z dysku (Logi, plik ostatniego startu) zwalidował już kontrakt."""

    return _BY_KEY[key]
