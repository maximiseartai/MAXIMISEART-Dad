from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Final, Literal, get_args

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import periods as periods_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.catalog import Catalog, declaration_of
from rozliczenia.centrum.metrics import last_results
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.process_kind import PERIODS_DIRECTORY
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.file_state import file_state, path_state
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    PeriodFolderObservation,
    PeriodFolders,
    PeriodPlace,
    PeriodStatus,
    locate_period_folder,
    period_place_label,
    period_status_label,
    scan_period_folders,
)
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period, parse_period_token



def _process_step(
    action: periods_contract.StepAction, process: common_contract.PeriodProcessKey, label: str, hint: str
) -> periods_contract.ProcessStep:
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


def _pricing(result: RunResult | None) -> Pricing:
    if result is None:
        return "not_run"
    return "ok" if result == "OK" else "unfinished"


def _path(status: PeriodStatus, pricing: Pricing) -> list[periods_contract.PathStep]:
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


RECENT_PERIODS: Final = 5


def _board_places(newest_first: Sequence[SettlementPeriod], today: date) -> list[periods_contract.BoardPlace]:
    places: list[periods_contract.BoardPlace] = []
    started = 0
    for period in newest_first:
        if period.tuesday > today:
            places.append("not_started")
            continue
        places.append("recent" if started < RECENT_PERIODS else "older")
        started += 1
    return places


def _row(
    folder: PeriodFolder, *, last_complete: bool, board_place: periods_contract.BoardPlace, pricing: Pricing
) -> periods_contract.PeriodRow:
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
        files=[_file(observation, place) for place in get_args(PeriodPlace)],
        last_complete=last_complete,
        board_place=board_place,
        fillable=status == "collective_file_prepared",
        path=_path(status, pricing),
        next_step=next_step,
        secondary_step=secondary_step,
    )


def _file(observation: PeriodFolderObservation, place: PeriodPlace) -> periods_contract.BoardFile:
    exists = observation.exists(place)
    counted = place == "worker_settlements_folder" and exists
    return periods_contract.BoardFile(
        target=place,
        label=period_place_label(place),
        exists=exists,
        count=observation.worker_settlement_count if counted else None,
    )


def _has_collective_file(row: periods_contract.PeriodRow) -> bool:
    return any(file.target == "collective_file" and file.exists for file in row.files)


def read_board(periods_directory: Path | None, today: date, catalog: Catalog) -> periods_contract.PeriodBoard:
    return board_of(None if periods_directory is None else scan_period_folders(periods_directory), today, catalog)


def board_of(scanned: PeriodFolders | None, today: date, catalog: Catalog) -> periods_contract.PeriodBoard:
    if scanned is None:
        return periods_contract.BoardNotSet(state="not_set")
    periods_directory = scanned.periods_directory
    if scanned.periods_directory_missing:
        return periods_contract.BoardMissing(state="missing", name=periods_directory.name)
    last_complete = last_complete_period(today)
    folders = {folder.period: folder for folder in scanned.found()}
    folders.setdefault(last_complete, PeriodFolder(periods_directory, last_complete))
    newest_first = sorted(folders.values(), key=lambda folder: folder.period.tuesday, reverse=True)
    priced = last_results(catalog.metrics("efenix"))
    places = _board_places([folder.period for folder in newest_first], today)
    rows = [
        _row(
            folder,
            last_complete=folder.period == last_complete,
            board_place=place,
            pricing=_pricing(priced.get(folder.period.token)),
        )
        for folder, place in zip(newest_first, places, strict=True)
    ]
    return periods_contract.BoardReady(
        state="ready",
        periods=rows,
        last_prepared_period=next((row.token for row in rows if _has_collective_file(row)), None),
    )


def observed_period_folder(folders: PeriodFolders, period: SettlementPeriod) -> PeriodFolder:
    try:
        return folders.locate(period)
    except PeriodFolderLookupError as error:
        return PeriodFolder(error.locations[0] if error.locations else folders.periods_directory, period)


def requested_period(token: str) -> SettlementPeriod:
    try:
        return parse_period_token(token)
    except ValueError:
        raise refusal.unknown_period() from None


def located_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    try:
        return locate_period_folder(periods_directory, period)
    except PeriodFolderLookupError as error:
        raise refusal.period_folder_lookup(error) from None


def requested_folder(settings: CentrumSettings, token: str) -> PeriodFolder:
    periods_directory = settings.folders().periods_directory_to_read
    if periods_directory is None:
        raise refusal.first_choose((PERIODS_DIRECTORY.name,))
    return located_period_folder(periods_directory, requested_period(token))


def periods_router(
    settings: CentrumSettings, platform: Platform, today: Callable[[], date], catalog: Catalog
) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    @router.get("", operation_id="getPeriodBoard", responses={409: {"model": common_contract.Problem}})
    def board() -> periods_contract.PeriodBoard:
        return read_board(settings.folders().periods_directory, today(), catalog)

    @router.post("/{token}/open", operation_id="openPeriodPath", responses=NOT_FOUND_OR_CONFLICT)
    def open_period_path(token: str, request: periods_contract.OpenRequest) -> common_contract.Opened:
        folder = requested_folder(settings, token)
        path = folder.path_of(request.target)
        match path_state(path):
            case "inaccessible":
                raise PeriodFolderInaccessible(folder.directory)
            case "missing":
                raise refusal.place_missing(request.target, token)
            case "file" | "folder":
                pass
        platform.open_path(path)
        return common_contract.Opened(name=path.name)

    @router.post(
        "/{token}/worker-settlements/open",
        operation_id="openWorkerSettlement",
        responses=NOT_FOUND_OR_CONFLICT,
    )
    def open_worker_settlement(token: str, request: periods_contract.WorkerSettlementRequest) -> common_contract.Opened:
        folder = requested_folder(settings, token)
        path = folder.worker_settlement(request.worker)
        inside = path.parent == folder.worker_settlements
        match file_state(path) if inside else "missing":
            case "inaccessible":
                raise PeriodFolderInaccessible(folder.directory)
            case "missing":
                raise refusal.worker_settlement_missing(request.worker, token)
            case "file":
                pass
        platform.open_path(path)
        return common_contract.Opened(name=path.name)

    return router
