"""Uruchamia polecenie na commitach scalenia wskazanych PR-ów; użyj, by pokazać, że nowe sprawdzenie łapie błąd bez fałszywego alarmu.

Nowe sprawdzenie (narzędzie, test struktury, zadanie CI) przed przeglądem przechodzi próbę na scalonych PR-ach: na PR-ach,
które dostały werdykt FAIL, ma znaleźć to, co znalazł przegląd, a na zwykłych dobrych PR-ach nie może dawać fałszywego
alarmu. Dla każdego PR-u narzędzie robi kopię commitu scalenia (``potomne.commit_copy``), nadpisuje w niej ``tools/``
plikami z tego checkoutu z chwili startu (także niezacommitowanymi), uruchamia polecenie w korzeniu kopii Pythonem, który uruchomił
narzędzie, z ``PYTHONPATH`` na ``src`` kopii i ``MAXIMISEART_NA_SCALONYCH_PR=1`` (``tools/lib/ciezkie_ci.py`` przepuszcza wtedy
``tools/mutacje_zmiany.py``), i drukuje jedną linię na PR: numer, commit, czas, kod wyjścia i ostatnią
linię wyjścia. W kopii ``HEAD^1`` to ``main`` sprzed scalenia, więc ``--baza HEAD^1`` to zmiana samego PR-u, jak w CI.
Pełne wyjście każdego PR-u leży w ``--wyniki`` (domyślnie katalog ``na-scalonych-pr`` w katalogu gita worktree).

    .venv/bin/python tools/na_scalonych_pr.py --pr 393 --pr 384 -- tools/mutacje_zmiany.py --baza HEAD^1
    .venv/bin/python tools/na_scalonych_pr.py --ostatnie 5 -- tools/mutacje_zmiany.py --baza HEAD^1
    .venv/bin/python tools/na_scalonych_pr.py --commit 04f08b45 -- tools/mutacje_zmiany.py --baza e7cf937b

``--narzedzia origin/main`` bierze narzędzia z commitu zamiast z checkoutu, np. dla pomiaru przed zmianą narzędzia.
``--commit`` bierze dowolny commit, np. HEAD PR-u z werdyktem FAIL, który w tej postaci nie wszedł do ``main``; wtedy
bazę zmiany polecenie podaje samo.

Kończy się ``NA SCALONYCH PR OK | <n> PR-ów`` albo ``NA SCALONYCH PR FAIL | <PR-y z kodem innym niż 0>``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
import github
import potomne
from repo import REMOTE, ROOT
import repo


@dataclass(frozen=True)
class Merged:
    label: str  # ``#393`` albo skrót commitu
    commit: str


def merged(numbers: list[int], last: int) -> list[Merged]:
    """Scalone PR-y z ``numbers`` i ``last`` ostatnio scalonych, każdy z commitem scalenia."""

    found: dict[int, str] = {}
    if last:
        listed = json.loads(github.gh("pr", "list", "--state", "merged", "--limit", str(last), "--json", "number,mergeCommit", limit_s=None))
        found |= {entry["number"]: entry["mergeCommit"]["oid"] for entry in listed}
    for number in numbers:
        entry = json.loads(github.gh("pr", "view", str(number), "--json", "number,state,mergeCommit", limit_s=None))
        if entry["state"] != "MERGED" or not entry.get("mergeCommit"):
            raise ValueError(f"PR #{number} nie jest scalony")
        found[number] = entry["mergeCommit"]["oid"]
    return [Merged(f"#{number}", commit) for number, commit in sorted(found.items())]


def commit_of(revision: str) -> str:
    """Pełny SHA rewizji znanej lokalnie (``origin/main``, ``HEAD^1``), a nieznany commit bez zmian, do pobrania.

    Etykieta i nazwa pliku wyniku biorą skrót SHA, bo skrót nazwy (``origin/m``) byłby ścieżką z ukośnikiem.
    """

    return repo.commit(ROOT, revision) or revision


def tools_snapshot(revision: str | None) -> dict[str, bytes]:
    """Treść plików ``tools/`` z chwili startu: z checkoutu (śledzonych i nowych nieignorowanych) albo z ``revision``.

    Każdy PR dostaje tę samą wersję narzędzi, choćby checkout zmienił się w trakcie długiego przebiegu.
    """

    if revision is not None:
        with potomne.commit_copy(ROOT, revision) as copy:
            return {path.relative_to(copy).as_posix(): path.read_bytes() for path in (copy / "tools").rglob("*") if path.is_file()}
    listed = repo.git(ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "tools").split("\0")
    return {name: (ROOT / name).read_bytes() for name in listed if name and (ROOT / name).is_file()}


def run_on(pr: Merged, command: list[str], tools: dict[str, bytes], output: Path) -> tuple[int, float, str]:
    """Kod wyjścia, czas w sekundach i ostatnia linia polecenia na kopii commitu scalenia ``pr``."""

    if repo.commit(ROOT, pr.commit) is None:
        fetched = repo.run_git(ROOT, "fetch", "--quiet", REMOTE, pr.commit)
        if fetched.returncode:
            return fetched.returncode, 0.0, f"git fetch {pr.commit[:8]}: {fetched.stderr.strip()}"
    with potomne.commit_copy(ROOT, pr.commit) as copy:
        for name, content in tools.items():
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            (copy / name).write_bytes(content)
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(copy / "src"), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
        # Próba narzędzia na cudzym commicie, nie sprawdzenie przed pushem: ciężkie zadania biegną (tools/lib/ciezkie_ci.py).
        env[ciezkie_ci.FROM_MERGED_PRS] = "1"
        started = time.monotonic()
        done = potomne.run([sys.executable, *command], cwd=copy, env=env)
        elapsed = time.monotonic() - started
    text = done.stdout + done.stderr
    output.write_text(text, encoding="utf-8")
    lines = text.strip().splitlines()
    return done.returncode, elapsed, lines[-1] if lines else ""


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    split = arguments.index("--") if "--" in arguments else len(arguments)
    command = arguments[split + 1 :]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr", type=int, action="append", default=[], help="Numer scalonego PR-u; powtórz dla kilku.")
    parser.add_argument("--ostatnie", type=int, default=0, help="Tyle ostatnio scalonych PR-ów.")
    parser.add_argument("--commit", action="append", default=[], help="Dowolny commit, np. HEAD PR-u z werdyktem FAIL.")
    parser.add_argument("--wyniki", type=Path, help="Katalog na pełne wyjście każdego PR-u.")
    parser.add_argument("--narzedzia", metavar="REV", help="Narzędzia z tego commitu zamiast z checkoutu, np. origin/main dla porównania.")
    args = parser.parse_args(arguments[:split])
    if not command or not (args.pr or args.ostatnie or args.commit):
        parser.error("podaj PR-y (--pr, --ostatnie albo --commit) i polecenie po --, np. -- tools/mutacje_zmiany.py --baza HEAD^1")
    try:
        prs = merged(args.pr, args.ostatnie) if args.pr or args.ostatnie else []
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"NA SCALONYCH PR FAIL | {error}")
        return 1
    folder = args.wyniki or ROOT / repo.git(ROOT, "rev-parse", "--git-path", "na-scalonych-pr").strip()
    folder.mkdir(parents=True, exist_ok=True)
    prs += [Merged(commit[:8], commit) for commit in map(commit_of, args.commit)]
    failed = []
    tools = tools_snapshot(args.narzedzia)
    for pr in prs:
        output = folder / f"{pr.label.lstrip('#')}.txt"
        code, elapsed, last = run_on(pr, command, tools, output)
        if code:
            failed.append(pr.label)
        print(f"{pr.label} | {pr.commit[:8]} | {elapsed:.0f} s | kod {code} | {last} | {output}", flush=True)
    print(f"NA SCALONYCH PR FAIL | {', '.join(failed)}" if failed else f"NA SCALONYCH PR OK | {len(prs)} PR-ów")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
