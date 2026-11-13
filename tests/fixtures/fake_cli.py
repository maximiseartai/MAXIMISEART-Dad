"""Atrapa programu z ``PATH`` (``gh``, ``git``, ``claude``…) i repozytorium z ``origin`` jak na GitHubie dla narzędzi PR."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import built_once, commit, copy_files, git, repository, with_imports

# Atrapa na Windows to ``.cmd``, a ta nie zastępuje programu w dwóch miejscach. CreateProcess dopisuje do nazwy bez
# rozszerzenia tylko ``.exe``, więc ``subprocess.run(["gh", ...])`` jej nie znajdzie (znajdzie ją ``shutil.which``, jak
# ``tools/lib/github.py``, albo pełna ścieżka), a cmd.exe tnie jej argumenty na ``&``, jak w adresie ``gh api …&per_page=``.
# Run próbny 42584543040 (9.11.2026, windows-latest, Python 3.11 i 3.14) bez markera: ``test_ciezkie_ci.py`` przeszedł
# cały, a w ``test_wydanie.py`` padło 21 testów na ``&``, w ``test_scal_pr.py`` 54 i w ``test_status_scalenia.py`` 3,
# głównie bez ruff i mypy, których zadania pytest na Windows nie instalują (scalenie z main sprawdza nimi).
ONLY_FOUND_BY_NAME_ON_POSIX = pytest.mark.skipif(
    sys.platform == "win32",
    reason="atrapa .cmd na Windows: program po samej nazwie jej nie znajduje, a cmd.exe tnie jej argumenty na &",
)


def fake_cli(folder: Path, name: str, script: str) -> Path:
    """Program ``name`` w ``folder``, który wykonuje kod Pythona ``script`` interpreterem testów z argumentami programu.

    Na POSIX to sam kod z linią ``#!`` interpretera (bez powłoki pośrodku, więc proces i jego środowisko są te same co
    wywołanego programu), na Windows ``name.cmd``, które uruchamia kod z ``name.py`` obok. Plik kodu leży w ``folder``,
    więc pliki stanu obok atrapy znajduje ``Path(__file__).with_name(...)``. Zwraca ścieżkę programu.
    """

    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        code = folder / f"{name}.py"
        code.write_text(script, encoding="utf-8")
        program = folder / f"{name}.cmd"
        program.write_text(f'@"{sys.executable}" "{code}" %*\r\n', encoding="utf-8")
    else:
        program = folder / name
        program.write_text(f"#!{sys.executable}\n{script}", encoding="utf-8")
        program.chmod(0o755)
    return program


class FakeGitHub:
    """Checkout na ``main`` z repozytorium bare jako ``origin`` (PR-y w ``refs/pull/N/head`` jak na GitHubie) i atrapa ``gh``.

    ``files`` i kopia narzędzia checkoutu ``tool`` (to, które uruchamia ``run``) z jego importami są w commicie ``start``
    z datą ``started`` (domyślnie chwila budowy). Oba repozytoria proces testów buduje raz na ``tool``, ``files`` i
    ``started``, a test dostaje ich kopię (``built_once``). Atrapa ``gh`` wykonuje kod ``gh`` i trzyma swój stan w
    katalogu ``bin``, który ``environment`` stawia na początku ``PATH``.
    """

    def __init__(
        self,
        tmp_path: Path,
        files: dict[str, str],
        *,
        tool: str,
        gh: str,
        started: str | None = None,
    ) -> None:
        def build(template: Path) -> None:
            git(template, "init", "--quiet", "--bare", "--initial-branch=main", str(template / "origin.git"))
            checkout = repository(template / "checkout", files)
            copy_files(checkout, with_imports((tool,)))
            git(checkout, "checkout", "--quiet", "-b", "main")
            with pytest.MonkeyPatch.context() as patch:
                if started is not None:
                    patch.setenv("GIT_COMMITTER_DATE", started)
                commit(checkout, "start")
            git(checkout, "remote", "add", "origin", str(template / "origin.git"))
            git(checkout, "push", "--quiet", "origin", "main")

        built_once(tmp_path, build, tool, started, *sorted(files.items()))
        self.tool = tool
        self.origin = tmp_path / "origin.git"
        self.checkout = tmp_path / "checkout"
        self.start = git(self.checkout, "rev-parse", "HEAD")
        self.bin = tmp_path / "bin"
        fake_cli(self.bin, "gh", gh)

    def commit_on(self, parent: str, files: dict[str, str], subject: str) -> str:
        git(self.checkout, "checkout", "--quiet", "--detach", parent)
        for name, text in files.items():
            (self.checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / name).write_text(text, encoding="utf-8")
        made = commit(self.checkout, subject)
        git(self.checkout, "checkout", "--quiet", "main")
        return made

    def push_head(self, number: int, head: str) -> None:
        git(
            self.checkout,
            "push",
            "--quiet",
            "--force",
            "origin",
            f"{head}:refs/pull/{number}/head",
        )

    def push_main(self, files: dict[str, str]) -> str:
        for name, text in files.items():
            (self.checkout / name).write_text(text, encoding="utf-8")
        head = commit(self.checkout, "main idzie dalej")
        git(self.checkout, "push", "--quiet", "origin", "main")
        return head

    def environment(self) -> dict[str, str]:
        return {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}

    def command(self, *arguments: str) -> list[str]:
        return [sys.executable, str(self.checkout / self.tool), *arguments]

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command(*arguments),
            cwd=self.checkout,
            env=self.environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )
