"""Zapisuje syntetyczne Wzorce w kształcie Wzorców taty; użyj, gdy benchmark, weryfikacja w Excelu albo CI nie ma prawdziwych Wzorców.

Użycie (z katalogu repozytorium):

    python tools/syntetyczne_wzorce.py FOLDER [--data-rows N]

Do ``FOLDER`` trafiają trzy Wzorce pod nazwami, pod którymi leżą w ``config`` (folder nadaje się
dla ``tools/benchmark_przebiegu.py --templates-dir``), oraz ``wykonawcy.yaml``: Lista Wykonawców
z 20 syntetycznymi Wykonawcami. Wzorców taty nie ma w repozytorium, a CI potrzebuje skoroszytów,
których wczytanie i zapis kosztują tyle samo.

Wzorzec rozliczenia pracownika i Wzorzec pliku zbiorczego mają kształt Wzorców taty (spec #141):
nagłówki w wierszu 17, ~10 tys. sformatowanych Wierszy danych (18..10093), ~500 tys. komórek,
~50 tys. formuł zapisanych jako wspólne (wzór co 64 wiersze) z zapisanymi wartościami,
``calcChain`` z każdą komórką z formułą, ``sharedStrings``, jedno odwołanie zewnętrzne
(``xl/externalLinks/*``), scalenia, pasy stylów i 483 wiersze zer w N:V i X. Nie wszystkie
wiersze mają komórki w A i B, jak u taty. Wzorzec rozliczenia pracownika ma, jak u taty,
komentarz komórki, więc relacje arkusza (``rId1`` rysunek VML, ``rId2`` komentarze). openpyxl nie zapisuje wspólnych formuł ani
``calcChain``, więc generator pisze XML części zip sam. Wszystkie trzy Wzorce otwierają się, jak
Wzorce taty od #465, w lewym górnym rogu arkusza (górna lewa komórka i zaznaczenie A1) w powiększeniu 75%.

Etykiety A:K, AQ:AY i opisy wierszy 13–16 są takie jak u taty; usługi N:AP, stawki, formuły
i odwołanie zewnętrzne są syntetyczne. Generator jest deterministyczny: te same argumenty dają
te same bajty, więc lustro benchmarku zbudowane z nich ma stały odcisk.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from atrapy.wzorce import FULL_DATA_ROWS, SHARED_FORMULA_ROWS, write_synthetic_templates


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="Folder na Wzorce i Listę Wykonawców.")
    parser.add_argument(
        "--data-rows",
        type=int,
        default=FULL_DATA_ROWS,
        help=f"Liczba sformatowanych Wierszy danych (domyślnie {FULL_DATA_ROWS}, jak u taty).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.data_rows < 2 * SHARED_FORMULA_ROWS:
        print(f"--data-rows musi wynosić co najmniej {2 * SHARED_FORMULA_ROWS}.")
        return 2
    write_synthetic_templates(args.directory.expanduser().resolve(), args.data_rows)
    print(f"Syntetyczne Wzorce w {args.directory}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
