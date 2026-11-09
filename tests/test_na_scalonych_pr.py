"""``tools/na_scalonych_pr.py`` uruchamia polecenie z narzędziami checkoutu na wskazanym commicie, bez dotykania checkoutu."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, copy_files, git, repository, with_imports

ROOT = Path(__file__).resolve().parents[1]
# Mutacje zmian z modułami, które importują, i pluginem pokrycia, który ładują w pytest po nazwie.
MUTACJE_ZMIANY = ("tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py")
SCRIPT = "import pathlib\nprint(pathlib.Path('src/dane.txt').read_text().strip(), '{}')\n"


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = repository(tmp_path / "repo", {".gitignore": "__pycache__/\n", "src/dane.txt": "stare dane\n", "tools/wypisz.py": SCRIPT.format("stare narzędzie")})
    shutil.copy2(ROOT / "tools" / "na_scalonych_pr.py", repo / "tools" / "na_scalonych_pr.py")
    first = commit(repo, "pierwszy")
    (repo / "src" / "dane.txt").write_text("nowe dane\n", encoding="utf-8")
    commit(repo, "drugi")
    return repo, first


def _run(repo: Path, *arguments: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "na_scalonych_pr.py"), "--wyniki", str(repo.parent / "wyniki"), *arguments],
        cwd=repo if cwd is None else cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_polecenie_biegnie_na_commicie_z_narzedziami_checkoutu_takze_niezacommitowanymi(tmp_path: Path) -> None:
    repo, first = _repo(tmp_path)
    (repo / "tools" / "wypisz.py").write_text(SCRIPT.format("nowe narzędzie"), encoding="utf-8")

    done = _run(repo, "--commit", first, "--", "tools/wypisz.py")

    assert done.returncode == 0, done.stdout + done.stderr
    line, summary = done.stdout.splitlines()
    assert line.startswith(f"{first[:8]} | {first[:8]} | ") and "| kod 0 | stare dane nowe narzędzie |" in line
    assert summary == "NA SCALONYCH PR OK | 1 PR-ów"
    assert (repo / "src" / "dane.txt").read_text(encoding="utf-8") == "nowe dane\n"
    assert (repo.parent / "wyniki" / f"{first[:8]}.txt").read_text(encoding="utf-8").strip() == "stare dane nowe narzędzie"


@pytest.mark.parametrize("revision", ["origin/main", "HEAD^1"])
def test_commit_podany_nazwa_rewizji_ma_etykiete_i_plik_wyniku_ze_skrotu_sha(tmp_path: Path, revision: str) -> None:
    repo, first = _repo(tmp_path)
    git(repo, "update-ref", "refs/remotes/origin/main", first)

    done = _run(repo, "--commit", revision, "--", "tools/wypisz.py")

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith(f"{first[:8]} | {first[:8]} | ")
    assert (repo.parent / "wyniki" / f"{first[:8]}.txt").read_text(encoding="utf-8").strip() == "stare dane stare narzędzie"


def test_commit_podany_tagiem_z_adnotacja_ma_etykiete_ze_skrotu_sha_commitu_a_nie_obiektu_tagu(tmp_path: Path) -> None:
    repo, first = _repo(tmp_path)
    git(repo, "tag", "--annotate", "v0.1.0", "--message", "Wydanie", first)
    assert git(repo, "rev-parse", "v0.1.0") != first

    done = _run(repo, "--commit", "v0.1.0", "--", "tools/wypisz.py")

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith(f"{first[:8]} | {first[:8]} | ")
    assert (repo.parent / "wyniki" / f"{first[:8]}.txt").read_text(encoding="utf-8").strip() == "stare dane stare narzędzie"


def test_narzedzie_uruchomione_spoza_repozytorium_czyta_rewizje_z_repozytorium_narzedzia(tmp_path: Path) -> None:
    repo, first = _repo(tmp_path)
    git(repo, "update-ref", "refs/remotes/origin/main", first)
    outside = tmp_path / "poza"
    outside.mkdir()

    done = _run(repo, "--commit", "origin/main", "--", "tools/wypisz.py", cwd=outside)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith(f"{first[:8]} | {first[:8]} | ")
    assert (repo.parent / "wyniki" / f"{first[:8]}.txt").read_text(encoding="utf-8").strip() == "stare dane stare narzędzie"


def test_commit_tylko_w_origin_narzedzie_pobiera(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    origin = tmp_path / "origin"
    git(tmp_path, "clone", "--quiet", str(repo), str(origin))
    (origin / "src" / "dane.txt").write_text("dane z origin\n", encoding="utf-8")
    only_in_origin = commit(origin, "trzeci")
    git(repo, "remote", "add", "origin", str(origin))

    done = _run(repo, "--commit", only_in_origin, "--", "tools/wypisz.py")

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith(f"{only_in_origin[:8]} | {only_in_origin[:8]} | ")
    assert "| kod 0 | dane z origin stare narzędzie |" in done.stdout


def test_polecenie_z_kodem_innym_niz_zero_konczy_sie_fail_z_nazwa_commitu(tmp_path: Path) -> None:
    repo, first = _repo(tmp_path)
    (repo / "tools" / "pada.py").write_text("print('zle')\nraise SystemExit(3)\n", encoding="utf-8")

    done = _run(repo, "--commit", first, "--", "tools/pada.py")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "| kod 3 | zle |" in done.stdout
    assert done.stdout.splitlines()[-1] == f"NA SCALONYCH PR FAIL | {first[:8]}"


def test_narzedzia_z_rewizji_zamiast_z_checkoutu(tmp_path: Path) -> None:
    repo, first = _repo(tmp_path)
    (repo / "tools" / "wypisz.py").write_text(SCRIPT.format("nowe narzędzie"), encoding="utf-8")

    done = _run(repo, "--narzedzia", first, "--commit", first, "--", "tools/wypisz.py")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "| kod 0 | stare dane stare narzędzie |" in done.stdout


def test_mutacje_zmiany_biegna_na_commicie_takze_poza_ci(tmp_path: Path) -> None:
    """Próba narzędzia na scalonym commicie to nie sprawdzenie przed pushem, więc strażnik ciężkiego CI ją przepuszcza."""

    repo, _ = _repo(tmp_path)
    copy_files(repo, with_imports(MUTACJE_ZMIANY))
    outside_ci = {name: value for name, value in os.environ.items() if name not in ("GITHUB_ACTIONS", "MAXIMISEART_NA_SCALONYCH_PR")}

    done = _run(repo, "--commit", "HEAD", "--", "tools/mutacje_zmiany.py", "--baza", "HEAD^1", env=outside_ci)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "| kod 0 | MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ i tools/ od HEAD^1 |" in done.stdout
