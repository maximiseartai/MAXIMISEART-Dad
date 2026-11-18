"""Ciche cofnięcie scalonej zmiany: plik, który zmiana PR (od merge-base z bazą do HEAD) zmienia na treść, jaką miał
tuż przed jednym z ostatnich ``DEPTH`` commitów bazy po ``--first-parent``, który go zmienił. Tak wychodzi commit
złożony z drzewa roboczego starszej bazy i przeniesiony na nowszą (``git reset --soft``, kopia plików, stash): diff PR
cofa wtedy scalone PR-y, których opis PR nie zna (#2100 r1: 25 z 28 plików).

| Przypadek | Wynik |
|---|---|
| plik HEAD ma treść sprzed commitu bazy, który go zmienił | cofnięcie |
| plik HEAD ma inną treść niż przed każdym z tych commitów | bez cofnięcia |
| PR usuwa plik, który dodał commit bazy | bez cofnięcia (usunięcie to zwykła zmiana PR) |
| PR przywraca plik, który usunął commit bazy | cofnięcie |
| commit PR z linią ``This reverts commit <SHA>`` (``git revert``) dla tego commitu bazy | bez cofnięcia |
| commit bazy starszy niż ostatnie ``DEPTH`` commitów bazy | bez cofnięcia (granica) |

Odmawiają ``--przeglad`` (krok 1 recenzenta) i zgoda na merge w ``tools/scal_pr.py``.
"""

from __future__ import annotations

import re
import subprocess

import repo
from repo import ROOT

DEPTH = 100
REVERTS = re.compile(r"^This reverts commit ([0-9a-f]{40})\b", re.MULTILINE)


def _object(revision: str, path: str) -> str | None:
    try:
        return repo.git(ROOT, "rev-parse", "--verify", "--quiet", f"{revision}:{path}").strip()
    except subprocess.CalledProcessError:
        return None


def reverted(fork: str, head: str) -> list[str]:
    """Pliki zmiany od ``fork`` (merge-base z bazą) do ``head``, które wracają do treści sprzed commitu bazy, każdy
    z tym commitem: ``plik (sprzed <sha> <temat>)``."""

    meant = set(REVERTS.findall(repo.git(ROOT, "log", "--format=%B", f"{fork}..{head}")))
    now = {path: found for path in repo.changed(ROOT, fork, head) if (found := _object(head, path)) is not None}
    reverts: dict[str, str] = {}
    # Commit bazy to linia ``\0<sha> <temat>``, a pod nią ścieżki, które zmienił względem pierwszego rodzica.
    log = repo.git(ROOT, "log", "--first-parent", f"--max-count={DEPTH}", "--no-renames", "--name-only", "--format=%x00%H %s", fork)
    for entry in log.split("\0")[1:]:
        title, *paths = entry.splitlines()
        commit = title.split(" ", 1)[0]
        for path in paths:
            if path in now and path not in reverts and commit not in meant and _object(f"{commit}^1", path) == now[path]:
                reverts[path] = f"{path} (sprzed {commit[:10]} {title.split(' ', 1)[1]})"
    return [reverts[path] for path in sorted(reverts)]


def problem(fork: str, head: str) -> str | None:
    """Przyczyna odmowy, gdy zmiana PR po cichu cofa scaloną zmianę bazy; ``None`` bez cofnięcia."""

    if not (found := reverted(fork, head)):
        return None
    return (
        f"cofnięcie: zmiana PR przywraca treść sprzed scalonych commitów bazy: {'; '.join(found)}; zbuduj commit na"
        " aktualnej bazie z samą swoją zmianą (git diff starej bazy do swojego commitu nałożony przez git apply --3way),"
        " a scaloną zmianę cofaj tylko przez git revert jej commitu"
    )
