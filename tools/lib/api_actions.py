"""API GitHuba narzędzi CI: jedna kopia odpowiedzi na komputerze i rezerwa wspólnego limitu zapytań.

``Api`` pyta po jednym, a odpowiedź 5xx (502, 503) dostaje ``PROBY_API`` prób z przerwą ``PRZERWA_API_S``.
Odpowiedź, która już się nie zmieni (lista runów zamkniętego dnia, zadania zakończonego runu, log), zapisuje się
w ``api`` kopii komputera (``kopia_komputera``: ``~/.cache/maximiseart``, albo katalog ze zmiennej ``MAXIMISEART_KOPIA``,
którą testy ustawiają na katalog tymczasowy, także dla podprocesów), wspólnej dla każdego checkoutu, wątku i biegu,
więc pyta się tylko o nowe.

Wątki na komputerze dzielą limit zapytań REST tokenu (5000 na godzinę). ``ZRezerwa`` przed każdym zapytaniem bierze
zapas z ``zapas_maca`` (``gh api rate_limit``, które do limitu się nie liczy, odczytane dla wszystkich procesów
najwyżej co ``ODSWIEZ_ZAPAS_S``) i poniżej swojej rezerwy odmawia ``PonizejRezerwy`` z godziną resetu, zanim
zapyta. Narzędzia pomiarowe stają przy ``REZERWA_POMIARU``, a ``scal_pr`` i ``ponow_ci`` dopiero przy
``REZERWA_SCALANIA``, więc pomiar nie zużyje zapytań, których potrzebuje merge. W GitHub Actions run ma swój token,
więc rezerwy tam nie ma.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import contextlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.parse

from github import REPO, BladApi, GitHub, gh

__all__ = [
    "KOPIA",
    "ODSWIEZ_ZAPAS_S",
    "PROBY_API",
    "PRZERWA_API_S",
    "REZERWA_POMIARU",
    "REZERWA_SCALANIA",
    "STRONA",
    "Api",
    "PonizejRezerwy",
    "ZRezerwa",
    "ZMIENNA_KOPII",
    "Zapas",
    "kopia_komputera",
    "odmowa",
    "runy",
    "zapas_maca",
]

STRONA = 100
# Odpowiedź 5xx API Actions (502, 503) mija po chwili: tyle prób z przerwą.
PROBY_API = 5
PRZERWA_API_S = 20.0
KOPIA = Path(".cache") / "maximiseart"
ZMIENNA_KOPII = "MAXIMISEART_KOPIA"
REZERWA_POMIARU = 1500
REZERWA_SCALANIA = 300
ODSWIEZ_ZAPAS_S = 20.0


@dataclass(frozen=True)
class Zapas:
    pozostalo: int
    reset: float


def kopia_komputera() -> Path:
    return Path(os.environ.get(ZMIENNA_KOPII) or Path.home() / KOPIA)


def _rate_limit() -> str:
    return gh("api", "rate_limit")


def _zapisz(plik: Path, dane: bytes) -> None:
    plik.parent.mkdir(parents=True, exist_ok=True)
    tymczasowy = plik.with_name(f"{plik.name}.{os.getpid()}.zapis")
    tymczasowy.write_bytes(dane)
    tymczasowy.replace(plik)


def _zapisany(plik: Path, teraz: float) -> Zapas | None:
    try:
        stan = json.loads(plik.read_text(encoding="utf-8"))
        zapas = Zapas(int(stan["pozostalo"]), float(stan["reset"]))
        swiezy = teraz - float(stan["odczyt"]) < ODSWIEZ_ZAPAS_S
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return zapas if swiezy else None


def zapas_maca(plik: Path | None = None, *, odczyt: Callable[[], str] = _rate_limit, teraz: Callable[[], float] = time.time) -> Zapas | None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return None
    plik = plik or kopia_komputera() / "zapas-api.json"
    if (zapisany := _zapisany(plik, teraz())) is not None:
        return zapisany
    try:
        core = json.loads(odczyt())["resources"]["core"]
        zapas = Zapas(int(core["remaining"]), float(core["reset"]))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        return None
    with contextlib.suppress(OSError):
        _zapisz(plik, json.dumps({"odczyt": teraz(), "pozostalo": zapas.pozostalo, "reset": zapas.reset}).encode("utf-8"))
    return zapas


def odmowa(rezerwa: int, zapas: Callable[[], Zapas | None] = zapas_maca) -> str | None:
    biezacy = zapas()
    if biezacy is None or biezacy.pozostalo >= rezerwa:
        return None
    reset = datetime.fromtimestamp(biezacy.reset).astimezone()
    return f"zapas GitHub API {biezacy.pozostalo} zapytań poniżej rezerwy {rezerwa}: ponów po resecie limitu o {reset:%H:%M}"


class PonizejRezerwy(BladApi):
    pass


@dataclass(frozen=True)
class ZRezerwa:
    github: GitHub
    rezerwa: int
    zapas: Callable[[], Zapas | None] = zapas_maca

    def _sprawdz(self, sciezka: str) -> None:
        if (powod := odmowa(self.rezerwa, self.zapas)) is not None:
            raise PonizejRezerwy(f"gh api {sciezka}", powod)

    def json(self, sciezka: str) -> Any:
        self._sprawdz(sciezka)
        return self.github.json(sciezka)

    def bajty(self, sciezka: str) -> bytes:
        self._sprawdz(sciezka)
        return self.github.bajty(sciezka)

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self._sprawdz(sciezka)
        return self.github.wyslij(metoda, sciezka, tresc)


class Api:
    """``gh api`` z odpowiedziami w ``kopia`` (domyślnie ``api`` w ``kopia_komputera``); ``trwala`` mówi, czy odpowiedź
    już się nie zmieni (wtedy ją zapisuje)."""

    def __init__(self, github: GitHub, kopia: Path | None = None) -> None:
        self.katalog = kopia or kopia_komputera() / "api"
        self.katalog.mkdir(parents=True, exist_ok=True)
        self.github = github
        self.zapytania = 0

    def json(self, sciezka: str, trwala: Callable[[Any], bool]) -> Any:
        plik = self._plik(sciezka, ".json")
        if plik.is_file():
            return json.loads(plik.read_text(encoding="utf-8"))
        dane = self._zapytaj(lambda: self.github.json(sciezka))
        if trwala(dane):
            _zapisz(plik, json.dumps(dane).encode("utf-8"))
        return dane

    def bajty(self, sciezka: str) -> bytes:
        """Bajty odpowiedzi, która już się nie zmieni (zip artefaktu, log zadania zakończonego runu)."""

        plik = self._plik(sciezka, ".bin")
        if plik.is_file():
            return plik.read_bytes()
        dane: bytes = self._zapytaj(lambda: self.github.bajty(sciezka))
        _zapisz(plik, dane)
        return dane

    def _plik(self, sciezka: str, rozszerzenie: str) -> Path:
        return self.katalog / f"{urllib.parse.quote(sciezka, safe='')}{rozszerzenie}"

    def _zapytaj(self, zapytanie: Callable[[], Any]) -> Any:
        for proba in range(1, PROBY_API + 1):
            self.zapytania += 1
            try:
                return zapytanie()
            except (BladApi, subprocess.TimeoutExpired) as blad:
                if proba == PROBY_API or (isinstance(blad, BladApi) and "HTTP 5" not in blad.stderr):
                    raise
                time.sleep(PRZERWA_API_S)
        raise AssertionError("pętla prób kończy się odpowiedzią albo wyjątkiem")


def runy(api: Api, od: date, do: date, dzis: date) -> list[dict[str, Any]]:
    """Runy ``ci.yml`` utworzone w dniach ``od``–``do`` (UTC), po dniu, bo lista API kończy się na 1000 runów."""

    znalezione = []
    dzien = od
    while dzien <= do:
        zamkniety = dzien < dzis

        def trwala(dane: dict[str, Any], zamkniety: bool = zamkniety) -> bool:
            return zamkniety and all(r["status"] == "completed" for r in dane["workflow_runs"])

        for strona in range(1, 100):
            partia = api.json(f"{REPO}/actions/workflows/ci.yml/runs?created={dzien.isoformat()}&per_page={STRONA}&page={strona}", trwala)["workflow_runs"]
            znalezione += partia
            if len(partia) < STRONA:
                break
        dzien += timedelta(days=1)
    return znalezione
