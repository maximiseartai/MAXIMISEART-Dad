"""Tymczasowa sonda #1883 (do usunięcia przed przeglądem): która gałąź ``shortcut._write`` pada pod obciążeniem runnera."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time

import pytest

from rozliczenia.call_trace import exception_type
from rozliczenia.centrum import shortcut
from rozliczenia.centrum.platform import run_console_program
from rozliczenia.tool_files import TOOL_ROOT


@pytest.mark.timeout(560)
@pytest.mark.skipif(sys.platform != "win32", reason="sonda #1883 mierzy Windows")
def test_sonda_1883_zapis_skrotu_pod_obciazeniem(tmp_path: Path) -> None:
    windowless = Path(sys.executable).with_name("pythonw.exe")
    [desktop] = [item for item in shortcut.shortcuts(TOOL_ROOT) if item.folder is shortcut.Folder.DESKTOP]
    burners = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(os.cpu_count() or 4)]
    stop = threading.Event()
    neighbour_runs: list[float] = []

    def neighbour() -> None:
        while not stop.is_set():
            started = time.monotonic()
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "exit"], capture_output=True, check=False)
            neighbour_runs.append(time.monotonic() - started)

    def one(worker: int, round_: int) -> tuple[float, str]:
        folder = tmp_path / f"w{worker}-r{round_}"
        folder.mkdir()
        started = time.monotonic()
        try:
            shortcut._write(desktop, windowless, folder, run_console_program)
            outcome = "ok"
        except OSError as error:
            cause = error.__cause__
            outcome = f"{exception_type(error)}: {error} (przyczyna {exception_type(cause) if cause else '-'}: {cause})"
        return time.monotonic() - started, outcome

    neighbours = [threading.Thread(target=neighbour, daemon=True) for _ in range(4)]
    try:
        for thread in neighbours:
            thread.start()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda item: one(*item), [(worker, round_) for round_ in range(10) for worker in range(4)]))
    finally:
        stop.set()
        for thread in neighbours:
            thread.join(timeout=60)
        for burner in burners:
            burner.kill()
            burner.wait()
    times = sorted(seconds for seconds, _ in results)
    failed = [f"{seconds:.1f} s {outcome}" for seconds, outcome in results if outcome != "ok"]
    p90 = times[int(len(times) * 0.9) - 1]
    pytest.fail(
        f"SONDA 1883 obciążenie: {len(burners)} procesów na rdzeniach, 4 wątki PowerShella sąsiadów "
        f"({len(neighbour_runs)} startów, mediana {statistics.median(neighbour_runs or [0]):.1f} s, max {max(neighbour_runs or [0]):.1f} s)\n"
        f"zapis skrótu {len(times)}×: min {times[0]:.1f} s, mediana {statistics.median(times):.1f} s, p90 {p90:.1f} s, "
        f"max {times[-1]:.1f} s (limit {shortcut._POWERSHELL_TIMEOUT_S:.0f} s)\nporażki {len(failed)}/{len(results)}: {failed}"
    )
