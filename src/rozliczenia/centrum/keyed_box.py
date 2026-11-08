"""Skrzynka Zgłoszeń z kluczem taty: jedyne miejsce, które czyta klucz i wie, czy Skrzynka go przyjmuje.

Kolejka Skrzynki, Powiadomienia i Zgłoszenia pytają Skrzynkę tylko przez ``KeyedBox``; nikt poza nim nie czyta
``config/zgloszenia-klucz.txt`` i nie podaje klucza adapterowi. Jedynym innym odbiorcą klucza jest Aktualność narzędzia:
``github_key`` daje jej klucz do pytań o Wydania publicznego repozytorium (wyższy limit pytań API GitHuba), a odpowiedź na
nie, także odmowa, nie jest werdyktem o kluczu (``tool_freshness``). Bez pliku klucza każda operacja to ``NoKey`` bez
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
czyta listy po zapisach. Każdy zapis, którego skutek widać tylko na liście (zakładanie issue z etykietą, zakładanie
Archiwum z tagiem, wysłanie albo usunięcie pliku Archiwum), ``KeyedBox`` najpierw notuje z chwilą i identyfikatorem w
pliku ``opening`` (bez pliku: w pamięci). Odpowiedź ze skutkiem zamienia ten zapis na skutek (issue, Archiwum, plik,
usunięcie) z chwilą odpowiedzi, a odmowa (``Refused``, ``Rejected``) go zabiera, bo nic się nie zmieniło. Lista issue z
etykietą i Archiwum z tagiem (z plikami) pokazują skutki z ostatnich ``LIST_LAG_S``, także zapisane przez inny
``KeyedBox``: nowe Centrum po zgaśnięciu albo po ponownym starcie zna skutki starego. Lista bez zamkniętych pomija
issue, które Maks zamknął: skutek, którego ta lista nie ma, dołącza tylko wtedy, gdy lista z zamkniętymi nie ma go
zamkniętego. Zapis jest wstrzymany (``Unreachable`` bez zapytania), gdy w pliku czeka zapis tego rodzaju bez
odpowiedzi (zgubiona odpowiedź albo zapis innego Centrum, które jeszcze kończy wysyłkę), a ostatnia lista tego rodzaju
w tym wątku przyszła na pytanie zadane mniej niż ``LIST_LAG_S`` po nim (albo przed nim): GitHub mógł go wykonać, a
nikt nie zna jego skutku. Tak druga wysyłka do issue okresu, Zgłoszenia albo Archiwum w tym samym przejściu kolejki
albo w nowym Centrum trafia do tego, co założyła pierwsza, a ponowienie zaraz po zgubionej odpowiedzi czeka na
budzenie kolejki, zamiast założyć drugie issue albo dostać odmowę drugiego Archiwum tego tagu albo drugiego pliku tej
nazwy (422) i dopisek, że plik czeka. Chwila jest z zegara Centrum (``time.monotonic``, wspólny dla procesów jednego
komputera do jego restartu), a chwila z przyszłości (po restarcie komputera) jest dawna.

Plik ``opening``, którego nie da się odczytać (``OSError``, np. trzyma go antywirus), nie wyklucza zapisu, którego
``KeyedBox`` nie zna, więc zapis i lista mają jedną zasadę (#909): zapis jest wstrzymany, gdy nie da się odczytać pliku
przy nim albo przy ostatniej liście jego rodzaju w tym wątku, a pierwsza lista tego rodzaju, przy której plik się
odczyta, wstrzymanie zdejmuje. Lista pokazuje wtedy to, co pokazuje GitHub. Tę samą zasadę ma brak issue o znanym
numerze na liście (``known_issue``, #915): kolejka uznaje, że issue zniknęło, tylko gdy zapis z jego etykietą nie byłby
wstrzymany, bo inaczej lista mogła jeszcze nie pokazać świeżego issue. Plik, którego treść nie jest UTF-8, to
treść w innej postaci (brak zapisów), którą następny zapis zastąpi. Plik, którego nie da się odczytać ani zapisać na
stałe, wstrzymuje każdy zapis do Skrzynki: kolejka czeka jak bez sieci i ponawia co budzenie, a dziennik Centrum dostaje
raz na pracę Centrum linię z typem błędu (``NotesFile.unavailable``), jak przy pliku kolejki, którego nie da się odczytać.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeVar

from rozliczenia.centrum.github import ANSWER_KEPT_S, NO_ANSWER_KEPT_S, sendable
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
from rozliczenia.centrum.report_issue import LABEL as REPORT_LABEL

REPORT_KEY_FILE: Final = "zgloszenia-klucz.txt"
# Ostatni zapis każdego rodzaju, którego skutek widać tylko na liście (``KeyedBox._ready``), obok klucza; poza
# ``config/zgloszenia``, w którym weryfikacja Kontroli ilości widzi tylko kolejkę.
OPENING_FILE: Final = "skrzynka-zakladanie.txt"
# Przyjęty klucz Centrum pamięta jak każdą odpowiedź GitHuba, a brak odpowiedzi o kluczu jak każdy brak odpowiedzi.
ACCEPTED_KEPT_S: Final = ANSWER_KEPT_S
# Odrzucony klucz nie zmieni się sam: Maks wymienia plik (nowy skrót, więc sprawdzenie od razu) albo uprawnienia tokenu.
REFUSED_KEPT_S: Final = 15 * 60
# Tyle po zapisie lista może go jeszcze nie pokazywać. W nagraniach ``verify-github-skrzynki`` (2026-11-05) lista issue
# nadążyła po 3,0–6,8 s, a lista Release'ów za nowym Archiwum po 2,8 s (#887). Liczy się od chwili zapisu, więc mieści
# też zapytanie do ``report_box._TIMEOUT_S``; mniej niż ``outbox.RETRY_S`` (test w ``test_klucz_zgloszen.py``), więc
# ponowienie po budzeniu kolejki już nie czeka.
LIST_LAG_S: Final = 30.0
# Zapis bez odpowiedzi dawniejszy niż to nie wstrzyma już żadnego zapisu: lista, na której kolejka opiera zapis, jest
# najwyżej kilka zapytań (każde do ``report_box._TIMEOUT_S``) przed nim, więc każda późniejsza jest dużo po nim.
PENDING_KEPT_S: Final = 60 * 60.0

_Outcome = TypeVar("_Outcome")


def _unnoticed(failure: OSError) -> None:
    """Bez dziennika: nieudany odczyt albo zapis pliku zapisów tylko wstrzymuje zapisy (opis modułu)."""


@dataclass(frozen=True)
class NotesFile:
    """Plik zapisów ``KeyedBox`` (opis modułu) i jego zamiana: u taty ``atomic_file.replace_atomically`` (``create_app``),
    która czeka na plik, który ktoś na chwilę trzyma, jak przy innych plikach Centrum, i nie zostawia urwanego pliku.
    ``unavailable`` dostaje pierwszy błąd odczytu albo zapisu pliku w tej pracy Centrum (u taty dziennik Centrum)."""

    path: Path
    replace: Callable[[Path, str], None]
    unavailable: Callable[[OSError], None] = _unnoticed


@dataclass
class _Notes:
    """Zapisy w pliku ``opening`` (opis modułu): po rodzaju (``KeyedBox._ready``) chwila i identyfikator zapisu bez
    odpowiedzi, a każdy skutek zapisu z odpowiedzią z jej chwilą: issue z etykietą, Archiwum z tagiem, plik w Archiwum
    o id i usunięty plik."""

    pending: dict[str, tuple[float, str]] = field(default_factory=dict)
    opened: list[tuple[float, str, Issue]] = field(default_factory=list)
    archives: list[tuple[float, str, int]] = field(default_factory=list)
    uploads: list[tuple[float, int, Asset]] = field(default_factory=list)
    removals: list[tuple[float, int]] = field(default_factory=list)

    def fresh(self, now: float) -> _Notes:
        """Bez skutków, których odpowiedź przyszła ``LIST_LAG_S`` temu albo dawniej (listy już je pokazują), i bez zapisów
        bez odpowiedzi sprzed ``PENDING_KEPT_S``; chwila z przyszłości (sprzed restartu komputera) jest dawna."""

        def fresh(at: float, kept: float = LIST_LAG_S) -> bool:
            return 0 <= now - at < kept

        return _Notes(
            {kind: entry for kind, entry in self.pending.items() if fresh(entry[0], PENDING_KEPT_S)},
            [entry for entry in self.opened if fresh(entry[0])],
            [entry for entry in self.archives if fresh(entry[0])],
            [entry for entry in self.uploads if fresh(entry[0])],
            [entry for entry in self.removals if fresh(entry[0])],
        )

    def dumped(self) -> str:
        return json.dumps(
            {
                "zapisy": {kind: list(entry) for kind, entry in self.pending.items()},
                "issue": [[at, label, issue.number, issue.body] for at, label, issue in self.opened],
                "archiwa": [list(entry) for entry in self.archives],
                "pliki": [[at, archive, asset.id, asset.name, asset.label] for at, archive, asset in self.uploads],
                "usuniete": [list(entry) for entry in self.removals],
            },
            ensure_ascii=False,
        )


def _parsed(text: str) -> _Notes:
    """Zapisy z treści pliku ``opening``; treść w innej postaci to brak zapisów."""

    try:
        found = json.loads(text)
        return _Notes(
            {str(kind): (float(moment), str(write)) for kind, (moment, write) in found["zapisy"].items()},
            [(float(at), str(label), Issue(int(number), str(body))) for at, label, number, body in found["issue"]],
            [(float(at), str(tag), int(archive)) for at, tag, archive in found["archiwa"]],
            [
                (float(at), int(archive), Asset(int(asset), str(name), str(label), True))
                for at, archive, asset, name, label in found["pliki"]
            ],
            [(float(at), int(asset)) for at, asset in found["usuniete"]],
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return _Notes()


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
        self, box: ReportBox, key: Callable[[], str | None], *, clock: Callable[[], float], opening: NotesFile | None = None
    ) -> None:
        self._box = box
        self._key = key
        self._clock = clock
        self._lock = threading.Lock()
        self._verdict: _Verdict | None = None
        self._no_answer: tuple[str, float] | None = None  # skrót klucza i chwila ostatniego pytania bez odpowiedzi
        self._probe: threading.Thread | None = None
        self._opening = opening
        self._remembered = _Notes()  # zapisy bez pliku ``opening``
        self._lists = threading.local()  # listed_at: chwila ostatniego pytania wątku o listę, na które przyszła
        self._unavailable_noted = False  # pierwszy błąd pliku ``opening`` w tej pracy Centrum już w ``unavailable``
        self._names: dict[int, str] = {}  # id pliku Archiwum z ostatnich odpowiedzi ``archive``: jego nazwa

    def open_issue(self, label: Label, title: str, body: str) -> SendOutcome | NoKey:
        """Nowe issue; ``Unreachable`` bez zapytania, gdy zakładanie z etykietą ``label`` jest wstrzymane (opis modułu)."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        ready = self._ready(label)
        if ready is None:
            return Unreachable()
        asked_at, write, before = ready
        outcome = self._box.open_issue(label, title, body, key=key)
        self._observe(key, asked_at, outcome)
        sent = outcome.number if isinstance(outcome, Sent) else None
        self._settled(
            label,
            write,
            before,
            None if sent is None else lambda notes, at: notes.opened.append((at, label, Issue(sent, body))),
            refused=isinstance(outcome, Refused | Rejected),
        )
        return outcome

    def _ready(self, kind: str) -> tuple[float, str, tuple[float, str] | None] | None:
        """Chwila i identyfikator zapisu ``kind`` (etykieta issue, ``_archive_kind`` albo ``_file_kind``) i zapis bez
        odpowiedzi tego rodzaju sprzed niego, zapisane w pliku ``opening``; ``None``: zapis wstrzymany albo pliku nie da
        się odczytać lub zapisać.

        Identyfikator, a nie chwila, mówi, czyj jest zapis: ``time.monotonic`` na Windows zmienia się co ok. 15 ms, więc
        dwa zapisy mogą mieć tę samą chwilę.
        """

        asked_at = self._clock()
        with self._lock:
            notes = self._notes()
            if notes is None or self._held(kind, asked_at, notes):
                return None
            write = uuid.uuid4().hex
            before = notes.pending.get(kind)
            notes.pending[kind] = (asked_at, write)
            if not self._noted(notes):
                return None
        return asked_at, write, before

    def _settled(
        self,
        kind: str,
        write: str,
        before: tuple[float, str] | None,
        effect: Callable[[_Notes, float], None] | None,
        *,
        refused: bool,
    ) -> None:
        """Po odpowiedzi na zapis ``write``: ``effect`` (wiadomo, co się zmieniło) trafia do pliku zamiast zapisu, a
        ``refused`` (nic się nie zmieniło) przywraca zapis ``before``; bez odpowiedzi zapis zostaje. Plik, którego nie da
        się odczytać albo zapisać, zostawia zapis bez odpowiedzi, czyli tylko wstrzymuje następne zapisy."""

        if effect is None and not refused:
            return
        answered_at = self._clock()
        with self._lock:
            notes = self._notes()
            if notes is None:
                return
            if notes.pending.get(kind, (0.0, ""))[1] == write:
                if refused and before is not None:
                    notes.pending[kind] = before
                else:
                    del notes.pending[kind]
            if effect is not None:
                effect(notes, answered_at)
            self._noted(notes)

    def _held(self, kind: str, now: float, notes: _Notes) -> bool:
        """Pod blokadą: czy ostatnia lista ``kind`` mogła nie pokazywać zapisu z pliku: przy niej pliku nie dało się
        odczytać (opis modułu) albo przyszła na pytanie zadane mniej niż ``LIST_LAG_S`` po zapisie bez odpowiedzi (albo
        przed nim).

        Liczy się chwila pytania o listę, nie ``now``: między listą a zapisem kolejka może jeszcze wysyłać plik do
        Archiwum okresu (``outbox._deliver_to_period``), a chwila zapisu, która w tym czasie dawnieje, nie mówi, że
        lista sprzed niej go pokazała. Liczy się też tylko lista tego wątku, czyli ta, na której kolejka opiera zapis:
        późniejsza lista podglądu Zgłoszenia albo Powiadomień w innym wątku nie mówi, co widziała lista kolejki.
        """

        listed_at = self._listed_at().get(_list_of(kind), now)
        if listed_at is None:
            return True
        if kind not in notes.pending:
            return False
        moment, _ = notes.pending[kind]
        return 0 <= now - moment and listed_at - moment < LIST_LAG_S

    def _listed_at(self) -> dict[str, float | None]:
        """Chwila ostatniego pytania tego wątku o listę etykiety, tagu albo plików Archiwum, na które przyszła; ``None``:
        przy tej liście pliku ``opening`` nie dało się odczytać."""

        listed: dict[str, float | None] = self._lists.__dict__.setdefault("listed_at", {})
        return listed

    def _notes(self) -> _Notes | None:
        """Pod blokadą: zapisy z pliku ``opening`` bez dawnych skutków; ``None``: pliku nie da się odczytać (np. trzyma
        go antywirus), więc zapisu innego ``KeyedBox`` nie da się wykluczyć. Treść, która nie jest UTF-8, to treść w
        innej postaci (``_parsed``)."""

        now = self._clock()
        if self._opening is None:
            return self._remembered.fresh(now)
        try:
            text = self._opening.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _Notes()
        except UnicodeError:
            return _Notes()
        except OSError as failure:
            self._unavailable(failure)
            return None
        return _parsed(text).fresh(now)

    def _unavailable(self, failure: OSError) -> None:
        """Pod blokadą: pierwszy błąd pliku ``opening`` w tej pracy Centrum idzie do ``NotesFile.unavailable``."""

        if self._opening is not None and not self._unavailable_noted:
            self._unavailable_noted = True
            self._opening.unavailable(failure)

    def _noted(self, notes: _Notes) -> bool:
        """Pod blokadą: zapisuje ``notes`` w pliku ``opening`` (bez pliku w pamięci); ``False``: zapis się nie udał.

        Zapisuje do Skrzynki tylko kolejka, w przejściu z blokadą folderu kolejki (``outbox._folder_lock``), więc plik
        zmienia naraz najwyżej jeden proces. Zamiana (``NotesFile.replace``) jest atomowa i czeka na plik, który ktoś
        na chwilę trzyma, więc zgaśnięcie w jej trakcie zostawia poprzednie zapisy, a
        plik, z którego ``fresh`` usunęła dawne wpisy, ma najwyżej zapisy z ostatnich ``LIST_LAG_S`` i zapisy bez
        odpowiedzi z ostatnich ``PENDING_KEPT_S``.
        """

        if self._opening is None:
            self._remembered = notes
            return True
        try:
            self._opening.replace(self._opening.path, notes.dumped())
        except OSError as failure:
            self._unavailable(failure)
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
        """Archiwum okresu z tagiem ``tag`` z plikami, po zapisach z pliku ``opening`` (opis modułu); jego odmowa (brak
        uprawnienia do treści repozytorium) nie jest werdyktem."""

        asked_at = self._clock()
        outcome = self._about_issue(lambda key: self._box.archive(tag, key=key))
        if outcome is not None and not isinstance(outcome, Archive):
            return outcome
        with self._lock:
            known = self._notes()
            self._listed_at()[_archive_kind(tag)] = self._listed_at()[_FILES_LIST] = None if known is None else asked_at
        notes = known or _Notes()
        opened = next((archive for _, of, archive in reversed(notes.archives) if of == tag), None)
        found = outcome if outcome is not None else None if opened is None else Archive(opened, ())
        if found is None:
            return None
        sent = [asset for _, archive, asset in notes.uploads if archive == found.id]
        removed = {asset for _, asset in notes.removals}
        listed = [asset for asset in found.assets if asset.id not in removed]
        ids = {asset.id for asset in listed} | removed
        merged = Archive(found.id, (*listed, *(asset for asset in sent if asset.id not in ids)))
        with self._lock:
            self._names.update((asset.id, asset.name) for asset in merged.assets)
        return merged

    def open_archive(self, tag: str, title: str, description: str) -> OpenArchiveOutcome | NoKey:
        """Nowe Archiwum; ``Unreachable`` bez zapytania, gdy zakładanie Archiwum ``tag`` jest wstrzymane (opis modułu)."""

        return self._listed_write(
            _archive_kind(tag),
            lambda key: self._box.open_archive(tag, title, description, key=key),
            lambda outcome: (
                None
                if not isinstance(outcome, Archive)
                else lambda notes, at: notes.archives.append((at, tag, outcome.id))
            ),
        )

    def upload(self, archive_id: int, name: str, label: str, data: bytes) -> UploadOutcome | NoKey:
        """Plik w Archiwum; ``Unreachable`` bez zapytania, gdy zapis plików Archiwum jest wstrzymany (opis modułu)."""

        return self._listed_write(
            _file_kind(name),
            lambda key: self._box.upload(archive_id, name, label, data, key=key),
            lambda outcome: (
                None
                if not isinstance(outcome, Asset)
                else lambda notes, at: notes.uploads.append((at, archive_id, outcome))
            ),
        )

    def remove(self, asset_id: int) -> RemoveOutcome | NoKey:
        """Usunięcie pliku Archiwum; ``Unreachable`` bez zapytania, gdy zapis plików Archiwum jest wstrzymany."""

        with self._lock:
            name = self._names.get(asset_id, f"#{asset_id}")
        return self._listed_write(
            _file_kind(name),
            lambda key: self._box.remove(asset_id, key=key),
            lambda outcome: (
                None if not isinstance(outcome, Removed) else lambda notes, at: notes.removals.append((at, asset_id))
            ),
        )

    def _listed_write(
        self,
        kind: str,
        ask: Callable[[str], _Outcome],
        effect: Callable[[_Outcome], Callable[[_Notes, float], None] | None],
    ) -> _Outcome | NoKey | Refused | Unreachable:
        """Zapis do Archiwum, którego skutek (``effect`` odpowiedzi) widać tylko na liście ``kind``: wstrzymany jak
        zakładanie issue (opis modułu), a jego odmowa nie jest werdyktem o kluczu (``_about_issue``)."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        ready = self._ready(kind)
        if ready is None:
            return Unreachable()
        asked_at, write, before = ready
        outcome = ask(key)
        if not isinstance(outcome, Refused):
            self._observe(key, asked_at, outcome)
        self._settled(kind, write, before, effect(outcome), refused=isinstance(outcome, Refused | Rejected))
        return outcome

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
        """Issue z etykietą ``label`` z listy Skrzynki i te, które ``KeyedBox`` założył w ``LIST_LAG_S``, a lista ich nie ma.

        Lista bez zamkniętych nie pokazuje ani issue, za którym nie nadążyła, ani issue, które Maks już zamknął, więc
        takie issue dołącza dopiero wtedy, gdy nie ma go zamkniętego na liście z zamkniętymi; bez jej odpowiedzi dołącza.
        """

        listed = self._labelled(label, include_closed=include_closed)
        return listed if isinstance(listed, NoKey | Refused | Unreachable) else listed[0]

    def known_issue(self, label: Label, number: int) -> Issue | None | Refused | Unreachable | NoKey:
        """Issue ``number`` z etykietą ``label`` (otwarte albo zamknięte) z ``labelled_issues``; ``None``: Skrzynka go
        nie ma (Maks je usunął, #402).

        Brak numeru na liście to decyzja, której kolejka nie cofnie (porzuca wysyłkę), więc ma zasadę zapisu (opis
        modułu, #909, #915): lista bez numeru mówi, że issue nie ma, tylko gdy zapis z etykietą ``label`` nie byłby
        teraz wstrzymany. Inaczej (przy liście pliku ``opening`` nie dało się odczytać albo czeka w nim zapis bez
        odpowiedzi, którego lista mogła jeszcze nie pokazać) to ``Unreachable`` bez decyzji, jak wstrzymany zapis.
        """

        listed = self._labelled(label, include_closed=True)
        if isinstance(listed, NoKey | Refused | Unreachable):
            return listed
        issues, complete = listed
        found = next((issue for issue in issues if issue.number == number), None)
        return found if found is not None or complete else Unreachable()

    def _labelled(
        self, label: Label, *, include_closed: bool
    ) -> tuple[tuple[Issue, ...], bool] | Refused | Unreachable | NoKey:
        """``labelled_issues`` i czy ta lista pokazuje każdy zapis etykiety ``label``: zapis nie byłby teraz wstrzymany."""

        key = self._usable()
        if not isinstance(key, str):
            return key
        asked_at = self._clock()
        listed = self._listed(key, label, include_closed=include_closed)
        if isinstance(listed, Refused | Unreachable):
            return listed
        with self._lock:
            known = self._notes()
            self._listed_at()[label] = None if known is None else asked_at
            notes = known or _Notes()
            complete = not self._held(label, self._clock(), notes)
        opened = [issue for _, of, issue in notes.opened if of == label]
        numbers = {issue.number for issue in listed}
        missing = [issue for issue in opened if issue.number not in numbers]
        if missing and not include_closed:
            every = self._listed(key, label, include_closed=True)
            if not isinstance(every, Refused | Unreachable):
                closed = {issue.number for issue in every if issue.closure is not None}
                missing = [issue for issue in missing if issue.number not in closed]
        return (*listed, *missing), complete

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

    def github_key(self) -> str | None:
        """Klucz do pytań Aktualności narzędzia i Powiadomienia o nowej wersji do API GitHuba; ``None`` bez pliku klucza
        i dla klucza, którego nie da się wysłać w nagłówku (``github.sendable``), bo taki nagłówek wywraca pytanie,
        zanim dojdzie do GitHuba, a pytanie bez tokenu i tak dostaje odpowiedź.

        Bez werdyktu i bez pytania Skrzynki: ich odmowa mówi o publicznym repozytorium, nie o Skrzynce (opis modułu).
        """

        key = self._key()
        return key if key is not None and sendable(key) else None

    def check_in_background(self) -> None:
        """Przy starcie Centrum: sprawdzenie klucza w tle, żeby pierwsza Konfiguracja nie czekała na Skrzynkę."""

        self.judge(wait_s=0)

    def _check(self, key: str) -> None:
        """Sprawdzenie w tle: jedno tanie pytanie o otwarte Zgłoszenia, także odrzuconym kluczem, któremu minęła pamięć.

        Zwykle jedna strona, a to samo pytanie zadaje podgląd Zgłoszenia.
        """

        self._listed(key, REPORT_LABEL, include_closed=False)

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
