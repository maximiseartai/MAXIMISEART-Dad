"""Files through which the drive steers the hooks of the served Centrum: pacing and the fault of reading the Rejestr.

The drive (``drive/``) writes them in the run root and ``serve_centrum.py`` (and the restart shim of
``create_centrum_fixture.py``) reads them, so both sides take the names from here: a name changed on one side only
would leave the drive writing a file no one reads, and the pacing it needs would go away without a failure.
Only the standard library: the restart shim imports it before it runs ``serve_centrum.py``.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import time


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


def register_fault(root: Path) -> Path:
    """While this file exists, reading the Rejestr zleceń raises an exception the process does not expect."""

    return root / "awaria" / "odczyt-rejestru"
