"""Skrzynka Zgłoszeń z kluczem taty: jedyne miejsce, które czyta klucz i wie, czy Skrzynka go przyjmuje.

Kolejka Skrzynki, Powiadomienia i Zgłoszenia pytają Skrzynkę tylko przez ``KeyedBox``; nikt poza nim nie czyta
``config/zgloszenia-klucz.txt`` i nie podaje klucza adapterowi. Bez pliku klucza każda operacja to ``NoKey`` bez
zapytania. Każda odpowiedź adaptera na pytanie z kluczem jest werdyktem o tym kluczu: odmowa przy zakładaniu issue
albo liście issue to „klucz odrzucony”, każda inna odpowiedź Skrzynki (także odmowa treści) to „klucz przyjęty”, a
brak sieci niczego nie zmienia. Odmowa komentarza, pytania o komentarze issue i poprawki komentarza mówi o issue
(404: Maks je usunął, #402), nie o kluczu, więc werdyktu nie zmienia; każda wysyłka kolejki najpierw pyta o listę
albo zakłada issue, więc zły klucz i tak wyjdzie przed komentarzem. Odmowa kroków Archiwum okresu (#844) też nie zmienia
werdyktu: mówi o uprawnieniu klucza do zapisu treści repozytorium, którego issue nie potrzebują, a tata, który zobaczyłby
niedziałający Token do Zgłoszeń, nie ma czego naprawiać, gdy Zgłoszenia i komentarze dochodzą.

Werdykt należy do klucza (skrót SHA-256): Maks, który wpisze nowy klucz, dostaje nowe sprawdzenie od razu.
Odrzucony klucz Centrum pamięta ``REFUSED_KEPT_S`` i przez ten czas nie wysyła nim żadnego zapytania: kolejka,
Powiadomienia i szukanie otwartego Zgłoszenia dostają ``Refused`` bez sieci. To jest wolniejsze tempo prób przy
odrzuconym kluczu. Przyjęty klucz jest ważny ``ACCEPTED_KEPT_S``; po tym czasie albo bez żadnego werdyktu ``judge``
zleca jedno tanie sprawdzenie (lista otwartych Zgłoszeń), najwyżej jedno naraz, a po pytaniu bez odpowiedzi nie
częściej niż co ``NO_ANSWER_KEPT_S``. Werdykt ustala najnowsze pytanie, nie najpóźniejsza odpowiedź: spóźnione
„przyjęty” sprzed odmowy jej nie cofa.
"""

from __future__ import annotations

import codecs
import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeVar

from rozliczenia.centrum.report_box import (
    ArchiveOutcome,
    CommentOutcome,
    CommentsOutcome,
    FindOutcome,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    Refused,
    RemoveOutcome,
    ReportBox,
    SendOutcome,
    Unreachable,
    UploadOutcome,
    newest_with_line,
)

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
# Sprawdzenie klucza pyta o otwarte Zgłoszenia: zwykle jedna strona, a to samo pytanie zadaje podgląd Zgłoszenia.
_PROBE_LABEL: Final[Label] = "zgloszenie"
# Jak ``tool_freshness.RememberedRelease``: odpowiedź 10 minut, brak odpowiedzi minutę.
ACCEPTED_KEPT_S: Final = 10 * 60
NO_ANSWER_KEPT_S: Final = 60
# Odrzucony klucz nie zmieni się sam: Maks wymienia plik (nowy skrót, więc sprawdzenie od razu) albo uprawnienia tokenu.
REFUSED_KEPT_S: Final = 15 * 60

_Outcome = TypeVar("_Outcome")

KeyJudgement = Literal["accepted", "refused", "unchecked", "missing"]
"""Co wiadomo o kluczu: przyjęty, odrzucony, jeszcze bez odpowiedzi Skrzynki (np. brak sieci) albo brak pliku klucza.

Konfiguracja i Diagnoza tłumaczą go każda swoją tabelą, jak ``tool_freshness.Judgement``.
"""


@dataclass(frozen=True)
class NoKey:
    """Na tym komputerze nie ma klucza do Zgłoszeń: Skrzynki nikt nie pytał."""


@dataclass(frozen=True)
class _Verdict:
    """Odpowiedź Skrzynki o kluczu o skrócie ``key``: czy odmówiła i kiedy zadano pytanie, które ją dało."""

    key: str
    refused: bool
    asked_at: float


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyedBox:
    """Skrzynka Zgłoszeń z kluczem taty i werdyktem o nim (opis modułu).

    Te same operacje co ``ReportBox`` (także Archiwum okresu) bez ``key=`` i z kolejną porażką ``NoKey``, plus ``find_issue``,
    ``judge`` (stan klucza w ograniczonym czasie) i ``check_in_background`` (sprawdzenie przy starcie Centrum).
    Blokada chroni tylko werdykt i sprawdzenie w tle; zapytania do Skrzynki idą bez niej.
    """

    def __init__(self, box: ReportBox, key: Callable[[], str | None], *, clock: Callable[[], float]) -> None:
        self._box = box
        self._key = key
        self._clock = clock
        self._lock = threading.Lock()
        self._verdict: _Verdict | None = None
        self._no_answer: tuple[str, float] | None = None  # skrót klucza i chwila ostatniego pytania bez odpowiedzi
        self._probe: threading.Thread | None = None

    def open_issue(self, label: Label, title: str, body: str) -> SendOutcome | NoKey:
        key = self._usable()
        if not isinstance(key, str):
            return key
        asked_at = self._clock()
        outcome = self._box.open_issue(label, title, body, key=key)
        self._observe(key, asked_at, outcome)
        return outcome

    def comment(self, number: int, body: str) -> CommentOutcome | NoKey:
        """Komentarz; jego odmowa (404 usuniętego issue) nie jest werdyktem o kluczu, przyjęcie jest."""

        return self._about_issue(lambda key: self._box.comment(number, body, key=key))

    def comments(self, number: int) -> CommentsOutcome | NoKey:
        """Komentarze issue; odmowa (404 usuniętego issue) nie jest werdyktem o kluczu, odpowiedź jest."""

        return self._about_issue(lambda key: self._box.comments(number, key=key))

    def edit_comment(self, comment_id: int, body: str) -> CommentOutcome | NoKey:
        """Poprawka komentarza; jej odmowa (404 usuniętego komentarza albo issue) nie jest werdyktem o kluczu."""

        return self._about_issue(lambda key: self._box.edit_comment(comment_id, body, key=key))

    def archive(self, tag: str) -> ArchiveOutcome | NoKey:
        """Archiwum okresu z tagiem ``tag``; jego odmowa (brak uprawnienia do treści repozytorium) nie jest werdyktem."""

        return self._about_issue(lambda key: self._box.archive(tag, key=key))

    def open_archive(self, tag: str, title: str, description: str) -> OpenArchiveOutcome | NoKey:
        return self._about_issue(lambda key: self._box.open_archive(tag, title, description, key=key))

    def upload(self, archive_id: int, name: str, label: str, data: bytes) -> UploadOutcome | NoKey:
        return self._about_issue(lambda key: self._box.upload(archive_id, name, label, data, key=key))

    def remove(self, asset_id: int) -> RemoveOutcome | NoKey:
        return self._about_issue(lambda key: self._box.remove(asset_id, key=key))

    def _about_issue(self, ask: Callable[[str], _Outcome]) -> _Outcome | NoKey | Refused:
        """Pytanie o jedno issue albo o Archiwum okresu: odpowiedź poza odmową jest werdyktem o kluczu."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        asked_at = self._clock()
        outcome = ask(key)
        if not isinstance(outcome, Refused):
            self._observe(key, asked_at, outcome)
        return outcome

    def labelled_issues(self, label: Label, *, include_closed: bool) -> IssuesOutcome | NoKey:
        key = self._usable()
        return key if not isinstance(key, str) else self._listed(key, label, include_closed=include_closed)

    def find_issue(self, label: Label, line: str, *, include_closed: bool) -> FindOutcome | NoKey:
        """Najnowsze issue z etykietą ``label`` i wierszem ``line`` (odcisk problemu, token okresu)."""

        issues = self.labelled_issues(label, include_closed=include_closed)
        if isinstance(issues, NoKey | Refused | Unreachable):
            return issues
        return newest_with_line(issues, line)

    def judge(self, *, wait_s: float) -> KeyJudgement:
        """Stan klucza teraz; gdy sprawdzenie jest należne, zleca je w tle i czeka na nie najwyżej ``wait_s``."""

        key = self._key()
        if key is None:
            return "missing"
        digest = _digest(key)
        with self._lock:
            probe = None
            if self._due(digest, self._clock()):
                if self._probe is None or not self._probe.is_alive():
                    self._probe = threading.Thread(target=self._check, args=(key,), name="skrzynka-klucz", daemon=True)
                    self._probe.start()
                probe = self._probe
        if probe is not None:
            probe.join(wait_s)
        with self._lock:
            verdict = self._verdict
        if verdict is None or verdict.key != digest:
            return "unchecked"
        return "refused" if verdict.refused else "accepted"

    def check_in_background(self) -> None:
        """Przy starcie Centrum: sprawdzenie klucza w tle, żeby pierwsza Konfiguracja nie czekała na Skrzynkę."""

        self.judge(wait_s=0)

    def _check(self, key: str) -> None:
        """Sprawdzenie w tle: jedno tanie pytanie o otwarte Zgłoszenia, także odrzuconym kluczem, któremu minęła pamięć."""

        self._listed(key, _PROBE_LABEL, include_closed=False)

    def _listed(self, key: str, label: Label, *, include_closed: bool) -> IssuesOutcome:
        asked_at = self._clock()
        outcome = self._box.labelled_issues(label, include_closed=include_closed, key=key)
        self._observe(key, asked_at, outcome)
        return outcome

    def _usable(self) -> str | NoKey | Refused:
        """Klucz do zapytania; ``Refused`` bez sieci, gdy Skrzynka odrzuciła ten klucz w ``REFUSED_KEPT_S``."""

        key = self._key()
        if key is None:
            return NoKey()
        with self._lock:
            verdict = self._verdict
            if (
                verdict is not None
                and verdict.refused
                and verdict.key == _digest(key)
                and self._clock() - verdict.asked_at < REFUSED_KEPT_S
            ):
                return Refused()
        return key

    def _observe(self, key: str, asked_at: float, outcome: object) -> None:
        """Werdykt z odpowiedzi na pytanie zadane w ``asked_at``; pytanie starsze niż obecny werdykt nic nie zmienia."""

        digest = _digest(key)
        with self._lock:
            if isinstance(outcome, Unreachable):
                self._no_answer = (digest, asked_at)
                return
            if self._verdict is not None and self._verdict.asked_at > asked_at:
                return
            self._verdict = _Verdict(digest, isinstance(outcome, Refused), asked_at)

    def _due(self, key: str, now: float) -> bool:
        """Sprawdzenie należne (pod blokadą): brak werdyktu tego klucza albo werdykt starszy niż jego ważność.

        Po pytaniu tym kluczem bez odpowiedzi dopiero po ``NO_ANSWER_KEPT_S``.
        """

        no_answer, verdict = self._no_answer, self._verdict
        silent = no_answer is not None and no_answer[0] == key and now - no_answer[1] < NO_ANSWER_KEPT_S
        if verdict is None or verdict.key != key:
            return not silent
        return not silent and now - verdict.asked_at >= (REFUSED_KEPT_S if verdict.refused else ACCEPTED_KEPT_S)


def read_report_key(config_directory: Path) -> str | None:
    """Klucz do Skrzynki Zgłoszeń z lokalnego pliku; ``None``, gdy pliku nie ma albo jest pusty."""

    try:
        content = (config_directory / REPORT_KEY_FILE).read_bytes()
        # Notatnik dopisuje BOM UTF-8, a ``>`` i ``Out-File`` w PowerShell 5.1 zapisują UTF-16 z BOM.
        encoding = "utf-16" if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
        key = content.decode(encoding).strip()
    except (OSError, UnicodeError):
        return None
    return key or None
