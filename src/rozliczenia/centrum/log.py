from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
import threading
from typing import Literal, final

from rozliczenia.centrum.tool_update import UPDATED
from rozliczenia.wall_clock import local_now

VIEW_TIMING_EVENT = "pomiar"
FOR_LOGS_FILE = "dziennik-centrum-do-logow.log"
MAX_FOR_LOGS = 2000
UNEXPECTED_FAILURE_EVENT = "nieoczekiwany-wyjatek"
MAX_VIEW_TIMINGS = 200
_UPDATE = "aktualizacja"
_UPDATE_STARTED = "aktualizacja-start"
_UPDATE_FINISHED = "aktualizacja-koniec"
_NO_PERIOD = "bez-okresu"
WaitingCause = Literal["brak-klucza", "brak-sieci", "odmowa", "odmowa-tresci", "odmowa-archiwum"]
SettlementMailFailure = Literal["wyslane-bez-odczytu", "plik", "haslo-odrzucone", "brak-sieci", "odmowa-wysylki"]

ReminderFailure = Literal[
    "bez-wdrozenia",
    "bez-ustawien",
    "bez-dostepu",
    "bez-adresow",
    "pamiec-wpisania",
    "okresy",
    "intermax",
    "brak-sieci",
    "haslo-odrzucone",
    "odmowa-wysylki",
    "zapis-por",
    "plik-bez-odczytu",
]
SettingsUnreadableCause = Literal["dostep", "historia"]
SettingsExternalResult = Literal["zapisano", "odrzucono", "bez-zapisu"]
SettingsReleaseResult = Literal[
    "zastosowano", "bez-zmian", "odrzucono", "pozniej", "bez-zapisu", "bez-pamieci", "bez-historii"
]


class CentrumLog:
    def __init__(self, path: Path, *, append: Callable[[str], None] | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._view_timings = 0
        self._append = self._to_file if append is None else append
        self._held: list[str] | None = None
        self._hold_lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._path.parent

    def hold_until_started(self) -> None:
        with self._hold_lock:
            self._held = []

    def started(self, *, port: int, version: str, console: bool) -> None:
        with self._hold_lock:
            self._append(self._line("start", port=port, wersja=version, konsola="tak" if console else "nie"))
            self._flush_held()

    def release_held(self) -> None:
        with self._hold_lock:
            self._flush_held()

    def _flush_held(self) -> None:
        held, self._held = self._held or [], None
        for line in held:
            self._append(line)

    def already_running(self, *, port: int) -> None:
        self._write("juz-dziala", port=port)

    def start_failed(self, code: str, *, port: int) -> None:
        self._write("blad-startu", kod=code, port=port)

    def shutdown_requested(self) -> None:
        self._write("zamkniecie", z="karta Centrum")

    def shutdown_for_update(self) -> None:
        self._write("zamkniecie", z=_UPDATE)

    def stopped(self, *, port: int) -> None:
        self._write("stop", port=port)

    def run_started(self, *, process: str, mode: str, period: str) -> None:
        self._write("uruchomienie-start", proces=process, tryb=mode, okres=period)

    def run_finished(self, *, process: str, mode: str, period: str, result: str, ending: str) -> None:
        self._write("uruchomienie-koniec", proces=process, tryb=mode, okres=period, wynik=result, koniec=ending)

    def update_started(self, *, before: str | None) -> None:
        self._write(_UPDATE_STARTED, przed=before or "-")

    def update_finished(self, *, result: str, before: str | None, after: str | None, installed: bool) -> None:
        self._write(
            _UPDATE_FINISHED,
            wynik=result,
            przed=before or "-",
            po=after or "-",
            biblioteki="tak" if installed else "nie",
        )

    def update_result_kept(self, failure: OSError) -> None:
        self._write("aktualizacja-wynik-zostaje", typ=type(failure).__name__)

    def update_result_stale(self, *, result: str, before: str, after: str | None) -> None:
        self._write("aktualizacja-wynik-stary", wynik=result, przed=before, po=after or "-")

    def update_awaits(self, *, result: str, before: str | None, after: str | None) -> bool:
        try:
            with self._lock:
                lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return True
        updates = [line for line in lines if event_of(line) in (_UPDATE_STARTED, _UPDATE_FINISHED)]
        if all(event_of(line) != _UPDATE_STARTED for line in updates):
            return True
        last = updates[-1]
        facts = _facts(last)
        same_before = facts.get("przed") == (before or "-")
        if event_of(last) == _UPDATE_STARTED:
            return same_before
        return same_before and facts.get("po") == (after or "-") and facts.get("wynik") == UPDATED != result

    def update_skipped_releases(self, *, tags: tuple[str, ...]) -> None:
        self._write("aktualizacja-pominiete-wydania", tagi=",".join(tags))

    def dad_actions_unavailable(self, failure: OSError) -> None:
        self._write("dzialania-taty-niedostepne", typ=type(failure).__name__)

    def pricing_journal_unavailable(self, failure: OSError, *, where: Literal["wpis", "start"]) -> None:
        self._write("dziennik-wyceny-niedostepny", typ=type(failure).__name__, miejsce=where)

    def settings_unreadable(self, *, cause: SettingsUnreadableCause) -> None:
        self._write("ustawienia-bez-zapisu", przyczyna=cause)

    def settings_changed(self, *, file: str, keys: Sequence[str], source: str) -> None:
        self._write("ustawienia-zmiana", plik=file, klucze=",".join(keys), zrodlo=source)

    def settings_external(self, *, file: str, result: SettingsExternalResult) -> None:
        self._write("ustawienia-spoza", plik=file, wynik=result)

    def settings_release(self, *, change: str, result: SettingsReleaseResult) -> None:
        self._write("ustawienia-wydanie", zmiana=change, wynik=result)

    def settings_bad(self, *, file: str, field: str) -> None:
        self._write("ustawienia-zle", plik=file, pole=field)

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        self._write(UNEXPECTED_FAILURE_EVENT, typ=type(failure).__name__, miejsce=where)

    def fill_unreadable(self, *, period: str, cause: str, excel_lock: str, failure: str) -> None:
        self._write("uzupelnienie-odczyt-nieudany", okres=period, przyczyna=cause, excel=excel_lock, typ=failure)

    def diagnosed(self, *, process: str, period: str, cause: str) -> None:
        self._write("diagnoza", proces=process, okres=period, przyczyna=cause)

    def box_post_queued(self, *, label: str, period: str | None) -> None:
        self._write("skrzynka-w-kolejce", etykieta=label, okres=_period(period))

    def box_post_sent(self, *, label: str, period: str | None, number: int) -> None:
        self._write("skrzynka-wyslano", etykieta=label, okres=_period(period), numer=number)

    def box_post_waiting(
        self, *, label: str, period: str | None, cause: WaitingCause, file: str | None = None
    ) -> None:
        named = {} if file is None else {"plik": file}
        self._write("skrzynka-czeka", etykieta=label, okres=_period(period), przyczyna=cause, **named)

    def box_post_archived(self, *, label: str, period: str | None) -> None:
        self._write("skrzynka-archiwum", etykieta=label, okres=_period(period))

    def box_post_dropped(self, *, label: str, file: str, number: int) -> None:
        self._write("skrzynka-porzucono", etykieta=label, plik=file, numer=number)

    def box_post_unreadable(self, *, file: str) -> None:
        self._write("skrzynka-nieczytelny", plik=file)

    def box_notes_unavailable(self, failure: OSError) -> None:
        self._write("skrzynka-zapisy-niedostepne", typ=type(failure).__name__)

    def reminder_sent(self, *, day: str, pora: str) -> None:
        self._write("przypomnienie-wyslane", dzien=day, pora=pora)

    def reminders_failed(self, *, cause: ReminderFailure, failure: str | None = None, file: str | None = None) -> None:
        named = ({} if failure is None else {"typ": failure}) | ({} if file is None else {"plik": file})
        self._write("przypomnienia-porazka", przyczyna=cause, **named)

    def settlement_mailed(self, *, period: str) -> None:
        self._write("rozliczenie-wyslane", okres=period)

    def settlement_mail_failed(self, *, period: str, cause: SettlementMailFailure, failure: str | None = None) -> None:
        self._write("rozliczenie-niewyslane", okres=period, przyczyna=cause, **({} if failure is None else {"typ": failure}))

    def view_timed(
        self,
        *,
        view: str,
        page: str,
        ready_ms: int,
        fcp_ms: int | None,
        skeleton_ms: int,
        requests: Sequence[tuple[str, int, int | None]],
    ) -> None:
        with self._lock:
            if self._view_timings >= MAX_VIEW_TIMINGS:
                return
            self._view_timings += 1
        facts: dict[str, str | int] = {"widok": view, "strona": page, "gotowe_ms": ready_ms}
        if fcp_ms is not None:
            facts["fcp_ms"] = fcp_ms
        facts["szkielet_ms"] = skeleton_ms
        if requests:
            facts["zapytania"] = ",".join(
                f"{operation}:{browser_ms}/{'-' if server_ms is None else server_ms}"
                for operation, browser_ms, server_ms in requests
            )
        self._write(VIEW_TIMING_EVENT, **facts)

    def recent(self, limit: int) -> list[str]:
        try:
            with self._lock:
                lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        starts = [index for index, line in enumerate(lines) if event_of(line) == "start"]
        session = lines[starts[-1] :] if starts else lines
        return [line for line in session if event_of(line) != VIEW_TIMING_EVENT][-limit:]

    @final
    def _write(self, event: str, **facts: str | int) -> None:
        line = self._line(event, **facts)
        with self._hold_lock:
            if self._held is not None:
                self._held.append(line)
                return
        self._append(line)

    @final
    @staticmethod
    def _line(event: str, **facts: str | int) -> str:
        moment = local_now().isoformat(timespec="seconds")
        return " ".join([moment, event, *(f"{key}={_quoted(value)}" for key, value in facts.items())])

    def take_for_logs(self) -> tuple[list[str], int]:
        path = self._path.with_name(FOR_LOGS_FILE)
        with self._lock:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                return [], 0
            with suppress(OSError):
                path.write_text("", encoding="utf-8")
        kept = lines[-MAX_FOR_LOGS:]
        return kept, len(lines) - len(kept)

    @final
    def _to_file(self, line: str) -> None:
        targets = [self._path] if event_of(line) == VIEW_TIMING_EVENT else [self._path, self._path.with_name(FOR_LOGS_FILE)]
        with self._lock:
            for target in targets:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("a", encoding="utf-8") as log:
                        log.write(line + "\n")
                except OSError:
                    pass


def event_of(line: str) -> str:
    fields = line.split(" ", 2)
    return fields[1] if len(fields) > 1 else ""


def _facts(line: str) -> dict[str, str]:
    return {key: value for key, _, value in (field.partition("=") for field in line.split(" ")[2:])}


def _quoted(value: str | int) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text


def _period(period: str | None) -> str:
    return period or _NO_PERIOD
