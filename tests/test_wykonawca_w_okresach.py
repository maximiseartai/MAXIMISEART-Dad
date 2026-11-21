from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rozliczenia import worker_periods
from rozliczenia.dad_files import DadFiles
from rozliczenia.period_folder import PeriodFolder, PeriodFolderInaccessible
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.worker_periods import InPeriod, NotInPeriods, Unchecked, WorkerPeriods, old_name_periods

from atrapy.preparation import register_order, write_register
from atrapy.settlement import SourceRow, write_source_rows

STARSZY, SRODKOWY, NOWSZY = "03_09_11_2026", "10_16_11_2026", "17_23_11_2026"


def okres(periods: Path, token: str, *loginy: str) -> PeriodFolder:
    folder = PeriodFolder(periods, parse_period_token(token))
    folder.directory.mkdir(parents=True)
    rows = [SourceRow("POZNAŃ", f"syntetyczny adres {number}", login, f"#{number}") for number, login in enumerate(loginy, 1)]
    write_source_rows(folder.collective_file, rows)
    return folder


def rejestr(tmp_path: Path, *loginy: str) -> Path:
    path = tmp_path / "Rejestr.xlsx"
    write_register(path, [register_order(number, datetime(2026, 11, 3, 10), worker=login) for number, login in enumerate(loginy, 1)])
    return path


def test_login_z_najnowszego_okresu_konczy_szukanie_przed_starszym_plikiem_zbiorczym_ktorego_nie_da_sie_przeczytac(
    tmp_path: Path,
) -> None:
    periods = tmp_path / "okresy"
    okres(periods, NOWSZY, "jan.testowy")
    okres(periods, STARSZY, "ewa.przykladowa").collective_file.write_bytes(b"to nie jest skoroszyt")

    found = WorkerPeriods(DadFiles()).find(["Jan.Testowy"], rejestr(tmp_path, "ewa.przykladowa"), periods)

    assert found == InPeriod(NOWSZY)


def test_rejestr_zlecen_ktorego_nie_da_sie_przeczytac_to_niesprawdzony_rejestr(tmp_path: Path) -> None:
    periods = tmp_path / "okresy"
    okres(periods, NOWSZY, "ewa.przykladowa")
    register = tmp_path / "Rejestr.xlsx"
    register.write_bytes(b"to nie jest skoroszyt")

    assert WorkerPeriods(DadFiles()).find(["jan.testowy"], register, periods) == Unchecked("register")


def test_okres_bez_pliku_zbiorczego_nie_zatrzymuje_szukania_a_login_spoza_okresow_ich_nie_ma(tmp_path: Path) -> None:
    periods = tmp_path / "okresy"
    PeriodFolder(periods, parse_period_token(NOWSZY)).directory.mkdir(parents=True)
    okres(periods, STARSZY, "ewa.przykladowa")

    assert WorkerPeriods(DadFiles()).find(["jan.testowy"], rejestr(tmp_path, "ewa.przykladowa"), periods) == NotInPeriods()


def test_drugie_szukanie_nie_czyta_plikow_zbiorczych_niezmienionych_od_pierwszego(tmp_path: Path) -> None:
    periods = tmp_path / "okresy"
    nowszy, starszy = okres(periods, NOWSZY, "ewa.przykladowa"), okres(periods, STARSZY, "ewa.przykladowa")
    register = rejestr(tmp_path, "ewa.przykladowa")
    read: list[Path] = []

    def counted(path: Path) -> bytes:
        read.append(path)
        return path.read_bytes()

    search = WorkerPeriods(DadFiles(source=counted))
    first = search.find(["jan.testowy"], register, periods)
    second = search.find(["jan.testowy"], register, periods)

    assert (first, second) == (NotInPeriods(), NotInPeriods())
    assert [path for path in read if path != register] == [nowszy.collective_file, starszy.collective_file]
    assert read.count(register) == 2


def rozliczenie(periods: Path, token: str, nazwa: str) -> None:
    folder = PeriodFolder(periods, parse_period_token(token))
    folder.worker_settlements.mkdir(parents=True)
    folder.worker_settlement(nazwa).write_bytes(b"")


def test_stara_nazwa_ostrzega_okresami_z_jej_rozliczeniem_od_najnowszego_bez_wzgledu_na_wielkosc_liter(tmp_path: Path) -> None:
    periods = tmp_path / "okresy"
    rozliczenie(periods, STARSZY, "jan testowy")
    rozliczenie(periods, SRODKOWY, "Ewa Przykładowa")
    rozliczenie(periods, NOWSZY, "JAN TESTOWY")

    assert old_name_periods("Jan Testowy", "Jan Nowak", periods) == (NOWSZY, STARSZY)
    assert old_name_periods("Jan Testowy", "jan  TESTOWY", periods) == ()


def test_stara_nazwa_bez_listowania_folderow_nie_daje_okresu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    periods = tmp_path / "okresy"
    rozliczenie(periods, STARSZY, "Jan Testowy")
    rozliczenie(periods, NOWSZY, "Jan Testowy")
    listed = PeriodFolder.worker_settlement_files

    def bez_listowania_nowszego(folder: PeriodFolder) -> tuple[Path, ...]:
        if folder.period.token == NOWSZY:
            raise PeriodFolderInaccessible(folder.worker_settlements)
        return listed(folder)

    monkeypatch.setattr(PeriodFolder, "worker_settlement_files", bez_listowania_nowszego)
    without_folder = old_name_periods("Jan Testowy", "Jan Nowak", periods)

    def bez_folderu_okresow(directory: Path) -> object:
        raise PeriodFolderInaccessible(directory)

    monkeypatch.setattr(worker_periods, "scan_period_folders", bez_folderu_okresow)

    assert (without_folder, old_name_periods("Jan Testowy", "Jan Nowak", periods)) == ((STARSZY,), ())
