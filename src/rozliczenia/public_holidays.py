from __future__ import annotations

from datetime import date, timedelta

# ZEWNĘTRZNE: 6 stycznia jest dniem wolnym od pracy od 2011 roku, więc _FIXED to dni o stałej dacie z ustawy od 2011, a wcześniejszych zmian ustawy funkcja nie zna (ustawa z 18 stycznia 1951 o dniach wolnych od pracy, art. 1)
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
    holidays = {date(year, month, day): name for month, day, name in _FIXED}
    if year >= _CHRISTMAS_EVE_SINCE:
        holidays[date(year, 12, 24)] = "Wigilia"
    easter = _gregorian_easter(year)
    holidays.update({easter + timedelta(days=days): name for days, name in _FROM_EASTER})
    return holidays


def _gregorian_easter(year: int) -> date:
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
