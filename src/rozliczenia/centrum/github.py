"""Polityka HTTP Centrum wobec API GitHuba: adresy, nagłówki, połączenie, stronicowanie i pamięć odpowiedzi.

Z GitHubem rozmawiają dwa klienty Centrum: Aktualność narzędzia (``tool_freshness``, publiczne repozytorium narzędzia,
z kluczem taty, gdy jest) i Skrzynka Zgłoszeń (``report_box``, prywatne repozytorium Zgłoszeń z kluczem taty). Oba
składają żądanie z ``headers`` i wysyłają je przez ``send``, więc nowy nagłówek, wersja API albo zmiana połączenia
ląduje tutaj. Klucz w ``Authorization`` nigdy nie idzie za przekierowaniem na inny origin (schemat, host, port), a za
przekierowaniem na ten sam origin idzie tylko w kliencie, który tak mówi (``KeyAfterRedirect``): GitHub przekierowuje
przeniesione repozytorium na ``/repositories/<id>/…`` tego samego hosta, a prywatne repozytorium Zgłoszeń bez klucza
odpowiada 404, więc Skrzynka niesie klucz dalej (``"same-origin"``). Aktualność od #1097 nie niesie tokenu za żadnym
przekierowaniem (``"nowhere"``): publiczne repozytorium narzędzia odpowiada też bez niego.

Proxy z ustawień systemu klienty traktują różnie, jak przed wydzieleniem tego modułu: Aktualność łączy się wprost
(``"direct"``), a Skrzynka przez proxy systemu (``"system"``). Nic w repozytorium nie uzasadnia tej różnicy; to pytanie
do Maksa, więc każdy klient mówi swoje ``Proxy`` jawnie.

Listy GitHub daje stronami po najwyżej ``PAGE_SIZE`` wpisów, a klient czyta najwyżej ``MAX_PAGES`` stron. Aktualność
idzie za ``rel="next"`` z nagłówka ``Link`` (``next_page``); transport Skrzynki i jej nagrania w
``verify-github-skrzynki`` nagłówków nie niosą, więc Skrzynka pyta o kolejne numery stron, aż strona przyjdzie
niepełna.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from http.client import HTTPMessage
from typing import IO, Final, Literal
import urllib.error
import urllib.parse
import urllib.request

from rozliczenia.centrum.opener import opener
from rozliczenia.tool_files import REPOSITORY

API: Final = "https://api.github.com"
UPLOADS: Final = "https://uploads.github.com"
"""Osobny adres, na który idą pliki GitHub Release (dokumentacja „Upload a release asset”)."""
WEB: Final = "https://github.com"
TOOL_API: Final = f"{API}/repos/{REPOSITORY}"

PAGE_SIZE: Final = 100
MAX_PAGES: Final = 10
"""Dziesięć stron po ``PAGE_SIZE``: 1000 tagów przy Wydaniu na tydzień to lata, a jedna etykieta Skrzynki nigdy tylu issue
nie ma."""

ANSWER_KEPT_S: Final = 10 * 60
"""Tyle Centrum pamięta odpowiedź GitHuba, także „brak Wydań”: API GitHuba bez tokenu odpowiada na 60 pytań na godzinę z
jednego adresu, a bez sieci każde pytanie czeka do limitu czasu."""
NO_ANSWER_KEPT_S: Final = 60
"""Tyle Centrum pamięta brak odpowiedzi GitHuba, także odmowę z powodu limitu: krócej niż odpowiedź, bo internet może
zaraz wrócić."""

Proxy = Literal["system", "direct"]
KeyAfterRedirect = Literal["same-origin", "nowhere"]


@dataclass(frozen=True)
class HttpRequest:
    """Żądanie do GitHuba; ``headers`` nie wchodzą do ``repr``, bo niosą klucz taty."""

    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes | None


@dataclass(frozen=True)
class HttpResponse:
    """Odpowiedź GitHuba: kod, treść i nagłówki z nazwami małymi literami (puste: transport ich nie niesie)."""

    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[HttpRequest], HttpResponse]
"""Transport HTTP do GitHuba; brak sieci to ``OSError``, urwana albo nieczytelna odpowiedź ``HTTPException``. Testy
podstawiają własny, bez prawdziwego GitHuba."""


def headers(key: str | None = None) -> dict[str, str]:
    sent = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
    }
    return sent if key is None else {**sent, "Authorization": f"Bearer {key}"}


def sendable(key: str) -> bool:
    """Klucz da się wysłać w nagłówku ``Authorization``: widoczne znaki ASCII bez spacji, jak każdy token GitHuba.

    Klucza, którego nie da się wysłać, nie dostaje żaden klient: Skrzynka uznaje go za odrzucony, a pytania o Wydania
    idą bez niego (``KeyedBox.github_key``).
    """

    return key.isascii() and key.isprintable() and " " not in key


def send(
    request: HttpRequest,
    *,
    proxy: Proxy,
    key_after_redirect: KeyAfterRedirect,
    timeout_s: float,
    read_limit: int | None = None,
) -> HttpResponse:
    """Żądanie HTTPS przez bibliotekę standardową; odpowiedź z kodem błędu HTTP to też odpowiedź.

    ``read_limit`` ucina treść do tylu bajtów (ucięty JSON jest nieczytelny jak każdy inny). ``Authorization`` idzie
    jako nagłówek bez przekierowania, bo zwykły nagłówek urllib przenosi na adres przekierowania, także na inny host.
    """

    plain = {name: value for name, value in request.headers.items() if name != "Authorization"}
    sent = urllib.request.Request(request.url, data=request.body, headers=plain, method=request.method)
    if "Authorization" in request.headers:
        sent.add_unredirected_header("Authorization", request.headers["Authorization"])
    handlers: list[urllib.request.BaseHandler] = [] if proxy == "system" else [urllib.request.ProxyHandler({})]
    if key_after_redirect == "same-origin":
        handlers.append(_KeyToSameOrigin())
    try:
        with opener(*handlers).open(sent, timeout=timeout_s) as response:
            body = response.read() if read_limit is None else response.read(read_limit)
            return HttpResponse(response.status, body, _lowered(response.headers.items()))
    except urllib.error.HTTPError as error:
        with error:
            body = error.read() if read_limit is None else error.read(read_limit)
            return HttpResponse(error.code, body, _lowered(error.headers.items()))


class _KeyToSameOrigin(urllib.request.HTTPRedirectHandler):
    """Przekierowanie, które niesie klucz dalej, gdy nowy adres ma ten sam origin co adres z kluczem."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        key = req.unredirected_hdrs.get("Authorization")
        if redirected is not None and key is not None and _origin(redirected.full_url) == _origin(req.full_url):
            redirected.add_unredirected_header("Authorization", key)
        return redirected


def _origin(url: str) -> tuple[str, str | None, int | None] | None:
    """Origin adresu; ``None``, gdy portu nie da się odczytać: takiego adresu nie ma z kim porównać, a urllib nie
    połączy się z nim i zgłosi brak połączenia."""

    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError:
        return None
    return scheme, parts.hostname, port or _DEFAULT_PORTS.get(scheme)


_DEFAULT_PORTS: Final = {"http": 80, "https": 443}


def _lowered(received: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {name.lower(): value for name, value in received}


def next_page(response: HttpResponse) -> str | None:
    """Adres następnej strony listy z nagłówka ``Link`` (``rel="next"``); ``None`` na ostatniej stronie."""

    link = response.headers.get("link")
    found = None if link is None else _NEXT_PAGE.search(link)
    return None if found is None else found[1]


def rate_limit_reset(response: HttpResponse) -> datetime | None:
    """Chwila, od której limit pytań znów jest pełny, gdy GitHub odmówił z powodu wyczerpanego limitu (403 albo 429
    z ``X-RateLimit-Remaining: 0`` i chwilą ``X-RateLimit-Reset`` w sekundach od 1970 roku); ``None`` dla każdej innej
    odpowiedzi."""

    if response.status not in (403, 429) or response.headers.get("x-ratelimit-remaining") != "0":
        return None
    reset = response.headers.get("x-ratelimit-reset", "")
    if re.fullmatch(r"[0-9]{1,10}", reset) is None:
        return None
    return datetime.fromtimestamp(int(reset), timezone.utc)


_NEXT_PAGE: Final = re.compile(r'<([^>]+)>;\s*rel="next"')
