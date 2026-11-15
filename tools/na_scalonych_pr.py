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

``--ostatnie`` bierze ostatnie merge'e PR-ów (``Merge pull request #N``) z historii ``--first-parent``
``origin/main`` po pobraniu ``main``.

Kończy się ``NA SCALONYCH PR OK | <n> PR-ów`` albo ``NA SCALONYCH PR FAIL | <PR-y z kodem innym niż 0>``.

Dowód reguły ast-grep (``--regula PLIK.yml`` zamiast polecenia) to trzy biegi reguły na kopii commitu, bez
nadpisywania ``tools/``, więc reguła z zakresem w ``tools/`` widzi linie samego commitu. Odpalenia na liniach dodanych
liczy ``odpalenia_ast_grep.on_added_lines``, ta sama funkcja co zapadka ``syntax_rules``: węzeł reguły obejmuje
którąkolwiek linię dodaną, a linia odpalenia to pierwsza dodana linia węzła (odpala też ``severity: off``):

    .venv/bin/python tools/na_scalonych_pr.py --regula reguly-ast-grep/x.yml --wazne 1533/W1/r2 --ostatnie 20
    .venv/bin/python tools/na_scalonych_pr.py --regula-id x --z-commita <SHA HEAD PR> --wazne 1533/W1/r2

``--regula-id ID --z-commita REV`` bierze regułę o id ``ID``, którą wybiera sam ast-grep z konfiguracji kopii commitu
``REV``: ``--config <kopia>/sgconfig.yml --filter '^ID$'``, ten sam loader co zapadka ``syntax_rules``
(``--config sgconfig.yml``), więc dowód widzi dokładnie te reguły, które zapadka ładuje, a plik reguły czyta tylko
ast-grep. Reguły, której ta konfiguracja nie ładuje (``NOT_LOADED``: poza ``ruleDirs``, w ukrytym podkatalogu, bez
katalogu ``ruleDirs`` albo commit bez ``sgconfig.yml``), dowód odmawia, bo próbka ``ZNANE_LUKI`` reguły nie
zastępuje. Pola ``files:`` takiej reguły dowód nie sprawdza: regułę bez niego w ``reguly-ast-grep/`` (jedyny katalog
``ruleDirs``, ``AST_GREP_RULES`` w ``tests/test_zapadki.py``) zatrzymuje zapadka ``ast_grep_rules_without_scope``
w Required CI tego commitu. Tak uruchamia dowód ``tools/scal_pr.py``.

1. Każde ``--wazne PR/W<n>/r<k>``: Ważne ``W<n>`` werdyktu ``FAIL`` rundy ``k`` PR-u (``werdykt_pr.rounds``), na
   liniach dodanych od ``merge-base`` bazy PR-u z SHA linii ``WERDYKT`` tego werdyktu do tego SHA. Ważne jest
   złapane, gdy reguła odpala w miejscu z pola ``Gdzie`` (``szablon_werdyktu.places``: ``plik:linia`` albo
   ``plik:linia-linia``): w najmniejszej funkcji Pythona, która obejmuje to miejsce, a poza funkcją albo w pliku
   spoza Pythona na samych jego liniach. Odpalenie w innym miejscu to ``obok``, a brak odpalenia ``nie``.
2. Fałszywe alarmy: odpalenia na liniach dodanych przez każdy PR z ``--pr`` i ``--ostatnie`` (bez obu 20 ostatnich),
   od ``<merge>^1`` do ``<merge>``.
3. Wystąpienia na całym ``origin/main`` (``--no-ignore hidden``, bo bez tej flagi ast-grep nie wchodzi do
   ``.agents/``), tylko jako dana.

Kończy się ``DOWÓD OK|ODMOWA | <id reguły> | złapane k/n | FP x w y z N PR (p%) | main z``, gdzie ``x`` to odpalenia
w ``y`` PR-ach. ``ODMOWA``, gdy któreś Ważne nie jest złapane albo PR-y z odpaleniem to ponad 10% ``N``; reguła bez
niepustego pola ``files:``, której zapadka nie przyjmie (``odpalenia_ast_grep.unscoped``), błąd GitHuba, brak
werdyktu, ``Gdzie`` bez miejsca ``plik:linia`` i porażka ast-grep to ``DOWÓD ODMOWA | <reguła> | <błąd>``, więc
``DOWÓD OK`` reguły z pliku znaczy też, że reguła może wejść. ``tools/scal_pr.py`` uruchamia ten dowód przy merge'u PR z Ważnym
z polem ``Idiom:`` (``bramka_idiomu``).

Dowód typu albo testu: gdy commit ``--z-commita`` ma plik ``dowody-idiomow/<ID>.json`` w postaci ``tools/mutacje.py --plik``,
``--regula-id`` dowodzi mutacjami złej postaci z ``Gdzie`` zamiast reguły ast-grep. Każde ``--wazne`` ma mutację, która
zmienia tylko pliki jego ``Gdzie`` i dopisuje jako kod całą pierwszą linię jednego z jego miejsc w SHA werdyktu: po
mutacji plik ma więcej linii równych jej bez wcięcia, a w pliku ``.py`` liczy się tylko linia, na której parser ``ast``
zaczyna węzeł w jej wcięciu, więc nie komentarz, nie tekst i nie plik, który się nie parsuje. Polecenie każdej, bez
``oczekiwane``, biegnie w Required CI: ruff albo mypy z ``kroki_lokalne.static_steps`` albo ``-m pytest -q -n 0
tests/<plik>::<test>``, które zakres runu pull requestu wybiera przy zmianie plików mutacji; bez mutacji przechodzi, a z nią
jest WYKRYTA na kopii commitu (silnik z tego checkoutu). Progu fałszywych alarmów nie ma, bo polecenie biegnie w Required
CI każdego PR. ``--bez-kodu-pr`` (status „Werdykt i bramka” z tokenem do statusów) czyta kopię commitu tylko jako dane:
plik dowodu, graf importów (``zakres_runu.pliki_pytest``) i tekst plików mutacji; bieg poleceń, który wykonuje kod
commitu, liczy merge. Granicę tego dowodu pokazują próbki ``ZNANE_LUKI`` w ``tests/test_na_scalonych_pr.py``.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
import github
from kroki_lokalne import static_steps
import mutacje
import odpalenia_ast_grep
import potomne
import rejestr_korzeni
from repo import REMOTE, ROOT
import repo
import silnik_mutacji
from silnik_mutacji import Mutation, Verdict
import szablon_werdyktu
import werdykt_pr
import zakres_runu

AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))
MAJOR = re.compile(r"#?(\d+)/(W\d+)/r(\d+)")
WHERE = "Gdzie:"
# Cała kopia: bez tych flag ast-grep nie wchodzi do katalogu ukrytego (``.agents/``) ani ignorowanego.
WHOLE = ("--no-ignore", "hidden", "--no-ignore", "vcs", "--no-ignore", "dot")
FUNCTIONS = "id: funkcja\nlanguage: python\nrule:\n  kind: function_definition\n"  # także async def
FALSE_ALARMS = 0.10  # najwyższy udział PR-ów z odpaleniem, przy którym dowód przechodzi
CONFIG = "sgconfig.yml"
# Odpowiedzi ast-grep 0.51.0, gdy konfiguracja nie ładuje reguły ``--filter``: brak takiej reguły, brak katalogu
# ``ruleDirs`` i brak pliku konfiguracji.
NOT_LOADED = ("Error: Rule not found", "Error: Cannot read rule directory", "Error: Cannot read configuration")
Rule = tuple[str, ...]  # argumenty ``ast-grep scan`` wybierające regułę: ``--rule PLIK`` albo ``--config`` z ``--filter``
PROOFS = "dowody-idiomow"
PYTEST = ("-m", "pytest", "-q", "-n", "0")


@dataclass(frozen=True)
class Merged:
    label: str  # ``#393`` albo skrót commitu
    commit: str


def merged(numbers: list[int], last: int) -> list[Merged]:
    """Scalone PR-y z ``numbers`` i ``last`` ostatnio scalonych (``recent``), każdy z commitem scalenia."""

    found = {int(pr.label[1:]): pr.commit for pr in recent(last)}
    for number in numbers:
        entry = json.loads(github.gh("pr", "view", str(number), "--json", "number,state,mergeCommit", limit_s=None))
        if entry["state"] != "MERGED" or not entry.get("mergeCommit"):
            raise ValueError(f"PR #{number} nie jest scalony")
        found[number] = entry["mergeCommit"]["oid"]
    return [Merged(f"#{number}", commit) for number, commit in sorted(found.items())]


def recent(count: int) -> list[Merged]:
    """``count`` ostatnich merge'y PR-ów na ``origin/main`` po ``--first-parent``, od najnowszego, po pobraniu ``main``."""

    if not count:
        return []
    found: list[Merged] = []
    for line in repo.git(ROOT, "log", "--first-parent", "--format=%H %s", main_commit()).splitlines():
        commit, _, subject = line.partition(" ")
        if match := github.MERGE.fullmatch(subject):
            found.append(Merged(f"#{match['numer']}", commit))
    return found[:count]


def main_commit() -> str:
    """Commit ``origin/main`` po pobraniu ``main``; błąd pobrania to ``ValueError``."""

    if (done := repo.run_git(ROOT, "fetch", "--quiet", REMOTE, "main")).returncode:
        raise ValueError(f"git fetch {REMOTE} main: {done.stderr.strip()}")
    return repo.git(ROOT, "rev-parse", f"{REMOTE}/main").strip()


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


def fetched(commit: str) -> str | None:
    """Pobiera z ``origin`` commit, którego checkout nie zna; błąd pobrania to jego opis, a sukces ``None``."""

    if repo.commit(ROOT, commit) is not None:
        return None
    done = repo.run_git(ROOT, "fetch", "--quiet", REMOTE, commit)
    return f"git fetch {commit[:8]}: {done.stderr.strip()}" if done.returncode else None


def run_on(pr: Merged, command: list[str], tools: dict[str, bytes], output: Path) -> tuple[int, float, str]:
    """Kod wyjścia, czas w sekundach i ostatnia linia polecenia na kopii commitu scalenia ``pr``."""

    if problem := fetched(pr.commit):
        return 1, 0.0, problem
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


def hits(commit: str, rule: Rule, paths: Iterable[str] | None = None) -> list[tuple[str, int, int]]:
    """Odpalenia reguły (argumenty ``Rule`` albo ``--inline-rules TEKST``) na kopii ``commit``: plik i linie od 1 do 1.

    Bez ``paths`` ast-grep skanuje całą kopię z katalogami ukrytymi i ignorowanymi, a z ``paths`` tylko te pliki, które
    w niej są (jawnie podaną ścieżkę skanuje zawsze); porażka ast-grep to ``ValueError``.
    """

    if AST_GREP is None:
        raise odpalenia_ast_grep.ScanFailed(odpalenia_ast_grep.INSTALL)
    if problem := fetched(commit):
        raise ValueError(problem)
    with potomne.commit_copy(ROOT, commit) as copy:
        targets = [*WHOLE, "."] if paths is None else [path for path in paths if (copy / path).is_file()]
        done = potomne.run([AST_GREP, "scan", *rule, "--error", "--json=stream", *targets], cwd=copy) if targets else None
    if done is not None and done.returncode not in (0, 1):  # 1: odpalenie z ``--error``
        raise ValueError(f"ast-grep {commit[:8]}: {done.stderr.strip()}")
    found = map(json.loads, done.stdout.splitlines() if done else [])
    return [(hit["file"], hit["range"]["start"]["line"] + 1, hit["range"]["end"]["line"] + 1) for hit in found]


def fired(rule: Rule, base: str, head: str) -> list[tuple[str, int]]:
    """Odpalenia reguły na liniach dodanych od ``base`` do ``head`` (``odpalenia_ast_grep.on_added_lines``): plik
    i pierwsza dodana linia węzła; brak ast-grep albo jego porażka to ``odpalenia_ast_grep.ScanFailed``."""

    if problem := fetched(head):
        raise ValueError(problem)
    with potomne.commit_copy(ROOT, head) as copy:
        found = odpalenia_ast_grep.on_added_lines(copy, base, rule, AST_GREP)
    return [(one.path, one.line) for one in found]


def places(where: str, commit: str) -> list[tuple[str, int, int]]:
    """Miejsca pola ``Gdzie`` w ``commit``: plik i zakres linii, rozszerzony do najmniejszej funkcji Pythona wokół;
    pole bez miejsca ``plik:linia`` to ``ValueError``."""

    if not (found := szablon_werdyktu.places(where)):
        raise ValueError(f"{where} nie ma miejsca plik:linia")
    functions = hits(commit, ("--inline-rules", FUNCTIONS), sorted({path for path, _, _ in found if path.endswith(".py")}))
    return [
        (path, *max(((start, end) for file, start, end in functions if file == path and start <= first and last <= end), default=(first, last)))
        for path, first, last in found
    ]


def _shown(found: Iterable[tuple[str, int]]) -> str:
    return ", ".join(f"{path}:{line}" for path, line in found) or "-"


def major(text: str) -> tuple[int, str, int]:
    if not (found := MAJOR.fullmatch(text)):
        raise argparse.ArgumentTypeError(f"Ważne w postaci PR/W<n>/r<k>, np. 1533/W1/r2, a jest {text}")
    return int(found[1]), found[2], int(found[3])


def finding(repository: str, number: int, label: str, round_: int) -> tuple[str, str, str]:
    """SHA werdyktu ``FAIL`` rundy ``round_`` PR-u ``number`` (pobrany), pole ``Gdzie`` jego Ważnego ``label`` i baza PR-u."""

    pull = rejestr_korzeni.pull(repository, number)
    verdict = next((one.verdict for one in werdykt_pr.rounds(pull, werdykt_pr.from_graphql) if one.number == round_ and one.verdict.decision == "FAIL"), None)
    if verdict is None or verdict.commit is None:
        raise ValueError(f"#{number} nie ma werdyktu FAIL rundy r{round_}")
    items = werdykt_pr.from_graphql(verdict)
    starts = [index for index, item in enumerate(items) if item.kind == "h3" and item.text.startswith(f"{label}. ")]
    where = items[starts[0] + 1].text if starts and len(items) > starts[0] + 1 else ""
    if not where.startswith(WHERE):
        raise ValueError(f"#{number} {label} r{round_}: brak pola {WHERE}")
    if problem := fetched(verdict.commit):
        raise ValueError(problem)
    return verdict.commit, where, pull.base


def caught(rule: Rule, repository: str, number: int, label: str, round_: int) -> bool:
    """Drukuje linię Ważnego ``label`` rundy ``round_`` PR-u ``number`` i mówi, czy reguła je złapała."""

    commit, where, base = finding(repository, number, label, round_)
    found = fired(rule, _fork(f"{REMOTE}/{base}", commit), commit)
    targets = places(where, commit)
    inside = [hit for hit in found if any(hit[0] == path and first <= hit[1] <= last for path, first, last in targets)]
    state = "złapane" if inside else "obok" if found else "nie"
    print(f"#{number} {label} r{round_} | {commit[:8]} | {state} | odpalenia {_shown(found)} | {where}", flush=True)
    return bool(inside)


def covers(mutation: Mutation, texts: dict[str, tuple[str, str]], commit: str, where: str) -> bool:
    """Czy mutacja zmienia tylko pliki miejsc pola ``Gdzie`` i dopisuje jako kod całą pierwszą linię któregoś z nich
    w ``commit``; ``texts`` to jej pliki przed nią i po niej (``mutated``)."""

    found = szablon_werdyktu.places(where)
    lines = {"".join(repo.git(ROOT, "show", f"{commit}:{path}").splitlines()[first - 1 : first]).strip() for path, first, _ in found} - {""}
    named = set(texts) <= {path for path, _, _ in found}
    return named and any(_as_code(after, path, lines) > _as_code(before, path, lines) for path, (before, after) in texts.items())


def _as_code(text: str, path: str, lines: set[str]) -> int:
    """Ile linii ``text`` z pliku ``path`` to bez wcięcia linia z ``lines``; w pliku ``.py`` tylko tych, na których parser
    ``ast`` zaczyna węzeł w ich wcięciu, a plik, który się nie parsuje, nie ma żadnej."""

    rows = re.split(r"\r\n|\r|\n", text)
    if not path.endswith(".py"):
        return sum(row.strip() in lines for row in rows)
    try:
        starts = {(getattr(node, "lineno", 0), getattr(node, "col_offset", -1)) for node in ast.walk(ast.parse(text))}
    except (SyntaxError, ValueError, RecursionError):
        return 0
    return sum(row.strip() in lines and (number, len(row) - len(row.lstrip())) in starts for number, row in enumerate(rows, 1))


def mutated(mutation: Mutation, copy: Path) -> dict[str, tuple[str, str]]:
    """Tekst każdego pliku mutacji w kopii ``copy`` przed nią i po niej, zmieniony przez silnik mutacji bez uruchamiania
    polecenia; kotwica, której nie ma dokładnie raz, to ``ValueError`` z werdyktem NIEAKTUALNA."""

    names = sorted({edit.file.as_posix() for edit in mutation.edits})
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        for name in names:
            if (copy / name).is_file():
                (scratch / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(copy / name, scratch / name)
        if stale := silnik_mutacji.apply(scratch, mutation.edits):
            raise ValueError(f"{mutation.name}: {Verdict.STALE} → {stale}")
        return {name: (_text(copy / name), _text(scratch / name)) for name in names}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def outside_ci(mutation: Mutation, copy: Path) -> str | None:
    """Przyczyna, gdy polecenie mutacji nie biegnie w Required CI przy zmianie jej plików w kopii ``copy``."""

    if mutation.expected is None and mutation.command in {step.command[1:] for step in static_steps(copy)}:
        return None
    nodes = mutation.command[len(PYTEST) :]
    if mutation.expected is not None or mutation.command[: len(PYTEST)] != PYTEST or not nodes or not all(node.startswith("tests/") for node in nodes):
        return f"{mutation.name}: polecenie {' '.join(mutation.command)} bez „oczekiwane” to ruff albo mypy zadania „Ruff, mypy” albo {' '.join(PYTEST)} tests/<plik>::<test>"
    chosen = set(zakres_runu.pliki_pytest(zakres_runu.Zdarzenie.PULL_REQUEST, frozenset(edit.file.as_posix() for edit in mutation.edits), copy))
    missing = [node for node in nodes if not {node.partition("::")[0], node.partition("[")[0]} & chosen]
    return f"{mutation.name}: zakres runu pull requestu przy zmianie plików mutacji nie uruchamia {', '.join(missing)}" if missing else None


def mutation_proof(commit: str, rule: str, majors: list[tuple[int, str, int]], *, replay: bool) -> int:
    """Dowód typu albo testu z ``PROOFS/<rule>.json`` kopii ``commit`` (``--help``); kod 0 tylko z ``DOWÓD OK``. Kopię
    ``commit`` czyta tylko jako dane, a kod commitu wykonuje dopiero bieg poleceń z ``replay``."""

    try:
        with potomne.commit_copy(ROOT, commit) as copy:
            mutations = mutacje.from_file(copy / PROOFS / f"{rule}.json", ())
            problems = [problem for mutation in mutations if (problem := outside_ci(mutation, copy))]
            texts = [mutated(mutation, copy) for mutation in mutations]
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        for number, label, round_ in majors:
            sha, where, _ = finding(repository, number, label, round_)
            covered = any(covers(mutation, files, sha, where) for mutation, files in zip(mutations, texts, strict=True))
            print(f"#{number} {label} r{round_} | {sha[:8]} | {'pokryte' if covered else 'nie'} | {where}", flush=True)
            problems += [] if covered else [f"#{number} {label} r{round_}: żadna mutacja nie dopisuje jako kod całej pierwszej linii jego miejsca, zmieniając tylko pliki z Gdzie"]
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"DOWÓD ODMOWA | {rule} | {error}")
        return 1
    if replay and not problems:
        commands = sorted({mutation.command for mutation in mutations})
        base = zip(commands, silnik_mutacji.verdicts([Mutation("podstawa", (), command) for command in commands], workers=1, commit=commit), strict=True)
        problems += [f"podstawa {' '.join(command)} bez mutacji: {last}" for command, (verdict, last) in base if verdict is not Verdict.SURVIVED]
        found = [] if problems else zip(mutations, silnik_mutacji.verdicts(mutations, workers=1, commit=commit), strict=True)
        problems += [f"{mutation.name}: {verdict} → {last}" for mutation, (verdict, last) in found if not silnik_mutacji.in_ci(verdict, last)[0]]
    done = f"przypadki {len(majors)}/{len(majors)} | mutacje {len(mutations)}/{len(mutations)} {'wykryte' if replay else 'bez biegu (--bez-kodu-pr)'}"
    print(f"DOWÓD {'ODMOWA' if problems else 'OK'} | {rule} | {'; '.join(problems) or done}")
    return 1 if problems else 0


def _fork(base: str, commit: str) -> str:
    """``merge-base`` z ``base`` sprzed merge'a, który wniósł ``commit`` (``<merge>^1``), albo z ``base``, gdy go nie wniósł."""

    after = set(repo.git(ROOT, "rev-list", "--ancestry-path", f"{commit}..{base}").split())
    merges = [one for one in repo.git(ROOT, "rev-list", "--first-parent", f"{commit}..{base}").split() if one in after]
    return repo.merge_base(ROOT, f"{merges[-1]}^1" if merges else base, commit)


def proof_on(commit: str, rule: str, majors: list[tuple[int, str, int]], numbers: list[int], last: int, *, replay: bool) -> int:
    """Dowód reguły o id ``rule``, którą ładuje konfiguracja ``CONFIG`` kopii ``commit`` (``--config`` z ``--filter``,
    jak zapadka), jak ``proof``; reguły, której ta konfiguracja nie ładuje, odmawia. Commit z plikiem ``PROOFS/<rule>.json``
    dostaje dowód typu albo testu (``mutation_proof``)."""

    if problem := fetched(commit):
        print(f"DOWÓD ODMOWA | {rule} | {problem}")
        return 1
    if repo.run_git(ROOT, "cat-file", "-e", f"{commit}:{PROOFS}/{rule}.json").returncode == 0:
        return mutation_proof(commit, rule, majors, replay=replay)
    if AST_GREP is None:
        print(f"DOWÓD ODMOWA | {rule} | {odpalenia_ast_grep.INSTALL}")
        return 1
    with potomne.commit_copy(ROOT, commit) as copy:
        chosen = ("--config", str(copy / CONFIG), "--filter", f"^{re.escape(rule)}$")
        # Plik spoza języków ast-grep: skan niczego nie czyta, a konfigurację i filtr ładuje jak każdy.
        loaded = potomne.run([AST_GREP, "scan", *chosen, "--json=stream", "--", CONFIG], cwd=copy)
        if loaded.stderr.startswith(NOT_LOADED):
            print(f"DOWÓD ODMOWA | {rule} | reguły o id {rule} nie ładuje konfiguracja ast-grep repo; połóż ją w reguly-ast-grep/")
            return 1
        if loaded.returncode:
            print(f"DOWÓD ODMOWA | {rule} | ast-grep scan zakończył się kodem {loaded.returncode}: {' '.join(loaded.stderr.split())}")
            return 1
        return checked(rule, chosen, majors, numbers, last)


def proof(rule: Path, majors: list[tuple[int, str, int]], numbers: list[int], last: int) -> int:
    """Dowód reguły z pliku ``rule``; reguły bez niepustego pola ``files:`` odmawia (``odpalenia_ast_grep.unscoped``)."""

    document = yaml.safe_load(rule.read_text(encoding="utf-8"))
    name = str(document["id"])
    if problem := odpalenia_ast_grep.unscoped(document):
        print(f"DOWÓD ODMOWA | {name} | {problem}")
        return 1
    return checked(name, ("--rule", str(rule.resolve())), majors, numbers, last)


def checked(name: str, rule: Rule, majors: list[tuple[int, str, int]], numbers: list[int], last: int) -> int:
    """Trzy biegi dowodu reguły ``name`` (argumenty ast-grep ``rule``) i jego linia końcowa; kod 0 tylko z ``DOWÓD OK``."""

    try:
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        catches = sum(caught(rule, repository, *one) for one in majors)
        alarms = 0
        prs = merged(numbers, last)
        flagged = []
        for pr in prs:
            found = fired(rule, f"{pr.commit}^1", pr.commit)
            alarms += len(found)
            flagged += [pr.label] if found else []
            print(f"FP {pr.label} | {pr.commit[:8]} | {len(found)} | {_shown(found)}", flush=True)
        tip = main_commit()
        existing = len(hits(tip, rule))
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"DOWÓD ODMOWA | {name} | {error}")
        return 1
    print(f"main | {tip[:8]} | {existing}")
    share = len(flagged) / len(prs) if prs else 1.0
    ok = catches == len(majors) and share <= FALSE_ALARMS
    print(f"DOWÓD {'OK' if ok else 'ODMOWA'} | {name} | złapane {catches}/{len(majors)} | FP {alarms} w {len(flagged)} z {len(prs)} PR ({share:.0%}) | main {existing}")
    return 0 if ok else 1


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
    rule = parser.add_mutually_exclusive_group()
    rule.add_argument("--regula", type=Path, help="Dowód reguły ast-grep z tego pliku YAML zamiast polecenia.")
    rule.add_argument("--regula-id", metavar="ID", help="Dowód o tym id na --z-commita: plik dowody-idiomow/ID.json albo reguła ast-grep, którą ładuje sgconfig.yml.")
    parser.add_argument("--z-commita", metavar="REV", help="Commit, z którego --regula-id bierze regułę, np. HEAD PR.")
    parser.add_argument("--wazne", type=major, action="append", default=[], help="Ważne PR/W<n>/r<k>, które reguła ma złapać; powtórz dla kilku.")
    parser.add_argument("--bez-kodu-pr", action="store_true", help="Dowód typu albo testu bez podstawy i mutacji, czyli bez kodu z --z-commita.")
    args = parser.parse_args(arguments[:split])
    if args.regula is not None or args.regula_id is not None:
        if command or not args.wazne or (args.regula_id is None) != (args.z_commita is None):
            parser.error("dowód reguły: --regula PLIK.yml albo --regula-id ID z --z-commita REV i co najmniej jedno --wazne PR/W<n>/r<k>, bez polecenia po --")
        last = args.ostatnie or (0 if args.pr else 20)
        if args.regula_id is not None:
            return proof_on(commit_of(args.z_commita), args.regula_id, args.wazne, args.pr, last, replay=not args.bez_kodu_pr)
        return proof(args.regula, args.wazne, args.pr, last)
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
