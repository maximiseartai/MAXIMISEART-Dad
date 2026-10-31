"""Ciężkie zadania CI (mutacje zmiany, mutacje skilli) liczy GitHub, a lokalnie biegną tylko do odtworzenia porażki.

``tools/mutacje_zmiany.py`` i ``tools/ci_lokalnie.py`` z ciężkim zadaniem poza CI odmawiają startu, chyba że
``--odtwarzam`` wskazuje run Actions tej gałęzi, w którym to zadanie padło; tak samo ``tools/mutacje.py`` z listą
dłuższą niż 100 mutacji. Atrapa ``gh`` podaje run bez sieci.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from tests.fixtures.git_repo import commit, copy_files, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "ci"))

from ciezkie_ci import HEAVY, NIGHTLY, mutations_refusal, refusal  # noqa: E402
from zakres_runu import MUTACJE, TORY  # noqa: E402

PASSES = ("GITHUB_ACTIONS", "MAXIMISEART_NA_SCALONYCH_PR")
OUTSIDE_CI = {name: value for name, value in os.environ.items() if name not in PASSES}
Jobs = list[dict[str, str | None]]
RED_MUTATIONS: Jobs = [{"name": "Change mutations (2/3)", "conclusion": "failure"}, {"name": "Change mutations (1/3)", "conclusion": "success"}]


def _repo(tmp_path: Path) -> Path:
    """Repozytorium z narzędziami na gałęzi ``praca``, odbitej od ``main`` z jednym commitem."""

    repo = repository(tmp_path / "repo", {".gitignore": "__pycache__/\n", "src/rozliczenia/__init__.py": ""})
    copy_files(repo, ("tools/lib/wplyw_zmiany.py", "tools/mutacje_zmiany.py", "tools/ci/pytest_pokrycie.py", "tools/ci/pokrycie_procesu.py"))
    git(repo, "checkout", "--quiet", "-b", "main")
    commit(repo, "baza")
    git(repo, "checkout", "--quiet", "-b", "praca")
    return repo


def _gh(head_branch: str, head_sha: str, jobs: Jobs, asked: list[Sequence[str]] | None = None, workflow: str = "CI") -> Callable[[Sequence[str]], str]:
    def gh(arguments: Sequence[str]) -> str:
        if asked is not None:
            asked.append(arguments)
        return json.dumps({"headBranch": head_branch, "headSha": head_sha, "jobs": jobs, "workflowName": workflow})

    return gh


def _tool(repo: Path, *arguments: str, env: dict[str, str] = OUTSIDE_CI) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments], cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )


def _with_fake_gh(tmp_path: Path, run: dict[str, object]) -> dict[str, str]:
    """Środowisko poza CI z atrapą ``gh`` na ``PATH``, która na ``gh run view`` podaje ``run``."""

    bin = tmp_path / "bin"
    bin.mkdir()
    (bin / "run.json").write_text(json.dumps(run), encoding="utf-8")
    gh = bin / "gh"
    gh.write_text(f'#!/bin/sh\ncat "{bin / "run.json"}"\n', encoding="utf-8")
    gh.chmod(0o755)
    return {**OUTSIDE_CI, "PATH": f"{bin}{os.pathsep}{OUTSIDE_CI['PATH']}"}


PUSH = "Wypchnij gałąź: CI policzy je w częściach, a stan pokaże tools/praca_w_toku.py albo gh pr checks."
NIGHT = "Liczy je noc na main (mutacje-nocne.yml, ADR 0021), a przeżyte mutacje trafiają do issue „Przeżyte mutacje z #N”."


@pytest.mark.parametrize(
    ("arguments", "advice"),
    [
        (("tools/mutacje_zmiany.py", "--baza", "main"), NIGHT),
        (("tools/ci_lokalnie.py",), PUSH),
        (("tools/ci_lokalnie.py", "--tylko", "mutations"), PUSH),
        (("tools/ci_lokalnie.py", "--kazdy-commit", "main", "--tylko", "mutations"), PUSH),
    ],
    ids=["mutacje zmiany", "ci lokalnie wszystkie zadania", "ci lokalnie mutacje skilli", "ci lokalnie mutacje skilli kazdego commitu"],
)
def test_ciezkie_zadanie_poza_ci_bez_odtwarzania_odmawia_startu_i_mowi_co_zrobic(tmp_path: Path, arguments: tuple[str, ...], advice: str) -> None:
    done = _tool(_repo(tmp_path), *arguments)

    assert done.returncode == 2, done.stdout + done.stderr
    last = done.stdout.splitlines()[-1]
    assert last.startswith("CIĘŻKIE CI ODMOWA | "), done.stdout
    assert advice in last and "--odtwarzam" in last


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="zadania pytest na Windows instalują tylko requirements.txt, bez ruff")
def test_brama_pre_push_poza_ci_sprawdza_ruff_i_mypy_bez_odtwarzania(tmp_path: Path) -> None:
    repo = repository(
        tmp_path / "repo",
        {"pyproject.toml": '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nfiles = ["kod"]\n', "kod/__init__.py": ""},
    )

    done = _tool(repo, "tools/ci_lokalnie.py", "--tylko", "ruff,mypy", "--do-pierwszego-bledu")

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == "CI LOKALNIE OK | tylko mypy, ruff"


@pytest.mark.parametrize("jobs", [{"ruff", "mypy"}, {"pytest"}, {"frontend"}, {"ruff", "mypy", "pytest"}])
def test_lekkie_zadania_biegna_poza_ci_bez_odtwarzania(tmp_path: Path, jobs: set[str]) -> None:
    def gh(arguments: Sequence[str]) -> str:
        raise AssertionError("lekkie zadanie nie pyta GitHuba")

    assert refusal(jobs, None, root=tmp_path, env={}, gh=gh) is None


@pytest.mark.parametrize(
    "env",
    [{"GITHUB_ACTIONS": "true"}, {"MAXIMISEART_NA_SCALONYCH_PR": "1"}],
    ids=["w CI", "z tools/na_scalonych_pr.py"],
)
def test_ciezkie_zadanie_w_ci_i_na_scalonych_pr_biegnie_bez_odtwarzania(tmp_path: Path, env: dict[str, str]) -> None:
    assert refusal({"change-mutations"}, None, root=tmp_path, env=env) is None


@pytest.mark.parametrize("env", [{"GITHUB_ACTIONS": "false"}, {"MAXIMISEART_NA_SCALONYCH_PR": "0"}])
def test_inna_wartosc_zmiennej_ci_nie_przepuszcza(tmp_path: Path, env: dict[str, str]) -> None:
    assert refusal({"change-mutations"}, None, root=tmp_path, env=env) is not None


def test_odtworzenie_czerwonego_runu_tej_galezi_biegnie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    asked: list[Sequence[str]] = []
    gh = _gh("praca", "0" * 40, RED_MUTATIONS, asked)

    assert refusal({"change-mutations"}, "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/123/job/9", root=repo, env={}, gh=gh) is None
    assert asked == [["run", "view", "123", "--json", "headBranch,headSha,jobs,workflowName"]]


def test_odtworzenie_runu_przodka_head_z_innej_galezi_biegnie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ancestor = git(repo, "rev-parse", "HEAD")
    (repo / "plik.txt").write_text("dalej\n", encoding="utf-8")
    commit(repo, "dalej")

    assert refusal({"change-mutations"}, "123", root=repo, env={}, gh=_gh("inna", ancestor, RED_MUTATIONS)) is None


def test_odtworzenie_runu_innej_galezi_na_odlaczonym_head_odmawia(tmp_path: Path) -> None:
    """Worktree agenta bywa na odłączonym HEAD: brak bieżącej gałęzi nie zastępuje porażki tej gałęzi."""

    repo = _repo(tmp_path)
    git(repo, "checkout", "--quiet", "--detach")

    refused = refusal({"change-mutations"}, "123", root=repo, env={}, gh=_gh("inna", "f" * 40, RED_MUTATIONS))

    assert refused is not None and "dotyczy gałęzi inna (ffffffff), a nie bieżącej HEAD" in refused


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh")
def test_odtworzenie_runu_commitu_z_main_odmawia(tmp_path: Path) -> None:
    """Czerwony run scalonego PR-u ma commit w historii HEAD, ale nie jest porażką tej gałęzi."""

    repo = _repo(tmp_path)
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", merged)
    (repo / "plik.txt").write_text("dalej\n", encoding="utf-8")
    commit(repo, "dalej")

    refused = refusal({"change-mutations"}, "123", root=repo, env={}, gh=_gh("scalony-pr", merged, RED_MUTATIONS))

    assert refused is not None and "dotyczy gałęzi scalony-pr" in refused


def test_odtworzenie_czerwonej_czesci_nocnej_biegnie_na_jej_commicie_z_main(tmp_path: Path) -> None:
    """Run nocny dotyczy ``main``, a worktree agenta nie ma tej gałęzi: odtwarza się go na odłączonym commicie runu."""

    repo = _repo(tmp_path)
    night = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", night)
    git(repo, "checkout", "--quiet", "--detach", night)

    assert refusal({"change-mutations"}, "123", root=repo, env={}, gh=_gh("main", night, RED_MUTATIONS, workflow=NIGHTLY)) is None


def test_odtworzenie_czesci_nocnej_poza_jej_commitem_odmawia_i_podaje_checkout(tmp_path: Path) -> None:
    """Stary czerwony run nocny nie otwiera mutacji gałęzi, która tylko ma jego commit w historii."""

    repo = _repo(tmp_path)
    night = git(repo, "rev-parse", "HEAD")
    (repo / "plik.txt").write_text("dalej\n", encoding="utf-8")
    commit(repo, "dalej")

    refused = refusal({"change-mutations"}, "123", root=repo, env={}, gh=_gh("praca", night, RED_MUTATIONS, workflow=NIGHTLY))

    assert refused == f"CIĘŻKIE CI ODMOWA | --odtwarzam 123: run nocny odtwarza się na jego commicie: git checkout --detach {night}"


@pytest.mark.parametrize(
    ("head_branch", "jobs", "reason"),
    [
        ("praca", [{"name": "Change mutations (1/3)", "conclusion": "success"}], "nie padło change-mutations"),
        ("praca", [{"name": "pytest (Python 3.14, Linux, 1/2)", "conclusion": "failure"}], "nie padło change-mutations"),
        ("praca", [{"name": "Change mutations (1/3)", "conclusion": None}], "nie padło change-mutations"),
        ("inna", RED_MUTATIONS, "dotyczy gałęzi inna"),
    ],
    ids=["zielony run", "padło inne zadanie", "zadanie jeszcze biegnie", "inna galaz"],
)
def test_odtworzenie_runu_ktory_nie_jest_ta_porazka_odmawia(tmp_path: Path, head_branch: str, jobs: Jobs, reason: str) -> None:
    repo = _repo(tmp_path)

    refused = refusal({"change-mutations"}, "123", root=repo, env={}, gh=_gh(head_branch, "f" * 40, jobs))

    assert refused is not None and refused.startswith("CIĘŻKIE CI ODMOWA | --odtwarzam 123: ") and reason in refused


def test_odtworzenie_wszystkich_ciezkich_zadan_wymaga_porazki_kazdego(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    refused = refusal({"ruff", "change-mutations", "mutations"}, "123", root=repo, env={}, gh=_gh("praca", "f" * 40, RED_MUTATIONS))

    assert refused is not None and "nie padło mutations;" in refused


def _no_github(arguments: Sequence[str]) -> str:
    raise AssertionError("bez --odtwarzam nie ma o co pytać GitHuba")


def test_celowany_dowod_do_100_mutacji_biegnie_poza_ci(tmp_path: Path) -> None:
    assert mutations_refusal(100, None, root=tmp_path, env={}, gh=_no_github) is None


def test_lista_ponad_100_mutacji_poza_ci_to_reczne_mutacje_zmiany_i_odmawia_z_jej_dlugoscia(tmp_path: Path) -> None:
    refused = mutations_refusal(101, None, root=tmp_path, env={}, gh=_no_github)

    assert refused is not None and refused.startswith("CIĘŻKIE CI ODMOWA | change-mutations ") and "\n" not in refused
    assert NIGHT in refused and "--odtwarzam" in refused
    assert "najwyżej 100 mutacji, a ta lista ma 101." in refused


@pytest.mark.parametrize("env", [{"GITHUB_ACTIONS": "true"}, {"MAXIMISEART_NA_SCALONYCH_PR": "1"}], ids=["w CI", "z tools/na_scalonych_pr.py"])
def test_dluga_lista_mutacji_w_ci_i_na_scalonych_pr_biegnie(tmp_path: Path, env: dict[str, str]) -> None:
    assert mutations_refusal(335, None, root=tmp_path, env=env, gh=_no_github) is None


def test_dluga_lista_mutacji_odtwarzajaca_czerwone_mutacje_zmiany_tej_galezi_biegnie(tmp_path: Path) -> None:
    assert mutations_refusal(335, "123", root=_repo(tmp_path), env={}, gh=_gh("praca", "f" * 40, RED_MUTATIONS)) is None


def test_dluga_lista_mutacji_z_runu_gdzie_padly_tylko_mutacje_skilli_odmawia(tmp_path: Path) -> None:
    red_skills: Jobs = [{"name": "Mutation checks (1/3)", "conclusion": "failure"}, {"name": "Change mutations (1/3)", "conclusion": "success"}]

    refused = mutations_refusal(335, "123", root=_repo(tmp_path), env={}, gh=_gh("praca", "f" * 40, red_skills))

    assert refused is not None and refused.startswith("CIĘŻKIE CI ODMOWA | --odtwarzam 123: ") and "nie padło change-mutations" in refused
    assert "a ta lista ma 335." in refused


# Podstawa padnie na pierwszej kopii: mutacje, które przeszły przez strażnika, kończą się na niej, a nie po 101 kopiach.
RED_BASELINE = ("--", "-c", "raise SystemExit(1)")
RED_BASELINE_LINE = "PODSTAWA CZERWONA: -c raise SystemExit(1) → kod wyjścia 1"


def _mutation_list(tmp_path: Path, count: int) -> Path:
    path = tmp_path / "mutacje.json"
    # Dwie zmiany w każdej mutacji: limit liczy mutacje, nie zmiany.
    edits = [["src/rozliczenia/__init__.py", "", "X = 1\n"], ["src/rozliczenia/inny.py", "", "Y = 1\n"]]
    entries = [{"nazwa": f"m{number}", "zmiany": edits} for number in range(count)]
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("count", "extra", "refused"),
    [
        (101, (), "CIĘŻKIE CI ODMOWA | change-mutations "),
        (100, ("--zmiana", "src/rozliczenia/__init__.py", "", "X = 0\n"), "CIĘŻKIE CI ODMOWA | change-mutations "),
        pytest.param(
            101,
            ("--odtwarzam", "123"),
            "CIĘŻKIE CI ODMOWA | --odtwarzam 123: run dotyczy gałęzi inna",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh"),
        ),
    ],
    ids=["101 z pliku", "100 z pliku i jedna z --zmiana", "odtworzenie runu innej galezi"],
)
def test_mutacje_z_lista_ponad_100_poza_ci_odmawiaja_zanim_policza_podstawe(
    tmp_path: Path, count: int, extra: tuple[str, ...], refused: str
) -> None:
    repo = _repo(tmp_path)
    env = _with_fake_gh(tmp_path, {"headBranch": "inna", "headSha": "0" * 40, "jobs": RED_MUTATIONS, "workflowName": "CI"})

    done = _tool(repo, "tools/mutacje.py", "--plik", str(_mutation_list(tmp_path, count)), *extra, *RED_BASELINE, env=env)

    assert done.returncode == 2, done.stdout + done.stderr
    [line] = done.stdout.splitlines()
    assert line.startswith(refused) and "a ta lista ma 101." in line


@pytest.mark.parametrize(
    ("count", "passes", "reproduces"),
    [
        (100, {}, ()),
        (101, {"GITHUB_ACTIONS": "true"}, ()),
        pytest.param(101, {}, ("--odtwarzam", "123"), marks=pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh")),
    ],
    ids=["celowany dowod poza CI", "w CI", "odtworzenie czerwonych mutacji zmiany"],
)
def test_mutacje_licza_celowany_dowod_i_dluga_liste_w_ci_i_przy_odtwarzaniu(
    tmp_path: Path, count: int, passes: dict[str, str], reproduces: tuple[str, ...]
) -> None:
    repo = _repo(tmp_path)
    env = {**_with_fake_gh(tmp_path, {"headBranch": "praca", "headSha": "0" * 40, "jobs": RED_MUTATIONS, "workflowName": "CI"}), **passes}

    done = _tool(repo, "tools/mutacje.py", "--plik", str(_mutation_list(tmp_path, count)), *reproduces, *RED_BASELINE, env=env)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "ODMOWA" not in done.stdout and done.stdout.splitlines()[0] == RED_BASELINE_LINE


def test_skrypt_mutacji_skilla_liczy_dluga_liste_poza_ci_bez_limitu(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    script = repo / ".agents" / "skills" / "verify-x" / "scripts" / "check_x_mutations.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))\n\n'
        "from mutacje import Edit, Mutation, check_all\n\n"
        'EDIT = Edit(Path("src/rozliczenia/__init__.py"), "", "X = 1\\n")\n'
        f'MUTATIONS = [Mutation(f"m{{number}}", (EDIT,), {RED_BASELINE[1:]!r}) for number in range(101)]\n'
        "raise SystemExit(check_all(MUTATIONS))\n",
        encoding="utf-8",
    )

    done = _tool(repo, str(script.relative_to(repo)))

    assert done.returncode == 2, done.stdout + done.stderr
    assert "ODMOWA" not in done.stdout and done.stdout.splitlines()[0] == RED_BASELINE_LINE


@pytest.mark.parametrize("given", ["ostatni", "https://github.com/a/b/pull/12"])
def test_odtworzenie_bez_id_runu_odmawia_bez_pytania_githuba(tmp_path: Path, given: str) -> None:
    def gh(arguments: Sequence[str]) -> str:
        raise AssertionError("bez id runu nie ma o co pytać")

    refused = refusal({"change-mutations"}, given, root=tmp_path, env={}, gh=gh)

    assert refused is not None and "to nie jest id ani URL runu Actions" in refused


def test_odtworzenie_runu_ktorego_gh_nie_podaje_odmawia_z_powodem(tmp_path: Path) -> None:
    def gh(arguments: Sequence[str]) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="could not find any workflow run")

    refused = refusal({"change-mutations"}, "123", root=_repo(tmp_path), env={}, gh=gh)

    assert refused is not None and "nie odczytałem runu 123 przez gh" in refused


def test_odtwarzam_z_wiersza_polecen_trafia_do_straznika(tmp_path: Path) -> None:
    """``--odtwarzam`` obu narzędzi dochodzi do strażnika: z wymyślonym id odmawia z jego powodem, nie bez flagi."""

    repo = _repo(tmp_path)
    for tool in ("tools/mutacje_zmiany.py", "tools/ci_lokalnie.py"):
        done = _tool(repo, tool, "--odtwarzam", "nie-run", *(("--tylko", "mutations") if "ci_lokalnie" in tool else ()))

        assert done.returncode == 2, done.stdout + done.stderr
        assert done.stdout.splitlines()[-1] == "CIĘŻKIE CI ODMOWA | --odtwarzam nie-run: to nie jest id ani URL runu Actions"


def test_nazwy_ciezkich_zadan_zgadzaja_sie_z_ci() -> None:
    # Change mutations biegną nocą na main (ADR 0021), Mutation checks w CI każdego runu.
    jobs = {
        **yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"],
        **yaml.safe_load((ROOT / ".github" / "workflows" / "mutacje-nocne.yml").read_text(encoding="utf-8"))["jobs"],
    }
    # Zadanie, którego macierz układa plan, nazywa się jak jego tor w planie.
    planned = {lane.szablon: lane.zadanie for lane in (*TORY, MUTACJE)}
    names = {job: planned[job] if jobs[job]["name"] == "${{ matrix.nazwa }}" else jobs[job]["name"] for job in HEAVY}

    assert {job: re.sub(r" \((\$\{\{|\{numer\}).*", "", name) for job, name in names.items()} == HEAVY
    assert yaml.safe_load((ROOT / ".github" / "workflows" / "mutacje-nocne.yml").read_text(encoding="utf-8"))["name"] == NIGHTLY
