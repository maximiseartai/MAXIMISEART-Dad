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
    "drugie wywołanie": "_pomocnik(run)\n    _pomocnik(run)  # tu",
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


def test_podfunkcje_mapy_rozliczen_sa_wynikiem_polecenia_z_workflow_procesu() -> None:
    """Plik funkcji ``verify-rozliczenia``, który nazywa polecenie ``workflow_sub_features.py`` swojej funkcji, ma jego
    wynik jako całą sekcję ``## Sub-features``, tuż przed ``## How to get to it (user POV)`` (#1630)."""

    printed = [
        path
        for path in _feature_files(ROZLICZENIA)
        if f"workflow_sub_features.py --feature {path.stem}`" in path.read_text(encoding="utf-8")
    ]

    problems = [
        f"verify-rozliczenia/features/{path.name}: sekcja ## Sub-features nie jest wynikiem workflow procesu; zastąp ją "
        f"wynikiem `.venv/bin/python .agents/skills/verify-rozliczenia/scripts/workflow_sub_features.py --feature "
        f"{path.stem}` (Windows: `py -3`)"
        for path in printed
        if f"\n{_sub_features(path.stem, WORKFLOW_SUB_FEATURES)}\n## How to get to it (user POV)\n"
        not in path.read_text(encoding="utf-8")
    ]

    assert printed, "żaden plik mapy verify-rozliczenia nie nazywa polecenia workflow_sub_features.py swojej funkcji"
    assert problems == [], "\n".join(problems)


@pytest.fixture
def polecenie_rozliczen(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(WORKFLOW_SUB_FEATURES.parent))
    spec = importlib.util.spec_from_file_location("workflow_sub_features", WORKFLOW_SUB_FEATURES)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "workflow_sub_features", module)
    spec.loader.exec_module(module)
    return module


WORKFLOW: Final = """\
from pathlib import Path

from run_verification import WorkflowProcess, WorkflowVariant

HELPER_DIRECTORY = Path("scripts")


def _run_step(name: str, arguments: list[str], *, expected_exit: int) -> None:
    del name, arguments, expected_exit


def _run_process_step(name: str, arguments: list[str], *, expected_exit: int) -> None:
    del name, arguments, expected_exit


def _etap() -> None:
    _run_step("etap", [str(HELPER_DIRECTORY / "sonda_fixture.py")], expected_exit=0)


def _sonda_workflow(nazwa: str, polecenie: str) -> None:
    _run_step("fixture", [str(HELPER_DIRECTORY / "sonda_fixture.py"), "--root", nazwa], expected_exit=0)
    _run_process_step("run", ["intermax", "--register", polecenie], expected_exit=1)
    _run_step("assert-run", [str(HELPER_DIRECTORY / "assert_sonda.py")], expected_exit=0)
    {wstawka}


SONDA = WorkflowProcess("sonda", _sonda_workflow)
WORKFLOW_VARIANTS = {"sonda": WorkflowVariant(SONDA), "druga": WorkflowVariant(SONDA)}
"""
ASSERT_SONDY: Final = """\
from wynik_uruchomienia import check_metrics, finish

STALA = "stała"


def _dwa(inne: list[str], errors: list[str]) -> None:
    del inne
    errors.append("drugi")


def _check(errors: list[str]) -> None:
    errors.append("pierwszy")


def main() -> int:
    errors: list[str] = []
    _check(errors)
    _dwa(["x"], errors)
    check_metrics("metrics.jsonl", errors=errors)
    {wstawka}
    return finish(errors, "ASSERT OK | sonda=true")
"""
WSPOLNY_SONDY: Final = """\
def check_metrics(path: str, *, errors: list[str]) -> None:
    errors.append(f"{path} nie ma rekordu")


def finish(errors: list[str], success_message: str) -> int:
    if errors:
        return 1
    print(success_message)
    return 0
"""


def _sonda(**pliki: str) -> dict[str, str]:
    """Pliki skilla sondy: workflow, asercja, wspólny moduł i fixture, z wstawką w ciele workflow i ``main`` asercji."""

    return {
        "run_verification.py": WORKFLOW.replace("{wstawka}", pliki.get("workflow", "pass")),
        "assert_sonda.py": ASSERT_SONDY.replace("{wstawka}", pliki.get("asercja", "pass")),
        "wynik_uruchomienia.py": pliki.get("wspolny", WSPOLNY_SONDY),
        "sonda_fixture.py": "def main() -> int:\n    return 0\n",
    }


def test_polecenie_mapy_rozliczen_czyta_kroki_workflow_i_sprawdzenia_asercji(polecenie_rozliczen: ModuleType) -> None:
    """Krok to instrukcja ciała workflow z literałem nazwy, skryptu i kodu wyjścia; pod krokiem skryptu stoją komunikaty
    ``errors.append`` w kolejności źródła, z funkcji skryptu i wspólnego modułu, którym ``main`` podaje ``errors``
    (każda raz), i niepusta linia ``finish``."""

    pliki = _sonda(
        asercja="\n    ".join(
            [
                'errors.append(f"{STALA} i {len(STALA)}")',
                "_check(errors)",
                'finish(errors, "")',
            ]
        )
    )

    variants, steps = polecenie_rozliczen.sub_features("sonda", pliki.__getitem__)

    assert variants == ["sonda", "druga"]
    assert [(step.name, step.runs, step.exit_code, step.checks, step.prints) for step in steps] == [
        ("fixture", "sonda_fixture.py", 0, [], []),
        ("run", "tools/uruchom_proces.py intermax", 1, [], []),
        ("assert-run", "assert_sonda.py", 0, ["pierwszy", "drugi", "… nie ma rekordu", "stała i …"], ["ASSERT OK | sonda=true"]),
    ]


ZAPIS = 'str(HELPER_DIRECTORY / "sonda_fixture.py")'
# Postać → (plik, pliki sondy); linia, którą odmowa wskazuje, ma komentarz `# tu`.
ODMOWY_ROZLICZEN: Final = {
    "krok: nazwa zmienną": ("run_verification.py", {"workflow": f"_run_step(nazwa, [{ZAPIS}], expected_exit=0)  # tu"}),
    "krok: nazwa f-stringiem": ("run_verification.py", {"workflow": f'_run_step(f"{{nazwa}}-run", [{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: nazwa nazwana": ("run_verification.py", {"workflow": f'_run_step(name="x", arguments=[{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: argumenty zmienną": ("run_verification.py", {"workflow": '_run_step("x", polecenie, expected_exit=0)  # tu'}),
    "krok: skrypt nie pierwszy": ("run_verification.py", {"workflow": f'_run_step("x", ["--root", {ZAPIS}], expected_exit=0)  # tu'}),
    "krok: skrypt bez HELPER_DIRECTORY": ("run_verification.py", {"workflow": '_run_step("x", [str(Path("a.py"))], expected_exit=0)  # tu'}),
    "krok: skrypt zmienną": ("run_verification.py", {"workflow": '_run_step("x", [str(HELPER_DIRECTORY / nazwa)], expected_exit=0)  # tu'}),
    "krok procesu: polecenie zmienną": ("run_verification.py", {"workflow": '_run_process_step("x", [polecenie], expected_exit=0)  # tu'}),
    "krok: bez expected_exit": ("run_verification.py", {"workflow": f'_run_step("x", [{ZAPIS}])  # tu'}),
    "krok: expected_exit z pola wariantu": ("run_verification.py", {"workflow": f'_run_step("x", [{ZAPIS}], expected_exit=nazwa.run_exit)  # tu'}),
    "krok: expected_exit True": ("run_verification.py", {"workflow": f'_run_step("x", [{ZAPIS}], expected_exit=True)  # tu'}),
    "krok: w if": ("run_verification.py", {"workflow": f'if nazwa:\n        _run_step("x", [{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: w pętli": ("run_verification.py", {"workflow": f'for _ in nazwa:\n        _run_step("x", [{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: w funkcji zagnieżdżonej": ("run_verification.py", {"workflow": f'def _krok() -> None:\n        _run_step("x", [{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: w lambdzie": ("run_verification.py", {"workflow": f'krok = lambda: _run_step("x", [{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: jako wartość": ("run_verification.py", {"workflow": "krok = _run_step  # tu"}),
    "krok: wynik przypisany": ("run_verification.py", {"workflow": f'wynik = _run_step("x", [{ZAPIS}], expected_exit=0)  # tu'}),
    "krok: w funkcji modułu": ("run_verification.py", {"workflow": "_etap()  # tu"}),
    "krok: funkcja modułu jako wartość": ("run_verification.py", {"workflow": "etap = _etap  # tu"}),
    "errors: extend": ("assert_sonda.py", {"asercja": 'errors.extend(["x"])  # tu'}),
    "errors: insert": ("assert_sonda.py", {"asercja": 'errors.insert(0, "x")  # tu'}),
    "errors: append jako wartość": ("assert_sonda.py", {"asercja": "dopisz = errors.append  # tu"}),
    "errors: +=": ("assert_sonda.py", {"asercja": 'errors += ["x"]  # tu'}),
    "errors: przypisanie niepustej listy": ("assert_sonda.py", {"asercja": 'errors = ["x"]  # tu'}),
    "errors: podstawienie elementu": ("assert_sonda.py", {"asercja": 'errors[0] = "x"  # tu'}),
    "errors: usunięcie elementu": ("assert_sonda.py", {"asercja": "del errors[0]  # tu"}),
    "append: dwa argumenty": ("assert_sonda.py", {"asercja": 'errors.append("x", "y")  # tu'}),
    "append: nazwany": ("assert_sonda.py", {"asercja": 'errors.append(object="x")  # tu'}),
    "append: *args": ("assert_sonda.py", {"asercja": 'errors.append(*["x"])  # tu'}),
    "append: komunikat zmienną": ("assert_sonda.py", {"asercja": "komunikat = STALA\n    errors.append(komunikat)  # tu"}),
    "append: komunikat konkatenacją": ("assert_sonda.py", {"asercja": 'errors.append("x" + STALA)  # tu'}),
    "append: komunikat wywołaniem": ("assert_sonda.py", {"asercja": 'errors.append("x {}".format(1))  # tu'}),
    "errors: podany metodzie": ("assert_sonda.py", {"asercja": "STALA.count(errors)  # tu"}),
    "errors: podany funkcji spoza skryptu i wspólnego modułu": ("assert_sonda.py", {"asercja": "print(errors)  # tu"}),
    "errors: podany funkcji wspólnego modułu, której nie ma": ("assert_sonda.py", {"asercja": "from wynik_uruchomienia import brak\n    brak(errors)  # tu"}),
    "errors: na pozycji innego parametru": ("assert_sonda.py", {"asercja": "_dwa(errors, [])  # tu"}),
    "errors: parametrem o innej nazwie": ("assert_sonda.py", {"asercja": "_dwa([], inne=errors)  # tu"}),
    "errors: dwa razy": ("assert_sonda.py", {"asercja": "_dwa(errors, errors)  # tu"}),
    "errors: w lambdzie": ("assert_sonda.py", {"asercja": '(lambda: errors.append("x"))()  # tu'}),
    "errors: w funkcji zagnieżdżonej": ("assert_sonda.py", {"asercja": 'def _w() -> None:\n        errors.append("x")  # tu'}),
    "finish: komunikat zmienną": ("assert_sonda.py", {"asercja": "tekst = STALA\n    finish(errors, tekst)  # tu"}),
    "main: return kodu bez print": ("assert_sonda.py", {"asercja": "return 1  # tu"}),
    "main: return wyrażenia": ("assert_sonda.py", {"asercja": "return len(errors)  # tu"}),
    "main: print i return stałej spoza liczb": ("assert_sonda.py", {"asercja": 'print("x")\n    return STALA  # tu'}),
    "main: print komunikatu zmienną i return": ("assert_sonda.py", {"asercja": "tekst = STALA\n    print(tekst)\n    return 1  # tu"}),
    "wyjście: sys.exit": ("assert_sonda.py", {"asercja": 'sys.exit("x")  # tu'}),
    "wyjście: exit": ("assert_sonda.py", {"asercja": "exit(1)  # tu"}),
    "wyjście: os._exit": ("assert_sonda.py", {"asercja": "os._exit(1)  # tu"}),
    "wyjście: raise SystemExit": ("assert_sonda.py", {"asercja": "raise SystemExit(1)  # tu"}),
    "raise: bez try": ("assert_sonda.py", {"asercja": 'raise ValueError("x")  # tu'}),
    "raise: wyjątek spoza złapanych": ("assert_sonda.py", {"asercja": 'try:\n        raise KeyError("x")  # tu\n    except ValueError:\n        pass'}),
    "raise: ponowny w obsłudze": ("assert_sonda.py", {"asercja": "try:\n        pass\n    except ValueError:\n        raise  # tu"}),
    "raise: SystemExit złapany przez BaseException": ("assert_sonda.py", {"asercja": "try:\n        raise SystemExit(1)  # tu\n    except BaseException:\n        pass"}),
    "assert: bez komunikatu": ("assert_sonda.py", {"asercja": "assert STALA  # tu"}),
    "assert: komunikat wywołaniem": ("assert_sonda.py", {"asercja": "assert STALA, STALA.upper()  # tu"}),
    "instrukcja złożona: match": ("assert_sonda.py", {"asercja": "match STALA:  # tu\n        case _:\n            pass"}),
    "errors: atrybut obiektu": ("assert_sonda.py", {"asercja": 'STALA.errors.append("x")  # tu'}),
    "wspólny moduł: extend": (
        "wynik_uruchomienia.py",
        {"wspolny": WSPOLNY_SONDY.replace('errors.append(f"{path} nie ma rekordu")', 'errors.extend([path])  # tu')},
    ),
}
# Postać → (plik, zamiany (stary tekst, nowy) w pliku sondy) dla miejsca poza wstawką.
ODMOWY_MODULU_ROZLICZEN: Final = {
    "proces bez nazwy literałem": ("run_verification.py", (('SONDA = WorkflowProcess("sonda", _sonda_workflow)', "SONDA = WorkflowProcess(Path.name, _sonda_workflow)  # tu"),)),
    "workflow spoza modułu": ("run_verification.py", (('SONDA = WorkflowProcess("sonda", _sonda_workflow)', 'SONDA = WorkflowProcess("sonda", Path.cwd)  # tu'),)),
    "funkcja bez procesu": ("run_verification.py", (('SONDA = WorkflowProcess("sonda", _sonda_workflow)', 'SONDA = WorkflowProcess("inna", _sonda_workflow)'),)),
    "wariant z polem": ("run_verification.py", (('"druga": WorkflowVariant(SONDA)}', '"druga": WorkflowVariant(SONDA, run_exit=1)}  # tu'),)),
    "wariant nie wywołaniem": ("run_verification.py", (('"druga": WorkflowVariant(SONDA)}', '"druga": SONDA}  # tu'),)),
    "workflow bez kroku": (
        "run_verification.py",
        (
            (
                WORKFLOW[WORKFLOW.index("def _sonda_workflow") : WORKFLOW.index("\n\n\nSONDA")].replace("{wstawka}", "pass"),
                "def _sonda_workflow() -> None:  # tu\n    pass",
            ),
        ),
    ),
    "errors podany funkcji innego modułu o nazwie z modułu wspólnego": (
        "assert_sonda.py",
        (
            ("from wynik_uruchomienia import check_metrics, finish", "from inny import check_metrics\nfrom wynik_uruchomienia import finish"),
            ('    check_metrics("metrics.jsonl", errors=errors)\n', '    check_metrics("metrics.jsonl", errors=errors)  # tu\n'),
        ),
    ),
    "wyjście: sys.exit w funkcji skryptu": ("assert_sonda.py", (('    errors.append("pierwszy")', '    errors.append("pierwszy")\n    sys.exit(1)  # tu'),)),
    "raise: w funkcji skryptu bez try w main": ("assert_sonda.py", (('    errors.append("pierwszy")', '    raise ValueError("x")  # tu'),)),
    "warunek z samego literału, którego polecenie nie rozstrzyga": (
        "assert_sonda.py",
        (
            ("def main() -> int:", 'def _tryb(errors: list[str], tryb: str = "a") -> None:\n    if tryb.startswith("a"):  # tu\n        errors.append("tryb")\n\n\ndef main() -> int:'),
            ("    _check(errors)\n", "    _check(errors)\n    _tryb(errors)\n"),
        ),
    ),
    "errors na poziomie modułu": ("assert_sonda.py", (('STALA = "stała"', 'STALA = "stała"\nerrors: list[str] = []  # tu'),)),
    "errors w bloku __main__": ("assert_sonda.py", (("    return finish(errors, \"ASSERT OK | sonda=true\")\n", "    return finish(errors, \"ASSERT OK | sonda=true\")\n\n\nif __name__ == \"__main__\":  # tu\n    errors = []\n    raise SystemExit(main())\n"),)),
    "errors w metodzie klasy": ("assert_sonda.py", (('STALA = "stała"', 'STALA = "stała"\n\n\nclass _Zbior:\n    def dodaj(self, errors: list[str]) -> None:  # tu\n        errors.append("x")'),)),
    "kod modułu poza funkcją": ("assert_sonda.py", (('STALA = "stała"', 'STALA = "stała"\nprint(STALA)  # tu'),)),
    "funkcja z errors, do której main nie dochodzi": ("assert_sonda.py", (("def _check(errors", "def _osobna(errors: list[str]) -> None:  # tu\n    errors.append(\"x\")\n\n\ndef _check(errors"),)),
    "errors przypisane w funkcji skryptu": ("assert_sonda.py", (('    errors.append("pierwszy")', '    errors = []  # tu\n    errors.append("pierwszy")'),)),
    "errors przypisane w main poza pierwszym poziomem": ("assert_sonda.py", (("    errors: list[str] = []\n", "    if STALA:\n        errors: list[str] = []  # tu\n"),)),
}


def _odmowa_rozliczen(opis: str) -> tuple[str, dict[str, str]]:
    if opis in ODMOWY_ROZLICZEN:
        plik, wstawki = ODMOWY_ROZLICZEN[opis]
        return plik, _sonda(**wstawki)
    plik, zamiany = ODMOWY_MODULU_ROZLICZEN[opis]
    pliki = _sonda()
    for stary, nowy in zamiany:
        assert pliki[plik].count(stary) == 1, (opis, stary)
        pliki[plik] = pliki[plik].replace(stary, nowy)
    if opis == "funkcja bez procesu":
        pliki[plik] = "# tu\n" + pliki[plik]
    return plik, pliki


@pytest.mark.parametrize("opis", [*ODMOWY_ROZLICZEN, *ODMOWY_MODULU_ROZLICZEN])
def test_polecenie_mapy_rozliczen_odmawia_postaci_ktorej_nie_czyta_z_plikiem_i_linia(
    polecenie_rozliczen: ModuleType, opis: str
) -> None:
    """Krok albo sprawdzenie w postaci spoza tych, które polecenie czyta, czerwieni je zdaniem z plikiem i linią, zamiast
    zgubić je z sekcji mapy po cichu (#1630)."""

    plik, pliki = _odmowa_rozliczen(opis)
    linia = next(numer for numer, tekst in enumerate(pliki[plik].splitlines(), start=1) if "# tu" in tekst)

    with pytest.raises(polecenie_rozliczen.Unreadable) as odmowa:
        polecenie_rozliczen.sub_features("sonda", pliki.__getitem__)

    assert str(odmowa.value).startswith(f"{plik}:{linia}: "), str(odmowa.value)


# Znane luki polecenia mapy rozliczeń (tests/fixtures/znane_luki.py): opis postaci → (plik sondy, jego tekst) z krokiem
# albo sprawdzeniem „LUKA”, którego sekcja nie pokazuje, choć skill go wykonuje, a próbka przechodzi przez ruff
# z konfiguracją scripts/ skilla i przez polecenie.
ZNANE_LUKI_ROZLICZEN: Final = {
    "sprawdzenie pod inną nazwą listy: polecenie zna tylko nazwę errors": (
        "assert_sonda.py",
        ASSERT_SONDY.replace("{wstawka}", 'znalezione = errors\n    znalezione.append("LUKA")'),
    ),
    "krok bez _run_step: polecenie zna tylko dwie funkcje kroków": (
        "run_verification.py",
        WORKFLOW.replace("{wstawka}", 'subprocess.run(["LUKA"], check=True)').replace(
            "from pathlib import Path\n", "from pathlib import Path\nimport subprocess\n"
        ),
    ),
    "wyjątek z funkcji innego modułu: polecenie zna tylko jawne raise w skrypcie i we wspólnym module": (
        "assert_sonda.py",
        ASSERT_SONDY.replace("{wstawka}", 'int("LUKA")'),
    ),
    "wyjście w kodzie modułu: polecenie czyta tylko funkcje, do których dochodzi main": (
        "assert_sonda.py",
        ASSERT_SONDY.replace("{wstawka}", "pass").replace('STALA = "stała"', 'STALA = "stała"\nKOD = sys.exit("LUKA")').replace(
            "from wynik_uruchomienia", "import sys\n\nfrom wynik_uruchomienia"
        ),
    ),
    "krok przez odbicie po nazwie": (
        "run_verification.py",
        WORKFLOW.replace("{wstawka}", f'getattr(sys.modules[__name__], "_run_step")("LUKA", [{ZAPIS}], expected_exit=0)').replace(
            "from pathlib import Path\n", "from pathlib import Path\nimport sys\n"
        ),
    ),
}


@wymaga_ruff
def test_znane_luki_polecenia_mapy_rozliczen_przechodza_przez_kazdy_jego_mechanizm(
    polecenie_rozliczen: ModuleType, tmp_path: Path
) -> None:
    pliki = zapisz({opis: tekst for opis, (_, tekst) in ZNANE_LUKI_ROZLICZEN.items()}, tmp_path)
    zgloszenia = ruff(pliki, sonda=WORKFLOW_SUB_FEATURES.parent / "sonda_luki.py")
    for opis, (nazwa, _) in ZNANE_LUKI_ROZLICZEN.items():
        sonda = {**_sonda(), nazwa: pliki[opis].read_text(encoding="utf-8")}
        try:
            _, kroki = polecenie_rozliczen.sub_features("sonda", sonda.__getitem__)
        except polecenie_rozliczen.Unreadable as odmowa:
            zgloszenia[opis].append(f"workflow_sub_features.py: {odmowa}")
        else:
            if any("LUKA" in tekst for krok in kroki for tekst in [krok.name, *krok.checks]):
                zgloszenia[opis].append("workflow_sub_features.py: czyta lukę")

    assert_znane_luki(zgloszenia, "tests/test_mapy_funkcji.py")


# Skrypt asercji i wspólny moduł, które naprawdę biegną: każde słowo z BIEG_WYZWALACZE w argv wywraca krok jedną drogą.
BIEG_ASERCJA: Final = """\
import sys

from wynik_uruchomienia import check_metrics, finish, load_result

STALA = "stała"


def _arkusz(tryb: str = "zwykły") -> None:
    if tryb == "ścisły":
        raise KeyError("nigdy")
    if "arkusz" in sys.argv:
        raise IndexError("arkusz")


def _sprawdz(errors: list[str], tryb: str) -> None:
    if "pierwszy" in sys.argv:
        errors.append("pierwszy")
    if tryb != "zwykły":
        errors.append(f"tryb {tryb}")
    _arkusz()


def main() -> int:
    errors: list[str] = []
    try:
        _sprawdz(errors, "zwykły")
        load_result(f"{STALA}.json", errors)
        check_metrics("metrics.jsonl", errors=errors)
    except LookupError as exc:
        print(f"ARKUSZ FAIL: {exc}", file=sys.stderr)
        return 2
    assert "asercja" not in sys.argv, "asercja przerwana"
    return finish(errors, f"ASSERT OK | {STALA}")


if __name__ == "__main__":
    raise SystemExit(main())
"""
BIEG_WSPOLNY: Final = """\
import sys


def load_result(path: str, errors: list[str], *, naming: tuple[str, ...] = ()) -> None:
    for name in naming:
        errors.append(f"{name} nazwany")
    if "wynik" in sys.argv:
        errors.append(f"{path} bez wyniku")


def check_metrics(path: str, *, errors: list[str]) -> None:
    if "metryki" in sys.argv:
        errors.append(f"{path} bez rekordu")


def finish(errors: list[str], success_message: str) -> int:
    if errors:
        for error in errors:
            print(f"ASSERT FAIL: {error}", file=sys.stderr)
        return 1
    print(success_message)
    return 0
"""
BIEG_WYZWALACZE: Final = ("pierwszy", "wynik", "metryki", "arkusz", "asercja")


def test_polecenie_mapy_rozliczen_drukuje_kazda_droge_porazki_biegu_skryptu_i_tylko_je(
    polecenie_rozliczen: ModuleType, tmp_path: Path
) -> None:
    """Sekcja kroku równa się prawdziwemu biegowi skryptu: każda droga, którą bieg kończy się porażką, ma swoją linię, a
    każda linia jakąś drogę; ``raise`` czyta, gdy łapie go ``try`` także klasą bazową. Sprawdzenie, do którego krok nie dochodzi z literału argumentu albo z wartości domyślnej
    (``tryb``, ``naming``), nie stoi w sekcji (D1 r1 #1630)."""

    pliki = {**_sonda(), "assert_sonda.py": BIEG_ASERCJA, "wynik_uruchomienia.py": BIEG_WSPOLNY}
    for nazwa, tekst in pliki.items():
        (tmp_path / nazwa).write_text(tekst, encoding="utf-8")

    _, kroki = polecenie_rozliczen.sub_features("sonda", pliki.__getitem__)
    krok = next(krok for krok in kroki if krok.runs == "assert_sonda.py")
    biegi = {
        slowo: subprocess.run(
            [sys.executable, "assert_sonda.py", *([slowo] if slowo else [])],
            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
        )
        for slowo in ("", *BIEG_WYZWALACZE)
    }
    wzory = {
        linia: re.compile(f"(?:^|: ){re.escape(linia).replace(re.escape('…'), '.+')}$") for linia in krok.checks
    }
    nieopisane = [
        f"{slowo}: kod {bieg.returncode}, {bieg.stderr.strip().splitlines()[-1:]}"
        for slowo, bieg in biegi.items()
        if slowo
        and not (bieg.returncode != 0 and any(wzor.search(linia) for wzor in wzory.values() for linia in bieg.stderr.splitlines()))
    ]
    bez_biegu = [
        linia
        for linia, wzor in wzory.items()
        if not any(wzor.search(wiersz) for bieg in biegi.values() for wiersz in bieg.stderr.splitlines())
    ]

    assert krok.checks == ["pierwszy", "… bez wyniku", "… bez rekordu", "ARKUSZ FAIL: …", "asercja przerwana"]
    assert (biegi[""].returncode, biegi[""].stdout.strip(), krok.prints) == (0, "ASSERT OK | stała", ["ASSERT OK | stała"])
    assert nieopisane == [], "bieg kończy się porażką drogą, której sekcja nie ma"
    assert bez_biegu == [], "sekcja ma drogę porażki, której żaden bieg nie przechodzi"
