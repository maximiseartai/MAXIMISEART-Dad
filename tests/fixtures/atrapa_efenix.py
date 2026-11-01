"""Atrapa efenix: lokalny serwer HTTP z wymyślonymi zleceniami w budowie stron efenix (ADR 0024).

Odtwarza tylko to, co czyta okno efenix narzędzia: identyfikatory pól (``#field_numer``, ``#wyniki``, ``#data_install``,
``#field_signum``, ``#field_password``), adresy odpowiedzi (``action_fill_orders.php``, ``page_order_edit.php?id=``,
``page_login.php``) i kształt komórek tabeli wyników (``Numer dokumentu<br><small>Identyfikator Fenix</small>``, status
w ``.badge``, ``Wykonawca (login)`` z datą, ``<small>województwo</small><br>Dane adresowe``). Skrypt listy to własny,
krótki kod Atrapy: Enter w polu ``Numer`` wysyła formularz do ``action_fill_orders.php`` i wkłada odpowiedź do
``#wyniki``. Nie ma w niej żadnego kodu, stylu ani danych z efenix.

Atrapa ma jedną sesję, jak okno taty z zapamiętanym logowaniem: po starcie jest zalogowana, ``expire_session`` ją
kończy, a wtedy każda strona i odpowiedź przekierowuje na ``page_login.php``; wysłanie tam formularza loguje z
powrotem. ``requests`` to każde żądanie po kolei (metoda, ścieżka, parametry), więc test widzi, czego narzędzie użyło.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import copy
from dataclasses import dataclass, field
from datetime import date
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs, urlparse

LIST_PAGE = "index.php"
SEARCH = "action_fill_orders.php"
ORDER_PAGE = "page_order_edit.php"
LOGIN_PAGE = "page_login.php"


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
        """Numery z każdego szukania po kolei."""

        with self._lock:
            return [request.params.get("numer", "") for request in self.requests if request.path == SEARCH]


@contextmanager
def atrapa_efenix(orders: Sequence[AtrapaOrder], *, expire_after_searches: int | None = None) -> Iterator[AtrapaEfenix]:
    """Uruchamia Atrapę na wolnym porcie ``127.0.0.1`` na czas bloku i zamyka ją razem z jej wątkiem.

    ``expire_after_searches``: sesja wygasa po tylu szukaniach, jak przy wylogowaniu w trakcie przebiegu.
    """

    atrapa = AtrapaEfenix(list(orders))

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
                if path == SEARCH and expire_after_searches is not None:
                    searches = sum(request.path == SEARCH for request in atrapa.requests)
                    if searches > expire_after_searches:
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
            elif not logged_in:
                self._redirect(LOGIN_PAGE)
            elif path == LIST_PAGE and method == "GET":
                self._html(_list_page())
            elif path == SEARCH and method == "POST":
                number = params.get("numer", "").strip()
                self._html(_results([order for order in orders if number in order.number]))
            elif path == ORDER_PAGE and method == "GET":
                found = [order for order in orders if order.order_id == params.get("id")]
                if found:
                    self._html(_order_page(found[0]))
                else:
                    self._html("<p>Nie ma takiego zlecenia.</p>", HTTPStatus.NOT_FOUND)
            else:
                self._html("<p>Nie ma takiej strony.</p>", HTTPStatus.NOT_FOUND)

        def _html(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
  function szukaj() {
    const body = new URLSearchParams({numer: numer.value, rodzaj: 'szukanie', strona: '1'});
    fetch('action_fill_orders.php', {method: 'POST', body: body})
      .then((answer) => answer.text())
      .then((html) => { document.getElementById('wyniki').innerHTML = html; });
  }
  numer.addEventListener('keypress', (event) => { if (event.key === 'Enter') szukaj(); });
  document.getElementById('button_order_search').addEventListener('click', szukaj);
})();
"""


def _list_page() -> str:
    return _page(
        "Atrapa efenix",
        '<div class="container-fluid"><input type="text" id="field_numer" class="form-control">'
        '<button type="button" id="button_order_search" class="btn">Szukaj</button>'
        f'<div id="wyniki"></div></div><script>{_LIST_SCRIPT}</script>',
    )


def _results(orders: Sequence[AtrapaOrder]) -> str:
    head = (
        "<thead><tr><th>Numer dokumentu<br><small>Identyfikator Fenix</small></th><th>Operator/Rodzaj</th>"
        "<th>Status</th><th>Wykonawca (login)</th><th>Dane adresowe</th><th></th></tr></thead>"
    )
    rows = "".join(
        f'<tr><td>{escape(order.number)}<br><small>{escape(order.order_id)}</small></td>'
        f"<td>{escape(order.operator)}<br><small>FSM</small></td>"
        f'<td><span class="badge badge-default">{escape(order.status)}</span></td>'
        f"<td>{escape(order.executor)} ({escape(order.realizator)})<small>2026-09-01</small></td>"
        f"<td><small>{escape(order.region)}</small><br>{escape(order.address)}</td>"
        f'<td><a href="{ORDER_PAGE}?id={escape(order.order_id)}" class="btn btn-sm">Otwórz</a></td></tr>'
        for order in orders
    )
    return f'<table class="table table-sm">{head}<tbody>{rows}</tbody></table>'


def _order_page(order: AtrapaOrder) -> str:
    day = "" if order.execution_date is None else order.execution_date.isoformat()
    return _page(
        "Atrapa efenix - zlecenie",
        f'<input type="hidden" name="main_id" id="main_id" value="{escape(order.order_id)}">'
        f"<div><small>Status</small> {escape(order.status)}</div>"
        f"<div><small>Realizator</small> {escape(order.realizator)}</div>"
        f"<div><small>Data wykonania</small><span id=\"data_install\">{day}</span></div>"
        f"<div><small>Ulica - numer</small> {escape(order.address)}</div>",
    )


def _login_page() -> str:
    return _page(
        "Atrapa efenix - logowanie",
        f'<form method="post" action="{LOGIN_PAGE}"><input type="text" id="field_signum" name="field_signum">'
        '<input type="password" id="field_password" name="field_password">'
        '<button type="submit" id="button_login">Zaloguj</button></form>',
    )
