"""Atrapa efenix: lokalny serwer HTTP z wymyślonymi zleceniami w budowie stron efenix (ADR 0024).

Odtwarza tylko to, czego używa okno efenix narzędzia: identyfikatory pól (``#field_numer``, ``#wyniki``, ``#data_install``,
``#field_signum``, ``#field_password``), adresy odpowiedzi (``action_fill_orders.php``, ``page_order_edit.php?id=``,
``page_login.php``) i kształt komórek tabeli wyników (``Numer dokumentu<br><small>Identyfikator Fenix</small>``, status
w ``.badge``, ``Wykonawca (login)`` z datą, ``<small>województwo</small><br>Dane adresowe``). Skrypt listy to własny,
krótki kod Atrapy: Enter w polu ``Numer`` wysyła formularz do ``action_fill_orders.php`` i wkłada odpowiedź do
``#wyniki``, a po wczytaniu, gdy karta pamięta numer z poprzedniego szukania (``sessionStorage``), sama szuka go
jeszcze raz, jak efenix po powrocie ze strony zlecenia na listę. Nie ma w niej żadnego kodu, stylu ani danych z efenix.

Strona zlecenia ma wycenę ze stanem: pozycje z wymyślonymi cenami (``CATALOG``, kody ``INDEKS_NNN_078`` z przypisania
kolumn i kilka bez niego) w polach ``input.wycena-ilosc`` (dwie ``.wycena-cena``), kwotę końcową ``#cena_all2``, datę
wykonania z oknem ``#dialog_select_date`` (przycisk ``#button-calendar``, pole ``#field_data_instalacji``, które jak
kalendarz efenix nie przyjmuje pisania i po otwarciu pokazuje dzisiejszy dzień), Wycenę Emmetta (``#button_emmett``,
okno ``#dialog_emmett`` z propozycją z ``action_fill_emmett.php``, „Załaduj do zlecenia” wysyła ``action_load_emmett.php``,
który czyści wycenę i wpisuje propozycję, a skrypt przeładowuje stronę) i przyciski, których narzędzie nie może użyć:
Przekazanie do akceptacji (``#button_forward_to_accept``) i anulowanie (``#button_forward_to_cancel``) z oknem
``#dialog_forward_yes_no``, którego ``.btn-ok`` wysyła ``action_change_status.php`` i stoi na stronie przed oknem Emmetta.
Ilość zapisuje skrypt strony po wyjściu z pola (Enter też z niego wychodzi) przez ``action_save_index.php``, a odpowiedź
JSON (``result``, ``price_index``, ``price_all``) odświeża ``#cena-…`` i ``#cena_all2``; bez sesji ta odpowiedź to
``result: nok``, jak w efenix.

Atrapa ma jedną sesję, jak okno taty z zapamiętanym logowaniem: po starcie jest zalogowana, ``expire_session`` ją
kończy, a wtedy każda strona i odpowiedź przekierowuje na ``page_login.php``; wysłanie tam formularza loguje z
powrotem. ``requests`` to każde żądanie po kolei (metoda, ścieżka, parametry), więc test widzi, czego narzędzie użyło.
``answer_delay_s`` opóźnia każdą odpowiedź na szukanie, więc szukanie, które lista wysyła sama, trwa jeszcze, gdy
narzędzie szuka swojego numeru. ``changed`` psuje budowę jednej części strony tak, jak mógłby ją zmienić autor efenix (``Changed``).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
import copy
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import enum
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse

LIST_PAGE = "index.php"
SEARCH = "action_fill_orders.php"
ORDER_PAGE = "page_order_edit.php"
LOGIN_PAGE = "page_login.php"
SAVE_QUANTITY = "action_save_index.php"
FILL_EMMETT = "action_fill_emmett.php"
LOAD_EMMETT = "action_load_emmett.php"
SET_DATE = "action_set_date_of_instalation.php"
GET_DATE = "action_get_date_of_instalation.php"
CHANGE_STATUS = "action_change_status.php"
# Pole ``rodzaj`` szukania, które skrypt listy wysyła sam po wczytaniu strony.
BY_LIST = "powrot"


class Changed(enum.Enum):
    """Część strony Atrapy w innej budowie niż w efenix, który zna narzędzie."""

    STATUS_HEADER = "nagłówek Status tabeli wyników ma inną nazwę"
    ORDER_LINK = "wiersz wyników nie ma linku do strony zlecenia"
    DATE_FORMAT = "data wykonania w innym zapisie niż RRRR-MM-DD"
    EMMETT_BUTTON = "strona zlecenia nie ma przycisku Emmetta"
    POSITION_CODE = "pozycja wyceny ma inny kod"
    STALE_AMOUNT = "kwota końcowa nie odświeża się po zapisie ilości"


@dataclass(frozen=True)
class Position:
    """Pozycja wyceny Atrapy: kod ``NNN``, wymyślona cena i rodzaj pola (``ILOSC`` albo ``CENA``)."""

    code: str
    price: Decimal
    kind: str = "ILOSC"


# Kody z przypisania kolumn Wyceny w efenix i kilka bez niego; ceny są wymyślone.
CATALOG = (
    *(
        Position(code, Decimal(price))
        for code, price in [
            ("005", "11.00"), ("007", "12.00"), ("008", "13.00"), ("009", "14.00"), ("010", "15.00"), ("012", "21.00"),
            ("013", "22.00"), ("014", "23.00"), ("015", "24.00"), ("016", "3.00"), ("017", "25.00"), ("018", "26.00"),
            ("019", "4.00"), ("020", "27.00"), ("021", "28.00"), ("023", "61.00"), ("024", "62.00"), ("025", "63.00"),
            ("026", "64.00"), ("027", "41.00"), ("028", "42.00"), ("029", "31.00"),
        ]
    ),
    Position("045", Decimal("1.00"), "CENA"),
    Position("032", Decimal("1.00"), "CENA"),
)
PRICES = {position.code: position.price for position in CATALOG}
# Przeładowanie strony po załadowaniu Wyceny Emmetta (w efenix po 1 s; tu krócej, żeby testy szły szybko).
_EMMETT_RELOAD_MS = 200


def amount_of(quantities: Mapping[str, int]) -> Decimal:
    """Kwota końcowa wyceny z ilościami ``quantities`` (kod → ilość) w cenach Atrapy."""

    return sum((PRICES[code] * quantity for code, quantity in quantities.items()), Decimal("0.00"))


@dataclass
class AtrapaOrder:
    """Wymyślone zlecenie Atrapy w tym, co pokazują lista i strona zlecenia efenix.

    ``quantities``: ilości wyceny (kod → ilość różna od 0), ``emmett``: propozycja Emmetta w tym samym kształcie,
    ``emmett_loads``: ile razy załadowano do zlecenia Wycenę Emmetta.
    """

    order_id: str
    number: str
    realizator: str
    address: str
    status: str = "Do wyceny"
    execution_date: date | None = None
    executor: str = "Firma Testowa Jan Fikcyjny"
    region: str = "WOJEWODZTWO-Miasto-Gmina-Dzielnica"
    operator: str = "OPERATOR"
    quantities: dict[str, int] = field(default_factory=dict)
    emmett: dict[str, int] = field(default_factory=dict)
    emmett_loads: int = 0

    @property
    def amount(self) -> Decimal:
        return amount_of(self.quantities)


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

    def status_changes(self) -> int:
        """Ile żądań zmiany statusu (Przekazanie do akceptacji, anulowanie) dostała Atrapa."""

        with self._lock:
            return sum(request.path == CHANGE_STATUS for request in self.requests)

    def searched_by_list(self) -> list[str]:
        """Numery z każdego szukania, które lista wysłała sama po wczytaniu, po kolei."""

        with self._lock:
            return [request.params.get("numer", "") for request in self.requests if request.by_list]


@contextmanager
def atrapa_efenix(
    orders: Sequence[AtrapaOrder],
    *,
    expire_after: tuple[str, int] | None = None,
    changed: Changed | None = None,
    answer_delay_s: float = 0.0,
) -> Iterator[AtrapaEfenix]:
    """Uruchamia Atrapę na wolnym porcie ``127.0.0.1`` na czas bloku i zamyka ją razem z jej wątkiem.

    ``expire_after``: ścieżka i liczba jej żądań narzędzia (bez szukania, które lista wysyła sama), po których sesja
    wygasa, jak przy wylogowaniu w trakcie przebiegu.
    """

    atrapa = AtrapaEfenix(list(orders))
    # Koniec bloku przerywa opóźnione odpowiedzi, więc żaden wątek obsługi nie czeka dłużej niż Atrapa.
    closing = threading.Event()

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
                logged_in = atrapa.logged_in
                orders = copy.deepcopy(atrapa.orders)
            if path == LOGIN_PAGE:
                if method == "POST":
                    with atrapa._lock:
                        atrapa.logged_in = True
                    self._redirect(LIST_PAGE)
                else:
                    self._html(_login_page())
            elif not logged_in and path == SAVE_QUANTITY:
                self._json({"result": "nok", "error": "Brak sesji."})
            elif not logged_in:
                self._redirect(LOGIN_PAGE)
            elif method == "POST" and path in _CHANGES:
                with atrapa._lock:
                    found = [order for order in atrapa.orders if order.order_id == params.get(_CHANGES[path])]
                    answer = _change(path, found[0], params) if found else None
                if answer is None:
                    self._html("<p>Nie ma takiego zlecenia.</p>", HTTPStatus.NOT_FOUND)
                elif isinstance(answer, dict):
                    self._json(answer)
                else:
                    self._html(answer)
            elif path == LIST_PAGE and method == "GET":
                self._html(_list_page())
            elif path == SEARCH and method == "POST":
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

        def _html(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = text.encode("utf-8")
            # Przeglądarka zrywa połączenie szukania, na które już nie czeka (karta przeszła na inną stronę).
            with suppress(ConnectionError):
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def _json(self, answer: Mapping[str, str]) -> None:
            self._html(json.dumps(answer))

        def _redirect(self, target: str) -> None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", target)
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
        server.shutdown()
        server.server_close()
        thread.join()


# Działania na zleceniu i pole, w którym przychodzi jego identyfikator.
_CHANGES = {SAVE_QUANTITY: "order_id", FILL_EMMETT: "order_id", LOAD_EMMETT: "order_id", SET_DATE: "id", GET_DATE: "id", CHANGE_STATUS: "main_id"}


def _change(path: str, order: AtrapaOrder, params: Mapping[str, str]) -> str | dict[str, str]:
    """Odpowiedź Atrapy na działanie ``path`` na zleceniu ``order`` i zmiana jego stanu (pod blokadą Atrapy)."""

    if path == SAVE_QUANTITY:
        code = params.get("index", "").removeprefix("INDEKS_").partition("_")[0]
        if code not in PRICES or not params.get("parametr", "").isdigit():
            return {"result": "nok", "error": "Zły indeks."}
        quantity = int(params["parametr"])
        if quantity:
            order.quantities[code] = quantity
        else:
            order.quantities.pop(code, None)
        return {"result": "ok", "price_index": f"{PRICES[code] * quantity:.2f}", "price_all": f"{order.amount:.2f}"}
    if path == FILL_EMMETT:
        rows = "".join(f"<li>INDEKS_{escape(code)}_078: {quantity}</li>" for code, quantity in sorted(order.emmett.items()))
        return f"<ul>{rows}</ul>"
    if path == LOAD_EMMETT:
        order.quantities = dict(order.emmett)
        order.emmett_loads += 1
        return "ok"
    if path == SET_DATE:
        order.execution_date = date.fromisoformat(params["date"])
        return "ok"
    if path == GET_DATE:
        return "0" if order.execution_date is None else order.execution_date.isoformat()
    order.status = params.get("status", "")
    return "ok"


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


def _list_page() -> str:
    return _page(
        "Atrapa efenix",
        '<div class="container-fluid"><input type="text" id="field_numer" class="form-control">'
        '<button type="button" id="button_order_search" class="btn">Szukaj</button>'
        f'<div id="wyniki"></div></div><script>{_LIST_SCRIPT.replace("__BY_LIST__", BY_LIST)}</script>',
    )


def _results(orders: Sequence[AtrapaOrder], changed: Changed | None) -> str:
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
        f"<td>{escape(order.executor)} ({escape(order.realizator)})<small>2026-09-01</small></td>"
        f"<td><small>{escape(order.region)}</small><br>{escape(order.address)}</td>"
        f'<td><a href="{link}?id={escape(order.order_id)}" class="btn btn-sm">Otwórz</a></td></tr>'
        for order in orders
    )
    return f'<table class="table table-sm">{head}<tbody>{rows}</tbody></table>'


_ORDER_SCRIPT = """
(function () {
  const show = (id) => { document.getElementById(id).style.display = 'block'; };
  const hide = (id) => { document.getElementById(id).style.display = 'none'; };
  const post = (url, data) => fetch(url, {method: 'POST', body: new URLSearchParams(data)});
  const mainId = document.getElementById('main_id').value;
  let status = '';
  document.getElementById('button_forward_to_accept').addEventListener('click', () => { status = 'Do akceptacji'; show('dialog_forward_yes_no'); });
  document.getElementById('button_forward_to_cancel').addEventListener('click', () => { status = 'Anulowane'; show('dialog_forward_yes_no'); });
  document.querySelector('#dialog_forward_yes_no .btn-ok').addEventListener('click', () => {
    post('action_change_status.php', {main_id: mainId, status: status, komentarz: ''}).then(() => location.reload());
  });
  const calendar = document.getElementById('button-calendar');
  const dayField = document.getElementById('field_data_instalacji');
  calendar.addEventListener('click', () => { dayField.value = new Date().toISOString().slice(0, 10); show('dialog_select_date'); });
  document.querySelector('#dialog_select_date .btn-ok').addEventListener('click', () => {
    const day = dayField.value;
    post('action_set_date_of_instalation.php', {id: calendar.dataset.recordId, date: day}).then((answer) => answer.text()).then((text) => {
      if (text !== 'ok') return;
      hide('dialog_select_date');
      document.getElementById('data_install').textContent = day;
    });
  });
  const emmett = document.getElementById('button_emmett');
  if (emmett) {
    emmett.addEventListener('click', () => {
      post('action_fill_emmett.php', {order_id: emmett.getAttribute('order_id')}).then((answer) => answer.text()).then((html) => {
        document.getElementById('emmett-propozycja').innerHTML = html;
        show('dialog_emmett');
      });
    });
  }
  document.querySelector('#dialog_emmett .btn-ok').addEventListener('click', () => {
    hide('dialog_emmett');
    post('action_load_emmett.php', {order_id: mainId}).then(() => setTimeout(() => location.reload(), __RELOAD__));
  });
  document.querySelectorAll('.wycena-ilosc, .wycena-cena').forEach((field) => {
    field.addEventListener('keypress', (event) => {
      if (event.key === 'Enter') field.blur();
      else if (!/^[0-9]$/.test(event.key)) event.preventDefault();
    });
    field.addEventListener('blur', () => {
      const kind = field.classList.contains('wycena-ilosc') ? 'ILOSC' : 'CENA';
      post('action_save_index.php', {order_id: field.getAttribute('order_id'), index: field.id, rodzaj: kind, parametr: field.value || '0'})
        .then((answer) => answer.json())
        .then((saved) => {
          if (saved.result !== 'ok') return;
          document.getElementById('cena-' + field.id).textContent = saved.price_index;
          if (__REFRESH__) document.getElementById('cena_all2').textContent = saved.price_all;
        });
    });
  });
})();
"""


def _order_page(order: AtrapaOrder, changed: Changed | None) -> str:
    day = "" if order.execution_date is None else order.execution_date.isoformat()
    if changed is Changed.DATE_FORMAT and order.execution_date is not None:
        day = f"{order.execution_date:%d.%m.%Y}"
    order_id = escape(order.order_id)
    emmett = (
        ""
        if changed is Changed.EMMETT_BUTTON
        else f'<button type="button" id="button_emmett" order_id="{order_id}" title="Załaduj wycenę przygotowaną przez Emmetta.">Emmett</button>'
    )
    script = _ORDER_SCRIPT.replace("__RELOAD__", str(_EMMETT_RELOAD_MS)).replace(
        "__REFRESH__", "false" if changed is Changed.STALE_AMOUNT else "true"
    )
    return _page(
        "Atrapa efenix - zlecenie",
        f'<input type="hidden" name="main_id" id="main_id" value="{order_id}">'
        f"<div><small>Status</small> {escape(order.status)}</div>"
        f"<div><small>Realizator</small> {escape(order.realizator)}</div>"
        f'<div><small>Data wykonania</small><span id="data_install">{day}</span>'
        f'<button type="button" id="button-calendar" data-record-id="{order_id}">Kalendarz</button></div>'
        f"<div><small>Ulica - numer</small> {escape(order.address)}</div>"
        '<div class="card"><button type="button" id="button_forward_to_accept">Przekaż do akceptacji.</button>'
        '<button type="button" id="button_forward_to_cancel">Anuluj to zlecenie.</button></div>'
        f'<div class="card"><span>Wycena</span>{emmett}{"".join(_position(order, position, changed) for position in CATALOG)}'
        f'<h1><span id="cena_all2">{order.amount:.2f}</span></h1></div>'
        + _dialog("dialog_forward_yes_no", "Zmiana statusu", "", "Tak")
        + _dialog("dialog_select_date", "Wybierz datę wykonania", '<input type="text" id="field_data_instalacji" readonly>', "Potwierdź")
        + _dialog("dialog_emmett", "Emmett", '<div id="emmett-propozycja"></div>', "Załaduj do zlecenia")
        + f"<script>{script}</script>",
    )


def _position(order: AtrapaOrder, position: Position, changed: Changed | None) -> str:
    code = "129" if changed is Changed.POSITION_CODE and position.code == "029" else position.code
    field_id = f"INDEKS_{code}_078"
    if position.kind == "CENA":
        field = f'<input type="text" id="{field_id}" order_id="{escape(order.order_id)}" class="form-control form-control-sm wycena-cena" value="0.00">'
        value = Decimal("0.00")
    else:
        quantity = order.quantities.get(position.code, 0)
        field = (
            f'<input step="1" type="number" id="{field_id}" order_id="{escape(order.order_id)}" '
            f'class="form-control form-control-sm wycena-ilosc" min="0" max="999999" value="{quantity}">'
        )
        value = position.price * quantity
    return (
        '<div class="card rounded-lg kolorek"><div class="row">'
        f'<div class="col-sm-3 mt-2"><span class="text-default">Usługa testowa {position.code}</span></div>'
        f'<div class="col-sm-2 mt-2"><span class="text-secondary"><small>{field_id}</small></span></div>'
        f'<div class="col-sm-1 mt-2"><span class="text-default"><small>{position.price:.2f}</small></span></div>'
        f'<div class="col-sm-2 mt-2">{field}</div>'
        f'<div class="col-sm-2 mt-2"><small><span id="cena-{field_id}"> {value:.2f}</span></small></div></div></div>'
    )


def _dialog(dialog_id: str, title: str, body: str, ok: str) -> str:
    return (
        f'<div class="modal" id="{dialog_id}" style="display: none"><h5>{escape(title)}</h5><div class="modal-body">{body}</div>'
        f'<button type="button" class="btn btn-secondary">Zamknij</button><button type="button" class="btn btn-ok">{escape(ok)}</button></div>'
    )


def _login_page() -> str:
    return _page(
        "Atrapa efenix - logowanie",
        f'<form method="post" action="{LOGIN_PAGE}"><input type="text" id="field_signum" name="field_signum">'
        '<input type="password" id="field_password" name="field_password">'
        '<button type="submit" id="button_login">Zaloguj</button></form>',
    )
