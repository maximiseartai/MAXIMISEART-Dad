"""Drive Centrum rozliczeń w ``verify-centrum-rozliczen``: limit zawieszenia i droga każdego zrzutu.

Drive uznaje się za zawieszony dopiero po limicie, który rośnie z liczbą przejeżdżanych funkcji, więc nowa funkcja nie
wypycha ``--feature all`` poza stały limit kroku.

Każdy zrzut drive'u idzie przez ``Run.capture``, które przyjmuje tylko zrzut z ``screenshots`` jego funkcji w
``FEATURES``, gdzie jeden numer zrzutu należy do jednej funkcji (pliki funkcji i PR-y cytują zrzut po numerze); zrzut
prosto przez ``screenshot`` tę regułę omijał (#783: zbliżenia 170b i 181b). Test czyta kod drive'u, nie uruchamia go, więc łapie też zrzut z rzadko jeżdżącej ścieżki; nie łapie zrzutu
wywołanego bez atrybutu ``screenshot`` (``getattr``).

Czekanie drive'u (``until`` z ``drive/waiting.py``, także przez ``Run.wait_for``) przeczekuje plik, który serwer albo
jego wątek jeszcze pisze: brak pliku, pusty, w połowie zapisany i chwilowo bez prawa odczytu to stan „jeszcze nie”, a
każdy inny błąd i plik, który po budżecie wciąż nie jest gotowy, kończą przebieg komunikatem (#1651, #1539). Stany
pliku zmienia sam odczyt warunku, nie zegar.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import importlib
import importlib.util
import json
from pathlib import Path
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Any

import playwright.sync_api
from playwright.sync_api import Error as PlaywrightError
import pytest
import yaml

from atrapy.pliki_taty import UPDATE_RESULT_FILE
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.tool_files import config_dir

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts"
DRIVE = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "drive"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("run_centrum_verification", SCRIPTS / "run_centrum_verification.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drive_wszystkich_funkcji_ma_limit_rosnacy_z_liczba_funkcji_a_jedna_funkcja_staly(runner: ModuleType) -> None:
    every = runner.driven("all", {})

    # all trwał w CI 280–305 s, a padał na stałych 300 s (runy 40309201075, 40322305317): limit daje mu co najmniej
    # dwa razy tyle i rośnie z każdą funkcją.
    assert runner.drive_timeout_s(every) == runner.DRIVE_SECONDS_PER_FEATURE * len(every) >= 2 * 305
    assert runner.drive_timeout_s((every[0],)) == runner.STEP_TIMEOUT_SECONDS
    assert runner.drive_timeout_s(("wydajnosc",)) == runner.PERFORMANCE_TIMEOUT_SECONDS


def _screenshots_outside_capture(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed: set[int] = set()
    if path.name == "common.py":
        run = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Run")
        capture = next(node for node in run.body if isinstance(node, ast.FunctionDef) and node.name == "capture")
        allowed = {id(node) for node in ast.walk(capture)}
    return [
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "screenshot"
        and id(node) not in allowed
    ]


def test_zrzut_w_drive_centrum_idzie_tylko_przez_run_capture() -> None:
    modules = sorted(DRIVE.glob("*.py"))
    assert DRIVE / "common.py" in modules

    found = [place for module in modules for place in _screenshots_outside_capture(module)]

    assert found == [], (
        "zrzut prosto przez screenshot omija regułę numerów zrzutów; użyj run.capture(page, name, clip=…) "
        f"z drive/common.py: {found}"
    )


@pytest.mark.parametrize("failure", ["DriveFailure", "TimedOut"])
def test_nieudany_zrzut_po_bledzie_drive_nie_zastepuje_przyczyny_bledu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    """Po błędzie funkcji drive robi zrzut ``zz-failure.png``; gdy przeglądarka już padła, zrzut też pada, a ``DRIVE FAIL``
    dalej podaje błąd funkcji, z dopiskiem, że zrzutu nie ma. Czekanie ``until`` po budżecie (``TimedOut``) to też linia
    ``DRIVE FAIL``, a nie traceback (przegląd #1703, D1)."""

    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("drive_centrum", SCRIPTS / "drive_centrum.py")
    assert spec is not None and spec.loader is not None
    drive_centrum = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drive_centrum)

    class ClosedPage:
        def set_default_timeout(self, timeout: float) -> None:
            pass

        def screenshot(self, **options: object) -> bytes:
            raise PlaywrightError("Target page, context or browser has been closed")

    class Browser:
        def new_context(self, **options: object) -> SimpleNamespace:
            return SimpleNamespace(new_page=ClosedPage)

        def close(self) -> None:
            pass

    @contextmanager
    def playwright() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(chromium=SimpleNamespace(launch=Browser))

    def failing(run: object, page: object) -> None:
        raise getattr(drive_centrum, failure)("funkcja nie zobaczyła przycisku")

    monkeypatch.setattr(drive_centrum, "sync_playwright", playwright)
    monkeypatch.setitem(drive_centrum.MODULES, "ustawienia", SimpleNamespace(drive=failing))
    (tmp_path / "fixture.json").write_text("{}", encoding="utf-8")
    arguments = ["--root", str(tmp_path), "--url", "http://127.0.0.1:9", "--evidence", str(tmp_path / "dowody")]

    code = drive_centrum.main([*arguments, "--feature", "ustawienia"])

    [line] = capsys.readouterr().err.splitlines()
    assert code == 1
    assert line.startswith("DRIVE FAIL | funkcja nie zobaczyła przycisku | zz-failure.png not taken: "), line


@pytest.fixture
def common(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return importlib.import_module("drive.common")


def _run(common: ModuleType, tmp_path: Path) -> Any:
    """Przebieg drive'u z katalogiem ``config/`` obok pliku Ustawień, jak w przygotowanym folderze okresów."""

    root = tmp_path / "run"
    config_dir(root).mkdir(parents=True)
    settings = config_dir(root) / SETTINGS_FILE
    (root / "fixture.json").write_text(json.dumps({"settings": str(settings)}), encoding="utf-8")
    return common.Run(root, "http://127.0.0.1:1/", tmp_path / "dowody")


def test_czekanie_drive_przeczekuje_wynik_aktualizacji_brakujacy_pusty_w_polowie_zapisany_i_bez_prawa_odczytu(
    common: ModuleType, tmp_path: Path
) -> None:
    """Warunek z ``aktualizacja-ok-przy-starej-wersji`` (``exists()`` i ``read_json`` wyniku Aktualizacji narzędzia,
    run 43496125209) czyta plik, który opiekun ponownego startu pisze: każdy odczyt warunku przestawia plik w następny
    stan, a czekanie kończy się dopiero na pełnym wyniku."""

    run = _run(common, tmp_path)
    result = run.config / UPDATE_RESULT_FILE
    full = json.dumps({"wynik": "NOWA_WERSJA_NIE_WYSTARTOWALA"})
    holding: list[threading.Thread] = []

    def refused_for_a_moment() -> None:
        refusing = threading.Event()

        def hold() -> None:
            with common.unreadable(result):
                refusing.set()
                time.sleep(0.3)

        holding.append(threading.Thread(target=hold))
        holding[0].start()
        refusing.wait()

    def written_whole() -> None:
        holding[0].join()
        result.write_text(full, encoding="utf-8")

    states = [
        lambda: None,
        lambda: result.write_text("", encoding="utf-8"),
        lambda: result.write_text(full[:12], encoding="utf-8"),
        refused_for_a_moment,
        written_whole,
    ]
    read: list[int] = []

    def guardian_wrote_the_failure() -> bool:
        states[len(read)]()
        read.append(len(read))
        return bool(result.exists() and common.read_json(result)["wynik"] == "NOWA_WERSJA_NIE_WYSTARTOWALA")

    run.wait_for(guardian_wrote_the_failure, "the guardian moved the clone back and wrote the failure", timeout_s=20)

    assert read == [0, 1, 2, 3, 4]


def _refused(path: Path) -> object:
    """Windows na chwilę odmawia odczytu pliku, który serwer właśnie podmienia (#1087)."""

    raise PermissionError(13, "Permission denied", str(path))


@pytest.mark.parametrize(
    "not_yet",
    [
        lambda path: path.read_text(encoding="utf-8"),
        lambda path: json.loads(""),
        lambda path: json.loads('{"wynik": "NOWA_'),
        lambda path: b"\xc5".decode("utf-8"),
        lambda path: yaml.safe_load("folder_okresow: [C:/okresy,"),
        _refused,
    ],
    ids=["brak-pliku", "pusty-json", "pol-json", "pol-znaku-utf8", "pol-yaml", "bez-prawa-odczytu"],
)
def test_czekanie_drive_czyta_jeszcze_raz_po_kazdym_stanie_jeszcze_nie(
    common: ModuleType, tmp_path: Path, not_yet: Callable[[Path], object]
) -> None:
    waiting = importlib.import_module("drive.waiting")
    reads: list[str] = []

    def ready() -> str:
        reads.append("odczyt")
        if len(reads) == 1:
            not_yet(tmp_path / "brak.json")
        return "gotowe"

    assert waiting.until(ready, "the file is written") == "gotowe"
    assert len(reads) == 2


def test_plik_trwale_w_polowie_zapisany_konczy_czekanie_po_budzecie_komunikatem_z_jego_stanem(
    common: ModuleType, tmp_path: Path
) -> None:
    run = _run(common, tmp_path)
    result = run.config / UPDATE_RESULT_FILE
    result.write_text('{"wynik": "NOWA_', encoding="utf-8")

    with pytest.raises(common.DriveFailure) as failure:
        run.wait_for(lambda: common.read_json(result)["wynik"] == "ok", "the update wrote its result", timeout_s=0.3)

    assert str(failure.value).startswith(
        "timed out: the update wrote its result; the last read was not ready: JSONDecodeError: Unterminated string"
    ), failure.value


def test_blad_spoza_stanow_jeszcze_nie_konczy_czekanie_od_razu(common: ModuleType, tmp_path: Path) -> None:
    """Pełny plik bez oczekiwanego klucza to błąd drive'u albo Centrum, a nie plik w trakcie zapisu."""

    run = _run(common, tmp_path)
    result = run.config / UPDATE_RESULT_FILE
    result.write_text(json.dumps({"stan": "ok"}), encoding="utf-8")
    reads: list[int] = []

    def updated() -> bool:
        reads.append(1)
        return bool(common.read_json(result)["wynik"] == "ok")

    with pytest.raises(KeyError, match="wynik"):
        run.wait_for(updated, "the update wrote its result")

    assert reads == [1]


class _Zegar:
    """Zegar czekania drive'u w teście: sen przesuwa go od razu, więc budżet 60 s mija bez minuty czekania."""

    def __init__(self) -> None:
        self.teraz = 0.0

    def monotonic(self) -> float:
        return self.teraz

    def sleep(self, seconds: float) -> None:
        self.teraz += seconds


def test_czekanie_drive_konczy_sie_po_budzecie_podanym_przez_wywolanie_a_nie_po_domyslnym(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Każdy nazwany budżet i liczba sekund z ``Run.wait_for`` to limit tego czekania: stan, który nie nadchodzi, kończy
    czekanie zaraz po nim, a nie po domyślnym ``Budget.SCREEN`` (przegląd #1663). Limit Playwrighta z tego budżetu
    (``Budget.ms``) to ten sam czas, więc asercja i czekanie z jednym budżetem trwają tyle samo (przegląd #1666)."""

    waiting = importlib.import_module("drive.waiting")
    zegar = _Zegar()
    monkeypatch.setattr(waiting, "time", zegar)
    run = _run(common, tmp_path)
    limits: dict[str, tuple[float, float]] = {}

    for budget in waiting.Budget:
        start = zegar.teraz
        with pytest.raises(waiting.TimedOut, match="timed out: the state comes"):
            waiting.until(lambda: None, "the state comes", budget)
        limits[budget.name] = (budget.ms / 1000, zegar.teraz - start)
    start = zegar.teraz
    with pytest.raises(common.DriveFailure, match="timed out: the state comes"):
        run.wait_for(lambda: False, "the state comes", timeout_s=0.3)
    limits["0.3 s"] = (0.3, zegar.teraz - start)

    outside = [name for name, (limit, waited) in limits.items() if not limit < waited <= limit + 2 * waiting.POLL_S]
    assert outside == [], limits


def test_expect_drive_bez_timeout_czeka_budzet_asercji(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asercja ``expect`` napędu bez ``timeout=`` czeka ``Budget.ASSERTION`` (przegląd #1666). Plik ``drive/waiting.py``
    biegnie tu jako osobny moduł, żeby nie podmienić ``Budget``, który trzymają inne moduły napędu."""

    defaults: list[dict[str, object]] = []

    class Expect(playwright.sync_api.Expect):
        def set_options(self, timeout: float | None = None) -> None:
            defaults.append({"timeout": timeout})
            super().set_options(timeout=timeout)

    monkeypatch.setattr(playwright.sync_api, "Expect", Expect)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("waiting_w_tescie", DRIVE / "waiting.py")
    assert spec is not None and spec.loader is not None
    waiting = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(waiting)

    assert isinstance(waiting.expect, Expect)
    assert defaults == [{"timeout": waiting.Budget.ASSERTION.ms}]


class _Karta:
    """Karta w teście: żądanie kliknięcia wychodzi z niej dopiero przy ``po_ilu``-tym czekaniu Playwrighta, jak zapis karty
    w trybie wolnego runnera, a klient synchroniczny dostarcza zdarzenie tylko w swoim wywołaniu (#1682)."""

    def __init__(self, po_ilu: int | None) -> None:
        self.sent: list[SimpleNamespace] = []
        self.czekania = 0
        self.po_ilu = po_ilu

    def wait_for_timeout(self, ms: float) -> None:
        self.czekania += 1
        if self.czekania == self.po_ilu:
            self.sent.append(SimpleNamespace(response=lambda: None))


def test_czekanie_na_zadanie_karty_czeka_w_playwright_wiec_zdarzenie_dochodzi(
    common: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiting = importlib.import_module("drive.waiting")
    monkeypatch.setattr(waiting, "time", _Zegar())
    karta = _Karta(po_ilu=5)

    assert waiting.until(lambda: len(karta.sent) >= 1, "the click sends its request", 1.0, page=karta) is True
    assert karta.czekania == 5


def test_powtorzone_klikniecie_liczy_zadanie_ktore_wyszlo_z_karty_pozno(common: ModuleType) -> None:
    """``settle`` liczy żądania dopiero, gdy kliknięcie wysłało swoje: stały sen liczył za wcześnie (lista #1539, miejsce 4),
    a kliknięcie, które ma nic nie wysłać (``at_least=0``), nie czeka na żądanie."""

    pozna = _Karta(po_ilu=8)
    bez_zadania = _Karta(po_ilu=None)

    assert common.settle(pozna, pozna.sent) == 1
    assert common.settle(bez_zadania, bez_zadania.sent, at_least=0) == 0


class _KartaZZegarem:
    """Karta w teście z zegarem, który przesuwa tylko jej czekanie: żądanie wychodzi z niej, gdy zegar minie
    ``wychodzi_ms`` od kliknięcia, jak zapis karty w trybie wolnego runnera (``LATE_WRITE_MS``)."""

    def __init__(self, wychodzi_ms: float) -> None:
        self.sent: list[SimpleNamespace] = []
        self.teraz_ms = 0.0
        self.wychodzi_ms = wychodzi_ms

    def wait_for_timeout(self, ms: float) -> None:
        self.teraz_ms += ms
        if not self.sent and self.teraz_ms >= self.wychodzi_ms:
            self.sent.append(SimpleNamespace(response=lambda: None))


@pytest.mark.parametrize("slow", [True, False], ids=["wolny-runner", "bez-trybu"])
def test_cisza_po_kliknieciu_ktore_ma_nic_nie_wyslac_obejmuje_spozniony_zapis_karty(
    common: ModuleType, monkeypatch: pytest.MonkeyPatch, slow: bool
) -> None:
    """Kliknięcie, które ma nic nie wysłać, a jednak wysyła, w trybie wolnego runnera wysyła swój zapis ``LATE_WRITE_MS``
    później: ``settle`` liczy go, bo cisza ``quiet_for`` trwa w trybie tyle dłużej (lista #1539, PR 5). Bez trybu
    zapis wychodzi od razu, a cisza zostaje krótka."""

    waiting = importlib.import_module("drive.waiting")
    if slow:
        monkeypatch.setenv(common.SLOW_RUNNER, "1")
    else:
        monkeypatch.delenv(common.SLOW_RUNNER, raising=False)
    late_ms = waiting.LATE_WRITE_MS if slow else 0
    # Drugie kliknięcie taty przychodzi w kilka milisekund po pierwszym, a zapis wychodzi z karty z opóźnieniem trybu.
    karta = _KartaZZegarem(late_ms + 50)

    assert common.settle(karta, karta.sent, at_least=0) == 1
    assert karta.teraz_ms <= 2 * (waiting.REPEAT_SETTLE_MS + late_ms)


@pytest.mark.parametrize("slow", [True, False], ids=["wolny-runner", "bez-trybu"])
def test_okno_taty_w_trybie_wolnego_runnera_wysyla_zapisy_pozno_i_zwalnia_animacje_a_bez_trybu_nie(
    common: ModuleType, monkeypatch: pytest.MonkeyPatch, slow: bool
) -> None:
    """Przegląd #1682, D3: flaga ``--wolny-runner`` (``SLOW_RUNNER``) wpina w każde okno taty opóźnione zapisy karty i
    wolne animacje każdej jego strony, a bez flagi okno jest zwykłe."""

    if slow:
        monkeypatch.setenv(common.SLOW_RUNNER, "1")
    else:
        monkeypatch.delenv(common.SLOW_RUNNER, raising=False)
    scripts: list[str] = []
    cdp: list[tuple[str, object]] = []
    pages: list[Callable[[object], None]] = []
    context = SimpleNamespace(
        add_init_script=scripts.append,
        on=lambda event, handler: pages.append(handler) if event == "page" else None,
        new_cdp_session=lambda page: SimpleNamespace(send=lambda method, params: cdp.append((method, params))),
    )

    common.dad_context(SimpleNamespace(new_context=lambda **_: context))
    for opened in pages:
        opened(object())

    slowed = (
        [common.LATE_WRITES % common.LATE_WRITE_MS],
        [("Animation.setPlaybackRate", {"playbackRate": common.SLOW_ANIMATIONS})],
    )
    assert (scripts, cdp) == (slowed if slow else ([], []))
