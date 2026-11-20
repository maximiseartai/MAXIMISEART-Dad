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
WHOLE_TEXT = "frontend/src/widok.ts"
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
NAMES = {
    CODE: ["zapisz", "Dziennik.zamknij", "utworz.kolejka", "STALA", "galezie.wynik"],
    WHOLE: [rozjazd_modelu.CALY_PLIK],
    WHOLE_TEXT: [rozjazd_modelu.CALY_PLIK],
}
STEPS = f"Wykonaj kroki „Bring the model in line” z {SKILL}/SKILL.md, a skróty przelicz (tools/przesun_model.py verify-model) dopiero, gdy model opisuje kod."


def _write(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8", newline="")


def _skill(root: Path) -> Path:
    """Skill z modelem kodu ``NAMES`` i kod, który model opisuje: skróty przeliczone na tym kodzie."""

    files = {CODE: SOURCE, WHOLE: "X = 1\n", WHOLE_TEXT: "x = 1\n", "inny.txt": "inny\n", f"{SKILL}/SKILL.md": "Model.\n"}
    for name, text in files.items():
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
        pytest.param("X = 1\n", "X = 2\n", WHOLE, id="caly-plik"),
        pytest.param("x = 1\n", "x = 1;\n", WHOLE_TEXT, id="tekst-calego-pliku-spoza-pythona-o-tym-samym-drzewie"),
    ],
)
def test_zmiana_kodu_opisanego_modelem_jest_rozjazdem_z_plikiem_definicja_i_krokami_naprawy(
    tmp_path: Path, old: str, new: str, changed: str
) -> None:
    skill = _skill(tmp_path)
    _edit(tmp_path, changed if changed in NAMES else CODE, old, new)

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
        pytest.param(CODE, '    """Zapisuje."""\n', '    """Zapisuje inaczej."""\n', id="zmieniony-docstring-definicji"),
        pytest.param(CODE, '    """Zapisuje."""\n', "", id="usuniety-docstring-definicji"),
        pytest.param(WHOLE, "X = 1\n", '"""Docstring."""\nX = 1\n', id="docstring-w-calym-pliku"),
        pytest.param(WHOLE, "X = 1\n", "X = 1  # komentarz\n", id="komentarz-w-calym-pliku"),
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


@pytest.mark.parametrize("body", ["pass", "...", "return None"])
def test_definicja_z_samym_docstringiem_ma_skrot_inny_niz_definicja_bez_docstringu(tmp_path: Path, body: str) -> None:
    _write(tmp_path, "z_docstringiem.py", 'def f():\n    """Opis."""\n')
    _write(tmp_path, "bez_docstringu.py", f"def f():\n    {body}\n")

    found = rozjazd_modelu.skroty({"z_docstringiem.py": {"f": ""}, "bez_docstringu.py": {"f": ""}}, tmp_path)

    assert found["z_docstringiem.py"]["f"] != found["bez_docstringu.py"]["f"]


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
    # „Changes to Komunikaty text, the log or Zgłoszenia do not matter here”: odmowę daje trasa w całym pliku
    # ``tool_update.py``, a ``update_without_port`` to tylko jej Komunikat.
    "verify-aktualizacja-narzedzia": ["src/rozliczenia/centrum/runs.py RunHost.begin_update", "src/rozliczenia/centrum/refusal.py update_without_port"],
    # „The rest of the table runs as real code”: klucze mają tylko części modelowane ręcznie.
    "verify-jedno-uruchomienie-naraz": [
        "src/rozliczenia/centrum/runs.py RunHost.start",
        "src/rozliczenia/centrum/logs_disk.py LogsOnDisk.started",
        "src/rozliczenia/centrum/runs.py RunHost.begin_update",
        "src/rozliczenia/centrum/runs.py RunHost.begin_restore",
        "src/rozliczenia/centrum/runs.py Run.work",
        "src/rozliczenia/centrum/runs.py RunHost.end",
        "src/rozliczenia/centrum/runs.py RunHost.after",
        "src/rozliczenia/centrum/shutdown.py Shutdown.request",
    ],
    "verify-kolejka-skrzynki": ["src/rozliczenia/centrum/run_comments.py RunComments.send_left_behind", "src/rozliczenia/centrum/case_delivery.py _CaseDelivery.delivered"],
    # Wiersz ``hyperlinks.py``: „its reader `read_sheet_hyperlinks` is covered by pytest (…), not here”.
    "verify-kopia-wzorca": ["src/rozliczenia/hyperlinks.py read_sheet_hyperlinks"],
    # „Left out on purpose: (…) the Komunikat of an Uwaga that was not queued (`refusal.note_not_queued`), (…)
    # `KeyedBox.judge`”.
    "verify-sprawy-taty": ["src/rozliczenia/centrum/keyed_box.py KeyedBox.judge", "src/rozliczenia/centrum/refusal.py note_not_queued"],
    "verify-urwane-uruchomienie": [
        "src/rozliczenia/centrum/app.py create_app",
        "src/rozliczenia/efenix_trace.py traced",
        "src/rozliczenia/efenix_pricing.py _outcome",
        "src/rozliczenia/centrum/run_comments.py RunComments._refresh",
        "src/rozliczenia/centrum/process_kind.py startable",
        "src/rozliczenia/centrum/catalog.py Catalog.prepared",
        "src/rozliczenia/centrum/run_comments.py RecordMaker.of",
        "src/rozliczenia/centrum/outbox.py _settle",
    ],
    # „Every code name in the table is one of them, except `onedrive_conflicts.beside` (…), `OlderOwnEntries.upgraded`
    # (Left out) and `register_file.read` (…) (`verify-zapis-intermax`)”.
    "verify-wpisanie-raportow": [
        "src/rozliczenia/onedrive_conflicts.py beside",
        "src/rozliczenia/register_file.py read",
        "src/rozliczenia/worker_reports/_model.py OlderOwnEntries.upgraded",
    ],
    # Wiersz ``Tata``: „none: Dad changes a quantity (…) by hand (…) (`StanEfenix.edit` in the tests)”.
    "verify-wznowienie-wyceny-efenix": ["tools/lib/atrapy/model_efenix.py StanEfenix.edit"],
    # „`intermax_file.check` and `check_cells` have no digest (…). Neither has `intermax_messages.refused`”.
    "verify-zapis-intermax": [
        "src/rozliczenia/intermax_file.py check",
        "src/rozliczenia/intermax_file.py check_cells",
        "src/rozliczenia/intermax_messages.py refused",
    ],
}


def test_kazda_funkcja_z_tabeli_modelu_skilla_ma_klucz_w_definicjach_albo_model_pomija_ja_celowo() -> None:
    """Rozjazd nie widzi zmiany funkcji bez klucza: merge w #2058 zgubił ``ReportEnteringEntry.on_request``, choć tabela
    ``verify-wpisanie-raportow`` go nazywa (#2058 r5), a metody nazwanej bez klasy, jak ``prepare``, sprawdzenie nie
    widziało (#2058 r6), a zgubionego wpisu całego pliku też nie (#2076 r1). Równość z ``POZA_MODELEM`` każe też usunąć
    stamtąd funkcję, która dostała klucz albo zniknęła z tabeli."""

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


def serwer() -> object:
    def stop() -> int:
        return 16

    return stop


class Kolejka:
    def wyslij(self) -> int:
        return 11

    def zaslepka(self) -> int:
        return 12


if True:

    class Zapasowa:
        def odbierz(self) -> int:
            return 13


STALA = 5
'''
KLUCZE_PLIKI = {
    CODE: KLUCZE_KOD,
    "src/pakiet/__init__.py": "def wejscie() -> int:\n    return 6\n\n\ndef inna() -> int:\n    return 7\n",
    "src/pakiet/drugi.py": "def wspolna() -> int:\n    return 8\n",
    WHOLE: "def cala() -> int:\n    return 9\n",
    "src/poza.py": "def poza() -> int:\n    return 10\n\n\nclass Spoza:\n    def licz(self) -> int:\n        return 14\n",
    "src/serwer.py": "X = 1\n",
    "tools/lib/atrapa.py": "class Atrapa:\n    def zmien(self) -> int:\n        return 15\n",
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
        pytest.param(_tabela("wyslij"), [f"{CODE} Kolejka.wyslij"], id="metoda-bez-klasy"),
        pytest.param(_tabela("kolejka.wyslij()"), [f"{CODE} Kolejka.wyslij"], id="metoda-bez-klasy-po-obiekcie"),
        pytest.param(_tabela("odbierz"), [f"{CODE} Zapasowa.odbierz"], id="metoda-bez-klasy-w-klasie-pod-if"),
        pytest.param(_tabela("poza.poza"), ["src/poza.py poza"], id="z-modulem-z-przodu-w-pliku-spoza-definicji"),
        pytest.param(_tabela("Spoza.licz"), ["src/poza.py Spoza.licz"], id="metoda-klasy-z-pliku-spoza-definicji"),
        pytest.param(_tabela("Atrapa.zmien"), ["tools/lib/atrapa.py Atrapa.zmien"], id="metoda-klasy-z-narzedzi"),
        pytest.param(_tabela("serwer.stop"), [f"{CODE} serwer.stop"], id="nazwa-modulu-spoza-definicji-i-funkcja-w-pliku-definicji"),
        pytest.param(_tabela("Logi.zamknij"), [], id="metoda-klasy-z-kluczem"),
        pytest.param(_tabela("zamknij"), [], id="metoda-bez-klasy-w-dwoch-klasach-z-kluczem-jednej"),
        pytest.param(_tabela("cala"), [], id="funkcja-calego-pliku"),
        pytest.param(_tabela("caly.cala"), [], id="z-modulem-z-przodu-funkcja-calego-pliku"),
        pytest.param(_tabela("wspolna"), [], id="nazwa-w-dwoch-plikach-z-kluczem-w-jednym"),
        pytest.param(_tabela("Dziennik", "STALA"), [], id="granica-klasa-i-stala"),
        pytest.param(_tabela("Protokol.zaslepka"), [], id="granica-zaslepka-obok-metody-z-cialem"),
        pytest.param(_tabela("pliki.zapisz()"), [], id="granica-nazwa-obiektu"),
        pytest.param(_tabela("poza", "licz"), [], id="granica-gola-nazwa-z-pliku-spoza-definicji"),
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


def test_zgubiony_wpis_calego_pliku_definicji_zglasza_jego_funkcje_nazwane_z_klasa_albo_modulem(tmp_path: Path) -> None:
    """Merge, który gubi wpis pliku w ``definicje.json``, zabiera rozjazdowi wszystkie definicje tego pliku naraz
    (#2076 r1: wpis ``efenix_browser.py`` w ``verify-wznowienie-wyceny-efenix``)."""

    definitions = {**KLUCZE_DEFINICJE, "src/poza.py": {"poza": "", "Spoza": ""}}
    files = {**KLUCZE_PLIKI, f"{SKILL}/SKILL.md": _tabela("poza.poza", "Spoza.licz"), f"{SKILL}/{rozjazd_modelu.DEFINICJE}": json.dumps(definitions)}
    for name, text in files.items():
        _write(tmp_path, name, text)
    assert rozjazd_modelu.bez_klucza(tmp_path / SKILL, tmp_path) == []

    del definitions["src/poza.py"]
    _write(tmp_path, f"{SKILL}/{rozjazd_modelu.DEFINICJE}", json.dumps(definitions))

    assert rozjazd_modelu.bez_klucza(tmp_path / SKILL, tmp_path) == ["src/poza.py poza", "src/poza.py Spoza.licz"]


def test_skill_bez_sekcji_tabeli_modelu_odmawia(tmp_path: Path) -> None:
    skill = _skill(tmp_path)

    with pytest.raises(ValueError, match=re.escape(f"SKILL.md nie ma sekcji „{rozjazd_modelu.TABELA}”")):
        rozjazd_modelu.bez_klucza(skill, tmp_path)


def _model_bez_wiersza(tla: str, skill_md: str) -> list[str]:
    text = re.sub(r"\(\*.*?\*\)|\\\*[^\n]*", "", tla, flags=re.DOTALL)
    blocks = {
        keyword: [found.group(1) for found in re.finditer(rf"^{keyword}S?\b(.*?)(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL)]
        for keyword in ("CONSTANT", "VARIABLE")
    }
    definitions = re.findall(r"^(\w+)\s*(?:\([^)]*\))?\s*==", text, re.MULTILINE)
    [steps] = re.findall(r"^Next\s*==(.*?)(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL) or [""]
    actions = [name for name in re.findall(r"\w+", re.sub(r"\\[EA]\s[^:]*:", "", steps)) if name in definitions]
    names = [name for keyword in blocks for block in blocks[keyword] for name in re.findall(r"\w+", block)] + actions
    named = {span.split("(", 1)[0] for row in rozjazd_modelu.wiersze_tabeli(skill_md) for span in row.split("|")[1].split("`")[1::2]}
    prefixes = tuple(name.removesuffix("…") for name in named if name.endswith("…"))
    return [name for name in dict.fromkeys(names) if name not in named and not name.startswith(prefixes or ("\0",))]


def _model(*, stale: str = "Max", zmienne: str = "x", next_: str = "Krok") -> str:
    return (
        "---- MODULE M ----\n"
        f"CONSTANTS\n    {stale}, WybaczoneA\n\nVARIABLES\n    {zmienne}\n\n"
        "Q == {1, 2}\nKrok == x' = x\nRuch(q) == x' = q\nPomocnik == 1\n\n"
        f"Next ==\n    \\/ {next_}\n\nSpec == [][Next]_x\n====\n"
    )


def _skill_modelu(*nazwy: str) -> str:
    rows = "".join(f"| {nazwa} | kod |\n" for nazwa in nazwy)
    return f"# Skill\n\n{rozjazd_modelu.TABELA}\n\n| Model | Code |\n| --- | --- |\n{rows}\n## Run\n\n| `Inna` | poza sekcją |\n"


WIERSZE = ("`Krok`", "`Ruch(q)`", "`Max`", "`Wybaczone…`", "`x`")


@pytest.mark.parametrize(
    ("tla", "wiersze", "missing"),
    [
        pytest.param(_model(), WIERSZE, [], id="kazda-nazwa-ma-wiersz-a-pomocnik-i-zbior-nie-musza"),
        pytest.param(_model(next_="Krok \\/ Nowa"), WIERSZE, [], id="nazwa-spoza-definicji-to-nie-akcja"),
        pytest.param(_model().replace("Pomocnik ==", "Nowa ==").replace("\\/ Krok", "\\/ Krok \\/ Nowa"), WIERSZE, ["Nowa"], id="nowa-akcja-next"),
        pytest.param(_model(next_="\\E q \\in Q : Ruch(q)"), WIERSZE[:1] + WIERSZE[2:], ["Ruch"], id="akcja-pod-kwantyfikatorem-bez-zbioru"),
        pytest.param(
            _model().replace("Pomocnik ==", "Nowa ==").replace("Next ==\n    \\/ Krok", "Next == Nowa \\/ Krok"), WIERSZE, ["Nowa"], id="nowa-akcja-next-w-jednej-linii"
        ),
        pytest.param(
            _model().replace("Pomocnik ==", "Nowa ==").replace("\\/ Krok", "\\/ Krok \\/ (Nowa)"), WIERSZE, ["Nowa"], id="nowa-akcja-next-w-nawiasie"
        ),
        pytest.param(_model(next_="(\\E q \\in Q : (Ruch(q)))"), WIERSZE[:1] + WIERSZE[2:], ["Ruch"], id="akcja-pod-kwantyfikatorem-w-nawiasie"),
        pytest.param(
            _model().replace("Pomocnik ==", "Nowa(q, r) ==").replace("\\/ Krok", "\\/ Krok \\/ \\E q \\in Q : \\E r \\in Q : Nowa(q, r)"),
            WIERSZE,
            ["Nowa"],
            id="akcja-pod-dwoma-kwantyfikatorami",
        ),
        pytest.param(
            _model().replace("Pomocnik ==", "Nowa(q) ==").replace("\\/ Krok", "\\/ Krok \\/ \\A q \\in Q : Nowa(q)"), WIERSZE, ["Nowa"], id="akcja-pod-kwantyfikatorem-ogolnym"
        ),
        pytest.param(_model(stale="Max, MaxNowa"), WIERSZE, ["MaxNowa"], id="stala-w-linii-z-inna"),
        pytest.param(_model(zmienne="x,\n    y"), WIERSZE, ["y"], id="zmienna"),
        pytest.param(_model(), ("`Krok`", "`Ruch(q)`", "`Max`", "`x`"), ["WybaczoneA"], id="bez-wiersza-z-przedrostkiem"),
        pytest.param(_model(next_="Krok \\/ Inna").replace("Pomocnik ==", "Inna =="), WIERSZE, ["Inna"], id="wiersz-innej-sekcji-sie-nie-liczy"),
        pytest.param(_model(zmienne="x \\* y"), WIERSZE, [], id="komentarz-to-nie-zmienna"),
        pytest.param(_model(), ("`Krok`, `Ruch(q)`", "`Max`, `Wybaczone…`", "`x` (`dysk`)"), [], id="kilka-nazw-w-wierszu"),
        pytest.param(_model(), ("`Krok`, `Ruch(q)`", "`Wybaczone…`, `x` | `Max`"), ["Max"], id="nazwa-w-kolumnie-kodu-to-nie-wiersz"),
    ],
)
def test_akcja_next_stala_i_zmienna_modelu_bez_wiersza_tabeli_jest_zgloszona(tla: str, wiersze: tuple[str, ...], missing: list[str]) -> None:
    assert _model_bez_wiersza(tla, _skill_modelu(*wiersze)) == missing


def test_kazda_akcja_next_stala_i_zmienna_modelu_skilla_ma_wiersz_tabeli() -> None:
    found = {
        tla.parents[1].name: missing
        for tla in sorted(ROOT.glob(".agents/skills/*/model/*.tla"))
        if (missing := _model_bez_wiersza(tla.read_text(encoding="utf-8"), (tla.parents[1] / "SKILL.md").read_text(encoding="utf-8")))
    }

    assert found == {}, (
        f"Akcja z Next, stała albo zmienna modelu TLA+ nie ma wiersza w tabelach sekcji „{rozjazd_modelu.TABELA}” SKILL.md "
        "skilla, więc nic nie mówi, który kod opisuje: dopisz wiersz z kodem, który modeluje."
    )
