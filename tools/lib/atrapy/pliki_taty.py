"""Układ i nazwy plików taty, które budują atrapy: kopia celowa: świat taty.

Atrapy budują Plik zbiorczy, Wzorce, Rejestr zleceń i Konfigurację wykonawców tak, jak leżą u taty, a narzędzie i
sprawdzenia skilli (``assert_chain``, ``run_excel_verification``) czytają ten sam układ od właścicieli w ``src``
(``rozliczenia.collective_layout``, ``register_columns``, ``tool_files``, ``period_folder``). Atrapa, która też
importowałaby właściciela, przesunęłaby się razem z nim, więc zmiana układu w ``src`` nie czerwieniłaby niczego. Tu
stoi jedyna kopia w atrapach, literałem; każda inna atrapa bierze układ i nazwy stąd.
"""

from __future__ import annotations

from typing import Final

# collective_layout: wiersze i kolumny arkusza Pliku zbiorczego i Wzorców (numery kolumn od 1).
COST_ROW: Final = 14
HEADER_ROW: Final = 17
FIRST_DATA_ROW: Final = 18
CITY_COLUMN: Final = 1  # A
ADDRESS_COLUMN: Final = 2  # B
ORDER_COLUMN: Final = 6  # F: NUMER ZLECENIA
WORKER_COLUMN: Final = 8  # H
DATA_ROW_COLUMNS: Final = range(1, 47)  # A:AT, Wiersz danych
LOOK_COLUMNS: Final = range(1, 13)  # A:L, Wygląd Wiersza danych
QUANTITY_COLUMNS: Final = range(14, 43)  # N:AP, Ilości usług
AMOUNT_COLUMN: Final = 47  # AU

# register_columns: nagłówki A17:K17 Wzorca pliku zbiorczego taty, pod którymi Przygotowanie zapisuje kolumny wejścia;
# Wzorzec rozliczenia pracownika ma je w B17:K17 (w A17 GODZINA).
COLLECTIVE_HEADERS: Final = (
    "MIASTO",
    "ADRES",
    "UMOWA",
    "URZĄDZENIA",
    "CZYNNOŚCI",
    "NUMER ZL.",
    "DATA",
    "WYKONAWCA",
    "NUMER UMOWY/ZLECENIA ORANGE",
    "SKUTECZNE",
    "CZYNNOŚCI ZREALIZOWANE",
)
# Nagłówki wiersza 1 Wzorca rozliczenia wewnętrznego taty: te same kolumny wejścia, potem zwrot i UWAGI, których
# narzędzie nie wypełnia.
INTERNAL_HEADERS: Final = (*COLLECTIVE_HEADERS, "zwrot", "UWAGI")

# register_columns: nagłówki nowego Rejestru taty od B; AKCJE, ZWROT i UWAGI narzędzie pomija.
REGISTER_HEADERS: Final = (
    "AKCJE",
    "DATA GODZ. POCZ.",
    "MIASTO",
    "ADRES",
    "UMOWA",
    "URZĄDZENIA",
    "CZYNNOŚCI",
    "NUMER ZL.",
    "WYKONAWCA",
    "NUMER UMOWY",
    "SKUTECZNE",
    "CZYNNOŚCI ZREALIZOWANE",
    "ZWROT",
    "UWAGI",
)
# raw_orders.SHIFT: pierwszy wiersz każdego wklejenia z aplikacji INTERMAX stoi o tyle kolumn na lewo od nagłówków.
PASTE_SHIFT: Final = 2
# Nazwa Rejestru zleceń, którą wybrał tata; src jej nie zna.
REGISTER_NAME: Final = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"

# tool_files: folder config klonu narzędzia i jego pliki.
CONFIG_DIRECTORY: Final = "config"
WORKER_LIST_NAME: Final = "wykonawcy.yaml"

# Układ folderu narzędzia u taty, którego nazwy czyta następne Wydanie tam, gdzie zostawiło je poprzednie (ADR 0015),
# pisze ręcznie Maks (klucz: README, ADR 0007) albo tata podaje Maksowi (dziennik), i nazwa usługi, po której nowe
# Centrum rozpoznaje działające starsze. Ścieżki są względem folderu narzędzia; same nazwy leżą w CONFIG_DIRECTORY,
# obok LOG_FILE (LAST_STARTED_FILE, RUN_LOGS_DIRECTORY) albo jak mówi nazwa.
SETTINGS_FILE: Final = f"{CONFIG_DIRECTORY}/centrum-ustawienia.yaml"
WORKER_MAPPING_FILE: Final = f"{CONFIG_DIRECTORY}/worker_mapping.yaml"
LOG_FILE: Final = "logs/centrum-rozliczen.log"
REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
DAD_CASES_FILE: Final = "sprawy-taty.json"
NOTIFICATIONS_FILE: Final = "powiadomienia.json"
CENTRUM_RUNS_FILE: Final = "centrum-uruchomienia.jsonl"
UPDATE_RESULT_FILE: Final = "centrum-aktualizacja.json"
QUEUE_DIRECTORY: Final = "zgloszenia/kolejka"
LAST_STARTED_FILE: Final = "ostatnie-uruchomienie.json"
RUN_LOGS_DIRECTORY: Final = "uruchomienia"
SERVICE: Final = "centrum-rozliczen"
WORKER_TEMPLATE_NAME: Final = "Wzorzec rozliczenia pracownika.xlsx"
COLLECTIVE_TEMPLATE_NAME: Final = "Wzorzec pliku zbiorczego.xlsx"
INTERNAL_TEMPLATE_NAME: Final = "Wzorzec rozliczenia wewnętrznego.xlsx"


# period_folder: pliki i foldery okresu o tokenie ``token``.
def collective_file_name(token: str) -> str:
    return f"Rozliczenie {token} - zbiorcze.xlsx"


def internal_settlement_name(token: str) -> str:
    return f"Rozliczenie wew. {token}.xlsx"


def worker_settlements_name(token: str) -> str:
    return f"Rozliczenie pracowników {token}"


def worker_settlement_name(token: str, worker: str) -> str:
    return f"Rozliczenie {token} - {worker}.xlsx"
