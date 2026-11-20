"""Zakaz ruff z ``ruff.toml`` korzenia obowiązuje też w katalogu, który ma własną konfigurację ruff z zakazami, a każdy
zakaz tylko tego katalogu ma próbkę, którą ruff tam odrzuca.

Ruff bierze tabelę ``banned-api`` (``TID251``) z najbliższego pliku konfiguracji w całości, zamiast dokładać ją do tabeli
pliku, który ten rozszerza (``extend``), więc katalog z własnymi zakazami powtarza każdy zakaz z ``ruff.toml``
korzenia. Bez tego zakaz korzenia, np. ``os.name``, w takim katalogu po cichu przestaje obowiązywać. Plikiem
konfiguracji ruff jest ``ruff.toml``, ``.ruff.toml`` i ``pyproject.toml`` z tabelą ``[tool.ruff]``.

Próbka biegnie przez ``ruff check --stdin-filename <katalog zakazu>/sonda_zakazu.py -``, więc ruff bierze konfigurację
tego katalogu, a usunięcie albo literówka w linii zakazu wywraca jego próbkę.

Z ``TID251`` konfiguracja ruff zwalnia tylko pliki z prawem właściciela (``OWNERS``), a kod każdego z nich zgłasza poza
zwolnieniem dokładnie nazwy, których jest właścicielem; to drugie sprawdza też krok reguł chwastów zadania CI „Ruff, mypy”.
"""

from __future__ import annotations

from collections.abc import Mapping
import importlib.util
import json
from pathlib import Path
import pkgutil
import subprocess
import sys
import tomllib
from typing import Any, Final

import pytest

from tests.fixtures.znane_luki import assert_znane_luki, platformy_mypy_ci, ruff, ruff_i_mypy, wymaga_ruff, wymaga_ruff_i_mypy, zapisz

ROOT = Path(__file__).resolve().parents[1]
# Każdy plik konfiguracji ruff, literałem, żeby tools/szybko.py i bramka PR wybierały ten test przy zmianie któregoś
# z nich. Konfiguracja korzenia stoi w ruff.toml, nie w pyproject.toml, więc jej zmiana nie uruchamia wszystkich testów.
ROOT_CONFIG = ROOT / "ruff.toml"
SRC_CONFIG = ROOT / "src" / "ruff.toml"
TESTS_CONFIG = ROOT / "tests" / "ruff.toml"
DRIVE_CONFIG = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "drive" / "ruff.toml"
DIRECTORY_CONFIGS = (SRC_CONFIG, TESTS_CONFIG, DRIVE_CONFIG)
# Sonda kodu narzędzi, który bierze konfigurację ruff z ruff.toml korzenia.
TOOLS_PROBE = ("tools", "lib")
# Katalogi, które ruff sprawdza (``include`` w ``ruff.toml`` korzenia), i nazwy plików konfiguracji ruff.
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
    "import sys\nsys.path[:0] = [x]": (TESTS_CONFIG, (), "sys.path"),
    "import sys as s\ns.path.append(x)": (TESTS_CONFIG, (), "sys.path"),
    "from sys import path as p": (TESTS_CONFIG, (), "sys.path"),
    # Import w trakcie działania obok tools/lib/import_dynamiczny.py: postacie z przeglądu #1680 (r1–r3, W1).
    'import importlib\nm = importlib.import_module(name="tests.fixtures.znane_luki")': (ROOT_CONFIG, TOOLS_PROBE, "importlib.import_module"),
    'from importlib import import_module\nm = import_module(".znane_luki", package="tests.fixtures")': (
        ROOT_CONFIG,
        TOOLS_PROBE,
        "importlib.import_module",
    ),
    'import importlib as il\nm = il.import_module("tests.fixtures.znane_luki")': (ROOT_CONFIG, (), "importlib.import_module"),
    'import builtins\nm = builtins.__import__("tests.fixtures.znane_luki")': (ROOT_CONFIG, TOOLS_PROBE, "builtins.__import__"),
    "from importlib.util import spec_from_file_location": (ROOT_CONFIG, (".agents", "skills", "verify-rozliczenia", "scripts"), "importlib.util"),
    'import runpy\nrunpy.run_path("tests/fixtures/znane_luki.py")': (ROOT_CONFIG, TOOLS_PROBE, "runpy"),
    # Ładowacz z importlib.abc (przegląd #1705 r1, W1), postacie jego importu i importlib.metadata.
    "from importlib.abc import SourceLoader\nclass Ladowacz(SourceLoader): ...": (ROOT_CONFIG, TOOLS_PROBE, "importlib.abc"),
    "from importlib import abc": (DRIVE_CONFIG, (), "importlib.abc"),
    "import importlib.abc as ladowacze": (ROOT_CONFIG, TOOLS_PROBE, "importlib.abc"),
    'from importlib.metadata import EntryPoint\nEntryPoint("x", "tests.fixtures.znane_luki:zapisz", "g").load()': (
        ROOT_CONFIG,
        TOOLS_PROBE,
        "importlib.metadata",
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
    # Wzorzec do Archiwum Logów okresu z bajtów bez sprawdzenia reguły danych: nazwa ze skrótu przechodzi from_queue.
    "from rozliczenia.centrum import template_archive\nwzorzec = template_archive.from_queue(nazwa, plik, bajty)": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.centrum.template_archive.from_queue",
    ),
    "from rozliczenia.centrum.template_archive import _CHECKED": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.centrum.template_archive._CHECKED",
    ),
    "from rozliczenia import client_data\nwynik = client_data.guarded(client_data.empty_memory(), cell, 'komórka')": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.client_data.empty_memory",
    ),
    # Zmieniona kopia dataclassy z polami Any, obok dataclasses.replace (przegląd #1660, W1).
    "import copy\nsent = copy.replace(post, run_id=run)": (SRC_CONFIG, ("rozliczenia", "centrum"), "copy.replace"),
    "from copy import replace as copied": (SRC_CONFIG, ("rozliczenia",), "copy.replace"),
    "import platform\nsystem = f'{platform.platform()}-{platform.node()}'": (SRC_CONFIG, ("rozliczenia", "centrum"), "platform.node"),
    "from platform import uname\nkomputer = uname().node": (SRC_CONFIG, ("rozliczenia", "centrum"), "platform.uname"),
    "import socket\nkomputer = socket.gethostname()": (SRC_CONFIG, ("rozliczenia", "centrum"), "socket.gethostname"),
    "from socket import getfqdn\nkomputer = getfqdn()": (SRC_CONFIG, ("rozliczenia",), "socket.getfqdn"),
    "import socket\nkomputer = socket.gethostbyaddr(adres)": (SRC_CONFIG, ("rozliczenia",), "socket.gethostbyaddr"),
    "import os\nkomputer = os.uname().nodename": (SRC_CONFIG, ("rozliczenia",), "os.uname"),
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
    # Kod między instrukcjami cudzej funkcji zmienia jej zmienne po sprawdzeniu (sonda przeglądu #1762: sys.settrace
    # podmienia nagłówek wysyłki w outbox._queue_text po kontroli dokładnego typu).
    "import sys\nsys.settrace(sledz)": (SRC_CONFIG, ("rozliczenia", "centrum"), "sys.settrace"),
    "from sys import setprofile as profiluj": (SRC_CONFIG, ("rozliczenia",), "sys.setprofile"),
    "import sys\nsys.monitoring.register_callback(2, 1, sledz)": (SRC_CONFIG, ("rozliczenia",), "sys.monitoring"),
    "import sys\nramki = sys._current_frames()": (SRC_CONFIG, ("rozliczenia",), "sys._current_frames"),
    "import threading\nthreading.settrace(sledz)": (SRC_CONFIG, ("rozliczenia",), "threading.settrace"),
    "from threading import setprofile": (SRC_CONFIG, ("rozliczenia",), "threading.setprofile"),
    "import threading\nthreading.settrace_all_threads(sledz)": (SRC_CONFIG, ("rozliczenia",), "threading.settrace_all_threads"),
    "import threading as watki\nwatki.setprofile_all_threads(sledz)": (SRC_CONFIG, ("rozliczenia",), "threading.setprofile_all_threads"),
    "import bdb\nclass Debuger(bdb.Bdb): ...": (SRC_CONFIG, ("rozliczenia",), "bdb"),
    "import pdb": (SRC_CONFIG, ("rozliczenia",), "pdb"),
    "from trace import Trace": (SRC_CONFIG, ("rozliczenia",), "trace"),
    "import profile": (SRC_CONFIG, ("rozliczenia",), "profile"),
    "from cProfile import Profile": (SRC_CONFIG, ("rozliczenia", "centrum"), "cProfile"),
    "import _lsprof": (SRC_CONFIG, ("rozliczenia",), "_lsprof"),
    # Handler sygnału dostaje ramkę przerwanej funkcji, a hak audytu biegnie w środku audytowanego wywołania (przegląd #1809, W1).
    "import signal\nsignal.signal(signal.SIGALRM, obsluz)": (SRC_CONFIG, ("rozliczenia", "centrum"), "signal.signal"),
    "from sys import addaudithook\naddaudithook(sluchaj)": (SRC_CONFIG, ("rozliczenia",), "sys.addaudithook"),
    # Moduł C i prywatne nazwy pod nazwami z listy: signal.signal owija _signal.signal, threading.*_all_threads woła
    # sys._settraceallthreads i sys._setprofileallthreads, a threading.settrace i setprofile ustawiają _trace_hook i
    # _profile_hook (przegląd #1809, runda 2, D1).
    "import _signal\n_signal.signal(14, obsluz)": (SRC_CONFIG, ("rozliczenia", "centrum"), "_signal"),
    "from _signal import signal as sygnal": (SRC_CONFIG, ("rozliczenia",), "_signal"),
    "from sys import _settraceallthreads": (SRC_CONFIG, ("rozliczenia",), "sys._settraceallthreads"),
    "from sys import _setprofileallthreads": (SRC_CONFIG, ("rozliczenia",), "sys._setprofileallthreads"),
    "from threading import _trace_hook": (SRC_CONFIG, ("rozliczenia",), "threading._trace_hook"),
    "from threading import _profile_hook": (SRC_CONFIG, ("rozliczenia",), "threading._profile_hook"),
    # Mypy wyłączony na funkcji bez komentarza tłumienia, którego licznik tłumień nie widzi (przegląd #1689, W1).
    "import typing\n@typing.no_type_check\ndef f() -> int:\n    return '1'": (SRC_CONFIG, ("rozliczenia",), "typing.no_type_check"),
    "from typing_extensions import no_type_check as unchecked": (TESTS_CONFIG, (), "typing_extensions.no_type_check"),
    "import yaml\ntekst = yaml.safe_dump_all(dokumenty, sort_keys=False)": (ROOT_CONFIG, TOOLS_PROBE, "yaml.safe_dump_all"),
    "import yaml\ntekst = yaml.safe_dump(regula)": (ROOT_CONFIG, (), "yaml.safe_dump"),
    "from yaml import dump as zapisz": (SRC_CONFIG, ("rozliczenia",), "yaml.dump"),
    "import yaml as y\ny.dump_all(dokumenty, plik)": (DRIVE_CONFIG, (), "yaml.dump_all"),
    # Treść z Wydania w miejscu pliku Ustawień bez odczytu: postacie z tabeli przypadków przy ZNANE_LUKI_TRESCI_Z_WYDANIA,
    # pierwsza to mail z treścią z Wydania z przeglądu #2029 (r1, W1).
    "from rozliczenia.settlement_mailing import DEFAULT_SETTLEMENT_MAIL": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.settlement_mailing.DEFAULT_SETTLEMENT_MAIL",
    ),
    "from ..settlement_mailing import DEFAULT_SETTLEMENT_MAIL": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.settlement_mailing.DEFAULT_SETTLEMENT_MAIL",
    ),
    "from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES as rules": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.quantity_rules_file.DEFAULT_QUANTITY_RULES",
    ),
    "from rozliczenia import activity_legend_file\nlegend = activity_legend_file.DEFAULT_ACTIVITY_LEGEND": (
        SRC_CONFIG,
        ("rozliczenia",),
        "rozliczenia.activity_legend_file.DEFAULT_ACTIVITY_LEGEND",
    ),
    "import rozliczenia.worker_reports as reports\nfooter = reports.DEFAULT_REMINDERS.footer": (
        SRC_CONFIG,
        ("rozliczenia", "centrum"),
        "rozliczenia.worker_reports.DEFAULT_REMINDERS",
    ),
    "from rozliczenia.worker_reports import DEFAULT_SCHEDULE": (SRC_CONFIG, ("rozliczenia",), "rozliczenia.worker_reports.DEFAULT_SCHEDULE"),
    "from rozliczenia.worker_reports import DEFAULT_TEXT": (SRC_CONFIG, ("rozliczenia", "centrum"), "rozliczenia.worker_reports.DEFAULT_TEXT"),
    "from ._reminders import DEFAULT_REMINDERS": (
        SRC_CONFIG,
        ("rozliczenia", "worker_reports"),
        "rozliczenia.worker_reports._reminders.DEFAULT_REMINDERS",
    ),
    "from ._reminders import DEFAULT_SCHEDULE": (
        SRC_CONFIG,
        ("rozliczenia", "worker_reports"),
        "rozliczenia.worker_reports._reminders.DEFAULT_SCHEDULE",
    ),
    "from rozliczenia.worker_reports._reminders import DEFAULT_TEXT": (
        SRC_CONFIG,
        ("rozliczenia",),
        "rozliczenia.worker_reports._reminders.DEFAULT_TEXT",
    ),
    # Raporty wykonawców okna poza odczytem okna w module rdzenia raportów bez prawa właściciela: liczby widoku Raporty z
    # przeglądów #2068 (r1, W2) i #2085 (r1 i r2, W1); postacie spoza pakietu odrzuca mypy (DROGI_RAPORTOW_PRZEZ_ODCZYT).
    "from ._model import ReadReport": (SRC_CONFIG, ("rozliczenia", "worker_reports"), "rozliczenia.worker_reports._model.ReadReport"),
    # Wejście odczytu okna spoza pamięci Wpisania (EnteringMemory._inputs) w module rdzenia raportów bez prawa
    # właściciela; postacie spoza pakietu, w tym Przypomnienia o raporcie z przeglądu #2059 (r1, W1), odrzuca mypy
    # (DROGI_WEJSCIA_ODCZYTU).
    "from ._model import ReportInputs": (SRC_CONFIG, ("rozliczenia", "worker_reports"), "rozliczenia.worker_reports._model.ReportInputs"),
}


def _banned(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("flake8-tidy-imports", {}).get("banned-api", {}))


def _ruff_table(path: Path) -> dict[str, Any] | None:
    """Tabela ustawień ruff pliku: cały ``ruff.toml``, a z ``pyproject.toml`` tylko ``[tool.ruff]``, bez niej ``None``."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("ruff") if path.name == "pyproject.toml" else data


def _configs(root: Path) -> set[Path]:
    """Każdy plik konfiguracji ruff w katalogach, które ruff sprawdza, i w korzeniu poza jego ``ruff.toml``: także
    ``[tool.ruff]`` w ``pyproject.toml`` korzenia, którą ruff pomija obok ``ruff.toml``."""
    candidates = {path for top in CHECKED for name in NAMES for path in (root / top).rglob(name)}
    candidates |= {root / name for name in NAMES if name != "ruff.toml" and (root / name).exists()}
    return {path for path in candidates if _ruff_table(path) is not None}


def test_szukanie_konfiguracji_widzi_pyproject_z_tabela_ruff_w_podkatalogu_i_korzeniu(tmp_path: Path) -> None:
    (tmp_path / "tools" / "z_ruff").mkdir(parents=True)
    (tmp_path / "tools" / "z_ruff" / "pyproject.toml").write_text("[tool.ruff]\nextend = '../../ruff.toml'\n")
    (tmp_path / "tools" / "bez_ruff").mkdir()
    (tmp_path / "tools" / "bez_ruff" / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / ".ruff.toml").write_text("extend = '../ruff.toml'\n")
    (tmp_path / "ruff.toml").write_text("")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")

    assert _configs(tmp_path) == {
        tmp_path / "tools" / "z_ruff" / "pyproject.toml",
        tmp_path / "src" / ".ruff.toml",
        tmp_path / "pyproject.toml",
    }


def test_katalog_z_wlasnymi_zakazami_ruff_powtarza_kazdy_zakaz_korzenia() -> None:
    assert _configs(ROOT) == set(DIRECTORY_CONFIGS), (
        "dopisz nowy plik konfiguracji ruff do DIRECTORY_CONFIGS w tests/test_zakazy_ruff.py; "
        "konfiguracja korzenia stoi tylko w ruff.toml, bo ruff pomija obok niego [tool.ruff] z pyproject.toml"
    )

    root = _banned(tomllib.loads(ROOT_CONFIG.read_text(encoding="utf-8"))["lint"])
    problems = []
    for path in DIRECTORY_CONFIGS:
        config = _ruff_table(path) or {}
        where = path.relative_to(ROOT).as_posix()
        if (path.parent / config.get("extend", "")).resolve() != ROOT_CONFIG:
            problems.append(f"{where}: extend nie wskazuje ruff.toml korzenia repozytorium")
        local = _banned(config.get("lint", {}))
        problems += [
            f"{where}: brak zakazu {name} z ruff.toml korzenia"
            for name, entry in root.items()
            if local.get(name) != entry and not (path == TESTS_CONFIG and name in (*DYNAMIC_IMPORT, *ZAPIS_YAML))
        ]

    assert problems == [], "\n".join(
        [*problems, "ruff bierze banned-api z najbliższego pliku konfiguracji w całości: skopiuj tam wpis z ruff.toml korzenia"]
    )


def test_kazdy_zakaz_tylko_katalogu_ma_probke() -> None:
    """Zakaz tylko katalogu to wpis, którego nie ma w ``ruff.toml`` korzenia; kopii jego tabeli pilnuje test zgodności
    wyżej."""
    root = _banned(tomllib.loads(ROOT_CONFIG.read_text(encoding="utf-8"))["lint"])
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


# Kod między instrukcjami cudzej funkcji, którego zakaz w src/ruff.toml nie widzi. Zakaz trzyma listę nazw haków, a nie
# całą klasę: inny hak interpretera, C API i nazwa poza importem przechodzą, a nowo znaleziony członek klasy to nowa próbka
# pod jedną z tych klas mechanizmu. Sondy (3.13, dane syntetyczne) podmieniają przez gc.callbacks i C API zmienną `parts`
# w outbox._queue_text po kontroli (przegląd #1809).
ZNANE_LUKI_SLEDZENIA = {
    "zakaz zna tylko nazwę z importu: getattr(sys, \"settrace\")": 'import sys\n\ngetattr(sys, "settrace")(lambda ramka, zdarzenie, arg: None)\n',
    "zakaz zna tylko nazwy z listy: inny hak interpretera, gc.callbacks z ramką z inspect": (
        "import gc\nimport inspect\n\n\ndef zwrotne(faza: str, info: dict[str, int]) -> None:\n"
        "    ramka = inspect.currentframe()\n    if ramka is not None and ramka.f_back is not None:\n"
        "        ramka.f_back.f_locals[\"parts\"] = ()\n\n\ngc.callbacks.append(zwrotne)\n"
    ),
    "zakaz zna tylko nazwy z listy: C API przez ctypes (PyEval_SetTrace)": (
        "import ctypes\n\nctypes.pythonapi.PyEval_SetTrace(None, None)\n"
    ),
    "zakaz zna tylko nazwy z listy: ramka wywołującego z inspect": (
        "import inspect\n\n\ndef podmien() -> None:\n    ramka = inspect.currentframe()\n"
        "    if ramka is not None and ramka.f_back is not None:\n        ramka.f_back.f_locals[\"header\"] = \"x\"\n"
    ),
}
ZNANE_LUKI_SLEDZENIA_POZA_SRC = {
    "zakaz obowiązuje tylko w src/: sys.settrace w narzędziu tools/": "import sys\n\nsys.settrace(None)\n",
}


@wymaga_ruff
def test_znane_luki_zakazu_sledzenia_w_src_przechodza_przez_ruff(tmp_path: Path) -> None:
    (tmp_path / "poza").mkdir()
    w_src = ruff(zapisz(ZNANE_LUKI_SLEDZENIA, tmp_path), sonda=SRC_CONFIG.parent / "rozliczenia" / "centrum" / "sonda_luki.py")
    poza = ruff(zapisz(ZNANE_LUKI_SLEDZENIA_POZA_SRC, tmp_path / "poza"), sonda=ROOT.joinpath(*TOOLS_PROBE, "sonda_luki.py"))

    assert_znane_luki(w_src | poza, "tests/test_zakazy_ruff.py (ZNANE_LUKI_SLEDZENIA)")


ZNANE_LUKI_NAZWY_KOMPUTERA = {
    "zakaz zna tylko nazwy z listy: zmienna środowiska COMPUTERNAME": 'import os\n\nkomputer = os.environ["COMPUTERNAME"]\n',
    "zakaz zna tylko wywołania Pythona: program hostname": (
        'import subprocess\n\nkomputer = subprocess.run(["hostname"], capture_output=True, check=True).stdout\n'
    ),
    "zakaz zna tylko nazwę z importu: getattr(platform, \"node\")": 'import platform\n\nkomputer = getattr(platform, "node")()\n',
}


@wymaga_ruff
def test_znane_luki_zakazu_nazwy_komputera_w_src_przechodza_przez_ruff(tmp_path: Path) -> None:
    w_src = ruff(zapisz(ZNANE_LUKI_NAZWY_KOMPUTERA, tmp_path), sonda=SRC_CONFIG.parent / "rozliczenia" / "centrum" / "sonda_luki.py")

    assert_znane_luki(w_src, "tests/test_zakazy_ruff.py (ZNANE_LUKI_NAZWY_KOMPUTERA)")


_GLOWA_WIDOKU: Final = "from rozliczenia.centrum.settings.owner import CentrumSettings\n{importy}\n\n\n"


def _opcje_mypy_src() -> str:
    """Opcje mypy modułów ``rozliczenia.*`` z ``pyproject.toml`` jako konfiguracja w pliku (``# mypy: …``): próbka leży
    poza ``src/``, a mypy ma sprawdzić ją tak jak kod w ``src/``."""

    overrides = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]["overrides"]
    src = [override for override in overrides if "rozliczenia.*" in override["module"]]
    options = [name.replace("_", "-") for override in src for name, value in override.items() if value is True]
    return f"# mypy: {', '.join(options)}\n" if options else ""


def _glowa(owner: str, *importy: str) -> str:
    return "".join(f"{linia}\n" for linia in importy) + f"from rozliczenia.centrum.settings.owner import {owner}\n\n\n"


_BEZ_ODCZYTU: Final = "from rozliczenia.centrum.settings.files import Unreadable"
_MARTWA_GALAZ: Final = '"Unreadable" is final'
_LISTA: Final = "from rozliczenia.worker_list import WorkerList"
_GLOWA_MIGAWKI_LISTY: Final = """from pathlib import Path

from rozliczenia.centrum.settings.files import {nazwy}
from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.worker_list import WorkerList


"""
_ODCZYT_LISTY_DO_USABLE: Final = 'Argument 1 to "usable" has incompatible type "WorkerListRead"'
_MARTWA_GALAZ_LISTY: Final = '"WorkerListRead" is final'

DROGI_TRESCI_Z_WYDANIA: Final = {
    "literał w gałęzi „bez odczytu” wartości migawki bez unii (#2029 r1 W1)": (
        _glowa("SettingsSnapshot", _BEZ_ODCZYTU) + "def stopka(snapshot: SettingsSnapshot) -> str:\n    reminders = snapshot.reminders\n"
        '    return "" if isinstance(reminders, Unreadable) else reminders.footer\n',
        _MARTWA_GALAZ,
    ),
    "konstruktor z wartościami domyślnymi w gałęzi „bez odczytu” wartości migawki bez unii (#1931 r1 D2)": (
        _glowa("SettingsSnapshot", _BEZ_ODCZYTU, "from rozliczenia.centrum.settings.folders import FolderSettings") + "def foldery(snapshot: SettingsSnapshot) -> FolderSettings:\n    folders = snapshot.folders\n"
        "    if isinstance(folders, Unreadable):\n        return FolderSettings()\n    return folders\n",
        _MARTWA_GALAZ,
    ),
    "konstruktor z wartościami domyślnymi w gałęzi „bez odczytu” Folderów okna": (
        _glowa("CentrumSettings", _BEZ_ODCZYTU, "from rozliczenia.centrum.settings.folders import FolderSettings") + "def foldery(settings: CentrumSettings) -> FolderSettings:\n    folders = settings.folders()\n"
        "    return FolderSettings() if isinstance(folders, Unreadable) else folders\n",
        _MARTWA_GALAZ,
    ),
    "gałąź „bez odczytu” Reguł ilości, którymi liczy okno": (
        _glowa("CentrumSettings", _BEZ_ODCZYTU, "from rozliczenia.quantity_engine import QuantityRules") + "def reguly(settings: CentrumSettings) -> QuantityRules | None:\n"
        "    rules = settings.quantity_rules().rules\n    return None if isinstance(rules, Unreadable) else rules\n",
        _MARTWA_GALAZ,
    ),
    "pole widoku do pokazania w odczycie, który liczy: podpowiedzi Listy Urządzeń z shown (#2078 r1 W1)": (
        _GLOWA_WIDOKU.format(
            importy="from rozliczenia.centrum.contract.quantity_rules import DeviceSuggestions\n"
            "from rozliczenia.centrum.device_suggestions import device_suggestions\n"
            "from rozliczenia.centrum.quantity_rules_preview import Recent"
        )
        + "def podpowiedzi(settings: CentrumSettings, recent: Recent) -> DeviceSuggestions:\n"
        "    return device_suggestions(settings.quantity_rules().shown, recent)\n",
        'Argument 1 to "device_suggestions" has incompatible type "ShownQuantityRules"',
    ),
    "pole widoku do pokazania jako legenda, którą się liczy": (
        _GLOWA_WIDOKU.format(importy="from rozliczenia.activity_legend import ActivityLegend")
        + "def legenda(settings: CentrumSettings) -> ActivityLegend:\n    return settings.activity_legend().shown\n",
        'Incompatible return value type (got "ShownActivityLegend", expected "ActivityLegend")',
    ),
    "Lista Wykonawców bez odczytu jako zła lista bez ostatniej dobrej: usable() na migawce (Decyzja 4A, przyczyna bez-adresow)": (
        _GLOWA_MIGAWKI_LISTY.format(nazwy="usable") + "def lista(config: Path) -> WorkerList | None:\n    return usable(read_snapshot(config).workers)\n",
        _ODCZYT_LISTY_DO_USABLE,
    ),
    "Lista Wykonawców bez odczytu jako pusta lista: usable() or WorkerList(())": (
        _GLOWA_MIGAWKI_LISTY.format(nazwy="usable")
        + "def lista(config: Path) -> WorkerList:\n    return usable(read_snapshot(config).workers) or WorkerList(())\n",
        _ODCZYT_LISTY_DO_USABLE,
    ),
    "pusta lista w jawnej gałęzi „bez odczytu” odczytu Listy Wykonawców": (
        _GLOWA_MIGAWKI_LISTY.format(nazwy="Unreadable, usable") + "def lista(config: Path) -> WorkerList | None:\n"
        "    workers = read_snapshot(config).workers\n    return WorkerList(()) if isinstance(workers, Unreadable) else usable(workers)\n",
        _MARTWA_GALAZ_LISTY,
    ),
    "wartość dobrego odczytu Listy Wykonawców wzięta przez isinstance": (
        _GLOWA_MIGAWKI_LISTY.format(nazwy="Good") + "def lista(config: Path) -> WorkerList | None:\n"
        "    workers = read_snapshot(config).workers\n    return workers.value if isinstance(workers, Good) else None\n",
        _MARTWA_GALAZ_LISTY,
    ),
    "pusta lista w gałęzi „bez odczytu” Listy Wykonawców, którą liczy Uruchomienie": (
        _glowa("SettingsSnapshot", _BEZ_ODCZYTU, _LISTA) + "def lista(snapshot: SettingsSnapshot) -> WorkerList:\n"
        "    workers = snapshot.workers.counted()\n    return WorkerList(()) if isinstance(workers, Unreadable) else workers\n",
        _MARTWA_GALAZ,
    ),
    "odczyt pliku Listy Wykonawców spod jej typu": (
        _glowa("SettingsSnapshot") + "def plik(snapshot: SettingsSnapshot) -> object:\n    return snapshot.workers._read\n",
        "SLF001",
    ),
    "Lista Wykonawców do pokazania jako lista, którą się liczy": (
        _GLOWA_WIDOKU.format(importy=_LISTA) + "def lista(settings: CentrumSettings) -> WorkerList:\n    return settings.view().workers.shown()\n",
        'Incompatible return value type (got "ShownWorkers", expected "WorkerList")',
    ),
}

ZNANE_LUKI_TRESCI_Z_WYDANIA = {
    "unia na jawne żądanie (_or_unreadable) u wołającego, który powinien odmówić: literał w jej gałęzi": (
        _glowa("SettingsSnapshot", _BEZ_ODCZYTU) + "def stopka(snapshot: SettingsSnapshot) -> str:\n    reminders = snapshot.reminders_or_unreadable\n"
        '    return "" if isinstance(reminders, Unreadable) else reminders.footer\n'
    ),
    "unia na jawne żądanie (_or_unreadable) u wołającego, który powinien odmówić: konstruktor w jej gałęzi": (
        _glowa("CentrumSettings", _BEZ_ODCZYTU, "from rozliczenia.centrum.settings.folders import FolderSettings") + "def foldery(settings: CentrumSettings) -> FolderSettings:\n    folders = settings.folders_or_unreadable()\n"
        "    return FolderSettings() if isinstance(folders, Unreadable) else folders\n"
    ),
    "odmowa właściciela złapana i zastąpiona: konstruktor w except": (
        _glowa("SettingsSnapshot", "from rozliczenia.centrum.refusal import Refusal", "from rozliczenia.centrum.settings.folders import FolderSettings")
        + "def foldery(snapshot: SettingsSnapshot) -> FolderSettings:\n    try:\n        return snapshot.folders\n"
        "    except Refusal:\n        return FolderSettings()\n"
    ),
    "typ widoku do pokazania nie jest QuantityRules, ale niesie jego części: reguły złożone z nich na nowo": (
        _GLOWA_WIDOKU.format(importy="from rozliczenia.quantity_engine import QuantityRules")
        + "def reguly(settings: CentrumSettings) -> QuantityRules:\n    shown = settings.quantity_rules().shown\n"
        "    return QuantityRules(shown.rules, shown.devices)\n"
    ),
    "typ widoku do pokazania nie jest QuantityRules, ale niesie jego części: Lista Urządzeń do pokazania": (
        _GLOWA_WIDOKU.format(importy="from rozliczenia.quantity_engine import DeviceList")
        + "def urzadzenia(settings: CentrumSettings) -> DeviceList:\n    return settings.quantity_rules().shown.devices\n"
    ),
    "unia na jawne żądanie (_or_unreadable) u wołającego, który powinien odmówić: pusta Lista Wykonawców w jej gałęzi": (
        _glowa("SettingsSnapshot", _LISTA) + "def lista(snapshot: SettingsSnapshot) -> WorkerList:\n"
        "    workers = snapshot.workers.counted_or_unreadable()\n    return workers if isinstance(workers, WorkerList) else WorkerList(())\n"
    ),
    "typ widoku do pokazania nie jest WorkerList, ale niesie jego części: lista złożona z nich na nowo": (
        _GLOWA_WIDOKU.format(importy=_LISTA) + "def lista(settings: CentrumSettings) -> WorkerList:\n"
        "    shown = settings.view().workers.shown()\n    return WorkerList(shown.workers, shown.unresolved)\n"
    ),
    "zakaz zna tylko nazwy modułów, nie pola obiektu: wartość domyślna opisu pliku Ustawień": (
        "from rozliczenia.centrum.settings.settlement_mail import SETTLEMENT_MAIL\n\nMAIL = SETTLEMENT_MAIL.default\n"
    ),
    "refleksja po nazwie: getattr modułu": (
        'from rozliczenia import settlement_mailing\n\nMAIL = getattr(settlement_mailing, "DEFAULT_SETTLEMENT_MAIL")\n'
    ),
}


@wymaga_ruff_i_mypy
def test_tresc_z_wydania_poza_wlascicielem_nie_przechodzi_a_znane_luki_przechodza_przez_ruff_i_mypy(tmp_path: Path) -> None:
    """Treść z Wydania pliku Ustawień (``DEFAULT_*``) czyta w ``src/`` tylko właściciel Ustawień i moduły z prawem
    właściciela (``OWNERS``), bo każdy inny wołający, który ma w ręku plik bez odczytu, wstawia ją w miejsce pliku taty.

    | Postać | Zakaz | Próbka |
    |---|---|---|
    | import z modułu: ``from rozliczenia.settlement_mailing import DEFAULT_SETTLEMENT_MAIL`` (#2029 r1 W1) | łapie | ``SAMPLES`` |
    | import względny: ``from ..settlement_mailing import DEFAULT_SETTLEMENT_MAIL`` | łapie | ``SAMPLES`` |
    | import pod inną nazwą: ``… import DEFAULT_QUANTITY_RULES as rules`` | łapie | ``SAMPLES`` |
    | atrybut zaimportowanego modułu: ``activity_legend_file.DEFAULT_ACTIVITY_LEGEND`` | łapie | ``SAMPLES`` |
    | atrybut pakietu pod aliasem: ``reports.DEFAULT_REMINDERS.footer`` | łapie | ``SAMPLES`` |
    | prywatny moduł pakietu: ``from ._reminders import DEFAULT_REMINDERS`` | łapie | ``SAMPLES`` |
    | część treści Przypomnień: ``DEFAULT_SCHEDULE``, ``DEFAULT_TEXT`` | łapie | ``SAMPLES`` |
    | literał w gałęzi „bez odczytu” wartości bez unii: ``reminders = snapshot.reminders``, ``"" if isinstance(reminders, Unreadable) else …`` (#2029 r1 W1) | łapie (mypy ``unreachable``: ``Unreadable`` jest final) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | konstruktor z wartościami domyślnymi w takiej gałęzi: ``FolderSettings()`` przy ``snapshot.folders`` (#1931 r1 D2) i ``settings.folders()`` okna | łapie (mypy ``unreachable``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | gałąź „bez odczytu” Reguł ilości okna: ``settings.quantity_rules().rules`` | łapie (mypy ``unreachable``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | literał albo konstruktor w gałęzi unii na jawne żądanie: ``snapshot.reminders_or_unreadable``, ``settings.folders_or_unreadable()`` | przepuszcza | ``ZNANE_LUKI_TRESCI_Z_WYDANIA`` |
    | odmowa właściciela złapana i zastąpiona: ``except Refusal: return FolderSettings()`` | przepuszcza | ``ZNANE_LUKI_TRESCI_Z_WYDANIA`` |
    | pole widoku do pokazania w odczycie, który liczy: ``device_suggestions(settings.quantity_rules().shown, …)`` (#2078 r1 W1; ``.rules`` to unia z ``Unreadable``) | łapie (mypy: ``ShownQuantityRules``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | legenda do pokazania jako legenda, którą się liczy: ``settings.activity_legend().shown`` | łapie (mypy: ``ShownActivityLegend``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | Lista Wykonawców jako zła lista bez ostatniej dobrej albo pusta: ``usable(read_snapshot(config).workers)``, ``… or WorkerList(())`` (Decyzja 4A) | łapie (mypy ``arg-type``: ``WorkerListRead``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | gałąź z typem odczytu pliku przy odczycie Listy Wykonawców: ``isinstance(workers, Unreadable)``, ``isinstance(workers, Good)`` | łapie (mypy ``unreachable``: ``WorkerListRead`` jest final) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | pusta lista w gałęzi „bez odczytu” listy, którą liczy Uruchomienie: ``snapshot.workers.counted()`` | łapie (mypy ``unreachable``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | odczyt pliku spod typu: ``snapshot.workers._read`` | łapie (ruff ``SLF001``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | Lista Wykonawców do pokazania jako liczona: ``settings.view().workers.shown()`` | łapie (mypy: ``ShownWorkers``) | ``DROGI_TRESCI_Z_WYDANIA`` |
    | pusta lista w gałęzi unii na jawne żądanie: ``snapshot.workers.counted_or_unreadable()`` | przepuszcza | ``ZNANE_LUKI_TRESCI_Z_WYDANIA`` |
    | części widoku do pokazania: ``QuantityRules(shown.rules, shown.devices)``, ``shown.devices``, ``WorkerList(shown.workers, shown.unresolved)`` | przepuszcza | ``ZNANE_LUKI_TRESCI_Z_WYDANIA`` |
    | wartość domyślna opisu pliku: ``SETTLEMENT_MAIL.default`` | przepuszcza | ``ZNANE_LUKI_TRESCI_Z_WYDANIA`` |
    | refleksja po nazwie: ``getattr(settlement_mailing, "DEFAULT_SETTLEMENT_MAIL")`` | przepuszcza | ``ZNANE_LUKI_TRESCI_Z_WYDANIA`` |
    | ``# noqa: TID251`` na linii importu | łapie | ``tests/test_zapadki.py::test_zadna_linia_repo_nie_tlumi_zakazu_ruff`` |

    Poza ``src/`` zakaz nie obowiązuje: narzędzia w ``tools/`` liczą celowo treścią z Wydania. Każda próbka biegnie przez
    mypy z opcjami modułów ``src/`` (``warn_unreachable``), bo leży w katalogu tymczasowym."""
    probe = SRC_CONFIG.parent / "rozliczenia" / "centrum" / "sonda_luki.py"
    opcje = _opcje_mypy_src()
    probki = {opis: kod for opis, (kod, _) in DROGI_TRESCI_Z_WYDANIA.items()} | ZNANE_LUKI_TRESCI_Z_WYDANIA
    pliki = zapisz({opis: opcje + kod for opis, kod in probki.items()}, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=probe)
    for opis, plik in pliki.items():
        zgloszenia[opis] += _release_content_findings("--stdin-filename", str(probe), "-", code=plik.read_text(encoding="utf-8"))

    przepuszczone = {opis: zgloszenia[opis] for opis, (_, odmowa) in DROGI_TRESCI_Z_WYDANIA.items() if not any(odmowa in z for z in zgloszenia[opis])}
    assert przepuszczone == {}
    assert_znane_luki({opis: zgloszenia[opis] for opis in ZNANE_LUKI_TRESCI_Z_WYDANIA}, "tests/test_zakazy_ruff.py (ZNANE_LUKI_TRESCI_Z_WYDANIA)")


_GLOWA_ODCZYTU = (
    "from rozliczenia.worker_reports import OrderKey\n"
    "from rozliczenia.worker_reports._reading import WindowRead\n\n\n"
    "def zlecenia(read: WindowRead) -> frozenset[OrderKey]:\n"
)
_GLOWA_FAKTOW = "from rozliczenia.report_entering import EnteringFacts\n"
_GLOWA_KAPSULY = (
    "from rozliczenia.report_entering import EnteringFacts\n"
    "from rozliczenia.worker_reports import WindowMails\n\n\n"
    "def odczyty(facts: EnteringFacts) -> object:\n"
)
# Raporty wykonawców Wpisania raportów bez nazwy ReadReport: z pola odczytu okna (moduł pakietu spoza właścicieli, sonda
# przeglądu #2114 r1 W1, ``read_window(inputs).reports`` bez Wpisów na życzenie), z pola dopisania i z odczytów maili
# wyniku rdzenia albo faktów kliknięcia (Logi kliknięcia w report_entering.py przed d18d2e48c7); odczyt → zgłoszenie,
# które go odrzuca.
DROGI_RAPORTOW_PRZEZ_ODCZYT = {
    "import z pakietu (Logi kliknięcia w report_entering.py przed d18d2e48c7)": (
        "from rozliczenia.worker_reports import MailRead, ReadReport\n\nREADS = (MailRead, ReadReport)\n",
        'has no attribute "ReadReport"',
    ),
    "atrybut pakietu pod aliasem: reports.ReadReport": (
        "import rozliczenia.worker_reports as reports\n\n\n"
        "def raporty(reads: tuple[object, ...]) -> int:\n    return sum(isinstance(read, reports.ReadReport) for read in reads)\n",
        'has no attribute "ReadReport"',
    ),
    "pole odczytu okna z Raportami wykonawców (#2114 r1 W1)": (
        _GLOWA_ODCZYTU + "    return frozenset(OrderKey(entry.number, report.day, report.worker) for report in read.reports for entry in report.entries)\n",
        "attr-defined",
    ),
    "prywatne pole odczytu okna z Raportami wykonawców Wpisania": (
        _GLOWA_ODCZYTU + "    return frozenset(OrderKey(entry.number, report.day, report.worker) for report in read._entering for entry in report.entries)\n",
        "SLF001",
    ),
    "wzorzec klasy odczytu okna po nazwie pola (#2114 r2 W1)": (
        _GLOWA_ODCZYTU
        + "    match read:\n"
        + "        case WindowRead(_entering=entering):\n"
        + "            return frozenset(OrderKey(entry.number, report.day, report.worker) for report in entering for entry in report.entries)\n"
        + "    return frozenset()\n",
        "has no attribute",
    ),
    "pole obiektu dopasowania: Raport wykonawcy Zlecenia dopisanego z raportu": (
        _GLOWA_ODCZYTU
        + "    added = read.additions\n"
        + "    return frozenset(OrderKey(entry.number, found.day, found.worker) for found in added for entry in found.report.entries)\n",
        'has no attribute "report"',
    ),
    "wykluczenie pozostałych odczytów maila w odczytach wyniku rdzenia": (
        "from rozliczenia.worker_reports import OrderNumber, ReadStranger, ReadUnreadable, ReportsOutcome\n\n\n"
        "def numery(outcome: ReportsOutcome) -> set[OrderNumber]:\n"
        "    return {entry.number for read in outcome.mails if not isinstance(read, (ReadUnreadable, ReadStranger)) for entry in read.entries}\n",
        "(not iterable)",
    ),
    "refleksja po nazwie: pole odczytu maila przez getattr w odczytach faktów kliknięcia": (
        _GLOWA_FAKTOW + "\n\n"
        "def wpisy(facts: EnteringFacts) -> int:\n"
        '    return sum(len(getattr(read, "entries", ())) for read in facts.mails if type(read).__name__ == "ReadReport")\n',
        "(not iterable)",
    ),
    "wzorzec klasy kapsuły po nazwie pola (#2190 r1 W1)": (
        _GLOWA_KAPSULY + "    match facts.mails:\n        case WindowMails(_reads=reads):\n            return reads\n    return None\n",
        'has no attribute "_reads"',
    ),
    "wzorzec klasy kapsuły po nazwie pola z name mangling": (
        _GLOWA_KAPSULY + "    match facts.mails:\n        case WindowMails(_WindowMails__reads=reads):\n            return reads\n    return None\n",
        'has no attribute "_WindowMails__reads"',
    ),
    "wzorzec klasy kapsuły pozycyjny": (
        _GLOWA_KAPSULY + "    match facts.mails:\n        case WindowMails(reads):\n            return reads\n    return None\n",
        'doesn\'t define "__match_args__"',
    ),
    "pole kapsuły z name mangling jako atrybut": (
        _GLOWA_KAPSULY + "    return facts.mails._WindowMails__reads\n",
        'has no attribute "_WindowMails__reads"',
    ),
    "pole kapsuły __reads jako atrybut spoza klasy": (_GLOWA_KAPSULY + "    return facts.mails.__reads\n", "SLF001"),
    "pola kapsuły przez dataclasses.fields": (
        "import dataclasses\n\n" + _GLOWA_KAPSULY + "    return [getattr(facts.mails, field.name) for field in dataclasses.fields(facts.mails)]\n",
        "arg-type",
    ),
    "pola kapsuły przez dataclasses.asdict": ("import dataclasses\n\n" + _GLOWA_KAPSULY + "    return dataclasses.asdict(facts.mails)\n", "call-overload"),
    "kopia kapsuły przez dataclasses.replace": ("import dataclasses\n\n" + _GLOWA_KAPSULY + "    return dataclasses.replace(facts.mails)\n", "type-var"),
}
ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM = {
    "kapsuła oddaje zapis do Logów jako JSON: przejście po jego rekordach z zawężeniem isinstance": (
        _GLOWA_FAKTOW + "\n\n"
        "def numery(facts: EnteringFacts) -> set[str]:\n"
        "    return {\n"
        "        number\n"
        "        for record in facts.mails.log()\n"
        '        if record["kind"] == "report" and isinstance(entries := record["entries"], list)\n'
        "        for entry in entries\n"
        '        if isinstance(entry, dict) and isinstance(number := entry["number"], str)\n'
        "    }\n"
    ),
    "Logi Wpisania raportów mają typowane rekordy odczytów: przejście po nich z zawężeniem isinstance": (
        "from rozliczenia.centrum.report_entering_logs import LoggedReportMail, logged_mails\n" + _GLOWA_FAKTOW + "\n\n"
        "def numery(facts: EnteringFacts) -> set[str]:\n"
        "    return {entry.number for read in logged_mails(facts.mails) if isinstance(read, LoggedReportMail) for entry in read.entries}\n"
    ),
    "refleksja po nazwie: pole kapsuły odczytów przez getattr z nazwą po name mangling": (
        _GLOWA_FAKTOW + "\n\n"
        "def wpisy(facts: EnteringFacts) -> int:\n"
        '    return sum(len(getattr(read, "entries", ())) for read in getattr(facts.mails, "_WindowMails__reads"))\n'
    ),
    "refleksja po nazwie: object.__getattribute__ z nazwą po name mangling": (
        _GLOWA_FAKTOW + "\n\ndef odczyty(facts: EnteringFacts) -> object:\n"
        '    return object.__getattribute__(facts.mails, "_WindowMails__reads")\n'
    ),
    "refleksja po stanie: __getstate__ daje sloty kapsuły": (
        _GLOWA_FAKTOW + "\n\ndef odczyty(facts: EnteringFacts) -> object:\n    return facts.mails.__getstate__()\n"
    ),
    "refleksja po stanie: __reduce_ex__ daje sloty kapsuły (#2190 r2 D1)": (
        _GLOWA_FAKTOW + "\n\ndef odczyty(facts: EnteringFacts) -> object:\n    return facts.mails.__reduce_ex__(2)\n"
    ),
    "refleksja po nazwie: inspect.getmembers daje pole kapsuły z name mangling (#2190 r2 D1)": (
        "import inspect\n\n" + _GLOWA_FAKTOW + "\n\n"
        "def wpisy(facts: EnteringFacts) -> int:\n"
        '    return sum(len(getattr(read, "entries", ())) for _, value in inspect.getmembers(facts.mails) if isinstance(value, tuple) for read in value)\n'
    ),
    "import prywatnej nazwy modułu rdzenia, w pakiecie względny: kodek _mails._read na rekordach zapisu do Logów": (
        "from rozliczenia.worker_reports import WindowMails\nfrom rozliczenia.worker_reports._mails import _read\n\n\n"
        "def wpisy(mails: WindowMails) -> int:\n"
        '    return sum(len(getattr(_read(record), "entries", ())) for record in mails.log())\n'
    ),
    "mypy nie zna name mangling we wzorcu klasy: case WindowMails(__reads=...) (w działaniu nic nie wiąże)": (
        _GLOWA_KAPSULY + "    match facts.mails:\n        case WindowMails(__reads=reads):\n            return reads\n    return None\n"
    ),
    "mypy nie zna __slots__: vars() i __dict__ (w działaniu TypeError i AttributeError)": (
        _GLOWA_FAKTOW + "\n\ndef odczyty(facts: EnteringFacts) -> object:\n    return vars(facts.mails), facts.mails.__dict__\n"
    ),
}


@wymaga_ruff_i_mypy
def test_znane_luki_zakazu_raportow_wykonawcow_poza_odczytem_okna_przechodza_przez_ruff_i_mypy(tmp_path: Path) -> None:
    """Raporty wykonawców okna (``ReadReport``) i ich Wpisy czyta w ``src/`` tylko odczyt okna i moduły z prawem
    właściciela (``OWNERS``), bo moduł, który sam przechodzi po ``ReadReport``, nie zna raportu z błędem tematu ani
    Wpisu na życzenie (ADR 0041) i liczy po swojemu, które zlecenia mają Wpis tego kliknięcia. Poza pakietem odczyty
    maili są tylko w kapsule ``WindowMails`` (``ReportsOutcome.mails``, ``EnteringFacts.mails``), która nie jest
    iterowalna i trzyma je w polu z name mangling (``__reads``), a wariantów odczytu pakiet nie wystawia, więc kształt
    pilnuje tego mypy; zakaz ruff ``_model.ReadReport`` łapie już tylko moduł rdzenia raportów bez prawa właściciela.

    | Postać | Strażnik | Próbka |
    |---|---|---|
    | import względny w pakiecie: ``from ._model import ReadReport`` (#2068 r1 W2, #2085 r1 W1 i r2 W1, ``_figures.py``) | ruff ``TID251`` | ``SAMPLES`` |
    | import z modułu prywatnego spoza pakietu: ``from ..worker_reports._model import ReadReport`` | ``tests/test_granice_importow.py::test_moduly_prywatne_rdzenia_raportow_importuje_tylko_jego_pakiet`` | ``REPORT_CORE_PRIVATE`` tam |
    | import z pakietu: ``from rozliczenia.worker_reports import MailRead, ReadReport`` (Logi kliknięcia w ``report_entering.py``) | mypy ``attr-defined`` (w działaniu ``ImportError``) | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | atrybut pakietu pod aliasem: ``isinstance(read, reports.ReadReport)`` | mypy ``attr-defined`` | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | pole odczytu okna: ``read_window(inputs).reports`` (#2114 r1 W1) | mypy: ``WindowRead`` nie ma pola z Raportami | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | prywatne pole odczytu okna: ``read._entering`` | ruff ``SLF001`` | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | wzorzec klasy po nazwie pola: ``case WindowRead(_entering=entering)`` (#2114 r2 W1; pozycyjny wiąże tylko wyniki odczytu) | mypy: ``WindowRead`` nie ma pola z Raportami | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | pole obiektu dopasowania: ``Addition.report`` z ``WindowRead.additions`` | mypy: ``Addition`` nie ma pola z Raportem, tylko jego numery | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | wykluczenie pozostałych odczytów: ``not isinstance(read, (ReadUnreadable, ReadStranger))`` po ``outcome.mails`` | mypy: pakiet nie wystawia wariantów, a ``WindowMails`` nie jest iterowalne | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | refleksja po nazwie: ``getattr(read, "entries", ())``, ``type(read).__name__`` po ``facts.mails`` | mypy: ``WindowMails`` nie jest iterowalne | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | wzorzec klasy kapsuły po nazwie pola: ``case WindowMails(_reads=reads)`` (#2190 r1 W1) i ``_WindowMails__reads=`` | mypy: odczyty są w polu z name mangling (``__reads``), którego wzorzec spoza klasy nie nazwie | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | wzorzec klasy kapsuły pozycyjny: ``case WindowMails(reads)`` | mypy: kapsuła nie ma ``__match_args__`` | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | pole kapsuły jako atrybut: ``facts.mails._WindowMails__reads``, ``facts.mails.__reads`` | mypy ``attr-defined``, ruff ``SLF001`` | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | pola kapsuły przez ``dataclasses.fields``, ``asdict``, ``replace`` | mypy: kapsuła nie jest dataclass | ``DROGI_RAPORTOW_PRZEZ_ODCZYT`` |
    | zapis do Logów: rekordy ``facts.mails.log()`` z zawężeniem JSON przez ``isinstance`` | przepuszcza (bez zawężenia mypy odrzuca) | ``ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM`` |
    | rekordy Logów: ``logged_mails(facts.mails)`` z ``isinstance(read, LoggedReportMail)`` | przepuszcza | ``ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM`` |
    | refleksja po nazwie pola kapsuły: ``getattr(facts.mails, "_WindowMails__reads")``, ``object.__getattribute__``, ``inspect.getmembers(facts.mails)`` (#2190 r2 D1) | przepuszcza | ``ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM`` |
    | refleksja po stanie: ``facts.mails.__getstate__()``, ``facts.mails.__reduce_ex__(2)`` (#2190 r2 D1) | przepuszcza | ``ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM`` |
    | prywatny kodek odczytów w module rdzenia bez prawa właściciela: ``from ._mails import _read`` na rekordach ``mails.log()`` | przepuszcza (import względny prywatnej nazwy: ``ZNANE_LUKI_IMPORTU_SRC`` w ``tests/test_granice_importow.py``) | ``ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM`` |
    | ``case WindowMails(__reads=reads)``, ``vars(facts.mails)``, ``facts.mails.__dict__`` | przepuszcza, ale w działaniu nic nie oddaje (``tests/test_rdzen_raportow.py::test_kapsula_odczytow_maili_nie_oddaje_odczytow_wzorcem_klasy_vars_ani_dict``) | ``ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM`` |

    Poza ``src/`` zakaz nie obowiązuje: próba skrzynki raportów w ``tools/`` czyta rekordy Logów każdego maila osobno."""
    probe = SRC_CONFIG.parent / "rozliczenia" / "worker_reports" / "sonda_luki.py"
    probki = {opis: kod for opis, (kod, _) in DROGI_RAPORTOW_PRZEZ_ODCZYT.items()} | ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM

    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=probe)

    przepuszczone = {
        opis: zgloszenia[opis] for opis, (_, odmowa) in DROGI_RAPORTOW_PRZEZ_ODCZYT.items() if not any(odmowa in z for z in zgloszenia[opis])
    }
    assert przepuszczone == {}, "odczyt okna albo kapsuła odczytów znów daje Raporty wykonawców modułowi spoza właścicieli: daj mu fakt odczytu"
    assert_znane_luki(
        {opis: zgloszenia[opis] for opis in ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM}, "tests/test_zakazy_ruff.py (ZNANE_LUKI_RAPORTOW_POZA_ODCZYTEM)"
    )


# Wejście odczytu okna spoza pamięci Wpisania (EnteringMemory._inputs): postać → (kod, zgłoszenie, które ją odrzuca).
# Spoza pakietu rdzenia raportów, bo pakiet nie wystawia ReportInputs ani ReminderInputs, a EnteringMemory nie oddaje
# wejścia; import z modułu prywatnego spoza pakietu odrzuca tests/test_granice_importow.py (REPORT_CORE_PRIVATE).
DROGI_WEJSCIA_ODCZYTU: Final = {
    "import z pakietu w Centrum: Przypomnienia o raporcie z własnym wejściem (#2059 r1 W1)": (
        "from rozliczenia.worker_reports import OwnEntries, ReportInputs\n\nINPUTS = (OwnEntries.EMPTY, ReportInputs)\n",
        'has no attribute "ReportInputs"',
    ),
    "atrybut pakietu pod aliasem: reports.ReportInputs": (
        "import rozliczenia.worker_reports as reports\n\nINPUTS = reports.ReportInputs\n",
        'has no attribute "ReportInputs"',
    ),
    "kopia wejścia pamięci Wpisania z pustą pamięcią przez dataclasses.replace (#2125 r1)": (
        "import dataclasses\n\nfrom rozliczenia.report_entering import ReportState\n"
        "from rozliczenia.worker_reports import EnteringMemory, OwnEntries\n\n\n"
        "def wejscie(state: ReportState) -> object:\n"
        "    return dataclasses.replace(EnteringMemory(state).report_inputs(), memory=OwnEntries.EMPTY)\n",
        'has no attribute "report_inputs"',
    ),
    "typ pola wejścia przez typing.get_type_hints(ReminderInputs) (#2125 r4 D1)": (
        "import typing\n\nfrom rozliczenia.worker_reports import ReminderInputs\n\nINPUTS = typing.get_type_hints(ReminderInputs)[\"reports\"]\n",
        'has no attribute "ReminderInputs"',
    ),
}
# Postacie, które zakaz _model.ReportInputs i mypy przepuszczają: refleksja po nazwie spoza pakietu (w działaniu
# AttributeError) i wejście zbudowane w module rdzenia raportów, w pakiecie importem względnym, którego
# tests/test_granice_importow.py nie sprawdza (ZNANE_LUKI_IMPORTU_SRC); próbka importuje bezwzględnie, bo mypy sprawdza ją
# w katalogu tymczasowym.
ZNANE_LUKI_WEJSCIA_ODCZYTU = {
    "refleksja po nazwie: getattr(pakiet, \"ReportInputs\") (w działaniu AttributeError, #2125 r4 D1)": (
        "from rozliczenia import worker_reports\n\nINPUTS = getattr(worker_reports, \"ReportInputs\")\n"
    ),
    "refleksja po nazwie w module rdzenia raportów: getattr(_model, \"ReportInputs\")": (
        "from rozliczenia.worker_reports import _model\n\nINPUTS = getattr(_model, \"ReportInputs\")\n"
    ),
    "zakaz zna tylko nazwę klasy, nie kopię: pole Przypomnień rdzenia z pustą pamięcią przez dataclasses.replace": (
        "import dataclasses\n\nfrom rozliczenia.worker_reports import OwnEntries\n"
        "from rozliczenia.worker_reports._reminders import ReminderInputs\n\n\n"
        "def wejscie(inputs: ReminderInputs) -> object:\n    return dataclasses.replace(inputs.reports, memory=OwnEntries.EMPTY)\n"
    ),
}
# Granica prawa właściciela: ruff zwalnia cały plik, więc konstruktor w module, który bierze typ tylko jako pole, przechodzi.
ZNANE_LUKI_PRAWA_DO_WEJSCIA = {
    "prawo do nazwy obejmuje plik: konstruktor w Przypomnieniach rdzenia, które biorą wejście jako pole": (
        "from ._model import OwnEntries, ReportInputs\n\n\n"
        "def wejscie(fields: tuple[object, ...]) -> object:\n    return ReportInputs(*fields, memory=OwnEntries.EMPTY)\n"
    ),
}


@wymaga_ruff_i_mypy
def test_wejscie_odczytu_okna_spoza_pamieci_wpisania_nie_przechodzi_a_znane_luki_przechodza_przez_ruff_i_mypy(tmp_path: Path) -> None:
    """Wejście odczytu okna rdzenia raportów (``ReportInputs``) buduje w ``src/`` tylko pamięć Wpisania za swoimi
    operacjami (``worker_reports.EnteringMemory.enter`` i ``reminders``), to samo dla Wpisania raportów i Przypomnień o
    raporcie, bo dzień raportu zależy od pamięci Wpisania: wejście zbudowane obok, np. z ``OwnEntries.EMPTY`` (#2059 r1
    W1), daje ``read_window`` inny dzień raportu niż kafelek Wpisania. Pakiet nie wystawia wejścia, a ``EnteringMemory``
    go nie oddaje, więc spoza pakietu pilnuje tego mypy; zakaz ruff ``_model.ReportInputs`` łapie już tylko moduł
    rdzenia raportów bez prawa właściciela (typ biorą odczyt okna, Przypomnienia rdzenia i operacja Wpisania).

    Pamięć Wpisania, którą wejście niesie, pilnuje typ ``EnteringMemory`` (powstaje tylko z ``MemorySource``), a jej
    postacie (#2125 r1–r3 W1) i znane luki są w
    ``tests/test_centrum_wpisanie_raportow.py::test_pamiec_wpisania_spoza_report_state_nie_przechodzi_mypy_a_znane_luki_przechodza``.

    | Postać | Strażnik | Próbka |
    |---|---|---|
    | import względny w module rdzenia raportów: ``from ._model import ReportInputs`` | ruff ``TID251`` | ``SAMPLES`` |
    | import z modułu prywatnego spoza pakietu: ``from ..worker_reports._model import ReportInputs`` | ``tests/test_granice_importow.py::test_moduly_prywatne_rdzenia_raportow_importuje_tylko_jego_pakiet`` | ``REPORT_CORE_PRIVATE`` tam |
    | import z pakietu w Centrum: ``from rozliczenia.worker_reports import OwnEntries, ReportInputs`` (#2059 r1 W1) | mypy ``attr-defined`` (w działaniu ``ImportError``) | ``DROGI_WEJSCIA_ODCZYTU`` |
    | atrybut pakietu pod aliasem: ``reports.ReportInputs`` | mypy ``attr-defined`` | ``DROGI_WEJSCIA_ODCZYTU`` |
    | kopia albo typ wejścia pamięci: ``dataclasses.replace(EnteringMemory(state).report_inputs(), …)``, ``type(…)(…)`` (#2125 r1) | mypy ``attr-defined``: pamięć nie oddaje wejścia | ``DROGI_WEJSCIA_ODCZYTU`` |
    | typ pola: ``typing.get_type_hints(ReminderInputs)["reports"]`` (#2125 r4 D1) | mypy ``attr-defined`` (w działaniu ``ImportError``) | ``DROGI_WEJSCIA_ODCZYTU`` |
    | refleksja po nazwie: ``getattr(worker_reports, "ReportInputs")`` | przepuszcza (w działaniu ``AttributeError``) | ``ZNANE_LUKI_WEJSCIA_ODCZYTU`` |
    | w module rdzenia raportów: ``getattr(_model, "ReportInputs")``, ``dataclasses.replace(inputs.reports, memory=…)`` z ``ReminderInputs`` | przepuszcza | ``ZNANE_LUKI_WEJSCIA_ODCZYTU`` |
    | konstruktor w module z prawem do typu (``_reading``, ``_reminders``, ``_operation``) | przepuszcza | ``ZNANE_LUKI_PRAWA_DO_WEJSCIA`` |

    Poza ``src/`` zakaz nie obowiązuje: testy rdzenia budują wejście same, a próba skrzynki raportów w ``tools/`` czyta
    każdy mail bez pamięci Wpisania."""
    probe = SRC_CONFIG.parent / "rozliczenia" / "worker_reports" / "sonda_luki.py"
    probki = {opis: kod for opis, (kod, _) in DROGI_WEJSCIA_ODCZYTU.items()} | ZNANE_LUKI_WEJSCIA_ODCZYTU
    (tmp_path / "prawo").mkdir()

    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=probe)
    zgloszenia |= ruff(zapisz(ZNANE_LUKI_PRAWA_DO_WEJSCIA, tmp_path / "prawo"), sonda=probe.with_name("_reminders.py"))

    przepuszczone = {opis: zgloszenia[opis] for opis, (_, odmowa) in DROGI_WEJSCIA_ODCZYTU.items() if not any(odmowa in z for z in zgloszenia[opis])}
    assert przepuszczone == {}, "rdzeń raportów znów oddaje wejście odczytu okna spoza pamięci Wpisania: daj wołającemu operację EnteringMemory"
    assert_znane_luki(
        {opis: zgloszenia[opis] for opis in (*ZNANE_LUKI_WEJSCIA_ODCZYTU, *ZNANE_LUKI_PRAWA_DO_WEJSCIA)},
        "tests/test_zakazy_ruff.py (ZNANE_LUKI_WEJSCIA_ODCZYTU, ZNANE_LUKI_PRAWA_DO_WEJSCIA)",
    )

# Prawo właściciela: plik, który konfiguracja ruff zwalnia z TID251 (per-file-ignores w ruff.toml korzenia) → zakazane nazwy,
# których jest właścicielem. Ruff zwalnia plik z całego TID251, a nie z jednej nazwy, więc ta tabela trzyma resztę
# zakazów: kod właściciela zgłasza dokładnie swoje nazwy, gdy stoi poza zwolnieniem.
OWNERS: dict[str, frozenset[str]] = {
    "src/rozliczenia/wall_clock.py": frozenset({"datetime.datetime.now"}),
    "src/rozliczenia/centrum/catalog.py": frozenset({"rozliczenia.centrum.process_kind._CATALOG"}),
    "src/rozliczenia/dad_files.py": frozenset({"rozliczenia.workbook_files.file_bytes"}),
    "src/rozliczenia/centrum/app.py": frozenset({"rozliczenia.client_data.empty_memory"}),
    "src/rozliczenia/centrum/case_delivery.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/comment_versions.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/dad_notes.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/outbox.py": frozenset(
        {"rozliczenia.client_data.logs_text", "rozliczenia.client_data.tool", "rozliczenia.centrum.template_archive.from_queue"}
    ),
    "src/rozliczenia/centrum/quantity_check_run.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/reports.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/centrum/run_logs_guard.py": frozenset({"rozliczenia.client_data.logs_text"}),
    "src/rozliczenia/centrum/template_archive.py": frozenset({"rozliczenia.client_data.tool"}),
    "src/rozliczenia/register_file.py": frozenset({"rozliczenia.workbook_files.open_workbook"}),
    "src/rozliczenia/template_file.py": frozenset(
        {"rozliczenia.workbook_files.open_workbook", "rozliczenia.workbook_files.template_content"}
    ),
    "src/rozliczenia/centrum/opener.py": frozenset({"urllib.request.build_opener"}),
    "src/rozliczenia/centrum/settings/activity_legend.py": frozenset({"rozliczenia.activity_legend_file.DEFAULT_ACTIVITY_LEGEND"}),
    "src/rozliczenia/centrum/settings/quantity_rules.py": frozenset({"rozliczenia.quantity_rules_file.DEFAULT_QUANTITY_RULES"}),
    "src/rozliczenia/centrum/settings/reminders.py": frozenset({"rozliczenia.worker_reports.DEFAULT_REMINDERS"}),
    "src/rozliczenia/centrum/settings/settlement_mail.py": frozenset({"rozliczenia.settlement_mailing.DEFAULT_SETTLEMENT_MAIL"}),
    "src/rozliczenia/centrum/settings_router.py": frozenset({"rozliczenia.worker_reports.DEFAULT_REMINDERS"}),
    "src/rozliczenia/centrum/report_reminders.py": frozenset({"rozliczenia.worker_reports.DEFAULT_REMINDERS"}),
    "src/rozliczenia/engine.py": frozenset(
        {"rozliczenia.activity_legend_file.DEFAULT_ACTIVITY_LEGEND", "rozliczenia.quantity_rules_file.DEFAULT_QUANTITY_RULES"}
    ),
    "src/rozliczenia/collective_preparation.py": frozenset(
        {"rozliczenia.activity_legend_file.DEFAULT_ACTIVITY_LEGEND", "rozliczenia.quantity_rules_file.DEFAULT_QUANTITY_RULES"}
    ),
    "src/rozliczenia/worker_reports/__init__.py": frozenset(
        {
            "rozliczenia.worker_reports._reminders.DEFAULT_REMINDERS",
            "rozliczenia.worker_reports._reminders.DEFAULT_SCHEDULE",
            "rozliczenia.worker_reports._reminders.DEFAULT_TEXT",
        }
    ),
    "src/rozliczenia/worker_reports/_reading.py": frozenset(
        {"rozliczenia.worker_reports._model.ReadReport", "rozliczenia.worker_reports._model.ReportInputs"}
    ),
    "src/rozliczenia/worker_reports/_reminders.py": frozenset({"rozliczenia.worker_reports._model.ReportInputs"}),
    "src/rozliczenia/worker_reports/_memory.py": frozenset({"rozliczenia.worker_reports._model.ReportInputs"}),
    "src/rozliczenia/worker_reports/_operation.py": frozenset({"rozliczenia.worker_reports._model.ReportInputs"}),
    "src/rozliczenia/worker_reports/_matching.py": frozenset({"rozliczenia.worker_reports._model.ReadReport"}),
    "src/rozliczenia/worker_reports/_corrections.py": frozenset({"rozliczenia.worker_reports._model.ReadReport"}),
    "src/rozliczenia/worker_reports/_canonical.py": frozenset({"rozliczenia.worker_reports._model.ReadReport"}),
    "src/rozliczenia/worker_reports/_mails.py": frozenset({"rozliczenia.worker_reports._model.ReadReport"}),
    "tools/lib/import_dynamiczny.py": frozenset({"importlib.import_module", "importlib.machinery", "importlib.util"}),
    "src/rozliczenia/centrum/settings/files.py": frozenset({"yaml.dump"}),
    "tests/conftest.py": frozenset({"sys.path"}),
    "tests/fixtures/linie_watkow.py": frozenset({"threading.Thread.start"}),
    ".agents/skills/verify-centrum-rozliczen/scripts/drive/common.py": frozenset({"os.replace", "shutil.rmtree"}),
    ".agents/skills/verify-centrum-rozliczen/scripts/drive/waiting.py": frozenset({"time.sleep"}),
}
# Zakaz z ruff.toml korzenia, który obowiązuje w każdym katalogu (test zgodności wyżej), więc jego brak w zgłoszeniu znaczy
# zwolnienie pliku z TID251.
SHARED_PROBE = "import os\nsystem = os.name\n"


def _banned_names(*arguments: str, code: str | None = None, cwd: Path = ROOT) -> list[tuple[str, str, str]]:
    """``(plik, nazwa, komunikat)`` każdego ``TID251`` i każdego ``import *`` (``F403``, nazwa ``F403``), które ``ruff check`` z
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
            finding["message"],
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
    for config in (ROOT_CONFIG, *_configs(ROOT)):
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

    reported = {name for name, banned, _ in _banned_names(cwd=tmp_path) if banned == "os.name"}

    assert sorted(checked - reported) == sorted(OWNERS), (
        "z TID251 konfiguracja ruff zwalnia tylko pliki z OWNERS w tests/test_zakazy_ruff.py: prawo właściciela to "
        "jego ścieżka w per-file-ignores ruff.toml korzenia i wiersz OWNERS z nazwami, a wyjątek tymczasowy stoi na linii"
    )


def _outside_owner_right(owners: Mapping[str, frozenset[str]], cwd: Path = ROOT) -> list[str]:
    """Pliki ``owners`` w ``cwd`` w jednym biegu ruff bez ``per-file-ignores`` i z ``--ignore-noqa``: każda zakazana nazwa
    spoza prawa pliku i każde ``import *`` z komunikatem zakazu, a potem każda nazwa prawa, której plik już nie używa."""

    found: dict[str, dict[str, str]] = {owner: {} for owner in owners}
    unexempted = ("--config", "lint.per-file-ignores = {}", "--config", "lint.extend-per-file-ignores = {}")
    for path, banned, message in _banned_names(*unexempted, *owners, cwd=cwd):
        found[path].setdefault(banned, message)
    return [
        *(f"{owner}: {found[owner][banned]}" for owner in owners for banned in sorted(found[owner].keys() - owners[owner])),
        *(f"{owner}: {banned} bez użycia" for owner in owners for banned in sorted(owners[owner] - found[owner].keys())),
    ]


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_wlasciciel_uzywa_tylko_swoich_zakazanych_nazw() -> None:
    """Ruff zwalnia plik właściciela z całego ``TID251``, więc reszta zakazów w nim to ten krok reguł chwastów (zadanie
    CI „Ruff, mypy”): inna zakazana nazwa (np. zegar w ``dad_files.py``) albo ``import *`` to droga obok właściciela tej
    nazwy, a nazwa, której właściciel już nie używa, to prawo do usunięcia."""

    outside = _outside_owner_right(OWNERS)

    assert outside == [], "\n".join(
        [
            "plik z prawem właściciela używa zakazanej nazwy spoza swojego wiersza OWNERS w tests/test_zakazy_ruff.py: inną "
            "nazwę bierz przez jej właściciela, a nazwę bez użycia usuń z OWNERS",
            *(f"- {line}" for line in outside),
        ]
    )


_OWNER_CONFIG = """[lint]
select = ["TID251", "F403"]
[lint.per-file-ignores]
"wlasciciel.py" = ["TID251"]
[lint.flake8-tidy-imports.banned-api]
"os.name".msg = "system"
"time.sleep".msg = "czekanie"
"""


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param("import os\nSYSTEM = os.name\n", [], id="własna-nazwa-przechodzi"),
        pytest.param(
            "import os\nimport time\nSYSTEM = os.name\ntime.sleep(1)\n",
            ["wlasciciel.py: `time.sleep` is banned: czekanie"],
            id="cudza-nazwa-obok-własnej-pada",
        ),
        pytest.param(
            "import os\nimport time as czas\nSYSTEM = os.name\nczas.sleep(1)\n",
            ["wlasciciel.py: `time.sleep` is banned: czekanie"],
            id="cudza-nazwa-pod-aliasem-pada",
        ),
        pytest.param(
            "import os\nfrom time import sleep  # noqa: TID251 - próbka\nSYSTEM = os.name\n",
            ["wlasciciel.py: `time.sleep` is banned: czekanie"],
            id="cudza-nazwa-pod-noqa-pada",
        ),
        pytest.param(
            "import os\nfrom time import *\nSYSTEM = os.name\n",
            ["wlasciciel.py: `from time import *` used; unable to detect undefined names"],
            id="import-gwiazdki-pada",
        ),
        pytest.param("import time\ntime.sleep(1)\n", ["wlasciciel.py: `time.sleep` is banned: czekanie", "wlasciciel.py: os.name bez użycia"], id="prawo-bez-użycia-pada"),
    ],
)
def test_zakazana_nazwa_spoza_prawa_wlasciciela_pada_w_pliku_wlasciciela(tmp_path: Path, code: str, expected: list[str]) -> None:
    """Plik z prawem właściciela ``os.name`` w konfiguracji z dwoma zakazami: ``_outside_owner_right`` przepuszcza tylko
    jego nazwę."""

    (tmp_path / "ruff.toml").write_text(_OWNER_CONFIG, encoding="utf-8")
    (tmp_path / "wlasciciel.py").write_text(code, encoding="utf-8")

    assert _outside_owner_right({"wlasciciel.py": frozenset({"os.name"})}, cwd=tmp_path) == expected


# Zakazy treści z Wydania pliku Ustawień w src/ruff.toml, które testy niżej uruchamiają z --ignore-noqa: każda zakazana
# nazwa ``DEFAULT_*``, więc nowa treść z Wydania z zakazem wchodzi tu bez dopisywania.
RELEASE_CONTENT = frozenset(
    name for name in _banned(tomllib.loads(SRC_CONFIG.read_text(encoding="utf-8"))["lint"]) if name.rpartition(".")[2].startswith("DEFAULT_")
)


def _release_content_findings(*arguments: str, code: str | None = None) -> list[str]:
    """``plik: nazwa`` każdego zakazu z ``RELEASE_CONTENT``, który ``ruff check`` z ``--ignore-noqa`` zgłasza."""

    return [f"{path}: {name}" for path, name, _ in _banned_names(*arguments, code=code) if name in RELEASE_CONTENT]


# Zakazy importu w trakcie działania w ruff.toml korzenia (i jego kopiach poza tests/ruff.toml): lista nazw, nie dopasowanie
# komunikatu, żeby nowy zakaz o innym brzmieniu nie wypadł z niej.
# Nazwy pakietu importlib wynikają z biblioteki działającego Pythona (test nazw niżej); reszta to moduły, których zadaniem
# jest import albo wykonanie modułu. Inne moduły biblioteki standardowej, które przy okazji wykonują plik albo importują po
# nazwie, są znaną luką z próbkami w ZNANE_LUKI_IMPORTU, nie pełną listą.
ZAPIS_YAML = ("yaml.dump", "yaml.dump_all", "yaml.safe_dump", "yaml.safe_dump_all")
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


def test_kazdy_zakaz_importu_w_trakcie_dzialania_jest_na_liscie_dynamic_import() -> None:
    """Zakazem importu w trakcie działania jest wpis ``ruff.toml`` korzenia, którego komunikat odsyła do właściciela."""
    banned = _banned(tomllib.loads(ROOT_CONFIG.read_text(encoding="utf-8"))["lint"])
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
        "w ruff.toml korzenia, src/ruff.toml i drive/ruff.toml oraz do DYNAMIC_IMPORT, albo do IMPORTLIB_DOZWOLONE z powodem "
        "i próbką w ZNANE_LUKI_IMPORTU, gdy kod poza tests/ jej potrzebuje"
    )
    assert sorted(IMPORTLIB_DOZWOLONE.keys() - names) == [], "IMPORTLIB_DOZWOLONE wymienia nazwę, której importlib nie ma"


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
    for config in (ROOT_CONFIG, *_configs(ROOT)):
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
# w ``extend-select`` ``ruff.toml`` korzenia, który pozostałe pliki konfiguracji rozszerzają.
INVALID_NOQA_CODES = (
    "import os  # noqa: PR1614 - historia\n",
    "x = 1  # noqa: PR1614 - historia\n",
    "import os  # noqa: F401, PR1614 - historia\n",
    "x = 1  # noqa: E501, PR1614 - historia\n",
)


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
@pytest.mark.parametrize(
    ("folder", "code"),
    [
        *(pytest.param(ROOT / "tools", code, id=f"tools-{number}") for number, code in enumerate(INVALID_NOQA_CODES)),
        *(
            pytest.param(config.parent, INVALID_NOQA_CODES[0], id=config.parent.name)
            for config in DIRECTORY_CONFIGS
        ),
    ],
)
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


MIEJSCE_Z_TEKSTU: Final = """\
from rozliczenia.centrum.settings.files import FieldPath


def miejsca(klucz: str, pole: str) -> tuple[FieldPath, FieldPath]:
    return FieldPath(klucz), FieldPath("wykonawcy", 0, pole)
"""


@wymaga_ruff_i_mypy
def test_miejsce_zlego_ustawienia_z_tekstu_spoza_znanych_nazw_pol_nie_przechodzi_mypy(tmp_path: Path) -> None:
    pliki = zapisz({"tekst z pliku": MIEJSCE_Z_TEKSTU}, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "settings" / "sonda_miejsca.py")

    odrzucone = sorted(zgloszenie.split(" ", 1)[1] for zgloszenie in zgloszenia["tekst z pliku"] if "[arg-type]" in zgloszenie)
    assert [zgloszenie.split(";", 1)[0] for zgloszenie in odrzucone] == sorted(
        [
            *(['Argument 1 to "FieldPath" has incompatible type "str"'] * len(platformy_mypy_ci())),
            *(['Argument 3 to "FieldPath" has incompatible type "str"'] * len(platformy_mypy_ci())),
        ]
    ), zgloszenia
