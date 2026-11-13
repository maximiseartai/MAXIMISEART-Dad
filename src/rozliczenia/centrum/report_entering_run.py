"""Wpisanie raportów z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień Centrum i start (ADR 0028).

INTERMAX to Rejestr zleceń z Ustawień Centrum, folder okresów też z nich (okres z Plikiem zbiorczym jest dla Wpisania
raportów zamknięty), Lista Wykonawców z migawki Ustawień Centrum, a
Skrzynkę raportów i pamięć własnych wpisów daje gospodarz (``HostParts.reports``). Proces nie należy do okresu: okres
Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc Logi Uruchomienia
trafiają do Skrzynki Zgłoszeń przy tym okresie. Start biegnie w miejscu „jedno naraz” ``RunHost``, więc nie zaczyna się
w czasie innego Uruchomienia, Aktualizacji narzędzia ani przywracania Kopii INTERMAX.

Bez pliku dostępu do skrzynki raportów karta mówi, że go brakuje, a bez adresu żadnego Wykonawcy na Liście Wykonawców,
że trzeba je dopisać; start jest wtedy odrzucony. Kopię konfliktu OneDrive obok INTERMAX karta pokazuje z instrukcją i blokuje przycisk, a kliknięcie ze
starej karty kończy się Zatrzymaniem „dla taty” z tą samą instrukcją, zanim proces przeczyta skrzynkę (spec #1224,
US 46 i 51).

Widok Raporty pokazuje wynik ostatniego udanego kliknięcia z pliku wyniku, bez czytania skrzynki, dla całego okna
tego kliknięcia: każdy dzień z nazwą święta (``public_holidays``), a przy każdym Wykonawcy jego dni z liczbami,
problemami, informacjami o Przeniesieniach zleceń i zleceniami dnia (#1319, #1322, #1347). Problemy łączy przy odczycie z decyzjami „Zostaw moją”: różnica, przy
której tata kliknął „Zostaw moją” z tą samą treścią Wpisu, znika z widoku od razu, także gdy wynik pochodzi z
kliknięcia sprzed decyzji, a jej zlecenie jest wtedy wpisane. „Zostaw moją” zapisuje decyzję w pliku decyzji, nigdy w
INTERMAX, i tylko przy różnicy z wyniku ostatniego kliknięcia (spec #1224, US 38–39 i 52–58).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
from rozliczenia.centrum.process_kind import (
    PERIODS_DIRECTORY,
    HostParts,
    NeededSetting,
    PathNeed,
    PreparedRun,
    Start,
    start_warnings,
    workers_at_start,
)
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.report_entering_state import FileReportState, ShownNote, ShownProblem, ShownResult, ShownWorker
from rozliczenia.centrum.report_reminders import ShownReminders
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.settings.files import Good, Read, Unreadable
from rozliczenia.centrum.settings.folders import FolderSettings
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.public_holidays import public_holidays
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import DecisionsUnreadable, StateUnreadable
from rozliczenia.run_context import RunContexts
from rozliczenia.worker_list import WorkerList
from rozliczenia.worker_reports import Kept, Login, OrderKey, OrderNumber, OrderState

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
    ``config``, z których widok Raporty czyta wynik i decyzje, a „Zostaw moją” zapisuje decyzję. ``reminders``: wynik
    ostatniego sprawdzenia pracy Przypomnień o raporcie (ADR 0030).
    """

    settings: CentrumSettings
    catalog: Catalog
    configuration: ConfigurationFiles
    parts: HostParts
    contexts: RunContexts
    files: FileReportState
    reminders: Callable[[], ShownReminders]

    @property
    def key(self) -> common_contract.ProcessKey:
        return "report_entering"

    def setup(self, last: runs_contract.RunRestored | None) -> report_entering_contract.ReportEnteringSetup:
        """Stan przycisku na ekranie Raporty przed kliknięciem z ostatnim Wpisaniem raportów ``last`` z Logów Uruchomienia."""

        snapshot = self.settings.snapshot()
        settings = snapshot.folders
        register = settings.register
        return report_entering_contract.ReportEnteringSetup(
            title=_KIND.title,
            reminder=_VIEW.reminder,
            blocker=_blocker(_unchosen(settings)) or self._not_set_up() or _no_addresses(snapshot.workers) or _conflict(register),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook(_VIEW.register_name, register, "data_file")]),
            last=last,
        )

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień Centrum i Konfiguracji; ``Refusal``, gdy INTERMAX albo folder okresów nie jest
        wskazany."""

        snapshot = self.settings.snapshot()
        settings = snapshot.folders
        if (unchosen := _unchosen(settings)) is not None:
            raise unchosen
        paths: dict[PathNeed, Path] = {
            setting.field: path for setting in _SETTINGS if (path := setting.chosen(settings)) is not None
        }
        if missing := self._missing():
            raise refusal.report_entering_not_set_up(missing)
        workers = workers_at_start(snapshot.workers)
        if not workers.addresses().logins:
            raise refusal.report_entering_without_addresses()
        paths.update({need: self.configuration.path(need) for need in _KIND.configuration_needs})
        start = Start(
            paths,
            period=None,
            dry_run=False,
            settings=snapshot,
            workers=workers,
            quantity_rules=snapshot.quantity_rules,
            warnings=start_warnings(snapshot, _KIND.needs),
        )
        return self.catalog.prepared(self.key, start, self.parts, self.contexts.new())

    def view(self) -> report_entering_contract.ReportsView:
        """Widok Raporty całego okna z wyniku ostatniego kliknięcia i decyzji „Zostaw moją”, z Przypomnieniami o raporcie
        z ostatniego sprawdzenia ich pracy."""

        try:
            return _view(self.files.shown(), self.files.kept(), self.parts.now().date(), self.reminders())
        except (StateUnreadable, DecisionsUnreadable) as error:
            raise refusal.reports_unreadable() from error

    def keep(self, cell: report_entering_contract.KeptCell) -> report_entering_contract.ReportsView:
        """„Zostaw moją” przy różnicy ``cell`` z wyniku ostatniego kliknięcia; cały widok Raporty bez tej różnicy."""

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
        return self.view()

    def _missing(self) -> list[refusal.ReportEnteringFile]:
        """Pliki w ``config``, których nie ma: bez nich kliknięcie i tak by się nie udało."""

        missing: list[refusal.ReportEnteringFile] = []
        if self.parts.report_entering().inbox.access() == "missing":
            missing.append("inbox_access")
        return missing

    def _not_set_up(self) -> str | None:
        missing = self._missing()
        return refusal.report_entering_not_set_up(missing).message if missing else None


def _unchosen(settings: FolderSettings) -> refusal.Refusal | None:
    """„Najpierw wskaż …” z nazwami niewskazanych Ustawień kliknięcia; ``None``, gdy wszystkie są wskazane."""

    missing = [setting.name for setting in _SETTINGS if setting.chosen(settings) is None]
    return refusal.first_choose(missing) if missing else None


def _no_addresses(workers: Read[WorkerList] | Unreadable) -> str | None:
    """Blokada karty, gdy na dobrej Liście Wykonawców nikt nie ma adresu; złą listę karta zostawia odmowie startu."""

    if isinstance(workers, Good) and not workers.value.addresses().logins:
        return refusal.report_entering_without_addresses().message
    return None


def _blocker(unchosen: refusal.Refusal | None) -> str | None:
    return None if unchosen is None else unchosen.message


def _conflict(register: Path | None) -> str | None:
    copies = () if register is None else onedrive_conflicts.beside(register)
    return conflict_note(copies[0]) if copies else None


def _view(
    shown: ShownResult | None, kept: frozenset[Kept], today: date, reminders: ShownReminders
) -> report_entering_contract.ReportsView:
    """Całe okno wyniku ``shown`` bez różnic, przy których tata kliknął „Zostaw moją” (``kept``): dni otwarte ostatniego
    kliknięcia i dziś od najstarszego, Wykonawcy alfabetycznie z dniami, które mają liczby, problem albo informację. Chwila
    kliknięcia jest w UTC, jak każda chwila kontraktu, a przeglądarka pokazuje ją w czasie komputera taty.

    Przy dniu Wykonawcy stoją chwile Przypomnień o raporcie za ten dzień z ``reminders``. Przypomnienie za dzień, którego
    Wykonawca nie ma w wyniku kliknięcia, nie tworzy dnia, bo kafelek bez wyniku nie ma okienka."""

    if shown is None:
        return report_entering_contract.ReportsView(
            clicked_at=None,
            today=today,
            days=_days({today}),
            workers=[],
            unknown_senders=[],
            reminders_without_footer=reminders.without_footer,
        )
    problems = [problem for problem in shown.problems if problem.difference not in kept]
    placed: defaultdict[tuple[str, date], list[ShownProblem]] = defaultdict(list)
    for problem in problems:
        if problem.worker is not None:
            placed[problem.worker, problem.day].append(problem)
    noted: defaultdict[tuple[str, date], list[ShownNote]] = defaultdict(list)
    for found in shown.notes:
        noted[found.worker, found.day].append(found)
    figures = {(worker.worker, worker.day): worker for worker in shown.workers}
    days: defaultdict[str, list[report_entering_contract.ReportsWorkerDay]] = defaultdict(list)
    for name, day in sorted(figures.keys() | placed.keys() | noted.keys()):
        days[name].append(
            _worker_day(
                day,
                figures.get((name, day)),
                placed[name, day],
                noted[name, day],
                shown.detailed,
                reminders.sent.get((name, day), ()),
            )
        )
    return report_entering_contract.ReportsView(
        clicked_at=shown.clicked_at.astimezone(timezone.utc),
        today=today,
        days=_days({today, *shown.days}),
        workers=[report_entering_contract.ReportsWorker(worker=name, days=found) for name, found in days.items()],
        unknown_senders=[
            report_entering_contract.UnknownReportSender(day=problem.day, sender=problem.sender, reason=problem.reason)
            for problem in problems
            if problem.worker is None and problem.sender is not None
        ],
        reminders_without_footer=reminders.without_footer,
    )


def _days(days: set[date]) -> list[report_entering_contract.ReportsDay]:
    """Dni od najstarszego, każdy z nazwą polskiego święta albo ``None``."""

    holidays = {found: name for year in {day.year for day in days} for found, name in public_holidays(year).items()}
    return [report_entering_contract.ReportsDay(day=day, holiday=holidays.get(day)) for day in sorted(days)]


def _worker_day(
    day: date,
    figure: ShownWorker | None,
    problems: list[ShownProblem],
    notes: list[ShownNote],
    detailed: bool,
    reminders: tuple[datetime, ...],
) -> report_entering_contract.ReportsWorkerDay:
    """Dzień Wykonawcy z liczbami ``figure`` (``None``: dzień z samym problemem albo informacją, zera), problemami
    ``problems``, informacjami ``notes`` i chwilami Przypomnień o raporcie ``reminders``; stan zlecenia daje
    ``OrderState.of`` z numerów problemów dnia."""

    numbers = {problem.number for problem in problems}
    orders = () if figure is None else figure.orders_detail
    if figure is None and not detailed:
        orders = None
    return report_entering_contract.ReportsWorkerDay(
        day=day,
        orders=0 if figure is None else figure.orders,
        entered=0 if figure is None else figure.entered,
        mails=0 if figure is None else figure.mails,
        without_report=[] if figure is None else list(figure.without_report),
        problems=[_problem(problem) for problem in problems],
        notes=[report_entering_contract.ReportsNote(number=found.number, text=found.text) for found in notes],
        orders_detail=None
        if orders is None
        else [
            report_entering_contract.ReportsOrder(
                number=order.number,
                successful=order.successful,
                activities=order.activities,
                state=OrderState.of(reported=order.reported, problem=order.number in numbers).value,
            )
            for order in orders
        ],
        reminders=list(reminders),
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
    return report_entering_contract.ReportsProblem(reason=problem.reason, number=problem.number, keep=keep)


def conflict_note(copy: Path) -> str:
    """Zdanie ekranu Raporty o kopii konfliktu OneDrive ``copy`` obok INTERMAX: tata usuwa ją, zanim kliknie."""

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
    def view() -> report_entering_contract.ReportsView:
        return entry.view()

    @router.post("/keep", operation_id="keepManualValue", responses={**NOT_FOUND_OR_CONFLICT, **_UNREADABLE})
    def keep(cell: report_entering_contract.KeptCell) -> report_entering_contract.ReportsView:
        return entry.keep(cell)

    return router
