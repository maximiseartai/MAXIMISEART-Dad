"""Zakaz ruff z ``pyproject.toml`` obowiązuje też w katalogu, który ma własną konfigurację ruff z zakazami, a każdy
zakaz tylko tego katalogu ma próbkę, którą ruff tam odrzuca.

Ruff bierze tabelę ``banned-api`` (``TID251``) z najbliższego pliku konfiguracji w całości, zamiast dokładać ją do tabeli
pliku, który ten rozszerza (``extend``), więc katalog z własnymi zakazami powtarza każdy zakaz z ``pyproject.toml``.
Bez tego zakaz z ``pyproject.toml``, np. ``os.name``, w takim katalogu po cichu przestaje obowiązywać. Plikiem
konfiguracji ruff jest ``ruff.toml``, ``.ruff.toml`` i ``pyproject.toml`` z tabelą ``[tool.ruff]``.

Próbka biegnie przez ``ruff check --stdin-filename <katalog zakazu>/sonda_zakazu.py -``, więc ruff bierze konfigurację
tego katalogu, a usunięcie albo literówka w linii zakazu wywraca jego próbkę.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Każdy plik konfiguracji ruff poza pyproject.toml w korzeniu, literałem, żeby tools/szybko.py wybierał ten test przy
# zmianie któregoś z nich.
SRC_CONFIG = ROOT / "src" / "ruff.toml"
TESTS_CONFIG = ROOT / "tests" / "ruff.toml"
DRIVE_CONFIG = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "drive" / "ruff.toml"
DIRECTORY_CONFIGS = (SRC_CONFIG, TESTS_CONFIG, DRIVE_CONFIG)
# Katalogi, które ruff sprawdza (``include`` w ``pyproject.toml``), i nazwy plików konfiguracji ruff.
CHECKED = ("src", "tests", "tools", ".agents/skills")
NAMES = ("ruff.toml", ".ruff.toml", "pyproject.toml")
STAR = "F403"

# Próbka → katalog (plik konfiguracji, podkatalog, w którym stoi sonda) i jedyny zakaz, który ruff w niej zgłasza
# (``F403`` dla ``import *``). Pierwsze postaci usunięć napędu to dawne ``REMOVAL_SAMPLES`` z ``centrum_self_test.py``,
# a ``sys.path`` dawne ``TOOLS_ON_PATH`` z ``test_struktura_testow.py``.
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
    "from .workbook_files import file_bytes": (SRC_CONFIG, ("rozliczenia",), "rozliczenia.workbook_files.file_bytes"),
    "from ..workbook_files import open_workbook as opened": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.workbook_files.open_workbook",
    ),
    "from . import workbook_files\nworkbook_files.template_content(p)": (
        SRC_CONFIG,
        ("rozliczenia",),
        "rozliczenia.workbook_files.template_content",
    ),
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
        problems += [f"{where}: brak zakazu {name} z pyproject.toml" for name, entry in root.items() if local.get(name) != entry]

    assert problems == [], "\n".join(
        [*problems, "ruff bierze banned-api z najbliższego pliku konfiguracji w całości: skopiuj tam wpis z pyproject.toml"]
    )


def test_kazdy_zakaz_tylko_katalogu_ma_probke() -> None:
    """Zakaz tylko katalogu to wpis, którego nie ma w ``pyproject.toml`` ani w każdym pliku katalogu naraz: wpis we
    wszystkich jest kopią tabeli ``pyproject.toml`` (także taką, którą ``main`` już tam dopisał), a jej pilnuje test
    zgodności wyżej."""
    root = _banned(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"])
    local = {path: _banned((_ruff_table(path) or {}).get("lint", {})) for path in DIRECTORY_CONFIGS}
    shared = root.keys() | set.intersection(*(set(banned) for banned in local.values()))
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
