"""Tożsamość commitów agentów Claude Code z ``env`` w ``.claude/settings.json``, a nie z ``user.*`` configu.

13.11.2026 recenzent PR #1646 wykonał ``git config user.name``/``user.email`` w ``.git/config``, który dzielą checkout
główny i wszystkie worktree, więc przez 3 dni commity agentów miały cudzego autora. Hook przywracający config po
poleceniu (#1966) nie zamknął okna przerwanego polecenia. Konstrukcja: Claude Code daje ``env`` z ustawień projektu
każdemu poleceniu Basha agenta, a ``GIT_AUTHOR_*``/``GIT_COMMITTER_*`` bije ``user.*`` z każdego configu, więc zmiana
configu nie dotyczy commitów agenta. Strażnik żąda tych zmiennych z wartościami konta agenta w ustawieniach projektu.

Granica (próbki ``ZNANE_LUKI``): strażnik czyta tylko ``.claude/settings.json`` i nie widzi poleceń, więc przepuszcza
ustawienia silniejsze od projektu z inną tożsamością, ``git commit --author`` i polecenie, które zdejmuje zmienne, oraz
każdy proces spoza Claude Code (terminal Maksa, agent innego harnessu), który bierze autora z ``user.*`` configu.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
from typing import Final

from tests.fixtures.znane_luki import assert_znane_luki

ROOT = Path(__file__).resolve().parents[1]
NAME = "MAXIMISEART-AI"
EMAIL = "281159351+MAXIMISEART-AI@users.noreply.github.com"
IDENTITY: Final = {
    "GIT_AUTHOR_NAME": NAME,
    "GIT_AUTHOR_EMAIL": EMAIL,
    "GIT_COMMITTER_NAME": NAME,
    "GIT_COMMITTER_EMAIL": EMAIL,
}
FORMAT = "%an <%ae> | %cn <%ce>"


def _settings_env(project: Path, name: str = "settings.json") -> dict[str, str]:
    path = project / ".claude" / name
    return (
        dict(json.loads(path.read_text(encoding="utf-8")).get("env", {}))
        if path.exists()
        else {}
    )


def _problems(project: Path) -> list[str]:
    env = _settings_env(project)
    return [
        f"{name}={env.get(name)!r}, a ma być {value!r}"
        for name, value in IDENTITY.items()
        if env.get(name) != value
    ]


def _git(cwd: Path, *arguments: str, env: Mapping[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout.strip()


def _shared_config_with_foreign_identity(tmp_path: Path) -> Path:
    """Worktree repozytorium, którego wspólny ``.git/config`` ma ``user.name r`` jak 13.11."""

    main, worktree = tmp_path / "glowne", tmp_path / "worktree"
    tmp_path.mkdir(exist_ok=True)
    _git(tmp_path, "init", "--quiet", str(main))
    _git(main, "commit", "--quiet", "--allow-empty", "--message", "start")
    _git(main, "worktree", "add", "--quiet", str(worktree))
    _git(worktree, "config", "user.name", "r")
    _git(worktree, "config", "user.email", "r@x")
    assert _git(main, "config", "--local", "user.name") == "r"
    return worktree


def test_ustawienia_projektu_daja_agentom_tozsamosc_konta() -> None:
    assert _problems(ROOT) == [], (
        "env w .claude/settings.json nie daje agentom tożsamości konta: "
        + "; ".join(_problems(ROOT))
        + ". Claude Code daje te zmienne każdemu poleceniu Basha agenta, a GIT_AUTHOR_*/GIT_COMMITTER_* bije user.* z "
        "każdego configu, więc agent, który zmieni wspólny .git/config, nie zmienia autora commitów agentów (13.11, "
        f"recenzent PR #1646). Przywróć w env: {json.dumps(IDENTITY)}; tożsamości nie bierz z user.* configu."
    )


def test_commit_z_env_ustawien_ma_tozsamosc_konta_mimo_obcej_we_wspolnym_configu(
    tmp_path: Path,
) -> None:
    worktree = _shared_config_with_foreign_identity(tmp_path)
    agent = os.environ | _settings_env(ROOT)

    _git(
        worktree, "commit", "--quiet", "--allow-empty", "--message", "agent", env=agent
    )

    assert (
        _git(worktree, "log", "-1", f"--format={FORMAT}")
        == f"{NAME} <{EMAIL}> | {NAME} <{EMAIL}>"
    )


@dataclass(frozen=True)
class Gap:
    """Commit, którego autor nie jest kontem agenta, choć ustawienia projektu mają ``IDENTITY``."""

    command: tuple[str, ...] = (
        "git",
        "commit",
        "--quiet",
        "--allow-empty",
        "--message",
        "luka",
    )
    local: Mapping[str, str] = field(default_factory=dict)
    dropped: tuple[str, ...] = ()
    claude_code: bool = True


ZNANE_LUKI: Final[dict[str, Gap]] = {
    "czyta tylko ustawienia projektu: .claude/settings.local.json z inną tożsamością": Gap(
        local={"GIT_AUTHOR_NAME": "r", "GIT_COMMITTER_NAME": "r"}
    ),
    "nie widzi polecenia: git commit --author": Gap(
        command=(
            "git",
            "commit",
            "--quiet",
            "--allow-empty",
            "--author",
            "r <r@x>",
            "--message",
            "luka",
        )
    ),
    "nie widzi polecenia: env -u albo unset zdejmuje zmienne przed git commit": Gap(
        dropped=("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL")
    ),
    "działa tylko w Claude Code: terminal Maksa albo agent innego harnessu bierze user.* configu": Gap(
        claude_code=False
    ),
}


def _gap_author(project: Path, worktree: Path, gap: Gap) -> str:
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps({"env": dict(gap.local)}), encoding="utf-8"
    )
    harness = (
        _settings_env(project) | _settings_env(project, "settings.local.json")
        if gap.claude_code
        else {}
    )
    env = {
        name: value
        for name, value in (os.environ | harness).items()
        if name not in gap.dropped
    }
    subprocess.run(gap.command, cwd=worktree, env=env, capture_output=True, check=True)
    return _git(worktree, "log", "-1", "--format=%an")


def test_znane_luki_maja_obcego_autora_a_straznik_ich_nie_zglasza(
    tmp_path: Path,
) -> None:
    findings: dict[str, list[str]] = {}
    authors: dict[str, str] = {}
    for number, (description, gap) in enumerate(ZNANE_LUKI.items()):
        project = tmp_path / f"projekt{number}"
        authors[description] = _gap_author(
            project, _shared_config_with_foreign_identity(tmp_path / str(number)), gap
        )
        findings[description] = _problems(project)

    assert authors == dict.fromkeys(ZNANE_LUKI, "r"), (
        "próbka ZNANE_LUKI daje autora konta, więc nie jest luką"
    )
    assert_znane_luki(findings, "tests/test_tozsamosc_agentow.py")
