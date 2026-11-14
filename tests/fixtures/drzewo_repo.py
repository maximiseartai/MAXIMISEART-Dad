"""Strażnik drzewa repozytorium: sesja testów nie zostawia w nim pliku z liniami dodanymi od ``HEAD``.

„Dodane” liczy ``odpalenia_ast_grep.Changes`` tak samo jak zapadka reguł ast-grep (``tests/test_zapadki.py``): plik
nieśledzony, którego nie wyklucza ``.gitignore`` repozytorium, cały, i plik śledzony, którego treść git widzi inaczej niż
w ``HEAD``, bez konfiguracji systemu (na Windows także bez ``core.autocrlf``). Plik zostawiony przez test w drzewie
wywraca tę zapadkę w tym samym zadaniu CI zależnie od kolejności testów (#1864), więc strażnik łapie go od razu i podaje
jego ścieżkę. Pliki, które miały linie dodane już na starcie sesji (zmiana autora), go nie dotyczą, a checkout bez
commitu (kopia repozytorium w teście) nie ma od czego liczyć, więc strażnik w nim milczy.
"""

from __future__ import annotations

from pathlib import Path

import odpalenia_ast_grep
import repo

REPO = Path(__file__).resolve().parents[2]


def files_with_added_lines() -> frozenset[str] | None:
    """Pliki checkoutu ``REPO`` z linią dodaną od ``HEAD``; ``None``, gdy checkout nie ma jeszcze commitu."""

    if not repo.succeeds(REPO, "rev-parse", "--verify", "--quiet", "HEAD"):
        return None
    return frozenset(path for path, _, _ in odpalenia_ast_grep.Changes(REPO, "HEAD").added())


def left_behind(before: frozenset[str]) -> list[str]:
    """Pliki z linią dodaną od ``HEAD``, których nie było w ``before``."""

    return sorted((files_with_added_lines() or frozenset()) - before)
