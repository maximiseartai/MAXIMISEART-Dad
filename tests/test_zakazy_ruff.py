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


# Właściciel zegara ściennego w src/: jedyny plik zwolniony z zakazów zegara.
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
CLOCK_PROBE = "import time\nlease = time.time()  # noqa: TID251 - termin opiekuna\n"


def _clock_findings(*arguments: str, code: str | None = None, cwd: Path = ROOT) -> list[str]:
    """``plik:linia`` każdego zakazu zegara z ``CLOCK``, który ``ruff check`` z ``--ignore-noqa`` zgłasza w ``cwd``."""
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
        if finding["code"] == "TID251" and finding["message"].split("`")[1] in CLOCK
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
    biegną tu z ``--ignore-noqa``; właściciel przechodzi tylko dzięki wyjątkowi w ``src/ruff.toml``."""

    assert _clock_findings("src") == [], "teraz i dzień taty bierz z rozliczenia.wall_clock, bez noqa"


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_noqa_nie_zwalnia_z_zakazu_zegara_a_wlasciciel_jest_zwolniony() -> None:
    probe = SRC_CONFIG.parent / "rozliczenia" / "sonda_zakazu.py"

    assert _clock_findings("--stdin-filename", str(probe), "-", code=CLOCK_PROBE) == ["src/rozliczenia/sonda_zakazu.py:2"]
    assert _clock_findings("--stdin-filename", str(CLOCK_OWNER), "-", code=CLOCK_PROBE) == []


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
    zwolniony, a zwolniony może być tylko właściciel. Że ruff w ogóle sprawdza każdy plik ``src/``, pilnuje
    ``test_ruff_sprawdza_kazdy_plik_src`` na prawdziwym checkoucie."""
    for config in (ROOT / "pyproject.toml", *_configs(ROOT)):
        copy = tmp_path / config.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    probes = _src_files()
    for name in probes:
        probe = tmp_path / name
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text(CLOCK_PROBE, encoding="utf-8")

    reported = {finding.rsplit(":", 1)[0] for finding in _clock_findings("src", cwd=tmp_path)}

    assert sorted(probes - reported) == [CLOCK_OWNER.relative_to(ROOT).as_posix()], (
        "z zakazu zegara konfiguracja ruff zwalnia tylko rozliczenia/wall_clock.py: teraz i dzień taty bierz z niego"
    )
