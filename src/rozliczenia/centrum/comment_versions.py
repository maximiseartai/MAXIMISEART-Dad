"""Wersje komentarza Uruchomienia w issue Logów okresu (#844, #846, #910): która wersja idzie do Kolejki wysyłki, w jakim
stopniu i co dalej z dziennikiem Wyceny w efenix. Moduł niczego nie czyta ani nie zapisuje.

Każde Uruchomienie ma jeden komentarz w issue Logów okresu z etykietą ``logi-uruchomienia`` (``LABEL``), a każda jego
wersja to ta sama wysyłka (Uruchomienie i etykieta), więc kolejka zmienia ten sam komentarz zamiast dokładać nowy. Wersje
(``CommentVersion``) i ich stopień (``rank_of``, ``outbox.Rank``), który wybiera nadawca, a nie zegar:

- postęp Wyceny w efenix w trakcie (``ProgressVersion``, ``DRAFT``): bez pliku w Archiwum Logów okresu, bo pełne Logi
  powstają dopiero na końcu;
- wersja zastępcza, którą start Centrum odtwarza z dziennika Wyceny (``STAND_IN``): Logi z pliku albo Logi Urwanego
  Uruchomienia (``StandInLogs``) i wynik bez Logów (``WithoutLogsVersion``), gdy pliku Logów nie ma albo nie da się go
  odczytać;
- Logi z pracy Centrum Uruchomienia (``OwnLogs``, ``OWN``): z wynikiem, z Diagnozą.

Wersja końcowa zamienia więc postęp w podsumowanie także po cofnięciu zegara komputera, a wersja zastępcza nie zastępuje
Logów z wynikiem, które kolejka już przyjęła. Każda wersja niesie tylko tekst po strażniku reguły danych pracy Centrum
(``run_logs.GuardedLogs``, ``run_logs.GuardedText``, ADR 0025), więc wysyłka (``post_of``) strażnika nie potrzebuje, a
wersja z tekstem sprzed strażnika to błąd typu, a gdy typ go nie widzi (``Any``), ``TypeError`` w konstruktorze wersji. Dziennik Wyceny znika tylko po wersji końcowej,
którą kolejka przyjęła (``journal_after``), bo do tej chwili jest śladem komentarza, który może jeszcze mówić, że
Uruchomienie trwa.

Typy Logów bierze z ``run_logs`` do adnotacji i, importem w funkcji, do ``isinstance`` w konstruktorach wersji, bo
``run_logs.RunLogs`` składa wersje z tego modułu.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, assert_never

from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.outbox import ArchiveFile, PeriodThread, Post, Rank
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.version import short_commit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rozliczenia.centrum.run_logs import (
        GuardedLogs,
        GuardedText,
        LoggedDiagnosis,
        LoggedMessage,
        PricingProgress,
        RunLog,
        StartedFacts,
    )

LABEL: Final[Label] = "logi-uruchomienia"

LogsMissing = Literal["niezapisane", "nieczytelne"]
"""Dlaczego start Centrum nie ma Logów Wyceny, która doszła do wyniku: pliku nie ma albo nie da się go odczytać."""

_LOGS_MISSING: Final[dict[LogsMissing, str]] = {
    "niezapisane": "nie ma, Centrum nie zapisało ich po wyniku (np. zamknęło się tuż po nim)",
    "nieczytelne": "plik Logów na komputerze taty jest, ale nie da się go odczytać",
}


@dataclass(frozen=True)
class ResultWithoutLogs:
    """Wynik Wyceny w efenix, której Logów start Centrum nie ma (``logs``): wynik z wpisu końca dziennika Wyceny
    (``result``; ``None``: dziennik go nie ma) i zlecenia z dziennika (``journal``)."""

    journal: PricingProgress
    result: contract.RunResult | None
    logs: LogsMissing


@dataclass(frozen=True)
class ProgressVersion:
    """Postęp Wyceny w efenix ``progress`` z tekstem komentarza po strażniku (``text``)."""

    progress: PricingProgress
    text: GuardedText

    def __post_init__(self) -> None:
        _require_text(self.text)


@dataclass(frozen=True)
class OwnLogs:
    """Logi z pracy Centrum Uruchomienia (z wynikiem albo z Diagnozą): podsumowanie z odnośnikiem i plik w Archiwum."""

    logs: GuardedLogs

    def __post_init__(self) -> None:
        _require_logs(self.logs)


@dataclass(frozen=True)
class StandInLogs:
    """Logi, które start Centrum wysyła z dziennika Wyceny: z pliku albo Logi Urwanego Uruchomienia."""

    logs: GuardedLogs

    def __post_init__(self) -> None:
        _require_logs(self.logs)


@dataclass(frozen=True)
class WithoutLogsVersion:
    """Wynik bez Logów ``final`` z tekstem komentarza po strażniku (``text``), bez pliku w Archiwum."""

    final: ResultWithoutLogs
    text: GuardedText

    def __post_init__(self) -> None:
        _require_text(self.text)


def _require_logs(logs: object) -> None:
    """Wersja z Logami bierze tylko Logi po strażniku (``run_logs._MINTED``): Logi sprzed strażnika podane przez ``Any``
    typ przepuszcza, a tu rzucają ``TypeError``."""

    from rozliczenia.centrum.run_logs import GuardedLogs

    if not isinstance(logs, GuardedLogs):
        raise TypeError("Wersja komentarza Uruchomienia bierze tylko Logi po strażniku z guard_logs.")


def _require_text(text: object) -> None:
    """Postęp i wynik bez Logów biorą tylko tekst po strażniku (``run_logs._MINTED``), także gdy typ go nie widzi."""

    from rozliczenia.centrum.run_logs import GuardedText

    if not isinstance(text, GuardedText):
        raise TypeError("Wersja komentarza Uruchomienia bierze tylko tekst po strażniku z guard_text.")


StandInVersion = StandInLogs | WithoutLogsVersion
"""Wersja zastępcza: to, co start Centrum wysyła z dziennika Wyceny."""

CommentVersion = ProgressVersion | OwnLogs | StandInLogs | WithoutLogsVersion
"""Każda wersja jednego komentarza Uruchomienia."""

JournalAction = Literal["zostaw", "usuń"]
"""Co dalej z dziennikiem Wyceny w efenix, gdy wersja jego komentarza poszła do Kolejki wysyłki."""


def rank_of(version: CommentVersion) -> Rank:
    """Stopień wersji (#910): postęp najniższy, wersja zastępcza środkowy, Logi z pracy Centrum Uruchomienia najwyższy."""

    match version:
        case ProgressVersion():
            return Rank.DRAFT
        case StandInLogs() | WithoutLogsVersion():
            return Rank.STAND_IN
        case OwnLogs():
            return Rank.OWN
        case _:
            assert_never(version)


def journal_after(version: CommentVersion, *, accepted: bool) -> JournalAction:
    """Dziennik Wyceny znika tylko wtedy, gdy kolejka przyjęła (``accepted``) wersję końcową jego komentarza: Logi albo
    wynik bez Logów. Postęp dziennika nie usuwa, bo komentarz mówiłby wtedy, że Uruchomienie trwa, a nikt by go nie
    skończył."""

    match version:
        case ProgressVersion():
            return "zostaw"
        case OwnLogs() | StandInLogs() | WithoutLogsVersion():
            return "usuń" if accepted else "zostaw"
        case _:
            assert_never(version)


def post_of(version: CommentVersion) -> Post:
    """Wysyłka wersji ``version``: jeden komentarz Uruchomienia w issue Logów okresu, a przy Logach także ich pełny plik w
    Archiwum Logów okresu, w stopniu ``rank_of``.

    Identyfikator wysyłki to Uruchomienie (``run_id``) i etykieta ``LABEL``, te same w każdej wersji, więc Logi z
    Diagnozą podmieniają plik w Archiwum i zmieniają komentarz swojego Uruchomienia, a Logi na końcu Wyceny zamieniają jej
    komentarz postępu w podsumowanie (``outbox``).
    """

    start: StartedFacts
    match version:
        case ProgressVersion(progress=progress, text=text):
            start, comment, archive = progress.started, text.text, None
        case OwnLogs(logs=logs) | StandInLogs(logs=logs):
            record = logs.record
            start, comment, archive = record, summary_markdown(record), _archive_file(record)
        case WithoutLogsVersion(final=final, text=text):
            start, comment, archive = final.journal.started, text.text, None
        case _:
            assert_never(version)
    period = start.period
    return Post(
        PeriodThread(
            label=LABEL,
            line=f"- Logi Uruchomienia okresu: {period}",
            closed="reuse",
            title=f"Logi Uruchomienia {period}",
        ),
        period=period,
        run_id=start.run_id,
        header=(
            f"Logi Uruchomień okresu {period} z Centrum rozliczeń taty. Każde Uruchomienie to jeden komentarz: "
            f"podsumowanie i odnośnik do pełnych Logów w Archiwum Logów okresu (Release `logi-{period}`)."
        ),
        parts=(comment + "\n",),
        archive=archive,
        rank=rank_of(version),
    )


def progress_markdown(progress: PricingProgress, *, elapsed_s: float) -> str:
    """Komentarz postępu: proces, tryb, okres, zlecenia skończone z wszystkich i ich wyniki, ostatnie skończone,
    zlecenie w trakcie, czas od startu (``elapsed_s``) i Uruchomienie; odnośnik do pełnych Logów przychodzi z końcem."""

    started = progress.started
    done = progress.done
    orders = _orders_done(progress) or "dziennik Wyceny nie ma jeszcze żadnego zlecenia"
    lines = ["- Wynik: jeszcze nie ma, Uruchomienie trwa", f"- Zlecenia: {orders}"]
    if done:
        last = done[-1]
        code = "" if last.code is None else f", `{last.code}`"
        lines.append(f"- Ostatnie zlecenie: wiersz {last.row}, {last.outcome}{code}")
    if progress.current is not None:
        lines.append(f"- W trakcie: wiersz {progress.current}")
    lines += [
        f"- Czas: {int(elapsed_s // 60)} min do tej pory",
        f"- Uruchomienie: {started.run_id}, start {started.started_at:%Y-%m-%d %H:%M:%S} UTC",
        "- Pełne Logi: w tym komentarzu, gdy Uruchomienie się skończy",
    ]
    return _comment_title(started) + "\n".join(lines)


def without_logs_markdown(final: ResultWithoutLogs) -> str:
    """Wynik bez Logów: proces, tryb, okres, wynik z wpisu końca dziennika, zlecenia skończone z dziennika i ich wyniki,
    zlecenie zaczęte bez wyniku, Uruchomienie i dlaczego pełnych Logów nie ma."""

    journal = final.journal
    started = journal.started
    result = "nieznany, dziennik Wyceny go nie ma" if final.result is None else final.result
    lines = [f"- Wynik: {result}", f"- Zlecenia: {_orders_done(journal) or 'dziennik Wyceny nie ma żadnego zlecenia'}"]
    if journal.current is not None:
        lines.append(f"- Zlecenie bez wyniku: wiersz {journal.current}")
    lines += [
        f"- Uruchomienie: {started.run_id}, start {started.started_at:%Y-%m-%d %H:%M:%S} UTC",
        f"- Pełne Logi: {_LOGS_MISSING[final.logs]}",
    ]
    return _comment_title(started) + "\n".join(lines)


def _comment_title(started: StartedFacts) -> str:
    return f"**Logi Uruchomienia**: {declaration_of(started.process).title}, {started.mode}, okres {started.period}\n\n"


def _orders_done(progress: PricingProgress) -> str | None:
    """Ile zleceń skończonych z wszystkich i ile każdego wyniku (``PricingProgress.outcomes``); ``None`` przed pierwszym
    wpisem „zaczynam zlecenie”."""

    if progress.total is None:
        return None
    outcomes = ", ".join(f"{outcome} {count}" for outcome, count in progress.outcomes())
    return f"{len(progress.done)} z {progress.total} skończone" + (f" ({outcomes})" if outcomes else "")


def _archive_file(record: RunLog) -> ArchiveFile:
    """Pełne Logi w Archiwum Logów okresu: Release z tagiem ``logi-<okres>``, plik o nazwie i treści pliku Logów."""

    period = record.period
    return ArchiveFile(
        tag=f"logi-{period}",
        title=f"Logi Uruchomień {period}",
        description=(
            f"Pełne Logi Uruchomień okresu {period} z Centrum rozliczeń taty: jeden plik na Uruchomienie, nazwany jak "
            "plik Logów na komputerze taty i spakowany gzipem. To nie jest Wydanie narzędzia."
        ),
        name=record.file_name,
        text=record.text,
    )


def summary_markdown(record: RunLog) -> str:
    """Komentarz Logów: proces, tryb, okres, wynik, czas, kody Komunikatów, Diagnoza, Wydanie i odnośnik do pełnych Logów
    w Archiwum Logów okresu."""

    commit = "nieznany" if record.tool.commit is None else short_commit(record.tool.commit)
    diagnosis = "" if record.diagnosis is None else f"- Diagnoza: {_diagnosis(record.diagnosis)}\n"
    archive = _archive_file(record)
    return (
        f"**Logi Uruchomienia**: {declaration_of(record.process).title}, {record.mode}, okres {record.period}\n"
        "\n"
        f"- Wynik: {_result(record)}\n"
        f"- Czas: {_duration(record.duration_ms)}\n"
        f"- Komunikaty: {_codes(record.messages)}\n"
        f"{diagnosis}"
        f"- Wydanie: {record.tool.wydanie or 'brak'}, commit {commit}\n"
        f"- Uruchomienie: {record.run_id}, start {record.started_at:%Y-%m-%d %H:%M:%S} UTC\n"
        f"- Pełne Logi: [{archive.packed_name}]({archive.link})"
    )


def _diagnosis(diagnosis: LoggedDiagnosis) -> str:
    """Kod wyjaśnienia, a po nim sprawdzenia, które nie przeszły albo których nie sprawdzono."""

    groups = [f"`{diagnosis.explanation.code}`"]
    for state, name in (("failed", "nie przeszło"), ("not_checked", "nie sprawdzono")):
        labels = [check.label for check in diagnosis.checks if check.state == state]
        if labels:
            groups.append(f"{name}: {', '.join(labels)}")
    return "; ".join(groups)


def _result(record: RunLog) -> str:
    match record.ending:
        case "finished":
            return f"{record.result}"
        case "stop" | "declined":
            return f"{record.result}, {_stop(record.stop_kind)}"
        case "unexpected":
            return f"{record.result}, nieoczekiwany wyjątek"
        case "after_engine":
            return f"{record.result}, błąd po zakończeniu silnika"
        case "interrupted":
            return "brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)"
        case _:
            assert_never(record.ending)


def _stop(kind: contract.StopKind | None) -> str:
    match kind:
        case "for_tata":
            return "Zatrzymanie dla taty"
        case "for_maks":
            return "Zatrzymanie do Maksa"
        case "repeated":
            return "powtórzone Zatrzymanie dla taty"
        case "declined":
            return "Zatrzymanie po odmowie w Decyzji taty"
        case None:
            return "Zatrzymanie"
        case _:
            assert_never(kind)


def _duration(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "nieznany"
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    return f"{milliseconds / 1000:.1f} s".replace(".", ",")


def _codes(messages: Sequence[LoggedMessage]) -> str:
    """Kody w kolejności karty, każdy raz, z liczbą powtórzeń i rodzajem."""

    counted = Counter((message.kind, message.code) for message in messages)
    if not counted:
        return "brak"
    kinds = {"stop": "Zatrzymanie", "warning": "ostrzeżenie"}
    return ", ".join(
        f"`{code}`{f' ×{count}' if count > 1 else ''} ({kinds[kind]})" for (kind, code), count in counted.items()
    )
