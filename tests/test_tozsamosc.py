"""Hook ``tools/hooks/tozsamosc.py``: tożsamość autora gita zmieniona przez polecenie agenta wraca do poprzedniej.

13.11.2026 recenzent PR #1646 ustawił w swoim worktree ``git config user.email r@x && git config user.name r``, żeby
zrobić próbny commit, a ``git config`` bez ``--file`` pisze do ``.git/config`` głównego checkoutu, który dzielą
wszystkie worktree: przez trzy dni każdy agent na Macu Maksa podpisywał nim commity. Testy odtwarzają to na repo
tymczasowym z worktree, z ``HOME``, configiem globalnym i systemowym w katalogu tymczasowym: hook biegnie jak w Claude
Code (``PreToolUse``, polecenie w ``bash``, potem ``PostToolUse`` albo ``PostToolUseFailure`` z tym samym
``tool_use_id``), a test sprawdza kod, stderr i tożsamość w configach po poleceniu.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from types import ModuleType

import pytest

from tests.fixtures.git_config import computer_git_config
from tests.fixtures.znane_luki import assert_znane_luki

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "tozsamosc.py"
SETTINGS = ROOT / ".claude" / "settings.json"
IDENTITY = r"^(user|author|committer)\.(name|email)$"
_calls = itertools.count()


def _git_version() -> tuple[int, ...]:
    words = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout.split()
    return tuple(int(part) for part in words[2].split(".")[:2])


# Podpolecenia ``git config set`` i ``rename-section`` ma git od 2.46; starszy (runner Ubuntu) ich nie zna i nic nie zapisuje.
git_2_46 = pytest.mark.skipif(sys.platform == "win32" or _git_version() < (2, 46), reason="podpolecenie git config od gita 2.46")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="polecenia agenta biegną w bash, jak Claude Code na macOS i Linuksie")

# Każda postać zapisu z werdyktu r1 (sonda recenzenta) i z incydentu; ``{glowne}`` to główny checkout repo.
WRITES = (
    "git config user.email r@x && git config user.name r",
    "cd {glowne} && git config --file .git/config user.name r",
    "git config --file $(git rev-parse --git-common-dir)/config user.name r",
    "git -C {glowne} config user.name r",
    "git -C $(git rev-parse --show-toplevel) config user.name r",
    "git --git-dir=$(git rev-parse --git-common-dir) config user.name r",
    "GIT_DIR={glowne}/.git git config user.name r",
    pytest.param("git config set user.name r", marks=git_2_46),
    "env git config user.name r",
    "command git config user.name r",
    "exec git config user.name r",
    "(git config user.name r)",
    "{{ git config user.name r; }}",
    "echo r | xargs git config user.name",
    "git config --global \\\n  user.name r",
    "git config \\\n  user.email r@x",
    "echo $((1<<2))\ngit config committer.name c",
    "bash <<'EOF'\ngit config user.name r\nEOF",
    "printf 'git config user.name r\\n' > ustaw.sh && sh ustaw.sh",
    "python3 -c \"import subprocess; subprocess.run(['git', 'config', 'user.name', 'r'])\"",
    'k=user.name; git config "$k" r',
    "g=git; $g config user.name r",
    "git -c alias.ustaw=config ustaw user.name r",
    "git config --unset user.email",
    "git config --remove-section user",
    pytest.param("git config rename-section user stary", marks=git_2_46),
    "git config --rename-section user stary",
    "git config User.Name r",
    "git config --add user.name drugi",
    "git config author.email a@x",
    "git config --system user.name r",
    "git config user.name r; false",
)

# Postacie bez zmiany tożsamości z werdyktu r1 i z jednorazowym podpisem: hook milczy.
QUIET = (
    "git config --get user.name",
    "git config user.name",
    "git -c user.name=x -c user.email=x@y commit -q --allow-empty -m x",
    "GIT_AUTHOR_NAME=r GIT_AUTHOR_EMAIL=r@x GIT_COMMITTER_NAME=r GIT_COMMITTER_EMAIL=r@x git commit -q --allow-empty -m p",
    "git log --author=r --format='%an'",
    'git commit -q --allow-empty -m "fix: odmowa dla git config user.name r"',
    "git commit -q --allow-empty -F - <<'EOF'\nnie rób git config user.name r\nEOF",
    "gh pr create --title t --body \"$(cat <<'EOF'\n## Why\ngit config user.email r@x && git config user.name r\nEOF\n)\"",
    "gh pr create --title t --body 'git config user.name r'",
    'gh pr comment 1 --body "Uruchom \\`git config user.name r\\`"',
    "git config --default r user.name",
    "git config --global --show-origin user.email",
    "git config user.signingkey ABC",
    "rg -n \"git config user.name\" .",
    "git config --get user.name || echo brak",
    "git config core.x y && git branch -q nowa && git config branch.nowa.description opis",
    "git config --file proba.ini user.name r",
)

# Postacie zmiany tożsamości, które hook przepuszcza, nazwane klasą mechanizmu, który je przepuszcza.
ZNANE_LUKI = {
    "porównuje configi tylko do zwrotu polecenia: zapis w poleceniu w tle": "git config user.name r",
    "pilnuje tylko repo katalogu polecenia i projektu: config innego repo": "git -C {inne} config user.name r",
    "czyta klucze tożsamości bez include: include.path do pliku z tożsamością": (
        "printf '[user]\\n\\tname = r\\n' > {inne}/tozsamosc.inc && git config include.path {inne}/tozsamosc.inc"
    ),
    "pilnuje tylko configów tego komputera: polecenie przez ssh": "ssh og-box 'git config --global user.name r'",
}
BACKGROUND = "porównuje configi tylko do zwrotu polecenia: zapis w poleceniu w tle"


@dataclass(frozen=True)
class Repo:
    glowne: Path
    worktree: Path
    inne: Path
    home: Path
    env: dict[str, str]

    def configs(self) -> list[Path]:
        return [self.glowne / ".git" / "config", Path(self.env["GIT_CONFIG_GLOBAL"]), Path(self.env["GIT_CONFIG_SYSTEM"])]

    def identity(self) -> dict[str, dict[str, list[str]]]:
        """Wartości kluczy tożsamości każdego pilnowanego configu w kolejności wpisów każdego klucza."""

        found: dict[str, dict[str, list[str]]] = {}
        for path in self.configs():
            listed = self.git("config", "--file", str(path), "--get-regexp", IDENTITY).stdout
            for key, _, value in (line.partition(" ") for line in listed.splitlines()):
                found.setdefault(str(path), {}).setdefault(key, []).append(value)
        return found

    def git(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments], cwd=cwd or self.worktree, env=self.env, capture_output=True, text=True, check=False
        )


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Repo]:
    home, bin_dir = tmp_path / "dom", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    # Polecenia ``gh`` i ``ssh`` z próbek nie mogą sięgnąć GitHuba ani innego komputera.
    for program in ("gh", "ssh"):
        (bin_dir / program).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (bin_dir / program).chmod(0o755)
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("GIT_", "XDG_"))}
    env = environment | {
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(computer_git_config(home / ".gitconfig", "")),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "system-gitconfig"),
        "TOZSAMOSC_STAN": str(tmp_path / "stan"),
    }
    glowne, worktree, inne = tmp_path / "glowne", tmp_path / "w", tmp_path / "inne"
    made = Repo(glowne, worktree, inne, home, env)
    for directory in (glowne, inne):
        made.git("init", "-q", str(directory), cwd=tmp_path)
    made.git("config", "user.name", "Maks", cwd=glowne)
    made.git("config", "user.email", "maks@example.invalid", cwd=glowne)
    made.git("commit", "-q", "--allow-empty", "-m", "start", cwd=glowne)
    made.git("worktree", "add", "-q", str(worktree), cwd=glowne)
    made.env["CLAUDE_PROJECT_DIR"] = str(worktree)
    yield made


def _hook(event: str, call: str, repo: Repo, command: str) -> subprocess.CompletedProcess[str]:
    data = {
        "hook_event_name": event,
        "session_id": "sesja",
        "tool_use_id": call,
        "cwd": str(repo.worktree),
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "x"},
    }
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(data), env=repo.env, capture_output=True, text=True, check=False
    )


def _agent(repo: Repo, command: str, *, background: bool = False) -> subprocess.CompletedProcess[str]:
    """Polecenie Basha agenta między hookami, jak w Claude Code; wynik ``PostToolUse`` (albo ``PostToolUseFailure``)."""

    call = f"toolu_{next(_calls)}"
    before = _hook("PreToolUse", call, repo, command)
    assert (before.returncode, before.stdout, before.stderr) == (0, "", "")
    ran = None if background else subprocess.run(["bash", "-c", command], cwd=repo.worktree, env=repo.env, capture_output=True, check=False)
    event = "PostToolUse" if ran is None or ran.returncode == 0 else "PostToolUseFailure"
    after = _hook(event, call, repo, command)
    if background:
        subprocess.run(["bash", "-c", command], cwd=repo.worktree, env=repo.env, capture_output=True, check=False)
    return after


@pytest.mark.parametrize("command", WRITES)
def test_zmieniona_tozsamosc_wraca_a_agent_dostaje_droge_jednorazowego_podpisu(repo: Repo, command: str) -> None:
    before = repo.identity()

    after = _agent(repo, command.format(glowne=repo.glowne))

    assert (after.returncode, after.stdout, "git -c user.name=… -c user.email=… commit" in after.stderr) == (2, "", True), after.stderr
    assert repo.identity() == before


@pytest.mark.parametrize("command", QUIET)
def test_polecenie_bez_zmiany_tozsamosci_przechodzi_bez_slowa(repo: Repo, command: str) -> None:
    before = repo.identity()

    after = _agent(repo, command)

    assert (after.returncode, after.stdout, after.stderr, repo.identity()) == (0, "", "", before)


def test_komunikat_podaje_zmiane_poprawke_commitu_i_cudza_zmiane(repo: Repo) -> None:
    after = _agent(repo, "git config user.email r@x && git config user.name r")

    said = [
        f"{repo.glowne / '.git' / 'config'}: user.name 'Maks' → 'r': przywrócone",
        "user.email 'maks@example.invalid' → 'r@x'",
        "GIT_COMMITTER_EMAIL",
        "--amend --reset-author",
        "Maks w swoim terminalu",
    ]
    assert [text for text in said if text not in after.stderr] == [], after.stderr


def test_inne_zmiany_configu_w_tym_samym_poleceniu_zostaja(repo: Repo) -> None:
    after = _agent(repo, "git config core.x y && git config user.name r && git config core.z w")

    assert after.returncode == 2, after.stderr
    assert [repo.git("config", key).stdout for key in ("core.x", "core.z", "user.name")] == ["y\n", "w\n", "Maks\n"]


@pytest.mark.parametrize("command", ["git config --replace-all user.name r", "git config --unset-all user.name"])
def test_wiele_wartosci_klucza_wraca_w_kolejnosci(repo: Repo, command: str) -> None:
    repo.git("config", "--add", "user.name", "Drugi")

    after = _agent(repo, command)

    assert (after.returncode, "przywrócone" in after.stderr) == (2, True), after.stderr
    assert repo.git("config", "--local", "--get-all", "user.name").stdout == "Maks\nDrugi\n"


def test_tozsamosc_dopisana_do_configu_bez_niej_znika(repo: Repo) -> None:
    after = _agent(repo, "git config --global author.name r")

    assert after.returncode == 2, after.stderr
    assert repo.git("config", "--global", "--get-all", "author.name").returncode == 1


def test_tozsamosc_w_config_worktree_glownego_checkoutu_i_worktree_wraca(repo: Repo) -> None:
    repo.git("config", "extensions.worktreeConfig", "true")
    before = {cwd: repo.git("config", "--worktree", "--get-regexp", IDENTITY, cwd=cwd).stdout for cwd in (repo.glowne, repo.worktree)}

    after = _agent(repo, f"git config --worktree user.name r && git -C {repo.glowne} config --worktree user.email r@x")

    assert after.returncode == 2, after.stderr
    assert {cwd: repo.git("config", "--worktree", "--get-regexp", IDENTITY, cwd=cwd).stdout for cwd in before} == before


def test_swieze_repo_w_katalogu_tymczasowym_ma_wlasna_tozsamosc(repo: Repo, tmp_path: Path) -> None:
    proba = tmp_path / "proba"

    after = _agent(repo, f"git init -q {proba} && cd {proba} && git config user.name r && git config user.email r@x")

    assert (after.returncode, after.stderr) == (0, "")
    assert repo.git("config", "user.name", cwd=proba).stdout == "r\n"


def test_bez_zmiany_configu_hook_nie_uruchamia_gita(repo: Repo, tmp_path: Path) -> None:
    # Hook biegnie przy każdym poleceniu Basha, więc git (jedyny drogi krok) tylko przy zmianie bajtów configu.
    spy, log = tmp_path / "szpieg", tmp_path / "git.log"
    spy.mkdir()
    real_git = subprocess.run(["bash", "-c", "command -v git"], env=repo.env, capture_output=True, text=True, check=True).stdout.strip()
    (spy / "git").write_text(f'#!/bin/sh\necho "$@" >> {log}\nexec {real_git} "$@"\n', encoding="utf-8")
    (spy / "git").chmod(0o755)
    repo.env["PATH"] = f"{spy}{os.pathsep}{repo.env['PATH']}"

    quiet, changed = _agent(repo, "echo hej"), _agent(repo, "git config user.name r")

    listed = [line for line in log.read_text(encoding="utf-8").splitlines() if "--no-includes --list" in line]
    # Jedno odczytanie tożsamości configu sprzed polecenia i jedno po nim, oba z polecenia, które go zmieniło.
    assert (quiet.returncode, changed.returncode, len(listed)) == (0, 2, 2), listed


def test_znane_luki_hooka_tozsamosci_przechodza_przez_hook(repo: Repo) -> None:
    zgloszenia = {}
    configs = {path: path.read_bytes() for path in repo.configs() if path.exists()}
    for opis, command in ZNANE_LUKI.items():
        before = repo.identity()
        after = _agent(repo, command.format(inne=repo.inne), background=opis == BACKGROUND)
        changed = [] if opis != BACKGROUND or repo.identity() != before else ["zapis w tle nie zmienił tożsamości"]
        zgloszenia[opis] = [line for line in [after.stderr.strip()] if line] + changed
        for path, content in configs.items():  # następna próbka zaczyna od tożsamości sprzed tej
            path.write_bytes(content)

    assert_znane_luki(zgloszenia, "tests/test_tozsamosc.py")


@pytest.mark.parametrize(
    "stdin",
    [
        pytest.param(json.dumps({"hook_event_name": "PostToolUse", "session_id": "s", "tool_use_id": "bez-pre"}), id="post-bez-pre"),
        pytest.param(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s"}), id="bez-tool-use-id"),
        pytest.param("nie json", id="nie-json"),
        pytest.param("[]", id="nie-obiekt"),
        pytest.param(json.dumps({"hook_event_name": "Stop"}), id="inne-zdarzenie"),
    ],
)
def test_hook_przepuszcza_bez_slowa(repo: Repo, stdin: str) -> None:
    hooked = subprocess.run([sys.executable, str(HOOK)], input=stdin, env=repo.env, capture_output=True, text=True, check=False)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def test_bez_git_config_global_hook_pilnuje_gitconfig_i_xdg_w_home(tmp_path: Path) -> None:
    hook = _load()
    environment = {"HOME": str(tmp_path), "PATH": "/nieistniejacy"}

    assert hook.watched([], environment) == [tmp_path / ".gitconfig", tmp_path / ".config" / "git" / "config", Path("/etc/gitconfig")]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tozsamosc", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registered(event: str) -> list[dict[str, object]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"].get(event, [])
    return [hook for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"] if "tozsamosc.py" in hook["command"]]


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse", "PostToolUseFailure"])
def test_claude_code_uruchamia_hook_przy_kazdym_bashu_z_limitem_najwyzej_10_s(event: str) -> None:
    (registered,) = _registered(event)
    timeout = registered["timeout"]

    assert isinstance(timeout, (int, float)) and 0 < timeout <= 10


def test_polecenie_z_ustawien_projektu_przywraca_tozsamosc(repo: Repo, tmp_path: Path) -> None:
    # Kopia skryptu w projekcie spoza repo: hook z CLAUDE_PROJECT_DIR=ROOT czytałby config prawdziwego checkoutu.
    project = tmp_path / "projekt"
    for script in (HOOK, ROOT / "tools" / "lib" / "repo.py"):
        (project / script.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(script, project / script.relative_to(ROOT))

    def configured(event: str, project: Path) -> subprocess.CompletedProcess[str]:
        (registered,) = _registered(event)
        data = {"hook_event_name": event, "session_id": "s", "tool_use_id": "t", "cwd": str(repo.worktree)}
        return subprocess.run(
            str(registered["command"]),
            shell=True,
            input=json.dumps(data),
            env=repo.env | {"CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            text=True,
            check=False,
        )

    configured("PreToolUse", project)
    repo.git("config", "user.name", "r")
    hooked = configured("PostToolUse", project)
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    without_script = configured("PostToolUse", repo.home)

    assert (hooked.returncode, repo.git("config", "user.name").stdout) == (2, "Maks\n"), hooked.stderr
    assert (without_script.returncode, without_script.stderr) == (0, "")
