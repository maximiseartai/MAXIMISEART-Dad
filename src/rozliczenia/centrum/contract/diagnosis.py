"""Kontrakt Diagnozy i Zgłoszenia do Maksa: wynik Diagnozy, podgląd i stan Zgłoszenia."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Message, Model, WaitsFor


class ReportDraft(Model):
    """Dokładna treść Zgłoszenia, które „Wyślij do Maksa” wyśle do skrzynki Zgłoszeń: tytuł i treść Markdown."""

    title: str
    body: str


class ReportReady(Model):
    """Zgłoszenia tego problemu jeszcze nie wysłano; „Wyślij do Maksa” wyśle podgląd z Diagnozy."""

    state: Literal["ready"]


class ReportSent(Model):
    """Zgłoszenie tego problemu wysłano z tego uchwytu (albo kolejka dostarczyła je później); czeka na naprawę."""

    state: Literal["sent"]


class ReportWaiting(Model):
    """Zgłoszenie tego problemu wysłano wcześniej i jest otwarte: czeka na naprawę, drugie nie powstaje."""

    state: Literal["waiting"]


class ReportQueued(Model):
    """Zgłoszenie czeka w Kolejce wysyłki na tym komputerze i wyjdzie samo, gdy będzie to, na co czeka."""

    state: Literal["queued"]
    waits_for: WaitsFor


class ReportRejected(Model):
    """Skrzynka Zgłoszeń odrzuciła treść tego Zgłoszenia: ani internet, ani Token do Zgłoszeń tego nie naprawią.

    Plik zostaje w Kolejce wysyłki, która spróbuje go dopiero przy następnym starcie Centrum, więc Centrum niczego nie
    obiecuje, tylko każe skontaktować się z Maksem.
    """

    state: Literal["rejected"]


class ReportNotQueued(Model):
    """Zgłoszenia nie udało się zapisać w kolejce, więc nic go nie wyśle; ``message`` mówi, co zrobić."""

    state: Literal["not_queued"]
    message: Message


ReportState = Annotated[
    ReportReady | ReportSent | ReportWaiting | ReportQueued | ReportRejected | ReportNotQueued,
    Field(discriminator="state"),
]


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
