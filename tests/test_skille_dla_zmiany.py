"""``tools/skille_dla_zmiany.py`` wskazuje skille ``verify-*`` dla zmiany z ``pilnuje:`` w ich ``SKILL.md``.

Testy zachowania budują własne repozytorium z kopią narzędzia. Testy struktury sprawdzają skille, ``AGENTS.md`` i
``docs/agents/skille.md`` tego checkoutu: routing skilli żyje we frontmatterach, a te pliki tylko odsyłają do narzędzia.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from tests.fixtures.git_repo import commit, copy_files, git, with_imports

import kroki_skilli
import repo
import wplyw_zmiany
import zakres_runu

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SKILLS = ROOT / ".agents" / "skills"


VERDICT = "SKILLE VERIFY: "
REPO = {
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\ndescription: a\npilnuje:\n  - src/a/*\n  - tools/narzedzie.py\n---\n",
    ".agents/skills/verify-b/SKILL.md": "---\nname: verify-b\ndescription: b\npilnuje:\n  - docs/b.md\n---\n",
    ".agents/skills/verify-b/scripts/run_b.py": "import pomocnik\nprint('b')\n",
    ".agents/skills/inny/SKILL.md": "---\nname: inny\ndescription: nie verify\npilnuje:\n  - docs/b.md\n---\n",
    "src/a/b/gleboki.py": "X = 1\n",
    "src/ab.py": "Y = 1\n",
    "tools/narzedzie.py": "Z = 1\n",
    "tools/pomocnik.py": "P = 1\n",
    "docs/b.md": "b\n",
    "docs/inny.md": "inny\n",
}


# Narzędzie i silnik mutacji, który importują tabele mutacji skilli repozytorium testu.
TOOLS_FOR_CHANGE = ("tools/skille_dla_zmiany.py", "tools/lib/silnik_mutacji.py")


def _repo(root: Path, files: dict[str, str] = REPO) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    copy_files(root, with_imports(TOOLS_FOR_CHANGE))
    git(root, "init", "--quiet")
    return commit(root, "baza")


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "skille_dla_zmiany.py"), *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _skills(result: subprocess.CompletedProcess[str]) -> list[str]:
    assert result.returncode == 0, result.stdout + result.stderr
    last = result.stdout.splitlines()[-1]
    assert last.startswith(VERDICT), result.stdout
    named = last.removeprefix(VERDICT)
    return [] if named == "brak" else named.split(", ")


def _append(root: Path, name: str) -> None:
    with (root / name).open("a", encoding="utf-8") as file:
        file.write("zmiana\n")


@pytest.mark.parametrize(
    ("changed", "skills", "reason"),
    [
        ("src/a/b/gleboki.py", ["verify-a"], "verify-a: src/a/b/gleboki.py (src/a/*)"),
        ("tools/narzedzie.py", ["verify-a"], "verify-a: tools/narzedzie.py"),
        ("docs/b.md", ["verify-b"], "verify-b: docs/b.md"),
        (".agents/skills/verify-b/scripts/run_b.py", ["verify-b"], "verify-b: .agents/skills/verify-b/scripts/run_b.py (folder skilla)"),
        ("src/ab.py", [], None),
        # Import skryptu skilla spoza pilnuje: skill pilnuje swojego zachowania globami, a importów nie liczy (ADR 0020).
        ("tools/pomocnik.py", [], None),
        ("docs/inny.md", [], None),
        (".agents/skills/inny/SKILL.md", [], None),
    ],
)
def test_zmiana_wskazuje_skille_ktorych_glob_albo_folder_obejmuje_zmieniony_plik(
    tmp_path: Path, changed: str, skills: list[str], reason: str | None
) -> None:
    base = _repo(tmp_path)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert _skills(result) == skills
    assert result.stdout.splitlines()[:-1] == ([reason] if reason else [])


def test_zmiana_bez_commitu_nowy_plik_i_przeniesienie_poza_glob_wskazuja_skill(tmp_path: Path) -> None:
    base = _repo(tmp_path)

    _append(tmp_path, "docs/b.md")
    assert _skills(_run(tmp_path, base)) == ["verify-b"]
    git(tmp_path, "checkout", "--", "docs/b.md")

    (tmp_path / "src/a/nowy.py").write_text("N = 1\n", encoding="utf-8")
    assert _skills(_run(tmp_path, base)) == ["verify-a"]
    (tmp_path / "src/a/nowy.py").unlink()

    git(tmp_path, "mv", "docs/b.md", "docs/przeniesiony.md")
    commit(tmp_path, "przeniesienie")
    assert _skills(_run(tmp_path, base)) == ["verify-b"]


def test_zmiana_tylko_w_bazie_po_rozgalezieniu_nie_wskazuje_skilla(tmp_path: Path) -> None:
    _repo(tmp_path)
    trunk = git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
    git(tmp_path, "checkout", "--quiet", "-b", "praca")
    _append(tmp_path, "tools/narzedzie.py")
    commit(tmp_path, "praca")
    git(tmp_path, "checkout", "--quiet", trunk)
    _append(tmp_path, "docs/b.md")
    moved = commit(tmp_path, "baza poszła dalej")
    git(tmp_path, "checkout", "--quiet", "praca")

    assert _skills(_run(tmp_path, moved)) == ["verify-a"]


def test_skill_bez_pilnuje_albo_z_nieczytelnym_pilnuje_obowiazuje_zawsze(tmp_path: Path) -> None:
    base = _repo(
        tmp_path,
        {
            **REPO,
            ".agents/skills/verify-bez/SKILL.md": "---\nname: verify-bez\ndescription: bez klucza\n---\n",
            ".agents/skills/verify-zly/SKILL.md": "---\nname: verify-zly\npilnuje: docs/b.md\n---\n",
        },
    )

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-bez", "verify-zly"]
    assert result.stdout.splitlines()[0] == "verify-bez: .agents/skills/verify-bez/SKILL.md nie ma klucza pilnuje"


def test_wiele_plikow_jednego_skilla_skraca_powod(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    for number in range(5):
        (tmp_path / f"src/a/plik{number}.py").write_text("P = 1\n", encoding="utf-8")

    result = _run(tmp_path, base)

    assert result.stdout.splitlines() == [
        "verify-a: src/a/plik0.py (src/a/*), src/a/plik1.py (src/a/*), src/a/plik2.py (src/a/*) i 2 innych",
        f"{VERDICT}verify-a",
    ]


def test_skill_z_poleceniami_w_ci_zostaje_w_skillach_verify_a_liczy_ci_wymienia_jego_polecenia(tmp_path: Path) -> None:
    base = _repo(
        tmp_path,
        {
            **REPO,
            ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\npilnuje:\n  - src/a/*\nci: tools/narzedzie.py --wszystko\n---\n",
            ".agents/skills/verify-a/scripts/check_a_mutations.py": MUTATION_SCRIPT,
            ".agents/skills/verify-mac/SKILL.md": "---\nname: verify-mac\npilnuje:\n  - src/a/*\n---\n",
            ".agents/skills/verify-zly/SKILL.md": "---\nname: verify-zly\npilnuje:\n  - src/a/*\nci: docs/b.md\n---\n",
        },
    )
    _append(tmp_path, "src/a/b/gleboki.py")

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-a", "verify-mac", "verify-zly"]
    assert result.stdout.splitlines()[-2] == "LICZY CI: verify-a (narzedzie.py --wszystko)"


MUTATION_SCRIPT = "MUTATIONS = ()\nif __name__ == '__main__':\n    print('MUTACJE OK')\n"
AGREEING = {
    **REPO,
    # Wczytanie tabel mutacji zostawia __pycache__ w folderze skilla, a repozytorium go ignoruje.
    ".gitignore": "__pycache__/\n",
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\npilnuje:\n  - src/a/*\nci: .agents/skills/verify-a/scripts/sprawdz_a.py --wszystko\n---\n",
    ".agents/skills/verify-a/scripts/sprawdz_a.py": "print('sprawdzone')\n",
    ".agents/skills/verify-a/scripts/check_a_mutations.py": MUTATION_SCRIPT,
}


@pytest.mark.parametrize(
    ("changed", "at_night"),
    [("src/a/b/gleboki.py", []), (".agents/skills/verify-a/SKILL.md", ["check_a_mutations.py"])],
    ids=["pilnuje", "folder skilla"],
)
def test_liczy_ci_i_liczy_noc_wymieniaja_dokladnie_kroki_skilla_ktore_uruchamia_plan_pull_requestu_i_nocy(
    tmp_path: Path, changed: str, at_night: list[str]
) -> None:
    base = _repo(tmp_path, AGREEING)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    result = _run(tmp_path, base)

    assert _skills(result) == ["verify-a"]
    lines = result.stdout.splitlines()
    assert [line for line in lines if line.startswith(("LICZY CI", "LICZY NOC"))] == [
        "LICZY CI: verify-a (sprawdz_a.py --wszystko)",
        *([f"LICZY NOC: verify-a ({', '.join(at_night)})"] * bool(at_night)),
    ]


MODEL_SCRIPT = (
    "from pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools/lib'))\n"
    "from silnik_mutacji import Edit, Mutation  # noqa: E402\n\n"
    "MUTATIONS = (Mutation('m', (Edit(Path('.agents/skills/verify-a/model/M.tla'), 'X', 'Y'),), "
    "('.agents/skills/verify-a/scripts/sprawdz_a.py',)),)\n"
    "if __name__ == '__main__':\n    print('MUTACJE OK')\n"
)
WITH_MODEL = {
    **AGREEING,
    ".agents/skills/verify-a/model/M.tla": "X\n",
    ".agents/skills/verify-a/scripts/check_model_a_mutations.py": MODEL_SCRIPT,
}


@pytest.mark.parametrize(
    ("changed", "in_ci", "at_night"),
    [
        (".agents/skills/verify-a/model/M.tla", ["check_model_a_mutations.py"], ["check_a_mutations.py"]),
        (".agents/skills/verify-a/SKILL.md", [], ["check_a_mutations.py", "check_model_a_mutations.py"]),
        ("src/a/b/gleboki.py", [], []),
    ],
    ids=["model", "folder skilla bez modelu", "pilnuje"],
)
def test_skrypt_mutacji_modelu_przy_zmianie_modelu_stoi_w_liczy_ci_a_nie_w_liczy_noc(
    tmp_path: Path, changed: str, in_ci: list[str], at_night: list[str]
) -> None:
    base = _repo(tmp_path, WITH_MODEL)
    _append(tmp_path, changed)
    commit(tmp_path, "zmiana")

    lines = _run(tmp_path, base).stdout.splitlines()

    assert [line for line in lines if line.startswith(("LICZY CI", "LICZY NOC"))] == [
        f"LICZY CI: verify-a ({', '.join(['sprawdz_a.py --wszystko', *in_ci])})",
        *([f"LICZY NOC: verify-a ({', '.join(at_night)})"] * bool(at_night)),
    ]


def test_zmiana_silnika_mutacji_nie_wskazuje_skilla_choc_noc_uruchamia_jego_skrypt_mutacji(tmp_path: Path) -> None:
    base = _repo(tmp_path, AGREEING)
    with (tmp_path / "tools" / "lib" / "silnik_mutacji.py").open("a", encoding="utf-8") as file:
        file.write("# zmiana\n")
    commit(tmp_path, "zmiana silnika mutacji")

    # Linie LICZY dostaje tylko skill, który obowiązuje; skrypt nocy uruchamia zakres (tests/test_zakres_runu.py).
    assert _run(tmp_path, base).stdout.splitlines() == [f"{VERDICT}brak"]


@pytest.mark.parametrize("argv", [["nie-ma-takiej-bazy"], [""], ["--baza", ""]], ids=["nieznana", "pusta-pozycyjna", "pusta-opcja"])
def test_baza_ktorej_nie_ma_albo_pusta_mimo_istniejacej_domyslnej_daje_nieznane_skille_i_kod_bledu(tmp_path: Path, argv: list[str]) -> None:
    git(tmp_path, "update-ref", "refs/remotes/origin/main", _repo(tmp_path))

    result = _run(tmp_path, *argv)

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith(f"{VERDICT}nieznane (git merge-base: ")
    assert argv[-1] in result.stdout


def test_pomoc_opcji_baza_podaje_domyslna_galaz_bazy() -> None:
    answered = subprocess.run([sys.executable, str(TOOLS / "skille_dla_zmiany.py"), "--help"], capture_output=True, text=True, encoding="utf-8", check=True)

    options = " ".join(answered.stdout.partition("options:")[2].split())
    assert f"--baza BAZA Commit albo gałąź, od której liczy się zmiana (domyślnie {repo.BASE})." in options


def test_baza_z_opcja_baza_i_pozycyjna_daje_ten_sam_wynik_a_dwie_rozne_to_blad_uzycia(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    _append(tmp_path, "docs/b.md")
    commit(tmp_path, "zmiana")

    forms = [[base], ["--baza", base], [f"--baza={base}"], ["--baza", base, base]]
    conflict = _run(tmp_path, "--baza", base, "HEAD")

    assert [_run(tmp_path, *form).stdout for form in forms] == [_run(tmp_path, base).stdout] * len(forms)
    assert _skills(_run(tmp_path, "--baza", base)) == ["verify-b"]
    assert conflict.returncode == 2
    assert f"dwie różne bazy: --baza {base} i HEAD" in conflict.stderr


def test_kazdy_skill_verify_deklaruje_pilnuje() -> None:
    skills = sorted(SKILLS.glob("verify-*/SKILL.md"))

    without = [md.parent.name for md in skills if kroki_skilli.guarded(md) is None]

    assert skills
    assert without == [], "dopisz do frontmattera SKILL.md klucz pilnuje: z globami ścieżek, przy których zmianie skill obowiązuje"



def test_frontmatter_kazdego_skilla_jest_poprawnym_yaml() -> None:
    broken = {}
    for md in sorted(SKILLS.glob("*/SKILL.md")):
        front = md.read_text(encoding="utf-8").split("\n---\n", 1)[0].removeprefix("---\n")
        try:
            yaml.safe_load(front)
        except yaml.YAMLError as error:
            broken[md.parent.name] = str(error).splitlines()[0]

    assert broken == {}, "harness czyta frontmatter jako YAML: wartość bez cudzysłowu nie może mieć „: ”"


def test_workflow_skilla_windows_biegnie_dla_tych_samych_sciezek_co_jego_pilnuje() -> None:
    skill = SKILLS / "verify-centrum-na-windowsie"
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / f"{skill.name}.yml").read_text(encoding="utf-8"))
    triggers = workflow[True]  # YAML 1.1 czyta klucz „on” jako True

    guarded = kroki_skilli.guarded(skill / "SKILL.md")
    assert guarded is not None
    expected = sorted([*guarded, f"{skill.relative_to(ROOT).as_posix()}/**"])

    assert {event: sorted(triggers[event]["paths"]) for event in ("pull_request", "push")} == {
        "pull_request": expected,
        "push": expected,
    }, "paths workflow skilla Windows to jego pilnuje: i folder skilla: dopisz ścieżkę w obu miejscach"


@pytest.mark.parametrize("skill", ["verify-centrum-rozliczen", "verify-centrum-na-windowsie"])
def test_zmiana_atrapy_ktora_importuja_skrypty_skilla_centrum_wybiera_ten_skill(skill: str) -> None:
    """Atrapa, do której skrypty skilla Centrum dochodzą importem, trafia w jego ``pilnuje:``, bo wybór importów nie
    liczy, a workflow Windows nie biegnie w pełnym CI ``main``: zmiana kopii w ``atrapy/pliki_taty.py`` nie uruchamiała
    ani podstawy Centrum, ani Windows (przegląd #1177 r3, wcześniej #1121 i #1125). Pakiet bez kodu (``__init__.py``)
    się nie liczy. Atrapy innych skilli łapie pełne CI ``main`` (``docs/agents/skille.md``). Ścieżki skilli stoją
    literałem, żeby graf wybierał test przy zmianie ich skryptów i ``SKILL.md``."""

    repository = wplyw_zmiany.Repository.scan(ROOT)
    centrum = ROOT / ".agents" / "skills" / "verify-centrum-rozliczen"
    windows = ROOT / ".agents" / "skills" / "verify-centrum-na-windowsie"
    folder, scripts = {
        "verify-centrum-rozliczen": (centrum, (centrum / "scripts").rglob("*.py")),
        "verify-centrum-na-windowsie": (windows, (windows / "scripts").rglob("*.py")),
    }[skill]
    atrapy = {
        name
        for script in scripts
        for name in repository.imported(script.relative_to(ROOT).as_posix())
        if name.startswith("tools/lib/atrapy/") and not name.endswith("/__init__.py")
    }

    assert "tools/lib/atrapy/pliki_taty.py" in atrapy
    assert sorted(atrapy - kroki_skilli.hits(folder, atrapy).files.keys()) == [], f"dopisz te atrapy do pilnuje: {skill}"

# Zdanie, które każe uruchomić coś przed oddaniem pracy albo pushem.
BEFORE_PUSH = re.compile(r"before (handing|you hand|pushing|you push|opening|you open)|przed (pushem|oddaniem)", re.IGNORECASE)
# Argumenty kontraktu skryptu skilla (``tools/lib/skrypt_skilla.py``), które mówią, gdzie biec, a nie co sprawdzić.
PLACE = ("--run-dir", "--root")
CI_AND_LOCAL = "## What CI runs and what stays local"
# Wywołanie skryptu skilla w prozie SKILL.md: skill, ścieżka skryptu w ``scripts/`` i argumenty do końca linii.
SKILL_COMMAND = re.compile(r"\.agents/skills/([\w-]+)/scripts/([\w/]+\.py)((?:[ \t]+[^\s`\"']+)*)")


def _ci_commands(skill: Path) -> set[tuple[str, ...]]:
    """Polecenia skilla (nazwa skryptu z argumentami), które CI liczy w którymś runie: jego kroki (podstawa ``ci:``,
    skrypty mutacji) i wywołania jego skryptów w krokach CI planu; skrypt mutacji bez argumentów obejmuje każde swoje
    wywołanie."""

    steps = kroki_skilli.Katalog.skanuj(ROOT).kroki
    ci_steps = zakres_runu.KROKI.values()
    runs = {(Path(step.command[0]).name, *step.command[1:]) for step in steps if step.skill == skill}
    return runs | {run for ci_step in ci_steps for run in ci_step.wywolania(skill.name)}


def _selecting(arguments: str) -> tuple[str, ...]:
    """Argumenty wywołania bez ``PLACE`` i ich wartości."""

    words = arguments.split()
    return tuple(word for number, word in enumerate(words) if word not in PLACE and (number == 0 or words[number - 1] not in PLACE))


def _paragraphs(text: str) -> list[str]:
    """Akapity prozy, każdy z blokiem kodu, który stoi zaraz pod nim."""

    found: list[str] = []
    for chunk in re.split(r"\n\s*\n", text):
        if chunk.lstrip().startswith("```") and found:
            found[-1] += "\n" + chunk
        else:
            found.append(chunk)
    return found


def _mandates(text: str, commands: set[tuple[str, ...]]) -> list[str]:
    """Akapity, które każą przed pushem uruchomić lokalnie polecenie liczone przez CI."""

    found = []
    for paragraph in _paragraphs(text):
        if not BEFORE_PUSH.search(paragraph):
            continue
        named = {(Path(script).name, *_selecting(arguments)) for _, script, arguments in SKILL_COMMAND.findall(paragraph.replace("\\", "/"))}
        # Wywołanie bez części argumentów polecenia CI to zwykle jego domyślny przebieg (``all``), więc też się liczy.
        if any(command[: len(ci)] == ci or ci[: len(command)] == command for command in named for ci in commands):
            found.append(paragraph.splitlines()[0])
    return found


def test_skill_nie_kaze_uruchamiac_przed_pushem_tego_co_liczy_ci() -> None:
    """Akapit ze zdaniem „before handing/pushing…” albo „przed pushem” nie wymienia polecenia, które liczy CI.

    Polecenie liczy się także w bloku kodu pod akapitem, z ``--run-dir``/``--root`` albo bez części argumentów.
    Granica: nakaz innymi słowami („after every change”, „always run”, „it must end with”) łapie tylko przegląd.
    """

    commands = {run for md in SKILLS.glob("*/SKILL.md") for run in _ci_commands(md.parent)}

    found = {md.parent.name: _mandates(md.read_text(encoding="utf-8"), commands) for md in sorted(SKILLS.glob("*/SKILL.md"))}

    assert {("run_verification.py", "--variant", "all"), ("run_centrum_verification.py", "--feature", "all")} <= commands
    assert {skill: lines for skill, lines in found.items() if lines} == {}, (
        "polecenie, które liczy CI, skill uruchamia lokalnie tylko do odtworzenia czerwonego kroku CI albo przy pracy nad jedną funkcją"
    )


def test_skill_z_poleceniami_w_ci_mowi_co_liczy_ci_a_co_zostaje_lokalnie() -> None:
    """Granica: czy sekcja trafnie nazywa osąd, który zostaje lokalnie, łapie tylko przegląd."""

    skills = [md for md in sorted(SKILLS.glob("verify-*/SKILL.md")) if _ci_commands(md.parent)]

    without = [md.parent.name for md in skills if CI_AND_LOCAL not in md.read_text(encoding="utf-8").splitlines()]

    assert {"verify-centrum-rozliczen", "verify-aktualizacja-narzedzia"} <= {md.parent.name for md in skills}
    assert without == [], f"dopisz sekcję {CI_AND_LOCAL!r}: które polecenia liczy CI, a co z workflow zostaje lokalnie (osąd, Mac)"


def test_agents_md_nie_wymienia_skilli_verify() -> None:
    """``AGENTS.md`` i pliki ``docs/agents/``, do których odsyła przed pushem, nie wymieniają skilli ``verify-*``."""

    documents = (ROOT / "AGENTS.md", ROOT / "docs" / "agents" / "pr-i-ci.md", ROOT / "docs" / "agents" / "skille.md")
    agents = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    named = [md.parent.name for md in sorted(SKILLS.glob("verify-*/SKILL.md")) if md.parent.name in agents]

    assert named == [], "routing skilli verify-* żyje w ich pilnuje:, a AGENTS.md odsyła do tools/skille_dla_zmiany.py"


NOT_PROSE = re.compile(r"\s*(?:#+\s|\||```)")
CODE_SPAN = re.compile(r"`[^`]*`")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
BACKGROUND = re.compile(r"background", re.IGNORECASE)
SAME_TURN = "same turn"


def _prose_paragraphs(text: str) -> Iterator[list[str]]:
    paragraph: list[str] = []
    fenced = False
    front_matter = text.startswith("---\n")
    for number, line in enumerate(text.splitlines(), start=1):
        if front_matter:
            front_matter = number == 1 or line != "---"
            continue
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and line.strip() and not NOT_PROSE.match(line):
            paragraph.append(line)
            continue
        if paragraph:
            yield paragraph
        paragraph = []
    if paragraph:
        yield paragraph


def _background_without_waiting(text: str) -> list[str]:
    sentences = (
        sentence
        for paragraph in _prose_paragraphs(text)
        for sentence in SENTENCE_BREAK.split(CODE_SPAN.sub("", " ".join(line.strip() for line in paragraph)))
    )
    return [sentence for sentence in sentences if BACKGROUND.search(sentence) and SAME_TURN not in sentence]


def test_skill_kaze_czekac_na_polecenie_w_tle_w_tej_samej_turze() -> None:
    """Zdanie ``SKILL.md`` o tle każe czekać na koniec polecenia w tej samej turze (``AGENTS.md``, hook ``praca_w_tle.py``).

    Granica: zdanie o tle w kodzie, w tabeli, w pliku ``features/`` skilla i inne słowa niż „background” łapie tylko
    przegląd.
    """

    found = {
        str(md.relative_to(ROOT)): sentences
        for md in sorted(SKILLS.glob("*/SKILL.md"))
        if (sentences := _background_without_waiting(md.read_text(encoding="utf-8")))
    }

    assert found == {}, (
        "Polecenie w tle: każ w tym samym zdaniu czekać na jego koniec „in the same turn” (AGENTS.md), "
        "a nie oddać turę i czekać na powiadomienie; polecenie do 600 s uruchom na pierwszym planie."
    )


def test_sprawdzenie_tla_pomija_kod_a_wskazuje_tlo_bez_czekania_w_tej_samej_turze() -> None:
    document = "\n".join(
        [
            "---",
            "description: Runs in the background.",
            "---",
            "Start it as a background command",
            "and wait for the notification. Then read its last line.",
            "Start it in the background and wait for its end",
            "in the same turn.",
            "The queue calls `send_in_background` and `run_in_background`.",
            "| table | in the background |",
            "```",
            "run it in the background",
            "```",
            "Run `x` in the background, then read it.",
        ]
    )

    assert _background_without_waiting(document) == [
        "Start it as a background command and wait for the notification.",
        "Run  in the background, then read it.",
    ]
