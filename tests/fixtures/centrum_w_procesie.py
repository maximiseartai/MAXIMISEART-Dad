"""Centrum rozliczeń w osobnym procesie na plikach Centrum testu, które test gasi nagle, jak brak prądu u taty.

``centrum_process`` uruchamia w procesie potomnym aplikację ``settling_app`` (te same Ustawienia taty, Logi, dzienniki i
metryki co ``settling_centrum`` testu) z oknem efenix na Atrapie efenix, przez prawdziwy serwer HTTP na wolnym porcie.
``kill`` zabija proces Centrum razem z jego potomkami (przeglądarka okna efenix) bez sprzątania: ``potomne.run`` ze
``stop`` zabija drzewo procesów (POSIX: SIGKILL grupy, Windows: Job Object), więc Centrum nie dokańcza niczego, co było w
toku, i niczego nie zapisuje przy zamknięciu.

Z ``after_result`` Uruchomienie tego Centrum staje po wyniku (rekord metryk, czyli wiersz Historii, jest już na dysku), a
przed działaniami po wyniku (``RunHost.after``: Logi Uruchomienia i ich wysyłka): zostawia plik ``after_result`` i czeka,
więc test zabija Centrum dokładnie w tej chwili.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

import uvicorn

from rozliczenia.centrum.runs import EndedRun, RunHost

from tests.fixtures.centrum_processes import Surroundings, settling_app
from tests.fixtures.potomne import potomne, wait_for
from tests.fixtures.tool_clone import free_port

ROOT = Path(__file__).resolve().parents[2]
_STARTUP_S = 60.0
_STALLED_S = 600.0


@dataclass
class CentrumProcess:
    """Centrum w procesie potomnym pod adresem ``address``; ``output`` to jego wyjście po zakończeniu."""

    address: str
    _stop: threading.Event
    _thread: threading.Thread
    _ended: list[subprocess.CompletedProcess[str] | None] = field(default_factory=list)

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Przycisk taty w karcie Centrum: zapytanie API z nagłówkiem ``Origin`` karty; status i odpowiedź."""

        request = urllib.request.Request(
            f"{self.address}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": self.address},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as refused:
            return refused.code, json.load(refused)

    def answers(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.address}/api/health", timeout=1) as response:
                return bool(response.status == 200)
        except OSError:
            return False

    def kill(self) -> None:
        """Centrum gaśnie nagle razem z oknem efenix; wraca, gdy drzewo procesów już nie żyje."""

        self._stop.set()
        self._thread.join()

    @property
    def output(self) -> str:
        ended = self._ended[0] if self._ended else None
        return "" if ended is None else ended.stdout + ended.stderr


@contextmanager
def centrum_process(tmp_path: Path, efenix_url: str, *, after_result: Path | None = None) -> Iterator[CentrumProcess]:
    """Centrum na plikach ``settling_centrum`` z ``tmp_path`` i oknem efenix pod ``efenix_url``, odpowiadające na zapytania;
    z ``after_result`` Uruchomienie staje po wyniku, przed działaniami po wyniku (docstring modułu).

    Po bloku proces nie żyje, także gdy test go nie zabił.
    """

    port = free_port()
    command = [sys.executable, "-m", "tests.fixtures.centrum_w_procesie", str(tmp_path), efenix_url, str(port)]
    if after_result is not None:
        command.append(str(after_result))
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    stop = threading.Event()
    ended: list[subprocess.CompletedProcess[str] | None] = []

    def run() -> None:
        try:
            ended.append(potomne.run(command, cwd=ROOT, env=environment, timeout=600, stop=stop))
        except potomne.Stopped:
            ended.append(None)

    thread = threading.Thread(target=run, name="centrum-w-procesie")
    thread.start()
    process = CentrumProcess(f"http://127.0.0.1:{port}", stop, thread, ended)
    try:
        if not wait_for(lambda: process.answers() or not thread.is_alive(), _STARTUP_S) or not thread.is_alive():
            raise AssertionError(f"Centrum w procesie nie odpowiada: {process.output}")
        yield process
    finally:
        process.kill()


def _stall_after_result(marker: Path) -> None:
    """Działania po wyniku każdego Uruchomienia czekają, aż test zabije Centrum, a przed tym zostawiają plik ``marker``."""

    def stalled(self: RunHost, run: EndedRun) -> None:
        marker.write_text(run.info.id, encoding="utf-8")
        time.sleep(_STALLED_S)

    RunHost.after = stalled  # type: ignore[method-assign]


def _main(tmp_path: Path, efenix_url: str, port: int, after_result: Path | None) -> int:
    if after_result is not None:
        _stall_after_result(after_result)
    app = settling_app(tmp_path, Surroundings(efenix_url=efenix_url))
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), Path(sys.argv[4]) if sys.argv[4:] else None))
