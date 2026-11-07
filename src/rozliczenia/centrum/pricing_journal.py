"""Dziennik Wyceny w efenix (#845) po wyniku Uruchomienia i przy następnym starcie Centrum.

Dziennik pisze i czyta ``logs_disk`` (``Journal``, ``LogsOnDisk.left_behind``); ten moduł decyduje, kiedy dziennik dostaje
wpis końca, kiedy znika i jaką wersję zastępczą komentarza Uruchomienia start Centrum z niego wysyła.

Uruchomienie, które doszło do wyniku (``run_process`` wrócił, z wierszem Historii albo bez niego), dopisuje „koniec
Uruchomienia” z wynikiem (``JournalAtResult`` → ``Journal.end``): to pierwsze działanie po wyniku, więc wpis jest na
dysku, zanim powstaną Logi z wynikiem i zanim pójdą do Skrzynki. Dziennik sam mówi więc startowi Centrum, czy jego
Uruchomienie doszło do wyniku i do jakiego, a start nie zgaduje tego z Historii, którą pisze kto inny i którą start może
źle odczytać (#870, #871). Uruchomienie, którego pierwsza linia nie trafiła na dysk w żadnym zapisie, usuwa zamiast
wpisu końca dziennik, który mógł po nim zostać (``Journal.end``). Zgaśnięcie Centrum między rekordem metryk a wpisem
końca (milisekundy) zostawia dziennik bez wpisu końca, a start zamyka go jako Logi Urwanego Uruchomienia; Logi z wynikiem
jeszcze wtedy nie istnieją, więc niczego w Skrzynce nie zastępują.

Dziennik z pierwszą linią na dysku to też ślad komentarza postępu Wyceny w issue okresu (``pricing_progress``, #846),
który mówi, że Uruchomienie trwa, więc znika dopiero wtedy, gdy Kolejka wysyłki przyjęła wersję końcową tego komentarza
(#910). Na końcu Wyceny to Logi z wynikiem: działanie po wyniku za Logami Uruchomienia (``JournalAfterLogs``) usuwa
dziennik, gdy kolejka je przyjęła (``RunLogs.queued``). Dziennik, którego Logów kolejka nie przyjęła (Centrum zgasło po
wyniku, a przed nimi, Logi nie powstały albo kolejka odmówiła), zostaje do następnego startu, także gdy nie zapisał się
wpis końca, a ten start wysyła z niego wersję zastępczą. Wersja zastępcza ma stopień wyższy od każdego postępu i niższy
od Logów z wynikiem (``outbox.Rank``), więc zamienia postęp w podsumowanie także po cofnięciu zegara komputera, a Logów z
wynikiem, które kolejka mogła już przyjąć, nie zastępuje ani w kolejce, ani w Skrzynce. Wpis końca, który się nie
zapisał, zostawia dziennik bez niego: gdy kolejka nie przyjęła też Logów z wynikiem, a pliku Logów nie ma, start zamknie
go jako Logi Urwanego Uruchomienia.

Start Centrum czyta każdy dziennik przy budowie aplikacji, przed kartą ostatniego Uruchomienia
(``InterruptedPricings.close``), i wersję zastępczą bierze z tego, co zastaje na dysku taty:

- dziennik z czytelnym plikiem Logów wysyła te Logi: Logi z wynikiem, których przyjęcia przez kolejkę nikt nie zapisał,
  albo Logi Urwanego Uruchomienia, które poprzedni start zapisał, a nie wysłał;
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

Wersja zastępcza idzie do Skrzynki Zgłoszeń jak zwykłe Logi, ale dopiero przy pierwszym zapytaniu API tej pracy Centrum
(``InterruptedPricings.send``): przychodzi ono po ``lifespan``, a więc po ``Outbox.resume``, więc kolejka nie dostaje
wysyłki przed swoim startem (model ``verify-kolejka-skrzynki``). Dziennik znika, gdy kolejka ją przyjęła, a Centrum
zgaszone przed tym wysyła ją przy następnym starcie, więc wysyłka jest co najmniej raz, jak w całej kolejce.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import (
    Found,
    Journal,
    JournalKey,
    LeftJournal,
    LogsOnDisk,
    Missing,
    Refused,
    Unreadable,
)
from rozliczenia.centrum.run_logs import ResultWithoutLogs, RunLog, RunLogs
from rozliczenia.centrum.runs import EndedRun


@dataclass(frozen=True)
class JournalAtResult:
    """Pierwsze działanie po wyniku (``runs.AfterRun``), przed Logami Uruchomienia: wpis końca z wynikiem ``run`` w
    dzienniku ``journal`` (``Journal.end``). Wpis końca, który się nie zapisał, zostawia dziennik ``JournalAfterLogs``:
    komentarz postępu nie zostaje bez wersji końcowej, gdy Centrum zgaśnie przed Logami."""

    journal: Journal

    def run_ended(self, run: EndedRun) -> None:
        self.journal.end(run.info.id, run.result)


@dataclass(frozen=True)
class JournalAfterLogs:
    """Działanie po wyniku za Logami Uruchomienia (``runs.AfterRun`` po ``RunLogs``): dziennik ``journal`` znika, gdy
    Kolejka wysyłki przyjęła Logi jego Uruchomienia (``RunLogs.queued``); inaczej zostaje, a następny start Centrum wyśle
    z niego wersję zastępczą (``InterruptedPricings``)."""

    journal: Journal
    run_logs: RunLogs

    def run_ended(self, run: EndedRun) -> None:
        if self.run_logs.queued(run.info.id):
            self.journal.remove(run.info.id)


class InterruptedPricings:
    """Dzienniki, które zostawiła poprzednia praca Centrum na Logach na dysku ``disk``, przy starcie Centrum: wersje
    zastępcze komentarzy Uruchomień, których Logów kolejka nie przyjęła w ich pracy Centrum, do zamknięcia i wysłania."""

    def __init__(self, run_logs: RunLogs, disk: LogsOnDisk, log: CentrumLog) -> None:
        self._run_logs = run_logs
        self._disk = disk
        self._log = log
        self._lock = threading.Lock()
        # wersje zastępcze do wysłania i ich dzienniki
        self._pending: list[tuple[JournalKey, RunLog | ResultWithoutLogs]] = []

    def close(self) -> None:
        """Przy budowie aplikacji: każdy dziennik z pierwszą linią zamyka jako wersję zastępczą komentarza jego
        Uruchomienia (docstring modułu), a dziennik bez niej usuwa. Dziennika, którego nie da się odczytać
        (``LogsOnDisk.left_behind``), ani dziennika, którego pliku Logów system nie daje odczytać (``logs_disk.Refused``),
        nie rusza: spróbuje następny start. Logi, których pliku nie dało się zapisać, i tak idą do Maksa."""

        for left in self._disk.left_behind():
            try:
                closed = self._closed(left)
            except OSError as failure:
                self._log.pricing_journal_unavailable(failure, where="start")
                continue
            if closed is None:
                self._disk.remove_journal(left.key)
            else:
                with self._lock:
                    self._pending.append((left.key, closed))

    async def send(self) -> None:
        """Zależność każdej trasy API: przy pierwszym zapytaniu tej pracy Centrum, już po ``Outbox.resume``, wersje
        zastępcze z zamkniętych dzienników idą do Kolejki wysyłki, a dziennik, którego wersję kolejka przyjęła, znika."""

        with self._lock:
            pending, self._pending = self._pending, []
        for key, final in pending:
            if self._run_logs.send(final):
                self._disk.remove_journal(key)

    def _closed(self, left: LeftJournal) -> RunLog | ResultWithoutLogs | None:
        """Wersja zastępcza komentarza Uruchomienia z dziennika ``left`` do wysłania; ``None``: dziennik bez pierwszej
        linii, do usunięcia."""

        read = left.journal
        if read is None:
            return None
        result = None if read.end is None else read.end.result
        match left.logs:
            case Found(logs=record):
                # Logi, które poprzednia praca Centrum zapisała, a których przyjęcia przez kolejkę nikt nie zapisał, także
                # Logi Urwanego Uruchomienia sprzed strażnika.
                pass
            case Unreadable():  # Logi są, choć nieczytelne: Uruchomienie miało wynik
                return ResultWithoutLogs(read.progress, result, "nieczytelne")
            case Refused(failure=failure):  # ``close`` zostawia dziennik do następnego startu
                raise failure
            case Missing() if read.end is not None:
                return ResultWithoutLogs(read.progress, result, "niezapisane")
            case Missing():
                record = self._run_logs.interrupted(
                    read.started, ended_at=read.last_at, orders=read.orders, interruption=read.interruption
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
