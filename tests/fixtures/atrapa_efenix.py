"""Atrapa efenix: lokalny serwer HTTP z wymyślonymi zleceniami w budowie stron efenix (ADR 0024).

Odtwarza tylko to, co czyta okno efenix narzędzia: identyfikatory pól (``#field_numer``, ``#wyniki``, ``#data_install``,
``#field_signum``, ``#field_password``), adresy odpowiedzi (``action_fill_orders.php``, ``page_order_edit.php?id=``,
``page_login.php``) i kształt komórek tabeli wyników (``Numer dokumentu<br><small>Identyfikator Fenix</small>``, status
w ``.badge``, ``Wykonawca (login)`` z datą, ``<small>województwo</small><br>Dane adresowe``). Skrypt listy to własny,
krótki kod Atrapy: Enter w polu ``Numer`` wysyła formularz do ``action_fill_orders.php`` i wkłada odpowiedź do
``#wyniki``, a po wczytaniu, gdy karta pamięta numer z poprzedniego szukania (``sessionStorage``), sama szuka go
jeszcze raz, jak efenix po powrocie ze strony zlecenia na listę. Nie ma w niej żadnego kodu, stylu ani danych z efenix.

Atrapa ma jedną sesję, jak okno taty z zapamiętanym logowaniem: po starcie jest zalogowana, ``expire_session`` ją
kończy, a wtedy każda strona i odpowiedź przekierowuje na ``page_login.php``; wysłanie tam formularza loguje z
powrotem. ``requests`` to każde żądanie po kolei (metoda, ścieżka, parametry), więc test widzi, czego narzędzie użyło.
``answer_delay_s`` opóźnia każdą odpowiedź na szukanie, więc szukanie, które lista wysyła sama, trwa jeszcze, gdy
narzędzie szuka swojego numeru. ``changed`` psuje budowę jednej części strony tak, jak mógłby ją zmienić autor efenix (``Changed``,
a w części, której Wycena w efenix jeszcze nie czyta, ``Unread``).

Dla narzędzia zgodności (``tools/zgodnosc_efenix.py``) strona zlecenia ma też nieruchomą budowę wyceny: karty pozycji
``POSITIONS`` w kształcie kart efenix (``.card.rounded-lg.kolorek``; karta z polem ``Ilość`` ``input.wycena-ilosc`` ma cenę
jednostkową w tekście ``.col-sm-1.mt-2 > span.text-default > small``, a karta z ceną wpisywaną ma tylko pole
``input.wycena-cena``; kod pozycji to ``id`` pola), kwotę końcową, przyciski i okna Emmetta i daty wykonania oraz
przyciski Przekazania do akceptacji i anulowania, a formularz logowania wysyła ``action_login.php`` z polem
``fingerprint``. Strony same wysyłają odczyty, które wysyła efenix (``PAGE_READS``): lista po wczytaniu czyta licznik
zalogowanych i listy wyboru, a po każdym szukaniu pobiera skrypt stronicowania, a strona zlecenia po wczytaniu czyta
notatki. ``cookie_session`` wiąże sesję z ciasteczkiem ``SESSION_COOKIE``, więc karta bez niego (nowy kontekst
przeglądarki) widzi stronę logowania, a sesja karty z ciasteczkiem trwa.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
import copy
from dataclasses import dataclass, field
from datetime import date
import enum
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs, urlparse

LIST_PAGE = "index.php"
SEARCH = "action_fill_orders.php"
ORDER_PAGE = "page_order_edit.php"
LOGIN_PAGE = "page_login.php"
LOGIN_ACTION = "action_login.php"
LOGOUT = "action_logout.php"
CHANGE_STATUS = "action_change_status.php"
SESSION_COOKIE = ("PHPSESSID", "atrapa-efenix")
# Pozycje wyceny strony zlecenia w kolejności kart efenix: kod (``id`` pola karty) i cena jednostkowa z cennika efenix
# (ceny usług, nie dane klientów); ``None`` to karta z ceną wpisywaną (pole ``input.wycena-cena``) bez ceny w cenniku.
POSITIONS: dict[str, str | None] = {
    f"INDEKS_{code}_078": price
    for code, price in (
        ("005", "30.00"), ("007", "30.00"), ("008", "40.00"), ("009", "160.00"), ("029", "32.00"), ("033", "50.00"),
        ("034", "30.00"), ("035", "30.00"), ("036", "23.00"), ("037", "200.00"), ("038", "50.00"), ("039", "5.00"),
        ("041", "5.00"), ("042", "75.00"), ("044", "1.00"), ("045", None), ("046", "70.00"), ("047", "70.00"),
        ("050", "500.00"), ("051", "500.00"), ("052", "250.00"), ("053", "20.00"), ("054", "16.00"), ("010", "38.00"),
        ("032", None), ("012", "26.00"), ("013", "28.00"), ("014", "28.00"), ("015", "20.00"), ("016", "4.00"),
        ("017", "13.00"), ("018", "19.00"), ("019", "16.00"), ("020", "15.00"), ("021", "23.00"), ("022", "16.00"),
        ("023", "75.00"), ("024", "20.00"), ("025", "45.00"), ("026", "70.00"), ("027", "54.00"), ("028", "42.00"),
        ("040", "50.00"),
    )
}
FILL_NOTES = "action_fill_notes.php"
PAGINATION = "js/pagination.js"
# Odczyty, które strony efenix wysyłają same: lista po wczytaniu (licznik zalogowanych i listy wyboru województwa,
# powiatu, gminy, miasta i liczba ulic) i po każdym szukaniu (skrypt stronicowania), strona zlecenia po wczytaniu
# (notatki do ``#notatki``). Atrapa odpowiada na nie pustą treścią w kształcie odpowiedzi efenix.
_LIST_READS = {
    "action_users_online.php": '{"users": "1", "cpu": "1"}',
    "action_fill_country_order.php": "<option value='wszystkie'>wszystkie</option>",
    "action_fill_community_order.php": "<option value='wszystkie'>wszystkie</option>",
    "action_fill_city_order.php": "<option value='wszystkie'>wszystkie</option>",
    "action_streets_count_order.php": "0",
}
PAGE_READS = frozenset({*(("POST", path) for path in _LIST_READS), ("GET", PAGINATION), ("POST", FILL_NOTES)})
# Pole ``rodzaj`` szukania, które skrypt listy wysyła sam po wczytaniu strony.
BY_LIST = "powrot"
# Pole ``rodzaj`` szukania, które lista z ``Unread.SEARCH_ON_LOAD`` wysyła sama po wczytaniu, zawsze.
ON_LOAD = "start"


class Changed(enum.Enum):
    """Część strony Atrapy w innej budowie niż w efenix, który zna narzędzie."""

    STATUS_HEADER = "nagłówek Status tabeli wyników ma inną nazwę"
    ORDER_LINK = "wiersz wyników nie ma linku do strony zlecenia"
    DATE_FORMAT = "data wykonania w innym zapisie niż RRRR-MM-DD"


class Unread(enum.Enum):
    """Część strony Atrapy w innej budowie, której Wycena w efenix jeszcze nie czyta, a sprawdza narzędzie zgodności."""

    ORDER_PARTS = "strona zlecenia bez przycisku Emmetta i bez pola daty w oknie daty wykonania"
    PRICE_LIST = "jedna pozycja wyceny ma inny kod, druga inną cenę, a trzecia cenę wpisywaną zamiast pola Ilość"
    PRICE_TEXT = "ceny pozycji w tekście karty z przecinkiem (70,00), a nie z kropką"
    LOGIN_FORM = "formularz logowania bez pola fingerprint"
    PAGE_WRITE = "skrypt strony zlecenia po wczytaniu zapisuje ilość (action_save_index.php)"
    LOGIN_IN_SMALL = "login realizatora w <small>, jak w rekonesansie efenix"
    PAGE_POPUP = "skrypt strony zlecenia po wczytaniu otwiera okno ze zmianą statusu (action_change_status.php)"
    REDIRECT_TO_LOGOUT = "skrypt strony zlecenia czyta listę, a lista przekierowuje na wylogowanie (action_logout.php)"
    PAGE_SOCKET = "skrypt strony zlecenia po wczytaniu otwiera WebSocket"
    PAGE_WORKER = "worker strony zlecenia po wczytaniu zapisuje ilość (action_save_index.php)"
    SEARCH_ON_LOAD = "lista po wczytaniu sama szuka pustego numeru, a odpowiedź przychodzi, gdy narzędzie już szuka swojego"


@dataclass
class AtrapaOrder:
    """Wymyślone zlecenie Atrapy w tym, co pokazują lista i strona zlecenia efenix."""

    order_id: str
    number: str
    realizator: str
    address: str
    status: str = "Do wyceny"
    execution_date: date | None = None
    executor: str = "Firma Testowa Jan Fikcyjny"
    region: str = "WOJEWODZTWO-Miasto-Gmina-Dzielnica"
    operator: str = "OPERATOR"


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    params: Mapping[str, str]

    @property
    def by_list(self) -> bool:
        """Szukanie, które skrypt listy wysłał sam po wczytaniu strony, a nie po Enter w polu ``Numer``."""

        return self.path == SEARCH and self.params.get("rodzaj") == BY_LIST


@dataclass
class AtrapaEfenix:
    """Stan Atrapy: zlecenia, sesja i dziennik żądań; ``url`` to adres listy zleceń."""

    orders: list[AtrapaOrder]
    url: str = ""
    logged_in: bool = True
    requests: list[Request] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def expire_session(self) -> None:
        with self._lock:
            self.logged_in = False

    def state(self) -> tuple[list[AtrapaOrder], bool]:
        """Kopia zleceń i sesji do porównania stanu przed przebiegiem i po nim."""

        with self._lock:
            return copy.deepcopy(self.orders), self.logged_in

    def requested(self) -> list[tuple[str, str]]:
        with self._lock:
            return [(request.method, request.path) for request in self.requests]

    def searched(self) -> list[str]:
        """Numery z każdego szukania z pola ``Numer`` po kolei."""

        with self._lock:
            return [request.params.get("numer", "") for request in self.requests if request.path == SEARCH and not request.by_list]

    def searched_by_list(self) -> list[str]:
        """Numery z każdego szukania, które lista wysłała sama po wczytaniu, po kolei."""

        with self._lock:
            return [request.params.get("numer", "") for request in self.requests if request.by_list]


@contextmanager
def atrapa_efenix(
    orders: Sequence[AtrapaOrder],
    *,
    expire_after: tuple[str, int] | None = None,
    changed: Changed | Unread | None = None,
    answer_delay_s: float = 0.0,
    cookie_session: bool = False,
) -> Iterator[AtrapaEfenix]:
    """Uruchamia Atrapę na wolnym porcie ``127.0.0.1`` na czas bloku i zamyka ją razem z jej wątkiem.

    ``expire_after``: ścieżka i liczba jej żądań narzędzia (bez szukania, które lista wysyła sama), po których sesja
    wygasa, jak przy wylogowaniu w trakcie przebiegu.
    """

    atrapa = AtrapaEfenix(list(orders))
    # Koniec bloku przerywa opóźnione odpowiedzi, więc żaden wątek obsługi nie czeka dłużej niż Atrapa.
    closing = threading.Event()
    # Szukanie z pola ``Numer`` przyszło: lista z ``Unread.SEARCH_ON_LOAD`` dopiero wtedy odpowiada na swoje szukanie.
    field_searched = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._answer("GET", {})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8")
            self._answer("POST", {name: values[0] for name, values in parse_qs(body, keep_blank_values=True).items()})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _answer(self, method: str, form: dict[str, str]) -> None:
            url = urlparse(self.path)
            path = url.path.lstrip("/") or LIST_PAGE
            params = {name: values[0] for name, values in parse_qs(url.query).items()} | form
            with atrapa._lock:
                atrapa.requests.append(Request(method, path, params))
                if expire_after is not None and path == expire_after[0]:
                    if sum(request.path == path and not request.by_list for request in atrapa.requests) > expire_after[1]:
                        atrapa.logged_in = False
                logged_in = atrapa.logged_in and (not cookie_session or _has_session_cookie(self.headers.get("Cookie", "")))
                orders = copy.deepcopy(atrapa.orders)
            if path == LOGIN_ACTION and method == "POST":
                with atrapa._lock:
                    atrapa.logged_in = True
                self._redirect(LIST_PAGE, cookie=cookie_session)
            elif path == LOGIN_PAGE:
                self._html(_login_page(changed))
            elif not logged_in:
                self._redirect(LOGIN_PAGE)
            elif path == LOGOUT:
                with atrapa._lock:
                    atrapa.logged_in = False
                self._redirect(LOGIN_PAGE)
            elif path == CHANGE_STATUS:
                with atrapa._lock:
                    for order in atrapa.orders:
                        if order.order_id == params.get("main_id"):
                            order.status = params.get("status", "")
                self._html("ok")
            elif path == LIST_PAGE and method == "GET" and changed is Unread.REDIRECT_TO_LOGOUT and "odswiez" in params:
                self._redirect(LOGOUT)
            elif path == LIST_PAGE and method == "GET":
                self._html(_list_page(changed))
            elif (method, path) in PAGE_READS:
                self._html(_page_read(path), content_type="text/javascript" if path == PAGINATION else "text/html")
            elif path == SEARCH and method == "POST":
                if params.get("rodzaj") == ON_LOAD:
                    field_searched.wait()
                else:
                    field_searched.set()
                    closing.wait(answer_delay_s)
                number = params.get("numer", "").strip()
                self._html(_results([order for order in orders if number in order.number], changed))
            elif path == ORDER_PAGE and method == "GET":
                found = [order for order in orders if order.order_id == params.get("id")]
                if found:
                    self._html(_order_page(found[0], changed))
                else:
                    self._html("<p>Nie ma takiego zlecenia.</p>", HTTPStatus.NOT_FOUND)
            else:
                self._html("<p>Nie ma takiej strony.</p>", HTTPStatus.NOT_FOUND)

        def _html(self, text: str, status: HTTPStatus = HTTPStatus.OK, *, content_type: str = "text/html") -> None:
            body = text.encode("utf-8")
            # Przeglądarka zrywa połączenie szukania, na które już nie czeka (karta przeszła na inną stronę).
            with suppress(ConnectionError):
                self.send_response(status)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def _redirect(self, target: str, *, cookie: bool = False) -> None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", target)
            if cookie:
                self.send_header("Set-Cookie", "=".join(SESSION_COOKIE))
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="atrapa-efenix")
    thread.start()
    atrapa.url = f"http://127.0.0.1:{server.server_address[1]}/{LIST_PAGE}"
    try:
        yield atrapa
    finally:
        closing.set()
        field_searched.set()
        server.shutdown()
        server.server_close()
        thread.join()


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title></head><body>{body}</body></html>"
    )


_LIST_SCRIPT = """
(function () {
  const numer = document.getElementById('field_numer');
  function szukaj(rodzaj) {
    sessionStorage.setItem('atrapa_numer', numer.value);
    const body = new URLSearchParams({numer: numer.value, rodzaj: rodzaj, strona: '1'});
    fetch('action_fill_orders.php', {method: 'POST', body: body})
      .then((answer) => answer.text())
      .then((html) => { document.getElementById('wyniki').innerHTML = html; });
  }
  numer.addEventListener('keypress', (event) => { if (event.key === 'Enter') szukaj('szukanie'); });
  document.getElementById('button_order_search').addEventListener('click', () => szukaj('szukanie'));
  const zapamietany = sessionStorage.getItem('atrapa_numer');
  if (zapamietany !== null) {
    numer.value = zapamietany;
    szukaj('__BY_LIST__');
  }
})();
"""


def _list_page(changed: Changed | Unread | None = None) -> str:
    return _page(
        "Atrapa efenix",
        '<div class="container-fluid"><input type="text" id="field_numer" class="form-control">'
        '<button type="button" id="button_order_search" class="btn">Szukaj</button>'
        f'<div id="wyniki"></div></div><script>{_LIST_SCRIPT.replace("__BY_LIST__", BY_LIST)}</script>'
        f"<script>{_list_reads(changed)}</script>",
    )


def _list_reads(changed: Changed | Unread | None) -> str:
    """Odczyty, które lista efenix wysyła sama: po wczytaniu, a skrypt stronicowania po każdej nowej tabeli wyników."""

    reads = "".join(f"post('{path}');" for path in _LIST_READS)
    on_load = f"post('{SEARCH}', {{numer: '', rodzaj: '{ON_LOAD}', strona: '1'}}).then(show);" if changed is Unread.SEARCH_ON_LOAD else ""
    return (
        "const post = (url, data) => fetch(url, {method: 'POST', body: new URLSearchParams(data || {})});"
        "const show = (answer) => answer.text().then((html) => { document.getElementById('wyniki').innerHTML = html; });"
        f"new MutationObserver(() => fetch('{PAGINATION}')).observe(document.getElementById('wyniki'), {{childList: true}});"
        f"{reads}{on_load}"
    )


def _page_read(path: str) -> str:
    if path == FILL_NOTES:
        return "<p>Brak notatek.</p>"
    return _LIST_READS.get(path, "")


def _results(orders: Sequence[AtrapaOrder], changed: Changed | Unread | None) -> str:
    status = "Stan" if changed is Changed.STATUS_HEADER else "Status"
    head = (
        "<thead><tr><th>Numer dokumentu<br><small>Identyfikator Fenix</small></th><th>Operator/Rodzaj</th>"
        f"<th>{status}</th><th>Wykonawca (login)</th><th>Dane adresowe</th><th></th></tr></thead>"
    )
    link = "" if changed is Changed.ORDER_LINK else ORDER_PAGE
    rows = "".join(
        f'<tr><td>{escape(order.number)}<br><small>{escape(order.order_id)}</small></td>'
        f"<td>{escape(order.operator)}<br><small>FSM</small></td>"
        f'<td><span class="badge badge-default">{escape(order.status)}</span></td>'
        f"<td>{escape(order.executor)} {_login(order, changed)}<small>2026-09-01</small></td>"
        f"<td><small>{escape(order.region)}</small><br>{escape(order.address)}</td>"
        f'<td><a href="{link}?id={escape(order.order_id)}" class="btn btn-sm">Otwórz</a></td></tr>'
        for order in orders
    )
    return f'<table class="table table-sm">{head}<tbody>{rows}</tbody></table>'


def _order_page(order: AtrapaOrder, changed: Changed | Unread | None) -> str:
    day = "" if order.execution_date is None else order.execution_date.isoformat()
    if changed is Changed.DATE_FORMAT and order.execution_date is not None:
        day = f"{order.execution_date:%d.%m.%Y}"
    return _page(
        "Atrapa efenix - zlecenie",
        f'<input type="hidden" name="main_id" id="main_id" value="{escape(order.order_id)}">'
        f"<div><small>Status</small> {escape(order.status)}</div>"
        f"<div><small>Realizator</small> {escape(order.realizator)}</div>"
        f"<div><small>Data wykonania</small><span id=\"data_install\">{day}</span></div>"
        f"<div><small>Ulica - numer</small> {escape(order.address)}</div>{_order_parts(changed)}",
    )


def _login(order: AtrapaOrder, changed: Changed | Unread | None) -> str:
    login = f"({escape(order.realizator)})"
    return f'<small><small class="text-default">{login}</small></small>' if changed is Unread.LOGIN_IN_SMALL else login


def _order_parts(changed: Changed | Unread | None) -> str:
    """Nieruchoma budowa wyceny strony zlecenia, którą sprawdza narzędzie zgodności; bez stanu wyceny."""

    without_parts = changed is Unread.ORDER_PARTS
    emmett = "" if without_parts else '<button type="button" id="button_emmett" class="btn">Załaduj wycenę przygotowaną przez Emmetta</button>'
    day = "" if without_parts else '<input type="text" id="field_data_instalacji" class="form-control">'
    return (
        f'<div id="wycena">{_pricing_cards(changed)}<div>Razem <span id="cena_all2">0.00</span></div></div>{emmett}'
        '<div id="dialog_emmett" class="modal"><div id="emmett-propozycja"></div>'
        '<button type="button" class="btn btn-ok">Załaduj do zlecenia</button></div>'
        f'<div id="dialog_data_instalacji" class="modal">{day}</div>'
        '<button type="button" id="button_forward_to_accept" class="btn btn-success">Zapisz</button>'
        '<button type="button" id="button_forward_to_cancel" class="btn btn-danger">Zapisz</button>'
        '<input type="hidden" id="main_button_note_delete" value="0"><div id="notatki"></div>'
        f"<script>{_order_page_script(changed)}</script>"
    )


def _pricing_cards(changed: Changed | Unread | None) -> str:
    """Karty ``POSITIONS`` w kształcie kart efenix: pole ``Ilość`` z ceną w tekście albo samo pole ceny wpisywanej."""

    positions = dict(POSITIONS)
    if changed is Unread.PRICE_LIST:
        first, second, third = list(positions)[:3]
        positions[first.replace("_078", "_079")] = positions.pop(first)
        positions[second] = "1.00"
        positions[third] = None
    cards = []
    for code, price in positions.items():
        if price is None:
            fields = (
                f'<div class="col-sm-1 md-form mt-0 mb-0"><input step="1" type="number" id="{code}" '
                'class="form-control form-control-sm wycena-cena" min="0" value="0.00"></div>'
                '<div class="col-sm-1 md-form mt-2 mb-0">1</div>'
            )
        else:
            shown = price.replace(".", ",") if changed is Unread.PRICE_TEXT else price
            fields = (
                f'<div class="col-sm-1 mt-2"><span class="text-default"><small>{shown}</small></span></div>'
                f'<div class="col-sm-1 md-form mt-0 mb-0"><input step="1" type="number" id="{code}" '
                'class="form-control form-control-sm wycena-ilosc" min="0" max="999999" value="0"></div>'
            )
        cards.append(
            '<div class="row"><div class="col-sm-12 mb-1"><div class="card rounded-lg kolorek"><div class="card-body">'
            f'<div class="row"><div class="col-sm-2 mt-2"><small>Pozycja {code[7:10]}</small></div>'
            '<div class="col-sm-1 mt-2"><span class="text-default mr-2"><i class="fas fa-tools"></i></span></div>'
            f'<div class="col-sm-2 mt-2"><span class="text-secondary"><small>{code}</small></span></div>{fields}'
            f'<div class="col-sm-1 mt-2"><small><span id="cena-{code}">0.00</span></small></div></div></div></div></div></div>'
        )
    return "".join(cards)


def _order_page_script(changed: Changed | Unread | None) -> str:
    """Skrypt strony zlecenia po wczytaniu: odczyt notatek jak w efenix, a w wariancie ``Unread`` żądanie spoza odczytów."""

    notes = (
        f"fetch('{FILL_NOTES}', {{method: 'POST', body: new URLSearchParams({{id: document.getElementById('main_id').value, "
        "button_note_delete: document.getElementById('main_button_note_delete').value})})"
        ".then((answer) => answer.text()).then((html) => { document.getElementById('notatki').innerHTML = html; });"
    )
    other = {
        Unread.PAGE_WRITE: "fetch('action_save_index.php', {method: 'POST', body: 'ilosc=1'});",
        Unread.PAGE_POPUP: f"window.open('{CHANGE_STATUS}?main_id=' + document.getElementById('main_id').value + '&status=Anulowane');",
        Unread.REDIRECT_TO_LOGOUT: f"fetch('{LIST_PAGE}?odswiez=1');",
        Unread.PAGE_SOCKET: "new WebSocket('ws://' + location.host + '/gniazdo');",
        Unread.PAGE_WORKER: (
            "new Worker(URL.createObjectURL(new Blob([\"fetch(location.origin + '/action_save_index.php', "
            "{method: 'POST', body: 'ilosc=1'});\"], {type: 'text/javascript'})));"
        ),
    }
    return notes + (other.get(changed, "") if isinstance(changed, Unread) else "")


def _has_session_cookie(header: str) -> bool:
    return "=".join(SESSION_COOKIE) in (part.strip() for part in header.split(";"))


def _login_page(changed: Changed | Unread | None) -> str:
    fingerprint = "" if changed is Unread.LOGIN_FORM else '<input type="hidden" id="fingerprint" name="fingerprint" value="">'
    return _page(
        "Atrapa efenix - logowanie",
        f'<form method="post" action="{LOGIN_ACTION}"><input type="text" id="field_signum" name="field_signum">'
        f'<input type="password" id="field_password" name="field_password">{fingerprint}'
        '<button type="submit" id="button_login">Zaloguj</button></form>',
    )
