"""Plugin pytest dla ``tools/mutacje_zmiany.py``: które testy wykonują zmienione linie i pliki.

``tools/mutacje_zmiany.py`` uruchamia testy z ``-p pytest_pokrycie``, ze zmienną ``POKRYCIE_LINII`` i z
``sitecustomize`` (``pokrycie_procesu.SITECUSTOMIZE``) na ``PYTHONPATH``. Zapis prowadzi ``tools/ci/pokrycie_procesu.py``.
Plugin mówi mu, który test trwa i czy trwa fixture o zasięgu szerszym niż test, a w czasie testu wystawia jego nodeid
w ``POKRYCIE_LINII_TEST``, żeby procesy Pythona uruchomione przez test zapisały się pod nim. Każdy proces pytest, także
worker xdist, zapisuje swój plik na końcu sesji, przed ``workerfinished``: po nim kontroler zamyka workera, a execnet
przerywa mu główny wątek po 5 s, więc zapis w ``pytest_unconfigure`` przepadał na wolnym runnerze (#788).
"""

from __future__ import annotations

from collections.abc import Generator
import os

import pytest

import pokrycie_procesu


def pytest_configure(config: pytest.Config) -> None:
    pokrycie_procesu.recorder()


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    pokrycie_procesu.recorder().test = nodeid
    os.environ[pokrycie_procesu.TEST] = nodeid


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest) -> Generator[None, object, object]:
    """Kod fixture o zasięgu szerszym niż test (moduł, sesja) wykonuje jeden test, a wynik dostają też inne."""

    recorder = pokrycie_procesu.recorder()
    if fixturedef.scope == "function":
        return (yield)
    recorder.shared_depth += 1
    try:
        return (yield)
    finally:
        recorder.shared_depth -= 1


def pytest_runtest_logfinish(nodeid: str, location: tuple[str, int | None, str]) -> None:
    pokrycie_procesu.recorder().test = None
    os.environ.pop(pokrycie_procesu.TEST, None)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    pokrycie_procesu.write()
