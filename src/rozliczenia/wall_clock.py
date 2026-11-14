"""Zegar ścienny: jedyny właściciel chwili „teraz” i dnia taty w ``src/``.

``utc_now`` to chwila, którą kod zapisuje albo porównuje (pliki Centrum, Logi, kolejka Skrzynki), w UTC, więc ma ten sam
zapis na każdym komputerze. ``local_now`` to chwila na zegarze komputera w jego strefie: ją kod pokazuje tacie i z niej
bierze dzień oraz porę taty. ``dad_today`` to dzień taty (okres rozliczeniowy, dzień INTERMAX, Metryki), czyli dzień
w strefie komputera taty, nigdy dzień UTC: od północy do 1:00 (latem do 2:00) czasu taty dzień UTC to jeszcze wczoraj.
``epoch_s`` to sekundy od epoki dla terminu, który czyta też inny proces (dzierżawa opiekuna ponownego startu).

Granica zakazu zegara. Ruff ``TID251`` (``src/ruff.toml``) odrzuca w ``src/`` poza tym plikiem tylko odwołanie, które
ruff rozwiązuje do pełnej nazwy wymienionej w ``src/ruff.toml`` (``datetime.datetime.now``, ``time.time``,
``email.utils.formatdate`` i reszta listy ``CLOCK`` w ``tests/test_zakazy_ruff.py``), także przez import z aliasem.
``tests/test_zakazy_ruff.py`` dokłada, że tej nazwy nie zwalnia ``noqa``, wyjątek w konfiguracji ruff ani wyłączenie
pliku z lintu, a granice zakazu pokazują tam próbki ``ZNANE_LUKI_ZEGARA``, każda za klasą nazwaną w swojej nazwie.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import time


def utc_now() -> datetime:
    """Teraz w UTC: chwila do zapisu i porównania."""

    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """Teraz na zegarze komputera w jego strefie czasu: chwila taty."""

    return datetime.now().astimezone()


def dad_today() -> date:
    """Dzień taty: dzisiejsza data w strefie komputera, nie w UTC."""

    return local_now().date()


def epoch_s() -> float:
    """Teraz w sekundach od epoki."""

    return time.time()
