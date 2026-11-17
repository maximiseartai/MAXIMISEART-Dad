"""Wysyłka rozliczeń (ADR 0040): Mail z rozliczeniem, czyli Rozliczenie pracownika okresu wysłane Wykonawcy ze skrzynki
raportów taty, jego temat i treść z Ustawień Centrum i stan każdego Rozliczenia pracownika w Wysyłce. Bez I/O.

Temat i treść to Ustawienia Centrum taty (``SettlementMailSettings``) z polami ``{okres}`` (dni okresu słowami, np.
„3–9 listopada 2026”) i ``{wykonawca}`` (nazwa Wykonawcy); reguły ma jedna budowa, ``SettlementMailSettings.of``.
Odpowiedź Wykonawcy ma temat Maila z rozliczeniem po ``Re:``, a port Skrzynki raportów wybiera maile, których temat
rdzeń raportów czyta jako temat Raportu wykonawcy (``reads_as_report``: pierwsze słowo ``raport`` z jedną literówką
albo bez, odpowiedź na Przypomnienie o raporcie i poprawka raportu w odpowiedzi), więc temat, którego odpowiedź port
by wybrał (``Raport 16.11.2026 …``), jest odmową. Treść kończy się stopką Przypomnień o raporcie, jednym podpisem
taty.

Pamięcią wysłanych jest folder „Wysłane” skrzynki raportów, jak dla Przypomnień o raporcie (ADR 0030): Mail z
rozliczeniem rozpoznaje się po nazwie pliku załącznika (nazwa Rozliczenia pracownika z tokenem okresu i nazwą
Wykonawcy), a nie po temacie, który zmienia tata, i tylko na adres tego Wykonawcy z Listy Wykonawców. Mail ze znakiem
Centrum wysłało Centrum, a bez niego tata sam z tej skrzynki. Stan Rozliczenia pracownika wylicza ``mailing_state``
z tych faktów, w stałej kolejności: plik bez Wykonawcy z Listy, Wykonawca bez adresu, mail z plikiem w „Wysłanych”
(wysłany, a plik zmieniony po nim), porażka ostatniej wysyłki, pusty Szablon pracownika, do wysłania.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
import unicodedata

from .settlement_period import SettlementPeriod
from .text import normalize_text
from .worker_list import Worker
from .worker_report_inbox import SentAttachment
from .worker_reports import reads_as_report

__all__ = [
    "CLOCK_MARGIN",
    "DEFAULT_SETTLEMENT_MAIL",
    "PERIOD_FIELD",
    "WORKER_FIELD",
    "ChangedAfterSending",
    "MailingState",
    "MailProblem",
    "MailProblemKind",
    "NoAddress",
    "NotListed",
    "NotSent",
    "Sent",
    "SentByHand",
    "SettlementMailSettings",
    "ToSend",
    "WithoutOrders",
    "listed_worker",
    "mail_subject",
    "mail_text",
    "mailing_state",
    "period_words",
    "resend",
    "sendable",
]

PERIOD_FIELD: Final = "{okres}"
"""Pole tematu i treści: dni okresu słowami (``period_words``)."""
WORKER_FIELD: Final = "{wykonawca}"
"""Pole tematu i treści: nazwa Wykonawcy z Listy Wykonawców."""
_FIELDS: Final = (PERIOD_FIELD, WORKER_FIELD)
_MONTHS: Final = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)
CLOCK_MARGIN: Final = timedelta(minutes=2)
"""O ile zmiana pliku (zegar komputera taty) musi być późniejsza od chwili maila w „Wysłanych” (zegar Gmaila), żeby plik
był zmieniony po wysłaniu: zegary laptopa i Gmaila różnią się o sekundy, a plik czytany tuż przed wysyłką nie jest
zmianą."""


MailProblemKind = Literal[
    "empty_subject", "subject_lines", "subject_report", "subject_unknown_field", "empty_text", "text_unknown_field"
]
"""Reguła tematu i treści, której wartość nie spełnia: pusty temat, temat w kilku liniach, temat, którego odpowiedź
``Re:`` port Skrzynki raportów wybrałby jako Raport wykonawcy, nawias klamrowy w temacie inny niż pole, pusta treść i
nawias klamrowy w treści inny niż pole."""


@dataclass(frozen=True)
class MailProblem:
    kind: MailProblemKind


@dataclass(frozen=True)
class SettlementMailSettings:
    """Temat i treść Maila z rozliczeniem z Ustawień Centrum, z polami ``{okres}`` i ``{wykonawca}``."""

    subject: str
    text: str

    @classmethod
    def of(cls, subject: str, text: str) -> SettlementMailSettings | MailProblem:
        """Jedyna budowa z regułami, w stałej kolejności: pierwsza niespełniona reguła to problem."""

        rules: Mapping[MailProblemKind, bool] = {
            "empty_subject": bool(subject.strip()),
            "subject_lines": not {"\r", "\n"} & set(subject),
            "subject_report": not reads_as_report(f"Re: {_without_fields(subject)}"),
            "subject_unknown_field": not {"{", "}"} & set(_without_fields(subject)),
            "empty_text": bool(text.strip()),
            "text_unknown_field": not {"{", "}"} & set(_without_fields(text)),
        }
        broken = next((kind for kind, holds in rules.items() if not holds), None)
        if broken is not None:
            return MailProblem(broken)
        return cls(subject.strip(), text)


def _without_fields(text: str) -> str:
    for name in _FIELDS:
        text = text.replace(name, "")
    return text


DEFAULT_SETTLEMENT_MAIL: Final = SettlementMailSettings(
    f"Rozliczenie za {PERIOD_FIELD}", f"Dzień dobry,\nw załączniku rozliczenie za {PERIOD_FIELD}."
)
"""Temat i treść bez pliku Ustawień."""


def period_words(period: SettlementPeriod) -> str:
    """Dni okresu słowami: „3–9 listopada 2026”, przez przełom miesięcy „27 października – 2 listopada 2026”, a przez
    przełom lat „29 grudnia 2026 – 4 stycznia 2027”."""

    tuesday, monday = period.tuesday, period.monday
    end = f"{monday.day} {_MONTHS[monday.month - 1]} {monday.year}"
    if tuesday.year != monday.year:
        return f"{tuesday.day} {_MONTHS[tuesday.month - 1]} {tuesday.year} – {end}"
    if tuesday.month != monday.month:
        return f"{tuesday.day} {_MONTHS[tuesday.month - 1]} – {end}"
    return f"{tuesday.day}–{end}"


def _filled(text: str, period: SettlementPeriod, worker: str) -> str:
    return text.replace(PERIOD_FIELD, period_words(period)).replace(WORKER_FIELD, worker)


def mail_subject(settings: SettlementMailSettings, period: SettlementPeriod, worker: str) -> str:
    return _filled(settings.subject, period, worker)


def mail_text(settings: SettlementMailSettings, period: SettlementPeriod, worker: str, footer: str) -> str:
    """Treść Maila z rozliczeniem: treść taty z polami, a na końcu stopka taty z Przypomnień o raporcie, gdy nie jest
    pusta."""

    lines = [_filled(settings.text, period, worker).rstrip("\r\n")]
    if footer.strip():
        lines += ["", footer.strip("\r\n")]
    return "\n".join(lines) + "\n"


def listed_worker(name: str, workers: Sequence[Worker]) -> Worker | None:
    """Wykonawca z Listy Wykonawców, którego nazwa daje plik o nazwie ``name`` (``normalize_text``, jak nazwa pliku
    Rozliczenia pracownika w ``WorkerList.of``); ``None``: żaden."""

    wanted = normalize_text(name)
    return next((worker for worker in workers if normalize_text(worker.name) == wanted), None)


@dataclass(frozen=True)
class ToSend:
    """Rozliczenie pracownika jeszcze nie poszło do Wykonawcy."""


@dataclass(frozen=True)
class Sent:
    """Centrum wysłało Mail z rozliczeniem w chwili ``at`` i plik się od tego czasu nie zmienił."""

    at: datetime


@dataclass(frozen=True)
class SentByHand:
    """Tata wysłał ten plik Wykonawcy sam ze skrzynki raportów w chwili ``at`` i plik się od tego czasu nie zmienił."""

    at: datetime


@dataclass(frozen=True)
class ChangedAfterSending:
    """Plik zmienił się po ostatnim mailu z nim (``at``): można go wysłać jeszcze raz."""

    at: datetime


@dataclass(frozen=True)
class NoAddress:
    """Wykonawca nie ma adresu w Liście Wykonawców."""


@dataclass(frozen=True)
class WithoutOrders:
    """Rozliczenie pracownika bez Wierszy danych (pusty Szablon pracownika): nie idzie."""


@dataclass(frozen=True)
class NotListed:
    """Nazwa pliku nie odpowiada żadnemu Wykonawcy z Listy Wykonawców: nie wiadomo, do kogo go wysłać."""


@dataclass(frozen=True)
class NotSent:
    """Ostatnia próba wysyłki w tej pracy Centrum nie wyszła; ``sentence`` mówi dlaczego, bez adresu i nazwy, a ``after``
    to chwila ostatniego maila z plikiem, gdy plik zmienił się po nim (``None``: plik jeszcze nie poszedł)."""

    sentence: str
    after: datetime | None = None


def resend(state: MailingState) -> bool:
    """Czy wysyłka w stanie ``state`` jest ponowną wysyłką pliku zmienionego po ostatnim mailu z nim."""

    return isinstance(state, ChangedAfterSending) or (isinstance(state, NotSent) and state.after is not None)


def sendable(state: MailingState) -> bool:
    """Czy tata może wysłać plik w stanie ``state``: jeszcze nie poszedł, zmienił się po wysłaniu albo nie wyszedł."""

    return isinstance(state, ToSend | ChangedAfterSending | NotSent)


MailingState = ToSend | Sent | SentByHand | ChangedAfterSending | NoAddress | WithoutOrders | NotListed | NotSent
"""Stan jednego Rozliczenia pracownika w Wysyłce rozliczeń."""


def _same_file(name: str, other: str) -> bool:
    """Ta sama nazwa pliku po NFC i ``casefold``: macOS zapisuje polskie litery rozłożone (NFD), a Windows i Gmail nie
    rozróżniają wielkości liter."""

    return unicodedata.normalize("NFC", name).casefold() == unicodedata.normalize("NFC", other).casefold()


def mailing_state(
    file_name: str,
    modified_at: datetime | None,
    worker: Worker | None,
    sent: Sequence[SentAttachment],
    failure: str | None,
    has_orders: Callable[[], bool],
) -> MailingState:
    """Stan Rozliczenia pracownika ``file_name`` zmienionego w chwili ``modified_at`` (``None``: nieznanej) dla
    Wykonawcy ``worker`` (``None``: plik bez Wykonawcy z Listy), według załączników z „Wysłanych” ``sent`` i porażki
    ostatniej wysyłki ``failure``. ``has_orders`` czyta plik, więc woła się tylko o plik, który jeszcze nie poszedł."""

    if worker is None:
        return NotListed()
    if not worker.addresses:
        return NoAddress()
    addresses = frozenset(worker.addresses)
    mails = [found for found in sent if _same_file(found.name, file_name) and found.recipients & addresses]
    if mails:
        last = max(mails, key=lambda found: found.sent_at)
        if modified_at is not None and modified_at > last.sent_at + CLOCK_MARGIN:
            return NotSent(failure, last.sent_at) if failure is not None else ChangedAfterSending(last.sent_at)
        return Sent(last.sent_at) if last.by_centrum else SentByHand(last.sent_at)
    if failure is not None:
        return NotSent(failure)
    return ToSend() if has_orders() else WithoutOrders()
