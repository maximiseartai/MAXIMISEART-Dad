"""Podstawa skilla z ``ci-czesci`` biegnie w CI w częściach ``MUTACJE_CZESC=k/n`` i żadna jej jednostka nie ginie:
części jednej liczby n składają się w kolejności na całość, a Centrum przejeżdża w nich każdą funkcję ``all`` raz.

Runner i drive Centrum biorą funkcję z rejestru ``FEATURES`` (``drive/__init__.py``): jej potrzeby przed nią, jej
zrzuty i dowody, wariant fixture'a i pomiar na wyłączność, a ``Run.capture`` odmawia zrzutu spoza jej listy. Tryb
„wolny runner” runnera dostają serwer i drive przez środowisko kroków, a serwer w nim bierze zapytania API później."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from jednostka import ZMIENNA_CZESCI
import kroki_skilli
import skrypt_skilla

ROOT = Path(__file__).resolve().parents[1]

CENTRUM = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(CENTRUM / "scripts"))
    spec = importlib.util.spec_from_file_location("run_centrum_verification", CENTRUM / "scripts" / "run_centrum_verification.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("count", range(1, 8))
def test_n_czesci_bierze_kazda_jednostke_raz_w_jej_kolejnosci_i_zadna_czesc_nie_jest_pusta(count: int) -> None:
    units = tuple(f"j{number}" for number in range(7))

    parts = [skrypt_skilla.part(units, {ZMIENNA_CZESCI: f"{number}/{count}"}) for number in range(1, count + 1)]

    assert sum(parts, ()) == units
    assert all(parts)


@pytest.mark.parametrize("value", ["8/8", "0/3", "3/2", "1", "a/b"])
def test_czesc_spoza_jednostek_to_blad_a_nie_pusty_przebieg(value: str) -> None:
    with pytest.raises(ValueError, match="MUTACJE_CZESC to K/N z 1 <= K <= N <= 7"):
        skrypt_skilla.part(tuple(range(7)), {ZMIENNA_CZESCI: value})


def test_czesci_podstawy_centrum_przejezdzaja_kazda_funkcje_all_raz_w_kolejnosci_all(runner: ModuleType) -> None:
    count = kroki_skilli.ci_parts(CENTRUM / "SKILL.md")
    every = runner.driven("all", {})

    assert count > 1 and count <= len(every)
    for parts in range(1, count + 1):
        driven = [runner.driven("all", {ZMIENNA_CZESCI: f"{number}/{parts}"}) for number in range(1, parts + 1)]
        assert sum(driven, ()) == every, parts
    assert set(every) == {feature.name for feature in runner.FEATURES if not feature.measurement}
    # Część nie zmienia przebiegu jednej funkcji (mutacje skilla), bo dzieli tylko all.
    assert runner.driven("zgloszenie", {ZMIENNA_CZESCI: "2/8"}) == ("zgloszenie",)


def test_zla_czesc_centrum_konczy_przebieg_porazka_zanim_cokolwiek_wystartuje(runner: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    driven_by_all = len([feature for feature in runner.FEATURES if not feature.measurement])
    monkeypatch.setenv(ZMIENNA_CZESCI, f"{driven_by_all + 1}/{driven_by_all + 1}")

    code = runner.main(["--feature", "all", "--run-dir", "nie-powstanie"])

    assert code == 1
    assert capsys.readouterr().err.startswith(
        f"VERIFY FAIL | features=all | MUTACJE_CZESC to K/N z 1 <= K <= N <= {driven_by_all}"
    )
    assert not Path("nie-powstanie").exists()


@dataclass
class _Steps:
    """Co runner bez procesów zrobił: funkcje każdego drive'u, argumenty fixture'a i jak trzymał maszynę."""

    driven: list[list[str]] = field(default_factory=list)
    fixtures: list[list[str]] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)


def _without_processes(runner: ModuleType, monkeypatch: pytest.MonkeyPatch, missing: str = "") -> _Steps:
    """Kroki runnera bez procesów: drive zostawia zrzuty i dowody funkcji, które dostał (``all`` to każda), poza
    ``missing`` (ścieżką w dowodach)."""

    steps = _Steps()

    def step(name: str, arguments: list[str], evidence: Path, timeout: int = 0) -> None:
        (evidence / f"{name}.txt").write_text("OK\n", encoding="utf-8")
        if name == "fixture":
            steps.fixtures.append(arguments)
        if name == "drive":
            features = arguments[arguments.index("--feature") + 1 :]
            steps.driven.append(features)
            for feature in runner.driven("all", {}) if features == ["all"] else features:
                paths = [f"screenshots/{shot}.png" for shot in runner.feature(feature).screenshots]
                for path in [*paths, *runner.feature(feature).evidence]:
                    if path != missing:
                        (evidence / path).parent.mkdir(parents=True, exist_ok=True)
                        (evidence / path).write_bytes(b"")

    def launch(root: Path, evidence: Path) -> tuple[None, str]:
        (evidence / "server.txt").write_text("OK\n", encoding="utf-8")
        return None, "http://127.0.0.1:1"

    def hold(kind: str) -> AbstractContextManager[float]:
        steps.holds.append(kind)
        return nullcontext(0.0)

    monkeypatch.setattr(runner, "_preflight", lambda: None)
    monkeypatch.setattr(runner, "_launch", launch)
    monkeypatch.setattr(runner, "_run_step", step)
    monkeypatch.setattr(
        runner,
        "QuietMachine",
        lambda: SimpleNamespace(run=lambda: hold("run"), measurement=lambda: hold("measurement")),
    )
    return steps


def test_czesc_all_przekazuje_drive_tylko_funkcje_swojej_czesci(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    steps = _without_processes(runner, monkeypatch)
    monkeypatch.setenv(ZMIENNA_CZESCI, "2/8")
    part = list(runner.driven("all"))

    code = runner.main(["--feature", "all", "--run-dir", str(tmp_path)])

    assert (code, steps.driven) == (0, [part])
    assert 1 < len(part) < len(runner.driven("all", {}))
    assert capsys.readouterr().out.splitlines()[-1].startswith(f"VERIFY OK | features={','.join(part)} | ")


def test_przejazd_bez_zrzutu_z_rejestru_funkcji_pada(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shot = runner.feature("uzupelnienie").screenshots[-1]
    _without_processes(runner, monkeypatch, missing=f"screenshots/{shot}.png")

    code = runner.main(["--feature", "uzupelnienie", "--run-dir", str(tmp_path)])

    assert code == 1
    assert capsys.readouterr().err.startswith(f"VERIFY FAIL | features=uzupelnienie | evidence is missing: {shot}.png")


def test_przejazd_bez_dowodu_z_rejestru_funkcji_pada(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = runner.feature("wydajnosc").evidence[-1]
    _without_processes(runner, monkeypatch, missing=path)

    code = runner.main(["--feature", "wydajnosc", "--run-dir", str(tmp_path)])

    assert code == 1
    assert capsys.readouterr().err.startswith(f"VERIFY FAIL | features=wydajnosc | evidence is missing: {path}")


def test_pomiar_trzyma_maszyne_na_wylacznosc_na_fixture_swojego_wariantu_a_inna_funkcja_czeka_tylko_na_pomiar(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    steps = _without_processes(runner, monkeypatch)

    codes = [runner.main(["--feature", name, "--run-dir", str(tmp_path)]) for name in ("wydajnosc", "metryki")]

    assert codes == [0, 0]
    assert steps.holds == ["measurement", "run"]
    assert [arguments[arguments.index("--root") + 2 :] for arguments in steps.fixtures] == [["--wariant", "rok-pracy"], []]


@pytest.mark.parametrize(("flags", "slow"), [(["--wolny-runner"], True), ([], False)])
def test_wolny_runner_dostaja_serwer_i_drive_a_bez_flagi_zaden_krok(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flags: list[str], slow: bool
) -> None:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.delenv(runner.SLOW_RUNNER, raising=False)
    environments: dict[str, bool] = {}
    _without_processes(runner, monkeypatch)
    fake_step, fake_launch = runner._run_step, runner._launch

    def step(name: str, arguments: list[str], evidence: Path, timeout: int = 0) -> None:
        environments[name] = runner.SLOW_RUNNER in skrypt_skilla.child_environment()
        fake_step(name, arguments, evidence, timeout)

    def launch(root: Path, evidence: Path) -> tuple[None, str]:
        environments["server"] = runner.SLOW_RUNNER in skrypt_skilla.child_environment()
        launched: tuple[None, str] = fake_launch(root, evidence)
        return launched

    monkeypatch.setattr(runner, "_launch", launch)
    monkeypatch.setattr(runner, "_run_step", step)

    code = runner.main(["--feature", "reguly-ilosci", "--run-dir", str(tmp_path), *flags])

    assert code == 0
    assert environments == dict.fromkeys(("fixture", "server", "doctor", "drive", "cleanup", "self-test"), slow)


def _serve_centrum(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(CENTRUM / "scripts"))
    spec = importlib.util.spec_from_file_location("serve_centrum", CENTRUM / "scripts" / "serve_centrum.py")
    assert spec is not None and spec.loader is not None
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    return serve


def test_serwer_wolnego_runnera_bierze_zapytanie_api_pozniej_a_strone_od_razu(monkeypatch: pytest.MonkeyPatch) -> None:
    serve = _serve_centrum(monkeypatch)
    # Opóźnienie dłuższe niż każda odpowiedź samej strony, więc obie strony nierówności nie zależą od obciążenia.
    monkeypatch.setattr(serve, "API_DELAY_S", 1.0)
    taken: dict[str, float] = {}

    async def centrum(scope: dict[str, Any], receive: object, send: object) -> None:
        taken[scope["path"]] = time.monotonic() - started

    async def requests() -> None:
        for path in ("/api/settings", "/index.html"):
            await serve._LateApi(centrum)({"type": "http", "path": path}, None, None)

    started = time.monotonic()
    asyncio.run(requests())

    assert taken["/api/settings"] >= 1.0
    assert taken["/index.html"] - taken["/api/settings"] < 1.0


@pytest.mark.parametrize("slow", [True, False], ids=["wolny-runner", "bez-trybu"])
def test_serwer_centrum_w_trybie_wolnego_runnera_bierze_api_pozniej_a_bez_trybu_od_razu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, slow: bool
) -> None:
    """Przegląd #1682, D3: serwer przebiegu z ``SLOW_RUNNER`` (flaga ``--wolny-runner``) bierze każde zapytanie API przez
    ``_LateApi``, a bez flagi bez niego. Serwer powstaje z prawdziwego fixture'a przebiegu, tylko bez nasłuchu."""

    serve = _serve_centrum(monkeypatch)
    root = tmp_path / "root"
    subprocess.run(
        [sys.executable, str(CENTRUM / "scripts" / "create_centrum_fixture.py"), "--root", str(root)],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    if slow:
        monkeypatch.setenv(serve.SLOW_RUNNER, "1")
    else:
        monkeypatch.delenv(serve.SLOW_RUNNER, raising=False)
    served: list[Any] = []

    def serve_without_listening(app: Any, **_: object) -> int:
        served.append(app)
        return 0

    monkeypatch.setattr(serve, "serve", serve_without_listening)

    assert serve.main(["--root", str(root), "--port", "0"]) == 0
    [app] = served
    assert [layer.cls for layer in app.user_middleware if layer.cls is serve._LateApi] == ([serve._LateApi] if slow else [])


def test_rejestr_funkcji_centrum_ma_kazdy_numer_zrzutu_w_jednej_funkcji_i_potrzeby_przed_funkcja(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    every = runner.FEATURES
    metryki = runner.feature("metryki")
    shared = metryki._replace(name="metryki-druga", screenshots=("20-metryki-druga",))
    early = runner.feature("kontrola-ilosci")

    assert runner.broken_rules(every) == []
    assert runner.broken_rules((*every, shared)) == [
        "screenshot numbers of more than one feature: {'20': ['metryki', 'metryki-druga']}"
    ]
    assert runner.broken_rules((early, *(each for each in every if each != early))) == [
        "a feature needs one that does not stand before it in FEATURES: ['kontrola-ilosci needs przebieg-rozliczen']"
    ]
    monkeypatch.setattr(runner, "FEATURES", (*every, shared))
    with pytest.raises(runner.VerificationFailure, match="screenshot numbers of more than one feature"):
        runner._preflight()


class _Playwright(ModuleType):
    """``playwright.sync_api`` bez przeglądarki: zadanie pytest na Windows nie ma Playwright, a drive go importuje."""

    Error = type("Error", (Exception,), {})
    TimeoutError = type("TimeoutError", (Exception,), {})
    Expect = type("Expect", (), {"set_options": lambda self, timeout: None})

    def __getattr__(self, name: str) -> Any:
        return type(name, (), {"__init__": lambda self, *args, **kwargs: None})

    @staticmethod
    @contextmanager
    def sync_playwright() -> Iterator[Any]:
        page = SimpleNamespace(set_default_timeout=lambda timeout: None)
        context = SimpleNamespace(new_page=lambda: page, add_init_script=lambda script: None, on=lambda event, handler: None)
        browser = SimpleNamespace(new_context=lambda **options: context, close=lambda: None)
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


def test_spozniona_odpowiedz_trasy_bez_podanej_odpowiedzi_puszcza_zadanie_dalej_takze_na_atrapie_playwright(
    drive_centrum: ModuleType,
) -> None:
    """Napęd wczytuje się na atrapie Playwrighta, której ``Route`` nie ma metod prawdziwej trasy: wartość domyślna
    ``answer_late`` z klasy ``Route`` wywracała import ``drive/waiting.py`` (PR #1719, CI). Bez podanej odpowiedzi trasa
    idzie dalej do Centrum."""

    puszczone: list[str] = []
    trasa = SimpleNamespace(continue_=lambda: puszczone.append("dalej"))

    sys.modules["drive.waiting"].answer_late(trasa, 0)

    assert puszczone == ["dalej"]


def test_drive_przejezdza_podane_funkcje_w_podanej_kolejnosci_po_potrzebach_ktorych_jeszcze_nie_przejechal(
    drive_centrum: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    driven: list[str] = []
    for feature, module in drive_centrum.MODULES.items():
        monkeypatch.setattr(module, "drive", lambda run, page, feature=feature, **options: driven.append(feature))
    (tmp_path / "fixture.json").write_text(json.dumps({}), encoding="utf-8")
    features = ["uwaga-taty", "logi-uruchomienia", "powiadomienia"]

    code = drive_centrum.main(["--root", str(tmp_path), "--url", "http://127.0.0.1:1", "--evidence", str(tmp_path / "dowody"), "--feature", *features])

    # logi-uruchomienia zastaje stan przebiegu-rozliczen, a ten przygotowania; powiadomienia zastają zgłoszenie i uwagę,
    # którą ten przejazd już przejechał.
    assert (code, driven) == (
        0,
        [
            "uwaga-taty",
            "przygotowanie-pliku-zbiorczego",
            "przebieg-rozliczen",
            "logi-uruchomienia",
            "zgloszenie",
            "powiadomienia",
        ],
    )
    assert capsys.readouterr().out.splitlines()[-1] == f"DRIVE OK | features={','.join(features)}"



def test_drive_daje_opcje_pomiaru_tylko_funkcji_pomiaru(
    drive_centrum: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: dict[str, dict[str, Any]] = {}
    for feature, module in drive_centrum.MODULES.items():
        monkeypatch.setattr(module, "drive", lambda run, page, feature=feature, **options: received.update({feature: options}))
    (tmp_path / "fixture.json").write_text(json.dumps({}), encoding="utf-8")

    code = drive_centrum.main(
        ["--root", str(tmp_path), "--url", "http://127.0.0.1:1", "--evidence", str(tmp_path / "dowody"),
         "--feature", "metryki", "wydajnosc", "--baseline", str(tmp_path / "baseline.json"), "--powtorzenia", "3"]
    )

    assert code == 0
    assert received == {
        "metryki": {},
        "wydajnosc": {"baseline_path": (tmp_path / "baseline.json").resolve(), "repeats": 3},
    }


@pytest.mark.parametrize(("zegar", "porazka"), [("padl", "czekanie"), ("zyje", "czekanie"), ("padl", "sprawdzenie")])
def test_czekanie_po_budzecie_przy_martwym_budziku_zegara_konczy_przebieg_porazka_zegara(
    drive_centrum: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    zegar: str,
    porazka: str,
) -> None:
    """Czekanie, które minęło budżet, gdy wątek budzika zegara Centrum już padł, czekało na budzik, który nie zadzwoni:
    ``DRIVE FAIL`` nazywa martwy zegar dla każdego ``until`` funkcji napędu, a przy żywym zegarze samo czekanie (#1539).
    Porażka inna niż czekanie zostaje sobą także przy martwym zegarze."""

    waiting = sys.modules["drive.waiting"]
    harness = sys.modules["harness"]

    def waits_past_its_budget(run: object, page: object) -> None:
        if porazka == "sprawdzenie":
            raise sys.modules["drive.common"].DriveFailure("the screen shows the queue")
        raise waiting.TimedOut("timed out: a wake-up of the clock")

    monkeypatch.setitem(drive_centrum.MODULES, "ustawienia", SimpleNamespace(drive=waits_past_its_budget))
    page = SimpleNamespace(set_default_timeout=lambda timeout: None, screenshot=lambda **options: b"")
    context = SimpleNamespace(new_page=lambda: page, add_init_script=lambda script: None, on=lambda event, handler: None)

    @contextmanager
    def playwright_fake() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda: SimpleNamespace(new_context=lambda **_: context, close=lambda: None)))

    monkeypatch.setattr(drive_centrum, "sync_playwright", playwright_fake)
    (tmp_path / "fixture.json").write_text(json.dumps({}), encoding="utf-8")
    if zegar == "padl":
        died = harness.File.CLOCK_DIED.file(tmp_path)
        died.parent.mkdir(parents=True)
        died.write_text("ValueError: could not convert", encoding="utf-8")

    code = drive_centrum.main(["--root", str(tmp_path), "--url", "http://127.0.0.1:1", "--evidence", str(tmp_path / "dowody"), "--feature", "ustawienia"])

    failure = capsys.readouterr().err
    assert code == 1
    assert failure == (
        "DRIVE FAIL | the wake-up thread of Centrum's clock died, so no wake-up fires any more:\nValueError: could not convert\n"
        if (zegar, porazka) == ("padl", "czekanie")
        else "DRIVE FAIL | the screen shows the queue\n"
        if porazka == "sprawdzenie"
        else "DRIVE FAIL | timed out: a wake-up of the clock\n"
    ), failure


class _Page:
    """Strona, której ``Run.capture`` robi zrzut: zapisuje tylko ścieżki zrzutów."""

    def __init__(self) -> None:
        self.shots: list[Path] = []

    def wait_for_function(self, expression: str) -> None:
        pass

    def screenshot(self, *, path: Path, full_page: bool, clip: object) -> None:
        self.shots.append(path)

    def locator(self, selector: str) -> SimpleNamespace:
        return SimpleNamespace(aria_snapshot=lambda: "- main")


def test_zrzut_spoza_rejestru_funkcji_konczy_jej_przejazd_a_jej_wlasny_zrzut_powstaje(
    drive_centrum: ModuleType, tmp_path: Path
) -> None:
    common = sys.modules["drive.common"]
    (tmp_path / "fixture.json").write_text(json.dumps({}), encoding="utf-8")
    run = common.Run(tmp_path, "http://127.0.0.1:1", tmp_path / "dowody")
    page = _Page()
    own = drive_centrum.feature("metryki").screenshots[0]
    foreign = drive_centrum.feature("tablica-okresow").screenshots[0]
    run.step("metryki", "metryki-karty-okresow")

    with pytest.raises(common.DriveFailure, match=f"screenshot {foreign} is not among the screenshots of metryki"):
        run.capture(page, foreign)
    run.capture(page, own)

    assert page.shots == [tmp_path / "dowody" / "screenshots" / f"{own}.png"]
