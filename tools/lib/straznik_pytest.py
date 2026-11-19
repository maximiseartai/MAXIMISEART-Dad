"""Plugin pytest dowodu strażnika ``pytest <węzeł>`` (``straznik``, ADR 0042): jak przeszła albo padła każda faza
testów węzła i jakie rodzaje wyjątków przeszły przez kod plików przeszczepu.

Dowód ładuje plugin z pliku kodu bazy (``straznik._BOOTSTRAP``), nie z drzewa PR, i podaje go ``pytest.main`` jako
obiekt ``Plugin``: drzewo PR, które ma własny plik o tej nazwie, wyniku nie zmienia. Plugin niczego nie ocenia, tylko
zapisuje, a biegi porównuje ``straznik``.

Wynik w pliku ``output`` (JSON):

- ``testy``: id węzła → lista ``faza:wynik`` (``passed``, ``failed``, ``skipped`` albo ``xfail``);
- ``padniecia``: każda faza z wynikiem ``failed``: id węzła, faza, rodzaj wyjątku, miejsce (najgłębsza ramka w pliku pod
  ``tests/``, ``plik:linia`` względem korzenia) i pierwsza linia komunikatu;
- ``wyjatki``: rodzaj wyjątku → pierwszy komunikat (do linii dowodu) dla każdego wyjątku, który przeszedł przez ramkę
  kodu pliku z ``watched`` w procesie pytest (``sys.monitoring``, zdarzenie ``RAISE``: wyjątek zgłoszony w tej ramce albo
  w kodzie, który ona wołała, także gdy kod niżej go łapie). Wyjątku w procesie potomnym i wyjątku, który nie przechodzi
  przez ramkę takiego pliku (np. zgłoszony i złapany w module, który tylko czyta wynik przeszczepu), plugin nie widzi.
"""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
import sys
from types import CodeType

import pytest

TESTS = "tests/"  # katalog, w którym leży miejsce padnięcia: test albo jego fikstura
_FREE_TOOLS = (3, 4)  # identyfikatory sys.monitoring bez roli w Pythonie (debugger 0, pokrycie 1, profiler 2, optymalizator 5)


class Plugin:
    """Plugin jednego biegu pytest: pliki ``watched`` (ścieżki bezwzględne) i plik wyniku ``output``."""

    def __init__(self, watched: list[str], output: str) -> None:
        self._watched = frozenset(watched)
        self._output = Path(output)
        self._tests: dict[str, list[str]] = {}
        self._failures: list[dict[str, str]] = []
        self._raised: dict[str, str] = {}

    def pytest_configure(self, config: pytest.Config) -> None:
        monitoring = sys.monitoring
        tool = next(one for one in _FREE_TOOLS if monitoring.get_tool(one) is None)
        monitoring.use_tool_id(tool, "straznik_pytest")
        monitoring.register_callback(tool, monitoring.events.RAISE, self._on_raise)
        monitoring.set_events(tool, monitoring.events.RAISE)

    def _on_raise(self, code: CodeType, offset: int, exception: BaseException) -> None:
        if code.co_filename in self._watched:
            self._raised.setdefault(type(exception).__name__, str(exception)[:200])

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
        found = {"testy": self._tests, "padniecia": self._failures, "wyjatki": self._raised}
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
