"""Exhaustively check how Przygotowanie pliku zbiorczego publishes the two period files.

The checker runs the real ``preparation_files.write_period_files()``, and with it the
real ``_publish()``, against an in-memory disk with Windows rename semantics. Each
filesystem call of the real code is one indivisible step. Before every step the
checker may let a second Uruchomienie procesu or Dad act first, make the call fail,
or kill the process. It tries every such schedule within the bounds of a scope,
re-running the code once per schedule, and checks two rules:

- NIENADPISYWANIE: no file or folder that someone else made is removed, replaced,
  or moved away.
- RAZEM_ALBO_ZADEN: when an Uruchomienie procesu has ended, the Folder okresu holds
  both of its period files or neither; a success leaves both and a stop leaves
  neither. The one allowed exception is a stop whose message names every file
  left and does not say that no file was created.

Nothing in the code is replaced: the checker gives ``write_period_files`` its own
``preparation_files.Disk``, whose workbook writing is a step that creates the staged
file and whose staging directory (made and removed) is a directory on the in-memory
disk whose removal is one step that may fail, as when OneDrive holds the folder. A filesystem call that the in-memory disk does not model
stops the check as LUKA MODELU instead of passing silently.

Schedules that reach a state already explored are cut short: the code is
deterministic, so a state (disk contents, what each Uruchomienie procesu has
observed so far, and the remaining bounds) has the same futures every time.
"""

from __future__ import annotations

import argparse
import builtins
import errno
import io
import os
import shutil
import stat as stat_module
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from rozliczenia import preparation_files
from rozliczenia.period_folder import PeriodFolder
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.template_file import TemplateFile
from rozliczenia.write_routes import Route
from eksplorator import Choices, Excuse, Interleaving, Kind, Thread, excuse_line, excused, gone_lines, schedules, verdict
import rozjazd_modelu

REPO_ROOT = Path(__file__).resolve().parents[4]

PERIOD = "08_14_09_2026"
DAD = "tata"
INTERNAL = "Rozliczenie wewnętrzne"
COLLECTIVE = "Plik zbiorczy"
VERIFIED_FILE = "preparation_files.py"

RunResult = Literal["SUKCES", "ZATRZYMANE", "PRZERWANE"]


class Crash(BaseException):
    """The process is killed before this step, e.g. Dad closes the console window."""


class Abort(BaseException):
    """The checker stops a schedule that reached an already explored state."""


class ModelGap(BaseException):
    """The real code made a filesystem call that the in-memory disk does not model."""


# --- In-memory disk with Windows semantics -------------------------------------------------------


@dataclass
class Entry:
    is_dir: bool
    owner: str


@dataclass(frozen=True)
class Broken:
    """How an Uruchomienie procesu that broke RAZEM_ALBO_ZADEN ended, each part of a risk's shape (``RiskShape``): the
    step before which the kill of its process ended it (``Pending.step``; ``None`` when it was not killed, or when the
    code caught the kill and the run did not end ``PRZERWANE``), its period files it left in the Folder okresu, and
    whether an ``os.unlink`` of the run failed."""

    killed_before: tuple[str, str] | None
    left: tuple[str, ...]
    unlink_failed: bool


@dataclass(frozen=True)
class Violation:
    rule: str
    signature: tuple[object, ...]
    text: str
    broken: Broken | None = None


class VirtualDisk:
    """Paths under ``root`` live only here; every entry records who created it."""

    def __init__(self, root: Path, short_names: Sequence[tuple[str, str]]) -> None:
        self.root_key = self.key(root)
        self.entries: dict[str, Entry] = {self.root_key: Entry(True, DAD)}
        self.short_names = short_names
        self.actor = DAD
        self.violations: list[Violation] = []

    @staticmethod
    def key(path: Any) -> str:
        return os.path.normcase(os.path.normpath(os.fsdecode(os.fspath(path))))

    def covers(self, path: object) -> bool:
        if not isinstance(path, (str, bytes, os.PathLike)):
            return False
        key = self.key(path)
        return key == self.root_key or key.startswith(self.root_key + os.sep)

    def label(self, path: object) -> str:
        """Short name for counterexamples, such as ``Folder okresu/…`` or ``katalog tymczasowy u1/…``."""

        relative = os.path.relpath(self.key(path), self.root_key).replace(os.sep, "/")
        for prefix, short in self.short_names:
            if relative == prefix or relative.startswith(prefix + "/"):
                return short + relative[len(prefix) :]
        return relative

    def entry(self, path: object) -> Entry | None:
        return self.entries.get(self.key(path))

    def snapshot(self) -> tuple[tuple[str, bool, str], ...]:
        return tuple(sorted((key, entry.is_dir, entry.owner) for key, entry in self.entries.items()))

    def _subtree(self, key: str) -> list[str]:
        return [other for other in self.entries if other == key or other.startswith(key + os.sep)]

    def _require_parent_dir(self, key: str) -> None:
        parent = self.entries.get(os.path.dirname(key))
        if parent is None or not parent.is_dir:
            raise FileNotFoundError(errno.ENOENT, "Nie znaleziono folderu nadrzędnego", key)

    def _record_foreign(self, key: str, entry: Entry, how: str) -> None:
        if entry.owner == self.actor:
            return
        kind = "folder" if entry.is_dir else "plik"
        self.violations.append(
            Violation(
                "NIENADPISYWANIE",
                ("NIENADPISYWANIE", how, entry.owner, self.label(key)),
                f"{self.actor} {how} {kind} {self.label(key)}, który należy do: {entry.owner}",
            )
        )

    def _remove(self, key: str, how: str) -> None:
        for other in self._subtree(key):
            self._record_foreign(other, self.entries.pop(other), how)

    def create(self, path: object, *, is_dir: bool, owner: str) -> None:
        key = self.key(path)
        if key in self.entries:
            raise FileExistsError(errno.EEXIST, "Plik już istnieje", key)
        self._require_parent_dir(key)
        self.entries[key] = Entry(is_dir, owner)

    # The calls below behave like os.* on Windows: rename never replaces, replace never replaces a folder.

    def stat(self, path: object) -> os.stat_result:
        entry = self.entry(path)
        if entry is None:
            raise FileNotFoundError(errno.ENOENT, "Nie znaleziono pliku", self.key(path))
        mode = stat_module.S_IFDIR | 0o777 if entry.is_dir else stat_module.S_IFREG | 0o666
        return os.stat_result((mode, 0, 0, 1, 0, 0, 0, 0, 0, 0))

    def rename(self, source: object, target: object, *, replace: bool) -> None:
        source_key, target_key = self.key(source), self.key(target)
        source_entry = self.entries.get(source_key)
        if source_entry is None:
            raise FileNotFoundError(errno.ENOENT, "Nie znaleziono pliku", source_key)
        self._require_parent_dir(target_key)
        target_entry = self.entries.get(target_key)
        if target_entry is not None:
            if not replace:
                raise FileExistsError(errno.EEXIST, "Nie można utworzyć pliku, który już istnieje", target_key)
            if target_entry.is_dir or source_entry.is_dir:
                raise PermissionError(errno.EACCES, "Odmowa dostępu", target_key)
            self._remove(target_key, "zastąpił")
        moved = {other: self.entries.pop(other) for other in self._subtree(source_key)}
        for other, entry in moved.items():
            self._record_foreign(other, entry, "przeniósł")
            self.entries[target_key + other[len(source_key) :]] = entry

    def unlink(self, path: object) -> None:
        key = self.key(path)
        entry = self.entries.get(key)
        if entry is None:
            raise FileNotFoundError(errno.ENOENT, "Nie znaleziono pliku", key)
        if entry.is_dir:
            raise PermissionError(errno.EACCES, "Odmowa dostępu", key)
        self._remove(key, "usunął")

    def mkdir(self, path: object) -> None:
        self.create(path, is_dir=True, owner=self.actor)

    def rmdir(self, path: object) -> None:
        key = self.key(path)
        entry = self.entries.get(key)
        if entry is None:
            raise FileNotFoundError(errno.ENOENT, "Nie znaleziono folderu", key)
        if not entry.is_dir:
            raise NotADirectoryError(errno.ENOTDIR, "To nie jest folder", key)
        if len(self._subtree(key)) > 1:
            raise OSError(errno.ENOTEMPTY, "Folder nie jest pusty", key)
        self._remove(key, "usunął")

    def remove_tree(self, path: object) -> None:
        key = self.key(path)
        if key in self.entries:
            self._remove(key, "usunął")


# --- Scheduler: one Uruchomienie procesu runs at a time, from one step to the next (``eksplorator.Interleaving``) ---


@dataclass
class Pending:
    call: str
    paths: tuple[str, ...]
    mutating: bool
    where: str
    killable: bool = True

    def describe(self, run: str) -> str:
        return f"{run}: {self.call}({' → '.join(self.paths)}) [{self.where}]"

    @property
    def step(self) -> tuple[str, str]:
        """The call and the function of ``preparation_files.py`` that makes it, without the line number."""

        return self.call, self.where.rpartition(" ")[2]


@dataclass
class Run(Thread):
    pending: Pending | None = None
    stopped_by: type[BaseException] | None = None
    result: RunResult | None = None
    error: str | None = None
    stop_text: str = ""
    gap: str | None = None
    killed_before: tuple[str, str] | None = None


def _current_run() -> Run | None:
    run = Interleaving.current()
    return run if isinstance(run, Run) else None


def _escaping() -> BaseException | None:
    """The exception that the run is unwinding from, unless it is the code's own stop (an ``Exception``).

    pytest's time limit and Ctrl+C belong to whoever runs the check, so the cleanup they pass through takes no step
    that the checker could pick, cut or kill: the check would go on exploring a tree that the exception has changed.
    """

    error = sys.exc_info()[1]
    return None if isinstance(error, Exception) else error


def _code_location() -> str:
    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename.endswith(VERIFIED_FILE):
            return f"{VERIFIED_FILE}:{frame.f_lineno} {frame.f_code.co_name}"
        frame = frame.f_back  # type: ignore[assignment]
    return "poza preparation_files.py"


class Scheduler(Interleaving[Run]):
    def __init__(self, disk: VirtualDisk) -> None:
        super().__init__()
        self.disk = disk
        self.probe_calls: list[str] | None = None

    def step(
        self,
        call: str,
        paths: Sequence[object],
        *,
        mutating: bool,
        perform: Callable[[], Any],
        killable: bool = True,
        seen: Callable[[], str] | None = None,
    ) -> Any:
        """Parks the calling Uruchomienie procesu until this step is picked, then performs it.

        A step that is not ``killable`` may still fail, but the process is never killed right before it. A read step
        records ``seen()``, what is on the disk at its path, instead of its answer.
        """

        if self.probe_calls is not None:
            self.probe_calls.append(call)
            return perform()
        run = _current_run()
        if run is None:
            raise ModelGap(f"{call} poza uruchomieniem procesu")
        if run.stopped_by is not None:
            raise run.stopped_by()
        if (escaping := _escaping()) is not None:
            raise escaping
        pending = Pending(call, tuple(self.disk.label(path) for path in paths), mutating, _code_location(), killable)
        run.pending = pending
        outcome = self.park(run)
        run.pending = None
        if outcome in ("crash", "abort"):
            run.stopped_by = Crash if outcome == "crash" else Abort
            if outcome == "crash":
                run.killed_before = pending.step
            raise run.stopped_by()
        if outcome == "fault":
            run.history.append(f"{call}!wstrzyknięty")
            raise PermissionError(errno.EACCES, "Plik jest używany przez inny proces (wstrzyknięty błąd)", pending.paths[-1])
        if seen is not None:
            run.history.append(f"{call}:{seen()}")
            return perform()
        try:
            answer = perform()
        except OSError as error:
            run.history.append(f"{call}!{type(error).__name__}")
            raise
        run.history.append(f"{call}={answer!r}" if not isinstance(answer, os.stat_result) else f"{call}={answer.st_mode}")
        return answer

    def _switch(self, thread: Run) -> None:
        self.disk.actor = thread.name
        super()._switch(thread)


# --- Interception of os.* for paths on the in-memory disk ------------------------------------------

_GUARDED_DISK: VirtualDisk | None = None


def _audit_real_filesystem(event: str, args: tuple[object, ...]) -> None:
    """A real filesystem call on a path of the in-memory disk bypassed the interception: LUKA MODELU.

    Native fast paths, such as ``_winapi.CopyFile2`` in ``shutil.copyfile`` on Windows,
    never reach the patched ``os`` functions. Without this hook they would fail on the
    missing real path with an ordinary ``OSError`` that the code treats as a write error.
    """

    disk = _GUARDED_DISK
    if disk is None:
        return
    for arg in args:
        if disk.covers(arg):
            raise ModelGap(f"{event}({disk.label(arg)}) nie jest modelowane")


sys.addaudithook(_audit_real_filesystem)


@contextmanager
def intercepted(disk: VirtualDisk, scheduler: Scheduler) -> Iterator[None]:
    """Routes os calls for paths under the disk root through the scheduler; other paths are untouched."""

    originals: list[tuple[Any, str, Any]] = []

    def patch(owner: Any, name: str, replacement: Any) -> None:
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def read_call(call: str, real: Callable[..., Any], answer: Callable[[object], Any]) -> Callable[..., Any]:
        # The run records what is at the path, not the answer: pathlib asks os.stat on Python 3.11 and 3.12 but
        # os.path.exists and os.path.islink on 3.14, whose answers say less. With the answer in the state, 3.14 merged
        # states that 3.12 kept apart and explored 6640 schedules of dwa-uruchomienia instead of 9798.
        def wrapper(path: Any, *args: Any, **kwargs: Any) -> Any:
            if not disk.covers(path):
                return real(path, *args, **kwargs)
            label = f"{call} bez dowiązań" if kwargs.get("follow_symlinks") is False else call
            return scheduler.step(label, (path,), mutating=False, perform=lambda: answer(path), seen=lambda: what_is_at(path))

        return wrapper

    def what_is_at(path: object) -> str:
        entry = disk.entry(path)
        return "brak" if entry is None else "folder" if entry.is_dir else "plik"

    def write_call(call: str, real: Callable[..., Any], apply: Callable[..., None], path_count: int) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            paths = args[:path_count]
            covered = [disk.covers(path) for path in paths]
            if not any(covered):
                return real(*args, **kwargs)
            if not all(covered):
                raise ModelGap(f"{call} między dyskiem w pamięci a prawdziwym dyskiem")
            return scheduler.step(call, paths, mutating=True, perform=lambda: apply(*paths))

        return wrapper

    def unmodeled(call: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if args and disk.covers(args[0]):
                raise ModelGap(f"{call}({disk.label(args[0])}) nie jest modelowane")
            return real(*args, **kwargs)

        return wrapper

    def exists(path: object) -> bool:
        return disk.entry(path) is not None

    def is_dir(path: object) -> bool:
        entry = disk.entry(path)
        return entry is not None and entry.is_dir

    def is_file(path: object) -> bool:
        entry = disk.entry(path)
        return entry is not None and not entry.is_dir

    # Path.exists/is_symlink/rename/unlink/mkdir reach these on Python 3.11 to 3.14, on Windows and elsewhere.
    patch(os, "stat", read_call("os.stat", os.stat, disk.stat))
    patch(os, "lstat", read_call("os.lstat", os.lstat, disk.stat))
    patch(os.path, "exists", read_call("os.path.exists", os.path.exists, exists))
    patch(os.path, "lexists", read_call("os.path.lexists", os.path.lexists, exists))
    patch(os.path, "isdir", read_call("os.path.isdir", os.path.isdir, is_dir))
    patch(os.path, "isfile", read_call("os.path.isfile", os.path.isfile, is_file))
    patch(os.path, "islink", read_call("os.path.islink", os.path.islink, lambda path: False))
    patch(os, "rename", write_call("os.rename", os.rename, lambda s, t: disk.rename(s, t, replace=False), 2))
    patch(os, "replace", write_call("os.replace", os.replace, lambda s, t: disk.rename(s, t, replace=True), 2))
    patch(os, "unlink", write_call("os.unlink", os.unlink, disk.unlink, 1))
    patch(os, "remove", write_call("os.remove", os.remove, disk.unlink, 1))
    patch(os, "mkdir", write_call("os.mkdir", os.mkdir, disk.mkdir, 1))
    patch(os, "rmdir", write_call("os.rmdir", os.rmdir, disk.rmdir, 1))
    for name in ("open", "scandir", "listdir", "link", "symlink", "chmod", "utime", "truncate"):
        if hasattr(os, name):
            patch(os, name, unmodeled(f"os.{name}", getattr(os, name)))
    patch(builtins, "open", unmodeled("open", builtins.open))
    patch(io, "open", unmodeled("io.open", io.open))
    global _GUARDED_DISK
    _GUARDED_DISK = disk
    try:
        yield
    finally:
        _GUARDED_DISK = None
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


# --- Steps of the code outside the os calls: workbook writing and the staging directory -----------------


def period_disk(disk: VirtualDisk, scheduler: Scheduler) -> preparation_files.Disk:
    """The steps of ``preparation_files.Disk`` on the in-memory disk: the staging directory and workbook writing.

    Workbook writing is one step that creates the staged file and returns its route, as ``_create_file`` returns it for
    the metrics record (``RouteCounts``). A killed process leaves the staging directory behind: the removal of a run
    that was killed or cut short takes no step. The removal fails like the real one, as when OneDrive holds the folder:
    the folder stays and the failure is swallowed. A kill during the removal is not explored: the run's outcome is
    already decided, as with a kill while the result is shown, which the checker does not explore either.
    """

    def make_staging(prefix: str, directory: Path) -> Path:
        run = _current_run()
        if run is None:
            raise ModelGap("katalog tymczasowy poza uruchomieniem procesu")
        path = directory / f"{prefix}{run.name}"
        disk.mkdir(path)
        return path

    def create_file(template: TemplateFile, target: Path, rows: object) -> Route:
        scheduler.step(
            "zapis skoroszytu",
            (target,),
            mutating=True,
            perform=lambda: disk.create(target, is_dir=False, owner=disk.actor),
        )
        return Route.COPY

    def remove_staging(path: Path) -> None:
        if not disk.covers(path):
            raise ModelGap("usunięcie katalogu spoza dysku w pamięci")
        with suppress(OSError):
            scheduler.step(
                "usunięcie katalogu tymczasowego",
                (path,),
                mutating=True,
                perform=lambda: disk.remove_tree(path),
                killable=False,
            )

    return preparation_files.Disk(make_staging=make_staging, create_file=create_file, remove_staging=remove_staging)


def probe_interception() -> list[str]:
    """Problems if the pathlib calls used by preparation_files.py bypass the in-memory disk on this Python."""

    layout = make_layout()
    disk = VirtualDisk(layout.disk_root, short_names(0))
    scheduler = Scheduler(disk)
    scheduler.probe_calls = []
    folder = layout.disk_root / "folder"
    problems: list[str] = []

    def expect(description: str, condition: Callable[[], bool]) -> None:
        before = len(scheduler.probe_calls or [])
        try:
            holds = condition()
        except OSError as error:
            holds = False
            description += f" ({type(error).__name__})"
        if not holds or len(scheduler.probe_calls or []) == before:
            problems.append(f"{description} nie przechodzi przez dysk w pamięci na Pythonie {sys.version.split()[0]}")

    moved = layout.disk_root / "przeniesiony"

    def make_folder() -> bool:
        folder.mkdir()
        return disk.entry(folder) is not None

    def rename_folder() -> bool:
        folder.rename(moved)
        return disk.entry(moved) is not None

    def rename_file() -> bool:
        disk.create(moved / "plik", is_dir=False, owner=DAD)
        os.rename(moved / "plik", moved / "inny")
        return disk.entry(moved / "inny") is not None

    def unlink_file() -> bool:
        (moved / "inny").unlink(missing_ok=True)
        return disk.entry(moved / "inny") is None

    def native_copy_is_a_gap() -> None:
        try:
            shutil.copyfile(layout.disk_root / "a", layout.disk_root / "b")
        except ModelGap:
            return
        except OSError as error:
            problems.append(f"shutil.copyfile omija dysk w pamięci bez LUKI MODELU ({type(error).__name__})")
            return
        problems.append("shutil.copyfile na dysku w pamięci nie zgłasza LUKI MODELU")

    with intercepted(disk, scheduler):
        native_copy_is_a_gap()
        expect("Path.exists dla brakującego folderu", lambda: not folder.exists())
        expect("Path.mkdir", make_folder)
        expect("Path.exists dla istniejącego folderu", folder.exists)
        expect("Path.is_symlink", lambda: not folder.is_symlink())
        expect("Path.rename", rename_folder)
        expect("os.rename", rename_file)
        expect("Path.unlink", unlink_file)
    return problems


# --- Scopes, initial states and Dad's actions -----------------------------------------------------


NO_FOLDER = "brak Folderu okresu"
EMPTY_FOLDER = "pusty Folder okresu"
DAD_INTERNAL = "Folder okresu z plikiem taty o nazwie Rozliczenia wewnętrznego"
DAD_COLLECTIVE = "Folder okresu z plikiem taty o nazwie Pliku zbiorczego"
ALL_STATES = (NO_FOLDER, EMPTY_FOLDER, DAD_INTERNAL, DAD_COLLECTIVE)


@dataclass(frozen=True)
class Scope:
    name: str
    runs: int
    initial_states: tuple[str, ...]
    dad_actions: int
    faults: int
    crashes: int

    def describe(self) -> str:
        return (
            f"uruchomienia równocześnie: {self.runs}, stany początkowe: {len(self.initial_states)}, "
            f"działania taty ≤ {self.dad_actions}, błędy systemu plików ≤ {self.faults}, "
            f"przerwania procesu ≤ {self.crashes}"
        )


SCOPES = {
    scope.name: scope
    for scope in (
        Scope("jedno-uruchomienie", 1, ALL_STATES, dad_actions=2, faults=2, crashes=1),
        Scope("dwa-uruchomienia", 2, ALL_STATES, dad_actions=1, faults=1, crashes=1),
    )
}

@dataclass(frozen=True)
class RiskShape:
    """The exact shape of an accepted risk or a known finding of RAZEM_ALBO_ZADEN, each part taken from its story and
    each required, so an entry cannot match on fewer of them (#920):

    - ``killed_before``: the steps before which the process was killed (``Pending.step``); a run that was not killed
      (``None``) is outside every shape;
    - ``left``: the run's period files left in the Folder okresu, exactly;
    - ``unlink_failed``: whether an ``os.unlink`` of the run failed; a rollback whose ``os.unlink`` failed is the case
      of issue #92 (``BLAD_ZAPISU_POZOSTAL_PLIK``), which ADR 0005 does not cover.

    Each part has in ``check_publication_mutations.BOUNDARIES`` a broken variant just outside it, which must give a new
    violation (``tests/test_mutacje_skilli.py``)."""

    killed_before: frozenset[tuple[str, str]]
    left: tuple[str, ...]
    unlink_failed: bool

    def __post_init__(self) -> None:
        if not self.killed_before or not self.left:
            raise ValueError("kształt bez kroku zabicia albo bez plików, które zostały")

    def holds(self, broken: Broken) -> bool:
        return (
            broken.killed_before in self.killed_before
            and broken.left == self.left
            and broken.unlink_failed == self.unlink_failed
        )


# Breaks of a rule that were consciously accepted; each names the decision that accepted it. Its shape judges a
# violation's ``broken``.
ACCEPTED_RISKS: tuple[Excuse[RiskShape], ...] = (
    Excuse(
        "ADR 0005",
        "RAZEM_ALBO_ZADEN",
        "proces zamknięty między dwoma os.rename w _publish albo po nieudanym drugim os.rename, zanim wycofanie usunęło "
        "pierwszy plik, zostawia w istniejącym Folderze okresu samo Rozliczenie wewnętrzne (ADR 0005, oba przypadki)",
        RiskShape(
            killed_before=frozenset({("os.rename", "_publish"), ("os.unlink", "_publish")}),
            left=(INTERNAL,),
            unlink_failed=False,
        ),
        after=("jedno-uruchomienie", "dwa-uruchomienia"),
    ),
)

# Findings in the current code. They are reported on every run; any other violation fails the check.
KNOWN_FINDINGS: tuple[Excuse[RiskShape], ...] = ()


@dataclass(frozen=True)
class Layout:
    disk_root: Path
    periods_directory: Path
    files: preparation_files.PeriodFiles


def make_layout() -> Layout:
    disk_root = Path(tempfile.gettempdir()).resolve() / f"publikacja-plikow-okresu-{os.getpid()}-nie-istnieje"
    if disk_root.exists():
        raise RuntimeError(f"Katalog dysku w pamięci istnieje na prawdziwym dysku: {disk_root}")
    periods_directory = disk_root / "Rozliczenia"
    # As in prepare_collective_file(): the value is built only from a checked period.
    files = preparation_files.PeriodFiles(
        internal_template=TemplateFile.internal_settlement(disk_root / "config" / "Wzorzec rozliczenia wewnętrznego.xlsx"),
        collective_template=TemplateFile.collective_file(disk_root / "config" / "Wzorzec pliku zbiorczego.xlsx"),
        folder=PeriodFolder(periods_directory, parse_period_token(PERIOD)),
    )
    return Layout(disk_root, periods_directory, files)


def short_names(run_count: int) -> list[tuple[str, str]]:
    staging = f"Rozliczenia/.{PERIOD}.staging-"
    names = [(f"Rozliczenia/{PERIOD}", "Folder okresu")]
    for index in range(1, run_count + 1):
        names.append((f"{staging}u{index}/{PERIOD}", f"katalog tymczasowy u{index}"))
        names.append((f"{staging}u{index}", f"nadrzędny katalog tymczasowy u{index}"))
    return names


def prepare_disk(disk: VirtualDisk, layout: Layout, initial_state: str) -> None:
    disk.create(layout.periods_directory, is_dir=True, owner=DAD)
    if initial_state == NO_FOLDER:
        return
    disk.create(layout.files.folder.directory, is_dir=True, owner=DAD)
    if initial_state == DAD_INTERNAL:
        disk.create(layout.files.folder.internal_settlement, is_dir=False, owner=DAD)
    elif initial_state == DAD_COLLECTIVE:
        disk.create(layout.files.folder.collective_file, is_dir=False, owner=DAD)


def dad_actions(disk: VirtualDisk, layout: Layout) -> list[tuple[str, Callable[[], None]]]:
    """What Dad, or OneDrive acting for him, may do in the Folder okresu while a process runs."""

    if disk.entry(layout.files.folder.directory) is None:
        return [
            (
                "tata zakłada Folder okresu",
                lambda: disk.create(layout.files.folder.directory, is_dir=True, owner=DAD),
            )
        ]
    def save_dad_file(target: Path) -> Callable[[], None]:
        return lambda: disk.create(target, is_dir=False, owner=DAD)

    return [
        (f"tata zapisuje własny plik {target.name} w Folderze okresu", save_dad_file(target))
        for target in (layout.files.folder.internal_settlement, layout.files.folder.collective_file)
        if disk.entry(target) is None
    ]


# --- One schedule ---------------------------------------------------------------------------------


@dataclass
class Execution:
    trace: list[str]
    violations: list[Violation]
    gaps: list[str]
    successes: int
    undisturbed_success: bool
    cut: bool
    disturbances: int


def _run_body(run: Run, layout: Layout, steps: preparation_files.Disk) -> None:
    try:
        preparation_files.write_period_files(layout.files, [], [], disk=steps)
        run.result = "SUKCES"
    except (Crash, Abort):
        run.result = "PRZERWANE"
    except ModelGap as gap:
        run.gap = str(gap)
        run.result = "PRZERWANE"
    # pytest's time limit and Ctrl+C are no stop of the code: they leave the greenlet for the checker.
    except Exception as error:  # noqa: BLE001 - every stop of the code counts, whatever its type
        run.result = "ZATRZYMANE"
        message = getattr(error, "message", None)
        run.error = f"{type(error).__name__} {message.code}" if message is not None else type(error).__name__
        run.stop_text = message.text if message is not None else str(error)


# Celowa kopia zdania Komunikatu, które tata czyta (``preparation_messages``, docs/agents/skille.md, „Co wyrocznia
# bierze z src”): Zatrzymanie, które mówi je przy pliku okresu na dysku, okłamuje tatę, także gdy zdanie zmieniono w src.
NOTHING_CREATED = "Nie utworzono żadnego pliku"


def _period_files(layout: Layout) -> dict[str, Path]:
    return {INTERNAL: layout.files.folder.internal_settlement, COLLECTIVE: layout.files.folder.collective_file}


def _owned_period_files(disk: VirtualDisk, layout: Layout, run: Run) -> tuple[str, ...]:
    return tuple(
        name
        for name, path in _period_files(layout).items()
        if (entry := disk.entry(path)) is not None and entry.owner == run.name
    )


def _stop_names_files_left(run: Run, layout: Layout, owned: tuple[str, ...]) -> bool:
    """The stop tells Dad the truth: it names every file left and does not claim that none was created."""

    paths = _period_files(layout)
    return NOTHING_CREATED not in run.stop_text and all(f"plik {paths[name].name}" in run.stop_text for name in owned)


def _razem_albo_zaden(run: Run, layout: Layout, owned: tuple[str, ...]) -> Violation | None:
    allowed = {
        "SUKCES": ((INTERNAL, COLLECTIVE),),
        "ZATRZYMANE": ((),),
        "PRZERWANE": ((), (INTERNAL, COLLECTIVE)),
    }[run.result or "PRZERWANE"]
    if owned in allowed:
        return None
    if run.result == "ZATRZYMANE" and _stop_names_files_left(run, layout, owned):
        return None
    left = ", ".join(owned) if owned else "żadnego pliku"
    unlink_failed = any(entry.startswith("os.unlink!") for entry in run.history)
    return Violation(
        "RAZEM_ALBO_ZADEN",
        ("RAZEM_ALBO_ZADEN", run.result, owned, unlink_failed, run.killed_before),
        f"{run.name} kończy się: {run.result}, a w Folderze okresu zostaje z jego plików: {left}",
        Broken(run.killed_before if run.result == "PRZERWANE" else None, owned, unlink_failed),
    )


def execute(scope: Scope, choices: Choices, visited: set[object]) -> Execution:
    trace: list[str] = []
    layout = make_layout()
    disk = VirtualDisk(layout.disk_root, short_names(scope.runs))
    scheduler = Scheduler(disk)
    initial_state = scope.initial_states[choices.choose(len(scope.initial_states))]
    prepare_disk(disk, layout, initial_state)
    trace.append(f"stan początkowy: {initial_state}")
    runs = [Run(f"u{index}") for index in range(1, scope.runs + 1)]
    dad_left, faults_left, crashes_left = scope.dad_actions, scope.faults, scope.crashes
    disturbances = 0
    cut = False

    steps = period_disk(disk, scheduler)
    with intercepted(disk, scheduler):
        for run in runs:
            scheduler.spawn(run, partial(_run_body, run, layout, steps))
            scheduler.settle()
        while True:
            scheduler.settle()
            parked = [run for run in runs if run.status == "parked"]
            if not parked:
                break
            state = (
                disk.snapshot(),
                tuple((run.status, tuple(run.history), run.result) for run in runs),
                dad_left,
                faults_left,
                crashes_left,
            )
            if not choices.replaying and state in visited:
                cut = True
                for run in parked:
                    scheduler.release(run, "abort")
                continue
            visited.add(state)
            options: list[tuple[str, Run | None, Callable[[], None] | None, str]] = []
            for run in parked:
                assert run.pending is not None
                step = run.pending.describe(run.name)
                options.append(("ok", run, None, step))
                if run.pending.mutating and faults_left:
                    options.append(("fault", run, None, f"{step} → błąd: plik używany przez inny proces"))
                if run.pending.mutating and run.pending.killable and crashes_left:
                    options.append(("crash", run, None, f"{run.name}: proces zamknięty tuż przed krokiem {step}"))
            if dad_left:
                options.extend(("dad", None, action, text) for text, action in dad_actions(disk, layout))
            kind, chosen, action, text = options[choices.choose(len(options))]
            trace.append(text)
            disturbances += kind != "ok"
            if kind == "dad":
                assert action is not None
                disk.actor = DAD
                action()
                dad_left -= 1
                continue
            assert chosen is not None
            faults_left -= kind == "fault"
            crashes_left -= kind == "crash"
            scheduler.release(chosen, kind)

    violations = list(disk.violations)
    gaps = [f"{run.name}: {run.gap}" for run in runs if run.gap]
    successes = 0
    if cut:
        trace.append("dalej ten sam stan co w harmonogramie sprawdzonym wcześniej")
    if not cut:
        for run in runs:
            detail = f" ({run.error})" if run.error else ""
            trace.append(f"{run.name} kończy się: {run.result}{detail}")
            successes += run.result == "SUKCES"
            violation = _razem_albo_zaden(run, layout, _owned_period_files(disk, layout, run))
            if violation is not None:
                violations.append(violation)
    undisturbed_success = not cut and not disturbances and runs[0].result == "SUKCES"
    return Execution(trace, violations, gaps, successes, undisturbed_success, cut, disturbances)


# --- Exploration and report ----------------------------------------------------------------------


@dataclass
class ScopeReport:
    scope: Scope
    schedules: int = 0
    states: int = 0
    successes: int = 0
    undisturbed_successes: int = 0
    seconds: float = 0.0
    counterexamples: dict[tuple[object, ...], tuple[Violation, list[str], tuple[int, int]]] = field(
        default_factory=dict
    )
    gaps: dict[str, list[str]] = field(default_factory=dict)


def explore(scope: Scope) -> ScopeReport:
    report = ScopeReport(scope)
    visited: set[object] = set()
    started = time.perf_counter()
    for execution in schedules(lambda choices: execute(scope, choices, visited)):
        report.schedules += 1
        report.successes += execution.successes
        report.undisturbed_successes += execution.undisturbed_success
        for violation in execution.violations:
            # Keep the simplest counterexample: fewest failures, kills and Dad actions, then fewest steps.
            rank = (execution.disturbances, len(execution.trace))
            known = report.counterexamples.get(violation.signature)
            if known is None or rank < known[2]:
                report.counterexamples[violation.signature] = (violation, execution.trace, rank)
        for gap in execution.gaps:
            report.gaps.setdefault(gap, execution.trace)
    report.states = len(visited)
    report.seconds = time.perf_counter() - started
    return report


@dataclass(frozen=True)
class Outcome:
    lines: list[str]
    exit_code: int


VERDICT = "PUBLIKACJA"
GAP_REASON = ": kod używa wywołania, którego dysk w pamięci nie modeluje."


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines = ["Publikacja plików okresu (Przygotowanie pliku zbiorczego): sprawdzenie wyczerpujące", ""]
    new = gaps = vacuous = 0
    counts: dict[Kind, int] = {"known": 0, "accepted": 0}
    shown: dict[tuple[object, ...], str] = {}
    excuses_shown: set[tuple[str, str]] = set()
    for report in reports:
        lines.append(f"zakres {report.scope.name}: {report.scope.describe()}")
        lines.append(
            f"  harmonogramy: {report.schedules}, różne stany: {report.states}, "
            f"udane publikacje: {report.successes}, czas: {report.seconds:.1f} s"
        )
        if report.undisturbed_successes == 0:
            vacuous += 1
            lines.append("  BRAK_PUBLIKACJI: bez błędów, przerwań i taty u1 ani razu nie opublikowało plików okresu.")
        for gap, trace in report.gaps.items():
            gaps += 1
            lines.append(f"  LUKA MODELU: {gap}")
            lines.extend(f"    {number}. {step}" for number, step in enumerate(trace, start=1))
        for signature, (violation, trace, _) in sorted(report.counterexamples.items(), key=lambda item: str(item[0])):
            found = excused(violation.rule, violation.broken, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
            if found is not None:
                excuses_shown.add((found[1].name, report.scope.name))
            if found is not None and not strict:
                counts[found[0]] += signature not in shown
                lines.append(f"  {excuse_line(*found)}")
            else:
                new += signature not in shown
                lines.append(f"  NARUSZENIE {violation.rule}: {violation.text}")
            if signature in shown:
                lines.append(f"    kontrprzykład jak w zakresie {shown[signature]}")
                continue
            shown[signature] = report.scope.name
            lines.extend(f"    {number}. {step}" for number, step in enumerate(trace, start=1))
        lines.append("")
    finished = [report.scope.name for report in reports if not report.gaps]
    disappeared = gone_lines(finished, excuses_shown, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
    lines.extend(disappeared)
    verdict_line, code = verdict(
        VERDICT,
        new=new + vacuous,
        gone=len(disappeared),
        known=counts["known"],
        accepted=counts["accepted"],
        gaps=gaps,
        gap_reason=GAP_REASON,
    )
    lines.append(verdict_line)
    return Outcome(lines, code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exhaustive check of how Przygotowanie publishes the period files.")
    parser.add_argument("--scope", choices=sorted(SCOPES), action="append", help="one scope; default: all")
    parser.add_argument("--strict", action="store_true", help="report known findings and accepted risks as violations too")
    arguments = parser.parse_args(argv)
    drift = rozjazd_modelu.rozjazd(Path(__file__).resolve().parents[1], REPO_ROOT)
    if (failure := rozjazd_modelu.porazka_w_ci(drift, VERDICT)) is not None:
        print(failure)
        return 1
    problems = probe_interception()
    if problems:
        print("\n".join(f"LUKA MODELU: {problem}" for problem in problems))
        verdict_line, code = verdict(VERDICT, new=0, gone=0, gaps=len(problems), gap_reason=GAP_REASON)
        print(verdict_line)
        return code
    reports = [explore(SCOPES[name]) for name in (arguments.scope or SCOPES)]
    outcome = summarize(reports, strict=arguments.strict)
    if drift is not None:
        print(f"UWAGA: {drift}\n")
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
