"""API Actions z odpowiedziami na dysku dla pomiarów CI (``tools/pomiar_ci.py``, ``tools/cien_podstaw.py``).

Zapytania idą po jednym, a odpowiedź 5xx (502, 503) dostaje ``PROBY_API`` prób z przerwą ``PRZERWA_API_S``.
Odpowiedź, która już się nie zmieni, zapisuje się w ``<katalog>/api``, więc ponowny bieg pyta tylko o nowe.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.parse

from github import REPO, BladApi, GitHub

__all__ = ["PROBY_API", "PRZERWA_API_S", "STRONA", "Api", "runy"]

STRONA = 100
# Odpowiedź 5xx API Actions (502, 503) mija po chwili: tyle prób z przerwą.
PROBY_API = 5
PRZERWA_API_S = 20.0


class Api:
    """``gh api`` z odpowiedziami na dysku; ``trwala`` mówi, czy odpowiedź już się nie zmieni (wtedy ją zapisuje)."""

    def __init__(self, katalog: Path, github: GitHub) -> None:
        self.katalog = katalog / "api"
        self.katalog.mkdir(parents=True, exist_ok=True)
        self.github = github
        self.zapytania = 0

    def json(self, sciezka: str, trwala: Callable[[Any], bool]) -> Any:
        plik = self._plik(sciezka, ".json")
        if plik.is_file():
            return json.loads(plik.read_text(encoding="utf-8"))
        dane = self._zapytaj(lambda: self.github.json(sciezka))
        if trwala(dane):
            self._zapisz(plik, json.dumps(dane).encode("utf-8"))
        return dane

    def bajty(self, sciezka: str) -> bytes:
        """Bajty odpowiedzi, która już się nie zmieni (zip artefaktu, log zadania zakończonego runu)."""

        plik = self._plik(sciezka, ".bin")
        if plik.is_file():
            return plik.read_bytes()
        dane: bytes = self._zapytaj(lambda: self.github.bajty(sciezka))
        self._zapisz(plik, dane)
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

    @staticmethod
    def _zapisz(plik: Path, dane: bytes) -> None:
        tymczasowy = plik.with_suffix(".pobieranie")
        tymczasowy.write_bytes(dane)
        tymczasowy.replace(plik)


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
