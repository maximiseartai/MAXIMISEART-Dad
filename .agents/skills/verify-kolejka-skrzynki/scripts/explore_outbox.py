"""Exhaustively check that the Kolejka Skrzynki Zgłoszeń delivers every part of every wysyłka exactly once.

The checker runs the real ``outbox.Outbox`` (its ``_drain`` and ``_send_all``) and the real ``KeyedBox`` against an
in-memory Skrzynka Zgłoszeń, on a real queue folder in a temporary directory. Each call the code makes to the
Skrzynka, the write of the delivery marker and the removal of a queue file is one indivisible step. Before every step
the checker may let it succeed, let the network fail before the Skrzynka sees it (``Unreachable``), let the Skrzynka
accept it and lose the answer (``Unreachable`` after the effect), fail the file call with ``OSError``, or kill the
process. Between two passes of the queue it may also restart Centrum. It tries every such schedule within the bounds
of a scope, re-running the code from scratch once per schedule. A pass runs only when the real ``send_in_background``
starts the queue thread, as ``Outbox.post``, ``Outbox.resume`` at a start, or the ``RETRY_S`` wake (``_woken``) that
``_drain`` armed ask it to. When no thread starts, the schedule may end there. Then it checks:

- DOKLADNIE_RAZ: every part of the newest version of every wysyłka is in the Skrzynka exactly once, in an issue of
  its target, and no text of an older version of it is left there (ADR 0015 after #840: „Wysyłka jest dokładnie
  raz”); a part the newest version no longer has is ``_RETIRED``. A wysyłka with a file for the Archiwum okresu
  (#844) has exactly one whole file of its name in the Archiwum of its tag, with the text of the newest version, and
  its file never went twice: the queue never removed a whole file of its version or a newer one to upload it again.
- JEDNO_ISSUE: one problem has one open Zgłoszenie and one period has one issue okresu; a wysyłka to a new issue
  (Uwaga taty) opens one issue.
- KOLEJKA_PUSTA: no queue file without its delivery marker is left when the schedule ends; a delivered file whose
  removal failed may wait for the next start.
- BEZ_WYJATKU: no pass ends in an exception that ``_drain`` logs as ``nieoczekiwany-wyjatek``.

Nothing in ``outbox.py`` or ``keyed_box.py`` is replaced but the start of the queue thread: ``threading.Thread`` in
``outbox.py`` hands its target (``_drain``) to the checker, which runs it in its own thread when nothing else is left
to do, so the real ``send_in_background`` decides whether a pass starts at all. The Skrzynka behind ``KeyedBox`` is
the in-memory ``MemoryBox`` (GitHub's issues and comments, and its Releases with their files for the Archiwum okresu),
the clock never moves and keeps the wakes ``after`` arms, and the key is always there and accepted; only a step of the
Archiwum may be refused (a key without the permission to write the repository's contents).
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum import outbox as outbox_module
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import (
    ArchiveFile,
    Deliveries,
    KnownIssue,
    NewIssue,
    Outbox,
    PeriodThread,
    Post,
    ReportIssue,
)
from rozliczenia.centrum.report_box import (
    Archive,
    ArchiveOutcome,
    Asset,
    Closure,
    Comment,
    CommentOutcome,
    CommentsOutcome,
    Commented,
    Issue,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    Refused,
    Rejected,
    Removed,
    RemoveOutcome,
    SendOutcome,
    Sent,
    Unreachable,
    UploadOutcome,
)

KEY = "github_pat_SYNTETYCZNY_KLUCZ"


class _Unchanged:
    """Słuchacz kolejki bez Spraw taty: każda wysyłka idzie bez zmian i bez wysyłek następczych."""

    def prepare(self, post: Post, sent: Deliveries) -> Post | None:
        return post

    def delivered(self, post: Post, number: int) -> tuple[Post, ...]:
        return ()

    def rejected(self, post: Post) -> None:
        return None
# Passes beyond one per failure until the queue must be empty; a pass without a failure delivers or removes each file.
EXTRA_PASSES = 3
DRAIN_FAILURE = "wysyłka do Skrzynki Zgłoszeń"


class Crash(BaseException):
    """The process dies at this step (Dad closes Centrum, the computer switches off)."""


@dataclass
class _Issue:
    label: Label
    title: str
    body: str
    comments: list[str] = field(default_factory=list)
    comment_ids: list[int] = field(default_factory=list)
    closed: bool = False


@dataclass
class _Asset:
    """A file of a Release: its name, label, packed bytes, and whether its upload ended (GitHub's ``state``)."""

    id: int
    name: str
    label: str
    data: bytes
    uploaded: bool


@dataclass
class _Release:
    id: int
    assets: list[_Asset] = field(default_factory=list)


class MemoryBox:
    """The Skrzynka Zgłoszeń behind ``KeyedBox``: GitHub issues with labels, bodies and comments, numbered from 1, and
    Releases by tag with their files (the Archiwum okresu). As on GitHub, a second Release of one tag and a second file
    of one name in one Release are ``Rejected`` and change nothing.

    ``twice`` names each file the queue sent twice: a whole file it removed and, as its very next call, uploaded again
    in the same version or an older one. ``_deliver_archive`` removes a file only to upload its own newer version right
    after, so the pair is one delivery; any other call, a failure or a restart in between ends the pair.
    """

    def __init__(self, scheduler: Scheduler) -> None:
        self.issues: dict[int, _Issue] = {}
        self.releases: dict[str, _Release] = {}
        self.twice: list[str] = []
        self._scheduler = scheduler
        self._comment_ids = 0
        self._ids = 0
        self._removed: _Asset | None = None  # whole file removed by the call just before, answered


    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        chosen = self._scheduler.archive_read(f"archive({tag})")
        if chosen != "ok":
            return Unreachable() if chosen == "unreachable" else Refused()
        found = self.releases.get(tag)
        self._scheduler.say(f"Skrzynka zwraca Archiwum {tag}: {'brak' if found is None else _files(found)}")
        if found is None:
            return None
        return Archive(found.id, tuple(Asset(a.id, a.name, a.label, a.uploaded) for a in found.assets))

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        chosen = self._scheduler.archive_write(f"open_archive({tag})")
        if chosen in ("unreachable", "partial"):
            return Unreachable()
        if chosen == "refused":
            return Refused()
        if tag in self.releases:
            self._scheduler.say(f"Skrzynka odrzuca drugie Archiwum {tag} (422)")
            return Rejected()
        self.releases[tag] = _Release(self._next_id())
        self._scheduler.say(f"Skrzynka zakłada Archiwum {tag}" + (", odpowiedź ginie (Unreachable)" if chosen == "lost" else ""))
        return Unreachable() if chosen == "lost" else Archive(self.releases[tag].id, ())

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        removed, self._removed = self._removed, None
        chosen = self._scheduler.archive_write(f"upload({_version_of(label)})", partial=True)
        if removed is not None and removed.name == name and _version_of(removed.label) >= _version_of(label):
            self.twice.append(name)
        if chosen == "unreachable":
            return Unreachable()
        if chosen == "refused":
            return Refused()
        release = next(release for release in self.releases.values() if release.id == archive_id)
        if any(asset.name == name for asset in release.assets):
            self._scheduler.say(f"Skrzynka odrzuca drugi plik {name} (422)")
            return Rejected()
        release.assets.append(_Asset(self._next_id(), name, label, data, chosen != "partial"))
        self._scheduler.say(
            {"ok": "Skrzynka przyjmuje plik", "lost": "Skrzynka przyjmuje plik, odpowiedź ginie (Unreachable)"}.get(
                chosen, "połączenie urywa się w trakcie pliku: Skrzynka ma go niepełnego (Unreachable)"
            )
        )
        return Asset(release.assets[-1].id, name, label, True) if chosen == "ok" else Unreachable()

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        self._removed = None
        chosen = self._scheduler.archive_write(f"remove({asset_id})")
        if chosen in ("unreachable", "partial"):
            return Unreachable()
        if chosen == "refused":
            return Refused()
        [gone] = [asset for release in self.releases.values() for asset in release.assets if asset.id == asset_id]
        for release in self.releases.values():
            release.assets = [asset for asset in release.assets if asset.id != asset_id]
        self._scheduler.say("Skrzynka usuwa plik" + (", odpowiedź ginie (Unreachable)" if chosen == "lost" else ""))
        if chosen == "lost":
            return Unreachable()
        self._removed = gone if gone.uploaded else None
        return Removed()

    def open_issue(
        self, label: Label, title: str, body: str, *, key: str
    ) -> SendOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        what = f"open_issue({label}, {_part_name(body)})"
        failure = self._scheduler.box_write(what)
        if failure == "unreachable":
            return Unreachable()
        number = len(self.issues) + 1
        self.issues[number] = _Issue(label, title, body)
        self._scheduler.say(
            f"Skrzynka zakłada issue #{number}"
            + (", odpowiedź ginie (Unreachable)" if failure else "")
        )
        return Unreachable() if failure else Sent(number)

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        failure = self._scheduler.box_write(f"comment(#{number}, {_part_name(body)})")
        if failure == "unreachable":
            return Unreachable()
        self._comment_ids += 1
        self.issues[number].comments.append(body)
        self.issues[number].comment_ids.append(self._comment_ids)
        self._scheduler.say(
            f"Skrzynka dopisuje komentarz do #{number}"
            + (", odpowiedź ginie (Unreachable)" if failure else "")
        )
        return (
            Unreachable()
            if failure
            else Commented(
                self._comment_ids, f"https://skrzynka/{number}#{self._comment_ids}"
            )
        )

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        number, issue = next(
            (number, issue) for number, issue in self.issues.items() if comment_id in issue.comment_ids
        )
        failure = self._scheduler.box_write(f"edit_comment(#{number}, {_part_name(body)})")
        if failure == "unreachable":
            return Unreachable()
        issue.comments[issue.comment_ids.index(comment_id)] = body
        self._scheduler.say(
            f"Skrzynka zmienia komentarz w #{number}"
            + (", odpowiedź ginie (Unreachable)" if failure else "")
        )
        return (
            Unreachable()
            if failure
            else Commented(comment_id, f"https://skrzynka/{number}#{comment_id}")
        )

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        if self._scheduler.box_read(f"comments(#{number})"):
            return Unreachable()
        issue = self.issues[number]
        self._scheduler.say(f"Skrzynka zwraca komentarze #{number}: {len(issue.comments)}")
        return tuple(
            Comment(comment_id, f"https://skrzynka/{number}#{comment_id}", body)
            for comment_id, body in zip(issue.comment_ids, issue.comments, strict=True)
        )

    def labelled_issues(
        self, label: Label, *, include_closed: bool, key: str
    ) -> IssuesOutcome:
        self._removed = None  # any call but upload ends a pair of remove and upload
        if self._scheduler.box_read(f"labelled_issues({label})"):
            return Unreachable()
        found = tuple(
            Issue(
                number, issue.body, Closure("completed", None) if issue.closed else None
            )
            for number, issue in self.issues.items()
            if issue.label == label and (include_closed or not issue.closed)
        )
        self._scheduler.say(
            f"Skrzynka zwraca issue {label}: {[issue.number for issue in found] or 'brak'}"
        )
        return found


Choice = Literal[
    "ok", "unreachable", "lost", "partial", "refused", "oserror", "unreadable", "kill", "next", "restart", "stuck"
]


@dataclass(frozen=True)
class Bounds:
    unreachable: int
    lost: int
    disk: int
    kills: int
    reads: int = 0
    """Reads of a queue file that raise ``OSError`` (OneDrive or an antivirus holding it), so the files after it go
    first in that pass; 0 leaves the read out of the schedules."""
    refusals: int = 0
    """Steps of the Archiwum okresu refused (``Refused``: a key without the permission to write the repository's
    contents); 0 leaves the refusal out of the schedules."""


class Scheduler:
    """Picks one option at each step from the schedule prefix, then the first option; records what it could pick."""

    def __init__(self, prefix: Sequence[int], bounds: Bounds) -> None:
        self._prefix = prefix
        self.taken: list[int] = []
        self.options: list[int] = []
        self.left = {
            "unreachable": bounds.unreachable,
            "lost": bounds.lost,
            "oserror": bounds.disk,
            "unreadable": bounds.reads,
            "refused": bounds.refusals,
            "kill": bounds.kills,
        }
        self.trace: list[str] = []
        self.faults: list[tuple[str, str]] = []

    def say(self, line: str) -> None:
        self.trace.append(line)

    def _pick(self, offered: Sequence[Choice], what: str) -> Choice:
        allowed = [choice for choice in offered if self.left.get(choice, 1) > 0]
        position = len(self.taken)
        index = self._prefix[position] if position < len(self._prefix) else 0
        self.taken.append(index)
        self.options.append(len(allowed))
        chosen = allowed[index]
        if chosen in self.left:
            self.left[chosen] -= 1
            self.faults.append((chosen, what.split("(")[0]))
        return chosen

    def _killed(self, chosen: Choice, what: str) -> None:
        if chosen == "kill":
            self.say(f"proces ginie przed {what}")
            raise Crash

    def box_read(self, what: str) -> bool:
        chosen = self._pick(("ok", "unreachable", "kill"), what)
        self._killed(chosen, what)
        if chosen == "unreachable":
            self.say(f"{what}: brak sieci (Unreachable)")
        return chosen == "unreachable"

    def box_write(self, what: str) -> Literal["unreachable", "lost"] | None:
        chosen = self._pick(("ok", "unreachable", "lost", "kill"), what)
        self._killed(chosen, what)
        if chosen == "unreachable":
            self.say(f"{what}: brak sieci (Unreachable), Skrzynka nic nie dostaje")
            return "unreachable"
        if chosen == "lost":
            self.say(what)
            return "lost"
        self.say(what)
        return None

    def archive_read(self, what: str) -> Literal["ok", "unreachable", "refused"]:
        """A read of the Archiwum: it answers, the network fails, the key lacks the permission, or the process dies."""

        chosen = self._pick(("ok", "unreachable", "refused", "kill"), what)
        self._killed(chosen, what)
        if chosen == "unreachable":
            self.say(f"{what}: brak sieci (Unreachable)")
        if chosen == "refused":
            self.say(f"{what}: odmowa (Refused, Token bez uprawnienia do treści repozytorium)")
        return "unreachable" if chosen == "unreachable" else "refused" if chosen == "refused" else "ok"

    def archive_write(
        self, what: str, *, partial: bool = False
    ) -> Literal["ok", "unreachable", "lost", "partial", "refused"]:
        """A write to the Archiwum as ``box_write``, or refused; an upload (``partial``) may also break off in the
        middle of the file, which leaves it on GitHub not whole (``state`` ``starter``), counted as a network failure."""

        offered: tuple[Choice, ...] = ("ok", "unreachable", "lost", "refused", "kill")
        chosen = self._pick((*offered, "partial") if partial and self.left["unreachable"] else offered, what)
        if chosen == "partial":
            self.left["unreachable"] -= 1
            self.faults.append(("partial", what.split("(")[0]))
        self._killed(chosen, what)
        if chosen == "unreachable":
            self.say(f"{what}: brak sieci (Unreachable), Skrzynka nic nie dostaje")
        elif chosen == "refused":
            self.say(f"{what}: odmowa (Refused, Token bez uprawnienia do treści repozytorium)")
        else:
            self.say(what)
        if chosen in ("ok", "unreachable", "lost", "partial", "refused"):
            return chosen
        raise AssertionError(chosen)

    def disk(self, what: str) -> bool:
        chosen = self._pick(("ok", "oserror", "kill"), what)
        self._killed(chosen, what)
        if chosen == "oserror":
            self.say(f"{what}: OSError")
        return chosen == "oserror"

    def read(self, what: str) -> bool:
        """A read of a queue file: it works or raises ``OSError``. A kill here is the kill at the step before it."""

        if not self.left["unreadable"]:
            return False
        chosen = self._pick(("ok", "unreadable"), what)
        if chosen == "unreadable":
            self.say(f"{what}: OSError (plik trzyma OneDrive albo antywirus)")
        return chosen == "unreadable"

    def between_passes(self, woken: bool) -> Literal["next", "restart", "stuck"]:
        """When nothing asked for a pass and files are left: the ``RETRY_S`` wake the code armed fires, Centrum
        restarts, or, without an armed wake, the queue may simply stay as it is until the next start."""

        offered: list[Choice] = ["next" if woken else "stuck"]
        if self.left["kill"]:
            offered.append("restart")
        chosen = offered[0] if len(offered) == 1 else self._pick(offered, "przejście")
        if chosen == "restart":
            self.left["kill"] -= 1
            self.faults.append(("restart", "przejście"))
            return "restart"
        return "next" if chosen == "next" else "stuck"


def _files(release: _Release) -> str:
    """The files of a Release in a trace: the version from each label, and whether its upload ended."""

    return ", ".join(f"{_version_of(a.label)}{'' if a.uploaded else ' (niepełny)'}" for a in release.assets) or "bez plików"


_LABEL_VERSION = re.compile(r"\(wersja (\S+)\)$")


def _version_of(label: str) -> str:
    found = _LABEL_VERSION.search(label)
    return f"wersja {found.group(1)}" if found else label


def _part_name(text: str) -> str:
    return next(
        (line for line in text.splitlines() if line.startswith(("część ", "Ta część"))), "treść"
    )


@dataclass(frozen=True)
class Scope:
    description: str
    posts: tuple[Post, ...]
    issues: tuple[tuple[Label, str, str], ...]
    bounds: Bounds


LOGS = PeriodThread(
    "logi-uruchomienia",
    "- Logi Uruchomienia okresu: 08_14_09_2026",
    "reuse",
    "Logi Uruchomienia 08_14_09_2026",
)
REPORT = ReportIssue(
    fingerprint="4f1c2d", title="Zgłoszenie: Przebieg rozliczeń zatrzymany"
)
THREAD = PeriodThread(
    "kontrola-ilosci",
    "- Kontrola ilości okresu: 08_14_09_2026",
    "new_issue",
    "Kontrola ilości 08_14_09_2026",
)
NOTE = NewIssue("uwaga-taty", "Uwaga taty: brakuje zlecenia")
KNOWN = KnownIssue("uwaga-taty", 1)


def _post(
    target: ReportIssue | PeriodThread | NewIssue | KnownIssue,
    run_id: str,
    count: int,
    *,
    header: str | None = None,
    version: str = "",
) -> Post:
    """Wysyłka ``run_id`` w ``count`` częściach; ``version`` odróżnia treść nowszej wersji tej samej wysyłki."""

    first = f"{REPORT.line}\n" if isinstance(target, ReportIssue) else ""
    parts = tuple(
        f"{first if number == 1 else ''}część {number}/{count} wysyłki {run_id}{version}"
        for number in range(1, count + 1)
    )
    return Post(target, "08_14_09_2026", run_id, header, parts)


BOUNDS = Bounds(unreachable=2, lost=1, disk=1, kills=1)
TAG = "logi-08_14_09_2026"


def _archived(run_id: str, version: str) -> Post:
    """Logi Uruchomienia ``run_id`` w jednym komentarzu z plikiem do Archiwum okresu (``logi_post``)."""

    archive = ArchiveFile(TAG, "Logi Uruchomień", "Archiwum", f"{run_id}.json", f"Logi {run_id}{version}\n")
    return Post(LOGS, "08_14_09_2026", run_id, "Logi okresu", (f"część 1/1 wysyłki {run_id}{version}",), archive)


# Logi z plikiem do Archiwum i ich Diagnoza: nowsza wersja tej samej wysyłki podmienia plik i zmienia komentarz.
ARCHIVED_DIAGNOSED = (_archived("uruchomienie", " przed Diagnozą"), _archived("uruchomienie", " po Diagnozie"))
# Logi Uruchomienia w dwóch częściach i ich Diagnoza w jednej: nowsza wersja tej samej wysyłki (ten sam run_id).
DIAGNOSED = (
    _post(LOGS, "uruchomienie", 2, header="Logi okresu"),
    _post(LOGS, "uruchomienie", 1, header="Logi okresu", version=" po Diagnozie"),
)
SCOPES = {
    "zgloszenie": Scope(
        "Zgłoszenie (ReportIssue) w jednej części, jak każde (Post odrzuca więcej).",
        (_post(REPORT, "zgl", 1),),
        (),
        BOUNDS,
    ),
    "zgloszenie-wrocilo": Scope(
        "Zgłoszenie (ReportIssue), którego odcisk ma już otwarte Zgłoszenie: jedyna część idzie do niego komentarzem.",
        (_post(REPORT, "zgl-wrocilo", 1),),
        (("zgloszenie", REPORT.title, f"{REPORT.line}\nwcześniejsze Zgłoszenie"),),
        BOUNDS,
    ),
    "watek-okresu": Scope(
        "Dwie Kontrole ilości do jednego issue okresu (PeriodThread), w dwóch i jednej części.",
        (_post(THREAD, "kontrola-a", 2), _post(THREAD, "kontrola-b", 1)),
        (),
        BOUNDS,
    ),
    "nowe-issue": Scope(
        "Uwaga taty (NewIssue) w dwóch częściach.",
        (_post(NOTE, "uwaga", 2),),
        (),
        BOUNDS,
    ),
    "znane-issue": Scope(
        "Komentarz do istniejącego issue Uwagi taty (KnownIssue) w dwóch częściach.",
        (_post(KNOWN, "logi", 2),),
        (("uwaga-taty", "Uwaga taty", "treść Uwagi"),),
        BOUNDS,
    ),
    "diagnoza": Scope(
        "Logi Uruchomienia (PeriodThread z nagłówkiem) w dwóch częściach, potem ich Diagnoza w jednej: nowsza wersja "
        "tej samej wysyłki zmienia część 1 i opróżnia część 2.",
        DIAGNOSED,
        (),
        # Z BOUNDS też przechodzi (51 s na Macu Maksa 2026-11-04 wobec 9 s), a w CI byłby najdłuższą jednostką.
        Bounds(unreachable=1, lost=1, disk=1, kills=1),
    ),
    "archiwum": Scope(
        "Logi Uruchomienia w jednym komentarzu z plikiem do Archiwum okresu (Release z tagiem okresu): plik idzie przed "
        "komentarzem, a odmowa Archiwum zostawia plik w kolejce i komentarz z dopiskiem.",
        (_archived("uruchomienie", ""),),
        (),
        Bounds(unreachable=1, lost=1, disk=1, kills=1, refusals=1),
    ),
    "archiwum-diagnoza": Scope(
        "Te Logi i ich Diagnoza, nowsza wersja tej samej wysyłki: podmienia plik w Archiwum (usunięcie, potem nowy) i "
        "zmienia komentarz; plik starszej wersji raz nieczytelny dochodzi po nowszej i niczego nie zmienia.",
        ARCHIVED_DIAGNOSED,
        (),
        Bounds(unreachable=0, lost=1, disk=0, kills=1, reads=1, refusals=1),
    ),
    "diagnoza-odczyt": Scope(
        "Te same Logi i Diagnoza, a pliku Logów raz nie da się odczytać: Diagnoza idzie przed nimi, a Logi, które "
        "dochodzą po niej, niczego w Skrzynce nie zmieniają ani nie dopisują.",
        DIAGNOSED,
        (),
        # Z błędem dysku też przechodzi (17 860 harmonogramów, 39 s na Macu Maksa 2026-11-04 wobec 9 s), a w CI byłby
        # najdłuższą jednostką; błąd dysku przy dwóch wersjach sprawdza zakres diagnoza.
        Bounds(unreachable=1, lost=1, disk=0, kills=1, reads=1),
    ),
}

Faults = Sequence[tuple[str, str]]
"""What went wrong in a schedule, in order: (``unreachable``/``lost``/``oserror``/``unreadable``/``kill``/``restart``, the step)."""


@dataclass(frozen=True)
class Excuse:
    """A break of ``rule`` in ``scope`` that is reported but does not fail the check, only after the faults that
    ``because`` names: the same rule broken in a schedule without them, or without any fault, is a new violation."""

    scope: str
    rule: str
    text: str
    because: Callable[[Faults], bool]


# Each must break in its scope after its faults, or the check ends with ZNALEZISKO ZNIKNĘŁO.
KNOWN_FINDINGS: tuple[Excuse, ...] = ()
ACCEPTED_RISKS: tuple[Excuse, ...] = ()
Kind = Literal["known", "accepted", "new"]


def _kind(scope: str, rule: str, faults: Faults) -> Kind:
    if any(
        e.scope == scope and e.rule == rule and e.because(faults)
        for e in KNOWN_FINDINGS
    ):
        return "known"
    if any(
        e.scope == scope and e.rule == rule and e.because(faults)
        for e in ACCEPTED_RISKS
    ):
        return "accepted"
    return "new"


class _Log(CentrumLog):
    def __init__(self, path: Path, failures: list[str]) -> None:
        super().__init__(path)
        self._failures = failures

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        super().unexpected_failure(failure, where=where)
        if where == DRAIN_FAILURE:
            self._failures.append(f"{type(failure).__name__}: {failure}")


class _Clock:
    """Time stands still; ``after`` arms the wake that the checker fires between passes, as the timer would."""

    def __init__(self) -> None:
        self.armed: list[Callable[[], None]] = []

    def __call__(self) -> float:
        return 0.0

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        self.armed.append(wake)


class _QueueThread:
    """``threading.Thread`` inside ``outbox.py``: ``start`` hands the target to the checker, which runs it later."""

    def __init__(
        self, started: list[Callable[[], None]], target: Callable[[], None]
    ) -> None:
        self._started = started
        self._target = target

    def start(self) -> None:
        self._started.append(self._target)


@contextmanager
def _queue_threads(started: list[Callable[[], None]]) -> Iterator[None]:
    """Only the start of the queue thread is replaced; ``Lock`` and ``Condition`` stay real."""

    names = vars(outbox_module)
    real = names["threading"]
    names["threading"] = SimpleNamespace(
        Thread=lambda *, target, name, daemon: _QueueThread(started, target),
        Lock=real.Lock,
        Condition=real.Condition,
    )
    try:
        yield
    finally:
        names["threading"] = real


@contextmanager
def _intercepted(scheduler: Scheduler, queue: Path, versions: dict[str, str]) -> Iterator[None]:
    """The read of a queue file, the marker write and the removal of queue files as steps of ``scheduler``.

    The read is ``_queued``, which lets the ``OSError`` of ``read_text`` through to ``_send_all``; the checker raises it
    before the real ``_queued`` runs.
    """

    names = vars(outbox_module)
    queued = names["_queued"]
    replace = names["replace_atomically"]
    unlink = pathlib.Path.unlink

    def read(path: Path) -> object:
        if scheduler.read(f"odczyt pliku kolejki wysyłki {versions[outbox_module._version(path)]}"):
            raise PermissionError("plik zablokowany")
        return queued(path)

    def marker(path: Path, text: str) -> None:
        if scheduler.disk("zapis znacznika dostarczenia"):
            raise PermissionError("plik zablokowany")
        replace(path, text)
        scheduler.say("znacznik dostarczenia zapisany")

    def removal(path: Path, missing_ok: bool = False) -> None:
        if path.parent == queue and path.suffix == ".json":
            if scheduler.disk("usunięcie pliku kolejki"):
                raise PermissionError("plik zablokowany")
            scheduler.say("plik kolejki usunięty")
        unlink(path, missing_ok=missing_ok)

    names["_queued"] = read
    names["replace_atomically"] = marker
    pathlib.Path.unlink = removal  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        names["_queued"] = queued
        names["replace_atomically"] = replace
        pathlib.Path.unlink = unlink  # type: ignore[method-assign]


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    trace: tuple[str, ...]
    kind: Kind


def _marked(path: Path) -> bool:
    """The file has its delivery marker: every part and its file in the Archiwum delivered (``_queue_text``), it only
    waits to be removed."""

    entry = json.loads(path.read_text(encoding="utf-8"))
    return bool(entry.get("delivered_parts") == len(entry["parts"]) and (entry["archive"] is None or entry["archived"]))


ENDINGS = {
    "pusta": "kolejka pusta",
    "limit": "wyczerpany limit przejść, choć kod wciąż uruchamia kolejkę",
    "nic": "nic nie rusza kolejki do następnego startu Centrum",
    "bez-watku": "budzik albo start nie uruchamia wątku kolejki",
}


def _check(
    scope: Scope, box: MemoryBox, queue: Path, failures: list[str], ended: str
) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    newest = {(post.target.label, post.run_id): post for post in scope.posts}
    for post in scope.posts:
        target = post.target
        if isinstance(target, KnownIssue):
            mine = [box.issues[target.number]]
        elif isinstance(target, NewIssue):
            mine = [
                issue
                for issue in box.issues.values()
                if issue.label == target.label and issue.title == target.title
            ]
        else:
            mine = [
                issue
                for issue in box.issues.values()
                if issue.label == target.label
                and target.line in issue.body.splitlines()
            ]
        texts = [text for issue in mine for text in (issue.body, *issue.comments)]
        times = {
            f"{number}/{len(post.parts)}": sum(part in text for text in texts)
            for number, part in enumerate(post.parts, 1)
        }
        if newest[post.target.label, post.run_id] is not post:
            left = [part for part, count in times.items() if count]
            if left:
                broken.append(
                    (
                        "DOKLADNIE_RAZ",
                        f"w Skrzynce zostaje część {', '.join(left)} starszej wersji wysyłki {post.run_id}",
                    )
                )
            continue
        wrong = [f"{part} ({count} razy)" for part, count in times.items() if count != 1]
        if wrong:
            broken.append(
                (
                    "DOKLADNIE_RAZ",
                    f"w Skrzynce jest część {', '.join(wrong)} wysyłki {post.run_id}",
                )
            )
        if post.archive is not None:
            broken.extend(_archive_broken(post, box))
        if (
            not isinstance(target, KnownIssue)
            and len([issue for issue in mine if not issue.closed]) > 1
        ):
            broken.append(
                (
                    "JEDNO_ISSUE",
                    f"wysyłka {post.run_id} ma {len(mine)} issue: {sorted(n for n, i in box.issues.items() if i in mine)}",
                )
            )
    waiting = [path.name for path in queue.glob("*.json") if not _marked(path)]
    if waiting:
        broken.append(
            (
                "KOLEJKA_PUSTA",
                f"w kolejce czeka {len(waiting)} plik(ów) bez znacznika dostarczenia: {ENDINGS[ended]}",
            )
        )
    if failures:
        broken.append(
            ("BEZ_WYJATKU", f"przejście kolejki kończy się wyjątkiem: {failures[0]}")
        )
    return list(dict.fromkeys(broken))


def _archive_broken(post: Post, box: MemoryBox) -> list[tuple[str, str]]:
    """DOKLADNIE_RAZ in the Archiwum: one whole file of the name with the newest text, no version uploaded twice."""

    archive = post.archive
    assert archive is not None
    release = box.releases.get(archive.tag)
    files = [asset for asset in (release.assets if release else []) if asset.name == archive.packed_name]
    texts = [gzip.decompress(asset.data).decode("utf-8") if asset.uploaded else "(niepełny)" for asset in files]
    broken = []
    if texts != [archive.text]:
        broken.append(("DOKLADNIE_RAZ", f"Archiwum ma pliki {archive.packed_name}: {texts or 'brak'}"))
    if archive.packed_name in box.twice:
        broken.append(("DOKLADNIE_RAZ", f"kolejka usuwa cały plik {archive.packed_name} i wysyła go drugi raz"))
    return broken


_VERSION = re.compile(r"wersja (\S+) -->")
_ASSET_VERSION = re.compile(r"\(wersja (\S+)\)$")


def _state(
    box: MemoryBox,
    queue: Path,
    outbox: Outbox,
    scheduler: Scheduler,
    passes: int,
    failures: list[str],
    clock: _Clock,
    threads: int,
    versions: dict[str, str],
) -> object:
    """What decides every future of a pass boundary and how its breaks are judged: the Skrzynka, the queue files,
    the files ``_remove`` could not delete, the faults so far and those left, the passes left and the exceptions.
    The faults so far count as a set plus the verdict of each ``Excuse`` on them: an excuse that holds keeps holding,
    and the only order it reads (a failed marker before a kill at the removal) is in the set as the failed marker.

    The version of a wysyłka in the Skrzynka's texts (``outbox._version``, from the moment the checker posted it) counts
    as its place among the scope's wysyłki (``versions``): the code only compares versions of one wysyłka.

    Also whether a ``RETRY_S`` wake is armed, and ``_stopped_on`` and ``_retry_armed``, which decide in ``_drain``
    whether the next one is, and ``_draining``, ``_again`` and the queue threads started and not run yet, which decide
    whether ``send_in_background`` starts a pass. The Archiwum counts as its files with the versions in their labels and
    whether each upload ended, plus the files the queue sent twice (``MemoryBox.twice``), which the rule reads; a pair of
    ``remove`` and ``upload`` never spans a pass boundary.
    ``_archive_refused`` is in the state although ``_send_all`` sets it anew in every pass, as the wake it arms is.
    Left out on purpose, because they do not change what is sent: ``_first_comments``
    (``delivered``, ``wait_delivered``), ``_rejected`` (no ``Rejected`` here), ``_read_failed`` and ``_unreadable``
    (``_send_all`` sets the first anew in every pass, and whether it armed a wake is in the state; the second only spares
    the log a line) and the key verdict of ``KeyedBox`` (the key is always accepted, and ``Unreachable`` does not change
    it).
    """

    files = {
        path.name: path.read_text(encoding="utf-8") for path in queue.glob("*.json")
    }
    def same(text: str) -> str:
        return _VERSION.sub(lambda found: f"wersja {versions.get(found.group(1), '?')} -->", text)

    def same_label(label: str) -> str:
        return _ASSET_VERSION.sub(lambda found: f"(wersja {versions.get(found.group(1), '?')})", label)

    return (
        tuple(
            (n, i.label, i.title, same(i.body), tuple(map(same, i.comments)), i.closed)
            for n, i in sorted(box.issues.items())
        ),
        tuple(
            (tag, tuple((a.name, same_label(a.label), a.data, a.uploaded) for a in release.assets))
            for tag, release in sorted(box.releases.items())
        ),
        tuple(box.twice),
        tuple(sorted(files.values())),
        tuple(sorted(files[name] for name in outbox._undeleted if name in files)),
        tuple(sorted(scheduler.left.items())),
        frozenset(scheduler.faults),
        tuple(
            excuse.because(scheduler.faults)
            for excuse in (*KNOWN_FINDINGS, *ACCEPTED_RISKS)
        ),
        passes,
        tuple(failures),
        bool(clock.armed),
        outbox._stopped_on,
        outbox._archive_refused,
        outbox._retry_armed,
        outbox._draining,
        outbox._again,
        threads,
    )


def execute(
    name: str, prefix: Sequence[int], work: Path, visited: set[object]
) -> tuple[Scheduler, list[Violation]]:
    """One schedule: write the wysyłki, then passes and restarts as ``prefix`` picks until failures run out.

    A schedule that reaches a pass boundary already explored, past the steps it replays from ``prefix``, stops
    there: the code is deterministic, so that state has the same futures, and the schedules that branch after it
    from the first visit check them.
    """

    scope = SCOPES[name]
    shutil.rmtree(work, ignore_errors=True)
    queue = work / "config" / "zgloszenia" / "kolejka"
    scheduler = Scheduler(prefix, scope.bounds)
    box = MemoryBox(scheduler)
    for label, title, body in scope.issues:
        box.issues[len(box.issues) + 1] = _Issue(label, title, body)
    failures: list[str] = []
    clock = _Clock()
    started_threads: list[
        Callable[[], None]
    ] = []  # targets of threads the code started, not run yet

    def started() -> Outbox:
        clock.armed.clear()  # a timer and a thread die with their process
        started_threads.clear()
        return Outbox(
            queue,
            KeyedBox(box, lambda: KEY, clock=clock),
            _Log(work / "centrum.log", failures),
            clock=clock,
            listener=_Unchanged(),
        )

    with _queue_threads(started_threads):
        outbox = started()
        for post in scope.posts:
            assert outbox.post(post), "zapis wysyłki do kolejki"
        scheduler.say("wysyłki czekają w kolejce (Outbox.post)")
        versions = {
            outbox_module._version(path): str(place)
            for place, path in enumerate(sorted(queue.glob("*.json")), start=1)
        }
        bounds = scope.bounds
        passes = (
            bounds.unreachable + bounds.lost + bounds.disk + bounds.kills + bounds.reads + EXTRA_PASSES
        )
        ended = "pusta"
        with _intercepted(scheduler, queue, versions):
            while any(queue.glob("*.json")):
                if not passes:
                    ended = "limit"
                    break
                if not started_threads:
                    then = scheduler.between_passes(bool(clock.armed))
                    if then == "restart":
                        scheduler.say("Centrum startuje znów (Outbox.resume)")
                        outbox = started()
                        outbox.resume()
                    elif then == "next":
                        scheduler.say("mija RETRY_S: budzik woła Outbox._woken")
                        clock.armed.pop(0)()
                    else:
                        scheduler.say(
                            "nic nie rusza kolejki do następnego startu Centrum"
                        )
                        ended = "nic"
                        break
                    if not started_threads:
                        scheduler.say(
                            "kod nie uruchamia wątku kolejki (send_in_background)"
                        )
                        ended = "bez-watku"
                        break
                state = _state(
                    box,
                    queue,
                    outbox,
                    scheduler,
                    passes,
                    failures,
                    clock,
                    len(started_threads),
                    versions,
                )
                if state in visited and len(scheduler.taken) >= len(prefix):
                    return scheduler, []
                visited.add(state)
                passes -= 1
                scheduler.say(
                    "przejście kolejki (wątek skrzynka-kolejka, Outbox._drain)"
                )
                try:
                    started_threads.pop(0)()
                except Crash:
                    outbox = started()
                    scheduler.say("Centrum startuje znów (Outbox.resume)")
                    outbox.resume()
    trace = tuple(scheduler.trace)
    faults = tuple(scheduler.faults)
    return scheduler, [
        Violation(rule, detail, trace, _kind(name, rule, faults))
        for rule, detail in _check(scope, box, queue, failures, ended)
    ]


def next_prefix(scheduler: Scheduler) -> list[int] | None:
    for position in range(len(scheduler.taken) - 1, -1, -1):
        if scheduler.taken[position] + 1 < scheduler.options[position]:
            return [*scheduler.taken[:position], scheduler.taken[position] + 1]
    return None


@dataclass
class ScopeReport:
    name: str
    schedules: int = 0
    shortest: dict[tuple[str, Kind], Violation] = field(default_factory=dict)


def explore(name: str) -> ScopeReport:
    report = ScopeReport(name)
    with tempfile.TemporaryDirectory(prefix="kolejka-skrzynki-") as directory:
        prefix: list[int] | None = []
        visited: set[object] = set()
        while prefix is not None:
            scheduler, violations = execute(
                name, prefix, Path(directory) / "praca", visited
            )
            report.schedules += 1
            for violation in violations:
                key = (violation.rule, violation.kind)
                seen = report.shortest.get(key)
                if seen is None or len(violation.trace) < len(seen.trace):
                    report.shortest[key] = violation
            prefix = next_prefix(scheduler)
    return report


@dataclass(frozen=True)
class Outcome:
    lines: list[str]
    exit_code: int


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines: list[str] = []
    new = known = accepted = gone = 0
    for report in reports:
        lines.append(
            f"== {report.name}: {SCOPES[report.name].description} Harmonogramy: {report.schedules}."
        )
        for (rule, kind), violation in sorted(report.shortest.items()):
            excuses = {"known": KNOWN_FINDINGS, "accepted": ACCEPTED_RISKS}.get(
                kind, ()
            )
            text = next(
                (e.text for e in excuses if e.scope == report.name and e.rule == rule),
                "",
            )
            if kind == "known" and not strict:
                known += 1
                lines.append(f"   znane ustalenie {rule}: {text}")
            elif kind == "accepted" and not strict:
                accepted += 1
                lines.append(f"   zaakceptowane ryzyko {rule}: {text}")
            else:
                new += 1
                lines.append(f"   NOWE NARUSZENIE {rule}")
            lines.append(f"   {violation.detail}")
            lines.extend(
                f"   {number}. {step}"
                for number, step in enumerate(violation.trace, start=1)
            )
        expected: list[tuple[Excuse, Kind]] = [
            *((e, "known") for e in KNOWN_FINDINGS),
            *((e, "accepted") for e in ACCEPTED_RISKS),
        ]
        for excuse, expected_kind in expected:
            if (
                excuse.scope == report.name
                and (excuse.rule, expected_kind) not in report.shortest
            ):
                gone += 1
                lines.append(
                    f"   ZNALEZISKO ZNIKNĘŁO {excuse.rule}: usuń je z KNOWN_FINDINGS albo ACCEPTED_RISKS i z SKILL.md"
                )
    lines.append("")
    if new or gone:
        lines.append(
            f"KOLEJKA: NOWE NARUSZENIE ({new})"
            if new
            else f"KOLEJKA: ZNALEZISKO ZNIKNĘŁO ({gone})"
        )
        return Outcome(lines, 1)
    counts = [
        f"ZNANE USTALENIA: {known}" if known else "",
        f"ZAAKCEPTOWANE RYZYKA: {accepted}" if accepted else "",
    ]
    lines.append(", ".join(["KOLEJKA OK", *filter(None, counts)]))
    return Outcome(lines, 0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exhaustive check that the Kolejka Skrzynki Zgłoszeń delivers every part."
    )
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        action="append",
        help="one scope; default: all",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="report known findings and accepted risks as violations too",
    )
    arguments = parser.parse_args(argv)
    outcome = summarize(
        [explore(name) for name in (arguments.scope or SCOPES)], strict=arguments.strict
    )
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
