"""Bramka chwastu przed merge'em (ADR 0031, Q12 i Q15; #1619): chwast z przeglądu wyrywa autor w tym samym PR.

PR, którego Ważne ma kod ``R-KOD`` z otwartym issue ``Chwast: R-KOD`` z etykietą ``chwast``, scala się dopiero wtedy,
gdy jego opis zamyka to issue linią ``Korzeń z #N: R-KOD`` (``rejestr_korzeni.root_lines``; zamyka je
``naprawia.close_fixed`` przy merge'u do domyślnej gałęzi) albo gdy każdy blok sekcji ``## Korzeń`` z tym kodem ma
``Wyrwany w #M`` (co najmniej jeden blok). Kody Ważnych daje ``rejestr_korzeni.majors`` z werdyktów PR, czyli kod
z ostatniego werdyktu, który dotyczy Ważnego (także po rozstrzygnięciu innym kodem, Q25), jak w bramce korzenia
i w rejestrze, który publikacją werdyktu dopisuje PR do tego issue. Issue wskazuje sam tytuł, jak w
``rejestr_korzeni.settle``; treści issue bramka nie czyta. Czy PR korzenia ``#M`` jest scalony i ma linię
``Korzeń z`` do tego PR, sprawdza bramka korzenia, która obowiązuje w każdym wątku tej bramki, bo weszła wcześniej.

Bramka obowiązuje od własnego wdrożenia (decyzja Q20): ``werdykt_pr.rule_applies`` z chwilą ``werdykt_pr.deployment``
dla pliku ``MARKER``, więc wątek z pierwszym werdyktem sprzed niej kończy po staremu. Werdykty i opis PR czyta
renderer GitHuba, a issues jedno zapytanie GraphQL (``rejestr_korzeni.weed_issues``), tylko gdy PR ma Ważne z kodem;
opis PR tylko, gdy któreś issue pasuje. Błąd GitHuba to odmowa.

Granica: issue zamknięte (także jako duplikat) bramki nie dotyczy, tak samo issue z tytułem innym niż
``Chwast: R-KOD`` (``settle`` go nie uzupełnia, tylko zakłada nowe). Ważne z kodem, którego issue założy dopiero
``tools/chwasty.py`` (``UWAGA`` w linii ``WERDYKT OK``), bramka zobaczy po jego uruchomieniu. Linia ``Korzeń z`` musi
stać poza sekcją ``## Korzeń``, bo tam bramka korzenia przyjmuje tylko bloki.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import subprocess

import github
import rejestr_korzeni
from rejestr_korzeni import Block
from stan_pr import Pull
import szablon_werdyktu
import werdykt_pr

MARKER = "tools/lib/bramka_chwastu.py"  # plik, którego dodanie do bazy PR to chwila wdrożenia bramki (werdykt_pr.deployment)
GITHUB_ERRORS = (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError)


def problems(pull: Pull, deployed: datetime | None) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z bramki chwastu; ``deployed`` to chwila jej wdrożenia na bazie PR."""

    if not werdykt_pr.rule_applies(pull, deployed):
        return []
    try:
        majors = rejestr_korzeni.majors(werdykt_pr.rounds(pull, werdykt_pr.rendered(pull)))[0].values()
    except GITHUB_ERRORS as error:
        return [f"chwast: GitHub nie wyrenderował treści werdyktów ({error}), uruchom ponownie"]
    titles = {rejestr_korzeni.TITLE.format(code=major.code): major.code for major in majors if major.code is not None}
    if not titles:
        return []
    try:
        weeds = [(int(issue["number"]), titles[str(issue["title"])]) for issue in rejestr_korzeni.weed_issues(pull.repository) if str(issue["title"]) in titles]
    except GITHUB_ERRORS as error:
        return [f"chwast: GitHub nie podał otwartych issues z etykietą {rejestr_korzeni.WEED} ({error}), uruchom ponownie"]
    if not weeds:
        return []
    try:
        units = szablon_werdyktu.items(github.html_markdownu(pull.body, pull.repository))
    except GITHUB_ERRORS as error:
        return [f"chwast: GitHub nie wyrenderował opisu PR ({error}), uruchom ponownie"]
    closing = {(link.numer, code) for link, code in rejestr_korzeni.root_lines(units, pull.repository)}
    section = rejestr_korzeni.section(units)
    blocks = section.blocks if section is not None else ()
    found = [problem for number, code in weeds if (problem := _unclosed(number, code, closing, blocks))]
    if not found:
        return []
    return [*found, f"chwast: opis popraw przez gh pr edit {pull.number} --body-file PLIK, bez nowego commita i bez nowego werdyktu"]


def _unclosed(number: int, code: str, closing: set[tuple[int, str]], blocks: Sequence[Block]) -> str | None:
    if (number, code) in closing:
        return None
    own = [block for block in blocks if block.code == code]
    if own and all(block.uprooted() is not None for block in own):
        return None
    return (
        f"chwast: otwarte #{number} „{rejestr_korzeni.TITLE.format(code=code)}” ma Ważne tego PR z kodem {code}, więc ten PR je zamyka: dopisz poza sekcją „## Korzeń” linię "
        f"„Korzeń z #{number}: {code}”, a gdy {code} wyrwał scalony PR korzenia, każdy blok {code} sekcji „## Korzeń” ma tylko „Wyrwany w #M”"
    )
