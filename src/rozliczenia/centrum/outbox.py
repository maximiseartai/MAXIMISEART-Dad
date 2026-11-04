"""Kolejka Skrzynki Zgłoszeń: Kontrole ilości, Logi Uruchomienia, Uwagi taty i Zgłoszenia, które Centrum wysyła w tle.

Każda wysyłka (``Post``) to gotowy tekst skierowany do issue okresu (``PeriodThread``: etykieta, wiersz rozpoznawczy
na początku treści issue, tytuł i co z issue, które Maks zamknął), do nowego issue (``NewIssue``: etykieta i tytuł,
jak Uwaga taty), do issue o znanym numerze (``KnownIssue``) albo do jednego otwartego Zgłoszenia problemu
(``ReportIssue``: wiersz odcisku problemu w treści i tytuł, zawsze jedna część; Zgłoszenie, którego odcisk ma już
otwarte issue, idzie do niego komentarzem „Zgłoszenie wróciło”). Najpierw trafia do własnego pliku JSON w
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
wersją, czyli chwilą i numerem z nazwy pliku kolejki (``_version``), w porządku kolejki. Przed wysłaniem kolejka
czyta treść i komentarze issue celu (``_settle``): część, której znacznik już tam jest w tej albo nowszej wersji,
nie idzie drugi raz, komentarz części w starszej wersji dostaje nowy tekst (``edit_comment``), a komentarz części,
której nowsza wersja nie ma, dostaje ``_RETIRED``. Tak Diagnoza, która wysyła Logi Uruchomienia drugi raz z tym samym
identyfikatorem, zmienia komentarz swojego Uruchomienia, a starszy plik, który dojdzie po nowszym (np. raz
nieczytelny), niczego nie cofa. Treści issue kolejka nigdy nie zmienia.

Issue okresu kolejka znajduje po wierszu rozpoznawczym przy każdej próbie wysyłki i dopisuje do niego części jako
komentarze. Bez niego zakłada nowe issue: pierwsza część (albo nagłówek) jest jego treścią, kolejne komentarzami.
``NewIssue`` szuka issue, którego treść ma znacznik tej wysyłki (także zamkniętego), a bez niego zakłada nowe, więc
issue, które założyła przerwana próba, dostaje tylko brakujące części. Kto czeka na wynik (Uwaga taty), może poczekać
na dostarczenie przez ``wait_delivered``.

Adres pierwszego komentarza każdej dostarczonej wysyłki (np. Logów Uruchomienia, do których prowadzi przypięta
Uwaga taty) kolejka dopisuje do pliku ``addresses`` i wczytuje przy następnym starcie Centrum, więc ``delivered``
zna też wysyłki poprzednich prac Centrum. Co wysyłka znaczy poza kolejką, wie jej słuchacz (``Listener``, w Centrum
Sprawy taty w Skrzynce, ``case_delivery``): tuż przed wysłaniem może ją zmienić albo zostawić w kolejce do następnego
przejścia, a po przyjęciu albo odrzuceniu treści przez skrzynkę dostaje wynik i oddaje wysyłki, które z niego wynikają.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Final, Literal, Protocol, assert_never, get_args

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.log import CentrumLog, WaitingCause
from rozliczenia.centrum.report_box import (
    COMMENT_LIMIT,
    Comment,
    Commented,
    Issue,
    Label,
    Refused,
    Rejected,
    Sent,
    Unreachable,
    newest_with_line,
)

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

QUEUE_DIRECTORY: Final = "kolejka"
# Poza ``config/zgloszenia``: weryfikacja Kontroli ilości sprawdza, że jest tam tylko kolejka.
ADDRESSES_FILE: Final = "skrzynka-adresy.jsonl"
SCHEMA_VERSION: Final = 2
# Pliki kolejki sprzed ``NewIssue`` (#273) mają cel w kluczu ``thread`` i zawsze jest nim issue okresu.
_PERIOD_THREAD_SCHEMA: Final = 1
# Miejsce w komentarzu na nagłówek części, wiersz rozpoznawczy i znacznik wysyłki, ponad tekst bloków.
_FRAME_RESERVE: Final = 2_000
# Najwięcej znaków tekstu bloków w jednej części; treść Zgłoszenia (``ReportIssue``) mieści się w jednej.
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
# Tekst komentarza części, której nowsza wersja wysyłki już nie ma (Logi po Diagnozie krótsze o część).
_RETIRED: Final = "Ta część jest pusta: nowsza wersja tej wysyłki ma mniej części."
# Etykieta Zgłoszenia jak ``dad_cases.REPORT``.
_REPORT_LABEL: Final[Label] = "zgloszenie"
# Początek wiersza odcisku problemu w treści Zgłoszenia (``fingerprint_line``).
_FINGERPRINT_PREFIX: Final = "- Odcisk problemu: "
# Nagłówek komentarza, którym Zgłoszenie trafia do otwartego Zgłoszenia tego samego odcisku (``returned_report``).
_RETURNED_HEADING: Final = "## Zgłoszenie wróciło\n\n"
# Po przejściu, które stanęło na przyczynie dla całej kolejki (brak sieci, brak klucza, odmowa klucza), kolejka
# próbuje znowu po minucie. Odrzucony klucz nie kosztuje przy tym zapytania: ``KeyedBox`` odpowiada ``Refused`` bez
# sieci przez kwadrans, a brak klucza to odczyt pliku. Nieudana próba DNS raz na minutę nic nie kosztuje, a dłuższa
# przerwa opóźniłaby wysyłkę po powrocie sieci.
RETRY_S: Final = 60.0
# Tyle „Wyślij” Uwagi taty i „Wyślij do Maksa” czekają na skrzynkę, zanim powiedzą, że wysyłka czeka w kolejce.
DELIVERY_WAIT_S: Final = 5.0

Frame = Callable[[int, int, str], str]
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


@dataclass(frozen=True)
class PeriodThread:
    """Issue okresu w Skrzynce Zgłoszeń: etykieta, wiersz rozpoznawczy i co z issue, które Maks zamknął."""

    label: Label
    line: str
    """Dokładny wiersz treści, po którym znaleźć issue; kolejka stawia go na początku każdego issue, które zakłada."""
    closed: Closed
    """Kontrola ilości: zamknięte issue to nowe issue okresu; Logi Uruchomienia: dalej to samo."""
    title: str
    """Tytuł, gdy issue trzeba założyć."""


@dataclass(frozen=True)
class NewIssue:
    """Nowe issue przy każdej wysyłce, bez wiersza rozpoznawczego (Uwaga taty: każda to osobna sprawa)."""

    label: Label
    title: str


@dataclass(frozen=True)
class KnownIssue:
    """Komentarze do issue o znanym numerze (odnośnik do Logów dopisany do issue Uwagi taty)."""

    label: Label
    number: int


def fingerprint_line(fingerprint: str) -> str:
    """Wiersz treści Zgłoszenia z odciskiem problemu, po którym Centrum znajduje otwarte Zgłoszenie w skrzynce."""

    return f"{_FINGERPRINT_PREFIX}{fingerprint}"


def returned_report(body: str) -> str:
    """Komentarz do otwartego Zgłoszenia tego odcisku: nagłówek „Zgłoszenie wróciło” i cała treść Zgłoszenia ``body``."""

    return f"{_RETURNED_HEADING}{body}"


@dataclass(frozen=True, kw_only=True)
class ReportIssue:
    """Zgłoszenie: jedno otwarte issue z etykietą ``zgloszenie`` na odcisk problemu ``fingerprint``.

    Wysyłka Zgłoszenia ma zawsze jedną część, treść issue albo komentarza (``Post`` odrzuca więcej, #724).
    Dostarczenie szuka otwartego Zgłoszenia z wierszem odcisku (``line``). Bez niego zakłada issue z ``title`` i tą
    częścią. Otwarte Zgłoszenie dokładnie z tą treścią założyła przerwana próba tej wysyłki: wysyłka je przejmuje bez
    komentarza. Inne otwarte Zgłoszenie tego odcisku (wcześniejsze, z tego albo innego komputera) dostaje komentarz
    ``returned_report`` z tą częścią, więc Maks widzi, że problem wraca (#820).
    """

    fingerprint: str
    title: str

    @property
    def line(self) -> str:
        """Wiersz odcisku w treści issue; w pliku kolejki zapisany tak samo."""

        return fingerprint_line(self.fingerprint)

    @property
    def label(self) -> Label:
        return _REPORT_LABEL


Target = PeriodThread | NewIssue | KnownIssue | ReportIssue
"""Dokąd w Skrzynce Zgłoszeń idzie wysyłka; dostarczenie rozróżnia cele przez ``match``."""


@dataclass(frozen=True)
class Post:
    """Gotowa wysyłka do Skrzynki Zgłoszeń, wyrenderowana przez wersję narzędzia, która ją utworzyła.

    ``header``: treść nowego issue; ``None``: nowe issue otwiera pierwsza część (Kontrola ilości, Uwaga taty).
    ``run_id`` to Uruchomienie, a dla Uwagi taty jej identyfikator.
    """

    target: Target
    period: str | None
    """Token okresu do dziennika Centrum; ``None``: Uruchomienie bez okresu."""
    run_id: str
    header: str | None
    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        body, comments = self.opening()
        if not self.parts or any(len(text) > TEXT_LIMIT for text in (body, *comments)):
            raise ValueError("Wysyłka musi mieć części mieszczące się w komentarzu Skrzynki Zgłoszeń.")
        # Identyfikator wysyłki stoi w znaczniku w jednej linii (``_mark``), a znacznik mieści się w ``_MARK_RESERVE``.
        if not 0 < len(self.run_id) <= _RUN_ID_LIMIT or not self.run_id.isprintable() or " " in self.run_id:
            raise ValueError("Identyfikator wysyłki musi być krótkim napisem bez spacji.")
        # Przerwaną wysyłkę Zgłoszenia następna próba znajduje po tym wierszu; bez niego założyłaby drugie issue.
        if isinstance(self.target, ReportIssue) and self.target.line not in body.splitlines():
            raise ValueError("Treść nowego issue Zgłoszenia musi mieć wiersz odcisku problemu.")
        # Przerwaną wysyłkę następna próba poznaje po treści issue równej części 1 i przejmuje bez komentarzy, więc
        # część 2 by przepadła. Nagłówek komentarza ``returned_report`` mieści się w zapasie ``PART_LIMIT``.
        if isinstance(self.target, ReportIssue) and comments:
            raise ValueError("Zgłoszenie musi mieścić się w jednej części wysyłki.")

    @classmethod
    def of(
        cls,
        target: Target,
        *,
        period: str | None,
        run_id: str,
        blocks: Sequence[str],
        frame: Frame,
        header: str | None = None,
    ) -> Post:
        """Dzieli ``blocks`` na części mieszczące się w komentarzu i opisuje każdą przez ``frame``.

        Bloki są sklejane w kolejności; blok dłuższy niż część jest cięty. Część ponad limit to ``ValueError``.
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
            case NewIssue() | ReportIssue():
                return first, comments
            case KnownIssue():
                return "", self.parts
            case _:
                assert_never(self.target)

    def to_json(self) -> str:
        return _queue_text(self, delivered_parts=0)


@dataclass(frozen=True)
class _Queued:
    """Plik kolejki: wysyłka i ile jej części skrzynka już przyjęła (wszystkie: plik czeka tylko na usunięcie)."""

    post: Post
    delivered_parts: int

    @property
    def delivered(self) -> bool:
        return self.delivered_parts == len(self.post.parts)


def _queue_text(post: Post, *, delivered_parts: int) -> str:
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "target": _target_json(post.target),
            "period": post.period,
            "run_id": post.run_id,
            "header": post.header,
            "parts": list(post.parts),
            "delivered_parts": delivered_parts,
        },
        ensure_ascii=False,
        indent=2,
    )


def _target_json(target: Target) -> dict[str, str | int]:
    match target:
        case PeriodThread():
            return {
                "kind": "period_thread",
                "label": target.label,
                "line": target.line,
                "closed": target.closed,
                "title": target.title,
            }
        case NewIssue():
            return {"kind": "new_issue", "label": target.label, "title": target.title}
        case KnownIssue():
            return {"kind": "known_issue", "label": target.label, "number": target.number}
        case ReportIssue():
            return {"kind": "report_issue", "label": target.label, "line": target.line, "title": target.title}
        case _:
            assert_never(target)


def _target(entry: dict[str, Any], kind: object) -> Target | None:
    """Cel wysyłki z pliku kolejki; nieznany rodzaj celu albo etykieta to ``None``."""

    if entry["label"] not in _LABELS:
        return None
    if kind == "new_issue":
        return NewIssue(entry["label"], _string(entry["title"]))
    if kind == "known_issue":
        return KnownIssue(entry["label"], entry["number"]) if type(entry["number"]) is int else None
    if kind == "report_issue":
        # Plik kolejki niesie wiersz odcisku; odcisk to reszta wiersza po jego stałym początku.
        line = _string(entry["line"])
        fingerprint = line.removeprefix(_FINGERPRINT_PREFIX)
        if fingerprint == line:
            return None
        return ReportIssue(fingerprint=fingerprint, title=_string(entry["title"]))
    if kind != "period_thread" or entry["closed"] not in _CLOSED:
        return None
    return PeriodThread(entry["label"], _string(entry["line"]), entry["closed"], _string(entry["title"]))


def _parse(text: str) -> _Queued | None:
    """Granica plików kolejki. ``delivered_parts`` jest opcjonalne: pliki z #273 go nie mają i nic nie dostarczyły.

    Pliki od #665 do #840 mogą mieć numer issue Uwagi taty (``issue``) i kolejka go pomija: issue wysyłki znajduje po
    znaczniku, a Uwaga ma jedną część, więc żadna jej próba nie zostawiła issue bez całej treści.
    """

    try:
        document = json.loads(text)
        schema = document["schema_version"]
        if schema == SCHEMA_VERSION:
            target = _target(document["target"], document["target"]["kind"])
        elif schema == _PERIOD_THREAD_SCHEMA:
            target = _target(document["thread"], "period_thread")
        else:
            return None
        if target is None:
            return None
        post = Post(
            target,
            _optional_string(document["period"]),
            _string(document["run_id"]),
            _optional_string(document["header"]),
            tuple(_string(part) for part in document["parts"]),
        )
        delivered_parts = document.get("delivered_parts", 0)
    except (ValueError, KeyError, TypeError):
        return None
    if type(delivered_parts) is not int or not 0 <= delivered_parts <= len(post.parts):
        return None
    return _Queued(post, delivered_parts)


def _queued(path: Path) -> _Queued | None:
    """Plik kolejki albo ``None``: uszkodzona treść albo nieznany schemat.

    ``OSError`` (plik trzyma np. OneDrive albo antywirus) przechodzi do wołającego: ten sam plik może się dać odczytać
    za chwilę, a treść, której się nie da, zostanie taka sama.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        return None
    return _parse(text)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("napis")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _pack(blocks: Sequence[str], budget: int) -> tuple[str, ...]:
    """Bloki sklejone w kolejności w części najwyżej ``budget`` znaków; blok, który się mieści, nie jest dzielony."""

    parts: list[str] = []
    current = ""
    for block in blocks:
        if len(block) <= budget:
            if len(current) + len(block) > budget:
                parts.append(current)
                current = ""
            current += block
            continue
        rest = current + block  # blok i tak jest cięty, więc dopełnia bieżącą część
        while len(rest) > budget:
            parts.append(rest[:budget])
            rest = rest[budget:]
        current = rest
    if current:
        parts.append(current)
    return tuple(parts)


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
    number: int
    comments: tuple[Commented, ...]


@dataclass(frozen=True)
class Gone:
    """Skrzynka działa, ale nie ma już issue ``number`` (Maks je usunął): wysyłka do niego nigdy nie przejdzie."""

    number: int


Failure = Refused | Rejected | Unreachable | NoKey
"""Porażka wysyłki: odmowa klucza, odmowa treści, brak sieci albo brak klucza."""


def _version(path: Path) -> str:
    """Wersja wysyłki z pliku ``path``: chwila i numer z początku nazwy (``Outbox.post``), w porządku kolejki."""

    return "-".join(path.stem.split("-")[:2])


def _mark(post: Post, part: int, version: str) -> str:
    """Znacznik części ``part`` (0: nagłówek) wysyłki ``post`` w wersji ``version``; GitHub go nie pokazuje."""

    return f"{_MARK_START}{post.target.label} {post.run_id} część {part} wersja {version} -->"


Marked = tuple[int, str]
"""Część wysyłki (0: nagłówek) i jej tekst ze znacznikiem."""


def _marked(text: str, post: Post, part: int, version: str) -> Marked:
    """Część ``part`` i jej tekst ze znacznikiem w ostatniej linii."""

    return part, f"{text}\n{_mark(post, part, version)}"


def _marks(text: str, post: Post) -> Iterator[tuple[int, str]]:
    """Część i wersja każdego znacznika wysyłki ``post`` w ``text``; linia w innej postaci znacznikiem nie jest."""

    start = f"{_MARK_START}{post.target.label} {post.run_id} "
    for line in text.splitlines():
        if line.startswith(start) and (found := _MARK_REST.fullmatch(line.removeprefix(start))):
            yield int(found.group(1)), found.group(2)


def _opening(post: Post, version: str) -> tuple[Marked, tuple[Marked, ...]]:
    """``Post.opening`` ze znacznikami: treść nowego issue i komentarze po niej."""

    body, comments = post.opening()
    first = len(post.parts) - len(comments) + 1
    return (
        _marked(body, post, 0 if post.header is not None else 1, version),
        tuple(_marked(text, post, part, version) for part, text in enumerate(comments, start=first)),
    )


def _deliver(post: Post, version: str, box: KeyedBox) -> Delivered | Gone | Failure:
    """Wysyłka w wersji ``version`` do jej celu."""

    match post.target:
        case PeriodThread() as thread:
            return _deliver_to_period(post, version, thread, box)
        case NewIssue() as issue:
            return _deliver_new_issue(post, version, issue, box)
        case KnownIssue() as known:
            return _deliver_to_known(post, version, known, box)
        case ReportIssue() as report:
            return _deliver_report(post, version, report, box)
        case _:
            assert_never(post.target)


def _deliver_new_issue(post: Post, version: str, issue: NewIssue, box: KeyedBox) -> Delivered | Failure:
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


def _deliver_report(post: Post, version: str, report: ReportIssue, box: KeyedBox) -> Delivered | Failure:
    """Nowe issue z jedyną częścią wysyłki albo komentarz z nią do otwartego Zgłoszenia z tym odciskiem.

    Jeden problem ma jedno otwarte Zgłoszenie: znalezione dostaje komentarz ``returned_report``. Wyjątkiem jest
    Zgłoszenie, którego treść ma znacznik tej części: założyła je ta wysyłka, a przerwanie przyszło przed znacznikiem
    dostarczenia, więc całe Zgłoszenie już jest w treści i wysyłka je przejmuje bez komentarza (``_settle``).
    """

    issues = box.labelled_issues(report.label, include_closed=False)
    if isinstance(issues, Refused | Unreachable | NoKey):
        return issues
    found = newest_with_line(issues, report.line)
    if found is None:
        (_, body), _ = _opening(post, version)
        opened = box.open_issue(report.label, report.title, body)
        if not isinstance(opened, Sent):
            return opened
        return Delivered(opened.number, ())
    returned = _marked(returned_report(post.parts[0]), post, 1, version)
    return _settle(post, version, _issue(issues, found), (returned,), box)


def _deliver_to_known(post: Post, version: str, known: KnownIssue, box: KeyedBox) -> Delivered | Gone | Failure:
    """Każda część wysyłki komentarzem do issue ``known.number``, jeśli skrzynka je ma (otwarte albo zamknięte).

    Komentarz do issue, które Maks usunął, to 404, czyli odmowa, która zatrzymałaby całą kolejkę, więc kolejka
    najpierw pyta o issue z etykietą. Gdy lista przyszła bez tego numeru, issue nie ma (``Gone``).
    """

    found = box.labelled_issues(known.label, include_closed=True)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    if all(issue.number != known.number for issue in found):
        return Gone(known.number)
    return _settle(post, version, _issue(found, known.number), _opening(post, version)[1], box)


def _deliver_to_period(post: Post, version: str, thread: PeriodThread, box: KeyedBox) -> Delivered | Failure:
    """Każda część jako komentarz do issue okresu, a bez niego nowe issue z pierwszą częścią i komentarze z resztą.

    Issue okresu jest szukane przy każdej próbie, więc usunięte albo zamknięte issue nie blokuje kolejki. Pierwsza
    porażka kończy wysyłkę; następna próba dopisuje tylko części, których w issue nie ma (``_settle``).
    """

    issues = box.labelled_issues(thread.label, include_closed=thread.closed == "reuse")
    if isinstance(issues, Refused | Unreachable | NoKey):
        return issues
    found = newest_with_line(issues, thread.line)
    if found is None:
        (_, body), comments = _opening(post, version)
        opened = box.open_issue(thread.label, thread.title, body)
        if not isinstance(opened, Sent):
            return opened
        return _comment_all(opened.number, comments, box)
    parts = tuple(_marked(text, post, part, version) for part, text in enumerate(post.parts, start=1))
    return _settle(post, version, _issue(issues, found), parts, box)


def _issue(issues: tuple[Issue, ...], number: int) -> Issue:
    return next(issue for issue in issues if issue.number == number)


def _comment_all(number: int, comments: Sequence[Marked], box: KeyedBox) -> Delivered | Failure:
    """Komentarze nowego issue po kolei; pierwsza porażka kończy wysyłkę."""

    delivered: list[Commented] = []
    for _part, comment in comments:
        answer = box.comment(number, comment)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    return Delivered(number, tuple(delivered))


def _settle(post: Post, version: str, issue: Issue, comments: Sequence[Marked], box: KeyedBox) -> Delivered | Failure:
    """Części ``comments`` w istniejącym issue, każda dokładnie raz, z komentarzami issue przeczytanymi przed wysłaniem.

    Część ze znacznikiem w treści issue albo w komentarzu w tej lub nowszej wersji już jest; komentarz części w
    starszej wersji dostaje nowy tekst; reszta to nowe komentarze po kolei. Komentarz części, której ta wersja nie
    ma (nowsza wersja ma mniej części), dostaje ``_RETIRED``. Pierwsza porażka kończy wysyłkę.
    """

    found = box.comments(issue.number)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    in_body = {part for part, _ in _marks(issue.body, post)}
    sent: dict[int, tuple[str, Comment]] = {}
    for comment in found:
        for part, seen in _marks(comment.body, post):
            sent.setdefault(part, (seen, comment))
    delivered: list[Commented] = []
    for part, text in comments:
        if part in in_body:
            continue
        answer = _put(issue.number, sent.get(part), text, version, box)
        if not isinstance(answer, Commented):
            return answer
        delivered.append(answer)
    wanted = {part for part, _ in comments} | in_body
    for part, (seen, comment) in sorted(sent.items()):
        if part not in wanted and seen < version:
            answer = box.edit_comment(comment.id, _marked(_RETIRED, post, part, version)[1])
            if not isinstance(answer, Commented):
                return answer
    return Delivered(issue.number, tuple(delivered))


def _put(number: int, sent: tuple[str, Comment] | None, text: str, version: str, box: KeyedBox) -> Commented | Failure:
    """Komentarz części: nowy, gdy go nie ma, nowy tekst w komentarzu starszej wersji, a inaczej ten, który już jest."""

    if sent is None:
        return box.comment(number, text)
    seen, comment = sent
    if seen < version:
        return box.edit_comment(comment.id, text)
    return Commented(comment.id, comment.url)


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
    przejście pójdzie dalej.
    """

    def prepare(self, post: Post, sent: Deliveries) -> Post | None: ...

    def delivered(self, post: Post, number: int) -> Sequence[Post]: ...

    def rejected(self, post: Post) -> None: ...


class Outbox:
    """Pliki kolejki w ``directory`` i jedyny wątek, który je wysyła, także sam po porażce skrzynki.

    Każdy plik ma jednego autora (``post``, nowa nazwa) i jednego czytelnika naraz, który go oznacza i usuwa
    (przejście wątku ``skrzynka-kolejka`` z blokadą folderu), więc same pliki nie potrzebują blokady. ``_lock`` chroni
    tylko to, czy wątek już biegnie, i adresy dostarczonych wysyłek; zbiory nazw plików i plik ``addresses`` zna tylko
    ten jeden wątek. ``listener`` dostaje każdą wysyłkę przed wysłaniem i jej wynik (``Listener``).

    Dwie kolejki jednego folderu w tym procesie nie wysyłają naraz (``_claimed``): kolejka, która zastanie przejście
    drugiej, nie wysyła nic, a druga po swoim przejściu robi następne. Kolejka, która zastanie blokadę folderu u kolejki
    innego procesu (``_folder_lock``), też nie wysyła nic.

    Przejście, które stanęło na przyczynie dla całej kolejki, pominęło plik, którego nie dało się odczytać, albo
    zastało blokadę folderu u innego procesu, nastawia jedno budzenie ``clock`` za ``RETRY_S``, chyba że już jest
    nastawione; budzenie rusza wysyłkę w tle. Uszkodzona treść pliku, odrzucona treść i wysyłka, którą zatrzymał
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
    ) -> None:
        self._directory = directory
        self._box = box
        self._log = log
        self._clock = clock
        self._listener = listener
        self._addresses = addresses
        self._sequence = itertools.count(1)
        self._lock = threading.Lock()  # _draining, _again, _retry_armed, _first_comments, _rejected_posts
        self._changed = threading.Condition(self._lock)
        self._draining = False
        self._again = False
        self._retry_armed = False
        self._stopped_on: WaitingCause | None = None  # tylko wątek kolejki
        self._read_failed = False  # tylko wątek kolejki: ostatnie przejście pominęło plik, którego nie dało się odczytać
        self._locked_out = False  # tylko wątek kolejki: ostatnie przejście zastało blokadę folderu u innego procesu
        self._first_comments: dict[tuple[str, Label], str | None] = {} if addresses is None else _read_addresses(addresses)
        self._undeleted: set[str] = set()  # wysłane w tej pracy Centrum, usunięcie się nie udało i jest w dzienniku
        self._unreadable: set[str] = set()  # nieczytelne, już w dzienniku tej pracy Centrum
        self._rejected: set[str] = set()  # treść odrzucona przez skrzynkę, w dzienniku; następna próba po starcie
        self._rejected_posts: set[tuple[str, Label]] = set()  # run_id i etykieta plików z _rejected

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

    def post(self, post: Post) -> bool:
        """Zapisuje ``post`` w nowym pliku kolejki i budzi wysyłkę w tle; nie pyta skrzynki i nie czeka na sieć.

        ``False``: pliku nie udało się zapisać (typ wyjątku jest w dzienniku) i wysyłka przepadła.
        """

        moment = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{moment}-{next(self._sequence):04d}-{post.target.label}-{post.run_id[:8]}.json"
        try:
            replace_atomically(self._directory / name, post.to_json())
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
        threading.Thread(target=self._drain, name="skrzynka-kolejka", daemon=True).start()

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
                self._log.unexpected_failure(failure, where="wysyłka do Skrzynki Zgłoszeń")
            with self._changed:
                if not self._again:
                    self._draining = False
                    if (self._stopped_on is not None or self._read_failed or self._locked_out) and not self._retry_armed:
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

        ``_stopped_on`` to potem przyczyna, na której przejście stanęło, albo ``None``, a ``_read_failed`` mówi, czy
        przejście pominęło plik, którego nie dało się odczytać.
        """

        self._read_failed = False
        for path in sorted(self._directory.glob("*.json")):
            if path.name in self._undeleted:
                self._remove(path)
                continue
            if path.name in self._rejected:
                continue
            try:
                queued = _queued(path)
            except OSError:
                self._read_failed = True
                queued = None
            if queued is None:
                self._skip_unreadable(path)
                continue
            if queued.delivered:
                self._remove(path)
                continue
            post = self._listener.prepare(queued.post, self)
            if post is None:
                continue
            label, period = post.target.label, post.period
            outcome = _deliver(post, _version(path), self._box)
            if isinstance(outcome, Gone):
                self._log.box_post_dropped(label=label, file=path.name, number=outcome.number)
                self._remove(path)
                continue
            if not isinstance(outcome, Delivered):
                cause, then = _waiting(outcome)
                if then == "stop":
                    if cause != self._stopped_on:
                        self._log.box_post_waiting(label=label, period=period, cause=cause)
                    self._stopped_on = cause
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
            with suppress(OSError):  # bez znacznika następna próba znajdzie każdą część w skrzynce (_settle)
                replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))
            self._remove(path)
        self._stopped_on = None

    def _remember_address(self, post: Post, outcome: Delivered) -> None:
        """Dopisuje adres pierwszego komentarza do pliku ``addresses``; nieudany zapis to tylko wpis w dzienniku."""

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
            path.unlink(missing_ok=True)
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
