"""Małe repozytorium Gita w katalogu testu z narzędziami z ``tools/`` checkoutu."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from functools import cache
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from wplyw_zmiany import Repository

ROOT = Path(__file__).resolve().parents[2]
# Narzędzia, z którymi działa repozytorium testu (``repository``), każde z modułami ``tools/``, które importuje.
TOOLS = ("tools/ci_lokalnie.py", "tools/mutacje.py")
AUTHOR = {name: value for role in ("AUTHOR", "COMMITTER") for name, value in ((f"GIT_{role}_NAME", "test"), (f"GIT_{role}_EMAIL", "test@example.com"))}

__all__ = ["TOOLS", "built_once", "commit", "copy_files", "git", "repository", "with_imports"]


def git(repo: Path, *arguments: str) -> str:
    answered = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env={**os.environ, **AUTHOR},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return answered.stdout.strip()


def commit(repo: Path, subject: str) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", subject)
    return git(repo, "rev-parse", "HEAD")


def copy_files(path: Path, names: Iterable[str]) -> None:
    """Kopie plików checkoutu (ścieżki względem korzenia repozytorium) w ``path``, w tych samych katalogach."""

    for name in names:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path / name)


def with_imports(names: Iterable[str]) -> list[str]:
    """``names`` (ścieżki od korzenia checkoutu) i pliki ``tools/``, do których dochodzą importem, wprost albo przez inny
    moduł (``Repository.imported``), więc kopia narzędzia ma każdy swój moduł bez listy, która się rozjeżdża."""

    names = tuple(names)
    reached = {found for name in names for found in _checkout().imported(name) if found.startswith("tools/")}
    return sorted({*names, *reached})


@cache
def _checkout() -> Repository:
    return Repository.scan(ROOT)


def repository(path: Path, files: dict[str, str], tools: Iterable[str] = TOOLS) -> Path:
    """Repozytorium z ``pyproject.toml``, narzędziami ``tools`` checkoutu z ich importami (``with_imports``) oraz ``files``,
    bez commitu."""

    copy_files(path, ("pyproject.toml", *with_imports(tools)))
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    git(path, "init", "--quiet")
    return path


# Repozytoria zbudowane w tym procesie testów (każdy worker xdist ma swoje) według budowy i klucza; testy dostają kopie.
_built: dict[tuple[str, str, tuple[Hashable, ...]], Path] = {}
_built_root: tempfile.TemporaryDirectory[str] | None = None


def built_once(directory: Path, build: Callable[[Path], object], *key: Hashable) -> None:
    """W ``directory`` kopia repozytoriów, które ``build`` zbudował w pustym katalogu raz na proces testów i ``key``.

    Spawn gita kosztuje na Windows 25–37 ms, a budowa to zwykle kilkanaście gitów. Obiekty wzorca są spakowane, więc
    kopia ma mało plików. Ścieżki do wzorca (adresy remote, powiązania worktree z repozytorium) wskazują w kopii na
    kopię, a indeks każdego checkoutu zna kopie plików (inny i-węzeł i ctime), więc test widzi to samo, co po własnym
    ``build``, i nic w kopii nie sięga do wzorca ani do innego testu. ``build`` nie może zostawić w repozytoriach innych
    ścieżek bezwzględnych (``FETCH_HEAD``, stan rebase).
    """

    global _built_root
    built = (build.__module__, build.__qualname__, key)
    template = _built.get(built)
    if template is None:
        if _built_root is None:
            _built_root = tempfile.TemporaryDirectory(prefix="repozytoria-", ignore_cleanup_errors=True)
        template = Path(tempfile.mkdtemp(dir=_built_root.name)).resolve()
        build(template)
        for objects in template.rglob("objects"):
            if (objects.parent / "HEAD").is_file():
                git(objects.parent, "repack", "-a", "-d", "-q")
        _built[built] = template
    shutil.copytree(template, directory, dirs_exist_ok=True)
    copy = directory.resolve()

    def moved(path: str) -> str | None:
        try:
            return (copy / Path(path).resolve().relative_to(template)).as_posix()
        except (ValueError, OSError):
            return None

    checkouts = []
    for found in sorted(copy.rglob("*")):
        if found.name == ".git":
            checkouts.append(found.parent)
        if found.name == ".git" and found.is_file():
            _rewrite(found, lambda line: f"gitdir: {target}\n" if line.startswith("gitdir: ") and (target := moved(line[8:].strip())) else line)
        elif found.name == "config" and found.is_file() and (found.parent / "HEAD").is_file():
            _rewrite(found, lambda line: f'\turl = "{_quoted(target)}"\n' if (target := _config_url(line, moved)) else line)
        elif found.name == "gitdir" and found.parent.parent.name == "worktrees":
            _rewrite(found, lambda line: f"{target}\n" if (target := moved(line.strip())) else line)
    for checkout in checkouts:
        git(checkout, "update-index", "-q", "--refresh")


def _rewrite(path: Path, line_of: Callable[[str], str]) -> None:
    # Git na Windows ukrywa plik .git worktree, a Windows nie pozwala otworzyć ukrytego pliku do zapisu od nowa ("w").
    with path.open("r+", encoding="utf-8", newline="") as file:
        lines = file.read().splitlines(keepends=True)
        file.seek(0)
        file.write("".join(map(line_of, lines)))
        file.truncate()


def _config_url(line: str, moved: Callable[[str], str | None]) -> str | None:
    """Nowa ścieżka z linii ``url = …`` konfiguracji Gita, gdy wskazuje do wzorca; Git zapisuje ukośnik wsteczny podwójnie."""

    name, separator, value = line.partition("=")
    if not separator or name.strip() != "url":
        return None
    unescaped, characters = [], iter(value.strip())
    for character in characters:
        if character != '"':
            unescaped.append(next(characters, "") if character == "\\" else character)
    return moved("".join(unescaped))


def _quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
