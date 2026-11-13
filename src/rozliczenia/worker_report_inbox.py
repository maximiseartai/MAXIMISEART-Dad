"""Skrzynka raportów: maile Wykonawców ze skrzynki raportów taty w Gmailu, przez IMAP i tylko do odczytu (ADR 0028), oraz
wysyłka Przypomnień o raporcie przez SMTP Gmaila (ADR 0030).

Port niczego w skrzynce nie zmienia: otwiera folder przez ``EXAMINE`` i pobiera maile przez ``BODY.PEEK``, więc nie
oznacza ich jako przeczytanych, i nie wysyła ``SELECT``, ``STORE``, ``COPY``, ``MOVE``, ``EXPUNGE`` ani ``APPEND``.
Oddaje maile ze słowem ``SUBJECT_WORD`` w temacie, od każdego nadawcy oprócz samej skrzynki: Raport wykonawcy od
adresu spoza pliku adresów rozpoznaje i pokazuje tacie rdzeń raportów, więc port nie filtruje po nadawcy. Mail, którego
nie umie przeczytać, pomija i tylko liczy, więc jeden zepsuty mail z zewnątrz nie zatrzymuje odczytu skrzynki. Treści
załączników nie pobiera: z serwera bierze szkielet maila (``mail_skeleton``), z którego ``mail_of`` czyta to samo co z
całego maila, a cały mail tylko wtedy, gdy szkieletu nie da się złożyć.

Adres i hasło aplikacji Google leżą w ``config/skrzynka-raportow.txt`` poza Gitem (linia 1 adres, linia 2 hasło). Plik
czyta i zmienia tylko właściciel Ustawień Centrum (``rozliczenia.centrum.settings.inbox``), a port dostaje od niego
dostęp (``InboxState``) przy każdej sesji, więc nowe hasło taty działa od następnego połączenia. Hasło nie wychodzi z
modułu: nie ma go w żadnym wyniku, ``repr`` ani wyjątku.

``ImapInbox.try_login`` to jedna próba logowania po zmianie hasła w oknie Ustawień: samo ``LOGIN`` i ``LOGOUT``, z
wynikiem przyjęte, odrzucone albo brak sieci.

Przypomnienia o raporcie (``ReminderMailbox``): ``sent_reminders`` czyta tak samo tylko do odczytu folder z atrybutem
``\\Sent`` (RFC 6154, w Gmailu „Wysłane”) i oddaje maile, których temat napisał ``reminder_subject``, z adresatami z
``To`` i chwilą przyjęcia przez Gmaila; bez takiego folderu to ``InboxUnreachable``, bo bez niego nie wiadomo, co już
poszło. ``send`` wysyła jedno przypomnienie przez ``smtp.gmail.com`` z adresu i hasła aplikacji z tego samego pliku
dostępu, a porażkę oddaje jako wynik: odrzucone hasło (``SMTPAuthenticationError``) to ``PasswordRejected``, sieć
(``OSError``, zerwane albo nienawiązane połączenie SMTP) to ``InboxUnreachable``, a każda inna odmowa serwera SMTP to
``MailRefused``; każdy wynik niesie tylko nazwę typu wyjątku.

``ImapInbox.survey`` to odczyt dla próby IMAP (``tools/proba_skrzynki_raportow.py``, #1234): flagi maili i liczby maili
ze słowem w temacie w folderze ``mails_since`` i w ``INBOX``, tą samą drogą (plik dostępu, połączenie, wybór folderu,
wyniki porażek) i tak samo tylko do odczytu, żeby próba sprawdzała port, a nie swoją kopię.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import email
from email.message import MIMEPart
from email.mime.text import MIMEText
import email.policy
from email.utils import format_datetime, getaddresses, make_msgid
import hashlib
from html.parser import HTMLParser
import imaplib
import re
import smtplib
import ssl
import time
from typing import Final, Literal, Protocol, TypeVar

from .mail_skeleton import FetchValue, Structure, UnknownReply, chosen, fetch_responses, sections, skeleton
from .worker_reports import SUBJECT_WORD, MailId, Reminder, ReportMail, SenderAddress, SentReminder, reminder_day

__all__ = [
    "FETCH_BATCH",
    "INBOX_ACCESS_FILE",
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
    "SentReminders",
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
"""Najwięcej zakresów kolejnych UID (``5:9``) w jednym ``UID FETCH``, żeby polecenie miało ograniczoną długość przy
każdej liczbie maili."""
_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_LIST_LINE: Final = re.compile(rb'\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) "(?P<name>(?:[^"\\]|\\.)*)"')
_UID: Final = re.compile(rb"\bUID (\d+)\b")
_FLAGS: Final = re.compile(rb"\bFLAGS \((?P<flags>[^)]*)\)")
_SENT_ITEMS: Final = "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT TO)])"
_LIGHT_ITEMS: Final = "(UID INTERNALDATE BODYSTRUCTURE BODY.PEEK[HEADER])"
_WHOLE_ITEMS: Final = "(UID INTERNALDATE BODY.PEEK[])"
_BODY_PREFERENCE: Final = ("plain", "html")
"""Treść maila to część ``text/plain``, a bez niej ``text/html`` (``mail_of``, ``mail_skeleton.chosen``)."""
_SMTP_NETWORK: Final = (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)
"""Porażki SMTP, które są siecią, a nie odmową serwera, jak każdy inny ``OSError``: przypomnienie poczeka na następną
próbę w tej porze. ``SMTPException`` dziedziczy po ``OSError``, więc idą przed odmową serwera."""
_T = TypeVar("_T")

InboxAccess = Literal["ready", "missing", "unreadable"]
"""Plik dostępu do skrzynki: gotowy, brak pliku albo pustej linii (``missing``), zła treść (``unreadable``)."""

LoginResult = Literal["accepted", "rejected", "no_network"]
"""Wynik jednej próby logowania: skrzynka przyjęła hasło, odrzuciła je albo nie odpowiedziała."""

ImapConnect = Callable[[], imaplib.IMAP4]
"""Połączenie z serwerem IMAP skrzynki raportów; testy i skille podają atrapę."""


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


@dataclass(frozen=True)
class SentReminders:
    """Przypomnienia o raporcie z folderu „Wysłane” z dni od dnia przed wskazanym."""

    reminders: tuple[SentReminder, ...]


@dataclass(frozen=True)
class MailSent:
    """Gmail przyjął przypomnienie do wysłania."""


@dataclass(frozen=True)
class MailRefused:
    """Serwer SMTP odmówił przypomnienia inaczej niż odrzuceniem hasła (np. adresu); ``cause`` to nazwa typu wyjątku."""

    cause: str


@dataclass(frozen=True)
class InboxSurvey:
    """Stan skrzynki z dni od dnia przed wskazanym, bez treści maili. ``searched`` to liczba maili, które w folderze
    czytanym przez ``mails_since`` dało wyszukiwanie tych dni, a ``flags`` to flagi IMAP każdego z nich po UID;
    ``in_folder`` i ``in_inbox`` to liczby maili ze słowem ``SUBJECT_WORD`` w temacie w tym folderze i w ``INBOX`` (te
    same, gdy port czyta ``INBOX``)."""

    searched: int
    flags: Mapping[str, frozenset[str]]
    in_folder: int
    in_inbox: int


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


class ReminderMailbox(WorkerReportInbox, Protocol):
    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        """Przypomnienia o raporcie z folderu „Wysłane” z dni od dnia przed ``day``; skrzynka zostaje bez zmian."""
        ...

    def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        """Wysyła przypomnienie ze skrzynki raportów do jego adresatów z datą ``at``."""
        ...


@dataclass(frozen=True)
class InboxCredentials:
    """Adres skrzynki raportów i hasło aplikacji z pliku dostępu; hasła nie ma w ``repr``."""

    address: SenderAddress
    password: str = field(repr=False)


InboxState = InboxCredentials | Literal["missing", "unreadable"]
"""Dostęp do skrzynki od właściciela Ustawień: adres i hasło albo stan pliku dostępu bez nich (``InboxAccess``)."""


class UnexpectedReply(Exception):
    """Odpowiedź serwera IMAP, której port nie zna; nie niesie jej treści."""


def _gmail() -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(GMAIL_HOST, GMAIL_PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)


def _gmail_smtp() -> smtplib.SMTP:
    return smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=TIMEOUT_S)


class ImapInbox:
    """Skrzynka raportów taty w Gmailu; ``access`` daje dostęp z pliku ``INBOX_ACCESS_FILE`` przy każdej sesji.

    ``connect`` łączy z serwerem IMAP (``None``: Gmail), a ``smtp`` z serwerem SMTP; testy podają atrapy."""

    def __init__(
        self,
        access: Callable[[], InboxState],
        *,
        connect: ImapConnect | None = None,
        smtp: Callable[[], smtplib.SMTP] = _gmail_smtp,
    ) -> None:
        self._access = access
        self._connect = connect or _gmail
        self._smtp = smtp

    def access(self) -> InboxAccess:
        found = self._access()
        return "ready" if isinstance(found, InboxCredentials) else found

    def try_login(self) -> LoginResult:
        """Jedno logowanie bez otwierania folderu: czy skrzynka przyjmuje hasło z pliku dostępu. Plik bez adresu albo
        hasła (zmieniony między zapisem a próbą) i każda porażka inna niż odrzucone hasło to brak sieci."""

        match self._session(lambda imap, access: imap.login(_quoted(access.address.shown()), access.password)):
            case PasswordRejected():
                return "rejected"
            case InboxUnreachable():
                return "no_network"
            case _:
                return "accepted"

    def mails_since(self, day: date) -> InboxOutcome:
        return self._session(lambda imap, access: _read(imap, access, day))

    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        return self._session(lambda imap, access: _sent(imap, access, day))

    def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
        found = self._access()
        if not isinstance(found, InboxCredentials):
            return InboxUnreachable(found)
        message = _reminder_message(reminder, found.address, at)
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
        """Flagi i liczby maili z dni od dnia przed ``day``, jak ``mails_since`` tylko do odczytu: ``EXAMINE`` i
        ``UID FETCH`` flag i tematów przez ``BODY.PEEK``."""

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


def _read(imap: imaplib.IMAP4, access: InboxCredentials, day: date) -> Mails:
    imap.login(_quoted(access.address.shown()), access.password)
    _ok(imap.select(_quoted(_folder(imap)), readonly=True))
    chosen = _with_subject_word(imap, _since(imap, day))
    mails, skipped = [], 0
    for prefix, raw in _mail_bytes(imap, chosen, access.address).values():
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


def _mail_bytes(imap: imaplib.IMAP4, uids: list[str], own: SenderAddress) -> dict[str, tuple[bytes, bytes]]:
    """UID → (``INTERNALDATE`` jak początek odpowiedzi FETCH, bajty maila) dla ``uids``, w ich kolejności, bez maili od
    samej skrzynki ``own`` (jej Przypomnień o raporcie), które port i tak pomija, a o nadawcy mówi już nagłówek: szkielet
    bez treści załączników (``mail_skeleton``), a cały mail (``BODY.PEEK[]``) tylko wtedy, gdy szkieletu nie da się
    złożyć albo mail nie ma ``Message-ID``, bo ``mail_of`` liczy wtedy jego ``MailId`` z bajtów całego maila.

    Najpierw ``BODYSTRUCTURE`` i nagłówek w paczkach po ``FETCH_BATCH``, potem sekcje ``mail_skeleton.sections``:
    jedno ``UID FETCH`` na paczkę maili z tą samą listą sekcji, bo Gmail odmawia całego polecenia, gdy któryś mail nie
    ma żądanej sekcji. Odmowa albo odpowiedź spoza RFC 3501 przy tych poleceniach odsyła maile do pobrania w całości."""

    light: dict[str, tuple[bytes, Structure, bytes]] = {}
    from_box: set[str] = set()
    for sequence, _ in _batches(uids):
        for response in _responses(imap.uid("FETCH", sequence, _LIGHT_ITEMS)):
            described = _described(response)
            if described is None:
                continue
            uid, internal, structure, header, sender, identified = described
            if sender == own:
                from_box.add(uid)
            elif identified:
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
    whole = _fetched(imap, [uid for uid in uids if uid not in built and uid not in from_box], _WHOLE_ITEMS)
    return {uid: mail for uid in uids if (mail := built.get(uid) or whole.get(uid)) is not None}


def _skeleton_of(structure: Structure, header: bytes, parts: Mapping[str, bytes]) -> tuple[bytes, str | None] | None:
    """Szkielet maila i sekcja części, którą wybiera ``mail_of`` (``None``: żadna); ``None``, gdy szkieletu nie da się
    złożyć albo pakiet ``email`` nie umie rozebrać nagłówka którejś części: taki mail port pobiera w całości, a tam
    ``mail_of`` liczy go jako pominięty, więc jeden zepsuty mail nie zatrzymuje odczytu skrzynki."""

    # Pakiet email zgłasza na zepsutym nagłówku różne wyjątki, zależnie od wersji Pythona (jak ``mail_of``).
    try:
        raw = skeleton(structure, header, parts)
        return None if raw is None else (raw, chosen(structure, raw, _BODY_PREFERENCE))
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: taki mail port pobiera w całości
        return None


def _fetch_sections(imap: imaplib.IMAP4, groups: Mapping[tuple[str, ...], list[str]], parts: dict[str, dict[str, bytes]]) -> None:
    """Dopisuje do ``parts`` sekcje ``BODY.PEEK[…]`` każdej grupy maili: jedno ``UID FETCH`` na paczkę maili z tą samą
    listą sekcji, bo Gmail odmawia całego polecenia, gdy któryś mail nie ma żądanej sekcji."""

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


def _described(
    response: Mapping[bytes, FetchValue],
) -> tuple[str, bytes, Structure, bytes, SenderAddress | None, bool] | None:
    """UID, ``INTERNALDATE`` jak początek odpowiedzi FETCH, ``BODYSTRUCTURE``, nagłówek maila, nadawca z ``From`` i to,
    czy nagłówek ma ``Message-ID``, z odpowiedzi; ``None``, gdy czegoś brak, kształt jest nieznany albo nagłówka nie da
    się rozebrać."""

    uid, internal, header = (response.get(name) for name in (b"UID", b"INTERNALDATE", b"BODY[HEADER]"))
    structure = Structure.of(response.get(b"BODYSTRUCTURE"))
    if not (isinstance(uid, bytes) and isinstance(internal, bytes) and isinstance(header, bytes)) or structure is None:
        return None
    facts = _header_facts(header)
    if facts is None:
        return None
    return uid.decode("ascii"), b'INTERNALDATE "' + internal + b'"', structure, header, *facts


def _batches(uids: list[str]) -> Iterator[tuple[str, list[str]]]:
    """Paczki ``uids`` po najwyżej ``FETCH_BATCH`` zakresów kolejnych UID: zbiór sekwencji IMAP (``1:5,9``) i UID
    paczki. Zakres ma tylko UID z ``uids``, więc serwer oddaje te same maile co przy wypisaniu każdego UID, a 800 maili
    z 10 dni skrzynki taty to 23 zakresy, czyli jedno polecenie zamiast ośmiu (12.11.2026)."""

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
    """Odpowiedzi ``FETCH`` polecenia, które serwer przyjął; po odmowie albo w formie spoza RFC 3501 żadnej."""

    status, data = reply
    if status != "OK":
        return []
    try:
        return fetch_responses(data)
    except UnknownReply:
        return []


def _header_facts(header: bytes) -> tuple[SenderAddress | None, bool] | None:
    """Nadawca z ``From`` tak, jak go czyta ``mail_of``, i to, czy nagłówek daje ``mail_of`` niepusty ``Message-ID``, z
    którego liczy ``MailId`` bez bajtów treści; ``None``, gdy nagłówka nie da się rozebrać (port pobiera cały mail)."""

    # Pakiet email zgłasza na zepsutym nagłówku różne wyjątki, zależnie od wersji Pythona (jak ``mail_of``).
    try:
        message = email.message_from_bytes(header, policy=email.policy.default)
        return SenderAddress.of(str(message["From"] or "")), bool(str(message["Message-ID"] or ""))
    except Exception:  # noqa: BLE001 - granica jednego maila z zewnątrz: taki mail port pobiera w całości
        return None


def _survey(imap: imaplib.IMAP4, access: InboxCredentials, day: date) -> InboxSurvey:
    imap.login(_quoted(access.address.shown()), access.password)
    folder = _folder(imap)
    _ok(imap.select(_quoted(folder), readonly=True))
    uids = _since(imap, day)
    flags = _flags(imap, uids)
    in_folder = len(_with_subject_word(imap, uids))
    if folder == "INBOX":
        return InboxSurvey(len(uids), flags, in_folder, in_folder)
    _ok(imap.select(_quoted("INBOX"), readonly=True))
    return InboxSurvey(len(uids), flags, in_folder, len(_with_subject_word(imap, _since(imap, day))))


def _since(imap: imaplib.IMAP4, day: date) -> list[str]:
    """UID maili otwartego folderu z dni od dnia przed ``day`` (``WorkerReportInbox.mails_since`` mówi dlaczego)."""

    first = day - timedelta(days=1)
    since = f"{first.day:02d}-{_MONTHS[first.month - 1]}-{first.year}"
    found = _ok(imap.uid("SEARCH", "SINCE", since))
    return [uid.decode("ascii") for line in found if isinstance(line, bytes) for uid in line.split()]


def _with_subject_word(imap: imaplib.IMAP4, uids: list[str]) -> list[str]:
    subjects = _fetched(imap, uids, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
    return [uid for uid, (_, header) in subjects.items() if SUBJECT_WORD in _subject(header).casefold()]


def _flags(imap: imaplib.IMAP4, uids: list[str]) -> dict[str, frozenset[str]]:
    """UID → flagi każdego z ``uids`` w paczkach po ``FETCH_BATCH``. Odpowiedź paczki, która nie ma flag dla któregoś
    jej UID (także ``OK`` bez żadnej linii ``FETCH``), ma linię bez UID albo flag albo flagi UID spoza paczki, to
    ``UnexpectedReply``."""

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
    """Folder Gmaila ze wszystkimi mailami (atrybut ``\\All``, RFC 6154), a bez niego ``INBOX``."""

    return _special(imap, rb"\all") or "INBOX"


def _special(imap: imaplib.IMAP4, attribute: bytes) -> str | None:
    """Folder z atrybutem ``attribute`` (małymi literami, RFC 6154); ``None``, gdy skrzynka go nie ma."""

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
    """Przypomnienie z nagłówków ``Subject`` i ``To`` maila z „Wysłanych”; ``None`` dla innego tematu, maila bez adresata
    i nagłówka, którego pakiet ``email`` nie umie rozebrać."""

    # Pakiet email zgłasza na zepsutym nagłówku różne wyjątki, zależnie od wersji Pythona (jak ``mail_of``).
    try:
        message = email.message_from_bytes(header, policy=email.policy.default)
        day = reminder_day(str(message["Subject"] or ""))
        pairs = getaddresses([str(value) for value in message.get_all("To", [])])
    except Exception:  # noqa: BLE001 - granica jednego maila z „Wysłanych”: inny mail niż przypomnienie
        return None
    recipients = frozenset(address for _, raw in pairs if (address := SenderAddress.of(raw)) is not None)
    return None if day is None or not recipients else SentReminder(recipients, day, sent_at)


def _reminder_message(reminder: Reminder, sender: SenderAddress, at: datetime) -> MIMEText:
    """Mail przypomnienia w UTF-8, z tematem po RFC 2047 (polityka SMTP pakietu ``email``)."""

    message = MIMEText(reminder.text, "plain", "utf-8", policy=email.policy.SMTP)
    message["From"] = sender.shown()
    message["To"] = ", ".join(recipient.shown() for recipient in reminder.recipients)
    message["Subject"] = reminder.subject
    message["Date"] = format_datetime(at)
    message["Message-ID"] = make_msgid(domain=sender.shown().partition("@")[2])
    return message


def _quit(smtp: smtplib.SMTP) -> None:
    """Koniec sesji SMTP bez wyjątku: po zerwanym połączeniu zamyka samo gniazdo."""

    try:
        smtp.quit()
    except (OSError, smtplib.SMTPException):
        smtp.close()


def _fetched(imap: imaplib.IMAP4, uids: list[str], items: str) -> dict[str, tuple[bytes, bytes]]:
    """UID → (początek odpowiedzi FETCH, literał) dla ``uids`` w paczkach po ``FETCH_BATCH``."""

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
    body = message.get_body(preferencelist=_BODY_PREFERENCE)
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
