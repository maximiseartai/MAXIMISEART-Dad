"""Rozjazd modelu z kodem (``tools/lib/rozjazd_modelu.py``) porównuje kod na dysku ze skrótami z ``model/definicje.json``
skilla. Narzędzie zapisuje tam skróty bieżącego kodu, dopiero po krokach „Bring the model in line” ze ``SKILL.md``
skilla, i drukuje zmienione definicje: wpisz je z tym, co zmieniło się w modelu, w opis commitu. Nowa definicja to nazwa
z dowolnym skrótem (np. ``""``) dopisana do pliku przed uruchomieniem. Definicja, której nie ma w kodzie, kończy się
kodem 1 bez zapisu: popraw jej nazwę w pliku.

    .venv/bin/python tools/przesun_model.py verify-urwane-uruchomienie
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import repo
import rozjazd_modelu

OPIS = "Przelicza skróty kodu w model/definicje.json skilla verify-*; użyj, gdy model albo eksplorator skilla znów opisuje zmieniony kod."
SCAL = (
    "Sterownik merge'a gita (merge=model-skilla w .gitattributes, ustawia go tools/setup_worktree.py): scala pliki definicji "
    "BAZA NASZA ICH do NASZA. Definicję bierze ze strony, która zmieniła jej skrót, a skrót zmieniony po obu stronach liczy "
    "na drzewie scalenia HEAD z gałęzią z git merge; inna zmiana kluczy po obu stronach zostaje konfliktem."
)
GALAZ_MERGE = "GITHEAD_"
WEWNATRZ = "MAXIMISEART_SCALANIE_MODELU"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS)
    parser.add_argument("skill", nargs="?", help=f"Nazwa skilla z {rozjazd_modelu.DEFINICJE}, np. verify-urwane-uruchomienie.")
    parser.add_argument("--root", type=Path, default=repo.ROOT, help="Korzeń repozytorium (domyślnie ten checkout).")
    parser.add_argument("--scal", nargs=4, metavar=("BAZA", "NASZA", "ICH", "SCIEZKA"), help=SCAL)
    args = parser.parse_args(argv)
    if args.scal is not None:
        return _merge(*args.scal)
    if args.skill is None:
        parser.error("podaj skill albo --scal")
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


def _merge(base: str, ours: str, theirs: str, path: str) -> int:
    root = Path.cwd()
    with ExitStack() as files:

        def merge_tree(paths: list[str]) -> Path | None:
            heads = [name.removeprefix(GALAZ_MERGE) for name in os.environ if name.startswith(GALAZ_MERGE)]
            if len(heads) != 1 or os.environ.get(WEWNATRZ):
                return None
            os.environ[WEWNATRZ] = "1"
            merged = repo.merge_tree(root, "HEAD", heads[0])
            if set(paths) & set(merged.conflicts):
                return None
            folder = Path(files.enter_context(tempfile.TemporaryDirectory(prefix="scalanie-modelu-")))
            for name in paths:
                if (data := repo.blob(root, merged.tree, name)) is not None:
                    (folder / name).parent.mkdir(parents=True, exist_ok=True)
                    (folder / name).write_bytes(data)
            return folder

        try:
            recomputed = rozjazd_modelu.scal(Path(base), Path(ours), Path(theirs), merge_tree)
        except ValueError as error:
            repo.succeeds(root, "merge-file", "-L", "HEAD", "-L", "baza", "-L", "scalana", ours, base, theirs)
            print(f"SCALENIE MODELU KONFLIKT | {path} | {error}", file=sys.stderr)
            return 1
    on_tree = f"przeliczone na drzewie scalenia: {', '.join(recomputed)}" if recomputed else "bez przeliczenia"
    print(f"SCALENIE MODELU OK | {path} | {on_tree}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
