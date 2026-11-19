"""Strażnik Ważnego ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)): mechanizm z zamkniętej
listy, który autor wpisuje w bloku Ważnego sekcji ``## Korzeń`` linią ``Strażnik: <selektor>``, i jego dowód.

Dowód liczy narzędzie: złą postać daje drzewo SHA werdyktu ``FAIL`` i miejsca jego pola ``Gdzie`` albo, przy teście,
blok mutacji w werdykcie, które pisze recenzent, a autor podaje tylko selektor. Strażnik ``mypy`` i ``ruff`` (``prove``) biegnie poleceniami Required CI
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
| ``pytest <plik>::<test>`` | mutacje recenzenta z najnowszego bloku ``### Mutacja W<n> r<k>`` tego Ważnego w werdyktach PR (``mutacja_recenzenta``), każda naniesiona silnikiem ``tools/mutacje.py`` (``silnik_mutacji.judged``: kotwica dokładnie raz) na kopię HEAD PR scalonego z bazą | węzeł (jeden test albo jego parametr) bez mutacji przechodzi, z każdą mutacją bloku biegnie i pada (``WYKRYTA``, jak w ``tools/mutacje.py``, ale węzeł, którego z mutacją nie ma, to nie wykrycie), a po nich bez mutacji przechodzi znowu; każdy bieg w osobnym środowisku toru Linux zadania pytest (``prove_test``) |
| ``brak - proza`` | bez | któreś miejsce ``Gdzie`` leży w pliku, który zmienił PR, a każde takie to plik ``.md``, docstring albo linia samego komentarza Pythona (``Case.prose`` z reguły ``na_scalonych_pr.PROSE``) |
| ``brak - napęd`` | bez | któreś miejsce ``Gdzie`` leży w pliku, który zmienił PR, a każde takie w ``frontend/``; strażnik to krok napędu skilla ``verify-*``, który Required CI uruchamia w Mutation checks, a recenzent następnej rundy uruchamia go na drzewie FAIL |
| ``brak - test`` | bez | tylko w wątku z pierwszym werdyktem sprzed wdrożenia dowodu testu (``bramka_straznika.TEST_MARKER``): czy test pada na błędzie z ``Gdzie``, sprawdza recenzent następnej rundy (skill ``przeglad``), jak przed ADR 0042 |
| ``brak - usunięte`` | bez | zawsze: PR usunął kod z ``Gdzie`` (szczebel (a): część, której przegląd nie przyjął, albo druga droga, której wołający biorą właściciela), więc nie ma mechanizmu do dowodu; czy kod zniknął i nie wraca inną drogą, sprawdza recenzent następnej rundy |

Dowód testu nie pyta, dlaczego test padł, i nie przenosi kodu z FAIL: drzewo biegu różni się od HEAD tylko mutacją
z bloku, więc węzeł, który bez niej przechodzi, a z nią pada, pada przez tę i tylko tę zmianę (ADR 0042, aneks; trzy
rundy #2116 i trzy #2197 obaliły kształty, które klasyfikowały przyczynę padnięcia albo przenosiły definicje z FAIL).
Złą postać pisze recenzent w werdykcie, a nie autor, więc wierność mutacji wobec błędu z Ważnego ocenia recenzent
następnej rundy, który czyta blok. Każdy bieg (bez mutacji i z każdą mutacją) dostaje od ``build`` własne środowisko
(kopię z własnym gitem, Pythona, ``HOME`` i ``TMPDIR``), więc stan w nim nie przechodzi do następnego biegu, a po
biegach z mutacją węzeł bez mutacji musi przejść znowu, inaczej dowód odmawia. Brak bloku to odmowa, w której
recenzent następnej rundy dopisuje blok, a kotwica, której na HEAD scalonym z bazą nie ma dokładnie raz, i blok innej
postaci to odmowa, w której recenzent następnej rundy odnawia blok. Granice (próbki ``ZNANE_LUKI_STRAZNIKA`` w
``tests/test_straznik.py``): ``brak - usunięte`` przechodzi przy każdym Ważnym, a ``brak - test`` przy każdym w wątku
sprzed wdrożenia dowodu testu, także gdy mechanizm z dowodem by je zamknął, test błędu nie łapie albo kod z ``Gdzie``
stoi na HEAD; mutacja słabsza albo szersza niż błąd z Ważnego daje ``WYKRYTA`` testowi, który łapie tylko ją, albo
testowi innej zmiany, którą mutacja też psuje, a nawet wierną mutację test może złapać inną drogą niż błąd z Ważnego
(np. na wejściu, którego błąd nie dotyczy); dowód nie ocenia, czy test sprawdza zachowanie, a nie tekst, a test
niestabilny może przejść jednym padnięciem, także test, którego wynik zależy od stanu poprzedniego biegu poza
środowiskiem (plik pod ścieżką bezwzględną, usługa systemu): biegi dowodu ten stan dzielą, a Required CI uruchamia
węzeł raz, więc test, który sprawdza błąd dopiero przy śladzie poprzedniego biegu albo pada na przemian, może dać
``WYKRYTA``, choć Required CI z błędem przechodzi; to ocenia recenzent. Mutację nanosi dowód po instalacji projektu, jak
``tools/mutacje.py`` na kopię z instalacją edytowalną, więc mutacja zależności w ``pyproject.toml`` pakietów nie
zmienia. Gałęzi tylko dla macOS nie sprawdza żaden krok Required CI, więc jej błędu ``mypy`` nie dowodzi na żadnej
maszynie, a test, który przechodzi tylko na Windows, dowód ``pytest`` odmawia bez mutacji. Plik, który po FAIL zmienił
też ``main``, wraca przy mypy i ruff z treścią sprzed tej zmiany. Budowa środowiska, mypy i pytest wykonują kod PR
(backend budowy, pakiety i wtyczki z jego konfiguracji, ``conftest.py`` i testy), więc status „Werdykt i bramka” liczy
dowód w jobie bez prawa zapisu (``.github/workflows/werdykt-i-bramka.yml``). Moduł nie importuje ``srodowisko_ci``
(PyYAML), bo ``tools/scal_pr.py`` bierze z niego selektory systemowym Pythonem runnera, a środowisko (``Environment``)
buduje ``srodowisko_ci.built``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from kroki_lokalne import JSON_OUTPUT, diagnostics, static_steps
import mutacja_recenzenta
import potomne
import repo
import silnik_mutacji
from silnik_mutacji import Mutation, Verdict

FIELD = "Strażnik:"

_RULE_ID = re.compile(r"[\w.-]+")
# Węzeł pytest: plik testów pod ``tests/``, test (``test…``, także w klasie) i najwyżej jeden parametr, nie klasa ani plik.
_NODE = re.compile(r"tests/(?:[\w-]+/)*[\w-]+\.py(?:::[^\W\d]\w*)?::test\w*(?:\[\S+\])?")
# Bieg węzła dowodu testu: jeden proces bez pamięci pytest, jak polecenie z przepisu ``tools/mutacje.py``.
_PYTEST = ("-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider")
PYTEST_TIMEOUT_S = 300  # jeden bieg węzła; razem dowody PR ogranicza ``bramka_straznika.PROOF_TIMEOUT_S``


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
# Wyjątki bez warunku narzędzia i to, co sprawdza recenzent następnej rundy (skill ``przeglad``).
REVIEWED = {
    Kind.TESTS: "czy test pada na błędzie z Gdzie, sprawdza recenzent następnej rundy",
    Kind.REMOVED: "czy kod z Gdzie zniknął z PR i nie wraca inną drogą, sprawdza recenzent następnej rundy",
}
FRONTEND = "frontend/"  # katalog każdego miejsca ``Gdzie`` zmienionego przez PR przy ``brak - napęd``
# Opcje dopisane do kroku ``kroki_lokalne.static_steps`` obok jego ``JSON_OUTPUT``: bieg bez pamięci, bo plik przywrócony
# z FAIL ma często ten sam rozmiar i tę samą sekundę zapisu, więc pamięć z biegu na HEAD byłaby dla niego ważna.
_NO_CACHE = {Kind.MYPY.value: "--no-incremental", Kind.RUFF.value: "--no-cache"}  # bieg bez pamięci, klucz to ``Step.job``
# Pliki, które w biegu piszą same narzędzia (pamięć mypy z ``--cache-dir``, bajtkod wtyczek), a których mypy i ruff nie
# czytają jako kodu, więc ich zapis nie jest zmianą kopii.
_OWN_WRITES = (".mypy_cache/", ".ruff_cache/")
FORMS = (
    f"{Kind.MYPY.value}, {Kind.RUFF.value}, {Kind.AST_GREP.value} <id reguły>, {Kind.PYTEST.value} tests/<plik>.py::<test>, {Kind.PROSE.value}, "
    f"{Kind.DRIVE.value}, {Kind.TESTS.value} (strażnik to test w wątku sprzed dowodu testu) albo {Kind.REMOVED.value} (kod z Gdzie usunięty z PR)"
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
    podaje wywołujący: ``scopes`` to miejsca ``places`` rozszerzone do najmniejszej funkcji (mypy, ruff), ``prose``
    zakresy komentarzy i docstringów plików Pythona z ``places`` (``brak - proza``), a ``mutation`` najnowszy blok
    mutacji recenzenta tego Ważnego w werdyktach PR (``pytest <węzeł>``)."""

    label: str
    failed: str
    fork: str
    places: tuple[Place, ...]
    scopes: tuple[Place, ...] = ()
    prose: tuple[Place, ...] = ()
    mutation: mutacja_recenzenta.Block | None = None


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
    """Dowód strażnika ``mypy`` albo ``ruff`` w środowisku Required CI ``environment`` (``srodowisko_ci.built``) dla
    każdego Ważnego ``cases``. Wynik ma jedną linię na Ważne."""

    before = _run(guard, environment, {})
    if before.written:
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {_writes(before)}") for case in cases]
    if before.findings or before.code != 0:
        shown = _shown(before.findings) or f"kod {before.code}: {before.last}"
        red = f"PODSTAWA CZERWONA | na HEAD scalonym z bazą bez przywrócenia: {shown} (tak samo pada Required CI PR: popraw HEAD albo zaktualizuj PR z bazy)"
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {red}") for case in cases]
    return [_restored(root, guard, environment, case) for case in cases]


Build = Callable[[], AbstractContextManager[Environment]]  # nowe środowisko Required CI na jeden bieg


def prove_test(node: str, build: Build, cases: Sequence[Case]) -> list[Outcome]:
    """Dowód ``pytest <węzeł>`` dla każdego Ważnego ``cases``: węzeł ``node`` bez mutacji przechodzi, a z każdą mutacją
    bloku Ważnego pada; każdy bieg w osobnym środowisku z ``build`` (``srodowisko_ci.built`` z ``tests``). Wynik ma
    jedną linię na Ważne."""

    command = (*_PYTEST, node)
    clean = Mutation("bez mutacji", (), command)
    verdict, last = _judged(build, clean)
    if verdict is not Verdict.SURVIVED:
        red = (
            f"PODSTAWA CZERWONA | {node} na HEAD scalonym z bazą bez mutacji: {last} (dowód liczy węzeł w środowisku toru Linux Required CI: "
            "wybierz węzeł, który tam przechodzi, popraw test albo zaktualizuj PR z bazy)"
        )
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {red}") for case in cases]
    found = [_mutated(build, command, case) for case in cases]
    if any(outcome.detected for outcome in found) and (again := _judged(build, clean))[0] is not Verdict.SURVIVED:
        left = (
            f"ODMOWA | {node} bez mutacji pada po biegach z mutacją ({again[1]}): węzeł zostawia stan poza środowiskiem biegu, który zmienia następny "
            "bieg, więc padnięcie z mutacją niczego nie dowodzi; strażnik to test, który przechodzi w każdym biegu bez mutacji"
        )
        return [Outcome(False, f"{case.label} | {case.failed[:8]} | {left}") for case in cases]
    return found


def exempt(root: Path, guard: Guard, head: str, base: str, cases: Sequence[Case], *, before_test_proof: bool = False) -> list[Outcome]:
    """Warunek wyjątku ``guard`` (``EXEMPT``) na HEAD PR ``head`` dla każdego Ważnego ``cases``; ``base`` to merge-base
    HEAD z bazą PR, a ``before_test_proof`` mówi, że wątek powstał przed wdrożeniem dowodu testu, więc tylko w nim
    ``brak - test`` przechodzi. Wynik ma jedną linię na Ważne."""

    return [_exempt(root, guard.kind, head, base, case, before_test_proof) for case in cases]


@dataclass(frozen=True)
class _Ran:
    code: int
    last: str
    findings: tuple[tuple[str, int, str], ...] = ()
    written: str = ""  # krok, który zmienił pliki kopii, i te pliki


def _run(guard: Guard, environment: Environment, contents: Mapping[str, bytes | None]) -> _Ran:
    """Bieg strażnika (``_steps``) na kopii środowiska z plikami ``contents`` (``None``: plik usunięty), po którym te
    pliki wracają do stanu sprzed biegu."""

    copy = environment.copy
    kept = {path: (copy / path).read_bytes() if (copy / path).exists() else None for path in contents}
    try:
        for path, content in contents.items():
            _write(copy / path, content)
        return _steps(guard, environment)
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
        if (now := _state(copy)) != state:
            changed = sorted(path for path in state.keys() | now.keys() if state.get(path) != now.get(path))
            for path in changed:
                _write(copy / path, state[path] if path in state else repo.blob(copy, "HEAD", path))
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


def _state(copy: Path) -> dict[str, bytes | None]:
    """Treść plików kopii, które różnią się od jej drzewa (zmienione, usunięte i nowe poza ignorowanymi), bez
    ``_OWN_WRITES`` i ``__pycache__``."""

    listed = repo.git(copy, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", isolated=True)
    paths = {entry[3:] for entry in listed.split("\0") if len(entry) > 3}
    kept = sorted(path for path in paths if not path.startswith(_OWN_WRITES) and "__pycache__" not in path.split("/"))
    return {path: (copy / path).read_bytes() if (copy / path).is_file() else None for path in kept}


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


def _judged(build: Build, mutation: Mutation) -> tuple[Verdict, str]:
    """Werdykt mutacji ``mutation`` silnikiem ``tools/mutacje.py`` na kopii nowego środowiska z ``build``, jego Pythonem
    i zmiennymi; mutacja, z którą pytest nie uruchomił węzła, nie jest wykryciem (``needs_test``)."""

    with build() as environment:
        verdict, last, _ = silnik_mutacji.judged(
            environment.copy, mutation, limit_s=PYTEST_TIMEOUT_S, python=str(environment.python), env=environment.variables, needs_test=bool(mutation.edits)
        )
    return verdict, last


def _mutated(build: Build, command: tuple[str, ...], case: Case) -> Outcome:
    """``WYKRYTA``, gdy węzeł ``command`` pada z każdą mutacją bloku ``case.mutation``; bez bloku, z blokiem innej
    postaci albo z kotwicą, której nie ma dokładnie raz, odmowa z poleceniem dla recenzenta następnej rundy."""

    label = f"{case.label} | {case.failed[:8]}"
    named = f"### Mutacja {case.label.partition(' ')[2]}"
    if case.mutation is None:
        return Outcome(False, f"{label} | ODMOWA | żaden werdykt PR nie ma bloku {named} ze złą postacią do naniesienia na HEAD: recenzent następnej rundy dopisuje blok (skill przeglad)")
    renew = f"recenzent następnej rundy odnawia blok {named} (skill przeglad)"
    try:
        mutations = mutacja_recenzenta.mutations(case.mutation, command)
    except ValueError as error:
        return Outcome(False, f"{label} | ODMOWA | {error}: {renew}")
    shown = []
    for mutation in mutations:
        verdict, last = _judged(build, mutation)
        if verdict is Verdict.STALE:
            return Outcome(False, f"{label} | ODMOWA | {mutation.name}: {last} na HEAD scalonym z bazą: {renew}")
        if verdict is not Verdict.CAUGHT:
            return Outcome(False, f"{label} | NIEWYKRYTA | {mutation.name}: {verdict}: {last}")
        shown.append(f"{mutation.name} → {last}")
    return Outcome(True, f"{label} | WYKRYTA | z bloku {named}: {'; '.join(shown)}")


def _exempt(root: Path, kind: Kind, head: str, base: str, case: Case, before_test_proof: bool) -> Outcome:
    label = f"{case.label} | {case.failed[:8]}"
    if kind is Kind.TESTS and not before_test_proof:
        return Outcome(
            False,
            f"{label} | ODMOWA | {kind.value} przechodzi tylko w wątku sprzed wdrożenia dowodu testu: strażnik-test to {Kind.PYTEST.value} tests/<plik>.py::<test> "
            "z blokiem ### Mutacja recenzenta w werdykcie (ADR 0042)",
        )
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
