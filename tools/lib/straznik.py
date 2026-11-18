"""Strażnik Ważnego ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)): mechanizm z zamkniętej
listy, który autor wpisuje w bloku Ważnego sekcji ``## Korzeń`` linią ``Strażnik: <selektor>``, i jego dowód.

Dowód liczy narzędzie: złą postać daje drzewo SHA werdyktu ``FAIL`` w miejscach jego pola ``Gdzie``, które pisze
recenzent, a autor podaje tylko selektor. Wynik to kod wyjścia pytest albo znaleziska mypy (``-O json``) i ruff
(``--output-format json``) w formacie z wiersza poleceń dowodu, więc konfiguracja PR wyniku nie przestawi.

| Selektor | Przywrócenie błędu na kopii HEAD PR | Dowód przechodzi, gdy |
|---|---|---|
| ``pytest tests/<plik>.py::<test> …`` | każdy plik spoza ``tests/``, który PR zmienił (od rozwidlenia do FAIL i od rozwidlenia HEAD do HEAD), z treścią z FAIL; testy z HEAD | węzły przechodzą na HEAD (kod 0) i padają po przywróceniu (kod 1, nie błąd kolekcji 2, użycia 4 ani brak testów 5), a co najmniej jeden węzeł pada wyjątkiem, który nie jest brakiem nazwy dodanej po FAIL (``ImportError``, ``NameError``, ``AttributeError`` modułu; wtyczka ``straznik_pytest``) |
| ``mypy``, ``ruff`` | pliki z ``Gdzie`` z FAIL w całości: najpierw wszystkie, potem każdy osobno | na HEAD bez znalezisk, po przywróceniu znalezisko w przywróconym pliku, w zakresie ``Case.scopes`` wokół ``Gdzie`` (najmniejsza funkcja z ``na_scalonych_pr.places``; cały plik, gdy kod zakresu z FAIL stoi bez zmian na HEAD, czyli poprawka leży obok) |
| ``ast-grep <id>`` | bez przywrócenia: dowód reguły ``tools/na_scalonych_pr.py --regula-id`` | Ważne stoi w polu ``metadata.przypadki`` reguły na HEAD (jedyna lista jej przypadków), a reguła z HEAD łapie ``Gdzie`` na liniach dodanych do FAIL i ma najwyżej ``na_scalonych_pr.FALSE_ALARMS`` fałszywych alarmów |
| ``brak - proza`` | bez | każde miejsce ``Gdzie`` w pliku, który zmienił PR, to plik ``.md``, docstring albo linia samego komentarza Pythona (``Case.prose`` z reguły ``na_scalonych_pr.PROSE``) |
| ``brak - test`` | bez | każde takie miejsce leży w ``tests/``; mutację złej implementacji powtarza recenzent następnej rundy (skill ``przeglad``) |
| ``brak - napęd`` | bez | każde takie miejsce leży w ``frontend/``, a strażnik to krok napędu skilla ``verify-*``, który Required CI uruchamia w Mutation checks; recenzent następnej rundy uruchamia ten krok na drzewie FAIL |

Granice (próbki ``ZNANE_LUKI_STRAZNIKA`` w ``tests/test_straznik.py``): test, który ten PR zmienił po FAIL dla innego
Ważnego, przechodzi dowód pytest każdego Ważnego tej rundy, bo przywrócenie cofa wszystkie zmiany PR poza ``tests/``;
test, który pada na drzewie FAIL ``TypeError`` z argumentu dodanego po FAIL albo asercją na nazwie czytanej przez
``getattr``, też przechodzi, bo wtyczka zna tylko wyjątek braku nazwy; plik, który po FAIL zmienił też ``main``, wraca
z treścią sprzed tej zmiany. Pytest i mypy wykonują kod PR, więc
status „Werdykt i bramka” liczy dowód w jobie bez prawa zapisu (``.github/workflows/werdykt-i-bramka.yml``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import potomne
import repo
import straznik_pytest

FIELD = "Strażnik:"

TESTS = "tests/"
_NODE = re.compile(r"tests/(?:[\w.-]+/)*[\w.-]+\.py::\w+(?:::\w+)?")
_RULE_ID = re.compile(r"[\w.-]+")
# Zmienne, których kod PR w dowodzie nie dostaje: token GitHuba joba statusu i środowisko wołającego Pythona.
_HIDDEN = ("GH_TOKEN", "GITHUB_TOKEN", "VIRTUAL_ENV")


class Kind(Enum):
    PYTEST = "pytest"
    MYPY = "mypy"
    RUFF = "ruff"
    AST_GREP = "ast-grep"
    PROSE = "brak - proza"
    TESTS = "brak - test"
    DRIVE = "brak - napęd"


EXEMPT = frozenset({Kind.PROSE, Kind.TESTS, Kind.DRIVE})
# Wyjątek, którego warunek to katalog każdego miejsca ``Gdzie`` zmienionego przez PR; proza ma własny warunek (``_prose``).
_FOLDERS = {Kind.TESTS: TESTS, Kind.DRIVE: "frontend/"}
FORMS = f"{Kind.PYTEST.value} tests/<plik>.py::<test> …, {Kind.MYPY.value}, {Kind.RUFF.value}, {Kind.AST_GREP.value} <id reguły>, {Kind.PROSE.value}, {Kind.TESTS.value} albo {Kind.DRIVE.value}"


@dataclass(frozen=True)
class Guard:
    """Selektor strażnika: rodzaj i jego argumenty (węzły pytest albo id reguły ast-grep)."""

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
    if len(words) > 1 and words[0] == Kind.PYTEST.value and all(_NODE.fullmatch(word) for word in words[1:]):
        return Guard(Kind.PYTEST, tuple(words[1:]))
    raise ValueError(f"„{FIELD} {text}” to nie selektor strażnika z listy: {FORMS}")


Place = tuple[str, int, int]


@dataclass(frozen=True)
class Case:
    """Ważne ``label`` (``#5 W1 r1``) werdyktu ``FAIL`` na commicie ``failed`` z miejscami ``places`` pola ``Gdzie``;
    ``fork`` to rozwidlenie gałęzi PR od bazy przed tym commitem (zmiany PR do FAIL to ``fork..failed``). Linie z FAIL
    podaje wywołujący: ``scopes`` to miejsca ``places`` rozszerzone do najmniejszej funkcji (strażnik statyczny),
    a ``prose`` zakresy komentarzy i docstringów plików Pythona z ``places`` (``brak - proza``)."""

    label: str
    failed: str
    fork: str
    places: tuple[Place, ...]
    scopes: tuple[Place, ...] = ()
    prose: tuple[Place, ...] = ()


@dataclass(frozen=True)
class Outcome:
    detected: bool
    line: str


def prove(root: Path, guard: Guard, head: str, base: str, cases: Sequence[Case]) -> list[Outcome]:
    """Dowód strażnika ``guard`` (bez ``ast-grep``) na kopii ``head`` dla każdego Ważnego ``cases``; ``base`` to
    merge-base HEAD z bazą PR. Wynik ma jedną linię na Ważne."""

    if guard.kind in EXEMPT:
        return [_exempt(root, guard.kind, head, base, case) for case in cases]
    with potomne.commit_copy(root, head) as copy:
        before = _run(guard, copy)
        if before.findings or before.code != 0:
            shown = _shown(before.findings) or f"kod {before.code}: {before.last}"
            return [Outcome(False, f"{case.label} | {case.failed[:8]} | PODSTAWA CZERWONA | na HEAD bez przywrócenia: {shown}") for case in cases]
        return [_restored(root, guard, copy, head, base, case) for case in cases]


@dataclass(frozen=True)
class _Ran:
    """Bieg strażnika: kod, ostatnia linia, znaleziska mypy i ruff, a przy pytest testy, które padły w wywołaniu:
    węzeł, nazwa wyjątku i to, czy padł z braku nazwy (``straznik_pytest``)."""

    code: int
    last: str
    findings: tuple[tuple[str, int, str], ...] = ()
    failed: tuple[tuple[str, str, bool], ...] = ()


def _run(guard: Guard, copy: Path) -> _Ran:
    environment = {name: value for name, value in os.environ.items() if name not in _HIDDEN}
    environment["PYTHONPATH"] = os.pathsep.join([str(copy / "src"), environment.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    # Plik przywrócony z FAIL ma często ten sam rozmiar i tę samą sekundę zapisu, więc pyc i pamięć mypy z biegu na HEAD
    # byłyby dla niego ważne: dowód nie pisze pyc, a mypy biegnie bez pamięci (``--no-incremental``).
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if guard.kind is Kind.PYTEST:
        return _pytest(guard, copy, environment)
    if guard.kind is Kind.MYPY:
        command = [sys.executable, "-m", "mypy", "--no-incremental", "-O", "json"]
    else:
        command = [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json"]
    done = potomne.run(command, cwd=copy, env=environment)
    lines = (done.stdout + done.stderr).strip().splitlines()
    last = lines[-1][:200] if lines else ""
    found = _mypy(done.stdout) if guard.kind is Kind.MYPY else _ruff(done.stdout, copy)
    # mypy i ruff kończą się kodem 1 przy znaleziskach, które niesie ``findings``; każdy inny kod to błąd narzędzia.
    return _Ran(0 if done.returncode == 1 and found else done.returncode, last, found)


def _pytest(guard: Guard, copy: Path, environment: dict[str, str]) -> _Ran:
    """Węzły strażnika z wtyczką ``straznik_pytest`` z kopii jej pliku w osobnym katalogu, która zapisuje wyjątek każdego
    testu, który padł."""

    with tempfile.TemporaryDirectory(prefix="straznik-") as folder:
        plugin = Path(straznik_pytest.__file__)
        shutil.copy(plugin, folder)
        results = Path(folder) / straznik_pytest.RESULTS
        environment = {**environment, "PYTHONPATH": os.pathsep.join([environment["PYTHONPATH"], folder])}
        command = [sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "-p", plugin.stem, *guard.arguments]
        done = potomne.run(command, cwd=copy, env=environment)
        entries = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()] if results.exists() else []
    lines = (done.stdout + done.stderr).strip().splitlines()
    failed = tuple((str(entry["wezel"]), str(entry["wyjatek"]), bool(entry["brak_nazwy"])) for entry in entries)
    return _Ran(done.returncode, lines[-1][:200] if lines else "", failed=failed)


def _mypy(output: str) -> tuple[tuple[str, int, str], ...]:
    found = []
    for line in output.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("severity") == "error":
            found.append((str(entry["file"]).replace("\\", "/"), int(entry["line"]), f"[{entry.get('code')}] {entry['message']}"))
    return tuple(found)


def _ruff(output: str, copy: Path) -> tuple[tuple[str, int, str], ...]:
    entries = json.loads(output or "[]")
    root = copy.resolve()
    return tuple((Path(entry["filename"]).resolve().relative_to(root).as_posix(), int(entry["location"]["row"]), f"{entry['code']} {entry['message']}") for entry in entries)


def _shown(findings: Iterable[tuple[str, int, str]]) -> str:
    return "; ".join(f"{path}:{line} {message[:120]}" for path, line, message in list(findings)[:2])


def _text(root: Path, commit: str, path: str) -> str | None:
    content = repo.blob(root, commit, path)
    return None if content is None else content.decode("utf-8", errors="replace")


def _pr_files(root: Path, head: str, base: str, case: Case) -> list[str]:
    return sorted(repo.changed(root, case.fork, case.failed) | repo.changed(root, base, head))


def _restored(root: Path, guard: Guard, copy: Path, head: str, base: str, case: Case) -> Outcome:
    if guard.kind is Kind.PYTEST:
        groups = [[path for path in _pr_files(root, head, base, case) if not path.startswith(TESTS)]]
        what = "pliki PR spoza tests/"
    else:
        paths = list(dict.fromkeys(path for path, _, _ in case.places))
        groups = [paths, *([[path] for path in paths] if len(paths) > 1 else [])]
        what = "pliki z Gdzie"
    tried = []
    for group in groups:
        changed = [path for path in group if _text(root, case.failed, path) != _text(root, head, path)]
        if not changed:
            continue
        kept = {path: (copy / path).read_bytes() if (copy / path).exists() else None for path in changed}
        try:
            for path in changed:
                _write(copy / path, repo.blob(root, case.failed, path))
            ran = _run(guard, copy)
        finally:
            for path, content in kept.items():
                _write(copy / path, content)
        where = "+".join(changed[:3]) + (f" (i {len(changed) - 3} innych)" if len(changed) > 3 else "")
        if guard.kind is Kind.PYTEST:
            behaviour = [one for one in ran.failed if not one[2]]
            if ran.code == 1 and behaviour:
                return Outcome(True, f"{case.label} | {case.failed[:8]} | WYKRYTA | z FAIL: {where} | {behaviour[0][0]}: {behaviour[0][1]} | {ran.last}")
            if ran.code == 1:
                names = ", ".join(sorted({one[1] for one in ran.failed})) or "bez wyjątku z wtyczki"
                tried.append(f"{where}: strażnik pada tylko z braku nazwy dodanej po FAIL ({names}), a nie na błędzie z Gdzie: {ran.last}")
                continue
            tried.append(f"{where}: kod {ran.code} ({'przechodzi' if ran.code == 0 else 'błąd kolekcji, użycia albo brak testów'}): {ran.last}")
            continue
        inside = [finding for finding in ran.findings if finding[0] in changed and finding[1] in _scope(root, head, case, finding[0])]
        if inside:
            return Outcome(True, f"{case.label} | {case.failed[:8]} | WYKRYTA | z FAIL: {where} | {_shown(inside)}")
        tried.append(f"{where}: {'znaleziska poza funkcją z Gdzie: ' + _shown(ran.findings) if ran.findings else f'bez znaleziska (kod {ran.code})'}")
    if not tried:
        return Outcome(False, f"{case.label} | {case.failed[:8]} | NIC DO PRZYWRÓCENIA | {what} mają na HEAD treść z FAIL")
    return Outcome(False, f"{case.label} | {case.failed[:8]} | NIEWYKRYTA | {' / '.join(tried)}")


def _write(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _scope(root: Path, head: str, case: Case, path: str) -> set[int]:
    """Linie pliku ``path`` z FAIL, w których znalezisko liczy się do dowodu: zakresy ``case.scopes`` w tym pliku, a cały
    plik, gdy kod któregoś z nich z FAIL stoi bez zmian na HEAD."""

    lines = (_text(root, case.failed, path) or "").splitlines()
    now = _text(root, head, path) or ""
    found: set[int] = set()
    for place, low, high in case.scopes or case.places:
        if place != path:
            continue
        if "\n".join(lines[low - 1 : high]) in now:
            return set(range(1, len(lines) + 1))
        found.update(range(low, high + 1))
    return found


def _exempt(root: Path, kind: Kind, head: str, base: str, case: Case) -> Outcome:
    touched = set(_pr_files(root, head, base, case))
    own = [place for place in case.places if place[0] in touched]
    if not own:
        return Outcome(False, f"{case.label} | {case.failed[:8]} | ODMOWA | żadne miejsce z Gdzie nie leży w pliku, który zmienił PR")
    wrong = [place for place in own if not (_prose(root, case, place) if kind is Kind.PROSE else place[0].startswith(_FOLDERS[kind]))]
    if wrong:
        why = "to nie plik .md, docstring ani komentarz" if kind is Kind.PROSE else f"leży poza {_FOLDERS[kind]}"
        return Outcome(False, f"{case.label} | {case.failed[:8]} | ODMOWA | {', '.join(f'{path}:{first}' for path, first, _ in wrong)} {why}")
    return Outcome(True, f"{case.label} | {case.failed[:8]} | WYJĄTEK {kind.value} | {', '.join(f'{path}:{first}' for path, first, _ in own)}")


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
