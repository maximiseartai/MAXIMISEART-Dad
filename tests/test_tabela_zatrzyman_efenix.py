"""Tabela decyzji Zatrzymań okna efenix (Zgłoszenia #19 i #20 z MAXIMISEART-Dad-zgloszenia): każde miejsce, które
zgłasza wyjątek okna, i przyczyna techniczna z zamkniętej listy (``efenix_window.WindowCause``), którą daje Logom
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

Wyjątek okna buduje tylko klasyfikator ``efenix_window.WindowStop.of`` z dowodu awarii, a konstruktora bez jego
dowodu nie przepuszcza mypy. Który wyjątek okna daje który dowód, sprawdza tu macierz klasyfikatora, a tabela niżej mówi,
gdzie okno zbiera który dowód. Tabela to dane, a test porównuje ją z kodem: każde wywołanie ``WindowStop.of`` w
``efenix_browser``, ``efenix_page``, ``efenix_pricing`` i ``efenix_positions`` (funkcja i tekst wywołania) ma dokładnie
jeden wiersz, a każdy wiersz ma swoje miejsce. Nowe miejsce bez wiersza albo przyczyny nie przejdzie, więc recenzent
czyta najpierw tę tabelę. Że przyczyna dochodzi do Logów Uruchomienia, pokazują przegląd odcięć w
``tests/test_wycena_efenix.py`` i testy hipotez B–E w ``tests/test_centrum_logi_uruchomienia.py``. Granica: wywołanie
klasyfikatora gdzie indziej niż w tych czterech modułach albo pod inną nazwą niż ``of`` na nazwie klasy wyjątku okna
(``WindowStop.of``, ``LoggedOut.of``) tabela pomija.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest

from rozliczenia.efenix_window import (
    BrowserFailure,
    BrowserNotStarted,
    Closed,
    EfenixUnreachable,
    ElementCount,
    Evidence,
    HttpStatus,
    ListOpenFailed,
    LoggedOut,
    LoginExpired,
    LoginSign,
    Operation,
    OtherShape,
    PagePart,
    Shape,
    StatusChangeBlocked,
    UnexpectedPage,
    WindowCause,
    WindowClosed,
    WindowStop,
)

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "efenix_browser": ROOT / "src" / "rozliczenia" / "efenix_browser.py",
    "efenix_page": ROOT / "src" / "rozliczenia" / "efenix_page.py",
    "efenix_pricing": ROOT / "src" / "rozliczenia" / "efenix_pricing.py",
    "efenix_positions": ROOT / "src" / "rozliczenia" / "efenix_positions.py",
}


class Row(NamedTuple):
    module: str
    function: str
    raised: str
    when: str
    hypothesis: str


TABLE = [
    # --- otwarcie okna i logowanie ---
    Row("efenix_browser", "_playwright", "WindowStop.of(PagePart.LIST, BrowserFailure(exception_type(error), Operation.DRIVER))",
        "sterownik Playwrighta nie wystartował (OSError pętli zdarzeń, np. WinError 10055, #975, albo brak programu "
        "sterownika)", "start sterownika Playwrighta"),
    Row("efenix_browser", "chrome", "WindowStop.of(PagePart.LIST, BrowserFailure(exception_type(error), Operation.START))",
        "Chrome nie wystartował (brak Chrome, profil trzyma inne okno)", "start przeglądarki"),
    Row("efenix_browser", "chromium", "WindowStop.of(PagePart.LIST, BrowserFailure(exception_type(error), Operation.START))",
        "Chromium Playwrighta Skryptu dla maszyn nie wystartował (brak Chromium, #976)", "start przeglądarki"),
    Row("efenix_browser", "open_list", "WindowStop.of(PagePart.LIST, ListOpenFailed(failed.failure, self._opened))",
        "goto listy zleceń: błąd Playwrighta (Operation.OPEN), przed pierwszym otwarciem efenix EfenixUnreachable, a po "
        "nim UnexpectedPage listy", "D przy starcie albo D"),
    Row("efenix_browser", "open_list", "WindowStop.of(PagePart.LIST, error_page)",
        "lista zleceń, także przy starcie, z odpowiedzią 4xx/5xx (nawigacja nie zgłasza wtedy błędu, dowód HttpStatus z "
        "_error_page), a pola Numer na niej nie ma: adres odpowiada, więc to nie EfenixUnreachable (#878)", "D"),
    Row("efenix_browser", "wait_for_login", "WindowStop.of(PagePart.LIST, Closed.DURING_LOGIN)",
        "karta zamknięta w czasie czekania na logowanie, także pytaniem o sesję, które przez nią padło", "E"),
    Row("efenix_browser", "wait_for_login",
        "WindowStop.of(PagePart.LIST, LoginExpired(failure, asked - answered, self._timeout_ms))",
        "minął LOGIN_TIMEOUT_MS: EfenixUnreachable z błędem Playwrighta (Operation.OPEN), gdy efenix nie odpowiedział na "
        "ostatnie pytanie o sesję ani na żadne przez dwa czasy okna przed nim (spis #27), a inaczej brak logowania "
        "LoggedOut(LIST, NO_LOGIN)", "D przy starcie albo E"),
    Row("efenix_browser", "_session_open", "WindowStop.of(PagePart.LIST, HttpStatus(response.status))",
        "lista zleceń, o którą okno pyta w czasie czekania na logowanie, z odpowiedzią 4xx/5xx: adres odpowiada, a tata "
        "mógł się już zalogować, więc to nie brak logowania po LOGIN_TIMEOUT_MS (#891)", "D"),
    Row("efenix_browser", "_ensure_logged_in", "WindowStop.of(part, LoginSign.PAGE)",
        "adres karty to page_login.php po otwarciu listy (LIST) albo strony zlecenia (ORDER)", "E"),
    # --- każde działanie okna ---
    Row("efenix_browser", "guarded", "WindowStop.of(part, Closed.DURING_ACTION)",
        "dowolny wyjątek działania, gdy karta jest zamknięta, także błąd nawigacji, który przyszedł przed wiadomością o "
        "zamknięciu karty (#878)", "E"),
    Row("efenix_browser", "_within", "WindowStop.of(part, failed.failure)",
        "błąd Playwrighta w działaniu przeglądarki nazwanym przez _doing: typ błędu i Operation", "D"),
    Row("efenix_browser", "_within", "WindowStop.of(part, answer.status)",
        "odpowiedź 4xx/5xx na żądanie, na które okno czeka (szukanie, zapis daty, „Załaduj do zlecenia”, zapis ilości), "
        "zanim okno ją przeczyta (#878)", "D"),
    Row("efenix_browser", "_within", "WindowStop.of(part, BrowserFailure(exception_type(error), None))",
        "błąd Playwrighta w działaniu przeglądarki bez nazwy (przegląd odcięć sprawdza, że żadne takie nie zostało)", "D"),
    # --- strona zlecenia, której okno nie przeczytało ---
    Row("efenix_browser", "_read_order", "WindowStop.of(PagePart.ORDER, error_page)",
        "otwarcie strony zlecenia albo jej przeładowanie po Wycenie Emmetta z odpowiedzią 4xx/5xx (nawigacja nie zgłasza "
        "wtedy błędu, dowód HttpStatus z _error_page), a odczyt strony się nie udał", "D"),
    Row("efenix_browser", "_read_order", "WindowStop.of(PagePart.ORDER, OtherShape(Shape.LOGIN_FORM))",
        "formularz logowania pod adresem strony zlecenia, bez przekierowania, a odczyt strony się nie udał", "E"),
    Row("efenix_page", "single", "WindowStop.of(part, ElementCount(selector, count))",
        "#data_install, #cena_all2 albo pole Ilość pozycji do wpisania nie dokładnie raz", "C"),
    Row("efenix_browser", "_element", "WindowStop.of(part, ElementCount(element.selector, count))",
        "element okna z efenix_page.Element (#field_numer, przyciski, pola i okna dialogowe) nie tyle razy, ile deklaruje "
        "jego PageElement: dokładnie raz, a przycisk zamknięcia okna dialogowego [data-dismiss=\"modal\"] co najmniej raz",
        "C"),
    Row("efenix_browser", "_still_single", "WindowStop.of(part, ElementCount(selector, count))",
        "#field_numer nie dokładnie raz po wpisaniu numeru albo Enter, które się nie udały: odpowiedź szukania listy "
        "włożyła do #wyniki stronę listy po sprawdzeniu pola (#971)", "C"),
    Row("efenix_page", "amount", "WindowStop.of(part, OtherShape(Shape.AMOUNT_TEXT))",
        "#cena_all2 (ORDER) albo price_all odpowiedzi (QUANTITY) nie jest liczbą z kropką", "C"),
    # --- szukanie i tabela wyników ---
    Row("efenix_page", "read_results", "WindowStop.of(PagePart.RESULTS, LoginSign.SESSION_WARNING)",
        "odpowiedź szukania to samo ostrzeżenie efenix o wygasłej sesji (tak efenix odpowiada bez sesji, #828)", "E"),
    Row("efenix_page", "read_results", "WindowStop.of(PagePart.RESULTS, OtherShape(Shape.NO_TABLE))",
        "odpowiedź szukania bez <table> i bez ostrzeżenia z SearchWarning", "inna budowa"),
    Row("efenix_page", "_column", "WindowStop.of(PagePart.RESULTS, OtherShape(Shape.COLUMNS))",
        "nagłówek Numer dokumentu, Status, Wykonawca albo Dane adresowe nie dokładnie raz", "inna budowa"),
    Row("efenix_page", "_listed_order", "WindowStop.of(PagePart.RESULTS, OtherShape(Shape.ROW_CELLS))",
        "wiersz z inną liczbą komórek niż nagłówków albo bez jednego linku page_order_edit.php?id=", "inna budowa"),
    Row("efenix_page", "_listed_order", "WindowStop.of(PagePart.RESULTS, OtherShape(Shape.ROW_EMPTY))",
        "wiersz bez id zlecenia w linku albo bez Numer dokumentu", "inna budowa"),
    # --- strona zlecenia ---
    Row("efenix_page", "read_order", "WindowStop.of(PagePart.ORDER, OtherShape(Shape.QUANTITY_ID))",
        "pole input.wycena-ilosc o id spoza INDEKS_NNN_…", "B"),
    Row("efenix_page", "read_order", "WindowStop.of(PagePart.ORDER, OtherShape(Shape.POSITION_TWICE, found[1]))",
        "ten sam kod pozycji w dwóch polach Ilość", "B"),
    Row("efenix_page", "read_order", "WindowStop.of(PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, found[1]))",
        "wartość pola Ilość, która nie jest liczbą całkowitą (np. 1.5)", "B"),
    Row("efenix_page", "_execution_date", "WindowStop.of(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))",
        "#data_install niepusta i nie RRRR-MM-DD", "C"),
    Row("efenix_page", "_execution_date", "WindowStop.of(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))",
        "#data_install RRRR-MM-DD, ale nie istniejący dzień (2026-02-30)", "C"),
    # --- data wykonania ---
    Row("efenix_browser", "set_execution_date", "WindowStop.of(PagePart.DATE, OtherShape(Shape.NO_CALENDAR))",
        "pole daty bez kalendarza pickadate", "inna budowa"),
    Row("efenix_browser", "set_execution_date", "WindowStop.of(PagePart.DATE, LoginSign.REDIRECT)",
        "odpowiedź zapisu daty przekierowana na page_login.php", "E"),
    # --- Wycena Emmetta: odmowa „Załaduj do zlecenia” (#877) ---
    Row("efenix_browser", "load_emmett", "WindowStop.of(PagePart.EMMETT, fault)",
        "okno Emmetta, gdy któreś jest już widoczne, nie dokładnie raz na stronie albo propozycja w nim nie dokładnie raz "
        "(ElementCount z efenix_page.emmett_window_fault, tej samej reguły, którą narzędzie zgodności mierzy efenix); "
        "zaraz po kliknięciu przycisku Emmetta okno Emmetta nie dokładnie raz to _element", "C"),
    Row("efenix_browser", "load_to_order", "WindowStop.of(PagePart.EMMETT, LoginSign.REDIRECT)",
        "odpowiedź „Załaduj do zlecenia” przekierowana na page_login.php", "E"),
    Row("efenix_browser", "load_to_order", "WindowStop.of(PagePart.EMMETT, OtherShape(Shape.ANSWER_REDIRECT))",
        "odpowiedź „Załaduj do zlecenia” przekierowana gdzie indziej niż na page_login.php", "inna budowa"),
    Row("efenix_pricing", "_emmett", "WindowStop.of(PagePart.EMMETT, OtherShape(Shape.EMMETT_NOT_LOADED))",
        "odpowiedź „Załaduj do zlecenia” 2xx, a strona po przeładowaniu nie ma żadnej ilości, choć okno Emmetta "
        "pokazało propozycję (result: nok, inna treść, #889) albo propozycja nie przyszła cała ze statusem 2xx (#908); "
        "rozstrzyga Wycena z obserwacji okna (EmmettLoad) w działaniu okna, bez treści odpowiedzi „Załaduj do zlecenia” "
        "(#895)", "inna budowa"),
    # --- pole Ilość ---
    Row("efenix_browser", "enter_quantity", "WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.UNKNOWN_POSITION, position))",
        "pozycji do wpisania nie ma wśród pól ostatnio odczytanej strony", "inna budowa"),
    Row("efenix_browser", "enter_quantity", "WindowStop.of(PagePart.QUANTITY, LoginSign.REDIRECT)",
        "odpowiedź zapisu ilości przekierowana na page_login.php", "E"),
    Row("efenix_browser", "enter_quantity", "WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.ANSWER_NOT_JSON, position))",
        "odpowiedź zapisu ilości nie jest JSON", "inna budowa"),
    Row("efenix_browser", "enter_quantity", "WindowStop.of(PagePart.QUANTITY, LoginSign.REFUSED)",
        "odpowiedź zapisu ilości result: nok (wygasła sesja)", "E"),
    Row("efenix_browser", "enter_quantity", "WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.ANSWER_RESULT, position))",
        "odpowiedź zapisu ilości z result innym niż ok i nok", "inna budowa"),
    # --- Przekazanie do akceptacji i strażnik zmiany statusu ---
    Row("efenix_browser", "accept", "WindowStop.of(PagePart.FORWARD, LoginSign.REDIRECT)",
        "odpowiedź na „Tak” Przekazania do akceptacji przekierowana na page_login.php", "E"),
    Row("efenix_browser", "_status_answer", "WindowStop.of(PagePart.FORWARD, OtherShape(Shape.STATUS_NOT_ANSWERED))",
        "żądanie Przekazania do akceptacji bez odpowiedzi w czasie okna albo z zerwanym połączeniem", "D"),
    Row("efenix_browser", "raise_blocked", "WindowStop.of(self._part, self._blocked)",
        "strażnik przerwał żądanie zmiany statusu: na inny status niż „Do akceptacji” albo poza Przekazaniem do "
        "akceptacji (także w trybie bez Przekazania), przed działaniem okna, w jego trakcie albo po ostatnim", "strażnik"),
]


# ``of`` dziedziczy każda podklasa, więc ``LoggedOut.of(…)`` też klasyfikuje, choć może dać inny wyjątek okna (#1365 r2).
# Bezpośrednie podklasy wystarczą, bo każda jest ``@final``, więc podklasę podklasy odrzuca mypy (#1378 r1).
_WINDOW_STOPS = {WindowStop.__name__, *(stop.__name__ for stop in WindowStop.__subclasses__())}


def _classified(path: Path) -> list[tuple[str, str]]:
    """Funkcja i tekst każdego wywołania klasyfikatora ``WindowStop.of`` w pliku ``path``, także przez podklasę
    (``LoggedOut.of``)."""

    found: list[tuple[str, str]] = []

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inside = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            func = child.func if isinstance(child, ast.Call) else None
            if isinstance(func, ast.Attribute) and func.attr == "of" and ast.unparse(func.value) in _WINDOW_STOPS:
                found.append((inside, ast.unparse(child)))
            walk(child, inside)

    walk(ast.parse(path.read_text(encoding="utf-8")), "<moduł>")
    return found


_OPEN = BrowserFailure("Error", Operation.OPEN)


@pytest.mark.parametrize(
    ("part", "evidence", "stop", "stop_part", "cause"),
    [
        pytest.param(PagePart.DATE, LoginSign.REDIRECT, LoggedOut, PagePart.DATE, LoginSign.REDIRECT, id="wylogowanie"),
        pytest.param(
            PagePart.ORDER, Closed.DURING_ACTION, WindowClosed, PagePart.ORDER, Closed.DURING_ACTION, id="zamkniete-okno"
        ),
        pytest.param(
            PagePart.LIST,
            BrowserFailure("Error", Operation.DRIVER),
            BrowserNotStarted,
            None,
            BrowserFailure("Error", Operation.DRIVER),
            id="sterownik-nie-wystartowal",
        ),
        pytest.param(
            PagePart.LIST,
            BrowserFailure("Error", Operation.START),
            BrowserNotStarted,
            None,
            BrowserFailure("Error", Operation.START),
            id="przegladarka-nie-wystartowala",
        ),
        pytest.param(
            PagePart.RESULTS,
            BrowserFailure("TimeoutError", Operation.ANSWER),
            UnexpectedPage,
            PagePart.RESULTS,
            BrowserFailure("TimeoutError", Operation.ANSWER),
            id="blad-przegladarki-w-dzialaniu",
        ),
        pytest.param(
            PagePart.QUANTITY,
            BrowserFailure("Error", None),
            UnexpectedPage,
            PagePart.QUANTITY,
            BrowserFailure("Error", None),
            id="blad-przegladarki-bez-nazwy",
        ),
        pytest.param(
            PagePart.ORDER,
            ElementCount("#data_install", 2),
            UnexpectedPage,
            PagePart.ORDER,
            ElementCount("#data_install", 2),
            id="element-nie-raz",
        ),
        pytest.param(PagePart.EMMETT, HttpStatus(500), UnexpectedPage, PagePart.EMMETT, HttpStatus(500), id="status-http"),
        pytest.param(
            PagePart.ORDER,
            OtherShape(Shape.DATE_TEXT),
            UnexpectedPage,
            PagePart.ORDER,
            OtherShape(Shape.DATE_TEXT),
            id="inna-budowa",
        ),
        pytest.param(
            PagePart.FORWARD,
            StatusChangeBlocked.OTHER_STATUS,
            UnexpectedPage,
            PagePart.FORWARD,
            StatusChangeBlocked.OTHER_STATUS,
            id="straznik-zmiany-statusu",
        ),
        pytest.param(
            PagePart.LIST, ListOpenFailed(_OPEN, False), EfenixUnreachable, PagePart.LIST, _OPEN, id="lista-przed-otwarciem"
        ),
        pytest.param(
            PagePart.LIST, ListOpenFailed(_OPEN, True), UnexpectedPage, PagePart.LIST, _OPEN, id="lista-po-otwarciu"
        ),
        pytest.param(
            PagePart.LIST,
            LoginExpired(_OPEN, 60.0, 30_000),
            EfenixUnreachable,
            PagePart.LIST,
            _OPEN,
            id="limit-logowania-po-dwoch-czasach-okna-ciszy",
        ),
        pytest.param(
            PagePart.LIST,
            LoginExpired(_OPEN, 59.9, 30_000),
            LoggedOut,
            PagePart.LIST,
            LoginSign.NO_LOGIN,
            id="limit-logowania-po-krotszej-ciszy",
        ),
        pytest.param(
            PagePart.LIST,
            LoginExpired(None, 900.0, 30_000),
            LoggedOut,
            PagePart.LIST,
            LoginSign.NO_LOGIN,
            id="limit-logowania-z-odpowiedzia",
        ),
    ],
)
def test_dowod_awarii_okna_efenix_daje_wyjatek_okna_z_tabeli_decyzji(
    part: PagePart, evidence: Evidence, stop: type[WindowStop], stop_part: PagePart | None, cause: WindowCause
) -> None:
    classified = WindowStop.of(part, evidence)

    assert (type(classified), classified.part, classified.cause) == (stop, stop_part, cause)


def test_kazde_miejsce_zatrzymania_okna_efenix_ma_wiersz_tabeli_decyzji_z_przyczyna_z_zamknietej_listy() -> None:
    in_code = Counter(
        (module, function, raised) for module, path in MODULES.items() for function, raised in _classified(path)
    )
    in_table = Counter((row.module, row.function, row.raised) for row in TABLE)

    assert (sorted(in_code - in_table), sorted(in_table - in_code)) == ([], [])
