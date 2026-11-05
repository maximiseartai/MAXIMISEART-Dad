"""Rozjazd modelu skilla z kodem (``tools/lib/rozjazd_modelu.py``): jedno miejsce decyzji dla skryptów modeli i szybko.

Kod opisany modelem leży w ``model/definicje.json`` skilla: plik w całości albo nazwane definicje. Rozjazd to zmiana
takiego kodu od Sync commit z ``SKILL.md`` skilla, a także brak Sync commit w ``SKILL.md`` albo w historii i plik
definicji w innej postaci, bo wtedy model nie jest porównany z kodem. Testy biegną na repozytoriach testu.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import potomne  # noqa: E402
import rozjazd_modelu  # noqa: E402

SKILL = ".agents/skills/verify-model"
CODE = "src/pakiet/kod.py"
WHOLE = "src/pakiet/caly.py"
SOURCE = '''"""Moduł."""


def zapisz() -> int:
    """Zapisuje."""
    return 1


def obok() -> int:
    return 2


class Dziennik:
    def zamknij(self) -> int:
        return 3


class Logi:
    def zamknij(self) -> int:
        return 4


def utworz() -> object:
    kolejka = list()
    return kolejka
'''
DEFINITIONS = {CODE: ["zapisz", "Dziennik.zamknij", "kolejka"], WHOLE: rozjazd_modelu.CALY_PLIK}
STEPS = f"Wykonaj kroki „Bring the model in line” z {SKILL}/SKILL.md, a Sync commit przesuń dopiero, gdy model opisuje kod."


def _repository(root: Path, definitions: object = DEFINITIONS) -> str:
    """Repozytorium ze skillem, jego definicjami i kodem; zwraca commit synchronizacji."""

    for name, text in {CODE: SOURCE, WHOLE: "X = 1\n", "inny.txt": "inny\n", f"{SKILL}/SKILL.md": "Bez Sync commit.\n"}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    (root / SKILL / rozjazd_modelu.DEFINICJE).parent.mkdir(parents=True)
    (root / SKILL / rozjazd_modelu.DEFINICJE).write_text(json.dumps(definitions), encoding="utf-8")
    git(root, "init", "--quiet")
    return commit(root, "synchronizacja")


def _sync(root: Path, sync: str) -> None:
    (root / SKILL / "SKILL.md").write_text(f"Model.\n\n**Sync commit: `{sync}`** (main).\n", encoding="utf-8")


def _edit(root: Path, name: str, old: str, new: str) -> None:
    text = (root / name).read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    (root / name).write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize(
    ("old", "new", "changed"),
    [
        pytest.param("    return 1\n", "    return 10\n", f"{CODE} zapisz", id="cialo-definicji"),
        pytest.param('    """Zapisuje."""\n', '    """Zapisuje inaczej."""\n', f"{CODE} zapisz", id="docstring-definicji"),
        pytest.param("        return 3\n", "        return 30\n", f"{CODE} Dziennik.zamknij", id="metoda-swojej-klasy"),
        pytest.param("    kolejka = list()\n", "    kolejka = dict()\n", f"{CODE} kolejka", id="przypisanie-w-funkcji"),
        pytest.param("def zapisz(", "def zapisz_inaczej(", f"{CODE} zapisz", id="definicji-nie-ma"),
        pytest.param("X = 1\n", '"""Docstring."""\nX = 1\n', WHOLE, id="caly-plik"),
    ],
)
def test_zmiana_kodu_opisanego_modelem_od_sync_commit_jest_rozjazdem_z_plikiem_definicja_i_krokami_naprawy(
    tmp_path: Path, old: str, new: str, changed: str
) -> None:
    sync = _repository(tmp_path)
    _edit(tmp_path, WHOLE if changed == WHOLE else CODE, old, new)
    _sync(tmp_path, sync[:9])

    found = rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path)

    assert found == f"kod opisany modelem zmienił się od {sync[:9]}: {changed}. {STEPS}"


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        pytest.param(CODE, "    return 2\n", "    return 20\n", id="funkcja-obok"),
        pytest.param(CODE, "        return 4\n", "        return 40\n", id="metoda-o-tej-nazwie-w-innej-klasie"),
        pytest.param(CODE, '"""Moduł."""\n', '"""Moduł."""\n\nPOZA = 1\n\n', id="przesuniete-linie"),
        pytest.param("inny.txt", "inny\n", "zmieniony\n", id="plik-spoza-definicji"),
    ],
)
def test_zmiana_obok_kodu_opisanego_modelem_nie_jest_rozjazdem(tmp_path: Path, name: str, old: str, new: str) -> None:
    sync = _repository(tmp_path)
    _edit(tmp_path, name, old, new)
    commit(tmp_path, "zmiana obok")
    _sync(tmp_path, sync[:9])

    assert rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path) is None


def test_sam_skill_md_przesuwajacy_sync_commit_na_zmiane_kodu_nie_jest_rozjazdem(tmp_path: Path) -> None:
    """Zmiana kodu, a po niej osobny commit samego ``SKILL.md`` z Sync commit na tej zmianie: model opisuje kod."""

    sync = _repository(tmp_path)
    _sync(tmp_path, sync[:9])
    commit(tmp_path, "Sync commit")
    _edit(tmp_path, CODE, "    return 1\n", "    return 10\n")
    _edit(tmp_path, WHOLE, "X = 1\n", "X = 2\n")
    changed = commit(tmp_path, "zmiana kodu opisanego modelem")
    before = rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path)
    _sync(tmp_path, changed[:9])
    commit(tmp_path, "model doprowadzony do kodu")

    assert before == f"kod opisany modelem zmienił się od {sync[:9]}: {WHOLE}, {CODE} zapisz. {STEPS}"
    assert rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path) is None


@pytest.mark.parametrize(
    "definitions",
    [
        pytest.param([CODE], id="lista-zamiast-obiektu"),
        pytest.param({}, id="pusty-obiekt"),
        pytest.param({CODE: []}, id="pusta-lista-definicji"),
        pytest.param({CODE: "cały"}, id="inny-napis"),
        pytest.param({CODE: ["zapisz", 1]}, id="nazwa-nie-napisem"),
    ],
)
def test_plik_definicji_w_innej_postaci_jest_rozjazdem(tmp_path: Path, definitions: object) -> None:
    sync = _repository(tmp_path, definitions)
    _sync(tmp_path, sync[:9])

    found = rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path)

    assert found is not None and found.startswith(f"{SKILL}/{rozjazd_modelu.DEFINICJE}: "), found
    assert found.endswith(STEPS)


def test_skill_md_bez_sync_commit_jest_rozjazdem(tmp_path: Path) -> None:
    _repository(tmp_path)

    assert rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path) == f"SKILL.md nie ma Sync commit. {STEPS}"


def test_sync_commit_spoza_historii_jest_rozjazdem(tmp_path: Path) -> None:
    _repository(tmp_path)
    _sync(tmp_path, "0" * 40)

    found = rozjazd_modelu.rozjazd(tmp_path / SKILL, tmp_path, dopobierz=True)

    assert found == f"Sync commit {'0' * 40} nie ma w tej historii; pobierz go albo porównaj kod ręcznie. {STEPS}"


def _shallow_clone(tmp_path: Path) -> tuple[Path, str]:
    """Płytki klon (jak w CI) repozytorium, w którym po Sync commit zmienił się kod opisany modelem i plik obok."""

    origin = tmp_path / "origin"
    origin.mkdir()
    sync = _repository(origin)
    _edit(origin, CODE, "    return 1\n", "    return 10\n")
    _sync(origin, sync[:9])
    commit(origin, "zmiana kodu opisanego modelem")
    _edit(origin, "inny.txt", "inny\n", "zmieniony\n")
    commit(origin, "zmiana obok")
    clone = tmp_path / "klon"
    git(tmp_path, "clone", "--quiet", "--depth", "1", origin.as_uri(), str(clone))
    return clone, sync


def test_plytki_klon_dopobiera_historie_do_sync_commit_tylko_gdy_ma_dopobrac(tmp_path: Path) -> None:
    clone, sync = _shallow_clone(tmp_path)

    without = rozjazd_modelu.rozjazd(clone / SKILL, clone)
    fetched = rozjazd_modelu.rozjazd(clone / SKILL, clone, dopobierz=True)

    assert without == f"Sync commit {sync[:9]} nie ma w płytkim klonie; dopobierz historię: git fetch --unshallow origin. {STEPS}"
    assert fetched == f"kod opisany modelem zmienił się od {sync[:9]}: {CODE} zapisz. {STEPS}"
    assert git(clone, "rev-parse", "--is-shallow-repository") == "false"


def test_plytki_klon_bez_sieci_mowi_ze_nie_dopobral_historii(tmp_path: Path) -> None:
    clone, sync = _shallow_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", (tmp_path / "nie-ma").as_uri())

    found = rozjazd_modelu.rozjazd(clone / SKILL, clone, dopobierz=True)

    assert found == f"nie udało się dopobrać historii do Sync commit {sync[:9]} (git fetch --unshallow); sprawdź sieć. {STEPS}"


def test_dopobranie_historii_ma_limit_czasu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clone, _ = _shallow_clone(tmp_path)
    limits: list[float | None] = []

    def run(command: list[str], *, cwd: Path, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        limits.append(timeout)
        raise subprocess.TimeoutExpired(command, timeout or 0)

    monkeypatch.setattr(potomne, "run", run)

    found = rozjazd_modelu.rozjazd(clone / SKILL, clone, dopobierz=True)

    assert limits == [rozjazd_modelu.FETCH_TIMEOUT_S]
    assert found is not None and found.startswith("nie udało się dopobrać historii do Sync commit"), found
