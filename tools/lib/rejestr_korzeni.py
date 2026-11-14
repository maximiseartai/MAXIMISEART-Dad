"""Rejestr korzeni (ADR 0031, decyzje Q11, Q12, Q13, Q15, Q22, Q25): wystąpienia kodów korzeni czytane z GitHuba,
issues „Chwast: R-KOD” i wcześniejsze wyrwania kodu dla bramki korzenia.

Rejestrem są werdykty i opisy PR-ów na GitHubie, a nie plik w repozytorium (Q22). Wystąpienie kodu to:

- Ważne ``W<n> r<k>`` werdyktu ``FAIL`` rundy ``k`` z kodem z ostatniego werdyktu, który go dotyczy: z pola
  ``Korzeń:`` tego Ważnego albo z późniejszego punktu ``Korzeń W<n> r<k>: R-KOD - zdanie`` w „## Sprawdzone” (Q25);
  te same Ważne i kody bierze bramka korzenia (``majors``);
- blok ``### Czerwony main #N: R-KOD`` sekcji ``## Korzeń`` opisu PR scalonego do bazy.

Liczą się tylko wystąpienia po wdrożeniu szablonu (Q13): chwila wdrożenia to ``werdykt_pr.deployment`` dla ADR 0031
(``szablon_werdyktu.ADR``). Ważne liczy się w wątku z szablonem (``werdykt_pr.rule_applies``), gdy jego werdykt
``FAIL`` powstał (``createdAt``) nie przed tą chwilą; werdykt w komentarzu edytowanym liczy się z treścią po edycji,
ale w chwili utworzenia, więc edycją nie da się przenieść starego werdyktu za wdrożenie. Blok czerwonego `main` liczy
się, gdy PR scalono (``mergedAt``) nie przed tą chwilą. Dwa wystąpienia kodu w jednym PR to jeszcze nie powrót:
chwast to kod z wystąpieniami w co najmniej 2 różnych PR-ach.

Szczebel i mechanizm wystąpienia to pierwsza linia bloku sekcji ``## Korzeń`` scalonego PR z tym samym nagłówkiem:
``Szczebel: (x) - mechanizm`` daje ``(x)`` i mechanizm, ``Wyrwany w #M`` daje szczebel ``-`` i mechanizm ``Wyrwany
w #M`` (szczebel ma tam PR korzenia, którego opis go nie podaje), a PR otwarty albo bez bloku daje ``-`` i ``-``.
Wcześniejsze wyrwanie kodu dla bramki (Q11) to wystąpienie ze szczeblem w innym PR scalonym (``mergedAt``) przed
chwilą, w której powstało wystąpienie kodu w PR bramki (``earlier``): dla Ważnego to chwila Ważnego, czyli utworzenia
werdyktu ``FAIL`` jego rundy (``Major.since``), także gdy późniejszy werdykt rozstrzyga je innym kodem (Q25), bo
dopiero wyrwanie scalone przed nią mogło temu Ważnemu zapobiec. Tę samą chwilę ``occurrences`` porównuje z chwilą
wdrożenia. Merge w tej samej sekundzie już się nie liczy.

Zapytanie do GitHuba jest jedno i po kolei, bo konto ma secondary rate limit: GraphQL ``search`` PR-ów repozytorium
zmienionych od wdrożenia (``updated:>=``), w kolejności założenia (``sort:created-asc``), po ``PAGE`` PR-ów na stronę,
z opisem, komentarzami i recenzjami. Każde wystąpienie zmienia PR (komentarz werdyktu, merge), więc PR bez zmiany od
wdrożenia go nie ma, a PR założony przed wdrożeniem z pierwszym werdyktem po nim (``werdykt_pr.rule_applies``) na
liście jest. Kolejność stron jest stała, bo chwila założenia PR się nie zmienia: następna strona to nowe wyszukiwanie
od chwili założenia ostatniego PR strony (``created:>=``, PR-y z tą samą sekundą rejestr pomija drugi raz). Lista
po ostatniej zmianie tego nie daje: kursor GitHuba przy ``UPDATED_AT`` to para (``updatedAt``, id), więc PR zmieniony
między stronami przeskakuje przed kursor i znika ze skanu. Nowe wyszukiwanie zamiast kursora wyszukiwarki omija też
jej limit 1000 wyników. Granica: indeks wyszukiwarki ma kilka sekund opóźnienia, a ``updatedAt`` tylko rośnie, więc
brakuje najwyżej PR-u, którego pierwsza zmiana od wdrożenia jest sprzed kilku sekund; jego publikacja werdyktu sama
czyta rejestr (``after_verdict``), a ``tools/chwasty.py`` uzupełnia go później.

Treść skanu to HTML z GitHuba z tej samej strony GraphQL (``bodyHTML`` opisu, komentarza i recenzji, ``FIELDS``),
więc rejestr nie woła renderera ``POST /markdown`` ani razu: werdykt czyta ``werdykt_pr.from_graphql``, a opis PR
i treść issue chwastu (``weed_issues``) ``szablon_werdyktu.items`` z ich ``bodyHTML``. PR z więcej niż 100
komentarzami albo recenzjami doczytuje ``pull_node`` (zapytanie na każde 100), a publikacja werdyktu czyta tak swój PR.
Granica: nagłówek sekcji zapisany encjami HTML (``Korze&#324;``) GitHub pokazałby jako sekcję, a rejestr takiego opisu
nie czyta. Renderer zostaje tylko w ``consents``, które czyta zgody w jednym PR bramki przy merge'u.

Budżet: workflow tygodniowy biegnie z ``GITHUB_TOKEN``, który ma 1000 punktów GraphQL na godzinę na repozytorium
(i osobno 1000 żądań REST). Strona skanu (``PAGE`` PR-ów z komentarzami i recenzjami) kosztuje 1 punkt (``rateLimit``
13.11.2026: 1 punkt dla 20 i dla 50 PR-ów na stronę), a koszt skanu rośnie z liczbą PR-ów zmienionych od wdrożenia
(Q13 liczy powtórzenia od wdrożenia, więc skan go nie ucina): strona na każde ``PAGE - 1`` PR-ów. Przy ok. 44 PR-ach
dziennie to ok. 16 stron na tydzień PR-ów, czyli ok. 420 punktów na przebieg po pół roku (ok. 8000 PR-ów), do tego
strona issues na każde 100 chwastów i ``pull_node`` na PR z ponad 100 komentarzami. Limit 1000 punktów przebieg
przekroczy po ok. 14 miesiącach; wtedy ``PAGE`` 50 (ten sam 1 punkt na stronę) daje 2,6 raza mniej stron.

Issue chwastu ma tytuł ``Chwast: R-KOD``, etykietę ``chwast`` (rejestr zakłada brakującą etykietę repozytorium)
i treść z szablonu Q15 bez wolnej prozy (``body``): sekcja „Korzeń” z opisem kodu z listy korzeni na bazie,
„Wystąpienia” z tabelą PR | Ważne | Szczebel wyrwania | Mechanizm i „Gotowe, gdy”. Etykietę ``ready-for-agent`` ma
tylko czoło kolejki chwastów (ADR 0034), więc nowe issue dostaje ją tylko wtedy, gdy kolejka (``queue``) jest pusta,
a z kilku nowych naraz tylko pierwsze. Gdy otwarte issue już jest, rejestr nie zmienia jego etykiet ani nie komentuje,
tylko zmienia jego treść: wiersze z rejestru zastępują wiersze z tym samym PR i Ważnym,
a pozostałe wiersze tabeli zostają; treść poza szablonem zostaje bez zmian z ostrzeżeniem. Dwie publikacje z tym
samym kodem w tej samej chwili mogą obie nie zobaczyć issue i obie je założyć, więc po założeniu rejestr czyta
otwarte issues jeszcze raz (``_duplicates``): każde nowsze ``Chwast: R-KOD`` niż najstarsze zamyka z komentarzem
``Duplikat #<najstarsze>``, a jego wiersze dopisuje do najstarszego. Bez blokady, bo każda publikacja czyta listę po
własnym założeniu, więc druga z nich widzi oba issues i zamyka to samo nowsze. Zamyka je merge PR z linią „Korzeń
z #<issue>: R-KOD” (``root_lines``, ``naprawia.close_fixed``).

Kolejność chwastów stoi w jednym otwartym issue z etykietą ``kolejka-chwastow`` (``QUEUE``), a czyta ją ``queue``,
jedna droga dla rejestru i dla ogrodnika. Treść to nagłówek „## Kolejka” z punktami ``- #N`` w kolejności brania
i nagłówek „## Poza kolejką” z chwastami, których nie bierze się osobno (wyrywa je program); każdy punkt ma jeden link
do issue tego repozytorium. Kolejka to otwarte chwasty z „Kolejki” w jej kolejności, a po nich otwarte chwasty spoza
obu list (założone później) w kolejności numerów; czoło to pierwszy. Inna liczba issues kolejki niż jedno albo treść
poza tym kształtem to ``ValueError``. Kolejkę rejestr czyta tylko wtedy, gdy ma założyć nowe issue, i to krok
najlepiej jak się da: przy każdym błędzie odczytu, bez względu na typ wyjątku, nie zakłada żadnego nowego issue
i podaje to ostrzeżeniem ``UWAGA`` z typem błędu, a otwarte issues chwastów uzupełnia jak zwykle, bo ich zmiana
kolejki nie potrzebuje.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
import json
import re
from typing import Any

import github
from repo import REMOTE, ROOT
import repo
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
CONSENT = re.compile(rf"ZGODA KORZEŃ: ({CODE.pattern})")
CONSENT_WORDS = "ZGODA KORZEŃ"
ADMIN = "admin"
WEED = "chwast"
READY = "ready-for-agent"
# Etykieta issue „Rejestr korzeni” z tygodniowym pomiarem (``tools/rejestr_korzeni_tydzien.py``), osobna od ``WEED``,
# żeby lista issues z etykietą ``chwast`` miała same chwasty.
REGISTRY = "rejestr-korzeni"
QUEUE = "kolejka-chwastow"
LABELS = {
    WEED: ("b60205", "Korzeń z Ważnym w co najmniej 2 PR-ach (ADR 0031)"),
    READY: ("0e8a16", "Gotowe do podjęcia przez agenta"),
    REGISTRY: ("5319e7", "Tygodniowy pomiar powtórzeń korzeni (ADR 0031)"),
}
QUEUE_HEADINGS = ("Kolejka", "Poza kolejką")
TITLE = "Chwast: {code}"
COLUMNS = ("PR", "Ważne", "Szczebel wyrwania", "Mechanizm")
HEADINGS = ("Korzeń", "Wystąpienia", "Gotowe, gdy")
# Jednostki treści issue w szablonie (``szablon_werdyktu.items``): nagłówki, linia opisu kodu, blok tabeli (dowolnego
# rodzaju, bo GitHub owija tabelę we własny znacznik, a tabelę liczy ``_Table``) i punkt „Gotowe, gdy”.
SHAPE = (("h2", HEADINGS[0]), ("line", ""), ("h2", HEADINGS[1]), ("*", ""), ("h2", HEADINGS[2]), ("point", ""))
DONE = (
    "PR z linią „Korzeń z #N: {code}” w opisie, gdzie N to numer tego issue, wyrywa korzeń szczebel wyżej niż "
    "najwyższy w tabeli (ADR 0031, Q11), a tools/scal_pr.py zamyka to issue przy merge'u tego PR."
)
NONE = "-"
PAGE = 20
_ESCAPED = re.compile(r"([\\`*_\[\]<>|~&])")
DUPLICATE = "Duplikat #{number}"
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
ISSUES_QUERY = """
query($owner: String!, $name: String!, $label: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], states: OPEN, first: 100, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title body bodyHTML }
    }
  }
}
"""
CONNECTIONS = ("comments", "reviews")


@dataclass(frozen=True)
class Block:
    """Blok sekcji ``## Korzeń``: nagłówek bez kodu (``W1 r2`` albo ``Czerwony main #N``), kod i jednostki pod nim."""

    heading: str
    code: str
    items: tuple[Item, ...]

    def rung(self) -> tuple[str, str] | None:
        """Litera szczebla i mechanizm z pierwszej linii ``Szczebel: (x) - mechanizm``; ``None`` bez niej."""

        first = self.items[0] if self.items else None
        found = szablon_werdyktu.RUNG_FIELD.fullmatch(first.text) if first is not None and first.kind == "line" else None
        return (found[1], found[2]) if found else None

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
    (``None``, gdy żaden nie podał kodu w szablonie), rundą ``decided`` tego werdyktu i chwilą Ważnego ``since``, czyli
    utworzenia werdyktu ``FAIL`` rundy ``round`` (``None`` bez chwili); rozstrzygnięcie innym kodem (Q25) zmienia kod,
    a nie chwilę."""

    heading: str
    round: int
    code: str | None
    decided: int
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
                found[f"{label} r{current.number}"] = Major(f"{label} r{current.number}", current.number, None, current.number, _moment(current.verdict.when))
            for root in current.findings.majors:
                if root.code is not None:
                    key = f"{root.label} r{current.number}"
                    found[key] = replace(found[key], code=root.code)
        for resolution in current.findings.resolutions:
            key = f"{resolution.label} r{resolution.round}"
            if key in found:
                found[key] = replace(found[key], code=resolution.code, decided=current.number)
            else:
                strays.append((current.number, resolution))
    return found, strays


@dataclass(frozen=True)
class Occurrence:
    """Wystąpienie kodu ``code`` w PR ``pull``: Ważne (``W1 r2``) albo ``Czerwony main #N``, runda werdyktu, który dał
    kod (0 dla czerwonego `main`), litera szczebla i mechanizm wyrwania (``NONE``, gdy ich nie ma), chwila wystąpienia
    ``when`` (Ważnego: utworzenie werdyktu ``FAIL`` jego rundy, ``Major.since``; czerwonego `main`: merge PR) i chwila
    merge'a PR (``None``: nie scalony)."""

    code: str
    pull: int
    major: str
    decided: int
    rung: str
    mechanism: str
    when: datetime
    merged: datetime | None = None


def read(repository: str, deployed: datetime | None, *, skip: int | None = None) -> list[Occurrence]:
    """Wystąpienia kodów w PR-ach ``repository`` (``właściciel/nazwa``) po chwili wdrożenia szablonu ``deployed``
    (``None``: szablon niewdrożony, więc żadnych), bez PR ``skip``, w kolejności PR i Ważnego. Błąd GitHuba to wyjątek."""

    if deployed is None:
        return []
    found = []
    for node in _pulls(repository, deployed):
        if node["number"] != skip:
            found.extend(occurrences(node if _complete(node) else pull_node(repository, node["number"]), deployed))
    return sorted(found, key=_order)


def occurrences(node: dict[str, Any], deployed: datetime) -> list[Occurrence]:
    """Wystąpienia kodów w PR z węzła GraphQL ``node`` (``FIELDS``, każdy komentarz i każda recenzja) po chwili
    wdrożenia ``deployed``; tylko PR scalony (``mergedAt``) ma szczebel i mechanizm wyrwania z sekcji ``## Korzeń``."""

    pull = _pull(node)
    merged = _moment(node["mergedAt"]) if node.get("mergedAt") else None
    blocks = _blocks(pull, str(node["bodyHTML"])) if merged is not None else {}
    found = []
    verdicts = [verdict for verdict in (werdykt_pr.read(verdict, pull.head) for verdict in pull.verdicts) if verdict is not None]
    if werdykt_pr.rule_applies(pull, deployed) and any(verdict.decision == "FAIL" for verdict in verdicts):
        rounds = werdykt_pr.rounds(pull, werdykt_pr.from_graphql)
        for major in majors(rounds)[0].values():
            if major.code is not None and major.since is not None and major.since >= deployed:
                found.append(Occurrence(major.code, pull.number, major.heading, major.decided, *_uprooting(blocks.get(major.heading)), major.since, merged))
    if merged is not None and merged >= deployed:
        found.extend(Occurrence(block.code, pull.number, heading, 0, *_uprooting(block), merged, merged) for heading, block in blocks.items() if heading.startswith("Czerwony"))
    return sorted(found, key=_order)


def earlier(found: Iterable[Occurrence], before: datetime | None) -> dict[str, tuple[str, tuple[int, ...]]]:
    """Najwyższy szczebel (najbliżej (a)) wyrwania każdego kodu i PR-y, w których go użyto, z wystąpień ze szczeblem
    w PR-ach scalonych przed chwilą ``before`` (``None``: w każdym scalonym)."""

    best: dict[str, tuple[str, tuple[int, ...]]] = {}
    for occurrence in found:
        if occurrence.rung == NONE or occurrence.merged is None or (before is not None and occurrence.merged >= before):
            continue
        rung, pulls = best.get(occurrence.code, ("z", ()))
        if occurrence.rung < rung:
            best[occurrence.code] = (occurrence.rung, (occurrence.pull,))
        elif occurrence.rung == rung and occurrence.pull not in pulls:
            best[occurrence.code] = (rung, (*pulls, occurrence.pull))
    return best


def consents(pull: Pull) -> frozenset[str]:
    """Kody z linii ``ZGODA KORZEŃ: R-KOD`` (linia akapitu albo punkt listy, poza kodem) w komentarzach i recenzjach
    ``pull`` od kont z prawem ``admin`` do repozytorium, czyli właściciela repo (Q11). Błąd GitHuba to wyjątek."""

    codes: set[str] = set()
    admins: dict[str, bool] = {}
    for verdict in pull.verdicts:
        body = str(verdict.get("body") or "")
        if CONSENT_WORDS not in body:
            continue
        units = szablon_werdyktu.items(github.html_markdownu(body, pull.repository))
        given = {found[1] for item in units if item.kind in {"line", "point"} and (found := CONSENT.fullmatch(item.text))}
        author = verdict.get("author")
        login = str(author.get("login", "")) if isinstance(author, dict) else ""
        if given and login and _admin(login, pull.repository, admins):
            codes |= given
    return frozenset(codes)


def _admin(login: str, repository: str, known: dict[str, bool]) -> bool:
    if login not in known:
        known[login] = json.loads(github.gh("api", f"repos/{repository}/collaborators/{login}/permission"))["permission"] == ADMIN
    return known[login]


def after_verdict(number: int, text: str, base: str, deployed: datetime | None, repository: str) -> str:
    """Dopisek linii ``WERDYKT OK`` po publikacji werdyktu ``text`` na PR ``number`` repozytorium ``repository``: kody,
    które ten werdykt nadał Ważnemu, z wystąpieniem w innym PR to chwasty, a dla każdego ``settle`` zakłada albo
    uzupełnia issue. Werdykt już jest na PR, więc każdy błąd to tylko ostrzeżenie w dopisku."""

    command = "tools/chwasty.py"
    try:
        node = pull_node(repository, number)
        current = _pull(node)
        verdicts = [verdict for verdict in (werdykt_pr.read(verdict, current.head) for verdict in current.verdicts) if verdict is not None and verdict.decision is not None]
        if not verdicts or werdykt_pr.text_lines(verdicts[-1].body) != werdykt_pr.text_lines(text):
            return f" | UWAGA: GitHub nie podał jeszcze opublikowanego werdyktu, chwastów nie sprawdzono; uruchom {command}"
        own = occurrences(node, deployed) if deployed is not None else []
        codes = {occurrence.code for occurrence in own if occurrence.decided == len(verdicts)}
        if not codes:
            return ""
        lines = settle([*own, *read(current.repository, deployed, skip=number)], codes, current.repository, base, write=True)
    except Exception as error:  # noqa: BLE001 - werdykt jest już opublikowany, a błąd chwastów podaje dopisek
        return f" | UWAGA: chwastów nie sprawdzono ({error}); uruchom {command}"
    return "".join(" | " + line.replace(" | ", " ", 1) for line in lines)


def returned(found: Iterable[Occurrence]) -> list[str]:
    """Chwasty: kody z wystąpieniami w co najmniej 2 różnych PR-ach, po kolei."""

    pulls: dict[str, set[int]] = {}
    for occurrence in found:
        pulls.setdefault(occurrence.code, set()).add(occurrence.pull)
    return sorted(code for code, numbers in pulls.items() if len(numbers) >= 2)


@dataclass(frozen=True)
class Row:
    """Wiersz tabeli „Wystąpienia” issue chwastu: PR, Ważne, szczebel (``(c)`` albo ``-``) i mechanizm."""

    pull: int
    major: str
    rung: str
    mechanism: str


def settle(found: Sequence[Occurrence], codes: Iterable[str] | None, repository: str, base: str, *, write: bool) -> list[str]:
    """Issues chwastów dla kodów z ``codes`` (``None``: każdego) z wystąpieniami ``found`` w co najmniej 2 PR-ach:
    zakłada brakujące issue (i brakujące etykiety; ``ready-for-agent`` tylko czołu pustej kolejki, a bez odczytanej
    kolejki żadnego), a w otwartym zmienia tabelę wystąpień. Bez ``write`` niczego nie zapisuje, tylko podaje, co by
    zrobił. Linia ``CHWAST | …`` na każdą akcję i ostrzeżenie."""

    wanted = None if codes is None else set(codes)
    by_code: dict[str, list[Occurrence]] = {}
    for occurrence in found:
        by_code.setdefault(occurrence.code, []).append(occurrence)
    weeds = [code for code in returned(found) if wanted is None or code in wanted]
    if not weeds:
        return []
    api = github.GhApi()
    present = weed_issues(repository)
    issues = {str(issue["title"]): issue for issue in sorted(present, key=lambda issue: -int(issue["number"]))}
    new = [code for code in weeds if TITLE.format(code=code) not in issues]
    lead = False
    unread: Exception | None = None
    if new:
        try:
            lead = not queue(repository, present)
        except Exception as error:  # noqa: BLE001 - odczyt kolejki to krok najlepiej jak się da: każdy błąd wstrzymuje tylko założenie
            unread = error
    described = _descriptions(base)
    actions: list[github.Akcja] = []
    notes = []
    for code in weeds:
        fresh = {(row.pull, row.major): row for row in map(_row, by_code[code])}
        issue = issues.get(TITLE.format(code=code))
        if issue is None and unread is not None:
            notes.append(f"CHWAST | UWAGA: nie założono „{TITLE.format(code=code)}”, bo kolejki chwastów nie odczytano ({type(unread).__name__}: {unread}); popraw issue z etykietą {QUEUE} i uruchom tools/chwasty.py")
            continue
        if issue is None:
            labels = (WEED, READY) if lead and code == new[0] else (WEED,)
            actions.append(github.Zaloz(TITLE.format(code=code), body(code, described.get(code, NONE), list(fresh.values())), labels))
            continue
        kept = _rows(str(issue["bodyHTML"]), repository)
        if kept is None:
            notes.append(f"CHWAST | UWAGA: #{issue['number']} „{issue['title']}” nie ma treści w szablonie, dopisz wystąpienia ręcznie")
            continue
        rows = sorted({**{(row.pull, row.major): row for row in kept}, **fresh}.values(), key=lambda row: (row.pull, _natural(row.major)))
        if rows == kept:
            notes.append(f"CHWAST | #{issue['number']} „{issue['title']}” ma już każde wystąpienie")
        else:
            actions.append(github.Edytuj(int(issue["number"]), body(code, described.get(code, NONE), rows)))
    lines = create_labels(api, (WEED, READY), "CHWAST", write=write) if any(isinstance(action, github.Zaloz) for action in actions) else []
    if not write:
        return [*lines, *(f"CHWAST | bez zapisu: {github.opis(action)}" for action in actions), *notes]
    lines += github.wykonaj(api, actions, "CHWAST")
    created = [action.tytul for action in actions if isinstance(action, github.Zaloz)]
    return [*lines, *(_duplicates(api, created, repository, described) if created else []), *notes]


def _duplicates(api: github.GhApi, titles: Sequence[str], repository: str, described: dict[str, str]) -> list[str]:
    """Po założeniu issues z tytułami ``titles``: każde otwarte issue z takim tytułem nowsze niż najstarsze zamyka
    z komentarzem ``Duplikat #<najstarsze>``, a jego wiersze dopisuje do najstarszego."""

    issues: dict[str, list[dict[str, Any]]] = {}
    for issue in weed_issues(repository):
        if str(issue["title"]) in titles:
            issues.setdefault(str(issue["title"]), []).append(issue)
    actions: list[github.Akcja] = []
    notes = []
    for title, same in issues.items():
        if len(same) < 2:
            continue
        oldest, *newer = sorted(same, key=lambda issue: int(issue["number"]))
        tables = [_rows(str(issue["bodyHTML"]), repository) for issue in (oldest, *newer)]
        if any(table is None for table in tables):
            notes.append(f"CHWAST | UWAGA: „{title}” ma {len(same)} otwarte issues, a nie każde ma treść w szablonie; zostaw najstarsze #{oldest['number']} i dopisz wiersze ręcznie")
            continue
        merged = {(row.pull, row.major): row for table in reversed(tables) for row in table or []}
        rows = sorted(merged.values(), key=lambda row: (row.pull, _natural(row.major)))
        code = title.removeprefix(TITLE.format(code=""))
        if rows != tables[0]:
            actions.append(github.Edytuj(int(oldest["number"]), body(code, described.get(code, NONE), rows)))
        actions.extend(github.Zamknij(int(issue["number"]), DUPLICATE.format(number=oldest["number"])) for issue in newer)
    return [*github.wykonaj(api, actions, "CHWAST"), *notes]


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


def weed_issues(repository: str, label: str = WEED) -> list[dict[str, Any]]:
    """Otwarte issues ``repository`` z etykietą ``label``: numer, tytuł, treść i jej HTML (``bodyHTML``), w kolejności
    założenia; strona GraphQL na 100 issues."""

    owner, name = repository.split("/")
    found: list[dict[str, Any]] = []
    after = None
    while True:
        page = _graphql(ISSUES_QUERY, owner=owner, name=name, label=label, after=after)["repository"]["issues"]
        found.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return found
        after = page["pageInfo"]["endCursor"]


def queue(repository: str, weeds: Iterable[dict[str, Any]] | None = None) -> list[int]:
    """Kolejka chwastów (ADR 0034): numery otwartych issues chwastów ``weeds`` (``None``: czytane z GitHuba) w kolejności
    brania według jedynego otwartego issue z etykietą ``QUEUE``; czoło kolejki to pierwszy numer."""

    found = weed_issues(repository, QUEUE)
    if len(found) != 1:
        raise ValueError(f"kolejka chwastów: {len(found)} otwartych issues z etykietą {QUEUE}, a ma być jedno")
    lists: dict[str, list[int]] = {}
    for item in szablon_werdyktu.items(str(found[0]["bodyHTML"])):
        if item.kind == "h2" and item.text in QUEUE_HEADINGS and item.text not in lists:
            lists[item.text] = []
        elif item.kind == "point" and lists and len(item.links) == 1 and item.links[0].w(repository) and item.links[0].rodzaj == "issue":
            lists[list(lists)[-1]].append(item.links[0].numer)
        else:
            raise ValueError(f"kolejka chwastów #{found[0]['number']}: {item.shown()} poza kształtem „## Kolejka” i „## Poza kolejką” z punktami „- #N”")
    listed = [number for numbers in lists.values() for number in numbers]
    if tuple(lists) != QUEUE_HEADINGS or len(set(listed)) != len(listed):
        raise ValueError(f"kolejka chwastów #{found[0]['number']}: nagłówki {list(lists)} zamiast {list(QUEUE_HEADINGS)} albo numer w dwóch punktach")
    present = {int(issue["number"]) for issue in (weed_issues(repository) if weeds is None else weeds)}
    return [number for number in lists[QUEUE_HEADINGS[0]] if number in present] + sorted(present - set(listed))


def body(code: str, description: str, rows: Sequence[Row]) -> str:
    """Treść issue chwastu ``code`` z szablonu Q15: opis kodu z listy, tabela wystąpień i „Gotowe, gdy”."""

    lines = [f"## {HEADINGS[0]}", "", f"{code}: {_cell(description)}", "", f"## {HEADINGS[1]}", "", f"| {' | '.join(COLUMNS)} |", f"|{' --- |' * len(COLUMNS)}"]
    lines += [f"| #{row.pull} | {_cell(row.major)} | {_cell(row.rung)} | {_cell(row.mechanism)} |" for row in rows]
    return "\n".join([*lines, "", f"## {HEADINGS[2]}", "", f"- {DONE.format(code=code)}", ""])


def _cell(text: str) -> str:
    """Tekst komórki, który renderer GitHuba pokaże dosłownie, więc odczyt tabeli (``_rows``) odda ten sam tekst."""

    return _ESCAPED.sub(r"\\\1", text)


def _row(occurrence: Occurrence) -> Row:
    return Row(occurrence.pull, occurrence.major, NONE if occurrence.rung == NONE else f"({occurrence.rung})", occurrence.mechanism)


def _rows(html: str, repository: str) -> list[Row] | None:
    """Wiersze tabeli „Wystąpienia” z HTML treści issue (``bodyHTML``); ``None``, gdy treść nie jest w szablonie: inne
    jednostki niż ``SHAPE``, inna liczba tabel niż jedna, inne kolumny albo wiersz bez jednego linku do PR tego
    repozytorium w pierwszej komórce."""

    units = szablon_werdyktu.items(html)
    parser = _Table()
    parser.feed(html)
    parser.close()
    shape = [(item.kind, item.text if item.kind == "h2" else "") for item in units]
    if parser.tables != 1 or len(shape) != len(SHAPE) or any(expected not in {kind, "*"} or text != heading for (kind, text), (expected, heading) in zip(shape, SHAPE, strict=True)):
        return None
    if not parser.rows or [text for text, _ in parser.rows[0]] != list(COLUMNS):
        return None
    rows = []
    for cells in parser.rows[1:]:
        links = [link for link in cells[0][1] if link.w(repository) and link.rodzaj == "pull_request"] if len(cells) == len(COLUMNS) else []
        if len(links) != 1 or cells[0][0] != f"#{links[0].numer}":
            return None
        rows.append(Row(links[0].numer, cells[1][0], cells[2][0], cells[3][0]))
    return rows


class _Table(HTMLParser):
    """Wiersze tabel HTML renderera GitHuba: tekst każdej komórki (``th`` albo ``td``) i jej linki do issues i PR-ów."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, list[github.LinkGithuba]]]] = []
        self.tables = 0
        self._cell: tuple[list[str], list[github.LinkGithuba]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables += 1
        elif tag == "tr":
            self.rows.append([])
        elif tag in {"td", "th"} and self.rows:
            self._cell = ([], [])
        elif tag == "a" and self._cell is not None and (link := github.link_githuba(attrs)) is not None:
            self._cell[1].append(link)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            self.rows[-1].append((" ".join("".join(self._cell[0]).split()), self._cell[1]))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell[0].append(data)


def _descriptions(base: str) -> dict[str, str]:
    """Opisy kodów z listy korzeni na ``origin/<base>``; lista, która się nie wczytuje, daje kody bez opisu."""

    try:
        return szablon_werdyktu.descriptions(repo.git(ROOT, "show", f"refs/remotes/{REMOTE}/{base}:{szablon_werdyktu.LIST}"))
    except Exception:  # noqa: BLE001 - bez listy issue dostaje opis „-”, a kod i wystąpienia zostają
        return {}


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


def _uprooting(block: Block | None) -> tuple[str, str]:
    if block is None:
        return NONE, NONE
    if (rung := block.rung()) is not None:
        return rung
    uprooted = block.uprooted()
    return (NONE, f"Wyrwany w #{uprooted}") if uprooted is not None else (NONE, NONE)


def _moment(when: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(when))
    except ValueError:
        return None


def _natural(major: str) -> tuple[int, ...]:
    return (major.startswith("Czerwony"), *map(int, re.findall(r"\d+", major)))


def _order(occurrence: Occurrence) -> tuple[int, tuple[int, ...]]:
    return occurrence.pull, _natural(occurrence.major)
