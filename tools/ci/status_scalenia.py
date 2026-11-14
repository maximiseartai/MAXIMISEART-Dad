"""Werdykt scalenia każdego otwartego PR z jego bazą jako status commita na HEAD PR.

CI na PR sprawdza scalenie z bazą tylko w chwili pushu. Gdy potem do bazy wejdzie inny PR, otwarty PR może
się z nim kłócić bez konfliktu tekstowego. Narzędzie bierze każdy otwarty PR do bazy (domyślnie ``main``)
i sprawdza, czy jego HEAD scala się z bieżącą bazą bez konfliktu (``git merge-tree``) i czy scalenie
przechodzi ``tools/ci_lokalnie.py --tylko ruff,mypy`` ze scalonego drzewa: ruff, mypy dla systemu, na którym
biegnie (w workflow ``scalenia.yml`` Linux), i mypy dla Windows. Werdykt to status ``scalenie z <baza>`` na
HEAD PR: ``success``, ``failure`` (konflikt albo kroki, które padły) albo ``error``. ``error`` znaczy, że
scalenie pada, ale sama baza też pada, albo że sprawdzenie nie dało wyniku. Opis statusu podaje SHA bazy.

Scalenia biegną po kolei w jednej kopii bazy (``potomne.commit_copy``), którą ``git read-tree`` przestawia
na kolejne drzewo, więc cache mypy zostaje ciepły. PR z forka jest pomijany: jego kod (``ci_lokalnie``
i konfiguracja mypy ze scalonego drzewa) biegłby z tokenem, który może ustawić każdy status commita, także
wymagany przez ruleset. PR, który zmienia zależności, jest sprawdzany z zależnościami zainstalowanymi dla
narzędzia, nie ze swoimi. GitHub przyjmuje najwyżej 1000 statusów na commit i kontekst, więc PR bez pushu
przez 1000 przebiegów przestaje dostawać werdykt.

Kończy się kodem 0, gdy każdy PR dostał werdykt, także czerwony, bo czerwony job na commicie ``main``
wyglądałby jak czerwony ``main``. Kod 1 znaczy, że narzędzie nie wysłało któregoś werdyktu.

    .venv/bin/python tools/ci/status_scalenia.py                # werdykty bez statusów
    python tools/ci/status_scalenia.py --publikuj --baza main   # workflow scalenia.yml
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import github
import potomne
from repo import ROOT
from werdykt_scalenia import PullRequest, base_problem, fetch, merge_verdict

def _open_pull_requests(base: str) -> list[PullRequest]:
    listed = github.gh("pr", "list", "--state", "open", "--limit", "500", "--json", "number,title,headRefOid,baseRefName,isCrossRepository")
    pulls = []
    for pull in json.loads(listed):
        if pull["baseRefName"] != base:
            continue
        if pull["isCrossRepository"]:
            print(f"#{pull['number']} pominięty: PR z forka", flush=True)
            continue
        pulls.append(PullRequest(pull["number"], pull["title"], pull["headRefOid"]))
    return pulls


def _check_all(base_name: str, publish: bool) -> int:
    started = time.monotonic()
    context = f"scalenie z {base_name}"
    pulls = _open_pull_requests(base_name)
    base = fetch(base_name, pulls)
    where = f"{base_name} {base[:7]}"
    states: Counter[str] = Counter()
    unsent = []
    if pulls:
        with potomne.commit_copy(ROOT, base) as copy:
            print(f"== {where}", flush=True)
            problem = base_problem(copy, where)
            for pull in pulls:
                print(f"== #{pull.number} {pull.head[:7]} {pull.title}", flush=True)
                verdict = merge_verdict(copy, where, base, problem, pull)
                print(f"#{pull.number} {verdict.state} | {verdict.description}", flush=True)
                states[verdict.state] += 1
                if publish and (error := github.ustaw_status(pull.head, context, verdict.state, verdict.description)):
                    print(f"#{pull.number} status niewysłany | {error}", flush=True)
                    unsent.append(f"#{pull.number}")
    counts = ", ".join(f"{state} {count}" for state, count in sorted(states.items()))
    summary = f"{where} | {len(pulls)} PR ({counts or 'brak'}) | {time.monotonic() - started:.0f} s"
    if unsent:
        print(f"SCALENIA FAIL | {summary} | statusy niewysłane: {', '.join(unsent)}")
        return 1
    print(f"SCALENIA OK | {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default="main", help="Gałąź, do której celują sprawdzane PR (domyślnie main).")
    parser.add_argument("--publikuj", action="store_true", help="Ustaw werdykty jako statusy commitów na GitHubie.")
    args = parser.parse_args(argv)
    try:
        return _check_all(args.baza, args.publikuj)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"SCALENIA FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"SCALENIA FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
