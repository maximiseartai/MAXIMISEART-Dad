from __future__ import annotations

import asyncio.base_events
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
import http.client
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import pytest

from atrapy.dziennik_wyceny import begun_line, journal_path, left_journal
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import QUEUE_DIRECTORY, Outbox, PeriodThread, Post
from rozliczenia.client_data import tool
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY
from rozliczenia.centrum.run_logs import StartFacts
from rozliczenia.centrum.server import serve
from rozliczenia.domain import RunMode
from rozliczenia.tool_files import HOST, listen_locally, port_free
from rozliczenia.centrum.shutdown import Shutdown

from tests.fixtures.centrum import (
    CentrumClient,
    FakeReportBox,
    ToolDirectory,
    centrum_app,
    join_threads_since,
    write_report_key,
)
from tests.fixtures.clock import ManualClock
from tests.fixtures.linie_watkow import PYTEST_TIMEOUT_THREAD, new_line, started_threads, threads_since

KONTROLA = Post.of(
    PeriodThread(
        "kontrola-ilosci", tool("- Kontrola ilości okresu: 08_14_09_2026"), "new_issue", tool("Kontrola ilości 08_14_09_2026")
    ),
    period="08_14_09_2026",
    run_id=tool("3f2a9c1b8e7d4f0a9b1c2d3e4f5a6b7c"),
    blocks=[tool("różnice\n")],
    frame=lambda _number, _count, text: text,
)
QUEUED = "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json"
ROOT = Path(__file__).resolve().parents[1]


def _centrum_could_listen(port: int) -> bool:
    try:
        listen_locally(port).close()
    except OSError:
        return False
    return True


class _PortAtStop(CentrumLog):
    port_free_at_stop: bool | None = None

    def stopped(self, *, port: int) -> None:
        self.port_free_at_stop = _centrum_could_listen(port)
        super().stopped(port=port)


def _events(path: Path) -> list[str]:
    return [line.split(" ")[1] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _centrum_with_queued_quantity_check(
    tmp_path: Path, box: FakeReportBox, log: CentrumLog, clock: ManualClock
) -> tuple[FastAPI, Shutdown]:
    tool = ToolDirectory(tmp_path)
    write_report_key(tool)
    queue = tool.config / UNSENT_DIRECTORY / QUEUE_DIRECTORY
    queue.mkdir(parents=True)
    (queue / QUEUED).write_text(KONTROLA.to_json(), encoding="utf-8")
    shutdown = Shutdown(log)
    return centrum_app(tool, log=log, shutdown=shutdown, report_box=box, clock=clock), shutdown


def _serving(app: FastAPI, shutdown: Shutdown, log: CentrumLog) -> tuple[threading.Thread, int]:
    listener = listen_locally(0)
    kwargs = {"listener": listener, "on_ready": lambda _url: None, "shutdown": shutdown, "log": log}
    thread = threading.Thread(target=serve, args=(app,), kwargs=kwargs, name="centrum-test", daemon=True)
    thread.start()
    return thread, int(listener.getsockname()[1])


def test_zamkniecie_po_starcie_zapisuje_stop_zanim_port_jest_wolny(tmp_path: Path) -> None:
    path = tmp_path / "centrum-rozliczen.log"
    log = _PortAtStop(path)
    shutdown = Shutdown(log)
    since = new_line()

    code = serve(FastAPI(), listener=listen_locally(0), on_ready=lambda _url: shutdown.request(), shutdown=shutdown, log=log)
    join_threads_since(since)

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
    shutdown = Shutdown(log)
    listener = listen_locally(0)
    port = listener.getsockname()[1]
    since = new_line()

    with pytest.raises(SystemExit):
        serve(FastAPI(lifespan=failing), listener=listener, on_ready=lambda _url: None, shutdown=shutdown, log=log)
    events = _events(path)
    shutdown.request()
    join_threads_since(since)

    assert events == []
    listen_locally(port).close()


def test_wpis_z_przygotowania_serwera_zostaje_w_dzienniku_takze_gdy_start_sie_nie_udal(tmp_path: Path) -> None:
    path = tmp_path / "centrum-rozliczen.log"
    log = CentrumLog(path)

    @asynccontextmanager
    async def failing(_app: FastAPI) -> AsyncIterator[None]:
        log.settings_release(change="2026-11-zmiana-testowa", result="pozniej")
        raise RuntimeError("start się nie udał")
        yield

    shutdown = Shutdown(log)
    since = new_line()

    with pytest.raises(SystemExit):
        serve(FastAPI(lifespan=failing), listener=listen_locally(0), on_ready=lambda _url: None, shutdown=shutdown, log=log)
    events = _events(path)
    shutdown.request()
    join_threads_since(since)

    assert events == ["ustawienia-wydanie"]


def test_wpis_z_przygotowania_serwera_czeka_na_wpis_start(tmp_path: Path) -> None:
    path = tmp_path / "centrum-rozliczen.log"
    log = CentrumLog(path)

    @asynccontextmanager
    async def preparing(_app: FastAPI) -> AsyncIterator[None]:
        log.settings_release(change="2026-11-zmiana-testowa", result="pozniej")
        yield

    shutdown = Shutdown(log)
    since = new_line()

    code = serve(FastAPI(lifespan=preparing), listener=listen_locally(0), on_ready=lambda _url: shutdown.request(), shutdown=shutdown, log=log)
    join_threads_since(since)

    assert (code, _events(path)) == (0, ["start", "ustawienia-wydanie", "zamkniecie", "stop"])


URWANA_WYCENA = StartFacts(
    run_id="627b45fe219e4274b722953c34d4af54",
    process="efenix",
    mode=RunMode.RUN,
    period="08_14_09_2026",
    started_at=datetime(2026, 9, 10, 8, 0),
)


def _left_pricing(tool: ToolDirectory) -> Path:
    return left_journal(
        tool.log_path.parent, URWANA_WYCENA, begun_line(datetime(2026, 9, 10, 8, 1), row=19, place=1, total=2)
    )


def _served_once(tool: ToolDirectory, *, before_start: Callable[[int], None] = lambda _port: None) -> tuple[int, list[str]]:
    log = CentrumLog(tool.log_path)
    shutdown = Shutdown(log)
    app = centrum_app(tool, log=log, shutdown=shutdown)
    ready = threading.Event()
    listener = listen_locally(0)
    port = int(listener.getsockname()[1])
    before_start(port)
    kwargs = {"listener": listener, "on_ready": lambda _url: ready.set(), "shutdown": shutdown, "log": log}
    since = new_line()
    served = threading.Thread(target=serve, args=(app,), kwargs=kwargs, name="centrum-test", daemon=True)
    served.start()
    try:
        assert ready.wait(30), "Centrum nie wystartowało"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        connection.request("GET", "/api/runs/current", headers={"Host": f"127.0.0.1:{port}"})
        status = connection.getresponse().status
        connection.close()
        recent = [line.split(" ", 1)[1] for line in log.recent(50)]
    finally:
        shutdown.request()
        served.join(30)
        join_threads_since(since)
    return status, recent


@pytest.mark.parametrize(
    ("queue_blocked", "sent_line"),
    [
        pytest.param(False, "skrzynka-w-kolejce etykieta=logi-uruchomienia okres=08_14_09_2026", id="kolejka-przyjela"),
        pytest.param(
            True,
            'nieoczekiwany-wyjatek typ=FileExistsError miejsce="zapis wysyłki do Skrzynki Zgłoszeń"',
            id="kolejka-nie-przyjela",
        ),
    ],
)
def test_wysylka_logow_urwanego_uruchomienia_przy_starcie_jest_we_wpisach_tej_pracy_centrum_dla_diagnozy_i_zgloszen(
    tmp_path: Path, queue_blocked: bool, sent_line: str
) -> None:
    tool = ToolDirectory(tmp_path)
    _left_pricing(tool)
    if queue_blocked:
        queue = tool.config / UNSENT_DIRECTORY / QUEUE_DIRECTORY
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_text("", encoding="utf-8")

    status, recent = _served_once(tool)

    assert status == 200
    assert recent[0].startswith("start ")
    assert recent.count(sent_line) == 1


def test_wyjatek_wysylki_logow_urwanego_uruchomienia_nie_zatrzymuje_startu_centrum_a_dziennik_wyceny_czeka(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(_outbox: Outbox, _sent: Post) -> bool:
        raise RuntimeError("nieprzewidziany błąd kolejki")

    monkeypatch.setattr(Outbox, "post", failing)
    tool = ToolDirectory(tmp_path)
    journal = _left_pricing(tool)

    status, recent = _served_once(tool)

    assert status == 200
    assert 'nieoczekiwany-wyjatek typ=RuntimeError miejsce="wysyłka wersji zastępczych przy starcie"' in recent
    assert journal == journal_path(tool.log_path.parent, URWANA_WYCENA)
    assert journal.exists()


_LINGER_FORMAT = "HH" if sys.platform == "win32" else "ii"


def _abandoned_connections(port: int) -> None:
    for reset in (True, False):
        client = socket.create_connection((HOST, port), timeout=30)
        try:
            client.sendall(f"GET /api/health HTTP/1.1\r\nHost: {HOST}:{port}\r\n\r\n".encode("ascii"))
            if reset:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack(_LINGER_FORMAT, 1, 0))
        finally:
            client.close()


def test_centrum_odpowiada_po_polaczeniach_ktore_klienci_porzucili_zanim_zaczelo_je_przyjmowac(tmp_path: Path) -> None:
    status, _recent = _served_once(ToolDirectory(tmp_path), before_start=_abandoned_connections)

    assert status == 200


def test_na_windows_centrum_na_petli_proactor_przestaje_sluchac_po_polaczeniu_porzuconym_przed_przyjeciem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform != "win32":
        pytest.skip("Pętla Proactor jest tylko na Windows.")
    monkeypatch.setattr("rozliczenia.centrum.server._LOOP_LISTENING_AFTER_FAILED_ACCEPT", asyncio.ProactorEventLoop)

    with pytest.raises(ConnectionError):
        _served_once(ToolDirectory(tmp_path), before_start=_abandoned_connections)


def test_zamkniete_centrum_zwalnia_port_od_razu_takze_gdy_kolejka_czeka_na_skrzynke(tmp_path: Path) -> None:
    hold = threading.Event()
    box = FakeReportBox(open_hold=hold)
    log = CentrumLog(ToolDirectory(tmp_path).log_path)
    app, shutdown = _centrum_with_queued_quantity_check(tmp_path, box, log, ManualClock())
    since = new_line()
    served, port = _serving(app, shutdown, log)

    try:
        assert box.opening.wait(30), "kolejka nie zaczęła wysyłki z poprzedniej pracy Centrum"
        shutdown.request()
        served.join(30)
        closed = not served.is_alive()
        port_free = _centrum_could_listen(port)
    finally:
        hold.set()
        join_threads_since(since)

    assert closed, "Centrum czekało z zamknięciem na wysyłkę kolejki"
    assert port_free


async def _progress_without_end() -> AsyncIterator[bytes]:
    yield b"postep\n"
    await asyncio.Event().wait()


def test_otwarty_strumien_postepu_nie_wstrzymuje_zamkniecia_centrum_bez_konca(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/postep")
    async def progress() -> StreamingResponse:
        return StreamingResponse(_progress_without_end())

    log = CentrumLog(ToolDirectory(tmp_path).log_path)
    shutdown = Shutdown(log)
    since = new_line()
    served, port = _serving(app, shutdown, log)
    connection = http.client.HTTPConnection(HOST, port, timeout=30)
    try:
        connection.request("GET", "/postep")
        first = connection.getresponse().readline()
        shutdown.request()
        served.join(30)
        closed = not served.is_alive()
    finally:
        connection.close()
        join_threads_since(since)

    assert (first, closed) == (b"postep\n", True)


class _EndingThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="konczacy-sie", daemon=True)
        self.code_ended = threading.Event()
        self.end = threading.Event()

    def _delete(self) -> None:
        super()._delete()  # type: ignore[misc]
        self.code_ended.set()
        self.end.wait()


def _other_program_listening() -> socket.socket:
    program = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        program.bind((HOST, 0))
        program.listen()
    except OSError:
        program.close()
        raise
    assert program.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
    if sys.platform == "win32":
        assert program.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) == 0
    return program


@pytest.mark.parametrize(
    "holder",
    [
        pytest.param(lambda: listen_locally(0), id="dzialajace-centrum"),
        pytest.param(_other_program_listening, id="inny-program"),
    ],
)
def test_port_na_ktorym_slucha_dzialajace_centrum_albo_inny_program_nie_jest_wolny_dla_drugiego_centrum(
    holder: Callable[[], socket.socket],
) -> None:
    held = holder()
    try:
        port = held.getsockname()[1]
        free = (port_free(port), _centrum_could_listen(port))
    finally:
        held.close()

    assert free == (False, False)


def test_zatrzymanie_centrum_w_tescie_czeka_na_koniec_watku_systemu_a_nie_tylko_jego_kodu() -> None:
    since = new_line()
    ending = _EndingThread()
    ending.start()
    assert ending.code_ended.wait(30), "wątek nie doszedł do końca swojego kodu"

    try:
        with pytest.raises(AssertionError, match="żyją wątki konczacy-sie"):
            join_threads_since(since, timeout_s=0)
    finally:
        ending.end.set()
    join_threads_since(since)

    assert not ending.is_alive()


def _ran(name: str) -> None:
    thread = threading.Thread(target=lambda: None, name=name)
    thread.start()
    thread.join()


def test_watki_uruchomione_w_bloku_licza_sie_takze_skonczone_a_watki_wczesniejszej_linii_i_po_bloku_nie() -> None:
    go = threading.Event()

    def left_behind() -> None:
        go.wait(30)
        _ran("z-wczesniejszej-linii")

    earlier = threading.Thread(target=left_behind, name="wczesniejszy")
    earlier.start()

    with started_threads() as started:
        _ran("w-bloku")
        go.set()
        earlier.join(30)
        left_behind_ran_in_block = not earlier.is_alive()
    _ran("po-bloku")

    assert (started, left_behind_ran_in_block) == (["w-bloku"], True)


def test_klient_testowy_bez_with_nie_otwiera_nowej_petli_zdarzen_na_zadanie(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"stan": "ok"}

    opened: list[object] = []
    open_loop = asyncio.base_events.BaseEventLoop.__init__

    def opening(self: asyncio.base_events.BaseEventLoop, *args: Any, **kwargs: Any) -> None:
        opened.append(self)
        open_loop(self, *args, **kwargs)

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "__init__", opening)
    client = TestClient(app)

    answers = [client.get("/ping").json() for _ in range(20)]

    assert (answers, opened) == ([{"stan": "ok"}] * 20, [])


def test_watek_z_obslugi_zadania_we_wspolnej_petli_nalezy_do_linii_testu_a_watek_roboczy_anyio_nie() -> None:
    app = FastAPI()
    end = threading.Event()

    @app.post("/w-petli")
    async def in_loop() -> None:
        threading.Thread(target=end.wait, name="z-petli").start()

    @app.post("/w-watku-roboczym")
    def in_worker() -> None:
        threading.Thread(target=end.wait, name="z-watku-roboczego").start()

    client = TestClient(app)
    since = new_line()
    try:
        client.post("/w-petli")
        client.post("/w-watku-roboczym")
        names = sorted(thread.name for thread in threads_since(since))
    finally:
        end.set()
    join_threads_since(since)

    assert names == ["z-petli", "z-watku-roboczego"]


def test_timer_pytest_timeout_z_watku_testu_nie_nalezy_do_linii_testu() -> None:
    end = threading.Event()
    since = new_line()
    threads = [threading.Thread(target=end.wait, name=name) for name in (f"{PYTEST_TIMEOUT_THREAD}test", "centrum")]
    try:
        for thread in threads:
            thread.start()
        names = [thread.name for thread in threads_since(since)]
    finally:
        end.set()
        for thread in threads:
            thread.join()

    assert names == ["centrum"]


@pytest.fixture(scope="module")
def watki_centrow_po_tescie() -> Iterator[list[threading.Thread]]:
    """Sprawdza wątki Centrów, nie linie klientów (``CentrumClient.threads``): z ``--dist worksteal`` worker bierze po tym
    teście inne testy modułu, a wątki, które one uruchamiają, też należą do linii od ``since`` klientów."""

    threads: list[threading.Thread] = []
    yield threads
    assert [thread.name for thread in threads if thread.is_alive()] == []


def test_kazde_centrum_testu_bez_stop_zatrzymuje_sie_po_tescie_razem_z_watkami(
    watki_centrow_po_tescie: list[threading.Thread],
) -> None:
    def started(name: str) -> CentrumClient:
        stopping = threading.Event()

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            threading.Thread(target=stopping.wait, name=name, daemon=True).start()
            yield
            stopping.set()

        client = CentrumClient(FastAPI(lifespan=lifespan))
        client.__enter__()
        return client

    first, second = started("praca-pierwszego-centrum"), started("praca-drugiego-centrum")
    watki_centrow_po_tescie.extend(thread for client in (first, second) for thread in client.threads())

    assert {"praca-pierwszego-centrum", "praca-drugiego-centrum"} <= {thread.name for thread in watki_centrow_po_tescie}


_PRIVACY_PROBE = """
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from rozliczenia.centrum.log import CentrumLog

from tests.fixtures.centrum import CentrumClient


def started(tmp_path: Path) -> CentrumClient:
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        log.run_started(process="settlement", mode="podglad", period=str(tmp_path))

    client = CentrumClient(FastAPI(lifespan=lifespan))
    client.__enter__()
    return client


def test_bez_stop(tmp_path: Path) -> None:
    started(tmp_path)


def test_ze_stop(tmp_path: Path) -> None:
    started(tmp_path).stop()
"""


def test_wpis_dziennika_przy_zamknieciu_centrum_bez_stop_lamie_regule_prywatnosci_jak_po_stop(tmp_path: Path) -> None:
    (tmp_path / "test_sonda_prywatnosci.py").write_text(_PRIVACY_PROBE, encoding="utf-8")
    report = tmp_path / "junit.xml"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.conftest", "-p", "no:cacheprovider", "-n", "0"]
        + [f"--junitxml={report}", "test_sonda_prywatnosci.py"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )

    broken = {
        case.attrib["name"]: [element.get("message", "") for element in case if element.tag == "error"]
        for case in ET.parse(report).iter("testcase")
    }
    assert done.returncode == 1, done.stdout + done.stderr
    leak = "Reguła prywatności Centrum (ADR 0004) złamana"
    assert {name: any(leak in message for message in messages) for name, messages in broken.items()} == {
        "test_bez_stop": True,
        "test_ze_stop": True,
    }
