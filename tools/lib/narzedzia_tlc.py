"""Narzędzia TLC modeli TLA+ skilli ``verify-*``: przypięte wersje Javy (``jdk4py``) i ``tla2tools.jar`` oraz ich pobieranie.

Jedyne miejsce tych wersji i jedyna droga pobrania. Pobiera je skrypt skilla ``verify-aktualizacja-narzedzia``
(``sprawdz_aktualizacje.py``) do katalogu podręcznego ``.verification/formal-aktualizacja``, a skrypty modeli innych
skilli biorą narzędzia od niego. Zadania CI, które uruchamiają modele (Mutation checks w ``ci.yml`` i skrypty mutacji
skilli w ``mutacje-nocne.yml``), trzymają ten katalog w ``actions/cache`` z kluczem od skrótu tego pliku, więc nowa
wersja albo suma to nowy klucz.

Chwilowa awaria źródła (błąd sieci, HTTP 5xx albo 429) nie kończy sprawdzenia: ``z_ponowieniem`` ponawia próbę po
przerwach ``PRZERWY_S``, bo jedno 504 GitHub Releases czerwieniło CI PR-ów i noc na ``main`` (#930). Gdy zawiedzie
ostatnia próba albo źródło odpowie innym błędem HTTP, proces kończy się linią z ``BLAD_POBIERANIA``, żeby log nie mylił
awarii pobierania z wynikiem modelu.
"""

from __future__ import annotations

from collections.abc import Callable
import http.client
from pathlib import Path
import shutil
import sys
import time
import urllib.error
import urllib.request

__all__ = [
    "BLAD_POBIERANIA",
    "JDK4PY",
    "PRZERWY_S",
    "TLA_SHA256",
    "TLA_URL",
    "TLA_WERSJA",
    "ChwilowaAwaria",
    "pobierz",
    "z_ponowieniem",
]

JDK4PY = "jdk4py==25.0.2.1"
TLA_WERSJA = "1.7.4"
TLA_URL = f"https://github.com/tlaplus/tlaplus/releases/download/v{TLA_WERSJA}/tla2tools.jar"
TLA_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
# Przerwy przed drugą i trzecią próbą: chwilowe 504 GitHub Releases mija zwykle w sekundach.
PRZERWY_S = (5.0, 20.0)
BLAD_POBIERANIA = "BŁĄD POBIERANIA NARZĘDZIA TLC"


class ChwilowaAwaria(Exception):
    """Próba pobrania zawiodła z powodu, który może minąć: błąd sieci, HTTP 5xx albo 429."""


def z_ponowieniem(narzedzie: str, proba: Callable[[], None]) -> None:
    """Wykonuje ``proba`` pobrania ``narzedzie`` i ponawia ją po ``ChwilowaAwaria`` po każdej z przerw ``PRZERWY_S``.

    Po ostatniej próbie kończy proces linią z ``BLAD_POBIERANIA``, liczbą prób i powodem ostatniej awarii.
    """

    for przerwa in (*PRZERWY_S, None):
        try:
            proba()
            return
        except ChwilowaAwaria as awaria:
            if przerwa is None:
                sys.exit(
                    f"{BLAD_POBIERANIA}: {narzedzie} po {len(PRZERWY_S) + 1} próbach ({awaria}); "
                    "to awaria pobierania narzędzia, nie wynik modelu."
                )
            print(f"UWAGA: pobieranie {narzedzie} zawiodło ({awaria}); ponawiam za {przerwa:g} s.", file=sys.stderr)
            time.sleep(przerwa)


def pobierz(url: str, cel: Path) -> None:
    """Zapisuje treść spod ``url`` w ``cel``, z ponowieniem chwilowej awarii; inny błąd HTTP kończy proces od razu."""

    def proba() -> None:
        try:
            with urllib.request.urlopen(url, timeout=120) as odpowiedz, cel.open("wb") as plik:
                shutil.copyfileobj(odpowiedz, plik)
        except urllib.error.HTTPError as blad:
            if blad.code < 500 and blad.code != 429:
                sys.exit(f"{BLAD_POBIERANIA}: {url} odpowiada HTTP {blad.code} {blad.reason}; to nie wynik modelu.")
            raise ChwilowaAwaria(f"HTTP {blad.code} {blad.reason}") from blad
        except (OSError, http.client.HTTPException) as blad:
            raise ChwilowaAwaria(f"{type(blad).__name__}: {blad}") from blad

    z_ponowieniem(url, proba)
