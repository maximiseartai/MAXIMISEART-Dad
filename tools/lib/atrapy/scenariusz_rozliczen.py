"""Scenariusz syntetyczny skilli verify-rozliczenia i verify-skoroszyty-w-excelu: dane wejścia, bez skoroszytów.

Generatory skilla verify-rozliczenia (``create_fixture.py``, ``create_preparation_fixture.py``) budują z tych danych pliki, a wyrocznie obu skilli (``assert_*.py``,
``fill_readiness.py``, ``self_test.py``, ``run_excel_verification.py``, ``excel_doctor.py``) biorą stąd te same
wartości wejścia. Okres, konfiguracja wykonawców, nazwy plików okresu, nagłówki Wzorców i opis zlecenia bez Kodu czynności
biorą z atrap plików taty, gdzie już są (``PERIOD``, ``SOURCE_NAME`` i ``WORKERS`` z ``tools/lib/atrapy/settlement.py``,
``INTERNAL_SETTLEMENT_NAME``, ``COLLECTIVE_FILE_NAME`` i ``COMPLETED_WITHOUT_CODES`` z ``tools/lib/atrapy/preparation.py``), a nazwy Rejestru, Wzorców, folderu ``config`` i
plików okresu oraz nagłówki Wzorców z kopii świata taty w ``tools/lib/atrapy/pliki_taty.py``.

Tu stoją fakty wejścia i cztery oczekiwania, które wyrocznie obu skilli sprawdzają tak samo, napisane ręcznie, a nie
wyliczone z ``ORDERS``: Ilości usług z Reguł ilości taty (``QUANTITIES``), wynik Legendy czynności z Wydania
(``CODE_QUANTITIES``, ``CODE_AMOUNTS``, ``CODE_FILLS``), Czerwone pole i Zielone pole w Rozliczeniu pracownika
(``WORKER_COLOURED_FIELDS``) i Wiersze danych Rozliczenia pracownika każdego Wykonawcy w ich kolejności
(``WORKER_ORDERS``); generatory ich nie czytają. To, które zlecenia trafiają do
Rozliczenia wewnętrznego i Pliku zbiorczego i w jakiej kolejności, wyrocznie piszą jawnie same, żeby błąd procesu w
wyborze albo kolejności nie przeszedł razem z danymi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from atrapy import pliki_taty
from atrapy.pliki_taty import REGISTER_NAME as REGISTER_NAME
from atrapy.preparation import COMPLETED_WITHOUT_CODES
from atrapy.settlement import PERIOD

PERIODS_DIRECTORY = "INEA"
TEMPLATES_DIRECTORY = pliki_taty.CONFIG_DIRECTORY
INTERNAL_TEMPLATE_NAME = pliki_taty.INTERNAL_TEMPLATE_NAME
COLLECTIVE_TEMPLATE_NAME = pliki_taty.COLLECTIVE_TEMPLATE_NAME
WORKER_TEMPLATE_NAME = pliki_taty.WORKER_TEMPLATE_NAME
WORKER_SETTLEMENTS_DIRECTORY = pliki_taty.worker_settlements_name(PERIOD)


def worker_settlement_name(worker: str) -> str:
    """Nazwa Rozliczenia pracownika ``worker`` (nazwa z konfiguracji wykonawców) w okresie scenariusza."""

    return pliki_taty.worker_settlement_name(PERIOD, worker)


# Przebieg rozliczeń na gotowym Pliku zbiorczym (create_fixture.py): Wiersze danych od 18, ilość w N = numer - 17.
SETTLEMENT_CITY = "TEST-CITY"
SETTLEMENT_ADDRESS = "TEST-ADDRESS"
# Hiperłącze w NUMER ZL. (F) każdego Wiersza danych, jak do zlecenia w aplikacji firmowej; numer wiersza na końcu.
SETTLEMENT_ORDER_LINK = "https://przyklad.invalid/zlecenie?caseId=SYNTHETIC-LINK&tw=1&wiersz="
# (Wykonawca, NUMER ZL.) Wierszy danych 18, 19 i 20.
SETTLEMENT_ROWS: tuple[tuple[str, str], ...] = (
    ("adrian.testowy", "SYNTHETIC-1"),
    ("dariusz.fikcyjny2", "SYNTHETIC-2"),
    ("adrian.testowy", "SYNTHETIC-3"),
)
UNMAPPED_WORKER = "unknown.synthetic"
# Wiersz danych 21 wariantu z Wykonawcą spoza konfiguracji wykonawców.
UNMAPPED_ROW = (UNMAPPED_WORKER, "SYNTHETIC-4")

# Przygotowanie pliku zbiorczego i łańcuch (create_preparation_fixture.py): tekstowe wartości zlecenia poza WYKONAWCA,
# SKUTECZNE, URZĄDZENIA, CZYNNOŚCI i CZYNNOŚCI ZREALIZOWANE mają znacznik ROW_MARKER, którego nie wolno znaleźć w wyniku
# ani w dowodach.
ROW_MARKER = "PREP-SYN-"
# Stawka Wzorca rozliczenia pracownika łańcucha, inna niż Wzorca pliku zbiorczego: stawka przeniesiona z Pliku
# zbiorczego do Rozliczenia pracownika zmienia komórkę spoza Wierszy danych, którą assert_chain.py porównuje ze Wzorcem.
WORKER_TEMPLATE_RATE = 12.0
# Wiersze zer obu Wzorców łańcucha w układzie Wzorca pliku zbiorczego: więcej niż 6 Zleceń skutecznych scenariusza, więc
# assert_preparation.py widzi zera Wzorca pod zapisanymi Wierszami danych.
TEMPLATE_ZERO_ROWS = 8
# Hiperłącze w NUMER ZL. każdego zlecenia ZLECENIA, jak do zlecenia w aplikacji firmowej; numer wiersza Rejestru
# kończy adres.
ORDER_LINK = "https://przyklad.invalid/zlecenie?caseId=PREP-SYN-LINK&tw=1&wiersz="


@dataclass(frozen=True)
class Order:
    """Zlecenie syntetycznego Rejestru: wiersz arkusza, DATA GODZ. POCZ., WYKONAWCA i SKUTECZNE."""

    row: int
    started: datetime
    worker: str
    successful: str


# Numer zlecenia -> zlecenie arkusza ZLECENIA, w kolejności wierszy Rejestru; wiersze bez zlecenia są puste.
ORDERS: dict[int, Order] = {
    1: Order(2, datetime(2026, 9, 7, 15, 0), "adrian.testowy", "tak"),  # previous period
    2: Order(4, datetime(2026, 9, 8, 0, 0), "adrian.testowy", "tak"),
    3: Order(6, datetime(2026, 9, 9, 10, 30), "dariusz.fikcyjny2", "NIE"),
    4: Order(9, datetime(2026, 9, 12, 12, 0), "kamil.syntetyczny", " Tak "),
    5: Order(11, datetime(2026, 9, 15, 0, 0), "adrian.testowy", "tak"),  # next period
    7: Order(12, datetime(2026, 9, 13, 9, 0), "adrian.testowy", "tak"),  # Adrian again, after Kamil
    6: Order(13, datetime(2026, 9, 14, 18, 30), "dariusz.fikcyjny2", "TAK"),  # late order of the period
    8: Order(14, datetime(2026, 9, 8, 11, 0), "dariusz.fikcyjny2", "tak"),
    9: Order(15, datetime(2026, 9, 14, 10, 0), "kamil.syntetyczny", "tak"),
}


def order_number(number: int) -> str:
    return f"{ROW_MARKER}ZL-{number}"


# Order number -> first word of UMOWA and the whole URZĄDZENIA, so that the Plik zbiorczy rows get Ilości usług from the
# Reguły ilości (2: router with two TV devices and printing, 4: gateway with wifi6extra and a Saturday usterka,
# 6: Monday-evening usterka with an unknown component and printing, 7: prewencja, settled from the description,
# 8: gniazdo, 9: a technicolor variant not on Dad's list). AP of order 8 and AK of order 9 are Ilości tylko dla INEA.
ORDER_CONTENT: dict[int, tuple[str, str]] = {
    2: ("u", "nokia zte  2*fut"),
    4: ("pr", "gateway wifi6extra, usterka"),
    6: ("U", "usterka przeniesienie"),
    7: ("u", "prewencja"),
    8: ("pr", "gniazdo"),
    9: ("pr", "Technicolor 3*globo"),
}


def order_contract(number: int) -> str:
    return f"{ORDER_CONTENT.get(number, ('pr', ''))[0]} PREP-SYN-UM-{number}"


def order_devices(number: int) -> str:
    return ORDER_CONTENT.get(number, ("", "nokia"))[1]


# Numer zlecenia -> CZYNNOŚCI ZREALIZOWANE z samych Kodów czynności Legendy czynności z Wydania (ADR 0038), więc
# Przygotowanie wpisuje ich Ilości usług, kwotę w AS i wypełnienia: spawpg daje AB, 70 w AS i czerwone AS, a rt2 daje AM
# z czerwonym AM i zielone AF bez wartości. Każde inne zlecenie ma opis atrap Rejestru bez kodu i bez Błędu opisu
# (COMPLETED_WITHOUT_CODES), więc czeka na tatę w kolumnach z opisu technika.
ACTIVITY_CODES: dict[int, str] = {8: "spawpg rt2"}


def completed_activities(number: int) -> str:
    """CZYNNOŚCI ZREALIZOWANE; order 2 has two lines, so its Wiersz danych wraps and Excel makes it taller."""

    without_codes = f"{COMPLETED_WITHOUT_CODES}\n{COMPLETED_WITHOUT_CODES}" if number == 2 else COMPLETED_WITHOUT_CODES
    return ACTIVITY_CODES.get(number, without_codes)


# The only order of the hidden ARCHIWUM sheet, a year before the period.
ARCHIVED_NUMBER = 90
ARCHIVED_ORDER = Order(2, datetime(2025, 9, 9, 9, 0), "kamil.syntetyczny", "tak")


def register_values(number: int, order: Order) -> dict[str, object]:
    return {
        "AKCJE": f"PREP-SYN-AKCJA-{number}",
        "DATA GODZ. POCZ.": order.started,
        "MIASTO": "PREP-SYN-MIASTO",
        "ADRES": f"PREP-SYN-ADRES-{number}",
        "UMOWA": order_contract(number),
        "URZĄDZENIA": order_devices(number),
        "CZYNNOŚCI": "instalacja",
        "NUMER ZL.": order_number(number),
        "WYKONAWCA": order.worker,
        "NUMER UMOWY": f"PREP-SYN-OR-{number}",
        "SKUTECZNE": order.successful,
        "CZYNNOŚCI ZREALIZOWANE": completed_activities(number),
        "ZWROT": f"PREP-SYN-ZWROT-{number}",
        "UWAGI": f"PREP-SYN-UWAGA-{number}",
    }


# Ilości usług, które Przygotowanie pliku zbiorczego wpisuje z Reguł ilości dla UMOWA i URZĄDZENIA zlecenia
# (ADR 0012, 0013); każda inna komórka N:AP zostaje z zerem Wzorca.
QUANTITIES: dict[int, dict[str, int]] = {
    2: {"O": 1, "P": 1, "Q": 1, "S": 3, "T": 1, "V": 1, "Z": 1},
    4: {"N": 45, "O": 1, "S": 2, "V": 1, "AG": 1, "AI": 1, "AO": 1},
    7: {},
    6: {"N": 45, "T": 1, "V": 1},
    8: {"V": 1, "AE": 1, "AP": 1},
    9: {"O": 1, "P": 1, "Q": 2, "S": 4, "V": 1, "Z": 1, "AK": 1},
}
# Ilości usług, kwota w AS i wypełnienia (kolumna -> ARGB), które Legenda czynności z Wydania wpisuje dla ACTIVITY_CODES.
CODE_QUANTITIES: dict[int, dict[str, int]] = {8: {"AB": 1, "AM": 1}}
CODE_AMOUNTS: dict[int, int] = {8: 70}
CODE_FILLS: dict[int, dict[str, str]] = {8: {"AF": "FF92D050", "AM": "FFFF0000", "AS": "FFFF0000"}}
# Czerwone pole i Zielone pole (ADR 0039) w Rozliczeniu pracownika: zlecenie -> kolumna -> wartość. Czerwone AM i AS z
# CODE_FILLS są tam puste, a zielone AF ma 1; wszystkie trzy są bez wypełnienia, czyli białe.
WORKER_COLOURED_FIELDS: dict[int, dict[str, int | None]] = {8: {"AF": 1, "AM": None, "AS": None}}


def written_quantities(number: int) -> dict[str, int]:
    """N:AP zlecenia ``number`` w Pliku zbiorczym: Reguły ilości i Legenda czynności sumują się w każdej kolumnie."""

    rules, codes = QUANTITIES.get(number, {}), CODE_QUANTITIES.get(number, {})
    return {column: rules.get(column, 0) + codes.get(column, 0) for column in {**rules, **codes}}

# Zlecenia skuteczne okresu każdego Wykonawcy w kolejności Rejestru, czyli Wiersze danych jego Rozliczenia
# pracownika; zlecenia Adriana rozdziela zlecenie Kamila.
WORKER_ORDERS: dict[str, tuple[int, ...]] = {
    "adrian.testowy": (2, 7),
    "dariusz.fikcyjny2": (6, 8),
    "kamil.syntetyczny": (4, 9),
}

# Gotowość (fill_readiness.py): Adrian twice and Darek once; Darek's gniazdo order and Kamil's two keep what
# Przygotowanie pliku zbiorczego wrote.
FILLED_ORDERS = (2, 7, 6)

# Treść Wierszy danych Przebiegu i Przygotowania; żadnej nie wolno znaleźć w dowodach skilla (znaczniki
# Uporządkowania INTERMAX ma ``create_intermax_fixture.ROW_MARKERS``).
ROW_CONTENT_MARKERS = (
    SETTLEMENT_CITY,
    SETTLEMENT_ADDRESS,
    *(marker for _, marker in (*SETTLEMENT_ROWS, UNMAPPED_ROW)),
    "SYNTHETIC-LINK",
    ROW_MARKER,
)
