"""Strażnik Ważnego ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)): mechanizm z zamkniętej
listy, który autor wpisuje w bloku Ważnego sekcji ``## Korzeń`` linią ``Strażnik: <selektor>``, i jego dowód.

Dowód liczy narzędzie: złą postać daje drzewo SHA werdyktu ``FAIL`` i miejsca jego pola ``Gdzie``, które pisze
recenzent, a autor podaje tylko selektor. Strażnik biegnie poleceniami Required CI na każdej maszynie
(``kroki_lokalne.static_steps``: ruff oraz mypy ``--platform linux`` i ``--platform win32``) w ich środowisku, a wynik to
znaleziska w JSON (``_JSON``: format z wiersza poleceń dowodu), więc ani system maszyny, ani konfiguracja PR wyniku nie
przestawi.

| Selektor | Przywrócenie błędu na kopii HEAD PR | Dowód przechodzi, gdy |
|---|---|---|
| ``mypy``, ``ruff`` | pliki z ``Gdzie`` z FAIL w całości: najpierw wszystkie, potem każdy osobno | na HEAD bez znalezisk w żadnym kroku narzędzia, po przywróceniu znalezisko któregoś kroku w przywróconym pliku, w zakresie ``Case.scopes`` wokół ``Gdzie`` (najmniejsza funkcja z ``na_scalonych_pr.places``; cały plik, gdy kod zakresu z FAIL stoi bez zmian na HEAD, czyli poprawka leży obok) |
| ``ast-grep <id>`` | bez przywrócenia: dowód reguły ``tools/na_scalonych_pr.py --regula-id`` | Ważne stoi w polu ``metadata.przypadki`` reguły na HEAD (jedyna lista jej przypadków), a reguła z HEAD łapie ``Gdzie`` na liniach dodanych do FAIL i ma najwyżej ``na_scalonych_pr.FALSE_ALARMS`` fałszywych alarmów |
| ``brak - proza`` | bez | któreś miejsce ``Gdzie`` leży w pliku, który zmienił PR, a każde takie to plik ``.md``, docstring albo linia samego komentarza Pythona (``Case.prose`` z reguły ``na_scalonych_pr.PROSE``) |
| ``brak - napęd`` | bez | któreś miejsce ``Gdzie`` leży w pliku, który zmienił PR, a każde takie w ``frontend/``; strażnik to krok napędu skilla ``verify-*``, który Required CI uruchamia w Mutation checks, a recenzent następnej rundy uruchamia go na drzewie FAIL |
| ``brak - test`` | bez | zawsze: strażnik to test (Ważne w kodzie albo próbka testu), a czy pada na błędzie z ``Gdzie``, sprawdza recenzent następnej rundy (skill ``przeglad``), jak przed ADR 0042 |
| ``brak - usunięte`` | bez | zawsze: PR usunął kod z ``Gdzie`` (szczebel (a): część, której przegląd nie przyjął, albo druga droga, której wołający biorą właściciela), więc nie ma mechanizmu do dowodu; czy kod zniknął i nie wraca inną drogą, sprawdza recenzent następnej rundy |

Test nie ma selektora z dowodem narzędzia: trzy rundy przeglądu #2116 obaliły trzy kształty dowodu, że test pada na
kodzie z ``Gdzie``, a nie z braku czegoś, co poprawka dodała obok (ADR 0042, „Test jako strażnik”). Granica (próbka
``ZNANE_LUKI_STRAZNIKA`` w ``tests/test_straznik.py``): ``brak - test`` i ``brak - usunięte`` przechodzą przy każdym
Ważnym, także gdy mechanizm z dowodem by je zamknął, test błędu nie łapie albo kod z ``Gdzie`` stoi na HEAD; to ocenia
recenzent. Gałęzi tylko dla macOS nie sprawdza żaden krok Required CI, więc jej błędu ``mypy`` nie dowodzi na żadnej
maszynie. Plik, który po FAIL zmienił też ``main``, wraca przy mypy i ruff z treścią sprzed tej zmiany. Mypy wykonuje
wtyczki z konfiguracji PR, więc status „Werdykt i bramka” liczy dowód w jobie bez prawa zapisu
(``.github/workflows/werdykt-i-bramka.yml``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import re

from kroki_lokalne import environment, static_steps
import potomne
import repo

FIELD = "Strażnik:"

_RULE_ID = re.compile(r"[\w.-]+")
# Zmienne, których kod PR (wtyczki mypy) w dowodzie nie dostaje: token GitHuba joba statusu i środowisko wołającego Pythona.
_HIDDEN = ("GH_TOKEN", "GITHUB_TOKEN", "VIRTUAL_ENV")


class Kind(Enum):
    MYPY = "mypy"
    RUFF = "ruff"
    AST_GREP = "ast-grep"
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
# Opcje dopisane do kroku ``kroki_lokalne.static_steps``: znaleziska w JSON i bieg bez pamięci, bo plik przywrócony z FAIL
# ma często ten sam rozmiar i tę samą sekundę zapisu, więc pamięć z biegu na HEAD byłaby dla niego ważna.
_JSON = {Kind.MYPY: ("--no-incremental", "-O", "json"), Kind.RUFF: ("--no-cache", "--output-format", "json")}
FORMS = f"{Kind.MYPY.value}, {Kind.RUFF.value}, {Kind.AST_GREP.value} <id reguły>, {Kind.PROSE.value}, {Kind.DRIVE.value}, {Kind.TESTS.value} (strażnik to test) albo {Kind.REMOVED.value} (kod z Gdzie usunięty z PR)"


@dataclass(frozen=True)
class Guard:
    """Selektor strażnika: rodzaj i jego argumenty (id reguły ast-grep)."""

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
        return [_restored(root, guard, copy, head, case) for case in cases]


@dataclass(frozen=True)
class _Ran:
    code: int
    last: str
    findings: tuple[tuple[str, int, str], ...] = ()


def _run(guard: Guard, copy: Path) -> _Ran:
    """Każdy krok narzędzia ``guard`` z ``kroki_lokalne.static_steps`` (mypy: Linux i Windows) na kopii ``copy``; znaleziska
    wszystkich kroków razem, a kod pierwszego kroku, który nie dał wyniku."""

    env = {name: value for name, value in environment(copy).items() if name not in _HIDDEN}
    code, last = 0, ""
    found: list[tuple[str, int, str]] = []
    for step in (step for step in static_steps(copy) if step.job == guard.kind.value):
        done = potomne.run([*step.command, *_JSON[guard.kind]], cwd=copy, env=env)
        read = _mypy(done.stdout) if guard.kind is Kind.MYPY else _ruff(done.stdout, copy)
        found.extend(read)
        # mypy i ruff kończą się kodem 1 przy znaleziskach, które niesie ``read``; każdy inny kod to błąd narzędzia.
        if code == 0 and not (done.returncode == 0 or (done.returncode == 1 and read)):
            lines = (done.stdout + done.stderr).strip().splitlines()
            code, last = done.returncode, f"{step.name}: {lines[-1][:200] if lines else ''}"
    return _Ran(code, last, tuple(dict.fromkeys(found)))


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


def _restored(root: Path, guard: Guard, copy: Path, head: str, case: Case) -> Outcome:
    paths = list(dict.fromkeys(path for path, _, _ in case.places))
    groups = [paths, *([[path] for path in paths] if len(paths) > 1 else [])]
    tried = []
    for group in groups:
        changed = [path for path in group if _text(root, case.failed, path) != _text(root, head, path)]
        if not changed:
            continue
        ran = _with(root, guard, copy, {path: repo.blob(root, case.failed, path) for path in changed})
        where = _listed(changed)
        inside = [finding for finding in ran.findings if finding[0] in changed and finding[1] in _scope(root, head, case, finding[0])]
        if inside:
            return Outcome(True, f"{case.label} | {case.failed[:8]} | WYKRYTA | z FAIL: {where} | {_shown(inside)}")
        tried.append(f"{where}: {'znaleziska poza funkcją z Gdzie: ' + _shown(ran.findings) if ran.findings else f'bez znaleziska (kod {ran.code})'}")
    if not tried:
        return Outcome(False, f"{case.label} | {case.failed[:8]} | NIC DO PRZYWRÓCENIA | pliki z Gdzie mają na HEAD treść z FAIL")
    return Outcome(False, f"{case.label} | {case.failed[:8]} | NIEWYKRYTA | {' / '.join(tried)}")


def _with(root: Path, guard: Guard, copy: Path, contents: dict[str, bytes | None]) -> _Ran:
    """Bieg strażnika na kopii z plikami ``contents`` (``None``: plik usunięty), po którym kopia wraca do HEAD."""

    kept = {path: (copy / path).read_bytes() if (copy / path).exists() else None for path in contents}
    try:
        for path, content in contents.items():
            _write(copy / path, content)
        return _run(guard, copy)
    finally:
        for path, content in kept.items():
            _write(copy / path, content)


def _listed(paths: Sequence[str]) -> str:
    return "+".join(paths[:3]) + (f" (i {len(paths) - 3} innych)" if len(paths) > 3 else "")


def _write(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _scope(root: Path, head: str, case: Case, path: str) -> set[int]:
    """Linie pliku ``path`` z FAIL, w których znalezisko liczy się do dowodu: zakresy ``case.scopes`` w tym pliku, a cały
    plik, gdy kod któregoś z nich z FAIL stoi bez zmian na HEAD; bez zakresu w pliku żadna."""

    lines = (_text(root, case.failed, path) or "").splitlines()
    now = _text(root, head, path) or ""
    found: set[int] = set()
    for place, low, high in case.scopes:
        if place != path:
            continue
        if "\n".join(lines[low - 1 : high]) in now:
            return set(range(1, len(lines) + 1))
        found.update(range(low, high + 1))
    return found


def _exempt(root: Path, kind: Kind, head: str, base: str, case: Case) -> Outcome:
    label = f"{case.label} | {case.failed[:8]}"
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
