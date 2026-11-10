"""Wpisanie raportów z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień taty i start (ADR 0028).

INTERMAX to Rejestr zleceń z Ustawień taty, folder okresów też z nich (okres z Plikiem zbiorczym jest dla Wpisania
raportów zamknięty), Konfiguracja wykonawców i plik adresów Wykonawców leżą w ``config``, a
Skrzynkę raportów i pamięć własnych wpisów daje gospodarz (``HostParts.reports``). Proces nie należy do okresu: okres
Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc Logi Uruchomienia
trafiają do Skrzynki Zgłoszeń przy tym okresie. Start biegnie w miejscu „jedno naraz” ``RunHost``, więc nie zaczyna się
w czasie innego Uruchomienia, Aktualizacji narzędzia ani przywracania Kopii INTERMAX.

Bez pliku dostępu do skrzynki raportów albo pliku adresów Wykonawców karta mówi, którego brakuje, a start jest
odrzucony. Kopię konfliktu OneDrive obok INTERMAX karta pokazuje z instrukcją i blokuje przycisk, a kliknięcie ze
starej karty kończy się Zatrzymaniem „dla taty” z tą samą instrukcją, zanim proces przeczyta skrzynkę (spec #1224,
US 46 i 51).

Widok Raporty pokazuje wynik ostatniego udanego kliknięcia z pliku wyniku, bez czytania skrzynki, z dniem do wyboru
(domyślnie dziś z zegara Centrum). Problemy łączy przy odczycie z decyzjami „Zostaw moją”: różnica, przy której tata
kliknął „Zostaw moją” z tą samą treścią Wpisu, znika z widoku od razu, także gdy wynik pochodzi z kliknięcia sprzed
decyzji. „Zostaw moją” zapisuje decyzję w pliku decyzji, nigdy w INTERMAX, i tylko przy różnicy z wyniku ostatniego
kliknięcia (spec #1224, US 38–39 i 52–58).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia import onedrive_conflicts
from rozliczenia import report_entering_messages as messages
from rozliczenia.centrum import refusal
from rozliczenia.centrum.catalog import Catalog, declaration_of
from rozliczenia.centrum.configuration import ConfigurationFiles, InputWorkbook, open_in_excel
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import report_entering as report_entering_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import PERIODS_DIRECTORY, HostParts, NeededSetting, PathNeed, PreparedRun, Start
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.report_entering_state import FileReportState, ShownProblem, ShownResult
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.settings import Settings, SettingsStore
from rozliczenia.file_state import file_state
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import DecisionsUnreadable, StateUnreadable
from rozliczenia.run_context import RunContexts
from rozliczenia.worker_reports import Kept, Login, OrderKey, OrderNumber

_KIND: Final = declaration_of("report_entering")
_UNREADABLE: Final[dict[int | str, dict[str, object]]] = {500: {"model": common_contract.Problem}}
_VIEW: Final = _KIND.view
_SETTINGS: Final[tuple[NeededSetting, ...]] = (*_KIND.settings, PERIODS_DIRECTORY)
"""Ustawienia, bez których kliknięcie nie startuje: INTERMAX i folder okresów. Folder okresów nie jest w
``KIND.settings``, bo tam znaczy, że proces należy do okresu i czyta jego pliki (Diagnoza Folderu okresu)."""


@dataclass(frozen=True)
class ReportEnteringEntry:
    """Adapter startu Wpisania raportów: katalog procesów, pliki Konfiguracji i zależności procesu od Centrum.

    ``parts``: zegar procesu, przerwa ponownej próby podmiany INTERMAX, kroki podmiany na dysku, Skrzynka raportów i
    pamięć własnych wpisów. ``contexts``: Kontekst Uruchomienia pracy Centrum. ``files``: pliki Wpisania raportów w
    ``config``, z których widok Raporty czyta wynik i decyzje, a „Zostaw moją” zapisuje decyzję.
    """

    store: SettingsStore
    catalog: Catalog
    configuration: ConfigurationFiles
    parts: HostParts
    contexts: RunContexts
    files: FileReportState

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
            blocker=_blocker(_unchosen(settings)) or self._not_set_up() or _conflict(register),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook(_VIEW.register_name, register, "data_file")]),
            last=last,
        )

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień taty i Konfiguracji; ``Refusal``, gdy INTERMAX albo folder okresów nie jest
        wskazany."""

        settings = self.store.load()
        if (unchosen := _unchosen(settings)) is not None:
            raise unchosen
        paths: dict[PathNeed, Path] = {
            setting.field: path for setting in _SETTINGS if (path := setting.chosen(settings)) is not None
        }
        if missing := self._missing():
            raise refusal.report_entering_not_set_up(missing)
        paths.update({need: self.configuration.path(need) for need in _KIND.configuration_needs})
        start = Start(paths, period=None, dry_run=False)
        return self.catalog.prepared(self.key, start, self.parts, self.contexts.new())

    def view(self, day: date | None) -> report_entering_contract.ReportsView:
        """Widok Raporty dnia ``day`` (``None``: dziś) z wyniku ostatniego kliknięcia i decyzji „Zostaw moją”."""

        try:
            return _view(self.files.shown(), self.files.kept(), day or self.parts.now().date(), self.parts.now().date())
        except (StateUnreadable, DecisionsUnreadable) as error:
            raise refusal.reports_unreadable() from error

    def keep(self, cell: report_entering_contract.KeptCell) -> report_entering_contract.ReportsView:
        """„Zostaw moją” przy różnicy ``cell`` z wyniku ostatniego kliknięcia; widok Raporty dnia jej zlecenia."""

        kept = Kept(
            OrderKey(OrderNumber(cell.number), cell.day, Login(cell.worker)), ReportColumn(cell.column), cell.reported
        )
        try:
            shown = self.files.shown()
            if shown is None or kept not in {problem.difference for problem in shown.problems}:
                raise refusal.difference_gone()
            self.files.keep(kept)
        except (StateUnreadable, DecisionsUnreadable) as error:
            raise refusal.reports_unreadable() from error
        return self.view(cell.day)

    def _missing(self) -> list[refusal.ReportEnteringFile]:
        """Pliki w ``config``, których nie ma: bez nich kliknięcie i tak by się nie udało."""

        missing: list[refusal.ReportEnteringFile] = []
        if self.parts.report_entering().inbox.access() == "missing":
            missing.append("inbox_access")
        if file_state(self.configuration.path("worker_addresses")) == "missing":
            missing.append("worker_addresses")
        return missing

    def _not_set_up(self) -> str | None:
        missing = self._missing()
        return refusal.report_entering_not_set_up(missing).message if missing else None


def _unchosen(settings: Settings) -> refusal.Refusal | None:
    """„Najpierw wskaż …” z nazwami niewskazanych Ustawień kliknięcia; ``None``, gdy wszystkie są wskazane."""

    missing = [setting.name for setting in _SETTINGS if setting.chosen(settings) is None]
    return refusal.first_choose(missing) if missing else None


def _blocker(unchosen: refusal.Refusal | None) -> str | None:
    return None if unchosen is None else unchosen.message


def _conflict(register: Path | None) -> str | None:
    copies = () if register is None else onedrive_conflicts.beside(register)
    return conflict_note(copies[0]) if copies else None


def _view(
    shown: ShownResult | None, kept: frozenset[Kept], day: date, today: date
) -> report_entering_contract.ReportsView:
    """Wykonawcy dnia ``day`` z wyniku ``shown`` bez różnic, przy których tata kliknął „Zostaw moją” (``kept``); dni do
    wyboru to dziś i dni otwarte ostatniego kliknięcia, od najnowszego. Chwila kliknięcia jest w UTC, jak każda chwila
    kontraktu, a przeglądarka pokazuje ją w czasie komputera taty."""

    if shown is None:
        return report_entering_contract.ReportsView(
            clicked_at=None, today=today, day=day, days=[today], workers=[], unknown_senders=[]
        )
    problems = [problem for problem in shown.problems if problem.day == day and problem.difference not in kept]
    figures = {worker.worker: worker for worker in shown.workers if worker.day == day}
    names = sorted(figures.keys() | {problem.worker for problem in problems if problem.worker is not None})
    workers = []
    for name in names:
        figure = figures.get(name)
        workers.append(
            report_entering_contract.ReportsWorker(
                worker=name,
                orders=0 if figure is None else figure.orders,
                entered=0 if figure is None else figure.entered,
                mails=0 if figure is None else figure.mails,
                problems=[_problem(problem) for problem in problems if problem.worker == name],
                without_report=[] if figure is None else list(figure.without_report),
            )
        )
    return report_entering_contract.ReportsView(
        clicked_at=shown.clicked_at.astimezone(timezone.utc),
        today=today,
        day=day,
        days=sorted({today, *shown.days}, reverse=True),
        workers=workers,
        unknown_senders=[_problem(problem) for problem in problems if problem.worker is None],
    )


def _problem(problem: ShownProblem) -> report_entering_contract.ReportsProblem:
    difference = problem.difference
    keep = (
        None
        if difference is None
        else report_entering_contract.KeptCell(
            number=difference.key.number,
            day=difference.key.day,
            worker=difference.key.worker,
            column=difference.column.value,
            reported=difference.reported,
        )
    )
    return report_entering_contract.ReportsProblem(
        reason=problem.reason, number=problem.number, sender=problem.sender, keep=keep
    )


def conflict_note(copy: Path) -> str:
    """Zdanie karty o kopii konfliktu OneDrive ``copy`` obok INTERMAX: tata usuwa ją, zanim kliknie."""

    return f"Obok INTERMAX leży kopia konfliktu OneDrive {copy.name}. {messages.CONFLICT_ACTION} Potem odśwież kartę."


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

    @router.get("/view", operation_id="getReportsView", responses=_UNREADABLE)
    def view(day: date | None = None) -> report_entering_contract.ReportsView:
        return entry.view(day)

    @router.post("/keep", operation_id="keepManualValue", responses={**NOT_FOUND_OR_CONFLICT, **_UNREADABLE})
    def keep(cell: report_entering_contract.KeptCell) -> report_entering_contract.ReportsView:
        return entry.keep(cell)

    return router
