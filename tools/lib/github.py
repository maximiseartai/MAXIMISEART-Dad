"""GitHub przez ``gh``: jedno wywołanie programu, klient API repozytorium checkoutu ze stronicowaniem i akcje issue.

``gh`` i ``gh_bajty`` to jedyne miejsce, które uruchamia ``gh`` w narzędziach: w katalogu checkoutu, z limitem czasu
``LIMIT_S`` (``None`` bez limitu), a porażka to ``subprocess.CalledProcessError`` z wyjściem błędów programu.
``GhApi`` pyta ``gh api`` o repozytorium checkoutu (``REPO``), a ``strony`` czyta listę API po ``STRONA`` wpisów do
ostatniej niepełnej strony, więc lista dłuższa od strony nie gubi wpisów. Akcje issue (``Zaloz``, ``Skomentuj``,
``Zamknij``, ``Edytuj``) narzędzie najpierw ustala, a potem wykonuje ``wykonaj``, które drukuje jedną linię na akcję.
``ustaw_status`` to jedyne miejsce, które ustawia status commita.

W workflow ``gh`` dostaje token z ``GH_TOKEN``, lokalnie z logowania Maksa. Moduł używa tylko biblioteki standardowej,
bo Zgłoszenia CI biegną systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Protocol
import urllib.parse

from repo import ROOT

REPO = "repos/{owner}/{repo}"
# Zadanie ``required`` w ``.github/workflows/ci.yml``: jedyny check, który ruleset ``main`` wymaga.
REQUIRED = "Required CI status"
# ``name:`` workflow ``.github/workflows/ci.yml``, który tworzy check ``REQUIRED``.
CI_WORKFLOW = "CI"
# Który run CI rozstrzyga o merge'u do `main`. Nowszy push na `main` anuluje run, który czeka za trwającym (concurrency
# w ci.yml, ADR 0020), a run commitu merge'a tak anulowany nie ma checku ``REQUIRED`` (``rozstrzygniety``).
ROZSTRZYGA = "o merge'u rozstrzyga pierwszy nieanulowany run CI pushu na main, którego commit zawiera merge"
# Etykieta issue czerwonego `main`, które zakłada ``tools/ci/zgloszenia_ci.py``.
CZERWONY_MAIN = "czerwony-main"
# Temat commitu scalenia PR na GitHubie: merge commit albo squash.
MERGE = re.compile(r"Merge pull request #(?P<numer>[1-9][0-9]*) from \S+")
SQUASH = re.compile(r"(?P<tytul>.+) \(#(?P<numer>[1-9][0-9]*)\)")
# Status commita, który ``tools/scal_pr.py --status`` ustawia na HEAD otwartego PR do `main` (workflow
# ``.github/workflows/werdykt-i-bramka.yml``), a raport tygodniowy czyta po merge'u.
WERDYKT_I_BRAMKA = "Werdykt i bramka"
OPIS_STATUSU_LIMIT = 140  # GitHub odrzuca dłuższy opis statusu commita
LIMIT_S = 60
STRONA = 100


def _run(argumenty: Sequence[str], wejscie: str | bytes | None, limit_s: float | None, cwd: Path, *, tekst: bool) -> Any:
    # Po ścieżce z PATH, bo Windows nie uruchamia po samej nazwie programu ``gh.cmd``; brak ``gh`` to FileNotFoundError.
    gh = shutil.which("gh") or "gh"
    try:
        return subprocess.run(
            [gh, *argumenty],
            input=wejscie,
            # Bez wejścia ``gh`` nie czyta wejścia wołającego: w bramie pre-push to lista wypychanych refów.
            stdin=None if wejscie is not None else subprocess.DEVNULL,
            cwd=cwd,
            capture_output=True,
            timeout=limit_s,
            check=True,
            encoding="utf-8" if tekst else None,
            errors="replace" if tekst else None,
        ).stdout
    except subprocess.CalledProcessError as blad:
        # Polecenie w komunikacie jak w logu: ``gh …``, nie ścieżka programu na tym komputerze.
        raise subprocess.CalledProcessError(blad.returncode, ["gh", *argumenty], blad.output, blad.stderr) from None


def gh(*argumenty: str, wejscie: str | None = None, limit_s: float | None = LIMIT_S, cwd: Path = ROOT) -> str:
    """Wyjście ``gh`` jako tekst UTF-8; kod inny niż 0 to ``CalledProcessError``, limit ``TimeoutExpired``."""

    wyjscie: str = _run(argumenty, wejscie, limit_s, cwd, tekst=True)
    return wyjscie


def gh_bajty(*argumenty: str, wejscie: bytes | None = None, limit_s: float | None = LIMIT_S, cwd: Path = ROOT) -> bytes:
    """Jak ``gh``, ale surowe bajty (zip artefaktu, log zadania); ``stderr`` błędu też w bajtach."""

    wyjscie: bytes = _run(argumenty, wejscie, limit_s, cwd, tekst=False)
    return wyjscie


def ustaw_status(commit: str, kontekst: str, stan: str, opis: str) -> str | None:
    """Status commita ``kontekst`` w stanie ``stan`` na ``commit`` repozytorium checkoutu, z ``opis`` przyciętym do
    ``OPIS_STATUSU_LIMIT`` i, w runie GitHub Actions, z linkiem do runu; błąd GitHuba, gdy status nie przeszedł."""

    if len(opis) > OPIS_STATUSU_LIMIT:
        opis = opis[: OPIS_STATUSU_LIMIT - 1] + "…"
    pola = {"state": stan, "context": kontekst, "description": opis}
    run = ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
    if all(os.environ.get(nazwa) for nazwa in run):
        pola["target_url"] = "{}/{}/actions/runs/{}".format(*(os.environ[nazwa] for nazwa in run))
    flagi = [czesc for nazwa, wartosc in pola.items() for czesc in ("-f", f"{nazwa}={wartosc}")]
    try:
        gh("api", "--method", "POST", "--silent", f"{REPO}/statuses/{commit}", *flagi)
    except subprocess.TimeoutExpired:
        return f"gh api bez odpowiedzi przez {LIMIT_S} s"
    except subprocess.CalledProcessError as blad:
        return blad.stderr.strip() or f"gh api: kod {blad.returncode}"
    return None


def html_markdownu(tekst: str, repozytorium: str) -> str:
    """HTML ``tekst`` z renderera GitHuba (``gh api markdown``, ``mode=gfm``, ``context`` to ``repozytorium``), więc to
    GitHub decyduje, co jest kodem, nagłówkiem albo punktem listy; pusty HTML to ``ValueError``."""

    html = gh("api", "markdown", "--input", "-", wejscie=json.dumps({"text": tekst, "mode": "gfm", "context": repozytorium}))
    if not html.strip():
        raise ValueError("GitHub zwrócił pusty HTML")
    return html


def domyslna_galaz(repozytorium: str) -> str:
    """Nazwa domyślnej gałęzi ``repozytorium`` (``właściciel/nazwa``) z ``gh repo view``."""

    return str(json.loads(gh("repo", "view", repozytorium, "--json", "defaultBranchRef"))["defaultBranchRef"]["name"])


@dataclass(frozen=True)
class LinkGithuba:
    """Odwołanie do issue albo PR, które renderer GitHuba (``html_markdownu``) zamienił na link: repozytorium
    ``właściciel/nazwa``, numer i ``rodzaj`` z ``data-hovercard-type`` (``issue`` albo ``pull_request``), który GitHub
    ustala ze stanu numeru u siebie."""

    repozytorium: str
    numer: int
    rodzaj: str

    def w(self, repozytorium: str) -> bool:
        """Czy link wskazuje ``repozytorium`` (właściciel i nazwa bez względu na wielkość liter)."""

        return self.repozytorium.casefold() == repozytorium.casefold()


def link_githuba(atrybuty: Sequence[tuple[str, str | None]]) -> LinkGithuba | None:
    """Link z atrybutów znacznika ``<a>`` HTML renderera GitHuba; ``None``, gdy to nie link do issue ani PR (``issue-link``)."""

    wartosci = dict(atrybuty)
    if "issue-link" not in (wartosci.get("class") or "").split():
        return None
    _, wlasciciel, nazwa, _, numer = urllib.parse.urlsplit(wartosci.get("data-url") or "").path.split("/")
    return LinkGithuba(f"{wlasciciel}/{nazwa}", int(numer), wartosci.get("data-hovercard-type") or "")


class GitHub(Protocol):
    def json(self, sciezka: str) -> Any: ...

    def bajty(self, sciezka: str) -> bytes: ...

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any: ...


class BladApi(RuntimeError):
    """Porażka ``gh api``: komunikat z poleceniem i błędem ``gh``, a ``stderr`` to sam błąd ``gh``."""

    def __init__(self, polecenie: str, stderr: str) -> None:
        super().__init__(f"{polecenie}: {stderr}")
        self.stderr = stderr


@dataclass(frozen=True)
class GhApi:
    """``gh api`` z ``{owner}/{repo}`` repozytorium checkoutu i limitem czasu ``limit_s`` jednego zapytania; porażka to
    ``BladApi`` z błędem ``gh``, a limit ``subprocess.TimeoutExpired``."""

    limit_s: float = 120

    def _api(self, *argumenty: str, wejscie: bytes | None = None) -> bytes:
        try:
            return gh_bajty("api", *argumenty, wejscie=wejscie, limit_s=self.limit_s)
        except subprocess.CalledProcessError as blad:
            raise BladApi(f"gh api {' '.join(argumenty)}", blad.stderr.decode("utf-8", errors="replace").strip()) from None

    def json(self, sciezka: str) -> Any:
        return json.loads(self._api(sciezka))

    def bajty(self, sciezka: str) -> bytes:
        # Zip artefaktu i log zadania mają bajty sekwencji terminala, których gh bez tej flagi nie wypisze.
        return self._api(sciezka, "--allow-escape-sequences")

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        return json.loads(self._api("--method", metoda, sciezka, "--input", "-", wejscie=json.dumps(tresc).encode("utf-8")))


def strony(github: GitHub, sciezka: str) -> Iterator[dict[str, Any]]:
    laczenie = "&" if "?" in sciezka else "?"
    for strona in itertools.count(1):
        partia = github.json(f"{sciezka}{laczenie}per_page={STRONA}&page={strona}")
        yield from partia
        if len(partia) < STRONA:
            return


def issues(github: GitHub, etykieta: str, stan: str, od: datetime | None = None) -> list[dict[str, Any]]:
    """Issue (bez PR-ów) z etykietą w stanie ``open``, ``closed`` albo ``all``, z ``od`` zmienione od tej chwili."""

    zapytanie = {"labels": etykieta, "state": stan, **({"since": od.strftime("%Y-%m-%dT%H:%M:%SZ")} if od else {})}
    return [issue for issue in strony(github, f"{REPO}/issues?{urllib.parse.urlencode(zapytanie)}") if "pull_request" not in issue]


def required(github: GitHub, commit: str) -> dict[str, Any] | None:
    """Najnowszy check ``REQUIRED`` commitu albo ``None``, gdy żaden run go nie utworzył."""

    znalezione = github.json(f"{REPO}/commits/{commit}/check-runs?check_name={urllib.parse.quote(REQUIRED)}&per_page=100")["check_runs"]
    return max(znalezione, key=lambda check: check.get("started_at") or "", default=None)


def rozstrzygniety(github: GitHub, commit: str) -> dict[str, Any] | None:
    """Check ``REQUIRED`` commitu `main`, gdy jego run rozstrzyga o merge'ach (``ROZSTRZYGA``): zakończony sukcesem albo
    porażką. ``None``, gdy run jeszcze biegnie albo go anulowano, więc o merge'ach tego commitu rozstrzyga run
    późniejszego."""

    check = required(github, commit)
    return check if check is not None and check["status"] == "completed" and check["conclusion"] in ("success", "failure") else None


def blok_kodu(linie: Sequence[str]) -> list[str]:
    """Blok kodu z ``linie``: płot dłuższy od każdego ciągu backticków w nich, więc treść nie wyjdzie z bloku."""

    plot = "`" * max([3, *(len(ciag) + 1 for linia in linie for ciag in re.findall("`+", linia))])
    return [plot, *linie, plot]


@dataclass(frozen=True)
class Powiadom:
    """Komentarz ``tresc`` w każdym z PR-ów ``pr`` po założeniu albo skomentowaniu issue; ``wykonaj`` zaczyna go linkiem
    do tego issue, a komentarz, który się nie udał albo przekroczył czas, zapisuje linią i idzie do następnego PR, bo
    issue już jest."""

    pr: tuple[int, ...] = ()
    tresc: str = ""


@dataclass(frozen=True)
class Zaloz:
    tytul: str
    tresc: str
    etykiety: tuple[str, ...]
    powiadom: Powiadom = Powiadom()


@dataclass(frozen=True)
class Skomentuj:
    issue: int
    tresc: str
    otworz: tuple[str, ...] = ()  # niepuste: zamknięte issue wraca otwarte z tymi etykietami
    powiadom: Powiadom = Powiadom()


@dataclass(frozen=True)
class Zamknij:
    issue: int
    tresc: str
    zdejmij: tuple[str, ...] = ()  # etykiety, które zamknięcie zdejmuje z issue


@dataclass(frozen=True)
class Edytuj:
    """Nowa treść issue, bez komentarza."""

    issue: int
    tresc: str


Akcja = Zaloz | Skomentuj | Zamknij | Edytuj


def wykonaj(github: GitHub, akcje: Sequence[Akcja], prefiks: str) -> list[str]:
    """Wykonuje akcje po kolei; linia ``<prefiks> | <co zrobione>`` na każdą."""

    linie = []
    for akcja in akcje:
        match akcja:
            case Zaloz(tytul, tresc, etykiety, powiadom):
                numer = github.wyslij("POST", f"{REPO}/issues", {"title": tytul, "body": tresc, "labels": list(etykiety)})["number"]
                linie.append(f"{prefiks} | założone #{numer} „{tytul}”")
                linie += _powiadom(github, numer, powiadom, prefiks)
            case Skomentuj(issue, tresc, otworz, powiadom):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                if otworz:
                    github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "open"})
                    github.wyslij("POST", f"{REPO}/issues/{issue}/labels", {"labels": list(otworz)})
                linie.append(f"{prefiks} | {'otwarte ponownie' if otworz else 'komentarz w'} #{issue}")
                linie += _powiadom(github, issue, powiadom, prefiks)
            case Zamknij(issue, tresc, zdejmij):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                for etykieta in zdejmij:
                    github.wyslij("DELETE", f"{REPO}/issues/{issue}/labels/{urllib.parse.quote(etykieta)}", {})
                github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "closed", "state_reason": "completed"})
                linie.append(f"{prefiks} | zamknięte #{issue}" + "".join(f", zdjęta etykieta {etykieta}" for etykieta in zdejmij))
            case Edytuj(issue, tresc):
                github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"body": tresc})
                linie.append(f"{prefiks} | zmieniona treść #{issue}")
    return linie


def _powiadom(github: GitHub, issue: int, powiadom: Powiadom, prefiks: str) -> list[str]:
    linie = []
    for pr in powiadom.pr:
        try:
            github.wyslij("POST", f"{REPO}/issues/{pr}/comments", {"body": f"#{issue}\n\n{powiadom.tresc}"})
        except (BladApi, subprocess.TimeoutExpired) as blad:
            linie.append(f"{prefiks} | komentarz w PR #{pr} o #{issue} nieudany: {blad}")
        else:
            linie.append(f"{prefiks} | komentarz w PR #{pr} o #{issue}")
    return linie


def _opis_powiadom(powiadom: Powiadom) -> str:
    return f" i skomentuj PR {', '.join(f'#{pr}' for pr in powiadom.pr)}" if powiadom.pr else ""


def opis(akcja: Akcja) -> str:
    """Co akcja zrobi, bez wykonania (podgląd ``--bez-zapisu``)."""

    match akcja:
        case Zaloz(tytul, _, etykiety, powiadom):
            return f"załóż issue „{tytul}” z etykietami {', '.join(etykiety)}" + _opis_powiadom(powiadom)
        case Skomentuj(issue, _, otworz, powiadom):
            return f"skomentuj #{issue}" + (f" i otwórz ponownie z etykietami {', '.join(otworz)}" if otworz else "") + _opis_powiadom(powiadom)
        case Zamknij(issue, _, zdejmij):
            return f"zamknij #{issue} z komentarzem" + "".join(f", zdejmij etykietę {etykieta}" for etykieta in zdejmij)
        case Edytuj(issue, _):
            return f"zmień treść #{issue} bez komentarza"
