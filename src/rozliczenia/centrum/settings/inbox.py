"""Skrzynka raportów: adres skrzynki i hasło aplikacji Google w pliku ``skrzynka-raportow.txt`` w formacie Maksa (linia 1
adres, linia 2 hasło), bez ``schema_version`` (ADR 0032, D5 projektu Ustawień).

Plik pisze Maks Notatnikiem albo PowerShellem, więc odczyt przyjmuje BOM UTF-8 i UTF-16, a spacje w haśle (Google
pokazuje je w czwórkach) pomija. Tata zmienia tylko hasło: zapis zostawia linię adresu, dalsze linie, BOM i znak końca
linii takie, jakie były, a plik UTF-16 wychodzi jako UTF-8, który odczyt przyjmuje tak samo.

Plik jest sekretem: Historia ma tylko klucz (``skrzynka.haslo`` po zmianie hasła, ``skrzynka.dostep`` po zmianie spoza
Centrum), bez wartości i bez „Cofnij”, a pamięć właściciela trzyma tylko odcisk treści (``owner``).
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from typing import Final

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import Bad, FieldPath, FieldProblem, Good, KeyChange, Read, SettingsFile, Unreadable
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE, InboxCredentials, InboxState
from rozliczenia.worker_reports import SenderAddress

ADDRESS: Final = "adres"
PASSWORD: Final = "haslo"
PASSWORD_KEY: Final = f"skrzynka.{PASSWORD}"
ACCESS_KEY: Final = "skrzynka.dostep"
"""Klucz Historii zmiany pliku spoza Centrum: co się zmieniło, nie wiadomo, bo pamięć sekretu nie trzyma treści."""


@dataclass(frozen=True)
class InboxFile:
    """Plik dostępu do skrzynki: linia adresu tak, jak ją zapisano, hasło bez spacji, dalsze linie, BOM i znak końca
    linii. Brak pliku to pusty adres i hasło."""

    address_line: str = ""
    password: str = field(default="", repr=False)
    rest: tuple[str, ...] = ()
    bom: bool = False
    newline: str = "\r\n"

    @property
    def address(self) -> SenderAddress | None:
        """Adres skrzynki, gdy linia adresu to jeden adres ``lokalna@domena`` i nic więcej."""

        address = SenderAddress.of(self.address_line.strip())
        if address is None or address.shown() != self.address_line.strip().casefold():
            return None
        return address


def unchecked(data: bytes | None) -> InboxFile | None:
    """Plik dostępu z bajtów bez reguł adresu i hasła; ``None``, gdy treść nie jest tekstem."""

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
    """Plik dostępu z bajtów; brak adresu albo hasła to dobra treść bez dostępu, a pierwszy problem złej treści ma pole."""

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
    """Hasło wpisane przez tatę bez spacji albo problem zmiany: puste hasło albo plik bez adresu (adres wpisuje Maks).
    Złą treść pliku sprawdza zapis właściciela: zaczyna od niej samej i odrzuca to, czego nowe hasło nie naprawi
    (zły adres, plik, który nie jest tekstem), a złe stare hasło zastępuje."""

    password = "".join(typed.split())
    if not password:
        return FieldProblem(FieldPath(PASSWORD), messages.inbox_password_empty())
    match read:
        case Good(value=inbox) if not inbox.address_line.strip():
            return FieldProblem(FieldPath(ADDRESS), messages.inbox_no_address())
        case _:
            return password


def dump(inbox: InboxFile) -> str:
    lines = (inbox.address_line, inbox.password, *inbox.rest)
    return ("\ufeff" if inbox.bom else "") + "".join(line + inbox.newline for line in lines)


def diff(before: InboxFile, after: InboxFile) -> tuple[KeyChange, ...]:
    if (before.address_line, before.password, before.rest) == (after.address_line, after.password, after.rest):
        return ()
    only_password = (before.address_line, before.rest) == (after.address_line, after.rest)
    return (KeyChange(PASSWORD_KEY if only_password else ACCESS_KEY, None, None),)


def restore(inbox: InboxFile, changes: tuple[KeyChange, ...]) -> InboxFile:
    """Sekretu nie da się cofnąć: wartości sprzed zmiany nikt nie zapisuje."""

    return inbox


def reported(change: KeyChange) -> str:
    """Zgłoszenie nie dostaje wartości sekretu (wiersz sekretu ma tylko klucze, więc właściciel tego nie woła)."""

    return f"{change.key}: zmieniono"


def state(read: Read[InboxFile] | Unreadable) -> InboxState:
    """Dostęp dla portu skrzynki: zła albo nieczytelna treść to ``unreadable`` (ostatniej dobrej treści sekretu właściciel
    nie pamięta), brak adresu albo hasła to ``missing``."""

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
