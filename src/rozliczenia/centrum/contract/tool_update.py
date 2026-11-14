"""Kontrakt Aktualizacji narzędzia: jej kroki i wynik."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Message, Model
from rozliczenia.centrum.contract.diagnosis import ReportDraft, ReportState


ToolUpdateStep = Literal["fetching", "installing", "restarting"]
"""Krok Aktualizacji narzędzia: pobieranie nowej wersji, instalowanie bibliotek, ponowne uruchamianie Centrum."""


class ToolUpdateIdle(Model):
    """Od startu Centrum tata nie zlecił Aktualizacji narzędzia."""

    state: Literal["idle"]


class ToolUpdateRunning(Model):
    state: Literal["running"]
    step: ToolUpdateStep


class ToolUpdateUpToDate(Model):
    """Narzędzie już było w najnowszej wersji; nic się nie zmieniło."""

    state: Literal["up_to_date"]


class ToolUpdateUpdated(Model):
    """Narzędzie jest w nowej wersji; to Centrum wystartowało już w niej (jej commit jest w ``Health``)."""

    state: Literal["updated"]


class ToolUpdateFailed(Model):
    """Aktualizacja narzędzia się nie udała; narzędzie zostało w wersji sprzed kliknięcia.

    ``next_action`` ``retry``: tata klika „Zaktualizuj narzędzie” jeszcze raz (np. gdy wróci internet);
    ``report``: sprawę przejmuje Maks. ``draft`` to Zgłoszenie z faktami dziennika tej aktualizacji, które
    wyśle „Wyślij do Maksa”, a ``report`` jego stan. ``after_restart``: porażkę zastało to Centrum przy starcie, od
    opiekuna ponownego startu (np. nowa wersja nie wystartowała), a nie z kliknięcia w tym Centrum.
    """

    state: Literal["failed"]
    message: Message
    next_action: Literal["retry", "report"]
    report: ReportState
    draft: ReportDraft
    after_restart: bool


ToolUpdate = Annotated[
    ToolUpdateIdle | ToolUpdateRunning | ToolUpdateUpToDate | ToolUpdateUpdated | ToolUpdateFailed,
    Field(discriminator="state"),
]
