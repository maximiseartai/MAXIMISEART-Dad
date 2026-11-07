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
Na szukanie bez tabeli wyników efenix odpowiada samym ostrzeżeniem (``SearchWarning``, pomiar 4.11.2026, #828): „Nie
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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, TypedDict
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Locator, Page

from .efenix_pricing import ElementCount, ListedOrder, LoggedOut, LoginSign, OrderPricing, OtherShape, PagePart, Shape, UnexpectedPage

__all__ = [
    "AMOUNT",
    "EXECUTION_DATE",
    "FILL_EMMETT",
    "HEADERS",
    "LOAD_EMMETT",
    "LOGIN_PAGE",
    "NUMBER_PARAM",
    "ORDER_PAGE",
    "PRICE_ALL",
    "QUANTITY",
    "SAVE_QUANTITY",
    "SCRIPT_USES",
    "SEARCH",
    "SET_DATE",
    "SHOWS_ANYTHING",
    "Cell",
    "Element",
    "EmmettWindow",
    "PageElement",
    "PageKind",
    "ResultsTable",
    "ScriptUse",
    "SearchWarning",
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
]

LOGIN_PAGE: Final = "page_login.php"
SEARCH: Final = "action_fill_orders.php"
ORDER_PAGE: Final = "page_order_edit.php"
SET_DATE: Final = "action_set_date_of_instalation.php"
FILL_EMMETT: Final = "action_fill_emmett.php"
LOAD_EMMETT: Final = "action_load_emmett.php"
SAVE_QUANTITY: Final = "action_save_index.php"
NUMBER_PARAM: Final = "numer"
"""Pole szukania z numerem, który okno wpisało w pole ``Numer``."""
PRICE_ALL: Final = "price_all"
"""Pole odpowiedzi zapisu ilości z kwotą końcową."""
EXECUTION_DATE: Final = "#data_install"
AMOUNT: Final = "#cena_all2"
QUANTITY: Final = "input.wycena-ilosc"
HEADERS: Final = {"number": "numer dokumentu", "status": "status", "realizator": "wykonawca", "address": "dane adresowe"}
"""Początek nagłówka kolumny tabeli wyników (bez wielkości liter), z której okno czyta pole ``ListedOrder``."""

_NUMBER_FIELD: Final = "#field_numer"
_DATE_DIALOG: Final = "#dialog_select_date"
_DATE_FIELD: Final = "#field_data_instalacji"
_EMMETT_BUTTON: Final = "#button_emmett"
_EMMETT_DIALOG: Final = "#dialog_emmett"
_PROPOSAL: Final = "#emmett-propozycja"
_OK: Final = ".btn-ok"
_DISMISS: Final = '[data-dismiss="modal"]'
_LOGIN_FORM: Final = 'form[action*="action_login.php"]'
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
            const link = cell.querySelector('a[href*="page_order_edit.php?id="]');
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

# Czy wśród znalezionych elementów jest dokładnie jeden i coś pokazuje (``SHOWS_ANYTHING``); bez czekania.
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


class Element(enum.Enum):
    """Element strony efenix, którego używa okno: na której stronie (``page``), jego nazwa, selektor i liczba
    (``element``) i czy efenix ma go na każdej takiej stronie (``always_on_page``). Okno bierze selektory elementów tylko
    stąd, więc narzędzie zgodności sprawdza na efenix każdy element z ``list(Element)``, a nie ręczną listę.

    Przycisk kalendarza (``DATE_BUTTON``) okno klika tylko przy pustej dacie wykonania, a efenix pokazuje go najpewniej
    tylko wtedy, więc nie jest na każdej stronie zlecenia.
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
    ),
}
"""Nazwy, które muszą być w skryptach stron efenix, bo okno polega na ich działaniu; budowane z selektorów elementów i
adresów działań, których używa okno."""


class SearchWarning(enum.Enum):
    """Ostrzeżenie, którym efenix odpowiada na szukanie zamiast tabeli wyników: cała odpowiedź to ono samo, 200 bez
    przekierowania (pomiar na efenix 4.11.2026, #828). Wartość to tekst odpowiedzi, po którym okno je rozpoznaje."""

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
    """Okno Emmetta na stronie ``page`` teraz, bez czekania: okna i propozycje liczone lokatorem (jak ``single``, także w
    shadow DOM), potem reguła ``SHOWS_ANYTHING`` dla jedynej propozycji. Tylko czyta."""

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
    """Tabela wyników z odpowiedzi szukania: teksty nagłówków i komórki wierszy."""

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
            raise LoggedOut(PagePart.RESULTS, LoginSign.SESSION_WARNING)
        case None:
            raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.NO_TABLE))


def listed(table: ResultsTable) -> tuple[ListedOrder, ...]:
    """Zlecenia z wierszy tabeli wyników po kolei; pierwszy wiersz w innej budowie to ``UnexpectedPage`` tabeli wyników z
    pierwszą jego różnicą (kolumna nie raz, inna liczba komórek albo nie jeden link, pusty numer albo id)."""

    return tuple(_listed_order(table.headers, row) for row in table.rows)


def _listed_order(headers: Sequence[str], row: Sequence[Cell]) -> ListedOrder:
    columns = {field: _column(headers, header) for field, header in HEADERS.items()}
    links = [cell.link for cell in row if cell.link]
    if len(row) != len(headers) or len(links) != 1:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.ROW_CELLS))
    order_id = parse_qs(urlparse(links[0]).query).get("id", [""])[0]
    number = row[columns["number"]].plain
    status = row[columns["status"]]
    found = _LOGIN.findall(row[columns["realizator"]].login or "")
    if not order_id or not number:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.ROW_EMPTY))
    return ListedOrder(
        number=number,
        status=status.badge if status.badge is not None else status.plain,
        realizator=found[-1] if found else None,
        address=row[columns["address"]].plain,
        order_id=order_id,
    )


def _column(headers: Sequence[str], header: str) -> int:
    positions = [index for index, text in enumerate(headers) if text.casefold().startswith(header)]
    if len(positions) != 1:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.COLUMNS))
    return positions[0]


def read_order(page: Page) -> tuple[OrderPricing, Mapping[str, str]]:
    """Data wykonania, kwota końcowa i ilości pozycji ze strony zlecenia, którą pokazuje ``page``, oraz ``id`` pola Ilość
    każdej pozycji (kod ``NNN`` → ``id``)."""

    executed = single(page, EXECUTION_DATE, PagePart.ORDER)
    total = single(page, AMOUNT, PagePart.ORDER)
    fields: list[list[str]] = page.locator(QUANTITY).evaluate_all("(fields) => fields.map((f) => [f.id, f.value])")
    positions: dict[str, str] = {}
    quantities: dict[str, int] = {}
    for field_id, value in fields:
        found = _POSITION.fullmatch(field_id)
        if found is None:
            raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.QUANTITY_ID))
        if found[1] in positions:
            raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.POSITION_TWICE, found[1]))
        if not _QUANTITY_TEXT.fullmatch(value.strip()):
            raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, found[1]))
        positions[found[1]] = field_id
        quantities[found[1]] = int(value.strip() or 0)
    return OrderPricing(_execution_date(executed.inner_text()), amount(total.inner_text(), PagePart.ORDER), quantities), positions


def login_form(page: Page) -> bool:
    """Strona ``page`` ma formularz logowania efenix."""

    return page.locator(_LOGIN_FORM).count() > 0


def single(page: Page, selector: str, part: PagePart) -> Locator:
    """Element strony, który jest na niej dokładnie raz; inaczej efenix ma inną budowę."""

    located = page.locator(selector)
    if (count := located.count()) != 1:
        raise UnexpectedPage(part, ElementCount(selector, count))
    return located


def amount(shown: str, part: PagePart) -> Decimal:
    """Kwota z tekstu efenix (``#cena_all2`` albo ``price_all`` odpowiedzi zapisu ilości): liczba z kropką."""

    text = "".join(shown.split())
    if not _AMOUNT_TEXT.fullmatch(text):
        raise UnexpectedPage(part, OtherShape(Shape.AMOUNT_TEXT))
    return Decimal(text)


def _execution_date(shown: str) -> date | None:
    text = " ".join(shown.split())
    if not text:
        return None
    if not _DAY.fullmatch(text):
        raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT)) from error
