"""Strażnik Ważnego ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)): mechanizm z zamkniętej
listy, który autor wpisuje w bloku Ważnego sekcji ``## Korzeń`` linią ``Strażnik: <selektor>``, i jego dowód.

Dowód liczy narzędzie: złą postać daje drzewo SHA werdyktu ``FAIL`` i miejsca jego pola ``Gdzie``, które pisze
recenzent, a autor podaje tylko selektor. Strażnik ``mypy`` i ``ruff`` (``prove``) biegnie poleceniami Required CI
(``kroki_lokalne.static_steps``: ruff oraz mypy dla każdej platformy ``MYPY_PLATFORMS``) w środowisku Required CI
z ``srodowisko_ci.built`` (HEAD PR scalony z bazą, Python i zależności tego drzewa, zmienne bez tych, które sterują
narzędziami), a wynik to znaleziska w JSON (``kroki_lokalne.JSON_OUTPUT`` i ``diagnostics``, format z wiersza poleceń
dowodu), więc ani maszyna, ani środowisko wołającego, ani konfiguracja wyjścia z PR wyniku nie przestawi. Każdy bieg
uruchamia kroki po kolei na kopii po instalacji projektu (z przywróconymi plikami), jak zadanie Required CI w jednym
checkoucie, do ostatniego kroku narzędzia strażnika (przy mypy także ruff), w kolejności kroków zadania, którą wiąże
``srodowisko_ci.mismatch``; krok, który zmienia pliki kopii (np. ruff z ``fix`` w konfiguracji drzewa, wtyczka mypy),
to ``KROK PISZE PLIKI``, bo Required CI liczy dalsze kroki na zmienionych plikach, a zakres ``Gdzie`` z FAIL ich nie
opisuje; kopia wraca do stanu sprzed biegu.

| Selektor | Przywrócenie błędu na kopii HEAD PR scalonego z bazą | Dowód przechodzi, gdy |
|---|---|---|
| ``mypy``, ``ruff`` | pliki z ``Gdzie`` z FAIL w całości: najpierw wszystkie, potem każdy osobno | na drzewie bez znalezisk w żadnym kroku narzędzia, po przywróceniu znalezisko któregoś kroku w przywróconym pliku, w zakresie ``Case.scopes`` wokół ``Gdzie`` (najmniejsza funkcja z ``na_scalonych_pr.places``; cały plik, gdy kod zakresu z FAIL stoi w drzewie bez zmian, czyli poprawka leży obok) |
| ``ast-grep <id>`` | bez przywrócenia: dowód reguły ``tools/na_scalonych_pr.py --regula-id`` na drzewie ``srodowisko_ci.built`` | Ważne stoi w polu ``metadata.przypadki`` reguły w drzewie (jedyna lista jej przypadków), ast-grep środowiska ma wersję ast-grepa dowodu, a reguła łapie ``Gdzie`` na liniach dodanych do FAIL i ma najwyżej ``na_scalonych_pr.FALSE_ALARMS`` fałszywych alarmów |
| ``pytest <plik>::<test>`` | przeszczep (``transplant``): definicje wokół miejsc ``Gdzie`` spoza ``tests/`` z FAIL, a do tego drzewo FAIL: pliki PR spoza ``tests/`` z treścią z FAIL | węzeł (jeden test albo jego parametr) na drzewie bez zmian przechodzi w całości, na przeszczepie i na drzewie FAIL pada (kod 1), a plugin ``straznik_pytest`` nie widzi na przeszczepie w jego plikach wyjątku rozjazdu interfejsu, którego nie ma na drzewie FAIL |
| ``brak - proza`` | bez | któreś miejsce ``Gdzie`` leży w pliku, który zmienił PR, a każde takie to plik ``.md``, docstring albo linia samego komentarza Pythona (``Case.prose`` z reguły ``na_scalonych_pr.PROSE``) |
| ``brak - napęd`` | bez | któreś miejsce ``Gdzie`` leży w pliku, który zmienił PR, a każde takie w ``frontend/``; strażnik to krok napędu skilla ``verify-*``, który Required CI uruchamia w Mutation checks, a recenzent następnej rundy uruchamia go na drzewie FAIL |
| ``brak - test`` | przeszczep na HEAD PR | przeszczep jest pusty (``Gdzie`` tylko w ``tests/`` albo definicje z ``Gdzie`` mają na HEAD treść z FAIL), więc dowodu testu nie ma z czego liczyć, a czy test pada na błędzie z ``Gdzie``, sprawdza recenzent następnej rundy (skill ``przeglad``); w wątku sprzed wdrożenia dowodu testu (``bramka_straznika.TEST_MARKER``) zawsze |
| ``brak - usunięte`` | bez | zawsze: PR usunął kod z ``Gdzie`` (szczebel (a): część, której przegląd nie przyjął, albo druga droga, której wołający biorą właściciela), więc nie ma mechanizmu do dowodu; czy kod zniknął i nie wraca inną drogą, sprawdza recenzent następnej rundy |

Dowód testu nie pyta, dlaczego test padł (trzy rundy przeglądu #2116 obaliły kształty, które to klasyfikowały: kod 1
na drzewie FAIL, rodzaj wyjątku, drugie przywrócenie linii obok ``Gdzie``). Pyta o dwie rzeczy, które da się zmierzyć:
czym drzewo dowodu różni się od drzewa bez zmian i czy przeszczep jest wierny. Przeszczep różni się od drzewa bez zmian
tylko definicjami, które wskazał recenzent, w postaci z FAIL; definicja to funkcja, metoda, funkcja zagnieżdżona,
instrukcja modułu wiążąca nazwę, klucz najwyższego poziomu YAML i tabela TOML (inny plik w całości), dopasowana po
nazwie kwalifikowanej w drzewie składni, więc linie dodane obok zostają z HEAD, a ``tests/`` zostaje z HEAD. Gdy HEAD
definicji nie ma albo ma ją z inną sygnaturą, wracają też jej wołający z FAIL w plikach PR, a nazwy z FAIL, których
przeszczep używa, a HEAD ich nie ma, wracają z nim. Wierność sprawdza plugin rozjazdu i warunek drzewa FAIL: funkcja
z FAIL, która na przeszczepie pada na polu dataclass dodanym przez PR, na drzewie FAIL przechodzi (próbka A7).
Węzeł biegnie Pythonem i zmiennymi środowiska Required CI (``srodowisko_ci.built`` z ``tests``: tor Linux zadania
pytest), z pustym ``HOME`` i bez bajtkodu w każdym biegu, a pliki, które bieg zapisał w kopii (także ignorowane), wracają
przed następnym, więc trzy biegi różnią się tylko plikami dowodu.

Granice (próbki ``ZNANE_LUKI_STRAZNIKA`` w ``tests/test_straznik.py``): ``brak - usunięte`` przechodzi przy każdym
Ważnym, a ``brak - test`` przy pustym przeszczepie, także gdy test błędu nie łapie; test innej zmiany tej samej definicji
z ``Gdzie`` w tym samym PR i test innej zmiany wołającego, który wraca, przechodzą dowód ``pytest``; wyjątek rozjazdu
w procesie potomnym i w pliku spoza przeszczepu plugin pomija; dowód nie ocenia, czy test sprawdza zachowanie, a nie
tekst, a test niestabilny może przejść jednym padnięciem; to ocenia recenzent. Gałęzi tylko dla macOS nie sprawdza
żaden krok Required CI, więc jej błędu ``mypy`` nie dowodzi na żadnej maszynie, a test, który przechodzi tylko na
Windows, nie przechodzi na drzewie bez zmian i dowód ``pytest`` go odmawia. Plik, który po FAIL zmienił też ``main``,
wraca przy mypy, ruff i na drzewie FAIL dowodu testu z treścią sprzed tej zmiany. Budowa środowiska, mypy i pytest
wykonują kod PR (backend budowy, pakiety i wtyczki z jego konfiguracji, ``conftest.py`` i testy), więc status „Werdykt
i bramka” liczy dowód w jobie bez prawa zapisu (``.github/workflows/werdykt-i-bramka.yml``), a kod PR, który celowo
zmienia wynik w procesie narzędzia, jest granicą jak wtyczka mypy. Moduł nie importuje ``srodowisko_ci`` (PyYAML) ani
pluginu (pytest), bo ``tools/scal_pr.py`` bierze z niego selektory systemowym Pythonem runnera, a środowisko
(``Environment``) buduje ``srodowisko_ci.built``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import subprocess
import tempfile

from kroki_lokalne import JSON_OUTPUT, diagnostics, static_steps
import potomne
import repo

FIELD = "Strażnik:"

_RULE_ID = re.compile(r"[\w.-]+")
# Węzeł pytest: plik testów pod ``tests/``, test (albo klasa i test) i najwyżej jeden parametr.
_NODE = re.compile(r"tests/(?:[\w-]+/)*[\w-]+\.py(?:::[^\W\d]\w*){1,2}(?:\[\S+\])?")


class Kind(Enum):
    MYPY = "mypy"
    RUFF = "ruff"
    AST_GREP = "ast-grep"
    PYTEST = "pytest"
    PROSE = "brak - proza"
    TESTS = "brak - test"
    DRIVE = "brak - napęd"
    REMOVED = "brak - usunięte"


EXEMPT = frozenset({Kind.PROSE, Kind.TESTS, Kind.DRIVE, Kind.REMOVED})
# Co przy wyjątku sprawdza recenzent następnej rundy (skill ``przeglad``); ``brak - usunięte`` nie ma warunku narzędzia.
REVIEWED = {
    Kind.TESTS: "czy test pada na błędzie z Gdzie, sprawdza recenzent następnej rundy",
    Kind.REMOVED: "czy kod z Gdzie zniknął z PR i nie wraca inną drogą, sprawdza recenzent następnej rundy",
}
TESTS_DIR = "tests/"  # katalog testów: jego miejsc ``Gdzie`` przeszczep nie bierze, a drzewo FAIL dowodu testu zostawia z HEAD
PLUGIN = repo.ROOT / "tools/lib/straznik_pytest.py"  # plugin dowodu testu z kodu bazy, ładowany z pliku
PYTEST_TIMEOUT_S = 300  # jeden bieg węzła; razem dowody PR ogranicza ``bramka_straznika.PROOF_TIMEOUT_S``
# Bieg węzła: bez xdist i bez pamięci pytest, jedna linia na padnięcie. Plugin z pliku kodu bazy (``sys.argv[1]``) dostaje
# pliki przeszczepu i plik wyniku (``sys.argv[2]``, JSON), a reszta to argumenty pytest.
_PYTEST_OPTIONS = ("-q", "-n", "0", "-p", "no:cacheprovider", "--tb=line")
_BOOTSTRAP = (
    "import importlib.util, json, sys\n"
    "spec = importlib.util.spec_from_file_location('straznik_pytest', sys.argv[1])\n"
    "plugin = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(plugin)\n"
    "watched, output = json.loads(sys.argv[2])\n"
    "sys.argv[1:] = sys.argv[3:]\n"
    "import pytest\n"
    "raise SystemExit(int(pytest.main(sys.argv[1:], plugins=[plugin.Plugin(watched, output)])))\n"
)
FRONTEND = "frontend/"  # katalog każdego miejsca ``Gdzie`` zmienionego przez PR przy ``brak - napęd``
# Opcje dopisane do kroku ``kroki_lokalne.static_steps`` obok jego ``JSON_OUTPUT``: bieg bez pamięci, bo plik przywrócony
# z FAIL ma często ten sam rozmiar i tę samą sekundę zapisu, więc pamięć z biegu na HEAD byłaby dla niego ważna.
_NO_CACHE = {Kind.MYPY.value: "--no-incremental", Kind.RUFF.value: "--no-cache"}  # bieg bez pamięci, klucz to ``Step.job``
# Pliki, które w biegu piszą same narzędzia (pamięć mypy z ``--cache-dir``, bajtkod wtyczek), a których mypy i ruff nie
# czytają jako kodu, więc ich zapis nie jest zmianą kopii.
_OWN_WRITES = (".mypy_cache/", ".ruff_cache/")
FORMS = (
    f"{Kind.MYPY.value}, {Kind.RUFF.value}, {Kind.AST_GREP.value} <id reguły>, {Kind.PYTEST.value} tests/<plik>.py::<test>, {Kind.PROSE.value}, "
    f"{Kind.DRIVE.value}, {Kind.TESTS.value} (strażnik to test, a przeszczep jest pusty) albo {Kind.REMOVED.value} (kod z Gdzie usunięty z PR)"
)


@dataclass(frozen=True)
class Guard:
    """Selektor strażnika: rodzaj i jego argumenty (id reguły ast-grep, węzeł pytest)."""

    kind: Kind
    arguments: tuple[str, ...] = ()

    def __str__(self) -> str:
        return " ".join((self.kind.value, *self.arguments))


def parse(text: str) -> Guard:
    """Selektor z tekstu pola ``Strażnik:``; tekst spoza zamkniętej listy to ``ValueError`` z jej postaciami."""

    words = text.split()
    exempt = {kind.value: kind for kind in EXEMPT}
    if " ".join(words) in exempt:
        return Guard(exempt[" ".join(words)])
    if words in (["mypy"], ["ruff"]):
        return Guard(Kind(words[0]))
    if len(words) == 2 and words[0] == Kind.AST_GREP.value and _RULE_ID.fullmatch(words[1]):
        return Guard(Kind.AST_GREP, (words[1],))
    if len(words) == 2 and words[0] == Kind.PYTEST.value and _NODE.fullmatch(words[1]):
        return Guard(Kind.PYTEST, (words[1],))
    raise ValueError(f"„{FIELD} {text}” to nie selektor strażnika z listy: {FORMS}")


Place = tuple[str, int, int]


@dataclass(frozen=True)
class Case:
    """Ważne ``label`` (``#5 W1 r1``) werdyktu ``FAIL`` na commicie ``failed`` z miejscami ``places`` pola ``Gdzie``;
    ``fork`` to rozwidlenie gałęzi PR od bazy przed tym commitem (zmiany PR do FAIL to ``fork..failed``). Linie z FAIL
    podaje wywołujący: ``scopes`` to miejsca ``places`` rozszerzone do najmniejszej funkcji (mypy, ruff), a ``prose``
    zakresy komentarzy i docstringów plików Pythona z ``places`` (``brak - proza``)."""

    label: str
    failed: str
    fork: str
    places: tuple[Place, ...]
    scopes: tuple[Place, ...] = ()
    prose: tuple[Place, ...] = ()


@dataclass(frozen=True)
class Environment:
    """Środowisko Required CI z ``srodowisko_ci.built``: commit ``tree`` (HEAD PR scalony z bazą), jego kopia ``copy``
    z projektem zainstalowanym edytowalnie, ``python`` z zależnościami drzewa i zmienne ``variables`` narzędzi."""

    tree: str
    copy: Path
    python: Path
    variables: Mapping[str, str]

    @property
    def ast_grep(self) -> Path:
        return self.python.parent / "ast-grep"


@dataclass(frozen=True)
class Outcome:
    detected: bool
    line: str


def prove(root: Path, guard: Guard, environment: Environment, cases: Sequence[Case]) -> list[Outcome]:
    """Dowód strażnika ``mypy``, ``ruff`` albo ``pytest <węzeł>`` w środowisku Required CI ``environment``
    (``srodowisko_ci.built``) dla każdego Ważnego ``cases``. Wynik ma jedną linię na Ważne."""

    if guard.kind is Kind.PYTEST:
        return _tests(root, guard.arguments[0], environment, cases)
    before = _run(guard, environment, {})
    if before.written:
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {_writes(before)}") for case in cases]
    if before.findings or before.code != 0:
        shown = _shown(before.findings) or f"kod {before.code}: {before.last}"
        red = f"PODSTAWA CZERWONA | na HEAD scalonym z bazą bez przywrócenia: {shown} (tak samo pada Required CI PR: popraw HEAD albo zaktualizuj PR z bazy)"
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {red}") for case in cases]
    return [_restored(root, guard, environment, case) for case in cases]


def exempt(root: Path, guard: Guard, head: str, base: str, cases: Sequence[Case], *, before_test_proof: bool = False) -> list[Outcome]:
    """Warunek wyjątku ``guard`` (``EXEMPT``) na HEAD PR ``head`` dla każdego Ważnego ``cases``; ``base`` to merge-base
    HEAD z bazą PR, a ``before_test_proof`` mówi, że wątek powstał przed wdrożeniem dowodu testu, więc ``brak - test``
    przechodzi bez warunku przeszczepu. Wynik ma jedną linię na Ważne."""

    return [_exempt(root, guard.kind, head, base, case, before_test_proof) for case in cases]


@dataclass(frozen=True)
class _Ran:
    code: int
    last: str
    findings: tuple[tuple[str, int, str], ...] = ()
    written: str = ""  # krok, który zmienił pliki kopii, i te pliki


def _run(guard: Guard, environment: Environment, contents: Mapping[str, bytes | None]) -> _Ran:
    """Bieg strażnika (``_steps``) na kopii środowiska z plikami ``contents`` (``_placed``)."""

    with _placed(environment.copy, contents):
        return _steps(guard, environment)


@contextmanager
def _placed(copy: Path, contents: Mapping[str, bytes | None]) -> Iterator[None]:
    """Pliki ``contents`` (``None``: plik usunięty) w kopii ``copy`` na czas bloku, po którym wracają do stanu sprzed
    niego."""

    kept = {path: (copy / path).read_bytes() if (copy / path).exists() else None for path in contents}
    try:
        for path, content in contents.items():
            _write(copy / path, content)
        yield
    finally:
        for path, content in kept.items():
            _write(copy / path, content)


def _steps(guard: Guard, environment: Environment) -> _Ran:
    """Kroki ``kroki_lokalne.static_steps`` po kolei do ostatniego kroku narzędzia ``guard`` (mypy: ruff i każda
    platforma) Pythonem i ze zmiennymi ``environment`` na jego kopii; znaleziska kroków ``guard`` razem, a kod pierwszego
    z nich, który nie dał wyniku. Krok, po którym pliki kopii są inne niż przed nim, kończy bieg z ``written``, a pliki,
    które zmienił, wracają do stanu sprzed kroku."""

    copy = environment.copy
    state = _state(copy)
    steps = static_steps(copy, str(environment.python))
    end = max(index for index, step in enumerate(steps) if step.job == guard.kind.value)
    code, last = 0, ""
    found: list[tuple[str, int, str]] = []
    for step in steps[: end + 1]:
        done = potomne.run([*step.command, _NO_CACHE[step.job], *JSON_OUTPUT[step.job]], cwd=copy, env=environment.variables)
        if changed := _restore(copy, state):
            return _Ran(code, last, tuple(found), f"po kroku {step.name}: {_listed(changed)}")
        if step.job != guard.kind.value:
            continue
        # Kod reguły w nawiasie przy mypy, jak w jego wyjściu, a przed komunikatem przy ruff.
        read = [(one.path, one.line, f"[{one.code}] {one.message}" if guard.kind is Kind.MYPY else f"{one.code} {one.message}") for one in diagnostics(step.job, done.stdout, copy)]
        found.extend(read)
        # mypy i ruff kończą się kodem 1 przy znaleziskach, które niesie ``read``; każdy inny kod to błąd narzędzia.
        if code == 0 and not (done.returncode == 0 or (done.returncode == 1 and read)):
            lines = (done.stdout + done.stderr).strip().splitlines()
            code, last = done.returncode, f"{step.name}: {lines[-1][:200] if lines else ''}"
    return _Ran(code, last, tuple(dict.fromkeys(found)))


def _state(copy: Path, *, ignored: bool = False) -> dict[str, bytes | None]:
    """Treść plików kopii, które różnią się od jej drzewa (zmienione, usunięte i nowe, z ``ignored`` także ignorowane),
    bez ``_OWN_WRITES`` i ``__pycache__``."""

    shown = ("--ignored=traditional",) if ignored else ()
    listed = repo.git(copy, "status", "--porcelain=v1", "-z", "--untracked-files=all", *shown, "--no-renames", isolated=True)
    paths = {entry[3:] for entry in listed.split("\0") if len(entry) > 3}
    kept = sorted(path for path in paths if not path.startswith(_OWN_WRITES) and "__pycache__" not in path.split("/"))
    return {path: (copy / path).read_bytes() if (copy / path).is_file() else None for path in kept}


def _restore(copy: Path, state: Mapping[str, bytes | None], *, ignored: bool = False) -> list[str]:
    """Pliki kopii, które od chwili ``state`` (``_state``) się zmieniły; wracają do tamtej treści."""

    now = _state(copy, ignored=ignored)
    changed = sorted(path for path in state.keys() | now.keys() if state.get(path) != now.get(path))
    for path in changed:
        _write(copy / path, state[path] if path in state else repo.blob(copy, "HEAD", path))
    return changed


def _writes(ran: _Ran) -> str:
    return (
        f"KROK PISZE PLIKI | {ran.written} (np. fix w konfiguracji ruff drzewa albo wtyczka mypy): Required CI liczy dalsze "
        "kroki na zmienionych plikach, a dowód ich nie odtwarza; wyłącz zapis w konfiguracji drzewa"
    )


def _shown(findings: Iterable[tuple[str, int, str]]) -> str:
    return "; ".join(f"{path}:{line} {message[:120]}" for path, line, message in list(findings)[:2])


def _text(root: Path, commit: str, path: str) -> str | None:
    content = repo.blob(root, commit, path)
    return None if content is None else content.decode("utf-8", errors="replace")


def _pr_files(root: Path, head: str, base: str, case: Case) -> list[str]:
    return sorted(repo.changed(root, case.fork, case.failed) | repo.changed(root, base, head))


def _restored(root: Path, guard: Guard, environment: Environment, case: Case) -> Outcome:
    paths = list(dict.fromkeys(path for path, _, _ in case.places))
    groups = [paths, *([[path] for path in paths] if len(paths) > 1 else [])]
    tried = []
    for group in groups:
        changed = [path for path in group if _text(root, case.failed, path) != _text(root, environment.tree, path)]
        if not changed:
            continue
        ran = _run(guard, environment, {path: repo.blob(root, case.failed, path) for path in changed})
        if ran.written:
            return Outcome(False, f"{case.label} | {case.failed[:8]} | {_writes(ran)}")
        where = _listed(changed)
        inside = [finding for finding in ran.findings if finding[0] in changed and finding[1] in _scope(root, environment.tree, case, finding[0])]
        if inside:
            return Outcome(True, f"{case.label} | {case.failed[:8]} | WYKRYTA | z FAIL: {where} | {_shown(inside)}")
        tried.append(f"{where}: {'znaleziska poza funkcją z Gdzie: ' + _shown(ran.findings) if ran.findings else f'bez znaleziska (kod {ran.code})'}")
    if not tried:
        return Outcome(False, f"{case.label} | {case.failed[:8]} | NIC DO PRZYWRÓCENIA | pliki z Gdzie mają na HEAD scalonym z bazą treść z FAIL")
    return Outcome(False, f"{case.label} | {case.failed[:8]} | NIEWYKRYTA | {' / '.join(tried)}")


def _listed(paths: Sequence[str]) -> str:
    return "+".join(paths[:3]) + (f" (i {len(paths) - 3} innych)" if len(paths) > 3 else "")


def _write(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _scope(root: Path, tree: str, case: Case, path: str) -> set[int]:
    """Linie pliku ``path`` z FAIL, w których znalezisko liczy się do dowodu: zakresy ``case.scopes`` w tym pliku, a cały
    plik, gdy kod któregoś z nich z FAIL stoi bez zmian w drzewie ``tree``; bez zakresu w pliku żadna."""

    lines = (_text(root, case.failed, path) or "").splitlines()
    now = _text(root, tree, path) or ""
    found: set[int] = set()
    for place, low, high in case.scopes:
        if place != path:
            continue
        if "\n".join(lines[low - 1 : high]) in now:
            return set(range(1, len(lines) + 1))
        found.update(range(low, high + 1))
    return found


def _exempt(root: Path, kind: Kind, head: str, base: str, case: Case, before_test_proof: bool) -> Outcome:
    label = f"{case.label} | {case.failed[:8]}"
    if kind is Kind.TESTS and not before_test_proof:
        try:
            graft = transplant(root, case, head, _pr_files(root, head, base, case))
        except SyntaxError as error:
            return Outcome(False, f"{label} | ODMOWA | przeszczep: {_unparsed(error)}")
        if graft.contents:
            return Outcome(
                False,
                f"{label} | ODMOWA | przeszczep z FAIL ma {_listed(graft.units)}: strażnik-test to {Kind.PYTEST.value} tests/<plik>.py::<test> z dowodem narzędzia, "
                f"a {kind.value} przechodzi tylko przy pustym przeszczepie",
            )
        return Outcome(True, f"{label} | WYJĄTEK {kind.value} | przeszczep pusty: {_EMPTY} | {REVIEWED[kind]}")
    if kind in REVIEWED:
        return Outcome(True, f"{label} | WYJĄTEK {kind.value} | {REVIEWED[kind]}")
    touched = set(_pr_files(root, head, base, case))
    own = [place for place in case.places if place[0] in touched]
    if not own:
        return Outcome(False, f"{label} | ODMOWA | żadne miejsce z Gdzie nie leży w pliku, który zmienił PR")
    wrong = [place for place in own if not (_prose(root, case, place) if kind is Kind.PROSE else place[0].startswith(FRONTEND))]
    if wrong:
        why = "to nie plik .md, docstring ani komentarz" if kind is Kind.PROSE else f"leży poza {FRONTEND}"
        return Outcome(False, f"{label} | ODMOWA | {', '.join(f'{path}:{first}' for path, first, _ in wrong)} {why}")
    return Outcome(True, f"{label} | WYJĄTEK {kind.value} | {', '.join(f'{path}:{first}' for path, first, _ in own)}")


def _prose(root: Path, case: Case, place: Place) -> bool:
    """Czy miejsce to proza: plik ``.md`` albo każda linia w docstringu z ``case.prose`` lub w linii samego komentarza
    (komentarz z ``case.prose`` na linii, która zaczyna się od ``#``, a nie za kodem)."""

    path, first, last = place
    if path.endswith(".md"):
        return True
    lines = (_text(root, case.failed, path) or "").splitlines()
    spans = [(low, high) for file, low, high in case.prose if file == path]

    def prose_line(number: int) -> bool:
        # Zakres jednej linii to komentarz albo docstring jednej linii: proza tylko, gdy linia od niego się zaczyna.
        text = lines[number - 1].lstrip() if 0 < number <= len(lines) else ""
        return any(low <= number <= high and (high > low or text.startswith(("#", '"', "'", 'r"', "r'"))) for low, high in spans)

    return path.endswith(".py") and all(prose_line(number) for number in range(first, last + 1))


# ---------------------------------------------------------------- dowód testu (``pytest <węzeł>``)

_EMPTY = "definicje z Gdzie spoza tests/ mają na HEAD treść z FAIL albo Gdzie leży tylko w tests/"


@dataclass(frozen=True)
class _Tested:
    """Bieg węzła pytest: kod wyjścia, ostatnia linia wyjścia i zapis pluginu ``straznik_pytest``."""

    code: int
    last: str
    phases: tuple[str, ...] = ()  # ``faza:wynik`` każdej fazy każdego testu węzła
    crashes: tuple[str, ...] = ()
    drift: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    @property
    def passed(self) -> bool:
        """Węzeł przeszedł w całości: kod 0, test wykonany i żadna faza nie pominięta ani nie padła."""

        return self.code == 0 and "call:passed" in self.phases and all(phase.endswith(":passed") for phase in self.phases)

    @property
    def failed(self) -> bool:
        """Węzeł padł: kod 1 (testy padły, a nie zbieranie ani przerwanie) i faza z wynikiem ``failed``."""

        return self.code == 1 and any(phase.endswith(":failed") for phase in self.phases)

    def why(self) -> str:
        if self.code == 0 and not self.passed:
            return f"pominięty albo bez testu ({', '.join(sorted(set(self.phases))) or 'żadnej fazy'})"
        return f"kod {self.code}: {self.crashes[0] if self.crashes else self.last}"


def _tests(root: Path, node: str, environment: Environment, cases: Sequence[Case]) -> list[Outcome]:
    """Dowód ``pytest <węzeł>``: węzeł przechodzi na drzewie bez zmian, a dla każdego Ważnego ``_transplanted``."""

    head = _pytest(node, environment, {}, ())
    if not head.passed:
        red = (
            f"PODSTAWA CZERWONA | {node} na HEAD scalonym z bazą: {head.why()} (dowód liczy węzeł w środowisku toru Linux Required CI: "
            "wybierz węzeł, który tam przechodzi bez pominięcia, popraw test albo zaktualizuj PR z bazy)"
        )
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {red}") for case in cases]
    return [_transplanted(root, node, environment, case) for case in cases]


def _transplanted(root: Path, node: str, environment: Environment, case: Case) -> Outcome:
    label = f"{case.label} | {case.failed[:8]}"
    tree = environment.tree
    files = _pr_files(root, tree, f"{tree}^1", case)
    try:
        graft = transplant(root, case, tree, files)
    except SyntaxError as error:
        return Outcome(False, f"{label} | ODMOWA | przeszczep: {_unparsed(error)}")
    if not graft.contents:
        return Outcome(False, f"{label} | NIC DO PRZESZCZEPIENIA | {_EMPTY}: dowodu testu nie ma z czego liczyć, strażnik to {Kind.TESTS.value}")
    failed = {path: repo.blob(root, case.failed, path) for path in files if not path.startswith(TESTS_DIR)}
    failed = {path: content for path, content in failed.items() if content != repo.blob(root, tree, path)}
    watched = sorted(graft.contents)
    on_failed = _pytest(node, environment, failed, watched)
    grafted = _pytest(node, environment, graft.contents, watched)
    units = _listed(graft.units)
    drift = sorted(grafted.drift - on_failed.drift)
    if grafted.failed and on_failed.failed and not drift:
        return Outcome(True, f"{label} | WYKRYTA | przeszczep z FAIL: {units} | {grafted.why()}")
    if not grafted.failed:
        why = f"na przeszczepie z FAIL ({units}) węzeł nie pada ({grafted.why()})"
    elif not on_failed.failed:
        why = f"na drzewie FAIL (pliki PR spoza tests/ z treścią z FAIL) węzeł nie pada ({on_failed.why()}), więc padnięcie na przeszczepie nie odtwarza FAIL"
    else:
        shown = "; ".join(f"{kind}: {message}" for kind, message in drift[:2])
        why = f"przeszczep ({units}) pada na interfejsie HEAD, a nie na błędzie: {shown} (tego wyjątku nie ma na drzewie FAIL)"
    return Outcome(False, f"{label} | NIEWYKRYTA | {why}")


def _pytest(node: str, environment: Environment, contents: Mapping[str, bytes | None], watched: Sequence[str]) -> _Tested:
    """Bieg węzła ``node`` Pythonem i zmiennymi ``environment`` na jego kopii z plikami ``contents`` (``_placed``), z pustym
    ``HOME`` i bez bajtkodu; plugin śledzi wyjątki rozjazdu w plikach ``watched``. Pliki, które bieg zapisał w kopii,
    także ignorowane, wracają do stanu sprzed biegu."""

    copy = environment.copy
    with tempfile.TemporaryDirectory(prefix="straznik-pytest-") as folder, _placed(copy, contents):
        home, output = Path(folder) / "dom", Path(folder) / "wynik.json"
        home.mkdir()
        # Ścieżka pliku w kodzie Pythona bywa ścieżką kopii albo jej postacią bez dowiązań (``/private`` na macOS).
        spelled = sorted({str(path) for name in watched for path in (copy / name, (copy / name).resolve())})
        command = [str(environment.python), "-B", "-c", _BOOTSTRAP, str(PLUGIN), json.dumps([spelled, str(output)]), *_PYTEST_OPTIONS, node]
        variables = {**environment.variables, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
        state = _state(copy, ignored=True)
        try:
            done = potomne.run(command, cwd=copy, env=variables, timeout=PYTEST_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return _Tested(-1, f"bieg trwał ponad {PYTEST_TIMEOUT_S} s")
        finally:
            _restore(copy, state, ignored=True)
        lines = (done.stdout + done.stderr).strip().splitlines()
        last = lines[-1][:200] if lines else ""
        if not output.is_file():
            return _Tested(done.returncode, last)
        read = json.loads(output.read_text(encoding="utf-8"))
    phases = tuple(phase for found in read["testy"].values() for phase in found)
    return _Tested(done.returncode, last, phases, tuple(read["padniecia"]), frozenset((kind, message) for kind, message in read["rozjazd"]))


def _unparsed(error: SyntaxError) -> str:
    return f"{error.filename or 'plik'}:{error.lineno} nie da się przeczytać drzewem składni Pythona ({error.msg}), więc definicji z Gdzie nie ma jak przeszczepić"


# ---------------------------------------------------------------- przeszczep

Qual = tuple[str, ...]  # nazwa kwalifikowana w module: ``(f,)``, ``(Klasa, metoda)``, ``("=a,b",)`` instrukcji wiążącej nazwy
_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_GROWTH = 4  # najwięcej rund domykania wołających i nazw przeszczepu


@dataclass(frozen=True)
class Transplant:
    """Pliki przeszczepu (``None``: plik usunięty) i nazwy jego jednostek dla linii dowodu."""

    contents: Mapping[str, bytes | None]
    units: tuple[str, ...]


def transplant(root: Path, case: Case, tree: str, files: Sequence[str]) -> Transplant:
    """Przeszczep Ważnego ``case`` na commit ``tree``: pliki, w których definicje wokół miejsc ``Gdzie`` spoza ``tests/``
    mają treść z FAIL, a reszta treść z ``tree`` (docstring modułu). ``files`` to pliki PR; tylko z nich wracają wołający
    definicji usuniętej albo ze zmienioną sygnaturą i nazwy z FAIL, których przeszczep używa. Plik Pythona, którego nie
    da się przeczytać, to ``SyntaxError``."""

    wanted: dict[str, set[Qual]] = {}
    whole: set[str] = set()
    blocks: dict[str, set[str]] = {}
    for path, first, last in case.places:
        old = _text(root, case.failed, path)
        if path.startswith(TESTS_DIR) or old is None:
            continue
        if not path.endswith(".py"):
            found = _blocks(path, old)
            if found is None:
                whole.add(path)
            else:
                blocks.setdefault(path, set()).update(key for key, low, high in found if low <= last and first <= high)
            continue
        quals = _locate(_parsed(old, path), first, last)
        if None in quals or not quals:
            whole.add(path)
        wanted.setdefault(path, set()).update(qual for qual in quals if qual is not None)
    code = [path for path in files if path.endswith(".py") and not path.startswith(TESTS_DIR)]
    old_indexes = {path: _index(_parsed(old, path)) for path in dict.fromkeys([*code, *wanted]) if (old := _text(root, case.failed, path)) is not None}
    now_indexes = {path: _index(_parsed(now, path)) if (now := _text(root, tree, path)) is not None else {} for path in old_indexes}
    _grow(wanted, old_indexes, now_indexes)
    contents: dict[str, bytes | None] = {}
    units: list[str] = []
    for path in sorted(whole):
        if (content := repo.blob(root, case.failed, path)) != repo.blob(root, tree, path):
            contents[path] = content
            units.append(f"{path} (cały)")
    for path, keys in sorted(blocks.items()):
        old, now = _text(root, case.failed, path) or "", _text(root, tree, path)
        new = old if now is None else _swap_blocks(path, old, now, keys)
        if new != now:
            contents[path] = new.encode()
            units += [f"{path}:[{key}]" for key in sorted(keys)]
    for path, chosen in sorted(wanted.items()):
        if path in whole:
            continue
        old, now = _text(root, case.failed, path) or "", _text(root, tree, path)
        new, made = (old, ["(cały, brak na HEAD)"]) if now is None else _graft(old, now, chosen, path)
        if new != now:
            contents[path] = new.encode()
            units += [f"{path}:{one}" for one in made]
    return Transplant(contents, tuple(units))


def _parsed(text: str, path: str) -> ast.Module:
    return ast.parse(text, filename=path)


def _grow(wanted: dict[str, set[Qual]], old_indexes: Mapping[str, Mapping[Qual, ast.stmt]], now_indexes: Mapping[str, Mapping[Qual, ast.stmt]]) -> None:
    """Dokłada do ``wanted`` definicje z FAIL plików PR: wołających definicji przeszczepu, której HEAD nie ma albo ma
    z inną sygnaturą (wołający z HEAD podaliby jej argumenty HEAD), i definicje, których HEAD nie ma, a przeszczep używa
    ich nazwy (funkcja, metoda, nazwa modułu innego pliku); nazwy modułu tego samego pliku domyka ``_graft``."""

    def absent(path: str, qual: Qual) -> bool:
        return qual not in now_indexes.get(path, {})

    for _ in range(_GROWTH):
        removed = {qual[-1] for path, quals in wanted.items() for qual in quals if not qual[-1].startswith("=") and absent(path, qual)}
        removed |= {
            qual[-1] for path, quals in wanted.items() for qual in quals if not absent(path, qual) and _signature_changed(old_indexes.get(path, {}).get(qual), now_indexes[path].get(qual))
        }
        used = {name for path, quals in wanted.items() for qual in quals if (node := old_indexes.get(path, {}).get(qual)) is not None for name in _used(node)}
        grown = False
        for path, index in old_indexes.items():
            for qual, node in index.items():
                if qual in wanted.get(path, set()):
                    continue
                caller = bool(removed) and isinstance(node, _DEFINITIONS) and bool(_used(node) & removed) and not absent(path, qual)
                needed = absent(path, qual) and bool(set(qual[-1].lstrip("=").split(",")) & used) and not (qual[-1].startswith("=") and path in wanted)
                if caller or needed:
                    wanted.setdefault(path, set()).add(qual)
                    grown = True
        if not grown:
            return


def _start(node: ast.stmt) -> int:
    decorators: list[ast.expr] = node.decorator_list if isinstance(node, _SCOPES) else []
    return min([node.lineno, *(one.lineno for one in decorators)])


def _span(node: ast.stmt) -> tuple[int, int]:
    return _start(node), node.end_lineno or node.lineno


def _bound(node: ast.stmt) -> list[str]:
    """Nazwy, które instrukcja modułu wiąże: definicja, import i przypisanie."""

    if isinstance(node, _SCOPES):
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [(alias.asname or alias.name).split(".")[0] for alias in node.names]
    targets: list[ast.expr] = list(node.targets) if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
    return [one.id for target in targets for one in ast.walk(target) if isinstance(one, ast.Name)]


def _used(node: ast.AST) -> set[str]:
    return {one.id for one in ast.walk(node) if isinstance(one, ast.Name)} | {one.attr for one in ast.walk(node) if isinstance(one, ast.Attribute)}


def _index(tree: ast.Module) -> dict[Qual, ast.stmt]:
    """Definicje modułu po nazwie kwalifikowanej: funkcja, metoda, funkcja i klasa zagnieżdżona w funkcji, klasa
    i instrukcja modułu wiążąca nazwy."""

    found: dict[Qual, ast.stmt] = {}

    def visit(node: ast.stmt, prefix: Qual) -> None:
        if isinstance(node, _SCOPES):
            found.setdefault((*prefix, node.name), node)
            inner = node.body if isinstance(node, ast.ClassDef) else [child for child in node.body if isinstance(child, _SCOPES)]
            for child in inner:
                visit(child, (*prefix, node.name))
        elif not prefix and (names := _bound(node)):
            found.setdefault(("=" + ",".join(sorted(names)),), node)

    for statement in tree.body:
        visit(statement, ())
    return found


def _locate(tree: ast.Module, first: int, last: int) -> list[Qual | None]:
    """Najmniejsze definicje wokół linii ``first``–``last``; ``None``: instrukcja modułu bez nazwy (cały plik)."""

    def overlaps(node: ast.stmt) -> bool:
        return _start(node) <= last and first <= (node.end_lineno or node.lineno)

    def descend(node: ast.stmt, prefix: Qual) -> Qual | None:
        if isinstance(node, _SCOPES):
            inner = [child for child in node.body if overlaps(child)]
            if len(inner) == 1 and isinstance(inner[0], _SCOPES):
                return descend(inner[0], (*prefix, node.name))
            return (*prefix, node.name)
        names = _bound(node)
        return ("=" + ",".join(sorted(names)),) if names and not prefix else None

    return [descend(statement, ()) for statement in tree.body if overlaps(statement)]


def _signature_changed(old: ast.stmt | None, now: ast.stmt | None) -> bool:
    """Czy wywołanie zgodne z jedną wersją funkcji może nie pasować do drugiej: inne nazwy, kolejność, rodzaje albo
    liczba wartości domyślnych parametrów (adnotacje się nie liczą)."""

    if not isinstance(old, _DEFINITIONS) or not isinstance(now, _DEFINITIONS):
        return False

    def shape(arguments: ast.arguments) -> tuple[object, ...]:
        return (
            tuple(one.arg for one in arguments.posonlyargs),
            tuple(one.arg for one in arguments.args),
            arguments.vararg.arg if arguments.vararg else None,
            tuple(one.arg for one in arguments.kwonlyargs),
            arguments.kwarg.arg if arguments.kwarg else None,
            len(arguments.defaults),
            tuple(default is None for default in arguments.kw_defaults),
        )

    return bool(shape(old.args) != shape(now.args))


def _blocks(path: str, content: str) -> list[tuple[str, int, int]] | None:
    """Jednostki pliku spoza Pythona z liniami od do: tabela TOML (``[nagłówek]``, przed pierwszą preambuła) albo klucz
    najwyższego poziomu YAML (linia bez wcięcia ``klucz:``); ``None``: inny format (cały plik)."""

    lines = content.splitlines()
    if path.endswith(".toml"):
        starts = [(number + 1, line.strip()) for number, line in enumerate(lines) if line.startswith("[")]
    elif path.endswith((".yml", ".yaml")):
        starts = [(number + 1, line.split(":", 1)[0]) for number, line in enumerate(lines) if line[:1] not in ("", " ", "\t", "#", "-") and ":" in line]
    else:
        return None
    if not starts or starts[0][0] != 1:
        starts = [(1, ""), *starts]
    return [(key, low, starts[position + 1][0] - 1 if position + 1 < len(starts) else len(lines)) for position, (low, key) in enumerate(starts)]


def _swap_blocks(path: str, old: str, now: str, keys: set[str]) -> str:
    """``now`` z jednostkami ``keys`` (``_blocks``) z ``old``; jednostka, której ``now`` nie ma, idzie na koniec."""

    old_blocks = {key: (low, high) for key, low, high in reversed(_blocks(path, old) or [])}
    now_blocks = {key: (low, high) for key, low, high in reversed(_blocks(path, now) or [])}
    now_lines, old_lines = now.splitlines(keepends=True), old.splitlines(keepends=True)
    edits = []
    for key in keys:
        low, high = old_blocks[key]
        piece = _ended(old_lines[low - 1 : high])
        start, end = now_blocks[key] if key in now_blocks else (len(now_lines) + 1, len(now_lines))
        edits.append((start - 1, end, piece))
    for start, end, piece in sorted(edits, reverse=True):
        now_lines[start:end] = piece
    return "".join(now_lines)


def _ended(lines: list[str]) -> list[str]:
    return [*lines[:-1], lines[-1] if lines[-1].endswith("\n") else lines[-1] + "\n"] if lines else lines


def _graft(old: str, now: str, quals: set[Qual], path: str) -> tuple[str, list[str]]:
    """``now`` z definicjami ``quals`` w treści z ``old`` i nazwy jednostek, które się zmieniły. Definicja, której ``now``
    nie ma, wraca na koniec swojej klasy albo modułu, a nazwy modułu z ``old``, których przeszczep używa, a ``now`` ich
    nie wiąże, przed instrukcją modułu z pierwszą zmianą."""

    old_tree, now_tree = _parsed(old, path), _parsed(now, path)
    old_index, now_index = _index(old_tree), _index(now_tree)
    old_lines, now_lines = old.splitlines(keepends=True), now.splitlines(keepends=True)
    edits: list[tuple[int, int, list[str]]] = []  # linie ``now`` od, do (wyłącznie) i nowe linie
    made: list[str] = []
    grafted: list[ast.stmt] = []
    for qual in sorted(quals):
        if (source := old_index.get(qual)) is None:
            continue
        low, high = _span(source)
        piece = _ended(old_lines[low - 1 : high])
        grafted.append(source)
        if (target := now_index.get(qual)) is not None:
            start, end = _span(target)
            if now_lines[start - 1 : end] != piece:
                edits.append((start - 1, end, piece))
                made.append(".".join(qual))
            continue
        parent = now_index.get(qual[:-1]) if len(qual) > 1 else None
        if len(qual) > 1 and parent is None:
            continue
        at = (parent.end_lineno or parent.lineno) if parent is not None else len(now_lines)
        edits.append((at, at, ["\n", *piece]))
        made.append(".".join(qual) + " (wraca)")
    now_bound = {name for node in now_tree.body for name in _bound(node)}
    old_binding = {name: node for node in old_tree.body for name in _bound(node)}
    needed = {name for node in grafted for name in _used(node)}
    missing = [old_binding[name] for name in sorted(needed) if name in old_binding and name not in now_bound and old_binding[name] not in grafted]
    if missing:
        first = min((start for start, _, _ in edits), default=len(now_lines))
        first = min([first, *(_start(node) - 1 for node in now_tree.body if _start(node) - 1 <= first < (node.end_lineno or node.lineno))])
        statements = [line for node in dict.fromkeys(missing) for line in old_lines[_span(node)[0] - 1 : _span(node)[1]]]
        edits.append((first, first, [*_ended(statements), "\n"]))
    for start, end, piece in sorted(edits, key=lambda one: (one[0], one[1]), reverse=True):
        now_lines[start:end] = piece
    return "".join(now_lines), made
