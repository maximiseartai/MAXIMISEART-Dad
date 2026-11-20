from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import IO, Final, Literal, TypeGuard

from rozliczenia.centrum.platform import NO_CONSOLE_WINDOW, run_console_program
from rozliczenia.file_state import file_state, path_taken
from rozliczenia.tool_files import REPOSITORY_URL, TOOL_ROOT, config_dir
from rozliczenia.wall_clock import epoch_s

BRANCH: Final = "main"

UPDATED: Final = "ok"
UP_TO_DATE: Final = "AKTUALNA"
NO_GIT: Final = "BRAK_GITA"
NO_CONNECTION: Final = "BRAK_POLACZENIA"
LOGIN: Final = "LOGOWANIE"
OTHER_BRANCH: Final = "INNA_GALAZ"
LOCAL_CHANGES: Final = "ZMIANY_NA_KOMPUTERZE"
UNEXPECTED: Final = "NIEOCZEKIWANY_BLAD"
LIBRARIES_FAILED: Final = "INSTALACJA_BIBLIOTEK"
NEW_VERSION_FAILED: Final = "NOWA_WERSJA_NIE_WYSTARTOWALA"
ROLLBACK_FAILED: Final = "COFNIECIE_NIEUDANE"

Step = Literal["fetching", "installing"]

RESULT_FILE: Final = "centrum-aktualizacja.json"
JOURNAL: Final = "centrum-aktualizacja-w-toku"
GUARDIAN_LEASE_S: Final = 10 * 60.0
_JOURNAL_FORMAT: Final = 1

_FETCHED_MAIN: Final = f"refs/remotes/origin/{BRANCH}"
_RELEASES: Final = "refs/wydania/"
_FETCH_TIMEOUT_S: Final = 120.0
_LOCAL_TIMEOUT_S: Final = 60.0
_TAGS_TIMEOUT_S: Final = 5.0
_STALLED_BYTES_PER_S: Final = 1000
_STALLED_FOR_S: Final = 30
_REQUIREMENTS: Final = "requirements.txt"
_INSTALL_TIMEOUT_S: Final = 15 * 60.0
_FOREIGN_VARIABLES: Final = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
)


_RELEASE_TAG: Final = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


@dataclass(frozen=True, order=True)
class Release:
    number: tuple[int, int, int]
    tag: str

    @classmethod
    def of_tag(cls, tag: str) -> Release | None:
        found = _RELEASE_TAG.fullmatch(tag)
        return None if found is None else cls((int(found[1]), int(found[2]), int(found[3])), tag)

    @property
    def version(self) -> str:
        return ".".join(map(str, self.number))


@dataclass(frozen=True)
class NewestRelease:
    commit: str | None
    skipped: tuple[str, ...] = ()
    release: Release | None = None


def newest_on_main(commits: Mapping[str, str], on_main: Callable[[str], bool]) -> NewestRelease:
    releases = sorted((release for tag in commits if (release := Release.of_tag(tag)) is not None), reverse=True)
    skipped: list[str] = []
    for release in releases:
        if on_main(commits[release.tag]):
            return NewestRelease(commits[release.tag], tuple(skipped), release)
        skipped.append(release.tag)
    return NewestRelease(None, tuple(skipped))


@dataclass(frozen=True)
class MainLine:
    tips: tuple[str, ...]
    releases: Mapping[str, str]

    def newest(self) -> NewestRelease:
        tips = frozenset(self.tips)
        return newest_on_main(self.releases, lambda commit: commit in tips)


def fetch_main_line(root: Path, origin: str) -> MainLine:
    git = find_git()
    if git is None:
        raise GitFailed(NO_GIT)
    run = _Git(git, root)
    failure = run.fetch(origin)
    if failure is not None:
        raise GitFailed(failure)
    return MainLine(_main_tips(run), _release_commits(run))


@dataclass(frozen=True)
class UpdateResult:
    code: str
    before: str | None
    after: str | None
    installed: bool = False
    skipped: tuple[str, ...] = ()


def write_result(path: Path, result: UpdateResult) -> None:
    record = {"wynik": result.code, "przed": result.before, "po": result.after, "biblioteki": result.installed}
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_result(path: Path) -> UpdateResult | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    code, before, after = record.get("wynik"), record.get("przed"), record.get("po")
    if not isinstance(code, str) or not _commit_or_none(before) or not _commit_or_none(after):
        return None
    return UpdateResult(code, before, after, record.get("biblioteki") is True)


def _commit_or_none(value: object) -> TypeGuard[str | None]:
    return value is None or isinstance(value, str)


def find_git(
    *,
    which: Callable[[str], str | None] = shutil.which,
    registry: Callable[[str], str | None] | None = None,
    environ: Mapping[str, str] = os.environ,
) -> Path | None:
    found = which("git")
    if found:
        return Path(found)
    install_path = registry or _registered_git_for_windows
    candidates = [Path(path, "cmd", "git.exe") for hive in ("HKLM", "HKCU") if (path := install_path(hive))]
    for variable, folders in (
        ("ProgramFiles", ("Git",)),
        ("ProgramFiles(x86)", ("Git",)),
        ("LOCALAPPDATA", ("Programs", "Git")),
    ):
        base = environ.get(variable)
        if base:
            candidates.append(Path(base, *folders, "cmd", "git.exe"))
    return next((candidate for candidate in candidates if file_state(candidate) == "file"), None)


def _registered_git_for_windows(hive: str) -> str | None:
    if sys.platform != "win32":
        return None
    else:
        import winreg

        root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
        try:
            with winreg.OpenKey(root, r"SOFTWARE\GitForWindows", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError:
            return None
        return value if isinstance(value, str) and value else None


def pip_install(requirements: Path) -> bool:
    # ZEWNĘTRZNE: pip bez --user sam instaluje dla użytkownika, gdy nie może pisać do katalogu bibliotek Pythona (https://pip.pypa.io/en/stable/news/#v20-0)
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet"]
    try:
        result = run_console_program(
            [*command, "-r", str(requirements)], cwd=requirements.parent, timeout_s=_INSTALL_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class GitFailed(Exception):
    ...


class JournalKept(Exception):
    ...


@dataclass(frozen=True)
class InterruptedUpdate:
    before: str
    after: str
    guardian_until: float | None = None

    def guardian_may_run(self, now: float) -> bool:
        return self.guardian_until is not None and now < self.guardian_until


@dataclass(frozen=True)
class ToolClone:
    root: Path
    origin: str = REPOSITORY_URL
    find_git: Callable[[], Path | None] = find_git
    install: Callable[[Path], bool] = pip_install

    @classmethod
    def of_system(cls) -> ToolClone:
        return cls(TOOL_ROOT)

    def update(self, on_step: Callable[[Step], None] = lambda step: None) -> UpdateResult:
        git = self.find_git()
        if git is None:
            return UpdateResult(NO_GIT, None, None)
        run = _Git(git, self.root)
        journal = self._journal
        interrupted = journal.read()
        if interrupted is not None and not interrupted.guardian_may_run(epoch_s()):
            if not _moved_back(run, journal):
                return UpdateResult(ROLLBACK_FAILED, interrupted.before, interrupted.after)
        before = run.text("rev-parse", "HEAD")
        if run.branch() != BRANCH:
            return UpdateResult(OTHER_BRANCH, before, None)
        on_step("fetching")
        fetch_failure = run.fetch(self.origin)
        if fetch_failure is not None:
            return UpdateResult(fetch_failure, before, None)
        newest = MainLine(_main_tips(run), _release_commits(run)).newest()
        after, skipped = newest.commit, newest.skipped
        if after is None or run.is_ancestor(after, before):
            return UpdateResult(UP_TO_DATE, before, before, skipped=skipped)
        dad_files = _DadFiles.leaving(run, after)
        if _has_local_commits(run, after) or _changed_tracked_files(run, keep=frozenset(dad_files.names)):
            return UpdateResult(LOCAL_CHANGES, before, None, skipped=skipped)
        journal.begin(self.root, dad_files.names, before, after)
        moved = False
        try:
            with dad_files.set_aside(run, journal.backup):
                moved = run.run("merge", "--ff-only", "--quiet", after).returncode == 0
        except _NotPutBack:
            if moved and _moved_back(run, journal):
                return UpdateResult(UNEXPECTED, before, after)
            return UpdateResult(ROLLBACK_FAILED, before, after if moved else None)
        except _NotSetAside:
            journal.end()
            raise
        if not moved:
            journal.end()
            return UpdateResult(LOCAL_CHANGES, before, None)
        try:
            installed = self._install_libraries(run, before, after, on_step)
        except Exception:
            if _moved_back(run, journal):
                raise
            return UpdateResult(ROLLBACK_FAILED, before, after, installed=True)
        if installed is False:
            code = LIBRARIES_FAILED if _moved_back(run, journal) else ROLLBACK_FAILED
            return UpdateResult(code, before, after, installed=True)
        return UpdateResult(UPDATED, before, after, installed=installed is True, skipped=skipped)

    def _install_libraries(self, run: _Git, before: str, after: str, on_step: Callable[[Step], None]) -> bool | None:
        if not run.changed(before, after, _REQUIREMENTS):
            return None
        on_step("installing")
        return self.install(self.root / _REQUIREMENTS)

    def roll_back(self) -> None:
        git = self.find_git()
        if git is None:
            raise GitFailed("brak Gita")
        _roll_back(_Git(git, self.root), self._journal)

    def interrupted_update(self) -> InterruptedUpdate | None:
        return self._journal.read()

    @contextmanager
    def leased_to_guardian(self) -> Iterator[None]:
        self._journal.lease(epoch_s() + GUARDIAN_LEASE_S)
        try:
            yield
        except BaseException:
            self._journal.lease(None)
            raise

    def confirm_update(self) -> None:
        self._journal.end()

    @property
    def _journal(self) -> _Journal:
        return _Journal(config_dir(self.root) / JOURNAL)


def _roll_back(git: _Git, journal: _Journal) -> None:
    update = journal.read()
    if update is None:
        raise JournalKept("brak dziennika")
    if git.text("rev-parse", "HEAD") not in (update.before, update.after):
        raise JournalKept("klon na innym commicie")
    names = [copy.relative_to(journal.backup).as_posix() for copy in journal.backup.rglob("*") if file_state(copy) == "file"]
    for name in names:
        (git.root / name).unlink(missing_ok=True)
    try:
        git.check("reset", "--keep", "--quiet", update.before)
    finally:
        _put_back(git.root, journal.backup, names)
    journal.end()


def _moved_back(git: _Git, journal: _Journal) -> bool:
    try:
        _roll_back(git, journal)
    except (GitFailed, OSError, subprocess.SubprocessError, JournalKept):
        return False
    return True


def _put_back(root: Path, backup: Path, names: Iterable[str]) -> None:
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / name, target)


def contains_commit(root: Path, ancestor: str, descendant: str) -> bool:
    if ancestor == descendant:
        return True
    git = find_git()
    if git is None:
        return False
    try:
        return _Git(git, root).is_ancestor(ancestor, descendant)
    except (GitFailed, OSError, subprocess.SubprocessError):
        return False


def release_at(root: Path, commit: str, *, find_git: Callable[[], Path | None] = find_git) -> Release | None:
    git = find_git()
    if git is None:
        return None
    try:
        listed = _Git(git, root).output(
            "for-each-ref",
            f"--points-at={commit}",
            "--format=%(refname:lstrip=2)",
            _RELEASES,
            "refs/tags/",
            timeout_s=_TAGS_TIMEOUT_S,
        )
    except (GitFailed, OSError, subprocess.SubprocessError):
        return None
    return max((release for tag in listed.split() if (release := Release.of_tag(tag)) is not None), default=None)


def _main_tips(run: _Git) -> tuple[str, ...]:
    return tuple(run.output("rev-list", "--first-parent", _FETCHED_MAIN).split())


def _release_commits(run: _Git) -> dict[str, str]:
    # ZEWNĘTRZNE: cmd.exe zjada „^” w argumentach pliku .cmd, którym jest Git w testach na Windows, więc commit tagu z opisem daje format for-each-ref, a nie tag^{commit} (https://learn.microsoft.com/windows-server/administration/windows-commands/cmd)
    listed = run.output(
        "for-each-ref", "--format=%(refname:lstrip=2) %(objecttype) %(objectname) %(*objecttype) %(*objectname)", _RELEASES
    )
    commits: dict[str, str] = {}
    for line in listed.splitlines():
        name, kind, target, *peeled = line.split()
        kind, target = (peeled[0], peeled[1]) if peeled else (kind, target)
        if kind == "commit":
            commits[name] = target
    return commits


def _has_local_commits(run: _Git, target: str) -> bool:
    return run.text("rev-list", "--count", f"{target}..HEAD") != "0"


def _changed_tracked_files(run: _Git, *, keep: frozenset[str]) -> bool:
    entries = run.entries("status", "--porcelain=v1", "-z", "--untracked-files=no", "--no-renames")
    return any(entry[3:] not in keep for entry in entries)


class _NotSetAside(GitFailed):
    ...


class _NotPutBack(Exception):
    ...


@dataclass(frozen=True)
class _Journal:
    directory: Path

    @property
    def backup(self) -> Path:
        return self.directory / "pliki-taty"

    @property
    def _state(self) -> Path:
        return self.directory / "stan.json"

    def read(self) -> InterruptedUpdate | None:
        try:
            record = json.loads(self._state.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as unreadable:
            raise JournalKept("nieczytelny") from unreadable
        if not isinstance(record, dict) or record.get("format") != _JOURNAL_FORMAT:
            raise JournalKept("nieznany format")
        before, after, until = record.get("przed"), record.get("po"), record.get("opiekun_do")
        if not isinstance(before, str) or not isinstance(after, str):
            raise JournalKept("bez commitów")
        if not isinstance(until, (int, float)) or isinstance(until, bool):
            until = None
        return InterruptedUpdate(before, after, until)

    def begin(self, root: Path, names: Iterable[str], before: str, after: str) -> None:
        if path_taken(self._state):
            raise JournalKept("poprzednia aktualizacja w toku")
        self.end()
        for name in names:
            copy = self.backup / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, copy)
            _flush_to_disk(copy)
        self._write(InterruptedUpdate(before, after))

    def lease(self, until: float | None) -> None:
        update = self.read()
        if update is None:
            raise JournalKept("brak dziennika")
        self._write(replace(update, guardian_until=until))

    def end(self) -> None:
        self._state.unlink(missing_ok=True)
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write(self, update: InterruptedUpdate) -> None:
        record = {"format": _JOURNAL_FORMAT, "przed": update.before, "po": update.after, "opiekun_do": update.guardian_until}
        temporary = self._state.with_name(self._state.name + ".tmp")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
        _flush_to_disk(temporary)
        os.replace(temporary, self._state)


def _flush_to_disk(path: Path) -> None:
    with path.open("r+b") as written:
        os.fsync(written.fileno())


@dataclass(frozen=True)
class _DadFiles:
    names: tuple[str, ...]

    @classmethod
    def leaving(cls, git: _Git, fetched: str) -> _DadFiles:
        listed = git.output(
            "diff", "--name-only", "-z", "--no-renames", "--diff-filter=D", "HEAD", fetched, "--", "config/"
        )
        return cls(tuple(name for name in listed.split("\0") if name and file_state(git.root / name) != "missing"))

    @contextmanager
    def set_aside(self, git: _Git, backup: Path) -> Iterator[None]:
        try:
            restored = (f":(literal){name}" for name in self.names)
            if self.names and git.run("checkout", "HEAD", "--", *restored).returncode != 0:
                raise _NotSetAside("checkout")
            yield
        finally:
            try:
                _put_back(git.root, backup, self.names)
            except OSError as failure:
                raise _NotPutBack from failure


@dataclass(frozen=True)
class _Git:
    executable: Path
    root: Path

    def run(self, *args: str, timeout_s: float = _LOCAL_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
        command = [
            str(self.executable),
            # ZEWNĘTRZNE: Git odmawia pracy w repozytorium innego właściciela niż użytkownik, który go uruchomił, dopóki to repozytorium nie stoi w safe.directory (https://git-scm.com/docs/git-config#Documentation/git-config.txt-safedirectory)
            "-c",
            f"safe.directory={self.root.as_posix()}",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-C",
            str(self.root),
            *args,
        ]
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            returncode = _run_tree(command, env=_quiet_environment(), stdout=output, stderr=errors, timeout_s=timeout_s)
            return subprocess.CompletedProcess(command, returncode, _text_of(output), _text_of(errors))

    def check(self, *args: str) -> None:
        if self.run(*args).returncode != 0:
            raise GitFailed(args[0])

    def text(self, *args: str) -> str:
        return self.output(*args).strip()

    def entries(self, *args: str) -> list[str]:
        return [entry for entry in self.output(*args).split("\0") if entry]

    def branch(self) -> str | None:
        result = self.run("symbolic-ref", "--quiet", "--short", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else None

    def output(self, *args: str, timeout_s: float = _LOCAL_TIMEOUT_S) -> str:
        result = self.run(*args, timeout_s=timeout_s)
        if result.returncode != 0:
            raise GitFailed(args[0])
        return result.stdout

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = self.run("merge-base", "--is-ancestor", ancestor, descendant)
        if result.returncode not in (0, 1):
            raise GitFailed("merge-base")
        return result.returncode == 0

    def changed(self, before: str, after: str, name: str) -> bool:
        result = self.run("diff", "--quiet", "--no-renames", "--diff-filter=AM", before, after, "--", f":(literal){name}")
        if result.returncode not in (0, 1):
            raise GitFailed("diff")
        return result.returncode == 1

    def fetch(self, origin: str) -> str | None:
        try:
            result = self.run(
                "-c",
                "http.proxy=",
                "-c",
                f"http.lowSpeedLimit={_STALLED_BYTES_PER_S}",
                "-c",
                f"http.lowSpeedTime={_STALLED_FOR_S}",
                "fetch",
                "--quiet",
                "--no-tags",
                "--prune",
                origin,
                f"+refs/heads/{BRANCH}:{_FETCHED_MAIN}",
                f"+refs/tags/v*:{_RELEASES}v*",
                timeout_s=_FETCH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return NO_CONNECTION
        if result.returncode == 0:
            return None
        asked_for_login = any(sign in result.stderr.lower() for sign in _ENGLISH_LOGIN_SIGNS)
        return LOGIN if asked_for_login else NO_CONNECTION


# ZEWNĘTRZNE: GitHub prosi o logowanie także przy repozytorium, którego nie widzi (https://docs.github.com/en/repositories/creating-and-managing-repositories/troubleshooting-cloning-errors)
_ENGLISH_LOGIN_SIGNS: Final = (
    "terminal prompts disabled",
    "could not read username",
    "could not read password",
    "authentication failed",
)
_GIT_IN_ENGLISH: Final[Mapping[str, str]] = {"LC_ALL": "C", "LANGUAGE": "C"}


def _text_of(file: IO[bytes]) -> str:
    file.seek(0)
    return file.read().decode("utf-8", errors="replace")


_KILL_TIMEOUT_S: Final = 10.0

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _JobObjectBasicProcessIdList(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", wintypes.DWORD),
            ("NumberOfProcessIdsInList", wintypes.DWORD),
            ("ProcessIdList", ctypes.c_size_t * 64),
        ]

    _CREATE_SUSPENDED: Final = 0x0004
    _PROCESS_ID_LIST: Final = 3
    _ERROR_MORE_DATA: Final = 234
    _SYNCHRONIZE: Final = 0x00100000
    _TERMINATE_SET_QUOTA_AND_RESUME: Final = 0x0901
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = _kernel32.OpenProcess.restype = wintypes.HANDLE

    def _run_tree(
        command: list[str], *, env: Mapping[str, str], stdout: IO[bytes], stderr: IO[bytes], timeout_s: float
    ) -> int:
        job = wintypes.HANDLE(_kernel32.CreateJobObjectW(None, None))
        if not job.value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # ZEWNĘTRZNE: proces, który Git uruchomi, zanim sam trafi do zadania, zostaje poza zadaniem (https://learn.microsoft.com/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)
            process = subprocess.Popen(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=NO_CONSOLE_WINDOW | _CREATE_SUSPENDED,
            )
            try:
                _join(job, process.pid)
            except BaseException:
                process.kill()
                process.wait()
                raise
            try:
                return process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                deadline = time.monotonic() + _KILL_TIMEOUT_S
                while members := _members(job):
                    if time.monotonic() >= deadline:
                        raise OSError("drzewo procesów Gita przeżyło zabicie") from None
                    # ZEWNĘTRZNE: zabicie procesu w Windows kończy się dopiero, gdy jego uchwyt jest zasygnalizowany, a z listy procesów zadania proces może zniknąć wcześniej (https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)
                    opened = (wintypes.HANDLE(_kernel32.OpenProcess(_SYNCHRONIZE, False, pid)) for pid in members)
                    handles = [handle for handle in opened if handle.value]
                    try:
                        if not _kernel32.TerminateJobObject(job, 1):
                            raise ctypes.WinError(ctypes.get_last_error()) from None
                        for handle in handles:
                            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                            if _kernel32.WaitForSingleObject(handle, remaining_ms) != 0:
                                raise OSError("drzewo procesów Gita przeżyło zabicie") from None
                    finally:
                        for handle in handles:
                            _kernel32.CloseHandle(handle)
                process.wait()
                raise
        finally:
            _kernel32.CloseHandle(job)

    def _join(job: wintypes.HANDLE, pid: int) -> None:
        handle = wintypes.HANDLE(_kernel32.OpenProcess(_TERMINATE_SET_QUOTA_AND_RESUME, False, pid))
        if not handle.value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _kernel32.AssignProcessToJobObject(job, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            # ZEWNĘTRZNE: subprocess.Popen w Windows zamyka uchwyt głównego wątku procesu, więc wstrzymany proces wznawia się cały, bez ResumeThread (https://github.com/python/cpython/blob/main/Lib/subprocess.py)
            status = ctypes.WinDLL("ntdll").NtResumeProcess(handle)
            if status != 0:
                raise OSError(f"NtResumeProcess: NTSTATUS 0x{status & 0xFFFFFFFF:08X}")
        finally:
            _kernel32.CloseHandle(handle)

    def _members(job: wintypes.HANDLE) -> list[int]:
        ids = _JobObjectBasicProcessIdList()
        if not _kernel32.QueryInformationJobObject(job, _PROCESS_ID_LIST, ctypes.byref(ids), ctypes.sizeof(ids), None):
            error = ctypes.get_last_error()
            if error != _ERROR_MORE_DATA:
                raise ctypes.WinError(error)
        return list(ids.ProcessIdList[: ids.NumberOfProcessIdsInList])

else:

    def _run_tree(
        command: list[str], *, env: Mapping[str, str], stdout: IO[bytes], stderr: IO[bytes], timeout_s: float
    ) -> int:
        process = subprocess.Popen(
            command, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True
        )
        try:
            return process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            with suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
            process.kill()
            process.wait()
            raise


def _quiet_environment() -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if name not in _FOREIGN_VARIABLES}
    return {**environment, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", **_GIT_IN_ENGLISH}
