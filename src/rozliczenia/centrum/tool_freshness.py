"""Aktualność narzędzia: commit narzędzia u taty względem najnowszego Wydania na publicznym GitHubie.

Diagnoza i Konfiguracja oceniają ją przez ``ToolFreshness.judge`` z trzech źródeł:
commitu narzędzia, z którego działa Centrum (``version.tool_commit`` odczytany
przy starcie), odpowiedzi GitHuba o najnowszym Wydaniu na `main` (ADR 0014; ten
sam wybór co w Aktualizacji narzędzia, ``tool_update.newest_on_main``) i
sprawdzenia w klonie, czy commit narzędzia zawiera commit Wydania. Źródła są
wstrzykiwane do aplikacji Centrum, więc testy i weryfikacja w przeglądarce nigdy
nie łączą się z GitHubem. Brak sieci to ``None`` w krótkim limicie czasu, nigdy
wyjątek ani Komunikat. Diagnoza pyta GitHuba przy każdym sprawdzeniu;
Konfiguracja, odczytywana przy każdym wejściu na stronę, pamięta jego odpowiedź
(``RememberedRelease``), także tę z Diagnozy. Czy z oceny wynika propozycja
Aktualizacji narzędzia, mówi jedna reguła: ``offers_update``. Powiadomienie o
nowej wersji czyta stąd też opublikowane Wydania z ich notkami
(``PublishedRelease``, lista GitHub Releases).

Pytania do API GitHuba idą z Tokenem do Zgłoszeń, gdy jest plik klucza: daje go
``KeyedBox.github_key``, a token daje limit konta (5000 pytań na godzinę) zamiast
60 na godzinę wspólnych dla całego adresu IP. Nagłówek ``Authorization`` dostaje
tylko host API (przekierowania: zob. ``github``). Odmowa pytania
z tokenem (401, 403 bez wyczerpanego limitu) to jedno ponowienie tego pytania
bez tokenu, a reszta sprawdzenia idzie już bez niego: stary albo zły token nie
zabiera tacie aktualizacji. 404 z tokenem to ponowienie tylko tego pytania bez
tokenu, bo 404 bywa prawdziwą odpowiedzią wyszukiwania. Odmowa z powodu wyczerpanego limitu pytania
z tokenem też daje jedno ponowienie bez tokenu, bo limit konta (wspólny z agentami
Maksa) i limit adresu IP to dwie osobne pule. Odmowa z powodu limitu pytania bez
tokenu to ``RateLimited`` z chwilą, od której limit znów jest pełny; Diagnoza ją nazywa.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
from http.client import HTTPException
import json
from pathlib import Path
import threading
from typing import Final, Literal
from urllib.parse import urlsplit

from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.github import (
    ANSWER_KEPT_S,
    MAX_PAGES,
    NO_ANSWER_KEPT_S,
    PAGE_SIZE,
    TOOL_API,
    HttpRequest,
    headers,
    next_page,
    rate_limit_reset,
    send,
)
from rozliczenia.centrum.tool_update import Release, contains_commit, find_git, newest_on_main, release_at
from rozliczenia.centrum.version import commit_since, is_commit, tool_commit
from rozliczenia.tool_files import TOOL_ROOT

CommitSource = Callable[[], str | None]


@dataclass(frozen=True)
class GitHubReleases:
    """Odpowiedź GitHuba: commit i tag najnowszego Wydania na `main`; ``None``, gdy na `main` nie ma żadnego Wydania."""

    newest: str | None
    tag: str | None


@dataclass(frozen=True)
class RateLimited:
    """GitHub odmówił, bo wyczerpał się limit pytań (403 albo 429 z ``X-RateLimit-Remaining: 0``); ``reset`` to chwila
    z ``X-RateLimit-Reset``, od której limit znów jest pełny."""

    reset: datetime


ReleaseSource = Callable[[], GitHubReleases | None]
"""``None``: GitHub nie odpowiedział (brak sieci, odmowa, limit czasu, niepełna odpowiedź)."""
ReleaseAnswer = GitHubReleases | RateLimited | None
"""Odpowiedź źródła Aktualności: jak ``ReleaseSource``, a odmowa z powodu limitu GitHuba to ``RateLimited``."""
AnswerSource = Callable[[], ReleaseAnswer]
KeySource = Callable[[], str | None]
"""Token do Zgłoszeń teraz albo ``None`` bez pliku klucza (``KeyedBox.github_key``)."""


@dataclass(frozen=True)
class PublishedRelease:
    """Wydanie opublikowane jako GitHub Release: numer z tagu, notka (``release_notes``) i czas publikacji."""

    release: Release
    notes: str
    at: datetime


PublishedSource = Callable[[], tuple[PublishedRelease, ...] | None]
"""``None``: GitHub nie odpowiedział; pusta krotka: nie ma żadnego opublikowanego Wydania."""
Judgement = Literal["current", "newer", "no_release", "no_answer", "no_commit"]


def offers_update(judgement: Judgement) -> bool:
    """Czy Centrum proponuje tacie Aktualizację narzędzia przy Aktualności ``judgement``.

    Tylko przy Wydaniu nowszym od wersji taty (ADR 0014), nigdy bez odpowiedzi
    GitHuba. Pytają o to Konfiguracja, Diagnoza i Powiadomienie o nowej wersji
    (#324).
    """

    return judgement == "newer"


_CANDIDATES: Final = 5
"""Tyle najwyższych Wydań sprawdza się po kolei, zanim jedno leży na ``main``; dalej wynik jest nieznany."""
_PAGE_BYTES: Final = 1_000_000
_TIMEOUT_S: Final = 3.0


@dataclass(frozen=True)
class ToolFreshness:
    """Źródła Aktualności narzędzia; ``None`` = nie wiadomo.

    ``local`` to commit narzędzia, z którego działa Centrum, ``since`` dzień, od
    którego narzędzie jest na tym commicie, ``release`` odpowiedź GitHuba o
    najnowszym Wydaniu, ``published`` opublikowane Wydania z notkami,
    ``contains(release, local)`` mówi, czy commit narzędzia zawiera commit Wydania, a
    ``wydanie(local)`` to Wydanie, którego tag w klonie wskazuje dokładnie commit narzędzia.
    """

    local: CommitSource
    since: Callable[[], date | None]
    release: AnswerSource
    published: PublishedSource
    contains: Callable[[str, str], bool] = field(default=lambda release, local: release == local)
    wydanie: Callable[[str], Release | None] = field(default=lambda local: None)

    @classmethod
    def of_system(cls, key: KeySource) -> ToolFreshness:
        """Aktualność narzędzia tego komputera; każde sprawdzenie pyta GitHuba z tokenem ``key()``, gdy jest."""

        return cls.of_clone(TOOL_ROOT, github_releases(key, TOOL_API), lambda: github_published(key()))

    @classmethod
    def of_clone(
        cls,
        root: Path,
        release: AnswerSource,
        published: PublishedSource,
        *,
        find_git: Callable[[], Path | None] = find_git,
    ) -> ToolFreshness:
        """Wersja narzędzia w ``root`` odczytana teraz, przy starcie Centrum.

        Klon przesunięty później (ręcznie albo przez aktualizację przed ponownym startem) nie zmienia kodu, który
        już działa, więc nie zmienia też wersji tego Centrum.
        """

        running = tool_commit(root)
        since = None if running is None else commit_since(running, root)
        return cls(
            local=lambda: running,
            since=lambda: since,
            release=release,
            published=published,
            contains=partial(contains_commit, root),
            wydanie=partial(release_at, root, find_git=find_git),
        )

    def judge(self, release: AnswerSource | None = None) -> Judgement:
        """Aktualność narzędzia według ``release`` (domyślnie ``self.release``).

        ``current``, gdy commit narzędzia zawiera commit najnowszego Wydania:
        także narzędzie na nowszym commicie `main` niż Wydanie jest aktualne.
        """

        return self.assess(release)[0]

    def assess(self, release: AnswerSource | None = None) -> tuple[Judgement, ReleaseAnswer]:
        """Aktualność narzędzia (``judge``) i odpowiedź GitHuba, z której wynika; ``None``, gdy nie pytano, bo narzędzie
        nie ma commitu."""

        local = self.local()
        if local is None:
            return "no_commit", None
        answer = (release or self.release)()
        if not isinstance(answer, GitHubReleases):
            return "no_answer", answer
        if answer.newest is None:
            return "no_release", answer
        return ("current" if self.contains(answer.newest, local) else "newer"), answer


class RememberedRelease:
    """Odpowiedź ``release`` pamiętana przez ``ANSWER_KEPT_S`` na zegarze ``clock``; brak odpowiedzi krócej.

    Konfiguracja, Powiadomienia i Aktualizacja narzędzia nie odróżniają odmowy z powodu limitu od braku odpowiedzi,
    więc dostają ``None``; ``RateLimited`` dostaje tylko Diagnoza (``fresh``).
    """

    def __init__(self, release: AnswerSource, *, clock: Callable[[], float]) -> None:
        self._release = release
        self._clock = clock
        self._lock = threading.Lock()
        self._answer: GitHubReleases | None = None
        self._asked_at: float | None = None

    def __call__(self) -> GitHubReleases | None:
        with self._lock:
            if self._asked_at is not None:
                kept = ANSWER_KEPT_S if self._answer is not None else NO_ANSWER_KEPT_S
                if self._clock() - self._asked_at < kept:
                    return self._answer
        answer = self._release()
        known = answer if isinstance(answer, GitHubReleases) else None
        with self._lock:
            self._answer, self._asked_at = known, self._clock()
        return known

    def fresh(self) -> ReleaseAnswer:
        """Odpowiedź ``release`` teraz, bez pamięci (Diagnoza); odpowiedź, która przyszła, zostaje w pamięci."""

        answer = self._release()
        if isinstance(answer, GitHubReleases):
            with self._lock:
                self._answer, self._asked_at = answer, self._clock()
        return answer


def github_releases(key: KeySource, api: str) -> AnswerSource:
    """Najnowsze Wydanie na `main` repozytorium ``api`` przy każdym pytaniu, z tokenem ``key()``, gdy jest; ``None`` bez
    sieci, po limicie czasu, przy odmowie.

    Commity Wydań, które są przodkami `main`, i czy leżą na linii jego pierwszych rodziców (``known`` w
    ``releases_from``), źródło pamięta między pytaniami.
    """

    line: dict[str, bool] = {}
    return lambda: releases_from(api, timeout_s=_TIMEOUT_S, known=line, token=key())


def releases_from(
    api: str, *, timeout_s: float, known: dict[str, bool] | None = None, token: str | None = None
) -> ReleaseAnswer:
    """Najnowsze Wydanie na `main` z API GitHuba repozytorium ``api``, najpóźniej po ``timeout_s`` sekundach.

    Lista tagów (``tags``) przychodzi stronami (nagłówek ``Link``); bez
    wszystkich stron nie wiadomo, które Wydanie jest najnowsze, więc więcej niż
    ``github.MAX_PAGES`` stron to ``None``. Wydanie leży na `main` tak jak w Aktualizacji
    narzędzia (``tool_update.MainLine``): jego commit leży na linii pierwszych
    rodziców `main` (``on_first_parent_line``). Odpowiedź dla commitu, który
    jest przodkiem `main`, trafia do ``known`` i się nie zmienia, bo `main`
    rośnie tylko o nowe commity. Diagnoza czeka na odpowiedź najwyżej
    ``timeout_s`` (``deadline.within``); spóźniona odpowiedź i tak trafia do
    ``known``. Połączenie idzie wprost, bez serwera proxy z ustawień systemu.
    Pytania idą z tokenem ``token`` tak, jak mówi opis modułu (``Asking``), a
    sprawdzenie bez odpowiedzi po odmowie z powodu limitu to ``RateLimited``.
    """

    line = {} if known is None else known

    def fetch() -> ReleaseAnswer:
        asking = Asking(api, timeout_s, token)
        answer = newest(asking)
        return answer if answer is not None else asking.limited

    def newest(asking: Asking) -> GitHubReleases | None:
        commits = tag_commits(asking, f"{api}/tags?per_page={PAGE_SIZE}")
        if commits is None:
            return None
        asked = 0
        tips: list[str] = []

        def on_main(commit: str) -> bool:
            nonlocal asked
            asked += 1
            if asked > _CANDIDATES:
                raise NoAnswer
            if commit in line:
                return line[commit]
            if not tips:
                tips.append(_main_tip(asking))
            on_line = on_first_parent_line(asking, commit, tips[0])
            if on_line is not None:
                line[commit] = on_line
            return on_line is True

        try:
            found = newest_on_main(commits, on_main)
        except NoAnswer:
            return None
        return GitHubReleases(found.commit, None if found.release is None else found.release.tag)

    return within(timeout_s, fetch, name="github-wydania")


def _main_tip(asking: Asking) -> str:
    """Czubek `main` teraz: wszystkie porównania jednego sprawdzenia liczą od tego samego commitu."""

    ref = asking.json(f"{asking.api}/git/ref/heads/main")
    target = ref.get("object") if isinstance(ref, dict) else None
    sha = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(sha, str) or not is_commit(sha):
        raise NoAnswer
    return sha


def on_first_parent_line(asking: Asking, commit: str, tip: str) -> bool | None:
    """Czy ``commit`` jest jednym z ``tip~k``, czyli leży na linii pierwszych rodziców ``tip``; ``None``, gdy nie
    jest przodkiem ``tip``.

    API bez logowania nie podaje linii pierwszych rodziców, ale porównuje z ``tip~k``. ``tip~k`` zawiera przodka
    ``commit`` od k = 0 do pewnego k, a dalej już nie; ``commit`` leży na linii, gdy przy tym k jest nim samym. To k
    nie przekracza liczby commitów ``tip`` spoza ``commit`` (``ahead_by``), bo ``tip~0`` … ``tip~(k-1)`` to różne
    takie commity, więc wyszukiwanie binarne pyta najwyżej ``log2(ahead_by) + 2`` razy. ``tip~k`` sprzed pierwszego
    commitu repozytorium (404) nie zawiera ``commit``.

    Wyszukiwanie przy tygodniu zmian `main` nie mieści się w limicie Diagnozy, więc najpierw pada jedno pytanie, czy
    ``commit`` to commit scalenia PR do `main` (``_merged_into_main``). Taki przodek ``tip`` był czubkiem `main`, a
    `main` rośnie tylko o nowe commity, więc leży na linii. Wyszukiwanie zostaje dla commitu bez scalenia PR (gałąź
    wciągnięta merge'em, commit wypchnięty wprost na `main`).
    """

    status, ahead = compare(asking, commit, tip)
    if status == "identical":
        return True
    if status != "ahead":
        return None
    if _merged_into_main(asking, commit):
        return True
    contains, beyond = 0, ahead + 1
    while beyond - contains > 1:
        middle = (contains + beyond) // 2
        try:
            status, _ = compare(asking, commit, f"{tip}~{middle}")
        except NotFound:
            status = "behind"
        if status == "identical":
            return True
        if status == "ahead":
            contains = middle
        else:
            beyond = middle
    return False


def _merged_into_main(asking: Asking, commit: str) -> bool:
    """Czy GitHub scalił ``commit`` do `main` jako commit PR (``merge_commit_sha``), czyli ``commit`` był czubkiem
    `main`; ``False`` także przy odmowie i odpowiedzi w innym kształcie, bo wtedy decyduje wyszukiwanie binarne.

    Jedno pytanie bez względu na to, jak daleko `main` odszedł od ``commit``. Commit gałęzi wciągniętej merge'em ma
    PR, ale inny ``merge_commit_sha``, więc tu nie przechodzi.
    """

    try:
        pulls = asking.json(f"{asking.api}/commits/{commit}/pulls")
    except NoAnswer:
        pulls = ()
    return any(
        isinstance(pull, dict)
        and pull.get("merge_commit_sha") == commit
        and isinstance(pull.get("merged_at"), str)
        and isinstance(base := pull.get("base"), dict)
        and base.get("ref") == "main"
        for pull in (pulls if isinstance(pulls, list) else ())
    )


def compare(asking: Asking, commit: str, head: str) -> tuple[str, int]:
    """Stan ``commit`` względem ``head`` (``ahead``: ``head`` go zawiera) i liczba commitów ``head`` spoza niego, ze
    strony porównania bez commitów i plików."""

    compared = asking.json(f"{asking.api}/compare/{commit}...{head}?per_page=1&page=2")
    status = compared.get("status") if isinstance(compared, dict) else None
    ahead = compared.get("ahead_by") if isinstance(compared, dict) else None
    if not isinstance(status, str) or type(ahead) is not int:
        raise NoAnswer
    return status, ahead


PUBLISHED_PAGE: Final = 30
"""Tyle ostatnio opublikowanych Wydań (jedna strona listy) pokazują Powiadomienia; starsze nie wracają do historii."""


def github_published(token: str | None = None) -> tuple[PublishedRelease, ...] | None:
    """Opublikowane Wydania publicznego repozytorium, pytane z tokenem ``token``, gdy jest; ``None`` bez sieci, po
    limicie czasu, przy odmowie."""

    return published_from(TOOL_API, timeout_s=_TIMEOUT_S, token=token)


def published_from(api: str, *, timeout_s: float, token: str | None = None) -> tuple[PublishedRelease, ...] | None:
    """Ostatnie ``PUBLISHED_PAGE`` Wydań z listy GitHub Releases repozytorium ``api`` jednym pytaniem, z tokenem
    ``token`` tak jak ``releases_from``."""

    def fetch() -> tuple[PublishedRelease, ...] | None:
        try:
            return parse_published(Asking(api, timeout_s, token).json(f"{api}/releases?per_page={PUBLISHED_PAGE}"))
        except NoAnswer:
            return None

    return within(timeout_s, fetch, name="github-notki-wydan")


def parse_published(document: object) -> tuple[PublishedRelease, ...] | None:
    """Wydania z odpowiedzi listy GitHub Releases; ``None``, gdy odpowiedź nie jest listą.

    Szkic, wersja przedpremierowa, tag, który nie jest Wydaniem, i wpis w innym kształcie się nie liczą; Release bez
    treści ma pustą notkę.
    """

    if not isinstance(document, list):
        return None
    return tuple(published for entry in document if (published := _published(entry)) is not None)


def _published(entry: object) -> PublishedRelease | None:
    if not isinstance(entry, dict) or entry.get("draft") is not False or entry.get("prerelease") is not False:
        return None
    tag, notes, at = entry.get("tag_name"), entry.get("body"), entry.get("published_at")
    release = Release.of_tag(tag) if isinstance(tag, str) else None
    if release is None or not isinstance(notes, str | None) or not isinstance(at, str):
        return None
    try:
        published_at = datetime.fromisoformat(at)
    except ValueError:
        return None
    return PublishedRelease(release, notes or "", published_at) if published_at.tzinfo is not None else None


class NoAnswer(Exception):
    """GitHub nie dał pełnej odpowiedzi; Aktualność to wtedy ``None``."""


class NotFound(NoAnswer):
    """GitHub odpowiedział 404: nie zna takiego commitu."""


def tag_commits(asking: Asking, url: str) -> dict[str, str] | None:
    """Tagi i ich commity ze wszystkich stron listy tagów; ``None`` bez pełnej listy."""

    commits: dict[str, str] = {}
    page = url
    for _ in range(MAX_PAGES):
        try:
            tags, following = asking.page(page)
        except NoAnswer:
            return None
        if not isinstance(tags, list):
            return None
        for tag in tags:
            named = _tag_commit(tag)
            if named is not None:
                commits[named[0]] = named[1]
        if following is None:
            return commits
        page = following
    return None


_TOKEN_REFUSALS: Final = frozenset({401, 403})
"""Odmowy pytania z tokenem, po których to samo pytanie idzie jeszcze raz bez tokenu (opis modułu)."""


class Asking:
    """Pytania jednego sprawdzenia do API repozytorium ``api``: z tokenem tylko do hosta ``api``, dopóki GitHub nie
    odmówi pytania z nim (opis modułu); ``limited`` to ostatnia odmowa z powodu limitu."""

    def __init__(self, api: str, timeout_s: float, token: str | None) -> None:
        self.api = api
        self._timeout_s = timeout_s
        self._token = token
        self._host = urlsplit(api)[:2]
        self.limited: RateLimited | None = None

    def json(self, url: str) -> object:
        return self.page(url)[0]

    def page(self, url: str, *, with_token: bool = True) -> tuple[object, str | None]:
        """Treść JSON odpowiedzi ``url`` i adres następnej strony z nagłówka ``Link``; ``NoAnswer`` przy porażce: brak
        sieci (``OSError``), zerwane połączenie (``HTTPException``), odpowiedź, która nie jest JSON (``ValueError``),
        albo odmowa GitHuba bez ponowienia, a 404 bez ponowienia to ``NotFound``.

        404 na pytanie z tokenem to jedno ponowienie tego pytania bez tokenu, ale token zostaje dla następnych:
        wyszukiwanie binarne dostaje 404 także wtedy, gdy ``tip~k`` sięga przed pierwszy commit repozytorium."""

        token = self._token if with_token and urlsplit(url)[:2] == self._host else None
        request = HttpRequest("GET", url, headers(token), None)
        try:
            response = send(
                request, proxy="direct", key_after_redirect="nowhere", timeout_s=self._timeout_s, read_limit=_PAGE_BYTES
            )
            if 200 <= response.status < 300:
                return json.loads(response.body), next_page(response)
        except (OSError, HTTPException, ValueError) as failure:
            raise NoAnswer from failure
        reset = rate_limit_reset(response)
        if reset is not None and token is None:
            self.limited = RateLimited(reset)
            raise NoAnswer
        if token is not None and (reset is not None or response.status in _TOKEN_REFUSALS):
            self._token = None
            return self.page(url)
        if token is not None and response.status == 404:
            return self.page(url, with_token=False)
        raise NotFound if response.status == 404 else NoAnswer


def _tag_commit(tag: object) -> tuple[str, str] | None:
    if not isinstance(tag, dict):
        return None
    name, commit = tag.get("name"), tag.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    return (name, sha) if isinstance(name, str) and isinstance(sha, str) and is_commit(sha) else None
