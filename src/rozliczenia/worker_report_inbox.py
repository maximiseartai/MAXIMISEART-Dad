"""Skrzynka raportów: maile Wykonawców ze skrzynki raportów taty w Gmailu, przez IMAP i tylko do odczytu (ADR 0028).

Port niczego w skrzynce nie zmienia: otwiera folder przez ``EXAMINE`` i pobiera maile przez ``BODY.PEEK``, więc nie
oznacza ich jako przeczytanych, i nie wysyła ``SELECT``, ``STORE``, ``COPY``, ``MOVE``, ``EXPUNGE`` ani ``APPEND``.
Oddaje maile ze słowem ``SUBJECT_WORD`` w temacie, od każdego nadawcy oprócz samej skrzynki: Raport wykonawcy od
adresu spoza pliku adresów rozpoznaje i pokazuje tacie rdzeń raportów, więc port nie filtruje po nadawcy. Mail, którego
nie umie przeczytać, pomija i tylko liczy, więc jeden zepsuty mail z zewnątrz nie zatrzymuje odczytu skrzynki.

Adres i hasło aplikacji Google leżą w ``config/skrzynka-raportow.txt`` poza Gitem (linia 1 adres, linia 2 hasło),
który Maks pisze Notatnikiem albo PowerShellem, więc odczyt przyjmuje BOM UTF-8 i UTF-16. Hasło nie wychodzi z modułu:
nie ma go w żadnym wyniku, ``repr`` ani wyjątku.
"""

from __future__ import annotations

import codecs
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import email
from email.message import MIMEPart
import email.policy
import hashlib
from html.parser import HTMLParser
import imaplib
from pathlib import Path
import re
import ssl
import time
from typing import Final, Literal, Protocol

from .worker_reports import SUBJECT_WORD, MailId, ReportMail, SenderAddress

__all__ = [
    "FETCH_BATCH",
    "INBOX_ACCESS_FILE",
    "ImapInbox",
    "InboxAccess",
    "InboxOutcome",
    "InboxUnreachable",
    "Mails",
    "PasswordRejected",
    "WorkerReportInbox",
    "mail_of",
]

INBOX_ACCESS_FILE: Final = "skrzynka-raportow.txt"
GMAIL_HOST: Final = "imap.gmail.com"
GMAIL_PORT: Final = 993
TIMEOUT_S: Final = 30
FETCH_BATCH: Final = 100
"""Najwięcej UID w jednym ``UID FETCH``, żeby polecenie miało ograniczoną długość przy każdej liczbie maili."""
_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_LIST_LINE: Final = re.compile(rb'\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) "(?P<name>(?:[^"\\]|\\.)*)"')
_UID: Final = re.compile(rb"\bUID (\d+)\b")

InboxAccess = Literal["ready", "missing", "unreadable"]
"""Plik dostępu do skrzynki: gotowy, brak pliku albo pustej linii (``missing``), zła treść (``unreadable``)."""


@dataclass(frozen=True)
class Mails:
    """Maile ze słowem ``SUBJECT_WORD`` w temacie z dni od dnia przed wskazanym, w kolejności skrzynki. ``skipped`` to
    liczba maili ze słowem w temacie, których port nie przeczytał (bez adresu nadawcy albo takich, których pakiet
    ``email`` nie umie rozebrać), bez ich treści, adresów i tematów."""

    mails: tuple[ReportMail, ...]
    skipped: int


@dataclass(frozen=True)
class PasswordRejected:
    """Gmail odrzucił hasło aplikacji (``AUTHENTICATIONFAILED``): naprawić może je tylko Maks."""


@dataclass(frozen=True)
class InboxUnreachable:
    """Skrzynki nie dało się przeczytać. ``cause`` to sama nazwa typu wyjątku (``OSError``, ``IMAP4.abort``…),
    ``UnexpectedReply`` dla odpowiedzi serwera, której port nie zna, albo stan pliku dostępu (``missing``,
    ``unreadable``), gdy plik zmienił się po ``access()``; nigdy tekst wyjątku."""

    cause: str


InboxOutcome = Mails | PasswordRejected | InboxUnreachable


class WorkerReportInbox(Protocol):
    def access(self) -> InboxAccess:
        """Stan pliku dostępu do skrzynki, bez sieci."""
        ...

    def mails_since(self, day: date) -> InboxOutcome:
        """Maile ze słowem ``SUBJECT_WORD`` w temacie z dni od dnia przed ``day``; skrzynka zostaje bez zmian.

        Dzień wcześniej, bo Gmail liczy ``SINCE`` po dniu przyjęcia w swojej strefie, a nie w strefie taty, a o dniu
        Raportu i tak rozstrzyga rdzeń raportów z tematu.
        """
        ...


@dataclass(frozen=True)
class _Access:
    address: SenderAddress
    password: str = field(repr=False)


class UnexpectedReply(Exception):
    """Odpowiedź serwera IMAP, której port nie zna; nie niesie jej treści."""


def _gmail() -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(GMAIL_HOST, GMAIL_PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)


class ImapInbox:
    """Skrzynka raportów taty w Gmailu; ``config_directory`` to folder ``config`` z plikiem ``INBOX_ACCESS_FILE``."""

    def __init__(self, config_directory: Path, *, connect: Callable[[], imaplib.IMAP4] = _gmail) -> None:
        self._config = config_directory
        self._connect = connect

    def access(self) -> InboxAccess:
        found = _read_access(self._config)
        return "ready" if isinstance(found, _Access) else found

    def mails_since(self, day: date) -> InboxOutcome:
        found = _read_access(self._config)
        if not isinstance(found, _Access):
            return InboxUnreachable(found)
        try:
            imap = self._connect()
        except (OSError, imaplib.IMAP4.error) as error:
            return InboxUnreachable(_cause(error))
        try:
            return _read(imap, found, day)
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


def _read_access(config_directory: Path) -> _Access | Literal["missing", "unreadable"]:
    try:
        content = (config_directory / INBOX_ACCESS_FILE).read_bytes()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return "missing"
    except OSError:
        return "unreadable"
    # Notatnik dopisuje BOM UTF-8, a ``>`` i ``Out-File`` w PowerShell 5.1 zapisują UTF-16 z BOM.
    encoding = "utf-16" if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    try:
        lines = content.decode(encoding).splitlines()
    except UnicodeError:
        return "unreadable"
    address_line, password_line = (lines + ["", ""])[:2]
    password = "".join(password_line.split())
    if not address_line.strip() or not password:
        return "missing"
    address = SenderAddress.of(address_line.strip())
    if address is None or address.shown() != address_line.strip().casefold() or not password.isascii():
        return "unreadable"
    return _Access(address, password)


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ok(reply: tuple[str, Sequence[object]]) -> Sequence[object]:
    status, data = reply
    if status != "OK":
        raise UnexpectedReply
    return data


def _read(imap: imaplib.IMAP4, access: _Access, day: date) -> Mails:
    imap.login(_quoted(access.address.shown()), access.password)
    _ok(imap.select(_quoted(_folder(imap)), readonly=True))
    first = day - timedelta(days=1)
    since = f"{first.day:02d}-{_MONTHS[first.month - 1]}-{first.year}"
    found = _ok(imap.uid("SEARCH", "SINCE", since))
    uids = [uid.decode("ascii") for line in found if isinstance(line, bytes) for uid in line.split()]
    subjects = _fetched(imap, uids, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
    chosen = [uid for uid, (_, header) in subjects.items() if SUBJECT_WORD in _subject(header).casefold()]
    mails, skipped = [], 0
    for prefix, raw in _fetched(imap, chosen, "(UID INTERNALDATE BODY.PEEK[])").values():
        moment = imaplib.Internaldate2tuple(prefix)
        if moment is None:
            raise UnexpectedReply
        arrived = datetime.fromtimestamp(time.mktime(moment), tz=timezone.utc).astimezone()
        mail = mail_of(raw, arrived)
        if mail is None:
            skipped += 1
        elif mail.sender != access.address:
            mails.append(mail)
    return Mails(tuple(mails), skipped)


def _folder(imap: imaplib.IMAP4) -> str:
    """Folder Gmaila ze wszystkimi mailami (atrybut ``\\All``, RFC 6154), a bez niego ``INBOX``."""

    for line in _ok(imap.list()):
        found = _LIST_LINE.fullmatch(line) if isinstance(line, bytes) else None
        if found is not None and rb"\all" in found["flags"].lower().split():
            return re.sub(rb"\\(.)", rb"\1", found["name"]).decode("ascii")
    return "INBOX"


def _fetched(imap: imaplib.IMAP4, uids: list[str], items: str) -> dict[str, tuple[bytes, bytes]]:
    """UID → (początek odpowiedzi FETCH, literał) dla ``uids`` w paczkach po ``FETCH_BATCH``."""

    fetched = {}
    for start in range(0, len(uids), FETCH_BATCH):
        for part in _ok(imap.uid("FETCH", ",".join(uids[start : start + FETCH_BATCH]), items)):
            if not isinstance(part, tuple):
                continue
            prefix, literal = part
            uid = _UID.search(prefix)
            if uid is None:
                raise UnexpectedReply
            fetched[uid[1].decode("ascii")] = (prefix, literal)
    return fetched


def _subject(header: bytes) -> str:
    return str(email.message_from_bytes(header, policy=email.policy.default)["Subject"] or "")


def _close(imap: imaplib.IMAP4) -> None:
    """Wylogowanie bez wyjątku: po zerwanym połączeniu zamyka samo gniazdo."""

    try:
        imap.logout()
    except (OSError, imaplib.IMAP4.error):
        with suppress(OSError):
            imap.shutdown()


def mail_of(raw: bytes, arrived: datetime) -> ReportMail | None:
    """Mail MIME jako ``ReportMail``: temat po RFC 2047, treść z ``text/plain``, a bez niego tekst z ``text/html``;
    ``None``, gdy nagłówek ``From`` nie ma adresu albo pakiet ``email`` nie umie maila rozebrać."""

    # Pakiet email zgłasza na zepsutym mailu AttributeError, IndexError, ValueError i inne, zależnie od wersji Pythona.
    try:
        return _report_mail(raw, arrived)
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: pominięty mail liczy Mails.skipped
        return None


def _report_mail(raw: bytes, arrived: datetime) -> ReportMail | None:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    sender = SenderAddress.of(str(message["From"] or ""))
    if sender is None:
        return None
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = _decoded(body)
        text = _html_text(content) if body.get_content_subtype() == "html" else content
    message_id = str(message["Message-ID"] or "") or hashlib.sha256(raw).hexdigest()
    return ReportMail(MailId.of(message_id), sender, str(message["Subject"] or ""), text, arrived)


def _decoded(part: MIMEPart) -> str:
    """Treść części po quoted-printable albo base64 w jej zestawie znaków; nieznany albo zepsuty zestaw (z bajtem
    zerowym) czyta jako UTF-8."""

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
    """Tekst strony HTML: linia na każdy ``br``, ``p``, ``div``, ``tr`` i ``li``, a nowa linia w tekście to spacja, jak
    w przeglądarce; bez pustych linii, stylów i skryptów."""

    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
