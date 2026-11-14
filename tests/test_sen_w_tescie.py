"""``sleep_in_test_thread`` (``tests/fixtures/sen.py``): podmiana snu obejmuje tylko wątek testu (#1783)."""

from __future__ import annotations

import threading
import time

import pytest

from tests.fixtures.sen import sleep_in_test_thread


def test_sen_watku_sasiada_nie_trafia_do_podmiany_a_sen_watku_testu_trafia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sąsiad w procesie workera (jak budzik ``ScriptedClock`` w #1783) śpi naprawdę i nie dopisuje się do snów testu."""

    pauses: list[float] = []
    sleep_in_test_thread(monkeypatch, pauses.append)

    def neighbour() -> None:
        time.sleep(0)

    sleeper = threading.Thread(target=neighbour, name="sasiad-spiacy")
    sleeper.start()
    sleeper.join(timeout=10)
    time.sleep(5.0)

    assert (sleeper.is_alive(), pauses) == (False, [5.0])
