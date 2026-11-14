"""Bieg próbki drogi do Skrzynki Zgłoszeń: czy wartość komórki z próbki dochodzi do pliku kolejki.

Plik kolejki pisze ``outbox._queue_text`` (``Post.to_json``, z niego ``LogsPost.to_json`` i ``Outbox.post``). Bieg daje
wynik próbki tej samej drodze, więc próbka znanej luki tekstu do wysyłki przechodzi go tylko wtedy, gdy wartość komórki
naprawdę stoi w pliku kolejki, a odmowa na tej drodze (np. podklasy przy jej powstaniu) jest zgłoszeniem.
"""

from __future__ import annotations

from collections.abc import Mapping
import inspect
from types import ModuleType

from rozliczenia.centrum.outbox import ArchiveFile, NewIssue, OpenIssue, PeriodThread, Post
from rozliczenia.client_data import tool


def tekst_pliku_kolejki(wynik: object) -> str:
    """Tekst pliku kolejki z wyniku próbki: wysyłki (``Post``, ``LogsPost``), celu wysyłki albo pliku w Archiwum, który
    dostaje wysyłkę z tekstem narzędzia; napis to tekst, który próbka sama przeczytała z dysku (plik Logów)."""

    match wynik:
        case str():
            return wynik
        case ArchiveFile():
            watek = PeriodThread("logi-uruchomienia", tool("- Logi"), "reuse", tool("Logi"))
            return Post(watek, "08_14_09_2026", "r", tool("Nagłówek"), (tool("Komentarz"),), wynik).to_json()
        case OpenIssue():
            return Post(wynik, None, "r", None, (wynik.line,)).to_json()
        case NewIssue() | PeriodThread():
            return Post(wynik, None, "r", None, (tool("Treść"),)).to_json()
        case _:
            to_json = getattr(wynik, "to_json")
            return str(to_json())


def bieg_do_pliku_kolejki(wykonany: ModuleType, argumenty: Mapping[str, object], komorka: str) -> list[str]:
    """Zgłoszenie biegu próbki: jedyna funkcja modułu próbki dostaje z ``argumenty`` swoje parametry po nazwie, a jej wynik
    idzie do pliku kolejki (``tekst_pliku_kolejki``). Odmowa (``TypeError``) albo plik kolejki bez ``komorka`` to
    zgłoszenie; pusta lista: wartość komórki stoi w pliku kolejki."""

    funkcje = [
        wartosc
        for nazwa, wartosc in vars(wykonany).items()
        if inspect.isfunction(wartosc) and wartosc.__module__ == wykonany.__name__ and not nazwa.startswith("_")
    ]
    assert len(funkcje) == 1, f"próbka ma mieć jedną funkcję, a ma {[funkcja.__name__ for funkcja in funkcje]}"
    funkcja = funkcje[0]
    try:
        tekst = tekst_pliku_kolejki(funkcja(**{nazwa: argumenty[nazwa] for nazwa in inspect.signature(funkcja).parameters}))
    except TypeError as odmowa:
        return [f"bieg TypeError: {odmowa}"]
    return [] if komorka in tekst else ["bieg: plik kolejki bez wartości komórki"]
