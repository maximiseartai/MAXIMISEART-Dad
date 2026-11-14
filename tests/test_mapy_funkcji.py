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

from tests.fixtures.znane_luki import assert_znane_luki, ruff, wymaga_ruff, zapisz

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
# razy i kiedy krok pomocnika biegnie, a nie widzi tego na liście postaci (mechanizm: tylko jedno wywołanie poza pętlą
# i warunkiem). Linia odmowy ma komentarz `# tu`.
ODMOWY_POMOCNIKA: Final = {
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


# Miejsce w ciele drive(), w którym pomocnik biegnie raz, gdy biegnie drive(): polecenie drukuje jego sprawdzenie raz,
# tam, gdzie wywołanie się kończy. Wstawka woła _pomocnik z POMOCNIK.
CZYTANE_MIEJSCA: Final = {
    "instrukcja": "_pomocnik(run)",
    "przypisanie": "wynik = _pomocnik(run)",
    "ciało with": "with open(__file__, encoding='utf-8'):\n        _pomocnik(run)",
    "ciało try": "try:\n        _pomocnik(run)\n    except ValueError:\n        pass",
    "finally": "try:\n        pass\n    finally:\n        _pomocnik(run)",
    "iterowane pętli for": "for _ in [_pomocnik(run)]:\n        pass",
    "warunek if": "if _pomocnik(run):\n        pass",
    "warunek wyrażenia warunkowego": "None if _pomocnik(run) else None",
    "pierwszy argument or": "_pomocnik(run) or None",
    "przedmiot match": "match _pomocnik(run):\n        case _:\n            pass",
    "warunek assert": "assert _pomocnik(run) is None",
}


@pytest.mark.parametrize("opis", list(CZYTANE_MIEJSCA))
def test_polecenie_podfunkcji_czyta_pomocnika_wolanego_raz_w_miejscu_ktore_biegnie_raz(polecenie: ModuleType, opis: str) -> None:
    czytane = polecenie.sub_features(NAPED.format(wstawka=CZYTANE_MIEJSCA[opis]) + POMOCNIK, "sonda.py")

    assert czytane == [("sonda-krok", ["pierwszy", "z pomocnika"])]


def test_polecenie_podfunkcji_drukuje_kroki_pomocnika_w_kolejnosci_w_ktorej_biegna(polecenie: ModuleType) -> None:
    """Kroki i sprawdzenia pomocnika stoją tam, gdzie drive() go woła, a pomocnik w argumencie sprawdzenia biegnie przed
    nim; pomocnik bez run.step i run.check może stać gdziekolwiek i ile razy."""

    zrodlo = NAPED.format(
        wstawka="\n    ".join(
            [
                "_pomocnik(run, page)",
                'run.check(_sprawdz(run), "po sprawdzeniu")',
                "for _ in range(2):\n        _bez_krokow(run)",
                "_bez_krokow(run)",
                'run.step(feature, "sonda-ostatni")',
            ]
        )
    ) + "".join(
        [
            "\n\ndef _pomocnik(run: Run, page: object) -> None:\n"
            '    run.check(True, SHOW_ALL)\n    run.step("sonda", "sonda-pomocnik")\n    run.check(True, f"w {SHOW_ALL}")\n',
            '\n\ndef _sprawdz(run: Run) -> bool:\n    run.check(True, "w sprawdzeniu")\n    return True\n',
            "\n\ndef _bez_krokow(run: Run) -> None:\n    pass\n",
        ]
    )

    assert polecenie.sub_features(zrodlo, "sonda.py") == [
        ("sonda-krok", ["pierwszy", "Pokaż wszystkie"]),
        ("sonda-pomocnik", ["w Pokaż wszystkie", "w sprawdzeniu", "po sprawdzeniu"]),
        ("sonda-ostatni", []),
    ]


# Znane luki polecenia podfunkcji (tests/fixtures/znane_luki.py): opis postaci → (napęd, ile razy jego bieg drukuje
# komunikat LUKA; None, gdy drukuje kroki innego modułu). Każdy przechodzi przez ruff z konfiguracją drive/ i przez
# polecenie, a sekcja drukuje LUKA inną liczbę razy niż bieg. Polecenie odmawia każdego atrybutu .step/.check poza
# tymi, które czyta, i każdego użycia nazwy pomocnika poza jednym wywołaniem w drive(), więc te postacie sięgają po
# check bez atrybutu, po pomocnika bez jego nazwy, po funkcję innego modułu albo omijają wywołanie przepływem drive().
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
    "zna pętlę i warunek wokół wywołania, nie przepływ drive(): po return": (
        NAPED.format(wstawka='if feature == "sonda":\n        return\n    sprawdz(run)') + POMOCNIK_LUKI,
        0,
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
