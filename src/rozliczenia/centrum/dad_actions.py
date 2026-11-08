"""Schemat działań taty w Centrum w Logach Uruchomienia: co tata robił w Centrum od poprzedniego Uruchomienia.

Wpisy to start Centrum, otwarty widok i wciśnięty przycisk, każdy z chwilą (UTC). Przycisk to zapytanie API, które coś
zmienia, nazwane operacją API z kontraktu, a start Uruchomienia procesu ma też proces i tryb (``RunMode``). Wpis nie ma
treści zapytania. Wpisy zbiera dziennik (``dad_action_journal``), a Logi Uruchomienia niosą je jako ``DadActions``.

Moduł nie wczytuje FastAPI (dziennik tak, bo jest zależnością tras), więc schemat Logów bierze go bez serwera, także
w katalogu procesów (``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from rozliczenia.centrum import contract

StoredRunMode = Annotated[contract.RunMode, BeforeValidator(contract.RunMode.stored)]
"""Tryb Uruchomienia w pliku na dysku taty (dziennik działań taty, Logi Uruchomienia, plik ostatniego startu, dziennik
Wyceny w efenix): wartość ``RunMode``, a w plikach sprzed schematu Logów 3 jego słowo."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CentrumStarted(_Record):
    """Start Centrum rozliczeń (nowa praca Centrum, np. po zamknięciu, Aktualizacji narzędzia albo restarcie Windows)."""

    at: datetime
    action: Literal["start Centrum"]


class ViewOpened(_Record):
    """Gotowy widok strony z menu; ``kind``: zimny start strony (otwarcie albo odświeżenie karty) albo przejście w menu."""

    at: datetime
    action: Literal["widok"]
    page: contract.PageId
    kind: contract.ViewKind


class ButtonPressed(_Record):
    """Zapytanie API, które coś zmienia, nazwane operacją API; start Uruchomienia procesu ma też proces i tryb."""

    at: datetime
    action: Literal["przycisk"]
    operation: str
    process: contract.ProcessKey | None = None
    mode: StoredRunMode | None = None


DadAction = Annotated[CentrumStarted | ViewOpened | ButtonPressed, Field(discriminator="action")]


class DadActions(_Record):
    """Działania taty w Logach Uruchomienia, po kolei; ``omitted``: wpisy starsze od ``dad_action_journal.MAX_ENTRIES`` najnowszych albo
    nieczytelne."""

    entries: list[DadAction]
    omitted: int
