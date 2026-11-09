"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Na razie pakiet ma typy maila, które oddaje port Skrzynki raportów (``worker_report_inbox``), i adresy Wykonawców,
które buduje ``worker_addresses.load``. Rozpoznanie Raportu wykonawcy, Wpisów raportu i reguły komórek dojdą tu jako
jedna operacja rdzenia (#1227). Pakiet bierze tylko bibliotekę standardową, bo przejdzie bez zmian do Centrum w chmurze
(#1161).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
import hashlib
from typing import Final, NewType

__all__ = ["SUBJECT_WORD", "Login", "MailId", "ReportMail", "SenderAddress", "WorkerAddresses"]

SUBJECT_WORD: Final = "raport"
"""Słowo tematu Raportu wykonawcy bez względu na wielkość liter: port bierze ze skrzynki tylko maile z nim w temacie,
a rdzeń rozstrzyga resztę tematu."""

Login = NewType("Login", str)
"""Identyfikator Wykonawcy z ``WYKONAWCA`` po ``normalize_text``: klucz Konfiguracji wykonawców i pliku adresów."""

_DIGEST_LETTERS: Final = 16
_LETTERS: Final = str.maketrans("0123456789abcdef", "abcdefghijklmnop")


@dataclass(frozen=True, order=True)
class MailId:
    """Mail ze Skrzynki raportów: 16 liter a–p ze skrótu SHA-256 jego Message-ID.

    Same litery, żeby strażnik reguły danych nie wziął skrótu za numer telefonu. Sam Message-ID do rdzenia nie wchodzi.
    """

    digest: str

    @classmethod
    def of(cls, message_id: str) -> MailId:
        hexdigest = hashlib.sha256(message_id.encode("utf-8", "surrogateescape")).hexdigest()
        return cls(hexdigest[:_DIGEST_LETTERS].translate(_LETTERS))


class SenderAddress:
    """Adres nadawcy Raportu wykonawcy: addr-spec po ``casefold``.

    Nie jest ``str``, więc pole tekstowe Logów go nie przyjmie: ``str()`` i f-string zgłaszają ``TypeError``, a ``repr``
    nie pokazuje adresu. Adres daje tylko ``shown()``, które woła jedynie zapis wyniku dla widoku Raporty (ADR 0028).
    Równość i skrót idą po adresie, bo adres jest kluczem ``WorkerAddresses``.
    """

    __slots__ = ("_address",)

    def __init__(self, address: str) -> None:
        self._address = address

    @classmethod
    def of(cls, header: str) -> SenderAddress | None:
        """Adres z nagłówka ``From`` albo z linii pliku; ``None``, gdy nie ma w nim jednego adresu ``lokalna@domena``."""

        local, at, domain = parseaddr(header)[1].casefold().partition("@")
        if not (local and at and domain) or "@" in domain or any(character.isspace() for character in local + domain):
            return None
        return cls(f"{local}@{domain}")

    def shown(self) -> str:
        return self._address

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SenderAddress) and other._address == self._address

    def __hash__(self) -> int:
        return hash(self._address)

    def __repr__(self) -> str:
        return "SenderAddress(…)"

    def __str__(self) -> str:
        raise TypeError("Adres nadawcy nie jest tekstem: daje go tylko SenderAddress.shown() dla widoku Raporty.")

    def __format__(self, spec: str) -> str:
        raise TypeError("Adres nadawcy nie jest tekstem: daje go tylko SenderAddress.shown() dla widoku Raporty.")


@dataclass(frozen=True)
class ReportMail:
    """Mail ze Skrzynki raportów ze słowem ``SUBJECT_WORD`` w temacie: temat i treść jako tekst, ``arrived`` ze strefą
    taty. Od ``arrived`` zależy, który Wpis raportu jest poprawką wcześniejszego."""

    id: MailId
    sender: SenderAddress
    subject: str
    text: str
    arrived: datetime


@dataclass(frozen=True)
class WorkerAddresses:
    """Adres nadawcy → login Wykonawcy; buduje go tylko ``worker_addresses.load`` z pliku adresów Maksa."""

    logins: Mapping[SenderAddress, Login]
