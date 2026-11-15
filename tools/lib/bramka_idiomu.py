"""Warunek merge'a z polem ``Idiom:`` ([ADR 0036](../../docs/adr/0036-chwast-to-regula.md), „Warunek merge'a” i „Dowód
reguły”): PR z Ważnym z polem ``Idiom: <id>`` albo ``Idiom: <id> jak #N W<n> r<k>`` scala się tylko wtedy, gdy na HEAD
PR stoi reguła ast-grep albo dowód typu albo testu o tym id, a jego dowód przechodzi.

Ważne z polem to Ważne werdyktów ``FAIL`` tego PR (``szablon_werdyktu.findings``, każda runda). Postać ``Idiom: bez
reguły <klasa> jak #N W<n> r<k>`` niczego nie wymaga.

Dowód to ``tools/na_scalonych_pr.py --regula-id <id> --z-commita <HEAD PR>`` z kodu bazy PR (``tools/scal_pr.py``
biegnie z kopii bazy, linia ``SĘDZIA``), tym samym Pythonem: regułę wybiera sam ast-grep z ``sgconfig.yml`` na HEAD PR
(``--config`` z ``--filter``), tym samym loaderem co zapadka w Required CI, a reguły, której ta konfiguracja nie
ładuje, odmawia, więc próbka ``ZNANE_LUKI`` nigdy reguły nie zastępuje. Biegnie na każdym przypadku tego id z historii
pól ``Idiom:``: na każdym Ważnym, którego pole nazywa ``<id>``, i na Ważnym z jego ``jak #N W<n> r<k>``, w tym PR i w każdym PR rejestru korzeni
od wdrożenia szablonu werdyktu z frazą ``"Idiom: <id>"`` (``rejestr_korzeni.idioms``). Przechodzi tylko z ostatnią linią ``DOWÓD OK``: dowód łapie ``Gdzie`` każdego
przypadku i ma najwyżej 10% PR-ów z fałszywym alarmem na 20 ostatnich scalonych, a regułę bez pola ``files:`` w ``reguly-ast-grep/``
zatrzymuje zapadka ``ast_grep_rules_without_scope`` w Required CI HEAD PR.

Dowód typu albo testu (plik ``dowody-idiomow/<id>.json``, ``tools/na_scalonych_pr.py --help``) uruchamia kod HEAD PR,
więc status „Werdykt i bramka” podaje dowodowi ``--bez-kodu-pr``, a bieg polecenia liczy merge.

Granica: dowód umie dziś ast-grep, typ i test, więc ``<id>``, które jest kluczem ``banned-api`` ruff albo kontraktem
import-linter, to odmowa, dopóki na HEAD nie stanie reguła ast-grep o tym id. Przypadek ``jak #N W<n> r<k>`` sprzed
szablonu werdyktu (bez pola ``Gdzie``) dowód odrzuca, więc i on daje odmowę. Rejestr czyta bramka tylko wtedy, gdy PR
ma Ważne z polem z id reguły, a błąd GitHuba, Gita albo dowodu to odmowa z przyczyną. Przyczyna, przy której dowód
nie ma jeszcze danych (GitHub nie wyrenderował werdyktów albo nie podał rejestru), to ``stan_pr.Waiting``, bo mija
przy następnym runie bez zmiany w PR; odmowa dowodu i jego przekroczony czas wymagają reguły albo poprawki autora.
Dowody wszystkich reguł PR mają razem ``PROOF_TIMEOUT_S``: status „Werdykt i bramka” uruchamia bramkę w jobie
z limitem 10 min (``.github/workflows/werdykt-i-bramka.yml``), więc przekroczony czas ma być przyczyną w statusie,
zanim Actions zabije job bez statusu. Dowód na 20 scalonych PR-ach trwał 14.11.2026 na Macu 24 s
(``tools/na_scalonych_pr.py --regula-id kotwica-konca-linii --z-commita origin/main --wazne 1495/W1/r1``).
Granica: błąd GitHuba wewnątrz dowodu kończy się linią ``DOWÓD ODMOWA`` jak brak reguły, więc to zwykła przyczyna.
Moduł bierze tylko bibliotekę standardową, bo status „Werdykt i bramka” uruchamia ``tools/scal_pr.py`` Pythonem
runnera; regułę ładuje ast-grep w dowodzie, który workflow statusu instaluje z dodatku dev.
"""

from __future__ import annotations

from collections.abc import Sequence
import subprocess
import sys
import time

import potomne
import rejestr_korzeni
from rejestr_korzeni import IdiomCase
from repo import ROOT
from stan_pr import Pull, Waiting
import szablon_werdyktu
import werdykt_pr

PROOF = ROOT / "tools" / "na_scalonych_pr.py"
PROOF_OK = "DOWÓD OK |"
FIELD = "Idiom:"
PROOF_TIMEOUT_S = 300


def problems(pull: Pull, *, runs_pull_code: bool) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z warunku pola ``Idiom:``; HEAD i baza PR są już pobrane z ``origin``. Wątek
    bez szablonu werdyktu (``werdykt_pr.rule_applies``) i PR bez słowa ``Idiom:`` w żadnym werdykcie bramka pomija bez
    pytania GitHuba. Bez ``runs_pull_code`` dowód nie uruchamia kodu PR (``--bez-kodu-pr``)."""

    deployed = werdykt_pr.deployment(pull.base, szablon_werdyktu.ADR)
    if not any(FIELD in str(verdict.get("body") or "") for verdict in pull.verdicts) or not werdykt_pr.rule_applies(pull, deployed):
        return []
    try:
        rounds = werdykt_pr.rounds(pull, werdykt_pr.rendered(pull))
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [Waiting(f"idiom: GitHub nie wyrenderował treści werdyktów ({error}), uruchom ponownie")]
    own = rejestr_korzeni.idiom_cases(pull.number, rounds)
    wanted = sorted({case.idiom.rule for case in own if case.idiom.rule is not None})
    if not wanted:
        return []
    try:
        history = {rule: rejestr_korzeni.idioms(pull.repository, deployed, rule) for rule in wanted}
    except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
        return [Waiting(f"idiom: GitHub nie podał rejestru korzeni ({error}), więc nie wiadomo, które przypadki dowód ma złapać; uruchom ponownie")]
    deadline = time.monotonic() + PROOF_TIMEOUT_S
    found = []
    for rule in wanted:
        every = [*own, *(case for case in history[rule] if case.pull != pull.number)]
        found.extend(_proved(pull, rule, _cases(every, rule), deadline - time.monotonic(), runs_pull_code))
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


def _proved(pull: Pull, rule: str, cases: Sequence[str], left: float, runs_pull_code: bool) -> list[str]:
    """Przyczyna odmowy z dowodu reguły ``rule`` na przypadkach ``cases``, który ma ``left`` sekund z ``PROOF_TIMEOUT_S``."""

    arguments = ["--regula-id", rule, "--z-commita", pull.head, *(part for case in cases for part in ("--wazne", case)), *([] if runs_pull_code else ["--bez-kodu-pr"])]
    late = f"idiom: {rule}: dowody reguł tego PR nie skończyły się w {PROOF_TIMEOUT_S} s, uruchom ponownie"
    if left <= 0:
        return [late]
    try:
        done = potomne.run([sys.executable, str(PROOF), *arguments], cwd=ROOT, timeout=left, echo=True)
    except subprocess.TimeoutExpired:
        return [late]
    lines = (done.stdout + done.stderr).strip().splitlines()
    last = lines[-1] if lines else ""
    if done.returncode == 0 and last.startswith(PROOF_OK):
        return []
    return [
        f"idiom: {rule}: Ważne {', '.join(cases)} ma pole Idiom: {rule}, a dowód reguły nie przeszedł (kod {done.returncode}): {last or 'bez wyniku'}; "
        f"dodaj albo popraw regułę ast-grep o id {rule} albo dowód typu albo testu (tools/na_scalonych_pr.py --help) i sprawdź go poleceniem tools/na_scalonych_pr.py {' '.join(arguments)}"
    ]
