"""Ryzyko przyjęte przez Maksa przy regule położenia wiersza (decyzja z 5.11.2026, ADR 0025): klasy przypadków, w
których fakt domeny nie zachodzi, a adres albo numer Orange wychodzi, i termin ich przeglądu.

Reguła zna każdy wiersz w jednym położeniu: pierwszy wiersz bloku wklejenia przesunięty o dwie kolumny w lewo, każdy
inny pod nagłówkiem, a inny wiersz z datą z godziną dwie kolumny przed ``DATA GODZ. POCZ.`` w obu. Przypadek klasy z
``KNOWN`` jest ``xfail`` strict: po terminie znów pada, a naprawiony pada od razu.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

KNOWN_UNTIL = date(2027, 2, 5)
"""Termin przeglądu ryzyka przyjętego przez Maksa: po nim przypadki ``KNOWN`` znów padają."""
KNOWN = {
    "pierwszy_na_miejscu": "Fakt domeny złamany (ryzyko przyjęte przez Maksa 5.11.2026, ADR 0025): pierwszy wiersz bloku "
    "wklejenia nie jest przesunięty w całości, a pamięć reguły danych zna go tylko przesuniętego",
    "przesuniety_inny_bez_sladu": "Fakt domeny złamany (ryzyko przyjęte przez Maksa 5.11.2026, ADR 0025): przesunięty jest "
    "wiersz inny niż pierwszy, bez daty z godziną dwie kolumny przed DATA, więc pamięć reguły danych zna go tylko pod "
    "nagłówkiem",
}
"""Klasa przypadku → powód z zgodą Maksa."""


def known(klass: str | None) -> tuple[pytest.MarkDecorator, ...]:
    """Znaczniki przypadku klasy ``klass`` (``None``: fakt domeny zachodzi albo ślad go zdradza, więc przypadek musi
    przejść)."""

    if klass is None or datetime.now().astimezone().date() > KNOWN_UNTIL:
        return ()
    return (pytest.mark.xfail(strict=True, reason=KNOWN[klass]),)
