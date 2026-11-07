"""Narzędzia TLC modeli TLA+ skilli ``verify-*``: przypięte wersje Javy (``jdk4py``) i ``tla2tools.jar``, ich pobieranie i instalacja.

Jedyne miejsce tych wersji i jedyna droga pobrania: ``java`` i ``jar`` kładą narzędzia w katalogu podręcznym ``KATALOG``,
a bierze je stamtąd ``tools/lib/model_tlc.py``, jedyna droga TLC skryptów modeli. Zadania CI, które uruchamiają modele
(Mutation checks w ``ci.yml`` i skrypty mutacji skilli w ``mutacje-nocne.yml``), trzymają ten katalog w cache z kluczem
od skrótu tego pliku, więc nowa wersja, suma albo sposób instalacji to nowy klucz. Zapisują go tylko wtedy, gdy ``tools/ci/zapis_narzedzi_tlc.py`` zobaczy w nim jar o przypiętej sumie
(``ma_przypieta_sume``), bo klucz raz zapisany z katalogiem bez jara dawałby każdemu runowi trafienie bez jara (#940).

Chwilowa awaria źródła (błąd sieci, HTTP 5xx albo 429) nie kończy sprawdzenia: ``z_ponowieniem`` ponawia próbę po
przerwach ``PRZERWY_S``, bo jedno 504 GitHub Releases czerwieniło CI PR-ów i noc na ``main`` (#930). Gdy zawiedzie
ostatnia próba albo źródło odpowie innym błędem HTTP, proces kończy się linią z ``BLAD_POBIERANIA``, żeby log nie mylił
awarii pobierania z wynikiem modelu.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import http.client
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import potomne

__all__ = [
    "BLAD_POBIERANIA",
    "JDK4PY",
    "KATALOG",
    "PRZERWY_S",
    "TLA_SHA256",
    "TLA_URL",
    "TLA_WERSJA",
    "ChwilowaAwaria",
    "jar",
    "jar_tla",
    "java",
    "ma_przypieta_sume",
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
# Katalog podręczny narzędzi względem korzenia repozytorium, ignorowany przez Gita; ``path`` kroków cache w workflowach.
KATALOG = Path(".verification") / "formal-aktualizacja"


def jar_tla(katalog: Path) -> Path:
    """Miejsce ``tla2tools.jar`` przypiętej wersji w katalogu podręcznym ``katalog``."""

    return katalog / f"tla2tools-{TLA_WERSJA}.jar"


def ma_przypieta_sume(plik: Path) -> bool:
    """Czy ``plik`` istnieje i ma przypiętą sumę SHA-256 ``tla2tools.jar``."""

    return plik.is_file() and hashlib.sha256(plik.read_bytes()).hexdigest() == TLA_SHA256


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


def java(katalog: Path) -> str:
    """Java z przypiętego ``jdk4py`` w katalogu podręcznym ``katalog``; instaluje je za pierwszym razem."""

    target = katalog / "jdk"
    if not (target / "jdk4py").is_dir():
        command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet"]
        if potomne.run([sys.executable, "-m", "pip", "--version"], cwd=Path.cwd()).returncode != 0:
            uv = shutil.which("uv")
            if uv is None:
                sys.exit("BŁĄD: ten Python nie ma pip, a uv nie jest dostępne; nie da się zainstalować jdk4py.")
            command = [uv, "pip", "install", "--python", sys.executable, "--quiet"]

        def install() -> None:
            shutil.rmtree(target, ignore_errors=True)
            done = potomne.run([*command, "--target", str(target), JDK4PY], cwd=Path.cwd(), echo=True)
            if done.returncode != 0:
                raise ChwilowaAwaria(f"instalacja skończyła się kodem {done.returncode}")

        z_ponowieniem(JDK4PY, install)
    command = [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(target)!r}); import jdk4py; print(jdk4py.JAVA)"]
    found = potomne.run(command, cwd=Path.cwd())
    if found.returncode != 0:
        raise subprocess.CalledProcessError(found.returncode, command, found.stdout, found.stderr)
    return found.stdout.strip()


def jar(katalog: Path) -> Path:
    """``tla2tools.jar`` przypiętej wersji w katalogu podręcznym ``katalog``, sprawdzony sumą SHA-256; pobiera go, gdy go
    nie ma albo ma inną sumę."""

    found = jar_tla(katalog)
    if not ma_przypieta_sume(found):
        katalog.mkdir(parents=True, exist_ok=True)
        partial = found.with_suffix(".part")
        pobierz(TLA_URL, partial)
        if not ma_przypieta_sume(partial):
            partial.unlink()
            sys.exit(f"{BLAD_POBIERANIA}: {TLA_URL} ma inną sumę SHA-256 niż przypięta; to nie wynik modelu.")
        os.replace(partial, found)
    return found
