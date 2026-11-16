"""Wysyłka rozliczeń w Centrum (ADR 0040): strona z Rozliczeniami pracowników ostatnich okresów i stanem każdego,
podgląd Maili z rozliczeniem i wysyłka jednego maila na żądanie taty.

Odczyt strony bierze migawkę Ustawień (folder okresów, Lista Wykonawców, temat i treść, stopka Przypomnień o raporcie),
listuje Foldery rozliczeń pracowników ostatnich ``MAILING_PERIODS`` okresów, które je mają, i czyta „Wysłane” skrzynki
raportów od wtorku najstarszego z nich (``SettlementMailbox.sent_attachments``). Stan każdego pliku liczy
``settlement_mailing.mailing_state``; Szablon pracownika czyta tylko plik, który jeszcze nie poszedł, i tylko kolumnę
``WYKONAWCA`` z XML (``workbook_files.collective_workers``), z pamięcią po chwili zmiany pliku. Skrzynki, której nie da
się przeczytać, strona nie zgaduje: mówi o niej jednym zdaniem, plik do wysłania ma stan nieznany i wysyłka jest
wyłączona.

Wysyłka idzie po jednym mailu pod jedną blokadą: przed każdym mailem znowu czyta „Wysłane” od wtorku okresu, więc
plik już wysłany i niezmieniony nie idzie drugi raz (podwójne kliknięcie, ponowienie, druga karta), a zmieniony idzie
tylko z ``resend``. Maile wysłane w tej pracy Centrum pamięta też w pamięci procesu, bo Gmail kładzie mail w „Wysłanych”
z opóźnieniem; porażkę ostatniej wysyłki pliku tak samo. Nie ma pliku stanu w ``config``. Plik Wykonawcy X idzie
tylko na adresy Wykonawcy X z Listy Wykonawców, także Nieaktywnego.

Dziennik Centrum dostaje token okresu i przyczynę porażki, bez adresów, nazw Wykonawców, nazw plików, tematu i treści.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Final, assert_never
import unicodedata

from fastapi import APIRouter

from rozliczenia import workbook_files
from rozliczenia.centrum import mailing_messages, refusal
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import settlement_mailing as contract
from rozliczenia.centrum.log import SettlementMailFailure
from rozliczenia.centrum.period_board import requested_folder
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.settings.files import usable
from rozliczenia.centrum.settings.owner import CentrumSettings, SettingsSnapshot, UnreadableFile
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.dad_files import DadFiles
from rozliczenia.period_folder import PeriodFolder, WorkerSettlementFile, scan_period_folders
from rozliczenia.settlement_mailing import (
    DEFAULT_SETTLEMENT_MAIL,
    ChangedAfterSending,
    MailingState,
    NoAddress,
    NotListed,
    NotSent,
    Sent,
    SentByHand,
    SettlementMailSettings,
    ToSend,
    WithoutOrders,
    listed_worker,
    mail_subject,
    mail_text,
    mailing_state,
    period_words,
    resend,
    sendable,
)
from rozliczenia.workbook_files import Problem, WorkbookError
from rozliczenia.worker_list import Worker
from rozliczenia.worker_report_inbox import (
    AttachmentMail,
    InboxUnreachable,
    MailRefused,
    MailSent,
    PasswordRejected,
    SentAttachment,
    SentAttachments,
    SettlementMailbox,
)

MAILING_PERIODS: Final = 12
"""Ile ostatnich okresów z Rozliczeniami pracowników pokazuje strona Wysyłka rozliczeń."""

_Key = tuple[str, str]
"""Okres (token) i nazwa pliku po NFC i ``casefold``."""


def _key(token: str, name: str) -> _Key:
    return token, unicodedata.normalize("NFC", name).casefold()


@dataclass(frozen=True)
class _Inputs:
    """Ustawienia, z których liczy się strona i mail: Wykonawcy, temat i treść, stopka Przypomnień o raporcie."""

    workers: tuple[Worker, ...]
    mail: SettlementMailSettings
    footer: str


class SettlementMailing:
    """Wysyłka rozliczeń jednej pracy Centrum; ``now`` daje chwilę maila ze strefą taty."""

    def __init__(
        self,
        work: CentrumWork,
        settings: CentrumSettings,
        mailbox: SettlementMailbox,
        files: DadFiles,
        now: Callable[[], datetime],
    ) -> None:
        self._log = work.log
        self._settings = settings
        self._mailbox = mailbox
        self._files = files
        self._now = now
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._sent: dict[_Key, SentAttachment] = {}
        self._failures: dict[_Key, str] = {}
        self._orders: dict[tuple[Path, datetime | None], bool] = {}

    def view(self) -> contract.SettlementMailing:
        """Okresy z Rozliczeniami pracowników od najnowszego i stan każdego pliku."""

        snapshot = self._settings.snapshot()
        if isinstance(snapshot.folders, UnreadableFile):
            raise refusal.settings_file_unreadable(snapshot.folders.name)
        directory = snapshot.folders.periods_directory
        if directory is None:
            return contract.MailingNotSet(state="not_set", message=mailing_messages.periods_directory_not_set())
        scanned = scan_period_folders(directory)
        if scanned.periods_directory_missing:
            return contract.MailingNotSet(state="not_set", message=mailing_messages.periods_directory_missing())
        inputs = _inputs(snapshot)
        if inputs is None:
            return contract.MailingNotSet(state="not_set", message=mailing_messages.worker_list_unusable())
        periods: list[tuple[PeriodFolder, tuple[WorkerSettlementFile, ...]]] = []
        for folder in sorted(scanned.found(), key=lambda found: found.period.tuesday, reverse=True):
            entries = folder.worker_settlement_entries()
            if entries:
                periods.append((folder, entries))
            if len(periods) == MAILING_PERIODS:
                break
        sent = self._read_sent(periods[-1][0]) if periods else SentAttachments(())
        mailbox: contract.MailboxState = contract.MailboxReady(state="ready")
        if not isinstance(sent, SentAttachments):
            mailbox = contract.MailboxUnreadable(state="unreadable", message=_unreadable_sentence(sent))
        return contract.MailingReady(
            state="ready",
            mailbox=mailbox,
            periods=[
                self._period(folder, entries, inputs, sent.attachments if isinstance(sent, SentAttachments) else None)
                for folder, entries in periods
            ],
        )

    def previews(self, token: str, choice: contract.MailingChoice) -> contract.MailPreviews:
        """Maile z rozliczeniem zaznaczonych plików okresu ``token`` w kolejności zaznaczenia; plik, który nie ma
        Wykonawcy z adresem, nie ma maila."""

        folder = requested_folder(self._settings, token)
        inputs = self._usable_inputs()
        entries = folder.worker_settlement_entries()
        mails = []
        for name in choice.workers:
            entry = _entry(entries, name, token)
            worker = listed_worker(entry.worker, inputs.workers)
            if worker is not None and worker.addresses:
                mails.append(_preview(folder, entry, worker, inputs))
        return contract.MailPreviews(mails=mails)

    def send(self, token: str, request: contract.MailingSend) -> contract.MailingSent:
        """Jeden Mail z rozliczeniem; plik, którego nie można teraz wysłać, wraca z wierszem bez wysyłki."""

        folder = requested_folder(self._settings, token)
        with self._send_lock:
            inputs = self._usable_inputs()
            entry = _entry(folder.worker_settlement_entries(), request.worker, token)
            worker = listed_worker(entry.worker, inputs.workers)
            if worker is None or not worker.addresses:
                return contract.MailingSent(row=self._row(folder, entry, inputs, ()), sent_now=False)
            sent = self._read_sent(folder)
            if not isinstance(sent, SentAttachments):
                self._fail(folder, entry, "wyslane-bez-odczytu", mailing_messages.sent_unread(), _cause(sent))
                return contract.MailingSent(row=self._row(folder, entry, inputs, ()), sent_now=False)
            state = self._state(folder, entry, worker, sent.attachments)
            if not sendable(state) or (resend(state) and not request.resend):
                return contract.MailingSent(row=_row(folder, entry, worker, state), sent_now=False)
            sent_now = self._mail(folder, entry, worker, inputs)
            row = self._row(folder, entry, inputs, sent.attachments)
            return contract.MailingSent(row=row, sent_now=sent_now)

    def _mail(self, folder: PeriodFolder, entry: WorkerSettlementFile, worker: Worker, inputs: _Inputs) -> bool:
        token = folder.period.token
        try:
            content = self._files.read(entry.path, despite_excel_lock=False).content
        except WorkbookError as error:
            sentence = mailing_messages.file_open_in_excel() if error.problem is Problem.OPEN_IN_EXCEL else mailing_messages.file_unreadable()
            self._fail(folder, entry, "plik", sentence, error.problem.name)
            return False
        at = self._now()
        mail = AttachmentMail(
            worker.addresses,
            mail_subject(inputs.mail, folder.period, worker.name),
            mail_text(inputs.mail, folder.period, worker.name, inputs.footer),
            entry.path.name,
            content,
        )
        outcome = self._mailbox.send_attachment(mail, at)
        match outcome:
            case MailSent():
                with self._lock:
                    self._sent[_key(token, entry.path.name)] = SentAttachment(
                        entry.path.name, frozenset(worker.addresses), at, by_centrum=True
                    )
                    self._failures.pop(_key(token, entry.path.name), None)
                self._log.settlement_mailed(period=token)
                return True
            case PasswordRejected():
                self._fail(folder, entry, "haslo-odrzucone", mailing_messages.password_rejected())
            case InboxUnreachable(cause=cause):
                self._fail(folder, entry, "brak-sieci", mailing_messages.no_network(), cause)
            case MailRefused(cause=cause):
                self._fail(folder, entry, "odmowa-wysylki", mailing_messages.mail_refused(), cause)
            case _:
                assert_never(outcome)
        return False

    def _fail(
        self,
        folder: PeriodFolder,
        entry: WorkerSettlementFile,
        cause: SettlementMailFailure,
        sentence: str,
        failure: str | None = None,
    ) -> None:
        with self._lock:
            self._failures[_key(folder.period.token, entry.path.name)] = sentence
        self._log.settlement_mail_failed(period=folder.period.token, cause=cause, failure=failure)

    def _usable_inputs(self) -> _Inputs:
        inputs = _inputs(self._settings.snapshot())
        if inputs is None:
            raise refusal.mailing_without_workers()
        return inputs

    def _read_sent(self, oldest: PeriodFolder) -> SentAttachments | PasswordRejected | InboxUnreachable:
        if self._mailbox.access() != "ready":
            return InboxUnreachable("missing")
        return self._mailbox.sent_attachments(oldest.period.tuesday)

    def _period(
        self,
        folder: PeriodFolder,
        entries: tuple[WorkerSettlementFile, ...],
        inputs: _Inputs,
        sent: tuple[SentAttachment, ...] | None,
    ) -> contract.MailingPeriod:
        rows = [
            self._row(folder, entry, inputs, sent) if sent is not None else self._unknown_row(folder, entry, inputs)
            for entry in entries
        ]
        states = [row.state.state for row in rows]
        moments = [entry.modified_at for entry in entries if entry.modified_at is not None]
        return contract.MailingPeriod(
            token=folder.period.token,
            tuesday=folder.period.tuesday,
            monday=folder.period.monday,
            label=period_words(folder.period),
            settled_at=None if not moments else _utc(max(moments)),
            rows=rows,
            to_send=sum(state in ("to_send", "not_sent") for state in states),
            sent=sum(state in ("sent", "sent_by_hand", "changed") for state in states),
            counted=sum(state not in ("without_orders", "not_listed") for state in states),
            without_orders=states.count("without_orders"),
        )

    def _row(
        self, folder: PeriodFolder, entry: WorkerSettlementFile, inputs: _Inputs, sent: Sequence[SentAttachment]
    ) -> contract.MailingRow:
        worker = listed_worker(entry.worker, inputs.workers)
        if worker is None:
            return _row(folder, entry, None, NotListed())
        return _row(folder, entry, worker, self._state(folder, entry, worker, sent))

    def _unknown_row(self, folder: PeriodFolder, entry: WorkerSettlementFile, inputs: _Inputs) -> contract.MailingRow:
        """Wiersz bez „Wysłanych”: stan, który zależy od skrzynki, jest nieznany i nie da się go wysłać."""

        worker = listed_worker(entry.worker, inputs.workers)
        if worker is None or not worker.addresses:
            return _row(folder, entry, worker, NotListed() if worker is None else NoAddress())
        return contract.MailingRow(
            worker=entry.worker,
            file=entry.path.name,
            addresses=[address.shown() for address in worker.addresses],
            state=contract.Unknown(state="unknown"),
            sendable=False,
            preselected=False,
            resend=False,
        )

    def _state(
        self, folder: PeriodFolder, entry: WorkerSettlementFile, worker: Worker, sent: Sequence[SentAttachment]
    ) -> MailingState:
        key = _key(folder.period.token, entry.path.name)
        with self._lock:
            mine = self._sent.get(key)
            failure = self._failures.get(key)
        return mailing_state(
            entry.path.name,
            entry.modified_at,
            worker,
            (*sent, *([] if mine is None else [mine])),
            failure,
            lambda: self._has_orders(entry),
        )

    def _has_orders(self, entry: WorkerSettlementFile) -> bool:
        """Czy Rozliczenie pracownika ma Wiersze danych: Wykonawca w ``WYKONAWCA`` od pierwszego Wiersza danych. Plik,
        którego nie da się przeczytać, liczy się jako plik ze zleceniami: lepiej go pokazać, niż ukryć."""

        stamp = (entry.path, entry.modified_at)
        with self._lock:
            known = self._orders.get(stamp)
        if known is not None:
            return known
        try:
            found = bool(workbook_files.collective_workers(entry.path, self._files))
        except WorkbookError:
            return True
        if entry.modified_at is not None:
            with self._lock:
                self._orders[stamp] = found
        return found


def _inputs(snapshot: SettingsSnapshot) -> _Inputs | None:
    workers = usable(snapshot.workers)
    if workers is None:
        return None
    mail = snapshot.settlement_mail
    reminders = snapshot.reminders
    return _Inputs(
        workers.workers,
        DEFAULT_SETTLEMENT_MAIL if isinstance(mail, UnreadableFile) else mail,
        "" if isinstance(reminders, UnreadableFile) else reminders.footer,
    )


def _entry(entries: Sequence[WorkerSettlementFile], worker: str, token: str) -> WorkerSettlementFile:
    found = next((entry for entry in entries if entry.worker == worker), None)
    if found is None:
        raise refusal.worker_settlement_missing(worker, token)
    return found


def _preview(folder: PeriodFolder, entry: WorkerSettlementFile, worker: Worker, inputs: _Inputs) -> contract.MailPreview:
    return contract.MailPreview(
        worker=entry.worker,
        to=[address.shown() for address in worker.addresses],
        subject=mail_subject(inputs.mail, folder.period, worker.name),
        attachment=entry.path.name,
        text=mail_text(inputs.mail, folder.period, worker.name, inputs.footer),
    )


def _row(folder: PeriodFolder, entry: WorkerSettlementFile, worker: Worker | None, state: MailingState) -> contract.MailingRow:
    return contract.MailingRow(
        worker=entry.worker,
        file=entry.path.name,
        addresses=[] if worker is None else [address.shown() for address in worker.addresses],
        state=_shown(state),
        sendable=sendable(state),
        preselected=isinstance(state, ToSend) or (isinstance(state, NotSent) and state.after is None),
        resend=resend(state),
    )


def _shown(state: MailingState) -> contract.MailingState:
    match state:
        case ToSend():
            return contract.ToSend(state="to_send")
        case Sent(at=at):
            return contract.Sent(state="sent", at=_utc(at))
        case SentByHand(at=at):
            return contract.SentByHand(state="sent_by_hand", at=_utc(at))
        case ChangedAfterSending(at=at):
            return contract.ChangedAfterSending(state="changed", at=_utc(at))
        case NoAddress():
            return contract.NoAddress(state="no_address")
        case WithoutOrders():
            return contract.WithoutOrders(state="without_orders")
        case NotListed():
            return contract.NotListed(state="not_listed")
        case NotSent(sentence=sentence):
            return contract.NotSent(state="not_sent", message=sentence)
        case _:
            assert_never(state)


def _utc(moment: datetime) -> datetime:
    """Chwila dla przeglądarki w UTC, jak każda chwila kontraktu: przeglądarka przyjmuje tylko zapis z „Z”."""

    return moment.astimezone(timezone.utc)


def _unreadable_sentence(outcome: PasswordRejected | InboxUnreachable) -> str:
    match outcome:
        case PasswordRejected():
            return mailing_messages.mailbox_password_rejected()
        case InboxUnreachable(cause="missing" | "unreadable"):
            return mailing_messages.mailbox_without_access()
        case InboxUnreachable():
            return mailing_messages.mailbox_unreachable()


def _cause(outcome: PasswordRejected | InboxUnreachable) -> str | None:
    return outcome.cause if isinstance(outcome, InboxUnreachable) else type(outcome).__name__


def settlement_mailing_router(mailing: SettlementMailing) -> APIRouter:
    """Trasy strony Wysyłka rozliczeń: odczyt, podgląd zaznaczonych maili i wysyłka jednego."""

    router = APIRouter(prefix="/api/settlement-mailing", tags=["wysylka-rozliczen"])

    @router.get("", operation_id="getSettlementMailing", responses={409: {"model": common_contract.Problem}})
    def view() -> contract.SettlementMailing:
        return mailing.view()

    @router.post("/{token}/preview", operation_id="previewSettlementMails", responses=NOT_FOUND_OR_CONFLICT)
    def previews(token: str, choice: contract.MailingChoice) -> contract.MailPreviews:
        return mailing.previews(token, choice)

    @router.post("/{token}/send", operation_id="sendSettlementMail", responses=NOT_FOUND_OR_CONFLICT)
    def send(token: str, request: contract.MailingSend) -> contract.MailingSent:
        return mailing.send(token, request)

    return router
