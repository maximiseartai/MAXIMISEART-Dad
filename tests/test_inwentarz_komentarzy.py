from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Final

import pytest

from tests.fixtures.git_repo import commit, copy_files, git, with_imports

import inwentarz_komentarzy
import odpalenia_ast_grep
import rozjazd_modelu

windows_bez_ast_grep = pytest.mark.skipif(
    sys.platform == "win32" and inwentarz_komentarzy.AST_GREP is None,
    reason="ast-grep z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt; formy spoza Pythona sprawdza Linux",
)
KSZTALT: Final = inwentarz_komentarzy.KSZTALT_DYREKTYWY
SHA: Final = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def _inwentarz(root: Path, pliki: dict[str, str], *argumenty: str) -> int:
    git(root, "init", "--quiet")
    for nazwa, tresc in pliki.items():
        (root / nazwa).parent.mkdir(parents=True, exist_ok=True)
        (root / nazwa).write_text(tresc, encoding="utf-8", newline="")
    git(root, "add", "--all")
    return inwentarz_komentarzy.main(["--root", str(root), *argumenty])


def _wpisy(root: Path, capsys: pytest.CaptureFixture[str], pliki: dict[str, str]) -> tuple[int, list[str]]:
    kod = _inwentarz(root, pliki)
    *wpisy, podsumowanie = capsys.readouterr().out.splitlines()
    assert podsumowanie.startswith(f"INWENTARZ OK | plików {len(pliki)} | wpisów {len(wpisy)} "), podsumowanie
    return kod, wpisy


@pytest.mark.parametrize(
    ("pliki", "oczekiwane"),
    [
        pytest.param(
            {"tools/a.py": "def f():\n    # krok przed zwrotem\n    return 1\n"}, ["tools/a.py:2 | komentarz | f | - | # krok przed zwrotem"], id="komentarz-w-funkcji"
        ),
        pytest.param({"tools/a.py": "LIMIT_S = 5  # sekundy\n"}, ["tools/a.py:1 | komentarz | moduł | - | # sekundy"], id="komentarz-na-koncu-linii"),
        pytest.param(
            {"tools/a.py": "# pierwsza\n# druga\ndef f():\n    return 1\n"},
            ["tools/a.py:1-2 | komentarz | f | - | # pierwsza"],
            id="kolejne-linie-komentarza-to-jeden-wpis-definicji-pod-nimi",
        ),
        pytest.param(
            {"tools/a.py": '"""Moduł."""\n\n\nclass K:\n    async def m(self):\n        """Opis."""\n        return 1\n'},
            ["tools/a.py:1 | docstring | moduł | - | Moduł.", "tools/a.py:6 | docstring | K.m | - | Opis."],
            id="docstring-modulu-i-metody-async",
        ),
        pytest.param({"tools/a.py": 'def f():\n    """Opis."""\n'}, ["tools/a.py:2 | docstring-jedyna-instrukcja | f | - | Opis."], id="docstring-jedyna-instrukcja-ciala"),
        pytest.param({"tools/a.py": 'LIMIT: int = 5\n"""Opis limitu."""\n'}, ["tools/a.py:2 | napis | LIMIT | - | Opis limitu."], id="napis-pod-przypisaniem"),
        pytest.param(
            {"src/a.py": "def trasa():\n    if True:\n        X = 1\n        'napis w gałęzi'\n"},
            ["src/a.py:4 | napis | trasa.X | - | napis w gałęzi"],
            id="napis-w-instrukcji-zlozonej-definicji",
        ),
        pytest.param(
            {"tools/hooks/hak": "#!/usr/bin/env python3\n# opis haka\nX = 1\n"},
            ["tools/hooks/hak:1 | komentarz | moduł | shebang | #!/usr/bin/env python3", "tools/hooks/hak:2 | komentarz | moduł | - | # opis haka"],
            id="python-bez-rozszerzenia-z-shebangiem",
        ),
        pytest.param(
            {"tools/a.py": "# -*- coding: utf-8 -*-\nX = 1\n"}, ["tools/a.py:1 | komentarz | moduł | kodowanie | # -*- coding: utf-8 -*-"], id="linia-kodowania"
        ),
        pytest.param(
            {"tools/a.py": "X = 1\nY = 2\n# -*- coding: utf-8 -*-\n"},
            ["tools/a.py:3 | komentarz | moduł | - | # -*- coding: utf-8 -*-"],
            id="granica-kodowanie-dopiero-w-trzeciej-linii-to-komentarz",
        ),
        pytest.param({"ruff.toml": 'line-length = 120\nnazwa = "a # b"  # opis\n'}, ["ruff.toml:2 | toml | plik | - | # opis"], id="komentarz-toml-za-napisem-z-krzyzykiem"),
        pytest.param({".importlinter": "[importlinter]\n# opis\nroot_package = x\n"}, [".importlinter:2 | ini | plik | - | # opis"], id="komentarz-ini"),
        pytest.param({"requirements.txt": "pytest>=8  # opis\n"}, ["requirements.txt:1 | requirements | plik | - | # opis"], id="komentarz-requirements"),
        pytest.param({".gitignore": "# opis\n.venv/\n"}, [".gitignore:1 | gitignore | plik | - | # opis"], id="komentarz-gitignore"),
        pytest.param({"tools/a.py": 'X = "# nie komentarz"\n'}, [], id="krzyzyk-w-napisie-pythona"),
        pytest.param({"ruff.toml": 'nazwa = "a # b"\n'}, [], id="krzyzyk-w-napisie-toml"),
        pytest.param(
            {"frontend/src/a.tsx": "// nad karta\nexport function Karta() {\n  return <div>{/* w jsx */}</div>;\n}\n"},
            ["frontend/src/a.tsx:1 | ts | Karta | - | // nad karta", "frontend/src/a.tsx:3 | ts | Karta | - | /* w jsx */"],
            id="komentarz-ts-i-jsx", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {".github/workflows/a.yml": "on:\n  # opis wyzwalacza\n  push:\n    branches: [main]\n"},
            [".github/workflows/a.yml:2 | yaml | on.push | - | # opis wyzwalacza"],
            id="komentarz-yaml", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {"tools/a.sh": "#!/bin/sh\n# opis\necho 1\n"},
            ["tools/a.sh:1 | powłoka | plik | shebang | #!/bin/sh", "tools/a.sh:2 | powłoka | plik | - | # opis"],
            id="komentarz-powloki-z-shebangiem", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {"frontend/index.html": "<!-- Strona Centrum dla taty -->\n<p></p>\n"},
            ["frontend/index.html:1 | html | plik | - | <!-- Strona Centrum dla taty -->"],
            id="komentarz-html-ktory-przepisuje-budowa-frontendu", marks=windows_bez_ast_grep,
        ),
        pytest.param({"frontend/src/a.css": "/* opis */\na { color: red; }\n"}, ["frontend/src/a.css:1 | css | plik | - | /* opis */"], id="komentarz-css", marks=windows_bez_ast_grep),
        pytest.param({".github/a.yml": "nazwa: 'a # b'\n"}, [], id="krzyzyk-w-napisie-yaml", marks=windows_bez_ast_grep),
        pytest.param(
            {".github/workflows/a.yml": "jobs:\n  a:\n    steps:\n      - run: |\n          # w skrypcie\n          echo 1\n"},
            [],
            id="krzyzyk-w-skrypcie-run-workflowu", marks=windows_bez_ast_grep,
        ),
    ],
)
def test_inwentarz_wypisuje_kazdy_komentarz_i_napis_z_plikiem_linia_forma_i_wezlem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], pliki: dict[str, str], oczekiwane: list[str]
) -> None:
    assert _wpisy(tmp_path, capsys, pliki) == (0, oczekiwane)


@pytest.mark.parametrize(
    ("pliki", "oczekiwane"),
    [
        pytest.param(
            {"frontend/src/a.ts": "const v: unknown = 1;\n// SAFETY: v ustawione wyżej\nexport const a = v as number;\n"},
            [f"frontend/src/a.ts:2 | ts | a | {KSZTALT} | // SAFETY: v ustawione wyżej"],
            id="safety-nad-rzutowaniem-czytane-przez-oxlint", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # mutacje-zmiany: tylko log | do 2026-12-31 | zgoda Maks\n"},
            [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # mutacje-zmiany: tylko log | do 2026-12-31 | zgoda Maks"],
            id="wyjatek-mutacji-zmian",
        ),
        pytest.param(
            {"tools/a.py": "import os  # NOQA: F401\n", "tools/b.py": "# flake8: noqa\nimport os\n", "tools/t.py": "x = []  # type: list[int]\n"},
            [
                f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # NOQA: F401",
                f"tools/b.py:1 | komentarz | moduł | {KSZTALT} | # flake8: noqa",
                f"tools/t.py:1 | komentarz | moduł | {KSZTALT} | # type: list[int]",
            ],
            id="dyrektywy-ruff-wielkimi-literami-i-komentarz-typu-mypy",
        ),
        pytest.param({"tools/a.py": "import os  # noqa: F401 - powód\n"}, [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # noqa: F401 - powód"], id="dyrektywa-ruff"),
        pytest.param(
            {"tools/a.py": "x = f()  # type: ignore[name-defined]\n"}, [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # type: ignore[name-defined]"], id="dyrektywa-mypy"
        ),
        pytest.param(
            {"tools/a.py": "def f(a,  # type: int\n      b):\n    # type: (...) -> None\n    pass\n"},
            [f"tools/a.py:1 | komentarz | f | {KSZTALT} | # type: int", f"tools/a.py:3 | komentarz | f | {KSZTALT} | # type: (...) -> None"],
            id="komentarz-typu-argumentu-i-funkcji",
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # pylint: disable=invalid-name\n"}, [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # pylint: disable=invalid-name"], id="dyrektywa-narzedzia-spoza-repo"
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # ZEWNĘTRZNE: Excel blokuje otwarty plik (https://learn.microsoft.com/office)\n"},
            [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # ZEWNĘTRZNE: Excel blokuje otwarty plik (https://learn.microsoft.com/office)"],
            id="ograniczenie-zewnetrzne-z-listy-wyjatkow",
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # Uwaga: proza w kształcie dyrektywy\n"},
            [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # Uwaga: proza w kształcie dyrektywy"],
            id="granica-proza-ze-slowem-i-dwukropkiem-ma-znacznik",
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # opis, potem NoQa bez krzyżyka\n"}, [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # opis, potem NoQa bez krzyżyka"], id="slowo-noqa-w-dowolnej-wielkosci-liter"
        ),
        pytest.param(
            {"tools/a.py": f"X = 1  # {odpalenia_ast_grep.SUPPRESSION}: regula\n"},
            [f"tools/a.py:1 | komentarz | moduł | {KSZTALT} | # {odpalenia_ast_grep.SUPPRESSION}: regula"],
            id="tlumienie-ast-grep",
        ),
        pytest.param(
            {"tools/a.py": "# opis nad\n# noqa: E501 - powód\n# opis pod\nX = 1\n"},
            ["tools/a.py:1 | komentarz | moduł | - | # opis nad", f"tools/a.py:2 | komentarz | moduł | {KSZTALT} | # noqa: E501 - powód", "tools/a.py:3 | komentarz | moduł | - | # opis pod"],
            id="komentarz-ze-znacznikiem-nie-laczy-sie-z-sasiadami",
        ),
        pytest.param(
            {"frontend/src/a.ts": "/**\n * Opis.\n * @deprecated użyj b\n */\nexport const a = 1;\n"},
            [f"frontend/src/a.ts:1-4 | ts | a | {KSZTALT} | /**"],
            id="malpa-w-linii-bloku", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {"frontend/src/a.ts": "// @ts-expect-error powód\nconst x: number = 'a';\n"},
            [f"frontend/src/a.ts:1 | ts | x | {KSZTALT} | // @ts-expect-error powód"],
            id="dyrektywa-tsc", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {".github/workflows/a.yml": "on:\n  pull_request_target: # zizmor: ignore[dangerous-triggers] powód\n    types: [opened]\n"},
            [f".github/workflows/a.yml:2 | yaml | on.pull_request_target | {KSZTALT} | # zizmor: ignore[dangerous-triggers] powód"],
            id="dyrektywa-zizmor", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {".github/workflows/a.yml": f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{SHA} # v7.0.1\n"},
            [".github/workflows/a.yml:4 | yaml | jobs.a.steps[0] | - | # v7.0.1"],
            id="granica-wersja-przypietej-akcji-bez-znacznika", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # zdanie z dwukropkiem: dalej proza\n"},
            ["tools/a.py:1 | komentarz | moduł | - | # zdanie z dwukropkiem: dalej proza"],
            id="granica-dwukropek-po-drugim-slowie-to-proza",
        ),
        pytest.param(
            {"tools/a.py": "X = 1  # mutacje-zmiany powód bez dwukropka\n"},
            ["tools/a.py:1 | komentarz | moduł | - | # mutacje-zmiany powód bez dwukropka"],
            id="granica-wyjatek-mutacji-bez-dwukropka",
        ),
        pytest.param(
            {"tools/a.sh": "echo $A  # shellcheck disable=SC2086\n"},
            ["tools/a.sh:1 | powłoka | plik | - | # shellcheck disable=SC2086"],
            id="granica-dyrektywa-shellcheck-bez-dwukropka", marks=windows_bez_ast_grep,
        ),
        pytest.param(
            {"frontend/src/a.ts": "/// <reference types=\"vite/client\" />\nconsole.log(0);\n// eslint-disable-next-line no-console\nconsole.log(1);\n// oxlint-disable-next-line no-console -- powód\nconsole.log(2);\n"},
            [
                "frontend/src/a.ts:1 | ts | plik | - | /// <reference types=\"vite/client\" />",
                "frontend/src/a.ts:3 | ts | plik | - | // eslint-disable-next-line no-console",
                "frontend/src/a.ts:5 | ts | plik | - | // oxlint-disable-next-line no-console -- powód",
            ],
            id="granica-dyrektywy-tsc-eslint-i-oxlint-bez-dwukropka", marks=windows_bez_ast_grep,
        ),
    ],
)
def test_znacznik_mowi_o_ksztalcie_dyrektywy_shebangu_albo_kodowania_a_nie_o_czytelniku(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], pliki: dict[str, str], oczekiwane: list[str]
) -> None:
    assert _wpisy(tmp_path, capsys, pliki) == (0, oczekiwane)


def test_ostatnia_linia_liczy_wpisy_znaczniki_i_pliki_nieczytane_z_przyczyna(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pliki = {
        "AGENTS.md": "<!-- spis narzędzi -->\n",
        "docs/b.md": "tekst\n",
        ".gitattributes": "gen/** merge=wygenerowane\n",
        "gen/a.py": "# opis\n",
        "frontend/.oxlintrc.json": json.dumps({"ignorePatterns": ["src/components/ui/**"]}),
        "frontend/src/components/ui/a.ts": "// opis\n",
        "tools/a.py": "# opis\nX = 1  # noqa: F841 - powód\n",
    }

    kod = _inwentarz(tmp_path, pliki)

    assert (kod, capsys.readouterr().out.splitlines()) == (
        0,
        [
            "tools/a.py:1 | komentarz | moduł | - | # opis",
            f"tools/a.py:2 | komentarz | moduł | {KSZTALT} | # noqa: F841 - powód",
            "INWENTARZ OK | plików 2 | wpisów 2 (linii 2) | ze znacznikiem 1 | nieczytane 5: bez parsera .md 2, bez parsera .json 1,"
            " ignorePatterns frontend/.oxlintrc.json 1, merge=wygenerowane 1",
        ],
    )


def test_wpis_jako_json_ma_pelny_tekst_i_znacznik(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    kod = _inwentarz(tmp_path, {"tools/a.py": 'def f():\n    """Pierwsza.\n\n    Druga."""\n'}, "--json")

    wpis, _ = capsys.readouterr().out.splitlines()
    assert (kod, json.loads(wpis)) == (
        0,
        {"plik": "tools/a.py", "linia": 2, "koniec": 4, "forma": "docstring-jedyna-instrukcja", "wezel": "f", "znacznik": None, "tekst": "Pierwsza.\n\n    Druga."},
    )


def test_plik_ktorego_parser_nie_czyta_konczy_inwentarz_porazka_z_nazwa_pliku(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    kod = _inwentarz(tmp_path, {"tools/a.py": "def (\n", "tools/b.py": "# opis\n"})

    assert (kod, capsys.readouterr().out.splitlines()[-1].startswith("INWENTARZ FAIL | tools/a.py: Python się nie parsuje")) == (1, True)


def test_bez_ast_grep_plik_pythona_ma_wpisy_a_plik_dla_ast_grep_konczy_inwentarz_porazka_z_przyczyna(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inwentarz_komentarzy, "AST_GREP", None)

    kod_pythona = _inwentarz(tmp_path, {"tools/a.py": "# opis\n", ".github/a.yml": "# opis\nx: 1\n"}, "tools")
    *wpisy, _ = capsys.readouterr().out.splitlines()
    kod_calosci = inwentarz_komentarzy.main(["--root", str(tmp_path)])

    assert (kod_pythona, wpisy, kod_calosci, capsys.readouterr().out.splitlines()) == (
        0,
        ["tools/a.py:1 | komentarz | moduł | - | # opis"],
        1,
        [f"INWENTARZ FAIL | .github/a.yml: {odpalenia_ast_grep.INSTALL}"],
    )


NARZEDZIE: Final = "tools/inwentarz_komentarzy.py"
SKILL: Final = ".agents/skills/verify-a"
MODEL: Final = f"{SKILL}/{rozjazd_modelu.DEFINICJE}"
SKRYPT_MUTACJI: Final = (
    "from pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools/lib'))\n\n"
    "from silnik_mutacji import Edit, Mutation\n\n"
    f"MUTATIONS = (Mutation('m', (Edit(Path('skrypty/mutowany.py'), 'M = 1', 'M = 2'),), ('{SKILL}/scripts/sprawdz_a.py',)),)\n"
    "if __name__ == '__main__':\n    print('MUTACJE OK')\n"
)
TEST_NAGLOWKOW: Final = (
    "import os\nfrom pathlib import Path\n\n\ndef test_kazdy_skrypt_ma_naglowek():\n"
    "    for katalog, _, nazwy in os.walk(Path(__file__).parents[1] / 'skrypty'):\n"
    "        for nazwa in nazwy:\n"
    "            assert (Path(katalog) / nazwa).read_text(encoding='utf-8').startswith('# nagłówek'), nazwa\n"
)
TEST_Z_WYBORU_PR: Final = (
    "from pathlib import Path\n\n\ndef test_opis_ma_drugi_komentarz():\n"
    "    assert '# drugi' in (Path(__file__).parents[1] / 'skrypty/opis.py').read_text(encoding='utf-8')\n"
)
BAZA_FALI: Final = {
    ".gitignore": "__pycache__/\n.pytest_cache/\n",
    "skrypty/opis.py": "# nagłówek opisu\n# drugi\nX = 1\n",
    "skrypty/mutowany.py": "# nagłówek mutowanego\nM = 1\n",
    "skrypty/model.py": '# nagłówek modelu\nclass Klasa:\n    X = 1\n    """Opis X."""\n',
    "frontend/src/karta.ts": "// opis karty\nexport const karta = 1;\n",
    "tests/test_naglowki.py": TEST_NAGLOWKOW,
    f"{SKILL}/SKILL.md": f"---\nname: verify-a\npilnuje:\n  - frontend/src/karta.ts\n  - skrypty/model.py\nci: {SKILL}/scripts/sprawdz_a.py\n---\n",
    f"{SKILL}/scripts/sprawdz_a.py": "print('sprawdzone')\n",
    f"{SKILL}/scripts/check_a_mutations.py": SKRYPT_MUTACJI,
    MODEL: json.dumps({"frontend/src/karta.ts": {rozjazd_modelu.CALY_PLIK: "-"}, "skrypty/model.py": {"Klasa": "-"}}),
}
JEDNOSTKA: Final = re.compile(r"^(?:MAIN|NOC) \| |^DOWÓD FALI ")
PRZECHODZI: Final = "MAIN | pytest | 1 plików poza wyborem pull requestu | OK"
KROKI_CI: Final = ["MAIN | krok CI | e2e | po merge'u", "MAIN | krok CI | timing | po merge'u"]
BEZ_ROZJAZDU: Final = "MAIN | podstawa | verify-a | po merge'u, rozjazd modelu: brak"
ROZJAZD_KARTY: Final = f"MAIN | podstawa | verify-a | {rozjazd_modelu.ROZJAZD}: kod opisany modelem zmienił się: frontend/src/karta.ts."
OK_FALI: Final = "lokalnie: pytest 1 plików, rozjazd modelu 1 skilli | po merge'u: kroki CI 2, podstawy 1"


def _fala(root: Path, baza: dict[str, str], zmiana: dict[str, str], *, stary_skrot: bool) -> tuple[subprocess.CompletedProcess[str], str]:
    copy_files(root, with_imports((NARZEDZIE, "tools/lib/silnik_mutacji.py")))
    for nazwa, tresc in baza.items():
        (root / nazwa).parent.mkdir(parents=True, exist_ok=True)
        (root / nazwa).write_text(tresc, encoding="utf-8", newline="")
    rozjazd_modelu.przesun(root / SKILL, root)
    if stary_skrot:
        skroty = json.loads((root / MODEL).read_text(encoding="utf-8"))
        skroty["frontend/src/karta.ts"][rozjazd_modelu.CALY_PLIK] = "0" * rozjazd_modelu.DLUGOSC
        (root / MODEL).write_text(json.dumps(skroty), encoding="utf-8")
    git(root, "init", "--quiet")
    poczatek = commit(root, "baza")
    for nazwa, tresc in zmiana.items():
        (root / nazwa).write_text(tresc, encoding="utf-8", newline="")
    commit(root, "fala")
    wynik = subprocess.run(
        [sys.executable, str(root / NARZEDZIE), "--dowod-fali", poczatek],
        cwd=root,
        env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return wynik, poczatek


def _jednostki(wynik: subprocess.CompletedProcess[str], poczatek: str) -> list[str]:
    jednostki = [re.sub(r" (?:kod \d+ )?\(\d+ s\)$", "", linia) for linia in wynik.stdout.splitlines() if JEDNOSTKA.match(linia)]
    return [linia.replace(f" | baza {poczatek[:10]} | zmiana 1 plików", "") for linia in jednostki]


@pytest.mark.parametrize(
    ("baza", "stary_skrot", "zmiana", "oczekiwane", "kod"),
    [
        pytest.param(
            {}, False, {"frontend/src/karta.ts": "export const karta = 1;\n"},
            [PRZECHODZI, *KROKI_CI, ROZJAZD_KARTY, "DOWÓD FALI FAIL | podstawa verify-a"], 1,
            id="usuniety-komentarz-pliku-ts-w-modelu-skilla-rozjezdza-podstawe-na-main",
        ),
        pytest.param(
            {}, False, {"skrypty/model.py": "# nagłówek modelu\nclass Klasa:\n    X = 1\n"},
            [PRZECHODZI, *KROKI_CI, f"MAIN | podstawa | verify-a | {rozjazd_modelu.ROZJAZD}: kod opisany modelem zmienił się: skrypty/model.py Klasa.", "DOWÓD FALI FAIL | podstawa verify-a"], 1,
            id="usuniety-napis-w-definicji-z-modelu-skilla-rozjezdza-podstawe-na-main",
        ),
        pytest.param(
            {}, False, {"skrypty/opis.py": "# drugi\nX = 1\n"},
            ["MAIN | pytest | 1 plików poza wyborem pull requestu | FAIL", *KROKI_CI, BEZ_ROZJAZDU, "DOWÓD FALI FAIL | pytest 1 plików poza wyborem pull requestu"], 1,
            id="test-spoza-wyboru-pull-requestu-czyta-usuniety-komentarz",
        ),
        pytest.param(
            {}, False, {"skrypty/opis.py": "# nagłówek opisu\nX = 1\n"},
            [PRZECHODZI, *KROKI_CI, BEZ_ROZJAZDU, f"DOWÓD FALI OK | {OK_FALI}, noc 0"], 0,
            id="komentarz-bez-czytelnika-w-zakresie-runu",
        ),
        pytest.param(
            {"tests/test_opis.py": TEST_Z_WYBORU_PR}, False, {"skrypty/opis.py": "# nagłówek opisu\nX = 1\n"},
            [PRZECHODZI, *KROKI_CI, BEZ_ROZJAZDU, f"DOWÓD FALI OK | {OK_FALI}, noc 0"], 0,
            id="test-z-wyboru-pull-requestu-liczy-required-ci-a-nie-dowod",
        ),
        pytest.param(
            {}, True, {"skrypty/opis.py": "# nagłówek opisu\nX = 1\n"},
            [
                PRZECHODZI, *KROKI_CI,
                "MAIN | podstawa | verify-a | po merge'u, rozjazd modelu już na bazie, bo zmiana nie dotyka plików modelu: kod opisany modelem zmienił się: frontend/src/karta.ts.",
                f"DOWÓD FALI OK | {OK_FALI}, noc 0",
            ], 0,
            id="rozjazd-modelu-z-bazy-nie-jest-porazka-fali",
        ),
        pytest.param(
            {}, False, {"skrypty/mutowany.py": "# nagłówek mutowanego\n\nM = 1\n"},
            [PRZECHODZI, *KROKI_CI, BEZ_ROZJAZDU, "NOC | skrypt mutacji | verify-a/check_a_mutations.py | po merge'u", f"DOWÓD FALI OK | {OK_FALI}, noc 1"], 0,
            id="skrypt-mutacji-nocy-wymieniony-bez-biegu",
        ),
        pytest.param(
            {f"{SKILL}/SKILL.md": f"---\nname: verify-a\npilnuje:\n  - frontend/src/karta.ts\nci: {SKILL}/scripts/sprawdz_a.py\nci-czesci: zero\n---\n"},
            False,
            {"skrypty/opis.py": "# nagłówek opisu\nX = 1\n"},
            [
                PRZECHODZI, *KROKI_CI,
                f"MAIN | krok skilla | PODSTAWA verify-a | FAIL znalezienia: ci-czesci w {SKILL}/SKILL.md nie jest liczbą części od 1",
                "DOWÓD FALI FAIL | krok skilla PODSTAWA verify-a",
            ], 1,
            id="krok-skilla-ktorego-ci-nie-da-sie-znalezc",
        ),
    ],
)
def test_dowod_fali_uruchamia_prace_pushu_spoza_pull_requestu_a_noc_i_podstawy_wymienia(
    tmp_path: Path, baza: dict[str, str], stary_skrot: bool, zmiana: dict[str, str], oczekiwane: list[str], kod: int
) -> None:
    wynik, poczatek = _fala(tmp_path, {**BAZA_FALI, **baza}, zmiana, stary_skrot=stary_skrot)

    jednostki = _jednostki(wynik, poczatek)
    poczatki = [linia[: len(oczekiwana)] for linia, oczekiwana in zip(jednostki[: len(oczekiwane)], oczekiwane[: len(jednostki)], strict=True)]
    assert (wynik.returncode, len(jednostki), poczatki) == (kod, len(oczekiwane), oczekiwane), wynik.stdout + wynik.stderr
    assert wynik.stdout.splitlines()[0].startswith("PR | Required CI pull requestu | wybór "), wynik.stdout


@pytest.mark.parametrize(("argumenty", "poczatek"), [(["--dowod-fali", "nie-ma-takiej-bazy"], "DOWÓD FALI FAIL | baza nie-ma-takiej-bazy: git merge-base"), (["--dowod-fali", "HEAD"], "DOWÓD FALI FAIL | brak zmiany od bazy HEAD")], ids=["nieznana-baza", "bez-zmiany"])
def test_dowod_fali_bez_bazy_albo_bez_zmiany_to_porazka(tmp_path: Path, capsys: pytest.CaptureFixture[str], argumenty: list[str], poczatek: str) -> None:
    _inwentarz(tmp_path, {"tools/a.py": "X = 1\n"})
    commit(tmp_path, "baza")

    kod = inwentarz_komentarzy.main(["--root", str(tmp_path), *argumenty])

    assert (kod, capsys.readouterr().out.splitlines()[-1].startswith(poczatek)) == (1, True)
