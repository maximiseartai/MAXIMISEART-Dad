"""Karty Uruchomień z Logów Uruchomienia (ADR 0017): ostatnie Uruchomienie po starcie Centrum i karta wiersza Historii.

Karty czytają pliki z dysku tylko przez Logi na dysku (``logs_disk``): plik ostatniego startu, w którym Centrum przy
każdym starcie Uruchomienia zapisuje jego bezpieczne fakty, i pliki Logów Uruchomienia. Po starcie Centrum ostatnie
Uruchomienie to ten start: gdy ma plik Logów, jego karta wraca z Logów. Gdy go nie ma, a Historia ma jego wiersz
(pierwszy wiersz procesu od jego startu, także jeszcze bez identyfikatora), Centrum zamknęło się po zapisie rekordu
metryk, a przed zapisem Logów, więc karta pokazuje wynik z Historii. Gdy nie ma ani Logów, ani wiersza Historii, to
Urwane Uruchomienie (Centrum zamknęło się w jego trakcie), bo Logi powstają przed końcem każdego Uruchomienia, także
przy Zatrzymaniu. Na końcu Uruchomienia ten moduł niczego nie zapisuje, więc nie ma kolejności względem działań po
wyniku.

Urwana Wycena w efenix ma Logi Urwanego Uruchomienia, które start Centrum zamknął z jej dziennika (``run_comments``,
#845), zanim karta ostatniego Uruchomienia przeczyta Logi (``LeftBehindClosed``): jej karta po starcie to dalej karta
Urwanego Uruchomienia, z liczbą zleceń skończonych przed zamknięciem Centrum z każdym wynikiem. Takie Logi nie dają karty wiersza Historii (Urwane Uruchomienie nie ma wiersza Historii) ani karty
zakończonego Uruchomienia, z której powstaje Powiadomienie, ani karty ostatniego Uporządkowania INTERMAX.

Karta z Logów niesie tylko to, co w nich jest: Komunikaty w trzech częściach, podsumowanie, etapy, sposób
zakończenia i Rodzaj Zatrzymania. Diagnozy i Zgłoszenia nie ma: żyją tylko przy Zatrzymaniu bieżącego
Uruchomienia tej pracy Centrum. Plik startu ma te same fakty co linia ``uruchomienie-start`` dziennika Centrum i
identyfikator Uruchomienia, więc reguła prywatności Logów obowiązuje bez zmian.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import metrics as metrics_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.logs_disk import Found, LogsOnDisk, Missing, Refused, Unreadable
from rozliczenia.centrum.run_comments import LeftBehindClosed
from rozliczenia.centrum.run_logs import RunLog, StartFacts
from rozliczenia.centrum.run_view import order_counts
from rozliczenia.centrum.runs import stop_note, verdict
from rozliczenia.efenix_pricing import OrderKind

_INTERRUPTED: Final = "Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku."
_ORDERS_TITLE: Final = "Zlecenia przed zamknięciem Centrum"
_PREVIEW_ADVICE: Final = "Podgląd niczego nie zapisał. Uruchom go ponownie."
_WRITE_ADVICE: Final = "Uruchom ponownie. Pliki okresu, które zdążyły powstać, Centrum zostawi i powie, co z nimi zrobić."

History = Callable[[], Iterable[metrics_contract.ProcessRun]]
"""Wiersze Historii z plików metryk; ``OSError``: plików nie da się odczytać."""


@dataclass(frozen=True)
class LoggedRun:
    """Zakończone Uruchomienie z jego Logów: karta, koniec i liczba zleceń Wyceny w efenix z każdym wynikiem (``None``:
    inny proces albo Wycena bez podsumowania, np. po Zatrzymaniu przed pierwszym zleceniem)."""

    card: runs_contract.RunRestored
    ended_at: datetime
    orders: Counter[OrderKind] | None


class RunCards:
    def __init__(self, disk: LogsOnDisk, history: History) -> None:
        self._disk = disk
        self._history = history
        self._ended = disk.viewed(self._ended_of)

    def last(self, closed: LeftBehindClosed) -> runs_contract.PastRun | None:
        """Ostatnie Uruchomienie sprzed tego startu Centrum; ``None``: żadnego albo nie da się go odczytać. ``closed``:
        start Centrum zamknął już dzienniki Wyceny, więc Urwana Wycena ma tu swoje Logi Urwanego Uruchomienia. Logi,
        które są, ale są nieczytelne, to też ``None``: wynik był, tylko go nie znamy, więc to nie Urwane Uruchomienie."""

        started = self._disk.last_start()
        if started is None:
            return None
        match self._disk.logs(started.run_id):
            case Missing():
                return self._recorded(started) or _interrupted(started, None)
            case Unreadable() | Refused():
                return None
            case Found(logs=record) if record.ending == "interrupted":
                return _interrupted(started, _orders(record))
            case Found(logs=record):
                return self._restored(record)

    def card(self, run_id: str) -> runs_contract.RunCard:
        """Karta Uruchomienia ``run_id`` z jego Logów; ``missing`` bez pliku Logów, z plikiem, którego nie da się odczytać,
        i z Logami Urwanego Uruchomienia, które nie ma wiersza Historii."""

        match self._disk.logs(run_id):
            case Found(logs=record) if record.ending != "interrupted":
                return self._restored(record)
            case _:
                return runs_contract.RunCardMissing(state="missing")

    def latest(self, process: common_contract.ProcessKey) -> runs_contract.RunRestored | None:
        """Karta ostatniego Uruchomienia procesu ``process`` z Logów (``LogsOnDisk.newest``); ``None``: żadnego, nie da się
        go odczytać albo to Logi Urwanego Uruchomienia, które nie mają karty wyniku."""

        record = self._disk.newest(process)
        return None if record is None or record.ending == "interrupted" else self._restored(record)

    def ended(self, process: common_contract.ProcessKey) -> list[LoggedRun]:
        """Zakończone Uruchomienia procesu ``process`` z Logów, od najnowszego; pliki, których nie da się odczytać, pomija."""

        return self._ended.of(process)

    def _ended_of(self, record: RunLog) -> LoggedRun | None:
        """Zakończone Uruchomienie z Logów ``record``; ``None`` dla Urwanego. Po Zatrzymaniu Logi mają zlecenia sprzed
        niego, ale Powiadomienie liczy zlecenia tylko Wyceny z podsumowaniem."""

        if record.ending == "interrupted":
            return None
        orders = (
            None
            if record.efenix_orders is None or record.summary is None
            else Counter(order.outcome for order in record.efenix_orders)
        )
        return LoggedRun(card=self._restored(record), ended_at=record.ended_at, orders=orders)

    def _restored(self, record: RunLog) -> runs_contract.RunRestored:
        ending, result = record.ending, record.result
        assert ending != "interrupted" and result is not None, "Logi Urwanego Uruchomienia nie mają karty wyniku"
        declaration = declaration_of(record.process)
        info = declaration.run_info(
            run_id=record.run_id, period=record.period, mode=record.mode, pricing=record.pricing
        )
        headline, next_action = verdict(
            ending=ending,
            stop_kind=record.stop_kind,
            result=result,
            dry_run=info.mode.dry_run,
            view=declaration.view,
        )
        messages = {
            kind: [
                message.shown()
                for message in record.messages
                if message.kind == kind
            ]
            for kind in ("stop", "warning")
        }
        return runs_contract.RunRestored(
            state="restored",
            run=info,
            started_at=record.started_at,
            phases=[phase.progress for phase in record.phases],
            result=runs_contract.LoggedOutcome(
                result=result,
                headline=headline,
                ending=ending,
                next_action=next_action,
                stop_kind=record.stop_kind,
                stop_note=stop_note(record.stop_kind),
                stops=messages["stop"],
                warnings=messages["warning"],
                technical_notes=record.technical_notes,
                summary=record.summary,
                collective_file_prepared=declaration.view.collective_file_prepared(
                    ending=ending, dry_run=info.mode.dry_run
                ),
            ),
        )

    def _recorded(self, started: StartFacts) -> runs_contract.RunRecorded | None:
        """Karta z wiersza Historii Uruchomienia bez Logów; ``None``: Historia go nie ma albo jej nie da się odczytać.

        Wiersz Uruchomienia to najwcześniejszy wiersz tego procesu ze startem od startu Uruchomienia (reguła
        ``CentrumRuns.remember``), więc karta go znajduje także wtedy, gdy nie ma jeszcze identyfikatora. Wcześniejsze
        Uruchomienia startowały przed nim, bo Centrum prowadzi jedno naraz. Uruchomienie spoza Centrum po starcie
        Urwanego Uruchomienia dałoby mu swój wynik; jak w ``remember`` to rzadkie.

        Bez ``stop_kind`` sposób zakończenia nie zmienia tytułu ani akcji. Wiersz Historii nie mówi, czy Zatrzymanie
        przyszło po silniku (``after_engine``), więc po zapisie karta proponuje ponowne Uruchomienie, nie otwarcie
        pliku; ponowne Uruchomienie zostawia pliki, które powstały, i mówi, co z nimi zrobić.
        """

        row = self._row(started.process, started.started_at)
        if row is None:
            return None
        declaration = declaration_of(started.process)
        info = declaration.run_info(
            run_id=started.run_id, period=started.period, mode=started.mode, pricing=started.pricing
        )
        headline, next_action = verdict(
            ending="stop",
            stop_kind=row.stop_kind,
            result=row.result,
            dry_run=info.mode.dry_run,
            view=declaration.view,
        )
        return runs_contract.RunRecorded(
            state="recorded",
            run=info,
            started_at=row.started_at,
            result=row.result,
            headline=headline,
            next_action=next_action,
        )

    def _row(self, process: common_contract.ProcessKey, started_at: datetime) -> metrics_contract.ProcessRun | None:
        try:
            rows = [run for run in self._history() if run.process == process and run.started_at >= started_at]
        except OSError:
            return None
        return min(rows, key=lambda run: run.started_at, default=None)


def _orders(record: RunLog) -> runs_contract.CountGroup | None:
    """Liczba zleceń Wyceny w efenix z Logów Urwanego Uruchomienia z każdym wynikiem; ``None`` bez śladu zleceń."""

    if record.efenix_orders is None:
        return None
    return runs_contract.CountGroup(
        title=_ORDERS_TITLE,
        counts=order_counts(Counter(order.outcome for order in record.efenix_orders)),
        zero_warns=False,
    )


def _interrupted(started: StartFacts, orders: runs_contract.CountGroup | None) -> runs_contract.RunInterrupted:
    info = declaration_of(started.process).run_info(
        run_id=started.run_id, period=started.period, mode=started.mode, pricing=started.pricing
    )
    return runs_contract.RunInterrupted(
        state="interrupted",
        run=info,
        started_at=started.started_at,
        advice=_interrupted_advice(info.title, info.period, dry_run=info.mode.dry_run),
        orders=orders,
    )


def _interrupted_advice(title: str, period: str, *, dry_run: bool) -> common_contract.Message:
    return common_contract.Message(
        what=_INTERRUPTED,
        where=f"{title}, okres {period}",
        action=_PREVIEW_ADVICE if dry_run else _WRITE_ADVICE,
    )


def run_cards_router(cards: RunCards) -> APIRouter:
    """Trasa karty Uruchomienia; brak karty to zwykła odpowiedź (``missing``), nie 404, bo przeglądarka nie odróżniłaby
    go od porażki odczytu."""

    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.get("/{run_id}/card", operation_id="getRunCard")
    def card(run_id: str) -> runs_contract.RunCard:
        return cards.card(run_id)

    return router
