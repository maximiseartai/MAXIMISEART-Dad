"""Test, który przekroczy limit pytest-timeout w workerze xdist, zostawia w logu swój limit, swoje id i stosy wątków.

Na Windows pytest-timeout ma tylko metodę ``thread``: po limicie drukuje stosy na terminal pytest i kończy proces przez
``os._exit``. Terminal workera xdist nie trafia do logu, więc po teście, który przekroczył limit, log ma tylko
``[gw0] node down: Not properly terminated`` i ``worker 'gw0' crashed while running '<test>'``, jak po procesie
zabitym z zewnątrz (#1685). W workerze xdist z metodą ``thread`` ten plugin zastępuje timer pytest-timeout takim samym
timerem, który przed ``os._exit`` pisze na stderr workera linię ``LIMIT TESTU`` i stosy wątków, a stderr workera
trafia do logu kontrolera. Metoda ``signal`` (Linux, macOS) kończy sam test błędem ``Timeout``, a pytest bez xdist ma
terminal w logu, więc tam limit mierzy pytest-timeout.

Linia ``LIMIT TESTU`` nie jest linią ``+++ Timeout +++`` pytest-timeout, więc ``ZAWIESZENIE`` silnika mutacji
(``tools/lib/silnik_mutacji.py``) dalej nie widzi workera xdist zabitego metodą ``thread``.

``tests/conftest.py`` wczytuje ten moduł jako plugin.
"""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
from typing import Protocol

import pytest

from tests.fixtures.linie_watkow import PYTEST_TIMEOUT_THREAD

LIMIT_TESTU = "LIMIT TESTU | {limit:g} s pytest-timeout: {test}; worker xdist kończy się, a xdist zgłosi test jako „crashed”"
_TIMER = pytest.StashKey[threading.Timer]()


class _Ustawienia(Protocol):
    """Pola ``Settings`` pytest-timeout, który nie ma typów."""

    method: str
    timeout: float


@pytest.hookimpl(tryfirst=True)
def pytest_timeout_set_timer(item: pytest.Item, settings: _Ustawienia) -> bool | None:
    if settings.method != "thread" or not hasattr(item.config, "workerinput"):
        return None
    timer = threading.Timer(settings.timeout, _przekroczony, (item, settings.timeout))
    # Ta sama nazwa co timer pytest-timeout: linie wątków testu go nie liczą.
    timer.name = f"{PYTEST_TIMEOUT_THREAD}{item.nodeid}"
    item.stash[_TIMER] = timer
    timer.start()
    return True


@pytest.hookimpl(tryfirst=True)
def pytest_timeout_cancel_timer(item: pytest.Item) -> bool | None:
    timer = item.stash.get(_TIMER, None)
    if timer is None:
        return None
    timer.cancel()
    timer.join()
    del item.stash[_TIMER]
    return True


def _przekroczony(item: pytest.Item, limit: float) -> None:
    try:
        capture = item.config.pluginmanager.getplugin("capturemanager")
        if capture is not None:
            capture.suspend_global_capture(item)  # stderr workera zamiast przechwyconego wyjścia testu
        sys.stderr.write(f"\n{LIMIT_TESTU.format(limit=limit, test=item.nodeid)}\n")
        sys.stderr.flush()
        faulthandler.dump_traceback(file=sys.stderr)
    finally:
        os._exit(1)
