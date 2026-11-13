"""Folder okresu: nazwy i ścieżki plików okresu, okres ze ścieżki Pliku zbiorczego i Status okresu (GLOSSARY).

To jedyne miejsce, które zna nazwy w Folderze okresu: Rozliczenia
wewnętrznego, Pliku zbiorczego, Folderu rozliczeń pracowników i Rozliczenia
pracownika. ``PeriodFolder`` powstaje tylko z folderu okresów i sprawdzonego
``SettlementPeriod`` albo ze ścieżki Pliku zbiorczego, którą moduł sam
sprawdza, więc niesprawdzony token nie trafia do nazw. ``PeriodFolderError``
mówi, co jest nie tak ze ścieżką, a Komunikat pisze z tego katalog procesu.
Moduł sprawdza też, czy nazwa Wykonawcy może być nazwą pliku
(``check_worker_name``), bo zna format nazwy Rozliczenia pracownika.

Status okresu wynika z tej samej obserwacji plików co flagi istnienia
(``PeriodFolder.observe``), więc nie może się z nimi rozjechać; treści
skoroszytów się nie czyta. Status nie zastępuje Gotowości.

Folder okresów ma jeden z dwóch układów. W płaskim Foldery okresu leżą w nim
bezpośrednio, a brakujący Folder okresu powstaje przy zapisie. W układzie
folderów taty leżą w ``Rozliczenia {rok}\\{miesiąc}\\INEA``; miesiąc to cykl
rozliczeniowy taty, nie kalendarz, więc Folder okresu jest szukany, a nie
wyliczany (``locate_period_folder``). Tata zakłada go sam; brak albo ten sam
okres w dwóch miesiącach to ``PeriodFolderLookupError``. Folder okresów
wskazany wewnątrz ``Rozliczenia {rok}`` (np. ``INEA`` jednego miesiąca) to ten
sam układ liczony od folderu nad ``Rozliczenia {rok}`` (``layout_root``), więc brakujący Folder
okresu nie powstaje w złym miesiącu.

Folder, którego nie da się odczytać (brak dostępu, OneDrive nie działa), to
``PeriodFolderInaccessible`` z tym folderem, a nie wyjątek systemu plików.
Brak folderu okresów (``PeriodFolders.periods_directory_missing``) i jego
niedostępność rozstrzyga to samo listowanie, więc nie zależą od wersji Pythona.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .settlement_period import PERIOD_TOKEN_PATTERN, UNKNOWN_PERIOD, SettlementPeriod, parse_period_token

from .file_state import entry_kind, folder_entries, path_state

# ``{token}`` to token okresu, ``{worker}`` nazwa Wykonawcy.
_INTERNAL_SETTLEMENT = "Rozliczenie wew. {token}.xlsx"
_COLLECTIVE_FILE = "Rozliczenie {token} - zbiorcze.xlsx"
_WORKER_SETTLEMENTS = "Rozliczenie pracowników {token}"
_WORKER_SETTLEMENT = "Rozliczenie {token} - {worker}.xlsx"

_INTERNAL_SETTLEMENT_MARK = _INTERNAL_SETTLEMENT.partition(" {token}")[0]  # Rozliczenie wew. dowolnego okresu
_COLLECTIVE_FILE_PREFIX, _, _COLLECTIVE_FILE_SUFFIX = _COLLECTIVE_FILE.partition("{token}")
_COLLECTIVE_FILE_NAME = re.compile(
    rf"{re.escape(_COLLECTIVE_FILE_PREFIX)}(?P<token>{PERIOD_TOKEN_PATTERN}){re.escape(_COLLECTIVE_FILE_SUFFIX)}"
)

# Układ folderów taty: Rozliczenia {rok}\{miesiąc}\INEA\{token}.
_YEAR_FOLDER = re.compile(r"Rozliczenia \d{4}")
_MONTH_PERIODS_FOLDER = "INEA"

PeriodStatus = Literal["no_period_files", "collective_file_prepared", "worker_settlements_ready"]
PeriodPlace = Literal["internal_settlement", "collective_file", "period_folder", "worker_settlements_folder"]
"""Folder okresu albo jeden z jego plików, które tata otwiera i które Diagnoza wylicza."""
WorkerNameCheck = Literal["fine", "invalid", "too_long"]
_FORBIDDEN_IN_FILE_NAME = frozenset('<>:"/\\|?*')
_MAX_FILE_NAME_CODE_UNITS = 255  # Windows liczy nazwę pliku w jednostkach UTF-16
_ANY_TOKEN = "00_00_00_0000"  # każdy token okresu ma tę długość


@dataclass(frozen=True)
class NotPeriodToken:
    """Token ``token`` z nazwy Pliku zbiorczego nie jest okresem od wtorku do poniedziałku."""

    token: str


@dataclass(frozen=True)
class FolderNotNamedAfterPeriod:
    """Folder pliku nie nazywa się jak okres ``token`` z nazwy pliku."""

    token: str


CollectiveFileProblem = (
    Literal["internal_settlement", "not_collective_file_name"] | NotPeriodToken | FolderNotNamedAfterPeriod
)
"""Wybrane Rozliczenie wew. (``internal_settlement``), nazwa inna niż nazwa Pliku zbiorczego
(``not_collective_file_name``, jej wzór daje ``collective_file_name_with``), token, który nie jest okresem
(``NotPeriodToken``), albo folder nazwany inaczej niż okres (``FolderNotNamedAfterPeriod``)."""


class PeriodFolderError(Exception):
    """Ścieżka nie jest Plikiem zbiorczym w swoim Folderze okresu; ``problem`` mówi dlaczego, bez zdania dla taty."""

    def __init__(self, problem: CollectiveFileProblem) -> None:
        self.problem: CollectiveFileProblem = problem


class PeriodFolderLookupError(Exception):
    """W układzie folderów taty Folderu okresu nie ma (``locations`` puste) albo jest w kilku miesiącach.

    ``locations`` to foldery ``INEA`` z Folderem okresu, w kolejności lat i miesięcy.
    """

    def __init__(self, periods_directory: Path, period: SettlementPeriod, locations: tuple[Path, ...]) -> None:
        super().__init__(period.token)
        self.periods_directory = periods_directory
        self.period = period
        self.locations = locations


class PeriodFolderInaccessible(Exception):
    """Folderu ``folder`` (folderu okresów, folderu miesiąca albo Folderu okresu) nie da się odczytać."""

    def __init__(self, folder: Path) -> None:
        super().__init__(folder.name)
        self.folder = folder


@contextmanager
def reading(folder: Path) -> Iterator[None]:
    """Odczyt zawartości ``folder``; błąd systemu plików staje się ``PeriodFolderInaccessible``."""

    try:
        yield
    except OSError as error:
        raise PeriodFolderInaccessible(folder) from error


@dataclass(frozen=True)
class PeriodFolder:
    """Folder okresu ``period`` w folderze okresów i ścieżki jego plików, które mogą jeszcze nie istnieć."""

    periods_directory: Path
    period: SettlementPeriod

    @classmethod
    def from_collective_file(cls, path: Path) -> PeriodFolder:
        """Folder okresu Pliku zbiorczego ``path``, czyli jego folder nadrzędny.

        Sprawdza dokładną nazwę pliku, okres od wtorku do poniedziałku i to, że
        folder nadrzędny nazywa się jak okres; inaczej ``PeriodFolderError``.
        """

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
        """Folder rozliczeń pracowników."""

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
        """Jeden odczyt plików Folderu okresu, który może nie istnieć: listowanie jego i Folderu rozliczeń pracowników."""

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
            worker_settlement_count=len(self.worker_settlement_files()) if has_worker_settlements else 0,
        )

    def worker_settlement_files(self) -> tuple[Path, ...]:
        """Rozliczenia pracownika w Folderze rozliczeń pracowników, po nazwie; bez tego folderu pusta krotka.

        Pomija pliki blokady Excela, pliki ukryte, foldery i Wzorzec rozliczenia pracownika bez nazwy wykonawcy.
        """

        prefix, suffix = _WORKER_SETTLEMENT.format(token=self.period.token, worker="\0").split("\0")
        return tuple(
            sorted(
                self.worker_settlements / entry.name
                for entry in _listing(self.worker_settlements) or ()
                if entry.name.startswith(prefix)
                and entry.name.endswith(suffix)
                and len(entry.name) > len(prefix) + len(suffix)
                and entry_kind(entry) == "file"
            )
        )


def _listing(directory: Path) -> list[os.DirEntry[str]] | None:
    """Wpisy folderu z jednego listowania; ``None``, gdy folderu nie ma, ``PeriodFolderInaccessible``, gdy jest niedostępny.

    Folder okresów taty leży w OneDrive, gdzie każdy osobny ``stat`` otwiera
    plik, a listowanie od razu podaje, czy wpis jest plikiem czy folderem.
    """

    with reading(directory):
        return folder_entries(directory)


def _exists(listed: Mapping[str, os.DirEntry[str]], path: Path, *, directory: bool) -> bool:
    """Czy ``path`` jest folderem (``directory``) albo plikiem, według listowania folderu nad nim.

    Nazwy spoza listowania pyta system plików: Windows i macOS nie rozróżniają
    wielkości liter, a macOS postaci Unicode, więc plik może mieć inną nazwę.
    """

    kind = "folder" if directory else "file"
    entry = listed.get(path.name)
    if entry is not None:
        return entry_kind(entry) == kind
    state = path_state(path)
    if state == "inaccessible":
        raise PeriodFolderInaccessible(path.parent)
    return state == kind


def collective_period_token(path: Path) -> str:
    """Token okresu Pliku zbiorczego ``path`` do rekordu metryk Uruchomienia; ``nieznany``, gdy ścieżka nie jest
    Plikiem zbiorczym w swoim Folderze okresu (proces sam zatrzymuje się wtedy Komunikatem)."""

    try:
        return PeriodFolder.from_collective_file(path.expanduser().resolve()).period.token
    except PeriodFolderError:
        return UNKNOWN_PERIOD


def collective_file_name(period: SettlementPeriod) -> str:
    """Nazwa Pliku zbiorczego okresu; nie zależy od folderu okresów."""

    return collective_file_name_with(period.token)


def collective_file_name_with(token: str) -> str:
    """Nazwa Pliku zbiorczego z ``token`` w miejscu tokenu okresu, np. ze wzorem tokenu w Komunikacie."""

    return _COLLECTIVE_FILE.format(token=token)


def worker_settlements_name_with(token: str) -> str:
    """Nazwa Folderu rozliczeń pracowników z ``token`` w miejscu tokenu okresu, także z tokenem, który nie jest okresem."""

    return _WORKER_SETTLEMENTS.format(token=token)


@dataclass(frozen=True)
class PeriodFolderObservation:
    """Pliki Folderu okresu w chwili jednego odczytu i Status okresu wyliczony z tych samych flag."""

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


def period_status_label(status: PeriodStatus) -> str:
    """Nazwa Statusu okresu z GLOSSARY."""

    # Status okresu bez nazwy mypy zgłasza jako brakujący return.
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
    """Foldery ``INEA`` miesięcy w ``Rozliczenia {rok}`` spośród wpisów ``entries`` jednego folderu, w kolejności lat
    i miesięcy.

    Puste w układzie płaskim. Folder miesiąca bez dostępu to ``PeriodFolderInaccessible`` z tym folderem.
    """

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
    """Folder, od którego liczy się układ folderów okresów, i jego foldery ``INEA`` miesięcy; ``entries`` to wpisy
    folderu okresów.

    Folder okresów wewnątrz ``Rozliczenia {rok}`` (np. ``INEA`` jednego miesiąca)
    oznacza folder nad ``Rozliczenia {rok}``, gdy ten ma foldery ``INEA``
    miesięcy. Inaczej to sam folder okresów.
    """

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
    """Folder, od którego liczy się układ folderów okresów (``PeriodFolders.layout_root``); ``by_years``: układ
    folderów taty z folderami ``INEA`` miesięcy w ``Rozliczenia {rok}``, inaczej układ płaski."""

    directory: Path
    by_years: bool


def layout_root(path: Path) -> LayoutRoot:
    """Folder, od którego Centrum liczy układ folderów okresów wskazanych w ``path``, tym samym rachunkiem co
    ``scan_period_folders``: dla tygodnia, ``INEA`` albo miesiąca w ``Rozliczenia {rok}`` to folder nad nim
    (``Załączniki``), w układzie płaskim sam ``path``.

    Folder, którego nie ma, liczy się od folderów nad nim, więc tydzień przeniesiony przez tatę dalej prowadzi do
    ``Załączniki``. Folder bez dostępu to ``PeriodFolderInaccessible``.
    """

    directory, month_folders = _layout(path, _listing(path) or ())
    return LayoutRoot(directory, bool(month_folders))


def month_folder_label(periods_directory: Path, month_periods_folder: Path) -> str:
    """Folder ``INEA`` miesiąca względem folderu okresów, np. ``Rozliczenia 2026\\06_Czerwiec_2026\\INEA``.

    Sam folder okresów, gdy Folder okresu leży też bezpośrednio w nim, to jego nazwa.
    """

    return "\\".join(month_periods_folder.relative_to(periods_directory).parts) or periods_directory.name


@dataclass(frozen=True)
class PeriodFolders:
    """Foldery okresu z jednego listowania układu folderu okresów ``periods_directory``.

    ``layout_root`` to folder, od którego liczy się układ (``_layout``).
    ``locations`` podaje dla okresu foldery, w których leży jego Folder okresu:
    najpierw ``layout_root``, potem foldery ``INEA`` w kolejności lat i miesięcy.
    ``periods_directory_missing``: folderu okresów nie ma (także gdy na jego
    miejscu jest plik).
    """

    periods_directory: Path
    layout_root: Path
    has_month_folders: bool
    locations: Mapping[SettlementPeriod, tuple[Path, ...]]
    periods_directory_missing: bool

    def locate(self, period: SettlementPeriod) -> PeriodFolder:
        """Folder okresu ``period``.

        W układzie płaskim Folder okresu może jeszcze nie istnieć. W układzie
        folderów taty musi istnieć dokładnie w jednym miejscu; inaczej
        ``PeriodFolderLookupError`` z folderem okresów ``layout_root``.
        """

        found = self.locations.get(period, ())
        if len(found) == 1:
            return PeriodFolder(found[0], period)
        if found or self.has_month_folders:
            raise PeriodFolderLookupError(self.layout_root, period, found)
        return PeriodFolder(self.layout_root, period)

    def found(self) -> list[PeriodFolder]:
        """Istniejące Foldery okresu; okres z Folderem okresu w kilku miejscach występuje raz, w pierwszym z nich."""

        return [PeriodFolder(parents[0], period) for period, parents in self.locations.items()]


def scan_period_folders(periods_directory: Path) -> PeriodFolders:
    """Foldery okresu w folderze okresów: tylko foldery, których nazwa jest tokenem okresu.

    Brak folderu okresów rozstrzyga jego pierwsze listowanie, zanim cokolwiek innego jest listowane, więc folder bez
    dostępu gdzie indziej w ``Rozliczenia {rok}`` nie zmienia braku w niedostępność.
    """

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
    """Folder okresu ``period`` w istniejącym folderze okresów (``PeriodFolders.locate``)."""

    return scan_period_folders(periods_directory).locate(period)


def check_worker_name(worker_name: str) -> WorkerNameCheck:
    """Czy nazwa Wykonawcy może być nazwą pliku Rozliczenia pracownika.

    ``invalid``: znak niedozwolony w Windows, znak sterujący albo kropka lub
    spacja na końcu. ``too_long``: pełna nazwa Rozliczenia pracownika ma ponad
    255 jednostek UTF-16 albo nie da się jej zapisać w UTF-16.
    """

    if (
        any(character in _FORBIDDEN_IN_FILE_NAME or ord(character) < 32 for character in worker_name)
        or worker_name.endswith((".", " "))
    ):
        return "invalid"
    file_name = _WORKER_SETTLEMENT.format(token=_ANY_TOKEN, worker=worker_name)
    try:
        code_units = len(file_name.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return "too_long"
    return "fine" if code_units <= _MAX_FILE_NAME_CODE_UNITS else "too_long"
