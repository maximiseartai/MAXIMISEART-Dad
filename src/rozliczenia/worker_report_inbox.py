from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import email
from email.message import MIMEPart
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import email.policy
from email.utils import format_datetime, getaddresses, make_msgid
import hashlib
from html.parser import HTMLParser
import imaplib
import re
import smtplib
import ssl
import threading
import time
from typing import Final, Literal, Protocol, TypeVar

from .mail_skeleton import FetchValue, Structure, UnknownReply, attachment_sections, chosen, fetch_responses, sections, skeleton
from .worker_reports import MailId, Reminder, ReportMail, SenderAddress, SentReminder, reads_as_report, reminder_day

__all__ = [
    "CENTRUM_MARK",
    "FETCH_BATCH",
    "INBOX_ACCESS_FILE",
    "AttachmentMail",
    "ImapInbox",
    "ImapConnect",
    "InboxAccess",
    "InboxCredentials",
    "InboxOutcome",
    "InboxState",
    "InboxSurvey",
    "InboxUnreachable",
    "LoginResult",
    "MailRefused",
    "MailSent",
    "Mails",
    "PasswordRejected",
    "ReminderMailbox",
    "SentAttachment",
    "SentAttachments",
    "SentReminders",
    "SettlementMailbox",
    "SmtpConnect",
    "WorkerReportInbox",
    "mail_of",
]

INBOX_ACCESS_FILE: Final = "skrzynka-raportow.txt"
GMAIL_HOST: Final = "imap.gmail.com"
GMAIL_PORT: Final = 993
SMTP_HOST: Final = "smtp.gmail.com"
SMTP_PORT: Final = 465
TIMEOUT_S: Final = 30
FETCH_BATCH: Final = 100
_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_LIST_LINE: Final = re.compile(rb'\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) "(?P<name>(?:[^"\\]|\\.)*)"')
_UID: Final = re.compile(rb"\bUID (\d+)\b")
_FLAGS: Final = re.compile(rb"\bFLAGS \((?P<flags>[^)]*)\)")
_SENT_ITEMS: Final = "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT TO)])"
_CHOICE_ITEMS: Final = "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])"
_LIGHT_ITEMS: Final = "(UID INTERNALDATE BODYSTRUCTURE BODY.PEEK[HEADER])"
_WHOLE_ITEMS: Final = "(UID INTERNALDATE BODY.PEEK[])"
_SENT_STRUCTURE_ITEMS: Final = "(UID INTERNALDATE BODYSTRUCTURE)"
CENTRUM_MARK: Final = ("X-Centrum-Rozliczen", "wysylka-rozliczen")
_XLSX: Final = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
_BODY_PREFERENCE: Final = ("plain", "html")
_SMTP_NETWORK: Final = (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)
_T = TypeVar("_T")

InboxAccess = Literal["ready", "missing", "unreadable"]

LoginResult = Literal["accepted", "rejected", "no_network"]

ImapConnect = Callable[[], imaplib.IMAP4]

SmtpConnect = Callable[[], smtplib.SMTP]


@dataclass(frozen=True)
class Mails:
    mails: tuple[ReportMail, ...]
    skipped: int


@dataclass(frozen=True)
class PasswordRejected:
    ...


@dataclass(frozen=True)
class InboxUnreachable:
    cause: str


InboxOutcome = Mails | PasswordRejected | InboxUnreachable


@dataclass(frozen=True)
class SentReminders:
    reminders: tuple[SentReminder, ...]


@dataclass(frozen=True)
class SentAttachment:
    name: str
    recipients: frozenset[SenderAddress]
    sent_at: datetime
    by_centrum: bool


@dataclass(frozen=True)
class SentAttachments:
    attachments: tuple[SentAttachment, ...]


@dataclass(frozen=True)
class AttachmentMail:
    recipients: tuple[SenderAddress, ...]
    subject: str
    text: str
    name: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class MailSent:
    ...


@dataclass(frozen=True)
class MailRefused:
    cause: str


@dataclass(frozen=True)
class InboxSurvey:
    searched: int
    flags: Mapping[str, frozenset[str]]
    in_folder: int
    in_inbox: int


class WorkerReportInbox(Protocol):
    def access(self) -> InboxAccess:
        ...

    def mails_since(self, day: date) -> InboxOutcome:
        ...


class ReminderMailbox(WorkerReportInbox, Protocol):
    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        ...

    def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        ...


class SettlementMailbox(Protocol):
    def access(self) -> InboxAccess:
        ...

    def sent_attachments(self, day: date) -> SentAttachments | PasswordRejected | InboxUnreachable:
        ...

    def send_attachment(
        self, mail: AttachmentMail, at: datetime
    ) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        ...


@dataclass(frozen=True)
class InboxCredentials:
    address: SenderAddress
    password: str = field(repr=False)


InboxState = InboxCredentials | Literal["missing", "unreadable"]


class UnexpectedReply(Exception):
    ...


def _gmail() -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(GMAIL_HOST, GMAIL_PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)


def _gmail_smtp() -> smtplib.SMTP:
    return smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=TIMEOUT_S)


class ImapInbox:
    def __init__(
        self,
        access: Callable[[], InboxState],
        *,
        connect: ImapConnect | None = None,
        smtp: SmtpConnect = _gmail_smtp,
    ) -> None:
        self._access = access
        self._connect = connect or _gmail
        self._smtp = smtp
        self._read_mails = _ReadMails()

    def access(self) -> InboxAccess:
        found = self._access()
        return "ready" if isinstance(found, InboxCredentials) else found

    def try_login(self) -> LoginResult:
        match self._session(lambda imap, access: imap.login(_quoted(access.address.shown()), access.password)):
            case PasswordRejected():
                return "rejected"
            case InboxUnreachable():
                return "no_network"
            case _:
                return "accepted"

    def mails_since(self, day: date) -> InboxOutcome:
        return self._session(lambda imap, access: _read(imap, access, day, self._read_mails))

    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        return self._session(lambda imap, access: _sent(imap, access, day))

    def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        return self._submit(lambda sender: _reminder_message(reminder, sender, at))

    def sent_attachments(self, day: date) -> SentAttachments | PasswordRejected | InboxUnreachable:
        return self._session(lambda imap, access: _sent_attachments(imap, access, day))

    def send_attachment(self, mail: AttachmentMail, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        return self._submit(lambda sender: _attachment_message(mail, sender, at))

    def _submit(self, build: Callable[[SenderAddress], MIMEBase]) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        found = self._access()
        if not isinstance(found, InboxCredentials):
            return InboxUnreachable(found)
        message = build(found.address)
        smtp: smtplib.SMTP | None = None
        try:
            smtp = self._smtp()
            smtp.login(found.address.shown(), found.password)
            smtp.send_message(message)
        except smtplib.SMTPAuthenticationError:
            return PasswordRejected()
        except _SMTP_NETWORK as error:
            return InboxUnreachable(_cause(error))
        except smtplib.SMTPException as error:
            return MailRefused(_cause(error))
        except OSError as error:
            return InboxUnreachable(_cause(error))
        finally:
            if smtp is not None:
                _quit(smtp)
        return MailSent()

    def survey(self, day: date) -> InboxSurvey | PasswordRejected | InboxUnreachable:
        return self._session(lambda imap, access: _survey(imap, access, day))

    def _session(self, read: Callable[[imaplib.IMAP4, InboxCredentials], _T]) -> _T | PasswordRejected | InboxUnreachable:
        found = self._access()
        if not isinstance(found, InboxCredentials):
            return InboxUnreachable(found)
        try:
            imap = self._connect()
        except (OSError, imaplib.IMAP4.error) as error:
            return InboxUnreachable(_cause(error))
        try:
            return read(imap, found)
        except imaplib.IMAP4.abort as error:
            return InboxUnreachable(_cause(error))
        except imaplib.IMAP4.error as error:
            if b"AUTHENTICATIONFAILED" in str(error).encode():
                return PasswordRejected()
            return InboxUnreachable(_cause(error))
        except (OSError, UnexpectedReply) as error:
            return InboxUnreachable(_cause(error))
        finally:
            _close(imap)


def _cause(error: BaseException) -> str:
    return type(error).__qualname__


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ok(reply: tuple[str, Sequence[object]]) -> Sequence[object]:
    status, data = reply
    if status != "OK":
        raise UnexpectedReply
    return data


# ZEWNĘTRZNE: UID przy tym samym UIDVALIDITY wskazuje w folderze zawsze ten sam mail, a treści maila IMAP nie zmienia (RFC 3501 §2.3.1.1)
@dataclass(frozen=True)
class _Folder:
    address: SenderAddress
    name: str
    validity: bytes


_NOT_REPORT: Final = "not_report"
_SKIPPED: Final = "skipped"
_MailRead = ReportMail | Literal["not_report", "skipped"]


class _ReadMails:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._folder: _Folder | None = None
        self._read: dict[str, _MailRead] = {}

    def known(self, folder: _Folder | None) -> dict[str, _MailRead]:
        with self._lock:
            return dict(self._read) if folder is not None and folder == self._folder else {}

    def keep(self, folder: _Folder | None, read: dict[str, _MailRead]) -> None:
        if folder is None:
            return
        with self._lock:
            self._folder, self._read = folder, read


def _read(imap: imaplib.IMAP4, access: InboxCredentials, day: date, memo: _ReadMails) -> Mails:
    imap.login(_quoted(access.address.shown()), access.password)
    name = _folder(imap)
    _ok(imap.select(_quoted(name), readonly=True))
    folder = _opened(imap, access.address, name)
    uids = _since(imap, day)
    read = memo.known(folder)
    unknown = [uid for uid in uids if uid not in read]
    choices = _choices(imap, unknown, access.address)
    fetched = _mail_bytes(imap, [uid for uid in unknown if choices.get(uid)])
    for uid in unknown:
        if choices.get(uid) is False:
            read[uid] = _NOT_REPORT
        elif uid in fetched:
            prefix, raw = fetched[uid]
            read[uid] = mail_of(raw, _arrived(prefix)) or _SKIPPED
    current = {uid: read[uid] for uid in uids if uid in read}
    memo.keep(folder, current)
    mails = tuple(mail for mail in current.values() if isinstance(mail, ReportMail))
    return Mails(mails, sum(1 for mail in current.values() if mail == _SKIPPED))


def _opened(imap: imaplib.IMAP4, address: SenderAddress, name: str) -> _Folder | None:
    _, data = imap.response("UIDVALIDITY")
    validity = data[0] if data and isinstance(data[0], bytes) else None
    return None if validity is None else _Folder(address, name, validity)


def _arrived(prefix: bytes) -> datetime:
    moment = imaplib.Internaldate2tuple(prefix)
    if moment is None:
        raise UnexpectedReply
    return datetime.fromtimestamp(time.mktime(moment), tz=timezone.utc).astimezone()


def _choices(imap: imaplib.IMAP4, uids: list[str], own: SenderAddress) -> dict[str, bool]:
    return {uid: _reads(header, own) for uid, (_, header) in _fetched(imap, uids, _CHOICE_ITEMS).items()}


def _reads(header: bytes, own: SenderAddress) -> bool:
    try:
        message = email.message_from_bytes(header, policy=email.policy.default)
        subject, sender = str(message["Subject"] or ""), SenderAddress.of(str(message["From"] or ""))
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: nagłówek nie do rozebrania, więc mail_of rozstrzyga
        return True
    return bool(message.defects) or (reads_as_report(subject) and sender != own)


def _mail_bytes(imap: imaplib.IMAP4, uids: list[str]) -> dict[str, tuple[bytes, bytes]]:
    light: dict[str, tuple[bytes, Structure, bytes]] = {}
    for sequence, _ in _batches(uids):
        for response in _responses(imap.uid("FETCH", sequence, _LIGHT_ITEMS)):
            described = _described(response)
            if described is None:
                continue
            uid, internal, structure, header, identified = described
            if identified:
                light[uid] = (internal, structure, header)
    groups: dict[tuple[str, ...], list[str]] = {}
    for uid, (_, structure, _) in light.items():
        groups.setdefault(sections(structure), []).append(uid)
    parts: dict[str, dict[str, bytes]] = {uid: {} for uid in light}
    _fetch_sections(imap, groups, parts)
    missing: dict[tuple[str, ...], list[str]] = {}
    for uid, (_, structure, header) in light.items():
        found = _skeleton_of(structure, header, parts[uid])
        if found is not None and found[1] is not None and found[1] not in parts[uid]:
            missing.setdefault((found[1],), []).append(uid)
    _fetch_sections(imap, missing, parts)
    built: dict[str, tuple[bytes, bytes]] = {}
    for uid, (internal, structure, header) in light.items():
        found = _skeleton_of(structure, header, parts[uid])
        if found is not None and (found[1] is None or found[1] in parts[uid]):
            built[uid] = (internal, found[0])
    whole = _fetched(imap, [uid for uid in uids if uid not in built], _WHOLE_ITEMS)
    return {uid: mail for uid in uids if (mail := built.get(uid) or whole.get(uid)) is not None}


def _skeleton_of(structure: Structure, header: bytes, parts: Mapping[str, bytes]) -> tuple[bytes, str | None] | None:
    try:
        raw = skeleton(structure, header, parts)
        return None if raw is None else (raw, chosen(structure, raw, _BODY_PREFERENCE))
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: taki mail port pobiera w całości
        return None


def _fetch_sections(imap: imaplib.IMAP4, groups: Mapping[tuple[str, ...], list[str]], parts: dict[str, dict[str, bytes]]) -> None:
    for names, members in groups.items():
        items = "(UID " + " ".join(f"BODY.PEEK[{name}]" for name in names) + ")"
        for sequence, _ in _batches(members) if names else ():
            for response in _responses(imap.uid("FETCH", sequence, items)):
                number = response.get(b"UID")
                taken = parts.get(number.decode("ascii")) if isinstance(number, bytes) else None
                for name in names if taken is not None else ():
                    value = response.get(f"BODY[{name}]".encode("ascii"))
                    if taken is not None and isinstance(value, bytes):
                        taken[name] = value


def _described(response: Mapping[bytes, FetchValue]) -> tuple[str, bytes, Structure, bytes, bool] | None:
    uid, internal, header = (response.get(name) for name in (b"UID", b"INTERNALDATE", b"BODY[HEADER]"))
    structure = Structure.of(response.get(b"BODYSTRUCTURE"))
    if not (isinstance(uid, bytes) and isinstance(internal, bytes) and isinstance(header, bytes)) or structure is None:
        return None
    identified = _identified(header)
    if identified is None:
        return None
    return uid.decode("ascii"), b'INTERNALDATE "' + internal + b'"', structure, header, identified


def _batches(uids: list[str]) -> Iterator[tuple[str, list[str]]]:
    runs: list[list[int]] = []
    for uid in uids:
        number = int(uid)
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    for start in range(0, len(runs), FETCH_BATCH):
        chunk = runs[start : start + FETCH_BATCH]
        sequence = ",".join(f"{run[0]}:{run[-1]}" if len(run) > 1 else str(run[0]) for run in chunk)
        yield sequence, [str(number) for run in chunk for number in run]


def _responses(reply: tuple[str, Sequence[object]]) -> list[dict[bytes, FetchValue]]:
    status, data = reply
    if status != "OK":
        return []
    try:
        return fetch_responses(data)
    except UnknownReply:
        return []


def _identified(header: bytes) -> bool | None:
    try:
        message = email.message_from_bytes(header, policy=email.policy.default)
        return bool(str(message["Message-ID"] or ""))
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: taki mail port pobiera w całości
        return None


def _survey(imap: imaplib.IMAP4, access: InboxCredentials, day: date) -> InboxSurvey:
    imap.login(_quoted(access.address.shown()), access.password)
    folder = _folder(imap)
    _ok(imap.select(_quoted(folder), readonly=True))
    uids = _since(imap, day)
    flags = _flags(imap, uids)
    in_folder = sum(_choices(imap, uids, access.address).values())
    if folder == "INBOX":
        return InboxSurvey(len(uids), flags, in_folder, in_folder)
    _ok(imap.select(_quoted("INBOX"), readonly=True))
    return InboxSurvey(len(uids), flags, in_folder, sum(_choices(imap, _since(imap, day), access.address).values()))


def _since(imap: imaplib.IMAP4, day: date) -> list[str]:
    # ZEWNĘTRZNE: SEARCH SINCE porównuje sam dzień daty przyjęcia maila bez godziny i strefy, więc w strefie serwera, a nie taty (RFC 3501 §6.4.4)
    first = day - timedelta(days=1)
    since = f"{first.day:02d}-{_MONTHS[first.month - 1]}-{first.year}"
    found = _ok(imap.uid("SEARCH", "SINCE", since))
    return [uid.decode("ascii") for line in found if isinstance(line, bytes) for uid in line.split()]


def _flags(imap: imaplib.IMAP4, uids: list[str]) -> dict[str, frozenset[str]]:
    flags = {}
    for sequence, batch in _batches(uids):
        lines = [line for line in _ok(imap.uid("FETCH", sequence, "(UID FLAGS)")) if line is not None]
        found = {}
        for line in lines:
            uid = _UID.search(line) if isinstance(line, bytes) else None
            line_flags = _FLAGS.search(line) if isinstance(line, bytes) else None
            if uid is not None and line_flags is not None:
                found[uid[1].decode("ascii")] = frozenset(line_flags["flags"].decode("latin-1").split())
        if len(found) != len(lines) or found.keys() != set(batch):
            raise UnexpectedReply
        flags.update(found)
    return flags


def _folder(imap: imaplib.IMAP4) -> str:
    return _special(imap, rb"\all") or "INBOX"


def _special(imap: imaplib.IMAP4, attribute: bytes) -> str | None:
    for line in _ok(imap.list()):
        found = _LIST_LINE.fullmatch(line) if isinstance(line, bytes) else None
        if found is not None and attribute in found["flags"].lower().split():
            return re.sub(rb"\\(.)", rb"\1", found["name"]).decode("ascii")
    return None


def _sent(imap: imaplib.IMAP4, access: InboxCredentials, day: date) -> SentReminders:
    imap.login(_quoted(access.address.shown()), access.password)
    folder = _special(imap, rb"\sent")
    if folder is None:
        raise UnexpectedReply
    _ok(imap.select(_quoted(folder), readonly=True))
    reminders = []
    for prefix, header in _fetched(imap, _since(imap, day), _SENT_ITEMS).values():
        moment = imaplib.Internaldate2tuple(prefix)
        if moment is None:
            raise UnexpectedReply
        found = _sent_reminder(header, datetime.fromtimestamp(time.mktime(moment), tz=timezone.utc).astimezone())
        if found is not None:
            reminders.append(found)
    return SentReminders(tuple(reminders))


def _sent_reminder(header: bytes, sent_at: datetime) -> SentReminder | None:
    try:
        message = email.message_from_bytes(header, policy=email.policy.default)
        day = reminder_day(str(message["Subject"] or ""))
        pairs = getaddresses([str(value) for value in message.get_all("To", [])])
    except Exception:  # noqa: BLE001 - granica jednego maila z „Wysłanych”: inny mail niż przypomnienie
        return None
    recipients = frozenset(address for _, raw in pairs if (address := SenderAddress.of(raw)) is not None)
    return None if day is None or not recipients else SentReminder(recipients, day, sent_at)


def _sent_attachments(imap: imaplib.IMAP4, access: InboxCredentials, day: date) -> SentAttachments:
    imap.login(_quoted(access.address.shown()), access.password)
    folder = _special(imap, rb"\sent")
    if folder is None:
        raise UnexpectedReply
    _ok(imap.select(_quoted(folder), readonly=True))
    described: dict[str, tuple[datetime, tuple[str, ...]]] = {}
    for sequence, _ in _batches(_since(imap, day)):
        for response in _strict(imap.uid("FETCH", sequence, _SENT_STRUCTURE_ITEMS)):
            number, internal = response.get(b"UID"), response.get(b"INTERNALDATE")
            if not (isinstance(number, bytes) and isinstance(internal, bytes)):
                raise UnexpectedReply
            structure = Structure.of(response.get(b"BODYSTRUCTURE"))
            names = () if structure is None else attachment_sections(structure)
            if names:
                described[number.decode("ascii")] = (_internal_moment(b'INTERNALDATE "' + internal + b'"'), names)
    groups: dict[tuple[str, ...], list[str]] = {}
    for uid, (_, names) in described.items():
        groups.setdefault(("HEADER", *names), []).append(uid)
    found: dict[str, list[SentAttachment]] = {}
    for names, members in groups.items():
        items = "(UID " + " ".join(f"BODY.PEEK[{name}]" for name in names) + ")"
        for sequence, _ in _batches(members):
            for response in _strict(imap.uid("FETCH", sequence, items)):
                number = response.get(b"UID")
                uid = number.decode("ascii") if isinstance(number, bytes) else ""
                if uid not in described:
                    raise UnexpectedReply
                found[uid] = _attachments(response, names, described[uid][0])
    return SentAttachments(tuple(attachment for uid in described for attachment in found.get(uid, ())))


def _strict(reply: tuple[str, Sequence[object]]) -> list[dict[bytes, FetchValue]]:
    try:
        return fetch_responses(_ok(reply))
    except UnknownReply:
        raise UnexpectedReply from None


def _internal_moment(prefix: bytes) -> datetime:
    moment = imaplib.Internaldate2tuple(prefix)
    if moment is None:
        raise UnexpectedReply
    return datetime.fromtimestamp(time.mktime(moment), tz=timezone.utc).astimezone()


_SENT_TO: Final = ("To", "Cc", "Bcc")


def _attachments(response: Mapping[bytes, FetchValue], names: tuple[str, ...], sent_at: datetime) -> list[SentAttachment]:
    header = response.get(b"BODY[HEADER]")
    parts = [response.get(f"BODY[{name}]".encode("ascii")) for name in names[1:]]
    try:
        message = email.message_from_bytes(header if isinstance(header, bytes) else b"", policy=email.policy.default)
        pairs = getaddresses([str(value) for field in _SENT_TO for value in message.get_all(field, [])])
        marked = str(message.get(CENTRUM_MARK[0]) or "").strip() == CENTRUM_MARK[1]
        file_names = [
            email.message_from_bytes(part, policy=email.policy.default).get_filename() if isinstance(part, bytes) else None
            for part in parts
        ]
    except Exception:  # noqa: BLE001 - granica jednego maila z „Wysłanych”: mail bez czytelnych załączników
        return []
    recipients = frozenset(address for _, raw in pairs if (address := SenderAddress.of(raw)) is not None)
    return [SentAttachment(name, recipients, sent_at, marked) for name in file_names if name]


def _attachment_message(mail: AttachmentMail, sender: SenderAddress, at: datetime) -> MIMEMultipart:
    message = MIMEMultipart(policy=email.policy.SMTP)
    message["From"] = sender.shown()
    message["To"] = ", ".join(recipient.shown() for recipient in mail.recipients)
    message["Subject"] = mail.subject
    message["Date"] = format_datetime(at)
    message["Message-ID"] = make_msgid(domain=sender.shown().partition("@")[2])
    message[CENTRUM_MARK[0]] = CENTRUM_MARK[1]
    message.attach(MIMEText(mail.text, "plain", "utf-8", policy=email.policy.SMTP))
    attachment = MIMEApplication(mail.content, _subtype=_XLSX[1], policy=email.policy.SMTP)
    attachment.add_header("Content-Disposition", "attachment", filename=("utf-8", "", mail.name))
    message.attach(attachment)
    return message


def _reminder_message(reminder: Reminder, sender: SenderAddress, at: datetime) -> MIMEText:
    message = MIMEText(reminder.text, "plain", "utf-8", policy=email.policy.SMTP)
    message["From"] = sender.shown()
    message["To"] = ", ".join(recipient.shown() for recipient in reminder.recipients)
    message["Subject"] = reminder.subject
    message["Date"] = format_datetime(at)
    message["Message-ID"] = make_msgid(domain=sender.shown().partition("@")[2])
    return message


def _quit(smtp: smtplib.SMTP) -> None:
    try:
        smtp.quit()
    except (OSError, smtplib.SMTPException):
        smtp.close()


def _fetched(imap: imaplib.IMAP4, uids: list[str], items: str) -> dict[str, tuple[bytes, bytes]]:
    fetched = {}
    for sequence, _ in _batches(uids):
        for part in _ok(imap.uid("FETCH", sequence, items)):
            if not isinstance(part, tuple):
                continue
            prefix, literal = part
            uid = _UID.search(prefix)
            if uid is None:
                raise UnexpectedReply
            fetched[uid[1].decode("ascii")] = (prefix, literal)
    return fetched


def _close(imap: imaplib.IMAP4) -> None:
    try:
        imap.logout()
    except (OSError, imaplib.IMAP4.error):
        with suppress(OSError):
            imap.shutdown()


def mail_of(raw: bytes, arrived: datetime) -> ReportMail | None:
    try:
        return _report_mail(raw, arrived)
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: pominięty mail liczy Mails.skipped
        return None


def _report_mail(raw: bytes, arrived: datetime) -> ReportMail | None:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    sender = SenderAddress.of(str(message["From"] or ""))
    if sender is None:
        return None
    body = message.get_body(preferencelist=_BODY_PREFERENCE)
    text = ""
    if body is not None:
        content = _decoded(body)
        text = _html_text(content) if body.get_content_subtype() == "html" else content
    message_id = str(message["Message-ID"] or "") or hashlib.sha256(raw).hexdigest()
    return ReportMail(MailId.of(message_id), sender, str(message["Subject"] or ""), text, arrived)


def _decoded(part: MIMEPart) -> str:
    payload = part.get_payload(decode=True)
    content = payload if isinstance(payload, bytes) else b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return content.decode(charset, errors="replace")
    except (LookupError, ValueError):
        return content.decode("utf-8", errors="replace")


class _HtmlText(HTMLParser):
    _BREAKS: Final = frozenset({"br", "p", "div", "tr", "li"})
    _HIDDEN: Final = frozenset({"style", "script"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._HIDDEN:
            self._hidden += 1
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._BREAKS - {"br"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(re.sub(r"\s+", " ", data))


def _html_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
