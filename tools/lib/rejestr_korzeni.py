"""Rejestr korzeni (ADR 0031, decyzje Q13, Q22, Q25): wystąpienia kodów korzeni czytane z GitHuba dla bramki korzenia
i tygodniowego pomiaru.

Rejestrem są werdykty i opisy PR-ów na GitHubie, a nie plik w repozytorium (Q22). Wystąpienie kodu to:

- Ważne ``W<n> r<k>`` werdyktu ``FAIL`` rundy ``k`` z kodem z ostatniego werdyktu, który go dotyczy: z pola
  ``Korzeń:`` tego Ważnego albo z późniejszego punktu ``Korzeń W<n> r<k>: R-KOD - zdanie`` w „## Sprawdzone” (Q25);
  te same Ważne i kody bierze bramka korzenia (``majors``);
- blok ``### Czerwony main #N: R-KOD`` sekcji ``## Korzeń`` opisu PR scalonego do bazy.

Liczą się tylko wystąpienia po wdrożeniu szablonu (Q13): chwila wdrożenia to ``werdykt_pr.deployment`` dla ADR 0031
(``szablon_werdyktu.ADR``). Ważne liczy się w wątku z szablonem (``werdykt_pr.rule_applies``), gdy jego werdykt
``FAIL`` powstał (``createdAt``) nie przed tą chwilą; werdykt w komentarzu edytowanym liczy się z treścią po edycji,
ale w chwili utworzenia, więc edycją nie da się przenieść starego werdyktu za wdrożenie. Blok czerwonego `main` liczy
się, gdy PR scalono (``mergedAt``) nie przed tą chwilą. Kod korzenia to kategoria, która niczego nie blokuje
([ADR 0036](../../docs/adr/0036-chwast-to-regula.md)): rejestr nie zakłada issues i nie szuka wcześniejszych wyrwań.

Zapytanie do GitHuba jest jedno i po kolei, bo konto ma secondary rate limit: GraphQL ``search`` PR-ów repozytorium
zmienionych od wdrożenia (``updated:>=``), w kolejności założenia (``sort:created-asc``), po ``PAGE`` PR-ów na stronę,
z opisem, komentarzami i recenzjami. Każde wystąpienie zmienia PR (komentarz werdyktu, merge), więc PR bez zmiany od
wdrożenia go nie ma, a PR założony przed wdrożeniem z pierwszym werdyktem po nim (``werdykt_pr.rule_applies``) na
liście jest. Kolejność stron jest stała, bo chwila założenia PR się nie zmienia: następna strona to nowe wyszukiwanie
od chwili założenia ostatniego PR strony (``created:>=``, PR-y z tą samą sekundą rejestr pomija drugi raz). Lista
po ostatniej zmianie tego nie daje: kursor GitHuba przy ``UPDATED_AT`` to para (``updatedAt``, id), więc PR zmieniony
między stronami przeskakuje przed kursor i znika ze skanu. Nowe wyszukiwanie zamiast kursora wyszukiwarki omija też
jej limit 1000 wyników. Granica: indeks wyszukiwarki ma kilka sekund opóźnienia, a ``updatedAt`` tylko rośnie, więc
brakuje najwyżej PR-u, którego pierwsza zmiana od wdrożenia jest sprzed kilku sekund.

Treść skanu to HTML z GitHuba z tej samej strony GraphQL (``bodyHTML`` opisu, komentarza i recenzji, ``FIELDS``),
więc rejestr nie woła renderera ``POST /markdown`` ani razu: werdykt czyta ``werdykt_pr.from_graphql``, a opis PR
``szablon_werdyktu.items`` z jego ``bodyHTML``. PR z więcej niż 100 komentarzami albo recenzjami doczytuje
``pull_node`` (zapytanie na każde 100). Granica: nagłówek sekcji zapisany encjami HTML (``Korze&#324;``) GitHub
pokazałby jako sekcję, a rejestr takiego opisu nie czyta.

Budżet: workflow tygodniowy biegnie z ``GITHUB_TOKEN``, który ma 1000 punktów GraphQL na godzinę na repozytorium
(i osobno 1000 żądań REST). Strona skanu (``PAGE`` PR-ów z komentarzami i recenzjami) kosztuje 1 punkt (``rateLimit``
13.11.2026: 1 punkt dla 20 i dla 50 PR-ów na stronę), a koszt skanu rośnie z liczbą PR-ów zmienionych od wdrożenia
(Q13 liczy powtórzenia od wdrożenia, więc skan go nie ucina): strona na każde ``PAGE - 1`` PR-ów. Przy ok. 44 PR-ach
dziennie to ok. 16 stron na tydzień PR-ów, czyli ok. 420 punktów na przebieg po pół roku (ok. 8000 PR-ów), do tego
``pull_node`` na PR z ponad 100 komentarzami. Limit 1000 punktów przebieg przekroczy po ok. 14 miesiącach; wtedy
``PAGE`` 50 (ten sam 1 punkt na stronę) daje 2,6 raza mniej stron.

Issues „Chwast: R-KOD” (``TITLE``, etykieta ``WEED``) rejestr nie zakłada ani nie zmienia; tytuł i etykietę czyta
tygodniowy pomiar, który podaje otwarte, dopóki ich nie zamknięto (ADR 0036, „Bez listy”).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import json
import re
from typing import Any

import github
import stan_pr
from stan_pr import Pull
import szablon_werdyktu
from szablon_werdyktu import CODE, Item, Root
import werdykt_pr

SECTION = "Korzeń"
MAJOR_HEADING = re.compile(rf"(W\d+) r(\d+): ({CODE.pattern})")
RED_HEADING = re.compile(rf"Czerwony main #(\d+): ({CODE.pattern})")
UPROOTED = re.compile(r"Wyrwany w #(\d+)")
ROOT_LINE = re.compile(rf"Korzeń z #\d+: ({CODE.pattern})")
ROOT_WORDS = "Korzeń z"
WEED = "chwast"
# Etykieta issue „Rejestr korzeni” z tygodniowym pomiarem (``tools/rejestr_korzeni_tydzien.py``), osobna od ``WEED``,
# żeby lista issues z etykietą ``chwast`` miała same chwasty.
REGISTRY = "rejestr-korzeni"
LABELS = {REGISTRY: ("5319e7", "Tygodniowy pomiar powtórzeń korzeni (ADR 0031)")}
TITLE = "Chwast: {code}"
PAGE = 20
SEARCH = "repo:{repository} is:pr updated:>={deployed} sort:created-asc"
SINCE = " created:>={created}"
# Pola PR z HTML treści (``bodyHTML``) opisu, komentarzy i recenzji, wspólne dla wyszukiwania i zapytania o jeden PR.
FIELDS = """
fragment Pull on PullRequest {
  number title state isDraft isCrossRepository baseRefName headRefOid url body bodyHTML createdAt updatedAt mergedAt
  comments(first: 100, after: $comments) { pageInfo { hasNextPage endCursor } nodes { body bodyHTML authorAssociation createdAt includesCreatedEdit author { login } } }
  reviews(first: 100, after: $reviews) { pageInfo { hasNextPage endCursor } nodes { body bodyHTML authorAssociation state submittedAt includesCreatedEdit author { login } } }
}
"""
QUERY = """
query($q: String!, $first: Int!, $comments: String, $reviews: String) {
  search(query: $q, type: ISSUE, first: $first) { nodes { ...Pull } }
}
""" + FIELDS
PULL_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $comments: String, $reviews: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { ...Pull } }
}
""" + FIELDS
CONNECTIONS = ("comments", "reviews")


@dataclass(frozen=True)
class Block:
    """Blok sekcji ``## Korzeń``: nagłówek bez kodu (``W1 r2`` albo ``Czerwony main #N``), kod i jednostki pod nim."""

    heading: str
    code: str
    items: tuple[Item, ...]

    def uprooted(self) -> int | None:
        """Numer z pierwszej linii ``Wyrwany w #M``; ``None`` bez niej."""

        first = self.items[0] if self.items else None
        found = UPROOTED.fullmatch(first.text) if first is not None and first.kind == "line" else None
        return int(found[1]) if found else None


@dataclass(frozen=True)
class Section:
    """Sekcja ``## Korzeń``: bloki w kolejności (także powtórzone) i jednostki, które blokiem nie są (inna jednostka
    przed blokiem albo nagłówek ``###`` spoza wzoru)."""

    blocks: tuple[Block, ...]
    strays: tuple[Item, ...]


def section(units: Sequence[Item]) -> Section | None:
    """Sekcja od pierwszego nagłówka ``## Korzeń`` do następnego ``##`` w jednostkach ``szablon_werdyktu.items``;
    ``None``, gdy jej nie ma."""

    starts = [index for index, item in enumerate(units) if item.kind == "h2" and item.text == SECTION]
    if not starts:
        return None
    end = next((index for index in range(starts[0] + 1, len(units)) if units[index].kind == "h2"), len(units))
    blocks, strays = [], []
    index = starts[0] + 1
    while index < end:
        item = units[index]
        after = next((later for later in range(index + 1, end) if units[later].kind == "h3"), end)
        heading = _heading(item)
        if heading is None:
            strays.append(item)
        else:
            blocks.append(Block(*heading, tuple(units[index + 1 : after])))
        index = after if item.kind == "h3" else index + 1
    return Section(tuple(blocks), tuple(strays))


def _heading(item: Item) -> tuple[str, str] | None:
    if item.kind != "h3":
        return None
    if major := MAJOR_HEADING.fullmatch(item.text):
        return f"{major[1]} r{major[2]}", major[3]
    if red := RED_HEADING.fullmatch(item.text):
        return f"Czerwony main #{red[1]}", red[2]
    return None


def root_lines(units: Sequence[Item], repository: str) -> list[tuple[github.LinkGithuba, str]]:
    """Linie akapitu i punkty listy ``Korzeń z #N: R-KOD`` z linkiem GitHuba do issue albo PR ``repository``: link
    i kod. Linia w tej postaci ma jeden numer, więc wyznacza go jej jedyny link do tego repozytorium."""

    found = []
    for item in units:
        listed = ROOT_LINE.fullmatch(item.text) if item.kind in {"line", "point"} else None
        links = [link for link in item.links if link.w(repository)]
        if listed and len(links) == 1:
            found.append((links[0], listed[1]))
    return found


@dataclass(frozen=True)
class Major:
    """Ważne ``heading`` (``W1 r2``) werdyktu ``FAIL`` rundy ``round`` z kodem z ostatniego werdyktu, który go dotyczy
    (``None``, gdy żaden nie podał kodu w szablonie), i chwilą Ważnego ``since``, czyli utworzenia werdyktu ``FAIL``
    rundy ``round`` (``None`` bez chwili); rozstrzygnięcie innym kodem (Q25) zmienia kod, a nie chwilę."""

    heading: str
    round: int
    code: str | None
    since: datetime | None = None


def majors(rounds: Sequence[werdykt_pr.Round]) -> tuple[dict[str, Major], list[tuple[int, Root]]]:
    """Ważne werdyktów ``FAIL`` po nagłówku i punkty rozstrzygnięcia, które nie wskazują Ważnego werdyktu ``FAIL`` tej
    albo wcześniejszej rundy (z rundą ich werdyktu). Ważne werdyktu to ``W1`` … ``W<a>`` z linii ``Znaleziska:`` (co
    najmniej ``W1``, bo ``FAIL`` daje tylko Ważne) i każde ``### W<n>.`` jego treści."""

    found: dict[str, Major] = {}
    strays: list[tuple[int, Root]] = []
    for current in rounds:
        if current.verdict.decision == "FAIL":
            labels = [*(f"W{index}" for index in range(1, max(current.declared_majors or 0, 1) + 1)), *(root.label for root in current.findings.majors)]
            for label in dict.fromkeys(labels):
                found[f"{label} r{current.number}"] = Major(f"{label} r{current.number}", current.number, None, _moment(current.verdict.when))
            for root in current.findings.majors:
                if root.code is not None:
                    key = f"{root.label} r{current.number}"
                    found[key] = replace(found[key], code=root.code)
        for resolution in current.findings.resolutions:
            key = f"{resolution.label} r{resolution.round}"
            if key in found:
                found[key] = replace(found[key], code=resolution.code)
            else:
                strays.append((current.number, resolution))
    return found, strays


@dataclass(frozen=True)
class Occurrence:
    """Wystąpienie kodu ``code`` w PR ``pull``: Ważne (``W1 r2``) albo ``Czerwony main #N`` i chwila wystąpienia
    ``when`` (Ważnego: utworzenie werdyktu ``FAIL`` jego rundy, ``Major.since``; czerwonego `main`: merge PR)."""

    code: str
    pull: int
    major: str
    when: datetime


def read(repository: str, deployed: datetime | None) -> list[Occurrence]:
    """Wystąpienia kodów w PR-ach ``repository`` (``właściciel/nazwa``) po chwili wdrożenia szablonu ``deployed``
    (``None``: szablon niewdrożony, więc żadnych), w kolejności PR i Ważnego. Błąd GitHuba to wyjątek."""

    if deployed is None:
        return []
    found = []
    for node in _pulls(repository, deployed):
        found.extend(occurrences(node if _complete(node) else pull_node(repository, node["number"]), deployed))
    return sorted(found, key=_order)


@dataclass(frozen=True)
class IdiomCase:
    """Pole ``Idiom:`` Ważnego ``idiom.label`` werdyktu ``FAIL`` rundy ``round`` PR ``pull``."""

    pull: int
    round: int
    idiom: szablon_werdyktu.Idiom


def idiom_cases(number: int, rounds: Sequence[werdykt_pr.Round]) -> list[IdiomCase]:
    """Pola ``Idiom:`` Ważnych werdyktów ``FAIL`` rund ``rounds`` PR ``number``."""

    return [IdiomCase(number, current.number, idiom) for current in rounds if current.verdict.decision == "FAIL" for idiom in current.findings.idioms]


def idioms(repository: str, deployed: datetime | None) -> list[IdiomCase]:
    """Pola ``Idiom:`` Ważnych werdyktów ``FAIL`` w PR-ach ``repository`` zmienionych od wdrożenia szablonu ``deployed``
    (``None``: szablon niewdrożony, więc żadnych), w kolejności PR; ten sam skan co ``read``. Błąd GitHuba to wyjątek."""

    if deployed is None:
        return []
    found = []
    for node in _pulls(repository, deployed):
        pull = _pull(node if _complete(node) else pull_node(repository, node["number"]))
        found.extend(idiom_cases(pull.number, werdykt_pr.rounds(pull, werdykt_pr.from_graphql)))
    return sorted(found, key=lambda case: (case.pull, case.round))


def occurrences(node: dict[str, Any], deployed: datetime) -> list[Occurrence]:
    """Wystąpienia kodów w PR z węzła GraphQL ``node`` (``FIELDS``, każdy komentarz i każda recenzja) po chwili
    wdrożenia ``deployed``; blok czerwonego `main` ma tylko PR scalony (``mergedAt``)."""

    pull = _pull(node)
    merged = _moment(node["mergedAt"]) if node.get("mergedAt") else None
    found = []
    verdicts = [verdict for verdict in (werdykt_pr.read(verdict, pull.head) for verdict in pull.verdicts) if verdict is not None]
    if werdykt_pr.rule_applies(pull, deployed) and any(verdict.decision == "FAIL" for verdict in verdicts):
        rounds = werdykt_pr.rounds(pull, werdykt_pr.from_graphql)
        for major in majors(rounds)[0].values():
            if major.code is not None and major.since is not None and major.since >= deployed:
                found.append(Occurrence(major.code, pull.number, major.heading, major.since))
    if merged is not None and merged >= deployed:
        found.extend(Occurrence(block.code, pull.number, heading, merged) for heading, block in _blocks(pull, str(node["bodyHTML"])).items() if heading.startswith("Czerwony"))
    return sorted(found, key=_order)


def create_labels(api: github.GhApi, names: Sequence[str], prefix: str, *, write: bool) -> list[str]:
    """Zakłada etykiety ``names`` (z ``LABELS``), których repozytorium jeszcze nie ma; bez ``write`` tylko podaje,
    co by założył. Linia ``<prefix> | …`` na każdą."""

    present = {str(label["name"]) for label in github.strony(api, f"{github.REPO}/labels")}
    lines = []
    for name in (name for name in names if name not in present):
        if write:
            color, description = LABELS[name]
            api.wyslij("POST", f"{github.REPO}/labels", {"name": name, "color": color, "description": description})
        lines.append(f"{prefix} | założona etykieta {name}" if write else f"{prefix} | bez zapisu: załóż etykietę {name}")
    return lines


def _pulls(repository: str, deployed: datetime) -> Iterator[dict[str, Any]]:
    """PR-y ``repository`` zmienione od ``deployed`` w kolejności założenia, każdy raz: strona to wyszukiwanie od chwili
    założenia ostatniego PR poprzedniej strony, więc zmiana PR w trakcie skanu nie przesuwa stron."""

    search = SEARCH.format(repository=repository, deployed=deployed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    seen: set[int] = set()
    since = ""
    while True:
        nodes = _graphql(QUERY, q=f"{search}{since}", first=PAGE, comments=None, reviews=None)["search"]["nodes"]
        fresh = [node for node in nodes if node["number"] not in seen]
        seen.update(node["number"] for node in fresh)
        yield from fresh
        if len(nodes) < PAGE:
            return
        if not fresh:
            raise ValueError(f"GitHub: co najmniej {PAGE} PR-ów założonych w chwili {nodes[-1]['createdAt']}, więc strony rejestru korzeni stoją w miejscu")
        since = SINCE.format(created=nodes[-1]["createdAt"])


def pull_node(repository: str, number: int) -> dict[str, Any]:
    """Węzeł GraphQL PR ``number`` (``FIELDS``) z każdym komentarzem i każdą recenzją: zapytanie na każde 100."""

    owner, name = repository.split("/")
    page = _graphql(PULL_QUERY, owner=owner, name=name, number=number, comments=None, reviews=None)["repository"]["pullRequest"]
    found = {kind: list(page[kind]["nodes"]) for kind in CONNECTIONS}
    cursors = {kind: page[kind]["pageInfo"]["endCursor"] for kind in CONNECTIONS if page[kind]["pageInfo"]["hasNextPage"]}
    while cursors:
        more = _graphql(PULL_QUERY, owner=owner, name=name, number=number, **{kind: cursors.get(kind) for kind in CONNECTIONS})["repository"]["pullRequest"]
        for kind in list(cursors):
            found[kind].extend(more[kind]["nodes"])
            if more[kind]["pageInfo"]["hasNextPage"]:
                cursors[kind] = more[kind]["pageInfo"]["endCursor"]
            else:
                del cursors[kind]
    return {**page, **{kind: {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": found[kind]} for kind in CONNECTIONS}}


def _complete(node: dict[str, Any]) -> bool:
    return not any(node[kind]["pageInfo"]["hasNextPage"] for kind in CONNECTIONS)


def _graphql(query: str, **variables: str | int | None) -> dict[str, Any]:
    """Pole ``data`` odpowiedzi GraphQL; błąd z odpowiedzi to ``ValueError``."""

    arguments = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        arguments += ["-F", f"{key}=null"] if value is None else ["-F", f"{key}={value}"] if isinstance(value, int) else ["-f", f"{key}={value}"]
    answer = json.loads(github.gh(*arguments))
    if answer.get("errors"):
        raise ValueError(f"GraphQL: {answer['errors']}")
    data: dict[str, Any] = answer["data"]
    return data


def pull(repository: str, number: int) -> Pull:
    """PR ``number`` z każdym komentarzem i każdą recenzją, z HTML treści dla ``werdykt_pr.from_graphql``."""

    return _pull(pull_node(repository, number))


def _pull(node: dict[str, Any]) -> Pull:
    view = {**node, "comments": node["comments"]["nodes"], "reviews": node["reviews"]["nodes"], "closingIssuesReferences": [], "statusCheckRollup": []}
    return stan_pr.from_view(view)


def _blocks(pull: Pull, html: str) -> dict[str, Block]:
    if SECTION not in pull.body:
        return {}
    found = section(szablon_werdyktu.items(html))
    return {} if found is None else {block.heading: block for block in found.blocks}


def _moment(when: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(when))
    except ValueError:
        return None


def _natural(major: str) -> tuple[int, ...]:
    return (major.startswith("Czerwony"), *map(int, re.findall(r"\d+", major)))


def _order(occurrence: Occurrence) -> tuple[int, tuple[int, ...]]:
    return occurrence.pull, _natural(occurrence.major)
