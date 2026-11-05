"""Karty Uruchomień z Logów Uruchomienia (ADR 0017): ostatnie Uruchomienie po starcie Centrum i karta wiersza Historii.

Przy każdym starcie Uruchomienia Centrum zapisuje jego bezpieczne fakty (identyfikator, proces, tryb, okres, start)
w jednym pliku obok dziennika, ``ostatnie-uruchomienie.json``, nadpisywanym przy następnym starcie i nigdy
nieusuwanym. Po starcie Centrum ostatnie Uruchomienie to ten start: gdy ma plik Logów, jego karta wraca z Logów.
Gdy go nie ma, a Historia ma jego wiersz (pierwszy wiersz procesu od jego startu, także jeszcze bez identyfikatora),
Centrum zamknęło się po zapisie rekordu metryk, a przed zapisem Logów, więc karta pokazuje wynik z Historii. Gdy nie
ma ani Logów, ani wiersza Historii, to Urwane Uruchomienie (Centrum zamknęło się w jego trakcie), bo Logi powstają
przed końcem każdego Uruchomienia, także przy Zatrzymaniu. Na końcu Uruchomienia ten moduł niczego nie zapisuje,
więc nie ma kolejności względem działań po wyniku.

Urwana Wycena w efenix ma Logi Urwanego Uruchomienia, które start Centrum zamknął z jej dziennika (``pricing_journal``,
#845): jej karta po starcie to dalej karta Urwanego Uruchomienia, z liczbą zleceń skończonych przed zamknięciem Centrum
z każdym wynikiem. Takie Logi nie dają karty wiersza Historii (Urwane Uruchomienie nie ma wiersza Historii) ani karty
zakończonego Uruchomienia, z której powstaje Powiadomienie.

Karta z Logów niesie tylko to, co w nich jest: Komunikaty w trzech częściach, podsumowanie, etapy, sposób
zakończenia i Rodzaj Zatrzymania. Tytuł i akcję wylicza ta sama reguła co na żywo (``runs.verdict``), a tytuł
procesu i Gotowość jego wpis w katalogu procesów, tak jak przy starcie. Diagnozy i Zgłoszenia nie ma: żyją tylko przy Zatrzymaniu bieżącego
Uruchomienia tej pracy Centrum. Plik startu ma te same fakty co linia ``uruchomienie-start`` dziennika Centrum i
identyfikator Uruchomienia, więc reguła prywatności Logów obowiązuje bez zmian.

Zakończone Uruchomienia procesu (``RunCards.ended``) to karty z Logów wszystkich jego Uruchomień, od najnowszego, z
końcem i liczbą zleceń Wyceny w efenix z każdym wynikiem; z nich powstaje Powiadomienie o zakończonej Wycenie w efenix.
Plik Logów zmienia się tylko przy Diagnozie, więc odczyt każdego pliku zostaje w pamięci, dopóki plik się nie zmieni.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import threading
from typing import Final, Literal, TypeVar

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.run_logs import OrderOutcome, RunLog
from rozliczenia.centrum.runs import verdict

LAST_STARTED_FILE: Final = "ostatnie-uruchomienie.json"
# Identyfikator Uruchomienia z Centrum (``uuid4().hex``); inny nie ma Logów, więc nie dotyka dysku.
_RUN_ID: Final = re.compile(r"[0-9a-f]{32}")

_INTERRUPTED: Final = "Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku."
_ORDERS_TITLE: Final = "Zlecenia przed zamknięciem Centrum"
# Wynik zlecenia Wyceny w efenix z Logów i jego nazwa na karcie, w kolejności karty na żywo.
_ORDER_LABELS: Final[dict[OrderOutcome, str]] = {
    "gotowe": "Gotowe do przekazania",
    "rozliczone": "Rozliczone",
    "błąd": "Błędy zleceń",
    "ostrzeżenie Emmetta": "Ostrzeżenia Emmetta",
}
_PREVIEW_ADVICE: Final = "Podgląd niczego nie zapisał. Uruchom go ponownie."
_WRITE_ADVICE: Final = "Uruchom ponownie. Pliki okresu, które zdążyły powstać, Centrum zostawi i powie, co z nimi zrobić."

ModelT = TypeVar("ModelT", bound=BaseModel)

History = Callable[[], Iterable[contract.ProcessRun]]
"""Wiersze Historii z plików metryk; ``OSError``: plików nie da się odczytać."""


class StartedRun(BaseModel):
    """Plik ostatniego startu (schemat 1): te same fakty co nagłówek Logów Uruchomienia."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime


@dataclass(frozen=True)
class LoggedRun:
    """Zakończone Uruchomienie z jego Logów: karta, koniec i liczba zleceń Wyceny w efenix z każdym wynikiem (``None``:
    inny proces albo Wycena bez podsumowania, np. po Zatrzymaniu przed pierwszym zleceniem)."""

    card: contract.RunRestored
    ended_at: datetime
    orders: Counter[OrderOutcome] | None


class RunCards:
    """Karty Uruchomień z dysku: ostatnie Uruchomienie sprzed startu Centrum i karta po identyfikatorze.

    ``logs`` to katalog Logów Uruchomienia, ``last_started`` plik ostatniego startu, a ``history`` wiersze Historii.
    """

    def __init__(self, logs: Path, last_started: Path, history: History) -> None:
        self._logs = logs
        self._last_started = last_started
        self._history = history
        self._lock = threading.Lock()
        # Odczyt pliku Logów po nazwie, z jego czasem zmiany i rozmiarem; ``None``: pliku nie dało się odczytać.
        self._ended: dict[str, tuple[tuple[int, int], LoggedRun | None]] = {}

    def run_started(self, info: contract.RunInfo, started_at: datetime) -> None:
        started = StartedRun(
            schema_version=1,
            run_id=info.id,
            process=info.process,
            mode="podgląd" if info.dry_run else "zapis",
            period=info.period,
            started_at=started_at,
        )
        replace_atomically(self._last_started, started.model_dump_json(indent=2) + "\n")

    def last(self) -> contract.PastRun | None:
        """Ostatnie Uruchomienie sprzed tego startu Centrum; ``None``: żadnego albo nie da się go odczytać."""

        started = _read(self._last_started, StartedRun)
        if started is None:
            return None
        path = self._logged(started.run_id)
        if path is None:
            return self._recorded(started) or _interrupted(started, None)
        record = _read(path, RunLog)
        if record is None:
            # Logi są, ale nieczytelne: wynik był, tylko go nie znamy, więc to nie jest Urwane Uruchomienie.
            return None
        return _interrupted(started, _orders(record)) if record.ending == "interrupted" else self._restored(record)

    def card(self, run_id: str) -> contract.RunCard:
        """Karta Uruchomienia ``run_id`` z jego Logów; ``missing`` bez pliku Logów, z plikiem, którego nie da się odczytać,
        i z Logami Urwanego Uruchomienia, które nie ma wiersza Historii."""

        path = self._logged(run_id) if _RUN_ID.fullmatch(run_id) else None
        record = None if path is None else _read(path, RunLog)
        if record is None or record.ending == "interrupted":
            return contract.RunCardMissing(state="missing")
        return self._restored(record)

    def latest(self, process: contract.ProcessKey) -> contract.RunRestored | None:
        """Karta ostatniego Uruchomienia procesu ``process`` z Logów; ``None``: żadnego albo nie da się go odczytać.

        Nazwa pliku Logów zaczyna się sekundą startu w UTC, a po niej stoi klucz procesu, więc ostatnie pliki procesu
        są ostatnie w kolejności nazw; z tych z tej samej sekundy wygrywa późniejszy start w Logach.
        """

        try:
            names = sorted(path.name for path in self._logs.iterdir() if f"-{process}-" in path.name)
        except OSError:
            return None
        second = names[-1][:16] if names else None
        records = [_read(self._logs / name, RunLog) for name in names if name[:16] == second]
        read = [record for record in records if record is not None]
        return self._restored(max(read, key=lambda record: record.started_at)) if read else None

    def ended(self, process: contract.ProcessKey) -> list[LoggedRun]:
        """Zakończone Uruchomienia procesu ``process`` z Logów, od najnowszego; pliki, których nie da się odczytać, pomija."""

        try:
            paths = sorted((path for path in self._logs.iterdir() if f"-{process}-" in path.name), reverse=True)
        except OSError:
            return []
        with self._lock:
            ended = [self._ended_of(path) for path in paths]
        return [run for run in ended if run is not None]

    def _ended_of(self, path: Path) -> LoggedRun | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        version = (stat.st_mtime_ns, stat.st_size)
        known = self._ended.get(path.name)
        if known is not None and known[0] == version:
            return known[1]
        record = _read(path, RunLog)
        ended = None
        if record is not None and record.ending != "interrupted":
            # Po Zatrzymaniu Logi mają zlecenia sprzed niego, ale Powiadomienie liczy tylko Wycenę z podsumowaniem.
            orders = (
                None
                if record.efenix_orders is None or record.summary is None
                else Counter(order.outcome for order in record.efenix_orders)
            )
            ended = LoggedRun(card=self._restored(record), ended_at=record.ended_at, orders=orders)
        self._ended[path.name] = (version, ended)
        return ended

    def _logged(self, run_id: str) -> Path | None:
        """Plik Logów Uruchomienia ``run_id`` (nazwa kończy się identyfikatorem); ``None`` bez pliku albo katalogu."""

        suffix = f"-{run_id}.json"
        try:
            return next((path for path in self._logs.iterdir() if path.name.endswith(suffix)), None)
        except OSError:
            return None

    def _restored(self, record: RunLog) -> contract.RunRestored:
        """Karta z Logów Uruchomienia, które doszło do wyniku (każdy sposób zakończenia poza ``interrupted``)."""

        ending, result = record.ending, record.result
        assert ending != "interrupted" and result is not None, "Logi Urwanego Uruchomienia nie mają karty wyniku"
        declaration = declaration_of(record.process)
        info = declaration.run_info(run_id=record.run_id, period=record.period, dry_run=record.mode == "podgląd")
        headline, next_action = verdict(
            ending=ending,
            stop_kind=record.stop_kind,
            result=result,
            dry_run=info.dry_run,
            view=declaration.view,
        )
        messages = {
            kind: [
                contract.Message(what=message.what, where=message.where, action=message.action)
                for message in record.messages
                if message.kind == kind
            ]
            for kind in ("stop", "warning")
        }
        return contract.RunRestored(
            state="restored",
            run=info,
            started_at=record.started_at,
            phases=[phase.progress for phase in record.phases],
            result=contract.LoggedOutcome(
                result=result,
                headline=headline,
                ending=ending,
                next_action=next_action,
                stop_kind=record.stop_kind,
                stops=messages["stop"],
                warnings=messages["warning"],
                technical_notes=record.technical_notes,
                summary=record.summary,
            ),
        )

    def _recorded(self, started: StartedRun) -> contract.RunRecorded | None:
        """Karta z wiersza Historii Uruchomienia bez Logów; ``None``: Historia go nie ma albo jej nie da się odczytać.

        Wiersz Uruchomienia to najwcześniejszy wiersz tego procesu ze startem od startu Uruchomienia (reguła
        ``CentrumRuns.remember``), więc karta go znajduje także wtedy, gdy nie ma jeszcze identyfikatora. Wcześniejsze
        Uruchomienia startowały przed nim, bo Centrum prowadzi jedno naraz. Uruchomienie spoza Centrum po starcie
        Urwanego Uruchomienia dałoby mu swój wynik; jak w ``remember`` to rzadkie.
        """

        row = self._row(started.process, started.started_at)
        if row is None:
            return None
        declaration = declaration_of(started.process)
        info = declaration.run_info(run_id=started.run_id, period=started.period, dry_run=started.mode == "podgląd")
        # Bez ``stop_kind`` sposób zakończenia nie zmienia tytułu ani akcji. Wiersz Historii nie mówi, czy Zatrzymanie
        # przyszło po silniku (``after_engine``), więc po zapisie karta proponuje ponowne Uruchomienie, nie otwarcie
        # pliku; ponowne Uruchomienie zostawia pliki, które powstały, i mówi, co z nimi zrobić.
        headline, next_action = verdict(
            ending="stop",
            stop_kind=row.stop_kind,
            result=row.result,
            dry_run=info.dry_run,
            view=declaration.view,
        )
        return contract.RunRecorded(
            state="recorded",
            run=info,
            started_at=row.started_at,
            result=row.result,
            headline=headline,
            next_action=next_action,
        )

    def _row(self, process: contract.ProcessKey, started_at: datetime) -> contract.ProcessRun | None:
        """Wiersz Historii Uruchomienia ze startem ``started_at``: najwcześniejszy wiersz procesu od tej chwili; ``None``,
        gdy go nie ma albo Historii nie da się odczytać."""

        try:
            rows = [run for run in self._history() if run.process == process and run.started_at >= started_at]
        except OSError:
            return None
        return min(rows, key=lambda run: run.started_at, default=None)


def _orders(record: RunLog) -> contract.CountGroup | None:
    """Liczba zleceń Wyceny w efenix z Logów Urwanego Uruchomienia z każdym wynikiem; ``None`` bez śladu zleceń."""

    if record.efenix_orders is None:
        return None
    counted = Counter(order.outcome for order in record.efenix_orders)
    return contract.CountGroup(
        title=_ORDERS_TITLE,
        counts=[contract.Count(label=label, count=counted[outcome]) for outcome, label in _ORDER_LABELS.items()],
        zero_warns=False,
    )


def _interrupted(started: StartedRun, orders: contract.CountGroup | None) -> contract.RunInterrupted:
    info = declaration_of(started.process).run_info(
        run_id=started.run_id, period=started.period, dry_run=started.mode == "podgląd"
    )
    return contract.RunInterrupted(
        state="interrupted",
        run=info,
        started_at=started.started_at,
        advice=_interrupted_advice(info.title, info.period, dry_run=info.dry_run),
        orders=orders,
    )


def _interrupted_advice(title: str, period: str, *, dry_run: bool) -> contract.Message:
    """Komunikat karty Urwanego Uruchomienia procesu ``title`` w okresie ``period``, bez kodu."""

    return contract.Message(
        what=_INTERRUPTED,
        where=f"{title}, okres {period}",
        action=_PREVIEW_ADVICE if dry_run else _WRITE_ADVICE,
    )


def _read(path: Path, model: type[ModelT]) -> ModelT | None:
    """Model z pliku JSON; ``None``, gdy pliku nie ma albo nie da się go odczytać (zły JSON, schemat, kodowanie)."""

    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_cards_router(cards: RunCards) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    # Brak karty to zwykła odpowiedź, nie 404: przeglądarka nie odróżniłaby go od porażki odczytu.
    @router.get("/{run_id}/card", operation_id="getRunCard")
    def card(run_id: str) -> contract.RunCard:
        return cards.card(run_id)

    return router
