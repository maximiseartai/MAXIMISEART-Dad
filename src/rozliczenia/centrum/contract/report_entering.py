"""Kontrakt Wpisania raportów: przycisk „Wpisz raporty z maili” poza okresami, widok Raporty (ADR 0028) i Wpis na
życzenie (ADR 0041)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.runs import RunRestored


class ReportEnteringSetup(Model):
    """Przycisk „Wpisz raporty z maili” na ekranie Raporty, poza okresami: INTERMAX to Rejestr zleceń z Ustawień Centrum.

    ``reminder`` to przypomnienie przed kliknięciem, ``blocker`` mówi, czego brakuje w Ustawieniach Centrum albo w
    ``config`` (plik dostępu do skrzynki raportów, plik adresów Wykonawców), albo jaka kopia konfliktu OneDrive leży
    obok INTERMAX, ``open_in_excel`` to zdanie o INTERMAX otwartym w Excelu, a ``last`` to karta ostatniego Wpisania
    raportów z jego Logów Uruchomienia, linia „Ostatnio …” pod przyciskiem (``None``: żadnego albo jego Logów nie da się
    odczytać).
    """

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


class RequestedCell(Model):
    """Wpis na życzenie przy problemie: Wpis, przy którym tata klika (skrót Raportu wykonawcy ``mail``, Wykonawca,
    dzień, w którym widzi problem, numer i czynności), i co się wpisze do INTERMAX: ``successful`` w ``SKUTECZNE`` i ``activities`` w ``CZYNNOŚCI
    ZREALIZOWANE`` zlecenia z dnia ``order_day``. Tę samą komórkę przeglądarka odsyła przy kliknięciu."""

    mail: str
    number: str
    day: date
    worker: str
    activities: str
    successful: Literal["tak", "nie"]
    order_day: date


class ReportsProblem(Model):
    """Problem z ostatniego kliknięcia przy dniu Wykonawcy: zdanie dla taty, numer zlecenia (``None``: problem bez
    numeru), komórka różnicy z ręczną wartością, przy której stoi „Zostaw moją” (``keep``), i Wpis na życzenie, przy
    którym stoi jego przycisk (``request``; ``None``: przycisku nie ma)."""

    reason: str
    number: str | None
    keep: KeptCell | None
    request: RequestedCell | None


class ReportsNote(Model):
    """Informacja z ostatniego kliknięcia przy dniu Wykonawcy o zmianie, którą Centrum zrobiło w INTERMAX (ADR 0029):
    numer zlecenia i krótkie zdanie, np. „przejęte od …” albo „przekazane …”. Nie jest problemem ani Zgłoszeniem."""

    number: str
    text: str


class ReportsOrder(Model):
    """Zlecenie dnia Wykonawcy w kolejności z INTERMAX: numer, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` po zapisie
    zmian kliknięcia, kto by ich nie wpisał (``None``: pusta komórka), i stan: wpisane z Wpisu (``entered``), bez
    żadnego Wpisu (``without_report``) albo z problemem, którego tata nie zostawił „Zostaw moją” (``problem``).

    ``codes``: słowa opisu zlecenia ``tak``, które Legenda czynności kliknięcia wzięła za Kody czynności, w zapisie legendy
    i kolejności z opisu (pusta lista także przy zleceniu bez ``tak``). ``no_code``: zlecenie ``tak`` bez żadnego Kodu
    czynności, informacja „BRAK KODU” dla taty, bo Ilości z opisu wpisze sam; nie jest problemem ani Zgłoszeniem."""

    number: str
    successful: str | None
    activities: str | None
    state: Literal["entered", "without_report", "problem"]
    codes: list[str]
    no_code: bool


class ReportsWorkerDay(Model):
    """Dzień Wykonawcy z ostatniego kliknięcia: jego zlecenia z dnia, wpisane (``tak`` albo ``nie`` w ``SKUTECZNE`` po
    kliknięciu, kto by ich nie wpisał), Raporty wykonawcy, problemy bez tych, przy których tata kliknął „Zostaw moją”,
    informacje o Przeniesieniach zleceń (``notes``), numery zleceń bez żadnego Wpisu i zlecenia dnia (``orders_detail``;
    ``None``: wynik kliknięcia sprzed listy zleceń, dopóki tata nie kliknie znowu)."""

    day: date
    orders: int
    entered: int
    mails: int
    without_report: list[str]
    problems: list[ReportsProblem]
    notes: list[ReportsNote]
    orders_detail: list[ReportsOrder] | None
    reminders: list[datetime]
    """Chwile wysłania Przypomnień o raporcie za ten dzień do tego Wykonawcy z ostatniego sprawdzenia pracy przypomnień,
    od najstarszej (ADR 0030), bez adresów i tematów maili."""


class ReportsWorker(Model):
    """Wykonawca z ostatniego kliknięcia i jego dni ze zleceniami, Raportem wykonawcy, problemem albo informacją, od
    najstarszego."""

    worker: str
    days: list[ReportsWorkerDay]


class ReportsDay(Model):
    """Dzień okna widoku Raporty z nazwą polskiego dnia ustawowo wolnego od pracy (``None``: dzień bez święta)."""

    day: date
    holiday: str | None


class UnknownReportSender(Model):
    """Raport wykonawcy z dnia ``day`` z adresu ``sender`` spoza Listy Wykonawców z ostatniego kliknięcia, ze zdaniem dla
    taty. ``worker``: login Wykonawcy, któremu tata przypisał ten adres po kliknięciu (Lista Wykonawców ma
    go teraz), więc następne kliknięcie wpisze ten raport; ``None``: adres dalej nieznany."""

    day: date
    sender: str
    reason: str
    worker: str | None


class ReportsView(Model):
    """Widok Raporty: wynik ostatniego udanego kliknięcia „Wpisz raporty z maili” bez czytania skrzynki, dla całego okna.

    ``clicked_at`` to chwila tego kliknięcia (``None``: jeszcze żadnego), ``today`` dzisiejszy dzień z zegara Centrum,
    ``days`` dni okna od najstarszego (dni otwartych okresów z ostatniego kliknięcia i dziś), ``workers`` Wykonawcy
    alfabetycznie, a ``unknown_senders`` Raporty wykonawcy z adresów spoza Listy Wykonawców.
    """

    clicked_at: datetime | None
    today: date
    days: list[ReportsDay]
    workers: list[ReportsWorker]
    unknown_senders: list[UnknownReportSender]
    reminders_without_footer: bool
    """Ostatnie sprawdzenie pracy przypomnień nie znalazło pliku stopki taty, więc Przypomnienia o raporcie idą bez
    niej; bez treści stopki."""
