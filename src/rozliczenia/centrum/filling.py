from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import collective_file
from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.centrum import fill_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import filling as filling_contract
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.live_file import GoodRead, LastGoodReads, saved_version
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_board import requested_folder
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.dad_files import DadFiles
from rozliczenia.file_state import file_state, path_state
from rozliczenia.collective_file import NumberedOrders
from rozliczenia.message import Message
from rozliczenia.order_facts import MissingHeaders
from rozliczenia.period_folder import PeriodFolder
from rozliczenia.quantities_to_fill import TEXT_COLUMNS, KindToFill, fill_hint, quantities_to_fill
from rozliczenia.tool_entry import FillKind
from rozliczenia.quantity_engine import QuantityRules
from rozliczenia.centrum.settings.files import Unreadable
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.text import plural
from rozliczenia.workbook_files import WorkbookError, excel_lock_file


class FillingReads:
    def __init__(self, work: CentrumWork, files: DadFiles) -> None:
        self.reads: LastGoodReads[NumberedOrders] = LastGoodReads(clock=work.clock)
        self.files = files

    def run_ended(self, run: EndedRun) -> None:
        if not run.files_unchanged:
            self.reads.forget_all()


def filling_router(settings: CentrumSettings, log: CentrumLog, cloud_files: CloudFiles, filling: FillingReads) -> APIRouter:
    router = APIRouter(prefix="/api/periods", tags=["okresy"])

    def read(token: str, path: Path) -> GoodRead[NumberedOrders] | filling_contract.QuantitiesToFillProblem:
        reads = filling.reads
        attempt = reads.attempt(path)
        found = _attempt(path, cloud_files, filling.files)
        if not isinstance(found, _Unreadable):
            return reads.succeeded(path, found, attempt)
        failing = reads.failed(path, attempt, cause=found.message.code)
        if failing.new_cause:
            log.fill_unreadable(
                period=token, cause=found.message.code, excel_lock=_excel_lock(path), failure=found.type
            )
        if failing.kept is not None:
            return failing.kept
        return filling_contract.QuantitiesToFillProblem(
            state="problem",
            message=common_contract.Message.of(found.message),
            version=attempt.version,
            collective_file_exists=file_state(path) == "file",
        )

    @router.get(
        "/{token}/quantities-to-fill", operation_id="getQuantitiesToFill", responses=NOT_FOUND_OR_CONFLICT
    )
    def quantities(token: str) -> filling_contract.QuantitiesToFill:
        folder = requested_folder(settings, token)
        rules, legend = settings.quantity_rules().rules, settings.counted_activity_legend()
        found = read(token, folder.collective_file)
        if isinstance(found, filling_contract.QuantitiesToFillProblem):
            return found
        return _ready(found, rules, legend, settled=folder.observe().settled)

    @router.get(
        "/{token}/quantities-to-fill/{kind}", operation_id="getKindTable", responses=NOT_FOUND_OR_CONFLICT
    )
    def kind_table(token: str, kind: FillKind) -> filling_contract.KindTable:
        folder = requested_folder(settings, token)
        rules, legend = settings.quantity_rules().rules, settings.counted_activity_legend()
        found = read(token, folder.collective_file)
        if isinstance(found, filling_contract.QuantitiesToFillProblem):
            return found
        settled = folder.observe().settled
        [listed] = (
            listed for listed in quantities_to_fill(found.value.rows, rules, legend, settled=settled).kinds if listed.kind is kind
        )
        return _table(listed, found, rules, settled=settled)

    @router.get(
        "/{token}/collective-file-version",
        operation_id="getCollectiveFileVersion",
        responses=NOT_FOUND_OR_CONFLICT,
    )
    def collective_file_version(token: str) -> filling_contract.CollectiveFileVersion:
        """Znacznik zapisu Pliku zbiorczego bez otwierania skoroszytu: strona porównuje go z ``read.version``."""

        return filling_contract.CollectiveFileVersion(version=saved_version(requested_folder(settings, token).collective_file))

    @router.get("/{token}/without-quantity", operation_id="getWithoutQuantity", responses=NOT_FOUND_OR_CONFLICT)
    def rows_without_quantity(token: str) -> filling_contract.WithoutQuantity:
        """Wiersze bez ilości dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń tego okresu.

        Tylko na żądanie wybranego okresu, bo odczyt trwa u taty ponad sekundę. Nieudany odczyt Pliku zbiorczego nie
        blokuje startu; Komunikat i wpis w dzienniku daje strona Uzupełnienia, a sam Przebieg rozliczeń nazywa plik.
        Plik pary Reguł ilości albo Legendy czynności bez odczytu to też wiersze nieprzeczytane, a start odmawia wtedy
        zdaniem o tym pliku.
        """

        folder = requested_folder(settings, token)
        snapshot = settings.snapshot()
        rules, legend = snapshot.quantity_rules_or_unreadable, snapshot.activity_legend_or_unreadable
        if isinstance(rules, Unreadable) or isinstance(legend, Unreadable):
            return filling_contract.WithoutQuantityUnread(state="unread")
        return _without_quantity(folder, filling.files, rules, legend)

    return router


def without_quantity_sentence(rows: Sequence[int]) -> str | None:
    if not rows:
        return None
    count = len(rows)
    return f"{count} {plural(count, 'wiersz', 'wiersze', 'wierszy')} bez ilości: {', '.join(map(str, rows))}"


def _without_quantity(
    folder: PeriodFolder, files: DadFiles, rules: QuantityRules, legend: ActivityLegend
) -> filling_contract.WithoutQuantity:
    try:
        found = collective_file.read_numbered_orders(folder.collective_file, files)
    except WorkbookError:
        return filling_contract.WithoutQuantityUnread(state="unread")
    if isinstance(found, MissingHeaders):
        return filling_contract.WithoutQuantityUnread(state="unread")
    rows = list(quantities_to_fill(found.rows, rules, legend, settled=folder.observe().settled).without_quantity)
    return filling_contract.WithoutQuantityRead(state="read", sentence=without_quantity_sentence(rows))


def _ready(
    read: GoodRead[NumberedOrders], rules: QuantityRules, legend: ActivityLegend, *, settled: bool
) -> filling_contract.QuantitiesToFillReady:
    found = quantities_to_fill(read.value.rows, rules, legend, settled=settled)
    return filling_contract.QuantitiesToFillReady(
        state="ready",
        read=_stamp(read),
        settled=settled,
        kinds=[
            filling_contract.KindToFill(
                kind=kind.kind,
                hint=fill_hint(kind.kind, rules),
                rows=[filling_contract.RowToFill(row=row.number, state=row.state) for row in kind.rows],
                done=kind.done,
            )
            for kind in found.kinds
        ],
        description_rows=filling_contract.DescriptionRows(
            by_legend=found.description_rows.by_legend, for_tata=found.description_rows.for_tata
        ),
        description_columns=[
            filling_contract.DescriptionColumn(column=column, rows=rows) for column, rows in found.description_filled.items()
        ],
    )


def _table(
    listed: KindToFill, read: GoodRead[NumberedOrders], rules: QuantityRules, *, settled: bool
) -> filling_contract.KindTableReady:
    return filling_contract.KindTableReady(
        state="ready",
        read=_stamp(read),
        settled=settled,
        hint=fill_hint(listed.kind, rules),
        text_columns=[column.target_header for column in TEXT_COLUMNS],
        columns=[filling_contract.PriceListItem(column=column, name=name) for column, name in read.value.price_list.items()],
        rows=[
            filling_contract.KindTableRow(
                row=row.number,
                state=row.state,
                texts=list(row.texts),
                cells=[filling_contract.KindTableCell(source=cell.source, value=cell.value) for cell in row.cells],
            )
            for row in listed.rows
        ],
    )


def _stamp(read: GoodRead[NumberedOrders]) -> filling_contract.CollectiveFileRead:
    return filling_contract.CollectiveFileRead(version=read.version, read_at=read.read_at, retrying=read.retrying)


@dataclass(frozen=True)
class _Unreadable:
    message: Message
    type: str


def _attempt(path: Path, cloud_files: CloudFiles, files: DadFiles) -> NumberedOrders | _Unreadable:
    try:
        read = collective_file.read_numbered_orders(path, files)
    except WorkbookError as error:
        message = (
            fill_messages.only_in_cloud(path)
            if cloud_files.online_only(path)
            else fill_messages.collective_file_unusable(error)
        )
        return _Unreadable(message, type(error.__cause__).__name__ if error.__cause__ else "-")
    if isinstance(read, MissingHeaders):
        return _Unreadable(fill_messages.headers_missing(path, read.headers), "-")
    return read


def _excel_lock(path: Path) -> str:
    # ZEWNĘTRZNE: os.access w Windows nie czyta ACL, tylko atrybut tylko do odczytu, więc nie mówi, czy system da plik blokady (CPython Modules/posixmodule.c, os_access_impl)
    match path_state(excel_lock_file(path)):
        case "missing":
            return "nie"
        case "inaccessible":
            return "nieznany"
        case "file" | "folder":
            return "tak"
