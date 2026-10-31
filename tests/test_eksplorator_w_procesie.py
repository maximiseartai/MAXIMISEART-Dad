"""Kod eksploratora przeplotów skilla wykonany w procesie pytest wywraca test, a eksplorator w osobnym procesie nie.

Przypadki biegną w osobnym pytest z pluginem strażnika (bez xdist i z ``-n 2``), każdy w swoim katalogu z własnym
udawanym eksploratorem ``explore_<przypadek>.py``, który zostawia znacznik, gdy jego kod się wykona. Formy wczytania
pochodzą z werdyktów rund 1 i 2 PR #707.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET

import pytest

from tests.fixtures.eksplorator_w_procesie import IN_PROCESS_EXPLORERS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "tests.fixtures.eksplorator_w_procesie"

RECORDS = 'from pathlib import Path\nPath(__file__).with_suffix(".wykonany").touch()\n'
# Na początku każdego pliku przypadku; ``explore_fake`` to eksplorator przypadku.
PRELUDE = """\
import importlib
import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "verify-x" / "scripts"
EXPLORER = SCRIPTS / "explore_fake.py"
sys.path.insert(0, str(SCRIPTS))


def wczytaj(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
"""
IN_PROCESS = {
    "import_na_gorze_modulu": {
        "test_x.py": """
            import explore_fake

            def test_x():
                pass
        """,
    },
    "import_w_conftest": {
        "conftest.py": "import explore_fake\n",
        "test_x.py": "def test_x():\n    pass\n",
    },
    "fixtura_exec_module": {
        "test_x.py": """
            @pytest.fixture
            def explorer():
                return wczytaj(EXPLORER)

            def test_x(explorer):
                pass
        """,
    },
    "fixtura_z_name": {
        "test_x.py": """
            @pytest.fixture(name="explorer_path")
            def _explorer_path():
                return EXPLORER

            def test_x(explorer_path):
                runpy.run_path(str(explorer_path))
        """,
    },
    "fixtura_z_conftest": {
        "conftest.py": """
            @pytest.fixture
            def explorer():
                return importlib.import_module("explore_fake")
        """,
        "test_x.py": "def test_x(explorer):\n    pass\n",
    },
    "watek_w_fixturze": {
        "test_x.py": """
            import threading

            @pytest.fixture
            def explorer():
                thread = threading.Thread(target=importlib.import_module, args=("explore_fake",))
                thread.start()
                thread.join(60)

            def test_x(explorer):
                pass
        """,
    },
    "sprzatanie_fixtury": {
        "test_x.py": """
            @pytest.fixture
            def po_tescie():
                yield
                try:
                    importlib.import_module("explore_fake")
                except Exception:
                    pass

            def test_x(po_tescie):
                pass
        """,
    },
    "pomocnik_spoza_modulu": {
        "pomocnik_testow.py": "",
        "test_x.py": """
            from pomocnik_testow import wczytaj

            def test_x():
                wczytaj(EXPLORER)
        """,
    },
    "submit_z_limitem": {
        "test_x.py": """
            from concurrent.futures import ThreadPoolExecutor

            def test_x():
                ThreadPoolExecutor(1).submit(runpy.run_path, str(EXPLORER)).result(timeout=60)
        """,
    },
    "watek_polyka_wyjatek": {
        "test_x.py": """
            import threading

            def test_x():
                thread = threading.Thread(target=runpy.run_path, args=(str(EXPLORER),))
                thread.start()
                thread.join(60)
        """,
    },
    "except_polyka_wyjatek": {
        "test_x.py": """
            def test_x():
                try:
                    import explore_fake
                except Exception:
                    pass
        """,
    },
    "partial": {
        "test_x.py": """
            from functools import partial

            def test_x():
                partial(importlib.import_module, "explore_fake")()
        """,
    },
    "alias": {
        "test_x.py": """
            def test_x():
                load = importlib.import_module
                load("explore_fake")
        """,
    },
    "map": {
        "test_x.py": """
            def test_x():
                list(map(importlib.import_module, ["explore_fake"]))
        """,
    },
    "run_module": {
        "test_x.py": """
            def test_x():
                runpy.run_module("explore_fake")
        """,
    },
    "sciezka_wzgledna": {
        "test_x.py": """
            def test_x(monkeypatch):
                monkeypatch.chdir(SCRIPTS.parent)
                runpy.run_path("scripts/explore_fake.py")
        """,
    },
    "exec_compile": {
        "test_x.py": """
            def test_x():
                exec(compile(EXPLORER.read_text(), str(EXPLORER), "exec"), {})
        """,
    },
}
# Przypadek poza procesem pytest albo z wyjątku: pliki i eksploratory, których kod się wykona.
OUTSIDE = {
    "podproces_z_limitem": ({
        "test_x.py": """
            def test_x():
                subprocess.run([sys.executable, str(EXPLORER)], timeout=60, check=True)
        """,
    }, {"explore_podproces_z_limitem"}),
    "wyjatek_explore_publication": ({
        "test_x.py": """
            def test_x():
                wczytaj(SCRIPTS / "explore_publication.py")
        """,
    }, {"explore_publication"}),
    "tekst_eksploratora": ({
        "test_x.py": """
            import ast

            def test_x():
                ast.parse(EXPLORER.read_text())
                compile(EXPLORER.read_text(), str(EXPLORER), "exec")
        """,
    }, set()),
    "explore_spoza_skilla": ({
        "explore_spoza_skilla.py": "",
        "test_x.py": """
            def test_x():
                importlib.import_module("explore_spoza_skilla")
        """,
    }, set()),
}


def _outcomes(tmp_path: Path, workers: list[str]) -> tuple[dict[str, str], set[str]]:
    """Wynik każdego przypadku w osobnym pytest: ``przeszedł`` albo komunikat porażki, oraz eksploratory, których kod się
    wykonał."""

    scripts = tmp_path / ".agents" / "skills" / "verify-x" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "explore_publication.py").write_text(RECORDS, encoding="utf-8")
    for case, files in [*IN_PROCESS.items(), *((case, files) for case, (files, _) in OUTSIDE.items())]:
        (scripts / f"explore_{case}.py").write_text(RECORDS, encoding="utf-8")
        (tmp_path / "przypadki" / case).mkdir(parents=True)
        for name, code in files.items():
            module = PRELUDE + textwrap.dedent(code)
            # Nazwa modułu testu jest jedna w całym pytest, więc każdy przypadek ma swoją.
            target = f"test_{case}.py" if name == "test_x.py" else name
            (tmp_path / "przypadki" / case / target).write_text(module.replace("explore_fake", f"explore_{case}"), encoding="utf-8")
    report = tmp_path / "junit.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-p", PLUGIN, "-p", "no:cacheprovider", "--continue-on-collection-errors"]
        + [f"--junitxml={report}", *workers, "przypadki"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        timeout=100,
        check=False,
    )
    outcomes: dict[str, str] = {}
    for testcase in ET.parse(report).iter("testcase"):
        # Błąd zbierania ma pustą klasę: przypadek jest wtedy w nazwie.
        case = (testcase.attrib["classname"] or testcase.attrib["name"]).split(".")[1]
        problems = [f"{element.get('message')}\n{element.text}" for element in testcase if element.tag in ("failure", "error")]
        outcomes[case] = problems[0] if problems else outcomes.get(case, "przeszedł")
    return outcomes, {path.stem for path in scripts.glob("*.wykonany")}


@pytest.fixture(scope="module", params=[[], ["-n", "2"]], ids=["bez-xdist", "xdist"])
def wyniki(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[dict[str, str], set[str]]]:
    yield _outcomes(tmp_path_factory.mktemp("eksplorator"), request.param)


@pytest.mark.parametrize("case", IN_PROCESS)
def test_kod_eksploratora_w_procesie_pytest_wywraca_test_zanim_eksplorator_zacznie_biec(
    wyniki: tuple[dict[str, str], set[str]], case: str
) -> None:
    outcomes, ran = wyniki

    assert "EksploratorWProcesie" in outcomes[case] and f"explore_{case}.py" in outcomes[case], outcomes[case]
    assert f"explore_{case}" not in ran


@pytest.mark.parametrize("case", OUTSIDE)
def test_eksplorator_w_osobnym_procesie_z_wyjatku_albo_czytany_jako_tekst_przechodzi(
    wyniki: tuple[dict[str, str], set[str]], case: str
) -> None:
    outcomes, ran = wyniki

    assert outcomes[case] == "przeszedł"
    assert ran & ({f"explore_{case}"} | OUTSIDE[case][1]) == OUTSIDE[case][1], sorted(ran)


def test_wyjatek_straznika_nazywa_istniejacy_eksplorator_skilla() -> None:
    explorers = {path.stem for path in (ROOT / ".agents" / "skills").glob("*/scripts/explore_*.py")}

    assert set(IN_PROCESS_EXPLORERS) <= explorers, sorted(set(IN_PROCESS_EXPLORERS) - explorers)


def test_pytest_testow_repozytorium_wczytuje_straznika(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin(PLUGIN)
