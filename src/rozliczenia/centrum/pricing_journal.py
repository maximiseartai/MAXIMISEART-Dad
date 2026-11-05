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
Uruchomienia” z wynikiem (``PricingJournal.run_ended``): to pierwsze działanie po wyniku, więc wpis jest na dysku, zanim
powstaną Logi z wynikiem i zanim pójdą do Skrzynki. Dziennik sam mówi więc startowi Centrum, czy jego Uruchomienie doszło
do wyniku i do jakiego, a start nie zgaduje tego z Historii, którą pisze kto inny i którą start może źle odczytać (#870,
#871). Zgaśnięcie Centrum między rekordem metryk a wpisem końca (milisekundy) zostawia dziennik bez wpisu końca, a start
zamyka go jako Logi Urwanego Uruchomienia; Logi z wynikiem jeszcze wtedy nie istnieją, więc niczego w Skrzynce nie
zastępują.

Dziennik z pierwszą linią to też ślad komentarza Uruchomienia, który w Skrzynce może jeszcze mówić, że Uruchomienie
trwa, więc znika dopiero wtedy, gdy Kolejka wysyłki przyjęła wersję końcową tego komentarza. Na końcu Wyceny to Logi z
wynikiem: działanie po wyniku za Logami Uruchomienia (``JournalAfterLogs``) usuwa dziennik, gdy kolejka je przyjęła
(``RunLogs.queued``). Dziennik, którego Logów kolejka nie przyjęła (Centrum zgasło po wyniku, a przed nimi, zapis się nie
udał, Logi nie powstały), zostaje do następnego startu, także gdy nie zapisał się wpis końca, a ten start wysyła wersję
końcową z dziennika. Dziennik, który nie ma na dysku pierwszej linii (``_header``), usuwa już wpis końca: postęp do niego
nie poszedł, a nieudany zapis mógł zostawić na dysku całą pierwszą linię (``flush`` albo ``fsync`` rzuca po ``write``).

Start Centrum czyta każdy dziennik przy budowie aplikacji, przed kartą ostatniego Uruchomienia
(``InterruptedPricings.close``), i wersję końcową bierze z tego, co zastaje na dysku taty:

- dziennik z czytelnym plikiem Logów wysyła te Logi: Logi Urwanego Uruchomienia, które poprzedni start zapisał, ale nie
  wysłał, albo Logi z wynikiem, których przyjęcia przez kolejkę nikt nie zapisał;
- dziennik bez pliku Logów i bez wpisu końca, czyli Urwanego Uruchomienia (ADR 0017), zamyka jako Logi Urwanego
  Uruchomienia (``RunLogs.interrupted``): zlecenia skończone przed zgaśnięciem, zlecenie zaczęte bez wyniku i liczbę
  wpisów, których nie dało się odczytać; karta po starcie pokazuje te zlecenia z tych Logów;
- dziennik bez pliku Logów, a z wpisem końca, i dziennik z plikiem Logów, którego nie da się odczytać, wysyła wynik bez
  Logów (``run_logs.ResultWithoutLogs``): wynik z wpisu końca, zlecenia z dziennika i dlaczego pełnych Logów nie ma;
- dziennik bez pierwszej linii (urwany pierwszy zapis, przed którym w efenix nic się nie zmieniło i do którego żaden
  postęp nie poszedł) usuwa.

Logi, nowe i te z pliku, start przepuszcza przez strażnika reguły danych pracy Centrum (``RunLogs.guard``, ADR 0025) i
zapisuje w pliku Logów takie, jakie pójdą do Skrzynki, więc plik i komentarz mają te same znaki także po Logach, które
zapisała praca Centrum sprzed strażnika; wynik bez Logów przechodzi przez strażnika przy wysyłce (``RunLogs.send``).

Wersja końcowa z dziennika idzie do Skrzynki Zgłoszeń jak zwykłe Logi, ale dopiero przy pierwszym zapytaniu API tej pracy
Centrum (``InterruptedPricings.send``): przychodzi ono po ``lifespan``, a więc po ``Outbox.resume``, więc kolejka nie
dostaje wysyłki przed swoim startem (model ``verify-kolejka-skrzynki``). Ma ten sam identyfikator wysyłki co postęp i
jest od niego nowsza, więc zastępuje go w kolejce i w Skrzynce. Dziennik znika, gdy kolejka ją przyjęła, a Centrum
zgaszone przed tym wysyła ją przy następnym starcie, więc wysyłka jest co najmniej raz, jak w całej kolejce.
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
    ResultWithoutLogs,
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
    """Koniec Uruchomienia, które doszło do wyniku ``result``: ``run_process`` wrócił, a Logi z wynikiem jeszcze nie
    powstały."""

    at: datetime
    entry: Literal["koniec Uruchomienia"]
    result: contract.RunResult


JournalEntry = Annotated[JournalStarted | OrderBegun | OrderEnded | RunEnded, Field(discriminator="entry")]


class _Line(RootModel[JournalEntry]):
    """Jedna linia dziennika: jeden wpis w JSON."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _path(directory: Path, started: JournalStarted) -> Path:
    return directory / Path(logs_file_name(started.started_at, started.process, started.run_id)).with_suffix(_SUFFIX)


class PricingJournal:
    """Dziennik bieżącej Wyceny w efenix (Uruchomienia procesu ``process``) w katalogu ``directory``
    (``efenix_pricing.OrderJournal`` w Centrum) i pierwsze działanie po jej wyniku (``runs.AfterRun``); dziennik, którego
    Logi przyjęła kolejka ``run_logs``, usuwa ``JournalAfterLogs``."""

    def __init__(self, directory: Path, log: CentrumLog, *, process: contract.ProcessKey, run_logs: RunLogs) -> None:
        self.process: Final = process
        self._directory = directory
        self._log = log
        self._run_logs = run_logs
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
        """Działanie po wyniku (``runs.AfterRun``), pierwsze, przed Logami Uruchomienia: wpis końca z wynikiem ``run`` w
        dzienniku, który ma pierwszą linię na dysku. Dziennik bez niej (``_header``) usuwa, bo postęp do niego nie poszedł,
        a nieudany zapis mógł zostawić na dysku całą pierwszą linię (``flush`` albo ``fsync`` rzuca po ``write``), którą
        start wziąłby za Urwane Uruchomienie. Wpis końca, który się nie zapisał, zostawia dziennik ``JournalAfterLogs``:
        komentarz postępu nie zostaje bez wersji końcowej, gdy Centrum zgaśnie przed Logami. Dziennik należy do ``run``,
        bo następne Uruchomienie startuje (``run_started``) dopiero po końcu tego."""

        with self._lock:
            started, header = self._started, self._header
        if started is None or started.run_id != run.info.id:
            return
        if header:
            _remove(_path(self._directory, started), self._log, where="wpis")
        else:
            self._write(RunEnded(at=_utc_now(), entry="koniec Uruchomienia", result=run.result))

    def logs_ended(self, run: EndedRun) -> None:
        """Za Logami Uruchomienia ``run`` (``JournalAfterLogs``): dziennik znika, gdy Kolejka wysyłki przyjęła jego Logi
        (``RunLogs.queued``), bo wersja końcowa jego komentarza jest już w drodze do Skrzynki. Inaczej zostaje, a następny
        start Centrum wyśle ją z dziennika (``InterruptedPricings``)."""

        with self._lock:
            started = self._started
            if started is None or started.run_id != run.info.id or self._header:
                return
        if self._run_logs.queued(run.info.id):
            _remove(_path(self._directory, started), self._log, where="wpis")

    def _write(self, entry: OrderBegun | OrderEnded | RunEnded) -> None:
        with self._lock:
            started = self._started
            if started is None:  # wpis bez startu Wyceny z Centrum nie ma dziennika, do którego by należał
                return
            if not self._append_locked(started, entry):
                return
            match entry:
                case OrderBegun():
                    self._total, self._current = entry.total, entry.row
                case OrderEnded(order=order):
                    self._done.append(OrderDone(order.row, order.outcome, order.code))
                    self._current = None
                case RunEnded():
                    pass

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


@dataclass(frozen=True)
class JournalAfterLogs:
    """Działanie po wyniku za Logami Uruchomienia (``runs.AfterRun`` po ``RunLogs``): dziennik ``journal`` znika, gdy
    kolejka przyjęła Logi jego Uruchomienia (``PricingJournal.logs_ended``)."""

    journal: PricingJournal

    def run_ended(self, run: EndedRun) -> None:
        self.journal.logs_ended(run)


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
    """Dziennik odczytany przy starcie Centrum: start, zlecenia skończone, zlecenie zaczęte bez wyniku, ostatni wpis,
    liczba zleceń przebiegu z ostatniego „zaczynam zlecenie” (``None`` przed pierwszym) i wpis końca (``end``; ``None``:
    Uruchomienie nie doszło do wyniku albo zgasło przed wpisem)."""

    started: JournalStarted
    orders: list[LoggedOrder]
    interruption: LoggedInterruption
    last_at: datetime
    total: int | None
    end: RunEnded | None

    @property
    def progress(self) -> PricingProgress:
        """To, co dziennik ma, w kształcie postępu: zlecenia skończone, ile wszystkich i zlecenie zaczęte bez wyniku."""

        done = tuple(OrderDone(order.row, order.outcome, order.code) for order in self.orders)
        return PricingProgress(self.started, done, self.total, self.interruption.row)


def _read(path: Path) -> _Read | None:
    """Dziennik z pliku ``path``; ``None`` bez pierwszej linii. Linie, których nie da się odczytać, liczy w ``omitted``."""

    started: JournalStarted | None = None
    orders: list[LoggedOrder] = []
    last: OrderBegun | OrderEnded | None = None
    total: int | None = None
    end: RunEnded | None = None
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
                last, total = entry, entry.total
            case OrderEnded():
                orders.append(entry.order)
                last = entry
            case RunEnded():
                end = entry
    if started is None:
        return None
    begun = last if isinstance(last, OrderBegun) else None
    interruption = LoggedInterruption(
        row=None if begun is None else begun.row,
        place=None if begun is None else begun.place,
        total=None if begun is None else begun.total,
        omitted=omitted,
    )
    return _Read(started, orders, interruption, started.started_at if last is None else last.at, total, end)


class InterruptedPricings:
    """Dzienniki z katalogu ``directory`` przy starcie Centrum: wersje końcowe komentarzy Uruchomień, których kolejka nie
    przyjęła w ich pracy Centrum, do zamknięcia i wysłania."""

    def __init__(self, directory: Path, run_logs: RunLogs, log: CentrumLog) -> None:
        self._directory = directory
        self._run_logs = run_logs
        self._log = log
        self._lock = threading.Lock()
        self._pending: list[tuple[Path, RunLog | ResultWithoutLogs]] = []  # wersje końcowe do wysłania i ich dzienniki

    def close(self) -> None:
        """Przy budowie aplikacji: każdy dziennik z pierwszą linią zamyka jako wersję końcową komentarza jego Uruchomienia
        (docstring modułu), a dziennik bez niej usuwa. Dziennika, którego nie da się odczytać, nie rusza: spróbuje
        następny start. Logi, których pliku nie dało się zapisać, i tak idą do Maksa."""

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
        """Zależność każdej trasy API: przy pierwszym zapytaniu tej pracy Centrum, już po ``Outbox.resume``, wersje końcowe
        z zamkniętych dzienników idą do Kolejki wysyłki, a dziennik, którego wersję kolejka przyjęła, znika."""

        with self._lock:
            pending, self._pending = self._pending, []
        for path, final in pending:
            if self._run_logs.send(final):
                _remove(path, self._log, where="start")

    def _closed(self, path: Path) -> RunLog | ResultWithoutLogs | None:
        """Wersja końcowa komentarza Uruchomienia z dziennika ``path`` do wysłania; ``None``: dziennik bez pierwszej linii,
        do usunięcia."""

        read = _read(path)
        if read is None:
            return None
        started = read.started
        result = None if read.end is None else read.end.result
        logs = self._run_logs.file_of(started)
        if logs.exists():
            try:
                record = RunLog.model_validate_json(logs.read_text(encoding="utf-8"))
            except ValueError:  # Logi są, choć nieczytelne: Uruchomienie miało wynik
                return ResultWithoutLogs(read.progress, result, "nieczytelne")
            # Logi, które poprzednia praca Centrum zapisała, a których przyjęcia przez kolejkę nikt nie zapisał, także
            # Logi Urwanego Uruchomienia sprzed strażnika.
        elif read.end is not None:
            return ResultWithoutLogs(read.progress, result, "niezapisane")
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
