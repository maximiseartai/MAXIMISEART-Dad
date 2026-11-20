from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia import onedrive_conflicts, workbook_files
from rozliczenia.intermax_messages import CONFLICT_ACTION
from rozliczenia.centrum import refusal
from rozliczenia.centrum.catalog import Catalog, declaration_of
from rozliczenia.centrum.configuration import InputWorkbook, open_in_excel
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import report_entering as report_entering_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import (
    PERIODS_DIRECTORY,
    HostParts,
    NeededSetting,
    PathNeed,
    PreparedRun,
    SettingField,
    chosen_settings,
    start_from_settings,
)
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.report_entering_state import (
    FileReportState,
    ShownNote,
    ShownProblem,
    ShownResult,
    ShownWorker,
)
from rozliczenia.centrum.report_reminders import ShownReminders
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.settings.reads import SettingsReads, SettingsSnapshot, WorkerListRead
from rozliczenia.public_holidays import public_holidays
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import DecisionsUnreadable, StateUnreadable
from rozliczenia.run_context import RunContexts
from rozliczenia.worker_list import WorkerList
from rozliczenia.worker_reports import (
    Kept,
    Login,
    MailId,
    Offer,
    OrderKey,
    OrderNumber,
    OrderState,
    RequestedEntry,
    SenderAddress,
    Verdict,
    WorkerAddresses,
)

_KIND: Final = declaration_of("report_entering")
_UNREADABLE: Final[dict[int | str, dict[str, object]]] = {500: {"model": common_contract.Problem}}
_VIEW: Final = _KIND.view
_SETTINGS: Final[tuple[NeededSetting, ...]] = (*_KIND.settings, PERIODS_DIRECTORY)


@dataclass(frozen=True)
class ReportEnteringEntry:
    settings: SettingsReads
    catalog: Catalog
    parts: HostParts
    contexts: RunContexts
    files: FileReportState
    reminders: Callable[[], ShownReminders]

    @property
    def key(self) -> common_contract.ProcessKey:
        return "report_entering"

    def setup(self, last: runs_contract.RunRestored | None) -> report_entering_contract.ReportEnteringSetup:
        snapshot = self.settings.snapshot()
        chosen = _chosen(snapshot)
        register = None if isinstance(chosen, refusal.Refusal) else chosen["register"]
        return report_entering_contract.ReportEnteringSetup(
            reminder=_VIEW.reminder,
            blocker=_blocker(chosen) or self._not_set_up() or _no_addresses(snapshot.workers) or _conflict(register),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook(_VIEW.register_name, register, "data_file")]),
            last=last,
        )

    def prepare(self, requested: RequestedEntry | None = None) -> PreparedRun[Any, Any]:
        snapshot = self.settings.snapshot()
        chosen = _chosen(snapshot)
        if isinstance(chosen, refusal.Refusal):
            raise chosen
        paths: dict[PathNeed, Path] = {field: path for field, path in chosen.items()}
        if missing := self._missing():
            raise refusal.report_entering_not_set_up(missing)
        start = start_from_settings(_KIND, snapshot, paths, period=None, dry_run=False)
        if not start.settings.worker_list().addresses().logins:
            raise refusal.report_entering_without_addresses()
        if requested is None:
            return self.catalog.prepared(self.key, start, self.parts, self.contexts.new())
        if workbook_files.is_open_in_excel(chosen["register"]):
            raise refusal.request_while_open_in_excel()
        parts = replace(self.parts, reports=replace(self.parts.report_entering(), requested=requested))
        return self.catalog.prepared(self.key, start, parts, self.contexts.new())

    def view(self) -> report_entering_contract.ReportsView:
        workers = self.settings.snapshot().workers.counted_or_unreadable()
        listed = workers if isinstance(workers, WorkerList) else WorkerList(())
        try:
            return _view(self.files.shown(), self.files.kept(), self.parts.now().date(), self.reminders(), listed.addresses())
        except (StateUnreadable, DecisionsUnreadable) as error:
            raise refusal.reports_unreadable() from error

    def keep(self, cell: report_entering_contract.KeptCell) -> report_entering_contract.ReportsView:
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

    def on_request(self, cell: report_entering_contract.RequestedCell) -> PreparedRun[Any, Any]:
        clicked = Offer(
            MailId(cell.mail),
            Login(cell.worker),
            cell.day,
            OrderNumber(cell.number),
            Verdict(cell.successful),
            cell.activities,
            cell.order_day,
        )
        try:
            shown = self.files.shown()
        except StateUnreadable as error:
            raise refusal.reports_unreadable() from error
        offer = None if shown is None else shown.offers().get(clicked.token)
        if offer is None or offer.order_day != clicked.order_day:
            raise refusal.request_gone()
        return self.prepare(offer.decide(self.parts.now()))

    def _missing(self) -> list[refusal.ReportEnteringFile]:
        missing: list[refusal.ReportEnteringFile] = []
        if self.parts.report_entering().inbox.access() == "missing":
            missing.append("inbox_access")
        return missing

    def _not_set_up(self) -> str | None:
        missing = self._missing()
        return refusal.report_entering_not_set_up(missing).message if missing else None


def _chosen(snapshot: SettingsSnapshot) -> dict[SettingField, Path] | refusal.Refusal:
    return chosen_settings(snapshot, _SETTINGS, _KIND.needs)


def _no_addresses(workers: WorkerListRead) -> str | None:
    if workers.problem() is None and not workers.counted().addresses().logins:
        return refusal.report_entering_without_addresses().message
    return None


def _blocker(chosen: dict[SettingField, Path] | refusal.Refusal) -> str | None:
    return chosen.message if isinstance(chosen, refusal.Refusal) else None


def _conflict(register: Path | None) -> str | None:
    copies = () if register is None else onedrive_conflicts.beside(register)
    return conflict_note(copies[0]) if copies else None


def _view(
    shown: ShownResult | None, kept: frozenset[Kept], today: date, reminders: ShownReminders, addresses: WorkerAddresses
) -> report_entering_contract.ReportsView:
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
    held = _held(shown)
    placed: defaultdict[tuple[str, date], list[_Placed]] = defaultdict(list)
    for problem in problems:
        if problem.worker is None:
            continue
        place = problem.worker, problem.day
        faulty = problem.faulty_subject
        offers = held.get((faulty.mail, problem.worker), ()) if faulty is not None and faulty.mail is not None else ()
        placed[place].append(_Placed(problem, offers))
        for holder in sorted({(found.worker, found.day) for found in offers} - {place}):
            placed[holder].append(_Placed(problem, tuple(found for found in offers if (found.worker, found.day) == holder)))
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
            report_entering_contract.UnknownReportSender(
                day=problem.day, sender=problem.sender, reason=problem.reason, worker=_assigned(problem.sender, addresses)
            )
            for problem in problems
            if problem.worker is None and problem.sender is not None
        ],
        reminders_without_footer=reminders.without_footer,
    )


@dataclass(frozen=True)
class _Held:
    worker: str
    day: date
    offer: Offer


@dataclass(frozen=True)
class _Placed:
    problem: ShownProblem
    offers: tuple[_Held, ...]


def _held(shown: ShownResult) -> dict[tuple[str, str], tuple[_Held, ...]]:
    held: defaultdict[tuple[str, str], list[_Held]] = defaultdict(list)
    for worker in shown.workers:
        for order in worker.orders_detail or ():
            if (offer := order.request) is not None:
                held[offer.mail.digest, offer.worker].append(_Held(worker.worker, worker.day, offer))
    return {mail: tuple(found) for mail, found in held.items()}


def _assigned(sender: str, addresses: WorkerAddresses) -> str | None:
    address = SenderAddress.of(sender)
    return None if address is None else addresses.logins.get(address)


def _days(days: set[date]) -> list[report_entering_contract.ReportsDay]:
    holidays = {found: name for year in {day.year for day in days} for found, name in public_holidays(year).items()}
    return [report_entering_contract.ReportsDay(day=day, holiday=holidays.get(day)) for day in sorted(days)]


def _worker_day(
    day: date,
    figure: ShownWorker | None,
    problems: list[_Placed],
    notes: list[ShownNote],
    detailed: bool,
    reminders: tuple[datetime, ...],
) -> report_entering_contract.ReportsWorkerDay:
    numbers = {placed.problem.number for placed in problems}
    orders = () if figure is None else figure.orders_detail
    if figure is None and not detailed:
        orders = None
    return report_entering_contract.ReportsWorkerDay(
        day=day,
        orders=0 if figure is None else figure.orders,
        entered=0 if figure is None else figure.entered,
        mails=0 if figure is None else figure.mails,
        without_report=[] if figure is None else list(figure.without_report),
        problems=[_problem(placed) for placed in problems],
        notes=[report_entering_contract.ReportsNote(number=found.number, text=found.text) for found in notes],
        mistaken_subjects=[] if figure is None else list(figure.mistaken),
        overtaken_subjects=[] if figure is None else list(figure.overtaken),
        orders_detail=None
        if orders is None
        else [
            report_entering_contract.ReportsOrder(
                number=order.number,
                successful=order.successful,
                activities=order.activities,
                state=OrderState.of(reported=order.reported, faulty=order.faulty, problem=order.number in numbers).value,
                codes=list(order.codes or ()),
                no_code=order.codes == (),
                request=None if order.request is None else _requested_cell(order.request),
            )
            for order in orders
        ],
        reminders=list(reminders),
    )


def _problem(placed: _Placed) -> report_entering_contract.ReportsProblem:
    problem = placed.problem
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
    request = None if problem.request is None else _requested_cell(problem.request)
    found = problem.faulty_subject
    faulty = (
        None
        if found is None
        else report_entering_contract.ReportsFaultySubject(
            subject=found.subject,
            fault=found.fault,
            day=found.day,
            arrived=found.arrived.astimezone(timezone.utc),
            offers=[
                report_entering_contract.ReportsFaultyOffer(
                    worker=held.worker, day=held.day, request=_requested_cell(held.offer)
                )
                for held in placed.offers
            ],
        )
    )
    return report_entering_contract.ReportsProblem(
        reason=problem.reason, number=problem.number, keep=keep, request=request, faulty_subject=faulty
    )


def _requested_cell(offer: Offer) -> report_entering_contract.RequestedCell:
    return report_entering_contract.RequestedCell(
        mail=offer.mail.digest,
        number=offer.number,
        day=offer.day,
        worker=offer.worker,
        activities=offer.activities,
        successful=offer.verdict.value,
        order_day=offer.order_day,
    )


def conflict_note(copy: Path) -> str:
    return f"Obok INTERMAX leży kopia konfliktu OneDrive {copy.name}. {CONFLICT_ACTION} Potem odśwież kartę."


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

    @router.post("/request", operation_id="enterOnRequest", responses={**NOT_FOUND_OR_CONFLICT, **_UNREADABLE})
    def on_request(cell: report_entering_contract.RequestedCell) -> runs_contract.RunView:
        return host.start(entry.on_request(cell))

    return router
