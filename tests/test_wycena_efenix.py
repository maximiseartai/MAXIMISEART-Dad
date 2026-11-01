"""Wycena w efenix przez rdzeń Uruchomienia procesu na Atrapie efenix w prawdziwej przeglądarce (spec #741, #743).

Każdy test prowadzi ``run_process`` z opisem procesu ``efenix_process.PROCESS`` i oknem efenix na karcie Chromium, a
sprawdza to, co widać z zewnątrz: wynik, Komunikaty, liczby podsumowania i żądania, które dostała Atrapa efenix. Wynik
w kształcie karty Uruchomienia sprawdza Skrypt dla maszyn (``tests/test_uruchom_proces.py``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
import socket

from playwright.sync_api import Browser, Page
import pytest

from rozliczenia import efenix_browser, efenix_process
from rozliczenia.efenix_pricing import PricingSummary
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.process_run import Finished, Outcome, Stop, run_process

from tests.fixtures.atrapa_efenix import LIST_PAGE, ORDER_PAGE, SEARCH, atrapa_efenix
from tests.fixtures.efenix import DAY, Order, write_collective_file
from tests.fixtures.interlocutor import Tata
from tests.fixtures.przegladarka import chromium, page_of

# Żądania, które niczego w efenix nie zmieniają: lista zleceń, szukanie i strona zlecenia.
READING = {("GET", LIST_PAGE), ("POST", SEARCH), ("GET", ORDER_PAGE)}
Priced = Outcome[PricingSummary]


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with chromium() as launched:
        yield launched


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    with page_of(browser) as opened:
        yield opened


def _price(tmp_path: Path, page: Page, url: str, orders: Sequence[Order]) -> Priced:
    source = write_collective_file(tmp_path, orders)
    inputs = EfenixInputs(source, lambda: efenix_browser.window(page, url, timeout_ms=10_000))
    return run_process(
        efenix_process.PROCESS, inputs, Tata(), view=lambda _inputs, summary: summary, metrics_path=tmp_path / "metryki.jsonl"
    )


def _figures(outcome: Priced) -> dict[str, int]:
    """Liczby podsumowania: zlecenia w zakresie, znalezione, błędy i pominięte."""

    assert isinstance(outcome.ending, Finished), outcome.ending
    assert outcome.view is not None
    summary = outcome.view
    return {
        "zakres": len(summary.results),
        "znalezione": summary.found_count,
        "błędy": summary.error_count,
        "ze zdjęciami": summary.with_photos,
        "usterki": summary.defects,
    }


def _errors(outcome: Priced) -> list[tuple[str, str]]:
    """Kod i wiersz Pliku zbiorczego każdego błędu zlecenia."""

    assert outcome.view is not None
    return [(warning.code, warning.where.rpartition(", ")[2]) for warning in outcome.view.warnings]


def _stop(outcome: Priced) -> str:
    assert isinstance(outcome.ending, Stop), outcome.ending
    assert outcome.ending.kind == "stop"
    return outcome.ending.message.code


def _figures_of(orders: int, found: int, photos: int = 0, defects: int = 0) -> dict[str, int]:
    return {"zakres": orders, "znalezione": found, "błędy": orders - found, "ze zdjęciami": photos, "usterki": defects}


def test_zlecenia_zgodne_z_efenix_sa_znalezione_a_efenix_dostaje_tylko_szukanie_i_otwarcie_zlecenia(tmp_path: Path, page: Page) -> None:
    orders = [Order("#5001"), Order("#5002"), Order("5003")]
    with atrapa_efenix(
        [orders[0].in_efenix("901"), replace(orders[1].in_efenix("902"), execution_date=DAY), orders[2].in_efenix("903")]
    ) as atrapa:
        before = atrapa.state()
        outcome = _price(tmp_path, page, atrapa.url, orders)
        after = atrapa.state()
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(3, 3), [])
    assert after == before
    assert set(requested) <= READING
    assert requested.count(("GET", ORDER_PAGE)) == 3


def test_zlecenia_ze_zdjeciami_i_usterki_sa_pominiete_i_policzone_a_wiersz_z_samymi_zerami_jest_w_zakresie(
    tmp_path: Path, page: Page
) -> None:
    photo_columns = ["AB", "AC", "AD", "AE", "AF", "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AS"]
    orders = [
        *(Order(f"#60{index:02}", cells={column: 1}) for index, column in enumerate(photo_columns)),
        Order("#6101", cells={"AJ": "tak"}),
        Order("#6201", cells={"AI": 1}),
        Order("#6301", cells=dict.fromkeys([*photo_columns, "AI"], 0)),
        Order("#6302", cells=dict.fromkeys([*photo_columns, "AI"], "0")),
        Order("#6401", cells={"H": None}),
    ]
    with atrapa_efenix([order.in_efenix(f"9{index:02}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched = atrapa.searched()

    assert (outcome.result, _figures(outcome), searched) == ("OK", _figures_of(2, 2, photos=14, defects=1), ["6301", "6302"])


def test_zlecenia_ida_po_wykonawcach_alfabetycznie_a_u_kazdego_od_najstarszej_daty(tmp_path: Path, page: Page) -> None:
    orders = [
        Order("#7001", worker="zenon.testowy", day=date(2026, 9, 8)),
        Order("#7002", worker="adrian.testowy", day=date(2026, 9, 12)),
        Order("#7003", worker="Bogdan.testowy", day=date(2026, 9, 10)),
        Order("#7004", worker="adrian.testowy", day=date(2026, 9, 9)),
        Order("#7005", worker="zenon.testowy", day=date(2026, 9, 7)),
    ]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched = atrapa.searched()

    assert (outcome.result, searched) == ("OK", ["7004", "7002", "7003", "7005", "7001"])


def test_kazda_niezgodnosc_z_efenix_to_blad_zlecenia_z_powodem_a_proces_idzie_dalej(tmp_path: Path, page: Page) -> None:
    orders = [
        Order(""),  # wiersz 18: bez NUMER ZL.
        Order("#8002", day=None),  # 19: bez daty w DATA
        Order("#8003"),  # 20: efenix go nie zna
        Order("#8004"),  # 21: dwa zlecenia o tym numerze
        Order("#8005"),  # 22: inny status
        Order("#8006"),  # 23: inny realizator
        Order("#8007"),  # 24: inny adres
        Order("#8008"),  # 25: inna data wykonania
        Order("#8009"),  # 26: zgodne, po wszystkich błędach
    ]
    efenix = [
        orders[1].in_efenix("902"),
        replace(orders[2].in_efenix("903"), number="80031"),
        orders[3].in_efenix("904"),
        orders[3].in_efenix("914"),
        replace(orders[4].in_efenix("905"), status="Do akceptacji"),
        replace(orders[5].in_efenix("906"), realizator="zenon.testowy"),
        replace(orders[6].in_efenix("907"), address="Miasto-Dzielnica ul.Testowa 14 Lokal 3"),
        replace(orders[7].in_efenix("908"), execution_date=date(2026, 9, 10)),
        replace(orders[8].in_efenix("909"), execution_date=DAY),
    ]
    with atrapa_efenix(efenix) as atrapa:
        before = atrapa.state()
        outcome = _price(tmp_path, page, atrapa.url, orders)
        after = atrapa.state()

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(9, 1))
    # Wiersz bez daty idzie na koniec swojego Wykonawcy, więc błędy są w kolejności wierszy dopiero po sortowaniu.
    assert sorted(_errors(outcome), key=lambda error: error[1]) == [
        ("EFENIX_BRAK_NUMERU", "wiersz 18"),
        ("EFENIX_BRAK_DATY", "wiersz 19"),
        ("EFENIX_NIEZNANY_NUMER", "wiersz 20"),
        ("EFENIX_KILKA_ZLECEN", "wiersz 21"),
        ("EFENIX_INNY_STATUS", "wiersz 22"),
        ("EFENIX_INNY_REALIZATOR", "wiersz 23"),
        ("EFENIX_INNY_ADRES", "wiersz 24"),
        ("EFENIX_INNA_DATA", "wiersz 25"),
    ]
    assert after == before


@pytest.mark.parametrize(
    ("efenix_address", "found"),
    [
        pytest.param("Poznań-Wilda ul.Kowalskiego Jana 12A Lokal 34", True, id="słowa-w-innej-kolejności-i-Lokal"),
        pytest.param("Poznań-Wilda ul.Jana Kowalskiego 12A Lokal 35", False, id="inny-lokal"),
        pytest.param("Poznań-Wilda ul.Jana Kowalskiego 12B Lokal 34", False, id="inny-numer"),
        pytest.param("Poznań-Wilda ul.Jana Kowalskiej 12A Lokal 34", False, id="inne-słowo"),
        pytest.param("Poznań-Wilda os.Jana Kowalskiego 12A Lokal 34", False, id="inny-rodzaj"),
    ],
)
def test_dane_adresowe_efenix_to_adres_z_pliku_w_dowolnej_kolejnosci_slow_z_lokalem_i_tylko_wtedy(
    tmp_path: Path, page: Page, efenix_address: str, found: bool
) -> None:
    order = Order("#9001", address="UL. JANA KOWALSKIEGO 12A/34", efenix_address=efenix_address)
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])

    assert _errors(outcome) == ([] if found else [("EFENIX_INNY_ADRES", "wiersz 18")])


def test_plik_bez_kwot_au_policzonych_przez_excel_zatrzymuje_wycene_zanim_otworzy_efenix(tmp_path: Path, page: Page) -> None:
    orders = [Order("#9101"), Order("#9102", amount=None)]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        requested = atrapa.requested()

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), outcome.ending.message.where.rpartition(", ")[2], requested) == ("EFENIX_KWOTY_NIEPOLICZONE", "wiersz 19", [])
    assert "Otwórz i zapisz Plik zbiorczy w Excelu" in outcome.ending.message.action


def test_strona_logowania_przed_szukaniem_albo_w_trakcie_zatrzymuje_wycene(tmp_path: Path, page: Page) -> None:
    orders = [Order("#9201"), Order("#9202"), Order("#9203")]
    efenix = [order.in_efenix(f"90{index}") for index, order in enumerate(orders)]
    with atrapa_efenix(efenix) as logged_out:
        logged_out.expire_session()
        at_start = _price(tmp_path / "start", page, logged_out.url, orders)
    with atrapa_efenix(efenix, expire_after_searches=1) as expiring:
        midway = _price(tmp_path / "w-trakcie", page, expiring.url, orders)
        searched = expiring.searched()

    assert (_stop(at_start), _stop(midway), searched) == ("EFENIX_WYLOGOWANY", "EFENIX_WYLOGOWANY", ["9201", "9202"])


def test_strona_bez_listy_zlecen_i_adres_bez_efenix_zatrzymuja_wycene(tmp_path: Path, page: Page) -> None:
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{unused.getsockname()[1]}/{LIST_PAGE}"
    with atrapa_efenix([Order("#9301").in_efenix("901")]) as atrapa:
        changed = _price(tmp_path / "zmieniony", page, atrapa.url.replace(LIST_PAGE, "inna_strona.php"), [Order("#9301")])
    unreachable = _price(tmp_path / "niedostepny", page, closed, [Order("#9301")])

    assert (_stop(changed), _stop(unreachable)) == ("EFENIX_ZMIENIONY", "EFENIX_NIEDOSTEPNY")
