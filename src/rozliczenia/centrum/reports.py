"""Zgłoszenie do Maksa: treść, wysyłka do skrzynki Zgłoszeń i stan na tym komputerze.

Treść Zgłoszenia powstaje tylko tutaj, z tych samych bezpiecznych faktów co
Komunikat. Zgłoszenie Zatrzymania (``StopReport``) ma Komunikat z kodem i
trzema częściami, proces, okres i tryb, odnośnik do Logów Uruchomienia, commit
narzędzia, wynik każdego sprawdzenia Diagnozy i ostatnie wpisy dziennika
Centrum, a przy nieoczekiwanym wyjątku jego typ i ślad wywołań w kodzie
narzędzia. Zgłoszenie nieudanej Aktualizacji narzędzia (``UpdateReport``) ma
te same fakty co dziennik Centrum:
kod Komunikatu, commit przed i po, czy instalowano biblioteki i ostatnie wpisy
dziennika, bez ścieżek i bez wyjścia Gita. Ścieżki są już skrócone w
Komunikatach, szczegółach sprawdzeń i ramkach śladu; treści wierszy, treści
wyjątków ani klucza Zgłoszenie nie ma (ADR 0007). Podgląd przechodzi przez
strażnika reguły danych (ADR 0025), więc tata widzi i wysyła tekst bez wartości
``ADRES`` i numeru Orange, z zamaskowanymi telefonami i ulicami.

Treść Zgłoszenia mieści się w jednej części wysyłki (``PART_LIMIT``), bo kolejka Skrzynki przejmuje Zgłoszenie,
które założyła przerwana próba tej samej wysyłki, bez komentarzy (#724), a do otwartego Zgłoszenia tego odcisku
dopisuje całą treść jednym komentarzem (#820). Za długa traci najpierw pierwsze ramki śladu wywołań (pełny ślad jest
w Logach Uruchomienia), a gdy to nie wystarczy, najstarsze wpisy dziennika Centrum; każde skrócenie ma dopisek.

Źródło Zgłoszenia (Zatrzymanie w ``stops``, nieudana Aktualizacja narzędzia w
``tool_updates``) trzyma jego uchwyt (``ReportHandle``): uchwyt zamraża podgląd,
a „Wyślij do Maksa” kładzie dokładnie ten podgląd w kolejce Skrzynki Zgłoszeń,
najwyżej raz na uchwyt. Powrót problemu, którego Zgłoszenie jest otwarte, idzie
do kolejki sam po Diagnozie Zatrzymania, bez kliknięcia (#820). Zgłoszenie pracy Przypomnień o raporcie
(``ReminderReport``, odrzucone hasło aplikacji przy wysyłce) praca przypomnień w ``report_reminders`` wysyła sama, bo
tata przy niej nie siedzi (ADR 0030). Bez sieci albo Tokenu do Zgłoszeń Zgłoszenie czeka w
kolejce i wychodzi samo; Komunikat jest tylko wtedy, gdy nie da się zapisać
pliku kolejki. Zgłoszenie, którego treść Skrzynka odrzuciła, nie czeka na nic,
co mógłby naprawić tata albo internet (``Rejected``).
"""

from __future__ import annotations

from bisect import bisect_left
import threading
import uuid
import weakref
from collections.abc import Callable, Sequence
from dataclasses import astuple, dataclass
import hashlib
from typing import Final, Literal

from rozliczenia.client_data import ForbiddenValues, Outgoing, guarded, tool
from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import report_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.dad_cases import REPORT, Case, CaseNews, CaseNumbered, CaseRejected, DadCases
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import DELIVERY_WAIT_S, PART_LIMIT, OpenIssue, Outbox, Post
from rozliczenia.centrum.report_issue import RETURNED_HEADING, fingerprint_line
from rozliczenia.centrum.report_box import FindOutcome
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import UpdateResult
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.message import Message
from rozliczenia.process_run import Stop
from rozliczenia.wall_clock import utc_now

# Podgląd Zgłoszenia czeka w tle na odpowiedź skrzynki o otwarte Zgłoszenie najwyżej tyle, co Diagnoza na commit `main`.
SEARCH_DEADLINE_S: Final = 3.0
REPORT_THREAD: Final = "zgloszenie-skrzynka"

# Zgłoszenie nieudanej Aktualizacji narzędzia ma tyle ostatnich wpisów dziennika co Zgłoszenie z Diagnozy.
_UPDATE_LOG_ENTRIES: Final = 20

_CHECK_STATES: Final = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}


@dataclass(frozen=True)
class Report:
    """Zgłoszenie: tytuł (kod i „Co się stało”), treść Markdown, odcisk problemu, po którym je rozpoznać, i samo
    „Co się stało”, którym Powiadomienie nazywa Zgłoszenie."""

    title: str
    body: str
    fingerprint: str
    what: str


@dataclass(frozen=True)
class ProblemFingerprint:
    """Odcisk problemu: proces (albo Aktualizacja narzędzia), kod Komunikatu i jego trzy części.

    Kody są unikalne tylko w katalogu procesu, więc odcisk zawiera proces.
    """

    process: common_contract.ProcessKey | Literal["tool_update", "report_reminders"]
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, process: common_contract.ProcessKey, message: Message) -> ProblemFingerprint:
        return cls(process, message.code, message.what, message.where, message.action)

    @classmethod
    def of_tool_update(cls, message: Message) -> ProblemFingerprint:
        """Odcisk problemu nieudanej Aktualizacji narzędzia: jej kody są unikalne w jej własnym katalogu."""

        return cls("tool_update", message.code, message.what, message.where, message.action)

    @classmethod
    def of_reminders(cls, message: Message) -> ProblemFingerprint:
        """Odcisk problemu pracy Przypomnień o raporcie: jej kody są unikalne w jej własnym katalogu."""

        return cls("report_reminders", message.code, message.what, message.where, message.action)

    @property
    def digest(self) -> str:
        """Stały skrót odcisku do Zgłoszenia i lokalnego stanu wysłanych; bez treści Komunikatu."""

        return hashlib.sha256("\x1f".join(astuple(self)).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StopReport:
    """Zgłoszenie Zatrzymania z Diagnozy.

    ``logs``: adres komentarza Logów Uruchomienia w Skrzynce Zgłoszeń z chwili Diagnozy; ``None``: Logi nie były
    jeszcze w Skrzynce (zwykle czekały w kolejce). Ustalony przy Diagnozie, więc wysłane Zgłoszenie jest dokładnie
    podglądem, który widział tata.
    """

    run: runs_contract.RunInfo
    stop: Stop
    fingerprint: ProblemFingerprint
    diagnosis: Diagnosis
    logs: str | None

    @property
    def period(self) -> str:
        return self.run.period

    def report(self, *, commit: str | None, previous: int | None, settings: Sequence[str]) -> Report:
        run, message, diagnosis, trace = self.run, self.stop.message, self.diagnosis, self.stop.trace
        fingerprint = self.fingerprint.digest
        explanation = diagnosis.explanation

        def lines(dropped_frames: int, dropped_entries: int) -> list[str]:
            return [
                *_message_lines(message),
                "## Uruchomienie procesu",
                "",
                f"- Proces: {run.title}",
                f"- Okres: {run.period}",
                f"- Tryb: {run.mode}",
                f"- Logi: {self.logs or f'jeszcze niewysłane, Uruchomienie {run.id}'}",
                "",
                *_trace_lines(trace, dropped_frames),
                *_tool_lines(fingerprint, previous, commit=f"- Commit: {commit or 'nieznany'}"),
                "## Diagnoza",
                "",
                f"Wyjaśnienie: {explanation.code} · {explanation.what}",
                "",
                "| Sprawdzenie | Wynik | Szczegóły |",
                "| --- | --- | --- |",
                *(
                    f"| {_cell(check.label)} | {_CHECK_STATES[check.state]} | {_cell(check.detail)} |"
                    for check in diagnosis.checks
                ),
                "",
                *_settings_lines(settings),
                *_log_lines(diagnosis.log_entries, dropped_entries),
            ]

        frames = 0 if trace is None else len(trace.frames)
        return _report(message, _fitted(lines, frames=frames, entries=len(diagnosis.log_entries)), fingerprint)


@dataclass(frozen=True)
class UpdateReport:
    """Zgłoszenie nieudanej Aktualizacji narzędzia: Komunikat i fakty wpisu ``aktualizacja-koniec`` dziennika."""

    result: UpdateResult
    message: Message
    log_entries: tuple[str, ...]
    fingerprint: ProblemFingerprint

    @classmethod
    def of(cls, result: UpdateResult, message: Message, log: CentrumLog) -> UpdateReport:
        return cls(result, message, tuple(log.recent(_UPDATE_LOG_ENTRIES)), ProblemFingerprint.of_tool_update(message))

    @property
    def period(self) -> None:
        return None

    def report(self, *, commit: str | None, previous: int | None, settings: Sequence[str]) -> Report:
        result, fingerprint = self.result, self.fingerprint.digest

        def lines(_dropped_frames: int, dropped_entries: int) -> list[str]:
            return [
                *_message_lines(self.message),
                "## Aktualizacja narzędzia",
                "",
                f"- Wynik: {result.code}",
                f"- Commit przed: {result.before or 'nieznany'}",
                f"- Commit po: {result.after or 'brak'}",
                f"- Biblioteki instalowane: {'tak' if result.installed else 'nie'}",
                "",
                *_tool_lines(fingerprint, previous),
                *_settings_lines(settings),
                *_log_lines(self.log_entries, dropped_entries),
            ]

        return _report(self.message, _fitted(lines, frames=0, entries=len(self.log_entries)), fingerprint)


@dataclass(frozen=True)
class ReminderReport:
    """Zgłoszenie pracy Przypomnień o raporcie, które Centrum wysyła samo, bez taty: Komunikat i ostatnie wpisy
    dziennika Centrum (bez adresów Wykonawców i treści maili, bo dziennik ich nie ma)."""

    message: Message
    log_entries: tuple[str, ...]
    fingerprint: ProblemFingerprint

    @classmethod
    def of(cls, message: Message, log: CentrumLog) -> ReminderReport:
        return cls(message, tuple(log.recent(_UPDATE_LOG_ENTRIES)), ProblemFingerprint.of_reminders(message))

    @property
    def period(self) -> None:
        return None

    def report(self, *, commit: str | None, previous: int | None, settings: Sequence[str]) -> Report:
        fingerprint = self.fingerprint.digest

        def lines(_dropped_frames: int, dropped_entries: int) -> list[str]:
            return [
                *_message_lines(self.message),
                *_tool_lines(fingerprint, previous, commit=f"- Commit: {commit or 'nieznany'}"),
                *_settings_lines(settings),
                *_log_lines(self.log_entries, dropped_entries),
            ]

        return _report(self.message, _fitted(lines, frames=0, entries=len(self.log_entries)), fingerprint)


ReportSource = StopReport | UpdateReport | ReminderReport
"""Źródło Zgłoszenia: Zatrzymanie, nieudana Aktualizacja narzędzia albo praca Przypomnień o raporcie."""


def _message_lines(message: Message) -> list[str]:
    return [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        f"- Kod: {message.code}",
        f"- Co się stało: {message.what}",
        f"- Gdzie: {message.where}",
        f"- Co zrobić: {message.action}",
        "",
    ]


def _tool_lines(fingerprint: str, previous: int | None, *, commit: str | None = None) -> list[str]:
    """Sekcja narzędzia: ``commit`` (gotowy wiersz, jeśli jest), odcisk problemu i poprzednie Zgłoszenie."""

    return [
        "## Narzędzie",
        "",
        *([] if commit is None else [commit]),
        fingerprint_line(fingerprint),
        *([] if previous is None else [f"- Poprzednie Zgłoszenie: #{previous}"]),
        "",
    ]


def _settings_lines(changes: Sequence[str]) -> list[str]:
    """Sekcja zmian Ustawień Centrum z ostatnich 30 dni (``CentrumSettings.reported_changes``): bez nazw, adresów i
    sekretów, bo te linie ich nie mają."""

    return ["## Zmiany Ustawień (30 dni)", "", *(changes or ["- bez zmian"]), ""]


def _report(message: Message, lines: list[str], fingerprint: str) -> Report:
    return Report(title=f"{message.code}: {message.what}", body=_body(lines), fingerprint=fingerprint, what=message.what)


def _guarded(report: Report, period: str | None, forbidden: ForbiddenValues) -> _Preview:
    """Podgląd Zgłoszenia po strażniku reguły danych (``guarded``): tytuł i treść bez zakazanych wartości,
    z zamaskowanymi telefonami i ulicami, a każda zamaskowana wartość to uwaga techniczna na końcu treści."""

    title = guarded(forbidden, report.title, "tytuł Zgłoszenia")
    body = guarded(forbidden, report.body, "treść Zgłoszenia")
    notes = [*title.notes, *body.notes]
    tail = "" if not notes else "\n## Uwagi techniczne\n\n" + "".join(f"- {note}\n" for note in notes)
    return _Preview(title.text, body.text + tool(tail), report.fingerprint, report.what, period)


def _body(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _fitted(lines: Callable[[int, int], list[str]], *, frames: int, entries: int) -> list[str]:
    """Wiersze Zgłoszenia, które mieszczą się w jednej części wysyłki (``PART_LIMIT``).

    ``lines`` dostaje, ile pierwszych ramek śladu wywołań i ile najstarszych wpisów dziennika pominąć. Skraca się
    najpierw ślad, potem dziennik, każde o najmniej, ile trzeba; treść, która nie mieści się nawet bez śladu i
    dziennika, zostaje taka, a ``Post`` ją odrzuci.
    """

    steps = [
        *((dropped, 0) for dropped in range(frames + 1)),
        *((frames, dropped) for dropped in range(1, entries + 1)),
    ]

    def fits(step: tuple[int, int]) -> bool:
        return len(_body(lines(*step))) <= PART_LIMIT

    # Każdy krok po pierwszym skraca treść, więc pierwszy, który się mieści, znajduje bisekcja. Pierwszy krok (całe
    # Zgłoszenie) sprawdza osobno, bo dopisek o pominiętych ramkach bywa dłuższy niż jedna ramka.
    first = 0 if fits(steps[0]) else bisect_left(steps, True, lo=1, key=fits)
    return lines(*steps[min(first, len(steps) - 1)])


def _trace_lines(trace: CallTrace | None, dropped: int) -> list[str]:
    """Sekcja śladu wywołań wyjątku: typ, przyczyny z łańcucha ``__cause__`` i ramki kodu narzędzia, bez treści wyjątku.

    ``dropped`` pierwszych ramek (od miejsca przechwycenia) pomija, z dopiskiem, że pełny ślad mają Logi Uruchomienia;
    ramki przyczyn są tylko w Logach Uruchomienia.
    """

    if trace is None:
        return []
    return [
        "## Ślad wywołań",
        "",
        f"- Wyjątek: {trace.exception_type}",
        *(f"- Przyczyna: {cause.exception_type}" for cause in trace.causes),
        *([] if dropped == 0 else [f"- Pominięte pierwsze ramki: {dropped}, pełny ślad wywołań jest w Logach Uruchomienia"]),
        "",
        "```text",
        *(f"{frame.file}:{frame.line} w {frame.function}" for frame in trace.frames[dropped:]),
        "```",
        "",
    ]


def _log_lines(entries: Sequence[str], dropped: int) -> list[str]:
    return [
        "## Dziennik Centrum rozliczeń",
        "",
        *([] if dropped == 0 else [f"Pominięte najstarsze wpisy: {dropped}, żeby Zgłoszenie zmieściło się w jednym issue.", ""]),
        "```text",
        *entries[dropped:],
        "```",
    ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")




def report_target(fingerprint: str, title: Outgoing) -> OpenIssue:
    """Cel wysyłki Zgłoszenia w kolejce: jedno otwarte Zgłoszenie na odcisk problemu, a Zgłoszenie, które wróciło, idzie
    do niego komentarzem „Zgłoszenie wróciło” (ADR 0007, #820)."""

    return OpenIssue(REPORT.label, tool(fingerprint_line(fingerprint)), title, tool(RETURNED_HEADING))


def _unframed(_number: int, _count: int, text: Outgoing) -> Outgoing:
    """Części Zgłoszenia bez nagłówków: issue i komentarze to razem dokładnie podgląd."""

    return text


@dataclass(frozen=True)
class _Preview:
    """Zamrożony podgląd Zgłoszenia po strażniku (``_guarded``), jego odcisk i „Co się stało” (``Report``) i token okresu
    jego źródła (``None``: Aktualizacja narzędzia) do dziennika kolejki."""

    title: Outgoing
    body: Outgoing
    fingerprint: str
    what: str
    period: str | None

    @property
    def view(self) -> diagnosis_contract.ReportDraft:
        return diagnosis_contract.ReportDraft(title=self.title, body=self.body)


ReportShown = Callable[[diagnosis_contract.ReportState], None]
"""Właściciel Zgłoszenia, który pokazuje każdy jego nowy stan (np. karta Uruchomienia przez ``RunHost``)."""


class NoPreview(Exception):
    """„Wyślij do Maksa” przed pierwszym podglądem: nie ma czego wysłać."""


class ReportHandle:
    """Zgłoszenie jednego problemu z jednego źródła (``ReportSource``), od podglądu do wysyłki.

    ``prepare`` zamraża podgląd i pyta skrzynkę Zgłoszeń w tle o otwarte Zgłoszenie tego problemu, a ``send``
    kładzie ostatni podgląd w kolejce Skrzynki najwyżej raz; drugie kliknięcie w trakcie wysyłki czeka na jej wynik.
    Podgląd Zatrzymania, którego problem po odpowiedzi skrzynki czeka na naprawę (ma otwarte Zgłoszenie), uchwyt
    kładzie w kolejce sam jako powrót problemu, najwyżej raz: kolejka dopisuje go do otwartego Zgłoszenia komentarzem
    „Zgłoszenie wróciło”, a stan zostaje „czeka na naprawę”, bo tata nie ma tu nic do zrobienia (ADR 0007).
    Po każdej odpowiedzi skrzynki, każdej wysyłce i dostarczeniu z kolejki nowy stan dostaje ``shown`` właściciela.
    Odpowiedź na pytanie sprzed wysyłki przepada, bo stan to już wynik wysyłki. ``shown`` biegnie pod blokadą
    uchwytu, więc dostaje stany w kolejności ich zmian, i nie woła uchwytu. Właściciel, który pokazuje stan dopiero
    po odpowiedzi skrzynki, czeka na nią przez ``wait_for_box``.
    """

    def __init__(self, reports: Reports, fingerprint: str, shown: ReportShown | None) -> None:
        self._reports = reports
        self._fingerprint = fingerprint
        self._shown = shown
        self._changed = threading.Condition()
        self._state = reports._state_of(fingerprint)
        self._preview: _Preview | None = None
        self._asking: threading.Thread | None = None
        self._sends = 0  # wysyłki zaczęte do tej pory: odpowiedź skrzynki na pytanie sprzed wysyłki przepada
        self._sending = False
        self._returned = False  # powrót problemu już poszedł do kolejki: drugi z tego uchwytu by go dublował

    @property
    def state(self) -> diagnosis_contract.ReportState:
        with self._changed:
            return self._state

    def prepare(self, source: ReportSource) -> diagnosis_contract.ReportDraft:
        """Nowy podgląd ``source``, który wyśle ``send``; nie czeka na skrzynkę i niczego nie zapisuje.

        Gdy ten problem był już zgłoszony z tego komputera, Zgłoszenie ma odnośnik do ostatniego z nich. Podgląd
        Zatrzymania, którego problem czeka na naprawę, po odpowiedzi skrzynki idzie sam do kolejki jako powrót.
        """

        preview = self._reports._preview(source)
        comeback = preview if isinstance(source, StopReport) else None
        with self._changed:
            self._preview = preview
            asking = self._asking = threading.Thread(
                target=self._ask, args=(self._sends, comeback), name=REPORT_THREAD, daemon=True
            )
        asking.start()
        return preview.view

    def wait_for_box(self) -> None:
        """Czeka na odpowiedź skrzynki na pytanie z ostatniego ``prepare``, najwyżej termin szukania w skrzynce.

        Po odpowiedzi „czeka na naprawę” podglądu Zatrzymania czeka też na wysyłkę jego powrotu (``DELIVERY_WAIT_S``).
        """

        with self._changed:
            asking = self._asking
        if asking is not None:
            asking.join()

    def _ask(self, sends: int, comeback: _Preview | None) -> None:
        self._reports._ask_box(self._fingerprint)
        with self._changed:
            if sends != self._sends:
                return
            self._show(self._state if self._done else self._reports._state_of(self._fingerprint))
            if comeback is None or self._returned or not isinstance(self._state, diagnosis_contract.ReportWaiting):
                return
            self._returned = self._sending = True
        try:
            self._reports._queue(comeback)
        finally:
            with self._changed:
                self._sending = False
                self._changed.notify_all()

    def send(self) -> diagnosis_contract.ReportState:
        """Kładzie ostatni podgląd w kolejce Skrzynki i czeka na nią chwilę, chyba że już wysłany albo czeka w kolejce.

        ``NoPreview``, gdy podglądu nie ma.
        """

        with self._changed:
            while self._sending:
                self._changed.wait()
            preview = self._preview
            if preview is None:
                raise NoPreview
            if self._done:
                return self._state
            self._sending = True
            self._sends += 1
        try:
            state = self._reports._queue(preview)
        except BaseException:
            with self._changed:
                self._sending = False
                self._changed.notify_all()
            raise
        with self._changed:
            self._sending = False
            # Dostarczenie mogło przyjść tuż po końcu czekania, zanim uchwyt pokazał „czeka w kolejce”.
            if isinstance(state, common_contract.Queued) and not self._reports._pending(self._fingerprint):
                state = common_contract.Sent(state="sent")
            self._show(state)
            self._changed.notify_all()
            return state

    def _rejected(self) -> None:
        with self._changed:
            self._show(common_contract.Rejected(state="rejected"))

    def _delivered(self) -> None:
        with self._changed:
            if isinstance(self._state, common_contract.Queued):
                self._show(common_contract.Sent(state="sent"))

    @property
    def _done(self) -> bool:
        return isinstance(self._state, common_contract.Sent | common_contract.Queued)

    def _show(self, state: diagnosis_contract.ReportState) -> None:
        self._state = state
        if self._shown is not None:
            self._shown(state)


class Reports:
    """Zgłoszenia z tego komputera: uchwyt Zgłoszenia każdego źródła, wysyłka przez kolejkę Skrzynki i sprawy.

    „Wyślij do Maksa” zapisuje sprawę bez numeru, kładzie zamrożony podgląd w kolejce jako ``report_target`` i czeka na
    skrzynkę najwyżej ``DELIVERY_WAIT_S``. Numer issue dopisują sprawie Sprawy taty w Skrzynce (``case_delivery``),
    także po następnym starcie Centrum, a ``Reports`` słyszy o nim od Spraw taty (``DadCases.watch``) i oddaje stan
    „wysłane” każdemu żywemu uchwytowi tego problemu; o odrzuconej treści tak samo. Jeden problem ma jedno
    otwarte Zgłoszenie: podgląd pyta skrzynkę o otwarte Zgłoszenie z tym odciskiem, kolejka dopisuje do niego
    komentarz „Zgłoszenie wróciło” zamiast zakładać nowe (powrót po Diagnozie Zatrzymania kładzie w kolejce sam
    uchwyt), a problem, którego Zgłoszenie czeka w kolejce, nie trafia do niej drugi raz.
    """

    def __init__(
        self,
        work: CentrumWork,
        box: KeyedBox,
        outbox: Outbox,
        commit: CommitSource,
        cases: DadCases,
        *,
        search_deadline_s: float,
        settings_changes: Callable[[], tuple[str, ...]],
    ) -> None:
        """``settings_changes`` daje linie zmian Ustawień Centrum z ostatnich 30 dni do każdego Zgłoszenia."""

        self._commit = commit
        self._settings_changes = settings_changes
        self._forbidden = work.forbidden
        self._search_deadline_s = search_deadline_s
        self._cases = cases
        self._queue_directory = outbox.directory
        self._box = box
        self._outbox = outbox
        # Blokada chroni tylko stan w pamięci; pytania do skrzynki idą bez niej.
        self._lock = threading.Lock()
        # Ostatnia odpowiedź skrzynki w tej pracy Centrum: odcisk problemu → numer otwartego Zgłoszenia albo None.
        self._open: dict[str, int | None] = {}
        # Ile numerów issue dostały sprawy problemu w tej pracy Centrum: odpowiedź na pytanie sprzed numeru jest starsza.
        self._numbered: dict[str, int] = {}
        self._handles: dict[str, weakref.WeakSet[ReportHandle]] = {}
        cases.watch(REPORT, self._heard)

    def handle(self, fingerprint: ProblemFingerprint, *, shown: ReportShown | None = None) -> ReportHandle:
        """Uchwyt Zgłoszenia problemu ``fingerprint`` bez podglądu; stan bez pytania skrzynki.

        ``shown`` dostaje każdy nowy stan; właściciel, który czyta ``ReportHandle.state`` sam, go nie podaje.
        """

        handle = ReportHandle(self, fingerprint.digest, shown)
        with self._lock:
            self._handles.setdefault(fingerprint.digest, weakref.WeakSet()).add(handle)
        return handle

    def _heard(self, news: CaseNews) -> None:
        with self._lock:
            if isinstance(news, CaseNumbered):
                self._open[news.case_id] = news.number
                self._numbered[news.case_id] = self._numbered.get(news.case_id, 0) + 1
            handles = list(self._handles.get(news.case_id, ()))
        for handle in handles:
            match news:
                case CaseNumbered():
                    handle._delivered()
                case CaseRejected():
                    handle._rejected()

    def _preview(self, source: ReportSource) -> _Preview:
        fingerprint = source.fingerprint.digest
        sent = [case.number for case in self._cases.all() if case.kind == REPORT and case.id == fingerprint]
        previous = next((number for number in reversed(sent) if number is not None), None)
        report = source.report(commit=self._commit(), previous=previous, settings=self._settings_changes())
        return _guarded(report, source.period, self._forbidden)

    def _queue(self, preview: _Preview) -> diagnosis_contract.ReportState:
        fingerprint = preview.fingerprint
        if self._pending(fingerprint):
            return self._cases.queued(fingerprint, self._box)
        case = Case(REPORT, fingerprint, preview.what, self._commit(), utc_now(), number=None)
        # Własny identyfikator wysyłki: odcisk wraca po zamknięciu, a kolejka czeka na dostarczenie po identyfikatorze.
        post = Post.of(
            report_target(fingerprint, preview.title),
            period=preview.period,
            run_id=uuid.uuid4().hex,
            blocks=[preview.body],
            frame=_unframed,
        )
        self._cases.add(case)
        queued = False
        try:
            queued = self._outbox.post(post)
        finally:
            if not queued:  # sprawa bez pliku kolejki czekałaby wiecznie, a tata nie mógłby kliknąć jeszcze raz
                self._cases.withdraw(case)
        if not queued:
            message = report_messages.not_queued(self._queue_directory)
            return diagnosis_contract.ReportNotQueued(state="not_queued", message=common_contract.Message.of(message))
        if self._outbox.wait_delivered(post.run_id, REPORT.label, timeout_s=DELIVERY_WAIT_S):
            return common_contract.Sent(state="sent")
        return self._cases.queued(fingerprint, self._box)


    def _pending(self, fingerprint: str) -> bool:
        latest = self._cases.find(REPORT, fingerprint)
        return latest is not None and latest.number is None

    def _ask_box(self, fingerprint: str) -> None:
        """Pyta skrzynkę o otwarte Zgłoszenie problemu; bez klucza albo odpowiedzi zostaje to, co już wiadomo.

        Brak odpowiedzi w ``search_deadline_s`` (u taty ``SEARCH_DEADLINE_S``) to brak odpowiedzi: spóźniona
        przepada, a kolejka i tak szuka otwartego Zgłoszenia, zanim założy nowe. Odpowiedź też przepada, gdy w trakcie
        pytania sprawa problemu dostała numer issue: skrzynka odpowiadała o stanie sprzed tego issue.
        """

        with self._lock:
            numbered = self._numbered.get(fingerprint, 0)
        answer = within(self._search_deadline_s, lambda: (self._find_open(fingerprint),), name="skrzynka-szukaj")
        if answer is None:
            return
        [found] = answer
        if found is None or isinstance(found, int):
            with self._lock:
                if self._numbered.get(fingerprint, 0) == numbered:
                    self._open[fingerprint] = found

    def _find_open(self, fingerprint: str) -> FindOutcome | NoKey:
        return self._box.find_issue(REPORT.label, fingerprint_line(fingerprint), include_closed=False)

    def _state_of(self, fingerprint: str) -> diagnosis_contract.ReportState:
        """Sprawa czekająca w kolejce, potem odpowiedź skrzynki z tej pracy Centrum, a bez niej ostatnia wysłana sprawa.

        Zgłoszenie, o którym wiadomo, że Maks je zamknął, nie czeka na naprawę.
        """

        latest = self._cases.find(REPORT, fingerprint)
        if latest is not None and latest.number is None:
            return self._cases.queued(fingerprint, self._box)
        with self._lock:
            known = fingerprint in self._open
            waiting = self._open.get(fingerprint) is not None
        if not known:
            waiting = latest is not None and latest.closure is None
        return diagnosis_contract.ReportWaiting(state="waiting") if waiting else diagnosis_contract.ReportReady(state="ready")
