"""Porównuje znaczeniowo dwa Foldery rozliczeń pracowników (spec #141); użyj jako bramki, gdy zmiana silnika ma dać te same rozliczenia.

Porównanie znaczeniowe dwóch Folderów rozliczeń pracowników: bramka poprawności wspinaczki (spec #141).

Użycie (z katalogu repozytorium):

    python tools/porownanie_rozliczen.py FOLDER_REFERENCYJNY FOLDER_KANDYDATA
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import porownanie_znaczeniowe


def main(argv: list[str] | None = None) -> int:
    # Co znaczy „ten sam wynik”, mówi docstring biblioteki, więc --help bierze go stamtąd.
    parser = argparse.ArgumentParser(description=f"{__doc__}\n{porownanie_znaczeniowe.__doc__}", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path, help="Folder rozliczeń pracowników z wyniku referencyjnego.")
    parser.add_argument("candidate", type=Path, help="Folder rozliczeń pracowników kandydata.")
    args = parser.parse_args(argv)
    differences = porownanie_znaczeniowe.compare_worker_settlements(args.reference, args.candidate)
    print(json.dumps(differences, ensure_ascii=False))
    return 0 if not any(differences.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
