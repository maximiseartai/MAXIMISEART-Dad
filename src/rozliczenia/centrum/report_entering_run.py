"""Wpisanie raportów z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień taty i start (ADR 0028).

INTERMAX to Rejestr zleceń z Ustawień taty, Konfiguracja wykonawców i plik adresów Wykonawców leżą w ``config``, a
Skrzynkę raportów i pamięć własnych wpisów daje gospodarz (``HostParts.reports``). Proces nie należy do okresu: okres
Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc Logi Uruchomienia
trafiają do Skrzynki Zgłoszeń przy tym okresie. Start biegnie w miejscu „jedno naraz” ``RunHost``, więc nie zaczyna się
w czasie innego Uruchomienia, Aktualizacji narzędzia ani przywracania Kopii INTERMAX.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia.centrum.catalog import Catalog, declaration_of
from rozliczenia.centrum.configuration import ConfigurationFiles, InputWorkbook, open_in_excel
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import report_entering as report_entering_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import HostParts, PathNeed, PreparedRun, Start
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.run_context import RunContexts

_KIND: Final = declaration_of("report_entering")
_VIEW: Final = _KIND.view


@dataclass(frozen=True)
class ReportEnteringEntry:
    """Adapter startu Wpisania raportów: katalog procesów, pliki Konfiguracji i zależności procesu od Centrum.

    ``parts``: zegar procesu, przerwa ponownej próby podmiany INTERMAX, kroki podmiany na dysku, Skrzynka raportów i
    pamięć własnych wpisów. ``contexts``: Kontekst Uruchomienia pracy Centrum.
    """

    store: SettingsStore
    catalog: Catalog
    configuration: ConfigurationFiles
    parts: HostParts
    contexts: RunContexts

    @property
    def key(self) -> common_contract.ProcessKey:
        return "report_entering"

    def setup(self, last: runs_contract.RunRestored | None) -> report_entering_contract.ReportEnteringSetup:
        """Karta przed kliknięciem z ostatnim Wpisaniem raportów ``last`` z Logów Uruchomienia."""

        settings = self.store.load()
        register = settings.register
        return report_entering_contract.ReportEnteringSetup(
            title=_KIND.title,
            reminder=_VIEW.reminder,
            blocker=_KIND.settings_blocker(settings),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook(_VIEW.register_name, register, "data_file")]),
            last=last,
        )

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień taty i Konfiguracji; ``Refusal``, gdy Rejestr zleceń nie jest wskazany."""

        paths: dict[PathNeed, Path] = {"register": _KIND.required_paths(self.store.load())["register"]}
        paths.update({need: self.configuration.path(need) for need in _KIND.configuration_needs})
        start = Start(paths, period=None, dry_run=False)
        return self.catalog.prepared(self.key, start, self.parts, self.contexts.new())


def report_entering_router(
    host: RunHost, entry: ReportEnteringEntry, last: Callable[[], runs_contract.RunRestored | None]
) -> APIRouter:
    router = APIRouter(prefix="/api/report-entering", tags=["uruchomienia"])

    @router.get("", operation_id="getReportEnteringSetup")
    def setup() -> report_entering_contract.ReportEnteringSetup:
        return entry.setup(last())

    @router.post("/run", operation_id="startReportEntering", responses=NOT_FOUND_OR_CONFLICT)
    def start() -> runs_contract.RunView:
        return host.start(entry.prepare())

    return router
