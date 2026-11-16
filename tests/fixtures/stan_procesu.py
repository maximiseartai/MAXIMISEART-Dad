"""Stan procesu workera, który test zostawił następnemu testowi w tym samym workerze (#1923, #1783).

Pod xdist testy jednego workera dzielą proces, więc to, co test zostawi w procesie, działa potem w oknie innego testu:
plik w śmieciach zamyka finalizer ``gc``, a jego ``ResourceWarning`` wywraca sąsiada, który łapie ostrzeżenia (#1923),
a wątek zegara śpi w podmianie snu sąsiada (#1783). Który test jest sąsiadem, zmienia każdy nowy podział plików na
zadania CI, więc plugin (``pytest_plugins`` w ``tests/conftest.py``) nie czeka na sąsiada: porównuje stan procesu po
pełnym teardownie testu ze stanem sprzed jego setupu, a test, po którym się różni, kończy się błędem z tym, co zostawił.

Stan to to, co proces trzyma poza stertą Pythona, czyli to, czym działa dalej bez kodu testu:

- deskryptory każdego rodzaju (plik, gniazdo, potok, plik biblioteki C), także te, które zamknąłby dopiero ``gc``;
- wątki z linii testu (``tests/fixtures/linie_watkow.py``), które żyją jeszcze ``WATEK_S`` po teardownie;
- procesy potomne, które żyją jeszcze ``POTOMEK_S`` po teardownie;
- katalog roboczy i zmienne środowiska.

Zasób, który powstał w setupie fixtury zasięgu modułu, klasy, pakietu albo sesji, należy do niej, a nie do testu: plugin
sprawdza go w chwili jej końca, czyli w teardownie testu, po którym się skończyła, albo w setupie następnego, gdy
fixtura z ``params`` zmienia parametr, a błąd ma nazwę fixtury. Od końca ciała testu i od początku końca takiej fixtury
do sprawdzenia samoczynny ``gc`` stoi (``_hold_gc``), więc plik w śmieciach nie zamyka się w oknie innego testu i nie
znika przed sprawdzeniem. Zasób na całe życie procesu workera (``_ZASOBY_PROCESU``) startuje przed pierwszym testem,
więc jest w stanie sprzed każdego testu.

Po błędzie plugin przywraca katalog roboczy i środowisko, więc błąd ma sprawca, a nie każdy następny test workera.
Porównanie kosztuje listę deskryptorów i potomków, poniżej 0,5 ms na test; ``gc.collect()``, czekanie na wątki i
potomków oraz opis zasobów biegną tylko wtedy, gdy stan się różni.

Granica porównania to stan poza stertą: zmienna modułu, atrybut podmieniony bez ``monkeypatch``, pamięć podręczna,
``sys.modules`` i filtry ostrzeżeń zostają dla sąsiada niewidoczne dla pluginu, tak jak zmiana stanu zasobu starszego
od testu (zadanie w pętli fixtury sesji). Wątek, który uruchomił wątek starszy od testu, nie należy do linii testu, a
wątek i potomek, które kończą się w ciągu ``WATEK_S`` i ``POTOMEK_S``, nie wywracają testu; deskryptor, który wątek
starszy od testu otworzył w trakcie testu i trzyma po nim, liczy się do testu. Gniazdo na macOS nie ma numeru węzła,
więc gniazdo zamknięte i otwarte znów pod tym samym numerem deskryptora wygląda jak to samo. Na Windows nie ma taniej
listy deskryptorów ani potomków procesu, więc tam plugin porównuje tylko wątki, katalog roboczy i środowisko. Stan
wspólny wszystkich workerów, czyli pliki w drzewie repozytorium, porównuje sesja w ``tests/conftest.py``
(``tests/fixtures/drzewo_repo.py``), bo plik w drzewie mógł zapisać każdy worker. Próbki granicy to ``ZNANE_LUKI`` w
``tests/test_stan_procesu.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass, field
import ctypes
import gc
import io
import multiprocessing.forkserver
import multiprocessing.resource_tracker
import os
from pathlib import Path
import socket
import stat
import sys
import threading
import time
from typing import Final
import warnings

import pytest

import potomne
from tests.fixtures.linie_watkow import new_line, threads_since
from tests.fixtures.potomne import wait_for

WATEK_S: Final = 5.0
"""Tyle po teardownie plugin czeka na koniec wątków z linii testu: wątek, który kończy pracę zaraz po teście (kolejka
Zgłoszeń po przejściu), nie wywraca testu, a pętla bez końca (budzik zegara z #1783) tak."""
POTOMEK_S: Final = 5.0
"""Tyle po teardownie plugin czeka na koniec procesów potomnych testu."""
_STANDARD_STREAMS: Final = frozenset({0, 1, 2})
# Przechwytywanie pytest podmienia standardowe strumienie, a pytest ustawia tę zmienną na czas każdego testu.
_ZMIENNE_PYTEST: Final = frozenset({"PYTEST_CURRENT_TEST"})


def _uruchom_zasoby_procesu() -> None:
    """Zasoby, które biblioteka otwiera raz na proces przy pierwszym użyciu i trzyma do jego końca: bez startu przed
    pierwszym testem należałyby do testu, który pierwszy ich użył. Nowy taki zasób dopisz tutaj."""

    if sys.platform == "win32":  # tam plugin nie porównuje deskryptorów ani potomków
        return
    socket.getaddrinfo("localhost", None)  # macOS: połączenia resolvera systemu (mDNSResponder, netsrc)
    potomne.run([sys.executable, "-c", ""], cwd=Path.cwd(), timeout=60)  # strażnik drzew procesów narzędzi
    multiprocessing.resource_tracker.ensure_running()  # proces śledzący zasoby multiprocessing
    multiprocessing.forkserver.ensure_running()  # serwer startu procesów multiprocessing (domyślny od Pythona 3.14)


_ZASOBY_PROCESU: list[Callable[[], None]] = [_uruchom_zasoby_procesu]


@dataclass(frozen=True)
class _Deskryptor:
    numer: int
    rodzaj: str
    urzadzenie: int
    wezel: int


@dataclass(frozen=True)
class Stan:
    """Stan procesu w jednej chwili; ``linia`` to numer, od którego ``threads_since`` liczy wątki uruchomione potem."""

    deskryptory: frozenset[_Deskryptor]
    potomki: frozenset[int]
    katalog: str
    srodowisko: frozenset[tuple[str, str]]
    linia: int


@dataclass(frozen=True)
class _Fixture:
    name: str
    scope: str


@dataclass
class _Wlasne:
    """Zasoby, które powstały w setupie fixtury szerszego zasięgu: od ``przed`` do ``po``."""

    fixture: _Fixture
    przed: Stan
    po: Stan

    def deskryptory(self) -> frozenset[_Deskryptor]:
        return self.po.deskryptory - self.przed.deskryptory

    def potomki(self) -> frozenset[int]:
        return self.po.potomki - self.przed.potomki

    def zmienne(self) -> frozenset[str]:
        return frozenset(name for name, _ in self.po.srodowisko ^ self.przed.srodowisko)

    def watki(self) -> list[threading.Thread]:
        pozniejsze = set(threads_since(self.po.linia))
        return [thread for thread in threads_since(self.przed.linia) if thread not in pozniejsze]


@dataclass
class Zostawione:
    """Różnica stanu procesu: to, co test albo fixtura zostawiły po sobie."""

    deskryptory: set[_Deskryptor] = field(default_factory=set)
    watki: list[threading.Thread] = field(default_factory=list)
    potomki: set[int] = field(default_factory=set)
    katalog: tuple[str, str] | None = None
    zmienne: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.deskryptory or self.watki or self.potomki or self.katalog or self.zmienne)


# Stan procesu, bo pod xdist każdy worker ma własne testy i fixtury: stan przed setupem bieżącego testu, zasoby żywych
# fixtur szerszego zasięgu, fixtury skończone od ostatniego sprawdzenia i stan samoczynnego gc sprzed jego wstrzymania.
_przed_testem: list[Stan] = []
_wlasne: dict[pytest.FixtureDef[object], _Wlasne] = {}
_skonczone: list[_Wlasne] = []
_held_gc_was_enabled: list[bool] = []


def _hold_gc() -> None:
    """Wstrzymuje samoczynny ``gc`` do najbliższego sprawdzenia: inaczej zebrałby puszczony plik przed nim."""

    if not _held_gc_was_enabled:
        _held_gc_was_enabled.append(gc.isenabled())
        gc.disable()


def _release_gc() -> None:
    # Test, który sam wyłączył gc, zostaje z wyłączonym.
    if _held_gc_was_enabled and _held_gc_was_enabled.pop():
        gc.enable()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    while _ZASOBY_PROCESU:
        _ZASOBY_PROCESU.pop()()
    _przed_testem[:] = [stan()]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    try:
        return (yield)
    finally:
        _hold_gc()  # ramka testu puściła swoje obiekty; śmieci czekają na sprawdzenie po teardownie


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest
) -> Generator[None, object, object]:
    if _skonczone:  # pytest skończył instancję fixtury z params w setupie następnego testu (FixtureDef.execute)
        try:
            _check("przed setupem tego testu")
        finally:
            _release_gc()
    if fixturedef.scope == "function":
        return (yield)
    przed = stan()
    result = yield
    _wlasne[fixturedef] = _Wlasne(_Fixture(fixturedef.argname, fixturedef.scope), przed, stan())
    # Finalizery biegną od ostatniego (LIFO), więc ten biegnie pierwszy w finish: gc stoi przez teardown fixtury i
    # puszczenie cached_result aż do sprawdzenia.
    fixturedef.addfinalizer(_hold_gc)
    return result


def pytest_fixture_post_finalizer(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest) -> None:
    if (wlasne := _wlasne.pop(fixturedef, None)) is not None:
        _skonczone.append(wlasne)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, object, object]:
    """Test, po którego pełnym teardownie proces ma inny stan niż przed jego setupem, kończy się błędem z tym, co
    zostawił, a zasób fixtury szerszego zasięgu także z jej nazwą: inaczej zasób działa w oknie innego testu."""

    _hold_gc()  # także po setupie, który padł przed ciałem testu
    try:
        result = yield
    except BaseException as error:
        # Teardown, który rzuca (także Skipped z pytest.skip, który testu nie czerwieni), też puszcza zasoby: sprawdzenie
        # biegnie przed powrotem gc, a błąd pluginu niesie pierwotny wyjątek jako przyczynę.
        try:
            _check_after(item)
        except AssertionError as found:
            raise found from error
        raise
    else:
        _check_after(item)
    finally:
        _release_gc()
    return result


def _check_after(item: pytest.Item) -> None:
    if isinstance(item, pytest.Function):
        # Ostatnia referencja wartości fixtur; pytest puszcza ją dopiero po hakach teardown (runner.runtestprotocol).
        item.funcargs = {}
    _check("po tym teście")


def _check(kiedy: str) -> None:
    skonczone = list(_skonczone)
    _skonczone.clear()
    przed = _przed_testem[0] if _przed_testem else stan()
    zostawione, wlasciciele = _roznica(przed, list(_wlasne.values()), skonczone)
    if not zostawione:
        return
    nazwy = {deskryptor: _opis_deskryptora(deskryptor) for deskryptor in zostawione.deskryptory}  # przed gc
    zebrane = _po_czekaniu_i_gc(zostawione)
    if not zostawione:
        return
    opisy = _opisy(zostawione, zebrane, nazwy, wlasciciele, kiedy)
    # Katalog i środowisko wracają, więc błąd ma tylko sprawca, a nie każdy następny test workera.
    if zostawione.katalog is not None:
        os.chdir(zostawione.katalog[0])
    oczekiwane = _oczekiwane_srodowisko(przed, skonczone)
    for name in zostawione.zmienne:
        if (value := oczekiwane.get(name)) is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    raise AssertionError(
        "Test albo jego fixtura zostawiły procesowi workera stan, który działa w oknie następnego testu: "
        + "; ".join(opisy)
        + ". Zamknij plik i gniazdo przez with albo try/finally (skoroszyt openpyxl read_only=True trzyma plik do "
        "workbook.close()), zatrzymaj i dołącz wątek, poczekaj na proces potomny, a katalog roboczy i środowisko "
        "zmieniaj przez monkeypatch (tests/fixtures/stan_procesu.py)."
    )


def _roznica(
    przed: Stan, zywe: Iterable[_Wlasne], skonczone: list[_Wlasne]
) -> tuple[Zostawione, dict[object, _Fixture]]:
    """To, co od ``przed`` przybyło poza zasobami żywych fixtur szerszego zasięgu, i zasoby ``skonczone`` fixtur, które
    jeszcze są, każdy z fixturą, do której należy."""

    teraz = stan()
    wlasciciele: dict[object, _Fixture] = {}
    zwolnione_deskryptory: set[_Deskryptor] = set()
    zwolnione_potomki: set[int] = set()
    zwolnione_zmienne: set[str] = set()
    zwolnione_watki: set[threading.Thread] = set()
    kandydaci = threads_since(przed.linia)
    for wlasne in zywe:
        zwolnione_deskryptory |= wlasne.deskryptory()
        zwolnione_potomki |= wlasne.potomki()
        zwolnione_zmienne |= wlasne.zmienne()
        if kandydaci:
            zwolnione_watki.update(wlasne.watki())
    for wlasne in skonczone:
        for zasob in (*wlasne.deskryptory(), *wlasne.potomki(), *wlasne.zmienne(), *wlasne.watki()):
            wlasciciele[zasob] = wlasne.fixture
    deskryptory = {d for d in teraz.deskryptory - przed.deskryptory if d not in zwolnione_deskryptory}
    deskryptory |= {d for d in teraz.deskryptory if d in wlasciciele}
    potomki = {p for p in teraz.potomki - przed.potomki if p not in zwolnione_potomki}
    potomki |= {p for p in teraz.potomki if p in wlasciciele}
    oczekiwane = _oczekiwane_srodowisko(przed, skonczone)
    srodowisko = dict(teraz.srodowisko)
    zmienne = {
        name
        for name in {*oczekiwane, *srodowisko}
        if name not in _ZMIENNE_PYTEST
        and srodowisko.get(name) != oczekiwane.get(name)
        and (name not in zwolnione_zmienne or name in wlasciciele)
    }
    watki = [t for t in kandydaci if t not in zwolnione_watki or t in wlasciciele]
    watki += [t for t in wlasciciele if isinstance(t, threading.Thread) and t.is_alive() and t not in watki]
    katalog = (przed.katalog, teraz.katalog) if teraz.katalog != przed.katalog else None
    return Zostawione(deskryptory, watki, potomki, katalog, zmienne), wlasciciele


def _oczekiwane_srodowisko(przed: Stan, skonczone: list[_Wlasne]) -> dict[str, str | None]:
    """Środowisko sprzed testu, a zmienna fixtury, która się skończyła, z wartością sprzed jej setupu."""

    oczekiwane: dict[str, str | None] = dict(przed.srodowisko)
    for wlasne in skonczone:
        sprzed_fixtury = dict(wlasne.przed.srodowisko)
        oczekiwane.update({name: sprzed_fixtury.get(name) for name in wlasne.zmienne()})
    return oczekiwane


def _po_czekaniu_i_gc(zostawione: Zostawione) -> set[_Deskryptor]:
    """Czeka na koniec wątków i potomków, potem zbiera śmieci; zostawia w ``zostawione`` to, co wciąż jest, i zwraca
    deskryptory, które zamknął dopiero ``gc`` (te zostają w ``zostawione``)."""

    termin = time.monotonic() + WATEK_S
    for thread in zostawione.watki:
        thread.join(max(termin - time.monotonic(), 0))
    zostawione.watki = [thread for thread in zostawione.watki if thread.is_alive()]
    wait_for(lambda: not (zostawione.potomki & children()), POTOMEK_S)
    zostawione.potomki &= children()
    zostawione.deskryptory &= descriptors()  # zamknięte przez wątek, który właśnie się skończył, nie należą do gc
    if not zostawione.deskryptory:
        return set()
    zebrane = left_to_gc(zostawione.deskryptory)
    zostawione.deskryptory &= descriptors() | zebrane
    return zebrane


def _opisy(
    zostawione: Zostawione,
    zebrane: set[_Deskryptor],
    nazwy: dict[_Deskryptor, str],
    wlasciciele: dict[object, _Fixture],
    kiedy: str,
) -> list[str]:
    def czyj(zasob: object) -> str:
        if (fixture := wlasciciele.get(zasob)) is None:
            return ""
        return f" (fixtura {fixture.name} zasięgu {fixture.scope}, która skończyła się {kiedy})"

    opisy = [
        f"{nazwy[d]} {'zamknął dopiero gc' if d in zebrane else 'otwarty po teście'}{czyj(d)}"
        for d in sorted(zostawione.deskryptory, key=lambda d: d.numer)
    ]
    opisy += [f"wątek {thread.name} żyje {WATEK_S:g} s po teście{czyj(thread)}" for thread in zostawione.watki]
    opisy += [f"proces potomny {pid} żyje {POTOMEK_S:g} s po teście{czyj(pid)}" for pid in sorted(zostawione.potomki)]
    if zostawione.katalog is not None:
        opisy.append(f"katalog roboczy {zostawione.katalog[0]} → {zostawione.katalog[1]}")
    opisy += [f"zmienna środowiska {name} zmieniona{czyj(name)}" for name in sorted(zostawione.zmienne)]
    return opisy


def stan() -> Stan:
    return Stan(
        descriptors(),
        children(),
        os.getcwd(),
        frozenset(os.environ.items()),
        new_line(),
    )


def descriptors() -> frozenset[_Deskryptor]:
    """Deskryptory procesu poza standardowymi strumieniami; na Windows pusty zbiór, bo nie ma taniej ich listy.
    Przechwytywanie pytest podmienia standardowe strumienie między setupem a teardownem."""

    if sys.platform == "win32":
        return frozenset()
    directory = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
    found: set[_Deskryptor] = set()
    for entry in Path(directory).iterdir():
        numer = int(entry.name)
        if numer in _STANDARD_STREAMS:
            continue
        try:
            info = os.fstat(numer)
        except OSError:  # deskryptor samej listy katalogu jest już zamknięty
            continue
        found.add(_Deskryptor(numer, _rodzaj(info.st_mode), info.st_dev, info.st_ino))
    return frozenset(found)


def _rodzaj(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "plik"
    if stat.S_ISSOCK(mode):
        return "gniazdo"
    if stat.S_ISFIFO(mode):
        return "potok"
    return "deskryptor"


def _opis_deskryptora(deskryptor: _Deskryptor) -> str:
    opis = f"{deskryptor.rodzaj} {deskryptor.numer}"
    if deskryptor.rodzaj != "plik":
        return opis
    try:
        if sys.platform == "darwin":
            import fcntl

            path = fcntl.fcntl(deskryptor.numer, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
        else:
            path = os.readlink(f"/proc/self/fd/{deskryptor.numer}")
    except OSError:  # deskryptor już zamknięty (gc)
        return opis
    return f"{opis} {os.path.realpath(path)}"


def children() -> frozenset[int]:
    """Procesy potomne, które jeszcze działają: bez zakończonych, na które nikt nie czekał (zombie); na Windows pusty."""

    if sys.platform == "win32":
        return frozenset()
    return frozenset(pid for pid in _child_pids() if _dziala(pid))


def _child_pids() -> list[int]:
    if sys.platform == "darwin":
        bufor = (ctypes.c_int * 4096)()
        liczba = _libproc().proc_listchildpids(os.getpid(), bufor, ctypes.sizeof(bufor))
        return list(bufor[: max(liczba, 0)])
    found: list[int] = []
    for task in Path("/proc/self/task").iterdir():
        try:
            found += [int(pid) for pid in (task / "children").read_text().split()]
        except OSError:  # wątek skończył się w trakcie listy
            continue
    return found


_LIBPROC: list[ctypes.CDLL] = []


def _libproc() -> ctypes.CDLL:
    if not _LIBPROC:
        _LIBPROC.append(ctypes.CDLL("/usr/lib/libproc.dylib"))
    return _LIBPROC[0]


def _dziala(pid: int) -> bool:
    if sys.platform == "win32":
        return False
    try:
        # WNOWAIT zostawia zakończony proces temu, kto na niego czeka (subprocess.Popen.wait).
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
    except ChildProcessError:  # już odebrany
        return False


def left_to_gc(nowe: Iterable[_Deskryptor]) -> set[_Deskryptor]:
    """Deskryptory z ``nowe``, które zamknął dopiero ``gc.collect()``: obiekt w śmieciach albo finalizer śmiecia.

    ``gc.collect()`` zbiera wszystkie śmieci, nie tylko obserwowane: ostrzeżenie obiektu z deskryptorem z ``nowe``
    należy do wyniku pluginu, a każde inne idzie dalej do filtrów i zapisu ostrzeżeń wołającego, jak przy samoczynnym
    ``gc`` w tym miejscu.
    """

    nowe = set(nowe)
    numery = {deskryptor.numer for deskryptor in nowe}
    automatic = gc.isenabled()
    gc.disable()
    try:
        obserwowane = {id(obj) for obj in gc.get_objects() if _numer(obj) in numery}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gc.collect()
    finally:
        if automatic:
            gc.enable()
    for warning in caught:
        if _zrodlo(warning.source) not in obserwowane:
            warnings.warn_explicit(
                warning.message, warning.category, warning.filename, warning.lineno, source=warning.source
            )
    return nowe - descriptors()


def _numer(obj: object) -> int | None:
    if not isinstance(obj, (io.FileIO, socket.socket)):
        return None
    try:
        return obj.fileno()
    except (ValueError, OSError):  # zamknięty, także przez inny wątek w trakcie przeglądu
        return None


def _zrodlo(source: object) -> int | None:
    """``id`` obiektu z deskryptorem pod źródłem ``ResourceWarning``: plik ostrzega z warstwą, którą zamknął finalizer
    (``TextIOWrapper`` → ``.buffer``, bufor → ``.raw``), a gniazdo samo."""

    raw = getattr(getattr(source, "buffer", source), "raw", source)
    return id(raw) if isinstance(raw, (io.FileIO, socket.socket)) else None
