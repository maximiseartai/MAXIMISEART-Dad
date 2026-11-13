"""Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.

Przepis z korzenia checkoutu; po ``--`` stoją argumenty Pythona, który uruchomił narzędzie:

    # jedna mutacja: plik, kotwica (jej tekst stoi w pliku dokładnie raz) i zamiana
    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'if n > LIMIT:' 'if False:' \\
        -- -m pytest -q -n 0 tests/test_x.py -k nazwa_testu
    # mutacje z pliku JSON, naraz
    .venv/bin/python tools/mutacje.py --rownolegle --plik mutacje.json -- -m pytest -q -n 0 tests/test_x.py

    mutacje.json: "polecenie" (zamiast polecenia po --) i "oczekiwane" (początek ostatniej linii wyjścia, który
    wykrywa mutację zamiast kodu wyjścia) są opcjonalne
    [
      {"nazwa": "bez limitu", "zmiany": [["src/rozliczenia/x.py", "if n > LIMIT:", "if False:"]]},
      {"nazwa": "dwa miejsca", "zmiany": [["src/rozliczenia/x.py", "n = 1", "n = 2"], ["tools/y.py", "z", "w"]],
       "polecenie": ["-m", "pytest", "-q", "-n", "0", "tests/test_y.py"], "oczekiwane": "SPRAWDZENIE: NARUSZENIE"}
    ]

Pytest w jednym procesie to ``-n 0``: ``-p no:xdist`` pada na ``--dist`` z ``addopts`` w ``pyproject.toml``. Ścieżka
i ``-k`` muszą wybrać test, bo polecenie bez mutacji (podstawa) musi przejść, zanim mutacja czegoś dowiedzie. Mutację
NIEWYKRYTA narzędzie powtarza na merge-base HEAD z ``--baza`` (domyślnie origin/main; gałąź zbudowana na innej podaje
ją), a WYKRYTA tam to REGRES. Poza CI jedno uruchomienie ma najwyżej 100 mutacji (``ciezkie_ci.TARGETED``). Dowodem
jest tylko WYKRYTA, a narzędzie kończy się wtedy kodem 0 i linią ``MUTACJE OK``.

Po ``MUTACJE OK`` z poleceniem pytest, które wybiera test dodany albo zmieniony od tego merge-base, narzędzie sprawdza
każdą mutację też testami sprzed zmiany: w plikach, które szybko wybrałby dla zmutowanych plików (``szybko.plan``), bez
testów dodanych albo zmienionych od merge-base, z ``-x``. Gdy test sprzed zmiany sam pada po mutacji, a bez niej
przechodzi, linia ``JUŻ ŁAPIE <plik>::<test>`` na stderr mówi, że ten błąd ma już test, więc nowy go dubluje: dopisz
asercję tam albo usuń nowy test. Linia ``JUŻ ŁAPIE NIESPRAWDZONE`` mówi, dlaczego sprawdzenia nie było. Werdyktów,
ostatniej linii stdout ani kodu wyjścia to nie zmienia, a całe sprawdzenie trwa najwyżej ``ALREADY_S`` s.

Zasady werdyktów, kopii, bramy typów, nocy, ``--jak-ci`` i ``MUTACJE_CZESC`` drukuje ``--zasady``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import cache, partial
from itertools import pairwise
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
import czasy_ci
import github
from jednostka import ZMIENNA_CZESCI
from kroki_lokalne import environment
import plan_runu
import potomne
from repo import BASE, ROOT
import repo
from silnik_mutacji import PARALLEL, TIMEOUT, Edit, Mutation, Verdict, review, verdicts
import silnik_mutacji
import szybko
import wplyw_zmiany
import wyniki_testow

RULES_HEADING = "Zasady werdyktów i przebiegu"
RULES = (silnik_mutacji.__doc__ or "").partition(f"\n{RULES_HEADING}\n")[2]


def _texts(value: object, count: int | None = None) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value) and count in {None, len(value)}


class _Key(NamedTuple):
    required: bool
    valid: Callable[[object], bool]


_ENTRY = {
    "nazwa": _Key(required=True, valid=lambda value: isinstance(value, str)),
    "zmiany": _Key(required=True, valid=lambda value: isinstance(value, list) and bool(value) and all(_texts(edit, 3) for edit in value)),
    "polecenie": _Key(required=False, valid=_texts),
    "oczekiwane": _Key(required=False, valid=lambda value: isinstance(value, str)),
}
FILE_SHAPE = '[{"nazwa": "...", "zmiany": [["plik", "kotwica", "zamiana"], ...]}, ...] z opcjonalnymi "polecenie": [...] i "oczekiwane": "..."'


def _entry_problem(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return "nie jest obiektem"
    if unknown := sorted(entry.keys() - _ENTRY.keys()):
        return f"ma nieznany klucz {unknown[0]!r}"
    wrong = [key for key, (required, valid) in _ENTRY.items() if (key in entry or required) and not (key in entry and valid(entry[key]))]
    return f"ma zły albo brakujący klucz {wrong[0]!r}" if wrong else None


def _from_file(path: Path, command: tuple[str, ...]) -> list[Mutation]:
    """Mutacje z pliku JSON; plik innej postaci niż ``FILE_SHAPE`` to ``ValueError``, która ją podaje."""

    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError(f"{path}: plik mutacji to lista, nie {type(entries).__name__}; postać: {FILE_SHAPE}")
    for number, entry in enumerate(entries, 1):
        if problem := _entry_problem(entry):
            raise ValueError(f"{path}: wpis {number} {problem}; postać: {FILE_SHAPE}")
    return [
        Mutation(
            name=entry["nazwa"],
            edits=tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in entry["zmiany"]),
            command=tuple(entry.get("polecenie", command)),
            expected=entry.get("oczekiwane"),
        )
        for entry in entries
    ]


def _output(*arguments: str) -> str:
    """Wyjście polecenia ``gh``; porażka to ``ValueError`` z końcem jego błędu."""

    try:
        return github.gh(*arguments, limit_s=None).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{' '.join(error.cmd[:3])} padł: {(error.stderr.strip() or error.stdout.strip())[-300:]}") from None


def _last_run() -> str:
    """Numer ostatniego runu ``ci.yml`` gałęzi, którą śledzi bieżąca (bez śledzonej: bieżącej)."""

    try:
        head = repo.git(ROOT, "rev-parse", "--symbolic-full-name", "HEAD").strip()
        if not head.startswith("refs/heads/"):
            raise ValueError("HEAD nie jest na gałęzi, więc podaj numer runu CI: --jak-ci <id runu>")
        branch = repo.git(ROOT, "for-each-ref", "--format=%(upstream:lstrip=3)", head).strip() or head.removeprefix("refs/heads/")
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{' '.join(error.cmd[:3])} padł: {(error.stderr.strip() or error.stdout.strip())[-300:]}") from error
    runs = json.loads(_output("run", "list", "--workflow", "ci.yml", "--branch", branch, "--limit", "1", "--json", "databaseId"))
    if not runs:
        raise ValueError(f"gałąź {branch} nie ma runu CI, więc podaj numer runu: --jak-ci <id runu>")
    return str(runs[0]["databaseId"])


def _ci_mutations(mutations: Sequence[Mutation], run: str, base: str) -> list[Mutation]:
    """Każda mutacja raz na każde zadanie pytest runu ``run`` (pusty: ``_last_run``), w którym stoi test zmieniony od
    ``base``, z poleceniem ``pytest -n 1`` z plikami tego zadania."""

    try:
        tested = wplyw_zmiany.changed_since(ROOT, base)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"brak merge-base HEAD z {base}, więc nie wiadomo, które testy zmieniono: {error.stderr.strip()}") from error
    run = run or _last_run()
    with tempfile.TemporaryDirectory(prefix="plan-ci-") as folder:
        _output("run", "download", run, "--name", plan_runu.ARTEFAKT, "--dir", folder)
        plan = plan_runu.Plan.z_json((Path(folder) / plan_runu.PLIK).read_text(encoding="utf-8"))
    tracks = plan_runu.tory_systemu(windows=sys.platform == "win32")
    jobs = plan.pliki_pytest(tracks, tested)
    if not jobs:
        raise ValueError(f"run {run} nie stawia w zadaniu pytest toru {', '.join(sorted(tracks))} pliku testów zmienionego od {base}")
    commands = {name: ("-m", "pytest", "-q", "-n", "1", "-p", "no:cacheprovider", *files) for name, files in jobs}
    for name, command in commands.items():
        print(f"JAK CI: run {run}, {name}: {' '.join(command)}", flush=True)
    return [replace(mutation, name=f"{mutation.name} [{name}]", command=command) for mutation in mutations for name, command in commands.items()]


ALREADY = "JUŻ ŁAPIE"
UNCHECKED = f"{ALREADY} NIESPRAWDZONE"
# Przy nowym zachowaniu żaden test sprzed zmiany nie pada, więc bez limitu każda mutacja kosztowałaby cały wybór szybko.
ALREADY_S = 300.0
COLLECT_S = 120.0


class _Probe(NamedTuple):
    new: tuple[str, ...]  # testy polecenia dodane albo zmienione od merge-base
    tests: tuple[str, ...]  # pliki albo id testów sprzed zmiany, po odległości od mutacji


def _key(node: str) -> tuple[str, str]:
    """Plik i test z id pytest bez parametrów: ``tests/x.py::K::test_y[1]`` → ``("tests/x.py", "K::test_y")``."""

    path, _, name = node.partition("[")[0].partition("::")
    return path, name


def _command_tests(command: Sequence[str]) -> set[tuple[str, str]] | None:
    """Testy (``_key``), które wybiera polecenie pytest, z kolekcji w checkoucie; ``None``, gdy kolekcja padła."""

    # --verbosity po -q polecenia: id testów drukuje tylko -1, a -q -q daje same pliki.
    collect = [sys.executable, *command, "--collect-only", "--verbosity=-1", "-n", "0", "-p", "no:cacheprovider"]
    try:
        done = potomne.run(collect, cwd=ROOT, env=environment(ROOT), timeout=COLLECT_S)
    except potomne.TimeoutExpired:
        return None
    if done.returncode != 0:
        return None
    return {_key(line.strip()) for line in done.stdout.splitlines() if "::" in line}


def _probe(
    mutation: Mutation, base: str, changed: frozenset[str], scanned: wplyw_zmiany.Repository, costs: czasy_ci.KosztyPlikow
) -> _Probe | str:
    """Testy, którymi ``_already`` sprawdza mutację, albo przyczyna, z którą jej nie sprawdza."""

    selected = _command_tests(mutation.command)
    if selected is None:
        return "kolekcja testów polecenia padła"

    unchanged = cache(partial(wplyw_zmiany.unchanged_tests, ROOT, base))
    new = tuple(sorted(f"{path}::{name}" for path, name in selected if path in changed and name not in unchanged(path)))
    if not new:
        return f"polecenie nie wybiera testu dodanego ani zmienionego od merge-base {base[:8]}"
    impact = scanned.impact(frozenset(edit.file.as_posix() for edit in mutation.edits))
    chosen = szybko.plan(impact.tests, impact.distances, costs).run
    tests: list[str] = []
    for path in sorted(chosen, key=lambda path: (impact.distances.get(path, 0), path)):
        tests += [f"{path}::{name}" for name in sorted(unchanged(path))] if path in changed else [path]
    return _Probe(new, tuple(tests))


def _first_failed(junit: Path) -> str | None:
    try:
        return next((test.id for test in wyniki_testow.testy(junit) if test.wynik == "padł" and test.id), None)
    except (OSError, ValueError):
        return None


def _already(mutation: Mutation, probe: _Probe, deadline: float, limit_s: float) -> str:
    """Linia ``JUŻ ŁAPIE`` albo ``JUŻ ŁAPIE NIESPRAWDZONE`` mutacji, której testy sprzed zmiany są w ``probe``; pusta,
    gdy żaden jej nie łapie.

    Pierwszy test, który padł (``-x``), biegnie potem sam z mutacją i bez niej: dowodem jest tylko test, który sam pada
    po mutacji, a bez niej przechodzi. Test sprzed zmiany potrafi padać na zmienionym kodzie także bez mutacji albo tylko
    z sąsiadem w tym samym workerze, a fałszywa linia kazałaby usunąć potrzebny test."""

    workers = os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", str(czasy_ci.WORKERY_LOKALNE))
    with tempfile.TemporaryDirectory(prefix="juz-lapie-") as folder:
        listed, junit = Path(folder) / "testy.txt", Path(folder) / "junit.xml"
        # Lista w pliku (``@plik`` pytest): id testów zmienionego pliku przekraczają limit wiersza poleceń Windows.
        listed.write_text("\n".join(probe.tests), encoding="utf-8")
        command = ("-m", "pytest", "-q", "-x", "-n", workers, "-p", "no:cacheprovider", *wyniki_testow.zapis(junit), f"@{listed}")
        [(verdict, last)] = verdicts([replace(mutation, command=command)], workers=1, limit_s=limit_s, deadline=deadline)
        failed = _first_failed(junit) if verdict in {Verdict.CAUGHT, Verdict.HANG} else None
    if verdict is Verdict.SURVIVED:
        return ""
    if verdict in {Verdict.OVER_LIMIT, Verdict.NO_VERDICT}:
        return f"{UNCHECKED}: {mutation.name}: testy sprzed zmiany nie skończyły się w limicie sprawdzenia ({last})"
    if failed is None:
        return f"{UNCHECKED}: {mutation.name}: testy sprzed zmiany dały {verdict} bez testu, który padł ({last})"
    alone = ("-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", failed)
    checks = [replace(mutation, command=alone), Mutation(mutation.name, (), alone)]
    (mutated, mutated_last), (clean, clean_last) = verdicts(checks, workers=1, limit_s=limit_s, deadline=deadline)
    if (mutated, clean) != (Verdict.CAUGHT, Verdict.SURVIVED):
        why = f"z mutacją {mutated} ({mutated_last}), bez niej {clean} ({clean_last})"
        return f"{UNCHECKED}: {mutation.name}: {failed} sam daje {why}, więc niczego nie dowodzi"
    return (
        f"{ALREADY} {failed}: ten test sprzed zmiany już łapie mutację „{mutation.name}”, więc {', '.join(probe.new)} "
        "dubluje go w tym błędzie: dopisz asercję do testu sprzed zmiany albo usuń nowy test"
    )


def _already_caught(mutations: Sequence[Mutation], base: str, limit_s: float) -> None:
    """Linie ``_already`` na stderr dla mutacji z poleceniem pytest bez oczekiwanej linii, razem w ``ALREADY_S`` s."""

    deadline = time.monotonic() + ALREADY_S
    checked = [mutation for mutation in mutations if ("-m", "pytest") in pairwise(mutation.command) and mutation.expected is None]
    if not checked:
        return
    try:
        commit = repo.merge_base(ROOT, "HEAD", base)
    except subprocess.CalledProcessError as error:
        print(f"{UNCHECKED}: brak merge-base HEAD z {base} ({error.stderr.strip()})", file=sys.stderr, flush=True)
        return
    changed, scanned = repo.changed(ROOT, commit), wplyw_zmiany.Repository.scan(ROOT)
    costs, _ = czasy_ci.lokalne(ROOT)
    for mutation in checked:
        if time.monotonic() >= deadline:
            print(f"{UNCHECKED}: {mutation.name}: minął limit sprawdzenia {ALREADY_S:g} s", file=sys.stderr, flush=True)
            continue
        probe = _probe(mutation, commit, changed, scanned, costs)
        if isinstance(probe, str):
            print(f"{UNCHECKED}: {mutation.name}: {probe}", file=sys.stderr, flush=True)
        elif probe.tests and (line := _already(mutation, probe, deadline, limit_s)):
            print(line, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    split = arguments.index("--") if "--" in arguments else len(arguments)
    command = tuple(arguments[split + 1 :])
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--zmiana",
        nargs=3,
        action="append",
        default=[],
        metavar=("PLIK", "KOTWICA", "ZAMIANA"),
        help="Jedna zmiana mutacji; powtórz dla mutacji w kilku miejscach.",
    )
    parser.add_argument("--plik", type=Path, help="Plik JSON z listą mutacji.")
    parser.add_argument("--rownolegle", action="store_true", help="Mutacje naraz, każda w swojej kopii.")
    parser.add_argument("--limit-s", type=float, default=TIMEOUT, help="Limit czasu jednego polecenia w sekundach.")
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, z której merge-base z HEAD daje REGRES i plan --jak-ci (domyślnie {BASE}).")
    parser.add_argument(
        "--jak-ci",
        nargs="?",
        const="",
        metavar="RUN",
        help="Polecenie z plików każdego zadania pytest runu CI RUN (bez numeru: ostatniego runu gałęzi), w którym stoją zmienione testy, bez polecenia po --.",
    )
    ciezkie_ci.argument(parser)
    parser.add_argument("--zasady", action="store_true", help=f"Drukuje zasady werdyktów, kopii, bramy typów, nocy, --jak-ci i {ZMIENNA_CZESCI}.")
    args = parser.parse_args(arguments[:split])
    if args.zasady:
        print(RULES.strip())
        return 0
    jak_ci = args.jak_ci is not None
    if jak_ci and command:
        parser.error("--jak-ci składa polecenie samo, więc nie podawaj go po --")
    try:
        mutations = _from_file(args.plik, command) if args.plik else []
        if args.zmiana:
            edits = tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in args.zmiana)
            mutations.append(Mutation("mutacja", edits, command))
    except ValueError as error:
        parser.error(str(error))
    if jak_ci and (named := [mutation.name for mutation in mutations if mutation.command]):
        parser.error(f"--jak-ci składa polecenie samo, a wpisy {', '.join(named)} mają własne")
    if not mutations or not (jak_ci or all(mutation.command for mutation in mutations)):
        parser.error("podaj mutację (--zmiana albo --plik) i polecenie po --, np. -- -m pytest -q -n 0 tests/test_x.py -k nazwa_testu, albo --jak-ci")
    if jak_ci:
        try:
            mutations = _ci_mutations(mutations, args.jak_ci, args.baza)
        except ValueError as error:
            parser.error(str(error))
    if refused := ciezkie_ci.mutations_refusal(len(mutations), args.odtwarzam, root=ROOT):
        print(refused)
        return 2
    code = review(mutations, base=args.baza, workers=PARALLEL if args.rownolegle else 1, limit_s=args.limit_s)
    if code == 0 and not jak_ci:
        _already_caught(mutations, args.baza, args.limit_s)
    return code


if __name__ == "__main__":
    raise SystemExit(main())