"""Układ arkusza Pliku zbiorczego: wiersze i kolumny, w których tata trzyma koszty, nagłówki i Wiersze danych.

Wspólny dla Pliku zbiorczego, Wzorca pliku zbiorczego, Wzorca rozliczenia pracownika i Szablonów pracowników. Każdy,
kto czyta albo pisze ten arkusz po położeniu (skoroszyt, plik z Wzorca, Kontrola ilości, Wycena w efenix, narzędzia),
pyta tu o wiersz i kolumnę, zamiast wpisywać własną liczbę albo literę. Kolumny są numerami od 1, zapisanymi literami
z GLOSSARY; ``letter`` daje literę numeru.
"""

from __future__ import annotations

from typing import Final

_LETTERS: Final = 26


def column(letters: str) -> int:
    """Numer od 1 kolumny o literach ``letters`` (``"A"`` → 1, ``"AU"`` → 47)."""

    number = 0
    for character in letters:
        number = number * _LETTERS + ord(character) - ord("A") + 1
    return number


def letter(number: int) -> str:
    """Litery kolumny o numerze od 1 ``number`` (47 → ``"AU"``)."""

    letters = ""
    while number:
        number, rest = divmod(number - 1, _LETTERS)
        letters = chr(ord("A") + rest) + letters
    return letters


def _span(first: str, last: str) -> range:
    return range(column(first), column(last) + 1)


COST_ROW: Final = 14
"""Koszt jednej sztuki każdej pozycji Ilości usług (GLOSSARY: Ilości usług)."""
HEADER_ROW: Final = 17
FIRST_DATA_ROW: Final = 18

ADDRESS_COLUMN: Final = column("B")
WORKER_COLUMN: Final = column("H")
ORANGE_COLUMN: Final = column("I")
"""``NUMER UMOWY/ZLECENIA ORANGE``."""
INPUT_COLUMNS: Final = _span("A", "K")
"""Nagłówki w wierszu 17 i dane wejściowe Wiersza danych."""
LOOK_COLUMNS: Final = _span("A", "L")
"""Kolumny wyglądu Wiersza danych (``row_look``)."""
QUANTITY_COLUMNS: Final = _span("N", "AP")
"""Ilości usług (GLOSSARY)."""
QUANTITY_LETTERS: Final = tuple(letter(number) for number in QUANTITY_COLUMNS)
DEFECT_COLUMN: Final = column("AI")
"""Ilość za usterkę: usterka nie jest Zleceniem ze zdjęciami (GLOSSARY)."""
PHOTO_COLUMNS: Final = (*_span("AB", "AF"), *_span("AJ", "AP"), column("AS"))
"""Kolumny Zlecenia ze zdjęciami (GLOSSARY)."""
CHARGE_DESCRIPTION, CHARGE_AMOUNT, REMARKS_AMOUNT, REMARKS = _span("AQ", "AT")
"""Wpisy taty za Ilościami usług: obciążenie klienta (opis, kwota) i uwagi (kwota, treść)."""
DATA_ROW_COLUMNS: Final = _span("A", "AT")
"""Kolumny Wiersza danych kopiowane z Pliku zbiorczego do Szablonu pracownika."""
AMOUNT_COLUMN: Final = column("AU")
"""``Kwota`` zlecenia, którą liczy formuła Pliku zbiorczego."""
