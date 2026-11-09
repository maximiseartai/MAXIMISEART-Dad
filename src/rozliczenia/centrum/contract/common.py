"""Wspólne typy kontraktu Centrum rozliczeń: Komunikat, odmowa, klucz procesu i otwarcie pliku."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rozliczenia.message import Message as ProcessMessage


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Problem(Model):
    """Odmowa wykonania żądania z bezpiecznym komunikatem dla taty, bez tekstu wyjątku."""

    message: str


# Każdy proces ma klucz, ten sam w Uruchomieniach i w Metrykach.
ProcessKey = Literal["preparation", "settlement", "efenix", "intermax"]


# Proces, którego Uruchomienie tata wybiera z okresem; Uporządkowanie INTERMAX ma własną kartę poza okresami.
PeriodProcessKey = Literal["preparation", "settlement", "efenix"]


class Opened(Model):
    name: str


class Message(Model):
    """Komunikat w trzech częściach (Co się stało, Gdzie, Co zrobić) bez kodu."""

    what: str
    where: str
    action: str

    @classmethod
    def of(cls, message: ProcessMessage) -> Message:
        return cls(what=message.what, where=message.where, action=message.action)


# Na co czeka wysyłka taty w Kolejce wysyłki: ``internet`` albo ``key``, czyli Token do Zgłoszeń od Maksa (brak
# tokenu albo token, którego Skrzynka Zgłoszeń odmówiła).
WaitsFor = Literal["internet", "key"]
