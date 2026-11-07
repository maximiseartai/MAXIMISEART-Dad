"""Zapis pokrycia zmienionych plików w jednym procesie Pythona dla ``tools/mutacje_zmiany.py``.

Bez pytest, bo ładuje go też ``sitecustomize`` każdego procesu, który uruchamia test (``in_child``). Ustawienia są
w zmiennej ``POKRYCIE_LINII``: JSON ``{"linie": {ścieżka bezwzględna: [numery linii]}, "wynik": katalog}``. Proces
zapisuje w katalogu ``wynik`` plik ``<pid>.json``:

- ``linie``: zmienione linie wykonane przez każdy test;
- ``pliki``: zmienione pliki, których kod (jakakolwiek funkcja albo linia) wykonał każdy test;
- ``wspolne``: zmienione linie wykonane poza testem (import modułu) albo w fixture o zasięgu szerszym niż test, czyli
  kod, którego wynik dostają też inne testy niż ten, który go wykonał;
- ``procesy``: testy, które uruchomiły proces (hak audytu ``subprocess.Popen``, ``os.posix_spawn``, ``os.exec``), bo
  kodu procesu z ``-I`` albo bez tych zmiennych zapis nie widzi.

Proces potomny zapisuje się pod testem ze zmiennej ``POKRYCIE_LINII_TEST``, przy wyjściu. Proces zabity sygnałem,
uruchomiony z ``-I`` albo z własnym środowiskiem bez tych zmiennych nie zapisuje nic.
"""

from __future__ import annotations

import atexit
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import threading
from types import CodeType, FrameType
from typing import Any

VARIABLE = "POKRYCIE_LINII"
TEST = "POKRYCIE_LINII_TEST"
_SPAWNS = frozenset({"subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn", "os.system", "os.startfile"})
SITECUSTOMIZE = "try:\n    import pokrycie_procesu\n    pokrycie_procesu.in_child()\nexcept Exception:\n    pass\n"


class Recorder:
    def __init__(self, lines: dict[str, set[int]]) -> None:
        self.lines = lines
        self.test: str | None = None
        self.shared_depth = 0  # fixture o zasięgu modułu, klasy albo sesji w toku
        self.hits: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        self.files: dict[str, set[str]] = defaultdict(set)
        self.shared: dict[str, set[int]] = defaultdict(set)
        self.spawners: set[str] = set()

    def entered(self, path: str) -> bool:
        """Zapisuje, że test wykonał kod pliku; fałsz, gdy plik nie jest zmieniony."""

        if path not in self.lines:
            return False
        if self.test is not None:
            self.files[self.test].add(path)
        return True

    def hit(self, path: str, line: int) -> bool:
        """Zapisuje zmienioną linię; fałsz, gdy linia nie jest zmieniona i nie trzeba jej więcej śledzić."""

        if line not in self.lines.get(path, ()):
            return False
        if self.test is None or self.shared_depth:
            self.shared[path].add(line)
        if self.test is not None:
            self.hits[self.test][path].add(line)
            self.files[self.test].add(path)
        return True

    def audit(self, event: str, _: tuple[object, ...]) -> None:
        if self.test is not None and event in _SPAWNS:
            self.spawners.add(self.test)

    def write(self, folder: Path) -> None:
        recorded = {
            "linie": {test: {path: sorted(lines) for path, lines in files.items()} for test, files in self.hits.items()},
            "pliki": {test: sorted(paths) for test, paths in self.files.items()},
            "wspolne": {path: sorted(lines) for path, lines in self.shared.items()},
            "procesy": sorted(self.spawners),
        }
        (folder / f"{os.getpid()}.json").write_text(json.dumps(recorded), encoding="utf-8")


def _start(recorder: Recorder) -> None:
    monitoring: Any = getattr(sys, "monitoring", None)
    if monitoring is not None:
        tool = monitoring.COVERAGE_ID
        monitoring.use_tool_id(tool, "pytest_pokrycie")

        def line(code: CodeType, number: int) -> object:
            # DISABLE wyłącza tylko to miejsce kodu, więc każda inna linia kosztuje jedno wywołanie na proces.
            return None if recorder.hit(code.co_filename, number) else monitoring.DISABLE

        def start(code: CodeType, _: int) -> object:
            return None if recorder.entered(code.co_filename) else monitoring.DISABLE

        monitoring.register_callback(tool, monitoring.events.LINE, line)
        monitoring.register_callback(tool, monitoring.events.PY_START, start)
        monitoring.set_events(tool, monitoring.events.LINE | monitoring.events.PY_START)
        return

    def local(frame: FrameType, event: str, _: object) -> Any:
        if event == "line":
            recorder.hit(frame.f_code.co_filename, frame.f_lineno)
        return local

    def call(frame: FrameType, event: str, _: object) -> Any:
        return local if event == "call" and recorder.entered(frame.f_code.co_filename) else None

    threading.settrace(call)
    sys.settrace(call)


_RECORDER: Recorder | None = None


def recorder() -> Recorder:
    """Zapis tego procesu, włączony przy pierwszym wywołaniu."""

    global _RECORDER
    if _RECORDER is None:
        settings = json.loads(os.environ[VARIABLE])
        _RECORDER = Recorder({path: set(lines) for path, lines in settings["linie"].items()})
        _start(_RECORDER)
        sys.addaudithook(_RECORDER.audit)
    return _RECORDER


def write() -> None:
    if _RECORDER is not None:
        _RECORDER.write(Path(json.loads(os.environ[VARIABLE])["wynik"]))


def in_child() -> None:
    """Proces Pythona uruchomiony przez test: zapisuje swoje zmienione linie pod tym testem przy wyjściu."""

    test = os.environ.get(TEST)
    if test is None or VARIABLE not in os.environ:
        return
    recorder().test = test
    atexit.register(write)
