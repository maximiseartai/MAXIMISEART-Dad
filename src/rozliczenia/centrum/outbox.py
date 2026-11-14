"""Kolejka Skrzynki Zgłoszeń: Kontrole ilości, Logi Uruchomienia, Uwagi taty i Zgłoszenia, które Centrum wysyła w tle.

Każda wysyłka (``Post``) to gotowy tekst skierowany do issue okresu (``PeriodThread``: etykieta, wiersz rozpoznawczy
na początku treści issue, tytuł i co z issue, które Maks zamknął), do nowego issue (``NewIssue``: etykieta i tytuł,
jak Uwaga taty), do issue o znanym numerze (``KnownIssue``) albo do jednego otwartego issue z wierszem rozpoznawczym
w treści (``OpenIssue``, jak Zgłoszenie: zawsze jedna część; gdy issue z tym wierszem jest otwarte, wysyłka idzie do
niego komentarzem z nagłówkiem celu). Najpierw trafia do własnego pliku JSON w
``config/zgloszenia/kolejka/`` (poza Gitem), potem jeden wątek w tle wysyła wszystkie pliki po kolei i usuwa
wysłane. Porażka (brak klucza, odmowa, brak sieci) zostawia plik bez Komunikatu; wątek rusza znów sam po
``RETRY_S``, przy starcie Centrum (``resume``) i po każdej nowej wysyłce. Plik do ``KnownIssue``, którego skrzynka
już nie ma, kolejka porzuca z linią dziennika (#402). Wysłany plik dostaje znacznik dostarczenia, zanim zniknie,
więc plik, którego nie da się usunąć, nie idzie drugi raz. Treść nigdy nie trafia do dziennika Centrum: tylko
etykieta, okres, numer issue i przyczyna czekania (decyzja 13).

Wysyłka jest dokładnie raz (#840): każda część trafia do Skrzynki raz, także gdy przerwanie (zerwane połączenie,
zgaśnięcie Centrum) przyjdzie między jej przyjęciem przez skrzynkę a znacznikiem dostarczenia. Każdy tekst, który
kolejka zapisuje w skrzynce, kończy się niewidocznym znacznikiem (``_mark``, komentarz HTML w osobnej linii): z
identyfikatorem wysyłki, czyli etykietą (rodzajem) i ``run_id`` (Uruchomieniem), z numerem części (0: nagłówek) i z
wersją (``Version``): najpierw stopniem, który wybiera nadawca (``Rank``, #910), potem chwilą i numerem z nazwy pliku
kolejki (``_version``). Przed wysłaniem kolejka czyta treść i komentarze issue celu (``_settle``): issue ze znacznikiem
tej wysyłki w nowszej wersji nie dostaje od niej niczego, część, której znacznik już tam jest w tej wersji, nie idzie
drugi raz, komentarz części w starszej wersji dostaje nowy tekst (``edit_comment``), a komentarz części, której nowsza
wersja nie ma, dostaje ``_RETIRED``. Tak Diagnoza, która wysyła Logi Uruchomienia drugi raz z tym samym
identyfikatorem, zmienia komentarz swojego Uruchomienia, a starszy plik, który dojdzie po nowszym (np. raz
nieczytelny), niczego w issue nie zmienia ani nie dopisuje. Plik, gdy przejście odczytało plik nowszej wersji tej samej
wysyłki (ten sam cel i ``run_id``, ``_superseded``), także zapisany przed nim, kolejka oznacza znacznikiem
dostarczenia i usuwa bez wysyłania, bo Skrzynce należy się nowsza: bez sieci w kolejce zostaje tylko najnowszy postęp
Wyceny w efenix (#846, ``run_comments``) i tylko Logi z ostatnią Diagnozą. Chwila i numer porządkują tylko wersje
jednego stopnia, a te powstają w jednej pracy Centrum (Diagnozę ma tylko ostatnie Uruchomienie tej pracy,
``run_comments``, a postęp tylko trwające), w której wersja rośnie z każdą wysyłką, także gdy zegar komputera się cofnie
(``Outbox.post``), albo są wersjami zastępczymi jednego dziennika Wyceny z kolejnych startów. Wersja zastępcza z
następnej pracy Centrum (Logi Urwanego Uruchomienia, wynik bez Logów) jest więc nowsza od każdego postępu, a starsza od
Logów z wynikiem, choć zegar komputera mógł się cofnąć. Treści issue kolejka nigdy nie zmienia.

Issue okresu kolejka znajduje po wierszu rozpoznawczym przy każdej próbie wysyłki i dopisuje do niego części jako
komentarze. Bez niego zakłada nowe issue: pierwsza część (albo nagłówek) jest jego treścią, kolejne komentarzami.
``NewIssue`` szuka issue, którego treść ma znacznik tej wysyłki (także zamkniętego), a bez niego zakłada nowe, więc
issue, które założyła przerwana próba, dostaje tylko brakujące części. Kto czeka na wynik (Uwaga taty), może poczekać
na dostarczenie przez ``wait_delivered``.

Wysyłka do issue okresu może nieść plik do Archiwum okresu (``ArchiveFile``, #844: pełne Logi Uruchomienia), GitHub
Release z tagiem w repozytorium Skrzynki. Plik idzie tuż przed częściami, a wysyłka jest dokładnie raz także w
Archiwum: GitHub trzyma jeden plik jednej nazwy, a etykieta pliku niesie wersję wysyłki, więc ponowienie nie wysyła
pliku, który już jest w tej albo nowszej wersji, plik starszej wersji ustępuje nowszej (``remove``, potem ``upload``),
a issue z nowszą wersją wysyłki nie dostaje od starszej niczego, także w Archiwum. Gdy Archiwum nie przyjmie pliku
(brak uprawnienia klucza do zapisu treści repozytorium, odmowa treści), części idą z dopiskiem, że plik czeka, a plik
kolejki dostaje znacznik części (``delivered_parts``) i czeka tylko na Archiwum: następne próby nie pytają już o issue.
Przejście, w którym Archiwum odmówiło, nie pyta go więcej, a budzenie po ``RETRY_S`` ponawia jedno pytanie.

Adres pierwszego komentarza każdej dostarczonej wysyłki (np. Logów Uruchomienia, do których prowadzi przypięta
Uwaga taty) kolejka dopisuje do pliku ``addresses`` i wczytuje przy następnym starcie Centrum, więc ``delivered``
zna też wysyłki poprzednich prac Centrum. Co wysyłka znaczy poza kolejką, wie jej słuchacz (``Listener``, w Centrum
Sprawy taty w Skrzynce, ``case_delivery``): tuż przed wysłaniem może ją zmienić albo zostawić w kolejce do następnego
przejścia, a po przyjęciu albo odrzuceniu treści przez skrzynkę dostaje wynik i oddaje wysyłki, które z niego wynikają.
"""

from __future__ import annotations

import gzip
import itertools
import json
import re
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Final, Literal, Protocol, assert_never, final, get_args

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.log import CentrumLog, WaitingCause
from rozliczenia.centrum.report_issue import RETURNED_HEADING
from rozliczenia.centrum.report_box import (
    COMMENT_LIMIT,
    Archive,
    Asset,
    Comment,
    Commented,
    Issue,
    Label,
    Refused,
    Rejected,
    Removed,
    Sent,
    Unreachable,
    archive_url,
    newest_with_line,
)
from rozliczenia.client_data import LogsText, Outgoing, logs_text, tool
from rozliczenia.wall_clock import utc_now

if TYPE_CHECKING:
    from rozliczenia.centrum.comment_versions import LogsPost

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

QUEUE_DIRECTORY: Final = "kolejka"
QUEUE_THREAD: Final = "skrzynka-kolejka"
# Poza ``config/zgloszenia``: weryfikacja Kontroli ilości sprawdza, że jest tam tylko kolejka.
ADDRESSES_FILE: Final = "skrzynka-adresy.jsonl"
# Schemat 3 (#844) niesie plik do Archiwum okresu; stare Centrum, które go nie zna, zostawia taki plik w kolejce,
# zamiast wysłać same części i usunąć plik razem z plikiem do Archiwum.
SCHEMA_VERSION: Final = 3
# Pliki kolejki od ``NewIssue`` (#273) do #844: cel w kluczu ``target``, bez pliku do Archiwum.
_TARGET_SCHEMA: Final = 2
# Pliki kolejki sprzed ``NewIssue`` (#273) mają cel w kluczu ``thread`` i zawsze jest nim issue okresu.
_PERIOD_THREAD_SCHEMA: Final = 1
# Rodzaj celu ``OpenIssue`` w pliku kolejki: nazwa z czasu, gdy był nim tylko cel Zgłoszenia, którą czyta też Centrum
# sprzed ``OpenIssue`` po cofnięciu Aktualizacji.
_OPEN_ISSUE: Final = "report_issue"
# Nagłówek celu ``OpenIssue`` w pliku bez klucza ``again``: takie pliki zapisało Centrum sprzed ``OpenIssue``, w którym
# tym celem było tylko Zgłoszenie (warunek usunięcia przy ``_parse``).
_AGAIN_BEFORE_OPEN_ISSUE: Final = RETURNED_HEADING
# Miejsce w komentarzu na nagłówek części, wiersz rozpoznawczy i znacznik wysyłki, ponad tekst bloków.
_FRAME_RESERVE: Final = 2_000
# Najwięcej znaków tekstu bloków w jednej części; treść celu ``OpenIssue`` mieści się w jednej.
PART_LIMIT: Final = COMMENT_LIMIT - _FRAME_RESERVE
# Najwięcej znaków ``run_id``: identyfikator Uruchomienia, Uwagi taty albo Zgłoszenia (32 znaki ``uuid4().hex``).
_RUN_ID_LIMIT: Final = 64
# Miejsce na znacznik wysyłki (``_mark``) z linią przed nim: przy ``run_id`` do ``_RUN_ID_LIMIT`` znaków i wersji z
# nazwy pliku z ``post`` ma najwyżej 150 znaków.
_MARK_RESERVE: Final = 200
# Najwięcej znaków tekstu wysyłki w treści issue albo komentarzu, bez znacznika.
TEXT_LIMIT: Final = COMMENT_LIMIT - _MARK_RESERVE
# Znacznik wysyłki: linia ``<!-- wysyłka <etykieta> <run_id> część <k> wersja <wersja> -->`` (``_mark``).
_MARK_START: Final = "<!-- wysyłka "
_MARK_REST: Final = re.compile(r"część ([0-9]+) wersja (\S+) -->")
# Najmniejszy krok chwili w nazwie pliku kolejki (``%f``): wysyłka po cofnięciu zegara dostaje chwilę tuż po poprzedniej.
_TICK: Final = timedelta(microseconds=1)
# Tekst komentarza części, której nowsza wersja wysyłki już nie ma (Logi po Diagnozie krótsze o część).
_RETIRED: Final = "Ta część jest pusta: nowsza wersja tej wysyłki ma mniej części."
# Po przejściu, które stanęło na przyczynie dla całej kolejki (brak sieci, brak klucza, odmowa klucza), kolejka
# próbuje znowu po minucie. Odrzucony klucz nie kosztuje przy tym zapytania: ``KeyedBox`` odpowiada ``Refused`` bez
# sieci przez kwadrans, a brak klucza to odczyt pliku. Nieudana próba DNS raz na minutę nic nie kosztuje, a dłuższa
# przerwa opóźniłaby wysyłkę po powrocie sieci.
RETRY_S: Final = 60.0
# Tyle „Wyślij” Uwagi taty i „Wyślij do Maksa” czekają na skrzynkę, zanim powiedzą, że wysyłka czeka w kolejce.
DELIVERY_WAIT_S: Final = 5.0
# Miejsce (``where``) wyjątku przejścia kolejki w dzienniku Centrum (``CentrumLog.unexpected_failure``).
DRAIN: Final = "wysyłka do Skrzynki Zgłoszeń"

Frame = Callable[[int, int, Outgoing], Outgoing]
"""Komentarz części ``k`` z ``n`` z jej tekstu."""

# Foldery kolejki z trwającym przejściem w tym procesie i czy inna kolejka tego folderu prosi o następne. Dwie
# kolejki jednego folderu (restart Centrum w procesie) nie wysyłają naraz: obie nie znalazłyby issue okresu, którego
# druga jeszcze nie założyła, i założyłyby je dwa razy. Kolejka, która zastanie tu przejście drugiej, nie czeka na
# budzenie, bo druga po swoim przejściu robi następne. Kolejki dwóch procesów rozdziela blokada folderu (``_folder_lock``).
_PASSES_LOCK: Final = threading.Lock()
_PASSES: Final[dict[Path, bool]] = {}
# Plik blokady folderu kolejki, obok plików kolejki; nie jest ani ``*.json``, ani ``*.tmp``.
PASS_LOCK: Final = "przejscie.lock"


def _claimed(directory: Path) -> bool:
    """Czy to przejście może wysyłać z ``directory``; inaczej prosi trwające przejście o następne."""

    with _PASSES_LOCK:
        alone = directory not in _PASSES
        _PASSES[directory] = not alone
        return alone


def _released(directory: Path) -> bool:
    """Kończy przejście z ``directory``; ``True``, gdy w jego trakcie inna kolejka tego folderu prosiła o następne."""

    with _PASSES_LOCK:
        return _PASSES.pop(directory)


@contextmanager
def _folder_lock(directory: Path) -> Iterator[bool]:
    """Blokada systemowa pliku ``PASS_LOCK`` w ``directory`` na czas bloku; ``False``: trzyma ją inna kolejka.

    Rozdziela przejścia kolejek jednego folderu także w dwóch procesach Centrum, których ``_PASSES`` nie widzi: stare
    Centrum po zwolnieniu portu jeszcze kończy pracę, a nowe już wysyła (Ponowny start Centrum albo skrót kliknięty
    zaraz po zamknięciu). Blokadę zwalnia zamknięcie pliku, a system także koniec procesu, nawet zabitego, więc nie
    zostaje po nim. Plik, którego nie da się otworzyć (folderu kolejki jeszcze nie ma), nie wstrzymuje przejścia:
    ``True`` bez blokady.
    """

    lock_file: BinaryIO | None
    try:
        lock_file = (directory / PASS_LOCK).open("ab")
    except OSError:
        lock_file = None
    if lock_file is None:
        yield True
        return
    with lock_file:
        if not _locked(lock_file):
            yield False
            return
        try:
            yield True
        finally:
            if sys.platform == "win32":  # dokumentacja LockFileEx zaleca zwolnić zakres przed zamknięciem pliku
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _locked(lock_file: BinaryIO) -> bool:
    """Bierze blokadę bez czekania; ``False``, gdy trzyma ją inny uchwyt pliku, także w innym procesie."""

    try:
        if sys.platform == "win32":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


Closed = Literal["new_issue", "reuse"]
_LABELS: Final = frozenset(get_args(Label))
_CLOSED: Final = frozenset(get_args(Closed))


@final
@dataclass(frozen=True)
class PeriodThread:
    """Issue okresu w Skrzynce Zgłoszeń."""

    label: Label
    line: Outgoing
    """Dokładny wiersz treści, po którym znaleźć issue; kolejka stawia go na początku każdego issue, które zakłada."""
    closed: Closed
    """Kontrola ilości: zamknięte issue to nowe issue okresu; Logi Uruchomienia: dalej to samo."""
    title: Outgoing
    """Tytuł, gdy issue trzeba założyć."""


@final
@dataclass(frozen=True)
class NewIssue:
    """Nowe issue przy każdej wysyłce, bez wiersza rozpoznawczego (Uwaga taty: każda to osobna sprawa)."""

    label: Label
    title: Outgoing


@final
@dataclass(frozen=True)
class KnownIssue:
    """Komentarze do issue o znanym numerze (odnośnik do Logów dopisany do issue Uwagi taty)."""

    label: Label
    number: int


@final
@dataclass(frozen=True)
class OpenIssue:
    """Jedno otwarte issue z etykietą ``label`` na wiersz rozpoznawczy ``line``, który nadawca stawia w treści (Zgłoszenie:
    wiersz odcisku problemu, ``report_issue``).

    Wysyłka ma zawsze jedną część, treść issue albo komentarza (``Post`` odrzuca więcej, #724). Dostarczenie szuka
    otwartego issue z tym wierszem. Bez niego zakłada issue z ``title`` i tą częścią. Otwarte issue dokładnie z tą treścią
    założyła przerwana próba tej wysyłki: wysyłka je przejmuje bez komentarza. Inne otwarte issue tego wiersza
    (wcześniejsze, z tego albo innego komputera) dostaje komentarz z nagłówkiem ``again`` i tą częścią, więc Maks widzi,
    że problem wraca (#820).
    """

    label: Label
    line: Outgoing
    title: Outgoing
    again: Outgoing
    """Nagłówek komentarza do otwartego issue z tym wierszem, przed częścią."""


Target = PeriodThread | NewIssue | KnownIssue | OpenIssue
"""Dokąd w Skrzynce Zgłoszeń idzie wysyłka; każde pole tekstowe celu to ``Outgoing``, a cel nie ma podklas (``final``)."""


@final
@dataclass(frozen=True)
class ArchiveFile:
    """Plik wysyłki w Archiwum okresu (GitHub Release z tagiem ``tag`` w repozytorium Skrzynki Zgłoszeń).

    ``name`` i ``text`` to plik przed spakowaniem (Logi Uruchomienia: nazwa i treść pliku Logów po strażniku); w
    Archiwum leży spakowany gzipem jako ``packed_name``, a ``link`` prowadzi do niego, zanim dojdzie. ``title`` i
    ``description`` to tytuł i opis Archiwum, gdy kolejka musi je założyć.
    """

    tag: str
    title: str
    description: str
    name: str
    text: LogsText

    @property
    def packed_name(self) -> str:
        return f"{self.name}.gz"

    @property
    def link(self) -> str:
        return archive_url(self.tag, self.packed_name)

    def packed(self) -> bytes:
        """``text`` w UTF-8 spakowany gzipem bez chwili spakowania, więc te same znaki to zawsze te same bajty."""

        return gzip.compress(self.text.encode("utf-8"), mtime=0)


def _waiting_note(archive: ArchiveFile) -> str:
    return (
        f"Plik `{archive.packed_name}` czeka w Kolejce wysyłki na komputerze taty: Archiwum okresu go nie przyjęło "
        "(np. Token do Zgłoszeń bez uprawnienia do zapisu treści repozytorium Skrzynki). Odnośnik zadziała, gdy plik dojdzie."
    )


def _noted(text: str, note: str) -> str:
    if not note:
        return text
    paragraph = text.rstrip("\n")
    return f"{paragraph}\n\n{note}\n"


class Rank(IntEnum):
    """Stopień wersji wysyłki (#910): wersja wyższego stopnia jest nowsza od każdej wersji niższego, bez względu na chwilę
    w nazwie pliku kolejki, a chwila i numer porządkują tylko wersje jednego stopnia.

    Stopień wybiera nadawca, a nie zegar komputera. Logi Uruchomienia (``run_logs``) mają trzy: postęp Wyceny w efenix
    (``DRAFT``), wersję zastępczą, którą start Centrum odtwarza z dziennika Wyceny (``STAND_IN``: Logi z pliku, Logi
    Urwanego Uruchomienia albo wynik bez Logów), i Logi z pracy Centrum Uruchomienia (``OWN``: z wynikiem, z Diagnozą).
    Każda inna wysyłka ma ``OWN``, tak jak wersja bez stopnia, którą zapisało Centrum sprzed #910: żadne Wydanie nie
    wysyłało postępu ani Logów z dziennika.
    """

    DRAFT = 0
    STAND_IN = 1
    OWN = 2


# Numer stopnia przed chwilą w tekście wersji (``Version.text``); ``OWN`` go nie ma.
_LOWER_RANKS: Final = {str(rank.value): rank for rank in Rank if rank is not Rank.OWN}


@dataclass(frozen=True, order=True)
class Version:
    """Wersja wysyłki: stopień (``Rank``), potem chwila i numer z nazwy pliku kolejki (``_version``)."""

    rank: Rank
    name: str

    @property
    def text(self) -> str:
        """Wersja w znaczniku wysyłki i w etykiecie pliku w Archiwum: stopień ``OWN`` sama chwila i numer, jak przed #910,
        a niższy stopień z numerem stopnia przed nimi (``1:20261105T063021123456Z-0001``)."""

        return self.name if self.rank is Rank.OWN else f"{self.rank.value}:{self.name}"

    @classmethod
    def of(cls, text: str) -> Version:
        """Wersja z tekstu ``text`` ze znacznika albo etykiety; tekst bez numeru niższego stopnia to stopień ``OWN``."""

        rank, colon, name = text.partition(":")
        if colon and rank in _LOWER_RANKS and name:
            return cls(_LOWER_RANKS[rank], name)
        return cls(Rank.OWN, text)


@final
@dataclass(frozen=True)
class Post:
    """Gotowa wysyłka do Skrzynki Zgłoszeń, wyrenderowana przez wersję narzędzia, która ją utworzyła.

    ``header``: treść nowego issue; ``None``: nowe issue otwiera pierwsza część (Kontrola ilości, Uwaga taty).
    ``run_id`` to Uruchomienie, a dla Uwagi taty jej identyfikator. ``archive``: plik do Archiwum okresu, tylko przy
    wysyłce do issue okresu w jednej części, która idzie z dopiskiem, gdy Archiwum pliku nie przyjmie. ``rank``: stopień
    wersji tej wysyłki (``Rank``). ``state``: stan wysyłki, który nadaje i czyta jej słuchacz (``Listener``, Uwaga taty:
    czy Logi Uruchomienia są w drodze); kolejka zapisuje go w pliku i oddaje bez zmian, a do Skrzynki nie wysyła.

    Podklasy nie ma (``final``), więc plik kolejki zapisuje zawsze ``to_json`` tej klasy, a zmienioną kopię daje tylko
    ``dataclasses.replace`` albo ``__replace__``, których pola sprawdza mypy (``copy.replace`` ma zakaz ruff w ``src``).
    """

    target: Target
    period: str | None
    """Token okresu do dziennika Centrum; ``None``: Uruchomienie bez okresu."""
    run_id: str
    header: Outgoing | None
    parts: tuple[Outgoing, ...]
    archive: ArchiveFile | None = None
    rank: Rank = Rank.OWN
    state: str | None = None

    def __post_init__(self) -> None:
        body, comments = self.opening()
        note = 0 if self.archive is None else len(_noted("", _waiting_note(self.archive)))
        if not self.parts or any(len(text) + note > TEXT_LIMIT for text in (body, *comments)):
            raise ValueError("Wysyłka musi mieć części mieszczące się w komentarzu Skrzynki Zgłoszeń.")
        if self.archive is not None and (not isinstance(self.target, PeriodThread) or len(self.parts) != 1):
            raise ValueError("Plik do Archiwum okresu idzie z jedną częścią do issue okresu.")
        # Identyfikator wysyłki stoi w znaczniku w jednej linii (``_mark``), a znacznik mieści się w ``_MARK_RESERVE``.
        if not 0 < len(self.run_id) <= _RUN_ID_LIMIT or not self.run_id.isprintable() or " " in self.run_id:
            raise ValueError("Identyfikator wysyłki musi być krótkim napisem bez spacji.")
        # Przerwaną wysyłkę następna próba znajduje po tym wierszu; bez niego założyłaby drugie issue.
        if isinstance(self.target, OpenIssue) and self.target.line not in body.splitlines():
            raise ValueError("Treść nowego issue musi mieć wiersz rozpoznawczy celu.")
        # Przerwaną wysyłkę następna próba poznaje po treści issue równej części 1 i przejmuje bez komentarzy, więc
        # część 2 by przepadła. Nagłówek ``OpenIssue.again`` mieści się w zapasie ``PART_LIMIT``.
        if isinstance(self.target, OpenIssue) and comments:
            raise ValueError("Wysyłka do jednego otwartego issue musi mieścić się w jednej części.")

    @classmethod
    def of(
        cls,
        target: Target,
        *,
        period: str | None,
        run_id: str,
        blocks: Sequence[Outgoing],
        frame: Frame,
        header: Outgoing | None = None,
    ) -> Post:
        """Dzieli ``blocks`` (tekst po strażniku reguły danych, ``Outgoing``) na części mieszczące się w komentarzu
        (``_pack``) i opisuje każdą przez ``frame``.

        Część ponad limit to ``ValueError``.
        """

        texts = _pack(blocks, PART_LIMIT)
        parts = tuple(frame(number, len(texts), text) for number, text in enumerate(texts, start=1))
        return cls(target, period, run_id, header, parts)

    def opening(self) -> tuple[str, tuple[str, ...]]:
        """Treść nowego issue (nagłówek albo część 1, w issue okresu po wierszu rozpoznawczym) i komentarze po nim.

        ``KnownIssue`` nie zakłada issue: pusta treść, a wszystkie części to komentarze.
        """

        if self.header is None:
            first, comments = (self.parts[0], self.parts[1:]) if self.parts else ("", ())
        else:
            first, comments = self.header, self.parts
        match self.target:
            case PeriodThread(line=line):
                return f"{line}\n\n{first}", comments
            case NewIssue() | OpenIssue():
                return first, comments
            case KnownIssue():
                return "", self.parts
            case _:
                assert_never(self.target)

    def to_json(self) -> str:
        return _queue_text(self, delivered_parts=0, archived=False)


@dataclass(frozen=True)
class _Queued:
    """Plik kolejki: wysyłka, ile jej części skrzynka już przyjęła i czy plik do Archiwum już tam jest.

    Wszystkie części bez pliku w Archiwum: Archiwum go nie przyjęło, a plik kolejki czeka tylko na nie (``commented``).
    Wszystkie części i plik w Archiwum (albo wysyłka bez niego): plik kolejki czeka tylko na usunięcie (``delivered``).
    """

    post: Post
    delivered_parts: int
    archived: bool

    @property
    def commented(self) -> bool:
        return self.delivered_parts == len(self.post.parts)

    @property
    def delivered(self) -> bool:
        return self.commented and (self.archived or self.post.archive is None)


def queue_file_pattern(label: str, run_id: str = "*") -> str:
    """Wzorzec ``glob`` plików kolejki z wysyłkami o etykiecie ``label`` Uruchomienia ``run_id`` (``*``: każdego)."""

    return _file_name("*", label, run_id)


def _file_name(version: str, label: str, run_id: str) -> str:
    """Nazwa pliku kolejki: wersja wysyłki (chwila i numer), którą czyta następne Wydanie, etykieta i początek ``run_id``."""

    return f"{version}-{label}-{run_id[:8]}.json"


def _queue_text(post: Post | LogsPost, *, delivered_parts: int, archived: bool) -> str:
    """Treść pliku kolejki z ``post``, sprawdzona w chwili zapisu, bo plik daje swoim tekstom ``Outgoing`` od nowa
    (``_parse``): wysyłka dokładnie ``Post`` albo ``comment_versions.LogsPost``, każde pole czytane raz, a tekst inny niż
    dokładnie ``Outgoing``, tekst pliku Archiwum inny niż dokładnie ``LogsText`` i stopień inny niż ``Rank`` dają
    ``TypeError``. Typ sprawdza porównanie ``is``, więc ani podklasa, jakkolwiek powstała, ani metaklasa z własnym
    ``__eq__``. Nie zamyka zmiany klasy albo modułu w chwili działania ani ``str.__new__`` z klasą ``Outgoing``."""

    from rozliczenia.centrum.comment_versions import LogsPost  # comment_versions importuje ten moduł

    if type(post) is not Post and type(post) is not LogsPost:
        raise TypeError(f"Plik kolejki bierze tylko Post i LogsPost, nie {type(post).__name__}.")
    header, parts, archive, rank = post.header, tuple(post.parts), post.archive, post.rank
    if any(type(part) is not Outgoing for part in (*parts, *(() if header is None else (header,)))) or type(rank) is not Rank:
        raise TypeError("Plik kolejki bierze tylko tekst Outgoing z rozliczenia.client_data i stopień Rank.")
    file: dict[str, str] | None = None
    if archive is not None:
        text = archive.text
        if type(archive) is not ArchiveFile or type(text) is not LogsText:
            raise TypeError("Plik kolejki bierze tylko plik ArchiveFile z tekstem LogsText z rozliczenia.client_data.")
        file = {"tag": archive.tag, "title": archive.title, "description": archive.description, "name": archive.name, "text": str.__str__(text)}
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "target": _target_json(post.target),
            "period": post.period,
            "run_id": post.run_id,
            "header": None if header is None else str.__str__(header),
            "parts": [str.__str__(part) for part in parts],
            "archive": file,
            "delivered_parts": delivered_parts,
            "archived": archived,
            "rank": rank.value,
            "state": post.state if type(post) is Post else None,
        },
        ensure_ascii=False,
        indent=2,
    )


_KINDS: Final[tuple[tuple[type[Target], str], ...]] = ((PeriodThread, "period_thread"), (NewIssue, "new_issue"), (KnownIssue, "known_issue"), (OpenIssue, _OPEN_ISSUE))
_FIELDS: Final[dict[str, Callable[[object], bool]]] = {
    "Outgoing": lambda value: type(value) is Outgoing,
    "Label": lambda value: type(value) is str and value in _LABELS,
    "Closed": lambda value: type(value) is str and value in _CLOSED,
    "int": lambda value: type(value) is int,
}
"""Sprawdzenie pola celu po jego adnotacji w klasie celu; pole z inną adnotacją wywraca zapis, zamiast przejść."""


def _target_json(target: object) -> dict[str, str | int]:
    """Cel w pliku kolejki: dokładnie jedna z klas ``Target`` (porównanie ``is``), a każde pole z ``fields`` tej klasy,
    nie z adnotacji wejścia, czytane raz i sprawdzone po adnotacji (``_FIELDS``)."""

    found = next(((kind, name) for kind, name in _KINDS if type(target) is kind), None)
    if found is None:
        raise TypeError(f"Plik kolejki bierze tylko cel z rozliczenia.centrum.outbox, nie {type(target).__name__}.")
    kind, name = found
    entry: dict[str, str | int] = {"kind": name}
    for field in fields(kind):
        value, check = getattr(target, field.name), _FIELDS.get(str(field.type))
        if check is None or not check(value):
            raise TypeError(f"Pole celu {kind.__name__}.{field.name} w pliku kolejki ma typ {type(value).__name__}.")
        entry[field.name] = value if type(value) is int else str.__str__(value)
    return entry


def _target(entry: dict[str, Any], kind: object) -> Target | None:
    """Cel wysyłki z pliku kolejki; nieznany rodzaj celu albo etykieta to ``None``."""

    if entry["label"] not in _LABELS:
        return None
    if kind == "new_issue":
        return NewIssue(entry["label"], tool(_string(entry["title"])))
    if kind == "known_issue":
        return KnownIssue(entry["label"], entry["number"]) if type(entry["number"]) is int else None
    if kind == _OPEN_ISSUE:
        again = tool(_string(entry.get("again", _AGAIN_BEFORE_OPEN_ISSUE)))
        return OpenIssue(entry["label"], tool(_string(entry["line"])), tool(_string(entry["title"])), again)
    if kind != "period_thread" or entry["closed"] not in _CLOSED:
        return None
    return PeriodThread(entry["label"], tool(_string(entry["line"])), entry["closed"], tool(_string(entry["title"])))


def _parse(text: str) -> _Queued | None:
    """Granica plików kolejki. ``delivered_parts`` jest opcjonalne: pliki z #273 go nie mają i nic nie dostarczyły.

    Pliki od #665 do #840 mogą mieć numer issue Uwagi taty (``issue``) i kolejka go pomija: issue wysyłki znajduje po
    znaczniku, a Uwaga ma jedną część, więc żadna jej próba nie zostawiła issue bez całej treści. Pliki schematu 1 i 2
    nie mają pliku do Archiwum. Stopień wersji (``rank``) jest opcjonalny: pliki sprzed #910 go nie mają i mają ``OWN``.
    Stan słuchacza (``state``) i nagłówek ``OpenIssue.again`` są opcjonalne: pliki sprzed ``OpenIssue`` ich nie mają.

    Te odczyty są dla plików, które Centrum starszej wersji zostawiło w kolejce taty, bo ich nie wysłało (brak tokenu,
    sieci, odrzucona treść). Warunek usunięcia: Maks sprawdzi, że w ``config/zgloszenia/kolejka`` u taty nie ma pliku
    zapisanego przed Wydaniem, które tata ma. Schematy 1–2 i plik bez ``rank`` zapisuje tylko Wydanie starsze niż v0.5.0,
    a plik bez ``state`` i ``again`` Wydanie sprzed ``OpenIssue``.
    """

    try:
        document = json.loads(text)
        schema = document["schema_version"]
        if schema in (SCHEMA_VERSION, _TARGET_SCHEMA):
            target = _target(document["target"], document["target"]["kind"])
        elif schema == _PERIOD_THREAD_SCHEMA:
            target = _target(document["thread"], "period_thread")
        else:
            return None
        if target is None:
            return None
        archive = _archive_file(document["archive"]) if schema == SCHEMA_VERSION else None
        archived = document["archived"] if schema == SCHEMA_VERSION else False
        post = Post(
            target,
            _optional_string(document["period"]),
            _string(document["run_id"]),
            None if document["header"] is None else tool(_string(document["header"])),
            tuple(tool(_string(part)) for part in document["parts"]),
            archive,
            _rank(document.get("rank", Rank.OWN.value)),
            _optional_string(document.get("state")),
        )
        delivered_parts = document.get("delivered_parts", 0)
    except (ValueError, KeyError, TypeError):
        return None
    if type(delivered_parts) is not int or not 0 <= delivered_parts <= len(post.parts) or type(archived) is not bool:
        return None
    return _Queued(post, delivered_parts, archived)


def _rank(entry: object) -> Rank:
    """Stopień wersji z pliku kolejki; inna wartość niż numer stopnia to ``TypeError`` albo ``ValueError`` (plik
    nieczytelny)."""

    if type(entry) is not int:
        raise TypeError("stopień wersji")
    return Rank(entry)


def _archive_file(entry: object) -> ArchiveFile | None:
    """Plik do Archiwum z pliku kolejki; ``None``: wysyłka go nie ma. Inny kształt to ``TypeError`` (plik nieczytelny)."""

    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise TypeError("plik do Archiwum")
    return ArchiveFile(
        _string(entry["tag"]),
        _string(entry["title"]),
        _string(entry["description"]),
        _string(entry["name"]),
        logs_text(_string(entry["text"])),
    )


@dataclass(frozen=True)
class QueueDisk:
    """Pliki kolejki na dysku: treść pliku, jego zapis atomowy (nowa wysyłka i znacznik dostarczenia) i usunięcie
    dostarczonego. U taty ``LOCAL_QUEUE_DISK``; wyrocznia ``verify-kolejka-skrzynki`` daje swój, którego każdy krok może
    zawieść."""

    read: Callable[[Path], str]
    write: Callable[[Path, str], None]
    remove: Callable[[Path], None]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


LOCAL_QUEUE_DISK: Final = QueueDisk(read=_read_text, write=replace_atomically, remove=_unlink)


def _in_thread(drain: Callable[[], None]) -> None:
    """Przejście kolejki w nowym wątku ``QUEUE_THREAD``, który nie trzyma zamknięcia Centrum."""

    threading.Thread(target=drain, name=QUEUE_THREAD, daemon=True).start()


def _queued(path: Path, disk: QueueDisk) -> _Queued | None:
    """Plik kolejki albo ``None``: uszkodzona treść albo nieznany schemat.

    ``OSError`` (plik trzyma np. OneDrive albo antywirus) przechodzi do wołającego: ten sam plik może się dać odczytać
    za chwilę, a treść, której się nie da, zostanie taka sama.
    """

    try:
        text = disk.read(path)
    except UnicodeError:
        return None
    return _parse(text)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("napis")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _pack(blocks: Sequence[Outgoing], budget: int) -> tuple[Outgoing, ...]:
    """Bloki sklejone w kolejności w części najwyżej ``budget`` znaków; blok, który się mieści, nie jest dzielony. Części
    dostają ``tool``, więc ``blocks`` czyta raz i blok inny niż dokładnie ``Outgoing`` daje ``TypeError``."""

    blocks = tuple(blocks)
    if any(type(block) is not Outgoing for block in blocks):
        raise TypeError("Wysyłka bierze tylko bloki Outgoing z rozliczenia.client_data.")
    parts: list[str] = []
    current = ""
    for block in blocks:
        if len(block) <= budget:
            if len(current) + len(block) > budget:
                parts.append(current)
                current = ""
            current += block
            continue
        rest = current + block
        while len(rest) > budget:
            parts.append(rest[:budget])
            rest = rest[budget:]
        current = rest
    if current:
        parts.append(current)
    return tuple(tool(part) for part in parts)


def _read_addresses(path: Path) -> dict[tuple[str, Label], str | None]:
    """Adresy pierwszych komentarzy z poprzednich prac Centrum; brak albo nieczytelny plik lub linia to brak adresu."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    found: dict[tuple[str, Label], str | None] = {}
    for line in text.splitlines():
        try:
            entry = json.loads(line)
            run_id, label, url = entry["run_id"], entry["label"], entry["url"]
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(run_id, str) and label in _LABELS and isinstance(url, str):
            found[run_id, label] = url
    return found


@dataclass(frozen=True)
class Delivered:
    """Skrzynka ma każdą część wysyłki w issue ``number``; ``archive_waits``: plik do Archiwum jeszcze nie doszedł."""

    number: int
    comments: tuple[Commented, ...]
    archive_waits: bool = False


@dataclass(frozen=True)
class InArchive:
    """Plik wysyłki jest w Archiwum okresu w tej wersji albo nowszej."""


@dataclass(frozen=True)
class ArchiveWaits:
    """Archiwum okresu nie przyjęło pliku (odmowa uprawnienia albo treści): plik czeka w kolejce, części idą dalej."""


@dataclass(frozen=True)
class Gone:
    """Skrzynka działa, ale nie ma już issue ``number`` (Maks je usunął): wysyłka do niego nigdy nie przejdzie."""

    number: int


Failure = Refused | Rejected | Unreachable | NoKey


def _version(path: Path) -> str:
    """Chwila i numer z początku nazwy pliku ``path`` (``Outbox.post``), w porządku kolejki.

    W jednej pracy Centrum rosną z każdą wysyłką także po cofnięciu zegara komputera (``Outbox.post``).
    """

    return "-".join(path.stem.split("-")[:2])


def _version_of(path: Path, post: Post) -> Version:
    return Version(post.rank, _version(path))


def _mark(post: Post, part: int, version: Version) -> str:
    """Znacznik części ``part`` (0: nagłówek) wysyłki ``post`` w wersji ``version``; GitHub go nie pokazuje."""

    return f"{_MARK_START}{post.target.label} {post.run_id} część {part} wersja {version.text} -->"


Marked = tuple[int, str]
"""Część wysyłki (0: nagłówek) i jej tekst ze znacznikiem."""


def _marked(text: str, post: Post, part: int, version: Version) -> Marked:
    return part, f"{text}\n{_mark(post, part, version)}"


def _marks(text: str, post: Post) -> Iterator[tuple[int, Version]]:
    """Część i wersja każdego znacznika wysyłki ``post`` w ``text``; linia w innej postaci znacznikiem nie jest."""

    start = f"{_MARK_START}{post.target.label} {post.run_id} "
    for line in text.splitlines():
        if line.startswith(start) and (found := _MARK_REST.fullmatch(line.removeprefix(start))):
            yield int(found.group(1)), Version.of(found.group(2))


def _opening(post: Post, version: Version, *, note: str = "") -> tuple[Marked, tuple[Marked, ...]]:
    """``Post.opening`` ze znacznikami: treść nowego issue i komentarze po niej; ``note`` kończy tekst każdej części."""

    body, comments = post.opening()
    first = len(post.parts) - len(comments) + 1
    opened = 0 if post.header is not None else 1
    return (
        _marked(_noted(body, note) if opened else body, post, opened, version),
        tuple(_marked(_noted(text, note), post, part, version) for part, text in enumerate(comments, start=first)),
    )


def _deliver(post: Post, version: Version, box: KeyedBox, *, archive_open: bool) -> Delivered | Gone | Failure:
    """``archive_open`` ``False``: Archiwum odmówiło w tym przejściu."""

    match post.target:
        case PeriodThread() as thread:
            return _deliver_to_period(post, version, thread, box, archive_open=archive_open)
        case NewIssue() as issue:
            return _deliver_new_issue(post, version, issue, box)
        case KnownIssue() as known:
            return _deliver_to_known(post, version, known, box)
        case OpenIssue() as target:
            return _deliver_open_issue(post, version, target, box)
        case _:
            assert_never(post.target)


def _deliver_new_issue(post: Post, version: Version, issue: NewIssue, box: KeyedBox) -> Delivered | Failure:
    """Issue z treścią ze znacznikiem tej wysyłki (także zamknięte) albo nowe z pierwszą częścią; reszta komentarzami.

    Takie issue założyła przerwana próba tej wysyłki (zerwane połączenie, zgaśnięcie Centrum przed znacznikiem
    dostarczenia), więc wysyłka dopisuje do niego tylko części, których tam nie ma.
    """

    issues = box.labelled_issues(issue.label, include_closed=True)
    if isinstance(issues, Refused | Unreachable | NoKey):
        return issues
    (_, body), comments = _opening(post, version)
    found = max((found for found in issues if any(_marks(found.body, post))), key=lambda found: found.number, default=None)
    if found is not None:
        return _settle(post, version, found, comments, box)
    opened = box.open_issue(issue.label, issue.title, body)
    if not isinstance(opened, Sent):
        return opened
    return _comment_all(opened.number, comments, box)


def _deliver_open_issue(post: Post, version: Version, target: OpenIssue, box: KeyedBox) -> Delivered | Failure:
    """Nowe issue z jedyną częścią wysyłki albo komentarz z nią do otwartego issue z tym wierszem rozpoznawczym.

    Jeden wiersz ma jedno otwarte issue: znalezione dostaje komentarz z nagłówkiem ``target.again``. Wyjątkiem jest
    issue, którego treść ma znacznik tej części: założyła je ta wysyłka, a przerwanie przyszło przed znacznikiem
    dostarczenia, więc cała część już jest w treści i wysyłka je przejmuje bez komentarza (``_settle``).
    """

    issues = box.labelled_issues(target.label, include_closed=False)
    if isinstance(issues, Refused | Unreachable | NoKey):
        return issues
    found = newest_with_line(issues, target.line)
    if found is None:
        (_, body), _ = _opening(post, version)
        opened = box.open_issue(target.label, target.title, body)
        if not isinstance(opened, Sent):
            return opened
        return Delivered(opened.number, ())
    returned = _marked(f"{target.again}{post.parts[0]}", post, 1, version)
    return _settle(post, version, _issue(issues, found), (returned,), box)


def _deliver_to_known(post: Post, version: Version, known: KnownIssue, box: KeyedBox) -> Delivered | Gone | Failure:
    """Każda część wysyłki komentarzem do issue ``known.number``, jeśli skrzynka je ma (otwarte albo zamknięte).

    Komentarz do issue, które Maks usunął, to 404, czyli odmowa, która zatrzymałaby całą kolejkę, więc kolejka
    najpierw pyta o issue z etykietą (``KeyedBox.known_issue``). Issue nie ma (``Gone``) tylko wtedy, gdy lista bez tego
    numeru pokazuje każdy zapis tej etykiety; świeże issue, którego lista jeszcze nie pokazuje, a plik zapisów
    ``KeyedBox`` o nim nie mówi, to ``Unreachable``, więc wysyłka czeka na budzenie (#915).
    """

    found = box.known_issue(known.label, known.number)
    if found is None:
        return Gone(known.number)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    return _settle(post, version, found, _opening(post, version)[1], box)


def _deliver_to_period(
    post: Post, version: Version, thread: PeriodThread, box: KeyedBox, *, archive_open: bool
) -> Delivered | Failure:
    """Każda część jako komentarz do issue okresu, a bez niego nowe issue z pierwszą częścią i komentarze z resztą.

    Issue okresu jest szukane przy każdej próbie, więc usunięte albo zamknięte issue nie blokuje kolejki. Pierwsza
    porażka kończy wysyłkę; następna próba dopisuje tylko części, których w issue nie ma (``_settle``). Plik do Archiwum
    idzie przed częściami (``_deliver_archive``), a w znalezionym issue dopiero wtedy, gdy nie ma w nim nowszej wersji tej
    wysyłki; plik, którego Archiwum nie przyjęło, dopisuje do części ``_waiting_note``.
    """

    issues = box.labelled_issues(thread.label, include_closed=thread.closed == "reuse")
    if isinstance(issues, Refused | Unreachable | NoKey):
        return issues
    found = newest_with_line(issues, thread.line)
    if found is None:
        step = _deliver_archive(post, version, box, archive_open=archive_open)
        if isinstance(step, Unreachable | NoKey):
            return step
        (_, body), comments = _opening(post, version, note=_note(post, step))
        opened = box.open_issue(thread.label, thread.title, body)
        if not isinstance(opened, Sent):
            return opened
        return _archive_waits(_comment_all(opened.number, comments, box), step)
    issue = _issue(issues, found)
    seen = _seen(post, issue, box)
    if not isinstance(seen, _Seen):
        return seen
    if seen.newest is not None and seen.newest > version:
        return _newer(post, issue.number, seen, range(1, len(post.parts) + 1))
    step = _deliver_archive(post, version, box, archive_open=archive_open)
    if isinstance(step, Unreachable | NoKey):
        return step
    note = _note(post, step)
    parts = tuple(_marked(_noted(text, note), post, part, version) for part, text in enumerate(post.parts, start=1))
    return _archive_waits(_put_all(post, version, issue.number, parts, seen, box), step)


def _note(post: Post, step: InArchive | ArchiveWaits) -> str:
    return _waiting_note(post.archive) if isinstance(step, ArchiveWaits) and post.archive is not None else ""


def _archive_waits(outcome: Delivered | Failure, step: InArchive | ArchiveWaits) -> Delivered | Failure:
    return replace(outcome, archive_waits=True) if isinstance(outcome, Delivered) and isinstance(step, ArchiveWaits) else outcome


def _deliver_archive(
    post: Post, version: Version, box: KeyedBox, *, archive_open: bool
) -> InArchive | ArchiveWaits | Unreachable | NoKey:
    """Plik wysyłki w Archiwum okresu w wersji ``version``, dokładnie raz; wysyłka bez pliku jest już w Archiwum.

    Archiwum z tagiem kolejka znajduje (``archive``) albo zakłada (``open_archive``). Plik tej nazwy w tej wersji albo
    nowszej (z etykiety, ``_asset_version``) zostaje; plik starszej wersji albo urwany w trakcie wysyłki ustępuje
    (``remove``), a potem idzie ten (``upload``). Odmowa Archiwum (``Refused``: brak uprawnienia, ``Rejected``: treść)
    to ``ArchiveWaits``; ``archive_open`` ``False`` daje je bez pytania Skrzynki.
    """

    archive = post.archive
    if archive is None:
        return InArchive()
    if not archive_open:
        return ArchiveWaits()
    listed = box.archive(archive.tag)
    found = box.open_archive(archive.tag, archive.title, archive.description) if listed is None else listed
    if isinstance(found, Refused | Rejected):
        return ArchiveWaits()
    if not isinstance(found, Archive):
        return found
    present = next((asset for asset in found.assets if asset.name == archive.packed_name), None)
    if present is not None:
        seen = _asset_version(present, archive)
        if present.uploaded and seen is not None and seen >= version:
            return InArchive()
        removed = box.remove(present.id)
        if isinstance(removed, Refused):
            return ArchiveWaits()
        if not isinstance(removed, Removed):
            return removed
    sent = box.upload(found.id, archive.packed_name, _asset_label(archive, version), archive.packed())
    if isinstance(sent, Refused | Rejected):
        return ArchiveWaits()
    return InArchive() if isinstance(sent, Asset) else sent


def _asset_label(archive: ArchiveFile, version: Version) -> str:
    """Etykieta pliku w Archiwum: jego nazwa i wersja wysyłki (``Version.text``), jak znacznik wysyłki w komentarzu."""

    return f"{archive.packed_name} (wersja {version.text})"


def _asset_version(asset: Asset, archive: ArchiveFile) -> Version | None:
    """Wersja wysyłki z etykiety pliku (``_asset_label``); etykieta w innej postaci to ``None``."""

    start, end = f"{archive.packed_name} (wersja ", ")"
    seen = asset.label.removeprefix(start).removesuffix(end)
    return Version.of(seen) if asset.label == f"{start}{seen}{end}" and seen and " " not in seen else None


def _issue(issues: tuple[Issue, ...], number: int) -> Issue:
    return next(issue for issue in issues if issue.number == number)


def _comment_all(number: int, comments: Sequence[Marked], box: KeyedBox) -> Delivered | Failure:
    delivered: list[Commented] = []
    for _part, comment in comments:
        answer = box.comment(number, comment)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    return Delivered(number, tuple(delivered))


@dataclass(frozen=True)
class _Seen:
    """Znaczniki wysyłki w znalezionym issue: części w treści z wersją, pierwszy komentarz każdej części z wersją i
    najnowsza wersja tej wysyłki w issue (``None``, gdy żadnej)."""

    in_body: dict[int, Version]
    sent: dict[int, tuple[Version, Comment]]
    newest: Version | None


def _seen(post: Post, issue: Issue, box: KeyedBox) -> _Seen | Failure:
    found = box.comments(issue.number)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    in_body = dict(_marks(issue.body, post))
    newest = max(in_body.values(), default=None)
    sent: dict[int, tuple[Version, Comment]] = {}
    for comment in found:
        for part, seen in _marks(comment.body, post):
            sent.setdefault(part, (seen, comment))
            newest = seen if newest is None else max(newest, seen)
    return _Seen(in_body, sent, newest)


def _settle(post: Post, version: Version, issue: Issue, comments: Sequence[Marked], box: KeyedBox) -> Delivered | Failure:
    """Części ``comments`` w istniejącym issue, każda dokładnie raz, z komentarzami issue przeczytanymi przed wysłaniem.

    Issue, które ma znacznik tej wysyłki w nowszej wersji (w treści albo w komentarzu), od tej wersji nie dostaje
    niczego: starszy plik, który doszedł po nowszym, nie dopisuje, nie zmienia i nie opróżnia żadnej części, także gdy
    ma ich więcej niż nowsza wersja. Inaczej części idą przez ``_put_all``.
    """

    seen = _seen(post, issue, box)
    if not isinstance(seen, _Seen):
        return seen
    if seen.newest is not None and seen.newest > version:
        return _newer(post, issue.number, seen, (part for part, _ in comments))
    return _put_all(post, version, issue.number, comments, seen, box)


def _newer(post: Post, number: int, seen: _Seen, parts: Iterable[int]) -> Delivered:
    """Wysyłka, której issue ma już nowszą wersję: nic nie idzie, a wynik to komentarze części, które tam są."""

    return Delivered(number, tuple(_kept(seen.sent[part][1]) for part in parts if part in seen.sent))


def _put_all(
    post: Post, version: Version, number: int, comments: Sequence[Marked], seen: _Seen, box: KeyedBox
) -> Delivered | Failure:
    """Komentarz części, której ta wersja nie ma (nowsza wersja ma mniej części), dostaje ``_RETIRED``, chyba że dostał
    go już od tej wersji (ponowienie po zgubionej odpowiedzi).
    """

    delivered: list[Commented] = []
    for part, text in comments:
        if part in seen.in_body:
            continue
        answer = _put(number, seen.sent.get(part), text, version, box)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    wanted = {part for part, _ in comments} | seen.in_body.keys()
    for part, (was, comment) in sorted(seen.sent.items()):
        if part not in wanted and was < version:
            answer = box.edit_comment(comment.id, _marked(_RETIRED, post, part, version)[1])
            if not isinstance(answer, Commented):
                return answer
    return Delivered(number, tuple(delivered))


def _put(
    number: int, sent: tuple[Version, Comment] | None, text: str, version: Version, box: KeyedBox
) -> Commented | Failure:
    if sent is None:
        return box.comment(number, text)
    seen, comment = sent
    if seen < version:
        return box.edit_comment(comment.id, text)
    return _kept(comment)


def _kept(comment: Comment) -> Commented:
    """Komentarz części, który już jest w Skrzynce, jako wynik wysyłki (jego adres zna potem ``Outbox.delivered``)."""

    return Commented(comment.id, comment.url)


def _superseded(read: Mapping[Path, _Queued | None]) -> frozenset[Path]:
    """Pliki przejścia, gdy przejście ma czytelny plik nowszej wersji tej samej wysyłki (ten sam cel i ``run_id``,
    ``Version``): przed nimi albo za nimi w porządku kolejki, bo wersja zastępcza ze startu Centrum powstaje po Logach z
    wynikiem, a jest od nich starsza."""

    newest: dict[tuple[Target, str], tuple[Version, Path]] = {}
    for path, queued in read.items():
        if queued is not None:
            key, mine = (queued.post.target, queued.post.run_id), (_version_of(path, queued.post), path)
            newest[key] = max(newest.get(key, mine), mine)
    return frozenset(
        path
        for path, queued in read.items()
        if queued is not None and newest[queued.post.target, queued.post.run_id][1] != path
    )


def _waiting(outcome: Failure) -> tuple[WaitingCause, Literal["stop", "next"]]:
    """Przyczyna w dzienniku i co dalej w przejściu kolejki po porażce wysyłki.

    Brak klucza, brak sieci (także limit zapytań) i odmowa (401/403/404: klucz albo dostęp) spotkałyby każdy następny plik,
    więc przejście staje z jedną linią dziennika. Odmowa treści dotyczy tylko tego pliku: zostaje do następnego
    startu Centrum, a przejście idzie dalej.
    """

    match outcome:
        case NoKey():
            return "brak-klucza", "stop"
        case Unreachable():
            return "brak-sieci", "stop"
        case Refused():
            return "odmowa", "stop"
        case Rejected():
            return "odmowa-tresci", "next"
        case _:
            assert_never(outcome)


class Deliveries(Protocol):
    """Co kolejka wie o swoich dostarczonych i odrzuconych wysyłkach; ``Outbox`` podaje siebie słuchaczowi jako ten widok."""

    def delivered(self, run_id: str, label: Label) -> str | None: ...

    def rejected(self, run_id: str, label: Label) -> bool: ...


class Listener(Protocol):
    """Kto nadaje wysyłce znaczenie poza kolejką; wszystko w wątku wysyłki, bez blokady kolejki.

    ``prepare`` dostaje wysyłkę z pliku tuż przed wysłaniem i zwraca tę, która pójdzie, albo ``None``: wysyłka czeka na
    inną i zostaje w kolejce do następnego przejścia. ``delivered`` dostaje każdą wysyłkę przyjętą przez skrzynkę i
    numer jej issue, zanim ``wait_delivered`` się obudzi i plik dostanie znacznik, i zwraca wysyłki następcze, które
    kolejka kładzie wtedy w swoich plikach. ``rejected`` dostaje każdą wysyłkę, której treść skrzynka odrzuciła, zanim
    przejście pójdzie dalej. Wysyłka może nieść stan, który słuchacz nadaje i czyta (``Post.state``).
    """

    def prepare(self, post: Post, sent: Deliveries) -> Post | None: ...

    def delivered(self, post: Post, number: int) -> Sequence[Post]: ...

    def rejected(self, post: Post) -> None: ...


@dataclass(frozen=True)
class QueueState:
    """Pamięć kolejki, od której zależą jej następne przejścia (``Outbox.state``): pliki, których usunięcie się nie udało,
    przyczyna, na której stanęło ostatnie przejście, odmowa Archiwum okresu w nim, nastawione budzenie oraz to, czy
    przejście trwa i czy ma przejść kolejkę jeszcze raz.

    Nie ma tu tego, co następnych wysyłek nie zmienia: adresów pierwszych komentarzy (``delivered``, ``wait_delivered``),
    plików i wysyłek odrzuconych, nieudanego odczytu, blokady folderu u innego procesu (przejście ustawia oba od nowa, a
    budzenie, które nastawiły, jest w ``retry_armed``) i plików, o których dziennik już wie (oszczędzają mu tylko linii).
    """

    undeleted: frozenset[str]
    stopped_on: WaitingCause | None
    archive_refused: bool
    retry_armed: bool
    draining: bool
    again: bool


class Outbox:
    """Pliki kolejki w ``directory`` i jedyny wątek, który je wysyła, także sam po porażce skrzynki.

    Każdy plik ma jednego autora (``post``, nowa nazwa) i jednego czytelnika naraz, który go oznacza i usuwa
    (przejście wątku ``skrzynka-kolejka`` z blokadą folderu), więc same pliki nie potrzebują blokady. ``_lock`` chroni
    tylko to, czy wątek już biegnie, i adresy dostarczonych wysyłek; zbiory nazw plików i plik ``addresses`` zna tylko
    ten jeden wątek. ``listener`` dostaje każdą wysyłkę przed wysłaniem i jej wynik (``Listener``).

    Przejście, które stanęło na przyczynie dla całej kolejki, pominęło plik, którego nie dało się odczytać, zastało
    blokadę folderu u innego procesu albo odmowę Archiwum okresu, nastawia jedno budzenie ``clock`` za ``RETRY_S``,
    chyba że już jest nastawione; budzenie rusza wysyłkę w tle. Uszkodzona treść pliku, odrzucona treść i wysyłka, którą zatrzymał
    ``Listener.prepare``, budzenia nie nastawiają: ponowienie im nie pomoże. Linia „skrzynka-czeka” trafia do dziennika
    tylko przy zmianie przyczyny (zeruje ją każde dostarczenie i przejście do końca), bo budzenie co minutę zapełniłoby
    ostatnie wpisy, które niesie Diagnoza.
    """

    def __init__(
        self,
        directory: Path,
        box: KeyedBox,
        log: CentrumLog,
        *,
        clock: Clock,
        listener: Listener,
        addresses: Path | None = None,
        disk: QueueDisk = LOCAL_QUEUE_DISK,
        start: Callable[[Callable[[], None]], None] = _in_thread,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        """``disk`` czyta, zapisuje i usuwa pliki kolejki, a ``start`` uruchamia przejście (``_drain``) w tle; inne niż
        domyślne daje tylko wyrocznia ``verify-kolejka-skrzynki``, która decyduje o każdym kroku. ``now`` to zegar
        ścienny komputera w UTC, z którego ``post`` bierze chwilę do nazwy pliku."""

        self._directory = directory
        self._disk = disk
        self._start = start
        self._now = now
        self._box = box
        self._log = log
        self._clock = clock
        self._listener = listener
        self._addresses = addresses
        self._sequence = itertools.count(1)
        self._last_moment: datetime | None = None  # chwila z nazwy ostatniego pliku, który zapisał ``post``
        # _draining, _again, _retry_armed, _first_comments, _rejected_posts, _sequence, _last_moment
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._draining = False
        self._again = False
        self._retry_armed = False
        self._stopped_on: WaitingCause | None = None  # tylko wątek kolejki
        self._read_failed = False  # tylko wątek kolejki: ostatnie przejście pominęło plik, którego nie dało się odczytać
        self._locked_out = False  # tylko wątek kolejki: ostatnie przejście zastało blokadę folderu u innego procesu
        self._archive_refused = False  # tylko wątek kolejki: Archiwum okresu odmówiło w ostatnim przejściu
        self._first_comments: dict[tuple[str, Label], str | None] = {} if addresses is None else _read_addresses(addresses)
        self._undeleted: set[str] = set()  # wysłane w tej pracy Centrum, usunięcie się nie udało i jest w dzienniku
        self._unreadable: set[str] = set()  # nieczytelne, już w dzienniku tej pracy Centrum
        self._rejected: set[str] = set()  # treść odrzucona przez skrzynkę, w dzienniku; następna próba po starcie
        self._rejected_posts: set[tuple[str, Label]] = set()  # run_id i etykieta plików z _rejected
        self._archive_logged: set[str] = set()  # pliki czekające na Archiwum, już w dzienniku tej pracy Centrum

    def resume(self) -> None:
        """Przy starcie Centrum: usuwa pozostałości urwanego zapisu i wysyła w tle wszystko, co czeka.

        Woła go ``lifespan`` przed przyjęciem pierwszego zapytania HTTP, więc ``*.tmp`` nie ma autora w tej pracy
        Centrum. Został po zapisie przerwanym w poprzedniej (np. utrata zasilania) albo pisze go jeszcze poprzednie
        Centrum, które po zwolnieniu portu kończy otwarte zapytania do ``_GRACEFUL_SHUTDOWN_S`` (``server``) i swoje
        przejście kolejki. Jego ``post`` zwraca wtedy ``False`` i zapytanie odmawia tacie (Uwaga taty, Zgłoszenie), a
        znacznik dostarczenia się nie zapisuje, choć plik i tak znika w ``_remove``. Plik ``.json`` obok ``*.tmp``, jeśli
        jest, ma pełną treść sprzed tego zapisu. Start nie czeka na skrzynkę: pyta ją tylko wątek w tle.
        """

        with suppress(OSError):
            for leftover in self._directory.glob("*.tmp"):
                with suppress(OSError):
                    leftover.unlink()
        self.send_in_background()

    @property
    def directory(self) -> Path:
        return self._directory

    def state(self) -> QueueState:
        """Pamięć kolejki między przejściami (``QueueState``); wyrocznia ``verify-kolejka-skrzynki`` porównuje ją, by nie
        sprawdzać drugi raz stanu, który już zna."""

        with self._lock:
            return QueueState(
                frozenset(self._undeleted),
                self._stopped_on,
                self._archive_refused,
                self._retry_armed,
                self._draining,
                self._again,
            )

    def delivered(self, run_id: str, label: Label) -> str | None:
        """Adres pierwszego komentarza wysyłki ``label`` z Uruchomienia ``run_id``, przyjętej przez skrzynkę.

        Zna wysyłki z tej pracy Centrum i z pliku ``addresses``. ``None``: wysyłka czeka w kolejce, nie powstała,
        cała zmieściła się w treści nowego issue albo jej adresu nie dało się zapamiętać.
        """

        with self._lock:
            return self._first_comments.get((run_id, label))

    def rejected(self, run_id: str, label: Label) -> bool:
        """Skrzynka odrzuciła w tej pracy Centrum treść wysyłki ``label`` z ``run_id``; plik czeka na następny start."""

        with self._lock:
            return (run_id, label) in self._rejected_posts

    def wait_delivered(self, run_id: str, label: Label, *, timeout_s: float) -> bool:
        """Czeka najwyżej ``timeout_s``, aż skrzynka przyjmie wysyłkę ``label`` z ``run_id`` w tej pracy Centrum.

        ``False`` od razu, gdy wątek wysyłki skończył przejście kolejki bez niej (brak klucza, sieci, odmowa, blokada
        folderu u innego procesu).
        """

        def settled() -> bool:
            return (run_id, label) in self._first_comments or not self._draining

        with self._changed:
            self._changed.wait_for(settled, timeout_s)
            return (run_id, label) in self._first_comments

    def post(self, post: Post | LogsPost) -> bool:
        """Zapisuje ``post`` w nowym pliku kolejki i budzi wysyłkę w tle; nie pyta skrzynki i nie czeka na sieć.

        Kolejka bierze tylko ``Post`` i ``comment_versions.LogsPost`` dokładnego typu, a treść pliku kolejki daje funkcja
        modułu ``_queue_text``, nie metoda wysyłki, więc ``to_json`` podmienione na klasie albo obiekcie jej nie zmienia. Nazwa pliku sortuje się po nazwie każdej wcześniejszej wysyłki tej kolejki, także gdy zegar komputera się cofnął
        (Windows poprawia czas): chwila w nazwie jest wtedy o ``_TICK`` późniejsza od poprzedniej, więc wysyłka zapisana
        później ma nowszą wersję (``_version``). ``False``: pliku nie udało się zapisać (typ wyjątku jest w dzienniku) i
        wysyłka przepadła; wysyłka albo tekst innego typu to ``TypeError`` przed zapisem.
        """

        text = _queue_text(post, delivered_parts=0, archived=False)
        with self._lock:  # chwila i numer razem: każda następna nazwa tej kolejki sortuje się po poprzedniej
            now = self._now()
            moment = now if self._last_moment is None else max(now, self._last_moment + _TICK)
            self._last_moment = moment
            name = _file_name(f"{moment:%Y%m%dT%H%M%S%fZ}-{next(self._sequence):04d}", post.target.label, post.run_id)
        try:
            self._disk.write(self._directory / name, text)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="zapis wysyłki do Skrzynki Zgłoszeń")
            return False
        self._log.box_post_queued(label=post.target.label, period=post.period)
        self.send_in_background()
        return True

    def send_in_background(self) -> None:
        """Jeden wątek wysyłki naraz; wywołanie w trakcie wysyłki każe jej przejść kolejkę jeszcze raz."""

        with self._lock:
            if self._draining:
                self._again = True
                return
            self._draining = True
        self._start(self._drain)

    def _drain(self) -> None:
        while True:
            try:
                if _claimed(self._directory):
                    try:
                        with _folder_lock(self._directory) as mine:
                            self._locked_out = not mine
                            if mine:
                                self._send_all()
                    finally:
                        if _released(self._directory):
                            with self._lock:
                                self._again = True
            except Exception as failure:
                self._log.unexpected_failure(failure, where=DRAIN)
            with self._changed:
                if not self._again:
                    self._draining = False
                    waiting = self._stopped_on is not None or self._read_failed or self._archive_refused
                    if (waiting or self._locked_out) and not self._retry_armed:
                        self._retry_armed = True
                        self._clock.after(RETRY_S, self._woken)
                    self._changed.notify_all()
                    return
                self._again = False

    def _woken(self) -> None:
        with self._lock:
            self._retry_armed = False
        self.send_in_background()

    def _send_all(self) -> None:
        """Pliki kolejki po nazwie (czas utworzenia); porażka skrzynki zatrzymuje przejście albo pomija plik (``_waiting``).

        Przejście czyta pliki na początku, więc plik, za którym jest nowsza wersja tej samej wysyłki (``_superseded``),
        oznacza bez wysyłania i usuwa. ``_stopped_on`` to potem przyczyna, na której przejście stanęło, albo ``None``,
        ``_read_failed`` mówi, czy przejście pominęło plik, którego nie dało się odczytać, a ``_archive_refused``, czy
        Archiwum okresu odmówiło. Plik, którego części już są w Skrzynce (``_Queued.commented``), czeka tylko na Archiwum
        i idzie bez issue.
        """

        self._read_failed = False
        self._archive_refused = False
        paths = sorted(self._directory.glob("*.json"))
        read = {path: self._read(path) for path in paths if path.name not in self._undeleted | self._rejected}
        superseded = _superseded(read)
        for path in paths:
            if path.name in self._undeleted:
                self._remove(path)
                continue
            if path.name in self._rejected:
                continue
            queued = read[path]
            if queued is None:
                self._skip_unreadable(path)
                continue
            if queued.delivered:
                self._remove(path)
                continue
            if path in superseded:
                # Znacznik jak po wysłaniu: plik, którego nie da się usunąć, nie czeka w kolejce bez niego.
                self._mark_delivered(path, queued.post)
                continue
            post = self._listener.prepare(queued.post, self)
            if post is None:
                continue
            label, period = post.target.label, post.period
            if queued.commented:
                step = _deliver_archive(post, _version_of(path, post), self._box, archive_open=not self._archive_refused)
                if isinstance(step, Unreachable | NoKey):
                    self._stop(label, period, _waiting(step)[0])
                    return
                if isinstance(step, ArchiveWaits):
                    self._archive_waits(path, post)
                    continue
                self._stopped_on = None
                self._log.box_post_archived(label=label, period=period)
                self._mark_delivered(path, post)
                continue
            outcome = _deliver(post, _version_of(path, post), self._box, archive_open=not self._archive_refused)
            if isinstance(outcome, Gone):
                self._log.box_post_dropped(label=label, file=path.name, number=outcome.number)
                self._remove(path)
                continue
            if not isinstance(outcome, Delivered):
                cause, then = _waiting(outcome)
                if then == "stop":
                    self._stop(label, period, cause)
                    return
                self._rejected.add(path.name)
                with self._lock:
                    self._rejected_posts.add((post.run_id, label))
                self._log.box_post_waiting(label=label, period=period, cause=cause, file=path.name)
                self._listener.rejected(post)
                continue
            self._stopped_on = None
            self._log.box_post_sent(label=label, period=period, number=outcome.number)
            for follow_up in self._listener.delivered(post, outcome.number):
                self.post(follow_up)
            with self._changed:
                self._first_comments[post.run_id, label] = outcome.comments[0].url if outcome.comments else None
                self._changed.notify_all()
            self._remember_address(post, outcome)
            if outcome.archive_waits:
                self._archive_waits(path, post)
                with suppress(OSError):  # bez znacznika części następna próba znajdzie je w skrzynce (_settle)
                    self._disk.write(path, _queue_text(post, delivered_parts=len(post.parts), archived=False))
                continue
            self._mark_delivered(path, post)
        self._stopped_on = None

    def _read(self, path: Path) -> _Queued | None:
        try:
            return _queued(path, self._disk)
        except OSError:
            self._read_failed = True
            return None

    def _stop(self, label: Label, period: str | None, cause: WaitingCause) -> None:
        if cause != self._stopped_on:
            self._log.box_post_waiting(label=label, period=period, cause=cause)
        self._stopped_on = cause

    def _archive_waits(self, path: Path, post: Post) -> None:
        self._archive_refused = True
        if path.name not in self._archive_logged:
            self._archive_logged.add(path.name)
            self._log.box_post_waiting(label=post.target.label, period=post.period, cause="odmowa-archiwum", file=path.name)

    def _mark_delivered(self, path: Path, post: Post) -> None:
        with suppress(OSError):  # bez znacznika następna próba znajdzie każdą część w skrzynce (_settle) i plik w Archiwum
            self._disk.write(path, _queue_text(post, delivered_parts=len(post.parts), archived=True))
        self._remove(path)

    def _remember_address(self, post: Post, outcome: Delivered) -> None:
        if self._addresses is None or not outcome.comments:
            return
        line = json.dumps({"run_id": post.run_id, "label": post.target.label, "url": outcome.comments[0].url})
        try:
            with self._addresses.open("a", encoding="utf-8") as addresses:
                addresses.write(line + "\n")
        except OSError as failure:
            self._log.unexpected_failure(failure, where="adres wysyłki do Skrzynki Zgłoszeń")

    def _remove(self, path: Path) -> None:
        """Usuwa dostarczony plik; gdy się nie da (np. plik otwarty w Windows), pierwszy raz zapisuje to w dzienniku."""

        try:
            self._disk.remove(path)
        except OSError as failure:
            if path.name not in self._undeleted:
                self._undeleted.add(path.name)
                self._log.unexpected_failure(failure, where="usunięcie wysłanej wysyłki do Skrzynki Zgłoszeń")
            return
        self._undeleted.discard(path.name)

    def _skip_unreadable(self, path: Path) -> None:
        """Uszkodzony plik albo nieznany schemat (np. z nowszej wersji narzędzia) zostaje; dziennik raz na pracę."""

        if path.name not in self._unreadable:
            self._unreadable.add(path.name)
            self._log.box_post_unreadable(file=path.name)
