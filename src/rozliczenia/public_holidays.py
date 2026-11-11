"""Polskie dni ustawowo wolne od pracy roku z nazwami, bez internetu i bez zależności.

Lista z ustawy o dniach wolnych od pracy: dziesięć dni o stałej dacie (Wigilia od 2025 roku) i cztery liczone od
Wielkanocy. Rok od 2011, odkąd 6 stycznia jest dniem wolnym; wcześniejszych zmian ustawy funkcja nie zna.
"""

from __future__ import annotations

from datetime import date, timedelta

_FIXED: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Nowy Rok"),
    (1, 6, "Trzech Króli"),
    (5, 1, "Święto Pracy"),
    (5, 3, "Święto Konstytucji 3 Maja"),
    (8, 15, "Wniebowzięcie Najświętszej Maryi Panny"),
    (11, 1, "Wszystkich Świętych"),
    (11, 11, "Święto Niepodległości"),
    (12, 25, "Boże Narodzenie"),
    (12, 26, "Drugi dzień Bożego Narodzenia"),
)
_CHRISTMAS_EVE_SINCE = 2025
_FROM_EASTER: tuple[tuple[int, str], ...] = (
    (0, "Wielkanoc"),
    (1, "Poniedziałek Wielkanocny"),
    (49, "Zielone Świątki"),
    (60, "Boże Ciało"),
)


def public_holidays(year: int) -> dict[date, str]:
    """Dni ustawowo wolne od pracy roku ``year``: dzień → nazwa święta."""

    holidays = {date(year, month, day): name for month, day, name in _FIXED}
    if year >= _CHRISTMAS_EVE_SINCE:
        holidays[date(year, 12, 24)] = "Wigilia"
    easter = _easter(year)
    holidays.update({easter + timedelta(days=days): name for days, name in _FROM_EASTER})
    return holidays


def _easter(year: int) -> date:
    """Niedziela Wielkanocna kalendarza gregoriańskiego (algorytm Meeusa, Jonesa i Butchera)."""

    golden = year % 19
    century, of_century = divmod(year, 100)
    leap_centuries, century_rest = divmod(century, 4)
    correction = (century + 8) // 25
    moon_correction = (century - correction + 1) // 3
    epact = (19 * golden + century - leap_centuries - moon_correction + 15) % 30
    leap_years, year_rest = divmod(of_century, 4)
    weekday = (32 + 2 * century_rest + 2 * leap_years - epact - year_rest) % 7
    shift = (golden + 11 * epact + 22 * weekday) // 451
    month, day = divmod(epact + weekday - 7 * shift + 114, 31)
    return date(year, month, day + 1)
