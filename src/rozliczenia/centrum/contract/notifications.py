"""Kontrakt Powiadomień: sprawy taty, nowe wersje i zakończone Wyceny w efenix."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Message, Model, Sending
from rozliczenia.centrum.contract.runs import Count, Pricing


CaseKey = Literal["uwaga", "zgloszenie"]
"""Rodzaj sprawy taty: Uwaga taty albo Zgłoszenie."""


class Resolved(Model):
    """Maks zamknął issue sprawy jako ``completed`` albo bez powodu: będzie w następnej wersji."""

    state: Literal["resolved"]


class ReadByMaks(Model):
    """Maks zamknął issue sprawy jako ``not_planned`` albo duplikat: przeczytał, bez zmian."""

    state: Literal["read"]


CaseState = Annotated[Sending | Resolved | ReadByMaks, Field(discriminator="state")]
"""Stan sprawy taty (Uwagi albo Zgłoszenia) w Powiadomieniu: stan jej wysyłki (``SendState``), a po wysłaniu to, co
zrobił z nią Maks."""


class _Notification(Model):
    """Wspólne pola Powiadomienia: ``id`` sprawy w jej stanie (nowy stan to nowe Powiadomienie) albo Wydania, ``at``
    czas tego stanu (zamknięcie przez Maksa, wysłanie przez tatę, publikacja Wydania) i ``unread``, czy tata go
    jeszcze nie widział."""

    id: str
    at: datetime
    unread: bool


class DadNoteNotification(_Notification):
    """Powiadomienie o Uwadze taty, nazwanej jej tytułem."""

    kind: Literal["uwaga"]
    title: str
    state: CaseState


class ReportNotification(_Notification):
    """Powiadomienie o Zgłoszeniu, nazwanym „Co się stało” jego Komunikatu, bez kodu."""

    kind: Literal["zgloszenie"]
    what: str
    state: CaseState


class SolvedCase(Model):
    """Sprawa wysłana z tego komputera, którą Wydanie rozwiązuje: Uwaga taty nazwana tytułem, Zgłoszenie jego
    „Co się stało”."""

    kind: CaseKey
    title: str


class ReleaseNotification(_Notification):
    """Powiadomienie o nowej wersji: numer Wydania (``0.2.0``), notka „Co nowego” jako zdanie wstępu i punkty
    (``release_notes.whats_new``; notka bez punktów to sam wstęp), sprawy taty, które rozwiązuje, i czy Centrum
    proponuje Aktualizację narzędzia (``tool_freshness.offers_update``, tylko przy najnowszym Wydaniu)."""

    kind: Literal["nowa_wersja"]
    version: str
    intro: str
    points: list[str]
    solved: list[SolvedCase]
    update_offered: bool


class PricingNotification(_Notification):
    """Powiadomienie o zakończonej Wycenie w efenix, także po Zatrzymaniu: tytuł wyniku jak na karcie Uruchomienia
    (``headline``), okres, tryb (jak ``RunInfo.pricing``), liczba zleceń z każdym wynikiem pod jego nazwą, jak na karcie (``None``: Zatrzymanie przed podsumowaniem), i „Co się stało”
    Komunikatu Zatrzymania (``None`` bez Zatrzymania). ``run_id`` otwiera kartę tego Uruchomienia z jego Logów."""

    kind: Literal["wycena_w_efenix"]
    run_id: str
    headline: str
    period: str
    pricing: Pricing | None
    orders: list[Count] | None
    stopped: str | None


Notification = Annotated[
    DadNoteNotification | ReportNotification | ReleaseNotification | PricingNotification, Field(discriminator="kind")
]


class Notifications(Model):
    """Powiadomienia od najnowszego, liczba nieprzeczytanych (kropka na dzwonku) i Komunikat o pliku stanu, którego
    Centrum nie może zapisać (``None``: wszystko zapisane)."""

    unread: int
    items: list[Notification]
    message: Message | None


class NotificationsRead(Model):
    """Powiadomienia, które tata zobaczył w widoku Powiadomienia (ich ``id``)."""

    ids: Annotated[list[str], Field(max_length=1_000)]
