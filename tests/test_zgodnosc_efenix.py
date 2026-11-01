"""Narzędzie zgodności Atrapy efenix z efenix (``tools/zgodnosc_efenix.py``, #748) na Atrapie efenix.

Każdy test uruchamia narzędzie jak Maks: osobnym procesem, który łączy się przez zdalne debugowanie z Chromium (u Maksa
Chrome z sesją taty), a sprawdza to, co widać z zewnątrz: wynik (plik expect w ``tests/expected/zgodnosc_efenix/``),
kod wyjścia i żądania, które dostała Atrapa. Zgodna Atrapa daje ``ZGODNOŚĆ OK``, a Atrapa ze zmienioną budową każdą
różnicę. Wynik nie zawiera numerów zleceń, adresów, loginów ani identyfikatorów, które Atrapa pokazuje.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
import pytest
import zgodnosc_efenix

from tests.fixtures.atrapa_efenix import (
    LIST_PAGE,
    LOGIN_PAGE,
    ORDER_PAGE,
    PAGE_READS,
    SEARCH,
    SESSION_COOKIE,
    AtrapaEfenix,
    AtrapaOrder,
    Changed,
    Unread,
    atrapa_efenix,
)
from tests.fixtures.expect import assert_expected

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "zgodnosc_efenix.py"
# Żądania, które niczego w efenix nie zmieniają: lista, szukanie, strona zlecenia, strona logowania i odczyty, które
# strony wysyłają same.
READING = {("GET", LIST_PAGE), ("POST", SEARCH), ("GET", ORDER_PAGE), ("GET", LOGIN_PAGE), *PAGE_READS}
# Żądania, które zmieniają zlecenie w efenix: zapis ilości, załadowanie Emmetta, ustawienie daty i statusu (#741),
# i wylogowanie, które kończy sesję taty.
WRITES = (
    "action_save_index.php",
    "action_load_emmett.php",
    "action_set_date_of_instalation.php",
    "action_change_status.php",
    "action_logout.php",
)
FORWARDING = ("forward", "accept", "cancel")
ORDERS = (
    AtrapaOrder("ID-TAJNE-71", "ZL/TAJNE/0001", "tajny-login", "ul.Tajemnicza 7 Lokal 3", execution_date=date(2026, 9, 2), executor="Firma Sekretna"),
    AtrapaOrder("ID-TAJNE-72", "ZL/TAJNE/0002", "tajny-login", "ul.Ukryta 9", executor="Firma Sekretna"),
    AtrapaOrder("ID-TAJNE-73", "ZL/TAJNE/0003", "inny-tajny", "os.Zakryte 4", status="Do akceptacji", execution_date=date(2026, 9, 3)),
)
PRIVATE = [text for order in ORDERS for text in (order.order_id, order.number, order.realizator, order.address, order.executor)]


@dataclass(frozen=True)
class Variant:
    """Atrapa efenix pod narzędziem i plik expect jego wyniku."""

    expected: Path | None = None
    changed: Changed | Unread | None = None
    cookie_session: bool = True
    orders: tuple[AtrapaOrder, ...] = ORDERS
    number: str = ""
    answer_delay_s: float = 0.0


DATED = tuple(AtrapaOrder(order.order_id, order.number, order.realizator, order.address, execution_date=date(2026, 9, 1)) for order in ORDERS)
CHANGED = {
    "inny-naglowek-status": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inny-naglowek-status.txt", Changed.STATUS_HEADER),
    "wiersz-bez-linku": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-bez-linku.txt", Changed.ORDER_LINK),
    "inny-zapis-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inny-zapis-daty.txt", Changed.DATE_FORMAT),
    "bez-emmetta-i-pola-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "bez-emmetta-i-pola-daty.txt", Unread.ORDER_PARTS),
    "inne-pozycje-wyceny": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inne-pozycje-wyceny.txt", Unread.PRICE_LIST),
    "logowanie-bez-fingerprint": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "logowanie-bez-fingerprint.txt", Unread.LOGIN_FORM),
    "skrypt-strony-zapisuje": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "skrypt-strony-zapisuje.txt", Unread.PAGE_WRITE),
    "login-realizatora-w-small": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "login-realizatora-w-small.txt", Unread.LOGIN_IN_SMALL),
    "sesja-bez-ciasteczka": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "sesja-bez-ciasteczka.txt", cookie_session=False),
    "bez-pustej-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "bez-pustej-daty.txt", orders=DATED),
    "okno-ze-zmiana-statusu": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "okno-ze-zmiana-statusu.txt", Unread.PAGE_POPUP),
    "przekierowanie-na-wylogowanie": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "przekierowanie-na-wylogowanie.txt", Unread.REDIRECT_TO_LOGOUT
    ),
    "websocket-strony": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "websocket-strony.txt", Unread.PAGE_SOCKET),
    "worker-zapisuje": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "worker-zapisuje.txt", Unread.PAGE_WORKER),
}
# Atrapa w innej postaci niż zgodna, a jednak zgodna z tym, czego używa Wycena w efenix: wynik to ``ZGODNOŚĆ OK``.
SAME = {
    "ceny-z-przecinkiem": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", Unread.PRICE_TEXT),
    "najpierw-zlecenie-do-akceptacji": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", orders=(ORDERS[2], ORDERS[0], ORDERS[1])
    ),
    "lista-sama-szuka-przy-wczytaniu": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "lista-sama-szuka-przy-wczytaniu.txt",
        Unread.SEARCH_ON_LOAD,
        number=ORDERS[1].number,
        answer_delay_s=0.3,
    ),
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
    wznawiać nowe karty narzędzia, więc ich strony nie wczytują się (#755, CI na windows-2025).
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


def _run(endpoint: str, atrapa: AtrapaEfenix, number: str = "") -> Checked:
    done = subprocess.run(
        [sys.executable, str(TOOL), "--efenix-url", atrapa.url, "--cdp", endpoint, "--limit-ms", "10000", "--numer", number],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    return Checked(done.returncode, done.stdout, done.stderr)


def _checked(endpoint: str, variant: Variant, before: Callable[[AtrapaEfenix], None] = lambda _atrapa: None) -> tuple[Checked, AtrapaEfenix]:
    with atrapa_efenix(
        variant.orders, changed=variant.changed, cookie_session=variant.cookie_session, answer_delay_s=variant.answer_delay_s
    ) as atrapa:
        before(atrapa)
        state = atrapa.state()
        checked = _run(endpoint, atrapa, variant.number)
        assert atrapa.state() == state
        assert not _open_tabs(endpoint, atrapa), "narzędzie zostawiło w Chrome kartę albo okno efenix"
    assert not [text for text in PRIVATE if text in checked.stdout + checked.stderr]
    return checked, atrapa


def _open_tabs(endpoint: str, atrapa: AtrapaEfenix) -> list[str]:
    """Adresy kart Chrome na Atrapie (lista celów zdalnego debugowania)."""

    with urlopen(f"{endpoint}/json/list", timeout=10) as answer:
        targets = json.load(answer)
    host = urlparse(atrapa.url).netloc
    return [target["url"] for target in targets if urlparse(target["url"]).netloc == host]


def test_atrapa_efenix_jest_zgodna_z_budowa_ktorej_uzywa_wycena_w_efenix(chrome: str) -> None:
    checked, atrapa = _checked(chrome, Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt"))

    assert (checked.code, checked.stderr) == (0, ""), checked
    assert checked.stdout.splitlines()[-1] == "ZGODNOŚĆ OK"
    assert_expected(checked.stdout, ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt")
    assert set(atrapa.requested()) <= READING


@pytest.mark.parametrize("variant", SAME.values(), ids=SAME.keys())
def test_atrapa_w_innej_postaci_tej_samej_budowy_jest_zgodna(chrome: str, variant: Variant) -> None:
    checked, atrapa = _checked(chrome, variant)

    assert (checked.code, checked.stderr) == (0, ""), checked
    assert variant.expected is not None
    assert_expected(checked.stdout, variant.expected)
    assert set(atrapa.requested()) <= READING


@pytest.mark.parametrize("variant", CHANGED.values(), ids=CHANGED.keys())
def test_atrapa_ze_zmieniona_budowa_daje_kazda_roznice(chrome: str, variant: Variant) -> None:
    checked, atrapa = _checked(chrome, variant)

    assert (checked.code, checked.stderr) == (2, ""), checked
    assert variant.expected is not None
    assert_expected(checked.stdout, variant.expected)
    assert set(atrapa.requested()) <= READING


def test_niezalogowana_karta_konczy_narzedzie_bledem_bez_wyniku(chrome: str) -> None:
    checked, atrapa = _checked(chrome, Variant(), before=lambda atrapa: atrapa.expire_session())

    assert (checked.code, checked.stdout) == (1, "")
    assert checked.stderr.startswith("BŁĄD | karta Chrome nie jest zalogowana do efenix")
    assert set(atrapa.requested()) <= READING


def test_bez_chrome_pod_adresem_zdalnego_debugowania_narzedzie_konczy_sie_bledem() -> None:
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{free.getsockname()[1]}"
    with atrapa_efenix(ORDERS) as atrapa:
        checked = _run(endpoint, atrapa)

    assert (checked.code, checked.stdout) == (1, "")
    assert checked.stderr == f"BŁĄD | nie ma Chrome ze zdalnym debugowaniem pod --cdp {endpoint}\n"
    assert atrapa.requested() == []


def test_lista_dozwolonych_zadan_ma_tylko_odczyty() -> None:
    names = {name for _method, name in zgodnosc_efenix.ALLOWED}

    assert not names & set(WRITES)
    assert not [name for name in names if any(word in name.casefold() for word in FORWARDING)]
    host = "efenix.example"
    for name in (*WRITES, "action_forward_to_accept.php", "action_forward_to_cancel.php"):
        for method in ("GET", "POST"):
            for kind in ("document", "fetch", "xhr", "script", "image"):
                assert not zgodnosc_efenix.allowed(method, f"https://{host}/{name}?id=1", kind, host), (method, name, kind)
    for method, name in zgodnosc_efenix.ALLOWED:
        assert zgodnosc_efenix.allowed(method, f"https://{host}/{name}", "fetch", host), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"https://inny.example/{name}", "fetch", host), (method, name)
