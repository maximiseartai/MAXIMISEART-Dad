"""Stan procesu, który test zostawił następnemu testowi (``tests/fixtures/stan_procesu.py``, #1923, #1783)."""

from __future__ import annotations

from collections.abc import Mapping
import gc
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Final
import warnings
from xml.etree import ElementTree as ET

import pytest

from tests.fixtures.stan_procesu import WATEK_S, descriptors, left_to_gc
from tests.fixtures.znane_luki import assert_znane_luki

import box_boat

ROOT: Final = Path(__file__).resolve().parents[1]

# Plugin w procesie pytest sesji próbek, z krótszym czekaniem na potomków niż w repozytorium.
_CONFTEST: Final = """
import pytest

import tests.fixtures.stan_procesu as stan_procesu

pytest_plugins = ["tests.fixtures.stan_procesu"]
stan_procesu.POTOMEK_S = 1.0


def plik_w_cyklu(path):
    path.write_bytes(b"x")
    cykl = [open(path, "rb")]  # bez close(): wyciek fixtury
    cykl.append(cykl)
    return cykl
"""


def _sesja(
    tmp_path: Path, pliki: Mapping[str, str], conftest: str = _CONFTEST, *, katalog: str = ".", kody: list[int] | None = None
) -> dict[str, str]:
    """Raport błędu albo porażki każdego testu sesji próbek z plików ``pliki``, w prawdziwym cyklu życia testu w
    osobnym procesie pytest: pierwsza linia to fazy błędów (``on setup``, ``on teardown``), dalej pełny raport z treści
    elementu JUnit, bo atrybut ``message`` pytest 9 skraca do 500 znaków; test bez błędu ma pusty raport. Sesja biegnie
    w ``tmp_path / katalog`` z conftest i plikami próbek, a raport JUnit i ``--basetemp`` leżą w ``tmp_path``; kod
    wyjścia sesji trafia do ``kody``."""

    sesja = tmp_path / katalog
    sesja.mkdir(exist_ok=True)
    (sesja / "conftest.py").write_text(conftest, encoding="utf-8")
    for name, text in pliki.items():
        (sesja / name).write_text(text, encoding="utf-8")
    report = tmp_path / "junit.xml"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", f"--basetemp={tmp_path / 'tmp'}"]
        + ["-p", "no:randomly", f"--junitxml={report}", "-o", "junit_family=xunit1", *pliki],
        cwd=sesja,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "tools/lib")])},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )
    assert report.exists(), done.stdout + done.stderr
    if kody is not None:
        kody.append(done.returncode)
    reports: dict[str, str] = {}
    for case in ET.parse(report).iter("testcase"):
        failed = [element for element in case if element.tag in ("error", "failure")]
        phases = [
            match.group(0) for element in failed if (match := re.search(r"on (setup|teardown)", element.get("message", "")))
        ]
        texts = [element.text or "" for element in failed]
        reports[case.attrib["name"]] = "\n".join([" ".join(phases), *texts]) if failed else ""
    return reports


_KOMUNIKAT: Final = re.compile(
    r"AssertionError: Test albo jego fixtura zostawiły procesowi workera stan, który działa w oknie następnego testu: "
    r"(.*?)\. Zamknij plik"
)


def _zostawione(report: str) -> str:
    """Części komunikatów pluginu w raporcie ``_sesja`` z tym, co test zostawił, bez rady, jak to naprawić."""

    return "; ".join(_KOMUNIKAT.findall(report))


def _fazy_i_zostawione(report: str) -> str:
    return report.partition("\n")[0] + " " + _zostawione(report)


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


def test_katalog_roboczy_usuniety(tmp_path):
    usuwany = tmp_path / "usuwany"
    usuwany.mkdir()
    os.chdir(usuwany)
    usuwany.rmdir()
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
                f"wątek watek-bez-konca żyje {WATEK_S:g} s po teście",
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
        "test_watek_bez_konca": [f"wątek watek-bez-konca żyje {WATEK_S:g} s po teście"],
        "test_proces_potomny_bez_konca": ["potok", "otwarty po teście", "proces potomny"],
        "test_katalog_roboczy": ["katalog roboczy"],
        "test_zmienna_srodowiska": ["zmienna środowiska ZMIENNA_SPRAWCY zmieniona"],
        "test_katalog_roboczy_usuniety": ["katalog roboczy"],
    }, ""), errors
    assert "→ katalog usunięty" in _zostawione(errors["test_katalog_roboczy_usuniety"]), errors


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
import os

import pytest
from conftest import plik_w_cyklu


@pytest.fixture(scope="module", params=["jeden", "dwa"])
def plik_parametru(request, tmp_path_factory):
    stan = [plik_w_cyklu(tmp_path_factory.mktemp(request.param) / f"{request.param}.bin")]
    if request.param == "jeden":
        os.environ["ZMIENNA_JEDEN"] = "1"  # bez przywrócenia: sprawdzenie przy zmianie parametru ją wraca
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
                "ZMIENNA_JEDEN",
            )
            if owner in _fazy_i_zostawione(message)
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
        "test_z_parametrem[dwa]": ["on setup", "jeden.bin", "fixtura plik_parametru zasięgu module", "ZMIENNA_JEDEN"],
        "test_jedyny_w_module": ["on teardown", "samotny.bin", "fixtura plik_samotnego zasięgu module"],
        "test_teardown_skip": ["on teardown", "skip.bin", "fixtura plik_skip zasięgu module"],
        "test_teardown_rzuca": ["on teardown", "rzuca.bin", "fixtura plik_rzuca zasięgu module"],
        "test_sasiad_zbiera_ostrzezenia": ["on teardown", "sesja.bin", "fixtura plik_sesji zasięgu session"],
    }, {
        "test_teardown_skip": ["sprzątanie bez zasobu", "direct cause"],
        "test_teardown_rzuca": ["teardown fixtury pada", "direct cause"],
    }), errors


# Fixtura modułu zmienia w setupie każdy rodzaj stanu procesu. Czysta sprząta go na końcu, więc nie wywraca żadnego
# testu, także gdy zmienia katalog roboczy; test, który pod nią znów zmienia jej katalog i zmienną, pada sam, a plugin
# wraca do wartości fixtury, także pod fixturą klasy, która zmienia tę samą zmienną i przywraca ją na swoim końcu.
# Czysta fixtura modułu, która bierze fixturę sesji przez request.getfixturevalue, nie przejmuje jej stanu, więc ani jej
# ostatni test, ani sąsiad z tą fixturą sesji w innym module nie padają, a jej zmienna, zmieniona przed fixturą sesji i
# po niej, wraca na jej końcu do wartości sprzed pierwszej zmiany, także gdy pytest w jej środku zmienia parametr innej
# fixtury. Stan setupu, który padł, należy do testu. Test, który usuwa katalog roboczy żywej fixtury,
# pada sam z nazwanym katalogiem. Brudna nie sprząta, więc wywraca ostatni test modułu z nazwą fixtury, a plugin przywraca katalog i środowisko, zanim
# zacznie się sąsiad. Wątek testu, który zamyka plik zaraz po teście, nie zostawia stanu.
_RODZAJ_FIXTURY: Final = """
import os
import subprocess
import sys
import threading

import pytest

TRZYMANE = []


def zmienia_kazdy_rodzaj(katalog, nazwa):
    plik = open(katalog / f"{nazwa}.bin", "wb")
    potomek = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    stop = threading.Event()
    watek = threading.Thread(target=stop.wait, name=f"watek-{nazwa}", daemon=True)
    watek.start()
    return plik, potomek, stop, watek
"""
_RODZAJE_FIXTUR: Final = {
    "test_a_czysta.py": _RODZAJ_FIXTURY
    + """

@pytest.fixture(scope="module")
def czysta_modulu(tmp_path_factory):
    katalog = tmp_path_factory.mktemp("czysta")
    plik, potomek, stop, watek = zmienia_kazdy_rodzaj(katalog, "czysta")
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(katalog)
        patch.setenv("ZMIENNA_CZYSTEJ", "1")
        yield
    stop.set()
    watek.join()
    potomek.stdin.close()
    potomek.wait()
    plik.close()


def test_pierwszy_z_czysta(czysta_modulu):
    assert os.environ["ZMIENNA_CZYSTEJ"] == "1"


def test_sprawca_pod_czysta_zmienia_jej_katalog_i_zmienna(czysta_modulu, tmp_path):
    os.chdir(tmp_path)
    os.environ["ZMIENNA_CZYSTEJ"] = "2"


class TestZagniezdzonaKlasa:
    @pytest.fixture(scope="class")
    def klasa_nad_czysta(self, czysta_modulu):
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("ZMIENNA_CZYSTEJ", "klasa")
            yield

    def test_w_klasie(self, klasa_nad_czysta):
        assert os.environ["ZMIENNA_CZYSTEJ"] == "klasa"


def test_drugi_z_czysta_ma_jej_katalog_i_zmienna(czysta_modulu):
    assert (os.getcwd().endswith("czysta0"), os.environ["ZMIENNA_CZYSTEJ"]) == (True, "1")


def test_watek_zamyka_plik_zaraz_po_tescie(tmp_path):
    plik = open(tmp_path / "krotki.bin", "wb")
    zamknij = threading.Event()

    def zamyka():
        zamknij.wait(0.3)
        plik.close()

    threading.Thread(target=zamyka, daemon=True).start()
""",
    "test_a_rozdzielacz.py": """
import queue
import threading

import pytest


@pytest.fixture(scope="module")
def rozdzielacz_modulu():
    prosby, stop, uruchomiony = queue.Queue(), threading.Event(), threading.Event()
    watki = []

    def rozdziela():
        while prosby.get():
            watek = threading.Thread(target=stop.wait, name="watek-rozdzielacza", daemon=True)
            watek.start()
            watki.append(watek)
            uruchomiony.set()

    rozdzielacz = threading.Thread(target=rozdziela, name="rozdzielacz", daemon=True)
    rozdzielacz.start()
    yield prosby, uruchomiony
    stop.set()
    prosby.put(False)
    rozdzielacz.join()
    for watek in watki:
        watek.join()


def test_watek_fixtury_uruchamia_watek_w_pierwszym_tescie(rozdzielacz_modulu):
    prosby, uruchomiony = rozdzielacz_modulu
    prosby.put(True)
    assert uruchomiony.wait(10)


def test_drugi_z_rozdzielaczem(rozdzielacz_modulu):
    pass
""",
    "test_a_zagniezdzona.py": """
import pytest


@pytest.fixture(scope="module")
def modul_z_sesja(request):
    # Ta sama zmienna przed fixturą sesji i po niej, przywrócona na końcu do stanu sprzed pierwszej zmiany.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ZMIENNA_MODULU_ZAGN", "przed")
        sesja = request.getfixturevalue("ustawienia_sesji")
        patch.setenv("ZMIENNA_MODULU_ZAGN", "po")
        yield sesja


def test_pierwszy_z_zagniezdzona(modul_z_sesja):
    assert modul_z_sesja == "sesja"


def test_ostatni_z_zagniezdzona(modul_z_sesja):
    assert modul_z_sesja == "sesja"
""",
    "test_a_param_w_zagniezdzeniu.py": """
import pytest


@pytest.fixture(scope="module")
def parametr(request):
    return request.param


@pytest.fixture(scope="module")
def z_parametrem(request):
    # Czysta fixtura modułu zmienia zmienną, a potem bierze fixturę z parametrem, którą pytest wtedy zmienia.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ZMIENNA_PRZED_PARAMETREM", "1")
        yield request.getfixturevalue("parametr")


@pytest.mark.parametrize("parametr", [1], indirect=True)
def test_pierwszy_parametr(parametr):
    assert parametr == 1


@pytest.mark.parametrize("parametr", [2], indirect=True)
def test_drugi_parametr_w_zagniezdzeniu(z_parametrem, parametr):
    assert (z_parametrem, parametr) == (2, 2)
""",
    "test_a_padly_setup.py": """
import os

import pytest


@pytest.fixture(scope="module")
def padly_setup():
    os.environ["ZMIENNA_PADLEGO_SETUPU"] = "1"
    raise RuntimeError("setup fixtury pada")


def test_z_padlym_setupem(padly_setup):
    pass
""",
    "test_a_usuwa_katalog_fixtury.py": """
import os
import shutil
import sys

import pytest


@pytest.fixture(scope="module")
def w_katalogu(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(tmp_path_factory.mktemp("usuwany_fixtury"))
        yield


def test_sprawca_usuwa_katalog_fixtury(w_katalogu):
    if sys.platform == "win32":
        pytest.skip("Windows nie usuwa katalogu roboczego procesu")
    shutil.rmtree(os.getcwd())


def test_drugi_w_katalogu_fixtury(w_katalogu):
    pass
""",
    "test_b_brudna.py": _RODZAJ_FIXTURY
    + """

@pytest.fixture(scope="module")
def brudna_modulu(tmp_path_factory):
    katalog = tmp_path_factory.mktemp("brudna")
    TRZYMANE.append(zmienia_kazdy_rodzaj(katalog, "brudna"))
    os.chdir(katalog)
    os.environ["ZMIENNA_BRUDNEJ"] = "1"
    yield


def test_pierwszy_z_brudna(brudna_modulu):
    pass


def test_drugi_z_brudna(brudna_modulu):
    pass
""",
    "test_c_sasiad.py": """
import os


def test_sasiad_z_sesja_w_innym_module(ustawienia_sesji):
    assert os.environ.get("ZMIENNA_SESJI_ZAGN") == "sesja"


def test_sasiad_ma_katalog_i_srodowisko_sprzed_fixtury(request):
    assert (os.getcwd(), os.environ.get("ZMIENNA_BRUDNEJ")) == (str(request.config.invocation_params.dir), None)
""",
}


_SESJA_ZAGNIEZDZONA: Final = """

@pytest.fixture(scope="session")
def ustawienia_sesji():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ZMIENNA_SESJI_ZAGN", "sesja")
        yield "sesja"
"""


def test_kazdy_rodzaj_stanu_z_setupu_fixtury_modulu_nalezy_do_niej_do_jej_konca(tmp_path: Path) -> None:
    errors = _sesja(tmp_path, _RODZAJE_FIXTUR, _CONFTEST + _SESJA_ZAGNIEZDZONA)
    deleted = _zostawione(errors.pop("test_sprawca_usuwa_katalog_fixtury"))
    failed_setup = errors.pop("test_z_padlym_setupem")
    dirty = _zostawione(errors.pop("test_drugi_z_brudna"))
    culprit = _zostawione(errors.pop("test_sprawca_pod_czysta_zmienia_jej_katalog_i_zmienna"))
    kinds = (
        *(("brudna.bin otwarty po teście", "potok", "proces potomny") if sys.platform != "win32" else ()),
        f"wątek watek-brudna żyje {WATEK_S:g} s po teście",
        "katalog roboczy",
        "zmienna środowiska ZMIENNA_BRUDNEJ zmieniona",
    )

    assert (
        errors,
        [kind for kind in kinds if kind in dirty],
        dirty.count("fixtura brudna_modulu zasięgu module"),
        [part.split(" → ")[0] for part in culprit.split("; ")],
        ("→ katalog usunięty (katalogu oczekiwanego już nie ma)" in deleted, "fixtura" in deleted),
        _zostawione(failed_setup),
    ) == (
        {name: "" for name in errors},
        list(kinds),
        len(kinds),
        [f"katalog roboczy {tmp_path / 'tmp' / 'czysta0'}", "zmienna środowiska ZMIENNA_CZYSTEJ zmieniona"],
        (sys.platform != "win32", False),
        "zmienna środowiska ZMIENNA_PADLEGO_SETUPU zmieniona",
    ), (dirty, culprit, deleted, failed_setup, errors)


# Box boat po załadowaniu dysku przenosi drzewo z katalogiem repo pod box_boat.KATALOG_ZWOLNIONY, gdy testy w nim
# biegną, a pod starą ścieżką stawia pełne drzewo: katalog roboczy procesu idzie za przeniesionym katalogiem. Próbka
# przenosi katalog sesji tak samo (rename) pod katalog zwolniony podstawiony w conftest i stawia nowy pod starą ścieżką.
_PRZENIESIENIE_BOXA: Final = {
    "test_przeniesienie.py": """
import os
from pathlib import Path

import box_boat


def test_box_przenosi_katalog_repo_w_trakcie_testu(po_tescie):
    repo = Path.cwd()
    przeniesiony = Path(box_boat.KATALOG_ZWOLNIONY, "home", repo.name)
    przeniesiony.parent.mkdir(parents=True)
    os.rename(repo, przeniesiony)
    repo.mkdir()


def test_sasiad_biegnie_w_katalogu_repo(request):
    assert os.getcwd() == str(request.config.invocation_params.dir)
""",
}


# Fixtura testu przeniesienia: bez błędu, a w próbce prawdziwej porażki teardownu z własnym błędem po teście.
_PO_TESCIE: Final = """


@pytest.fixture
def po_tescie():
    yield
"""
_PADLY_TEARDOWN: Final = """


@pytest.fixture
def po_tescie():
    yield
    raise RuntimeError("prawdziwy błąd teardownu fixtury")
"""
_ZOSTAWIONA_ZMIENNA: Final = """


@pytest.fixture
def po_tescie():
    import os

    os.environ["ZMIENNA_ZOSTAWIONA"] = "1"
    yield
"""
# Porażka sesji spoza raportów testów, jak DRZEWO REPO w tests/conftest.py.
_PORAZKA_SESJI: Final = """


def pytest_sessionfinish(session):
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
"""


@pytest.mark.skipif(sys.platform == "win32", reason="Windows nie przenosi katalogu roboczego procesu")
@pytest.mark.parametrize(
    ("dodatkowe", "sesji", "kod", "zostawione"),
    [
        ({}, "", box_boat.KOD_WYJSCIA, ""),
        ({"test_zwykly.py": "def test_zwykly():\n    assert len('ab') == 3\n"}, "", 1, ""),
        ({}, _PORAZKA_SESJI, 1, ""),
        ({}, _PADLY_TEARDOWN, 1, ""),
        ({}, _ZOSTAWIONA_ZMIENNA, 1, "zmienna środowiska ZMIENNA_ZOSTAWIONA zmieniona"),
    ],
    ids=[
        "tylko-box",
        "box-i-zwykla-porazka",
        "box-i-porazka-sesji",
        "box-i-padly-teardown",
        "box-i-zostawiona-zmienna",
    ],
)
def test_katalog_repo_przeniesiony_przez_box_to_komunikat_boxa_a_sesja_tylko_z_nim_konczy_sie_kodem_boxa(
    tmp_path: Path, dodatkowe: dict[str, str], sesji: str, kod: int, zostawione: str
) -> None:
    zwolniony = tmp_path.resolve() / "retired"
    conftest = _CONFTEST + f"\nimport box_boat\n\nbox_boat.KATALOG_ZWOLNIONY = {str(zwolniony) + os.sep!r}\n" + _PO_TESCIE + sesji
    kody: list[int] = []

    errors = _sesja(tmp_path, {**_PRZENIESIENIE_BOXA, **dodatkowe}, conftest, katalog="repo", kody=kody)

    moved = errors["test_box_przenosi_katalog_repo_w_trakcie_testu"]
    expected = f"{box_boat.KOMUNIKAT} (katalog roboczy {tmp_path.resolve() / 'repo'} → {zwolniony / 'home' / 'repo'})"
    assert (expected in moved, _zostawione(moved), errors["test_sasiad_biegnie_w_katalogu_repo"], kody) == (
        True,
        zostawione,
        "",
        [kod],
    ), errors


def test_kod_boxa_ma_tylko_sesja_z_porazka_testow_ktorej_kazda_porazka_to_box() -> None:
    przypadki = {
        "tylko box": (1, [True]),
        "box i inna porażka": (1, [True, False]),
        "padła bez raportu (DRZEWO REPO)": (1, []),
        "przerwana innym kodem": (3, [True]),
        "przeszła": (0, []),
    }

    kody = {nazwa: box_boat.kod_sesji(kod, porazki) for nazwa, (kod, porazki) in przypadki.items()}

    assert kody == {
        "tylko box": box_boat.KOD_WYJSCIA,
        "box i inna porażka": 1,
        "padła bez raportu (DRZEWO REPO)": 1,
        "przerwana innym kodem": 3,
        "przeszła": 0,
    }


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
    "maska uprawnień nowych plików (umask) zmieniona bez przywrócenia": """
    import os
    os.umask(0o077)
""",
    "dyspozycja sygnału zmieniona bez przywrócenia": """
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
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
