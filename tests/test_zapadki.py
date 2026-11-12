"""Zapadki: reguły, które w ``tools/szybko.py`` padają tylko na liniach dodanych przez zmianę.

W CI ``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py`` uruchamia każdą zapadkę z
bazą w pustym drzewie, więc tam zapadka zakazuje swojej formy w całym ``tests/`` i ``src/``. Formę, która ma jeszcze
stare wystąpienia, zapadka dostaje dopiero wtedy, gdy zmiana je usunie albo poprawi tamten test.

Bazę zmiany daje zmienna ``MAXIMISEART_ZAPADKA_BAZA`` (commit albo gałąź), a bez niej zapadka liczy od ``merge-base``
HEAD z ``origin/main``. Dodane linie to ``git diff`` od bazy (z niezacommitowanymi zmianami) i całe pliki nieśledzone.
Płytki checkout bez bazy (zadania pytest w CI) nie ma czego porównać, więc zapadka się pomija; pilnuje jej
``tools/szybko.py`` przed pushem. Moduł importuje tylko bibliotekę standardową i pytest, bo pomiar zapadek uruchamia go
też w kopii starego commitu.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")

# Lookbehind wokół cyfr numeru, jak ``(?<![0-9a-f])`` w 5b2edaf2f9 i ``(?<![0-9])`` w cc7e5ced21.
_ORDER_NUMBER_ORACLE = re.compile(r"\(\?<!\[?(?:\\d|0-9)")
_ORDER_NUMBER_HELPER = (
    "własna wyrocznia wycieku numeru zlecenia: sprawdź tekst przez zawiera_wartosc z tests/fixtures/wyciek.py, która"
    " pyta strażnika reguły danych (ForbiddenValues.guard)"
)

# Stan ścieżki bez file_state, jak ``copy.path.exists()`` w ea69c32bea i ``old.is_file()`` w 5f4e134ba5.
_BARE_FILE_STATE = re.compile(r"\.(?:exists|is_file|is_dir)\(\s*\)|\bos\.path\.(?:exists|lexists|isfile|isdir)\(")
_FILE_STATE = "src/rozliczenia/file_state.py"
_FILE_STATE_HELPER = (
    "stan pliku poza file_state: zapytaj src/rozliczenia/file_state.py (file_state, path_state, path_taken, a o wpis"
    " folder_entries entry_kind), które rozróżnia brak od pliku niedostępnego (OneDrive, folder bez dostępu)"
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
    """.split()
)
PARSER_FOLDERS = ("tests", "tools", ".agents/skills")
_PARSER_CALL = re.compile(r"(?<![\w.])(?:ast\.(?:parse|walk)\(|tokenize\.)")
_NEW_PARSER = (
    "nowy plik z ręcznym parserem Pythona (ast.parse, ast.walk, tokenize): nazwij korzeń poprawki i napraw go na"
    " najwyższym szczeblu z sekcji „Reguły i co ich pilnuje” w AGENTS.md: (a) jedna droga i jeden właściciel, (b) typ"
    " albo reguła ruff (banned-api TID251 z msg „użyj X” w pyproject.toml), (c) test zachowania, (d) dopiero zapadka"
    " w tests/test_zapadki.py; plik, który mimo to parsuje, dopisz do PARSERS w tests/test_zapadki.py z powodem w"
    " opisie PR"
)
_GONE_PARSER = "plik zniknął: usuń go z PARSERS w tests/test_zapadki.py"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _base() -> str | None:
    base = os.environ.get("MAXIMISEART_ZAPADKA_BAZA")
    if base:
        return base
    try:
        return _git(ROOT, "merge-base", "HEAD", BASE).strip()
    except subprocess.CalledProcessError:
        return None


def _added_lines(root: Path, base: str, folder: str) -> Iterator[tuple[str, int, str]]:
    """Linie ``*.py`` w ``folder`` repozytorium ``root``, które zmiana od ``base`` dodaje: ścieżka, numer linii i treść."""

    path = None
    number = 0
    for line in _git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, "--", f"{folder}/*.py").splitlines():
        if line.startswith("+++ "):
            path = line.removeprefix("+++ b/") if line != "+++ /dev/null" else None
        elif hunk := _HUNK.match(line):
            number = int(hunk["start"])
        elif line.startswith("+") and path is not None:
            yield path, number, line[1:]
            number += 1
    for path in _git(root, "ls-files", "--others", "--exclude-standard", "--", f"{folder}/*.py").splitlines():
        for number, line in enumerate((root / path).read_text(encoding="utf-8").splitlines(), start=1):
            yield path, number, line


def order_number_oracle(line: str) -> bool:
    """Czy linia testu sprawdza wyciek numeru zlecenia własną definicją zamiast ``zawiera_wartosc``.

    Łapie tylko napis ``(?<!``, po nim opcjonalnie ``[``, a po nim ``\\d`` z jednym ukośnikiem albo ``0-9``: tak zaczyna
    się ``(?<![0-9a-f])``, ``(?<![0-9])``, ``(?<!0-9`` i ``r"(?<!\\d)"``. Nie łapie ``"(?<!\\\\d)"`` (dwa ukośniki w napisie
    bez ``r``), klasy, w której ``0-9`` nie stoi zaraz po ``[`` (``(?<![a-f0-9])``), ``\\b`` wokół liczby, literału liczby
    przed ``not in``, numeru ze zmiennej, ``str.find``, ``count``, ``re.search`` na samym numerze, lookaheadu bez
    lookbehindu ani wyrażenia złożonego w kilku liniach; te zostają przeglądowi. Każda forma ma 0 trafień, gdy każda
    linia ``tests/`` jest dodana (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``),
    dlatego literał liczby przed ``not in`` nie jest formą: w ``tests/`` stoją poprawne ``"2026" not in`` i ``"999999" not
    in``.
    """

    return _ORDER_NUMBER_ORACLE.search(line) is not None


def test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    found = [
        f"{path}:{number}: {_ORDER_NUMBER_HELPER}"
        for path, number, line in _added_lines(ROOT, base, "tests")
        if path != "tests/test_zapadki.py" and order_number_oracle(line)
    ]
    assert found == []


def bare_file_state(line: str) -> bool:
    """Czy linia ``src/`` pyta o stan ścieżki z pominięciem ``file_state``.

    Łapie tylko ``.exists()``, ``.is_file()`` i ``.is_dir()`` bez argumentów, także ze spacją w nawiasie (na ``Path`` i
    na wpisie ``os.DirEntry``), oraz ``os.path.exists(``, ``os.path.lexists(``, ``os.path.isfile(`` i
    ``os.path.isdir(``, także w komentarzu i napisie. Nie łapie ``.iterdir()`` (#1249 dodał świadome
    ``register.parent.iterdir()`` w ``try``/``except OSError``, którego po linii nie odróżnić od błędu #1021),
    ``os.listdir``, ``os.scandir``, ``glob``, ``stat`` i ``try``/``except OSError`` napisanych od nowa, wywołań z
    argumentem (``is_file(follow_symlinks=False)``) ani rozbitych na kilka linii, metody pod inną nazwą
    (``check = path.exists``), ``Path.exists(path)``, ``os.path`` pod aliasem (``import os.path as osp``) ani ``exists``
    z ``from os.path import``; te zostają przeglądowi.
    Żadna forma nie trafia w dzisiejsze ``src/``, gdy każda jego linia jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    return _BARE_FILE_STATE.search(line) is not None


def file_state_bypasses(root: Path, base: str) -> list[str]:
    """Linie ``src/`` poza ``file_state.py``, które zmiana od ``base`` dodaje z ``bare_file_state``, z komunikatem."""

    return [
        f"{path}:{number}: {_FILE_STATE_HELPER}"
        for path, number, line in _added_lines(root, base, "src")
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
        # Formy, których zapadka według docstringu nie łapie.
        "        names = sorted(path.name for path in register.parent.iterdir())",
        "    return path.is_file(follow_symlinks=False)",
        "    names = os.listdir(folder)",
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
        # Formy, których zapadka według docstringu nie łapie.
        'number = re.compile("(?<!\\\\d)94001(?!\\\\d)")',
        'number = re.compile(r"(?<![a-f0-9])94001(?![a-f0-9])")',
        r'assert not re.search(r"\b94001\b", text)',
        'assert "94001" not in (tmp_path / "slad.json").read_text(encoding="utf-8")',
    ],
)
def test_zapadka_przepuszcza_zawiera_wartosc_i_inne_wyrazenia(line: str) -> None:
    assert not order_number_oracle(line)


def worker_threads(line: str) -> bool:
    """Czy linia testu pyta o wątki procesu workera pytest z pominięciem ``linie_watkow``.

    Łapie tylko ``active_count(`` (także ``threading.active_count(``), ``Thread.start`` jako całą nazwę (odczyt,
    podmiana i wywołanie ``threading.Thread.start``) oraz ``Thread,`` i napis ``"start"`` albo ``'start'``
    (``monkeypatch.setattr(threading.Thread, "start", …)``), także w komentarzu, docstringu i napisie z kodem procesu
    potomnego. Nie łapie ``threading.enumerate()`` przed i po (#1297 i #1308 dodały tę formę w scalonych PR-ach bez
    rundy FAIL, więc zapadka na niej dałaby alarm na historii; jej przykłady zniknęły z ``tests/``),
    ``thread.start()`` na wątku, ``super().start()``, ``ModelThread.start``, ``sys._current_frames``,
    ``threading._active``, ``setattr`` z nazwą klasy w zmiennej, podmiany ``Thread.run`` i ``Thread.__init__`` ani
    wywołania rozbitego na kilka linii (``monkeypatch.setattr(``, pod nim ``threading.Thread,`` i ``"start",``, jak łamie
    je ruff format przy magicznym przecinku); te zostają przeglądowi.
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
        for path, number, line in _added_lines(root, base, "tests")
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
        # Formy, których zapadka według docstringu nie łapie.
        "    before = set(threading.enumerate())",
        '        checks = [thread for thread in threading.enumerate() if thread.name == "powiadomienia-sprawdzanie"]',
        '    monkeypatch.setattr(threading.Thread, "run", counted)',
        '    monkeypatch.setattr(klasa, "start", counted)',
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
    listy (``return _checked(`` i pod nim ``page.goto(…``), także gdy ta linia jest nową instrukcją po linii z ``,`` na
    końcu (krotka bez nawiasu) albo elementem listy, której nikt nie czyta. Odstęp z ``#`` w napisie ``previous``
    (``"strona #1",``) nie daje więc alarmu. Nie łapie odpowiedzi przypisanej, zwróconej albo podanej dalej w tej samej
    linii, nawigacji po linii, której komentarz albo napis od odstępu z ``#`` kończy się ``(``, ``[`` albo ``,``
    (``wait()  # najpierw lista,``), ``as _`` ani nieużytej zmiennej po ``as``, ``expect_navigation`` z nawiasem w kilku
    liniach, nawigacji na wyniku wywołania (``context.new_page().goto(``), ``wait_for_url`` i ``wait_for_load_state``,
    metody pod inną nazwą
    (``go = page.goto``) ani nawigacji w pliku bez linii, która po wcięciu zaczyna się od ``from playwright`` albo
    ``import playwright`` (karta podana bez adnotacji); import pod ``if TYPE_CHECKING:`` się liczy. Te zostają
    przeglądowi. Żadna forma nie trafia w dzisiejsze ``src/``, gdy każda jego linia jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    ends = (previous.rstrip(), _TRAILING_COMMENT.sub("", previous).rstrip())
    return _DROPPED_NAVIGATION.search(line) is not None and not any(end.endswith(("(", "[", ",")) for end in ends)


def navigation_drops(root: Path, base: str) -> list[str]:
    """Linie plików ``src/`` z importem ``playwright``, które zmiana od ``base`` dodaje z ``dropped_navigation``, z
    komunikatem. Inne pliki ``src/`` kart przeglądarki nie mają, a ich ``.reload(`` (np. ustawień) to nie nawigacja."""

    files: dict[str, tuple[bool, list[str]]] = {}
    found = []
    for path, number, line in _added_lines(root, base, "src"):
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
        # Formy, których zapadka według docstringu nie łapie.
        "    with page.expect_navigation(",
        "    browser.contexts[0].new_page().goto(address)",
        "    page.wait_for_url(url)",
        "    with page.expect_navigation() as _:",
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

    added = sorted(_added_lines(tmp_path, base, "tests"))

    assert added == [("tests/fixtures/nowy.py", 1, "nowa"), ("tests/test_a.py", 2, "dodana"), ("tests/test_a.py", 4, "na końcu")]


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
