from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import notifications as notifications_contract
from rozliczenia.centrum.dad_cases import NOTE, Case, DadCases
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.report_box import Closure
from rozliczenia.centrum.run_cards import LoggedRun
from rozliczenia.centrum.run_view import order_counts
from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.notification_messages import unavailable
from rozliczenia.centrum.release_notes import parse, whats_new
from rozliczenia.centrum.tool_freshness import PublishedRelease, ReleaseSource, ToolFreshness, offers_update
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.work import CentrumWork

NOTIFICATIONS_FILE: Final = "powiadomienia.json"
SCHEMA_VERSION: Final = 1
CHECK_INTERVAL_S: Final = 10 * 60
CHECK_WAIT_S: Final = 3.0
CHECK_THREAD: Final = "powiadomienia-sprawdzanie"



class ReadNotifications:
    def __init__(self, work: CentrumWork) -> None:
        self.file = StateFile(
            work.config / NOTIFICATIONS_FILE, work.log, where="stan przeczytanych Powiadomień", pause=work.pause
        )
        self._lock = threading.Lock()
        self._read = self._load()

    def __contains__(self, notification_id: str) -> bool:
        with self._lock:
            return notification_id in self._read

    def add(self, ids: Iterable[str]) -> None:
        with self._lock:
            added = set(ids) - self._read
            if not added:
                self.file.retry()
                return
            self._read |= added
            document = {"schema_version": SCHEMA_VERSION, "przeczytane": sorted(self._read)}
            self.file.write(json.dumps(document, indent=2) + "\n")

    def _load(self) -> set[str]:
        try:
            document = json.loads(self.file.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return set()
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            return set()
        ids = document.get("przeczytane")
        return {entry for entry in ids if isinstance(entry, str)} if isinstance(ids, list) else set()


@dataclass(frozen=True)
class _Releases:
    newest: Release | None = None
    offered: bool = False
    published: tuple[PublishedRelease, ...] = ()


class Notifications:
    def __init__(
        self,
        work: CentrumWork,
        cases: DadCases,
        box: KeyedBox,
        freshness: ToolFreshness,
        release: ReleaseSource,
        pricings: Callable[[], Iterable[LoggedRun]],
    ) -> None:
        self._cases = cases
        self._pricings = pricings
        self._read = ReadNotifications(work)
        self._box = box
        self._freshness = freshness
        self._release = release
        self._log = work.log
        self._clock = work.clock
        self._lock = threading.Lock()
        self._asked_at: float | None = None
        self._check: threading.Thread | None = None
        self._releases = _Releases()
        self._files = (cases.file, self._read.file)

    def view(self) -> notifications_contract.Notifications:
        for file in self._files:
            file.retry()
        check = self._start_check_if_due()
        if check is not None:
            check.join(CHECK_WAIT_S)
        return self._notifications()

    def mark_read(self, ids: Iterable[str]) -> notifications_contract.Notifications:
        self._read.add(ids)
        return self._notifications()

    def check_in_background(self) -> None:
        self._start_check_if_due()

    def _start_check_if_due(self) -> threading.Thread | None:
        with self._lock:
            now = self._clock()
            if self._asked_at is None or now - self._asked_at >= CHECK_INTERVAL_S:
                self._asked_at = now
                self._check = threading.Thread(target=self._ask, name=CHECK_THREAD, daemon=True)
                self._check.start()
            return self._check

    def _ask(self) -> None:
        self._ask_box()
        try:
            self._ask_github()
        except Exception as failure:
            self._log.unexpected_failure(failure, where="Wydania w Powiadomieniach")

    def _ask_github(self) -> None:
        answer = self._release()
        published = self._freshness.published()
        known = self._releases
        if answer is not None:
            newest = None if answer.tag is None else Release.of_tag(answer.tag)
            offered = offers_update(self._freshness.judge(lambda: answer))
            known = replace(known, newest=newest, offered=offered)
        if published is not None:
            known = replace(known, published=published)
        self._releases = known

    def _ask_box(self) -> None:
        try:
            self._cases.ask_box(self._box)
        except Exception as failure:
            self._log.unexpected_failure(failure, where="stan spraw w Powiadomieniach")

    def _notifications(self) -> notifications_contract.Notifications:
        waiting = [file.path for file in self._files if file.unavailable]
        cases = self._cases.all()
        items: list[
            notifications_contract.DadNoteNotification
            | notifications_contract.ReportNotification
            | notifications_contract.ReleaseNotification
            | notifications_contract.PricingNotification
        ] = [
            *(notification for notification in map(self._case, cases) if notification is not None),
            *self._new_versions(cases),
            *map(self._pricing, self._pricings()),
        ]
        items.sort(key=lambda item: item.at, reverse=True)
        return notifications_contract.Notifications(
            unread=sum(item.unread for item in items),
            items=items,
            message=common_contract.Message.of(unavailable(waiting)) if waiting else None,
        )

    def _new_versions(self, cases: list[Case]) -> list[notifications_contract.ReleaseNotification]:
        sent: dict[tuple[str, int | None], notifications_contract.SolvedCase] = {
            (case.kind.label, case.number): notifications_contract.SolvedCase(kind=case.kind.key, title=case.title)
            for case in cases
            if case.title is not None
        }
        known = self._releases
        newest = known.newest
        if newest is None:
            return []
        versions = []
        for published in known.published:
            release = published.release
            if release > newest:
                continue
            notes = parse(published.notes)
            shown = whats_new(notes.summary)
            notification_id = f"wydanie-{release.tag}"
            offered = known.offered and release == newest
            versions.append(
                notifications_contract.ReleaseNotification(
                    kind="nowa_wersja",
                    id=notification_id,
                    at=published.at,
                    unread=offered and notification_id not in self._read,
                    version=".".join(map(str, release.number)),
                    intro=shown.intro,
                    points=list(shown.points),
                    solved=[sent[case.label, case.number] for case in notes.cases if (case.label, case.number) in sent],
                    update_offered=offered,
                )
            )
        return versions

    def _case(self, case: Case) -> notifications_contract.DadNoteNotification | notifications_contract.ReportNotification | None:
        if case.title is None or case.sent_at is None:
            return None
        state, at = self._cases.state(case, self._box), _moment(case.closure, case.sent_at)
        if case.kind == NOTE:
            notification_id = f"uwaga-{case.id}-{_id_word(state)}"
            unread = self._unread(notification_id, state)
            return notifications_contract.DadNoteNotification(
                kind="uwaga", id=notification_id, at=at, unread=unread, title=case.title, state=state
            )
        notification_id = f"zgloszenie-{case.id if case.number is None else case.number}-{_id_word(state)}"
        unread = self._unread(notification_id, state)
        return notifications_contract.ReportNotification(
            kind="zgloszenie", id=notification_id, at=at, unread=unread, what=case.title, state=state
        )

    def _pricing(self, ended: LoggedRun) -> notifications_contract.PricingNotification:
        card = ended.card
        notification_id = f"wycena-{card.run.id}"
        orders = ended.orders
        return notifications_contract.PricingNotification(
            kind="wycena_w_efenix",
            id=notification_id,
            at=ended.ended_at,
            unread=notification_id not in self._read,
            run_id=card.run.id,
            headline=card.result.headline,
            period=card.run.period,
            pricing=card.run.pricing,
            orders=None if orders is None else order_counts(orders),
            stopped=card.result.stops[0].what if card.result.stops else None,
        )

    def _unread(self, notification_id: str, state: notifications_contract.CaseState) -> bool:
        news = isinstance(state, notifications_contract.Resolved | notifications_contract.ReadByMaks)
        return news and notification_id not in self._read


def _id_word(state: notifications_contract.CaseState) -> str:
    match state:
        case common_contract.Sent():
            return "wyslana"
        case common_contract.Queued(waits_for=waits_for):
            match waits_for:
                case "internet":
                    return "czeka_na_internet"
                case "key":
                    return "czeka_na_token"
        case common_contract.Rejected():
            return "odrzucona"
        case notifications_contract.Resolved():
            return "rozwiazana"
        case notifications_contract.ReadByMaks():
            return "przeczytana"


def _moment(closure: Closure | None, sent_at: datetime) -> datetime:
    return closure.at if closure is not None and closure.at is not None else sent_at


def notifications_router(notifications: Notifications) -> APIRouter:
    router = APIRouter(prefix="/api/notifications", tags=["powiadomienia"])

    @router.get("", operation_id="getNotifications")
    def get_notifications() -> notifications_contract.Notifications:
        return notifications.view()

    @router.post("/read", operation_id="markNotificationsRead")
    def mark_read(read: notifications_contract.NotificationsRead) -> notifications_contract.Notifications:
        return notifications.mark_read(read.ids)

    return router
