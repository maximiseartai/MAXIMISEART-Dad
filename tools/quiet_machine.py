from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

OPIS = """Pokazuje, co trzyma maszynę (--status), i pilnuje jednego pomiaru wydajności naraz na cichym procesorze; użyj, gdy pomiar czeka.

One measurement at a time on this machine, on a quiet CPU; other runs wait only while it measures.

A measurement (``--feature wydajnosc``, ``benchmark_przebiegu.py measure``) waits,
holding nothing, until no run is registered in a lock directory shared by every
checkout and worktree on the machine, no other measurement holds ``pomiar.lock``
and no test run, mutation check or browser drive is running (on macOS and Linux,
read from ``ps``). Then it takes ``pomiar.lock`` for as long as it measures.
Every other run (a Centrum verification run, ``benchmark_przebiegu.py freeze``)
registers a ``run-*.pid`` file for its duration and first waits while a
measurement holds the lock. Locks and registrations of a process that died are
taken over.

What a waiter waits for sets its limit. A measurement waits for a quiet CPU at
most ``QUIET_TIMEOUT_S``; a run waits for a measurement in progress at most
``MEASUREMENT_TIMEOUT_S``. Past its limit each fails with what kept the machine busy.

    python tools/quiet_machine.py --status   # who holds the machine now
"""

LOCK_DIRECTORY = Path(tempfile.gettempdir()) / "verify-centrum-rozliczen"
MEASUREMENT_LOCK = "pomiar.lock"
# A measurement's wait for a quiet CPU: short, so the wait plus a wydajnosc measurement (about 5 minutes)
# ends inside an agent's 10-minute command limit.
QUIET_TIMEOUT_S = 3 * 60
# A run's wait for a measurement in progress: a whole wydajnosc measurement (about 5 minutes) three times over.
MEASUREMENT_TIMEOUT_S = 15 * 60
POLL_S = 5.0
REPORT_EVERY_S = 60.0
# Command-line fragments of work that loads the CPU and is not registered in the lock directory.
# Benchmarks are absent: they hold the lock or a registration, and two waiting ones would see each other here.
BUSY_COMMANDS = (
    "pytest",
    "serve_centrum.py",
    "drive_centrum.py",
    "chrome-headless-shell",
    "run_verification.py",
    "_mutations.py",
)
# Programs that do that work. A shell (``zsh -c "… && pytest"``) or another wrapper only names it while it waits,
# and the program it starts is listed on its own.
WORKING_PROGRAMS = ("python", "chrome-headless-shell")


class MachineBusy(Exception):
    """The machine did not become quiet within the timeout; the message names what kept it busy."""


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owner(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def busy_commands() -> list[str]:
    """Commands from ``BUSY_COMMANDS`` run by ``WORKING_PROGRAMS`` other than this process and its ancestors.

    Read from ``ps``; none on Windows.
    """

    if sys.platform == "win32":
        return []
    # -ww: ps z procps (Linux) obcina polecenie do 80 kolumn, gdy nie pisze do terminala.
    listing = subprocess.run(["ps", "-ww", "-Ao", "pid=,ppid=,command="], capture_output=True, text=True, check=False)
    parents: dict[int, int] = {}
    commands: dict[int, str] = {}
    for line in listing.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = int(fields[1])
            commands[int(fields[0])] = fields[2]
    own: set[int] = set()
    pid = os.getpid()
    while pid > 1 and pid not in own:
        own.add(pid)
        pid = parents.get(pid, 0)
    return sorted(
        {
            fragment
            for pid, command in commands.items()
            if pid not in own and Path(command.split(None, 1)[0]).name.lower().startswith(WORKING_PROGRAMS)
            for fragment in BUSY_COMMANDS
            if fragment in command
        }
    )


class QuietMachine:
    def __init__(
        self,
        directory: Path = LOCK_DIRECTORY,
        *,
        quiet_timeout_s: float = QUIET_TIMEOUT_S,
        measurement_timeout_s: float = MEASUREMENT_TIMEOUT_S,
        poll_s: float = POLL_S,
        busy_processes: Callable[[], list[str]] = busy_commands,
        report_every_s: float | None = REPORT_EVERY_S,
    ) -> None:
        self._directory = directory
        self._quiet_timeout_s = quiet_timeout_s
        self._measurement_timeout_s = measurement_timeout_s
        self._poll_s = poll_s
        self._busy_processes = busy_processes
        self._report_every_s = report_every_s

    @contextmanager
    def measurement(self) -> Iterator[float]:
        """Hold the machine for one measurement; yields how many seconds it waited."""

        started = time.monotonic()
        self._wait("pomiar", self._take_quiet_machine, self._quiet_timeout_s)
        try:
            yield time.monotonic() - started
        finally:
            (self._directory / MEASUREMENT_LOCK).unlink(missing_ok=True)

    @contextmanager
    def run(self) -> Iterator[float]:
        """Register one run for its duration; yields how many seconds it waited for a measurement."""

        started = time.monotonic()
        self._directory.mkdir(parents=True, exist_ok=True)
        marker = self._directory / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}.pid"
        try:
            # Register first, then look at the lock: a measurement taking the lock now sees this run and waits.
            marker.write_text(str(os.getpid()), encoding="utf-8")
            while self._measurement_holder() is not None:
                marker.unlink(missing_ok=True)
                self._wait("przebieg", self._measurement_holder, self._measurement_timeout_s)
                marker.write_text(str(os.getpid()), encoding="utf-8")
            yield time.monotonic() - started
        finally:
            marker.unlink(missing_ok=True)

    def status(self) -> list[str]:
        holder = self._measurement_holder()
        return ([] if holder is None else [holder]) + self._registered_runs() + self._busy_processes()

    def _measurement_holder(self) -> str | None:
        lock = self._directory / MEASUREMENT_LOCK
        if not lock.exists():
            return None
        pid = _owner(lock)
        if _alive(pid):
            return f"pomiar (pid {pid})"
        lock.unlink(missing_ok=True)
        return None

    def _registered_runs(self) -> list[str]:
        runs = []
        for marker in sorted(self._directory.glob("run-*.pid")):
            pid = _owner(marker)
            if _alive(pid):
                runs.append(f"przebieg (pid {pid})")
            else:
                marker.unlink(missing_ok=True)
        return runs

    def _take_lock(self) -> str | None:
        """None once this process holds the lock, otherwise who holds it."""

        self._directory.mkdir(parents=True, exist_ok=True)
        if (holder := self._measurement_holder()) is not None:
            return holder
        try:
            descriptor = os.open(self._directory / MEASUREMENT_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return "pomiar (właśnie zaczęty)"
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
            lock.write(str(os.getpid()))
        return None

    def _take_quiet_machine(self) -> str | None:
        """None once this process holds the lock on a quiet machine, otherwise what keeps it busy."""

        if (busy := self._quiet()) is not None:
            return busy
        if (holder := self._take_lock()) is not None:
            return holder
        # A run that registered between the first look and the lock saw no lock and goes ahead, so this one backs off.
        if (busy := self._quiet()) is not None:
            (self._directory / MEASUREMENT_LOCK).unlink(missing_ok=True)
            return busy
        return None

    def _quiet(self) -> str | None:
        busy = self._registered_runs() + self._busy_processes()
        return ", ".join(busy) if busy else None

    def _wait(self, who: str, blocked: Callable[[], str | None], timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        reported: float | None = None
        while (blocker := blocked()) is not None:
            now = time.monotonic()
            if now >= deadline:
                raise MachineBusy(
                    f"maszyna nie ucichła w {timeout_s:.0f} s; zajmuje ją: {blocker}; "
                    "uruchom ponownie, gdy ucichnie (python tools/quiet_machine.py --status)"
                )
            if self._report_every_s is not None and (reported is None or now - reported >= self._report_every_s):
                print(f"MASZYNA ZAJĘTA | {who} czeka na: {blocker}", flush=True)
                reported = now
            time.sleep(self._poll_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="Print what holds the machine now and exit.")
    parser.parse_args(argv)
    busy = QuietMachine().status()
    print("MASZYNA WOLNA" if not busy else "MASZYNA ZAJĘTA | " + ", ".join(busy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
