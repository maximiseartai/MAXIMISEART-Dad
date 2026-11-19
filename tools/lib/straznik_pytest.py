"""Plugin pytest dowodu strażnika ``pytest <węzeł>`` (``straznik``, ADR 0042): jak padła każda faza testów węzła
i jakie wyjątki zgłosił kod plików przeszczepu.

Dowód ładuje plugin z pliku kodu bazy (``straznik._BOOTSTRAP``), nie z drzewa PR, i podaje go ``pytest.main`` jako
obiekt ``Plugin``: drzewo PR, które ma własny plik o tej nazwie, wyniku nie zmienia. Plugin niczego nie klasyfikuje,
tylko zapisuje; porównanie biegów robi ``straznik``.

Wynik w pliku ``output`` (JSON):

- ``testy``: id węzła → lista ``faza:wynik`` (``passed``, ``failed``, ``skipped`` albo ``xfail``);
- ``padniecia``: każda faza z wynikiem ``failed``: id węzła, faza, rodzaj wyjątku, miejsce (najgłębsza ramka w pliku pod
  ``tests/``, ``plik:linia`` względem korzenia) i pierwsza linia komunikatu;
- ``wyjatki``: rodzaj i komunikat każdego wyjątku zgłoszonego w kodzie pliku z ``watched`` (``sys.monitoring``,
  zdarzenie ``RAISE`` w miejscu, w którym powstał, także gdy kod niżej go łapie), bez adresów obiektów. Granica: wyjątek
  w procesie potomnym plugin pomija.
"""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
import re
import sys
from types import CodeType

import pytest

TESTS = "tests/"  # katalog, w którym leży miejsce padnięcia: test albo jego fikstura
_ADDRESS = re.compile(r"0x[0-9a-f]+")  # adres obiektu w komunikacie różni się między biegami
_FREE_TOOLS = (3, 4)  # identyfikatory sys.monitoring bez roli w Pythonie (debugger 0, pokrycie 1, profiler 2, optymalizator 5)


class Plugin:
    """Plugin jednego biegu pytest: pliki ``watched`` (ścieżki bezwzględne) i plik wyniku ``output``."""

    def __init__(self, watched: list[str], output: str) -> None:
        self._watched = frozenset(watched)
        self._output = Path(output)
        self._tests: dict[str, list[str]] = {}
        self._failures: list[dict[str, str]] = []
        self._raised: set[tuple[str, str]] = set()

    def pytest_configure(self, config: pytest.Config) -> None:
        monitoring = sys.monitoring
        tool = next(one for one in _FREE_TOOLS if monitoring.get_tool(one) is None)
        monitoring.use_tool_id(tool, "straznik_pytest")
        monitoring.register_callback(tool, monitoring.events.RAISE, self._on_raise)
        monitoring.set_events(tool, monitoring.events.RAISE)

    def _on_raise(self, code: CodeType, offset: int, exception: BaseException) -> None:
        if code.co_filename in self._watched:
            self._raised.add((type(exception).__name__, _ADDRESS.sub("0x", str(exception))[:300]))

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, pytest.TestReport, pytest.TestReport]:
        report = yield
        outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
        self._tests.setdefault(report.nodeid, []).append(f"{report.when}:{outcome}")
        if report.failed and call.excinfo is not None:
            message = (call.excinfo.exconly().splitlines() or [""])[0]
            self._failures.append(
                {"wezel": report.nodeid, "faza": str(report.when), "wyjatek": call.excinfo.typename, "miejsce": _place(item, call.excinfo), "komunikat": message[:200]}
            )
        return report

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        found = {"testy": self._tests, "padniecia": self._failures, "wyjatki": sorted(self._raised)}
        self._output.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")


def _place(item: pytest.Item, excinfo: pytest.ExceptionInfo[BaseException]) -> str:
    """Najgłębsza ramka wyjątku w pliku pod ``TESTS`` jako ``plik:linia`` względem korzenia pytest; bez takiej ramki pusty."""

    root = item.config.rootpath.resolve()
    found = ""
    for entry in excinfo.traceback:
        path = Path(entry.path).resolve()
        if path.is_relative_to(root) and (relative := path.relative_to(root).as_posix()).startswith(TESTS):
            found = f"{relative}:{entry.lineno + 1}"
    return found
