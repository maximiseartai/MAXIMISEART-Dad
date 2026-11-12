"""Serwer Centrum rozliczeń: ``start`` i ``stop`` w dzienniku, póki Centrum trzyma port, wysyłka Logów Urwanego
Uruchomienia po wpisie ``start``, której wyjątek nie zatrzymuje startu, i port, który zamknięte Centrum zwalnia od razu, także gdy jego kolejka Skrzynki Zgłoszeń jeszcze wysyła, oraz zatrzymanie Centrum w teście, które
czeka na koniec każdego jego wątku, także każdego Centrum, którego test nie zatrzymał, zanim reguła prywatności czyta
dziennik, i klient testowy, który nie otwiera pętli zdarzeń na każde żądanie (#975)."""

from __future__ import annotations

import asyncio.base_events
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
import http.client
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from atrapy.dziennik_wyceny import begun_line, journal_path, left_journal
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import QUEUE_DIRECTORY, Outbox, PeriodThread, Post
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY
from rozliczenia.centrum.run_logs import StartFacts
from rozliczenia.centrum.server import serve
from rozliczenia.domain import RunMode
from rozliczenia.tool_files import listen_locally
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
        "kontrola-ilosci", "- Kontrola ilości okresu: 08_14_09_2026", "new_issue", "Kontrola ilości 08_14_09_2026"
    ),
    period="08_14_09_2026",
    run_id="3f2a9c1b8e7d4f0a9b1c2d3e4f5a6b7c",
    blocks=["różnice\n"],
    frame=lambda _number, _count, text: text,
)
QUEUED = "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json"
ROOT = Path(__file__).resolve().parents[1]


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
    # Po nieudanym starcie u taty kończy się proces; w teście wątek ``serve``, który czeka na prośbę o zamknięcie,
    # skończy się dopiero po niej.
    shutdown.request()
    join_threads_since(since)

    assert events == []
    listen_locally(port).close()


# Wycena w efenix, którą zgaszone Centrum urwało: jej dziennik w katalogu Logów czeka na następny start.
URWANA_WYCENA = StartFacts(
    run_id="627b45fe219e4274b722953c34d4af54",
    process="efenix",
    mode=RunMode.RUN,
    period="08_14_09_2026",
    started_at=datetime(2026, 9, 10, 8, 0),
)


def _left_pricing(tool: ToolDirectory) -> Path:
    """Dziennik Urwanej Wyceny w efenix, z którego start Centrum robi wersję zastępczą Logów; jego ścieżka."""

    return left_journal(
        tool.log_path.parent, URWANA_WYCENA, begun_line(datetime(2026, 9, 10, 8, 1), row=19, place=1, total=2)
    )


def _served_once(tool: ToolDirectory) -> tuple[int, list[str]]:
    """Centrum na ``serve`` jak u taty: start, jedno zapytanie karty i zamknięcie; status zapytania i wpisy dziennika,
    które Diagnoza i Zgłoszenia biorą jako wpisy tej pracy Centrum (``CentrumLog.recent``), bez czasu."""

    log = CentrumLog(tool.log_path)
    shutdown = Shutdown(log)
    app = centrum_app(tool, log=log, shutdown=shutdown)
    ready = threading.Event()
    listener = listen_locally(0)
    port = int(listener.getsockname()[1])
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
    """Wpisy dziennika o Logach Urwanego Uruchomienia, które start Centrum kładzie w Kolejce wysyłki (albo których kolejka
    nie przyjęła), stoją po wpisie ``start`` tej pracy Centrum, więc Diagnoza („Dziennik Centrum rozliczeń”), treść
    Zgłoszenia i Zgłoszenie Aktualizacji je widzą."""

    tool = ToolDirectory(tmp_path)
    _left_pricing(tool)
    if queue_blocked:  # na miejscu Kolejki wysyłki stoi plik, więc kolejka nie zapisze wersji zastępczej
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
    """Nieoczekiwany wyjątek przy wysyłce wersji zastępczej na starcie trafia do dziennika Centrum (typ), Centrum
    odpowiada, a dziennik Urwanej Wyceny zostaje na dysku na następny start."""

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


def test_zamkniete_centrum_zwalnia_port_od_razu_takze_gdy_kolejka_czeka_na_skrzynke(tmp_path: Path) -> None:
    # Skrót i opiekun ponownego startu startują nowe Centrum, gdy tylko port jest wolny, a zapytanie do Skrzynki nie ma
    # górnego limitu (wolna sieć): port trzymany do końca wysyłki dałby tacie kartę Centrum, które zaraz zniknie.
    hold = threading.Event()
    box = FakeReportBox(open_hold=hold)
    log = CentrumLog(ToolDirectory(tmp_path).log_path)
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
    """Wątek, którego kod już się skończył (zniknął z listy wątków modułu ``threading``), a wątek systemu jeszcze żyje.

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
    # Wątek wcześniejszego testu, który został w workerze, uruchamia swój wątek w czasie bloku następnego testu.
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
    _ran("po-bloku")

    assert (started, earlier.is_alive()) == (["w-bloku"], False)


def test_klient_testowy_bez_with_nie_otwiera_nowej_petli_zdarzen_na_zadanie(monkeypatch: pytest.MonkeyPatch) -> None:
    # #975: Starlette poza ``with`` otwierał pętlę z parą gniazd TCP na każde żądanie, a na Windows CI ich porty w
    # TIME_WAIT szły w tysiące na zadanie pytest (``WinError 10055`` przy ``socket.socketpair()``).
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
    # Wspólną pętlę klienta testowego otworzył inny test, a ``CentrumClient.stop`` czeka tylko na wątki linii testu:
    # wątek, który kod Centrum uruchamia w obsłudze żądania, musi do niej należeć, a bezczynny wątek roboczy AnyIO nie.
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
    # Na Windows pytest-timeout mierzy test wątkiem o nazwie „pytest_timeout <test>” z wątku testu; sprawdzenie linii
    # na końcu modułu widziało timer ostatniego testu jako wątek Centrum (#1080).
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
    """Wątki Centrów testu, żywe na jego końcu, które sprawdza koniec modułu, czyli chwila po ich zatrzymaniu w conftest.

    Sprawdza te wątki, nie linie klientów (``CentrumClient.threads``): z ``--dist worksteal`` worker bierze po tym teście
    inne testy modułu, a wątki, które one uruchamiają, też należą do linii od ``since`` klientów (#1330).
    """

    threads: list[threading.Thread] = []
    yield threads
    assert [thread.name for thread in threads if thread.is_alive()] == []


def test_kazde_centrum_testu_bez_stop_zatrzymuje_sie_po_tescie_razem_z_watkami(
    watki_centrow_po_tescie: list[threading.Thread],
) -> None:
    # Reguła „test nie zostawia wątku” nie zależy od tego, czy autor zawołał ``stop``: conftest po teście zatrzymuje
    # każde Centrum testu, nie tylko pierwsze albo ostatnie.
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


# Centrum testu, które przy zamknięciu (``lifespan``) pisze do swojego dziennika ścieżkę katalogu tymczasowego testów.
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
    # Conftest zatrzymuje Centrum, którego test nie zatrzymał, zanim reguła prywatności (ADR 0004) czyta dziennik, więc
    # wpis z zamknięcia Centrum sprawdza tak samo, jak po ``stop`` w teście; kolejność autouse z nazw by to odwróciła.
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
