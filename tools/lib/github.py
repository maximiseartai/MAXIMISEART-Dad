"""GitHub przez ``gh``: jedno wywołanie programu, klient API repozytorium checkoutu ze stronicowaniem i akcje issue.

``gh`` i ``gh_bajty`` to jedyne miejsce, które uruchamia ``gh`` w narzędziach: w katalogu checkoutu, z limitem czasu
``LIMIT_S`` (``None`` bez limitu), a porażka to ``subprocess.CalledProcessError`` z wyjściem błędów programu.
``GhApi`` pyta ``gh api`` o repozytorium checkoutu (``REPO``), a ``strony`` czyta listę API po ``STRONA`` wpisów do
ostatniej niepełnej strony, więc lista dłuższa od strony nie gubi wpisów. Akcje issue (``Zaloz``, ``Skomentuj``,
``Zamknij``) narzędzie najpierw ustala, a potem wykonuje ``wykonaj``, które drukuje jedną linię na akcję.

W workflow ``gh`` dostaje token z ``GH_TOKEN``, lokalnie z logowania Maksa. Moduł używa tylko biblioteki standardowej,
bo Zgłoszenia CI biegną systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import itertools
import json
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
# Temat commitu scalenia PR na GitHubie: merge commit albo squash.
MERGE = re.compile(r"Merge pull request #(?P<numer>[1-9][0-9]*) from \S+")
SQUASH = re.compile(r"(?P<tytul>.+) \(#(?P<numer>[1-9][0-9]*)\)")
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


class GitHub(Protocol):
    def json(self, sciezka: str) -> Any: ...

    def bajty(self, sciezka: str) -> bytes: ...

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any: ...


class GhApi:
    """``gh api`` z ``{owner}/{repo}`` repozytorium checkoutu; porażka to ``RuntimeError`` z błędem ``gh``."""

    def _api(self, *argumenty: str, wejscie: bytes | None = None) -> bytes:
        try:
            return gh_bajty("api", *argumenty, wejscie=wejscie, limit_s=120)
        except subprocess.CalledProcessError as blad:
            raise RuntimeError(f"gh api {' '.join(argumenty)}: {blad.stderr.decode('utf-8', errors='replace').strip()}") from None

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


def blok_kodu(linie: Sequence[str]) -> list[str]:
    """Blok kodu z ``linie``: płot dłuższy od każdego ciągu backticków w nich, więc treść nie wyjdzie z bloku."""

    plot = "`" * max([3, *(len(ciag) + 1 for linia in linie for ciag in re.findall("`+", linia))])
    return [plot, *linie, plot]


@dataclass(frozen=True)
class Zaloz:
    tytul: str
    tresc: str
    etykiety: tuple[str, ...]


@dataclass(frozen=True)
class Skomentuj:
    issue: int
    tresc: str
    otworz: tuple[str, ...] = ()  # niepuste: zamknięte issue wraca otwarte z tymi etykietami


@dataclass(frozen=True)
class Zamknij:
    issue: int
    tresc: str
    zdejmij: tuple[str, ...] = ()  # etykiety, które zamknięcie zdejmuje z issue


Akcja = Zaloz | Skomentuj | Zamknij


def wykonaj(github: GitHub, akcje: Sequence[Akcja], prefiks: str) -> list[str]:
    """Wykonuje akcje po kolei; linia ``<prefiks> | <co zrobione>`` na każdą."""

    linie = []
    for akcja in akcje:
        match akcja:
            case Zaloz(tytul, tresc, etykiety):
                numer = github.wyslij("POST", f"{REPO}/issues", {"title": tytul, "body": tresc, "labels": list(etykiety)})["number"]
                linie.append(f"{prefiks} | założone #{numer} „{tytul}”")
            case Skomentuj(issue, tresc, otworz):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                if otworz:
                    github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "open"})
                    github.wyslij("POST", f"{REPO}/issues/{issue}/labels", {"labels": list(otworz)})
                linie.append(f"{prefiks} | {'otwarte ponownie' if otworz else 'komentarz w'} #{issue}")
            case Zamknij(issue, tresc, zdejmij):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                for etykieta in zdejmij:
                    github.wyslij("DELETE", f"{REPO}/issues/{issue}/labels/{urllib.parse.quote(etykieta)}", {})
                github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "closed", "state_reason": "completed"})
                linie.append(f"{prefiks} | zamknięte #{issue}" + "".join(f", zdjęta etykieta {etykieta}" for etykieta in zdejmij))
    return linie


def opis(akcja: Akcja) -> str:
    """Co akcja zrobi, bez wykonania (podgląd ``--bez-zapisu``)."""

    match akcja:
        case Zaloz(tytul, _, etykiety):
            return f"załóż issue „{tytul}” z etykietami {', '.join(etykiety)}"
        case Skomentuj(issue, _, otworz):
            return f"skomentuj #{issue}" + (f" i otwórz ponownie z etykietami {', '.join(otworz)}" if otworz else "")
        case Zamknij(issue, _, zdejmij):
            return f"zamknij #{issue} z komentarzem" + "".join(f", zdejmij etykietę {etykieta}" for etykieta in zdejmij)
