"""Scenariusz syntetyczny skilla verify-centrum-rozliczen: dane wejścia Centrum, bez skoroszytów.

``create_centrum_fixture.py`` i ``serve_centrum.py`` budują z tych danych pliki taty i Atrapę efenix, a napęd
(``drive/*.py``), ``centrum_self_test.py`` i ``windows_tool.py`` skilla verify-centrum-na-windowsie biorą stąd te same
wartości wejścia. Nagłówki biorą z ``tests/fixtures/preparation.py``, a nazwy Wzorców generator bierze z
``tests/fixtures/scenariusz_rozliczen.py``; Rejestr ma układ starego Rejestru taty, a Wzorzec rozliczenia
wewnętrznego nie ma kolumn ``zwrot`` i ``UWAGI``, których żaden proces nie czyta.

Wiersze Pliku zbiorczego, na które trafiają zlecenia okresu (``COLLECTIVE_FILE_ROWS``), stoją tu jawnie, a nie z kodu
Przygotowania pliku zbiorczego; ``create_centrum_fixture.py`` liczy z nich wiersze bez reguły i z opisu do
``fixture.json``. To, co Centrum ma z nimi pokazać, napęd sprawdza sam.
"""

from __future__ import annotations

from datetime import datetime

from tests.fixtures.atrapa_efenix import amount_of
from tests.fixtures.efenix import ADDRESS, Order as EfenixOrder
from tests.fixtures.preparation import COLLECTIVE_TEMPLATE_HEADERS, INTERNAL_TEMPLATE_HEADERS, OLD_REGISTER_HEADERS
from tests.fixtures.settlement import PERIOD

# Dad's "today" for the run: Monday 19.10.2026, so the last complete period is 06_12_10_2026,
# whose Folder okresu deliberately does not exist.
TODAY = "2026-10-19"
LAST_COMPLETE = "06_12_10_2026"
# A period whose Plik zbiorczy has a Wiersz danych of a Wykonawca the konfiguracja wykonawców does not know.
NEEDS_CHECK = "29_05_10_2026"
# An older period with no Folder okresu, which Centrum offers with „Brak plików okresu”.
PERIOD_WITHOUT_FILES = "08_14_09_2026"
UNKNOWN_WORKER = "wykonawca.spoza.konfiguracji"
WORKERS = ("Wykonawca Testowy A", "Wykonawca Testowy B", "Wykonawca Testowy C")
# A Wykonawca of the konfiguracja wykonawców without orders: his Szablon pracownika stays empty.
EMPTY_WORKER = "Wykonawca Testowy D"
WORKER_IDS = ("wykonawca.a", "wykonawca.b", "wykonawca.c", "wykonawca.d")
# A synthetic row value inside every workbook. Centrum must never read or show workbook content,
# so this marker must never appear in evidence (centrum_self_test.py checks it).
ROW_MARKER = "CENTRUM-SYN-ROW"

REGISTER_HEADERS = OLD_REGISTER_HEADERS
# The target headers the engine looks for; in the Wzorzec pliku zbiorczego WYKONAWCA must be in H17.
INTERNAL_HEADERS = tuple(header for header in INTERNAL_TEMPLATE_HEADERS if header not in {"zwrot", "UWAGI"})
COLLECTIVE_HEADERS = COLLECTIVE_TEMPLATE_HEADERS
# Synthetic price-list names in N17:AP17 of the Wzorzec pliku zbiorczego, which Przygotowanie copies into the Plik
# zbiorczy; the kind page of Uzupełnienie shows them over the quantity columns.
PRICE_LIST = (
    "Dodatek za usterkę po godzinach", "Instalacja internetu", "Instalacja telewizji", "Multiroom",
    "Aktywacja telefonu", "Dostarczenie urządzenia", "Drukowanie umowy", "Prace niestandardowe (rbh)",
    "Dojazd do klienta", "Przyłącze w mikrokanalizacji", "Przyłącze napowietrzne",
    "Przyłącze w budynku wielorodzinnym", "Montaż ONT", "Przyłącze doziemne", "Spawanie w mufie",
    "Przedłużenie przyłącza", "Spawanie gniazdka", "Trasa do splittera", "Instalacja wewnętrzna",
    "Dodatkowe urządzenie", "Dostarczenie dodatkowego urządzenia", "Usterka", "Sieć domowa do 30 m",
    "Sieć domowa do 10 m bez przebicia", "Sieć domowa do 15 m z przebiciem", "Modyfikacja sieci domowej",
    "Wywiad techniczny", "Prace dodatkowe z premii", "Deinstalacja usługi z odbiorem urządzeń",
)
# CZYNNOŚCI ZREALIZOWANE: a technician's description long enough to be cut to one line, with the row marker.
COMPLETED = "Wymiana gniazdka abonenckiego i przedłużenie kabla do salonu, klient prosi o kontakt przed wizytą"

# (start, worker, SKUTECZNE): one order of the previous period, then 06_12_10_2026 ending on Saturday.
ORDERS = (
    (datetime(2026, 10, 5, 9, 0), "wykonawca.a", "tak"),
    (datetime(2026, 10, 6, 8, 0), "wykonawca.a", "tak"),
    (datetime(2026, 10, 7, 10, 0), "wykonawca.b", "nie"),
    (datetime(2026, 10, 8, 12, 0), "wykonawca.b", "tak"),
    (datetime(2026, 10, 10, 9, 30), "wykonawca.c", "tak"),
)
# URZĄDZENIA by order number; every other order's URZĄDZENIA is its row marker, a device the Reguły ilości do not
# know, and prewencja is settled from the technician's description.
DEVICES = {4: "prewencja"}
# Order number → its Wiersz danych in the Plik zbiorczy of LAST_COMPLETE after Przygotowanie: the Zlecenia skuteczne
# of the period in the Rejestr's order from row 18.
COLLECTIVE_FILE_ROWS = {2: 18, 4: 19, 5: 20}

# Wycena w efenix: the Plik zbiorczy of the period of tests.fixtures.efenix, rows 18–20 one per Wykonawca: ready after
# the Wycena Emmetta and the quantity from the file, unknown to efenix, and an Emmett whose quantity differs from the file;
# row 21 is „Rozliczone” in efenix.
EFENIX_PERIOD = PERIOD
EFENIX_ORDERS = (
    EfenixOrder("#QX9001", cells={"O": 1, "T": 2}, amount=float(amount_of({"012": 1, "019": 2})), emmett={"012": 1}),
    EfenixOrder("#QX9002", worker="beata.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    EfenixOrder("#QX9003", worker="celina.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 2}),
    EfenixOrder(
        "#QX9004", worker="dorota.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}
    ),
)
# The orders of ``EFENIX_ORDERS`` with the status „Rozliczone” in efenix (an Zlecenie rozliczone, #821).
EFENIX_SETTLED = frozenset({"#QX9004"})
# The ADRES of every order (tests.fixtures.efenix.Order), pieces of it and of its Dane adresowe in the Atrapa: the rule of data (ADR 0025) keeps
# each out of the Logi.
EFENIX_ADDRESS_MARKERS = (ADDRESS, "TESTOWA", "Testowa", "Miasto-Dzielnica")
