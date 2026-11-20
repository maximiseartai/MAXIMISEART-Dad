from __future__ import annotations

import codecs
from dataclasses import dataclass, field, replace
from typing import Final

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import Bad, FieldPath, FieldProblem, Good, KeyChange, Read, SettingsFile, Unreadable
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE, InboxCredentials, InboxState
from rozliczenia.worker_reports import SenderAddress

ADDRESS: Final = "adres"
PASSWORD: Final = "haslo"
PASSWORD_KEY: Final = f"skrzynka.{PASSWORD}"
ACCESS_KEY: Final = "skrzynka.dostep"


@dataclass(frozen=True)
class InboxFile:
    address_line: str = ""
    password: str = field(default="", repr=False)
    rest: tuple[str, ...] = ()
    bom: bool = False
    newline: str = "\r\n"

    @property
    def address(self) -> SenderAddress | None:
        address = SenderAddress.of(self.address_line.strip())
        if address is None or address.shown() != self.address_line.strip().casefold():
            return None
        return address


def unchecked(data: bytes | None) -> InboxFile | None:
    if data is None:
        return InboxFile()
    utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    try:
        text = data.decode("utf-16" if utf16 else "utf-8-sig")
    except UnicodeError:
        return None
    lines = text.splitlines()
    address_line, password_line = (lines + ["", ""])[:2]
    return InboxFile(
        address_line,
        "".join(password_line.split()),
        tuple(lines[2:]),
        bom=not utf16 and data.startswith(codecs.BOM_UTF8),
        newline="\n" if "\n" in text and "\r\n" not in text else "\r\n",
    )


def parse(data: bytes | None) -> InboxFile | FieldProblem:
    inbox = unchecked(data)
    if inbox is None:
        return FieldProblem(None, messages.inbox_not_text())
    if not inbox.address_line.strip() or not inbox.password:
        return inbox
    if inbox.address is None:
        return FieldProblem(FieldPath(ADDRESS), messages.inbox_address())
    if not inbox.password.isascii():
        return FieldProblem(FieldPath(PASSWORD), messages.inbox_password_text())
    return inbox


def new_password(read: Read[InboxFile] | Unreadable, typed: str) -> str | FieldProblem:
    password = "".join(typed.split())
    if not password:
        return FieldProblem(FieldPath(PASSWORD), messages.inbox_password_empty())
    match read:
        case Good(value=inbox) if not inbox.address_line.strip():
            return FieldProblem(FieldPath(ADDRESS), messages.inbox_no_address())
        case _:
            return password


def with_password(inbox: InboxFile, password: str) -> InboxFile:
    return replace(inbox, password=password)


def dump(inbox: InboxFile) -> bytes:
    lines = (inbox.address_line, inbox.password, *inbox.rest)
    return (("\ufeff" if inbox.bom else "") + "".join(line + inbox.newline for line in lines)).encode("utf-8")


def diff(before: InboxFile, after: InboxFile) -> tuple[KeyChange, ...]:
    if (before.address_line, before.password, before.rest) == (after.address_line, after.password, after.rest):
        return ()
    only_password = (before.address_line, before.rest) == (after.address_line, after.rest)
    return (KeyChange(PASSWORD_KEY if only_password else ACCESS_KEY, None, None),)


def restore(inbox: InboxFile, changes: tuple[KeyChange, ...]) -> InboxFile:
    return inbox


def reported(change: KeyChange) -> str:
    return f"{change.key}: zmieniono"


def state(read: Read[InboxFile] | Unreadable) -> InboxState:
    match read:
        case Good(value=inbox):
            address = inbox.address
            if address is None or not inbox.password:
                return "missing"
            return InboxCredentials(address, inbox.password)
        case Bad() | Unreadable():
            return "unreadable"


INBOX: Final = SettingsFile(
    name=INBOX_ACCESS_FILE,
    parse=parse,
    dump=dump,
    diff=diff,
    restore=restore,
    reported=reported,
    default=InboxFile(),
    secret=True,
    unchecked=unchecked,
)
