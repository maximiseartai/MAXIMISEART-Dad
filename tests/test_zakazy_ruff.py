"""Zakaz ruff z ``pyproject.toml`` obowiązuje też w katalogu, który ma własną konfigurację ruff z zakazami, a każdy
zakaz tylko tego katalogu ma próbkę, którą ruff tam odrzuca.

Ruff bierze tabelę ``banned-api`` (``TID251``) z najbliższego pliku konfiguracji w całości, zamiast dokładać ją do tabeli
pliku, który ten rozszerza (``extend``), więc katalog z własnymi zakazami powtarza każdy zakaz z ``pyproject.toml``.
Bez tego zakaz z ``pyproject.toml``, np. ``os.name``, w takim katalogu po cichu przestaje obowiązywać. Plikiem
konfiguracji ruff jest ``ruff.toml``, ``.ruff.toml`` i ``pyproject.toml`` z tabelą ``[tool.ruff]``.

Próbka biegnie przez ``ruff check --stdin-filename <katalog zakazu>/sonda_zakazu.py -``, więc ruff bierze konfigurację
tego katalogu, a usunięcie albo literówka w linii zakazu wywraca jego próbkę.

Z ``TID251`` konfiguracja ruff zwalnia tylko pliki z prawem właściciela (``OWNERS``), a kod każdego z nich zgłasza poza
zwolnieniem dokładnie nazwy, których jest właścicielem.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pkgutil
import subprocess
import sys
import tomllib
from typing import Any

import pytest

from tests.fixtures.znane_luki import assert_znane_luki, ruff, ruff_i_mypy, wymaga_ruff, wymaga_ruff_i_mypy, zapisz

ROOT = Path(__file__).resolve().parents[1]
# Każdy plik konfiguracji ruff poza pyproject.toml w korzeniu, literałem, żeby tools/szybko.py wybierał ten test przy
# zmianie któregoś z nich.
SRC_CONFIG = ROOT / "src" / "ruff.toml"
TESTS_CONFIG = ROOT / "tests" / "ruff.toml"
DRIVE_CONFIG = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "drive" / "ruff.toml"
DIRECTORY_CONFIGS = (SRC_CONFIG, TESTS_CONFIG, DRIVE_CONFIG)
# Sonda kodu narzędzi, który bierze konfigurację ruff z pyproject.toml w korzeniu.
TOOLS_PROBE = ("tools", "lib")
# Katalogi, które ruff sprawdza (``include`` w ``pyproject.toml``), i nazwy plików konfiguracji ruff.
CHECKED = ("src", "tests", "tools", ".agents/skills")
NAMES = ("ruff.toml", ".ruff.toml", "pyproject.toml")
STAR = "F403"

# Próbka → katalog (plik konfiguracji, podkatalog, w którym stoi sonda) i jedyny zakaz, który ruff w niej zgłasza
# (``F403`` dla ``import *``). Pierwsze postaci usunięć napędu to dawne ``REMOVAL_SAMPLES`` z ``centrum_self_test.py``,
# a ``sys.path`` dawne ``TOOLS_ON_PATH`` z ``test_struktura_testow.py``. Postaci wątków to formy zapadki wątków z
# ``tests/test_zapadki.py`` (0e304aec7, #633), które ruff widzi w kodzie.
SAMPLES: dict[str, tuple[Path, tuple[str, ...], str]] = {
    "import os\nos.remove(p)": (DRIVE_CONFIG, (), "os.remove"),
    "import os\nos.replace(p, q)": (DRIVE_CONFIG, (), "os.replace"),
    "import shutil\nshutil.move(p, q)": (DRIVE_CONFIG, (), "shutil.move"),
    "import os as system\nsystem.remove(p)": (DRIVE_CONFIG, (), "os.remove"),
    "import shutil as files\nfiles.move(p, q)": (DRIVE_CONFIG, (), "shutil.move"),
    "import os.path\nos.remove(p)": (DRIVE_CONFIG, (), "os.remove"),
    "import functools\nimport os\nfunctools.partial(os.replace, p, q)": (DRIVE_CONFIG, (), "os.replace"),
    "import os as fs\nimport shutil as fs\nfs.move(p, q)": (DRIVE_CONFIG, (), "shutil.move"),
    "import os\nos.unlink(p)": (DRIVE_CONFIG, (), "os.unlink"),
    "import os\nos.rmdir(p)": (DRIVE_CONFIG, (), "os.rmdir"),
    "import os\nos.removedirs(p)": (DRIVE_CONFIG, (), "os.removedirs"),
    "import os\nos.rename(p, q)": (DRIVE_CONFIG, (), "os.rename"),
    "import os\nos.renames(p, q)": (DRIVE_CONFIG, (), "os.renames"),
    "from os import remove": (DRIVE_CONFIG, (), "os.remove"),
    "from os import replace as swap": (DRIVE_CONFIG, (), "os.replace"),
    "from os import getcwd, unlink": (DRIVE_CONFIG, (), "os.unlink"),
    "from shutil import move as shift": (DRIVE_CONFIG, (), "shutil.move"),
    "from shutil import rmtree": (DRIVE_CONFIG, (), "shutil.rmtree"),
    "from os import *": (DRIVE_CONFIG, (), STAR),
    "from shutil import *": (DRIVE_CONFIG, (), STAR),
    "from pathlib import *": (DRIVE_CONFIG, (), STAR),
    "from pathlib import Path\nPath.replace(p, q)": (DRIVE_CONFIG, (), "pathlib.Path.replace"),
    "from pathlib import Path\nPath.move(p, q)": (DRIVE_CONFIG, (), "pathlib.Path.move"),
    "from pathlib import Path as P\nP.replace(p, q)": (DRIVE_CONFIG, (), "pathlib.Path.replace"),
    "import pathlib\npathlib.Path.move(p, q)": (DRIVE_CONFIG, (), "pathlib.Path.move"),
    "import pathlib\npathlib.PosixPath.move(p, q)": (DRIVE_CONFIG, (), "pathlib.PosixPath.move"),
    "from pathlib import PosixPath\nPosixPath.replace(p, q)": (DRIVE_CONFIG, (), "pathlib.PosixPath.replace"),
    "from pathlib import WindowsPath\nWindowsPath.move(p, q)": (DRIVE_CONFIG, (), "pathlib.WindowsPath.move"),
    "import pathlib as pl\npl.WindowsPath.replace(p, q)": (DRIVE_CONFIG, (), "pathlib.WindowsPath.replace"),
    "from pathlib import Path\nswap = Path.replace": (DRIVE_CONFIG, (), "pathlib.Path.replace"),
    # Stały sen w napędzie zamiast czekania z drive/waiting.py (#1539).
    "import time\ntime.sleep(0.3)": (DRIVE_CONFIG, (), "time.sleep"),
    "from time import sleep as pause": (DRIVE_CONFIG, (), "time.sleep"),
    'import sys\nsys.path.insert(0, str(ROOT / "tools"))': (TESTS_CONFIG, (), "sys.path"),
    'import sys\nsys.path.append(str(Path(__file__).resolve().parents[1] / "tools/ci"))': (TESTS_CONFIG, (), "sys.path"),
    'import sys\nsys.path.append("C:\\\\repo\\\\tools")': (TESTS_CONFIG, (), "sys.path"),
    'import sys\nTOOLS: Final = ROOT / "tools"\nsys.path.insert(0, str(TOOLS / "lib"))': (
        TESTS_CONFIG,
        ("fixtures",),
        "sys.path",
    ),
    'import sys\ndef f() -> None:\n    sys.path.insert(0, str(ROOT / "tools"))': (TESTS_CONFIG, (), "sys.path"),
    "import sys\nsys.path[:0] = [x]": (TESTS_CONFIG, (), "sys.path"),
    "import sys as s\ns.path.append(x)": (TESTS_CONFIG, (), "sys.path"),
    "from sys import path as p": (TESTS_CONFIG, (), "sys.path"),
    # Import w trakcie działania obok tools/lib/import_dynamiczny.py: postacie z przeglądu #1680 (r1–r3, W1).
    'import importlib\nm = importlib.import_module(name="tests.fixtures.znane_luki")': (ROOT / "pyproject.toml", TOOLS_PROBE, "importlib.import_module"),
    'import importlib\nm = importlib.import_module(".znane_luki", "tests.fixtures")': (ROOT / "pyproject.toml", TOOLS_PROBE, "importlib.import_module"),
    'from importlib import import_module\nm = import_module(".znane_luki", package="tests.fixtures")': (
        ROOT / "pyproject.toml",
        TOOLS_PROBE,
        "importlib.import_module",
    ),
    'import importlib as il\nm = il.import_module("tests.fixtures.znane_luki")': (ROOT / "pyproject.toml", (), "importlib.import_module"),
    'import builtins\nm = builtins.__import__("tests.fixtures.znane_luki")': (ROOT / "pyproject.toml", TOOLS_PROBE, "builtins.__import__"),
    "from importlib.util import spec_from_file_location": (ROOT / "pyproject.toml", (".agents", "skills", "verify-rozliczenia", "scripts"), "importlib.util"),
    'import runpy\nrunpy.run_module("tests.fixtures.znane_luki")': (DRIVE_CONFIG, (), "runpy"),
    'import runpy\nrunpy.run_path("tests/fixtures/znane_luki.py")': (ROOT / "pyproject.toml", TOOLS_PROBE, "runpy"),
    'import importlib\nm = importlib.import_module("tests.fixtures.znane_luki")': (SRC_CONFIG, ("rozliczenia",), "importlib.import_module"),
    # Ładowacz z importlib.abc (przegląd #1705 r1, W1), postacie jego importu i importlib.metadata.
    "from importlib.abc import SourceLoader\nclass Ladowacz(SourceLoader): ...": (ROOT / "pyproject.toml", TOOLS_PROBE, "importlib.abc"),
    "from importlib.abc import SourceLoader": (SRC_CONFIG, ("rozliczenia",), "importlib.abc"),
    "from importlib import abc": (DRIVE_CONFIG, (), "importlib.abc"),
    "import importlib.abc as ladowacze": (ROOT / "pyproject.toml", TOOLS_PROBE, "importlib.abc"),
    'from importlib.metadata import EntryPoint\nEntryPoint("x", "tests.fixtures.znane_luki:zapisz", "g").load()': (
        ROOT / "pyproject.toml",
        TOOLS_PROBE,
        "importlib.metadata",
    ),
    # Dawne znane luki, które zakaz zamknął: ZNANE_LUKI_SKRYPTU i ZNANE_LUKI_GRAFU (tests/test_granice_importow.py) oraz
    # „tool przez importlib” z ZNANE_LUKI w tests/test_regula_danych.py, każda w katalogu swojej sondy.
    'import importlib\n\nSERWER = importlib.import_module("fastapi")\n': (ROOT / "pyproject.toml", ("tools",), "importlib.import_module"),
    'import importlib\n\nSKOROSZYT = importlib.import_module("openpyxl")\n': (SRC_CONFIG, ("rozliczenia",), "importlib.import_module"),
    'import importlib\n\nWZORZEC = importlib.import_module("rozliczenia." + "template_file")\n': (
        SRC_CONFIG,
        ("rozliczenia",),
        "importlib.import_module",
    ),
    'import importlib\n\ntekst = importlib.import_module("rozliczenia.client_data").tool(komorka)\n': (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "importlib.import_module",
    ),
    "import threading\nstart = threading.Thread.start": (TESTS_CONFIG, (), "threading.Thread.start"),
    "from threading import Thread as Worker\nWorker.start = counted": (TESTS_CONFIG, ("fixtures",), "threading.Thread.start"),
    "import threading\nassert threading.active_count() == before": (TESTS_CONFIG, (), "threading.active_count"),
    "from threading import active_count as count": (TESTS_CONFIG, (), "threading.active_count"),
    "from .workbook_files import file_bytes": (SRC_CONFIG, ("rozliczenia",), "rozliczenia.workbook_files.file_bytes"),
    "from ..workbook_files import open_workbook as opened": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.workbook_files.open_workbook",
    ),
    # Tekst do wysyłki z komórki taty bez strażnika pracy Centrum (przegląd #1648, D1).
    "from rozliczenia.client_data import tool\ntext = tool(cell)": (SRC_CONFIG, ("rozliczenia", "centrum"), "rozliczenia.client_data.tool"),
    # Plik w Archiwum Logów okresu z komórki taty bez strażnika Logów (przegląd #1688, runda 3).
    "from rozliczenia import client_data\ntext = client_data.logs_text(cell)": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.client_data.logs_text",
    ),
    "from rozliczenia import client_data\nwynik = client_data.guarded(client_data.empty_memory(), cell, 'komórka')": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.client_data.empty_memory",
    ),
    # Zmieniona kopia dataclassy z polami Any, obok dataclasses.replace (przegląd #1660, W1).
    "import copy\nsent = copy.replace(post, run_id=run)": (SRC_CONFIG, ("rozliczenia", "centrum"), "copy.replace"),
    "from copy import replace as copied": (SRC_CONFIG, ("rozliczenia",), "copy.replace"),
    "from . import workbook_files\nworkbook_files.template_content(p)": (
        SRC_CONFIG,
        ("rozliczenia",),
        "rozliczenia.workbook_files.template_content",
    ),
    # Zegar ścienny w src/ tylko przez rozliczenia/wall_clock.py; pierwsza próbka to dzień UTC zamiast dnia taty.
    "from datetime import datetime, timezone\nday = datetime.now(timezone.utc).date()": (SRC_CONFIG, ("rozliczenia",), "datetime.datetime.now"),
    "import datetime as dt\nmoment = dt.datetime.now(dt.UTC)": (SRC_CONFIG, ("rozliczenia",), "datetime.datetime.now"),
    "from datetime import datetime\nmoment = datetime.today()": (SRC_CONFIG, ("rozliczenia",), "datetime.datetime.today"),
    "from datetime import datetime\nmoment = datetime.utcnow()": (SRC_CONFIG, ("rozliczenia",), "datetime.datetime.utcnow"),
    "from datetime import date\ntoday: Callable[[], date] = date.today": (SRC_CONFIG, ("rozliczenia",), "datetime.date.today"),
    "import time\nlease = time.time() + 30": (SRC_CONFIG, ("rozliczenia",), "time.time"),
    "from time import time_ns": (SRC_CONFIG, ("rozliczenia",), "time.time_ns"),
    "import time\nparts = time.localtime()": (SRC_CONFIG, ("rozliczenia",), "time.localtime"),
    "import time\nparts = time.gmtime()": (SRC_CONFIG, ("rozliczenia",), "time.gmtime"),
    "import time\ntext = time.ctime()": (SRC_CONFIG, ("rozliczenia",), "time.ctime"),
    "import time\ntext = time.asctime()": (SRC_CONFIG, ("rozliczenia",), "time.asctime"),
    "import time\nname = time.strftime('%Y%m%d')": (SRC_CONFIG, ("rozliczenia",), "time.strftime"),
    "import email.utils\nmoment = email.utils.localtime()": (SRC_CONFIG, ("rozliczenia",), "email.utils.localtime"),
    "from email.utils import formatdate\nheader = formatdate(localtime=True)": (SRC_CONFIG, ("rozliczenia",), "email.utils.formatdate"),
    # Otwieracz z nowym kontekstem TLS: sprawdzenie health launchera przed #1675 (przegląd D1).
    "import urllib.request\ndirect = urllib.request.build_opener(urllib.request.ProxyHandler({}))": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "urllib.request.build_opener",
    ),
    "from urllib.request import urlopen\nhealth = urlopen(url, timeout=1)": (SRC_CONFIG, ("rozliczenia",), "urllib.request.urlopen"),
    # Mypy wyłączony na funkcji bez komentarza tłumienia, którego licznik tłumień nie widzi (przegląd #1689, W1).
    "import typing\n@typing.no_type_check\ndef f() -> int:\n    return '1'": (SRC_CONFIG, ("rozliczenia",), "typing.no_type_check"),
    "from typing_extensions import no_type_check as unchecked": (TESTS_CONFIG, (), "typing_extensions.no_type_check"),
}


def _banned(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("flake8-tidy-imports", {}).get("banned-api", {}))


def _ruff_table(path: Path) -> dict[str, Any] | None:
    """Tabela ustawień ruff pliku: cały ``ruff.toml``, a z ``pyproject.toml`` tylko ``[tool.ruff]``, bez niej ``None``."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("ruff") if path.name == "pyproject.toml" else data


def _configs(root: Path) -> set[Path]:
    """Każdy plik konfiguracji ruff w katalogach, które ruff sprawdza, i w korzeniu poza ``pyproject.toml`` korzenia."""
    candidates = {path for top in CHECKED for name in NAMES for path in (root / top).rglob(name)}
    candidates |= {root / name for name in NAMES if name != "pyproject.toml" and (root / name).exists()}
    return {path for path in candidates if _ruff_table(path) is not None}


def test_szukanie_konfiguracji_widzi_pyproject_z_tabela_ruff_w_podkatalogu(tmp_path: Path) -> None:
    (tmp_path / "tools" / "z_ruff").mkdir(parents=True)
    (tmp_path / "tools" / "z_ruff" / "pyproject.toml").write_text("[tool.ruff]\nextend = '../../pyproject.toml'\n")
    (tmp_path / "tools" / "bez_ruff").mkdir()
    (tmp_path / "tools" / "bez_ruff" / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / ".ruff.toml").write_text("extend = '../pyproject.toml'\n")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")

    assert _configs(tmp_path) == {tmp_path / "tools" / "z_ruff" / "pyproject.toml", tmp_path / "src" / ".ruff.toml"}


def test_katalog_z_wlasnymi_zakazami_ruff_powtarza_kazdy_zakaz_z_pyproject() -> None:
    assert _configs(ROOT) == set(DIRECTORY_CONFIGS), "dopisz nowy plik konfiguracji ruff do DIRECTORY_CONFIGS w tests/test_zakazy_ruff.py"

    root = _banned(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"])
    problems = []
    for path in DIRECTORY_CONFIGS:
        config = _ruff_table(path) or {}
        where = path.relative_to(ROOT).as_posix()
        if (path.parent / config.get("extend", "")).resolve() != ROOT / "pyproject.toml":
            problems.append(f"{where}: extend nie wskazuje pyproject.toml repozytorium")
        local = _banned(config.get("lint", {}))
        problems += [
            f"{where}: brak zakazu {name} z pyproject.toml"
            for name, entry in root.items()
            if local.get(name) != entry and not (path == TESTS_CONFIG and name in DYNAMIC_IMPORT)
        ]

    assert problems == [], "\n".join(
        [*problems, "ruff bierze banned-api z najbliższego pliku konfiguracji w całości: skopiuj tam wpis z pyproject.toml"]
    )


def test_kazdy_zakaz_tylko_katalogu_ma_probke() -> None:
    """Zakaz tylko katalogu to wpis, którego nie ma w ``pyproject.toml``; kopii tabeli ``pyproject.toml`` pilnuje test
    zgodności wyżej."""
    root = _banned(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"])
    local = {path: _banned((_ruff_table(path) or {}).get("lint", {})) for path in DIRECTORY_CONFIGS}
    shared = root.keys()
    sampled = {(config, banned) for config, _, banned in SAMPLES.values()}
    missing = [
        f"{path.relative_to(ROOT).as_posix()}: {name}"
        for path, banned in local.items()
        for name in banned
        if name not in shared and (path, name) not in sampled
    ]

    assert missing == [], "dopisz do SAMPLES w tests/test_zakazy_ruff.py próbkę zakazu:\n" + "\n".join(missing)


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
@pytest.mark.parametrize("code", list(SAMPLES))
def test_ruff_odrzuca_probke_zakazu_w_jego_katalogu(code: str) -> None:
    config, subdirectory, banned = SAMPLES[code]
    probe = config.parent.joinpath(*subdirectory, "sonda_zakazu.py")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--select", f"TID251,{STAR}", "--output-format", "json"]
        + ["--stdin-filename", str(probe), "-"],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    assert result.stderr == "", result.stderr

    found = [
        STAR if finding["code"] == STAR else finding["message"].split("`")[1]
        for finding in json.loads(result.stdout)
    ]

    assert found == [banned], f"{config.relative_to(ROOT).as_posix()} ma odrzucić zakazem {banned}:\n{code}"


# Sen w napędzie obok drive/waiting.py, którego zakaz time.sleep w drive/ruff.toml nie widzi (#1539, PR 6).
ZNANE_LUKI_SNU = {
    "metoda na obiekcie: page.wait_for_timeout (13 wywołań w drive/wydajnosc.py)": (
        "from playwright.sync_api import Page\n\n\ndef measured(page: Page) -> None:\n    page.wait_for_timeout(300)\n"
    ),
    "nazwa w napisie: getattr": 'import time\n\ngetattr(time, "sleep")(0.3)\n',
    "inne API z limitem czasu: threading.Event.wait": "import threading\n\nthreading.Event().wait(0.3)\n",
}


@wymaga_ruff
def test_znane_luki_zakazu_snu_w_napedzie_przechodza_przez_ruff(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_SNU, tmp_path)

    zgloszenia = ruff(pliki, sonda=DRIVE_CONFIG.parent / "sonda_luki.py")

    assert_znane_luki(zgloszenia, "tests/test_zakazy_ruff.py (ZNANE_LUKI_SNU)")


# Prawo właściciela: plik, który konfiguracja ruff zwalnia z TID251 (per-file-ignores w pyproject.toml) → zakazane nazwy,
# których jest właścicielem. Ruff zwalnia plik z całego TID251, a nie z jednej nazwy, więc ta tabela trzyma resztę
# zakazów: kod właściciela zgłasza dokładnie swoje nazwy, gdy stoi poza zwolnieniem.
OWNERS: dict[str, frozenset[str]] = {
    "src/rozliczenia/wall_clock.py": frozenset({"datetime.datetime.now", "time.time"}),
    "src/rozliczenia/centrum/catalog.py": frozenset({"rozliczenia.centrum.process_kind._CATALOG"}),
    "src/rozliczenia/dad_files.py": frozenset({"rozliczenia.workbook_files.file_bytes"}),
    "src/rozliczenia/centrum/app.py": frozenset({"rozliczenia.client_data.empty_memory"}),
    "src/rozliczenia/centrum/case_delivery.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/comment_versions.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/dad_notes.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/outbox.py": frozenset({"rozliczenia.client_data.logs_text", "rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/quantity_check_run.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/reports.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/run_logs_guard.py": frozenset({"rozliczenia.client_data.logs_text"}),
    "src/rozliczenia/register_file.py": frozenset({"rozliczenia.workbook_files.open_workbook"}),
    "src/rozliczenia/template_file.py": frozenset(
        {"rozliczenia.workbook_files.open_workbook", "rozliczenia.workbook_files.template_content"}
    ),
    "src/rozliczenia/centrum/opener.py": frozenset({"urllib.request.build_opener"}),
    "tools/lib/import_dynamiczny.py": frozenset({"importlib.import_module", "importlib.machinery", "importlib.util"}),
    "tests/conftest.py": frozenset({"sys.path"}),
    "tests/fixtures/linie_watkow.py": frozenset({"threading.Thread.start"}),
    ".agents/skills/verify-centrum-rozliczen/scripts/drive/common.py": frozenset({"os.replace", "shutil.rmtree"}),
    ".agents/skills/verify-centrum-rozliczen/scripts/drive/waiting.py": frozenset({"time.sleep"}),
}
# Zakaz z pyproject.toml, który obowiązuje w każdym katalogu (test zgodności wyżej), więc jego brak w zgłoszeniu znaczy
# zwolnienie pliku z TID251.
SHARED_PROBE = "import os\nsystem = os.name\n"


def _banned_names(*arguments: str, code: str | None = None, cwd: Path = ROOT) -> list[tuple[str, str]]:
    """``(plik, nazwa)`` każdego ``TID251`` i każdego ``import *`` (``F403``, nazwa ``F403``), które ``ruff check`` z
    ``--ignore-noqa`` zgłasza w ``cwd``. Reguły wybiera konfiguracja jak w CI: ``--select`` z wiersza poleceń zastąpiłby
    jej ``ignore``, a to też zwolnienie z ``TID251``."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--ignore-noqa", "--output-format", "json", *arguments],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        check=False,
    )
    assert result.stderr == "", result.stderr
    return [
        (
            Path(finding["filename"]).resolve().relative_to(cwd.resolve()).as_posix(),
            STAR if finding["code"] == STAR else finding["message"].split("`")[1],
        )
        for finding in json.loads(result.stdout)
        if finding["code"] in ("TID251", STAR)
    ]


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_konfiguracja_ruff_zwalnia_z_tid251_tylko_wlascicieli(tmp_path: Path) -> None:
    """Zwolnienie z ``TID251`` daje każdy mechanizm konfiguracji (``per-file-ignores``, ``ignore``, wzorzec ze ``**``),
    więc test pyta ruff, a nie czyta konfiguracji: kopia drzewa z próbką ``os.name`` w miejscu każdego pliku, który ruff
    sprawdza, i z każdym plikiem konfiguracji ruff repozytorium. Plik bez zgłoszenia jest zwolniony, a zwolniony może
    być tylko właściciel z ``OWNERS``."""
    for config in (ROOT / "pyproject.toml", *_configs(ROOT)):
        copy = tmp_path / config.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    shown = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--show-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    checked = {Path(line).resolve().relative_to(ROOT.resolve()).as_posix() for line in shown.splitlines() if line.strip()}
    for name in checked:
        probe = tmp_path / name
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text(SHARED_PROBE, encoding="utf-8")

    reported = {name for name, banned in _banned_names(cwd=tmp_path) if banned == "os.name"}

    assert sorted(checked - reported) == sorted(OWNERS), (
        "z TID251 konfiguracja ruff zwalnia tylko pliki z OWNERS w tests/test_zakazy_ruff.py: prawo właściciela to "
        "jego ścieżka w per-file-ignores pyproject.toml i wiersz OWNERS z nazwami, a wyjątek tymczasowy stoi na linii"
    )


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
@pytest.mark.parametrize("owner", list(OWNERS))
def test_wlasciciel_uzywa_tylko_swoich_zakazanych_nazw(owner: str) -> None:
    """Kod właściciela biegnie przez ruff jako sonda obok niego, poza jego zwolnieniem i z ``--ignore-noqa``: zgłasza
    dokładnie nazwy z ``OWNERS``. Inna zakazana nazwa (np. zegar w ``dad_files.py``) albo ``import *`` to droga obok
    właściciela tej nazwy, a nazwa, której właściciel już nie używa, to prawo do usunięcia."""
    path = ROOT / owner
    probe = path.with_name("sonda_zakazu.py")

    found = {banned for _, banned in _banned_names("--stdin-filename", str(probe), "-", code=path.read_text(encoding="utf-8"))}

    assert sorted(found) == sorted(OWNERS[owner]), (
        f"{owner} używa zakazanych nazw {sorted(found)}, a jego prawo w OWNERS to {sorted(OWNERS[owner])}: inną nazwę "
        "bierz przez jej właściciela, a nazwę, której plik już nie używa, usuń z OWNERS"
    )


# Właściciel importu w trakcie działania poza tests/: jedyny plik z prawem do jego dróg (OWNERS).
DYNAMIC_IMPORT_OWNER = ROOT / "tools" / "lib" / "import_dynamiczny.py"
# Zakazy importu w trakcie działania w pyproject.toml (i jego kopiach poza tests/ruff.toml), które testy niżej
# uruchamiają z --ignore-noqa: lista nazw, nie dopasowanie komunikatu, żeby nowy zakaz o innym brzmieniu nie wypadł z niej.
# Nazwy pakietu importlib wynikają z biblioteki działającego Pythona (test nazw niżej); reszta to moduły, których zadaniem
# jest import albo wykonanie modułu. Inne moduły biblioteki standardowej, które przy okazji wykonują plik albo importują po
# nazwie, są znaną luką z próbkami w ZNANE_LUKI_IMPORTU, nie pełną listą.
DYNAMIC_IMPORT = (
    "importlib.import_module",
    "importlib.__import__",
    "importlib.util",
    "importlib.machinery",
    "importlib._bootstrap",
    "importlib._bootstrap_external",
    "importlib._abc",
    "importlib.abc",
    "importlib.metadata",
    "importlib.readers",
    "importlib.simple",
    "importlib.reload",
    "importlib.invalidate_caches",
    "importlib.sys",
    "importlib._imp",
    "importlib._RELOADING",
    "importlib._pack_uint32",
    "importlib._unpack_uint32",
    "builtins.__import__",
    "_frozen_importlib",
    "_frozen_importlib_external",
    "_imp",
    "runpy",
    "pkgutil",
    "zipimport",
)
# Nazwy pakietu importlib, które kod poza tests/ bierze wprost, z powodem; reszta pakietu jest w DYNAMIC_IMPORT.
IMPORTLIB_DOZWOLONE = {
    "importlib.resources": (
        "zasób pakietu taty czyta src/rozliczenia/quantity_rules_file.py; files() importuje pakiet po nazwie, więc ta "
        "droga stoi próbką „dozwolona nazwa importlib” w ZNANE_LUKI_IMPORTU"
    ),
}
DYNAMIC_IMPORT_PROBE = 'import importlib\nm = importlib.import_module("tests.fixtures.znane_luki")  # noqa: TID251 - sonda\n'


def _dynamic_imports(*arguments: str, code: str | None = None) -> list[str]:
    """``plik`` każdego zakazu z ``DYNAMIC_IMPORT``, który ``ruff check`` z ``--ignore-noqa`` zgłasza poza ``tests/``."""
    return sorted(
        {name for name, banned in _banned_names(*arguments, code=code) if banned in DYNAMIC_IMPORT and not name.startswith("tests/")}
    )


def test_kazdy_zakaz_importu_w_trakcie_dzialania_jest_na_liscie_dynamic_import() -> None:
    """Zakazem importu w trakcie działania jest wpis ``pyproject.toml``, którego komunikat odsyła do właściciela."""
    banned = _banned(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"])
    owned = {name for name, entry in banned.items() if "tools/lib/import_dynamiczny.py" in entry["msg"]}

    assert sorted(owned ^ set(DYNAMIC_IMPORT)) == [], "DYNAMIC_IMPORT w tests/test_zakazy_ruff.py ma wymieniać każdy zakaz właściciela"


def test_kazda_nazwa_pakietu_importlib_jest_zakazana_albo_dozwolona_z_powodem() -> None:
    """Granica zakazu w pakiecie ``importlib`` wynika z biblioteki standardowej działającego Pythona, nie z wyliczenia:
    każdy jego podmoduł (``pkgutil.iter_modules``, także prywatny) i każda nazwa modułu poza dunderami (i ``__import__``)
    jest w ``DYNAMIC_IMPORT`` wprost albo przez zakazany moduł nadrzędny, albo w ``IMPORTLIB_DOZWOLONE`` z powodem."""
    names = {f"importlib.{module.name}" for module in pkgutil.iter_modules(importlib.__path__)}
    names |= {f"importlib.{name}" for name in vars(importlib) if not (name.startswith("__") and name.endswith("__"))}
    names.add("importlib.__import__")
    banned = [name for name in DYNAMIC_IMPORT if name.startswith("importlib.")]

    open_names = sorted(
        name for name in names if name not in IMPORTLIB_DOZWOLONE and not any(name == ban or name.startswith(f"{ban}.") for ban in banned)
    )

    assert open_names == [], (
        f"importlib tego Pythona ma nazwy bez zakazu: {open_names}; dopisz każdą z komunikatem właściciela do banned-api "
        "w pyproject.toml, src/ruff.toml i drive/ruff.toml oraz do DYNAMIC_IMPORT, albo do IMPORTLIB_DOZWOLONE z powodem "
        "i próbką w ZNANE_LUKI_IMPORTU, gdy kod poza tests/ jej potrzebuje"
    )
    assert sorted(IMPORTLIB_DOZWOLONE.keys() - names) == [], "IMPORTLIB_DOZWOLONE wymienia nazwę, której importlib nie ma"


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_import_w_trakcie_dzialania_poza_testami_tylko_u_wlasciciela_takze_z_noqa() -> None:
    """``# noqa: TID251`` przy ``importlib.import_module`` byłoby drugą drogą obok właściciela, który odmawia modułu z
    ``tests/``, więc te zakazy biegną z ``--ignore-noqa`` na całym kodzie, który ruff sprawdza; ``tests/`` importuje w
    trakcie działania własne moduły i ma je poza zakazem."""

    assert _dynamic_imports() == [], "import w trakcie działania bierz z tools/lib/import_dynamiczny.py, bez noqa"


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_noqa_nie_zwalnia_z_zakazu_importu_w_trakcie_dzialania_a_wlasciciel_jest_zwolniony() -> None:
    probe = ROOT.joinpath(*TOOLS_PROBE, "sonda_zakazu.py")

    assert _dynamic_imports("--stdin-filename", str(probe), "-", code=DYNAMIC_IMPORT_PROBE) == ["tools/lib/sonda_zakazu.py"]
    assert _dynamic_imports("--stdin-filename", str(DYNAMIC_IMPORT_OWNER), "-", code=DYNAMIC_IMPORT_PROBE) == []


# Znane luki zakazu importu w trakcie działania (tests/fixtures/znane_luki.py): „klasa: postać” → moduł narzędzi, który
# wykonuje kod z tests/ obok tools/lib/import_dynamiczny.py, a mimo to przechodzi przez ruff i mypy.
ZNANE_LUKI_IMPORTU = {
    "wbudowana bez modułu: __import__ z nazwą w argumencie nazwanym": (
        'FIXTURES = __import__(name="tests.fixtures.znane_luki", fromlist=["zapisz"])\n'
    ),
    "nazwa z napisu: getattr na module importlib": (
        'import importlib\n\nFIXTURES = getattr(importlib, "import_module")("tests.fixtures.znane_luki")\n'
    ),
    "maszyneria z obiektu: klasa loadera z __spec__ modułu": (
        "import json\nfrom typing import Any\n\n"
        "LOADER: Any = type(json.__spec__.loader)\n"
        'FIXTURES = LOADER("znane_luki", "tests/fixtures/znane_luki.py").load_module()\n'
    ),
    "kod w napisie: exec pod inną nazwą": 'URUCHOM = exec\nURUCHOM("import tests.fixtures.znane_luki")\n',
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: multiprocessing.popen_spawn_posix": (
        "from multiprocessing import popen_spawn_posix\n\n"
        'getattr(popen_spawn_posix, "spawn").import_main_path("tests/fixtures/znane_luki.py")\n'
    ),
    "osobny proces: polecenie python -c": (
        "import subprocess\nimport sys\n\n"
        'subprocess.run([sys.executable, "-c", "import tests.fixtures.znane_luki"], check=True)\n'
    ),
    "tłumienie ruff: exec z noqa": 'exec("import tests.fixtures.znane_luki")  # noqa: S102 - próbka\n',
    "kod w napisie: code.InteractiveInterpreter": (
        'import code\n\ncode.InteractiveInterpreter().runsource("import tests.fixtures.znane_luki")\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: traceback, podpowiedź do ImportError": (
        'import traceback\n\nBLAD = ImportError("x", name="tests.fixtures.znane_luki")\nsetattr(BLAD, "name_from", "nie_ma")\n'
        "traceback.format_exception(BLAD)\n"
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: sysconfig, moduł danych ze zmiennej środowiska": (
        'import os\nimport sysconfig\n\nos.environ["_PYTHON_SYSCONFIGDATA_NAME"] = "tests.fixtures.znane_luki"\n'
        "ZMIENNE = sysconfig.get_config_vars()\n"
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: unittest.mock.patch po nazwie": (
        'from unittest import mock\n\nmock.patch("tests.fixtures.znane_luki.ROOT", None).start()\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: warnings, kategoria z opcji -W": (
        'import warnings\n\ngetattr(warnings, "_setoption")("ignore::tests.fixtures.znane_luki.Nie")\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: xml.sax.make_parser z nazwą parsera": (
        'import xml.sax\n\nPARSER = xml.sax.make_parser(["tests.fixtures.znane_luki"])\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: pickle.loads po nazwie": (
        'import pickle\n\nFIXTURES = pickle.loads(b"ctests.fixtures.znane_luki\\nzapisz\\n.")\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: logging.config.dictConfig z fabryką po nazwie": (
        "import logging.config\n\n"
        'logging.config.dictConfig({"version": 1, "handlers": {"h": {"()": "tests.fixtures.znane_luki.zapisz"}}})\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: optparse.Values.read_module": (
        'import optparse\n\noptparse.Values().read_module("tests.fixtures.znane_luki")\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: inspect, wiersz poleceń": (
        'import inspect\nimport sys\n\nsys.argv = ["inspect", "tests.fixtures.znane_luki"]\ngetattr(inspect, "_main")()\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: cProfile.main z plikiem": (
        'import cProfile\nimport sys\n\nsys.argv = ["cProfile", "tests/fixtures/znane_luki.py"]\ngetattr(cProfile, "main")()\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: multiprocessing.spawn.import_main_path": (
        'from multiprocessing import spawn\n\nspawn.import_main_path("tests/fixtures/znane_luki.py")\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: pydoc.locate": 'import pydoc\n\nFIXTURES = pydoc.locate("tests.fixtures.znane_luki")\n',
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: doctest.DocTestSuite po nazwie": 'import doctest\n\nZESTAW = doctest.DocTestSuite("tests.fixtures.znane_luki")\n',
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: unittest.TestLoader": (
        'import unittest\n\nZESTAW = unittest.TestLoader().loadTestsFromName("tests.fixtures.znane_luki")\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: trace z modułem z wiersza poleceń": (
        'import sys\nimport trace\n\nsys.argv = ["trace", "--count", "--module", "tests.fixtures"]\ngetattr(trace, "main")()\n'
    ),
    "moduł biblioteki standardowej, który przy okazji wykonuje plik albo importuje po nazwie: profile.main z plikiem": (
        'import profile\nimport sys\n\nsys.argv = ["profile", "tests/fixtures/znane_luki.py"]\ngetattr(profile, "main")()\n'
    ),
    "wbudowana bez modułu: help po nazwie": 'help("tests.fixtures.znane_luki")\n',
    "dozwolona nazwa importlib: importlib.resources pakietu": (
        'from importlib import resources\n\nFIXTURES = resources.files("tests.fixtures")\n'
    ),
}


@wymaga_ruff_i_mypy
def test_znane_luki_zakazu_importu_w_trakcie_dzialania_przechodza_przez_ruff_i_mypy(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_IMPORTU, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT.joinpath(*TOOLS_PROBE, "sonda_luki.py"))

    assert_znane_luki(zgloszenia, "tests/test_zakazy_ruff.py (ZNANE_LUKI_IMPORTU)")


# Właściciel zegara ściennego w src/: jedyny plik z prawem do nazw zegara (OWNERS).
CLOCK_OWNER = ROOT / "src" / "rozliczenia" / "wall_clock.py"
# Zakazy zegara ściennego w src/ruff.toml, które testy niżej uruchamiają z --ignore-noqa: lista nazw, nie dopasowanie
# komunikatu, żeby nowy zakaz zegara o innym brzmieniu nie wypadł z niej po cichu.
CLOCK = (
    "datetime.datetime.now",
    "datetime.datetime.today",
    "datetime.datetime.utcnow",
    "datetime.date.today",
    "time.time",
    "time.time_ns",
    "time.localtime",
    "time.gmtime",
    "time.ctime",
    "time.asctime",
    "time.strftime",
    "email.utils.localtime",
    "email.utils.formatdate",
)
CLOCK_MODULES = ("datetime.", "time.", "email.utils.")
# Druga linia to zegar z ``noqa``, trzecia to ``import *`` z ``noqa``: gwiazdka daje nazwę zegara bez pełnej nazwy
# odwołania, której szuka TID251, więc w ``src/`` liczy się jak zegar (#1423 r1).
CLOCK_PROBE = "import time\nlease = time.time()  # noqa: TID251 - termin opiekuna\nfrom datetime import *  # noqa: F403\n"


def _clock_findings(*arguments: str, code: str | None = None, cwd: Path = ROOT) -> list[str]:
    """``plik:linia`` każdego zakazu zegara z ``CLOCK`` i każdego ``import *`` (``F403``), które ``ruff check``
    z ``--ignore-noqa`` zgłasza w ``cwd``."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--ignore-noqa", "--output-format", "json", *arguments],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        check=False,
    )
    assert result.stderr == "", result.stderr
    return [
        f"{Path(finding['filename']).resolve().relative_to(cwd.resolve()).as_posix()}:{finding['location']['row']}"
        for finding in json.loads(result.stdout)
        if finding["code"] == STAR or (finding["code"] == "TID251" and finding["message"].split("`")[1] in CLOCK)
    ]


def test_kazdy_zakaz_zegara_jest_na_liscie_clock() -> None:
    """Zakazem zegara jest wpis ``src/ruff.toml`` dla modułu z ``CLOCK_MODULES`` i wpis, którego komunikat odsyła do
    ``rozliczenia.wall_clock``."""
    banned = _banned(tomllib.loads(SRC_CONFIG.read_text(encoding="utf-8"))["lint"])
    clock = {name for name, entry in banned.items() if name.startswith(CLOCK_MODULES) or "rozliczenia.wall_clock" in entry["msg"]}

    assert sorted(clock - set(CLOCK)) == [], "dopisz zakaz zegara do CLOCK w tests/test_zakazy_ruff.py"
    assert sorted(set(CLOCK) - banned.keys()) == [], "CLOCK wymienia zakaz, którego nie ma w src/ruff.toml"


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_zegar_scienny_w_src_tylko_u_wlasciciela_takze_z_noqa() -> None:
    """``# noqa: TID251`` przy ``datetime.now`` byłoby drugą drogą do zegara obok właściciela (#1371), więc zakazy zegara
    biegną tu z ``--ignore-noqa``; właściciel przechodzi tylko dzięki prawu właściciela w konfiguracji ruff, a że inny
    plik z takim prawem nie używa zegara, sprawdza ``test_wlasciciel_uzywa_tylko_swoich_zakazanych_nazw``."""

    assert _clock_findings("src") == [], "teraz i dzień taty bierz z rozliczenia.wall_clock, bez noqa i bez import *"


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_noqa_nie_zwalnia_z_zakazu_zegara_a_wlasciciel_jest_zwolniony() -> None:
    probe = SRC_CONFIG.parent / "rozliczenia" / "sonda_zakazu.py"

    assert _clock_findings("--stdin-filename", str(probe), "-", code=CLOCK_PROBE) == [
        "src/rozliczenia/sonda_zakazu.py:2",
        "src/rozliczenia/sonda_zakazu.py:3",
    ]
    assert _clock_findings("--stdin-filename", str(CLOCK_OWNER), "-", code=CLOCK_PROBE) == ["src/rozliczenia/wall_clock.py:3"]


# Znane luki zakazu zegara ściennego (tests/fixtures/znane_luki.py): „klasa: postać” → moduł src, który bierze chwilę
# „teraz” albo dzień obok ``rozliczenia.wall_clock``, a mimo to przechodzi przez ruff, mypy i ``_clock_findings``.
ZNANE_LUKI_ZEGARA = {
    "nazwa, nie typ wyrażenia: dzień UTC z chwili wall_clock": "from rozliczenia.wall_clock import utc_now\n\nDZIEN = utc_now().date()\n",
    "nazwa, nie typ wyrażenia: instancja datetime": "from datetime import datetime\n\nTERAZ = datetime.min.now()\n",
    "nazwa, nie typ wyrażenia: podklasa datetime": "from datetime import datetime\n\n\nclass Chwila(datetime):\n    pass\n\n\nTERAZ = Chwila.now()\n",
    "refleksja po nazwie: __import__": 'TERAZ = __import__("time").time()\n',
    "refleksja po nazwie: getattr modułu": 'import time\n\nTERAZ = getattr(time, "time")()\n',
    "refleksja po nazwie: getattr z nazwą złożoną": 'import time\n\nTERAZ = getattr(time, "ti" + "me")()\n',
    "tylko zegary z listy: zegar modułu, którego src/ruff.toml nie wymienia": "import logging\n\nTERAZ = logging.makeLogRecord({}).created\n",
    "tłumienie mypy: reeksport z type: ignore": "from rozliczenia.wall_clock import datetime  # type: ignore[attr-defined]  # próbka\n\nTERAZ = datetime.now()\n",
    "tłumienie mypy: reeksport time z type: ignore": "from rozliczenia.wall_clock import time  # type: ignore[attr-defined]  # próbka\n\nTERAZ = time.time()\n",
    "tłumienie mypy: reeksport przez atrybut modułu z type: ignore": (
        "from rozliczenia import wall_clock\n\nTERAZ = wall_clock.datetime.now()  # type: ignore[attr-defined]  # próbka\n"
    ),
}


@wymaga_ruff_i_mypy
def test_znane_luki_zakazu_zegara_przechodza_przez_ruff_i_mypy(tmp_path: Path) -> None:
    probe = SRC_CONFIG.parent / "rozliczenia" / "sonda_zakazu.py"
    pliki = zapisz(ZNANE_LUKI_ZEGARA, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=probe)
    for opis, plik in pliki.items():
        zgloszenia[opis] += _clock_findings("--stdin-filename", str(probe), "-", code=plik.read_text(encoding="utf-8"))

    assert_znane_luki(zgloszenia, "tests/test_zakazy_ruff.py (ZNANE_LUKI_ZEGARA)")


def _src_files() -> set[str]:
    """Pliki ``src/*.py``, które ruff ma sprawdzać: śledzone i nowe nieignorowane, które stoją na dysku."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "src/*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return {name for name in listed.split("\0") if name and (ROOT / name).is_file()}


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_ruff_sprawdza_kazdy_plik_src() -> None:
    """Plik ``src/``, którego ruff nie sprawdza, omija każdy zakaz, także zegara. Ruff wyłącza plik nie tylko ``exclude``
    i ``include`` konfiguracji, ale też wpisem w ``.ignore``, ``.gitignore`` i ``.git/info/exclude``, więc test pyta
    ruff tym samym wywołaniem co CI (``ruff check`` bez ścieżek, ``--show-files``), które pliki ``src/`` sprawdza."""
    shown = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--show-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    checked = {
        path.relative_to(ROOT.resolve()).as_posix()
        for line in shown.splitlines()
        if (path := Path(line).resolve()).is_relative_to(ROOT.resolve() / "src")
    }

    assert sorted(_src_files() - checked) == [], (
        "ruff nie sprawdza tych plików src/, więc nie obejmuje ich żaden zakaz src/ruff.toml: usuń ich wyłączenie "
        "(exclude albo include w konfiguracji ruff) i nie dopisuj pliku src/ do .ignore, .gitignore ani .git/info/exclude"
    )


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_konfiguracja_ruff_zwalnia_z_zakazu_zegara_tylko_wlasciciela(tmp_path: Path) -> None:
    """Wyjątek od reguły w konfiguracji (``per-file-ignores``, ``extend-per-file-ignores``, ``ignore`` w każdym pliku
    konfiguracji ruff) to druga droga do zegara obok ``noqa``. Kopia drzewa ``src/`` z próbką zegara w miejscu każdego
    pliku i z każdym plikiem konfiguracji ruff repozytorium idzie przez ruff tak jak ``src/``: plik bez zgłoszenia jest
    zwolniony, a zwolniony może być tylko plik z prawem właściciela (``OWNERS``), któremu nazw zegara poza
    ``wall_clock.py`` odmawia ``test_wlasciciel_uzywa_tylko_swoich_zakazanych_nazw``. Że ruff w ogóle sprawdza każdy
    plik ``src/``, pilnuje ``test_ruff_sprawdza_kazdy_plik_src`` na prawdziwym checkoucie."""
    for config in (ROOT / "pyproject.toml", *_configs(ROOT)):
        copy = tmp_path / config.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    probes = _src_files()
    for name in probes:
        probe = tmp_path / name
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text(CLOCK_PROBE, encoding="utf-8")

    expected = {f"{name}:{row}" for name in probes for row in ((3,) if name in OWNERS else (2, 3))}

    assert sorted(expected ^ set(_clock_findings("src", cwd=tmp_path))) == [], (
        "z zakazu zegara konfiguracja ruff zwalnia tylko pliki z OWNERS, a z import * nikogo: "
        "teraz i dzień taty bierz z wall_clock"
    )


# Kod ``noqa`` spoza ruff, który reguła ast-grep ``komentarz-w-src`` przepuszcza, bo ma kształt kodu ``[A-Z]+[0-9]+``:
# sam i obok prawdziwego kodu, na linii z naruszeniem i bez. Każdy katalog z konfiguracją ruff, bo ``RUF102`` stoi
# w ``extend-select`` ``pyproject.toml``, które pozostałe pliki konfiguracji rozszerzają.
INVALID_NOQA_CODES = (
    "import os  # noqa: PR1614 - historia\n",
    "x = 1  # noqa: PR1614 - historia\n",
    "import os  # noqa: F401, PR1614 - historia\n",
    "x = 1  # noqa: E501, PR1614 - historia\n",
)


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
@pytest.mark.parametrize("folder", [ROOT / "tools", *(config.parent for config in DIRECTORY_CONFIGS)])
@pytest.mark.parametrize("code", INVALID_NOQA_CODES)
def test_ruff_odrzuca_kod_noqa_spoza_ruff_w_kazdym_katalogu(folder: Path, code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json"]
        + ["--stdin-filename", str(folder / "sonda_noqa.py"), "-"],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    assert result.stderr == "", result.stderr

    assert "RUF102" in {finding["code"] for finding in json.loads(result.stdout)}, (
        f"konfiguracja ruff w {folder.relative_to(ROOT).as_posix()} ma odrzucić kod noqa spoza ruff (RUF102):\n{code}"
    )
