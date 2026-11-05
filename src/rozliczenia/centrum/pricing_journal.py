"""Dziennik Wyceny w efenix (#845): ślad Uruchomienia na dysku taty w trakcie, który przeżywa nagłe zgaśnięcie Centrum.

Wycena w efenix trwa do półtorej godziny, a Logi Uruchomienia powstają dopiero na jej końcu i tylko pełne (ADR 0017
odrzucił niepełny plik Logów). Dziennik to osobny plik Uruchomienia w ``logs/dzienniki-wyceny/``, obok katalogu Logów, o
nazwie pliku Logów z rozszerzeniem ``.jsonl``. Silnik dopisuje do niego wpis po wpisie (``efenix_pricing.OrderJournal``):
„zaczynam zlecenie” z wierszem Pliku zbiorczego i miejscem w przebiegu przed pierwszym działaniem okna efenix przy
zleceniu, więc przed każdym zapisem w efenix, i „zlecenie skończone” zaraz po wyniku, ze śladem zlecenia jak w Logach
(``run_logs.LoggedOrder``), każdy z chwilą w UTC. Pierwsza linia pliku to start Uruchomienia, te same bezpieczne fakty co
plik ostatniego startu, które Centrum podaje dziennikowi przy każdym starcie Uruchomienia (``PricingJournal.run_started``).
Dziennik pisze tylko Wycena w efenix (``process``), a jego pierwsza linia trafia na dysk już przy jej starcie, zanim ruszy
jej wątek (#846), więc każda Wycena z Centrum, także zamknięta przed pierwszym zleceniem (np. gdy okno efenix czeka na
logowanie taty), ma dziennik, a procesy, które go nie piszą (Przygotowanie pliku zbiorczego, Przebieg rozliczeń,
Uporządkowanie INTERMAX), niczego nie zapisują. Każdy wpis jest na dysku (``fsync``), zanim silnik zrobi następny krok,
więc zgaśnięcie Centrum, także brak prądu, urywa najwyżej wpis w trakcie zapisu. Nieudany zapis pierwszej linii albo
wpisu to jedna linia dziennika Centrum na Uruchomienie, a Wycena biegnie dalej: ślad jest dla Maksa, a nie warunkiem pracy
taty; pierwsza linia, której nie dało się zapisać, idzie razem z następnym wpisem. Postęp w trakcie
(``PricingJournal.progress``, #846) jest tylko z tego, co dziennik ma na dysku, więc bez jego pierwszej linii go nie ma.
Dziennik ma tylko dane Logów Uruchomienia: bez numeru zlecenia i bez danych adresowych.

Uruchomienie, które doszło do wyniku (``run_process`` wrócił, z wierszem Historii albo bez niego), dopisuje „koniec
Uruchomienia” (``PricingJournal.run_ended``): to pierwsze działanie po wyniku, więc wpis jest na dysku, zanim powstaną
Logi z wynikiem i zanim pójdą do Skrzynki. Dziennik sam mówi więc startowi Centrum, czy jego Uruchomienie doszło do
wyniku, a start nie zgaduje tego z Historii, którą pisze kto inny i którą start może źle odczytać (#870, #871). Wpis
końca, który się nie zapisał, usuwa dziennik: Uruchomienie ma wynik, więc jego dziennik nie jest już potrzebny. Tak samo
Uruchomienie, którego pierwsza linia nie trafiła na dysk w żadnym zapisie, usuwa dziennik, który mógł po nim zostać:
zapis, w którym ``flush`` albo ``fsync`` rzucił po ``write``, zostawia na dysku całą pierwszą linię, a Zatrzymanie przed
pierwszym zleceniem albo przy nim kończy Wycenę bez następnego wpisu.
Zgaśnięcie Centrum między rekordem metryk a wpisem końca (milisekundy) zostawia dziennik bez wpisu końca, a start
zamyka go jako Logi Urwanego Uruchomienia; Logi z wynikiem jeszcze wtedy nie istnieją, więc niczego w Skrzynce nie
zastępują.

Dziennik z pierwszą linią na dysku to też ślad komentarza postępu Wyceny w issue okresu (``pricing_progress``, #846),
który mówi, że Uruchomienie trwa. Wersją końcową tego komentarza są Logi z wynikiem na końcu Wyceny albo Logi Urwanego
Uruchomienia, które wysyła następny start. Start nie wysyła niczego za Wycenę, która doszła do wyniku: Logi z wynikiem,
które kolejka już przyjęła, zostają w Skrzynce, a wersja końcowa ze startu by je zastąpiła (#871). Dlatego Wycena, której
Logi z wynikiem nie doszły do kolejki po wpisie końca (Centrum zgasło między wpisem końca a ich przyjęciem, wpis końca się
nie zapisał, Logi nie powstały albo kolejka ich nie przyjęła), zostawia w issue okresu komentarz postępu bez wersji
końcowej; to okno zamyka #910 (najpierw model porządku wersji, potem kod).

Start Centrum czyta każdy dziennik przy budowie aplikacji, przed kartą ostatniego Uruchomienia
(``InterruptedPricings.close``):

- dziennik z wpisem końca usuwa: to Uruchomienie doszło do wyniku, także Wycena w efenix, która doszła do końca, bo jej
  dziennik zostaje do następnego startu;
- dziennik bez wpisu końca i bez Logów, czyli Urwanego Uruchomienia (ADR 0017), zamyka jako Logi Urwanego Uruchomienia
  (``RunLogs.interrupted``): zlecenia skończone przed zgaśnięciem, zlecenie zaczęte bez wyniku i liczbę wpisów, których
  nie dało się odczytać; karta po starcie pokazuje te zlecenia z tych Logów;
- dziennik z Logami Urwanego Uruchomienia, które jeszcze nie poszły (Centrum zgasło przed wysyłką), też wysyła;
- dziennik z innymi Logami usuwa (Uruchomienie z wynikiem, którego wpis końca i usunięcie dziennika się nie udały);
- dziennik bez pierwszej linii (urwany pierwszy zapis, przed którym w efenix nic się nie zmieniło) usuwa.

Logi Urwanego Uruchomienia, nowe i te z pliku, start przepuszcza przez strażnika reguły danych pracy Centrum
(``RunLogs.guard``, ADR 0025) i zapisuje w pliku Logów takie, jakie pójdą do Skrzynki, więc plik i komentarz mają te
same znaki także po Logach, które zapisała praca Centrum sprzed strażnika.

Logi Urwanego Uruchomienia idą do Skrzynki Zgłoszeń jak zwykłe Logi, ale dopiero przy pierwszym zapytaniu API tej pracy
Centrum (``InterruptedPricings.send``): przychodzi ono po ``lifespan``, a więc po ``Outbox.resume``, więc kolejka nie
dostaje wysyłki przed swoim startem (model ``verify-kolejka-skrzynki``). Dziennik znika, gdy kolejka przyjęła jego Logi,
a Centrum zgaszone przed tym wysyła je przy następnym starcie, więc wysyłka jest co najmniej raz, jak w całej kolejce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from rozliczenia.centrum import contract
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.run_logs import (
    LoggedInterruption,
    LoggedOrder,
    OrderDone,
    PricingProgress,
    RunLog,
    RunLogs,
    logs_file_name,
)
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.efenix_pricing import OrderResult
from rozliczenia.message import Message

JOURNALS_DIRECTORY: Final = "dzienniki-wyceny"
_SUFFIX: Final = ".jsonl"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class JournalStarted(_Record):
    """Pierwsza linia dziennika: start Uruchomienia, te same fakty co plik ostatniego startu."""

    entry: Literal["start Uruchomienia"]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime


class OrderBegun(_Record):
    """Zaczynam zlecenie z wiersza ``row``, ``place`` z ``total`` w przebiegu, przed pierwszym działaniem okna efenix."""

    at: datetime
    entry: Literal["zaczynam zlecenie"]
    row: int
    place: int
    total: int


class OrderEnded(_Record):
    """Zlecenie skończone z wynikiem i śladem, jak w Logach Uruchomienia."""

    at: datetime
    entry: Literal["zlecenie skończone"]
    order: LoggedOrder


class RunEnded(_Record):
    """Koniec Uruchomienia, które doszło do wyniku: ``run_process`` wrócił, a Logi z wynikiem jeszcze nie powstały."""

    at: datetime
    entry: Literal["koniec Uruchomienia"]


JournalEntry = Annotated[JournalStarted | OrderBegun | OrderEnded | RunEnded, Field(discriminator="entry")]


class _Line(RootModel[JournalEntry]):
    """Jedna linia dziennika: jeden wpis w JSON."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _path(directory: Path, started: JournalStarted) -> Path:
    return directory / Path(logs_file_name(started.started_at, started.process, started.run_id)).with_suffix(_SUFFIX)


class PricingJournal:
    """Dziennik bieżącej Wyceny w efenix (Uruchomienia procesu ``process``) w katalogu ``directory``
    (``efenix_pricing.OrderJournal`` w Centrum) i pierwsze działanie po jej wyniku (``runs.AfterRun``)."""

    def __init__(self, directory: Path, log: CentrumLog, *, process: contract.ProcessKey) -> None:
        self.process: Final = process
        self._directory = directory
        self._log = log
        self._lock = threading.Lock()
        self._started: JournalStarted | None = None
        self._header = False  # pierwszej linii nie ma jeszcze na dysku
        self._failed = False  # nieudany zapis tego Uruchomienia jest już w dzienniku Centrum
        # Wpisy tego Uruchomienia, które są już na dysku (po ``fsync``), dla postępu (``progress``).
        self._done: list[OrderDone] = []
        self._total: int | None = None
        self._current: int | None = None

    def run_started(self, info: contract.RunInfo, started_at: datetime) -> None:
        """Start Uruchomienia z Centrum, zanim ruszy jego wątek: Uruchomienie procesu ``process`` dostaje dziennik z
        pierwszą linią na dysku, a następne wpisy idą do niego; inne Uruchomienie dziennika nie ma."""

        with self._lock:
            self._done, self._total, self._current = [], None, None
            if info.process != self.process:
                self._started = None
                return
            self._started = JournalStarted(
                entry="start Uruchomienia",
                run_id=info.id,
                process=info.process,
                mode="podgląd" if info.dry_run else "zapis",
                period=info.period,
                started_at=started_at,
            )
            self._header, self._failed = True, False
            self._append_locked(self._started)

    def progress(self, run_id: str) -> PricingProgress | None:
        """Postęp Uruchomienia ``run_id`` z wpisów, które dziennik ma już na dysku, więc nigdy przed dziennikiem (#846);
        ``None``: dziennik pisze inne Uruchomienie albo żadne, albo nie ma jeszcze na dysku pierwszej linii. Wpis, którego
        nie dało się zapisać, postępu nie zmienia."""

        with self._lock:
            started = self._started
            if started is None or started.run_id != run_id or self._header:
                return None
            return PricingProgress(started, tuple(self._done), self._total, self._current)

    def begun(self, row: int, place: int, total: int) -> None:
        self._write(OrderBegun(at=_utc_now(), entry="zaczynam zlecenie", row=row, place=place, total=total))

    def ended(self, result: OrderResult, message: Message | None) -> None:
        order = LoggedOrder.of(result, None if message is None else message.code)
        self._write(OrderEnded(at=_utc_now(), entry="zlecenie skończone", order=order))

    def run_ended(self, run: EndedRun) -> None:
        """Działanie po wyniku (``runs.AfterRun``), pierwsze, przed Logami Uruchomienia: wpis końca w dzienniku, który ma
        pierwszą linię na dysku. Dziennik bez wpisu końca start Centrum wziąłby za Urwane Uruchomienie, więc usuwa go wpis
        końca, który się nie zapisał, i Uruchomienie, którego pierwsza linia nie trafiła na dysk w żadnym zapisie
        (``_header``): nieudany zapis mógł ją tam jednak zostawić (``flush`` albo ``fsync`` rzuca po ``write``).
        Uruchomienie bez dziennika (inny proces albo każdy zapis nieudany bez śladu) nie ma czego usuwać. Dziennik należy
        do ``run``, bo następne Uruchomienie startuje (``run_started``) dopiero po końcu tego."""

        with self._lock:
            started, header = self._started, self._header
        if started is None or started.run_id != run.info.id:
            return
        if header or not self._write(RunEnded(at=_utc_now(), entry="koniec Uruchomienia")):
            _remove(_path(self._directory, started), self._log, where="wpis")

    def _write(self, entry: OrderBegun | OrderEnded | RunEnded) -> bool:
        """Wpis ``entry`` na dysku (z pierwszą linią, gdy jej tam jeszcze nie ma); ``False``: nie zapisał się."""

        with self._lock:
            started = self._started
            if started is None:  # wpis bez startu Wyceny z Centrum nie ma dziennika, do którego by należał
                return False
            if not self._append_locked(started, entry):
                return False
            match entry:
                case OrderBegun():
                    self._total, self._current = entry.total, entry.row
                case OrderEnded(order=order):
                    self._done.append(OrderDone(order.row, order.outcome, order.code))
                    self._current = None
                case RunEnded():
                    pass
            return True

    def _append_locked(self, started: JournalStarted, *entries: OrderBegun | OrderEnded | RunEnded) -> bool:
        """Wpisy ``entries`` dziennika ``started`` na dysku (``fsync``), z pierwszą linią przed nimi, gdy jeszcze jej tam
        nie ma; ``False``: zapis się nie udał (jedna linia dziennika Centrum na Uruchomienie)."""

        lines: list[JournalEntry] = [started, *entries] if self._header else list(entries)
        path = _path(self._directory, started)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as journal:
                journal.write("".join(_Line(line).model_dump_json() + "\n" for line in lines))
                journal.flush()
                os.fsync(journal.fileno())
        except OSError as failure:
            if not self._failed:
                self._log.pricing_journal_unavailable(failure, where="wpis")
                self._failed = True
            return False
        self._header = False
        return True


def _remove(path: Path, log: CentrumLog, *, where: Literal["wpis", "start"]) -> None:
    """Usuwa dziennik ``path``; ``OSError`` zostawia go z linią dziennika Centrum. Dziennika nie ma także wtedy, gdy na
    miejscu katalogu dzienników stoi plik (``NotADirectoryError``, a w Windows ``FileNotFoundError``)."""

    try:
        path.unlink()
    except (FileNotFoundError, NotADirectoryError):
        pass
    except OSError as failure:
        log.pricing_journal_unavailable(failure, where=where)


@dataclass(frozen=True)
class _Read:
    """Dziennik odczytany przy starcie Centrum: start, zlecenia skończone, zlecenie zaczęte bez wyniku, ostatni wpis i
    to, czy ma wpis końca (``ended``: Uruchomienie doszło do wyniku)."""

    started: JournalStarted
    orders: list[LoggedOrder]
    interruption: LoggedInterruption
    last_at: datetime
    ended: bool


def _read(path: Path) -> _Read | None:
    """Dziennik z pliku ``path``; ``None`` bez pierwszej linii. Linie, których nie da się odczytać, liczy w ``omitted``."""

    started: JournalStarted | None = None
    orders: list[LoggedOrder] = []
    last: OrderBegun | OrderEnded | None = None
    ended = False
    omitted = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = _Line.model_validate_json(line).root
        except ValidationError:
            omitted += 1
            continue
        match entry:
            case JournalStarted():
                if started is None:
                    started = entry
            case OrderBegun():
                last = entry
            case OrderEnded():
                orders.append(entry.order)
                last = entry
            case RunEnded():
                ended = True
    if started is None:
        return None
    begun = last if isinstance(last, OrderBegun) else None
    interruption = LoggedInterruption(
        row=None if begun is None else begun.row,
        place=None if begun is None else begun.place,
        total=None if begun is None else begun.total,
        omitted=omitted,
    )
    return _Read(started, orders, interruption, started.started_at if last is None else last.at, ended)


class InterruptedPricings:
    """Dzienniki z katalogu ``directory`` przy starcie Centrum: Logi Urwanych Uruchomień do zamknięcia i wysłania."""

    def __init__(self, directory: Path, run_logs: RunLogs, log: CentrumLog) -> None:
        self._directory = directory
        self._run_logs = run_logs
        self._log = log
        self._lock = threading.Lock()
        self._pending: list[tuple[Path, RunLog]] = []  # Logi Urwanych Uruchomień do wysłania i ich dzienniki

    def close(self) -> None:
        """Przy budowie aplikacji: zamyka każdy dziennik Urwanego Uruchomienia jako jego Logi, a dzienniki Uruchomień z
        wynikiem usuwa. Dziennika, którego nie da się odczytać, nie rusza: spróbuje następny start. Logi, których pliku nie
        dało się zapisać, i tak idą do Maksa."""

        try:
            paths = sorted(self._directory.glob(f"*{_SUFFIX}"))
        except OSError as failure:
            self._log.pricing_journal_unavailable(failure, where="start")
            return
        for path in paths:
            try:
                closed = self._closed(path)
            except OSError as failure:
                self._log.pricing_journal_unavailable(failure, where="start")
                continue
            if closed is None:
                _remove(path, self._log, where="start")
            else:
                with self._lock:
                    self._pending.append((path, closed))

    async def send(self) -> None:
        """Zależność każdej trasy API: przy pierwszym zapytaniu tej pracy Centrum, już po ``Outbox.resume``, Logi
        zamkniętych dzienników idą do Kolejki wysyłki, a dziennik, którego Logi kolejka przyjęła, znika."""

        with self._lock:
            pending, self._pending = self._pending, []
        for path, record in pending:
            if self._run_logs.send(record):
                _remove(path, self._log, where="start")

    def _closed(self, path: Path) -> RunLog | None:
        """Logi Urwanego Uruchomienia z dziennika ``path`` do wysłania; ``None``: dziennik do usunięcia."""

        read = _read(path)
        if read is None or read.ended:
            return None  # bez pierwszej linii albo z wpisem końca: Uruchomienie doszło do wyniku
        started = read.started
        logs = self._run_logs.file_of(started)
        if logs.exists():
            try:
                logged = RunLog.model_validate_json(logs.read_text(encoding="utf-8"))
            except ValueError:
                return None  # Logi są, choć nieczytelne: Uruchomienie miało wynik
            if logged.ending != "interrupted":
                return None
            record = logged  # Logi, które poprzednia praca Centrum zapisała, a nie wysłała, także sprzed strażnika
        else:
            record = self._run_logs.interrupted(
                started, ended_at=read.last_at, orders=read.orders, interruption=read.interruption
            )
        # Strażnik reguły danych (ADR 0025) przed plikiem i przed wysyłką: plik i plik w Archiwum Logów okresu mają te
        # same znaki.
        record = self._run_logs.guard(record)
        try:
            self._run_logs.close(record)
        except OSError as failure:
            # Katalog Logów, który nie przyjął pliku, nie zatrzymuje Logów w drodze do Maksa (jak ``RunLogs._keep``).
            self._log.pricing_journal_unavailable(failure, where="start")
        return record
