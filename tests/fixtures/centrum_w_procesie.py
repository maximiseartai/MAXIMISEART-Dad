"""Centrum rozliczeń w osobnym procesie na plikach Centrum testu, które test gasi nagle, jak brak prądu u taty.

``centrum_process`` uruchamia w procesie potomnym aplikację ``settling_app`` (te same Ustawienia taty, Logi, dzienniki i
metryki co ``settling_centrum`` testu) z oknem efenix na Atrapie efenix, przez prawdziwy serwer HTTP na porcie, który proces
Centrum sam bierze od systemu i trzyma od tej chwili, a dopiero potem podaje testowi (#1917, #1918). Port wybrany przez test
i zwolniony przed startem Centrum mógł w tym czasie wziąć serwer sąsiedniego workera pytest, np. Atrapa efenix eksploratora:
Centrum nie startowało („address already in use”), a pytanie testu o ``/api/health`` trafiało w tę Atrapę jako żądanie
okna spoza listy dozwolonych.
``kill`` zabija proces Centrum razem z jego potomkami (przeglądarka okna efenix) bez sprzątania: ``potomne.run`` ze
``stop`` zabija drzewo procesów (POSIX: SIGKILL grupy, Windows: Job Object), więc Centrum nie dokańcza niczego, co było w
toku, i niczego nie zapisuje przy zamknięciu.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from typing import Any
import urllib.error
import urllib.request

import uvicorn

from tests.fixtures.centrum_processes import Surroundings, settling_app
from tests.fixtures.potomne import wait_for
import potomne

ROOT = Path(__file__).resolve().parents[2]
_STARTUP_S = 60.0


@dataclass
class CentrumProcess:
    """Centrum w procesie potomnym, które podaje swój port w pliku ``_port_file``; ``output`` to jego wyjście po zakończeniu."""

    _port_file: Path
    _stop: threading.Event
    _thread: threading.Thread
    _ended: list[subprocess.CompletedProcess[str] | None] = field(default_factory=list)

    @property
    def address(self) -> str:
        """Adres Centrum; jest dopiero, gdy proces Centrum trzyma już swój port."""

        return f"http://127.0.0.1:{self._port_file.read_text(encoding='ascii')}"

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
        if not self._port_file.exists():
            return False
        try:
            with urllib.request.urlopen(f"{self.address}/api/health", timeout=1) as response:
                return bool(response.status == 200)
        except OSError:
            return False

    def kill(self) -> None:
        """Centrum gaśnie nagle razem z oknem efenix: ``kill`` wraca, gdy wróci ``potomne.run`` ze ``stop``. Na POSIX grupa
        lidera dostaje SIGKILL, a ``kill`` czeka tylko na lidera, więc procesy spoza tej grupy, w tym przeglądarka okna
        efenix, kończą się same i mogą jeszcze żyć po powrocie."""

        self._stop.set()
        self._thread.join()

    @property
    def output(self) -> str:
        ended = self._ended[0] if self._ended else None
        return "" if ended is None else ended.stdout + ended.stderr


@contextmanager
def centrum_process(tmp_path: Path, efenix_url: str) -> Iterator[CentrumProcess]:
    """Centrum na plikach ``settling_centrum`` z ``tmp_path`` i oknem efenix pod ``efenix_url``, odpowiadające na zapytania.

    Po bloku proces nie żyje, także gdy test go nie zabił.
    """

    with tempfile.TemporaryDirectory(prefix="centrum-port-") as ports:
        port_file = Path(ports) / "port"
        command = [sys.executable, "-m", "tests.fixtures.centrum_w_procesie", str(tmp_path), efenix_url, str(port_file)]
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tools" / "lib")])}
        stop = threading.Event()
        ended: list[subprocess.CompletedProcess[str] | None] = []

        def run() -> None:
            try:
                ended.append(potomne.run(command, cwd=ROOT, env=environment, timeout=600, stop=stop))
            except potomne.Stopped:
                ended.append(None)

        thread = threading.Thread(target=run, name="centrum-w-procesie")
        thread.start()
        process = CentrumProcess(port_file, stop, thread, ended)
        try:
            if not wait_for(lambda: process.answers() or not thread.is_alive(), _STARTUP_S) or not thread.is_alive():
                raise AssertionError(f"Centrum w procesie nie odpowiada: {process.output}")
            yield process
        finally:
            process.kill()


def _main(tmp_path: Path, efenix_url: str, port_file: Path) -> int:
    """Centrum słucha na porcie od systemu, zanim poda go w ``port_file``, więc test pyta tylko port, który Centrum trzyma;
    zapytanie przed startem serwera czeka w kolejce gniazda."""

    app = settling_app(tmp_path, Surroundings(efenix_url=efenix_url))
    listening = socket.create_server(("127.0.0.1", 0))
    written = port_file.with_name(f"{port_file.name}.zapis")
    written.write_text(str(listening.getsockname()[1]), encoding="ascii")
    written.replace(port_file)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listening])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])))
