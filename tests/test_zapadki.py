"""Zapadki: reguły, które w ``tools/szybko.py`` padają tylko na liniach dodanych przez zmianę, i reguły całego drzewa.

W CI ``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py`` uruchamia każdą zapadkę
poza regułami ast-grep z bazą w pustym drzewie, więc tam zapadka zakazuje swojej formy w całym ``tests/`` i ``src/``.
Formę, która ma jeszcze stare wystąpienia, zapadka dostaje dopiero wtedy, gdy zmiana je usunie albo poprawi tamten test;
reguła ast-grep na liniach dodanych dostaje ją od razu, bo zgłasza tylko linie dodane od prawdziwej bazy zmiany. Reguły ast-grep
``REGULY_CALEGO_DRZEWA`` zgłaszają każdą linię swoich plików (``test_reguly_calego_drzewa_nie_zglaszaja_zadnej_linii``),
bez bazy, w ``tools/szybko.py`` i w zadaniu CI „Ruff, mypy”.

Bazę zmiany daje zmienna ``MAXIMISEART_ZAPADKA_BAZA`` (commit albo gałąź), a bez niej zapadka liczy od ``merge-base``
HEAD z ``origin/main``. Dodane linie to ``git diff`` od bazy (z niezacommitowanymi zmianami) i całe pliki nieśledzone.
Płytki checkout bez bazy (zadania pytest w CI) nie ma czego porównać, więc zapadka się pomija; pilnuje jej
``tools/szybko.py`` przed pushem, a reguł ast-grep na dodanych liniach całego repozytorium także zadanie CI „Ruff, mypy”
z bazą ``HEAD^1``. Linie dodane i odpalenia reguł ast-grep na nich liczy ``tools/lib/odpalenia_ast_grep.py``, ten sam
co dowód reguły ``tools/na_scalonych_pr.py --regula``. Moduł importuje tylko bibliotekę standardową, pytest i ten moduł
(z ``repo`` i ``potomne``, które importują tylko bibliotekę standardową), bo pomiar zapadek uruchamia go też w kopii
starego commitu; ta kopia potrzebuje więc obok także tych trzech plików ``tools/lib/``.
"""

from __future__ import annotations

from collections.abc import Mapping
import importlib.util
import json
import os
from pathlib import Path, PurePath
import re
import shutil
import subprocess
import sys
import sysconfig
from typing import Final

import pytest

import odpalenia_ast_grep

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"

# Odpowiedź nawigacji karty odrzucona w ``src/``, jak ``page.goto(…)`` w 637b1ef25c i ``with page.expect_navigation(…):``
# w 7ba1aaf8d1 (#808 r1 i r2: strona błędu serwera efenix wyglądała jak zmieniony efenix).
_DROPPED_NAVIGATION = re.compile(
    r"^\s*[A-Za-z_][\w.]*\.(?:goto|reload|go_back|go_forward)\("
    r"|^\s*with\b.*\bexpect_navigation\((?:[^()]|\([^()]*\))*\)(?!\s+as\b)"
)
_TRAILING_COMMENT = re.compile(r"\s#.*$")
_PLAYWRIGHT_IMPORT = re.compile(r"^\s*(?:from|import) playwright\b", re.MULTILINE)
_NAVIGATION_HELPER = (
    "odpowiedź nawigacji karty odrzucona: przejdź przez BrowserEfenix._go albo _reloaded"
    " (src/rozliczenia/efenix_browser.py) i stronę, której nie przeczytasz, zapytaj o nią _error_page, bo nawigacja nie"
    " zgłasza błędu przy statusie 4xx i 5xx"
)

# Pliki, którym wolno parsować Pythona ręcznie.
# Jeden napis z odstępami, bo graf wyboru testów (``tools/lib/wplyw_zmiany.py``) bierze ścieżkę z napisu testu za jego
# zależność, a zapadki i tak biegną przy każdej zmianie (``ZAPADKI`` w ``tools/szybko.py``).
PARSERS = frozenset(
    """
    .agents/skills/verify-centrum-rozliczen/scripts/centrum_self_test.py
    tests/fixtures/skladnia.py
    tests/test_decyzje_na_faktach.py
    tests/test_eksplorator_w_procesie.py
    tests/test_glossary.py
    tests/test_granice_importow.py
    tests/test_granice_wyjatkow.py
    tests/test_jeden_odczyt_skoroszytu.py
    tests/test_jeden_zapis_skoroszytu.py
    tests/test_komunikaty_expect.py
    tests/test_limit_drive_centrum.py
    tests/test_mapy_funkcji.py
    tests/test_potomne.py
    tests/test_rodzaj_zatrzymania.py
    tests/test_skrypty_bez_instalacji.py
    tests/test_spis_narzedzi.py
    tests/test_struktura_testow.py
    tests/test_tabela_zatrzyman_efenix.py
    tests/test_wywolanie_skryptow_skilli.py
    tools/inwentarz_komentarzy.py
    tools/lib/komunikat_mapy.py
    tools/lib/kroki_skilli.py
    tools/lib/niestabilne_testy.py
    tools/lib/rozjazd_modelu.py
    tools/lib/wplyw_zmiany.py
    tools/lib/zmiany_z_wydania.py
    tools/mutacje_zmiany.py
    tools/rownowaznosc.py
    """.split()
)
PARSER_FOLDERS = ("tests", "tools", ".agents/skills")
_PARSER_CALL = re.compile(r"(?<![\w.])(?:ast\.(?:parse|walk)\(|tokenize\.)")
_NEW_PARSER = (
    "nowy plik z ręcznym parserem Pythona (ast.parse, ast.walk, tokenize): nazwij korzeń poprawki i napraw go na"
    " najwyższym szczeblu z .agents/skills/przeglad/korzen.md; plik, który mimo to"
    " parsuje, dopisz do PARSERS w tests/test_zapadki.py z powodem w opisie PR, który mówi, dlaczego reguła ruff albo"
    " ast-grep ani test zachowania nie wystarczą, a recenzent sprawdza, czy ten powód jest prawdziwy (#1888)"
)
_GONE_PARSER = "plik zniknął: usuń go z PARSERS w tests/test_zapadki.py"


def _git(root: Path, *args: str) -> str:
    """Wyjście ``git``; bajt spoza UTF-8 (różnica pliku w innym kodowaniu, np. cp1250) staje się znakiem zastępczym."""

    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def _base() -> str | None:
    base = os.environ.get("MAXIMISEART_ZAPADKA_BAZA")
    if base:
        return base
    try:
        return _git(ROOT, "merge-base", "HEAD", BASE).strip()
    except subprocess.CalledProcessError:
        return None


def dropped_navigation(line: str, previous: str) -> bool:
    """Czy linia pliku ``src/`` z importem ``playwright`` (``navigation_drops``) odrzuca odpowiedź nawigacji karty;
    ``previous`` to poprzednia niepusta linia pliku, która nie jest samym komentarzem.

    Łapie tylko linię, która zaczyna się od kropkowanej nazwy i wywołania ``.goto(``, ``.reload(``, ``.go_back(`` albo
    ``.go_forward(`` (``page.goto(…)``, ``self._page.reload(…)``), oraz linię, która zaczyna się od ``with``, z
    ``expect_navigation(…)``, którego nawias zamyka się w tej samej linii (z najwyżej jednym poziomem nawiasów w
    środku) bez ``as`` po nim; obie także w linii napisu wielowierszowego. Przepuszcza każdą z nich, gdy ``previous``
    bez końcowych odstępów kończy się ``(``, ``[`` albo ``,`` tak, jak stoi, albo po zdjęciu wszystkiego od pierwszego
    odstępu z ``#`` (komentarz na końcu), bo tak ruff format łamie nawigację podaną dalej jako argument albo element
    listy (``return _checked(`` i pod nim ``page.goto(…``). Odstęp z ``#`` w napisie ``previous`` (``"strona #1",``)
    nie daje więc alarmu. Odpowiedź przypisana, zwrócona albo podana dalej w tej samej linii przechodzi. Plik bez linii,
    która po wcięciu zaczyna się od ``from playwright`` albo ``import playwright``, zapadka pomija; import pod
    ``if TYPE_CHECKING:`` się liczy. Postacie, których nie łapie ani zapadka, ani ruff, są próbkami ``ZNANE_LUKI`` tego
    pliku. Żadna forma nie trafia w dzisiejsze ``src/``, gdy każda jego linia jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    ends = (previous.rstrip(), _TRAILING_COMMENT.sub("", previous).rstrip())
    return _DROPPED_NAVIGATION.search(line) is not None and not any(end.endswith(("(", "[", ",")) for end in ends)


def navigation_drops(root: Path, base: str) -> list[str]:
    """Linie plików ``src/`` z importem ``playwright``, które zmiana od ``base`` dodaje z ``dropped_navigation``, z
    komunikatem. Inne pliki ``src/`` kart przeglądarki nie mają, a ich ``.reload(`` (np. ustawień) to nie nawigacja."""

    files: dict[str, tuple[bool, list[str]]] = {}
    found = []
    for path, number, line in odpalenia_ast_grep.added_lines(root, base, "src"):
        if path not in files:
            text = (root / path).read_text(encoding="utf-8")
            files[path] = (_PLAYWRIGHT_IMPORT.search(text) is not None, text.split("\n"))
        imports_playwright, lines = files[path]
        if not imports_playwright:
            continue
        earlier = (lines[index].strip() for index in range(number - 2, -1, -1))
        previous = next((text for text in earlier if text and not text.startswith("#")), "")
        if dropped_navigation(line, previous):
            found.append(f"{path}:{number}: {_NAVIGATION_HELPER}")
    return found


def test_odpowiedz_nawigacji_karty_w_src_nie_jest_odrzucona() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert navigation_drops(ROOT, base) == []


def test_zapadka_nawigacji_widzi_tylko_pliki_src_z_importem_playwright(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, *author, "commit", "-q", "--allow-empty", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path, imports in {
        "src/rozliczenia/okno.py": "from playwright.sync_api import Page\n",
        "src/rozliczenia/okno_typow.py": "if TYPE_CHECKING:\n    from playwright.sync_api import Page",
        "src/rozliczenia/ustawienia.py": "import importlib\n",
        "tests/test_okna.py": "from playwright.sync_api import Page\n",
        "tools/narzedzie.py": "from playwright.sync_api import Page\n",
    }.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(f"{imports}\n\ndef open_order(page, url):\n    page.goto(url)\n", encoding="utf-8")

    found = navigation_drops(tmp_path, base)

    assert found == [f"src/rozliczenia/okno.py:5: {_NAVIGATION_HELPER}", f"src/rozliczenia/okno_typow.py:5: {_NAVIGATION_HELPER}"]


def test_zapadka_nawigacji_przepuszcza_odpowiedz_podana_dalej_po_zlamaniu_linii(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, *author, "commit", "-q", "--allow-empty", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "okno.py").write_text(
        "from playwright.sync_api import Page\n"
        "\n\n"
        "def open_order(page, url):\n"
        "    return _checked(\n"
        "        page.goto(\n"
        "            url,\n"
        "            wait_until=\"load\",\n"
        "        )\n"
        "    )\n"
        "\n\n"
        "def open_list(page, url):\n"
        "    return _checked(\n"
        "        page,\n"
        "\n"
        "        page.goto(url, wait_until=\"load\"),\n"
        "    )\n"
        "\n\n"
        "def open_start(page, url):\n"
        "    return _checked(\n"
        "        page.goto(url, wait_until=\"load\", timeout=timeout_ms)\n"
        "    )\n"
        "\n\n"
        "def reload(page):\n"
        "    page.reload()\n"
        "\n\n"
        "def open_noted(page, url):\n"
        "    return _checked(\n"
        "        # lista zleceń\n"
        "        page.goto(url, wait_until=\"load\"),\n"
        "    )\n"
        "\n\n"
        "def statuses(page, urls):\n"
        "    return [\n"
        "        page.goto(url).status\n"
        "        for url in urls\n"
        "    ]\n"
        "\n\n"
        "def open_after_comment(page, url):\n"
        "    # najpierw lista zleceń,\n"
        "    page.goto(url)\n",
        encoding="utf-8",
    )

    found = navigation_drops(tmp_path, base)

    assert found == [f"src/okno.py:28: {_NAVIGATION_HELPER}", f"src/okno.py:47: {_NAVIGATION_HELPER}"]


@pytest.mark.parametrize(
    ("previous", "line"),
    [
        ("def open_order(page, url):", '    page.goto(urljoin(url, f"edit.php?id={order_id}"), wait_until="load", timeout=timeout_ms)'),
        ("    try:", "    with page.expect_navigation(wait_until=\"load\", timeout=timeout_ms):"),
        ("    def load_emmett(self) -> None:", "        with _doing(Operation.RELOAD), self._page.expect_navigation(wait_until=\"load\", timeout=self._timeout_ms):"),
        ("        with _doing(Operation.RELOAD):", "            self._page.reload(timeout=self._timeout_ms)"),
        ("    tab.go_forward()", "    tab.go_back()"),
        ("    )", "    with page.expect_navigation(timeout=min(a, b)), other():"),
        ("", "    page.goto(url)"),
        ('    log("lista #1,")', "    page.goto(url)"),
        # ``#`` bez odstępu przed nim nie zaczyna komentarza.
        ('    log("lista(#1)")', "    page.goto(url)"),
        # Dwie postacie, które reguła ast-grep z drzewa gubi, więc ta zapadka zostaje regexem (CODING_STANDARDS.md): odbiorca
        # nad wywołaniem dostaje wartość policzoną z odpowiedzi, a menedżer expect_navigation idzie do innego wywołania
        # w with bez as.
        ("    loaded = \\", "        page.goto(url) is not None"),
        ("def open_order(page, timed):", "    with timed(page.expect_navigation()):"),
    ],
)
def test_zapadka_lapie_odrzucona_odpowiedz_nawigacji(previous: str, line: str) -> None:
    assert dropped_navigation(line, previous)


@pytest.mark.parametrize(
    "line",
    [
        "    response = page.goto(url, wait_until=\"load\", timeout=timeout_ms)",
        "            return self._page.goto(url, wait_until=\"load\", timeout=self._timeout_ms)",
        "        with _doing(Operation.RELOAD), self._page.expect_navigation(wait_until=\"load\", timeout=self._timeout_ms) as reload:",
        "        return self._read_order(self._go(urljoin(self._url, f\"{ORDER_PAGE}?id={order.order_id}\")))",
        "        self._reloaded(accept)",
        "    # page.goto(url) odrzuca odpowiedź",
    ],
)
def test_zapadka_przepuszcza_odpowiedz_nawigacji_ktora_ktos_czyta(line: str) -> None:
    assert not dropped_navigation(line, "def open_order(page, url):")


@pytest.mark.parametrize(
    "previous",
    [
        "    return _checked(",
        "        page,",
        "    return _checked(  ",
        "    return _checked(  # lista zleceń",
        "    return [",
        '            "strona #1",',
        "    wait()  # najpierw lista,",
    ],
)
def test_zapadka_przepuszcza_nawigacje_ktora_jest_argumentem_po_zlamaniu_linii(previous: str) -> None:
    assert not dropped_navigation("        page.goto(", previous)


def test_zapadka_widzi_linie_dodane_od_bazy_i_nowe_pliki_a_nie_usuniete_ani_spoza_folderu(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("pierwsza\nusunieta\ntrzecia\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, *author, "commit", "-q", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "tests" / "test_a.py").write_text("pierwsza\ndodana\ntrzecia\nna końcu\n", encoding="utf-8")
    (tmp_path / "tests" / "fixtures").mkdir()
    (tmp_path / "tests" / "fixtures" / "nowy.py").write_text("nowa\n", encoding="utf-8")
    (tmp_path / "poza.py").write_text("poza testami\n", encoding="utf-8")

    added = sorted(odpalenia_ast_grep.added_lines(tmp_path, base, "tests"))

    assert added == [("tests/fixtures/nowy.py", 1, "nowa"), ("tests/test_a.py", 2, "dodana"), ("tests/test_a.py", 4, "na końcu")]


def test_zapadka_nie_liczy_linii_rozniacej_sie_tylko_koncem_crlf_jak_w_checkoucie_windows(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_bytes(b"pierwsza\ndruga\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "src" / "a.py").write_bytes(b"pierwsza\r\ndruga\r\nnowa\r\n")

    assert [(path, number) for path, number, _ in odpalenia_ast_grep.added_lines(tmp_path, base, "src")] == [("src/a.py", 3)]


def test_zapadka_repozytorium_widzi_dodane_linie_kazdego_pliku_takze_bez_rozszerzenia_i_spoza_utf8(tmp_path: Path) -> None:
    tracked = {
        ".agents/skills/s/SKILL.md": b"stara\n",
        ".github/workflows/ci.yml": b"on: push\n",
        "tools/bez_rozszerzenia": b"stara\n",
        "docs/ze spacja.md": b"stara\n",
        "dane/cp1250.txt": b"stara\n",
    }
    for path, text in tracked.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(text)
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path, text in tracked.items():
        (tmp_path / path).write_bytes(text + ("zażółć\n".encode("cp1250") if path.endswith("cp1250.txt") else b"nowa\n"))
    (tmp_path / "obraz.bin").write_bytes(b"\x89\x00\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "ignorowany.py").write_text("nowa\n", encoding="utf-8")
    if sys.platform != "win32":  # Dowiązanie na Windows wymaga uprawnień, których zadanie CI nie ma.
        (tmp_path / "dowiazanie").symlink_to("docs", target_is_directory=True)

    added = sorted((path, number) for path, number, _ in odpalenia_ast_grep.added_lines(tmp_path, base, ".", "*"))

    assert added == sorted([*((path, 2) for path in tracked), ("obraz.bin", 1)])


def test_zapadka_liczy_dodana_linie_zaczynajaca_sie_od_plusow_i_kazda_nastepna_linie_pliku(tmp_path: Path) -> None:
    """Dodana linia ``++ …`` jest w różnicy linią ``+++ …``, jak nagłówek pliku, a mimo to zostaje linią swojego pliku,
    tak jak dodane linie po niej i dodana linia następnego pliku."""

    (tmp_path / "docs").mkdir()
    for name in ("a.md", "b.md"):
        (tmp_path / "docs" / name).write_text("stara\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "docs" / "a.md").write_text("stara\n++ dodana\n++ b/udawany.md\nnowa\n", encoding="utf-8")
    (tmp_path / "docs" / "b.md").write_text("stara\nnowa\n", encoding="utf-8")

    added = sorted(odpalenia_ast_grep.added_lines(tmp_path, base, "docs", "*"))

    assert added == [("docs/a.md", 2, "++ dodana"), ("docs/a.md", 3, "++ b/udawany.md"), ("docs/a.md", 4, "nowa"), ("docs/b.md", 2, "nowa")]


def _committed(root: Path, files: Mapping[str, str]) -> str:
    """Repozytorium gita w ``root`` z plikami ``files`` w commicie bazy; zwraca bazę."""

    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(text.encode("utf-8"))
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "baza")
    return _git(root, "rev-parse", "HEAD").strip()


# Fikstura różnicy: dwa bliskie hunki i usunięta linia (a.py), ostatnia linia bez końca zamieniona na dwie (b.py,
# znacznik „\ No newline at end of file” w środku hunka), plik nieśledzony (c.py), przeniesiona linia, którą inny
# algorytm różnicy liczy jako starą (d.py), dodana linia, którą bez heurystyki wcięć git przesuwa o jedną (e.py),
# i plik przeniesiony w indeksie z dopisaną linią (f.py → g.py), którego bez wykrywania przeniesień każda linia jest
# dodana.
_DIFF_BASE: Final = {
    "src/rozliczenia/a.py": "X1 = 1\nX2 = 2\nX3 = 3\n\nX5 = 5\nX6 = 6\nX7 = 7\nX8 = 8\nX9 = 9\nX10 = 10\nX11 = 11\nX12 = 12\n",
    "src/rozliczenia/b.py": "Y1 = 1\nY2 = 2",
    "src/rozliczenia/d.py": "Z = 0\nE = 5  # komentarz\nZ = 0\n",
    "src/rozliczenia/e.py": "\nX = 1  # komentarz\nA = 1\nB = 2\n",
    "src/rozliczenia/f.py": "F1 = 1\nF2 = 2\nF3 = 3\nF4 = 4\n",
}
_DIFF_HEAD: Final = {
    "src/rozliczenia/a.py": "X1 = 1\nX2 = 2\nA = 1\nX3 = 3\n\nX5 = 5\nX6 = 6\nX7 = 7\nB = 2  # komentarz\nX8 = 8\nX10 = 10\nX11 = 11\nX12 = 12\n",
    "src/rozliczenia/b.py": "Y1 = 1\nY3 = 3\nC = 3  # komentarz",
    "src/rozliczenia/c.py": "D = 4  # komentarz\n",
    "src/rozliczenia/d.py": "Z = 0\nZ = 0\nE = 5  # komentarz\n",
    "src/rozliczenia/e.py": "\nX = 1  # komentarz\nX = 1  # komentarz\nA = 1\n",
    "src/rozliczenia/g.py": "F1 = 1\nF2 = 2\nF3 = 3\nF4 = 4\nG = 5  # komentarz\n",
}
_DIFF_UNTRACKED: Final = "src/rozliczenia/c.py"
# Plik przeniesiony w indeksie (``git mv``) przed zmianą drzewa: stara ścieżka → nowa.
_DIFF_MOVED: Final = {"src/rozliczenia/f.py": "src/rozliczenia/g.py"}
# Linie dodane w różnicy gita bez konfiguracji, jak w CI.
_DIFF_ADDED: Final = [
    ("src/rozliczenia/a.py", 3, "A = 1"),
    ("src/rozliczenia/a.py", 9, "B = 2  # komentarz"),
    ("src/rozliczenia/b.py", 2, "Y3 = 3"),
    ("src/rozliczenia/b.py", 3, "C = 3  # komentarz"),
    ("src/rozliczenia/c.py", 1, "D = 4  # komentarz"),
    ("src/rozliczenia/d.py", 3, "E = 5  # komentarz"),
    ("src/rozliczenia/e.py", 2, "X = 1  # komentarz"),
    ("src/rozliczenia/g.py", 5, "G = 5  # komentarz"),
]
# Postać, która bez ``odpalenia_ast_grep.Changes`` chowa linię dodaną albo zmienia jej numer:
# pliki (``.gitattributes`` z PR, ``.git/info/attributes``, pliki konfiguracji komputera), wpisy ``git config``
# checkoutu, zmienne środowiska wołającego i polecenia gita, które zapisują lokalny stan ``.git`` (obiekty podmienione
# przez ``refs/replace``, bity indeksu hooka ``core.fsmonitor``); ``{root}`` to katalog repozytorium, a ``{base}``
# commit bazy.
_TEXTCONV = {"diff.ukryj.textconv": "true"}
# Hook ``core.fsmonitor`` w powłoce gita (protokół 2): token bez żadnej zmienionej ścieżki, czyli „nic się nie
# zmieniło”; ``#`` chowa argumenty, które git dopisuje do polecenia.
_FSMONITOR_UNCHANGED = "printf 'tok\\0' #"
_COMMIT = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "zmiana")
_DIFF_DISGUISES: Final[dict[str, tuple[dict[str, str], dict[str, str], dict[str, str], tuple[tuple[str, ...], ...]]]] = {
    "-diff w .gitattributes": ({".gitattributes": "*.py -diff\n"}, {}, {}, ()),
    "binary w .gitattributes podkatalogu": ({"src/.gitattributes": "*.py binary\n"}, {}, {}, ()),
    "diff= z textconv w .gitattributes": ({".gitattributes": "*.py diff=ukryj\n"}, _TEXTCONV, {}, ()),
    "filter= z czyszczeniem w .gitattributes": ({".gitattributes": "*.py filter=ukryj\n"}, {"filter.ukryj.clean": "true"}, {}, ()),
    "-diff w .git/info/attributes": ({".git/info/attributes": "*.py -diff\n"}, {}, {}, ()),
    "diff= ze sterownikiem binarnym w .git/info/attributes": ({".git/info/attributes": "*.py diff=ukryj\n"}, {"diff.ukryj.binary": "true"}, {}, ()),
    "diff= z textconv w .git/info/attributes": ({".git/info/attributes": "*.py diff=ukryj\n"}, _TEXTCONV, {}, ()),
    "diff= z zewnętrznym programem w .git/info/attributes": ({".git/info/attributes": "*.py diff=ukryj\n"}, {"diff.ukryj.command": "true"}, {}, ()),
    "filter= z pliku core.attributesFile": (
        {"atrybuty": "*.py filter=ukryj\n"},
        {"core.attributesFile": "{root}/atrybuty", "filter.ukryj.clean": "true"},
        {},
        (),
    ),
    "przedrostki z diff.mnemonicPrefix": ({}, {"diff.mnemonicPrefix": "true"}, {}, ()),
    "kolory z color.diff": ({}, {"color.diff": "always"}, {}, ()),
    "kontekst między bliskimi hunkami z diff.interHunkContext": ({}, {"diff.interHunkContext": "10"}, {}, ()),
    "pusta linia kontekstu z diff.suppressBlankEmpty": ({}, {"diff.interHunkContext": "10", "diff.suppressBlankEmpty": "true"}, {}, ()),
    "kontekst z diff.context": ({}, {"diff.context": "5"}, {}, ()),
    "algorytm z diff.algorithm": ({}, {"diff.algorithm": "patience"}, {}, ()),
    "heurystyka wcięć z diff.indentHeuristic": ({}, {"diff.indentHeuristic": "false"}, {}, ()),
    "przeniesienia wyłączone przez diff.renames": ({}, {"diff.renames": "false"}, {}, ()),
    "kontekst z GIT_DIFF_OPTS": ({}, {}, {"GIT_DIFF_OPTS": "--unified=3"}, ()),
    "dosłowne ścieżki z GIT_LITERAL_PATHSPECS": ({}, {}, {"GIT_LITERAL_PATHSPECS": "1"}, ()),
    "ścieżki glob z GIT_GLOB_PATHSPECS": ({}, {}, {"GIT_GLOB_PATHSPECS": "1"}, ()),
    "ścieżki bez glob z GIT_NOGLOB_PATHSPECS": ({}, {}, {"GIT_NOGLOB_PATHSPECS": "1"}, ()),
    "wpis core.excludesFile z GIT_CONFIG_COUNT": (
        {"wykluczone": "c.py\n"},
        {},
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.excludesFile", "GIT_CONFIG_VALUE_0": "{root}/wykluczone"},
        (),
    ),
    "plik ignore gita z XDG_CONFIG_HOME": ({"xdg/git/ignore": "c.py\n"}, {}, {"XDG_CONFIG_HOME": "{root}/xdg"}, ()),
    "plik ignore gita w HOME": ({"dom/.config/git/ignore": "c.py\n"}, {}, {"HOME": "{root}/dom"}, ()),
    "core.excludesFile w konfiguracji checkoutu": ({"wykluczone": "c.py\n"}, {"core.excludesFile": "{root}/wykluczone"}, {}, ()),
    "drzewo robocze z core.worktree": ({"inne/.keep": ""}, {"core.worktree": "{root}/inne"}, {}, ()),
    "commit bazy podmieniony przez refs/replace na commit zmiany": ({}, {}, {}, (("add", "-A"), _COMMIT, ("replace", "{base}", "HEAD"))),
    "hook core.fsmonitor bez zmian przy bitach fsmonitor-valid": (
        {},
        {"core.fsmonitor": _FSMONITOR_UNCHANGED},
        {},
        (("update-index", "--fsmonitor"), ("update-index", "--fsmonitor-valid", "--", *(path for path in _DIFF_HEAD if path != _DIFF_UNTRACKED))),
    ),
}


def _disguised(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
    config: dict[str, str],
    environment: dict[str, str],
    commands: tuple[tuple[str, ...], ...],
) -> str:
    """Fikstura ``_DIFF_BASE`` w commicie bazy repozytorium ``root``, w indeksie przeniesienia ``_DIFF_MOVED``, w drzewie
    roboczym ``_DIFF_HEAD`` i postać ``_DIFF_DISGUISES``: jej pliki, wpisy ``git config`` checkoutu, polecenia gita
    w checkoucie i zmienne środowiska testu; zwraca bazę."""

    base = _committed(root, _DIFF_BASE)
    for old, new in _DIFF_MOVED.items():
        _git(root, "mv", old, new)
    for name, text in {**_DIFF_HEAD, **files}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(text.encode("utf-8"))
    for key, value in config.items():
        _git(root, "config", key, value.format(root=root))
    for command in commands:
        _git(root, *(argument.format(base=base) for argument in command))
    for name, value in environment.items():
        monkeypatch.setenv(name, value.format(root=root))
    return base


@pytest.mark.parametrize(("files", "config", "environment", "commands"), _DIFF_DISGUISES.values(), ids=_DIFF_DISGUISES)
def test_linie_dodane_nie_zaleza_od_atrybutow_konfiguracji_ani_srodowiska_gita(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
    config: dict[str, str],
    environment: dict[str, str],
    commands: tuple[tuple[str, ...], ...],
) -> None:
    """Atrybut z drzewa zmiany (``.gitattributes``, także w podkatalogu), atrybut ``diff`` spoza drzewa, konfiguracja
    różnicy w checkoucie, zmienna środowiska, obiekt podmieniony przez ``refs/replace`` ani hook ``core.fsmonitor``
    nie chowa linii dodanej przed zapadką i dowodem reguły ani nie zmienia jej numeru, bo oba biorą ją z ``Changes``:
    linie dodane są takie, jak w różnicy gita bez konfiguracji, czyli w CI."""

    base = _disguised(tmp_path, monkeypatch, files, config, environment, commands)

    assert sorted(odpalenia_ast_grep.added_lines(tmp_path, base, "src")) == _DIFF_ADDED
    assert sorted(line for line in odpalenia_ast_grep.added_lines(tmp_path, base, ".", "*") if line[0] in _DIFF_HEAD) == _DIFF_ADDED


@pytest.mark.parametrize("separator", ["\x1c", "\x0c", "\r", " "], ids=["x1c", "x0c", "samotne-r", "u2028"])
def test_linie_konczy_tylko_znak_nowej_linii_wiec_znak_podzialu_splitlines_nie_zjada_nastepnej_linii_dodanej(tmp_path: Path, separator: str) -> None:
    """``str.splitlines`` dzieli linię także na ``\\x1c``, ``\\x0c``, samotnym ``\\r`` i U+2028, więc kawałek ``+…``
    po takim znaku liczyłby się jako dodana linia z ``@@``, a prawdziwa następna linia wypadałaby z hunka."""

    base = _committed(tmp_path, {"src/a.py": "a = 1\n"})
    text = f"A = '{separator}+'\nB = 2\n"
    (tmp_path / "src" / "a.py").write_text("a = 1\n" + text, encoding="utf-8", newline="")
    (tmp_path / "src" / "nowy.py").write_text(text, encoding="utf-8", newline="")

    added = sorted(odpalenia_ast_grep.added_lines(tmp_path, base, "src"))

    assert added == [
        ("src/a.py", 2, f"A = '{separator}+'"),
        ("src/a.py", 3, "B = 2"),
        ("src/nowy.py", 1, f"A = '{separator}+'"),
        ("src/nowy.py", 2, "B = 2"),
    ]


def test_zapadka_bierze_baze_zmiany_ze_zmiennej(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAXIMISEART_ZAPADKA_BAZA", "galaz-rodzica")

    assert _base() == "galaz-rodzica"


def parsers_off_entry(root: Path, base: str) -> list[str]:
    """Pliki zmiany od ``base``, na których wpis ``PARSERS`` rozjeżdża się ze stanem, każdy z poleceniem naprawy.

    Łapie tylko plik ``*.py`` w ``tests/``, ``tools/`` albo ``.agents/skills/`` (bez ``tests/test_zapadki.py``), który
    zmiana dodaje, zmienia albo usuwa (zmiana nazwy to usunięcie i dodanie), gdy po zmianie jego tekst, z komentarzami i
    napisami, ma ``ast.parse(``, ``ast.walk(`` albo ``tokenize.``, a ``PARSERS`` go nie ma: nowy plik z ręcznym
    parserem albo istniejący, do którego zmiana dopisała pierwsze takie wywołanie.
    Z wpisu każe usunąć tylko plik z ``PARSERS``, którego zmiana usuwa.
    Plik z ``PARSERS``, z którego zmiana usuwa ostatnie takie wywołanie, przechodzi i zostaje we wpisie, bo zapadka pada
    tylko na dodanym: inaczej nocna mutacja, która usuwa linię parsera, byłaby WYKRYTA przez wpis, a nie przez test
    zachowania, i linia bez testu nie trafiłaby do ``Przeżyte mutacje z #N`` (#670).
    Nie łapie matchera dopisanego do pliku z ``PARSERS`` ani do ``tests/test_zapadki.py``, regexu,
    ``from ast import parse``, ``import ast as a``, samego ``import tokenize``, ``from tokenize import …``,
    ``compile(…, ast.PyCF_ONLY_AST)``, ``ast.NodeVisitor``, wywołania pomocnika, który parsuje za wywołującego
    (``tests/fixtures/skladnia.py``), ani parsera w ``src/`` i poza tymi trzema folderami; te zostają przeglądowi.
    Pliku z ``PARSERS``, którego zmiana nie dotyka, nie sprawdza.
    """

    patterns = [f"{folder}/*.py" for folder in PARSER_FOLDERS]
    changed = {
        *_git(root, "diff", "--no-renames", "--name-only", base, "--", *patterns).splitlines(),
        *_git(root, "ls-files", "--others", "--exclude-standard", "--", *patterns).splitlines(),
    }
    found = []
    for path in sorted(changed - {"tests/test_zapadki.py"}):
        file = root / path
        parses = file.is_file() and _PARSER_CALL.search(file.read_text(encoding="utf-8")) is not None
        if parses and path not in PARSERS:
            found.append(f"{path}: {_NEW_PARSER}")
        elif not file.is_file() and path in PARSERS:
            found.append(f"{path}: {_GONE_PARSER}")
    return found


def test_reczny_parser_pythona_stoi_tylko_w_plikach_z_wpisu() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")

    assert parsers_off_entry(ROOT, base) == []


# Plik z ``PARSERS``, który testy zapadki kładą w swoim repozytorium (zmienna, nie napis, z powodu jak przy ``PARSERS``).
_IN_ENTRY = min(PARSERS)


def _repo_with_parser(root: Path) -> str:
    """Repozytorium z jednym plikiem z ``PARSERS`` i jednym bez parsera; zwraca commit bazy."""

    for path, text in {
        _IN_ENTRY: "import ast\n\ntree = ast.parse(source)\n",
        "tests/test_zwykly.py": "def test_zwykly() -> None:\n    assert True\n",
    }.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "baza")
    return _git(root, "rev-parse", "HEAD").strip()


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("tests/test_nowy.py", "import ast\n\nnodes = list(ast.walk(ast.parse(source)))\n"),
        ("tests/fixtures/nowy.py", "for node in ast.walk(tree):\n    pass\n"),
        ("tools/lib/nowy.py", "import tokenize\n\ntokens = tokenize.generate_tokens(readline)\n"),
        (".agents/skills/verify-x/scripts/nowy.py", "tree = ast.parse(path.read_text())\n"),
        ("tests/test_zwykly.py", "import ast\n\n\ndef test_zwykly() -> None:\n    assert ast.parse('x')\n"),
    ],
    ids=["nowy-test", "nowy-pomocnik", "tokenize-w-tools", "skrypt-skilla", "pierwsze-wywolanie-w-istniejacym"],
)
def test_zapadka_parsera_lapie_plik_spoza_wpisu_z_recznym_parserem(tmp_path: Path, path: str, text: str) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(text, encoding="utf-8")

    assert parsers_off_entry(tmp_path, base) == [f"{path}: {_NEW_PARSER}"]


def test_zapadka_parsera_zada_powodu_dla_ktorego_regula_ani_test_zachowania_nie_wystarcza(tmp_path: Path) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / "tests" / "test_nowy.py").write_text("tree = ast.parse(source)\n", encoding="utf-8")

    [finding] = parsers_off_entry(tmp_path, base)

    assert "dopisz do PARSERS" in finding
    assert "w opisie PR, który mówi, dlaczego reguła ruff albo ast-grep ani test zachowania nie wystarczą" in finding


def test_zapadka_parsera_widzi_nowy_plik_oznaczony_git_add_n(tmp_path: Path) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / "tests" / "test_nowy.py").write_text("tree = ast.parse(source)\n", encoding="utf-8")
    _git(tmp_path, "add", "-N", "tests/test_nowy.py")

    assert parsers_off_entry(tmp_path, base) == [f"tests/test_nowy.py: {_NEW_PARSER}"]


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (_IN_ENTRY, "import ast\n\ntree = ast.parse(source)\nnodes = list(ast.walk(tree))\n"),
        ("tests/test_nowy.py", "import re\n\nCALL = re.compile(r'open\\(')\n"),
        ("tests/test_nowy.py", "from ast import parse\n\ntree = parse(source)\n"),
        ("tests/test_nowy.py", "import ast as syntax\n\ntree = syntax.parse(source)\n"),
        ("tests/test_nowy.py", "import tokenize\n"),
        ("tests/test_nowy.py", "from tokenize import generate_tokens\n\ntokens = generate_tokens(readline)\n"),
        ("tests/test_nowy.py", "from tests.fixtures.skladnia import calls\n\nfound = calls(tree)\n"),
        ("tests/test_nowy.py", "tree = myast.parse(source)\nvalue = node.ast.walk(x)\n"),
        ("src/pakiet/nowy.py", "tree = ast.parse(source)\n"),
        ("tests/test_zapadki.py", "tree = ast.parse(source)\n"),
    ],
    ids=[
        "matcher-w-pliku-z-wpisu",
        "regex",
        "from-ast-import",
        "alias-modulu",
        "import-tokenize",
        "from-tokenize-import",
        "pomocnik",
        "inna-nazwa-przed-kropka",
        "src",
        "plik-zapadek",
    ],
)
def test_zapadka_parsera_przepuszcza_formy_spoza_granicy(tmp_path: Path, path: str, text: str) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(text, encoding="utf-8")

    assert parsers_off_entry(tmp_path, base) == []


@pytest.mark.parametrize(
    ("removed", "written", "expected"),
    [
        (True, {}, [f"{_IN_ENTRY}: {_GONE_PARSER}"]),
        (False, {_IN_ENTRY: "from tests.fixtures.skladnia import calls\n"}, []),
        (
            True,
            {"tests/test_granice.py": "import ast\n\ntree = ast.parse(source)\n"},
            [f"{_IN_ENTRY}: {_GONE_PARSER}", f"tests/test_granice.py: {_NEW_PARSER}"],
        ),
    ],
    ids=["usuniety", "bez-wywolania", "nowa-nazwa"],
)
def test_zapadka_parsera_kaze_usunac_z_wpisu_tylko_plik_ktory_zniknal(
    tmp_path: Path, removed: bool, written: dict[str, str], expected: list[str]
) -> None:
    base = _repo_with_parser(tmp_path)
    if removed:
        (tmp_path / _IN_ENTRY).unlink()
    for path, text in written.items():
        (tmp_path / path).write_text(text, encoding="utf-8")
    # W indeksie, jak w commicie gałęzi, git widzi przeniesienie pliku jako zmianę nazwy.
    _git(tmp_path, "add", "-A")

    assert parsers_off_entry(tmp_path, base) == expected


def _empty_base(root: Path) -> str:
    """Repozytorium gita w ``root`` z pustym commitem bazy, więc każdy plik zapisany potem jest dodany; zwraca bazę."""

    _git(root, "init", "-q")
    _git(root, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "--allow-empty", "-m", "baza")
    return _git(root, "rev-parse", "HEAD").strip()


AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))
AST_GREP_CONFIG = ROOT / "sgconfig.yml"
# Jedyny katalog ``ruleDirs`` z ``sgconfig.yml``, szukany obok pliku konfiguracji; zgodność pokazuje test drogi od końca
# do końca, który kopiuje prawdziwy ``sgconfig.yml`` do drzewa tymczasowego.
AST_GREP_RULES = "reguly-ast-grep"
# Reguła ast-grep z ``AST_GREP_RULES`` → fragment jej komunikatu, który mówi, co zrobić zamiast zgłoszonego kodu.
AST_GREP_INSTRUCTIONS: Final[dict[str, str]] = {
    "historia-w-docstringu": "historię zmiany zostaw w opisie PR,",
    "komentarz-poza-src": "wyraź nazwą albo testem, który pada bez tego kodu, decyzję zapisz w ADR, motywację domenową w GLOSSARY.md, a historię zmiany w opisie PR",
    "komentarz-w-src": "wyraź nazwą albo testem, który pada bez tego kodu, decyzję zapisz w ADR, motywację domenową w GLOSSARY.md, a historię zmiany w opisie PR",
    "komunikat-boxa-podlancuchem": "bierz własność box_boat.WLASNOSC z junit",
    "kotwica-konca-linii": "użyj \\r?$ zamiast $",
    "krok-mypy-ruff-poza-krokami": "weź krok z kroki_lokalne.static_steps",
    "lokator-tytulu-okna": "użyj settings_title(page)",
    "naglowek-toml-podlancuchem": "czytaj plik tomllib",
    "odczyt-docstringu": "trzymaj w nazwanej stałej modułu",
    "przegladarka-bez-launch-options": "podaj w tym samym wywołaniu **launch_options(playwright)",
    "regula-w-trasie": "przenieś regułę do właściciela Ustawień",
    "stan-pliku-poza-file-state": "zapytaj src/rozliczenia/file_state.py",
    "stosunek-czasow-sciany": "licz kroki budżetu (węzły, wywołania), nie zegar",
    "watki-workera": "zapytaj tests/fixtures/linie_watkow.py",
    "wlasna-wyrocznia-numeru": "sprawdź tekst przez zawiera_wartosc",
}
needs_ast_grep = pytest.mark.skipif(
    AST_GREP is None,
    reason="ast-grep z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt; reguły ast-grep biegną"
    " w zadaniu CI „Ruff, mypy” i w tools/szybko.py",
)


def ast_grep_rules(config: Path) -> list[Path]:
    """Pliki reguł ast-grep w katalogu ``AST_GREP_RULES`` obok ``config``; bez katalogu żadnej reguły nie ma."""

    return sorted(path for pattern in ("*.yml", "*.yaml") for path in (config.parent / AST_GREP_RULES).rglob(pattern))


def syntax_rules(root: Path, base: str, config: Path = AST_GREP_CONFIG, ast_grep: str | None = AST_GREP) -> list[odpalenia_ast_grep.Finding]:
    """Odpalenia reguł ast-grep z ``config`` na liniach dodanych w repozytorium ``root`` od ``base``
    (``odpalenia_ast_grep.on_added_lines``: węzeł obejmuje którąkolwiek linię dodaną, linia to pierwsza dodana).

    Bez pliku reguły zapadka nie woła ``ast-grep``, więc checkout bez dodatku dev przechodzi; z regułą i dodaną linią
    brak ``ast-grep`` jest porażką z poleceniem instalacji. O tym, w których plikach z dodaną linią reguła szuka,
    decydują jej pola ``files:`` i ``ignores:`` (``ast_grep_rules_without_scope``). Zgłasza każda reguła katalogu,
    także z ``severity: off`` w pliku, i wbudowane reguły o dyrektywie tłumienia: regułę wyłącza tylko
    usunięcie jej pliku. Postacie, których nie łapie ani reguła, ani ruff, są próbkami ``ZNANE_LUKI`` tego pliku.
    """

    if not ast_grep_rules(config):
        return []
    return odpalenia_ast_grep.on_added_lines(root, base, ("--config", str(config)), ast_grep)


def syntax_rule_findings(root: Path, base: str) -> list[str]:
    return [f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in syntax_rules(root, base)]


# Zadania pytest na Windows instalują tylko requirements.txt, bez dodatku dev, więc tam reguły ast-grep (na liniach
# dodanych i całego drzewa) się pomijają, a biegną w zadaniach pytest na Linuksie i w zadaniu „Ruff, mypy”; poza
# Windows brak ast-grep to porażka z poleceniem instalacji (``odpalenia_ast_grep.INSTALL``), a nie ciche pominięcie.
BEZ_DODATKU_DEV = sys.platform == "win32"
windows_without_ast_grep = pytest.mark.skipif(
    AST_GREP is None and BEZ_DODATKU_DEV,
    reason="ast-grep z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt; reguły ast-grep biegną"
    " w zadaniach pytest na Linuksie, w zadaniu CI „Ruff, mypy” i w tools/szybko.py",
)


@windows_without_ast_grep
def test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert syntax_rule_findings(ROOT, base) == []


# Reguły ast-grep z ``AST_GREP_RULES``, które obowiązują każdą linię swoich plików (pole ``files:`` reguły), a nie tylko
# linie dodane przez zmianę, i folder, od którego liczy je ``whole_tree_rules``.
REGULY_CALEGO_DRZEWA: Final = (
    "historia-w-docstringu",
    "komentarz-w-src",
    "komunikat-boxa-podlancuchem",
    "kotwica-konca-linii",
    "krok-mypy-ruff-poza-krokami",
    "lokator-tytulu-okna",
    "naglowek-toml-podlancuchem",
    "odczyt-docstringu",
    "regula-w-trasie",
    "stan-pliku-poza-file-state",
    "stosunek-czasow-sciany",
    "watki-workera",
    "wlasna-wyrocznia-numeru",
)
CALE_DRZEWO: Final = "."


def whole_tree_rules(
    root: Path, rules: tuple[str, ...] = REGULY_CALEGO_DRZEWA, folder: str = CALE_DRZEWO, config: Path = AST_GREP_CONFIG, ast_grep: str | None = AST_GREP
) -> list[odpalenia_ast_grep.Finding]:
    """Odpalenia reguł ``rules`` z ``config`` na każdej linii plików ``folder`` checkoutu ``root``: śledzonych, także
    ignorowanych przez ``.gitignore``, i nieśledzonych bez ignorowanych (``odpalenia_ast_grep.on_added_lines`` od
    pustego drzewa); o tym, w których plikach reguła szuka, decydują jej ``files:`` i ``ignores:``, a linia odpalenia
    to pierwsza linia węzła."""

    arguments = ("--config", str(config), "--filter", f"^(?:{'|'.join(rules)})$")
    return odpalenia_ast_grep.on_added_lines(root, odpalenia_ast_grep.EMPTY_TREE, arguments, ast_grep, folder)


@windows_without_ast_grep
def test_reguly_calego_drzewa_nie_zglaszaja_zadnej_linii() -> None:
    assert [f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in whole_tree_rules(ROOT)] == []


def test_kazda_regula_calego_drzewa_jest_w_katalogu_regul() -> None:
    """``--filter`` z id, którego katalog reguł nie ma, obok id, które ma, gubi tę regułę bez błędu ast-grep."""

    ids = {str(rule["id"]) for rule in _ast_grep_rule_documents(AST_GREP_CONFIG)}
    assert set(REGULY_CALEGO_DRZEWA) - ids == set(), f"popraw REGULY_CALEGO_DRZEWA na id reguł z {AST_GREP_RULES}/"


# Rozszerzenia plików, które ast-grep 0.51 czyta jako Python (jedyny język reguł z ``AST_GREP_RULES``, bez
# ``languageGlobs`` w ``sgconfig.yml``), i tekst dyrektywy tłumienia ast-grep, z którego próbki tego pliku ją składają.
PYTHON_SUFFIXES: Final = odpalenia_ast_grep.PYTHON_SUFFIXES
_IGNORE: Final = odpalenia_ast_grep.SUPPRESSION


def ast_grep_suppressions(root: Path, folder: str = CALE_DRZEWO) -> list[str]:
    """``plik:linia`` każdej linii z tekstem dyrektywy tłumienia ast-grep (``odpalenia_ast_grep.SUPPRESSION``)
    w plikach Pythona ``folder`` checkoutu ``root``, tych samych co ``whole_tree_rules``. Test nie
    pyta, czy tekst stoi w komentarzu: dyrektywa, którą ast-grep uznaje, zawsze ma ten tekst w całości, a własny
    parser komentarza rozjeżdża się z parserem ast-grep (``#`` i samotne ``\\r``, sonda przeglądu #2099 r2)."""

    return [
        f"{path}:{number}"
        for path, number, text in odpalenia_ast_grep.Changes(root, odpalenia_ast_grep.EMPTY_TREE, folder).added()
        if path.endswith(PYTHON_SUFFIXES) and _IGNORE in text
    ]


def test_zadna_linia_repo_nie_tlumi_reguly_ast_grep() -> None:
    """Reguła chwastu nie ma prawa właściciela w komentarzu (ADR 0036): dyrektywa tłumienia z nazwą reguły chowa jej
    odpalenie przed zapadką linii dodanych i przed regułami całego drzewa, a wbudowane reguły ast-grep zgłaszają tylko
    dyrektywę bez nazw albo taką, która niczego nie wyłącza. Wyjątek reguły stoi więc tylko w jej ``ignores:``, który
    widać w diffie reguły, a w plikach Pythona, w których ast-grep szuka reguł, tekst dyrektywy nie stoi wcale."""

    import yaml

    languages = {str(rule["language"]).lower() for rule in _ast_grep_rule_documents(AST_GREP_CONFIG)}
    assert languages == {"python"}, f"reguła ast-grep w języku spoza Pythona ({sorted(languages)}): dopisz jego pliki do ast_grep_suppressions"
    assert "languageGlobs" not in yaml.safe_load(AST_GREP_CONFIG.read_text(encoding="utf-8")), (
        "languageGlobs w sgconfig.yml daje Pythona innym plikom niż PYTHON_SUFFIXES: dopisz je tam"
    )
    assert ast_grep_suppressions(ROOT) == [], (
        f"{_IGNORE} chowa odpalenie reguły chwastu przed CI: popraw kod według komunikatu reguły, a trwały wyjątek "
        f"właściciela dopisz do ignores: jej pliku w {AST_GREP_RULES}/; tekst dyrektywy w próbce albo komunikacie składaj "
        "z odpalenia_ast_grep.SUPPRESSION"
    )


def banned_under_noqa(root: Path) -> list[str]:
    """``plik:linia: komunikat`` każdego zakazu ``banned-api`` (``TID251``) i ``import *`` (``F403``, który chowa nazwę
    przed ``TID251``), które ``ruff check --ignore-noqa`` zgłasza w ``root`` z konfiguracją repozytorium. Zwykłe ``ruff
    check`` przechodzi, więc każde takie zgłoszenie chowa ``# noqa``, ``# ruff: noqa`` na pliku albo zakres ``# ruff:
    disable``; zwolnienie w konfiguracji ruff (prawo właściciela) zostaje zwolnieniem."""

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--ignore-noqa", "--output-format", "json"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.stderr == "", result.stderr
    return [
        f"{Path(finding['filename']).resolve().relative_to(root.resolve()).as_posix()}:{finding['location']['row']}: {finding['message']}"
        for finding in json.loads(result.stdout)
        if finding["code"] in ("TID251", "F403")
    ]


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_zadna_linia_repo_nie_tlumi_zakazu_ruff() -> None:
    """Zakaz ``banned-api`` nie ma prawa właściciela w komentarzu (ADR 0036): zakazanej nazwy używa tylko plik z prawem
    właściciela w konfiguracji ruff (``per-file-ignores`` i ``OWNERS`` w ``tests/test_zakazy_ruff.py``), więc
    ``banned_under_noqa`` na całym kodzie, który ruff sprawdza, nie zgłasza niczego."""

    assert banned_under_noqa(ROOT) == [], (
        "noqa chowa zakazaną nazwę przed ruff: użyj tego, co mówi komunikat zakazu, a trwałe prawo właściciela zapisz w "
        "per-file-ignores ruff.toml i w OWNERS tests/test_zakazy_ruff.py"
    )


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_noqa_przy_zakazanej_nazwie_i_gwiazdce_jest_zgloszone_a_prawo_wlasciciela_nie(tmp_path: Path) -> None:
    """Prawdziwy ruff z ``ruff.toml`` repozytorium: ``# noqa`` na linii, ``# ruff: noqa`` na pliku i ``# ruff:
    disable`` chowają ``TID251``, a ``# noqa: F403`` gwiazdkę, więc ``banned_under_noqa`` zgłasza każdą z tych linii, a
    zakazanej nazwy u właściciela z ``per-file-ignores`` nie."""

    shutil.copyfile(ROOT / "ruff.toml", tmp_path / "ruff.toml")
    files = {
        "tools/linia.py": "import os\n\nSYSTEM = os.name  # noqa: TID251 - próbka\n",
        "tools/plik.py": "# ruff: noqa\nimport os\n\nSYSTEM = os.name\n",
        "tools/zakres.py": "import os\n\n# ruff: disable[TID251]\nSYSTEM = os.name\n# ruff: enable[TID251]\n",
        "tools/gwiazdka.py": "from os import *  # noqa: F403 - próbka\n",
        "tools/lib/import_dynamiczny.py": 'import importlib\n\nMODUL = importlib.import_module("json")\n',
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")

    assert sorted(finding.split(": ")[0] for finding in banned_under_noqa(tmp_path)) == [
        "tools/gwiazdka.py:1",
        "tools/linia.py:3",
        "tools/plik.py:4",
        "tools/zakres.py:4",
    ]


@needs_ast_grep
def test_dyrektywa_ast_grep_po_kazdym_znaku_po_haszu_jest_zgloszona_gdy_chowa_odpalenie(tmp_path: Path) -> None:
    """Klasa przedrostków dyrektywy: każdy znak ASCII od U+0001 bez liter, cyfr i ``\\n``, każdy biały znak Unicode
    i kilka znaków interpunkcji Unicode między ``#`` a tekstem dyrektywy.
    Każdy plik, w którym prawdziwy ast-grep chowa wywołanie reguły-fikstury, ``ast_grep_suppressions`` zgłasza, a
    ast-grep chowa je co najmniej po ``##`` (sonda przeglądu #2099 r1) i po samotnym ``\\r`` (r2). Tekst dyrektywy
    wielkimi literami ast-grep 0.51 pomija, więc test go nie szuka; gdy ast-grep zacznie go uznawać, ten test pada."""

    config = _fixture_rules(tmp_path)
    base = _empty_base(tmp_path)
    folder = tmp_path / "src" / "rozliczenia"
    folder.mkdir(parents=True)
    signs = [chr(code) for code in range(1, 0x80) if chr(code) != "\n" and not chr(code).isalnum()]
    signs += [chr(code) for code in range(0x80, 0x3000) if chr(code).isspace()] + ["\u2014", "\u00b7", "\u201e", "\u00a7"]
    for number, sign in enumerate(signs):
        (folder / f"probka_{number}.py").write_text(f"zakazane()  #{sign}{_IGNORE}: zakazane-wywolanie\n", encoding="utf-8", newline="")
    (folder / "wielkie.py").write_text(f"zakazane()  # {_IGNORE.upper()}: zakazane-wywolanie\n", encoding="utf-8")

    shown = {finding.path for finding in syntax_rules(tmp_path, base, config) if finding.rule == "zakazane-wywolanie"}
    hidden = {f"src/rozliczenia/probka_{number}.py" for number in range(len(signs))} - shown
    assert {f"src/rozliczenia/probka_{signs.index(sign)}.py" for sign in ("#", "\r")} <= hidden
    assert "src/rozliczenia/wielkie.py" in shown
    assert sorted(hidden - {line.rpartition(":")[0] for line in ast_grep_suppressions(tmp_path)}) == []


@needs_ast_grep
def test_pliki_pythona_dyrektyw_to_pliki_ktore_ast_grep_czyta_jako_python(tmp_path: Path) -> None:
    """``PYTHON_SUFFIXES`` to dokładnie te rozszerzenia próbki (Pythona i jemu bliskie), w których prawdziwy ast-grep
    zgłasza regułę-fiksturę w Pythonie, więc dyrektywa w pliku, który ast-grep czyta jako Python, nie jest poza testem."""

    config = _fixture_rules(tmp_path)
    base = _empty_base(tmp_path)
    folder = tmp_path / "src" / "rozliczenia"
    folder.mkdir(parents=True)
    suffixes = (".py", ".pyi", ".py3", ".bzl", ".pyw", ".pyx", ".pyc", ".ipynb", ".gyp")
    for suffix in suffixes:
        (folder / f"probka{suffix}").write_text("zakazane()\n", encoding="utf-8")

    shown = {PurePath(finding.path).suffix for finding in syntax_rules(tmp_path, base, config)}
    assert sorted(shown) == sorted(PYTHON_SUFFIXES)


@windows_without_ast_grep
def test_reguly_calego_drzewa_zglaszaja_linie_bazy_i_plik_nowy_a_zapadka_tylko_plik_nowy(tmp_path: Path) -> None:
    """Komentarz i docstring z numerem issue w pliku ``src/`` z commitu bazy zgłaszają reguły całego drzewa, choć
    zapadka linii dodanych ich nie widzi; nowy plik nieśledzony zgłaszają obie, a komentarz w ``tests/`` żadna."""

    base = _committed(
        tmp_path,
        {
            "src/rozliczenia/stary.py": '"""Moduł z #1618."""\n\nX = 1  # stary komentarz\n',
            "tests/test_stary.py": "X = 1  # komentarz testu\n",
        },
    )
    (tmp_path / "src" / "rozliczenia" / "nowy.py").write_text("Y = 2  # nowy komentarz\n", encoding="utf-8")

    assert [(finding.path, finding.line, finding.rule) for finding in whole_tree_rules(tmp_path)] == [
        ("src/rozliczenia/nowy.py", 1, "komentarz-w-src"),
        ("src/rozliczenia/stary.py", 1, "historia-w-docstringu"),
        ("src/rozliczenia/stary.py", 3, "komentarz-w-src"),
    ]
    assert [(finding.path, finding.line) for finding in syntax_rules(tmp_path, base)] == [("src/rozliczenia/nowy.py", 1)]


@needs_ast_grep
@pytest.mark.parametrize(
    ("files", "config", "environment", "commands"),
    [_DIFF_DISGUISES[name] for name in ("-diff w .gitattributes", "plik ignore gita w HOME")],
    ids=["-diff w .gitattributes", "plik ignore gita w HOME"],
)
def test_regula_komentarz_w_src_zglasza_kazdy_dodany_komentarz_mimo_atrybutow_konfiguracji_i_srodowiska_gita(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
    config: dict[str, str],
    environment: dict[str, str],
    commands: tuple[tuple[str, ...], ...],
) -> None:
    """Zapadka reguł ast-grep z prawdziwą regułą ``komentarz-w-src`` zgłasza w postaci z ``_DIFF_DISGUISES``
    każdy komentarz, który fikstura różnicy dodaje w ``src/``, na jego linii, jak w CI."""

    base = _disguised(tmp_path, monkeypatch, files, config, environment, commands)

    found = [(finding.path, finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)]
    assert found == [(path, number, "komentarz-w-src") for path, number, text in _DIFF_ADDED if "#" in text]


# Znane luki ``odpalenia_ast_grep.Changes``: lokalny stan checkoutu, którego zmiana nie zapisuje w commicie, a żadna
# zmienna ani opcja gita nie wyłącza (plik ``.git/info``, bit indeksu), chowa linię dodaną przed zapadką; Required CI
# biegnie na świeżym checkoucie bez niego. Klasa: postać → pliki zmiany na bazie z ``src/rozliczenia/a.py`` i polecenia
# gita w checkoucie po niej.
_BAZA_ZNANYCH_LUK_ZMIAN: Final = {"src/rozliczenia/a.py": "X = 1\n"}
# Parzysta liczba bajtów, więc git czyta plik jako UTF-16LE bez błędu: jedna linia znaków spoza ASCII.
_DODANY_KOMENTARZ: Final = "X = 1\nY = 2  # komentarze\n"
ZNANE_LUKI_ZMIAN: Final[dict[str, tuple[dict[str, str], tuple[tuple[str, ...], ...]]]] = {
    "atrybut spoza drzewa: working-tree-encoding z .git/info/attributes": (
        {".git/info/attributes": "*.py working-tree-encoding=UTF-16LE\n", "src/rozliczenia/a.py": _DODANY_KOMENTARZ},
        (),
    ),
    "wykluczenie spoza drzewa: plik nieśledzony z .git/info/exclude": (
        {".git/info/exclude": "nowy.py\n", "src/rozliczenia/nowy.py": "X = 1  # komentarz\n"},
        (),
    ),
    "lokalny stan indeksu checkoutu: bit assume-unchanged na zmienionym pliku": (
        {"src/rozliczenia/a.py": _DODANY_KOMENTARZ},
        (("update-index", "--assume-unchanged", "--", "src/rozliczenia/a.py"),),
    ),
    "lokalny stan indeksu checkoutu: bit skip-worktree na zmienionym pliku": (
        {"src/rozliczenia/a.py": _DODANY_KOMENTARZ},
        (("update-index", "--skip-worktree", "--", "src/rozliczenia/a.py"),),
    ),
}


@needs_ast_grep
def test_znane_luki_zmian_przechodza_przez_zapadke_regul_ast_grep(tmp_path: Path) -> None:
    """Każda próbka ``ZNANE_LUKI_ZMIAN`` przechodzi przez zapadkę reguł ast-grep z prawdziwą regułą
    ``komentarz-w-src``, choć dodaje komentarz w ``src/``."""

    from tests.fixtures.znane_luki import assert_znane_luki

    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, (pliki, polecenia)) in enumerate(ZNANE_LUKI_ZMIAN.items()):
        root = tmp_path / str(numer)
        base = _committed(root, _BAZA_ZNANYCH_LUK_ZMIAN)
        for nazwa, tekst in pliki.items():
            (root / nazwa).parent.mkdir(parents=True, exist_ok=True)
            (root / nazwa).write_bytes(tekst.encode("utf-8"))
        for polecenie in polecenia:
            _git(root, *polecenie)
        zgloszenia[opis] = [f"zapadka: {finding}" for finding in syntax_rules(root, base)]

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py (ZNANE_LUKI_ZMIAN)")


def _src_sample(root: Path, text: str, name: str = "probka.py") -> str:
    """Repozytorium z pustą bazą w ``root`` i nowym plikiem ``src/rozliczenia/<name>`` z ``text``, czyli dodaną
    próbką, złą albo dobrą, dla ``syntax_rules``; zwraca bazę."""

    base = _empty_base(root)
    (root / "src" / "rozliczenia").mkdir(parents=True)
    (root / "src" / "rozliczenia" / name).write_text(text, encoding="utf-8")
    return base


def _ast_grep_rule_documents(config: Path) -> list[dict[str, object]]:
    """Każda reguła z plików ``ast_grep_rules(config)``; plik reguły może mieć kilka dokumentów YAML."""

    import yaml

    return [rule for path in ast_grep_rules(config) for rule in yaml.safe_load_all(path.read_text(encoding="utf-8"))]


def ast_grep_rules_without_instruction(config: Path, instructions: dict[str, str]) -> list[str]:
    """Reguły ast-grep z ``config`` bez wpisu w ``instructions`` albo z komunikatem bez fragmentu z wpisu, i wpisy bez
    reguły."""

    messages = {str(rule["id"]): str(rule.get("message", "")) for rule in _ast_grep_rule_documents(config)}
    return sorted(
        [f"{rule}: brak wpisu w AST_GREP_INSTRUCTIONS" for rule in messages.keys() - instructions.keys()]
        + [f"{rule}: wpis bez reguły w {AST_GREP_RULES}/" for rule in instructions.keys() - messages.keys()]
        + [
            f"{rule}: komunikat nie mówi „{instructions[rule]}”"
            for rule, message in messages.items()
            if rule in instructions and instructions[rule] not in message
        ]
    )


def test_komunikat_kazdej_reguly_ast_grep_mowi_co_zrobic() -> None:
    assert ast_grep_rules_without_instruction(AST_GREP_CONFIG, AST_GREP_INSTRUCTIONS) == []


def ast_grep_rules_without_scope(config: Path) -> list[str]:
    """Reguły ast-grep z ``config`` bez niepustego pola ``files:``, każda z poleceniem naprawy: zapadka podaje ast-grep
    każdy plik repozytorium z dodaną linią, więc reguła bez ``files:`` obejmowałaby całe repozytorium."""

    return sorted(problem for rule in _ast_grep_rule_documents(config) if (problem := odpalenia_ast_grep.unscoped(rule)))


def test_kazda_regula_ast_grep_ma_zakres_w_polu_files() -> None:
    assert ast_grep_rules_without_scope(AST_GREP_CONFIG) == []


_FIXTURE_RULE = """\
id: zakazane-wywolanie
language: python
severity: error
message: "Zamień zakazane() na dozwolone()."
files:
  - src/**
rule:
  pattern: zakazane()
"""


def _fixture_rules(root: Path) -> Path:
    """Prawdziwy ``sgconfig.yml`` w ``root`` z regułą-fiksturą ``zakazane-wywolanie`` w jego katalogu reguł."""

    config = root / "sgconfig.yml"
    shutil.copyfile(AST_GREP_CONFIG, config)
    (root / AST_GREP_RULES).mkdir()
    (root / AST_GREP_RULES / "zakazane-wywolanie.yml").write_text(_FIXTURE_RULE, encoding="utf-8")
    return config


def test_komunikat_reguly_ast_grep_bez_polecenia_jest_zgloszony(tmp_path: Path) -> None:
    config = _fixture_rules(tmp_path)

    assert ast_grep_rules_without_instruction(config, {"zakazane-wywolanie": "na dozwolone()"}) == []
    assert ast_grep_rules_without_instruction(config, {"zakazane-wywolanie": "usuń wywołanie"}) == [
        "zakazane-wywolanie: komunikat nie mówi „usuń wywołanie”"
    ]
    assert ast_grep_rules_without_instruction(config, {"inna": "x"}) == [
        "inna: wpis bez reguły w reguly-ast-grep/",
        "zakazane-wywolanie: brak wpisu w AST_GREP_INSTRUCTIONS",
    ]


def test_bez_regul_ast_grep_zapadka_przechodzi_bez_ast_grep(tmp_path: Path) -> None:
    config = tmp_path / "sgconfig.yml"
    shutil.copyfile(AST_GREP_CONFIG, config)
    base = _src_sample(tmp_path, "zakazane()\n")

    assert syntax_rules(tmp_path, base, config, ast_grep=None) == []


def test_z_regula_ast_grep_brak_ast_grep_przy_dodanej_linii_poza_src_jest_porazka_z_poleceniem_instalacji(tmp_path: Path) -> None:
    config = _fixture_rules(tmp_path)
    base = _empty_base(tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "narzedzie.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(odpalenia_ast_grep.ScanFailed, match="uruchom python3 tools/setup_worktree.py"):
        syntax_rules(tmp_path, base, config, ast_grep=None)


@needs_ast_grep
def test_regula_ast_grep_zglasza_dodana_linie_src_a_nie_ta_sama_linie_sprzed_zmiany(tmp_path: Path) -> None:
    config = _fixture_rules(tmp_path)
    files = (
        "src/rozliczenia/stary.py",
        "src/rozliczenia/stub.pyi",
        "src/rozliczenia/.ukryty/stary.py",
        "src/build/stary.py",
        "tests/test_stary.py",
    )
    for path in files:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("zakazane()\nx = 1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    _empty_base(tmp_path)
    _git(tmp_path, "add", "-A", "-f")
    _git(tmp_path, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "stare linie")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    assert syntax_rules(tmp_path, base, config) == []

    for path in files:
        (tmp_path / path).write_text("zakazane()\nx = 1\nzakazane()\n", encoding="utf-8")
    (tmp_path / "src" / "rozliczenia" / "nowy.py").write_text("y = 2\nzakazane()\n", encoding="utf-8")
    message = "Zamień zakazane() na dozwolone()."

    assert syntax_rules(tmp_path, base, config) == sorted(
        [
            *(odpalenia_ast_grep.Finding(path, 3, "zakazane-wywolanie", message) for path in files[:4]),
            odpalenia_ast_grep.Finding("src/rozliczenia/nowy.py", 2, "zakazane-wywolanie", message),
        ]
    )


def test_regula_ast_grep_bez_pola_files_jest_odmowa_z_poleceniem(tmp_path: Path) -> None:
    config = _fixture_rules(tmp_path)
    (tmp_path / AST_GREP_RULES / "bez-zakresu.yml").write_text(
        _FIXTURE_RULE.replace("zakazane-wywolanie", "bez-files").replace("files:\n  - src/**\n", "")
        + "---\n"
        + _FIXTURE_RULE.replace("zakazane-wywolanie", "puste-files").replace("files:\n  - src/**\n", "files: []\n"),
        encoding="utf-8",
    )

    assert ast_grep_rules_without_scope(config) == [
        f"{rule}: reguła bez pola files: obejmuje każdy plik repozytorium; dopisz files: z globami plików, w których"
        " obowiązuje (np. src/**/*.py albo .agents/skills/**/*.py), a wyjątki w ignores:"
        for rule in ("bez-files", "puste-files")
    ]


@needs_ast_grep
def test_regula_ast_grep_zglasza_dodana_linie_tylko_w_plikach_ze_swojego_pola_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reguła z ``files:`` na skryptach skilli widzi dodaną linię w ukrytym ``.agents/``, a reguła z ``files:`` na
    ``src/**`` nie widzi tej samej linii w ``tools/``; linia sprzed zmiany i plik nieśledzony z ``.gitignore`` nie są
    zgłoszone. Po jednej ścieżce na ``ast-grep scan``, więc zgłoszenia przychodzą z kilku skanów."""

    monkeypatch.setattr(odpalenia_ast_grep, "PATHS_PER_SCAN", 1)
    config = _fixture_rules(tmp_path)
    (tmp_path / AST_GREP_RULES / "skrypty-skilli.yml").write_text(
        _FIXTURE_RULE.replace("zakazane-wywolanie", "skrypty-skilli").replace("src/**", ".agents/skills/**"),
        encoding="utf-8",
    )
    files = (".agents/skills/s/scripts/stary.py", "tools/stary.py", "src/rozliczenia/stary.py")
    for path in files:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("zakazane()\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    _empty_base(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "stare linie")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path in files:
        (tmp_path / path).write_text("zakazane()\nzakazane()\n", encoding="utf-8")
    (tmp_path / ".agents/skills/s/build").mkdir()
    (tmp_path / ".agents/skills/s/build/ignorowany.py").write_text("zakazane()\n", encoding="utf-8")
    message = "Zamień zakazane() na dozwolone()."

    assert syntax_rules(tmp_path, base, config) == [
        odpalenia_ast_grep.Finding(".agents/skills/s/scripts/stary.py", 2, "skrypty-skilli", message),
        odpalenia_ast_grep.Finding("src/rozliczenia/stary.py", 2, "zakazane-wywolanie", message),
    ]


@needs_ast_grep
def test_regula_ast_grep_z_waznoscia_off_w_pliku_tez_zglasza_dodana_linie_src(tmp_path: Path) -> None:
    config = _fixture_rules(tmp_path)
    rule = tmp_path / AST_GREP_RULES / "zakazane-wywolanie.yml"
    rule.write_text(_FIXTURE_RULE.replace("severity: error", "severity: off"), encoding="utf-8")
    base = _src_sample(tmp_path, "zakazane()\n")

    assert syntax_rules(tmp_path, base, config) == [
        odpalenia_ast_grep.Finding("src/rozliczenia/probka.py", 1, "zakazane-wywolanie", "Zamień zakazane() na dozwolone().")
    ]


@needs_ast_grep
def test_plik_reguly_ast_grep_ktorego_ast_grep_nie_wczyta_jest_porazka_zapadki(tmp_path: Path) -> None:
    config = _fixture_rules(tmp_path)
    rule = tmp_path / AST_GREP_RULES / "zakazane-wywolanie.yml"
    rule.write_text(_FIXTURE_RULE + "  nieznane_pole: 1\n", encoding="utf-8")
    base = _src_sample(tmp_path, "zakazane()\n")

    with pytest.raises(odpalenia_ast_grep.ScanFailed, match="(?s)ast-grep scan zakończył się kodem 8:\n.*nieznane_pole"):
        syntax_rules(tmp_path, base, config)


@needs_ast_grep
@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\x1c", "\x0c"], ids=["u2028", "u2029", "x85", "x1c", "x0c"])
def test_znak_podzialu_splitlines_w_linii_odpalenia_nie_rozcina_rekordu_json_ast_grep(tmp_path: Path, separator: str) -> None:
    config = _fixture_rules(tmp_path)
    base = _src_sample(tmp_path, f"x = 1\ns = 'a{separator}b'; zakazane()\n")

    assert syntax_rules(tmp_path, base, config) == [
        odpalenia_ast_grep.Finding("src/rozliczenia/probka.py", 2, "zakazane-wywolanie", "Zamień zakazane() na dozwolone().")
    ]


_IN_FUNCTION = "def f() -> None:\n    "
_SHORTS = ("deadbee", "1abcdef", "12abcde", "123abcd", "1234abc", "12345ab", "123456a", "1234567a")

# Próbki reguły ``historia-w-docstringu``: „klasa: postać” → nowy plik ``src/`` i linie, które reguła zgłasza.
_PROBKI_HISTORII: Final[dict[str, tuple[str, list[int]]]] = {
    "# z cyfrą: w docstringu modułu": ('"""Moduł z #1614."""\n', [1]),
    "# z cyfrą: po nawiasie": (f'{_IN_FUNCTION}"""Wzór z (#1614)."""\n', [2]),
    "# z cyfrą: po słowie ze spacją i bez": (f'{_IN_FUNCTION}"""Wzór z issue #1614 i PR#12."""\n', [2]),
    "# z cyfrą: po nazwie repozytorium": ('class K:\n    """Od o/r#1614."""\n', [2]),
    "# z cyfrą: zgłoszenie w repozytorium spoza projektu": ('"""Zob. microsoft/playwright#43545."""\n', [1]),
    "adres github.com: z https i /issues/": ('"""Moduł z https://github.com/o/r/issues/1614."""\n', [1]),
    "adres github.com: bez schematu": (f'{_IN_FUNCTION}"""Zob. github.com/o/r/pull/77."""\n', [2]),
    "adres github.com: wielkie litery": (f'{_IN_FUNCTION}"""Zob. HTTPS://GitHub.COM/o/r/pull/77."""\n', [2]),
    "adres github.com: subdomena gist.": (f'{_IN_FUNCTION}"""Zob. https://gist.github.com/o/1."""\n', [2]),
    "adres github.com: git@ z dwukropkiem": (f'{_IN_FUNCTION}"""Zob. git@github.com:o/r."""\n', [2]),
    "adres github.com: kropka na końcu zdania": (f'{_IN_FUNCTION}"""Repozytorium jest na github.com."""\n', [2]),
    "skrót commitu: wielkie litery": (f'{_IN_FUNCTION}"""Naprawione w 2FF78B6B3."""\n', [2]),
    "skrót commitu: pełny SHA": (f'{_IN_FUNCTION}"""Naprawione w 8d3f7b66dfe85c4f3e0fae27b05a66340c076deb."""\n', [2]),
    **{
        f"skrót commitu: pierwsza litera na pozycji {len(short) - len(short.lstrip('0123456789')) + 1} ({short})": (
            f'{_IN_FUNCTION}"""Naprawione w {short}."""\n',
            [2],
        )
        for short in _SHORTS
    },
    "miejsce docstringu: po komentarzu": ('#!/usr/bin/env python3\n"""Moduł z #1614."""\n', [2]),
    "miejsce docstringu: wieloliniowy, linia węzła to pierwsza": (f'{_IN_FUNCTION}"""Opis.\n\n    Wzór z #808.\n    """\n', [2]),
    "tekst źródła: # i cyfra w jednym z dwóch sklejonych literałów": (f'{_IN_FUNCTION}"Część z #1 " "i dalej"\n', [2]),
    "miejsce docstringu: napis r": (f"{_IN_FUNCTION}r'''Z a1b2c3d.'''\n", [2]),
    "miejsce docstringu: napis b": (f'{_IN_FUNCTION}b"""Z #1614."""\n', [2]),
    "miejsce docstringu: f-string": ('def f(x: int) -> None:\n    f"""Z #1614 i {x}."""\n', [2]),
    "miejsce docstringu: metoda asynchroniczna z dekoratorem": (
        'class K:\n    @staticmethod\n    async def f() -> None:\n        """Z #1614."""\n',
        [4],
    ),
    "miejsce docstringu: funkcja zagnieżdżona": (f'{_IN_FUNCTION}def g() -> None:\n        """Z #1614."""\n', [3]),
    "bez postaci: liczby, data, telefon, słowa hex do 6 znaków i literał 0x": (
        '"""Moduł bez historii: 600 s, 2026-11-14, telefon 48600123456, słowa added i deadbe, 0xdeadbeef1."""\n',
        [],
    ),
    "bez postaci: # przed literą": ('"""Kolor #fff, kotwica #L12 i sekcja #opis."""\n', []),
    "bez postaci: domena inna niż github.com": (
        f'{_IN_FUNCTION}"""Adresy notgithub.com, my-github.com, github.com.pl, github.company i githubusercontent.com."""\n',
        [],
    ),
    "nie docstring: napis przypisany": ('w = "#123 w napisie, który nie jest docstringiem"\n', []),
    "nie docstring: drugi napis funkcji": (
        'def f() -> str:\n    s = "zwykły napis"\n    """Drugi napis z #9 nie jest docstringiem."""\n    return s\n',
        [],
    ),
    "nie docstring: napis w bloku if": ('if True:\n    """Napis z #9 w bloku if nie jest docstringiem."""\n', []),
}


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_HISTORII.values(), ids=_PROBKI_HISTORII.keys())
def test_historia_w_docstringu_zglasza_docstring_z_numerem_adresem_github_albo_skrotem_commitu(
    tmp_path: Path, text: str, lines: list[int]
) -> None:
    base = _src_sample(tmp_path, text)

    assert [finding.line for finding in syntax_rules(tmp_path, base) if finding.rule == "historia-w-docstringu"] == lines


@needs_ast_grep
def test_historia_w_docstringu_czyta_pliki_py_pyi_i_py3_a_pomija_pyw_i_plik_bez_rozszerzenia(tmp_path: Path) -> None:
    """Granica zbioru plików reguły, ta sama co ``komentarz-w-src``: ``files:`` ma globy ``.py``, ``.pyi`` i ``.py3``,
    więc ``.pyw`` i skrypt Pythona bez rozszerzenia przechodzą z docstringiem z „#” i cyfrą; gdy reguła zacznie je
    czytać, ten test każe przesunąć granicę."""

    base = _empty_base(tmp_path)
    names = ("a.py", "pakiet/b.py", "c.pyi", "d.py3", "e.pyw", "skrypt")
    for name in names:
        (tmp_path / "src" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / name).write_text('"""Wzór z #1614."""\n', encoding="utf-8")

    assert [finding.path for finding in syntax_rules(tmp_path, base) if finding.rule == "historia-w-docstringu"] == sorted(
        f"src/{name}" for name in names[:4]
    )


# Znane luki reguły ``historia-w-docstringu`` (tests/fixtures/znane_luki.py): klasa mechanizmu, który ją przepuszcza:
# postać → nowy plik ``src/`` z docstringiem z historią, który przechodzi przez regułę i ruff z konfiguracją ``src/``.
ZNANE_LUKI_HISTORII: Final = {
    "numer bez # przed cyfrą: PR 12": '"""Wzór z PR 12."""\n',
    "numer bez # przed cyfrą: issue 1614": '"""Wzór z issue 1614."""\n',
    "numer bez # przed cyfrą: PRy 12": '"""Wzór z PRy 12."""\n',
    "numer bez # przed cyfrą: PRów 12": '"""Wzór z PRów 12."""\n',
    "numer bez # przed cyfrą: GH-1614": '"""Wzór z GH-1614."""\n',
    "numer bez # przed cyfrą: odstęp po #": '"""Wzór z # 1614."""\n',
    "ścieżka bez domeny github.com: o/r/issues/1614": '"""Zob. o/r/issues/1614."""\n',
    "ścieżka bez domeny github.com: /pull/77": '"""Zob. /pull/77."""\n',
    "skrót bez litery a-f: same cyfry": '"""Naprawione w 4801234."""\n',
    "skrót krótszy niż 7 znaków: abc123": '"""Naprawione w abc123."""\n',
    "wartość napisu inna niż tekst źródła: # i cyfra rozcięte między sklejone literały": (
        'def f() -> None:\n    "Wzór z #" "1614."\n'
    ),
    "wartość napisu inna niż tekst źródła: # zapisany ucieczką": '"""Wzór z \\x231614."""\n',
    "wartość napisu inna niż tekst źródła: # i cyfra rozcięte backslashem i nową linią": '"""Wzór z #\\\n1614."""\n',
    "wartość napisu inna niż tekst źródła: # wstawiony polem f-stringu": (
        'def f() -> None:\n    f"""Wzór z {"#"}1614."""\n'
    ),
    "historia bez numeru, adresu i skrótu: przegląd i data": '"""Tak od przeglądu z 14.11.2026, po drugim FAIL."""\n',
    "historia bez numeru, adresu i skrótu: numer Wydania": '"""Pliki Wydań starszych niż v0.5.0 nie mają stopnia."""\n',
    "odnośnik do zgłoszenia spoza github.com bez # przed cyfrą: crbug.com/572515601": '"""Zob. crbug.com/572515601."""\n',
    "napis, który nie jest docstringiem: komunikat wyjątku": (
        'def f() -> None:\n    message = "Logi bez maski (#936)."\n    raise ValueError(message)\n'
    ),
    "napis, który nie jest całym pierwszym wyrażeniem bloku: w nawiasach": (
        '"""Moduł."""\n\n\ndef f() -> None:\n    ("""Z #1614.""")\n'
    ),
    "napis, który nie jest całym pierwszym wyrażeniem bloku: pod przypisaniem atrybutu": (
        '"""Moduł."""\n\nLIMIT = 5\n"""Limit z #1614."""\n'
    ),
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_reguly_historia_w_docstringu_przechodza_przez_regule_i_ruff(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (tmp_path / "src" / "rozliczenia").mkdir(parents=True)
    pliki = zapisz(ZNANE_LUKI_HISTORII, tmp_path / "src" / "rozliczenia")
    zgloszenia = ruff(pliki, sonda=ROOT / "src" / "rozliczenia" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(
        zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_historia_w_docstringu_przechodza_przez_regule_i_ruff"
    )


# Reguła ``przegladarka-bez-launch-options`` (#1871): odwołanie do metody startu przeglądarki Playwrighta poza wywołaniem
# z argumentami jej właściciela.
_PRZEGLADARKA = "przegladarka-bez-launch-options"


def _start(text: str, prefix: str = "", signature: str = "p: Playwright") -> str:
    """Nowy plik ``src/`` z ``prefix`` i funkcją, której ciało to ``text``: pierwsza linia ciała to linia 7 bez ``prefix``."""

    return (
        f"{prefix}from playwright.sync_api import Playwright\n\nfrom rozliczenia.efenix_browser import launch_options\n\n\n"
        f"def start({signature}) -> object:\n    {text}\n"
    )


_IMPORT_EXCEL = "import excel\n"
# Tekst nowego pliku ``src/`` → linie, które reguła zgłasza. Odwołanie do metody ``launch`` albo
# ``launch_persistent_context`` w każdym miejscu drzewa (wywołanie, argument, przypisanie, dekorator, ``partial``,
# ``to_thread``, atrybut odwołania) jest zgłoszone, chyba że to wołana funkcja wywołania z ``**launch_options(…)``, albo
# obiekt to nazwa z importu w tym pliku albo parametr z typem ``ModuleType``. Pełny korpus par gramatyki (rodzaj węzła,
# pole) z miejscem na węzeł ``attribute`` stoi w komentarzu PR #1877.
_PROBKI_PRZEGLADARKI: Final[dict[str, tuple[str, list[int]]]] = {
    "bez argumentów": (_start("return p.chromium.launch()"), [7]),
    "argument nazwany": (_start("return p.chromium.launch(headless=False)"), [7]),
    "inna przeglądarka": (_start("return p.firefox.launch()"), [7]),
    "kontekst z profilem": (_start('return p.chromium.launch_persistent_context("profil")'), [7]),
    "** słownika": (_start('return p.chromium.launch(**{"args": []})'), [7]),
    "** innego wywołania": (_start("return p.chromium.launch(**dict(args=[]))"), [7]),
    "** nazwy launch_options bez wywołania": (_start("return p.chromium.launch(**launch_options)"), [7]),
    "** wywołania o nazwie kończącej się na launch_options": (_start("return p.chromium.launch(**my_launch_options(p))"), [7]),
    "** launch_options w nawiasach": (_start("return p.chromium.launch(**(launch_options(p)))"), [7]),
    "launch_options w argumentach wywołania, które metodę dostaje": (
        _start("return g(p.chromium.launch, **launch_options(p))"),
        [7],
    ),
    "metoda w nawiasach": (_start("return (p.chromium.launch)()"), [7]),
    "obiekt w nawiasach": (_start("return (p.chromium).launch()"), [7]),
    "obiekt przez nazwę pośrednią": (_start("browser_type = p.chromium\n    return browser_type.launch()"), [8]),
    "wywołanie w kilku liniach": (_start("return p.chromium.launch(\n        headless=True,\n    )"), [7]),
    "metoda w partial bez argumentów": (_start("return functools.partial(p.chromium.launch)()", "import functools\n"), [8]),
    "metoda w partial z argumentem": (_start("return functools.partial(p.chromium.launch, headless=True)()", "import functools\n"), [8]),
    "metoda w asyncio.to_thread": (_start("return asyncio.to_thread(p.chromium.launch, headless=True)", "import asyncio\n"), [8]),
    "metoda zapisana pod nazwą": (_start("launch = p.chromium.launch\n    return launch()"), [7]),
    "metoda przez __call__": (_start("return p.chromium.launch.__call__()"), [7]),
    "metoda jako dekorator": (_start("@p.chromium.launch\n    def g() -> None:\n        pass\n\n    return g"), [7]),
    "obiekt o nazwie modułu bez importu": (_start("excel = p.chromium\n    return excel.launch()"), [8]),
    "obiekt o nazwie ścieżki modułu z from": (_start("return excel.launch()", "from excel import zgoda\n"), [8]),
    "obiekt o nazwie dalszej części ścieżki importu": (_start("return excel.launch()", "import narzedzia.excel\n"), [8]),
    "obiekt o nazwie modułu sprzed aliasu": (_start("return excel.launch()", "import excel as xl\n"), [8]),
    "obiekt o nazwie modułu sprzed aliasu w from": (_start("return excel.launch()", "from narzedzia import excel as xl\n"), [8]),
    "klasa przeglądarki z importu playwright": (
        _start("return BrowserType.launch(p.chromium)", "from playwright.sync_api import BrowserType\n"),
        [8],
    ),
    "moduł playwright z importu": (_start("return playwright.launch()", "import playwright\n"), [8]),
    "moduł playwright pod aliasem": (_start("return api.launch()", "import playwright.sync_api as api\n"), [8]),
    "moduł o nazwie playwright z innego pakietu": (_start("return playwright.launch()", "from narzedzia import playwright\n"), []),
    "klasa przeglądarki z importu playwright.async_api": (
        _start("return BrowserType.launch(p.chromium)", "from playwright.async_api import BrowserType\n"),
        [8],
    ),
    "moduł o nazwie zaczynającej się od playwright": (_start("return playwright_stealth.launch()", "import playwright_stealth\n"), []),
    "moduł z from pakietu o nazwie zaczynającej się od playwright": (
        _start("return stealth.launch()", "from playwright_stealth import stealth\n"),
        [],
    ),
    "moduł z importu ścieżki z playwright w środku": (_start("return narzedzia.launch()", "import narzedzia.playwright\n"), []),
    "moduł z from ścieżki z playwright w środku": (_start("return excel.launch()", "from narzedzia.playwright import excel\n"), []),
    "** wywołania o nazwie zaczynającej się od launch_options": (_start("return p.chromium.launch(**launch_options_x(p))"), [7]),
    "parametr typu o nazwie zaczynającej się od ModuleType": (_start("return excel.launch()", signature="excel: ModuleTypeX"), [7]),
    "parametr bez typu ModuleType": (_start("return excel.launch()", signature="excel: object"), [7]),
    "parametr typu o nazwie kończącej się na ModuleType": (_start("return excel.launch()", signature="excel: MyModuleType"), [7]),
    "inny parametr z typem ModuleType": (_start("return p.chromium.launch()", "from types import ModuleType\n", "p: Playwright, m: ModuleType"), [8]),
    "z launch_options": (_start("return p.chromium.launch(**launch_options(p))"), []),
    "z launch_options i innymi argumentami": (_start('return p.chromium.launch(headless=True, **launch_options(p, arguments=["--x"]))'), []),
    "z launch_options modułu": (_start("return p.chromium.launch(**efenix_browser.launch_options(p))"), []),
    "kontekst z profilem i launch_options": (_start('return p.chromium.launch_persistent_context("profil", **launch_options(p))'), []),
    "metoda w nawiasach z launch_options": (_start("return (p.chromium.launch)(**launch_options(p))"), []),
    "connect_over_cdp": (_start('return p.chromium.connect_over_cdp("http://127.0.0.1:9222")'), []),
    "metoda z launch w środku nazwy": (_start("return p.relaunch()"), []),
    "metoda z launch na początku nazwy": (_start("return p.chromium.launched()"), []),
    "funkcja modułu z importu": (_start("return excel.launch(timeout=20)", _IMPORT_EXCEL), []),
    "funkcja modułu z importu w nawiasach": (_start("return (excel.launch)()", _IMPORT_EXCEL), []),
    "funkcja modułu z importu przekazana dalej": (_start("return retry(excel.launch)()", _IMPORT_EXCEL), []),
    "funkcja modułu z importu w funkcji": (_start("import excel\n\n    return excel.launch()"), []),
    "funkcja modułu z importu kilku modułów": (_start("return excel.launch()", "import os, excel\n"), []),
    "funkcja modułu pod aliasem": (_start("return xl.launch()", "import excel as xl\n"), []),
    "funkcja modułu z from i kilku nazw": (
        _start("return restart_guardian.launch(a, b)", "from rozliczenia.centrum import launcher, restart_guardian\n"),
        [],
    ),
    "funkcja modułu z from pod aliasem": (_start("return excel.launch()", "from narzedzia import zgoda, xl as excel\n"), []),
    "funkcja modułu z parametru ModuleType": (_start("return excel.launch()", signature="excel: ModuleType"), []),
    "funkcja modułu z parametru types.ModuleType": (_start("return excel.launch()", signature="excel: types.ModuleType"), []),
}


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_PRZEGLADARKI.values(), ids=_PROBKI_PRZEGLADARKI.keys())
def test_przegladarka_bez_launch_options_zglasza_odwolanie_do_startu_poza_wywolaniem_z_argumentami_wlasciciela(
    tmp_path: Path, text: str, lines: list[int]
) -> None:
    base = _src_sample(tmp_path, text)

    assert [finding.line for finding in syntax_rules(tmp_path, base) if finding.rule == _PRZEGLADARKA] == lines


# Pliki reguły ``przegladarka-bez-launch-options`` jako części ścieżki, bo napis ścieżki w pliku testu jest zależnością
# testu w grafie wpływu zmiany (``tools/lib/wplyw_zmiany.py``): zakres ``files:`` i dwaj właściciele z ``ignores:``.
_ZAKRES_PRZEGLADARKI: Final = (
    ("src", "rozliczenia", "okno.py"),
    ("tools", "narzedzie.py"),
    ("tests", "test_okna.py"),
    (".agents", "skills", "verify-x", "scripts", "naped.py"),
)
_WLASCICIELE_PRZEGLADARKI: Final = (
    ("src", "rozliczenia", "efenix_browser.py"),
    ("tests", "fixtures", "przegladarka.py"),
    ("frontend", "skrypt.py"),
)


@needs_ast_grep
def test_przegladarka_bez_launch_options_czyta_src_tools_tests_i_skrypty_skilli_poza_wlascicielami(tmp_path: Path) -> None:
    base = _empty_base(tmp_path)
    for parts in (*_ZAKRES_PRZEGLADARKI, *_WLASCICIELE_PRZEGLADARKI):
        tmp_path.joinpath(*parts).parent.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(*parts).write_text("def start(p: object) -> object:\n    return p.chromium.launch()\n", encoding="utf-8")

    assert sorted(finding.path for finding in syntax_rules(tmp_path, base) if finding.rule == _PRZEGLADARKA) == sorted(
        "/".join(parts) for parts in _ZAKRES_PRZEGLADARKI
    )


# Prawo właściciela reguły ``przegladarka-bez-launch-options`` (``ignores:``): plik → funkcja → liczba odwołań do metody
# startu bez ``**launch_options(…)`` w tym samym wywołaniu. Reguła zwalnia cały plik, więc ta tabela trzyma resztę
# zakazu: plik właściciela poza zwolnieniem zgłasza dokładnie tyle w tych funkcjach. Ścieżka jako części, jak
# w ``_ZAKRES_PRZEGLADARKI``.
WLASCICIELE_PRZEGLADARKI: Final[dict[tuple[str, ...], dict[str, int]]] = {
    ("src", "rozliczenia", "efenix_browser.py"): {"_playwright_disabling": 1, "chrome": 1},
    ("tests", "fixtures", "przegladarka.py"): {"plain_chromium": 1},
}


def _owner_starts(root: Path, owners: list[tuple[str, ...]], tmp_path: Path) -> dict[tuple[str, ...], dict[str, int]]:
    """Plik właściciela z ``owners`` w drzewie ``root`` → funkcja → liczba odwołań, które reguła
    ``przegladarka-bez-launch-options`` zgłasza w nim poza zwolnieniem ``ignores:``. Kopia reguły leży w ``tmp_path``:
    ast-grep czyta globy ``files:`` względem jej katalogu, gdy plik leży pod nim, więc dla drzewa w ``tmp_path``
    katalog kopii to sam ``root``."""

    import ast

    import yaml

    rule = yaml.safe_load((ROOT / AST_GREP_RULES / f"{_PRZEGLADARKA}.yml").read_text(encoding="utf-8"))
    rule.pop("ignores")
    unexempted = tmp_path / "bez-ignores.yml"
    unexempted.write_text(yaml.safe_dump(rule, allow_unicode=True), encoding="utf-8")
    scan = subprocess.run(
        [str(AST_GREP), "scan", "--rule", str(unexempted), "--json=stream", "--", *("/".join(parts) for parts in owners)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    found: dict[tuple[str, ...], dict[str, int]] = {parts: {} for parts in owners}
    for match in odpalenia_ast_grep.json_stream(scan.stdout):
        parts = tuple(Path(match["file"]).parts)
        line = match["range"]["start"]["line"] + 1
        tree = ast.parse((root.joinpath(*parts)).read_text(encoding="utf-8"))
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= line <= (node.end_lineno or 0)
        ]
        name = max(functions, key=lambda node: node.lineno).name if functions else "<moduł>"
        found[parts][name] = found[parts].get(name, 0) + 1
    return found


@needs_ast_grep
def test_wlasciciel_przegladarki_startuje_bez_launch_options_tylko_w_funkcjach_z_tabeli_wlascicieli(tmp_path: Path) -> None:
    import yaml

    rule = yaml.safe_load((ROOT / AST_GREP_RULES / f"{_PRZEGLADARKA}.yml").read_text(encoding="utf-8"))
    assert sorted(rule["ignores"]) == sorted("/".join(parts) for parts in WLASCICIELE_PRZEGLADARKI)

    found = _owner_starts(ROOT, list(WLASCICIELE_PRZEGLADARKI), tmp_path)

    assert found == WLASCICIELE_PRZEGLADARKI, (
        "goły start przeglądarki w pliku z ignores: reguły przegladarka-bez-launch-options stoi tylko w funkcjach z "
        "WLASCICIELE_PRZEGLADARKI tyle razy, ile mówi tabela: podaj **launch_options(playwright) albo zmień tabelę"
    )


# Znane luki tabeli ``WLASCICIELE_PRZEGLADARKI`` (tests/fixtures/znane_luki.py): „klasa: postać” → plik właściciela
# z ``ignores:`` i jego tekst, którego start nie niesie argumentów, które ma nieść, a który mimo to przechodzi tabelę, bo
# ta liczy starty na funkcję. Każda próbka mówi, który test tę postać łapie.
_EFENIX_BROWSER: Final = ("src", "rozliczenia", "efenix_browser.py")
_PRZEGLADARKA_TESTOW: Final = ("tests", "fixtures", "przegladarka.py")
_SONDA = 'def _playwright_disabling(playwright: Playwright) -> object:\n    return playwright.chromium.launch(headless=True{})\n\n\n'
_KONTEKST = 'def chrome(playwright: Playwright, profile: str) -> object:\n    return playwright.chromium.launch_persistent_context(profile{})\n'
ZNANE_LUKI_WLASCICIELI_PRZEGLADARKI: Final[dict[str, tuple[tuple[str, ...], str]]] = {
    "tabela liczy starty, nie ich argumenty: kontekst okna efenix bez **options (łapie "
    "tests/test_centrum_logi_uruchomienia.py::test_okno_efenix_z_centrum_nie_losuje_portu_polaczenia_i_ma_wylaczone_funkcje_playwrighta)": (
        _EFENIX_BROWSER,
        "from playwright.sync_api import Playwright\n\n\n"
        + _SONDA.format(', args=["--enable-automation"]')
        + _KONTEKST.format(", headless=True"),
    ),
    "tabela liczy starty, nie ich argumenty: sonda Playwrighta bez --enable-automation (łapie "
    "tests/test_wycena_efenix.py::test_argumenty_okna_efenix_nie_zostawiaja_otwartej_przegladarki_z_ktorej_wziely_liste_playwrighta)": (
        _EFENIX_BROWSER,
        "from playwright.sync_api import Playwright\n\n\n"
        + _SONDA.format(', ignore_default_args=["--enable-automation"]')
        + _KONTEKST.format(", **options"),
    ),
    "tabela liczy starty, nie ich argumenty: wzorzec bez --enable-automation (łapie "
    "tests/test_centrum_logi_uruchomienia.py::test_okno_efenix_z_centrum_nie_losuje_portu_polaczenia_i_ma_wylaczone_funkcje_playwrighta)": (
        _PRZEGLADARKA_TESTOW,
        "from playwright.sync_api import Playwright\n\n\n"
        "def plain_chromium(playwright: Playwright) -> object:\n    return playwright.chromium.launch(args=[])\n",
    ),
}


@needs_ast_grep
def test_znane_luki_tabeli_wlascicieli_przegladarki_przechodza_przez_tabele(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki

    zgloszenia: dict[str, list[str]] = {}
    for number, (opis, (parts, text)) in enumerate(ZNANE_LUKI_WLASCICIELI_PRZEGLADARKI.items()):
        root = tmp_path / str(number)
        root.joinpath(*parts).parent.mkdir(parents=True)
        root.joinpath(*parts).write_text(text, encoding="utf-8")
        found = _owner_starts(root, [parts], root)
        zgloszenia[opis] = [] if found[parts] == WLASCICIELE_PRZEGLADARKI[parts] else [f"tabela: {found[parts]}"]

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_tabeli_wlascicieli_przegladarki_przechodza_przez_tabele")


# Znane luki reguły ``przegladarka-bez-launch-options`` (tests/fixtures/znane_luki.py): „klasa: postać” → nowy plik
# ``src/`` ze startem przeglądarki bez argumentów właściciela, który przechodzi przez regułę i ruff.
_LUKA_PRZEGLADARKI = "from playwright.sync_api import Browser, Playwright\n\n\ndef start(p: Playwright) -> Browser:\n"
ZNANE_LUKI_PRZEGLADARKI: Final = {
    "drzewo nie zna nazwy z napisu: metoda po nazwie z getattr": (
        f'{_LUKA_PRZEGLADARKI}    name = "launch"\n    return getattr(p.chromium, name)()\n'
    ),
    "drzewo nie czyta napisów: start w skrypcie dla procesu potomnego": (
        'SKRYPT = "from playwright.sync_api import sync_playwright\\nsync_playwright().start().chromium.launch()\\n"\n'
    ),
    "zna tylko API Playwrighta: przeglądarka uruchomiona jako proces": (
        "import subprocess\n\n\ndef chrome(binary: str) -> None:\n    subprocess.run([binary, \"--headless=new\", \"about:blank\"], check=True)\n"
    ),
    "zna tylko nazwę launch_options: funkcja innego obiektu o tej nazwie": (
        "from types import SimpleNamespace\n\n"
        f"{_LUKA_PRZEGLADARKI}    helpers = SimpleNamespace(launch_options=lambda playwright: {{}})\n"
        "    return p.chromium.launch(**helpers.launch_options(p))\n"
    ),
    "nazwa z importu to dla reguły moduł: obiekt przeglądarki zaimportowany pod nazwą": (
        "from playwright.sync_api import Browser\n\nfrom narzedzia.przegladarki import chromium\n\n\n"
        "def start() -> Browser:\n    return chromium.launch()\n"
    ),
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_przegladarki_bez_launch_options_przechodza_przez_regule_i_ruff(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (tmp_path / "src" / "rozliczenia").mkdir(parents=True)
    pliki = zapisz(ZNANE_LUKI_PRZEGLADARKI, tmp_path / "src" / "rozliczenia")
    zgloszenia = ruff(pliki, sonda=ROOT / "src" / "rozliczenia" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(
        zgloszenia, "tests/test_zapadki.py::test_znane_luki_przegladarki_bez_launch_options_przechodza_przez_regule_i_ruff"
    )


@needs_ast_grep
@pytest.mark.parametrize(
    ("text", "rules"),
    [
        (f"x = 1  # {_IGNORE}\n", ["no-suppress-all", "unused-suppression"]),
        (f"x = 1  # {_IGNORE}: zakazane-wywolanie\n", ["unused-suppression"]),
        (f"zakazane()  # {_IGNORE}: zakazane-wywolanie\n", []),
    ],
)
def test_dyrektywa_ast_grep_ignore_przechodzi_tylko_z_nazwa_reguly_ktora_wylacza(
    tmp_path: Path, text: str, rules: list[str]
) -> None:
    config = _fixture_rules(tmp_path)
    base = _src_sample(tmp_path, text)

    assert syntax_rules(tmp_path, base, config) == [
        odpalenia_ast_grep.Finding("src/rozliczenia/probka.py", 1, rule, odpalenia_ast_grep.BUILTIN_MESSAGES[rule]) for rule in rules
    ]


# Katalog Centrum w zakresie ``files:`` reguły ``regula-w-trasie`` jako części ścieżki, bo napis ścieżki w pliku
# testu jest zależnością testu w grafie wpływu zmiany (``tools/lib/wplyw_zmiany.py``).
_CENTRUM: Final = ("src", "rozliczenia", "centrum")
_ODMOWA = "from rozliczenia.centrum import refusal\n\n\ndef changed(problem: object) -> None:\n"
# Moduł w zakresie reguły: woła metodę zapisu właściciela Ustawień, bez żadnej trasy.
_ZAPIS_USTAWIEN = "\n\ndef apply(settings: object) -> None:\n    settings.change()\n"
_WLASCICIEL = "from rozliczenia.centrum.settings.owner import CentrumSettings\n"


def _modul_zapisu(text: str) -> str:
    return f"{text}{_ZAPIS_USTAWIEN}"


def _moduly_centrum(root: Path, probki: dict[str, str]) -> dict[str, Path]:
    """Nowy moduł każdej próbki w katalogu Centrum ``root``, bez ``router`` w nazwie."""

    folder = root.joinpath(*_CENTRUM)
    folder.mkdir(parents=True, exist_ok=True)
    pliki = {opis: folder / f"probka_{numer}.py" for numer, opis in enumerate(probki)}
    for opis, plik in pliki.items():
        plik.write_text(probki[opis], encoding="utf-8")
    return pliki


@needs_ast_grep
@pytest.mark.parametrize(
    ("modul", "naglowek", "zapis", "lines"),
    [
        (
            "quantity_differences.py",
            "from fastapi import APIRouter\n",
            "\n\ndef add_worker_routes(router: APIRouter, settings: object) -> None:\n    settings.change()\n",
            [6, 8],
        ),
        (
            "app.py",
            "from fastapi import FastAPI\n",
            '\n\ndef add_delete(app: FastAPI, settings: object) -> None:\n    @app.delete("/api/settings/workers/{name}")\n'
            "    def delete_worker(name: str) -> None:\n        settings.change(name)\n",
            [6, 8],
        ),
        (
            "probka.py",
            "import fastapi\n",
            '\n\ndef add_worker_routes(router: "fastapi.APIRouter", settings: object) -> None:\n    settings.change_with_used_keys()\n',
            [6, 8],
        ),
        ("probka.py", _WLASCICIEL, '\n\ndef undo(settings: CentrumSettings) -> None:\n    settings.undo("row")\n', [6, 8]),
        ("probka.py", _WLASCICIEL, "\n\ndef release(settings: CentrumSettings) -> None:\n    settings.apply_release_changes()\n", [6, 8]),
        ("probka.py", _WLASCICIEL, '\n\ndef apply(settings: CentrumSettings) -> None:\n    getattr(settings, "change")()\n', [6, 8]),
        ("probka.py", _WLASCICIEL, '\n\ndef apply(settings: CentrumSettings) -> None:\n    getattr(settings, r"change")()\n', [6, 8]),
        ("probka.py", _WLASCICIEL, "\n\ndef apply(settings: CentrumSettings) -> None:\n    getattr(settings, '''change''')()\n", [6, 8]),
        ("probka.py", _WLASCICIEL, "\n\ndef apply(settings: CentrumSettings) -> None:\n    settings._dad_change()\n", [6, 8]),
        ("probka.py", _WLASCICIEL, "\n\ndef apply(settings: CentrumSettings) -> None:\n    write = settings._checked\n", [6, 8]),
        (
            "probka.py",
            "from collections.abc import Callable\n",
            "\n\ndef apply(settings: object, run: Callable[[object], None]) -> None:\n    run(settings.change)\n",
            [6, 8],
        ),
        ("settings/history.py", _WLASCICIEL, "\n\ndef apply(settings: CentrumSettings) -> None:\n    settings.change()\n", [6, 8]),
        ("settings/owner.py", _WLASCICIEL, "\n\ndef apply(settings: CentrumSettings) -> None:\n    settings.change()\n", []),
        ("probka.py", "from fastapi import APIRouter\n", "\n\ndef runs_router() -> APIRouter:\n    return APIRouter()\n", []),
        ("probka.py", "", '\n\ndef apply(settings: object) -> None:\n    """Zapis: settings.change w trasie."""\n', []),
    ],
)
def test_regula_w_trasie_obejmuje_kazdy_modul_z_zapisem_wlasciciela_ustawien_poza_wlascicielem(
    tmp_path: Path, modul: str, naglowek: str, zapis: str, lines: list[int]
) -> None:
    """Zakres reguły wynika z własności, nie ze składni trasy: sondy #1727 r1 W1 (``quantity_differences.py`` bez
    ``router`` w nazwie), r2 W1 (router z parametru) i r3 W1 (``@app.delete`` na ``FastAPI`` w ``app.py``, adnotacja
    napisem ``"fastapi.APIRouter"``), sondy r4 W1 (``getattr`` z nazwą metody zapisu w literale, prywatna metoda
    właściciela), sondy r5 W2 (literał z przedrostkiem ``r`` i w potrójnym cudzysłowie) i moduł bez trasy, który nazywa którąkolwiek metodę zapisu właściciela, także przekazaną bez
    wywołania, są zgłoszone; ten sam kod w module właściciela ``settings/owner.py`` (prawo właściciela w ``ignores:``),
    w module bez zapisu Ustawień i w module, którego napis tylko wspomina metodę zapisu, nie."""

    base = _empty_base(tmp_path)
    plik = tmp_path.joinpath(*_CENTRUM, *modul.split("/"))
    plik.parent.mkdir(parents=True)
    plik.write_text(
        f'{naglowek}{_ODMOWA}    _ensure_not_in_periods(problem)\n    if problem:\n        raise refusal.worker_kept(problem, "worker")\n{zapis}',
        encoding="utf-8",
    )

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(line, "regula-w-trasie") for line in lines]


@needs_ast_grep
@pytest.mark.parametrize(
    ("text", "lines"),
    [
        (f"{_ODMOWA}    _ensure_not_in_periods(problem)\n", [5]),
        (f"{_ODMOWA}    checks._ensure_not_in_periods(problem)\n", [5]),
        (f"{_ODMOWA}    needed = needed_by(problem)\n    if needed is not None:\n        raise refusal.setting_refused(needed)\n", [7]),
        (
            f'{_ODMOWA}    match problem:\n        case "delete":\n            if problem:\n'
            '                raise refusal.worker_kept(problem, "worker")\n',
            [8],
        ),
        (f'{_ODMOWA}    match problem:\n        case "delete" if problem:\n            raise refusal.worker_kept(problem, "worker")\n', [7]),
        (f'{_ODMOWA}    if problem:\n        return\n    else:\n        raise refusal.worker_kept(problem, "worker")\n', [8]),
        (f"{_ODMOWA}    match problem:\n        case Refused(problem=refused) if refused:\n            raise refusal.setting_refused(refused)\n", [7]),
        (f"{_ODMOWA}    match problem:\n        case Saved() | InPeriods():\n            raise refusal.setting_refused(problem)\n", [7]),
        (f'{_ODMOWA}    match problem:\n        case InPeriods():\n            raise refusal.worker_kept(problem, "worker")\n', [7]),
        (
            f"{_ODMOWA}    match problem:\n        case Refused(problem=refused):\n            if refused:\n"
            "                raise refusal.setting_refused(refused)\n",
            [8],
        ),
        (f'{_ODMOWA}    if isinstance(problem, InPeriods):\n        raise refusal.worker_kept(problem, "worker")\n', [6]),
        (f"{_ODMOWA}    if isinstance(problem, FieldProblem) and problem:\n        raise refusal.setting_refused(problem)\n", [6]),
        (f"{_ODMOWA}    if isinstance(problem, FieldProblem):\n        return\n    else:\n        raise refusal.setting_refused(problem)\n", [8]),
        (f"{_ODMOWA}    if problem is None:\n        for part in str(problem):\n            raise refusal.setting_refused(part)\n", [7]),
        (
            f"{_ODMOWA}    if isinstance(problem, NotUndoable):\n"
            "        raise refusal.settings_change_not_undoable() if problem else refusal.settings_not_saved()\n",
            [6, 6],
        ),
        (f"{_ODMOWA}    try:\n        str(problem)\n    except ValueError as error:\n        raise refusal.setting_refused(problem) from error\n", [8]),
        (f"{_ODMOWA}    raise refusal.setting_refused(problem)\n", [5]),
        (f"{_ODMOWA}    return refusal.setting_refused(problem)\n", [5]),
        (f"{_ODMOWA}    match problem:\n        case Refused(problem=refused):\n            raise refusal.setting_refused(refused)\n", []),
        (
            f"{_ODMOWA}    match problem:\n        case owner.KeptInPeriods(presence=presence, what=what):\n"
            "            raise refusal.worker_kept(presence, what)\n",
            [],
        ),
        (f"{_ODMOWA}    if isinstance(problem, FieldProblem):\n        raise refusal.setting_refused(problem)\n", []),
        (f"{_ODMOWA}    if isinstance(problem, NotSaved):\n        raise refusal.settings_not_saved()\n", []),
        (f'{_ODMOWA}    if problem:\n        if problem.found is None:\n            raise refusal.worker_kept(problem, "worker")\n', [7]),
        (f"{_ODMOWA}    with problem:\n        if problem is None:\n            raise refusal.register_not_chosen()\n", [7]),
        (
            f'{_ODMOWA}    match problem:\n        case "delete":\n            if isinstance(problem, FieldProblem):\n'
            "                raise refusal.setting_refused(problem)\n",
            [8],
        ),
        (f"{_ODMOWA}    if problem is None:\n        raise refusal.register_not_chosen()\n", []),
        (
            f"{_ODMOWA}    match problem:\n        case Refused(problem=refused):\n            if isinstance(refused, FieldProblem):\n"
            "                raise refusal.setting_refused(refused)\n",
            [],
        ),
        (f"{_ODMOWA}    if problem:\n        raise refusal.device_component_unknown()\n", []),
    ],
)
def test_regula_w_trasie_zglasza_odmowe_trasy_poza_kazdym_dozwolonym_ksztaltem(tmp_path: Path, text: str, lines: list[int]) -> None:
    """Powroty #1585 W1 r1 (``_ensure_*``) i #1577 W1 r3 (odmowa ``needed_by``), sondy werdyktów #1724 r1 i r2 (``case``
    napisu z ``if`` w ciele i ze strażnikiem, ``else``), sonda #1727 r1 D2 (dozwolony ``if`` pod ``if``) i każda odmowa
    poza dozwolonym kształtem są zgłoszone; kształty dozwolone (``raise`` wprost w ``case`` klasy wyniku właściciela i
    pod ``if isinstance``/``is None`` wprost w ciele funkcji albo w takim ``case``, 404) nie."""

    base = _empty_base(tmp_path)
    _moduly_centrum(tmp_path, {"probka": _modul_zapisu(text)})

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(line, "regula-w-trasie") for line in lines]


_FIELD_PROBLEM = "from rozliczenia.centrum.settings.files import FieldProblem\n"
# Znane luki reguły ``regula-w-trasie`` (tests/fixtures/znane_luki.py): „klasa: postać” → nowy moduł z odmową
# reguły domeny Ustawień obok zapisu poza właścicielem, który mimo to przechodzi przez regułę i ruff z konfiguracją ``src/``.
ZNANE_LUKI_REGULY_W_TRASIE: Final = {
    "dozwolony warunek na wyniku sprawdzenia spoza właściciela: reguła czyta klasę w isinstance, nie źródło wartości": _modul_zapisu(
        f"from rozliczenia.centrum.device_forms import needed_by\n{_FIELD_PROBLEM}"
        f"{_ODMOWA}    needed = needed_by(problem)\n    if isinstance(needed, FieldProblem):\n"
        "        raise refusal.setting_refused(needed)\n"
    ),
    "dozwolony warunek na wyniku sprawdzenia spoza właściciela: reguła czyta is None, nie źródło wartości": _modul_zapisu(
        "from rozliczenia import worker_periods\n"
        f'{_ODMOWA}    found = worker_periods.unused(problem)\n    if found is None:\n        raise refusal.worker_kept(problem, "worker")\n'
    ),
    "nazwa: funkcja katalogu odmów importowana z nazwy": _modul_zapisu(
        "from rozliczenia.centrum.refusal import setting_refused\n\n\ndef changed(problem: object) -> None:\n"
        "    raise setting_refused(problem)\n"
    ),
    "nazwa: katalog odmów pod inną nazwą modułu": _modul_zapisu(
        "from rozliczenia.centrum import refusal as odmowy\n\n\ndef changed(problem: object) -> None:\n"
        '    raise odmowy.worker_kept(problem, "worker")\n'
    ),
    "nazwa: odmowa z funkcji spoza katalogu odmów": _modul_zapisu(
        "from rozliczenia.centrum import periods\n\n\ndef changed(problem: object) -> None:\n    raise periods.kept(problem)\n"
    ),
    "nazwa: sprawdzenie z innego modułu bez przedrostka _ensure_": _modul_zapisu(
        "from rozliczenia import worker_periods\n\n\ndef changed(problem: object) -> None:\n    worker_periods.ensure_unused(problem)\n"
    ),
    "nazwa: klasa wyniku o nazwie klasy właściciela spoza settings/owner.py": _modul_zapisu(
        "from rozliczenia.centrum.report_box import Refused\n"
        f"{_ODMOWA}    match problem:\n        case Refused():\n            raise refusal.setting_refused(problem)\n"
    ),
    "zakres: moduł zmienia Ustawienia funkcją innego modułu, nie metodą zapisu właściciela": (
        "from rozliczenia.centrum import refusal, settings_writes\n\n\n"
        'def apply(settings: object, problem: object) -> None:\n    if problem:\n        raise refusal.worker_kept(problem, "worker")\n'
        "    settings_writes.save(settings)\n"
    ),
    "zakres: nazwa metody zapisu właściciela sklejona z dwóch literałów": (
        "from rozliczenia.centrum import refusal\n\n\n"
        "def apply(settings: object, problem: object) -> None:\n    if problem:\n"
        '        raise refusal.worker_kept(problem, "worker")\n    getattr(settings, "chan" "ge")(problem)\n'
    ),
    "zakres: nazwa metody zapisu właściciela nie jest literałem, np. getattr ze zmienną": (
        "from rozliczenia.centrum import refusal\n\n\n"
        "def apply(settings: object, problem: object, operation: str) -> None:\n    if problem:\n"
        '        raise refusal.worker_kept(problem, "worker")\n    getattr(settings, operation)(problem)\n'
    ),
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_reguly_w_trasie_przechodza_przez_regule_i_ruff(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki, ruff

    base = _empty_base(tmp_path)
    pliki = _moduly_centrum(tmp_path, ZNANE_LUKI_REGULY_W_TRASIE)
    zgloszenia = ruff(pliki, sonda=ROOT.joinpath(*_CENTRUM, "test_sonda_luki_zapisu.py"))
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_w_trasie_przechodza_przez_regule_i_ruff")


_DARWIN = 'import sys\n\nif sys.platform == "darwin":\n    x: int = "a"  # type: ignore'
_NOT_TYPE_CHECKING = "from typing import TYPE_CHECKING\n\nif not TYPE_CHECKING:\n    "


_REGULY_KOMENTARZY: Final[dict[str, tuple[str, ...]]] = {"komentarz-w-src": ("src", "rozliczenia"), "komentarz-poza-src": ("tests",)}


@needs_ast_grep
@pytest.mark.parametrize("rule", _REGULY_KOMENTARZY)
@pytest.mark.parametrize(
    ("text", "lines"),
    [
        ("import os  # noqa: F401 - import dla efektu ubocznego\n", []),
        ("import os  # noqa: F401, E501 - powód\n", []),
        ('x: int = "a"  # type: ignore[assignment]\n', []),
        ('x: int = "a"  # type: ignore[assignment, no-untyped-call]  # powód\n', []),
        ('x: int = "a"  # type: ignore[assignment]\r\ny = 1\r\n', []),
        ("x = 1  # wyjaśnienie\n", [1]),
        ('"""Moduł."""\n# uwaga\nx = max(\n    1,  # pierwszy\n)\n# koniec', [2, 4, 6]),
        ("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n# fmt: off\nx = 1  # pragma: no cover\n", [2, 3, 4]),
        ("x = []  # type: list[int]\n", [1]),
        ("x = 1  # mypy: patrz, tu jest cała historia z #1234 i powód\n", [1]),
        ("# mypy: always-true=uwaga od PR 1234\n# mypy: ignore-errors\nx = 1\n", [1, 2]),
        ("# ruff: noqa: F401\nimport os\n", [1]),
        (f"{_DARWIN}[historia z PR 1614]\n", [4]),
        ("import os  # noqa: F401 , proza\n", [1]),
        ("import os  # noqa: F401, , proza\n", [1]),
        ("import os  # noqa\n", [1]),
        ("import os  # noqa: F401\n", [1]),
        ("import os  # noqa: F401 - \n", [1]),
        ("import os  # noqa: F401 E501 - powód\n", [1]),
        ("import os  # noqa: F401: powód\n", [1]),
        ("import os  # noqa:F401 - powód\n", [1]),
        ("import os  # NOQA: F401 - powód\n", [1]),
        ("import os  # noqa: f401 - powód\n", [1]),
        ("import os  # noqa: 1614 - powód\n", [1]),
        ("import os  # noqa: F401x - powód\n", [1]),
        ("import os  # noqa: UWAGA - powód\n", [1]),
        ("import os  # uwaga: noqa: F401 - powód\n", [1]),
        ("import os  # import z PR 12 # noqa: F401 - powód\n", [1]),
        ("import os  #noqa: F401 - powód\n", [1]),
        ("import os  #\tnoqa: F401 - powód\n", [1]),
        ('x: int = "a"  # type: ignore\n', [1]),
        ('x: int = "a"  # type: ignore[]\n', [1]),
        ('x: int = "a"  # type: ignore[assignment] powód\n', [1]),
        ('x: int = "a"  # type: ignore[assignment] # powód\n', [1]),
        ('x: int = "a"  # type: ignore[assignment,misc]\n', [1]),
        ('x: int = "a"  # type:ignore[assignment]\n', [1]),
        ('x: int = "a"  #  type: ignore[assignment]\n', [1]),
        ('x: int = "a"  # Type: Ignore[assignment]\n', [1]),
        ('x: int = "a"  # type: ignore[ASSIGNMENT]\n', [1]),
        ('x: int = "a"  # type: ignore[assignment2]\n', [1]),
        ('x: int = "a"  # type: ignore[assign--ment]\n', [1]),
        ('x: int = "a"  # type: ignore[assignment-]\n', [1]),
        ('x: int = "a"  # bo PR 12, type: ignore[assignment]\n', [1]),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje otwarty plik (https://learn.microsoft.com/office)\n", [], id="zewnetrzne-ze-zrodlem"),
        pytest.param("# ZEWNĘTRZNE: GitHub tnie komentarz (https://github.com/cli/cli/issues/1)\r\nx = 1\r\n", [], id="zewnetrzne-z-issue-innego-repo-i-crlf"),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje otwarty plik\n", [1], id="zewnetrzne-bez-zrodla"),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje otwarty plik ()\n", [1], id="zewnetrzne-z-pustym-zrodlem"),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje otwarty plik ( Excel)\n", [1], id="zewnetrzne-ze-zrodlem-od-spacji"),
        pytest.param("x = 1  # ZEWNĘTRZNE: (https://learn.microsoft.com)\n", [1], id="zewnetrzne-bez-faktu"),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje plik (https://learn.microsoft.com) i proza\n", [1], id="zewnetrzne-z-proza-po-zrodle"),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje plik (#1234)\n", [1], id="zewnetrzne-ze-zrodlem-w-issue-repo"),
        pytest.param("x = 1  # ZEWNĘTRZNE: Excel blokuje plik, patrz #1234 (Excel)\n", [1], id="zewnetrzne-z-numerem-issue-w-fakcie"),
        pytest.param(
            "x = 1  # ZEWNĘTRZNE: Excel blokuje plik (https://GitHub.com/MaximiseArtAI/MAXIMISEART-Dad/pull/12)\n", [1], id="zewnetrzne-z-adresem-repo"
        ),
        pytest.param("import os  # noqa: F401 - import z przeglądu #1234\n", [1], id="noqa-z-numerem-issue-w-powodzie"),
        pytest.param(
            'x: int = "a"  # type: ignore[assignment]  # jak w github.com/maximiseartai/MAXIMISEART-Dad/pull/1\n', [1], id="type-ignore-z-adresem-repo-w-powodzie"
        ),
        pytest.param(
            "# ZEWNĘTRZNE: GitHub tnie (https://api.github.com/repos/maximiseartai/MAXIMISEART-Dad/issues/12)\nx = 1\n", [1], id="zewnetrzne-z-adresem-api-repo"
        ),
        pytest.param(
            "import os  # noqa: F401 - jak w github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/5\n", [1], id="noqa-z-adresem-repo-zgloszen"
        ),
        pytest.param("x = 1  # zewnętrzne: Excel blokuje plik (Excel)\n", [1], id="zewnetrzne-malymi-literami"),
        pytest.param("x = 1  # ZEWNETRZNE: Excel blokuje plik (Excel)\n", [1], id="zewnetrzne-bez-polskiej-litery"),
        pytest.param("x = 1  #ZEWNĘTRZNE: Excel blokuje plik (Excel)\n", [1], id="zewnetrzne-bez-spacji-po-haszu"),
        pytest.param("#!/usr/bin/env python3\r\nx = 1\r\n", [], id="shebang-w-pierwszej-linii-crlf"),
        pytest.param('"""Moduł."""\n#!/usr/bin/env python3\n', [2], id="shebang-po-docstringu"),
        pytest.param("x = 1\n#!/usr/bin/env python3\n", [2], id="shebang-po-kodzie"),
        pytest.param("#!/usr/bin/env python\nx = 1\n", [1], id="shebang-pythona-bez-wersji"),
        pytest.param("#!/usr/bin/python3\nx = 1\n", [1], id="shebang-bez-env"),
        pytest.param("#!/usr/bin/env python3 -u\nx = 1\n", [1], id="shebang-z-argumentem"),
        pytest.param("def f() -> None:\n    #!/usr/bin/env python3\n    pass\n", [2], id="shebang-w-bloku-funkcji"),
    ],
)
def test_komentarz_w_src_i_poza_nim_przechodzi_tylko_w_postaci_z_listy_wyjatkow(tmp_path: Path, rule: str, text: str, lines: list[int]) -> None:
    base = _empty_base(tmp_path)
    (folder := tmp_path.joinpath(*_REGULY_KOMENTARZY[rule])).mkdir(parents=True)
    (folder / "probka.py").write_text(text, encoding="utf-8")

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(line, rule) for line in lines]


@needs_ast_grep
def test_komentarz_w_src_czyta_pliki_py_pyi_i_py3_a_pomija_pyw_i_plik_bez_rozszerzenia(tmp_path: Path) -> None:
    """Granica zbioru plików reguły: ``files:`` ma globy ``.py``, ``.pyi`` i ``.py3``, więc ``.pyw`` i skrypt Pythona
    bez rozszerzenia przechodzą z komentarzem prozy; gdy reguła zacznie je czytać, ten test każe przesunąć granicę."""

    base = _empty_base(tmp_path)
    names = ("a.py", "pakiet/b.py", "c.pyi", "d.py3", "e.pyw", "skrypt")
    for name in names:
        (tmp_path / "src" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / name).write_text("#!/usr/bin/env python3\nx = 1  # proza\n", encoding="utf-8")

    assert [finding.path for finding in syntax_rules(tmp_path, base)] == sorted(f"src/{name}" for name in names[:4])


_ZAKRES_KOMENTARZY_POZA_SRC: Final[tuple[tuple[str, ...], ...]] = (
    ("tests", "test_a.py"),
    ("tests", "fixtures", "b.pyi"),
    ("tools", "c.py3"),
    ("tools", "lib", "d.py"),
    (".agents", "skills", "s", "scripts", "drive", "e.py"),
    ("conftest.py",),
    ("docs", "f.py"),
    (".github", "scripts", "g.py"),
    ("frontend", "scripts", "h.py"),
)


@needs_ast_grep
def test_komentarz_poza_src_czyta_kazdy_plik_py_pyi_i_py3_poza_src_a_src_zostawia_regule_komentarz_w_src(tmp_path: Path) -> None:
    base = _empty_base(tmp_path)
    for parts in (*_ZAKRES_KOMENTARZY_POZA_SRC, ("src", "rozliczenia", "i.py")):
        tmp_path.joinpath(*parts).parent.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(*parts).write_text("x = 1  # proza\n", encoding="utf-8")

    assert sorted((finding.path, finding.rule) for finding in syntax_rules(tmp_path, base)) == sorted(
        [*(("/".join(parts), "komentarz-poza-src") for parts in _ZAKRES_KOMENTARZY_POZA_SRC), ("src/rozliczenia/i.py", "komentarz-w-src")]
    )


_BAZA_KOMENTARZY_POZA_SRC: Final = {"tests/test_stary.py": "X = 1  # komentarz\n"}
ZNANE_LUKI_KOMENTARZY_POZA_SRC: Final[dict[str, tuple[dict[str, str], tuple[tuple[str, ...], ...]]]] = {
    "plik spoza języków ast-grep: rozszerzenie .pyw": ({"tools/skrypt.pyw": "X = 1  # proza\n"}, ()),
    "plik spoza języków ast-grep: Python bez rozszerzenia jak tools/hooks/pre-push": (
        {"tools/hooks/skrypt": "#!/usr/bin/env python3\nX = 1  # proza\n"},
        (),
    ),
    "przeniesienie bez zmian: git mv pliku z komentarzem (git diff -M)": ({}, (("mv", "tests/test_stary.py", "tests/test_nowy.py"),)),
    "shebang poza pierwszą linią: pusta linia przed nim": ({"tests/test_a.py": "\n#!/usr/bin/env python3\nX = 1\n"}, ()),
    "fakt bez sprawdzenia: proza o kodzie repo w postaci ZEWNĘTRZNE": ({"tests/test_a.py": "X = 1  # ZEWNĘTRZNE: ta funkcja jest wolna (Maks)\n"}, ()),
}


@needs_ast_grep
def test_znane_luki_reguly_komentarz_poza_src_przechodza_przez_zapadke_regul_ast_grep(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki

    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, (pliki, polecenia)) in enumerate(ZNANE_LUKI_KOMENTARZY_POZA_SRC.items()):
        root = tmp_path / str(numer)
        base = _committed(root, _BAZA_KOMENTARZY_POZA_SRC)
        for nazwa, tekst in pliki.items():
            (root / nazwa).parent.mkdir(parents=True, exist_ok=True)
            (root / nazwa).write_text(tekst, encoding="utf-8")
        for polecenie in polecenia:
            _git(root, *polecenie)
        zgloszenia[opis] = [f"{finding.path}:{finding.line}: {finding.rule}" for finding in syntax_rules(root, base)]

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_komentarz_poza_src_przechodza_przez_zapadke_regul_ast_grep")


# Znane luki reguły ``komentarz-w-src`` (tests/fixtures/znane_luki.py): „klasa: postać” → nowy plik ``src/`` z komentarzem
# poza tłumieniem, który mimo to przechodzi przez regułę, ruff z konfiguracją ``src/`` i mypy z ``pyproject.toml`` na
# każdej platformie kroków mypy zadania CI „Ruff, mypy” (``platformy_mypy_ci``), nie na platformie hosta.
ZNANE_LUKI_KOMENTARZY: Final = {
    "powód tłumienia: drugie noqa w powodzie noqa": "import os  # noqa: F401 - powód  # noqa: E501 - drugi\n",
    "powód tłumienia: type: ignore w powodzie noqa": "import os  # noqa: F401 - powód  # type: ignore[misc]\n",
    "powód tłumienia: drugie type: ignore w powodzie": 'x: int = "a"  # type: ignore[assignment]  # type: ignore[misc]\n',
    "kod mypy: słowo w kształcie kodu pod if not TYPE_CHECKING": f"{_NOT_TYPE_CHECKING}x: int = 'a'  # type: ignore[historia]\n",
    "kod mypy: słowo w kształcie kodu obok prawdziwego pod if not TYPE_CHECKING": (
        f"{_NOT_TYPE_CHECKING}x: int = 'a'  # type: ignore[assignment, historia]\n"
    ),
    "kod mypy: słowo w kształcie kodu w gałęzi sys.platform == \"darwin\", której żaden krok mypy w CI nie sprawdza": (
        f"{_DARWIN}[historia]\n"
    ),
    "kod mypy: słowo w kształcie kodu obok prawdziwego w gałęzi sys.platform == \"darwin\", której żaden krok mypy w CI nie sprawdza": (
        f"{_DARWIN}[assignment, historia]\n"
    ),
    "kod mypy: słowo w kształcie kodu w gałęzi sys.version_info nowszej niż python_version mypy": (
        "import sys\n\nif sys.version_info >= (3, 14):\n    x: int = 'a'  # type: ignore[historia]\n"
    ),
    f"dyrektywa {_IGNORE}: nazwa tej reguły i proza w komentarzu obok kodu": (
        f"x = 1  # {_IGNORE}: komentarz-w-src (wyjaśnienie obok kodu)\n"
    ),
    "fakt bez sprawdzenia: proza o kodzie repo w postaci ZEWNĘTRZNE": "x = 1  # ZEWNĘTRZNE: ta funkcja jest wolna (Maks)\n",
}


@needs_ast_grep
@pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None or importlib.util.find_spec("mypy") is None,
    reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff i mypy",
)
def test_znane_luki_reguly_komentarz_w_src_przechodza_przez_regule_ruff_i_mypy(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki, ruff_i_mypy, zapisz

    base = _empty_base(tmp_path)
    (tmp_path / "src" / "rozliczenia").mkdir(parents=True)
    pliki = zapisz(ZNANE_LUKI_KOMENTARZY, tmp_path / "src" / "rozliczenia")
    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_komentarz_w_src_przechodza_przez_regule_ruff_i_mypy")


# Reguły ast-grep powrotów chwastów (#1676, ADR 0036) → katalog w zakresie ``files:`` reguły i przyrostek nazwy pliku
# próbki. Katalog to części ścieżki, nie napis z ``/``, bo napis ścieżki w pliku testu jest zależnością testu w grafie
# wpływu zmiany (``tools/lib/wplyw_zmiany.py``); katalog to prawdziwy katalog repo, więc ruff próbki czyta jego
# konfigurację.
_ZAKRES_REGUL_POWROTOW: Final[dict[str, tuple[tuple[str, ...], str]]] = {
    "kotwica-konca-linii": (("tools",), ".py"),
    "krok-mypy-ruff-poza-krokami": (("tools",), ".py"),
    "naglowek-toml-podlancuchem": (("tools",), ".py"),
    "komunikat-boxa-podlancuchem": (("tools",), ".py"),
    "stosunek-czasow-sciany": (("tests",), ".py"),
}
_SYS = "import sys\n\n"
_TOML = "from pathlib import Path\n\n\ndef uv(plik: Path) -> bool:\n    return "
_BOX = "import box_boat\n\n\ndef infra(wyjscie: str) -> bool:\n    return "
_ZEGAR = "import time\n\n\ndef test_stosunek() -> None:\n    start = time.perf_counter()\n    srodek = time.perf_counter()\n"
_PATTERN = "import re\n\nLINE = "
# Reguła powrotu → (tekst dodanego pliku w jej zakresie, linie, które zgłasza): postać z powrotu, którą reguła łapie
# (#1584 W1 r1), i postać po poprawce, którą przepuszcza.
_PROBKI_REGUL_POWROTOW: Final[list[tuple[str, str, list[int]]]] = [
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE \\| test .*$")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"(?m)^" + r"PONOWIENIE$")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.search(rf"{{LINE}}$", "")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE\\r?$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE\\s*$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE\\s+$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE \\s?$")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE\\n$")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"cena w \\$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}"PONOWIENIE$"\n', []),
    ("krok-mypy-ruff-poza-krokami", f'{_SYS}POLECENIE = [sys.executable, "-m", "mypy", "--no-incremental"]\n', [3]),
    ("krok-mypy-ruff-poza-krokami", f"{_SYS}POLECENIE = (sys.executable, '-m', 'ruff', 'check')\n", [3]),
    ("krok-mypy-ruff-poza-krokami", f'{_SYS}POLECENIE = [sys.executable, "-m", "pytest", "-q"]\n', []),
    ("krok-mypy-ruff-poza-krokami", 'NARZEDZIA = ["mypy", "ruff"]\n', []),
    ("krok-mypy-ruff-poza-krokami", f'{_SYS}POLECENIE = [sys.executable, "-m", "mypy", "--strict", "format"]\n', [3]),
    ("krok-mypy-ruff-poza-krokami", f'{_SYS}POLECENIE = [sys.executable, "-m", "ruff", "format", "--check"]\n', []),
    ("naglowek-toml-podlancuchem", f'{_TOML}"[tool.uv" in plik.read_text(encoding="utf-8")\n', [5]),
    ("naglowek-toml-podlancuchem", f'{_TOML}"[project]" not in plik.read_text()\n', [5]),
    ("naglowek-toml-podlancuchem", f'import tomllib\n\n{_TOML}"uv" in tomllib.loads(plik.read_text())["tool"]\n', []),
    ("naglowek-toml-podlancuchem", f'{_TOML}"[tool.uv" in str(plik)\n', []),
    ("komunikat-boxa-podlancuchem", f"{_BOX}box_boat.KOMUNIKAT in wyjscie\n", [5]),
    ("komunikat-boxa-podlancuchem", f"{_BOX}box_boat.KOMUNIKAT not in wyjscie\n", [5]),
    ("komunikat-boxa-podlancuchem", "from box_boat import KOMUNIKAT\n\n\ndef infra(wyjscie: str) -> bool:\n    return KOMUNIKAT in wyjscie\n", [5]),
    ("komunikat-boxa-podlancuchem", "import box_boat\n\n\ndef komunikat() -> str:\n    return box_boat.KOMUNIKAT\n", []),
    ("komunikat-boxa-podlancuchem", f'{_BOX}"OK" in wyjscie\n', []),
    ("stosunek-czasow-sciany", f"{_ZEGAR}    assert (time.perf_counter() - srodek) / (srodek - start) < 2\n", [7]),
    ("stosunek-czasow-sciany", f"{_ZEGAR}    assert (time.monotonic() - start) / (time.monotonic() - srodek) < 2\n", [7]),
    ("stosunek-czasow-sciany", f"{_ZEGAR}    assert time.perf_counter() - srodek < start\n", []),
    ("stosunek-czasow-sciany", f"{_ZEGAR}    assert (time.perf_counter() - srodek) / 2 < start\n", []),
]


def _probki_w_zakresie(root: Path, rule: str, probki: dict[str, str]) -> dict[str, Path]:
    """Plik każdej próbki reguły ``rule`` w katalogu jej zakresu ``files:`` w ``root``, z przyrostkiem nazwy z
    ``_ZAKRES_REGUL_POWROTOW``."""

    parts, suffix = _ZAKRES_REGUL_POWROTOW[rule]
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    pliki = {opis: folder / f"znana_luka_{numer}{suffix}" for numer, opis in enumerate(probki)}
    for opis, plik in pliki.items():
        plik.write_text(probki[opis], encoding="utf-8")
    return pliki


@needs_ast_grep
@pytest.mark.parametrize(("rule", "text", "lines"), _PROBKI_REGUL_POWROTOW)
def test_regula_powrotu_zglasza_postac_z_powrotu_a_nie_postac_po_poprawce(
    tmp_path: Path, rule: str, text: str, lines: list[int]
) -> None:
    base = _empty_base(tmp_path)
    _probki_w_zakresie(tmp_path, rule, {"probka": text})

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(line, rule) for line in lines]


@needs_ast_grep
@pytest.mark.parametrize(
    "naglowek",
    [
        pytest.param('"[tool.uv"', id="nawias-na-poczatku"),
        pytest.param('"\\n[tool.uv]"', id="nawias-po-nowej-linii"),
        pytest.param('"\\n\\n[project]"', id="nawias-po-dwoch-nowych-liniach"),
        pytest.param('"uv = 1\\n[tool.uv]"', id="nawias-w-srodku-napisu"),
        pytest.param('"\\n  [tool.uv]"', id="nawias-po-wcieciu"),
        pytest.param('r"\\n[tool.uv]"', id="napis-surowy"),
    ],
)
def test_naglowek_toml_podlancuchem_zglasza_naglowek_od_poczatku_linii(tmp_path: Path, naglowek: str) -> None:
    base = _empty_base(tmp_path)
    _probki_w_zakresie(tmp_path, "naglowek-toml-podlancuchem", {"probka": f"{_TOML}{naglowek} in plik.read_text()\n"})

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(5, "naglowek-toml-podlancuchem")]


@needs_ast_grep
@pytest.mark.parametrize(
    ("szukanie", "linie"),
    [
        pytest.param(f'{_TOML}"""[tool.uv]\nmanaged = true""" in plik.read_text()\n', [5], id="potrojny-cudzyslow"),
        pytest.param(f'{_TOML}"""\n[tool.uv]\n""" in plik.read_text()\n', [5], id="potrojny-cudzyslow-od-nowej-linii"),
        pytest.param(f'{_TOML}plik.read_text().find("\\n[tool.uv]") >= 0\n', [5], id="find-na-tekscie-pliku"),
        pytest.param(f'{_TOML}plik.read_text(encoding="utf-8").count("[project]") > 0\n', [5], id="count-na-tekscie-pliku"),
        pytest.param(f'{_TOML}"[" in plik.name\n', [], id="nawias-poza-tekstem-pliku"),
        pytest.param(f'{_TOML}"a[0]" in plik.read_text()\n', [], id="nawias-w-srodku-linii"),
        pytest.param(f'{_TOML}plik.read_text().find("tool.uv") >= 0\n', [], id="find-bez-nawiasu"),
    ],
)
def test_naglowek_toml_podlancuchem_w_kazdym_zapisie_literalu(tmp_path: Path, szukanie: str, linie: list[int]) -> None:
    base = _empty_base(tmp_path)
    _probki_w_zakresie(tmp_path, "naglowek-toml-podlancuchem", {"probka": szukanie})

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(line, "naglowek-toml-podlancuchem") for line in linie]


# Znane luki reguł powrotów (tests/fixtures/znane_luki.py): reguła → „klasa: postać” → dodany plik w zakresie
# ``files:`` reguły z postacią tego samego chwastu, który mimo to przechodzi przez wszystkie reguły ast-grep i ruff z
# konfiguracją swojego katalogu.
ZNANE_LUKI_REGUL_POWROTOW: Final[dict[str, dict[str, str]]] = {
    "kotwica-konca-linii": {
        "wzorzec w stałej poza wywołaniem re": f'{_PATTERN}r"PONOWIENIE$"\nFOUND = re.compile(LINE)\n',
        "kotwica w środku wzorca": f'{_PATTERN}re.compile(r"PONOWIENIE$|ZNANY")\n',
        "re pod inną nazwą": 'import re as wzorce\n\nLINE = wzorce.compile(r"PONOWIENIE$")\n',
        "kotwica po ukośniku literału": f'{_PATTERN}re.compile(r"C:\\\\$")\n',
    },
    "krok-mypy-ruff-poza-krokami": {
        "program bez -m": 'POLECENIE = ["mypy", "--no-incremental"]\n',
        "narzędzie w zmiennej": f'{_SYS}NARZEDZIE = "mypy"\nPOLECENIE = [sys.executable, "-m", NARZEDZIE]\n',
        "polecenie w jednym napisie": 'POLECENIE = "python -m mypy --no-incremental"\n',
    },
    "naglowek-toml-podlancuchem": {
        "tekst pliku w zmiennej": 'from pathlib import Path\n\n\ndef uv(plik: Path) -> bool:\n    tekst = plik.read_text()\n    return "[tool.uv" in tekst\n',
        "klucz bez nawiasu": f'{_TOML}"tool.uv" in plik.read_text()\n',
    },
    "komunikat-boxa-podlancuchem": {
        "tekst komunikatu w literale": 'def infra(wyjscie: str) -> bool:\n    return "BOX: boat przeniósł katalog repo" in wyjscie\n',
        "szukanie przez find": f"{_BOX}wyjscie.find(box_boat.KOMUNIKAT) >= 0\n",
    },
    "stosunek-czasow-sciany": {
        "stosunek zapisany mnożeniem": f"{_ZEGAR}    assert time.perf_counter() - srodek < 2 * (srodek - start)\n",
        "czasy w nazwanych zmiennych": f"{_ZEGAR}    pierwszy = srodek - start\n    drugi = time.perf_counter() - srodek\n    assert drugi / pierwszy < 2\n",
    },
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_regul_powrotow_przechodza_przez_reguly_ast_grep_i_ruff(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki, ruff

    base = _empty_base(tmp_path)
    zgloszenia: dict[str, list[str]] = {}
    opisy: dict[str, str] = {}
    for rule, probki in ZNANE_LUKI_REGUL_POWROTOW.items():
        pliki = {f"{rule}: {opis}": plik for opis, plik in _probki_w_zakresie(tmp_path, rule, probki).items()}
        zgloszenia |= ruff(pliki, sonda=ROOT.joinpath(*_ZAKRES_REGUL_POWROTOW[rule][0], "test_sonda_luki.py"))
        opisy |= {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_regul_powrotow_przechodza_przez_reguly_ast_grep_i_ruff")


_PAGE = "from playwright.sync_api import Page\n\n\n"

# Znane luki zapadek (tests/fixtures/znane_luki.py): test zapadki → opis postaci → plik, który dodaje formę zakazaną
# regułą zapadki, a mimo to przechodzi przez zapadkę i ruff z konfiguracją swojego folderu.
ZNANE_LUKI: Final = {
    "test_odpowiedz_nawigacji_karty_w_src_nie_jest_odrzucona": {
        "po linii, której komentarz kończy się przecinkiem": _PAGE
        + """\
def open_order(page: Page, url: str) -> None:
    page.wait_for_timeout(0)  # najpierw lista,
    page.goto(url)
""",
        "po linii, której tekst przed odstępem z # kończy się przecinkiem": _PAGE
        + """\
def open_order(page: Page, url: str) -> None:
    page.evaluate("1, #1")
    page.goto(url)
""",
        "as _": _PAGE
        + """\
def open_order(page: Page) -> None:
    with page.expect_navigation() as _:
        page.click("a")
""",
        "expect_navigation z nawiasem w kilku liniach": _PAGE
        + """\
def open_order(page: Page) -> None:
    with page.expect_navigation(
        timeout=1000,
    ):
        page.click("a")
""",
        "nawigacja na wyniku wywołania": _PAGE
        + """\
def open_order(page: Page, url: str) -> None:
    page.context.new_page().goto(url)
""",
        "wait_for_url": _PAGE
        + """\
def open_order(page: Page, url: str) -> None:
    page.click("a")
    page.wait_for_url(url)
""",
        "wait_for_load_state": _PAGE
        + """\
def open_order(page: Page) -> None:
    page.click("a")
    page.wait_for_load_state()
""",
        "metoda pod inną nazwą": _PAGE
        + """\
def open_order(page: Page, url: str) -> None:
    go = page.goto
    go(url)
""",
        "karta bez importu playwright": """\
from typing import Protocol


class Tab(Protocol):
    def goto(self, url: str) -> object: ...


def open_order(page: Tab, url: str) -> None:
    page.goto(url)
""",
        "nowa instrukcja po krotce bez nawiasu": _PAGE
        + """\
def open_order(page: Page, url: str) -> tuple[str]:
    names = url,
    page.goto(url)
    return names
""",
        "element listy, której nikt nie czyta": _PAGE
        + """\
def open_order(page: Page, url: str) -> None:
    [
        page.goto(url),
    ]
""",
    },

}

# Test zapadki → folder repozytorium, w którym zapadka szuka, i jej sprawdzenie dodanych linii.
_ZAPADKI: Final = {
    "test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo": ("src/rozliczenia", syntax_rule_findings),
    "test_odpowiedz_nawigacji_karty_w_src_nie_jest_odrzucona": ("src/rozliczenia", navigation_drops),
}


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
@pytest.mark.parametrize("zapadka", sorted(ZNANE_LUKI))
def test_znane_luki_zapadki_przechodza_przez_zapadke_i_ruff(tmp_path: Path, zapadka: str) -> None:
    """Każda próbka ``ZNANE_LUKI`` zapadki, zapisana jako nowy plik jej folderu, przechodzi przez jej sprawdzenie
    dodanych linii i ruff z konfiguracją tego folderu. Pomocnik ``znane_luki`` importuje się tu, a nie na górze modułu,
    bo pomiar zapadek kładzie ten plik na starych commitach, które go nie mają."""

    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    folder, sprawdzenie = _ZAPADKI[zapadka]
    base = _empty_base(tmp_path)
    (tmp_path / folder).mkdir(parents=True)
    pliki = zapisz(ZNANE_LUKI[zapadka], tmp_path / folder)
    zgloszenia = ruff(pliki, sonda=ROOT / folder / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for linia in sprawdzenie(tmp_path, base):
        zgloszenia[opisy[linia.split(":", 1)[0]]].append(f"{zapadka}: {linia}")

    assert_znane_luki(zgloszenia, f"tests/test_zapadki.py::{zapadka}")


# Katalog skryptu skilla w zakresie ``files:`` reguły ``lokator-tytulu-okna`` jako części ścieżki, nie napis z ``/``,
# bo napis ścieżki w pliku testu jest zależnością testu w grafie wpływu zmiany (``tools/lib/wplyw_zmiany.py``); to
# prawdziwy katalog, więc ruff próbki czyta jego ``ruff.toml``.
_KATALOG_LOKATORA: Final = (".agents", "skills", "verify-centrum-rozliczen", "scripts", "drive")
_LOCATOR = "from playwright.sync_api import Locator, Page\n\n\ndef title(page: Page) -> Locator:\n    return "
# Tekst dodanego skryptu skilla → linie, które reguła ``lokator-tytulu-okna`` zgłasza: rola nagłówka z powrotu #1533
# W1 r2 w każdym zapisie literału i w nawiasach, i lokatory zawężone albo innej roli, które przepuszcza.
_PROBKI_LOKATORA: Final[list[tuple[str, list[int]]]] = [
    (f'{_LOCATOR}page.get_by_role("heading")\n', [5]),
    (f'{_LOCATOR}page.get_by_role(role="heading")\n', [5]),
    (f"{_LOCATOR}page.get_by_role('heading')\n", [5]),
    (f"{_LOCATOR}page.get_by_role(role='heading')\n", [5]),
    (f'{_LOCATOR}page.get_by_role(f"heading")\n', [5]),
    (f'{_LOCATOR}page.get_by_role("""heading""")\n', [5]),
    (_LOCATOR + "page.get_by_role('''heading''')\n", [5]),
    (f'{_LOCATOR}page.get_by_role(r"heading")\n', [5]),
    (f'{_LOCATOR}page.get_by_role(u"heading")\n', [5]),
    (f'{_LOCATOR}page.get_by_role(rf"heading")\n', [5]),
    (f'{_LOCATOR}page.get_by_role(("heading"))\n', [5]),
    (f'{_LOCATOR}page.get_by_role((("heading")))\n', [5]),
    (f"{_LOCATOR}page.get_by_role(role=('heading'))\n", [5]),
    (f'{_LOCATOR}page.get_by_role(role=(("heading")))\n', [5]),
    (f'{_LOCATOR}page.get_by_role("head\\x69ng")\n', [5]),
    (f'{_LOCATOR}(page.get_by_role)("heading")\n', [5]),
    (f'{_LOCATOR}page.get_by_role("heading", exact=True)\n', [5]),
    (f'{_LOCATOR}page.get_by_role("heading", level=2)\n', [5]),
    (f'{_LOCATOR}page.get_by_role("heading", name="")\n', [5]),
    (f"{_LOCATOR}page.get_by_role('heading', level=2, name='')\n", [5]),
    (f'{_LOCATOR}page.get_by_role("heading", name=(r""))\n', [5]),
    (_LOCATOR + 'page.get_by_role("heading", name=\'\'\'\'\'\')\n', [5]),
    (f'{_LOCATOR}page.get_by_role(  # nagłówek\n        "heading",\n    )\n', [5]),
    (f'{_LOCATOR}page.locator("main").get_by_role("heading").first\n', [5]),
    (f'{_LOCATOR}page.get_by_role(f"{{HEADING}}heading")\n', []),
    (f'{_LOCATOR}page.get_by_role(f"{{{{heading}}}}")\n', []),
    (f'{_LOCATOR}page.get_by_role(r"head\\x69ng")\n', []),
    (f'{_LOCATOR}page.get_by_role("heading", name="Okresy", exact=True)\n', []),
    (f'{_LOCATOR}page.get_by_role("heading", level=2, name="Okresy")\n', []),
    (f'{_LOCATOR}page.get_by_role(("heading"), name="Okresy")\n', []),
    (f'{_LOCATOR}page.get_by_role("button")\n', []),
    (f'{_LOCATOR}page.get_by_text("heading")\n', []),
]


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_LOKATORA)
def test_lokator_tytulu_okna_zglasza_literal_roli_naglowka_bez_nazwy_w_kazdym_zapisie(
    tmp_path: Path, text: str, lines: list[int]
) -> None:
    from tests.fixtures.znane_luki import zapisz

    base = _empty_base(tmp_path)
    (folder := tmp_path.joinpath(*_KATALOG_LOKATORA)).mkdir(parents=True)
    zapisz({"probka": text}, folder)

    found = syntax_rules(tmp_path, base)

    assert [finding.line for finding in found if finding.rule == "lokator-tytulu-okna"] == lines


# Znane luki reguły ``lokator-tytulu-okna`` (tests/fixtures/znane_luki.py): „klasa: postać” → dodany skrypt skilla
# z nagłówkiem bez nazwy albo kopią tytułu okna, który mimo to przechodzi przez wszystkie reguły ast-grep i ruff.
ZNANE_LUKI_LOKATORA: Final[dict[str, str]] = {
    "rola nie jest literałem: nazwa zmiennej": f'{_LOCATOR}page.get_by_role(role)\n\n\nrole = "heading"\n',
    "rola nie jest literałem: stała modułu": f'{_LOCATOR}page.get_by_role(HEADING)\n\n\nHEADING = "heading"\n',
    "rola nie jest literałem: atrybut": f'{_LOCATOR}page.get_by_role(Roles.HEADING)\n\n\nclass Roles:\n    HEADING = "heading"\n',
    "rola nie jest literałem: sklejone napisy": f'{_LOCATOR}page.get_by_role("head" "ing")\n',
    "rola nie jest literałem: operator +": f'{_LOCATOR}page.get_by_role("head" + "ing")\n',
    "rola nie jest literałem: wywołanie": f'{_LOCATOR}page.get_by_role("HEADING".lower())\n',
    "rola nie jest literałem: f-napis ze wstawką": _LOCATOR + "page.get_by_role(f\"{'heading'}\")\n",
    "rola nie jest literałem: wyrażenie warunkowe": f'{_LOCATOR}page.get_by_role("heading" if page else "button")\n',
    "rola nie jest literałem: indeks": f'{_LOCATOR}page.get_by_role(ROLES[0])\n\n\nROLES = ("heading",)\n',
    "rola nie jest literałem: rozpakowanie argumentów": f'{_LOCATOR}page.get_by_role(*ROLES)\n\n\nROLES = ("heading",)\n',
    "rola nie jest literałem: rozpakowanie słownika": f'{_LOCATOR}page.get_by_role(**{{"role": "heading"}})\n',
    "metoda pod inną nazwą": f'{_LOCATOR}by_role("heading")\n\n\nby_role = Page.get_by_role\n',
    "pusta nazwa nie jest literałem: stała modułu": f'{_LOCATOR}page.get_by_role("heading", name=ANY)\n\n\nANY = ""\n',
    "kopia właściciela: lokator settings_title z name= poza drive/common.py": (
        f'import re\n\n{_LOCATOR}page.get_by_role("heading", name=re.compile(r"^Ustawienia "))\n'
    ),
    "selektor zamiast roli": f'{_LOCATOR}page.locator("h2")\n',
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_lokatora_tytulu_okna_przechodza_przez_reguly_ast_grep_i_ruff(tmp_path: Path) -> None:
    """Reguła ``lokator-tytulu-okna`` czyta tylko literał roli: z miejsca albo ``role=``, po zdjęciu dowolnej liczby
    nawiasów, napis o wartości ``heading`` w dowolnym zapisie (cudzysłów, przedrostki ``r``, ``u``, ``f`` bez wstawki,
    ucieczki), a zawężenie tylko z ``name=``, którego wartość nie jest literałem pustego napisu (``level=`` nie odróżnia
    tytułu okna od tytułu powiadomienia, bo oba to ``<h2>``). Każda rola, która nie jest literałem, to jedna klasa
    znanej luki „rola nie jest literałem”, z próbką na rodzaj wyrażenia; bajty ``b"…"`` i szablon ``t"…"`` nie są
    napisem roli, więc nie są lukami."""

    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (folder := tmp_path.joinpath(*_KATALOG_LOKATORA)).mkdir(parents=True)
    pliki = zapisz(ZNANE_LUKI_LOKATORA, folder)
    zgloszenia = ruff(pliki, sonda=ROOT.joinpath(*_KATALOG_LOKATORA, "test_sonda_luki.py"))
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_lokatora_tytulu_okna_przechodza_przez_reguly_ast_grep_i_ruff")


def _findings_of(rule: str, root: Path, base: str) -> list[tuple[str, int]]:
    """Odpalenia reguły ``rule`` (z całego katalogu reguł) na liniach dodanych od ``base``: ścieżka i linia; reguły
    ``src/`` o komentarzach i docstringach zgłaszają w tych samych próbkach swoje, więc liczy się tylko ta jedna."""

    return [(finding.path, finding.line) for finding in syntax_rules(root, base) if finding.rule == rule]


_STATE_RULE = "stan-pliku-poza-file-state"
_IN_TAKEN = "def taken(path, copy, old, entries, link, folder):\n"
# Tekst dodanego pliku ``src/`` → linie, które reguła ``stan-pliku-poza-file-state`` zgłasza: stan ścieżki z pominięciem
# ``file_state`` z ea69c32bea (``copy.path.exists()``) i 5f4e134ba5 (``old.is_file()``) w każdej postaci, którą reguła
# czyta, i pytania o stan przez ``file_state`` albo metodę domeny z argumentem, które przepuszcza.
_PROBKI_STANU_PLIKU: Final[list[tuple[str, list[int]]]] = [
    (f"{_IN_TAKEN}    taken = copy.path.exists()\n", [2]),
    (f"{_IN_TAKEN}    return old.name if old.is_file() else None\n", [2]),
    (f"{_IN_TAKEN}    if STATIC_DIRECTORY.is_dir():\n        pass\n", [2]),
    (f"{_IN_TAKEN}    return [entry for entry in entries if entry.is_dir() and _YEAR_FOLDER.fullmatch(entry.name)]\n", [2]),
    (f"{_IN_TAKEN}    return os.path.exists(excel_lock_file(path))\n", [2]),
    (f"{_IN_TAKEN}    return dict(collective_file_exists=os.path.isfile(path))\n", [2]),
    (f"{_IN_TAKEN}    if not path.exists( ):\n        pass\n", [2]),
    (f"{_IN_TAKEN}    return path.exists(\n    )\n", [2]),
    (f"{_IN_TAKEN}    taken = os.path.lexists(link)\n", [2]),
    (f"{_IN_TAKEN}    if os.path.isdir(folder):\n        pass\n", [2]),
    (f"{_IN_TAKEN}    return path  # path.exists() pomijam\n", [2]),
    (f'{_IN_TAKEN}    return "os.path.isfile(x)"\n', [2]),
    (f'{_IN_TAKEN}    return old.name if file_state(old) == "file" else None\n', []),
    (f"{_IN_TAKEN}    if path_taken(self._state):\n        pass\n", []),
    (f"{_IN_TAKEN}    return [period_place_label(place) for place in places if observed.exists(place)]\n", []),
    # os.path na atrybucie os i łamane przed kropką (#1868 r1); tekst każdej nazwy w komentarzu i napisie.
    (f"{_IN_TAKEN}    return foo.os.path.exists(path)\n", [2]),
    (f"{_IN_TAKEN}    return (os\n        .path.isdir(path))\n", [2]),
    (f"{_IN_TAKEN}    return path  # old.is_file()\n", [2]),
    (f"{_IN_TAKEN}    return path  # d.is_dir()\n", [2]),
    (f'{_IN_TAKEN}    return "os.path.exists(p)"\n', [2]),
    (f'{_IN_TAKEN}    return "os.path.lexists(p)"\n', [2]),
    (f'{_IN_TAKEN}    return "os.path.isdir(p)"\n', [2]),
    (f"{_IN_TAKEN}    return disk.exists(copy.path)\n", []),
    (f"{_IN_TAKEN}    return myos.path.exists(path)\n", []),
    (f"{_IN_TAKEN}    return foo.myos.path.exists(path)\n", []),
    (f"{_IN_TAKEN}    return os.extras.exists(path)\n", []),
    (f"{_IN_TAKEN}    return foo.file_exists()\n", []),
    (f'{_IN_TAKEN}    return "myos.path.exists(p)"\n', []),
]


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_STANU_PLIKU)
def test_regula_stanu_pliku_zglasza_stan_sciezki_poza_file_state_a_nie_file_state_ani_metode_z_argumentem(
    tmp_path: Path, text: str, lines: list[int]
) -> None:
    base = _empty_base(tmp_path)
    (tmp_path / "src" / "rozliczenia").mkdir(parents=True)
    (tmp_path / "src" / "rozliczenia" / "kopia.py").write_text(text, encoding="utf-8")

    assert _findings_of(_STATE_RULE, tmp_path, base) == [("src/rozliczenia/kopia.py", line) for line in lines]


@needs_ast_grep
def test_regula_stanu_pliku_zglasza_tylko_src_poza_file_state(tmp_path: Path) -> None:
    base = _empty_base(tmp_path)
    for path in ("src/rozliczenia/file_state.py", "src/rozliczenia/kopia.py", "tests/test_kopii.py", "tools/narzedzie.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("def taken(path):\n    return path.exists()\n", encoding="utf-8")

    assert _findings_of(_STATE_RULE, tmp_path, base) == [("src/rozliczenia/kopia.py", 2)]


# Znane luki reguły ``stan-pliku-poza-file-state`` (tests/fixtures/znane_luki.py): „postać” → dodany plik ``src/``,
# który pyta o stan ścieżki z pominięciem ``file_state``, a mimo to przechodzi przez reguły ast-grep i ruff.
ZNANE_LUKI_STANU_PLIKU: Final[dict[str, str]] = {
    # Po składni nie odróżnić od świadomego ``register.parent.iterdir()`` w ``try``/``except OSError`` z #1249.
    "lista folderu z iterdir": """\
from pathlib import Path


def taken(path: Path) -> bool:
    return path.name in {entry.name for entry in path.parent.iterdir()}
""",
    "os.scandir": """\
import os


def taken(folder: str, name: str) -> bool:
    with os.scandir(folder) as entries:
        return any(entry.name == name for entry in entries)
""",
    "glob": """\
from pathlib import Path


def taken(path: Path) -> bool:
    return any(path.parent.glob(path.name))
""",
    "stat": """\
from pathlib import Path
import stat


def is_folder(path: Path) -> bool:
    return stat.S_ISDIR(path.stat().st_mode)
""",
    "try i except OSError napisane od nowa": """\
from pathlib import Path


def taken(path: Path) -> bool:
    try:
        path.open("rb").close()
    except OSError:
        return False
    return True
""",
    "wywołanie z argumentem": """\
from pathlib import Path


def taken(path: Path) -> bool:
    return path.is_file(follow_symlinks=False)
""",
    "metoda pod inną nazwą": """\
from pathlib import Path


def taken(path: Path) -> bool:
    check = path.exists
    return check()
""",
    "metoda wołana na klasie": """\
from pathlib import Path


def taken(path: Path) -> bool:
    return Path.exists(path)
""",
    "os.path pod aliasem": """\
import os.path as osp


def taken(path: str) -> bool:
    return osp.exists(path)
""",
    "exists z from os.path import": """\
from os.path import exists


def taken(path: str) -> bool:
    return exists(path)
""",
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_reguly_stanu_pliku_przechodza_przez_reguly_ast_grep_i_ruff(tmp_path: Path) -> None:
    """Reguła ``stan-pliku-poza-file-state`` czyta wywołanie ``exists``, ``is_file`` albo ``is_dir`` bez argumentów na
    dowolnym obiekcie, ``exists``, ``lexists``, ``isfile`` i ``isdir`` na ``path`` modułu ``os`` albo atrybutu ``os``
    (także łamane przed kropką) oraz ten sam tekst
    w komentarzu i napisie; metoda pod inną nazwą albo na klasie, ``os.path`` pod aliasem albo z from-importu
    i każda inna droga do stanu ścieżki to znane luki."""

    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (folder := tmp_path / "src" / "rozliczenia").mkdir(parents=True)
    pliki = zapisz(ZNANE_LUKI_STANU_PLIKU, folder)
    zgloszenia = ruff(pliki, sonda=ROOT / "src" / "rozliczenia" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_stanu_pliku_przechodza_przez_reguly_ast_grep_i_ruff")


_ORACLE_RULE = "wlasna-wyrocznia-numeru"
_IN_TEST = "import re\n\n\ndef test_bez_numeru(text, number, texts, order, line):\n"
# Tekst dodanego pliku ``tests/`` → linie, które reguła ``wlasna-wyrocznia-numeru`` zgłasza: własna wyrocznia numeru
# zlecenia z lookbehindem wokół cyfr (``(?<![0-9a-f])`` z 5b2edaf2f9, ``(?<![0-9])`` z cc7e5ced21) w napisie
# i w komentarzu, i wyrażenia bez lookbehindu cyfr, które przepuszcza.
_PROBKI_WYROCZNI_NUMERU: Final[list[tuple[str, list[int]]]] = [
    (_IN_TEST + "    return re.search(rf\"(?<![0-9a-f]){re.escape(number.removeprefix('#'))}(?![0-9a-f])\", text) is not None\n", [5]),
    (_IN_TEST + '    number = re.compile(r"(?<![0-9a-f])9401(?![0-9a-f])")\n', [5]),
    (_IN_TEST + '    number = re.compile(r"(?<![0-9])9401(?![0-9])")\n', [5]),
    (_IN_TEST + '    assert re.search(r"(?<!\\d)9401", text) is None\n', [5]),
    (_IN_TEST + "    assert text  # wzorzec (?<![0-9]) wokół numeru\n", [5]),
    (_IN_TEST + '    assert text  # wzorzec r"(?<!\\d)" wokół numeru\n', [5]),
    (_IN_TEST + "    assert [zawiera_wartosc(text, order.number) for text in texts] == [False, False]\n", []),
    (_IN_TEST + '    FULL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\\\/]")\n', []),
    (_IN_TEST + '    assert "TESTOWA" not in text\n', []),
    (_IN_TEST + '    assert "2026" in text\n', []),
    (_IN_TEST + '    assert re.fullmatch(r"CZAS: ([0-9]+) s", line)\n', []),
]


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_WYROCZNI_NUMERU)
def test_regula_wyroczni_numeru_zglasza_lookbehind_cyfr_w_napisie_i_komentarzu_a_nie_zawiera_wartosc(
    tmp_path: Path, text: str, lines: list[int]
) -> None:
    base = _empty_base(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_numeru.py").write_text(text, encoding="utf-8")

    assert _findings_of(_ORACLE_RULE, tmp_path, base) == [("tests/test_numeru.py", line) for line in lines]


@needs_ast_grep
def test_regula_wyroczni_numeru_zglasza_tylko_tests_poza_plikiem_zapadek(tmp_path: Path) -> None:
    base = _empty_base(tmp_path)
    for path in ("tests/test_numeru.py", "tests/fixtures/pomocnik.py", "tests/test_zapadki.py", "src/rozliczenia/numer.py", "tools/numer.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text('import re\n\nNUMBER = re.compile(r"(?<![0-9])9401")\n', encoding="utf-8")

    assert _findings_of(_ORACLE_RULE, tmp_path, base) == [("tests/fixtures/pomocnik.py", 3), ("tests/test_numeru.py", 3)]


# Znane luki reguły ``wlasna-wyrocznia-numeru`` (tests/fixtures/znane_luki.py): „postać” → dodany plik ``tests/``
# z własną wyrocznią numeru zlecenia, który mimo to przechodzi przez reguły ast-grep i ruff.
ZNANE_LUKI_WYROCZNI_NUMERU: Final[dict[str, str]] = {
    "lookbehind z dwoma ukośnikami w napisie bez r": r'''import re


def test_bez_numeru(text: str) -> None:
    assert re.search("(?<!\\d)94001(?!\\d)", text) is None
''',
    "klasa, w której 0-9 nie stoi zaraz po [": r'''import re


def test_bez_numeru(text: str) -> None:
    assert re.search(r"(?<![a-f0-9])94001(?![a-f0-9])", text) is None
''',
    r"\b wokół numeru": r'''import re


def test_bez_numeru(text: str) -> None:
    assert re.search(r"\b94001\b", text) is None
''',
    # W ``tests/`` stoją poprawne ``"2026" not in`` i ``"999999" not in``.
    "literał numeru przed not in": """\
def test_bez_numeru(text: str) -> None:
    assert "94001" not in text
""",
    "numer ze zmiennej": """\
def test_bez_numeru(text: str, number: str) -> None:
    assert number not in text
""",
    "str.find": """\
def test_bez_numeru(text: str) -> None:
    assert text.find("94001") == -1
""",
    "count": """\
def test_bez_numeru(text: str) -> None:
    assert text.count("94001") == 0
""",
    "re.search na samym numerze": """\
import re


def test_bez_numeru(text: str) -> None:
    assert re.search("94001", text) is None
""",
    "lookahead bez lookbehindu": r'''import re


def test_bez_numeru(text: str) -> None:
    assert re.search(r"94001(?!\d)", text) is None
''',
    "lookbehind złożony w kilku liniach": r'''import re

NUMBER = re.compile(
    r"(?<!"
    r"\d)94001"
)


def test_bez_numeru(text: str) -> None:
    assert NUMBER.search(text) is None
''',
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_reguly_wyroczni_numeru_przechodza_przez_reguly_ast_grep_i_ruff(tmp_path: Path) -> None:
    """Reguła ``wlasna-wyrocznia-numeru`` czyta w napisie albo komentarzu tekst ``(?<!``, po nim opcjonalnie ``[``,
    a po nim ``\\d`` z jednym ukośnikiem albo ``0-9``; lookbehind złożony z kilku literałów, ``\\d`` z dwoma ukośnikami
    w napisie bez ``r``, klasa z ``0-9`` nie zaraz po ``[``, ``\\b``, sam lookahead i każda wyrocznia bez lookbehindu to
    znane luki."""

    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (folder := tmp_path / "tests").mkdir()
    pliki = zapisz(ZNANE_LUKI_WYROCZNI_NUMERU, folder)
    zgloszenia = ruff(pliki, sonda=ROOT / "tests" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_wyroczni_numeru_przechodza_przez_reguly_ast_grep_i_ruff")


_THREADS_RULE = "watki-workera"
_IN_THREADS = "import threading\n\n\ndef test_watki(monkeypatch, thread, threads, pool, counted, before, work, asking):\n"
# Tekst dodanego pliku ``tests/`` → linie, które reguła ``watki-workera`` zgłasza: wątki procesu workera poza
# ``linie_watkow``, jak ``monkeypatch.setattr(threading.Thread, "start", counted)`` z 0e304aec7, w każdej postaci, którą
# reguła czyta (wyrażenie pośrednie przed przecinkiem, węzeł zaczynający się napisem po nim, odstępy i łamanie wokół
# kropki), i pytania o wątki przez ``linie_watkow`` albo o inne nazwy, które przepuszcza.
_PROBKI_WATKOW: Final[list[tuple[str, list[int]]]] = [
    (f"{_IN_THREADS}    start = threading.Thread.start\n", [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, "start", counted)\n', [5]),
    (f"{_IN_THREADS}    monkeypatch.setattr(threading.Thread, 'start', counted)\n", [5]),
    (f"{_IN_THREADS}    threading.Thread.start = counted\n", [5]),
    (f"{_IN_THREADS}    assert threading.active_count() == before\n", [5]),
    (f"{_IN_THREADS}    threading.Thread.start(thread)\n", [5]),
    (f"{_IN_THREADS}    assert active_count() == before\n", [5]),
    (f"{_IN_THREADS}    Thread.start(thread)\n", [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(\n        threading.Thread,\n        "start",\n        counted,\n    )\n', [7]),
    # Para Thread i "start" w każdym ciągu wyrażeń, nie tylko w argumentach (korpus z node-types.json gramatyki).
    (f'{_IN_THREADS}    monkeypatch.setattr(Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    targets = [(threading.Thread, "start")]\n', [5]),
    (f'{_IN_THREADS}    patched = pool[threading.Thread, "start"]\n', [5]),
    (f'{_IN_THREADS}    assert threading.Thread, "start"\n', [5]),
    (f"{_IN_THREADS}    assert before  # threading.active_count() przed\n", [5]),
    (f'{_IN_THREADS}    """Podmienia Thread.start na liczący."""\n', [5]),
    (f"{_IN_THREADS}    code = \"monkeypatch.setattr(threading.Thread, 'start', f)\"\n", [5]),
    # Węzeł dowolnego rodzaju przed przecinkiem, którego tekst kończy się słowem Thread (#1879 r1 W1).
    (f'{_IN_THREADS}    monkeypatch.setattr(pool or threading.Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(pool if before else threading.Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(cls := threading.Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(lambda: threading.Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(pool is threading.Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(-threading.Thread, "start", counted)\n', [5]),
    (f'{_IN_THREADS}    patches = {{pool: threading.Thread, "start": counted}}\n', [5]),
    (f'{_IN_THREADS}    patched = pool[threading.Thread, "start":]\n', [5]),
    # Węzeł po przecinku, który zaczyna się napisem start.
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, "start" "", counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, "start".strip(), counted)\n', [5]),
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, "start"[:], counted)\n', [5]),
    # Odstępy i łamanie wokół kropki, także na linii z noqa, którą ruff przepuszcza.
    (f"{_IN_THREADS}    assert threading. active_count() == before  # noqa: TID251 - próbka\n", [5]),
    (f"{_IN_THREADS}    start = threading. Thread.start  # noqa: TID251 - próbka\n", [5]),
    (f"{_IN_THREADS}    start = (threading\n        .Thread.start)\n", [5]),
    (f"{_IN_THREADS}    count = (threading\n        .active_count())\n", [5]),
    (f"{_IN_THREADS}    since = new_line()\n", []),
    (f"{_IN_THREADS}    assert wait_for(lambda: threads_since(since) == [], seconds=10)\n", []),
    (f"{_IN_THREADS}    with started_threads() as started:\n        pass\n", []),
    (f"{_IN_THREADS}    asking.start()\n", []),
    (f"{_IN_THREADS}    super().start()\n", []),
    (f"{_IN_THREADS}    thread_started: bool = False  # through ``threads.Thread`` of ``RunHost`` (``ModelThread.start``)\n", []),
    (f"{_IN_THREADS}    for index, thread in enumerate(threads):\n        pass\n", []),
    (f"{_IN_THREADS}    began = threading.Thread.started_at\n", []),
    (f"{_IN_THREADS}    threading.Thread.start_soon(work)\n", []),
    (f"{_IN_THREADS}    assert pool._active_count() == 0\n", []),
    (f"{_IN_THREADS}    assert threading.active_counts() == 0\n", []),
    (f"{_IN_THREADS}    ModelThread.start(thread)\n", []),
    (f'{_IN_THREADS}    monkeypatch.setattr(MyThread, "start", counted)\n', []),
    (f'{_IN_THREADS}    assert threading.Thread == "start"\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, r"start", counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(pool.MyThread, "start", counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(Threads, "start", counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(pool.Threads, "start", counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, "started", counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(threading.Thread, prefix + "start", counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(MyThread, "start".strip(), counted)\n', []),
    (f'{_IN_THREADS}    monkeypatch.setattr(Threads, "start".strip(), counted)\n', []),
    (f"{_IN_THREADS}    restart = threading.Thread.restart\n", []),
    (f"{_IN_THREADS}    start = threading.Threads.start\n", []),
    (f"{_IN_THREADS}    def active_count(self):\n        return 0\n", []),
    (f'{_IN_THREADS}    names = {{threading.Thread: "start"}}\n', []),
    # Wzorzec case nie tworzy wartości, ale tekst ma postać pary; zgłasza go reguła, tak jak zapadka.
    (f'{_IN_THREADS}    match pool:\n        case [threading.Thread, "start"]:\n            pass\n', [6]),
    (f"{_IN_THREADS}    assert pool  # pool._active_count() == 0\n", []),
    (f"{_IN_THREADS}    assert pool  # Thread.started_at przed\n", []),
    (f'{_IN_THREADS}    assert pool  # setattr(MyThread, "start", f)\n', []),
]


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_WATKOW)
def test_regula_watkow_zglasza_watki_workera_poza_linie_watkow_a_nie_linie_watkow_ani_inne_nazwy(
    tmp_path: Path, text: str, lines: list[int]
) -> None:
    base = _empty_base(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_watkow.py").write_text(text, encoding="utf-8")

    assert _findings_of(_THREADS_RULE, tmp_path, base) == [("tests/test_watkow.py", line) for line in lines]


@needs_ast_grep
def test_regula_watkow_zglasza_tylko_tests_poza_linie_watkow_i_probkami_zakazu(tmp_path: Path) -> None:
    base = _empty_base(tmp_path)
    for path in (
        "tests/fixtures/linie_watkow.py",
        "tests/test_zapadki.py",
        "tests/test_zakazy_ruff.py",
        "tests/test_watkow.py",
        "src/rozliczenia/watki.py",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("import threading\nstart = threading.Thread.start\n", encoding="utf-8")

    assert _findings_of(_THREADS_RULE, tmp_path, base) == [("tests/test_watkow.py", 2)]


# Znane luki reguły ``watki-workera`` (tests/fixtures/znane_luki.py): „postać” → dodany plik ``tests/``, który pyta
# o wątki procesu workera poza ``linie_watkow``, a mimo to przechodzi przez reguły ast-grep i ruff.
ZNANE_LUKI_WATKOW: Final[dict[str, str]] = {
    # #1297 i #1308 dodały tę postać w scalonych PR-ach bez rundy FAIL, więc reguła na niej dałaby alarm na historii.
    "threading.enumerate przed i po": """\
import threading


def test_bez_nowych_watkow() -> None:
    before = set(threading.enumerate())
    assert set(threading.enumerate()) == before
""",
    "sys._current_frames": """\
import sys


def test_bez_nowych_watkow() -> None:
    assert len(sys._current_frames()) == 1
""",
    "threading._active": """\
import threading


def test_bez_nowych_watkow() -> None:
    assert len(threading._active) == 1
""",
    "setattr z klasą wątku w zmiennej": """\
import threading

import pytest


def test_liczy_starty(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_class = threading.Thread
    monkeypatch.setattr(thread_class, "start", lambda self: None)
""",
    "podmiana Thread.run": """\
import threading

import pytest


def test_liczy_starty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threading.Thread, "run", lambda self: None)
""",
    "podmiana Thread.__init__": """\
import threading

import pytest


def test_liczy_starty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threading.Thread, "__init__", lambda self, *args, **kwargs: None)
""",
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_reguly_watkow_przechodza_przez_reguly_ast_grep_i_ruff(tmp_path: Path) -> None:
    """Reguła ``watki-workera`` czyta tekst węzłów, nie ich rodzaj: wywołanie, którego funkcja kończy się słowem
    ``active_count``, atrybut ``start`` na wyrażeniu kończącym się słowem ``Thread``, napis ``start`` zaraz po przecinku
    za węzłem kończącym się słowem ``Thread`` (sam albo jako początek węzła po przecinku) oraz ten sam tekst
    w komentarzu i napisie; ``threading.enumerate``, ``sys._current_frames``, ``threading._active``, klasa wątku
    w zmiennej i podmiana ``run`` albo ``__init__`` to znane luki."""

    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (folder := tmp_path / "tests").mkdir()
    pliki = zapisz(ZNANE_LUKI_WATKOW, folder)
    zgloszenia = ruff(pliki, sonda=ROOT / "tests" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_watkow_przechodza_przez_reguly_ast_grep_i_ruff")


_DOC_RULE = "odczyt-docstringu"
_ARGPARSE = "import argparse\n\n"
_PROBKI_ODCZYTU_DOCSTRINGU: Final[list[tuple[str, list[int]]]] = [
    (f"{_ARGPARSE}parser = argparse.ArgumentParser(description=__doc__)\n", [3]),
    (f"{_ARGPARSE}parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)\n", [3, 3]),
    ('import limit_rund\n\nRULES = (limit_rund.__doc__ or "").partition("Zasady")[2]\n', [3]),
    ("import limit_rund\n\nRULES = (\n    limit_rund\n    .__doc__\n)\n", [5]),
    ('def f() -> None:\n    pass\n\n\nf.__doc__ = "Opis."\n', [5]),
    (f'{_ARGPARSE}OPIS = "Opis narzędzia."\nparser = argparse.ArgumentParser(description=OPIS)\n', []),
    ('NAME = "__doc__"\n', []),
    ('"""Docstring, który mówi o __doc__."""\n', []),
]


@needs_ast_grep
@pytest.mark.parametrize(("text", "lines"), _PROBKI_ODCZYTU_DOCSTRINGU)
def test_regula_odczytu_docstringu_zglasza_kazde_doc_a_nie_stala_opis_ani_napis(tmp_path: Path, text: str, lines: list[int]) -> None:
    base = _empty_base(tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "narzedzie.py").write_text(text, encoding="utf-8")

    assert _findings_of(_DOC_RULE, tmp_path, base) == [("tools/narzedzie.py", line) for line in lines]


@needs_ast_grep
def test_regula_odczytu_docstringu_obejmuje_kazdy_plik_pythona_repo(tmp_path: Path) -> None:
    base = _empty_base(tmp_path)
    paths = (
        "narzedzie.py",
        "src/rozliczenia/modul.py",
        "tests/test_modulu.py",
        "tools/lib/modul.py",
        "tools/ci/skrypt.py",
        ".agents/skills/verify-x/scripts/skrypt.py",
        "tools/lib/modul.pyi",
        "tools/skrypt.py3",
    )
    for path in paths:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("TEXT = __doc__\n", encoding="utf-8")

    assert sorted(_findings_of(_DOC_RULE, tmp_path, base)) == sorted((path, 1) for path in paths)


# Znane luki reguły ``odczyt-docstringu`` (tests/fixtures/znane_luki.py): „klasa: postać” → dodany plik ``tools/``,
# który czyta docstring modułu, a mimo to przechodzi przez reguły ast-grep i ruff.
ZNANE_LUKI_ODCZYTU_DOCSTRINGU: Final[dict[str, str]] = {
    "odbicie po nazwie atrybutu: getattr": 'import limit_rund\n\nRULES = getattr(limit_rund, "__doc__")\n',
    "odbicie po nazwie atrybutu: vars": 'import limit_rund\n\nRULES = vars(limit_rund)["__doc__"]\n',
    "biblioteka czyta za kod: inspect.getdoc": "import inspect\n\nimport limit_rund\n\nRULES = inspect.getdoc(limit_rund)\n",
    "biblioteka czyta za kod: pydoc": "import pydoc\n\nimport limit_rund\n\nRULES = pydoc.getdoc(limit_rund)\n",
    "docstring z drzewa składni": (
        "import ast\nfrom pathlib import Path\n\n"
        'RULES = ast.get_docstring(ast.parse(Path("tools/lib/limit_rund.py").read_text(encoding="utf-8")))\n'
    ),
}


@needs_ast_grep
@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_znane_luki_reguly_odczytu_docstringu_przechodza_przez_reguly_ast_grep_i_ruff(tmp_path: Path) -> None:
    from tests.fixtures.znane_luki import assert_znane_luki, ruff, zapisz

    base = _empty_base(tmp_path)
    (folder := tmp_path / "tools").mkdir()
    pliki = zapisz(ZNANE_LUKI_ODCZYTU_DOCSTRINGU, folder)
    zgloszenia = ruff(pliki, sonda=ROOT / "tools" / "test_sonda_luki.py")
    opisy = {plik.relative_to(tmp_path).as_posix(): opis for opis, plik in pliki.items()}
    for finding in syntax_rules(tmp_path, base):
        zgloszenia[opisy[finding.path]].append(f"{finding.path}:{finding.line}: {finding.rule}")

    assert_znane_luki(zgloszenia, "tests/test_zapadki.py::test_znane_luki_reguly_odczytu_docstringu_przechodza_przez_reguly_ast_grep_i_ruff")


# Reguła z zapadki → plik z jej ignores: (części ścieżki, nie napis z ``/``, bo napis ścieżki w pliku testu jest
# zależnością testu w grafie wpływu zmiany, ``tools/lib/wplyw_zmiany.py``), nowa nazwa
# w jej zakresie, tekst z jej formą i linia formy. Zapadka biegła w CI na całym ``tests/`` i ``src/`` od pustego drzewa
# (``test_zapadki_nie_zglaszaja_zadnej_linii_testow``), więc reguła z niej biegnie na całym drzewie.
_PRZENIESIENIA: Final[dict[str, tuple[tuple[str, ...], str, str, int]]] = {
    "stan-pliku-poza-file-state": (("src", "rozliczenia", "file_state.py"), "src/rozliczenia/kopia.py", "def taken(path):\n    return path.exists()\n", 2),
    "watki-workera": (("tests", "fixtures", "linie_watkow.py"), "tests/test_watkow.py", "import threading\nstart = threading.Thread.start\n", 2),
    "wlasna-wyrocznia-numeru": (("tests", "test_zapadki.py"), "tests/test_numeru.py", 'import re\n\nNUMBER = re.compile(r"(?<![0-9])9401")\n', 3),
}


@windows_without_ast_grep
@pytest.mark.parametrize("rule", sorted(_PRZENIESIENIA))
def test_regula_z_zapadki_na_calym_drzewie_zglasza_plik_przeniesiony_spoza_ignores_a_linie_dodane_nie(tmp_path: Path, rule: str) -> None:
    """Plik z ``ignores:`` reguły przeniesiony pod nową nazwę w jej zakresie (``git mv``) nie ma linii dodanych, więc
    reguła na liniach dodanych go nie widzi; reguła całego drzewa widzi formę bez względu na to, jak trafiła do pliku."""

    old, new, text, line = _PRZENIESIENIA[rule]
    base = _committed(tmp_path, {"/".join(old): text})
    _git(tmp_path, "mv", "/".join(old), new)

    assert [(finding.path, finding.line) for finding in whole_tree_rules(tmp_path) if finding.rule == rule] == [(new, line)]
    assert _findings_of(rule, tmp_path, base) == []
