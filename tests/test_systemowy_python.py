"""Pliki, które systemowy Python uruchamia przed ``.venv``, importują się najstarszym Pythonem, jaki dla nich obiecano.

Lista plików i wersji to ``per-file-target-version`` z ``ruff.toml``. Ruff odrzuca w nich nowszą składnię,
a ten test importuje je tą wersją Pythona, więc łapie też API, którego ruff nie widzi, np. ``dataclass(slots=True)``
przed 3.10. Bez takiego Pythona na komputerze (CI na Linuksie) test się pomija.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGETS: dict[str, str] = tomllib.loads((ROOT / "ruff.toml").read_text(encoding="utf-8"))["per-file-target-version"]
LOAD = (
    "import importlib.machinery, importlib.util, sys\n"
    "path, tools = sys.argv[1:]\n"
    "sys.path.insert(0, tools)\n"
    "loader = importlib.machinery.SourceFileLoader('sprawdzany', path)\n"
    "module = importlib.util.module_from_spec(importlib.util.spec_from_loader('sprawdzany', loader))\n"
    "sys.modules['sprawdzany'] = module\n"
    "loader.exec_module(module)\n"
)


def _python(target: str) -> str | None:
    """Python w wersji ``target`` (``py39``): ``python3.9`` z PATH, ``python3`` z PATH albo ``/usr/bin/python3``."""

    version = f"{target[2]}.{target[3:]}"
    for candidate in (shutil.which(f"python{version}"), shutil.which("python3"), "/usr/bin/python3"):
        if candidate is None or not Path(candidate).exists():
            continue
        answered = subprocess.run(
            [candidate, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True, check=False
        )
        if answered.stdout.strip() == version:
            return candidate
    return None


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store, a brama tam nie biegnie")
@pytest.mark.parametrize(("path", "target"), sorted(TARGETS.items()))
def test_plik_uruchamiany_przed_venv_importuje_sie_systemowym_pythonem(path: str, target: str) -> None:
    python = _python(target)
    if python is None:
        pytest.skip(f"brak Pythona {target} na tym komputerze")

    imported = subprocess.run(
        [python, "-I", "-c", LOAD, str(ROOT / path), str(ROOT / "tools")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert imported.returncode == 0, imported.stderr
