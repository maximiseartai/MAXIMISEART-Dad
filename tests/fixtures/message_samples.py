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
from typing import get_args

from rozliczenia import tool_files
from rozliczenia import efenix_messages, intermax_messages, intermax_replace, report_entering_messages
from rozliczenia import preparation_messages as messages
from rozliczenia import settlement_messages, worker_config_messages
from rozliczenia.centrum import (
    diagnosis_messages,
    fill_messages,
    notification_messages,
    refusal,
    reminder_messages,
    report_messages,
    start_problems,
    update_messages,
)
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.notifications import NOTIFICATIONS_FILE
from rozliczenia.efenix_checks import DateRefused, OrderProblem
from rozliczenia.efenix_window import ForwardRefusal, PagePart
from rozliczenia.efenix_marking import Refusal
from rozliczenia.efenix_positions import (
    Excess,
    MissingPositions,
    NotWholeQuantities,
    OrderFault,
    OtherAmount,
    PageRead,
    UnpairedColumns,
)
from rozliczenia.message import Message
from rozliczenia.period_folder import (
    PeriodFolder,
    FolderNotNamedAfterPeriod,
    NotPeriodToken,
    PeriodFolderError,
    PeriodFolderLookupError,
    PeriodPlace,
)
from rozliczenia.quantity_engine import DESCRIPTION_COLUMNS
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.workbook_files import MergedCells, MissingHeader, Problem, WorkbookError
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE, AddressesProblem, UnknownLogin
from rozliczenia.worker_config import SameWorkerFile, WorkerConfigError
from rozliczenia.worker_reports import Login

REGISTER = Path("C:/Dane/ZLECENIA INTERMAX OD 08_11_2021.xlsx")
PERIODS = Path("C:/Dane/INEA")
PERIOD_DIRECTORY = PERIODS / "08_14_09_2026"
DAD_PERIODS = Path("C:/Users/tata/OneDrive/Załączniki")
JUNE = DAD_PERIODS / "Rozliczenia 2026" / "06_Czerwiec_2026" / "INEA"
JULY = DAD_PERIODS / "Rozliczenia 2026" / "07_Lipiec_2026" / "INEA"
PARSED_PERIOD = parse_period_token("08_14_09_2026")
TEMPLATE = tool_files.config_dir(Path("C:/Narzedzie")) / tool_files.COLLECTIVE_TEMPLATE.name
CONFIG = tool_files.config_dir(Path("//nas/Wspolne/Narzedzie")) / tool_files.WORKER_CONFIG.name
SHEET = "ZLECENIA"
PERIOD = "08_14_09_2026"
SOURCE = PeriodFolder(PERIODS, PARSED_PERIOD).collective_file
WORKER_SETTLEMENTS = PeriodFolder(PERIODS, PARSED_PERIOD).worker_settlements
INTERNAL_SETTLEMENT = PeriodFolder(PERIODS, PARSED_PERIOD).internal_settlement
WORKER_TEMPLATE = tool_files.config_dir(Path("C:/Narzedzie")) / tool_files.WORKER_TEMPLATE.name
MISSING_CONFIG = WorkerConfigError("missing")
INACCESSIBLE_CONFIG = WorkerConfigError("inaccessible")
CONFIG_NOT_UTF8 = WorkerConfigError("not_utf8")
CONFIG_NOT_YAML = WorkerConfigError("not_yaml")
INVALID_CONFIG = WorkerConfigError("unsupported_version")
# Pozostałe złamane reguły konfiguracji; każda ma swoje zdanie w Komunikacie.
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
# Konfigurację wykonawców objaśniają sekcje instrukcji obu procesów, które ją czytają.
WORKER_CONFIG_SAMPLES: Samples = {
    "worker_config_problem": [
        lambda: worker_config_messages.worker_config_problem(CONFIG, MISSING_CONFIG),
        lambda: worker_config_messages.worker_config_problem(CONFIG, INACCESSIBLE_CONFIG),
        lambda: worker_config_messages.worker_config_problem(CONFIG, CONFIG_NOT_UTF8),
        lambda: worker_config_messages.worker_config_problem(CONFIG, CONFIG_NOT_YAML),
        lambda: worker_config_messages.worker_config_problem(CONFIG, INVALID_CONFIG),
        *(partial(worker_config_messages.worker_config_problem, CONFIG, error) for error in BROKEN_CONFIG_RULES),
    ],
}
PREPARATION_SAMPLES: Samples = {
    "invalid_period_token": [lambda: messages.invalid_period_token("08_14_9_2026")],
    "period_file_exists": [lambda: messages.period_file_exists(PERIOD_DIRECTORY, INTERNAL_SETTLEMENT.name)],
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
        lambda: messages.too_few_zero_rows(SOURCE.name, 7, 6, 24),
        lambda: messages.too_few_zero_rows(SOURCE.name, 9, 6, 24),
    ],
    "unknown_devices": [
        lambda: messages.unknown_devices(SOURCE.name, [19]),
        lambda: messages.unknown_devices(SOURCE.name, list(range(18, 30))),
    ],
    "rows_from_description": [
        lambda: messages.rows_from_description(SOURCE.name, [20]),
        lambda: messages.rows_from_description(SOURCE.name, [20, 21, 23]),
    ],
    "columns_from_description": [lambda: messages.columns_from_description(SOURCE.name, DESCRIPTION_COLUMNS)],
    "incomplete_period": [
        lambda: messages.incomplete_period(REGISTER, SHEET, PERIOD, date(2026, 9, 12), date(2026, 9, 14))
    ],
    "incomplete_period_refused": [
        lambda: messages.incomplete_period_refused(
            PERIOD, "uruchom proces w Centrum rozliczeń i przy decyzji wybierz „Kontynuuj”"
        ),
        lambda: messages.incomplete_period_refused(PERIOD, runs_contract.CONTINUE_HINT),
    ],
    "write_failed": [lambda: messages.write_failed(PERIOD_DIRECTORY)],
    "write_failed_with_file_left": [
        lambda: messages.write_failed_with_file_left(PERIOD_DIRECTORY, INTERNAL_SETTLEMENT.name)
    ],
    "staging_left": [
        lambda: messages.staging_left(messages.write_failed(PERIOD_DIRECTORY), PERIODS, f".{PERIOD}.staging-"),
        lambda: messages.staging_left(
            messages.write_failed_with_file_left(PERIOD_DIRECTORY, INTERNAL_SETTLEMENT.name),
            PERIODS,
            f".{PERIOD}.staging-",
        ),
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
    "worker_template_unusable": [
        *(
            partial(settlement_messages.worker_template_unusable, WorkbookError(WORKER_TEMPLATE, problem))
            for problem in Problem
        ),
        partial(settlement_messages.worker_template_unusable, WorkbookError(WORKER_TEMPLATE, Problem.MISSING), "placeholder.xlsx"),
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
    "period_file_open": [lambda: diagnosis_messages.period_file_open(PERIOD_DIRECTORY / INTERNAL_SETTLEMENT.name)],
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

DAD_CASES_STATE = tool_files.config_dir(Path("//nas/Wspolne/Narzedzie")) / DAD_CASES_FILE
READ_NOTIFICATIONS_STATE = DAD_CASES_STATE.with_name(NOTIFICATIONS_FILE)
NOTIFICATION_SAMPLES: Samples = {
    "unavailable": [
        lambda: notification_messages.unavailable([DAD_CASES_STATE]),
        lambda: notification_messages.unavailable([DAD_CASES_STATE, READ_NOTIFICATIONS_STATE]),
    ],
}

REMINDER_SAMPLES: Samples = {
    "password_rejected": [reminder_messages.password_rejected],
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
}

# Każdy błąd zlecenia z tym, czy proces wysłał już do efenix zmianę zlecenia, gdy Wycena go daje (``changed``).
_ORDER_FAULTS: tuple[tuple[OrderFault, bool], ...] = (
    *((problem, problem is OrderProblem.NOT_FORWARDED) for problem in OrderProblem),
    *((refused, refused is DateRefused.NOT_SAVED) for refused in DateRefused),
    (UnpairedColumns(("N", "AR")), False),
    (NotWholeQuantities(("O",)), False),
    (OtherAmount(Decimal("1234.50"), Decimal("1200")), True),
    *((MissingPositions(("012", "019"), read), read is not PageRead.OPENED) for read in PageRead),
    *((refusal, False) for refusal in ForwardRefusal),
)
EFENIX_SAMPLES: Samples = {
    "source_unusable": [partial(efenix_messages.source_unusable, WorkbookError(SOURCE, problem)) for problem in Problem],
    "collective_file_missing": [lambda: efenix_messages.collective_file_missing(SOURCE)],
    "missing_columns": [lambda: efenix_messages.missing_columns(SOURCE, ["NUMER ZL.", "ADRES"])],
    "amounts_not_computed": [lambda: efenix_messages.amounts_not_computed(SOURCE, 18)],
    "logged_out": [partial(efenix_messages.logged_out, kept=kept) for kept in (False, True)],
    "window_closed": [partial(efenix_messages.window_closed, kept=kept) for kept in (False, True)],
    "window_stopped": [
        partial(efenix_messages.window_stopped, PagePart.LIST, kept=False),
        partial(efenix_messages.window_stopped, PagePart.EMMETT, kept=True),
    ],
    "efenix_unreachable": [partial(efenix_messages.efenix_unreachable, kept=kept) for kept in (False, True)],
    "browser_not_started": [efenix_messages.browser_not_started],
    "order_error": [
        partial(efenix_messages.order_error, SOURCE, 23, problem, changed=changed) for problem, changed in _ORDER_FAULTS
    ],
    "emmett_warning": [
        lambda: efenix_messages.emmett_warning(SOURCE, 23, [Excess("012", 2, 1), Excess("020", 1, 0)]),
    ],
    "marks_not_saved": [partial(efenix_messages.marks_not_saved, SOURCE, refusal) for refusal in Refusal],
    "unexpected_failure": [efenix_messages.unexpected_failure],
    "summary_not_shown": [efenix_messages.summary_not_shown],
}

COPIES = Path("C:/Narzedzie/Kopie INTERMAX")
COPY = COPIES / "INTERMAX przed uporządkowaniem 2026-09-14 07-30-00.xlsx"
SEPTEMBER_14 = date(2026, 9, 14)
REPLACEMENTS = (intermax_messages.ORDERING, intermax_messages.RESTORE)
# Wpisanie raportów podmienia INTERMAX bez Kopii, więc odmowy o Kopii go nie dotyczą (ADR 0028).
_WITHOUT_COPY = tuple(
    refusal
    for refusal in intermax_replace.Refusal
    if refusal not in (intermax_replace.Refusal.COPY_FAILED, intermax_replace.Refusal.COPY_EXISTS)
)
INTERMAX_SAMPLES: Samples = {
    "register_unusable": [
        partial(intermax_messages.register_unusable, WorkbookError(REGISTER, problem), replacement)
        for replacement in (*REPLACEMENTS, intermax_messages.ENTERING)
        for problem in Problem
    ],
    "register_missing": [
        partial(intermax_messages.register_missing, REGISTER, replacement)
        for replacement in (*REPLACEMENTS, intermax_messages.ENTERING)
    ],
    "no_order_sheet": [lambda: intermax_messages.no_order_sheet(REGISTER)],
    "register_with_duplicated_headers": [
        lambda: intermax_messages.register_with_duplicated_headers(REGISTER, SHEET, ["ADRES"]),
        lambda: intermax_messages.register_with_duplicated_headers(REGISTER, SHEET, ["ADRES", "UMOWA"]),
    ],
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
    "day_already_ordered": [
        lambda: intermax_messages.day_already_ordered(REGISTER, SHEET, SEPTEMBER_14, 816, 840),
        lambda: intermax_messages.day_already_ordered(REGISTER, SHEET, SEPTEMBER_14, 816, 816),
    ],
    "unsupported_shape": [lambda: intermax_messages.unsupported_shape(REGISTER, SHEET)],
    "refused": [
        *(
            partial(intermax_messages.refused, refusal, REGISTER, COPIES, replacement)
            for replacement in REPLACEMENTS
            for refusal in intermax_replace.Refusal
        ),
        *(
            partial(intermax_messages.refused, refusal, REGISTER, REGISTER.parent, intermax_messages.ENTERING)
            for refusal in _WITHOUT_COPY
        ),
    ],
    "old_copies_kept": [partial(intermax_messages.old_copies_kept, COPIES, replacement) for replacement in REPLACEMENTS],
    "copies_unreadable": [lambda: intermax_messages.copies_unreadable(COPIES)],
    "copy_missing": [lambda: intermax_messages.copy_missing(COPIES, COPY.name)],
    "copy_unusable": [partial(intermax_messages.copy_unusable, WorkbookError(COPY, problem)) for problem in Problem],
    "copy_damaged": [lambda: intermax_messages.copy_damaged(COPY)],
    "unexpected_failure": [intermax_messages.unexpected_failure],
    "summary_not_shown": [intermax_messages.summary_not_shown],
}

ADDRESSES = tool_files.config_dir(Path("C:/Narzedzie")) / WORKER_ADDRESSES_FILE
_ADDRESSES_PROBLEMS: tuple[AddressesProblem, ...] = (*get_args(get_args(AddressesProblem)[0]), UnknownLogin(Login("jan.testowy")))
# Kopia konfliktu OneDrive obok INTERMAX: jego nazwa z dopiskiem nazwy komputera (``onedrive_conflicts``).
CONFLICT_COPY = REGISTER.with_name(f"{REGISTER.stem}-LAPTOP-TATY{REGISTER.suffix}")
REPORT_ENTERING_SAMPLES: Samples = {
    "inbox_access_missing": [report_entering_messages.inbox_access_missing],
    "inbox_access_unreadable": [report_entering_messages.inbox_access_unreadable],
    "password_rejected": [report_entering_messages.password_rejected],
    "inbox_unreachable": [report_entering_messages.inbox_unreachable],
    "addresses_unusable": [
        partial(report_entering_messages.addresses_unusable, ADDRESSES, problem) for problem in _ADDRESSES_PROBLEMS
    ],
    "periods_directory_missing": [lambda: report_entering_messages.periods_directory_missing(PERIODS)],
    "periods_folder_inaccessible": [
        lambda: report_entering_messages.periods_folder_inaccessible(PERIODS),
        lambda: report_entering_messages.periods_folder_inaccessible(PERIOD_DIRECTORY),
    ],
    "state_unreadable": [report_entering_messages.state_unreadable],
    "decisions_unreadable": [report_entering_messages.decisions_unreadable],
    "cells_rejected": [report_entering_messages.cells_rejected],
    "unsupported_shape": [lambda: report_entering_messages.unsupported_shape(REGISTER, SHEET)],
    "memory_not_saved": [report_entering_messages.memory_not_saved],
    "conflict_copy": [lambda: report_entering_messages.conflict_copy(CONFLICT_COPY)],
    "conflict_after_save": [lambda: report_entering_messages.conflict_after_save(CONFLICT_COPY)],
    "unexpected_failure": [report_entering_messages.unexpected_failure],
    "summary_not_shown": [report_entering_messages.summary_not_shown],
}

RefusalSamples = Mapping[str, Sequence[Callable[[], refusal.Refusal]]]
_REPORT_ENTERING_MISSING: tuple[tuple[refusal.ReportEnteringFile, ...], ...] = (
    ("inbox_access",),
    ("worker_addresses",),
    ("inbox_access", "worker_addresses"),
)
_RETRIES: tuple[refusal.Retry, ...] = get_args(refusal.Retry)

# Każda fabryka katalogu odmów Centrum rozliczeń; nazwa bez końcówki ``_SAMPLES``, bo odmowa nie ma kodu Komunikatu.
REFUSALS: RefusalSamples = {
    "not_local_address": [refusal.not_local_address],
    "not_from_centrum_card": [refusal.not_from_centrum_card],
    "unexpected_failure": [refusal.unexpected_failure],
    "period_folder_unreadable": [partial(refusal.period_folder_unreadable, PERIOD)],
    "first_choose": [
        partial(refusal.first_choose, ["folder okresów"]),
        partial(refusal.first_choose, ["Rejestr zleceń", "folder okresów"]),
    ],
    "register_not_chosen": [refusal.register_not_chosen],
    "register_unavailable": [partial(refusal.register_unavailable, REGISTER.name)],
    "register_missing": [partial(refusal.register_missing, REGISTER.name)],
    "settings_not_saved": [refusal.settings_not_saved],
    "setting_refused": [
        lambda: refusal.setting_refused(FieldProblem("folder_okresow", settings_messages.periods_directory_path()))
    ],
    "settings_change_unknown": [refusal.settings_change_unknown],
    "settings_change_not_undoable": [refusal.settings_change_not_undoable],
    "autostart_not_changed": [refusal.autostart_not_changed],
    "unknown_period": [refusal.unknown_period],
    "period_folder_lookup": [
        lambda: refusal.period_folder_lookup(PeriodFolderLookupError(DAD_PERIODS, PARSED_PERIOD, ())),
        lambda: refusal.period_folder_lookup(PeriodFolderLookupError(DAD_PERIODS, PARSED_PERIOD, (JUNE, JULY))),
    ],
    "place_missing": [partial(refusal.place_missing, place, PERIOD) for place in get_args(PeriodPlace)],
    "worker_settlement_missing": [partial(refusal.worker_settlement_missing, "Jan Testowy", PERIOD)],
    "no_forwarding": [partial(refusal.no_forwarding, "Przygotowanie pliku zbiorczego")],
    "pricing_without_preview": [refusal.pricing_without_preview],
    # Tylko pary, które daje RunHost: drugie zamknięcie po przyjętym przechodzi, drugą aktualizację odrzuca
    # ``update_in_progress``, a drugi start ``run_in_progress``.
    "closing": [partial(refusal.closing, then) for then in _RETRIES if then != "shutdown"],
    "updating": [partial(refusal.updating, then) for then in _RETRIES if then != "update"],
    "restoring": [partial(refusal.restoring, then) for then in _RETRIES],
    "running": [partial(refusal.running, "Przebieg rozliczeń", PERIOD, then) for then in _RETRIES if then != "start"],
    "update_in_progress": [refusal.update_in_progress],
    "update_without_port": [refusal.update_without_port],
    "run_in_progress": [partial(refusal.run_in_progress, "Przebieg rozliczeń", PERIOD)],
    "unknown_run": [refusal.unknown_run],
    "not_awaiting_decision": [refusal.not_awaiting_decision],
    "no_diagnosis": [refusal.no_diagnosis],
    "no_report_draft": [refusal.no_report_draft],
    "no_failed_update": [refusal.no_failed_update],
    "metrics_unreadable": [refusal.metrics_unreadable],
    "history_unreadable": [refusal.history_unreadable],
    "run_not_in_history": [refusal.run_not_in_history],
    "note_not_queued": [refusal.note_not_queued],
    "report_entering_not_set_up": [
        partial(refusal.report_entering_not_set_up, missing) for missing in _REPORT_ENTERING_MISSING
    ],
    "reports_unreadable": [refusal.reports_unreadable],
    "difference_gone": [refusal.difference_gone],
}
