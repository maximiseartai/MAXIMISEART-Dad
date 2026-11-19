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
OTHER = "src/inny.py"
SOURCES = {
    CODE: (
        "def pierwsza() -> int:\n    a = 1\n    x = 0\n    y = 0\n    b = 2\n    return a + b + x + y\n\n\n"
        "def druga() -> int:\n    return 2\n\n\n"
        "def trzecia() -> int:\n    return 3\n"
    ),
    OTHER: "def czwarta() -> int:\n    return 4\n\n\ndef piata() -> int:\n    return 5\n",
}
KEYS = {OTHER: ["czwarta"], CODE: ["pierwsza", "druga"]}
PYTHON = shlex.quote(Path(sys.executable).as_posix())


Keys = dict[str, list[str]]
Change = tuple[str, str, str, Keys | None]


def _repo(path: Path, python: str | None) -> Path:
    files = {
        ".gitattributes": (ROOT / ".gitattributes").read_text(encoding="utf-8"),
        f"{SKILL}/SKILL.md": "Model.\n",
        DEFINITIONS: json.dumps({name: dict.fromkeys(names, "") for name, names in KEYS.items()}),
    }
    repo = repository(path, files, ("tools/przesun_model.py",))
    for name, text in SOURCES.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8", newline="")
    rozjazd_modelu.przesun(repo / SKILL, repo)
    commit(repo, "baza")
    if python is not None:
        setup_worktree._merge_model_digests(repo, python)
    return repo


def _branch_change(repo: Path, file: str, old: str, new: str, keys: Keys | None) -> None:
    source = (repo / file).read_text(encoding="utf-8")
    assert source.count(old) == 1, old
    (repo / file).write_text(source.replace(old, new), encoding="utf-8", newline="")
    if keys is not None:
        (repo / DEFINITIONS).write_text(json.dumps({name: dict.fromkeys(names, "") for name, names in keys.items()}), encoding="utf-8")
    rozjazd_modelu.przesun(repo / SKILL, repo)
    commit(repo, f"zmiana {new.strip()}")


def _branches(path: Path, python: str | None, ours: Change, theirs: Change) -> Path:
    repo = _repo(path, python)
    git(repo, "checkout", "--quiet", "-b", "druga")
    _branch_change(repo, *theirs)
    git(repo, "checkout", "--quiet", "-")
    _branch_change(repo, *ours)
    return repo


def _merged(repo: Path) -> bool:
    try:
        git(repo, "merge", "--quiet", "--no-edit", "druga")
    except subprocess.CalledProcessError:
        return False
    return True


OURS_FIRST: Change = (CODE, "    a = 1\n", "    a = 10\n", None)
NEW_DEFINITIONS: tuple[Change, Change] = (
    (OTHER, "    return 4\n", "    return 40\n", {OTHER: ["czwarta", "piata"], CODE: ["pierwsza", "druga"]}),
    (CODE, "    return 2\n", "    return 20\n", {OTHER: ["czwarta"], CODE: ["pierwsza", "druga", "trzecia"]}),
)
CONFLICTING: tuple[Change, Change] = (
    (CODE, "    a = 1\n", "    a = 10\n", {OTHER: ["czwarta"], CODE: ["pierwsza", "druga", "trzecia"]}),
    (CODE, "    return 2\n", "    return 20\n", {OTHER: ["czwarta"], CODE: ["pierwsza"]}),
)
RESOLVED = [
    pytest.param(OURS_FIRST, (CODE, "    return 2\n", "    return 20\n", None), id="rozne-definicje-tego-samego-skilla"),
    pytest.param(OURS_FIRST, (CODE, "    b = 2\n", "    b = 20\n", None), id="ta-sama-definicja-zmieniona-po-obu-stronach"),
    pytest.param(OURS_FIRST, NEW_DEFINITIONS[1], id="nowa-definicja-po-jednej-stronie"),
    pytest.param(*NEW_DEFINITIONS, id="rozne-nowe-definicje-w-roznych-plikach-po-obu-stronach"),
]


@pytest.mark.parametrize(("ours", "theirs"), RESOLVED)
def test_merge_dwoch_galezi_ze_skrotami_przeliczonymi_na_kazdej_przechodzi_bez_konfliktu_a_skroty_zgadzaja_sie_z_kodem(
    tmp_path: Path, ours: Change, theirs: Change
) -> None:
    repo = _branches(tmp_path / "repo", PYTHON, ours, theirs)

    git(repo, "merge", "--quiet", "--no-edit", "druga")

    assert rozjazd_modelu.rozjazd(repo / SKILL, repo) is None
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""


@pytest.mark.parametrize(("ours", "theirs"), [*RESOLVED, pytest.param(*CONFLICTING, id="klucze-zmienione-po-obu-stronach-w-tych-samych-liniach")])
def test_sterownik_nie_daje_konfliktu_tam_gdzie_scalenie_tekstem_go_nie_daje(tmp_path: Path, ours: Change, theirs: Change) -> None:
    as_text = _merged(_branches(tmp_path / "tekstem", None, ours, theirs))

    with_driver = _merged(repo := _branches(tmp_path / "sterownik", PYTHON, ours, theirs))

    assert with_driver or not as_text
    assert not with_driver or rozjazd_modelu.rozjazd(repo / SKILL, repo) is None


def test_checkout_bez_venv_scala_definicje_tekstem_jak_bez_sterownika(tmp_path: Path) -> None:
    repo = _branches(tmp_path / "repo", setup_worktree.VENV_PYTHON, *NEW_DEFINITIONS)
    assert not (repo / setup_worktree.VENV_PYTHON).exists()

    git(repo, "merge", "--quiet", "--no-edit", "druga")

    assert rozjazd_modelu.rozjazd(repo / SKILL, repo) is None


def test_klucze_modelu_zmienione_po_obu_stronach_w_tych_samych_liniach_zostaja_konfliktem_tekstu(tmp_path: Path) -> None:
    repo = _branches(tmp_path / "repo", PYTHON, *CONFLICTING)

    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "merge", "--quiet", "--no-edit", "druga")

    assert git(repo, "diff", "--name-only", "--diff-filter=U") == DEFINITIONS
    assert "<<<<<<< HEAD" in (repo / DEFINITIONS).read_text(encoding="utf-8")


def test_scalenie_bez_checkoutu_jak_w_scal_pr_i_szybko_daje_drzewo_ze_skrotami_obu_stron(tmp_path: Path) -> None:
    repo = _branches(tmp_path / "repo", PYTHON, OURS_FIRST, (CODE, "    return 2\n", "    return 20\n", None))

    merged = repo_gita.merge_tree(repo, "HEAD", "druga")

    assert merged.conflicts == ()
    git(repo, "read-tree", "-u", "--reset", merged.tree)
    assert rozjazd_modelu.rozjazd(repo / SKILL, repo) is None
