"""Treść pliku werdyktu pod dwiema pierwszymi liniami według szablonu ze skilla ``przeglad`` (ADR 0031, decyzja Q9).

Każda niepusta linia, bez odstępów na brzegach, ma miejsce w szablonie, a każda inna linia to odmowa:

- Ważne to nagłówek ``### W<n>. <zdanie>`` i pola w tej kolejności: ``Gdzie: <plik:linia>``, ``Dowód: <tekst>`` z
  najwyżej 5 liniami treści (linia ``Dowód:`` z tekstem i linie po niej do pola ``Korzeń:``), ``Korzeń: R-KOD -
  <zdanie>`` albo ``Korzeń: NOWY R-KOD - <opis>`` oraz ``Szczebel: (a) - <zdanie>`` ze szczeblem od ``(a)`` do ``(e)``;
- Drobne to nagłówek ``### D<n>. <zdanie>`` i jedna linia ``Gdzie: <plik:linia>``;
- Ważne stoją przed Drobnymi, numery idą od 1 bez przerw, a ich liczby zgadzają się z linią ``Znaleziska:``;
- na końcu ``## Sprawdzone`` z 1 do 5 punktami ``- <tekst>``, a po nich nic.

``PASS`` bez znalezisk ma więc tylko dwie pierwsze linie i ``## Sprawdzone``; Drobne może mieć jak dotąd.
Kod korzenia stoi na zamkniętej liście ``.agents/skills/przeglad/korzenie.toml`` na HEAD PR, a ``NOWY R-KOD`` przechodzi
tylko wtedy, gdy HEAD PR dodaje ten kod do listy względem merge-base z bazą. Listę z obu commitów narzędzie czyta
z Gita po pobraniu bazy i ``refs/pull/N/head`` z ``origin``, i tylko wtedy, gdy werdykt ma pole ``Korzeń:``. Odmowa
kończy się wzorem szablonu, który narzędzie bierze z bloku ``markdown`` sekcji „Postać werdyktu” skilla.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re
import tomllib

import github
from repo import ROOT
import repo
from stan_pr import Pull
import werdykt_scalenia

LIST = ".agents/skills/przeglad/korzenie.toml"
SKILL = ROOT / ".agents" / "skills" / "przeglad" / "SKILL.md"
CHECKED = "## Sprawdzone"
MAX_CHECKED = 5
MAX_EVIDENCE = 5
CODE = re.compile(r"R-[A-Z0-9]+(?:-[A-Z0-9]+)*")
HEADING = re.compile(r"### ([WD])(\d+)\. (\S.*)")
ROOT_FIELD = re.compile(rf"Korzeń: (NOWY )?({CODE.pattern}) - (\S.*)")
RUNG_FIELD = re.compile(r"Szczebel: \(([a-e])\) - (\S.*)")
POINT = re.compile(r"- (\S.*)")
FIELDS = ("Gdzie:", "Dowód:", "Korzeń:", "Szczebel:")
ENTRY_KEYS = frozenset({"opis", "przyklad"})


@dataclass(frozen=True)
class Codes:
    listed: frozenset[str]  # kody na liście HEAD PR
    added: frozenset[str]  # kody, które HEAD PR dodaje względem merge-base


class CodesUnavailable(Exception):
    pass


@dataclass(frozen=True)
class _Root:
    label: str
    new: bool
    code: str


def listed_codes(text: str) -> frozenset[str]:
    """Kody z treści listy korzeni; ``ValueError``, gdy wpis nie ma postaci kodu z ``opis`` i numerem PR ``przyklad``."""

    entries = tomllib.loads(text)
    for code, entry in entries.items():
        if CODE.fullmatch(code) is None:
            raise ValueError(f"„{code}” to nie kod R-WIELKIE-LITERY")
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ValueError(f"{code} ma mieć tylko pola opis i przyklad")
        if not isinstance(entry["opis"], str) or not entry["opis"].strip():
            raise ValueError(f"{code}: opis to jedno zdanie tekstu")
        if not isinstance(entry["przyklad"], int) or isinstance(entry["przyklad"], bool) or entry["przyklad"] < 1:
            raise ValueError(f"{code}: przyklad to numer PR")
    return frozenset(entries)


def _codes_at(commit: str) -> frozenset[str] | None:
    if not repo.succeeds(ROOT, "cat-file", "-e", f"{commit}:{LIST}"):
        return None
    try:
        return listed_codes(repo.git(ROOT, "show", f"{commit}:{LIST}"))
    except ValueError as error:
        raise CodesUnavailable(f"lista {LIST} na {commit[:7]} się nie wczytuje: {error}") from error


def pull_codes(pull: Pull) -> Codes:
    """Kody listy na HEAD ``pull`` i kody, które HEAD dodaje względem merge-base z bazą PR w ``origin``."""

    base = werdykt_scalenia.fetch(pull.base, [werdykt_scalenia.PullRequest(pull.number, pull.title, pull.head)])
    fork = repo.merge_base(ROOT, base, pull.head, timeout=github.LIMIT_S)
    listed = _codes_at(pull.head)
    if listed is None:
        raise CodesUnavailable(f"HEAD PR {pull.head[:7]} nie ma listy {LIST}")
    return Codes(listed, listed - (_codes_at(fork) or frozenset()))


def template() -> str:
    """Wzór szablonu z bloku ``markdown`` sekcji „Postać werdyktu” skilla, w jednej linii."""

    section = SKILL.read_text(encoding="utf-8").partition("## Postać werdyktu\n")[2]
    block = section.partition("```markdown\n")[2].partition("\n```")[0]
    return " / ".join(line.strip() for line in block.splitlines() if line.strip())


def _value(line: str, field: str) -> str | None:
    """Tekst pola ``field`` w ``line``; ``None``, gdy linia to inne pole, a pusty napis, gdy pole jest puste."""

    return line.removeprefix(field).strip() if line.startswith(field) else None


def _major(label: str, block: Sequence[str], roots: list[_Root]) -> list[str]:
    order = f"{label}: pola w kolejności Gdzie, Dowód, Korzeń, Szczebel"
    where = _value(block[0], "Gdzie:") if block else None
    if where is None:
        return [f"{order}, a po nagłówku jest {f'„{block[0]}”' if block else 'koniec'}"]
    problems = [] if where else [f"{label}: puste pole Gdzie"]
    evidence = _value(block[1], "Dowód:") if len(block) > 1 else None
    if evidence is None:
        return [*problems, f"{order}, a po Gdzie jest {f'„{block[1]}”' if len(block) > 1 else 'koniec'}"]
    end = next((index for index, line in enumerate(block) if index > 1 and line.startswith(FIELDS)), len(block))
    lines = [evidence] * bool(evidence) + list(block[2:end])
    if not lines:
        problems.append(f"{label}: puste pole Dowód")
    elif len(lines) > MAX_EVIDENCE:
        problems.append(f"{label}: Dowód ma {len(lines)} linii, najwyżej {MAX_EVIDENCE}")
    rest = list(block[end:])
    if not rest or not rest[0].startswith("Korzeń:"):
        return [*problems, f"{order}, a po Dowodzie jest {f'„{rest[0]}”' if rest else 'koniec'}"]
    found = ROOT_FIELD.fullmatch(rest[0])
    if found is None:
        problems.append(f"{label}: „{rest[0]}” to nie „Korzeń: R-KOD - zdanie” ani „Korzeń: NOWY R-KOD - opis”")
    else:
        roots.append(_Root(label, bool(found[1]), found[2]))
    if len(rest) < 2:
        return [*problems, f"{order}, a po Korzeniu jest koniec"]
    if RUNG_FIELD.fullmatch(rest[1]) is None:
        problems.append(f"{label}: „{rest[1]}” to nie „Szczebel: (a) - zdanie” ze szczeblem od (a) do (e)")
    return [*problems, *(f"{label}: po Szczeblu nic więcej, a jest „{line}”" for line in rest[2:])]


def _minor(label: str, block: Sequence[str]) -> list[str]:
    where = _value(block[0], "Gdzie:") if block else None
    if where is None:
        return [f"{label}: po nagłówku jedna linia „Gdzie: <plik:linia>”, a jest {f'„{block[0]}”' if block else 'koniec'}"]
    return [*([] if where else [f"{label}: puste pole Gdzie"]), *(f"{label}: Drobne ma tylko pole Gdzie, a jest „{line}”" for line in block[1:])]


def _root_problems(roots: Sequence[_Root], codes: Callable[[], Codes]) -> list[str]:
    if not roots:
        return []
    try:
        known = codes()
    except CodesUnavailable as error:
        return [str(error)]
    problems = []
    for root in roots:
        if root.new and root.code in known.listed - known.added:
            problems.append(f"{root.label}: {root.code} już jest na liście {LIST}, napisz „Korzeń: {root.code} - zdanie” bez NOWY")
        elif root.new and root.code not in known.added:
            problems.append(f"{root.label}: NOWY {root.code}, a HEAD PR nie dodaje go do listy {LIST}: dopisz kod do listy albo użyj istniejącego")
        elif not root.new and root.code not in known.listed:
            problems.append(f"{root.label}: kod {root.code} spoza listy {LIST}: dopisz kod do listy albo użyj istniejącego")
    return problems


def problems(lines: Sequence[str], declared: tuple[int, int] | None, codes: Callable[[], Codes]) -> list[str]:
    """Co poprawić w treści werdyktu: ``lines`` to niepuste linie pod dwiema pierwszymi, ``declared`` liczby Ważnych
    i Drobnych z linii ``Znaleziska:`` (``None``, gdy jej nie ma), a ``codes`` czyta listę kodów, gdy jest pole Korzeń."""

    found: list[str] = []
    roots: list[_Root] = []
    counts = {"W": 0, "D": 0}
    end = lines.index(CHECKED) if CHECKED in lines else len(lines)
    index = 0
    while index < end:
        heading = HEADING.fullmatch(lines[index])
        if heading is None:
            found.append(f"linia „{lines[index]}” to nie nagłówek „### W<n>. <zdanie>”, „### D<n>. <zdanie>” ani „{CHECKED}”")
            index += 1
            continue
        kind, label = heading[1], f"{heading[1]}{heading[2]}"
        if kind == "W" and counts["D"]:
            found.append(f"{label}: Ważne stoją przed Drobnymi")
        counts[kind] += 1
        if int(heading[2]) != counts[kind]:
            found.append(f"{label}: to {counts[kind]}. {'Ważne' if kind == 'W' else 'Drobne'}, więc {kind}{counts[kind]}")
        after = next((later for later in range(index + 1, end) if HEADING.fullmatch(lines[later])), end)
        block = lines[index + 1 : after]
        found.extend(_major(label, block, roots) if kind == "W" else _minor(label, block))
        index = after
    if declared is not None and (counts["W"], counts["D"]) != declared:
        found.append(f"w treści Ważne {counts['W']} i Drobne {counts['D']}, a linia Znaleziska mówi Ważne {declared[0]}, Drobne {declared[1]}")
    points = lines[end + 1 :]
    if end == len(lines):
        found.append(f"brak „{CHECKED}” z 1–{MAX_CHECKED} punktami „- …” na końcu")
    elif not points or len(points) > MAX_CHECKED:
        found.append(f"„{CHECKED}” ma {len(points)} punktów, a ma od 1 do {MAX_CHECKED}")
    found.extend(f"po „{CHECKED}” tylko punkty „- …”, a jest „{line}”" for line in points if POINT.fullmatch(line) is None)
    found.extend(_root_problems(roots, codes))
    return [*found, f"wzór ({SKILL.relative_to(ROOT).as_posix()}): {template()}"] if found else []
