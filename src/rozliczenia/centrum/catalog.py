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

_BY_KEY: Final[Mapping[common_contract.ProcessKey, ProcessKind[Any, Any]]] = {kind.key: kind for kind in KINDS}
assert sum(kind.journaled for kind in KINDS) == 1, "dziennik Wyceny w efenix w katalogu Logów pisze jeden proces"


@dataclass(frozen=True)
class Catalog:
    kinds: tuple[ProcessKind[Any, Any], ...]
    metrics_paths: Mapping[common_contract.ProcessKey, Path]
    engine: Engine = run_process

    @classmethod
    def default(cls) -> Catalog:
        return cls(KINDS, {kind.key: kind.default_metrics for kind in KINDS})

    def kind(self, key: common_contract.ProcessKey) -> ProcessKind[Any, Any]:
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
        return replace(self, engine=engine)

    def prepared(
        self, key: common_contract.ProcessKey, start: Start, parts: HostParts, context: RunContext
    ) -> PreparedRun[Any, Any]:
        kind = self.kind(key)
        if set(start.paths) != set(kind.path_needs):
            raise ValueError(f"{kind.title} potrzebuje plików {sorted(kind.path_needs)}, a start ma {sorted(start.paths)}")
        if "period" in kind.needs and start.period is None:
            raise ValueError(f"{kind.title} potrzebuje okresu")
        if (absent := start.settings.missing(kind.needs)) is not None:
            raise ValueError(f"{kind.title} {absent}")
        if "efenix_window" in kind.needs and parts.efenix is None:
            raise ValueError(f"{kind.title} potrzebuje okna efenix")
        if "worker_report_inbox" in kind.needs and parts.reports is None:
            raise ValueError(f"{kind.title} potrzebuje Skrzynki raportów")
        if start.dry_run and kind.core.preview is None:
            raise ValueError(f"{kind.title} nie ma Podglądu bez zapisu")
        pricing = kind.pricing_of(start.pricing)
        settings = start.settings.for_process(kind.needs)
        inputs = kind.inputs(replace(start, pricing=pricing, settings=settings), parts)
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
            settings,
        )


CATALOG: Final = Catalog.default()


def declaration_of(key: common_contract.ProcessKey) -> ProcessKind[Any, Any]:
    return _BY_KEY[key]
