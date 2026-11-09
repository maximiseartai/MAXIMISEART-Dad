"""Kolejka wysyłki starego Centrum w osobnym procesie i Skrzynka Zgłoszeń w plikach, którą widzą oba procesy.

Stare Centrum po zwolnieniu portu jeszcze kończy pracę, a nowe już startuje na tym samym folderze kolejki (Ponowny
start Centrum, skrót kliknięty zaraz po zamknięciu). ``old_centrum`` uruchamia prawdziwy ``Outbox`` w procesie
potomnym: jego przejście staje w ``open_issue``, a gdy test je puści (``finish``), Skrzynka zakłada issue i proces
się kończy, zanim kolejka dostanie odpowiedź, jak wątek kolejki, który ginie z końcem procesu. ``killed_after_comment``
tak samo kończy proces Centrum, gdy Skrzynka przyjęła pierwszy komentarz, przed znacznikiem dostarczenia.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import Outbox
from rozliczenia.centrum.report_box import (
    ArchiveOutcome,
    Comment,
    Commented,
    CommentOutcome,
    CommentsOutcome,
    Issue,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    RemoveOutcome,
    SendOutcome,
    Sent,
    UploadOutcome,
)

from tests.fixtures.clock import ManualClock
from tests.fixtures.potomne import wait_for
from atrapy.sluchacz_kolejki import QueueListener

ROOT = Path(__file__).resolve().parents[2]
KEY = "github_pat_SYNTETYCZNY_KLUCZ"
_OPENING = "zaklada-issue"
_COMMENT = "komentarz"


class SharedBox:
    """Skrzynka Zgłoszeń w folderze ``directory``: issue to plik ``<numer>.json`` z etykietą, treścią i komentarzami.

    Numer to pierwszy wolny plik (``O_EXCL``), więc dwa procesy nie założą dwóch issue pod jednym numerem, a
    komentarz ``k`` issue ``n`` ma identyfikator ``n * 1000 + k``.
    ``before_opening`` biegnie na początku każdego ``open_issue``, ``after_opening`` po założeniu issue, a
    ``after_comment`` po zapisaniu komentarza, przed odpowiedzią.
    """

    def __init__(
        self,
        directory: Path,
        *,
        before_opening: Callable[[], None] = lambda: None,
        after_opening: Callable[[], None] = lambda: None,
        after_comment: Callable[[], None] = lambda: None,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._before_opening = before_opening
        self._after_opening = after_opening
        self._after_comment = after_comment

    def issues(self) -> list[dict[str, object]]:
        """Issue po numerze, każde z ``label``, ``body`` i ``comments``."""

        numbered = sorted(self._directory.glob("*.json"), key=lambda path: int(path.stem))
        return [json.loads(path.read_text(encoding="utf-8")) for path in numbered]

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        self._before_opening()
        for number in itertools.count(1):
            try:
                descriptor = os.open(self._directory / f"{number}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as issue:
                json.dump({"label": label, "title": title, "body": body, "comments": []}, issue)
            self._after_opening()
            return Sent(number)
        raise AssertionError("itertools.count nie kończy się")

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        path = self._directory / f"{number}.json"
        issue = json.loads(path.read_text(encoding="utf-8"))
        issue["comments"].append(body)
        path.write_text(json.dumps(issue), encoding="utf-8")
        self._after_comment()
        position = len(issue["comments"])
        return Commented(number * 1000 + position, f"{path.name}#komentarz-{position}")

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        path = self._directory / f"{number}.json"
        bodies = json.loads(path.read_text(encoding="utf-8"))["comments"]
        return tuple(
            Comment(number * 1000 + position, f"{path.name}#komentarz-{position}", body)
            for position, body in enumerate(bodies, start=1)
        )

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        number, position = divmod(comment_id, 1000)
        path = self._directory / f"{number}.json"
        issue = json.loads(path.read_text(encoding="utf-8"))
        issue["comments"][position - 1] = body
        path.write_text(json.dumps(issue), encoding="utf-8")
        return Commented(comment_id, f"{path.name}#komentarz-{position}")

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        raise AssertionError("stare Centrum w tych testach wysyła tylko Kontrole ilości, bez plików do Archiwum")

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        raise AssertionError("stare Centrum w tych testach wysyła tylko Kontrole ilości, bez plików do Archiwum")

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        raise AssertionError("stare Centrum w tych testach wysyła tylko Kontrole ilości, bez plików do Archiwum")

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        raise AssertionError("stare Centrum w tych testach wysyła tylko Kontrole ilości, bez plików do Archiwum")

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        return tuple(
            Issue(int(path.stem), issue["body"])
            for path in sorted(self._directory.glob("*.json"), key=lambda path: int(path.stem))
            if (issue := json.loads(path.read_text(encoding="utf-8")))["label"] == label
        )


def queue_on(directory: Path, box: SharedBox, log: Path, clock: ManualClock) -> Outbox:
    """Kolejka Centrum na folderze ``directory`` ze skrzynką ``box`` i kluczem do Zgłoszeń."""

    return Outbox(directory, KeyedBox(box, lambda: KEY, clock=clock), CentrumLog(log), clock=clock, listener=QueueListener())


@dataclass
class OldCentrum:
    process: subprocess.Popen[bytes]

    def finish(self) -> None:
        """Skrzynka zakłada issue staremu Centrum, a ono kończy się przed odpowiedzią; czeka na koniec procesu."""

        _output, errors = self.process.communicate(b"\n", timeout=60)
        assert self.process.returncode == 0, errors.decode("utf-8", "replace")


def killed_after_comment(directory: Path, box: Path, log: Path) -> None:
    """Centrum, którego przejście kolejki ``directory`` kończy się razem z procesem zaraz po tym, jak skrzynka ``box``
    przyjęła pierwszy komentarz, przed znacznikiem dostarczenia; czeka na koniec procesu."""

    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tools" / "lib")])}
    command = [sys.executable, "-m", "tests.fixtures.stare_centrum", str(directory), str(box), str(log), _COMMENT]
    done = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=60, check=False)
    assert done.returncode == 0, f"proces Centrum nie zginął przy komentarzu: {done.stderr.decode('utf-8', 'replace')}"


def old_centrum(directory: Path, box: Path, log: Path) -> OldCentrum:
    """Stare Centrum, którego przejście kolejki ``directory`` stoi w ``open_issue`` skrzynki ``box``."""

    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tools" / "lib")])}
    command = [sys.executable, "-m", "tests.fixtures.stare_centrum", str(directory), str(box), str(log), _OPENING]
    process = subprocess.Popen(
        command, cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    opening = box / _OPENING
    if not wait_for(lambda: opening.exists() or process.poll() is not None) or not opening.exists():
        process.kill()
        _output, errors = process.communicate(timeout=60)
        raise AssertionError(f"przejście starego Centrum nie doszło do open_issue: {errors.decode('utf-8', 'replace')}")
    return OldCentrum(process)


def _main(directory: Path, box: Path, log: Path, ending: str) -> int:
    """Przejście kolejki, którego proces kończy się po założeniu issue (``_OPENING``) albo po komentarzu (``_COMMENT``)."""

    def hold() -> None:
        (box / _OPENING).touch()
        sys.stdin.readline()

    def end() -> None:
        os._exit(0)

    shared = (
        SharedBox(box, before_opening=hold, after_opening=end) if ending == _OPENING else SharedBox(box, after_comment=end)
    )
    clock = ManualClock()
    outbox = queue_on(directory, shared, log, clock)
    outbox.resume()
    outbox.wait_delivered("", "kontrola-ilosci", timeout_s=60)
    return 1  # przejście skończyło się, zanim proces zginął


if __name__ == "__main__":
    raise SystemExit(_main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]))
