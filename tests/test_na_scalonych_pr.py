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
from tests.fixtures.git_repo import commit, copy_files, git, mutation_repository, with_imports

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
