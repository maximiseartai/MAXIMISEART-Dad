"""Reguły ast-grep z bazy na liniach, które PR dodaje: PR nie osłabia reguły, która go sądzi ([ADR 0036](../../docs/adr/0036-chwast-to-regula.md)).

Required CI uruchamia zapadkę reguł ast-grep kodem i regułami HEAD PR, więc PR, który usuwa regułę z
``reguly-ast-grep/``, dopisuje jej ``ignores:``, zawęża ``files:`` albo zmienia ``sgconfig.yml``, przechodzi ją razem
z kopią idiomu. ``findings`` liczy więc odpalenia reguł z commitu bazy na liniach dodanych przez PR (od
``merge-base`` HEAD z bazą): w odłączonej kopii HEAD PR katalog reguł i ``sgconfig.yml`` zastępuje ich wersja z bazy,
a odpalenia liczy ``odpalenia_ast_grep.on_added_lines``, ta sama droga co zapadka i dowód reguły. Reguły z HEAD na
tych liniach liczy zapadka w Required CI, więc razem obowiązuje suma: reguła usunięta albo osłabiona w PR obowiązuje
go jeszcze w wersji z bazy, a zmiana reguły działa od merge'a PR, który ją wprowadza.

Przypadki reguł (``metadata.przypadki``) liczy ``case_problems``: ``tools/na_scalonych_pr.py --przypadki-regul
--z-commita <scalenie>`` z kodu bazy na commicie scalenia HEAD PR z bazą (``git merge-tree``), czyli na regułach,
które wejdą do bazy, więc reguła łapie każdy swój przypadek i wymienia każdy przypadek reguły bazy o tym samym id,
także gdy PR zmienia krok CI, który liczy przypadki kodem PR. Scalenie, a nie sam HEAD, bo PR rozgałęziony przed
dodaniem przypadku do bazy nie ma go w swoich regułach, choć go nie usuwa.

Biegnie w ``tools/scal_pr.py`` (warunek 6), także w statusie „Werdykt i bramka”, który sądzi kod bazy, nigdy kod PR:
ast-grep czyta pliki PR jako dane, z konfiguracją bazy, a ``tools/na_scalonych_pr.py`` bazy czyta YAML reguł PR.
Moduł importuje tylko bibliotekę standardową, ``repo``, ``potomne`` i ``odpalenia_ast_grep``, bo status uruchamia go
Pythonem runnera.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

import odpalenia_ast_grep
from odpalenia_ast_grep import Finding
import potomne
import repo

RULES = "reguly-ast-grep"
CONFIG = "sgconfig.yml"
CASES_TOOL = Path("tools") / "na_scalonych_pr.py"
CASES_OK = "PRZYPADKI REGUŁ OK |"
CASES_TIMEOUT_S = 180


def findings(root: Path, head: str, base: str) -> list[Finding]:
    """Odpalenia reguł ast-grep commitu ``base`` repozytorium ``root`` na liniach, które ``head`` dodaje od
    ``merge-base`` z ``base``; ``head`` i ``base`` są już w ``root``. Baza bez ``sgconfig.yml`` albo bez katalogu reguł
    nie ma reguł, więc niczego nie zgłasza. Brak ast-grep przy dodanej linii albo jego porażka to
    ``odpalenia_ast_grep.ScanFailed``."""

    if not _has_rules(root, base):
        return []
    since = repo.merge_base(root, head, base)
    ast_grep = shutil.which("ast-grep", path=sysconfig.get_path("scripts")) or shutil.which("ast-grep")
    with potomne.commit_copy(root, head) as copy:
        for command in (("rm", "-r", "-q", "--ignore-unmatch", "--", RULES, CONFIG), ("checkout", base, "--", RULES, CONFIG)):
            repo.run_git(copy, *command).check_returncode()
        return odpalenia_ast_grep.on_added_lines(copy, since, ("--config", str(copy / CONFIG)), ast_grep)


def problems(root: Path, head: str, base: str) -> list[str]:
    """Przyczyny odmowy merge'a: każde odpalenie z ``findings`` z poleceniem naprawy, albo porażka skanu."""

    try:
        found = findings(root, head, base)
    except odpalenia_ast_grep.ScanFailed as error:
        return [f"reguły bazy: {error}"]
    return [
        f"reguły bazy: {finding.path}:{finding.line}: {finding.rule}: {finding.message} (reguła z bazy {base[:7]} obowiązuje PR, "
        "także gdy PR ją usuwa albo osłabia: popraw kod według komunikatu, a zmianę reguły scal osobnym PR-em przed kodem, który z niej korzysta)"
        for finding in found
    ]


def case_problems(root: Path, head: str, base: str) -> list[str]:
    """Przyczyna odmowy z ``tools/na_scalonych_pr.py --przypadki-regul --z-commita <scalenie>`` kodu ``root``
    (commitu ``base``): reguły scalenia ``head`` z ``base`` łapią swoje przypadki i wymieniają przypadki reguł bazy
    o tym samym id. Baza bez reguł niczego nie wymaga, a scalenie z konfliktem to odmowa."""

    if not _has_rules(root, base):
        return []
    merged = repo.merge_tree(root, base, head)
    if merged.conflicts:
        return [f"przypadki reguł: HEAD PR scala się z bazą {base[:7]} z konfliktem ({', '.join(merged.conflicts)}), więc nie wiadomo, które reguły wejdą"]
    author = ("-c", "user.name=scal_pr", "-c", "user.email=scal_pr@localhost")
    commit = repo.git(root, *author, "commit-tree", merged.tree, "-p", base, "-p", head, "-m", "scalenie PR z bazą").strip()
    late = f"przypadki reguł: bez wyniku w {CASES_TIMEOUT_S} s, uruchom ponownie"
    try:
        done = potomne.run([sys.executable, str(root / CASES_TOOL), "--przypadki-regul", "--z-commita", commit], cwd=root, timeout=CASES_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return [late]
    lines = (done.stdout + done.stderr).strip().splitlines()
    last = lines[-1] if lines else ""
    if done.returncode == 0 and last.startswith(CASES_OK):
        return []
    return [f"przypadki reguł: {last or f'kod {done.returncode} bez wyniku'} (przypadek z bazy obowiązuje PR: tools/na_scalonych_pr.py --przypadki-regul --z-commita {commit})"]


def _has_rules(root: Path, base: str) -> bool:
    return all(repo.succeeds(root, "cat-file", "-e", f"{base}:{path}") for path in (RULES, CONFIG))
