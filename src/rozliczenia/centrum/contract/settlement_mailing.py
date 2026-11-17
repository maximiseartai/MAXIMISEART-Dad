"""Kontrakt Wysyłki rozliczeń (ADR 0040): sekcja Ustawień z tematem i treścią Maila z rozliczeniem, strona z
Rozliczeniami pracowników okresów i stanem każdego w Wysyłce, podgląd maili i wysyłka jednego maila."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.settings_workers import SettingProblem


class SettlementMailForm(Model):
    """Formularz sekcji Wysyłka rozliczeń: temat i treść z polami ``{okres}`` i ``{wykonawca}``."""

    subject: str
    text: str


class SettlementMailSetting(SettlementMailForm):
    """Temat i treść: ``good``, ``bad`` (zły plik: ``problem`` i ostatnie dobre wartości, a bez nich domyślne) albo
    ``unreadable`` (system nie daje teraz czytać pliku, wartości domyślne)."""

    state: Literal["good", "bad", "unreadable"]
    problem: SettingProblem | None


class SettlementMailPreview(Model):
    """Mail z formularza dla przykładowego Wykonawcy i ostatniego pełnego okresu, ze stopką Przypomnień o raporcie. Nic
    się nie zapisuje ani nie wysyła."""

    subject: str
    text: str


class ToSend(Model):
    """Rozliczenie pracownika jeszcze nie poszło."""

    state: Literal["to_send"]


class Sent(Model):
    """Centrum wysłało je w chwili ``at`` i plik się od tego czasu nie zmienił."""

    state: Literal["sent"]
    at: datetime


class SentByHand(Model):
    """Tata wysłał ten plik sam ze skrzynki raportów w chwili ``at`` i plik się od tego czasu nie zmienił."""

    state: Literal["sent_by_hand"]
    at: datetime


class ChangedAfterSending(Model):
    """Plik zmienił się po ostatnim mailu z nim (``at``): można go wysłać jeszcze raz."""

    state: Literal["changed"]
    at: datetime


class NoAddress(Model):
    """Wykonawca nie ma adresu w Liście Wykonawców."""

    state: Literal["no_address"]


class WithoutOrders(Model):
    """Pusty Szablon pracownika: nie idzie."""

    state: Literal["without_orders"]


class NotListed(Model):
    """Nazwa pliku nie odpowiada żadnemu Wykonawcy z Listy Wykonawców: nie idzie."""

    state: Literal["not_listed"]


class NotSent(Model):
    """Ostatnia próba wysyłki nie wyszła; ``message`` mówi dlaczego."""

    state: Literal["not_sent"]
    message: str


class Unknown(Model):
    """Skrzynki raportów nie dało się przeczytać, więc nie wiadomo, czy plik już poszedł."""

    state: Literal["unknown"]


MailingState = Annotated[
    ToSend | Sent | SentByHand | ChangedAfterSending | NoAddress | WithoutOrders | NotListed | NotSent | Unknown,
    Field(discriminator="state"),
]


class MailingRow(Model):
    """Rozliczenie pracownika okresu: nazwa Wykonawcy z nazwy pliku, nazwa pliku, adresy Wykonawcy z Listy Wykonawców i
    stan. ``sendable``: tata może je wysłać, ``preselected``: zaznaczone na start (do wysłania albo po porażce), a
    ``resend``: wysyłka jest ponowną wysyłką zmienionego pliku."""

    worker: str
    file: str
    addresses: list[str]
    state: MailingState
    sendable: bool
    preselected: bool
    resend: bool


class MailingPeriod(Model):
    """Okres z Rozliczeniami pracowników: dni słowami (``label``), najnowsza zmiana jego plików i wiersze; ile poszło,
    strona liczy ze stanów wierszy, bo zmienia je po każdym mailu wysyłki."""

    token: str
    tuesday: date
    monday: date
    label: str
    settled_at: datetime | None
    rows: list[MailingRow]


class MailboxReady(Model):
    state: Literal["ready"]


class MailboxUnreadable(Model):
    """Skrzynki raportów nie da się teraz przeczytać: ``message`` mówi dlaczego jednym zdaniem; wysyłka jest wyłączona."""

    state: Literal["unreadable"]
    message: str


MailboxState = Annotated[MailboxReady | MailboxUnreadable, Field(discriminator="state")]


class MailingNotSet(Model):
    """Folder okresów nie jest wskazany albo go nie ma: ``message`` mówi, co zrobić."""

    state: Literal["not_set"]
    message: str


class MailingReady(Model):
    """Okresy z Rozliczeniami pracowników od najnowszego, najwyżej ostatnie ``MAILING_PERIODS``."""

    state: Literal["ready"]
    mailbox: MailboxState
    periods: list[MailingPeriod]


SettlementMailing = Annotated[MailingNotSet | MailingReady, Field(discriminator="state")]


class MailingChoice(Model):
    """Rozliczenia pracowników okresu, które tata zaznaczył, po nazwie Wykonawcy z nazwy pliku."""

    workers: list[str]


class MailPreview(Model):
    """Mail z rozliczeniem tak, jak go dostanie Wykonawca: adresaci, temat, nazwa pliku i treść ze stopką."""

    worker: str
    to: list[str]
    subject: str
    attachment: str
    text: str


class MailPreviews(Model):
    mails: list[MailPreview]


class MailingSend(Model):
    """Jeden Mail z rozliczeniem: Wykonawca z nazwy pliku i to, czy tata wysyła jeszcze raz zmieniony plik."""

    worker: str
    resend: bool


class MailingSent(Model):
    """Wynik wysyłki: wiersz po niej i to, czy mail poszedł teraz (``False``: już był w „Wysłanych” albo nie wyszedł)."""

    row: MailingRow
    sent_now: bool
