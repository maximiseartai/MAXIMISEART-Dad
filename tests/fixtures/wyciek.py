"""Jedna wyrocznia wycieku w testach: czy tekst zawiera wartość tak, jak ją widzi strażnik reguły danych.

Definicję „tekst zawiera wartość” ma produkt (``ForbiddenValues.guard`` w ``rozliczenia.client_data``, ADR 0025): słowa
wartości po kolei, całe i bez wielkości liter. Cyfry numeru zlecenia w środku dłuższego słowa (losowy HMAC hex śladu,
mikrosekundy chwili) nie są więc wyciekiem, a numer po ``#``, w cudzysłowie albo po spacji jest. Test nie pisze swojej
definicji wokół cyfr numeru, bo cztery kolejne takie definicje rozjechały się ze strażnikiem (czerwony ``main`` po #757,
przeglądy #765 i #1048); zapadka ``tests/test_zapadki.py`` odrzuca nowe.
"""

from __future__ import annotations

from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, empty_memory, guarded


def zawiera_wartosc(tekst: str, wartosc: str) -> bool:
    """Czy ``tekst`` zawiera ``wartosc`` (numer zlecenia, adres) według strażnika reguły danych.

    To jest też definicja „zawiera” wymagania „ślad bez numeru zlecenia” (#843), które własnej nie ma: numer sklejony ze
    znakiem słowa (``ZL_94001``, ``nr94001``) nie jest w śladzie wyciekiem, a ``#94001`` i ``nr 94001`` są.

    Wartości, której strażnik nie szuka, bo od pierwszego słowa ma mniej niż ``MIN_VALUE`` znaków (jak czterocyfrowy
    numer), pomocnik nie przyjmuje (``ValueError``): test z nią przechodziłby zawsze.
    """

    pamiec = empty_memory()
    pamiec.remember_value(ForbiddenColumn.ADDRESS, wartosc)
    if not guarded(pamiec, wartosc, "wartość").notes:
        raise ValueError(f"strażnik nie szuka wartości krótszej niż {MIN_VALUE} znaków od pierwszego słowa ({len(wartosc)} znaków)")
    return bool(guarded(pamiec, tekst, "tekst testu").notes)
