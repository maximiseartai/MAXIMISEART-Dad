"""Wycena w efenix przez rdzeń Uruchomienia procesu na Atrapie efenix w prawdziwej przeglądarce (spec #741, #743, #746).

Każdy test prowadzi ``run_process`` z opisem procesu ``efenix_process.PROCESS`` i oknem efenix na karcie Chromium, a
sprawdza to, co widać z zewnątrz: wynik, Komunikaty, liczby podsumowania, żądania, które dostała Atrapa efenix, i jej
stan po przebiegu (ilości, data wykonania, załadowania Wyceny Emmetta, zmiany statusu). Przypisanie kolumn do pozycji
testy piszą literałami ze specyfikacji #741 (O→012, T→019, Z→010, AG→015). Wynik w kształcie karty Uruchomienia
sprawdza Skrypt dla maszyn (``tests/test_uruchom_proces.py``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import socket

from playwright.sync_api import Browser, Page
import pytest

from rozliczenia import efenix_browser, efenix_process
from rozliczenia.efenix_pricing import PricingSummary
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.process_run import Finished, Outcome, Stop, run_process

from tests.fixtures.atrapa_efenix import (
    LIST_PAGE,
    LOAD_EMMETT,
    ORDER_PAGE,
    SAVE_QUANTITY,
    SEARCH,
    SET_DATE,
    AtrapaEfenix,
    Changed,
    amount_of,
    atrapa_efenix,
)
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
    """Liczby podsumowania: zlecenia w zakresie, gotowe, błędy, ostrzeżenia Emmetta i pominięte."""

    assert isinstance(outcome.ending, Finished), outcome.ending
    assert outcome.view is not None
    summary = outcome.view
    return {
        "zakres": len(summary.results),
        "gotowe": summary.ready_count,
        "błędy": summary.error_count,
        "ostrzeżenia": summary.warning_count,
        "ze zdjęciami": summary.with_photos,
        "usterki": summary.defects,
    }


def _errors(outcome: Priced) -> list[tuple[str, str]]:
    """Kod i wiersz Pliku zbiorczego każdego błędu zlecenia i ostrzeżenia Emmetta."""

    assert outcome.view is not None
    return [(warning.code, warning.where.rpartition(", ")[2]) for warning in outcome.view.warnings]


def _what(outcome: Priced) -> list[str]:
    assert outcome.view is not None
    return [warning.what for warning in outcome.view.warnings]


def _pricing(atrapa: AtrapaEfenix) -> dict[str, tuple[dict[str, int], date | None, int]]:
    """Stan wyceny każdego zlecenia Atrapy: ilości, data wykonania i liczba załadowań Wyceny Emmetta."""

    orders, _logged_in = atrapa.state()
    return {order.number: (order.quantities, order.execution_date, order.emmett_loads) for order in orders}


def _stop(outcome: Priced) -> str:
    assert isinstance(outcome.ending, Stop), outcome.ending
    assert outcome.ending.kind == "stop"
    return outcome.ending.message.code


def _figures_of(orders: int, ready: int, warnings: int = 0, photos: int = 0, defects: int = 0) -> dict[str, int]:
    return {
        "zakres": orders,
        "gotowe": ready,
        "błędy": orders - ready - warnings,
        "ostrzeżenia": warnings,
        "ze zdjęciami": photos,
        "usterki": defects,
    }


def _au(quantities: dict[str, int]) -> float:
    """``Kwota`` (AU) zlecenia z ilościami ``quantities`` (kod pozycji → ilość) w cenach Atrapy."""

    return float(amount_of(quantities))


def test_zlecenie_z_wycena_zgodna_z_plikiem_jest_gotowe_a_efenix_dostaje_tylko_szukanie_i_otwarcie_zlecenia(
    tmp_path: Path, page: Page
) -> None:
    """Wycena już jest, każda ilość i kwota zgadzają się z plikiem: proces niczego nie zmienia, także pustej daty."""

    orders = [
        Order("#5001", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), quantities={"012": 1, "019": 2}),
        Order("#5002", cells={"AG": 3}, amount=_au({"015": 3}), quantities={"015": 3}, emmett={"015": 1}),
        Order("5003", cells={"Z": 1}, amount=_au({"010": 1}), quantities={"010": 1}),
    ]
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


@pytest.mark.parametrize(
    ("in_efenix", "positions"),
    [
        pytest.param({"012": 1, "019": 1}, "pozycja INDEKS_019 (kolumna T)", id="inna-ilość"),
        pytest.param({"012": 1, "019": 2, "005": 1}, "pozycja INDEKS_005 (bez kolumny w Pliku zbiorczym)", id="pozycja-bez-kolumny"),
        pytest.param({"012": 1, "019": 2}, None, id="ilości-zgodne-kwota-inna"),
    ],
)
def test_wycena_ktora_juz_jest_i_rozni_sie_od_pliku_to_blad_z_kwotami_bez_zmian_i_bez_emmetta(
    tmp_path: Path, page: Page, in_efenix: dict[str, int], positions: str | None
) -> None:
    au = _au({"012": 1, "019": 2}) + (0 if positions else 1)
    order = Order("#5101", cells={"O": 1, "T": 2}, amount=au, quantities=in_efenix, emmett={"012": 1, "019": 2})
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        before = atrapa.state()
        outcome = _price(tmp_path, page, atrapa.url, [order])
        after = atrapa.state()
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [("EFENIX_WYCENA_INNA", "wiersz 18")])
    [what] = _what(outcome)
    assert f"kwota w efenix {amount_of(in_efenix):.2f} zł".replace(".", ",") in what
    assert f"Kwota (AU) {Decimal(str(au)):.2f} zł".replace(".", ",") in what
    assert (positions is None) == ("Inne ilości" not in what)
    assert positions is None or positions in what
    assert (after, set(requested) <= READING) == (before, True)


def test_pusta_wycena_dostaje_date_z_data_wycene_emmetta_i_ilosci_z_pliku_w_pustych_pozycjach_a_kwota_rowna_au_daje_gotowe(
    tmp_path: Path, page: Page
) -> None:
    """Emmett wpisał O (012) zgodnie z plikiem; proces dopisuje T (019) i AG (015), a Z z 0 w pliku zostaje puste.

    Data wykonania jest ustawiana z ``DATA`` tylko w zleceniu, które jej nie miało.
    """

    filled = {"012": 1, "019": 2, "015": 1}
    orders = [
        Order("#5201", day=date(2026, 9, 3), cells={"O": 1, "T": 2, "AG": 1, "Z": 0}, amount=_au(filled), emmett={"012": 1}),
        # AU z ułamkiem binarnym, jaki zostawia suma Excela: równa kwocie efenix co do grosza.
        Order("#5202", cells={"O": 2}, amount=_au({"012": 2}) + 1e-9, emmett={"012": 2}),
    ]
    with atrapa_efenix([orders[0].in_efenix("901"), replace(orders[1].in_efenix("902"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        pricing = _pricing(atrapa)
        requested = atrapa.requested()
        changes = atrapa.status_changes()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(2, 2), [])
    assert pricing == {"5201": (filled, date(2026, 9, 3), 1), "5202": ({"012": 2}, DAY, 1)}
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", SAVE_QUANTITY)), changes) == (1, 2, 0)


def test_kwota_efenix_inna_niz_au_po_dopisaniu_ilosci_to_blad_z_obiema_kwotami(tmp_path: Path, page: Page) -> None:
    order = Order("#5301", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}) + 5, emmett={"012": 1})
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [("EFENIX_INNA_KWOTA", "wiersz 18")])
    assert pricing == {"5301": ({"012": 1, "019": 2}, DAY, 1)}
    [what] = _what(outcome)
    efenix_amount, au = amount_of({"012": 1, "019": 2}), amount_of({"012": 1, "019": 2}) + 5
    assert f"kwota w efenix to {efenix_amount:.2f} zł, a Kwota (AU) {au:.2f} zł".replace(".", ",") in what


@pytest.mark.parametrize(
    ("emmett", "conflict"),
    [
        pytest.param({"012": 2}, "pozycja INDEKS_012 (kolumna O): Emmett 2, plik 1", id="inna-ilość"),
        pytest.param({"012": 1, "013": 1}, "pozycja INDEKS_013 (kolumna P): Emmett 1, plik 0", id="0-w-pliku"),
        pytest.param({"012": 1, "020": 1}, "pozycja INDEKS_020 (bez kolumny w Pliku zbiorczym): Emmett 1, plik 0", id="pozycja-bez-kolumny"),
    ],
)
def test_ilosc_emmetta_inna_niz_w_pliku_to_ostrzezenie_z_pozycja_a_proces_niczego_nie_dopisuje(
    tmp_path: Path, page: Page, emmett: dict[str, int], conflict: str
) -> None:
    order = Order("#5401", cells={"O": 1, "P": 0, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett=emmett)
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == (
        "WYMAGA_SPRAWDZENIA",
        _figures_of(1, 0, warnings=1),
        [("EFENIX_SPRZECZNOSC_Z_EMMETTEM", "wiersz 18")],
    )
    assert conflict in _what(outcome)[0]
    assert (pricing, ("POST", SAVE_QUANTITY) in requested) == ({"5401": (emmett, DAY, 1)}, False)


@pytest.mark.parametrize(
    ("cells", "error"),
    [
        pytest.param({"O": 1, "N": 1}, "EFENIX_KOLUMNA_BEZ_POZYCJI", id="kolumna-N-bez-pary"),
        pytest.param({"AR": 2}, "EFENIX_KOLUMNA_BEZ_POZYCJI", id="kolumna-AR-bez-pary"),
        pytest.param({"O": "tak"}, "EFENIX_ILOSC_NIECALKOWITA", id="ilość-słowem"),
        pytest.param({"O": -1}, "EFENIX_ILOSC_NIECALKOWITA", id="ilość-ujemna"),
    ],
)
def test_ilosc_ktorej_nie_da_sie_przepisac_do_efenix_to_blad_zlecenia_zanim_proces_go_szuka(
    tmp_path: Path, page: Page, cells: dict[str, int | str], error: str
) -> None:
    orders = [Order("#5501", cells=cells, amount=100.0), Order("#5502")]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched = atrapa.searched()

    assert (_figures(outcome), _errors(outcome), searched) == (_figures_of(2, 1), [(error, "wiersz 18")], ["5502"])


def test_szukanie_ktore_lista_efenix_wysyla_sama_po_powrocie_ze_strony_zlecenia_nie_zmienia_wynikow_szukania(
    tmp_path: Path, page: Page
) -> None:
    """Efenix odpowiada wolno, więc szukanie poprzedniego numeru, które lista wysyła sama po wczytaniu, trwa jeszcze,
    gdy okno szuka następnego zlecenia, i jego odpowiedź przychodzi pierwsza."""

    orders = [Order("#5101"), Order("#5102"), Order("#5103")]
    with atrapa_efenix([order.in_efenix(f"91{index}") for index, order in enumerate(orders)], answer_delay_s=0.3) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        searched, by_list = atrapa.searched(), atrapa.searched_by_list()

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("OK", _figures_of(3, 3), [])
    assert (searched, by_list) == (["5101", "5102", "5103"], ["5101", "5102"])


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
        Order("#8009", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),  # 26: gotowe, po wszystkich błędach
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


@pytest.mark.parametrize(
    ("expire_after", "searched"),
    [
        pytest.param(None, [], id="przed-szukaniem"),
        pytest.param((SEARCH, 1), ["9201", "9202"], id="przy-szukaniu"),
        # Strona pierwszego zlecenia otwiera się dwa razy: przy otwarciu i po załadowaniu Wyceny Emmetta.
        pytest.param((ORDER_PAGE, 2), ["9201", "9202"], id="przy-otwarciu-zlecenia"),
        pytest.param((SET_DATE, 1), ["9201", "9202"], id="przy-dacie-wykonania"),
        pytest.param((LOAD_EMMETT, 1), ["9201", "9202"], id="przy-wycenie-emmetta"),
        pytest.param((SAVE_QUANTITY, 1), ["9201", "9202"], id="przy-zapisie-ilości"),
    ],
)
def test_strona_logowania_przed_szukaniem_albo_w_trakcie_zatrzymuje_wycene(
    tmp_path: Path, page: Page, expire_after: tuple[str, int] | None, searched: list[str]
) -> None:
    orders = [Order(f"#920{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)], expire_after=expire_after) as atrapa:
        if expire_after is None:
            atrapa.expire_session()
        outcome = _price(tmp_path, page, atrapa.url, orders)

        assert (_stop(outcome), atrapa.searched()) == ("EFENIX_WYLOGOWANY", searched)


@pytest.mark.parametrize("changed", list(Changed))
def test_inna_budowa_tabeli_wynikow_albo_strony_zlecenia_zatrzymuje_wycene(tmp_path: Path, page: Page, changed: Changed) -> None:
    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)], changed=changed) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        changes = atrapa.status_changes()

    assert (_stop(outcome), changes) == ("EFENIX_ZMIENIONY", 0)


def test_strona_bez_listy_zlecen_i_adres_bez_efenix_zatrzymuja_wycene(tmp_path: Path, page: Page) -> None:
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{unused.getsockname()[1]}/{LIST_PAGE}"
    with atrapa_efenix([Order("#9301").in_efenix("901")]) as atrapa:
        changed = _price(tmp_path / "zmieniony", page, atrapa.url.replace(LIST_PAGE, "inna_strona.php"), [Order("#9301")])
    unreachable = _price(tmp_path / "niedostepny", page, closed, [Order("#9301")])

    assert (_stop(changed), _stop(unreachable)) == ("EFENIX_ZMIENIONY", "EFENIX_NIEDOSTEPNY")
