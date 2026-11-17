"""Znaczniki Wyceny w efenix w komórce ``ADRES``: jasnofioletowy Znacznik efenix gotowego zlecenia i ciemniejszy fiolet
Znacznika przekazania zlecenia przekazanego do akceptacji.

Kolory mają jednego właściciela, ``Mark``, a wypełnienie, które jest Znacznikiem, rozpoznaje ``mark_of``: Przebieg
rozliczeń i zapis Znaczników Wyceny w efenix (``efenix_marking``) pytają obu, bez osobnej kopii. Który Znacznik zastępuje
który, mówi ``Mark.replaces``. Znacznik nie jest Wyróżnieniem, więc Przebieg rozliczeń zdejmuje każdy z nich z Wierszy
danych w drodze do Rozliczenia pracownika (``worker_settlement``), a Plik zbiorczy dalej go ma.
"""

from __future__ import annotations

import enum

from openpyxl.styles.fills import Fill, PatternFill

class Mark(enum.Enum):
    """Znacznik w ``ADRES``; wartość to RGB jednolitego wypełnienia, bez względu na kanał alfa, który Excel pomija.

    Oba kolory nie zaciemniają czarnego tekstu adresu: kontrast 14,3:1 jasnego i 8,0:1 ciemnego (WCAG AAA, decyzja Maksa
    7.11.2026).
    """

    READY = "E0CCFF"
    """Znacznik efenix: zlecenie gotowe, Przekazanie do akceptacji należy do taty."""
    FORWARDED = "B48AFF"
    """Znacznik przekazania: zlecenie ma w efenix status „Do akceptacji”."""

    def replaces(self, current: Mark | None) -> bool:
        """Znacznik staje w komórce ze Znacznikiem ``current`` (``None``: bez Znacznika): Znacznik przekazania zastępuje
        Znacznik efenix, a Znacznik efenix nigdy nie zastępuje Znacznika przekazania, bo zlecenie przekazane nie wraca do
        wyceny."""

        return current is None or (self is Mark.FORWARDED and current is Mark.READY)


def mark_of(fill: Fill | None) -> Mark | None:
    """Znacznik, którym jest wypełnienie: jednolite w kolorze ``Mark`` podanym jako RGB; ``None``: żaden."""

    if not isinstance(fill, PatternFill) or fill.patternType != "solid" or fill.fgColor.type != "rgb":
        return None
    rgb = str(fill.fgColor.rgb).upper()
    return next((mark for mark in Mark if rgb.endswith(mark.value)), None)
