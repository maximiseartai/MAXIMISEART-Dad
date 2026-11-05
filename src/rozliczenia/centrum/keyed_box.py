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

Listy GitHuba nadążają za zapisem po kilku sekundach: lista issue za nowym issue (#879), lista Release'ów za nowym
Archiwum okresu (#887). Kolejka Skrzynki szuka na liście tego, co mogła już zapisać, zanim zapisze, więc ``KeyedBox``
czyta listy po własnych zapisach. Lista issue z etykietą i Archiwum z tagiem (z plikami) pokazują to, co ten
``KeyedBox`` zapisał w ostatnich ``LIST_LAG_S`` (issue i Archiwum, które założył, pliki, które wysłał, bez plików, które
usunął). Zapis, którego skutek widać tylko na liście (zakładanie issue z etykietą, zakładanie Archiwum z tagiem,
wysłanie albo usunięcie pliku Archiwum), jest wstrzymany (``Unreachable`` bez zapytania), gdy ostatnia lista tego samego
przyszła na pytanie zadane mniej niż ``LIST_LAG_S`` po takim zapisie bez odpowiedzi (GitHub mógł go wykonać) albo przez
inny ``KeyedBox``: nowe Centrum, gdy stare jeszcze kończy wysyłkę, albo start po zgaśnięciu. Dlatego przed każdym takim
zapisem ``KeyedBox`` zapisuje jego chwilę w pliku ``opening`` (bez pliku: w pamięci), a odmowa (``Refused``,
``Rejected``) ją zabiera, bo nic się nie zmieniło. Tak druga wysyłka do
issue okresu, Zgłoszenia albo Archiwum w tym samym przejściu kolejki trafia do tego, co założyła pierwsza, a ponowienie
zaraz po zgubionej odpowiedzi czeka na budzenie kolejki, zamiast założyć drugie issue albo dostać odmowę drugiego
Archiwum tego tagu albo drugiego pliku tej nazwy (422) i dopisek, że plik czeka. Chwila jest z zegara Centrum (``time.monotonic``, wspólny dla procesów
jednego komputera do jego restartu), a chwila z przyszłości (po restarcie komputera) jest dawna.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeVar

from rozliczenia.centrum.report_box import (
    Archive,
    ArchiveOutcome,
    Asset,
    CommentOutcome,
    CommentsOutcome,
    FindOutcome,
    Issue,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    Refused,
    Rejected,
    Removed,
    RemoveOutcome,
    ReportBox,
    SendOutcome,
    Sent,
    Unreachable,
    UploadOutcome,
    newest_with_line,
)

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
# Ostatni zapis każdego rodzaju, którego skutek widać tylko na liście (``KeyedBox._ready``), obok klucza; poza
# ``config/zgloszenia``, w którym weryfikacja Kontroli ilości widzi tylko kolejkę.
OPENING_FILE: Final = "skrzynka-zakladanie.txt"
# Sprawdzenie klucza pyta o otwarte Zgłoszenia: zwykle jedna strona, a to samo pytanie zadaje podgląd Zgłoszenia.
_PROBE_LABEL: Final[Label] = "zgloszenie"
# Jak ``tool_freshness.RememberedRelease``: odpowiedź 10 minut, brak odpowiedzi minutę.
ACCEPTED_KEPT_S: Final = 10 * 60
NO_ANSWER_KEPT_S: Final = 60
# Odrzucony klucz nie zmieni się sam: Maks wymienia plik (nowy skrót, więc sprawdzenie od razu) albo uprawnienia tokenu.
REFUSED_KEPT_S: Final = 15 * 60
# Tyle po zapisie lista może go jeszcze nie pokazywać. W nagraniach ``verify-github-skrzynki`` (2026-11-05) lista issue
# nadążyła po 3,0–6,8 s, a lista Release'ów za nowym Archiwum po 2,8 s (#887). Liczy się od chwili zapisu, więc mieści
# też zapytanie do ``report_box._TIMEOUT_S``; mniej niż ``outbox.RETRY_S``, więc ponowienie po budzeniu kolejki już nie
# czeka.
LIST_LAG_S: Final = 30.0

_Outcome = TypeVar("_Outcome")

Writes = dict[str, tuple[float, str]]
"""Zapisy, których skutek widać tylko na liście, po rodzaju (``KeyedBox._ready``): chwila i identyfikator ostatniego."""

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

    def __init__(
        self, box: ReportBox, key: Callable[[], str | None], *, clock: Callable[[], float], opening: Path | None = None
    ) -> None:
        self._box = box
        self._key = key
        self._clock = clock
        self._lock = threading.Lock()
        self._verdict: _Verdict | None = None
        self._no_answer: tuple[str, float] | None = None  # skrót klucza i chwila ostatniego pytania bez odpowiedzi
        self._probe: threading.Thread | None = None
        self._opened: list[tuple[float, Label, Issue]] = []  # chwila odpowiedzi, etykieta i issue, które założył
        self._answered: dict[str, str] = {}  # zapisy tego KeyedBox, na które przyszła odpowiedź
        self._opening = opening
        self._remembered: Writes = {}  # zapisy bez pliku ``opening``
        self._listed_at: dict[str, float] = {}  # chwila ostatniego pytania o listę etykiety albo tagu, na które przyszła
        self._archives: dict[str, tuple[float, int]] = {}  # tag: chwila odpowiedzi i id Archiwum, które założył
        self._uploads: list[tuple[float, int, Asset]] = []  # chwila odpowiedzi, id Archiwum i plik, który wysłał
        self._removals: dict[int, float] = {}  # id pliku, który usunął: chwila odpowiedzi
        self._names: dict[int, str] = {}  # id pliku Archiwum z ostatnich odpowiedzi ``archive``: jego nazwa

    def open_issue(self, label: Label, title: str, body: str) -> SendOutcome | NoKey:
        """Nowe issue; ``Unreachable`` bez zapytania, gdy zakładanie z etykietą ``label`` jest wstrzymane (opis modułu)."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        ready = self._ready(label)
        if ready is None:
            return Unreachable()
        asked_at, write, writes = ready
        outcome = self._box.open_issue(label, title, body, key=key)
        self._observe(key, asked_at, outcome)
        if isinstance(outcome, Sent):
            answered_at = self._clock()
            with self._lock:
                self._opened.append((answered_at, label, Issue(outcome.number, body)))
        self._settled(label, write, writes, created=isinstance(outcome, Sent), refused=isinstance(outcome, Refused | Rejected))
        return outcome

    def _ready(self, kind: str) -> tuple[float, str, Writes] | None:
        """Chwila i identyfikator zapisu ``kind`` (etykieta issue, ``_archive_kind`` albo ``_file_kind``) i zapisy w
        pliku przed nim, zapisane z nim; ``None``: zapis wstrzymany albo pliku ``opening`` nie da się odczytać lub zapisać.

        Identyfikator, a nie chwila, mówi, czyj jest zapis: ``time.monotonic`` na Windows zmienia się co ok. 15 ms, więc
        dwa zapisy mogą mieć tę samą chwilę.
        """

        asked_at = self._clock()
        writes = self._writes()
        if writes is None or self._held(kind, asked_at, writes):
            return None
        write = uuid.uuid4().hex
        if not self._noted({**writes, kind: (asked_at, write)}):
            return None
        return asked_at, write, writes

    def _settled(self, kind: str, write: str, writes: Writes, *, created: bool, refused: bool) -> None:
        """Po odpowiedzi na zapis ``write``: ``created`` (wiadomo, co się zmieniło) nie wstrzymuje tego ``KeyedBox``, a
        ``refused`` (nic się nie zmieniło) przywraca plik sprzed zapisu; bez odpowiedzi zapis zostaje."""

        if created:
            with self._lock:
                self._answered[kind] = write
        if refused:
            self._noted(writes)  # bez tego zapisu następne Centrum tylko poczeka

    def _held(self, kind: str, now: float, writes: Writes) -> bool:
        """Czy ostatnia lista ``kind`` mogła nie pokazywać zapisu bez odpowiedzi albo przez inny ``KeyedBox``: przyszła na
        pytanie zadane mniej niż ``LIST_LAG_S`` po nim (albo przed nim).

        Liczy się chwila pytania o listę, nie ``now``: między listą a zapisem kolejka może jeszcze wysyłać plik do
        Archiwum okresu (``outbox._deliver_to_period``), a chwila zapisu, która w tym czasie dawnieje, nie mówi, że
        lista sprzed niej go pokazała.
        """

        if kind not in writes:
            return False
        moment, write = writes[kind]
        with self._lock:
            answered, listed_at = self._answered.get(kind), self._listed_at.get(_list_of(kind), now)
        return write != answered and 0 <= now - moment and listed_at - moment < LIST_LAG_S

    def _writes(self) -> Writes | None:
        """Zapisy z pliku ``opening``; ``None``: pliku nie da się odczytać (np. trzyma go antywirus), więc zapisu innego
        ``KeyedBox`` nie da się wykluczyć. Treść w innej postaci to brak zapisów."""

        if self._opening is None:
            with self._lock:
                return dict(self._remembered)
        try:
            text = self._opening.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError):
            return None
        try:
            found = json.loads(text)
        except ValueError:
            return {}
        if not isinstance(found, dict):
            return {}
        return {
            kind: (float(entry[0]), entry[1])
            for kind, entry in found.items()
            if isinstance(entry, list)
            and len(entry) == 2
            and isinstance(entry[0], int | float)
            and not isinstance(entry[0], bool)
            and isinstance(entry[1], str)
        }

    def _noted(self, writes: Writes) -> bool:
        """Zapisuje ``writes`` w pliku ``opening`` (bez pliku w pamięci); ``False``: zapis się nie udał.

        Zapisuje do Skrzynki tylko kolejka, w przejściu z blokadą folderu kolejki (``outbox._folder_lock``), więc plik
        czyta i pisze naraz najwyżej jeden proces. Zapis urwany przez zgaśnięcie zostawia treść w innej postaci, czyli
        brak zapisów, a jeden ``write_text`` stu kilkudziesięciu znaków urywa się tylko w tej jednej chwili.
        """

        if self._opening is None:
            with self._lock:
                self._remembered = dict(writes)
            return True
        try:
            self._opening.write_text(json.dumps(writes), encoding="utf-8")
        except OSError:
            return False
        return True

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
        """Archiwum okresu z tagiem ``tag`` z plikami, po zapisach tego ``KeyedBox`` (opis modułu); jego odmowa (brak
        uprawnienia do treści repozytorium) nie jest werdyktem."""

        asked_at = self._clock()
        outcome = self._about_issue(lambda key: self._box.archive(tag, key=key))
        if outcome is not None and not isinstance(outcome, Archive):
            return outcome
        now = self._clock()
        with self._lock:
            self._listed_at[_archive_kind(tag)] = self._listed_at[_FILES_LIST] = asked_at
            self._forget(now)
            opened = self._archives.get(tag)
            found = outcome if outcome is not None else None if opened is None else Archive(opened[1], ())
            if found is None:
                return None
            sent = [asset for _, archive_id, asset in self._uploads if archive_id == found.id]
            removed = set(self._removals)
        listed = [asset for asset in found.assets if asset.id not in removed]
        ids = {asset.id for asset in listed} | removed
        merged = Archive(found.id, (*listed, *(asset for asset in sent if asset.id not in ids)))
        with self._lock:
            self._names.update((asset.id, asset.name) for asset in merged.assets)
        return merged

    def open_archive(self, tag: str, title: str, description: str) -> OpenArchiveOutcome | NoKey:
        """Nowe Archiwum; ``Unreachable`` bez zapytania, gdy zakładanie Archiwum ``tag`` jest wstrzymane (opis modułu)."""

        outcome = self._listed_write(
            _archive_kind(tag), lambda key: self._box.open_archive(tag, title, description, key=key), Archive
        )
        if isinstance(outcome, Archive):
            answered_at = self._clock()
            with self._lock:
                self._archives[tag] = (answered_at, outcome.id)
        return outcome

    def upload(self, archive_id: int, name: str, label: str, data: bytes) -> UploadOutcome | NoKey:
        """Plik w Archiwum; ``Unreachable`` bez zapytania, gdy zapis plików Archiwum jest wstrzymany (opis modułu)."""

        outcome = self._listed_write(
            _file_kind(name), lambda key: self._box.upload(archive_id, name, label, data, key=key), Asset
        )
        if isinstance(outcome, Asset):
            answered_at = self._clock()
            with self._lock:
                self._uploads.append((answered_at, archive_id, outcome))
        return outcome

    def remove(self, asset_id: int) -> RemoveOutcome | NoKey:
        """Usunięcie pliku Archiwum; ``Unreachable`` bez zapytania, gdy zapis plików Archiwum jest wstrzymany."""

        with self._lock:
            name = self._names.get(asset_id, f"#{asset_id}")
        outcome = self._listed_write(_file_kind(name), lambda key: self._box.remove(asset_id, key=key), Removed)
        if isinstance(outcome, Removed):
            answered_at = self._clock()
            with self._lock:
                self._removals[asset_id] = answered_at
        return outcome

    def _listed_write(
        self, kind: str, ask: Callable[[str], _Outcome], done: type[Archive | Asset | Removed]
    ) -> _Outcome | NoKey | Refused | Unreachable:
        """Zapis do Archiwum, którego skutek widać tylko na liście ``kind``: wstrzymany jak zakładanie issue (opis
        modułu), a jego odmowa nie jest werdyktem o kluczu (``_about_issue``)."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        ready = self._ready(kind)
        if ready is None:
            return Unreachable()
        asked_at, write, writes = ready
        outcome = ask(key)
        if not isinstance(outcome, Refused):
            self._observe(key, asked_at, outcome)
        self._settled(kind, write, writes, created=isinstance(outcome, done), refused=isinstance(outcome, Refused | Rejected))
        return outcome

    def _forget(self, now: float) -> None:
        """Pod blokadą: zapisy starsze niż ``LIST_LAG_S``, które listy już pokazują."""

        self._opened = [entry for entry in self._opened if now - entry[0] < LIST_LAG_S]
        self._archives = {tag: entry for tag, entry in self._archives.items() if now - entry[0] < LIST_LAG_S}
        self._uploads = [entry for entry in self._uploads if now - entry[0] < LIST_LAG_S]
        self._removals = {asset: at for asset, at in self._removals.items() if now - at < LIST_LAG_S}

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
        """Issue z etykietą ``label`` z listy Skrzynki i te, które ``KeyedBox`` założył w ``LIST_LAG_S``, a lista ich nie ma."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        asked_at = self._clock()
        listed = self._listed(key, label, include_closed=include_closed)
        if isinstance(listed, Refused | Unreachable):
            return listed
        now = self._clock()
        with self._lock:
            self._listed_at[label] = asked_at
            self._forget(now)
            opened = [issue for _, of, issue in self._opened if of == label]
        numbers = {issue.number for issue in listed}
        return (*listed, *(issue for issue in opened if issue.number not in numbers))

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


# Wysłanie i usunięcie pliku Archiwum widać na liście plików Archiwum (``archive``): rodzaj zapisu to nazwa pliku
# (``_file_kind``), a chwila listy jest wspólna dla wszystkich plików.
_FILE_PREFIX: Final = "plik "
_FILES_LIST: Final = "pliki archiwum"


def _file_kind(name: str) -> str:
    """Rodzaj zapisu pliku Archiwum o nazwie ``name`` w pliku ``opening``."""

    return f"{_FILE_PREFIX}{name}"


def _list_of(kind: str) -> str:
    """Lista, która pokazuje zapis rodzaju ``kind``: plik Archiwum na liście plików, inny zapis na swojej."""

    return _FILES_LIST if kind.startswith(_FILE_PREFIX) else kind


def _archive_kind(tag: str) -> str:
    """Klucz Archiwum z tagiem ``tag`` w pliku ``opening`` i w pamięci zapisów, obok etykiet issue."""

    return f"archiwum {tag}"


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
