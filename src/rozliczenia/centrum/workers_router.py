"""Interfejs HTTP sekcji Wykonawcy w Ustawieniach Centrum (ADR 0032): tata dodaje Wykonawcę, zmienia go formularzem,
przełącza Nieaktywnego i Przypomnienia o raporcie, usuwa Wykonawcę, którego login nie występuje w żadnym okresie,
przypisuje Wykonawcy adres nieznanego nadawcy z widoku Raporty i widzi podpowiedzi loginów z ostatnich zleceń Rejestru
zleceń (``worker_suggestions``).

Listę Wykonawców i jej reguły ma właściciel Ustawień (``settings``), także sprawdzenie okresów przy każdym usunięciu
loginu, a zmiany wpisu ``settings.workers``; tu są tylko żądania przeglądarki i odmowy. Zła wartość formularza to 422 z
polem formularza (``nazwa``, ``adresy[1]``), a Wykonawca albo login, który występuje w okresie albo którego nie da się
sprawdzić, to 409 z propozycją Nieaktywnego.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter

from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import settings as settings_contract
from rozliczenia.centrum.contract import settings_workers as contract
from rozliczenia.centrum.settings import messages, workers
from rozliczenia.centrum.settings.files import FieldProblem, usable
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.centrum.settings.workers import WORKERS, WorkerForm
from rozliczenia.centrum.settings_router import choice, describe
from rozliczenia.centrum.worker_suggestions import worker_suggestions
from rozliczenia.dad_files import DadFiles
from rozliczenia.worker_list import Worker, WorkerList
from rozliczenia.worker_periods import old_name_periods

_REFUSED: dict[int | str, dict[str, object]] = {422: {"model": common_contract.Problem}}
"""Odmowa w OpenAPI: zła wartość formularza (422) jako ``Problem``."""
_KEPT: dict[int | str, dict[str, object]] = {409: {"model": common_contract.Problem}, **_REFUSED}
"""Odmowy w OpenAPI: zła wartość formularza (422) i Wykonawca albo login, który zostaje (409), obie jako ``Problem``."""


def workers_router(settings: CentrumSettings, files: DadFiles, today: Callable[[], date]) -> APIRouter:
    """``files``: uchwyt plików taty pracy Centrum, którym podpowiedzi czytają Rejestr zleceń; ``today``: dzień taty,
    od którego liczą się ostatnie okresy podpowiedzi."""

    router = APIRouter(prefix="/api/settings/workers", tags=["ustawienia"])

    @router.post("", operation_id="addWorker", responses=_REFUSED)
    def add(form: contract.WorkerForm) -> settings_contract.Choice:
        return choice(settings, settings.change(WORKERS, lambda current: workers.added(current, _form(form))))

    @router.put("/{login}", operation_id="changeWorker", responses=_KEPT)
    def change(login: str, edit: contract.WorkerEdit) -> settings_contract.WorkerSaved:
        """Formularz Wykonawcy naraz. Zła wartość jest odmową, zanim cokolwiek się sprawdza; zmiana nazwy, przy której w
        okresie leży Rozliczenie pracownika ze starą nazwą, bez ``rename_confirmed`` niczego nie zapisuje i daje
        ostrzeżenie; usunięty login sprawdza w okresach właściciel."""

        listed = _listed(settings)
        worker = _worker(listed, login)
        form = _form(edit)
        trial = workers.edited(listed, login, form)
        if isinstance(trial, FieldProblem):
            raise refusal.setting_refused(trial)
        if not edit.rename_confirmed:
            old = old_name_periods(worker.name, edit.name, settings.snapshot().folders.periods_directory)
            if old:
                return settings_contract.WorkerSaved(
                    settings=describe(settings.view()), rename_warning=messages.worker_rename_old_files(old)
                )
        saved = choice(settings, settings.change(WORKERS, lambda current: workers.edited(current, login, form)))
        return settings_contract.WorkerSaved(settings=saved.settings, change=saved.change)

    @router.get("/suggestions", operation_id="getWorkerSuggestions")
    def suggestions() -> contract.WorkerSuggestions:
        """Loginy ostatnich zleceń Rejestru zleceń spoza Listy Wykonawców (``worker_suggestions``), bez zapisu. Lista
        Wykonawców, której nie ma (nieczytelna albo zła bez ostatniej dobrej), jest pusta: sekcja pokazuje wtedy zdanie
        o liście, a dodanie zapisuje listę od nowa."""

        snapshot = settings.snapshot()
        listed = usable(snapshot.workers) or WorkerList(())
        return worker_suggestions(listed, snapshot.folders.register, files, today())

    @router.post("/{login}/addresses", operation_id="assignWorkerAddress", responses=_REFUSED)
    def assign_address(login: str, assigned: contract.WorkerAddress) -> settings_contract.Choice:
        """„Przypisz do Wykonawcy…” z widoku Raporty: adres nieznanego nadawcy na końcu adresów Wykonawcy, zapisany od
        razu jak pojedynczy wybór (ADR 0032), tą samą drogą i regułami co formularz; loginów nie usuwa."""

        return choice(
            settings, settings.change(WORKERS, lambda current: workers.address_assigned(current, login, assigned.address))
        )

    @router.put("/{login}/switches", operation_id="switchWorker", responses=_REFUSED)
    def switch(login: str, switches: contract.WorkerSwitches) -> settings_contract.Choice:
        return choice(
            settings,
            settings.change(
                WORKERS,
                lambda current: workers.switched(current, login, active=switches.active, reminders=switches.reminders),
            ),
        )

    @router.delete("/{login}", operation_id="removeWorker", responses=_KEPT)
    def remove(login: str) -> settings_contract.Choice:
        """Usuwa Wykonawcę; właściciel zapisuje to tylko po pełnym sprawdzeniu okresów, w którym żaden jego login nie
        występuje."""

        _worker(_listed(settings), login)
        return choice(settings, settings.change(WORKERS, lambda current: workers.removed(current, login)))

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
