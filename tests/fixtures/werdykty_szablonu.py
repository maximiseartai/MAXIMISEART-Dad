"""Treści werdyktów pod dwiema pierwszymi liniami i ich HTML z renderera GitHuba dla testów szablonu werdyktu (ADR 0031).

``PRZECHODZA`` to treści w szablonie, ``ODMOWY`` treści poza nim z liczbami z linii ``Znaleziska:`` i fragmentem
przyczyny odmowy, a ``WERDYKTY`` treści testów przepływu ``tools/scal_pr.py``. Wymagania bierzemy z docstringu
``szablon_werdyktu`` i ze skilla ``przeglad``: pola liczą się tylko poza blokami kodu, które wyznacza GitHub
(ogrodzone ``` i ~~~ oraz wcięte o cztery spacje), Dowód ma najwyżej 5 linii po najwyżej 300 znaków.

``werdykty_szablonu.json`` trzyma HTML każdej treści z ``gh api markdown`` (``mode=gfm``, ``context`` to ``REPO``),
a testy podają go zamiast GitHuba, więc biegną bez sieci. Po zmianie treści w tym pliku albo renderera GitHuba
odśwież plik (jedno wywołanie ``gh`` na treść, po kolei):

    .venv/bin/python tests/fixtures/werdykty_szablonu.py
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
import subprocess

REPO = "maximiseartai/MAXIMISEART-Dad"
RENDERED = Path(__file__).with_name("werdykty_szablonu.json")
LINES = (
    "### W1. Odmowa gubi przyczynę.",
    "Gdzie: tools/scal_pr.py:149",
    "Dowód: tools/mutacje.py --plik tools/scal_pr.py: NIEWYKRYTA",
    "Korzeń: R-BEZ-TESTU - nowa gałąź bez testu zachowania.",
    "Szczebel: (c) - test zachowania łapie klasę.",
    "### D1. Nieaktualne zdanie.",
    "Gdzie: AGENTS.md:60",
    "## Sprawdzone",
    "- szybko: SZYBKO OK",
)
HEADING, WHERE, EVIDENCE, ROOT, RUNG, MINOR, MINOR_WHERE, CHECKED, POINT = LINES
QUOTE = "cytat z polem albo nagłówkiem w Dowodzie ujmij w blok kodu ```"


def _text(*lines: str) -> str:
    return "\n".join(lines)


def _replaced(old: str, *new: str) -> str:
    """Treść szablonu, w której linia ``old`` ustępuje liniom ``new`` (bez nich: znika)."""

    index = LINES.index(old)
    return _text(*LINES[:index], *new, *LINES[index + 1 :])


TEMPLATE = _text(*LINES)
# Pole ``Idiom:`` po Szczeblu w trzech postaciach z ADR 0036 i Idiom, który ``szablon_werdyktu.findings`` z niego czyta:
# id reguły, klasa idiomu bez reguły i wcześniejsze Ważne (PR, Ważne, runda).
IDIOMY: dict[str, tuple[str, tuple[str | None, str | None, tuple[int, str, int] | None]]] = {
    "drugie-wystapienie": ("Idiom: komentarz-w-src jak #1553 W1 r2", ("komentarz-w-src", None, (1553, "W1", 2))),
    "ucieczka-reguly": ("Idiom: os.name", ("os.name", None, None)),
    "bez-reguly": ("Idiom: bez reguły stan-kroku jak #1553 W2 r1", (None, "stan-kroku", (1553, "W2", 1))),
}
PRZECHODZA = {
    "szablon": TEMPLATE,
    "nowy-kod-spoza-listy": _replaced(ROOT, "Korzeń: NOWY R-NOWY-KOD - opis kodu, którego nie ma na liście."),
    "szczebel-e": _replaced(RUNG, "Szczebel: (e) - punkt w „Co jest porażką”, bo (a)–(d) nie działają."),
    "dowod-5-linii": _replaced(EVIDENCE, "Dowód: tools/mutacje.py", *(f"linia {number}" for number in range(2, 6))),
    "dowod-pod-polem": _replaced(EVIDENCE, "Dowód:", "polecenie", "wynik"),
    "5-punktow-sprawdzone": _text(*LINES, *(f"- punkt {number}" for number in range(2, 6))),
    "punkty-gwiazdka-i-luzna-lista": _replaced(POINT, "* szybko: SZYBKO OK", "", "* diff przeczytany", "", "* sondy"),
    "cytat-pola-i-naglowka-w-bloku-kodu": _replaced(EVIDENCE, "Dowód: odmowa --werdykt:", "```", "    Korzeń: R-NIE-MA - cytat", "### W9. cytat", "```"),
    "cytat-pola-w-bloku-tyld": _replaced(EVIDENCE, "Dowód: grep:", "~~~text", "Gdzie: tools/x.py:3", "Szczebel: (a) - cytat", "~~~"),
    "cytat-pola-we-wcietym-bloku-kodu": _replaced(EVIDENCE, "Dowód: grep:", "", "    Gdzie: tools/x.py:3", "    Korzeń: R-NIE-MA - cytat", ""),
    "linia-dowodu-300-znakow-w-bloku-kodu": _replaced(EVIDENCE, "Dowód:", "```", "x" * 300, "```"),
    **{f"idiom-{name}": _replaced(RUNG, RUNG, line) for name, (line, _) in IDIOMY.items()},
}
ODMOWY: dict[str, tuple[str, tuple[int, int], str]] = {
    "brak-pola-gdzie": (_replaced(WHERE), (1, 1), "W1: pola w kolejności Gdzie, Dowód, Korzeń, Szczebel, a po nagłówku"),
    "puste-pole-gdzie": (_replaced(WHERE, "Gdzie:"), (1, 1), "W1: puste pole Gdzie"),
    "puste-pole-dowod": (_replaced(EVIDENCE, "Dowód:"), (1, 1), "W1: puste pole Dowód"),
    "drobne-z-pustym-gdzie": (_replaced(MINOR_WHERE, "Gdzie:"), (1, 1), "D1: puste pole Gdzie"),
    "dowod-przed-gdzie": (_text(HEADING, EVIDENCE, WHERE, *LINES[3:]), (1, 1), "W1: pola w kolejności Gdzie, Dowód, Korzeń, Szczebel, a po nagłówku"),
    "szczebel-przed-korzeniem": (_text(*LINES[:3], RUNG, ROOT, *LINES[5:]), (1, 1), f"a po Dowodzie jest linia „{RUNG}” ({QUOTE})"),
    "wazne-bez-korzenia": (_replaced(ROOT), (1, 1), f"a po Dowodzie jest linia „{RUNG}”"),
    "wazne-bez-szczebla": (_replaced(RUNG), (1, 1), "W1: pola w kolejności Gdzie, Dowód, Korzeń, Szczebel, a po Korzeniu jest koniec"),
    "kod-spoza-listy": (_replaced(ROOT, "Korzeń: R-NIE-MA - kod spoza listy."), (1, 1), "W1: kod R-NIE-MA spoza listy"),
    "nowy-kod-z-listy": (_replaced(ROOT, "Korzeń: NOWY R-BEZ-TESTU - kod, który już jest."), (1, 1), "W1: NOWY R-BEZ-TESTU: ten kod jest już na liście"),
    "nowy-bez-opisu": (_replaced(ROOT, "Korzeń: NOWY R-NOWY-KOD -"), (1, 1), "W1: „Korzeń: NOWY R-NOWY-KOD -” to nie"),
    "nowy-bez-myslnika-i-opisu": (_replaced(ROOT, "Korzeń: NOWY R-NOWY-KOD"), (1, 1), "W1: „Korzeń: NOWY R-NOWY-KOD” to nie"),
    "nowy-kod-malymi-literami": (_replaced(ROOT, "Korzeń: NOWY r-nowy-kod - kod małymi literami."), (1, 1), "W1: „Korzeń: NOWY r-nowy-kod"),
    "nowy-kod-bez-r": (_replaced(ROOT, "Korzeń: NOWY NOWY-KOD - kod bez R-."), (1, 1), "W1: „Korzeń: NOWY NOWY-KOD"),
    "nowy-kod-z-podkresleniem": (_replaced(ROOT, "Korzeń: NOWY R-NOWY_KOD - kod z podkreśleniem."), (1, 1), "W1: „Korzeń: NOWY R-NOWY_KOD"),
    "korzen-bez-zdania": (_replaced(ROOT, "Korzeń: R-BEZ-TESTU"), (1, 1), "W1: „Korzeń: R-BEZ-TESTU”"),
    "szczebel-spoza-drabiny": (_replaced(RUNG, "Szczebel: (f) - poza drabiną."), (1, 1), "W1: linia „Szczebel: (f)"),
    "dowod-6-linii": (_replaced(EVIDENCE, "Dowód: tools/mutacje.py", *(f"linia {number}" for number in range(2, 7))), (1, 1), "W1: Dowód ma 6 linii"),
    "dowod-6-linii-z-blokiem-kodu": (_replaced(EVIDENCE, "Dowód: wynik:", "```", *(f"linia {number}" for number in range(2, 7)), "```"), (1, 1), "W1: Dowód ma 6 linii"),
    "linia-dowodu-301-znakow": (
        _replaced(EVIDENCE, "Dowód: " + "x" * 301),
        (1, 1),
        "W1: linia Dowodu ma 301 znaków, najwyżej 300; dłuższy dowód zapisz w pliku obok werdyktu i podaj w Dowodzie jego ścieżkę",
    ),
    "cytat-pola-bez-bloku-kodu": (_replaced(EVIDENCE, "Dowód: grep:", "Gdzie: tools/x.py:3"), (1, 1), f"a po Dowodzie jest linia „Gdzie: tools/x.py:3” ({QUOTE})"),
    "cytowany-korzen-bez-bloku-nie-nadpisuje-prawdziwego": (
        _replaced(EVIDENCE, "Dowód: odmowa:", "Korzeń: R-DRUGA-DROGA - cytat"),
        (1, 1),
        f"W1: linia „{ROOT}” to nie „Szczebel: (a) - zdanie”",
    ),
    "lista-w-dowodzie": (_replaced(EVIDENCE, "Dowód: wyniki:", "", "- wynik", ""), (1, 1), "W1: w Dowodzie tylko linie tekstu i bloki kodu, a jest punkt listy „wynik”"),
    "wiecej-waznych-niz-w-linii-znalezisk": (TEMPLATE, (0, 1), "w treści Ważne 1"),
    "mniej-drobnych-niz-w-linii-znalezisk": (_text(*LINES[:5], *LINES[7:]), (1, 1), "w treści Ważne 1 i Drobne 0"),
    "wazne-po-drobnych": (_text(*LINES[5:7], *LINES[:5], *LINES[7:]), (1, 1), "W1: Ważne stoją przed Drobnymi"),
    "numer-nie-po-kolei": (_text(HEADING.replace("W1", "W2"), *LINES[1:]), (1, 1), "W2: to 1. Ważne"),
    "naglowek-czwartego-stopnia": (_text("#" + HEADING, *LINES[1:]), (1, 1), "blok <h4> „W1. Odmowa gubi przyczynę.”"),
    "drobne-z-drugim-polem": (_replaced(MINOR_WHERE, MINOR_WHERE, "Dowód: zdanie"), (1, 1), "D1: Drobne ma tylko pole Gdzie"),
    "proza-poza-szablonem": (_text("Recenzent pisze prozą.", "", *LINES), (1, 1), "linia „Recenzent pisze prozą.” to nie nagłówek"),
    "bez-sprawdzone": (_text(*LINES[:7]), (1, 1), "brak „## Sprawdzone”"),
    "sprawdzone-bez-punktow": (_text(*LINES[:8]), (1, 1), "„## Sprawdzone” ma 0 punktów"),
    "sprawdzone-6-punktow": (_text(*LINES, *(f"- punkt {number}" for number in range(2, 7))), (1, 1), "„## Sprawdzone” ma 6 punktów"),
    "sprawdzone-pusty-punkt": (_text(*LINES, "-"), (1, 1), "po „## Sprawdzone” pusty punkt listy"),
    "sprawdzone-lista-w-liscie": (_text(*LINES, "  - podpunkt"), (1, 1), "po „## Sprawdzone” tylko punkty „- …”, a jest blok <ul>"),
    "proza-po-sprawdzone": (_text(*LINES, "", "Wszystko dobrze."), (1, 1), "a jest linia „Wszystko dobrze.”"),
    "cytat-po-sprawdzone": (_text(*LINES, "", "> cytat"), (1, 1), "a jest blok <blockquote> „cytat”"),
    "proza-po-szczeblu": (_replaced(RUNG, RUNG, "Dalsza proza."), (1, 1), "W1: po Szczeblu tylko pole Idiom:, a jest linia „Dalsza proza.”"),
    "proza-po-idiomie": (_replaced(RUNG, RUNG, "Idiom: os.name", "Dalsza proza."), (1, 1), "W1: po Szczeblu tylko pole Idiom:, a jest linia „Dalsza proza.”"),
    "idiom-w-dowodzie": (_replaced(EVIDENCE, EVIDENCE, "Idiom: os.name"), (1, 1), f"a po Dowodzie jest linia „Idiom: os.name” ({QUOTE})"),
    "idiom-przed-szczeblem": (_replaced(RUNG, "Idiom: os.name", RUNG), (1, 1), "W1: linia „Idiom: os.name” to nie „Szczebel:"),
    "idiom-bez-reguly-z-klasa-spoza-listy": (_replaced(RUNG, RUNG, "Idiom: bez reguły inna-klasa jak #1553 W1 r2"), (1, 1), "W1: „Idiom: bez reguły inna-klasa jak #1553 W1 r2” to nie „Idiom: <id> jak #N W<n> r<k>”"),
    "idiom-bez-reguly-bez-wczesniejszego-waznego": (_replaced(RUNG, RUNG, "Idiom: bez reguły brak-testu"), (1, 1), "W1: „Idiom: bez reguły brak-testu” to nie"),
    "idiom-jak-bez-rundy": (_replaced(RUNG, RUNG, "Idiom: komentarz-w-src jak #1553 W1"), (1, 1), "W1: „Idiom: komentarz-w-src jak #1553 W1” to nie"),
    "puste-pole-idiom": (_replaced(RUNG, RUNG, "Idiom:"), (1, 1), "W1: „Idiom:” to nie"),
    "proza-zamiast-szczebla": (_replaced(RUNG, "Dalsza proza.", RUNG), (1, 1), "W1: linia „Dalsza proza.” to nie „Szczebel:"),
    "pass-z-waznym": (_text(*LINES[:5], *LINES[7:]), (0, 0), "w treści Ważne 1"),
}
_MAJOR = (
    "### W1. Brak testu.",
    "Gdzie: kod/inne.py:1",
    "Dowód: tools/mutacje.py: NIEWYKRYTA",
    "Korzeń: R-BEZ-TESTU - gałąź bez testu.",
    "Szczebel: (c) - test zachowania.",
)
ROOTS_E2E = (
    "Korzeń: NOWY R-NOWY-KOD - opis kodu spoza listy.",
    "Korzeń: R-NOWY-KOD - kod dodany do listy przez HEAD.",
    "Korzeń: NOWY R-NOWY-KOD - opis kodu, który HEAD już dodał.",
    "Korzeń: R-NOWY-KOD - kod spoza listy.",
    "Korzeń: R-BEZ-TESTU - kod z listy.",
    "Korzeń: NOWY R-BEZ-TESTU - kod z listy.",
)
WERDYKTY = {
    "sprawdzone": _text("## Sprawdzone", "- diff"),
    "drobne": _text("### D1. Nazwa.", "Gdzie: kod/inne.py:1", "## Sprawdzone", "- diff"),
    "wazne": _text(*_MAJOR, "## Sprawdzone", "- diff"),
    # Ważne z polem Idiom: dla warunku merge'a (ADR 0036): drugie wystąpienie, ucieczka, bez reguły i inna reguła.
    "wazne-idiom-drugie-wystapienie": _text(*_MAJOR, "Idiom: zakazane-wywolanie jak #1553 W1 r2", "## Sprawdzone", "- diff"),
    "wazne-idiom-ucieczka": _text(*_MAJOR, "Idiom: zakazane-wywolanie", "## Sprawdzone", "- diff"),
    "wazne-idiom-bez-reguly": _text(*_MAJOR, "Idiom: bez reguły brak-testu jak #1553 W1 r2", "## Sprawdzone", "- diff"),
    "wazne-idiom-innej-reguly": _text(*_MAJOR, "Idiom: inna-regula jak #1553 W2 r1", "## Sprawdzone", "- diff"),
    "proza": "Wszystko dobrze, bez uwag.",
    **{f"korzen-{index}": _text(*_MAJOR[:3], root, _MAJOR[4], "## Sprawdzone", "- diff") for index, root in enumerate(ROOTS_E2E)},
}


@functools.cache
def _saved() -> dict[str, str]:
    saved: dict[str, str] = json.loads(RENDERED.read_text(encoding="utf-8"))
    return saved


def rendered() -> dict[str, str]:
    """HTML z renderera GitHuba dla każdej treści z ``werdykty_szablonu.json``."""

    return dict(_saved())


def html(text: str) -> str:
    """HTML treści ``text`` z renderera GitHuba."""

    return _saved()[text]


def bodies() -> list[str]:
    """Treści, których HTML muszą mieć testy."""

    return [*PRZECHODZA.values(), *(text for text, _, _ in ODMOWY.values()), *WERDYKTY.values()]


def _refresh() -> None:
    saved = {}
    for text in dict.fromkeys(bodies()):
        request = json.dumps({"text": text, "mode": "gfm", "context": REPO})
        saved[text] = subprocess.run(
            ["gh", "api", "markdown", "--input", "-"], input=request, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60
        ).stdout
    RENDERED.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"WERDYKTY OK | {len(saved)} treści w {RENDERED.name}")


if __name__ == "__main__":
    _refresh()
