"""Strona efenix tak, jak czyta ją Wycena w efenix: budowa stron, której używa okno (``efenix_browser``), i jej odczyty.

Moduł zna adresy działań efenix, elementy stron, które okno klika i czyta (``Element``), nazwy, które muszą być w
skryptach stron, bo okno polega na ich działaniu (``SCRIPT_USES``), i reguły odczytu: tabeli wyników, strony zlecenia i
okna Emmetta. Odczyty nie czekają, nie klikają i nie wysyłają: czytają stronę, która jest, i zwracają fakty albo nazwaną
różnicę budowy (``UnexpectedPage`` z przyczyną z zamkniętej listy, ``ElementCount``). Czekanie, klik i sieć zostają w
oknie. Tych samych odczytów i budowy używa narzędzie zgodności Atrapy efenix (``tools/zgodnosc_efenix.py``) na HTML z
serwera efenix, więc sprawdza budowę, którą czyta Wycena, a nie własną kopię.

Tabelę wyników okno czyta z odpowiedzi szukania parserem HTML przeglądarki w ``<template>``, w którym jej skrypty nie
biegną. Kolumny rozpoznaje po nagłówkach (``Numer dokumentu``, ``Status``, ``Wykonawca``, ``Dane adresowe``), tekst
komórki bez jej ``<small>`` (identyfikator Fenix, województwo), login realizatora z ``small.text-default`` komórki
Wykonawca (obok niego w ``<small>`` stoi data), a stronę zlecenia otwiera linkiem ``page_order_edit.php?id=`` z wiersza.
Wiersz w innej budowie okno zgłasza pierwszą jego różnicą (``listed``), a każdą różnicę tabeli z liczbą wierszy według
tych samych reguł podaje ``table_faults``, którym narzędzie zgodności tłumaczy tabelę, której Wycena nie czyta. Na szukanie bez tabeli wyników efenix odpowiada samym ostrzeżeniem (``SearchWarning``, sprawdza ``tools/zgodnosc_efenix.py``): „Nie
znaleziono pasujących wyników” to brak wyników, a ostrzeżenie o wygasłej sesji to ``LoggedOut``, bo na szukanie bez
sesji efenix nie przekierowuje.

Stronę zlecenia czyta tak, jak widzi ją tata: datę wykonania z ``#data_install`` (RRRR-MM-DD albo pusta), kwotę końcową z
``#cena_all2`` i ilość każdej pozycji z pola ``input.wycena-ilosc`` o id ``INDEKS_NNN_…`` (kod pozycji to ``NNN``).

Okno Emmetta czyta reguła ``emmett_window_fault`` na liczeniu ``emmett_window``: najpierw dokładnie jedno okno Emmetta
(``#dialog_emmett``) na całej stronie, potem dokładnie jedna propozycja (``#emmett-propozycja``) w nim. Liczy lokatorem
Playwrighta, jak element okna, który ma być na stronie dokładnie raz (``single``), więc także w shadow DOM. Propozycja
nic nie pokazuje, gdy nie ma w niej elementu ani tekstu (``SHOWS_ANYTHING``).
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, TypedDict
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Locator, Page

from .efenix_window import ElementCount, ListedOrder, LoginSign, OrderPricing, OtherShape, PagePart, Shape, WindowStop

__all__ = [
    "AMOUNT",
    "CHANGE_STATUS",
    "EXECUTION_DATE",
    "FILL_EMMETT",
    "LOAD_EMMETT",
    "LOGIN_FORM",
    "LOGIN_PAGE",
    "NUMBER_PARAM",
    "ORDER_ID_FIELD",
    "ORDER_PAGE",
    "PRICE_ALL",
    "QUANTITY",
    "SAVE_QUANTITY",
    "SCRIPT_USES",
    "SEARCH",
    "SET_DATE",
    "SHOWS_ANYTHING",
    "ORDER_PARAM",
    "STATUS_PARAM",
    "Cell",
    "ColumnFault",
    "Element",
    "EmmettWindow",
    "PageElement",
    "PageKind",
    "ResultsTable",
    "RowFault",
    "RowsFault",
    "ScriptUse",
    "SearchWarning",
    "TableFault",
    "amount",
    "emmett_window",
    "emmett_window_fault",
    "listed",
    "login_form",
    "read_order",
    "read_results",
    "results_table",
    "search_warning",
    "single",
    "table_faults",
]

LOGIN_PAGE: Final = "page_login.php"
SEARCH: Final = "action_fill_orders.php"
ORDER_PAGE: Final = "page_order_edit.php"
SET_DATE: Final = "action_set_date_of_instalation.php"
FILL_EMMETT: Final = "action_fill_emmett.php"
LOAD_EMMETT: Final = "action_load_emmett.php"
SAVE_QUANTITY: Final = "action_save_index.php"
CHANGE_STATUS: Final = "action_change_status.php"
STATUS_PARAM: Final = "xstatus"
"""Pole żądania zmiany statusu z nowym statusem zlecenia."""
ORDER_PARAM: Final = "order_id"
"""Pole żądania zmiany statusu z identyfikatorem zlecenia; strażnik okna przepuszcza tylko ``id`` z linku otwartego
zlecenia (``page_order_edit.php?id=``)."""
ORDER_ID_FIELD: Final = "#main_id"
"""Ukryte pole strony zlecenia z identyfikatorem zlecenia, który skrypt strony wysyła jako ``order_id`` w żądaniu zmiany
statusu (skrypt efenix z rekonesansu 1.11.2026). Okno go nie czyta: narzędzie zgodności sprawdza, że jest równy ``id``
z linku listy, bo inaczej strażnik okna zatrzyma Przekazanie."""
NUMBER_PARAM: Final = "numer"
"""Pole szukania z numerem, który okno wpisało w pole ``Numer``."""
PRICE_ALL: Final = "price_all"
"""Pole odpowiedzi zapisu ilości z kwotą końcową."""
EXECUTION_DATE: Final = "#data_install"
AMOUNT: Final = "#cena_all2"
QUANTITY: Final = "input.wycena-ilosc"
_HEADERS: Final = {"number": "numer dokumentu", "status": "status", "realizator": "wykonawca", "address": "dane adresowe"}
"""Początek nagłówka kolumny tabeli wyników (bez wielkości liter), z której okno czyta pole ``ListedOrder``."""

_NUMBER_FIELD: Final = "#field_numer"
_DATE_DIALOG: Final = "#dialog_select_date"
_DATE_FIELD: Final = "#field_data_instalacji"
_EMMETT_BUTTON: Final = "#button_emmett"
_EMMETT_DIALOG: Final = "#dialog_emmett"
_PROPOSAL: Final = "#emmett-propozycja"
_FORWARD_BUTTON: Final = "#button_forward_to_accept"
_FORWARD_DIALOG: Final = "#dialog_forward_yes_no"
_INFO_DIALOG: Final = "#dialog_info"
_INFO_TEXT: Final = "#dialog_info_field_info"
_OK: Final = ".btn-ok"
_DISMISS: Final = '[data-dismiss="modal"]'
LOGIN_FORM: Final = 'form[action*="action_login.php"]'
"""Formularz logowania efenix, po którym okno poznaje stronę logowania; narzędzie zgodności szuka go na efenix."""
_POSITION: Final = re.compile(r"INDEKS_(\d{3})_\d+")
_AMOUNT_TEXT: Final = re.compile(r"[0-9]+(\.[0-9]+)?")
_QUANTITY_TEXT: Final = re.compile(r"[0-9]*")
_LOGIN: Final = re.compile(r"\(([^()\s]+)\)")
_DAY: Final = re.compile(r"\d{4}-\d{2}-\d{2}")

# Tabela z odpowiedzi szukania przeczytana parserem HTML przeglądarki w ``<template>``, w którym jej skrypty nie biegną.
_READ_RESULTS: Final = """(html) => {
    const template = document.createElement('template');
    template.innerHTML = html;
    const table = template.content.querySelector('table');
    if (!table) return null;
    const text = (element) => element.textContent.replace(/\\s+/g, ' ').trim();
    return {
        headers: [...table.querySelectorAll('thead th')].map(text),
        rows: [...table.querySelectorAll('tbody tr')].map((row) => [...row.querySelectorAll('td')].map((cell) => {
            const plain = cell.cloneNode(true);
            plain.querySelectorAll('small').forEach((small) => small.remove());
            const badge = cell.querySelector('.badge');
            const login = cell.querySelector('small.text-default');
            const link = cell.querySelector(""" + json.dumps(f'a[href*="{ORDER_PAGE}?id="]') + """);
            return {
                plain: text(plain),
                badge: badge ? text(badge) : null,
                login: login ? text(login) : null,
                link: link ? link.getAttribute('href') : null,
            };
        })),
    };
}"""

# Cały tekst odpowiedzi szukania bez tabeli (białe znaki jak jedna spacja); ``null``, gdy odpowiedź ma tabelę.
_ANSWER_TEXT: Final = """(html) => {
    const template = document.createElement('template');
    template.innerHTML = html;
    return template.content.querySelector('table') ? null : template.content.textContent.replace(/\\s+/g, ' ').trim();
}"""

SHOWS_ANYTHING: Final = "(element) => element.childElementCount > 0 || element.textContent.trim() !== ''"
"""Reguła okna Wyceny, czy element pokazuje cokolwiek: ma element albo tekst, a ``false`` tylko dla pustego (same białe
znaki); funkcja JavaScript elementu. Narzędzie zgodności (``tools/zgodnosc_efenix.py``) mierzy nią propozycję Emmetta
w efenix i w Atrapie efenix (#908, #953)."""

_ONLY_ONE_SHOWS: Final = f"(found) => found.length === 1 && ({SHOWS_ANYTHING})(found[0])"


class PageKind(enum.Enum):
    """Strona efenix, na której okno używa elementu."""

    LIST = "lista zleceń"
    ORDER = "strona zlecenia"


@dataclass(frozen=True)
class PageElement:
    """Element strony efenix: jest na stronie dokładnie raz (``many``: co najmniej raz), a ten, który okno klika pierwszy
    (``clicked``), jest widoczny."""

    name: str
    selector: str
    many: bool = False
    clicked: bool = False

    def fits(self, count: int) -> bool:
        return count == 1 or (self.many and count > 1)


class Element(enum.Enum):
    """Element strony efenix, którego używa okno: na której stronie (``page``), jego nazwa, selektor i liczba
    (``element``) i czy efenix ma go na każdej takiej stronie (``always_on_page``). Okno bierze selektory elementów tylko
    stąd, więc narzędzie zgodności sprawdza na efenix każdy element z ``list(Element)``, a nie ręczną listę.

    Przycisk kalendarza (``DATE_BUTTON``) okno klika tylko przy pustej dacie wykonania, a efenix pokazuje go najpewniej
    tylko wtedy, więc nie jest na każdej stronie zlecenia. Okno zmiany statusu (``FORWARD_DIALOG``) dzieli Przekazanie do
    akceptacji z anulowaniem zlecenia, więc okno klika jego „Tak” tylko po przycisku Przekazania. Okno informacji
    (``INFO_DIALOG``) skrypt efenix pokazuje po przycisku Przekazania zamiast okna zmiany statusu, gdy odmawia
    Przekazania, z tekstem odmowy w ``INFO_TEXT``.
    """

    NUMBER = (PageKind.LIST, PageElement("pole Numer", _NUMBER_FIELD))
    DATE_BUTTON = (PageKind.ORDER, PageElement("przycisk kalendarza", "#button-calendar"), False)
    DATE_DIALOG = (PageKind.ORDER, PageElement("okno daty wykonania", _DATE_DIALOG))
    DATE_FIELD = (PageKind.ORDER, PageElement("pole kalendarza w oknie daty wykonania", f"{_DATE_DIALOG} {_DATE_FIELD}"))
    DATE_OK = (PageKind.ORDER, PageElement("„Potwierdź” w oknie daty wykonania", f"{_DATE_DIALOG} {_OK}"))
    DATE_DISMISS = (PageKind.ORDER, PageElement("zamknięcie okna daty wykonania", f"{_DATE_DIALOG} {_DISMISS}", many=True))
    EMMETT_BUTTON = (PageKind.ORDER, PageElement("przycisk Emmetta", _EMMETT_BUTTON, clicked=True))
    EMMETT_DIALOG = (PageKind.ORDER, PageElement("okno Emmetta", _EMMETT_DIALOG))
    PROPOSAL = (PageKind.ORDER, PageElement("propozycja w oknie Emmetta", f"{_EMMETT_DIALOG} {_PROPOSAL}"))
    EMMETT_LOAD = (PageKind.ORDER, PageElement("„Załaduj do zlecenia” w oknie Emmetta", f"{_EMMETT_DIALOG} {_OK}"))
    FORWARD_BUTTON = (PageKind.ORDER, PageElement("przycisk Przekazania do akceptacji", _FORWARD_BUTTON))
    FORWARD_DIALOG = (PageKind.ORDER, PageElement("okno zmiany statusu", _FORWARD_DIALOG))
    FORWARD_OK = (PageKind.ORDER, PageElement("„Tak” w oknie zmiany statusu", f"{_FORWARD_DIALOG} {_OK}"))
    INFO_DIALOG = (PageKind.ORDER, PageElement("okno informacji", _INFO_DIALOG))
    INFO_TEXT = (PageKind.ORDER, PageElement("tekst w oknie informacji", f"{_INFO_DIALOG} {_INFO_TEXT}"))
    INFO_DISMISS = (PageKind.ORDER, PageElement("zamknięcie okna informacji", f"{_INFO_DIALOG} {_DISMISS}", many=True))

    def __init__(self, page: PageKind, element: PageElement, always_on_page: bool = True) -> None:
        self.page = page
        self.element = element
        self.always_on_page = always_on_page

    @property
    def selector(self) -> str:
        return self.element.selector


@dataclass(frozen=True)
class ScriptUse:
    """Działanie skryptu strony efenix, na którym polega okno, i nazwy (pól, klas, odpowiedzi), które skrypt zawiera."""

    what: str
    names: tuple[str, ...]


def _bare(selector: str) -> str:
    """Nazwa z selektora jednego id albo jednej klasy (``#pole`` → ``pole``), tak jak stoi w skrypcie strony."""

    return selector[1:]


SCRIPT_USES: Final[Mapping[PageKind, tuple[ScriptUse, ...]]] = {
    PageKind.LIST: (
        ScriptUse("Enter w polu Numer wysyła szukanie z polem numer", (_bare(_NUMBER_FIELD), SEARCH, f"{NUMBER_PARAM}:")),
    ),
    PageKind.ORDER: (
        ScriptUse("kalendarz pickadate pola daty wykonania sprawdza dzień w onSet", (_bare(_DATE_FIELD), "pickadate", "onSet")),
        ScriptUse("„Potwierdź” okna daty wykonania zapisuje datę", (_bare(_DATE_DIALOG), _bare(_OK), SET_DATE)),
        ScriptUse(
            "przycisk Emmetta pokazuje propozycję, a „Załaduj do zlecenia” ją ładuje",
            (_bare(_EMMETT_BUTTON), FILL_EMMETT, _bare(_PROPOSAL), _bare(_EMMETT_DIALOG), LOAD_EMMETT),
        ),
        ScriptUse(
            "wyjście z pola Ilość zapisuje ilość, a kwotę końcową z odpowiedzi pokazuje na stronie",
            (QUANTITY.partition(".")[2], "blur", SAVE_QUANTITY, PRICE_ALL, _bare(AMOUNT)),
        ),
        ScriptUse(
            "„Tak” okna zmiany statusu po przycisku Przekazania wysyła nowy status i identyfikator zlecenia z pola"
            f" {ORDER_ID_FIELD} i przeładowuje stronę",
            (_bare(_FORWARD_BUTTON), _bare(_FORWARD_DIALOG), CHANGE_STATUS, STATUS_PARAM, ORDER_PARAM, _bare(ORDER_ID_FIELD), "reload"),
        ),
        ScriptUse(
            "przycisk Przekazania pokazuje odmowę efenix tekstem w oknie informacji zamiast okna zmiany statusu",
            (_bare(_FORWARD_BUTTON), _bare(_INFO_DIALOG), _bare(_INFO_TEXT)),
        ),
    ),
}
"""Nazwy, które muszą być w skryptach stron efenix, bo okno polega na ich działaniu; budowane z selektorów elementów i
adresów działań, których używa okno."""


class SearchWarning(enum.Enum):
    """Ostrzeżenie, którym efenix odpowiada na szukanie zamiast tabeli wyników: cała odpowiedź to ono samo, 200 bez
    przekierowania (sprawdza ``tools/zgodnosc_efenix.py``). Wartość to tekst odpowiedzi, po którym okno je
    rozpoznaje."""

    NOT_FOUND = "Ostrzeżenie: Nie znaleziono pasujących wyników !"
    """Szukanie nie znalazło żadnego zlecenia: efenix nie zna numeru."""
    SESSION_EXPIRED = "Ostrzeżenie: Twoja sesja wygasła - zaloguj się ponownie !"
    """Szukanie bez ważnej sesji: efenix wylogował."""


@dataclass(frozen=True)
class EmmettWindow:
    """Okno Emmetta na stronie w jednej chwili: ile okien Emmetta (``dialogs``) i propozycji w nich (``proposals``) jest na
    całej stronie i czy jedyna propozycja coś pokazuje (``shows``; ``False``, gdy propozycji nie ma dokładnie jednej)."""

    dialogs: int
    proposals: int
    shows: bool


def emmett_window(page: Page) -> EmmettWindow:
    """Okno Emmetta na stronie ``page`` teraz, bez czekania. Tylko czyta."""

    proposals = page.locator(Element.PROPOSAL.selector)
    return EmmettWindow(
        dialogs=page.locator(Element.EMMETT_DIALOG.selector).count(),
        proposals=proposals.count(),
        shows=proposals.evaluate_all(_ONLY_ONE_SHOWS) is True,
    )


def emmett_window_fault(window: EmmettWindow) -> ElementCount | None:
    """Jedyna reguła okna Emmetta: najpierw dokładnie jedno okno Emmetta na stronie, potem dokładnie jedna propozycja w
    nim; ``None``, gdy okno ma tę budowę."""

    if window.dialogs != 1:
        return ElementCount(Element.EMMETT_DIALOG.selector, window.dialogs)
    if window.proposals != 1:
        return ElementCount(Element.PROPOSAL.selector, window.proposals)
    return None


@dataclass(frozen=True)
class Cell:
    """Komórka tabeli wyników: tekst bez ``<small>`` (``plain``), tekst ``.badge``, login z ``small.text-default`` i
    adres linku do strony zlecenia; ``None``, gdy komórka go nie ma."""

    plain: str
    badge: str | None
    login: str | None
    link: str | None


@dataclass(frozen=True)
class ResultsTable:
    """Tabela wyników z odpowiedzi szukania."""

    headers: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]


class _Cell(TypedDict):
    plain: str
    badge: str | None
    login: str | None
    link: str | None


class _Results(TypedDict):
    headers: list[str]
    rows: list[list[_Cell]]


def results_table(page: Page, html: str) -> ResultsTable | SearchWarning | None:
    """Tabela wyników z odpowiedzi szukania ``html`` przeczytana parserem HTML przeglądarki strony ``page``, a bez tabeli
    ostrzeżenie efenix, którym jest cała odpowiedź (``search_warning``); ``None``: odpowiedź bez tabeli z innym tekstem."""

    results: _Results | None = page.evaluate(_READ_RESULTS, html)
    if results is None:
        return search_warning(page, html)
    return ResultsTable(
        tuple(results["headers"]),
        tuple(tuple(Cell(cell["plain"], cell["badge"], cell["login"], cell["link"]) for cell in row) for row in results["rows"]),
    )


def search_warning(page: Page, html: str) -> SearchWarning | None:
    """Ostrzeżenie efenix, którym jest cała odpowiedź szukania ``html`` bez tabeli, przeczytana parserem HTML przeglądarki
    strony ``page``; ``None``: odpowiedź z tabelą albo z innym tekstem."""

    try:
        return SearchWarning(page.evaluate(_ANSWER_TEXT, html))
    except ValueError:
        return None


def read_results(page: Page, html: str) -> tuple[ListedOrder, ...]:
    """Wiersze tabeli wyników z odpowiedzi szukania ``html``, przeczytane parserem HTML przeglądarki strony ``page``.

    Odpowiedź bez tabeli, która jest samym ostrzeżeniem efenix (``search_warning``), to brak wierszy
    (``SearchWarning.NOT_FOUND``) albo ``LoggedOut`` (``SearchWarning.SESSION_EXPIRED``), a każda inna odpowiedź bez
    tabeli to ``UnexpectedPage``.
    """

    match results_table(page, html):
        case ResultsTable() as table:
            return listed(table)
        case SearchWarning.NOT_FOUND:
            return ()
        case SearchWarning.SESSION_EXPIRED:
            raise WindowStop.of(PagePart.RESULTS, LoginSign.SESSION_WARNING)
        case None:
            raise WindowStop.of(PagePart.RESULTS, OtherShape(Shape.NO_TABLE))


class RowFault(enum.Enum):
    """Różnica wiersza tabeli wyników, przez którą okno go nie czyta, w kolejności, w której okno ją sprawdza."""

    CELLS = "inna liczba komórek niż nagłówków"
    LINK = "nie jeden link do strony zlecenia"
    EMPTY = "pusty numer albo id zlecenia"
    """Okno sprawdza ją tylko w wierszu bez innej różnicy w tabeli, w której każda kolumna jest dokładnie raz."""


@dataclass(frozen=True)
class ColumnFault:
    """Nagłówek kolumny tabeli wyników (początek, bez wielkości liter), od którego zaczyna się ``found`` nagłówków
    tabeli zamiast dokładnie jednego."""

    header: str
    found: int


@dataclass(frozen=True)
class RowsFault:
    """Różnica wiersza ``fault`` w ``rows`` wierszach tabeli wyników."""

    fault: RowFault
    rows: int


TableFault = ColumnFault | RowsFault


def listed(table: ResultsTable) -> tuple[ListedOrder, ...]:
    """Zlecenia z wierszy tabeli wyników po kolei; pierwszy wiersz w innej budowie to ``UnexpectedPage`` tabeli wyników z
    pierwszą jego różnicą: kolumna nie raz (``Shape.COLUMNS``), inna liczba komórek albo nie jeden link
    (``Shape.ROW_CELLS``), pusty numer albo id (``Shape.ROW_EMPTY``). Tabela bez wierszy nie ma różnicy."""

    return tuple(_listed_order(table.headers, row) for row in table.rows)


def table_faults(table: ResultsTable) -> tuple[TableFault, ...]:
    """Każda różnica tabeli wyników według reguł ``listed``: każdy nagłówek kolumny, który nie jest dokładnie raz, a
    potem każda różnica wiersza z liczbą wierszy, które ją mają (wiersz może mieć kilka). Krotka bez różnicy wierszy
    znaczy, że ``listed`` czyta każdy wiersz, gdy każda kolumna jest dokładnie raz."""

    found = {field: _starting(table.headers, header) for field, header in _HEADERS.items()}
    columns = {field: positions[0] for field, positions in found.items() if len(positions) == 1}
    rows = [_row_faults(table.headers, columns if len(columns) == len(found) else None, row) for row in table.rows]
    return (
        *(ColumnFault(_HEADERS[field], len(positions)) for field, positions in found.items() if len(positions) != 1),
        *(RowsFault(fault, count) for fault in RowFault if (count := sum(fault in faults for faults in rows))),
    )


def _listed_order(headers: Sequence[str], row: Sequence[Cell]) -> ListedOrder:
    columns = {field: _column(headers, header) for field, header in _HEADERS.items()}
    faults = _row_faults(headers, columns, row)
    if RowFault.CELLS in faults or RowFault.LINK in faults:
        raise WindowStop.of(PagePart.RESULTS, OtherShape(Shape.ROW_CELLS))
    if RowFault.EMPTY in faults:
        raise WindowStop.of(PagePart.RESULTS, OtherShape(Shape.ROW_EMPTY))
    status = row[columns["status"]]
    found = _LOGIN.findall(row[columns["realizator"]].login or "")
    return ListedOrder(
        number=row[columns["number"]].plain,
        status=status.badge if status.badge is not None else status.plain,
        realizator=found[-1] if found else None,
        address=row[columns["address"]].plain,
        order_id=_order_id(_links(row)[0]),
    )


def _row_faults(headers: Sequence[str], columns: Mapping[str, int] | None, row: Sequence[Cell]) -> tuple[RowFault, ...]:
    """Różnice wiersza ``row``; pusty numer albo id tylko przy kolumnach ``columns`` (``None``: kolumna nie raz) i bez
    innej różnicy."""

    links = _links(row)
    faults = [fault for fault, differs in ((RowFault.CELLS, len(row) != len(headers)), (RowFault.LINK, len(links) != 1)) if differs]
    if not faults and columns is not None and not (_order_id(links[0]) and row[columns["number"]].plain):
        faults.append(RowFault.EMPTY)
    return tuple(faults)


def _links(row: Sequence[Cell]) -> list[str]:
    return [cell.link for cell in row if cell.link]


def _order_id(link: str) -> str:
    return parse_qs(urlparse(link).query).get("id", [""])[0]


def _column(headers: Sequence[str], header: str) -> int:
    positions = _starting(headers, header)
    if len(positions) != 1:
        raise WindowStop.of(PagePart.RESULTS, OtherShape(Shape.COLUMNS))
    return positions[0]


def _starting(headers: Sequence[str], header: str) -> list[int]:
    return [index for index, text in enumerate(headers) if text.casefold().startswith(header)]


def read_order(page: Page, *, timeout_ms: float | None = None) -> tuple[OrderPricing, Mapping[str, str]]:
    """Data wykonania, kwota końcowa i ilości pozycji ze strony zlecenia, którą pokazuje ``page``, oraz ``id`` pola Ilość
    każdej pozycji (kod ``NNN`` → ``id``). Tekst daty i kwoty czeka na stronę najwyżej ``timeout_ms`` (``None``: domyślny
    limit Playwrighta karty, który narzędzie zgodności ustawia na swój czas), bo okno efenix czeka swoim czasem także w
    karcie z innym domyślnym limitem."""

    executed = single(page, EXECUTION_DATE, PagePart.ORDER)
    total = single(page, AMOUNT, PagePart.ORDER)
    fields: list[list[str]] = page.locator(QUANTITY).evaluate_all("(fields) => fields.map((f) => [f.id, f.value])")
    positions: dict[str, str] = {}
    quantities: dict[str, int] = {}
    for field_id, value in fields:
        found = _POSITION.fullmatch(field_id)
        if found is None:
            raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.QUANTITY_ID))
        if found[1] in positions:
            raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.POSITION_TWICE, found[1]))
        if not _QUANTITY_TEXT.fullmatch(value.strip()):
            raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, found[1]))
        positions[found[1]] = field_id
        quantities[found[1]] = int(value.strip() or 0)
    shown_date, shown_amount = executed.inner_text(timeout=timeout_ms), total.inner_text(timeout=timeout_ms)
    return OrderPricing(_execution_date(shown_date), amount(shown_amount, PagePart.ORDER), quantities), positions


def login_form(page: Page) -> bool:
    return page.locator(LOGIN_FORM).count() > 0


def single(page: Page, selector: str, part: PagePart) -> Locator:
    """Element strony, który jest na niej dokładnie raz; inaczej efenix ma inną budowę."""

    located = page.locator(selector)
    if (count := located.count()) != 1:
        raise WindowStop.of(part, ElementCount(selector, count))
    return located


def amount(shown: str, part: PagePart) -> Decimal:
    """Kwota z tekstu efenix (``#cena_all2`` albo ``price_all`` odpowiedzi zapisu ilości): liczba z kropką."""

    text = "".join(shown.split())
    if not _AMOUNT_TEXT.fullmatch(text):
        raise WindowStop.of(part, OtherShape(Shape.AMOUNT_TEXT))
    return Decimal(text)


def _execution_date(shown: str) -> date | None:
    text = " ".join(shown.split())
    if not text:
        return None
    if not _DAY.fullmatch(text):
        raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.DATE_TEXT)) from error
