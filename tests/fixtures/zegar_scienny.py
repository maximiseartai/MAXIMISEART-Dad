"""Zegar ścienny ``src`` (``rozliczenia.wall_clock``), który biegnie od chwili wybranej przez test."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, tzinfo
import inspect
import time
from typing import Self

import pytest

from rozliczenia import wall_clock

# Najwyżej tyle może minąć między podmianą zegara a sprawdzeniem każdej funkcji ``wall_clock``.
_MARGIN = timedelta(minutes=1)


def wall_clock_from(monkeypatch: pytest.MonkeyPatch, start: datetime) -> None:
    """Każda funkcja ``rozliczenia.wall_clock`` biegnie od ``start`` (chwila ze strefą) w tempie prawdziwego zegara.

    Kod ``src`` bierze chwilę tylko z ``rozliczenia.wall_clock`` (ruff ``TID251``), a ten pyta zegar systemu jednym
    ``datetime.now`` w ``utc_now``, więc podmiana tej jednej nazwy przestawia zegar całego Centrum, także w jego wątkach.
    Test, który szuka w wyjściu godziny albo daty z pliku taty, nie zależy wtedy od godziny biegu (#1789). Gdy którakolwiek
    publiczna funkcja ``wall_clock`` da chwilę, datę albo sekundy spoza podstawionego zegara (zapyta system inną drogą),
    albo wynik, którego fixture nie umie porównać, fixture pada od razu, zamiast zostawić test na prawdziwym zegarze.
    """

    started = time.monotonic()

    class Moving(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(start.timestamp() + time.monotonic() - started, tz)

    monkeypatch.setattr(wall_clock, "datetime", Moving)
    outside = [problem for name, function in _clock_functions() if (problem := _outside(name, function(), start))]
    assert outside == [], f"rozliczenia.wall_clock pyta zegar systemu poza podstawionym datetime.now: {outside}"


def _clock_functions() -> list[tuple[str, Callable[[], object]]]:
    """Publiczne funkcje modułu ``wall_clock`` (bez importowanych), każda wołana bez argumentów."""

    return [
        (name, function)
        for name, function in vars(wall_clock).items()
        if not name.startswith("_") and inspect.isfunction(function) and function.__module__ == wall_clock.__name__
    ]


def _outside(name: str, value: object, start: datetime) -> str | None:
    """Opis wyniku funkcji ``name`` spoza zegara od ``start``; ``None``, gdy wynik jest z niego."""

    if isinstance(value, datetime):
        inside = value.tzinfo is not None and timedelta(0) <= value - start < _MARGIN
    elif isinstance(value, date):
        inside = value in {start.astimezone().date(), (start + _MARGIN).astimezone().date()}
    elif isinstance(value, float):
        inside = 0 <= value - start.timestamp() < _MARGIN.total_seconds()
    else:
        return f"{name}: wynik typu {type(value).__name__}, którego fixture nie porównuje z zegarem"
    return None if inside else f"{name}: {value!r}"
