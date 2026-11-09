"""Drive Centrum rozliczeń w ``verify-centrum-rozliczen``: limit zawieszenia i droga każdego zrzutu.

Drive uznaje się za zawieszony dopiero po limicie, który rośnie z liczbą przejeżdżanych funkcji, więc nowa funkcja nie
wypycha ``--feature all`` poza stały limit kroku.

Każdy zrzut drive'u idzie przez ``Run.capture``, które przyjmuje tylko zrzut z ``screenshots`` jego funkcji w
``FEATURES``, gdzie jeden numer zrzutu należy do jednej funkcji (pliki funkcji i PR-y cytują zrzut po numerze); zrzut
prosto przez ``screenshot`` tę regułę omijał (#783: zbliżenia 170b i 181b). Test czyta kod drive'u, nie uruchamia go, więc łapie też zrzut z rzadko jeżdżącej ścieżki; nie łapie zrzutu
wywołanego bez atrybutu ``screenshot`` (``getattr``).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

from playwright.sync_api import Error as PlaywrightError
import pytest

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


def test_nieudany_zrzut_po_bledzie_drive_nie_zastepuje_przyczyny_bledu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Po błędzie funkcji drive robi zrzut ``zz-failure.png``; gdy przeglądarka już padła, zrzut też pada, a ``DRIVE FAIL``
    dalej podaje błąd funkcji, z dopiskiem, że zrzutu nie ma."""

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
        raise drive_centrum.DriveFailure("funkcja nie zobaczyła przycisku")

    monkeypatch.setattr(drive_centrum, "sync_playwright", playwright)
    monkeypatch.setitem(drive_centrum.MODULES, "ustawienia", SimpleNamespace(drive=failing))
    (tmp_path / "fixture.json").write_text("{}", encoding="utf-8")
    arguments = ["--root", str(tmp_path), "--url", "http://127.0.0.1:9", "--evidence", str(tmp_path / "dowody")]

    code = drive_centrum.main([*arguments, "--feature", "ustawienia"])

    [line] = capsys.readouterr().err.splitlines()
    assert code == 1
    assert line.startswith("DRIVE FAIL | funkcja nie zobaczyła przycisku | zz-failure.png not taken: "), line
