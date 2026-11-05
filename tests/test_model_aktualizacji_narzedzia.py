"""Sprawdzenie modelu Aktualizacji narzędzia nie przechodzi w CI, gdy pokryty kod rozjechał się z modelem.

Model opisuje kod z ``model/definicje.json`` skilla ``verify-aktualizacja-narzedzia`` w Sync commit z jego ``SKILL.md``.
Rozjazd rozstrzyga ``tools/lib/rozjazd_modelu.py`` (``tests/test_rozjazd_modelu.py``), a skrypt w CI kończy się nim
porażką, zanim ruszy TLC.

Narzędzia TLC (``tla2tools.jar``) skrypt pobiera z GitHub Releases: chwilowy 5xx ponawia, a gdy pobieranie zawiedzie do
końca, mówi, że zawiodło narzędzie, nie model (#930).
"""

from __future__ import annotations

import email.message
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType
import urllib.error

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
OWNER = ROOT / "tools" / "lib" / "rozjazd_modelu.py"
# Właścicielka rozjazdu dopobiera historię przez potomne.run.
POTOMNE = ROOT / "tools" / "lib" / "potomne.py"
# Właściciel przypiętych narzędzi TLC i ich pobierania z ponowieniem.
NARZEDZIA = ROOT / "tools" / "lib" / "narzedzia_tlc.py"
COVERED = "src/rozliczenia/centrum/tool_update.py"
DRIFT = "AKTUALIZACJA: ROZJAZD MODELU Z KODEM"


def _repo(root: Path) -> str:
    """Repozytorium z pokrytym plikiem, jego definicjami i skryptem skilla; zwraca commit synchronizacji."""

    (root / COVERED).parent.mkdir(parents=True)
    (root / COVERED).write_text("X = 1\n", encoding="utf-8")
    skill = root / SCRIPT.relative_to(ROOT).parents[1]
    for script in (SCRIPT, OWNER, POTOMNE, NARZEDZIA):
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
    monkeypatch.setattr(module.rozjazd_modelu, "rozjazd", lambda skill, root: "pokryty kod zmienił się")
    (tmp_path / "oczekiwane.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)  # model bez konfiguracji: sprawdzenie biegnie do końca bez TLC
    monkeypatch.setattr(module, "_java", lambda: "java")
    monkeypatch.setattr(module, "_tla_tools", lambda: tmp_path / "tla2tools.jar")

    module.main([])

    printed = capsys.readouterr().out
    assert "UWAGA: pokryty kod zmienił się" in printed
    assert DRIFT not in printed


JAR = b"tla2tools z atrapy"


def _download_answers(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answers: list[int | OSError]
) -> list[str]:
    """Atrapa ``urlopen`` odpowiada kolejno z ``answers``: kod HTTP (200 daje jar) albo błąd sieci; zwraca adresy prób."""

    calls: list[str] = []

    def urlopen(url: str, timeout: float) -> io.BytesIO:
        calls.append(url)
        code = answers[len(calls) - 1]
        if isinstance(code, OSError):
            raise code
        if code != 200:
            raise urllib.error.HTTPError(url, code, "Gateway Time-out", email.message.Message(), None)
        return io.BytesIO(JAR)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(sys.modules["narzedzia_tlc"], "PRZERWY_S", (0.0, 0.0))
    monkeypatch.setattr(module, "CACHE", tmp_path)
    monkeypatch.setattr(module, "TLA_SHA256", hashlib.sha256(JAR).hexdigest())
    return calls


@pytest.mark.parametrize(
    "awaria", [504, 500, 429, urllib.error.URLError("Connection reset by peer")], ids=["504", "500", "429", "siec"]
)
def test_chwilowa_awaria_github_releases_nie_przerywa_pobrania_tla2tools_bo_skrypt_ponawia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, awaria: int | OSError
) -> None:
    module = _load()
    calls = _download_answers(module, tmp_path, monkeypatch, [awaria, 200])

    jar = module._tla_tools()

    assert jar.read_bytes() == JAR
    assert calls == [module.TLA_URL, module.TLA_URL]


def test_pobranie_tla2tools_ktore_zawodzi_do_konca_konczy_sie_bledem_pobierania_a_nie_modelu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    calls = _download_answers(module, tmp_path, monkeypatch, [504, 502, 503])

    with pytest.raises(SystemExit) as stopped:
        module._tla_tools()

    assert str(stopped.value).startswith(f"BŁĄD POBIERANIA NARZĘDZIA TLC: {module.TLA_URL} po 3 próbach (HTTP 503 ")
    assert len(calls) == 3
    assert not list(tmp_path.glob("*.jar"))


def test_adres_tla2tools_ktorego_nie_ma_konczy_sie_bledem_pobierania_bez_ponawiania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    calls = _download_answers(module, tmp_path, monkeypatch, [404, 200])

    with pytest.raises(SystemExit) as stopped:
        module._tla_tools()

    assert str(stopped.value).startswith(f"BŁĄD POBIERANIA NARZĘDZIA TLC: {module.TLA_URL} odpowiada HTTP 404 ")
    assert len(calls) == 1
