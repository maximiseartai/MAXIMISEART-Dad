"""Strażnik drzewa repozytorium (``tests/fixtures/drzewo_repo.py``, haki sesji w ``tests/conftest.py``, #1864)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tests import conftest
from tests.fixtures import drzewo_repo
from tests.fixtures.git_repo import commit, git


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "modul.py").write_text("A = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    git(root, "init", "--quiet")
    commit(root, "baza")
    return root


class _Session:
    def __init__(self) -> None:
        self.config = pytest.Config.__new__(pytest.Config)
        self.config.stash = pytest.Stash()
        self.exitstatus: int = pytest.ExitCode.OK


def test_sesja_ktora_zostawila_w_drzewie_plik_albo_zmiane_konczy_sie_porazka_z_jego_sciezka(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plik nieśledzony i zmieniony plik śledzony, których nie było na starcie, wywracają sesję i stoją w komunikacie;
    plik wykluczony ``.gitignore`` repozytorium i zmiana sprzed startu sesji nie."""

    root = _checkout(tmp_path)
    monkeypatch.setattr(drzewo_repo, "REPO", root)
    (root / "przed_sesja.txt").write_text("autor\n", encoding="utf-8")
    session = _Session()

    conftest.pytest_sessionstart(cast(pytest.Session, session))
    (root / "debug.log").write_text("[0101/000000.000:ERROR] x\n", encoding="utf-8")
    (root / "src" / "modul.py").write_text("A = 1\nB = 2\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "wynik.txt").write_text("ignorowany\n", encoding="utf-8")
    conftest.pytest_sessionfinish(cast(pytest.Session, session), pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert "pliki z liniami dodanymi od HEAD: debug.log ([0101/000000.000:ERROR] x), src/modul.py (A = 1 / B = 2) |" in capsys.readouterr().out


def test_sesja_bez_nowego_pliku_w_drzewie_zostaje_zielona(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = _checkout(tmp_path)
    monkeypatch.setattr(drzewo_repo, "REPO", root)
    (root / "przed_sesja.txt").write_text("autor\n", encoding="utf-8")
    session = _Session()

    conftest.pytest_sessionstart(cast(pytest.Session, session))
    conftest.pytest_sessionfinish(cast(pytest.Session, session), pytest.ExitCode.OK)

    assert (session.exitstatus, capsys.readouterr().out) == (pytest.ExitCode.OK, "")


def test_checkout_bez_commitu_nie_ma_od_czego_liczyc_wiec_straznik_milczy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "kopia"
    root.mkdir()
    git(root, "init", "--quiet")
    monkeypatch.setattr(drzewo_repo, "REPO", root)
    session = _Session()

    conftest.pytest_sessionstart(cast(pytest.Session, session))
    (root / "debug.log").write_text("x\n", encoding="utf-8")
    conftest.pytest_sessionfinish(cast(pytest.Session, session), pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.OK
