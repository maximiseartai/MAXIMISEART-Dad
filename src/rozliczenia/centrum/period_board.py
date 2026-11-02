"""Tablica okresów: Foldery okresu z folderu okresów, ich Status okresu i Droga okresu, wyliczane przy każdym odczycie.

Nie ma bazy ani pamięci podręcznej. Foldery okresu, ścieżki ich plików,
obserwację plików i Status okresu z nazwą zna silnik (``period_folder``);
treści skoroszytów Centrum nie czyta. Wycena w efenix okresu jest zaliczona, gdy
ostatnie jej Uruchomienie w Historii (plik metryk procesu) skończyło się wynikiem
OK; Statusu okresu nie zmienia. Tu są Droga okresu, następny krok i krok obok
niego (podpowiedź podglądu deklaruje proces w ``run_view``) oraz etykiety i wybór plików do otwarcia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Final, Literal

from fastapi import APIRouter

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.catalog import EFENIX
from rozliczenia.centrum.metrics import last_results
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.processes import Processes
from rozliczenia.settings import SettingsStore
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodFolderLookupError,
    PeriodFolders,
    PeriodStatus,
    locate_period_folder,
    month_folder_label,
    period_status_label,
    reading,
    scan_period_folders,
)
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token
from rozliczenia.telemetry import MetricsStore

_PREPARE: Final = contract.ProcessStep(
    action="prepare_collective_file",
    label="Przygotuj plik zbiorczy",
    hint="Z Rejestru zleceń powstaną Rozliczenie wewnętrzne i Plik zbiorczy.",
    preview_hint=run_view.PREPARATION.preview_hint,
)
_PRICE: Final = contract.ProcessStep(
    action="price_in_efenix",
    label="Wyceń w efenix",
    hint="Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.",
    preview_hint=None,
)
_PRICE_AGAIN: Final = _PRICE.model_copy(
    update={"hint": "Ostatnia Wycena w efenix nie skończyła się wynikiem OK. Sprawdź jej wynik i uruchom ją ponownie."}
)
_SETTLE: Final = contract.ProcessStep(
    action="create_worker_settlements",
    label="Utwórz rozliczenia pracowników",
    hint="Wycena w efenix skończyła się wynikiem OK. Teraz rozliczenia pracowników z Pliku zbiorczego.",
    preview_hint=run_view.SETTLEMENT.preview_hint,
)
_SETTLE_BEFORE_PRICING: Final = _SETTLE.model_copy(
    update={"hint": "Możesz je utworzyć także bez Wyceny w efenix, na przykład gdy efenix nie działa."}
)
_CLOSED: Final = contract.ClosedStep(
    action="none",
    label="Okres zamknięty",
    hint="Rozliczenia pracowników są w Folderze okresu.",
)
_PATH: Final = ("Plik zbiorczy", "Uzupełnienie w Excelu", "Wycena w efenix", "Rozliczenia pracowników")

Pricing = Literal["not_run", "unfinished", "ok"]
"""Wycena w efenix okresu: bez Uruchomienia, ostatnie bez wyniku OK (Wymaga sprawdzenia, Zatrzymanie) albo zaliczona."""


def _pricing(result: contract.RunResult | None) -> Pricing:
    if result is None:
        return "not_run"
    return "ok" if result == "OK" else "unfinished"


def _path(status: PeriodStatus, pricing: Pricing) -> list[contract.PathStep]:
    """Krok jest zrobiony po kolei; Uzupełnienie w Excelu kończy Gotowość, którą potwierdza start Wyceny w efenix."""

    settled = status == "worker_settlements_ready"
    done = (
        status != "no_period_files",
        settled or pricing != "not_run",
        pricing == "ok",
        settled,
    )
    if settled:
        stages: list[contract.PathStage] = ["done" if step else "not_done" for step in done]
    else:
        now = done.index(False)
        stages = ["done" if index < now else "now" if index == now else "later" for index in range(len(done))]
    return [contract.PathStep(label=label, stage=stage) for label, stage in zip(_PATH, stages, strict=True)]


def _steps(status: PeriodStatus, pricing: Pricing) -> tuple[contract.NextStep, contract.ProcessStep | None]:
    """Następny krok okresu i krok obok niego: Przebieg rozliczeń nie czeka na Wycenę w efenix, tylko po niej stoi."""

    match status:
        case "no_period_files":
            return _PREPARE, None
        case "worker_settlements_ready":
            return _CLOSED, None
        case "collective_file_prepared":
            if pricing == "ok":
                return _SETTLE, None
            return (_PRICE if pricing == "not_run" else _PRICE_AGAIN), _SETTLE_BEFORE_PRICING


def _row(folder: PeriodFolder, *, last_complete: bool, pricing: Pricing) -> contract.PeriodRow:
    period = folder.period
    observation = folder.observe()
    status = observation.status
    next_step, secondary_step = _steps(status, pricing)
    return contract.PeriodRow(
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
        path=_path(status, pricing),
        next_step=next_step,
        secondary_step=secondary_step,
    )


def read_board(periods_directory: Path | None, today: date, processes: Processes) -> contract.PeriodBoard:
    """Tablica okresów z folderu okresów; ``processes`` daje Historię Wyceny w efenix (plik metryk jej rdzenia)."""

    if periods_directory is None:
        return contract.BoardNotSet(state="not_set")
    if not periods_directory.is_dir():
        return contract.BoardMissing(state="missing", name=periods_directory.name)
    last_complete = last_complete_period(today)
    folders = {folder.period: folder for folder in scan_period_folders(periods_directory).found()}
    folders.setdefault(last_complete, PeriodFolder(periods_directory, last_complete))
    newest_first = sorted(folders.values(), key=lambda folder: folder.period.tuesday, reverse=True)
    efenix = EFENIX.core(processes)
    priced = last_results(MetricsStore(efenix.metrics_path(), efenix.counter_names))
    rows = [
        _row(folder, last_complete=folder.period == last_complete, pricing=_pricing(priced.get(folder.period.token)))
        for folder in newest_first
    ]
    return contract.BoardReady(
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
        raise contract.Refusal(404, "Nie ma takiego okresu.") from None


def located_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    """Jeden Folder okresu dla akcji Centrum; brak albo kilka miejsc to odmowa ze wskazówką dla taty."""

    try:
        return locate_period_folder(periods_directory, period)
    except PeriodFolderLookupError as error:
        token = period.token
        if not error.locations:
            raise contract.Refusal(
                404, f"Nie ma folderu {token} w żadnym folderze miesiąca. Załóż go w folderze INEA właściwego miesiąca."
            ) from None
        months = ", ".join(month_folder_label(error.periods_directory, location) for location in error.locations)
        raise contract.Refusal(
            409, f"Folder {token} jest w więcej niż jednym folderze miesiąca ({months}). Zostaw go tylko w jednym."
        ) from None


_TARGET_LABELS: dict[contract.OpenTarget, str] = {
    "internal_settlement": "Rozliczenie wewnętrzne",
    "collective_file": "Plik zbiorczy",
    "period_folder": "Folder okresu",
    "worker_settlements_folder": "Folder rozliczeń pracowników",
}


def periods_router(
    store: SettingsStore, platform: Platform, today: Callable[[], date], processes: Processes
) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    @router.get("", operation_id="getPeriodBoard")
    def board() -> contract.PeriodBoard:
        return read_board(store.load().periods_directory, today(), processes)

    def requested_folder(token: str) -> PeriodFolder:
        periods_directory = store.load().periods_directory
        if periods_directory is None or not periods_directory.is_dir():
            raise contract.Refusal(409, "Najpierw wskaż folder okresów.")
        return located_period_folder(periods_directory, requested_period(token))

    @router.post("/{token}/open", operation_id="openPeriodPath", responses=contract.NOT_FOUND_OR_CONFLICT)
    def open_period_path(token: str, request: contract.OpenRequest) -> contract.Opened:
        folder = requested_folder(token)
        path = {
            "internal_settlement": folder.internal_settlement,
            "collective_file": folder.collective_file,
            "period_folder": folder.directory,
            "worker_settlements_folder": folder.worker_settlements,
        }[request.target]
        with reading(folder.directory):
            exists = path.exists()
        if not exists:
            raise contract.Refusal(404, f"{_TARGET_LABELS[request.target]} okresu {token} jeszcze nie istnieje.")
        platform.open_path(path)
        return contract.Opened(name=path.name)

    @router.post(
        "/{token}/worker-settlements/open",
        operation_id="openWorkerSettlement",
        responses=contract.NOT_FOUND_OR_CONFLICT,
    )
    def open_worker_settlement(token: str, request: contract.WorkerSettlementRequest) -> contract.Opened:
        folder = requested_folder(token)
        path = folder.worker_settlement(request.worker)
        # Nazwa Wykonawcy z „/”, „\” albo „..” wyprowadziłaby ścieżkę poza Folder rozliczeń pracowników.
        inside = path.parent == folder.worker_settlements
        with reading(folder.directory):
            exists = inside and path.is_file()
        if not exists:
            raise contract.Refusal(404, f"Rozliczenia pracownika {request.worker} nie ma w okresie {token}.")
        platform.open_path(path)
        return contract.Opened(name=path.name)

    return router
