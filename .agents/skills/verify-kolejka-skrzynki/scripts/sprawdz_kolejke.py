"""Podstawa skilla w CI: model TLA+ Kolejki Skrzynki (TLC) i sprawdzenie prawdziwego kodu, oba do końca.

Uruchamia po kolei jednostki z ``UNITS`` (zakresy ``explore_outbox.py`` i ``sprawdz_model_kolejki.py``) tym samym
Pythonem, z ich wyjściem, i kończy się linią ``KOLEJKA SKRZYNKI OK`` albo ``KOLEJKA SKRZYNKI: PADŁO <jednostki>`` z
kodem 1. W CI część ``MUTACJE_CZESC=k/n`` (``ci-czesci`` w ``SKILL.md``) uruchamia tylko swój kawałek ``UNITS``
(``skrypt_skilla.part``).

    .venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_kolejke.py
    py -3 .agents\\skills\\verify-kolejka-skrzynki\\scripts\\sprawdz_kolejke.py
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import part

# Jednostka to skrypt skilla z argumentami; każda biegnie od świeżego startu. Na Macu Maksa (2026-11-04) zakresy
# ``archiwum`` i ``archiwum-diagnoza`` trwają razem ok. 53 s, ``watek-okresu`` ok. 22 s, ``diagnoza``,
# ``diagnoza-odczyt`` i ``archiwum-puste-repo`` razem ok. 37 s, cztery pozostałe zakresy razem ok. 8 s, a model ok.
# 45 s, więc przy trzech częściach pierwsza bierze zakresy Archiwum, druga dwie następne jednostki, a trzecia resztę i
# model (ok. 53 s, 59 s i 53 s).
UNITS = (
    ("explore_outbox.py", ("--scope", "archiwum", "--scope", "archiwum-diagnoza")),
    ("explore_outbox.py", ("--scope", "watek-okresu")),
    ("explore_outbox.py", ("--scope", "diagnoza", "--scope", "diagnoza-odczyt", "--scope", "archiwum-puste-repo")),
    (
        "explore_outbox.py",
        (
            "--scope",
            "zgloszenie",
            "--scope",
            "zgloszenie-wrocilo",
            "--scope",
            "nowe-issue",
            "--scope",
            "znane-issue",
        ),
    ),
    ("sprawdz_model_kolejki.py", ()),
)


def units(environment: Mapping[str, str] = os.environ) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Jednostki tego przebiegu: wszystkie albo w CI kawałek ``MUTACJE_CZESC=k/n`` z ``UNITS``."""

    return part(UNITS, environment)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None).parse_args(argv)
    try:
        chosen = units()
    except ValueError as problem:
        print(f"KOLEJKA SKRZYNKI: PADŁO ({problem})")
        return 1
    here = Path(__file__).resolve().parent
    failed = [
        " ".join((name, *arguments))
        for name, arguments in chosen
        if subprocess.run([sys.executable, str(here / name), *arguments], check=False).returncode != 0
    ]
    print()
    if failed:
        print(f"KOLEJKA SKRZYNKI: PADŁO {', '.join(failed)}")
        return 1
    print("KOLEJKA SKRZYNKI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
