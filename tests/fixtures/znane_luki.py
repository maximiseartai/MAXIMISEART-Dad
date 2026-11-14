"""Znane luki strażnika (ADR 0034): znana postać, którą strażnik przepuszcza, jest próbką w jego teście.

Strażnik trzyma próbki w słowniku ``ZNANE_LUKI`` swojego testu („klasa: postać” → kod modułu), a test puszcza każdą przez
prawdziwe mechanizmy strażnika: ``ruff check`` z konfiguracją repozytorium na ścieżce sondy, ``mypy`` z konfiguracją
``pyproject.toml``, gdy strażnik stoi na typie, i własne sprawdzenie strażnika na module próbki. Próbka przechodzi przez
każdy z nich, a gdy któryś zaczyna ją łapać, ``assert_znane_luki`` każe usunąć ją ze ``ZNANE_LUKI``. Próbki to luki
znane, nie pełna lista postaci ani klas: nowo znaleziona luka staje się nową próbką albo zamyka ją konstrukcja (typ,
zakaz ruff, odmowa w biegu).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

wymaga_ruff_i_mypy = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None or importlib.util.find_spec("mypy") is None,
    reason="znane luki ocenia prawdziwy ruff i mypy z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt",
)
wymaga_ruff = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="znane luki ocenia prawdziwy ruff z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt",
)


def zapisz(probki: Mapping[str, str], katalog: Path) -> dict[str, Path]:
    """Plik modułu każdej próbki w ``katalog``."""

    pliki = {opis: katalog / f"znana_luka_{numer}.py" for numer, opis in enumerate(probki)}
    for opis, plik in pliki.items():
        plik.write_text(probki[opis], encoding="utf-8")
    return pliki


def modul(plik: Path) -> ModuleType:
    """Moduł wykonany z pliku próbki, dla sprawdzenia strażnika, które rozwiązuje nazwy w module."""

    spec = importlib.util.spec_from_file_location(plik.stem, plik)
    assert spec is not None and spec.loader is not None, plik
    wykonany = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wykonany)
    return wykonany


def ruff(pliki: Mapping[str, Path], sonda: Path) -> dict[str, list[str]]:
    """Zgłoszenia ruff dla każdej próbki: próbka jako plik ``sonda``, więc z konfiguracją jej katalogu i bez
    ``--ignore-noqa``, jak w CI."""

    zgloszenia: dict[str, list[str]] = {opis: [] for opis in pliki}
    for opis, plik in pliki.items():
        sprawdzenie = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json", "--stdin-filename", str(sonda), "-"],
            input=plik.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            check=False,
        )
        assert sprawdzenie.stderr == "", sprawdzenie.stderr
        zgloszenia[opis] += [f"ruff {finding['code']}: {finding['message']}" for finding in json.loads(sprawdzenie.stdout)]
    return zgloszenia


def ruff_i_mypy(pliki: Mapping[str, Path], sonda: Path, platformy: Sequence[str] = ()) -> dict[str, list[str]]:
    """Zgłoszenia ruff (``ruff``) i mypy (jedno uruchomienie na wszystkie pliki, z własnym cache) dla każdej próbki.
    Bez ``platformy`` mypy biegnie dla systemu, na którym biegnie test; z ``platformy`` raz z ``--platform`` każdej
    z nich, a zgłoszenie ma postać ``mypy[platforma] błąd``."""

    zgloszenia = ruff(pliki, sonda)
    katalog = {plik.parent for plik in pliki.values()}
    assert len(katalog) == 1, katalog
    cache = katalog.pop() / ".mypy_cache"
    opisy = {plik.name: opis for opis, plik in pliki.items()}
    for platforma in platformy or (None,):
        wybor = ["--platform", platforma, "--cache-dir", str(cache / platforma)] if platforma else ["--cache-dir", str(cache)]
        mypy = subprocess.run(
            [sys.executable, "-m", "mypy", "--no-error-summary", *wybor] + [str(plik) for plik in pliki.values()],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            check=False,
        )
        assert mypy.returncode in (0, 1) and mypy.stderr == "", mypy.stdout + mypy.stderr
        obce = []
        for linia in mypy.stdout.splitlines():
            miejsce, _, blad = linia.partition(": error: ")
            if blad and (probka := opisy.get(Path(miejsce.rsplit(":", 1)[0]).name)) is not None:
                zgloszenia[probka].append(f"mypy[{platforma}] {blad}" if platforma else f"mypy {blad}")
            elif blad:
                obce.append(linia)
        assert obce == [], "mypy zgłasza błąd poza próbkami:\n" + "\n".join(obce)
    return zgloszenia


def assert_znane_luki(zgloszenia: Mapping[str, Sequence[str]], test: str) -> None:
    """Żadna próbka ``ZNANE_LUKI`` testu ``test`` nie ma zgłoszenia mechanizmu strażnika."""

    zlapane = {opis: lista for opis, lista in zgloszenia.items() if lista}

    assert zlapane == {}, "\n".join(
        [
            f"strażnik łapie już te znane luki z ZNANE_LUKI w {test}, więc nie są lukami: usuń ich próbki z ZNANE_LUKI "
            "(a gdy zgłoszenie dotyczy błędu samej próbki, popraw próbkę)",
            *(f"- {opis}: {'; '.join(lista)}" for opis, lista in zlapane.items()),
        ]
    )
