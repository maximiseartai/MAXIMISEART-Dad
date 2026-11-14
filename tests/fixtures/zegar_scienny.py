"""Zegar ścienny ``src`` (``rozliczenia.wall_clock``), który biegnie od chwili wybranej przez test."""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
import time
from typing import Self

import pytest

from rozliczenia import wall_clock


def wall_clock_from(monkeypatch: pytest.MonkeyPatch, start: datetime) -> None:
    """``utc_now``, ``local_now`` i ``dad_today`` biegną od ``start`` (chwila ze strefą) w tempie prawdziwego zegara.

    Kod ``src`` bierze chwilę tylko z ``rozliczenia.wall_clock`` (ruff ``TID251``), a ten pyta ``datetime.now``, więc
    podmiana tej jednej nazwy przestawia zegar całego Centrum, także w jego wątkach. Test, który szuka w wyjściu godziny
    albo daty z pliku taty, nie zależy wtedy od godziny biegu (#1789). Gdy ``wall_clock`` przestanie pytać
    ``datetime.now``, fixture pada od razu, zamiast zostawić test na prawdziwym zegarze.
    """

    started = time.monotonic()

    class Moving(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(start.timestamp() + time.monotonic() - started, tz)

    monkeypatch.setattr(wall_clock, "datetime", Moving)
    assert abs(wall_clock.utc_now() - start) < timedelta(minutes=1), "rozliczenia.wall_clock nie bierze chwili z datetime.now"
