"""Treść pliku werdyktu pod dwiema pierwszymi liniami według szablonu ze skilla ``przeglad`` (ADR 0031, decyzja Q9).

Treść czyta renderer GitHuba (``github.html_markdownu``), jak opis PR przy „Naprawia”, więc to GitHub decyduje, co
jest nagłówkiem, akapitem, punktem listy i blokiem kodu (ogrodzonym ``` albo ~~~ i wciętym o cztery spacje). Pola
i nagłówki szablonu liczą się tylko poza blokami kodu: linia bloku kodu w Dowodzie to zawsze linia Dowodu, także
gdy zaczyna się od ``Korzeń:`` albo ``###``. Każdy blok i każda linia akapitu ma miejsce w szablonie, a każda inna
to odmowa:

- Ważne to nagłówek ``### W<n>. <zdanie>`` i linie akapitu z polami w tej kolejności: ``Gdzie: <plik:linia>``,
  ``Dowód: <tekst>`` z najwyżej 5 liniami treści po najwyżej 300 znaków (tekst pola ``Dowód:``, linie akapitu po nim
  i niepuste linie bloków kodu, do pola ``Korzeń:``), ``Korzeń: R-KOD - <zdanie>`` albo ``Korzeń: NOWY R-KOD -
  <opis>`` oraz ``Szczebel: (a) - <zdanie>`` ze szczeblem od ``(a)`` do ``(e)``; dłuższy dowód recenzent zapisuje
  w pliku obok werdyktu i podaje w Dowodzie jego ścieżkę;
- Drobne to nagłówek ``### D<n>. <zdanie>`` i jedna linia ``Gdzie: <plik:linia>``;
- Ważne stoją przed Drobnymi, numery idą od 1 bez przerw, a ich liczby zgadzają się z linią ``Znaleziska:``;
- na końcu ``## Sprawdzone`` z 1 do 5 niepustymi punktami listy, a po nich nic.

Inny blok (cytat, tabela, lista numerowana, lista w liście, ``<details>``, blok HTML i każdy, którego GitHub dopiero
zacznie używać) jest odmową, a linia pola poza blokiem kodu jest polem, więc cytowane pole bez bloku kodu nie
przechodzi i nie nadpisuje prawdziwego. ``PASS`` bez znalezisk ma więc tylko dwie pierwsze linie i ``## Sprawdzone``;
Drobne może mieć jak dotąd. Kod korzenia bez ``NOWY`` stoi na zamkniętej liście
``.agents/skills/przeglad/korzenie.toml`` na HEAD PR, a kod z ``NOWY`` ma postać kodu listy i na niej nie stoi
(decyzja Q18: recenzent nie dobiera najbliższego kodu, autor dopisuje nowy w swoim PR). NOWY kod musi być na liście
przed merge'em PR; pilnuje tego bramka korzenia (ADR 0031, PR 2). Listę z HEAD PR narzędzie czyta z Gita (HEAD
pobiera wywołujący), i tylko wtedy, gdy werdykt ma pole ``Korzeń:``; lista, której nie ma albo która się nie
wczytuje, to odmowa z przyczyną. Odmowa kończy się wzorem szablonu, który narzędzie bierze z bloku ``markdown``
sekcji „Postać werdyktu” skilla.

Szablon jest wdrożony od chwili, w której ADR 0031 wszedł do bazy PR (``deployed``): to data commitu, który na
``origin/<baza>`` dodał ADR, liczona po ``--first-parent``. Na ``main`` to commit merge'a PR wdrożenia, a nie commit
autora, który powstał przed merge'em, gdy szablon jeszcze nie działał. Na gałęzi stosu to commit z jej własnej
historii: scalenie ``main`` do niej albo commit autora, którego datę zmienia rebase. Na bazie, do której ADR jeszcze
nie wszedł, szablon nie obowiązuje (``None``). Chwila płynie z historii bazy, więc nie trzeba jej zgadywać przed
merge'em, a każdy checkout po pobraniu bazy dostaje tę samą; komentarzem, także edytowanym, nie da się jej przesunąć.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import re
import tomllib

from repo import REMOTE, ROOT
import repo
from stan_pr import Pull

LIST = ".agents/skills/przeglad/korzenie.toml"
ADR = "docs/adr/0031-korzen-po-fail-i-chwasty.md"
SKILL = ROOT / ".agents" / "skills" / "przeglad" / "SKILL.md"
CHECKED = "Sprawdzone"
MAX_CHECKED = 5
MAX_EVIDENCE = 5
MAX_EVIDENCE_CHARS = 300
CODE = re.compile(r"R-[A-Z0-9]+(?:-[A-Z0-9]+)*")
HEADING = re.compile(r"([WD])(\d+)\. (\S.*)")
ROOT_FIELD = re.compile(rf"Korzeń: (NOWY )?({CODE.pattern}) - (\S.*)")
RUNG_FIELD = re.compile(r"Szczebel: \(([a-e])\) - (\S.*)")
FIELDS = ("Gdzie:", "Dowód:", "Korzeń:", "Szczebel:")
ENTRY_KEYS = frozenset({"opis", "przyklad"})
QUOTE = "cytat z polem albo nagłówkiem w Dowodzie ujmij w blok kodu ```"
# Bloki, które GitHub stawia w punkcie listy: luźna lista owija tekst punktu w akapit, a każdy inny blok to odmowa.
_LOOSE_ITEM = "p"
_VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"})
_BLOCKS = frozenset({"blockquote", "details", "div", "dl", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "ol", "pre", "table", "ul"})


class CodesUnavailable(Exception):
    pass


@dataclass(frozen=True)
class _Root:
    label: str
    new: bool
    code: str


@dataclass(frozen=True)
class _Item:
    """Jedna jednostka treści: ``h2`` albo ``h3`` (nagłówek), ``line`` (linia akapitu), ``code`` (linia bloku kodu),
    ``point`` (punkt listy) albo nazwa innego bloku najwyższego poziomu, którego szablon nie zna."""

    kind: str
    text: str

    def shown(self) -> str:
        if self.kind in {"h2", "h3"}:
            return f"nagłówek „{'#' * int(self.kind[1])} {self.text}”"
        described = {"line": "linia", "code": "linia bloku kodu", "point": "punkt listy"}.get(self.kind, f"blok <{self.kind}>")
        return f"{described} „{self.text}”"


class _Items(HTMLParser):
    """Jednostki ``_Item`` HTML z renderera GitHuba w kolejności dokumentu: akapit dzieli ``<br>``, którym GitHub
    zastępuje koniec wiersza, a ``<pre>`` jego koniec wiersza; tekst znaczników wierszowych (kod, link, pogrubienie)
    należy do linii."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[_Item] = []
        self._open: list[str] = []
        self._text: list[str] = []
        self._nested: str | None = None  # blok wewnątrz punktu listy

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        top = self._open[0] if self._open else None
        if top is None:
            self._text = []
            if tag in _VOID:
                self.items.append(_Item(tag, ""))
                return
        elif top == "p" and tag == "br":
            self._line()
        elif top == "ul" and tag == "li" and len(self._open) == 1:
            self._text, self._nested = [], None
        elif top == "ul" and len(self._open) > 1 and tag in _BLOCKS | {_LOOSE_ITEM}:
            self._nested = self._nested or (tag if tag != _LOOSE_ITEM else None)
            self._text.append(" ")
        elif tag == "br":
            self._text.append(" ")
        if tag not in _VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._open:
            return
        del self._open[len(self._open) - 1 - self._open[::-1].index(tag) :]
        if self._open == ["ul"] and tag == "li":
            self.items.append(_Item(self._nested or "point", _joined(self._text)))
        elif not self._open:
            self._close(tag)

    def handle_data(self, data: str) -> None:
        if self._open:
            self._text.append(data)
        elif data.strip():
            self.items.append(_Item("tekst", data.strip()))

    def _line(self) -> None:
        if text := _joined(self._text):
            self.items.append(_Item("line", text))
        self._text = []

    def _close(self, tag: str) -> None:
        if tag == "p":
            self._line()
        elif tag == "pre":
            self.items.extend(_Item("code", line.rstrip()) for line in "".join(self._text).splitlines() if line.strip())
        elif tag != "ul":
            self.items.append(_Item(tag, _joined(self._text)))


def _joined(parts: Sequence[str]) -> str:
    return " ".join("".join(parts).split())


def _items(html: str) -> list[_Item]:
    parser = _Items()
    parser.feed(html)
    parser.close()
    return parser.items


def deployed(base: str) -> datetime | None:
    """Chwila wdrożenia szablonu na bazie ``base`` pobranej z ``origin``; ``None``, gdy ADR 0031 jeszcze do niej nie wszedł."""

    added = repo.git(ROOT, "log", "--first-parent", "--diff-filter=A", "--format=%cI", f"refs/remotes/{REMOTE}/{base}", "--", ADR).split()
    return datetime.fromisoformat(added[-1]) if added else None


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


def pull_codes(pull: Pull) -> frozenset[str]:
    """Kody listy na HEAD ``pull``, który wywołujący pobrał już z ``origin``."""

    if not repo.succeeds(ROOT, "cat-file", "-e", f"{pull.head}:{LIST}"):
        raise CodesUnavailable(f"HEAD PR {pull.head[:7]} nie ma listy {LIST}")
    try:
        return listed_codes(repo.git(ROOT, "show", f"{pull.head}:{LIST}"))
    except ValueError as error:
        raise CodesUnavailable(f"lista {LIST} na {pull.head[:7]} się nie wczytuje: {error}") from error


def template() -> str:
    """Wzór szablonu z bloku ``markdown`` sekcji „Postać werdyktu” skilla, w jednej linii."""

    section = SKILL.read_text(encoding="utf-8").partition("## Postać werdyktu\n")[2]
    block = section.partition("```markdown\n")[2].partition("\n```")[0]
    return " / ".join(line.strip() for line in block.splitlines() if line.strip())


def _value(item: _Item, field: str) -> str | None:
    """Tekst pola ``field`` w linii akapitu ``item``; ``None``, gdy to inne pole albo nie linia akapitu, a pusty
    napis, gdy pole jest puste."""

    return item.text.removeprefix(field).strip() if item.kind == "line" and item.text.startswith(field) else None


def _evidence(label: str, evidence: str, items: Sequence[_Item]) -> list[str]:
    problems = [f"{label}: w Dowodzie tylko linie tekstu i bloki kodu, a jest {item.shown()}" for item in items if item.kind not in {"line", "code"}]
    lines = [evidence] * bool(evidence) + [item.text for item in items if item.kind in {"line", "code"}]
    if not lines:
        problems.append(f"{label}: puste pole Dowód")
    elif len(lines) > MAX_EVIDENCE:
        problems.append(f"{label}: Dowód ma {len(lines)} linii, najwyżej {MAX_EVIDENCE}")
    problems.extend(
        f"{label}: linia Dowodu ma {len(line)} znaków, najwyżej {MAX_EVIDENCE_CHARS}; dłuższy dowód zapisz w pliku obok werdyktu i podaj w Dowodzie jego ścieżkę"
        for line in lines
        if len(line) > MAX_EVIDENCE_CHARS
    )
    return problems


def _major(label: str, block: Sequence[_Item], roots: list[_Root]) -> list[str]:
    order = f"{label}: pola w kolejności Gdzie, Dowód, Korzeń, Szczebel"
    where = _value(block[0], "Gdzie:") if block else None
    if where is None:
        return [f"{order}, a po nagłówku jest {block[0].shown() if block else 'koniec'}"]
    problems = [] if where else [f"{label}: puste pole Gdzie"]
    evidence = _value(block[1], "Dowód:") if len(block) > 1 else None
    if evidence is None:
        return [*problems, f"{order}, a po Gdzie jest {block[1].shown() if len(block) > 1 else 'koniec'}"]
    end = next((index for index, item in enumerate(block) if index > 1 and item.kind == "line" and item.text.startswith(FIELDS)), len(block))
    problems.extend(_evidence(label, evidence, block[2:end]))
    rest = list(block[end:])
    if not rest or _value(rest[0], "Korzeń:") is None:
        return [*problems, f"{order}, a po Dowodzie jest {rest[0].shown() if rest else 'koniec'} ({QUOTE})"]
    found = ROOT_FIELD.fullmatch(rest[0].text)
    if found is None:
        problems.append(f"{label}: „{rest[0].text}” to nie „Korzeń: R-KOD - zdanie” ani „Korzeń: NOWY R-KOD - opis”")
    else:
        roots.append(_Root(label, bool(found[1]), found[2]))
    if len(rest) < 2:
        return [*problems, f"{order}, a po Korzeniu jest koniec"]
    if rest[1].kind != "line" or RUNG_FIELD.fullmatch(rest[1].text) is None:
        problems.append(f"{label}: {rest[1].shown()} to nie „Szczebel: (a) - zdanie” ze szczeblem od (a) do (e)")
    return [*problems, *(f"{label}: po Szczeblu nic więcej, a jest {item.shown()}" for item in rest[2:])]


def _minor(label: str, block: Sequence[_Item]) -> list[str]:
    where = _value(block[0], "Gdzie:") if block else None
    if where is None:
        return [f"{label}: po nagłówku jedna linia „Gdzie: <plik:linia>”, a jest {block[0].shown() if block else 'koniec'}"]
    return [*([] if where else [f"{label}: puste pole Gdzie"]), *(f"{label}: Drobne ma tylko pole Gdzie, a jest {item.shown()}" for item in block[1:])]


def _root_problems(roots: Sequence[_Root], codes: Callable[[], frozenset[str]]) -> list[str]:
    if not roots:
        return []
    try:
        listed = codes()
    except CodesUnavailable as error:
        return [str(error)]
    problems = []
    for root in roots:
        if root.new and root.code in listed:
            problems.append(f"{root.label}: NOWY {root.code}: ten kod jest już na liście {LIST}, napisz go bez NOWY")
        elif not root.new and root.code not in listed:
            problems.append(f"{root.label}: kod {root.code} spoza listy {LIST}: użyj kodu z listy albo napisz „Korzeń: NOWY {root.code} - opis”")
    return problems


def problems(html: str, declared: tuple[int, int] | None, codes: Callable[[], frozenset[str]]) -> list[str]:
    """Co poprawić w treści werdyktu: ``html`` to HTML renderera GitHuba dla linii pod dwiema pierwszymi (pusty, gdy
    ich nie ma), ``declared`` liczby Ważnych i Drobnych z linii ``Znaleziska:`` (``None``, gdy jej nie ma), a
    ``codes`` czyta kody listy na HEAD PR, gdy jest pole Korzeń."""

    items = _items(html)
    found: list[str] = []
    roots: list[_Root] = []
    counts = {"W": 0, "D": 0}
    end = next((index for index, item in enumerate(items) if item.kind == "h2" and item.text == CHECKED), len(items))
    index = 0
    while index < end:
        heading = HEADING.fullmatch(items[index].text) if items[index].kind == "h3" else None
        if heading is None:
            found.append(f"{items[index].shown()} to nie nagłówek „### W<n>. <zdanie>”, „### D<n>. <zdanie>” ani „## {CHECKED}”")
            index += 1
            continue
        kind, label = heading[1], f"{heading[1]}{heading[2]}"
        if kind == "W" and counts["D"]:
            found.append(f"{label}: Ważne stoją przed Drobnymi")
        counts[kind] += 1
        if int(heading[2]) != counts[kind]:
            found.append(f"{label}: to {counts[kind]}. {'Ważne' if kind == 'W' else 'Drobne'}, więc {kind}{counts[kind]}")
        after = next((later for later in range(index + 1, end) if items[later].kind in {"h2", "h3"}), end)
        block = items[index + 1 : after]
        found.extend(_major(label, block, roots) if kind == "W" else _minor(label, block))
        index = after
    if declared is not None and (counts["W"], counts["D"]) != declared:
        found.append(f"w treści Ważne {counts['W']} i Drobne {counts['D']}, a linia Znaleziska mówi Ważne {declared[0]}, Drobne {declared[1]}")
    after_checked = items[end + 1 :]
    points = [item for item in after_checked if item.kind == "point"]
    if end == len(items):
        found.append(f"brak „## {CHECKED}” z 1–{MAX_CHECKED} punktami „- …” na końcu")
    elif not points or len(points) > MAX_CHECKED:
        found.append(f"„## {CHECKED}” ma {len(points)} punktów, a ma od 1 do {MAX_CHECKED}")
    found.extend(f"po „## {CHECKED}” tylko punkty „- …”, a jest {item.shown()}" for item in after_checked if item.kind != "point")
    found.extend(f"po „## {CHECKED}” pusty punkt listy" for item in points if not item.text)
    found.extend(_root_problems(roots, codes))
    return [*found, f"wzór ({SKILL.relative_to(ROOT).as_posix()}): {template()}"] if found else []
