"""Tydzień czasu polskiego narzędzi tygodniowych: od poniedziałku 0:00 do następnego poniedziałku 0:00 w ``Europe/Warsaw``.

Granice biorą strefę także po zmianie czasu, więc tydzień ze zmianą ma 167 albo 169 godzin. Moduł bierze tylko
bibliotekę standardową, bo tygodniowy pomiar korzeni biegnie w workflow systemowym Pythonem runnera.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")


def week_of(moment: datetime) -> date:
    day = moment.astimezone(WARSAW).date()
    return day - timedelta(days=day.weekday())


def last_full_week(now: datetime) -> date:
    return week_of(now) - timedelta(days=7)


def midnight(day: date) -> datetime:
    return datetime.combine(day, time(), WARSAW)
