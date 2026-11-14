"""Reguła chwastu niczego nie ukrywa poza właścicielem ([ADR 0036](../../docs/adr/0036-chwast-to-regula.md)): krok
Required CI w zadaniu „Ruff, mypy” (``tests/test_zapadki.py``) i w ``tools/szybko.py``.

Reguły chwastu to reguły ast-grep z katalogów ``ruleDirs`` pliku ``sgconfig.yml`` i zakazy ``banned-api`` ruff
(``TID251``). Ukrycie to zgłoszenie, które zmiana od ``base`` chowa tańszą drogą niż zmiana reguły z jej dowodem:
tłumieniem (``# noqa``, ``# ruff: noqa``, ``# ast-grep-ignore`` na linii albo nad nią, także z powodem, terminem
i zgodą Maksa, bo wyjątek tymczasowy ``KNOWN`` reguł chwastu nie dotyczy) albo zmianą konfiguracji (wpis
w ``per-file-ignores``, ``ignore``, ``exclude``, ``ignores:`` albo ``files:`` reguły, usunięta reguła, zmieniony
``.gitignore`` albo ``.ignore``). Krok porównuje cztery zbiory zgłoszeń:

- HEAD: drzewo checkoutu (pliki śledzone i nieśledzone, a nieignorowane, jak zapadki) z konfiguracją bazy bez
  tłumień, czyli z plikami konfiguracji ruff, ``.gitignore``, ``.ignore``, ``sgconfig.yml`` i katalogami reguł
  z bazy, ``ruff --ignore-noqa`` bez ``per-file-ignores`` i ast-grep na drzewie, w którym dyrektywa
  ``ast-grep-ignore`` przestaje nią być; z tego zbioru odpada prawo właściciela (niżej);
- wobec HEAD z jego konfiguracją i tłumieniami, jak w CI;
- baza w tych samych dwóch postaciach daje ukrycia, które baza już miała.

Zgłoszenie z pierwszego zbioru, którego nie ma w drugim, to ukrycie. Tożsamość zgłoszenia to plik, pierwsza linia
węzła i reguła (``banned-api <nazwa>`` albo ``ast-grep <id>``), bez komunikatu, więc zmiana samego ``message:`` reguły
ast-grep albo ``msg`` klucza ``banned-api`` niczego nie ukrywa. Reguła przemianowana to usunięta reguła starego id
i nowa reguła, więc ukrywa każde zgłoszenie starego id, jak reguła usunięta. Ukrycie na linii dodanej od ``base`` jest
odpaleniem, a na linii starej (pozycję w bazie daje ``odpalenia_ast_grep.Changes``, więc przesunięcie i przeniesienie
pliku jej nie zmienia) tylko wtedy, gdy baza tej linii nie ukrywała, więc zmiana konfiguracji odpala na każdej linii,
którą ukrywa, a stare tłumienie zostaje. Zmieniony ``.gitattributes`` niczego nie ukrywa: ruff i ast-grep go nie
czytają, a linie dodane i ich pozycje w bazie ``Changes`` liczy z różnicy bez atrybutów.

Prawo właściciela wyznacza baza, nie HEAD: klucz ``banned-api`` w pliku, który ``per-file-ignores`` bazy zwalnia,
a kod bazy go tam używa, więc zwolnienie z całego ``TID251`` nie obejmuje innego klucza, a nowy wpis zwolnienia,
wiersz ``OWNERS`` czy zmieniony ``msg`` w HEAD niczego nie dają; dla reguły ast-grep to jej ``ignores:`` i ``files:``
w bazie. Zgłoszenia ast-grep liczą się od pierwszej linii węzła, z wyjątkiem wbudowanych reguł o dyrektywie
(``odpalenia_ast_grep.BUILTIN_MESSAGES``), które zgłasza już zapadka.

Baza, która nie jest commitem (puste drzewo w dowodzie braku fałszywych alarmów zapadek), nie ma konfiguracji reguł,
więc niczego nie ukrywa. Moduł importuje z repozytorium tylko ``repo``, ``potomne`` i ``odpalenia_ast_grep``, jak
zapadki, a poza biblioteką standardową PyYAML z ``requirements.txt``. Granice pokazują próbki ``ZNANE_LUKI_UKRYC``
w ``tests/test_zapadki.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path, PurePath
import re
import shutil
import sys
import tempfile
from typing import NamedTuple

import yaml

import odpalenia_ast_grep
import potomne
import repo

CONFIG = "sgconfig.yml"
RUFF_CONFIGS = ("pyproject.toml", "ruff.toml", ".ruff.toml")
IGNORE_FILES = (".gitignore", ".ignore")
DIRECTIVE = "ast-grep-ignore"
# Ta sama długość, więc kolumny i linie zostają, a ast-grep nie widzi już dyrektywy.
DISARMED = "ast-grep-ignor_"
BANNED = "TID251"
_BANNED_NAME = re.compile(r"`([^`]+)` is banned(?:: (.*))?", re.DOTALL)
_WITHOUT_EXEMPTIONS = ("--config", "lint.per-file-ignores = {}", "--config", "lint.extend-per-file-ignores = {}")


class Hidden(NamedTuple):
    path: str
    line: int
    rule: str  # ``banned-api <nazwa>`` albo ``ast-grep <id>``
    message: str  # komunikat reguły z bazy

    def shown(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.rule}: odpalenie reguły chwastu ukryte tłumieniem albo zmianą konfiguracji;"
            f" usuń tłumienie albo zmień regułę z jej dowodem (ADR 0036): {self.message}"
        )


@dataclass(frozen=True, order=True)
class _Finding:
    """Zgłoszenie reguły chwastu: równość, skrót i porządek biorą tylko jego tożsamość, bez komunikatu."""

    path: str
    line: int
    rule: str
    message: str = field(compare=False)


def hidden(root: Path, base: str, ast_grep: str | None) -> list[Hidden]:
    """Odpalenia ukryte w checkoucie ``root`` od ``base`` (reguły ast-grep i ``banned-api``), posortowane; brak
    ast-grep przy regule ast-grep i porażka narzędzia to ``odpalenia_ast_grep.ScanFailed``."""

    if repo.git(root, "cat-file", "-t", base).strip() != "commit":
        return []
    listed = _listed(root)
    moved = odpalenia_ast_grep.Changes(root, base)
    with potomne.commit_copy(root, base) as old, tempfile.TemporaryDirectory(prefix="ukrycia-") as folder:
        head = Path(folder)
        _copy(root, listed, head)
        _base_configs(root, base, head)
        old_listed = [name for name in repo.git(root, "ls-tree", "-r", "-z", "--name-only", base).split("\0") if name and (old / name).is_file()]
        base_visible = [*_ruff(old), *_ast_grep(old, old_listed, ast_grep)]
        unexempted = _ruff(old, "--ignore-noqa", "--select", BANNED, *_WITHOUT_EXEMPTIONS)
        exempted = set(_ruff(old, "--ignore-noqa", "--select", BANNED))
        owners = {(finding.path, finding.rule) for finding in unexempted if finding not in exempted}
        _disarm(old, old_listed)
        base_bare = [*exempted, *_ast_grep(old, old_listed, ast_grep)]
        present = [name for name in listed if (head / name).is_file()]
        _disarm(head, present)
        bare = [*_ruff(head, "--ignore-noqa", "--select", BANNED, *_WITHOUT_EXEMPTIONS), *_ast_grep(head, present, ast_grep)]
    visible = set(_ruff(root)) | set(_ast_grep(root, listed, ast_grep))
    before = {(finding.path, finding.line, finding.rule) for finding in set(base_bare) - set(base_visible)}
    found = []
    for finding in sorted(set(bare) - visible):
        place = moved.old(finding.path, finding.line)
        owned = finding.rule.startswith("banned-api ") and (moved.base_path(finding.path), finding.rule) in owners
        if not owned and (place is None or (*place, finding.rule) not in before):
            found.append(Hidden(finding.path, finding.line, finding.rule, finding.message))
    return found


def _listed(root: Path) -> list[str]:
    """Pliki checkoutu, które widzą zapadki: śledzone i nieśledzone, a nieignorowane."""

    names = repo.git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    return sorted(name for name in set(names) if name and (root / name).is_file())


def _copy(root: Path, names: Iterable[str], target: Path) -> None:
    for name in names:
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target / name)


def _base_configs(root: Path, base: str, head: Path) -> None:
    """Pliki konfiguracji reguł z ``base`` w drzewie ``head``: ruff, ``.gitignore``, ``sgconfig.yml`` i katalogi
    reguł; plik konfiguracji, którego baza nie ma, znika."""

    old = [name for name in repo.git(root, "ls-tree", "-r", "-z", "--name-only", base).split("\0") if name]
    configs = {name for name in old if PurePath(name).name in (*RUFF_CONFIGS, *IGNORE_FILES, CONFIG)}
    current = {path.relative_to(head).as_posix() for path in head.rglob("*") if path.is_file() and path.name in (*RUFF_CONFIGS, *IGNORE_FILES, CONFIG)}
    for directory in (*_rule_dirs(head), *(_rule_dirs_in(repo.git(root, "show", f"{base}:{CONFIG}")) if CONFIG in old else [])):
        shutil.rmtree(head / directory, ignore_errors=True)
        configs |= {name for name in old if name.startswith(f"{directory.rstrip('/')}/")}
    for name in current - configs:
        (head / name).unlink()
    for name in configs:
        (head / name).parent.mkdir(parents=True, exist_ok=True)
        (head / name).write_bytes(repo.git(root, "show", f"{base}:{name}").encode("utf-8"))


def _rule_dirs(tree: Path) -> list[str]:
    config = tree / CONFIG
    return _rule_dirs_in(config.read_text(encoding="utf-8")) if config.is_file() else []


def _rule_dirs_in(text: str) -> list[str]:
    """Katalogi ``ruleDirs`` treści ``sgconfig.yml``."""

    return [str(directory) for directory in (yaml.safe_load(text) or {}).get("ruleDirs") or []]


def _disarm(tree: Path, names: Iterable[str]) -> None:
    """Dyrektywa ``ast-grep-ignore`` w każdym pliku drzewa przestaje nią być, a reszta treści zostaje."""

    for name in names:
        path = tree / name
        data = path.read_bytes()
        if DIRECTIVE.encode() in data:
            path.write_bytes(data.replace(DIRECTIVE.encode(), DISARMED.encode()))


def _ruff(tree: Path, *options: str) -> list[_Finding]:
    """Zgłoszenia ``TID251`` ruff w drzewie ``tree`` z jego konfiguracją i opcjami ``options``."""

    done = potomne.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--exit-zero", "--output-format", "json", *options], cwd=tree)
    if done.returncode:
        raise odpalenia_ast_grep.ScanFailed(f"ruff check zakończył się kodem {done.returncode}:\n{done.stderr}")
    found = []
    for entry in json.loads(done.stdout or "[]"):
        banned = _BANNED_NAME.match(str(entry.get("message", ""))) if entry.get("code") == BANNED else None
        if banned:
            path = Path(entry["filename"]).resolve().relative_to(tree.resolve()).as_posix()
            found.append(_Finding(path, int(entry["location"]["row"]), f"banned-api {banned[1]}", banned[2] or ""))
    return found


def _ast_grep(tree: Path, names: Sequence[str], ast_grep: str | None) -> list[_Finding]:
    """Zgłoszenia reguł ast-grep z ``sgconfig.yml`` drzewa ``tree`` w plikach ``names`` (podanych jawnie, jak
    w zapadce), bez wbudowanych reguł o dyrektywie."""

    if not _has_rules(tree):
        return []
    if ast_grep is None:
        raise odpalenia_ast_grep.ScanFailed(odpalenia_ast_grep.INSTALL)
    found = []
    for start in range(0, len(names), odpalenia_ast_grep.PATHS_PER_SCAN):
        chunk = names[start : start + odpalenia_ast_grep.PATHS_PER_SCAN]
        scan = potomne.run([ast_grep, "scan", "--config", CONFIG, "--json=stream", "--color=never", "--error", "--", *chunk], cwd=tree)
        if scan.returncode not in (0, 1) or bool(scan.stdout) != (scan.returncode == 1):
            raise odpalenia_ast_grep.ScanFailed(f"ast-grep scan zakończył się kodem {scan.returncode}:\n{scan.stderr}")
        for match in map(json.loads, scan.stdout.splitlines()):
            if match["ruleId"] not in odpalenia_ast_grep.BUILTIN_MESSAGES:
                found.append(_Finding(PurePath(match["file"]).as_posix(), match["range"]["start"]["line"] + 1, f"ast-grep {match['ruleId']}", match["message"]))
    return found


def _has_rules(tree: Path) -> bool:
    return any(path.suffix in (".yml", ".yaml") for directory in _rule_dirs(tree) for path in (tree / directory).rglob("*"))
