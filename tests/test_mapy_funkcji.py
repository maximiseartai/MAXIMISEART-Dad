"""Mapa funkcji skilla ``verify-*`` (``features/``) zgadza się z jego kodem i ``SKILL.md``.

Mapa to pamięć skilla: agent wybiera z niej funkcję do sprawdzenia, a harness skilla prowadzi funkcje z krotki
``FEATURES`` w swoich skryptach (napisów albo rejestru ``Feature("nazwa", …)``) i z modułów pakietu
``scripts/<pakiet>/``. Rozjazd mapy z kodem czerwieni CI, a nie dopiero przebieg skilla u agenta. Plik funkcji skilla z funkcjami w kodzie odpowiada funkcji z kodu
w obie strony, więc ``features/README.md`` takiego skilla nie listuje plików: lista bez sprawdzenia kompletności kłamie od
pierwszej nowej funkcji. Skill bez funkcji w kodzie listuje je w README, a każdy plik funkcji ma tam link.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
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


def _sub_features(feature: str, polecenie: Path = SUB_FEATURES) -> str:
    done = subprocess.run(
        [sys.executable, str(polecenie), "--feature", feature], capture_output=True, timeout=60, check=False
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
# razy i w jakiej kolejności krok pomocnika biegnie (mechanizm: czyta tylko jedno wywołanie, które jest całą
# instrukcją ciała drive() albo całą prawą stroną przypisania do nazwy). Linia odmowy ma komentarz `# tu`.
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


# Znane luki polecenia podfunkcji (tests/fixtures/znane_luki.py): opis postaci → (napęd, ile razy jego bieg drukuje
# komunikat LUKA; None, gdy drukuje kroki innego modułu). Każdy przechodzi przez ruff z konfiguracją drive/ i przez
# polecenie, a sekcja drukuje LUKA inną liczbę razy niż bieg. Polecenie odmawia każdego atrybutu .step/.check poza
# tymi, które czyta, i każdego użycia nazwy pomocnika poza jednym wywołaniem w instrukcji drive(), więc te postacie
# sięgają po check bez atrybutu, po pomocnika bez jego nazwy albo po funkcję innego modułu.
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


ROZLICZENIA = SKILLS / "verify-rozliczenia"
WORKFLOW_SUB_FEATURES = ROOT / ".agents/skills/verify-rozliczenia/scripts/workflow_sub_features.py"


def test_podfunkcje_mapy_rozliczen_sa_wynikiem_polecenia_z_planu_wariantow() -> None:
    """Plik funkcji ``verify-rozliczenia``, który nazywa polecenie ``workflow_sub_features.py`` swojej funkcji, ma jego
    wynik (plan wariantów procesu) jako całą sekcję ``## Sub-features``, tuż przed ``## How to get to it (user POV)``, a
    każdy plik z listy ``## Features`` w README nazywa polecenie (D2 #1836)."""

    printed = [
        path
        for path in _feature_files(ROZLICZENIA)
        if f"workflow_sub_features.py --feature {path.stem}`" in path.read_text(encoding="utf-8")
    ]

    problems = [
        f"verify-rozliczenia/features/{path.name}: sekcja ## Sub-features nie jest planem wariantów procesu; zastąp ją "
        f"wynikiem `.venv/bin/python .agents/skills/verify-rozliczenia/scripts/workflow_sub_features.py --feature "
        f"{path.stem}` (Windows: `py -3`)"
        for path in printed
        if f"\n{_sub_features(path.stem, WORKFLOW_SUB_FEATURES)}\n## How to get to it (user POV)\n"
        not in path.read_text(encoding="utf-8")
    ]

    assert printed, "żaden plik mapy verify-rozliczenia nie nazywa polecenia workflow_sub_features.py swojej funkcji"
    assert problems == [], "\n".join(problems)
    assert sorted(name for name in _linked(ROZLICZENIA) if name not in {path.name for path in printed}) == [], (
        "plik funkcji z listy ## Features w verify-rozliczenia/features/README.md nie nazywa polecenia "
        "workflow_sub_features.py: kontrakt mapy mówi, że sekcja każdego pliku funkcji pochodzi z polecenia"
    )


def _skrypt_skilla(monkeypatch: pytest.MonkeyPatch, nazwa: str) -> ModuleType:
    monkeypatch.syspath_prepend(str(WORKFLOW_SUB_FEATURES.parent))
    spec = importlib.util.spec_from_file_location(nazwa, WORKFLOW_SUB_FEATURES.parent / f"{nazwa}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, nazwa, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def przebieg(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return _skrypt_skilla(monkeypatch, "run_verification")


@pytest.fixture
def polecenie_rozliczen(monkeypatch: pytest.MonkeyPatch, przebieg: ModuleType) -> ModuleType:
    return _skrypt_skilla(monkeypatch, "workflow_sub_features")


def test_plan_kazdego_wariantu_biegnie_do_konca_bez_sladu_na_dysku(
    przebieg: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Plan wykonuje workflow i ``_verify`` z zapisem zamiast uruchomienia: dochodzi do ``cleanup`` i ``self-test``
    każdego wariantu, a w katalogu, w którym biegnie, nie zostaje żaden plik ani katalog (#1804 r2)."""

    monkeypatch.chdir(tmp_path)

    plany = {wariant: przebieg.plan(wariant) for wariant in przebieg.WORKFLOW_VARIANTS}

    assert len(plany) == 9
    assert {wariant: [krok.name for krok in kroki][-2:] for wariant, kroki in plany.items()} == {
        wariant: ["cleanup", "self-test"] for wariant in plany
    }
    assert list(tmp_path.iterdir()) == []


class _SciezkaWindows(PureWindowsPath):
    """Ścieżka z regułami Windows, której pliki nie istnieją, a zapis do nich niczego nie robi."""

    def exists(self) -> bool:
        return False

    def is_file(self) -> bool:
        return False

    def write_text(self, data: str, encoding: str | None = None) -> int:
        return len(data)


def test_plan_i_bieg_pokazuja_te_same_polecenia_ze_sciezkami_windows(
    przebieg: ModuleType, polecenie_rozliczen: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Na regułach ścieżek Windows plan każdego wariantu jest taki sam jak na tym systemie, sekcja z polecenia równa się
    plikowi mapy, a bieg workflow w folderach Windows zapisuje te same polecenia co plan: plan i bieg pokazują folder
    runu jedną drogą (W1 r2 #1804, run 43616329420)."""

    tutaj = {wariant: przebieg.plan(wariant) for wariant in przebieg.WORKFLOW_VARIANTS}
    monkeypatch.setattr(przebieg, "Path", _SciezkaWindows)
    monkeypatch.setattr(przebieg.os, "sep", "\\")
    monkeypatch.setattr(przebieg, "_launch", lambda arguments, environment: przebieg._Completed("", "", 0))
    foldery = {r"D:\run\runs\x": "<run-root>", r"D:\run\evidence\x": "<evidence>", r"D:\wzorce": "<templates>"}
    bieg = przebieg._Record(planning=False, folders=foldery)
    monkeypatch.setattr(przebieg, "_record", bieg)

    windows = {wariant: przebieg.plan(wariant) for wariant in przebieg.WORKFLOW_VARIANTS}
    sekcja = polecenie_rozliczen.section("order-intermax", przebieg)
    przebieg._run_workflow("intermax", *(_SciezkaWindows(folder) for folder in foldery))

    assert windows == tutaj
    assert f"\n{sekcja}\n## How to get to it (user POV)\n" in (ROZLICZENIA / "features" / "order-intermax.md").read_text(
        encoding="utf-8"
    )
    assert bieg.steps == [krok for krok in tutaj["intermax"] if krok.name not in ("cleanup", "self-test")]


def _workflow_proby(przebieg: ModuleType, rozwidlenie: bool) -> Callable[..., None]:
    def workflow(variant: object, run_root: Path, evidence_root: Path, templates: object) -> None:
        if rozwidlenie and evidence_root.exists():
            przebieg._run_step("tylko-w-biegu", ["proba.py"], evidence_root, {}, expected_exit=0)

    return workflow


@pytest.mark.parametrize("rozwidlenie", [False, True], ids=["kroki-jak-plan", "krok-poza-planem"])
def test_bieg_konczy_sie_verify_fail_gdy_kroki_roznia_sie_od_planu(
    przebieg: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], rozwidlenie: bool
) -> None:
    """Prawdziwy bieg zapisuje kroki, które uruchomił, i kończy się ``VERIFY FAIL``, gdy różnią się od planu wariantu,
    jak tu workflow, który w biegu widzi swój katalog dowodów, a w planie nie (#1804 r2)."""

    proces = przebieg.WorkflowProcess("proba", _workflow_proby(przebieg, rozwidlenie), (), ("cleanup",))
    monkeypatch.setitem(przebieg.WORKFLOW_VARIANTS, "proba", przebieg.WorkflowVariant(proces))
    monkeypatch.setattr(przebieg, "_launch", lambda arguments, environment: przebieg._Completed("", "", 0))

    kod = przebieg._verify("proba", tmp_path / "wzorce", tmp_path / "run")

    assert (kod, "differ from its plan" in capsys.readouterr().err) == ((1, True) if rozwidlenie else (0, False))


def _modul_procesow(przebieg: ModuleType, warianty: dict[str, object], **nazwy: object) -> ModuleType:
    """Moduł z procesami ``nazwy``, wariantami ``warianty`` i planem, który każdemu wariantowi daje jeden krok."""

    modul = ModuleType("procesy_proby")
    vars(modul).update(
        WorkflowProcess=przebieg.WorkflowProcess,
        WORKFLOW_VARIANTS=warianty,
        plan=lambda wariant: [przebieg.PlannedStep("run", "proba.py --zawsze", 0)],
        **nazwy,
    )
    return modul


def test_polecenie_mapy_rozliczen_odmawia_nazwy_procesu_uzytej_drugi_raz(
    przebieg: ModuleType, polecenie_rozliczen: ModuleType
) -> None:
    pierwszy = przebieg.WorkflowProcess("proba", lambda *_: None, (), ())
    drugi = przebieg.WorkflowProcess("proba", lambda *_: None, (), ())
    warianty = {"a": przebieg.WorkflowVariant(pierwszy), "b": przebieg.WorkflowVariant(drugi)}
    modul = _modul_procesow(przebieg, warianty, PIERWSZY=pierwszy, DRUGI=drugi)

    with pytest.raises(polecenie_rozliczen.Refusal, match="two processes are named proba"):
        polecenie_rozliczen.section("proba", modul)


def test_polecenie_mapy_rozliczen_odmawia_procesu_bez_wariantu(przebieg: ModuleType, polecenie_rozliczen: ModuleType) -> None:
    proba = przebieg.WorkflowProcess("proba", lambda *_: None, (), ())
    bez_wariantu = przebieg.WorkflowProcess("bez-wariantu", lambda *_: None, (), ())
    modul = _modul_procesow(przebieg, {"a": przebieg.WorkflowVariant(proba)}, PROBA=proba, BEZ_WARIANTU=bez_wariantu)

    with pytest.raises(polecenie_rozliczen.Refusal, match="no variant runs bez-wariantu"):
        polecenie_rozliczen.section("proba", modul)


def test_plan_wariantu_ktory_nie_dobiega_konca_to_odmowa_a_nie_krotsza_lista(
    przebieg: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def workflow(variant: object, run_root: Path, evidence_root: Path, templates: object) -> None:
        przebieg._run_step("pierwszy", ["proba.py"], evidence_root, {}, expected_exit=0)
        (run_root / "nie-ma").read_text(encoding="utf-8")

    proces = przebieg.WorkflowProcess("proba", workflow, (), ("cleanup",))
    monkeypatch.setitem(przebieg.WORKFLOW_VARIANTS, "proba", przebieg.WorkflowVariant(proces))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(przebieg.PlanFailure, match="the plan of proba stopped"):
        przebieg.plan("proba")


def test_polecenie_mapy_rozliczen_laczy_warianty_o_tym_samym_planie(przebieg: ModuleType, polecenie_rozliczen: ModuleType) -> None:
    proba = przebieg.WorkflowProcess("proba", lambda *_: None, (), ())
    warianty = {"a": przebieg.WorkflowVariant(proba), "b": przebieg.WorkflowVariant(proba, run_exit=1)}
    modul = _modul_procesow(przebieg, warianty, PROBA=proba)

    sekcja = polecenie_rozliczen.section("proba", modul)

    assert sekcja.endswith("Variants `a`, `b`:\n\n- `run`: `proba.py --zawsze`, exit 0.\n"), sekcja


# Znane luki planu wariantów (tests/fixtures/znane_luki.py): klasa mechanizmu → moduł z workflow „LUKA”, którego plan
# nie pokazuje tego, co robi prawdziwy bieg, a który przechodzi przez ruff z konfiguracją scripts/ skilla, przez plan
# i przez polecenie; LUKA_W_CI mówi, czy wariant biegnie w CI, gdzie bieg porównuje swoje kroki z planem.
ZNANE_LUKI_ROZLICZEN: Final = {
    "gałąź zależna od wyniku kroku, wariant spoza CI: plan ma tylko foldery zastępcze": """\
from pathlib import Path

from run_verification import _run_step

LUKA_W_CI = False


def workflow(variant: object, run_root: Path, evidence_root: Path, templates: object) -> None:
    if evidence_root.exists():
        _run_step("LUKA", ["luka.py"], evidence_root, {}, expected_exit=0)
""",
    "efekt uboczny poza zapisywanymi funkcjami: plan zapisuje tylko kroki i dwie zmiany katalogu runu": """\
from pathlib import Path

LUKA_W_CI = True


def workflow(variant: object, run_root: Path, evidence_root: Path, templates: object) -> None:
    (Path.cwd() / "LUKA").mkdir()
""",
    "podproces poza dwiema funkcjami kroków: plan i bieg zapisują tylko _run_step i _run_process_step": """\
from pathlib import Path
import subprocess
import sys

LUKA_W_CI = True


def workflow(variant: object, run_root: Path, evidence_root: Path, templates: object) -> None:
    subprocess.run([sys.executable, "-c", "print('LUKA')"], check=True, capture_output=True)
""",
}


@wymaga_ruff
def test_znane_luki_planu_wariantow_przechodza_przez_kazdy_jego_mechanizm(
    przebieg: ModuleType, polecenie_rozliczen: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pliki = zapisz(ZNANE_LUKI_ROZLICZEN, tmp_path)
    zgloszenia = ruff(pliki, sonda=WORKFLOW_SUB_FEATURES.parent / "sonda_luki.py")
    for opis, plik in pliki.items():
        luka = _modul_luki(plik)
        proces = przebieg.WorkflowProcess("luka", luka.workflow, (), ("cleanup",))
        szablony = "synthetic" if luka.LUKA_W_CI else "config"
        monkeypatch.setitem(przebieg.WORKFLOW_VARIANTS, "luka", przebieg.WorkflowVariant(proces, templates=szablony))
        katalog = tmp_path / f"plan-{plik.stem}"
        katalog.mkdir()
        monkeypatch.chdir(katalog)
        try:
            sekcja = polecenie_rozliczen.section("luka", przebieg)
        except (polecenie_rozliczen.Refusal, przebieg.PlanFailure) as odmowa:
            zgloszenia[opis].append(f"plan: {odmowa}")
        else:
            if "LUKA" in sekcja:
                zgloszenia[opis].append("plan pokazuje lukę")
        monkeypatch.delitem(przebieg.WORKFLOW_VARIANTS, "luka")

    assert_znane_luki(zgloszenia, "tests/test_mapy_funkcji.py")


def _modul_luki(plik: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(plik.stem, plik)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul
