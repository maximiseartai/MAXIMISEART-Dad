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


def _scopes(*names: str) -> tuple[str, tuple[str, ...]]:
    return ("explore_outbox.py", tuple(argument for name in names for argument in ("--scope", name)))


def _configs(*names: str) -> tuple[str, tuple[str, ...]]:
    return ("sprawdz_model_kolejki.py", tuple(argument for name in names for argument in ("--config", name)))


# Jednostka to skrypt skilla z argumentami; każda biegnie od świeżego startu. Część bierze kolejne jednostki po ich
# liczbie, nie po czasie, więc kolejność przeplata ciężkie jednostki z lekkimi. Na czasach jednostek z runu PR
# 43290270296 (Windows CI, 12.11: ``archiwum-diagnoza`` 265 s, grupa z ``postep`` 193 s, ``archiwum`` 146 s, grupa
# z ``diagnoza`` 136 s, konfiguracja ``starsza`` 97 s, pozostałe 58–107 s) ta kolejność daje przy czterech i pięciu
# częściach (tyle plan bierze na PR) najdłuższą część 323 s; najlepsza z wszystkich kolejności tych jednostek.
# Najdłuższa niepodzielna jednostka to zakres ``archiwum-diagnoza``.
UNITS = (
    _scopes("archiwum-diagnoza"),
    _configs("archiwum", "logi", "odczyt"),
    _scopes("watek-okresu", "watek-okresu-lista", "zgloszenie", "zgloszenie-wrocilo", "zgloszenie-lista"),
    _configs("okres", "diagnoza", "zgloszenie", "znane"),
    _scopes("diagnoza", "diagnoza-odczyt", "archiwum-puste-repo"),
    _configs("starsza"),
    _scopes("postep", "archiwum-lista", "nowe-issue", "nowe-issue-lista", "znane-issue"),
    _configs("archiwum-lista", "odmowa-tresci", "dwa-procesy", "dwie-kolejki"),
    _scopes("archiwum"),
    _configs("postep", "puste-repo", "nowe"),
)


def units(environment: Mapping[str, str] = os.environ) -> tuple[tuple[str, tuple[str, ...]], ...]:
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
