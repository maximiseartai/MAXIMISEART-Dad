"""Repozytorium mówi po angielsku „flaky test” („flaky testy” w polskim zdaniu), nigdy spolszczoną formą tego słowa.

Maks uznał 29.10, że spolszczona forma źle wygląda w repozytorium i na GitHubie (tytuły issues, etykieta, nazwy
zadań i artefaktów CI), więc test czyta każdy plik śledzony i nieśledzony nieignorowany, także jego ścieżkę, bez
rozróżniania wielkości liter i także wewnątrz identyfikatorów (``TestX``, ``zapisz_x``). ``flake8`` to nazwa
programu, także w kluczu ustawień ruff (``flake8_self``), nie to słowo. Pliku binarnego (z bajtem zero) test nie czyta.

Granica: commity, issues i komentarze na GitHubie widzi tylko przegląd.
"""

from __future__ import annotations

from pathlib import Path
import re

from tests.fixtures.git_repo import git

ROOT = Path(__file__).resolve().parents[1]
# Wzorzec składa słowo z klasy znaków, żeby ten plik sam go nie zawierał.
SPOLSZCZONE = re.compile(r"fl[a]k(?!y|e8(?:_|\b))\w*", re.IGNORECASE)
# Dane historyczne: tekst, którego nie piszemy, tylko przechowujemy taki, jaki był.
HISTORIA = {
    "tests/fixtures/opisy_pr.json": "prawdziwe opisy dawnych PR-ów z GitHuba i ich HTML z renderera (tests/fixtures/opisy_pr.py)",
}


def _wystapienia(nazwa: str, tekst: str) -> list[str]:
    linie = [(0, nazwa), *enumerate(tekst.splitlines(), 1)]
    return [f"{nazwa}:{numer}: „{slowo.group()}”" for numer, linia in linie for slowo in SPOLSZCZONE.finditer(linia)]


def test_repozytorium_mowi_flaky_test_a_nie_spolszczone_slowo() -> None:
    pliki = sorted(set(filter(None, git(ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"))))
    znalezione = []
    for nazwa in pliki:
        sciezka = ROOT / nazwa
        if nazwa in HISTORIA or not sciezka.is_file():
            continue
        tresc = sciezka.read_bytes()
        znalezione += _wystapienia(nazwa, "" if b"\0" in tresc else tresc.decode("utf-8", errors="replace"))
    znalezione += [f"{nazwa}: nie ma takiego pliku, usuń jego wyjątek z HISTORIA" for nazwa in HISTORIA if nazwa not in pliki]

    assert not znalezione, "\n".join([*znalezione, "Napisz „flaky test”, a w polskim zdaniu „flaky testy”."])
