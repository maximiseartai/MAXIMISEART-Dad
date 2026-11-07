"""Komentarz Uruchomienia przy starcie Centrum: dzienniki Wyceny w efenix, które zostawiła poprzednia praca Centrum (#845,
#910).

Dziennik Wyceny z pierwszą linią na dysku to ślad Uruchomienia, którego wersji końcowej komentarza Kolejka wysyłki nie
przyjęła w jego pracy Centrum (``pricing_journal``): Centrum zgasło w trakcie Wyceny albo po wyniku, a przed Logami, Logi
nie powstały albo kolejka odmówiła. Start Centrum zamyka każdy taki dziennik przy budowie aplikacji, przed kartą
ostatniego Uruchomienia (``RunComments.close_left_behind``, ``run_cards.RunCards.last`` bierze jego dowód
``LeftBehindClosed``), a wersję zastępczą bierze z tego, co zastaje na dysku taty (macierz ``comment_versions.close``,
ze strażnikiem reguły danych tej pracy Centrum w środku, ADR 0025):

- dziennik z czytelnym plikiem Logów wysyła te Logi: Logi z wynikiem, których przyjęcia przez kolejkę nikt nie zapisał,
  albo Logi Urwanego Uruchomienia, które poprzedni start zapisał, a nie wysłał;
- dziennik bez pliku Logów i bez wpisu końca, czyli Urwanego Uruchomienia (ADR 0017), zamyka jako Logi Urwanego
  Uruchomienia (``RecordMaker.interrupted``): zlecenia skończone przed zgaśnięciem, zlecenie zaczęte bez wyniku i liczbę
  wpisów, których nie dało się odczytać; karta po starcie pokazuje te zlecenia z tych Logów;
- dziennik bez pliku Logów, a z wpisem końca, i dziennik z plikiem Logów, którego nie da się odczytać, wysyła wynik bez
  Logów (``comment_versions.ResultWithoutLogs``): wynik z wpisu końca, zlecenia z dziennika i dlaczego pełnych Logów nie ma;
- dziennik bez pierwszej linii (urwany pierwszy zapis, przed którym w efenix nic się nie zmieniło i do którego żaden
  postęp nie poszedł) usuwa.

Logi, nowe i te z pliku, start zapisuje w pliku Logów takie, jakie pójdą do Skrzynki (``LogsOnDisk.write``), więc plik i
komentarz mają te same znaki także po Logach, które zapisała praca Centrum sprzed strażnika. Plik, którego nie dało się
zapisać, nie zatrzymuje Logów w drodze do Maksa. Dziennika, którego nie da się odczytać, ani dziennika, którego pliku Logów
system nie daje odczytać (``logs_disk.Refused``), start nie rusza: spróbuje następny.

Wersja zastępcza idzie do Skrzynki Zgłoszeń jak zwykłe Logi, ale dopiero przy pierwszym zapytaniu API tej pracy Centrum
(``RunComments.send_left_behind``): przychodzi ono po ``lifespan``, a więc po ``Outbox.resume``, więc kolejka nie dostaje
wysyłki przed swoim startem (model ``verify-kolejka-skrzynki``). Dziennik znika, gdy kolejka ją przyjęła
(``comment_versions.journal_after``), a Centrum zgaszone przed tym wysyła ją przy następnym starcie, więc wysyłka jest co
najmniej raz, jak w całej kolejce. Wersja zastępcza ma stopień wyższy od każdego postępu i niższy od Logów z wynikiem
(``comment_versions.rank_of``), więc zamienia postęp w podsumowanie także po cofnięciu zegara komputera, a Logów z wynikiem,
które kolejka mogła już przyjąć, nie zastępuje ani w kolejce, ani w Skrzynce.

``RecordMaker`` składa Logi z dzisiejszym narzędziem, środowiskiem i działaniami taty, które czekają na Logi: Logi z wynikiem
(``run_logs.RunLogs``) i Logi Urwanego Uruchomienia.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
import platform
import threading
from typing import Protocol, assert_never

from rozliczenia.centrum import contract
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.comment_versions import (
    Drop,
    StandInLogs,
    StandInVersion,
    WithoutLogsVersion,
    close,
    journal_after,
    post_of,
)
from rozliczenia.centrum.dad_actions import DadActionJournal
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import JournalKey, JournalRead, LogsOnDisk
from rozliczenia.centrum.outbox import Post
from rozliczenia.centrum.run_logs import Environment, LoggedFile, ProcessFiles, RunLog, Tool
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import Release
from rozliczenia.client_data import ForbiddenValues
from rozliczenia.period_folder import PeriodFolderInaccessible


class CommentQueue(Protocol):
    """Kolejka wysyłki (``outbox.Outbox``) tak, jak widzi ją komentarz Uruchomienia: ``post`` mówi, czy plik kolejki
    powstał."""

    def post(self, post: Post) -> bool: ...


@dataclass(frozen=True)
class LeftBehindClosed:
    """Dowód, że start Centrum zamknął każdy dziennik Wyceny, który zostawiła poprzednia praca Centrum
    (``RunComments.close_left_behind``). Karta ostatniego Uruchomienia (``run_cards.RunCards.last``) go bierze, więc w
    ``create_app`` nie przeczyta Logów, zanim powstaną Logi Urwanego Uruchomienia. Kod, który go tworzy sam, omija tę
    kolejność: to zostaje przeglądowi."""


class RecordMaker:
    """Logi Uruchomienia z dzisiejszym narzędziem (``commit``, ``wydanie``), środowiskiem (system, Python i pliki procesu
    ``files`` z rozmiarem i atrybutem OneDrive z ``cloud_files``) i działaniami taty, które czekają na Logi
    (``dad_actions``)."""

    def __init__(
        self,
        *,
        commit: CommitSource,
        wydanie: Callable[[str], Release | None],
        files: ProcessFiles,
        cloud_files: CloudFiles,
        dad_actions: DadActionJournal,
    ) -> None:
        self._commit = commit
        self._wydanie = wydanie
        self._files = files
        self._cloud = cloud_files
        self._dad_actions = dad_actions

    def of(self, run: EndedRun) -> RunLog:
        """Logi Uruchomienia ``run``, które doszło do działań po wyniku (``RunLog.of``)."""

        environment = self._environment(run.info.process, run.info.period)
        return RunLog.of(run, tool=self._tool(), environment=environment, dad_actions=self._dad_actions.take())

    def interrupted(self, journal: JournalRead) -> RunLog:
        """Logi Urwanego Uruchomienia z dziennika ``journal`` (``RunLog.interrupted``): Aktualizacja narzędzia nie startuje
        w trakcie Uruchomienia, więc po zgaśnięciu Centrum ma ten sam commit."""

        return RunLog.interrupted(
            journal.started,
            ended_at=journal.last_at,
            orders=journal.orders,
            interruption=journal.interruption,
            tool=self._tool(),
            environment=self._environment(journal.started.process, journal.started.period),
            dad_actions=self._dad_actions.take(),
        )

    def _tool(self) -> Tool:
        commit = self._commit()
        release = None if commit is None else self._wydanie(commit)
        return Tool(wydanie=None if release is None else release.version, commit=commit)

    def _environment(self, process: contract.ProcessKey, period: str) -> Environment:
        try:
            paths = self._files(process, period)
        except (OSError, PeriodFolderInaccessible):
            # Niedostępny folder to stan komputera taty, nie nieoczekiwany wyjątek: bez wpisu, który Diagnoza by zgłosiła.
            files = None
        else:
            files = [self._file(path) for path in paths]
        return Environment(system=_system(), python=platform.python_version(), files=files)

    def _file(self, path: Path) -> LoggedFile:
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        online_only = self._cloud.online_only(path) if self._cloud.checked and size is not None else None
        return LoggedFile(name=path.name, size=size, online_only=online_only)


@cache
def _system() -> str:
    """System raz na pracę Centrum, przy pierwszych Logach, nie przy starcie; nigdy ``platform.node()`` (nazwa komputera)."""

    return platform.platform()


class RunComments:
    """Komentarze Uruchomień przy starcie Centrum (docstring modułu): dzienniki Wyceny na Logach na dysku ``disk``
    zamknięte wersjami zastępczymi po strażniku ``forbidden`` i wysłane do kolejki ``queue``; Logi Urwanego Uruchomienia
    składa ``records``."""

    def __init__(
        self,
        disk: LogsOnDisk,
        queue: CommentQueue,
        *,
        forbidden: ForbiddenValues,
        log: CentrumLog,
        records: RecordMaker,
    ) -> None:
        self._disk = disk
        self._queue = queue
        self._forbidden = forbidden
        self._log = log
        self._records = records
        self._lock = threading.Lock()
        # wersje zastępcze do wysłania i ich dzienniki
        self._pending: list[tuple[JournalKey, StandInVersion]] = []

    def close_left_behind(self) -> LeftBehindClosed:
        """Przy budowie aplikacji: każdy dziennik z pierwszą linią zamyka wersją zastępczą komentarza jego Uruchomienia
        (``comment_versions.close``), a Logi zapisuje w pliku Logów; dziennik bez niej usuwa. Niczego nie wysyła."""

        for left in self._disk.left_behind():
            try:
                closing = close(left, self._forbidden, self._records.interrupted)
            except OSError as failure:
                self._log.pricing_journal_unavailable(failure, where="start")
                continue
            match closing:
                case Drop():
                    self._disk.remove_journal(left.key)
                    continue
                case StandInLogs(logs=logs):
                    try:
                        self._disk.write(logs)
                    except OSError as failure:
                        # Katalog Logów, który nie przyjął pliku, nie zatrzymuje Logów w drodze do Maksa.
                        self._log.pricing_journal_unavailable(failure, where="start")
                case WithoutLogsVersion():
                    pass
                case _:
                    assert_never(closing)
            with self._lock:
                self._pending.append((left.key, closing))
        return LeftBehindClosed()

    async def send_left_behind(self) -> None:
        """Zależność każdej trasy API: przy pierwszym zapytaniu tej pracy Centrum, już po ``Outbox.resume``, wersje
        zastępcze z zamkniętych dzienników idą do Kolejki wysyłki, a dziennik, którego wersję kolejka przyjęła, znika
        (``journal_after``); dziennik wersji, której kolejka nie przyjęła, czeka na następny start."""

        with self._lock:
            pending, self._pending = self._pending, []
        for key, version in pending:
            if journal_after(version, accepted=self._queue.post(post_of(version))) == "usuń":
                self._disk.remove_journal(key)
