"""Centrum rozliczeń w testach z syntetycznym INTERMAX we wskazanym Rejestrze zleceń i zegarem procesu.

``restart()`` to nowa aplikacja Centrum na tych samych plikach i Ustawieniach taty, jak po zamknięciu i ponownym
otwarciu Centrum na komputerze taty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from rozliczenia import intermax_copies

from tests.fixtures.centrum import (
    QUEUE_THREAD,
    CentrumClient,
    FakePlatform,
    ToolDirectory,
    centrum_app,
    finished_view,
    join_threads_since,
)
from tests.fixtures.centrum_processes import Engines, Surroundings
from tests.fixtures.intermax import Intermax, Layout
from tests.fixtures.intermax_disk import FaultyDisk

REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021-NOWA WERSJA.xlsx"
# Poniedziałek, w który tata porządkuje wklejone zlecenia dnia z domyślnego syntetycznego INTERMAX.
NOW = datetime(2026, 10, 26, 14, 5, 7)
PERIOD = "20_26_10_2026"


@dataclass
class Clock:
    """Zegar procesu Uporządkowania INTERMAX: każde pytanie bierze następną chwilę, ostatnia zostaje."""

    moments: list[datetime] = field(default_factory=lambda: [NOW])

    def __call__(self) -> datetime:
        return self.moments.pop(0) if len(self.moments) > 1 else self.moments[0]


@dataclass
class OrderingCentrum:
    client: CentrumClient
    register: Path
    layout: Layout
    copies: Path
    tmp_path: Path
    surroundings: Surroundings
    engines: Engines
    clock: Clock
    tool_copies: bool = False
    disk: FaultyDisk = field(default_factory=FaultyDisk)
    """Usterki kroków podmiany INTERMAX dla Uporządkowania i przywrócenia Kopii; test wkłada je w każdej chwili."""

    @property
    def tool(self) -> ToolDirectory:
        return ToolDirectory(self.tmp_path)

    @property
    def log_path(self) -> Path:
        return self.tool.log_path

    @property
    def metrics_path(self) -> Path:
        return self.engines.metrics.intermax

    def start(self) -> Any:
        return self.client.post("/api/intermax/run")

    def run_to_end(self) -> dict[str, Any]:
        started = self.start()
        assert started.status_code == 200, started.json()
        return finished_view(self.client)

    def setup(self) -> dict[str, Any]:
        response = self.client.get("/api/intermax")
        assert response.status_code == 200, response.json()
        return dict(response.json())

    def metric_records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.metrics_path.read_text(encoding="utf-8").splitlines()]

    def run_logs(self) -> list[dict[str, Any]]:
        directory = self.tool.run_logs
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]

    def last_started(self) -> dict[str, Any]:
        return dict(json.loads(self.tool.last_started.read_text(encoding="utf-8")))

    def restart(self) -> None:
        """Nowe Centrum na tych samych plikach i Ustawieniach taty, gdy skończy się przejście kolejki poprzedniego.

        Powód czekania na kolejkę opisuje ``PreparingCentrum.restart``.
        """

        join_threads_since(self.client.since, named=QUEUE_THREAD)
        self.client = _client(
            self.tmp_path,
            self.surroundings,
            self.engines,
            self.clock,
            FakePlatform(),
            None if self.tool_copies else self.copies,
            self.disk,
            since=self.client.since,
        )


def _client(
    tmp_path: Path,
    surroundings: Surroundings,
    engines: Engines,
    clock: Clock,
    platform: FakePlatform,
    copies: Path | None,
    disk: FaultyDisk,
    *,
    since: int | None = None,
) -> CentrumClient:
    """Centrum na plikach ``tmp_path``; ``copies``: folder Kopii INTERMAX, ``None``: domyślny folder narzędzia."""

    onedrive = surroundings.onedrive
    app = centrum_app(
        ToolDirectory(tmp_path),
        platform=platform,
        today=clock.moments[0].date(),
        processes=engines.processes(),
        tool_freshness=surroundings.tool_freshness(),
        cloud_files=None if onedrive is None else onedrive.cloud_files(),
        report_box=surroundings.report_box,
        clock=surroundings.started_clock(),
        pause=surroundings.clock.pause,
        readers=surroundings.readers,
        intermax_copies=copies,
        intermax_disk=disk.disk(),
        now=clock,
    )
    return CentrumClient(app, since=since)


def ordering_centrum(
    tmp_path: Path,
    intermax: Intermax | None = None,
    *,
    chosen: bool = True,
    clock: Clock | None = None,
    surroundings: Surroundings | None = None,
    periods_directory: Path | None = None,
    tool_copies: bool = False,
) -> OrderingCentrum:
    """Centrum z syntetycznym INTERMAX (domyślnie z Surowymi zleceniami 26.10.2026) i własnymi metrykami.

    ``chosen``: tata wskazał INTERMAX w Ustawieniach jako Rejestr zleceń. Bez ``surroundings`` narzędzie jest
    aktualne, a każdy plik ma kopię na tym komputerze. ``periods_directory``: tata wskazał też folder okresów.
    ``tool_copies``: Centrum nie dostaje folderu Kopii INTERMAX i kładzie je w domyślnym folderze narzędzia.
    """

    register = tmp_path / "OneDrive" / REGISTER_NAME
    register.parent.mkdir(parents=True)
    layout = (intermax or Intermax()).write(register)
    surroundings, engines, clock = surroundings or Surroundings(), Engines(ToolDirectory(tmp_path).metrics), clock or Clock()
    platform = FakePlatform(chosen_files=[register], chosen_folders=[periods_directory])
    copies = intermax_copies.default_directory() if tool_copies else tmp_path / "Kopie INTERMAX"
    disk = FaultyDisk()
    client = _client(tmp_path, surroundings, engines, clock, platform, None if tool_copies else copies, disk)
    if chosen:
        assert client.post("/api/settings/register/choose").status_code == 200
    if periods_directory is not None:
        assert client.post("/api/settings/periods-directory/choose").status_code == 200
    return OrderingCentrum(client, register, layout, copies, tmp_path, surroundings, engines, clock, tool_copies, disk)


def copies(centrum: OrderingCentrum) -> list[str]:
    """Nazwy Kopii INTERMAX w folderze Kopii; bez folderu żadnych."""

    return sorted(path.name for path in centrum.copies.iterdir()) if centrum.copies.is_dir() else []


def open_in_excel(register: Path) -> Path:
    """Plik blokady Excela obok INTERMAX, jak przy pliku otwartym u taty; zwraca jego ścieżkę."""

    lock = register.with_name(f"~${register.name}")
    lock.write_bytes(b"\x00" * 165)
    return lock
