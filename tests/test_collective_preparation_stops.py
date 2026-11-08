"""Zatrzymania Przygotowania pliku zbiorczego przy problemach z Rejestrem zleceń i wzorcami."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from dataclasses import replace
from datetime import datetime
import errno
import os
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font
import pytest

from rozliczenia.domain import PhaseFailed, PhaseStarted, ProgressEvent, ProgressPhase
from rozliczenia.intermax_replace import Waiting
from rozliczenia.intermax_ordering import OrderingInputs, order_register
from rozliczenia.run_context import RunContext
from rozliczenia.dad_files import DadFiles
from rozliczenia.preparation_register import register_problem
from rozliczenia.message import StopError

from tests.fixtures.preparation import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    REGISTER_HEADERS,
    PreparationFixture,
    RegisterRow,
    default_register_rows,
    make_dad_layout_fixture,
    make_preparation_fixture,
    month_periods_folder,
    paste_raw_orders,
    register_order,
    run_preparation,
    write_register,
    write_register_sheet,
)
from tests.fixtures.clock import ManualClock
from tests.fixtures.workbooks import (
    break_row_far_below_data_rows,
    cut_sheet_after_data_rows,
    rewrite_parts,
    without_sheet,
    without_styles,
)


def input_snapshot(fixture: PreparationFixture) -> dict[Path, bytes]:
    paths = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path)
    return {path: path.read_bytes() for path in paths if path.exists()}


def stop_preparation(fixture: PreparationFixture, *, dry_run: bool = False) -> StopError:
    """Uruchamia proces, oczekuje zatrzymania i sprawdza, że nic nie powstało ani nie zmieniło się."""

    inputs_before = input_snapshot(fixture)
    periods_before = sorted(path.name for path in fixture.periods_directory.iterdir())

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, dry_run=dry_run)

    assert sorted(path.name for path in fixture.periods_directory.iterdir()) == periods_before
    assert input_snapshot(fixture) == inputs_before
    assert "SYN-" not in raised.value.message.text
    return raised.value


def test_missing_rejestr_zlecen_stops_without_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.register_path.unlink()

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_REJESTRU"
    assert error.message.text == (
        "Co się stało: Nie znaleziono Rejestru zleceń. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, folder {tmp_path.name}\n"
        "Co zrobić: Wybierz właściwy plik Rejestru zleceń i uruchom ponownie."
    )


def test_rejestr_otwarty_w_excelu_zatrzymuje_sprawdzanie_przed_wzorcami(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.register_path.with_name(f"~${fixture.register_path.name}").write_bytes(b"")
    fixture.internal_template_path.unlink()

    error = stop_preparation(fixture)

    assert error.message.code == "REJESTR_OTWARTY"


def test_rejestr_open_in_excel_stops_and_leaves_lock_file(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    lock_file = fixture.register_path.with_name(f"~${fixture.register_path.name}")
    lock_file.write_bytes(b"")

    error = stop_preparation(fixture)

    assert error.message.code == "REJESTR_OTWARTY"
    assert error.message.text == (
        "Co się stało: Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, folder {tmp_path.name}\n"
        "Co zrobić: Zapisz i zamknij Rejestr zleceń w Excelu, potem uruchom ponownie. "
        "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
        "pozostawiony plik ~$ZLECENIA INTERMAX OD 08_11_2021.xlsx i uruchom ponownie."
    )
    assert lock_file.exists()


@pytest.mark.parametrize(
    ("failing", "error"),
    [
        ("read_bytes", PermissionError(errno.EACCES, "The process cannot access the file because it is being used by another process")),
        ("read_bytes", OSError(errno.EIO, "The cloud file provider is not running")),
        ("stat", PermissionError(errno.EACCES, "Permission denied")),
    ],
    ids=["zablokowany-przez-inny-program", "onedrive-bez-sieci", "folder-bez-dostepu"],
)
@pytest.mark.parametrize(
    ("unavailable", "code"),
    [
        ("register_path", "NIEDOSTEPNY_REJESTR"),
        ("internal_template_path", "NIEDOSTEPNY_WZORZEC"),
        ("collective_template_path", "NIEDOSTEPNY_WZORZEC"),
    ],
    ids=["rejestr", "wzorzec-wewnetrzny", "wzorzec-zbiorczy"],
)
def test_plik_niedostepny_do_odczytu_nie_jest_nazwany_uszkodzonym(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unavailable: str, code: str, failing: str, error: OSError
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    original = getattr(Path, failing)
    unavailable_path = getattr(fixture, unavailable)

    def blocked(path: Path, **options: object) -> object:
        if path == unavailable_path:
            raise error
        return original(path, **options)

    monkeypatch.setattr(Path, failing, blocked)

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    assert raised.value.message.code == code
    assert "uszkodzony" not in raised.value.message.text
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize(
    ("removed", "label"),
    [
        ("SKUTECZNE", "SKUTECZNE"),
        ("ADRES", "ADRES"),
        ("NUMER UMOWY", "NUMER UMOWY albo NUMER UMOWY/ZLECENIA ORANGE"),
    ],
)
def test_rejestr_without_required_header_stops_with_header_name(tmp_path: Path, removed: str, label: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(
        fixture.register_path,
        headers=tuple(header for header in REGISTER_HEADERS if header != removed),
    )

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_NAGLOWKA_REJESTRU"
    assert error.message.text == (
        f"Co się stało: W Rejestrze zleceń brakuje wymaganego nagłówka {label}. "
        "Nie utworzono żadnego pliku.\n"
        "Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, wiersz 1\n"
        f"Co zrobić: Dopisz albo popraw nagłówek {label} w pierwszym wierszu arkusza ze zleceniami, "
        "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
    )


def test_rejestr_with_duplicated_required_header_stops_with_header_name(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=(*REGISTER_HEADERS, "WYKONAWCA "))

    error = stop_preparation(fixture)

    assert error.message.code == "POWTORZONY_NAGLOWEK_REJESTRU"
    assert error.message.text == (
        "Co się stało: W Rejestrze zleceń nagłówek WYKONAWCA występuje więcej niż raz, "
        "więc nie wiadomo, z której kolumny brać dane. Nie utworzono żadnego pliku.\n"
        "Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, wiersz 1\n"
        "Co zrobić: Zostaw nagłówek WYKONAWCA tylko w jednej kolumnie, "
        "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
    )


def test_rejestr_with_both_spellings_of_one_header_stops_as_duplicated(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=(*REGISTER_HEADERS, "nr zlecenia"))

    error = stop_preparation(fixture)

    assert error.message.code == "POWTORZONY_NAGLOWEK_REJESTRU"
    assert error.message.what.startswith(
        "W Rejestrze zleceń nagłówek NUMER ZL. albo nr zlecenia występuje więcej niż raz"
    )


def test_rejestr_with_header_repeated_in_other_letter_case_names_it_once(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=(*REGISTER_HEADERS, "adres"))

    error = stop_preparation(fixture)

    assert error.message.code == "POWTORZONY_NAGLOWEK_REJESTRU"
    assert error.message.what.startswith("W Rejestrze zleceń nagłówek ADRES występuje więcej niż raz")


def test_rejestr_without_sheet_with_required_headers_stops(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=("KLIENT", "TELEFON", "WYKONAWCA"))

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_ARKUSZA_ZLECEN"
    assert error.message.text == (
        "Co się stało: W Rejestrze zleceń nie znaleziono arkusza ze zleceniami, czyli arkusza "
        "z wymaganymi nagłówkami w pierwszym wierszu. Nie utworzono żadnego pliku.\n"
        "Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx\n"
        "Co zrobić: Sprawdź, czy wybrano właściwy plik Rejestru zleceń. Pierwszy wiersz arkusza "
        "ze zleceniami musi zawierać nagłówki: DATA GODZ. POCZ., MIASTO, ADRES, UMOWA, URZĄDZENIA, "
        "CZYNNOŚCI, NUMER ZL. albo nr zlecenia, WYKONAWCA, NUMER UMOWY albo NUMER UMOWY/ZLECENIA ORANGE, "
        "SKUTECZNE, "
        "CZYNNOŚCI ZREALIZOWANE."
    )


def add_register_sheet(
    register_path: Path,
    title: str,
    rows: list[RegisterRow],
    *,
    headers: tuple[str, ...] = REGISTER_HEADERS,
    hidden: bool = False,
    first: bool = False,
) -> None:
    """Dopisuje do syntetycznego Rejestru arkusz z nagłówkami w wierszu 1 i wierszami od 2."""

    workbook = load_workbook(register_path)
    sheet = workbook.create_sheet(title, 0 if first else None)
    write_register_sheet(sheet, rows, headers=headers)
    if hidden:
        sheet.sheet_state = "hidden"
    workbook.save(register_path)
    workbook.close()


def test_decoy_sheets_do_not_hide_sheet_with_orders(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(
        fixture.register_path,
        "komentarze",
        [{"UWAGI": "sprawdzić w poniedziałek", "WYKONAWCA": "adrian.testowy"}],
        headers=("DATA GODZ. POCZ.", "WYKONAWCA", "UWAGI"),
        first=True,
    )
    add_register_sheet(
        fixture.register_path,
        "słowniki",
        [{"MIASTO": "POZNAŃ", "UMOWA": "abonament", "SKUTECZNE": "tak"}],
        headers=("MIASTO", "UMOWA", "SKUTECZNE", "URZĄDZENIA"),
        hidden=True,
    )

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (4, 3)
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_period_orders_in_more_than_one_sheet_stop_with_sheet_names(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(fixture.register_path, "ZLECENIA 2", [register_order(7, datetime(2026, 9, 10, 9, 0))])

    error = stop_preparation(fixture)

    assert error.message.code == "ZLECENIA_W_WIELU_ARKUSZACH"
    assert error.message.text == (
        "Co się stało: Zlecenia tego okresu są w więcej niż jednym arkuszu Rejestru zleceń, "
        "więc nie wiadomo, który arkusz jest właściwy. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusze ZLECENIA, ZLECENIA 2, okres {PERIOD}\n"
        "Co zrobić: Zostaw zlecenia tego okresu tylko w jednym arkuszu, "
        "zapisz i zamknij Rejestr zleceń i uruchom ponownie."
    )


def test_sheet_with_orders_of_other_periods_does_not_block_period(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(
        fixture.register_path,
        "archiwum 2025",
        [register_order(8, datetime(2025, 9, 9, 9, 0)), None, register_order(9, datetime(2025, 9, 10, 9, 0))],
        hidden=True,
        first=True,
    )

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (4, 3)


def raw_order(number: int, started: datetime | None, worker: str | None = "adrian.testowy") -> dict[str, object]:
    """Zlecenie z aplikacji do wklejenia na dół Rejestru; ``None``: bez daty albo bez Wykonawcy."""

    order = register_order(number, datetime(2026, 9, 1) if started is None else started)
    if started is None:
        del order["DATA GODZ. POCZ."]
    if worker is None:
        del order["WYKONAWCA"]
    else:
        order["WYKONAWCA"] = worker
    return order


# Domyślny Rejestr kończy się uporządkowanym zleceniem z poniedziałku 14.09 w wierszu 13; wklejenie zaczyna się w 16.
@pytest.mark.parametrize(
    ("pasted", "rows"),
    [
        ([raw_order(11, datetime(2026, 9, 13, 10)), raw_order(12, datetime(2026, 9, 13, 12))], "wiersze 16–17"),
        ([raw_order(11, datetime(2026, 9, 8, 10)), raw_order(12, datetime(2026, 9, 8, 12))], "wiersze 16–17"),
        ([raw_order(11, datetime(2026, 9, 14, 10)), raw_order(12, datetime(2026, 9, 14, 12))], "wiersze 16–17"),
        ([raw_order(11, datetime(2026, 9, 14, 10)), raw_order(12, datetime(2026, 9, 15, 12))], "wiersze 16–17"),
        ([raw_order(11, datetime(2026, 9, 7, 10)), raw_order(12, datetime(2026, 9, 8, 12))], "wiersze 16–17"),
        ([raw_order(11, None), raw_order(12, datetime(2026, 9, 21, 12))], "wiersz 16"),
        ([raw_order(11, datetime(2026, 9, 21, 10)), raw_order(12, None)], "wiersz 17"),
        ([raw_order(11, datetime(2026, 9, 21, 10)), raw_order(12, datetime(2026, 9, 21, 12), worker=None)], "wiersz 17"),
    ],
    ids=[
        "dzien-okresu",
        "pierwszy-dzien-okresu",
        "ostatni-dzien-okresu-juz-uporzadkowany",
        "dzien-okresu-i-nastepny",
        "dzien-poprzedniego-okresu-i-pierwszy-dzien-okresu",
        "bez-daty",
        "bez-daty-w-drugim-wierszu",
        "bez-wykonawcy",
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_surowe_zlecenia_w_okresie_zatrzymuja_sprawdzanie_bez_plikow(
    tmp_path: Path, pasted: list[dict[str, object]], rows: str, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    paste_raw_orders(fixture.register_path, pasted)
    recorded: list[ProgressEvent] = []
    periods_before = sorted(path.name for path in fixture.periods_directory.iterdir())
    register_before = fixture.register_path.read_bytes()

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, dry_run=dry_run, observer=recorded.append)

    assert raised.value.message.text == (
        "Co się stało: Wklejone zlecenia na dole Rejestru zleceń nie są jeszcze uporządkowane, "
        "a mogą należeć do tego okresu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, {rows}\n"
        "Co zrobić: Najpierw uporządkuj INTERMAX w Centrum rozliczeń, potem uruchom ponownie."
    )
    assert not raised.value.message.reports_to_maintainer
    assert [(event.phase, type(event)) for event in recorded] == [
        (ProgressPhase.CHECKING, PhaseStarted),
        (ProgressPhase.CHECKING, PhaseFailed),
    ]
    assert sorted(path.name for path in fixture.periods_directory.iterdir()) == periods_before
    assert fixture.register_path.read_bytes() == register_before


@pytest.mark.parametrize(
    "pasted",
    [
        [raw_order(11, datetime(2026, 9, 15, 10)), raw_order(12, datetime(2026, 9, 15, 12))],
        [raw_order(11, datetime(2026, 9, 15, 10)), raw_order(12, datetime(2026, 9, 16, 12))],
        [raw_order(11, datetime(2026, 9, 7, 10)), raw_order(12, datetime(2026, 9, 7, 12))],
    ],
    ids=["dzien-nastepnego-okresu", "dni-nastepnego-okresu", "dzien-poprzedniego-okresu-juz-uporzadkowany"],
)
def test_surowe_zlecenia_z_dnia_spoza_okresu_nie_zatrzymuja_przygotowania(
    tmp_path: Path, pasted: list[dict[str, object]]
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    paste_raw_orders(fixture.register_path, pasted)

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (4, 3)
    assert fixture.collective_file_path.exists()


def register_with_app_look_row(tmp_path: Path, day: int) -> PreparationFixture:
    """Rejestr, którego dół to trzy uporządkowane zlecenia z ``day``.09, a środkowe ma wygląd z aplikacji (Roboto 8).

    Tak wygląda zlecenie dopisane do uporządkowanego dnia przez skopiowanie z aplikacji albo notatka taty w innej
    czcionce: wiersz bez Calibri 8 nad uporządkowanym, a na dole nic nie jest wklejone. Środkowe zlecenie jest w
    wierszu 17.
    """

    fixture = make_preparation_fixture(
        tmp_path,
        [*default_register_rows(), None, None, *(register_order(7 + hour, datetime(2026, 9, day, 8 + hour)) for hour in range(3))],
    )
    workbook = load_workbook(fixture.register_path)
    for cell in workbook["ZLECENIA"][17]:
        if cell.value is not None:
            cell.font = Font(name="Roboto", size=8)
    workbook.save(fixture.register_path)
    workbook.close()
    return fixture


@pytest.mark.parametrize(("day", "period", "period_orders"), [(16, PERIOD, 4), (16, "15_21_09_2026", 4), (14, PERIOD, 7)])
@pytest.mark.parametrize("dry_run", [False, True])
def test_wiersz_z_wygladem_z_aplikacji_w_uporzadkowanym_dniu_bez_wklejenia_nie_zatrzymuje_przygotowania(
    tmp_path: Path, day: int, period: str, period_orders: int, dry_run: bool
) -> None:
    fixture = register_with_app_look_row(tmp_path, day)

    summary = run_preparation(fixture, period, dry_run=dry_run)

    assert summary.period_order_count == period_orders


def test_surowe_zlecenia_na_dole_zatrzymuja_okres_mimo_wiersza_z_wygladem_z_aplikacji_nad_nimi(tmp_path: Path) -> None:
    fixture = register_with_app_look_row(tmp_path, 16)
    first = paste_raw_orders(
        fixture.register_path, [raw_order(11, datetime(2026, 9, 13, 10)), raw_order(12, datetime(2026, 9, 13, 12))]
    )

    error = stop_preparation(fixture)

    assert (error.message.code, error.message.where) == (
        "SUROWE_ZLECENIA_W_OKRESIE",
        f"plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, wiersze {first}–{first + 1}",
    )


@pytest.mark.parametrize("other_first", [True, False], ids=["drugi-arkusz-przed", "drugi-arkusz-za"])
def test_surowe_zlecenia_w_jednym_z_dwoch_arkuszy_zlecen_zatrzymuja_okres(tmp_path: Path, other_first: bool) -> None:
    fixture = make_preparation_fixture(tmp_path)
    add_register_sheet(
        fixture.register_path, "archiwum 2025", [register_order(8, datetime(2025, 9, 9, 9, 0))], first=other_first
    )
    paste_raw_orders(fixture.register_path, [raw_order(11, datetime(2026, 9, 13, 10)), raw_order(12, datetime(2026, 9, 13, 12))])

    error = stop_preparation(fixture)

    assert (error.message.code, error.message.where) == (
        "SUROWE_ZLECENIA_W_OKRESIE",
        "plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, arkusz ZLECENIA, wiersze 16–17",
    )


def test_powtorzony_naglowek_z_surowymi_zleceniami_w_okresie_zatrzymuje_odczyt_danych_na_naglowku(tmp_path: Path) -> None:
    """Sprawdzanie rozpoznaje arkusz zleceń tak jak Odczyt danych, więc arkusz z powtórzonym nagłówkiem nie jest
    arkuszem zleceń: tata słyszy o nagłówku, a nie o wklejonych zleceniach w kolumnach, których nie wiadomo."""

    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, headers=(*REGISTER_HEADERS, "WYKONAWCA "))
    paste_raw_orders(fixture.register_path, [raw_order(11, datetime(2026, 9, 13, 10)), raw_order(12, datetime(2026, 9, 13, 12))])
    recorded: list[ProgressEvent] = []

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, observer=recorded.append)

    assert raised.value.message.code == "POWTORZONY_NAGLOWEK_REJESTRU"
    assert (recorded[-1].phase, type(recorded[-1])) == (ProgressPhase.READING, PhaseFailed)


def test_okres_po_uporzadkowaniu_intermax_przechodzi_z_uporzadkowanymi_zleceniami(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    paste_raw_orders(
        fixture.register_path,
        [raw_order(11, datetime(2026, 9, 13, 12), "kamil.syntetyczny"), raw_order(12, datetime(2026, 9, 13, 10))],
    )
    clock = ManualClock()
    order_register(
        OrderingInputs(
            fixture.register_path,
            tmp_path / "Kopie INTERMAX",
            now=lambda: datetime(2026, 9, 12, 20),
            waiting=Waiting(clock, clock.pause),
        ),
        RunContext(),
    )

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (6, 5)
    assert fixture.collective_file_path.exists()


def order_fills(path: Path, number: str) -> dict[str, str | None]:
    """Wypełnienie RGB komórek ``URZĄDZENIA``, ``CZYNNOŚCI`` i numeru umowy zlecenia ``number`` w pliku okresu."""

    workbook = load_workbook(path)
    try:
        sheet = workbook.worksheets[0]
        [header] = [row for row in sheet.iter_rows(max_row=20) if any(cell.value == "NUMER ZL." for cell in row)]
        columns = {cell.value: cell.column for cell in header if cell.value}
        first = cast(int, header[0].row) + 1
        [row] = [row for row in range(first, sheet.max_row + 1) if sheet.cell(row, columns["NUMER ZL."]).value == number]
        cells = {name: sheet.cell(row, columns[name]) for name in ("URZĄDZENIA", "CZYNNOŚCI", "NUMER UMOWY/ZLECENIA ORANGE")}
        return {name: cell.fill.fgColor.rgb if cell.fill.fill_type == "solid" else None for name, cell in cells.items()}
    finally:
        workbook.close()


def test_kolor_operatora_z_uporzadkowania_intermax_przechodzi_do_obu_plikow_okresu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    tmobile, fault = raw_order(11, datetime(2026, 9, 13, 12)), raw_order(12, datetime(2026, 9, 13, 10))
    tmobile["CZYNNOŚCI"] = fault["CZYNNOŚCI"] = "TMOBILE"
    fault["URZĄDZENIA"] = "Usterka"
    paste_raw_orders(fixture.register_path, [tmobile, fault])
    clock = ManualClock()
    order_register(
        OrderingInputs(
            fixture.register_path,
            tmp_path / "Kopie INTERMAX",
            now=lambda: datetime(2026, 9, 12, 20),
            waiting=Waiting(clock, clock.pause),
        ),
        RunContext(),
    )

    run_preparation(fixture)

    for path in (fixture.internal_settlement_path, fixture.collective_file_path):
        assert order_fills(path, "ZL-SYN-011") == {
            "URZĄDZENIA": None,
            "CZYNNOŚCI": "FF99FF66",
            "NUMER UMOWY/ZLECENIA ORANGE": "FF99FF66",
        }, path.name
        assert order_fills(path, "ZL-SYN-012") == {
            "URZĄDZENIA": "FFE89CA7",
            "CZYNNOŚCI": None,
            "NUMER UMOWY/ZLECENIA ORANGE": None,
        }, path.name


@pytest.mark.parametrize(
    "damage",
    [
        lambda path: path.write_bytes(b"to nie jest skoroszyt Excela"),
        lambda path: cut_sheet_after_data_rows(path, "xl/worksheets/sheet2.xml"),  # ZLECENIA za arkuszem lista
        without_styles,
        without_sheet,
    ],
    ids=["nie-skoroszyt", "urwany-arkusz-zlecen", "bez-styles-xml", "bez-arkusza"],
)
def test_damaged_rejestr_zlecen_stops_without_files(tmp_path: Path, damage: Callable[[Path], object]) -> None:
    fixture = make_preparation_fixture(tmp_path)
    damage(fixture.register_path)

    error = stop_preparation(fixture)

    assert error.message.code == "USZKODZONY_REJESTR"
    assert error.message.text == (
        "Co się stało: Nie można odczytać Rejestru zleceń. Plik jest uszkodzony "
        "albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik ZLECENIA INTERMAX OD 08_11_2021.xlsx, folder {tmp_path.name}\n"
        "Co zrobić: Sprawdź, czy Rejestr zleceń otwiera się w Excelu i jest zapisany jako .xlsx, "
        "zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie."
    )


def break_tag_of_row_2(data: bytes) -> bytes:
    end = data.index(b"</row>", data.index(b'<row r="2"'))
    return data[:end] + b"</wiersz>" + data[end + len(b"</row>") :]


def text_instead_of_number_in_date_of_row_2(data: bytes) -> bytes:
    value = data.index(b"<v>", data.index(b'<c r="C2"')) + len(b"<v>")
    return data[:value] + b"brak" + data[data.index(b"</v>", value) :]


def _damaged_in_earlier_period(tmp_path: Path, damage: Callable[[bytes], bytes]) -> PreparationFixture:
    """Rejestr, w którym wiersz 2 (zlecenie z 2025 r., daleko przed okresem) jest uszkodzony przez ``damage``."""

    fixture = make_preparation_fixture(tmp_path, [register_order(1, datetime(2025, 3, 4, 8, 0)), *default_register_rows()])
    # ZLECENIA jest za arkuszem lista.
    rewrite_parts(fixture.register_path, lambda name, data: damage(data) if name == "xl/worksheets/sheet2.xml" else data)
    return fixture


def test_rejestr_z_tekstem_zamiast_liczby_w_dacie_wiersza_wczesniejszego_okresu_zatrzymuje_jako_uszkodzony(
    tmp_path: Path,
) -> None:
    fixture = _damaged_in_earlier_period(tmp_path, text_instead_of_number_in_date_of_row_2)

    error = stop_preparation(fixture)

    assert error.message.code == "USZKODZONY_REJESTR"


def test_zepsuty_znacznik_w_wierszu_wczesniejszego_okresu_nie_zatrzymuje_przygotowania_a_diagnoza_go_widzi(
    tmp_path: Path,
) -> None:
    """Przygotowanie czyta z Rejestru tylko wiersze okresu, więc zepsuty XML w wierszu z 2025 r. go nie zatrzymuje;
    Diagnoza czyta cały Rejestr i nazywa go uszkodzonym."""

    (tmp_path / "caly").mkdir()
    (tmp_path / "zepsuty").mkdir()
    intact = run_preparation(_damaged_in_earlier_period(tmp_path / "caly", lambda data: data))
    fixture = _damaged_in_earlier_period(tmp_path / "zepsuty", break_tag_of_row_2)

    summary = run_preparation(fixture)
    diagnosis = register_problem(fixture.register_path, DadFiles())

    assert (summary.period_order_count, summary.successful_order_count) == (intact.period_order_count, intact.successful_order_count)
    assert diagnosis is not None and diagnosis.code == "USZKODZONY_REJESTR"


WZORCE = pytest.mark.parametrize(
    "template_name",
    ["Wzorzec rozliczenia wewnętrznego.xlsx", "Wzorzec pliku zbiorczego.xlsx"],
)


def template_path(fixture: PreparationFixture, template_name: str) -> Path:
    path = fixture.internal_template_path.with_name(template_name)
    assert path in (fixture.internal_template_path, fixture.collective_template_path)
    return path


@WZORCE
def test_missing_wzorzec_stops_without_files(tmp_path: Path, template_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    template_path(fixture, template_name).unlink()

    error = stop_preparation(fixture)

    assert error.message.code == "BRAK_WZORCA"
    assert error.message.text == (
        "Co się stało: Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, folder config\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


@WZORCE
def test_wzorzec_open_in_excel_stops_and_leaves_lock_file(tmp_path: Path, template_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    lock_file = template_path(fixture, template_name).with_name(f"~${template_name}")
    lock_file.write_bytes(b"")

    error = stop_preparation(fixture)

    assert error.message.code == "WZORZEC_OTWARTY"
    assert error.message.text == (
        "Co się stało: Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, folder config\n"
        "Co zrobić: Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. "
        "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
        f"pozostawiony plik ~${template_name} i uruchom ponownie."
    )
    assert lock_file.exists()


@WZORCE
@pytest.mark.parametrize(
    "damage",
    [lambda path: path.write_bytes(b"uszkodzony wzorzec"), without_styles, break_row_far_below_data_rows],
    ids=["nie-skoroszyt", "bez-styles-xml", "zepsuty-wiersz-daleko-pod-danymi"],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_damaged_wzorzec_stops_before_reading_rejestr(
    tmp_path: Path, template_name: str, damage: Callable[[Path], object], dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    damage(template_path(fixture, template_name))
    fixture.register_path.write_bytes(b"uszkodzony Rejestr")

    error = stop_preparation(fixture, dry_run=dry_run)

    assert error.message.code == "USZKODZONY_WZORZEC"
    assert error.message.text == (
        "Co się stało: Nie można odczytać wzorca. Plik jest uszkodzony "
        "albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, folder config\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


@pytest.mark.parametrize(
    ("template_name", "header_cell", "header", "sheet", "row"),
    [
        ("Wzorzec rozliczenia wewnętrznego.xlsx", "G1", "NUMER ZL.", "Arkusz1", 1),
        ("Wzorzec pliku zbiorczego.xlsx", "H17", "WYKONAWCA", "Sheet1", 17),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_wzorzec_without_expected_header_stops_before_reading_rejestr(
    tmp_path: Path, template_name: str, header_cell: str, header: str, sheet: str, row: int, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    path = template_path(fixture, template_name)
    workbook = load_workbook(path, keep_links=True)
    workbook[sheet][header_cell].value = "inna kolumna"
    workbook.save(path)
    workbook.close()
    fixture.register_path.write_bytes(b"uszkodzony Rejestr")

    error = stop_preparation(fixture, dry_run=dry_run)

    assert error.message.code == "ZLY_WZORZEC"
    assert error.message.text == (
        f"Co się stało: We wzorcu brakuje nagłówka {header}, więc nie wiadomo, gdzie wpisać zlecenia. "
        "Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, arkusz {sheet}, wiersz {row}\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


@pytest.mark.parametrize("dry_run", [False, True])
def test_wzorzec_pliku_zbiorczego_with_wykonawca_outside_h_stops_before_reading_rejestr(
    tmp_path: Path, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    workbook = load_workbook(fixture.collective_template_path, keep_links=True)
    sheet = workbook["Sheet1"]
    sheet["G17"].value, sheet["H17"].value = sheet["H17"].value, sheet["G17"].value
    workbook.save(fixture.collective_template_path)
    workbook.close()
    fixture.register_path.write_bytes(b"uszkodzony Rejestr")

    error = stop_preparation(fixture, dry_run=dry_run)

    assert error.message.code == "WYKONAWCA_POZA_H"
    assert error.message.text == (
        "Co się stało: Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie G zamiast w H (wiersz 17). "
        "Nie utworzono żadnego pliku.\n"
        "Gdzie: plik Wzorzec pliku zbiorczego.xlsx, arkusz Sheet1, wiersz 17\n"
        "Co zrobić: Przenieś WYKONAWCA do kolumny H we wzorcu i uruchom ponownie."
    )


@pytest.mark.parametrize(
    ("template_name", "header_cell", "register_header", "header", "sheet", "row"),
    [
        ("Wzorzec rozliczenia wewnętrznego.xlsx", "G1", "nr zlecenia", "NUMER ZL.", "Arkusz1", 1),
        ("Wzorzec rozliczenia wewnętrznego.xlsx", "A1", "DATA GODZ. POCZ.", "DATA", "Arkusz1", 1),
        ("Wzorzec pliku zbiorczego.xlsx", "F17", "nr zlecenia", "NUMER ZL.", "Sheet1", 17),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_wzorzec_with_rejestr_header_instead_of_its_own_stops(
    tmp_path: Path,
    template_name: str,
    header_cell: str,
    register_header: str,
    header: str,
    sheet: str,
    row: int,
    dry_run: bool,
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    path = template_path(fixture, template_name)
    workbook = load_workbook(path, keep_links=True)
    workbook[sheet][header_cell].value = register_header
    workbook.save(path)
    workbook.close()

    error = stop_preparation(fixture, dry_run=dry_run)

    assert error.message.code == "ZLY_WZORZEC"
    assert error.message.where == f"plik {template_name}, arkusz {sheet}, wiersz {row}"
    assert f"brakuje nagłówka {header}," in error.message.what


@pytest.mark.parametrize(
    ("template_name", "merged_range", "sheet"),
    [
        ("Wzorzec rozliczenia wewnętrznego.xlsx", "C5:D5", "Arkusz1"),  # 4. zlecenie okresu
        ("Wzorzec pliku zbiorczego.xlsx", "B19:C20", "Sheet1"),  # 2. i 3. Zlecenie skuteczne
        ("Wzorzec pliku zbiorczego.xlsx", "U19:V19", "Sheet1"),  # Ilości usług 2. Zlecenia skutecznego
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_wzorzec_with_merged_cells_where_orders_go_stops_without_files(
    tmp_path: Path, template_name: str, merged_range: str, sheet: str, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    path = template_path(fixture, template_name)
    workbook = load_workbook(path, keep_links=True)
    workbook[sheet].merge_cells(merged_range)
    workbook.save(path)
    workbook.close()

    error = stop_preparation(fixture, dry_run=dry_run)

    assert error.message.code == "SCALONE_KOMORKI_WZORCA"
    assert error.message.text == (
        "Co się stało: We wzorcu są scalone komórki tam, gdzie trafiają zlecenia, więc nie można ich wpisać. "
        "Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {template_name}, arkusz {sheet}, komórki {merged_range}\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


def test_wzorzec_changed_after_a_run_stops_the_next_run_in_the_same_process(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    run_preparation(fixture, dry_run=True)
    workbook = load_workbook(fixture.collective_template_path, keep_links=True)
    workbook["Sheet1"].merge_cells("B19:C20")
    workbook.save(fixture.collective_template_path)
    workbook.close()

    error = stop_preparation(fixture, dry_run=True)

    assert error.message.code == "SCALONE_KOMORKI_WZORCA"


def test_merged_cells_of_wzorzec_below_written_orders_do_not_stop(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    workbook = load_workbook(fixture.collective_template_path, keep_links=True)
    workbook["Sheet1"].merge_cells("A21:K21")  # pod trzema Zleceniami skutecznymi z wiersza 18
    workbook.save(fixture.collective_template_path)
    workbook.close()

    summary = run_preparation(fixture)

    assert summary.successful_order_count == 3
    assert fixture.collective_file_path.is_file()


@pytest.mark.parametrize("dry_run", [False, True])
def test_in_dad_layout_missing_folder_okresu_stops_without_creating_it(tmp_path: Path, dry_run: bool) -> None:
    fixture = make_dad_layout_fixture(tmp_path)
    fixture.period_directory.rmdir()
    tree_before = sorted(fixture.periods_directory.rglob("*"))

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, dry_run=dry_run)

    assert raised.value.message.code == "BRAK_FOLDERU_OKRESU"
    assert raised.value.message.text == (
        "Co się stało: Nie znaleziono folderu 08_14_09_2026 w żadnym folderze miesiąca. "
        "Nie utworzono żadnego pliku.\n"
        "Gdzie: foldery INEA w folderze Załączniki\n"
        "Co zrobić: Załóż folder 08_14_09_2026 w folderze INEA właściwego miesiąca i uruchom ponownie."
    )
    assert sorted(fixture.periods_directory.rglob("*")) == tree_before


def test_in_dad_layout_folder_inea_of_another_month_does_not_get_missing_folder_okresu(tmp_path: Path) -> None:
    fixture = make_dad_layout_fixture(tmp_path)
    fixture.period_directory.rmdir()
    august = fixture.periods_directory / "Rozliczenia 2026" / "08_Sierpień_2026" / "INEA"
    tree_before = sorted(fixture.periods_directory.rglob("*"))

    with pytest.raises(StopError) as raised:
        run_preparation(replace(fixture, periods_directory=august))

    assert raised.value.message.code == "BRAK_FOLDERU_OKRESU"
    assert raised.value.message.where == "foldery INEA w folderze Załączniki"
    assert sorted(fixture.periods_directory.rglob("*")) == tree_before


def test_in_dad_layout_folder_okresu_in_two_months_stops_with_both_months(tmp_path: Path) -> None:
    fixture = make_dad_layout_fixture(tmp_path)
    (month_periods_folder(fixture.periods_directory, "10_Październik_2026") / PERIOD).mkdir()

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    assert raised.value.message.code == "POWTORZONY_FOLDER_OKRESU"
    assert raised.value.message.where == (
        "Rozliczenia 2026\\09_Wrzesień_2026\\INEA, Rozliczenia 2026\\10_Październik_2026\\INEA"
    )
    assert [list(folder.iterdir()) for folder in fixture.periods_directory.glob(f"*/*/INEA/{PERIOD}")] == [[], []]


def test_missing_folder_okresow_stops_without_creating_it(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.periods_directory.rmdir()

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    assert raised.value.message.code == "BRAK_FOLDERU_OKRESOW"
    assert raised.value.message.text == (
        "Co się stało: Nie znaleziono folderu okresów. Nie utworzono żadnego pliku.\n"
        f"Gdzie: folder {tmp_path.name}\\INEA\n"
        "Co zrobić: Wybierz istniejący folder okresów, w którym są foldery poprzednich tygodni, "
        "i uruchom ponownie."
    )
    assert not fixture.periods_directory.exists()


def test_zlamana_regula_konfiguracji_wykonawcow_zatrzymuje_przygotowanie_ze_szczegolem(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.config_path.write_text("schema_version: 1\nworkers:\n  a: Ten Sam\n  b: ten sam\n", encoding="utf-8")

    error = stop_preparation(fixture)

    assert error.message.code == "ZLA_KONFIGURACJA_WYKONAWCOW"
    assert error.message.text == (
        "Co się stało: Nie można odczytać konfiguracji wykonawców. "
        "Dwóch identyfikatorów wskazuje ten sam plik pracownika: Ten Sam / ten sam\n"
        "Gdzie: plik worker_mapping.yaml, folder config\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


def test_nieczytelna_konfiguracja_wykonawcow_zatrzymuje_przygotowanie_bez_powtorzenia(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.config_path.unlink()
    fixture.config_path.mkdir()

    error = stop_preparation(fixture)

    assert error.message.code == "ZLA_KONFIGURACJA_WYKONAWCOW"
    assert error.message.text == (
        "Co się stało: Nie można odczytać konfiguracji wykonawców.\n"
        "Gdzie: plik worker_mapping.yaml, folder config\n"
        "Co zrobić: Przekaż ten komunikat osobie utrzymującej narzędzie."
    )


@pytest.mark.parametrize("period_directory_exists", [False, True])
def test_failed_save_of_plik_zbiorczy_leaves_no_period_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, period_directory_exists: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    if period_directory_exists:
        fixture.period_directory.mkdir()
    real_replace = os.replace
    saved: list[str] = []

    def replace_first_then_fail(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).name == COLLECTIVE_FILE_NAME:
            raise OSError("wymuszony błąd dysku")
        if Path(target).name == INTERNAL_SETTLEMENT_NAME:
            saved.append(Path(target).name)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace_first_then_fail)

    error = stop_preparation(fixture)

    assert saved == [INTERNAL_SETTLEMENT_NAME]
    assert error.message.code == "BLAD_ZAPISU"
    assert "wymuszony" not in error.message.text
    assert [path.name for path in fixture.periods_directory.iterdir()] == ([PERIOD] if period_directory_exists else [])
    if period_directory_exists:
        assert list(fixture.period_directory.iterdir()) == []


def test_failed_publication_of_plik_zbiorczy_removes_published_rozliczenie_wewnetrzne(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    real_rename = os.rename

    def rename_fails_for_plik_zbiorczy(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == fixture.collective_file_path:
            raise OSError("wymuszony błąd publikacji")
        real_rename(source, target)

    monkeypatch.setattr(os, "rename", rename_fails_for_plik_zbiorczy)

    error = stop_preparation(fixture)

    assert error.message.code == "BLAD_ZAPISU"
    assert list(fixture.period_directory.iterdir()) == []


def test_failed_removal_of_published_rozliczenie_wewnetrzne_names_the_file_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    real_rename, real_unlink = os.rename, os.unlink

    def rename_fails_for_plik_zbiorczy(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == fixture.collective_file_path:
            raise OSError("wymuszony błąd publikacji")
        real_rename(source, target)

    def unlink_fails_for_rozliczenie_wewnetrzne(path: str | os.PathLike[str], **kwargs: object) -> None:
        if Path(path) == fixture.internal_settlement_path:
            raise PermissionError("wymuszony: plik używany przez inny proces")
        real_unlink(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", rename_fails_for_plik_zbiorczy)
    monkeypatch.setattr(os, "unlink", unlink_fails_for_rozliczenie_wewnetrzne)

    error = stop_preparation(fixture)

    assert error.message.code == "BLAD_ZAPISU_POZOSTAL_PLIK"
    assert error.message.text == (
        "Co się stało: Zapisano tylko jeden z dwóch plików okresu i nie udało się go usunąć.\n"
        f"Gdzie: folder INEA\\{PERIOD}, plik {INTERNAL_SETTLEMENT_NAME}\n"
        "Co zrobić: Usuń wskazany plik, bo bez drugiego pliku okresu jest niepełny, i uruchom ponownie. "
        "Jeśli nie daje się go usunąć, odczekaj chwilę. Jeśli błąd wraca, przekaż komunikat osobie "
        "utrzymującej narzędzie."
    )
    assert [path.name for path in fixture.period_directory.iterdir()] == [INTERNAL_SETTLEMENT_NAME]


@pytest.mark.parametrize("period_directory_exists", [False, True])
def test_staging_folder_that_cannot_be_removed_after_publication_does_not_stop_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, period_directory_exists: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    if period_directory_exists:
        fixture.period_directory.mkdir()
    real_rmdir = os.rmdir

    def rmdir_fails_for_staging_folder(path: str | os.PathLike[str], **kwargs: object) -> None:
        if Path(path).name.startswith(f".{PERIOD}.staging-"):
            raise PermissionError("wymuszony: folder trzyma OneDrive")
        real_rmdir(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rmdir", rmdir_fails_for_staging_folder)

    run_preparation(fixture)

    assert sorted(path.name for path in fixture.period_directory.iterdir()) == sorted(
        [INTERNAL_SETTLEMENT_NAME, COLLECTIVE_FILE_NAME]
    )


@pytest.mark.parametrize("period_directory_exists", [False, True])
def test_zatrzymanie_przy_zapisie_wskazuje_folder_tymczasowy_trzymany_przez_onedrive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, period_directory_exists: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    if period_directory_exists:
        fixture.period_directory.mkdir()
    real_rename, real_unlink = os.rename, os.unlink
    staging_prefix = f".{PERIOD}.staging-"

    def first_publication_fails(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) in (fixture.period_directory, fixture.internal_settlement_path):
            raise OSError("wymuszony błąd publikacji")
        real_rename(source, target)

    def unlink_fails_for_staged_period_files(path: str | os.PathLike[str], **kwargs: object) -> None:
        if Path(path).name in (INTERNAL_SETTLEMENT_NAME, COLLECTIVE_FILE_NAME):
            raise PermissionError("wymuszony: plik okresu trzyma OneDrive")
        real_unlink(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", first_publication_fails)
    monkeypatch.setattr(os, "unlink", unlink_fails_for_staged_period_files)

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    staging_left = [path for path in fixture.periods_directory.iterdir() if path.name.startswith(staging_prefix)]
    assert len(staging_left) == 1
    assert raised.value.message.text == (
        "Co się stało: Nie udało się zapisać plików okresu. "
        "Obok Folderu okresu został folder tymczasowy, którego nie udało się usunąć.\n"
        f"Gdzie: folder INEA\\{PERIOD}\n"
        f"Co zrobić: Usuń z folderu INEA każdy folder, którego nazwa zaczyna się od „{staging_prefix}”. "
        "To foldery tymczasowe, nie Folder okresu. Jeśli któregoś nie daje się usunąć, odczekaj chwilę. "
        "Sprawdź, czy folder jest dostępny i czy pliki okresu nie są otwarte, i uruchom ponownie. "
        "Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
    )
    assert not period_directory_exists or list(fixture.period_directory.iterdir()) == []
