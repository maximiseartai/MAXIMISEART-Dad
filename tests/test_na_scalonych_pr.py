"""``tools/na_scalonych_pr.py`` uruchamia polecenie z narzędziami checkoutu na wskazanym commicie, bez dotykania checkoutu."""

from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys

import pytest

import chroniony_wlasciciel
import na_scalonych_pr
import strazniki_przeniesione
from tests.fixtures import werdykty_szablonu
from tests.fixtures.body_html import body_html
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub
from tests.fixtures.git_repo import commit, copy_files, git, mutation_repository, repository, with_imports
from tests.fixtures.srodowisko import DEV, PINS, project, wymaga_uv

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


def _proof(
    tmp_path: Path,
    failed: str,
    clean: dict[str, str],
    start: dict[str, str] | None = None,
    where: str = WHERE,
    rule: str = RULE,
    chosen: tuple[str, ...] = ("--regula", "regula.yml"),
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Bieg dowodu reguły wybranej argumentami ``chosen`` (domyślnie plik ``regula.yml`` z treścią ``rule``) na
    repozytorium ``_merged``."""

    github, sha = _merged(tmp_path, failed, clean, {"regula.yml": rule, **(start or {})}, where)
    return github.run(*chosen, "--wazne", "5/W1/r1", "--ostatnie", "2"), sha


def _merged(tmp_path: Path, failed: str, clean: dict[str, str], start: dict[str, str], where: str = WHERE) -> tuple[FakeGitHub, str]:
    """``main`` z plikami ``start`` i dawnym odpaleniem w ``stare.py`` i dwoma merge'ami: PR #5, którego werdykt FAIL
    z polem ``where`` ma ``kod/inne.py`` w postaci ``failed`` (poprawka go usuwa), i PR #6 z plikami ``clean``;
    obok SHA linii ``WERDYKT``."""

    files = {"stare.py": OLD.format("obiekt"), **start}
    github = FakeGitHub(tmp_path, files, tool="tools/na_scalonych_pr.py", gh=FAKE_GH)
    sha = _merge(github, 5, {"kod/inne.py": failed}, {"kod/inne.py": CLEAN})[0]
    _merge(github, 6, clean)
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
def test_dowod_reguly_liczy_wystapienie_na_main_w_linii_ze_znakiem_podzialu_splitlines_u2028(tmp_path: Path) -> None:
    done, _ = _proof(tmp_path, CAUGHT, {"czysty.py": CLEAN}, start={"znak.py": "def znak(obiekt):\n    return obiekt.zakazane() or '\u2028'\n"})

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == "DOWÓD OK | zakazane-wywolanie | złapane 1/1 | FP 0 w 0 z 2 PR (0%) | main 2", done.stdout


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


# Przypadki z pola metadata.przypadki reguły: Ważne W1 PR #5 i merge PR #6, który dodaje odpalenie w kod/drugi.py:2.
CASES = "metadata:\n  przypadki:\n    - 5/W1/r1\n    - {merge} kod/drugi.py:1\n"


def _founding(tmp_path: Path, rules: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Bieg ``--przypadki-regul`` z regułami ``rules`` (plik → treść, w której ``{merge}`` to SHA merge'a PR #6)
    w ``reguly-ast-grep/`` checkoutu repozytorium ``_merged``; obok SHA linii ``WERDYKT`` PR #5 i merge'a PR #6."""

    github, sha = _merged(tmp_path, CAUGHT, {"kod/drugi.py": CAUGHT}, {"sgconfig.yml": SGCONFIG})
    merge = git(github.checkout, "rev-parse", "HEAD")
    for name, text in rules.items():
        (github.checkout / "reguly-ast-grep").mkdir(exist_ok=True)
        (github.checkout / "reguly-ast-grep" / name).write_text(text.replace("{merge}", merge), encoding="utf-8")
    return github.run("--przypadki-regul"), sha, merge


@needs_ast_grep
def test_przypadki_regul_lapia_wazne_i_commit_z_pola_metadata_kazdej_reguly(tmp_path: Path) -> None:
    done, sha, merge = _founding(tmp_path, {"zakazane-wywolanie.yml": RULE + CASES})

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [
        f"#5 W1 r1 | {sha[:8]} | złapane | odpalenia kod/inne.py:2 | Gdzie: kod/inne.py:1",
        f"commit | {merge[:8]} | złapane | odpalenia kod/drugi.py:2 | Gdzie: kod/drugi.py:1",
        "PRZYPADKI REGUŁ OK | 1 reguł, 2 przypadków",
    ], done.stdout


@needs_ast_grep
def test_przypadki_regul_odmawiaja_reguly_ktora_nie_lapie_przypadku_albo_go_nie_ma(tmp_path: Path) -> None:
    """Reguła osłabiona tak, że nie odpala już w ``Gdzie`` swoich przypadków, i reguła bez pola ``metadata.przypadki``
    to odmowa z tym, co zrobić."""

    weakened = RULE.replace("$O.zakazane()", "$O.inne()") + CASES
    done, _, merge = _founding(tmp_path, {"a.yml": RULE.replace("zakazane-wywolanie", "bez-przypadku"), "b.yml": weakened})

    assert done.returncode == 1, done.stdout + done.stderr
    again = "popraw regułę tak, by znów odpalała w jego Gdzie"
    assert done.stdout.splitlines()[-1] == (
        "PRZYPADKI REGUŁ FAIL | bez-przypadku: bez pola metadata.przypadki; dopisz przypadek, który reguła łapie: Ważne PR/W<n>/r<k> albo <pełny SHA> plik:linia"
        f" | zakazane-wywolanie: nie łapie 5/W1/r1; {again} | zakazane-wywolanie: nie łapie {merge} kod/drugi.py:1; {again}"
    ), done.stdout


# Reguła PR, która nie wymienia już przypadku bazy 5/W1/r1: plik → treść (``{merge}`` to SHA merge'a PR #6). Ochrona
# przypadku nie zależy od id ani od pliku reguły, bo obie zmiany wybiera sam PR.
ZGUBIONE_PRZYPADKI = {
    "to samo id": {"zakazane-wywolanie.yml": RULE + "metadata:\n  przypadki:\n    - {merge} kod/drugi.py:1\n"},
    "zmienione id": {
        "zakazane-wywolanie.yml": RULE.replace("id: zakazane-wywolanie", "id: zakazane-wywolanie-2") + "metadata:\n  przypadki:\n    - {merge} kod/drugi.py:1\n"
    },
    "reguła w innym pliku": {"inna.yml": RULE + "metadata:\n  przypadki:\n    - {merge} kod/drugi.py:1\n"},
}


@needs_ast_grep
@pytest.mark.parametrize("rules", ZGUBIONE_PRZYPADKI.values(), ids=ZGUBIONE_PRZYPADKI)
def test_przypadki_regul_z_commita_pr_odmawiaja_przypadku_z_bazy_ktorego_zadna_regula_pr_nie_wymienia(
    tmp_path: Path, rules: dict[str, str]
) -> None:
    """``--z-commita`` HEAD PR z regułami bazy w checkoucie (``tools/scal_pr.py``, warunek 6): PR, którego reguły nie
    wymieniają przypadku z bazy, nie przechodzi, choć jego reguły łapią wszystkie swoje przypadki i ten sam bieg na
    jego regułach (krok CI kodem PR) przechodzi."""

    github, _ = _merged(tmp_path, CAUGHT, {"kod/drugi.py": CAUGHT}, {"sgconfig.yml": SGCONFIG})
    merge = git(github.checkout, "rev-parse", "HEAD")
    rule = github.checkout / "reguly-ast-grep" / "zakazane-wywolanie.yml"
    rule.parent.mkdir(exist_ok=True)
    for name, text in rules.items():
        (rule.parent / name).write_text(text.replace("{merge}", merge), encoding="utf-8")
    git(github.checkout, "switch", "--quiet", "--create", "pr")
    head = commit(github.checkout, "PR usuwa przypadek 5/W1/r1")
    on_pr = github.run("--przypadki-regul")
    git(github.checkout, "switch", "--quiet", "-")
    rule.parent.mkdir(exist_ok=True)
    for name in rules:
        (rule.parent / name).unlink(missing_ok=True)
    rule.write_text(RULE + CASES.replace("{merge}", merge), encoding="utf-8")

    done = github.run("--przypadki-regul", "--z-commita", head)

    assert on_pr.returncode == 0, on_pr.stdout + on_pr.stderr
    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == (
        "PRZYPADKI REGUŁ FAIL | PR usuwa z metadata.przypadki przypadki z bazy 5/W1/r1: każdy z nich wymienia reguła, która go łapie; przywróć je i popraw regułę tak, by je łapała"
    ), done.stdout


# Piny pytest i xdist z dodatku dev repozytorium dla dowodu ``pytest <węzeł>``, który biegnie ``-n 0`` (opcja xdist).
PYTEST_PINS = tuple(pin for pin in DEV if pin.startswith(("pytest==", "pytest-xdist==")))
# Dowód strażnika (``--straznik``, ADR 0042) tak, jak uruchamia go tools/scal_pr.py: PR #5 z werdyktem FAIL na wersji
# z ``zakazane()`` w ``kod/inne.py`` i HEAD z poprawką i testem, który pada na wersji z werdyktu.
GUARD_TEST = "from kod.inne import wazne\n\n\nclass Obiekt:\n    def dozwolone(self) -> None:\n        pass\n\n\ndef test_wazne_wola_tylko_dozwolone() -> None:\n    wazne(Obiekt())\n"


def _guard_proof(
    tmp_path: Path,
    *arguments: str,
    failed_files: dict[str, str] | None = None,
    fixed_files: dict[str, str] | None = None,
    where: str = WHERE,
    dev: tuple[str, ...] = (),
    findings: str = werdykty_szablonu.WERDYKTY["wazne"],
    later: str | None = None,
    base: dict[str, str] | None = None,
    on_main: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Dowód ``arguments`` (``--straznik`` z selektorem) dla Ważnego 5/W1/r1 z werdyktu FAIL z treścią ``findings``,
    a z ``later`` także z późniejszym werdyktem PASS HEAD z tą treścią; ``dev`` to dodatkowe piny dodatku dev, a ``base``
    dokłada pliki do bazy."""

    files = {"kod/__init__.py": "", "tests/__init__.py": "", "stare.py": OLD.format("obiekt"), "regula.yml": RULE, **project(dev=dev, tools='[tool.mypy]\nfiles = ["kod"]\n\n[tool.pytest.ini_options]\n'), **(base or {})}
    files["kod/typy.py"] = "class Obiekt:\n    def dozwolone(self) -> None:\n        pass\n"
    github = FakeGitHub(tmp_path, files, tool="tools/na_scalonych_pr.py", gh=FAKE_GH)
    fixed = fixed_files or {"kod/inne.py": CAUGHT.replace("zakazane", "dozwolone"), "tests/test_inne.py": GUARD_TEST}
    failed, head = _merge(github, 5, failed_files or {"kod/inne.py": CAUGHT}, fixed)
    rendered = {text.replace(WHERE, where): html.replace(WHERE, where) for text, html in werdykty_szablonu.rendered().items()}
    verdicts = [f"WERDYKT: FAIL {failed}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + findings.replace(WHERE, where)]
    verdicts += [] if later is None else [f"WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n{later}"]
    comments = [
        {"body": verdict, "bodyHTML": body_html(verdict, rendered), "authorAssociation": "OWNER", "createdAt": f"2026-11-14T0{hour}:00:00Z", "author": {"login": "recenzent"}}
        for hour, verdict in enumerate(verdicts, start=1)
    ]
    pages = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
    pull = {
        **{"number": 5, "title": "PR 5", "state": "MERGED", "isDraft": False, "isCrossRepository": False, "baseRefName": "main", "headRefOid": head},
        **{"url": "https://github.com/maximiseartai/MAXIMISEART-Dad/pull/5", "body": "", "comments": {**pages, "nodes": comments}, "reviews": {**pages, "nodes": []}},
    }
    (github.bin / "state.json").write_text(json.dumps(pull), encoding="utf-8")
    if on_main is not None:
        _merge(github, 6, on_main)
        head = git(github.checkout, "rev-parse", "main").strip()
    return github.run(*arguments, "--z-commita", head, "--wazne", "5/W1/r1"), failed


@pytest.mark.parametrize(
    ("arguments", "last"),
    [
        (("--straznik", "brak - test"), "DOWÓD ODMOWA | brak - test | wyjątek 0/1"),
        (("--straznik", "brak - test", "--przed-dowodem-testu"), "DOWÓD OK | brak - test | wyjątek 1/1"),
        (("--straznik", "pytest tests/test_inne.py"), "DOWÓD ODMOWA | pytest tests/test_inne.py | „Strażnik: pytest tests/test_inne.py” to nie selektor strażnika z listy: "),
    ],
    ids=["brak-testu-po-wdrozeniu-dowodu-testu", "brak-testu-w-watku-sprzed-dowodu-testu", "plik-testow-zamiast-wezla"],
)
@ONLY_FOUND_BY_NAME_ON_POSIX  # atrapa gh .cmd nie przenosi wielowierszowego zapytania GraphQL (#2116 r2 W2)
def test_brak_testu_to_odmowa_poza_watkiem_sprzed_dowodu_testu(tmp_path: Path, arguments: tuple[str, ...], last: str) -> None:
    """Strażnik-test ma dowód z mutacją recenzenta (``pytest <węzeł>``), więc ``brak - test`` to odmowa, a w wątku sprzed
    wdrożenia dowodu testu (``--przed-dowodem-testu`` od ``bramka_straznika``) przechodzi jak przed nim; selektor
    testu to jeden węzeł, nie plik."""

    done, failed = _guard_proof(tmp_path, *arguments)

    assert done.returncode == (0 if last.startswith("DOWÓD OK") else 1), done.stdout + done.stderr
    assert done.stdout.splitlines()[-1].startswith(last), done.stdout
    if arguments[-1] == "--przed-dowodem-testu":
        assert done.stdout.splitlines()[0] == f"#5 W1 r1 | {failed[:8]} | WYJĄTEK brak - test | czy test pada na błędzie z Gdzie, sprawdza recenzent następnej rundy", done.stdout


@wymaga_uv
@pytest.mark.parametrize(
    ("later", "where", "state", "last"),
    [
        (
            None,
            WHERE,
            "ODMOWA | inne z FAIL: kotwicy nie ma dokładnie raz w kod/inne.py: 'obiekt.inne()' na HEAD scalonym z bazą: recenzent następnej rundy odnawia blok ### Mutacja W1 r1",
            "DOWÓD ODMOWA",
        ),
        (werdykty_szablonu.WERDYKTY["pass-z-mutacja"], WHERE, "WYKRYTA | z bloku ### Mutacja W1 r1: zakazane z FAIL → 1 failed", "DOWÓD OK"),
        (werdykty_szablonu.WERDYKTY["pass-z-mutacja"], "Gdzie: ~/.zshrc:17 (poza repo)", "WYKRYTA | z bloku ### Mutacja W1 r1: zakazane z FAIL → 1 failed", "DOWÓD OK"),
    ],
    ids=["blok-z-fail-nieaktualny", "najnowszy-blok-z-pozniejszego-werdyktu", "wazne-z-gdzie-poza-repo"],
)
@ONLY_FOUND_BY_NAME_ON_POSIX
def test_dowod_straznika_pytest_liczy_wezel_z_najnowszym_blokiem_mutacji_w_srodowisku_toru_linux(tmp_path: Path, later: str | None, where: str, state: str, last: str) -> None:
    """``Strażnik: pytest <węzeł>`` tak, jak uruchamia go ``tools/scal_pr.py``: test z HEAD pada z mutacją z najnowszego
    bloku ``### Mutacja W1 r1`` w werdyktach PR, w środowisku toru Linux Required CI z ``srodowisko_ci.built`` (jego
    zmienne widzi test); blok z FAIL, którego kotwicy nie ma na HEAD, odnawia recenzent następnej rundy. Złą postać daje
    mutacja, nie ``Gdzie``, więc Ważne o pliku spoza repo (``Gdzie`` bez miejsca ``plik:linia``) też ma dowód."""

    in_ci = "import os\n\n" + GUARD_TEST.replace("    wazne(Obiekt())\n", "    assert os.environ.get('EXPECTED_PYTHON_VERSION') == '3.14'\n    wazne(Obiekt())\n")
    fixed = {"kod/inne.py": CAUGHT.replace("zakazane", "dozwolone"), "tests/test_inne.py": in_ci}
    stale = werdykty_szablonu.WERDYKTY["wazne-z-nieaktualna-mutacja"]

    done, failed = _guard_proof(tmp_path, "--straznik", "pytest tests/test_inne.py::test_wazne_wola_tylko_dozwolone", fixed_files=fixed, where=where, dev=PYTEST_PINS, findings=stale, later=later)

    assert done.returncode == (0 if last == "DOWÓD OK" else 1), done.stdout + done.stderr
    [line, end] = done.stdout.splitlines()
    assert line.startswith(f"#5 W1 r1 | {failed[:8]} | {state}"), done.stdout
    assert end.startswith(f"{last} | pytest tests/test_inne.py::test_wazne_wola_tylko_dozwolone | wykryte"), done.stdout


GUARD_NODE = "pytest tests/test_inne.py::test_wazne_wola_tylko_dozwolone"
FIXED_WITH_TEST = {"kod/inne.py": CAUGHT.replace("zakazane", "dozwolone"), "tests/test_inne.py": GUARD_TEST}
OWNER_RULE = "id: przez-wlasciciela\nlanguage: python\nmessage: wołaj wazne() z kod/inne.py\nfiles:\n  - '**/*.py'\nignores:\n  - {owner}\nrule:\n  pattern: $O.zakazane()\n"
OUTSIDE_OWNER = f"DOWÓD ODMOWA | {GUARD_NODE} | #5 W1 r1: Mechanizm: test przyjmuje Strażnik: pytest tylko na chronionym właścicielu, a {{named}} nim nie jest w konfiguracji reguł HEAD scalonego z bazą ("


def _owner(owner: str) -> dict[str, str]:
    return {"sgconfig.yml": SGCONFIG, "reguly-ast-grep/przez-wlasciciela.yml": OWNER_RULE.format(owner=owner)}


OWNER = "src/pakiet/modul.py"
RUFF_EXEMPT = '[lint.per-file-ignores]\n"{pattern}" = ["{code}"]\n'
CONTRACT = "[importlinter]\nroot_package = pakiet\n\n[importlinter:contract:jedno-wejscie]\nname = x\ntype = protected\nprotected_modules =\n    os\n{field} =\n    {module}\n"
IGNORING_RULE = "id: regula\nlanguage: python\nmessage: użyj właściciela\nfiles:\n  - '**/*.py'\nignores:\n  - {pattern}\nrule:\n  pattern: zle()\n"


def _exempt(pattern: str = OWNER, code: str = "TID251") -> dict[str, str]:
    return {"ruff.toml": RUFF_EXEMPT.format(pattern=pattern, code=code)}


def _ignoring(pattern: str, directory: str = "reguly-ast-grep") -> dict[str, str]:
    return {"sgconfig.yml": SGCONFIG, f"{directory}/regula.yml": IGNORING_RULE.format(pattern=pattern)}


@pytest.mark.parametrize(
    ("config", "owned"),
    [
        pytest.param(_exempt(), True, id="zwolnienie-z-zakazu-tid251"),
        pytest.param(_exempt(pattern="src/pakiet/{modul,inny}.py"), True, id="zwolnienie-tid251-z-plikiem-w-nawiasie"),
        pytest.param(_exempt(code="BLE001"), False, id="zwolnienie-z-innej-reguly-niz-tid251"),
        pytest.param(_exempt(pattern="src/pakiet/*.py"), False, id="zwolnienie-tid251-na-wzorcu-zasiegu"),
        pytest.param({"ruff.toml": "[lint.per-file-ignores\n"}, False, id="ruff-toml-ktorego-toml-nie-wczyta"),
        pytest.param({".importlinter": CONTRACT.format(field="allowed_importers", module="pakiet.modul")}, True, id="allowed-importers-kontraktu-importow"),
        pytest.param({".importlinter": CONTRACT.format(field="allowed_importers", module="pakiet.*")}, False, id="allowed-importers-ze-wzorcem"),
        pytest.param({".importlinter": CONTRACT.format(field="ignore_imports", module="pakiet.modul")}, False, id="modul-w-innym-polu-kontraktu"),
        pytest.param(_ignoring(OWNER), True, id="ignores-reguly-ast-grep"),
        pytest.param(_ignoring(OWNER, directory="poza"), False, id="ignores-reguly-spoza-rule-dirs"),
        pytest.param(_ignoring("src/**"), False, id="ignores-ze-wzorcem-zasiegu"),
        pytest.param(_ignoring("src/pakiet"), False, id="ignores-katalogu-wlasciciela"),
        pytest.param(_ignoring("src/pakiet/modul"), False, id="ignores-z-przedrostkiem-sciezki-wlasciciela"),
        pytest.param({}, False, id="plik-spoza-konfiguracji-regul"),
    ],
)
def test_chroniony_wlasciciel_to_plik_wskazany_wprost_przez_konfiguracje_regul_drzewa(tmp_path: Path, config: dict[str, str], owned: bool) -> None:
    root = repository(tmp_path / "repo", {OWNER: "WARTOSC = 1\n", "src/pakiet/__init__.py": "", **config}, tools=())
    commit(root, "drzewo")

    protected = chroniony_wlasciciel.owners(root, git(root, "rev-parse", "HEAD^{tree}"))

    assert (OWNER in protected) is owned, sorted(protected)
    assert (chroniony_wlasciciel.refusal([OWNER], protected) is None) is owned


@pytest.mark.parametrize(
    ("base", "fixed", "where", "named"),
    [
        pytest.param({}, FIXED_WITH_TEST, WHERE, "kod/inne.py", id="plik-spoza-konfiguracji-regul"),
        pytest.param(_owner("kod/inne.py"), {**FIXED_WITH_TEST, **_owner("kod/drugi.py")}, WHERE, "kod/inne.py", id="wlasciciel-z-bazy-usuniety-w-pr"),
        pytest.param(_owner("kod/inne.py"), FIXED_WITH_TEST, "Gdzie: kod/inne.py:1, kod/typy.py:1", "kod/typy.py", id="drugi-plik-z-gdzie-poza-wlascicielem"),
        pytest.param({}, FIXED_WITH_TEST, "Gdzie: ~/.zshrc:17 (poza repo)", "Gdzie bez miejsca plik:linia w repo", id="gdzie-poza-repo"),
    ],
)
@ONLY_FOUND_BY_NAME_ON_POSIX
def test_straznik_pytest_szczebla_test_poza_chronionym_wlascicielem_to_odmowa_z_droga_do_architektury(
    tmp_path: Path, base: dict[str, str], fixed: dict[str, str], where: str, named: str
) -> None:
    done, _ = _guard_proof(tmp_path, "--straznik", GUARD_NODE, "--chroniony-wlasciciel", base=base, fixed_files=fixed, where=where)

    last = done.stdout.splitlines()[-1]
    assert done.returncode == 1 and last.startswith(OUTSIDE_OWNER.format(named=named)), done.stdout + done.stderr
    assert "właściciel bez tej ochrony to szczebel architektura: dopisz w tym PR zakaz TID251 albo regułę ast-grep, która kieruje resztę kodu do właściciela" in last, last


@wymaga_uv
@ONLY_FOUND_BY_NAME_ON_POSIX
def test_straznik_pytest_szczebla_test_ma_dowod_na_wlascicielu_dopisanym_w_tym_samym_pr(tmp_path: Path) -> None:
    fixed = {**FIXED_WITH_TEST, **_owner("kod/inne.py")}

    done, failed = _guard_proof(tmp_path, "--straznik", GUARD_NODE, "--chroniony-wlasciciel", fixed_files=fixed, dev=PYTEST_PINS, later=werdykty_szablonu.WERDYKTY["pass-z-mutacja"])

    assert done.returncode == 0, done.stdout + done.stderr
    [line, end] = done.stdout.splitlines()
    assert line.startswith(f"#5 W1 r1 | {failed[:8]} | WYKRYTA | z bloku ### Mutacja W1 r1: zakazane z FAIL → 1 failed"), done.stdout
    assert end == f"DOWÓD OK | {GUARD_NODE} | wykryte 1/1", done.stdout


REWRITTEN = {"kod/inne.py": 'def wazne(obiekt):\n    getattr(obiekt, "dozwolone")()\n'}
MOVED_MUTATION = '''[{"nazwa": "zakazane na nowej kotwicy", "zmiany": [["kod/inne.py", "getattr(obiekt, \\"dozwolone\\")()", "obiekt.zakazane()"]]}]'''
STALE = "ODMOWA | zakazane z FAIL: kotwicy nie ma dokładnie raz w kod/inne.py"


def _moved_entry(selector: str) -> dict[str, str]:
    return {strazniki_przeniesione.PLIK: f'["5/W1/r1"]\nstraznik = "{selector}"\nmutacja = \'\'\'{MOVED_MUTATION}\'\'\'\n'}


@wymaga_uv
@pytest.mark.parametrize(
    ("later_files", "state", "last"),
    [
        ({"kod/obok.py": "OBOK = 1\n"}, "WYKRYTA | z bloku ### Mutacja W1 r1: zakazane z FAIL → 1 failed", "DOWÓD OK"),
        ({"tests/test_inne.py": "def test_wazne_wola_tylko_dozwolone() -> None:\n    pass\n"}, "NIEWYKRYTA | zakazane z FAIL: NIEWYKRYTA", "DOWÓD ODMOWA"),
        (REWRITTEN, STALE, "DOWÓD ODMOWA"),
        ({**REWRITTEN, **_moved_entry("pytest tests/test_inne.py::test_wazne_wola_tylko_dozwolone")}, "WYKRYTA | z bloku ### Mutacja W1 r1: zakazane na nowej kotwicy → 1 failed", "DOWÓD OK"),
        ({**REWRITTEN, **_moved_entry("pytest tests/test_inne.py::test_inny")}, STALE, "DOWÓD ODMOWA"),
    ],
    ids=[
        "pozniejszy-commit-nie-rusza-straznika",
        "pozniejszy-commit-wylacza-straznika",
        "pozniejszy-commit-zmienia-kotwice-mutacji",
        "wpis-straznika-przeniesionego-niesie-mutacje-na-nowej-kotwicy",
        "wpis-innego-selektora-nie-zmienia-mutacji",
    ],
)
@ONLY_FOUND_BY_NAME_ON_POSIX
def test_ponowny_dowod_straznika_scalonego_pr_na_pozniejszym_main_wykrywa_tylko_gdy_main_nie_wylaczyl_straznika(tmp_path: Path, later_files: dict[str, str], state: str, last: str) -> None:
    done, failed = _guard_proof(
        tmp_path,
        "--straznik",
        "pytest tests/test_inne.py::test_wazne_wola_tylko_dozwolone",
        dev=PYTEST_PINS,
        findings=werdykty_szablonu.WERDYKTY["wazne-z-nieaktualna-mutacja"],
        later=werdykty_szablonu.WERDYKTY["pass-z-mutacja"],
        on_main=later_files,
    )

    assert done.returncode == (0 if last == "DOWÓD OK" else 1), done.stdout + done.stderr
    [line, end] = done.stdout.splitlines()
    assert line.startswith(f"#5 W1 r1 | {failed[:8]} | {state}"), done.stdout
    assert end.startswith(f"{last} | pytest tests/test_inne.py::test_wazne_wola_tylko_dozwolone | wykryte"), done.stdout


@needs_ast_grep
@pytest.mark.parametrize(
    ("text", "last"),
    [
        ('"""Wołanie {} na obiekcie."""\n\n\ndef wazne(obiekt):\n    obiekt.dozwolone()\n', "DOWÓD OK | brak - proza | wyjątek 1/1"),
        ("NAZWA = '{}'\n\n\ndef wazne(obiekt):\n    obiekt.dozwolone()\n", "DOWÓD ODMOWA | brak - proza | wyjątek 0/1"),
    ],
    ids=["docstring", "napis-w-kodzie"],
)
def test_wyjatek_prozy_czyta_docstring_regula_ast_grep_z_kopii_sha_werdyktu(tmp_path: Path, text: str, last: str) -> None:
    """Ważne o zdaniu docstringu (#2069 W1 r2) nie ma strażnika poza właścicielem faktu, a napis przypisany w kodzie to
    kod: odróżnia je reguła ``PROSE`` na kopii SHA werdyktu, nie parser autora."""

    done, _ = _guard_proof(tmp_path, "--straznik", "brak - proza", failed_files={"kod/inne.py": text.format("zakazane")}, fixed_files={"kod/inne.py": text.format("dozwolone")})

    assert done.stdout.splitlines()[-1] == last, done.stdout


@needs_ast_grep
@wymaga_uv
@pytest.mark.parametrize(
    ("cases", "pins", "last"),
    [
        ("metadata:\n  przypadki:\n    - 5/W1/r1\n", True, "DOWÓD OK | zakazane-wywolanie | złapane 1/1 | FP 0 w 0 z 2 PR (0%) | main 1"),
        (
            "metadata:\n  przypadki:\n    - 1533/W1/r2\n",
            True,
            "DOWÓD ODMOWA | ast-grep zakazane-wywolanie | 5/W1/r1 nie stoi w metadata.przypadki reguły zakazane-wywolanie na HEAD: dopisz je tam, to jedyna lista przypadków reguły",
        ),
        ("metadata:\n  przypadki:\n    - 5/W1/r1\n", False, "DOWÓD ODMOWA | ast-grep zakazane-wywolanie | ast-grep dowodu (ast-grep "),
    ],
    ids=["wazne-w-przypadkach-reguly", "wazne-spoza-przypadkow-reguly", "ast-grep-spoza-srodowiska-ci"],
)
def test_straznik_regula_ast_grep_wymaga_waznego_w_przypadkach_reguly_i_jej_dowodu(tmp_path: Path, cases: str, pins: bool, last: str) -> None:
    """Przypadki reguły mają jedną listę, pole ``metadata.przypadki`` (krok ``--przypadki-regul``), więc strażnik
    ``ast-grep <id>`` przechodzi tylko z Ważnym na tej liście na HEAD i z dowodem reguły na nim, a dowód biegnie tylko
    ast-grepem w wersji z ``pyproject.toml`` drzewa, którą instaluje Required CI (tu drzewo bez ``ast-grep-cli``)."""

    tree = project() if pins else {**project(), "pyproject.toml": project()["pyproject.toml"].replace(next(pin for pin in PINS if pin.startswith("ast-grep-cli")), "ruff")}
    start = {"sgconfig.yml": SGCONFIG, "reguly-ast-grep/zakazane-wywolanie.yml": RULE + cases, **tree}
    done, _ = _proof(tmp_path, CAUGHT, {"czysty.py": CLEAN}, start=start, chosen=("--straznik", "ast-grep zakazane-wywolanie", "--z-commita", "HEAD"))

    assert done.returncode == (0 if last.startswith("DOWÓD OK") else 1), done.stdout + done.stderr
    assert done.stdout.splitlines()[-1].startswith(last), done.stdout
    if not pins:
        assert done.stdout.splitlines()[-1].endswith("(brak ast-grep): gdy PR zmienia pin ast-grep-cli, zmień go osobnym PR przed tym, a gdy nie, odśwież .venv (python3 tools/setup_worktree.py)"), done.stdout


TYPED = "from kod.typy import Obiekt\n\n\ndef wazne(obiekt: Obiekt) -> None:\n    nazwa = '{0}'\n    obiekt.{0}()\n"


@needs_ast_grep
@wymaga_uv
def test_straznik_mypy_liczy_znalezisko_w_funkcji_wokol_gdzie_z_zakresu_ast_grep(tmp_path: Path) -> None:
    """``Gdzie`` wskazuje linię, którą poprawka zmieniła (``kod/inne.py:5``), a mypy zgłasza wywołanie w linii obok:
    znalezisko liczy się, bo zakres to najmniejsza funkcja wokół ``Gdzie`` z ``places``, jak w dowodzie reguły."""

    failed_files, fixed_files = {"kod/inne.py": TYPED.format("zakazane")}, {"kod/inne.py": TYPED.format("dozwolone")}
    done, failed = _guard_proof(tmp_path, "--straznik", "mypy", failed_files=failed_files, fixed_files=fixed_files, where="Gdzie: kod/inne.py:5")

    assert done.stdout.splitlines()[-1] == "DOWÓD OK | mypy | wykryte 1/1", done.stdout
    assert done.stdout.splitlines()[0].startswith(f"#5 W1 r1 | {failed[:8]} | WYKRYTA | z FAIL: kod/inne.py | kod/inne.py:6 [attr-defined]"), done.stdout
