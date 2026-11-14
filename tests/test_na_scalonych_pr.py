"""``tools/na_scalonych_pr.py`` uruchamia polecenie z narzędziami checkoutu na wskazanym commicie, bez dotykania checkoutu."""

from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys

import pytest

import na_scalonych_pr
from tests.fixtures import werdykty_szablonu
from tests.fixtures.body_html import body_html
from tests.fixtures.fake_cli import FakeGitHub
from tests.fixtures.git_repo import commit, copy_files, git, repository, with_imports

# Mutacje zmian z modułami, które importują, i pluginem pokrycia, który ładują w pytest po nazwie.
MUTACJE_ZMIANY = ("tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py")
SCRIPT = "import pathlib\nprint(pathlib.Path('src/dane.txt').read_text().strip(), '{}')\n"


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = repository(tmp_path / "repo", {".gitignore": "__pycache__/\n", "src/dane.txt": "stare dane\n", "tools/wypisz.py": SCRIPT.format("stare narzędzie")})
    copy_files(repo, with_imports(("tools/na_scalonych_pr.py",)))
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


def test_commit_podany_nazwa_rewizji_ma_etykiete_i_plik_wyniku_ze_skrotu_sha(tmp_path: Path) -> None:
    """Nazwę zdalnej gałęzi (``origin/main``) sprawdza ``test_narzedzie_uruchomione_spoza_repozytorium…``."""

    repo, first = _repo(tmp_path)

    done = _run(repo, "--commit", "HEAD^1", "--", "tools/wypisz.py")

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


# Dowód reguły ast-grep na atrapie GitHuba: werdykt FAIL PR-u #5 z Ważnym W1 w ``kod/inne.py:1`` (``werdykty_szablonu``).
RULE = "id: zakazane-wywolanie\nlanguage: python\nseverity: error\nmessage: bez zakazane()\nrule:\n  pattern: $O.zakazane()\n"
CAUGHT = "def wazne(obiekt):\n    obiekt.zakazane()\n"
ELSEWHERE = "def wazne(obiekt):\n    return obiekt\n\n\ndef inna(obiekt):\n    obiekt.zakazane()\n"
CLEAN = "def czysty(obiekt):\n    obiekt.dozwolone()\n"
FAKE_GH = """\
import json, pathlib, sys

state = json.loads((pathlib.Path(sys.argv[0]).parent / "state.json").read_text(encoding="utf-8"))
if sys.argv[1:3] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "maximiseartai/MAXIMISEART-Dad"}))
elif sys.argv[1:3] == ["api", "graphql"] and "number=5" in sys.argv:
    print(json.dumps({"data": {"repository": {"pullRequest": state}}}))
else:
    sys.exit(f"atrapa gh nie zna: {sys.argv[1:]}")
"""
needs_ast_grep = pytest.mark.skipif(na_scalonych_pr.AST_GREP is None, reason="ast-grep z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt")


def _merge(github: FakeGitHub, number: int, *versions: dict[str, str]) -> list[str]:
    """Commity gałęzi PR-u ``number`` od ``main`` (po jednym na wersję plików) i ich merge do ``main`` jak na GitHubie."""

    made: list[str] = []
    for files in versions:
        made.append(github.commit_on(made[-1] if made else "main", files, f"wersja {len(made) + 1}"))
    git(github.checkout, "merge", "--quiet", "--no-ff", "--message", f"Merge pull request #{number} from organizacja/galaz-{number}", made[-1])
    git(github.checkout, "push", "--quiet", "origin", "main")
    return made


def _proof(tmp_path: Path, failed: str, clean: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], str]:
    """Bieg dowodu na ``main`` z dawnym odpaleniem w ``stare.py`` i dwoma merge'ami: PR #5, którego werdykt FAIL ma
    ``kod/inne.py`` w postaci ``failed`` (poprawka go usuwa), i PR #6 z plikami ``clean``."""

    github = FakeGitHub(tmp_path, {"stare.py": "def stare(obiekt):\n    obiekt.zakazane()\n", "regula.yml": RULE}, tool="tools/na_scalonych_pr.py", gh=FAKE_GH)
    sha = _merge(github, 5, {"kod/inne.py": failed}, {"kod/inne.py": CLEAN})[0]
    _merge(github, 6, clean)
    verdict = f"WERDYKT: FAIL {sha}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne"]
    comment = {"body": verdict, "bodyHTML": body_html(verdict, werdykty_szablonu.rendered()), "authorAssociation": "OWNER", "createdAt": "2026-11-14T01:00:00Z", "author": {"login": "recenzent"}}
    pages = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
    pull = {
        **{"number": 5, "title": "PR 5", "state": "MERGED", "isDraft": False, "isCrossRepository": False, "baseRefName": "main", "headRefOid": sha},
        **{"url": "https://github.com/maximiseartai/MAXIMISEART-Dad/pull/5", "body": "", "comments": {**pages, "nodes": [comment]}, "reviews": {**pages, "nodes": []}},
    }
    (github.bin / "state.json").write_text(json.dumps(pull), encoding="utf-8")
    return github.run("--regula", "regula.yml", "--wazne", "5/W1/r1", "--ostatnie", "2"), sha


@needs_ast_grep
def test_dowod_reguly_lapie_wazne_w_funkcji_z_gdzie_na_liniach_dodanych_przed_merge_bez_starych_linii(tmp_path: Path) -> None:
    """PR #5 jest już scalony, więc jego linie liczą się od ``main`` sprzed merge'a, a ``stare.py`` zmienione w PR #6
    ma dawne odpalenie poza liniami dodanymi."""

    done, sha = _proof(tmp_path, CAUGHT, {".agents/skills/s/scripts/czysty.py": CLEAN, "stare.py": "def stare(obiekt):\n    obiekt.zakazane()\n\n\nNOWA = 1\n"})

    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == f"#5 W1 r1 | {sha[:8]} | złapane | odpalenia kod/inne.py:2 | Gdzie: kod/inne.py:1", done.stdout
    assert [line.split(" | ")[0::2] for line in lines[1:3]] == [["FP #5", "0"], ["FP #6", "0"]], done.stdout
    assert lines[3].startswith("main | ") and lines[3].endswith(" | 1"), done.stdout
    assert lines[4] == "DOWÓD OK | zakazane-wywolanie | złapane 1/1 | FP 0 w 0 z 2 PR (0%) | main 1"


@needs_ast_grep
@pytest.mark.parametrize(
    ("failed", "clean", "summary"),
    [
        (ELSEWHERE, {"czysty.py": CLEAN}, "złapane 0/1 | FP 0 w 0 z 2 PR (0%) | main 1"),
        (CAUGHT, {".agents/skills/s/scripts/kopia.py": CAUGHT}, "złapane 1/1 | FP 1 w 1 z 2 PR (50%) | main 2"),
    ],
    ids=["odpalenie-w-innej-funkcji-niz-gdzie", "falszywy-alarm-w-katalogu-ukrytym"],
)
def test_dowod_reguly_odmawia_gdy_nie_zlapal_waznego_albo_alarmuje_w_ponad_10_procentach_pr(tmp_path: Path, failed: str, clean: dict[str, str], summary: str) -> None:
    done, _ = _proof(tmp_path, failed, clean)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == f"DOWÓD ODMOWA | zakazane-wywolanie | {summary}", done.stdout
