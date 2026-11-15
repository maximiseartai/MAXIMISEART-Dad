"""``tools/na_scalonych_pr.py`` uruchamia polecenie z narzędziami checkoutu na wskazanym commicie, bez dotykania checkoutu."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import os
import subprocess
import sys

import pytest

import na_scalonych_pr
from tests.fixtures import werdykty_szablonu
from tests.fixtures.body_html import body_html
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub
from tests.fixtures.git_repo import commit, copy_files, git, mutation_repository, with_imports
from tests.fixtures.znane_luki import assert_znane_luki

# Mutacje zmian z modułami, które importują, i pluginem pokrycia, który ładują w pytest po nazwie.
MUTACJE_ZMIANY = ("tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py")
SCRIPT = "import pathlib\nprint(pathlib.Path('src/dane.txt').read_text().strip(), '{}')\n"


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = mutation_repository(tmp_path / "repo", {".gitignore": "__pycache__/\n", "src/dane.txt": "stare dane\n", "tools/wypisz.py": SCRIPT.format("stare narzędzie")})
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


def test_bez_folderu_wynikow_wynik_trafia_do_katalogu_gita_checkoutu(tmp_path: Path) -> None:
    repo, first = _repo(tmp_path)

    done = subprocess.run(
        [sys.executable, str(repo / "tools" / "na_scalonych_pr.py"), "--commit", first, "--", "tools/wypisz.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert (repo / ".git" / "na-scalonych-pr" / f"{first[:8]}.txt").read_text(encoding="utf-8").strip() == "stare dane stare narzędzie"


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
    assert "| kod 0 | MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ i jednostek przepuszcza od HEAD^1 |" in done.stdout


# Dowód reguły ast-grep na atrapie GitHuba: werdykt FAIL PR-u #5 z Ważnym W1 w ``kod/inne.py:1`` (``werdykty_szablonu``).
RULE = 'id: zakazane-wywolanie\nlanguage: python\nseverity: error\nmessage: bez zakazane()\nfiles:\n  - "**/*.py"\nrule:\n  pattern: $O.zakazane()\n'
CAUGHT = "def wazne(obiekt):\n    obiekt.zakazane()\n"
ELSEWHERE = "def wazne(obiekt):\n    return obiekt\n\n\ndef inna(obiekt):\n    obiekt.zakazane()\n"
CLEAN = "def czysty(obiekt):\n    obiekt.dozwolone()\n"
# Instrukcja na czterech liniach: Ważne zmienia tylko jej ostatnią linię, a dawne odpalenie w ``stare.py`` środkową.
STATEMENT = "def wazne(obiekt):\n    return (\n        obiekt\n    ).{}()\n"
OLD = "def stare(obiekt):\n    (\n        {}\n    ).zakazane()\n"
WHERE = "Gdzie: kod/inne.py:1"
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


def _history(tmp_path: Path, failed: str, start: dict[str, str] | None, where: str, rule: str, fixed: str = CLEAN) -> tuple[FakeGitHub, str]:
    """``main`` z plikami ``start``, dawnym odpaleniem w ``stare.py``, plikiem ``regula.yml`` z treścią ``rule`` i scalonym
    PR #5, którego werdykt FAIL z polem ``where`` ma ``kod/inne.py`` w postaci ``failed``, a poprawka zostawia ``fixed``;
    atrapa ``gh`` oddaje ten werdykt. Zwraca atrapę GitHuba i SHA werdyktu."""

    files = {"stare.py": OLD.format("obiekt"), "regula.yml": rule, **(start or {})}
    github = FakeGitHub(tmp_path, files, tool="tools/na_scalonych_pr.py", gh=FAKE_GH)
    sha = _merge(github, 5, {"kod/inne.py": failed}, {"kod/inne.py": fixed})[0]
    findings = werdykty_szablonu.WERDYKTY["wazne"]
    verdict = f"WERDYKT: FAIL {sha}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + findings.replace(WHERE, where)
    # Pole bez znaków Markdownu renderer GitHuba oddaje bez zmian, więc inne ``where`` to ta sama podmiana w HTML.
    rendered = {findings.replace(WHERE, where): html.replace(WHERE, where) for findings, html in werdykty_szablonu.rendered().items()}
    comment = {"body": verdict, "bodyHTML": body_html(verdict, rendered), "authorAssociation": "OWNER", "createdAt": "2026-11-14T01:00:00Z", "author": {"login": "recenzent"}}
    pages = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
    pull = {
        **{"number": 5, "title": "PR 5", "state": "MERGED", "isDraft": False, "isCrossRepository": False, "baseRefName": "main", "headRefOid": sha},
        **{"url": "https://github.com/maximiseartai/MAXIMISEART-Dad/pull/5", "body": "", "comments": {**pages, "nodes": [comment]}, "reviews": {**pages, "nodes": []}},
    }
    (github.bin / "state.json").write_text(json.dumps(pull), encoding="utf-8")
    return github, sha


def _proof(
    tmp_path: Path,
    failed: str,
    clean: dict[str, str],
    start: dict[str, str] | None = None,
    where: str = WHERE,
    rule: str = RULE,
    chosen: tuple[str, ...] = ("--regula", "regula.yml"),
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Bieg dowodu reguły wybranej argumentami ``chosen`` (domyślnie plik ``regula.yml`` z treścią ``rule``) na historii
    ``_history`` (poprawka PR #5 usuwa ``kod/inne.py``) z drugim merge'em, PR #6 z plikami ``clean``."""

    github, sha = _history(tmp_path, failed, start, where, rule)
    _merge(github, 6, clean)
    return github.run(*chosen, "--wazne", "5/W1/r1", "--ostatnie", "2"), sha


@needs_ast_grep
def test_dowod_reguly_lapie_wazne_w_funkcji_z_gdzie_na_liniach_dodanych_przed_merge_bez_starych_linii(tmp_path: Path) -> None:
    """PR #5 jest już scalony, więc jego linie liczą się od ``main`` sprzed merge'a, a ``stare.py`` zmienione w PR #6
    ma dawne odpalenie poza liniami dodanymi."""

    done, sha = _proof(tmp_path, CAUGHT, {".agents/skills/s/scripts/czysty.py": CLEAN, "stare.py": OLD.format("obiekt") + "\n\nNOWA = 1\n"})

    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == f"#5 W1 r1 | {sha[:8]} | złapane | odpalenia kod/inne.py:2 | Gdzie: kod/inne.py:1", done.stdout
    assert [line.split(" | ")[0::2] for line in lines[1:3]] == [["FP #5", "0"], ["FP #6", "0"]], done.stdout
    assert lines[3].startswith("main | ") and lines[3].endswith(" | 1"), done.stdout
    assert lines[4] == "DOWÓD OK | zakazane-wywolanie | złapane 1/1 | FP 0 w 0 z 2 PR (0%) | main 1"


@needs_ast_grep
def test_dowod_reguly_lapie_wazne_z_linii_dodanej_w_srodku_starej_instrukcji_jak_zapadka(tmp_path: Path) -> None:
    """Zapadka zatrzymuje instrukcję, której którakolwiek linia jest dodana, więc dowód liczy to samo Ważne jako
    złapane w pierwszej dodanej linii węzła, choć instrukcja zaczyna się na linii starej."""

    done, sha = _proof(tmp_path, STATEMENT.format("zakazane"), {"czysty.py": CLEAN}, start={"kod/inne.py": STATEMENT.format("dozwolone")})

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[0] == f"#5 W1 r1 | {sha[:8]} | złapane | odpalenia kod/inne.py:4 | Gdzie: kod/inne.py:1", done.stdout
    assert done.stdout.splitlines()[-1] == "DOWÓD OK | zakazane-wywolanie | złapane 1/1 | FP 0 w 0 z 2 PR (0%) | main 1", done.stdout


@needs_ast_grep
@pytest.mark.parametrize(
    ("failed", "clean", "where", "summary"),
    [
        (ELSEWHERE, {"czysty.py": CLEAN}, WHERE, "złapane 0/1 | FP 0 w 0 z 2 PR (0%) | main 1"),
        (ELSEWHERE, {"czysty.py": CLEAN}, f"{WHERE} (proporcja 1:6)", "złapane 0/1 | FP 0 w 0 z 2 PR (0%) | main 1"),
        (CAUGHT, {"czysty.py": CLEAN}, "Gdzie: kod/inne (o 12:30)", "Gdzie: kod/inne (o 12:30) nie ma miejsca plik:linia"),
        (CAUGHT, {".agents/skills/s/scripts/kopia.py": CAUGHT}, WHERE, "złapane 1/1 | FP 1 w 1 z 2 PR (50%) | main 2"),
        (CAUGHT, {"stare.py": OLD.format("obiekt.inny")}, WHERE, "złapane 1/1 | FP 1 w 1 z 2 PR (50%) | main 1"),
    ],
    ids=["odpalenie-w-innej-funkcji-niz-gdzie", "liczba-po-dwukropku-bez-pliku-nie-jest-linia", "gdzie-bez-miejsca", "falszywy-alarm-w-katalogu-ukrytym", "falszywy-alarm-z-linii-w-srodku-starej-instrukcji"],
)
def test_dowod_reguly_odmawia_gdy_nie_zlapal_waznego_albo_alarmuje_w_ponad_10_procentach_pr(tmp_path: Path, failed: str, clean: dict[str, str], where: str, summary: str) -> None:
    done, _ = _proof(tmp_path, failed, clean, where=where)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == f"DOWÓD ODMOWA | zakazane-wywolanie | {summary}", done.stdout


@pytest.mark.parametrize(
    "rule",
    [RULE.replace('files:\n  - "**/*.py"\n', ""), RULE.replace('files:\n  - "**/*.py"\n', "files: []\n")],
    ids=["bez-pola-files", "puste-pole-files"],
)
def test_dowod_reguly_odmawia_reguly_bez_pola_files_ktorej_zapadka_nie_przyjmie(tmp_path: Path, rule: str) -> None:
    """Zapadka podaje ast-grep każdy plik z dodaną linią, więc reguła bez ``files:`` objęłaby całe repozytorium
    i nie wejdzie (``tests/test_zapadki.py``): ``DOWÓD OK`` znaczy też, że reguła może wejść."""

    done, _ = _proof(tmp_path, CAUGHT, {"czysty.py": CLEAN}, rule=rule)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == (
        "DOWÓD ODMOWA | zakazane-wywolanie | zakazane-wywolanie: reguła bez pola files: obejmuje każdy plik repozytorium;"
        " dopisz files: z globami plików, w których obowiązuje (np. src/**/*.py albo .agents/skills/**/*.py), a wyjątki w ignores:"
    ), done.stdout


# Reguła, którą ładuje sgconfig.yml commitu (``--regula-id`` z ``--z-commita``), tak jak dowód uruchamia
# tools/scal_pr.py dla Ważnego z polem Idiom: (ADR 0036): HEAD tego repozytorium to merge PR #6 do ``main``.
BY_ID = ("--regula-id", "zakazane-wywolanie", "--z-commita", "HEAD")
SGCONFIG = "ruleDirs:\n  - reguly-ast-grep\n"


@needs_ast_grep
@pytest.mark.parametrize(
    "start",
    [
        {"sgconfig.yml": SGCONFIG, "reguly-ast-grep/podkatalog/zakazy.yml": RULE.replace("zakazane-wywolanie", "inna-regula") + "---\n" + RULE},
        {"sgconfig.yml": SGCONFIG, "reguly-ast-grep/zakazane-wywolanie.yml": RULE.replace("severity: error", "severity: off")},
    ],
    ids=["podkatalog-ruledirs", "waznosc-off"],
)
def test_dowod_reguly_o_id_bierze_regule_ktora_laduje_konfiguracja_ast_grep_commitu(tmp_path: Path, start: dict[str, str]) -> None:
    """Regułę wybiera ast-grep z ``sgconfig.yml`` commitu, jak zapadka: także ze zwykłego podkatalogu ``ruleDirs``
    i z ``severity: off``, którą zapadka też zgłasza (``test_regula_ast_grep_z_waznoscia_off_w_pliku_tez_zglasza_dodana_linie_src``)."""

    done, sha = _proof(tmp_path, CAUGHT, {"czysty.py": CLEAN}, start=start, chosen=BY_ID)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[0] == f"#5 W1 r1 | {sha[:8]} | złapane | odpalenia kod/inne.py:2 | Gdzie: kod/inne.py:1", done.stdout
    assert done.stdout.splitlines()[-1] == "DOWÓD OK | zakazane-wywolanie | złapane 1/1 | FP 0 w 0 z 2 PR (0%) | main 1", done.stdout


@needs_ast_grep
@pytest.mark.parametrize(
    "start",
    [
        {"sgconfig.yml": SGCONFIG, "tests/fixtures/znane_luki_zakazanego.py": 'ZNANE_LUKI = {"zakazane: wywołanie": "obiekt.zakazane()\\n"}\n'},
        {"sgconfig.yml": SGCONFIG, "reguly-ast-grep/inna.yml": RULE.replace("zakazane-wywolanie", "inna-regula")},
        {"sgconfig.yml": SGCONFIG, "inne-reguly/zakazane-wywolanie.yml": RULE},
        {"sgconfig.yml": SGCONFIG, "reguly-ast-grep/.wylaczone/zakazane-wywolanie.yml": RULE},
        {"reguly-ast-grep/zakazane-wywolanie.yml": RULE},
    ],
    ids=["tylko-probka-znane-luki", "regula-o-innym-id", "regula-poza-ruledirs", "regula-w-ukrytym-podkatalogu", "bez-sgconfig"],
)
def test_dowod_reguly_o_id_odmawia_reguly_ktorej_konfiguracja_ast_grep_nie_laduje(tmp_path: Path, start: dict[str, str]) -> None:
    """Próbka ``ZNANE_LUKI`` nie jest regułą, a reguły z ukrytego podkatalogu ``ruleDirs`` ast-grep nie ładuje, więc
    zapadka by jej nie odpaliła: dowód Ważnego z polem Idiom: bez reguły w konfiguracji commitu nie przechodzi."""

    done, _ = _proof(tmp_path, CAUGHT, {"czysty.py": CLEAN}, start=start, chosen=BY_ID)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == (
        "DOWÓD ODMOWA | zakazane-wywolanie | reguły o id zakazane-wywolanie nie ładuje konfiguracja ast-grep repo; połóż ją w reguly-ast-grep/"
    ), done.stdout


# Dowód typu albo testu (plik ``dowody-idiomow/<id>.json`` na HEAD, ``--help`` narzędzia): Ważne W1 PR-u #5 nadpisuje
# w ``ustaw`` stałą modułu ``kod/stala.py`` (``kod/inne.py:5``), jego poprawka zostawia sam odczyt, a otwarty PR #6
# zamyka tę postać typem ``Final``, testem albo niczym. Małe repozytorium ma własny ``pyproject.toml``, więc mypy
# sprawdza samo ``kod/``, a nie skopiowane narzędzia.
LIMIT_ID = "stala-limitu"
READ = "from kod import stala\n\n\ndef ustaw() -> int:\n    return stala.LIMIT\n"
OVERWRITE = "from kod import stala\n\n\ndef ustaw() -> int:\n    stala.LIMIT = 2\n    return stala.LIMIT\n"
AT_OVERWRITE = "Gdzie: kod/inne.py:5"
FINAL = {"kod/stala.py": "from typing import Final\n\nLIMIT: Final = 1\n"}
LIMIT_TEST = {"tests/test_inne.py": "from kod import inne, stala\n\n\ndef test_ustaw_nie_zmienia_limitu() -> None:\n    inne.ustaw()\n    assert stala.LIMIT == 1\n"}
SMALL_REPO = {
    "pyproject.toml": '[tool.mypy]\nstrict = true\nfiles = ["kod"]\n\n[tool.pytest.ini_options]\npythonpath = [".", "src"]\n',
    "src/rozliczenia/__init__.py": "",
    "kod/__init__.py": "",
    "kod/stala.py": "LIMIT = 1\n",
    "kod/inne.py": READ,
    "tests/test_inny.py": "def test_inny() -> None:\n    assert True\n",
}
MYPY = ["-m", "mypy"]
NODE = ["-m", "pytest", "-q", "-n", "0", "tests/test_inne.py::test_ustaw_nie_zmienia_limitu"]
needs_mypy = pytest.mark.skipif(importlib.util.find_spec("mypy") is None, reason="dowód typu uruchamia mypy z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt")


def _mutation_proof(
    tmp_path: Path,
    pull: dict[str, str],
    command: list[str] | str,
    *flags: str,
    failed: str = OVERWRITE,
    where: str = AT_OVERWRITE,
    fixed: str = READ,
    start: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Dowód id ``LIMIT_ID`` na HEAD otwartego PR #6 z plikami ``pull`` i plikiem dowodu z poleceniem ``command`` (tekst
    pliku, gdy to napis) po historii ``_history`` na ``main`` z plikami ``SMALL_REPO`` i ``start``, z werdyktem ``failed``,
    polem ``where`` i poprawką ``fixed``, uruchomiony jak przez ``tools/scal_pr.py`` z ``flags``. Zwraca bieg, SHA
    werdyktu i bazę PR #6."""

    github, sha = _history(tmp_path, failed, {**SMALL_REPO, **(start or {})}, where, RULE, fixed=fixed)
    base = git(github.checkout, "rev-parse", "main").strip()
    proof = command if isinstance(command, str) else json.dumps({"polecenie": command})
    head = github.commit_on("main", {f"dowody-idiomow/{LIMIT_ID}.json": proof, **pull}, "PR 6")
    return github.run("--regula-id", LIMIT_ID, "--z-commita", head, *flags, "--wazne", "5/W1/r1"), sha, base


# Zakres z werdyktu z odczytem stałej, której ``main`` już nie ma: mypy pada na nim także na bazie, bez mechanizmu.
DRIFT = OVERWRITE.replace("return stala.LIMIT", "return stala.STARY")
# Nadpisanie w funkcji wewnętrznej z lokalną zmienną ``ustaw``: baza ma jeszcze ``wpisz`` bez tej zmiennej, a HEAD
# już nie ma ``wpisz``, więc dowód przenosi całe ``ustaw``, najmniejszy zakres, który mają oba.
NESTED = "from kod import stala\n\n\ndef ustaw() -> int:\n    nowy = 2\n\n    def wpisz() -> None:\n        stala.LIMIT = nowy\n\n    wpisz()\n    return stala.LIMIT\n"
NESTED_FIXED = "from kod import stala\n\n\ndef ustaw() -> int:\n    def wpisz() -> None:\n        print(stala.LIMIT)\n\n    wpisz()\n    return stala.LIMIT\n"


@ONLY_FOUND_BY_NAME_ON_POSIX
@pytest.mark.parametrize(
    ("pull", "command", "failed", "where", "fixed"),
    [
        pytest.param(FINAL, MYPY, OVERWRITE, AT_OVERWRITE, READ, id="typ-final-w-mypy", marks=needs_mypy),
        pytest.param(LIMIT_TEST, NODE, OVERWRITE, AT_OVERWRITE, READ, id="test-w-pytest-ktorego-baza-nie-ma"),
        pytest.param(FINAL, MYPY, DRIFT, AT_OVERWRITE, READ, id="typ-final-obok-bledu-ktory-daje-baza", marks=needs_mypy),
        pytest.param({**FINAL, "kod/inne.py": READ}, MYPY, NESTED, "Gdzie: kod/inne.py:8", NESTED_FIXED, id="zakres-wewnetrzny-ktorego-head-nie-ma", marks=needs_mypy),
    ],
)
def test_dowod_typu_albo_testu_bierze_zla_postac_z_werdyktu_i_wykrywa_ja_na_head_a_nie_na_bazie(
    tmp_path: Path, pull: dict[str, str], command: list[str], failed: str, where: str, fixed: str
) -> None:
    """Autor nie pisze mutacji: dowód wstawia zakres z werdyktu wokół ``Gdzie`` w miejsce tego z HEAD i z bazy PR, a
    polecenie Required CI pada na HEAD ze znaleziskiem, którego baza nie daje, także gdy ten zakres ma błąd, który daje
    i baza."""

    done, sha, base = _mutation_proof(tmp_path, pull, command, failed=failed, where=where, fixed=fixed)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [
        f"#5 W1 r1 | {sha[:8]} | miejsca 1/1 | {where}",
        f"DOWÓD OK | {LIMIT_ID} | przypadki 1/1 | 1 wykryte na HEAD bez tego samego na bazie {base[:8]}",
    ], done.stdout


SHAPE = 'dowody-idiomow/stala-limitu.json to {{"polecenie": [argumenty Pythona]}}, bo złą postać bierze dowód z werdyktu'
NOT_MOVED = "#5 W1 r1: żadnego miejsca z Gdzie nie da się przenieść z werdyktu na HEAD i bazę {base}: kod/inne.py:{line}: {cause}"
NOT_CAUGHT = "#5 W1 r1: żadne przeniesienie nie pada na HEAD bez tego samego na bazie {base}: kod/inne.py HEAD: {head}, baza: {old}"
CLEAN_MYPY = "Success: no issues found in 3 source files"
DRIFT_MYPY = "Found 2 errors in 1 file (checked 3 source files)"
HELPER = "from kod import stala\n\n\ndef pomoc() -> int:\n    return 2\n\n\ndef ustaw() -> int:\n    stala.LIMIT = pomoc()\n    return stala.LIMIT\n"
# Pierwsza postać pliku dowodu (r1–r2 #1912): mutacja autora, która może wpisać złą postać tam, gdzie pada przez siebie.
AUTHOR_MUTATION = json.dumps([{"nazwa": "nadpisanie", "zmiany": [["kod/inne.py", "LIMIT = 1\n", "LIMIT = 1\nLIMIT = 2\n"]], "polecenie": MYPY}])


@ONLY_FOUND_BY_NAME_ON_POSIX
@pytest.mark.parametrize(
    ("pull", "command", "failed", "where", "summary"),
    [
        pytest.param(FINAL, AUTHOR_MUTATION, OVERWRITE, AT_OVERWRITE, SHAPE, id="mutacja-autora-w-pliku-dowodu"),
        pytest.param({"kod/inne.py": OVERWRITE}, MYPY, OVERWRITE, AT_OVERWRITE, NOT_MOVED.format(base="{base}", line=5, cause="postać z werdyktu stoi już na HEAD"), id="postac-na-head"),
        pytest.param(FINAL, MYPY, HELPER, "Gdzie: kod/inne.py:10", NOT_MOVED.format(base="{base}", line=10, cause="zakres ustaw z werdyktu bierze pomoc, a tu tego nie ma"), id="nazwa-spoza-importow-werdyktu"),
        pytest.param({}, MYPY, OVERWRITE, AT_OVERWRITE, NOT_CAUGHT.format(base="{base}", head=CLEAN_MYPY, old=CLEAN_MYPY), id="mechanizm-nie-lapie", marks=needs_mypy),
        pytest.param(
            {"kod/inne.py": "from kod.stala import LIMIT\n\n\ndef ustaw() -> int:\n    return LIMIT\n"}, MYPY, OVERWRITE, AT_OVERWRITE,
            NOT_CAUGHT.format(base="{base}", head=CLEAN_MYPY, old=CLEAN_MYPY), id="head-bez-importu-z-werdyktu-i-bez-mechanizmu", marks=needs_mypy,
        ),
        # HEAD przesuwa linie pliku, więc to samo znalezisko ma na HEAD inny numer linii niż na bazie.
        pytest.param(
            {"kod/inne.py": '"""Odczyt stałej."""\n\n' + READ}, MYPY, DRIFT, AT_OVERWRITE, NOT_CAUGHT.format(base="{base}", head=DRIFT_MYPY, old=DRIFT_MYPY), id="blad-zakresu-takze-na-bazie", marks=needs_mypy
        ),
        pytest.param(
            {**FINAL, "kod/zly.py": "X: int = 'tekst'\n"}, MYPY, OVERWRITE, AT_OVERWRITE, "podstawa -m mypy bez przeniesienia: Found 1 error in 1 file (checked 4 source files)", id="podstawa-czerwona", marks=needs_mypy
        ),
        pytest.param(FINAL, ["-m", "mypy", "kod"], OVERWRITE, AT_OVERWRITE, "polecenie -m mypy kod to ruff albo mypy zadania „Ruff, mypy” albo -m pytest -q -n 0 tests/<plik>::<test>", id="mypy-spoza-krokow-ci"),
        pytest.param(
            LIMIT_TEST, [*NODE[:-1], "tests/test_inny.py::test_inny"], OVERWRITE, AT_OVERWRITE, "zakres runu pull requestu przy zmianie kod/inne.py nie uruchamia tests/test_inny.py::test_inny", id="test-spoza-zakresu-runu-pr"
        ),
    ],
)
def test_dowod_typu_albo_testu_odmawia_bez_wykrycia_ktorego_nie_daje_baza(
    tmp_path: Path, pull: dict[str, str], command: list[str] | str, failed: str, where: str, summary: str
) -> None:
    """Plik dowodu z mutacją autora, postać z werdyktu już na HEAD, zakres z nazwą, której HEAD nie ma, polecenie, które
    tak samo pada albo przechodzi na bazie, czerwona podstawa i polecenie spoza Required CI to odmowa."""

    done, _, base = _mutation_proof(tmp_path, pull, command, failed=failed, where=where)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == f"DOWÓD ODMOWA | {LIMIT_ID} | {summary.format(base=base[:8])}", done.stdout


@ONLY_FOUND_BY_NAME_ON_POSIX
@needs_mypy
def test_dowod_typu_albo_testu_na_bazie_z_dowodem_tego_id_wymaga_przypadku_wykrytego_tylko_na_head(tmp_path: Path) -> None:
    """Baza z plikiem dowodu tego id i z mechanizmem łapie już przypadek z historii, więc pada on na obu bez odmowy
    przypadku, ale dowód bez żadnego przypadku, który łapie dopiero HEAD, to odmowa: PR nie wnosi mechanizmu."""

    proven = {**FINAL, f"dowody-idiomow/{LIMIT_ID}.json": json.dumps({"polecenie": MYPY})}

    done, _, base = _mutation_proof(tmp_path, {"kod/nowy.py": ""}, MYPY, start=proven)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == (
        f"DOWÓD ODMOWA | {LIMIT_ID} | żaden przypadek nie pada na HEAD bez tego samego na bazie {base[:8]}, choć baza ma już dowód {LIMIT_ID}"
    ), done.stdout


@ONLY_FOUND_BY_NAME_ON_POSIX
@pytest.mark.parametrize(
    ("pull", "code", "summary"),
    [
        ({}, 0, f"DOWÓD OK | {LIMIT_ID} | przypadki 1/1 | bez biegu (--bez-kodu-pr)"),
        ({"kod/inne.py": OVERWRITE}, 1, f"DOWÓD ODMOWA | {LIMIT_ID} | " + NOT_MOVED.format(base="{base}", line=5, cause="postać z werdyktu stoi już na HEAD")),
    ],
    ids=["mechanizm-nie-lapie-bez-biegu", "postac-na-head"],
)
def test_dowod_typu_albo_testu_bez_kodu_pr_nie_wykonuje_niczego_z_head_a_sprawdza_przeniesienie(tmp_path: Path, pull: dict[str, str], code: int, summary: str) -> None:
    """Status „Werdykt i bramka” ma token do statusów, więc nie wykonuje żadnego pliku HEAD PR: ani skryptu mutacji
    skilla, który pełny zakres runu wykonuje przy skanie kroków skilli (#1912 r1 W1), ani ``conftest.py`` polecenia
    pytest. Mechanizmu, który nie łapie postaci, więc nie widzi; widzi postać, której nie da się przenieść."""

    marker = tmp_path / "wykonany-plik-head"
    trap = f"import pathlib\npathlib.Path({str(marker)!r}).write_text(__file__)\nMUTATIONS = []\n"
    traps = {".agents/skills/obcy/scripts/check_obcy_mutations.py": trap, "tests/conftest.py": trap, **LIMIT_TEST}

    done, _, base = _mutation_proof(tmp_path, {**traps, **pull}, NODE, "--bez-kodu-pr")

    assert done.returncode == code, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == summary.format(base=base[:8]), done.stdout
    assert not marker.exists(), marker.read_text(encoding="utf-8")


# Znane luki dowodu typu albo testu (tests/fixtures/znane_luki.py): klasa → pliki otwartego PR #6 i polecenie. Kontrola
# na bazie odróżnia błąd, który przyniósł PR, od błędu, który zakres z werdyktu daje już na bazie, ale nie mówi, czy pada
# przez złą postać: PR, który zmienia nazwę atrybutu, którego ten zakres używa, przechodzi bez mechanizmu.
ZNANE_LUKI = {
    "kontrola porównuje znaleziska z bazą, nie ich przyczynę: PR zmienia nazwę atrybutu, którego używa zakres z werdyktu": (
        {"kod/stala.py": "LIMIT2 = 1\n", "kod/inne.py": READ.replace("LIMIT", "LIMIT2")},
        MYPY,
    ),
}


@ONLY_FOUND_BY_NAME_ON_POSIX
@needs_mypy
def test_znane_luki_dowodu_typu_albo_testu_przechodza_przez_dowod(tmp_path: Path) -> None:
    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, (pull, command)) in enumerate(ZNANE_LUKI.items()):
        done, _, _ = _mutation_proof(tmp_path / str(numer), pull, command)
        zgloszenia[opis] = [] if done.returncode == 0 else [done.stdout.splitlines()[-1] if done.stdout else done.stderr]

    assert_znane_luki(zgloszenia, "tests/test_na_scalonych_pr.py")
