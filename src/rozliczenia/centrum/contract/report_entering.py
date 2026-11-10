"""Kontrakt Wpisania raportów: karta „Wpisz raporty z maili” poza okresami i widok Raporty (ADR 0028)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.runs import RunRestored


class ReportEnteringSetup(Model):
    """Karta „Wpisz raporty z maili” poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty.

    ``reminder`` to przypomnienie przed kliknięciem, ``blocker`` mówi, czego brakuje w Ustawieniach taty albo w
    ``config`` (plik dostępu do skrzynki raportów, plik adresów Wykonawców), albo jaka kopia konfliktu OneDrive leży
    obok INTERMAX, ``open_in_excel`` to zdanie o INTERMAX otwartym w Excelu, a ``last`` to karta ostatniego Wpisania
    raportów z jego Logów Uruchomienia (``None``: żadnego albo jego Logów nie da się odczytać).
    """

    title: str
    reminder: str
    blocker: str | None
    open_in_excel: list[str]
    last: RunRestored | None


class KeptCell(Model):
    """Komórka zlecenia z treścią Wpisu raportu, przy której tata klika „Zostaw moją”: numer, dzień i Wykonawca
    zlecenia, kolumna INTERMAX i treść Wpisu (``reported``), która różni się od ręcznej wartości."""

    number: str
    day: date
    worker: str
    column: Literal["SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE"]
    reported: str


class ReportsProblem(Model):
    """Problem z ostatniego kliknięcia: zdanie dla taty, numer zlecenia (``None``: problem bez numeru), adres
    nieznanego nadawcy (tylko przy nim) i komórka różnicy z ręczną wartością, przy której stoi „Zostaw moją”
    (``keep``)."""

    reason: str
    number: str | None
    sender: str | None
    keep: KeptCell | None


class ReportsWorker(Model):
    """Wykonawca w wybranym dniu: jego zlecenia z dnia, wpisane (``tak`` albo ``nie`` w ``SKUTECZNE`` po kliknięciu,
    kto by ich nie wpisał), Raporty wykonawcy, problemy bez tych, przy których tata kliknął „Zostaw moją”, i numery
    zleceń bez żadnego Wpisu."""

    worker: str
    orders: int
    entered: int
    mails: int
    problems: list[ReportsProblem]
    without_report: list[str]


class ReportsView(Model):
    """Widok Raporty: wynik ostatniego udanego kliknięcia „Wpisz raporty z maili” bez czytania skrzynki.

    ``clicked_at`` to chwila tego kliknięcia (``None``: jeszcze żadnego), ``today`` dzisiejszy dzień z zegara Centrum,
    ``day`` wybrany dzień, ``days`` dni do wyboru od najnowszego (dziś i dni otwartych okresów z ostatniego kliknięcia),
    ``workers`` Wykonawcy wybranego dnia, a ``unknown_senders`` Raporty wykonawcy z tego dnia z adresów spoza listy
    adresów Wykonawców.
    """

    clicked_at: datetime | None
    today: date
    day: date
    days: list[date]
    workers: list[ReportsWorker]
    unknown_senders: list[ReportsProblem]
