"""Plik, który test zostawił otwarty w śmieciach (#1923).

Obiekt pliku trzymany tylko przez cykl referencji (skoroszyt openpyxl ``read_only=True`` bez ``close()``) zamyka dopiero
``gc``, czyli często w oknie innego testu na tym samym workerze, a ``ResourceWarning`` jego finalizera wywraca test, który
łapie własne ostrzeżenia: w #1923 test portu opiekuna dostał plik INTERMAX z ``tests/test_uporzadkowanie_intermax.py``,
gdy zmiana podziału plików postawiła oba pliki testów w jednym zadaniu CI.

Plugin (``pytest_plugins`` w ``tests/conftest.py``) sprawdza plik w chwili, w której jego właściciel puszcza ostatnią
referencję, a nie w umówionej chwili po nim: samoczynny ``gc`` stoi od tego zdarzenia do sprawdzenia (``_hold_gc``),
więc ``ResourceWarning`` nie ma okna, w którym trafiłby do innego testu. Zdarzenia to koniec ciała testu (sprawdzenie po
pełnym teardownie, także po puszczeniu wartości fixtur, które pytest trzyma w ``item.funcargs`` aż po hakach teardown) i
początek końca fixtury zasięgu modułu, klasy, pakietu albo sesji: jej finalizer straży biegnie pierwszy w
``FixtureDef.finish``, a sprawdzenie w najbliższym haku po nim, czyli w setupie nowej instancji, gdy fixtura z
``params`` zmienia parametr w setupie następnego testu, albo w teardownie testu. Przed zdarzeniem plik trzyma silna
referencja, więc ``gc`` go nie zbierze; śmieć z ciała testu albo setupu fixtury, który ``gc`` zbierze od razu, ostrzega
w tym samym teście. Test, którego plik zwolnił dopiero ``gc`` (``left_to_gc``), kończy się błędem z jego ścieżką, a plik
fixtury szerszego zasięgu także z jej nazwą. Lista deskryptorów kosztuje ułamek milisekundy, a przegląd obiektów i
``gc.collect()`` biegną tylko wtedy, gdy nowy plik jest jeszcze otwarty. Plik trzymany przez żywy obiekt (wątek kolejki
Zgłoszeń, który kończy przejście już po teście) nie wywraca testu, także gdy wątek zamyka go w trakcie ``gc.collect()``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
import gc
import io
import os
from pathlib import Path
import stat
import sys
import threading
from typing import Final
import warnings
import weakref

import pytest

_STANDARD_STREAMS: Final = frozenset({0, 1, 2})


@dataclass(frozen=True)
class _Fixture:
    name: str
    scope: str


@dataclass(frozen=True)
class _EndedFixture:
    fixture: _Fixture
    open_before_setup: dict[int, str]


# Stan procesu, bo pod xdist każdy worker ma własne testy i fixtury: pliki przed setupem bieżącego testu, przed setupem
# żywych fixtur zasięgu szerszego niż test, pliki otwarte przez setup takiej fixtury, fixtury skończone od ostatniego
# sprawdzenia i stan samoczynnego gc sprzed jego wstrzymania.
_open_before_test: dict[int, str] = {}
_open_at_fixture_setup: dict[pytest.FixtureDef[object], dict[int, str]] = {}
_opened_in_setup: dict[str, _Fixture] = {}
_ended_fixtures: list[_EndedFixture] = []
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
    _open_before_test.clear()
    _open_before_test.update(open_files())


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
    if _ended_fixtures:  # pytest skończył instancję fixtury z params w setupie następnego testu (FixtureDef.execute)
        try:
            _check("przed setupem tego testu")
        finally:
            _release_gc()
    if fixturedef.scope == "function":
        return (yield)
    before = _open_at_fixture_setup[fixturedef] = open_files()
    result = yield
    fixture = _Fixture(fixturedef.argname, fixturedef.scope)
    for path in set(open_files().values()) - set(before.values()):
        _opened_in_setup[path] = fixture
    # Finalizery biegną od ostatniego (LIFO), więc ten biegnie pierwszy w finish: gc stoi przez teardown fixtury i
    # puszczenie cached_result aż do sprawdzenia.
    fixturedef.addfinalizer(_hold_gc)
    return result


def pytest_fixture_post_finalizer(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest) -> None:
    if (before := _open_at_fixture_setup.pop(fixturedef, None)) is not None:
        _ended_fixtures.append(_EndedFixture(_Fixture(fixturedef.argname, fixturedef.scope), before))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, object, object]:
    """Test, którego plik po pełnym teardownie zwolnił dopiero ``gc``, kończy się błędem z jego ścieżką, a plik fixtury
    szerszego zasięgu także z jej nazwą: inaczej ``ResourceWarning`` tego pliku trafia do innego testu (#1923)."""

    _hold_gc()  # także po setupie, który padł przed ciałem testu
    try:
        result = yield
        if isinstance(item, pytest.Function):
            # Ostatnia referencja wartości fixtur; pytest puszcza ją dopiero po hakach teardown (runner.runtestprotocol).
            item.funcargs = {}
        _check("po tym teście")
    except BaseException as error:
        # Teardown, który rzuca (także Skipped z pytest.skip, który testu nie czerwieni), też puszcza pliki: sprawdzenie
        # biegnie przed powrotem gc, a błąd straży niesie pierwotny wyjątek jako przyczynę (W1 r3 PR #1930).
        if isinstance(item, pytest.Function):
            item.funcargs = {}
        try:
            _check("po tym teście")
        except AssertionError as found:
            raise found from error
        raise
    finally:
        _release_gc()
    return result


def _check(when: str) -> None:
    ended = list(_ended_fixtures)
    _ended_fixtures.clear()
    before = {
        descriptor: path
        for descriptor, path in _open_before_test.items()
        if all(fixture.open_before_setup.get(descriptor) == path for fixture in ended)
    }
    left = left_to_gc(before)
    assert left == [], (
        "Pliki otwarte w teście albo w fixturze zamknął dopiero gc: "
        + ", ".join(_owner(path, ended, when) for path in left)
        + ". Zamknij plik w teście albo w fixturze przez with albo try/finally z close(); skoroszyt openpyxl "
        "read_only=True trzyma plik do workbook.close()."
    )


def _owner(path: str, ended: list[_EndedFixture], when: str) -> str:
    """Ścieżka z fixturą, która otworzyła plik w setupie albo skończyła się od jego otwarcia; plik otwarty w tym teście
    poza setupem fixtury szerszego zasięgu należy do testu albo jego fixtury zasięgu funkcji."""

    ended_now = [record.fixture for record in ended]
    if (opener := _opened_in_setup.get(path)) is not None:
        fixtures = [opener]
    elif path in _open_before_test.values():
        fixtures = [record.fixture for record in ended if path not in record.open_before_setup.values()]
    else:
        return path
    return (
        path
        + " ("
        + ", ".join(
            f"fixtura {fixture.name} zasięgu {fixture.scope}, "
            + (f"która skończyła się {when}" if fixture in ended_now else "która otworzyła go w setupie")
            for fixture in fixtures
        )
        + ")"
    )


def open_files() -> dict[int, str]:
    """Zwykłe pliki otwarte w procesie: deskryptor → ścieżka bez dowiązań; na Windows pusty, bo nie ma taniej listy
    deskryptorów procesu. Bez standardowych strumieni: przechwytywanie pytest podmienia je między setupem a teardownem,
    więc wyjście pytest przekierowane do pliku (``> log``) byłoby nowym plikiem po każdym teście."""

    if sys.platform == "win32":
        return {}
    directory = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
    files: dict[int, str] = {}
    for entry in Path(directory).iterdir():
        descriptor = int(entry.name)
        if descriptor in _STANDARD_STREAMS:
            continue
        try:
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                files[descriptor] = os.path.realpath(_path(descriptor))
        except OSError:  # deskryptor samej listy katalogu jest już zamknięty
            continue
    return files


def _path(descriptor: int) -> str:
    if sys.platform == "darwin":
        import fcntl

        return fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
    return os.readlink(f"/proc/self/fd/{descriptor}")


def left_to_gc(before: Mapping[int, str]) -> list[str]:
    """Ścieżki plików otwartych od ``before``, których obiekt ``io.FileIO`` zwolnił dopiero ``gc.collect()``.

    Kryterium to zwolnienie obiektu pliku w trakcie ``gc.collect()`` i w wątku, który go woła: przez sam ``gc`` albo
    przez finalizer śmiecia (``zipfile.ZipFile.__del__`` zamyka swój plik bez ``ResourceWarning``). Zamknięty
    deskryptor nie jest kryterium, bo zamyka go też żywy wątek, który w trakcie ``gc.collect()`` kończy swój blok
    ``with``; jego obiekt pliku zwalnia ten drugi wątek. Zwolnienie przed ``gc.collect()`` też nie: lista
    ``gc.get_objects()`` trzyma każdy obiekt, więc plik, który inny wątek zamknął i puścił w trakcie przeglądu, zwalnia
    dopiero koniec tej listy w wątku straży. Samoczynny ``gc`` stoi na czas sprawdzenia, żeby śmieć nie zniknął przed
    ``gc.collect()``.

    ``gc.collect()`` zbiera wszystkie śmieci, nie tylko obserwowane pliki: ostrzeżenie obserwowanego pliku zastępuje
    wynik straży, a każde inne ostrzeżenie idzie dalej do filtrów i zapisu ostrzeżeń wołającego, jak przy samoczynnym
    ``gc`` w tym miejscu.
    """

    new = {descriptor: path for descriptor, path in open_files().items() if before.get(descriptor) != path}
    if not new:
        return []
    collecting: list[int] = []
    left: set[str] = set()

    def freed_by(path: str) -> Callable[[object], None]:
        def freed(_: object) -> None:
            if collecting == [threading.get_ident()]:
                left.add(path)

        return freed

    automatic = gc.isenabled()
    gc.disable()
    try:
        watched = {
            id(candidate): weakref.ref(candidate, freed_by(new[descriptor]))
            for candidate in gc.get_objects()
            if isinstance(candidate, io.FileIO) and (descriptor := _open_descriptor(candidate)) in new
        }
        if not watched:
            return []
        collecting.append(threading.get_ident())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gc.collect()
        collecting.clear()
    finally:
        if automatic:
            gc.enable()
    for warning in caught:
        if _file_of(warning.source) not in watched:
            warnings.warn_explicit(
                warning.message,
                warning.category,
                warning.filename,
                warning.lineno,
                source=warning.source,
            )
    return sorted(left)


def _open_descriptor(file: io.FileIO) -> int | None:
    try:
        return file.fileno()
    except ValueError:  # plik zamknięty, także przez inny wątek w trakcie przeglądu
        return None


def _file_of(source: object) -> int | None:
    """``id`` obiektu ``io.FileIO`` pod źródłem ``ResourceWarning``: plik ostrzega z warstwą, którą zamknął finalizer
    (``TextIOWrapper`` → ``.buffer``, bufor → ``.raw``)."""

    raw = getattr(getattr(source, "buffer", source), "raw", source)
    return id(raw) if isinstance(raw, io.FileIO) else None
