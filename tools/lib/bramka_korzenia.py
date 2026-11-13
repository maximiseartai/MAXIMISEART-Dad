"""Bramka korzenia przed merge'em (ADR 0031, decyzje Q8, Q10, Q14, Q17, Q18, Q20, Q25, Q26): opis PR ma sekcję
``## Korzeń`` z blokiem na każde Ważne i każdy czerwony `main`, który PR naprawia, a każdy kod ``NOWY`` z werdyktów PR
stoi na liście korzeni na HEAD.

Bramka obowiązuje w wątku z szablonem werdyktu (``werdykt_pr.template_applies``, ta sama funkcja co przy publikacji
werdyktu i zgodzie na merge, decyzja Q20); wątek, który kończy po staremu, przechodzi ją bez sprawdzania. Sekcja jest
wymagana, gdy PR miał werdykt ``FAIL`` z Ważnym (dowolnego commitu) albo naprawia czerwony `main` (Q10, Q17). PR
naprawia czerwony `main`, gdy linia jego opisu zaczyna się od „Część” albo „Naprawia” z listą numerów, na której stoi
issue tego repozytorium z etykietą ``czerwony-main`` (``github.CZERWONY_MAIN``, zakłada je ``tools/ci/zgloszenia_ci.py``);
linię i listę czyta ``naprawia.listed_issues`` według tych samych reguł co „Naprawia”, a etykiety podaje ``gh api``.
Flaky test ma własne issue z etykietą ``flaky-test``, więc PR, który wskazuje tylko je, sekcji nie potrzebuje (Q10).
Opis bez słów „Część” i „Naprawia” i bez Ważnych bramka pomija bez pytania GitHuba.

Opis PR, werdykty, opis PR korzenia i sekcję „Co jest porażką” skilla ``przeglad`` czyta renderer GitHuba
(``github.html_markdownu``) przez ``szablon_werdyktu.items``, więc pola liczą się tylko poza blokami kodu, a cytat pola
w bloku kodu w Dowodzie nie psuje bloku. Sekcja to wszystko od pierwszego nagłówka ``## Korzeń`` do następnego nagłówka ``##``;
w niej tylko bloki ``###``, a w bloku tylko linie akapitu i (w Dowodzie) bloki kodu:

- nagłówek ``### W<n> r<k>: R-KOD`` dla Ważnego ``W<n>`` z werdyktu ``FAIL`` rundy ``k`` (``k``-ty werdykt PR, od 1,
  ``werdykt_pr.rounds``), z kodem z ostatniego werdyktu, który go dotyczy: z pola ``Korzeń:`` tego Ważnego albo
  z późniejszego punktu ``Korzeń W<n> r<k>: R-KOD - zdanie`` w „## Sprawdzone”, którym recenzent następnej rundy
  rozstrzyga kod zakwestionowany przez autora (Q25); Ważne werdyktu to ``W1`` … ``W<a>`` z linii ``Znaleziska:`` i każde
  ``### W<n>.`` jego treści, a Ważne bez kodu w szablonie dostaje kod tylko z takiego punktu;
- nagłówek ``### Czerwony main #<N>: R-KOD`` dla issue czerwonego `main` ``#N`` z linii „Część” albo „Naprawia”
  z kodem z listy na HEAD, który wybiera autor;
- potem ``Wyrwany w #M`` (link GitHuba do PR tego repozytorium) i nic więcej, albo ``Szczebel: (x) - mechanizm`` ze
  szczeblem od (a) do (e), przy szczeblu niższym niż (a) ``Wyżej nie, bo:`` z jedną linią ``(y) - zdanie`` na każdy
  wyższy szczebel, w kolejności drabiny (pierwsza może stać w linii pola), i na końcu ``Dowód:`` jak w szablonie
  werdyktu (``szablon_werdyktu.evidence_problems``: od 1 do 5 linii po najwyżej 300 znaków, bloki kodu się liczą).

Bloku brakującego, nadmiarowego, powtórzonego albo z innym kodem bramka odmawia. Szczebel (e) wymaga, żeby HEAD PR
dodał do sekcji „Co jest porażką” skilla ``przeglad`` punkt listy z linkiem GitHuba do PR tego repozytorium
(przykład), którego nie było na bazie scalenia z bazą PR (Q26). Granica: bramka sprawdza, że taki punkt przybył, a czy
opisuje ten korzeń i czy szczebel jest najwyższy działający, ocenia recenzent następnej rundy (Q2, Q7), tak jak treść
Dowodu, której narzędzie nie odtwarza. Rozmiaru wyrwania (Q8: ponad M według etykiety ``size:`` z
``tools/ci/rozmiar_pr.py`` idzie osobnym PR-em korzenia) bramka nie liczy, bo w jednym PR nie oddzieli linii korzenia
od linii funkcji.

``Wyrwany w #M`` przechodzi, gdy PR ``#M`` jest scalony (``gh pr view``), a jego opis ma linię akapitu albo punkt listy
``Korzeń z #N: R-KOD`` z linkiem GitHuba do tego PR i kodem bloku (Q14). Oba odwołania są linkami GitHuba, więc
GitHub pokazuje je na osi czasu obu PR-ów. Każdy kod ``NOWY`` z pól ``Korzeń:`` i punktów rozstrzygnięcia werdyktów PR
stoi na liście ``szablon_werdyktu.LIST`` na HEAD PR (Q18). Błąd GitHuba (renderer, ``gh api`` issue, ``gh pr view``)
to odmowa z przyczyną.

Odmowa podaje każdą brakującą rzecz, wzór sekcji z bloku ``markdown`` sekcji „Root section” skilla ``pr`` i to, że
opis poprawia ``gh pr edit N --body-file PLIK`` bez nowego commita i bez nowego werdyktu.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import re

import github
import naprawia
from repo import REMOTE, ROOT
import repo
from stan_pr import Pull
import szablon_werdyktu
from szablon_werdyktu import CODE, Item
import werdykt_pr

SECTION = "Korzeń"
PATTERN_SKILL = ROOT / ".agents" / "skills" / "pr" / "SKILL.md"
PATTERN_SECTION = "Root section"
FAILURES = "Co jest porażką"
REVIEW_SKILL = ".agents/skills/przeglad/SKILL.md"
RED_MAIN_WORDS = ("Część", naprawia.FIXES)
RUNGS = "abcde"
MAJOR_HEADING = re.compile(rf"(W\d+) r(\d+): ({CODE.pattern})")
RED_HEADING = re.compile(rf"Czerwony main #(\d+): ({CODE.pattern})")
UPROOTED = re.compile(r"Wyrwany w #(\d+)")
HIGHER = re.compile(r"\(([a-e])\) - (\S.*)")
ROOT_PR_LINE = re.compile(rf"Korzeń z #(\d+): ({CODE.pattern})")
WHY_NOT = "Wyżej nie, bo:"
EVIDENCE = "Dowód:"
PULL_REQUEST = "pull_request"


@dataclass(frozen=True)
class _Block:
    heading: str
    code: str
    items: tuple[Item, ...]


def problems(pull: Pull, deployed: datetime | None) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z bramki korzenia; ``deployed`` to chwila wdrożenia szablonu na bazie PR
    (``szablon_werdyktu.deployed``), a baza i HEAD PR są już pobrane z ``origin``."""

    if not werdykt_pr.template_applies(pull, deployed):
        return []
    try:
        rounds = werdykt_pr.rounds(pull)
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [f"korzeń: GitHub nie wyrenderował treści werdyktów ({error}), uruchom ponownie"]
    found: list[str] = []
    expected = _expected(rounds, found)
    found.extend(_new_codes(rounds, pull))
    if not expected and not any(word in pull.body for word in RED_MAIN_WORDS):
        return _refusal(found, pull)
    try:
        html = github.html_markdownu(pull.body, pull.repository)
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [*found, f"korzeń: GitHub nie wyrenderował opisu PR ({error}), uruchom ponownie"]
    red = _red_main(html, pull, found)
    expected.update({f"Czerwony main #{number}": None for number in red})
    if expected:
        found.extend(_section(szablon_werdyktu.items(html), expected, pull))
    return _refusal(found, pull)


def _expected(rounds: Sequence[werdykt_pr.Round], found: list[str]) -> dict[str, str | None]:
    """Nagłówki bloków ``W<n> r<k>`` każdego Ważnego werdyktów ``FAIL`` z kodem z ostatniego werdyktu, który go dotyczy."""

    codes: dict[str, str | None] = {}
    for current in rounds:
        if current.verdict.decision == "FAIL":
            labels = [*(f"W{index}" for index in range(1, (current.declared_majors or 0) + 1)), *(root.label for root in current.findings.majors)]
            codes.update(dict.fromkeys(f"{label} r{current.number}" for label in dict.fromkeys(labels)))
            codes.update({f"{root.label} r{current.number}": root.code for root in current.findings.majors if root.code is not None})
        for resolution in current.findings.resolutions:
            key = f"{resolution.label} r{resolution.round}"
            if key in codes:
                codes[key] = resolution.code
            else:
                found.append(f"korzeń: punkt „Korzeń {key}: {resolution.code}” werdyktu r{current.number} nie wskazuje Ważnego werdyktu FAIL tej albo wcześniejszej rundy")
    return codes


def _new_codes(rounds: Sequence[werdykt_pr.Round], pull: Pull) -> list[str]:
    new = sorted({root.code for current in rounds for root in (*current.findings.majors, *current.findings.resolutions) if root.new and root.code})
    if not new:
        return []
    try:
        listed = szablon_werdyktu.pull_codes(pull)
    except szablon_werdyktu.CodesUnavailable as error:
        return [f"korzeń: {error}"]
    return [f"korzeń: NOWY {code} z werdyktu nie stoi na liście {szablon_werdyktu.LIST} na HEAD: dopisz go z opisem i przykładem PR" for code in new if code not in listed]


def _red_main(html: str, pull: Pull, found: list[str]) -> list[int]:
    red = []
    for number in naprawia.listed_issues(html, pull.repository, RED_MAIN_WORDS):
        try:
            labels = {label["name"] for label in json.loads(github.gh("api", f"repos/{pull.repository}/issues/{number}"))["labels"]}
        except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
            found.append(f"korzeń: GitHub nie podał etykiet #{number}, więc nie wiadomo, czy to czerwony main ({error}), uruchom ponownie")
            continue
        if github.CZERWONY_MAIN in labels:
            red.append(number)
    return red


def _section(units: Sequence[Item], expected: dict[str, str | None], pull: Pull) -> list[str]:
    starts = [index for index, item in enumerate(units) if item.kind == "h2" and item.text == SECTION]
    missing = [f"brak bloku „### {heading}: {code or 'R-KOD'}”" for heading, code in expected.items()]
    if not starts:
        return [f"korzeń: brak sekcji „## {SECTION}”, a PR ma {_why(expected)}; {'; '.join(missing)}"]
    found: list[str] = []
    end = next((index for index in range(starts[0] + 1, len(units)) if units[index].kind == "h2"), len(units))
    blocks: dict[str, _Block] = {}
    index = starts[0] + 1
    while index < end:
        item = units[index]
        after = next((later for later in range(index + 1, end) if units[later].kind == "h3"), end)
        block = _heading(item, found)
        if block is not None:
            if block.heading in blocks:
                found.append(f"korzeń: blok „### {item.text}” powtórzony")
            blocks[block.heading] = _Block(block.heading, block.code, tuple(units[index + 1 : after]))
        index = after if item.kind == "h3" else index + 1
    for heading, code in expected.items():
        block = blocks.get(heading)
        if block is None:
            found.append(f"korzeń: brak bloku „### {heading}: {code or 'R-KOD'}”")
            continue
        if heading.startswith("W") and code is None:
            found.append(f"korzeń: {heading}: werdykt nie podaje kodu korzenia w szablonie, więc kod podaje recenzent następnej rundy punktem „Korzeń {heading}: R-KOD - zdanie” w „## Sprawdzone”")
        elif code is not None and block.code != code:
            found.append(
                f"korzeń: {heading}: kod {block.code}, a ostatni werdykt, który go dotyczy, podaje {code}; inny kod rozstrzyga recenzent następnej rundy punktem „Korzeń {heading}: R-KOD - zdanie” w „## Sprawdzone” (Q25)"
            )
        found.extend(_fields(block, pull))
    found.extend(f"korzeń: blok „### {heading}: {block.code}”, a PR nie ma takiego Ważnego ani czerwonego main" for heading, block in blocks.items() if heading not in expected)
    return found


def _why(expected: dict[str, str | None]) -> str:
    reasons = [*(["werdykt FAIL z Ważnym"] if any(heading.startswith("W") for heading in expected) else []), *(["naprawę czerwonego main"] if any(heading.startswith("Czerwony") for heading in expected) else [])]
    return " i ".join(reasons)


def _heading(item: Item, found: list[str]) -> _Block | None:
    """Blok bez treści z nagłówka ``###`` sekcji; inna jednostka przed blokiem albo nagłówek poza wzorem to przyczyna."""

    if item.kind != "h3":
        found.append(f"korzeń: w sekcji „## {SECTION}” przed blokiem jest {item.shown()}")
        return None
    if major := MAJOR_HEADING.fullmatch(item.text):
        return _Block(f"{major[1]} r{major[2]}", major[3], ())
    if red := RED_HEADING.fullmatch(item.text):
        return _Block(f"Czerwony main #{red[1]}", red[2], ())
    found.append(f"korzeń: nagłówek „### {item.text}” to nie „### W<n> r<runda>: R-KOD” ani „### Czerwony main #<issue>: R-KOD”")
    return None


def _links_to(item: Item, pull: Pull, number: int, kind: str | None) -> bool:
    return any(link.w(pull.repository) and link.numer == number and (kind is None or link.rodzaj == kind) for link in item.links)


def _line(item: Item | None, field: str) -> str | None:
    return item.text.removeprefix(field).strip() if item is not None and item.kind == "line" and item.text.startswith(field) else None


def _fields(block: _Block, pull: Pull) -> list[str]:
    label = f"korzeń: {block.heading}"
    units = list(block.items)
    first = units[0] if units else None
    if first is not None and first.kind == "line" and (uprooted := UPROOTED.fullmatch(first.text)):
        return [*(f"{label}: po „Wyrwany w #{uprooted[1]}” nic więcej, a jest {item.shown()}" for item in units[1:]), *_root_pull(block, first, int(uprooted[1]), pull)]
    rung = szablon_werdyktu.RUNG_FIELD.fullmatch(first.text) if first is not None and first.kind == "line" else None
    if rung is None:
        return [f"{label}: pierwsza linia bloku to „Szczebel: (a) - mechanizm” ze szczeblem od (a) do (e) albo „Wyrwany w #M”, a jest {first.shown() if first else 'koniec'}"]
    found = []
    evidence = next((index for index, item in enumerate(units) if _line(item, EVIDENCE) is not None), None)
    higher = RUNGS[: RUNGS.index(rung[1])]
    why = units[1 : evidence if evidence is not None else len(units)]
    if higher and _line(why[0] if why else None, WHY_NOT) is None:
        found.append(f"{label}: po Szczeblu ({rung[1]}) linia „{WHY_NOT} (a) - zdanie” z jedną linią na każdy wyższy szczebel {', '.join(f'({letter})' for letter in higher)}")
    elif higher:
        lines = [*([text] if (text := _line(why[0], WHY_NOT)) else []), *(item.text if item.kind == "line" else item.shown() for item in why[1:])]
        given = [found_rung[1] if (found_rung := HIGHER.fullmatch(line)) else line for line in lines]
        if given != list(higher):
            found.append(f"{label}: „{WHY_NOT}” ma jedną linię „(x) - zdanie” na każdy wyższy szczebel {', '.join(f'({letter})' for letter in higher)} po kolei, a ma: {' / '.join(lines) or 'nic'}")
    elif why:
        found.append(f"{label}: przy (a) nie ma wyższego szczebla, więc po Szczeblu tylko Dowód, a jest {why[0].shown()}")
    if evidence is None:
        return [*found, f"{label}: brak pola „{EVIDENCE} <polecenie i wynik>” na końcu bloku"]
    found.extend(szablon_werdyktu.evidence_problems(label, _line(units[evidence], EVIDENCE) or "", units[evidence + 1 :]))
    if rung[1] == "e":
        found.extend(_failure_point(block, pull))
    return found


def _root_pull(block: _Block, line: Item, number: int, pull: Pull) -> list[str]:
    label = f"korzeń: {block.heading}: Wyrwany w #{number}"
    if not _links_to(line, pull, number, PULL_REQUEST):
        return [f"{label} bez linku GitHuba do PR tego repo: napisz numer PR korzenia jako #{number}"]
    try:
        root = json.loads(github.gh("pr", "view", str(number), "--json", "state,body"))
    except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
        return [f"{label}: GitHub nie podał stanu PR ({error}), uruchom ponownie"]
    state = {"MERGED": None, "OPEN": "jest otwarty"}.get(root["state"], "jest zamknięty bez merge'a")
    found = [f"{label}: PR korzenia {state}, a scala się go przed tym PR"] if state else []
    try:
        units = szablon_werdyktu.items(github.html_markdownu(root["body"], pull.repository))
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [*found, f"{label}: GitHub nie wyrenderował opisu PR korzenia ({error}), uruchom ponownie"]
    if not any(_root_line(item, pull) == block.code for item in units):
        found.append(f"{label}: opis PR korzenia nie ma linii „Korzeń z #{pull.number}: {block.code}” z linkiem do tego PR")
    return found


def _root_line(item: Item, pull: Pull) -> str | None:
    """Kod z linii ``Korzeń z #N: R-KOD`` opisu PR korzenia, gdy ``#N`` to link GitHuba do ``pull``."""

    listed = ROOT_PR_LINE.fullmatch(item.text) if item.kind in {"line", "point"} else None
    return listed[2] if listed and int(listed[1]) == pull.number and _links_to(item, pull, pull.number, None) else None


def _failure_point(block: _Block, pull: Pull) -> list[str]:
    """Przyczyna, gdy HEAD PR nie dodał do „Co jest porażką” skilla ``przeglad`` punktu z linkiem do PR (szczebel (e))."""

    label = f"korzeń: {block.heading}: Szczebel (e)"
    try:
        base = repo.git(ROOT, "merge-base", f"refs/remotes/{REMOTE}/{pull.base}", pull.head).strip()
        before, after = (_points(repo.git(ROOT, "show", f"{commit}:{REVIEW_SKILL}"), pull) for commit in (base, pull.head))
    except Exception as error:  # noqa: BLE001 - każdy błąd Gita albo renderera to odmowa z przyczyną
        return [f"{label}: nie odczytano sekcji „{FAILURES}” skilla przeglad na bazie i HEAD ({error}), uruchom ponownie"]
    texts = {item.text for item in before}
    if any(item.text not in texts and any(link.w(pull.repository) and link.rodzaj == PULL_REQUEST for link in item.links) for item in after):
        return []
    return [f"{label} wymaga punktu z przykładem PR (#N) dopisanego w tym PR do sekcji „{FAILURES}” w {REVIEW_SKILL}"]


def _points(text: str, pull: Pull) -> list[Item]:
    units = szablon_werdyktu.items(github.html_markdownu(text, pull.repository))
    start = next((index for index, item in enumerate(units) if item.kind == "h2" and item.text == FAILURES), len(units))
    end = next((index for index in range(start + 1, len(units)) if units[index].kind == "h2"), len(units))
    return [item for item in units[start + 1 : end] if item.kind == "point"]


def _refusal(found: list[str], pull: Pull) -> list[str]:
    if not found:
        return []
    pattern = szablon_werdyktu.pattern(PATTERN_SKILL, PATTERN_SECTION)
    fix = f"opis popraw przez gh pr edit {pull.number} --body-file PLIK, bez nowego commita i bez nowego werdyktu"
    return [*found, f"wzór sekcji ({PATTERN_SKILL.relative_to(ROOT).as_posix()}): {pattern}; {fix}"]
