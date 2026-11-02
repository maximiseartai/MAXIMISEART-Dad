"""Narzędzie zgodności Atrapy efenix z efenix (``tools/zgodnosc_efenix.py``, #748) na Atrapie efenix.

Każdy test uruchamia narzędzie jak Maks: osobnym procesem, który łączy się przez zdalne debugowanie z Chromium (u Maksa
Chrome z sesją taty), a sprawdza to, co widać z zewnątrz: wynik (plik expect w ``tests/expected/zgodnosc_efenix/``),
kod wyjścia, żądania, które dostała Atrapa, i jej stan. Zgodna Atrapa daje wynik bez różnic, a Atrapa ze zmienioną
budową każdą różnicę; każdy wynik ma prośbę o ręczne sprawdzenie przycisku kalendarza daty wykonania. Każde żądanie, które dostaje Atrapa, jest z listy dozwolonych odczytów, także gdy skrypty i
elementy stron same wysyłają zapis albo wylogowanie. Wynik nie zawiera numerów zleceń, adresów, loginów ani
identyfikatorów, które Atrapa pokazuje, ani cen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
import pytest
import zgodnosc_efenix

from rozliczenia.efenix_positions import POSITION_OF_COLUMN

from tests.fixtures.atrapa_efenix import (
    CHANGE_STATUS,
    LIST_PAGE,
    LIST_SCRIPT,
    LOAD_EMMETT,
    LOGIN_PAGE,
    LOGOUT,
    ORDER_PAGE,
    ORDER_SCRIPT,
    PRICES,
    SAVE_QUANTITY,
    SEARCH,
    SESSION_COOKIE,
    SET_DATE,
    AtrapaEfenix,
    AtrapaOrder,
    Changed,
    Unread,
    atrapa_efenix,
)
from tests.fixtures.efenix import write_template_costs
from tests.fixtures.expect import assert_expected
from tests.fixtures.settlement import CellValue

ROOT = Path(__file__).resolve().parents[1]
# Linia, którą ma każdy wynik narzędzia (#748): przycisku kalendarza narzędzie nie sprawdza, sprawdza go Maks.
DATE_BUTTON_BY_HAND = (
    "NIESPRAWDZONE | strona zlecenia | przycisk kalendarza daty wykonania nie jest sprawdzany: sprawdź ręcznie w efenix"
    " na zleceniu „Do wyceny” bez daty wykonania, że jest przycisk otwierający okno wyboru daty"
)
TOOL = ROOT / "tools" / "zgodnosc_efenix.py"
# Żądania, które niczego w efenix nie zmieniają: lista, szukanie, strona zlecenia, skrypty obu stron i strona logowania.
READING = {("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("GET", LOGIN_PAGE)}
# Żądania, które zmieniają zlecenie w efenix: zapis ilości, załadowanie Emmetta, ustawienie daty i statusu (#741),
# i logowanie oraz wylogowanie, które zmieniają sesję taty.
WRITES = (SAVE_QUANTITY, LOAD_EMMETT, SET_DATE, CHANGE_STATUS, "action_login.php", LOGOUT)
FORWARDING = ("forward", "accept", "cancel")
ORDERS = (
    AtrapaOrder("ID-TAJNE-71", "ZL/TAJNE/0001", "tajny-login", "ul.Tajemnicza 7 Lokal 3", execution_date=date(2026, 9, 2), executor="Firma Sekretna"),
    AtrapaOrder("ID-TAJNE-72", "ZL/TAJNE/0002", "tajny-login", "ul.Ukryta 9", executor="Firma Sekretna"),
    AtrapaOrder("ID-TAJNE-73", "ZL/TAJNE/0003", "inny-tajny", "os.Zakryte 4", status="Do akceptacji", execution_date=date(2026, 9, 3)),
)
PRIVATE = [text for order in ORDERS for text in (order.order_id, order.number, order.realizator, order.address, order.executor)]
# Koszty pozycji w wierszu 14 Wzorca pliku zbiorczego równe cenom Atrapy: kolumna → koszt pozycji z przypisania kolumn.
COSTS: dict[str, CellValue] = {column: float(PRICES[position]) for column, position in POSITION_OF_COLUMN.items()}


@dataclass(frozen=True)
class Variant:
    """Atrapa efenix pod narzędziem, koszty we Wzorcu i plik expect wyniku."""

    expected: Path
    changed: Changed | Unread | None = None
    cookie_session: bool = True
    orders: tuple[AtrapaOrder, ...] = ORDERS
    costs: Mapping[str, CellValue] = field(default_factory=lambda: COSTS)
    number: str = ""


DATED = tuple(AtrapaOrder(order.order_id, order.number, order.realizator, order.address, execution_date=date(2026, 9, 1)) for order in ORDERS)
CHANGED = {
    "inny-naglowek-status": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inny-naglowek-status.txt", Changed.STATUS_HEADER),
    "wiersz-bez-linku": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-bez-linku.txt", Changed.ORDER_LINK),
    "inny-zapis-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inny-zapis-daty.txt", Changed.DATE_FORMAT),
    "bez-emmetta-i-pola-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "bez-emmetta-i-pola-daty.txt", Unread.ORDER_PARTS),
    "ukryty-przycisk-emmetta": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "ukryty-przycisk-emmetta.txt", Changed.HIDDEN_EMMETT),
    "inne-pozycje-wyceny": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inne-pozycje-wyceny.txt", Unread.PRICE_LIST),
    "inne-koszty-we-wzorcu": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inne-koszty-we-wzorcu.txt", costs={**COSTS, "O": 99.5, "P": "=O14", "AP": None}
    ),
    "skrypty-stron-inne": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "skrypty-stron-inne.txt", Unread.SCRIPTS),
    "skrypty-stron-pod-adresem-z-fragmentem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "skrypty-stron-pod-adresem-z-fragmentem.txt", Unread.SCRIPT_ADDRESSES
    ),
    "przekierowanie-strony-zlecenia": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "przekierowanie-strony-zlecenia.txt", Unread.ORDER_REDIRECT
    ),
    "logowanie-bez-fingerprint": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "logowanie-bez-fingerprint.txt", Unread.LOGIN_FORM),
    "sesja-bez-ciasteczka": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "sesja-bez-ciasteczka.txt", cookie_session=False),
    "bez-pustej-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "bez-pustej-daty.txt", orders=DATED),
}
# Atrapa w innej postaci niż zgodna, a jednak zgodna z tym, czego używa Wycena w efenix: wynik bez różnic.
SAME = {
    "ceny-z-przecinkiem": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", Unread.PRICE_TEXT),
    "najpierw-zlecenie-do-akceptacji": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", orders=(ORDERS[2], ORDERS[0], ORDERS[1])),
    "skrypty-stron-zapisuja-i-wylogowuja": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", Unread.HOSTILE),
    "szukanie-numeru": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "szukanie-numeru.txt", number=ORDERS[1].number),
}


@dataclass(frozen=True)
class Checked:
    code: int
    stdout: str
    stderr: str


@pytest.fixture(scope="module")
def chrome() -> Iterator[str]:
    """Chromium ze zdalnym debugowaniem (jak Chrome Maksa) i ciasteczkiem sesji Atrapy w domyślnym kontekście.

    Chromium i jego Playwright żyją w osobnym wątku, który przez cały czas obsługuje Playwrighta, jak osobny program
    Chrome u Maksa. Playwright, który uruchomił przeglądarkę, a którego nikt nie obsługuje, bo test czeka na proces
    narzędzia, na Windows wstrzymuje przeglądarkę: jego sterownik pisze do pełnej rury procesu testu i przestaje
    wznawiać nowe karty, więc karta, w której narzędzie składa HTML, nie wczytuje się (#755, CI na windows-2025).
    """

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    started: queue.Queue[BaseException | None] = queue.Queue()
    stop = threading.Event()

    def own() -> None:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=[f"--remote-debugging-port={port}"])
                try:
                    remote = playwright.chromium.connect_over_cdp(endpoint)
                    name, value = SESSION_COOKIE
                    remote.contexts[0].add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
                    idle = browser.new_page()
                    started.put(None)
                    while not stop.is_set():
                        idle.wait_for_timeout(50)
                finally:
                    browser.close()
        except BaseException as error:  # noqa: BLE001 - błąd startu przeglądarki wraca do fixture'a w wątku testu
            started.put(error)

    owner = threading.Thread(target=own, name="chromium-zgodnosc")
    owner.start()
    try:
        failure = started.get(timeout=120)
        if failure is not None:
            raise failure
        yield endpoint
    finally:
        stop.set()
        owner.join()


def _run(endpoint: str, atrapa: AtrapaEfenix, template: Path, *extra: str) -> Checked:
    done = subprocess.run(
        [sys.executable, str(TOOL), "--efenix-url", atrapa.url, "--cdp", endpoint, "--limit-ms", "10000", "--wzorzec", str(template), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    return Checked(done.returncode, done.stdout, done.stderr)


def _checked(
    endpoint: str, tmp_path: Path, variant: Variant, before: Callable[[AtrapaEfenix], None] = lambda _atrapa: None
) -> tuple[Checked, AtrapaEfenix]:
    """Wynik narzędzia na Atrapie ``variant``; Atrapa ma po nim ten sam stan i sesję, a Chrome te same karty."""

    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", variant.costs)
    with atrapa_efenix(variant.orders, changed=variant.changed, cookie_session=variant.cookie_session) as atrapa:
        before(atrapa)
        state, pages = atrapa.state(), _pages(endpoint)
        checked = _run(endpoint, atrapa, template, "--numer", variant.number)
        assert (atrapa.state(), _pages(endpoint)) == (state, pages)
    assert not [text for text in PRIVATE if text in checked.stdout + checked.stderr]
    assert DATE_BUTTON_BY_HAND in checked.stdout.splitlines()
    return checked, atrapa


def _pages(endpoint: str) -> int:
    """Liczba kart Chrome (lista celów zdalnego debugowania)."""

    with urlopen(f"{endpoint}/json/list", timeout=10) as answer:
        return sum(target["type"] == "page" for target in json.load(answer))


def test_atrapa_efenix_jest_zgodna_z_budowa_ktorej_uzywa_wycena_w_efenix(chrome: str, tmp_path: Path) -> None:
    checked, atrapa = _checked(chrome, tmp_path, Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt"))

    assert (checked.code, checked.stderr) == (0, ""), checked
    assert_expected(checked.stdout, ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt")
    assert set(atrapa.requested()) == READING
    # Szukanie z sesją i bez niej, z polami, które wysyła skrypt listy po Enter w polu Numer.
    assert [request.params for request in atrapa.requests if request.path == SEARCH] == 2 * [{"numer": "", "rodzaj": "szukanie", "strona": "1"}]


@pytest.mark.parametrize("variant", SAME.values(), ids=SAME.keys())
def test_atrapa_w_innej_postaci_tej_samej_budowy_jest_zgodna(chrome: str, tmp_path: Path, variant: Variant) -> None:
    checked, atrapa = _checked(chrome, tmp_path, variant)

    assert (checked.code, checked.stderr) == (0, ""), checked
    assert_expected(checked.stdout, variant.expected)
    assert set(atrapa.requested()) == READING


@pytest.mark.parametrize("variant", CHANGED.values(), ids=CHANGED.keys())
def test_atrapa_ze_zmieniona_budowa_daje_kazda_roznice(chrome: str, tmp_path: Path, variant: Variant) -> None:
    checked, atrapa = _checked(chrome, tmp_path, variant)

    assert (checked.code, checked.stderr) == (2, ""), checked
    assert_expected(checked.stdout, variant.expected)
    assert set(atrapa.requested()) <= READING


@pytest.mark.parametrize(
    ("before", "expire_after", "error"),
    [
        pytest.param(AtrapaEfenix.expire_session, None, zgodnosc_efenix.NOT_SIGNED_IN, id="przed-sprawdzaniem"),
        pytest.param(lambda _atrapa: None, (ORDER_PAGE, 0), zgodnosc_efenix.LOGGED_OUT_MIDWAY, id="w-trakcie-sprawdzania"),
    ],
)
def test_bez_sesji_taty_narzedzie_konczy_sie_bledem_bez_wyniku(
    chrome: str, tmp_path: Path, before: Callable[[AtrapaEfenix], None], expire_after: tuple[str, int] | None, error: str
) -> None:
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    with atrapa_efenix(ORDERS, cookie_session=True, expire_after=expire_after) as atrapa:
        before(atrapa)
        checked = _run(chrome, atrapa, template)

    assert (checked.code, checked.stdout, checked.stderr) == (1, "", f"BŁĄD | {error}\n")
    assert set(atrapa.requested()) <= READING


def test_bez_chrome_pod_adresem_zdalnego_debugowania_narzedzie_konczy_sie_bledem(tmp_path: Path) -> None:
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{free.getsockname()[1]}"
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    with atrapa_efenix(ORDERS) as atrapa:
        checked = _run(endpoint, atrapa, template)

    assert (checked.code, checked.stdout) == (1, "")
    assert checked.stderr == f"BŁĄD | nie ma Chrome ze zdalnym debugowaniem pod --cdp {endpoint}\n"
    assert atrapa.requested() == []


def test_bez_wzorca_pliku_zbiorczego_narzedzie_konczy_sie_bledem_przed_efenix(chrome: str, tmp_path: Path) -> None:
    missing = tmp_path / "Wzorzec pliku zbiorczego.xlsx"
    with atrapa_efenix(ORDERS, cookie_session=True) as atrapa:
        checked = _run(chrome, atrapa, missing)

    assert (checked.code, checked.stdout, checked.stderr) == (1, "", f"BŁĄD | Wzorzec pliku zbiorczego {missing}: brak pliku\n")
    assert atrapa.requested() == []


def test_lista_dozwolonych_zadan_ma_tylko_odczyty() -> None:
    names = {name for _method, name in zgodnosc_efenix.ALLOWED}

    assert not names & set(WRITES)
    assert not [name for name in names if any(word in name.casefold() for word in FORWARDING)]
    efenix = "https://efenix.example/app/index.php"
    for name in (*WRITES, "action_forward_to_accept.php", "action_forward_to_cancel.php", "action_fill_emmett.php"):
        for method in ("GET", "POST"):
            assert not zgodnosc_efenix.allowed(method, f"https://efenix.example/app/{name}?id=1", efenix), (method, name)
    for method, name in zgodnosc_efenix.ALLOWED:
        assert zgodnosc_efenix.allowed(method, f"https://efenix.example/app/{name}?v=1", efenix), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"https://inny.example/app/{name}", efenix), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"http://efenix.example/app/{name}", efenix), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"https://efenix.example/{name}", efenix), (method, name)
        assert not zgodnosc_efenix.allowed("DELETE", f"https://efenix.example/app/{name}", efenix), name
    # Skrypt zapisu z dopisaną ścieżką (PATH_INFO serwera PHP) i ścieżka z ``..`` to inne strony niż dozwolone.
    for path in (f"{LOGOUT}/{LIST_PAGE}", f"{SAVE_QUANTITY}/{SEARCH}", f"js/../{LOGOUT}", f"{LIST_PAGE}/x.png"):
        for method in ("GET", "POST"):
            assert not zgodnosc_efenix.allowed(method, f"https://efenix.example/app/{path}", efenix), (method, path)
