"""Porównuje budowę stron efenix z Atrapą efenix samym odczytem; uruchom przed pierwszą Wyceną w efenix i po Zgłoszeniu z Zatrzymania okna efenix.

Narzędzie dla Maksa, poza CI (ADR 0024). Łączy się z Chrome, w którym Maks jest zalogowany do efenix kontem taty, i
sprawdza budowę, której używa Wycena w efenix i którą odtwarza Atrapa efenix (``tests/fixtures/atrapa_efenix.py``).
Żadna strona efenix nie działa przy tym w przeglądarce: każde żądanie do efenix narzędzie wysyła samo, z ciasteczkami
sesji domyślnego kontekstu Chrome (``contexts[0].request``, bez kart i bez skryptów), tylko z listy ``ALLOWED``
porównywanej po pełnej ścieżce i hoście ``--efenix-url``, i nigdy nie podąża za przekierowaniem: przekierowanie na
``page_login.php`` i odpowiedź szukania z ostrzeżeniem o wygasłej sesji (``efenix_page.SearchWarning``) to brak
sesji, a inne przekierowanie to różnica. HTML z odpowiedzi składa parserem przeglądarki we własnej karcie
w osobnym kontekście bez ciasteczek, z wyłączonym JavaScriptem i service workerami, z której nie wychodzi żadne żądanie
(obraz, styl, ramka, przejście, prefetch; ``parser_page``). Kart taty nie zmienia: z ``--emmett`` tylko czyta okno
Emmetta w karcie, w której Maks sam kliknął przycisk Emmetta. Sprawdza:

- lista zleceń: elementy ``efenix_page.Element`` listy zleceń (pole ``Numer``) i skrypt ``js/index.js``, który lista ładuje,
  z nazwami ``efenix_page.SCRIPT_USES`` listy (Enter w polu ``Numer`` wysyła ``action_fill_orders.php`` z polem
  ``numer``);
- tabela wyników: szukanie ``--numer`` tak jak skrypt listy w domyślnym stanie listy (POST ``action_fill_orders.php``
  z każdym polem, które wysyła wtedy skrypt listy, bez ``xrodzaj``, z pustymi filtrami, pierwszym ``sortowanie`` i
  ``na_stronie`` jak w domyślnym ustawieniu listy), a odpowiedź czyta
  ``efenix_page.read_results``, odczyt Wyceny w efenix, ze statusem, loginem realizatora i ``Dane adresowe`` w każdym
  wierszu, które reguła adresu (``efenix_address.readable``) rozbiera na ulicę, numer domu i lokal, bo z tych części
  Logi Uruchomienia mówią, czym różni się adres (przy błędzie odczytu każda różnica tabeli według reguł Wyceny,
  ``efenix_page.table_faults``: nagłówek kolumny nie raz, liczba komórek, link ``page_order_edit.php?id=``, pusty numer
  albo id, i do tego status poza ``.badge``, w którym pokazuje go Atrapa); ostrzeżenie „Nie znaleziono pasujących wyników”, którym efenix odpowiada na numer, którego nie zna,
  Wycena czyta jak tabelę bez wierszy, więc ``--numer`` takiego numeru sprawdza i tę odpowiedź;
- strona zlecenia (do ``ORDERS_TO_OPEN`` zleceń z tabeli, najpierw „Do wyceny”, aż znajdzie pustą datę wykonania):
  ``efenix_page.read_order`` (data wykonania ``RRRR-MM-DD`` albo pusta, kwota końcowa, pola Ilość), a na pierwszym
  zleceniu elementy ``efenix_page.Element`` strony zlecenia, które efenix ma na każdej (okno daty wykonania, przycisk i okno Emmetta; przycisk Emmetta
  widoczny w samym HTML, bez stylów efenix, a propozycja w oknie Emmetta ``#emmett-propozycja`` pusta, bez elementu i
  tekstu, jak w Atrapie, zanim skrypt strony włoży do niej propozycję; przycisk Przekazania do akceptacji, okno zmiany
  statusu ``#dialog_forward_yes_no`` i jego „Tak” ``.btn-ok``, okno informacji ``#dialog_info`` z tekstem
  ``#dialog_info_field_info`` i przyciskiem zamknięcia, w którym efenix odmawia Przekazania, bez klikania), przycisk
  anulowania, który ma Atrapa, skrypt
  ``js/page_order_edit.js`` (pod adresem z listy ``ALLOWED``) z nazwami ``efenix_page.SCRIPT_USES`` strony zlecenia
  (pickadate z ``onSet``, „Potwierdź” daty, Emmett, zapis ilości z ``price_all``, „Tak” okna zmiany statusu z
  ``action_change_status.php``, ``xstatus``, ``order_id`` i ``main_id``, odmowa Przekazania w ``dialog_info`` i
  ``dialog_info_field_info``) i karty pozycji
  ``.card.rounded-lg.kolorek``: karta z polem Ilość ma cenę w tekście ``.col-sm-1.mt-2 > span.text-default > small``,
  a karta z ceną wpisywaną samo pole ``input.wycena-cena``; każdy kod ``INDEKS_NNN_NNN`` jest pozycją Atrapy
  (``model_efenix.CATALOG``) z tym samym rodzajem karty, przy czym strona może mieć tylko część pozycji Atrapy, jak
  zlecenia efenix z mniejszą liczbą pozycji wyceny, a strona bez żadnej karty pozycji to część niesprawdzona; cena
  pozycji z przypisania kolumn (``efenix_positions.POSITION_OF_COLUMN``) jest równa kosztowi jej kolumny w wierszu 14 Wzorca pliku zbiorczego, bo z kosztów tego wiersza liczy się ``Kwota`` (AU),
  z którą Wycena w efenix porównuje kwotę końcową efenix;
- bez sesji (żądania bez ciasteczek, więc sesja taty trwa): lista przekierowuje na ``page_login.php``, szukanie
  odpowiada 2xx bez przekierowania samym ostrzeżeniem o wygasłej sesji, które rozpoznaje Wycena w efenix
  (``efenix_page.SearchWarning``), a strona logowania ma formularz ``action_login.php`` z polami
  ``field_signum``, ``field_password`` i ``fingerprint``.

Skryptów stron narzędzie nie uruchamia, więc ich działania nie widzi: sprawdza tylko, że skrypt ma nazwy, na których
polega okno Wyceny w efenix. Na każdej otwartej stronie zlecenia sprawdza za to, że ukryte pole ``#main_id``
(``efenix_page.ORDER_ID_FIELD``) jest raz i ma wartość ``id`` z linku listy, którym narzędzie otworzyło stronę. Strażnik
okna przepuszcza Przekazanie tylko z ``order_id`` równym temu ``id``, a skrypt strony efenix z rekonesansu 1.11.2026
wysyła jako ``order_id`` wartość ``#main_id``. Że skrypt robi to dalej, narzędzie widzi tylko po nazwach ``order_id`` i
``main_id`` w skrypcie, które stoją w nim też przy innych działaniach. Przycisku kalendarza daty wykonania (``#button-calendar``) nie sprawdza: okno klika go tylko
przy pustej dacie wykonania, a efenix pokazuje go najpewniej tylko wtedy, więc wynik zawsze ma linię ``NIESPRAWDZONE``
z prośbą o sprawdzenie ręczne (``DATE_BUTTON_BY_HAND``).

Propozycji Emmetta narzędzie samo nie pobiera: ``action_fill_emmett.php`` nie jest na liście ``ALLOWED``. Skrypt strony
zlecenia efenix (rekonesans z 1.11.2026) wysyła w nim tylko ``order_id`` z przycisku Emmetta, odpowiedź 2xx wkłada do
``#emmett-propozycja`` i pokazuje okno Emmetta z podglądem, co i z jakimi ilościami Emmett uzupełni. Ilości wpisuje
dopiero „Załaduj do zlecenia” (``action_load_emmett.php``), a okno bez zmian w zleceniu zamyka „Zamknij”; tak pamięta to
Maks i tak działa Atrapa, ale co serwer efenix robi przy ``action_fill_emmett.php``, nikt nie sprawdził. Bez
``--emmett`` wynik ma więc zawsze linię ``NIESPRAWDZONE`` o budowie propozycji (``PROPOSAL_BY_HAND``).

Z ``--emmett`` przycisk Emmetta klika Maks, a narzędzie po jego Enter czyta żywe drzewo propozycji w oknie Emmetta tej
karty Chrome, której strona to strona zlecenia efenix spod ``--efenix-url`` (``_READ_TREE``): sam odczyt DOM funkcją,
która przechodzi drzewo ``#emmett-propozycja`` i oddaje znaczniki, klasy (cyfra to 9), nazwy atrybutów bez wartości i
tekst z maską (litera to a, cyfra to 9), bez skryptu, stylu i ramki w środku. Okna i propozycje liczy, a czy propozycja
coś pokazuje (``efenix_page.SHOWS_ANYTHING``), sprawdza odczyt Wyceny ``efenix_page.emmett_window``: lokatorem
Playwrighta, także w shadow DOM, kilkoma pytaniami do karty zamiast jednego. Niczego nie klika, nie przewija, nie
zamyka i nie wysyła.
Odczyt widzi propozycję po skryptach strony, także tę, którą narysował skrypt w odpowiedzi ``action_fill_emmett.php``.
Potem narzędzie uruchamia Atrapę efenix na tym komputerze, otwiera jej zlecenie z propozycją dwóch pozycji
(``ATRAPA_PROPOSAL``) w osobnym oknie Chrome bez ciasteczek taty, klika w nim przycisk Emmetta, czyta jej
okno tą samą funkcją i zamyka okno. Budowa jest zgodna, gdy oba drzewa mają te same znaczniki, klasy, nazwy atrybutów i
miejsca tekstu, przy czym kolejne takie same węzły to jeden (liczba pozycji propozycji zależy od zlecenia). Inna budowa to
``RÓŻNICA`` z oboma drzewami z maską. ``NIESPRAWDZONE`` z powodem, nigdy zgodna, jest propozycja bez Enter, bez karty
strony zlecenia efenix (także strona zlecenia w ramce innej strony), z oknem Emmetta zamkniętym w każdej karcie (zamknięte
przed odczytem, strona przeładowana, odpowiedź jeszcze nie przyszła), otwartym w kilku kartach, z kartą, której odczyt
padł (karta zmieniła stronę w trakcie odczytu), i z propozycją, która nic nie pokazuje (pusta albo same białe znaki: Emmett
nic nie zaproponował albo propozycja padła, a tego narzędzie nie rozróżni). Karta, w której widać okno Emmetta, a jej
strona po skryptach nie ma dokładnie jednego ``#dialog_emmett`` (widocznego albo nie) albo potem dokładnie jednego
``#dialog_emmett #emmett-propozycja``, to ``RÓŻNICA``: rozstrzyga to ta sama reguła okna Emmetta co w Wycenie
(``efenix_page.emmett_window_fault``), najpierw okno na całej stronie, potem propozycja w nim. Chwila liczenia jest
inna: Wycena liczy okna zaraz po kliknięciu Emmetta i jeszcze raz, gdy któreś okno Emmetta jest już widoczne, a
narzędzie liczy je po Enter. Drugie okno,
które skrypt strony dopisze, zanim przeglądarka pokaże pierwsze, Wycena zatrzymuje więc z ``ElementCount`` tak, jak
narzędzie zgłasza ``RÓŻNICA``, ale okno dopisane później Wycena przepuszcza (próba na Atrapie 7.11.2026: ukryte okno
dopisane 300 ms po pokazaniu propozycji). Widoczność odczyt sprawdza tylko dla okna,
nie dla propozycji: czyta drzewo DOM, jak reguła okna Wyceny (``efenix_page.SHOWS_ANYTHING``), więc propozycja
ukryta stylem w widocznym oknie (``display: none`` albo ``visibility: hidden`` na ``#emmett-propozycja``) ma zgodną
budowę, choć tata widzi puste okno (próba na Atrapie 6.11.2026, #953).

Uruchomienie: Chrome z osobnym profilem i zdalnym debugowaniem (macOS, Linux, Windows), w nim logowanie do efenix kontem
taty, potem narzędzie:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.efenix-zgodnosc"
    google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.efenix-zgodnosc"
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\\.efenix-zgodnosc"
    .venv/bin/python tools/zgodnosc_efenix.py --efenix-url <adres listy zleceń, …/index.php> --cdp http://127.0.0.1:9222 [--numer <numer>] [--emmett]

Pomiar propozycji Emmetta na Macu, krok po kroku:

1. Uruchom Chrome pierwszym poleceniem wyżej i zaloguj się w nim do efenix kontem taty.
2. W tym Chrome otwórz w jednej karcie stronę zlecenia „Do wyceny”, któremu Emmett coś proponuje.
3. Uruchom narzędzie poleceniem wyżej z ``--emmett``. Po sprawdzeniu stron narzędzie prosi
   (``EMMETT | …`` na stderr) o kliknięcie przycisku Emmetta.
4. W Chrome kliknij przycisk Emmetta i poczekaj, aż okno Emmetta pokaże propozycję. Nie klikaj „Załaduj do zlecenia”:
   ono wpisuje ilości do zlecenia taty.
5. W oknie narzędzia wciśnij Enter. Narzędzie czyta okno Emmetta, a potem prosi o jego zamknięcie i na chwilę otwiera okno
   Atrapy efenix.
6. W Chrome zamknij okno Emmetta przyciskiem „Zamknij”.

Czasu przebiegu w prawdziwym efenix nikt nie zmierzył: narzędzie wysyła po kolei najwyżej 17 odczytów (lista, jej
skrypt, szukanie, do ``ORDERS_TO_OPEN`` stron zleceń, skrypt strony zlecenia i trzy odczyty bez sesji), więc trwa mniej
więcej tyle, ile tyle odpowiedzi efenix (na Atrapie 0,98 s: ``pytest --durations`` testu zgodnej Atrapy 5.11.2026), a odpowiedź, która nie przyjdzie w ``--limit-ms``
(domyślnie 30 s), kończy je kodem 1.

Na czas sprawdzania w Chrome otwiera się okno narzędzia, w którym widać złożony HTML stron bez stylów i skryptów;
narzędzie zamyka je na końcu. Wzorzec pliku zbiorczego to domyślnie ten z konfiguracji narzędzia
(``config/Wzorzec pliku zbiorczego.xlsx``, jak w Centrum rozliczeń), a inny podaje ``--wzorzec``.

Wynik (na stdout): linie ``RÓŻNICA | <część> | <co>`` i ``NIESPRAWDZONE | <część> | <co>``, na końcu liczby jednych i
drugich. Kod 0: bez różnic, a niesprawdzone są tylko przycisk kalendarza i, bez ``--emmett``, budowa propozycji Emmetta;
kod 2: różnice albo inne części niesprawdzone, także propozycja Emmetta niesprawdzona z ``--emmett``. Wynik nie zawiera numerów zleceń, adresów, loginów ani cen: tylko nazwy elementów,
liczby, kody pozycji z kolumnami i postać daty i kwoty (cyfry jako ``9``). Kod 1: brak Chrome pod ``--cdp``,
nieczytelny Wzorzec, efenix nie odpowiada albo Chrome nie jest zalogowany; opis na stderr.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import enum
from pathlib import Path
import re
import socket
import sys
from typing import Final, TypedDict, cast
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import APIRequestContext, Browser, Page, ProxySettings, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Korzeń repozytorium dla Atrapy efenix (``tests.fixtures``), z której narzędzie bierze ścieżki i pola szukania, i
# ``tools/lib`` dla modelu efenix z kodami pozycji i zleceniem.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from rozliczenia import workbook_files
from rozliczenia.collective_layout import COST_ROW
from rozliczenia.efenix_address import readable
from rozliczenia.efenix_browser import TIMEOUT_MS
from rozliczenia.efenix_page import (
    AMOUNT,
    EXECUTION_DATE,
    LOGIN_FORM,
    LOGIN_PAGE,
    ORDER_ID_FIELD,
    ORDER_PAGE,
    QUANTITY,
    SCRIPT_USES,
    SEARCH,
    SHOWS_ANYTHING,
    Cell,
    ColumnFault,
    Element,
    PageElement,
    PageKind,
    ResultsTable,
    RowFault,
    RowsFault,
    ScriptUse,
    SearchWarning,
    TableFault,
    emmett_window,
    emmett_window_fault,
    listed,
    read_order,
    results_table,
    search_warning,
    table_faults,
)
from rozliczenia.efenix_checks import PRICING_STATUS
from rozliczenia.efenix_window import ElementCount, UnexpectedPage
from rozliczenia.efenix_positions import POSITION_OF_COLUMN
from rozliczenia.tool_files import COLLECTIVE_TEMPLATE
from rozliczenia.workbook_files import WorkbookError

from model_efenix import CATALOG, EfenixOrder

from tests.fixtures.atrapa_efenix import (
    LIST_PAGE,
    LIST_ROWS_PER_PAGE,
    LIST_SCRIPT,
    LIST_SEARCH_FIELDS,
    ORDER_SCRIPT,
    atrapa_efenix,
)

# Jedyne żądania do efenix, które narzędzie wysyła: (metoda, ścieżka względem katalogu ``--efenix-url``). Zapis ilości,
# Emmett, data wykonania, zmiana statusu, Przekazanie do akceptacji, anulowanie, logowanie i wylogowanie nie są na liście.
ALLOWED: Final = frozenset(
    {
        ("GET", LIST_PAGE),
        ("GET", LIST_SCRIPT),
        ("POST", SEARCH),
        ("GET", ORDER_PAGE),
        ("GET", ORDER_SCRIPT),
        ("GET", LOGIN_PAGE),
    }
)
# Szukanie z pola Numer tak, jak wysyła je skrypt listy efenix (``js/index.js``) w domyślnym stanie listy, który
# odtwarza Atrapa: każde jego pole w jego kolejności, bez ``xrodzaj``, którego skrypt wtedy nie wysyła, z pustymi
# filtrami, pierwszą opcją ``sortowanie`` i liczbą wierszy ``na_stronie`` z domyślnego ustawienia listy. Pusty
# ``xrodzaj`` daje w efenix zero wyników, a brak ``na_stronie`` stronę błędu bazy danych (#822). ``asp`` zostaje pusty
# zamiast nazwy ASP konta taty: w pomiarze z 4.11.2026 pusty nie zmienił wyniku.
SEARCH_FORM: Final = dict.fromkeys(LIST_SEARCH_FIELDS, "") | {
    "rodzaj": "szukanie",
    "strona": "1",
    "na_stronie": LIST_ROWS_PER_PAGE,
    "sortowanie": "1",
}
POSITION_CODE: Final = re.compile(r"INDEKS_\d{3}_\d{3}")
ORDERS_TO_OPEN: Final = 10
NOT_SIGNED_IN: Final = "Chrome nie jest zalogowany do efenix: zaloguj się kontem taty i uruchom narzędzie jeszcze raz"
LOGGED_OUT_MIDWAY: Final = "efenix wylogował w trakcie sprawdzania: zaloguj się i uruchom narzędzie jeszcze raz"


class Part(enum.Enum):
    """Część efenix, której dotyczy linia wyniku."""

    LIST = "lista zleceń"
    RESULTS = "tabela wyników"
    ORDER = "strona zlecenia"
    PRICING = "pozycje wyceny"
    LOGGED_OUT = "bez sesji"
    LOGIN = "strona logowania"
    PROPOSAL = "propozycja Emmetta"


# Elementy stron, których używa okno Wyceny w efenix (``efenix_page.Element``) i które efenix ma na każdej stronie tego
# rodzaju; przycisku kalendarza na każdej stronie zlecenia nie ma, więc narzędzie nie sprawdza go na pierwszym zleceniu.
LIST_ELEMENTS: Final = tuple(element.element for element in Element if element.page is PageKind.LIST and element.always_on_page)
ORDER_ELEMENTS: Final = tuple(element.element for element in Element if element.page is PageKind.ORDER and element.always_on_page)
# Elementy, których Wycena w efenix nie używa, a Atrapa ma: przycisk anulowania, którego okno nie może kliknąć, i
# formularz logowania, w którym tata loguje się sam.
UNUSED_ORDER_ELEMENTS: Final = (PageElement("przycisk anulowania", "#button_forward_to_cancel"),)
LOGIN_ELEMENTS: Final = (
    PageElement("formularz logowania", LOGIN_FORM),
    PageElement("pole loginu", "input#field_signum"),
    PageElement("pole hasła", "input#field_password"),
    PageElement("pole fingerprint", 'input[name="fingerprint"]'),
)
PRICING_CARD: Final = ".card.rounded-lg.kolorek"
# Przycisk i okno Emmetta i propozycja w oknie Emmetta: element, do którego skrypt strony wkłada odpowiedź
# ``action_fill_emmett.php``.
EMMETT_BUTTON: Final = Element.EMMETT_BUTTON.selector
DIALOG: Final = Element.EMMETT_DIALOG.selector
PROPOSAL: Final = Element.PROPOSAL.selector
# Zlecenie Atrapy efenix, na którym narzędzie z ``--emmett`` klika Emmetta, żeby przeczytać okno Emmetta Atrapy: propozycja
# dwóch pozycji z przypisania kolumn.
ATRAPA_PROPOSAL: Final = EfenixOrder("ATRAPA-1", "ZL/ATRAPA/1", "atrapa", "ul.Atrapy 1", emmett={"012": 2, "021": 1})
# Tyle znaków tekstu z maską pokazuje wynik w drzewie propozycji.
TEXT_SHOWN: Final = 40
# Część, której narzędzie nie sprawdza nigdy, a Maks sprawdza ręcznie; zawsze w wyniku jako ``NIESPRAWDZONE``.
DATE_BUTTON_BY_HAND: Final = (
    Part.ORDER,
    "przycisk kalendarza daty wykonania nie jest sprawdzany: sprawdź ręcznie w efenix na zleceniu "
    f"„{PRICING_STATUS}” bez daty wykonania, że jest przycisk otwierający okno wyboru daty",
)
# Budowa propozycji Emmetta bez ``--emmett``: narzędzie samo nie wysyła ``action_fill_emmett.php``, a okno Emmetta czyta
# tylko po kliknięciu Maksa; wtedy zawsze w wyniku jako ``NIESPRAWDZONE``.
PROPOSAL_BY_HAND: Final = (
    Part.PROPOSAL,
    "budowa propozycji Emmetta nie jest sprawdzana: uruchom narzędzie z --emmett i kliknij w Chrome przycisk Emmetta,"
    " gdy narzędzie o to poprosi",
)
# Rozmowa z Maksem przy ``--emmett`` (na stderr): prośba o kliknięcie Emmetta i, po odczycie okna, o jego zamknięcie.
ASK_EMMETT: Final = (
    "EMMETT | W Chrome na stronie zlecenia „Do wyceny”, któremu Emmett coś proponuje, kliknij przycisk Emmetta i poczekaj,"
    " aż okno Emmetta pokaże propozycję. Nie klikaj „Załaduj do zlecenia”: ono wpisuje ilości do zlecenia. Potem wciśnij"
    " tu Enter."
)
CLOSE_EMMETT: Final = "EMMETT | Okno Emmetta przeczytane: zamknij je w Chrome przyciskiem „Zamknij”."
NO_ENTER: Final = "bez Enter po kliknięciu Emmetta: okna Emmetta narzędzie nie czytało"
NO_ORDER_TAB: Final = (
    f"w Chrome nie ma karty ze stroną zlecenia efenix ({ORDER_PAGE} spod --efenix-url): otwórz zlecenie w karcie,"
    " kliknij w niej przycisk Emmetta i uruchom narzędzie jeszcze raz"
)
READ_FAILED: Final = (
    "odczyt karty strony zlecenia efenix padł (karta zmieniła stronę albo zamknęła się w trakcie odczytu): kliknij"
    " Emmetta jeszcze raz i uruchom narzędzie jeszcze raz"
)
SHOWS_NOTHING: Final = (
    "okno Emmetta nic nie pokazuje (bez elementu i bez tekstu): Emmett nic nie zaproponował albo propozycja padła;"
    " kliknij Emmetta na zleceniu, któremu Emmett coś proponuje, i uruchom narzędzie jeszcze raz"
)

# Czy pierwszy element ``selector`` coś pokazuje według reguły okna Wyceny (``efenix_page.SHOWS_ANYTHING``, #908);
# ``false`` bez elementu.
_SHOWS_ANYTHING: Final = f"""(selector) => {{
    const element = document.querySelector(selector);
    return element !== null && ({SHOWS_ANYTHING})(element);
}}"""
# Dokument karty: chwila, w której zaczęło się jego wczytanie; nowa strona albo przeładowanie ma inną.
_DOCUMENT: Final = "performance.timeOrigin"
# Dokument karty (``_DOCUMENT``) i czy w nim któreś z okien Emmetta (``DIALOG``) jest widoczne: ma pudełko (nie
# ``display: none``) i nie ``visibility: hidden``.
_ANY_VISIBLE: Final = (
    f"(dialogs) => [{_DOCUMENT}, dialogs.some((dialog) => dialog.getClientRects().length > 0 && getComputedStyle(dialog).visibility !== 'hidden')]"
)
# Drzewo propozycji w oknie Emmetta, bez sprawdzania widoczności propozycji i jej węzłów. Węzeł drzewa to tekst z maską
# (litera to a, cyfra to 9, białe znaki jak jedna spacja; sam biały znak pomija) albo element: znacznik, klasy (cyfra to
# 9), nazwy atrybutów poza ``class`` bez wartości i węzły w środku, a w skrypcie, stylu, szablonie, ramce i ``noscript``
# bez nich. Komentarz pomija. Funkcja tylko czyta.
_READ_TREE: Final = """(proposal) => {
    const opaque = ['script', 'style', 'template', 'iframe', 'noscript'];
    const mask = (text) => text.replace(/\\s+/g, ' ').trim().replace(/\\p{L}/gu, 'a').replace(/\\p{N}/gu, '9');
    const read = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
            const text = mask(node.data);
            return text === '' ? null : {text: text};
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return null;
        return {
            tag: node.localName,
            classes: [...node.classList].map((name) => name.replace(/\\d/g, '9')).sort(),
            attributes: node.getAttributeNames().filter((name) => name !== 'class').sort(),
            nodes: opaque.includes(node.localName) ? [] : nodes(node),
        };
    };
    const nodes = (parent) => [...parent.childNodes].map(read).filter((node) => node !== null);
    return nodes(proposal);
}"""
# Karta pozycji: ``id`` pól Ilość, ``id`` pól ceny wpisywanej i ceny z tekstu karty.
_READ_CARDS: Final = """([card, quantity]) => [...document.querySelectorAll(card)].map((element) => ({
    quantity: [...element.querySelectorAll(quantity)].map((input) => input.id),
    price: [...element.querySelectorAll('input.wycena-cena')].map((input) => input.id),
    shown: [...element.querySelectorAll('.col-sm-1.mt-2 > span.text-default > small')].map((small) => small.textContent.trim()),
}))"""


class _Card(TypedDict):
    quantity: list[str]
    price: list[str]
    shown: list[str]


class _Node(TypedDict, total=False):
    """Węzeł drzewa propozycji z ``_READ_TREE``: ``text`` w węźle tekstu, a pozostałe klucze w elemencie."""

    text: str
    tag: str
    classes: list[str]
    attributes: list[str]
    nodes: list[_Node]


@dataclass(frozen=True)
class _Window:
    """Widoczne okno Emmetta w karcie: różnica z reguły okna Wyceny (``efenix_page.emmett_window_fault``), czy jedyna
    propozycja coś pokazuje (``efenix_page.emmett_window``) i jej drzewo (puste przy różnicy)."""

    fault: ElementCount | None
    shows: bool
    nodes: list[_Node]


class _PageChanged(Exception):
    """Karta zmieniła stronę między odczytami okna Emmetta, więc odczyty są z dwóch dokumentów."""


class ToolError(Exception):
    """Narzędzie nie może sprawdzić efenix (brak Chrome, Wzorca, odpowiedzi efenix albo sesji); opis dla Maksa."""


@dataclass
class Report:
    """Różnice i części niesprawdzone; ``checked`` to liczby tego, co narzędzie obejrzało."""

    differences: list[tuple[Part, str]] = field(default_factory=list)
    unchecked: list[tuple[Part, str]] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)
    proposal_by_hand: bool = True

    def differ(self, part: Part, what: str) -> None:
        self.differences.append((part, what))

    def lines(self) -> list[str]:
        """Wynik dla Maksa; po częściach niesprawdzonych stoi zawsze ``DATE_BUTTON_BY_HAND``, a bez pomiaru propozycji
        Emmetta (``proposal_by_hand``) ``PROPOSAL_BY_HAND``."""

        head = " | ".join(f"{name}: {count}" for name, count in self.checked.items())
        unchecked = [*self.unchecked, DATE_BUTTON_BY_HAND, *([PROPOSAL_BY_HAND] if self.proposal_by_hand else [])]
        lines = [f"ZGODNOŚĆ ATRAPY EFENIX Z EFENIX | {head}"]
        lines += [f"RÓŻNICA | {part.value} | {what}" for part, what in self.differences]
        lines += [f"NIESPRAWDZONE | {part.value} | {what}" for part, what in unchecked]
        lines.append(f"RÓŻNICE: {len(self.differences)} | NIESPRAWDZONE: {len(unchecked)}")
        return lines


def allowed(method: str, url: str, efenix_url: str) -> bool:
    """Czy narzędzie może wysłać to żądanie: ``ALLOWED`` po pełnej ścieżce w katalogu ``efenix_url``, na jego hoście."""

    address, efenix = urlparse(url), urlparse(efenix_url)
    folder = efenix.path.rpartition("/")[0] + "/"
    if (address.scheme, address.netloc) != (efenix.scheme, efenix.netloc) or address.params or address.fragment:
        return False
    return address.path.startswith(folder) and (method, address.path.removeprefix(folder)) in ALLOWED


@dataclass(frozen=True)
class _Answer:
    """Odpowiedź efenix: kod, adres przekierowania (``None``: bez przekierowania) i treść."""

    status: int
    location: str | None
    text: str


class _Efenix:
    """Odczyty efenix z ``ALLOWED`` wysyłane przez ``request`` bez podążania za przekierowaniem."""

    def __init__(self, request: APIRequestContext, url: str, *, timeout_ms: int) -> None:
        self._request = request
        self.url = url
        self._timeout_ms = timeout_ms

    def address(self, name: str, **query: str) -> str:
        return urljoin(self.url, name + (f"?{urlencode(query)}" if query else ""))

    def name(self, url: str) -> str:
        """Ścieżka adresu względem katalogu efenix (adres innego hosta: sam host), bez zapytania."""

        address, efenix = urlparse(url), urlparse(self.url)
        if address.netloc != efenix.netloc:
            return address.netloc
        return address.path.removeprefix(efenix.path.rpartition("/")[0] + "/")

    def get(self, url: str) -> _Answer:
        return self._send("GET", url, {})

    def post(self, url: str, form: Mapping[str, str]) -> _Answer:
        return self._send("POST", url, form)

    def to_login(self, answer: _Answer) -> bool:
        return answer.location is not None and urlparse(answer.location).path == urlparse(self.address(LOGIN_PAGE)).path

    def _send(self, method: str, url: str, form: Mapping[str, str]) -> _Answer:
        if not allowed(method, url, self.url):
            raise ValueError(f"{method} {self.name(url)} nie jest na liście dozwolonych żądań")
        try:
            response = self._request.fetch(
                url,
                method=method,
                form=dict(form) if method == "POST" else None,
                max_redirects=0,
                timeout=self._timeout_ms,
            )
        except PlaywrightError as error:
            raise ToolError("efenix nie odpowiada pod --efenix-url") from error
        try:
            location = urljoin(url, response.headers["location"]) if 300 <= response.status < 400 and "location" in response.headers else None
            return _Answer(response.status, location, "" if location is not None else response.text())
        finally:
            response.dispose()


def template_costs(path: Path) -> dict[str, Decimal | None]:
    """Koszt z wiersza 14 Wzorca pliku zbiorczego w każdej kolumnie przypisania kolumn; ``None``: komórka bez liczby."""

    try:
        content = workbook_files.template_content(path)
        with workbook_files.open_workbook(path, content, read_only=True) as workbook:
            sheet = cast(Worksheet, workbook.active)  # tylko do odczytu: ReadOnlyWorksheet
            row = next(sheet.iter_rows(min_row=COST_ROW, max_row=COST_ROW, values_only=True), ())
    except WorkbookError as error:
        raise ToolError(f"Wzorzec pliku zbiorczego {path}: {error.problem.value}") from error
    costs: dict[str, Decimal | None] = {}
    for column in POSITION_OF_COLUMN:
        index = column_index_from_string(column) - 1
        value = row[index] if index < len(row) else None
        costs[column] = Decimal(str(value)) if isinstance(value, int | float | Decimal) and not isinstance(value, bool) else None
    return costs


def check(signed_in: _Efenix, signed_out: _Efenix, page: Page, costs: Mapping[str, Decimal | None], *, number: str = "") -> Report:
    """Sprawdza efenix odczytami ``signed_in`` (sesja taty) i ``signed_out`` (bez ciasteczek); HTML składa w ``page``."""

    report = Report()
    _check_signed_in(signed_in, page, costs, report, number=number)
    _check_signed_out(signed_out, page, report)
    return report


@contextmanager
def parser_page(browser: Browser, *, timeout_ms: int) -> Iterator[Page]:
    """Karta w nowym kontekście bez ciasteczek, JavaScriptu i service workerów, z której nie wychodzi żadne żądanie.

    Przejście (``<meta http-equiv="refresh">``, ramka) dostaje od narzędzia odpowiedź 204, więc karta zostaje przy
    złożonym HTML, a każde inne żądanie (obraz, styl, skrypt) narzędzie przerywa. Żądania, których przechwytywanie
    Playwrighta nie widzi (``<link rel="prefetch">`` wysyła proces przeglądarki), idą przez proxy kontekstu na port, który
    narzędzie zajmuje bez nasłuchu, więc połączenie jest odrzucane (adresy lokalne Playwright też kieruje przez proxy).
    """

    with socket.socket() as dead:
        dead.bind(("127.0.0.1", 0))
        proxy: ProxySettings = {"server": f"http://127.0.0.1:{dead.getsockname()[1]}"}
        context = browser.new_context(java_script_enabled=False, service_workers="block", proxy=proxy)
        try:
            context.route("**/*", _stay)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            yield page
        finally:
            context.close()


def _stay(route: Route) -> None:
    if route.request.is_navigation_request():
        route.fulfill(status=204)
    else:
        route.abort()


def _show(page: Page, html: str) -> None:
    page.set_content(html, wait_until="domcontentloaded")


def _text(efenix: _Efenix, answer: _Answer, what: str, part: Part, report: Report) -> str | None:
    """Treść odpowiedzi 2xx; przekierowanie na stronę logowania kończy narzędzie, a inne i inny kod to różnica."""

    if efenix.to_login(answer):
        raise ToolError(LOGGED_OUT_MIDWAY)
    if answer.location is not None:
        report.differ(part, f"{what} przekierowuje na {efenix.name(answer.location)}")
    elif not 200 <= answer.status < 300:
        report.differ(part, f"{what}: odpowiedź {answer.status}")
    else:
        return answer.text
    return None


def _check_signed_in(efenix: _Efenix, page: Page, costs: Mapping[str, Decimal | None], report: Report, *, number: str) -> None:
    listing = efenix.get(efenix.url)
    if efenix.to_login(listing):
        raise ToolError(NOT_SIGNED_IN)
    html = _text(efenix, listing, f"GET {LIST_PAGE}", Part.LIST, report)
    if html is None:
        report.unchecked.append((Part.RESULTS, "bez listy zleceń"))
        return
    _show(page, html)
    _check_elements(page, Part.LIST, LIST_ELEMENTS, report)
    _check_script(efenix, page, efenix.url, Part.LIST, LIST_SCRIPT, SCRIPT_USES[PageKind.LIST], report)
    answer = efenix.post(efenix.address(SEARCH), {**SEARCH_FORM, "numer": number})
    results = _text(efenix, answer, f"POST {SEARCH}", Part.RESULTS, report)
    table: ResultsTable | None = None
    if results is not None:
        match results_table(page, results):
            case SearchWarning.SESSION_EXPIRED:
                raise ToolError(LOGGED_OUT_MIDWAY)
            case SearchWarning.NOT_FOUND:
                # Wycena w efenix czyta tę odpowiedź jak tabelę bez wierszy (``read_results``).
                table = ResultsTable((), ())
            case ResultsTable() as read:
                table = read
            case None:
                report.differ(Part.RESULTS, f"odpowiedź POST {SEARCH} bez tabeli")
    if results is None or table is None:
        report.unchecked += [(Part.ORDER, "bez tabeli wyników nie ma zleceń do otwarcia"), (Part.PRICING, "bez strony zlecenia")]
        return
    _check_results(table, report)
    rows = sorted((row for row in table.rows if len(_links(row)) == 1), key=lambda row: PRICING_STATUS not in _badges(row))
    if not table.rows:
        report.unchecked.append((Part.RESULTS, "tabela wyników bez wierszy: podaj --numer, który znajduje zlecenia"))
    if not rows:
        report.unchecked += [(Part.ORDER, "żaden wiersz nie prowadzi do strony zlecenia"), (Part.PRICING, "bez strony zlecenia")]
        return
    _check_orders(efenix, page, [parse_qs(urlparse(_links(row)[0]).query).get("id", [""])[0] for row in rows], costs, report)


def _links(row: Sequence[Cell]) -> list[str]:
    return [cell.link for cell in row if cell.link]


def _badges(row: Sequence[Cell]) -> list[str]:
    return [cell.badge for cell in row if cell.badge is not None]


def _check_results(table: ResultsTable, report: Report) -> None:
    """Wycena w efenix czyta każdy wiersz ze statusem, loginem realizatora i adresem, który rozbiera reguła adresu; przy
    błędzie odczytu każda różnica tabeli według reguł Wyceny (``efenix_page.table_faults``) i wiersze bez statusu w
    ``.badge``, w którym pokazuje go Atrapa."""

    rows = table.rows
    report.checked["wiersze wyników"] = len(rows)
    try:
        orders = listed(table)
    except UnexpectedPage:
        report.differ(Part.RESULTS, "Wycena w efenix nie czyta tabeli wyników")
        report.differences += [(Part.RESULTS, _described(fault, table)) for fault in table_faults(table)]
        if missing := sum(not _badges(row) for row in rows):
            report.differ(Part.RESULTS, f"wiersze bez statusu w .badge: {missing} z {len(rows)}")
        return
    for what, missing in (
        ("statusu", sum(not order.status for order in orders)),
        ("loginu realizatora „(login)” z kolumny Wykonawca", sum(order.realizator is None for order in orders)),
        ("Dane adresowe", sum(not order.address for order in orders)),
        (
            "Dane adresowe jako ulicy, numeru domu i lokalu (reguła adresu ich nie rozbiera)",
            sum(bool(order.address) and not readable(order.address) for order in orders),
        ),
    ):
        if missing:
            report.differ(Part.RESULTS, f"Wycena w efenix nie czyta {what}: {missing} z {len(orders)} wierszy")


def _described(fault: TableFault, table: ResultsTable) -> str:
    """Różnica tabeli wyników dla Maksa; nagłówki są tekstem, który czyta Wycena w efenix."""

    match fault:
        case ColumnFault(header, found):
            shown = " / ".join(text or "(pusty)" for text in table.headers)
            return f"nagłówek zaczynający się od „{header}”: {found} zamiast 1 (nagłówki: {shown})"
        case RowsFault(row_fault, rows):
            match row_fault:
                case RowFault.CELLS:
                    what = f"wiersze z inną liczbą komórek niż nagłówków ({len(table.headers)})"
                case RowFault.LINK:
                    what = f"wiersze bez jednego linku {ORDER_PAGE}?id="
                case RowFault.EMPTY:
                    what = "wiersze z pustym numerem dokumentu albo id zlecenia w linku"
            return f"{what}: {rows} z {len(table.rows)}"


def _check_orders(efenix: _Efenix, page: Page, order_ids: Sequence[str], costs: Mapping[str, Decimal | None], report: Report) -> None:
    """Otwiera zlecenia z tabeli, aż sprawdzi budowę strony zlecenia i znajdzie pustą datę wykonania."""

    opened = report.checked["otwarte zlecenia"] = 0
    unread: Counter[str] = Counter()
    other_ids: Counter[str] = Counter()
    structure_checked = empty_found = False
    for order_id in order_ids[:ORDERS_TO_OPEN]:
        if structure_checked and empty_found:
            break
        address = efenix.address(ORDER_PAGE, id=order_id)
        html = _text(efenix, efenix.get(address), f"GET {ORDER_PAGE}", Part.ORDER, report)
        if html is None:
            break
        opened += 1
        _show(page, html)
        try:
            empty_found = empty_found or read_order(page)[0].execution_date is None
        except UnexpectedPage:
            unread[_shape(page)] += 1
        if (fault := _order_id_fault(page, order_id)) is not None:
            other_ids[fault] += 1
        if not structure_checked:
            _check_elements(page, Part.ORDER, (*ORDER_ELEMENTS, *UNUSED_ORDER_ELEMENTS), report)
            _check_proposal_before(page, report)
            _check_script(efenix, page, address, Part.ORDER, ORDER_SCRIPT, SCRIPT_USES[PageKind.ORDER], report)
            _check_positions(page, costs, report)
            structure_checked = True
    report.checked["otwarte zlecenia"] = opened
    for shape, count in unread.items():
        report.differ(Part.ORDER, f"Wycena w efenix nie czyta strony zlecenia ({shape}): {count} z {opened}")
    for fault, count in other_ids.items():
        report.differ(Part.ORDER, f"{fault}: {count} z {opened}; na nich strażnik okna zatrzyma Przekazanie do akceptacji")
    if not structure_checked:
        report.unchecked.append((Part.PRICING, "bez strony zlecenia"))
    elif not empty_found:
        report.unchecked.append((Part.ORDER, f"postać pustej daty wykonania: żadne z {opened} otwartych zleceń nie ma pustej {EXECUTION_DATE}"))


def _order_id_fault(page: Page, order_id: str) -> str | None:
    """Różnica pola ``ORDER_ID_FIELD`` strony zlecenia otwartej linkiem z ``id`` ``order_id``: skrypt strony wysyła jego
    wartość jako ``order_id`` Przekazania, a strażnik okna przepuszcza tylko ``id`` z linku; ``None``, gdy pole jest raz
    i ma tę wartość. Wartości nie podaje, bo to identyfikator zlecenia."""

    located = page.locator(ORDER_ID_FIELD)
    if located.count() != 1:
        return f"strony zlecenia bez jednego pola identyfikatora zlecenia {ORDER_ID_FIELD}"
    if located.get_attribute("value") != order_id:
        return f"strony zlecenia z identyfikatorem w polu {ORDER_ID_FIELD} innym niż id z linku listy ({ORDER_PAGE}?id=)"
    return None


def _shape(page: Page) -> str:
    """Postać daty wykonania i kwoty końcowej bez treści: cyfra to 9, a litera to a."""

    shapes = []
    for selector in (EXECUTION_DATE, AMOUNT):
        located = page.locator(selector)
        if located.count() != 1:
            shapes.append(f"{located.count()} × {selector}")
            continue
        text = re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "a", " ".join(located.inner_text().split())))
        shapes.append(f"{selector} „{text}”")
    return ", ".join(shapes)


def _check_elements(page: Page, part: Part, elements: Sequence[PageElement], report: Report) -> None:
    for element in elements:
        located = page.locator(element.selector)
        found = located.count()
        if not element.fits(found):
            report.differ(part, f"{element.name} ({element.selector}): {found} zamiast {'co najmniej 1' if element.many else '1'}")
        elif element.clicked and not located.first.is_visible():
            report.differ(part, f"{element.name} ({element.selector}) jest ukryty w HTML strony")


def _check_proposal_before(page: Page, report: Report) -> None:
    """Propozycja w oknie Emmetta na stronie zlecenia nic nie pokazuje, zanim skrypt strony włoży do niej odpowiedź
    ``action_fill_emmett.php``, jak w Atrapie; strona bez niej to różnica z ``ORDER_ELEMENTS``."""

    if page.evaluate(_SHOWS_ANYTHING, PROPOSAL):
        report.differ(Part.ORDER, f"propozycja w oknie Emmetta ({PROPOSAL}) coś pokazuje przed propozycją Emmetta, a w Atrapie jest pusta")


def _check_script(efenix: _Efenix, page: Page, page_url: str, part: Part, script: str, uses: Sequence[ScriptUse], report: Report) -> None:
    """Skrypt ``script``, który strona ładuje, ma nazwy każdego działania ``uses``; skryptu narzędzie nie uruchamia."""

    sources: list[str] = page.locator("script[src]").evaluate_all("(scripts) => scripts.map((script) => script.getAttribute('src'))")
    loaded = [address for address in (urljoin(page_url, source) for source in sources) if efenix.name(address) == script]
    if not loaded:
        report.differ(part, f"strona nie ładuje skryptu {script}")
        return
    if not allowed("GET", loaded[0], efenix.url):
        report.unchecked.append(
            (part, f"skrypt {script}: strona ładuje go pod adresem spoza listy dozwolonych żądań (inny schemat, #fragment albo ;parametr)")
        )
        return
    text = _text(efenix, efenix.get(loaded[0]), f"GET {script}", part, report)
    if text is None:
        return
    for use in uses:
        missing = [name for name in use.names if name not in text]
        if missing:
            report.differ(part, f"skrypt {script} bez {', '.join(f'„{name}”' for name in missing)}: {use.what}")


def _check_positions(page: Page, costs: Mapping[str, Decimal | None], report: Report) -> None:
    """Karty pozycji to pozycje Atrapy (kod, rodzaj karty), a ceny pozycji z przypisania są równe kosztom Wzorca.

    Strona z częścią pozycji Atrapy jest zgodna: zlecenia efenix bywają bez części pozycji wyceny (#819, #822). Strona
    bez żadnej pozycji z przypisania kolumn nie pozwala porównać cen, więc to porównanie zostaje niesprawdzone.
    """

    cards: list[_Card] = page.evaluate(_READ_CARDS, [PRICING_CARD, QUANTITY])
    if not cards:
        report.unchecked.append((Part.PRICING, f"strona zlecenia bez kart pozycji {PRICING_CARD}"))
    found = dict(position for card in cards if (position := _position(card)) is not None)
    report.checked["pozycje wyceny"] = len(found)
    if broken := len(cards) - len(found):
        report.differ(
            Part.PRICING,
            f"karty bez jednego pola Ilość z ceną w tekście albo jednego pola ceny wpisywanej z kodem INDEKS_NNN_NNN: {broken} z {len(cards)}",
        )
    atrapa = {f"INDEKS_{item.code}_078": item.kind == "CENA" for item in CATALOG}
    for code in sorted(found.keys() - atrapa.keys()):
        report.differ(Part.PRICING, f"{code}: jest w efenix, nie ma go w Atrapie")
    for code in sorted(found.keys() & atrapa.keys()):
        if (found[code] is None) != atrapa[code]:
            kinds = ("pole ceny wpisywanej", "pole Ilość") if found[code] is None else ("pole Ilość", "pole ceny wpisywanej")
            report.differ(Part.PRICING, f"{code}: w efenix {kinds[0]}, w Atrapie {kinds[1]}")
    compared = mapped_shown = 0
    for column, mapped in POSITION_OF_COLUMN.items():
        for code, shown in sorted(found.items()):
            if code.split("_")[1] != mapped or shown is None:
                continue
            mapped_shown += 1
            cost = costs.get(column)
            if cost is None:
                report.unchecked.append((Part.PRICING, f"{code} (kolumna {column}): koszt w wierszu {COST_ROW} Wzorca pliku zbiorczego nie jest liczbą"))
                continue
            compared += 1
            if _amount(shown) != cost:
                report.differ(Part.PRICING, f"{code} (kolumna {column}): cena w efenix inna niż koszt w wierszu {COST_ROW} Wzorca pliku zbiorczego")
    if cards and not mapped_shown:
        report.unchecked.append((Part.PRICING, "strona zlecenia bez pozycji z przypisania kolumn: ceny nie porównane z Wzorcem pliku zbiorczego"))
    report.checked["ceny porównane z Wzorcem"] = compared


def _position(card: _Card) -> tuple[str, str | None] | None:
    """Kod i cena z tekstu karty; ``None`` jako cena to karta z ceną wpisywaną, a karta w innym kształcie to ``None``."""

    match card["quantity"], card["price"], card["shown"]:
        case [code], [], [shown]:
            position: tuple[str, str | None] = (code, shown)
        case [], [code], []:
            position = (code, None)
        case _:
            return None
    return position if POSITION_CODE.fullmatch(position[0]) else None


def _amount(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def _check_signed_out(efenix: _Efenix, page: Page, report: Report) -> None:
    """Lista bez sesji przekierowuje na stronę logowania, szukanie odpowiada ostrzeżeniem o wygasłej sesji, które
    rozpoznaje Wycena w efenix, a strona logowania ma pola formularza logowania."""

    if not efenix.to_login(efenix.get(efenix.url)):
        report.differ(Part.LOGGED_OUT, f"GET {LIST_PAGE} bez sesji nie przekierowuje na {LOGIN_PAGE}")
    search = efenix.post(efenix.address(SEARCH), SEARCH_FORM)
    if search.location is not None:
        report.differ(Part.LOGGED_OUT, f"POST {SEARCH} bez sesji przekierowuje na {efenix.name(search.location)} zamiast ostrzeżenia o wygasłej sesji")
    elif not 200 <= search.status < 300:
        report.differ(Part.LOGGED_OUT, f"POST {SEARCH} bez sesji: odpowiedź {search.status}")
    elif search_warning(page, search.text) is not SearchWarning.SESSION_EXPIRED:
        report.differ(Part.LOGGED_OUT, f"POST {SEARCH} bez sesji nie odpowiada ostrzeżeniem o wygasłej sesji")
    login = efenix.get(efenix.address(LOGIN_PAGE))
    if login.location is not None or not 200 <= login.status < 300:
        report.differ(Part.LOGIN, f"GET {LOGIN_PAGE}: odpowiedź {login.status}")
        return
    _show(page, login.text)
    _check_elements(page, Part.LOGIN, LOGIN_ELEMENTS, report)


def measure_proposal(browser: Browser, efenix_url: str, report: Report, *, timeout_ms: int) -> None:
    """Pomiar propozycji Emmetta z ``--emmett``: prosi Maksa o kliknięcie Emmetta, po jego Enter czyta okno Emmetta
    w karcie strony zlecenia efenix i porównuje drzewo propozycji z drzewem z okna Emmetta Atrapy efenix."""

    report.proposal_by_hand = False
    print(ASK_EMMETT, file=sys.stderr, flush=True)
    if not sys.stdin.readline():
        report.unchecked.append((Part.PROPOSAL, NO_ENTER))
        return
    window = _efenix_window(browser.contexts[0].pages, efenix_url, report)
    if window is None:
        return
    print(CLOSE_EMMETT, file=sys.stderr, flush=True)
    if window.fault is not None:
        where = "strona z oknem Emmetta" if window.fault.selector == DIALOG else "okno Emmetta"
        report.differ(Part.PROPOSAL, f"{where} po kliknięciu Emmetta ma {window.fault.count} × {window.fault.selector} zamiast 1")
        return
    if not window.shows:
        report.unchecked.append((Part.PROPOSAL, SHOWS_NOTHING))
        return
    efenix_key, efenix_shown = _layout(window.nodes)
    atrapa_key, atrapa_shown = _layout(_atrapa_proposal(browser, timeout_ms=timeout_ms))
    report.checked["okno Emmetta"] = 1
    if efenix_key != atrapa_key:
        report.differ(Part.PROPOSAL, f"propozycja po kliknięciu Emmetta w innej budowie niż w Atrapie: w efenix {efenix_shown}, w Atrapie {atrapa_shown}")


def order_tab(url: str, efenix_url: str) -> bool:
    """Czy karta pod ``url`` to strona zlecenia efenix: ``ORDER_PAGE`` w katalogu ``efenix_url``, na jego hoście."""

    address = urlparse(url)
    return f"{address.scheme}://{address.netloc}{address.path}" == urljoin(efenix_url, ORDER_PAGE)


def _efenix_window(tabs: Sequence[Page], efenix_url: str, report: Report) -> _Window | None:
    """Okno Emmetta jedynej karty strony zlecenia efenix, w której jest widoczne; inaczej powód ``NIESPRAWDZONE``."""

    orders = [tab for tab in tabs if order_tab(tab.url, efenix_url)]
    try:
        windows = [window for tab in orders if (window := _window(tab)) is not None]
    except (PlaywrightError, _PageChanged):
        report.unchecked.append((Part.PROPOSAL, READ_FAILED))
        return None
    if len(windows) == 1:
        return windows[0]
    if not orders:
        report.unchecked.append((Part.PROPOSAL, NO_ORDER_TAB))
    elif not windows:
        report.unchecked.append(
            (
                Part.PROPOSAL,
                f"okno Emmetta nie jest otwarte w żadnej karcie strony zlecenia efenix (kart: {len(orders)}): kliknij"
                " Emmetta, poczekaj na propozycję i uruchom narzędzie jeszcze raz",
            )
        )
    else:
        report.unchecked.append(
            (Part.PROPOSAL, f"okno Emmetta jest otwarte w {len(windows)} kartach: zostaw je otwarte w jednej i uruchom narzędzie jeszcze raz")
        )
    return None


def _window(tab: Page) -> _Window | None:
    """Okno Emmetta w karcie ``tab`` po skryptach jej strony: ``None``, gdy żadne okno Emmetta nie jest widoczne, a przy
    widocznym okna i propozycje na całej stronie liczone i ocenione regułą okna Wyceny (``efenix_page.emmett_window``,
    ``emmett_window_fault``) i drzewo jedynej propozycji.

    Kilka odczytów karty jeden po drugim, więc wynik jest z jednej strony tylko wtedy, gdy karta ma po ostatnim ten sam
    dokument (``performance.timeOrigin``) co w pierwszym, który czyta go razem z widocznością okna: karta, która zmieni
    stronę w trakcie odczytu, daje błąd Playwrighta, a między odczytami ``_PageChanged``."""

    document, visible = tab.locator(DIALOG).evaluate_all(_ANY_VISIBLE)
    if not visible:
        return None
    counted = emmett_window(tab)
    fault = emmett_window_fault(counted)
    nodes: list[_Node] = [] if fault is not None else tab.locator(PROPOSAL).evaluate(_READ_TREE)
    if tab.evaluate(_DOCUMENT) != document:
        raise _PageChanged
    return _Window(fault, counted.shows, nodes)


def _atrapa_proposal(browser: Browser, *, timeout_ms: int) -> list[_Node]:
    """Drzewo propozycji w oknie Emmetta Atrapy efenix po kliknięciu Emmetta na zleceniu ``ATRAPA_PROPOSAL``, w osobnym
    kontekście Chrome bez ciasteczek; strona Atrapy wysyła żądania tylko do Atrapy."""

    with atrapa_efenix([ATRAPA_PROPOSAL]) as atrapa:
        context = browser.new_context(service_workers="block")
        try:
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(urljoin(atrapa.url, f"{ORDER_PAGE}?id={ATRAPA_PROPOSAL.order_id}"))
            page.click(EMMETT_BUTTON)
            page.locator(DIALOG).wait_for(state="visible")
            nodes: list[_Node] = page.locator(PROPOSAL).evaluate(_READ_TREE)
        finally:
            context.close()
    return nodes


def _layout(nodes: Sequence[_Node]) -> tuple[str, str]:
    """Drzewo węzłów do porównania (kolejne takie same węzły jako jeden, tekst jako ``#text``) i do wyniku (z liczbą
    kolejnych takich samych węzłów i tekstem z maską pierwszego z nich)."""

    runs: list[tuple[str, str, int]] = []
    for node in nodes:
        key, shown = _node_layout(node)
        if runs and runs[-1][0] == key:
            runs[-1] = (key, runs[-1][1], runs[-1][2] + 1)
        else:
            runs.append((key, shown, 1))
    return " ".join(key for key, _shown, _count in runs), " ".join(shown + (f"×{count}" if count > 1 else "") for _key, shown, count in runs)


def _node_layout(node: _Node) -> tuple[str, str]:
    if "text" in node:
        return "#text", f"„{node['text'][:TEXT_SHOWN]}”"
    head = node["tag"] + "".join(f".{name}" for name in node["classes"]) + (f"[{','.join(node['attributes'])}]" if node["attributes"] else "")
    if not node["nodes"]:
        return head, head
    key, shown = _layout(node["nodes"])
    return f"{head}({key})", f"{head}({shown})"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efenix-url", required=True, help=f"Adres listy zleceń efenix (…/{LIST_PAGE}).")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222", help="Adres zdalnego debugowania Chrome (domyślnie %(default)s).")
    parser.add_argument(
        "--numer",
        default="",
        help=(
            "Co wpisać w pole Numer, żeby lista pokazała zlecenia (domyślnie puste pole). Podaj numer zlecenia"
            f" „{PRICING_STATUS}” bez daty wykonania, gdy wynik mówi, że lista nie ma zleceń albo że żadne otwarte zlecenie nie ma pustej daty wykonania."
        ),
    )
    parser.add_argument(
        "--wzorzec",
        type=Path,
        default=None,
        help="Wzorzec pliku zbiorczego z kosztami pozycji w wierszu 14 (domyślnie Wzorzec z konfiguracji narzędzia, jak w Centrum).",
    )
    parser.add_argument("--limit-ms", type=int, default=TIMEOUT_MS, help="Limit czekania na odpowiedź efenix (ms).")
    parser.add_argument(
        "--emmett",
        action="store_true",
        help=(
            "Po sprawdzeniu stron poproś o kliknięcie przycisku Emmetta w Chrome, po Enter przeczytaj okno Emmetta i"
            " porównaj budowę propozycji z Atrapą efenix (krok po kroku w opisie narzędzia)."
        ),
    )
    args = parser.parse_args(argv)
    try:
        address = urlparse(args.efenix_url)
        if address.scheme not in ("http", "https") or not address.path.endswith("/" + LIST_PAGE):
            raise ToolError(f"--efenix-url to adres listy zleceń efenix kończący się na /{LIST_PAGE}")
        costs = template_costs(args.wzorzec or COLLECTIVE_TEMPLATE)
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(args.cdp)
            except PlaywrightError as error:
                raise ToolError(f"nie ma Chrome ze zdalnym debugowaniem pod --cdp {args.cdp}") from error
            if not browser.contexts:
                raise ToolError("Chrome pod --cdp nie ma okna z sesją efenix")
            # Domyślny kontekst Chrome (sesja taty), wzięty przed kontekstem narzędzia, który też trafia do ``contexts``.
            session = browser.contexts[0].request
            signed_out = playwright.request.new_context()
            try:
                with parser_page(browser, timeout_ms=args.limit_ms) as page:
                    report = check(
                        _Efenix(session, args.efenix_url, timeout_ms=args.limit_ms),
                        _Efenix(signed_out, args.efenix_url, timeout_ms=args.limit_ms),
                        page,
                        costs,
                        number=args.numer,
                    )
                if args.emmett:
                    measure_proposal(browser, args.efenix_url, report, timeout_ms=args.limit_ms)
            finally:
                signed_out.dispose()
    except ToolError as error:
        print(f"BŁĄD | {error}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()))
    return 2 if report.differences or report.unchecked else 0


if __name__ == "__main__":
    sys.exit(main())
