"""Logi na dysku (ADR 0017): pliki Logów Uruchomienia i plik ostatniego startu w katalogu Logów obok dziennika Centrum.

Jedyne miejsce, które zna układ tych plików, format nazwy pliku Logów i jego odczyt. Karty Uruchomień (``run_cards``) i
start Centrum, który zamyka dzienniki Wyceny w efenix (``pricing_journal.InterruptedPricings``), pytają ten moduł o Logi
Uruchomienia i dostają jedną odpowiedź (``LogsRead``), a nie ścieżkę: każdy z nich decyduje sam, co z nią zrobić.

Nazwa pliku Logów (``name_of``) to sekunda startu w UTC, klucz procesu i identyfikator Uruchomienia, więc jedna na
Uruchomienie, a pliki jednego procesu układają się chronologicznie. Ta sama nazwa z rozszerzeniem ``.jsonl`` to dziennik
Wyceny w efenix, a bez zmian to plik w Archiwum Logów okresu. Plik, którego nazwa nie ma tej postaci (np. ``.tmp`` po
zapisie, który się nie skończył), nie jest Logami Uruchomienia.

Plik ostatniego startu, ``ostatnie-uruchomienie.json``, ma bezpieczne fakty ostatniego startu Uruchomienia z Centrum
(``StartFacts``), te same co nagłówek Logów: Centrum nadpisuje go przy każdym starcie Uruchomienia i nigdy nie usuwa, a po
swoim starcie bierze z niego ostatnie Uruchomienie (``RunCards.last``).

Plik Logów zmienia się tylko przy Diagnozie, więc widok każdego pliku (``LogsOnDisk.viewed``) zostaje w pamięci, dopóki
plik nie zmieni czasu zmiany albo rozmiaru.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import threading
from typing import Final, Generic, Literal, TypeVar, get_args

from pydantic import BaseModel, ConfigDict

from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.run_logs import RUN_LOGS_DIRECTORY, RunLog, StartedFacts, StartFacts, logs_file_name

LAST_STARTED_FILE: Final = "ostatnie-uruchomienie.json"
# Nazwa pliku Logów (``name_of``); identyfikator Uruchomienia z Centrum to ``uuid4().hex``.
_NAME: Final = re.compile(
    rf"(?P<second>\d{{8}}T\d{{6}}Z)-(?P<process>{'|'.join(get_args(contract.ProcessKey))})-(?P<run_id>[0-9a-f]{{32}})\.json"
)

T = TypeVar("T")


def name_of(start: StartedFacts) -> str:
    """Nazwa pliku Logów Uruchomienia ``start``: ``20261023T140507Z-settlement-<run_id>.json``."""

    return logs_file_name(start.started_at, start.process, start.run_id)


@dataclass(frozen=True)
class _Name:
    """Nazwa pliku Logów rozłożona na części (``name_of`` w drugą stronę)."""

    second: str
    process: contract.ProcessKey
    run_id: str


def _parsed(name: str) -> _Name | None:
    """Części nazwy pliku Logów; ``None``: plik nie jest Logami Uruchomienia."""

    match = _NAME.fullmatch(name)
    if match is None:
        return None
    process = next(key for key in get_args(contract.ProcessKey) if key == match["process"])
    return _Name(second=match["second"], process=process, run_id=match["run_id"])


@dataclass(frozen=True)
class Found:
    """Czytelny plik Logów Uruchomienia."""

    logs: RunLog


@dataclass(frozen=True)
class Missing:
    """Uruchomienie nie ma pliku Logów (albo nie ma katalogu Logów)."""


@dataclass(frozen=True)
class Unreadable:
    """Plik Logów jest, ale jego treść nie jest Logami (zły JSON, schemat, kodowanie): Uruchomienie miało wynik, którego
    nie znamy."""


@dataclass(frozen=True)
class Refused:
    """Plik Logów jest, ale system odmówił jego odczytu (``failure``, np. plik trzyma antywirus): następna próba może się
    udać."""

    failure: OSError


LogsRead = Found | Missing | Unreadable | Refused
"""Co dysk mówi o Logach jednego Uruchomienia."""


class _StartedFile(BaseModel):
    """Plik ostatniego startu (schemat 1): te same fakty co nagłówek Logów Uruchomienia."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime


class LogsOnDisk:
    """Pliki Logów Uruchomienia i plik ostatniego startu w katalogu Logów ``directory`` (``log.directory``)."""

    def __init__(self, directory: Path) -> None:
        self._logs = directory / RUN_LOGS_DIRECTORY
        self._last_started = directory / LAST_STARTED_FILE

    def started(self, start: StartFacts) -> None:
        """Start Uruchomienia: plik ostatniego startu z jego faktami, nadpisany atomowo; ``OSError``: pliku nie udało się
        zapisać."""

        started = _StartedFile(
            schema_version=1,
            run_id=start.run_id,
            process=start.process,
            mode=start.mode,
            period=start.period,
            started_at=start.started_at,
        )
        replace_atomically(self._last_started, started.model_dump_json(indent=2) + "\n")

    def last_start(self) -> StartFacts | None:
        """Ostatni start Uruchomienia przed tą pracą Centrum; ``None``: żadnego albo pliku nie da się odczytać."""

        try:
            started = _StartedFile.model_validate_json(self._last_started.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return StartFacts(
            run_id=started.run_id,
            process=started.process,
            mode=started.mode,
            period=started.period,
            started_at=started.started_at,
        )

    def logs(self, run_id: str) -> LogsRead:
        """Logi Uruchomienia ``run_id``; identyfikator, którego Centrum nie nadaje, nie ma pliku Logów (``Missing``)."""

        name = next((name for name, parsed in _names(self._logs) if parsed.run_id == run_id), None)
        return Missing() if name is None else _read_logs(self._logs / name)

    def newest(self, process: contract.ProcessKey) -> RunLog | None:
        """Najnowsze Logi procesu ``process``: z plików najnowszej sekundy startu w nazwie te z późniejszym startem w
        Logach. ``None``: żadnych albo żadnych czytelnych w tej sekundzie, bo starsze nie są najnowszymi."""

        names = sorted((pair for pair in _names(self._logs) if pair[1].process == process), key=lambda pair: pair[0])
        if not names:
            return None
        second = names[-1][1].second
        read = [_read_logs(self._logs / name) for name, parsed in names if parsed.second == second]
        found = [logs.logs for logs in read if isinstance(logs, Found)]
        return max(found, key=lambda record: record.started_at) if found else None

    def viewed(self, view: Callable[[RunLog], T | None]) -> ViewedLogs[T]:
        """``view`` każdych czytelnych Logów procesu, który poda wołający, liczony raz na wersję pliku."""

        return ViewedLogs(self._logs, view)


class ViewedLogs(Generic[T]):
    """Widok (``view``) Logów każdego Uruchomienia jednego procesu z katalogu Logów ``logs``; ``None`` z widoku pomija
    Logi."""

    def __init__(self, logs: Path, view: Callable[[RunLog], T | None]) -> None:
        self._logs = logs
        self._view = view
        self._lock = threading.Lock()
        # Widok pliku Logów po nazwie, z jego czasem zmiany i rozmiarem; ``None``: pliku nie da się odczytać albo widok
        # go pomija.
        self._known: dict[str, tuple[tuple[int, int], T | None]] = {}

    def of(self, process: contract.ProcessKey) -> list[T]:
        """Widoki Logów procesu ``process`` od najnowszych; pliki, których nie da się odczytać, pomija."""

        names = sorted((name for name, parsed in _names(self._logs) if parsed.process == process), reverse=True)
        with self._lock:
            viewed = [self._of(self._logs / name) for name in names]
        return [view for view in viewed if view is not None]

    def _of(self, path: Path) -> T | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        version = (stat.st_mtime_ns, stat.st_size)
        known = self._known.get(path.name)
        if known is not None and known[0] == version:
            return known[1]
        read = _read_logs(path)
        view = self._view(read.logs) if isinstance(read, Found) else None
        self._known[path.name] = (version, view)
        return view


def _names(logs: Path) -> list[tuple[str, _Name]]:
    """Pliki Logów Uruchomienia w katalogu ``logs`` z częściami nazwy; bez katalogu żadnych."""

    try:
        names = [path.name for path in logs.iterdir()]
    except OSError:
        return []
    return [(name, parsed) for name in names if (parsed := _parsed(name)) is not None]


def _read_logs(path: Path) -> LogsRead:
    """Logi z pliku ``path``, który był w katalogu Logów: czytelne, nieczytelne albo odmowa odczytu (także gdy plik
    zniknął po wylistowaniu katalogu)."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as failure:
        return Refused(failure)
    except ValueError:  # bajty spoza UTF-8
        return Unreadable()
    try:
        return Found(RunLog.model_validate_json(text))
    except ValueError:
        return Unreadable()
