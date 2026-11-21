from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .settlement_period import PERIOD_TOKEN_PATTERN, UNKNOWN_PERIOD, SettlementPeriod, parse_period_token

from .file_state import entry_kind, folder_entries, path_state

_INTERNAL_SETTLEMENT = "Rozliczenie wew. {token}.xlsx"
_COLLECTIVE_FILE = "Rozliczenie {token} - zbiorcze.xlsx"
_WORKER_SETTLEMENTS = "Rozliczenie pracowników {token}"
_WORKER_SETTLEMENT = "Rozliczenie {token} - {worker}.xlsx"

_INTERNAL_SETTLEMENT_MARK = _INTERNAL_SETTLEMENT.partition(" {token}")[0]
_COLLECTIVE_FILE_PREFIX, _, _COLLECTIVE_FILE_SUFFIX = _COLLECTIVE_FILE.partition("{token}")
_COLLECTIVE_FILE_NAME = re.compile(
    rf"{re.escape(_COLLECTIVE_FILE_PREFIX)}(?P<token>{PERIOD_TOKEN_PATTERN}){re.escape(_COLLECTIVE_FILE_SUFFIX)}"
)

_YEAR_FOLDER = re.compile(r"Rozliczenia \d{4}")
_MONTH_PERIODS_FOLDER = "INEA"

PeriodStatus = Literal["no_period_files", "collective_file_prepared", "worker_settlements_ready"]
PeriodPlace = Literal["internal_settlement", "collective_file", "period_folder", "worker_settlements_folder"]
WorkerNameCheck = Literal["fine", "invalid", "too_long"]
# ZEWNĘTRZNE: Windows nie przyjmuje w nazwie pliku znaków <>:"/\|?* ani znaków o kodach 0–31, nazwa pliku nie może kończyć się kropką ani spacją i ma najwyżej 255 jednostek UTF-16 (Microsoft Learn, „Naming Files, Paths, and Namespaces” i „Maximum Path Length Limitation”)
_FORBIDDEN_IN_WINDOWS_FILE_NAME = frozenset('<>:"/\\|?*')
_WINDOWS_MAX_FILE_NAME_UTF16_UNITS = 255
_SAME_LENGTH_AS_EVERY_PERIOD_TOKEN = "00_00_00_0000"


@dataclass(frozen=True)
class NotPeriodToken:
    token: str


@dataclass(frozen=True)
class FolderNotNamedAfterPeriod:
    token: str


CollectiveFileProblem = (
    Literal["internal_settlement", "not_collective_file_name"] | NotPeriodToken | FolderNotNamedAfterPeriod
)


class PeriodFolderError(Exception):
    def __init__(self, problem: CollectiveFileProblem) -> None:
        self.problem: CollectiveFileProblem = problem


class PeriodFolderLookupError(Exception):
    def __init__(self, periods_directory: Path, period: SettlementPeriod, locations: tuple[Path, ...]) -> None:
        super().__init__(period.token)
        self.periods_directory = periods_directory
        self.period = period
        self.locations = locations


class PeriodFolderInaccessible(Exception):
    def __init__(self, folder: Path) -> None:
        super().__init__(folder.name)
        self.folder = folder


@contextmanager
def reading(folder: Path) -> Iterator[None]:
    try:
        yield
    except OSError as error:
        raise PeriodFolderInaccessible(folder) from error


@dataclass(frozen=True)
class PeriodFolder:
    periods_directory: Path
    period: SettlementPeriod

    @classmethod
    def from_collective_file(cls, path: Path) -> PeriodFolder:
        if _INTERNAL_SETTLEMENT_MARK in path.name:
            raise PeriodFolderError("internal_settlement")
        match = _COLLECTIVE_FILE_NAME.fullmatch(path.name)
        if match is None:
            raise PeriodFolderError("not_collective_file_name")
        token = match.group("token")
        try:
            period = parse_period_token(token)
        except ValueError:
            raise PeriodFolderError(NotPeriodToken(token)) from None
        if path.parent.name != token:
            raise PeriodFolderError(FolderNotNamedAfterPeriod(token))
        return cls(path.parent.parent, period)

    @property
    def directory(self) -> Path:
        return self.periods_directory / self.period.token

    @property
    def internal_settlement(self) -> Path:
        return self.directory / _INTERNAL_SETTLEMENT.format(token=self.period.token)

    @property
    def collective_file(self) -> Path:
        return self.directory / collective_file_name(self.period)

    @property
    def worker_settlements(self) -> Path:
        return self.directory / worker_settlements_name_with(self.period.token)

    def path_of(self, place: PeriodPlace) -> Path:
        match place:
            case "internal_settlement":
                return self.internal_settlement
            case "collective_file":
                return self.collective_file
            case "period_folder":
                return self.directory
            case "worker_settlements_folder":
                return self.worker_settlements

    def worker_settlement(self, worker_name: str) -> Path:
        return self.worker_settlements / _WORKER_SETTLEMENT.format(token=self.period.token, worker=worker_name)

    def observe(self) -> PeriodFolderObservation:
        entries = _listing(self.directory)
        if entries is None:
            return PeriodFolderObservation(False, False, False, False, 0)
        listed = {entry.name: entry for entry in entries}
        has_worker_settlements = _exists(listed, self.worker_settlements, directory=True)
        return PeriodFolderObservation(
            period_folder_exists=True,
            internal_settlement_exists=_exists(listed, self.internal_settlement, directory=False),
            collective_file_exists=_exists(listed, self.collective_file, directory=False),
            worker_settlements_folder_exists=has_worker_settlements,
            worker_settlement_count=len(self._worker_settlement_listing()) if has_worker_settlements else 0,
        )

    def worker_settlement_files(self) -> tuple[Path, ...]:
        return tuple(sorted(self.worker_settlements / entry.name for entry in self._worker_settlement_listing()))

    def worker_settlement_entries(self) -> tuple[WorkerSettlementFile, ...]:
        prefix, suffix = self._worker_settlement_affixes()
        return tuple(
            sorted(
                (
                    WorkerSettlementFile(
                        self.worker_settlements / entry.name, entry.name[len(prefix) : -len(suffix)], _modified(entry)
                    )
                    for entry in self._worker_settlement_listing()
                ),
                key=lambda found: found.path,
            )
        )

    def _worker_settlement_affixes(self) -> tuple[str, str]:
        prefix, suffix = _WORKER_SETTLEMENT.format(token=self.period.token, worker="\0").split("\0")
        return prefix, suffix

    def _worker_settlement_listing(self) -> list[os.DirEntry[str]]:
        prefix, suffix = self._worker_settlement_affixes()
        return [
            entry
            for entry in _listing(self.worker_settlements) or ()
            if entry.name.startswith(prefix)
            and entry.name.endswith(suffix)
            and len(entry.name) > len(prefix) + len(suffix)
            and entry_kind(entry) == "file"
        ]


@dataclass(frozen=True)
class WorkerSettlementFile:
    path: Path
    worker: str
    modified_at: datetime | None


# ZEWNĘTRZNE: os.DirEntry.stat w Windows daje chwilę zmiany z listowania folderu, bez wywołania systemowego na samym pliku, więc OneDrive nie otwiera pliku „tylko online” (dokumentacja Pythona, os.DirEntry.stat)
def _modified(entry: os.DirEntry[str]) -> datetime | None:
    try:
        return datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)
    except OSError:
        return None


# ZEWNĘTRZNE: os.scandir podaje z samego listowania, czy wpis jest plikiem czy folderem, a osobny stat każdego wpisu w OneDrive taty otwiera plik (dokumentacja Pythona, os.scandir; docs/agents/komputer-taty.md)
def _listing(directory: Path) -> list[os.DirEntry[str]] | None:
    with reading(directory):
        return folder_entries(directory)


# ZEWNĘTRZNE: Windows i macOS domyślnie nie rozróżniają wielkości liter w nazwach plików, a macOS także postaci Unicode, więc plik może być w listowaniu pod inną nazwą niż szukana (Microsoft Learn, „Case sensitivity”; Apple, „File System Programming Guide”)
def _exists(listed: Mapping[str, os.DirEntry[str]], path: Path, *, directory: bool) -> bool:
    kind = "folder" if directory else "file"
    entry = listed.get(path.name)
    if entry is not None:
        return entry_kind(entry) == kind
    state = path_state(path)
    if state == "inaccessible":
        raise PeriodFolderInaccessible(path.parent)
    return state == kind


def collective_period_token(path: Path) -> str:
    try:
        return PeriodFolder.from_collective_file(path.expanduser().resolve()).period.token
    except PeriodFolderError:
        return UNKNOWN_PERIOD


def collective_file_name(period: SettlementPeriod) -> str:
    return collective_file_name_with(period.token)


def collective_file_name_with(token: str) -> str:
    return _COLLECTIVE_FILE.format(token=token)


def worker_settlements_name_with(token: str) -> str:
    return _WORKER_SETTLEMENTS.format(token=token)


@dataclass(frozen=True)
class PeriodFolderObservation:
    period_folder_exists: bool
    internal_settlement_exists: bool
    collective_file_exists: bool
    worker_settlements_folder_exists: bool
    worker_settlement_count: int

    def exists(self, place: PeriodPlace) -> bool:
        match place:
            case "internal_settlement":
                return self.internal_settlement_exists
            case "collective_file":
                return self.collective_file_exists
            case "period_folder":
                return self.period_folder_exists
            case "worker_settlements_folder":
                return self.worker_settlements_folder_exists

    @property
    def status(self) -> PeriodStatus:
        if self.worker_settlements_folder_exists:
            return "worker_settlements_ready"
        if self.collective_file_exists:
            return "collective_file_prepared"
        return "no_period_files"

    @property
    def settled(self) -> bool:
        return self.status == "worker_settlements_ready"


def period_status_label(status: PeriodStatus) -> str:
    match status:
        case "no_period_files":
            return "Brak plików okresu"
        case "collective_file_prepared":
            return "Plik zbiorczy przygotowany"
        case "worker_settlements_ready":
            return "Rozliczenia pracowników gotowe"


def period_place_label(place: PeriodPlace) -> str:
    match place:
        case "internal_settlement":
            return "Rozliczenie wewnętrzne"
        case "collective_file":
            return "Plik zbiorczy"
        case "period_folder":
            return "Folder okresu"
        case "worker_settlements_folder":
            return "Folder rozliczeń pracowników"


def _month_periods_folders(entries: Iterable[os.DirEntry[str]]) -> list[Path]:
    years = sorted(Path(entry.path) for entry in entries if entry_kind(entry) == "folder" and _YEAR_FOLDER.fullmatch(entry.name))
    return [
        month / _MONTH_PERIODS_FOLDER
        for year in years
        for month in sorted(Path(entry.path) for entry in _listing(year) or () if entry_kind(entry) == "folder")
        if _exists(
            {entry.name: entry for entry in _listing(month) or ()}, month / _MONTH_PERIODS_FOLDER, directory=True
        )
    ]


def _layout(periods_directory: Path, entries: Iterable[os.DirEntry[str]]) -> tuple[Path, list[Path]]:
    if month_folders := _month_periods_folders(entries):
        return periods_directory, month_folders
    for directory in (periods_directory, *periods_directory.parents):
        if _YEAR_FOLDER.fullmatch(directory.name) and (
            month_folders := _month_periods_folders(_listing(directory.parent) or ())
        ):
            return directory.parent, month_folders
    return periods_directory, []


@dataclass(frozen=True)
class LayoutRoot:
    directory: Path
    by_years: bool


def layout_root(path: Path) -> LayoutRoot:
    directory, month_folders = _layout(path, _listing(path) or ())
    return LayoutRoot(directory, bool(month_folders))


def month_folder_label(periods_directory: Path, month_periods_folder: Path) -> str:
    return "\\".join(month_periods_folder.relative_to(periods_directory).parts) or periods_directory.name


@dataclass(frozen=True)
class PeriodFolders:
    periods_directory: Path
    layout_root: Path
    has_month_folders: bool
    locations: Mapping[SettlementPeriod, tuple[Path, ...]]
    periods_directory_missing: bool

    def locate(self, period: SettlementPeriod) -> PeriodFolder:
        found = self.locations.get(period, ())
        if len(found) == 1:
            return PeriodFolder(found[0], period)
        if found or self.has_month_folders:
            raise PeriodFolderLookupError(self.layout_root, period, found)
        return PeriodFolder(self.layout_root, period)

    def found(self) -> list[PeriodFolder]:
        return [PeriodFolder(parents[0], period) for period, parents in self.locations.items()]


def scan_period_folders(periods_directory: Path) -> PeriodFolders:
    entries = _listing(periods_directory)
    if entries is None:
        return PeriodFolders(periods_directory, periods_directory, False, {}, periods_directory_missing=True)
    layout_root, month_folders = _layout(periods_directory, entries)
    locations: dict[SettlementPeriod, list[Path]] = {}
    for parent in (layout_root, *month_folders):
        for entry in _listing(parent) or ():
            if entry_kind(entry) != "folder":
                continue
            try:
                period = parse_period_token(entry.name)
            except ValueError:
                continue
            locations.setdefault(period, []).append(parent)
    return PeriodFolders(
        periods_directory,
        layout_root,
        bool(month_folders),
        {period: tuple(parents) for period, parents in locations.items()},
        periods_directory_missing=False,
    )


def locate_period_folder(periods_directory: Path, period: SettlementPeriod) -> PeriodFolder:
    return scan_period_folders(periods_directory).locate(period)


def check_worker_name(worker_name: str) -> WorkerNameCheck:
    if (
        any(character in _FORBIDDEN_IN_WINDOWS_FILE_NAME or ord(character) < 32 for character in worker_name)
        or worker_name.endswith((".", " "))
    ):
        return "invalid"
    file_name = _WORKER_SETTLEMENT.format(token=_SAME_LENGTH_AS_EVERY_PERIOD_TOKEN, worker=worker_name)
    try:
        code_units = len(file_name.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return "too_long"
    return "fine" if code_units <= _WINDOWS_MAX_FILE_NAME_UTF16_UNITS else "too_long"
