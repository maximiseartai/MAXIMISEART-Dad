"""Dziennik Centrum: lokalny plik z bezpiecznymi faktami o pracy serwera.

Każdy wpis to jedna linia: czas, nazwa zdarzenia i fakty ``klucz=wartość``.
Do dziennika trafiają tylko fakty wybrane tutaj (port, wersja, kod komunikatu,
nazwa typu wyjątku), nigdy tekst wyjątku, ścieżki z folderu okresów ani treść
wierszy (ADR 0004), więc można go przekazać Maksowi.
Moduł używa tylko biblioteki standardowej, bo zapisuje też błędy startu, gdy
brakuje zależności.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import threading
from typing import Literal, final

from rozliczenia.centrum.tool_update import UPDATED
from rozliczenia.wall_clock import local_now

VIEW_TIMING_EVENT = "pomiar"
UNEXPECTED_FAILURE_EVENT = "nieoczekiwany-wyjatek"
MAX_VIEW_TIMINGS = 200
"""Najwięcej pomiarów widoku w dzienniku od startu Centrum: pomiar przychodzi po każdym widoku, więc kolejne przepadają
po cichu, a wpisy o pracy serwera są zapisywane dalej."""
_UPDATE = "aktualizacja"
_UPDATE_STARTED = "aktualizacja-start"
"""Zdarzenie, które pisze ``update_started``; ``update_awaits`` szuka go w dzienniku."""
_UPDATE_FINISHED = "aktualizacja-koniec"
"""Zdarzenie, które pisze ``update_finished``; ``update_awaits`` szuka go w dzienniku."""
_NO_PERIOD = "bez-okresu"
"""Okres wysyłki w tle z Uruchomienia, którego okresu nie ustalono."""
WaitingCause = Literal["brak-klucza", "brak-sieci", "odmowa", "odmowa-tresci", "odmowa-archiwum"]
"""Dlaczego wysyłka w tle czeka w kolejce Skrzynki Zgłoszeń; ``odmowa-tresci`` i ``odmowa-archiwum`` (Archiwum okresu
nie przyjęło pliku wysyłki, której części już doszły) dotyczą tylko jednego pliku kolejki."""
ReminderFailure = Literal[
    "bez-wdrozenia",
    "bez-ustawien",
    "bez-dostepu",
    "bez-adresow",
    "okresy",
    "intermax",
    "brak-sieci",
    "haslo-odrzucone",
    "odmowa-wysylki",
    "zapis-por",
]
"""Dlaczego sprawdzenie Przypomnień o raporcie (``report_reminders``) nie wysłało wszystkiego, co się należało."""
SettingsUnreadableCause = Literal["dostep", "historia"]
"""Dlaczego zmiany Ustawień Centrum nie zapisano: plik Ustawień (``dostep``) albo Historia Ustawień (``historia``) jest,
ale system nie daje go czytać."""
SettingsExternalResult = Literal["zapisano", "odrzucono", "bez-zapisu"]
"""Co Ustawienia Centrum zrobiły z plikiem zmienionym poza Centrum; ``bez-zapisu``: wiersza Historii albo pamięci nie
dało się zapisać, więc następny odczyt spróbuje jeszcze raz."""
SettingsReleaseResult = Literal[
    "zastosowano", "bez-zmian", "odrzucono", "pozniej", "bez-zapisu", "bez-pamieci", "bez-historii"
]


class CentrumLog:
    def __init__(self, path: Path, *, append: Callable[[str], None] | None = None) -> None:
        """Dziennik w pliku ``path``; ``append`` dostaje każdą linię zamiast pliku (wyrocznia skilla, która ocenia same
        wywołania dziennika, a zapis na dysk dodawałby jej tylko czasu)."""

        self._path = path
        self._lock = threading.Lock()
        self._view_timings = 0
        self._append = self._to_file if append is None else append
        self._held: list[str] | None = None
        self._hold_lock = threading.Lock()

    @property
    def directory(self) -> Path:
        """Katalog dziennika; obok niego leżą Logi Uruchomienia (ADR 0015)."""

        return self._path.parent

    def hold_until_started(self) -> None:
        """Wpisy z przygotowania serwera (zmiany Ustawień z Wydania, pierwszy odczyt Ustawień) czekają na wpis
        ``start``, więc dziennik każdego startu zaczyna się od ``start`` z portem i wersją; ``started`` zapisuje je
        zaraz po nim, a ``release_held`` bez niego, gdy start się nie udał."""

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

    def settings_unreadable(self, *, cause: SettingsUnreadableCause) -> None:
        """Zmiany Ustawień Centrum nie zapisano, bo jej pliku albo Historii nie dało się przeczytać; plik zostaje bez
        zmian."""

        self._write("ustawienia-bez-zapisu", przyczyna=cause)

    def settings_changed(self, *, file: str, keys: Sequence[str], source: str) -> None:
        """Zapisana zmiana Ustawień Centrum: plik, klucze (``foldery.folder_okresow``) i źródło, bez wartości."""

        self._write("ustawienia-zmiana", plik=file, klucze=",".join(keys), zrodlo=source)

    def settings_external(self, *, file: str, result: SettingsExternalResult) -> None:
        """Plik Ustawień Centrum zmieniony poza Centrum: przyjęty, odrzucony jako zła treść albo bez zapisu wiersza."""

        self._write("ustawienia-spoza", plik=file, wynik=result)

    def settings_release(self, *, change: str, result: SettingsReleaseResult) -> None:
        """Zmiana Ustawień Centrum z Wydania przy starcie: id zmiany i wynik (``pozniej``, ``bez-zapisu``, ``bez-pamieci``
        i ``bez-historii`` wracają przy następnym starcie), bez wartości."""

        self._write("ustawienia-wydanie", zmiana=change, wynik=result)

    def settings_bad(self, *, file: str, field: str) -> None:
        """Złe ustawienie w pliku Ustawień Centrum: pole (``plik`` dla całego pliku), bez treści pliku."""

        self._write("ustawienia-zle", plik=file, pole=field)

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

    def reminder_sent(self, *, day: str, pora: str) -> None:
        """Praca przypomnień wysłała Przypomnienie o raporcie za dzień ``day`` w porze ``pora``; bez adresu, Wykonawcy i
        treści (ADR 0028, ADR 0030)."""

        self._write("przypomnienie-wyslane", dzien=day, pora=pora)

    def reminders_failed(self, *, cause: ReminderFailure, failure: str | None = None) -> None:
        """Sprawdzenie Przypomnień o raporcie nie wysłało wszystkiego: przyczyna i nazwa typu wyjątku, gdy jest."""

        named = {} if failure is None else {"typ": failure}
        self._write("przypomnienia-porazka", przyczyna=cause, **named)

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
        Urwany zapis (np. przy utracie zasilania) psuje jeden wpis, nie odczyt całego dziennika.
        """

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
        """Format wpisu i zapis są tylko tutaj: wyrocznia podaje własny zapis przez ``append``, a podklasa, która je
        nadpisuje, to błąd mypy (``final``)."""

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

    @final
    def _to_file(self, line: str) -> None:
        """Dopisuje wpis do pliku dziennika; brak dziennika nie zatrzymuje Centrum, bo dziennik tylko pomaga przy
        wsparciu."""

        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as log:
                    log.write(line + "\n")
        except OSError:
            pass


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
    return period or _NO_PERIOD
