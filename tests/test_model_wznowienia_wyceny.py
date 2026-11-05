"""Sprawdzenie modelu TLA+ wznowienia Wyceny w efenix: rozjazd z kodem w CI i werdykty znanych znalezisk.

Model opisuje definicje z ``model/definicje.json`` skilla ``verify-wznowienie-wyceny-efenix`` w Sync commit z jego
``SKILL.md`` (rozjazd rozstrzyga ``tools/lib/rozjazd_modelu.py``). Zmiana innej części tych plików (``efenix_pricing.py``
zmienia się często) rozjazdem nie jest.

Znane znalezisko z ``model/oczekiwane.json`` wybacza tylko swoją obietnicę i tylko zdarzenie, przed którym zdarzyła się
jego przyczyna: kontrprzykład innej obietnicy albo bez tej przyczyny to nowe naruszenie, jak w ``verify-kolejka-skrzynki``.
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
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import rozjazd_modelu  # noqa: E402

SCRIPT = ROOT / ".agents" / "skills" / "verify-wznowienie-wyceny-efenix" / "scripts" / "sprawdz_wznowienie_wyceny.py"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
OWNER = ROOT / "tools" / "lib" / "rozjazd_modelu.py"
# Właścicielka rozjazdu dopobiera historię przez potomne.run.
POTOMNE = ROOT / "tools" / "lib" / "potomne.py"
# Narzędzia TLC skryptu Aktualizacji narzędzia (przypięte wersje, pobieranie z ponowieniem).
NARZEDZIA = ROOT / "tools" / "lib" / "narzedzia_tlc.py"
DEFINITIONS = ROOT / ".agents" / "skills" / "verify-wznowienie-wyceny-efenix" / "model" / "definicje.json"
PRICING = "src/rozliczenia/efenix_pricing.py"
DRIFT = "WZNOWIENIE WYCENY: ROZJAZD MODELU Z KODEM"

COVERED = (
    "src/rozliczenia/efenix_pricing.py",
    "src/rozliczenia/efenix_emmett_trace.py",
    "src/rozliczenia/efenix_positions.py",
    "src/rozliczenia/efenix_browser.py",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repository(root: Path) -> str:
    """Repozytorium z kodem opisanym modelem i skryptami skilli; zwraca commit synchronizacji."""

    for script in (SCRIPT, TOOLS, OWNER, POTOMNE, NARZEDZIA, DEFINITIONS, *(ROOT / path for path in COVERED)):
        copy = root / script.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(script, copy)
    git(root, "init", "--quiet")
    return commit(root, "synchronizacja")


def _edit(path: Path, anchor: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(anchor) == 1, anchor
    path.write_text(text.replace(anchor, replacement), encoding="utf-8")


def _check_in_ci(root: Path, sync: str) -> subprocess.CompletedProcess[str]:
    skill = root / SCRIPT.relative_to(ROOT).parents[1]
    (skill / "SKILL.md").write_text(f"Sync commit: `{sync}` (main).\n", encoding="utf-8")
    model = skill / "model"
    model.mkdir(exist_ok=True)
    (model / "oczekiwane.json").write_text("{}", encoding="utf-8")  # bez konfiguracji: bez rozjazdu kończy się bez TLC
    return subprocess.run(
        [sys.executable, str(skill / "scripts" / SCRIPT.name)],
        cwd=root,
        env={**os.environ, "GITHUB_ACTIONS": "true", "TLC_JAVA": "java", "TLC_JAR": "tla2tools.jar"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_w_ci_zmieniona_definicja_opisana_modelem_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    sync = _repository(tmp_path)
    _edit(tmp_path / PRICING, "    trace.finished(number)\n", "")
    commit(tmp_path, "bez trace.finished")

    done = _check_in_ci(tmp_path, sync[:9])

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"kod opisany modelem zmienił się od {sync[:9]}: {PRICING} _priced" in done.stdout


def test_w_ci_zmiana_obok_definicji_opisanych_modelem_nie_jest_rozjazdem(tmp_path: Path) -> None:
    sync = _repository(tmp_path)
    # Sprawdzanie (``check`` w ``price_orders``) model nie opisuje.
    _edit(tmp_path / PRICING, "    def check() -> None:\n", "    def check() -> None:\n        pass\n")
    commit(tmp_path, "zmiana Sprawdzania")

    done = _check_in_ci(tmp_path, sync[:9])

    assert (done.returncode, done.stdout.splitlines()[-1]) == (0, "WZNOWIENIE WYCENY OK"), done.stdout + done.stderr


def test_w_ci_brak_commitu_synchronizacji_konczy_sprawdzenie_porazka(tmp_path: Path) -> None:
    _repository(tmp_path)

    done = _check_in_ci(tmp_path, "0" * 40)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"Sync commit {'0' * 40} nie ma w tej historii" in done.stdout


def _verdicts(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, known: list[dict[str, str]], answers: list[object]
) -> list[frozenset[tuple[str, str]]]:
    """Konfiguracja ``k`` ze znanymi znaleziskami ``known``; kolejne przebiegi TLC dają ``answers``. Zwraca wybaczone
    znaleziska każdego przebiegu."""

    (tmp_path / "k.cfg").write_text("\\* konfiguracja testu\n", encoding="utf-8")
    (tmp_path / "oczekiwane.json").write_text(json.dumps({"k": {"znane": known}}), encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)
    monkeypatch.setattr(rozjazd_modelu, "rozjazd", lambda skill, root: None)
    monkeypatch.setenv("TLC_JAVA", "java")
    monkeypatch.setenv("TLC_JAR", "tla2tools.jar")
    forgiven: list[frozenset[tuple[str, str]]] = []
    pending = iter(answers)

    def run(java: str, jar: Path, name: str, forgiven_now: frozenset[tuple[str, str]]) -> object:
        forgiven.append(forgiven_now)
        return next(pending)

    monkeypatch.setattr(module, "_run", run)
    return forgiven


_KNOWN = [{"obietnica": "ZmianaTatyZostaje", "przyczyna": "przerwanie-po-ilosci", "znalezisko": "test"}]


@pytest.mark.parametrize(
    ("own", "rest", "code", "last"),
    [
        pytest.param(("ZmianaTatyZostaje", {"przerwanie-po-ilosci"}), None, 0, "WZNOWIENIE WYCENY OK, ZNANE ZNALEZISKA: 1", id="znane"),
        pytest.param(("ZmianaTatyZostaje", set()), None, 1, "WZNOWIENIE WYCENY: NOWE NARUSZENIE (1)", id="bez-przyczyny"),
        pytest.param(("BladTylkoPoZmianieTaty", {"przerwanie-po-ilosci"}), None, 1, "WZNOWIENIE WYCENY: NOWE NARUSZENIE (1)", id="inna-obietnica"),
        pytest.param(None, None, 1, "WZNOWIENIE WYCENY: ZNALEZISKO ZNIKNĘŁO (1)", id="zniknelo"),
        pytest.param(
            ("ZmianaTatyZostaje", {"przerwanie-po-ilosci"}),
            ("NieCzysciWycenyTaty", set()),
            1,
            "WZNOWIENIE WYCENY: NOWE NARUSZENIE (1)",
            id="reszta-narusza",
        ),
    ],
)
def test_znane_znalezisko_wybacza_tylko_swoja_obietnice_po_swojej_przyczynie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    own: tuple[str, set[str]] | None,
    rest: tuple[str, set[str]] | None,
    code: int,
    last: str,
) -> None:
    module = _load()

    def verdict(found: tuple[str, set[str]] | None) -> object:
        return module.Verdict(None) if found is None else module.Verdict(found[0], frozenset(found[1]))

    forgiven = _verdicts(module, monkeypatch, tmp_path, _KNOWN, [verdict(own), verdict(rest)])

    assert module.main([]) == code
    assert capsys.readouterr().out.splitlines()[-1] == last
    assert forgiven == [frozenset(), frozenset({("ZmianaTatyZostaje", "przerwanie-po-ilosci")})]


def test_kontrprzyklad_daje_obietnice_i_przyczyny_jej_zdarzenia_z_wyjscia_tlc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    output = "\n".join(
        [
            "Error: Invariant ZmianaTatyZostajePozaZnanymi is violated.",
            "State 1: <Initial predicate>",
            "/\\ efenix = <<[A |-> 0, B |-> 0]>>",
            '/\\ naDysku = <<"brak">>',
            "/\\ zlecenie = 1",
            "/\\ nadpisujeTate = {}",
            "State 2: <Wpisz line 170, col 5 to line 179, col 70 of module WznowienieWyceny>",
            "/\\ efenix = <<[A |-> 1, B |-> 1]>>",
            '/\\ naDysku = <<"zaladowany">>',
            "/\\ zlecenie = 1",
            '/\\ nadpisujeTate = {{"przerwanie-po-ilosci",',
            '   "slad-zostal-po-gotowe"}}',
        ]
    )
    monkeypatch.setattr(module, "_tools", lambda: type("T", (), {"_tlc": staticmethod(lambda *arguments: output)}))
    (tmp_path / "k.cfg").write_text("\\* konfiguracja testu\n", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)

    found = module._run("java", Path("tla2tools.jar"), "k", frozenset())

    assert found == module.Verdict("ZmianaTatyZostaje", frozenset({"przerwanie-po-ilosci", "slad-zostal-po-gotowe"}))
    assert "1. okno wpisuje ilość z pliku w zleceniu 1" in capsys.readouterr().out
