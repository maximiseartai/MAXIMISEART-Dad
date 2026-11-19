from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Final

import pytest

import odpalenia_ast_grep
import odpalenia_oxlint
from tests.fixtures.git_repo import commit, git

ROOT: Final = Path(__file__).resolve().parents[1]
FRONTEND: Final = ROOT / odpalenia_oxlint.FRONTEND
needs_oxlint = pytest.mark.skipif(
    odpalenia_oxlint.oxlint(FRONTEND) is None,
    reason="oxlint z zależności frontendu (npm ci w frontend/) ma zadanie CI Frontend, a zadania pytest go nie instalują",
)
DISABLING: Final = re.compile(r"no-comments|(?:eslint|oxlint)-disable(?:-line|-next-line)?(?=\s*(?:\*/|--|$))", re.IGNORECASE)
PLUGIN_PATH: Final = "frontend/tools/oxlint/repo/index.ts"


def disabling_lines(root: Path) -> list[str]:
    return [
        f"{path}:{number}: {text.strip()}"
        for path, number, text in odpalenia_ast_grep.Changes(root, odpalenia_ast_grep.EMPTY_TREE, odpalenia_oxlint.FRONTEND).added()
        if path != PLUGIN_PATH and DISABLING.search(text)
    ]


def _base() -> str | None:
    if base := os.environ.get("MAXIMISEART_ZAPADKA_BAZA"):
        return base
    try:
        return git(ROOT, "merge-base", "HEAD", "origin/main")
    except subprocess.CalledProcessError:
        return None


def test_zadna_linia_frontendu_nie_wylacza_reguly_no_comments() -> None:
    assert disabling_lines(ROOT) == [], (
        f"wyłączenie {odpalenia_oxlint.RULE} (jej nazwa albo dyrektywa oxlint lub eslint bez nazw reguł) chowa komentarz przed"
        " regułą: usuń je, a to, co mówi komentarz, wyraź nazwą, typem albo testem"
    )


def test_komentarz_na_linii_dodanej_we_frontendzie_jest_tylko_w_postaci_z_listy_wyjatkow() -> None:
    base = _base()
    if base is None:
        pytest.skip("brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz origin/main")

    assert [f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in odpalenia_oxlint.comments_on_added_lines(ROOT, base)] == []


@pytest.mark.parametrize(
    ("text", "caught"),
    [
        pytest.param("/* oxlint-disable repo/no-comments */\n", True, id="blok-z-nazwa-reguly"),
        pytest.param("// oxlint-disable-next-line repo/no-comments -- powód\n", True, id="nastepna-linia-z-nazwa-reguly"),
        pytest.param('{ "rules": { "repo/no-comments": "off" } }\n', True, id="konfiguracja-wylacza-regule"),
        pytest.param("/* eslint-disable */\n", True, id="blok-eslint-bez-nazw"),
        pytest.param("/*oxlint-disable*/\n", True, id="blok-oxlint-bez-nazw-i-spacji"),
        pytest.param("/* oxlint-disable\n */\n", True, id="blok-bez-nazw-na-dwoch-liniach"),
        pytest.param("export const a = 1 // eslint-disable-line\n", True, id="ta-linia-bez-nazw"),
        pytest.param("export const a = 1 // oxlint-disable-line -- proza\n", True, id="ta-linia-bez-nazw-z-powodem"),
        pytest.param("// oxlint-disable-next-line\n", True, id="nastepna-linia-bez-nazw"),
        pytest.param("// ESLINT-DISABLE\n", True, id="linia-bez-nazw-wielkimi-literami"),
        pytest.param("// oxlint-disable-next-line no-debugger -- powód\n", False, id="nastepna-linia-innej-reguly"),
        pytest.param("/* oxlint-disable no-debugger */\n", False, id="blok-innej-reguly"),
        pytest.param("export const disabled = true\n", False, id="slowo-bez-dyrektywy"),
    ],
)
def test_wylaczenie_no_comments_nazwa_albo_dyrektywa_bez_nazw_regul_jest_zgloszone(tmp_path: Path, text: str, caught: bool) -> None:
    git(tmp_path, "init", "--quiet")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "probka.ts").write_text(text, encoding="utf-8")
    tmp_path.joinpath(PLUGIN_PATH).parent.mkdir(parents=True)
    tmp_path.joinpath(PLUGIN_PATH).write_text('rules: { "no-comments": noCommentsRule }\n', encoding="utf-8")

    assert bool(disabling_lines(tmp_path)) is caught


def _frontend(root: Path, files: dict[str, str]) -> str:
    git(root, "init", "--quiet")
    (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    root.joinpath(PLUGIN_PATH).parent.mkdir(parents=True)
    shutil.copyfile(FRONTEND / odpalenia_oxlint.CONFIG, root / odpalenia_oxlint.FRONTEND / odpalenia_oxlint.CONFIG)
    shutil.copyfile(ROOT.joinpath(PLUGIN_PATH), root.joinpath(PLUGIN_PATH))
    (root / odpalenia_oxlint.FRONTEND / "node_modules").symlink_to(FRONTEND / "node_modules", target_is_directory=True)
    for name, text in files.items():
        (root / odpalenia_oxlint.FRONTEND / name).parent.mkdir(parents=True, exist_ok=True)
        (root / odpalenia_oxlint.FRONTEND / name).write_text(text, encoding="utf-8")
    return commit(root, "baza")


_SAFETY: Final = "const value: unknown = 1\n// SAFETY: wartość ustawiona linię wyżej\nexport const a = value as number\n"


@needs_oxlint
@pytest.mark.parametrize(
    ("name", "text", "lines"),
    [
        pytest.param("src/a.ts", "// proza\nexport const a = 1\n", [1], id="proza"),
        pytest.param("src/a.ts", "export const a = 1 // za kodem\n", [1], id="komentarz-za-kodem"),
        pytest.param("src/a.ts", "/* blok */\nexport const a = 1\n", [1], id="blok"),
        pytest.param("src/a.ts", "/**\n * Opis.\n */\nexport const a = 1\n", [1], id="jsdoc-na-trzech-liniach"),
        pytest.param("src/a.tsx", "export const A = () => <div>{/* jsx */}</div>\n", [1], id="komentarz-jsx"),
        pytest.param("scripts/a.mjs", "// skrypt\nexport const a = 1\n", [1], id="skrypt-mjs"),
        pytest.param("src/a.ts", _SAFETY, [], id="safety-nad-rzutowaniem"),
        pytest.param("src/a.ts", "//SAFETY: powód\nexport const a = 1\n", [1], id="safety-bez-spacji"),
        pytest.param("src/a.ts", "// SAFETY:\nexport const a = 1\n", [1], id="safety-bez-powodu"),
        pytest.param("src/a.ts", "/* SAFETY: powód */\nexport const a = 1\n", [1], id="safety-w-bloku"),
        pytest.param("src/a.ts", "// @ts-expect-error powód\nexport const a: number = 'a'\n", [], id="ts-expect-error-z-powodem"),
        pytest.param("src/a.ts", "// @ts-expect-error\nexport const a: number = 'a'\n", [1], id="ts-expect-error-bez-powodu"),
        pytest.param("src/a.ts", "// @ts-ignore powód\nexport const a: number = 'a'\n", [1], id="ts-ignore"),
        pytest.param("src/a.ts", "// oxlint-disable-next-line no-debugger -- powód\nexport const a = 1\n", [], id="dyrektywa-z-regula-i-powodem"),
        pytest.param("src/a.ts", "// oxlint-disable-next-line no-debugger, eqeqeq -- powód\nexport const a = 1\n", [], id="dyrektywa-z-dwiema-regulami"),
        pytest.param("src/a.ts", "// oxlint-disable-next-line no-debugger\nexport const a = 1\n", [1], id="dyrektywa-bez-powodu"),
        pytest.param("src/a.ts", "// eslint-disable-next-line no-debugger -- powód\nexport const a = 1\n", [1], id="dyrektywa-eslint"),
        pytest.param("src/a.ts", "// ZEWNĘTRZNE: Safari nie ma tej funkcji (https://webkit.org/status)\nexport const a = 1\n", [], id="zewnetrzne-ze-zrodlem"),
        pytest.param("src/a.ts", "// ZEWNĘTRZNE: Safari nie ma tej funkcji\nexport const a = 1\n", [1], id="zewnetrzne-bez-zrodla"),
        pytest.param("src/a.ts", "// ZEWNĘTRZNE: Safari nie ma tej funkcji (#1234)\nexport const a = 1\n", [1], id="zewnetrzne-z-numerem-issue"),
        pytest.param("src/a.ts", "// @ts-expect-error powód z #1234\nexport const a: number = 'a'\n", [1], id="powod-z-numerem-issue"),
        pytest.param(
            "src/a.ts",
            "// SAFETY: jak w https://github.com/maximiseartai/MAXIMISEART-Dad/pull/1\nexport const a = 1 as number\n",
            [1],
            id="powod-z-adresem-repo",
        ),
        pytest.param(
            "src/a.ts",
            "// ZEWNĘTRZNE: GitHub tnie (https://api.github.com/repos/maximiseartai/MAXIMISEART-Dad/issues/12)\nexport const a = 1\n",
            [1],
            id="zewnetrzne-z-adresem-api-repo",
        ),
        pytest.param(
            "src/a.ts",
            "// @ts-expect-error jak w github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/5\nexport const a: number = 'a'\n",
            [1],
            id="powod-z-adresem-repo-zgloszen",
        ),
        pytest.param("scripts/a.mjs", "#!/usr/bin/env node\nexport const a = 1\n", [], id="shebang-node"),
        pytest.param("scripts/a.mjs", "#!/usr/bin/env bun\nexport const a = 1\n", [1], id="shebang-innego-programu"),
        pytest.param("src/api/generated/a.ts", "// wygenerowane\nexport const a = 1\n", [], id="kod-wygenerowany-z-ignore-patterns"),
        pytest.param("src/components/ui/a.tsx", "// shadcn\nexport const a = 1\n", [], id="komponent-ui-z-ignore-patterns"),
    ],
)
def test_regula_no_comments_zglasza_komentarz_dodany_we_frontendzie_poza_postaciami_z_listy_wyjatkow(
    tmp_path: Path, name: str, text: str, lines: list[int]
) -> None:
    base = _frontend(tmp_path, {})
    (tmp_path / odpalenia_oxlint.FRONTEND / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / odpalenia_oxlint.FRONTEND / name).write_text(text, encoding="utf-8")

    found = odpalenia_oxlint.comments_on_added_lines(tmp_path, base)

    assert [(finding.path, finding.line, finding.rule) for finding in found] == [(f"frontend/{name}", line, odpalenia_oxlint.RULE) for line in lines]


_ESCAPED_RULE: Final = "repo/no-comment\\u0073"


@needs_oxlint
@pytest.mark.parametrize(
    ("name", "hiding"),
    [
        pytest.param("src/a.ts", {"frontend/.eslintignore": "src/a.ts\n"}, id="eslintignore"),
        pytest.param("src/a.ts", {"frontend/src/.eslintignore": "a.ts\n"}, id="eslintignore-w-podkatalogu"),
        pytest.param("src/a.ts", {"frontend/src/.gitignore": "a.ts\n"}, id="plik-git-add-f-spod-gitignore"),
        pytest.param("src/a.ts", {".gitignore": "node_modules\nfrontend/src/a.ts\n"}, id="plik-git-add-f-spod-gitignore-korzenia"),
        pytest.param("src/a.ts", {".git/info/exclude": "frontend/src/a.ts\n"}, id="plik-git-add-f-spod-info-exclude"),
        pytest.param("src/node_modules/a.ts", {}, id="katalog-node-modules"),
        pytest.param("src/a.ts", {"frontend/src/.oxlintrc.json": '{ "ignorePatterns": ["a.ts"] }\n'}, id="ignore-patterns-konfiguracji-w-podkatalogu"),
        pytest.param("src/a.ts", {"frontend/src/.oxlintrc.json": f'{{ "rules": {{ "{_ESCAPED_RULE}": "off" }} }}\n'}, id="regula-wylaczona-w-podkatalogu"),
        pytest.param(
            "src/a.ts",
            {"frontend/.oxlintrc.json": f'{{ "overrides": [{{ "files": ["src/a.ts"], "rules": {{ "{_ESCAPED_RULE}": "off" }} }}] }}\n'},
            id="overrides-konfiguracji-frontendu",
        ),
        pytest.param("src/a.ts", {"frontend/oxlint-suppressions.json": f'{{ "src/a.ts": {{ "{_ESCAPED_RULE}": {{ "count": 1 }} }} }}\n'}, id="plik-tlumien-oxlint"),
    ],
)
def test_regula_no_comments_zglasza_komentarz_w_pliku_ktory_oxlint_pomija_poza_ignore_patterns(tmp_path: Path, name: str, hiding: dict[str, str]) -> None:
    base = _frontend(tmp_path, {})
    for path, text in hiding.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    (tmp_path / odpalenia_oxlint.FRONTEND / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / odpalenia_oxlint.FRONTEND / name).write_text("// proza\nexport const a = 1\n", encoding="utf-8")
    git(tmp_path, "add", "--force", "--", f"{odpalenia_oxlint.FRONTEND}/{name}")

    found = odpalenia_oxlint.comments_on_added_lines(tmp_path, base)

    assert [(finding.path, finding.line) for finding in found] == [(f"frontend/{name}", 1)]


@needs_oxlint
def test_regula_no_comments_zglasza_tylko_komentarz_na_linii_dodanej_a_blok_od_pierwszej_dodanej_linii(tmp_path: Path) -> None:
    old = "// stary\n/*\n * stary blok\n */\nexport const a = 1\n"
    base = _frontend(tmp_path, {"src/a.ts": old, "src/b.ts": "export const b = 1\n"})
    (tmp_path / "frontend" / "src" / "a.ts").write_text(old.replace(" * stary blok", " * zmieniony blok") + "// nowy\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "b.ts").write_text("export const b = 1\n", encoding="utf-8")

    found = odpalenia_oxlint.comments_on_added_lines(tmp_path, base)

    assert [(finding.path, finding.line) for finding in found] == [("frontend/src/a.ts", 3), ("frontend/src/a.ts", 6)]


@needs_oxlint
def test_regula_no_comments_liczy_linie_jak_git_po_znakach_wielobajtowych_i_samotnym_powrocie_karetki(tmp_path: Path) -> None:
    base = _frontend(tmp_path, {})
    (tmp_path / "frontend" / "src").mkdir()
    (tmp_path / "frontend" / "src" / "a.ts").write_bytes('export const ąę = "żółć"\r// po samotnym r\nexport const b = ąę\n// trzecia\n'.encode())

    assert [(finding.path, finding.line) for finding in odpalenia_oxlint.comments_on_added_lines(tmp_path, base)] == [
        ("frontend/src/a.ts", 1),
        ("frontend/src/a.ts", 3),
    ]


@needs_oxlint
def test_plik_frontendu_ktorego_oxlint_nie_sparsuje_jest_porazka_a_nie_brak_komentarzy(tmp_path: Path) -> None:
    base = _frontend(tmp_path, {})
    (tmp_path / "frontend" / "src").mkdir()
    (tmp_path / "frontend" / "src" / "a.ts").write_text("export const a = (\n", encoding="utf-8")

    with pytest.raises(odpalenia_ast_grep.ScanFailed, match="oxlint nie sprawdził komentarzy frontend/src/a.ts"):
        odpalenia_oxlint.comments_on_added_lines(tmp_path, base)


def test_bez_oxlint_linia_dodana_we_frontendzie_jest_porazka_z_poleceniem_instalacji(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "a.ts").write_text("export const a = 1\n", encoding="utf-8")
    base = commit(tmp_path, "baza")
    (tmp_path / "frontend" / "b.ts").write_text("// proza\n", encoding="utf-8")

    with pytest.raises(odpalenia_ast_grep.ScanFailed, match=re.escape(odpalenia_oxlint.INSTALL)):
        odpalenia_oxlint.comments_on_added_lines(tmp_path, base)


ZNANE_LUKI_KOMENTARZY_FRONTENDU: Final[dict[str, dict[str, str]]] = {
    "treść dyrektywy bez sprawdzenia: proza w postaci SAFETY bez rzutowania pod nią": {"src/a.ts": "// SAFETY: tu jest cała historia zmiany\nexport const a = 1\n"},
    "treść dyrektywy bez sprawdzenia: proza jako powód @ts-expect-error": {"src/a.ts": "// @ts-expect-error tu jest cała historia zmiany\nexport const a: number = 'a'\n"},
    "fakt bez sprawdzenia: proza o kodzie repo w postaci ZEWNĘTRZNE": {"src/a.ts": "// ZEWNĘTRZNE: ta funkcja jest wolna (Maks)\nexport const a = 1\n"},
    "plik, którego oxlint nie czyta: CSS": {"src/a.css": "/* proza */\n.a { color: red; }\n"},
    "plik, którego oxlint nie czyta: HTML": {"index2.html": "<!-- proza -->\n<p></p>\n"},
    "plik, którego oxlint nie czyta: JSONC jak knip.jsonc": {"knip2.jsonc": "// proza\n{}\n"},
    "plik, którego oxlint nie czyta: JSON z komentarzem jak tsconfig.json": {"tsconfig.proba.json": '{\n  // proza\n  "compilerOptions": {}\n}\n'},
    "plik, który oxlint czyta tylko w części skryptu: szablon .vue": {"src/a.vue": "<template>\n  <!-- proza -->\n  <p></p>\n</template>\n"},
}


@needs_oxlint
def test_znane_luki_reguly_no_comments_przechodza_przez_regule_i_sprawdzenie_wylaczen(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki

    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, pliki) in enumerate(ZNANE_LUKI_KOMENTARZY_FRONTENDU.items()):
        root = tmp_path / str(numer)
        root.mkdir()
        base = _frontend(root, {})
        for name, text in pliki.items():
            (root / "frontend" / name).parent.mkdir(parents=True, exist_ok=True)
            (root / "frontend" / name).write_text(text, encoding="utf-8")
        found = odpalenia_oxlint.comments_on_added_lines(root, base)
        zgloszenia[opis] = [f"{finding.path}:{finding.line}" for finding in found] + disabling_lines(root)

    assert_znane_luki(zgloszenia, "tests/test_komentarze_frontendu.py::test_znane_luki_reguly_no_comments_przechodza_przez_regule_i_sprawdzenie_wylaczen")
