"""Dokumenty z regułami łamią linie tylko na końcu zdania: zmiana jednego słowa zmienia jedną linię, nie cały akapit.

Frontmatter skilla (YAML między liniami ``---`` na początku pliku) to nie proza, więc go pomija.
``GLOSSARY.md`` i ``README.md`` są jeszcze łamane twardo, więc dołączą do ``DOCUMENTS`` po przeformatowaniu.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re

from tests.fixtures.git_repo import git

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("AGENTS.md", "CODING_STANDARDS.md", "docs/agents/pr-i-ci.md", ".agents/skills/przeglad/SKILL.md", "docs/agents/skille.md")
FENCE = "```"
NOT_PROSE = re.compile(r"\s*(?:#+\s|\||```)")
LIST_ITEM = re.compile(r"\s*(?:-|\d+\.)\s")
SENTENCE_END = re.compile(r"[.!?][)”\"*]*$")


def _prose(line: str) -> bool:
    return bool(line.strip()) and not NOT_PROSE.match(line)


def _lines_broken_mid_sentence(text: str) -> Iterator[int]:
    """Numery linii prozy, które kończą się w środku zdania, choć następna linia ciągnie ten sam akapit."""

    lines = text.splitlines()
    fenced = False
    front_matter = lines[:1] == ["---"]
    for number, (line, following) in enumerate(zip(lines, [*lines[1:], ""], strict=True), start=1):
        if front_matter:
            front_matter = number == 1 or line != "---"
        elif line.lstrip().startswith(FENCE):
            fenced = not fenced
        elif (
            not fenced
            and _prose(line)
            and _prose(following)
            and not LIST_ITEM.match(following)
            and not SENTENCE_END.search(line.rstrip())
        ):
            yield number


def test_dokument_regul_lamie_linie_tylko_na_koncu_zdania() -> None:
    broken = [
        f"{name}:{number}: linia kończy się w środku zdania, a linia {number + 1} ciągnie ten sam akapit"
        for name in DOCUMENTS
        for number in _lines_broken_mid_sentence((ROOT / name).read_text(encoding="utf-8"))
    ]

    assert not broken, "\n".join(
        [
            *broken,
            "Łam linię tylko na końcu zdania: dołącz następną linię do tej i zacznij nową linię dopiero od nowego "
            "zdania. Nowe zdanie elementu listy wcinaj o szerokość jego znacznika (dwie spacje dla „- ”).",
        ]
    )


def test_sprawdzenie_pomija_kod_tabele_i_naglowki_a_wskazuje_lamanie_w_srodku_zdania() -> None:
    document = "\n".join(
        [
            "# Nagłówek bez kropki",
            "Akapit łamany",
            "w środku zdania.",
            "Lista:",
            "- Element listy łamany",
            "  w środku zdania.",
            "  Drugie zdanie w nowej linii.",
            "- Element bez kropki",
            "1. Element numerowany bez kropki",
            "",
            "Akapit łamany przed numerem PR",
            "#285 ciągnie to samo zdanie.",
            "Uruchom:",
            "```",
            "polecenie --flaga",
            "  --druga-flaga",
            "```",
            "Tekst przed nagłówkiem",
            "## Nagłówek",
            "| kolumna | bez kropki |",
            "| --- | --- |",
            "",
            "Komunikat brzmi „Plik jest niedostępny.”",
            "(Całe zdanie w nawiasie.)",
            'Napisz "gotowe."',
            "**Pogrubione zdanie.**",
            "Zdanie z wykrzyknikiem!",
            "Zdanie z pytaniem?",
            "Ostatnia linia bez kropki",
        ]
    )

    assert list(_lines_broken_mid_sentence(document)) == [2, 5, 11]


def test_sprawdzenie_pomija_frontmatter_skilla_a_sprawdza_proze_po_nim() -> None:
    document = "\n".join(
        [
            "---",
            "name: skill",
            "description: Opis",
            "---",
            "",
            "Akapit łamany",
            "w środku zdania.",
        ]
    )

    assert list(_lines_broken_mid_sentence(document)) == [6]


MAKS_CLAIM = re.compile(r"\b(?:zgod|decyzj)\w*[\s#*\"'/]+Maksa\b", re.IGNORECASE)
GITHUB_SOURCE = re.compile(r"(?<![\w&])#\d+\b|https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+")
CLAIM_SENTENCE_END = re.compile(r"[.!?](?=\s)|\n[ \t#]*\n")
CLAIM_DIRECTORIES = ("src", "tests", "tools", "docs/adr")
ROLE = "opis roli: mówi, kto decyduje, a nie, że Maks już zdecydował"
T3_THREAD = "decyzja w wątku T3 bez linku do GitHuba"
NOT_GITHUB = "wskazuje ADR albo GLOSSARY zamiast issue lub PR z decyzją"
SAME_AS_HEADER = "ta sama decyzja co nagłówek ADR (spec #313), bez własnego odwołania"
OTHER_PROGRAM = "plik zmienia program architektury (WS-A, WS-B, WS-C), więc ten PR go nie rusza"
KNOWN_UNSOURCED: dict[tuple[str, str], str] = {
    ("docs/adr/0014-tata-dostaje-tylko-wydania.md", "Dowolny MAJOR to decyzja Maksa z 23.10."): SAME_AS_HEADER,
    ("docs/adr/0014-tata-dostaje-tylko-wydania.md", "commitu: decyzja Maksa z 23.10."): SAME_AS_HEADER,
    ("docs/adr/0020-ci-w-poziomach.md", "Zaakceptowana (decyzje Maksa z 26.10)."): T3_THREAD,
    ("docs/adr/0020-ci-w-poziomach.md", "Test kształtu planu bramki dla dwóch wzorcowych PR-ów, małego tylko z testami i zmiany Centrum, ma limit liczby zadań i prognozy czasu; przekroczenie to decyzja Maksa."): ROLE,
    ("docs/adr/0021-mutacje-noca.md", "Zaakceptowana (decyzja Maksa z 29.10: „nie możemy na każdy nowy PR odpalać mutacji”)."): f"{T3_THREAD}; {OTHER_PROGRAM}",
    ("docs/adr/0022-uklad-tools-i-spis-narzedzi.md", "Zaakceptowana na próbę (decyzja Maksa z 31.10 po hillclimbie przeglądu 30–31.10, dźwignia L4+L4b)."): T3_THREAD,
    ("docs/adr/0023-przeglad-jako-skill.md", "Zaakceptowana na próbę (decyzja Maksa z 31.10 w wątku T3 po hillclimbie przeglądu 30–31.10)."): T3_THREAD,
    ("docs/adr/0023-przeglad-jako-skill.md", "Decyzja Maksa z 31.10: dziura w sprawdzeniu daje `FAIL`, wąsko."): T3_THREAD,
    ("docs/adr/0025-regula-danych-wysylki-do-skrzynki.md", "Wcześniej A i B stały tu jako decyzja Maksa z 5.11.2026, a pierwszy wiersz tylko"): f"historia zmian ADR; {OTHER_PROGRAM}",
    ("docs/adr/0025-regula-danych-wysylki-do-skrzynki.md", "## Pewniki i granica dziedziny (decyzja Maksa z 6.11.2026)"): f"nagłówek sekcji, odwołania stoją w nagłówku ADR; {OTHER_PROGRAM}",
    ("src/rozliczenia/raw_orders.py", "Pamięć reguły danych zna każdy wiersz w jednym położeniu (decyzja Maksa z 5.11.2026, ADR 0025): pierwszy wiersz bloku"): NOT_GITHUB,
    ("tests/fixtures/fakt_domeny.py", '"""Klasa przypadku → powód z zgodą Maksa."""'): ROLE,
    ("tests/test_centrum_logi_uruchomienia.py", "# cytuje je potem w Uwadze. Każdy wiersz ma jedno położenie (decyzja Maksa z 5.11.2026, ADR 0025): pierwszy wiersz bloku"): f"{NOT_GITHUB}; {OTHER_PROGRAM}",
    ("tests/test_centrum_uporzadkowanie_intermax.py", "# strażnik musi je znać tam, gdzie stoją. Każdy wiersz ma jedno położenie (decyzja Maksa z 5.11.2026, ADR 0025):"): NOT_GITHUB,
    ("tests/test_ksztalt_bramki.py", "limitu to decyzja Maksa."): ROLE,
    ("tests/test_ksztalt_bramki.py", 'f" {praca.zrodlo}; podniesienie limitu to decyzja Maksa"'): ROLE,
    ("tests/test_uszkodzone_wejscia.py", "# Znane przypadki: powód, termin i zgoda Maksa. Po terminie przypadek znów pada, a naprawiony pada od razu (strict)."): ROLE,
    ("tests/test_wlasnosci_dopasowania_tekstu.py", "# Samo ``SA`` doklejone za nazwą (``NetiaSA``) to dopisek ``S.A.`` bez spacji, więc ten sam operator (decyzja Maksa"): NOT_GITHUB,
    ("tests/test_wlasnosci_dopasowania_tekstu.py", "# Decyzja Maksa z 6.11.2026 (GLOSSARY.md, Kolor operatora): dopisek S.A. bez spacji przed nim to dalej Netia."): NOT_GITHUB,
    ("tests/test_wycena_efenix.py", '"""Decyzja Maksa z 5.11.2026: zlecenie z wyceną, która już jest, ale bez daty wykonania, dostaje datę z ``DATA`` tak'): f"ta sama decyzja co ADR 0026 (#965); {OTHER_PROGRAM}",
}


def _line_end(text: str, at: int) -> int:
    end = text.find("\n", at)
    return len(text) if end < 0 else end


def _line_start(text: str, at: int) -> int:
    return text.rfind("\n", 0, at) + 1


def _two_lines_around(text: str, start: int, end: int) -> tuple[int, int]:
    before = _line_start(text, max(_line_start(text, max(_line_start(text, start) - 1, 0)) - 1, 0))
    return before, _line_end(text, _line_end(text, _line_end(text, end) + 1) + 1)


def _unsourced_claims(text: str) -> Iterator[tuple[int, str]]:
    for claim in MAKS_CLAIM.finditer(text):
        line_start = _line_start(text, claim.start())
        window_start, window_end = _two_lines_around(text, claim.start(), claim.end())
        ends = [end.end() for end in CLAIM_SENTENCE_END.finditer(text, window_start, claim.start() + 1)]
        following = CLAIM_SENTENCE_END.search(text, claim.end(), window_end)
        if not GITHUB_SOURCE.search(text, ends[-1] if ends else window_start, following.start() if following else window_end):
            yield text.count("\n", 0, claim.start()) + 1, text[line_start : _line_end(text, claim.start())].strip()


def _unsourced_in(root: Path) -> dict[tuple[str, str], int]:
    names = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *CLAIM_DIRECTORIES).split("\0")
    own = Path(__file__).resolve().name
    found = {}
    for name in sorted(filter(None, names)):
        content = (root / name).read_bytes() if Path(name).name != own and (root / name).is_file() else b"\0"
        for number, line in [] if b"\0" in content else _unsourced_claims(content.decode("utf-8", errors="replace")):
            found[(name, line)] = number
    return found


def _claim_problems(found: dict[tuple[str, str], int], known: dict[tuple[str, str], str]) -> list[str]:
    unsourced = [f"{name}:{number}: {line}" for (name, line), number in found.items() if (name, line) not in known]
    stale = [f"{name}: „{line}” nie jest już powołaniem bez odwołania, usuń jego wpis z KNOWN_UNSOURCED" for name, line in known.keys() - found.keys()]
    return [*unsourced, *sorted(stale)]


def test_kazde_powolanie_na_maksa_ma_odwolanie_do_githuba() -> None:
    problems = _claim_problems(_unsourced_in(ROOT), KNOWN_UNSOURCED)

    assert not problems, "\n".join(
        [
            *problems,
            "Powołanie na Maksa podaje w tym samym zdaniu #N issue albo PR albo adres issue lub PR na GitHubie, gdzie Maks "
            "to powiedział, żeby recenzent sprawdził je jednym krokiem.",
        ]
    )


def test_powolanie_bez_odwolania_w_swoim_zdaniu_jest_wskazane_a_z_odwolaniem_obok_przechodzi() -> None:
    document = "\n".join(
        [
            "Zaakceptowana (decyzja Maksa z 4.11.2026, #834).",
            "Zmieniona 5.11: decyzją Maksa",
            "obejmuje też proces zabity",
            "(PR #948).",
            "Rozstrzyga issue #91. Zmieniona: decyzja Maksa bez odwołania.",
            "# Wyjątek z terminem, zgoda",
            "# Maksa 5.11.2026: test nie biegnie na Windows.",
            "Za zgodą Maksa (https://github.com/maximiseartai/MAXIMISEART-Dad/issues/979#issuecomment-1).",
            "Zgodzie Maksa z 6.11 przeczy &#123; encja HTML.",
            "",
            "Decyzje Maksa z 26.10",
            "",
            "#12 stoi w innym akapicie.",
            "Podniesienie limitu to decyzja Maksa",
            "i ciągnie się",
            "przez trzy linie",
            "do #77 za daleko.",
        ]
    )

    assert list(_unsourced_claims(document)) == [
        (5, "Rozstrzyga issue #91. Zmieniona: decyzja Maksa bez odwołania."),
        (6, "# Wyjątek z terminem, zgoda"),
        (9, "Zgodzie Maksa z 6.11 przeczy &#123; encja HTML."),
        (11, "Decyzje Maksa z 26.10"),
        (14, "Podniesienie limitu to decyzja Maksa"),
    ]


def test_znane_powolanie_przechodzi_nowe_jest_wskazane_a_wpis_bez_powolania_wywraca_test() -> None:
    found = {("src/a.py", "decyzja Maksa z 1.11"): 3, ("src/b.py", "zgoda Maksa"): 7}
    known = {("src/a.py", "decyzja Maksa z 1.11"): "powód", ("src/c.py", "usunięte powołanie"): "powód"}

    assert _claim_problems(found, known) == [
        "src/b.py:7: zgoda Maksa",
        "src/c.py: „usunięte powołanie” nie jest już powołaniem bez odwołania, usuń jego wpis z KNOWN_UNSOURCED",
    ]
