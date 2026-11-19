from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git, repository

import repo as repo_gita
import rozjazd_modelu
import setup_worktree

ROOT = Path(__file__).resolve().parents[1]
SKILL = ".agents/skills/verify-model"
DEFINITIONS = f"{SKILL}/{rozjazd_modelu.DEFINICJE}"
CODE = "src/kod.py"
SOURCE = (
    "def pierwsza() -> int:\n    a = 1\n    x = 0\n    y = 0\n    b = 2\n    return a + b + x + y\n\n\n"
    "def druga() -> int:\n    return 2\n\n\n"
    "def trzecia() -> int:\n    return 3\n"
)


Change = tuple[str, str, tuple[str, ...] | None]


def _repo(tmp_path: Path) -> Path:
    files = {
        ".gitattributes": (ROOT / ".gitattributes").read_text(encoding="utf-8"),
        CODE: SOURCE,
        f"{SKILL}/SKILL.md": "Model.\n",
        DEFINITIONS: json.dumps({CODE: {"pierwsza": "", "druga": ""}}),
    }
    repo = repository(tmp_path / "repo", files, ("tools/przesun_model.py",))
    rozjazd_modelu.przesun(repo / SKILL, repo)
    commit(repo, "baza")
    setup_worktree._merge_model_digests(repo, shlex.quote(Path(sys.executable).as_posix()))
    return repo


def _branch_change(repo: Path, old: str, new: str, keys: tuple[str, ...] | None = None) -> None:
    source = (repo / CODE).read_text(encoding="utf-8")
    assert source.count(old) == 1, old
    (repo / CODE).write_text(source.replace(old, new), encoding="utf-8", newline="")
    if keys is not None:
        (repo / DEFINITIONS).write_text(json.dumps({CODE: dict.fromkeys(keys, "")}), encoding="utf-8")
    rozjazd_modelu.przesun(repo / SKILL, repo)
    commit(repo, f"zmiana {new.strip()}")


def _branches(repo: Path, ours: Change, theirs: Change) -> None:
    git(repo, "checkout", "--quiet", "-b", "druga")
    _branch_change(repo, *theirs)
    git(repo, "checkout", "--quiet", "-")
    _branch_change(repo, *ours)


@pytest.mark.parametrize(
    ("ours", "theirs"),
    [
        pytest.param(("    a = 1\n", "    a = 10\n", None), ("    return 2\n", "    return 20\n", None), id="rozne-definicje-tego-samego-skilla"),
        pytest.param(("    a = 1\n", "    a = 10\n", None), ("    b = 2\n", "    b = 20\n", None), id="ta-sama-definicja-zmieniona-po-obu-stronach"),
        pytest.param(("    a = 1\n", "    a = 10\n", None), ("    return 2\n", "    return 20\n", ("pierwsza", "druga", "trzecia")), id="nowa-definicja-po-jednej-stronie"),
    ],
)
def test_merge_dwoch_galezi_ze_skrotami_przeliczonymi_na_kazdej_przechodzi_bez_konfliktu_a_skroty_zgadzaja_sie_z_kodem(
    tmp_path: Path, ours: Change, theirs: Change
) -> None:
    repo = _repo(tmp_path)
    _branches(repo, ours, theirs)

    git(repo, "merge", "--quiet", "--no-edit", "druga")

    assert rozjazd_modelu.rozjazd(repo / SKILL, repo) is None
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_klucze_modelu_zmienione_po_obu_stronach_inaczej_zostaja_konfliktem(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _branches(repo, ("    a = 1\n", "    a = 10\n", ("pierwsza", "druga", "trzecia")), ("    return 2\n", "    return 20\n", ("pierwsza",)))

    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "merge", "--quiet", "--no-edit", "druga")

    assert git(repo, "diff", "--name-only", "--diff-filter=U") == DEFINITIONS
    assert "<<<<<<< HEAD" in (repo / DEFINITIONS).read_text(encoding="utf-8")


def test_scalenie_bez_checkoutu_jak_w_scal_pr_i_szybko_daje_drzewo_ze_skrotami_obu_stron(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _branches(repo, ("    a = 1\n", "    a = 10\n", None), ("    return 2\n", "    return 20\n", None))

    merged = repo_gita.merge_tree(repo, "HEAD", "druga")

    assert merged.conflicts == ()
    git(repo, "read-tree", "-u", "--reset", merged.tree)
    assert rozjazd_modelu.rozjazd(repo / SKILL, repo) is None
