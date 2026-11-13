"""Opisy PR z „Naprawia” i ich HTML z renderera GitHuba dla testów ``tools/scal_pr.py``.

``PRZYPADKI`` to opisy z numerami issues, które ``naprawia.listed_issues`` ma wziąć z ich HTML po słowie „Naprawia”: repro z pięciu werdyktów
FAIL PR #624 (parser regex nie odtwarzał, co GitHub renderuje jako kod, znacznik spoza listy wierszowych kończył
linię, a akapit w nagłówku, ``<summary>`` albo tabeli zamykał) i przypadki brzegowe. ``PRAWDZIWE`` to scalone PR-y z bazą ``main``, których issues z „Naprawia” zostawały
otwarte przed #624, z numerami, które narzędzie ma zamknąć. ``SCALENIE`` to opisy testów przepływu
``tools/scal_pr.py``, z nagłówkami wzoru skilla ``pr`` (``wzor``). Numery to prawdziwe issues i PR-y tego repo, bo renderer odróżnia je po ich stanie na GitHubie
(``data-hovercard-type``).

``opisy_pr.json`` trzyma opisy ``PRAWDZIWE`` i HTML każdego opisu z ``gh api markdown`` (``mode=gfm``, ``context``
to ``REPO``), a atrapa ``gh`` w testach podaje go zamiast GitHuba, więc testy biegną bez sieci. Po zmianie opisów
w tym pliku albo renderera GitHuba odśwież plik (jedno wywołanie ``gh`` na opis, po kolei):

    .venv/bin/python tests/fixtures/opisy_pr.py
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
import subprocess

REPO = "maximiseartai/MAXIMISEART-Dad"
RENDERED = Path(__file__).with_name("opisy_pr.json")
ZGLOSZENIE = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia#12"
PRZYPADKI: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("linia-naprawia", "Naprawia #490.", (490,)),
    ("tylko-naprawia-od-wielkiej-litery", "naprawia #490\nNAPRAWIA #491\nNaprawia #492", (492,)),
    ("kilka-numerow-w-linii", "Naprawia #490, #491 i #492 oraz #493", (490, 491, 492, 493)),
    ("kilka-linii-bez-powtorzen", "## Why\n\nNaprawia #487\nNaprawia #493\nNaprawia #487", (487, 493)),
    ("linie-z-crlf", "Opis\r\nNaprawia #490\r\nNaprawia #491, #492\r\n", (490, 491, 492)),
    ("linia-po-br", "Opis<br>Naprawia #490", (490,)),
    ("twarda-spacja", "Naprawia\u00a0#490", (490,)),
    ("pogrubienie-i-kursywa", "**Naprawia #490**\n*Naprawia #491*", (490, 491)),
    ("pogrubienie-z-kursywa-w-punkcie-listy", "- ***Naprawia #490***", (490,)),
    ("naprawia-w-innym-znaczniku-wierszowym", "<ins>Naprawia #490</ins>\n\nOpis\n<span>Naprawia #491</span>", ()),
    ("punkty-list", "- Naprawia #490\n* Naprawia #491\n+ Naprawia #492\n1. Naprawia #493", (490, 491, 492, 493)),
    ("ciag-dalszy-punktu-listy", "- Naprawia #490\n  Naprawia #491\n   Naprawia #492", (490, 491, 492)),
    ("zagniezdzona-lista", "- Naprawia #490\n  - Naprawia #491\n  - Nie naprawia #492", (490, 491)),
    ("wciecie-po-znaczniku-listy", "-    Naprawia #490\n-     Naprawia #491\n-\tNaprawia #492", (490, 492)),
    ("ciag-dalszy-punktu-wciety-o-cztery-spacje", "   - Naprawia #490\n    - Naprawia #491", (490,)),
    ("wiersz-wciety-bez-pustej-linii", "Opis\n    Naprawia #490", (490,)),
    ("lista-wcieta-o-cztery-spacje-pod-punktem", "- a\n    - Naprawia #490", (490,)),
    ("akapit-wciety-w-punkcie-listy", "- punkt\n\n    Naprawia #490", (490,)),
    ("akapit-w-zagniezdzonej-liscie", "1. a\n   - b\n\n     Naprawia #490", (490,)),
    ("lista-bez-punktu", "<ul>Naprawia #490</ul>\n\nOpis", ()),
    ("adres-issue", f"Naprawia https://github.com/{REPO}/issues/490", (490,)),
    ("pelne-odwolanie-do-tego-repo", f"Naprawia {REPO}#490", (490,)),
    ("pelne-odwolanie-innymi-literami", "Naprawia MAXIMISEARTAI/maximiseart-dad#490", (490,)),
    ("numer-pr", "Naprawia #624, #490", (490,)),
    ("zgloszenie-z-innego-repo", f"Naprawia {ZGLOSZENIE}", ()),
    ("goly-numer-po-zgloszeniu", f"Naprawia {ZGLOSZENIE}, #13", ()),
    ("numer-przed-zgloszeniem", f"Naprawia #490, {ZGLOSZENIE}, #491", (490,)),
    ("numer-po-odwolaniu-bez-linku", "Naprawia inny/repo#8, #490", ()),
    ("numer-z-backslashem", "Naprawia \\#490, #491", (490, 491)),
    ("numer-bez-linku", "Naprawia #9999999, #491", (491,)),
    ("numer-bez-naprawia", "Wprowadzone w #480, przeniesione na nowy main (po #564).", ()),
    ("slowo-githuba", "Closes #490", ()),
    ("dwukropek-po-naprawia", "Naprawia: #490", ()),
    ("numer-w-nastepnej-linii", "Naprawia\n#490", ()),
    ("numer-w-drugim-zdaniu", "Naprawia #490. Błąd wszedł w #480.", (490,)),
    ("przeczenie-w-drugim-zdaniu", "Naprawia #490. Nie naprawia #491", (490,)),
    ("naprawia-w-drugim-zdaniu", "Naprawia #490. Naprawia #491", (490,)),
    ("tekst-w-liscie-numerow", "Naprawia #490 i dlatego #491 działa", (490,)),
    ("w-srodku-zdania", "Ta zmiana naprawia #490, bo plan liczy limit od runu.", ()),
    ("przeczenie-w-srodku-zdania", "Ten PR nie do końca naprawia #490", ()),
    ("naprawia-od-wielkiej-litery-w-srodku-zdania", "Ten PR nie Naprawia #490", ()),
    ("zawinieta-linia-z-przeczeniem", "Ten PR nie do końca\nnaprawia #490, tylko część.", ()),
    ("zawinieta-linia-z-nie", "Ta zmiana nie\nnaprawia #490", ()),
    ("zawinieta-linia-z-pytaniem", "Sprawdziłem, czy ta zmiana\nnaprawia #490, ale nie.", ()),
    ("naprawia-za-cytatem-q", "Ten PR <q>nie</q> Naprawia #490", ()),
    ("naprawia-za-tt", "Zmiana w <tt>scal_pr</tt> Naprawia #490", ()),
    ("naprawia-za-samp", "Wynik <samp>OK</samp> Naprawia #490", ()),
    ("naprawia-za-var", "Gdy <var>n</var> Naprawia #490", ()),
    ("naprawia-za-ruby", "<ruby>X<rt>y</rt></ruby> Naprawia #490", ()),
    ("naprawia-za-wzorem", "Gdy $n > 0$ Naprawia #490", ()),
    ("naprawia-za-emoji", "Ten PR :x: Naprawia #490", ()),
    ("naprawia-za-kbd", "Skrót <kbd>Ctrl</kbd> Naprawia #490", ()),
    ("naprawia-za-sup", "Przypis<sup>1</sup> Naprawia #490", ()),
    ("naprawia-za-pustym-znacznikiem", "Ten PR nie <q></q>Naprawia #490", ()),
    ("naprawia-za-span-i-mark", "Opis <span>x</span> Naprawia #490\nOpis <mark>x</mark> Naprawia #491", ()),
    ("przeczenie-z-dwiema-spacjami", "Nie  naprawia #490", ()),
    ("przeczenie-z-tabulatorem", "Nie\tnaprawia #490", ()),
    ("naglowek", "## Naprawia #490", ()),
    ("akapit-w-naglowku", "<h2>\n\nNaprawia #490\n\n</h2>", ()),
    ("akapit-w-naglowku-w-punkcie-listy", "- <h2>\n\n  Naprawia #490\n\n  </h2>", ()),
    ("lista-w-naglowku", "<h3><ul><li>Naprawia #490</li></ul></h3>", ()),
    ("naglowki-w-punktach-listy", "- # Naprawia #490\n- ## Naprawia #491\n- ### Naprawia #492\n- #### Naprawia #493\n- ##### Naprawia #487\n- ###### Naprawia #488", ()),
    ("tabela-w-punkcie-listy", "- <table><tr><td>Naprawia #490</td></tr></table>", ()),
    ("blok-html-w-punkcie-listy", "- <div>Naprawia #490</div>", ()),
    ("pre-w-punkcie-listy", "- <pre>Naprawia #490</pre>", ()),
    ("details-w-punkcie-listy", "- <details>Naprawia #490</details>", ()),
    ("summary-w-punkcie-listy", "- <summary>Naprawia #490</summary>", ()),
    ("linia-po-bloku-html-w-punkcie-listy", "- Opis\n  <div>x</div>\n  Naprawia #490", (490,)),
    ("linia-po-cytacie-w-punkcie-listy", "- <blockquote>x</blockquote>Naprawia #490", (490,)),
    ("linia-po-pre-w-punkcie-listy", "- <pre>x</pre>Naprawia #490", (490,)),
    ("linia-po-linii-poziomej-w-punkcie-listy", "- Opis\n  ***\n  Naprawia #490", (490,)),
    ("akapit-html-w-punkcie-listy", "- Opis\n  <p>Naprawia #490</p>", (490,)),
    ("tabela", "| Naprawia #490 |\n|---|\n| Naprawia #491 |", ()),
    ("akapit-w-komorce-tabeli", "| a |\n|---|\n| <p>Naprawia #490</p> |", ()),
    ("lista-w-komorce-tabeli", "| a |\n|---|\n| <ul><li>Naprawia #490</li></ul> |", ()),
    ("akapit-w-td", "<table><tr><td>\n\nNaprawia #490\n\n</td></tr></table>", ()),
    ("akapit-w-th", "<table><tr><th>\n\nNaprawia #490\n\n</th></tr></table>", ()),
    ("blok-html", "<div>Naprawia #490</div>", ()),
    ("akapit-w-bloku-html", "<div>\n\nNaprawia #490\n\n</div>", ()),
    ("details", "<details>\n<summary>Naprawia #490</summary>\n\nNaprawia #491\n</details>", ()),
    ("akapit-w-summary", "<details>\n<summary>\n\nNaprawia #490\n\n</summary>\n\nTreść\n</details>", ()),
    ("pogrubiony-akapit-w-summary", "<details><summary>\n\n**Naprawia #490**\n\n</summary>\nx\n</details>", ()),
    ("akapit-w-summary-bez-details", "<summary>\n\nNaprawia #490\n\n</summary>", ()),
    ("lista-w-summary", "<details><summary><ul><li>Naprawia #490</li></ul></summary>x</details>", ()),
    ("linia-po-details", "<details><summary>x</summary>y</details>\n\nNaprawia #490", (490,)),
    ("akapit-w-section", "<section>\n\nNaprawia #490\n\n</section>", ()),
    ("przypis", "Opis[^1]\n\n[^1]: Naprawia #490", ()),
    ("akapit-w-dd", "<dl><dd>\n\nNaprawia #490\n\n</dd></dl>", ()),
    ("dd-w-punkcie-listy", "- <dl><dd>Naprawia #490</dd></dl>po wdrożeniu", ()),
    ("lista-w-cytacie", "> - Naprawia #490", ()),
    ("punkty-listy-zadan", "- [x] Naprawia #490\n- [ ] Naprawia #491\n- Naprawia #492", (492,)),
    ("link-przed-naprawia", "[Naprawia](https://example.com) #490", ()),
    ("obrazek-przed-naprawia", "![x](https://example.com/a.png) Naprawia #490\n\nNaprawia #491", (491,)),
    ("cytat", "> Naprawia #490", ()),
    ("alert", "> [!NOTE]\n> Naprawia #490\n\nNaprawia #491", (491,)),
    ("alert-w-punkcie-listy-to-cytat", "- > [!WARNING]\n  > Naprawia #490", ()),
    ("przekreslenie", "~~Naprawia #490~~", ()),
    ("przekreslony-numer", "Naprawia ~~#490~~, #491", ()),
    ("przekreslony-numer-w-s", "Naprawia <s>#490</s>, #491", ()),
    ("przekreslony-numer-w-strike", "Naprawia <strike>#490</strike>, #491", ()),
    ("przekreslenie-przez-koniec-wiersza", "~~Ten PR\nnie~~ Naprawia #490", ()),
    ("kod-przez-br", "Ten PR <code>nie<br>x</code> Naprawia #490", ()),
    ("kod-przez-br-ze-spacja", "Ten PR <code>nie<br> </code>Naprawia #490", ()),
    ("komentarz-html", "Opis\n<!-- Naprawia #490 -->", ()),
    ("komentarz-html-w-kilku-liniach", "<!--\nNaprawia #490\n-->\nNaprawia #491", (491,)),
    ("niedomkniety-komentarz-html", "Opis\n\n<!-- niedomknięty\nNaprawia #490", ()),
    ("fragment-kodu", "`Naprawia #490`", ()),
    ("fragment-kodu-html", "Naprawia <code>#490</code>, #491", ()),
    ("fragment-kodu-z-dwoma-backtickami", "``Naprawia #490``", ()),
    ("fragment-kodu-z-dwoma-backtickami-w-dwoch-liniach", "``kod\nNaprawia #490``", ()),
    ("backtick-w-fragmencie-kodu", "``Naprawia ` #490``\nNaprawia #491", (491,)),
    ("naprawia-za-fragmentem-kodu", "`kod` Naprawia #490", ()),
    ("fragment-kodu-w-dwoch-liniach", "`kod\nNaprawia #490`", ()),
    ("dluzszy-ciag-backtickow-nie-zamyka-fragmentu-kodu", "`x``\nNaprawia #490\n`", ()),
    ("fragment-kodu-po-niedomknietych-backtickach", "``x`\nNaprawia #490\n`", ()),
    ("fragment-kodu-nie-przechodzi-przez-pusta-linie", "Zmienia 5` znaków.\n \nNaprawia #490\nI `kod`", (490,)),
    ("backslash-przed-backtickami", "\\``\nNaprawia #490\n`\n", ()),
    ("blok-kodu", "```\nNaprawia #490\n```\nNaprawia #491", (491,)),
    ("wciety-plot-bloku-kodu", "   ```\nkod\n\nNaprawia #490\n   ```\nNaprawia #491", (491,)),
    ("blok-kodu-z-tyldami", "~~~text\nNaprawia #490\n~~~", ()),
    ("plot-z-tekstem-nie-zamyka-bloku-kodu", "```\n```python\nNaprawia #490\n```\n~~~\n~~~text\nNaprawia #491\n~~~\nNaprawia #492", (492,)),
    ("krotszy-plot-nie-zamyka-bloku-kodu", "````\nkod\n```\nNaprawia #490\n````\nNaprawia #491", (491,)),
    ("plot-z-innym-znakiem-nie-zamyka-bloku-kodu", "~~~\n```\nNaprawia #490\n~~~\nNaprawia #491", (491,)),
    ("plot-z-dopisanym-innym-znakiem-nie-zamyka-bloku-kodu", "```\nkod\n```~\nNaprawia #490\n```\nNaprawia #491", (491,)),
    ("dluzszy-plot-ze-spacjami-zamyka-blok-kodu", "```\nkod\n````  \nNaprawia #490\n~~~\nkod\n~~~~\nNaprawia #491", (490, 491)),
    ("plot-z-crlf-zamyka-blok-kodu", "```\r\nkod\r\n```\r\nNaprawia #490\r\n", (490,)),
    ("niedomkniety-blok-kodu", "```\nNaprawia #490 w niedomkniętym bloku", ()),
    ("info-z-backtickiem-to-nie-plot", "```a`b\n```\nNaprawia #490\n```\n", ()),
    ("tyldy-wciete-o-cztery-spacje-to-nie-plot", "Opis:\n\n    ~~~\n\n~~~\nNaprawia #490\n~~~\nNaprawia #491", (491,)),
    ("wciety-blok-kodu", "Przykład opisu:\n\n    Naprawia #490\n", ()),
    ("blok-kodu-wciety-tabulatorem", "Przykład:\n\n\tNaprawia #490\n", ()),
    ("plot-z-tyldami-w-punkcie-listy", "- ~~~\n  Naprawia #490\n  ~~~\n", ()),
    ("plot-z-tyldami-w-punkcie-listy-numerowanej", "1. ~~~\n   Naprawia #490\n   ~~~\n", ()),
    ("plot-w-punkcie-listy-z-pusta-linia", "- ```\n  kod\n\n  Naprawia #490\n  ```\n", ()),
    ("plot-z-jezykiem-w-punkcie-listy-numerowanej", "1. ```python\n   kod\n\n   Naprawia #490\n   ```\n", ()),
    ("blok-kodu-po-koncu-listy", "- a\n\n  ```\n  kod\n\nkoniec listy\n\n```\nNaprawia #490\n```\n", ()),
    ("blok-pre", "<pre>\nNaprawia #490\n</pre>\n", ()),
)
PRAWDZIWE = {
    394: (390,),
    397: (396,),
    461: (459,),
    497: (487, 493),
    498: (488,),
    530: (489,),
    531: (492,),
    534: (490, 491),
    535: (533,),
}


def wzor(why: str) -> str:
    """Opis z nagłówkami wzoru skilla ``pr``, bez których ``tools/scal_pr.py`` nie scala, z ``why`` w ``## Why``."""

    return f"## Why\n\n{why}\n\n## Summary\n\nSzkic.\n\n## Evidence\n\n- **Before:** FAIL\n  **After:** OK\n\n## Merge Danger\n\n**Door:** two-way\n"


SCALENIE = {
    "zamyka": wzor("Naprawia #3, #4\nNaprawia #5\nNaprawia #1\nCloses #7\nNaprawia #7\nNaprawia inny/repo#8, #6"),
    "jedno": wzor("Naprawia #3"),
    "dwa": wzor("Naprawia #3, #4"),
    "porazki": wzor("Naprawia #14, #3, #10, #11, #12, #13"),
    "bez-commitu-merge": wzor("Naprawia #3, #5, #15"),
}


@functools.cache
def _saved() -> dict[str, dict[str, str]]:
    saved: dict[str, dict[str, str]] = json.loads(RENDERED.read_text(encoding="utf-8"))
    return saved


def real_body(number: int) -> str:
    """Opis scalonego PR ``number`` z ``PRAWDZIWE`` z dnia odświeżenia."""

    return _saved()["prawdziwe"][str(number)]


def rendered() -> dict[str, str]:
    """HTML z renderera GitHuba dla każdego opisu z ``opisy_pr.json``."""

    return dict(_saved()["html"])


def bodies() -> list[str]:
    """Opisy, których HTML muszą mieć testy."""

    return [*(body for _, body, _ in PRZYPADKI), *SCALENIE.values(), *map(real_body, PRAWDZIWE)]


def _gh(*arguments: str, stdin: str | None = None) -> str:
    return subprocess.run(["gh", *arguments], input=stdin, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60).stdout


def _refresh() -> None:
    real = {}
    for number in PRAWDZIWE:
        real[str(number)] = json.loads(_gh("pr", "view", str(number), "--repo", REPO, "--json", "body"))["body"]
    texts = [*(body for _, body, _ in PRZYPADKI), *SCALENIE.values(), *real.values()]
    html = {}
    for text in dict.fromkeys(texts):
        html[text] = _gh("api", "markdown", "--input", "-", stdin=json.dumps({"text": text, "mode": "gfm", "context": REPO}))
    RENDERED.write_text(json.dumps({"prawdziwe": real, "html": html}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OPISY PR OK | {len(html)} opisów w {RENDERED.name}")


if __name__ == "__main__":
    _refresh()
