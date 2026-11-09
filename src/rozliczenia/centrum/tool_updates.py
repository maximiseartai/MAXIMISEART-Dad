"""Aktualizacja narzędzia z Centrum rozliczeń: akcja karty, krok i wynik dla przeglądarki (ADR 0009).

Samą aktualizację robi ``tool_update.ToolClone.update``; ten moduł prowadzi ją
w Centrum. Zajmuje miejsce „jedno naraz” w ``RunHost`` (odmowy 409 w trakcie
Uruchomienia procesu albo innej aktualizacji), odpowiada od razu i prowadzi
aktualizację w osobnym wątku, a karta odczytuje krok i wynik. Dziennik Centrum
dostaje start i koniec z commitem przed i po, bez ścieżek i bez wyjścia Gita.
Po udanej aktualizacji Centrum zamyka się, a opiekun ponownego startu
(``restart_guardian``) uruchamia nową wersję; koniec aktualizacji zapisuje
wtedy w dzienniku nowe Centrum, z pliku wyniku od opiekuna. Gdy opiekun nie
wystartuje, klon wraca do wersji sprzed kliknięcia, a Centrum działa dalej.
Każdą porażkę, której ``tool_update`` nie przewidział, karta widzi jako Komunikat
nieoczekiwanej porażki, a dziennik tylko nazwę typu wyjątku. Przy każdej
porażce karta dostaje też Zgłoszenie do Maksa z faktami dziennika, a jego stan
czyta z uchwytu Zgłoszenia (``reports.ReportHandle``) przy każdym odczycie.
Porażkę kliknięcia karta widzi dopiero ze stanem po odpowiedzi skrzynki
Zgłoszeń (najwyżej termin szukania), a porażkę od opiekuna od razu.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Final

from fastapi import APIRouter, Request

from rozliczenia.centrum import restart_guardian, update_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import tool_update as tool_update_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.reports import ReportHandle, Reports, UpdateReport
from rozliczenia.centrum.restart_guardian import Restart
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import CommitSource, GitHubReleases, ReleaseSource
from rozliczenia.centrum.tool_update import (
    RESULT_FILE,
    UNEXPECTED,
    UP_TO_DATE,
    ROLLBACK_FAILED,
    UPDATED,
    Step,
    ToolClone,
    UpdateResult,
    read_result,
)
from rozliczenia.centrum.work import CentrumWork

# Nazwa wątku Aktualizacji narzędzia (``ToolUpdates.start``); po udanej kończy się, gdy opiekun wystartował i Centrum
# się zamknęło.
UPDATE_THREAD: Final = "aktualizacja-narzedzia"

GuardianLauncher = Callable[[Path, Restart], object]
"""Uruchamia opiekuna ponownego startu z kopii (``restart_guardian.launch``); w testach podstawiany."""


class ToolUpdates:
    """Aktualizacja narzędzia tego Centrum: najwyżej jedna naraz, a po niej jej wynik.

    ``clone`` daje klon narzędzia przy każdym kliknięciu, nie przy starcie
    Centrum (test bez podstawionego klonu kończy się dopiero na akcji), a
    ``commit`` to commit narzędzia przed aktualizacją, tak jak widzi go Diagnoza.

    Wynik ``AKTUALNA`` dotyczy najnowszego Wydania, które Centrum znało w jego
    chwili (``release``, ta sama pamięć co w Konfiguracji); gdy Centrum zna już
    inne, wynik znika, żeby przy przycisku nowego Wydania nie było starego „Masz
    najnowszą wersję.” (#373).

    Po udanej aktualizacji Centrum uruchamia opiekuna ponownego startu
    (``guardian``) i zamyka się (``shutdown``); miejsca „jedno naraz” już nie
    zwalnia. Opiekun zostawia wynik w ``result_file``, a nowe Centrum odczytuje
    go raz przy starcie: zapisuje koniec aktualizacji w dzienniku, usuwa plik i
    pokazuje wynik karcie.
    """

    def __init__(
        self,
        work: CentrumWork,
        clone: Callable[[], ToolClone],
        runs: RunHost,
        commit: CommitSource,
        reports: Reports,
        *,
        shutdown: Shutdown,
        guardian: GuardianLauncher,
        release: ReleaseSource,
    ) -> None:
        self._clone = clone
        self._runs = runs
        self._log = work.log
        self._reports = reports
        self._commit = commit
        self._shutdown = shutdown
        self._guardian = guardian
        self._result_file = work.config / RESULT_FILE
        self._release = release
        self._lock = threading.Lock()
        self._view: tool_update_contract.ToolUpdate | _Failed = tool_update_contract.ToolUpdateIdle(state="idle")
        self._up_to_date_with: GitHubReleases | None = None
        self._after_restart()

    def current(self) -> tool_update_contract.ToolUpdate:
        with self._lock:
            view, judged = self._view, self._up_to_date_with
        if isinstance(view, tool_update_contract.ToolUpdateUpToDate):
            newest = self._release()
            with self._lock:
                if newest is not None and newest != judged and self._view is view:
                    self._view = tool_update_contract.ToolUpdateIdle(state="idle")
                view = self._view
        return view.view if isinstance(view, _Failed) else view

    def start(self, port: int) -> tool_update_contract.ToolUpdate:
        """Zaczyna aktualizację w tle i od razu zwraca jej pierwszy krok; ``Refusal``, gdy coś trwa.

        ``port`` to port tego Centrum: na nim opiekun startuje nową wersję.
        """

        clone = self._clone()
        self._runs.begin_update()
        before = self._commit()
        self._log.update_started(before=before)
        first = tool_update_contract.ToolUpdateRunning(state="running", step="fetching")
        with self._lock:
            self._view = first
        threading.Thread(target=self._update, args=(clone, before, port), name=UPDATE_THREAD, daemon=True).start()
        return first

    def _after_restart(self) -> None:
        """Wynik od opiekuna ponownego startu: do dziennika i do karty, raz, bez czekania na sieć.

        „ok” przy działającym commicie innym niż „po” to porażka nieoczekiwana: nowa wersja nie działa (#490). Porażkę
        z pliku zapisał opiekun albo skrót po cofnięciu klonu do „przed”, więc przy działającym commicie innym niż
        „przed” jest stara: dziennik ją zapisuje, a karta jej nie pokazuje (#725). Wynik, który dziennik już zgłosił,
        albo wynik starszej Aktualizacji (``CentrumLog.update_awaits``) Centrum pomija, bo dysk mógł nie dać usunąć jego
        pliku (#491). Po porażce (np. cofnięcie nowej wersji) skrzynkę Zgłoszeń pyta w tle uchwyt Zgłoszenia: start
        Centrum na nią nie czeka.
        """

        result = read_result(self._result_file)
        if result is None:
            return
        running = self._commit()
        if result.code != UPDATED and running is not None and result.before is not None and result.before != running:
            self._log.update_result_stale(result=result.code, before=result.before, after=result.after)
            with suppress(OSError):  # następny start zastaje ten sam stary wynik i znów go pomija
                self._result_file.unlink()
            return
        if result.code == UPDATED and running is not None and running != result.after:
            result = replace(result, code=UNEXPECTED)
        if not self._log.update_awaits(result=result.code, before=result.before, after=result.after):
            with suppress(OSError):  # dziennik już wie, że ten wynik nie jest nowy
                self._result_file.unlink()
            return
        self._finished(result)
        try:
            self._result_file.unlink(missing_ok=True)
        except OSError as failure:  # następny start zastaje ten wynik w dzienniku i go pomija, jeśli nie było nowego kliknięcia
            self._log.update_result_kept(failure)
        self._view = _view_of(result) or self._failed(result, after_restart=True)

    def _update(self, clone: ToolClone, before: str | None, port: int) -> None:
        work = Path(tempfile.mkdtemp(prefix="centrum-aktualizacja-"))
        restarting = False
        view: tool_update_contract.ToolUpdate | _Failed | None = None
        newest: GitHubReleases | None = None
        try:
            result, guardian = self._result(clone, before, work)
            if result.before is None:  # bez Gita commit zna tylko Centrum
                result = replace(result, before=before)
            # Przed ponownym startem: wynik w pliku opiekuna nie niesie pominiętych Wydań.
            if result.skipped:
                self._log.update_skipped_releases(tags=result.skipped)
            if result.code == UPDATED and result.after is not None and guardian is not None:
                restart = Restart(
                    port, result.before, result.after, clone.root, self._result_file, result.installed, work
                )
                restarting = self._restart(clone, restart, guardian)
                if not restarting:
                    result = self._moved_back(clone, result)
            if not restarting:
                self._finished(result)
                view = _view_of(result)
                if isinstance(view, tool_update_contract.ToolUpdateUpToDate):
                    newest = self._release()
                if view is None:
                    failed = self._failed(result, after_restart=False)
                    # Po pierwszym „failed” karta nie czyta już stanu, więc dostaje go po odpowiedzi skrzynki.
                    failed.report.wait_for_box()
                    view = failed
        finally:
            if not restarting:
                shutil.rmtree(work, ignore_errors=True)
                # Karta widzi wynik dopiero z wolnym miejscem „jedno naraz”, żeby „jeszcze raz” nie dostało 409;
                # pod blokadą widoku, żeby następne kliknięcie nie zobaczyło po swoim starcie tego wyniku.
                with self._lock:
                    self._runs.end_update()
                    if view is not None:
                        self._view, self._up_to_date_with = view, newest

    def _result(self, clone: ToolClone, before: str | None, work: Path) -> tuple[UpdateResult, Path | None]:
        try:
            # Opiekun działa z kopii sprzed aktualizacji, więc kopia powstaje, zanim klon się zmieni.
            guardian = restart_guardian.prepare(work)
            return clone.update(self._show_step), guardian
        except Exception as failure:
            self._log.unexpected_failure(failure, where="aktualizacja narzędzia")
            return UpdateResult(UNEXPECTED, before, None), None

    def _restart(self, clone: ToolClone, restart: Restart, guardian: Path) -> bool:
        """Uruchamia opiekuna i zamyka Centrum; ``False``, gdy opiekun nie wystartował (Centrum działa dalej)."""

        try:
            with clone.leased_to_guardian():
                with self._lock:
                    self._view = tool_update_contract.ToolUpdateRunning(state="running", step="restarting")
                self._guardian(guardian, restart)
        except Exception as failure:
            self._log.unexpected_failure(failure, where="ponowny start po aktualizacji")
            return False
        self._shutdown.close_for_update()
        return True

    def _moved_back(self, clone: ToolClone, result: UpdateResult) -> UpdateResult:
        """Bez opiekuna nowa wersja nie wystartuje, a stary kod działałby na nowych plikach: klon wraca sprzed kliknięcia.

        Wynik to porażka nieoczekiwana, a gdy nie uda się cofnięcie, porażka cofnięcia.
        """

        try:
            clone.roll_back()
        except Exception as failure:
            self._log.unexpected_failure(failure, where="cofnięcie aktualizacji")
            return replace(result, code=ROLLBACK_FAILED)
        return replace(result, code=UNEXPECTED)

    def _finished(self, result: UpdateResult) -> None:
        self._log.update_finished(
            result=result.code, before=result.before, after=result.after, installed=result.installed
        )

    def _failed(self, result: UpdateResult, *, after_restart: bool) -> _Failed:
        """Komunikat porażki z podglądem Zgłoszenia; ``aktualizacja-koniec`` jest już w dzienniku, więc podgląd go ma."""

        failure = update_messages.UpdateFailure.of(result.code)
        source = UpdateReport.of(result, failure.message, self._log)
        report = self._reports.handle(source.fingerprint)
        return _Failed(
            common_contract.Message.of(failure.message),
            failure.next_action,
            report,
            report.prepare(source),
            after_restart,
        )

    def send_report(self) -> diagnosis_contract.ReportState:
        """„Wyślij do Maksa” przy nieudanej aktualizacji; ``Refusal``, gdy ostatnia aktualizacja nie zawiodła."""

        with self._lock:
            failed = self._view
        if not isinstance(failed, _Failed):
            raise refusal.no_failed_update()
        return failed.report.send()

    def _show_step(self, step: Step) -> None:
        with self._lock:
            self._view = tool_update_contract.ToolUpdateRunning(state="running", step=step)


@dataclass(frozen=True)
class _Failed:
    """Nieudana Aktualizacja narzędzia: Komunikat, co dalej i jej Zgłoszenie z zamrożonym podglądem ``draft``."""

    message: common_contract.Message
    next_action: update_messages.NextAction
    report: ReportHandle
    draft: diagnosis_contract.ReportDraft
    after_restart: bool

    @property
    def view(self) -> tool_update_contract.ToolUpdateFailed:
        return tool_update_contract.ToolUpdateFailed(
            state="failed",
            message=self.message,
            next_action=self.next_action,
            report=self.report.state,
            draft=self.draft,
            after_restart=self.after_restart,
        )


def _view_of(result: UpdateResult) -> tool_update_contract.ToolUpdate | None:
    """Widok udanej aktualizacji albo ``None`` przy porażce."""

    if result.code == UPDATED:
        return tool_update_contract.ToolUpdateUpdated(state="updated")
    if result.code == UP_TO_DATE:
        return tool_update_contract.ToolUpdateUpToDate(state="up_to_date")
    return None


def tool_update_router(updates: ToolUpdates) -> APIRouter:
    router = APIRouter(prefix="/api/tool-update", tags=["aktualizacja"])

    @router.post("", operation_id="startToolUpdate", status_code=202, responses={409: {"model": common_contract.Problem}})
    def start(request: Request) -> tool_update_contract.ToolUpdate:
        # ASGI daje ``server`` opcjonalnie, a gniazdo bez portu TCP jako ``(ścieżka, None)``.
        match request.scope.get("server"):
            case (str(), int(port)):
                return updates.start(port)
            case _:
                raise refusal.update_without_port()

    @router.get("", operation_id="getToolUpdate")
    def current() -> tool_update_contract.ToolUpdate:
        return updates.current()

    @router.post("/report", operation_id="reportToolUpdate", responses={409: {"model": common_contract.Problem}})
    def send_report() -> diagnosis_contract.ReportState:
        return updates.send_report()

    return router
