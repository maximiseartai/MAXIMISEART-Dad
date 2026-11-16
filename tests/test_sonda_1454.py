"""SONDA TYMCZASOWA #1454, do usunięcia przed oddaniem PR: zawsze pada, żeby log CI pokazał wynik."""

from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from tests.fixtures.tool_clone import free_port
from tests.test_przerwana_aktualizacja_narzedzia import (
    test_skrot_z_autostartu_po_cofnieciu_przerwanej_aktualizacji_startuje_centrum_dalej_bez_karty as scenariusz,
)

POWTORZENIA = 8


@pytest.mark.parametrize("timeout", [1.0, 5.0])
def test_sonda_polaczenia_z_portem_bez_nasluchu(timeout: float) -> None:
    lines = []
    if True:
        for _ in range(3):
            port = free_port()
            start = time.monotonic()
            try:
                socket.create_connection(("127.0.0.1", port), timeout=timeout).close()
                outcome = "połączono?!"
            except OSError as failure:
                outcome = f"{type(failure).__name__}: {failure}"
            lines.append(f"timeout={timeout}: {time.monotonic() - start:.2f} s, {outcome}")
    pytest.fail("SONDA POŁĄCZENIA\n" + "\n".join(lines))


@pytest.mark.timeout(1200)
@pytest.mark.parametrize("obciazenie", [0, 0, 1, 1], ids=["bez-0", "bez-1", "obc-0", "obc-1"])
def test_sonda_skrotu(tmp_path: Path, obciazenie: int) -> None:
    busy = [
        subprocess.Popen([sys.executable, "-c", "import time\nend=time.monotonic()+1100\nwhile time.monotonic()<end: pass"])
        for _ in range(obciazenie)
    ]
    results = []
    try:
        for n in range(POWTORZENIA):
            start = time.monotonic()
            with pytest.MonkeyPatch.context() as monkeypatch:
                try:
                    scenariusz(tmp_path / str(n), monkeypatch)
                    outcome = "OK"
                except (AssertionError, OSError, subprocess.SubprocessError) as failure:
                    notes = "\n".join(getattr(failure, "__notes__", []))
                    outcome = f"PADŁ {type(failure).__name__}: {failure}\n{notes}"
            results.append(f"[{n}] {time.monotonic() - start:.1f} s {outcome}")
    finally:
        for process in busy:
            process.kill()
            process.wait()
    pytest.fail("SONDA SKRÓTU\n" + "\n".join(results))
