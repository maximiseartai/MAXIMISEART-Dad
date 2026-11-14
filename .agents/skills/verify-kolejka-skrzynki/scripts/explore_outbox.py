"""Exhaustively check that the Kolejka Skrzynki Zgłoszeń delivers every part of every wysyłka exactly once.

The checker runs the real ``outbox.Outbox`` (its ``_drain`` and ``_send_all``) and the real ``KeyedBox`` against an
in-memory Skrzynka Zgłoszeń, on a real queue folder in a temporary directory. Each call the code makes to the
Skrzynka, the write of the delivery marker and the removal of a queue file is one indivisible step. Before every step
the checker may let it succeed, let the network fail before the Skrzynka sees it (``Unreachable``), let the Skrzynka
accept it and lose the answer (``Unreachable`` after the effect), fail the file call with ``OSError``, or kill the
process. Between two passes of the queue it may also restart Centrum. It tries every such schedule within the bounds
of a scope, re-running the code from scratch once per schedule. A pass runs only when the real ``send_in_background``
starts the queue thread, as ``Outbox.post``, ``Outbox.resume`` at a start, or the ``RETRY_S`` wake (``_woken``) that
``_drain`` armed ask it to. When no thread starts, the schedule may end there. A scope's later wysyłki (a newer version
of a wysyłka, as a Diagnoza or the next progress of a Wycena w efenix) arrive through ``Outbox.post`` between two
passes, at a moment the schedule picks. Then it checks:

- DOKLADNIE_RAZ: every part of the newest version of every wysyłka is in the Skrzynka exactly once, in an issue of
  its target, and no text of an older version of it is left there (ADR 0015 after #840: „Wysyłka jest dokładnie
  raz”); a part the newest version no longer has is ``_RETIRED``. A wysyłka with a file for the Archiwum okresu
  (#844) has exactly one whole file of its name in the Archiwum of its tag, with the text of the newest version, and
  its file never went twice: the queue never removed a whole file of its version or a newer one to upload it again.
  In a scope whose Archiwum refuses every time (a repository without a commit: GitHub answers 409 to every new
  Release), the file waits in the queue with the marker of its parts, and every part of every wysyłka still arrives: a
  refusal of the Archiwum stops only the file, not the wysyłki after it.
- JEDNO_ISSUE: one problem has one open Zgłoszenie and one period has one issue okresu; a wysyłka to a new issue
  (Uwaga taty) opens one issue.
- NAJNOWSZA_WERSJA: once a newer version of a wysyłka is in the queue, the Skrzynka gets no text of an older one: a
  pass removes the file of the older version unsent (``_superseded``, #846: without the network only the newest progress
  of a Wycena w efenix waits). Judged only in schedules in which no read of a queue file failed, because a pass that
  cannot read the newer file sends the older one, and the newer then changes its comment.
- KOLEJKA_PUSTA: no queue file without its delivery marker is left when the schedule ends; a delivered file whose
  removal failed may wait for the next start.
- BEZ_WYJATKU: no pass ends in an exception that ``_drain`` logs as ``nieoczekiwany-wyjatek``.

Nothing in ``outbox.py`` or ``keyed_box.py`` is replaced: ``Outbox`` gets the checker's queue files (``QueueDisk``) and
start of a pass (``start``), which hands ``_drain`` to the checker, which runs it when nothing else is left to do, so the
real ``send_in_background`` decides whether a pass starts at all. The Skrzynka behind ``KeyedBox`` is
the in-memory ``MemoryBox`` (GitHub's issues and comments, and its Releases with their files for the Archiwum okresu),
the clock moves only when the ``RETRY_S`` wake fires and keeps the wakes ``after`` arms, and the key is always there and
accepted. In a scope with ``list_lag`` GitHub's issue list does not show an issue until ``LIST_LAG_S`` after it was
opened, the longest lag ``KeyedBox`` allows for (#879), so only the wake lets it catch up: a restart of Centrum takes no
time. ``KeyedBox`` keeps the moments of its openings in the file ``OPENING_FILE``, which a restart keeps, as Dad's
``config`` folder does; the checker keeps that file in memory (``_NotesInMemory``), because it never fails it. Only a
step of the
Archiwum may be refused (a key without the permission to write the repository's contents, GitHub's 403, or a repository
without a commit, its 409 to a new Release). The checker does not decide what such an answer means: it hands GitHub's
answer to the real ``report_box.GitHubReportBox`` (``_github``) and gives the queue its outcome.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.github import HttpResponse
from rozliczenia.centrum.keyed_box import LIST_LAG_S, OPENING_FILE, KeyedBox, NotesFile
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import (
    DRAIN,
    LOCAL_QUEUE_DISK,
    RETRY_S,
    ArchiveFile,
    KnownIssue,
    NewIssue,
    Outbox,
    PeriodThread,
    OpenIssue,
    Post,
    QueueDisk,
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
    GitHubReportBox,
    Issue,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    Rejected,
    Removed,
    RemoveOutcome,
    SendOutcome,
    Sent,
    Unreachable,
    UploadOutcome,
)
from rozliczenia.centrum.reports import report_target
from eksplorator import Choices, Excuse, Kind, Shape, excuse_line, excused, gone_lines, schedules, verdict
from atrapy.sluchacz_kolejki import QueueListener
from rozliczenia.centrum.case_delivery import queue_directory
from rozliczenia.tool_files import config_dir
from rozliczenia.client_data import logs_text, tool

KEY = "github_pat_SYNTETYCZNY_KLUCZ"
# GitHub's answers to a step of the Archiwum it refuses until Maks changes something: a key without the permission to
# write the repository's contents, and a new Release in a repository without a commit (the Skrzynka's on 2026-11-04).
NO_PERMISSION = HttpResponse(403, b'{"message": "Resource not accessible by personal access token"}')
EMPTY_REPOSITORY = HttpResponse(409, b'{"message": "Git Repository is empty."}')


def _github(answer: HttpResponse) -> GitHubReportBox:
    """The real GitHub adapter given one answer of GitHub: the code, not the checker, decides what it is to the queue."""

    return GitHubReportBox(transport=lambda request: answer)


# Passes beyond one per failure until the queue must be empty; a pass without a failure delivers or removes each file.
EXTRA_PASSES = 3
# Początek dopisku części, gdy Archiwum nie przyjęło pliku (outbox._waiting_note). Celowa kopia (docs/agents/skille.md,
# „Co wyrocznia bierze z src”): dopisek czyta Maks w Skrzynce, więc zmiana jego tekstu w src ma wywrócić sprawdzenie.
WAITING = "czeka w Kolejce wysyłki na komputerze taty"


class Crash(BaseException):
    """The process dies at this step (Dad closes Centrum, the computer switches off)."""


class _NotesInMemory:
    """``OPENING_FILE`` of one schedule in memory: the ``path`` and ``replace`` of ``NotesFile`` that ``KeyedBox`` gets.

    ``KeyedBox.of_work`` hands ``KeyedBox`` the file through ``NotesFile`` with ``replace_atomically``; the checker hands it
    this object as both, so every Centrum of a schedule reads what the last one wrote, as from Dad's ``config``
    folder, and the file is missing (``FileNotFoundError``) until the first write. The checker never fails the read or
    the write of this file (SKILL.md), so the disk added nothing but time: since #897 the file took about 40% of a scope
    (#911), and on Windows CI ``archiwum-diagnoza`` ran past the 600 s limit of the mutation engine (``tools/lib/silnik_mutacji.py``).
    """

    def __init__(self) -> None:
        self._text: str | None = None

    def read_text(self, encoding: str) -> str:
        if self._text is None:
            raise FileNotFoundError(OPENING_FILE)
        return self._text

    def replace(self, path: object, text: str) -> None:
        self._text = text


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
    of one name in one Release are ``Rejected`` and change nothing. A refused step and a Release in a repository without a
    commit (``empty_repository``) get the outcome the real ``GitHubReportBox`` gives GitHub's answer (``_github``).

    ``twice`` names each file the queue sent twice: a whole file it removed and, as its very next call, uploaded again
    in the same version or an older one. ``_deliver_archive`` removes a file only to upload its own newer version right
    after, so the pair is one delivery; any other call, a failure or a restart in between ends the pair.

    With ``list_lag`` ``labelled_issues`` leaves out each issue opened less than ``LIST_LAG_S`` ago on ``clock``
    (``opened_at``), also one whose answer was lost, as GitHub's list does for a few seconds, and ``archive`` leaves out
    a Release opened so recently (``release_opened_at``), as GitHub's list of Releases does (#887). The list of a
    Release's files does not lag here: its lag was not measured.
    """

    def __init__(
        self, scheduler: Scheduler, clock: _Clock, *, empty_repository: bool = False, list_lag: bool = False
    ) -> None:
        self.issues: dict[int, _Issue] = {}
        self.opened_at: dict[int, float] = {}
        self.release_opened_at: dict[str, float] = {}
        self._clock = clock
        self._list_lag = list_lag
        self.releases: dict[str, _Release] = {}
        self.twice: list[str] = []
        self._scheduler = scheduler
        self._empty = empty_repository  # no commit: GitHub opens no Release (409), so the Archiwum stays without one
        self._comment_ids = 0
        self._ids = 0
        self._removed: _Asset | None = None  # whole file removed by the call just before, answered
        self.versions: dict[str, str] = {}  # the version in a mark → the place of its wysyłka (``execute``)


    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        self._removed = None
        chosen = self._scheduler.archive_read(f"archive({tag})")
        if chosen != "ok":
            return Unreachable() if chosen == "unreachable" else _github(NO_PERMISSION).archive(tag, key=key)
        found = self.releases.get(tag)
        lags = found is not None and self._list_lag and self._clock() - self.release_opened_at[tag] < LIST_LAG_S
        found = None if lags else found
        self._scheduler.say(
            f"Skrzynka zwraca Archiwum {tag}: {'brak' if found is None else _files(found)}"
            + (" (lista Release'ów jeszcze go nie pokazuje)" if lags else "")
        )
        if found is None:
            return None
        return Archive(found.id, tuple(Asset(a.id, a.name, a.label, a.uploaded) for a in found.assets))

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        self._removed = None
        chosen = self._scheduler.archive_write(f"open_archive({tag})")
        if chosen in ("unreachable", "partial"):
            return Unreachable()
        if chosen == "refused":
            return _github(NO_PERMISSION).open_archive(tag, title, description, key=key)
        if self._empty:
            self._scheduler.say(
                f"Skrzynka nie zakłada Archiwum {tag}: repozytorium bez commitu (409 „Git Repository is empty.”)"
                + (", odpowiedź ginie (Unreachable)" if chosen == "lost" else "")
            )
            return Unreachable() if chosen == "lost" else _github(EMPTY_REPOSITORY).open_archive(tag, title, description, key=key)
        if tag in self.releases:
            self._scheduler.say(f"Skrzynka odrzuca drugie Archiwum {tag} (422)")
            return Rejected()
        self.releases[tag] = _Release(self._next_id())
        self.release_opened_at[tag] = self._clock()
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
            return _github(NO_PERMISSION).upload(archive_id, name, label, data, key=key)
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
            return _github(NO_PERMISSION).remove(asset_id, key=key)
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
        self._removed = None
        what = f"open_issue({label}, {_part_name(body)})"
        failure = self._scheduler.box_write(what)
        if failure == "unreachable":
            return Unreachable()
        number = len(self.issues) + 1
        self.issues[number] = _Issue(label, title, body)
        self._scheduler.written(body, self.versions)
        self.opened_at[number] = self._clock()
        self._scheduler.say(
            f"Skrzynka zakłada issue #{number}"
            + (", odpowiedź ginie (Unreachable)" if failure else "")
        )
        return Unreachable() if failure else Sent(number)

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        self._removed = None
        failure = self._scheduler.box_write(f"comment(#{number}, {_part_name(body)})")
        if failure == "unreachable":
            return Unreachable()
        self._comment_ids += 1
        self.issues[number].comments.append(body)
        self._scheduler.written(body, self.versions)
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
        self._removed = None
        number, issue = next(
            (number, issue) for number, issue in self.issues.items() if comment_id in issue.comment_ids
        )
        failure = self._scheduler.box_write(f"edit_comment(#{number}, {_part_name(body)})")
        if failure == "unreachable":
            return Unreachable()
        issue.comments[issue.comment_ids.index(comment_id)] = body
        self._scheduler.written(body, self.versions)
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
        self._removed = None
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
        self._removed = None
        if self._scheduler.box_read(f"labelled_issues({label})"):
            return Unreachable()
        found = tuple(
            Issue(
                number, issue.body, Closure("completed", None) if issue.closed else None
            )
            for number, issue in self.issues.items()
            if issue.label == label and (include_closed or not issue.closed) and number not in self.unlisted()
        )
        self._scheduler.say(
            f"Skrzynka zwraca issue {label}: {[issue.number for issue in found] or 'brak'}"
            + (f" (lista jeszcze nie pokazuje {sorted(self.unlisted())})" if self.unlisted() else "")
        )
        return found

    def unlisted_releases(self) -> set[str]:
        """Tagi Release'ów, których lista Release'ów jeszcze nie pokazuje (``list_lag``)."""

        now = self._clock()
        return {tag for tag, at in self.release_opened_at.items() if self._list_lag and now - at < LIST_LAG_S}

    def unlisted(self) -> set[int]:
        """Issue, których lista issue jeszcze nie pokazuje (``list_lag``)."""

        now = self._clock()
        return {n for n, at in self.opened_at.items() if self._list_lag and now - at < LIST_LAG_S}


Choice = Literal[
    "ok", "unreachable", "lost", "partial", "refused", "oserror", "unreadable", "kill", "next", "restart", "stuck",
    "later", "now",
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

    def budget(self) -> dict[str, int]:
        """How many times each fault may be picked in a schedule (``eksplorator.Choices``)."""

        return {
            "unreachable": self.unreachable,
            "lost": self.lost,
            "oserror": self.disk,
            "unreadable": self.reads,
            "refused": self.refusals,
            "kill": self.kills,
        }


class Scheduler:
    """Plays out at each step the option that ``choices`` picks; ``faults`` are the picked faults, in order."""

    def __init__(self, choices: Choices) -> None:
        self.choices = choices
        self.left = choices.left
        self.faults = choices.faults
        self.trace: list[str] = []
        self.superseded: set[str] = set()  # places (``versions``) of wysyłki whose newer version is in the queue
        self.older_sent: list[str] = []  # box writes of a superseded place: NAJNOWSZA_WERSJA

    def say(self, line: str) -> None:
        self.trace.append(line)

    def _pick(self, offered: Sequence[Choice], what: str) -> Choice:
        return self.choices.pick(offered, what.split("(")[0])

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

    def arrival(self, what: str) -> bool:
        """Between two passes: the code posts the scope's next later wysyłka now, or not yet."""

        return self._pick(("later", "now"), what) == "now"

    def written(self, text: str, versions: dict[str, str]) -> None:
        """A box write of ``text``: its mark names a version whose newer version is already in the queue."""

        found = _VERSION.search(text)
        place = None if found is None else versions.get(found.group(1))
        if place in self.superseded:
            self.older_sent.append(f"{_part_name(text)} wersji {place}")

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
    empty_repository: bool = False
    """The Skrzynka's repository has no commit: GitHub refuses every new Release (409) for the whole schedule, so a file
    for the Archiwum never arrives and waits in the queue with the marker of its parts."""
    later: tuple[Post, ...] = ()
    """Wysyłki the code posts later, in order, each between two passes at a moment the schedule picks (before the first
    pass, too): a Diagnoza or the next progress of a Wycena w efenix, newer versions of a wysyłka in ``posts``."""
    list_lag: bool = False
    """GitHub's issue list shows a new issue only ``LIST_LAG_S`` after it was opened (``MemoryBox``)."""


LOGS = PeriodThread(
    "logi-uruchomienia",
    tool("- Logi Uruchomienia okresu: 08_14_09_2026"),
    "reuse",
    tool("Logi Uruchomienia 08_14_09_2026"),
)
REPORT = report_target("4f1c2d", tool("Zgłoszenie: Przebieg rozliczeń zatrzymany"))
THREAD = PeriodThread(
    "kontrola-ilosci",
    tool("- Kontrola ilości okresu: 08_14_09_2026"),
    "new_issue",
    tool("Kontrola ilości 08_14_09_2026"),
)
NOTE = NewIssue("uwaga-taty", tool("Uwaga taty: brakuje zlecenia"))
KNOWN = KnownIssue("uwaga-taty", 1)


def _post(
    target: OpenIssue | PeriodThread | NewIssue | KnownIssue,
    run_id: str,
    count: int,
    *,
    header: str | None = None,
    version: str = "",
) -> Post:
    """Wysyłka ``run_id`` w ``count`` częściach; ``version`` odróżnia treść nowszej wersji tej samej wysyłki."""

    first = f"{REPORT.line}\n" if isinstance(target, OpenIssue) else ""
    parts = tuple(
        tool(f"{first if number == 1 else ''}część {number}/{count} wysyłki {run_id}{version}")
        for number in range(1, count + 1)
    )
    return Post(target, "08_14_09_2026", run_id, None if header is None else tool(header), parts)


BOUNDS = Bounds(unreachable=2, lost=1, disk=1, kills=1)
TAG = "logi-08_14_09_2026"


def _archived(run_id: str, version: str) -> Post:
    """Logi Uruchomienia ``run_id`` w jednym komentarzu z plikiem do Archiwum okresu (``comment_versions.post_of``)."""

    archive = ArchiveFile(TAG, "Logi Uruchomień", "Archiwum", f"{run_id}.json", logs_text(f"Logi {run_id}{version}\n"))
    return Post(LOGS, "08_14_09_2026", run_id, tool("Logi okresu"), (tool(f"część 1/1 wysyłki {run_id}{version}"),), archive)


def _progress(run_id: str, version: str) -> Post:
    """Postęp Wyceny w efenix ``run_id`` (``comment_versions.ProgressVersion``): starsza wersja Logów, bez pliku."""

    return Post(LOGS, "08_14_09_2026", run_id, tool("Logi okresu"), (tool(f"część 1/1 wysyłki {run_id}{version}"),))


# Logi z plikiem do Archiwum i ich Diagnoza: nowsza wersja tej samej wysyłki podmienia plik i zmienia komentarz.
ARCHIVED_DIAGNOSED = (_archived("uruchomienie", " przed Diagnozą"), _archived("uruchomienie", " po Diagnozie"))
# Logi Uruchomienia w dwóch częściach i ich Diagnoza w jednej: nowsza wersja tej samej wysyłki (ten sam run_id).
DIAGNOSED = (
    _post(LOGS, "uruchomienie", 2, header="Logi okresu"),
    _post(LOGS, "uruchomienie", 1, header="Logi okresu", version=" po Diagnozie"),
)
SCOPES = {
    "zgloszenie": Scope(
        "Zgłoszenie (OpenIssue) w jednej części, jak każde (Post odrzuca więcej).",
        (_post(REPORT, "zgl", 1),),
        (),
        BOUNDS,
    ),
    "zgloszenie-wrocilo": Scope(
        "Zgłoszenie (OpenIssue), którego odcisk ma już otwarte Zgłoszenie: jedyna część idzie do niego komentarzem.",
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
        "Logi Uruchomienia (PeriodThread z nagłówkiem) w dwóch częściach, potem ich Diagnoza w jednej, w dowolnej chwili "
        "między przejściami: nowsza wersja tej samej wysyłki zmienia część 1 i opróżnia część 2, a gdy Logi jeszcze "
        "czekają, zastępuje ich plik w kolejce.",
        DIAGNOSED[:1],
        (),
        Bounds(unreachable=1, lost=1, disk=1, kills=1),
        later=DIAGNOSED[1:],
    ),
    "archiwum": Scope(
        "Logi Uruchomienia w jednym komentarzu z plikiem do Archiwum okresu (Release z tagiem okresu): plik idzie przed "
        "komentarzem, a odmowa Archiwum zostawia plik w kolejce i komentarz z dopiskiem.",
        (_archived("uruchomienie", ""),),
        (),
        Bounds(unreachable=1, lost=1, disk=1, kills=1, refusals=1),
    ),
    "archiwum-diagnoza": Scope(
        "Te Logi i ich Diagnoza, nowsza wersja tej samej wysyłki, w dowolnej chwili między przejściami: podmienia plik w "
        "Archiwum (usunięcie, potem nowy) i zmienia komentarz; plik starszej wersji raz nieczytelny dochodzi po nowszej i "
        "niczego nie zmienia.",
        ARCHIVED_DIAGNOSED[:1],
        (),
        Bounds(unreachable=0, lost=1, disk=0, kills=1, reads=1, refusals=1),
        later=ARCHIVED_DIAGNOSED[1:],
    ),
    "postep": Scope(
        "Postęp Wyceny w efenix (Logi tego Uruchomienia bez pliku do Archiwum), potem nowszy postęp i Logi z plikiem, "
        "każde w dowolnej chwili między przejściami: jeden komentarz Uruchomienia, który na końcu jest podsumowaniem, a "
        "nowsza wersja w kolejce zastępuje plik starszej.",
        (_progress("wycena", " postęp 1"),),
        (),
        # Ze zgubioną odpowiedzią też przechodzi (218 s na Macu Maksa 2026-11-05 wobec 30 s); zgubioną odpowiedź przy
        # dwóch wersjach sprawdzają zakresy diagnoza i archiwum-diagnoza.
        Bounds(unreachable=1, lost=0, disk=1, kills=1),
        later=(_progress("wycena", " postęp 2"), _archived("wycena", " podsumowanie")),
    ),
    "archiwum-puste-repo": Scope(
        "Logi Uruchomienia z plikiem do Archiwum okresu, a za nimi Zgłoszenie, w repozytorium Skrzynki bez commitu: GitHub "
        "odmawia każdego założenia Archiwum (409), więc plik Logów czeka w kolejce, a komentarz Logów i Zgłoszenie dochodzą.",
        (_archived("uruchomienie", ""), _post(REPORT, "zgl", 1)),
        (),
        Bounds(unreachable=1, lost=1, disk=1, kills=1),
        empty_repository=True,
    ),
    "watek-okresu-lista": Scope(
        "Te dwie Kontrole ilości, a lista issue pokazuje nowe issue dopiero po LIST_LAG_S (#879): druga Kontrola w tym "
        "samym przejściu, ponowienie po zgubionej odpowiedzi i start Centrum przychodzą, zanim lista je pokaże.",
        (_post(THREAD, "kontrola-a", 2), _post(THREAD, "kontrola-b", 1)),
        (),
        # Z BOUNDS też przechodzi (11 827 harmonogramów, 40 s na Macu Maksa 2026-11-05), a brak sieci przed skutkiem
        # sprawdza watek-okresu; opóźnienie listy spotyka zgubiona odpowiedź, błąd dysku i start Centrum.
        Bounds(unreachable=1, lost=1, disk=1, kills=1),
        list_lag=True,
    ),
    "nowe-issue-lista": Scope(
        "Uwaga taty w dwóch częściach, a lista issue pokazuje nowe issue dopiero po LIST_LAG_S (#879).",
        (_post(NOTE, "uwaga", 2),),
        (),
        BOUNDS,
        list_lag=True,
    ),
    "zgloszenie-lista": Scope(
        "Zgłoszenie w jednej części, a lista issue pokazuje nowe issue dopiero po LIST_LAG_S (#879).",
        (_post(REPORT, "zgl", 1),),
        (),
        BOUNDS,
        list_lag=True,
    ),
    "archiwum-lista": Scope(
        "Logi dwóch Uruchomień okresu, każde z plikiem do Archiwum okresu, a lista Release'ów pokazuje nowe Archiwum "
        "dopiero po LIST_LAG_S (#887): drugie Logi w tym samym przejściu i ponowienie po zgubionej odpowiedzi dokładają "
        "plik do Archiwum, które już jest, bez odmowy drugiego Archiwum i bez dopisku, że plik czeka.",
        (_archived("uruchomienie-a", ""), _archived("uruchomienie-b", "")),
        (),
        Bounds(unreachable=1, lost=1, disk=0, kills=1),
        list_lag=True,
    ),
    "diagnoza-odczyt": Scope(
        "Te same Logi i Diagnoza, a pliku Logów raz nie da się odczytać: Diagnoza idzie przed nimi, a Logi, które "
        "dochodzą po niej, niczego w Skrzynce nie zmieniają ani nie dopisują.",
        DIAGNOSED,
        (),
        # Błąd dysku przy dwóch wersjach sprawdza zakres diagnoza.
        Bounds(unreachable=1, lost=1, disk=0, kills=1, reads=1),
    ),
}

Faults = Sequence[tuple[str, str]]
"""What went wrong in a schedule, in order: (the kind, the step), the kind one of ``unreachable``, ``lost``, ``partial``,
``refused``, ``oserror``, ``unreadable``, ``kill`` and ``restart``."""


# An entry's shape judges the faults of its schedule (``Faults``); each names in ``after`` the scopes after which it
# always shows, or the check ends with ZNALEZISKO ZNIKNĘŁO.
KNOWN_FINDINGS: tuple[Excuse[Shape], ...] = ()
ACCEPTED_RISKS: tuple[Excuse[Shape], ...] = ()


def _dropped(line: str) -> None:
    return None


class _Log(CentrumLog):
    """The Centrum log of the queue without a file: the checker judges only the exceptions of a pass (BEZ_WYJATKU), and
    a line written to disk added only time, as ``_NotesInMemory`` says (#911)."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__(Path("centrum.log"), append=_dropped)
        self._failures = failures

    def unexpected_failure(self, failure: BaseException, *, where: str) -> None:
        super().unexpected_failure(failure, where=where)
        if where == DRAIN:
            self._failures.append(f"{type(failure).__name__}: {failure}")


class _Clock:
    """Time stands still but for the ``RETRY_S`` wake (``now``); ``after`` arms the wake that the checker fires between
    passes, as the timer would."""

    def __init__(self) -> None:
        self.armed: list[Callable[[], None]] = []
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        self.armed.append(wake)


def _queue_version(path: Path) -> str:
    """The version of a wysyłka from the name of its queue file (``Outbox.post``): its moment and number, as in its marks.

    A deliberate copy (docs/agents/skille.md, „Co wyrocznia bierze z src”): the queue file and the marks in the Skrzynka
    outlive a Wydanie, and the next one reads them, so a change of the name in ``outbox.py`` must break this checker.
    """

    return "-".join(path.stem.split("-")[:2])


class _QueueDisk:
    """The queue files of ``Outbox`` (``outbox.QueueDisk``) as steps of ``scheduler``: the read of a queue file, the
    marker write and the removal of a queue file. A wysyłka the checker posts itself (``posting``) writes its file with
    the real ``replace_atomically``: the checker fails only the marker write, never a post (the model has a failed post).
    The read fails before the real one, with the ``OSError`` that ``_queued`` lets through to ``_send_all``.
    """

    def __init__(self, scheduler: Scheduler, versions: dict[str, str]) -> None:
        self._scheduler = scheduler
        self._versions = versions
        self.posting = True

    def read(self, path: Path) -> str:
        if self._scheduler.read(f"odczyt pliku kolejki wysyłki {self._versions[_queue_version(path)]}"):
            raise PermissionError("plik zablokowany")
        return LOCAL_QUEUE_DISK.read(path)

    def write(self, path: Path, text: str) -> None:
        if self.posting:
            replace_atomically(path, text)
            return
        if self._scheduler.disk("zapis znacznika dostarczenia"):
            raise PermissionError("plik zablokowany")
        replace_atomically(path, text)
        self._scheduler.say("znacznik dostarczenia zapisany")

    def remove(self, path: Path) -> None:
        if self._scheduler.disk("usunięcie pliku kolejki"):
            raise PermissionError("plik zablokowany")
        self._scheduler.say("plik kolejki usunięty")
        LOCAL_QUEUE_DISK.remove(path)


@contextmanager
def _posting(disk: _QueueDisk) -> Iterator[None]:
    """``Outbox.post`` of a later wysyłka writes its file as the first posts do (``_QueueDisk.posting``)."""

    disk.posting = True
    try:
        yield
    finally:
        disk.posting = False


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    trace: tuple[str, ...]
    excuse: tuple[Kind, Excuse[Shape]] | None


def _marked(path: Path) -> bool:
    """The file has its delivery marker: every part and its file in the Archiwum delivered (``_queue_text``), it only
    waits to be removed."""

    entry = json.loads(path.read_text(encoding="utf-8"))
    return bool(entry.get("delivered_parts") == len(entry["parts"]) and (entry["archive"] is None or entry["archived"]))


def _waits_for_archive(path: Path) -> bool:
    """The file has the marker of its parts only: every part delivered, its file for the Archiwum not (``commented``)."""

    entry = json.loads(path.read_text(encoding="utf-8"))
    return bool(entry["archive"] is not None and entry.get("delivered_parts") == len(entry["parts"]) and not entry["archived"])


def _settled(scope: Scope, path: Path) -> bool:
    """A queue file the queue leaves for good in this scope: one whose Archiwum refuses every time, with all its parts."""

    return scope.empty_repository and _waits_for_archive(path)


ENDINGS = {
    "pusta": "kolejka pusta",
    "limit": "wyczerpany limit przejść, choć kod wciąż uruchamia kolejkę",
    "nic": "nic nie rusza kolejki do następnego startu Centrum",
    "bez-watku": "budzik albo start nie uruchamia wątku kolejki",
}


def _check(
    scope: Scope,
    box: MemoryBox,
    queue: Path,
    failures: list[str],
    ended: str,
    older: Sequence[str],
    refused: bool,
) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    if not (scope.empty_repository or refused) and any(
        WAITING in text for issue in box.issues.values() for text in (issue.body, *issue.comments)
    ):
        broken.append(("DOKLADNIE_RAZ", "komentarz ma dopisek, że plik czeka na Archiwum, choć Archiwum niczego nie odmówiło"))
    everything = (*scope.posts, *scope.later)
    newest = {(post.target.label, post.run_id): post for post in everything}
    for post in everything:
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
            broken.extend(_waiting_broken(post, box, queue) if scope.empty_repository else _archive_broken(post, box))
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
    waiting = [path.name for path in queue.glob("*.json") if not _marked(path) and not _settled(scope, path)]
    if waiting:
        broken.append(
            (
                "KOLEJKA_PUSTA",
                f"w kolejce czeka {len(waiting)} plik(ów) bez znacznika dostarczenia: {ENDINGS[ended]}",
            )
        )
    if older:
        broken.append(
            ("NAJNOWSZA_WERSJA", f"Skrzynka dostaje starszą wersję, choć nowsza czeka w kolejce: {', '.join(older)}")
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


def _waiting_broken(post: Post, box: MemoryBox, queue: Path) -> list[tuple[str, str]]:
    """DOKLADNIE_RAZ when the Archiwum refuses every time: no Archiwum, and the file waits in the queue with all parts."""

    archive = post.archive
    assert archive is not None
    waits = [path for path in queue.glob("*.json") if _waits_for_archive(path) and json.loads(path.read_text(encoding="utf-8"))["run_id"] == post.run_id]
    broken = []
    if archive.tag in box.releases:
        broken.append(("DOKLADNIE_RAZ", f"repozytorium bez commitu ma Archiwum {archive.tag}"))
    if len(waits) != 1:
        broken.append(("DOKLADNIE_RAZ", f"plik {archive.packed_name} nie czeka w kolejce na Archiwum ({len(waits)} plików)"))
    return broken


# A deliberate copy of the end of a wysyłka mark (``_mark`` in outbox.py; docs/agents/skille.md, „Co wyrocznia bierze
# z src”): marks in the Skrzynka outlive a Wydanie, and the next one reads them, so a change of the format must break
# this checker.
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
    pending: int,
    keyed: KeyedBox,
) -> object:
    """What decides every future of a pass boundary and how its breaks are judged: the Skrzynka, the queue files,
    the files ``_remove`` could not delete, the faults so far and those left, the passes left and the exceptions.
    The faults so far count as a set plus the verdict of each ``Excuse`` on them: an excuse that holds keeps holding,
    and the only order it reads (a failed marker before a kill at the removal) is in the set as the failed marker.

    The version of a wysyłka in the Skrzynka's texts (``_queue_version``, from the moment the checker posted it) counts
    as its place among the scope's wysyłki (``versions``): the code only compares versions of one wysyłka.

    Also whether a ``RETRY_S`` wake is armed, the memory of the queue that decides its next passes (``Outbox.state``,
    whose docstring says what it leaves out and why) and the queue threads started and not run yet, which decide
    whether ``send_in_background`` starts a pass. The Archiwum counts as its files with the versions in their labels and
    whether each upload ended, plus the files the queue sent twice (``MemoryBox.twice``), which the rule reads; a pair of
    ``remove`` and ``upload`` never spans a pass boundary.
    ``archive_refused`` is in the state although ``_send_all`` sets it anew in every pass, as the wake it arms is.
    Also how many later wysyłki of the scope the code has not posted yet (``pending``), which decides which versions are
    superseded, and whether the Skrzynka got a text of a superseded one (NAJNOWSZA_WERSJA).
    Time counts only as what it decides (#879): which issues and Releases GitHub's lists do not show yet, and what
    ``KeyedBox`` adds to its answers from ``opening`` and which writes it holds (``KeyedBox.state``); a wake moves time
    past all of them. The checker runs every
    pass in its own thread, so the last list of a pass is still there in the next one; in Centrum each pass has a new
    thread, so it holds at least as often, and every write follows a list of its kind in the same pass.
    Left out on purpose, because they do not change what is sent: the key verdict of ``KeyedBox`` (the key is always
    accepted, and ``Unreachable`` does not change it).
    """

    files = {
        path.name: path.read_text(encoding="utf-8") for path in queue.glob("*.json")
    }
    memory = outbox.state()
    box_state = keyed.state()

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
        tuple(sorted(files[name] for name in memory.undeleted if name in files)),
        tuple(sorted(scheduler.left.items())),
        frozenset(scheduler.faults),
        tuple(
            excuse.shape.holds(scheduler.faults)
            for excuse in (*KNOWN_FINDINGS, *ACCEPTED_RISKS)
        ),
        passes,
        tuple(failures),
        bool(clock.armed),
        memory.stopped_on,
        memory.archive_refused,
        memory.retry_armed,
        memory.draining,
        memory.again,
        threads,
        pending,
        bool(scheduler.older_sent),
        tuple(sorted(box.unlisted())),
        tuple(sorted(box.unlisted_releases())),
        box_state.archives,
        box_state.uploads,
        box_state.removals,
        box_state.names,
        box_state.opened,
        box_state.pending,
        # A list at which the file could not be read holds every write of its kind (``_held``); the checker never fails
        # the read, so this stays empty, and it is here so that such a state differs from one without it.
        box_state.unread_lists,
    )


def _emptied(work: Path) -> None:
    """Every file the last schedule left in ``work`` removed, its folders kept: the queue folder, ``config`` and
    ``zgloszenia`` hold no state of their own (the queue folder appears with the first ``Outbox.post`` of every scope
    anyway, and the folder lock opens ``PASS_LOCK`` with ``"ab"``), and deleting and creating them again for every
    schedule only cost time, most of it on Windows CI (#911)."""

    for folder, _, names in os.walk(work):
        for name in names:
            os.remove(os.path.join(folder, name))


def execute(name: str, choices: Choices, work: Path, visited: set[object]) -> list[Violation]:
    """One schedule: write the wysyłki, then passes and restarts as ``choices`` picks until failures run out.

    A schedule that reaches a pass boundary already explored, past the steps it replays from the prefix, stops
    there: the code is deterministic, so that state has the same futures, and the schedules that branch after it
    from the first visit check them.
    """

    scope = SCOPES[name]
    _emptied(work)
    queue = queue_directory(config_dir(work))
    scheduler = Scheduler(choices)
    clock = _Clock()
    box = MemoryBox(scheduler, clock, empty_repository=scope.empty_repository, list_lag=scope.list_lag)
    for label, title, body in scope.issues:
        box.issues[len(box.issues) + 1] = _Issue(label, title, body)
    failures: list[str] = []
    started_threads: list[
        Callable[[], None]
    ] = []  # targets of threads the code started, not run yet
    keyed: list[KeyedBox] = []  # the KeyedBox of the Centrum that runs now
    notes = _NotesInMemory()  # survives a restart, as the file in Dad's config folder does
    disk = _QueueDisk(scheduler, box.versions)

    def started() -> Outbox:
        clock.armed.clear()  # a timer and a thread die with their process
        started_threads.clear()
        opening = NotesFile(notes, notes.replace)  # type: ignore[arg-type]  # read_text is all KeyedBox reads of path
        keyed[:] = [KeyedBox(box, lambda: KEY, clock=clock, opening=opening)]
        return Outbox(
            queue,
            keyed[0],
            _Log(failures),
            clock=clock,
            listener=QueueListener(),
            disk=QueueDisk(read=disk.read, write=disk.write, remove=disk.remove),
            start=started_threads.append,
        )

    outbox = started()
    for post in scope.posts:
        assert outbox.post(post), "zapis wysyłki do kolejki"
    scheduler.say("wysyłki czekają w kolejce (Outbox.post)")
    versions = box.versions
    versions.update(
        (_queue_version(path), str(place))
        for place, path in enumerate(sorted(queue.glob("*.json")), start=1)
    )
    pending = list(scope.later)
    everything = (*scope.posts, *scope.later)

    def arrive() -> None:
        """The code posts the next later wysyłka; every earlier version of it in the scope is now superseded."""

        post = pending.pop(0)
        place = len(everything) - len(pending)
        with _posting(disk):
            assert outbox.post(post), "zapis wysyłki do kolejki"
        [new] = [path for path in queue.glob("*.json") if _queue_version(path) not in versions]
        versions[_queue_version(new)] = str(place)
        scheduler.superseded.update(
            str(number)
            for number, earlier in enumerate(everything[: place - 1], start=1)
            if (earlier.target, earlier.run_id) == (post.target, post.run_id)
        )
        scheduler.say(f"kod wysyła nowszą wersję {place} wysyłki {post.run_id} (Outbox.post)")

    bounds = scope.bounds
    passes = (
        bounds.unreachable + bounds.lost + bounds.disk + bounds.kills + bounds.reads + len(scope.later) + EXTRA_PASSES
    )
    ended = "pusta"
    disk.posting = False
    while pending or any(not _settled(scope, path) for path in queue.glob("*.json")):
        if not passes:
            ended = "limit"
            break
        while pending and scheduler.arrival(f"Outbox.post(wersja {len(everything) - len(pending) + 1})"):
            arrive()
        if not started_threads and pending and all(_settled(scope, path) for path in queue.glob("*.json")):
            arrive()  # nothing else is left to do before it
        if not started_threads:
            then = scheduler.between_passes(bool(clock.armed))
            if then == "restart":
                scheduler.say("Centrum startuje znów (Outbox.resume)")
                outbox = started()
                outbox.resume()
            elif then == "next":
                scheduler.say("mija RETRY_S: budzik woła Outbox._woken")
                clock.now += RETRY_S
                clock.armed.pop(0)()
            elif pending:
                arrive()  # the code posts it anyway: the next version is the last thing that moves the queue
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
            len(pending),
            keyed[0],
        )
        if state in visited and not choices.replaying:
            return []
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
    # A pass that could not read the newer file sends the older one, and the newer then changes its comment.
    older = [] if any(fault == "unreadable" for fault, _ in faults) else scheduler.older_sent
    return [
        Violation(rule, detail, trace, excused(rule, faults, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS))
        for rule, detail in _check(
            scope, box, queue, failures, ended, older, any(kind == "refused" for kind, _ in faults)
        )
    ]


@dataclass
class ScopeReport:
    name: str
    schedules: int = 0
    shortest: dict[tuple[str, str], Violation] = field(default_factory=dict)
    stopped: bool = False  # ended at the first schedule with a new violation (``--stop-at-new``)


def explore(name: str, *, stop_at_new: bool = False) -> ScopeReport:
    """Every schedule of scope ``name``; with ``stop_at_new`` only up to the first one with a new violation.

    A mutation of ``check_outbox_mutations.py`` needs only the verdict, and a new violation makes it
    ``KOLEJKA: NOWE NARUSZENIE`` whatever the schedules after it show. Without the stop, the mutation of
    ``archiwum-diagnoza`` explored all 23 787 schedules (51 s on Maks's Mac on 2026-11-05) after it saw its violation in the
    first one, and with eight mutations at once on the four vCPU of Windows CI it ran over the 600 s limit (#963).
    """

    report = ScopeReport(name)
    with tempfile.TemporaryDirectory(prefix="kolejka-skrzynki-") as directory:
        visited: set[object] = set()
        work = Path(directory) / "praca"
        for violations in schedules(lambda choices: execute(name, choices, work, visited), SCOPES[name].bounds.budget()):
            report.schedules += 1
            for violation in violations:
                key = (violation.rule, "new" if violation.excuse is None else violation.excuse[0])
                seen = report.shortest.get(key)
                if seen is None or len(violation.trace) < len(seen.trace):
                    report.shortest[key] = violation
            if stop_at_new and any(violation.excuse is None for violation in violations):
                report.stopped = True
                break
    return report


@dataclass(frozen=True)
class Outcome:
    lines: list[str]
    exit_code: int


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines: list[str] = []
    new = 0
    counts: dict[Kind, int] = {"known": 0, "accepted": 0}
    shown: set[tuple[str, str]] = set()
    for report in reports:
        stopped = " Koniec na pierwszym nowym naruszeniu (--stop-at-new)." if report.stopped else ""
        lines.append(
            f"== {report.name}: {SCOPES[report.name].description} Harmonogramy: {report.schedules}.{stopped}"
        )
        for _key, violation in sorted(report.shortest.items()):
            if violation.excuse is not None:
                shown.add((violation.excuse[1].name, report.name))
            if violation.excuse is not None and not strict:
                counts[violation.excuse[0]] += 1
                lines.append(f"   {excuse_line(*violation.excuse)}")
            else:
                new += 1
                lines.append(f"   NOWE NARUSZENIE {violation.rule}")
            lines.append(f"   {violation.detail}")
            lines.extend(
                f"   {number}. {step}"
                for number, step in enumerate(violation.trace, start=1)
            )
    # A scope that stopped early did not reach every schedule, so an entry it did not see may still be there.
    finished = [report.name for report in reports if not report.stopped]
    disappeared = gone_lines(finished, shown, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
    lines.extend(disappeared)
    lines.append("")
    verdict_line, code = verdict(
        "KOLEJKA", new=new, gone=len(disappeared), known=counts["known"], accepted=counts["accepted"]
    )
    lines.append(verdict_line)
    return Outcome(lines, code)


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
    parser.add_argument(
        "--stop-at-new",
        action="store_true",
        help="end at the first schedule with a new violation: the verdict of a mutation run, not its shortest counterexample",
    )
    arguments = parser.parse_args(argv)
    reports: list[ScopeReport] = []
    for name in arguments.scope or SCOPES:
        reports.append(explore(name, stop_at_new=arguments.stop_at_new))
        if reports[-1].stopped:
            break  # the verdict is already NOWE NARUSZENIE
    outcome = summarize(reports, strict=arguments.strict)
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
