"""Komentarz Uruchomienia w issue Logów okresu (#844, #845, #846, #910): jedyne miejsce, które układa kroki jego wersji,
plików Logów i dziennika Wyceny w efenix w Uruchomieniu i przy starcie Centrum.

Co jest którą wersją komentarza, w jakim stopniu i co dalej z dziennikiem, decyduje ``comment_versions``, a pliki zapisuje
i czyta ``logs_disk``. ``RunComments`` tylko układa ich kroki w kolejności modelu ``verify-urwane-uruchomienie``, każdy we
własnej osłonie, i trzyma to, co komentarz pamięta w tej pracy Centrum: obserwowaną Wycenę i ostatnie Logi do Diagnozy.

**Start Uruchomienia** (``RunComments.run_started``, zanim ruszy jego wątek): pierwsza linia dziennika Wyceny i plik
ostatniego startu (``LogsOnDisk.started``), potem postęp. Plik startu, którego nie dało się zapisać, wychodzi do
``RunHost.start`` i postępu nie ma; postęp jest ostatni, bo jest dla Maksa, a nie warunkiem pracy taty.

**Postęp Wyceny w efenix** (#846): Wycena trwa u taty do półtorej godziny, a Logi powstają dopiero na jej końcu. Przy jej
starcie Centrum zakłada komentarz Uruchomienia, a potem co ``PROGRESS_S`` na zegarze Centrum, nigdy częściej, odświeża go
stanem dziennika (``logs_disk.Journal.progress``): zlecenia skończone z wszystkich, wyniki do tej pory, ostatnie skończone
zlecenie, zlecenie w trakcie i czas od startu. Dziennik podaje tylko wpisy, które już ma na dysku, a bez swojej pierwszej
linii na dysku nic, więc postęp nigdy go nie wyprzedza: każdy komentarz postępu ma dziennik. Wycena, której dziennika nie
da się zapisać, postępu nie ma, tylko podsumowanie na końcu. Postęp to wersja najniższego stopnia
(``comment_versions.ProgressVersion``), po strażniku reguły danych jak Logi; od działań po wyniku jego Uruchomienia
(``run_ended``) nie idzie, a pierwsze odświeżenie po końcu kończy budzik. Postęp, którego kolejka nie przyjęła, ``Outbox.post``
zapisuje w dzienniku Centrum, a Wycena biegnie dalej.

**Koniec Uruchomienia** (``RunComments.run_ended``, pierwsze działanie po wyniku, ``runs.AfterRun``), cztery kroki:

1. wpis końca z wynikiem w dzienniku Wyceny (``Journal.end``): jest na dysku, zanim powstaną Logi z wynikiem i zanim
   pójdą do Skrzynki, więc dziennik sam mówi następnemu startowi, czy jego Uruchomienie doszło do wyniku i do jakiego, a
   start nie zgaduje tego z Historii (#870, #871); Uruchomienie, którego pierwsza linia nie trafiła na dysk w żadnym zapisie,
   zamiast niego usuwa dziennik, który mógł po nim zostać;
2. Logi z wynikiem (``RecordMaker.of``) po strażniku reguły danych (``run_logs_guard.guard_logs``, ADR 0025);
3. plik Logów (``LogsOnDisk.write``), a potem, także gdy pliku nie dało się zapisać, te same Logi do Kolejki wysyłki
   (``comment_versions.OwnLogs``, stopień najwyższy): komentarz z podsumowaniem i plik w Archiwum Logów okresu;
4. dziennik znika, gdy kolejka przyjęła Logi (``comment_versions.journal_after``); inaczej zostaje do następnego startu,
   który zamknie go wersją zastępczą.

Błąd jednego kroku trafia do dziennika Centrum (typ, jak w ``RunHost.after``) i nie pomija następnych: wpis końca, który się
nie zapisał, nie zatrzymuje Logów, a plik Logów, który się nie zapisał, nie zatrzymuje ich wysyłki. Bez Logów (krok 2
rzucił) nic nie idzie, a dziennik zostaje. Zgaśnięcie Centrum między wpisem końca a przyjęciem Logów zostawia dziennik z
wpisem końca, a start wysyła z niego wynik bez Logów; Logi z wynikiem, które kolejka mogła już przyjąć, mają wyższy stopień,
więc ich nie zastępuje.

**Diagnoza** Zatrzymania (``RunComments.diagnosed``) dopisuje się do Logów swojego Uruchomienia: ten sam plik dostaje pole
``diagnosis``, a Logi idą do kolejki drugi raz jako nowsza wersja tej samej wysyłki, więc kolejka podmienia plik w Archiwum
i zmienia komentarz tego Uruchomienia (#840, #844). Diagnoza z tym samym wynikiem co ostatnio dopisana
(``LoggedDiagnosis.same_result``) nie zmienia niczego: po nieoczekiwanym wyjątku karta zaczyna Diagnozę sama przy każdym
pokazaniu, a Maks potrzebuje tylko zmiany wyniku. Diagnozę ma tylko ostatnie Uruchomienie tej pracy Centrum, więc w
pamięci zostają tylko jego Logi; Diagnoza, w której trakcie skończyło się następne Uruchomienie, nie dopisuje się nigdzie.

**Start Centrum** zamyka dzienniki, które zostawiła poprzednia praca Centrum. Dziennik Wyceny z pierwszą linią na dysku to
ślad Uruchomienia, którego wersji końcowej komentarza kolejka nie przyjęła w jego pracy Centrum: Centrum zgasło w trakcie
Wyceny albo po wyniku, a przed Logami, Logi nie powstały albo kolejka odmówiła. Start zamyka każdy taki dziennik przy budowie
aplikacji, przed kartą ostatniego Uruchomienia (``RunComments.close_left_behind``, ``run_cards.RunCards.last`` bierze jego
dowód ``LeftBehindClosed``), a wersję zastępczą bierze z tego, co zastaje na dysku taty (macierz
``comment_versions.close``, ze strażnikiem reguły danych tej pracy Centrum w środku). Dziennik Urwanego Uruchomienia
(ADR 0017) zamyka jako Logi Urwanego Uruchomienia (``RecordMaker.interrupted``), a karta po starcie pokazuje zlecenia z
tych Logów.

Logi, nowe i te z pliku, start zapisuje w pliku Logów takie, jakie pójdą do Skrzynki (``LogsOnDisk.write``), więc plik i
komentarz mają te same znaki także po Logach, które zapisała praca Centrum sprzed strażnika. Plik, którego nie dało się
zapisać, nie zatrzymuje Logów w drodze do Maksa. Dziennika, którego nie da się odczytać, ani dziennika, którego pliku Logów
system nie daje odczytać (``logs_disk.Refused``), start nie rusza: spróbuje następny.

Wersja zastępcza idzie do Skrzynki Zgłoszeń jak zwykłe Logi, ale dopiero w starcie serwera, po ``Outbox.resume`` w
``lifespan`` i po wpisie ``start`` (``RunComments.send_left_behind``, krok ``server.AFTER_START``), więc kolejka nie
dostaje wysyłki przed swoim startem (model ``verify-kolejka-skrzynki``), a wpisy wysyłki należą w dzienniku do tej pracy
Centrum. Dziennik znika, gdy kolejka ją przyjęła
(``comment_versions.journal_after``), a Centrum zgaszone przed tym wysyła ją przy następnym starcie, więc wysyłka jest co
najmniej raz, jak w całej kolejce. Wersja zastępcza ma stopień wyższy od każdego postępu i niższy od Logów z wynikiem
(``comment_versions.rank_of``), więc zamienia postęp w podsumowanie także po cofnięciu zegara komputera, a Logów z wynikiem,
które kolejka mogła już przyjąć, nie zastępuje ani w kolejce, ani w Skrzynce.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import cache, partial
from pathlib import Path
import platform
import threading
from typing import Final, Protocol, TypeVar, assert_never

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.comment_versions import (
    LABEL,
    Drop,
    LogsPost,
    OwnLogs,
    ProgressVersion,
    StandInLogs,
    StandInVersion,
    WithoutLogsVersion,
    close,
    journal_after,
    post_of,
    progress_markdown,
)
from rozliczenia.centrum.dad_action_journal import DadActionJournal
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.logs_disk import JournalKey, JournalRead, LogsOnDisk
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.logs_of_run import logged_diagnosis, logs_of
from rozliczenia.centrum.run_logs import Environment, LoggedFile, RunLog, StartFacts, Tool
from rozliczenia.centrum.run_logs_guard import GuardedLogs, guard_logs, guard_text
from rozliczenia.centrum.settings.owner import SettingsSnapshot
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.period_folder import PeriodFolderInaccessible
from rozliczenia.wall_clock import utc_now

PROGRESS_S: Final = 300.0
"""Odstęp między postępami jednej Wyceny w efenix na zegarze Centrum (#846: „najwyżej co 5 minut”)."""

_AFTER_RUN: Final = "po wyniku Uruchomienia procesu"
"""Miejsce błędu kroku końca Uruchomienia w dzienniku Centrum: to samo co błąd działania po wyniku w ``RunHost.after``."""
_LEFT_BEHIND: Final = "wysyłka wersji zastępczych przy starcie"
"""Miejsce błędu wysyłki jednej wersji zastępczej w kroku startu serwera (``RunComments.send_left_behind``)."""

_PROGRESS_PLACE: Final = "postęp Wyceny w efenix"
"""Miejsce zamaskowanej wartości w uwadze technicznej postępu."""

T = TypeVar("T")

ProcessFiles = Callable[[common_contract.ProcessKey, str, SettingsSnapshot | None], Sequence[Path]]
"""Pliki procesu dla tokenu okresu z migawką Ustawień Centrum ze startu Uruchomienia (``None``: bez migawki, z
bieżącymi)."""
"""Pliki taty Uruchomienia procesu dla tokenu okresu, z Ustawieniami Centrum z chwili końca Uruchomienia."""


class CommentQueue(Protocol):
    """Kolejka wysyłki (``outbox.Outbox``) tak, jak widzi ją komentarz Uruchomienia."""

    def post(self, post: LogsPost) -> bool:
        """Wysyłka Logów z ``post_of`` do kolejki; ``True``: plik kolejki powstał."""
        ...

    def delivered(self, run_id: str, label: Label) -> str | None:
        """Adres komentarza wysyłki Uruchomienia ``run_id`` z etykietą ``label``, który Skrzynka przyjęła w tej pracy
        Centrum; ``None``: jeszcze żaden."""
        ...


@dataclass(frozen=True)
class LeftBehindClosed:
    """Dowód, że start Centrum zamknął każdy dziennik Wyceny, który zostawiła poprzednia praca Centrum
    (``RunComments.close_left_behind``). Karta ostatniego Uruchomienia (``run_cards.RunCards.last``) go bierze, więc
    nie przeczyta Logów, zanim powstaną Logi Urwanego Uruchomienia."""


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
        environment = self._environment(run.info.process, run.info.period, run.settings)
        return logs_of(run, tool=self._tool(), environment=environment, dad_actions=self._dad_actions.take())

    def interrupted(self, journal: JournalRead) -> RunLog:
        """Logi Urwanego Uruchomienia z dziennika ``journal`` (``RunLog.interrupted``): Aktualizacja narzędzia nie startuje
        w trakcie Uruchomienia, więc po zgaśnięciu Centrum ma ten sam commit."""

        return RunLog.interrupted(
            journal.started,
            ended_at=journal.last_at,
            orders=journal.orders,
            interruption=journal.interruption,
            tool=self._tool(),
            environment=self._environment(journal.started.process, journal.started.period, None),
            dad_actions=self._dad_actions.take(),
        )

    def _tool(self) -> Tool:
        commit = self._commit()
        release = None if commit is None else self._wydanie(commit)
        return Tool(wydanie=None if release is None else release.version, commit=commit)

    def _environment(
        self, process: common_contract.ProcessKey, period: str, settings: SettingsSnapshot | None
    ) -> Environment:
        """Środowisko Uruchomienia do Logów. Niedostępny folder to stan komputera taty, nie nieoczekiwany wyjątek, więc
        Logi mają wtedy pliki ``None``, bez wpisu w dzienniku, który Diagnoza by zgłosiła."""

        try:
            paths = self._files(process, period, settings)
        except (OSError, PeriodFolderInaccessible):
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


@dataclass(frozen=True)
class _Watched:
    """Wycena w efenix z komentarzem postępu, jej start na zegarze Centrum i to, czy doszła do działań po wyniku
    (``ended``): wtedy jej postęp się skończył."""

    run_id: str
    since: float
    ended: bool = False


class RunComments:
    """Komentarz Uruchomienia każdego Uruchomienia procesu z Centrum (docstring modułu).

    ``run_ended`` oznacza Wycenę jako skończoną pod tą samą blokadą co postęp, więc postęp, który już idzie do kolejki,
    jest w niej przed Logami, a następny nie pójdzie. Wynik wysyłki Logów (``accepted``) zostaje także wtedy, gdy plik
    Logów rzucił po niej, a każdy krok końca biegnie we własnej osłonie (``_step``), więc nie zmienia wyniku ani nie
    pomija następnych. Katalog Logów, który przy starcie nie przyjął pliku Logów Urwanego Uruchomienia
    (``close_left_behind``), nie zatrzymuje tych Logów w drodze do Maksa, a wyjątek przy wysyłce wersji zastępczej
    (``send_left_behind``) zostawia jej dziennik na dysku, więc wersja idzie przy następnym starcie.
    """

    def __init__(self, work: CentrumWork, disk: LogsOnDisk, queue: CommentQueue, records: RecordMaker) -> None:
        """``_lock`` porządkuje postęp, Logi z wynikiem i Diagnozę: postęp, który już idzie do kolejki, jest w niej przed
        Logami, a dwie Diagnozy naraz (dwie karty) piszą plik i komentarz jedna po drugiej. ``_last`` to Logi ostatniego
        Uruchomienia tak, jak ostatnio poszły do pliku i Skrzynki."""

        self._disk = disk
        self._queue = queue
        self._forbidden = work.forbidden
        self._clock = work.clock
        self._log = work.log
        self._records = records
        self._lock = threading.Lock()
        self._watched: _Watched | None = None
        self._last: GuardedLogs | None = None
        self._pending: list[tuple[JournalKey, StandInVersion]] = []

    def run_started(self, info: runs_contract.RunInfo, started_at: datetime) -> None:
        """Start Uruchomienia z Centrum, zanim ruszy jego wątek (docstring modułu); ``OSError`` pliku startu wychodzi do
        ``RunHost.start``."""

        self._disk.started(StartFacts.of_run(info, started_at))
        if info.process != self._disk.journal.process:
            return
        watched = self._watched = _Watched(info.id, self._clock())
        self._progress(watched)
        self._clock.after(PROGRESS_S, partial(self._refresh, info.id))

    def _refresh(self, run_id: str) -> None:
        """Budzik ``PROGRESS_S`` po starcie albo poprzednim odświeżeniu: postęp i następny budzik, dopóki Uruchomienie
        ``run_id`` nie doszło do działań po wyniku i nie zaczęło się następne."""

        watched = self._watched
        if watched is None or watched.run_id != run_id or not self._progress(watched):
            return
        self._clock.after(PROGRESS_S, partial(self._refresh, run_id))

    def _progress(self, watched: _Watched) -> bool:
        """Postęp ``watched`` z dziennika do Kolejki wysyłki (``ProgressVersion``). ``False``: Uruchomienie doszło do
        działań po wyniku (``run_ended``), więc jego postęp się skończył i nic nie idzie, bo postęp po Logach byłby ich
        nowszą wersją i cofnąłby podsumowanie. Postęp, którego kolejka nie przyjęła, daje ``True``: typ błędu jest w
        dzienniku Centrum, a następne odświeżenie spróbuje znowu."""

        progress = self._disk.journal.progress(watched.run_id)
        elapsed_s = self._clock() - watched.since
        with self._lock:
            current = self._watched
            if current is None or current.run_id != watched.run_id or current.ended:
                return False
            if progress is not None:
                text = guard_text(progress_markdown(progress, elapsed_s=elapsed_s), _PROGRESS_PLACE, self._forbidden)
                self._queue.post(post_of(ProgressVersion(progress, text)))
            return True

    def run_ended(self, run: EndedRun) -> None:
        """Koniec Uruchomienia ``run`` (``runs.AfterRun``) w czterech krokach modelu, każdy we własnej osłonie (docstring
        modułu): wpis końca, Logi z wynikiem, plik i wysyłka, dziennik po przyjęciu."""

        run_id = run.info.id
        self._step(lambda: self._disk.journal.end(run_id, run.result))
        with self._lock:
            if self._watched is not None and self._watched.run_id == run_id:
                self._watched = replace(self._watched, ended=True)
        logs = self._step(lambda: self._own(run))
        if logs is None:
            return
        accepted: list[bool] = []
        self._step(lambda: self._keep(logs, accepted.append))
        if accepted and journal_after(OwnLogs(logs), accepted=accepted[0]) == "usuń":
            self._step(lambda: self._disk.journal.remove(run_id))

    def _own(self, run: EndedRun) -> GuardedLogs:
        logs = guard_logs(self._records.of(run), self._forbidden)
        with self._lock:
            self._last = logs
        return logs

    def _step(self, step: Callable[[], T]) -> T | None:
        try:
            return step()
        except Exception as failure:
            self._log.unexpected_failure(failure, where=_AFTER_RUN)
            return None

    def link(self, run_id: str) -> str | None:
        """Adres komentarza Logów Uruchomienia ``run_id``, który Skrzynka przyjęła w tej pracy Centrum; ``None``: jeszcze
        żaden. Komentarz Uruchomienia prowadzi do jego pełnych Logów w Archiwum Logów okresu, także po Diagnozie."""

        return self._queue.delivered(run_id, LABEL)

    def diagnosed(self, run_id: str, diagnosis: Diagnosis) -> None:
        """Dopisuje Diagnozę do Logów Uruchomienia ``run_id`` (docstring modułu, ``stops.DiagnosedLogs``); Logi, które
        jeszcze czekają w kolejce, Logi z Diagnozą zastępują (``outbox._superseded``).

        Plik Logów, którego nie dało się zapisać, wychodzi po wysyłce jako błąd, a następna Diagnoza próbuje znowu: plik
        i komentarz.
        """

        with self._lock:
            last = self._last
            if last is None or last.record.run_id != run_id:
                return
            logged = logged_diagnosis(diagnosis, diagnosed_at=utc_now())
            logs = last.with_diagnosis(logged, self._forbidden)
            if logs is None:
                return
            self._keep(logs, lambda accepted: None)
            self._last = logs

    def _keep(self, logs: GuardedLogs, accepted: Callable[[bool], None]) -> None:
        """Plik Logów (nowy albo nadpisany), a potem, także gdy pliku nie dało się zapisać, do Skrzynki komentarz w issue
        okresu i plik w Archiwum Logów okresu z tymi samymi bajtami co plik (``LogsOnDisk.write``): katalog Logów, który nie
        przyjął pliku, nie zatrzymuje Logów w drodze do Maksa. ``accepted`` dostaje wynik wysyłki (``Outbox.post``), a
        błąd zapisu pliku wychodzi dopiero po niej."""

        try:
            self._disk.write(logs)
        finally:
            accepted(self._queue.post(post_of(OwnLogs(logs))))

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
                        self._log.pricing_journal_unavailable(failure, where="start")
                case WithoutLogsVersion():
                    pass
                case _:
                    assert_never(closing)
            with self._lock:
                self._pending.append((left.key, closing))
        return LeftBehindClosed()

    def send_left_behind(self) -> None:
        """Krok startu serwera po wpisie ``start`` i po ``Outbox.resume``, przed pierwszym zapytaniem: wersje zastępcze z
        zamkniętych dzienników idą do Kolejki wysyłki, a dziennik, którego wersję kolejka przyjęła, znika
        (``journal_after``); dziennik wersji, której kolejka nie przyjęła, czeka na następny start. Błąd jednej wersji
        trafia do dziennika Centrum (typ) i nie zatrzymuje startu Centrum ani następnych wersji."""

        with self._lock:
            pending, self._pending = self._pending, []
        for key, version in pending:
            try:
                if journal_after(version, accepted=self._queue.post(post_of(version))) == "usuń":
                    self._disk.remove_journal(key)
            except Exception as failure:
                self._log.unexpected_failure(failure, where=_LEFT_BEHIND)
