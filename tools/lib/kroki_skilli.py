"""Kroki skilli: co jest krokiem skilla w CI (podstawa ``ci:`` albo skrypt mutacji), czego pilnuje i co je uruchamia.

Skrypt mutacji skilla to ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``: dowodzi, że sprawdzenie skilla
pada na zepsutych wariantach kodu, i kończy się linią ``MUTACJE OK``. Nowy skrypt o takiej nazwie jest krokiem bez wpisu
w ``ci.yml``. Skrypt nie może zgubić się po cichu: ``znajdz`` daje FAIL plikowi ``.py`` w skillu z ``mutation`` w nazwie,
który nie pasuje do wzorca, i skryptowi mutacji wskazanemu w ``SKILL.md`` skilla, którego nie ma.

Skill może zadeklarować we frontmatterze ``SKILL.md`` klucz ``ci:``: polecenie (skrypt ``.py`` z repozytorium, ścieżka
od korzenia, i jego argumenty), którym CI sprawdza skill na niezmienionym kodzie, czyli krok ``PODSTAWA``, także w skillu
bez skryptu mutacji. Klucz ``ci-czesci: <n>`` mówi, że polecenie ``ci:`` dzieli się na najwyżej n części
(``MUTACJE_CZESC=k/n``, ``tools/lib/skrypt_skilla.py``); bez klucza podstawa jest niepodzielna. Klucz ``pilnuje:``, lista
globów ścieżek względem korzenia (``*`` obejmuje też ``/``), mówi, przy zmianie których plików skill obowiązuje
(``hits``).

Kiedy który krok biegnie, rozstrzyga zakres runu (``tools/lib/zakres_runu.py``), a uruchamia go
``tools/ci/mutacje_skilli.py`` (``run``).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from fnmatch import fnmatchcase
from functools import cache
import importlib.util
import os
from pathlib import Path
import re
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
PATTERN = "check_*_mutations.py"
# Wywołanie skryptu mutacji w SKILL.md; ścieżka bez ``.agents`` na początku liczy się od folderu skilla.
MENTION = re.compile(r"[\w.\\/-]*scripts[\\/]check_\w+_mutations\.py")
VERDICT = "MUTACJE OK"
BASELINE = "PODSTAWA"
# Runner mutacji: jego zmiana może zmienić werdykt każdego skryptu mutacji (uruchomienie kroku, jego polecenie i części).
RUNNER = ("tools/mutacje.py", "tools/ci/mutacje_skilli.py", "tools/lib/kroki_skilli.py")
# Powód w ``Hits`` dla pliku w folderze skilla.
FOLDER = "folder skilla"
# Folder modelu TLA+ w skillu: skrypt mutacji, który psuje tylko pliki w nim, biegnie też na pull request (ADR 0021).
MODEL = "model"


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


@cache
def _mutations(script: Path) -> tuple[Any, ...]:
    spec = importlib.util.spec_from_file_location(f"_mutacje_{script.parents[1].name}", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"nie da się wczytać {_name(script)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.MUTATIONS)


def _front(skill_md: Path) -> list[str]:
    """Linie frontmattera ``SKILL.md``.

    Czytniki kluczy nie parsują frontmattera jako YAML, bo opisy skilli mają w tekście dwukropki, których YAML nie
    przyjmuje.
    """

    lines = skill_md.read_text(encoding="utf-8").splitlines() if skill_md.is_file() else []
    end = lines.index("---", 1) if lines[:1] == ["---"] and "---" in lines[1:] else 0
    return lines[1:end]


def _values(skill_md: Path, key: str) -> list[str]:
    """Wartości linii ``<key>: <wartość>`` frontmattera, w kolejności."""

    return [line.split(":", 1)[1] for line in _front(skill_md) if line.split(":", 1)[0] == key]


def guarded(skill_md: Path) -> tuple[str, ...] | None:
    """Globy z klucza ``pilnuje`` frontmattera ``SKILL.md``; ``None``, gdy klucza nie ma.

    Klucz to linia ``pilnuje:``, a pod nią linie ``  - <glob>``.
    """

    front = _front(skill_md)
    keys = [number for number, line in enumerate(front) if line.split(":", 1)[0] == "pilnuje"]
    if not keys:
        return None
    if front[keys[0]] != "pilnuje:":
        raise ValueError(f"pilnuje w {_name(skill_md)} nie jest listą globów pod kluczem")
    globs = []
    for line in front[keys[0] + 1 :]:
        if not line.startswith("  - "):
            break
        globs.append(line.removeprefix("  - ").strip())
    if not globs:
        raise ValueError(f"pilnuje w {_name(skill_md)} nie ma żadnego globu")
    return tuple(globs)


def ci_parts(skill_md: Path) -> int:
    """Najwięcej części polecenia ``ci`` z klucza ``ci-czesci`` frontmattera ``SKILL.md``; bez klucza 1.

    Klucz to jedna linia ``ci-czesci: <liczba całkowita od 1>``.
    """

    values = _values(skill_md, "ci-czesci")
    if not values:
        return 1
    if not values[0].strip().isdigit() or int(values[0]) < 1:
        raise ValueError(f"ci-czesci w {_name(skill_md)} nie jest liczbą części od 1")
    return int(values[0])


def ci_command(skill_md: Path) -> tuple[str, ...] | None:
    """Polecenie z klucza ``ci`` frontmattera ``SKILL.md``; ``None``, gdy klucza nie ma.

    Klucz to jedna linia ``ci: <skrypt .py od korzenia repozytorium> <argumenty>``.
    """

    values = _values(skill_md, "ci")
    if not values:
        return None
    command = tuple(values[0].split())
    if not command or not command[0].endswith(".py") or not (ROOT / command[0]).is_file():
        raise ValueError(f"ci w {_name(skill_md)} nie zaczyna się skryptem .py z repozytorium")
    return command


class Hits(NamedTuple):
    """Zmienione pliki, przy których skill obowiązuje: plik → glob ``pilnuje``, który go obejmuje, albo ``FOLDER``.

    ``always`` to powód, gdy skill obowiązuje przy każdej zmianie: nie ma klucza ``pilnuje`` albo nie da się go odczytać.
    """

    files: dict[str, str]
    always: str | None


def hits(skill: Path, changed: Iterable[str]) -> Hits:
    """Pliki ``changed``, przy których skill obowiązuje, a na pull request biegnie jego podstawa ``ci``."""

    try:
        globs = guarded(skill / "SKILL.md")
    except ValueError as error:
        return Hits({}, str(error))
    if globs is None:
        return Hits({}, f"{_name(skill)}/SKILL.md nie ma klucza pilnuje")
    own = f"{_name(skill)}/"
    found = {}
    for name in sorted(changed):
        glob = FOLDER if name.startswith(own) else next((glob for glob in globs if fnmatchcase(name, glob)), None)
        if glob is not None:
            found[name] = glob
    return Hits(found, None)


class Step(NamedTuple):
    """Krok zadania: podstawa ``ci`` skilla (``verdict`` ``None``) albo jeden jego skrypt mutacji.

    ``parts`` to najwięcej części kroku: liczba mutacji skryptu, bo więcej części skrypt nie ma, a podstawy ``ci-czesci``
    (bez klucza 1); ``browser``: skrypty skilla importują Playwright, więc zadanie CI potrzebuje Chromium.
    """

    skill: Path
    key: str
    name: str
    command: tuple[str, ...]
    verdict: str | None
    parts: int
    browser: bool


def _lost(scripts: list[Path]) -> dict[str, str]:
    """Skrypty mutacji, których runner by nie uruchomił, z powodem."""

    lost = {
        _name(path): f"nazwa spoza wzorca scripts/{PATTERN}"
        for path in SKILLS.glob("*/**/*.py")
        if "mutation" in path.name.lower() and path not in scripts
    }
    for skill_md in SKILLS.glob("*/SKILL.md"):
        for mentioned in set(MENTION.findall(skill_md.read_text(encoding="utf-8"))):
            relative = mentioned.replace("\\", "/").removeprefix("./")
            base = ROOT if relative.startswith(".agents/") else skill_md.parent
            path = Path(os.path.normpath(base / relative))
            if path not in scripts:
                lost.setdefault(_name(path), f"wskazany w {_name(skill_md)}, a nie ma go pod tą nazwą")
    return lost


@cache
def _browser(skill: Path) -> bool:
    """Skrypty skilla importują Playwright; skrypt, który się nie parsuje, liczy się jak taki, co importuje."""

    for path in skill.glob("scripts/**/*.py"):
        try:
            tree = ast.parse(path.read_bytes(), filename=str(path))
        except SyntaxError:
            return True
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            names += [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            if any(name.split(".")[0] == "playwright" for name in names):
                return True
    return False


def _count(script: Path) -> int:
    """Liczba mutacji skryptu; tabela, której nie da się wczytać, to jedna niepodzielna część, która pokaże swój błąd."""

    try:
        return max(1, len(_mutations(script)))
    except Exception:  # noqa: BLE001 - błąd tabeli zgłasza sam skrypt mutacji, gdy biegnie
        return 1


def steps(failed: dict[str, str]) -> list[Step]:
    """Kroki wszystkich skilli, podstawa każdego skilla z kluczem ``ci`` przed jego skryptami; zły klucz ``ci`` albo
    ``ci-czesci`` trafia do ``failed``."""

    skills: dict[Path, list[Path]] = {skill_md.parent: [] for skill_md in SKILLS.glob("*/SKILL.md") if _values(skill_md, "ci")}
    for script in sorted(SKILLS.glob(f"*/scripts/{PATTERN}")):
        skills.setdefault(script.parents[1], []).append(script)
    found = []
    for skill, scripts in sorted(skills.items()):
        try:
            command, parts = ci_command(skill / "SKILL.md"), ci_parts(skill / "SKILL.md")
        except ValueError as error:
            failed[f"{BASELINE} {skill.name}"] = str(error)
            command = None
        browser = _browser(skill)
        if command:
            found.append(Step(skill, f"{skill.name}/ci", f"{BASELINE} {skill.name}", command, None, parts, browser))
        found += [
            Step(skill, f"{skill.name}/{script.name}", _name(script), (_name(script),), VERDICT, _count(script), browser) for script in scripts
        ]
    return found


def watched(step: Step) -> tuple[str, ...]:
    """Ścieżki, których zmiana uruchamia skrypt mutacji ``step``: folder skilla (z ``/`` na końcu), ``RUNNER`` i
    sprawdzenia, które uruchamiają jego mutacje; tabela, której nie da się wczytać, to wyjątek z ``exec_module``."""

    checkers = sorted({mutation.command[0] for mutation in _mutations(ROOT / step.command[0])})
    return (f"{_name(step.skill)}/", *RUNNER, *checkers)


def model_watched(step: Step) -> tuple[str, ...] | None:
    """Ścieżki, których zmiana na pull request uruchamia skrypt mutacji modelu ``step``: folder ``MODEL`` skilla (z ``/``
    na końcu), sam skrypt i sprawdzenia, które uruchamiają jego mutacje; ``None``, gdy skrypt nie ma mutacji albo któraś
    psuje plik spoza ``MODEL``. Tabela, której nie da się wczytać, to wyjątek z ``exec_module``."""

    model = f"{_name(step.skill)}/{MODEL}/"
    mutations = _mutations(ROOT / step.command[0])
    edited = {edit.file.as_posix() for mutation in mutations for edit in mutation.edits}
    if not edited or not all(name.startswith(model) for name in edited):
        return None
    return (model, step.command[0], *sorted({mutation.command[0] for mutation in mutations}))


def repeats(step: Step, chosen: Iterable[Step]) -> bool:
    """Podstawę uruchamia bez mutacji (podstawa ``check_all``) wybrany skrypt mutacji jej skilla."""

    scripts = [ROOT / other.command[0] for other in chosen if other.skill == step.skill and other.verdict]
    try:
        return any(step.command == tuple(mutation.command) for script in scripts for mutation in _mutations(script))
    except Exception:  # noqa: BLE001 - tabeli, której nie da się wczytać, podstawa nie zastąpi: biegnie polecenie ci
        return False


def znajdz() -> tuple[list[Step], dict[str, str]]:
    """Kroki wszystkich skilli (``steps``) i FAIL-e ich znalezienia: zgubione skrypty mutacji, zły klucz ``ci:`` albo
    ``ci-czesci:`` i brak jakiegokolwiek skryptu mutacji."""

    scripts = sorted(SKILLS.glob(f"*/scripts/{PATTERN}"))
    failed = _lost(scripts)
    found = steps(failed)
    if not scripts and not failed:
        failed[f"scripts/{PATTERN}"] = f"brak skryptów .agents/skills/*/scripts/{PATTERN}"
    return found, failed
