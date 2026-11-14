"""Warunek merge'a z polem ``Idiom:`` ([ADR 0036](../../docs/adr/0036-chwast-to-regula.md), „Warunek merge'a” i „Dowód
reguły”): PR z Ważnym z polem ``Idiom: <id>`` albo ``Idiom: <id> jak #N W<n> r<k>`` scala się tylko wtedy, gdy na HEAD
PR stoi reguła ast-grep o tym id, a jej dowód przechodzi.

Ważne z polem to Ważne werdyktów ``FAIL`` tego PR (``szablon_werdyktu.findings``, każda runda). Postać ``Idiom: bez
reguły <klasa> jak #N W<n> r<k>`` niczego nie wymaga.

Dowód to ``tools/na_scalonych_pr.py --regula-id <id> --z-commita <HEAD PR>`` z kodu bazy PR (``tools/scal_pr.py``
biegnie z kopii bazy, linia ``SĘDZIA``), tym samym Pythonem: regułę bierze z katalogów ``ruleDirs`` pliku
``sgconfig.yml`` na HEAD PR, czyli tam, skąd czyta ją zapadka w Required CI, a bez niej odmawia, więc próbka
``ZNANE_LUKI`` nigdy reguły nie zastępuje. Biegnie na każdym przypadku tego id z historii pól ``Idiom:``: na każdym
Ważnym, którego pole nazywa ``<id>``, i na Ważnym z jego ``jak #N W<n> r<k>``, w tym PR i w każdym PR rejestru korzeni
od wdrożenia szablonu werdyktu (``rejestr_korzeni.idioms``). Przechodzi tylko z ostatnią linią ``DOWÓD OK``: dowód łapie ``Gdzie`` każdego
przypadku, ma najwyżej 10% PR-ów z fałszywym alarmem na 20 ostatnich scalonych i odmawia reguły bez pola ``files:``,
której zapadka nie przyjmie (``odpalenia_ast_grep.unscoped``).

Granica: dowód umie dziś tylko ast-grep, więc ``<id>``, które jest kluczem ``banned-api`` ruff albo kontraktem
import-linter, to odmowa, dopóki na HEAD nie stanie reguła ast-grep o tym id. Przypadek ``jak #N W<n> r<k>`` sprzed
szablonu werdyktu (bez pola ``Gdzie``) dowód odrzuca, więc i on daje odmowę. Rejestr czyta bramka tylko wtedy, gdy PR
ma Ważne z polem z id reguły, a błąd GitHuba, Gita albo dowodu to odmowa z przyczyną. Moduł bierze tylko bibliotekę
standardową, bo status „Werdykt i bramka” uruchamia ``tools/scal_pr.py`` systemowym ``python3``; YAML reguły czyta
dowód.
"""

from __future__ import annotations

from collections.abc import Sequence
import subprocess
import sys

import potomne
import rejestr_korzeni
from rejestr_korzeni import IdiomCase
from repo import ROOT
from stan_pr import Pull
import szablon_werdyktu
import werdykt_pr

PROOF = ROOT / "tools" / "na_scalonych_pr.py"
PROOF_OK = "DOWÓD OK |"
FIELD = "Idiom:"
PROOF_TIMEOUT_S = 1800


def problems(pull: Pull) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z warunku pola ``Idiom:``; HEAD i baza PR są już pobrane z ``origin``. Wątek
    bez szablonu werdyktu (``werdykt_pr.rule_applies``) i PR bez słowa ``Idiom:`` w żadnym werdykcie bramka pomija bez
    pytania GitHuba."""

    deployed = werdykt_pr.deployment(pull.base, szablon_werdyktu.ADR)
    if not any(FIELD in str(verdict.get("body") or "") for verdict in pull.verdicts) or not werdykt_pr.rule_applies(pull, deployed):
        return []
    try:
        rounds = werdykt_pr.rounds(pull, werdykt_pr.rendered(pull))
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [f"idiom: GitHub nie wyrenderował treści werdyktów ({error}), uruchom ponownie"]
    own = rejestr_korzeni.idiom_cases(pull.number, rounds)
    wanted = sorted({case.idiom.rule for case in own if case.idiom.rule is not None})
    if not wanted:
        return []
    try:
        history = rejestr_korzeni.idioms(pull.repository, deployed)
    except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
        return [f"idiom: GitHub nie podał rejestru korzeni ({error}), więc nie wiadomo, które przypadki dowód ma złapać; uruchom ponownie"]
    every = [*own, *(case for case in history if case.pull != pull.number)]
    found = []
    for rule in wanted:
        found.extend(_proved(pull, rule, _cases(every, rule)))
    return found


def _cases(every: Sequence[IdiomCase], rule: str) -> list[str]:
    """Przypadki ``PR/W<n>/r<k>`` id ``rule`` z pól ``Idiom:``: Ważne z polem i Ważne z jego ``jak``, po kolei."""

    found: dict[tuple[int, str, int], None] = {}
    for case in every:
        if case.idiom.rule == rule:
            found[(case.pull, case.idiom.label, case.round)] = None
            if case.idiom.like is not None:
                found[case.idiom.like] = None
    return [f"{number}/{label}/r{round_}" for number, label, round_ in sorted(found)]


def _proved(pull: Pull, rule: str, cases: Sequence[str]) -> list[str]:
    arguments = ["--regula-id", rule, "--z-commita", pull.head, *(part for case in cases for part in ("--wazne", case))]
    try:
        done = potomne.run([sys.executable, str(PROOF), *arguments], cwd=ROOT, timeout=PROOF_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return [f"idiom: {rule}: dowód reguły nie skończył się w {PROOF_TIMEOUT_S} s, uruchom ponownie"]
    lines = (done.stdout + done.stderr).strip().splitlines()
    last = lines[-1] if lines else ""
    if done.returncode == 0 and last.startswith(PROOF_OK):
        return []
    return [
        f"idiom: {rule}: Ważne {', '.join(cases)} ma pole Idiom: {rule}, a dowód reguły nie przeszedł (kod {done.returncode}): {last or 'bez wyniku'}; "
        f"dodaj albo popraw regułę ast-grep o id {rule} i sprawdź ją poleceniem tools/na_scalonych_pr.py {' '.join(arguments)}"
    ]
