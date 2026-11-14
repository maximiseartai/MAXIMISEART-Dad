"""Kontrakt Diagnozy i Zgłoszenia do Maksa: wynik Diagnozy, podgląd i stan Zgłoszenia."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Message, Model, Sending


class ReportDraft(Model):
    """Dokładna treść Zgłoszenia, które „Wyślij do Maksa” wyśle do skrzynki Zgłoszeń: tytuł i treść Markdown."""

    title: str
    body: str


class ReportReady(Model):
    """Zgłoszenia tego problemu jeszcze nie wysłano; „Wyślij do Maksa” wyśle podgląd z Diagnozy."""

    state: Literal["ready"]


class ReportWaiting(Model):
    """Zgłoszenie tego problemu wysłano wcześniej i jest otwarte: czeka na naprawę, drugie nie powstaje."""

    state: Literal["waiting"]


class ReportNotQueued(Model):
    """Zgłoszenia nie udało się zapisać w kolejce, więc nic go nie wyśle; ``message`` mówi, co zrobić."""

    state: Literal["not_queued"]
    message: Message


ReportState = Annotated[ReportReady | ReportWaiting | ReportNotQueued | Sending, Field(discriminator="state")]
"""Stan Zgłoszenia tego problemu: przed wysłaniem, wysłane wcześniej i otwarte, niezapisane w kolejce albo stan jego
wysyłki (``SendState``)."""


CheckState = Literal["passed", "failed", "not_checked"]
"""Wynik sprawdzenia Diagnozy; ten sam w Logach Uruchomienia (``run_logs.LoggedCheck``)."""


class DiagnosisCheck(Model):
    """Jedno sprawdzenie Diagnozy: co sprawdzono, czy przeszło i krótko dlaczego, bez pełnych ścieżek."""

    label: str
    state: CheckState
    detail: str


DiagnosisNextAction = Literal["rerun", "update", "report"]


class Diagnosis(Model):
    """Wynik Diagnozy Zatrzymania: wyjaśnienie w trzech częściach i każde sprawdzenie po kolei.

    ``explanation`` to Komunikat pierwszego sprawdzenia, które nie przeszło, albo „Nie znalazłem
    przyczyny na tym komputerze”. ``next_action`` ``rerun``: przyczynę tata usuwa sam i uruchamia
    ponownie; ``update``: przyczyną jest nowsza wersja narzędzia, więc tata klika „Zaktualizuj
    narzędzie”; ``report``: przyczynę usuwa Maks. ``report`` to podgląd: dokładnie to Zgłoszenie wyśle
    „Wyślij do Maksa” (przy ``rerun`` jako drugi przycisk). ``confirms_stop``: wyjaśnienie to ten sam
    Komunikat (kod i trzy części) co Zatrzymanie, więc przeglądarka go nie powtarza.
    ``update_proposal``: jest nowsza wersja narzędzia, ale wyjaśnieniem jest inna przyczyna, więc
    Diagnoza proponuje Aktualizację narzędzia tylko pod wyjaśnieniem.
    """

    explanation: Message
    confirms_stop: bool
    next_action: DiagnosisNextAction
    update_proposal: bool
    checks: list[DiagnosisCheck]
    report: ReportDraft
