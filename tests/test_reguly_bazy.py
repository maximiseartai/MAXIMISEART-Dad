"""Reguły ast-grep z bazy na liniach dodanych przez PR (``tools/lib/reguly_bazy.py``, warunek 6 ``tools/scal_pr.py``).

Tabela przypadków: zmiana PR na bazie z regułą ``zakazane-wywolanie`` (``files: src/**``) → czy reguła z bazy ją
zgłasza. Zgłasza wywołanie dodane przez PR także wtedy, gdy PR usuwa plik reguły, dopisuje jej ``ignores:``, zawęża
``files:`` albo opróżnia ``ruleDirs`` w ``sgconfig.yml``. Nie zgłasza samego osłabienia reguły bez dodanego
wywołania, wywołania, które stało już w ``merge-base``, ani wywołania, które łapie tylko reguła dodana w PR: tę liczy
zapadka w Required CI regułami HEAD.
"""

from __future__ import annotations

from collections.abc import Mapping
import shutil
import sysconfig
from pathlib import Path

import pytest

from tests.fixtures.git_repo import commit, git

import reguly_bazy

pytestmark = pytest.mark.skipif(
    shutil.which("ast-grep", path=sysconfig.get_path("scripts")) is None,
    reason="ast-grep z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt",
)

RULE = "id: zakazane-wywolanie\nlanguage: python\nseverity: error\nmessage: Zamień zakazane() na dozwolone().\nfiles:\n  - src/**\nrule:\n  pattern: zakazane()\n"
OTHER = "id: inne-wywolanie\nlanguage: python\nseverity: error\nmessage: Zamień inne() na dozwolone().\nfiles:\n  - src/**\nrule:\n  pattern: inne()\n"
CONFIG = "ruleDirs:\n  - reguly-ast-grep\n"
CALL = "zakazane()\n"
BASE = {"sgconfig.yml": CONFIG, "reguly-ast-grep/zakazane-wywolanie.yml": RULE, "src/stary.py": "X = 1\n"}

# Zmiana PR: pliki zapisane (tekst) albo usunięte (None) → czy reguła z bazy zgłasza src/nowy.py:1.
ZMIANY_PR: dict[str, tuple[dict[str, str | None], bool]] = {
    "wywołanie bez zmiany reguły": ({"src/nowy.py": CALL}, True),
    "PR usuwa plik reguły": ({"reguly-ast-grep/zakazane-wywolanie.yml": None, "src/nowy.py": CALL}, True),
    "PR dopisuje ignores:": ({"reguly-ast-grep/zakazane-wywolanie.yml": RULE + "ignores:\n  - src/nowy.py\n", "src/nowy.py": CALL}, True),
    "PR zawęża files:": ({"reguly-ast-grep/zakazane-wywolanie.yml": RULE.replace("src/**", "src/inne/**"), "src/nowy.py": CALL}, True),
    "PR opróżnia ruleDirs": ({"sgconfig.yml": "ruleDirs: []\n", "src/nowy.py": CALL}, True),
    "PR osłabia regułę bez wywołania": ({"reguly-ast-grep/zakazane-wywolanie.yml": None, "src/nowy.py": "Y = 2\n"}, False),
    "wywołanie tylko reguły dodanej w PR": ({"reguly-ast-grep/inne-wywolanie.yml": OTHER, "src/nowy.py": "inne()\n"}, False),
}


def _write(root: Path, files: Mapping[str, str | None]) -> None:
    for name, text in files.items():
        if text is None:
            (root / name).unlink()
        else:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")


def _repository(root: Path, base: Mapping[str, str | None]) -> str:
    git(root, "init", "--quiet", "--initial-branch", "main")
    _write(root, base)
    return commit(root, "baza")


@pytest.mark.parametrize(("change", "reported"), ZMIANY_PR.values(), ids=ZMIANY_PR)
def test_regula_z_bazy_zglasza_wywolanie_dodane_przez_pr_takze_gdy_pr_ja_oslabia(
    tmp_path: Path, change: dict[str, str | None], reported: bool
) -> None:
    base = _repository(tmp_path, BASE)
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    _write(tmp_path, change)
    head = commit(tmp_path, "pr")

    found = [(finding.path, finding.line, finding.rule) for finding in reguly_bazy.findings(tmp_path, head, base)]
    assert found == ([("src/nowy.py", 1, "zakazane-wywolanie")] if reported else [])


def test_wywolanie_z_merge_base_nie_jest_linia_pr_a_regula_dodana_w_bazie_po_rozgalezieniu_obowiazuje(tmp_path: Path) -> None:
    """Linie liczą się od ``merge-base``: stare wywołanie z ``src/stary.py`` nie jest linią PR, a reguła, którą baza
    dodała po rozgałęzieniu PR, zgłasza linię, którą PR dodał, bo obowiązuje go baza z chwili merge'a."""

    fork = _repository(tmp_path, {**BASE, "src/stary.py": CALL})
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    _write(tmp_path, {"src/nowy.py": "inne()\n"})
    head = commit(tmp_path, "pr")
    git(tmp_path, "switch", "--quiet", "main")
    _write(tmp_path, {"reguly-ast-grep/inne-wywolanie.yml": OTHER})
    base = commit(tmp_path, "nowa reguła w bazie")

    assert fork != base
    assert [(finding.path, finding.rule) for finding in reguly_bazy.findings(tmp_path, head, base)] == [("src/nowy.py", "inne-wywolanie")]


def test_odmowa_mowi_co_zrobic_gdy_pr_usuwa_regule_ktora_go_sadzi(tmp_path: Path) -> None:
    base = _repository(tmp_path, BASE)
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    _write(tmp_path, {"reguly-ast-grep/zakazane-wywolanie.yml": None, "src/nowy.py": CALL})
    head = commit(tmp_path, "pr")

    assert reguly_bazy.problems(tmp_path, head, base) == [
        "reguły bazy: src/nowy.py:1: zakazane-wywolanie: Zamień zakazane() na dozwolone(). (reguła z bazy "
        f"{base[:7]} obowiązuje PR, także gdy PR ją usuwa albo osłabia: popraw kod według komunikatu, a zmianę reguły "
        "scal osobnym PR-em przed kodem, który z niej korzysta)"
    ]


def test_baza_bez_regul_niczego_nie_zglasza(tmp_path: Path) -> None:
    base = _repository(tmp_path, {"src/stary.py": "X = 1\n"})
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    _write(tmp_path, {**BASE, "src/nowy.py": CALL})
    head = commit(tmp_path, "pr")

    assert reguly_bazy.findings(tmp_path, head, base) == []
