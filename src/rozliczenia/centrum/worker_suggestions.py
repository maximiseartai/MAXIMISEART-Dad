"""Podpowiedzi sekcji Wykonawcy (ADR 0032, US 24): loginy z ``WYKONAWCA`` ostatnich zleceń Rejestru zleceń, których nie
ma na Liście Wykonawców, do dodania przyciskiem „Dodaj Wykonawcę”.

Ostatnie zlecenia to uporządkowane zlecenia bieżącego okresu i okresów, które Tablica okresów pokazuje razem z nim od
razu (``RECENT_PERIODS``): nowy pracownik taty pojawia się w nich w pierwszym tygodniu pracy, a login, którego dawno nie
ma w zleceniach (pracownik sprzed narzędzia albo literówka sprzed miesięcy), nie wraca przy każdym otwarciu sekcji.

Login, który ma Wykonawca (także Nieaktywny), albo login sprawy „login bez Wykonawcy” po przeniesieniu starych plików,
który ma już swój przycisk z adresami, nie jest podpowiedzią. Po dodaniu Wykonawcy z loginem podpowiedź znika. Odczyt
niczego nie zapisuje, a odpowiedź ma tylko loginy i liczby zleceń: bez numerów, adresów, umów i dat (ADR 0028).
Niewskazany Rejestr, Rejestr, którego nie da się przeczytać, i Rejestr bez obszaru wklejania to zdanie dla taty, a nie
pusta lista. Obszary wklejania rozpoznaje ta sama reguła co procesy (``intermax_ordering.paste_areas``), więc Rejestr bez
nich (np. arkusz zleceń w starszym układzie bez AKCJE i UWAGI) ma w sekcji zdanie „Co się stało” tego samego Komunikatu.
"""

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
    """Loginy ostatnich zleceń Rejestru zleceń ``register`` spoza Listy Wykonawców ``workers`` z liczbą tych zleceń, od
    najczęstszego; Rejestr czyta uchwyt plików taty ``files``, także otwarty w Excelu (jego ostatnią zapisaną wersję)."""

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
