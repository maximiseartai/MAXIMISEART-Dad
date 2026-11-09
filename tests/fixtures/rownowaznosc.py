"""Drzewa ze skryptem dla maszyn na niby do testów weryfikacji różnicowej ``tools/rownowaznosc.py``.

Drzewo na niby ma tylko ``tools/uruchom_proces.py``, który drukuje podany JSON, zapisuje podane pliki w folderze
scenariusza i kończy się podanym kodem, więc test porównania nie zależy od procesów. ``METRICS`` w JSON staje się
ścieżką pliku metryk, którą skrypt dostał w ``--metrics``, zapisaną jak w JSON: backslashe ścieżki z Windows jako
``\\\\``.
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from atrapy.workbooks import active_worksheet

__all__ = ["METRICS", "stub_tree", "write_workbook"]

METRICS = "<METRYKI>"

_STUB = """import json, pathlib, sys, time
time.sleep({sleep_s})
for name, text in {files!r}.items():
    path = pathlib.Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
sys.stdout.write({output!r}.replace({metrics!r}, json.dumps(sys.argv[sys.argv.index("--metrics") + 1])[1:-1]))
raise SystemExit({code})
"""


def stub_tree(path: Path, result: object, *, code: int = 0, files: dict[str, str] | None = None, sleep_s: float = 0) -> Path:
    """Drzewo, którego skrypt dla maszyn po ``sleep_s`` sekundach drukuje ``result`` jako JSON (napis: dosłownie) i zapisuje ``files``."""

    output = result if isinstance(result, str) else json.dumps(result)
    script = path / "tools" / "uruchom_proces.py"
    script.parent.mkdir(parents=True)
    script.write_text(_STUB.format(sleep_s=sleep_s, files=files or {}, output=output, metrics=METRICS, code=code), encoding="utf-8")
    return path


def write_workbook(path: Path, value: str | int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    active_worksheet(workbook)["A1"] = value
    workbook.save(path)
    return path
