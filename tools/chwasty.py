"""Zakłada albo uzupełnia issues „Chwast: R-KOD” dla każdego kodu korzenia z Ważnym w 2 PR-ach; --bez-zapisu tylko je podaje.

Przechodzi rejestr korzeni od wdrożenia szablonu werdyktu na ``origin/main`` (ADR 0031) i dla każdego kodu
z wystąpieniami w co najmniej 2 różnych PR-ach robi to samo, co ``tools/scal_pr.py --werdykt`` przy publikacji
werdyktu z tym kodem (``rejestr_korzeni.settle``): zakłada issue z szablonu albo zmienia tabelę wystąpień otwartego.
Jednorazowe uzupełnienie wstecz po wdrożeniu wykrywania powrotu, a potem polecenie na zgubioną publikację (dopisek
``UWAGA: chwastów nie sprawdzono`` w linii ``WERDYKT OK``).

Linia ``CHWAST | …`` na każdą akcję albo ostrzeżenie, a na końcu ``CHWASTY OK | <liczba wystąpień> wystąpień, chwasty:
<kody>``. Z ``--bez-zapisu`` niczego nie zakłada ani nie zmienia, tylko podaje akcje (``bez zapisu: …``). Błąd
GitHuba albo Gita kończy się linią ``CHWASTY FAIL`` i kodem 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import github
import rejestr_korzeni
from repo import MAIN, REMOTE, ROOT
import repo
import szablon_werdyktu
import werdykt_pr

EXAMPLES = """\
    .venv/bin/python tools/chwasty.py --bez-zapisu   # tylko podaje issues do założenia i zmiany
    .venv/bin/python tools/chwasty.py                # zakłada i uzupełnia issues chwastów
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bez-zapisu", action="store_true", help="Niczego nie zapisuj na GitHubie, tylko podaj akcje.")
    args = parser.parse_args(argv)
    try:
        repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{MAIN}:refs/remotes/{REMOTE}/{MAIN}", timeout=github.LIMIT_S).check_returncode()
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        found = rejestr_korzeni.read(repository, werdykt_pr.deployment(MAIN, szablon_werdyktu.ADR))
        lines = rejestr_korzeni.settle(found, None, repository, MAIN, write=not args.bez_zapisu)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, github.BladApi) as error:
        print(f"CHWASTY FAIL | {error}")
        return 1
    for line in lines:
        print(line)
    print(f"CHWASTY OK | {len(found)} wystąpień, chwasty: {', '.join(rejestr_korzeni.returned(found)) or 'brak'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
