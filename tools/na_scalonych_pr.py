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
    .venv/bin/python tools/na_scalonych_pr.py --ostatnie -- tools/mutacje_zmiany.py --baza HEAD^1
    .venv/bin/python tools/na_scalonych_pr.py --commit 04f08b45 -- tools/mutacje_zmiany.py --baza e7cf937b

``--narzedzia origin/main`` bierze narzędzia z commitu zamiast z checkoutu, np. dla pomiaru przed zmianą narzędzia.
``--commit`` bierze dowolny commit, np. HEAD PR-u z werdyktem FAIL, który w tej postaci nie wszedł do ``main``; wtedy
bazę zmiany polecenie podaje samo.

``--ostatnie N`` bierze ``N`` ostatnich merge'y PR-ów (``Merge pull request #N``) z historii ``--first-parent``
``origin/main`` po pobraniu ``main``, a ``--ostatnie`` bez liczby ``CHECK_PRS``: tyle PR-ów bez fałszywego alarmu
pokazuje nowe sprawdzenie (``CODING_STANDARDS.md``).

Kończy się ``NA SCALONYCH PR OK | <n> PR-ów`` albo ``NA SCALONYCH PR FAIL | <PR-y z kodem innym niż 0>``.

Dowód reguły ast-grep (``--regula PLIK.yml`` zamiast polecenia) to trzy biegi reguły na kopii commitu, bez
nadpisywania ``tools/``, więc reguła z zakresem w ``tools/`` widzi linie samego commitu. Odpalenia na liniach dodanych
liczy ``odpalenia_ast_grep.on_added_lines``, ta sama funkcja co zapadka ``syntax_rules``: węzeł reguły obejmuje
którąkolwiek linię dodaną, a linia odpalenia to pierwsza dodana linia węzła (odpala też ``severity: off``):

    .venv/bin/python tools/na_scalonych_pr.py --regula reguly-ast-grep/x.yml --wazne 1533/W1/r2
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
2. Fałszywe alarmy: odpalenia na liniach dodanych przez każdy PR z ``--pr`` i ``--ostatnie`` (bez obu ``RULE_PRS``
   ostatnich), od ``<merge>^1`` do ``<merge>``.
3. Wystąpienia na całym ``origin/main`` (``--no-ignore hidden``, bo bez tej flagi ast-grep nie wchodzi do
   ``.agents/``), tylko jako dana.

Kończy się ``DOWÓD OK|ODMOWA | <id reguły> | złapane k/n | FP x w y z N PR (p%) | main z``, gdzie ``x`` to odpalenia
w ``y`` PR-ach. ``ODMOWA``, gdy któreś Ważne nie jest złapane albo PR-y z odpaleniem to ponad ``FALSE_ALARMS`` ``N``; reguła bez
niepustego pola ``files:``, której zapadka nie przyjmie (``odpalenia_ast_grep.unscoped``), błąd GitHuba, brak
werdyktu, ``Gdzie`` bez miejsca ``plik:linia`` i porażka ast-grep to ``DOWÓD ODMOWA | <reguła> | <błąd>``, więc
``DOWÓD OK`` reguły z pliku znaczy też, że reguła może wejść.

Przypadki reguł (``--przypadki-regul``, krok zadania CI „Ruff, mypy”): każda reguła z katalogów ``ruleDirs``
``sgconfig.yml`` checkoutu ma w polu ``metadata.przypadki`` przypadki, które łapie, i łapie każdy z nich jak Ważne
dowodu (punkt 1): Ważne ``PR/W<n>/r<k>`` albo ``<pełny SHA> plik:linia``, czyli linie dodane przez commit od jego
pierwszego rodzica, dla reguły, która nie powstała z Ważnego z polem ``Gdzie``. Pole czyta tylko ten krok, a ast-grep
je pomija. Kończy się ``PRZYPADKI REGUŁ OK | <n> reguł, <k> przypadków`` albo ``PRZYPADKI REGUŁ FAIL | <reguła>:
<co zrobić> | …``, także dla reguły bez pola:

    .venv/bin/python tools/na_scalonych_pr.py --przypadki-regul
    .venv/bin/python tools/na_scalonych_pr.py --przypadki-regul --z-commita <SHA scalenia HEAD PR z bazą>

Z ``--z-commita REV`` reguły i ich przypadki bierze z kopii ``REV``, a każdy przypadek reguły checkoutu (bazy)
wymienia w ``metadata.przypadki`` któraś reguła ``REV``, która go łapie: przypadek, którego żadna reguła ``REV`` nie
wymienia, to porażka, bez względu na id i plik reguły, więc zmiana ``id:``, przeniesienie reguły do innego pliku ani
usunięcie reguły go nie gubi. Regułę z przypadkami usuwa się więc tylko razem z przeniesieniem każdego przypadku do
reguły, która go łapie. Tak uruchamia go ``tools/scal_pr.py`` z kodu bazy na scaleniu HEAD PR z bazą (warunek 6,
``reguly_bazy``), więc PR, który osłabia regułę i usuwa z niej przypadek, nie przechodzi także wtedy, gdy zmienia ten
krok CI.

Dowód strażnika (``--straznik SELEKTOR --z-commita <HEAD PR>`` z ``--wazne``) to selektor z pola ``Strażnik:`` bloku
Ważnego w sekcji ``## Korzeń``. ``ast-grep <id>`` idzie dowodem reguły o tym id (wyżej, z ``RULE_PRS`` ostatnimi PR-ami),
gdy reguła na HEAD ma to Ważne w polu ``metadata.przypadki``, jedynej liście jej przypadków; każdy inny selektor idzie
dowodem ``straznik.prove``, który opisuje docstring ``tools/lib/straznik.py``, z zakresem funkcji z ``places`` i prozą
z reguły ``PROSE`` na kopii SHA werdyktu. Linia na Ważne i na końcu ``DOWÓD OK|ODMOWA | <selektor> | wykryte k/n``
(przy wyjątku ``wyjątek k/n``); ``tools/scal_pr.py`` uruchamia go przy merge'u każdego PR z Ważnym
(``bramka_straznika``):

    .venv/bin/python tools/na_scalonych_pr.py --straznik 'pytest tests/test_x.py::test_y' --z-commita <HEAD PR> --wazne 2029/W1/r1
"""

from __future__ import annotations

import argparse
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
import time
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
import github
import odpalenia_ast_grep
import potomne
import rejestr_korzeni
from repo import REMOTE, ROOT
import repo
import straznik
import szablon_werdyktu
import werdykt_pr

AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))
MAJOR = re.compile(r"#?(\d+)/(W\d+)/r(\d+)")
COMMIT_CASE = re.compile(r"([0-9a-f]{40}) (\S+)")
CASES = "przypadki"  # pole ``metadata`` reguły ast-grep z przypadkami, które reguła ma łapać
WHERE = "Gdzie:"
# Cała kopia: bez tych flag ast-grep nie wchodzi do katalogu ukrytego (``.agents/``) ani ignorowanego.
WHOLE = ("--no-ignore", "hidden", "--no-ignore", "vcs", "--no-ignore", "dot")
FUNCTIONS = "id: funkcja\nlanguage: python\nrule:\n  kind: function_definition\n"  # także async def
# Proza w pliku Pythona dla ``Strażnik: brak - proza``: komentarz i docstring, czyli instrukcja z samym napisem na
# początku modułu, klasy albo funkcji.
PROSE = "id: proza\nlanguage: python\nrule:\n  any:\n    - kind: comment\n    - kind: expression_statement\n      nthChild: 1\n      has:\n        kind: string\n        stopBy: neighbor\n"
FALSE_ALARMS = 0.10  # najwyższy udział PR-ów z odpaleniem, przy którym dowód reguły przechodzi (próg Tricorder, ADR 0036)
RULE_PRS = 20  # ostatnie scalone PR-y fałszywych alarmów dowodu reguły bez ``--pr`` i ``--ostatnie``
CHECK_PRS = 5  # ostatnie scalone PR-y próby nowego sprawdzenia: ``--ostatnie`` bez liczby (CODING_STANDARDS.md)
CONFIG = "sgconfig.yml"
# Odpowiedzi ast-grep 0.51.0, gdy konfiguracja nie ładuje reguły ``--filter``: brak takiej reguły, brak katalogu
# ``ruleDirs`` i brak pliku konfiguracji.
NOT_LOADED = ("Error: Rule not found", "Error: Cannot read rule directory", "Error: Cannot read configuration")
Rule = tuple[str, ...]  # argumenty ``ast-grep scan`` wybierające regułę: ``--rule PLIK`` albo ``--config`` z ``--filter``


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


@dataclass(frozen=True)
class Probe:
    """Przypadek, który reguła ma złapać: odpalenie na liniach dodanych od ``base`` do ``head`` w miejscu ``where``."""

    label: str  # ``#1584 W1 r1`` albo ``commit``
    base: str
    head: str
    where: str  # tekst pola ``Gdzie:``


def major_probe(repository: str, number: int, label: str, round_: int) -> Probe:
    """Ważne ``label`` werdyktu ``FAIL`` rundy ``round_`` PR-u ``number``: linie dodane od ``merge-base`` bazy PR-u
    do SHA linii ``WERDYKT`` i pole ``Gdzie`` tego Ważnego."""

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
    return Probe(f"#{number} {label} r{round_}", _fork(f"{REMOTE}/{pull.base}", verdict.commit), verdict.commit, where)


def caught(rule: Rule, probe: Probe) -> bool:
    """Drukuje linię przypadku ``probe`` i mówi, czy reguła go złapała."""

    found = fired(rule, probe.base, probe.head)
    targets = places(probe.where, probe.head)
    inside = [hit for hit in found if any(hit[0] == path and first <= hit[1] <= last for path, first, last in targets)]
    state = "złapane" if inside else "obok" if found else "nie"
    print(f"{probe.label} | {probe.head[:8]} | {state} | odpalenia {_shown(found)} | {probe.where}", flush=True)
    return bool(inside)


def _fork(base: str, commit: str) -> str:
    """``merge-base`` z ``base`` sprzed merge'a, który wniósł ``commit`` (``<merge>^1``), albo z ``base``, gdy go nie wniósł."""

    after = set(repo.git(ROOT, "rev-list", "--ancestry-path", f"{commit}..{base}").split())
    merges = [one for one in repo.git(ROOT, "rev-list", "--first-parent", f"{commit}..{base}").split() if one in after]
    return repo.merge_base(ROOT, f"{merges[-1]}^1" if merges else base, commit)


def proof_on(commit: str, rule: str, majors: list[tuple[int, str, int]], numbers: list[int], last: int) -> int:
    """Dowód reguły o id ``rule``, którą ładuje konfiguracja ``CONFIG`` kopii ``commit`` (``--config`` z ``--filter``,
    jak zapadka), jak ``proof``; reguły, której ta konfiguracja nie ładuje, odmawia."""

    if problem := fetched(commit):
        print(f"DOWÓD ODMOWA | {rule} | {problem}")
        return 1
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
        catches = sum(caught(rule, major_probe(repository, *one)) for one in majors)
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


def guard_proof(head: str, text: str, majors: list[tuple[int, str, int]]) -> int:
    """Dowód strażnika z pola ``Strażnik:`` (``straznik``) na HEAD PR-u ``head`` dla Ważnych ``majors``; reguła
    ast-grep idzie dowodem reguły (``proof_on``), a kod 0 jest tylko z ``DOWÓD OK``."""

    try:
        guard = straznik.parse(text)
    except ValueError as error:
        print(f"DOWÓD ODMOWA | {text} | {error}")
        return 1
    if guard.kind is straznik.Kind.AST_GREP:
        return _rule_guard(head, guard, majors)
    try:
        if problem := fetched(head):
            raise ValueError(problem)
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        cases = [_case(guard, major_probe(repository, *one)) for one in majors]
        # Rozwidlenie HEAD od ``main`` sprzed merge'a PR, więc dowód na scalonym już PR widzi jego zmiany jak przed merge'em.
        found = straznik.prove(ROOT, guard, head, _fork(repo.BASE, head), cases)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"DOWÓD ODMOWA | {guard} | {error}")
        return 1
    for outcome in found:
        print(outcome.line, flush=True)
    detected = sum(outcome.detected for outcome in found)
    ok = detected == len(found)
    print(f"DOWÓD {'OK' if ok else 'ODMOWA'} | {guard} | {'wyjątek' if guard.kind in straznik.EXEMPT else 'wykryte'} {detected}/{len(found)}")
    return 0 if ok else 1


def _rule_guard(head: str, guard: straznik.Guard, majors: list[tuple[int, str, int]]) -> int:
    """Strażnik ``ast-grep <id>``: każde Ważne stoi w ``metadata.przypadki`` reguły na HEAD (jedna lista przypadków,
    którą sprawdza też ``--przypadki-regul``), a dowód reguły na nich przechodzi."""

    rule = guard.arguments[0]
    if problem := fetched(head):
        print(f"DOWÓD ODMOWA | {guard} | {problem}")
        return 1
    with potomne.commit_copy(ROOT, head) as copy:
        listed = {case for document in _rule_documents(copy) if str(document["id"]) == rule for case in _cases_of(document)}
    if missing := [f"{number}/{label}/r{round_}" for number, label, round_ in majors if f"{number}/{label}/r{round_}" not in listed]:
        print(f"DOWÓD ODMOWA | {guard} | {', '.join(missing)} nie stoi w metadata.{CASES} reguły {rule} na HEAD: dopisz je tam, to jedyna lista przypadków reguły")
        return 1
    return proof_on(head, rule, majors, [], RULE_PRS)


def _case(guard: straznik.Guard, probe: Probe) -> straznik.Case:
    """Ważne ``probe`` jako przypadek dowodu: zakresy funkcji z ``places`` dla strażnika statycznego, a proza z ``PROSE``
    dla ``brak - proza``; oba czyta ast-grep z kopii SHA werdyktu, jak dowód reguły."""

    if not (raw := szablon_werdyktu.places(probe.where)):
        raise ValueError(f"{probe.where} nie ma miejsca plik:linia")
    scopes = places(probe.where, probe.head) if guard.kind in (straznik.Kind.MYPY, straznik.Kind.RUFF) else []
    python = sorted({path for path, _, _ in raw if path.endswith(".py")})
    prose = hits(probe.head, ("--inline-rules", PROSE), python) if guard.kind is straznik.Kind.PROSE and python else []
    return straznik.Case(probe.label, probe.head, probe.base, tuple(raw), tuple(scopes), tuple(prose))


def case_probe(repository: str, text: str) -> Probe:
    """Przypadek z pola ``metadata.przypadki`` reguły: Ważne ``PR/W<n>/r<k>`` (``major_probe``) albo ``<SHA> plik:linia``,
    czyli linie dodane przez commit od jego pierwszego rodzica; inna postać to ``ValueError``."""

    if found := MAJOR.fullmatch(text):
        return major_probe(repository, int(found[1]), found[2], int(found[3]))
    if found := COMMIT_CASE.fullmatch(text):
        if problem := fetched(found[1]):
            raise ValueError(problem)
        return Probe("commit", f"{found[1]}^1", found[1], f"{WHERE} {found[2]}")
    raise ValueError(f"przypadek {text!r} nie ma postaci PR/W<n>/r<k> ani <pełny SHA> plik:linia")


def _rule_documents(root: Path) -> list[dict[str, Any]]:
    """Każda reguła (dokument YAML) z katalogów ``ruleDirs`` konfiguracji ``CONFIG`` w ``root``."""

    config = yaml.safe_load((root / CONFIG).read_text(encoding="utf-8"))
    files = sorted(path for folder in config["ruleDirs"] for path in (root / folder).rglob("*.y*ml"))
    return [document for path in files for document in yaml.safe_load_all(path.read_text(encoding="utf-8")) if document]


def _cases_of(document: dict[str, Any]) -> list[str]:
    return [str(case) for case in (document.get("metadata") or {}).get(CASES) or []]


def founding(commit: str | None = None) -> int:
    """Każda reguła z katalogów ``ruleDirs`` konfiguracji ``CONFIG`` checkoutu (z ``commit``: jego kopii) łapie każdy
    przypadek ze swojego pola ``metadata.przypadki`` (``caught``), a regułę wybiera ast-grep z tej konfiguracji, jak
    zapadka; z ``commit`` któraś jego reguła wymienia też każdy przypadek reguł checkoutu. Kod 0 tylko
    z ``PRZYPADKI REGUŁ OK``."""

    if commit is None:
        return _founding(ROOT, ())
    if problem := fetched(commit):
        print(f"PRZYPADKI REGUŁ FAIL | {problem}")
        return 1
    with potomne.commit_copy(ROOT, commit) as copy:
        return _founding(copy, tuple(case for document in _rule_documents(ROOT) for case in _cases_of(document)))


def _founding(root: Path, kept: tuple[str, ...]) -> int:
    """``founding`` na regułach ``root``; każdy przypadek z ``kept`` wymienia któraś z nich."""

    rules = _rule_documents(root)
    listed = {case for document in rules for case in _cases_of(document)}
    problems: list[str] = []
    if dropped := sorted(set(kept) - listed):
        problems.append(
            f"PR usuwa z metadata.{CASES} przypadki z bazy {', '.join(dropped)}: każdy z nich wymienia reguła, która go łapie; przywróć je i popraw regułę tak, by je łapała"
        )
    total = 0
    try:
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"PRZYPADKI REGUŁ FAIL | {error}")
        return 1
    for document in rules:
        name = str(document["id"])
        cases = _cases_of(document)
        if not cases:
            problems.append(f"{name}: bez pola metadata.{CASES}; dopisz przypadek, który reguła łapie: Ważne PR/W<n>/r<k> albo <pełny SHA> plik:linia")
            continue
        chosen = ("--config", str(root / CONFIG), "--filter", f"^{re.escape(name)}$")
        for text in cases:
            total += 1
            try:
                if not caught(chosen, case_probe(repository, text)):
                    problems.append(f"{name}: nie łapie {text}; popraw regułę tak, by znów odpalała w jego Gdzie")
            except (ValueError, subprocess.CalledProcessError) as error:
                problems.append(f"{name}: {text}: {error}")
    if problems:
        print(f"PRZYPADKI REGUŁ FAIL | {' | '.join(problems)}")
        return 1
    print(f"PRZYPADKI REGUŁ OK | {len(rules)} reguł, {total} przypadków")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    split = arguments.index("--") if "--" in arguments else len(arguments)
    command = arguments[split + 1 :]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr", type=int, action="append", default=[], help="Numer scalonego PR-u; powtórz dla kilku.")
    parser.add_argument("--ostatnie", type=int, nargs="?", const=CHECK_PRS, default=0, help=f"Tyle ostatnio scalonych PR-ów; bez liczby {CHECK_PRS}.")
    parser.add_argument("--commit", action="append", default=[], help="Dowolny commit, np. HEAD PR-u z werdyktem FAIL.")
    parser.add_argument("--wyniki", type=Path, help="Katalog na pełne wyjście każdego PR-u.")
    parser.add_argument("--narzedzia", metavar="REV", help="Narzędzia z tego commitu zamiast z checkoutu, np. origin/main dla porównania.")
    rule = parser.add_mutually_exclusive_group()
    rule.add_argument("--regula", type=Path, help="Dowód reguły ast-grep z tego pliku YAML zamiast polecenia.")
    rule.add_argument("--regula-id", metavar="ID", help="Dowód reguły ast-grep o tym id, którą ładuje sgconfig.yml na --z-commita.")
    rule.add_argument("--straznik", metavar="SELEKTOR", help=f"Dowód strażnika z pola Strażnik: na HEAD PR --z-commita ({straznik.FORMS}).")
    parser.add_argument("--z-commita", metavar="REV", help="HEAD PR: z niego --regula-id bierze regułę, --straznik kopię, a --przypadki-regul reguły z przypadkami.")
    parser.add_argument("--wazne", type=major, action="append", default=[], help="Ważne PR/W<n>/r<k>, które reguła ma złapać; powtórz dla kilku.")
    rule.add_argument("--przypadki-regul", action="store_true", help="Każda reguła z reguly-ast-grep/ łapie przypadki ze swojego pola metadata.przypadki.")
    args = parser.parse_args(arguments[:split])
    if args.przypadki_regul:
        if command or args.wazne or args.pr or args.ostatnie or args.commit:
            parser.error("--przypadki-regul bierze przypadki z reguł checkoutu albo --z-commita REV, bez innych argumentów")
        return founding(commit_of(args.z_commita) if args.z_commita else None)
    if args.straznik is not None:
        if command or not args.wazne or args.z_commita is None:
            parser.error("dowód strażnika: --straznik SELEKTOR z --z-commita REV i co najmniej jednym --wazne PR/W<n>/r<k>, bez polecenia po --")
        return guard_proof(commit_of(args.z_commita), args.straznik, args.wazne)
    if args.regula is not None or args.regula_id is not None:
        if command or not args.wazne or (args.regula_id is None) != (args.z_commita is None):
            parser.error("dowód reguły: --regula PLIK.yml albo --regula-id ID z --z-commita REV i co najmniej jedno --wazne PR/W<n>/r<k>, bez polecenia po --")
        last = args.ostatnie or (0 if args.pr else RULE_PRS)
        if args.regula_id is not None:
            return proof_on(commit_of(args.z_commita), args.regula_id, args.wazne, args.pr, last)
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
