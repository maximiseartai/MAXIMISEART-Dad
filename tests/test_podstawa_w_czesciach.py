"""Podstawa skilla z ``ci-czesci`` biegnie w CI w częściach ``MUTACJE_CZESC=k/n`` i żadna jej jednostka nie ginie:
części jednej liczby n składają się w kolejności na całość, a Centrum przejeżdża w nich każdą funkcję ``all`` raz."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import mutacje  # noqa: E402
import kroki_skilli  # noqa: E402
import skrypt_skilla  # noqa: E402

CENTRUM = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(CENTRUM / "scripts"))
    spec = importlib.util.spec_from_file_location("run_centrum_verification", CENTRUM / "scripts" / "run_centrum_verification.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skrypt_skilla_czyta_czesc_z_tej_samej_zmiennej_co_silnik_mutacji_i_plan() -> None:
    assert skrypt_skilla.PART == mutacje.PART


@pytest.mark.parametrize("count", range(1, 8))
def test_n_czesci_bierze_kazda_jednostke_raz_w_jej_kolejnosci_i_zadna_czesc_nie_jest_pusta(count: int) -> None:
    units = tuple(f"j{number}" for number in range(7))

    parts = [skrypt_skilla.part(units, {mutacje.PART: f"{number}/{count}"}) for number in range(1, count + 1)]

    assert sum(parts, ()) == units
    assert all(parts)


@pytest.mark.parametrize("value", ["8/8", "0/3", "3/2", "1", "a/b"])
def test_czesc_spoza_jednostek_to_blad_a_nie_pusty_przebieg(value: str) -> None:
    with pytest.raises(ValueError, match="MUTACJE_CZESC to K/N z 1 <= K <= N <= 7"):
        skrypt_skilla.part(tuple(range(7)), {mutacje.PART: value})


def test_czesci_podstawy_centrum_przejezdzaja_kazda_funkcje_all_raz_w_kolejnosci_all(runner: ModuleType) -> None:
    count = kroki_skilli.ci_parts(CENTRUM / "SKILL.md")
    every = runner.driven("all", {})

    assert count > 1 and count <= len(every)
    for parts in range(1, count + 1):
        driven = [runner.driven("all", {mutacje.PART: f"{number}/{parts}"}) for number in range(1, parts + 1)]
        assert sum(driven, ()) == every, parts
    assert set(every) == set(runner.REQUIRED_SCREENSHOTS) - set(importlib.import_module("drive").EXPLICIT_FEATURES)
    # Część nie zmienia przebiegu jednej funkcji (mutacje skilla), bo dzieli tylko all.
    assert runner.driven("zgloszenie", {mutacje.PART: "2/8"}) == ("zgloszenie",)


def test_zla_czesc_centrum_konczy_przebieg_porazka_zanim_cokolwiek_wystartuje(runner: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv(mutacje.PART, "30/30")

    code = runner.main(["--feature", "all", "--run-dir", "nie-powstanie"])

    assert code == 1
    assert capsys.readouterr().err.startswith("VERIFY FAIL | features=all | MUTACJE_CZESC to K/N z 1 <= K <= N <= 22")
    assert not Path("nie-powstanie").exists()


def test_czesc_all_przekazuje_drive_tylko_funkcje_swojej_czesci(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    driven: list[list[str]] = []

    def step(name: str, arguments: list[str], evidence: Path, timeout: int = 0) -> None:
        """Krok bez procesu: drive zostawia zrzuty funkcji, które dostał, jak prawdziwy (``all`` to każda)."""

        (evidence / f"{name}.txt").write_text("OK\n", encoding="utf-8")
        if name == "drive":
            features = arguments[arguments.index("--feature") + 1 :]
            driven.append(features)
            (evidence / "screenshots").mkdir(exist_ok=True)
            for feature in runner.driven("all", {}) if features == ["all"] else features:
                for shot in runner.REQUIRED_SCREENSHOTS[feature]:
                    (evidence / "screenshots" / shot).write_bytes(b"")

    def launch(root: Path, evidence: Path) -> tuple[None, str]:
        (evidence / "server.txt").write_text("OK\n", encoding="utf-8")
        return None, "http://127.0.0.1:1"

    monkeypatch.setattr(runner, "_preflight", lambda: None)
    monkeypatch.setattr(runner, "_launch", launch)
    monkeypatch.setattr(runner, "_run_step", step)
    monkeypatch.setattr(runner, "QuietMachine", lambda: SimpleNamespace(run=lambda: nullcontext(0.0)))
    monkeypatch.setenv(mutacje.PART, "2/8")
    part = list(runner.driven("all"))

    code = runner.main(["--feature", "all", "--run-dir", str(tmp_path)])

    assert (code, driven) == (0, [part])
    assert 1 < len(part) < len(runner.driven("all", {}))
    assert capsys.readouterr().out.splitlines()[-1].startswith(f"VERIFY OK | features={','.join(part)} | ")


class _Playwright(ModuleType):
    """``playwright.sync_api`` bez przeglądarki: zadanie pytest na Windows nie ma Playwright, a drive go importuje."""

    Error = type("Error", (Exception,), {})
    TimeoutError = type("TimeoutError", (Exception,), {})

    def __getattr__(self, name: str) -> Any:
        return type(name, (), {"__init__": lambda self, *args, **kwargs: None})

    @staticmethod
    @contextmanager
    def sync_playwright() -> Iterator[Any]:
        page = SimpleNamespace(set_default_timeout=lambda timeout: None)
        browser = SimpleNamespace(new_context=lambda **options: SimpleNamespace(new_page=lambda: page), close=lambda: None)
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda: browser))


@pytest.fixture
def drive_centrum(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """``drive_centrum.py`` wczytany na ``_Playwright``; moduły ``drive`` wczytane tu znikają z ``sys.modules`` po teście."""

    monkeypatch.syspath_prepend(str(CENTRUM / "scripts"))
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", _Playwright("playwright.sync_api"))
    for name in [name for name in sys.modules if name == "drive" or name.startswith("drive.")]:
        monkeypatch.delitem(sys.modules, name)
    before = set(sys.modules)
    spec = importlib.util.spec_from_file_location("drive_centrum", CENTRUM / "scripts" / "drive_centrum.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in set(sys.modules) - before:
        del sys.modules[name]


def test_drive_przejezdza_tylko_podane_funkcje_w_podanej_kolejnosci(
    drive_centrum: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    driven: list[str] = []
    for feature in drive_centrum.FEATURES:
        module = getattr(drive_centrum, feature.replace("-", "_"))
        for name in [name for name in vars(module) if name.startswith("drive_")]:
            monkeypatch.setattr(module, name, lambda run, page, feature=feature: driven.append(feature))
    (tmp_path / "fixture.json").write_text(json.dumps({}), encoding="utf-8")
    features = ["uwaga-taty", "logi-uruchomienia", "powiadomienia"]

    code = drive_centrum.main(["--root", str(tmp_path), "--url", "http://127.0.0.1:1", "--evidence", str(tmp_path / "dowody"), "--feature", *features])

    assert (code, driven) == (0, features)
    assert capsys.readouterr().out.splitlines()[-1] == f"DRIVE OK | features={','.join(features)}"
