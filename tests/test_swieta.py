"""Polskie dni ustawowo wolne od pracy, które widok Raporty Centrum oznacza w kolumnach dni (#1319).

Oczekiwane daty pochodzą z ustawy o dniach wolnych od pracy i kalendarza Wielkanocy, nie z uruchomienia funkcji.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from rozliczenia.public_holidays import public_holidays


def test_swieta_roku_to_kazdy_dzien_ustawowo_wolny_z_nazwa() -> None:

    assert public_holidays(2026) == {
        date(2026, 1, 1): "Nowy Rok",
        date(2026, 1, 6): "Trzech Króli",
        date(2026, 4, 5): "Wielkanoc",
        date(2026, 4, 6): "Poniedziałek Wielkanocny",
        date(2026, 5, 1): "Święto Pracy",
        date(2026, 5, 3): "Święto Konstytucji 3 Maja",
        date(2026, 5, 24): "Zielone Świątki",
        date(2026, 6, 4): "Boże Ciało",
        date(2026, 8, 15): "Wniebowzięcie Najświętszej Maryi Panny",
        date(2026, 11, 1): "Wszystkich Świętych",
        date(2026, 11, 11): "Święto Niepodległości",
        date(2026, 12, 24): "Wigilia",
        date(2026, 12, 25): "Boże Narodzenie",
        date(2026, 12, 26): "Drugi dzień Bożego Narodzenia",
    }


@pytest.mark.parametrize(
    ("easter", "corpus_christi"),
    [
        (date(2008, 3, 23), date(2008, 5, 22)),
        (date(2011, 4, 24), date(2011, 6, 23)),
        (date(2019, 4, 21), date(2019, 6, 20)),
        (date(2024, 3, 31), date(2024, 5, 30)),
        (date(2025, 4, 20), date(2025, 6, 19)),
        (date(2026, 4, 5), date(2026, 6, 4)),
        (date(2027, 3, 28), date(2027, 5, 27)),
        (date(2028, 4, 16), date(2028, 6, 15)),
        (date(2029, 4, 1), date(2029, 5, 31)),
        (date(2030, 4, 21), date(2030, 6, 20)),
        (date(2038, 4, 25), date(2038, 6, 24)),
        (date(2049, 4, 18), date(2049, 6, 17)),
        (date(2076, 4, 19), date(2076, 6, 18)),
    ],
)
def test_swieta_od_wielkanocy_stoja_w_znanych_datach(easter: date, corpus_christi: date) -> None:
    """Poniedziałek Wielkanocny to dzień po Wielkanocy, a Zielone Świątki siódma niedziela po niej.

    Lata 2049 i 2076 to dwa wyjątki reguły Gaussa, w których księżycowa data Wielkanocy cofa się o tydzień.
    """

    holidays = public_holidays(easter.year)

    assert {day: holidays.get(day) for day in (easter, easter + timedelta(days=1), easter + timedelta(weeks=7), corpus_christi)} == {
        easter: "Wielkanoc",
        easter + timedelta(days=1): "Poniedziałek Wielkanocny",
        easter + timedelta(weeks=7): "Zielone Świątki",
        corpus_christi: "Boże Ciało",
    }


@pytest.mark.parametrize(("year", "christmas_eve"), [(2024, None), (2025, "Wigilia")])
def test_wigilia_jest_swietem_od_2025_roku(year: int, christmas_eve: str | None) -> None:

    assert public_holidays(year).get(date(year, 12, 24)) == christmas_eve
