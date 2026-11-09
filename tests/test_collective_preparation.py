from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import os
import re
from pathlib import Path
import time
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import column_index_from_string
from openpyxl.utils.datetime import CALENDAR_MAC_1904
import pytest

from rozliczenia.period_folder import PeriodFolder
from rozliczenia.dad_files import DadFiles
from rozliczenia.domain import (
    IssueCountReady,
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    PlanReady,
    ProgressEvent,
    ProgressPhase,
)
from rozliczenia.progress import PhaseState, ProgressProjection
from rozliczenia.message import StopError
from rozliczenia.highlights import PLAIN
from rozliczenia.preparation_register import period_sheets, read, register_problem
from rozliczenia.register_columns import COLUMNS
from rozliczenia.workbook_files import DataCell
from rozliczenia.settlement_period import parse_period_token

from atrapy.preparation import (
    COLLECTIVE_FILE_NAME,
    COLLECTIVE_TEMPLATE_ZERO_ROWS,
    INTERNAL_SETTLEMENT_NAME,
    INTERNAL_TEMPLATE_HEADERS,
    NOT_TRANSFERRED_PREFIXES,
    OLD_REGISTER_HEADERS,
    PERIOD,
    REGISTER_HEADERS,
    TEMPLATE_NARROW_COLUMN_WIDTHS,
    RAW_ORDER_FONT,
    PreparationFixture,
    RegisterRow,
    default_register_rows,
    in_old_layout,
    link_register_order_numbers,
    make_dad_layout_fixture,
    make_preparation_fixture,
    register_order,
    template_column_width,
    write_collective_template,
    write_internal_template,
    write_register,
)
from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, write_synthetic_templates
from atrapy.intermax import like_excel
from atrapy.workbooks import (
    TEMPLATE_VIEW,
    View,
    active_worksheet,
    column_widths,
    external_link_parts,
    hyperlinks,
    marked_for_copy,
    opening_view,
    refused_by_copy,
    rewrite_parts,
    view_of,
    written_by_copy,
)
from tests.fixtures.operacje import projected
from atrapy.preparation import (
    cell_values,
    collective_row,
    incomplete_period_fixture,
)
from tests.fixtures.operacje import other_warnings, run_preparation
from atrapy.interlocutor import Tata


def sheet_rows(path: Path, *, min_row: int, max_col: int) -> list[tuple[object, ...]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return list(sheet.iter_rows(min_row=min_row, max_col=max_col, values_only=True))
    finally:
        workbook.close()


def internal_row(number: int, started: datetime, successful: str, worker: str) -> tuple[object, ...]:
    return (
        started,
        "POZNAŃ",
        f"syntetyczny adres SYN-{number:03d}",
        f"UM-SYN-{number:03d}",
        "dekoder",
        "instalacja",
        f"ZL-SYN-{number:03d}",
        worker,
        f"OR-SYN-{number:03d}",
        successful,
        "montaż",
        None,
        None,
    )


def test_narzedzie_szuka_w_rejestrze_naglowkow_z_pliku_taty() -> None:
    # Atrapy budują Rejestr z kopii nagłówków pliku taty, więc ten test pokazuje rozjazd z register_columns wprost.
    assert ("", "AKCJE", *(column.register_header for column in COLUMNS), "ZWROT", "UWAGI") == REGISTER_HEADERS


def test_rozliczenie_wewnetrzne_contains_exactly_period_orders_in_register_order(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    assert sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=len(INTERNAL_TEMPLATE_HEADERS)) == [
        internal_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.testowy"),
        internal_row(3, datetime(2026, 9, 9, 10, 30), "NIE", "dariusz.fikcyjny2"),
        internal_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.syntetyczny"),
        internal_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.fikcyjny2"),
    ]


def test_plik_zbiorczy_contains_exactly_zlecenia_skuteczne_from_row_18(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    assert cell_values(fixture.collective_file_path, min_row=18, max_row=24, min_col=1, max_col=11) == [
        collective_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.testowy"),
        collective_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.syntetyczny"),
        collective_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.fikcyjny2"),
        *[(None,) * 11] * 4,
    ]


def test_akcje_zwrot_and_uwagi_from_rejestr_stay_out_of_both_period_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    for path in (fixture.internal_settlement_path, fixture.collective_file_path):
        workbook = load_workbook(path)
        try:
            texts = [
                cell.value
                for sheet in workbook.worksheets
                for row in sheet.iter_rows()
                for cell in row
                if isinstance(cell.value, str)
            ]
        finally:
            workbook.close()
        assert [text for text in texts if any(prefix in text for prefix in NOT_TRANSFERRED_PREFIXES.values())] == []


def test_rejestr_in_old_layout_still_fills_both_period_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, in_old_layout(default_register_rows()), headers=OLD_REGISTER_HEADERS)

    run_preparation(fixture)

    assert sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=len(INTERNAL_TEMPLATE_HEADERS)) == [
        internal_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.testowy"),
        internal_row(3, datetime(2026, 9, 9, 10, 30), "NIE", "dariusz.fikcyjny2"),
        internal_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.syntetyczny"),
        internal_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.fikcyjny2"),
    ]
    assert cell_values(fixture.collective_file_path, min_row=18, max_row=20, min_col=1, max_col=11) == [
        collective_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.testowy"),
        collective_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.syntetyczny"),
        collective_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.fikcyjny2"),
    ]


def test_rejestr_in_old_layout_has_no_paste_area_so_rows_with_app_look_do_not_stop_preparation(tmp_path: Path) -> None:
    """Starszy układ Rejestru (bez ``AKCJE`` i ``UWAGI``) nie ma obszaru wklejania, do którego aplikacja firmowa wkleja,
    więc Sprawdzanie nie szuka w nim Surowych zleceń, choć jego wiersze okresu nie mają Calibri 8."""

    fixture = make_preparation_fixture(tmp_path)
    write_register(fixture.register_path, in_old_layout(default_register_rows()), headers=OLD_REGISTER_HEADERS)
    workbook = load_workbook(fixture.register_path)
    sheet = workbook["ZLECENIA"]
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = RAW_ORDER_FONT
    workbook.save(fixture.register_path)
    workbook.close()

    summary = run_preparation(fixture)

    assert summary.period_order_count == 4


def with_drive_to_every_order(
    rows: list[tuple[object, ...]], *, first_column: int, orders: int
) -> list[tuple[object, ...]]:
    """Wiersze Wzorca od ``first_column`` z 1 w V (dojazd) w pierwszych ``orders`` wierszach.

    Domyślne zlecenia mają ``URZĄDZENIA`` ``dekoder``, którego Reguły ilości nie znają, i UMOWA bez druku, więc
    dostają tylko V.
    """

    drive = column_index_from_string("V") - first_column
    return [row[:drive] + (1,) + row[drive + 1 :] if index < orders else row for index, row in enumerate(rows)]


def test_plik_zbiorczy_keeps_wzorzec_rows_1_to_17_quantities_and_formulas(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    template, created = fixture.collective_template_path, fixture.collective_file_path
    assert cell_values(created, min_row=1, max_row=17, min_col=1, max_col=47) == cell_values(
        template, min_row=1, max_row=17, min_col=1, max_col=47
    )
    assert cell_values(created, min_row=18, max_row=30, min_col=12, max_col=47) == with_drive_to_every_order(
        cell_values(template, min_row=18, max_row=30, min_col=12, max_col=47), first_column=12, orders=3
    )
    assert cell_values(created, min_row=18, max_row=18, min_col=14, max_col=14) == [(0,)]
    assert cell_values(created, min_row=18, max_row=18, min_col=47, max_col=47) == [("=N18*$N$1",)]
    workbook = load_workbook(created)
    try:
        assert workbook["Rates"]["B1"].value == 17.5
    finally:
        workbook.close()


def test_przygotowanie_na_syntetycznych_wzorcach_ksztaltu_taty_wypelnia_pliki_okresu_jak_na_testowych(
    tmp_path: Path,
) -> None:
    (tmp_path / "testowe").mkdir()
    (tmp_path / "syntetyczne").mkdir()
    reference = make_preparation_fixture(tmp_path / "testowe")
    templates = write_synthetic_templates(tmp_path / "wzorce")
    fixture = replace(
        make_preparation_fixture(tmp_path / "syntetyczne"),
        internal_template_path=templates / INTERNAL_TEMPLATE,
        collective_template_path=templates / COLLECTIVE_TEMPLATE,
    )

    run_preparation(reference)
    summary = run_preparation(fixture)

    assert other_warnings(summary.warnings) == []
    created, template = fixture.collective_file_path, fixture.collective_template_path
    assert cell_values(created, min_row=18, max_row=21, min_col=1, max_col=11) == cell_values(
        reference.collective_file_path, min_row=18, max_row=21, min_col=1, max_col=11
    )
    assert cell_values(created, min_row=1, max_row=17, min_col=1, max_col=51) == cell_values(
        template, min_row=1, max_row=17, min_col=1, max_col=51
    )
    assert cell_values(created, min_row=18, max_row=21, min_col=14, max_col=51) == with_drive_to_every_order(
        cell_values(template, min_row=18, max_row=21, min_col=14, max_col=51), first_column=14, orders=3
    )
    assert external_link_parts(created) == external_link_parts(template)
    def filled_rows(path: Path) -> int:
        return sum(any(value is not None for value in row) for row in sheet_rows(path, min_row=2, max_col=13))

    assert filled_rows(fixture.internal_settlement_path) == filled_rows(reference.internal_settlement_path) == 4


def test_przygotowanie_leaves_rejestr_and_wzorce_byte_identical(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    inputs = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path)
    before = [path.read_bytes() for path in inputs]

    run_preparation(fixture)

    assert [path.read_bytes() for path in inputs] == before


def test_summary_reports_counts_and_file_names_without_client_data(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    summary = run_preparation(fixture)

    assert summary.period_order_count == 4
    assert summary.successful_order_count == 3
    assert summary.skipped_empty_rows == 5
    assert other_warnings(summary.warnings) == []
    assert summary.internal_settlement_file == fixture.internal_settlement_path
    assert summary.collective_file == fixture.collective_file_path
    assert sorted(path.name for path in fixture.period_directory.iterdir()) == [
        COLLECTIVE_FILE_NAME,
        INTERNAL_SETTLEMENT_NAME,
    ]
    assert "SYN-" not in repr(summary)


def test_existing_empty_folder_okresu_is_allowed(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()

    run_preparation(fixture)

    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_in_dad_layout_period_files_go_to_folder_okresu_found_in_its_month(tmp_path: Path) -> None:
    fixture = make_dad_layout_fixture(tmp_path)

    run_preparation(fixture)

    assert fixture.period_directory.parent.parent.name == "09_Wrzesień_2026"
    assert sorted(path.name for path in fixture.period_directory.iterdir()) == sorted(
        [INTERNAL_SETTLEMENT_NAME, COLLECTIVE_FILE_NAME]
    )
    assert not (fixture.periods_directory / PERIOD).exists()


@pytest.mark.parametrize("levels_up", [0, 1, 2], ids=["INEA", "miesiąc", "rok"])
def test_in_dad_layout_folder_okresow_chosen_inside_another_month_finds_folder_okresu_in_its_month(
    tmp_path: Path, levels_up: int
) -> None:
    fixture = make_dad_layout_fixture(tmp_path)
    august = fixture.periods_directory / "Rozliczenia 2026" / "08_Sierpień_2026" / "INEA"
    chosen = ([august, *august.parents])[levels_up]

    run_preparation(replace(fixture, periods_directory=chosen))

    assert sorted(path.name for path in fixture.period_directory.iterdir()) == sorted(
        [INTERNAL_SETTLEMENT_NAME, COLLECTIVE_FILE_NAME]
    )
    assert not (chosen / PERIOD).exists()
    assert sorted(path.name for path in august.iterdir()) == ["25_31_08_2026"]


@pytest.mark.parametrize("existing_name", [INTERNAL_SETTLEMENT_NAME, COLLECTIVE_FILE_NAME])
def test_nienadpisywanie_stops_when_period_file_exists(tmp_path: Path, existing_name: str) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    existing = fixture.period_directory / existing_name
    existing.write_bytes(b"reczne poprawki taty")

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    message = raised.value.message.text
    assert message == (
        "Co się stało: Plik tego okresu już istnieje, więc nie został nadpisany. "
        "Nie utworzono żadnego pliku.\n"
        f"Gdzie: folder INEA\\{PERIOD}, plik {existing_name}\n"
        "Co zrobić: Sprawdź, czy wybrano właściwy okres. Jeśli plik ma powstać od nowa, "
        "przenieś albo usuń istniejący plik i uruchom ponownie."
    )
    assert raised.value.message.code == "PLIK_OKRESU_ISTNIEJE"
    assert [path.name for path in fixture.period_directory.iterdir()] == [existing_name]
    assert existing.read_bytes() == b"reczne poprawki taty"
    assert [path.name for path in fixture.periods_directory.iterdir()] == [PERIOD]


@pytest.mark.parametrize(
    "token",
    [
        "8_14_09_2026",
        "09_15_09_2026",
        "08_15_09_2026",
        "okres",
        "../14_09_2026",
        # Na przełomie miesięcy i lat miesiąc i rok tokenu są z poniedziałku, nie z wtorku.
        "27_02_10_2026",
        "29_04_12_2026",
        # Wtorek przed poniedziałkiem 1-6 stycznia roku 1 leży przed najwcześniejszą datą Pythona.
        "00_01_01_0001",
    ],
)
def test_invalid_period_token_stops_before_reading_rejestr(tmp_path: Path, token: str) -> None:
    fixture = make_preparation_fixture(tmp_path)

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, token)

    assert raised.value.message.code == "ZLY_TOKEN_OKRESU"
    assert list(fixture.periods_directory.iterdir()) == []


@pytest.mark.parametrize(
    ("token", "tuesday"),
    [("27_02_11_2026", datetime(2026, 10, 27)), ("29_04_01_2027", datetime(2026, 12, 29))],
)
def test_period_crossing_month_or_year_takes_month_and_year_of_monday(
    tmp_path: Path, token: str, tuesday: datetime
) -> None:
    rows: list[RegisterRow] = [
        register_order(1, tuesday - timedelta(minutes=1)),
        register_order(2, tuesday + timedelta(hours=8)),
        register_order(3, tuesday + timedelta(days=7, minutes=-1)),
        register_order(4, tuesday + timedelta(days=7)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture, token)

    assert summary.period_order_count == 2
    assert next(iter(summary.orders_per_day)) == tuesday.date()
    assert PeriodFolder(fixture.periods_directory, parse_period_token(token)).internal_settlement.is_file()


EXPECTED_ORDERS_PER_DAY = {
    date(2026, 9, 8): 1,
    date(2026, 9, 9): 1,
    date(2026, 9, 10): 0,
    date(2026, 9, 11): 0,
    date(2026, 9, 12): 1,
    date(2026, 9, 13): 0,
    date(2026, 9, 14): 1,
}


def test_summary_reports_orders_per_day_for_every_day_of_the_period(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    summary = run_preparation(fixture)

    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY
    assert list(summary.orders_per_day) == sorted(EXPECTED_ORDERS_PER_DAY)


def test_dry_run_returns_plan_with_orders_per_day_and_writes_nothing(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    inputs = (fixture.register_path, fixture.internal_template_path, fixture.collective_template_path)
    before = [path.read_bytes() for path in inputs]

    summary = run_preparation(fixture, dry_run=True)

    assert summary.period_order_count == 4
    assert summary.successful_order_count == 3
    assert summary.skipped_empty_rows == 5
    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY
    assert summary.internal_settlement_file == fixture.internal_settlement_path
    assert summary.collective_file == fixture.collective_file_path
    assert list(fixture.periods_directory.iterdir()) == []
    assert [path.read_bytes() for path in inputs] == before


def test_rejestr_replaced_after_podglad_by_one_of_the_same_size_and_time_is_read_anew_by_run(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    before = fixture.register_path.stat()
    run_preparation(fixture, dry_run=True)
    write_register(fixture.register_path, default_register_rows()[:-1])
    with zipfile.ZipFile(fixture.register_path, "a") as archive:
        archive.comment = b" " * (before.st_size - fixture.register_path.stat().st_size)
    os.utime(fixture.register_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = fixture.register_path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

    summary = run_preparation(fixture)

    assert summary.period_order_count == 3
    assert summary.successful_order_count == 2


def test_rejestr_row_ending_before_the_last_column_has_an_empty_general_cell_there(tmp_path: Path) -> None:
    path = tmp_path / "Rejestr.xlsx"
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.append([column.register_header for column in COLUMNS])
    sheet.append([datetime(2026, 9, 8, 9, 0), "syntetyczne miasto"])
    workbook.save(path)
    rewrite_parts(  # bez wymiaru arkusza openpyxl daje wiersz tylko do jego ostatniej komórki
        path, lambda name, data: re.sub(rb"<dimension [^>]*/>", b"", data) if name.startswith("xl/worksheets/") else data
    )

    [register] = period_sheets(read(path, DadFiles()), None)

    [row] = register.register_rows
    assert row.cells["CZYNNOŚCI ZREALIZOWANE"] == DataCell(None, PLAIN, "General", None)
    assert row.cells["MIASTO"].value == "syntetyczne miasto"


def test_odczyt_danych_okresu_ma_wiersze_od_dnia_przed_okresem_do_dnia_po_nim(tmp_path: Path) -> None:
    """Odczyt danych okresu ma wiersze od pierwszego do ostatniego z datą z dniem zapasu z obu stron okresu (openpyxl
    zaokrągla część dnia do milisekund), a Planowanie bierze z nich tylko zlecenia okresu."""

    period = parse_period_token(PERIOD)
    days = [period.start + timedelta(days=offset, hours=9) for offset in range(-4, 11)]
    orders: list[RegisterRow] = [register_order(number, day) for number, day in enumerate(days, start=1)]
    path = write_register(tmp_path / "Rejestr.xlsx", orders)

    [sheet] = period_sheets(read(path, DadFiles()), period)

    margin = timedelta(days=1)
    window = [row for row, day in enumerate(days, start=2) if period.start - margin <= day < period.end + margin]
    assert [row.number for row in sheet.register_rows] == window


def test_rejestr_rows_remembered_after_podglad_cannot_be_changed(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    link_register_order_numbers(fixture.register_path, "https://firma.example/zlecenie/")
    row = period_sheets(read(fixture.register_path, DadFiles()), parse_period_token(PERIOD))[0].register_rows[0]
    header, cell = next((header, cell) for header, cell in row.cells.items() if cell.hyperlink is not None)

    with pytest.raises(TypeError):
        row.cells[header] = cell  # type: ignore[index]
    with pytest.raises(TypeError):
        row.quantities[header] = 1  # type: ignore[index]


def test_podglad_of_another_period_does_not_change_what_run_reads_from_the_same_rejestr(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    run_preparation(fixture, "15_21_09_2026", dry_run=True)

    summary = run_preparation(fixture)

    assert summary.period_order_count == 4
    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY


STAGES_IN_ORDER = [
    (ProgressPhase.CHECKING, PhaseStarted),
    (ProgressPhase.CHECKING, PhaseEnded),
    (ProgressPhase.READING, PhaseStarted),
    (ProgressPhase.READING, PhaseEnded),
    (ProgressPhase.READING, IssueCountReady),
    (ProgressPhase.PLANNING, PhaseStarted),
    (ProgressPhase.PLANNING, PhaseEnded),
    (ProgressPhase.PLANNING, PlanReady),
    (ProgressPhase.SAVING, PhaseStarted),
    (ProgressPhase.SAVING, PhaseEnded),
]


@pytest.mark.parametrize("dry_run", [False, True])
def test_zdarzenia_przebiegu_pass_four_stages_in_order_without_worker_events(
    tmp_path: Path, dry_run: bool
) -> None:
    fixture = make_preparation_fixture(tmp_path, [register_order(1, datetime(2026, 9, 13, 23, 59))])
    recorded: list[ProgressEvent] = []
    projection = ProgressProjection()

    def recording_observer(event: ProgressEvent) -> None:
        recorded.append(event)
        projection.update(event)

    summary = run_preparation(fixture, dry_run=dry_run, observer=recording_observer)

    assert [(event.phase, type(event)) for event in recorded] == STAGES_IN_ORDER
    assert set(projection.snapshot.phase_states.values()) == {PhaseState.COMPLETED}
    assert [warning.code for warning in summary.warnings] == ["NIEPELNY_OKRES", "NIEZNANE_URZADZENIA", "KOLUMNY_Z_OPISU"]
    assert projection.snapshot.issue_count == 3
    assert projection.snapshot.template_total == 0
    assert "SYN-" not in repr(recorded)


def test_progress_projection_accepts_przygotowanie_pliku_zbiorczego_interrupted_in_zapisywanie_with_its_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    projection = ProgressProjection()
    save_s = 0.05

    real_replace = os.replace

    def fail_replacing_period_file(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).suffix != ".xlsx":
            real_replace(source, target)
            return
        time.sleep(save_s)
        raise OSError("wymuszony błąd")

    monkeypatch.setattr(os, "replace", fail_replacing_period_file)

    with pytest.raises(StopError):
        run_preparation(fixture, observer=projected(projection))

    assert projection.snapshot.phase_states == {
        ProgressPhase.CHECKING: PhaseState.COMPLETED,
        ProgressPhase.READING: PhaseState.COMPLETED,
        ProgressPhase.PLANNING: PhaseState.COMPLETED,
        ProgressPhase.SAVING: PhaseState.FAILED,
    }
    assert projection.snapshot.phase_durations_ms[ProgressPhase.SAVING] >= save_s * 1000


def test_nienadpisywanie_przerywa_przygotowanie_w_sprawdzaniu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    fixture.period_directory.mkdir()
    fixture.collective_file_path.write_bytes(b"reczne poprawki taty")
    recorded: list[ProgressEvent] = []

    with pytest.raises(StopError):
        run_preparation(fixture, observer=recorded.append)

    assert [(event.phase, type(event)) for event in recorded] == [
        (ProgressPhase.CHECKING, PhaseStarted),
        (ProgressPhase.CHECKING, PhaseFailed),
    ]


def test_failing_observer_is_detached_and_does_not_change_result_or_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    calls = 0

    def failing_observer(event: ProgressEvent) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("awaria podglądu")

    summary = run_preparation(fixture, observer=failing_observer)

    assert calls == 1
    assert summary.period_order_count == 4
    assert summary.successful_order_count == 3
    assert summary.orders_per_day == EXPECTED_ORDERS_PER_DAY
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def cell_formats(path: Path, coordinates: list[str]) -> dict[str, tuple[object, ...]]:
    """Wypełnienie, kolor czcionki, pogrubienie i kursywa wskazanych komórek."""

    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        formats: dict[str, tuple[object, ...]] = {}
        for coordinate in coordinates:
            cell = sheet[coordinate]
            fill = cell.fill.fgColor.rgb if cell.fill.fill_type == "solid" else None
            # Kolor motywu (domyślny tekst) nie jest wyróżnieniem.
            color = cell.font.color.rgb if cell.font.color is not None and cell.font.color.type == "rgb" else None
            formats[coordinate] = (fill, color, bool(cell.font.b), bool(cell.font.i))
        return formats
    finally:
        workbook.close()


def test_highlights_from_rejestr_reach_both_files_and_plain_cells_get_none(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    # Zlecenie 2: ADRES żółty, pogrubiony, czerwoną czcionką; zlecenie 4: ADRES niebieski, WYKONAWCA kursywą;
    # zlecenie 6 i reszta bez wyróżnień.
    assert cell_formats(fixture.internal_settlement_path, ["C2", "C4", "H4", "B2", "C3", "C5", "H2"]) == {
        "C2": ("FFFFFF00", "FFC00000", True, False),
        "C4": ("FF00B0F0", None, False, False),
        "H4": (None, None, False, True),
        "B2": (None, None, False, False),
        "C3": (None, None, False, False),
        "C5": (None, None, False, False),
        "H2": (None, None, False, False),
    }
    assert cell_formats(fixture.collective_file_path, ["B18", "B19", "H19", "A18", "B20", "H18"]) == {
        "B18": ("FFFFFF00", "FFC00000", True, False),
        "B19": ("FF00B0F0", None, False, False),
        "H19": (None, None, False, True),
        "A18": (None, None, False, False),
        "B20": (None, None, False, False),
        "H18": (None, None, False, False),
    }


def test_numer_zlecenia_w_obu_plikach_okresu_ma_hiperlacze_z_rejestru_bez_zmiany_wygladu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    links = link_register_order_numbers(fixture.register_path, "https://przyklad.invalid/zlecenie?tw=1&caseId=SYN-")

    run_preparation(fixture)

    # Zlecenia okresu: wiersze Rejestru 4, 6, 9 i 13; skuteczne: 4, 9 i 13. NUMER ZL. jest w I, G i F.
    assert hyperlinks(fixture.internal_settlement_path) == {
        "G2": links[4],
        "G3": links[6],
        "G4": links[9],
        "G5": links[13],
    }
    assert hyperlinks(fixture.collective_file_path) == {"F18": links[4], "F19": links[9], "F20": links[13]}
    assert cell_formats(fixture.collective_file_path, ["F18"]) == {"F18": (None, None, False, False)}
    workbook = load_workbook(fixture.collective_file_path)
    try:
        assert active_worksheet(workbook)["F18"].font.u is None
    finally:
        workbook.close()


def test_hiperlacze_wzorca_w_zapisanym_wierszu_znika_a_poza_nim_zostaje(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    for path, cells in (
        (fixture.internal_template_path, ("A1", "G2", "C3")),
        (fixture.collective_template_path, ("A1", "B18", "F18", "F23")),
    ):
        workbook = load_workbook(path)
        try:
            sheet = active_worksheet(workbook)
            for coordinate in cells:
                sheet[coordinate].value = sheet[coordinate].value or "pole Wzorca"
                sheet[coordinate].hyperlink = f"https://przyklad.invalid/wzorzec/{coordinate}"
            workbook.save(path)
        finally:
            workbook.close()

    run_preparation(fixture)

    # Zapisane wiersze: 2–5 Rozliczenia wewnętrznego, 18–20 Pliku zbiorczego.
    assert hyperlinks(fixture.internal_settlement_path) == {"A1": "https://przyklad.invalid/wzorzec/A1"}
    assert hyperlinks(fixture.collective_file_path) == {
        "A1": "https://przyklad.invalid/wzorzec/A1",
        "F23": "https://przyklad.invalid/wzorzec/F23",
    }


def test_data_column_keeps_date_format_from_rejestr(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    internal = load_workbook(fixture.internal_settlement_path)
    collective = load_workbook(fixture.collective_file_path)
    try:
        internal_dates = [active_worksheet(internal).cell(row, 1) for row in range(2, 6)]
        collective_dates = [active_worksheet(collective).cell(row, 7) for row in range(18, 21)]
        assert {
            (type(cell.value), cell.number_format) for cell in internal_dates + collective_dates
        } == {(datetime, "dd.mm.yyyy hh:mm")}
    finally:
        internal.close()
        collective.close()


@dataclass(frozen=True)
class SheetLayout:
    """Szerokości kolumn, wysokości wierszy, nagłówek z formatowaniem i blokada wierszy."""

    widths: list[float | None]
    heights: list[float | None]
    header: list[tuple[object, ...]]
    freeze_panes: str | None


def sheet_layout(path: Path, *, header_row: int) -> SheetLayout:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return SheetLayout(
            widths=column_widths(sheet, 47),
            heights=[sheet.row_dimensions[row].height for row in range(1, header_row + 1)],
            header=[
                (cell.value, cell.font.name, cell.font.sz, cell.font.b, cell.fill.fgColor.rgb)
                for cell in sheet[header_row][:47]
            ],
            freeze_panes=sheet.freeze_panes,
        )
    finally:
        workbook.close()


@pytest.mark.parametrize("kind", ["internal", "collective"])
def test_column_widths_header_and_frozen_row_equal_wzorzec(tmp_path: Path, kind: str) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    if kind == "internal":
        template, created, header_row = fixture.internal_template_path, fixture.internal_settlement_path, 1
    else:
        template, created, header_row = fixture.collective_template_path, fixture.collective_file_path, 17
    expected = sheet_layout(template, header_row=header_row)
    assert expected.freeze_panes == f"A{header_row + 1}"
    # Szerokości Wzorca, łącznie z jego bardzo wąskimi kolumnami.
    leading = range(1, max(TEMPLATE_NARROW_COLUMN_WIDTHS) + 1)
    assert expected.widths[: len(leading)] == [template_column_width(column) for column in leading]
    assert sheet_layout(created, header_row=header_row) == expected


# Widok Wzorca przewinięty w bok i powiększony inaczej niż Wzorce taty: plik okresu bierze widok ze swojego Wzorca.
SCROLLED_VIEW = View("C1", "D30", 60)


@pytest.mark.parametrize("view", [TEMPLATE_VIEW, SCROLLED_VIEW], ids=["lewy-gorny-rog-75", "przewiniety"])
@pytest.mark.parametrize("copied", [True, False], ids=["kopia", "openpyxl"])
def test_plik_zbiorczy_i_rozliczenie_wewnetrzne_otwieraja_sie_z_widokiem_swojego_wzorca(
    tmp_path: Path, copied: bool, view: View
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    write_internal_template(fixture.internal_template_path, view=view)
    marked_for_copy(write_collective_template(fixture.collective_template_path, view=view))
    if not copied:
        refused_by_copy(fixture.collective_template_path)

    run_preparation(fixture)

    assert written_by_copy(fixture.collective_file_path) == copied
    for template, created in (
        (fixture.internal_template_path, fixture.internal_settlement_path),
        (fixture.collective_template_path, fixture.collective_file_path),
    ):
        expected = opening_view(template)
        assert view_of(expected) == view
        assert opening_view(created) == expected, created.name


def test_plik_zbiorczy_columns_outside_a_to_l_keep_wzorzec_formatting(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    def formats(path: Path) -> list[tuple[object, ...]]:
        workbook = load_workbook(path)
        try:
            sheet = active_worksheet(workbook)
            return [
                (cell.coordinate, cell.fill.fill_type, cell.fill.fgColor.rgb, cell.number_format, cell.font.name)
                for row in sheet.iter_rows(min_row=18, max_row=24, min_col=13, max_col=47)
                for cell in row
            ]
        finally:
            workbook.close()

    expected = formats(fixture.collective_template_path)
    assert ("N18", "solid", "FFCCE5FF", "0", "Calibri") in expected
    assert formats(fixture.collective_file_path) == expected


def autofilter_range(path: Path) -> str | None:
    workbook = load_workbook(path)
    try:
        ref: str | None = active_worksheet(workbook).auto_filter.ref
        return ref
    finally:
        workbook.close()


def test_autofilter_covers_header_and_last_order_row_in_both_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    run_preparation(fixture)

    # Wzorce mają zakres B:C do wiersza +40, który ma zostać zignorowany.
    # Rozliczenie wewnętrzne: nagłówki A:M i 4 zlecenia okresu.
    assert autofilter_range(fixture.internal_settlement_path) == "A1:M5"
    # Plik zbiorczy: nagłówki wiersza 17 od A do AP i 3 Zlecenia skuteczne.
    assert autofilter_range(fixture.collective_file_path) == "A17:AP20"


def test_autofilter_covers_only_header_when_period_has_no_zlecenia_skuteczne(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [register_order(1, datetime(2026, 9, 9, 10, 0), successful="nie")]
    fixture = make_preparation_fixture(tmp_path, rows)

    run_preparation(fixture)

    assert autofilter_range(fixture.internal_settlement_path) == "A1:M2"
    assert autofilter_range(fixture.collective_file_path) == "A17:AP17"


REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"


def stop_message(fixture: PreparationFixture) -> StopError:
    """Uruchamia Przygotowanie, oczekuje zatrzymania i sprawdza, że nic nie powstało."""

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)
    assert list(fixture.periods_directory.iterdir()) == []
    assert "SYN-" not in raised.value.message.text
    return raised.value


def test_row_without_date_between_period_orders_stops_with_register_row_numbers(tmp_path: Path) -> None:
    undated = register_order(90, datetime(2026, 9, 9, 8, 0))
    undated["DATA GODZ. POCZ."] = "środa rano"
    blank_date = register_order(91, datetime(2026, 9, 9, 9, 0))
    blank_date["DATA GODZ. POCZ."] = None
    rows: list[RegisterRow] = [
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        undated,
        None,
        blank_date,
        register_order(3, datetime(2026, 9, 10, 8, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "WIERSZ_BEZ_DATY"
    assert error.message.text == (
        "Co się stało: Między zleceniami okresu są wiersze z danymi bez poprawnej daty "
        "w kolumnie DATA GODZ. POCZ. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, wiersze 3, 5\n"
        "Co zrobić: Wpisz poprawną datę w kolumnie DATA GODZ. POCZ. we wskazanych wierszach Rejestru "
        "zleceń albo wyczyść wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, i uruchom ponownie."
    )


def test_rows_without_date_outside_period_orders_do_not_stop(tmp_path: Path) -> None:
    note_before = register_order(90, datetime(2026, 9, 1))
    note_before["DATA GODZ. POCZ."] = "uwaga"
    note_after = register_order(91, datetime(2026, 9, 1))
    note_after["DATA GODZ. POCZ."] = "uwaga"
    rows: list[RegisterRow] = [
        note_before,
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(3, datetime(2026, 9, 10, 8, 0)),
        note_after,
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert summary.period_order_count == 2
    assert summary.skipped_empty_rows == 1


def earlier_orders(count: int, first_number: int) -> list[RegisterRow]:
    """Zlecenia z 2025 r., jak historia Rejestru zleceń sprzed okresu."""

    return [register_order(first_number + index, datetime(2025, 3, 4, 8, 0) + timedelta(days=index)) for index in range(count)]


def without_date(number: int, value: object) -> dict[str, object]:
    return register_order(number, datetime(2026, 9, 9, 8, 0)) | {"DATA GODZ. POCZ.": value}


@pytest.mark.parametrize("value", ["09.09.2026 08:00", "=DATE(2026,9,9)+TIME(8,0,0)"], ids=["tekst", "formula"])
def test_row_without_date_between_period_orders_separated_by_other_periods_stops(tmp_path: Path, value: str) -> None:
    rows: list[RegisterRow] = [
        *earlier_orders(20, 100),
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        *earlier_orders(5, 200),
        without_date(90, value),
        *earlier_orders(5, 300),
        register_order(3, datetime(2026, 9, 14, 8, 0)),  # spóźnione zlecenie okresu
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "WIERSZ_BEZ_DATY"
    assert error.message.where == f"plik {REGISTER_NAME}, arkusz ZLECENIA, wiersz 28"


def test_rows_without_date_next_to_period_orders_after_register_history_do_not_stop(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        *earlier_orders(20, 100),
        without_date(90, "08.09.2026 07:00"),
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(3, datetime(2026, 9, 10, 8, 0)),
        without_date(91, "10.09.2026 09:00"),
        *earlier_orders(5, 200),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.skipped_empty_rows) == (2, 1)


def test_period_orders_after_register_history_keep_values_highlights_and_hyperlinks_of_their_rows(
    tmp_path: Path,
) -> None:
    rows: list[RegisterRow] = [
        *earlier_orders(30, 100),
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(3, datetime(2026, 9, 10, 8, 0), successful="nie"),
        *earlier_orders(5, 200),
        register_order(4, datetime(2026, 9, 14, 18, 0)),
        *earlier_orders(3, 300),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)
    links = link_register_order_numbers(fixture.register_path, "https://przyklad.invalid/zlecenie?caseId=SYN-")
    workbook = load_workbook(fixture.register_path)
    workbook["ZLECENIA"]["E40"].fill = PatternFill(fill_type="solid", fgColor="FFFFFF00")
    workbook.save(fixture.register_path)
    workbook.close()

    summary = run_preparation(fixture)

    # Wiersze Rejestru: historia 2–31, zlecenia okresu 32, 34 i 40 (ADRES w E, NUMER ZL. w I).
    assert (summary.period_order_count, summary.successful_order_count, summary.skipped_empty_rows) == (3, 2, 1)
    assert [row[6] for row in sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=13)] == [
        "ZL-SYN-002",
        "ZL-SYN-003",
        "ZL-SYN-004",
    ]
    assert hyperlinks(fixture.collective_file_path) == {"F18": links[32], "F19": links[40]}
    assert cell_formats(fixture.internal_settlement_path, ["C2", "C3", "C4"]) == {
        "C2": (None, None, False, False),
        "C3": (None, None, False, False),
        "C4": ("FFFFFF00", None, False, False),
    }


def iso_dates(workbook: Workbook) -> None:
    workbook.iso_dates = True


def mac_1904_dates(workbook: Workbook) -> None:
    workbook.epoch = CALENDAR_MAC_1904


@pytest.mark.parametrize("dates", [mac_1904_dates, iso_dates], ids=["system-dat-1904", "daty-tekstem-iso"])
def test_rejestr_with_other_date_notation_gives_same_period_files(
    tmp_path: Path, dates: Callable[[Workbook], None]
) -> None:
    rows = [*earlier_orders(10, 100), *default_register_rows(), *earlier_orders(3, 200)]
    (tmp_path / "1900").mkdir()
    (tmp_path / "zapis").mkdir()
    expected_fixture = make_preparation_fixture(tmp_path / "1900", rows)
    fixture = make_preparation_fixture(tmp_path / "zapis", rows)
    workbook = load_workbook(fixture.register_path)
    dates(workbook)
    workbook.save(fixture.register_path)
    workbook.close()

    expected = run_preparation(expected_fixture)
    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count, summary.skipped_empty_rows) == (
        expected.period_order_count,
        expected.successful_order_count,
        expected.skipped_empty_rows,
    )
    assert summary.period_order_count == 4
    for path, expected_path in (
        (fixture.internal_settlement_path, expected_fixture.internal_settlement_path),
        (fixture.collective_file_path, expected_fixture.collective_file_path),
    ):
        assert sheet_rows(path, min_row=1, max_col=13) == sheet_rows(expected_path, min_row=1, max_col=13)


def _shared_formula_from_history(tmp_path: Path) -> PreparationFixture:
    """Rejestr z 10 zleceniami historii w wierszach 2–11, dwoma zleceniami okresu w wierszach 12–13, w których M to
    wspólna formuła z formułą główną w wierszu 2 historii, jak zapisuje ją Excel, i dwoma zleceniami po okresie w
    wierszach 14–15 z własną wspólną formułą M z formułą główną w wierszu 14."""

    rows: list[RegisterRow] = [
        *earlier_orders(10, 100),
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        register_order(3, datetime(2026, 9, 10, 8, 0)),
        register_order(4, datetime(2026, 9, 17, 8, 0)),
        register_order(5, datetime(2026, 9, 18, 8, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)
    workbook = load_workbook(fixture.register_path)
    for row in (2, 12, 13, 14, 15):
        workbook["ZLECENIA"].cell(row, 13).value = f"=N{row}"
    workbook.save(fixture.register_path)
    workbook.close()

    def share(name: str, data: bytes) -> bytes:
        if name != "xl/worksheets/sheet2.xml":
            return data
        # Jak Excel: formuła główna w wierszu 2, w wierszach okresu tylko odwołanie do niej.
        data = data.replace(b"<f>N2</f>", b'<f t="shared" ref="M2:M13" si="0">N2</f>')
        data = data.replace(b"<f>N12</f>", b'<f t="shared" si="0"/>').replace(b"<f>N13</f>", b'<f t="shared" si="0"/>')
        return data.replace(b"<f>N14</f>", b'<f t="shared" ref="M14:M15" si="1">N14</f>').replace(b"<f>N15</f>", b'<f t="shared" si="1"/>')

    rewrite_parts(fixture.register_path, share)
    return fixture


def test_shared_formula_from_register_history_reaches_period_order(tmp_path: Path) -> None:
    fixture = _shared_formula_from_history(tmp_path)

    run_preparation(fixture)

    assert [row[10] for row in sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=13)] == ["=N12", "=N13"]


def test_kopia_wejscia_rejestru_ma_tylko_wiersze_okresu_bez_wiersza_historii_z_formula_glowna(tmp_path: Path) -> None:
    """Przygotowanie czyta z Rejestru zleceń tylko wiersze od pierwszego do ostatniego, którego data może leżeć w
    okresie (``OrderSheets.period_rows``): wiersz historii z formułą główną wspólnej formuły wierszy okresu i wiersz za
    ostatnim zleceniem okresu nie trafiają do Kopii wejścia ani jako wiersz, ani jako pusty wiersz."""

    fixture = _shared_formula_from_history(tmp_path)
    files = DadFiles().for_run()

    run_preparation(fixture, files=files)

    assert files.copy is not None
    [register] = [copied for copied in files.copy.files() if copied.name == fixture.register_path.name]
    [orders] = [sheet for sheet in register.sheets if sheet.name == "ZLECENIA"]
    assert ([row.number for row in orders.rows], orders.empty_rows) == ([12, 13], ())


def test_period_without_orders_stops(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 7, 15, 0)),
        None,
        register_order(5, datetime(2026, 9, 15, 0, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "BRAK_ZLECEN_OKRESU"
    assert error.message.text == (
        "Co się stało: W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, okres {PERIOD}\n"
        "Co zrobić: Sprawdź, czy wybrano właściwy okres i czy eksport zleceń do Rejestru został "
        "zrobiony i zapisany, i uruchom ponownie."
    )


SKUTECZNE_ACTION = (
    "Co zrobić: Wpisz tak albo nie we wskazanych komórkach Rejestru zleceń. "
    "Zapisz i zamknij Rejestr, i uruchom ponownie."
)


def with_skuteczne(order: dict[str, object], value: object) -> dict[str, object]:
    """Zlecenie z dowolną odczytaną wartością ``SKUTECZNE``, także nie-tekstem."""

    return order | {"SKUTECZNE": value}


def test_period_orders_without_tak_or_nie_in_skuteczne_stop_with_empty_and_other_cells(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 7, 15, 0), successful="???"),  # poprzedni okres, wiersz 2
        register_order(2, datetime(2026, 9, 8, 8, 0), successful=""),
        with_skuteczne(register_order(3, datetime(2026, 9, 8, 9, 0)), None),
        register_order(4, datetime(2026, 9, 9, 8, 0), successful=" NIE "),
        register_order(5, datetime(2026, 9, 9, 9, 0), successful="   "),
        register_order(6, datetime(2026, 9, 10, 8, 0), successful="Tak"),
        register_order(7, datetime(2026, 9, 11, 8, 0), successful="TAK/NIE\nsprawdzić"),
        register_order(8, datetime(2026, 9, 12, 8, 0), successful="nie"),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "ZLE_SKUTECZNE"
    assert error.message.text == (
        "Co się stało: 4 zlecenia okresu nie mają tak ani nie w SKUTECZNE. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, puste: L3–L4, L6; inna wartość: L8 („TAK/NIE sprawdzić”)\n"
        f"{SKUTECZNE_ACTION}"
    )


def test_single_empty_skuteczne_points_to_cell_in_column_of_skuteczne_header(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 8, 8, 0), successful=""),
        register_order(2, datetime(2026, 9, 9, 8, 0)),
    ]
    write_register(fixture.register_path, in_old_layout(rows), headers=OLD_REGISTER_HEADERS)

    error = stop_message(fixture)

    assert error.message.text == (
        "Co się stało: 1 zlecenie okresu nie ma tak ani nie w SKUTECZNE. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, puste: J2\n"
        f"{SKUTECZNE_ACTION}"
    )


def test_every_other_skuteczne_value_is_listed_with_exact_cell_content(tmp_path: Path) -> None:
    values: list[object] = ["???", "tsk", "tsk", " nia ", "ne", "trak", "niie", "tak/nie", 1, "TAKK", "x", "-"]
    rows: list[RegisterRow] = [
        with_skuteczne(register_order(number, datetime(2026, 9, 10, 8, number)), value)
        for number, value in enumerate(values, start=1)
    ]
    rows.append(register_order(99, datetime(2026, 9, 11, 8, 0)))
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.text == (
        "Co się stało: 12 zleceń okresu nie ma tak ani nie w SKUTECZNE. Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, inna wartość: L2 („???”), L3–L4 („tsk”), "
        "L5 („ nia ”), L6 („ne”), L7 („trak”), L8 („niie”), L9 („tak/nie”), L10 („1”), L11 („TAKK”), "
        "L12 („x”), L13 („-”)\n"
        f"{SKUTECZNE_ACTION}"
    )


def test_zlecenie_skuteczne_with_worker_outside_worker_config_stops_with_identifier(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(2, datetime(2026, 9, 8, 8, 0), worker="nowy.wykonawca"),
        register_order(3, datetime(2026, 9, 9, 8, 0), worker=" Kamil.Syntetyczny "),
        register_order(4, datetime(2026, 9, 10, 8, 0), successful="TAK", worker="NOWY.wykonawca"),
        register_order(5, datetime(2026, 9, 11, 8, 0), successful="nie", worker="ktos.nieskuteczny"),
        register_order(6, datetime(2026, 9, 12, 8, 0), worker=""),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    error = stop_message(fixture)

    assert error.message.code == "NIEZNANY_WYKONAWCA"
    assert error.message.text == (
        "Co się stało: Zlecenia skuteczne mają wykonawców spoza konfiguracji wykonawców: "
        "nowy.wykonawca, (pusty). Nie utworzono żadnego pliku.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, nowy.wykonawca: wiersze 2, 4; (pusty): wiersz 6\n"
        "Co zrobić: Dopisz identyfikator wykonawcy do konfiguracji wykonawców (worker_mapping.yaml), "
        "tej samej co w Przebiegu rozliczeń, albo popraw WYKONAWCA we wskazanych wierszach Rejestru zleceń. "
        "Zapisz i zamknij Rejestr, i uruchom ponownie."
    )
    assert "ktos.nieskuteczny" not in error.message.text


def test_worker_outside_worker_config_in_unsuccessful_order_does_not_stop(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        register_order(3, datetime(2026, 9, 9, 8, 0), successful="nie", worker="ktos.nieskuteczny"),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (2, 1)
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_more_zlecenia_skuteczne_than_wzorzec_zero_rows_warns_and_creates_both_files(tmp_path: Path) -> None:
    successful_count = COLLECTIVE_TEMPLATE_ZERO_ROWS + 2
    rows: list[RegisterRow] = [
        {**register_order(number, datetime(2026, 9, 14, 8, number)), "UMOWA": "u", "URZĄDZENIA": "nokia zte"}
        for number in range(1, successful_count + 1)
    ]
    rows.insert(3, register_order(99, datetime(2026, 9, 14, 9, 0), successful="nie"))
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert [warning.text for warning in other_warnings(summary.warnings)] == [
        "Co się stało: Zleceń skutecznych: 8, wierszy przygotowanych zerami we Wzorcu pliku zbiorczego: 6. "
        "Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości.\n"
        f"Gdzie: plik {COLLECTIVE_FILE_NAME}, wiersze 24–25\n"
        "Co zrobić: Sprawdź te wiersze jak pozostałe: narzędzie wpisało w nich ilości tak samo, a puste komórki "
        "liczą się jak 0. Jeśli zdarza się to często, przekaż to osobie utrzymującej narzędzie, żeby dodała wiersze "
        "z zerami we Wzorcu pliku zbiorczego."
    ]
    assert other_warnings(summary.warnings)[0].code == "MALO_WIERSZY_Z_ZERAMI"
    assert summary.successful_order_count == successful_count
    assert len(sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=1)) == successful_count + 1
    created = cell_values(fixture.collective_file_path, min_row=18, max_row=26, min_col=1, max_col=14)
    assert [row[5] for row in created] == [f"ZL-SYN-{number:03d}" for number in range(1, 9)] + [None]
    assert [row[13] for row in created] == [0] * COLLECTIVE_TEMPLATE_ZERO_ROWS + [None] * 3
    with_zeros, without_zeros = cell_values(fixture.collective_file_path, min_row=23, max_row=24, min_col=14, max_col=42)
    assert [value or 0 for value in without_zeros] == list(with_zeros)
    assert any(with_zeros)


def test_jedno_zlecenie_skuteczne_ponad_wiersze_z_zerami_ostrzega_o_jednym_wierszu(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 14, 8, number))
        for number in range(1, COLLECTIVE_TEMPLATE_ZERO_ROWS + 2)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert [(warning.code, warning.text) for warning in other_warnings(summary.warnings)] == [
        (
            "MALO_WIERSZY_Z_ZERAMI",
            "Co się stało: Zleceń skutecznych: 7, wierszy przygotowanych zerami we Wzorcu pliku zbiorczego: 6. "
            "Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości.\n"
            f"Gdzie: plik {COLLECTIVE_FILE_NAME}, wiersz 24\n"
            "Co zrobić: Sprawdź te wiersze jak pozostałe: narzędzie wpisało w nich ilości tak samo, a puste komórki "
            "liczą się jak 0. Jeśli zdarza się to często, przekaż to osobie utrzymującej narzędzie, żeby dodała wiersze "
            "z zerami we Wzorcu pliku zbiorczego.",
        )
    ]


def test_zlecenia_skuteczne_filling_exactly_wzorzec_zero_rows_do_not_warn(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(number, datetime(2026, 9, 14, 8, number))
        for number in range(1, COLLECTIVE_TEMPLATE_ZERO_ROWS + 1)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture)

    assert other_warnings(summary.warnings) == []


def test_last_order_before_monday_warns_about_incomplete_period_with_orders_per_day(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(2, datetime(2026, 9, 12, 23, 59), successful="nie"),
        register_order(3, datetime(2026, 9, 10, 9, 0)),
        register_order(4, datetime(2026, 9, 10, 15, 30)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    plan = run_preparation(fixture, dry_run=True)

    assert [warning.text for warning in other_warnings(plan.warnings)] == [
        "Co się stało: Ostatnie zlecenie okresu jest z soboty 12.09.2026, a okres kończy się w poniedziałek "
        "14.09.2026. Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu.\n"
        f"Gdzie: plik {REGISTER_NAME}, arkusz ZLECENIA, okres {PERIOD}\n"
        "Co zrobić: Sprawdź liczby zleceń na dzień. Jeśli brakuje zleceń, przerwij, uzupełnij eksport "
        "w Rejestrze zleceń, zapisz go i uruchom ponownie. Jeśli okres jest pełny, kontynuuj."
    ]
    assert other_warnings(plan.warnings)[0].code == "NIEPELNY_OKRES"
    assert plan.orders_per_day == {
        date(2026, 9, 8): 1,
        date(2026, 9, 9): 0,
        date(2026, 9, 10): 2,
        date(2026, 9, 11): 0,
        date(2026, 9, 12): 1,
        date(2026, 9, 13): 0,
        date(2026, 9, 14): 0,
    }
    assert list(fixture.periods_directory.iterdir()) == []


def test_incomplete_period_warning_does_not_block_creating_both_files(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path, [register_order(1, datetime(2026, 9, 13, 23, 59))])

    summary = run_preparation(fixture)

    assert [warning.code for warning in other_warnings(summary.warnings)] == ["NIEPELNY_OKRES"]
    assert fixture.internal_settlement_path.is_file()
    assert fixture.collective_file_path.is_file()


def test_order_on_monday_anywhere_in_rejestr_means_full_period(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        register_order(1, datetime(2026, 9, 14, 0, 0)),
        register_order(2, datetime(2026, 9, 9, 8, 0)),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    plan = run_preparation(fixture, dry_run=True)

    assert other_warnings(plan.warnings) == []


def test_skipped_empty_rows_are_all_empty_rows_from_first_to_last_period_order(tmp_path: Path) -> None:
    rows: list[RegisterRow] = [
        None,
        register_order(1, datetime(2026, 9, 7, 15, 0)),  # poprzedni okres
        None,
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(3, datetime(2026, 9, 15, 8, 0)),  # następny okres, między zleceniami okresu
        None,
        None,
        register_order(4, datetime(2026, 9, 14, 8, 0)),  # spóźnione zlecenie okresu
        None,
    ]
    fixture = make_preparation_fixture(tmp_path, rows)

    summary = run_preparation(fixture, dry_run=True)

    assert summary.period_order_count == 2
    assert summary.skipped_empty_rows == 3


def test_decyzja_taty_about_incomplete_period_comes_after_planowanie_and_before_zapisywanie(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    seen: list[tuple[list[tuple[ProgressPhase, type[ProgressEvent]]], bool]] = []
    tata = Tata(
        before_answer=lambda: seen.append(
            ([(event.phase, type(event)) for event in recorded], fixture.period_directory.exists())
        )
    )

    summary = run_preparation(fixture, observer=recorded.append, conversation=tata)

    [decision] = tata.decisions
    assert (decision.message.code, decision.question) == (
        "NIEPELNY_OKRES",
        "Kontynuować mimo niepełnego okresu?",
    )
    assert decision.counts_title == "Zlecenia na dzień"
    assert list(decision.counts) == [
        ("wt 08.09.2026", 1),
        ("śr 09.09.2026", 1),
        ("czw 10.09.2026", 0),
        ("pt 11.09.2026", 0),
        ("sob 12.09.2026", 1),
        ("niedz 13.09.2026", 0),
        ("pon 14.09.2026", 0),
    ]
    assert seen == [(STAGES_IN_ORDER[:8], False)]
    assert [(event.phase, type(event)) for event in recorded] == STAGES_IN_ORDER
    assert summary.period_order_count == 3
    assert fixture.collective_file_path.is_file()


def test_full_period_does_not_ask_tata(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    tata = Tata(consent=False)

    run_preparation(fixture, conversation=tata)

    assert tata.decisions == []
    assert fixture.collective_file_path.is_file()


def test_stage_times_ended_before_zapisywanie_stay_unchanged_after_measured_zapisywanie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    save_s = 0.05
    real_replace = os.replace
    ended_before_saving: dict[ProgressPhase, int | None] = {}

    def slow_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        time.sleep(save_s)
        real_replace(source, target)

    def observer(event: ProgressEvent) -> None:
        if isinstance(event, PhaseEnded) and event.phase is not ProgressPhase.SAVING:
            ended_before_saving[event.phase] = event.phase_elapsed_ms

    monkeypatch.setattr(os, "replace", slow_replace)

    summary = run_preparation(fixture, observer=observer)

    assert set(ended_before_saving) == {ProgressPhase.CHECKING, ProgressPhase.READING, ProgressPhase.PLANNING}
    assert summary.phase_durations_ms[ProgressPhase.SAVING] >= save_s * 1000
    assert dict(summary.phase_durations_ms) == {
        **ended_before_saving,
        ProgressPhase.SAVING: summary.phase_durations_ms[ProgressPhase.SAVING],
    }
    with pytest.raises(TypeError):
        summary.phase_durations_ms[ProgressPhase.SAVING] = 0  # type: ignore[index]


def test_refused_incomplete_period_stops_with_hint_of_the_conversation_and_creates_nothing(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)
    recorded: list[ProgressEvent] = []
    tata = Tata(consent=False, continue_hint="przy decyzji wybierz „Kontynuuj”")

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, observer=recorded.append, conversation=tata)

    assert raised.value.message.text == (
        "Co się stało: Przerwano z powodu niepełnego okresu, zgodnie z odpowiedzią. Nie utworzono żadnego pliku.\n"
        f"Gdzie: okres {PERIOD}\n"
        "Co zrobić: Uzupełnij eksport zleceń w Rejestrze zleceń, zapisz go, zamknij i uruchom ponownie. "
        "Jeśli okres jest pełny, przy decyzji wybierz „Kontynuuj”."
    )
    assert [(event.phase, type(event)) for event in recorded] == STAGES_IN_ORDER[:8]
    assert list(fixture.periods_directory.iterdir()) == []


def test_dry_run_of_incomplete_period_does_not_ask_tata(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)
    tata = Tata(consent=False)

    plan = run_preparation(fixture, dry_run=True, conversation=tata)

    assert tata.decisions == []
    assert [warning.code for warning in other_warnings(plan.warnings)] == ["NIEPELNY_OKRES"]


def _orders_around_period() -> list[RegisterRow]:
    """Trzy zlecenia z 2025 r. (wiersze 2–4) i trzy zlecenia okresu 08_14_09_2026 (wiersze 5–7)."""

    return [
        *earlier_orders(3, 100),
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        register_order(3, datetime(2026, 9, 10, 8, 0)),
        register_order(4, datetime(2026, 9, 11, 8, 0)),
    ]


@pytest.mark.parametrize(("opening", "closing"), [(b"<!-- ", b" -->"), (b"<![CDATA[", b"]]>")], ids=["komentarz", "cdata"])
def test_komentarz_zaczety_przed_okresem_i_zamkniety_w_wierszach_okresu_ukrywa_ich_zlecenia(
    tmp_path: Path, opening: bytes, closing: bytes
) -> None:
    """Wiersze 3–5 Rejestru są w komentarzu XML (albo CDATA), więc nie są wierszami arkusza: pierwsze zlecenie okresu
    nie jest zleceniem, a dwa następne są."""

    fixture = make_preparation_fixture(tmp_path, _orders_around_period())

    def commented(name: str, data: bytes) -> bytes:
        if name != "xl/worksheets/sheet2.xml":
            return data
        data = data.replace(b'<row r="3"', opening + b'<row r="3"', 1)
        return data.replace(b'<row r="6"', closing + b'<row r="6"', 1)

    rewrite_parts(fixture.register_path, commented)

    assert run_preparation(fixture).period_order_count == 2



def test_formula_glowna_wspolnej_formuly_w_wierszu_okresu_daje_jedno_zlecenie_tego_wiersza(tmp_path: Path) -> None:
    """Formuła główna wspólnej formuły stoi w pierwszym wierszu okresu, a drugi wiersz okresu się do niej odwołuje:
    każdy wiersz okresu jest jednym zleceniem z formułą przeniesioną na swój wiersz."""

    fixture = make_preparation_fixture(tmp_path, _orders_around_period())
    workbook = load_workbook(fixture.register_path)
    for row in (5, 6):
        workbook["ZLECENIA"].cell(row, 13).value = f"=N{row}"
    workbook.save(fixture.register_path)
    workbook.close()

    def share(name: str, data: bytes) -> bytes:
        if name != "xl/worksheets/sheet2.xml":
            return data
        data = data.replace(b"<f>N5</f>", b'<f t="shared" ref="M5:M6" si="0">N5</f>')
        return data.replace(b"<f>N6</f>", b'<f t="shared" si="0"/>')

    rewrite_parts(fixture.register_path, share)

    summary = run_preparation(fixture)

    assert summary.period_order_count == 3
    assert [row[10] for row in sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=13)] == ["=N5", "=N6", "montaż"]


_SECOND_PERIOD_ORDER = internal_row(3, datetime(2026, 9, 10, 8, 0), "NIE", "dariusz.fikcyjny2")
_PERIOD_ORDERS_AFTER_HISTORY = (
    internal_row(2, datetime(2026, 9, 8, 8, 0), "tak", "adrian.testowy"),
    (*_SECOND_PERIOD_ORDER[:3], 7, *_SECOND_PERIOD_ORDER[4:]),
    internal_row(4, datetime(2026, 9, 14, 18, 0), "tak", "kamil.syntetyczny"),
)


def _excel_register_after_history(tmp_path: Path, lista_rows: int = 1) -> PreparationFixture:
    """Rejestr zapisany jak w Excelu (teksty wspólne, nagłówek UWAGI tekstem sformatowanym z podpowiedzią wymowy):
    40 zleceń z 2025 r. w wierszach 2–41, trzy zlecenia okresu 08_14_09_2026 w wierszach 42–44 i pięć z 2025 r. za
    nimi; UMOWA drugiego zlecenia okresu to liczba 7. Teksty zleceń okresu stoją w tabeli tekstów wspólnych za tekstami
    wcześniejszych zleceń, a miasto, urządzenie, czynność i wykonawcę dzielą z nimi. Arkusz ``lista`` ma
    ``lista_rows`` wykonawców pod nagłówkiem, a arkusz ``notatki`` za arkuszem zleceń tekst z końca tabeli."""

    rows: list[RegisterRow] = [
        *earlier_orders(40, 100),
        register_order(2, datetime(2026, 9, 8, 8, 0)),
        register_order(3, datetime(2026, 9, 10, 8, 0), successful="NIE", worker="dariusz.fikcyjny2") | {"UMOWA": 7},
        register_order(4, datetime(2026, 9, 14, 18, 0), worker="kamil.syntetyczny"),
        *earlier_orders(5, 200),
    ]
    fixture = make_preparation_fixture(tmp_path, rows)
    workbook = load_workbook(fixture.register_path)
    for row in range(3, lista_rows + 2):
        workbook["lista"].cell(row, 1).value = f"wykonawca.syntetyczny{row}"
    workbook.create_sheet("notatki")["A1"] = "notatka syntetyczna"
    workbook.save(fixture.register_path)
    workbook.close()
    like_excel(fixture.register_path)
    return fixture


def test_teksty_zlecen_okresu_z_konca_tabeli_tekstow_wspolnych_rejestru_trafiaja_do_rozliczenia_wewnetrznego(
    tmp_path: Path,
) -> None:
    fixture = _excel_register_after_history(tmp_path)

    summary = run_preparation(fixture)

    assert (summary.period_order_count, summary.successful_order_count) == (3, 2)
    assert sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=len(INTERNAL_TEMPLATE_HEADERS)) == list(
        _PERIOD_ORDERS_AFTER_HISTORY
    )


def _value_of_period_cell(change: Callable[[bytes], bytes]) -> Callable[[str, bytes], bytes]:
    """Zmiana ``<v>`` komórki ADRES drugiego zlecenia okresu (E43) przez ``change``."""

    def changed(name: str, data: bytes) -> bytes:
        if name != "xl/worksheets/sheet2.xml":
            return data
        cell = data.index(b'<c r="E43"')
        start = data.index(b"<v>", cell)
        end = data.index(b"</v>", start) + len(b"</v>")
        return data[:start] + change(data[start:end]) + data[end:]

    return changed


def _out_of_table_in_lista_row_2(name: str, data: bytes) -> bytes:
    old, new = b'<c r="A2" t="s"><v>1</v>', b'<c r="A2" t="s"><v>99999</v>'
    return data.replace(old, new) if name == "xl/worksheets/sheet1.xml" else data


def _broken_far_after_lista_header(name: str, data: bytes) -> bytes:
    return data.replace(b"</sheetData>", b"</sheetData><zepsuty>") if name == "xl/worksheets/sheet1.xml" else data


@pytest.mark.parametrize(
    ("lista_rows", "change"),
    [
        (1, _value_of_period_cell(lambda value: b"<v>" + b"".join(b"&#%d;" % digit for digit in value[3:-4]) + b"</v>")),
        (1, _out_of_table_in_lista_row_2),
        (3000, _broken_far_after_lista_header),
    ],
    ids=[
        "numer-tekstu-encjami",
        "numer-spoza-tabeli-w-nieczytanym-wierszu",
        "zepsuty-xml-za-wierszem-1-listy",
    ],
)
def test_rejestr_w_ksztalcie_ktorego_zawezenie_tekstow_wspolnych_nie_zna_daje_te_same_zlecenia_okresu(
    tmp_path: Path, lista_rows: int, change: Callable[[str, bytes], bytes]
) -> None:
    """Numer tekstu wspólnego zapisany encjami, numer spoza tabeli w wierszu, którego Przygotowanie nie czyta, albo
    zepsuty XML daleko za wierszem 1 arkusza bez zleceń: zawężony Rejestr ma wtedy całą tabelę tekstów wspólnych, więc
    zlecenia okresu są takie same jak bez nich."""

    fixture = _excel_register_after_history(tmp_path, lista_rows)
    rewrite_parts(fixture.register_path, change)

    run_preparation(fixture)

    assert sheet_rows(fixture.internal_settlement_path, min_row=2, max_col=len(INTERNAL_TEMPLATE_HEADERS)) == list(
        _PERIOD_ORDERS_AFTER_HISTORY
    )


@pytest.mark.parametrize(
    ("item", "odd"),
    [
        ("<si><t>POZNAŃ</t></si>", "<si><t>POZNAŃ</t><si><t>obcy tekst</t></si></si>"),
        (
            "<si><t>POZNAŃ</t></si>",
            '<si><t>POZNAŃ</t><x:si xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><t>obcy tekst</t></x:si></si>',
        ),
        ("<si><t>POZNAŃ</t></si>", '<si xmlns="urn:inna"><t>obcy tekst</t></si><si><t>POZNAŃ</t></si>'),
        ("<si><t>POZNAŃ</t></si>", "<si><t><![CDATA[POZNAŃ</si><si>]]></t></si>"),
        ("<si><t>POZNAŃ</t></si>", "<si><t>POZNAŃ</t><!-- </si><si> --></si>"),
        ("<si><t>POZNAŃ</t></si>", "<si><t>POZNAŃ</t><?obcy </si><si>?></si>"),
    ],
    ids=["zagniezdzony", "zagniezdzony-z-prefiksem", "w-innej-przestrzeni-nazw", "cdata", "komentarz", "instrukcja"],
)
def test_tekst_wspolny_w_ksztalcie_spoza_listy_zatrzymuje_przygotowanie_na_nieczytelnym_rejestrze(
    tmp_path: Path, item: str, odd: str
) -> None:
    """Tabela tekstów wspólnych w kształcie, którego granic ``<si>`` czytnik Rejestru nie zna (zagnieżdżony ``<si>``,
    ``<si>`` z innej przestrzeni nazw, znaczniki w CDATA, komentarzu albo instrukcji przetwarzania; Excel tak nie
    zapisuje): Przygotowanie zatrzymuje się na nieczytelnym Rejestrze, a Diagnoza mówi to samo, zamiast zgadywać, który
    tekst ma komórka."""

    fixture = _excel_register_after_history(tmp_path)
    rewrite_parts(
        fixture.register_path,
        lambda name, data: data.replace(item.encode(), odd.encode(), 1) if name == "xl/sharedStrings.xml" else data,
    )

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    assert raised.value.message.code == "USZKODZONY_REJESTR"
    assert register_problem(fixture.register_path, DadFiles()) == raised.value.message
