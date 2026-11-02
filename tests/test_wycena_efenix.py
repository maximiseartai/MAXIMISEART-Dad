"""Wycena w efenix przez rdzeń Uruchomienia procesu na Atrapie efenix w prawdziwej przeglądarce (spec #741, #743, #746, #747).

Każdy test prowadzi ``run_process`` z opisem procesu ``efenix_process.PROCESS`` i oknem efenix na karcie Chromium, a
sprawdza to, co widać z zewnątrz: wynik, Komunikaty, liczby podsumowania, żądania, które dostała Atrapa efenix, jej
stan po przebiegu (ilości, data wykonania, załadowania Wyceny Emmetta, zmiany statusu) i Plik zbiorczy po przebiegu
(Znaczniki efenix czytane tą samą drogą co Przebieg rozliczeń, ``read_data_rows``, i części zip pliku). Przypisanie kolumn do pozycji
testy piszą literałami ze specyfikacji #741 (O→012, T→019, Z→010, AG→015). Wynik w kształcie karty Uruchomienia
sprawdza Skrypt dla maszyn (``tests/test_uruchom_proces.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager, nullcontext
from copy import copy
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import hashlib
import itertools
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import zipfile

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection

from playwright.sync_api import Browser, Page, Route
import pytest

from rozliczenia import TOOL_ROOT, efenix_browser, efenix_process
from rozliczenia.domain import ProgressPhase
from rozliczenia.efenix_mark import MARK_RGB
from rozliczenia.efenix_pace import KEEPALIVE_S, Pace
from rozliczenia.efenix_pricing import LoggedOut, Login, PagePart, PricingSummary
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.engine import run_settlements
from rozliczenia.process_run import Finished, Outcome, Stop, run_process
from rozliczenia.progress import ProgressSnapshot, SavingStep
from rozliczenia.workbook_files import excel_lock_file, read_computed_rows, read_data_rows

from tests.fixtures.atrapa_efenix import (
    LIST_PAGE,
    LIST_SCRIPT,
    LOAD_EMMETT,
    ORDER_PAGE,
    ORDER_SCRIPT,
    FILL_EMMETT,
    SAVE_QUANTITY,
    SEARCH,
    SET_DATE,
    AtrapaEfenix,
    AtrapaOrder,
    Changed,
    Outage,
    amount_of,
    atrapa_efenix,
)
from tests.fixtures.efenix import DAY, Order, number_in_trace, write_collective_file
from tests.fixtures.interlocutor import Tata
from tests.fixtures.przegladarka import chromium, page_of
from tests.fixtures.settlement import PERIOD, write_mapping, write_template
from tests.fixtures.workbooks import active_worksheet, rewrite_parts

# Żądania, które niczego w efenix nie zmieniają: lista zleceń, szukanie, strona zlecenia i skrypty obu stron.
READING = {("GET", LIST_PAGE), ("POST", SEARCH), ("GET", ORDER_PAGE), ("GET", LIST_SCRIPT), ("GET", ORDER_SCRIPT)}
Priced = Outcome[PricingSummary]


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with chromium() as launched:
        yield launched


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    with page_of(browser) as opened:
        yield opened


def _price(tmp_path: Path, page: Page, url: str, orders: Sequence[Order], *, timeout_ms: int = 10_000) -> Priced:
    return _run(write_collective_file(tmp_path, orders), page, url, timeout_ms=timeout_ms)


def _run(
    source: Path,
    page: Page,
    url: str,
    *,
    timeout_ms: int = 10_000,
    meanwhile: Callable[[], None] = lambda: None,
    pace: Pace | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Priced:
    """Uruchomienie Wyceny w efenix dla Pliku zbiorczego ``source``; ``meanwhile`` to to, co tata zrobił z plikiem, zanim
    proces skończył ostatnie zlecenie. Tempo ludzkie jest wyłączone, chyba że test poda ``pace``, a ``clock`` to zegar
    czasów etapów i śladu działań okna. Ślad Wyceny Emmetta leży w ``_traces(source)``, więc każde Uruchomienie dla tego
    samego pliku czyta ślad poprzedniego.

    Błąd okna efenix (np. ``UnexpectedPage``) trafia na stderr testu ze swoją przyczyną z Playwrighta, bo Zatrzymanie w
    wyniku mówi tylko, w której części strony stanęło, a porażka testu pokazuje stderr. Z samego Zatrzymania nie dało się
    ustalić przyczyny porażek #767 i #768 na Windows."""

    @contextmanager
    def open_efenix(_login: Login) -> Iterator[efenix_browser.BrowserEfenix]:
        try:
            with efenix_browser.window(page, url, timeout_ms=timeout_ms) as efenix:
                yield efenix
        except Exception as error:
            print("Błąd okna efenix:", "".join(traceback.format_exception(error)), sep="\n", file=sys.stderr)
            raise
        meanwhile()

    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(source, open_efenix, pace=pace, trace_directory=_traces(source), clock=clock),
        Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=source.parent.parent / "metryki.jsonl",
    )


def _traces(source: Path) -> Path:
    """Folder Śladów Wyceny Emmetta testu z Plikiem zbiorczym ``source``, obok jego Folderu okresu."""

    return source.parent.parent / "slad"


def _figures(outcome: Priced) -> dict[str, int]:
    """Liczby podsumowania: zlecenia w zakresie, gotowe, błędy, ostrzeżenia Emmetta i pominięte."""

    assert isinstance(outcome.ending, Finished), _ending(outcome)
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


def _ending(outcome: Priced) -> str:
    """Zakończenie przebiegu w komunikacie porażki: przy Zatrzymaniu jego kod i „Gdzie” z częścią strony efenix, które
    pełny zapis Zatrzymania w porażce testu ucina (#768)."""

    if isinstance(outcome.ending, Stop):
        return f"Zatrzymanie {outcome.ending.message.code} | {outcome.ending.message.where}"
    return repr(outcome.ending)


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
    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert outcome.ending.kind == "stop"
    return outcome.ending.message.code


def _kept(outcome: Priced) -> bool:
    """Komunikat Zatrzymania mówi, że wycena zleceń sprzed niego została w efenix (``False``: że nic się nie zmieniło)."""

    assert isinstance(outcome.ending, Stop), outcome.ending
    what = outcome.ending.message.what
    kept, unchanged = "Wycena zleceń sprzed zatrzymania została w efenix." in what, "W efenix nic się nie zmieniło." in what
    assert kept != unchanged, what
    return kept


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
    ("in_efenix", "executed", "positions"),
    [
        pytest.param({"012": 1, "019": 1}, None, "pozycja INDEKS_019 (kolumna T)", id="inna-ilość"),
        pytest.param({"012": 2}, DAY, "pozycja INDEKS_012 (kolumna O), pozycja INDEKS_019 (kolumna T)", id="inna-ilość-z-datą"),
        pytest.param(
            {"012": 1, "019": 2, "005": 1}, None, "pozycja INDEKS_005 (bez kolumny w Pliku zbiorczym)", id="pozycja-bez-kolumny"
        ),
        pytest.param({"012": 1, "019": 2}, DAY, None, id="ilości-zgodne-kwota-inna"),
        pytest.param({"012": 1}, None, "pozycja INDEKS_019 (kolumna T)", id="brak-ilości-bez-daty"),
        # Tata zaczął wycenę sam, bez Wyceny Emmetta: data jest, wpisane ilości zgadzają się z plikiem, a brakuje T. Bez
        # Śladu Wyceny Emmetta proces tylko porównuje, choć Emmett (019: 5) przeczyłby plikowi.
        pytest.param({"012": 1}, DAY, "pozycja INDEKS_019 (kolumna T)", id="wycena-zaczęta-przez-tatę"),
    ],
)
def test_wycena_ktora_juz_jest_i_rozni_sie_od_pliku_to_blad_z_kwotami_bez_zmian_i_bez_emmetta(
    tmp_path: Path, page: Page, in_efenix: dict[str, int], executed: date | None, positions: str | None
) -> None:
    au = _au({"012": 1, "019": 2}) + (0 if positions else 1)
    order = Order("#5101", cells={"O": 1, "T": 2}, amount=au, quantities=in_efenix, emmett={"012": 1, "019": 5})
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=executed)]) as atrapa:
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
    """Kwoty różnią się o 40 groszy: równość jest co do grosza, nie co do złotówki."""

    order = Order("#5301", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}) + 0.4, emmett={"012": 1})
    with atrapa_efenix([order.in_efenix("901")]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)

    assert (outcome.result, _figures(outcome), _errors(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(1, 0), [("EFENIX_INNA_KWOTA", "wiersz 18")])
    assert pricing == {"5301": ({"012": 1, "019": 2}, DAY, 1)}
    [what] = _what(outcome)
    efenix_amount, au = amount_of({"012": 1, "019": 2}), amount_of({"012": 1, "019": 2}) + Decimal("0.40")
    assert f"kwota w efenix to {efenix_amount:.2f} zł, a Kwota (AU) {au:.2f} zł".replace(".", ",") in what


@pytest.mark.parametrize(
    ("day", "result", "errors", "pricing"),
    [
        pytest.param(date(2026, 9, 1), "OK", [], ({"012": 1}, date(2026, 9, 1), 1), id="pierwszy-dzień-poprzedniego-miesiąca"),
        pytest.param(date(2026, 10, 12), "OK", [], ({"012": 1}, date(2026, 10, 12), 1), id="dziś"),
        pytest.param(
            date(2026, 8, 31), "WYMAGA_SPRAWDZENIA", [("EFENIX_DATA_POZA_ZAKRESEM", "wiersz 18")], ({}, None, 0), id="przed-poprzednim-miesiącem"
        ),
        pytest.param(date(2026, 10, 13), "WYMAGA_SPRAWDZENIA", [("EFENIX_DATA_POZA_ZAKRESEM", "wiersz 18")], ({}, None, 0), id="jutro"),
    ],
)
def test_dzien_z_data_spoza_zakresu_kalendarza_efenix_to_blad_bez_zapisu_daty_bez_emmetta_i_bez_ilosci(
    tmp_path: Path,
    page: Page,
    day: date,
    result: str,
    errors: list[tuple[str, str]],
    pricing: tuple[dict[str, int], date | None, int],
) -> None:
    """Kalendarz Atrapy ma za dziś 12 października 2026, więc efenix przyjmuje daty wykonania od 1 września do 12 października."""

    order = Order("#5601", day=day, cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("901")], today=date(2026, 10, 12)) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        after = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _errors(outcome), after) == (result, errors, {"5601": pricing})
    assert requested.count(("POST", SET_DATE)) == (1 if result == "OK" else 0)


def test_data_wykonania_ktorej_efenix_nie_zapisal_po_potwierdz_to_blad_bez_emmetta_i_bez_ilosci(tmp_path: Path, page: Page) -> None:
    """Skrypt strony wpisuje dzień do ``#data_install`` po każdej odpowiedzi, także gdy serwer daty nie zapisał."""

    order = Order("#5701", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([order.in_efenix("901")], refuse_dates=True) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order])
        pricing = _pricing(atrapa)
        requested = atrapa.requested()

    assert (outcome.result, _errors(outcome), pricing) == ("WYMAGA_SPRAWDZENIA", [("EFENIX_DATA_NIEZAPISANA", "wiersz 18")], {"5701": ({}, None, 0)})
    assert (requested.count(("POST", SET_DATE)), requested.count(("POST", LOAD_EMMETT)), requested.count(("POST", SAVE_QUANTITY))) == (1, 0, 0)


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
    ("expire_after", "searched", "kept"),
    [
        pytest.param(None, [], False, id="przed-szukaniem"),
        pytest.param((ORDER_PAGE, 0), ["9201"], False, id="przy-otwarciu-pierwszego-zlecenia"),
        pytest.param((SEARCH, 1), ["9201", "9202"], True, id="przy-szukaniu"),
        # Strona pierwszego zlecenia otwiera się trzy razy: przy otwarciu, po dacie wykonania i po Wycenie Emmetta.
        pytest.param((ORDER_PAGE, 3), ["9201", "9202"], True, id="przy-otwarciu-zlecenia"),
        pytest.param((SET_DATE, 1), ["9201", "9202"], True, id="przy-dacie-wykonania"),
        pytest.param((LOAD_EMMETT, 1), ["9201", "9202"], True, id="przy-wycenie-emmetta"),
        pytest.param((SAVE_QUANTITY, 1), ["9201", "9202"], True, id="przy-zapisie-ilości"),
    ],
)
def test_strona_logowania_przed_szukaniem_albo_w_trakcie_zatrzymuje_wycene_a_komunikat_mowi_czy_cos_zmienila(
    tmp_path: Path, page: Page, expire_after: tuple[str, int] | None, searched: list[str], kept: bool
) -> None:
    orders = [Order(f"#920{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    with atrapa_efenix([order.in_efenix(f"90{index}") for index, order in enumerate(orders)], expire_after=expire_after) as atrapa:
        if expire_after is None:
            atrapa.expire_session()
        outcome = _price(tmp_path, page, atrapa.url, orders)

        assert (_stop(outcome), atrapa.searched(), _kept(outcome)) == ("EFENIX_WYLOGOWANY", searched, kept)


# Część strony, której zabrakło przy każdej zmianie budowy Atrapy: tabela wyników, strona zlecenia, okno daty wykonania,
# Emmett albo kwota.
CHANGED_PART = {
    Changed.STATUS_HEADER: PagePart.RESULTS,
    Changed.ORDER_LINK: PagePart.RESULTS,
    Changed.DATE_FORMAT: PagePart.ORDER,
    Changed.DATE_DIALOG: PagePart.DATE,
    Changed.EMMETT_BUTTON: PagePart.EMMETT,
    Changed.HIDDEN_EMMETT: PagePart.EMMETT,
    Changed.POSITION_CODE: PagePart.ORDER,
    Changed.STALE_AMOUNT: PagePart.QUANTITY,
    Changed.QUANTITY_ANSWER: PagePart.QUANTITY,
}


@pytest.mark.parametrize("changed", list(Changed))
def test_inna_budowa_tabeli_wynikow_albo_strony_zlecenia_zatrzymuje_wycene_do_maksa_z_czescia_strony(
    tmp_path: Path, page: Page, changed: Changed
) -> None:
    """Zatrzymanie przychodzi w czasie okna (tu 3 s), także przy elemencie obecnym, ale niewidocznym.

    Tylko zapis ilości (kwota, która się nie odświeża, i odpowiedź w innym zapisie) zatrzymuje wycenę po zmianie w efenix
    (Wycena Emmetta i ilość). Zatrzymanie jest „do Maksa”, więc Centrum daje przy nim Diagnozę i Zgłoszenie, a „Gdzie”
    nazywa część strony, której zabrakło.
    """

    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    # Okno daty wykonania okno efenix otwiera tylko przy pustej dacie wykonania w efenix.
    in_efenix = replace(order.in_efenix("901"), execution_date=None if changed is Changed.DATE_DIALOG else DAY)
    with atrapa_efenix([in_efenix], changed=changed) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)
        changes = atrapa.status_changes()

    assert (_stop(outcome), changes, _kept(outcome)) == ("EFENIX_ZMIENIONY", 0, changed in (Changed.STALE_AMOUNT, Changed.QUANTITY_ANSWER))
    assert isinstance(outcome.ending, Stop)
    message = outcome.ending.message
    assert (outcome.ending.stop_kind, message.where) == ("for_maks", f"okno efenix, {CHANGED_PART[changed].value}")
    assert message.what.startswith("efenix się zmienił, Maks już wie.")


@pytest.mark.parametrize("changed", [Changed.HIDDEN_EMMETT, Changed.STALE_AMOUNT])
def test_zadanie_spoza_efenix_bez_odpowiedzi_nie_zmienia_innej_budowy_strony_w_brak_polaczenia(
    tmp_path: Path, page: Page, changed: Changed
) -> None:
    """Widżet spoza efenix na stronie (jak Mapy Google na stronie zlecenia), który co chwilę pyta swój serwer i nie dostaje
    odpowiedzi, nie chowa zmienionej strony efenix pod „brak połączenia z efenix”: to dalej Zatrzymanie do Maksa."""

    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    # Serwer widżetu przyjmuje połączenia, ale nigdy nie odpowiada.
    with socket.create_server(("127.0.0.1", 0), backlog=64) as silent:
        widget = f"http://127.0.0.1:{silent.getsockname()[1]}/widget"
        page.add_init_script(f"setInterval(() => fetch({json.dumps(widget)}, {{mode: 'no-cors'}}).catch(() => {{}}), 200)")
        with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)], changed=changed) as atrapa:
            outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert (_stop(outcome), outcome.ending.stop_kind, outcome.ending.message.where) == (
        "EFENIX_ZMIENIONY",
        "for_maks",
        f"okno efenix, {CHANGED_PART[changed].value}",
    )


# Skrypt strony, którego efenix już nie ma (usunięty albo przemianowany): efenix odpowiada na niego błędem HTTP od żądania
# ``from_request`` (licząc od zera) tego skryptu.
@pytest.mark.parametrize(
    ("script", "status", "from_request", "part"),
    [
        pytest.param(LIST_SCRIPT, 404, 0, PagePart.RESULTS, id="skrypt-listy-404"),
        pytest.param(LIST_SCRIPT, 500, 0, PagePart.RESULTS, id="skrypt-listy-500"),
        # Drugie otwarcie listy to szukanie drugiego zlecenia ze strony pierwszego, w tym samym działaniu okna co szukanie.
        pytest.param(LIST_SCRIPT, 404, 1, PagePart.RESULTS, id="skrypt-listy-404-przy-szukaniu"),
        pytest.param(ORDER_SCRIPT, 404, 0, PagePart.EMMETT, id="skrypt-zlecenia-404"),
        pytest.param(ORDER_SCRIPT, 500, 0, PagePart.EMMETT, id="skrypt-zlecenia-500"),
    ],
)
def test_skrypt_strony_ktorego_efenix_juz_nie_ma_to_zmieniony_efenix_a_nie_brak_polaczenia(
    tmp_path: Path, page: Page, script: str, status: int, from_request: int, part: PagePart
) -> None:
    """Przeglądarka zgłasza skrypt, na który efenix odpowiedział 404 albo 500, jako nieudany, tak jak zerwany, ale efenix
    odpowiedział: strona bez swojego skryptu to efenix, który się zmienił, z Diagnozą i Zgłoszeniem do Maksa, a nie
    „brak połączenia z efenix”, który tata dostawałby przy każdym ponownym uruchomieniu."""

    orders = [Order(f"#950{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2)]
    sent = itertools.count()

    def gone(route: Route) -> None:
        if next(sent) < from_request:
            route.continue_()
        else:
            route.fulfill(status=status, body="<p>Nie ma takiej strony.</p>", content_type="text/html")

    page.route(f"**/{script}*", gone)
    with atrapa_efenix([replace(order.in_efenix(f"90{index}"), execution_date=DAY) for index, order in enumerate(orders)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders, timeout_ms=3_000)

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert (_stop(outcome), outcome.ending.stop_kind, outcome.ending.message.where) == (
        "EFENIX_ZMIENIONY",
        "for_maks",
        f"okno efenix, {part.value}",
    )


def _on_efenix_pages(page: Page, tag: str) -> None:
    """Dokleja ``tag`` do ``<head>`` listy zleceń i strony zlecenia Atrapy, jak plik, który efenix ładuje na swoich stronach."""

    def add(route: Route) -> None:
        response = route.fetch()
        route.fulfill(response=response, body=response.text().replace("</head>", f"{tag}</head>", 1))

    for path in (LIST_PAGE, ORDER_PAGE):
        page.route(f"**/{path}*", add)


@pytest.mark.parametrize(
    "tag",
    [
        pytest.param('<link rel="stylesheet" href="css/usuniety.css">', id="martwy-arkusz-stylow-efenix"),
        pytest.param('<script src="js/usuniety.js"></script>', id="martwy-skrypt-efenix"),
        pytest.param('<link rel="stylesheet" href="https://use.fontawesome.com/releases/v5.15.4/css/all.css">', id="arkusz-fontawesome"),
        pytest.param('<script src="https://maps.googleapis.com/maps/api/js"></script>', id="skrypt-map-google"),
    ],
)
def test_martwy_link_efenix_i_plik_spoza_efenix_bez_odpowiedzi_nie_zatrzymuja_wyceny(tmp_path: Path, page: Page, tag: str) -> None:
    """Działająca strona efenix z linkiem do pliku, którego efenix już nie ma (Atrapa odpowiada na nieznany adres 404), albo
    z plikiem z innego serwera (fontawesome, Mapy Google), który nie odpowiada, wycenia zlecenie jak bez nich: martwy link
    to nie brak połączenia, a serwer spoza efenix nic nie mówi o połączeniu z efenix."""

    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    _on_efenix_pages(page, tag)
    # Serwery spoza efenix zrywają połączenie; Atrapa jest pod ``http://127.0.0.1``.
    page.route("https://**/*", lambda route: route.abort("connectionreset"))
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)

    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(1, 1))


@pytest.mark.parametrize(
    ("where", "load"),
    [
        pytest.param(LIST_PAGE, 1, id="lista"),
        pytest.param(ORDER_PAGE, 1, id="strona-zlecenia"),
        pytest.param(ORDER_PAGE, 2, id="przeladowanie-po-emmetcie"),
    ],
)
def test_milczacy_arkusz_spoza_efenix_przy_otwarciu_strony_to_brak_polaczenia_z_efenix(
    tmp_path: Path, page: Page, where: str, load: int
) -> None:
    """Strona efenix ładuje w ``<head>`` arkusze z innych serwerów (fontawesome, Google Fonts). Serwer, który przyjął
    żądanie i milczy, sprawia, że strona nie kończy się ładować, a to dla taty „brak połączenia z efenix”, nie zmieniony
    efenix ze Zgłoszeniem do Maksa."""

    loads: list[str] = []

    def add(route: Route) -> None:
        loads.append(route.request.url)
        response = route.fetch()
        body = response.text()
        if len(loads) == load:
            body = body.replace("</head>", '<link rel="stylesheet" href="https://use.fontawesome.com/all.css"></head>', 1)
        route.fulfill(response=response, body=body)

    held: list[Route] = []
    page.route(f"**/{where}*", add)
    page.route("https://**/*", lambda route: held.append(route))
    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)

    assert len(loads) >= load, loads
    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert (_stop(outcome), outcome.ending.stop_kind) == ("EFENIX_NIEDOSTEPNY", "for_tata")


def test_efenix_bez_przeladowania_po_zaladuj_do_zlecenia_to_zmieniony_efenix_dla_maksa(tmp_path: Path, page: Page) -> None:
    """Zmieniony efenix zapisuje Wycenę Emmetta po „Załaduj do zlecenia”, ale jego skrypt nie przeładowuje już strony.
    Przeładowanie, które się nie zaczęło, to nie brak połączenia, więc tata nie ponawia Wyceny bez końca, a Maks dostaje
    Zgłoszenie."""

    def no_reload(route: Route) -> None:
        response = route.fetch()
        body = response.text()
        changed = body.replace(".then(() => setTimeout(() => location.reload(),", ".then(() => setTimeout(() => null,", 1)
        assert changed != body, "skrypt strony zlecenia Atrapy przeładowuje stronę po Wycenie Emmetta"
        route.fulfill(response=response, body=changed)

    page.route(f"**/{ORDER_SCRIPT}*", no_reload)
    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert (_stop(outcome), outcome.ending.stop_kind) == ("EFENIX_ZMIENIONY", "for_maks")


def test_arkusz_stylow_efenix_bez_odpowiedzi_to_brak_polaczenia_z_efenix(tmp_path: Path, page: Page) -> None:
    """Arkusz stylów spod adresu efenix (strona zlecenia efenix ładuje ich sześć), który nie przyszedł, bo połączenie się
    zerwało, to „brak połączenia z efenix” dla taty, jak zerwany skrypt strony."""

    order = Order("#9501", cells={"O": 1}, amount=_au({"012": 1}))
    _on_efenix_pages(page, '<link rel="stylesheet" href="css/efenix.css">')
    page.route("**/css/efenix.css", lambda route: route.abort("connectionreset"))
    with atrapa_efenix([replace(order.in_efenix("901"), execution_date=DAY)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, [order], timeout_ms=3_000)

    assert isinstance(outcome.ending, Stop), _ending(outcome)
    assert (_stop(outcome), outcome.ending.stop_kind, _kept(outcome)) == ("EFENIX_NIEDOSTEPNY", "for_tata", False)


def test_zmieniona_strona_efenix_oznacza_gotowe_przed_nia_a_komunikat_do_maksa_nie_ma_numeru_adresu_ani_loginu(
    tmp_path: Path, page: Page
) -> None:
    """Wiersz 18 ma już wycenę zgodną z plikiem, a wiersz 19 czeka na Wycenę Emmetta, której przycisku efenix już nie ma.

    Komunikat Zatrzymania trafia do Zgłoszenia do Maksa i do Logów Uruchomienia, więc nie ma w nim niczego ze zlecenia.
    """

    orders = [
        Order("#9601", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9602", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    source = write_collective_file(tmp_path, orders)
    in_efenix = [order.in_efenix(f"96{index}") for index, order in enumerate(orders)]
    with atrapa_efenix(in_efenix, changed=Changed.EMMETT_BUTTON) as atrapa:
        outcome = _run(source, page, atrapa.url, timeout_ms=3_000)

    assert (_stop(outcome), _kept(outcome), _marked(source)) == ("EFENIX_ZMIENIONY", True, [18])
    assert isinstance(outcome.ending, Stop)
    text = outcome.ending.message.text
    private = [
        *(order.number for order in in_efenix),
        *(order.order_id for order in in_efenix),
        *(order.realizator for order in in_efenix),
        "Testowa",
        "TESTOWA",
        "Fikcyjny",
    ]
    assert (outcome.ending.stop_kind, [word for word in private if word in text]) == ("for_maks", [])


@dataclass
class _FakeTime:
    """Udawany czas tempa ludzkiego: stoi, a przesuwa go tylko przerwa (``pause``).

    Nie ``ManualClock`` z ``tests/fixtures/clock.py``: ten plik jest w zmianie wzorcowego PR C bramki, a jego import
    dołożyłby ten plik testów do toru C ponad limit (``tests/test_ksztalt_bramki.py``).
    """

    seconds: float = 0.0

    def __call__(self) -> float:
        return self.seconds

    def pause(self, seconds: float) -> None:
        self.seconds += seconds


def _closing_window(page: Page, clock: _FakeTime, at_pause: int) -> Pace:
    """Tempo na udawanym zegarze, w którym tata zamyka kartę efenix w przerwie numer ``at_pause``."""

    pauses = 0

    def sleep(seconds: float) -> None:
        nonlocal pauses
        clock.pause(seconds)
        pauses += 1
        if pauses == at_pause:
            page.close()

    return Pace(sleep=sleep, clock=clock)


@pytest.mark.parametrize(
    ("at_pause", "kept", "marked"),
    [
        # Przerwy: 1 przed szukaniem wiersza 18, 2 przed jego otwarciem, 3 przed szukaniem wiersza 19, 4 przed jego
        # otwarciem, 5 przed datą wykonania, 6 przed ponownym otwarciem po dacie, 7 przed Wyceną Emmetta, 8 przed ilością.
        pytest.param(1, False, [], id="przy-szukaniu-na-liście"),
        pytest.param(3, False, [18], id="między-zleceniami"),
        pytest.param(5, False, [18], id="przy-dacie-wykonania"),
        pytest.param(6, True, [18], id="po-dacie-wykonania"),
        pytest.param(7, True, [18], id="przy-wycenie-emmetta"),
        pytest.param(8, True, [18], id="przy-ilości"),
    ],
)
def test_zamkniete_okno_efenix_zatrzymuje_wycene_z_komunikatem_dla_taty_a_gotowe_przed_nim_maja_znacznik(
    tmp_path: Path, page: Page, at_pause: int, kept: bool, marked: list[int]
) -> None:
    orders = [
        Order("#9701", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9702", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1})),
    ]
    source = write_collective_file(tmp_path, orders)
    clock = _FakeTime()
    with atrapa_efenix([order.in_efenix(f"97{index}") for index, order in enumerate(orders)], clock=clock) as atrapa:
        outcome = _run(source, page, atrapa.url, pace=_closing_window(page, clock, at_pause))

    assert isinstance(outcome.ending, Stop)
    assert (_stop(outcome), outcome.ending.stop_kind, _kept(outcome), _marked(source)) == ("EFENIX_OKNO_ZAMKNIETE", "for_tata", kept, marked)


def test_w_tempie_ludzkim_zlecenie_trwa_20_s_a_przerwa_miedzy_dzialaniami_w_efenix_nie_przekracza_progu_podtrzymania_sesji(
    tmp_path: Path, page: Page
) -> None:
    """Na udawanym zegarze: zlecenie z Wyceną Emmetta trwa od szukania do szukania następnego 20 s (spec #741), a zlecenie
    z wyceną, która już jest (szukanie i otwarcie), nie czeka na następne dłużej niż próg podtrzymania sesji. Czas każdego
    działania okna w śladzie zlecenia do Logów Uruchomienia nie liczy przerwy przed nim, więc na zegarze, który przesuwa
    tylko przerwa, jest równy 0."""

    emmett = {"O": 1, "T": 2, "AG": 1}
    orders = [
        Order("#9801", day=date(2026, 9, 3), cells=emmett, amount=_au({"012": 1, "019": 2, "015": 1}), emmett={"012": 1}),
        Order("#9802", day=date(2026, 9, 4), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#9803", day=date(2026, 9, 5), cells=emmett, amount=_au({"012": 1, "019": 2, "015": 1}), emmett={"012": 1}),
    ]
    clock = _FakeTime()
    with atrapa_efenix([order.in_efenix(f"98{index}") for index, order in enumerate(orders)], clock=clock) as atrapa:
        source = write_collective_file(tmp_path, orders)
        outcome = _run(source, page, atrapa.url, pace=Pace(sleep=clock.pause, clock=clock), clock=clock)
        moments = atrapa.moments()

    searches = [at for at, path in moments if path == SEARCH]
    gaps = [later[0] - earlier[0] for earlier, later in itertools.pairwise(moments)]
    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(3, 3))
    # Ruch w oknie co kilkanaście sekund (spec #741): próg podtrzymania sesji jest krótszy niż 20 s.
    assert (searches[1] - searches[0], max(gaps) <= KEEPALIVE_S < 20) == (20, True)
    assert outcome.view is not None
    durations = [[step.duration_ms for step in result.steps] for result in outcome.view.results]
    assert [len(steps) for steps in durations] == [7, 2, 7]
    assert {duration for steps in durations for duration in steps} == {0}


def test_strona_bez_listy_zlecen_i_adres_bez_efenix_zatrzymuja_wycene(tmp_path: Path, browser: Browser, page: Page) -> None:
    """Strona efenix bez listy zleceń to efenix, który się zmienił, a adres, który nie odpowiada, także ten, pod który
    efenix przekierowuje listę zleceń, to brak połączenia: strona, która nie przyszła, nie ma budowy, którą efenix mógłby
    zmienić."""

    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{unused.getsockname()[1]}/{LIST_PAGE}"
    with atrapa_efenix([Order("#9301").in_efenix("901")]) as atrapa:
        changed = _price(tmp_path / "zmieniony", page, atrapa.url.replace(LIST_PAGE, "inna_strona.php"), [Order("#9301")])
        with page_of(browser) as redirecting:
            redirecting.route(atrapa.url, lambda route: route.fulfill(status=302, headers={"Location": closed}))
            redirected = _price(tmp_path / "przekierowany", redirecting, atrapa.url, [Order("#9301")])
    unreachable = _price(tmp_path / "niedostepny", page, closed, [Order("#9301")])

    assert (_stop(changed), _stop(unreachable), _stop(redirected)) == ("EFENIX_ZMIENIONY", "EFENIX_NIEDOSTEPNY", "EFENIX_NIEDOSTEPNY")
    assert (_kept(changed), _kept(unreachable), _kept(redirected)) == (False, False, False)


# --- Znacznik efenix w Pliku zbiorczym (#747) ------------------------------------------------------------------------

YELLOW = "FFFF00"
CHANGED_PARTS = {"xl/worksheets/sheet1.xml", "xl/styles.xml"}


def _parts(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def _address_fills(source: Path) -> dict[int, str | None]:
    """RGB jednolitego wypełnienia ``ADRES`` każdego Wiersza danych tak, jak czyta je Przebieg rozliczeń (``None``: bez)."""

    fills: dict[int, str | None] = {}
    for row in read_data_rows(source, despite_excel_lock=True).rows:
        fill = row.cells[1].highlights.fill
        solid = isinstance(fill, PatternFill) and fill.patternType == "solid"
        fills[row.number] = str(fill.fgColor.rgb)[-6:].upper() if solid and isinstance(fill, PatternFill) else None
    return fills


def _marked(source: Path) -> list[int]:
    return [row for row, rgb in _address_fills(source).items() if rgb == MARK_RGB]


def _address_looks(source: Path) -> dict[int, tuple[Font, Border, Protection, Alignment, str]]:
    """Wygląd ``ADRES`` każdego Wiersza danych poza wypełnieniem: czcionka, obramowanie, ochrona, wyrównanie, format."""

    workbook = load_workbook(source)
    try:
        sheet = active_worksheet(workbook)
        return {
            row: (copy(cell.font), copy(cell.border), copy(cell.protection), copy(cell.alignment), cell.number_format)
            for row in range(18, sheet.max_row + 1)
            if (cell := sheet[f"B{row}"]).value is not None
        }
    finally:
        workbook.close()


def _amounts(source: Path) -> dict[int, object]:
    """``Kwota`` (AU) każdego Wiersza danych tak, jak policzył ją Excel."""

    return {row.number: row.value("AU") for row in read_computed_rows(source).rows}


def _without_address_styles(xml: bytes, rows: Sequence[int]) -> bytes:
    """XML arkusza bez atrybutu ``s`` komórek ``ADRES`` wierszy ``rows``."""

    def neutral(found: re.Match[bytes]) -> bytes:
        return found.group(1) if int(found.group(2)) in rows else found.group(0)

    return re.sub(rb'(<c r="B(\d+)")(?: s="\d+")?', neutral, xml)


STYLE_LISTS = {b"fills": b"fill", b"cellXfs": b"xf"}


def _style_list(styles: bytes, tag: bytes) -> re.Match[bytes]:
    found = re.search(rb"<" + tag + rb'\b[^>]*?count="(\d+)"[^>]*>(.*?)</' + tag + rb">", styles, re.S)
    assert found is not None, tag
    return found


def _style_counts(styles: bytes) -> dict[bytes, int]:
    """Liczba wpisów każdej listy ``fills`` i ``cellXfs`` w ``xl/styles.xml``, zgodna z jej atrybutem ``count``."""

    counts = {}
    for tag, entry in STYLE_LISTS.items():
        found = _style_list(styles, tag)
        counts[tag] = len(re.findall(rb"<" + entry + rb"[\s>/]", found.group(2)))
        assert int(found.group(1)) == counts[tag], tag
    return counts


def _without_appended_styles(written: bytes, original: bytes) -> bytes:
    """``xl/styles.xml`` ``written`` z listami ``fills`` i ``cellXfs`` z ``original``, gdy ``written`` tylko dopisał do
    nich wpisy na końcu."""

    for tag in STYLE_LISTS:
        before, after = _style_list(original, tag), _style_list(written, tag)
        assert after.group(2).startswith(before.group(2)), tag
        written = written[: after.start()] + before.group(0) + written[after.end() :]
    return written


def _marking_orders() -> list[Order]:
    """Wiersze 18 i 19 gotowe (wycena już jest; dopisane ilości, ``ADRES`` bez stylu), 20 błąd kwoty, 21 sprzeczność z
    Emmettem, 22 Zlecenie ze zdjęciami, 23 nieznane efenix z żółtym ``ADRES`` taty.

    Wiersz 19 ma starszą ``DATA``, więc proces kończy go przed wierszem 18.
    """

    red = Font(name="Arial", sz=8, color="FFFF0000", b=True, i=True)
    return [
        Order("#7701", day=date(2026, 9, 10), cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_font=red),
        Order("#7702", day=date(2026, 9, 8), cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), address_font=None),
        Order("#7703", cells={"O": 1}, amount=_au({"012": 1}) + 5),
        Order("#7704", cells={"O": 1}, amount=_au({"012": 1}), emmett={"012": 2}),
        Order("#7705", cells={"AB": 1}),
        Order("#7706", address_fill=YELLOW),
    ]


def _marking_efenix(orders: Sequence[Order]) -> list[AtrapaOrder]:
    return [order.in_efenix(f"77{index}") for index, order in enumerate(orders) if order.number != "#7706"]


def test_znacznik_efenix_staje_tylko_w_adresie_gotowych_zlecen_a_reszta_pliku_zostaje_bajt_w_bajt(tmp_path: Path, page: Page) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    parts, looks, amounts = _parts(source), _address_looks(source), _amounts(source)
    with atrapa_efenix(_marking_efenix(orders)) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _figures(outcome)) == ("WYMAGA_SPRAWDZENIA", _figures_of(5, 2, warnings=1, photos=1))
    assert _address_fills(source) == {18: MARK_RGB, 19: MARK_RGB, 20: None, 21: None, 22: None, 23: YELLOW}
    # Poza wypełnieniem komórka ADRES ma swój wygląd, także czerwoną, pogrubioną kursywę taty w wierszu 18.
    assert _address_looks(source) == looks
    font = looks[18][0]
    assert (font.color.rgb if font.color else None, font.b, font.i) == ("FFFF0000", True, True)
    assert _amounts(source) == amounts
    written = _parts(source)
    assert [name for name, _ in written] == [name for name, _ in parts]
    before, after = dict(parts), dict(written)
    assert {name for name in before if before[name] != after[name]} == CHANGED_PARTS
    assert any(name.startswith("xl/externalLinks/") for name in before)
    sheet = "xl/worksheets/sheet1.xml"
    assert _without_address_styles(after[sheet], [18, 19]) == _without_address_styles(before[sheet], [18, 19])
    assert _without_appended_styles(after["xl/styles.xml"], before["xl/styles.xml"]) == before["xl/styles.xml"]
    # Jedno wypełnienie Znacznika i po jednym stylu na dwa dotychczasowe style gotowych ADRES.
    counts, original = _style_counts(after["xl/styles.xml"]), _style_counts(before["xl/styles.xml"])
    assert (counts[b"fills"] - original[b"fills"], counts[b"cellXfs"] - original[b"cellXfs"]) == (1, 2)


def test_nastepny_przebieg_na_pliku_ze_znacznikami_czyta_kwoty_au_ma_te_same_gotowe_i_niczego_nie_zmienia(
    tmp_path: Path, page: Page
) -> None:
    """Sprzeczność z Emmettem kończy w pierwszym przebiegu zlecenie z wiersza 21 (stan „gotowe” Śladu Wyceny Emmetta), więc
    drugi przebieg tylko porównuje jego wycenę: błąd „wycena już jest i się różni”, a w efenix nic się nie zmienia.

    Pierwszy przebieg musi dojść do końca: zatrzymany przed Wyceną Emmetta wiersza 21 zostawia ją drugiemu przebiegowi,
    który daje wtedy ostrzeżenie Emmetta zamiast błędu i myli porażkę z błędem drugiego przebiegu (#767)."""

    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix(_marking_efenix(orders)) as atrapa:
        first = _run(source, page, atrapa.url)
        assert _figures(first) == _figures_of(5, 2, warnings=1, photos=1)
        marked, saved, state, requests = source.read_bytes(), source.stat().st_mtime_ns, atrapa.state(), len(atrapa.requested())
        second = _run(source, page, atrapa.url)
        after, again = atrapa.state(), atrapa.requested()[requests:]

    assert (_figures(second), _marked(source), _amounts(source)[18]) == (_figures_of(5, 2, photos=1), [18, 19], _au({"012": 1}))
    # Błąd kwoty (20) i sprzeczność z Emmettem (21) skończyły zlecenie, więc drugi przebieg tylko porównuje ich wycenę.
    assert [error for error in _errors(second) if error[1] in {"wiersz 20", "wiersz 21"}] == [
        ("EFENIX_WYCENA_INNA", "wiersz 20"),
        ("EFENIX_WYCENA_INNA", "wiersz 21"),
    ]
    # Plik ze wszystkimi Znacznikami nie jest zapisywany od nowa, więc OneDrive nie dostaje nowej wersji.
    assert (source.read_bytes() == marked, source.stat().st_mtime_ns == saved) == (True, True)
    assert (after == state, set(again) <= READING) == (True, True)


def test_kolejne_uruchomienie_oznacza_nowe_gotowe_zlecenie_wypelnieniem_i_stylem_z_poprzedniego(
    tmp_path: Path, page: Page
) -> None:
    """Wiersz 19 jest gotowy dopiero w drugim przebiegu (w pierwszym efenix go nie zna), a jego ADRES ma ten sam styl co 18."""

    orders = [Order(f"#760{index}", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}) for index in (1, 2)]
    source = write_collective_file(tmp_path, orders)
    original = _style_counts(dict(_parts(source))["xl/styles.xml"])
    with atrapa_efenix([orders[0].in_efenix("761")]) as atrapa:
        first = _run(source, page, atrapa.url)
    marked_first = _marked(source)
    with atrapa_efenix([order.in_efenix(f"76{index}") for index, order in enumerate(orders)]) as atrapa:
        second = _run(source, page, atrapa.url)

    assert (first.result, marked_first, second.result, _marked(source)) == ("WYMAGA_SPRAWDZENIA", [18], "OK", [18, 19])
    counts = _style_counts(dict(_parts(source))["xl/styles.xml"])
    assert (counts[b"fills"] - original[b"fills"], counts[b"cellXfs"] - original[b"cellXfs"]) == (1, 1)


def test_znacznik_efenix_staje_na_aktywnej_karcie_ktora_czyta_wycena_a_inny_arkusz_zostaje(tmp_path: Path, page: Page) -> None:
    order = Order("#7401", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1})
    source = write_collective_file(tmp_path, [order], notes_sheet_first=True)
    notes = dict(_parts(source))["xl/worksheets/sheet1.xml"]
    with atrapa_efenix([order.in_efenix("741")]) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _marked(source), dict(_parts(source))["xl/worksheets/sheet1.xml"] == notes) == ("OK", [18], True)


def test_gotowe_zlecenie_z_adresem_juz_w_kolorze_znacznika_zostaje_a_plik_sie_nie_zmienia(tmp_path: Path, page: Page) -> None:
    order = Order("#7501", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}, address_fill=MARK_RGB)
    source = write_collective_file(tmp_path, [order])
    before = source.read_bytes()
    with atrapa_efenix([order.in_efenix("751")]) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _marked(source), source.read_bytes() == before) == ("OK", [18], True)


@contextmanager
def _excel_open(source: Path) -> Iterator[Callable[[], None]]:
    """Tata otwiera Plik zbiorczy w Excelu w trakcie przebiegu (plik blokady ``~$…``), a po przebiegu go zamyka."""

    lock = excel_lock_file(source)
    def open_in_excel() -> None:
        lock.write_bytes(b"")

    yield open_in_excel
    lock.unlink(missing_ok=True)


@contextmanager
def _saved_in_excel(source: Path) -> Iterator[Callable[[], None]]:
    """Tata zapisuje w trakcie przebiegu Plik zbiorczy ze zmienioną komórką."""

    def save() -> None:
        rewrite_parts(source, lambda name, data: data.replace(b">MIASTO<", b">MIASTA<") if name == "xl/worksheets/sheet1.xml" else data)

    yield save


@contextmanager
def _read_only_folder(source: Path) -> Iterator[Callable[[], None]]:
    """Folder okresu przestaje przyjmować nowe pliki w trakcie przebiegu (np. OneDrive go trzyma), a potem znów je przyjmuje."""

    folder = source.parent
    yield lambda: folder.chmod(0o555)
    folder.chmod(0o755)


@pytest.mark.parametrize(
    ("obstacle", "code"),
    [
        pytest.param(_excel_open, "EFENIX_ZNACZNIKI_PLIK_OTWARTY", id="otwarty-w-excelu"),
        pytest.param(_saved_in_excel, "EFENIX_ZNACZNIKI_PLIK_ZMIENIONY", id="zapisany-w-trakcie"),
        pytest.param(
            _read_only_folder,
            "EFENIX_ZNACZNIKI_NIEZAPISANE",
            id="zapis-nieudany",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="chmod folderu nie odbiera zapisu na Windows"),
        ),
    ],
)
def test_plik_ktorego_nie_da_sie_oznaczyc_daje_komunikat_a_ponowne_uruchomienie_stawia_znaczniki_bez_zmian_w_efenix(
    tmp_path: Path, page: Page, obstacle: Callable[[Path], AbstractContextManager[Callable[[], None]]], code: str
) -> None:
    orders = [
        Order("#7801", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#7802", cells={"O": 1}, amount=_au({"012": 1})),
        Order("#7803", cells={"O": 1}, amount=_au({"012": 1}) + 5),
    ]
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix([order.in_efenix(f"78{index}") for index, order in enumerate(orders)]) as atrapa:
        with obstacle(source) as meanwhile:
            stopped = _run(source, page, atrapa.url, meanwhile=meanwhile)
            unmarked = source.read_bytes()
            assert (_stop(stopped), _marked(source)) == (code, [])
        priced, requests = atrapa.state(), len(atrapa.requested())
        assert source.read_bytes() == unmarked
        again = _run(source, page, atrapa.url)
        after, repeated = atrapa.state(), atrapa.requested()[requests:]

    assert {order.number: (order.quantities, order.execution_date, order.emmett_loads) for order in priced[0]} == {
        "7801": ({"012": 1}, None, 0),
        "7802": ({"012": 1}, DAY, 1),
        "7803": ({"012": 1}, DAY, 1),
    }
    assert (again.result, _figures(again), _marked(source)) == ("WYMAGA_SPRAWDZENIA", _figures_of(3, 2), [18, 19])
    assert (after == priced, set(repeated) <= READING) == (True, True)


@pytest.mark.parametrize(
    ("expire_after", "marked"),
    [
        pytest.param((SAVE_QUANTITY, 1), [18], id="po-pierwszym-gotowym"),
        pytest.param((SAVE_QUANTITY, 0), [], id="przed-pierwszym-gotowym"),
    ],
)
def test_zatrzymanie_w_polowie_przebiegu_oznacza_zlecenia_gotowe_przed_nim(
    tmp_path: Path, page: Page, expire_after: tuple[str, int], marked: list[int]
) -> None:
    orders = [Order(f"#790{index}", cells={"O": 1}, amount=_au({"012": 1})) for index in (1, 2, 3)]
    source = write_collective_file(tmp_path, orders)
    unmarked = source.read_bytes()
    with atrapa_efenix([order.in_efenix(f"79{index}") for index, order in enumerate(orders)], expire_after=expire_after) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (_stop(outcome), _marked(source)) == ("EFENIX_WYLOGOWANY", marked)
    assert (source.read_bytes() == unmarked) == (not marked)


def _resumed_orders() -> list[Order]:
    """Trzy zlecenia z pustą wyceną i datą wykonania: Emmett wpisuje O (012), a proces dopisuje AG (015) i T (019)."""

    cells, filled = {"O": 1, "T": 2, "AG": 1}, {"012": 1, "019": 2, "015": 1}
    return [Order(f"#990{index}", day=date(2026, 9, index), cells=cells, amount=_au(filled), emmett={"012": 1}) for index in (1, 2, 3)]


@pytest.mark.parametrize(
    "expire_after",
    [
        # Zlecenie 1 ma dwa zapisy ilości, więc trzeci to pierwsza ilość zlecenia 2, a czwarty wylogowuje w jego połowie.
        pytest.param((SAVE_QUANTITY, 3), id="w-połowie-ilości-zlecenia"),
        pytest.param((LOAD_EMMETT, 1), id="przy-wycenie-emmetta"),
        pytest.param((SET_DATE, 1), id="przy-dacie-wykonania"),
        # Strona zlecenia 1 otwiera się trzy razy, więc piąte otwarcie to zlecenie 2 po dacie wykonania.
        pytest.param((ORDER_PAGE, 4), id="przy-otwarciu-po-dacie"),
        pytest.param((SEARCH, 1), id="przy-szukaniu"),
    ],
)
def test_przerwanie_wylogowaniem_i_ponowne_uruchomienie_daje_ten_sam_stan_efenix_i_plik_zbiorczy_co_jeden_przebieg(
    tmp_path: Path, page: Page, expire_after: tuple[str, int]
) -> None:
    """Po wylogowaniu tata loguje się z powrotem i uruchamia ponownie; Wycena Emmetta jest najwyżej raz na zlecenie.

    W każdym z tych miejsc proces albo nie kliknął jeszcze „Załaduj do zlecenia” zlecenia 2, albo odczytał już jego Wycenę
    Emmetta, więc ślad ma stan „Emmett załadowany” z jej ilościami."""

    orders = _resumed_orders()
    original = write_collective_file(tmp_path / "plik", orders)
    whole, resumed = (tmp_path / name / PERIOD / original.name for name in ("pelny", "przerwany"))
    for copy_of in (whole, resumed):
        copy_of.parent.mkdir(parents=True)
        shutil.copy2(original, copy_of)
    def in_efenix() -> list[AtrapaOrder]:
        return [order.in_efenix(f"99{index}") for index, order in enumerate(orders)]

    with atrapa_efenix(in_efenix()) as atrapa:
        once = _run(whole, page, atrapa.url)
        priced_once = (_pricing(atrapa), atrapa.status_changes())
    with atrapa_efenix(in_efenix(), expire_after=expire_after) as atrapa:
        stopped = _run(resumed, page, atrapa.url)
        atrapa.log_in()
        again = _run(resumed, page, atrapa.url)
        priced_again = (_pricing(atrapa), atrapa.status_changes())

    assert isinstance(stopped.ending, Stop)
    message = stopped.ending.message
    assert (_stop(stopped), stopped.ending.stop_kind, message.what.startswith("efenix wylogował")) == ("EFENIX_WYLOGOWANY", "for_tata", True)
    assert (once.result, again.result, _figures(again)) == ("OK", "OK", _figures_of(3, 3))
    assert priced_again == priced_once
    assert [emmett_loads for _quantities, _day, emmett_loads in priced_again[0].values()] == [1, 1, 1]
    assert (_parts(resumed), _marked(resumed)) == (_parts(whole), [18, 19, 20])


# Żądania pełnej Wyceny w efenix dwóch zleceń z pustą wyceną po kolei (``_resumed_orders`` bez trzeciego). Okno otwiera
# stronę zlecenia, ustawia datę wykonania i otwiera stronę jeszcze raz, pyta o propozycję Emmetta i ładuje ją do zlecenia, a
# skrypt strony ją przeładowuje, potem zapisuje dwie ilości. Pierwsze zlecenie szuka na liście otwartej przy starcie, a
# kolejne na liście otwartej od nowa, która sama szuka jeszcze raz poprzedniego numeru, zanim okno wyśle swoje szukanie.
_ONE_ORDER = (
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", SET_DATE),
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", FILL_EMMETT), ("POST", LOAD_EMMETT),
    ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("POST", SAVE_QUANTITY), ("POST", SAVE_QUANTITY),
)
WHOLE_RUN = (
    ("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), *_ONE_ORDER,
    ("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), ("POST", SEARCH), *_ONE_ORDER,
)
# Przegląd w CI: zerwane połączenie od każdego żądania, a pozostałe tryby od pierwszego szukania i pierwszego zapisu ilości,
# odpowiedzi, których treść czyta samo okno. Pełny przegląd, każde żądanie w każdym trybie (116 przypadków, ok. 8 min
# procesora), uruchamiasz przed zmianą okna efenix albo odcięcia Atrapy efenix:
# ``PELNY_PRZEGLAD_EFENIX=1 .venv/bin/python -m pytest tests/test_wycena_efenix.py -n 8 -k od_kazdego_zadania``.
_READ_BY_WINDOW = (WHOLE_RUN.index(("POST", SEARCH)), WHOLE_RUN.index(("POST", SAVE_QUANTITY)))
SWEEP = [
    pytest.param(first, outage, id=f"{first:02d}-{path.replace('/', '-')}-{outage.name}")
    for first, (_method, path) in enumerate(WHOLE_RUN)
    for outage in Outage
    if os.environ.get("PELNY_PRZEGLAD_EFENIX") == "1" or outage is Outage.CUT or first in _READ_BY_WINDOW
]


@dataclass(frozen=True)
class _WholeRun:
    """Jeden przebieg Wyceny w efenix bez przerwy: Plik zbiorczy przed nim (``original``) i po nim (``source``) oraz stan
    wyceny Atrapy efenix po nim."""

    original: Path
    source: Path
    pricing: dict[str, tuple[dict[str, int], date | None, int]]


def _two_orders() -> list[Order]:
    return _resumed_orders()[:2]


def _two_in_efenix() -> list[AtrapaOrder]:
    return [order.in_efenix(f"99{index}") for index, order in enumerate(_two_orders())]


@pytest.fixture(scope="module")
def whole_run(tmp_path_factory: pytest.TempPathFactory, browser: Browser) -> _WholeRun:
    """Przebieg bez przerwy, z którym przegląd porównuje ponowne uruchomienie; wysyła dokładnie żądania ``WHOLE_RUN``."""

    root = tmp_path_factory.mktemp("jeden-przebieg")
    original = write_collective_file(root / "plik", _two_orders())
    source = root / "pelny" / PERIOD / original.name
    source.parent.mkdir(parents=True)
    shutil.copy2(original, source)
    with atrapa_efenix(_two_in_efenix()) as atrapa, page_of(browser) as window:
        once = _run(source, window, atrapa.url)
        requested, pricing, status_changes = atrapa.requested(), _pricing(atrapa), atrapa.status_changes()
    assert (once.result, _figures(once), requested, status_changes) == ("OK", _figures_of(2, 2), list(WHOLE_RUN), 0)
    return _WholeRun(original, source, pricing)


def _emmett_not_read(outage: Outage, first: int) -> int | None:
    """Zlecenie (od 0), którego Wycenę Emmetta efenix załadował, a okno jej nie odczytało, bo odcięcie od żądania
    ``first`` zaczęło się między „Załaduj do zlecenia” a odczytem przeładowanej strony: od samego „Załaduj”, które efenix
    wykonuje, gdy jest wolny albo sieć zrywa tylko odpowiedź, albo od przeładowania (strona i jej skrypt)."""

    loads = [index for index, request in enumerate(WHOLE_RUN) if request == ("POST", LOAD_EMMETT)]
    for order, load in enumerate(loads):
        if first in (load + 1, load + 2) or (first == load and outage is not Outage.CUT):
            return order
    return None


@pytest.mark.parametrize(("first", "outage"), SWEEP)
def test_brak_polaczenia_z_efenix_od_kazdego_zadania_wyceny_to_zatrzymanie_dla_taty_a_ponowne_uruchomienie_konczy_jak_jeden_przebieg(
    tmp_path: Path, browser: Browser, whole_run: _WholeRun, outage: Outage, first: int
) -> None:
    """Sieć zrywa każde żądanie od żądania ``first`` pełnej Wyceny (także w połowie odpowiedzi), odpowiedź staje w połowie
    albo efenix odpowiada wolniej niż czas okna (tu 3 s), aż połączenie wróci. To zawsze Zatrzymanie „brak połączenia z efenix” dla taty, bez
    Diagnozy i Zgłoszenia do Maksa, bo odcięcie trwa, a okno potrzebuje każdego żądania po nim, a Komunikat, że w efenix
    nic się nie zmieniło, mówi prawdę. Ponowne uruchomienie po powrocie połączenia, w nowym oknie efenix jak u taty, kończy
    się tym samym stanem efenix i Pliku zbiorczego co jeden przebieg bez przerwy. Wyjątek przyjęty w #774: odcięcie między
    „Załaduj do zlecenia” a odczytem przeładowanej strony daje przy ponownym uruchomieniu błąd tylko tego zlecenia, które
    zostaje z Wyceną Emmetta."""

    orders = _two_orders()
    resumed = tmp_path / PERIOD / whole_run.original.name
    resumed.parent.mkdir(parents=True)
    shutil.copy2(whole_run.original, resumed)
    with atrapa_efenix(_two_in_efenix(), outage_from=(outage, first)) as atrapa:
        untouched = _pricing(atrapa)
        with page_of(browser) as window:
            stopped = _run(resumed, window, atrapa.url, timeout_ms=3_000)
        after_stop = _pricing(atrapa)
        atrapa.reconnect()
        with page_of(browser) as window:
            again = _run(resumed, window, atrapa.url)
        priced_again, status_changes = _pricing(atrapa), atrapa.status_changes()

    assert isinstance(stopped.ending, Stop), _ending(stopped)
    message = stopped.ending.message
    assert (message.code, stopped.ending.stop_kind, message.where) == ("EFENIX_NIEDOSTEPNY", "for_tata", "okno efenix")
    assert message.what.startswith("Brak połączenia z efenix"), message.what
    assert _kept(stopped) or after_stop == untouched, (after_stop, untouched)
    assert status_changes == 0
    unread = _emmett_not_read(outage, first)
    if unread is None:
        assert (_figures(again), _errors(again), priced_again) == (_figures_of(2, 2), [], whole_run.pricing)
        assert (_parts(resumed), _marked(resumed)) == (_parts(whole_run.source), [18, 19])
    else:
        order, row = orders[unread], 18 + unread
        reloaded = {order.number.removeprefix("#"): (dict(order.emmett), order.day, 1)}
        assert (_figures(again), _errors(again)) == (_figures_of(2, 1), [("EFENIX_WYCENA_INNA", f"wiersz {row}")])
        assert (priced_again, _marked(resumed)) == (whole_run.pricing | reloaded, [other for other in (18, 19) if other != row])


def test_przerwanie_po_zaladuj_do_zlecenia_przed_odczytem_wyceny_emmetta_daje_przy_ponownym_uruchomieniu_blad_tylko_tego_zlecenia(
    tmp_path: Path, page: Page
) -> None:
    """Wylogowanie przy przeładowaniu strony zlecenia 2 po „Załaduj do zlecenia”: Emmett jest w efenix, ale narzędzie nie
    odczytało go ze strony, więc ślad nie ma stanu „Emmett załadowany”, a ponowne uruchomienie tylko porównuje wycenę
    zlecenia 2 i nic w niej nie zmienia. Zlecenia 1 i 3 kończą się jak w jednym przebiegu."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    # Szóste otwarcie strony zlecenia to przeładowanie po Wycenie Emmetta zlecenia 2 (każde zlecenie otwiera ją trzy razy).
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=(ORDER_PAGE, 5)) as atrapa:
        stopped = _run(source, page, atrapa.url)
        atrapa.log_in()
        again = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    filled = {"012": 1, "019": 2, "015": 1}
    assert (_stop(stopped), _figures(again), _errors(again)) == (
        "EFENIX_WYLOGOWANY",
        _figures_of(3, 2),
        [("EFENIX_WYCENA_INNA", "wiersz 19")],
    )
    assert pricing == {
        "9901": (filled, date(2026, 9, 1), 1),
        "9902": ({"012": 1}, date(2026, 9, 2), 1),
        "9903": (filled, date(2026, 9, 3), 1),
    }
    assert _marked(source) == [18, 20]


@pytest.mark.parametrize(
    "expire_after",
    [
        # „Załaduj do zlecenia” trafia na wygasłą sesję, więc efenix Emmetta nie ładuje.
        pytest.param((LOAD_EMMETT, 0), id="przy-zaladuj-do-zlecenia"),
        # Drugie otwarcie strony zlecenia to sprawdzenie daty wykonania, przed przyciskiem Emmetta.
        pytest.param((ORDER_PAGE, 1), id="po-dacie-przed-emmettem"),
    ],
)
def test_przerwanie_przed_wycena_emmetta_a_potem_wycena_zaczeta_przez_tate_zostaje_bledem_bez_zmian(
    tmp_path: Path, page: Page, expire_after: tuple[str, int]
) -> None:
    """Emmett dałby T (019) 5, a plik ma 2. Po Zatrzymaniu tata loguje się i sam, bez Emmetta, wpisuje O (012) 1 jak w
    pliku: proces nie załadował Emmetta, więc ponowne uruchomienie tylko porównuje tę wycenę i T nie dopisuje."""

    order = Order("#5201", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1, "019": 5})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("921")], expire_after=expire_after) as atrapa:
        stopped = _run(source, page, atrapa.url)
        atrapa.log_in()
        atrapa.edit("5201", lambda edited: edited.quantities.update({"012": 1}))
        again = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert (_stop(stopped), _errors(again)) == ("EFENIX_WYLOGOWANY", [("EFENIX_WYCENA_INNA", "wiersz 18")])
    assert (pricing, _marked(source)) == ({"5201": ({"012": 1}, DAY, 0)}, [])


@pytest.mark.parametrize(
    ("amount", "first"),
    [
        pytest.param(_au({"012": 1, "019": 2}), [], id="gotowe"),
        pytest.param(_au({"012": 1, "019": 2}) + 1, [("EFENIX_INNA_KWOTA", "wiersz 18")], id="błąd-kwoty"),
    ],
)
def test_zlecenie_skonczone_przez_proces_w_ktorym_tata_usunal_potem_ilosc_ponowne_uruchomienie_tylko_porownuje(
    tmp_path: Path, page: Page, amount: float, first: list[tuple[str, str]]
) -> None:
    """Proces załadował Emmetta (O), dopisał T (019) i skończył zlecenie; tata usuwa potem w efenix T. Ponowne
    uruchomienie nie dopisuje T drugi raz, bo ślad ma stan „gotowe”."""

    order = Order("#5301", cells={"O": 1, "T": 2}, amount=amount, emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("931")]) as atrapa:
        priced = _run(source, page, atrapa.url)
        atrapa.edit("5301", lambda edited: edited.quantities.pop("019"))
        again = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert (_errors(priced), _errors(again)) == (first, [("EFENIX_WYCENA_INNA", "wiersz 18")])
    assert pricing == {"5301": ({"012": 1}, DAY, 1)}


def _interrupted(source: Path, atrapa: AtrapaEfenix, page: Page) -> None:
    """Przebieg ``_resumed_orders`` przerwany wylogowaniem w połowie ilości zlecenia 2 (wiersz 19); tata loguje się z powrotem."""

    assert _stop(_run(source, page, atrapa.url)) == "EFENIX_WYLOGOWANY"
    atrapa.log_in()


# Zlecenie 1 ``_resumed_orders`` ma dwa zapisy ilości, więc czwarty zapis wylogowuje w połowie ilości zlecenia 2.
_IN_HALF_OF_ORDER_2 = (SAVE_QUANTITY, 3)


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda trace: shutil.rmtree(trace.parent), id="brak"),
        pytest.param(lambda trace: trace.write_bytes(trace.read_bytes()[: trace.stat().st_size // 2]), id="urwany"),
        pytest.param(lambda trace: trace.write_text("[]", encoding="utf-8"), id="nie-obiekt"),
        # Ilości jako tekst zamiast liczb: plik jest JSON-em, ale nie ma budowy śladu.
        pytest.param(
            lambda trace: trace.write_text(re.sub(r'(": )(\d+)', r'\1"\2"', trace.read_text(encoding="utf-8")), encoding="utf-8"),
            id="inna-budowa",
        ),
        # Zlecenie bez ilości Wyceny Emmetta, jak dawny zapis „ładuje” sprzed jej odczytu.
        pytest.param(
            lambda trace: trace.write_text(
                re.sub(r'\{"emmett": \{[^}]*\}\}', "null", trace.read_text(encoding="utf-8")), encoding="utf-8"
            ),
            id="bez-wyceny-emmetta",
        ),
        pytest.param(lambda trace: trace.rename(trace.with_name("15_21_09_2026.json")), id="inny-okres"),
        pytest.param(lambda trace: trace.with_name("klucz").unlink(), id="bez-klucza"),
    ],
)
def test_bez_sladu_wyceny_emmetta_albo_z_uszkodzonym_ponowne_uruchomienie_przerwanej_wyceny_tylko_ja_porownuje(
    tmp_path: Path, page: Page, damage: Callable[[Path], object]
) -> None:
    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=_IN_HALF_OF_ORDER_2) as atrapa:
        _interrupted(source, atrapa, page)
        interrupted = _pricing(atrapa)["9902"]
        damage(_traces(source) / f"{PERIOD}.json")
        again = _run(source, page, atrapa.url)
        after = _pricing(atrapa)["9902"]

    assert (_figures(again), _errors(again)) == (_figures_of(3, 2), [("EFENIX_WYCENA_INNA", "wiersz 19")])
    assert (after, _marked(source)) == (interrupted, [18, 20])


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda order: order.quantities.update({"012": 3}), id="inna-ilość-emmetta"),
        pytest.param(lambda order: order.quantities.pop("012"), id="usunięta-ilość-emmetta"),
        # T (019) jest pusta u Emmetta, a plik ma 2.
        pytest.param(lambda order: order.quantities.update({"019": 5}), id="inna-ilość-w-pozycji-pustej-u-emmetta"),
        pytest.param(lambda order: setattr(order, "execution_date", None), id="bez-daty-wykonania"),
    ],
)
def test_przerwana_wycena_ze_sladu_ktora_tata_zmienil_potem_w_efenix_to_blad_bez_zmian(
    tmp_path: Path, page: Page, change: Callable[[AtrapaOrder], object]
) -> None:
    """Po przerwaniu zlecenie 2 ma O (012) od Emmetta i AG (015) od procesu. Tata zmienia albo usuwa w efenix ilość
    Emmetta, wpisuje w pozycji pustej u Emmetta ilość inną niż plik albo usuwa datę wykonania: strona nie jest już taka,
    jaką proces zostawił, więc proces nie dokańcza tej wyceny."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=_IN_HALF_OF_ORDER_2) as atrapa:
        _interrupted(source, atrapa, page)
        atrapa.edit("9902", change)
        changed = _pricing(atrapa)["9902"]
        again = _run(source, page, atrapa.url)
        after = _pricing(atrapa)["9902"]

    assert (_figures(again), _errors(again)) == (_figures_of(3, 2), [("EFENIX_WYCENA_INNA", "wiersz 19")])
    assert after == changed


def test_przerwana_wycena_ze_sladu_sprzeczna_z_plikiem_zmienionym_po_przerwaniu_to_ostrzezenie_bez_dopisywania(
    tmp_path: Path, page: Page
) -> None:
    """Emmett wpisał w zleceniu 2 O (012) 1, proces dopisał AG, a wylogowanie przerwało go przed T. Tata zmienia w Pliku
    zbiorczym O tego zlecenia na 2: ponowne uruchomienie ostrzega o sprzeczności z Wyceną Emmetta ze śladu i T nie
    dopisuje."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    changed = replace(orders[1], cells={**orders[1].cells, "O": 2}, amount=_au({"012": 2, "019": 2, "015": 1}))
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=_IN_HALF_OF_ORDER_2) as atrapa:
        _interrupted(source, atrapa, page)
        interrupted = _pricing(atrapa)["9902"]
        write_collective_file(tmp_path, [orders[0], changed, orders[2]])
        again = _run(source, page, atrapa.url)
        after = _pricing(atrapa)["9902"]

    assert (_figures(again), _errors(again)) == (
        _figures_of(3, 2, warnings=1),
        [("EFENIX_SPRZECZNOSC_Z_EMMETTEM", "wiersz 19")],
    )
    assert after == interrupted


def test_ostrzezenie_emmetta_konczy_zlecenie_wiec_po_zmianie_pliku_na_ilosc_emmetta_ponowne_uruchomienie_tylko_porownuje(
    tmp_path: Path, page: Page
) -> None:
    """Emmett wpisał O (012) 2, a plik ma 1: ostrzeżenie bez dopisywania. Tata zmienia w Pliku zbiorczym O na 2, a T (019)
    zostawia: ponowne uruchomienie nie dopisuje T do wyceny, którą proces skończył ostrzeżeniem."""

    order = Order("#9601", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 2})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("961")]) as atrapa:
        first = _run(source, page, atrapa.url)
        write_collective_file(tmp_path, [replace(order, cells={"O": 2, "T": 2}, amount=_au({"012": 2, "019": 2}))])
        again = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert [_errors(outcome) for outcome in (first, again)] == [
        [("EFENIX_SPRZECZNOSC_Z_EMMETTEM", "wiersz 18")],
        [("EFENIX_WYCENA_INNA", "wiersz 18")],
    ]
    assert (pricing, _marked(source)) == ({"9601": ({"012": 2}, DAY, 1)}, [])


def test_wycena_zaczeta_przez_tate_obok_zlecenia_wycenionego_przez_proces_zostaje_bledem_bez_zmian(tmp_path: Path, page: Page) -> None:
    """Ślad jednego zlecenia nie dotyczy innego: proces ładuje Wycenę Emmetta do wiersza 18, a wiersz 19 tata zaczął sam."""

    started = date(2026, 9, 4)
    orders = [
        Order("#5111", day=date(2026, 9, 3), cells={"O": 1}, amount=_au({"012": 1})),
        Order("#5112", day=started, cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), quantities={"012": 1}),
    ]
    with atrapa_efenix([orders[0].in_efenix("511"), replace(orders[1].in_efenix("512"), execution_date=started)]) as atrapa:
        outcome = _price(tmp_path, page, atrapa.url, orders)
        pricing = _pricing(atrapa)

    assert (_figures(outcome), _errors(outcome)) == (_figures_of(2, 1), [("EFENIX_WYCENA_INNA", "wiersz 19")])
    assert pricing["5112"] == ({"012": 1}, started, 0)


def test_pusta_wycena_emmetta_ze_sladu_nie_laduje_sie_drugi_raz_po_przerwaniu_przed_pierwsza_iloscia(tmp_path: Path, page: Page) -> None:
    filled = {"012": 1, "019": 2}
    order = Order("#9501", cells={"O": 1, "T": 2}, amount=_au(filled))
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("951")], expire_after=(SAVE_QUANTITY, 0)) as atrapa:
        stopped = _run(source, page, atrapa.url)
        atrapa.log_in()
        again = _run(source, page, atrapa.url)
        pricing = _pricing(atrapa)

    assert (_stop(stopped), again.result, pricing, _marked(source)) == ("EFENIX_WYLOGOWANY", "OK", {"9501": (filled, DAY, 1)}, [18])


def test_slad_wyceny_emmetta_ktorego_nie_da_sie_zapisac_nie_zatrzymuje_wyceny_i_nie_zostawia_pliku_tymczasowego(
    tmp_path: Path, page: Page
) -> None:
    order = Order("#9401", cells={"O": 1}, amount=_au({"012": 1}))
    source = write_collective_file(tmp_path, [order])
    # Folder w miejscu pliku śladu: plik tymczasowy się zapisuje, a zamiana nie.
    (_traces(source) / f"{PERIOD}.json").mkdir(parents=True)
    with atrapa_efenix([order.in_efenix("941")]) as atrapa:
        outcome = _run(source, page, atrapa.url)

    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(1, 1))
    assert sorted(path.name for path in _traces(source).iterdir()) == [f"{PERIOD}.json", "klucz"]


def test_slad_wyceny_emmetta_ktorego_nie_da_sie_zastapic_znika_z_dysku_wiec_skonczone_zlecenie_nie_wraca_do_dokonczenia(
    tmp_path: Path, page: Page
) -> None:
    """Po przerwaniu ślad na dysku ma zlecenie 2 w stanie „Emmett załadowany”. Ponowne uruchomienie kończy je, ale żadnego
    zapisu śladu nie da się zastąpić, więc proces usuwa stary ślad. Tata usuwa potem w efenix T (019) zlecenia 2: trzecie
    uruchomienie nie ma śladu i T nie dopisuje."""

    orders = _resumed_orders()
    source = write_collective_file(tmp_path, orders)
    trace = _traces(source) / f"{PERIOD}.json"
    with atrapa_efenix([order.in_efenix(f"99{index}") for index, order in enumerate(orders)], expire_after=_IN_HALF_OF_ORDER_2) as atrapa:
        _interrupted(source, atrapa, page)
        # Folder w miejscu pliku tymczasowego: plik tymczasowy się nie zapisuje, a stary ślad da się usunąć.
        trace.with_name(f"{PERIOD}.json.tmp").mkdir()
        resumed = _run(source, page, atrapa.url)
        atrapa.edit("9902", lambda order: order.quantities.pop("019"))
        edited = _pricing(atrapa)["9902"]
        again = _run(source, page, atrapa.url)
        after = _pricing(atrapa)["9902"]

    assert (_figures(resumed), trace.exists()) == (_figures_of(3, 3), False)
    assert (_errors(again), after) == ([("EFENIX_WYCENA_INNA", "wiersz 19")], edited)


def test_slad_wyceny_emmetta_nie_ma_numeru_zlecenia_adresu_loginu_ani_skrotu_numeru_bez_klucza(tmp_path: Path, page: Page) -> None:
    """Przerwanie przed pierwszą ilością zostawia zlecenie w stanie „Emmett załadowany”; plik śladu i klucz nie mają
    numeru zlecenia, adresu ani loginu, a plik śladu także skrótu SHA-256 numeru, którym bez klucza dałoby się sprawdzić
    zgadnięty numer."""

    number = "12345678"
    order = Order(f"#{number}", cells={"O": 1, "T": 2}, amount=_au({"012": 1, "019": 2}), emmett={"012": 1})
    source = write_collective_file(tmp_path, [order])
    with atrapa_efenix([order.in_efenix("123")], expire_after=(SAVE_QUANTITY, 0)) as atrapa:
        stopped = _run(source, page, atrapa.url)
    written = {path.name: path.read_text(encoding="utf-8").lower() for path in _traces(source).iterdir()}

    assert (_stop(stopped), sorted(written)) == ("EFENIX_WYLOGOWANY", [f"{PERIOD}.json", "klucz"])
    unkeyed = hashlib.sha256(number.encode("utf-8")).hexdigest()
    found = {name: [number_in_trace(number, text), *(word in text for word in (unkeyed, "testowa", "adrian"))] for name, text in written.items()}
    assert found == {name: [False] * 4 for name in written}


# --- Okno efenix taty: logowanie i przeglądarka (#750) ------------------------------------------------------------------

LOGIN_STEP = SavingStep("Zaloguj się w oknie efenix", None, 0, 0)


def test_okno_na_stronie_logowania_czeka_az_tata_sie_zaloguje_a_czas_czekania_nie_liczy_sie_do_czasow_uruchomienia(
    tmp_path: Path, page: Page
) -> None:
    """Tata loguje się 10 minut; każdy inny krok Zapisywania trwa 2 s. ``Czas uruchomienia``, czas Zapisywania i rekord
    metryk mają tylko te 2 s każdego kroku, czas uruchomienia na żywo przy każdym kroku postępu też nie liczy logowania, a
    postęp idzie po Wykonawcach alfabetycznie, potem Znaczniki efenix."""

    # Zegar, który przesuwa tylko tata z testu (ManualClock z tests/fixtures/clock.py wciągnąłby ten plik do bramki C).
    now = [0.0]
    orders = [
        Order("#5402", worker="beata.testowa", cells={"O": 1}, amount=_au({"012": 1}), quantities={"012": 1}),
        Order("#5401", cells={"T": 1}, amount=_au({"019": 1}), quantities={"019": 1}),
    ]
    source = write_collective_file(tmp_path, orders)
    metrics = tmp_path / "metryki.jsonl"
    steps: list[SavingStep] = []
    reached_ms: list[int] = []
    with atrapa_efenix([orders[0].in_efenix("541"), orders[1].in_efenix("542")]) as atrapa:
        atrapa.expire_session()

        class LoggingIn(Tata):
            def show_progress(self, snapshot: ProgressSnapshot) -> None:
                if snapshot.step is None or (steps and steps[-1] == snapshot.step):
                    return
                steps.append(snapshot.step)
                reached_ms.append(snapshot.total_elapsed_ms)
                if snapshot.step == LOGIN_STEP:
                    now[0] += 600
                    atrapa.log_in()
                else:
                    now[0] += 2

        outcome = run_process(
            efenix_process.PROCESS,
            EfenixInputs(
                source,
                lambda login: efenix_browser.window(page, atrapa.url, login=login),
                pace=None,
                trace_directory=_traces(source),
                clock=lambda: now[0],
            ),
            LoggingIn(),
            view=lambda _inputs, summary: summary,
            metrics_path=metrics,
            clock=lambda: now[0],
        )
    [record] = [json.loads(line) for line in metrics.read_text(encoding="utf-8").splitlines()]

    assert (outcome.result, _figures(outcome)) == ("OK", _figures_of(2, 2))
    assert steps == [
        LOGIN_STEP,
        SavingStep("Zlecenia", "adrian.testowy", 0, 2),
        SavingStep("Zlecenia", "beata.testowa", 1, 2),
        SavingStep("Znaczniki efenix w Pliku zbiorczym", None, 0, 0),
    ]
    assert (outcome.total_duration_ms, outcome.progress.phase_durations_ms[ProgressPhase.SAVING]) == (6000, 6000)
    assert reached_ms == [0, 0, 2000, 4000]
    assert (record["total_duration_ms"], record["phase_durations_ms"][ProgressPhase.SAVING]) == (6000, 6000)


def test_okno_bez_logowania_taty_i_przegladarka_ktora_nie_wystartowala_zatrzymuja_wycene_z_komunikatem(
    tmp_path: Path, page: Page
) -> None:
    """Brak logowania w czasie oczekiwania to Zatrzymanie jak po wylogowaniu, a przeglądarka, której nie ma na komputerze
    (tu kanał, którego Playwright nie zna), to Komunikat dla taty, nie nieoczekiwany wyjątek; w efenix nic się nie zmienia."""

    orders = [Order("#5501", cells={"O": 1}, amount=_au({"012": 1}))]
    with atrapa_efenix([orders[0].in_efenix("551")]) as atrapa:
        atrapa.expire_session()
        not_logged_in = _run_with(
            write_collective_file(tmp_path / "bez-logowania", orders),
            lambda login: efenix_browser.window(page, atrapa.url, login=login, login_timeout_ms=1),
        )
        # Okno ``chrome`` startuje własny Playwright, a ten wątek ma już Playwright przeglądarki testów.
        with ThreadPoolExecutor(max_workers=1) as own_thread:
            no_browser = own_thread.submit(
                _run_with,
                write_collective_file(tmp_path / "bez-chrome", orders),
                lambda login: efenix_browser.chrome(atrapa.url, tmp_path / "profil", login, channel="chrome-niezainstalowany"),
            ).result()
        requested = atrapa.requested()

    assert (_stop(not_logged_in), _stop(no_browser)) == ("EFENIX_WYLOGOWANY", "EFENIX_BRAK_PRZEGLADARKI")
    assert (_kept(not_logged_in), _kept(no_browser)) == (False, False)
    assert set(requested) <= READING | {("GET", "page_login.php")}


def test_okno_czeka_na_logowanie_taty_15_minut_a_potem_daje_wylogowanie(page: Page) -> None:
    """Domyślny limit czekania na logowanie to 15 minut: tata, który loguje się w 14. minucie i 59. sekundzie, zaczyna
    Wycenę, a bez logowania okno kończy czekanie w 15. minucie (``LoggedOut``), nie później. Czas czekania mierzy
    zegar okna, który tu przesuwa test: start w 0, potem podana minuta, a każdy następny odczyt godzinę później."""

    seen: list[float] = []

    def waiting(minutes: float, log_in: Callable[[], None] = lambda: None) -> Callable[[], float]:
        seen.clear()
        readings = iter([0.0, minutes * 60])

        def clock() -> float:
            seen.append(next(readings, 3600.0))
            if len(seen) == 2:
                log_in()
            return seen[-1]

        return clock

    with atrapa_efenix([]) as atrapa:
        atrapa.expire_session()
        with efenix_browser.window(page, atrapa.url, login=nullcontext, clock=waiting(14 + 59 / 60, atrapa.log_in)):
            logged_in = page.url
        atrapa.expire_session()
        with pytest.raises(LoggedOut), efenix_browser.window(page, atrapa.url, login=nullcontext, clock=waiting(15)):
            pass

    assert (logged_in, max(seen)) == (atrapa.url, 900.0)


def test_profil_przegladarki_okna_efenix_lezy_w_katalogu_narzedzia_poza_gitem() -> None:
    """Katalog narzędzia leży u taty na dysku lokalnym poza OneDrive (``docs/agents/komputer-taty.md``)."""

    profile = efenix_browser.default_profile()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", str(profile / "Default" / "Cookies")], cwd=TOOL_ROOT, check=False
    )

    assert (profile.parent, ignored.returncode) == (TOOL_ROOT, 0)


def _run_with(source: Path, open_efenix: Callable[[Login], AbstractContextManager[efenix_browser.BrowserEfenix]]) -> Priced:
    return run_process(
        efenix_process.PROCESS,
        EfenixInputs(source, open_efenix, pace=None, trace_directory=_traces(source)),
        Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=source.parent.parent / "metryki.jsonl",
    )


def test_plik_zbiorczy_otwarty_w_excelu_zatrzymuje_wycene_zanim_otworzy_efenix(tmp_path: Path, page: Page) -> None:
    orders = [Order("#7601", cells={"O": 1}, amount=_au({"012": 1}))]
    source = write_collective_file(tmp_path, orders)
    excel_lock_file(source).write_bytes(b"")
    with atrapa_efenix([orders[0].in_efenix("761")]) as atrapa:
        outcome = _run(source, page, atrapa.url)
        requested = atrapa.requested()

    assert (_stop(outcome), requested, _kept(outcome)) == ("EFENIX_PLIK_ZBIORCZY_OTWARTY", [], False)


def test_plik_zbiorczy_ze_znacznikami_daje_w_przebiegu_rozliczen_rozliczenie_pracownika_bez_nich(tmp_path: Path, page: Page) -> None:
    orders = _marking_orders()
    source = write_collective_file(tmp_path, orders)
    with atrapa_efenix(_marking_efenix(orders)) as atrapa:
        _run(source, page, atrapa.url)
    template = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    write_template(template)
    assert _marked(source) == [18, 19]

    summary = run_settlements(source, write_mapping(tmp_path / "worker_mapping.yaml"), worker_template_path=template)

    assert summary.written_count == 1
    written = source.parent / f"Rozliczenie pracowników {PERIOD}" / f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx"
    workbook = load_workbook(written)
    try:
        sheet = active_worksheet(workbook)
        fills = {row: sheet[f"B{row}"].fill for row in range(18, 24)}
        font = sheet["B18"].font
    finally:
        workbook.close()
    assert {row: (fill.fill_type, str(fill.fgColor.rgb)[-6:] if fill.fill_type else None) for row, fill in fills.items()} == {
        **{row: (None, None) for row in range(18, 23)},
        23: ("solid", YELLOW),
    }
    assert (font.color.rgb, font.b, font.i) == ("FFFF0000", True, True)
