"""Plik, który test zostawił otwarty w śmieciach (#1923).

Obiekt pliku trzymany tylko przez cykl referencji (skoroszyt openpyxl ``read_only=True`` bez ``close()``) zamyka dopiero
``gc``, czyli często w oknie innego testu na tym samym workerze, a ``ResourceWarning`` jego finalizera wywraca test, który
łapie własne ostrzeżenia: w #1923 test portu opiekuna dostał plik INTERMAX z ``tests/test_uporzadkowanie_intermax.py``,
gdy zmiana podziału plików postawiła oba pliki testów w jednym zadaniu CI.

Plugin (``pytest_plugins`` w ``tests/conftest.py``) bierze zwykłe pliki procesu przed setupem testu (``open_files``) i po
pełnym teardownie wywraca test, którego plik zwolnił dopiero ``gc`` (``left_to_gc``). Pełny teardown to także wartości
fixtur: pytest trzyma je w ``item.funcargs`` aż po hakach teardown, więc plugin puszcza je przed sprawdzeniem, a plik
fixtury zasięgu modułu, klasy, pakietu albo sesji sprawdza w teście, po którym ta fixtura skończyła się, względem plików
sprzed jej setupu i z jej nazwą. Lista deskryptorów kosztuje ułamek milisekundy, a przegląd obiektów i ``gc.collect()``
biegną tylko wtedy, gdy po teście nowy plik jest jeszcze otwarty. Plik trzymany przez żywy obiekt (wątek kolejki
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
_OPEN_BEFORE_TEST: Final = pytest.StashKey[dict[int, str]]()


@dataclass(frozen=True)
class _EndedFixture:
    name: str
    scope: str
    open_before_setup: dict[int, str]


# Pliki przed setupem żywych fixtur zasięgu szerszego niż test i fixtury skończone od ostrzeżenia ostatniego testu; stan
# procesu, bo pod xdist każdy worker ma własne fixtury.
_open_at_fixture_setup: dict[pytest.FixtureDef[object], dict[int, str]] = {}
_ended_fixtures: list[_EndedFixture] = []


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    item.stash[_OPEN_BEFORE_TEST] = open_files()


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest) -> None:
    if fixturedef.scope != "function":
        _open_at_fixture_setup[fixturedef] = open_files()


def pytest_fixture_post_finalizer(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest) -> None:
    if (before := _open_at_fixture_setup.pop(fixturedef, None)) is not None:
        _ended_fixtures.append(_EndedFixture(fixturedef.argname, fixturedef.scope, before))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, object, object]:
    """Test, którego plik po pełnym teardownie zwolnił dopiero ``gc``, kończy się błędem z jego ścieżką, a plik fixtury
    szerszego zasięgu także z jej nazwą: inaczej ``ResourceWarning`` tego pliku trafia do innego testu (#1923)."""

    result = yield
    test_before = item.stash[_OPEN_BEFORE_TEST]
    ended = list(_ended_fixtures)
    _ended_fixtures.clear()
    before = {
        descriptor: path
        for descriptor, path in test_before.items()
        if all(fixture.open_before_setup.get(descriptor) == path for fixture in ended)
    }
    automatic = gc.isenabled()
    gc.disable()  # samoczynny gc zebrałby puszczoną wartość fixtury przed sprawdzeniem
    try:
        if isinstance(item, pytest.Function):
            # Ostatnia referencja wartości fixtur; pytest puszcza ją dopiero po hakach teardown (runner.runtestprotocol).
            item.funcargs = {}
        left = left_to_gc(before)
    finally:
        if automatic:
            gc.enable()
    assert left == [], (
        "Test zostawił otwarte pliki, które zamknął dopiero gc: "
        + ", ".join(_owner(path, test_before, ended) for path in left)
        + ". Zamknij plik w teście albo w fixturze przez with albo try/finally z close(); skoroszyt openpyxl "
        "read_only=True trzyma plik do workbook.close()."
    )
    return result


def _owner(path: str, test_before: Mapping[int, str], ended: list[_EndedFixture]) -> str:
    if path not in test_before.values():
        return path
    fixtures = [
        f"fixtura {fixture.name} zasięgu {fixture.scope}, która skończyła się po tym teście"
        for fixture in ended
        if path not in fixture.open_before_setup.values()
    ]
    return f"{path} ({', '.join(fixtures)})"


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
