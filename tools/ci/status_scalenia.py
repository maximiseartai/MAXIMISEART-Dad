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

OPIS = """Werdykt scalenia każdego otwartego PR z jego bazą jako status commita na HEAD PR.

CI na PR sprawdza scalenie z bazą tylko w chwili pushu. Gdy potem do bazy wejdzie inny PR, otwarty PR może
się z nim kłócić bez konfliktu tekstowego. Narzędzie bierze każdy otwarty PR do bazy (domyślnie ``main``)
i sprawdza, czy jego HEAD scala się z bieżącą bazą bez konfliktu (``git merge-tree``) i czy scalenie
przechodzi ``tools/ci_lokalnie.py --tylko ruff,mypy`` ze scalonego drzewa: ruff, mypy dla systemu, na którym
biegnie (w workflow ``scalenia.yml`` Linux), i mypy dla Windows. Werdykt to status ``scalenie z <baza>`` na
HEAD PR: ``success``, ``failure`` (konflikt albo kroki, które padły) albo ``error``. ``error`` znaczy, że
scalenie pada, ale sama baza też pada, albo że sprawdzenie nie dało wyniku. Opis statusu podaje SHA bazy.

Scalenia biegną po kolei w jednej kopii bazy (``potomne.commit_copy``), którą ``git read-tree`` przestawia
na kolejne drzewo, więc cache mypy zostaje ciepły. PR z forka jest pomijany. PR, który zmienia zależności, jest
sprawdzany z zależnościami zainstalowanymi dla narzędzia, nie ze swoimi. GitHub przyjmuje najwyżej 1000 statusów na
commit i kontekst, więc PR bez pushu przez 1000 przebiegów przestaje dostawać werdykt.

Werdykty liczy kod PR (``ci_lokalnie`` i konfiguracja mypy ze scalonego drzewa), więc ten bieg nie ma prawa zapisu
statusów: ``--zapisz PLIK`` zapisuje werdykty w pliku, który ``scalenia.yml`` wysyła jako artefakt, a status ustawia
``--publikuj-z PLIK`` w workflow ``werdykt-i-bramka.yml``, kodem ``main`` i bez kodu PR, jedynym z prawem
``statuses: write`` (``tests/test_zadania_ci.py``). Plik podaje bazę biegu (``--baza``, w ``scalenia.yml`` wejście
``baza``), a ``--publikuj-z`` ustawia tylko status ``scalenie z <ta baza>`` o stanie z ``VERDICT_STATES`` na HEAD,
który otwarty PR do tej bazy (nie z forka) ma teraz; inny wpis pomija z linią.
Granica: plik pisze bieg z kodem PR, więc kod PR może zmienić werdykt scalenia, ale nie inny status.

Kończy się kodem 0, gdy każdy PR dostał werdykt, także czerwony, bo czerwony job na commicie ``main``
wyglądałby jak czerwony ``main``. Kod 1 znaczy, że narzędzie nie zapisało albo nie wysłało któregoś werdyktu.

    .venv/bin/python tools/ci/status_scalenia.py                                 # werdykty bez statusów
    python tools/ci/status_scalenia.py --zapisz scalenia.json --baza main         # workflow scalenia.yml
    python3 tools/ci/status_scalenia.py --publikuj-z scalenia.json                # workflow werdykt-i-bramka.yml
"""

VERDICT_STATES = frozenset({"success", "failure", "error"})


def _context(base: str) -> str:
    return f"scalenie z {base}"


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


def _check_all(base_name: str, out: Path | None) -> int:
    started = time.monotonic()
    pulls = _open_pull_requests(base_name)
    base = fetch(base_name, pulls)
    where = f"{base_name} {base[:7]}"
    states: Counter[str] = Counter()
    verdicts = []
    if pulls:
        with potomne.commit_copy(ROOT, base) as copy:
            print(f"== {where}", flush=True)
            problem = base_problem(copy, where)
            for pull in pulls:
                print(f"== #{pull.number} {pull.head[:7]} {pull.title}", flush=True)
                verdict = merge_verdict(copy, where, base, problem, pull)
                print(f"#{pull.number} {verdict.state} | {verdict.description}", flush=True)
                states[verdict.state] += 1
                verdicts.append({"numer": pull.number, "sha": pull.head, "kontekst": _context(base_name), "stan": verdict.state, "opis": verdict.description})
    if out is not None:
        out.write_text(json.dumps({"baza": base_name, "werdykty": verdicts}, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = ", ".join(f"{state} {count}" for state, count in sorted(states.items()))
    print(f"SCALENIA OK | {where} | {len(pulls)} PR ({counts or 'brak'}) | {time.monotonic() - started:.0f} s")
    return 0


def _publish_from(path: Path) -> int:
    """Statusy z pliku ``--zapisz``: tylko wpis z kontekstem ``scalenie z <baza pliku>``, stanem z ``VERDICT_STATES``
    i SHA, które otwarty PR o tym numerze do tej bazy (nie z forka) ma teraz jako HEAD."""

    written = json.loads(path.read_text(encoding="utf-8"))
    base_name = str(written["baza"])
    heads = {pull.number: pull.head for pull in _open_pull_requests(base_name)}
    sent, skipped, unsent = 0, 0, []
    for entry in written["werdykty"]:
        number, head, context, state = entry.get("numer"), entry.get("sha"), entry.get("kontekst"), entry.get("stan")
        if context != _context(base_name) or state not in VERDICT_STATES or heads.get(number) != head:
            print(f"#{number} pominięty: {context!r} {state!r} na {str(head)[:7]} to nie werdykt scalenia z {base_name} na HEAD otwartego PR", flush=True)
            skipped += 1
            continue
        if error := github.ustaw_status(str(head), context, str(state), str(entry.get("opis", ""))):
            print(f"#{number} status niewysłany | {error}", flush=True)
            unsent.append(f"#{number}")
            continue
        sent += 1
    summary = f"{base_name} | wysłane {sent}, pominięte {skipped}"
    if unsent:
        print(f"SCALENIA FAIL | {summary} | statusy niewysłane: {', '.join(unsent)}")
        return 1
    print(f"SCALENIA OK | {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default="main", help="Gałąź, do której celują sprawdzane PR (domyślnie main); --publikuj-z bierze ją z pliku.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--zapisz", type=Path, metavar="PLIK", help="Zapisz werdykty w pliku JSON dla --publikuj-z.")
    mode.add_argument("--publikuj-z", type=Path, metavar="PLIK", help="Ustaw statusy z pliku --zapisz, bez liczenia werdyktów.")
    args = parser.parse_args(argv)
    try:
        if args.publikuj_z is not None:
            return _publish_from(args.publikuj_z)
        return _check_all(args.baza, args.zapisz)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"SCALENIA FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, AttributeError, TypeError) as error:
        print(f"SCALENIA FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
