from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from rozliczenia import intermax_ordering, register_file
from rozliczenia.centrum.contract import settings_workers as contract
from rozliczenia.centrum.period_board import RECENT_PERIODS
from rozliczenia.centrum.settings import messages
from rozliczenia.dad_files import DadFiles
from rozliczenia.message import StopError
from rozliczenia.settlement_period import period_of
from rozliczenia.text import normalize_text
from rozliczenia.workbook_files import WorkbookError
from rozliczenia.workbook_parts import UnsupportedShape
from rozliczenia.worker_list import UnmatchedLogin, WorkerList


def worker_suggestions(workers: WorkerList, register: Path | None, files: DadFiles, today: date) -> contract.WorkerSuggestions:
    if register is None:
        return contract.WorkerSuggestions(state="not_set", suggestions=[], message=messages.worker_suggestions_not_set())
    since = period_of(today).tuesday - timedelta(weeks=RECENT_PERIODS - 1)
    try:
        areas = intermax_ordering.paste_areas(register_file.read(register, files, despite_excel_lock=True))
        orders = register_file.recent_workers(areas, since)
    except (WorkbookError, UnsupportedShape):
        return contract.WorkerSuggestions(state="unreadable", suggestions=[], message=messages.worker_suggestions_unreadable())
    except StopError as stop:
        return contract.WorkerSuggestions(state="unreadable", suggestions=[], message=stop.message.what)
    listed: set[str] = {login for worker in workers.workers for login in worker.logins}
    listed |= {normalize_text(item.login) for item in workers.unresolved if isinstance(item, UnmatchedLogin)}
    ranked = sorted(((login, count) for login, count in orders.items() if login not in listed), key=lambda item: (-item[1], item[0]))
    return contract.WorkerSuggestions(
        state="read",
        suggestions=[contract.WorkerSuggestion(login=login, orders=count) for login, count in ranked],
        message=None,
    )
