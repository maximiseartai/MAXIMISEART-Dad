"""Sprawdzenie modelu Aktualizacji narzędzia nie przechodzi w CI, gdy pokryty kod rozjechał się z modelem.

Model opisuje kod z ``model/definicje.json`` skilla ``verify-aktualizacja-narzedzia`` w Sync commit z jego ``SKILL.md``.
Rozjazd rozstrzyga ``tools/lib/rozjazd_modelu.py`` (``tests/test_rozjazd_modelu.py``), a skrypt w CI kończy się nim
porażką, zanim ruszy TLC.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
OWNER = ROOT / "tools" / "lib" / "rozjazd_modelu.py"
COVERED = "src/rozliczenia/centrum/tool_update.py"
DRIFT = "AKTUALIZACJA: ROZJAZD MODELU Z KODEM"


def _repo(root: Path) -> str:
    """Repozytorium z pokrytym plikiem, jego definicjami i skryptem skilla; zwraca commit synchronizacji."""

    (root / COVERED).parent.mkdir(parents=True)
    (root / COVERED).write_text("X = 1\n", encoding="utf-8")
    skill = root / SCRIPT.relative_to(ROOT).parents[1]
    for script in (SCRIPT, OWNER):
        copy = root / script.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(script, copy)
    (skill / "model").mkdir()
    (skill / "model" / "definicje.json").write_text(json.dumps({COVERED: "cały plik"}), encoding="utf-8")
    git(root, "init", "--quiet")
    return commit(root, "synchronizacja")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_in_ci(root: Path, sync: str) -> subprocess.CompletedProcess[str]:
    skill = root / ".agents" / "skills" / "verify-aktualizacja-narzedzia"
    (skill / "SKILL.md").write_text(f"Sync commit: `{sync}` (main).\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(skill / "scripts" / SCRIPT.name)],
        cwd=root,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_w_ci_pokryty_kod_zmieniony_od_synchronizacji_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    sync = _repo(tmp_path)
    (tmp_path / COVERED).write_text("X = 2\n", encoding="utf-8")
    commit(tmp_path, "zmiana pokrytego kodu")

    done = _check_in_ci(tmp_path, sync[:8])

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"kod opisany modelem zmienił się od {sync[:8]}: {COVERED}." in done.stdout


def test_w_ci_brak_commitu_synchronizacji_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    _repo(tmp_path)

    done = _check_in_ci(tmp_path, "0" * 40)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"Sync commit {'0' * 40} nie ma w tej historii" in done.stdout


def test_poza_ci_rozjazd_tylko_ostrzega_i_sprawdzenie_modelu_biegnie_dalej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module.rozjazd_modelu, "rozjazd", lambda skill, root, dopobierz: "pokryty kod zmienił się")
    (tmp_path / "oczekiwane.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)  # model bez konfiguracji: sprawdzenie biegnie do końca bez TLC
    monkeypatch.setattr(module, "_java", lambda: "java")
    monkeypatch.setattr(module, "_tla_tools", lambda: tmp_path / "tla2tools.jar")

    module.main([])

    printed = capsys.readouterr().out
    assert "UWAGA: pokryty kod zmienił się" in printed
    assert DRIFT not in printed
