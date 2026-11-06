"""Ryzyko przyjęte przez Maksa przy regule położenia wiersza (decyzja z 6.11.2026, ADR 0025): klasy plików poza
dziedziną, w których adres albo numer Orange wychodzi, i termin ich przeglądu.

Reguła zna każdy wiersz w jednym położeniu: pierwszy wiersz bloku wklejenia przesunięty o dwie kolumny w lewo, każdy
inny pod nagłówkiem. W obu zna pierwszy wiersz bloku, którego przesunięcia nie widać (``raw_orders.shift_visible``: data
z godziną dwie kolumny przed ``DATA GODZ. POCZ.``, a pod nią nie), i inny wiersz z datą z godziną dwie kolumny przed
``DATA GODZ. POCZ.`` (``raw_orders.both_positions``). Klasy A i B łamią fakt domeny bez śladu, a w klasie C fakt
zachodzi, ale reguła bierze za pierwszy wiersz bloku z widocznym przesunięciem wiersz, który stoi na miejscu. Każda klasa
łamie pewnik wklejenia (ADR 0025, sekcja „Pewniki i granica dziedziny”), więc nie jest powodem do FAIL. Przypadek
klasy z ``KNOWN`` jest ``xfail`` strict: po terminie znów pada, a naprawiony pada od razu.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

KNOWN_UNTIL = date(2027, 2, 5)
"""Termin przeglądu ryzyka przyjętego przez Maksa: po nim przypadki ``KNOWN`` znów padają."""
KNOWN = {
    # klasa B
    "pierwszy_na_miejscu": "Fakt domeny złamany (ryzyko przyjęte przez Maksa 6.11.2026, ADR 0025): pierwszy wiersz bloku "
    "wklejenia z widocznym przesunięciem jest przesunięty tylko w części albo stoi na miejscu, a pamięć reguły danych zna "
    "go tylko przesuniętego",
    # klasa A
    "przesuniety_inny_bez_sladu": "Fakt domeny złamany (ryzyko przyjęte przez Maksa 6.11.2026, ADR 0025): przesunięty jest "
    "wiersz inny niż pierwszy, bez daty z godziną dwie kolumny przed DATA, więc pamięć reguły danych zna go tylko pod "
    "nagłówkiem",
    # klasa C
    "na_miejscu_z_data_w_a": "Ryzyko przyjęte przez Maksa 6.11.2026 (ADR 0025): wiersz na miejscu, który nie jest "
    "pierwszym przesuniętym wierszem wklejenia, ma datę z godziną w kolumnie A i bez daty z godziną pod DATA, a reguła "
    "bierze go za pierwszy wiersz bloku (pod wpisem taty w Calibri 8, także na początku bloku nad uporządkowanymi), więc "
    "pamięć reguły danych zna go tylko przesuniętego; u taty kolumna A Rejestru jest pusta w 31 779 wierszach, a "
    "Uporządkowanie ją czyści",
}
"""Klasa przypadku → powód z zgodą Maksa."""


def known(klass: str | None) -> tuple[pytest.MarkDecorator, ...]:
    """Znaczniki przypadku klasy ``klass`` (``None``: fakt domeny zachodzi albo ślad go zdradza, więc przypadek musi
    przejść)."""

    if klass is None or datetime.now().astimezone().date() > KNOWN_UNTIL:
        return ()
    return (pytest.mark.xfail(strict=True, reason=KNOWN[klass]),)
