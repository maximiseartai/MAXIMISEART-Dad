"""Kroki skilli: co jest krokiem skilla w CI (podstawa ``ci:`` albo skrypt mutacji), czego pilnuje i co je uruchamia.

Skrypt mutacji skilla to ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``: dowodzi, że sprawdzenie skilla
pada na zepsutych wariantach kodu, i kończy się linią ``MUTACJE OK``. Nowy skrypt o takiej nazwie jest krokiem bez wpisu
w ``ci.yml``. Skrypt nie może zgubić się po cichu: ``Katalog.skanuj`` daje FAIL plikowi ``.py`` w skillu z ``mutation``
w nazwie, który nie pasuje do wzorca, i skryptowi mutacji wskazanemu w ``SKILL.md`` skilla, którego nie ma.

Katalog kroków skilli checkoutu to ``Katalog.skanuj(root)``. Reguły jednego skilla albo kroku (``hits``, ``guarded``,
``ci_command``, ``watched``, ``model_watched``, ``repeats``) biorą korzeń checkoutu z położenia skilla, bo skill leży
zawsze w ``<root>/.agents/skills/<skill>`` (``tests/test_miejsce_skilli.py``), więc moduł nie ma globalnego korzenia.

Skill może zadeklarować we frontmatterze ``SKILL.md`` klucz ``ci:``: polecenie (skrypt ``.py`` z repozytorium, ścieżka
od korzenia, i jego argumenty), którym CI sprawdza skill na niezmienionym kodzie, czyli krok ``PODSTAWA``, także w skillu
bez skryptu mutacji. Klucz ``ci-czesci: <n>`` mówi, że polecenie ``ci:`` dzieli się na najwyżej n części
(``MUTACJE_CZESC=k/n``, ``tools/lib/skrypt_skilla.py``); bez klucza podstawa jest niepodzielna. Klucz ``pilnuje:``, lista
globów ścieżek względem korzenia (``*`` obejmuje też ``/``), mówi, przy zmianie których plików skill obowiązuje
(``hits``).

Kiedy który krok biegnie, rozstrzyga zakres runu (``tools/lib/zakres_runu.py``), a uruchamia go
``tools/ci/wykonaj_zadanie.py`` (``run``).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
import os
from pathlib import Path
import re
from typing import Any, NamedTuple

from import_dynamiczny import modul_z_pliku
from jednostka import Klucz, Rodzaj
from ostatnie_linie import MUTACJE_OK

FOLDER_SKILLI = (".agents", "skills")
PATTERN = "check_*_mutations.py"
# Wywołanie skryptu mutacji w SKILL.md; ścieżka bez ``.agents`` na początku liczy się od folderu skilla.
MENTION = re.compile(r"[\w.\\/-]*scripts[\\/]check_\w+_mutations\.py")
BASELINE = "PODSTAWA"
# Uruchamiacz kroku: proces skryptu mutacji, jego polecenie, części i limit czasu; zmiana każdego z nich może zmienić
# werdykt każdego skryptu. Silnik, który skrypt importuje, wchodzi do ``watched`` z domknięcia importów skryptu.
LAUNCHER = ("tools/ci/wykonaj_zadanie.py", "tools/lib/kroki_skilli.py")
# Powód w ``Hits`` dla pliku w folderze skilla.
FOLDER = "folder skilla"
# Folder modelu TLA+ w skillu: skrypt mutacji, który psuje tylko pliki w nim, biegnie też na pull request (ADR 0021).
MODEL = "model"


def _root(skill: Path) -> Path:
    """Korzeń checkoutu skilla ``skill`` (folder w ``<root>/.agents/skills``)."""

    return skill.parents[len(FOLDER_SKILLI)]


def _name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


@cache
def _mutations(script: Path) -> tuple[Any, ...]:
    return tuple(modul_z_pliku(f"_mutacje_{script.parents[1].name}", script).MUTATIONS)


def _front(skill_md: Path) -> list[str]:
    """Linie frontmattera ``SKILL.md``.

    Czytniki kluczy nie parsują frontmattera jako YAML, bo plan CI biegnie systemowym ``python3`` runnera bez PyYAML
    (``test_skrypt_workflow_na_systemowym_python3_importuje_tylko_biblioteke_standardowa``).
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
        raise ValueError(f"pilnuje w {_name(skill_md, _root(skill_md.parent))} nie jest listą globów pod kluczem")
    globs = []
    for line in front[keys[0] + 1 :]:
        if not line.startswith("  - "):
            break
        globs.append(line.removeprefix("  - ").strip())
    if not globs:
        raise ValueError(f"pilnuje w {_name(skill_md, _root(skill_md.parent))} nie ma żadnego globu")
    return tuple(globs)


def ci_parts(skill_md: Path) -> int:
    """Najwięcej części polecenia ``ci`` z klucza ``ci-czesci`` frontmattera ``SKILL.md``; bez klucza 1.

    Klucz to jedna linia ``ci-czesci: <liczba całkowita od 1>``.
    """

    values = _values(skill_md, "ci-czesci")
    if not values:
        return 1
    if not values[0].strip().isdigit() or int(values[0]) < 1:
        raise ValueError(f"ci-czesci w {_name(skill_md, _root(skill_md.parent))} nie jest liczbą części od 1")
    return int(values[0])


def ci_command(skill_md: Path) -> tuple[str, ...] | None:
    """Polecenie z klucza ``ci`` frontmattera ``SKILL.md``; ``None``, gdy klucza nie ma.

    Klucz to jedna linia ``ci: <skrypt .py od korzenia repozytorium> <argumenty>``.
    """

    values = _values(skill_md, "ci")
    if not values:
        return None
    root = _root(skill_md.parent)
    command = tuple(values[0].split())
    if not command or not command[0].endswith(".py") or not (root / command[0]).is_file():
        raise ValueError(f"ci w {_name(skill_md, root)} nie zaczyna się skryptem .py z repozytorium")
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
    own = f"{_name(skill, _root(skill))}/"
    if globs is None:
        return Hits({}, f"{own}SKILL.md nie ma klucza pilnuje")
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

    @property
    def root(self) -> Path:
        return _root(self.skill)

    @property
    def folder(self) -> str:
        """Folder skilla od korzenia z ``/`` na końcu, np. ``.agents/skills/verify-x/``."""

        return f"{_name(self.skill, self.root)}/"


def _lost(root: Path, scripts: list[Path]) -> dict[str, str]:
    """Skrypty mutacji checkoutu ``root``, których runner by nie uruchomił, z powodem."""

    skills = root.joinpath(*FOLDER_SKILLI)
    lost = {
        _name(path, root): f"nazwa spoza wzorca scripts/{PATTERN}"
        for path in skills.glob("*/**/*.py")
        if "mutation" in path.name.lower() and path not in scripts
    }
    for skill_md in skills.glob("*/SKILL.md"):
        for mentioned in set(MENTION.findall(skill_md.read_text(encoding="utf-8"))):
            relative = mentioned.replace("\\", "/").removeprefix("./")
            base = root if relative.startswith(".agents/") else skill_md.parent
            path = Path(os.path.normpath(base / relative))
            if path not in scripts:
                lost.setdefault(_name(path, root), f"wskazany w {_name(skill_md, root)}, a nie ma go pod tą nazwą")
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


def _steps(root: Path, failed: dict[str, str]) -> list[Step]:
    """Kroki wszystkich skilli checkoutu ``root``, podstawa każdego skilla z kluczem ``ci`` przed jego skryptami; zły
    klucz ``ci`` albo ``ci-czesci`` trafia do ``failed``."""

    folder = root.joinpath(*FOLDER_SKILLI)
    skills: dict[Path, list[Path]] = {skill_md.parent: [] for skill_md in folder.glob("*/SKILL.md") if _values(skill_md, "ci")}
    for script in sorted(folder.glob(f"*/scripts/{PATTERN}")):
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
            Step(skill, f"{skill.name}/{script.name}", _name(script, root), (_name(script, root),), MUTACJE_OK, _count(script), browser)
            for script in scripts
        ]
    return found


def watched(step: Step, imported: Callable[[str], Iterable[str]]) -> tuple[str, ...]:
    """Ścieżki, których zmiana uruchamia skrypt mutacji ``step``: folder skilla (z ``/`` na końcu), pliki, które skrypt
    importuje (``imported``, ``Repository.imported``: silnik mutacji i jego zależności), ``LAUNCHER``, sprawdzenia,
    które uruchamiają jego mutacje, pliki, które te sprawdzenia importują (kod, którego zmiana spowalnia sprawdzenie
    albo przesuwa jego mutacje), i pliki, które mutacje psują (``Edit.file``), także te, po które sprawdzenie sięga
    procesem, ``pytest.main`` albo ścieżką, a nie importem; tabela, której nie da się wczytać, to wyjątek
    z ``exec_module``."""

    mutations = _mutations(step.root / step.command[0])
    checkers = sorted({mutation.command[0] for mutation in mutations})
    edited = {edit.file.as_posix() for mutation in mutations for edit in mutation.edits}
    reached = sorted(({name for checker in checkers for name in imported(checker)} | edited) - {step.command[0], *checkers})
    return (step.folder, *sorted(imported(step.command[0])), *LAUNCHER, *checkers, *reached)


def model_watched(step: Step, imported: Callable[[str], Iterable[str]]) -> tuple[str, ...] | None:
    """Ścieżki, których zmiana na pull request uruchamia skrypt mutacji modelu ``step``: folder ``MODEL`` skilla (z ``/``
    na końcu), sam skrypt, sprawdzenia, które uruchamiają jego mutacje, i pliki, które te sprawdzenia importują
    (``imported``, ``Repository.imported``), bo silnik modelu (``tools/lib/model_tlc.py``) daje ich werdykt; ``None``,
    gdy skrypt nie ma mutacji albo któraś psuje plik spoza ``MODEL``. Tabela, której nie da się wczytać, to wyjątek
    z ``exec_module``."""

    model = f"{step.folder}{MODEL}/"
    mutations = _mutations(step.root / step.command[0])
    edited = {edit.file.as_posix() for mutation in mutations for edit in mutation.edits}
    if not edited or not all(name.startswith(model) for name in edited):
        return None
    checkers = sorted({mutation.command[0] for mutation in mutations})
    engine = sorted({name for checker in checkers for name in imported(checker)} - {step.command[0], *checkers})
    return (model, step.command[0], *checkers, *engine)


def repeats(step: Step, chosen: Iterable[Step]) -> bool:
    """Podstawę uruchamia bez mutacji (podstawa ``check_all``) wybrany skrypt mutacji jej skilla."""

    scripts = [other.root / other.command[0] for other in chosen if other.skill == step.skill and other.verdict]
    try:
        return any(step.command == tuple(mutation.command) for script in scripts for mutation in _mutations(script))
    except Exception:  # noqa: BLE001 - tabeli, której nie da się wczytać, podstawa nie zastąpi: biegnie polecenie ci
        return False


@dataclass(frozen=True)
class Katalog:
    """Kroki skilli checkoutu ``root`` i FAIL-e ich znalezienia, jak ``Repository.scan`` w ``tools/lib/wplyw_zmiany.py``.

    ``kroki``: podstawa każdego skilla z kluczem ``ci`` przed jego skryptami mutacji, skille po nazwie. ``bledy``: FAIL
    po nazwie: zgubione skrypty mutacji, zły klucz ``ci:`` albo ``ci-czesci:`` i brak jakiegokolwiek skryptu mutacji.
    """

    root: Path
    kroki: tuple[Step, ...]
    bledy: Mapping[str, str]

    @classmethod
    def skanuj(cls, root: Path) -> Katalog:
        scripts = sorted(root.joinpath(*FOLDER_SKILLI).glob(f"*/scripts/{PATTERN}"))
        failed = _lost(root, scripts)
        found = _steps(root, failed)
        if not scripts and not failed:
            failed[f"scripts/{PATTERN}"] = f"brak skryptów .agents/skills/*/scripts/{PATTERN}"
        return cls(root, tuple(found), failed)

    def krok(self, klucz: Klucz) -> Step:
        """Krok po kluczu jednostki planu (rodzaju ``Rodzaj.SKILL``, część bez znaczenia); ``KeyError``, gdy go nie ma."""

        return {Klucz(Rodzaj.SKILL, step.key): step for step in self.kroki}[klucz.calosc]

    def skille(self, wzorzec: str = "*") -> list[Path]:
        return sorted(skill_md.parent for skill_md in self.root.joinpath(*FOLDER_SKILLI).glob(f"{wzorzec}/SKILL.md"))
