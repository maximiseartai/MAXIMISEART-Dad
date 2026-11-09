"""Kontrakt i build scalają się bez konfliktu: ``merge=wygenerowane`` z ``.gitattributes`` i sterownik z ``tools/setup_worktree.py``."""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.git_repo import commit, git, repository

import setup_worktree

ROOT = Path(__file__).resolve().parents[1]
GENERATED = (
    "frontend/src/api/openapi.json",
    "frontend/src/api/generated/types.gen.ts",
    "src/rozliczenia/centrum/static/assets/index.js",
)


def _write(repo: Path, text: str) -> None:
    for name in GENERATED:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(text.encode())


def test_scalenie_dwoch_galezi_zostawia_w_plikach_generowanych_wersje_head_bez_konfliktu(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {".gitattributes": (ROOT / ".gitattributes").read_text(encoding="utf-8")})
    _write(repo, "baza\n")
    commit(repo, "baza")
    setup_worktree._merge_generated(repo)
    git(repo, "checkout", "--quiet", "-b", "druga")
    _write(repo, "druga\n")
    commit(repo, "druga gałąź")
    git(repo, "checkout", "--quiet", "-")
    _write(repo, "pierwsza\n")
    commit(repo, "pierwsza gałąź")

    git(repo, "merge", "--quiet", "--no-edit", "druga")

    assert {name: (repo / name).read_bytes() for name in GENERATED} == dict.fromkeys(GENERATED, b"pierwsza\n")
