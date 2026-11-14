"""Linie dodane od bazy i odpalenia reguł ast-grep na nich: jedna droga zapadek ``tests/test_zapadki.py`` (także
``syntax_rules``) i dowodu reguły ``tools/na_scalonych_pr.py --regula``.

Linie dodane to ``git diff`` od bazy w checkoucie (z niezacommitowanymi zmianami) i całe pliki nieśledzone, bez
ignorowanych przez ``.gitignore``. Linię różnicy rozpoznaje struktura: nagłówek pliku od ``diff --git`` do pierwszego
``@@``, a w hunku tyle linii, ile mówi jego ``@@``, więc dodana linia ``++ x`` (w różnicy ``+++ x``) jest linią, nie
nagłówkiem. Linia różna tylko końcem CRLF nie jest dodana: checkout na Windows ma CRLF w drzewie, a testy ustawiają
``core.autocrlf=false`` (``tests/fixtures/git_config.py``). Plik, który git różnicuje jako binarny (także ``-text``
w ``.gitattributes``), nie ma dodanych linii; nieśledzony plik binarny ma linie ze znakami zastępczymi, a dowiązanie do
katalogu i dowiązanie zerwane nie mają żadnej; bajt spoza UTF-8 staje się znakiem zastępczym.

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

from collections.abc import Iterator, Sequence
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
_FILE = "diff --git "
_HUNK = re.compile(r"@@ -\d+(?:,(?P<old>\d+))? \+(?P<start>\d+)(?:,(?P<new>\d+))? @@")


class Finding(NamedTuple):
    path: str
    line: int  # pierwsza dodana linia węzła, od 1
    rule: str
    message: str


class ScanFailed(ValueError):
    """Brak ast-grep przy dodanej linii albo ast-grep z kodem innym niż 0 i 1 lub niezgodnym z wyjściem (np. plik
    reguły, którego nie wczyta): porażka, nie brak odpaleń."""


def added_lines(root: Path, base: str, folder: str, pattern: str = "*.py") -> Iterator[tuple[str, int, str]]:
    """Linie plików ``pattern`` w ``folder`` checkoutu ``root``, które zmiana od ``base`` dodaje: ścieżka, numer linii
    od 1 i treść."""

    path = None
    header = False
    number = old_left = new_left = 0
    changed = repo.git(root, "diff", "-U0", "--no-color", "--no-ext-diff", "--ignore-cr-at-eol", base, "--", f"{folder}/{pattern}")
    for line in changed.splitlines():
        if old_left or new_left:
            if line.startswith("+"):
                new_left -= 1
                if path is not None:
                    yield path, number, line[1:]
                number += 1
            elif line.startswith("-"):
                old_left -= 1
        elif line.startswith(_FILE):
            path, header = None, True
        elif hunk := _HUNK.match(line):
            header = False
            number, old_left, new_left = int(hunk["start"]), int(hunk["old"] or 1), int(hunk["new"] or 1)
        elif header and line.startswith("+++ "):
            # Nazwę ze spacją git kończy tabulatorem (zgodność z GNU patch).
            path = line.removeprefix("+++ b/").removesuffix("\t") if line != "+++ /dev/null" else None
    for path in repo.git(root, "ls-files", "--others", "--exclude-standard", "--", f"{folder}/{pattern}").splitlines():
        if (root / path).is_file():
            text = (root / path).read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                yield path, number, line


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
