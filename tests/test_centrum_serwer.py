"""Serwer Centrum rozliczeń: ``start`` i ``stop`` w dzienniku, póki Centrum trzyma port, i port, który zamknięte Centrum
zwalnia od razu, także gdy jego kolejka Skrzynki Zgłoszeń jeszcze wysyła, oraz zatrzymanie Centrum w teście, które
czeka na koniec każdego jego wątku."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI
import pytest

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.launcher import listen_locally
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import PeriodThread, Post
from rozliczenia.centrum.server import serve
from rozliczenia.centrum.shutdown import Shutdown

from tests.fixtures.centrum import (
    FakeGitHub,
    FakeOneDrive,
    FakePlatform,
    FakeReportBox,
    MetricsPaths,
    join_threads_since,
    new_line,
)
from tests.fixtures.clock import ManualClock

KONTROLA = Post.of(
    PeriodThread(
        "kontrola-ilosci", "- Kontrola ilości okresu: 08_14_09_2026", "new_issue", "Kontrola ilości 08_14_09_2026"
    ),
    period="08_14_09_2026",
    run_id="3f2a9c1b8e7d4f0a9b1c2d3e4f5a6b7c",
    blocks=["różnice\n"],
    frame=lambda _number, _count, text: text,
)
QUEUED = "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json"


def _port_free(port: int) -> bool:
    """Czy nowe Centrum mogłoby teraz zająć ``port``."""

    try:
        listen_locally(port).close()
    except OSError:
        return False
    return True


class _PortAtStop(CentrumLog):
    """Dziennik, który przy ``stop`` sprawdza, czy nowe Centrum mogłoby już zająć port."""

    port_free_at_stop: bool | None = None

    def stopped(self, *, port: int) -> None:
        self.port_free_at_stop = _port_free(port)
        super().stopped(port=port)


def _events(path: Path) -> list[str]:
    return [line.split(" ")[1] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _centrum(tmp_path: Path, box: FakeReportBox, log: CentrumLog, clock: ManualClock) -> tuple[FastAPI, Shutdown]:
    """Centrum z kluczem do Zgłoszeń, w którego kolejce czeka Kontrola ilości z poprzedniej pracy Centrum."""

    config = tmp_path / "config"
    (config / "zgloszenia" / "kolejka").mkdir(parents=True)
    (config / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY_KLUCZ\n", encoding="utf-8")
    (config / "zgloszenia" / "kolejka" / QUEUED).write_text(KONTROLA.to_json(), encoding="utf-8")
    shutdown = Shutdown(log)
    metrics = MetricsPaths(
        preparation=tmp_path / "przygotowanie-metrics.jsonl",
        settlement=tmp_path / "metrics.jsonl",
        intermax=tmp_path / "intermax-metrics.jsonl",
    )
    app = create_app(
        settings_path=config / "centrum-ustawienia.yaml",
        platform=FakePlatform(),
        log=log,
        shutdown=shutdown,
        processes=metrics.processes(),
        tool_freshness=FakeGitHub().freshness(),
        cloud_files=FakeOneDrive().cloud_files(),
        report_box=box,
        clock=clock,
        pause=clock.pause,
    )
    return app, shutdown


def _serving(app: FastAPI, shutdown: Shutdown, log: CentrumLog) -> tuple[threading.Thread, int]:
    """``serve`` na wolnym porcie w osobnym wątku, do zamknięcia przez ``shutdown``, i ten port."""

    listener = listen_locally(0)
    kwargs = {"listener": listener, "on_ready": lambda _url: None, "shutdown": shutdown, "log": log}
    thread = threading.Thread(target=serve, args=(app,), kwargs=kwargs, name="centrum-test", daemon=True)
    thread.start()
    return thread, int(listener.getsockname()[1])


def test_zamkniecie_po_starcie_zapisuje_stop_zanim_port_jest_wolny(tmp_path: Path) -> None:
    path = tmp_path / "centrum-rozliczen.log"
    log = _PortAtStop(path)
    shutdown = Shutdown(log)

    code = serve(FastAPI(), listener=listen_locally(0), on_ready=lambda _url: shutdown.request(), shutdown=shutdown, log=log)

    assert code == 0
    assert _events(path) == ["start", "zamkniecie", "stop"]
    assert log.port_free_at_stop is False


def test_nieudany_start_nie_zapisuje_ani_startu_ani_stopu(tmp_path: Path) -> None:
    @asynccontextmanager
    async def failing(_app: FastAPI) -> AsyncIterator[None]:
        raise RuntimeError("start się nie udał")
        yield

    path = tmp_path / "centrum-rozliczen.log"
    log = _PortAtStop(path)
    listener = listen_locally(0)
    port = listener.getsockname()[1]

    with pytest.raises(SystemExit):
        serve(FastAPI(lifespan=failing), listener=listener, on_ready=lambda _url: None, shutdown=Shutdown(log), log=log)

    assert _events(path) == []
    listen_locally(port).close()


def test_zamkniete_centrum_zwalnia_port_od_razu_takze_gdy_kolejka_czeka_na_skrzynke(tmp_path: Path) -> None:
    # Skrót i opiekun ponownego startu startują nowe Centrum, gdy tylko port jest wolny, a zapytanie do Skrzynki nie ma
    # górnego limitu (wolna sieć): port trzymany do końca wysyłki dałby tacie kartę Centrum, które zaraz zniknie.
    hold = threading.Event()
    box = FakeReportBox(open_hold=hold)
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    app, shutdown = _centrum(tmp_path, box, log, ManualClock())
    since = new_line()
    served, port = _serving(app, shutdown, log)

    try:
        assert box.opening.wait(30), "kolejka nie zaczęła wysyłki z poprzedniej pracy Centrum"
        shutdown.request()
        served.join(30)
        closed = not served.is_alive()
        port_free = _port_free(port)
    finally:
        hold.set()
        join_threads_since(since)

    assert closed, "Centrum czekało z zamknięciem na wysyłkę kolejki"
    assert port_free


class _EndingThread(threading.Thread):
    """Wątek, którego kod już się skończył (zniknął z ``threading.enumerate()``), a wątek systemu jeszcze żyje.

    Tak kończy się każdy wątek: ``Thread._delete`` zdejmuje go z ``enumerate()``, zanim skończy się wątek systemu, a
    ``is_alive()`` do tej chwili zwraca True; tu ta chwila trwa, dopóki test nie ustawi ``end``.
    """

    def __init__(self) -> None:
        super().__init__(name="konczacy-sie", daemon=True)
        self.code_ended = threading.Event()
        self.end = threading.Event()

    def _delete(self) -> None:
        super()._delete()  # type: ignore[misc]
        self.code_ended.set()
        self.end.wait()


def test_zatrzymanie_centrum_w_tescie_czeka_na_koniec_watku_systemu_a_nie_tylko_jego_kodu() -> None:
    # #862: ``stop`` uznał Centrum za zatrzymane, gdy ``skrzynka-klucz`` zniknął już z ``enumerate()``, a jeszcze żył.
    since = new_line()
    ending = _EndingThread()
    ending.start()
    assert ending.code_ended.wait(30), "wątek nie doszedł do końca swojego kodu"

    with pytest.raises(AssertionError, match="żyją wątki konczacy-sie"):
        join_threads_since(since, timeout_s=0)
    ending.end.set()
    join_threads_since(since)

    assert not ending.is_alive()
