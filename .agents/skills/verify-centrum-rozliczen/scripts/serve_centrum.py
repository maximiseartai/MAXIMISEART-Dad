"""Serve the real Centrum rozliczeń for one verification run on 127.0.0.1.

This is the production app (``create_app`` + ``serve`` from ``rozliczenia.centrum``)
with run-local inputs: the settings file, the configuration directory
(Lista Wykonawców and the three Wzorce), and the metrics files of the processes live in
the run root and ``File.FIXTURE`` names them (never Dad's files next to the tool), and the platform adapter,
the production boundary for Dad's computer, is scripted.
Every file of the run root named below by a member of ``harness.py`` is the file of that member; without it the
boundary answers as the sentence says.

- the native file and folder pickers answer with the path in ``File.PICKER_ANSWER``
  (consumed by the next picker; no file = Dad cancelled) and log each dialog title in ``Log.DIALOGS``;
- opening a file in Excel or a folder in Explorer is logged in ``Log.OPENED`` instead of launching an application;
- the Windows Autostart is the file ``File.AUTOSTART_SHORTCUT``: the switch „Uruchamiaj Centrum razem z Windows”
  writes or removes it, the drive may remove it by hand, and while ``Switch.NO_AUTOSTART`` is on the computer has no
  Windows Autostart, like a Mac.

The Diagnoza's two boundaries beyond Dad's files are scripted too, so the
verification never reaches GitHub and checks OneDrive on every system:

- the commit of the newest Wydanie on GitHub is the tool's own commit (up to date) unless
  ``File.MAIN_COMMIT`` names another one, and its tag is the one in ``File.RELEASE_TAG`` (none without it);
  the published Wydania (GitHub Releases with their notes) are ``File.RELEASES`` in the
  shape of GitHub's list (none without it); while ``Switch.GITHUB_OFFLINE`` is on there is no network.
  The tool is the run's synthetic clone (``tool.clone`` of ``File.FIXTURE``): its own commit is the
  clone's ``HEAD`` (``tool_commit``) unless ``File.TOOL_COMMIT`` names another one (Dad updated the tool),
  the day it is on that commit comes from the clone's ``HEAD`` reflog (``commit_since``), and its Wydanie
  from the clone's tags on that commit (``release_at``), as in production;
- a file whose full path is a line of ``File.CLOUD_ONLY`` has the Windows attribute of a OneDrive file
  „tylko online”.

Aktualizacja narzędzia moves that clone with real Git, fetching from the
run's local "origin" (``tool.origin``) instead of GitHub, so no
Centrum of a verification run ever updates the checkout it runs from. After a
successful update this Centrum closes itself and the real restart guardian runs
the clone's ``run_centrum.py``, a fixture shim that runs this script again with
the same run root and port after ``Pace.RESTART``: the restarted Centrum keeps every scripted boundary
and rewrites ``File.SERVER`` with its own pid.

The skrzynka Zgłoszeń (Maks's private repository on GitHub at Dad's) is a
directory, ``report_box``: each issue Centrum opens (a Zgłoszenie
Dad sends, or a Kontrola ilości Centrum sends by itself) becomes its
``issue_file`` with its title, body, label, comments, and ``state`` (``open``; the
drive may edit it to ``closed`` with ``state_reason`` and ``closed_at`` as GitHub
gives them, which Centrum reads as Maks closing the Zgłoszenie or Uwaga taty).
``body`` and ``comments`` are what Maks sees on GitHub, without the hidden line of the
queue's delivery mark (``tools/lib/atrapy/widok_skrzynki.py``); ``raw_body`` and
``raw_comments`` hold the text as Centrum wrote it, which Centrum reads back, and
Centrum may change a comment (``edit_comment``) in place.
Asked for the issues with a label, the skrzynka lists the files
with that label, only the ``open`` ones unless closed issues are asked for too;
Centrum takes the newest one whose body has its exact line (the fingerprint
line of a Zgłoszenie's problem, or the period line of a Kontrola ilości, which
then goes into that file's ``comments``). The key is never written
there. The skrzynka puts each issue file and the ``archive_listing`` in place at once (``replace_atomically``), as GitHub
never shows half an issue: the drive reads them from its own process, and on Windows a plain write leaves the file
empty for a moment (#963). The drive edits an issue file the same way (``edit_issue``), so the skrzynka reads an issue
file once it is in place (``_read_put_in_place``). While ``Switch.BOX_OFFLINE`` is on the skrzynka is unreachable,
while ``Switch.KEY_REFUSED`` is on it refuses the key for every question
(``Refused``, like GitHub's 401 for an expired token), and while
``rejects`` of a label is on it rejects the content of every new
issue with that label and of every comment to one (``Rejected``, like GitHub's 422).
The Archiwa Logów okresu (GitHub Releases of that repository) live beside it: ``archive_listing`` lists
each Archiwum (id, tag, title, description) and its files (id, name, label), and ``archive_file`` holds the bytes of each
file as Centrum uploaded them (gzip). A second file of one name in one Archiwum is ``Rejected``, as on GitHub, a file
gets an id no file had before, also one removed (``last_file_id`` keeps the last id), as on GitHub, where
``KeyedBox`` tells a removed file from its new version by the id, and while
``Switch.ARCHIVE_REFUSED`` is on every step of the Archiwum is ``Refused``, like GitHub's 403 for a
Token without the permission to write the repository's contents.
GitHub's rate limit (a 403 that is no refusal) only pytest covers, on the GitHub adapter.
Each question for the issues with a label, closed ones included (how
Powiadomienia ask about Dad's sent Zgłoszenia and Uwagi), logs its label in ``Log.REPORT_QUESTIONS``.
While ``Pace.REPORT_BOX`` is on, the skrzynka waits that many milliseconds before it opens an issue, like
GitHub over a slow connection, so the drive can see that Centrum starts without
waiting for the Kontrole ilości it sends again at start.

Centrum asks the skrzynka for the state of Dad's sent cases, and GitHub for the
Wydania, at most once per 10 minutes of its monotonic clock; each question for the
published Wydania is logged in ``Log.RELEASE_QUESTIONS``; ``File.CLOCK_MOVE`` moves that
clock forward by the given minutes, so the drive need not wait. Wake-ups on that clock (the queue's retry a minute
after a failure) fire within 0.2 s of their moment, so moving the clock wakes the queue at once. A failure of that
wake-up thread leaves its traceback in ``File.CLOCK_DIED``, as no wake-up fires after it.

One harness-only pacing hook: while ``Pace.TEMPLATES`` is on,
each Szablon pracownika of a Przebieg rozliczeń RUN waits that many
milliseconds before it is written. The synthetic Szablony take milliseconds,
so without it the live Szablony pracowników progress and the refused closing
during the Uruchomienie could not be observed. Results are unchanged.

One more pacing hook: while ``Pace.UPDATE`` is on, each
Aktualizacja narzędzia waits that many milliseconds before it looks for Git.
Fetching from the local "origin" takes milliseconds, so without it the progress
and the refusals during an update could not be observed. Results are unchanged.
Likewise, while ``Pace.INSTALL`` is on, each installation of
libraries waits that many milliseconds before it starts.

Libraries are installed by the production installer (``pip_install``: this
Python's ``-m pip``), but pip is offline: ``PIP_NO_INDEX`` is set for this
process, so an installation never reaches PyPI and fails when it needs a library
that is not installed. The run's virtual environment may have no pip at all;
then the installation fails the same way.

One harness-only fault hook: while ``Switch.REGISTER_FAULT`` is on,
reading the Rejestr zleceń raises an exception the process does not expect, so
the drive can show Dad's path after a nieoczekiwany wyjątek. The hook is the
byte source of Dad's files this Centrum gets (``create_app(source=...)``, ``DadFiles.source``), which the
Uruchomienie procesu and its Diagnoza both read the Rejestr with, so the fault reaches the
Diagnoza too, as a real one that does not go away would. No synthetic file causes one,
because every known problem has its own Komunikat.

Once the port is bound, ``File.SERVER`` records this process and URL.
Each HTTP request it answered is a line ``REQUEST <moment> <method> <path> <status>`` on its console (``_RequestLog``),
which the run keeps as ``server.txt`` or ``api/<name>-server.txt`` of the evidence.
The Centrum log goes where the tool keeps it in the run root (``log_path``), and the button
„Zamknij Centrum rozliczeń” stops this process the way it stops Dad's.

Wycena w efenix never reaches efenix.pl (ADR 0024): this script serves the Atrapa efenix of the tests
(``tools/lib/atrapy/atrapa_efenix.py``) on a free local port for as long as Centrum runs, writes its address to
``File.EFENIX_ADDRESS``, and gives Centrum an efenix window in Playwright's headless Chromium with its profile in
the run root and no human pace, like the
tests of the process (Dad's window pauses about 20 s per order). The Atrapa holds ``EFENIX_ORDERS`` of ``tools/lib/atrapy/scenariusz_centrum.py`` (made-up numbers, addresses and logins), starts
logged out, so the window waits for Dad's login, and answers each search after ``EFENIX_SEARCH_DELAY_S``, so the
live progress can be seen; a form posted to its ``page_login.php`` logs in. At its first start for a run root the
script also writes the Plik zbiorczy of those orders, with the Kwota (AU) Excel computed, to its period folder in
``efenix_files`` (outside the folder okresów, so the drive puts it in place when it needs it).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from functools import partial
import imaplib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.efenix_chrome import EfenixWindow
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import AutostartState
from rozliczenia.centrum.report_box import (
    Archive,
    ArchiveOutcome,
    Asset,
    Closure,
    Comment,
    CommentOutcome,
    CommentsOutcome,
    Commented,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    Refused,
    Rejected,
    RemoveOutcome,
    SendOutcome,
    Sent,
    Unreachable,
    UploadOutcome,
    close_reason,
)
from rozliczenia.centrum.server import serve
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import GitHubReleases, PublishedRelease, ToolFreshness, parse_published
from rozliczenia.centrum.tool_update import ToolClone, find_git, pip_install, release_at
from rozliczenia.centrum.version import commit_since, tool_commit
from rozliczenia.template_file import TemplateFile
from rozliczenia.tool_files import listen_locally, log_path
from rozliczenia.write_routes import Route
from rozliczenia.workbook_files import ByteSource, DataRow, RegisterRow, file_bytes
from skrypt_skilla import Parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from harness import (
    INBOX_ADDRESS,
    INBOX_PASSWORD,
    File,
    Log,
    SLOW_RUNNER,
    Pace,
    Switch,
    archive_file,
    archive_listing,
    comment_address,
    efenix_files,
    issue_file,
    last_file_id,
    rejects,
    report_box,
)
from atrapy.atrapa_efenix import atrapa_efenix
from atrapy.skrzynka import ArchivedFile, Archives, BoxArchive, BoxIssue, Issues
from atrapy.widok_skrzynki import shown
from atrapy.efenix import write_collective_file
from atrapy.scenariusz_centrum import EFENIX_ORDERS, EFENIX_SETTLED, EFENIX_UNKNOWN
from atrapy.skrzynka_raportow import AtrapaImap, FolderInbox

EFENIX_SEARCH_DELAY_S = 1.0
# The mode „wolny runner” (SLOW_RUNNER): Centrum takes each request of its API this late.
API_DELAY_S = 0.3
# How long a file the drive is putting in place is tried again (``_read_put_in_place``).
READ_RETRY_S = 10.0


def _read_put_in_place(path: Path, retry_s: float = READ_RETRY_S) -> str:
    """``path`` once the drive has put it in place whole (``put_text`` of ``drive/common.py``): Windows refuses a read
    for that moment (#1087), so a refused read is tried again for at most ``retry_s``, then the refusal is raised."""

    deadline = time.monotonic() + retry_s
    while True:
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


class ScriptedPlatform:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()

    def _log(self, log: Log, record: dict[str, str]) -> None:
        with self._lock:
            log.append(self._root, record)

    def _answer(self, title: str) -> Path | None:
        self._log(Log.DIALOGS, {"title": title})
        answer = File.PICKER_ANSWER.file(self._root)
        if not answer.exists():
            return None
        chosen = answer.read_text(encoding="utf-8").strip()
        answer.unlink()
        return Path(chosen)

    def open_path(self, path: Path) -> None:
        self._log(Log.OPENED, {"path": str(path)})

    def choose_file(self, title: str, filetypes: Sequence[tuple[str, str]]) -> Path | None:
        return self._answer(title)

    def choose_folder(self, title: str) -> Path | None:
        return self._answer(title)


class ScriptedAutostart:
    """The Windows Autostart as the file ``File.AUTOSTART_SHORTCUT`` of the run root (see the module doc)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def state(self) -> AutostartState:
        if Switch.NO_AUTOSTART.is_on(self._root):
            return "unsupported"
        return "on" if File.AUTOSTART_SHORTCUT.file(self._root).exists() else "off"

    def enable(self) -> None:
        File.AUTOSTART_SHORTCUT.write(self._root, "skrót")

    def disable(self) -> None:
        File.AUTOSTART_SHORTCUT.file(self._root).unlink(missing_ok=True)


class FileReportBox:
    """The skrzynka Zgłoszeń as a directory of ``<number>.json`` files (see the module doc).

    Each step reads the state from the files into the model of the fakes (``atrapy.skrzynka``), which owns GitHub's
    rules, and writes back what the step changed; the scripted refusals and the unreachable network come first.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._directory = report_box(root)
        self._lock = threading.Lock()

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        refused = self._archive_refused()
        if refused is not None:
            return refused
        with self._lock:
            return self._archive_state().archive(tag)

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        refused = self._archive_refused()
        if refused is not None:
            return refused
        with self._lock:
            state = self._archive_state()
            outcome = state.open_archive(tag, title, description)
            if isinstance(outcome, Archive):
                self._save_archives(state)
        return outcome

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        refused = self._archive_refused()
        if refused is not None:
            return refused
        with self._lock:
            state = self._archive_state()
            outcome = state.upload(archive_id, name, label, data)
            if isinstance(outcome, Asset):
                [archive] = [each for each in state.archives if each.id == archive_id]
                stored = archive_file(self._root, archive.tag, name)
                stored.parent.mkdir(parents=True, exist_ok=True)
                stored.write_bytes(data)
                self._save_archives(state)
        return outcome

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        refused = self._archive_refused()
        if refused is not None:
            return refused
        with self._lock:
            state = self._archive_state()
            found = state.file(asset_id)
            outcome = state.remove(asset_id)
            if found is not None:
                archive, asset = found
                archive_file(self._root, archive.tag, asset.name).unlink()
                self._save_archives(state)
        return outcome

    def _archive_refused(self) -> Refused | Unreachable | None:
        if Switch.BOX_OFFLINE.is_on(self._root):
            return Unreachable()
        if Switch.KEY_REFUSED.is_on(self._root) or Switch.ARCHIVE_REFUSED.is_on(self._root):
            return Refused()
        return None

    def _archive_state(self) -> Archives:
        """The Archiwa as listed (``archive_listing``) with each file's bytes (``archive_file``) and the last file id
        (``last_file_id``)."""

        listed, last = archive_listing(self._root), last_file_id(self._root)
        entries = json.loads(listed.read_text(encoding="utf-8")) if listed.is_file() else []
        return Archives(
            [
                BoxArchive(
                    entry["id"],
                    entry["tag"],
                    entry["title"],
                    entry["description"],
                    [
                        ArchivedFile(asset["id"], asset["name"], asset["label"], archive_file(self._root, entry["tag"], asset["name"]).read_bytes())
                        for asset in entry["assets"]
                    ],
                )
                for entry in entries
            ],
            last_file_id=int(last.read_text(encoding="utf-8")) if last.is_file() else 0,
        )

    def _save_archives(self, state: Archives) -> None:
        last = last_file_id(self._root)
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(str(state.last_file_id), encoding="utf-8")
        _save(
            archive_listing(self._root),
            [
                {
                    "id": archive.id,
                    "tag": archive.tag,
                    "title": archive.title,
                    "description": archive.description,
                    "assets": [{"id": asset.id, "name": asset.name, "label": asset.label} for asset in archive.assets],
                }
                for archive in state.archives
            ],
        )

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        Pace.REPORT_BOX.wait(self._root)
        if (blocked := self._blocked()) is not None:
            return blocked
        if self._rejects(label):
            return Rejected()
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            opened = self._issues(*self._directory.glob("*.json")).open(label, title, body)
            issue = {
                "number": opened.number,
                "title": title,
                "body": shown(body),
                "raw_body": body,
                "labels": [label],
                "state": "open",
            }
            _save(issue_file(self._root, opened.number), issue)
        return Sent(opened.number)

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        """The comment goes into the issue's own file, so numbering by ``*.json`` stays the issue count.

        Its address names the file within the run root, never the full path: the Zgłoszenie links it, and a
        Zgłoszenie holds no full path. Comment ``k`` of issue ``n`` has the id ``n * 1000 + k``.
        """

        if (blocked := self._blocked()) is not None:
            return blocked
        with self._lock:
            found = self._issues(*self._issue_file(number)).comment(number, body)
            if isinstance(found, Refused):
                return found
            issue, comment_id = found
            if self._rejects(issue.label):
                return Rejected()
            self._save_comments(issue)
        return Commented(comment_id, _comment_address(issue, comment_id))

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        if (blocked := self._blocked()) is not None:
            return blocked
        with self._lock:
            found = self._issues(*self._issue_file(comment_id // _COMMENT_BASE)).edit_comment(comment_id, body)
            if isinstance(found, Refused):
                return found
            if self._rejects(found.label):
                return Rejected()
            self._save_comments(found)
        return Commented(comment_id, _comment_address(found, comment_id))

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        if (blocked := self._blocked()) is not None:
            return blocked
        with self._lock:
            found = self._issues(*self._issue_file(number)).comments(number)
        if isinstance(found, Refused):
            return found
        return tuple(
            Comment(comment_id, _comment_address(found, comment_id), text)
            for comment_id, text in zip(found.comment_ids, found.comment_texts, strict=True)
        )

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        if include_closed:
            with self._lock:
                Log.REPORT_QUESTIONS.append(self._root, {"label": label})
        if (blocked := self._blocked()) is not None:
            return blocked
        with self._lock:
            return self._issues(*self._directory.glob("*.json")).listed(label, include_closed=include_closed)

    def _blocked(self) -> Refused | Unreachable | None:
        if Switch.BOX_OFFLINE.is_on(self._root):
            return Unreachable()
        if Switch.KEY_REFUSED.is_on(self._root):
            return Refused()
        return None

    def _issue_file(self, number: int) -> tuple[Path, ...]:
        path = issue_file(self._root, number)
        return (path,) if path.is_file() else ()

    def _issues(self, *paths: Path) -> Issues:
        documents = (json.loads(_read_put_in_place(path)) for path in paths)
        return Issues(sorted(map(_box_issue, documents), key=lambda issue: issue.number), comment_base=_COMMENT_BASE)

    def _save_comments(self, issue: BoxIssue) -> None:
        path = issue_file(self._root, issue.number)
        document = json.loads(_read_put_in_place(path))
        document["raw_comments"], document["comments"] = issue.comment_texts, issue.comments
        _save(path, document)

    def _rejects(self, label: str) -> bool:
        return rejects(self._root, label).exists()


# Comment ``k`` of issue ``n`` has the id ``n * 1000 + k`` (``FileReportBox.comment``).
_COMMENT_BASE = 1000


def _box_issue(issue: dict[str, Any]) -> BoxIssue:
    """``issue`` as Centrum wrote it (``raw_body``, ``raw_comments``); an issue the drive wrote itself has only ``body``
    and ``comments``, and its ``state_reason`` and ``closed_at`` are Maks's closing as GitHub gives it."""

    number = issue["number"]
    texts = list(issue.get("raw_comments", issue.get("comments", [])))
    ids = [number * _COMMENT_BASE + position for position in range(1, len(texts) + 1)]
    body = issue.get("raw_body", issue["body"])
    return BoxIssue(number, issue["labels"][0], issue.get("title", ""), body, texts, ids, _closure(issue))


def _comment_address(issue: BoxIssue, comment_id: int) -> str:
    return comment_address(issue.number, issue.position(comment_id))


def _save(path: Path, content: object) -> None:
    """``content`` as JSON in place of ``path`` at once: a reader in another process sees the old file or the new one,
    never an empty or cut one (module doc, #963)."""

    replace_atomically(path, json.dumps(content, ensure_ascii=False, indent=2) + "\n")


def _closure(issue: dict[str, Any]) -> Closure | None:
    """Maks's closing as the drive wrote it, with ``state_reason`` and ``closed_at`` like GitHub."""

    if issue["state"] != "closed":
        return None
    closed_at = issue.get("closed_at")
    return Closure(close_reason(issue.get("state_reason")), datetime.fromisoformat(closed_at) if closed_at else None)


def _scripted_github(root: Path, clone: Path) -> ToolFreshness:
    def local_commit() -> str | None:
        chosen = File.TOOL_COMMIT.file(root)
        return chosen.read_text(encoding="utf-8").strip() if chosen.exists() else tool_commit(clone)

    def since() -> date | None:
        commit = local_commit()
        return None if commit is None else commit_since(commit, clone)

    def releases() -> GitHubReleases | None:
        if Switch.GITHUB_OFFLINE.is_on(root):
            return None
        chosen, tag = File.MAIN_COMMIT.file(root), File.RELEASE_TAG.file(root)
        return GitHubReleases(
            chosen.read_text(encoding="utf-8").strip() if chosen.exists() else local_commit(),
            tag.read_text(encoding="utf-8").strip() if tag.exists() else None,
        )

    def published() -> tuple[PublishedRelease, ...] | None:
        Log.RELEASE_QUESTIONS.append(root, {"lista": "wydania"})
        if Switch.GITHUB_OFFLINE.is_on(root):
            return None
        listed = File.RELEASES.file(root)
        return parse_published(json.loads(listed.read_text(encoding="utf-8"))) if listed.exists() else ()

    return ToolFreshness(
        local=local_commit, since=since, release=releases, published=published, wydanie=partial(release_at, clone)
    )


class ScriptedClock:
    """Centrum's clock: monotonic time moved forward by ``File.CLOCK_MOVE`` (see the module doc)."""

    def __init__(self, root: Path, *, retry_s: float = READ_RETRY_S, alarm: bool = True) -> None:
        """``retry_s`` limits a refused read of the move (``_read_put_in_place``); without ``alarm`` no wake-up thread
        fires what ``after`` schedules, as the self-test needs for a clock it only reads."""

        self._moved = File.CLOCK_MOVE.file(root)
        self._died = File.CLOCK_DIED.file(root)
        self._retry_s = retry_s
        self._lock = threading.Lock()
        self._wakes: list[tuple[float, Callable[[], None]]] = []
        if alarm:
            threading.Thread(target=self._fire_due, name="zegar-budzik", daemon=True).start()

    def __call__(self) -> float:
        return time.monotonic() + self._moved_s()

    def _moved_s(self) -> float:
        """The move in seconds, which the drive puts in place whole (``_read_put_in_place``)."""

        try:
            return float(_read_put_in_place(self._moved, self._retry_s)) * 60
        except FileNotFoundError:
            return 0.0

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        with self._lock:
            self._wakes.append((self() + seconds, wake))

    def _fire_due(self) -> None:
        """A failure ends every later wake-up, so it leaves its traceback where the drive finds it
        (``check_clock_alarm``), put in place whole: a plain write leaves it empty for a moment, and a reader that waits
        only for it to exist reads no traceback (#1210)."""

        try:
            while True:
                time.sleep(0.2)
                now = self()
                with self._lock:
                    due = [wake for moment, wake in self._wakes if moment <= now]
                    self._wakes = [(moment, wake) for moment, wake in self._wakes if moment > now]
                for wake in due:
                    wake()
        except BaseException:
            replace_atomically(self._died, traceback.format_exc())
            raise


class _RequestLog:
    """Each HTTP request on the console once answered: the moment it came (UTC), the method, the path without its query
    and the answer's status, or how the answer broke off. The evidence then shows whether a request the page lost
    (``zadania-strony.txt`` of the drive) reached Centrum (#1539). Only these: a query or a body may carry a value of
    a file."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        came = datetime.now(UTC).isoformat(timespec="milliseconds")
        status: list[int] = []

        async def answer(message: Message) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)

        line = f"REQUEST {came} {scope['method']} {quote(scope['path'])}"
        try:
            await self.app(scope, receive, answer)
        except BaseException as broken:
            print(f"{line} {status[0] if status else '-'} broken off: {type(broken).__name__}", flush=True)
            raise
        print(f"{line} {status[0] if status else 'no answer'}", flush=True)


class _LateApi:
    """Each request of ``/api/`` waits ``API_DELAY_S`` before Centrum takes it; the page itself does not."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            await asyncio.sleep(API_DELAY_S)
        await self.app(scope, receive, send)


def _scripted_onedrive(root: Path) -> CloudFiles:
    normal, online_only = 0x80, 0x400000  # FILE_ATTRIBUTE_NORMAL, FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

    def attributes(path: Path) -> int:
        listed = File.CLOUD_ONLY.file(root)
        lines = listed.read_text(encoding="utf-8").splitlines() if listed.exists() else []
        return online_only if str(path) in lines else normal

    return CloudFiles(read_attributes=attributes)


def _paced_git(root: Path) -> Callable[[], Path | None]:
    def found() -> Path | None:
        Pace.UPDATE.wait(root)
        return find_git()

    return found


def _paced_install(root: Path) -> Callable[[Path], bool]:
    def install(requirements: Path) -> bool:
        Pace.INSTALL.wait(root)
        return pip_install(requirements)

    return install


def _pace_worker_templates(root: Path, worker_template: Path) -> None:
    create = TemplateFile.create
    worker_template = worker_template.resolve()

    def paced(self: TemplateFile, target: Path, rows: Sequence[DataRow] | Sequence[RegisterRow]) -> Route:
        if self.path == worker_template:
            Pace.TEMPLATES.wait(root)
        return create(self, target, rows)

    TemplateFile.create = paced  # type: ignore[method-assign]


def _register_failing_on_hook(root: Path, register: Path) -> ByteSource:
    def source(path: Path) -> bytes:
        if Switch.REGISTER_FAULT.is_on(root) and path.name == register.name:
            raise RuntimeError("synthetic unexpected failure")
        return file_bytes(path)

    return source


@contextmanager
def _efenix_window(root: Path) -> Iterator[EfenixWindow]:
    directory = efenix_files(root)
    if not directory.exists():
        write_collective_file(directory, EFENIX_ORDERS)
    known = [
        replace(order.in_efenix(f"90{index}"), status="Rozliczone") if order.number in EFENIX_SETTLED else order.in_efenix(f"90{index}")
        for index, order in enumerate(EFENIX_ORDERS)
        if order.number not in EFENIX_UNKNOWN
    ]
    with atrapa_efenix(known, answer_delay_s=EFENIX_SEARCH_DELAY_S) as atrapa:
        atrapa.expire_session()
        File.EFENIX_ADDRESS.write(root, atrapa.url)
        # Bez tempa ludzkiego, jak testy procesu: na Atrapie efenix nikt nie patrzy na sesję taty.
        yield EfenixWindow(atrapa.url, root / "przegladarka-efenix", channel=None, headless=True, pace=None)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_root("Run root created by create_centrum_fixture.py.")
    parser.add_argument("--port", type=int, required=True, help="Free port on 127.0.0.1.")
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        return _serve(args, stack)


def _serve(args: argparse.Namespace, stack: ExitStack) -> int:
    root = args.root
    fixture = json.loads(File.FIXTURE.file(root).read_text(encoding="utf-8"))
    today = date.fromisoformat(fixture["today"])
    metrics = fixture["metrics"]
    catalog = CATALOG.with_metrics(
        {
            "preparation": Path(metrics["preparation"]),
            "settlement": Path(metrics["settlement"]),
            "efenix": Path(metrics["efenix"]),
            "intermax": Path(metrics["intermax"]),
            "report_entering": Path(metrics["report_entering"]),
        }
    )
    configuration = {name: Path(path) for name, path in fixture["configuration"].items()}
    clone = Path(fixture["tool"]["clone"])
    log = CentrumLog(log_path(root))
    shutdown = Shutdown(log)
    _pace_worker_templates(root, configuration["worker_template"])
    efenix = stack.enter_context(_efenix_window(root))
    inbox = stack.enter_context(AtrapaImap(address=INBOX_ADDRESS, password=INBOX_PASSWORD))

    def inbox_connect() -> imaplib.IMAP4:
        """The login after a new password in Ustawienia goes to the atrapa, or nowhere while ``INBOX_OFFLINE`` is on."""

        if Switch.INBOX_OFFLINE.is_on(root):
            raise ConnectionRefusedError("skrzynka raportów poza siecią (atrapa)")
        return imaplib.IMAP4("127.0.0.1", inbox.port)

    # Pip never reaches PyPI from a verification run.
    os.environ["PIP_NO_INDEX"] = "1"
    app = create_app(
        config=Path(fixture["settings"]).parent,
        platform=ScriptedPlatform(root),
        autostart=ScriptedAutostart(root),
        log=log,
        shutdown=shutdown,
        today=lambda: today,
        catalog=catalog,
        configuration_files=ConfigurationFiles(**configuration),
        tool_freshness=_scripted_github(root, clone),
        cloud_files=_scripted_onedrive(root),
        report_box=FileReportBox(root),
        clock=ScriptedClock(root),
        tool_update=ToolClone(
            clone, origin=str(Path(fixture["tool"]["origin"])), find_git=_paced_git(root), install=_paced_install(root)
        ),
        source=_register_failing_on_hook(root, Path(fixture["order_register"])),
        intermax_copies=Path(fixture["intermax"]["copies"]),
        now=lambda: datetime.combine(today, datetime.now().astimezone().timetz()),
        efenix_window=efenix,
        inbox_connect=inbox_connect,
        # Wpisanie raportów reads the run's .eml folder, never Dad's Gmail.
        worker_report_inbox=FolderInbox(Path(fixture["report_entering"]["mails"])),
    )

    if SLOW_RUNNER in os.environ:
        app.add_middleware(_LateApi)
    app.add_middleware(_RequestLog)

    def record_bound_server(url: str) -> None:
        """The run waits for the record as soon as it exists, so it is put in place whole (``replace_atomically``)."""

        record = {"pid": os.getpid(), "port": args.port, "url": url}
        replace_atomically(File.SERVER.file(root), json.dumps(record))
        print(f"SERVING {url}", flush=True)

    return serve(app, listener=listen_locally(args.port), on_ready=record_bound_server, shutdown=shutdown, log=log)


if __name__ == "__main__":
    raise SystemExit(main())
