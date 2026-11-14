"""``tools/rownowaznosc.py``: zmiana, która nie zmienia zachowania, daje TAK SAMO, a każda różnica wyniku RÓŻNICA."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from openpyxl import load_workbook
import pytest

from rozliczenia import tool_files
from rozliczenia.period_folder import PeriodFolder
from rozliczenia.settlement_period import parse_period_token

from tests.fixtures.git_repo import commit, git
from atrapy.intermax import ORDER_SHEET, YELLOW
from atrapy.pliki_taty import REGISTER_NAME as REGISTER
import potomne
from tests.fixtures.rownowaznosc import METRICS, stub_tree, write_workbook
import rownowaznosc
from atrapy.workbooks import rewrite_parts

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "rownowaznosc.py"
TIME, MOMENT, FOLDER = rownowaznosc.TIME, rownowaznosc.MOMENT, rownowaznosc.FOLDER
PERIOD_FOLDER = PeriodFolder(Path(), parse_period_token("08_14_09_2026"))
SETTLEMENTS = PERIOD_FOLDER.worker_settlements.name

# Kod wyjścia, wynik i kod Komunikatu Zatrzymania każdego scenariusza na kodzie tego checkoutu.
EXPECTED = {
    "przebieg": "kod 0, OK",
    "przebieg-podglad": "kod 0, OK",
    "przebieg-ilosci": "kod 0, OK",
    "przebieg-wzorzec-syntetyczny": "kod 0, OK",
    "przebieg-podglad-nieznany-wykonawca": "kod 2, WYMAGA_SPRAWDZENIA",
    "przebieg-nieznany-wykonawca": "kod 1, BLAD_KRYTYCZNY, NIEZNANY_WYKONAWCA",
    "przebieg-folder-rozliczen-istnieje": "kod 1, BLAD_KRYTYCZNY, FOLDER_ROZLICZEN_ISTNIEJE",
    "przebieg-plik-zbiorczy-nie-skoroszyt": "kod 1, BLAD_KRYTYCZNY, ZLY_PLIK_ZBIORCZY",
    "przebieg-plik-zbiorczy-uciety": "kod 1, BLAD_KRYTYCZNY, ZLY_PLIK_ZBIORCZY",
    "przebieg-format-bez-definicji-L18": "kod 1, BLAD_KRYTYCZNY, ZLY_PLIK_ZBIORCZY",
    "przebieg-format-bez-definicji-M18": "kod 0, OK",
    "przebieg-format-bez-definicji-AT18": "kod 0, OK",
    "przygotowanie": "kod 2, WYMAGA_SPRAWDZENIA",
    "przygotowanie-podglad": "kod 0, OK",
    "przygotowanie-uklad-folderow-taty": "kod 2, WYMAGA_SPRAWDZENIA",
    "przygotowanie-wzorce-syntetyczne": "kod 2, WYMAGA_SPRAWDZENIA",
    "przygotowanie-niepelny-okres": "kod 1, BLAD_KRYTYCZNY, PRZERWANO_NIEPELNY_OKRES",
    "przygotowanie-plik-zbiorczy-istnieje": "kod 1, BLAD_KRYTYCZNY, PLIK_OKRESU_ISTNIEJE",
    "przygotowanie-rejestr-nie-skoroszyt": "kod 1, BLAD_KRYTYCZNY, USZKODZONY_REJESTR",
    "przygotowanie-rejestr-uciety": "kod 1, BLAD_KRYTYCZNY, USZKODZONY_REJESTR",
    "intermax": "kod 0, OK",
    "intermax-starszy-arkusz-zolte-komorki": "kod 0, OK",
    "intermax-pierwszy-wiersz-na-miejscu": "kod 0, OK",
    "intermax-kalendarz-1904": "kod 0, OK",
    "intermax-bez-surowych-zlecen": "kod 1, BLAD_KRYTYCZNY, BRAK_SUROWYCH_ZLECEN",
    "intermax-rejestr-nie-skoroszyt": "kod 1, BLAD_KRYTYCZNY, NIECZYTELNY_INTERMAX",
}
# Scenariusz bazowy każdego procesu.
BASES = {"settlement": "przebieg", "preparation": "przygotowanie", "intermax": "intermax"}
# Scenariusze, które różnią się od bazowego argumentami procesu, a nie samymi wejściami.
OWN_ARGUMENTS = {"przebieg-podglad", "przebieg-podglad-nieznany-wykonawca", "przygotowanie-podglad", "przygotowanie-uklad-folderow-taty"}
COLLECTIVE = PERIOD_FOLDER.collective_file.as_posix()
CONFIG = tool_files.config_dir(Path())
# Wejścia, które każdy pozostały scenariusz zmienia wobec bazowego swojego procesu, przy tych samych argumentach.
VARIANTS = {
    "przebieg-ilosci": {COLLECTIVE},
    "przebieg-wzorzec-syntetyczny": {tool_files.WORKER_TEMPLATE.name},
    "przebieg-nieznany-wykonawca": {COLLECTIVE},
    "przebieg-folder-rozliczen-istnieje": {f"08_14_09_2026/{SETTLEMENTS}/zostaje.txt"},
    "przebieg-plik-zbiorczy-nie-skoroszyt": {COLLECTIVE},
    "przebieg-plik-zbiorczy-uciety": {COLLECTIVE},
    "przebieg-format-bez-definicji-L18": {COLLECTIVE},
    "przebieg-format-bez-definicji-M18": {COLLECTIVE},
    "przebieg-format-bez-definicji-AT18": {COLLECTIVE},
    "przygotowanie-wzorce-syntetyczne": {
        (CONFIG / tool_files.COLLECTIVE_TEMPLATE.name).as_posix(),
        (CONFIG / tool_files.INTERNAL_TEMPLATE.name).as_posix(),
    },
    "przygotowanie-niepelny-okres": {REGISTER},
    "przygotowanie-plik-zbiorczy-istnieje": {f"INEA/{COLLECTIVE}"},
    "przygotowanie-rejestr-nie-skoroszyt": {REGISTER},
    "przygotowanie-rejestr-uciety": {REGISTER},
    "intermax-starszy-arkusz-zolte-komorki": {REGISTER},
    "intermax-pierwszy-wiersz-na-miejscu": {REGISTER},
    "intermax-kalendarz-1904": {REGISTER},
    "intermax-bez-surowych-zlecen": {REGISTER},
    "intermax-rejestr-nie-skoroszyt": {REGISTER},
}


def _stub_scenario(name: str = "na-niby") -> rownowaznosc.Scenario:
    def build(folder: Path) -> list[str | Path]:
        (folder / "wejscie.txt").write_text("wejście\n", encoding="utf-8")
        return ["--source", folder / "wejscie.txt"]

    return rownowaznosc.Scenario(name, "settlement", build)


def _equivalence(tmp_path: Path, base: Path, head: Path, *scenarios: rownowaznosc.Scenario) -> int:
    work = tmp_path / "praca"
    work.mkdir()
    return rownowaznosc.equivalence(base, head, scenarios or (_stub_scenario(),), work)


# --- maskowanie --------------------------------------------------------------------------------------------------


def test_maskowanie_ukrywa_czasy_chwile_zegara_i_folder_strony_a_reszte_wyniku_zostawia(tmp_path: Path) -> None:
    folder = tmp_path / "strona" / "scenariusz"
    result = {
        "result": "OK",
        "total_duration_ms": 1234,
        "progress": {"phases": [{"phase": "Odczyt", "state": "completed", "duration_ms": 12}]},
        "stop": {"kind": "stop", "message": {"code": "ZLY_PLIK_ZBIORCZY", "what": "Plik jest uszkodzony.", "where": "Plik zbiorczy", "action": "Otwórz go w Excelu."}},
        "warnings": [{"code": "PUSTY_WIERSZ", "what": "Wiersz 7 jest pusty.", "where": "Rejestr, wiersz 7", "action": "Usuń wiersz."}],
        "summary": {
            "figures": [{"label": "Czas", "value": 812, "unit": "ms"}, {"label": "Zlecenia", "value": 6, "unit": "count"}],
            "intermax_copy": "INTERMAX przed uporządkowaniem 2026-10-29 15-12-01.xlsx",
        },
        "technical_notes": [
            f"Nie zapisano metryk w {folder / 'm.jsonl'} o 2026-10-29T15:12:01.123+02:00.",
            f"Plik {tmp_path / 'strona' / 'm.jsonl'}, chwila 2026-10-29T13:12:01Z, dzień 2026-10-29.",
        ],
        "metrics_saved": False,
    }

    assert rownowaznosc.masked(result, (folder, tmp_path / "strona")) == {
        "result": "OK",
        "total_duration_ms": TIME,
        "progress": {"phases": [{"phase": "Odczyt", "state": "completed", "duration_ms": TIME}]},
        "stop": {"kind": "stop", "message": {"code": "ZLY_PLIK_ZBIORCZY", "what": "Plik jest uszkodzony.", "where": "Plik zbiorczy", "action": "Otwórz go w Excelu."}},
        "warnings": [{"code": "PUSTY_WIERSZ", "what": "Wiersz 7 jest pusty.", "where": "Rejestr, wiersz 7", "action": "Usuń wiersz."}],
        "summary": {
            "figures": [{"label": "Czas", "value": TIME, "unit": "ms"}, {"label": "Zlecenia", "value": 6, "unit": "count"}],
            "intermax_copy": f"INTERMAX przed uporządkowaniem {MOMENT}.xlsx",
        },
        "technical_notes": [
            f"Nie zapisano metryk w {FOLDER}{os.sep}m.jsonl o {MOMENT}.",
            f"Plik {FOLDER}{os.sep}m.jsonl, chwila {MOMENT}, dzień 2026-10-29.",
        ],
        "metrics_saved": False,
    }


def test_maskowanie_ukrywa_folder_strony_podany_wzglednie_i_po_rozwiazaniu_dowiazan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    folder = Path("strona") / "scenariusz"
    note = f"Plik {(tmp_path / 'strona' / 'scenariusz').resolve() / 'm.jsonl'} i {folder / 'w.txt'}."

    assert rownowaznosc.masked(note, (folder, Path("strona"))) == f"Plik {FOLDER}{os.sep}m.jsonl i {FOLDER}{os.sep}w.txt."


def test_maskowanie_ukrywa_folder_strony_podany_przez_dowiazanie_symboliczne_w_postaci_po_jego_rozwiazaniu(tmp_path: Path) -> None:
    (tmp_path / "prawdziwa" / "scenariusz").mkdir(parents=True)
    try:
        (tmp_path / "dowiazanie").symlink_to(tmp_path / "prawdziwa", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"dowiązanie symboliczne wymaga uprawnień, których ten Windows nie daje: {error}")
    note = f"Plik {tmp_path / 'prawdziwa' / 'scenariusz' / 'm.jsonl'}."

    assert rownowaznosc.masked(note, (tmp_path / "dowiazanie" / "scenariusz",)) == f"Plik {FOLDER}{os.sep}m.jsonl."


# --- JSON wyniku -------------------------------------------------------------------------------------------------


def test_rozne_pola_json_to_ich_sciezki_bez_wartosci() -> None:
    base = {"result": "OK", "stop": None, "warnings": [{"code": "A", "what": "x"}], "summary": {"files": [1, 2]}}
    head = {"result": "BLAD_KRYTYCZNY", "stop": None, "warnings": [{"code": "A", "what": "y"}], "summary": {"files": [1]}, "nowe": 1}

    assert rownowaznosc.json_differences(base, head) == ["result", "warnings[0].what", "summary.files (liczba 2→1)", "nowe"]
    assert rownowaznosc.json_differences(base, dict(base)) == []
    assert rownowaznosc.json_differences({"a": 1}, {"b": 1}) == ["a", "b"]
    assert rownowaznosc.json_differences([1], 1) == ["JSON"]


# --- pliki wynikowe ----------------------------------------------------------------------------------------------


def _folders(tmp_path: Path) -> tuple[Path, Path]:
    base, head = tmp_path / "baza", tmp_path / "head"
    base.mkdir()
    head.mkdir()
    return base, head


def test_te_same_pliki_z_inna_chwila_w_nazwie_i_innym_czasem_zapisu_skoroszytu_to_brak_roznicy(tmp_path: Path) -> None:
    base, head = _folders(tmp_path)
    write_workbook(base / "Kopie INTERMAX" / "INTERMAX przed uporządkowaniem 2026-10-29 15-12-01.xlsx", "zlecenie")
    write_workbook(head / "Kopie INTERMAX" / "INTERMAX przed uporządkowaniem 2026-10-29 15-12-04.xlsx", "zlecenie")
    write_workbook(base / "Plik.xlsx", 1)
    write_workbook(head / "Plik.xlsx", 1)
    rewrite_parts(head / "Plik.xlsx", lambda name, data: data.replace(b"<dcterms:modified", b"<dcterms:modified x=\"1\"") if name == "docProps/core.xml" else data)
    for folder in (base, head):
        (folder / "uwagi.txt").write_text("to samo\n", encoding="utf-8")
        (folder / "nie-skoroszyt.xlsx").write_bytes(b"to nie jest skoroszyt\n")

    assert rownowaznosc.file_differences(base, head) == []


def test_plik_tylko_po_jednej_stronie_to_roznica_z_nazwa_pliku(tmp_path: Path) -> None:
    base, head = _folders(tmp_path)
    (base / "okres").mkdir()
    (base / "okres" / "stary.txt").write_text("x", encoding="utf-8")
    (head / "nowy.txt").write_text("x", encoding="utf-8")

    assert rownowaznosc.file_differences(base, head) == ["pliki tylko w bazie: okres/stary.txt", "pliki tylko w HEAD: nowy.txt"]


def test_druga_kopia_z_inna_tylko_chwila_w_nazwie_to_plik_tylko_po_jednej_stronie(tmp_path: Path) -> None:
    base, head = _folders(tmp_path)
    write_workbook(base / "Kopie INTERMAX" / "INTERMAX przed uporządkowaniem 2026-10-29 15-12-01.xlsx", "zlecenie")
    for moment in ("15-12-01", "15-12-02"):
        write_workbook(head / "Kopie INTERMAX" / f"INTERMAX przed uporządkowaniem 2026-10-29 {moment}.xlsx", "zlecenie")

    assert rownowaznosc.file_differences(base, head) == [f"pliki tylko w HEAD: Kopie INTERMAX/INTERMAX przed uporządkowaniem {MOMENT}.xlsx (2)"]


def test_inny_skoroszyt_rozni_sie_czescia_zipu_takze_samymi_stylami_a_inny_plik_bajtami(tmp_path: Path) -> None:
    base, head = _folders(tmp_path)
    write_workbook(base / "okres" / "Plik zbiorczy.xlsx", 1)
    write_workbook(head / "okres" / "Plik zbiorczy.xlsx", 2)
    for folder in (base, head):
        write_workbook(folder / "okres" / "Style.xlsx", 1)
    rewrite_parts(head / "okres" / "Style.xlsx", lambda name, data: data.replace(b"<sz val=\"11\" />", b"<sz val=\"12\" />") if name == "xl/styles.xml" else data)
    (base / "uwagi.txt").write_text("przed\n", encoding="utf-8")
    (head / "uwagi.txt").write_text("po\n", encoding="utf-8")
    (base / "zly.xlsx").write_bytes(b"przed")
    (head / "zly.xlsx").write_bytes(b"po")
    write_workbook(base / "okres" / "Uszkodzony w HEAD.xlsx", 1)
    (head / "okres" / "Uszkodzony w HEAD.xlsx").write_bytes(b"to nie jest skoroszyt\n")

    assert rownowaznosc.file_differences(base, head) == [
        "okres/Plik zbiorczy.xlsx: części xl/worksheets/sheet1.xml",
        "okres/Style.xlsx: części xl/styles.xml",
        "okres/Uszkodzony w HEAD.xlsx: bajty",
        "uwagi.txt: bajty",
        "zly.xlsx: bajty",
    ]


def test_czesc_zipu_tylko_po_jednej_stronie_to_roznica_z_nazwa_czesci(tmp_path: Path) -> None:
    base, head = _folders(tmp_path)
    for folder in (base, head):
        write_workbook(folder / "Nowa.xlsx", 1)
        write_workbook(folder / "Brakujaca.xlsx", 1)
    with zipfile.ZipFile(head / "Nowa.xlsx", "a") as archive:
        archive.writestr("customXml/item1.xml", "<nowa/>")
    with zipfile.ZipFile(base / "Brakujaca.xlsx", "a") as archive:
        archive.writestr("customXml/item1.xml", "<stara/>")

    assert rownowaznosc.file_differences(base, head) == ["Brakujaca.xlsx: części customXml/item1.xml", "Nowa.xlsx: części customXml/item1.xml"]


def test_rozliczenie_pracownika_bez_ochrony_arkusza_rozni_sie_czescia_zipu(tmp_path: Path) -> None:
    base, head = _folders(tmp_path)
    for folder in (base, head):
        write_workbook(folder / "okres" / SETTLEMENTS / "Adrian Testowy.xlsx", "to samo")
        write_workbook(folder / "okres" / SETTLEMENTS / "Darek Fikcyjny.xlsx", "to samo")
        (folder / "okres" / SETTLEMENTS / "zostaje.txt").write_text("plik sprzed uruchomienia\n", encoding="utf-8")
    protected = b'<sheetProtection sheet="1" selectLockedCells="1"/><pageMargins'
    rewrite_parts(base / "okres" / SETTLEMENTS / "Darek Fikcyjny.xlsx", lambda name, data: data.replace(b"<pageMargins", protected) if name == "xl/worksheets/sheet1.xml" else data)

    assert rownowaznosc.file_differences(base, head) == [f"okres/{SETTLEMENTS}/Darek Fikcyjny.xlsx: części xl/worksheets/sheet1.xml"]


# --- linia scenariusza -------------------------------------------------------------------------------------------


def _outcome(tmp_path: Path, name: str, code: int, result: object) -> rownowaznosc.Outcome:
    folder = tmp_path / name
    folder.mkdir()
    return rownowaznosc.Outcome(code, result, folder)


def test_ten_sam_wynik_to_tak_samo_z_kodem_wynikiem_i_kodem_zatrzymania(tmp_path: Path) -> None:
    result = {"result": "BLAD_KRYTYCZNY", "stop": {"kind": "stop", "message": {"code": "ZLY_PLIK_ZBIORCZY"}}}

    assert rownowaznosc.compare("s", _outcome(tmp_path, "a", 1, result), _outcome(tmp_path, "b", 1, dict(result))) == (
        "s | TAK SAMO | kod 1, BLAD_KRYTYCZNY, ZLY_PLIK_ZBIORCZY",
        True,
    )
    assert rownowaznosc.compare("s", _outcome(tmp_path, "c", 1, None), _outcome(tmp_path, "d", 1, None)) == ("s | TAK SAMO | kod 1, bez JSON", True)


def test_inny_kod_wyjscia_json_tylko_po_jednej_stronie_i_rozne_pole_to_roznica(tmp_path: Path) -> None:
    ok = {"result": "OK", "stop": None}

    assert rownowaznosc.compare("s", _outcome(tmp_path, "a", 0, ok), _outcome(tmp_path, "b", 1, None)) == (
        "s | RÓŻNICA | kod 0→1; JSON tylko w bazie",
        False,
    )
    assert rownowaznosc.compare("s", _outcome(tmp_path, "c", 1, None), _outcome(tmp_path, "d", 0, ok))[0] == "s | RÓŻNICA | kod 1→0; JSON tylko w HEAD"
    assert rownowaznosc.compare("s", _outcome(tmp_path, "e", 0, ok), _outcome(tmp_path, "f", 0, {"result": "OK", "stop": 1}))[0] == "s | RÓŻNICA | JSON stop"
    stopped = {"result": "BLAD_KRYTYCZNY", "stop": {"kind": "stop", "message": {"code": "ZLY_PLIK_ZBIORCZY"}}}
    assert rownowaznosc.compare("s", _outcome(tmp_path, "g", 1, stopped), _outcome(tmp_path, "h", 0, ok))[0] == "s | RÓŻNICA | kod 1→0; JSON result, stop"


def test_linia_roznicy_nazywa_piec_pierwszych_pol_json_a_reszte_liczy(tmp_path: Path) -> None:
    base, head = {letter: 0 for letter in "abcdefg"}, {letter: 1 for letter in "abcdefg"}
    five = {letter: 0 for letter in "abcde"}

    assert rownowaznosc.compare("s", _outcome(tmp_path, "a", 0, base), _outcome(tmp_path, "b", 0, head))[0] == "s | RÓŻNICA | JSON a, b, c, d, e, … (+2)"
    assert rownowaznosc.compare("s", _outcome(tmp_path, "c", 0, five), _outcome(tmp_path, "d", 0, dict.fromkeys(five, 1)))[0] == "s | RÓŻNICA | JSON a, b, c, d, e"


# --- przebieg narzędzia ------------------------------------------------------------------------------------------


def test_strony_z_tym_samym_wynikiem_innym_czasem_i_swoim_plikiem_metryk_daja_rownowaznosc_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Plik metryk leży w folderze strony obok folderu scenariusza, więc uwaga o nim różni się ścieżką strony.
    note = f"Nie zapisano metryk w {METRICS}."
    base = stub_tree(tmp_path / "baza", {"result": "OK", "total_duration_ms": 5, "technical_notes": [note]}, files={"wynik.txt": "to samo"})
    head = stub_tree(tmp_path / "head", {"result": "OK", "total_duration_ms": 9, "technical_notes": [note]}, files={"wynik.txt": "to samo"})

    code = _equivalence(tmp_path, base, head, _stub_scenario("pierwszy"), _stub_scenario("drugi"))

    assert (code, capsys.readouterr().out.splitlines()) == (
        0,
        ["pierwszy | TAK SAMO | kod 0, OK", "drugi | TAK SAMO | kod 0, OK", "RÓWNOWAŻNOŚĆ OK | 2 scenariuszy"],
    )


def test_strona_z_innym_plikiem_wynikowym_daje_roznica_z_nazwa_scenariusza(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = stub_tree(tmp_path / "baza", {"result": "OK"}, files={"okres/wynik.txt": "przed"})
    head = stub_tree(tmp_path / "head", {"result": "OK"}, files={"okres/wynik.txt": "po"})

    code = _equivalence(tmp_path, base, head)

    assert (code, capsys.readouterr().out.splitlines()) == (
        1,
        ["na-niby | RÓŻNICA | okres/wynik.txt: bajty", "RÓWNOWAŻNOŚĆ RÓŻNICA | na-niby"],
    )


def test_strona_bez_json_daje_roznica(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = stub_tree(tmp_path / "baza", {"result": "OK"})
    head = stub_tree(tmp_path / "head", "Traceback (most recent call last):\n", code=1)

    code = _equivalence(tmp_path, base, head)

    assert (code, capsys.readouterr().out.splitlines()[0]) == (1, "na-niby | RÓŻNICA | kod 0→1; JSON tylko w bazie")


def test_scenariusz_bez_fixture_w_checkoucie_ma_linie_bez_fixture_i_nie_liczy_sie(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def missing(folder: Path) -> list[str | Path]:
        raise ModuleNotFoundError("No module named 'atrapy.nieznany'", name="atrapy.nieznany")

    tree = stub_tree(tmp_path / "drzewo", {"result": "OK"})

    code = _equivalence(tmp_path, tree, tree, rownowaznosc.Scenario("stary", "intermax", missing), _stub_scenario())

    assert (code, capsys.readouterr().out.splitlines()) == (
        0,
        ["stary | BEZ FIXTURE | atrapy.nieznany", "na-niby | TAK SAMO | kod 0, OK", "RÓWNOWAŻNOŚĆ OK | 1 scenariuszy"],
    )


def test_bez_zadnego_porownanego_scenariusza_wynik_jest_niesprawdzony_z_kodem_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def missing(folder: Path) -> list[str | Path]:
        raise ModuleNotFoundError("No module named 'atrapy.intermax'", name="atrapy.intermax")

    tree = stub_tree(tmp_path / "drzewo", {"result": "OK"})

    code = _equivalence(tmp_path, tree, tree, rownowaznosc.Scenario("stary", "intermax", missing))

    assert (code, capsys.readouterr().out.splitlines()) == (2, ["stary | BEZ FIXTURE | atrapy.intermax", "RÓWNOWAŻNOŚĆ NIESPRAWDZONA | 0 scenariuszy"])


@pytest.mark.parametrize("module", ["openpyxl_nowy", None])
def test_brak_modulu_spoza_fixtures_to_blad_narzedzia_a_nie_pominiety_scenariusz(tmp_path: Path, module: str | None) -> None:
    def broken(folder: Path) -> list[str | Path]:
        raise ModuleNotFoundError("No module named 'openpyxl_nowy'", name=module)

    tree = stub_tree(tmp_path / "drzewo", {"result": "OK"})

    with pytest.raises(ModuleNotFoundError, match="openpyxl_nowy"):
        _equivalence(tmp_path, tree, tree, rownowaznosc.Scenario("zepsuty", "settlement", broken))


@pytest.mark.parametrize("scenario", rownowaznosc.SCENARIOS, ids=lambda scenario: scenario.name)
def test_scenariusz_na_tym_samym_kodzie_po_obu_stronach_daje_tak_samo_z_oczekiwanym_wynikiem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], scenario: rownowaznosc.Scenario
) -> None:
    code = _equivalence(tmp_path, ROOT, ROOT, scenario)

    assert (code, capsys.readouterr().out.splitlines()) == (
        0,
        [f"{scenario.name} | TAK SAMO | {EXPECTED[scenario.name]}", "RÓWNOWAŻNOŚĆ OK | 1 scenariuszy"],
    )


def test_kazdy_proces_ma_scenariusz_zakonczony_i_scenariusz_z_zatrzymaniem_na_pliku_uszkodzonym() -> None:
    assert set(EXPECTED) == {scenario.name for scenario in rownowaznosc.SCENARIOS}
    for process in ("settlement", "preparation", "intermax"):
        names = [scenario.name for scenario in rownowaznosc.SCENARIOS if scenario.process == process]
        assert any(EXPECTED[name].startswith("kod 0") for name in names), process
        assert any("nie-skoroszyt" in name and "BLAD_KRYTYCZNY" in EXPECTED[name] for name in names), process


def _changed_inputs(base: Path, variant: Path) -> set[str]:
    changed: set[str] = set()
    for difference in rownowaznosc.file_differences(base, variant):
        side, _, names = difference.partition(": ")
        changed |= set(names.split(", ")) if side.startswith("pliki tylko w ") else {side}
    return changed


def test_kazdy_wariant_scenariusza_zmienia_wobec_bazowego_tylko_wejscia_ktore_nazywa(tmp_path: Path) -> None:
    # Wariant, który zgubi swoją zmianę, biegnie jak scenariusz bazowy, a jego linia TAK SAMO niczego nie sprawdza.
    arguments = {scenario.name: rownowaznosc.built(scenario, tmp_path / scenario.name) for scenario in rownowaznosc.SCENARIOS}
    variants = [scenario for scenario in rownowaznosc.SCENARIOS if scenario.name not in {*BASES.values(), *OWN_ARGUMENTS}]

    assert {scenario.name: _changed_inputs(tmp_path / BASES[scenario.process], tmp_path / scenario.name) for scenario in variants} == VARIANTS
    assert [scenario.name for scenario in variants if arguments[scenario.name] != arguments[BASES[scenario.process]]] == []


def test_rejestr_wariantu_starszy_arkusz_zolte_komorki_ma_starszy_arkusz_zlecen_i_zolte_komorki_zamiast_wiersza(tmp_path: Path) -> None:
    # Każda z dwóch zmian sama zmienia Rejestr wobec scenariusza bazowego, więc utratę drugiej łapie tylko ten test.
    scenario = next(scenario for scenario in rownowaznosc.SCENARIOS if scenario.name == "intermax-starszy-arkusz-zolte-komorki")
    rownowaznosc.built(scenario, tmp_path / "wejscia")

    workbook = load_workbook(tmp_path / "wejscia" / REGISTER)

    assert [name for name in workbook.sheetnames if name.startswith("ZLECENIA OD ")] == ["ZLECENIA OD 08_11_2021", ORDER_SHEET]
    yellow = [cell.coordinate for row in workbook[ORDER_SHEET].iter_rows() for cell in row if cell.fill.fgColor.rgb == YELLOW.fgColor.rgb]
    assert yellow != []
    assert [number for number, row in workbook[ORDER_SHEET].row_dimensions.items() if row.fill.fgColor.rgb == YELLOW.fgColor.rgb] == []


def test_rozliczenia_pracownikow_ze_wzorca_syntetycznego_maja_komentarz_wzorca_taty(tmp_path: Path) -> None:
    # Porównanie znaczeniowe nie widzi komentarzy, więc utratę komentarza w Rozliczeniu łapie tylko ten scenariusz.
    scenario = next(scenario for scenario in rownowaznosc.SCENARIOS if scenario.name == "przebieg-wzorzec-syntetyczny")
    arguments = rownowaznosc.built(scenario, tmp_path / "wejscia")

    outcome = rownowaznosc.run(ROOT, scenario, arguments, tmp_path / "wejscia", tmp_path / "strona")

    settlements = sorted((outcome.folder / "08_14_09_2026" / SETTLEMENTS).glob("*.xlsx"))
    assert len(settlements) == 3
    for path in settlements:
        with zipfile.ZipFile(path) as archive:
            assert "xl/comments1.xml" in archive.namelist(), path.name


def test_proces_ktory_wisi_konczy_narzedzie_po_limicie_czasu_zamiast_czekac_bez_konca(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rownowaznosc, "TIMEOUT", 1)
    tree = stub_tree(tmp_path / "drzewo", {"result": "OK"}, sleep_s=30)

    with pytest.raises(subprocess.TimeoutExpired):
        _equivalence(tmp_path, tree, tree)


def _script(copy: Path, *arguments: str) -> tuple[int, list[str]]:
    done = subprocess.run(
        [sys.executable, str(copy / "tools" / "rownowaznosc.py"), *arguments],
        cwd=copy,
        # Jak konsola Windows: bez UTF-8 wprost „RÓŻNICA” nie dałaby się wydrukować.
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )
    assert not done.stderr, done.stderr
    return done.returncode, done.stdout.splitlines()


def test_skrypt_porownuje_baze_z_drzewem_roboczym_z_niezacommitowana_zmiana_a_z_glowa_z_kopia_commitu() -> None:
    with potomne.commit_copy(ROOT, "HEAD") as copy:
        shutil.copy2(SCRIPT, copy / "tools" / "rownowaznosc.py")
        machine_script = copy / "tools" / "uruchom_proces.py"
        exit_codes = '_EXIT_CODES = {"OK": 0,'
        assert exit_codes in machine_script.read_text(encoding="utf-8")
        machine_script.write_text(machine_script.read_text(encoding="utf-8").replace(exit_codes, '_EXIT_CODES = {"OK": 5,'), encoding="utf-8")

        changed = _script(copy, "--baza", "HEAD", "--scenariusz", "przebieg")
        committed = _script(copy, "--baza", "HEAD", "--glowa", "HEAD", "--scenariusz", "przebieg")

    assert changed == (1, ["przebieg | RÓŻNICA | kod 0→5", "RÓWNOWAŻNOŚĆ RÓŻNICA | przebieg"])
    assert committed == (0, ["przebieg | TAK SAMO | kod 0, OK", "RÓWNOWAŻNOŚĆ OK | 1 scenariuszy"])


def _commit_file(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(name, encoding="utf-8")
    return commit(repo, name)


def test_domyslna_baza_to_merge_base_z_origin_main_commitu_glowy_a_bez_niego_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    root = _commit_file(repo, "korzen")
    git(repo, "checkout", "--quiet", "-b", "glowa")
    head = _commit_file(repo, "glowa")
    git(repo, "checkout", "--quiet", "--detach", root)
    main = _commit_file(repo, "main")
    git(repo, "update-ref", "refs/remotes/origin/main", main)
    _commit_file(repo, "head")

    assert (rownowaznosc.default_base(repo, head), rownowaznosc.default_base(repo, None)) == (root, main)


class _BaseComputed(Exception):
    pass


@pytest.mark.parametrize(("arguments", "head"), [(["--glowa", "abc123"], "abc123"), ([], None)])
def test_skrypt_bez_bazy_liczy_domyslna_baze_od_commitu_glowy_a_bez_niego_od_head(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], head: str | None
) -> None:
    def default_base(repository: Path, given: str | None) -> str:
        raise _BaseComputed(repository, given)

    monkeypatch.setattr(rownowaznosc, "default_base", default_base)

    with pytest.raises(_BaseComputed) as computed:
        rownowaznosc.main(arguments)

    assert computed.value.args == (ROOT, head)


class _BaseCopied(Exception):
    pass


def test_skrypt_z_baza_kopiuje_te_baze_bez_liczenia_domyslnej(monkeypatch: pytest.MonkeyPatch) -> None:
    def default_base(repository: Path, given: str | None) -> str:
        raise _BaseComputed(repository, given)

    def commit_copy(repository: Path, commit: str) -> Path:
        raise _BaseCopied(repository, commit)

    monkeypatch.setattr(rownowaznosc, "default_base", default_base)
    monkeypatch.setattr(potomne, "commit_copy", commit_copy)

    with pytest.raises(_BaseCopied) as copied:
        rownowaznosc.main(["--baza", "abc123"])

    assert copied.value.args == (ROOT, "abc123")


def test_nieznany_commit_glowy_to_blad_gita_a_nie_pusta_baza(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "update-ref", "refs/remotes/origin/main", _commit_file(repo, "main"))

    with pytest.raises(subprocess.CalledProcessError):
        rownowaznosc.default_base(repo, "nieznany")


def test_pomoc_wymienia_kazdy_scenariusz_do_wyboru(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        rownowaznosc.main(["--help"])

    # Pomoc łamie długą linię także na łączniku nazwy, więc bez białych znaków każda nazwa jest w całości.
    shown = "".join(capsys.readouterr().out.split())
    assert [scenario.name for scenario in rownowaznosc.SCENARIOS if scenario.name not in shown] == []


_MODULE = '''"""Moduł."""

LIMIT = 10
"""Tyle najwyżej."""


def capped(value: int) -> int:
    return min(value, LIMIT)  # ponad limit przepada
'''


def _repository_with_module(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repo"
    (repository / "src").mkdir(parents=True)
    git(repository, "init", "--quiet")
    (repository / "src" / "modul.py").write_text(_MODULE, encoding="utf-8")
    return repository, commit(repository, "baza")


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("LIMIT = 10", "LIMIT = 11", (1, ["src/modul.py | RÓŻNICA | drzewo składni", "RÓWNOWAŻNOŚĆ RÓŻNICA | src/modul.py"])),
        ('"""Tyle najwyżej."""', '"""Tyle najwyżej, a więcej przepada."""', (0, ["src/modul.py | TAK SAMO", "RÓWNOWAŻNOŚĆ OK | 1 plików"])),
        ("  # ponad limit przepada", "", (0, ["src/modul.py | TAK SAMO", "RÓWNOWAŻNOŚĆ OK | 1 plików"])),
        ('    return', '    """Ponad limit przepada."""\n\n    return', (0, ["src/modul.py | TAK SAMO", "RÓWNOWAŻNOŚĆ OK | 1 plików"])),
    ],
    ids=["zmieniona-stala", "sam-docstring", "sam-komentarz", "komentarz-do-docstringu-funkcji"],
)
def test_tryb_ast_zmieniona_stala_to_roznica_a_sam_docstring_albo_komentarz_to_tak_samo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], old: str, new: str, expected: tuple[int, list[str]]
) -> None:
    repository, base = _repository_with_module(tmp_path)
    module = repository / "src" / "modul.py"
    assert module.read_text(encoding="utf-8").count(old) == 1
    module.write_text(module.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    monkeypatch.setattr(rownowaznosc, "ROOT", repository)

    code = rownowaznosc.main(["--ast", "--baza", base])

    assert (code, capsys.readouterr().out.splitlines()) == expected


def test_tryb_ast_z_glowa_nazywa_plik_po_jednej_stronie_bez_skladni_i_spoza_pythona_a_bez_zmian_jest_niesprawdzony(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository, base = _repository_with_module(tmp_path)
    (repository / "src" / "stary.py").write_text("STARY = 1\n", encoding="utf-8")
    (repository / "src" / "dane.toml").write_text("a = 1\n", encoding="utf-8")
    base = commit(repository, "pliki bazy")
    (repository / "src" / "stary.py").unlink()
    (repository / "src" / "nowy.py").write_text("NOWY = 1\n", encoding="utf-8")
    (repository / "src" / "dane.toml").write_text("a = 2\n", encoding="utf-8")
    (repository / "src" / "modul.py").write_text("def capped(:\n", encoding="utf-8")
    (repository / "poza_src.py").write_text("POZA = 1\n", encoding="utf-8")
    head = commit(repository, "głowa")
    monkeypatch.setattr(rownowaznosc, "ROOT", repository)

    changed = rownowaznosc.main(["--ast", "--baza", base, "--glowa", head]), capsys.readouterr().out.splitlines()
    unchanged = rownowaznosc.main(["--ast", "--baza", head, "--glowa", head]), capsys.readouterr().out.splitlines()

    assert changed == (
        1,
        [
            "src/dane.toml | RÓŻNICA | nie plik Pythona",
            "src/modul.py | RÓŻNICA | plik bez składni Pythona",
            "src/nowy.py | RÓŻNICA | plik tylko w HEAD",
            "src/stary.py | RÓŻNICA | plik tylko w bazie",
            "RÓWNOWAŻNOŚĆ RÓŻNICA | src/dane.toml, src/modul.py, src/nowy.py, src/stary.py",
        ],
    )
    assert unchanged == (2, ["RÓWNOWAŻNOŚĆ NIESPRAWDZONA | 0 plików"])
