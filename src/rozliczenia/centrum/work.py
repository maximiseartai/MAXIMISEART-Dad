"""Praca Centrum rozliczeń: to, co dzielą moduły Centrum od startu serwera do jego zamknięcia.

Moduł Centrum bierze ``CentrumWork`` i sam wie, które jego pliki leżą w katalogu ``config`` (obok Ustawień Centrum) albo
obok dziennika Centrum (``log.directory``, katalog Logów, ADR 0015), więc nowy plik stanu albo nowa wspólna zależność
modułu zmienia tylko ten moduł, nie ``create_app``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.client_data import ForbiddenValues


@dataclass(frozen=True)
class CentrumWork:
    """Jedna praca Centrum; ``forbidden`` to pamięć reguły danych (ADR 0025): zakazane wartości z każdego pliku taty,
    który ta praca przeczytała, dla strażnika każdej wysyłki do Skrzynki, tylko w pamięci. Pustą pamięć daje jej tylko
    start serwera (``app.create_app``), więc moduł Centrum nie zbuduje drugiej pracy z pustą pamięcią obok niej."""

    config: Path
    log: CentrumLog
    clock: Clock
    pause: Callable[[float], None]
    forbidden: ForbiddenValues
