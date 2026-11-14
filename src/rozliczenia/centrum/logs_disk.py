"""Logi na dysku (ADR 0017): pliki Logów Uruchomienia, plik ostatniego startu i dzienniki Wyceny w efenix w katalogu Logów
obok dziennika Centrum.

Jedyne miejsce, które zna układ tych plików, format nazwy pliku Logów, zapis i odczyt Logów i zapis oraz odczyt dziennika
Wyceny w efenix. Karty Uruchomień (``run_cards``) i start Centrum, który zamyka dzienniki Wyceny w efenix
(``run_comments.RunComments``), pytają ten moduł o Logi Uruchomienia i o pozostawione dzienniki i dostają
odpowiedź (``LogsRead``, ``LeftJournal``), a nie ścieżkę: każdy z nich decyduje sam, co z nią zrobić. Plik Logów
zapisuje tylko z Logów po strażniku reguły danych (``LogsOnDisk.write``, ``run_logs_guard.GuardedLogs``).

Nazwa pliku Logów (``name_of``) to sekunda startu w UTC, klucz procesu i identyfikator Uruchomienia, więc jedna na
Uruchomienie, a pliki jednego procesu układają się chronologicznie. Ta sama nazwa z rozszerzeniem ``.jsonl`` to dziennik
Wyceny w efenix, a bez zmian to plik w Archiwum Logów okresu. Plik, którego nazwa nie ma tej postaci (np. ``.tmp`` po
zapisie, który się nie skończył), nie jest Logami Uruchomienia.

Plik ostatniego startu, ``ostatnie-uruchomienie.json``, ma bezpieczne fakty ostatniego startu Uruchomienia z Centrum
(``StartFacts``), te same co nagłówek Logów: Centrum nadpisuje go przy każdym starcie Uruchomienia i nigdy nie usuwa, a po
swoim starcie bierze z niego ostatnie Uruchomienie (``RunCards.last``).

Plik Logów zmienia się tylko przy Diagnozie, więc widok każdego pliku (``LogsOnDisk.viewed``) zostaje w pamięci, dopóki
plik nie zmieni czasu zmiany albo rozmiaru.

Dziennik Wyceny w efenix (#845, ``Journal``) to ślad Uruchomienia na dysku taty w trakcie, który przeżywa nagłe zgaśnięcie
Centrum. Wycena w efenix trwa do półtorej godziny, a Logi Uruchomienia powstają dopiero na jej końcu i tylko pełne (ADR 0017
odrzucił niepełny plik Logów). Dziennik to osobny plik Uruchomienia w ``logs/dzienniki-wyceny/``, obok katalogu Logów, o
nazwie pliku Logów z rozszerzeniem ``.jsonl``. Silnik dopisuje do niego wpis po wpisie (``efenix_pricing.OrderJournal``):
„zaczynam zlecenie” z wierszem Pliku zbiorczego i miejscem w przebiegu przed pierwszym działaniem okna efenix przy
zleceniu, więc przed każdym zapisem w efenix, i „zlecenie skończone” zaraz po wyniku, ze śladem zlecenia jak w Logach
(``run_logs.LoggedOrder``), każdy z chwilą w UTC. Pierwsza linia pliku to start Uruchomienia, te same bezpieczne fakty co
plik ostatniego startu, które Centrum zapisuje przed nim przy każdym starcie Uruchomienia (``LogsOnDisk.started``).
Dziennik pisze tylko Wycena w efenix (``journaled``), a jego pierwsza linia trafia na dysk już przy jej starcie, zanim ruszy
jej wątek (#846), więc każda Wycena z Centrum, także zamknięta przed pierwszym zleceniem (np. gdy okno efenix czeka na
logowanie taty), ma dziennik, a procesy, które go nie piszą (Przygotowanie pliku zbiorczego, Przebieg rozliczeń,
Uporządkowanie INTERMAX), niczego nie zapisują. Każdy wpis jest na dysku (``fsync``), zanim silnik zrobi następny krok,
więc zgaśnięcie Centrum, także brak prądu, urywa najwyżej wpis w trakcie zapisu. Nieudany zapis pierwszej linii albo
wpisu to jedna linia dziennika Centrum na Uruchomienie, a Wycena biegnie dalej: ślad jest dla Maksa, a nie warunkiem pracy
taty; pierwsza linia, której nie dało się zapisać, idzie razem z następnym wpisem. Postęp w trakcie
(``Journal.progress``, #846) jest tylko z tego, co dziennik ma na dysku, więc bez jego pierwszej linii go nie ma.
Dziennik ma tylko dane Logów Uruchomienia: bez numeru zlecenia i bez danych adresowych.

Wpis „koniec Uruchomienia” z wynikiem (``Journal.end``) mówi startowi Centrum, że Uruchomienie doszło do wyniku i do
jakiego (#870, #871). Uruchomienie, którego pierwsza linia nie trafiła na dysk w żadnym zapisie, zamiast niego usuwa
dziennik, który mógł po nim zostać: postęp do niego nie poszedł, a zapis, w którym ``flush`` albo ``fsync`` rzucił po
``write``, zostawia na dysku całą pierwszą linię, a Zatrzymanie przed pierwszym zleceniem albo przy nim kończy Wycenę bez
następnego wpisu. Kiedy wpis końca idzie i kiedy dziennik znika po wyniku, decyduje ``run_comments.RunComments``, a co
start Centrum robi z dziennikiem, który zastał, ``comment_versions.close``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import threading
from typing import Annotated, Final, Generic, Literal, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.pricing_progress import OrderDone, PricingProgress
from rozliczenia.centrum.run_logs import RUN_LOGS_DIRECTORY, LoggedInterruption, LoggedOrder, RunLog, StartFacts
from rozliczenia.centrum.run_logs_guard import GuardedLogs
from rozliczenia.efenix_pricing import OrderResult
from rozliczenia.file_state import folder_entries, remove_file
from rozliczenia.wall_clock import utc_now

LAST_STARTED_FILE: Final = "ostatnie-uruchomienie.json"
_JOURNALS: Final = "dzienniki-wyceny"
_JOURNAL_SUFFIX: Final = ".jsonl"
_STARTER: Final = object()
"""Dowód ``LogsOnDisk.started``: tylko z nim ``Journal.run_started`` startuje dziennik."""
# Identyfikator Uruchomienia z Centrum (``uuid4().hex``); inny nie ma Logów, więc nie dotyka dysku.
_RUN_ID: Final = re.compile(r"[0-9a-f]{32}")
# Nazwa pliku Logów (``name_of``).
_NAME: Final = re.compile(
    rf"(?P<second>\d{{8}}T\d{{6}}Z)-(?P<process>{'|'.join(get_args(common_contract.ProcessKey))})-(?P<run_id>{_RUN_ID.pattern})\.json"
)

T = TypeVar("T")


def name_of(start: StartFacts) -> str:
    """Nazwa pliku Logów Uruchomienia ``start`` (Logi dają swój przez ``RunLog.start``):
    ``20261023T140507Z-settlement-<run_id>.json``, sekunda startu w UTC, klucz procesu i identyfikator Uruchomienia."""

    return f"{start.started_at:%Y%m%dT%H%M%SZ}-{start.process}-{start.run_id}.json"


@dataclass(frozen=True)
class _Name:
    """Nazwa pliku Logów rozłożona na części (``name_of`` w drugą stronę)."""

    second: str
    process: common_contract.ProcessKey
    run_id: str


def _parsed(name: str) -> _Name | None:
    """Części nazwy pliku Logów; ``None``: plik nie jest Logami Uruchomienia."""

    match = _NAME.fullmatch(name)
    if match is None:
        return None
    process = next(key for key in get_args(common_contract.ProcessKey) if key == match["process"])
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
    """System odmówił odczytu pliku Logów albo wylistowania katalogu Logów (``failure``, np. plik trzyma antywirus), więc
    nie wiadomo, czy Logi są i jakie: następna próba może się udać."""

    failure: OSError


LogsRead = Found | Missing | Unreadable | Refused
"""Co dysk mówi o Logach jednego Uruchomienia."""


class _StartedFile(StartFacts):
    """Plik ostatniego startu: fakty startu Uruchomienia. Schemat 2 ma tryb jako wartość ``RunMode``, a schemat 1
    jego słowo (``StoredRunMode``)."""

    schema_version: Literal[1, 2]


class _JournalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _JournalStarted(StartFacts):
    """Pierwsza linia dziennika: start Uruchomienia, te same fakty co plik ostatniego startu."""

    entry: Literal["start Uruchomienia"]


class _OrderBegun(_JournalRecord):
    """Zaczynam zlecenie z wiersza ``row``, ``place`` z ``total`` w przebiegu, przed pierwszym działaniem okna efenix."""

    at: datetime
    entry: Literal["zaczynam zlecenie"]
    row: int
    place: int
    total: int


class _OrderEnded(_JournalRecord):
    """Zlecenie skończone z wynikiem i śladem, jak w Logach Uruchomienia."""

    at: datetime
    entry: Literal["zlecenie skończone"]
    order: LoggedOrder


class _RunEnded(_JournalRecord):
    """Koniec Uruchomienia, które doszło do wyniku ``result``: ``run_process`` wrócił, a Logi z wynikiem jeszcze nie
    powstały. ``None``: wpis sprzed #910, który wyniku nie zapisywał."""

    at: datetime
    entry: Literal["koniec Uruchomienia"]
    result: RunResult | None = None


_JournalEntry = Annotated[_JournalStarted | _OrderBegun | _OrderEnded | _RunEnded, Field(discriminator="entry")]


class _JournalLine(RootModel[_JournalEntry]):
    """Jedna linia dziennika: jeden wpis w JSON."""


def _first_line(start: StartFacts) -> _JournalStarted:
    return _JournalStarted(**dict(start.start), entry="start Uruchomienia")


class Journal:
    """Dziennik bieżącej Wyceny w efenix (Uruchomienia procesu ``process``) w katalogu ``directory``
    (``efenix_pricing.OrderJournal`` w Centrum). Pierwszą linię pisze start Uruchomienia (``LogsOnDisk.started``)."""

    def __init__(self, directory: Path, log: CentrumLog, *, process: common_contract.ProcessKey) -> None:
        self.process: Final = process
        self._directory = directory
        self._log = log
        self._lock = threading.Lock()
        self._start: StartFacts | None = None
        self._header = False  # pierwszej linii nie ma jeszcze na dysku
        self._failed = False  # nieudany zapis tego Uruchomienia jest już w dzienniku Centrum
        # Wpisy tego Uruchomienia, które są już na dysku (po ``fsync``), dla postępu (``progress``).
        self._done: list[OrderDone] = []
        self._total: int | None = None
        self._current: int | None = None

    def run_started(self, start: StartFacts, proof: object) -> None:
        """Start Uruchomienia z Centrum, zanim ruszy jego wątek: Uruchomienie procesu ``process`` dostaje dziennik z
        pierwszą linią na dysku, a następne wpisy idą do niego; inne Uruchomienie dziennika nie ma. Bez dowodu
        ``LogsOnDisk.started`` (``_STARTER``) ``TypeError``, bo start bez pliku ostatniego startu gubi Urwane
        Uruchomienie."""

        if proof is not _STARTER:
            raise TypeError("Dziennik Wyceny w efenix startuje tylko LogsOnDisk.started.")
        with self._lock:
            self._done, self._total, self._current = [], None, None
            if start.process != self.process:
                self._start = None
                return
            self._start = start
            self._header, self._failed = True, False
            self._append_locked(start)

    def progress(self, run_id: str) -> PricingProgress | None:
        """Postęp Uruchomienia ``run_id`` z wpisów, które dziennik ma już na dysku, więc nigdy przed dziennikiem (#846);
        ``None``: dziennik pisze inne Uruchomienie albo żadne, albo nie ma jeszcze na dysku pierwszej linii. Wpis, którego
        nie dało się zapisać, postępu nie zmienia."""

        with self._lock:
            start = self._start
            if start is None or start.run_id != run_id or self._header:
                return None
            return PricingProgress(start, tuple(self._done), self._total, self._current)

    def begun(self, row: int, place: int, total: int) -> None:
        self._write(_OrderBegun(at=utc_now(), entry="zaczynam zlecenie", row=row, place=place, total=total))

    def ended(self, result: OrderResult) -> None:
        self._write(_OrderEnded(at=utc_now(), entry="zlecenie skończone", order=LoggedOrder.of(result)))

    def end(self, run_id: str, result: RunResult) -> None:
        """Wpis końca z wynikiem ``result`` w dzienniku Uruchomienia ``run_id``, który ma pierwszą linię na dysku. Dziennik
        bez niej (``_header``) usuwa, bo postęp do niego nie poszedł, a nieudany zapis mógł zostawić na dysku całą
        pierwszą linię (``flush`` albo ``fsync`` rzuca po ``write``), którą start wziąłby za Urwane Uruchomienie. Wpis
        końca, który się nie zapisał, zostawia dziennik bez niego. Uruchomienie bez dziennika (inny proces albo każdy
        zapis nieudany bez śladu) nie ma czego usuwać. Dziennik należy do ``run_id``, bo następne Uruchomienie startuje
        dopiero po końcu tego."""

        with self._lock:
            start, header = self._start, self._header
        if start is None or start.run_id != run_id:
            return
        if header:
            _remove(self._path(start), self._log, where="wpis")
        else:
            self._write(_RunEnded(at=utc_now(), entry="koniec Uruchomienia", result=result))

    def remove(self, run_id: str) -> None:
        """Dziennik Uruchomienia ``run_id`` znika; dziennik bez pierwszej linii na dysku (``_header``) usunął już
        ``end``."""

        with self._lock:
            start, header = self._start, self._header
        if start is None or start.run_id != run_id or header:
            return
        _remove(self._path(start), self._log, where="wpis")

    def _path(self, start: StartFacts) -> Path:
        return self._directory / Path(name_of(start)).with_suffix(_JOURNAL_SUFFIX)

    def _write(self, entry: _OrderBegun | _OrderEnded | _RunEnded) -> None:
        """Wpis ``entry`` na dysku (z pierwszą linią, gdy jej tam jeszcze nie ma); nieudany zostawia dziennik bez niego."""

        with self._lock:
            start = self._start
            if start is None:  # wpis bez startu Wyceny z Centrum nie ma dziennika, do którego by należał
                return
            if not self._append_locked(start, entry):
                return
            match entry:
                case _OrderBegun():
                    self._total, self._current = entry.total, entry.row
                case _OrderEnded(order=order):
                    self._done.append(OrderDone.of(order))
                    self._current = None
                case _RunEnded():
                    pass

    def _append_locked(self, start: StartFacts, *entries: _OrderBegun | _OrderEnded | _RunEnded) -> bool:
        """Wpisy ``entries`` dziennika ``start`` na dysku (``fsync``), z pierwszą linią przed nimi, gdy jeszcze jej tam
        nie ma; ``False``: zapis się nie udał (jedna linia dziennika Centrum na Uruchomienie)."""

        lines: list[_JournalEntry] = [_first_line(start), *entries] if self._header else list(entries)
        path = self._path(start)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as journal:
                journal.write("".join(_JournalLine(line).model_dump_json() + "\n" for line in lines))
                journal.flush()
                os.fsync(journal.fileno())
        except OSError as failure:
            if not self._failed:
                self._log.pricing_journal_unavailable(failure, where="wpis")
                self._failed = True
            return False
        self._header = False
        return True


@dataclass(frozen=True)
class EndEntry:
    """Wpis końca dziennika: Uruchomienie doszło do wyniku ``result`` (``None``: wpis sprzed #910, bez wyniku)."""

    result: RunResult | None


@dataclass(frozen=True)
class JournalRead:
    """Dziennik odczytany przy starcie Centrum: start, zlecenia skończone, zlecenie zaczęte bez wyniku, ostatni wpis,
    liczba zleceń przebiegu z ostatniego „zaczynam zlecenie” (``None`` przed pierwszym) i wpis końca (``end``; ``None``:
    Uruchomienie nie doszło do wyniku albo jego wpis końca się nie zapisał)."""

    started: StartFacts
    orders: list[LoggedOrder]
    interruption: LoggedInterruption
    last_at: datetime
    total: int | None
    end: EndEntry | None

    @property
    def progress(self) -> PricingProgress:
        """To, co dziennik ma, w kształcie postępu: zlecenia skończone, ile wszystkich i zlecenie zaczęte bez wyniku."""

        done = tuple(OrderDone.of(order) for order in self.orders)
        return PricingProgress(self.started, done, self.total, self.interruption.row)


class JournalKey:
    """Jeden dziennik na dysku, który zostawiła poprzednia praca Centrum; ścieżkę zna tylko ``LogsOnDisk``, który dał
    klucz (``left_behind``)."""

    __slots__ = ()


@dataclass(frozen=True)
class LeftJournal:
    """Dziennik, który zostawiła poprzednia praca Centrum, odczytany razem z Logami jego Uruchomienia: ``journal``
    ``None`` to dziennik bez pierwszej linii, a wtedy Logów nikt nie czyta (``Missing``)."""

    key: JournalKey
    journal: JournalRead | None
    logs: LogsRead


def _read_journal(path: Path) -> JournalRead | None:
    """Dziennik z pliku ``path``; ``None`` bez pierwszej linii. Linie, których nie da się odczytać, liczy w ``omitted``."""

    started: _JournalStarted | None = None
    orders: list[LoggedOrder] = []
    last: _OrderBegun | _OrderEnded | None = None
    total: int | None = None
    end: _RunEnded | None = None
    omitted = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = _JournalLine.model_validate_json(line).root
        except ValidationError:
            omitted += 1
            continue
        match entry:
            case _JournalStarted():
                if started is None:
                    started = entry
            case _OrderBegun():
                last, total = entry, entry.total
            case _OrderEnded():
                orders.append(entry.order)
                last = entry
            case _RunEnded():
                end = entry
    if started is None:
        return None
    begun = last if isinstance(last, _OrderBegun) else None
    interruption = LoggedInterruption(
        row=None if begun is None else begun.row,
        place=None if begun is None else begun.place,
        total=None if begun is None else begun.total,
        omitted=omitted,
    )
    return JournalRead(
        started.start,
        orders,
        interruption,
        started.started_at if last is None else last.at,
        total,
        None if end is None else EndEntry(end.result),
    )


def _remove(path: Path, log: CentrumLog, *, where: Literal["wpis", "start"]) -> None:
    """Usuwa dziennik ``path``; ``OSError`` zostawia go z linią dziennika Centrum. Dziennika nie ma także wtedy, gdy na
    miejscu katalogu dzienników stoi plik (``NotADirectoryError``, a w Windows ``FileNotFoundError``)."""

    try:
        remove_file(path)
    except OSError as failure:
        log.pricing_journal_unavailable(failure, where=where)


class LogsOnDisk:
    """Pliki Logów Uruchomienia, plik ostatniego startu i dzienniki Wyceny w efenix w katalogu Logów ``log.directory``;
    dziennik pisze Uruchomienie procesu ``journaled`` (``journal``)."""

    def __init__(self, log: CentrumLog, *, journaled: common_contract.ProcessKey) -> None:
        self._logs = log.directory / RUN_LOGS_DIRECTORY
        self._last_started = log.directory / LAST_STARTED_FILE
        self._journals = log.directory / _JOURNALS
        self._log = log
        self._journal = Journal(self._journals, log, process=journaled)
        self._left: dict[JournalKey, Path] = {}

    @property
    def journal(self) -> Journal:
        return self._journal

    def started(self, start: StartFacts) -> None:
        """Start Uruchomienia, zanim ruszy jego wątek: pierwsza linia dziennika (``Journal``; nieudana to linia dziennika
        Centrum), potem plik ostatniego startu z jego faktami, nadpisany atomowo; ``OSError``: pliku ostatniego startu nie
        udało się zapisać."""

        self.journal.run_started(start, _STARTER)
        started = _StartedFile(**dict(start.start), schema_version=2)
        replace_atomically(self._last_started, started.model_dump_json(indent=2) + "\n")

    def write(self, logs: GuardedLogs) -> None:
        """Plik Logów ``logs`` (nowy albo nadpisany atomowo) z bajtami pliku w Archiwum Logów okresu
        (``ArchiveFile.packed``): ``text`` w UTF-8 bez zamiany ``\n`` na ``\r\n``, którą robi zapis tekstowy na Windows,
        więc ``gunzip`` pliku z Archiwum daje plik z komputera taty bajt w bajt. Logi innego typu niż ``GuardedLogs`` (np.
        sprzed strażnika przez ``Any``) rzucają ``TypeError`` (``run_logs_guard._MINTED``); ``OSError``: pliku nie udało się
        zapisać."""

        if not isinstance(logs, GuardedLogs):
            raise TypeError("Plik Logów bierze tylko Logi po strażniku z guard_logs.")
        replace_atomically(self._logs / name_of(logs.record.start), logs.text, newline="")

    def last_start(self) -> StartFacts | None:
        """Ostatni start Uruchomienia przed tą pracą Centrum; ``None``: żadnego albo pliku nie da się odczytać."""

        try:
            started = _StartedFile.model_validate_json(self._last_started.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return started.start

    def logs(self, run_id: str) -> LogsRead:
        """Logi Uruchomienia ``run_id``; identyfikator, którego Centrum nie nadaje, nie ma pliku Logów (``Missing``) bez
        zaglądania na dysk."""

        if _RUN_ID.fullmatch(run_id) is None:
            return Missing()
        try:
            names = _names(self._logs)
        except OSError as failure:
            return Refused(failure)
        name = next((name for name, parsed in names if parsed.run_id == run_id), None)
        return Missing() if name is None else _read_logs(self._logs / name)

    def newest(self, process: common_contract.ProcessKey) -> RunLog | None:
        """Najnowsze Logi procesu ``process``: z plików najnowszej sekundy startu w nazwie te z późniejszym startem w
        Logach. ``None``: żadnych albo żadnych czytelnych w tej sekundzie, bo starsze nie są najnowszymi."""

        try:
            listed = _names(self._logs)
        except OSError:
            return None
        names = sorted((pair for pair in listed if pair[1].process == process), key=lambda pair: pair[0])
        if not names:
            return None
        second = names[-1][1].second
        read = [_read_logs(self._logs / name) for name, parsed in names if parsed.second == second]
        found = [logs.logs for logs in read if isinstance(logs, Found)]
        return max(found, key=lambda record: record.started_at) if found else None

    def viewed(self, view: Callable[[RunLog], T | None]) -> ViewedLogs[T]:
        """``view`` każdych czytelnych Logów procesu, który poda wołający, liczony raz na wersję pliku."""

        return ViewedLogs(self._logs, view)

    def left_behind(self) -> Iterator[LeftJournal]:
        """Przy starcie Centrum: każdy dziennik, który zostawiła poprzednia praca Centrum, w kolejności nazw, odczytany
        razem z Logami jego Uruchomienia (``logs``), jeden po drugim, gdy wołający bierze następny. Dziennika, którego nie
        da się wylistować albo odczytać, nie ma tu (linia dziennika Centrum), więc zostaje następnemu startowi."""

        try:
            paths = sorted(self._journals.glob(f"*{_JOURNAL_SUFFIX}"))
        except OSError as failure:
            self._log.pricing_journal_unavailable(failure, where="start")
            return
        for path in paths:
            try:
                read = _read_journal(path)
            except OSError as failure:
                self._log.pricing_journal_unavailable(failure, where="start")
                continue
            logs = Missing() if read is None else self.logs(read.started.run_id)
            key = JournalKey()
            self._left[key] = path
            yield LeftJournal(key, read, logs)

    def remove_journal(self, key: JournalKey) -> None:
        """Usuwa dziennik ``key`` z ``left_behind``, który zostawiła poprzednia praca Centrum; ``OSError`` zostawia go
        z linią dziennika Centrum."""

        _remove(self._left.pop(key), self._log, where="start")


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

    def of(self, process: common_contract.ProcessKey) -> list[T]:
        """Widoki Logów procesu ``process`` od najnowszych; pliki, których nie da się odczytać, pomija, a bez wylistowania
        katalogu Logów nie ma żadnych."""

        try:
            listed = _names(self._logs)
        except OSError:
            return []
        names = sorted((name for name, parsed in listed if parsed.process == process), reverse=True)
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
    """Pliki Logów Uruchomienia w katalogu ``logs`` z częściami nazwy; bez katalogu żadnych. ``OSError``: katalog jest,
    ale system nie daje go wylistować, więc nie wiadomo, jakie pliki w nim są."""

    entries = folder_entries(logs) or []
    return [(entry.name, parsed) for entry in entries if (parsed := _parsed(entry.name)) is not None]


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
