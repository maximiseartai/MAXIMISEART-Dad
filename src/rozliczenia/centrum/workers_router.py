"""Interfejs HTTP sekcji Wykonawcy w Ustawieniach Centrum (ADR 0032): tata dodaje Wykonawcę, zmienia go formularzem,
przełącza Nieaktywnego i Przypomnienia o raporcie i usuwa Wykonawcę, którego login nie występuje w żadnym okresie.

Listę Wykonawców i jej reguły ma właściciel Ustawień (``settings``), a zmiany wpisu ``settings.workers``; tu są tylko
żądania przeglądarki, sprawdzenie okresów i odmowy. Zła wartość formularza to 422 z polem formularza (``nazwa``,
``adresy[1]``), a Wykonawca albo login, który występuje w okresie albo którego nie da się sprawdzić, to 409 z
propozycją Nieaktywnego. Okresy sprawdza się przed zapisem, poza blokadą właściciela, bo pierwsze sprawdzenie czyta
Plik zbiorczy każdego okresu; zapis odmawia, gdy loginy Wykonawcy zmieniły się w tym czasie.
"""

from __future__ import annotations

from fastapi import APIRouter

from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import settings as settings_contract
from rozliczenia.centrum.contract import settings_workers as contract
from rozliczenia.centrum.refusal import Kept
from rozliczenia.centrum.settings import messages, workers
from rozliczenia.centrum.settings.files import FieldProblem, usable
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.workers import WORKERS, WorkerForm
from rozliczenia.centrum.settings_router import describe
from rozliczenia.text import normalize_text
from rozliczenia.worker_list import Worker, WorkerList
from rozliczenia.worker_periods import NotInPeriods, WorkerPeriods, old_name_periods

# Odmowy w OpenAPI: zła wartość formularza (422) i Wykonawca albo login, który zostaje (409), obie jako ``Problem``.
_REFUSED: dict[int | str, dict[str, object]] = {422: {"model": common_contract.Problem}}
_KEPT: dict[int | str, dict[str, object]] = {409: {"model": common_contract.Problem}, **_REFUSED}


def workers_router(settings: CentrumSettings, periods: WorkerPeriods) -> APIRouter:
    router = APIRouter(prefix="/api/settings/workers", tags=["ustawienia"])

    @router.post("", operation_id="addWorker", responses=_REFUSED)
    def add(form: contract.WorkerForm) -> settings_contract.Choice:
        return _choice(settings, settings.change(WORKERS, lambda current: workers.added(current, _form(form))))

    @router.put("/{login}", operation_id="changeWorker", responses=_KEPT)
    def change(login: str, edit: contract.WorkerEdit) -> settings_contract.WorkerSaved:
        """Formularz Wykonawcy naraz. Zła wartość jest odmową, zanim cokolwiek się sprawdza; zmiana nazwy, przy której w
        okresie leży Rozliczenie pracownika ze starą nazwą, bez ``rename_confirmed`` niczego nie zapisuje i daje
        ostrzeżenie; usunięty login musi przejść sprawdzenie okresów."""

        listed = _listed(settings)
        worker = _worker(listed, login)
        seen = frozenset(worker.logins)
        form = _form(edit)
        trial = workers.edited(listed, login, form, seen)
        if isinstance(trial, FieldProblem):
            raise refusal.setting_refused(trial)
        if not edit.rename_confirmed:
            old = old_name_periods(worker.name, edit.name, settings.snapshot().folders.periods_directory)
            if old:
                return settings_contract.WorkerSaved(
                    settings=describe(settings.view()), rename_warning=messages.worker_rename_old_files(old)
                )
        kept = seen - {normalize_text(entered) for entered in edit.logins}
        if kept:
            _ensure_not_in_periods(settings, periods, kept, "login")
        choice = _choice(settings, settings.change(WORKERS, lambda current: workers.edited(current, login, form, seen)))
        return settings_contract.WorkerSaved(settings=choice.settings, change=choice.change)

    @router.put("/{login}/switches", operation_id="switchWorker", responses=_REFUSED)
    def switch(login: str, switches: contract.WorkerSwitches) -> settings_contract.Choice:
        return _choice(
            settings,
            settings.change(
                WORKERS,
                lambda current: workers.switched(current, login, active=switches.active, reminders=switches.reminders),
            ),
        )

    @router.delete("/{login}", operation_id="removeWorker", responses=_KEPT)
    def remove(login: str) -> settings_contract.Choice:
        """Usuwa Wykonawcę tylko po pełnym sprawdzeniu okresów, w którym żaden jego login nie występuje."""

        seen = frozenset(_worker(_listed(settings), login).logins)
        _ensure_not_in_periods(settings, periods, seen, "worker")
        return _choice(settings, settings.change(WORKERS, lambda current: workers.removed(current, login, seen)))

    return router


def _form(form: contract.WorkerForm) -> WorkerForm:
    return WorkerForm(form.logins, form.name, form.addresses)


def _listed(settings: CentrumSettings) -> WorkerList:
    """Lista Wykonawców, od której zaczyna zmiana: dobra albo ostatnia dobra przy złym pliku."""

    listed = usable(settings.view().workers)
    if listed is None:
        raise refusal.workers_unusable(None)
    return listed


def _worker(listed: WorkerList, login: str) -> Worker:
    found = workers.worker_of(listed, login)
    if found is None:
        raise refusal.setting_refused(FieldProblem(None, messages.worker_unknown()))
    return found


def _ensure_not_in_periods(settings: CentrumSettings, periods: WorkerPeriods, logins: frozenset[str], kept: Kept) -> None:
    folders = settings.snapshot().folders
    presence = periods.find(logins, folders.register, folders.periods_directory)
    if not isinstance(presence, NotInPeriods):
        raise refusal.worker_kept(presence, kept)


def _choice(settings: CentrumSettings, result: Saved | Refused | NotSaved) -> settings_contract.Choice:
    match result:
        case Saved(change=change):
            return settings_contract.Choice(settings=describe(settings.view()), change=change)
        case Refused(problem=problem):
            raise refusal.setting_refused(problem)
        case NotSaved():
            raise refusal.settings_not_saved()
