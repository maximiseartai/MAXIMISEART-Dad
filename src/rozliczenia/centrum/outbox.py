from __future__ import annotations

import base64
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
from rozliczenia.centrum.template_archive import ArchivedTemplate, from_queue
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
ADDRESSES_FILE: Final = "skrzynka-adresy.jsonl"
SCHEMA_VERSION: Final = 3
_TARGET_SCHEMA: Final = 2
_OPEN_ISSUE: Final = "report_issue"
_AGAIN_BEFORE_OPEN_ISSUE: Final = RETURNED_HEADING
_FRAME_RESERVE: Final = 2_000
PART_LIMIT: Final = COMMENT_LIMIT - _FRAME_RESERVE
_RUN_ID_LIMIT: Final = 64
_MARK_RESERVE: Final = 200
TEXT_LIMIT: Final = COMMENT_LIMIT - _MARK_RESERVE
_MARK_START: Final = "<!-- wysyłka "
_MARK_REST: Final = re.compile(r"część ([0-9]+) wersja (\S+) -->")
_TICK: Final = timedelta(microseconds=1)
_RETIRED: Final = "Ta część jest pusta: nowsza wersja tej wysyłki ma mniej części."
RETRY_S: Final = 60.0
DELIVERY_WAIT_S: Final = 5.0
DRAIN: Final = "wysyłka do Skrzynki Zgłoszeń"

Frame = Callable[[int, int, Outgoing], Outgoing]

_PASSES_LOCK: Final = threading.Lock()
_PASSES: Final[dict[Path, bool]] = {}
PASS_LOCK: Final = "przejscie.lock"


def _claimed(directory: Path) -> bool:
    with _PASSES_LOCK:
        alone = directory not in _PASSES
        _PASSES[directory] = not alone
        return alone


def _released(directory: Path) -> bool:
    with _PASSES_LOCK:
        return _PASSES.pop(directory)


@contextmanager
def _folder_lock(directory: Path) -> Iterator[bool]:
    lock_file: BinaryIO | None
    try:
        lock_file = (directory / PASS_LOCK).open("ab")
    except OSError:
        lock_file = None
    if lock_file is None:
        yield True
        return
    # ZEWNĘTRZNE: blokadę flock i msvcrt.locking zwalnia zamknięcie pliku, a system także koniec procesu, nawet zabitego, więc po procesie nie zostaje (strona man flock, Microsoft Learn LockFileEx)
    with lock_file:
        if not _locked(lock_file):
            yield False
            return
        try:
            yield True
        finally:
            # ZEWNĘTRZNE: na Windows zakres blokady zwalnia się przed zamknięciem pliku, bo tak zaleca dokumentacja (Microsoft Learn LockFileEx)
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _locked(lock_file: BinaryIO) -> bool:
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
    label: Label
    line: Outgoing
    closed: Closed
    title: Outgoing


@final
@dataclass(frozen=True)
class NewIssue:
    label: Label
    title: Outgoing


@final
@dataclass(frozen=True)
class KnownIssue:
    label: Label
    number: int


@final
@dataclass(frozen=True)
class OpenIssue:
    label: Label
    line: Outgoing
    title: Outgoing
    again: Outgoing


Target = PeriodThread | NewIssue | KnownIssue | OpenIssue


@final
@dataclass(frozen=True)
class ArchiveFile:
    tag: Outgoing
    title: Outgoing
    description: Outgoing
    name: Outgoing
    text: LogsText
    templates: tuple[ArchivedTemplate, ...] = ()

    @property
    def packed_name(self) -> str:
        return f"{self.name}.gz"

    @property
    def link(self) -> str:
        return archive_url(self.tag, self.packed_name)

    def packed(self) -> bytes:
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
    DRAFT = 0
    STAND_IN = 1
    OWN = 2


_LOWER_RANKS: Final = {str(rank.value): rank for rank in Rank if rank is not Rank.OWN}


@dataclass(frozen=True, order=True)
class Version:
    rank: Rank
    name: str

    @property
    def text(self) -> str:
        return self.name if self.rank is Rank.OWN else f"{self.rank.value}:{self.name}"

    @classmethod
    def of(cls, text: str) -> Version:
        rank, colon, name = text.partition(":")
        if colon and rank in _LOWER_RANKS and name:
            return cls(_LOWER_RANKS[rank], name)
        return cls(Rank.OWN, text)


@final
@dataclass(frozen=True)
class Post:
    target: Target
    period: str | None
    run_id: Outgoing
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
        if not 0 < len(self.run_id) <= _RUN_ID_LIMIT or not self.run_id.isprintable() or " " in self.run_id:
            raise ValueError("Identyfikator wysyłki musi być krótkim napisem bez spacji.")
        if isinstance(self.target, OpenIssue) and self.target.line not in body.splitlines():
            raise ValueError("Treść nowego issue musi mieć wiersz rozpoznawczy celu.")
        if isinstance(self.target, OpenIssue) and comments:
            raise ValueError("Wysyłka do jednego otwartego issue musi mieścić się w jednej części.")
        if isinstance(self.target, OpenIssue) and len(self.target.again) + len(body) > TEXT_LIMIT:
            raise ValueError("Wysyłka do jednego otwartego issue musi mieścić się z nagłówkiem again w komentarzu Skrzynki Zgłoszeń.")

    @classmethod
    def of(
        cls,
        target: Target,
        *,
        period: str | None,
        run_id: Outgoing,
        blocks: Sequence[Outgoing],
        frame: Frame,
        header: Outgoing | None = None,
    ) -> Post:
        texts = _pack(blocks, PART_LIMIT)
        parts = tuple(frame(number, len(texts), text) for number, text in enumerate(texts, start=1))
        return cls(target, period, run_id, header, parts)

    def opening(self) -> tuple[str, tuple[str, ...]]:
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
    return _file_name("*", label, run_id)


def _file_name(version: str, label: str, run_id: str) -> str:
    return f"{version}-{label}-{run_id[:8]}.json"


def _queue_text(post: Post | LogsPost, *, delivered_parts: int, archived: bool) -> str:
    from rozliczenia.centrum.comment_versions import LogsPost

    if type(post) is not Post and type(post) is not LogsPost:
        raise TypeError(f"Plik kolejki bierze tylko Post i LogsPost, nie {type(post).__name__}.")
    header, parts, archive, rank, run_id = post.header, tuple(post.parts), post.archive, post.rank, post.run_id
    if any(type(part) is not Outgoing for part in (*parts, *(() if header is None else (header,)))) or type(rank) is not Rank:
        raise TypeError("Plik kolejki bierze tylko tekst Outgoing z rozliczenia.client_data i stopień Rank.")
    if type(run_id) is not Outgoing:
        raise TypeError(f"Plik kolejki bierze tylko identyfikator wysyłki Outgoing z rozliczenia.client_data, nie {type(run_id).__name__}.")
    file: dict[str, object] | None = None
    if archive is not None:
        if type(archive) is not ArchiveFile:
            raise TypeError(f"Plik kolejki bierze tylko plik ArchiveFile z rozliczenia.centrum.outbox, nie {type(archive).__name__}.")
        templates = _templates_json(archive.templates)
        file = {name: str(value) for name, value in _checked_fields(ArchiveFile, archive).items()}
        if templates:
            file["templates"] = templates
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "target": _target_json(post.target),
            "period": post.period,
            "run_id": str.__str__(run_id),
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
    "LogsText": lambda value: type(value) is LogsText,
}


def _target_json(target: object) -> dict[str, str | int]:
    found = next(((kind, name) for kind, name in _KINDS if type(target) is kind), None)
    if found is None:
        raise TypeError(f"Plik kolejki bierze tylko cel z rozliczenia.centrum.outbox, nie {type(target).__name__}.")
    kind, name = found
    return {"kind": name, **_checked_fields(kind, target)}


def _templates_json(templates: object) -> list[dict[str, str]]:
    if type(templates) is not tuple:
        raise TypeError(f"Plik kolejki bierze Wzorce tylko w krotce, nie {type(templates).__name__}.")
    entries: list[dict[str, str]] = []
    for template in templates:
        if type(template) is not ArchivedTemplate:
            raise TypeError(
                f"Plik kolejki bierze tylko Wzorzec ArchivedTemplate z rozliczenia.centrum.template_archive, nie {type(template).__name__}."
            )
        name, file, content = template.name, template.file, template.content
        if type(name) is not Outgoing or type(file) is not Outgoing or type(content) is not bytes:
            raise TypeError("Wzorzec w pliku kolejki ma nazwy Outgoing i bajty bytes.")
        entries.append(
            {"name": str.__str__(name), "file": str.__str__(file), "content": base64.b64encode(content).decode("ascii")}
        )
    return entries


_COLLECTIONS: Final = frozenset({"templates"})


def _checked_fields(kind: type[Target] | type[ArchiveFile], value: object) -> dict[str, str | int]:
    entry: dict[str, str | int] = {}
    for field in fields(kind):
        if field.name in _COLLECTIONS:
            continue
        read, check = getattr(value, field.name), _FIELDS.get(str(field.type))
        if check is None or not check(read):
            raise TypeError(f"Pole {kind.__name__}.{field.name} w pliku kolejki ma typ {type(read).__name__}.")
        entry[field.name] = read if type(read) is int else str.__str__(read)
    return entry


def _target(entry: dict[str, Any], kind: object) -> Target | None:
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
    try:
        document = json.loads(text)
        schema = document["schema_version"]
        if schema not in (SCHEMA_VERSION, _TARGET_SCHEMA):
            return None
        target = _target(document["target"], document["target"]["kind"])
        if target is None:
            return None
        archive = _archive_file(document["archive"]) if schema == SCHEMA_VERSION else None
        archived = document["archived"] if schema == SCHEMA_VERSION else False
        post = Post(
            target,
            _optional_string(document["period"]),
            tool(_string(document["run_id"])),
            None if document["header"] is None else tool(_string(document["header"])),
            tuple(tool(_string(part)) for part in document["parts"]),
            archive,
            _rank(document.get("rank", Rank.OWN.value)),
            _optional_string(document.get("state")),
        )
        delivered_parts = document["delivered_parts"]
    except (ValueError, KeyError, TypeError):
        return None
    if type(delivered_parts) is not int or not 0 <= delivered_parts <= len(post.parts) or type(archived) is not bool:
        return None
    return _Queued(post, delivered_parts, archived)


def _checked(post: Post) -> Post:
    queued = _parse(_queue_text(post, delivered_parts=0, archived=False))
    if queued is None:
        raise TypeError("Słuchacz kolejki oddał wysyłkę, której plik kolejki nie odczytuje.")
    return queued.post


def _rank(entry: object) -> Rank:
    if type(entry) is not int:
        raise TypeError("stopień wersji")
    return Rank(entry)


def _archive_file(entry: object) -> ArchiveFile | None:
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise TypeError("plik do Archiwum")
    templates = entry.get("templates", [])
    if not isinstance(templates, list):
        raise TypeError("Wzorce pliku do Archiwum")
    return ArchiveFile(
        tool(_string(entry["tag"])),
        tool(_string(entry["title"])),
        tool(_string(entry["description"])),
        tool(_string(entry["name"])),
        logs_text(_string(entry["text"])),
        tuple(_queued_template(template) for template in templates),
    )


def _queued_template(entry: object) -> ArchivedTemplate:
    if not isinstance(entry, dict):
        raise TypeError("Wzorzec pliku do Archiwum")
    content = base64.b64decode(_string(entry["content"]), validate=True)
    return from_queue(_string(entry["name"]), _string(entry["file"]), content)


@dataclass(frozen=True)
class QueueDisk:
    read: Callable[[Path], str]
    write: Callable[[Path, str], None]
    remove: Callable[[Path], None]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


LOCAL_QUEUE_DISK: Final = QueueDisk(read=_read_text, write=replace_atomically, remove=_unlink)


def _in_thread(drain: Callable[[], None]) -> None:
    threading.Thread(target=drain, name=QUEUE_THREAD, daemon=True).start()


def _queued(path: Path, disk: QueueDisk) -> _Queued | None:
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
    archive_waits: bool = False


@dataclass(frozen=True)
class InArchive:
    ...


@dataclass(frozen=True)
class ArchiveWaits:
    logs: bool = True


@dataclass(frozen=True)
class Gone:
    number: int


Failure = Refused | Rejected | Unreachable | NoKey


def _version(path: Path) -> str:
    return "-".join(path.stem.split("-")[:2])


def _version_of(path: Path, post: Post) -> Version:
    return Version(post.rank, _version(path))


def _mark(post: Post, part: int, version: Version) -> str:
    return f"{_MARK_START}{post.target.label} {post.run_id} część {part} wersja {version.text} -->"


Marked = tuple[int, str]


def _marked(text: str, post: Post, part: int, version: Version) -> Marked:
    return part, f"{text}\n{_mark(post, part, version)}"


def _marks(text: str, post: Post) -> Iterator[tuple[int, Version]]:
    start = f"{_MARK_START}{post.target.label} {post.run_id} "
    for line in text.splitlines():
        if line.startswith(start) and (found := _MARK_REST.fullmatch(line.removeprefix(start))):
            yield int(found.group(1)), Version.of(found.group(2))


def _opening(post: Post, version: Version, *, note: str = "") -> tuple[Marked, tuple[Marked, ...]]:
    body, comments = post.opening()
    first = len(post.parts) - len(comments) + 1
    opened = 0 if post.header is not None else 1
    return (
        _marked(_noted(body, note) if opened else body, post, opened, version),
        tuple(_marked(_noted(text, note), post, part, version) for part, text in enumerate(comments, start=first)),
    )


def _deliver(post: Post, version: Version, box: KeyedBox, *, archive_open: bool) -> Delivered | Gone | Failure:
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
    found = box.known_issue(known.label, known.number)
    if found is None:
        return Gone(known.number)
    if isinstance(found, Refused | Unreachable | NoKey):
        return found
    return _settle(post, version, found, _opening(post, version)[1], box)


def _deliver_to_period(
    post: Post, version: Version, thread: PeriodThread, box: KeyedBox, *, archive_open: bool
) -> Delivered | Failure:
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
    return _waiting_note(post.archive) if isinstance(step, ArchiveWaits) and step.logs and post.archive is not None else ""


def _archive_waits(outcome: Delivered | Failure, step: InArchive | ArchiveWaits) -> Delivered | Failure:
    return replace(outcome, archive_waits=True) if isinstance(outcome, Delivered) and isinstance(step, ArchiveWaits) else outcome


def _deliver_archive(
    post: Post, version: Version, box: KeyedBox, *, archive_open: bool
) -> InArchive | ArchiveWaits | Unreachable | NoKey:
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
    template_waits = False
    for template in archive.templates:
        sent_template = _deliver_template(found, template, box)
        if isinstance(sent_template, Unreachable | NoKey):
            return sent_template
        template_waits = template_waits or isinstance(sent_template, ArchiveWaits)
    logs = _deliver_logs_file(found, archive, version, box)
    if isinstance(logs, InArchive) and template_waits:
        return ArchiveWaits(logs=False)
    return logs


def _deliver_template(
    found: Archive, template: ArchivedTemplate, box: KeyedBox
) -> InArchive | ArchiveWaits | Unreachable | NoKey:
    present = next((asset for asset in found.assets if asset.name == template.name), None)
    if present is not None and present.uploaded:
        return InArchive()
    if present is not None:
        removed = box.remove(present.id)
        if isinstance(removed, Refused):
            return ArchiveWaits()
        if not isinstance(removed, Removed):
            return removed
    sent = box.upload(found.id, template.name, template.file, template.content)
    if isinstance(sent, Refused | Rejected):
        return ArchiveWaits()
    return InArchive() if isinstance(sent, Asset) else sent


def _deliver_logs_file(
    found: Archive, archive: ArchiveFile, version: Version, box: KeyedBox
) -> InArchive | ArchiveWaits | Unreachable | NoKey:
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
    return f"{archive.packed_name} (wersja {version.text})"


def _asset_version(asset: Asset, archive: ArchiveFile) -> Version | None:
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
    seen = _seen(post, issue, box)
    if not isinstance(seen, _Seen):
        return seen
    if seen.newest is not None and seen.newest > version:
        return _newer(post, issue.number, seen, (part for part, _ in comments))
    return _put_all(post, version, issue.number, comments, seen, box)


def _newer(post: Post, number: int, seen: _Seen, parts: Iterable[int]) -> Delivered:
    return Delivered(number, tuple(_kept(seen.sent[part][1]) for part in parts if part in seen.sent))


def _put_all(
    post: Post, version: Version, number: int, comments: Sequence[Marked], seen: _Seen, box: KeyedBox
) -> Delivered | Failure:
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
    return Commented(comment.id, comment.url)


def _superseded(read: Mapping[Path, _Queued | None]) -> frozenset[Path]:
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
    def delivered(self, run_id: str, label: Label) -> str | None: ...

    def rejected(self, run_id: str, label: Label) -> bool: ...


class Listener(Protocol):
    def prepare(self, post: Post, sent: Deliveries) -> Post | None: ...

    def delivered(self, post: Post, number: int) -> Sequence[Post]: ...

    def rejected(self, post: Post) -> None: ...


@dataclass(frozen=True)
class QueueState:
    undeleted: frozenset[str]
    stopped_on: WaitingCause | None
    archive_refused: bool
    retry_armed: bool
    draining: bool
    again: bool


class Outbox:
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
        self._last_moment: datetime | None = None
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._draining = False
        self._again = False
        self._retry_armed = False
        self._stopped_on: WaitingCause | None = None
        self._read_failed = False
        self._locked_out = False
        self._archive_refused = False
        self._first_comments: dict[tuple[str, Label], str | None] = {} if addresses is None else _read_addresses(addresses)
        self._undeleted: set[str] = set()
        self._unreadable: set[str] = set()
        self._rejected: set[str] = set()
        self._rejected_posts: set[tuple[str, Label]] = set()
        self._archive_logged: set[str] = set()

    def resume(self) -> None:
        with suppress(OSError):
            for leftover in self._directory.glob("*.tmp"):
                with suppress(OSError):
                    leftover.unlink()
        self.send_in_background()

    @property
    def directory(self) -> Path:
        return self._directory

    def state(self) -> QueueState:
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
        with self._lock:
            return self._first_comments.get((run_id, label))

    def rejected(self, run_id: str, label: Label) -> bool:
        with self._lock:
            return (run_id, label) in self._rejected_posts

    def wait_delivered(self, run_id: str, label: Label, *, timeout_s: float) -> bool:
        def settled() -> bool:
            return (run_id, label) in self._first_comments or not self._draining

        with self._changed:
            self._changed.wait_for(settled, timeout_s)
            return (run_id, label) in self._first_comments

    def post(self, post: Post | LogsPost) -> bool:
        text = _queue_text(post, delivered_parts=0, archived=False)
        with self._lock:
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
                self._mark_delivered(path, queued.post)
                continue
            prepared = self._listener.prepare(queued.post, self)
            if prepared is None:
                continue
            post = _checked(prepared)
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
                with suppress(OSError):
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
        with suppress(OSError):
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
        try:
            self._disk.remove(path)
        except OSError as failure:
            if path.name not in self._undeleted:
                self._undeleted.add(path.name)
                self._log.unexpected_failure(failure, where="usunięcie wysłanej wysyłki do Skrzynki Zgłoszeń")
            return
        self._undeleted.discard(path.name)

    def _skip_unreadable(self, path: Path) -> None:
        if path.name not in self._unreadable:
            self._unreadable.add(path.name)
            self._log.box_post_unreadable(file=path.name)
