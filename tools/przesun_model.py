"""Przelicza skróty kodu w model/definicje.json skilla verify-*; użyj, gdy model albo eksplorator skilla znów opisuje zmieniony kod.

Rozjazd modelu z kodem (``tools/lib/rozjazd_modelu.py``) porównuje kod na dysku ze skrótami z ``model/definicje.json``
skilla. Narzędzie zapisuje tam skróty bieżącego kodu, dopiero po krokach „Bring the model in line” ze ``SKILL.md``
skilla, i drukuje zmienione definicje: wpisz je z tym, co zmieniło się w modelu, w opis commitu. Nowa definicja to nazwa
z dowolnym skrótem (np. ``""``) dopisana do pliku przed uruchomieniem. Definicja, której nie ma w kodzie, kończy się
kodem 1 bez zapisu: popraw jej nazwę w pliku.

    .venv/bin/python tools/przesun_model.py verify-urwane-uruchomienie
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import repo
import rozjazd_modelu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("skill", help=f"Nazwa skilla z {rozjazd_modelu.DEFINICJE}, np. verify-urwane-uruchomienie.")
    parser.add_argument("--root", type=Path, default=repo.ROOT, help="Korzeń repozytorium (domyślnie ten checkout).")
    args = parser.parse_args(argv)
    skill = args.root / ".agents" / "skills" / args.skill
    if skill not in rozjazd_modelu.skille(args.root):
        known = ", ".join(path.name for path in rozjazd_modelu.skille(args.root))
        print(f"PRZESUNIĘCIE FAIL | {args.skill} nie ma {rozjazd_modelu.DEFINICJE}; skille z modelem: {known}")
        return 1
    try:
        moved = rozjazd_modelu.przesun(skill, args.root)
    except ValueError as error:
        print(f"PRZESUNIĘCIE FAIL | {error}")
        return 1
    print("\n".join(f"przeliczona: {name}" for name in moved))
    print(f"PRZESUNIĘCIE OK | {args.skill} | przeliczone {len(moved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
