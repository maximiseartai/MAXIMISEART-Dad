"""Linie wątków testu, zatrzymanie Centrum po teście i jedna pętla zdarzeń ``TestClient`` (#975), bez importu kodu narzędzia.

Linia to wątki, które uruchomił wątek testu, razem z wątkami, które one uruchomiły później. ``CentrumClient``
(``tests/fixtures/centrum.py``) czeka po ``stop`` na wątki swojej linii, a ``stop_after_test`` zapisuje go do
zatrzymania po teście. Moduł nie importuje ``src/``, bo ładuje go
``tests/conftest.py``: import Centrum stąd uzależniłby każdy plik testów od kodu Centrum (``tests/test_ksztalt_bramki.py``).
"""

from __future__ import annotations

import contextlib
import contextvars
import itertools
import threading
import weakref
from collections.abc import Callable, Iterator
from typing import Any

from anyio._backends._asyncio import WorkerThread
from anyio.from_thread import BlockingPortal, start_blocking_portal
from fastapi.testclient import TestClient


# Numer startu przodka każdego wątku, którego uruchomił wątek testu (pierwszego wątku tej linii).
_LINE_STARTS: weakref.WeakKeyDictionary[threading.Thread, int] = weakref.WeakKeyDictionary()
# Wątki Centrum dopisują się do ``_LINE_STARTS`` w chwili, gdy ``threads_since`` go przegląda.
_LINE_STARTS_LOCK = threading.Lock()
_STARTS = itertools.count()
_thread_start = threading.Thread.start
# pytest-timeout bez sygnałów (Windows) mierzy każdy test wątkiem-timerem o tej nazwie, uruchomionym w wątku testu: to
# wątek pytest, nie Centrum, i żyje do końca testu, także w teardownie modułu, który sprawdza linie (#1080).
PYTEST_TIMEOUT_THREAD = "pytest_timeout "
# Nazwy wątków, które linie od numeru startu uruchomiły w bloku ``started_threads``, także te, które już się skończyły.
_RECORDED: list[tuple[int, list[str]]] = []


# Linia wątku, który wysłał żądanie przez wspólną pętlę ``TestClient``: obsługa żądania biegnie w wątku tej pętli albo
# w wątku roboczym AnyIO, a wątki, które w niej uruchamia Centrum, należą do linii wysyłającego, nie pętli.
_REQUEST_LINE: contextvars.ContextVar[int] = contextvars.ContextVar("linia_zadania")


def _line_of_new_thread() -> int:
    """Numer startu linii, którą dostaje wątek uruchomiony teraz w bieżącym wątku (i obsłudze żądania)."""

    line = _REQUEST_LINE.get(None)
    if line is None:
        line = _LINE_STARTS.get(threading.current_thread())
    return next(_STARTS) if line is None else line


def _start_in_line(self: threading.Thread) -> None:
    """Wątek dziedziczy numer startu linii po wątku, który go uruchamia; wątek testu zaczyna nową linię.

    Wątek roboczy AnyIO nie należy do żadnej linii: pętla ``TestClient`` trzyma go bezczynnego po żądaniu, a wątki,
    które uruchamia kod Centrum w nim, dostają linię żądania z ``_REQUEST_LINE``.
    """

    with _LINE_STARTS_LOCK:
        if not isinstance(self, WorkerThread) and not self.name.startswith(PYTEST_TIMEOUT_THREAD):
            line = _LINE_STARTS[self] = _line_of_new_thread()
            for since, names in _RECORDED:
                if line >= since:
                    names.append(self.name)
    _thread_start(self)


threading.Thread.start = _start_in_line  # type: ignore[method-assign]


# Zatrzymania Centrum, które ``stopped_after_test`` woła po teście.
_AFTER_TEST: list[Callable[[], None]] = []


def stop_after_test(stop: Callable[[], None]) -> None:
    """Zapisuje ``stop`` (np. ``CentrumClient.stop``) do wywołania po bieżącym teście."""

    _AFTER_TEST.append(stop)


def stopped_after_test() -> None:
    """Woła każde zatrzymanie z ``stop_after_test``, od ostatniego, także po błędzie wcześniejszego, i rzuca ten błąd."""

    stops = list(_AFTER_TEST)
    _AFTER_TEST.clear()
    with contextlib.ExitStack() as after_test:
        for stop in stops:
            after_test.callback(stop)


# Pętla zdarzeń, w której ``TestClient`` poza ``with`` obsługuje każde żądanie (``shared_test_loop``).
_SHARED_PORTAL: list[BlockingPortal] = []


class _PortalInLine:
    """Wspólna pętla dla jednego żądania: aplikacja biegnie z linią wątku, który je wysłał (``_REQUEST_LINE``)."""

    def __init__(self, portal: BlockingPortal, line: int) -> None:
        self._portal = portal
        self._line = line

    def call(self, func: Callable[..., Any], *args: object) -> Any:
        return self._portal.call(func, *args)

    def start_task_soon(self, func: Callable[..., Any], *args: object, name: object = None) -> Any:
        async def in_line(*task_args: object) -> Any:
            _REQUEST_LINE.set(self._line)
            return await func(*task_args)

        return self._portal.start_task_soon(in_line, *args, name=name)


@contextlib.contextmanager
def _one_loop_portal(self: TestClient) -> Iterator[Any]:
    """Pętla żądania ``TestClient``: w ``with`` ta z ``lifespan``, poza nim wspólna, nie nowa pętla na żądanie.

    Starlette poza ``with`` otwiera na każde żądanie nową pętlę z parą gniazd TCP (``socket.socketpair()``). Że ich
    porty w TIME_WAIT wyczerpywały na Windows pulę portów efemerycznych (``WinError 10055``), to hipoteza #975, której
    pomiar z #981 nie potwierdził; pomiary i powód wspólnej pętli opisuje fixture ``jedna_petla_testclient``.
    Gdy Starlette przestanie wołać ``_portal_factory``, pada
    ``test_klient_testowy_bez_with_nie_otwiera_nowej_petli_zdarzen_na_zadanie`` (``tests/test_centrum_serwer.py``),
    a gdy usunie ten atrybut, mypy (``attr-defined`` przy podmianie).
    """

    if self.portal is not None:
        yield self.portal
        return
    assert _SHARED_PORTAL, "TestClient poza testem: wspólną pętlę żądań otwiera fixture shared_test_loop z conftest.py."
    yield _PortalInLine(_SHARED_PORTAL[0], _line_of_new_thread())


TestClient._portal_factory = _one_loop_portal  # type: ignore[method-assign]


@contextlib.contextmanager
def shared_test_loop() -> Iterator[None]:
    """Jedna pętla zdarzeń dla żądań każdego ``TestClient`` poza ``with``; na końcu przerywa zadania, które w niej
    zostały (strumień zdarzeń, którego test nie zamknął)."""

    with start_blocking_portal(name="wspolna-petla-testclient") as portal:
        _SHARED_PORTAL.append(portal)
        try:
            yield
        finally:
            _SHARED_PORTAL.clear()
            portal.call(portal.stop, True)


def new_line() -> int:
    """Numer, od którego ``threads_since`` liczy wątki, które wątek testu uruchomi od teraz."""

    return next(_STARTS)


@contextlib.contextmanager
def started_threads() -> Iterator[list[str]]:
    """Nazwy wątków, które wątek testu uruchomi w bloku, razem z wątkami, które one uruchomią, także już skończonych.

    Dla testu, który sprawdza, że kod nie uruchamia wątków; o wątki, które jeszcze żyją, pyta ``threads_since``.
    """

    names: list[str] = []
    recorded = (new_line(), names)
    with _LINE_STARTS_LOCK:
        _RECORDED.append(recorded)
    try:
        yield names
    finally:
        with _LINE_STARTS_LOCK:
            _RECORDED.remove(recorded)


def threads_since(since: int, *, named: str | None = None) -> list[threading.Thread]:
    """Żywe wątki z linii, które wątek testu zaczął od ``since``, także uruchomione później przez wątki tych linii.

    ``named``: tylko wątki o tej nazwie.
    Żywy to ``is_alive()``, nie obecność w ``threading.enumerate()``: wątek znika z ``enumerate()`` na końcu swojego
    kodu (``Thread._delete``), zanim skończy się wątek systemu, a ``is_alive()`` do tej chwili zwraca True (#862).
    """

    with _LINE_STARTS_LOCK:
        lines = list(_LINE_STARTS.items())
    return [thread for thread, line in lines if line >= since and named in (None, thread.name) and thread.is_alive()]
