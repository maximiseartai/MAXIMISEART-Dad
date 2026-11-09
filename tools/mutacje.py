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

Zasady werdyktów, kopii, bramy typów, nocy, ``--jak-ci`` i ``MUTACJE_CZESC`` drukuje ``--zasady``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
import github
from jednostka import ZMIENNA_CZESCI
import plan_runu
from repo import BASE, ROOT
import repo
from silnik_mutacji import PARALLEL, TIMEOUT, Edit, Mutation, review
import silnik_mutacji
import wplyw_zmiany

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
    return review(mutations, base=args.baza, workers=PARALLEL if args.rownolegle else 1, limit_s=args.limit_s)


if __name__ == "__main__":
    raise SystemExit(main())