"""Bramka korzenia przed merge'em (ADR 0031, decyzje Q8, Q10, Q14, Q17, Q18, Q20, Q25, Q26): opis PR ma sekcję
``## Korzeń`` z blokiem na każde Ważne i każdy czerwony `main`, który PR naprawia, a każdy kod ``NOWY`` z werdyktów PR
stoi na liście korzeni na HEAD.

Bramka obowiązuje od własnego wdrożenia, nie od wdrożenia szablonu (decyzja Q20: wątki, które już pracują, kończą
po swojemu): w wątku, którego najstarszy nieedytowany werdykt od konta z prawem zapisu nie powstał przed chwilą
wdrożenia bramki na bazie PR. Rozstrzyga to ta sama funkcja co dla szablonu, ``werdykt_pr.rule_applies``, z chwilą
``werdykt_pr.deployment`` dla pliku ``MARKER``: commitem merge'a (``--first-parent``), który dodał do bazy ten moduł.
Wyznacza go moduł, a nie sekcja „Root section” skilla ``pr``, bo moduł jest plikiem, który dodał PR wdrożenia bramki,
więc jego dodanie Git znajduje bez czytania treści, a sekcja to zmiana istniejącego pliku, którą zmieni każda późniejsza
poprawka wzoru. Bramka wchodzi po szablonie, więc wątek, w którym obowiązuje, ma też szablon; wątek, który kończy po
staremu, przechodzi ją bez sprawdzania. Sekcja jest
wymagana, gdy PR miał werdykt ``FAIL`` (dowolnego commitu) albo naprawia czerwony `main` (Q10, Q17). ``FAIL`` daje
tylko Ważne (skill ``przeglad``), więc sekcję wymaga sama decyzja ``FAIL``, także bez linii ``Znaleziska:`` albo
z ``Ważne 0`` (werdykt opublikowany poza ``--werdykt``). PR
naprawia czerwony `main`, gdy linia jego opisu zaczyna się od „Część” albo „Naprawia” z listą numerów, na której stoi
issue tego repozytorium z etykietą ``czerwony-main`` (``github.CZERWONY_MAIN``, zakłada je ``tools/ci/zgloszenia_ci.py``);
linię i listę czyta ``naprawia.listed_issues`` według tych samych reguł co „Naprawia”, a etykiety podaje ``gh api``.
Granica: PR naprawy, który wskazuje issue inaczej (np. „Część: #N” albo „Naprawia czerwony main #N”), bramka liczy jak
PR bez naprawy czerwonego `main`; linię „Część #N” każe pisać ``docs/agents/pr-i-ci.md`` i skill ``pr``, a jej brak
łapie recenzent.
Flaky test ma własne issue z etykietą ``flaky-test``, więc PR, który wskazuje tylko je, sekcji nie potrzebuje (Q10).
Opis bez słów „Część” i „Naprawia” i bez werdyktu ``FAIL`` bramka pomija bez pytania GitHuba.

Kod korzenia to kategoria i niczego nie blokuje ([ADR 0036](../../docs/adr/0036-chwast-to-regula.md)): bramka nie
porównuje szczebla bloku z wcześniejszymi wyrwaniami tego kodu w innych PR-ach i nie czyta zgód.

Opis PR, werdykty, opis PR korzenia i sekcję „Co jest porażką” skilla ``przeglad`` czyta renderer GitHuba
(``github.html_markdownu``) przez ``szablon_werdyktu.items``, więc pola liczą się tylko poza blokami kodu, a cytat pola
w bloku kodu w Dowodzie nie psuje bloku. Sekcja to wszystko od pierwszego nagłówka ``## Korzeń`` do następnego nagłówka ``##``;
w niej tylko bloki ``###``, a w bloku tylko linie akapitu i (w Dowodzie) bloki kodu:

- nagłówek ``### W<n> r<k>: R-KOD`` dla Ważnego ``W<n>`` z werdyktu ``FAIL`` rundy ``k`` (``k``-ty werdykt PR, od 1,
  ``werdykt_pr.rounds``), z kodem z ostatniego werdyktu, który go dotyczy: z pola ``Korzeń:`` tego Ważnego albo
  z późniejszego punktu ``Korzeń W<n> r<k>: R-KOD - zdanie`` w „## Sprawdzone”, którym recenzent następnej rundy
  rozstrzyga kod zakwestionowany przez autora (Q25); Ważne werdyktu to ``W1`` … ``W<a>`` z linii ``Znaleziska:``
  (co najmniej ``W1``) i każde ``### W<n>.`` jego treści, a Ważne bez kodu w szablonie dostaje kod tylko z takiego
  punktu;
- nagłówek ``### Czerwony main #<N>: R-KOD`` dla issue czerwonego `main` ``#N`` z linii „Część” albo „Naprawia”
  z kodem, który wybiera autor;
- potem ``Wyrwany w #M`` (link GitHuba do PR tego repozytorium) i nic więcej, albo ``Szczebel: (x) - mechanizm`` ze
  szczeblem od (a) do (e), przy szczeblu niższym niż (a) ``Wyżej nie, bo:`` z jedną linią ``(y) - zdanie`` na każdy
  wyższy szczebel, w kolejności drabiny (pierwsza może stać w linii pola), i na końcu ``Dowód:`` jak w szablonie
  werdyktu (``szablon_werdyktu.evidence_problems``: od 1 do 5 linii po najwyżej 300 znaków, bloki kodu się liczą).

Bloku brakującego, nadmiarowego, powtórzonego albo z innym kodem bramka odmawia. Szczebel (e) wymaga, żeby HEAD PR
dopisał do sekcji „Co jest porażką” skilla ``przeglad`` nowy punkt listy z linkiem GitHuba do tego PR (przykład),
a pozostałe punkty zostawił jak na bazie scalenia z bazą PR (Q26), więc zmieniony punkt bazy nie jest nowym punktem.
Granica: bramka sprawdza, że taki punkt przybył, a czy
opisuje ten korzeń i czy szczebel jest najwyższy działający, ocenia recenzent następnej rundy (Q2, Q7), tak jak treść
Dowodu, której narzędzie nie odtwarza. Rozmiaru wyrwania (Q8: ponad M według etykiety ``size:`` z
``tools/ci/rozmiar_pr.py`` idzie osobnym PR-em korzenia) bramka nie liczy, bo w jednym PR nie oddzieli linii korzenia
od linii funkcji: czy wyrwanie mieści się w PR, czy idzie do PR korzenia, rozstrzyga recenzent według skilla
``przeglad``.

``Wyrwany w #M`` przechodzi, gdy PR ``#M`` jest scalony do domyślnej gałęzi repozytorium (``gh pr view``, baza PR
równa ``github.domyslna_galaz``), a jego opis ma linię akapitu albo punkt listy ``Korzeń z #N: R-KOD`` z linkiem
GitHuba do tego PR i kodem bloku (Q14). Oba odwołania są linkami GitHuba, więc GitHub pokazuje je na osi czasu obu
PR-ów. Każdy kod bramki stoi na liście ``szablon_werdyktu.LIST`` na HEAD PR (Q18): kod nagłówka każdego bloku sekcji
(``W<n> r<k>`` i ``Czerwony main #N``) i każdy kod ``NOWY`` z pól ``Korzeń:`` i punktów rozstrzygnięcia werdyktów PR.
Sprawdza je jedna funkcja, ``_unlisted``, bo kod bloku Ważnego z werdyktu opublikowanego poza ``--werdykt`` nie przeszedł
kontroli listy przy publikacji, a kod bloku czerwonego `main` nie przechodzi jej nigdzie indziej. Błąd GitHuba
(renderer, ``gh api`` issue, ``gh pr view``, ``gh repo view``) to odmowa z przyczyną.

Odmowa podaje każdą brakującą rzecz, wzór sekcji z bloku ``markdown`` sekcji „Root section” skilla ``pr`` i to, że
opis poprawia ``gh pr edit N --body-file PLIK`` bez nowego commita i bez nowego werdyktu.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json
import re

import github
import naprawia
import rejestr_korzeni
from rejestr_korzeni import SECTION, Block
from repo import REMOTE, ROOT
import repo
from stan_pr import Pull
import szablon_werdyktu
from szablon_werdyktu import Item
import werdykt_pr

MARKER = "tools/lib/bramka_korzenia.py"  # plik, którego dodanie do bazy PR to chwila wdrożenia bramki (werdykt_pr.deployment)
PATTERN_SKILL = ROOT / ".agents" / "skills" / "pr" / "SKILL.md"
PATTERN_SECTION = "Root section"
FAILURES = "Co jest porażką"
REVIEW_SKILL = ".agents/skills/przeglad/SKILL.md"
RED_MAIN_WORDS = ("Część", naprawia.FIXES)
RUNGS = "abcde"
HIGHER = re.compile(r"\(([a-e])\) - (\S.*)")
WHY_NOT = "Wyżej nie, bo:"
EVIDENCE = "Dowód:"
PULL_REQUEST = "pull_request"


def problems(pull: Pull, deployed: datetime | None) -> list[str]:
    """Przyczyny odmowy merge'a ``pull`` z bramki korzenia; ``deployed`` to chwila wdrożenia bramki na bazie PR
    (``werdykt_pr.deployment`` z ``MARKER``), a baza i HEAD PR są już pobrane z ``origin``."""

    if not werdykt_pr.rule_applies(pull, deployed):
        return []
    try:
        rounds = werdykt_pr.rounds(pull, werdykt_pr.rendered(pull))
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [f"korzeń: GitHub nie wyrenderował treści werdyktów ({error}), uruchom ponownie"]
    found: list[str] = []
    expected = {heading: major.code for heading, major in _expected(rounds, found).items()}
    codes = {code: ["NOWY z werdyktu"] for code in _new_codes(rounds)}
    if expected or any(word in pull.body for word in RED_MAIN_WORDS):
        found.extend(_described(pull, expected, codes))
    found.extend(_unlisted(codes, pull))
    return _refusal(found, pull)


def _described(pull: Pull, expected: dict[str, str | None], codes: dict[str, list[str]]) -> list[str]:
    """Przyczyny z opisu PR: czerwony `main` z linii „Część” i „Naprawia” i sekcja ``## Korzeń``, której kody bloków
    trafiają do ``codes``."""

    try:
        html = github.html_markdownu(pull.body, pull.repository)
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [f"korzeń: GitHub nie wyrenderował opisu PR ({error}), uruchom ponownie"]
    found: list[str] = []
    expected.update({f"Czerwony main #{number}": None for number in _red_main(html, pull, found)})
    if expected:
        found.extend(_section(szablon_werdyktu.items(html), expected, pull, codes))
    return found


def _expected(rounds: Sequence[werdykt_pr.Round], found: list[str]) -> dict[str, rejestr_korzeni.Major]:
    """Nagłówki bloków ``W<n> r<k>`` każdego Ważnego werdyktów ``FAIL`` z kodem z ostatniego werdyktu, który go dotyczy
    (``rejestr_korzeni.majors``, z którego tak samo czyta rejestr korzeni)."""

    majors, strays = rejestr_korzeni.majors(rounds)
    found.extend(
        f"korzeń: punkt „Korzeń {resolution.label} r{resolution.round}: {resolution.code}” werdyktu r{number} nie wskazuje Ważnego werdyktu FAIL tej albo wcześniejszej rundy"
        for number, resolution in strays
    )
    return majors


def _new_codes(rounds: Sequence[werdykt_pr.Round]) -> list[str]:
    return sorted({root.code for current in rounds for root in (*current.findings.majors, *current.findings.resolutions) if root.new and root.code})


def _unlisted(codes: dict[str, list[str]], pull: Pull) -> list[str]:
    """Jedyna kontrola listy korzeni bramki: każdy kod ``codes`` (``NOWY`` z werdyktów i kod nagłówka każdego bloku
    sekcji, z miejscami, w których stoi) stoi na liście ``szablon_werdyktu.LIST`` na HEAD PR."""

    if not codes:
        return []
    try:
        listed = szablon_werdyktu.pull_codes(pull)
    except szablon_werdyktu.CodesUnavailable as error:
        return [f"korzeń: {error}"]
    return [
        f"korzeń: kod {code} ({', '.join(where)}) nie stoi na liście {szablon_werdyktu.LIST} na HEAD: użyj kodu z listy albo dopisz go z opisem i przykładem PR"
        for code, where in sorted(codes.items())
        if code not in listed
    ]


def _red_main(html: str, pull: Pull, found: list[str]) -> list[int]:
    """Issues czerwonego `main` z linii „Część” i „Naprawia”."""

    red: list[int] = []
    for number in naprawia.listed_issues(html, pull.repository, RED_MAIN_WORDS):
        try:
            issue = json.loads(github.gh("api", f"repos/{pull.repository}/issues/{number}"))
        except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
            found.append(f"korzeń: GitHub nie podał etykiet #{number}, więc nie wiadomo, czy to czerwony main ({error}), uruchom ponownie")
            continue
        if github.CZERWONY_MAIN in {label["name"] for label in issue["labels"]}:
            red.append(number)
    return red


def _section(units: Sequence[Item], expected: dict[str, str | None], pull: Pull, codes: dict[str, list[str]]) -> list[str]:
    parsed = rejestr_korzeni.section(units)
    missing = [f"brak bloku „### {heading}: {code or 'R-KOD'}”" for heading, code in expected.items()]
    if parsed is None:
        return [f"korzeń: brak sekcji „## {SECTION}”, a PR ma {_why(expected)}; {'; '.join(missing)}"]
    found = [
        f"korzeń: w sekcji „## {SECTION}” przed blokiem jest {item.shown()}"
        if item.kind != "h3"
        else f"korzeń: nagłówek „### {item.text}” to nie „### W<n> r<runda>: R-KOD” ani „### Czerwony main #<issue>: R-KOD”"
        for item in parsed.strays
    ]
    blocks: dict[str, Block] = {}
    for block in parsed.blocks:
        codes.setdefault(block.code, []).append(f"blok „### {block.heading}”")
        if block.heading in blocks:
            found.append(f"korzeń: blok „### {block.heading}: {block.code}” powtórzony")
        blocks[block.heading] = block
    for heading, code in expected.items():
        expected_block = blocks.get(heading)
        if expected_block is None:
            found.append(f"korzeń: brak bloku „### {heading}: {code or 'R-KOD'}”")
            continue
        block = expected_block
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


def _links_to(item: Item, pull: Pull, number: int, kind: str | None) -> bool:
    return any(link.w(pull.repository) and link.numer == number and (kind is None or link.rodzaj == kind) for link in item.links)


def _line(item: Item | None, field: str) -> str | None:
    return item.text.removeprefix(field).strip() if item is not None and item.kind == "line" and item.text.startswith(field) else None


def _fields(block: Block, pull: Pull) -> list[str]:
    label = f"korzeń: {block.heading}"
    units = list(block.items)
    first = units[0] if units else None
    if first is not None and (uprooted := block.uprooted()) is not None:
        return [*(f"{label}: po „Wyrwany w #{uprooted}” nic więcej, a jest {item.shown()}" for item in units[1:]), *_root_pull(block, first, uprooted, pull)]
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
    return [*found, *(_failure_point(block, pull) if rung[1] == "e" else [])]


def _root_pull(block: Block, line: Item, number: int, pull: Pull) -> list[str]:
    label = f"korzeń: {block.heading}: Wyrwany w #{number}"
    if not _links_to(line, pull, number, PULL_REQUEST):
        return [f"{label} bez linku GitHuba do PR tego repo: napisz numer PR korzenia jako #{number}"]
    try:
        root = json.loads(github.gh("pr", "view", str(number), "--json", "state,body,baseRefName"))
    except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
        return [f"{label}: GitHub nie podał stanu PR ({error}), uruchom ponownie"]
    found = _root_merged(label, root, pull)
    try:
        units = szablon_werdyktu.items(github.html_markdownu(root["body"], pull.repository))
    except Exception as error:  # noqa: BLE001 - każdy błąd renderera to odmowa z przyczyną
        return [*found, f"{label}: GitHub nie wyrenderował opisu PR korzenia ({error}), uruchom ponownie"]
    if not any(link.numer == pull.number and code == block.code for link, code in rejestr_korzeni.root_lines(units, pull.repository)):
        found.append(f"{label}: opis PR korzenia nie ma linii „Korzeń z #{pull.number}: {block.code}” z linkiem do tego PR")
    return found


def _root_merged(label: str, root: dict[str, str], pull: Pull) -> list[str]:
    """Przyczyna, gdy PR korzenia ``root`` (``gh pr view`` ze stanem i bazą) nie jest scalony do domyślnej gałęzi."""

    if root["state"] != "MERGED":
        state = "jest otwarty" if root["state"] == "OPEN" else "jest zamknięty bez merge'a"
        return [f"{label}: PR korzenia {state}, a scala się go do domyślnej gałęzi przed tym PR"]
    try:
        default = github.domyslna_galaz(pull.repository)
    except Exception as error:  # noqa: BLE001 - każdy błąd GitHuba to odmowa z przyczyną
        return [f"{label}: GitHub nie podał domyślnej gałęzi repozytorium ({error}), uruchom ponownie"]
    if root["baseRefName"] != default:
        return [f"{label}: PR korzenia scalony do {root['baseRefName']}, a nie do domyślnej gałęzi {default}"]
    return []


def _failure_point(block: Block, pull: Pull) -> list[str]:
    """Przyczyna, gdy HEAD PR nie dopisał do „Co jest porażką” skilla ``przeglad`` nowego punktu z linkiem do tego PR
    (szczebel (e)): punkty HEAD bez linku do tego PR to dokładnie punkty bazy, w tej samej kolejności, a co najmniej
    jeden punkt HEAD ma ten link. Punkt z bazy zmieniony w PR (przeredagowany, przeniesiony, z dopisanym linkiem) nie
    jest więc nowym punktem."""

    label = f"korzeń: {block.heading}: Szczebel (e)"
    try:
        base = repo.git(ROOT, "merge-base", f"refs/remotes/{REMOTE}/{pull.base}", pull.head).strip()
        before, after = (_points(repo.git(ROOT, "show", f"{commit}:{REVIEW_SKILL}"), pull) for commit in (base, pull.head))
    except Exception as error:  # noqa: BLE001 - każdy błąd Gita albo renderera to odmowa z przyczyną
        return [f"{label}: nie odczytano sekcji „{FAILURES}” skilla przeglad na bazie i HEAD ({error}), uruchom ponownie"]
    kept = [item.text for item in after if not _links_to(item, pull, pull.number, PULL_REQUEST)]
    if len(kept) < len(after) and kept == [item.text for item in before]:
        return []
    return [
        f"{label} wymaga nowego punktu z linkiem do tego PR (#{pull.number}) dopisanego w tym PR do sekcji „{FAILURES}” w {REVIEW_SKILL}, "
        "a pozostałe punkty sekcji zostają jak na bazie: zmieniony punkt z bazy to nie nowy punkt"
    ]


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
