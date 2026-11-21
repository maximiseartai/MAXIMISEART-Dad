from __future__ import annotations

from datetime import datetime, timezone
import time

import pytest

from tests.fixtures.zegar_scienny import MOMENTS, STEP, wall_clock_from
from rozliczenia import wall_clock

START = datetime(2026, 9, 16, 12, 7, tzinfo=timezone.utc)


def test_zegar_testu_rosnie_o_krok_na_pytanie_a_pytanie_ponad_limit_pada(monkeypatch: pytest.MonkeyPatch) -> None:
    wall_clock_from(monkeypatch, START)
    readings: list[datetime] = []

    def read_past_limit() -> None:
        for _ in range(MOMENTS + 1):
            readings.append(wall_clock.utc_now())

    with pytest.raises(AssertionError, match=f"więcej niż {MOMENTS} razy"):
        read_past_limit()

    first = readings[0]
    assert (readings == [first + step * STEP for step in range(len(readings))], readings[-1]) == (True, START + (MOMENTS - 1) * STEP)


def test_zegar_testu_pada_gdy_wall_clock_czyta_zegar_systemu_przypisanym_wywolywalnym(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wall_clock, "epoch_s", time.time)

    with pytest.raises(AssertionError, match="epoch_s: "):
        wall_clock_from(monkeypatch, START)
