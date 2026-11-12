"""Atrapy Skrzynki raportów taty w Gmailu: ``FakeInbox`` dla testów procesu, ``FakeMailbox`` dla pracy przypomnień
Centrum, ``FolderInbox`` dla Skryptu dla maszyn i skilli oraz ``AtrapaImap`` i ``AtrapaSmtp`` dla testu portu.

``FakeInbox`` oddaje gotowy wynik ``mails_since``, zapisuje dzień każdego wywołania i w jego trakcie robi ``during``. ``FolderInbox`` czyta maile z
plików ``.eml`` folderu tym samym rozbiorem MIME co port (``mail_of``), z chwilą przyjścia z nagłówka ``Date``. ``AtrapaImap`` to lokalny serwer
IMAP na ``127.0.0.1`` z wolnym portem, z którym prawdziwy ``imaplib`` portu (``ImapInbox``) rozmawia jak z Gmailem: te
same postacie odpowiedzi (literał ``{n}`` w FETCH, ``[READ-ONLY]`` po ``EXAMINE``, ``AUTHENTICATIONFAILED`` przy złym
haśle, folder ``\\All`` w cudzysłowie). Zapisuje polecenia klienta (``LOGIN`` bez argumentów, bo niesie hasło) i
odmawia każdego polecenia, które zmienia skrzynkę: ``SELECT``, ``STORE``, ``COPY``, ``MOVE``, ``EXPUNGE``, ``APPEND``.
Folder ``\\Sent`` („Wysłane”) ma maile ``sent``, a ``AtrapaSmtp`` to lokalny serwer SMTP, który przyjmuje maile po
``AUTH PLAIN`` (``535`` przy złym haśle, jak Gmail) i kładzie każdy przyjęty mail w „Wysłanych” swojej ``AtrapaImap`` z
chwilą z nagłówka ``Date``, jak Gmail kładzie tam mail wysłany przez SMTP.
Wierności Gmailowi atrapa nie dowodzi: prawdziwą skrzynkę sprawdza próba IMAP z #1234.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import email
import email.policy
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
import socketserver
import threading
from types import TracebackType
from typing import Final, Literal

from rozliczenia.worker_report_inbox import (
    InboxAccess,
    InboxOutcome,
    InboxUnreachable,
    MailRefused,
    Mails,
    MailSent,
    PasswordRejected,
    SentReminders,
    mail_of,
)
from rozliczenia.worker_reports import SUBJECT_WORD, Reminder, ReportMail, SentReminder

__all__ = ["AtrapaImap", "AtrapaMail", "AtrapaSmtp", "FakeInbox", "FakeMailbox", "FolderInbox"]

_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WRITES: Final = frozenset({"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"})
_HEADER_ITEMS: Final = {
    "BODY.PEEK[HEADER.FIELDS (SUBJECT)]": ("BODY[HEADER.FIELDS (SUBJECT)]", (b"subject",)),
    "BODY.PEEK[HEADER.FIELDS (SUBJECT TO)]": ("BODY[HEADER.FIELDS (SUBJECT TO)]", (b"subject", b"to")),
}
_ALL: Final = "[Gmail]/Wszystkie wiadomo&AVs-ci"
_SENT: Final = "[Gmail]/Wys&AUI-ane"
# Co tyle ``serve_forever`` sprawdza prośbę o zatrzymanie: tyle najwyżej trwa wyjście z bloku ``with``.
_POLL_S: Final = 0.02


@dataclass
class FakeInbox:
    """Skrzynka raportów testu i odtworzenia z Logów: ``outcome`` to maile albo wynik porażki, ``state`` stan pliku
    dostępu, a ``days`` dzień każdego ``mails_since``, więc pusta lista mówi, że skrzynki nikt nie czytał. ``during``
    dzieje się w trakcie każdego odczytu, jak zapis INTERMAX przez tatę, gdy proces czeka na Gmaila, a ``skipped`` to
    liczba maili, których skrzynka nie umiała przeczytać."""

    outcome: Sequence[ReportMail] | PasswordRejected | InboxUnreachable = ()
    state: InboxAccess = "ready"
    days: list[date] = field(default_factory=list)
    during: Callable[[], object] = lambda: None
    skipped: int = 0

    def access(self) -> InboxAccess:
        return self.state

    def mails_since(self, day: date) -> InboxOutcome:
        self.days.append(day)
        self.during()
        if isinstance(self.outcome, (PasswordRejected, InboxUnreachable)):
            return self.outcome
        return Mails(tuple(self.outcome), skipped=self.skipped)


@dataclass
class FakeMailbox(FakeInbox):
    """Skrzynka raportów pracy przypomnień: maile jak ``FakeInbox``, przypomnienia z „Wysłanych” (``sent`` albo wynik
    porażki) i każda wysyłka w ``sends`` (przypomnienie i chwila); ``send_outcome`` to wynik każdej wysyłki."""

    sent: Sequence[SentReminder] | PasswordRejected | InboxUnreachable = ()
    send_outcome: MailSent | PasswordRejected | InboxUnreachable | MailRefused = MailSent()
    sends: list[tuple[Reminder, datetime]] = field(default_factory=list)

    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        if isinstance(self.sent, (PasswordRejected, InboxUnreachable)):
            return self.sent
        return SentReminders(tuple(self.sent))

    def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        self.sends.append((reminder, at))
        return self.send_outcome


@dataclass(frozen=True)
class FolderInbox:
    """Skrzynka raportów z plików ``.eml`` w ``folder``, po nazwie pliku; bez folderu plik dostępu jest ``missing``.

    Jak port oddaje maile ze słowem ``SUBJECT_WORD`` w temacie z dni od dnia przed wskazanym, a mail, którego nie umie
    przeczytać (bez ``From`` z adresem albo bez ``Date``), tylko liczy. Nie łączy się z siecią.
    """

    folder: Path

    def access(self) -> InboxAccess:
        return "ready" if self.folder.is_dir() else "missing"

    def mails_since(self, day: date) -> InboxOutcome:
        if not self.folder.is_dir():
            return InboxUnreachable("missing")
        mails: list[ReportMail] = []
        skipped = 0
        for path in sorted(self.folder.glob("*.eml")):
            raw = path.read_bytes()
            message = email.message_from_bytes(raw, policy=email.policy.default)
            if SUBJECT_WORD not in str(message["Subject"] or "").casefold():
                continue
            sent = message["Date"]
            arrived = None if sent is None else sent.datetime
            mail = None if not isinstance(arrived, datetime) else mail_of(raw, arrived)
            if mail is None:
                skipped += 1
            elif mail.arrived.date() >= day - timedelta(days=1):
                mails.append(mail)
        return Mails(tuple(mails), skipped=skipped)


@dataclass(frozen=True)
class AtrapaMail:
    """Mail w atrapie: UID, chwila przyjęcia przez skrzynkę (``INTERNALDATE``, ze strefą), bajty MIME, flagi IMAP i to,
    czy leży też w ``INBOX`` (``False``: tylko w folderze ``\\All``, jak mail zarchiwizowany w Gmailu)."""

    uid: int
    arrived: datetime
    raw: bytes
    flags: tuple[str, ...] = ()
    in_inbox: bool = True


class AtrapaImap:
    """Serwer IMAP jednej skrzynki na czas bloku ``with``; ``port`` to jego port, ``commands`` polecenia klienta.

    Skrzynka ma ``INBOX`` i, gdy ``all_folder``, folder ``\\All`` z nazwą w modified UTF-7 i spacją: ``\\All`` pokazuje
    każdy mail, a ``INBOX`` maile z ``in_inbox`` (bez ``all_folder`` każdy). ``flags`` to bieżące flagi maili po UID, które
    oddaje ``UID FETCH … FLAGS``; ``marks_seen`` dopisuje ``\\Seen`` mailowi, którego treść klient pobrał, nawet przez
    ``BODY.PEEK[]``, jak serwer, który nie dotrzymuje RFC 3501, a ``deletes_read`` taki mail usuwa ze skrzynki dla
    następnych sesji, jak filtr, który przenosi przeczytane maile. ``flags_reply="without_fetch"`` odpowiada na
    ``UID FETCH … FLAGS`` samym ``OK`` bez linii ``FETCH``, a ``flags_reply="unsolicited"`` dokłada do linii z flagami
    linię ``FETCH`` z flagami bez UID, jak serwer, który ogłasza flagę zmienioną w innej sesji. ``cut="greeting"`` zrywa każde połączenie przed
    powitaniem, jak sieć, która zgubiła Gmaila, a
    ``cut="after_login"`` po udanym ``LOGIN`` czyta polecenia, ale odpowiada już tylko na ``CAPABILITY``, o które
    ``imaplib`` 3.14 pyta sam po ``LOGIN``, jak Gmail, który zamilkł w trakcie sesji: klient z limitem czasu dostaje
    wtedy ``TimeoutError``. ``refuse="login"`` odmawia ``LOGIN`` jak Gmail w chwilowej awarii (``NO [UNAVAILABLE]``, bez
    ``AUTHENTICATIONFAILED``), a ``refuse="examine"`` odmawia otwarcia folderu. ``sent`` to maile folderu ``\\Sent``
    („Wysłane”, UID inne niż maili ``mails``), którego nie ma bez ``sent_folder``.
    """

    def __init__(
        self,
        *,
        address: str,
        password: str,
        mails: Sequence[AtrapaMail] = (),
        all_folder: bool = True,
        cut: Literal["greeting", "after_login"] | None = None,
        refuse: Literal["login", "examine"] | None = None,
        marks_seen: bool = False,
        deletes_read: bool = False,
        flags_reply: Literal["without_fetch", "unsolicited"] | None = None,
        sent: Sequence[AtrapaMail] = (),
        sent_folder: bool = True,
    ) -> None:
        self.address = address
        self.password = password
        self.mails = tuple(mails)
        self.all_folder = all_folder
        self.cut = cut
        self.refuse = refuse
        self.marks_seen = marks_seen
        self.deletes_read = deletes_read
        self.flags_reply = flags_reply
        self.deleted: set[int] = set()
        self.sent = list(sent)
        self.sent_folder = sent_folder
        self.flags: dict[int, set[str]] = {mail.uid: set(mail.flags) for mail in (*self.mails, *self.sent)}
        self.commands: list[str] = []
        self._server = _Server(self)
        self._thread = threading.Thread(target=self._server.serve_forever, args=(_POLL_S,), name="atrapa-imap")

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def __enter__(self) -> AtrapaImap:
        self._thread.start()
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class _Server(socketserver.TCPServer):
    allow_reuse_address = False

    def __init__(self, atrapa: AtrapaImap) -> None:
        self.atrapa = atrapa
        super().__init__(("127.0.0.1", 0), _Session)


class _Session(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        atrapa = self.server.atrapa
        if atrapa.cut == "greeting":
            return
        self._send(b"* OK [CAPABILITY IMAP4rev1] AtrapaImap gotowa")
        self._mails: tuple[AtrapaMail, ...] = ()
        logged_in = False
        while line := self.rfile.readline():
            tag, _, rest = line.decode("utf-8").rstrip("\r\n").partition(" ")
            command, _, arguments = rest.partition(" ")
            command = command.upper()
            if command == "UID":
                inner, _, arguments = arguments.partition(" ")
                command = f"UID {inner.upper()}"
            atrapa.commands.append(command if command == "LOGIN" else f"{command} {arguments}".rstrip())
            if logged_in and atrapa.cut == "after_login" and command != "CAPABILITY":
                continue
            if not self._answer(tag, command, arguments):
                return
            logged_in = logged_in or (command == "LOGIN" and self._logs_in(arguments))

    def _answer(self, tag: str, command: str, arguments: str) -> bool:
        atrapa = self.server.atrapa
        done = f"{tag} OK {command} gotowe".encode()
        if command == "CAPABILITY":
            self._send(b"* CAPABILITY IMAP4rev1", done)
        elif command == "LOGIN":
            if atrapa.refuse == "login":
                self._send(f"{tag} NO [UNAVAILABLE] Temporary System Problem. Try again later".encode())
            elif not self._logs_in(arguments):
                self._send(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials (Failure)".encode())
            else:
                self._send(done)
        elif command == "LIST":
            folders = [b'* LIST (\\HasNoChildren) "/" "INBOX"']
            if atrapa.all_folder:
                folders.append(f'* LIST (\\All \\HasNoChildren) "/" "{_ALL}"'.encode())
            if atrapa.sent_folder:
                folders.append(f'* LIST (\\HasNoChildren \\Sent) "/" "{_SENT}"'.encode())
            self._send(*folders, done)
        elif command == "EXAMINE" and atrapa.sent_folder and _strings(arguments) == [_SENT]:
            self._mails = tuple(atrapa.sent)
            self._send(f"* {len(self._mails)} EXISTS".encode(), f"{tag} OK [READ-ONLY] EXAMINE gotowe".encode())
        elif command == "EXAMINE":
            known = atrapa.refuse != "examine" and _strings(arguments) in (["INBOX"], *([[_ALL]] if atrapa.all_folder else []))
            if known:
                self._mails = tuple(
                    mail
                    for mail in atrapa.mails
                    if mail.uid not in atrapa.deleted and (_strings(arguments) == [_ALL] or mail.in_inbox or not atrapa.all_folder)
                )
            exists = f"* {len(self._mails)} EXISTS".encode()
            self._send(*((exists, f"{tag} OK [READ-ONLY] EXAMINE gotowe".encode()) if known else (f"{tag} NO brak folderu".encode(),)))
        elif command == "UID SEARCH":
            self._send(f"* SEARCH {' '.join(str(mail.uid) for mail in _since(self._mails, arguments))}".rstrip().encode(), done)
        elif command == "UID FETCH":
            uids, _, items = arguments.partition(" ")
            for number, mail in enumerate(self._mails, start=1):
                if str(mail.uid) in uids.split(","):
                    self._fetch(number, mail, items)
            self._send(done)
        elif command == "LOGOUT":
            self._send(b"* BYE AtrapaImap", done)
            return False
        elif command.removeprefix("UID ") in _WRITES:
            self._send(f"{tag} NO [CANNOT] AtrapaImap jest tylko do odczytu".encode())
        else:
            self._send(f"{tag} BAD nieznane polecenie".encode())
        return True

    def _fetch(self, number: int, mail: AtrapaMail, items: str) -> None:
        atrapa = self.server.atrapa
        flags = atrapa.flags.setdefault(mail.uid, set())
        if items == "(UID FLAGS)":
            if atrapa.flags_reply != "without_fetch":
                self._send(f"* {number} FETCH (UID {mail.uid} FLAGS ({' '.join(sorted(flags))}))".encode())
            if atrapa.flags_reply == "unsolicited":
                self._send(f"* {number} FETCH (FLAGS ({' '.join(sorted(flags))}))".encode())
            return
        header = next((found for item, found in _HEADER_ITEMS.items() if item in items), None)
        if header is not None:
            name, literal = header[0], _header_fields(mail.raw, header[1])
        else:
            name, literal = "BODY[]", mail.raw
            if atrapa.marks_seen:
                flags.add("\\Seen")
            if atrapa.deletes_read:
                atrapa.deleted.add(mail.uid)
        moment = mail.arrived
        internal = f"{moment.day:02d}-{_MONTHS[moment.month - 1]}-{moment.year} {moment:%H:%M:%S %z}"
        head = f'* {number} FETCH (UID {mail.uid} INTERNALDATE "{internal}" {name} {{{len(literal)}}}\r\n'
        self.wfile.write(head.encode() + literal + b")\r\n")

    def _logs_in(self, arguments: str) -> bool:
        atrapa = self.server.atrapa
        return atrapa.refuse != "login" and _strings(arguments) == [atrapa.address, atrapa.password]

    def _send(self, *lines: bytes) -> None:
        self.wfile.write(b"".join(line + b"\r\n" for line in lines))


def _strings(arguments: str) -> list[str]:
    """Argumenty polecenia: napisy w cudzysłowie i atomy, jak je wysyła ``imaplib``."""

    return [
        re.sub(r"\\(.)", r"\1", quoted) if quoted or atom == "" else atom
        for quoted, atom in re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', arguments)
    ]


def _since(mails: Sequence[AtrapaMail], arguments: str) -> list[AtrapaMail]:
    """``SINCE dd-Mon-yyyy``: maile z dnia przyjęcia od tego dnia, bez godziny i strefy (RFC 3501)."""

    found = re.fullmatch(r"SINCE (\d{2})-([A-Z][a-z]{2})-(\d{4})", arguments)
    if found is None:
        return []
    day = date(int(found[3]), _MONTHS.index(found[2]) + 1, int(found[1]))
    return [mail for mail in mails if mail.arrived.date() >= day]


def _header_fields(raw: bytes, names: Sequence[bytes]) -> bytes:
    """Linie nagłówków ``names`` (małymi literami) z kontynuacjami i pusta linia, jak ``BODY[HEADER.FIELDS (…)]``."""

    header = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)[0]
    kept, inside = [], False
    for line in re.split(rb"\r?\n", header):
        inside = (line[:1] in (b" ", b"\t") and inside) or any(line.lower().startswith(name + b":") for name in names)
        if inside:
            kept.append(line + b"\r\n")
    return b"".join(kept) + b"\r\n"


class AtrapaSmtp:
    """Serwer SMTP skrzynki ``imap`` na czas bloku ``with``; ``port`` to jego port, ``commands`` polecenia klienta
    (``AUTH`` bez argumentów, bo niesie hasło), ``received`` bajty każdego przyjętego maila i jego adresaci z ``RCPT``.

    Przyjmuje ``AUTH PLAIN`` z adresem i hasłem ``imap`` (inne hasło: ``535``, jak Gmail) i kładzie każdy przyjęty mail
    w „Wysłanych” ``imap`` z chwilą z nagłówka ``Date``. ``cut="greeting"`` zrywa połączenie przed powitaniem, jak
    sieć, która zgubiła Gmaila, a ``refuse="recipients"`` odmawia każdego adresata (``550``).
    """

    def __init__(
        self,
        imap: AtrapaImap,
        *,
        cut: Literal["greeting"] | None = None,
        refuse: Literal["recipients"] | None = None,
    ) -> None:
        self.imap = imap
        self.cut = cut
        self.refuse = refuse
        self.commands: list[str] = []
        self.received: list[tuple[bytes, tuple[str, ...]]] = []
        self._server = _SmtpServer(self)
        self._thread = threading.Thread(target=self._server.serve_forever, args=(_POLL_S,), name="atrapa-smtp")

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def __enter__(self) -> AtrapaSmtp:
        self._thread.start()
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class _SmtpServer(socketserver.TCPServer):
    allow_reuse_address = False

    def __init__(self, atrapa: AtrapaSmtp) -> None:
        self.atrapa = atrapa
        super().__init__(("127.0.0.1", 0), _SmtpSession)


class _SmtpSession(socketserver.StreamRequestHandler):
    server: _SmtpServer

    def handle(self) -> None:
        atrapa = self.server.atrapa
        if atrapa.cut == "greeting":
            return
        self._reply("220 AtrapaSmtp gotowa")
        authenticated = False
        recipients: list[str] = []
        while line := self.rfile.readline():
            text = line.decode("utf-8").rstrip("\r\n")
            verb = text.split(" ", 1)[0].upper()
            atrapa.commands.append("AUTH" if verb == "AUTH" else text)
            if verb == "EHLO":
                self._reply("250-AtrapaSmtp", "250 AUTH PLAIN")
            elif verb == "AUTH":
                authenticated = self._authenticated(text)
                self._reply("235 2.7.0 Accepted" if authenticated else "535 5.7.8 Username and Password not accepted.")
            elif verb == "MAIL":
                recipients = []
                self._reply("250 2.1.0 OK" if authenticated else "530 5.7.0 Authentication Required.")
            elif verb == "RCPT" and atrapa.refuse == "recipients":
                self._reply("550 5.1.1 The email account that you tried to reach does not exist.")
            elif verb == "RCPT":
                recipients.append(text.partition(":")[2].strip().strip("<>"))
                self._reply("250 2.1.5 OK")
            elif verb == "DATA":
                self._reply("354 Go ahead")
                self._receive(tuple(recipients))
                self._reply("250 2.0.0 OK")
            elif verb == "QUIT":
                self._reply("221 2.0.0 closing connection")
                return
            elif verb in ("RSET", "NOOP"):
                self._reply("250 2.0.0 OK")
            else:
                self._reply("502 5.5.1 Unrecognized command.")

    def _authenticated(self, text: str) -> bool:
        parts = text.split(" ")
        if len(parts) != 3 or parts[1].upper() != "PLAIN":
            return False
        imap = self.server.atrapa.imap
        return base64.b64decode(parts[2]).split(b"\0")[1:] == [imap.address.encode(), imap.password.encode()]

    def _receive(self, recipients: tuple[str, ...]) -> None:
        lines = []
        while (line := self.rfile.readline()) not in (b".\r\n", b""):
            lines.append(line[1:] if line.startswith(b"..") else line)
        raw = b"".join(lines)
        atrapa = self.server.atrapa
        atrapa.received.append((raw, recipients))
        message = email.message_from_bytes(raw, policy=email.policy.default)
        imap = atrapa.imap
        uid = 1 + max((mail.uid for mail in (*imap.mails, *imap.sent)), default=1000)
        imap.sent.append(AtrapaMail(uid, parsedate_to_datetime(str(message["Date"])), raw, in_inbox=False))

    def _reply(self, *lines: str) -> None:
        self.wfile.write(b"".join(line.encode() + b"\r\n" for line in lines))
