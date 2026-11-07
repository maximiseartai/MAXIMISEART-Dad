"""Dziennik Centrum: lokalny plik z bezpiecznymi faktami o pracy serwera.

Każdy wpis to jedna linia: czas, nazwa zdarzenia i fakty ``klucz=wartość``.
Do dziennika trafiają tylko fakty wybrane tutaj (port, wersja, kod komunikatu,
nazwa typu wyjątku), nigdy tekst wyjątku, ścieżki z folderu okresów ani treść
wierszy (ADR 0004), więc można go przekazać osobie utrzymującej narzędzie.
Moduł używa tylko biblioteki standardowej, bo zapisuje też błędy startu, gdy
brakuje zależności.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
import threading
from typing import Literal

from rozliczenia.centrum.tool_update import UPDATED

VIEW_TIMING_EVENT = "pomiar"
UNEXPECTED_FAILURE_EVENT = "nieoczekiwany-wyjatek"
# Pomiar przychodzi po każdym widoku, więc na jedno uruchomienie Centrum dziennik przyjmuje ich najwyżej
# tyle (spec #164, US29); kolejne przepadają po cichu, a wpisy o pracy serwera są zapisywane dalej.
MAX_VIEW_TIMINGS = 200
# Wpisy o Aktualizacji narzędzia i jej Zgłoszeniach mówią, skąd są, tym samym słowem.
_UPDATE = "aktualizacja"
# Zdarzenia, które piszą ``update_started`` i ``update_finished``, dla ``update_awaits``.
_UPDATE_STARTED = "aktualizacja-start"
_UPDATE_FINISHED = "aktualizacja-koniec"
# Okres wysyłki w tle z Uruchomienia, którego okresu nie ustalono.
_NO_PERIOD = "bez-okresu"
# Dlaczego wysyłka w tle czeka w kolejce Skrzynki Zgłoszeń; ``odmowa-tresci`` i ``odmowa-archiwum`` (Archiwum okresu
# nie przyjęło pliku wysyłki, której części już doszły) dotyczą tylko jednego pliku kolejki.
WaitingCause = Literal["brak-klucza", "brak-sieci", "odmowa", "odmowa-tresci", "odmowa-archiwum"]


class CentrumLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._view_timings = 0

    @property
    def directory(self) -> Path:
        """Katalog dziennika; obok niego leżą Logi Uruchomienia (ADR 0015)."""

        return self._path.parent

    def started(self, *, port: int, version: str, console: bool) -> None:
        self._write("start", port=port, wersja=version, konsola="tak" if console else "nie")

    def already_running(self, *, port: int) -> None:
        """Ponowne uruchomienie trafiło na działające Centrum tej samej wersji i tylko otworzyło kartę."""

        self._write("juz-dziala", port=port)

    def start_failed(self, code: str, *, port: int) -> None:
        self._write("blad-startu", kod=code, port=port)

    def shutdown_requested(self) -> None:
        self._write("zamkniecie", z="karta Centrum")

    def shutdown_for_update(self) -> None:
        """Centrum zamyka się samo po udanej Aktualizacji narzędzia, żeby wystartować w nowej wersji."""

        self._write("zamkniecie", z=_UPDATE)

    def stopped(self, *, port: int) -> None:
        self._write("stop", port=port)

    def run_started(self, *, process: str, mode: str, period: str) -> None:
        """Początek Uruchomienia procesu z Centrum: klucz procesu, tryb i token okresu."""

        self._write("uruchomienie-start", proces=process, tryb=mode, okres=period)

    def run_finished(self, *, process: str, mode: str, period: str, result: str, ending: str) -> None:
        """Koniec Uruchomienia procesu z Centrum: wynik i sposób zakończenia, bez linii komunikatu."""

        self._write("uruchomienie-koniec", proces=process, tryb=mode, okres=period, wynik=result, koniec=ending)

    def update_started(self, *, before: str | None) -> None:
        """Tata kliknął „Zaktualizuj narzędzie”; ``before`` to commit narzędzia przed aktualizacją."""

        self._write("aktualizacja-start", przed=before or "-")

    def update_finished(self, *, result: str, before: str | None, after: str | None, installed: bool) -> None:
        """Wynik Aktualizacji narzędzia (``ok``, ``AKTUALNA`` albo kod Komunikatu), bez wyjścia Gita ani pip."""

        self._write(
            "aktualizacja-koniec",
            wynik=result,
            przed=before or "-",
            po=after or "-",
            biblioteki="tak" if installed else "nie",
        )

    def update_result_kept(self, failure: OSError) -> None:
        """Dysk nie dał usunąć pliku wyniku Aktualizacji narzędzia po jej końcu w dzienniku; tylko nazwa typu błędu."""

        self._write("aktualizacja-wynik-zostaje", typ=type(failure).__name__)

    def update_result_stale(self, *, result: str, before: str, after: str | None) -> None:
        """Plik wyniku Aktualizacji narzędzia mówi o porażce z ``before``, a działa inna wersja: wynik jest stary (#725)."""

        self._write("aktualizacja-wynik-stary", wynik=result, przed=before, po=after or "-")

    def update_awaits(self, *, result: str, before: str | None, after: str | None) -> bool:
        """Czy wynik Aktualizacji narzędzia (kod ``result``, commity ``before`` i ``after``) ma jeszcze trafić do dziennika.

        Patrzy na cały dziennik, nie tylko od ostatniego startu. Ma trafić, gdy
        ostatni wpis Aktualizacji to ``aktualizacja-start`` z commitem
        ``before`` albo ``aktualizacja-koniec`` z wynikiem „ok”, tymi samymi
        commitami i innym ``result`` (nowa wersja zapisała „ok”, a potem nie
        odpowiedziała na czas, więc opiekun ją cofnął). Koniec z porażką
        znaczy, że wynik już zgłoszono, nawet gdy kolejne kliknięcie padło z
        tymi samymi commitami. Wynik starszej Aktualizacji nie trafia. Bez
        dziennika albo bez żadnego ``aktualizacja-start`` nie wiadomo, co już
        zapisano, więc wynik trafia.
        """

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
        """Wydania wyższe od wybranego, których commit nie leży na `main`: Aktualizacja narzędzia je pominęła."""

        self._write("aktualizacja-pominiete-wydania", tagi=",".join(tags))

    def dad_actions_unavailable(self, failure: OSError) -> None:
        """Dziennika działań taty dla Logów Uruchomienia nie da się zapisać, odczytać albo opróżnić; tylko typ błędu."""

        self._write("dzialania-taty-niedostepne", typ=type(failure).__name__)

    def pricing_journal_unavailable(self, failure: OSError, *, where: Literal["wpis", "start"]) -> None:
        """Dziennika Wyceny w efenix nie da się zapisać w trakcie Uruchomienia (``wpis``) albo odczytać, zamknąć lub usunąć
        przy starcie Centrum (``start``); tylko typ błędu."""

        self._write("dziennik-wyceny-niedostepny", typ=type(failure).__name__, miejsce=where)

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        """Nieoczekiwany wyjątek: tylko nazwa typu i miejsce (np. trasa API), bez tekstu wyjątku."""

        self._write(UNEXPECTED_FAILURE_EVENT, typ=type(failure).__name__, miejsce=where)

    def fill_unreadable(self, *, period: str, cause: str, excel_lock: str, failure: str) -> None:
        """Nieudany odczyt Pliku zbiorczego dla Uzupełnienia: kod Komunikatu, plik blokady Excela i typ błędu.

        ``excel_lock`` to ``tak``, ``nie`` albo ``nieznany``; ``failure`` to nazwa typu błędu systemu albo
        openpyxl, a ``-`` bez niego. Po tym wpisie wiadomo, czy Windows daje czytać plik, który trzyma Excel (ADR 0016).
        """

        self._write("uzupelnienie-odczyt-nieudany", okres=period, przyczyna=cause, excel=excel_lock, typ=failure)

    def diagnosed(self, *, process: str, period: str, cause: str) -> None:
        """Diagnoza Zatrzymania: klucz procesu, token okresu i kod Komunikatu wyjaśnienia."""

        self._write("diagnoza", proces=process, okres=period, przyczyna=cause)

    def box_post_queued(self, *, label: str, period: str | None) -> None:
        """Wysyłka w tle (np. Kontrola ilości) czeka w kolejce Skrzynki Zgłoszeń; bez treści."""

        self._write("skrzynka-w-kolejce", etykieta=label, okres=_period(period))

    def box_post_sent(self, *, label: str, period: str | None, number: int) -> None:
        """Wysyłka w tle przyjęta przez Skrzynkę Zgłoszeń w issue ``number``; bez treści i klucza."""

        self._write("skrzynka-wyslano", etykieta=label, okres=_period(period), numer=number)

    def box_post_waiting(
        self, *, label: str, period: str | None, cause: WaitingCause, file: str | None = None
    ) -> None:
        """Wysyłka w tle zostaje w kolejce do następnej próby; ``cause``: dlaczego, ``file``: plik odrzuconej treści."""

        named = {} if file is None else {"plik": file}
        self._write("skrzynka-czeka", etykieta=label, okres=_period(period), przyczyna=cause, **named)

    def box_post_archived(self, *, label: str, period: str | None) -> None:
        """Plik wysyłki, której części już były w Skrzynce Zgłoszeń, doszedł do Archiwum okresu; bez treści i klucza."""

        self._write("skrzynka-archiwum", etykieta=label, okres=_period(period))

    def box_post_dropped(self, *, label: str, file: str, number: int) -> None:
        """Plik kolejki Skrzynki Zgłoszeń usunięty bez wysyłki: issue ``number``, do którego szedł, zniknęło."""

        self._write("skrzynka-porzucono", etykieta=label, plik=file, numer=number)

    def box_post_unreadable(self, *, file: str) -> None:
        """Pliku kolejki Skrzynki Zgłoszeń nie da się odczytać (uszkodzony, nieznany schemat); zostaje. Tylko nazwa."""

        self._write("skrzynka-nieczytelny", plik=file)

    def box_notes_unavailable(self, failure: OSError) -> None:
        """Pliku zapisów Skrzynki Zgłoszeń (``keyed_box.OPENING_FILE``) nie da się odczytać albo zapisać, więc zapisy do
        Skrzynki czekają; tylko typ błędu, raz na pracę Centrum."""

        self._write("skrzynka-zapisy-niedostepne", typ=type(failure).__name__)

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
        """Pomiar gotowego widoku z przeglądarki; ``fcp_ms`` tylko przy zimnym starcie.

        Każde zapytanie API to ``operacja:przeglądarka/serwer`` w milisekundach,
        a ``-`` zamiast czasu serwera, gdy odpowiedź nie miała ``Server-Timing``.
        Ponad ``MAX_VIEW_TIMINGS`` pomiarów tego dziennika nic nie zapisuje.
        """

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
        """Najwyżej ``limit`` ostatnich wpisów od ostatniego startu Centrum; brak dziennika to brak wpisów.

        Pomiary widoków są pominięte: po każdym przejściu w menu jest nowy, więc
        wyparłyby wpisy o pracy serwera, a pomiary zostają na komputerze taty.
        """

        try:
            with self._lock:
                # urwany zapis (np. przy utracie zasilania) psuje jeden wpis, nie odczyt całego dziennika
                lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        starts = [index for index, line in enumerate(lines) if event_of(line) == "start"]
        session = lines[starts[-1] :] if starts else lines
        return [line for line in session if event_of(line) != VIEW_TIMING_EVENT][-limit:]

    def _write(self, event: str, **facts: str | int) -> None:
        moment = datetime.now().astimezone().isoformat(timespec="seconds")
        line = " ".join([moment, event, *(f"{key}={_quoted(value)}" for key, value in facts.items())])
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as log:
                    log.write(line + "\n")
        except OSError:
            pass  # dziennik pomaga przy wsparciu; jego brak nie może zatrzymać Centrum


def event_of(line: str) -> str:
    """Nazwa zdarzenia wpisu dziennika (drugie pole po czasie)."""

    fields = line.split(" ", 2)
    return fields[1] if len(fields) > 1 else ""


def _facts(line: str) -> dict[str, str]:
    """Fakty ``klucz=wartość`` wpisu dziennika; wartości ze spacją (w cudzysłowie) wychodzą rozbite."""

    return {key: value for key, _, value in (field.partition("=") for field in line.split(" ")[2:])}


def _quoted(value: str | int) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text


def _period(period: str | None) -> str:
    """Token okresu wysyłki w tle; Uruchomienie bez ustalonego okresu ma ``bez-okresu``."""

    return period or _NO_PERIOD
