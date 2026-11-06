"""Tabela decyzji Zatrzymań okna efenix (Zgłoszenia #19 i #20 z MAXIMISEART-Dad-zgloszenia): każde miejsce, które
zgłasza wyjątek okna, i przyczyna techniczna z zamkniętej listy (``efenix_pricing.WindowCause``), którą daje Logom
Uruchomienia.

Hipotezy ze Zgłoszeń, które przyczyna rozróżnia przy ``UnexpectedPage(PagePart.ORDER)``:
A: strona zlecenia bez pozycji z przypisania kolumn. Od #819 to nie Zatrzymanie: strona bez pozycji z ilością w pliku to
błąd zlecenia (``efenix_positions.missing_positions``), a bez pozycji z 0 w pliku to zwykła strona efenix.
B: pole Ilość z id spoza ``INDEKS_NNN_…``, kod pozycji dwa razy albo wartość, która nie jest liczbą całkowitą
(``OtherShape`` z ``Shape.QUANTITY_ID``, ``POSITION_TWICE``, ``QUANTITY_VALUE``).
C: ``#data_install`` albo ``#cena_all2`` nie dokładnie raz (``ElementCount`` z selektorem i liczbą) albo data lub
kwota w innej postaci (``Shape.DATE_TEXT``, ``Shape.AMOUNT_TEXT``).
D: błąd Playwrighta (``BrowserFailure``: typ wyjątku i działanie przeglądarki, ``Operation``, np. ``OPEN`` przy
``goto``, ``ELEMENT`` przy czekaniu na element, ``ANSWER`` przy odpowiedzi) albo strona błędu serwera efenix zamiast
strony albo odpowiedzi, na którą okno czekało (``HttpStatus`` ze statusem).
E: wylogowanie (``LoginSign``), formularz logowania pod adresem strony zlecenia bez przekierowania
(``Shape.LOGIN_FORM``) i zamknięte okno (``Closed``) mają własne przyczyny.

Tabela to dane, a test porównuje ją z kodem: każde ``raise`` wyjątku okna w ``efenix_browser``, ``efenix_pricing`` i
``efenix_positions`` (funkcja i tekst wyrażenia) ma dokładnie jeden wiersz, a każdy wiersz ma swoje miejsce. Nowe
miejsce bez wiersza albo przyczyny nie przejdzie, więc recenzent czyta najpierw tę tabelę. Że przyczyna dochodzi do Logów
Uruchomienia, pokazują przegląd odcięć w ``tests/test_wycena_efenix.py`` i testy hipotez B–E w
``tests/test_centrum_logi_uruchomienia.py``. Granica: wyjątek okna zgłoszony gdzie indziej niż w tych trzech modułach
i ``raise`` zmiennej (``raise error``) tabela pomija.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "efenix_browser": ROOT / "src" / "rozliczenia" / "efenix_browser.py",
    "efenix_pricing": ROOT / "src" / "rozliczenia" / "efenix_pricing.py",
    "efenix_positions": ROOT / "src" / "rozliczenia" / "efenix_positions.py",
}
WINDOW_ERRORS = {"UnexpectedPage", "LoggedOut", "WindowClosed", "EfenixUnreachable", "BrowserNotStarted"}


class Row(NamedTuple):
    module: str
    function: str
    raised: str
    when: str
    hypothesis: str


TABLE = [
    # --- otwarcie okna i logowanie ---
    Row("efenix_browser", "_playwright", "BrowserNotStarted(BrowserFailure(exception_type(error), Operation.DRIVER))",
        "sterownik Playwrighta nie wystartował (OSError pętli zdarzeń, np. WinError 10055, #975, albo brak programu "
        "sterownika)", "start sterownika Playwrighta"),
    Row("efenix_browser", "chrome", "BrowserNotStarted(BrowserFailure(exception_type(error), Operation.START))",
        "Chrome nie wystartował (brak Chrome, profil trzyma inne okno)", "start przeglądarki"),
    Row("efenix_browser", "open_list", "EfenixUnreachable(failed.failure)",
        "goto listy zleceń przed pierwszym otwarciem efenix: błąd Playwrighta (Operation.OPEN)", "D przy starcie"),
    Row("efenix_browser", "open_list", "UnexpectedPage(PagePart.LIST, HttpStatus(response.status))",
        "lista zleceń, także przy starcie, z odpowiedzią 4xx/5xx (nawigacja nie zgłasza wtedy błędu), a pola Numer na niej "
        "nie ma: adres odpowiada, więc to nie EfenixUnreachable (#878)", "D"),
    Row("efenix_browser", "wait_for_login", "WindowClosed(PagePart.LIST, Closed.DURING_LOGIN)",
        "karta zamknięta w czasie czekania na logowanie", "E"),
    Row("efenix_browser", "wait_for_login", "LoggedOut(PagePart.LIST, LoginSign.NO_LOGIN)",
        "tata nie zalogował się w LOGIN_TIMEOUT_MS", "E"),
    Row("efenix_browser", "_session_open", "UnexpectedPage(PagePart.LIST, HttpStatus(response.status))",
        "lista zleceń, o którą okno pyta w czasie czekania na logowanie, z odpowiedzią 4xx/5xx: adres odpowiada, a tata "
        "mógł się już zalogować, więc to nie brak logowania po LOGIN_TIMEOUT_MS (#891)", "D"),
    Row("efenix_browser", "_ensure_logged_in", "LoggedOut(part, LoginSign.PAGE)",
        "adres karty to page_login.php po otwarciu listy (LIST) albo strony zlecenia (ORDER)", "E"),
    # --- każde działanie okna ---
    Row("efenix_browser", "guarded", "WindowClosed(part, Closed.DURING_ACTION)",
        "dowolny wyjątek działania, gdy karta jest zamknięta, także błąd nawigacji, który przyszedł przed wiadomością o "
        "zamknięciu karty (#878)", "E"),
    Row("efenix_browser", "_within", "UnexpectedPage(part, failed.failure)",
        "błąd Playwrighta w działaniu przeglądarki nazwanym przez _doing: typ błędu i Operation", "D"),
    Row("efenix_browser", "_within", "UnexpectedPage(part, answer.status)",
        "odpowiedź 4xx/5xx na żądanie, na które okno czeka (szukanie, zapis daty, „Załaduj do zlecenia”, zapis ilości), "
        "zanim okno ją przeczyta (#878)", "D"),
    Row("efenix_browser", "_within", "UnexpectedPage(part, BrowserFailure(exception_type(error), None))",
        "błąd Playwrighta w działaniu przeglądarki bez nazwy (przegląd odcięć sprawdza, że żadne takie nie zostało)", "D"),
    # --- strona zlecenia, której okno nie przeczytało ---
    Row("efenix_browser", "_read_order", "UnexpectedPage(PagePart.ORDER, HttpStatus(response.status))",
        "otwarcie strony zlecenia albo jej przeładowanie po Wycenie Emmetta z odpowiedzią 4xx/5xx (nawigacja nie zgłasza "
        "wtedy błędu), a odczyt strony się nie udał", "D"),
    Row("efenix_browser", "_read_order", "UnexpectedPage(PagePart.ORDER, OtherShape(Shape.LOGIN_FORM))",
        "formularz logowania pod adresem strony zlecenia, bez przekierowania, a odczyt strony się nie udał", "E"),
    Row("efenix_browser", "_single", "UnexpectedPage(part, ElementCount(selector, count))",
        "element okna (#field_numer, #data_install, #cena_all2, przyciski i okna dialogowe) nie dokładnie raz", "C"),
    Row("efenix_browser", "_still_single", "UnexpectedPage(part, ElementCount(selector, count))",
        "#field_numer nie dokładnie raz po wpisaniu numeru albo Enter, które się nie udały: odpowiedź szukania listy "
        "włożyła do #wyniki stronę listy po sprawdzeniu pola (#971)", "C"),
    Row("efenix_browser", "_close", "UnexpectedPage(part, ElementCount(selector, count))",
        "okno dialogowe bez przycisku zamknięcia [data-dismiss=\"modal\"]", "C"),
    Row("efenix_browser", "_amount", "UnexpectedPage(part, OtherShape(Shape.AMOUNT_TEXT))",
        "#cena_all2 (ORDER) albo price_all odpowiedzi (QUANTITY) nie jest liczbą z kropką", "C"),
    # --- szukanie i tabela wyników ---
    Row("efenix_browser", "read_results", "LoggedOut(PagePart.RESULTS, LoginSign.SESSION_WARNING)",
        "odpowiedź szukania to samo ostrzeżenie efenix o wygasłej sesji (tak efenix odpowiada bez sesji, #828)", "E"),
    Row("efenix_browser", "read_results", "UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.NO_TABLE))",
        "odpowiedź szukania bez <table> i bez ostrzeżenia z SearchWarning", "inna budowa"),
    Row("efenix_browser", "_column", "UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.COLUMNS))",
        "nagłówek Numer dokumentu, Status, Wykonawca albo Dane adresowe nie dokładnie raz", "inna budowa"),
    Row("efenix_browser", "_listed", "UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.ROW_CELLS))",
        "wiersz z inną liczbą komórek niż nagłówków albo bez jednego linku page_order_edit.php?id=", "inna budowa"),
    Row("efenix_browser", "_listed", "UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.ROW_EMPTY))",
        "wiersz bez id zlecenia w linku albo bez Numer dokumentu", "inna budowa"),
    # --- strona zlecenia ---
    Row("efenix_browser", "_order_on", "UnexpectedPage(PagePart.ORDER, OtherShape(Shape.QUANTITY_ID))",
        "pole input.wycena-ilosc o id spoza INDEKS_NNN_…", "B"),
    Row("efenix_browser", "_order_on", "UnexpectedPage(PagePart.ORDER, OtherShape(Shape.POSITION_TWICE, found[1]))",
        "ten sam kod pozycji w dwóch polach Ilość", "B"),
    Row("efenix_browser", "_order_on", "UnexpectedPage(PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, found[1]))",
        "wartość pola Ilość, która nie jest liczbą całkowitą (np. 1.5)", "B"),
    Row("efenix_browser", "_execution_date", "UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))",
        "#data_install niepusta i nie RRRR-MM-DD", "C"),
    Row("efenix_browser", "_execution_date", "UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))",
        "#data_install RRRR-MM-DD, ale nie istniejący dzień (2026-02-30)", "C"),
    # --- data wykonania ---
    Row("efenix_browser", "set_execution_date", "UnexpectedPage(PagePart.DATE, OtherShape(Shape.NO_CALENDAR))",
        "pole daty bez kalendarza pickadate", "inna budowa"),
    Row("efenix_browser", "set_execution_date", "LoggedOut(PagePart.DATE, LoginSign.REDIRECT)",
        "odpowiedź zapisu daty przekierowana na page_login.php", "E"),
    # --- Wycena Emmetta: odmowa „Załaduj do zlecenia” (#877) ---
    Row("efenix_browser", "load_emmett", "LoggedOut(PagePart.EMMETT, LoginSign.REDIRECT)",
        "odpowiedź „Załaduj do zlecenia” przekierowana na page_login.php", "E"),
    Row("efenix_browser", "load_emmett", "UnexpectedPage(PagePart.EMMETT, OtherShape(Shape.ANSWER_REDIRECT))",
        "odpowiedź „Załaduj do zlecenia” przekierowana gdzie indziej niż na page_login.php", "inna budowa"),
    Row("efenix_browser", "load_emmett", "UnexpectedPage(PagePart.EMMETT, OtherShape(Shape.EMMETT_NOT_LOADED))",
        "odpowiedź „Załaduj do zlecenia” 2xx, a strona po przeładowaniu nie ma żadnej ilości, choć okno Emmetta "
        "pokazało propozycję (result: nok, inna treść, #889) albo propozycja nie przyszła cała ze statusem 2xx (#908); "
        "treści odpowiedzi „Załaduj do zlecenia” okno nie czyta (#895)", "inna budowa"),
    # --- pole Ilość ---
    Row("efenix_browser", "enter_quantity", "UnexpectedPage(PagePart.QUANTITY, OtherShape(Shape.UNKNOWN_POSITION, position))",
        "pozycji do wpisania nie ma wśród pól ostatnio odczytanej strony", "inna budowa"),
    Row("efenix_browser", "enter_quantity", "LoggedOut(PagePart.QUANTITY, LoginSign.REDIRECT)",
        "odpowiedź zapisu ilości przekierowana na page_login.php", "E"),
    Row("efenix_browser", "enter_quantity", "UnexpectedPage(PagePart.QUANTITY, OtherShape(Shape.ANSWER_NOT_JSON, position))",
        "odpowiedź zapisu ilości nie jest JSON", "inna budowa"),
    Row("efenix_browser", "enter_quantity", "LoggedOut(PagePart.QUANTITY, LoginSign.REFUSED)",
        "odpowiedź zapisu ilości result: nok (wygasła sesja)", "E"),
    Row("efenix_browser", "enter_quantity", "UnexpectedPage(PagePart.QUANTITY, OtherShape(Shape.ANSWER_RESULT, position))",
        "odpowiedź zapisu ilości z result innym niż ok i nok", "inna budowa"),
]


def _raised(path: Path) -> list[tuple[str, str]]:
    """Funkcja i tekst wyrażenia każdego ``raise`` wyjątku okna w pliku ``path``."""

    found: list[tuple[str, str]] = []

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inside = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.Raise) and child.exc is not None:
                head = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                if isinstance(head, ast.Name) and head.id in WINDOW_ERRORS:
                    found.append((inside, ast.unparse(child.exc)))
            walk(child, inside)

    walk(ast.parse(path.read_text(encoding="utf-8")), "<moduł>")
    return found


def test_kazde_miejsce_zatrzymania_okna_efenix_ma_wiersz_tabeli_decyzji_z_przyczyna_z_zamknietej_listy() -> None:
    in_code = Counter((module, function, raised) for module, path in MODULES.items() for function, raised in _raised(path))
    in_table = Counter((row.module, row.function, row.raised) for row in TABLE)

    assert (sorted(in_code - in_table), sorted(in_table - in_code)) == ([], [])
