"""Okres rozliczeniowy: token ``dd_dd_mm_rrrr`` i ostatni pełny okres przed danym dniem.

Token zawiera dzień wtorku, dzień poniedziałku oraz miesiąc i rok poniedziałku,
jak zapis zakresu dat ``08–14.09.2026``. Na przełomie miesięcy i lat liczy się
miesiąc poniedziałku, tak jak w folderach taty: okres od wtorku 27 października
do poniedziałku 2 listopada 2026 ma token ``27_02_11_2026``, a od 29 grudnia
2026 do 4 stycznia 2027 token ``29_04_01_2027``. Każdy okres ma dokładnie jeden
token, więc jeden Folder okresu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Zapis tokenu bez sprawdzania dni tygodnia; wspólny dla nazw plików i metryk.
PERIOD_TOKEN_PATTERN = r"\d{2}_\d{2}_\d{2}_\d{4}"
_TUESDAY = 1


@dataclass(frozen=True)
class SettlementPeriod:
    """Okres rozliczeniowy od wtorku do poniedziałku."""

    tuesday: date

    def __post_init__(self) -> None:
        if self.tuesday.weekday() != _TUESDAY:
            raise ValueError("Okres rozliczeniowy zaczyna się we wtorek.")

    @property
    def monday(self) -> date:
        return self.tuesday + timedelta(days=6)

    @property
    def token(self) -> str:
        monday = self.monday
        return f"{self.tuesday.day:02d}_{monday.day:02d}_{monday.month:02d}_{monday.year:04d}"

    @property
    def start(self) -> datetime:
        """Wtorek 00:00."""

        return datetime(self.tuesday.year, self.tuesday.month, self.tuesday.day)

    @property
    def end(self) -> datetime:
        """Następny wtorek 00:00, wyłącznie."""

        return self.start + timedelta(days=7)

    def contains(self, moment: date) -> bool:
        """Czy dzień ``moment`` (przy ``datetime`` jego dzień) leży w okresie."""

        day = moment.date() if isinstance(moment, datetime) else moment
        return self.tuesday <= day <= self.monday


def parse_period_token(token: str) -> SettlementPeriod:
    """Okres z tokenu; ``ValueError``, gdy token nie opisuje okresu od wtorku do poniedziałku."""

    if re.fullmatch(PERIOD_TOKEN_PATTERN, token) is None:
        raise ValueError("Token okresu ma postać dd_dd_mm_rrrr.")
    _, monday_day, month, year = (int(part) for part in token.split("_"))
    try:
        period = SettlementPeriod(date(year, month, monday_day) - timedelta(days=6))
    except (ValueError, OverflowError):
        period = None
    if period is None or period.token != token:
        raise ValueError("Token okresu nie opisuje okresu od wtorku do poniedziałku.")
    return period


def period_of(day: date) -> SettlementPeriod:
    """Okres, w którym leży ``day``."""

    return SettlementPeriod(day - timedelta(days=(day.weekday() - _TUESDAY) % 7))


def last_complete_period(today: date) -> SettlementPeriod:
    """Ostatni pełny okres zakończony przed ``today``; okres kończący się dziś nie jest pełny."""

    days_since_previous_monday = today.weekday() or 7
    return SettlementPeriod(today - timedelta(days=days_since_previous_monday + 6))
