"""Straż pliku, który test zostawił otwarty w śmieciach (``tests/fixtures/pliki_w_smieciach.py``, #1923)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import contextlib
import gc
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from typing import IO, Final
import warnings
from xml.etree import ElementTree as ET
import zipfile

from openpyxl import Workbook, load_workbook
import pytest

from tests.fixtures.pliki_w_smieciach import left_to_gc, open_files
from tests.fixtures.znane_luki import assert_znane_luki

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="straż listuje deskryptory tylko na Linuksie i macOS")


@contextlib.contextmanager
def _bez_samoczynnego_gc() -> Iterator[None]:
    # Samoczynny gc w trakcie testu zamknąłby plik w śmieciach przed sprawdzeniem.
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def _skoroszyt(tmp_path: Path) -> Path:
    path = tmp_path / "skoroszyt.xlsx"
    Workbook().save(path)
    return path


def test_skoroszyt_read_only_bez_close_zamyka_dopiero_gc_a_straz_podaje_jego_sciezke(tmp_path: Path) -> None:
    path = _skoroszyt(tmp_path)

    with _bez_samoczynnego_gc():
        before = open_files()
        load_workbook(path, read_only=True)
        left = left_to_gc(before)

    assert left == [str(path.resolve())]


def test_zamkniety_skoroszyt_read_only_nie_wywraca_testu(tmp_path: Path) -> None:
    path = _skoroszyt(tmp_path)

    with _bez_samoczynnego_gc():
        before = open_files()
        workbook = load_workbook(path, read_only=True)
        workbook.close()
        left = left_to_gc(before)

    assert left == []


def test_zipfile_w_cyklu_zamyka_plik_bez_resourcewarning_a_straz_i_tak_podaje_jego_sciezke(tmp_path: Path) -> None:
    path = _skoroszyt(tmp_path)

    with _bez_samoczynnego_gc():
        before = open_files()
        cykl: list[object] = [zipfile.ZipFile(path)]
        cykl.append(cykl)
        del cykl
        left = left_to_gc(before)

    assert left == [str(path.resolve())]


def test_plik_ktory_zywy_watek_zamyka_w_trakcie_gc_nie_wywraca_testu(tmp_path: Path) -> None:
    # Wątek kolejki Zgłoszeń kończy blok with na pliku blokady przejścia już po teście, czasem w trakcie gc.collect()
    # straży: callback gc puszcza wątek dokładnie w tym oknie i czeka na jego koniec.
    path = _skoroszyt(tmp_path)
    otwarty, puszczony = threading.Event(), threading.Event()

    def trzyma_plik() -> None:
        with path.open("rb"):
            otwarty.set()
            puszczony.wait(10)

    watek = threading.Thread(target=trzyma_plik, daemon=True)

    def konczy_watek_w_trakcie_gc(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            puszczony.set()
            watek.join(10)

    with _bez_samoczynnego_gc():
        before = open_files()
        watek.start()
        otwarty.wait(10)
        gc.callbacks.append(konczy_watek_w_trakcie_gc)
        try:
            left = left_to_gc(before)
        finally:
            gc.callbacks.remove(konczy_watek_w_trakcie_gc)

    assert (left, watek.is_alive()) == ([], False)


class _PuszczaWatekWPrzegladzie:
    """Obiekt, o którego ``__class__`` pyta ``isinstance`` w przeglądzie ``gc.get_objects()`` straży: puszcza wtedy wątek
    i czeka na jego koniec, więc wątek zamyka i puszcza swój plik, gdy lista przeglądu jeszcze go trzyma."""

    def __init__(self, puszcza: Callable[[], None]) -> None:
        self._puszcza = puszcza

    def __getattribute__(self, name: str) -> object:
        if name == "__class__":
            object.__getattribute__(self, "_puszcza")()
        return object.__getattribute__(self, name)


def test_plik_ktory_zywy_watek_puszcza_w_trakcie_przegladu_obiektow_nie_wywraca_testu(tmp_path: Path) -> None:
    # Lista gc.get_objects() trzyma każdy obiekt, więc obiekt pliku, który wątek kolejki puścił w trakcie przeglądu,
    # zwalnia dopiero koniec listy w wątku straży, przed gc.collect().
    path = _skoroszyt(tmp_path)
    otwarty, puszczony = threading.Event(), threading.Event()

    def trzyma_plik() -> None:
        with path.open("rb"):
            otwarty.set()
            puszczony.wait(10)

    watek = threading.Thread(target=trzyma_plik, daemon=True)

    def puszcza() -> None:
        puszczony.set()
        watek.join(10)

    with _bez_samoczynnego_gc():
        before = open_files()
        watek.start()
        otwarty.wait(10)
        straznik = _PuszczaWatekWPrzegladzie(puszcza)
        left = left_to_gc(before)
        del straznik

    assert (left, watek.is_alive()) == ([], False)


_PLIK_W_CYKLU = """
def plik_w_cyklu(path):
    path.write_bytes(b"x")
    cykl = [open(path, "rb")]  # bez close(): wyciek fixtury
    cykl.append(cykl)
    return cykl
"""

# Sondy r1 i r2 PR #1930: fixtura każdego zasięgu yielduje plik w cyklu bez close(); sąsiad na końcu sesji zbiera
# ostrzeżenia gc jak test portu opiekuna w #1923. Fixturę z params pytest kończy w setupie następnego testu, a jej
# teardown robi zwykłą pracę, w której samoczynny gc zebrałby puszczony plik przed sprawdzeniem. Fixtura modułu z jednym
# testem ma setup i koniec w tym samym teście. Ciało testu zostawia plik w śmieciach, a raport testu robi zwykłą pracę
# przed teardownem. Setup, który pada, pomija ciało testu, a teardown fixtury funkcji puszcza plik i robi zwykłą pracę.
# Fixtura sesji kończy się po ostatnim teście, czyli po sąsiedzie.
_SONDY_FIXTUR: Final = {
    "conftest.py": _PLIK_W_CYKLU
    + """
import pytest

pytest_plugins = ["tests.fixtures.pliki_w_smieciach"]


@pytest.fixture(scope="session")
def plik_sesji(tmp_path_factory):
    yield plik_w_cyklu(tmp_path_factory.mktemp("s") / "sesja.bin")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if item.name == "test_cialo_zostawia_plik" and call.when == "call":
        zywe = [[i] for i in range(1_000_000)]
        del zywe
    return report
""",
    "test_a_sesja.py": """
def test_otwiera_fixture_sesji(plik_sesji):
    assert plik_sesji
""",
    "test_b_funkcja.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture
def plik_funkcji(tmp_path):
    yield plik_w_cyklu(tmp_path / "funkcja.bin")


def test_z_fixtura_funkcji(plik_funkcji):
    assert plik_funkcji
""",
    "test_b_cialo.py": """
from conftest import plik_w_cyklu


def test_cialo_zostawia_plik(tmp_path):
    plik_w_cyklu(tmp_path / "cialo.bin")
""",
    "test_b_setup_pada.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture
def plik_przed_bledem(tmp_path):
    stan = [plik_w_cyklu(tmp_path / "przed_bledem.bin")]
    yield
    stan.clear()
    zywe = [[i] for i in range(1_000_000)]
    del zywe


@pytest.fixture
def blad():
    raise RuntimeError("setup pada")


def test_setup_pada(plik_przed_bledem, blad):
    pass
""",
    "test_c_modul.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture(scope="module")
def plik_modulu(tmp_path_factory):
    yield plik_w_cyklu(tmp_path_factory.mktemp("m") / "modul.bin")


def test_pierwszy_w_module(plik_modulu):
    assert plik_modulu


def test_ostatni_w_module(plik_modulu):
    assert plik_modulu
""",
    "test_c_parametr.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture(scope="module", params=["jeden", "dwa"])
def plik_parametru(request, tmp_path_factory):
    stan = [plik_w_cyklu(tmp_path_factory.mktemp(request.param) / f"{request.param}.bin")]
    yield request.param
    stan.clear()
    zywe = [[i] for i in range(1_000_000)]
    del zywe


def test_z_parametrem(plik_parametru):
    assert plik_parametru
""",
    "test_c_samotny.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture(scope="module")
def plik_samotnego(tmp_path_factory):
    yield plik_w_cyklu(tmp_path_factory.mktemp("j") / "samotny.bin")


def test_jedyny_w_module(plik_samotnego):
    assert plik_samotnego
""",
    "test_d_sasiad.py": """
import gc
import warnings


def test_sasiad_zbiera_ostrzezenia():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []
""",
}


def test_plik_fixtury_kazdego_zasiegu_wywraca_test_po_ktorym_fixtura_sie_konczy_a_nie_sasiada(tmp_path: Path) -> None:
    # Pytest trzyma wartości fixtur w item.funcargs aż po hakach teardown, fixtura modułu i sesji żyje przez wiele
    # testów, a fixturę z params kończy w setupie następnego testu, więc straż sprawdza każdą w chwili jej końca, w
    # prawdziwym cyklu życia testu w osobnym procesie pytest.
    for name, text in _SONDY_FIXTUR.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    report = tmp_path / "junit.xml"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", f"--basetemp={tmp_path / 'tmp'}"]
        + ["-p", "no:randomly", f"--junitxml={report}", "-o", "junit_family=xunit1"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )

    errors = {
        case.attrib["name"]: " ".join(
            element.get("message", "") for element in case if element.tag in ("error", "failure")
        )
        for case in ET.parse(report).iter("testcase")
    }
    owners = {
        name: [
            owner
            for owner in (
                "on setup",
                "on teardown",
                "funkcja.bin",
                "cialo.bin",
                "przed_bledem.bin",
                "modul.bin",
                "fixtura plik_modulu zasięgu module",
                "jeden.bin",
                "dwa.bin",
                "fixtura plik_parametru zasięgu module",
                "samotny.bin",
                "fixtura plik_samotnego zasięgu module",
                "sesja.bin",
                "fixtura plik_sesji zasięgu session",
            )
            if owner in message
        ]
        for name, message in errors.items()
        if message
    }
    assert owners == {
        "test_z_fixtura_funkcji": ["on teardown", "funkcja.bin"],
        "test_cialo_zostawia_plik": ["on teardown", "cialo.bin"],
        "test_setup_pada": ["on setup", "on teardown", "przed_bledem.bin"],
        "test_ostatni_w_module": ["on teardown", "modul.bin", "fixtura plik_modulu zasięgu module"],
        "test_z_parametrem[dwa]": ["on setup", "jeden.bin", "fixtura plik_parametru zasięgu module"],
        "test_jedyny_w_module": ["on teardown", "samotny.bin", "fixtura plik_samotnego zasięgu module"],
        "test_sasiad_zbiera_ostrzezenia": ["on teardown", "sesja.bin", "fixtura plik_sesji zasięgu session"],
    }, done.stdout + done.stderr


def test_ostrzezenie_smiecia_spoza_nowych_plikow_idzie_dalej_a_obserwowanego_pliku_zastepuje_wynik(
    tmp_path: Path,
) -> None:
    # gc.collect() straży zbiera też śmieć sprzed testu; jego ResourceWarning nie może zniknąć w straży (D1 r1 PR #1930).
    stary, nowy = tmp_path / "stary.bin", tmp_path / "nowy.bin"
    stary.write_bytes(b"x")
    nowy.write_bytes(b"x")

    with _bez_samoczynnego_gc(), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cykl: list[object] = [stary.open("rb")]
        cykl.append(cykl)
        before = open_files()
        cykl = [nowy.open("rb")]
        cykl.append(cykl)
        del cykl
        left = left_to_gc(before)

    unclosed = [str(warning.message) for warning in caught if issubclass(warning.category, ResourceWarning)]
    # Plik w cyklu ostrzega z bufora albo z io.FileIO, zależnie od tego, który finalizer gc puści pierwszy.
    assert (left, [(stary.name in message, nowy.name in message) for message in unclosed]) == (
        [str(nowy.resolve())],
        [(True, False)],
    )


def _zywy_obiekt(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    trzymane.append(path.open("rb"))


def _windows(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    load_workbook(path, read_only=True)


def _plik_biblioteki_c(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    cykl: list[object] = [sqlite3.connect(path.with_suffix(".sqlite"))]
    cykl.append(cykl)


def _potok(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    odczyt, zapis = os.pipe()
    os.close(zapis)
    cykl: list[object] = [os.fdopen(odczyt, "rb")]
    cykl.append(cykl)


ZNANE_LUKI: Final[dict[str, Callable[[Path, list[IO[bytes]], pytest.MonkeyPatch], None]]] = {
    "widzi tylko plik zwolniony przez gc: plik trzymany po teście przez żywy obiekt": _zywy_obiekt,
    "listuje deskryptory tylko na Linuksie i macOS: na Windows nie widzi pliku w śmieciach": _windows,
    "zna tylko obiekt io.FileIO: plik otwarty przez bibliotekę C (połączenie sqlite3) w cyklu": _plik_biblioteki_c,
    "zna tylko zwykłe pliki: potok (jak wyjście procesu potomnego) w cyklu": _potok,
}


def test_znane_luki_strazy_plikow_w_smieciach_przechodza_przez_nia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _skoroszyt(tmp_path)
    zgloszenia: dict[str, list[str]] = {}

    for opis, probka in ZNANE_LUKI.items():
        trzymane: list[IO[bytes]] = []
        with monkeypatch.context() as patch, _bez_samoczynnego_gc():
            before = open_files()
            probka(path, trzymane, patch)
            zgloszenia[opis] = left_to_gc(before)
        for obiekt in trzymane:
            obiekt.close()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()  # plik próbki w śmieciach nie zostaje dla straży po teście

    assert_znane_luki(zgloszenia, "tests/test_pliki_w_smieciach.py")
