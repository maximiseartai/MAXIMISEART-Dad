"""Rozjazd modelu skilla z kodem (``tools/lib/rozjazd_modelu.py``): jedno miejsce decyzji dla skryptów skilli i szybko.

Kod opisany modelem leży w ``model/definicje.json`` skilla: plik w całości albo definicje po ścieżce od modułu, każda ze
skrótem z chwili, gdy model ją opisywał. Rozjazd to kod inny niż w tych skrótach albo plik definicji w innej postaci,
bo wtedy model nie jest porównany z kodem. Porównanie nie pyta gita, więc rebase, cherry-pick i squash gałęzi, która
definicji nie zmienia, rozjazdu nie dają (#1060). Skróty przelicza ``tools/przesun_model.py``. Testy biegną na
repozytoriach testu, poza testem kluczy funkcji z tabeli modelu, który czyta skille tego repozytorium.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Final

import pytest

from tests.fixtures.git_repo import commit, git

import przesun_model
import rozjazd_modelu

ROOT = Path(__file__).resolve().parents[1]

SKILL = ".agents/skills/verify-model"
CODE = "src/pakiet/kod.py"
WHOLE = "src/pakiet/caly.py"
# ``zapisz`` w ``obok``, ``Logi.zamknij`` przed ``Dziennik.zamknij`` z tabeli i ``kolejka`` w ``inna`` przed ``kolejka``
# w ``utworz``: definicja o tej nazwie w innym zakresie.
SOURCE = '''"""Moduł."""


def zapisz() -> int:
    """Zapisuje."""
    return 1


def obok() -> int:
    def zapisz() -> int:
        return 5

    return 2 + zapisz()


class Logi:
    def zamknij(self) -> int:
        return 4


class Dziennik:
    def zamknij(self) -> int:
        return 3


def inna() -> object:
    kolejka = set()
    return kolejka


def utworz() -> object:
    if True:
        kolejka = list()
    return kolejka


STALA: int = 7


def galezie(x: object) -> object:
    try:
        wynik = 1
    except ValueError:
        wynik = 2
    match x:
        case 0:
            wynik = 3
    return wynik
'''
NAMES = {CODE: ["zapisz", "Dziennik.zamknij", "utworz.kolejka", "STALA", "galezie.wynik"], WHOLE: [rozjazd_modelu.CALY_PLIK]}
STEPS = f"Wykonaj kroki „Bring the model in line” z {SKILL}/SKILL.md, a skróty przelicz (tools/przesun_model.py verify-model) dopiero, gdy model opisuje kod."


def _write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8", newline="")


def _skill(root: Path) -> Path:
    """Skill z modelem kodu ``NAMES`` i kod, który model opisuje: skróty przeliczone na tym kodzie."""

    for name, text in {CODE: SOURCE, WHOLE: "X = 1\n", "inny.txt": "inny\n", f"{SKILL}/SKILL.md": "Model.\n"}.items():
        _write(root, name, text)
    _write(root, f"{SKILL}/{rozjazd_modelu.DEFINICJE}", json.dumps({path: dict.fromkeys(names, "") for path, names in NAMES.items()}))
    rozjazd_modelu.przesun(root / SKILL, root)
    return root / SKILL


def _edit(root: Path, name: str, old: str, new: str) -> None:
    text = (root / name).read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    (root / name).write_text(text.replace(old, new), encoding="utf-8", newline="")


@pytest.mark.parametrize(
    ("old", "new", "changed"),
    [
        pytest.param("    return 1\n", "    return 10\n", f"{CODE} zapisz", id="cialo-definicji"),
        pytest.param('    """Zapisuje."""\n', '    """Zapisuje inaczej."""\n', f"{CODE} zapisz", id="docstring-definicji"),
        pytest.param("        return 3\n", "        return 30\n", f"{CODE} Dziennik.zamknij", id="metoda-swojej-klasy"),
        pytest.param("        kolejka = list()\n", "        kolejka = dict()\n", f"{CODE} utworz.kolejka", id="przypisanie-w-funkcji"),
        pytest.param(
            "        kolejka = list()\n    return kolejka\n",
            "        kolejka = list()\n    kolejka = tuple()\n    return kolejka\n",
            f"{CODE} utworz.kolejka",
            id="drugie-wiazanie-w-zakresie",
        ),
        pytest.param("STALA: int = 7\n", "STALA: int = 8\n", f"{CODE} STALA", id="przypisanie-z-adnotacja"),
        pytest.param("        wynik = 2\n", "        wynik = 20\n", f"{CODE} galezie.wynik", id="wiazanie-w-except"),
        pytest.param("            wynik = 3\n", "            wynik = 30\n", f"{CODE} galezie.wynik", id="wiazanie-w-case"),
        pytest.param("\ndef zapisz(", "\ndef zapisz_inaczej(", f"{CODE} zapisz", id="definicji-nie-ma"),
        pytest.param("X = 1\n", '"""Docstring."""\nX = 1\n', WHOLE, id="caly-plik"),
        pytest.param("X = 1\n", "X = 1  # komentarz\n", WHOLE, id="komentarz-w-calym-pliku"),
    ],
)
def test_zmiana_kodu_opisanego_modelem_jest_rozjazdem_z_plikiem_definicja_i_krokami_naprawy(
    tmp_path: Path, old: str, new: str, changed: str
) -> None:
    skill = _skill(tmp_path)
    _edit(tmp_path, WHOLE if changed == WHOLE else CODE, old, new)

    found = rozjazd_modelu.rozjazd(skill, tmp_path)

    assert found == f"kod opisany modelem zmienił się: {changed}. {STEPS}"


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        pytest.param(CODE, "    return 2 + zapisz()\n", "    return 20 + zapisz()\n", id="funkcja-obok"),
        pytest.param(CODE, "        return 5\n", "        return 50\n", id="funkcja-o-tej-nazwie-zagniezdzona-w-innej"),
        pytest.param(CODE, "        return 4\n", "        return 40\n", id="metoda-o-tej-nazwie-w-innej-klasie"),
        pytest.param(CODE, "    kolejka = set()\n", "    kolejka = frozenset()\n", id="przypisanie-o-tej-nazwie-w-innej-funkcji"),
        pytest.param(CODE, '"""Moduł."""\n', '"""Moduł."""\n\nPOZA = 1\n\n', id="przesuniete-linie"),
        pytest.param(CODE, "    return 1\n", "    return 1  # komentarz\n", id="komentarz-w-definicji"),
        pytest.param(WHOLE, "X = 1\n", "X = 1\r\n", id="konce-linii-windows-w-calym-pliku"),
        pytest.param("inny.txt", "inny\n", "zmieniony\n", id="plik-spoza-definicji"),
    ],
)
def test_zmiana_obok_kodu_opisanego_modelem_nie_jest_rozjazdem(tmp_path: Path, name: str, old: str, new: str) -> None:
    skill = _skill(tmp_path)
    _edit(tmp_path, name, old, new)

    assert rozjazd_modelu.rozjazd(skill, tmp_path) is None


def test_galaz_po_rebase_nie_daje_rozjazdu_w_plytkim_klonie(tmp_path: Path) -> None:
    """Przed #1060 rebase przepisywał Sync commit z ``SKILL.md``, a płytki klon CI go nie miał: rozjazd bez zmiany kodu.

    Porównanie czyta tylko pliki, a cherry-pick i squash gałęzi dają to samo drzewo co rebase, więc wystarczy rebase;
    zmianę definicji po przepisaniu gałęzi łapie ``test_zmiana_kodu_opisanego_modelem…[cialo-definicji]``."""

    origin = tmp_path / "origin"
    _skill(origin)
    git(origin, "init", "--quiet", "--initial-branch", "main")
    commit(origin, "model opisuje kod")
    git(origin, "switch", "--quiet", "--create", "zmiana")
    _edit(origin, CODE, "    return 2 + zapisz()\n", "    return 20 + zapisz()\n")
    commit(origin, "zmiana obok")
    _write(origin, "inny.txt", "na gałęzi\n")
    commit(origin, "druga zmiana")
    git(origin, "switch", "--quiet", "main")
    _write(origin, "src/pakiet/nowy.py", "Y = 1\n")
    commit(origin, "main dalej")
    git(origin, "rebase", "--quiet", "main", "zmiana")
    clone = tmp_path / "klon"
    git(tmp_path, "clone", "--quiet", "--depth", "1", "--branch", "zmiana", origin.as_uri(), str(clone))

    assert rozjazd_modelu.rozjazd(clone / SKILL, clone) is None


def test_przeliczenie_skrotow_po_zmianie_kodu_konczy_rozjazd_i_wymienia_przeliczone(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    _edit(tmp_path, CODE, "    return 1\n", "    return 10\n")
    _edit(tmp_path, WHOLE, "X = 1\n", "X = 2\n")
    before = rozjazd_modelu.rozjazd(skill, tmp_path)

    moved = rozjazd_modelu.przesun(skill, tmp_path)

    assert before == f"kod opisany modelem zmienił się: {CODE} zapisz, {WHOLE}. {STEPS}"
    assert moved == [f"{CODE} zapisz", f"{WHOLE} {rozjazd_modelu.CALY_PLIK}"]
    assert rozjazd_modelu.rozjazd(skill, tmp_path) is None


def test_przeliczenie_zapisuje_nazwe_calego_pliku_wprost_jak_pliki_definicji_w_repozytorium(tmp_path: Path) -> None:
    """Pliki definicji skilli w repozytorium mają „cały plik” wprost, a nie ``ca\\u0142y plik``: przeliczenie, które
    zapisałoby ucieczki, zmieniłoby w PR każdy plik definicji z całym plikiem, także bez zmiany jego skrótu."""

    skill = _skill(tmp_path)

    assert f'  "{WHOLE}": {{\n    "{rozjazd_modelu.CALY_PLIK}": "' in (skill / rozjazd_modelu.DEFINICJE).read_text(encoding="utf-8")


def test_przeliczenie_nie_zapisuje_skrotow_gdy_definicji_nie_ma(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    recorded = (skill / rozjazd_modelu.DEFINICJE).read_text(encoding="utf-8")
    _edit(tmp_path, CODE, "\ndef zapisz(", "\ndef zapisz_inaczej(")

    with pytest.raises(ValueError, match=f"nie ma definicji: {CODE} zapisz; popraw nazwy"):
        rozjazd_modelu.przesun(skill, tmp_path)

    assert (skill / rozjazd_modelu.DEFINICJE).read_text(encoding="utf-8") == recorded


def test_skrot_definicji_to_skrot_drzewa_bez_polozenia_i_pustych_pol_ten_sam_w_kazdym_pythonie(tmp_path: Path) -> None:
    """``ast.dump`` od Pythona 3.13 pomija puste pola, a 3.12 dodał ``type_params``: skrót z ``ast.dump`` z Maca (3.12)
    byłby w CI (3.14) rozjazdem. CI biegnie ten test na każdym Pythonie z macierzy."""

    _write(tmp_path, CODE, "def f(x):\n    return x\n")
    canonical = "FunctionDef(name='f', args=arguments(args=[arg(arg='x')]), body=[Return(value=Name(id='x', ctx=Load()))])"

    found = rozjazd_modelu.skroty({CODE: {"f": ""}}, tmp_path)

    assert found == {CODE: {"f": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[: rozjazd_modelu.DLUGOSC]}}


@pytest.mark.parametrize(
    "definitions",
    [
        pytest.param([CODE], id="lista-zamiast-obiektu"),
        pytest.param({}, id="pusty-obiekt"),
        pytest.param({CODE: ["zapisz"]}, id="lista-nazw-bez-skrotow"),
        pytest.param({CODE: rozjazd_modelu.CALY_PLIK}, id="napis-zamiast-obiektu"),
        pytest.param({CODE: {}}, id="pusty-obiekt-definicji"),
        pytest.param({CODE: {"zapisz": 1}}, id="skrot-nie-napisem"),
        pytest.param({CODE: {"": "abc"}}, id="pusta-nazwa"),
        pytest.param({CODE: {rozjazd_modelu.CALY_PLIK: "abc", "zapisz": "abc"}}, id="caly-plik-obok-definicji"),
    ],
)
def test_plik_definicji_w_innej_postaci_jest_rozjazdem(tmp_path: Path, definitions: object) -> None:
    skill = _skill(tmp_path)
    _write(tmp_path, f"{SKILL}/{rozjazd_modelu.DEFINICJE}", json.dumps(definitions))

    found = rozjazd_modelu.rozjazd(skill, tmp_path)

    assert found is not None and found.startswith(f"{SKILL}/{rozjazd_modelu.DEFINICJE}: "), found
    assert found.endswith(STEPS)


def test_plik_ktory_sie_nie_parsuje_zmienil_kazda_swoja_definicje(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    _edit(tmp_path, CODE, "def obok() -> int:", "def obok( -> int:")

    found = rozjazd_modelu.rozjazd(skill, tmp_path)

    assert found == f"kod opisany modelem zmienił się: {CODE} zapisz, {CODE} Dziennik.zamknij, {CODE} utworz.kolejka, {CODE} STALA, {CODE} galezie.wynik. {STEPS}"


def test_narzedzie_przelicza_skroty_skilla_i_drukuje_przeliczone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skill = _skill(tmp_path)
    _edit(tmp_path, CODE, "        return 3\n", "        return 30\n")

    code = przesun_model.main(["verify-model", "--root", str(tmp_path)])

    assert (code, capsys.readouterr().out.splitlines()) == (
        0,
        [f"przeliczona: {CODE} Dziennik.zamknij", "PRZESUNIĘCIE OK | verify-model | przeliczone 1"],
    )
    assert rozjazd_modelu.rozjazd(skill, tmp_path) is None


def test_narzedzie_odmawia_skillowi_bez_definicji_i_definicji_ktorej_nie_ma(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _skill(tmp_path)
    _edit(tmp_path, CODE, "\ndef zapisz(", "\ndef zapisz_inaczej(")

    unknown = przesun_model.main(["verify-inny", "--root", str(tmp_path)])
    missing = przesun_model.main(["verify-model", "--root", str(tmp_path)])

    assert (unknown, missing) == (1, 1)
    assert capsys.readouterr().out.splitlines() == [
        f"PRZESUNIĘCIE FAIL | verify-inny nie ma {rozjazd_modelu.DEFINICJE}; skille z modelem: verify-model",
        f"PRZESUNIĘCIE FAIL | nie ma definicji: {CODE} zapisz; popraw nazwy w {rozjazd_modelu.DEFINICJE}",
    ]


# Funkcje z tabeli modelu, które model pomija celowo, a wiersz tabeli to mówi: skill → wynik ``bez_klucza``.
POZA_MODELEM: Final = {
    # Wiersz ``hyperlinks.py``: „its reader `read_sheet_hyperlinks` is covered by pytest (…), not here”.
    "verify-kopia-wzorca": ["src/rozliczenia/hyperlinks.py read_sheet_hyperlinks"],
    # Wiersz ``Zapis``: pamięć starsza niż wersja 4 idzie przez ``OlderOwnEntries.upgraded``, „Left out”.
    "verify-wpisanie-raportow": ["src/rozliczenia/worker_reports/_model.py OlderOwnEntries.upgraded"],
}


def test_kazda_funkcja_z_tabeli_modelu_skilla_ma_klucz_w_definicjach_albo_model_pomija_ja_celowo() -> None:
    """Rozjazd nie widzi zmiany funkcji bez klucza: merge 7aea02f zgubił ``ReportEnteringEntry.on_request``, choć tabela
    ``verify-wpisanie-raportow`` go nazywa (#2058 r5). Równość z ``POZA_MODELEM`` każe też usunąć stamtąd funkcję, która
    dostała klucz albo zniknęła z tabeli."""

    found = {skill.name: missing for skill in rozjazd_modelu.skille(ROOT) if (missing := rozjazd_modelu.bez_klucza(skill, ROOT))}

    assert found == POZA_MODELEM, (
        f"Tabela sekcji „{rozjazd_modelu.TABELA}” w SKILL.md nazywa funkcję bez klucza w {rozjazd_modelu.DEFINICJE}, więc "
        'rozjazd modelu nie zobaczy jej zmiany. Gdy wiersz opisuje kod, dopisz ją tam ze skrótem "" i przelicz skróty '
        "(tools/przesun_model.py <skill>); gdy model pomija ją celowo i wiersz to mówi, wpisz ją do POZA_MODELEM."
    )


KLUCZE_KOD = '''"""Moduł."""

from typing import Protocol


def zapisz() -> int:
    return 1


def wspolna() -> int:
    return 2


class Logi:
    def zamknij(self) -> int:
        return 3


class Dziennik:
    def zamknij(self) -> int:
        return 4


class Protokol(Protocol):
    def zaslepka(self) -> int:
        """Zaślepka."""
        ...


STALA = 5
'''
KLUCZE_PLIKI = {
    CODE: KLUCZE_KOD,
    "src/pakiet/__init__.py": "def wejscie() -> int:\n    return 6\n\n\ndef inna() -> int:\n    return 7\n",
    "src/pakiet/drugi.py": "def wspolna() -> int:\n    return 8\n",
    WHOLE: "def cala() -> int:\n    return 9\n",
    "src/poza.py": "def poza() -> int:\n    return 10\n",
}
KLUCZE_DEFINICJE = {
    CODE: {"Logi": "", "STALA": ""},
    "src/pakiet/__init__.py": {"inna": ""},
    "src/pakiet/drugi.py": {"wspolna": ""},
    WHOLE: {rozjazd_modelu.CALY_PLIK: ""},
}


def _tabela(*spans: str) -> str:
    rows = "".join(f"| `Akcja` | `{span}` w kroku |\n" for span in spans)
    return f"# Skill\n\n{rozjazd_modelu.TABELA}\n\nModel opisuje kod.\n\n| Model action | Code |\n| --- | --- |\n{rows}\n## Run\n"


@pytest.mark.parametrize(
    ("skill_md", "missing"),
    [
        pytest.param(_tabela("zapisz"), [f"{CODE} zapisz"], id="funkcja-modulu"),
        pytest.param(_tabela("Dziennik.zamknij"), [f"{CODE} Dziennik.zamknij"], id="metoda-klasy"),
        pytest.param(_tabela("kod.zapisz"), [f"{CODE} zapisz"], id="z-modulem-z-przodu"),
        pytest.param(_tabela("pakiet.wejscie"), ["src/pakiet/__init__.py wejscie"], id="z-pakietem-z-przodu"),
        pytest.param(_tabela("zapisz(...)"), [f"{CODE} zapisz"], id="z-wywolaniem"),
        pytest.param(
            _tabela("zapisz()", "Dziennik.zamknij", "zapisz"), [f"{CODE} zapisz", f"{CODE} Dziennik.zamknij"], id="w-kolejnosci-tabeli-raz"
        ),
        pytest.param(_tabela("Logi.zamknij"), [], id="metoda-klasy-z-kluczem"),
        pytest.param(_tabela("cala"), [], id="funkcja-calego-pliku"),
        pytest.param(_tabela("wspolna"), [], id="nazwa-w-dwoch-plikach-z-kluczem-w-jednym"),
        pytest.param(_tabela("Dziennik", "STALA"), [], id="granica-klasa-i-stala"),
        pytest.param(_tabela("Protokol.zaslepka"), [], id="granica-zaslepka"),
        pytest.param(_tabela("pliki.zapisz()"), [], id="granica-nazwa-obiektu"),
        pytest.param(_tabela("poza"), [], id="granica-plik-spoza-definicji"),
        pytest.param(
            f"{rozjazd_modelu.TABELA}\n\nKrok `zapisz`.\n\n| Model action | Code |\n| --- | --- |\n| `Akcja` | `Logi.zamknij` |\n", [], id="granica-proza-sekcji"
        ),
        pytest.param(f"{rozjazd_modelu.TABELA}\n\nKrok `zapisz`.\n\n## Run\n\n| Kod |\n| --- |\n| `zapisz` |\n", [], id="granica-tabela-innej-sekcji"),
    ],
)
def test_funkcja_z_tabeli_modelu_bez_klucza_w_definicjach_jest_zgloszona(tmp_path: Path, skill_md: str, missing: list[str]) -> None:
    files = {**KLUCZE_PLIKI, f"{SKILL}/SKILL.md": skill_md, f"{SKILL}/{rozjazd_modelu.DEFINICJE}": json.dumps(KLUCZE_DEFINICJE)}
    for name, text in files.items():
        _write(tmp_path, name, text)

    assert rozjazd_modelu.bez_klucza(tmp_path / SKILL, tmp_path) == missing


def test_skill_bez_sekcji_tabeli_modelu_odmawia(tmp_path: Path) -> None:
    skill = _skill(tmp_path)

    with pytest.raises(ValueError, match=re.escape(f"SKILL.md nie ma sekcji „{rozjazd_modelu.TABELA}”")):
        rozjazd_modelu.bez_klucza(skill, tmp_path)
