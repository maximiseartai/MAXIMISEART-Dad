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
(``run_logs_guard.GuardedLogs``, ``run_logs_guard.GuardedText``, ADR 0025), więc wysyłka (``post_of``) strażnika nie
potrzebuje, a wersja z tekstem sprzed strażnika to błąd typu, a gdy typ go nie widzi (``Any``), ``TypeError`` w
konstruktorze wersji. Wysyłkę daje tylko ``post_of`` jako ``LogsPost``, której nikt nie zmieni przed kolejką
(docstring ``_VERSIONS``). Dziennik Wyceny znika tylko po wersji końcowej, którą kolejka przyjęła (``journal_after``).

Wersję zastępczą z dziennika, który zostawiła poprzednia praca Centrum, wybiera ``close``: cała macierz startu w jednym
``match``, ze strażnikiem w środku, więc start Centrum (``run_comments.RunComments``) dostaje tylko wersję po strażniku.

Strażnika i typy po nim bierze z ``run_logs_guard``, typy schematu Logów (``run_logs``) i postępu Wyceny tylko do
adnotacji, a z ``logs_disk`` tylko typy wyniku odczytu dysku i nazwę pliku Logów (``name_of``), bez metod, które czytają
pliki (``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, assert_never, final

from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.logs_disk import Found, JournalRead, LeftJournal, Missing, Refused, Unreadable, name_of
from rozliczenia.centrum.outbox import ArchiveFile, PeriodThread, Post, Rank, Target
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.run_logs_guard import GuardedLogs, GuardedText, exact_logs, exact_text, guard_logs, guard_text
from rozliczenia.centrum.version import short_commit
from rozliczenia.client_data import WithoutSubclasses, tool

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rozliczenia.centrum.pricing_progress import PricingProgress
    from rozliczenia.centrum.run_logs import LoggedDiagnosis, LoggedMessage, RunLog, StartFacts
    from rozliczenia.client_data import ForbiddenValues

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
    result: RunResult | None
    logs: LogsMissing


_NO_VERSION_SUBCLASSES: Final = "Wersja komentarza Uruchomienia nie ma podklas: post_of bierze tylko cztery klasy wersji."


@final
@dataclass(frozen=True)
class ProgressVersion(metaclass=WithoutSubclasses):
    progress: PricingProgress
    text: GuardedText

    def __post_init__(self) -> None:
        exact_text(self.text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


@final
@dataclass(frozen=True)
class OwnLogs(metaclass=WithoutSubclasses):
    """Logi z pracy Centrum Uruchomienia (z wynikiem albo z Diagnozą): podsumowanie z odnośnikiem i plik w Archiwum."""

    logs: GuardedLogs

    def __post_init__(self) -> None:
        exact_logs(self.logs)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


@final
@dataclass(frozen=True)
class StandInLogs(metaclass=WithoutSubclasses):
    """Logi, które start Centrum wysyła z dziennika Wyceny: z pliku albo Logi Urwanego Uruchomienia."""

    logs: GuardedLogs

    def __post_init__(self) -> None:
        exact_logs(self.logs)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


@final
@dataclass(frozen=True)
class WithoutLogsVersion(metaclass=WithoutSubclasses):
    """Wynik bez Logów ``final`` z tekstem komentarza po strażniku (``text``), bez pliku w Archiwum."""

    final: ResultWithoutLogs
    text: GuardedText

    def __post_init__(self) -> None:
        exact_text(self.text)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_VERSION_SUBCLASSES)


StandInVersion = StandInLogs | WithoutLogsVersion
"""Wersja zastępcza: to, co start Centrum wysyła z dziennika Wyceny."""

CommentVersion = ProgressVersion | OwnLogs | StandInLogs | WithoutLogsVersion
"""Każda wersja jednego komentarza Uruchomienia."""

JournalAction = Literal["zostaw", "usuń"]
"""Co dalej z dziennikiem Wyceny w efenix, gdy wersja jego komentarza poszła do Kolejki wysyłki."""


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


@dataclass(frozen=True)
class Drop:
    """Dziennik bez pierwszej linii (urwany pierwszy zapis): przed nim nic się w efenix nie zmieniło i żaden postęp do
    niego nie poszedł, więc start Centrum go usuwa."""


Closing = Drop | StandInLogs | WithoutLogsVersion
"""Co start Centrum robi z jednym dziennikiem Wyceny, który zostawiła poprzednia praca Centrum."""


def close(left: LeftJournal, forbidden: ForbiddenValues, interrupted: Callable[[JournalRead], RunLog]) -> Closing:
    """Wersja zastępcza komentarza Uruchomienia z dziennika ``left`` po strażniku reguły danych ``forbidden`` (ADR 0025):

    - dziennik bez pierwszej linii: ``Drop``;
    - czytelny plik Logów: te Logi (``StandInLogs``), czyli Logi z wynikiem, których przyjęcia przez kolejkę nikt nie
      zapisał, albo Logi Urwanego Uruchomienia, które poprzedni start zapisał, a nie wysłał, także sprzed strażnika;
    - plik Logów, którego nie da się odczytać: wynik bez Logów ``nieczytelne`` (Logi są, więc Uruchomienie miało wynik);
    - bez pliku Logów, z wpisem końca: wynik bez Logów ``niezapisane`` z wynikiem z wpisu końca;
    - bez pliku Logów i bez wpisu końca, czyli Urwane Uruchomienie (ADR 0017): Logi Urwanego Uruchomienia z
      ``interrupted``, które bierze działania taty czekające na Logi, więc woła je tylko ta gałąź.

    Strażnik jest w środku: plik Logów i Skrzynka mają te same znaki także po Logach, które zapisała praca Centrum sprzed
    strażnika, a żadna gałąź nie daje Logów ani tekstu sprzed niego. Plik Logów, którego system nie daje odczytać
    (``logs_disk.Refused``), rzuca jego ``OSError``: nie wiadomo, czy Logi są, więc dziennik zostaje następnemu startowi.
    """

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
"""Miejsce zamaskowanej wartości w uwadze technicznej wyniku bez Logów."""


@final
class _Versions:
    """Typ dowodu, że wysyłkę Logów zbudował ``post_of`` (``_VERSIONS``)."""

    __slots__ = ()


_VERSIONS: Final = _Versions()
"""Dowód wersji komentarza: ``LogsPost`` bez niego to błąd mypy (brak argumentu albo zły typ). Bierze go tylko
``post_of``, bez pomocnika, który wkładałby go za wywołującego. Poza tym modułem ruff (``TID251`` w ``pyproject.toml``)
odrzuca ``from … import _VERSIONS`` (także z aliasem) i atrybut modułu (``comment_versions._VERSIONS``, także przez
alias albo pełną ścieżkę), tak samo ``_Versions``.

``LogsPost`` nie jest dataclassą i nie oddaje swojej ``Post``, więc mypy odrzuca ``dataclasses.replace`` gotowej
wysyłki, np. w innym stopniu albo z innymi częściami (``type-var``), a ``replace`` wartości ``Any`` rzuca
``TypeError``. Podklasę odrzuca mypy (``final``). Nową ``Post`` złożoną z pól gotowej wysyłki typ przepuszcza, bo
``Outbox.post`` bierze też gołą ``Post``, a łapie ją ``tests/test_granice_importow.py``: wynik ``post_of`` stoi tylko w
``<kolejka>.post(post_of(…))``, więc nikt nie czyta jego pól, a etykietę Logów (``LABEL``) kod poza ``post_of`` tylko
podaje kolejce w pytaniu (``delivered``, ``rejected``). Granice tych mechanizmów pokazują tam próbki
``ZNANE_LUKI_WYSYLKI``, każda za klasą nazwaną w swojej nazwie."""


@final
class LogsPost(metaclass=WithoutSubclasses):
    """Wysyłka Logów Uruchomienia, którą ``Outbox.post`` bierze tak, jak zbudował ją ``post_of`` (``_VERSIONS``): pola
    tylko do odczytu, bez ``Post`` do skopiowania."""

    __slots__ = ("__post",)

    def __init__(self, post: Post, proof: _Versions) -> None:
        self.__post: Final = post

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("Wysyłka Logów nie ma podklas: daje ją tylko post_of.")

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
    def run_id(self) -> str:
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


def post_of(version: CommentVersion) -> LogsPost:
    """Wysyłka wersji ``version``: jeden komentarz Uruchomienia w issue Logów okresu, a przy Logach także ich pełny plik w
    Archiwum Logów okresu, w stopniu ``rank_of``."""

    start: StartFacts
    match version:
        case ProgressVersion(progress=progress, text=text):
            start, comment, archive = progress.started, text.text, None
        case OwnLogs(logs=logs) | StandInLogs(logs=logs):
            record = logs.record
            start, comment, archive = record.start, summary_markdown(logs), _archive_file(logs)
        case WithoutLogsVersion(final=final, text=text):
            start, comment, archive = final.journal.started, text.text, None
        case _:
            assert_never(version)
    period = start.period
    post = Post(
        PeriodThread(
            label=LABEL,
            line=tool(f"- Logi Uruchomienia okresu: {period}"),
            closed="reuse",
            title=tool(f"Logi Uruchomienia {period}"),
        ),
        period=period,
        run_id=start.run_id,
        header=tool(
            f"Logi Uruchomień okresu {period} z Centrum rozliczeń taty. Każde Uruchomienie to jeden komentarz: "
            f"podsumowanie i odnośnik do pełnych Logów w Archiwum Logów okresu (Release `logi-{period}`)."
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
    """``None`` przed pierwszym wpisem „zaczynam zlecenie”."""

    if progress.total is None:
        return None
    outcomes = ", ".join(f"{outcome.value} {count}" for outcome, count in progress.outcomes())
    return f"{len(progress.done)} z {progress.total} skończone" + (f" ({outcomes})" if outcomes else "")


def _archive_file(logs: GuardedLogs) -> ArchiveFile:
    record = logs.record
    period = record.period
    return ArchiveFile(
        tag=f"logi-{period}",
        title=f"Logi Uruchomień {period}",
        description=(
            f"Pełne Logi Uruchomień okresu {period} z Centrum rozliczeń taty: jeden plik na Uruchomienie, nazwany jak "
            "plik Logów na komputerze taty i spakowany gzipem. To nie jest Wydanie narzędzia."
        ),
        name=name_of(record.start),
        text=logs.text,
    )


def summary_markdown(logs: GuardedLogs) -> str:
    record = logs.record
    commit = "nieznany" if record.tool.commit is None else short_commit(record.tool.commit)
    diagnosis = "" if record.diagnosis is None else f"- Diagnoza: {_diagnosis(record.diagnosis)}\n"
    archive = _archive_file(logs)
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
    """Kody w kolejności karty, każdy raz, z liczbą powtórzeń i rodzajem."""

    counted = Counter((message.kind, message.code) for message in messages)
    if not counted:
        return "brak"
    kinds = {"stop": "Zatrzymanie", "warning": "ostrzeżenie"}
    return ", ".join(
        f"`{code}`{f' ×{count}' if count > 1 else ''} ({kinds[kind]})" for (kind, code), count in counted.items()
    )
