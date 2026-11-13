"""Bramka chwastu przed merge'em (ADR 0031, Q12 i Q15; #1619): chwast z przeglądu wyrywa autor w tym samym PR.

PR, który wymienia otwarte issue z etykietą ``chwast`` (link GitHuba do tego PR w treści issue, czyli wiersz tabeli
„Wystąpienia”, który dopisała publikacja werdyktu), scala się dopiero wtedy, gdy jego opis zamyka to issue linią
``Korzeń z #N: R-KOD`` (``rejestr_korzeni.root_lines`` z linkiem do issue i kodem z tytułu ``Chwast: R-KOD``; zamyka
je ``naprawia.close_fixed`` przy merge'u do domyślnej gałęzi) albo gdy każdy blok sekcji ``## Korzeń`` z kodem issue
ma ``Wyrwany w #M`` (co najmniej jeden blok). Czy PR korzenia ``#M`` jest scalony i ma linię ``Korzeń z`` do tego PR,
sprawdza bramka korzenia, która obowiązuje w każdym wątku tej bramki, bo weszła wcześniej.

Bramka obowiązuje od własnego wdrożenia (decyzja Q20): ``werdykt_pr.rule_applies`` z chwilą ``werdykt_pr.deployment``
dla pliku ``MARKER``, więc wątek z pierwszym werdyktem sprzed niej kończy po staremu. Issues czyta jedno zapytanie
GraphQL (``rejestr_korzeni.weed_issues``, z HTML treści), a opis PR renderer GitHuba, tylko gdy któreś issue wymienia
PR. Błąd GitHuba i issue z etykietą ``chwast``, które wymienia PR, a ma tytuł inny niż ``Chwast: R-KOD``, to odmowa.

Granica: issue zamknięte (także jako duplikat) bramki nie dotyczy, a werdykt, którego chwastu publikacja nie zapisała
w issue (``UWAGA`` w linii ``WERDYKT OK``), bramka zobaczy dopiero po ``tools/chwasty.py``. Linia ``Korzeń z`` musi
stać poza sekcją ``## Korzeń``, bo tam bramka korzenia przyjmuje tylko bloki.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import subprocess
from typing import Any

import github
import rejestr_korzeni
from rejestr_korzeni import Block
from stan_pr import Pull
import szablon_werdyktu
from szablon_werdyktu import CODE
import werdykt_pr

MARKER = "tools/lib/bramka_chwastu.py"  # plik, którego dodanie do bazy PR to chwila wdrożenia bramki (werdykt_pr.deployment)
TITLE_PREFIX = rejestr_korzeni.TITLE.format(code="")
GITHUB_ERRORS = (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError)


def problems(pull: Pull, deployed: datetime | None) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z bramki chwastu; ``deployed`` to chwila jej wdrożenia na bazie PR."""

    if not werdykt_pr.rule_applies(pull, deployed):
        return []
    try:
        weeds = [issue for issue in rejestr_korzeni.weed_issues(pull.repository) if _names(issue, pull)]
    except GITHUB_ERRORS as error:
        return [f"chwast: GitHub nie podał otwartych issues z etykietą {rejestr_korzeni.WEED} ({error}), uruchom ponownie"]
    if not weeds:
        return []
    try:
        units = szablon_werdyktu.items(github.html_markdownu(pull.body, pull.repository))
    except GITHUB_ERRORS as error:
        return [f"chwast: GitHub nie wyrenderował opisu PR ({error}), uruchom ponownie"]
    closing = {(link.numer, code) for link, code in rejestr_korzeni.root_lines(units, pull.repository) if link.rodzaj == "issue"}
    section = rejestr_korzeni.section(units)
    blocks = section.blocks if section is not None else ()
    found = [problem for issue in weeds if (problem := _unclosed(issue, closing, blocks))]
    if not found:
        return []
    return [*found, f"chwast: opis popraw przez gh pr edit {pull.number} --body-file PLIK, bez nowego commita i bez nowego werdyktu"]


def _names(issue: dict[str, Any], pull: Pull) -> bool:
    """Czy treść issue ma link GitHuba do ``pull``."""

    return any(
        link.w(pull.repository) and link.numer == pull.number and link.rodzaj == "pull_request"
        for item in szablon_werdyktu.items(str(issue["bodyHTML"]))
        for link in item.links
    )


def _unclosed(issue: dict[str, Any], closing: set[tuple[int, str]], blocks: Sequence[Block]) -> str | None:
    number, title = int(issue["number"]), str(issue["title"])
    code = title.removeprefix(TITLE_PREFIX)
    if not title.startswith(TITLE_PREFIX) or CODE.fullmatch(code) is None:
        return f"chwast: #{number} „{title}” z etykietą {rejestr_korzeni.WEED} wymienia ten PR, a ma tytuł inny niż „{TITLE_PREFIX}R-KOD”, więc linia „Korzeń z” go nie zamknie: popraw tytuł issue"
    if (number, code) in closing:
        return None
    own = [block for block in blocks if block.code == code]
    if own and all(block.uprooted() is not None for block in own):
        return None
    return (
        f"chwast: otwarte #{number} „{title}” wymienia ten PR, więc ten PR je zamyka: dopisz poza sekcją „## Korzeń” linię "
        f"„Korzeń z #{number}: {code}”, a gdy {code} wyrwał scalony PR korzenia, każdy blok {code} sekcji „## Korzeń” ma tylko „Wyrwany w #M”"
    )
