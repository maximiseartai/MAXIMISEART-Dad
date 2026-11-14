"""``tools/lib/potomne.py``: drzewo procesów polecenia i kopia commitu nie przeżywają wyniku ani narzędzia.

Macierz przypadków biegnie raz, na interfejsie modułu i na prawdziwych procesach. Narzędzia, które go
używają, mają po jednym teście, że ich procesy giną razem z nimi. Tu biegnie też macierz drogi narzędzi do gita
(``tools/lib/repo.py``): scalenie bez worktree i git bez konserwacji w tle, która usuwa kopie commitów (#312).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Sequence
import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import pytest

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_config import computer_git_config
from tests.fixtures.git_repo import commit, git
from tests.fixtures.potomne import beating, wait_for, with_grandchild, worktrees
import potomne
import repo
from tests.fixtures.skladnia import dotted, imports

TOOLS = Path(__file__).resolve().parents[1] / "tools"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="sesje, grupy procesów i sygnały są tylko na POSIX")
OWN_TREE_OR_COPY = re.compile(
    r"killpg|taskkill|start_new_session|process_group|setsid|setpgid|setpgrp|CreateJobObject|CREATE_NEW_PROCESS_GROUP"
    r"|[\"']worktree[\"'],\s*[\"']add[\"']"
)


def _repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "--quiet")
    (path / "plik.txt").write_text("w commicie\n", encoding="utf-8")
    commit(path, "baza")
    (path / "plik.txt").write_text("w checkoucie\n", encoding="utf-8")
    return path


def test_potomek_trzymajacy_wyjscie_ginie_z_koncem_polecenia_a_wynik_jest_pelny(tmp_path: Path) -> None:
    beats = tmp_path / "wnuk-zyje"

    done = potomne.run(
        with_grandchild(beats, "print('gotowe'); print('uwaga', file=sys.stderr); sys.exit(3)"), cwd=tmp_path
    )

    assert (done.returncode, done.stdout, done.stderr) == (3, "gotowe\n", "uwaga\n")
    assert not beating(beats)


def test_echo_drukuje_wyjscie_razem_z_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = "import sys; print('a', flush=True); print('b', file=sys.stderr, flush=True)"

    done = potomne.run([sys.executable, "-c", code], cwd=tmp_path, echo=True)

    assert (done.stdout, done.stderr, capsys.readouterr().out) == ("a\nb\n", "", "a\nb\n")


def test_po_limicie_drzewo_ginie_a_run_rzuca_timeout_z_wyjsciem_wypisanym_przed_limitem(tmp_path: Path) -> None:
    beats = tmp_path / "wnuk-zyje"
    then = "print('a', flush=True); print('b', file=sys.stderr, flush=True); time.sleep(60)"

    with pytest.raises(potomne.TimeoutExpired) as expired:
        potomne.run(with_grandchild(beats, then), cwd=tmp_path, timeout=5)

    assert expired.value.printed == ("a\n", "b\n")
    assert not beating(beats)


def test_wnuk_uruchomiony_zanim_narzedzie_wroci_ze_startu_polecenia_ginie_z_drzewem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beats = tmp_path / "wnuk-zyje"
    start = subprocess.Popen
    returned: list[float] = []
    # Na Windows polecenie stoi wstrzymane, aż Popen wróci, więc wnuk dopiero startuje, gdy limit już biegnie.
    limit = 5 if sys.platform == "win32" else 1

    def descheduled_after_start(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        process = start(*args, **kwargs)
        wait_for(beats.exists, 3)
        returned.append(time.monotonic())
        return process

    monkeypatch.setattr(subprocess, "Popen", descheduled_after_start)
    with pytest.raises(subprocess.TimeoutExpired):
        potomne.run(with_grandchild(beats, "time.sleep(60)"), cwd=tmp_path, timeout=limit)

    assert time.monotonic() - returned[-1] < 2 * limit
    assert not beating(beats)


if sys.platform == "win32":
    import ctypes

    def _ctrl_c(handle: object) -> int:
        raise KeyboardInterrupt

    def _access_denied(handle: object) -> int:
        return -0x3FFFFFDE  # STATUS_ACCESS_DENIED

    @pytest.mark.parametrize(
        ("resume", "error"),
        [(_ctrl_c, KeyboardInterrupt), (_access_denied, PermissionError)],
        ids=["ctrl-c-przed-wznowieniem", "wznowienie-odmowione"],
    )
    def test_polecenie_niewznowione_w_job_object_ginie_zamiast_zostac_wstrzymane(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: Callable[[object], int], error: type[BaseException]
    ) -> None:
        started: list[subprocess.Popen[str]] = []
        start, load = subprocess.Popen, ctypes.WinDLL

        def recorded(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
            started.append(start(*args, **kwargs))
            return started[-1]

        class Ntdll:
            def __getattr__(self, name: str) -> Any:
                return getattr(load("ntdll"), name)

            def NtResumeProcess(self, handle: object) -> int:  # noqa: N802 - nazwa funkcji WinAPI
                return resume(handle)

        monkeypatch.setattr(subprocess, "Popen", recorded)
        monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kwargs: Ntdll() if name == "ntdll" else load(name, **kwargs))
        try:
            with pytest.raises(error):
                potomne.run([sys.executable, "-c", "pass"], cwd=tmp_path)
        finally:
            left = [process for process in started if process.poll() is None]
            for process in left:
                process.kill()

        assert (len(started), left) == (1, [])

    _NO_PROCESS = 0xFFFFFFFC  # PID, którego system nie ma, więc OpenProcess go nie otwiera
    _SURVIVORS = re.compile(r"potomne: po zabiciu po [\d.]+ s żyją procesy (.*)")

    @pytest.mark.parametrize(
        ("outlives", "reported"),
        [(False, None), (True, r"python\S*\.exe \(WAIT_TIMEOUT\)")],
        ids=["pid-czlonka-dostal-proces-spoza-zadania", "czlonek-zyje-po-terminie"],
    )
    def test_zabijanie_czeka_tylko_na_procesy_zadania_a_po_terminie_nie_wywraca_wyniku(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], outlives: bool, reported: str | None
    ) -> None:
        members, calls = potomne._Tree._members, []

        def reused_once(tree: Any) -> list[int]:
            calls.append(tree)
            return [*members(tree), *([os.getpid()] if len(calls) == 1 else [])]

        monkeypatch.setattr(potomne, "_KILL_S", 1.0)
        monkeypatch.setattr(potomne._Tree, "_members", reused_once)
        if outlives:
            monkeypatch.setattr(potomne._Tree, "_in_job", lambda tree, handle: True)

        done = potomne.run([sys.executable, "-c", "print('gotowe')"], cwd=tmp_path)

        named = _SURVIVORS.findall(capsys.readouterr().err)
        assert done.stdout == "gotowe\n"
        if reported is None:
            assert named == []
        else:
            assert len(named) == 1 and re.fullmatch(rf"{os.getpid()} {reported}", named[0]), named

    def test_czlonek_bez_uchwytu_nie_kreci_petla_zabijania_az_do_terminu(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        members, calls = potomne._Tree._members, []

        def with_unopenable(tree: Any) -> list[int]:
            calls.append(tree)
            return [*members(tree), _NO_PROCESS]

        monkeypatch.setattr(potomne, "_KILL_S", 1.0)
        monkeypatch.setattr(potomne._Tree, "_members", with_unopenable)

        done = potomne.run([sys.executable, "-c", "print('gotowe')"], cwd=tmp_path)

        assert done.stdout == "gotowe\n"
        assert _SURVIVORS.findall(capsys.readouterr().err) == [f"{_NO_PROCESS} ?"]
        assert len(calls) <= 2 * potomne._KILL_S / potomne._POLL_S


def test_stop_konczy_trwajace_polecenie_a_nowe_nie_biegnie(tmp_path: Path) -> None:
    beats, marker = tmp_path / "wnuk-zyje", tmp_path / "nowe-polecenie"
    stop = threading.Event()
    raised: list[str] = []

    def running() -> None:
        try:
            potomne.run(with_grandchild(beats, "time.sleep(60)"), cwd=tmp_path, stop=stop)
        except potomne.Stopped:
            raised.append("Stopped")

    thread = threading.Thread(target=running)
    thread.start()
    wait_for(beats.exists)
    stop.set()
    thread.join(timeout=10)

    assert raised == ["Stopped"]
    assert not beating(beats)
    with pytest.raises(potomne.Stopped):
        potomne.run([sys.executable, "-c", f"open({str(marker)!r}, 'w')"], cwd=tmp_path, stop=stop)
    assert not wait_for(marker.exists, 1)


@POSIX_ONLY
def test_grupa_z_samymi_zombie_nie_wywraca_konca_polecenia(tmp_path: Path) -> None:
    ready = tmp_path / "potomek-gotowy"
    child = (
        "import os, pathlib, subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'pass'])\n"
        "os.setsid()\n"
        f"time.sleep(1)\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(600)\n"
    )
    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"while not pathlib.Path({str(ready)!r}).exists():\n    time.sleep(0.05)\n"
        "print('gotowe')\n"
    )

    try:
        done = potomne.run([sys.executable, "-c", code], cwd=tmp_path, timeout=60)
    finally:
        if ready.exists():
            os.kill(int(ready.read_text()), signal.SIGTERM)

    assert (done.returncode, done.stdout) == (0, "gotowe\n")


@POSIX_ONLY
def test_potomek_spoza_drzewa_z_otwartym_wyjsciem_nie_wstrzymuje_wyniku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(potomne, "_DRAIN_S", 1.0)
    ready = tmp_path / "potomek-gotowy"
    child = f"import os, pathlib, time\nos.setsid()\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n"
    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        f"while not pathlib.Path({str(ready)!r}).exists():\n    time.sleep(0.05)\n"
        "print(time.time())\n"
    )

    try:
        done = potomne.run([sys.executable, "-c", code], cwd=tmp_path)
        returned = time.time()
    finally:
        os.kill(int(ready.read_text()), signal.SIGTERM)

    assert done.returncode == 0
    assert returned - float(done.stdout) < 2 * potomne._DRAIN_S


@pytest.mark.parametrize("ending", ["koniec bloku", "wyjątek", "zablokowana kopia"])
def test_kopia_commitu_ma_jego_drzewo_i_znika_z_blokiem(tmp_path: Path, ending: str) -> None:
    repo = _repository(tmp_path / "repo")
    seen: tuple[str, int] | None = None

    with contextlib.suppress(RuntimeError), potomne.commit_copy(repo, "HEAD") as copy:
        seen = ((copy / "plik.txt").read_text(encoding="utf-8"), len(worktrees(repo)))
        if ending == "zablokowana kopia":
            git(repo, "worktree", "lock", str(copy))
        if ending == "wyjątek":
            raise RuntimeError

    assert seen == ("w commicie\n", 2)
    assert (copy.exists(), len(worktrees(repo))) == (False, 1)


@pytest.mark.parametrize("change", ["inny plik", "ta sama linia"])
def test_scalenie_bez_worktree_daje_drzewo_scalenia_i_pliki_z_konfliktem(tmp_path: Path, change: str) -> None:
    path = _repository(tmp_path / "repo")
    commit(path, "stan checkoutu")
    git(path, "checkout", "--quiet", "-b", "druga")
    (path / ("inny.txt" if change == "inny plik" else "plik.txt")).write_text("z drugiej\n", encoding="utf-8")
    commit(path, "druga")
    git(path, "checkout", "--quiet", "-")
    (path / "plik.txt").write_text("z pierwszej\n", encoding="utf-8")
    commit(path, "pierwsza")

    merged = repo.merge_tree(path, "HEAD", "druga")

    files = sorted(git(path, "ls-tree", "--name-only", merged.tree).split())
    assert (merged.conflicts, files) == (((), ["inny.txt", "plik.txt"]) if change == "inny plik" else (("plik.txt",), ["plik.txt"]))


def test_scalenie_historii_bez_wspolnej_bazy_to_blad_gita_a_nie_konflikt(tmp_path: Path) -> None:
    path = _repository(tmp_path / "repo")
    git(path, "checkout", "--quiet", "--orphan", "obca")
    commit(path, "bez wspólnej historii")

    with pytest.raises(subprocess.CalledProcessError, match=r"merge-tree") as raised:
        repo.merge_tree(path, "obca", "main")

    assert raised.value.returncode not in (0, 1) and "unrelated histories" in raised.value.stderr


def test_git_narzedzia_nie_uruchamia_konserwacji_w_tle_takze_gdy_komputer_ja_wlacza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _repository(tmp_path / "repo")
    trace = tmp_path / "trace2.json"
    config = computer_git_config(tmp_path / "gitconfig", "[maintenance]\n\tauto = true\n\tautoDetach = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    # Wpis konfiguracji wołającego zostaje obok wyłączonej konserwacji.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "z wołającego")
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))

    repo.git(path, "commit", "--quiet", "--allow-empty", "--message", "x")

    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    started = [event["argv"] for event in events if event["event"] == "child_start" and "maintenance" in event["argv"]]
    assert (started, git(path, "log", "-1", "--format=%an")) == ([], "z wołającego")


def test_nieudana_kopia_commitu_niesie_komunikat_gita(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")

    with pytest.raises(subprocess.CalledProcessError) as raised, potomne.commit_copy(repo, "nie-ma-takiego-commitu"):
        pass

    said = raised.value.stderr.strip()
    assert said and said in str(raised.value)
    assert len(worktrees(repo)) == 1


# Atrapa gita zapisuje początek i koniec każdego polecenia, które zmienia .git/worktrees; ``add`` trwa sekundę dłużej.
WORKTREE_LOG = """import os, subprocess, sys, time
real, arguments = os.environ["SHIM_GIT"], sys.argv[1:]
if arguments[:1] != ["worktree"] or arguments[1:2] not in (["add"], ["remove"], ["prune"]):
    os.execv(real, [real, *arguments])
with open(os.environ["SHIM_LOG"], "a") as log:
    log.write(f"start {arguments[1]}\\n")
if arguments[1] == "add":
    time.sleep(1)
code = subprocess.call([real, *arguments])
with open(os.environ["SHIM_LOG"], "a") as log:
    log.write(f"end {arguments[1]}\\n")
sys.exit(code)
"""


def _overlapping(log: list[str]) -> list[str]:
    running: list[str] = []
    found = []
    for line in log:
        state, command = line.split()
        if state == "end":
            running.remove(command)
            continue
        if running:
            found.append(f"{command} w trakcie {', '.join(running)}")
        running.append(command)
    return found


@POSIX_ONLY
@pytest.mark.parametrize("place", ["wątek", "inny proces"])
def test_kopie_commitu_z_wielu_watkow_i_procesow_nie_zmieniaja_worktree_naraz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str
) -> None:
    repo = _repository(tmp_path / "repo")
    log, shim = tmp_path / "git.log", fake_cli(tmp_path / "atrapa", "git", WORKTREE_LOG)
    monkeypatch.setenv("SHIM_GIT", str(shutil.which("git")))
    monkeypatch.setenv("SHIM_LOG", str(log))
    monkeypatch.setenv("PATH", f"{shim.parent}{os.pathsep}{os.environ['PATH']}")
    seen: list[str] = []
    # Workery pytest-xdist i narzędzia z kilku worktree robią kopie jednego repozytorium z osobnych procesów (#1312).
    code = (
        f"import pathlib, sys\nsys.path.insert(0, {str(TOOLS / 'lib')!r})\nimport potomne\n"
        f"with potomne.commit_copy(pathlib.Path({str(repo)!r}), 'HEAD') as copy:\n"
        "    print((copy / 'plik.txt').read_text(encoding='utf-8'), end='')\n"
    )

    def second_copy() -> None:
        if place == "inny proces":
            seen.append(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True).stdout)
            return
        with potomne.commit_copy(repo, "HEAD") as copy:
            seen.append((copy / "plik.txt").read_text(encoding="utf-8"))

    with potomne.commit_copy(repo, "HEAD") as copy:
        seen.append((copy / "plik.txt").read_text(encoding="utf-8"))
        second = threading.Thread(target=second_copy)
        second.start()
        wait_for(lambda: log.read_text(encoding="utf-8").count("start add") == 2, 30)
    second.join(timeout=60)

    assert seen == ["w commicie\n", "w commicie\n"]
    assert _overlapping(log.read_text(encoding="utf-8").splitlines()) == []


def _kill(tool: subprocess.Popen[bytes]) -> None:
    tool.kill()


TOOL_STOPS: dict[str, Callable[[subprocess.Popen[bytes]], None]] = {"SIGKILL narzędzia": _kill}
if sys.platform != "win32":

    def _kill_group(tool: subprocess.Popen[bytes]) -> None:
        os.killpg(tool.pid, signal.SIGKILL)

    def _ctrl_c(tool: subprocess.Popen[bytes]) -> None:
        os.killpg(tool.pid, signal.SIGINT)

    TOOL_STOPS |= {"SIGKILL grupy narzędzia": _kill_group, "Ctrl+C": _ctrl_c}


@pytest.mark.parametrize("stop", sorted(TOOL_STOPS))
def test_zabite_narzedzie_nie_zostawia_drzewa_ani_kopii(tmp_path: Path, stop: str) -> None:
    repo = _repository(tmp_path / "repo")
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    beats = tmp_path / "wnuk-zyje"
    code = (
        f"import pathlib, sys\nsys.path.insert(0, {str(TOOLS / 'lib')!r})\nimport potomne\n"
        f"with potomne.commit_copy(pathlib.Path({str(repo)!r}), 'HEAD') as copy:\n"
        f"    potomne.run({with_grandchild(beats, 'time.sleep(60)')!r}, cwd=copy)\n"
    )
    tool = subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    try:
        wait_for(beats.exists)
        assert beats.exists(), "narzędzie nie uruchomiło polecenia"

        TOOL_STOPS[stop](tool)
        tool.wait(timeout=20)
        wait_for(lambda: not any(scratch.iterdir()), seconds=20)

        assert not beating(beats)
        assert (list(scratch.iterdir()), len(worktrees(repo))) == ([], 1)
    finally:
        tool.kill()
        tool.wait()


@POSIX_ONLY
def test_bez_straznika_narzedzie_przerywa_zamiast_dzialac_bez_sprzatania(tmp_path: Path) -> None:
    code = (
        f"import os, pathlib, signal, subprocess, sys\nsys.path.insert(0, {str(TOOLS / 'lib')!r})\nimport potomne\n"
        "here = pathlib.Path.cwd()\n"
        "potomne.run([sys.executable, '-c', 'pass'], cwd=here)\n"
        "found = subprocess.run(['pgrep', '-P', str(os.getpid()), '-f', 'potomne.py'], capture_output=True, text=True)\n"
        "guard = int(found.stdout.split()[0])\n"
        "os.kill(guard, signal.SIGKILL)\n"
        "os.waitpid(guard, 0)\n"
        "for name, attempt in [('run', lambda: potomne.run([sys.executable, '-c', 'pass'], cwd=here)),\n"
        "                      ('commit_copy', lambda: potomne.commit_copy(here, 'HEAD').__enter__())]:\n"
        "    try:\n"
        "        attempt()\n"
        "        print(name, 'bez błędu')\n"
        "    except OSError as error:\n"
        "        print(name, type(error).__name__, 'strażnik' in str(error))\n"
    )

    answered = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False
    )

    assert answered.stdout.splitlines() == ["run OSError True", "commit_copy OSError True"], answered.stderr


def _tool_sources() -> list[Path]:
    return sorted(path for path in [*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push"] if path != TOOLS / "lib" / "potomne.py")


def test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne() -> None:
    found = [
        f"{path.relative_to(TOOLS.parent).as_posix()}:{number}: {line.strip()}"
        for path in _tool_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OWN_TREE_OR_COPY.search(line)
    ]

    assert not found, "\n".join(
        [*found, "Polecenie, które trwa, i kopię commitu narzędzie uruchamia przez potomne.run i potomne.commit_copy."]
    )


FAST_PROGRAMS = frozenset({"git", "gh", "ps"})
# Lokalne podpolecenia gita, które kończą się w ułamku sekundy i nie uruchamiają pomocników (sieć, hooki).
FAST_GIT = frozenset(
    {
        "blame",
        "branch",
        "cat-file",
        "commit-tree",
        "config",
        "diff",
        "for-each-ref",
        "log",
        "ls-files",
        "ls-tree",
        "merge-base",
        "merge-tree",
        "rev-list",
        "rev-parse",
        "show",
        "show-ref",
        "status",
        "worktree",
    }
)
LAUNCHES = frozenset(
    {
        *(f"subprocess.{name}" for name in ("run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput")),
        "os.system",
        "os.popen",
        *(f"os.{name}" for name in ("spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe")),
        "os.posix_spawn",
        "os.posix_spawnp",
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
    }
)
Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _Tool:
    path: Path
    module: str
    tree: ast.Module
    names: dict[str, str]
    parents: dict[ast.AST, ast.AST]

    @classmethod
    def read(cls, path: Path) -> _Tool:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Nazwa, pod którą narzędzia importują moduł: ``tools/lib`` i ``tools/ci`` są na ``sys.path`` jak ``tools``.
        root = next(root for root in (TOOLS / "lib", TOOLS / "ci", TOOLS) if path.is_relative_to(root))
        module = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        return cls(path, module, tree, imports(tree), parents)

    def calls(self) -> Iterator[tuple[ast.Call, str | None]]:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                yield node, dotted(node.func, self.names, self.module)

    def function_of(self, node: ast.AST) -> Function | None:
        parent = self.parents.get(node)
        while parent is not None and not isinstance(parent, Function):
            parent = self.parents.get(parent)
        return parent


def _command(call: ast.Call) -> ast.expr | None:
    return call.args[0] if call.args else next((keyword.value for keyword in call.keywords if keyword.arg == "args"), None)


def _program(command: ast.expr | None) -> str | None:
    if not isinstance(command, (ast.List, ast.Tuple)) or not command.elts:
        return None
    head = command.elts[0]
    if isinstance(head, ast.Constant) and isinstance(head.value, str):
        return head.value
    return head.id if isinstance(head, ast.Name) else None


def _literal(name: ast.expr, scope: ast.AST) -> list[ast.expr] | None:
    """Elementy krotki albo listy z jedynego przypisania tej nazwy w funkcji (albo module)."""

    if not isinstance(name, ast.Name):
        return None
    bound = [
        node.value
        for node in ast.walk(scope)
        if isinstance(node, ast.Assign) and [ast.unparse(target) for target in node.targets] == [name.id]
    ]
    return list(bound[0].elts) if len(bound) == 1 and isinstance(bound[0], (ast.Tuple, ast.List)) else None


def _git_subcommand(tool: _Tool, call: ast.Call, arguments: Sequence[ast.expr]) -> str | Function | None:
    """Podpolecenie po opcjach ``-C``/``-c``; funkcja, która przekazuje gitowi swoje ``*args``; ``None``, gdy nieznane."""

    function = tool.function_of(call)
    pending = list(arguments)
    while pending:
        argument = pending.pop(0)
        if isinstance(argument, ast.Starred):
            vararg = function.args.vararg if function is not None else None
            if vararg is not None and isinstance(argument.value, ast.Name) and argument.value.id == vararg.arg:
                return function
            unpacked = _literal(argument.value, function or tool.tree)
            if unpacked is None:
                return None
            pending[:0] = unpacked
        elif isinstance(argument, ast.Constant) and argument.value in ("-C", "-c"):
            pending = pending[1:]
        else:
            return argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else None
    return None


def _git_calls(tool: _Tool, wrappers: dict[str, int]) -> Iterator[tuple[ast.Call, str, Sequence[ast.expr]]]:
    """Wywołanie gita, jego opis w komunikacie i argumenty po ``git``: w poleceniu ``subprocess`` albo funkcji gita."""

    for call, called in tool.calls():
        if called in wrappers:
            yield call, f"{ast.unparse(call.func)}()", call.args[wrappers[called] :]
        elif called in LAUNCHES and _program(command := _command(call)) == "git":
            assert isinstance(command, (ast.List, ast.Tuple))
            yield call, ast.unparse(call.func), command.elts[1:]


def _git_wrappers(tools: Sequence[_Tool]) -> dict[str, int]:
    """Funkcje z ``tools/``, które przekazują gitowi swoje ``*args`` (także przez inną taką funkcję), i pozycja pierwszego."""

    wrappers: dict[str, int] = {}
    while True:
        found = {
            f"{tool.module}.{function.name}": len(function.args.posonlyargs) + len(function.args.args)
            for tool in tools
            for call, _, arguments in _git_calls(tool, wrappers)
            if isinstance(function := _git_subcommand(tool, call, arguments), Function)
        }
        if found.keys() <= wrappers.keys():
            return wrappers
        wrappers |= found


def _slow_launches(tool: _Tool, wrappers: dict[str, int]) -> Iterator[tuple[int, str, str]]:
    """Wiersz, wywołanie i polecenie każdego uruchomienia spoza ``gh``, ``ps`` i gita z ``FAST_GIT``."""

    for call, called in tool.calls():
        if called in LAUNCHES and _program(command := _command(call)) not in FAST_PROGRAMS:
            shown = ast.unparse(command.elts[0]) if isinstance(command, (ast.List, ast.Tuple)) else ast.unparse(command or call)
            yield call.lineno, ast.unparse(call.func), shown
    for call, launcher, arguments in _git_calls(tool, wrappers):
        subcommand = _git_subcommand(tool, call, arguments)
        if not isinstance(subcommand, Function) and subcommand not in FAST_GIT:
            yield call.lineno, launcher, f"git {subcommand or '?'}"


GIT_OWNERS = frozenset({TOOLS / "lib" / "repo.py", TOOLS / "lib" / "potomne.py"})


def _git_outside_repo(path: Path) -> Iterator[tuple[int, str]]:
    """Wiersz i początek każdej listy albo krotki, która zaczyna się od stałej ``"git"``."""

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "git":
            yield node.lineno, ast.unparse(node)[:80]


def test_narzedzia_pytaja_gita_przez_repo_a_polecenia_ktore_trwaja_uruchamiaja_przez_potomne_run() -> None:
    """Lista albo krotka zaczynająca się od stałej ``"git"`` stoi w ``tools/`` tylko w ``tools/lib/repo.py``
    i ``tools/lib/potomne.py``, więc narzędzie pyta gita przez ``repo`` z jego kodowaniem, limitem czasu i bazą,
    a zwykłe ``subprocess`` w ``tools/`` uruchamia tylko ``gh``, ``ps`` i szybkie podpolecenia gita z ``FAST_GIT``.

    Import pod inną nazwą (``import subprocess as sp``) to ten sam ``subprocess``. Git liczy się też przez funkcję
    z dowolnego modułu ``tools/``, która przekazuje mu swoje ``*args``, a krotkę rozpakowaną w wywołaniu (``*own``)
    test czyta z jej jedynego przypisania. Znane granice:

    - każdy inny program, także krótki ``python -c``, idzie przez ``potomne.run``, bo bez uruchomienia nie widać,
      czy trwa;
    - funkcji gita wołanej pod inną nazwą (``partial``, przypisanie, metoda) test nie widzi, bo to wymaga analizy
      przepływu danych;
    - nazwy programu ``git`` zbudowanej w czasie biegu (``"g" + "it"``, zmienna) test nie widzi.
    """

    tools = [_Tool.read(path) for path in _tool_sources()]
    wrappers = _git_wrappers(tools)
    found = [
        f"{tool.path.relative_to(TOOLS.parent).as_posix()}:{number}: {launcher} uruchamia {command} poza potomne.run"
        for tool in tools
        for number, launcher, command in sorted(_slow_launches(tool, wrappers))
    ]
    found += [
        f"{path.relative_to(TOOLS.parent).as_posix()}:{number}: {command} poza tools/lib/repo.py"
        for path in sorted({*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push"} - GIT_OWNERS)
        for number, command in _git_outside_repo(path)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Polecenie, które trwa albo uruchamia własne procesy, uruchom przez potomne.run z tools/lib/potomne.py; "
            "zwykłe subprocess zostaje tylko dla git, gh i ps, a nowe szybkie, lokalne podpolecenie gita dopisz do FAST_GIT.",
            "Gita pytaj przez tools/lib/repo.py: repo.git i repo.succeeds dla szybkich zapytań, repo.run_git dla poleceń,"
            " które trwają albo sięgają sieci, a repo.command dla polecenia kroku, który uruchamia ktoś inny.",
        ]
    )

