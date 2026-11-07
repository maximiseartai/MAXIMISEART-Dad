"""Benchmark Przebiegu rozliczeń za poleceniem ``tools/benchmark_przebiegu.py``.

- ``lustro``: lustro folderów taty dla scenariusza (Rejestr zleceń, Przygotowanie pliku
  zbiorczego, wpisy taty w ``N:AT``),
- ``uruchomienie``: jedno uruchomienie Przebiegu rozliczeń na lustrze i podział jego czasu ściany,
- ``referencja``: zamrożenie wyniku referencyjnego z commita i bramka poprawności,
- ``pomiar``: kilka uruchomień, wyłączna blokada pomiarów i rekord dziennika,
- ``dziennik``: dziennik JSONL, komentarz Markdown i straż czasu w CI.

Benchmark mierzy kod tego checkoutu: ``src`` trafia na początek ``sys.path`` przed
importem ``rozliczenia``, bo pakiet jest zainstalowany w trybie edytowalnym z głównego
checkoutu.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from repo import ROOT

DEFAULT_DIRECTORY = ROOT / ".benchmark"
SCRIPT = Path("tools", "uruchom_proces.py")


class BenchmarkError(Exception):
    """Pomiar nie może się odbyć; komunikat nie zawiera danych z lustra."""
