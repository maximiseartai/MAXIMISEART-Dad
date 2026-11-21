"""Zegar ścienny ``src`` (``rozliczenia.wall_clock``), który stoi na chwili wybranej przez test i rusza o 1 µs na pytanie."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, tzinfo
import itertools
import threading
from typing import Self

import pytest

from rozliczenia import wall_clock

MOMENTS = 10_000
"""Najwięcej pytań o zegar w jednym teście; chwile zegara to ``start + k µs`` dla ``k < MOMENTS``."""
STEP = timedelta(microseconds=1)


def wall_clock_from(monkeypatch: pytest.MonkeyPatch, start: datetime) -> None:
    """Każda funkcja ``rozliczenia.wall_clock`` daje chwile ``start + k µs`` (``start`` ze strefą), k-te pytanie ``k``.

    Kod ``src`` bierze chwilę tylko z ``rozliczenia.wall_clock`` (ruff ``TID251``), a ten pyta zegar systemu jednym
    ``datetime.now`` w ``utc_now``, więc podmiana tej jednej nazwy przestawia zegar całego Centrum, także w jego wątkach.
    Zegar rośnie o 1 µs na pytanie, więc chwile są różne i po kolei, a test zna z góry każdą chwilę, którą może zapisać:
    gdy szuka w wyjściu godziny albo daty z pliku taty, sprawdza raz, że żadna z tych chwil jej nie zawiera (#1789).
    Pytanie numer ``MOMENTS`` pada zamiast wyjść poza te chwile.

    Fixture pada też od razu, gdy którakolwiek publiczna wywoływalna nazwa ``wall_clock`` poza klasą (funkcja modułu,
    przypisany ``time.time``, ``functools.partial``) wołana bez argumentów da chwilę, datę albo sekundy spoza
    podstawionego zegara, wynik, którego fixture nie porównuje, albo wymaga argumentu: wtedy pyta system inną drogą.
    """

    asked = itertools.count()
    lock = threading.Lock()

    class Stepping(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            with lock:
                step = next(asked)
            assert step < MOMENTS, f"test zapytał zegar ścienny więcej niż {MOMENTS} razy; podnieś MOMENTS i sprawdź chwile"
            moment = (start + step * STEP).astimezone(tz)
            return cls.combine(moment.date(), moment.timetz() if tz is not None else moment.time())

    monkeypatch.setattr(wall_clock, "datetime", Stepping)
    outside = [problem for name, read in _clock_readings() if (problem := _outside(name, read, start))]
    assert outside == [], f"rozliczenia.wall_clock pyta zegar systemu poza podstawionym datetime.now: {outside}"


def _clock_readings() -> list[tuple[str, Callable[[], object]]]:
    """Publiczne wywoływalne nazwy modułu ``wall_clock`` poza klasami (importowane ``date``, ``datetime``)."""

    return [
        (name, value)
        for name, value in vars(wall_clock).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, type)
    ]


def _outside(name: str, read: Callable[[], object], start: datetime) -> str | None:
    last = start + MOMENTS * STEP
    try:
        value = read()
    except TypeError as refused:
        return f"{name}: nie da się wywołać bez argumentów ({refused})"
    if isinstance(value, datetime):
        inside = value.tzinfo is not None and start <= value < last
    elif isinstance(value, date):
        inside = value in {start.astimezone().date(), last.astimezone().date()}
    elif isinstance(value, float):
        inside = start.timestamp() <= value < last.timestamp()
    else:
        return f"{name}: wynik typu {type(value).__name__}, którego fixture nie porównuje z zegarem"
    return None if inside else f"{name}: {value!r}"
