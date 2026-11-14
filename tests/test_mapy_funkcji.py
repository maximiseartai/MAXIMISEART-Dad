"""Mapa funkcji skilla ``verify-*`` (``features/``) zgadza się z jego kodem i ``SKILL.md``.

Mapa to pamięć skilla: agent wybiera z niej funkcję do sprawdzenia, a harness skilla prowadzi funkcje z krotki
``FEATURES`` w swoich skryptach (napisów albo rejestru ``Feature("nazwa", …)``) i z modułów pakietu
``scripts/<pakiet>/``. Rozjazd mapy z kodem czerwieni CI, a nie dopiero przebieg skilla u agenta. Plik funkcji skilla z funkcjami w kodzie odpowiada funkcji z kodu
w obie strony, więc ``features/README.md`` takiego skilla nie listuje plików: lista bez sprawdzenia kompletności kłamie od
pierwszej nowej funkcji. Skill bez funkcji w kodzie listuje je w README, a każdy plik funkcji ma tam link.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import re
import subprocess
import sys
from types import ModuleType
from typing import Final

import pytest

from tests.fixtures.znane_luki import assert_znane_luki, modul, ruff, wymaga_ruff, zapisz

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
MAPS = sorted(path.parent for path in SKILLS.glob("*/features"))
PACKAGE_HELPERS = frozenset({"__init__", "common", "teksty", "waiting"})
LINK = re.compile(r"\]\(\./([^)]+\.md)\)")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
DRIVING = re.compile(r"## Driving it with \S.*")


@dataclass(frozen=True)
class Feature:
    name: str
    source: str


def _feature_files(skill: Path) -> list[Path]:
    return sorted(path for path in (skill / "features").glob("*.md") if path.name != "README.md")


def _feature_list_values(tree: ast.Module) -> list[tuple[str, ast.expr]]:
    return [
        (target.id, node.value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and node.value is not None
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id == "FEATURES"
    ]


def _names(value: ast.expr) -> list[str]:
    """Nazwy funkcji z krotki napisów albo z rejestru, którego każdy wpis to wywołanie z nazwą jako pierwszym argumentem."""

    if isinstance(value, ast.Tuple) and value.elts and all(isinstance(entry, ast.Call) for entry in value.elts):
        return [ast.literal_eval(entry.args[0]) for entry in value.elts if isinstance(entry, ast.Call) and entry.args]
    names = ast.literal_eval(value)
    assert isinstance(names, tuple)
    return list(names)


def _code_features(skill: Path) -> list[Feature]:
    features = []
    for path in sorted((skill / "scripts").rglob("*.py")):
        source = path.relative_to(skill).as_posix()
        for name, value in _feature_list_values(ast.parse(path.read_text(encoding="utf-8"))):
            try:
                features += [Feature(feature, f"{name} w {source}") for feature in _names(value)]
            except (ValueError, AssertionError):
                pytest.fail(
                    f"{name} w {source}:{value.lineno} nie jest krotką napisów ani rejestrem Feature(\"nazwa\", …): "
                    "zapisz funkcje literałem"
                )
    return features


def _package_modules(skill: Path) -> list[Feature]:
    return [
        Feature(module.stem.replace("_", "-"), module.relative_to(skill).as_posix())
        for package in sorted(path.parent for path in (skill / "scripts").glob("*/__init__.py"))
        for module in sorted(package.glob("*.py"))
        if module.stem not in PACKAGE_HELPERS
    ]


def _readme(skill: Path) -> str:
    readme = skill / "features" / "README.md"
    if not readme.is_file():
        pytest.fail(f"{skill.name}/features/ nie ma README.md: dopisz konwencje mapy i ## Feature entry contract")
    return HTML_COMMENT.sub("", readme.read_text(encoding="utf-8"))


def _linked(skill: Path) -> list[str]:
    return LINK.findall(_readme(skill))


@pytest.mark.parametrize("skill", MAPS, ids=lambda skill: skill.name)
def test_mapa_skilla_ma_readme_bez_linkow_do_brakujacych_plikow(skill: Path) -> None:
    files = [path.name for path in _feature_files(skill)]

    problems = [
        f"{skill.name}/features/README.md linkuje {name}, którego nie ma: dopisz plik funkcji albo usuń link"
        for name in _linked(skill)
        if name not in files
    ]

    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("skill", MAPS, ids=lambda skill: skill.name)
def test_kazdy_plik_funkcji_ma_naglowki_h2_z_szablonu(skill: Path) -> None:
    headings = {
        path.name: [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
        for path in _feature_files(skill)
    }
    driving = {found[2] for found in headings.values() if len(found) == 4}

    problems = [
        f"{skill.name}/features/{name} ma nagłówki H2 {found}: zostaw dokładnie `## Sub-features`, "
        "`## How to get to it (user POV)`, `## Driving it with …` (jak w pozostałych plikach skilla) i `## Gotchas`, "
        "w tej kolejności (## Feature entry contract w features/README.md)"
        for name, found in headings.items()
        if len(found) != 4
        or found[:2] != ["## Sub-features", "## How to get to it (user POV)"]
        or not DRIVING.fullmatch(found[2])
        or found[3] != "## Gotchas"
    ]

    assert problems == [], "\n".join(problems)
    assert len(driving) <= 1, (
        f"pliki funkcji {skill.name} prowadzą funkcje różnymi nagłówkami {sorted(driving)}: ujednolić `## Driving it with …`"
    )


CODE_MAPS = [skill for skill in MAPS if _code_features(skill) or _package_modules(skill)]


@pytest.mark.parametrize("skill", [skill for skill in MAPS if skill not in CODE_MAPS], ids=lambda skill: skill.name)
def test_mapa_skilla_bez_funkcji_w_kodzie_linkuje_kazdy_plik_funkcji(skill: Path) -> None:
    problems = [
        f"{skill.name}/features/{path.name} nie ma linku w features/README.md: "
        f"dopisz w sekcji ## Features linię `- [Nazwa funkcji](./{path.name}) covers …`"
        for path in _feature_files(skill)
        if path.name not in _linked(skill)
    ]

    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("skill", CODE_MAPS, ids=lambda skill: skill.name)
def test_mapa_skilla_z_funkcjami_w_kodzie_nie_listuje_plikow_funkcji(skill: Path) -> None:
    files = {path.name for path in _feature_files(skill)}

    listing = [line for line in _readme(skill).splitlines() if line.rstrip() == "## Features"] + [
        f"link do {name}" for name in _linked(skill) if name in files
    ]

    assert listing == [], (
        f"{skill.name}/features/README.md listuje funkcje ({', '.join(listing)}): usuń listę, bo plik funkcji i funkcję "
        "w kodzie pilnują testy w obie strony, a lista bez takiego testu kłamie od pierwszej nowej funkcji"
    )


@pytest.mark.parametrize("skill", CODE_MAPS, ids=lambda skill: skill.name)
def test_kazda_funkcja_z_kodu_skilla_ma_plik_w_mapie_i_wpis_w_skill_md(skill: Path) -> None:
    files = {path.stem for path in _feature_files(skill)}
    skill_md = (skill / "SKILL.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"--feature ([a-z0-9-]+)", skill_md))

    without_file = [
        f"funkcja `{feature.name}` z {feature.source} nie ma pliku {skill.name}/features/{feature.name}.md: "
        "dopisz go według ## Feature entry contract z features/README.md"
        for feature in [*_code_features(skill), *_package_modules(skill)]
        if feature.name not in files
    ]
    not_in_skill_md = [
        f"funkcja `{feature.name}` z {feature.source} nie pada w {skill.name}/SKILL.md: "
        f"dopisz `--feature {feature.name}` tam, gdzie SKILL.md wymienia funkcje"
        for feature in _code_features(skill)
        if feature.name not in listed
    ]

    assert without_file == [], "\n".join(without_file)
    assert not_in_skill_md == [], "\n".join(not_in_skill_md)


@pytest.mark.parametrize("skill", CODE_MAPS, ids=lambda skill: skill.name)
def test_kazdy_plik_funkcji_i_modul_pakietu_ma_funkcje_w_kodzie_skilla(skill: Path) -> None:
    driven = {feature.name for feature in _code_features(skill)}
    lists = " albo ".join(sorted({feature.source for feature in _code_features(skill)}))

    problems = [
        f"{skill.name}/features/{path.name} nie ma funkcji w kodzie: dopisz `{path.stem}` do {lists} "
        "i jej moduł albo usuń plik"
        for path in _feature_files(skill)
        if path.stem not in driven
    ] + [
        f"moduł {skill.name}/{module.source} nie jest funkcją harnessu: dopisz `{module.name}` do {lists} "
        "albo przenieś wspólny kod do common.py (teksty ekranu do teksty.py, czekanie do waiting.py)"
        for module in _package_modules(skill)
        if module.name not in driven
    ]

    assert lists, f"{skill.name} ma pakiet funkcji bez krotki FEATURES w scripts/"
    assert problems == [], "\n".join(problems)


CENTRUM = SKILLS / "verify-centrum-rozliczen"
SUB_FEATURES = ROOT / ".agents/skills/verify-centrum-rozliczen/scripts/sub_features.py"


def _sub_features(feature: str) -> str:
    done = subprocess.run(
        [sys.executable, str(SUB_FEATURES), "--feature", feature], capture_output=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")
    return done.stdout.decode("utf-8")


def test_podfunkcje_mapy_centrum_sa_wynikiem_polecenia_z_kodu_napedu() -> None:
    """Plik funkcji, który nazywa polecenie ``sub_features.py`` swojej funkcji, ma jego wynik jako całą sekcję
    ``## Sub-features``, tuż przed ``## How to get to it (user POV)``."""

    printed = [path for path in _feature_files(CENTRUM) if f"sub_features.py --feature {path.stem}`" in path.read_text(encoding="utf-8")]

    problems = [
        f"verify-centrum-rozliczen/features/{path.name}: sekcja ## Sub-features nie jest wynikiem kodu napędu; zastąp ją "
        f"wynikiem `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/sub_features.py --feature {path.stem}` "
        "(Windows: `py -3`)"
        for path in printed
        if f"\n{_sub_features(path.stem)}\n## How to get to it (user POV)\n" not in path.read_text(encoding="utf-8")
    ]

    assert printed, "żaden plik mapy verify-centrum-rozliczen nie nazywa polecenia sub_features.py swojej funkcji"
    assert problems == [], "\n".join(problems)


@pytest.fixture
def polecenie(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SUB_FEATURES.parent))
    spec = importlib.util.spec_from_file_location("sub_features", SUB_FEATURES)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NAPED: Final = """\
from drive.common import Run

SHOW_ALL = "Pokaż wszystkie"


def drive(run: Run, page: object) -> None:
    feature = "sonda"
    run.step(feature, "sonda-krok")
    run.check(True, "pierwszy")
    {wstawka}
"""

# Postać → wstawka w ciele drive() napędu NAPED; linia, którą odmowa wskazuje, ma komentarz `# tu`.
ODMOWY: Final = {
    "check: komunikat nazwany": 'run.check(True, message="x")  # tu',
    "check: oba argumenty nazwane": 'run.check(condition=True, message="x")  # tu',
    "check: *args": 'run.check(*(True, "x"))  # tu',
    "check: *args przed komunikatem": 'run.check(*[True], "x")  # tu',
    "check: **kwargs": 'run.check(True, **{"message": "x"})  # tu',
    "check: **kwargs po komunikacie": 'run.check(True, "x", **{})  # tu',
    "check: jeden argument": "run.check(True)  # tu",
    "check: trzy argumenty": 'run.check(True, "x", 1)  # tu',
    "check: komunikat zmienną lokalną": "run.check(True, feature)  # tu",
    "check: komunikat konkatenacją": 'run.check(True, "x" + "y")  # tu',
    "check: komunikat wywołaniem": 'run.check(True, "x {}".format(1))  # tu',
    "check: komunikat warunkiem": 'run.check(True, "x" if True else "y")  # tu',
    "check: w funkcji zagnieżdżonej": 'def _pomocnik() -> None:\n        run.check(True, "x")  # tu',
    "check: w lambdzie": '_pomocnik = lambda: run.check(True, "x")  # tu',
    "check: w ciele klasy": 'class _Pomocnik:\n        run.check(True, "x")  # tu',
    "check: jako wartość": 'sprawdz = run.check  # tu',
    "step: nazwa nazwana": 'run.step(feature, name="x")  # tu',
    "step: nazwa zmienną": "run.step(feature, feature)  # tu",
    "step: *args": 'run.step(*(feature, "x"))  # tu',
    "check: na aliasie run": 'plansza = run\n    plansza.check(True, "x")  # tu',
    "step: na aliasie run": 'plansza = run\n    plansza.step(feature, "x")  # tu',
    "check: na celu pętli": 'for r in (run,):\n        r.check(True, "x")  # tu',
    "check: na wyniku walrusa": '(r := run).check(True, "x")  # tu',
    "check: na parametrze lambdy": '(lambda r: r.check(True, "x"))(run)  # tu',
    "check: przez klasę Run": 'Run.check(run, True, "x")  # tu',
    "check: przez klasę obiektu": 'run.__class__.check(run, True, "x")  # tu',
    "check: pętla po nazwie z parametru": 'for _ in feature:\n        run.check(True, "x")  # tu',
    "check: pętla po range": 'for _ in range(2):\n        run.check(True, "x")  # tu',
    "check: pętla po pustej krotce": 'for _ in ():\n        run.check(True, "x")  # tu',
    "check: pętla po literale z gwiazdką": 'for _ in (*feature,):\n        run.check(True, "x")  # tu',
    "check: pętla nad literałem z break": 'for _ in (1, 2):\n        run.check(True, "x")  # tu\n        break',
    "check: pętla nad literałem z continue": 'for _ in (1, 2):\n        run.check(True, "x")  # tu\n        continue',
    "check: pętla nad literałem z else": 'for _ in (1, 2):\n        run.check(True, "x")  # tu\n    else:\n        pass',
    "check: pętla po nazwie związanej drugi raz": 'lista = (1, 2)\n    lista = (3,)\n    for _ in lista:\n        run.check(True, "x")  # tu',
    "check: pętla po nazwie z innego bloku": 'if feature:\n        lista = (1, 2)\n    for _ in lista:\n        run.check(True, "x")  # tu',
    "check: pętla po nazwie przypisanej po pętli": 'for _ in lista:\n        run.check(True, "x")  # tu\n    lista = (1, 2)',
    "check: pętla po nazwie listy (W2 r1)": 'lista = ["a", "b"]\n    for _ in lista:\n        run.check(True, "x")  # tu',
    "check: dalszy człon łańcucha porównań (W1 r1)": '_ = 1 > 2 > run.check(True, "x")  # tu',
    "check: cel przypisania": 'd = {}\n    d[run.check(True, "x")] = 1  # tu',
    "check: adnotacja zmiennej lokalnej": 'x: run.check(True, "x") = 1  # tu',
    "check: gałąź wyrażenia warunkowego": '_ = run.check(True, "x") if feature else None  # tu',
    "check: dwa w jednej instrukcji": '_ = (run.check(True, "a"), run.check(True, "b"))  # tu',
    "check: pętla po nazwie pustej krotki": 'lista = ()\n    for _ in lista:\n        run.check(True, "x")  # tu',
    "check: pętla while": 'while feature:\n        run.check(True, "x")  # tu\n        feature = ""',
    "check: wyrażenie listowe nad literałem": '[run.check(True, "x") for _ in (1, 2)]  # tu',
    "check: gałąź if": 'if feature:\n        run.check(True, "x")  # tu',
    "check: gałąź else": 'if feature:\n        pass\n    else:\n        run.check(True, "x")  # tu',
    "check: wyrażenie warunkowe": 'run.check(True, "x") if feature else None  # tu',
    "check: drugi argument or": 'feature or run.check(True, "x")  # tu',
    "check: except": 'try:\n        pass\n    except ValueError:\n        run.check(True, "x")  # tu',
    "check: ciało try z except": 'try:\n        run.check(True, "x")  # tu\n    except ValueError:\n        pass',
    "check: else po try": 'try:\n        pass\n    except ValueError:\n        pass\n    else:\n        run.check(True, "x")  # tu',
    "check: przypadek match": 'match feature:\n        case _:\n            run.check(True, "x")  # tu',
    "check: komunikat assert": 'assert feature, run.check(True, "x")  # tu',
    "check: po return drive()": 'if feature == "x":\n        return\n    run.check(True, "x")  # tu',
}
# Postać → cały napęd, gdy odmowa dotyczy miejsca poza wstawką.
ODMOWY_MODULU: Final = {
    "check przed pierwszym step": NAPED.replace('    run.step(feature, "sonda-krok")\n', '    run.check(True, "x")  # tu\n    run.step(feature, "sonda-krok")\n'),
    "check w pomocniku modułu": NAPED + '\n\ndef _pomocnik(run: Run) -> None:\n    run.check(True, "x")  # tu\n',
    "check na parametrze pomocnika r: Run": NAPED + '\n\ndef _pomocnik(r: Run) -> None:\n    r.check(True, "x")  # tu\n',
    'check na parametrze pomocnika r: "Run"': NAPED + '\n\ndef _pomocnik(r: "Run") -> None:\n    r.check(True, "x")  # tu\n',
    "check na parametrze pomocnika r: Run | None": NAPED
    + '\n\ndef _pomocnik(r: Run | None) -> None:\n    assert r\n    r.check(True, "x")  # tu\n',
    "check w metodzie podklasy Run": NAPED + '\n\nclass _Run(Run):\n    def sprawdz(self) -> None:\n        self.check(True, "x")  # tu\n',
    "drive bez parametru run": NAPED.replace(
        "def drive(run: Run, page: object) -> None:", "def drive(r: Run, page: object) -> None:  # tu"
    ),
    "moduł bez drive": NAPED.replace("def drive(", "def napedz(").replace(
        "from drive.common import Run", "from drive.common import Run  # tu"
    ),
    "drive bez run.step": NAPED.replace(
        "def drive(run: Run, page: object) -> None:", "def drive(run: Run, page: object) -> None:  # tu"
    ).replace('    run.step(feature, "sonda-krok")\n    run.check(True, "pierwszy")\n', ""),
}

# Pomocnik modułu z run.check, którego wywołanie wstawka stawia w ciele drive() napędu NAPED.
POMOCNIK: Final = '\n\ndef _pomocnik(run: Run) -> None:\n    run.check(True, "z pomocnika")\n'
# Postać wywołania pomocnika z krokami albo sprawdzeniami → wstawka w drive(); polecenie odmawia, bo nie wie, czy, ile
# razy i w jakiej kolejności krok pomocnika biegnie (mechanizm: czyta tylko wywołania, z których każde jest całą
# instrukcją albo całą prawą stroną przypisania do nazw w ciele drive() albo w ciele try z samym finally, które nie
# zwraca). Linia odmowy ma komentarz `# tu`.
ODMOWY_POMOCNIKA: Final = {
    "cel pętli for (W1 r1)": "d = {}\n    for d[_pomocnik(run)] in range(2):  # tu\n        pass",
    "dalszy człon łańcucha porównań (W1 r1)": "0 > 1 > _pomocnik(run)  # tu",
    "adnotacja zmiennej lokalnej (W1 r1)": "x: _pomocnik(run) = 1  # tu",
    "wartość przypisania z adnotacją": "x: object = _pomocnik(run)  # tu",
    "cel przypisania biegnie po wartości (W2 r1)": 'd = {}\n    d[run.check(True, "w celu")] = _pomocnik(run)  # tu',
    "przypisanie rozszerzone": "x = 0\n    x += _pomocnik(run)  # tu",
    "argument innego wywołania": "print(_pomocnik(run))  # tu",
    "argument sprawdzenia": 'run.check(_pomocnik(run), "po")  # tu',
    "run.check w argumencie pomocnika": '_pomocnik(run, run.check(True, "w argumencie"))  # tu',
    "ciało with": "with open(__file__, encoding='utf-8'):\n        _pomocnik(run)  # tu",
    "ciało try": "try:\n        _pomocnik(run)  # tu\n    except ValueError:\n        pass",
    "finally": "try:\n        pass\n    finally:\n        _pomocnik(run)  # tu",
    "iterowane pętli for": "for _ in [_pomocnik(run)]:  # tu\n        pass",
    "warunek if": "if _pomocnik(run):  # tu\n        pass",
    "pierwszy argument or": "_pomocnik(run) or None  # tu",
    "przedmiot match": "match _pomocnik(run):  # tu\n        case _:\n            pass",
    "warunek assert": "assert _pomocnik(run) is None  # tu",
    "po return drive()": 'if feature == "sonda":\n        return\n    _pomocnik(run)  # tu',
    "pętla for": "for _ in range(2):\n        _pomocnik(run)  # tu",
    "pętla while": "while feature:\n        _pomocnik(run)  # tu\n        break",
    "wyrażenie listowe": "[_pomocnik(run) for _ in range(2)]  # tu",
    "gałąź if": "if feature:\n        _pomocnik(run)  # tu",
    "gałąź else": "if feature:\n        pass\n    else:\n        _pomocnik(run)  # tu",
    "wyrażenie warunkowe": "_pomocnik(run) if feature else None  # tu",
    "drugi argument or": "feature or _pomocnik(run)  # tu",
    "except": "try:\n        pass\n    except ValueError:\n        _pomocnik(run)  # tu",
    "else po try": "try:\n        pass\n    except ValueError:\n        pass\n    else:\n        _pomocnik(run)  # tu",
    "przypadek match": "match feature:\n        case _:\n            _pomocnik(run)  # tu",
    "komunikat assert": "assert feature, _pomocnik(run)  # tu",
    "try z else": "try:\n        _pomocnik(run)  # tu\n    except ValueError:\n        pass\n    else:\n        pass",
    "try zagnieżdżony w try z finally": "try:\n        try:\n            _pomocnik(run)  # tu\n        finally:\n"
    "            pass\n    finally:\n        pass",
    "try z finally, które zwraca": "try:\n        _pomocnik(run)  # tu\n    finally:\n        return",
    "try z finally, które zwraca pod if": "try:\n        _pomocnik(run)  # tu\n    finally:\n        if feature:\n            return",
    "drugie wywołanie w pętli": "_pomocnik(run)\n    for _ in range(2):\n        _pomocnik(run)  # tu",
    "lambda w drive()": "(lambda: _pomocnik(run))()  # tu",
    "funkcja w drive()": "def _w_drive() -> None:\n        _pomocnik(run)  # tu\n\n    _w_drive()",
    "inna nazwa": "inny = _pomocnik  # tu\n    inny(run)",
    "run nie pierwszy": "_pomocnik(*[run])  # tu",
    "run nazwany": "_pomocnik(run=run)  # tu",
    "inny pierwszy argument": "_pomocnik(feature)  # tu",
    "przekazany jako argument": "print(run, _pomocnik)  # tu",
}
# Postać pomocnika → cały napęd, gdy odmowa dotyczy miejsca poza wstawką.
ODMOWY_POMOCNIKA_MODULU: Final = {
    "pomocnik pomocnika": NAPED.replace("{wstawka}", "_zewnetrzny(run)")
    + POMOCNIK
    + "\n\ndef _zewnetrzny(run: Run) -> None:\n    _pomocnik(run)  # tu\n",
    "pomocnik z dekoratorem": NAPED.replace("{wstawka}", "_pomocnik(run)")
    + '\n\n@staticmethod\ndef _pomocnik(run: Run) -> None:  # tu\n    run.check(True, "z pomocnika")\n',
    "pomocnik z yield": NAPED.replace("{wstawka}", "next(_pomocnik(run))")
    + '\n\ndef _pomocnik(run: Run) -> object:  # tu\n    run.check(True, "z pomocnika")\n    yield\n',
    "wywołanie na poziomie modułu": NAPED.replace("{wstawka}", "pass") + POMOCNIK + "\n\n_pomocnik(run)  # tu\n",
    "run nie pierwszym parametrem": NAPED.replace("{wstawka}", "_pomocnik(run, page)")
    + '\n\ndef _pomocnik(page: object, run: Run) -> None:\n    run.check(True, "z pomocnika")  # tu\n',
    "nazwa pomocnika związana drugi raz": NAPED.replace("{wstawka}", "_pomocnik(run)")
    + '\n\ndef _pomocnik(run: Run) -> None:\n    run.check(True, "z pomocnika")  # tu\n\n\n_pomocnik = print\n',
    "dwóch pomocników w przypisaniu (W2 r1)": NAPED.replace("{wstawka}", "d = {}\n    d[_a(run)] = _b(run)  # tu")
    + '\n\ndef _a(run: Run) -> int:\n    run.step("sonda", "krok-a")\n    return 0\n'
    + '\n\ndef _b(run: Run) -> int:\n    run.step("sonda", "krok-b")\n    return 0\n',
    "check pomocnika przed pierwszym step": NAPED.replace(
        '    run.step(feature, "sonda-krok")\n', '    _pomocnik(run)\n    run.step(feature, "sonda-krok")\n'
    ).replace("{wstawka}", "pass")
    + '\n\ndef _pomocnik(run: Run) -> None:\n    run.check(True, "z pomocnika")  # tu\n',
}


def _odmowy() -> dict[str, str]:
    return {
        **{opis: NAPED.format(wstawka=wstawka) for opis, wstawka in ODMOWY.items()},
        **{opis: zrodlo.replace("{wstawka}", "pass") for opis, zrodlo in ODMOWY_MODULU.items()},
        **{f"pomocnik: {opis}": NAPED.format(wstawka=wstawka) + POMOCNIK for opis, wstawka in ODMOWY_POMOCNIKA.items()},
        **{f"pomocnik: {opis}": zrodlo for opis, zrodlo in ODMOWY_POMOCNIKA_MODULU.items()},
    }


@pytest.mark.parametrize("opis", list(_odmowy()))
def test_polecenie_podfunkcji_odmawia_postaci_run_ktorej_nie_czyta_z_plikiem_i_linia(polecenie: ModuleType, opis: str) -> None:
    """Postać spoza tej jednej, którą polecenie czyta (``run.step``/``run.check`` z dwoma argumentami pozycyjnymi w ciele
    ``drive(run, page)`` i pomocnika, którego drive() woła raz jako ``pomocnik(run, …)`` poza pętlą i warunkiem),
    czerwieni je zdaniem z plikiem i linią, także atrybut ``.check`` na obiekcie innym niż ``run``, zamiast zgubić
    komunikat, który napęd drukuje w ``drive.txt``, albo wydrukować go raz tam, gdzie napęd drukuje go inaczej (W1 r1
    i r2, D1 i D2 r3 #1690)."""

    zrodlo = _odmowy()[opis]
    linia = next(numer for numer, tekst in enumerate(zrodlo.splitlines(), start=1) if "# tu" in tekst)

    with pytest.raises(polecenie.Unreadable) as odmowa:
        polecenie.sub_features(zrodlo, "sonda.py")

    assert str(odmowa.value).startswith(f"sonda.py:{linia}: "), str(odmowa.value)


def test_polecenie_podfunkcji_czyta_komunikaty_ze_stalych_modulu_jak_naped(polecenie: ModuleType) -> None:
    """Komunikat to literał, stała modułu (także z adnotacją) albo f-string; pole f-stringu spoza stałych, w tym
    nazwa, którą moduł wiąże drugi raz (przypisaniem, importem, parametrem, ``def``, ``except ... as``, wzorcem
    ``match``, parametrem typu), jest wielokropkiem."""

    zrodlo = NAPED.format(
        wstawka="\n    ".join(
            [
                "run.check(True, SHOW_ALL)",
                "run.check(True, ADNOTOWANA)",
                'run.check(True, f"{SHOW_ALL} i {feature}")',
                'run.check(True, f"{DWA_RAZY}")',
                'LOKALNA = "lokalna"',
                'run.check(True, f"{LOKALNA} {IMPORT} {PARAMETR} {FUNKCJA} {WYJATEK}")',
                'run.check(True, f"{WZORZEC} {GWIAZDKA} {RESZTA} {TYP} {SPEC} {KROTKA}")',
                'run.step(feature, "sonda-drugi")',
            ]
        )
    ) + "".join(
        f"\n{wiersz}\n"
        for wiersz in [
            'ADNOTOWANA: str = "z adnotacją"',
            'DWA_RAZY = "a"\nDWA_RAZY = "b"',
            'LOKALNA = "moduł"',
            'IMPORT = "moduł"\nfrom os import sep as IMPORT',
            'PARAMETR = "moduł"\n\n\ndef _pomocnik(PARAMETR: str) -> None:\n    pass',
            'FUNKCJA = "moduł"\n\n\ndef FUNKCJA() -> None:\n    pass',
            'WYJATEK = "moduł"\ntry:\n    pass\nexcept ValueError as WYJATEK:\n    pass',
            'WZORZEC = "moduł"\nmatch 1:\n    case WZORZEC:\n        pass',
            'GWIAZDKA = "moduł"\nmatch []:\n    case [*GWIAZDKA]:\n        pass',
            'RESZTA = "moduł"\nmatch {}:\n    case {**RESZTA}:\n        pass',
            'TYP = "moduł"\n\n\ndef _typ[TYP]() -> None:\n    pass',
            'SPEC = "moduł"\n\n\ndef _spec[**SPEC]() -> None:\n    pass',
            'KROTKA = "moduł"\n\n\ndef _krotka[*KROTKA]() -> None:\n    pass',
        ]
    )

    assert polecenie.sub_features(zrodlo, "sonda.py") == [
        (
            "sonda-krok",
            [
                "pierwszy",
                "Pokaż wszystkie",
                "z adnotacją",
                "Pokaż wszystkie i …",
                "…",
                "… … … … …",
                "… … … … … …",
            ],
        ),
        ("sonda-drugi", []),
    ]


# Pole f-stringu komunikatu → jak stoi w sekcji: stała modułu bez konwersji i formatu daje swoją wartość, każde inne
# pole wielokropek, bez wyrażenia i formatu, bo wartość zna dopiero przebieg napędu (D2 #1708).
POLA: Final = {
    "pole proste": ('f"każda z {len(feature)} reguł"', "każda z … reguł"),
    "pole z formatem": ('f"po {len(feature):>3} s"', "po … s"),
    "pole z konwersją": ('f"adres {feature!r}"', "adres …"),
    "pole zagnieżdżone": ('f"szerokość {feature:{len(feature)}} i {f\'{feature}\'}"', "szerokość … i …"),
    "podwójne klamry": ('f"{{wiersz}} {feature} }}"', "{wiersz} … }"),
    "stała z formatem": ('f"{SHOW_ALL:>20}"', "…"),
    "stała z konwersją": ('f"{SHOW_ALL!r}"', "…"),
}


@pytest.mark.parametrize("opis", list(POLA))
def test_polecenie_podfunkcji_drukuje_pole_f_stringu_spoza_stalych_wielokropkiem(polecenie: ModuleType, opis: str) -> None:
    komunikat, sekcja = POLA[opis]

    czytane = polecenie.sub_features(NAPED.format(wstawka=f"run.check(True, {komunikat})"), "sonda.py")

    assert czytane == [("sonda-krok", ["pierwszy", sekcja])]


# Napęd, którego pomocnika polecenie czyta: wywołanie jest całą instrukcją ciała drive() albo całą prawą stroną
# przypisania do nazw. Pomocnik bez run.step i run.check może stać gdziekolwiek i ile razy.
CZYTANE_POMOCNIKI: Final = {
    "instrukcja": NAPED.format(wstawka="_pomocnik(run)") + POMOCNIK,
    "przypisanie do nazwy": NAPED.format(wstawka="wynik = _pomocnik(run)") + POMOCNIK,
    "przypisanie do dwóch nazw": NAPED.format(wstawka="a = b = _pomocnik(run)") + POMOCNIK,
    "return funkcji w drive() przed pomocnikiem": NAPED.format(
        wstawka="def _w_drive() -> int:\n        return 1\n\n    _pomocnik(run)"
    )
    + POMOCNIK,
    "return drive() po pomocniku": NAPED.format(wstawka="_pomocnik(run)\n    return") + POMOCNIK,
    "dwa wywołania": NAPED.format(wstawka='_pomocnik(run)\n    run.check(True, "między")\n    wynik = _pomocnik(run)') + POMOCNIK,
    "ciało try z samym finally": NAPED.format(
        wstawka='try:\n        _pomocnik(run)\n        run.check(True, "w try")\n    finally:\n        run.check(True, "w finally")'
    )
    + POMOCNIK,
    "kroki pomocników między krokami drive()": NAPED.format(
        wstawka="\n    ".join(
            [
                "_pomocnik(run, page)",
                'run.check(True, "po pomocniku")',
                "for _ in range(2):\n        _bez_krokow(run)",
                "_bez_krokow(run)",
                "wynik = _drugi(run)",
                'run.step(feature, "sonda-ostatni")',
            ]
        )
    )
    + "\n\ndef _pomocnik(run: Run, page: object) -> None:\n"
    '    run.check(True, SHOW_ALL)\n    run.step("sonda", "sonda-pomocnik")\n    run.check(True, f"w {SHOW_ALL}")\n'
    + '\n\ndef _drugi(run: Run) -> bool:\n    run.check(True, "w drugim")\n    run.step("sonda", "sonda-drugi")\n    return True\n'
    + "\n\ndef _bez_krokow(run: Run) -> None:\n    pass\n",
}


# Pomocnik z run.check w pętli, która nie jest pętlą nad stałą listą → cały napęd; odmowa wskazuje linię `# tu`.
ODMOWY_PRZEPLYWU_POMOCNIKA: Final = {
    "pętla po range w pomocniku": NAPED.format(wstawka="_pomocnik(run)")
    + '\n\ndef _pomocnik(run: Run) -> None:\n    for _ in range(2):\n        run.check(True, "x")  # tu\n',
    "return w pomocniku przed check": NAPED.format(wstawka="_pomocnik(run, page)")
    + '\n\ndef _pomocnik(run: Run, page: object) -> None:\n    if page is None:\n        return\n'
    '    run.check(True, "x")  # tu\n',
}


# Pętla nad stałą listą: bieg drukuje sprawdzenie w każdym obrocie, a sekcja raz na pętlę.
CZYTANE_PETLE: Final = {
    "krotka w nagłówku for": NAPED.format(wstawka='for nazwa in ("a", "b"):\n        run.check(True, f"w pętli {nazwa}")'),
    "krotka przypisana nazwie wcześniej w bloku": NAPED.format(
        wstawka='lista = ("a", "b")\n    for nazwa in lista:\n        run.check(True, "w pętli")\n    run.check(True, "po pętli")'
    ),
    "krotka z adnotacją w ciele try": NAPED.format(
        wstawka='try:\n        lista: tuple[str, ...] = ("a", "b")\n        for _ in lista:\n            run.check(True, "w pętli")\n'
        "    finally:\n        pass"
    ),
    "pętle zagnieżdżone nad literałami": NAPED.format(
        wstawka='for _ in (1, 2):\n        for _ in [3]:\n            run.check(True, "wewnątrz")\n        run.check(True, "na zewnątrz")'
    ),
    "pętla nad literałem w pomocniku": NAPED.format(wstawka="_pomocnik(run)")
    + '\n\ndef _pomocnik(run: Run) -> None:\n    for _ in (1, 2, 3):\n        run.check(True, "w pomocniku")\n',
}


class _Zapis:
    """Run próbki napędu, który zapisuje kroki i sprawdzenia w kolejności biegu."""

    def __init__(self) -> None:
        self.bieg: list[tuple[str, str]] = []

    def step(self, feature: str, name: str) -> None:
        self.bieg.append(("step", name))

    def check(self, condition: bool, message: str) -> None:
        self.bieg.append(("check", message))


@pytest.mark.parametrize("opis", list(CZYTANE_POMOCNIKI))
def test_polecenie_podfunkcji_drukuje_pomocnika_tak_jak_bieg_napedu(polecenie: ModuleType, opis: str, tmp_path: Path) -> None:
    """Wydruk polecenia to kroki i sprawdzenia w kolejności i liczbie, w jakiej drukuje je prawdziwy bieg napędu próbki,
    a nie w kolejności tekstu (W1 i W2 r1 #1769)."""

    zrodlo = CZYTANE_POMOCNIKI[opis]
    plik = tmp_path / "sonda_biegu.py"
    plik.write_text(zrodlo.replace("from drive.common import Run\n", "Run = object\n"), encoding="utf-8")
    run = _Zapis()
    modul(plik).drive(run, None)

    czytane = polecenie.sub_features(zrodlo, "sonda.py")

    assert [wpis for krok, komunikaty in czytane for wpis in [("step", krok), *(("check", k) for k in komunikaty)]] == run.bieg


# Sprawdzenie w miejscu ciała drive(), które biegnie raz, gdy biegnie drive(); bieg drukuje je raz, jak sekcja.
CZYTANE_PRZEPLYW: Final = {
    "warunek if": 'if run.check(True, "w warunku") is None:\n        pass',
    "pierwszy argument or": 'run.check(True, "w or") or None',
    "przedmiot match": 'match run.check(True, "w match"):\n        case _:\n            pass',
    "warunek assert": 'assert run.check(True, "w assert") is None',
    "ciało try z samym finally": 'try:\n        run.check(True, "w try")\n    finally:\n        run.check(True, "w finally")',
    "return po sprawdzeniu": 'run.check(True, "przed return")\n    return',
    "return ze sprawdzeniem (D1 r1)": 'return run.check(True, "w return")',
    "drugi operand pojedynczego porównania": '_ = None is run.check(True, "w porównaniu")',
    "argument wywołania": 'print(run.check(True, "w argumencie"))',
    "ciało with": "with open(__file__, encoding='utf-8'):\n        run.check(True, \"w with\")",
    "finally po try z except": 'try:\n        pass\n    except ValueError:\n        pass\n    finally:\n        run.check(True, "w finally")',
    "wartość przypisania z adnotacją": 'x: object = run.check(True, "w wartości")',
    "test wyrażenia warunkowego": '_ = None if run.check(True, "w teście") else None',
    "iterowane pętli po wywołaniu": 'for _ in str(run.check(True, "w iterowanym")):\n        pass',
    "return funkcji w drive()": 'def _w_drive() -> int:\n        return 1\n\n    run.check(True, "po funkcji")',
}


@pytest.mark.parametrize("opis", list(CZYTANE_PRZEPLYW))
def test_polecenie_podfunkcji_czyta_sprawdzenie_w_miejscu_ktore_biegnie_raz_jak_bieg(polecenie: ModuleType, opis: str, tmp_path: Path) -> None:
    zrodlo = NAPED.format(wstawka=CZYTANE_PRZEPLYW[opis])
    plik = tmp_path / "sonda_przeplywu.py"
    plik.write_text(zrodlo.replace("from drive.common import Run\n", "Run = object\n"), encoding="utf-8")
    run = _Zapis()
    modul(plik).drive(run, None)

    czytane = polecenie.sub_features(zrodlo, "sonda.py")

    assert [wpis for krok, komunikaty in czytane for wpis in [("step", krok), *(("check", k) for k in komunikaty)]] == run.bieg


@pytest.mark.parametrize("opis", list(CZYTANE_PETLE))
def test_polecenie_podfunkcji_drukuje_sprawdzenie_raz_na_petle_nad_stala_lista(polecenie: ModuleType, opis: str, tmp_path: Path) -> None:
    """Bieg drukuje sprawdzenie w pętli nad stałą listą raz w każdym obrocie, a sekcja raz na pętlę: test porównuje
    różne sprawdzenia biegu w kolejności ich pierwszego wystąpienia z wydrukiem, a pole zmiennej pętli w wydruku (`…`)
    pasuje do każdej jej wartości."""

    zrodlo = CZYTANE_PETLE[opis]
    plik = tmp_path / "sonda_petli.py"
    plik.write_text(zrodlo.replace("from drive.common import Run\n", "Run = object\n"), encoding="utf-8")
    run = _Zapis()
    modul(plik).drive(run, None)

    czytane = polecenie.sub_features(zrodlo, "sonda.py")

    wydruk = [wpis for krok, komunikaty in czytane for wpis in [("step", krok), *(("check", k) for k in komunikaty)]]
    wzory = [(rodzaj, re.compile(".*".join(map(re.escape, tekst.split("…"))))) for rodzaj, tekst in wydruk]
    pierwsze = dict.fromkeys(
        next(wpis for wpis, (rodzaj, wzor) in zip(wydruk, wzory, strict=True) if rodzaj == zapis[0] and wzor.fullmatch(zapis[1]))
        for zapis in run.bieg
    )
    assert list(pierwsze) == wydruk
    assert len(run.bieg) > len(wydruk)


@pytest.mark.parametrize("opis", list(ODMOWY_PRZEPLYWU_POMOCNIKA))
def test_polecenie_podfunkcji_odmawia_sprawdzenia_pomocnika_poza_jednym_biegiem(polecenie: ModuleType, opis: str) -> None:
    zrodlo = ODMOWY_PRZEPLYWU_POMOCNIKA[opis]
    linia = next(numer for numer, tekst in enumerate(zrodlo.splitlines(), start=1) if "# tu" in tekst)

    with pytest.raises(polecenie.Unreadable) as odmowa:
        polecenie.sub_features(zrodlo, "sonda.py")

    assert str(odmowa.value).startswith(f"sonda.py:{linia}: "), str(odmowa.value)


# Ciało drive() i ciało try z samym finally, w którym instrukcja przed pomocnikiem rzuca wyjątek.
RZUCA_PRZED_POMOCNIKIEM: Final = {
    "ciało drive()": 'run.check(True, "przed")\n    raise ValueError("w próbce")\n    _pomocnik(run)',
    "ciało try z samym finally": 'try:\n        run.check(True, "przed")\n        raise ValueError("w próbce")\n        _pomocnik(run)\n'
    "    finally:\n        pass",
}


def test_wyjatek_przed_pomocnikiem_konczy_bieg_w_try_z_finally_jak_w_ciele_drive(polecenie: ModuleType, tmp_path: Path) -> None:
    """Wyjątek przed pomocnikiem przechodzi przez samo finally i kończy drive(), więc bieg drukuje początek sekcji i pada,
    jak w ciele drive(): w obu postaciach polecenie drukuje tę samą sekcję, a bieg jej początek."""

    biegi: list[list[tuple[str, str]]] = []
    sekcje: list[list[tuple[str, list[str]]]] = []
    for opis, wstawka in RZUCA_PRZED_POMOCNIKIEM.items():
        zrodlo = NAPED.format(wstawka=wstawka) + POMOCNIK
        plik = tmp_path / f"sonda_{len(biegi)}.py"
        plik.write_text(zrodlo.replace("from drive.common import Run\n", "Run = object\n"), encoding="utf-8")
        run = _Zapis()
        with pytest.raises(ValueError, match="w próbce"):
            modul(plik).drive(run, None)
        biegi.append(run.bieg)
        sekcje.append(polecenie.sub_features(zrodlo, "sonda.py"))

    assert biegi[0] == biegi[1] == [("step", "sonda-krok"), ("check", "pierwszy"), ("check", "przed")]
    assert sekcje[0] == sekcje[1] == [("sonda-krok", ["pierwszy", "przed", "z pomocnika"])]


# Sondy przeglądu #1812 r1 (wstawki w ciele drive()): dla każdej polecenie odmawia albo drukuje to, co bieg.
SONDY_PRZEGLADU: Final = {
    "dalszy człon łańcucha porównań": '_ = 1 > 2 > run.check(True, "LUKA")',
    "dalszy człon łańcucha w if": 'if 1 > 2 > run.check(True, "LUKA"):\n        pass',
    "lista z nazwy opróżniona clear()": 'lista = ["a"]\n    lista.clear()\n    for _ in lista:\n        run.check(True, "LUKA")',
    "lista z nazwy opróżniona del [:]": 'lista = ["a"]\n    del lista[:]\n    for _ in lista:\n        run.check(True, "LUKA")',
    "drugi argument or": 'feature or run.check(True, "LUKA")',
}


@pytest.mark.parametrize("opis", list(SONDY_PRZEGLADU))
def test_polecenie_podfunkcji_odmawia_albo_drukuje_to_co_bieg_w_sondach_przegladu(polecenie: ModuleType, opis: str, tmp_path: Path) -> None:
    zrodlo = NAPED.format(wstawka=SONDY_PRZEGLADU[opis])
    plik = tmp_path / "sonda_przegladu.py"
    plik.write_text(zrodlo.replace("from drive.common import Run\n", "Run = object\n"), encoding="utf-8")
    run = _Zapis()
    modul(plik).drive(run, None)

    try:
        czytane = polecenie.sub_features(zrodlo, "sonda.py")
    except polecenie.Unreadable:
        return
    assert [wpis for krok, komunikaty in czytane for wpis in [("step", krok), *(("check", k) for k in komunikaty)]] == run.bieg


# Znane luki polecenia podfunkcji (tests/fixtures/znane_luki.py): opis postaci → (napęd, ile razy jego bieg drukuje
# komunikat LUKA; None, gdy drukuje kroki innego modułu). Każdy przechodzi przez ruff z konfiguracją drive/ i przez
# polecenie, a sekcja drukuje LUKA inną liczbę razy niż bieg. Polecenie odmawia każdego atrybutu .step/.check poza
# tymi, które czyta, i każdego użycia nazwy pomocnika poza wywołaniem, które jest całą instrukcją ciała drive() albo
# ciała try z samym finally, więc te postacie sięgają po check bez atrybutu, po pomocnika bez jego nazwy albo po
# funkcję innego modułu.
POMOCNIK_LUKI: Final = '\n\ndef sprawdz(run: Run) -> None:\n    run.check(True, "LUKA")\n'
ZNANE_LUKI: Final = {
    "zna tylko atrybut .check: check przez getattr": (NAPED.format(wstawka='getattr(run, "check")(True, "LUKA")'), 1),
    "zna tylko atrybut .check: check przez operator.methodcaller": (
        NAPED.format(wstawka='import operator\n\n    operator.methodcaller("check", True, "LUKA")(run)'),
        1,
    ),
    "zna tylko atrybut .check: check ze słownika klasy": (
        NAPED.format(wstawka='type(run).__dict__["check"](run, True, "LUKA")'),
        1,
    ),
    "czyta tylko ten moduł: funkcja innego modułu napędu z run": (
        "from drive.uzupelnienie import drive_result_card\n" + NAPED.format(wstawka="drive_result_card(run, page)"),
        None,
    ),
    "nie widzi wyjątku stłumionego przez menedżer kontekstu: with suppress": (
        "from contextlib import suppress\n"
        + NAPED.format(wstawka='with suppress(ValueError):\n        int(feature)\n        run.check(True, "LUKA")'),
        0,
    ),
    "zna pomocnika tylko po nazwie: drugi raz przez globals()": (
        NAPED.format(wstawka='sprawdz(run)\n    globals()["sprawdz"](run)') + POMOCNIK_LUKI,
        2,
    ),
    "zna pomocnika tylko po nazwie: drugi raz przez atrybut modułu": (
        NAPED.format(wstawka="import sys\n\n    sprawdz(run)\n    sys.modules[__name__].sprawdz(run)") + POMOCNIK_LUKI,
        2,
    ),
}


@wymaga_ruff
def test_znane_luki_polecenia_podfunkcji_przechodza_przez_kazdy_jego_mechanizm(polecenie: ModuleType, tmp_path: Path) -> None:
    pliki = zapisz({opis: zrodlo for opis, (zrodlo, _) in ZNANE_LUKI.items()}, tmp_path)
    zgloszenia = ruff(pliki, sonda=SUB_FEATURES.parent / "drive" / "sonda_luki.py")
    for opis, plik in pliki.items():
        try:
            czytane = polecenie.sub_features(plik.read_text(encoding="utf-8"), plik.name)
        except polecenie.Unreadable as odmowa:
            zgloszenia[opis].append(f"sub_features.py: {odmowa}")
        else:
            razy = ZNANE_LUKI[opis][1]
            if razy is not None and [komunikat for _, komunikaty in czytane for komunikat in komunikaty].count("LUKA") == razy:
                zgloszenia[opis].append(f"sub_features.py: drukuje LUKA {razy} raz(y), jak bieg napędu")

    assert_znane_luki(zgloszenia, "tests/test_mapy_funkcji.py")
