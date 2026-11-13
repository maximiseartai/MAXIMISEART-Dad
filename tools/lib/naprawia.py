"""Po merge'u do domyślnej gałęzi repozytorium, przed sprzątaniem, zamyka jego otwarte issues, które opis PR wskazuje
słowem „Naprawia”. GitHub tego słowa nie zna, więc bez narzędzia takie issues zostawały otwarte. Każde dostaje
komentarz z numerem PR i pełnym SHA commitu merge'a, a linia ``SCAL OK`` podaje ``zamknięte: #N``. Opis bez słowa
„Naprawia” pomija bez pytania GitHuba. Z nim pyta o domyślną gałąź (``gh repo view``), a przy merge'u do niej
renderuje opis rendererem GitHuba (``gh api markdown``, ``mode=gfm``, ``context`` to repozytorium PR), więc to GitHub
decyduje, co jest kodem, cytatem albo komentarzem HTML.

Issue się liczy, gdy GitHub zamienił jego odwołanie na link do issue tego repozytorium (bez względu na wielkość liter
właściciela i nazwy), a link stoi na liście numerów zaraz po słowie „Naprawia”, pisanym dokładnie tak, od wielkiej
litery, które zaczyna linię akapitu albo punktu listy. Linia liczy się tylko wtedy, gdy jej tekst zaczyna się
w akapicie albo punkcie listy, a wszystko, w czym ten blok stoi, to akapity, punkty i listy; w samym bloku tekst może
stać jeszcze w pogrubieniu albo kursywie. Każde inne miejsce niczego nie zamyka, także takie, którego tu nie wymieniono
i którego GitHub dopiero zacznie używać: nagłówek, tabela, ``<details>`` i ``<summary>``, cytat i alert GitHuba
(``> [!NOTE]``), blok HTML (``<div>``, ``<section>``, ``<dl>``), przypis i ``<pre>``, także gdy GitHub owinie tekst
w nich w akapit albo punkt listy. Linię kończy tylko ``<br>``, którym GitHub zastępuje koniec wiersza, oraz początek
i koniec bloku: akapitu, punktu listy, nagłówka, cytatu, tabeli, ``<pre>``, ``<div>``, ``<details>``, ``<summary>``
i ``<hr>``. Każdy inny znacznik (``<q>``, ``<kbd>``, emoji, wzór ``$…$`` i każdy, którego GitHub dopiero zacznie
używać) należy do linii, a jego tekst się liczy, poza kodem i przekreśleniem. Liczy się więc ``Naprawia #490``,
``Naprawia #490, #491 i #492 oraz #493``, kilka linii, także pogrubionych, i adres issue. Lista kończy się na
pierwszym tekście innym niż przecinek, „i”, „oraz” albo numer, którego GitHub nie zlinkował (nieistniejący): „Naprawia
#490. Nie naprawia #491” zamyka tylko #490. Kończy ją też odwołanie do innego repozytorium: w ``Naprawia
MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia#12, #13`` GitHub linkuje ``#13`` do tego repo, ale autor wylicza tam
Zgłoszenia. Zgłoszenie zostaje otwarte, bo zamknięte mówi Centrum taty, że poprawka czeka na aktualizację, a merge do
``main`` to jeszcze nie Wydanie. Nie zamyka: „Naprawia” w środku linii (także „Ten PR <q>nie</q> Naprawia #490”),
„naprawia” małą literą (także w zawiniętej linii „Ten PR nie do końca⏎naprawia #490”), linii, która zaczyna się od
kodu, przekreślenia (także takich, które zaczęły się przed końcem poprzedniego wiersza: ``~~Ten PR⏎nie~~ Naprawia
#490``), obrazka albo pola punktu listy zadań (``- [ ] Naprawia #490``), linii spoza akapitów i list (wyżej), kodu
(fragmentu, bloku i ``<pre>``), przekreślenia, PR-a, issue już zamkniętego ani issues, które GitHub zamyka sam
(``closingIssuesReferences``: ``Closes``, ``Fixes``, ``Resolves``).

Tą samą drogą zamyka issues chwastów (ADR 0031, Q15): linia akapitu albo punkt listy ``Korzeń z #N: R-KOD``
(``rejestr_korzeni.root_lines``) z linkiem do issue tego repozytorium zamyka #N, gdy jest otwarte i ma tytuł
``Chwast: R-KOD`` z tym kodem, z tym samym komentarzem o PR i commicie merge'a; inne issue zostaje otwarte
z ostrzeżeniem ``UWAGA: #N z „Korzeń z” to nie otwarte issue „Chwast: R-KOD” z tym kodem``. Linia z linkiem do PR to
linia PR korzenia (Q14), więc niczego nie zamyka. Ostrzeżenia niżej mówią wtedy o „Naprawia” i „Korzeń z”.

Merge do innej gałęzi niż domyślna (stos PR-ów) niczego nie zamyka i nie renderuje opisu, jak GitHub przy ``Closes``,
a linia podaje ``bez zamykania „Naprawia”: baza <gałąź> to nie <domyślna>``. Gdy GitHub nie poda domyślnej gałęzi
albo nie wyrenderuje opisu (``gh`` z błędem albo po czasie, pusta odpowiedź), narzędzie niczego nie zamyka, tylko
ostrzega ``UWAGA: GitHub nie podał domyślnej gałęzi`` albo ``UWAGA: GitHub nie wyrenderował opisu PR`` z dopiskiem
``nie zamknięto issues z „Naprawia”, zamknij je ręcznie``. Gdy GitHub po merge'u nie poda commitu merge'a, narzędzie
nie zamyka, bo nie wie, czy PR wszedł do gałęzi (np. czeka w kolejce merge'a), tylko ostrzega ``UWAGA: GitHub nie
podał commitu merge'a, nie zamknięto #N, zamknij ręcznie``. Każdy błąd przy zamykaniu (``gh`` z błędem albo po
czasie, odpowiedź bez stanu issue) kończy się ostrzeżeniem ``UWAGA: nie zamknięto #N, zamknij ręcznie``. Każde z tych
ostrzeżeń stoi w linii ``SCAL OK`` z kodem 0, bo PR jest już scalony. Z ``--bez-merge`` tylko czyta, niczego nie
zamyka, a linia podaje ``po merge'u zamknie: #N`` (a zamiast „nie zamknięto …” ostrzeżenia ``nie sprawdzono …``).
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
import re

import github
from github import LinkGithuba
import rejestr_korzeni
from stan_pr import Pull
import szablon_werdyktu

LINK = "\x01"
NOT_TEXT = "\x00"
_REFERENCE = rf"(?:{LINK}|(?:[\w.-]+/[\w.-]+)?#\d+)"
FIXES = "Naprawia"
_LISTED = rf"\s+({_REFERENCE}(?:\s*(?:,|\bi\b|\boraz\b)\s*{_REFERENCE})*)"
REFERENCE = re.compile(_REFERENCE)
BLOCKS = frozenset({"blockquote", "details", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "p", "pre", "summary", "table"})
LIST_OR_PARAGRAPH = frozenset({"li", "ol", "p", "ul"})
EMPHASIS = frozenset({"em", "strong"})
HIDDEN = frozenset({"code", "del", "s", "strike"})
VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"})


class _Lines(HTMLParser):
    """Linie akapitów i punktów list w HTML opisu PR: ``LINK`` w miejscu linku do issue albo PR, ``NOT_TEXT`` w miejscu kodu, przekreślenia, obrazka i pola wyboru.

    Linię kończy ``<br>`` i początek albo koniec bloku z ``BLOCKS``, a każdy inny znacznik należy do linii. Linia
    trafia do ``lines`` tylko wtedy, gdy jej tekst zaczyna się wewnątrz samych ``LIST_OR_PARAGRAPH`` i ``EMPHASIS``,
    a najgłębszy z tych bloków to akapit albo punkt listy.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[list[str | LinkGithuba]] = []
        self._line: list[str | LinkGithuba] = []
        self._start: tuple[str, ...] | None = None
        self._open: list[str] = []
        self._link: LinkGithuba | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCKS or tag == "br":
            self._end_line()
        if tag in {"img", "input"} or (tag in HIDDEN and not self._hidden()):
            self._append(NOT_TEXT)
        elif tag == "a" and not self._hidden():
            self._link = github.link_githuba(attrs)
        if tag not in VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCKS:
            self._end_line()
        if tag in self._open:
            del self._open[len(self._open) - 1 - self._open[::-1].index(tag) :]
        if tag == "a" and self._link is not None:
            self._line.append(self._link)
            self._link = None

    def handle_data(self, data: str) -> None:
        if not self._hidden() and self._link is None:
            self._append(data)

    def _hidden(self) -> bool:
        return not HIDDEN.isdisjoint(self._open)

    def _append(self, part: str) -> None:
        if self._start is None and part.strip():
            self._start = tuple(self._open)
        self._line.append(part)

    def _end_line(self) -> None:
        blocks = [tag for tag in self._start or () if tag not in EMPHASIS]
        if blocks and blocks[-1] in {"p", "li"} and LIST_OR_PARAGRAPH.issuperset(blocks):
            self.lines.append(self._line)
        self._line, self._start = [], None
        if self._hidden():
            self._append(NOT_TEXT)  # kod albo przekreślenie przechodzi przez ``<br>`` na początek następnej linii


def fixed_issues(body: str, repository: str) -> tuple[int, ...]:
    """Numery issues ``repository`` z linii „Naprawia” opisu PR ``body`` wyrenderowanego przez GitHuba.

    Rzuca wyjątek, gdy GitHub opisu nie wyrenderował.
    """

    return listed_issues(github.html_markdownu(body, repository), repository, (FIXES,))


def listed_issues(html: str, repository: str, words: tuple[str, ...]) -> tuple[int, ...]:
    """Numery issues ``repository`` z list numerów po słowie z ``words`` na początku linii HTML opisu PR z renderera
    GitHuba, według tych samych reguł co „Naprawia” (docstring modułu)."""

    parser = _Lines()
    parser.feed(html)
    parser.close()
    pattern = re.compile(rf"\s*(?:{'|'.join(map(re.escape, words))}){_LISTED}")
    numbers: list[int] = []
    for line in parser.lines:
        listed = pattern.match("".join(LINK if isinstance(part, LinkGithuba) else part for part in line))
        links = iter(part for part in line if isinstance(part, LinkGithuba))
        for reference in REFERENCE.finditer(listed[1] if listed else ""):
            if reference[0] != LINK:
                if "/" in reference[0]:
                    break
                continue
            link = next(links)
            if not link.w(repository):
                break
            if link.rodzaj == "issue" and link.numer not in numbers:
                numbers.append(link.numer)
    return tuple(numbers)


def close_fixed(pull: Pull, *, merged: bool, merge_commit: str | None) -> str:
    """Zamyka otwarte issues z linii „Naprawia” i issues chwastów z linii „Korzeń z #N: R-KOD” z komentarzem o merge'u,
    a przed merge'em tylko je podaje."""

    words = [word for word, present in ((f"„{FIXES}”", FIXES in pull.body), (f"„{rejestr_korzeni.ROOT_WORDS}”", rejestr_korzeni.ROOT_WORDS in pull.body)) if present]
    if not words:
        return ""
    unchecked = f"nie zamknięto issues z {' i '.join(words)}, zamknij je ręcznie" if merged else f"nie sprawdzono {' i '.join(words)}"
    try:
        default_branch = github.domyslna_galaz(pull.repository)
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        return f" | UWAGA: GitHub nie podał domyślnej gałęzi, {unchecked}"
    if pull.base != default_branch:
        return f" | bez zamykania {' i '.join(words)}: baza {pull.base} to nie {default_branch}"
    try:
        html = github.html_markdownu(pull.body, pull.repository)
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        return f" | UWAGA: GitHub nie wyrenderował opisu PR, {unchecked}"
    fixes: dict[int, str | None] = {number: None for number in listed_issues(html, pull.repository, (FIXES,)) if number not in pull.closed_by_github}
    weeds = rejestr_korzeni.root_lines(szablon_werdyktu.items(html), pull.repository)
    fixes.update({link.numer: rejestr_korzeni.TITLE.format(code=code) for link, code in weeds if link.rodzaj == "issue" and link.numer not in fixes})
    closes = merged and merge_commit is not None
    open_issues, failed, other = [], [], []
    for number, title in fixes.items():
        try:
            issue = json.loads(github.gh("api", f"repos/{pull.repository}/issues/{number}"))
            if issue["state"] != "open":
                continue
            if title is not None and issue["title"] != title:
                other.append(f"#{number}")
                continue
            if closes:
                comment = f"Naprawione przez #{pull.number}, scalone jako {merge_commit}."
                github.gh("issue", "close", str(number), "--repo", pull.repository, "--comment", comment)
            open_issues.append(f"#{number}")
        except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
            failed.append(f"#{number}")
    if merged and not closes:
        missed = [*open_issues, *failed]
        return f" | UWAGA: GitHub nie podał commitu merge'a, nie zamknięto {', '.join(missed)}, zamknij ręcznie" if missed else ""
    done, warning = ("zamknięte", "UWAGA: nie zamknięto {}, zamknij ręcznie") if merged else (
        "po merge'u zamknie", "UWAGA: nie sprawdzono {}"
    )
    parts = [f"{done}: {', '.join(open_issues)}"] if open_issues else []
    parts += [warning.format(", ".join(failed))] if failed else []
    parts += [f"UWAGA: {', '.join(other)} z „{rejestr_korzeni.ROOT_WORDS}” to nie otwarte issue „Chwast: R-KOD” z tym kodem, nie zamknięte"] if other else []
    return "".join(f" | {part}" for part in parts)
