from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, assert_never, final, get_args

from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.box_prefix import tagged, titled
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.logs_disk import Found, JournalRead, LeftJournal, Missing, Refused, Unreadable, name_of
from rozliczenia.centrum.outbox import ArchiveFile, PeriodThread, Post, Rank, Target
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.scope import BoxPrefix
from rozliczenia.centrum.run_logs_guard import GuardedLogs, GuardedText, exact_logs, exact_text, guard_logs, guard_text, tool_text
from rozliczenia.centrum.version import short_commit
from rozliczenia.client_data import WithoutSubclasses, tool

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rozliczenia.centrum.pricing_progress import PricingProgress
    from rozliczenia.centrum.run_logs import LoggedDiagnosis, LoggedMessage, RunLog, StartFacts
    from rozliczenia.centrum.template_archive import ArchivedTemplate
    from rozliczenia.client_data import ForbiddenValues, Outgoing

LABEL: Final[Label] = "logi-uruchomienia"

LogsMissing = Literal["niezapisane", "nieczytelne"]

_LOGS_MISSING: Final[dict[LogsMissing, str]] = {
    "niezapisane": "nie ma, Centrum nie zapisało ich po wyniku (np. zamknęło się tuż po nim)",
    "nieczytelne": "plik Logów na komputerze taty jest, ale nie da się go odczytać",
}


@dataclass(frozen=True)
class ResultWithoutLogs:
    journal: PricingProgress
    result: RunResult | None
    logs: LogsMissing


_NO_VERSION_SUBCLASSES: Final = "Wersja komentarza Uruchomienia nie ma podklas: post_of bierze tylko cztery klasy wersji."


@final
@dataclass(frozen=True)
class ProgressVersion(metaclass=WithoutSubclasses, refusal=_NO_VERSION_SUBCLASSES):
    progress: PricingProgress
    text: GuardedText

    def __post_init__(self) -> None:
        exact_text(self.text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


@final
@dataclass(frozen=True)
class OwnLogs(metaclass=WithoutSubclasses, refusal=_NO_VERSION_SUBCLASSES):
    logs: GuardedLogs
    templates: tuple[ArchivedTemplate, ...] = ()

    def __post_init__(self) -> None:
        exact_logs(self.logs)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


@final
@dataclass(frozen=True)
class StandInLogs(metaclass=WithoutSubclasses, refusal=_NO_VERSION_SUBCLASSES):
    logs: GuardedLogs

    def __post_init__(self) -> None:
        exact_logs(self.logs)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


@final
@dataclass(frozen=True)
class WithoutLogsVersion(metaclass=WithoutSubclasses, refusal=_NO_VERSION_SUBCLASSES):
    final: ResultWithoutLogs
    text: GuardedText

    def __post_init__(self) -> None:
        exact_text(self.text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


StandInVersion = StandInLogs | WithoutLogsVersion

CommentVersion = ProgressVersion | OwnLogs | StandInLogs | WithoutLogsVersion

JournalAction = Literal["zostaw", "usuń"]


def rank_of(version: CommentVersion) -> Rank:
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
    match version:
        case ProgressVersion():
            return "zostaw"
        case OwnLogs() | StandInLogs() | WithoutLogsVersion():
            return "usuń" if accepted else "zostaw"
        case _:
            assert_never(version)


@dataclass(frozen=True)
class Drop:
    ...


Closing = Drop | StandInLogs | WithoutLogsVersion


def close(left: LeftJournal, forbidden: ForbiddenValues, interrupted: Callable[[JournalRead], RunLog]) -> Closing:
    read = left.journal
    if read is None:
        return Drop()
    final: ResultWithoutLogs
    match left.logs:
        case Found(logs=record):
            return StandInLogs(guard_logs(record, forbidden))
        case Refused(failure=failure):
            raise failure
        case Unreadable():
            final = ResultWithoutLogs(read.progress, None if read.end is None else read.end.result, "nieczytelne")
        case Missing() if read.end is not None:
            final = ResultWithoutLogs(read.progress, read.end.result, "niezapisane")
        case Missing():
            return StandInLogs(guard_logs(interrupted(read), forbidden))
        case _:
            assert_never(left.logs)
    return WithoutLogsVersion(final, guard_text(without_logs_markdown(final), _WITHOUT_LOGS_PLACE, forbidden))


_WITHOUT_LOGS_PLACE: Final = "wynik Wyceny w efenix bez Logów"


@final
class _Versions:
    __slots__ = ()


_VERSIONS: Final = _Versions()


_NO_POST_SUBCLASSES: Final = "Wysyłka Logów nie ma podklas: daje ją tylko post_of."


@final
class LogsPost(metaclass=WithoutSubclasses, refusal=_NO_POST_SUBCLASSES):
    __slots__ = ("__post",)

    def __init__(self, post: Post, proof: _Versions) -> None:
        self.__post: Final = post

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_POST_SUBCLASSES)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LogsPost) and self.__post == other.__post

    def __hash__(self) -> int:
        return hash(self.__post)

    def __repr__(self) -> str:
        return f"LogsPost({self.__post!r})"

    @property
    def target(self) -> Target:
        return self.__post.target

    @property
    def period(self) -> str | None:
        return self.__post.period

    @property
    def run_id(self) -> Outgoing:
        return self.__post.run_id

    @property
    def header(self) -> str | None:
        return self.__post.header

    @property
    def parts(self) -> tuple[str, ...]:
        return self.__post.parts

    @property
    def archive(self) -> ArchiveFile | None:
        return self.__post.archive

    @property
    def rank(self) -> Rank:
        return self.__post.rank

    def to_json(self) -> str:
        return self.__post.to_json()


def post_of(version: CommentVersion, *, prefix: BoxPrefix | None = None) -> LogsPost:
    if not any(type(version) is kind for kind in get_args(CommentVersion)):
        raise TypeError(f"Wysyłkę Logów daje post_of tylko z wersji komentarza Uruchomienia, nie {type(version).__name__}.")
    start: StartFacts
    match version:
        case ProgressVersion(progress=progress, text=text):
            start, comment, archive = progress.started, exact_text(text).text, None
        case OwnLogs(logs=logs, templates=templates):
            checked = exact_logs(logs)
            start = checked.record.start
            comment, archive = summary_markdown(checked, prefix=prefix), _archive_file(checked, prefix, templates)
        case StandInLogs(logs=logs):
            checked = exact_logs(logs)
            start = checked.record.start
            comment, archive = summary_markdown(checked, prefix=prefix), _archive_file(checked, prefix)
        case WithoutLogsVersion(final=final, text=text):
            start, comment, archive = final.journal.started, exact_text(text).text, None
        case _:
            assert_never(version)
    period = tool_text("RunLog.period", start.period)
    post = Post(
        PeriodThread(
            label=LABEL,
            line=tool(f"- Logi Uruchomienia okresu: {period}"),
            closed="reuse",
            title=titled(prefix, tool(f"Logi Uruchomienia {period}")),
        ),
        period=period,
        run_id=tool(tool_text("RunLog.run_id", start.run_id)),
        header=tool(
            f"Logi Uruchomień okresu {period} z Centrum rozliczeń taty. Każde Uruchomienie to jeden komentarz: "
            f"podsumowanie i odnośnik do pełnych Logów w Archiwum Logów okresu (Release `{_tag(prefix, period)}`)."
        ),
        parts=(tool(comment + "\n"),),
        archive=archive,
        rank=rank_of(version),
    )
    return LogsPost(post, _VERSIONS)


def progress_markdown(progress: PricingProgress, *, elapsed_s: float) -> str:
    started = progress.started
    done = progress.done
    orders = _orders_done(progress) or "dziennik Wyceny nie ma jeszcze żadnego zlecenia"
    lines = ["- Wynik: jeszcze nie ma, Uruchomienie trwa", f"- Zlecenia: {orders}"]
    if done:
        last = done[-1]
        code = "" if last.code is None else f", `{last.code}`"
        lines.append(f"- Ostatnie zlecenie: wiersz {last.row}, {last.outcome.value}{code}")
    if progress.current is not None:
        lines.append(f"- W trakcie: wiersz {progress.current}")
    lines += [
        f"- Czas: {int(elapsed_s // 60)} min do tej pory",
        _run_line(started),
        "- Pełne Logi: w tym komentarzu, gdy Uruchomienie się skończy",
    ]
    return _comment_title(started) + "\n".join(lines)


def without_logs_markdown(final: ResultWithoutLogs) -> str:
    journal = final.journal
    started = journal.started
    result = "nieznany, dziennik Wyceny go nie ma" if final.result is None else final.result
    lines = [f"- Wynik: {result}", f"- Zlecenia: {_orders_done(journal) or 'dziennik Wyceny nie ma żadnego zlecenia'}"]
    if journal.current is not None:
        lines.append(f"- Zlecenie bez wyniku: wiersz {journal.current}")
    lines += [
        _run_line(started),
        f"- Pełne Logi: {_LOGS_MISSING[final.logs]}",
    ]
    return _comment_title(started) + "\n".join(lines)


def _comment_title(run: StartFacts | RunLog) -> str:
    return f"**Logi Uruchomienia**: {declaration_of(run.process).title}, {run.mode.word}, okres {run.period}\n\n"


def _run_line(run: StartFacts | RunLog) -> str:
    return f"- Uruchomienie: {run.run_id}, start {run.started_at:%Y-%m-%d %H:%M:%S} UTC"


def _orders_done(progress: PricingProgress) -> str | None:
    if progress.total is None:
        return None
    outcomes = ", ".join(f"{outcome.value} {count}" for outcome, count in progress.outcomes())
    return f"{len(progress.done)} z {progress.total} skończone" + (f" ({outcomes})" if outcomes else "")


def _tag(prefix: BoxPrefix | None, period: str) -> Outgoing:
    return tagged(prefix, tool(f"logi-{period}"))


def _archive_file(logs: GuardedLogs, prefix: BoxPrefix | None, templates: tuple[ArchivedTemplate, ...] = ()) -> ArchiveFile:
    record = logs.record
    period = record.period
    return ArchiveFile(
        tag=_tag(prefix, period),
        title=titled(prefix, tool(f"Logi Uruchomień {period}")),
        description=tool(
            f"Pełne Logi Uruchomień okresu {period} z Centrum rozliczeń taty: jeden plik na Uruchomienie, nazwany jak "
            "plik Logów na komputerze taty i spakowany gzipem, a obok Wzorce taty, którymi liczyły, każda wersja raz "
            "jako wzorzec-<SHA-256>.xlsx. To nie jest Wydanie narzędzia."
        ),
        name=tool(name_of(record.start)),
        text=logs.text,
        templates=templates,
    )


def summary_markdown(logs: GuardedLogs, *, prefix: BoxPrefix | None = None) -> str:
    record = logs.record
    commit = "nieznany" if record.tool.commit is None else short_commit(record.tool.commit)
    diagnosis = "" if record.diagnosis is None else f"- Diagnoza: {_diagnosis(record.diagnosis)}\n"
    archive = _archive_file(logs, prefix)
    return (
        _comment_title(record)
        + f"- Wynik: {_result(record)}\n"
        f"- Czas: {_duration(record.duration_ms)}\n"
        f"- Komunikaty: {_codes(record.messages)}\n"
        f"{diagnosis}"
        f"- Wydanie: {record.tool.wydanie or 'brak'}, commit {commit}\n"
        f"{_run_line(record)}\n"
        f"- Pełne Logi: [{archive.packed_name}]({archive.link})"
    )


def _diagnosis(diagnosis: LoggedDiagnosis) -> str:
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


def _stop(kind: runs_contract.StopKind | None) -> str:
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
    counted = Counter((message.kind, message.code) for message in messages)
    if not counted:
        return "brak"
    kinds = {"stop": "Zatrzymanie", "warning": "ostrzeżenie"}
    return ", ".join(
        f"`{code}`{f' ×{count}' if count > 1 else ''} ({kinds[kind]})" for (kind, code), count in counted.items()
    )
