"""Scenariusz syntetyczny skilli verify-rozliczenia i verify-skoroszyty-w-excelu: dane wejścia, bez skoroszytów.

Generatory skilla verify-rozliczenia (``create_fixture.py``, ``create_preparation_fixture.py``) budują z tych danych pliki, a wyrocznie obu skilli (``assert_*.py``,
``fill_readiness.py``, ``self_test.py``, ``run_excel_verification.py``, ``excel_doctor.py``) biorą stąd te same
wartości wejścia. Okres, konfiguracja wykonawców, nazwy plików okresu i nagłówki Wzorców biorą z atrap plików taty, gdzie już są
(``PERIOD``, ``SOURCE_NAME`` i ``WORKERS`` z ``tools/lib/atrapy/settlement.py``, ``INTERNAL_SETTLEMENT_NAME``,
``COLLECTIVE_FILE_NAME`` i nagłówki z ``tools/lib/atrapy/preparation.py``).

Tu stoją fakty wejścia i dwa oczekiwania, które wyrocznie obu skilli sprawdzają tak samo, napisane ręcznie, a nie
wyliczone z ``ORDERS``: Ilości usług z Reguł ilości taty (``QUANTITIES``) i Wiersze danych Rozliczenia pracownika
każdego Wykonawcy w ich kolejności (``WORKER_ORDERS``); generatory ich nie czytają. To, które zlecenia trafiają do
Rozliczenia wewnętrznego i Pliku zbiorczego i w jakiej kolejności, wyrocznie piszą jawnie same, żeby błąd procesu w
wyborze albo kolejności nie przeszedł razem z danymi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from atrapy.settlement import PERIOD

REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
PERIODS_DIRECTORY = "INEA"
TEMPLATES_DIRECTORY = "config"
INTERNAL_TEMPLATE_NAME = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE_TEMPLATE_NAME = "Wzorzec pliku zbiorczego.xlsx"
WORKER_TEMPLATE_NAME = "Wzorzec rozliczenia pracownika.xlsx"
WORKER_SETTLEMENTS_DIRECTORY = f"Rozliczenie pracowników {PERIOD}"


def worker_settlement_name(worker: str) -> str:
    """Nazwa Rozliczenia pracownika ``worker`` (nazwa z konfiguracji wykonawców) w okresie scenariusza."""

    return f"Rozliczenie {PERIOD} - {worker}.xlsx"


# Przebieg rozliczeń na gotowym Pliku zbiorczym (create_fixture.py): Wiersze danych od 18, ilość w N = numer - 17.
SETTLEMENT_CITY = "TEST-CITY"
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

# Przygotowanie pliku zbiorczego i łańcuch (create_preparation_fixture.py): każda wartość tekstowa zlecenia ma
# znacznik ROW_MARKER, którego nie wolno znaleźć w wyniku ani w dowodach.
ROW_MARKER = "PREP-SYN-"
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
    """NUMER ZL. zlecenia ``number``."""

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


def completed_activities(number: int) -> str:
    """CZYNNOŚCI ZREALIZOWANE; order 2 has two lines, so its Wiersz danych wraps and Excel makes it taller."""

    return "montaż\ndemontaż" if number == 2 else "montaż"


# The only order of the hidden ARCHIWUM sheet, a year before the period.
ARCHIVED_NUMBER = 90
ARCHIVED_ORDER = Order(2, datetime(2025, 9, 9, 9, 0), "kamil.syntetyczny", "tak")


def register_values(number: int, order: Order) -> dict[str, object]:
    """Wartości zlecenia ``number`` po nagłówkach Rejestru; każda wartość tekstowa ma znacznik ``ROW_MARKER``."""

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
    *(marker for _, marker in (*SETTLEMENT_ROWS, UNMAPPED_ROW)),
    "SYNTHETIC-LINK",
    ROW_MARKER,
)
