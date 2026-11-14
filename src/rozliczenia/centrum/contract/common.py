"""Wspólne typy kontraktu Centrum rozliczeń: Komunikat, odmowa, klucz procesu i otwarcie pliku."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from rozliczenia.message import Message as ProcessMessage, SettingsSection


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Problem(Model):
    """Odmowa wykonania żądania z bezpiecznym komunikatem dla taty, bez tekstu wyjątku; ``field``: pole formularza,
    którego dotyczy zła wartość (np. ``folder_okresow`` w Ustawieniach Centrum)."""

    message: str
    field: str | None = None


ProcessKey = Literal["preparation", "settlement", "efenix", "intermax", "report_entering"]
"""Klucz procesu, ten sam w Uruchomieniach i w Metrykach."""


PeriodProcessKey = Literal["preparation", "settlement", "efenix"]
"""Proces, którego Uruchomienie tata wybiera z okresem; Uporządkowanie INTERMAX i Wpisanie raportów mają własne karty
poza okresami."""


class Opened(Model):
    name: str


class Message(Model):
    """Komunikat w trzech częściach (Co się stało, Gdzie, Co zrobić) bez kodu; ``setting``: sekcja okna Ustawień
    Centrum, do której prowadzi link przy „Co zrobić”. Bez sekcji pola nie ma w odpowiedzi, więc Komunikat bez poprawki
    w Ustawieniach ma dalej trzy części, także w Logach Uruchomienia."""

    what: str
    where: str
    action: str
    setting: SettingsSection | None = Field(default=None, exclude_if=lambda setting: setting is None)

    @classmethod
    def of(cls, message: ProcessMessage) -> Message:
        return cls(what=message.what, where=message.where, action=message.action, setting=message.setting)


WaitsFor = Literal["internet", "key"]
"""Na co czeka wysyłka taty w Kolejce wysyłki: ``internet`` albo ``key``, czyli Token do Zgłoszeń od Maksa (brak tokenu
albo token, którego Skrzynka Zgłoszeń odmówiła)."""


class Sent(Model):
    """Skrzynka Zgłoszeń przyjęła wysyłkę taty, od razu albo gdy Kolejka wysyłki dostarczyła ją później."""

    state: Literal["sent"]


class Queued(Model):
    """Wysyłka taty czeka w Kolejce wysyłki na tym komputerze i wyjdzie sama, także po następnym starcie, gdy będzie
    to, na co czeka."""

    state: Literal["queued"]
    waits_for: WaitsFor


class Rejected(Model):
    """Skrzynka Zgłoszeń odrzuciła treść wysyłki taty: ani internet, ani Token do Zgłoszeń tego nie naprawią.

    Plik zostaje w Kolejce wysyłki, która spróbuje go dopiero przy następnym starcie Centrum, więc Centrum niczego nie
    obiecuje, tylko każe skontaktować się z Maksem.
    """

    state: Literal["rejected"]


Sending = Sent | Queued | Rejected
"""Stan wysyłki taty (Zgłoszenia albo Uwagi taty) w Kolejce wysyłki, ten sam w odpowiedzi na „Wyślij”, w stanie
Zgłoszenia i w Powiadomieniu."""


SendState = Annotated[Sending, Field(discriminator="state")]
