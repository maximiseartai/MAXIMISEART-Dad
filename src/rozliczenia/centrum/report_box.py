"""Skrzynka Zgłoszeń: adapter, przez który Centrum rozliczeń pisze do Maksa.

Skrzynka jest wstrzykiwana do ``create_app`` obok platformy (ADR 0007). U taty
to prywatne repozytorium Zgłoszeń na GitHubie (``GitHubReportBox``), w
``verify-centrum-rozliczen`` katalog plików, a w testach API fałszywa skrzynka.
Skrzynka nie zna Centrum ani rodzajów treści: dostaje etykietę issue
(``zgloszenie``, ``kontrola-ilosci``, ``logi-uruchomienia``, ``uwaga-taty``),
gotowy tekst i klucz taty, a zwraca wynik bez wyjątków. Klucz nie trafia do
wyniku, dziennika ani issue.

Każda operacja zwraca wynik albo jedną z dwóch porażek: ``Refused`` (skrzynka
odmówiła: klucz wygasł albo jest nieważny) albo ``Unreachable`` (brak sieci,
limit zapytań GitHuba albo skrzynka nie odpowiedziała jak zwykle). Zakładanie issue, komentarz i jego poprawka mają
trzecią: ``Rejected`` (skrzynka odmówiła tej treści). Klucz, którego nie da się wysłać
w nagłówku HTTP (np. z BOM albo znakiem spoza ASCII), to ``Refused`` bez
zapytania: taki klucz nie może być ważny. Nowe issue to ``Sent`` z numerem,
komentarz i jego poprawka (``edit_comment``) ``Commented`` z identyfikatorem i adresem, pytanie o komentarze
issue (``comments``) daje je po kolei z treścią, a pytanie o issue z
etykietą (``labelled_issues``) daje ich numery, treści i zamknięcie (powód i czas,
z których Powiadomienia biorą stan sprawy). ``newest_with_line`` wybiera z nich
najnowsze issue z wierszem rozpoznawczym: odciskiem problemu Zgłoszenia albo
tokenem okresu Kontroli ilości. Klucz taty podaje adapterowi tylko ``KeyedBox``.

Archiwum okresu (#844) to GitHub Release z tagiem w repozytorium Zgłoszeń, nie Wydanie narzędzia (inne repozytorium i
tag): ``archive`` znajduje je po tagu z jego plikami (``Asset``: nazwa, etykieta i czy plik doszedł w całości) albo
daje ``None``, ``open_archive`` zakłada je bez plików, ``upload`` wysyła plik, a ``remove`` usuwa plik, który ma ustąpić
nowszemu. Zapis treści repozytorium to inne uprawnienie klucza niż issue: jego brak to ``Refused`` z kroków Archiwum,
a repozytorium bez commitu odmawia założenia Archiwum (422 albo 409, ``Rejected``).
``archive_url`` to adres pobrania pliku z Archiwum, który zna komentarz, zanim plik dojdzie.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol, get_args


Label = Literal["zgloszenie", "kontrola-ilosci", "logi-uruchomienia", "uwaga-taty"]
"""Etykieta issue w Skrzynce Zgłoszeń; etykiety zakłada Maks w repozytorium Zgłoszeń, kod ich nie tworzy."""
# Najwięcej znaków (jak ``len``) w treści issue i komentarza. Dokumentacja REST GitHuba limitu nie podaje; pomiar na
# repozytorium Zgłoszeń 2026-10-24 (#332): nowe issue przyjmuje 65 536 znaków (także „ą” i emoji), a 65 537 odrzuca
# kodem 422; komentarz przyjmuje do 262 144 bajtów UTF-8, czyli każdy tekst do 65 536 znaków (najwyżej 4 bajty na znak).
COMMENT_LIMIT: Final = 65_536


@dataclass(frozen=True)
class Sent:
    """Skrzynka założyła issue o numerze ``number``."""

    number: int


@dataclass(frozen=True)
class Commented:
    """Skrzynka przyjęła komentarz: ``id`` z API i ``url`` do niego."""

    id: int
    url: str


@dataclass(frozen=True)
class Comment:
    """Komentarz issue w skrzynce: ``id`` z API, ``url`` do niego i treść (pusta, gdy komentarz jej nie ma)."""

    id: int
    url: str
    body: str


CloseReason = Literal["completed", "not_planned", "duplicate"]
"""Powód zamknięcia issue (``state_reason``): Maks coś zmienił (``completed``) albo nie (``not_planned``, ``duplicate``)."""


@dataclass(frozen=True)
class Closure:
    """Zamknięcie issue przez Maksa: powód (``None``, gdy GitHub go nie podał) i czas (``None``: nieczytelny)."""

    reason: CloseReason | None
    at: datetime | None


@dataclass(frozen=True)
class Issue:
    """Issue z etykietą w skrzynce: numer, treść (pusta, gdy issue jej nie ma) i zamknięcie (``None``: otwarte)."""

    number: int
    body: str
    closure: Closure | None = None


@dataclass(frozen=True)
class Refused:
    """Skrzynka odmówiła: klucz wygasł, jest nieważny albo nie ma dostępu do repozytorium Zgłoszeń."""


@dataclass(frozen=True)
class Rejected:
    """Skrzynka odmówiła tej treści (np. 422 GitHuba: treść za długa); klucz i sieć działają, inna treść przejdzie."""


@dataclass(frozen=True)
class Unreachable:
    """Skrzynka nie odpowiedziała jak zwykle: brak sieci, przekroczony czas, limit zapytań albo awaria GitHuba."""


@dataclass(frozen=True)
class Asset:
    """Plik w Archiwum okresu: ``id`` z API, nazwa, etykieta (pusta, gdy pliku jej nie dano) i czy doszedł w całości.

    ``uploaded`` ``False``: wysyłka pliku urwała się w trakcie, a GitHub trzyma go niepełnego pod tą nazwą.
    """

    id: int
    name: str
    label: str
    uploaded: bool


@dataclass(frozen=True)
class Archive:
    """Archiwum okresu (GitHub Release z tagiem) w Skrzynce: ``id`` z API i jego pliki."""

    id: int
    assets: tuple[Asset, ...]


@dataclass(frozen=True)
class Removed:
    """Skrzynka usunęła plik z Archiwum."""


SendOutcome = Sent | Refused | Rejected | Unreachable
CommentOutcome = Commented | Refused | Rejected | Unreachable
IssuesOutcome = tuple[Issue, ...] | Refused | Unreachable
CommentsOutcome = tuple[Comment, ...] | Refused | Unreachable
# Numer znalezionego issue albo ``None``, gdy issue z tym wierszem nie ma (nigdy nie było albo Maks je zamknął).
FindOutcome = int | None | Refused | Unreachable
# Archiwum z tym tagiem albo ``None``, gdy go jeszcze nie ma.
ArchiveOutcome = Archive | None | Refused | Unreachable
OpenArchiveOutcome = Archive | Refused | Rejected | Unreachable
UploadOutcome = Asset | Refused | Rejected | Unreachable
RemoveOutcome = Removed | Refused | Unreachable


class ReportBox(Protocol):
    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        """Zakłada issue z etykietą ``label`` kluczem taty; nigdy nie rzuca wyjątku sieci."""
        ...

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        """Dopisuje komentarz do issue ``number``; nigdy nie rzuca wyjątku sieci."""
        ...

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        """Otwarte issue z etykietą ``label``, z ``include_closed`` także zamknięte; nigdy nie rzuca wyjątku sieci."""
        ...

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        """Komentarze issue ``number`` w kolejności dodania; nigdy nie rzuca wyjątku sieci."""
        ...

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        """Zmienia treść komentarza ``comment_id`` na ``body``; nigdy nie rzuca wyjątku sieci."""
        ...

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        """Archiwum z tagiem ``tag`` z jego plikami albo ``None``, gdy go nie ma; nigdy nie rzuca wyjątku sieci."""
        ...

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        """Zakłada Archiwum z tagiem ``tag``, tytułem i opisem, bez plików; nigdy nie rzuca wyjątku sieci."""
        ...

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        """Wysyła plik ``name`` z etykietą ``label`` do Archiwum ``archive_id``; nigdy nie rzuca wyjątku sieci.

        Plik o tej nazwie, który już jest w Archiwum, to ``Rejected``: GitHub nie trzyma dwóch plików jednej nazwy.
        """
        ...

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        """Usuwa plik ``asset_id`` z Archiwum; nigdy nie rzuca wyjątku sieci."""
        ...


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)  # nagłówki niosą klucz taty
    body: bytes | None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


# Transport HTTP skrzynki GitHuba; brak sieci to ``OSError``, urwana albo nieczytelna odpowiedź ``HTTPException``. Testy podstawiają własny, bez prawdziwego GitHuba.
Transport = Callable[[HttpRequest], HttpResponse]

REPOSITORY: Final = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia"
_API: Final = "https://api.github.com"
# Pliki GitHub Release idą na osobny adres (dokumentacja „Upload a release asset”).
_UPLOADS: Final = "https://uploads.github.com"
_WEB: Final = "https://github.com"
_TIMEOUT_S: Final = 15.0
_REFUSALS: Final = frozenset({401, 403, 404})
# GitHub odpowiada na przekroczony limit zapytań (podstawowy i „secondary”) kodem 403 z „rate limit” w ``message``
# (429 nie jest odmową, więc i tak jest ``Unreachable``); ``HttpResponse`` nie niesie nagłówków, a treść to mówi.
_RATE_LIMIT: Final = b"rate limit"
# Odpowiedzi na treść wysyłki (zła albo za długa), nie na klucz ani sieć.
_REJECTIONS: Final = frozenset({400, 413, 422})
# Odpowiedź na założenie Release w repozytorium bez commitu, którą raz dała Skrzynka 2026-11-04 („Git Repository is
# empty.”); repozytorium próbne odpowiada 422 (``_REJECTIONS``), nagrania ``verify-github-skrzynki``.
_EMPTY_REPOSITORY: Final = 409
# Issue z etykietą przegląda się stronami po 100; dziesięć stron to więcej, niż jedna etykieta kiedykolwiek będzie miała.
_PAGE_SIZE: Final = 100
_MAX_PAGES: Final = 10
_CLOSE_REASONS: Final[Mapping[str, CloseReason]] = {reason: reason for reason in get_args(CloseReason)}


def newest_with_line(issues: tuple[Issue, ...], line: str) -> int | None:
    """Najnowsze (o najwyższym numerze) z ``issues`` z dokładnie wierszem ``line`` w treści."""

    return max((issue.number for issue in issues if line in issue.body.splitlines()), default=None)


def archive_url(tag: str, name: str) -> str:
    """Adres pobrania pliku ``name`` z Archiwum z tagiem ``tag`` (GitHub Release w repozytorium Zgłoszeń)."""

    return f"{_WEB}/{REPOSITORY}/releases/download/{urllib.parse.quote(tag)}/{urllib.parse.quote(name)}"


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Żądanie HTTPS przez bibliotekę standardową; odpowiedź z kodem błędu HTTP to też odpowiedź."""

    sent = urllib.request.Request(request.url, data=request.body, headers=dict(request.headers), method=request.method)
    try:
        with urllib.request.urlopen(sent, timeout=_TIMEOUT_S) as response:
            return HttpResponse(response.status, response.read())
    except urllib.error.HTTPError as error:
        with error:
            return HttpResponse(error.code, error.read())


class GitHubReportBox:
    """Prywatne repozytorium Zgłoszeń na GitHubie przez REST API, z kluczem taty (token fine-grained Maksa)."""

    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        if not sendable(key):
            return Refused()
        payload = {"title": title, "body": body, "labels": [label]}
        answer = self._send("POST", f"{_API}/repos/{REPOSITORY}/issues", payload, key)
        if not isinstance(answer, HttpResponse):
            return answer
        number = _json_field(answer.body, "number") if answer.status == 201 else None
        return Sent(number) if isinstance(number, int) else Unreachable()

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        if not sendable(key):
            return Refused()
        answer = self._send("POST", f"{_API}/repos/{REPOSITORY}/issues/{number}/comments", {"body": body}, key)
        return _commented(answer, 201)

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        if not sendable(key):
            return Refused()
        answer = self._send("PATCH", f"{_API}/repos/{REPOSITORY}/issues/comments/{comment_id}", {"body": body}, key)
        return _commented(answer, 200)

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        """Issue z etykietą strona po stronie; wpis bez numeru (nie issue) pomija, a porażka strony to porażka całości."""

        state = "all" if include_closed else "open"
        entries = self._pages(f"{_API}/repos/{REPOSITORY}/issues?state={state}&labels={label}&", key)
        return entries if not isinstance(entries, list) else tuple(i for i in map(_issue, entries) if i is not None)

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        """Komentarze issue strona po stronie; wpis bez identyfikatora albo adresu pomija, a porażka strony to porażka
        całości."""

        entries = self._pages(f"{_API}/repos/{REPOSITORY}/issues/{number}/comments?", key)
        return entries if not isinstance(entries, list) else tuple(c for c in map(_comment, entries) if c is not None)

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        """Release z tagiem ``tag`` z listy Release'ów i jego pliki, oba strona po stronie; porażka strony to porażka
        całości. Lista, a nie Release po tagu: 404 po tagu znaczy też brak uprawnienia, a lista bez niego jest pusta."""

        releases = self._pages(f"{_API}/repos/{REPOSITORY}/releases?", key)
        if not isinstance(releases, list):
            return releases
        found = next((_release_id(entry) for entry in releases if _tag(entry) == tag), None)
        if found is None:
            return None
        assets = self._pages(f"{_API}/repos/{REPOSITORY}/releases/{found}/assets?", key)
        if not isinstance(assets, list):
            return assets
        return Archive(found, tuple(asset for asset in map(_asset, assets) if asset is not None))

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        """Release z tagiem na domyślnej gałęzi, nie oznaczony jako najnowszy: Archiwum nie jest Wydaniem.

        Repozytorium bez żadnego commitu nie ma gałęzi, na której GitHub założyłby tag: odpowiada 422 „Repository is empty.”
        (repozytorium próbne 2026-11-05 oboma rodzajami klucza, nagrania ``verify-github-skrzynki``), raz 409 „Git
        Repository is empty.” (repozytorium Skrzynki 2026-11-04), a na tag, który już ma Release, 422. Każda z tych odmów trwa, aż Maks
        coś zmieni, więc to ``Rejected``: kolejka zatrzymuje tylko plik w Archiwum, nie wysyłki za nim.
        """

        if not sendable(key):
            return Refused()
        payload = {"tag_name": tag, "name": title, "body": description, "make_latest": "false"}
        answer = self._send("POST", f"{_API}/repos/{REPOSITORY}/releases", payload, key)
        if not isinstance(answer, HttpResponse):
            return answer
        if answer.status == _EMPTY_REPOSITORY:
            return Rejected()
        found = _release_id(_json(answer.body)) if answer.status == 201 else None
        return Archive(found, ()) if found is not None else Unreachable()

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        if not sendable(key):
            return Refused()
        query = urllib.parse.urlencode({"name": name, "label": label})
        url = f"{_UPLOADS}/repos/{REPOSITORY}/releases/{archive_id}/assets?{query}"
        answer = self._submit("POST", url, data, "application/octet-stream", key)
        if not isinstance(answer, HttpResponse):
            return answer
        asset = _asset(_json(answer.body)) if answer.status == 201 else None
        return asset if asset is not None else Unreachable()

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        if not sendable(key):
            return Refused()
        answer = self._exchange(
            HttpRequest(
                method="DELETE",
                url=f"{_API}/repos/{REPOSITORY}/releases/assets/{asset_id}",
                headers=_headers(key),
                body=None,
            )
        )
        if not isinstance(answer, HttpResponse):
            return answer
        return Removed() if answer.status == 204 else Unreachable()

    def _pages(self, query: str, key: str) -> list[object] | Refused | Unreachable:
        """Wpisy listy GitHuba ze wszystkich stron, najwyżej ``_MAX_PAGES``; ``query`` to adres z ``?`` albo ``&`` na końcu."""

        if not sendable(key):
            return Refused()
        found: list[object] = []
        for page in range(1, _MAX_PAGES + 1):
            paged = f"{query}per_page={_PAGE_SIZE}&page={page}"
            answer = self._exchange(HttpRequest(method="GET", url=paged, headers=_headers(key), body=None))
            if not isinstance(answer, HttpResponse):
                return answer
            entries = _json(answer.body) if answer.status == 200 else None
            if not isinstance(entries, list):
                return Unreachable()
            found.extend(entries)
            if len(entries) < _PAGE_SIZE:
                break
        return found

    def _send(
        self, method: str, url: str, payload: Mapping[str, object], key: str
    ) -> HttpResponse | Refused | Rejected | Unreachable:
        return self._submit(method, url, json.dumps(payload).encode("utf-8"), "application/json", key)

    def _submit(
        self, method: str, url: str, body: bytes, content_type: str, key: str
    ) -> HttpResponse | Refused | Rejected | Unreachable:
        """Wysyłka treści ``body``; odpowiedź na samą treść (``_REJECTIONS``) to ``Rejected``."""

        answer = self._exchange(
            HttpRequest(method=method, url=url, headers={**_headers(key), "Content-Type": content_type}, body=body)
        )
        return Rejected() if isinstance(answer, HttpResponse) and answer.status in _REJECTIONS else answer

    def _exchange(self, request: HttpRequest) -> HttpResponse | Refused | Unreachable:
        """Odpowiedź skrzynki na ``request``; brak sieci to ``Unreachable``, odmowa autoryzacji ``Refused``.

        Limit zapytań GitHuba to ``Unreachable``: klucz działa, a skrzynka każe poczekać jak bez sieci.
        """

        transport = self._transport or urllib_transport  # odczyt przy każdym żądaniu: testy blokują go w conftest
        try:
            response = transport(request)
        except (OSError, http.client.HTTPException):
            return Unreachable()
        if response.status in _REFUSALS and _RATE_LIMIT not in response.body:
            return Refused()
        return response


def sendable(key: str) -> bool:
    """Klucz da się wysłać w nagłówku ``Authorization``: widoczne znaki ASCII bez spacji, jak każdy token GitHuba.

    Tę samą regułę stosuje ``KeyedBox.github_key`` dla pytań o Wydania: klucza, którego nie da się wysłać, nie dostają.
    """

    return key.isascii() and key.isprintable() and " " not in key


def _headers(key: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {key}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
    }


def _commented(answer: HttpResponse | Refused | Rejected | Unreachable, status: int) -> CommentOutcome:
    """Komentarz z odpowiedzi ``status`` (201 nowy, 200 poprawiony); inna odpowiedź albo bez id i adresu to ``Unreachable``."""

    if not isinstance(answer, HttpResponse):
        return answer
    document = _json(answer.body) if answer.status == status else None
    if not isinstance(document, dict):
        return Unreachable()
    comment_id, url = document.get("id"), document.get("html_url")
    return Commented(comment_id, url) if isinstance(comment_id, int) and isinstance(url, str) else Unreachable()


def _comment(entry: object) -> Comment | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), int) or not isinstance(entry.get("html_url"), str):
        return None
    body = entry.get("body")
    return Comment(entry["id"], entry["html_url"], body if isinstance(body, str) else "")


def _release_id(entry: object) -> int | None:
    found = entry.get("id") if isinstance(entry, dict) else None
    return found if isinstance(found, int) else None


def _tag(entry: object) -> object:
    return entry.get("tag_name") if isinstance(entry, dict) else None


def _asset(entry: object) -> Asset | None:
    """Plik Release z odpowiedzi GitHuba; wpis bez identyfikatora albo nazwy to ``None``."""

    if not isinstance(entry, dict) or not isinstance(entry.get("id"), int) or not isinstance(entry.get("name"), str):
        return None
    label = entry.get("label")
    return Asset(entry["id"], entry["name"], label if isinstance(label, str) else "", entry.get("state") == "uploaded")


def _issue(entry: object) -> Issue | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("number"), int):
        return None
    body = entry.get("body")
    closure = _closure(entry) if entry.get("state") == "closed" else None
    return Issue(entry["number"], body if isinstance(body, str) else "", closure)


def _closure(entry: dict[str, object]) -> Closure:
    """Zamknięcie z ``state_reason`` i ``closed_at``; nieznany powód albo nieczytelny czas to ``None``."""

    return Closure(close_reason(entry.get("state_reason")), read_moment(entry.get("closed_at")))


def close_reason(value: object) -> CloseReason | None:
    """Znany powód zamknięcia albo ``None`` (brak, ``reopened`` przy otwartym albo powód, którego Centrum nie zna)."""

    return _CLOSE_REASONS.get(value) if isinstance(value, str) else None


def _json_field(body: bytes, name: str) -> object:
    document = _json(body)
    return document.get(name) if isinstance(document, dict) else None


def _json(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None


def read_moment(value: object) -> datetime | None:
    """Czas ze strefą z GitHuba albo z pliku stanu taty; brak, czas bez strefy albo nieczytelny to ``None``."""

    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None
