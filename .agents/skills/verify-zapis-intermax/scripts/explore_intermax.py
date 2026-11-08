"""Exhaustively check how Uporządkowanie INTERMAX and Przywracanie Kopii INTERMAX replace the Rejestr zleceń.

The checker runs the real ``intermax_ordering.order_register()`` and the real ``intermax_restore.restore()`` (#472),
which both replace INTERMAX through ``intermax_replace.replace_register`` (#716), on a synthetic INTERMAX
(``tests/fixtures/intermax.py``) in a real folder, next to a Kopie folder that already holds ``KEPT`` older Kopie of
both names, so that their order by name differs from their order in time. The restore brings back the oldest of them, a
real workbook. A second restore starts as one in the same second as an earlier restore: the Kopie folder also holds the
Kopia that the replace would name, so its ``Disk.create`` raises ``FileExistsError``. Nine steps of the code are
points where the checker picks what happens first:

- after ``Register.read`` has read INTERMAX (in the restore: after ``workbook_content`` has read it);
- ``workbook_files.is_open_in_excel`` on INTERMAX (in ``check``, in ``Register.read`` and before the Kopia);
- ``Disk.write`` of the temporary file next to INTERMAX, which may raise ``OSError``;
- the check of that file (``Register.check``), which may find it does not match (``WriteMismatch``); the restore
  compares bytes and has no such point;
- ``Disk.exists`` of the Kopia's name, which may raise ``OSError`` (a Kopie folder it cannot search);
- ``Disk.create`` of the Kopia (in the restore: the Kopia of the current state), which may raise ``OSError``;
- ``Disk.replace`` of the temporary file over INTERMAX (the ``replace`` that ``replace_register`` gives
  ``workbook_save.write_atomically``), which may raise ``OSError``, may be refused by OneDrive (``PermissionError``
  without the ``~$`` lock file), and always raises ``PermissionError`` while Excel has INTERMAX open, as on Windows;
- the pause between two attempts of that replace (``Waiting.pause``), which may last the whole retry time;
- ``Disk.remove`` of an older Kopia after the replace, which may raise ``OSError``.

At each point a worker may first save a change to INTERMAX on another computer, which OneDrive puts in place as a new
file (not while Excel holds INTERMAX: OneDrive then keeps a conflict copy beside it), Dad may open INTERMAX in Excel
(the ``~$`` lock file), the step may fail, or the process may die. The checker tries every such schedule within the
bounds and checks:

- BEZ_UTRATY_ZMIAN: when the run replaces INTERMAX, it replaces the bytes it read. ADR 0019: the run „zmienia tylko
  Surowe zlecenia”, and every other part and row „zostają bajt w bajt”.
- KOPIA_ZASTAPIONEGO: when the run replaces INTERMAX, a Kopia INTERMAX holds exactly the bytes it replaced
  (ADR 0019: „Przed każdą podmianą powstaje Kopia INTERMAX”).
- ZATRZYMANIE_BEZ_SLADU: a run that stops (``StopError``), or raises any other exception before the replace, leaves
  INTERMAX as it was, no temporary file next to it, and
  the Kopie folder with the same Kopie, names and bytes, as before (docstring of ``order_register``).
- SUKCES: a run that returns a summary has replaced INTERMAX and left no temporary file.
- PRZYWROCONA_KOPIA: a restore that returns has replaced INTERMAX with exactly the bytes of the chosen Kopia.
- KOPIE_NAJNOWSZE: after a summary, the Kopie folder holds the ``KEPT`` newest Kopie of both names by the moment in
  their name, the new one among them, unless removing older ones failed, which the code turns into a warning, and
  every Kopia from before the run that is still there has the same bytes as before (``Disk.create`` makes the Kopia only
  as a new file, ``O_EXCL``), also after such a warning.
- BEZ_WYJATKU: the run ends with a summary or a ``StopError``, or the process dies; nothing else escapes.

Nothing in the product code is replaced; the checker only wraps the steps to pick at their points, and gives both runs
its own ``Disk`` and ``Waiting`` whose steps are the real ones behind a point. A killed process
is a ``BaseException`` raised at a point, so ``finally`` blocks still run, which a real kill would skip.
"""

from __future__ import annotations

import argparse
import enum
import errno
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from rozliczenia import intermax_copies, intermax_file, intermax_replace, intermax_restore, workbook_files
from rozliczenia.intermax_ordering import OrderingInputs, order_register
from rozliczenia.intermax_replace import LOCAL_DISK, Disk, Waiting, WriteMismatch
from rozliczenia.message import StopError
from rozliczenia.run_context import RunContext

from tests.fixtures.intermax import Intermax, Order

NOW = datetime(2026, 10, 25, 20, 0, 0)
NAME = "INTERMAX.xlsx"
TEMPORARY = f".{Path(NAME).stem}."
AFTER_READ = "pracownik po odczycie, przed podmianą"
INJECTED = "plik zablokowany"
READ = "po odczycie INTERMAX"
EXCEL = "is_open_in_excel(INTERMAX)"
WRITE = "zapis pliku tymczasowego obok INTERMAX"
CHECK = "Register.check sprawdza plik tymczasowy"
EXISTS = "Disk.exists (nazwa Kopii INTERMAX)"
CREATE = "Disk.create (Kopia INTERMAX)"
REPLACE = "os.replace pliku tymczasowego na INTERMAX"
PAUSE = "przerwa przed ponowną próbą podmiany"
PRUNE = "usunięcie starszej Kopii (KEPT)"
Mode = Literal["Uporządkowanie", "przywrócenie Kopii", "drugie przywrócenie w tej samej sekundzie"]
ORDERING: Mode = "Uporządkowanie"
RESTORE: Mode = "przywrócenie Kopii"
SAME_SECOND: Mode = "drugie przywrócenie w tej samej sekundzie"
"""A restore in the second of an earlier one: the Kopie folder already holds the Kopia that the replace would name."""

Actor = Literal["pracownik", "excel"]
Choice = Literal["ok", "pracownik", "excel", "oserror", "niezgodny", "kill", "onedrive", "dluga"]


class Crash(BaseException):
    """The process dies at this step (Dad closes Centrum, the computer switches off)."""


@dataclass(frozen=True)
class Bounds:
    worker: int = 1
    excel: int = 1
    oserror: int = 1
    mismatch: int = 1
    kills: int = 1
    refusals: int = 2
    long_pauses: int = 1


class Scheduler:
    """Picks one option at each point from the schedule prefix, then the first option; records what it could pick."""

    def __init__(
        self,
        prefix: Sequence[int],
        bounds: Bounds,
        act: Callable[[Actor], None],
        locked: Callable[[], bool],
    ) -> None:
        self._prefix = prefix
        self._act = act
        self._locked = locked
        self.taken: list[int] = []
        self.options: list[int] = []
        self.left: dict[Choice, int] = {
            "pracownik": bounds.worker,
            "excel": bounds.excel,
            "oserror": bounds.oserror,
            "niezgodny": bounds.mismatch,
            "kill": bounds.kills,
            "onedrive": bounds.refusals,
            "dluga": bounds.long_pauses,
        }
        self.trace: list[str] = []
        self.faults: list[tuple[str, str]] = []
        self.step = ""

    def say(self, line: str) -> None:
        self.trace.append(line)

    def _pick(self, offered: Sequence[Choice], step: str) -> Choice:
        allowed = [choice for choice in offered if self.left.get(choice, 1) > 0]
        position = len(self.taken)
        index = self._prefix[position] if position < len(self._prefix) else 0
        self.taken.append(index)
        self.options.append(len(allowed))
        chosen = allowed[index]
        if chosen in self.left:
            self.left[chosen] -= 1
            self.faults.append((chosen, step))
        return chosen

    def point(
        self,
        step: str,
        *,
        fails: Literal["oserror", "niezgodny"] | None = None,
        error: type[OSError] = PermissionError,
        extra: Sequence[Choice] = (),
    ) -> Choice:
        """Before ``step``: actors may act first (each at most once), then the step may fail or the process die.

        ``extra`` are outcomes of the step itself that the caller plays out; the chosen one (or ``ok``) is returned.
        """

        while True:
            offered: list[Choice] = ["ok", "excel", "kill"]
            if not self._locked():
                offered.insert(1, "pracownik")
            if fails is not None:
                offered.insert(-1, fails)
            offered[-1:-1] = extra
            self.step = step
            chosen = self._pick(offered, step)
            if chosen == "kill":
                self.say(f"proces ginie przed: {step}")
                raise Crash
            if chosen == "oserror":
                self.say(f"{step}: OSError")
                raise error(INJECTED)
            if chosen == "niezgodny":
                self.say(f"{step}: zapis się nie zgadza (WriteMismatch)")
                raise WriteMismatch("syntetyczna niezgodność")
            if chosen in ("pracownik", "excel"):
                self._act(chosen)
                continue
            return chosen


@dataclass
class World:
    mode: Mode
    folder: Path
    copies: Path
    original: bytes
    worker_bytes: bytes
    current: bytes
    """What INTERMAX holds as far as anyone but the run knows: the original or the worker's version."""
    old_copies: dict[str, bytes]
    chosen: str
    """The Kopia the restore brings back: the oldest of ``old_copies``, a real workbook."""
    read: bytes | None = None
    replaced: bytes | None = None
    written: bytes | None = None
    keep_failed: bool = False
    failure: str = ""
    seconds: float = 0.0
    """The process clock that ``Waiting`` reads; only the checker's pause moves it."""
    changed_at: int | None = None
    """The number of OneDrive refusals when a worker's change arrived after the read."""
    refused: int = 0

    @property
    def register(self) -> Path:
        return self.folder / NAME

    @property
    def lock(self) -> Path:
        return workbook_files.excel_lock_file(self.register)

    def kopie(self) -> dict[str, bytes]:
        return (
            {path.name: path.read_bytes() for path in self.copies.iterdir()}
            if self.copies.exists()
            else {}
        )


@contextmanager
def _points(world: World, scheduler: Scheduler) -> Iterator[None]:
    """Wraps the read, the Excel lock and the write check, which the runs reach through their modules; restores them."""

    real_read: Callable[..., intermax_file.Register] = intermax_file.Register.read.__func__  # type: ignore[attr-defined]
    real_content = workbook_files.workbook_content
    real_check = intermax_file.Register.check
    real_open = workbook_files.is_open_in_excel

    def read(cls: type[intermax_file.Register], /, path: Path, *arguments: Any, **options: Any) -> intermax_file.Register:
        # Uchwyt plików taty i ``despite_excel_lock`` przechodzą bez zmian.
        register = real_read(cls, path, *arguments, **options)
        if path == world.register:
            world.read = register.content
            scheduler.say("Register.read czyta INTERMAX")
            scheduler.point(READ)
        return register

    def content(path: Path) -> bytes:
        read = real_content(path)
        if world.mode != ORDERING and path == world.register and world.read is None:
            world.read = read
            scheduler.say("restore czyta INTERMAX (workbook_content)")
            scheduler.point(READ)
        return read

    def check(self: intermax_file.Register, *arguments: Any) -> None:
        scheduler.point(CHECK, fails="niezgodny")
        real_check(self, *arguments)

    def is_open(path: Path) -> bool:
        if path == world.register:
            scheduler.point(EXCEL)
        return real_open(path)

    intermax_file.Register.read = classmethod(read)  # type: ignore[method-assign,assignment]
    intermax_file.Register.check = check  # type: ignore[method-assign,assignment]
    workbook_files.is_open_in_excel = is_open
    workbook_files.workbook_content = content
    try:
        yield
    finally:
        intermax_file.Register.read = classmethod(real_read)  # type: ignore[method-assign,assignment]
        intermax_file.Register.check = real_check  # type: ignore[method-assign]
        workbook_files.is_open_in_excel = real_open
        workbook_files.workbook_content = real_content


def _disk(world: World, scheduler: Scheduler) -> Disk:
    """The replace's steps on the disk: the real ones (``LOCAL_DISK``), each behind its point."""

    def write(path: Path, data: bytes) -> None:
        scheduler.point(WRITE, fails="oserror")
        LOCAL_DISK.write(path, data)

    def exists(path: Path) -> bool:
        scheduler.point(EXISTS, fails="oserror")
        return LOCAL_DISK.exists(path)

    def create(path: Path, data: bytes) -> None:
        scheduler.point(CREATE, fails="oserror")
        LOCAL_DISK.create(path, data)
        scheduler.say(f"Kopia INTERMAX zapisana: {path.name}")

    def replace(source: Path, target: Path) -> None:
        if scheduler.point(REPLACE, fails="oserror", error=OSError, extra=("onedrive",)) == "onedrive":
            world.refused += 1
            scheduler.say("os.replace: PermissionError, OneDrive trzyma INTERMAX")
            raise PermissionError(errno.EACCES, "OneDrive trzyma INTERMAX")
        if world.lock.exists():
            scheduler.say(
                "os.replace: PermissionError, Excel trzyma INTERMAX (Windows)"
            )
            raise PermissionError("Excel trzyma INTERMAX")
        world.replaced = world.register.read_bytes()
        LOCAL_DISK.replace(source, target)
        world.written = world.register.read_bytes()
        scheduler.say("os.replace podmienia INTERMAX")

    def remove(path: Path) -> None:
        # Only the removal of older Kopie after the replace is a point; removing the run's own Kopia after a failed
        # replace is not (SKILL.md: not covered).
        if world.replaced is not None:
            try:
                scheduler.point(PRUNE, fails="oserror")
            except OSError:
                world.keep_failed = True
                raise
        LOCAL_DISK.remove(path)

    return Disk(write=write, read=LOCAL_DISK.read, exists=exists, create=create, replace=replace, remove=remove)


def _waiting(world: World, scheduler: Scheduler) -> Waiting:
    """The process clock and the pause of the retried replace; the pause only moves the clock, never sleeps."""

    def pause(seconds: float) -> None:
        if scheduler.point(PAUSE, extra=("dluga",)) == "dluga":
            scheduler.say("przerwa trwa cały czas ponownych prób")
            world.seconds += intermax_replace._RETRY_S
        else:
            world.seconds += seconds
        scheduler.say("ponowna próba podmiany")

    return Waiting(lambda: world.seconds, pause)


def _synthetic(work: Path) -> tuple[bytes, bytes, bytes]:
    """The original INTERMAX, the version a worker saves on another computer (one more ordered order above) and an
    earlier INTERMAX with one ordered order fewer, which the oldest Kopia holds."""

    original, worker, earlier = Intermax(), Intermax(), Intermax()
    worker.ordered = (
        *original.ordered,
        Order(datetime(2026, 10, 20, 11), "jan.nowak", 4),
    )
    earlier.ordered = original.ordered[:-1]
    paths = (work / "oryginal.xlsx", work / "pracownik.xlsx", work / "wczesniejszy.xlsx")
    for intermax, path in zip((original, worker, earlier), paths, strict=True):
        intermax.write(path)
    return paths[0].read_bytes(), paths[1].read_bytes(), paths[2].read_bytes()


def _old_copies(earlier: bytes) -> dict[str, bytes]:
    """``KEPT`` Kopie from earlier days, named as the replace names them, alternately before an Uporządkowanie and
    before a restore, so that sorting by name (``przywróceniem`` < ``uporządkowaniem``) differs from sorting in time.

    The oldest holds the ``earlier`` INTERMAX, the others their own bytes.
    """

    names = {
        day: f"INTERMAX przed {'przywróceniem' if day % 2 else 'uporządkowaniem'} "
        f"{NOW - timedelta(days=day):%Y-%m-%d %H-%M-%S}.xlsx"
        for day in range(1, intermax_copies.KEPT + 1)
    }
    return {
        name: earlier if day == intermax_copies.KEPT else f"stara Kopia {day}".encode() for day, name in names.items()
    }


def _newest(names: set[str]) -> list[str]:
    """The ``KEPT`` newest Kopie by the moment in their name, sorted by name."""

    by_moment = sorted(names, key=lambda name: (name[-24:], name))
    return sorted(by_moment[-intermax_copies.KEPT :])


Outcome = Literal["podsumowanie", "zatrzymanie", "zginal", "wyjatek"]


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    trace: tuple[str, ...]
    kind: Literal["known", "new"]


def _check(world: World, outcome: Outcome, failure: str) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    left = sorted(
        path.name
        for path in world.folder.iterdir()
        if path.name not in (NAME, world.lock.name)
    )
    kopie = world.kopie()
    if world.replaced is not None:
        if world.replaced != world.read:
            broken.append(
                (
                    "BEZ_UTRATY_ZMIAN",
                    "podmiana zastąpiła INTERMAX z cudzą zmianą, której run nie czytał",
                )
            )
        if world.replaced not in kopie.values():
            broken.append(
                (
                    "KOPIA_ZASTAPIONEGO",
                    "żadna Kopia INTERMAX nie ma bajtów, które podmiana zastąpiła",
                )
            )
    if outcome == "zatrzymanie" or (outcome == "wyjatek" and world.replaced is None):
        who = "Zatrzymanie" if outcome == "zatrzymanie" else "Wyjątek"
        if world.register.read_bytes() != world.current:
            broken.append(
                ("ZATRZYMANIE_BEZ_SLADU", f"{who} zostawia zmieniony INTERMAX")
            )
        if left:
            broken.append(
                (
                    "ZATRZYMANIE_BEZ_SLADU",
                    f"{who} zostawia pliki obok INTERMAX: {left}",
                )
            )
        if kopie != world.old_copies:
            broken.append(
                (
                    "ZATRZYMANIE_BEZ_SLADU",
                    f"{who} zmienia Kopie INTERMAX: {sorted(set(kopie) ^ set(world.old_copies))}",
                )
            )
    if outcome == "podsumowanie":
        if world.written is None:
            broken.append(("SUKCES", "wynik bez podmiany INTERMAX"))
        if left:
            broken.append(("SUKCES", f"po wyniku zostają pliki obok INTERMAX: {left}"))
        # What the replace put in place: a worker's change that OneDrive brings in after it is not the restore's.
        if world.mode != ORDERING and world.written != world.old_copies[world.chosen]:
            broken.append(("PRZYWROCONA_KOPIA", "podmiana przywrócenia nie dała INTERMAX bajtów wybranej Kopii"))
        expected = _newest({*world.old_copies, *kopie})
        if not world.keep_failed and sorted(kopie) != expected:
            broken.append(
                (
                    "KOPIE_NAJNOWSZE",
                    f"po wyniku zostają Kopie {sorted(kopie)} zamiast {intermax_copies.KEPT} najnowszych",
                )
            )
        rewritten = sorted(name for name, content in world.old_copies.items() if kopie.get(name, content) != content)
        if rewritten:
            broken.append(("KOPIE_NAJNOWSZE", f"po wyniku Kopie sprzed runu mają inne bajty: {rewritten}"))
    if outcome == "wyjatek":
        broken.append(
            ("BEZ_WYJATKU", f"{world.mode} kończy się wyjątkiem: {failure}")
        )
    return list(dict.fromkeys(broken))


class Version(enum.Enum):
    """Whose bytes INTERMAX had, as far as the model tells them apart: the original, the worker's change or other bytes
    (the run's own file, a Kopia brought back, nothing read)."""

    ORIGINAL = "oryginał"
    WORKER = "zmiana pracownika"
    OTHER = "inne bajty"


class Copy(enum.Enum):
    """Whether a Kopia INTERMAX holds the bytes the run read."""

    OF_READ = "Kopia ma bajty, które run przeczytał"
    OTHER = "żadna Kopia nie ma bajtów, które run przeczytał"


@dataclass(frozen=True)
class Came:
    """How the run lost the worker's change it did not read, each part of a finding's shape (``FindingShape``): the
    point of the run the change came before after the read (``None``: no change came after the read), how many times
    OneDrive refused the replace after it, what the run read and what its replace put its file over, and whether a
    Kopia holds the bytes the run read."""

    before: str | None
    refusals_after: int
    lost: tuple[Version, Version]
    copy: Copy


def _version(world: World, content: bytes | None) -> Version:
    if content == world.original:
        return Version.ORIGINAL
    return Version.WORKER if content == world.worker_bytes else Version.OTHER


def _came(world: World, faults: Sequence[tuple[str, str]]) -> Came:
    before = next((step for kind, step in faults if kind == AFTER_READ), None)
    return Came(
        before,
        0 if world.changed_at is None else world.refused - world.changed_at,
        (_version(world, world.read), _version(world, world.replaced)),
        Copy.OF_READ if world.read in world.kopie().values() else Copy.OTHER,
    )


@dataclass(frozen=True)
class FindingShape:
    """The exact shape of a known finding, each part taken from its story and each required, so an entry cannot match
    on fewer of them (#920):

    - ``came_before``: the points of the run before which the worker's change came after the read; not the pause
      before a retry, after which the run reads INTERMAX again, so a change it puts its file over there is one it had
      time to see;
    - ``refusals_after``: how many times OneDrive refused the replace after the change came; after a refusal the run
      reads INTERMAX again too;
    - ``lost``: what the run read and what its replace put its file over: the original and the worker's change, and not
      the run's own bytes or a change the run read;
    - ``copy``: what the Kopia holds; the story of KOPIA_ZASTAPIONEGO is a Kopia of the bytes read (``current`` of
      ``replace_register``), and BEZ_UTRATY_ZMIAN says nothing of the Kopia, so its shape admits every ``Copy``.

    Each part that restricts has in ``check_intermax_mutations.BOUNDARIES`` a broken variant just outside it, which must
    give a new violation (``tests/test_mutacje_skilli.py``)."""

    came_before: frozenset[str]
    refusals_after: int
    lost: frozenset[tuple[Version, Version]]
    copy: frozenset[Copy]

    def __post_init__(self) -> None:
        if not self.came_before or not self.lost or not self.copy:
            raise ValueError("kształt bez punktu, przed którym przyszła zmiana pracownika, bez tego, co run stracił, albo bez Kopii")

    def holds(self, came: Came) -> bool:
        return (
            came.before in self.came_before
            and came.refusals_after == self.refusals_after
            and came.lost in self.lost
            and came.copy in self.copy
        )


@dataclass(frozen=True)
class Finding:
    """A break of the rule ``name`` that the report lists apart from new ones, only in ``shape``: the same rule broken
    otherwise is a new violation."""

    name: str
    story: str
    shape: FindingShape


CHANGE_AFTER_READ = FindingShape(
    came_before=frozenset({READ, EXCEL, WRITE, CHECK, EXISTS, CREATE, REPLACE}),
    refusals_after=0,
    lost=frozenset({(Version.ORIGINAL, Version.WORKER)}),
    copy=frozenset(Copy),
)
"""Uporządkowanie and the restore do not check right before os.replace whether INTERMAX still has the bytes they read:
a worker's change that comes after the read of the original, and after which the run neither paused nor was refused, is
lost under the run's file."""

KNOWN_FINDINGS: tuple[Finding, ...] = (
    Finding(
        "BEZ_UTRATY_ZMIAN",
        "Uporządkowanie i przywrócenie Kopii nie sprawdzają tuż przed os.replace, czy INTERMAX ma wciąż bajty, które "
        "przeczytały (przed pierwszą próbą wcale, przed ponowną po przerwie): zmiana pracownika z innego komputera, "
        "którą OneDrive wgrał w trakcie, przepada",
        CHANGE_AFTER_READ,
    ),
    Finding(
        "KOPIA_ZASTAPIONEGO",
        "Kopia INTERMAX powstaje z bajtów przeczytanych na początku (current w replace_register), więc "
        "nie ma też zmiany pracownika, która przyszła w trakcie",
        replace(CHANGE_AFTER_READ, copy=frozenset({Copy.OF_READ})),
    ),
)


def _finding(rule: str) -> Finding | None:
    return next((finding for finding in KNOWN_FINDINGS if finding.name == rule), None)


def execute(
    mode: Mode, prefix: Sequence[int], work: Path, versions: tuple[bytes, bytes, bytes], bounds: Bounds
) -> tuple[Scheduler, list[Violation]]:
    shutil.rmtree(work / "OneDrive", ignore_errors=True)
    shutil.rmtree(work / "Kopie INTERMAX", ignore_errors=True)
    folder = work / "OneDrive"
    folder.mkdir()
    original, worker, earlier = versions
    old_copies = _old_copies(earlier)
    if mode == SAME_SECOND:
        old_copies[f"INTERMAX przed przywróceniem {NOW:%Y-%m-%d %H-%M-%S}.xlsx"] = b"Kopia przywrocenia sprzed chwili"
    world = World(mode, folder, work / "Kopie INTERMAX", original, worker, original, old_copies, min(old_copies, key=lambda name: name[-24:]))
    world.register.write_bytes(original)
    world.copies.mkdir()
    for name, content in world.old_copies.items():
        (world.copies / name).write_bytes(content)

    def act(actor: Actor) -> None:
        if actor == "pracownik":
            scheduler.say(
                "pracownik zapisuje zmianę na innym komputerze, OneDrive podmienia INTERMAX"
            )
            incoming = folder / ".onedrive-przychodzi.tmp"
            incoming.write_bytes(world.worker_bytes)
            os.replace(incoming, world.register)
            world.current = world.worker_bytes
            if world.read is not None and world.replaced is None:
                scheduler.faults.append((AFTER_READ, scheduler.step))
                world.changed_at = world.refused
        else:
            scheduler.say("tata otwiera INTERMAX w Excelu (plik ~$)")
            world.lock.write_bytes(b"tata")

    scheduler = Scheduler(prefix, bounds, act, world.lock.exists)
    outcome: Outcome = "podsumowanie"
    failure = ""
    scheduler.say(mode if mode == ORDERING else f"{mode} {world.chosen}")
    with _points(world, scheduler):
        try:
            waiting, disk = _waiting(world, scheduler), _disk(world, scheduler)
            if mode == ORDERING:
                order_register(
                    OrderingInputs(world.register, world.copies, now=lambda: NOW, waiting=waiting, disk=disk),
                    RunContext(),
                )
            else:
                intermax_restore.restore(
                    world.chosen, world.register, world.copies, now=lambda: NOW, waiting=waiting, disk=disk
                )
            scheduler.say(f"{mode} kończy się wynikiem")
        except StopError as stop:
            outcome = "zatrzymanie"
            scheduler.say(f"Zatrzymanie: {stop.message.code}")
        except Crash:
            outcome = "zginal"
        except Exception as error:  # noqa: BLE001 - BEZ_WYJATKU: every other exception is a finding
            outcome = "wyjatek"
            failure = world.failure = f"{type(error).__name__}: {error}"
            scheduler.say(f"wyjątek {failure}")
    trace = tuple(scheduler.trace)
    violations = []
    came = _came(world, scheduler.faults)
    for rule, detail in _check(world, outcome, failure):
        known = _finding(rule)
        kind: Literal["known", "new"] = "known" if known and known.shape.holds(came) else "new"
        violations.append(Violation(rule, detail, trace, kind))
    return scheduler, violations


def next_prefix(scheduler: Scheduler) -> list[int] | None:
    for position in range(len(scheduler.taken) - 1, -1, -1):
        if scheduler.taken[position] + 1 < scheduler.options[position]:
            return [*scheduler.taken[:position], scheduler.taken[position] + 1]
    return None


@dataclass
class Report:
    schedules: int = 0
    shortest: dict[tuple[str, str], Violation] = field(default_factory=dict)


def explore(bounds: Bounds | None = None) -> Report:
    bounds = bounds or Bounds()
    report = Report()
    with tempfile.TemporaryDirectory(prefix="zapis-intermax-") as directory:
        work = Path(directory).resolve()  # order_register resolves the path of INTERMAX
        versions = _synthetic(work)
        modes: tuple[Mode, ...] = (ORDERING, RESTORE, SAME_SECOND)
        for mode in modes:
            prefix: list[int] | None = []
            while prefix is not None:
                scheduler, violations = execute(mode, prefix, work, versions, bounds)
                report.schedules += 1
                for violation in violations:
                    key = (violation.rule, violation.kind)
                    seen = report.shortest.get(key)
                    if seen is None or len(violation.trace) < len(seen.trace):
                        report.shortest[key] = violation
                prefix = next_prefix(scheduler)
    return report


def summarize(report: Report, *, strict: bool = False) -> tuple[list[str], int]:
    lines = [f"Harmonogramy: {report.schedules}."]
    new = known = 0
    for (rule, kind), violation in sorted(report.shortest.items()):
        finding = _finding(rule)
        if kind == "known" and finding is not None and not strict:
            known += 1
            lines.append(f"znane ustalenie {rule}: {finding.story}")
        else:
            new += 1
            lines.append(f"NOWE NARUSZENIE {rule}")
        lines.append(f"   {violation.detail}")
        lines.extend(
            f"   {number}. {step}"
            for number, step in enumerate(violation.trace, start=1)
        )
    gone = [finding.name for finding in KNOWN_FINDINGS if (finding.name, "known") not in report.shortest]
    lines.extend(
        f"ZNALEZISKO ZNIKNĘŁO {rule}: usuń je z KNOWN_FINDINGS i z SKILL.md"
        for rule in gone
    )
    lines.append("")
    if new:
        lines.append(f"INTERMAX: NOWE NARUSZENIE ({new})")
        return lines, 1
    if gone and not strict:
        lines.append(f"INTERMAX: ZNALEZISKO ZNIKNĘŁO ({len(gone)})")
        return lines, 1
    lines.append(f"INTERMAX OK, ZNANE USTALENIA: {known}" if known else "INTERMAX OK")
    return lines, 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exhaustive check of how Uporządkowanie INTERMAX and Przywracanie Kopii INTERMAX replace INTERMAX."
    )
    parser.add_argument(
        "--strict", action="store_true", help="report known findings as violations too"
    )
    arguments = parser.parse_args(argv)
    lines, code = summarize(explore(), strict=arguments.strict)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
