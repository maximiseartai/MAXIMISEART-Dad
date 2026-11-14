"""Linie dodane od bazy i odpalenia reguł ast-grep na nich: jedna droga zapadek ``tests/test_zapadki.py`` (także
``syntax_rules``), kroku „niczego nie ukrywa” i dowodu reguły ``tools/na_scalonych_pr.py --regula``.

Linie dodane od bazy i pozycję w bazie każdej innej linii daje ``Changes``, jedyna droga do różnicy od bazy zapadek,
kroku „niczego nie ukrywa” (``ukrycia_regul``) i dowodu reguły: ``git diff -U0 -M`` od bazy w checkoucie (z
niezacommitowanymi zmianami) i całe pliki nieśledzone, bez ignorowanych przez ``.gitignore``. Różnica nie zależy od
atrybutów z drzewa ani od konfiguracji różnicy: atrybuty bierze z pustego drzewa (``attr.tree``, git ≥ 2.43) bez pliku
``core.attributesFile``, więc ``-diff``, ``binary``, ``diff=`` ani ``filter=`` z ``.gitattributes`` (także
w podkatalogu) linii nie chowają, a ``--text``, ``--no-textconv``, ``--no-ext-diff`` i stałe przedrostki ``a/``
i ``b/`` wyłączają różnicę binarną, ``textconv``, zewnętrzny program i przedrostki z konfiguracji, także dla atrybutów
spoza drzewa. Granica: ``.git/info/attributes`` i plik atrybutów systemu git czyta dalej, więc ich ``filter=`` albo
``working-tree-encoding`` zmienia linie; PR żadnego z nich nie zmienia (próbka ``ZNANE_LUKI_UKRYC``
w ``tests/test_zapadki.py``). Plik binarny ma więc dodane linie jak każdy, bajt spoza UTF-8 staje się znakiem
zastępczym, a dowiązanie do katalogu i dowiązanie zerwane nie mają żadnej.

Linię różnicy rozpoznaje struktura: nagłówek pliku od ``diff --git`` do pierwszego ``@@``, a w hunku tyle linii, ile
mówi jego ``@@``, więc dodana linia ``++ x`` (w różnicy ``+++ x``) jest linią, nie nagłówkiem. Linię kończy tylko
``\\n``, jak liczy ją git, a nie każdy znak, na którym dzieli ``str.splitlines`` (``\\x1c``, ``\\x0c``, samotne ``\\r``,
U+2028): inaczej taki znak w dodanej linii zjadałby następną. Linia różna tylko końcem CRLF nie jest dodana: checkout
na Windows ma CRLF w drzewie, a testy ustawiają ``core.autocrlf=false`` (``tests/fixtures/git_config.py``).

Odpalenie reguły liczy się, gdy węzeł, który reguła zgłasza, obejmuje którąkolwiek linię dodaną, a jego linia to
pierwsza dodana linia węzła; linia dodana w środku starej instrukcji odpala więc całą instrukcję. ast-grep dostaje
jawnie każdy plik z dodaną linią, a jawnie podaną ścieżkę ast-grep 0.51.0 skanuje zawsze, także w katalogu ukrytym jak
``.agents/`` i śledzoną mimo ``.gitignore``; o tym, w których z nich reguła szuka, decydują jej pola ``files:``
i ``ignores:``. Granica: plik bez rozszerzenia (``tools/hooks/pre-push``) ast-grep pomija, bo język bierze
z rozszerzenia, a ``sgconfig.yml`` nie ma ``languageGlobs``. ``--error`` bez nazw reguł ustawia ważność error każdej
regule (dokumentacja ast-grep 0.51.0: „all rules will be set to error”), więc odpala także reguła z ``severity: off``
i wbudowane reguły o dyrektywie ``ast-grep-ignore`` (``BUILTIN_MESSAGES``). Moduł importuje tylko bibliotekę
standardową, ``repo`` i ``potomne`` (same z biblioteki standardowej), bo zapadki biegną też w kopii starego commitu.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import json
from pathlib import Path, PurePath
import re
from typing import Final, NamedTuple

import potomne
import repo

# Najwięcej ścieżek w jednym ``ast-grep scan``: wiersz polecenia na Windows mieści 32 767 znaków.
PATHS_PER_SCAN = 200
# Wbudowane reguły ast-grep o dyrektywie ``ast-grep-ignore`` → komunikat zamiast angielskiego komunikatu ast-grep.
BUILTIN_MESSAGES: Final = {
    "no-suppress-all": "dyrektywa ast-grep-ignore bez nazw reguł wyłącza każdą regułę: usuń ją i popraw kod według"
    " komunikatu reguły, którą wyłączała",
    "unused-suppression": "dyrektywa ast-grep-ignore niczego nie wyłącza: usuń ją",
}
INSTALL = "brak ast-grep z dodatku dev: uruchom python3 tools/setup_worktree.py (Windows: py -3 tools/setup_worktree.py)"
# Pusty obiekt drzewa gita: atrybuty z niego (``attr.tree``) to brak atrybutów.
EMPTY_TREE: Final = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_FILE = "diff --git "
_HUNK = re.compile(r"@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@")


class Finding(NamedTuple):
    path: str
    line: int  # pierwsza dodana linia węzła, od 1
    rule: str
    message: str


class ScanFailed(ValueError):
    """Brak ast-grep przy dodanej linii albo ast-grep z kodem innym niż 0 i 1 lub niezgodnym z wyjściem (np. plik
    reguły, którego nie wczyta): porażka, nie brak odpaleń."""


def unscoped(rule: Mapping[str, object]) -> str | None:
    """Przyczyna z poleceniem naprawy, gdy reguła ast-grep (dokument YAML) nie ma niepustego pola ``files:``: zapadka
    podaje ast-grep każdy plik repozytorium z dodaną linią, więc reguła bez ``files:`` obejmowałaby całe repozytorium,
    a dowód reguły takiej nie przyjmuje; ``None``, gdy pole jest."""

    if rule.get("files"):
        return None
    return (
        f"{rule.get('id')}: reguła bez pola files: obejmuje każdy plik repozytorium; dopisz files: z globami plików, w"
        " których obowiązuje (np. src/**/*.py albo .agents/skills/**/*.py), a wyjątki w ignores:"
    )


class _Hunk(NamedTuple):
    old: int
    old_count: int
    new: int
    new_count: int


class Changes:
    """Zmiana checkoutu ``root`` od ``base`` w plikach ``pathspec`` (ścieżka gita): linie dodane i pozycja w bazie
    każdej innej linii. Plik nieśledzony i plik nowy mają tylko linie dodane, a plik przeniesiony ścieżkę z bazy."""

    def __init__(self, root: Path, base: str, pathspec: str = ".") -> None:
        self._root = root
        listed = repo.git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", pathspec).split("\0")
        self._untracked = sorted(name for name in set(listed) if name)
        self._new = set(self._untracked)
        self._renamed: dict[str, str] = {}
        self._hunks: dict[str, list[_Hunk]] = {}
        self._added: list[tuple[str, int, str]] = []
        options = ("-U0", "-M", "--text", "--no-textconv", "--no-ext-diff", "--no-color", "--ignore-cr-at-eol", "--src-prefix=a/", "--dst-prefix=b/")
        self._read(repo.git(root, "-c", "core.attributesFile=", "-c", f"attr.tree={EMPTY_TREE}", "diff", *options, base, "--", pathspec))

    def _read(self, diff: str) -> None:
        old_path: str | None = None
        path: str | None = None
        header = False
        number = old_left = new_left = 0
        for line in _lines(diff):
            if old_left or new_left:
                if line.startswith("+"):
                    new_left -= 1
                    if path is not None:
                        self._added.append((path, number, line[1:]))
                    number += 1
                elif line.startswith("-"):
                    old_left -= 1
            elif line.startswith(_FILE):
                old_path = path = None
                header = True
            elif hunk := _HUNK.match(line):
                header = False
                number, old_left, new_left = int(hunk["new"]), int(hunk["old_count"] or 1), int(hunk["new_count"] or 1)
                if path is not None:
                    self._hunks.setdefault(path, []).append(_Hunk(int(hunk["old"]), old_left, number, new_left))
            elif header and line.startswith("--- "):
                old_path = None if line == "--- /dev/null" else _name(line, "--- a/")
            elif header and line.startswith("+++ "):
                path = None if line == "+++ /dev/null" else _name(line, "+++ b/")
                if path is not None and old_path is None:
                    self._new.add(path)
                elif path is not None and old_path is not None and old_path != path:
                    self._renamed[path] = old_path
            elif header and line.startswith("rename from "):
                old_path = line.removeprefix("rename from ")
            elif header and line.startswith("rename to "):
                path = line.removeprefix("rename to ")
                if old_path is not None:
                    self._renamed[path] = old_path

    def added(self) -> Iterator[tuple[str, int, str]]:
        """Linie dodane: ścieżka, numer linii od 1 i treść; plik nieśledzony cały."""

        yield from self._added
        for path in self._untracked:
            if (self._root / path).is_file():
                yield from ((path, number, line) for number, line in enumerate(_lines((self._root / path).read_bytes().decode("utf-8", errors="replace")), start=1))

    def base_path(self, path: str) -> str | None:
        """Ścieżka pliku ``path`` w bazie; ``None`` dla pliku, którego baza nie ma."""

        return None if path in self._new else self._renamed.get(path, path)

    def old(self, path: str, line: int) -> tuple[str, int] | None:
        """Ścieżka w bazie i numer w niej linii ``line`` pliku ``path``; ``None`` dla linii dodanej."""

        if path in self._new:
            return None
        shift = 0
        for hunk in self._hunks.get(path, []):
            if hunk.new_count and hunk.new <= line < hunk.new + hunk.new_count:
                return None
            if (hunk.new + hunk.new_count - 1 if hunk.new_count else hunk.new) < line:
                shift += hunk.new_count - hunk.old_count
        return self._renamed.get(path, path), line - shift


def _name(line: str, prefix: str) -> str:
    """Ścieżka z nagłówka ``---`` albo ``+++``; nazwę ze spacją git kończy tabulatorem (zgodność z GNU patch)."""

    return line.removeprefix(prefix).removesuffix("\t")


def _lines(text: str) -> list[str]:
    """Linie tekstu, jak liczy je git: kończy je tylko ``\\n``, a ``\\r`` przed nim nie należy do treści."""

    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


def added_lines(root: Path, base: str, folder: str, pattern: str = "*.py") -> Iterator[tuple[str, int, str]]:
    """Linie plików ``pattern`` w ``folder`` checkoutu ``root``, które zmiana od ``base`` dodaje: ścieżka, numer linii
    od 1 i treść."""

    return Changes(root, base, f"{folder}/{pattern}").added()


def on_added_lines(root: Path, base: str, rules: Sequence[str], ast_grep: str | None) -> list[Finding]:
    """Odpalenia reguł ``rules`` (``--config sgconfig.yml`` albo ``--rule PLIK.yml``) w checkoucie ``root``, których
    węzeł obejmuje linię dodaną od ``base``, posortowane. Bez linii dodanej ast-grep nie biegnie, więc ``ast_grep``
    może być ``None``; z linią dodaną brak ast-grep i jego porażka to ``ScanFailed``."""

    added: dict[str, set[int]] = {}
    for path, number, _ in added_lines(root, base, ".", "*"):
        added.setdefault(path, set()).add(number)
    if not added:
        return []
    if ast_grep is None:
        raise ScanFailed(INSTALL)
    paths = sorted(added)
    found = []
    for start in range(0, len(paths), PATHS_PER_SCAN):
        scan = potomne.run([ast_grep, "scan", *rules, "--json=stream", "--color=never", "--error", "--", *paths[start : start + PATHS_PER_SCAN]], cwd=root)
        if scan.returncode not in (0, 1) or bool(scan.stdout) != (scan.returncode == 1):
            raise ScanFailed(f"ast-grep scan zakończył się kodem {scan.returncode}:\n{scan.stderr}")
        for match in map(json.loads, scan.stdout.splitlines()):
            path = PurePath(match["file"]).as_posix()
            lines = range(match["range"]["start"]["line"] + 1, match["range"]["end"]["line"] + 2)
            if new := sorted(added.get(path, set()).intersection(lines)):
                found.append(Finding(path, new[0], match["ruleId"], BUILTIN_MESSAGES.get(match["ruleId"], match["message"])))
    return sorted(found)
