"""Zegar Centrum u taty (``SYSTEM_CLOCK``), wątki w tle, na które zamknięcie Centrum nie czeka, i zegar ścienny
(``rozliczenia.wall_clock``) w strefie komputera.

Testy Centrum podstawiają ``ManualClock``, więc prawdziwy budzik i wątek sprawdzenia klucza sprawdza tylko ten plik.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
import time

import pytest

from rozliczenia.centrum.clock import SYSTEM_CLOCK
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.wall_clock import dad_today, local_now, utc_now

ROOT = Path(__file__).resolve().parents[1]

# Budzik za godzinę i sprawdzenie klucza w Skrzynce, która nie odpowiada; potem koniec programu. Moduł ``KeyedBox``
# z importu tego pliku: mutacje zmiany (``tools/mutacje_zmiany.py``) wybierają testy pliku po grafie importów.
EXIT_WITH_BACKGROUND_THREADS = f"""
import threading

from rozliczenia.centrum.clock import SYSTEM_CLOCK
from {KeyedBox.__module__} import KeyedBox


class SilentBox:
    def labelled_issues(self, label, *, include_closed, key):
        threading.Event().wait()


SYSTEM_CLOCK.after(3600, print)
KeyedBox(SilentBox(), lambda: "github_pat_SYNTETYCZNY", clock=SYSTEM_CLOCK).check_in_background()
"""


def test_budzik_zegara_systemu_budzi_w_innym_watku() -> None:
    woken = threading.Event()
    threads: list[threading.Thread] = []

    def wake() -> None:
        threads.append(threading.current_thread())
        woken.set()

    SYSTEM_CLOCK.after(0, wake)

    assert woken.wait(10), "budzik nie zadzwonił"
    assert threads != [threading.current_thread()]


def test_zamkniecie_centrum_nie_czeka_na_budzik_ani_na_skrzynke_bez_odpowiedzi() -> None:
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

    finished = subprocess.run(
        [sys.executable, "-c", EXIT_WITH_BACKGROUND_THREADS], env=environment, timeout=30, check=False
    )

    assert finished.returncode == 0


def test_dzien_taty_jest_dniem_strefy_komputera_a_nie_dniem_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform == "win32":
        pytest.skip("time.tzset jest tylko w systemach POSIX")
    # UTC+14 i UTC−12 dzieli 26 h, więc w każdej chwili mają inną datę, a dzień UTC byłby w obu strefach ten sam.
    seen: dict[str, tuple[date, timedelta | None, timedelta | None]] = {}
    try:
        for zone in ("Etc/GMT-14", "Etc/GMT+12"):
            monkeypatch.setenv("TZ", zone)
            time.tzset()
            seen[zone] = (dad_today(), local_now().utcoffset(), utc_now().utcoffset())
    finally:
        monkeypatch.undo()
        time.tzset()

    east, west = seen["Etc/GMT-14"], seen["Etc/GMT+12"]
    assert east[0] > west[0]
    assert (east[1], west[1]) == (timedelta(hours=14), timedelta(hours=-12))
    assert east[2] == west[2] == timedelta(0)
