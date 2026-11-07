"""Procesy potomne i kopie commitów narzędzia z ``tools/``, które giną razem z nim.

``run`` to ``subprocess.run`` z przechwyconym wyjściem, którego polecenie biegnie z całym drzewem swoich
potomków (POSIX: własna sesja, Windows: Job Object). Drzewo nie przeżywa:

- końca polecenia: potomkowie, którzy je przeżyli, giną, a ``run`` nie czeka, aż zamkną jego wyjście;
- limitu czasu (``subprocess.TimeoutExpired``) ani ustawienia ``stop`` przez inny wątek (``Stopped``);
- wyjątku w narzędziu, także przerwania (Ctrl+C);
- śmierci narzędzia bez sprzątania (SIGKILL, ``os._exit``): na POSIX zabija je strażnik narzędzia, na
  Windows system, gdy zamyka uchwyt Job Object (KILL_ON_JOB_CLOSE).

``commit_copy`` to odłączony worktree commitu w katalogu tymczasowym. Znika z blokiem ``with``, a po
śmierci narzędzia usuwa go strażnik.

Strażnik to ten plik uruchomiony ``python -I`` we własnej sesji. Po EOF na stdin, czyli po końcu
narzędzia, zabija zgłoszone drzewa i usuwa zgłoszone kopie. Narzędzie uruchomione przez inne narzędzie
ma własnego strażnika, więc śmierć zewnętrznego kończy kolejne poziomy po kolei. Gdy strażnik nie żyje,
``commit_copy``, a na POSIX także ``run``, rzucają ``OSError``, zamiast działać bez tej gwarancji. Na Windows
zabite drzewo, które żyje jeszcze ``_KILL_S`` po zabiciu, ``run`` nazywa na stderr i wraca jak zwykle.

Granice: na POSIX potomek, który sam założył sesję albo grupę procesów (``setsid``, ``setpgid``), jest poza
drzewem i przeżywa; ``run`` czeka na resztę wyjścia najwyżej ``_DRAIN_S``. Na Windows narzędzie zabite razem z cudzym Job Object
zostawia swoje kopie w katalogu tymczasowym. Narzędzie nie robi ``fork`` bez ``exec``: potomek z kopią
potoku strażnika opóźniłby EOF. Gita narzędzie pyta przez ``repo.py``, którego ``run_git`` idzie przez ``run``;
przez ``run`` idzie też każde inne polecenie, które trwa albo uruchamia własne procesy.

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))  # skrypt z tools/
    import potomne

    done = potomne.run([sys.executable, "-m", "pytest", "-q"], cwd=root, timeout=600)
    with potomne.commit_copy(ROOT, commit) as tree:
        potomne.run([...], cwd=tree, stop=stop)
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import IO, Any

_DRAIN_S = 5.0
# Na Windows tyle czeka zabijanie drzewa, aż każdy jego proces skończy I/O w toku.
_KILL_S = 10.0
_POLL_S = 0.1
# Na Windows pliki zabitych procesów zwalniają się z opóźnieniem, więc usuwanie kopii trochę ponawia.
_RELEASE_S = 10.0
# ``git worktree prune`` i ``remove`` z jednego wątku usuwają katalogi ``.git/worktrees``, które ``add`` z innego
# wątku właśnie zakłada, i ``add`` pada. Równoległe mutacje robią kopie naraz, więc te polecenia idą po kolei.
_WORKTREES = threading.Lock()


class Stopped(Exception):
    """Wołający ustawił ``stop``: drzewo polecenia już nie żyje."""


class TimeoutExpired(subprocess.TimeoutExpired):
    """Limit czasu ``run``: drzewo polecenia już nie żyje, a ``printed`` to stdout i stderr, które zdążyło wypisać.

    Nazwa jak w ``subprocess``, bo wywołujący pokazują nazwę klasy wyjątku (brama pre-push).
    """

    def __init__(self, command: list[str], timeout: float, stdout: str, stderr: str) -> None:
        super().__init__(command, timeout, stdout, stderr)
        self.printed = (stdout, stderr)


class _GitFailed(subprocess.CalledProcessError):
    def __str__(self) -> str:
        return f"{super().__str__()}\n{self.stderr.strip()}"


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    echo: bool = False,
    stop: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """``subprocess.run(capture_output=True, text=True)``, którego drzewo procesów nie przeżywa wyniku ani narzędzia.

    Czeka na koniec polecenia, nie na zamknięcie jego wyjścia, i po nim zabija potomków, którzy je przeżyli.
    ``echo`` drukuje wyjście na bieżąco; stderr trafia wtedy do stdout. stdin to DEVNULL, tekst UTF-8 z
    ``errors="replace"``. Po ``timeout`` rzuca ``TimeoutExpired`` (``subprocess.TimeoutExpired`` z wyjściem wypisanym
    do limitu), a po ``stop`` ``Stopped``.
    """

    arguments = list(command)
    if stop is not None and stop.is_set():
        raise Stopped(arguments)
    tree = _Tree(
        arguments,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if echo else subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    expired: subprocess.TimeoutExpired | None = None
    try:
        assert tree.process.stdout is not None
        output = _Reader(tree.process.stdout, echo=echo)
        errors = None if tree.process.stderr is None else _Reader(tree.process.stderr, echo=False)
        try:
            _wait(tree.process, math.inf if timeout is None else timeout, stop)
        except subprocess.TimeoutExpired as error:
            expired = error
    finally:
        tree.kill()
    deadline = time.monotonic() + _DRAIN_S
    stdout, stderr = output.text(deadline), "" if errors is None else errors.text(deadline)
    if expired is not None:
        raise TimeoutExpired(arguments, expired.timeout, stdout, stderr) from None
    return subprocess.CompletedProcess(arguments, tree.process.returncode, stdout, stderr)


@contextmanager
def commit_copy(repo: Path, commit: str) -> Iterator[Path]:
    """Odłączony worktree commitu ``commit`` repozytorium ``repo`` w nowym katalogu tymczasowym.

    Znika z końcem bloku, także po wyjątku, a gdy narzędzie zginie, usuwa go strażnik. Rzuca
    ``subprocess.CalledProcessError``, gdy ``git worktree add`` się nie uda.
    """

    repo = repo.resolve()
    guard = _guard()
    copy = Path(tempfile.mkdtemp(prefix="kopia-commitu-"))
    try:
        guard.report("+", "kopia", str(copy), str(repo))
        # Przez run: strażnik zabija przerwane ``worktree add``, zanim usunie kopię, którą ono jeszcze wypełnia.
        with _WORKTREES:
            added = run(["git", "worktree", "add", "--quiet", "--detach", str(copy), commit], cwd=repo)
        if added.returncode:
            raise _GitFailed(added.returncode, added.args, added.stdout, added.stderr)
        yield copy
    finally:
        _remove_copy(repo, copy)
        with suppress(OSError):
            guard.report("-", "kopia", str(copy), str(repo))


def _wait(process: subprocess.Popen[str], timeout: float, stop: threading.Event | None) -> None:
    if stop is None:
        process.wait(None if math.isinf(timeout) else timeout)
        return
    deadline = time.monotonic() + timeout
    while not stop.is_set():
        try:
            process.wait(min(_POLL_S, max(0.0, deadline - time.monotonic())))
            return
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, timeout) from None
    raise Stopped(process.args)


class _Reader:
    def __init__(self, stream: IO[str], *, echo: bool) -> None:
        self._lines: list[str] = []
        self._thread = threading.Thread(target=self._read, args=(stream, echo), daemon=True)
        self._thread.start()

    def _read(self, stream: IO[str], echo: bool) -> None:
        with stream:
            for line in stream:
                if echo:
                    print(line, end="", flush=True)
                self._lines.append(line)

    def text(self, deadline: float) -> str:
        self._thread.join(max(0.0, deadline - time.monotonic()))
        return "".join(self._lines)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _ProcessIds(ctypes.Structure):
        """JOBOBJECT_BASIC_PROCESS_ID_LIST."""

        _fields_ = [
            ("NumberOfAssignedProcesses", wintypes.DWORD),
            ("NumberOfProcessIdsInList", wintypes.DWORD),
            ("ProcessIdList", ctypes.c_size_t * 64),
        ]

    _KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFORMATION = 9
    _PROCESS_ID_LIST = 3
    _ERROR_MORE_DATA = 234
    _SYNCHRONIZE = 0x00100000
    _QUERY_LIMITED_INFORMATION = 0x1000
    _WAIT_TIMEOUT = 0x102
    _TERMINATE_SET_QUOTA_AND_RESUME = 0x0901
    _CREATE_SUSPENDED = 0x0004

    class _Tree:
        """Job Object obejmuje też potomków, którzy przeżyli polecenie; ``taskkill /T`` już ich nie znajduje."""

        def __init__(self, command: list[str], **popen: Any) -> None:
            self._kernel32 = kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = kernel32.OpenProcess.restype = wintypes.HANDLE
            self._job = wintypes.HANDLE(kernel32.CreateJobObjectW(None, None))
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            size = ctypes.sizeof(limits)
            if not self._job.value or not kernel32.SetInformationJobObject(
                self._job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), size
            ):
                error = ctypes.get_last_error()
                kernel32.CloseHandle(self._job)
                raise OSError(error, "Job Object dla polecenia")
            # Wstrzymane do przypisania: inaczej polecenie zdąży uruchomić potomka, który jest poza jobem i przeżywa.
            try:
                self.process = subprocess.Popen(command, creationflags=_CREATE_SUSPENDED, **popen)
            except BaseException:
                kernel32.CloseHandle(self._job)
                raise
            # Także Ctrl+C w tym oknie: wstrzymanego polecenia poza jobem nikt by nie wznowił ani nie zabił.
            try:
                self._assign_and_resume()
            except BaseException:
                self.process.kill()
                self.process.wait()
                kernel32.CloseHandle(self._job)
                raise

        def _assign_and_resume(self) -> None:
            kernel32 = self._kernel32
            handle = wintypes.HANDLE(kernel32.OpenProcess(_TERMINATE_SET_QUOTA_AND_RESUME, False, self.process.pid))
            if not handle.value:
                raise ctypes.WinError(ctypes.get_last_error(), "uchwyt polecenia dla Job Object")
            try:
                if not kernel32.AssignProcessToJobObject(self._job, handle):
                    raise ctypes.WinError(ctypes.get_last_error(), "przypisanie polecenia do Job Object")
                ntdll = ctypes.WinDLL("ntdll")
                status = ntdll.NtResumeProcess(handle)
                if status != 0:
                    ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
                    raise ctypes.WinError(
                        ntdll.RtlNtStatusToDosError(status),
                        f"wznowienie polecenia w Job Object (NTSTATUS 0x{status & 0xFFFFFFFF:08X})",
                    )
            finally:
                kernel32.CloseHandle(handle)

        def kill(self) -> None:
            """``TerminateJobObject`` tylko zaczyna zabijanie: proces z I/O w toku pisze jeszcze po jego powrocie (#401).

            Licznik ``ActiveProcesses`` zadania spada, zanim proces zgłosi koniec, więc czeka na uchwyty członków
            zadania otwarte przed zabiciem, najwyżej ``_KILL_S``. Po tym terminie nie wywraca wołającego, tylko
            nazywa na stderr procesy, które jeszcze żyją.
            """

            kernel32 = self._kernel32
            try:
                started = time.monotonic()
                deadline = started + _KILL_S
                while members := self._members():
                    if time.monotonic() >= deadline:
                        self._survived(started, {})
                        return
                    handles = self._handles(members)
                    try:
                        if not kernel32.TerminateJobObject(self._job, 1):
                            raise ctypes.WinError(ctypes.get_last_error(), "zabicie Job Object polecenia")
                        for pid, handle in handles.items():
                            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                            waited = kernel32.WaitForSingleObject(handle, remaining_ms) & 0xFFFFFFFF
                            if waited == _WAIT_TIMEOUT:
                                self._survived(started, {pid: "WAIT_TIMEOUT"})
                                return
                            if waited:
                                self._survived(started, {pid: f"WAIT_FAILED, błąd {ctypes.get_last_error()}"})
                                return
                    finally:
                        for handle in handles.values():
                            kernel32.CloseHandle(handle)
                    if not handles:  # członek bez uchwytu już się kończy, a bez pauzy pętla kręciłaby się do terminu
                        time.sleep(_POLL_S)
            finally:
                kernel32.CloseHandle(self._job)
                self.process.wait()

        def _handles(self, members: list[int]) -> dict[int, wintypes.HANDLE]:
            """Uchwyty członków, którzy jeszcze istnieją: PID członka, który zdążył się skończyć, mógł już dostać
            proces spoza zadania, a na niego czekanie trwałoby do terminu."""

            kernel32 = self._kernel32
            handles = {}
            for pid in members:
                handle = wintypes.HANDLE(kernel32.OpenProcess(_SYNCHRONIZE | _QUERY_LIMITED_INFORMATION, False, pid))
                if handle.value and self._in_job(handle):
                    handles[pid] = handle
                elif handle.value:
                    kernel32.CloseHandle(handle)
            return handles

        def _in_job(self, handle: wintypes.HANDLE) -> bool:
            inside = wintypes.BOOL()
            return bool(self._kernel32.IsProcessInJob(handle, self._job, ctypes.byref(inside)) and inside.value)

        def _survived(self, started: float, alive: dict[int, str]) -> None:
            alive = {pid: "" for pid in self._members()} | alive
            named = ", ".join(f"{pid} {self._image(pid)}" + (f" ({why})" if why else "") for pid, why in alive.items())
            took = time.monotonic() - started
            print(f"potomne: po zabiciu po {took:.1f} s żyją procesy {named}", file=sys.stderr, flush=True)

        def _image(self, pid: int) -> str:
            kernel32 = self._kernel32
            handle = wintypes.HANDLE(kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid))
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            try:
                found = handle.value and kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size))
            finally:
                kernel32.CloseHandle(handle)
            return Path(path.value).name if found else "?"

        def _members(self) -> list[int]:
            """PID-y procesów zadania, najwyżej 64; resztę zabija to samo ``TerminateJobObject``, a łapie następne koło."""

            ids = _ProcessIds()
            if not self._kernel32.QueryInformationJobObject(
                self._job, _PROCESS_ID_LIST, ctypes.byref(ids), ctypes.sizeof(ids), None
            ):
                error = ctypes.get_last_error()
                if error != _ERROR_MORE_DATA:
                    raise ctypes.WinError(error, "członkowie Job Object polecenia")
            return list(ids.ProcessIdList[: ids.NumberOfProcessIdsInList])

else:

    class _Tree:
        def __init__(self, command: list[str], **popen: Any) -> None:
            self._guard = _guard()
            self.process = subprocess.Popen(command, start_new_session=True, **popen)
            try:
                self._guard.report("+", "drzewo", str(self.process.pid))
            except OSError:
                self.kill()
                raise

        def kill(self) -> None:
            _kill_group(self.process.pid)
            self.process.wait()
            with suppress(OSError):
                self._guard.report("-", "drzewo", str(self.process.pid))

    def _kill_group(group: int) -> None:
        """macOS odpowiada EPERM, gdy w grupie zostały same zombie."""

        with suppress(ProcessLookupError, PermissionError):
            os.killpg(group, signal.SIGKILL)


class _Guard:
    """Strażnik żyje dłużej niż narzędzie, więc nie trzyma jego wyjścia (wołający czekałby na EOF), jego katalogu
    (na Windows blokowałby usunięcie kopii) ani jego ``PYTHONPATH`` (``-I``)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=tempfile.gettempdir(),
            start_new_session=True,
        )

    def report(self, sign: str, kind: str, value: str, repo: str = "") -> None:
        assert self._process.stdin is not None
        line = json.dumps([sign, kind, value, repo]).encode() + b"\n"
        with self._lock:
            try:
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except OSError as error:
                raise OSError(f"strażnik procesów potomnych nie żyje, więc nie sprzątnie po zabitym narzędziu: {error}") from error


_guard_lock = threading.Lock()
_guard_started: _Guard | None = None


def _guard() -> _Guard:
    global _guard_started
    with _guard_lock:
        if _guard_started is None:
            _guard_started = _Guard()
        return _guard_started


def _remove_copy(repo: Path, copy: Path) -> None:
    # Drugie --force usuwa też worktree zablokowane przez ``worktree add`` zabite w trakcie.
    with _WORKTREES:
        removed = subprocess.run(
            ["git", "worktree", "remove", "--force", "--force", str(copy)], cwd=repo, capture_output=True, check=False
        )
    if removed.returncode == 0:
        return
    deadline = time.monotonic() + (_RELEASE_S if sys.platform == "win32" else 0)
    shutil.rmtree(copy, ignore_errors=True)
    while copy.exists() and time.monotonic() < deadline:
        time.sleep(_POLL_S)
        shutil.rmtree(copy, ignore_errors=True)
    with _WORKTREES:
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True, check=False)


def _guard_main() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C w konsoli Windows trafia do wszystkich jej procesów
    live: dict[tuple[str, str], str] = {}
    for line in sys.stdin.buffer:
        try:
            sign, kind, value, repo = json.loads(line)
        except ValueError:
            continue  # urwana linia narzędzia zabitego w trakcie zapisu
        if sign == "+":
            live[kind, value] = repo
        else:
            live.pop((kind, value), None)
    if sys.platform != "win32":
        for kind, value in live:
            if kind == "drzewo":
                _kill_group(int(value))
    for (kind, value), repo in live.items():
        if kind == "kopia":
            _remove_copy(Path(repo), Path(value))


if __name__ == "__main__":
    _guard_main()
