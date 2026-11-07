"""Odtwarza lokalnie porażkę zadania CI z PR: ruff-mypy, frontend, pytest, mutations; nie plan runu (plan_ci) ani części nocnych mutacji (mutacje_zmiany).

Lokalnie te same sprawdzenia co CI: zadania ruff, mypy (w CI jedno zadanie ``ruff-mypy``), frontend, pytest i
mutations.

Uruchamia każdy krok po kolei Pythonem, który uruchomił skrypt (w worktree: jego ``.venv``,
patrz ``tools/setup_worktree.py``), i drukuje wynik kroku jedną linią; wyjście pokazuje tylko
przy porażce. Kończy się ``CI LOKALNIE OK`` (z ``--tylko``: ``CI LOKALNIE OK | tylko <zadania>``)
albo ``CI LOKALNIE FAIL | <kroki>``; przebieg wszystkich zadań drukuje przedtem nakładania z pracą
w toku (``tools/praca_w_toku.py --nakladania``). Kroki pytest i mutacji skilli biegną tu w całości, a w CI plan
(``tools/plan_ci.py``) dzieli je między zadania i dokłada do zadań Windows E2E i Timing guard, które mają swoje
narzędzia (skill verify-rozliczenia, ``tools/benchmark_przebiegu.py``), bo trwają kilka minut.

Ciężkie zadanie ``mutations``, także w przebiegu wszystkich zadań, liczy CI na GitHubie: poza CI biegnie tylko z
``--odtwarzam <id albo URL runu>``, w którym padło na tej gałęzi (``tools/lib/ciezkie_ci.py``). Mutacje zmienionych linii
nie biegną w ``ci.yml``, tylko nocą na ``main`` (``mutacje-nocne.yml``, ADR 0021), więc narzędzie ich nie odtwarza.

``--kazdy-commit`` sprawdza każdy commit gałęzi od bazy (domyślnie ``origin/main``) we własnym
tymczasowym worktree, domyślnie krokami ruff, mypy i pytest, i nie dotyka checkoutu: zastępuje
ręczne ``git rebase --exec``. Niezacommitowanych zmian nie sprawdza.

Kroki i kopie commitów nie przeżywają ``ci_lokalnie``, także zabitego przez SIGKILL (``tools/lib/potomne.py``).

    py -3 tools/ci_lokalnie.py --tylko pytest               # Windows
    .venv/bin/python tools/ci_lokalnie.py --tylko pytest    # macOS i Linux
    .venv/bin/python tools/ci_lokalnie.py --tylko mutations --odtwarzam <id albo URL runu>
    .venv/bin/python tools/ci_lokalnie.py --kazdy-commit
    .venv/bin/python tools/ci_lokalnie.py --tylko ruff,mypy
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
from mutacje import environment
import potomne
from repo import BASE, ROOT
import repo

# Wygenerowany kontrakt i zbudowany frontend muszą zgadzać się ze źródłami (u taty nie ma Node).
GENERATED = ("frontend/src/api", "src/rozliczenia/centrum/static")
# Zadanie w ci.yml, w którym biegną kroki zadania narzędzia, gdy nazywa się inaczej.
CI_JOB = {"ruff": "ruff-mypy", "mypy": "ruff-mypy"}
JOBS_ELSEWHERE = {
    "plan": "plan zadań pytest i Mutation checks runu (tools/plan_ci.py plan drukuje go lokalnie), nic nie sprawdza",
    "required": "zbiorczy status pozostałych zadań, nic do odtworzenia",
}
# Fragment polecenia `run:` w odtwarzanym zadaniu CI, którego narzędzie nie odtwarza, i co je zastępuje.
COMMANDS_ELSEWHERE = {
    "tools/ci/czasy_ci.py": "pomiar czasów zadania (artefakt czasy-ci), nic nie sprawdza",
    "tools/ci/zapis_narzedzi_tlc.py": "decyzja o zapisie cache narzędzi TLC (#940), nie sprawdza zmiany",
}
OUTPUT_ON_FAILURE = 40
EVERY_COMMIT_JOBS = ("ruff", "mypy", "pytest")
# Zadania bramy pre-push (``--tylko ruff,mypy``); ich krokami biegną też szybko i brama typów mutacji (tools/mutacje.py).
STATIC_JOBS = ("ruff", "mypy")


@dataclass(frozen=True)
class Step:
    name: str
    job: str
    # Fragment polecenia `run:` w ci.yml, które ten krok odtwarza.
    ci: str
    command: tuple[str, ...]
    cwd: Path


def _npm() -> str:
    return shutil.which("npm") or "npm"


def _steps(root: Path) -> list[Step]:
    python, npm, frontend = sys.executable, _npm(), root / "frontend"
    return [
        Step("ruff", "ruff", "-m ruff check", (python, "-m", "ruff", "check"), root),
        # Gałęzie innych systemów niż Windows sprawdza mypy systemu, na którym biegnie; CI biegnie na Linuksie.
        Step("mypy", "mypy", "-m mypy --platform linux", (python, "-m", "mypy"), root),
        # Gałęzie tylko dla Windows używają API, którego inne systemy nie mają.
        # Własny cache, bo zmiana --platform unieważnia wspólny i oba kroki sprawdzałyby za każdym razem całość.
        Step("mypy (Windows)", "mypy", "-m mypy --platform win32", (python, "-m", "mypy", "--platform", "win32", "--cache-dir", ".mypy_cache/win32"), root),
        Step("pytest", "pytest", "tools/plan_ci.py wykonaj", (python, "-m", "pytest", "-q", "-n", "auto"), root),
        # W CI kroki skilli biegną z planu, w zadaniach Mutation checks; tu wszystkie po kolei.
        Step("mutacje skilli", "mutations", "tools/plan_ci.py wykonaj", (python, "tools/ci/mutacje_skilli.py"), root),
        Step("npm ci", "frontend", "npm ci", (npm, "ci"), frontend),
        *(
            Step(f"npm run {script}", "frontend", f"npm run {script}", (npm, "run", script), frontend)
            for script in ("contract", "typecheck", "lint", "rules", "unused", "duplicates", "build")
        ),
        Step(
            "kontrakt i build zacommitowane",
            "frontend",
            f"git status --porcelain -- {' '.join(GENERATED)}",
            repo.command("status", "--porcelain", "--", *GENERATED),
            root,
        ),
    ]


def static_steps(root: Path) -> list[Step]:
    """Kroki ruff i mypy obu systemów w ``root``, w kolejności bramy pre-push."""

    return [step for step in _steps(root) if step.job in STATIC_JOBS]


def _dependencies_fresh(frontend: Path) -> bool:
    """``node_modules`` zainstalowane z bieżącego ``package-lock.json`` (wtedy ``npm ci`` jest zbędne)."""

    installed = frontend / "node_modules" / ".package-lock.json"
    return installed.exists() and installed.stat().st_mtime >= (frontend / "package-lock.json").stat().st_mtime


def _run(step: Step, root: Path) -> tuple[bool, str]:
    completed = potomne.run(step.command, cwd=step.cwd, env={**environment(root), "PYTHON": sys.executable})
    output = completed.stdout + completed.stderr
    if step.command[:2] == repo.command("status"):
        stale = completed.stdout.strip()
        hint = "\nUruchom 'npm run contract' i 'npm run build' we frontend/ i zacommituj wynik."
        return completed.returncode == 0 and not stale, stale + hint
    return completed.returncode == 0, output


def _check(root: Path, jobs: set[str], *, fail_fast: bool = False) -> list[str]:
    """Uruchamia kroki wybranych zadań w ``root``; zwraca nazwy kroków, które padły."""

    failed: list[str] = []
    for step in _steps(root):
        if failed and fail_fast:
            break
        if step.job not in jobs:
            continue
        if step.name == "npm ci" and _dependencies_fresh(step.cwd):
            print(f"POMINIĘTO {step.name} (node_modules z bieżącego package-lock.json)", flush=True)
            continue
        started = time.monotonic()
        passed, output = _run(step, root)
        elapsed = time.monotonic() - started
        print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({elapsed:.0f} s)", flush=True)
        if not passed:
            failed.append(step.name)
            print("\n".join(output.rstrip().splitlines()[-OUTPUT_ON_FAILURE:]), flush=True)
    return failed


def _check_every_commit(base: str, jobs: set[str], *, fail_fast: bool) -> int:
    if repo.commit(ROOT, base) is None:
        print(f"COMMITY FAIL | nieznana baza {base}")
        return 1
    commits = repo.git(ROOT, "rev-list", "--reverse", f"{base}..HEAD").split()
    if not commits:
        print(f"COMMITY FAIL | brak commitów między {base} a HEAD")
        return 1
    if repo.git(ROOT, "status", "--porcelain", "--untracked-files=no").strip():
        print("UWAGA: niezacommitowane zmiany nie są sprawdzane", flush=True)
    failed = []
    for commit in commits:
        print(f"== {repo.git(ROOT, 'log', '-1', '--format=%h %s', commit).strip()}", flush=True)
        if repo.changed(ROOT, commit, "HEAD", paths=("pyproject.toml", "requirements.txt")):
            print("UWAGA: zależności różnią się od HEAD, a .venv jest zainstalowane z HEAD", flush=True)
        with potomne.commit_copy(ROOT, commit) as tree:
            if steps := _check(tree, jobs, fail_fast=fail_fast):
                failed.append(f"{commit[:7]} ({', '.join(steps)})")
    if failed:
        print(f"COMMITY FAIL | {'; '.join(failed)}")
        return 1
    print(f"COMMITY OK ({len(commits)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kroki-ci", action="store_true", help="Wypisz JSON: odtwarzane zadania CI i ich polecenia.")
    parser.add_argument(
        "--kazdy-commit",
        nargs="?",
        const=BASE,
        metavar="BAZA",
        help=f"Sprawdź każdy commit od BAZA (domyślnie {BASE}) do HEAD w osobnym worktree.",
    )
    parser.add_argument("--tylko", metavar="ZADANIA", help="Tylko te zadania CI, po przecinku, np. ruff,mypy.")
    parser.add_argument(
        "--do-pierwszego-bledu",
        action="store_true",
        help="Zakończ po pierwszym nieudanym kroku (brama pre-push: nieudany push odpowiada szybko).",
    )
    ciezkie_ci.argument(parser)
    args = parser.parse_args(argv)
    steps = _steps(ROOT)
    known = {step.job for step in steps}
    if args.kroki_ci:
        reproduced = sorted({CI_JOB.get(job, job) for job in known})
        elsewhere = {"zadania": JOBS_ELSEWHERE, "polecenia": COMMANDS_ELSEWHERE}
        print(json.dumps({"lokalnie": reproduced, "gdzie_indziej": elsewhere, "fragmenty": [s.ci for s in steps]}))
        return 0
    jobs = set(args.tylko.split(",")) if args.tylko else set(EVERY_COMMIT_JOBS if args.kazdy_commit else known)
    if unknown := jobs - known:
        parser.error(f"nieznane zadania: {', '.join(sorted(unknown))}; znane: {', '.join(sorted(known))}")
    if refusal := ciezkie_ci.refusal(jobs, args.odtwarzam, root=ROOT):
        print(refusal)
        return 2
    if args.kazdy_commit:
        return _check_every_commit(args.kazdy_commit, jobs, fail_fast=args.do_pierwszego_bledu)
    complete = jobs == known
    failed = _check(ROOT, jobs, fail_fast=args.do_pierwszego_bledu)
    if complete:
        try:
            overlaps = (sys.executable, str(ROOT / "tools" / "praca_w_toku.py"), "--nakladania")
            potomne.run(overlaps, cwd=ROOT, timeout=120, echo=True)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"NAKŁADANIA POMINIĘTE | {error}", flush=True)
    if failed:
        print(f"CI LOKALNIE FAIL | {', '.join(failed)}")
        return 1
    print("CI LOKALNIE OK" if complete else f"CI LOKALNIE OK | tylko {', '.join(sorted(jobs))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
