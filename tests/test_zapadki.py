"""Zapadki: reguły, które w ``tools/szybko.py`` padają tylko na liniach dodanych przez zmianę.

W CI ``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py`` uruchamia każdą zapadkę
poza regułami ast-grep z bazą w pustym drzewie, więc tam zapadka zakazuje swojej formy w całym ``tests/`` i ``src/``.
Formę, która ma jeszcze stare wystąpienia, zapadka dostaje dopiero wtedy, gdy zmiana je usunie albo poprawi tamten test;
reguła ast-grep dostaje ją od razu, bo zgłasza tylko linie dodane od prawdziwej bazy zmiany.

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

import importlib.util
import os
from pathlib import Path
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

# Lookbehind wokół cyfr numeru, jak ``(?<![0-9a-f])`` w 5b2edaf2f9 i ``(?<![0-9])`` w cc7e5ced21.
_ORDER_NUMBER_ORACLE = re.compile(r"\(\?<!\[?(?:\\d|0-9)")
_ORDER_NUMBER_HELPER = (
    "własna wyrocznia wycieku numeru zlecenia: sprawdź tekst przez zawiera_wartosc z tests/fixtures/wyciek.py, która"
    " pyta strażnika reguły danych (ForbiddenValues.guard), bo cztery własne wzorce z rzędu rozjechały się ze strażnikiem,"
    " a jeden zaczerwienił main, gdy losowy hex HMAC zawierał numer"
)

# Stan ścieżki bez file_state, jak ``copy.path.exists()`` w ea69c32bea i ``old.is_file()`` w 5f4e134ba5.
_BARE_FILE_STATE = re.compile(r"\.(?:exists|is_file|is_dir)\(\s*\)|\bos\.path\.(?:exists|lexists|isfile|isdir)\(")
_FILE_STATE = "src/rozliczenia/file_state.py"
_FILE_STATE_HELPER = (
    "stan pliku poza file_state: zapytaj src/rozliczenia/file_state.py (file_state, path_state, path_taken, a o wpis"
    " folder_entries entry_kind), które rozróżnia brak od pliku niedostępnego (OneDrive, folder bez dostępu), bo gołe"
    " .exists() albo .is_file() rzuca PermissionError na Pythonie 3.11–3.13 i odpowiada „brak” na 3.14 (#729, #1190)"
)

# Wątki procesu workera pytest poza ``linie_watkow``, jak ``monkeypatch.setattr(threading.Thread, "start", counted)``
# w 0e304aec7 (#633, czerwony main: wątki innych testów policzone jako wątki sprawdzenia).
_WORKER_THREADS = re.compile(r"\bactive_count\(|\bThread\.start\b|\bThread,\s*[\"']start[\"']")
_THREAD_LINES = "tests/fixtures/linie_watkow.py"
_THREAD_LINES_HELPER = (
    "wątki procesu workera pytest poza linią testu: zapytaj tests/fixtures/linie_watkow.py (new_line i threads_since o"
    " wątki, które żyją, started_threads o wątki uruchomione w bloku), bo w workerze żyją też wątki wcześniejszych testów"
    " i timer pytest-timeout"
)

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

# Pliki, którym wolno parsować Pythona ręcznie: stan z 12.11.2026 (23 pliki); wpis maleje z każdym usuniętym plikiem.
# Jeden napis z odstępami, bo graf wyboru testów (``tools/lib/wplyw_zmiany.py``) bierze ścieżkę z napisu testu za jego
# zależność, a zapadki i tak biegną przy każdej zmianie (``ZAPADKI`` w ``tools/szybko.py``).
PARSERS = frozenset(
    """
    .agents/skills/verify-centrum-rozliczen/scripts/centrum_self_test.py
    .agents/skills/verify-centrum-rozliczen/scripts/sub_features.py
    tests/fixtures/skladnia.py
    tests/test_decyzje_na_faktach.py
    tests/test_eksplorator_w_procesie.py
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
    tools/lib/kroki_skilli.py
    tools/lib/niestabilne_testy.py
    tools/lib/rozjazd_modelu.py
    tools/lib/wplyw_zmiany.py
    tools/mutacje_zmiany.py
    tools/rownowaznosc.py
    """.split()
)
PARSER_FOLDERS = ("tests", "tools", ".agents/skills")
_PARSER_CALL = re.compile(r"(?<![\w.])(?:ast\.(?:parse|walk)\(|tokenize\.)")
_NEW_PARSER = (
    "nowy plik z ręcznym parserem Pythona (ast.parse, ast.walk, tokenize): nazwij korzeń poprawki i napraw go na"
    " najwyższym szczeblu z sekcji „Korzeń i chwast” skilla .agents/skills/przeglad/SKILL.md: (a) jedna droga i jeden"
    " właściciel, (b) typ albo reguła ruff (banned-api TID251 z msg „użyj X” w pyproject.toml), (c) test zachowania,"
    " (d) dopiero zapadka"
    " w tests/test_zapadki.py; plik, który mimo to parsuje, dopisz do PARSERS w tests/test_zapadki.py z powodem w"
    " opisie PR"
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


def order_number_oracle(line: str) -> bool:
    """Czy linia testu sprawdza wyciek numeru zlecenia własną definicją zamiast ``zawiera_wartosc``.

    Łapie tylko napis ``(?<!``, po nim opcjonalnie ``[``, a po nim ``\\d`` z jednym ukośnikiem albo ``0-9``: tak zaczyna
    się ``(?<![0-9a-f])``, ``(?<![0-9])``, ``(?<!0-9`` i ``r"(?<!\\d)"``. Postacie, których nie łapie ani zapadka, ani
    ruff, są próbkami ``ZNANE_LUKI`` tego pliku. Każda forma ma 0 trafień, gdy każda linia ``tests/`` jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    return _ORDER_NUMBER_ORACLE.search(line) is not None


def order_number_oracles(root: Path, base: str) -> list[str]:
    """Linie ``tests/`` poza tym plikiem, które zmiana od ``base`` dodaje z ``order_number_oracle``, z komunikatem."""

    return [
        f"{path}:{number}: {_ORDER_NUMBER_HELPER}"
        for path, number, line in odpalenia_ast_grep.added_lines(root, base, "tests")
        if path != "tests/test_zapadki.py" and order_number_oracle(line)
    ]


def test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert order_number_oracles(ROOT, base) == []


def bare_file_state(line: str) -> bool:
    """Czy linia ``src/`` pyta o stan ścieżki z pominięciem ``file_state``.

    Łapie tylko ``.exists()``, ``.is_file()`` i ``.is_dir()`` bez argumentów, także ze spacją w nawiasie (na ``Path`` i
    na wpisie ``os.DirEntry``), oraz ``os.path.exists(``, ``os.path.lexists(``, ``os.path.isfile(`` i
    ``os.path.isdir(``, także w komentarzu i napisie. Postacie, których nie łapie ani zapadka, ani ruff, są próbkami
    ``ZNANE_LUKI`` tego pliku.
    Żadna forma nie trafia w dzisiejsze ``src/``, gdy każda jego linia jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    return _BARE_FILE_STATE.search(line) is not None


def file_state_bypasses(root: Path, base: str) -> list[str]:
    """Linie ``src/`` poza ``file_state.py``, które zmiana od ``base`` dodaje z ``bare_file_state``, z komunikatem."""

    return [
        f"{path}:{number}: {_FILE_STATE_HELPER}"
        for path, number, line in odpalenia_ast_grep.added_lines(root, base, "src")
        if path != _FILE_STATE and bare_file_state(line)
    ]


def test_stan_pliku_w_src_tylko_przez_file_state() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert file_state_bypasses(ROOT, base) == []


def test_zapadka_stanu_pliku_widzi_tylko_src_poza_file_state(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, *author, "commit", "-q", "--allow-empty", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path in (_FILE_STATE, "src/rozliczenia/kopia.py", "tests/test_kopii.py", "tools/narzedzie.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("def taken(path):\n    return path.exists()\n", encoding="utf-8")

    found = file_state_bypasses(tmp_path, base)

    assert found == [f"src/rozliczenia/kopia.py:2: {_FILE_STATE_HELPER}"]


@pytest.mark.parametrize(
    "line",
    [
        "    taken = copy.path.exists()",
        "    return old.name if old.is_file() else None",
        "    if STATIC_DIRECTORY.is_dir():",
        "    for entry in entries if entry.is_dir() and _YEAR_FOLDER.fullmatch(entry.name)",
        "    return os.path.exists(excel_lock_file(path))",
        "            collective_file_exists=os.path.isfile(path),",
        "    if not path.exists( ):",
        "    taken = os.path.lexists(link)",
        "    if os.path.isdir(folder):",
    ],
)
def test_zapadka_lapie_stan_pliku_poza_file_state(line: str) -> None:
    assert bare_file_state(line)


@pytest.mark.parametrize(
    "line",
    [
        '    return old.name if file_state(old) == "file" else None',
        "    if path_taken(self._state):",
        '    present = [period_place_label(place) for place in places if observed.exists(place)]',
        "                taken = disk.exists(copy.path)",
    ],
)
def test_zapadka_przepuszcza_file_state_i_metody_domeny(line: str) -> None:
    assert not bare_file_state(line)


@pytest.mark.parametrize(
    "line",
    [
        'return re.search(rf"(?<![0-9a-f]){re.escape(number.removeprefix(\'#\'))}(?![0-9a-f])", text) is not None',
        'number = re.compile(r"(?<![0-9a-f])9401(?![0-9a-f])")',
        'number = re.compile(r"(?<![0-9])9401(?![0-9])")',
        r'assert re.search(r"(?<!\d)9401", text) is None',
    ],
)
def test_zapadka_lapie_wlasna_wyrocznie_numeru_zlecenia(line: str) -> None:
    assert order_number_oracle(line)


@pytest.mark.parametrize(
    "line",
    [
        "assert [zawiera_wartosc(text, order.number) for text in texts] == [False, False]",
        'FULL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\\\/]")',
        'assert "TESTOWA" not in text',
        'assert "2026" in text',
        'assert re.fullmatch(r"CZAS: ([0-9]+) s", line)',
    ],
)
def test_zapadka_przepuszcza_zawiera_wartosc_i_inne_wyrazenia(line: str) -> None:
    assert not order_number_oracle(line)


def worker_threads(line: str) -> bool:
    """Czy linia testu pyta o wątki procesu workera pytest z pominięciem ``linie_watkow``.

    Łapie tylko ``active_count(`` (także ``threading.active_count(``), ``Thread.start`` jako całą nazwę (odczyt,
    podmiana i wywołanie ``threading.Thread.start``) oraz ``Thread,`` i napis ``"start"`` albo ``'start'``
    (``monkeypatch.setattr(threading.Thread, "start", …)``), także w komentarzu, docstringu i napisie z kodem procesu
    potomnego. Postacie, których nie łapie ani zapadka, ani ruff, są próbkami ``ZNANE_LUKI`` tego pliku.
    W kodzie ``threading.Thread.start`` i ``threading.active_count`` odrzuca wcześniej, także w CI, ruff (``TID251`` w
    ``tests/ruff.toml``), ale nie na linii z ``# noqa: TID251`` ani w napisie, więc zapadka zostaje.
    Żadna forma nie trafia w dzisiejsze ``tests/``, gdy każda jego linia jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    return _WORKER_THREADS.search(line) is not None


def worker_thread_counts(root: Path, base: str) -> list[str]:
    """Linie ``tests/`` poza ``linie_watkow.py``, tym plikiem i ``test_zakazy_ruff.py`` (próbki zakazu ruff tych samych
    form), które zmiana od ``base`` dodaje z ``worker_threads``."""

    return [
        f"{path}:{number}: {_THREAD_LINES_HELPER}"
        for path, number, line in odpalenia_ast_grep.added_lines(root, base, "tests")
        if path not in {_THREAD_LINES, "tests/test_zapadki.py", "tests/test_zakazy_ruff.py"} and worker_threads(line)
    ]


def test_watki_testu_tylko_przez_linie_watkow() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert worker_thread_counts(ROOT, base) == []


def test_zapadka_watkow_widzi_tylko_tests_poza_linie_watkow(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, *author, "commit", "-q", "--allow-empty", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path in (
        _THREAD_LINES,
        "tests/test_zapadki.py",
        "tests/test_zakazy_ruff.py",
        "tests/test_watkow.py",
        "src/rozliczenia/watki.py",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("import threading\nstart = threading.Thread.start\n", encoding="utf-8")

    found = worker_thread_counts(tmp_path, base)

    assert found == [f"tests/test_watkow.py:2: {_THREAD_LINES_HELPER}"]


@pytest.mark.parametrize(
    "line",
    [
        "    start = threading.Thread.start",
        '    monkeypatch.setattr(threading.Thread, "start", counted)',
        "    monkeypatch.setattr(threading.Thread, 'start', counted)",
        "threading.Thread.start = counted",
        "    assert threading.active_count() == before",
        "        threading.Thread.start(thread)",
    ],
)
def test_zapadka_lapie_watki_workera_poza_linie_watkow(line: str) -> None:
    assert worker_threads(line)


@pytest.mark.parametrize(
    "line",
    [
        "    since = new_line()",
        "    assert wait_for(lambda: threads_since(since) == [], seconds=10)",
        "    with started_threads() as started:",
        "        asking.start()",
        "        super().start()",
        "    thread_started: bool = False  # through ``threads.Thread`` of ``RunHost`` (``ModelThread.start``)",
        "    for index, thread in enumerate(threads):",
        # Granice całej nazwy: inna nazwa, która zaczyna się od ``start`` albo kończy na ``active_count``.
        "    began = threading.Thread.started_at",
        "    threading.Thread.start_soon(work)",
        "    assert pool._active_count() == 0",
    ],
)
def test_zapadka_przepuszcza_linie_watkow_i_inne_watki(line: str) -> None:
    assert not worker_threads(line)


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
        "        self._read_order(",
        "        page,",
        "    return _checked(  ",
        "        response = _checked(page, (",
        "    return _checked(  # lista zleceń",
        "    return [",
        "    statuses = [  # odpowiedzi kolejnych stron",
        # Odstęp z ``#`` w napisie, a linia kończy się przecinkiem albo nawiasem (#1378 r1).
        '            "strona #1",',
        '    return _checked(f"lista #{number}", (',
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
    "komentarz-w-src": "wyraź lepszą nazwą albo testem",
    "kotwica-konca-linii": "użyj \\r?$ zamiast $",
    "lokator-tytulu-okna": "użyj settings_title(page)",
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
    także z ``severity: off`` w pliku, i wbudowane reguły o dyrektywie ``ast-grep-ignore``: regułę wyłącza tylko
    usunięcie jej pliku. Postacie, których nie łapie ani reguła, ani ruff, są próbkami ``ZNANE_LUKI`` tego pliku.
    """

    if not ast_grep_rules(config):
        return []
    return odpalenia_ast_grep.on_added_lines(root, base, ("--config", str(config)), ast_grep)


def syntax_rule_findings(root: Path, base: str) -> list[str]:
    return [f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in syntax_rules(root, base)]


def test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert syntax_rule_findings(ROOT, base) == []


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

    return sorted(
        f"{rule['id']}: reguła bez pola files: obejmuje każdy plik repozytorium; dopisz files: z globami plików, w"
        " których obowiązuje (np. src/**/*.py albo .agents/skills/**/*.py), a wyjątki w ignores:"
        for rule in _ast_grep_rule_documents(config)
        if not rule.get("files")
    )


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
@pytest.mark.parametrize(
    ("text", "rules"),
    [
        ("x = 1  # ast-grep-ignore\n", ["no-suppress-all", "unused-suppression"]),
        ("x = 1  # ast-grep-ignore: zakazane-wywolanie\n", ["unused-suppression"]),
        ("zakazane()  # ast-grep-ignore: zakazane-wywolanie\n", []),
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


_DARWIN = 'import sys\n\nif sys.platform == "darwin":\n    x: int = "a"  # type: ignore'
_NOT_TYPE_CHECKING = "from typing import TYPE_CHECKING\n\nif not TYPE_CHECKING:\n    "


@needs_ast_grep
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
        ("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n# fmt: off\nx = 1  # pragma: no cover\n", [1, 2, 3, 4]),
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
    ],
)
def test_komentarz_w_src_przechodzi_tylko_jako_tlumienie_w_gramatyce_reguly(tmp_path: Path, text: str, lines: list[int]) -> None:
    base = _src_sample(tmp_path, text)

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [
        (line, "komentarz-w-src") for line in lines
    ]


@needs_ast_grep
def test_komentarz_w_src_czyta_pliki_py_pyi_i_py3_a_pomija_pyw_i_plik_bez_rozszerzenia(tmp_path: Path) -> None:
    """Granica zbioru plików reguły: ``files:`` ma globy ``.py``, ``.pyi`` i ``.py3``, więc ``.pyw`` i skrypt Pythona
    bez rozszerzenia przechodzą z komentarzem prozy; gdy reguła zacznie je czytać, ten test każe przesunąć granicę."""

    base = _empty_base(tmp_path)
    names = ("a.py", "pakiet/b.py", "c.pyi", "d.py3", "e.pyw", "skrypt")
    for name in names:
        (tmp_path / "src" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / name).write_text("#!/usr/bin/env python3\nx = 1\n", encoding="utf-8")

    assert [finding.path for finding in syntax_rules(tmp_path, base)] == sorted(f"src/{name}" for name in names[:4])


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
    "dyrektywa ast-grep-ignore: nazwa tej reguły i proza w komentarzu obok kodu": (
        "x = 1  # ast-grep-ignore: komentarz-w-src (wyjaśnienie obok kodu)\n"
    ),
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
}
_PATTERN = "import re\n\nLINE = "
# Reguła powrotu → (tekst dodanego pliku w jej zakresie, linie, które zgłasza): postać z powrotu, którą reguła łapie
# (#1584 W1 r1), i postać po poprawce, którą przepuszcza.
_PROBKI_REGUL_POWROTOW: Final[list[tuple[str, str, list[int]]]] = [
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE \\| test .*$")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"(?m)^" + r"PONOWIENIE$")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.search(rf"{{LINE}}$", "")\n', [3]),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE\\r?$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"PONOWIENIE\\s*$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}re.compile(r"cena w \\$")\n', []),
    ("kotwica-konca-linii", f'{_PATTERN}"PONOWIENIE$"\n', []),
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
    "test_stan_pliku_w_src_tylko_przez_file_state": {
        # Po linii nie odróżnić od świadomego ``register.parent.iterdir()`` w ``try``/``except OSError`` z #1249.
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
        "wywołanie rozbite na dwie linie": """\
from pathlib import Path


def taken(path: Path) -> bool:
    return path.exists(
    )
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
    },
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
    "test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc": {
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
    },
    "test_watki_testu_tylko_przez_linie_watkow": {
        # #1297 i #1308 dodały tę postać w scalonych PR-ach bez rundy FAIL, więc zapadka na niej dałaby alarm na historii.
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
        "setattr rozbity na kilka linii": """\
import threading

import pytest


def test_liczy_starty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda self: None,
    )
""",
    },
}

# Test zapadki → folder repozytorium, w którym zapadka szuka, i jej sprawdzenie dodanych linii.
_ZAPADKI: Final = {
    "test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo": ("src/rozliczenia", syntax_rule_findings),
    "test_stan_pliku_w_src_tylko_przez_file_state": ("src/rozliczenia", file_state_bypasses),
    "test_odpowiedz_nawigacji_karty_w_src_nie_jest_odrzucona": ("src/rozliczenia", navigation_drops),
    "test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc": ("tests", order_number_oracles),
    "test_watki_testu_tylko_przez_linie_watkow": ("tests", worker_thread_counts),
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

    assert [(finding.line, finding.rule) for finding in syntax_rules(tmp_path, base)] == [(line, "lokator-tytulu-okna") for line in lines]


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
