"""Notka Wydania: tekst GitHub Release, który czyta też Powiadomienie o nowej wersji (ADR 0015).

Notka to „Co nowego” dla taty jego językiem: krótkie zdanie wstępu (może go nie być) i punkty, każdy w linii ``- ``,
a pod nią, gdy są, rozwiązane sprawy taty ze Skrzynki Zgłoszeń, każda w jednej linii z rodzajem, numerem i tytułem::

    Ta wersja oszczędza Ci wpisywania.

    - Przygotowanie pliku zbiorczego samo wpisuje ilości usług.
    - Centrum rozliczeń pokazuje „Co nowego” jako listę.

    ## Rozwiązane sprawy taty

    - Uwaga taty #12: Brakuje ilości przy montażu
    - Zgłoszenie #7: Zatrzymanie przy pustym ADRES

Release jest publiczny, a Skrzynka prywatna, więc sprawa ma tylko numer i tytuł, nigdy treść. Ten moduł jest
jedynym miejscem formatu: notkę pisze ``render`` (narzędzie Wydań), a czyta ``parse`` (Centrum).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Final

from rozliczenia.centrum.dad_cases import KINDS

CASE_KINDS: Final[Mapping[str, str]] = {kind.label: kind.name for kind in KINDS}
"""Etykieta sprawy w Skrzynce Zgłoszeń → jej rodzaj w notce."""
CASES_HEADING: Final = "## Rozwiązane sprawy taty"
_CASES_HEADING_LINE: Final = re.compile(rf"^#+[ \t]+{re.escape(CASES_HEADING.lstrip('# '))}[ \t]*$", re.MULTILINE)
"""Maks poprawia notkę ręcznie na GitHubie, więc nagłówek spraw może mieć inny poziom i spacje na końcu."""

_CASE_LINE: Final = re.compile(r"- (?P<kind>.+?) #(?P<number>[1-9][0-9]*): (?P<title>.+)")
_POINT_LINE: Final = re.compile(r"[-*][ \t]+(?P<text>.+)")
"""Punkt „Co nowego”; Maks poprawia notkę na GitHubie, więc punkt może zaczynać też ``*`` i mieć wcięcie."""


@dataclass(frozen=True)
class DadCase:
    """Sprawa taty ze Skrzynki Zgłoszeń, zamknięta jako rozwiązana: numer issue, tytuł i etykieta rodzaju."""

    number: int
    title: str
    label: str


@dataclass(frozen=True)
class ReleaseNotes:
    """Notka Wydania: „Co nowego” i rozwiązane sprawy taty."""

    summary: str
    cases: tuple[DadCase, ...]


@dataclass(frozen=True)
class WhatsNew:
    """„Co nowego” tak, jak pokazuje je karta Nowej wersji: zdanie wstępu i punkty (bez ``- ``)."""

    intro: str
    points: tuple[str, ...]


def whats_new(summary: str) -> WhatsNew:
    """Wstęp i punkty „Co nowego”; tekst, który nie jest wstępem z samymi punktami po nim, to cały wstęp bez punktów.

    Linia bez ``- `` tuż pod punktem to dalszy ciąg tego punktu (ręcznie złamany na GitHubie), a akapit po pustej
    linii pod punktami zostawia cały tekst wstępem, żeby karta nie zgubiła ani nie przestawiła żadnego zdania.
    """

    lines = summary.strip().splitlines()
    first = next((index for index, line in enumerate(lines) if _POINT_LINE.fullmatch(line.strip())), None)
    if first is None:
        return WhatsNew(summary.strip(), ())
    points: list[str] = []
    after_blank = False
    for line in map(str.strip, lines[first:]):
        if (point := _POINT_LINE.fullmatch(line)) is not None:
            points.append(point["text"].strip())
        elif after_blank:
            return WhatsNew(summary.strip(), ())
        elif line:
            points[-1] = f"{points[-1]} {line}"
        after_blank = not line
    return WhatsNew("\n".join(lines[:first]).strip(), tuple(points))


def render(notes: ReleaseNotes) -> str:
    """Tekst notki; ``ValueError``, gdy „Co nowego” jest puste albo zawiera nagłówek spraw."""

    summary = notes.summary.strip()
    if not summary:
        raise ValueError("notka nie ma „Co nowego”")
    if _CASES_HEADING_LINE.search(summary):
        raise ValueError(f"„Co nowego” nie może zawierać nagłówka {CASES_HEADING!r}")
    if not notes.cases:
        return summary + "\n"
    lines = [f"- {CASE_KINDS[case.label]} #{case.number}: {' '.join(case.title.split())}" for case in notes.cases]
    return "\n".join([summary, "", CASES_HEADING, "", *lines]) + "\n"


def parse(text: str) -> ReleaseNotes:
    """Notka z tekstu ``render``; linia listy spraw, której nie da się odczytać, jest pomijana."""

    summary, *listed = _CASES_HEADING_LINE.split(text.replace("\r\n", "\n"), maxsplit=1)
    labels = {kind: label for label, kind in CASE_KINDS.items()}
    cases = tuple(
        DadCase(int(found["number"]), found["title"].strip(), labels[found["kind"]])
        for line in "".join(listed).splitlines()
        if (found := _CASE_LINE.fullmatch(line.strip())) is not None and found["kind"] in labels
    )
    return ReleaseNotes(summary.strip(), cases)
