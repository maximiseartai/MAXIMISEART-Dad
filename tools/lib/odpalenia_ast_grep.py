"""Linie dodane od bazy i odpalenia reguł ast-grep na nich: jedna droga zapadek ``tests/test_zapadki.py`` (także
``syntax_rules``) i dowodu reguły ``tools/na_scalonych_pr.py --regula``.

Linie dodane od bazy daje ``Changes``, jedyna droga do różnicy od bazy zapadek i dowodu reguły: ``git diff -U0 -M`` od
bazy w checkoucie (z niezacommitowanymi zmianami) i całe pliki nieśledzone, bez ignorowanych przez ``.gitignore``
i ``.git/info/exclude``. Różnica nie zależy od środowiska, atrybutów z drzewa ani konfiguracji gita poza ``.git/info``,
więc jest taka, jak w CI, gdzie gita nikt nie konfiguruje:

- git biegnie przez ``repo.git(isolated=True)``: bez zmiennych wołającego (``GIT_DIFF_OPTS``, ``GIT_*_PATHSPECS``,
  ``GIT_CONFIG_*``, ``XDG_CONFIG_HOME``), bez konfiguracji i atrybutów systemu, bez konfiguracji użytkownika, bez
  obiektów podmienionych przez ``refs/replace`` i z ``root`` jako drzewem roboczym;
- konfigurację checkoutu (``.git/config``), której żadna zmienna nie wyłącza, nadpisuje wywołanie tam, gdzie zmienia
  pliki albo linie: ``core.excludesFile=``, ``core.fsmonitor=false`` (hook nie mówi gitowi, które pliki są bez
  zmian), atrybuty z pustego drzewa (``attr.tree``, git ≥ 2.43) bez pliku ``core.attributesFile``, więc ``-diff``,
  ``binary``, ``diff=`` ani ``filter=`` z ``.gitattributes`` (także w podkatalogu) linii nie chowają, oraz opcje
  ``_DIFF_OPTIONS``, które wyłączają różnicę binarną, ``textconv`` i zewnętrzny program (także dla atrybutów spoza
  drzewa), kolory, przedrostki z konfiguracji, ``diff.renames``, ``diff.algorithm`` i ``diff.indentHeuristic``;
- ``diff.context``, ``diff.interHunkContext`` i ``diff.suppressBlankEmpty`` dokładają tylko linie kontekstu, które
  parser liczy (niżej), a pozostałe klucze ``diff.*`` z ``git help --config`` gita 2.50 linii dodanych nie zmieniają:
  kolejność plików, ścieżki względem ``root``, ``diff.renameLimit`` (mniej przeniesień to więcej linii dodanych, nie
  mniej), podmoduły, których repozytorium nie ma, i wyjścia inne niż łatka.

Granica: różnicę jak w CI gwarantuje świeży checkout Required CI, a lokalny stan checkoutu, którego PR nie zmienia,
a żadna zmienna ani opcja gita nie wyłącza, to znana luka: bity indeksu ``assume-unchanged`` i ``skip-worktree``
chowają zmianę pliku śledzonego, ``.git/info/exclude`` plik nieśledzony, a ``filter=`` albo ``working-tree-encoding``
z ``.git/info/attributes`` zmienia linie (próbki ``ZNANE_LUKI_ZMIAN`` w ``tests/test_zapadki.py``). Plik binarny ma
dodane linie jak każdy, bajt spoza UTF-8 staje się znakiem zastępczym, a dowiązanie do katalogu i dowiązanie zerwane
nie mają żadnej.

Linię różnicy rozpoznaje struktura: nagłówek pliku od ``diff --git`` do pierwszego ``@@``, a w hunku tyle linii bazy
i zmiany, ile mówi jego ``@@``: linia kontekstu (spacja, przy ``diff.suppressBlankEmpty`` linia pusta) liczy się do
obu, ``-`` do bazy, ``+`` do zmiany, a znacznik ``\\ No newline at end of file`` do żadnej. Kontekst, także ten, który
skleja bliskie hunki, nie zmienia więc numeru linii dodanej ani granicy pliku, a dodana linia ``++ x`` (w różnicy
``+++ x``) jest linią, nie nagłówkiem. Linię kończy tylko ``\\n``, jak liczy ją git, a nie każdy znak, na którym dzieli
``str.splitlines`` (``\\x1c``, ``\\x0c``, samotne ``\\r``, U+2028): inaczej taki znak w dodanej linii zjadałby
następną. Linia różna tylko końcem CRLF nie jest dodana: checkout na Windows ma CRLF
w drzewie, a testy ustawiają ``core.autocrlf=false`` (``tests/fixtures/git_config.py``).

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
_HUNK = re.compile(r"@@ -\d+(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@")


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


# Opcje ``git diff`` w ``Changes`` (docstring modułu): bez kontekstu, z przeniesieniami, bez różnicy binarnej,
# ``textconv``, zewnętrznego programu, kolorów i końca CRLF, ze stałymi przedrostkami, algorytmem i heurystyką wcięć.
_DIFF_OPTIONS: Final = (
    "-U0",
    "-M",
    "--text",
    "--no-textconv",
    "--no-ext-diff",
    "--no-color",
    "--ignore-cr-at-eol",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--diff-algorithm=myers",
    "--indent-heuristic",
)


class Changes:
    """Zmiana checkoutu ``root`` od ``base`` w plikach ``pathspec`` (ścieżka gita): jej linie dodane, a pliku
    nieśledzonego każda linia."""

    def __init__(self, root: Path, base: str, pathspec: str = ".") -> None:
        self._root = root
        # Konfiguracja checkoutu, której ``isolated`` nie wyłącza, a która zmienia pliki albo linie różnicy.
        checkout = ("-c", "core.excludesFile=", "-c", "core.attributesFile=", "-c", f"attr.tree={EMPTY_TREE}", "-c", "core.fsmonitor=false")
        listed = repo.git(root, *checkout, "ls-files", "-z", "--others", "--exclude-standard", "--", pathspec, isolated=True).split("\0")
        self._untracked = sorted(name for name in set(listed) if name)
        self._added: list[tuple[str, int, str]] = []
        self._read(repo.git(root, *checkout, "diff", *_DIFF_OPTIONS, base, "--", pathspec, isolated=True))

    def _read(self, diff: str) -> None:
        path: str | None = None
        header = False
        # Linie bazy i zmiany, które hunk ma jeszcze według ``@@``, i numer następnej linii zmiany.
        old_left = new_left = new_next = 0
        for line in _lines(diff):
            if old_left or new_left:
                if line.startswith("\\"):
                    continue
                if line.startswith("+"):
                    if path is not None:
                        self._added.append((path, new_next, line[1:]))
                    new_next, new_left = new_next + 1, new_left - 1
                elif line.startswith("-"):
                    old_left -= 1
                else:
                    old_left, new_next, new_left = old_left - 1, new_next + 1, new_left - 1
            elif line.startswith(_FILE):
                path, header = None, True
            elif hunk := _HUNK.match(line):
                header = False
                old_left, new_left, new_next = int(hunk["old_count"] or 1), int(hunk["new_count"] or 1), int(hunk["new"])
            elif header and line.startswith("+++ "):
                # Nazwę ze spacją git kończy tabulatorem (zgodność z GNU patch).
                path = line.removeprefix("+++ b/").removesuffix("\t") if line != "+++ /dev/null" else None

    def added(self) -> Iterator[tuple[str, int, str]]:
        """Linie dodane: ścieżka, numer linii od 1 i treść; plik nieśledzony cały."""

        yield from self._added
        for path in self._untracked:
            if (self._root / path).is_file():
                yield from ((path, number, line) for number, line in enumerate(_lines((self._root / path).read_bytes().decode("utf-8", errors="replace")), start=1))


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
