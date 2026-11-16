"""Stan procesu, który test zostawił następnemu testowi (``tests/fixtures/stan_procesu.py``, #1923, #1783)."""

from __future__ import annotations

from collections.abc import Mapping
import gc
import os
from pathlib import Path
import subprocess
import sys
from typing import Final
import warnings
from xml.etree import ElementTree as ET

import pytest

from tests.fixtures.stan_procesu import descriptors, left_to_gc
from tests.fixtures.znane_luki import assert_znane_luki

ROOT: Final = Path(__file__).resolve().parents[1]

# Plugin w procesie pytest sesji próbek, z krótszym czekaniem na wątki i potomków niż w repozytorium.
_CONFTEST: Final = """
import pytest

import tests.fixtures.stan_procesu as stan_procesu

pytest_plugins = ["tests.fixtures.stan_procesu"]
stan_procesu.WATEK_S = 1.0
stan_procesu.POTOMEK_S = 1.0


def plik_w_cyklu(path):
    path.write_bytes(b"x")
    cykl = [open(path, "rb")]  # bez close(): wyciek fixtury
    cykl.append(cykl)
    return cykl
"""


def _sesja(tmp_path: Path, pliki: Mapping[str, str], conftest: str = _CONFTEST) -> dict[str, str]:
    """Komunikat błędu albo porażki każdego testu sesji próbek z plików ``pliki``, w prawdziwym cyklu życia testu w
    osobnym procesie pytest; test bez błędu ma pusty komunikat."""

    (tmp_path / "conftest.py").write_text(conftest, encoding="utf-8")
    for name, text in pliki.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    report = tmp_path / "junit.xml"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", f"--basetemp={tmp_path / 'tmp'}"]
        + ["-p", "no:randomly", f"--junitxml={report}", "-o", "junit_family=xunit1", *pliki],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "tools/lib")])},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )
    assert report.exists(), done.stdout + done.stderr
    return {
        case.attrib["name"]: " ".join(
            element.get("message", "") for element in case if element.tag in ("error", "failure")
        )
        for case in ET.parse(report).iter("testcase")
    }


def _zostawione(message: str) -> str:
    """Część komunikatu pluginu z tym, co test zostawił, bez rady, jak to naprawić."""

    return message.partition("następnego testu: ")[2].partition(". Zamknij")[0]


# Sprawca zostawia stan, a sąsiad w tym samym procesie zbiera ostrzeżenia gc jak sąsiad z #1923 i czyta środowisko i
# katalog roboczy, które plugin przywraca po błędzie sprawcy. Gniazdo w śmieciach to postać siostrzana #1923, której
# nie widziała straż samych plików.
_SASIAD: Final = "test_sasiad_zbiera_ostrzezenia_czyta_srodowisko_i_katalog"
_SPRAWCY: Final = {
    "test_a_sprawcy.py": """
import os
import socket
import sqlite3
import subprocess
import sys
import threading

TRZYMANE = []


def test_gniazdo_w_cyklu():
    cykl = [socket.socket()]
    cykl.append(cykl)


def test_potok_w_cyklu():
    odczyt, zapis = os.pipe()
    os.close(zapis)
    cykl = [os.fdopen(odczyt, "rb")]
    cykl.append(cykl)


def test_plik_biblioteki_c_w_cyklu(tmp_path):
    cykl = [sqlite3.connect(tmp_path / "baza.sqlite")]
    cykl.append(cykl)


def test_plik_trzymany_przez_zywy_obiekt(tmp_path):
    (tmp_path / "zywy.bin").write_bytes(b"x")
    TRZYMANE.append(open(tmp_path / "zywy.bin", "rb"))


def test_watek_bez_konca():
    stop = threading.Event()
    TRZYMANE.append(stop)
    threading.Thread(target=lambda: stop.wait(60), name="watek-bez-konca", daemon=True).start()


def test_proces_potomny_bez_konca():
    TRZYMANE.append(subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE))


def test_katalog_roboczy(tmp_path):
    os.chdir(tmp_path)


def test_zmienna_srodowiska():
    os.environ["ZMIENNA_SPRAWCY"] = "1"
""",
    "test_b_sasiad.py": """
import gc
import os
from pathlib import Path
import warnings


def test_sasiad_zbiera_ostrzezenia_czyta_srodowisko_i_katalog(request):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    unclosed = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
    assert (unclosed, os.environ.get("ZMIENNA_SPRAWCY"), Path.cwd()) == ([], None, request.config.invocation_params.dir)
""",
}


@pytest.mark.skipif(sys.platform == "win32", reason="deskryptory i potomków plugin listuje tylko na Linuksie i macOS")
def test_kazdy_zasob_zostawiony_przez_test_wywraca_sprawce_a_nie_sasiada(tmp_path: Path) -> None:
    errors = _sesja(tmp_path, _SPRAWCY)

    found = {
        name: [
            part
            for part in (
                "gniazdo",
                "potok",
                "plik",
                "zywy.bin",
                "baza.sqlite",
                "zamknął dopiero gc",
                "otwarty po teście",
                "wątek watek-bez-konca żyje 1 s po teście",
                "proces potomny",
                "katalog roboczy",
                "zmienna środowiska ZMIENNA_SPRAWCY zmieniona",
            )
            if part in _zostawione(message)
        ]
        for name, message in errors.items()
        if name != _SASIAD
    }
    assert (found, errors[_SASIAD]) == ({
        "test_gniazdo_w_cyklu": ["gniazdo", "zamknął dopiero gc"],
        "test_potok_w_cyklu": ["potok", "zamknął dopiero gc"],
        "test_plik_biblioteki_c_w_cyklu": ["plik", "baza.sqlite", "zamknął dopiero gc"],
        "test_plik_trzymany_przez_zywy_obiekt": ["plik", "zywy.bin", "otwarty po teście"],
        "test_watek_bez_konca": ["wątek watek-bez-konca żyje 1 s po teście"],
        "test_proces_potomny_bez_konca": ["potok", "otwarty po teście", "proces potomny"],
        "test_katalog_roboczy": ["katalog roboczy"],
        "test_zmienna_srodowiska": ["zmienna środowiska ZMIENNA_SPRAWCY zmieniona"],
    }, ""), errors


# Fixtura każdego zasięgu yielduje plik w cyklu bez close(); sąsiad na końcu sesji zbiera ostrzeżenia gc jak test portu
# opiekuna w #1923. Fixturę z params pytest kończy w setupie następnego testu, a jej teardown robi zwykłą pracę, w której
# samoczynny gc zebrałby puszczony plik przed sprawdzeniem. Fixtura modułu z jednym testem ma setup i koniec w tym samym
# teście. Ciało testu zostawia plik w śmieciach, a raport testu robi zwykłą pracę przed teardownem. Setup, który pada,
# pomija ciało testu, a teardown fixtury funkcji puszcza plik i robi zwykłą pracę. Fixtura sesji kończy się po ostatnim
# teście, czyli po sąsiedzie. Teardown fixtury modułu, który rzuca (Skipped z pytest.skip, który testu nie czerwieni,
# albo RuntimeError), też puszcza plik. Fixtura sesji ustawia zmienną środowiska i przywraca ją na końcu.
_SONDY_FIXTUR: Final = {
    "test_a_sesja.py": """
import os

import pytest

from conftest import plik_w_cyklu


@pytest.fixture(scope="session")
def plik_sesji(tmp_path_factory):
    yield plik_w_cyklu(tmp_path_factory.mktemp("s") / "sesja.bin")


@pytest.fixture(scope="session")
def zmienna_sesji():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ZMIENNA_SESJI", "1")
        yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if item.name == "test_cialo_zostawia_plik" and call.when == "call":
        zywe = [[i] for i in range(1_000_000)]
        del zywe
    return report


def test_otwiera_fixture_sesji(plik_sesji, zmienna_sesji):
    assert plik_sesji and os.environ["ZMIENNA_SESJI"] == "1"
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
    "test_c_teardown_skip.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture(scope="module")
def plik_skip(tmp_path_factory):
    yield plik_w_cyklu(tmp_path_factory.mktemp("k") / "skip.bin")
    pytest.skip("sprzątanie bez zasobu")


def test_teardown_skip(plik_skip):
    assert plik_skip
""",
    "test_c_teardown_rzuca.py": """
import pytest
from conftest import plik_w_cyklu


@pytest.fixture(scope="module")
def plik_rzuca(tmp_path_factory):
    yield plik_w_cyklu(tmp_path_factory.mktemp("r") / "rzuca.bin")
    raise RuntimeError("teardown fixtury pada")


def test_teardown_rzuca(plik_rzuca):
    assert plik_rzuca
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


@pytest.mark.skipif(sys.platform == "win32", reason="deskryptory plugin listuje tylko na Linuksie i macOS")
def test_plik_fixtury_kazdego_zasiegu_wywraca_test_po_ktorym_fixtura_sie_konczy_a_nie_sasiada(tmp_path: Path) -> None:
    # Pytest trzyma wartości fixtur w item.funcargs aż po hakach teardown, fixtura modułu i sesji żyje przez wiele
    # testów, a fixturę z params kończy w setupie następnego testu, więc plugin sprawdza każdą w chwili jej końca.
    (tmp_path / "pliki").mkdir()
    report = tmp_path / "pliki"
    errors = _sesja(report, _SONDY_FIXTUR)
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
                "skip.bin",
                "fixtura plik_skip zasięgu module",
                "rzuca.bin",
                "fixtura plik_rzuca zasięgu module",
                "sesja.bin",
                "fixtura plik_sesji zasięgu session",
                "ZMIENNA_SESJI",
            )
            if owner in message
        ]
        for name, message in errors.items()
        if message
    }
    causes = {
        case.attrib["name"]: [
            cause
            for cause in ("sprzątanie bez zasobu", "teardown fixtury pada", "direct cause")
            if any(cause in (element.text or "") for element in case if element.tag == "error")
        ]
        for case in ET.parse(report / "junit.xml").iter("testcase")
        if case.attrib["name"].startswith("test_teardown_")
    }
    assert (owners, causes) == ({
        "test_z_fixtura_funkcji": ["on teardown", "funkcja.bin"],
        "test_cialo_zostawia_plik": ["on teardown", "cialo.bin"],
        "test_setup_pada": ["on setup", "on teardown", "przed_bledem.bin"],
        "test_ostatni_w_module": ["on teardown", "modul.bin", "fixtura plik_modulu zasięgu module"],
        "test_z_parametrem[dwa]": ["on setup", "jeden.bin", "fixtura plik_parametru zasięgu module"],
        "test_jedyny_w_module": ["on teardown", "samotny.bin", "fixtura plik_samotnego zasięgu module"],
        "test_teardown_skip": ["on teardown", "skip.bin", "fixtura plik_skip zasięgu module"],
        "test_teardown_rzuca": ["on teardown", "rzuca.bin", "fixtura plik_rzuca zasięgu module"],
        "test_sasiad_zbiera_ostrzezenia": ["on teardown", "sesja.bin", "fixtura plik_sesji zasięgu session"],
    }, {
        "test_teardown_skip": ["sprzątanie bez zasobu", "direct cause"],
        "test_teardown_rzuca": ["teardown fixtury pada", "direct cause"],
    }), errors


_LUKI_CONFTEST: Final = _CONFTEST + """

import threading
import queue

# Wątek starszy od każdego testu: uruchamia wątek bez końca na prośbę testu.
PROSBY = queue.Queue()


def _rozdziela():
    while True:
        PROSBY.get()
        threading.Thread(target=threading.Event().wait, name="watek-starszego-watku", daemon=True).start()


threading.Thread(target=_rozdziela, name="rozdzielacz", daemon=True).start()
"""

ZNANE_LUKI: Final = {
    "stan sterty Pythona: atrybut modułu zmieniony bez monkeypatch": """
    import json
    json.ZMIENIONE_PRZEZ_TEST = True
""",
    "wątek, który kończy się w ciągu WATEK_S po teście": """
    import threading
    threading.Thread(target=threading.Event().wait, args=(0.2,), name="krotki", daemon=True).start()
""",
    "wątek, który uruchomił wątek starszy od testu (fixtura albo moduł)": """
    from conftest import PROSBY
    PROSBY.put(1)
""",
    "proces potomny zakończony, na który nikt nie czekał (zombie)": """
    import subprocess, sys
    TRZYMANE.append(subprocess.Popen([sys.executable, "-c", ""]))
""",
    "plik w katalogu roboczym procesu, czyli w drzewie repozytorium (stan wspólny workerów porównuje sesja)": """
    from pathlib import Path
    Path("debug.log").write_text("x", encoding="utf-8")
""",
}


def test_znane_luki_porownania_stanu_procesu_przechodza_przez_plugin(tmp_path: Path) -> None:
    names = {opis: f"test_luka_{number}" for number, opis in enumerate(ZNANE_LUKI)}
    text = "TRZYMANE = []\n" + "".join(f"\n\ndef {names[opis]}():{body}" for opis, body in ZNANE_LUKI.items())
    errors = _sesja(tmp_path, {"test_luki.py": text}, _LUKI_CONFTEST)

    assert_znane_luki({opis: [errors[name]] if errors[name] else [] for opis, name in names.items()}, "tests/test_stan_procesu.py")


@pytest.mark.skipif(sys.platform == "win32", reason="deskryptory plugin listuje tylko na Linuksie i macOS")
def test_ostrzezenie_smiecia_sprzed_testu_idzie_dalej_a_obserwowanego_deskryptora_zastepuje_wynik(tmp_path: Path) -> None:
    # gc.collect() pluginu zbiera też śmieć sprzed testu; jego ResourceWarning nie może zniknąć w pluginie.
    stary, nowy = tmp_path / "stary.bin", tmp_path / "nowy.bin"
    stary.write_bytes(b"x")
    nowy.write_bytes(b"x")

    gc.disable()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cykl: list[object] = [stary.open("rb")]
            cykl.append(cykl)
            before = descriptors()
            cykl = [nowy.open("rb")]
            cykl.append(cykl)
            del cykl
            left = left_to_gc(descriptors() - before)
    finally:
        gc.enable()

    unclosed = [str(warning.message) for warning in caught if issubclass(warning.category, ResourceWarning)]
    # Plik w cyklu ostrzega z bufora albo z io.FileIO, zależnie od tego, który finalizer gc puści pierwszy.
    assert (len(left), [(stary.name in message, nowy.name in message) for message in unclosed]) == (1, [(True, False)])
