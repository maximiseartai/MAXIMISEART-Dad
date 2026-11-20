"""Drive Centrum rozliczeń w ``verify-centrum-rozliczen``: limit zawieszenia i droga każdego zrzutu.

Drive uznaje się za zawieszony dopiero po limicie, który rośnie z liczbą przejeżdżanych funkcji, więc nowa funkcja nie
wypycha ``--feature all`` poza stały limit kroku.

Każdy zrzut drive'u idzie przez ``Run.capture``, które przyjmuje tylko zrzut z ``screenshots`` jego funkcji w
``FEATURES``, gdzie jeden numer zrzutu należy do jednej funkcji (pliki funkcji i PR-y cytują zrzut po numerze); zrzut
prosto przez ``screenshot`` tę regułę omijał (#783: zbliżenia 170b i 181b). Test czyta kod drive'u, nie uruchamia go, więc łapie też zrzut z rzadko jeżdżącej ścieżki; nie łapie zrzutu
wywołanego bez atrybutu ``screenshot`` (``getattr``).

Czekanie drive'u (``until`` z ``drive/waiting.py``) przeczekuje plik, który serwer albo
jego wątek jeszcze pisze: brak pliku, pusty, w połowie zapisany i chwilowo bez prawa odczytu to stan „jeszcze nie”, a
każdy inny błąd i plik, który po budżecie wciąż nie jest gotowy, kończą przebieg komunikatem (#1651, #1539). Stany
pliku zmienia sam odczyt warunku, nie zegar.

Nakładka napędu (``Run.refusing_text_settings_writes``) odmawia otwarcia pliku Ustawień runu do zapisu tekstem; postacie,
które przepuszcza, są próbkami ``ZNANE_LUKI_ZAPISU_TEKSTEM``.
"""

from __future__ import annotations

import ast
import asyncio
from collections import deque
from collections.abc import Callable, Iterator
import contextlib
from contextlib import contextmanager
from functools import partial
import importlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Final

import playwright.sync_api
from playwright.sync_api import Error as PlaywrightError
import pytest
import yaml

from atrapy.pliki_taty import UPDATE_RESULT_FILE
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.efenix_browser import launch_options
from rozliczenia.tool_files import config_dir
from tests.fixtures.znane_luki import assert_znane_luki, modul, zapisz

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts"
DRIVE = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "drive"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("run_centrum_verification", SCRIPTS / "run_centrum_verification.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drive_wszystkich_funkcji_ma_limit_rosnacy_z_liczba_funkcji_a_jedna_funkcja_staly(runner: ModuleType) -> None:
    every = runner.driven("all", {})

    # all trwał w CI 280–305 s, a padał na stałych 300 s (runy 40309201075, 40322305317): limit daje mu co najmniej
    # dwa razy tyle i rośnie z każdą funkcją.
    assert runner.drive_timeout_s(every) == runner.DRIVE_SECONDS_PER_FEATURE * len(every) >= 2 * 305
    assert runner.drive_timeout_s((every[0],)) == runner.STEP_TIMEOUT_SECONDS
    assert runner.drive_timeout_s(("wydajnosc",)) == runner.PERFORMANCE_TIMEOUT_SECONDS


def _screenshots_outside_capture(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed: set[int] = set()
    if path.name == "common.py":
        run = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Run")
        capture = next(node for node in run.body if isinstance(node, ast.FunctionDef) and node.name == "capture")
        allowed = {id(node) for node in ast.walk(capture)}
    return [
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "screenshot"
        and id(node) not in allowed
    ]


def test_zrzut_w_drive_centrum_idzie_tylko_przez_run_capture() -> None:
    modules = sorted(DRIVE.glob("*.py"))
    assert DRIVE / "common.py" in modules

    found = [place for module in modules for place in _screenshots_outside_capture(module)]

    assert found == [], (
        "zrzut prosto przez screenshot omija regułę numerów zrzutów; użyj run.capture(page, name, clip=…) "
        f"z drive/common.py: {found}"
    )


@pytest.mark.parametrize("failure", ["DriveFailure", "TimedOut"])
def test_nieudany_zrzut_po_bledzie_drive_nie_zastepuje_przyczyny_bledu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    """Po błędzie funkcji drive robi zrzut ``zz-failure.png``; gdy przeglądarka już padła, zrzut też pada, a ``DRIVE FAIL``
    dalej podaje błąd funkcji, z dopiskiem, że zrzutu nie ma. Czekanie ``until`` po budżecie (``TimedOut``) to też linia
    ``DRIVE FAIL``, a nie traceback (przegląd #1703, D1)."""

    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("drive_centrum", SCRIPTS / "drive_centrum.py")
    assert spec is not None and spec.loader is not None
    drive_centrum = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drive_centrum)

    class ClosedPage:
        def set_default_timeout(self, timeout: float) -> None:
            pass

        def screenshot(self, **options: object) -> bytes:
            raise PlaywrightError("Target page, context or browser has been closed")

    class Browser:
        def new_context(self, **options: object) -> SimpleNamespace:
            return SimpleNamespace(new_page=ClosedPage, add_init_script=lambda script: None, on=lambda event, handler: None)

        contexts: tuple[object, ...] = ()

        def close(self) -> None:
            pass

    @contextmanager
    def playwright() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(chromium=SimpleNamespace(launch=Browser))

    def failing(run: object, page: object) -> None:
        raise getattr(drive_centrum, failure)("funkcja nie zobaczyła przycisku")

    # Atrapa przeglądarki nie ma linii poleceń, z której launch_options bierze listę funkcji wyłączonych przez Playwright.
    monkeypatch.setattr(drive_centrum, "launch_options", lambda playwright: {})
    monkeypatch.setattr(drive_centrum, "sync_playwright", playwright)
    monkeypatch.setitem(drive_centrum.MODULES, "ustawienia", SimpleNamespace(drive=failing))
    (tmp_path / "fixture.json").write_text("{}", encoding="utf-8")
    arguments = ["--root", str(tmp_path), "--url", "http://127.0.0.1:9", "--evidence", str(tmp_path / "dowody")]

    code = drive_centrum.main([*arguments, "--feature", "ustawienia"])

    [line] = capsys.readouterr().err.splitlines()
    assert code == 1
    assert line.startswith("DRIVE FAIL | funkcja nie zobaczyła przycisku | zz-failure.png not taken: "), line


@pytest.fixture
def common(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return importlib.import_module("drive.common")


def _run(common: ModuleType, tmp_path: Path) -> Any:
    """Przebieg drive'u z katalogiem ``config/`` obok pliku Ustawień, jak w przygotowanym folderze okresów."""

    root = tmp_path / "run"
    config_dir(root).mkdir(parents=True)
    settings = config_dir(root) / SETTINGS_FILE
    (root / "fixture.json").write_text(json.dumps({"settings": str(settings)}), encoding="utf-8")
    return common.Run(root, "http://127.0.0.1:1/", tmp_path / "dowody")


def _refused(path: Path) -> object:
    """Windows na chwilę odmawia odczytu pliku, który serwer właśnie podmienia (#1087)."""

    raise PermissionError(13, "Permission denied", str(path))


# Znane luki czekania ``until`` (tests/fixtures/znane_luki.py): klasa mechanizmu → moduł z predykatem ``gotowe``, który
# zwraca leniwy iterator bez żadnego elementu. ``until`` czeka, dopóki wartość nie jest prawdziwa, a leniwy iterator jest
# prawdziwy, zanim cokolwiek odda, więc czekanie kończy się od razu; dziś żadne wywołanie napędu go nie zwraca (#1857 r3).
ZNANE_LUKI_UNTIL: Final = {
    "leniwy iterator jest prawdziwy, zanim cokolwiek odda: pusty generator": "def gotowe():\n    return (wpis for wpis in [])\n",
    "leniwy iterator jest prawdziwy, zanim cokolwiek odda: filter": "def gotowe():\n    return filter(None, [])\n",
    "leniwy iterator jest prawdziwy, zanim cokolwiek odda: map": "def gotowe():\n    return map(str, [])\n",
    "leniwy iterator jest prawdziwy, zanim cokolwiek odda: iter": "def gotowe():\n    return iter([])\n",
}


def test_znane_luki_czekania_until_przechodza_przez_until(common: ModuleType, tmp_path: Path) -> None:
    waiting = importlib.import_module("drive.waiting")
    zgloszenia: dict[str, list[str]] = {}
    for opis, plik in zapisz(ZNANE_LUKI_UNTIL, tmp_path).items():
        zgloszenia[opis] = []
        try:
            waiting.until(modul(plik).gotowe, "the first entry comes", 0.3)
        except waiting.TimedOut:
            zgloszenia[opis].append("until czeka na pierwszy element leniwego iteratora")

    assert_znane_luki(zgloszenia, "tests/test_limit_drive_centrum.py (ZNANE_LUKI_UNTIL)")


def test_logi_dwoch_uruchomien_w_jednej_sekundzie_ostatnie_to_pozniej_rozpoczete_a_nie_dalsze_w_nazwie(
    common: ModuleType, tmp_path: Path
) -> None:
    """Nazwa pliku Logów ma start do sekundy i losowy id, więc dwa Uruchomienia w jednej sekundzie (szybki runner
    Windows, CI 44194162002) sortują się po nazwie odwrotnie co trzeci raz; ``[-1]`` napędu ma być późniejszym."""

    run = _run(common, tmp_path)
    run.run_logs_dir.mkdir(parents=True)
    for run_id, started, ended in [
        ("96b82ef9", "2026-11-17T22:55:33.182448Z", "2026-11-17T22:55:33.210000Z"),
        ("50346d26", "2026-11-17T22:55:33.853516Z", "2026-11-17T22:55:33.880951Z"),
        ("0a000000", "2026-11-17T22:55:33.853516Z", "2026-11-17T22:55:33.990000Z"),
    ]:
        logged = {"run_id": run_id, "started_at": started, "ended_at": ended}
        (run.run_logs_dir / f"20261117T225533Z-report_entering-{run_id}.json").write_text(json.dumps(logged), encoding="utf-8")

    assert [logged["run_id"] for logged in common.run_logs(run, "report_entering").values()] == [
        "96b82ef9",
        "50346d26",
        "0a000000",
    ]


# Znane luki nakładki ``Run.refusing_text_settings_writes`` (tests/fixtures/znane_luki.py): klasa mechanizmu → moduł z
# ``zapis(path)``, który pisze plik Ustawień runu tekstem, a nakładka go przepuszcza. Nakładka odmawia tylko otwarcia
# do zapisu tekstem przez ``io.open`` i ``os.open`` procesu napędu pliku o tożsamości pliku Ustawień w chwili otwarcia
# albo o nazwie jego czy jego ``.zapis`` w jego folderze; na Windows takie zapisy łapie potem
# ``Run.refuse_cr_in_settings``, o ile serwer nie nadpisze pliku przed nim.
ZNANE_LUKI_ZAPISU_TEKSTEM: Final = {
    "nakładka zna tylko plik, który się otwiera: tekst do innego pliku przeniesiony na plik Ustawień": "import os\n\n\n"
    + "def zapis(path):\n    obok = path.with_name('ustawienia.tmp')\n"
    + "    obok.write_text('schema_version: 1\\n', encoding='utf-8')\n    os.replace(obok, path)\n",
    "nakładka żyje w io.open i os.open procesu napędu: tekst owinięty na uchwyt bajtów": "import io\n\n\n"
    + "def zapis(path):\n    with open(path, 'wb') as bajty, io.TextIOWrapper(bajty, encoding='utf-8') as tekst:\n"
    + "        tekst.write('schema_version: 1\\n')\n",
    "nakładka żyje w io.open i os.open procesu napędu: _io.open, z którego io.open pochodzi": "import _io\n\n\n"
    + "def zapis(path):\n    with _io.open(path, 'w', encoding='utf-8') as tekst:\n"
    + "        tekst.write('schema_version: 1\\n')\n",
    "nakładka żyje w io.open i os.open procesu napędu: proces potomny": "import subprocess\nimport sys\n\n\n"
    + "def zapis(path):\n    kod = 'import sys; open(sys.argv[1], \"w\", encoding=\"utf-8\").write(\"schema_version: 1\\\\n\")'\n"
    + "    subprocess.run([sys.executable, '-c', kod, str(path)], check=True)\n",
}


def test_znane_luki_zapisu_tekstem_pliku_ustawien_przechodza_przez_nakladke_napedu(common: ModuleType, tmp_path: Path) -> None:
    run = _run(common, tmp_path)
    settings = Path(run.fixture["settings"])
    zapisy = {opis: modul(plik).zapis for opis, plik in zapisz(ZNANE_LUKI_ZAPISU_TEKSTEM, tmp_path).items()}
    zgloszenia: dict[str, list[str]] = {}
    with run.refusing_text_settings_writes():
        for opis, zapis in zapisy.items():
            zgloszenia[opis] = []
            try:
                zapis(settings)
            except common.DriveFailure as odmowa:
                zgloszenia[opis].append(f"nakładka odmawia: {odmowa}")
            else:
                assert settings.read_bytes() == f"schema_version: 1{os.linesep}".encode(), opis

    assert_znane_luki(zgloszenia, "tests/test_limit_drive_centrum.py (ZNANE_LUKI_ZAPISU_TEKSTEM)")


@pytest.mark.parametrize("chwila", ["Run.api", "koniec funkcji"])
def test_plik_ustawien_z_cr_konczy_naped_przy_run_api_i_po_funkcji(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chwila: str
) -> None:
    """Druga siatka ``Run.refuse_cr_in_settings`` biegnie przy każdym ``Run.api`` i po napędzie każdej funkcji
    (``drive_centrum.drive``): plik Ustawień z ``\\r`` (zapis tekstem na Windows, którego nakładka nie widzi) kończy napęd
    tam, zanim cokolwiek przeczyta plik albo odpowiedź serwera (przegląd #1913 r3, D1)."""

    run = _run(common, tmp_path)
    settings = Path(run.fixture["settings"])

    def zapis_tekstem_na_windows(*argumenty: object) -> None:
        settings.write_bytes(b"schema_version: 1\r\n")

    spec = importlib.util.spec_from_file_location("drive_centrum", SCRIPTS / "drive_centrum.py")
    assert spec is not None and spec.loader is not None
    drive_centrum = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drive_centrum)
    monkeypatch.setitem(drive_centrum.MODULES, "ustawienia", SimpleNamespace(drive=zapis_tekstem_na_windows))
    okna = SimpleNamespace(open=lambda run: contextlib.nullcontext(object()))
    kroki: dict[str, Callable[[], object]] = {
        "Run.api": partial(run.api, "/api/ustawienia", "ustawienia"),
        "koniec funkcji": partial(drive_centrum.drive, run, okna, "ustawienia", [], {}, []),
    }
    if chwila == "Run.api":
        zapis_tekstem_na_windows()

    with pytest.raises(common.DriveFailure, match="holds \\\\r"):
        kroki[chwila]()


class _Dlugosc:
    """Obiekt z własnym ``__len__``, bez ``__bool__``: prawdziwy, gdy jego długość nie jest zerem."""

    def __init__(self, length: int) -> None:
        self.length = length

    def __len__(self) -> int:
        return self.length


@pytest.mark.parametrize(
    ("pusta", "pelna"),
    [
        ("", "wpis"),
        (b"", b"wpis"),
        (deque(), deque(["wpis"])),
        ({}.keys(), {"wpis": 1}.keys()),
        (_Dlugosc(0), _Dlugosc(1)),
        (0, 1),
        ([], ["wpis"]),
    ],
    ids=["str", "bytes", "deque", "widok-slownika", "wlasne-len", "zero", "lista"],
)
def test_czekanie_drive_na_wartosc_falszywa_czyta_jeszcze_raz(common: ModuleType, pusta: object, pelna: object) -> None:
    """Wartość fałszywa w Pythonie to stan „jeszcze nie”, z jakiegokolwiek typu: pusty tekst ``Run.log()`` przed
    pierwszym wpisem dziennika, pusta kolekcja, zero (#1857 r2)."""

    waiting = importlib.import_module("drive.waiting")
    reads: list[str] = []

    def ready() -> object:
        reads.append("odczyt")
        return pelna if len(reads) == 3 else pusta

    assert (waiting.until(ready, "the entry comes", 1.0) is pelna, len(reads)) == (True, 3)


@pytest.mark.parametrize(
    "not_yet",
    [
        lambda path: path.read_text(encoding="utf-8"),
        lambda path: json.loads(""),
        lambda path: b"\xc5".decode("utf-8"),
        lambda path: yaml.safe_load("folder_okresow: [C:/okresy,"),
        _refused,
    ],
    ids=["brak-pliku", "pusty-json", "pol-znaku-utf8", "pol-yaml", "bez-prawa-odczytu"],
)
def test_czekanie_drive_czyta_jeszcze_raz_po_kazdym_stanie_jeszcze_nie(
    common: ModuleType, tmp_path: Path, not_yet: Callable[[Path], object]
) -> None:
    waiting = importlib.import_module("drive.waiting")
    reads: list[str] = []

    def ready() -> str:
        reads.append("odczyt")
        if len(reads) == 1:
            not_yet(tmp_path / "brak.json")
        return "gotowe"

    assert waiting.until(ready, "the file is written") == "gotowe"
    assert len(reads) == 2


def test_plik_trwale_w_polowie_zapisany_konczy_czekanie_po_budzecie_komunikatem_z_jego_stanem(
    common: ModuleType, tmp_path: Path
) -> None:
    run = _run(common, tmp_path)
    result = run.config / UPDATE_RESULT_FILE
    result.write_text('{"wynik": "NOWA_', encoding="utf-8")

    waiting = importlib.import_module("drive.waiting")
    with pytest.raises(waiting.TimedOut) as failure:
        waiting.until(lambda: common.read_json(result)["wynik"] == "ok", "the update wrote its result", 0.3)

    assert str(failure.value).startswith(
        "timed out: the update wrote its result; the last read was not ready: JSONDecodeError: Unterminated string"
    ), failure.value


def test_blad_spoza_stanow_jeszcze_nie_konczy_czekanie_od_razu(common: ModuleType, tmp_path: Path) -> None:
    """Pełny plik bez oczekiwanego klucza to błąd drive'u albo Centrum, a nie plik w trakcie zapisu."""

    run = _run(common, tmp_path)
    result = run.config / UPDATE_RESULT_FILE
    result.write_text(json.dumps({"stan": "ok"}), encoding="utf-8")
    reads: list[int] = []

    def updated() -> bool:
        reads.append(1)
        return bool(common.read_json(result)["wynik"] == "ok")

    with pytest.raises(KeyError, match="wynik"):
        importlib.import_module("drive.waiting").until(updated, "the update wrote its result")

    assert reads == [1]


class _Zegar:
    """Zegar czekania drive'u w teście: sen przesuwa go od razu, więc budżet 60 s mija bez minuty czekania."""

    def __init__(self) -> None:
        self.teraz = 0.0

    def monotonic(self) -> float:
        return self.teraz

    def sleep(self, seconds: float) -> None:
        self.teraz += seconds


def test_czekanie_drive_konczy_sie_po_budzecie_podanym_przez_wywolanie_a_nie_po_domyslnym(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Każdy nazwany budżet i liczba sekund podana ``until`` to limit tego czekania: stan, który nie nadchodzi, kończy
    czekanie zaraz po nim, a nie po domyślnym ``Budget.SCREEN`` (przegląd #1663). Limit Playwrighta z tego budżetu
    (``Budget.ms``) to ten sam czas, więc asercja i czekanie z jednym budżetem trwają tyle samo (przegląd #1666)."""

    waiting = importlib.import_module("drive.waiting")
    zegar = _Zegar()
    monkeypatch.setattr(waiting, "time", zegar)
    limits: dict[str, tuple[float, float]] = {}

    for budget in waiting.Budget:
        start = zegar.teraz
        with pytest.raises(waiting.TimedOut, match="timed out: the state comes"):
            waiting.until(lambda: None, "the state comes", budget)
        limits[budget.name] = (budget.ms / 1000, zegar.teraz - start)
    start = zegar.teraz
    with pytest.raises(waiting.TimedOut, match="timed out: the state comes"):
        waiting.until(lambda: False, "the state comes", 0.3)
    limits["0.3 s"] = (0.3, zegar.teraz - start)

    outside = [name for name, (limit, waited) in limits.items() if not limit < waited <= limit + 2 * waiting.POLL_S]
    assert outside == [], limits


def test_expect_drive_bez_timeout_czeka_budzet_asercji(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asercja ``expect`` napędu bez ``timeout=`` czeka ``Budget.ASSERTION`` (przegląd #1666). Plik ``drive/waiting.py``
    biegnie tu jako osobny moduł, żeby nie podmienić ``Budget``, który trzymają inne moduły napędu."""

    defaults: list[dict[str, object]] = []

    class Expect(playwright.sync_api.Expect):
        def set_options(self, timeout: float | None = None) -> None:
            defaults.append({"timeout": timeout})
            super().set_options(timeout=timeout)

    monkeypatch.setattr(playwright.sync_api, "Expect", Expect)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("waiting_w_tescie", DRIVE / "waiting.py")
    assert spec is not None and spec.loader is not None
    waiting = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(waiting)

    assert isinstance(waiting.expect, Expect)
    assert defaults == [{"timeout": waiting.Budget.ASSERTION.ms}]


class _Karta:
    """Karta w teście: żądanie kliknięcia wychodzi z niej dopiero przy ``po_ilu``-tym czekaniu Playwrighta, jak zapis karty
    w trybie wolnego runnera, a klient synchroniczny dostarcza zdarzenie tylko w swoim wywołaniu (#1682)."""

    def __init__(self, po_ilu: int | None) -> None:
        self.sent: list[SimpleNamespace] = []
        self.czekania = 0
        self.po_ilu = po_ilu

    def wait_for_timeout(self, ms: float) -> None:
        self.czekania += 1
        if self.czekania == self.po_ilu:
            self.sent.append(SimpleNamespace(response=lambda: None))


def test_czekanie_na_zadanie_karty_czeka_w_playwright_wiec_zdarzenie_dochodzi(
    common: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiting = importlib.import_module("drive.waiting")
    monkeypatch.setattr(waiting, "time", _Zegar())
    karta = _Karta(po_ilu=5)

    assert waiting.until(lambda: len(karta.sent) >= 1, "the click sends its request", 1.0, page=karta) is True
    assert karta.czekania == 5


def test_powtorzone_klikniecie_liczy_zadanie_ktore_wyszlo_z_karty_pozno(common: ModuleType) -> None:
    """``settle`` liczy żądania dopiero, gdy kliknięcie wysłało swoje: stały sen liczył za wcześnie (lista #1539, miejsce 4),
    a kliknięcie, które ma nic nie wysłać (``at_least=0``), nie czeka na żądanie."""

    pozna = _Karta(po_ilu=8)
    bez_zadania = _Karta(po_ilu=None)

    assert common.settle(pozna, pozna.sent) == 1
    assert common.settle(bez_zadania, bez_zadania.sent, at_least=0) == 0


class _KartaZZegarem:
    """Karta w teście z zegarem, który przesuwa tylko jej czekanie: żądanie wychodzi z niej, gdy zegar minie
    ``wychodzi_ms`` od kliknięcia, jak zapis karty w trybie wolnego runnera (``LATE_WRITE_MS``)."""

    def __init__(self, wychodzi_ms: float) -> None:
        self.sent: list[SimpleNamespace] = []
        self.teraz_ms = 0.0
        self.wychodzi_ms = wychodzi_ms
        self.odpowiedzi_czekane = 0

    def wait_for_timeout(self, ms: float) -> None:
        self.teraz_ms += ms
        if not self.sent and self.teraz_ms >= self.wychodzi_ms:
            self.sent.append(SimpleNamespace(response=self._odpowiedz))

    def _odpowiedz(self) -> None:
        self.odpowiedzi_czekane += 1


@pytest.mark.parametrize("slow", [True, False], ids=["wolny-runner", "bez-trybu"])
def test_cisza_po_kliknieciu_ktore_ma_nic_nie_wyslac_obejmuje_spozniony_zapis_karty(
    common: ModuleType, monkeypatch: pytest.MonkeyPatch, slow: bool
) -> None:
    """Kliknięcie, które ma nic nie wysłać, a jednak wysyła, w trybie wolnego runnera wysyła swój zapis ``LATE_WRITE_MS``
    później: ``settle`` liczy go, bo cisza ``quiet_for`` trwa w trybie tyle dłużej (lista #1539, PR 5). Bez trybu
    zapis wychodzi od razu, a cisza zostaje krótka. Już pierwsza cisza obejmuje spóźniony zapis, więc ``settle`` czeka
    na jego odpowiedź, zanim druga cisza da jej dojść na ekran (przegląd #1712, D1)."""

    waiting = importlib.import_module("drive.waiting")
    if slow:
        monkeypatch.setenv(common.SLOW_RUNNER, "1")
    else:
        monkeypatch.delenv(common.SLOW_RUNNER, raising=False)
    late_ms = waiting.LATE_WRITE_MS if slow else 0
    # Drugie kliknięcie taty przychodzi w kilka milisekund po pierwszym, a zapis wychodzi z karty z opóźnieniem trybu.
    karta = _KartaZZegarem(late_ms + 50)

    assert common.settle(karta, karta.sent, at_least=0) == 1
    assert karta.odpowiedzi_czekane == 1
    assert karta.teraz_ms <= 2 * (waiting.REPEAT_SETTLE_MS + late_ms)


@pytest.mark.parametrize("slow", [True, False], ids=["wolny-runner", "bez-trybu"])
def test_okno_taty_w_trybie_wolnego_runnera_wysyla_zapisy_pozno_i_zwalnia_animacje_a_bez_trybu_nie(
    common: ModuleType, monkeypatch: pytest.MonkeyPatch, slow: bool
) -> None:
    """Przegląd #1682, D3: flaga ``--wolny-runner`` (``SLOW_RUNNER``) wpina w każde okno taty opóźnione zapisy karty i
    wolne animacje każdej jego strony, a bez flagi okno jest zwykłe."""

    if slow:
        monkeypatch.setenv(common.SLOW_RUNNER, "1")
    else:
        monkeypatch.delenv(common.SLOW_RUNNER, raising=False)
    scripts: list[str] = []
    cdp: list[tuple[str, object]] = []
    pages: list[Callable[[object], None]] = []
    context = SimpleNamespace(
        add_init_script=scripts.append,
        on=lambda event, handler: pages.append(handler) if event == "page" else None,
        new_cdp_session=lambda page: SimpleNamespace(send=lambda method, params: cdp.append((method, params))),
    )

    common.dad_context(SimpleNamespace(new_context=lambda **_: context))
    for opened in pages:
        opened(object())

    slowed = (
        [common.LATE_WRITES % common.LATE_WRITE_MS],
        [("Animation.setPlaybackRate", {"playbackRate": common.SLOW_ANIMATIONS})],
    )
    assert (scripts, cdp) == (slowed if slow else ([], []))


STRONA_CENTRUM = (
    '<!doctype html><html><head><link rel="icon" href="data:,"><link rel="stylesheet" href="/assets/index.css">'
    '<link rel="stylesheet" href="http://czcionki.test/font.css"></head><body><h1>Okresy</h1></body></html>'
)


def _bez_chwili(plik: Path) -> list[str]:
    return sorted(line.partition(" ")[2] for line in plik.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize("arkusz", ["doszedl", "przepadl"])
def test_strona_napedu_zapisuje_utracone_zadania_a_bez_arkusza_stylow_konczy_przebieg_porazka_arkusza(
    common: ModuleType, tmp_path: Path, arkusz: str
) -> None:
    """Run 43561009106: ``index.css`` nie doszedł, a kliknięcie w oknie Ustawień czekało 10 s za tłem okna Base UI i
    nie nazwało przyczyny (#1539). Każda karta okna taty zapisuje nieudane żądanie i odpowiedź 400 lub wyższą, adres bez
    zapytania (żądanie, które strona sama porzuciła, jak strumień Uruchomień przy przejściu, nic nie straciło), a strona
    bez arkusza stylów kończy przebieg porażką, która go nazywa i wskazuje ten plik. Arkusza z innego origin strona nigdy
    nie odczyta, więc doszły nie jest porażką (przegląd #1714, D2)."""

    def arkusz_stylow(route: playwright.sync_api.Route) -> None:
        if arkusz == "doszedl":
            route.fulfill(body="h1 { color: red }", content_type="text/css")
        else:
            route.abort()

    with playwright.sync_api.sync_playwright() as przegladarki:
        browser = przegladarki.chromium.launch(**launch_options(przegladarki))
        try:
            with common.page_requests.recording(tmp_path):
                context = common.dad_context(browser)
                context.route("http://centrum.test/", lambda route: route.fulfill(body=STRONA_CENTRUM, content_type="text/html"))
                context.route("http://centrum.test/assets/index.css", arkusz_stylow)
                context.route("http://czcionki.test/font.css", lambda route: route.fulfill(body="h1 {}", content_type="text/css"))
                context.route("http://centrum.test/api/brak**", lambda route: route.fulfill(status=404, body="{}"))
                context.route("http://centrum.test/api/runs/events", lambda route: route.abort("aborted"))
                page = context.new_page()
                page.goto("http://centrum.test/")
                page.evaluate("fetch('/api/brak?klucz=wartosc').then(answer => answer.status)")
                page.evaluate("fetch('/api/runs/events').catch(() => 'porzucone')")
        finally:
            browser.close()

    zapisane = _bez_chwili(tmp_path / "zadania-strony.txt")
    if arkusz == "doszedl":
        assert zapisane == ["GET http://centrum.test/api/brak answered 404"]
        common.page_requests.check()
        return
    assert zapisane == [
        "GET http://centrum.test/api/brak answered 404",
        "GET http://centrum.test/assets/index.css failed: net::ERR_FAILED",
        "page without stylesheet http://centrum.test/assets/index.css",
    ]
    with pytest.raises(common.DriveFailure) as failure:
        common.page_requests.check()
    assert str(failure.value).startswith("the page got no stylesheet (http://centrum.test/assets/index.css)"), failure.value
    assert str(failure.value).endswith("are in zadania-strony.txt"), failure.value


@pytest.mark.parametrize("funkcja", ["pada", "przechodzi"])
def test_przebieg_ze_strona_bez_arkusza_stylow_pada_najpierw_na_arkuszu_a_potem_na_bledzie_funkcji(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], funkcja: str
) -> None:
    """``DRIVE FAIL`` przebiegu, którego strona nie dostała arkusza, zaczyna się od arkusza i pliku utraconych żądań, a
    błąd funkcji (kliknięcie za tłem okna) zostaje po nim z notatkami (zrzut porażki, którego nie zrobiono), jak w runie
    43561009106 (#1539, przegląd #1714, D1). Funkcja, która mimo to przeszła, też kończy przebieg porażką: jej zrzuty
    nie pokazują ekranu taty."""

    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("drive_centrum", SCRIPTS / "drive_centrum.py")
    assert spec is not None and spec.loader is not None
    drive_centrum = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drive_centrum)
    common = importlib.import_module("drive.common")
    handlers: dict[str, Callable[[object], None]] = {}

    class Page:
        def set_default_timeout(self, timeout: float) -> None:
            pass

        def screenshot(self, **options: object) -> bytes:
            raise PlaywrightError("Page.screenshot: Target closed")

    class Browser:
        def new_context(self, **options: object) -> SimpleNamespace:
            return SimpleNamespace(new_page=Page, storage_state=dict, add_init_script=lambda script: None, on=handlers.__setitem__)

        contexts: tuple[object, ...] = ()

        def close(self) -> None:
            pass

    @contextmanager
    def playwright_fake() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(chromium=SimpleNamespace(launch=Browser))

    def click_behind_the_backdrop(run: object, page: object) -> None:
        handlers["console"](SimpleNamespace(text=common.NO_STYLESHEET + "http://127.0.0.1:9/assets/index.css"))
        if funkcja == "pada":
            raise PlaywrightError("Locator.click: Timeout 10000ms exceeded.")

    # Atrapa przeglądarki nie ma linii poleceń, z której launch_options bierze listę funkcji wyłączonych przez Playwright.
    monkeypatch.setattr(drive_centrum, "launch_options", lambda playwright: {})
    monkeypatch.setattr(drive_centrum, "sync_playwright", playwright_fake)
    monkeypatch.setitem(drive_centrum.MODULES, "ustawienia", SimpleNamespace(drive=click_behind_the_backdrop))
    (tmp_path / "fixture.json").write_text("{}", encoding="utf-8")
    evidence = tmp_path / "dowody"
    arguments = ["--root", str(tmp_path), "--url", "http://127.0.0.1:9", "--evidence", str(evidence)]

    code = drive_centrum.main([*arguments, "--feature", "ustawienia"])

    [line] = capsys.readouterr().err.splitlines()
    assert code == 1
    assert line == (
        "DRIVE FAIL | the page got no stylesheet (http://127.0.0.1:9/assets/index.css), so Base UI windows lie under "
        "their backdrop; its failed requests and error answers are in zadania-strony.txt"
        + (" | Locator.click: Timeout 10000ms exceeded. | zz-failure.png not taken: Page.screenshot: Target closed" if funkcja == "pada" else "")
    ), line
    assert _bez_chwili(evidence / "zadania-strony.txt") == ["page without stylesheet http://127.0.0.1:9/assets/index.css"]


def test_serwer_przebiegu_wypisuje_kazde_zadanie_ze_sciezka_bez_zapytania_i_kodem_odpowiedzi(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Konsola serwera w dowodach mówi, czy żądanie, które strona straciła, doszło do Centrum i jak się skończyło
    (#1539): metoda, ścieżka bez zapytania i kod odpowiedzi albo jej przerwanie, nic więcej."""

    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("serve_centrum", SCRIPTS / "serve_centrum.py")
    assert spec is not None and spec.loader is not None
    serve_centrum = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve_centrum)

    async def app(scope: dict[str, Any], receive: object, send: Callable[[dict[str, Any]], Any]) -> None:
        await send({"type": "http.response.start", "status": 200 if scope["path"].startswith("/assets/") else 404})
        if scope["path"] == "/assets/index.css":
            raise ConnectionResetError
        await send({"type": "http.response.body", "body": b""})

    async def send(message: dict[str, Any]) -> None:
        pass

    log = serve_centrum._RequestLog(app)
    for path in ("/api/okresy/żółw", "/assets/index.css"):
        scope = {"type": "http", "method": "GET", "path": path, "query_string": b"klucz=wartosc"}
        with contextlib.suppress(ConnectionResetError):
            asyncio.run(log(scope, None, send))

    lines = [line.split(" ", 2)[2] for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        "GET /api/okresy/%C5%BC%C3%B3%C5%82w 404",
        "GET /assets/index.css 200 broken off: ConnectionResetError",
    ]


def test_porazka_napedu_drukuje_utracone_zadania_strony_z_ostatnia_linia_serwera_dla_ich_sciezki(
    runner: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CI zachowuje z porażki tylko log, nie dowody, więc noce 13.11 i 14.11 nie nazwały, dlaczego strona nie dostała
    ``index.css`` (#1567, #1756). Porażka napędu drukuje każdą linię ``zadania-strony.txt`` i ostatnią linię ``REQUEST``
    serwera dla jej ścieżki sprzed niej albo z tej samej chwili (żądanie z późniejszego przejścia się nie liczy) albo to,
    że takiej nie było. Ścieżkę z ``(`` i ``)`` strona wysyła bez kodowania, a serwer pisze je jako ``%28`` i ``%29``;
    linia bez adresu http (żądanie ``data:``) nie przerywa wydruku następnych."""

    def step(name: str, arguments: list[str], evidence: Path, timeout: int = 0) -> None:
        if name != "drive":
            return
        (evidence / "server.txt").write_text(
            "SERVING http://127.0.0.1:9/\n"
            "REQUEST 2026-11-14T08:50:10.000+00:00 GET /assets/index.css 200\n"
            "REQUEST 2026-11-14T08:50:20.000+00:00 GET /assets/index.css 304\n"
            "REQUEST 2026-11-14T08:50:21.000+00:00 GET /assets/index.js 304\n"
            "REQUEST 2026-11-14T08:50:22.200+00:00 GET /api/pracownicy/Kowalski%20%28A%29/plik%3A1 500\n"
            "REQUEST 2026-11-14T08:50:23.500+00:00 GET /assets/index.css 200\n",
            encoding="utf-8",
        )
        (evidence / "zadania-strony.txt").write_text(
            "2026-11-14T08:50:21.900+00:00 GET text/css,a failed: net::ERR_FAILED\n"
            "2026-11-14T08:50:22.000+00:00 GET http://127.0.0.1:9/assets/index.css failed: net::ERR_FAILED\n"
            "2026-11-14T08:50:22.100+00:00 GET http://127.0.0.1:9/api/brak answered 404\n"
            "2026-11-14T08:50:22.200+00:00 GET http://127.0.0.1:9/api/pracownicy/Kowalski%20(A)/plik:1 answered 500\n",
            encoding="utf-8",
        )
        raise runner.VerificationFailure("drive returned 1")

    monkeypatch.setattr(runner, "_preflight", lambda: None)
    monkeypatch.setattr(runner, "_launch", lambda root, evidence: (SimpleNamespace(poll=lambda: 0), "http://127.0.0.1:9/"))
    monkeypatch.setattr(runner, "_run_step", step)

    with pytest.raises(runner.VerificationFailure, match="drive returned 1"):
        runner._verify(("ustawienia",), [], tmp_path)

    assert capsys.readouterr().err.splitlines() == [
        "PAGE LOST | 2026-11-14T08:50:21.900+00:00 GET text/css,a failed: net::ERR_FAILED",
        "PAGE LOST | 2026-11-14T08:50:22.000+00:00 GET http://127.0.0.1:9/assets/index.css failed: net::ERR_FAILED",
        "  server before it: REQUEST 2026-11-14T08:50:20.000+00:00 GET /assets/index.css 304",
        "PAGE LOST | 2026-11-14T08:50:22.100+00:00 GET http://127.0.0.1:9/api/brak answered 404",
        "  server before it: no answered REQUEST of /api/brak",
        "PAGE LOST | 2026-11-14T08:50:22.200+00:00 GET http://127.0.0.1:9/api/pracownicy/Kowalski%20(A)/plik:1 answered 500",
        "  server before it: REQUEST 2026-11-14T08:50:22.200+00:00 GET /api/pracownicy/Kowalski%20%28A%29/plik%3A1 500",
    ]


@pytest.mark.parametrize(
    ("left", "printed"),
    [
        ({}, []),
        (
            {"zadania-strony.txt": "2026-11-14T08:50:22.000+00:00 GET http://127.0.0.1:9/assets/index.css answered 500\n"},
            [
                "PAGE LOST | 2026-11-14T08:50:22.000+00:00 GET http://127.0.0.1:9/assets/index.css answered 500",
                "  server before it: no answered REQUEST of /assets/index.css",
            ],
        ),
    ],
    ids=["bez-plikow", "bez-server-txt"],
)
def test_porazka_napedu_przed_zapisem_dowodow_konczy_sie_bledem_napedu(
    runner: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    left: dict[str, str],
    printed: list[str],
) -> None:
    """Napęd, który padł, zanim zapisał ``zadania-strony.txt`` albo zanim serwer zapisał ``server.txt``, kończy się
    swoim ``VerificationFailure``, nie błędem odczytu brakującego pliku, który by go zasłonił."""

    def step(name: str, arguments: list[str], evidence: Path, timeout: int = 0) -> None:
        if name != "drive":
            return
        for file, text in left.items():
            (evidence / file).write_text(text, encoding="utf-8")
        raise runner.VerificationFailure("drive returned 1")

    monkeypatch.setattr(runner, "_preflight", lambda: None)
    monkeypatch.setattr(runner, "_launch", lambda root, evidence: (SimpleNamespace(poll=lambda: 0), "http://127.0.0.1:9/"))
    monkeypatch.setattr(runner, "_run_step", step)

    with pytest.raises(runner.VerificationFailure, match="drive returned 1"):
        runner._verify(("ustawienia",), [], tmp_path)

    assert capsys.readouterr().err.splitlines() == printed
