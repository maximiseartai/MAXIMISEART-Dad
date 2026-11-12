"""Uzupełnienie pliku zbiorczego w Centrum: Ilości do uzupełnienia okresu jako zasób tylko do odczytu (ADR 0016).

Każde żądanie czyta zapisany Plik zbiorczy jedynym odczytem skoroszytu, także gdy trzyma go Excel, i przelicza
Ilości do uzupełnienia w silniku (``quantities_to_fill``); Centrum nigdy nie zmienia pliku. Na żywo: tani znacznik
zapisu i ostatni dobry odczyt (``live_file``, ``FillingReads``).
Podsumowanie dostaje tylko numery wierszy, stan „zrobione” i liczniki kolumn, a strona rodzaju też teksty
wiersza, komórki N:AP i nazwy pozycji cennika, nigdy adres, numer zlecenia ani UMOWA. Nieudany odczyt to
Komunikat, który nazywa Plik zbiorczy, i wpis w dzienniku Centrum z przyczyną, bez treści wierszy. Czy Przebieg
rozliczeń okresu się odbył, mówi Status okresu z plików Folderu okresu, ten sam co na Tablicy okresów.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from rozliczenia import collective_file
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
from rozliczenia.quantities_to_fill import TEXT_COLUMNS, FillKind, KindToFill, fill_hint, quantities_to_fill
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.text import plural
from rozliczenia.workbook_files import WorkbookError, excel_lock_file


class FillingReads:
    """Ostatnie dobre odczyty Plików zbiorczych dla stron Uzupełnienia i działanie po wyniku Uruchomienia.

    Uruchomienie, które zmieniło pliki okresu (``files_unchanged`` fałszywe), mogło podmienić jego Plik zbiorczy, więc
    ostatni dobry odczyt sprzed niego nie zastępuje już nieudanego odczytu: ``run_ended`` (``runs.AfterRun``) zapomina
    odczyty wszystkich plików, zanim karta wyniku dostanie wynik. Pliki innych okresów tracą przez to tylko minutę
    pokazywania ostatniego dobrego odczytu podczas porażki. Pliki czyta uchwyt plików taty pracy Centrum (``files``),
    którego pamięć reguły danych poznaje komórki zakazanych kolumn każdego odczytu (ADR 0025).
    """

    def __init__(self, work: CentrumWork, files: DadFiles) -> None:
        self.reads: LastGoodReads[NumberedOrders] = LastGoodReads(clock=work.clock)
        self.files = files

    def run_ended(self, run: EndedRun) -> None:
        if not run.files_unchanged:
            self.reads.forget_all()


def filling_router(store: SettingsStore, log: CentrumLog, cloud_files: CloudFiles, filling: FillingReads) -> APIRouter:
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
        folder = requested_folder(store, token)
        found = read(token, folder.collective_file)
        if isinstance(found, filling_contract.QuantitiesToFillProblem):
            return found
        return _ready(found, settled=_settled(folder))

    @router.get(
        "/{token}/quantities-to-fill/{kind}", operation_id="getKindTable", responses=NOT_FOUND_OR_CONFLICT
    )
    def kind_table(token: str, kind: FillKind) -> filling_contract.KindTable:
        folder = requested_folder(store, token)
        found = read(token, folder.collective_file)
        if isinstance(found, filling_contract.QuantitiesToFillProblem):
            return found
        settled = _settled(folder)
        [listed] = (
            listed for listed in quantities_to_fill(found.value.rows, settled=settled).kinds if listed.kind is kind
        )
        return _table(listed, found, settled=settled)

    @router.get(
        "/{token}/collective-file-version",
        operation_id="getCollectiveFileVersion",
        responses=NOT_FOUND_OR_CONFLICT,
    )
    def collective_file_version(token: str) -> filling_contract.CollectiveFileVersion:
        """Znacznik zapisu Pliku zbiorczego bez otwierania skoroszytu: strona porównuje go z ``read.version``."""

        return filling_contract.CollectiveFileVersion(version=saved_version(requested_folder(store, token).collective_file))

    @router.get("/{token}/without-quantity", operation_id="getWithoutQuantity", responses=NOT_FOUND_OR_CONFLICT)
    def rows_without_quantity(token: str) -> filling_contract.WithoutQuantity:
        """Wiersze bez ilości dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń tego okresu.

        Tylko na żądanie wybranego okresu, bo odczyt trwa u taty ponad sekundę. Nieudany odczyt nie blokuje startu;
        Komunikat i wpis w dzienniku daje strona Uzupełnienia, a sam Przebieg rozliczeń nazywa plik.
        """

        return _without_quantity(requested_folder(store, token), filling.files)

    return router


def without_quantity_sentence(rows: Sequence[int]) -> str | None:
    """„1 wiersz bez ilości: 20”, „3 wiersze bez ilości: 18, 19, 20”, „12 wierszy bez ilości: …”; ``None`` bez wierszy."""

    if not rows:
        return None
    count = len(rows)
    return f"{count} {plural(count, 'wiersz', 'wiersze', 'wierszy')} bez ilości: {', '.join(map(str, rows))}"


def _without_quantity(folder: PeriodFolder, files: DadFiles) -> filling_contract.WithoutQuantity:
    try:
        found = collective_file.read_numbered_orders(folder.collective_file, files)
    except WorkbookError:
        return filling_contract.WithoutQuantityUnread(state="unread")
    if isinstance(found, MissingHeaders):
        return filling_contract.WithoutQuantityUnread(state="unread")
    rows = list(quantities_to_fill(found.rows, settled=_settled(folder)).without_quantity)
    return filling_contract.WithoutQuantityRead(state="read", sentence=without_quantity_sentence(rows))


def _settled(folder: PeriodFolder) -> bool:
    return folder.observe().status == "worker_settlements_ready"


def _ready(read: GoodRead[NumberedOrders], *, settled: bool) -> filling_contract.QuantitiesToFillReady:
    found = quantities_to_fill(read.value.rows, settled=settled)
    return filling_contract.QuantitiesToFillReady(
        state="ready",
        read=_stamp(read),
        settled=settled,
        kinds=[
            filling_contract.KindToFill(
                kind=kind.kind,
                hint=fill_hint(kind.kind),
                rows=[filling_contract.RowToFill(row=row.number, state=row.state) for row in kind.rows],
                done=kind.done,
            )
            for kind in found.kinds
        ],
        description_columns=[
            filling_contract.DescriptionColumn(column=column, rows=rows) for column, rows in found.description_filled.items()
        ],
    )


def _table(listed: KindToFill, read: GoodRead[NumberedOrders], *, settled: bool) -> filling_contract.KindTableReady:
    return filling_contract.KindTableReady(
        state="ready",
        read=_stamp(read),
        settled=settled,
        hint=fill_hint(listed.kind),
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
    """Odczyt Pliku zbiorczego bez Ilości do uzupełnienia: Komunikat i typ błędu dla dziennika (``-`` bez niego)."""

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
    """``tak`` albo ``nie`` tylko wtedy, gdy system odpowiedział o pliku blokady; inaczej ``nieznany``.

    ``path_state`` sprawdza prawa jak każdy odczyt, także ACL w Windows, gdzie ``os.access`` ich nie widzi.
    """

    match path_state(excel_lock_file(path)):
        case "missing":
            return "nie"
        case "inaccessible":
            return "nieznany"
        case "file" | "folder":
            return "tak"
