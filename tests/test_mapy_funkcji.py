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
from typing import Any, Final

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
DRIVE_CENTRUM = CENTRUM / "scripts" / "drive_centrum.py"


def _sub_features(feature: str, polecenie: Path) -> str:
    done = subprocess.run(
        [sys.executable, str(polecenie), "--feature", feature], capture_output=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")
    return done.stdout.decode("utf-8")


@pytest.fixture
def naped(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(DRIVE_CENTRUM.parent))
    spec = importlib.util.spec_from_file_location("drive_centrum", DRIVE_CENTRUM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "drive_centrum", module)
    spec.loader.exec_module(module)
    return module


def test_kazdy_plik_funkcji_centrum_ma_sekcje_z_biegu() -> None:
    """Bieg porównuje sekcję ``## Sub-features`` każdej funkcji, którą jedzie, z jej plikiem, więc każdy plik funkcji ma
    sekcję z biegu (jej pierwsze zdanie), także nowej funkcji: listy funkcji bez porównania nie ma."""

    bez_sekcji = [
        f"verify-centrum-rozliczen/features/{path.name} nie ma sekcji ## Sub-features z biegu: wstaw ją z dowodu biegu "
        f"`run_centrum_verification.py --feature {path.stem}` (sekcje-z-biegu/{path.stem}.md)"
        for path in _feature_files(CENTRUM)
        if f"Printed by `scripts/sub_features.py --feature {path.stem}`" not in path.read_text(encoding="utf-8")
    ]

    assert bez_sekcji == [], "\n".join(bez_sekcji)


def _naped_funkcji(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, funkcja: str, zrodlo: str) -> ModuleType:
    """Napęd funkcji ``funkcja`` z ``zrodlo``, zaimportowany pod nazwą jej modułu zamiast prawdziwego."""

    if "from drive.common import sprawdz_wspolne" in zrodlo:
        _naped_funkcji(monkeypatch, tmp_path, "common", WSPOLNY_POMOCNIK)
    plik = tmp_path / f"{funkcja}.py"
    plik.write_text(zrodlo, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("drive." + funkcja.replace("-", "_"), plik)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _bieg(naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, napedy: dict[str, ModuleType], funkcje: list[str]) -> dict[str, Any]:
    """Sekcje z biegu ``funkcje`` po kolei (``drive_centrum.Section``), jak ``drive_centrum.main``, z napędami
    ``napedy`` zamiast prawdziwych."""

    for funkcja, modul_napedu in napedy.items():
        monkeypatch.setitem(naped.MODULES, funkcja, modul_napedu)
    korzen = tmp_path / f"bieg-{len(list(tmp_path.glob('bieg-*')))}"
    korzen.mkdir()
    (korzen / "fixture.json").write_text("{}", encoding="utf-8")
    run = naped.Run(korzen, "http://127.0.0.1:1", korzen / "dowod")
    driven: list[str] = []
    owners: list[str] = []
    for funkcja in funkcje:
        if funkcja not in driven:
            naped.drive(run, None, funkcja, driven, {}, owners)
    sekcje: dict[str, Any] = naped.sections(run.calls, owners, driven)
    return sekcje


NAPED_PROBY: Final = '''\
KOMUNIKAT = "ze stałej"


from drive.common import sprawdz_wspolne


def wspolne(run):
    run.check(True, "wspólne")


def krok(run, nazwa):
    run.step("okno-ustawien", nazwa)


def drive(run, page):
    krok(run, "pierwszy")
    for numer in range(2):
        run.check(True, f"obrót {numer} {KOMUNIKAT}")
        wspolne(run)
        sprawdz_wspolne(run)
    run.check(True, f"{page}")
    krok(run, "drugi")
    wspolne(run)
'''
# Wspólny pomocnik napędu (drive/common.py) ze sprawdzeniem, które nie należy do sekcji żadnej funkcji.
WSPOLNY_POMOCNIK: Final = '''\
def sprawdz_wspolne(run):
    run.check(True, "ze wspólnego pomocnika")
'''
SEKCJA_PROBY: Final = """\
## Sub-features

Printed by `scripts/sub_features.py --feature okno-ustawien` from the drive's steps and checks; refresh the section with it.

- `pierwszy`: obrót … ze stałej; wspólne; ….
- `drugi`: wspólne.
"""


@pytest.mark.parametrize("rozni_sie", [False, True], ids=["sekcja-jak-plik", "sekcja-inna-niz-plik"])
def test_bieg_konczy_sie_drive_fail_gdy_sekcja_z_biegu_rozni_sie_od_pliku_mapy(
    naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], rozni_sie: bool
) -> None:
    """Sekcja z biegu to kroki napędu, każdy raz na miejsce i nazwę z biegu (pomocnik woła tu ``run.step`` z nazwą z
    parametru), a pod każdym miejsca sprawdzeń, które przebiegły pod nim, każde raz, w kolejności pierwszego wywołania,
    z komunikatem z wywołania w kodzie; sprawdzenia wspólnego pomocnika z ``drive/common.py`` są policzone poza sekcją.
    Sekcja i to, co poza nią, trafia do dowodu, a bieg kończy się porażką z różnicą, gdy plik mapy ma inną sekcję."""

    mapa = tmp_path / "features"
    mapa.mkdir()
    w_pliku = SEKCJA_PROBY.replace("- `drugi`: wspólne.", "- `drugi`: stare.") if rozni_sie else SEKCJA_PROBY
    (mapa / "okno-ustawien.md").write_text(f"# Okno\n\n{w_pliku}\n## How to get to it (user POV)\n", encoding="utf-8")
    monkeypatch.setattr(naped, "FEATURE_FILES", mapa)
    sekcje = _bieg(naped, monkeypatch, tmp_path, {"okno-ustawien": _naped_funkcji(monkeypatch, tmp_path, "okno-ustawien", NAPED_PROBY)}, ["okno-ustawien"])

    try:
        naped.compare(tmp_path / "bieg-0" / "dowod", sekcje)
    except naped.DriveFailure as porazka:
        wynik = ("porażka", str(porazka).startswith("the section Sub-features of okno-ustawien"), "-- `drugi`: stare." in capsys.readouterr().err)
    else:
        wynik = ("bez porażki", False, False)

    assert sekcje == {"okno-ustawien": (SEKCJA_PROBY, {"a helper the drives share (drive.common)": 2})}
    assert (tmp_path / "bieg-0" / "dowod" / "sekcje-z-biegu" / "poza-sekcja.txt").read_text(encoding="utf-8") == (
        "okno-ustawien | a helper the drives share (drive.common) | 2\n"
    )
    assert (tmp_path / "bieg-0" / "dowod" / "sekcje-z-biegu" / "okno-ustawien.md").read_bytes() == SEKCJA_PROBY.encode("utf-8")
    assert wynik == (("porażka", True, True) if rozni_sie else ("bez porażki", False, False))


def test_sekcja_z_biegu_jest_ta_sama_gdy_ramka_nazywa_plik_sciezka_windows(
    naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Na Windows ramka napędu nazywa swój plik ścieżką z literą dysku i ``\\``; sekcja bierze kod z zaimportowanego
    modułu, nie ze ścieżki ramki, więc jest ta sama na każdym systemie, a ten test pada bez Windows (#1804 r2)."""

    modul_napedu = _naped_funkcji(monkeypatch, tmp_path, "okno-ustawien", NAPED_PROBY)
    modul_napedu.drive.__code__ = modul_napedu.drive.__code__.replace(co_filename=r"C:\a\drive\okno_ustawien.py")

    na_windows = _bieg(naped, monkeypatch, tmp_path, {"okno-ustawien": modul_napedu}, ["okno-ustawien"])

    assert na_windows["okno-ustawien"].text == SEKCJA_PROBY


WSPOLNY_Z_KROKIEM: Final = '''\
def krok_wspolny(run, funkcja):
    run.step(funkcja, "ze-wspolnego")
'''
NAPED_Z_KROKIEM_ZE_WSPOLNEGO: Final = '''\
from drive.common import krok_wspolny


def drive(run, page):
    run.step("okno-ustawien", "pierwszy")
    krok_wspolny(run, "okno-ustawien")
    run.check(True, "po kroku ze wspólnego")
'''


def test_krok_ze_wspolnego_pomocnika_jest_krokiem_sekcji(
    naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kroki sekcji to linie ``STEP`` funkcji, z którego modułu by nie biegły: krok ze wspólnego pomocnika
    ``drive/common.py`` jest w sekcji, a sprawdzenie po nim pod nim (sonda #1845 r2)."""

    _naped_funkcji(monkeypatch, tmp_path, "common", WSPOLNY_Z_KROKIEM)
    okno = _naped_funkcji(monkeypatch, tmp_path, "okno-ustawien", NAPED_Z_KROKIEM_ZE_WSPOLNEGO)

    sekcje = _bieg(naped, monkeypatch, tmp_path, {"okno-ustawien": okno}, ["okno-ustawien"])

    assert [linia for linia in capsys.readouterr().out.splitlines() if linia.startswith("STEP")] == [
        "STEP okno-ustawien | pierwszy",
        "STEP okno-ustawien | ze-wspolnego",
    ]
    assert sekcje["okno-ustawien"].text.endswith("\n- `pierwszy`.\n- `ze-wspolnego`: po kroku ze wspólnego.\n")


NAPED_UZUPELNIENIA: Final = '''\
def z_przygotowania(run, page):
    run.step("uzupelnienie", "wynik")
    run.check(True, "karta wyniku")


def drive(run, page):
    run.step("uzupelnienie", "wlasny")
'''
NAPED_Z_KROKIEM_UZUPELNIENIA: Final = '''\
from drive.uzupelnienie import z_przygotowania


def drive(run, page):
    run.step("{funkcja}", "przed")
    z_przygotowania(run, page)
    run.step("{funkcja}", "po")
'''


@pytest.mark.parametrize(
    "funkcje",
    [["uzupelnienie"], ["przygotowanie-pliku-zbiorczego", "uzupelnienie"], ["okno-ustawien", "przygotowanie-pliku-zbiorczego", "uzupelnienie"]],
    ids=["sama", "po-potrzebnej", "w-srodku-czesci"],
)
def test_kroki_funkcji_z_napedu_innej_naleza_do_niej_przy_kazdym_podziale(
    naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, funkcje: list[str]
) -> None:
    """Krok, który napęd Przygotowania woła z modułu Uzupełnienia, należy do funkcji z ``run.step``: Uzupełnienie
    potrzebuje Przygotowania, więc dostaje ten krok pierwszy, bez względu na to, które funkcje jego część CI jedzie."""

    przygotowanie = "przygotowanie-pliku-zbiorczego"
    napedy = {
        "uzupelnienie": _naped_funkcji(monkeypatch, tmp_path, "uzupelnienie", NAPED_UZUPELNIENIA),
        przygotowanie: _naped_funkcji(monkeypatch, tmp_path, przygotowanie, NAPED_Z_KROKIEM_UZUPELNIENIA.format(funkcja=przygotowanie)),
        "okno-ustawien": _naped_funkcji(monkeypatch, tmp_path, "okno-ustawien", NAPED_PROBY),
    }

    sekcje = _bieg(naped, monkeypatch, tmp_path, napedy, funkcje)

    assert sekcje["uzupelnienie"].text.endswith("\n- `wynik`: karta wyniku.\n- `wlasny`.\n")
    assert sekcje[przygotowanie].text.endswith("\n- `przed`.\n- `po`.\n")


def test_krok_funkcji_z_napedu_potrzebnej_posrednio_nalezy_do_niej(
    naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Logi Uruchomienia potrzebują Przebiegu rozliczeń, a ten Przygotowania, więc krok Logów z napędu Przygotowania
    biegnie zawsze przed nimi i należy do ich sekcji: potrzeba jest przechodnia."""

    napedy = {
        "logi-uruchomienia": _naped_funkcji(
            monkeypatch, tmp_path, "logi-uruchomienia", NAPED_UZUPELNIENIA.replace('"uzupelnienie"', '"logi-uruchomienia"')
        ),
        "przebieg-rozliczen": _naped_funkcji(monkeypatch, tmp_path, "przebieg-rozliczen", 'def drive(run, page):\n    run.step("przebieg-rozliczen", "jeden")\n'),
        "przygotowanie-pliku-zbiorczego": _naped_funkcji(
            monkeypatch,
            tmp_path,
            "przygotowanie-pliku-zbiorczego",
            NAPED_Z_KROKIEM_UZUPELNIENIA.format(funkcja="przygotowanie-pliku-zbiorczego").replace("drive.uzupelnienie", "drive.logi_uruchomienia"),
        ),
    }

    sekcje = _bieg(naped, monkeypatch, tmp_path, napedy, ["logi-uruchomienia"])

    assert sekcje["logi-uruchomienia"].text.endswith("\n- `wynik`: karta wyniku.\n- `wlasny`.\n")


@pytest.mark.parametrize(
    ("zrodlo", "odmowa"),
    [
        (NAPED_PROBY.replace('    krok(run, "pierwszy")\n', '    run.check(True, "przed krokiem")\n    krok(run, "pierwszy")\n'),
         "run.check before the first run.step of the drive of okno-ustawien"),
        (NAPED_PROBY.replace('run.check(True, f"{page}")', "run.check(True, page)"), "the message of this run.check cannot be printed"),
        (NAPED_Z_KROKIEM_UZUPELNIENIA.format(funkcja="okno-ustawien"), "the drive of okno-ustawien runs a step of uzupelnienie, which does not need okno-ustawien"),
    ],
    ids=["sprawdzenie-przed-krokiem", "komunikat-bez-wydruku", "krok-funkcji-ktora-go-nie-potrzebuje"],
)
def test_bieg_odmawia_sekcji_ktora_zalezy_od_funkcji_przed_nia_w_czesci_ci(
    naped: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, zrodlo: str, odmowa: str
) -> None:
    """Bieg odmawia sekcji, która zależy od funkcji przejechanych przed nią w tym samym biegu (sprawdzenia przed
    pierwszym krokiem napędu i kroku funkcji z napędu innej, której ta nie potrzebuje), i sprawdzenia, którego komunikatu
    mapa nie wydrukuje."""

    przygotowanie = "przygotowanie-pliku-zbiorczego"
    napedy = {
        "uzupelnienie": _naped_funkcji(monkeypatch, tmp_path, "uzupelnienie", NAPED_UZUPELNIENIA),
        przygotowanie: _naped_funkcji(monkeypatch, tmp_path, przygotowanie, NAPED_Z_KROKIEM_UZUPELNIENIA.format(funkcja=przygotowanie)),
        "okno-ustawien": _naped_funkcji(monkeypatch, tmp_path, "okno-ustawien", zrodlo),
    }

    with pytest.raises(naped.DriveFailure, match=re.escape(odmowa)):
        _bieg(naped, monkeypatch, tmp_path, napedy, [przygotowanie, "okno-ustawien"])


# Znane luki porównania sekcji z biegu (tests/fixtures/znane_luki.py): klasa mechanizmu → funkcja z sekcją z biegu w
# pliku mapy, której sekcji CI nie porównuje; puszczona przez wybór funkcji, które CI jedzie (`--feature all`).
ZNANE_LUKI_SEKCJI: Final = {
    "porównuje tylko funkcje, które bieg jedzie, a CI jedzie `all`: pomiar poza `all`": "wydajnosc",
}


def test_znane_luki_porownania_sekcji_z_biegu_przechodza_przez_wybor_funkcji_ci(naped: ModuleType) -> None:
    zgloszenia = {
        opis: [f"CI jedzie {funkcja} w --feature all i porównuje jej sekcję"] if funkcja in naped.ALL else []
        for opis, funkcja in ZNANE_LUKI_SEKCJI.items()
    }

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
