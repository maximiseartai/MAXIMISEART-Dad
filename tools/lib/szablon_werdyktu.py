"""Treść pliku werdyktu pod dwiema pierwszymi liniami według szablonu ze skilla ``przeglad`` (ADR 0031, decyzja Q9).

Treść czyta renderer GitHuba (``github.html_markdownu``; rejestr korzeni bierze ten sam HTML z pola ``bodyHTML``
GraphQL), jak opis PR przy „Naprawia”, więc to GitHub decyduje, co jest nagłówkiem, akapitem, punktem listy
i blokiem kodu (ogrodzonym ``` albo ~~~ i wciętym o cztery spacje). Pola i nagłówki szablonu liczą się tylko poza
blokami kodu: linia bloku kodu w Dowodzie to zawsze linia Dowodu, także gdy zaczyna się od ``Korzeń:`` albo ``###``.
Każdy blok i każda linia akapitu ma miejsce w szablonie, a każda inna to odmowa:

- Ważne to nagłówek ``### W<n>. <zdanie>`` i linie akapitu z polami w tej kolejności: ``Gdzie: <plik:linia>``,
  ``Dowód: <tekst>`` z najwyżej 5 liniami treści po najwyżej 300 znaków (tekst pola ``Dowód:``, linie akapitu po nim
  i niepuste linie bloków kodu, do pola ``Korzeń:``), ``Korzeń: R-KOD - <zdanie>`` albo ``Korzeń: NOWY R-KOD -
  <opis>`` oraz ``Szczebel: (a) - <zdanie>`` ze szczeblem od ``(a)`` do ``(e)``; dłuższy dowód recenzent zapisuje
  w pliku obok werdyktu i podaje w Dowodzie jego ścieżkę; po Szczeblu może stać jeszcze pole ``Idiom:`` w jednej
  z trzech postaci z [ADR 0036](../../docs/adr/0036-chwast-to-regula.md): ``Idiom: <id> jak #N W<n> r<k>`` (drugie
  wystąpienie idiomu bez reguły, ``<id>`` to reguła, którą PR ma dodać), ``Idiom: <id>`` (ucieczka istniejącej reguły
  ``<id>``) albo ``Idiom: bez reguły <klasa> jak #N W<n> r<k>`` z klasą z zamkniętej listy ``CLASSES``; ``<id>`` to
  pole ``id`` reguły ast-grep, klucz ``banned-api`` albo ``id`` kontraktu import-linter, bez spacji (``RULE_ID``);
- Drobne to nagłówek ``### D<n>. <zdanie>`` i jedna linia ``Gdzie: <plik:linia>``;
- Ważne stoją przed Drobnymi, numery idą od 1 bez przerw, a ich liczby zgadzają się z linią ``Znaleziska:``;
- na końcu ``## Sprawdzone`` z 1 do 5 niepustymi punktami listy, a po nich nic; punkt, który zaczyna się od
  ``Korzeń ``, to rozstrzygnięcie ``Korzeń W<n> r<k>: R-KOD - zdanie`` albo ``Korzeń W<n> r<k>: NOWY R-KOD - opis``,
  którym recenzent następnej rundy podaje kod Ważnego ``W<n>`` z rundy ``k`` (decyzja Q25).

Inny blok (cytat, tabela, lista numerowana, lista w liście, ``<details>``, blok HTML i każdy, którego GitHub dopiero
zacznie używać) jest odmową, a linia pola poza blokiem kodu jest polem, więc cytowane pole bez bloku kodu nie
przechodzi i nie nadpisuje prawdziwego. ``PASS`` bez znalezisk ma więc tylko dwie pierwsze linie i ``## Sprawdzone``;
Drobne może mieć jak dotąd. Kod korzenia bez ``NOWY`` stoi na zamkniętej liście
``.agents/skills/przeglad/korzenie.toml`` na HEAD PR, a kod z ``NOWY`` ma postać kodu listy i na niej nie stoi
(decyzja Q18: recenzent nie dobiera najbliższego kodu, autor dopisuje nowy w swoim PR); ten sam warunek ma kod punktu
rozstrzygnięcia. NOWY kod musi być na liście przed merge'em PR (``bramka_korzenia``). Listę z HEAD PR narzędzie czyta
z Gita (HEAD pobiera wywołujący), i tylko wtedy, gdy werdykt ma pole ``Korzeń:`` albo punkt rozstrzygnięcia; lista, której nie ma albo która się nie
wczytuje, to odmowa z przyczyną. Odmowa kończy się wzorem szablonu, który narzędzie bierze z bloku ``markdown``
sekcji „Postać werdyktu” skilla.

Szablon jest wdrożony od chwili, w której ADR 0031 (``ADR``) wszedł do bazy PR, a czy obowiązuje w wątku,
rozstrzyga ``werdykt_pr.rule_applies`` z chwilą ``werdykt_pr.deployment`` (decyzja Q20).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import tomllib

import github
from repo import ROOT
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
# Pole ``Idiom:`` Ważnego (ADR 0036, „Pole werdyktu”): id reguły, klasa idiomu bez reguły i wcześniejsze Ważne ``jak``.
CLASSES = ("brak-testu", "stan-kroku")
RULE_ID = r"[\w.-]+"
_EARLIER = r" jak #(\d+) (W\d+) r(\d+)"
IDIOM_LIKE = re.compile(rf"Idiom: ({RULE_ID}){_EARLIER}")
IDIOM_ESCAPE = re.compile(rf"Idiom: ({RULE_ID})")
IDIOM_NO_RULE = re.compile(rf"Idiom: bez reguły ({'|'.join(CLASSES)}){_EARLIER}")
# Punkt „## Sprawdzone”, którym recenzent rozstrzyga kod Ważnego z wcześniejszej rundy (decyzja Q25).
RESOLUTION = re.compile(rf"Korzeń (W\d+) r(\d+): (NOWY )?({CODE.pattern}) - (\S.*)")
RESOLUTION_START = "Korzeń "
FIELDS = ("Gdzie:", "Dowód:", "Korzeń:", "Szczebel:", "Idiom:")
# ``plik:linia`` albo ``plik:linia-linia`` pola ``Gdzie:`` (``places``).
PLACE = re.compile(r"(?<![\w./:-])((?:[\w.-]+/)+[\w.-]*\w|[\w-][\w.-]*\.[A-Za-z]\w*):(\d+)(?:[-–](\d+))?(?!\d)")
ENTRY_KEYS = frozenset({"opis", "przyklad"})
QUOTE = "cytat z polem albo nagłówkiem w Dowodzie ujmij w blok kodu ```"
IDIOM_FORMS = f"Idiom: <id> jak #N W<n> r<k>”, „Idiom: <id>” ani „Idiom: bez reguły <{'|'.join(CLASSES)}> jak #N W<n> r<k>"
# Bloki, które GitHub stawia w punkcie listy: luźna lista owija tekst punktu w akapit, a każdy inny blok to odmowa.
_LOOSE_ITEM = "p"
_VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"})
# Osłona, w którą HTML treści z GraphQL (``bodyHTML``) owija blok kodu ``<pre>`` (przycisk kopiowania), a renderer
# ``POST /markdown`` nie: parser ją pomija, więc oba HTML dają te same jednostki.
SNIPPET = "snippet-clipboard-content"
_BLOCKS = frozenset({"blockquote", "details", "div", "dl", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "ol", "pre", "table", "ul"})


class CodesUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Root:
    """Kod korzenia Ważnego ``label`` (``W1``) z pola ``Korzeń:`` albo, z ``round``, z punktu rozstrzygnięcia
    ``Korzeń W1 r2: …`` w „## Sprawdzone”; ``code`` to ``None``, gdy Ważne nie ma pola ``Korzeń:`` w postaci szablonu."""

    label: str
    new: bool
    code: str | None
    round: int | None = None


@dataclass(frozen=True)
class Idiom:
    """Pole ``Idiom:`` Ważnego ``label``: ``rule`` to id reguły (``None`` w postaci ``bez reguły``), ``klass`` klasa
    idiomu bez reguły (``None`` z regułą), a ``like`` wcześniejsze Ważne z ``jak #N W<n> r<k>``: PR, Ważne i runda
    (``None`` w postaci ``Idiom: <id>``, czyli przy ucieczce istniejącej reguły)."""

    label: str
    rule: str | None
    klass: str | None
    like: tuple[int, str, int] | None


@dataclass(frozen=True)
class Findings:
    """Kody korzeni z treści werdyktu: ``majors`` po jednym na Ważne w kolejności, ``resolutions`` z punktów
    rozstrzygnięcia w „## Sprawdzone”, a ``idioms`` z pól ``Idiom:`` Ważnych, które je mają."""

    majors: tuple[Root, ...]
    resolutions: tuple[Root, ...]
    idioms: tuple[Idiom, ...] = ()


@dataclass(frozen=True)
class Item:
    """Jedna jednostka treści: ``h2`` albo ``h3`` (nagłówek), ``line`` (linia akapitu), ``code`` (linia bloku kodu),
    ``point`` (punkt listy) albo nazwa innego bloku najwyższego poziomu, którego szablon nie zna; ``links`` to linki
    GitHuba do issues i PR-ów w jej tekście."""

    kind: str
    text: str
    links: tuple[github.LinkGithuba, ...] = ()

    def shown(self) -> str:
        if self.kind in {"h2", "h3"}:
            return f"nagłówek „{'#' * int(self.kind[1])} {self.text}”"
        described = {"line": "linia", "code": "linia bloku kodu", "point": "punkt listy"}.get(self.kind, f"blok <{self.kind}>")
        return f"{described} „{self.text}”"


class _Items(HTMLParser):
    """Jednostki ``Item`` HTML z renderera GitHuba w kolejności dokumentu: akapit dzieli ``<br>``, którym GitHub
    zastępuje koniec wiersza, a ``<pre>`` jego koniec wiersza; tekst znaczników wierszowych (kod, link, pogrubienie)
    należy do linii."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[Item] = []
        self._open: list[str] = []
        self._text: list[str] = []
        self._links: list[github.LinkGithuba] = []
        self._nested: str | None = None  # blok wewnątrz punktu listy
        self._wrappers: list[int] = []  # głębokość otwarcia każdej otwartej osłony ``SNIPPET``

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div" and SNIPPET in (dict(attrs).get("class") or "").split():
            self._wrappers.append(len(self._open))
            return
        top = self._open[0] if self._open else None
        if top is None:
            self._text, self._links = [], []
            if tag in _VOID:
                self.items.append(Item(tag, ""))
                return
        elif top == "p" and tag == "br":
            self._line()
        elif top == "ul" and tag == "li" and len(self._open) == 1:
            self._text, self._links, self._nested = [], [], None
        elif top == "ul" and len(self._open) > 1 and tag in _BLOCKS | {_LOOSE_ITEM}:
            self._nested = self._nested or (tag if tag != _LOOSE_ITEM else None)
            self._text.append(" ")
        elif tag == "br":
            self._text.append(" ")
        if tag == "a" and (link := github.link_githuba(attrs)) is not None:
            self._links.append(link)
        if tag not in _VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._wrappers and self._wrappers[-1] == len(self._open):
            self._wrappers.pop()
            return
        if tag not in self._open:
            return
        del self._open[len(self._open) - 1 - self._open[::-1].index(tag) :]
        if self._open == ["ul"] and tag == "li":
            self.items.append(Item(self._nested or "point", _joined(self._text), tuple(self._links)))
        elif not self._open:
            self._close(tag)

    def handle_data(self, data: str) -> None:
        if self._open:
            self._text.append(data)
        elif data.strip():
            self.items.append(Item("tekst", data.strip()))

    def _line(self) -> None:
        if text := _joined(self._text):
            self.items.append(Item("line", text, tuple(self._links)))
        self._text, self._links = [], []

    def _close(self, tag: str) -> None:
        if tag == "p":
            self._line()
        elif tag == "pre":
            self.items.extend(Item("code", line.rstrip()) for line in "".join(self._text).splitlines() if line.strip())
        elif tag != "ul":
            self.items.append(Item(tag, _joined(self._text), tuple(self._links)))


def _joined(parts: Sequence[str]) -> str:
    return " ".join("".join(parts).split())


def items(html: str) -> list[Item]:
    """Jednostki treści HTML GitHuba w kolejności dokumentu: z renderera ``github.html_markdownu`` albo z pola
    ``bodyHTML`` GraphQL, które daje te same jednostki (``SNIPPET``)."""

    parser = _Items()
    parser.feed(html)
    parser.close()
    return parser.items


def listed_codes(text: str) -> frozenset[str]:
    """Kody z treści listy korzeni; ``ValueError``, gdy wpis nie ma postaci kodu z ``opis`` i numerem PR ``przyklad``."""

    return frozenset(descriptions(text))


def descriptions(text: str) -> dict[str, str]:
    """Kody z treści listy korzeni z ich opisem; ``ValueError`` jak w ``listed_codes``."""

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
    return {code: entry["opis"] for code, entry in entries.items()}


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

    return pattern(SKILL, "Postać werdyktu")


def pattern(skill: Path, section: str) -> str:
    """Wzór z pierwszego bloku ``markdown`` sekcji ``## <section>`` pliku ``skill``, w jednej linii."""

    block = skill.read_text(encoding="utf-8").partition(f"## {section}\n")[2].partition("```markdown\n")[2].partition("\n```")[0]
    return " / ".join(line.strip() for line in block.splitlines() if line.strip())


def _value(item: Item, field: str) -> str | None:
    """Tekst pola ``field`` w linii akapitu ``item``; ``None``, gdy to inne pole albo nie linia akapitu, a pusty
    napis, gdy pole jest puste."""

    return item.text.removeprefix(field).strip() if item.kind == "line" and item.text.startswith(field) else None


def places(where: str) -> list[tuple[str, int, int]]:
    """Miejsca ``plik:linia`` i ``plik:linia-linia`` z tekstu pola ``Gdzie:``: ścieżka repo, pierwsza i ostatnia linia.

    Plik to ścieżka z ``/`` albo nazwa z rozszerzeniem od litery, więc godzina ``12:30``, proporcja ``3:1`` i ``:linia``
    bez pliku nie są miejscem; plik bez rozszerzenia w korzeniu repo (``Makefile:3``) też nie."""

    return [(found[1], int(found[2]), int(found[3] or found[2])) for found in PLACE.finditer(where)]


def evidence_problems(label: str, evidence: str, items: Sequence[Item]) -> list[str]:
    """Co poprawić w Dowodzie ``label``: ``evidence`` to tekst pola ``Dowód:``, a ``items`` jednostki po nim; Dowód to
    linie tekstu i bloki kodu, od 1 do ``MAX_EVIDENCE`` linii po najwyżej ``MAX_EVIDENCE_CHARS`` znaków."""

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


def idiom(label: str, text: str) -> Idiom | None:
    """Pole ``Idiom:`` Ważnego ``label`` z linii ``text`` w jednej z trzech postaci; ``None`` w każdej innej."""

    if found := IDIOM_NO_RULE.fullmatch(text):
        return Idiom(label, None, found[1], (int(found[2]), found[3], int(found[4])))
    if found := IDIOM_LIKE.fullmatch(text):
        return Idiom(label, found[1], None, (int(found[2]), found[3], int(found[4])))
    if found := IDIOM_ESCAPE.fullmatch(text):
        return Idiom(label, found[1], None, None)
    return None


def _major(label: str, block: Sequence[Item], roots: list[Root], idioms: list[Idiom]) -> list[str]:
    order = f"{label}: pola w kolejności Gdzie, Dowód, Korzeń, Szczebel"
    where = _value(block[0], "Gdzie:") if block else None
    if where is None:
        return [f"{order}, a po nagłówku jest {block[0].shown() if block else 'koniec'}"]
    problems = [] if where else [f"{label}: puste pole Gdzie"]
    evidence = _value(block[1], "Dowód:") if len(block) > 1 else None
    if evidence is None:
        return [*problems, f"{order}, a po Gdzie jest {block[1].shown() if len(block) > 1 else 'koniec'}"]
    end = next((index for index, item in enumerate(block) if index > 1 and item.kind == "line" and item.text.startswith(FIELDS)), len(block))
    problems.extend(evidence_problems(label, evidence, block[2:end]))
    rest = list(block[end:])
    if not rest or _value(rest[0], "Korzeń:") is None:
        return [*problems, f"{order}, a po Dowodzie jest {rest[0].shown() if rest else 'koniec'} ({QUOTE})"]
    found = ROOT_FIELD.fullmatch(rest[0].text)
    roots[-1] = Root(label, bool(found[1]), found[2]) if found else roots[-1]
    if found is None:
        problems.append(f"{label}: „{rest[0].text}” to nie „Korzeń: R-KOD - zdanie” ani „Korzeń: NOWY R-KOD - opis”")
    if len(rest) < 2:
        return [*problems, f"{order}, a po Korzeniu jest koniec"]
    if rest[1].kind != "line" or RUNG_FIELD.fullmatch(rest[1].text) is None:
        problems.append(f"{label}: {rest[1].shown()} to nie „Szczebel: (a) - zdanie” ze szczeblem od (a) do (e)")
    after = list(rest[2:])
    if after and _value(after[0], "Idiom:") is not None:
        if (found_idiom := idiom(label, after.pop(0).text)) is None:
            problems.append(f"{label}: „{rest[2].text}” to nie „{IDIOM_FORMS}”")
        else:
            idioms.append(found_idiom)
    return [*problems, *(f"{label}: po Szczeblu tylko pole Idiom:, a jest {item.shown()}" for item in after)]


def _minor(label: str, block: Sequence[Item]) -> list[str]:
    where = _value(block[0], "Gdzie:") if block else None
    if where is None:
        return [f"{label}: po nagłówku jedna linia „Gdzie: <plik:linia>”, a jest {block[0].shown() if block else 'koniec'}"]
    return [*([] if where else [f"{label}: puste pole Gdzie"]), *(f"{label}: Drobne ma tylko pole Gdzie, a jest {item.shown()}" for item in block[1:])]


def _root_problems(roots: Sequence[Root], codes: Callable[[], frozenset[str]]) -> list[str]:
    roots = [root for root in roots if root.code is not None]
    if not roots:
        return []
    try:
        listed = codes()
    except CodesUnavailable as error:
        return [str(error)]
    problems = []
    for root in roots:
        name, field = (root.label, "Korzeń:") if root.round is None else (f"punkt „Korzeń {root.label} r{root.round}”", f"Korzeń {root.label} r{root.round}:")
        if root.new and root.code in listed:
            problems.append(f"{name}: NOWY {root.code}: ten kod jest już na liście {LIST}, napisz go bez NOWY")
        elif not root.new and root.code not in listed:
            problems.append(f"{name}: kod {root.code} spoza listy {LIST}: użyj kodu z listy albo napisz „{field} NOWY {root.code} - opis”")
    return problems


def problems(html: str, declared: tuple[int, int] | None, codes: Callable[[], frozenset[str]]) -> list[str]:
    """Co poprawić w treści werdyktu: ``html`` to HTML renderera GitHuba dla linii pod dwiema pierwszymi (pusty, gdy
    ich nie ma), ``declared`` liczby Ważnych i Drobnych z linii ``Znaleziska:`` (``None``, gdy jej nie ma), a
    ``codes`` czyta kody listy na HEAD PR, gdy jest pole Korzeń albo punkt rozstrzygnięcia."""

    found, findings = _read(items(html), declared)
    found.extend(_root_problems([*findings.majors, *findings.resolutions], codes))
    return [*found, f"wzór ({SKILL.relative_to(ROOT).as_posix()}): {template()}"] if found else []


def findings(units: Sequence[Item]) -> Findings:
    """Kody korzeni treści werdyktu z jej jednostek (``items``), czytane tak samo jak przy ``problems``."""

    return _read(units, None)[1]


def _read(units: Sequence[Item], declared: tuple[int, int] | None) -> tuple[list[str], Findings]:
    found: list[str] = []
    roots: list[Root] = []
    idioms: list[Idiom] = []
    counts = {"W": 0, "D": 0}
    end = next((index for index, item in enumerate(units) if item.kind == "h2" and item.text == CHECKED), len(units))
    index = 0
    while index < end:
        heading = HEADING.fullmatch(units[index].text) if units[index].kind == "h3" else None
        if heading is None:
            found.append(f"{units[index].shown()} to nie nagłówek „### W<n>. <zdanie>”, „### D<n>. <zdanie>” ani „## {CHECKED}”")
            index += 1
            continue
        kind, label = heading[1], f"{heading[1]}{heading[2]}"
        if kind == "W" and counts["D"]:
            found.append(f"{label}: Ważne stoją przed Drobnymi")
        counts[kind] += 1
        if int(heading[2]) != counts[kind]:
            found.append(f"{label}: to {counts[kind]}. {'Ważne' if kind == 'W' else 'Drobne'}, więc {kind}{counts[kind]}")
        after = next((later for later in range(index + 1, end) if units[later].kind in {"h2", "h3"}), end)
        block = units[index + 1 : after]
        if kind == "W":
            roots.append(Root(label, False, None))
            found.extend(_major(label, block, roots, idioms))
        else:
            found.extend(_minor(label, block))
        index = after
    if declared is not None and (counts["W"], counts["D"]) != declared:
        found.append(f"w treści Ważne {counts['W']} i Drobne {counts['D']}, a linia Znaleziska mówi Ważne {declared[0]}, Drobne {declared[1]}")
    after_checked = units[end + 1 :]
    points = [item for item in after_checked if item.kind == "point"]
    if end == len(units):
        found.append(f"brak „## {CHECKED}” z 1–{MAX_CHECKED} punktami „- …” na końcu")
    elif not points or len(points) > MAX_CHECKED:
        found.append(f"„## {CHECKED}” ma {len(points)} punktów, a ma od 1 do {MAX_CHECKED}")
    found.extend(f"po „## {CHECKED}” tylko punkty „- …”, a jest {item.shown()}" for item in after_checked if item.kind != "point")
    found.extend(f"po „## {CHECKED}” pusty punkt listy" for item in points if not item.text)
    resolutions = []
    for point in (item for item in points if item.text.startswith(RESOLUTION_START)):
        resolved = RESOLUTION.fullmatch(point.text)
        if resolved is None:
            found.append(f"punkt „{point.text}” to nie rozstrzygnięcie „Korzeń W<n> r<runda>: R-KOD - zdanie” (punkt „## {CHECKED}” nie zaczyna się od „{RESOLUTION_START.strip()}”, gdy nim nie jest)")
        else:
            resolutions.append(Root(resolved[1], bool(resolved[3]), resolved[4], int(resolved[2])))
    return found, Findings(tuple(roots), tuple(resolutions), tuple(idioms))
