"""Katalog procesów Centrum rozliczeń: jeden wpis na każdy proces, który Centrum uruchamia, i jedyny rejestr procesów
w działaniu (``Catalog``).

Wpis procesu (``process_kind.ProcessKind``) leży w ``centrum/processes/<proces>.py``, a ``KINDS`` to jedyna lista
wpisów. ``Catalog`` trzyma wpisy z rdzeniami i plikiem metryk każdego procesu: Uruchomienia, Metryki, Tablica okresów
i karty przed startem biorą rdzeń, historię metryk i silnik procesu tylko stąd, więc test podmienia je jednym obiektem
(``with_metrics``, ``steered``, ``with_engine``), a Skrypt dla maszyn i odtworzenie podają własny plik metryk tak samo.

Kartę przed startem i wejście procesu buduje adapter startu procesu (``*_run.py``): proces z okresem przez
``runs.ProcessEntry``, Uporządkowanie INTERMAX własną kartą poza okresami (ADR 0019).

Moduł leży nisko w grafie importów i nie robi I/O przy wczytaniu: nie wczytuje ``runs``, Diagnozy, Konfiguracji,
Tablicy okresów, okna efenix ani FastAPI (``tests/test_granice_importow.py``), więc każdy moduł Centrum może go czytać
bez cyklu, a wersje komentarza Uruchomienia biorą z niego ``declaration_of``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from rozliczenia.centrum import contract
from rozliczenia.centrum.process_kind import Engine, PreparedRun, ProcessKind
from rozliczenia.centrum.processes import efenix, intermax, preparation, settlement
from rozliczenia.process_run import Process, ProcessInputs, run_process
from rozliczenia.run_context import RunContext
from rozliczenia.telemetry import MetricsStore

KINDS: Final[tuple[ProcessKind[Any, Any], ...]] = (preparation.KIND, settlement.KIND, efenix.KIND, intermax.KIND)
"""Kolejność statystyk w Metrykach."""

_BY_KEY: Final[Mapping[contract.ProcessKey, ProcessKind[Any, Any]]] = {kind.key: kind for kind in KINDS}


@dataclass(frozen=True)
class Catalog:
    """Wpisy procesów z rdzeniami (``kinds``), plik metryk każdego procesu (``metrics_paths``) i silnik, który prowadzi
    każde Uruchomienie (``engine``)."""

    kinds: tuple[ProcessKind[Any, Any], ...]
    metrics_paths: Mapping[contract.ProcessKey, Path]
    engine: Engine = run_process

    @classmethod
    def default(cls) -> Catalog:
        """Prawdziwe rdzenie i pliki metryk w katalogu narzędzia, bez I/O."""

        return cls(KINDS, {kind.key: kind.default_metrics for kind in KINDS})

    def kind(self, key: contract.ProcessKey) -> ProcessKind[Any, Any]:
        """Wpis procesu ``key`` z rdzeniem tego katalogu."""

        return next(kind for kind in self.kinds if kind.key == key)

    def metrics(self, key: contract.ProcessKey) -> MetricsStore:
        """Historia metryk procesu ``key``: plik metryk tego katalogu z licznikami rdzenia procesu."""

        return MetricsStore(self.metrics_paths[key], self.kind(key).core.counter_names)

    def with_metrics(self, paths: Mapping[contract.ProcessKey, Path]) -> Catalog:
        """Ten katalog z plikami metryk ``paths`` w miejscu plików procesów, które wymienia."""

        return replace(self, metrics_paths={**self.metrics_paths, **paths})

    def steered(self, steer: Callable[[Process[Any, Any, RunContext]], Process[Any, Any, RunContext]]) -> Catalog:
        """Ten katalog z rdzeniem każdego procesu podmienionym przez ``steer`` (testy)."""

        return replace(self, kinds=tuple(replace(kind, core=steer(kind.core)) for kind in self.kinds))

    def with_engine(self, engine: Engine) -> Catalog:
        """Ten katalog z silnikiem ``engine`` w miejscu ``run_process``: tylko wyrocznia
        ``verify-jedno-uruchomienie-naraz``, której silnik to kroki modelu, a ``PreparedRun.conduct`` zostaje prawdziwe."""

        return replace(self, engine=engine)

    def prepared(
        self,
        key: contract.ProcessKey,
        *,
        period: str,
        inputs: ProcessInputs,
        context: RunContext,
        pricing: contract.Pricing | None = None,
    ) -> PreparedRun[Any, Any]:
        """Uruchomienie procesu ``key`` gotowe do startu: rdzeń i historia metryk procesu z tego katalogu."""

        return PreparedRun(self.kind(key), period, inputs, context, self.metrics(key), pricing, self.engine)


CATALOG: Final = Catalog.default()


def declaration_of(key: contract.ProcessKey) -> ProcessKind[Any, Any]:
    """Wpis procesu ``key`` z prawdziwym rdzeniem; klucz z dysku (Logi, plik ostatniego startu) zwalidował już kontrakt."""

    return _BY_KEY[key]
