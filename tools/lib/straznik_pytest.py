"""Plugin pytest dowodu strażnika ``pytest <węzeł>`` (``straznik``, ADR 0042): wynik każdej fazy testów węzła
i wyjątki rozjazdu interfejsu zgłoszone w kodzie plików przeszczepu.

Dowód ładuje plugin z pliku kodu bazy (``straznik._BOOTSTRAP``), nie z drzewa PR, i podaje go ``pytest.main`` jako
obiekt ``Plugin``: drzewo PR, które ma własny plik o tej nazwie, wyniku nie zmienia. Wyjątek rozjazdu to ``TypeError``,
``AttributeError``, ``NameError`` albo ``ImportError`` zgłoszony w pliku z ``watched`` (``sys.monitoring``, zdarzenie
``RAISE`` w miejscu, w którym powstał, także gdy kod niżej go łapie): kod z FAIL, który pada na interfejsie HEAD
(parametr dodany przez poprawkę, metoda przemianowana), a nie na swoim zachowaniu. Granica: wyjątek w procesie
potomnym i wyjątek zgłoszony w pliku spoza ``watched`` plugin pomija.

Wynik w pliku ``output`` (JSON): ``testy`` (id węzła → lista ``faza:wynik``, wynik ``passed``, ``failed``, ``skipped``
albo ``xfail``), ``padniecia`` (komunikat wyjątku każdej fazy z wynikiem ``failed`` i każdego pliku, którego zbieranie padło) i ``rozjazd`` (rodzaj
i komunikat wyjątku rozjazdu).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from types import CodeType

import pytest

DRIFT = (TypeError, AttributeError, NameError, ImportError)
_ADDRESS = re.compile(r"0x[0-9a-f]+")  # adres obiektu w komunikacie różni się między biegami
_FREE_TOOLS = (3, 4)  # identyfikatory sys.monitoring bez roli w Pythonie (debugger 0, pokrycie 1, profiler 2, optymalizator 5)


class Plugin:
    """Plugin jednego biegu pytest: pliki ``watched`` (ścieżki bezwzględne) i plik wyniku ``output``."""

    def __init__(self, watched: list[str], output: str) -> None:
        self._watched = frozenset(watched)
        self._output = Path(output)
        self._tests: dict[str, list[str]] = {}
        self._crashes: list[str] = []
        self._drift: set[tuple[str, str]] = set()

    def pytest_configure(self, config: pytest.Config) -> None:
        monitoring = sys.monitoring
        tool = next(one for one in _FREE_TOOLS if monitoring.get_tool(one) is None)
        monitoring.use_tool_id(tool, "straznik_pytest")
        monitoring.register_callback(tool, monitoring.events.RAISE, self._raised)
        monitoring.set_events(tool, monitoring.events.RAISE)

    def _raised(self, code: CodeType, offset: int, exception: BaseException) -> None:
        if isinstance(exception, DRIFT) and code.co_filename in self._watched:
            self._drift.add((type(exception).__name__, _ADDRESS.sub("0x", str(exception))[:200]))

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
        self._tests.setdefault(report.nodeid, []).append(f"{report.when}:{outcome}")
        if report.failed:
            self._crashes.append(_crash(report))

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self._crashes.append(f"zbieranie {report.nodeid}: {_crash(report)}")

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        found = {"testy": self._tests, "padniecia": self._crashes, "rozjazd": sorted(self._drift)}
        self._output.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")


def _crash(report: pytest.TestReport | pytest.CollectReport) -> str:
    """Pierwsza linia komunikatu wyjątku, którym faza padła (``reprcrash``), albo ostatnia linia jej opisu."""

    crash = getattr(report.longrepr, "reprcrash", None)
    lines = (str(crash.message) if crash is not None else report.longreprtext).strip().splitlines()
    return (lines[0] if crash is not None and lines else lines[-1] if lines else report.nodeid)[:200]
