"""Repozytorium narzędzi z ``tools/``: korzeń checkoutu, gałąź bazowa i jedyna droga do gita.

Narzędzie pyta gita tylko przez ten moduł, a ``tests/test_potomne.py`` odrzuca polecenie ``["git", …]`` w innym pliku
``tools/`` niż ten i ``potomne.py``. Każde zapytanie biegnie tak samo:

- ścieżki spoza ASCII bez cytowania (``core.quotePath=false``), a wyjście w UTF-8 z ``errors="replace"`` i bez
  zamiany samotnego ``\\r`` z treści pliku na koniec linii, więc linie są takie, jak liczy je git;
- bez odświeżania indeksu (``GIT_OPTIONAL_LOCKS=0``): raport o cudzym worktree niczego w nim nie zapisuje;
- bez konserwacji w tle (``maintenance.auto=false``): od Gita 2.54 ``fetch`` i ``commit`` uruchamiają odłączone
  ``git maintenance run --auto``, którego ``git worktree prune`` usuwa kopię zakładaną właśnie przez
  ``potomne.commit_copy`` (#312);
- z limitem czasu ``TIMEOUT_S``, więc zawieszony git kończy się ``subprocess.TimeoutExpired``.

``git(..., isolated=True)`` daje gitowi środowisko z listy dozwolonych zamiast środowiska wołającego: ``PATH``
i ``SYSTEMROOT`` (Windows) wołającego, pusty katalog jako ``HOME``, ``LANG=C``, ``GIT_CONFIG_NOSYSTEM=1``,
``GIT_ATTR_NOSYSTEM=1``, ``GIT_CONFIG_GLOBAL`` równe ``os.devnull`` i ``GIT_WORK_TREE`` równe ``root``. Taki git nie
czyta więc żadnej zmiennej ``GIT_*`` ani ``XDG_CONFIG_HOME`` wołającego, konfiguracji ani atrybutów systemu,
konfiguracji użytkownika ani plików ``ignore`` i ``attributes`` z ``~/.config/git``, a drzewem roboczym jest ``root``
także wbrew ``core.worktree``; czyta tylko konfigurację repozytorium (``.git/config``) i ``.git/info``, których żadna
zmienna nie wyłącza.

``git`` i ``succeeds`` to szybkie, lokalne podpolecenia (``FAST_GIT`` w ``tests/test_potomne.py``). Polecenie, które
trwa albo sięga sieci (fetch, push, zapis drzewa), idzie przez ``run_git``, czyli ``potomne.run``. Brama pre-push
i ``setup_worktree.py`` biegną systemowym Pythonem, więc ten plik działa pod Pythonem 3.9
(``per-file-target-version`` w ``pyproject.toml``), a ``potomne`` importuje dopiero ``run_git``: push człowieka
nie zależy od niego.

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))  # narzędzie z tools/
    import repo

    fork = repo.merge_base(repo.ROOT, "HEAD", repo.BASE)
    files = repo.changed(repo.ROOT, fork)
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
REMOTE = "origin"
MAIN = "main"
BASE = f"{REMOTE}/{MAIN}"
TIMEOUT_S = 60.0
# Push tagu Wydania przechodzi bramę pre-push tylko z tą zmienną równą 1; ustawia ją tylko narzędzie Wydań (ADR 0014).
RELEASE_OVERRIDE = "MAXIMISEART_WYDANIE"
# Zmienne wołającego, które dostaje ``git(isolated=True)``: bez nich git nie wystartuje.
_ISOLATED_KEPT = ("PATH", "SYSTEMROOT")

__all__ = [
    "BASE",
    "MAIN",
    "RELEASE_OVERRIDE",
    "REMOTE",
    "ROOT",
    "TIMEOUT_S",
    "Merged",
    "Worktree",
    "changed",
    "command",
    "commit",
    "common_dir",
    "git",
    "git_dir",
    "is_ancestor",
    "main_checkout",
    "main_config",
    "merge_base",
    "merge_tree",
    "run_git",
    "succeeds",
    "toplevel",
    "uncommitted",
    "worktrees",
]

@dataclass(frozen=True)
class Worktree:
    """Worktree z ``git worktree list --porcelain`` (bez repozytorium bare); ``main`` to główny checkout."""

    path: Path
    branch: str | None
    head: str
    main: bool
    locked: bool
    missing: bool


def git(root: Path, *arguments: str, timeout: float | None = TIMEOUT_S, isolated: bool = False) -> str:
    """Wyjście szybkiego, lokalnego polecenia gita w ``root``; kod różny od zera to ``subprocess.CalledProcessError``
    z tekstem ``stderr``, a limit czasu ``subprocess.TimeoutExpired``, oba z poleceniem ``["git", *arguments]``.
    ``isolated``: git bez środowiska wołającego i bez konfiguracji systemu i użytkownika (docstring modułu)."""

    with _isolated(root) if isolated else nullcontext(_environment(os.environ)) as environment:
        try:
            done = subprocess.run(
                ["git", "-c", "core.quotePath=false", *arguments], cwd=root, env=environment, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as expired:
            raise subprocess.TimeoutExpired(["git", *arguments], expired.timeout, expired.output, expired.stderr) from None
    if done.returncode:
        raise subprocess.CalledProcessError(done.returncode, ["git", *arguments], _text(done.stdout), _text(done.stderr))
    return _text(done.stdout)


def succeeds(root: Path, *arguments: str) -> bool:
    done = subprocess.run(
        ["git", "-c", "core.quotePath=false", *arguments], cwd=root, env=_environment(os.environ), capture_output=True, timeout=TIMEOUT_S, check=False
    )
    return done.returncode == 0


def run_git(
    root: Path,
    *arguments: str,
    timeout: float | None = None,
    extra_env: Mapping[str, str] | None = None,
    stop: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Polecenie gita, które trwa albo sięga sieci, przez ``potomne.run`` (drzewo procesów ginie z narzędziem): wynik
    bez sprawdzania kodu i z poleceniem ``["git", *arguments]``, a ``extra_env`` dochodzi do środowiska narzędzia."""

    import potomne

    environment = {**_environment(os.environ), **(extra_env or {})}
    return potomne.run(["git", *arguments], cwd=root, env=environment, timeout=timeout, stop=stop)


def command(*arguments: str) -> tuple[str, ...]:
    """Polecenie gita dla kroku, który uruchamia ktoś inny i pokazuje je w raporcie (krok ``tools/ci_lokalnie.py``)."""

    return ("git", *arguments)


def commit(root: Path, revision: str) -> str | None:
    """Pełny SHA commitu ``revision``; ``None``, gdy repozytorium go nie zna."""

    try:
        return git(root, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}").strip()
    except subprocess.CalledProcessError:
        return None


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return succeeds(root, "merge-base", "--is-ancestor", ancestor, descendant)


def merge_base(root: Path, first: str, second: str, *, timeout: float | None = TIMEOUT_S) -> str:
    """Najlepszy wspólny przodek; bez niego (nieznana rewizja, rozłączne historie) ``subprocess.CalledProcessError``."""

    return git(root, "merge-base", first, second, timeout=timeout).strip()


@dataclass(frozen=True)
class Merged:
    """Scalenie dwóch commitów zapisane jako drzewo, bez worktree: ``conflicts`` to pliki z konfliktem (puste bez
    konfliktu), a drzewo ma w nich znaczniki konfliktu."""

    tree: str
    conflicts: tuple[str, ...]


def merge_tree(root: Path, first: str, second: str) -> Merged:
    """Scalenie ``first`` z ``second`` (``git merge-tree --write-tree``). Kod 1 to konflikt; każdy inny kod różny od zera
    (rozłączne historie, brak obiektu, nieznana rewizja) to ``subprocess.CalledProcessError``, a nie konflikt."""

    try:
        written = git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", first, second)
    except subprocess.CalledProcessError as error:
        if error.returncode != 1:
            raise
        written = error.stdout
    tree, *conflicts = written.split("\0")
    return Merged(tree, tuple(dict.fromkeys(path for path in conflicts if path)))


def changed(
    root: Path, since: str, until: str | None = None, paths: Iterable[str] = (), *, timeout: float | None = TIMEOUT_S
) -> frozenset[str]:
    """Ścieżki zmienione od ``since`` do ``until``, a bez ``until`` do drzewa roboczego razem z nieśledzonymi
    nieignorowanymi plikami; przeniesienie to stara i nowa ścieżka. ``paths`` zawęża do tych ścieżek."""

    limit = ("--", *paths)
    listed = git(root, "diff", "-z", "--name-only", "--no-renames", since, *([] if until is None else [until]), *limit, timeout=timeout)
    if until is None:
        listed += git(root, "ls-files", "-z", "--others", "--exclude-standard", *limit, timeout=timeout)
    return frozenset(path for path in listed.split("\0") if path)


def uncommitted(root: Path, paths: Iterable[str] = ()) -> frozenset[str]:
    """Ścieżki, w których checkout różni się od HEAD: zmienione, także w indeksie, usunięte i nieśledzone."""

    return changed(root, "HEAD", paths=paths)


def toplevel(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel").strip()).resolve()


def git_dir(worktree: Path) -> Path:
    """Katalog gita worktree (w nim stan rebase, merge'a i bisect)."""

    return Path(git(worktree, "rev-parse", "--absolute-git-dir").strip())


def common_dir(root: Path) -> Path:
    """Katalog gita wspólny dla wszystkich worktree repozytorium."""

    return (root / git(root, "rev-parse", "--git-common-dir").strip()).resolve()


def main_checkout(root: Path) -> Path:
    """Główny checkout repozytorium, także gdy ``root`` to inny worktree: tam leżą pliki spoza gita (``config/``)."""

    return common_dir(root).parent


def main_config(root: Path) -> Path | None:
    """``config/`` głównego checkoutu z Wzorcami i Konfiguracją wykonawców Maksa spoza gita, których worktree nie ma;
    ``None``, gdy go nie ma albo git nie wskaże głównego checkoutu (kopia bez gita)."""

    try:
        # Nazwa folderu narzędzia (atrapy.pliki_taty.CONFIG_DIRECTORY), tu literałem: repo biegnie systemowym python3.
        folder = main_checkout(root) / "config"
    except (OSError, subprocess.SubprocessError):
        return None
    return folder if folder.is_dir() else None


def worktrees(root: Path) -> list[Worktree]:
    trees = []
    for number, block in enumerate(git(root, "worktree", "list", "--porcelain").strip().split("\n\n")):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        if "bare" in fields:
            continue
        path = Path(fields["worktree"])
        branch = fields.get("branch")
        trees.append(
            Worktree(
                path=path.resolve(),
                branch=branch.removeprefix("refs/heads/") if branch else None,
                head=fields["HEAD"],
                main=number == 0,
                locked="locked" in fields,
                missing="prunable" in fields or not path.is_dir(),
            )
        )
    return trees


def _environment(base: Mapping[str, str]) -> dict[str, str]:
    environment = {**base, "GIT_OPTIONAL_LOCKS": "0"}
    # Za wpisami ``GIT_CONFIG_*`` wołającego, bo ``GIT_CONFIG_COUNT`` liczy je wszystkie.
    index = int(environment.get("GIT_CONFIG_COUNT") or 0)
    environment.update(
        {"GIT_CONFIG_COUNT": str(index + 1), f"GIT_CONFIG_KEY_{index}": "maintenance.auto", f"GIT_CONFIG_VALUE_{index}": "false"}
    )
    return environment


@contextmanager
def _isolated(root: Path) -> Iterator[dict[str, str]]:
    """Środowisko ``git(isolated=True)`` w ``root``: pusty katalog ``HOME`` istnieje do końca bloku."""

    with tempfile.TemporaryDirectory(prefix="git-bez-konfiguracji-") as home:
        kept = {name: os.environ[name] for name in _ISOLATED_KEPT if name in os.environ}
        machine = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_ATTR_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        yield _environment({**kept, **machine, "HOME": home, "LANG": "C", "GIT_WORK_TREE": str(root.resolve())})


def _text(output: bytes) -> str:
    return output.decode("utf-8", errors="replace")
