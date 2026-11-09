"""Tablica okresów: Foldery okresu z folderu okresów, ich Status okresu i Droga okresu, wyliczane przy każdym odczycie.

Nie ma bazy ani pamięci podręcznej. Foldery okresu, ścieżki ich plików,
obserwację plików i Status okresu z nazwą zna silnik (``period_folder``);
treści skoroszytów Centrum nie czyta. Wycena w efenix okresu jest zaliczona, gdy
ostatnie jej Uruchomienie w Historii (plik metryk procesu) skończyło się wynikiem
OK; Statusu okresu nie zmienia. Tu są Droga okresu, następny krok i krok obok
niego (podpowiedź podglądu deklaruje wpis procesu w katalogu procesów) oraz etykiety i wybór plików do otwarcia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Final, Literal

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import periods as periods_contract
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT, Refusal
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.catalog import Catalog, declaration_of
from rozliczenia.centrum.metrics import last_results
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.process_kind import PERIODS_DIRECTORY, first_choose
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodFolderLookupError,
    PeriodFolders,
    PeriodStatus,
    period_place_label,
    locate_period_folder,
    month_folder_label,
    period_status_label,
    reading,
    scan_period_folders,
)
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token



def _process_step(
    action: periods_contract.StepAction, process: common_contract.PeriodProcessKey, label: str, hint: str
) -> periods_contract.ProcessStep:
    """Krok okresu, który robi proces ``process``, z podpowiedzią podglądu z jego wpisu w katalogu procesów."""

    return periods_contract.ProcessStep(
        action=action, process=process, label=label, hint=hint, preview_hint=declaration_of(process).preview_hint
    )


_PREPARE: Final = _process_step(
    "prepare_collective_file",
    "preparation",
    "Przygotuj plik zbiorczy",
    "Z Rejestru zleceń powstaną Rozliczenie wewnętrzne i Plik zbiorczy.",
)
_PRICE: Final = _process_step(
    "price_in_efenix", "efenix", "Wyceń w efenix", "Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij."
)
_FILL: Final = periods_contract.FillStep(
    action="fill_collective_file",
    label="Uzupełnij plik zbiorczy",
    hint="Uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.",
    then=_PRICE,
)
_PRICE_AGAIN: Final = _PRICE.model_copy(
    update={"hint": "Ostatnia Wycena w efenix nie skończyła się wynikiem OK. Sprawdź jej wynik i uruchom ją ponownie."}
)
_SETTLE: Final = _process_step(
    "create_worker_settlements",
    "settlement",
    "Utwórz rozliczenia pracowników",
    "Wycena w efenix skończyła się wynikiem OK. Teraz rozliczenia pracowników z Pliku zbiorczego.",
)
_SETTLE_BEFORE_PRICING: Final = _SETTLE.model_copy(
    update={"hint": "Możesz je utworzyć także bez Wyceny w efenix, na przykład gdy efenix nie działa."}
)
_CLOSED: Final = periods_contract.ClosedStep(
    action="none",
    label="Okres zamknięty",
    hint="Rozliczenia pracowników są w Folderze okresu.",
)
_PATH: Final = ("Plik zbiorczy", "Uzupełnienie w Excelu", "Wycena w efenix", "Rozliczenia pracowników")

Pricing = Literal["not_run", "unfinished", "ok"]
"""Wycena w efenix okresu: bez Uruchomienia, ostatnie bez wyniku OK (Wymaga sprawdzenia, Zatrzymanie) albo zaliczona."""


def _pricing(result: RunResult | None) -> Pricing:
    if result is None:
        return "not_run"
    return "ok" if result == "OK" else "unfinished"


def _path(status: PeriodStatus, pricing: Pricing) -> list[periods_contract.PathStep]:
    """Krok jest zrobiony po kolei; Uzupełnienie w Excelu kończy Gotowość, którą potwierdza skończone Uruchomienie
    Wyceny w efenix okresu w Historii albo Rozliczenia pracowników."""

    settled = status == "worker_settlements_ready"
    done = (
        status != "no_period_files",
        settled or pricing != "not_run",
        pricing == "ok",
        settled,
    )
    if settled:
        stages: list[periods_contract.PathStage] = ["done" if step else "not_done" for step in done]
    else:
        now = done.index(False)
        stages = ["done" if index < now else "now" if index == now else "later" for index in range(len(done))]
    return [periods_contract.PathStep(label=label, stage=stage) for label, stage in zip(_PATH, stages, strict=True)]


def _steps(status: PeriodStatus, pricing: Pricing) -> tuple[periods_contract.NextStep, periods_contract.ProcessStep | None]:
    """Następny krok okresu, czyli bieżący krok Drogi okresu, i krok obok niego: Przebieg rozliczeń nie czeka na Wycenę
    w efenix, tylko po niej stoi."""

    match status:
        case "no_period_files":
            return _PREPARE, None
        case "worker_settlements_ready":
            return _CLOSED, None
        case "collective_file_prepared":
            match pricing:
                case "not_run":
                    return _FILL, _SETTLE_BEFORE_PRICING
                case "unfinished":
                    return _PRICE_AGAIN, _SETTLE_BEFORE_PRICING
                case "ok":
                    return _SETTLE, None


def _row(folder: PeriodFolder, *, last_complete: bool, pricing: Pricing) -> periods_contract.PeriodRow:
    period = folder.period
    observation = folder.observe()
    status = observation.status
    next_step, secondary_step = _steps(status, pricing)
    return periods_contract.PeriodRow(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status=status,
        status_label=period_status_label(status),
        period_folder_exists=observation.period_folder_exists,
        internal_settlement_exists=observation.internal_settlement_exists,
        collective_file_exists=observation.collective_file_exists,
        worker_settlements_folder_exists=observation.worker_settlements_folder_exists,
        worker_settlement_count=observation.worker_settlement_count,
        last_complete=last_complete,
        fillable=status == "collective_file_prepared",
        path=_path(status, pricing),
        next_step=next_step,
        secondary_step=secondary_step,
    )


def read_board(periods_directory: Path | None, today: date, catalog: Catalog) -> periods_contract.PeriodBoard:
    """Tablica okresów z folderu okresów; ``catalog`` daje Historię Wyceny w efenix (jej plik metryk)."""

    if periods_directory is None:
        return periods_contract.BoardNotSet(state="not_set")
    if not periods_directory.is_dir():
        return periods_contract.BoardMissing(state="missing", name=periods_directory.name)
    last_complete = last_complete_period(today)
    folders = {folder.period: folder for folder in scan_period_folders(periods_directory).found()}
    folders.setdefault(last_complete, PeriodFolder(periods_directory, last_complete))
    newest_first = sorted(folders.values(), key=lambda folder: folder.period.tuesday, reverse=True)
    priced = last_results(catalog.metrics("efenix"))
    rows = [
        _row(folder, last_complete=folder.period == last_complete, pricing=_pricing(priced.get(folder.period.token)))
        for folder in newest_first
    ]
    return periods_contract.BoardReady(
        state="ready",
        periods=rows,
        last_prepared_period=next((row.token for row in rows if row.collective_file_exists), None),
    )


def observed_period_folder(folders: PeriodFolders, period: SettlementPeriod) -> PeriodFolder:
    """Folder okresu do pokazania Statusu okresu; brak albo kilka miejsc nie jest tu zatrzymaniem.

    Gdy Folderu okresu nie ma, obserwacja dotyczy nieistniejącego folderu w
    samym folderze okresów; gdy jest w kilku miejscach, pierwszego z nich.
    Zatrzymuje dopiero akcja, która potrzebuje jednego Folderu okresu.
    """

    try:
        return folders.locate(period)
    except PeriodFolderLookupError as error:
        return PeriodFolder(error.locations[0] if error.locations else folders.periods_directory, period)


def requested_period(token: str) -> SettlementPeriod:
    """Okres z tokenu żądania przeglądarki; zły token to odmowa 404."""

    try:
        return parse_period_token(token)
    except ValueError:
        raise Refusal(404, "Nie ma takiego okresu.") from None


def located_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    """Jeden Folder okresu dla akcji Centrum; brak albo kilka miejsc to odmowa ze wskazówką dla taty."""

    try:
        return locate_period_folder(periods_directory, period)
    except PeriodFolderLookupError as error:
        token = period.token
        if not error.locations:
            raise Refusal(
                404, f"Nie ma folderu {token} w żadnym folderze miesiąca. Załóż go w folderze INEA właściwego miesiąca."
            ) from None
        months = ", ".join(month_folder_label(error.periods_directory, location) for location in error.locations)
        raise Refusal(
            409, f"Folder {token} jest w więcej niż jednym folderze miesiąca ({months}). Zostaw go tylko w jednym."
        ) from None


def requested_folder(store: SettingsStore, token: str) -> PeriodFolder:
    """Folder okresu z tokenu żądania przeglądarki; bez folderu okresów na miejscu odmowa „Najpierw wskaż …”."""

    periods_directory = PERIODS_DIRECTORY.existing(store.load())
    if periods_directory is None:
        raise Refusal(409, first_choose((PERIODS_DIRECTORY,)))
    return located_period_folder(periods_directory, requested_period(token))


def periods_router(
    store: SettingsStore, platform: Platform, today: Callable[[], date], catalog: Catalog
) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    @router.get("", operation_id="getPeriodBoard")
    def board() -> periods_contract.PeriodBoard:
        return read_board(store.load().periods_directory, today(), catalog)

    @router.post("/{token}/open", operation_id="openPeriodPath", responses=NOT_FOUND_OR_CONFLICT)
    def open_period_path(token: str, request: periods_contract.OpenRequest) -> common_contract.Opened:
        folder = requested_folder(store, token)
        path = folder.path_of(request.target)
        with reading(folder.directory):
            exists = path.exists()
        if not exists:
            raise Refusal(404, f"{period_place_label(request.target)} okresu {token} jeszcze nie istnieje.")
        platform.open_path(path)
        return common_contract.Opened(name=path.name)

    @router.post(
        "/{token}/worker-settlements/open",
        operation_id="openWorkerSettlement",
        responses=NOT_FOUND_OR_CONFLICT,
    )
    def open_worker_settlement(token: str, request: periods_contract.WorkerSettlementRequest) -> common_contract.Opened:
        folder = requested_folder(store, token)
        path = folder.worker_settlement(request.worker)
        # Nazwa Wykonawcy z „/”, „\” albo „..” wyprowadziłaby ścieżkę poza Folder rozliczeń pracowników.
        inside = path.parent == folder.worker_settlements
        with reading(folder.directory):
            exists = inside and path.is_file()
        if not exists:
            raise Refusal(404, f"Rozliczenia pracownika {request.worker} nie ma w okresie {token}.")
        platform.open_path(path)
        return common_contract.Opened(name=path.name)

    return router
