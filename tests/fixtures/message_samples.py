"""Próbki każdej fabryki katalogów Komunikatów, z syntetycznymi ścieżkami komputera taty.

Wspólne dla testu instrukcji taty, testu rodzaju Zatrzymania i testu expect Komunikatów: każdy katalog
ma tu wszystkie swoje fabryki, warianty liczby pojedynczej i mnogiej osobno.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from functools import partial
from pathlib import Path

from rozliczenia import efenix_messages, intermax_messages
from rozliczenia import preparation_messages as messages
from rozliczenia import settlement_messages
from rozliczenia.centrum import (
    diagnosis_messages,
    fill_messages,
    notification_messages,
    report_messages,
    start_problems,
    update_messages,
)
from rozliczenia.centrum.tool_update import LIBRARIES_FAILED, NEW_VERSION_FAILED, ROLLBACK_FAILED, UNEXPECTED
from rozliczenia.efenix_checks import OrderProblem
from rozliczenia.efenix_positions import Conflict, NotWholeQuantities, OrderFault, OtherAmount, PricedDifferently, UnpairedColumns
from rozliczenia.message import Message
from rozliczenia.period_folder import (
    FolderNotNamedAfterPeriod,
    NotPeriodToken,
    PeriodFolderError,
    PeriodFolderLookupError,
)
from rozliczenia.quantity_rules import DESCRIPTION_COLUMNS
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.workbook_files import MergedCells, MissingHeader, Problem, WorkbookError
from rozliczenia.worker_config import SameWorkerFile, WorkerConfigError

REGISTER = Path("C:/Dane/ZLECENIA INTERMAX OD 08_11_2021.xlsx")
PERIODS = Path("C:/Dane/INEA")
PERIOD_DIRECTORY = PERIODS / "08_14_09_2026"
DAD_PERIODS = Path("C:/Users/tata/OneDrive/Załączniki")
JUNE = DAD_PERIODS / "Rozliczenia 2026" / "06_Czerwiec_2026" / "INEA"
JULY = DAD_PERIODS / "Rozliczenia 2026" / "07_Lipiec_2026" / "INEA"
PARSED_PERIOD = parse_period_token("08_14_09_2026")
TEMPLATE = Path("C:/Narzedzie/config/Wzorzec pliku zbiorczego.xlsx")
CONFIG = Path("//nas/Wspolne/Narzedzie/config/worker_mapping.yaml")
SHEET = "ZLECENIA"
PERIOD = "08_14_09_2026"
SOURCE = PERIOD_DIRECTORY / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
WORKER_SETTLEMENTS = PERIOD_DIRECTORY / f"Rozliczenie pracowników {PERIOD}"
WORKER_TEMPLATE = Path("C:/Narzedzie/config/Wzorzec rozliczenia pracownika.xlsx")
MISSING_CONFIG = WorkerConfigError("missing")
INACCESSIBLE_CONFIG = WorkerConfigError("inaccessible")
CONFIG_NOT_UTF8 = WorkerConfigError("not_utf8")
CONFIG_NOT_YAML = WorkerConfigError("not_yaml")
INVALID_CONFIG = WorkerConfigError("unsupported_version")
# Pozostałe złamane reguły konfiguracji; każda ma swoje zdanie w obu katalogach.
BROKEN_CONFIG_RULES = [
    WorkerConfigError("not_mapping"),
    WorkerConfigError("no_workers"),
    WorkerConfigError("not_text_entry"),
    WorkerConfigError("empty_entry"),
    WorkerConfigError("repeated_id"),
    WorkerConfigError("invalid_worker_name"),
    WorkerConfigError("too_long_worker_name"),
    WorkerConfigError(SameWorkerFile("Jan Testowy", "jan testowy")),
]
# Foldery nad folderem config z próbek; żaden Komunikat ich nie pokazuje.
ABOVE_CONFIG = frozenset({"Wspolne", "Narzedzie"})

Samples = Mapping[str, Sequence[Callable[[], Message]]]


# Każda fabryka katalogu z przykładowymi argumentami; warianty liczby pojedynczej i mnogiej osobno.
PREPARATION_SAMPLES: Samples = {
    "invalid_period_token": [lambda: messages.invalid_period_token("08_14_9_2026")],
    "period_file_exists": [lambda: messages.period_file_exists(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")],
    "worker_config_problem": [
        lambda: messages.worker_config_problem(CONFIG, MISSING_CONFIG),
        lambda: messages.worker_config_problem(CONFIG, INACCESSIBLE_CONFIG),
        lambda: messages.worker_config_problem(CONFIG, CONFIG_NOT_UTF8),
        lambda: messages.worker_config_problem(CONFIG, CONFIG_NOT_YAML),
        lambda: messages.worker_config_problem(CONFIG, INVALID_CONFIG),
        *(partial(messages.worker_config_problem, CONFIG, error) for error in BROKEN_CONFIG_RULES),
    ],
    "template_unusable": [
        *(partial(messages.template_unusable, WorkbookError(TEMPLATE, problem)) for problem in Problem),
        partial(messages.template_unusable, WorkbookError(TEMPLATE, Problem.LAYOUT, MissingHeader("Sheet1", 17, "WYKONAWCA"))),
        partial(
            messages.template_unusable, WorkbookError(TEMPLATE, Problem.LAYOUT, MissingHeader("Sheet1", 17, "WYKONAWCA", "G"))
        ),
        partial(messages.template_unusable, WorkbookError(TEMPLATE, Problem.LAYOUT, MergedCells("Sheet1", "B19:C20"))),
    ],
    "register_missing": [lambda: messages.register_missing(REGISTER)],
    "register_unusable": [
        partial(messages.register_unusable, WorkbookError(REGISTER, problem)) for problem in Problem
    ],
    "register_without_headers": [
        lambda: messages.register_without_headers(REGISTER, SHEET, ["SKUTECZNE"]),
        lambda: messages.register_without_headers(REGISTER, SHEET, ["SKUTECZNE", "WYKONAWCA"]),
    ],
    "register_with_duplicated_headers": [
        lambda: messages.register_with_duplicated_headers(REGISTER, SHEET, ["ADRES"]),
        lambda: messages.register_with_duplicated_headers(REGISTER, SHEET, ["ADRES", "UMOWA"]),
    ],
    "register_without_data_sheet": [lambda: messages.register_without_data_sheet(REGISTER, ["DATA GODZ. POCZ."])],
    "period_orders_in_many_sheets": [
        lambda: messages.period_orders_in_many_sheets(REGISTER, ["ZLECENIA", "ZLECENIA 2"], PERIOD)
    ],
    "raw_orders_not_ordered": [
        lambda: messages.raw_orders_not_ordered(REGISTER, SHEET, 120, 140),
        lambda: messages.raw_orders_not_ordered(REGISTER, SHEET, 120, 120),
    ],
    "periods_directory_missing": [lambda: messages.periods_directory_missing(PERIODS)],
    "folder_inaccessible": [lambda: messages.folder_inaccessible(PERIODS)],
    "period_folder_lookup_problem": [
        lambda: messages.period_folder_lookup_problem(PeriodFolderLookupError(DAD_PERIODS, PARSED_PERIOD, ())),
        lambda: messages.period_folder_lookup_problem(
            PeriodFolderLookupError(DAD_PERIODS, PARSED_PERIOD, (JUNE, JULY))
        ),
    ],
    "rows_without_date": [
        lambda: messages.rows_without_date(REGISTER, SHEET, [7]),
        lambda: messages.rows_without_date(REGISTER, SHEET, [7, 9]),
    ],
    "invalid_successful_values": [
        lambda: messages.invalid_successful_values(REGISTER, SHEET, "L", [4], []),
        lambda: messages.invalid_successful_values(REGISTER, SHEET, "L", [4, 5, 9], [messages.CellContent(6, "???")]),
        lambda: messages.invalid_successful_values(REGISTER, SHEET, "L", [], [messages.CellContent(n, "tsk") for n in range(2, 14)]),
    ],
    "unknown_workers": [
        lambda: messages.unknown_workers(REGISTER, SHEET, CONFIG, [("nowy.wykonawca", [4])]),
        lambda: messages.unknown_workers(REGISTER, SHEET, CONFIG, [("nowy.wykonawca", [4, 9]), ("", [6])]),
    ],
    "no_period_orders": [lambda: messages.no_period_orders(REGISTER, SHEET, PERIOD)],
    "too_few_zero_rows": [
        lambda: messages.too_few_zero_rows(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", 7, 6, 24),
        lambda: messages.too_few_zero_rows(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", 9, 6, 24),
    ],
    "unknown_devices": [
        lambda: messages.unknown_devices(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", [19]),
        lambda: messages.unknown_devices(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", list(range(18, 30))),
    ],
    "rows_from_description": [
        lambda: messages.rows_from_description(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", [20]),
        lambda: messages.rows_from_description(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", [20, 21, 23]),
    ],
    "columns_from_description": [lambda: messages.columns_from_description(f"Rozliczenie {PERIOD} - zbiorcze.xlsx", DESCRIPTION_COLUMNS)],
    "incomplete_period": [
        lambda: messages.incomplete_period(REGISTER, SHEET, PERIOD, date(2026, 9, 12), date(2026, 9, 14))
    ],
    "incomplete_period_refused": [
        lambda: messages.incomplete_period_refused(
            PERIOD, "uruchom proces w Centrum rozliczeń i przy decyzji wybierz „Kontynuuj”"
        ),
        lambda: messages.incomplete_period_refused(PERIOD, "przy decyzji wybierz „Kontynuuj”"),
    ],
    "write_failed": [lambda: messages.write_failed(PERIOD_DIRECTORY)],
    "write_failed_with_file_left": [
        lambda: messages.write_failed_with_file_left(PERIOD_DIRECTORY, f"Rozliczenie wew. {PERIOD}.xlsx")
    ],
    "unexpected_failure": [messages.unexpected_failure],
    "summary_not_shown": [messages.summary_not_shown],
    "plan_not_shown": [messages.plan_not_shown],
}

SETTLEMENT_SAMPLES: Samples = {
    "collective_file_missing": [lambda: settlement_messages.collective_file_missing(SOURCE)],
    "collective_file_invalid": [
        lambda: settlement_messages.collective_file_invalid(SOURCE, PeriodFolderError("internal_settlement")),
        lambda: settlement_messages.collective_file_invalid(SOURCE, PeriodFolderError("not_collective_file_name")),
        lambda: settlement_messages.collective_file_invalid(SOURCE, PeriodFolderError(NotPeriodToken("09_15_09_2026"))),
        lambda: settlement_messages.collective_file_invalid(
            SOURCE, PeriodFolderError(FolderNotNamedAfterPeriod(PERIOD))
        ),
    ],
    "collective_file_unusable": [
        partial(settlement_messages.collective_file_unusable, WorkbookError(SOURCE, problem)) for problem in Problem
    ],
    "worker_settlements_exist": [lambda: settlement_messages.worker_settlements_exist(WORKER_SETTLEMENTS)],
    "worker_config_problem": [
        lambda: settlement_messages.worker_config_problem(CONFIG, MISSING_CONFIG),
        lambda: settlement_messages.worker_config_problem(CONFIG, INACCESSIBLE_CONFIG),
        lambda: settlement_messages.worker_config_problem(CONFIG, CONFIG_NOT_UTF8),
        lambda: settlement_messages.worker_config_problem(CONFIG, CONFIG_NOT_YAML),
        lambda: settlement_messages.worker_config_problem(CONFIG, INVALID_CONFIG),
        *(partial(settlement_messages.worker_config_problem, CONFIG, error) for error in BROKEN_CONFIG_RULES),
    ],
    "worker_template_unusable": [
        partial(settlement_messages.worker_template_unusable, WorkbookError(WORKER_TEMPLATE, problem))
        for problem in Problem
    ],
    "worker_template_unusable_in_saving": [
        partial(
            settlement_messages.worker_template_unusable_in_saving,
            WORKER_SETTLEMENTS,
            "Wykonawca Testowy",
            WorkbookError(WORKER_TEMPLATE, problem),
        )
        for problem in Problem
    ],
    "unmapped_worker": [
        lambda: settlement_messages.unmapped_worker(SOURCE, ["jan.nieznany"]),
        lambda: settlement_messages.unmapped_worker(SOURCE, ["jan.nieznany", "ewa.nieznana"]),
    ],
    "rows_without_worker": [lambda: settlement_messages.rows_without_worker(SOURCE)],
    "unmapped_worker_warning": [lambda: settlement_messages.unmapped_worker_warning(SOURCE, "jan.nieznany")],
    "row_without_worker_warning": [lambda: settlement_messages.row_without_worker_warning(SOURCE, 19)],
    "worker_file_failed": [lambda: settlement_messages.worker_file_failed(WORKER_SETTLEMENTS, "Wykonawca Testowy")],
    "publish_failed": [lambda: settlement_messages.publish_failed(WORKER_SETTLEMENTS)],
    "staging_left": [
        lambda: settlement_messages.staging_left(
            settlement_messages.publish_failed(WORKER_SETTLEMENTS), f".{WORKER_SETTLEMENTS.name}.staging-"
        ),
        lambda: settlement_messages.staging_left(
            settlement_messages.worker_file_failed(WORKER_SETTLEMENTS, "Wykonawca Testowy"),
            f".{WORKER_SETTLEMENTS.name}.staging-",
        ),
        lambda: settlement_messages.staging_left(
            settlement_messages.worker_settlements_exist(WORKER_SETTLEMENTS),
            f".{WORKER_SETTLEMENTS.name}.staging-",
        ),
    ],
    "write_failed": [lambda: settlement_messages.write_failed(WORKER_SETTLEMENTS)],
    "unexpected_failure": [settlement_messages.unexpected_failure],
    "summary_not_shown": [settlement_messages.summary_not_shown],
    "plan_not_shown": [settlement_messages.plan_not_shown],
}

START_SAMPLES: Samples = {
    "port_taken": [lambda: start_problems.port_taken(47811)],
    "other_version_running": [lambda: start_problems.other_version_running(47811, "3c1d0a9")],
    "missing_library": [lambda: start_problems.missing_library("fastapi")],
    "unexpected_start_failure": [start_problems.unexpected_start_failure],
    "not_started_after_update": [start_problems.not_started_after_update],
    "update_finishing": [start_problems.update_finishing],
}

DIAGNOSIS_SAMPLES: Samples = {
    "cause_not_found": [diagnosis_messages.cause_not_found],
    "newer_tool_version": [diagnosis_messages.newer_tool_version],
    "file_only_in_cloud": [lambda: diagnosis_messages.file_only_in_cloud(SOURCE)],
    "period_file_open": [lambda: diagnosis_messages.period_file_open(PERIOD_DIRECTORY / f"Rozliczenie wew. {PERIOD}.xlsx")],
}

FILL_SAMPLES: Samples = {
    "collective_file_unusable": [
        partial(fill_messages.collective_file_unusable, WorkbookError(SOURCE, problem)) for problem in Problem
    ],
    "headers_missing": [
        lambda: fill_messages.headers_missing(SOURCE, ("URZĄDZENIA",)),
        lambda: fill_messages.headers_missing(SOURCE, ("UMOWA", "DATA")),
    ],
    "only_in_cloud": [lambda: fill_messages.only_in_cloud(SOURCE)],
}

REPORT_QUEUE = Path("C:/Narzedzie/config/zgloszenia/kolejka")

REPORT_SAMPLES: Samples = {
    "not_queued": [lambda: report_messages.not_queued(REPORT_QUEUE)],
}

DAD_CASES_STATE = Path("//nas/Wspolne/Narzedzie/config/sprawy-taty.json")
READ_NOTIFICATIONS_STATE = DAD_CASES_STATE.with_name("powiadomienia.json")
NOTIFICATION_SAMPLES: Samples = {
    "unavailable": [
        lambda: notification_messages.unavailable([DAD_CASES_STATE]),
        lambda: notification_messages.unavailable([DAD_CASES_STATE, READ_NOTIFICATIONS_STATE]),
    ],
}

UPDATE_SAMPLES: Samples = {
    "no_git": [update_messages.no_git],
    "no_connection": [update_messages.no_connection],
    "login_required": [update_messages.login_required],
    "other_branch": [update_messages.other_branch],
    "local_changes": [update_messages.local_changes],
    "unexpected_failure": [update_messages.unexpected_failure],
    "libraries_failed": [update_messages.libraries_failed],
    "new_version_failed": [update_messages.new_version_failed],
    "rollback_failed": [update_messages.rollback_failed],
    "message_of": [
        lambda: update_messages.message_of(UNEXPECTED),
        lambda: update_messages.message_of(LIBRARIES_FAILED),
        lambda: update_messages.message_of(NEW_VERSION_FAILED),
        lambda: update_messages.message_of(ROLLBACK_FAILED),
        lambda: update_messages.message_of("NIEZNANY_KOD"),
    ],
}

_ORDER_FAULTS: tuple[OrderFault, ...] = (
    *OrderProblem,
    UnpairedColumns(("N", "AR")),
    NotWholeQuantities(("O",)),
    PricedDifferently(Decimal("150.00"), Decimal("125.5"), ("005", "012")),
    PricedDifferently(Decimal("150.00"), Decimal("125.5"), ()),
    OtherAmount(Decimal("1234.50"), Decimal("1200")),
)
EFENIX_SAMPLES: Samples = {
    "source_unusable": [partial(efenix_messages.source_unusable, WorkbookError(SOURCE, problem)) for problem in Problem],
    "missing_columns": [lambda: efenix_messages.missing_columns(SOURCE, ["NUMER ZL.", "ADRES"])],
    "amounts_not_computed": [lambda: efenix_messages.amounts_not_computed(SOURCE, 18)],
    "logged_out": [efenix_messages.logged_out],
    "efenix_changed": [efenix_messages.efenix_changed],
    "efenix_unreachable": [efenix_messages.efenix_unreachable],
    "order_error": [partial(efenix_messages.order_error, SOURCE, 23, problem) for problem in _ORDER_FAULTS],
    "emmett_conflict": [
        lambda: efenix_messages.emmett_conflict(SOURCE, 23, [Conflict("012", 2, 1), Conflict("020", 1, 0)]),
    ],
    "unexpected_failure": [efenix_messages.unexpected_failure],
    "plan_not_shown": [efenix_messages.plan_not_shown],
    "summary_not_shown": [efenix_messages.summary_not_shown],
}

COPIES = Path("C:/Narzedzie/Kopie INTERMAX")
COPY = COPIES / "INTERMAX przed uporządkowaniem 2026-09-14 07-30-00.xlsx"
SEPTEMBER_14 = date(2026, 9, 14)
INTERMAX_SAMPLES: Samples = {
    "register_unusable": [
        partial(intermax_messages.register_unusable, WorkbookError(REGISTER, problem)) for problem in Problem
    ],
    "register_missing": [lambda: intermax_messages.register_missing(REGISTER)],
    "register_open": [lambda: intermax_messages.register_open(REGISTER)],
    "no_order_sheet": [lambda: intermax_messages.no_order_sheet(REGISTER)],
    "no_raw_orders": [lambda: intermax_messages.no_raw_orders(REGISTER, SHEET)],
    "raw_orders_in_several_sheets": [
        lambda: intermax_messages.raw_orders_in_several_sheets(REGISTER, [SHEET, "ZLECENIA 2025"])
    ],
    "raw_order_above_ordered": [lambda: intermax_messages.raw_order_above_ordered(REGISTER, SHEET, 812, 815)],
    "raw_order_without_value": [
        lambda: intermax_messages.raw_order_without_value(REGISTER, SHEET, 816, "B", worker=False),
        lambda: intermax_messages.raw_order_without_value(REGISTER, SHEET, 816, "R", worker=True),
    ],
    "several_days": [
        lambda: intermax_messages.several_days(REGISTER, SHEET, [SEPTEMBER_14, date(2026, 9, 15)], 816, 840),
        lambda: intermax_messages.several_days(
            REGISTER, SHEET, [SEPTEMBER_14, date(2026, 9, 15), date(2026, 9, 16)], 816, 860
        ),
    ],
    "day_already_ordered": [lambda: intermax_messages.day_already_ordered(REGISTER, SHEET, SEPTEMBER_14, 816, 840)],
    "unsupported_shape": [lambda: intermax_messages.unsupported_shape(REGISTER, SHEET)],
    "register_syncing": [lambda: intermax_messages.register_syncing(REGISTER)],
    "write_check_failed": [lambda: intermax_messages.write_check_failed(REGISTER)],
    "register_write_failed": [lambda: intermax_messages.register_write_failed(REGISTER)],
    "copy_failed": [lambda: intermax_messages.copy_failed(COPIES)],
    "old_copies_kept": [lambda: intermax_messages.old_copies_kept(COPIES)],
    "copies_unreadable": [lambda: intermax_messages.copies_unreadable(COPIES)],
    "copy_missing": [lambda: intermax_messages.copy_missing(COPIES, COPY.name)],
    "copy_unusable": [partial(intermax_messages.copy_unusable, WorkbookError(COPY, problem)) for problem in Problem],
    "copy_damaged": [lambda: intermax_messages.copy_damaged(COPY)],
    "restore_register_unusable": [
        partial(intermax_messages.restore_register_unusable, WorkbookError(REGISTER, problem)) for problem in Problem
    ],
    "restore_register_open": [lambda: intermax_messages.restore_register_open(REGISTER)],
    "restore_register_syncing": [lambda: intermax_messages.restore_register_syncing(REGISTER)],
    "restore_copy_failed": [lambda: intermax_messages.restore_copy_failed(COPIES)],
    "restored_moment_ago": [lambda: intermax_messages.restored_moment_ago(COPIES)],
    "restore_failed": [lambda: intermax_messages.restore_failed(REGISTER)],
    "old_copies_kept_after_restore": [lambda: intermax_messages.old_copies_kept_after_restore(COPIES)],
    "unexpected_failure": [intermax_messages.unexpected_failure],
    "summary_not_shown": [intermax_messages.summary_not_shown],
    "plan_not_shown": [intermax_messages.plan_not_shown],
}
