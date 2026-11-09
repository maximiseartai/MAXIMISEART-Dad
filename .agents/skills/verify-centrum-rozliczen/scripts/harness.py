"""Files through which the drive and the served Centrum talk: every name of the harness's protocol in the run root.

The drive (``drive/``) writes and reads them in the run root, and ``serve_centrum.py`` (and the restart shim of
``create_centrum_fixture.py``) reads and writes them, so both sides take the names from here: a name changed on one side
only would leave the drive writing a file no one reads, or reading a log no one writes, and a check that nothing opens
would pass without a failure. ``centrum_self_test.py`` holds both sides to it: no other script spells a name of this
module, and the scripted boundaries of the served side take their files from here in the round trips its docstring
lists (``File.EFENIX_ADDRESS`` and ``File.SERVER``, which the served side writes as it starts, only the run itself
holds, loudly).
These are the harness's own names, not files of Dad's: the drive spells a name of the product (a Komunikat, a fact of the
Logi) itself, as an oracle (``docs/agents/skille.md``).
Only the standard library: the restart shim imports it before it runs ``serve_centrum.py``.
"""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
import re
import time

_BOX = "skrzynka-zgloszen"
_ARCHIVES = "skrzynka-archiwum"
_GITHUB = "github"
_REJECTS = "odrzuca-"
_EFENIX = "efenix"


class Pace(Enum):
    """A step the served Centrum slows down while ``<root>/pacing/<value>-ms.txt`` holds a number of milliseconds."""

    REPORT_BOX = "skrzynka"  # the skrzynka Zgłoszeń, before it opens an issue
    TEMPLATES = "szablony"  # each Szablon pracownika of a Przebieg rozliczeń RUN, before it is written
    UPDATE = "aktualizacja"  # the Aktualizacja narzędzia, before it looks for Git
    INSTALL = "instalacja"  # each installation of libraries, before it starts
    RESTART = "ponowny-start"  # the restarted Centrum of the run's clone, before it serves

    def file(self, root: Path) -> Path:
        return root / "pacing" / f"{self.value}-ms.txt"

    def set(self, root: Path, ms: int) -> Path:
        """The drive turns the pacing on; it turns it off by removing the returned file."""

        path = self.file(root)
        path.parent.mkdir(exist_ok=True)
        path.write_text(str(ms), encoding="utf-8")
        return path

    def wait(self, root: Path) -> None:
        """The served side waits as long as the drive asked, or not at all without the file."""

        path = self.file(root)
        if path.exists():
            time.sleep(int(path.read_text(encoding="utf-8")) / 1000)


class Switch(Enum):
    """A failure the served Centrum scripts while this file exists; the drive turns it off by removing the file."""

    BOX_OFFLINE = f"{_BOX}/brak-sieci"  # the skrzynka Zgłoszeń and its Archiwa are out of reach
    KEY_REFUSED = f"{_BOX}/odmawia-klucza"  # the skrzynka refuses the key for every question (GitHub's 401)
    ARCHIVE_REFUSED = f"{_BOX}/odmawia-archiwum"  # every step of an Archiwum is refused (GitHub's 403)
    GITHUB_OFFLINE = f"{_GITHUB}/brak-sieci"  # GitHub's Wydania are out of reach
    REGISTER_FAULT = "awaria/odczyt-rejestru"  # reading the Rejestr zleceń raises an exception the process does not expect

    def file(self, root: Path) -> Path:
        return root / self.value

    def on(self, root: Path) -> Path:
        path = self.file(root)
        path.parent.mkdir(exist_ok=True)
        path.touch()
        return path

    def is_on(self, root: Path) -> bool:
        return self.file(root).exists()


def rejects(root: Path, label: str) -> Path:
    """While this file exists, the skrzynka rejects the content of every new issue with ``label`` and of every comment to
    one (GitHub's 422)."""

    return root / _BOX / f"{_REJECTS}{label}"


class Log(Enum):
    """A JSON line the served Centrum appends for each event the drive counts."""

    DIALOGS = "dialogs.jsonl"  # the title of each file or folder picker
    OPENED = "opened.jsonl"  # the path of each file or folder opened in Excel or Explorer
    REPORT_QUESTIONS = f"{_BOX}-zapytania.jsonl"  # the label of each question for issues, closed ones included
    RELEASE_QUESTIONS = f"{_GITHUB}/zapytania-wydan.jsonl"  # each question for the published Wydania

    def file(self, root: Path) -> Path:
        return root / self.value

    def append(self, root: Path, record: dict[str, str]) -> None:
        """The served side appends ``record``; it holds its own lock, as two threads may log at once."""

        path = self.file(root)
        path.parent.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")


class File(Enum):
    """A file of one side's answer that the other side reads; no file is the default of the module doc of
    ``serve_centrum.py``."""

    # The drive writes these, the served Centrum reads them.
    PICKER_ANSWER = "picker/answer.txt"  # the path the next picker answers with
    MAIN_COMMIT = f"{_GITHUB}/main-commit.txt"  # the commit of the newest Wydanie on GitHub
    RELEASE_TAG = f"{_GITHUB}/wydanie.txt"  # its tag
    RELEASES = f"{_GITHUB}/wydania.json"  # the published Wydania in the shape of GitHub's list
    TOOL_COMMIT = f"{_GITHUB}/tool-commit.txt"  # the tool's own commit, once Dad updated it
    CLOUD_ONLY = "onedrive/tylko-w-chmurze.txt"  # the full paths of the files „tylko online” in OneDrive
    CLOCK_MOVE = "zegar/przesuniecie-min.txt"  # the minutes Centrum's clock moved forward
    # The served Centrum writes these, the drive reads them.
    CLOCK_DIED = "zegar/budzik-padl.txt"  # the traceback of the clock's wake-up thread that died
    EFENIX_ADDRESS = f"{_EFENIX}/adres.txt"  # the address of the Atrapa efenix
    SERVER = "server.json"  # the pid and port of the served Centrum

    def file(self, root: Path) -> Path:
        return root / self.value

    def write(self, root: Path, text: str) -> Path:
        path = self.file(root)
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def report_box(root: Path) -> Path:
    """The skrzynka Zgłoszeń: one ``<number>.json`` per issue (``issue_file``)."""

    return root / _BOX


def issue_file(root: Path, number: int) -> Path:
    return report_box(root) / f"{number}.json"


_COMMENT_ADDRESS = re.compile(rf"{_BOX}/(\d+)\.json#komentarz-(\d+)")


def comment_address(number: int, position: int) -> str:
    """The address of comment ``position`` (from 1) of issue ``number``: within the run root, as a Zgłoszenie holds no
    full path."""

    return f"{_BOX}/{number}.json#komentarz-{position}"


def comment_position(address: str) -> tuple[int, int] | None:
    """The issue number and the comment's position of ``address`` (``comment_address``); ``None`` for another one."""

    found = _COMMENT_ADDRESS.fullmatch(address)
    return None if found is None else (int(found[1]), int(found[2]))


def archive_listing(root: Path) -> Path:
    """Each Archiwum Logów okresu (id, tag, title, description) and its files (id, name, label)."""

    return root / _ARCHIVES / "archiwa.json"


def archive_file(root: Path, tag: str, name: str) -> Path:
    """The bytes of the file ``name`` of the Archiwum ``tag`` as Centrum uploaded them (gzip)."""

    return root / _ARCHIVES / tag / name


def last_file_id(root: Path) -> Path:
    """The last id a file of an Archiwum got, also one removed since."""

    return root / _ARCHIVES / "ostatni-plik.txt"


def efenix_files(root: Path) -> Path:
    """Where the served Centrum writes the Plik zbiorczy of the Atrapa efenix and its address (``File.EFENIX_ADDRESS``),
    outside the folder okresów."""

    return root / _EFENIX
