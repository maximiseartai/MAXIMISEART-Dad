"""Tymczasowa sonda #1883 (do usunięcia przed przeglądem): która gałąź ``shortcut._write`` pada pod obciążeniem."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time

import pytest

from rozliczenia.centrum import shortcut
from rozliczenia.centrum.platform import run_console_program
from rozliczenia.tool_files import TOOL_ROOT


@pytest.mark.timeout(560)
@pytest.mark.skipif(sys.platform != "win32", reason="sonda #1883 mierzy Windows")
def test_sonda_1883_zapis_skrotu_pod_obciazeniem(tmp_path: Path) -> None:
    windowless = Path(sys.executable).with_name("pythonw.exe")
    [desktop] = [item for item in shortcut.shortcuts(TOOL_ROOT) if item.folder is shortcut.Folder.DESKTOP]

    def one(worker: int, round_: int) -> str:
        folder = tmp_path / f"w{worker}-r{round_}"
        folder.mkdir()
        started = time.monotonic()
        try:
            shortcut._write(desktop, windowless, folder, run_console_program)
            outcome = "ok"
        except OSError as error:
            cause = error.__cause__ or error.__context__
            outcome = f"OSError {type(error).__name__}: {error} (przyczyna {type(cause).__name__ if cause else '-'}: {cause})"
        return f"w{worker} r{round_}: {time.monotonic() - started:.1f} s {outcome}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda item: one(*item), [(worker, round_) for round_ in range(10) for worker in range(4)]))
    slow = sorted(results, key=lambda line: float(line.split(": ", 1)[1].split(" s", 1)[0]), reverse=True)[:5]
    failed = [line for line in results if "OSError" in line]
    pytest.fail(f"SONDA 1883\nporażki {len(failed)}/{len(results)}: {failed}\nnajwolniejsze: {slow}")
