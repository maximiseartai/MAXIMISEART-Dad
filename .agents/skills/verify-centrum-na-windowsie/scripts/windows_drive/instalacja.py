"""Instalacja: the tool as Maks installs it on Dad's computer, from the clone to the shortcut on the desktop."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from windows_drive.common import Run, same_path
import windows_desktop
from windows_tool import REPO_ROOT
from rozliczenia.tool_files import REPOSITORY_URL

FEATURE = "instalacja"


def _python(run: Run, *args: str) -> subprocess.CompletedProcess[str]:
    """Dad's ``py -3 …`` in the tool's folder; output captured as UTF-8, which a console shows as such."""

    return subprocess.run(
        [sys.executable, *args],
        cwd=run.tool,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ | {"PYTHONIOENCODING": "utf-8"},
        check=False,
        timeout=600,
    )


_PIP_LINE = "py -3 -m pip install -r requirements.txt"


def _readme_clone() -> str:
    """README's PowerShell for ``Instalacja lokalna`` up to ``git reset --hard $wydanie``; its last line must be pip."""

    section = (REPO_ROOT / "README.md").read_text(encoding="utf-8").split("## Instalacja lokalna", 1)[1]
    lines = section.split("```powershell\n", 1)[1].split("```", 1)[0].splitlines()
    if lines[-1:] != [_PIP_LINE] or not lines[-2].startswith("git reset --hard "):
        raise AssertionError(f"README's installation no longer ends with git reset and {_PIP_LINE!r}: {lines}")
    return "\n".join(lines[:-1]) + "\n"


def _encodable(text: str, code_page: int) -> bool:
    try:
        text.encode(f"cp{code_page}")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def drive(run: Run) -> None:
    facts = run.facts
    versions = facts["versions"]

    run.step(FEATURE, "klon")
    # Maks types README's lines in Windows PowerShell; the boundaries rewrite GitHub's address to the run's origin.
    script = run.root / "instalacja.ps1"
    script.write_text(_readme_clone(), encoding="utf-8-sig")
    run.tool.parent.mkdir(parents=True)
    clone = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=run.tool.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )
    said = [line.strip() for line in (clone.stdout + clone.stderr).splitlines() if line.strip()]
    print(f"  README: {' | '.join(said)}", flush=True)
    run.check(clone.returncode == 0 and (run.tool / ".git").is_dir(), "README's clone and choice of the Wydanie run in PowerShell")
    run.check(run.git("rev-parse", "HEAD") == versions["first"], "the tool stands on the newest Wydanie (the first version), not on main")
    run.check(run.git("branch", "--show-current") == "main", "the clone is on main")
    run.check(run.git("config", "--get", "remote.origin.url") == REPOSITORY_URL, "origin is the tool's GitHub address")
    run.check(" " in str(run.tool) and not str(run.tool).isascii(), f"the tool's folder has a space and a Polish letter: {run.tool}")

    run.step(FEATURE, "pliki-taty")
    for name in facts["dad_config"]:
        shutil.copy2(name, run.config / Path(name).name)
    status = run.git("status", "--porcelain", "--untracked-files=all")
    run.check(status == "", "Dad's konfiguracja wykonawców and Wzorce in config/ leave the clone clean for Git")

    run.step(FEATURE, "biblioteki")
    run.harness(f"README's {_PIP_LINE!r} runs with this Python, not with the py launcher")
    pip = _python(run, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt")
    (run.evidence / "state" / "pip-instalacja.txt").write_text(pip.stdout + pip.stderr, encoding="utf-8")
    run.check(pip.returncode == 0, "py -3 -m pip install -r requirements.txt succeeds in the tool's folder")

    run.step(FEATURE, "skrot")
    desktop, startup = Path(facts["desktop"]), Path(facts["startup"])
    desktop.mkdir()
    startup.mkdir()
    created = _python(run, "install_centrum_shortcut.py", "--folder", str(desktop), "--folder-autostartu", str(startup))
    print(f"  install_centrum_shortcut.py: {created.stdout.strip()} {created.stderr.strip()}".rstrip(), flush=True)
    link = Path(facts["shortcut"])
    code_page = windows_desktop.ansi_code_page()
    links = sorted(desktop.glob("*.lnk"))
    print(f"  code page {code_page}; shortcuts: {[ascii(found.name) for found in links]}", flush=True)
    run.check(created.returncode == 0 and len(links) == 1, "the step exits 0 and makes one shortcut on the desktop folder")
    if not _encodable(link.name, code_page):
        # WScript.Shell writes the name through the ANSI code page: Dad's 1250 has „ń”, the runner's may not.
        run.harness(f"code page {code_page} cannot write {link.name!r} (Dad's 1250 can): the shortcut is {links[0].name!r}")
        link = links[0]
        facts["shortcut"] = str(link)
    run.check(links[0] == link, f"the shortcut is {link.name}")
    run.check(f"Utworzono skrót „Centrum rozliczeń”: {facts['desktop']}" in created.stdout, "the step says where the shortcut is")
    shortcut = windows_desktop.read_shortcut(link)
    (run.evidence / "state" / "skrot.json").write_text(json.dumps(shortcut, ensure_ascii=False, indent=2), encoding="utf-8")
    windowless = Path(sys.executable).with_name("pythonw.exe")
    run.check(same_path(shortcut["TargetPath"], windowless), f"the shortcut starts {windowless}")
    run.check(shortcut["Arguments"] == f'"{run.run_centrum}"', "its argument is the tool's run_centrum.py, quoted")
    run.check(same_path(shortcut["WorkingDirectory"], run.tool), "it works in the tool's folder")
    icon = run.tool / "src" / "rozliczenia" / "centrum" / "centrum-rozliczen.ico"
    run.check(shortcut["IconLocation"].casefold() == f"{icon},0".casefold() and icon.is_file(), "its icon is Centrum's")

    run.step(FEATURE, "autostart")
    started_by_login = sorted(startup.glob("*.lnk"))
    print(f"  Autostart shortcuts: {[ascii(found.name) for found in started_by_login]}", flush=True)
    run.check([found.name for found in started_by_login] == [link.name], "the same step makes one shortcut in the Autostart folder")
    run.check(
        f"Utworzono skrót „Centrum rozliczeń” w Autostarcie (start po zalogowaniu, bez karty): {facts['startup']}"
        in created.stdout,
        "the step says where the Autostart shortcut is",
    )
    from_startup = windows_desktop.read_shortcut(started_by_login[0])
    (run.evidence / "state" / "skrot-autostart.json").write_text(
        json.dumps(from_startup, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run.check(
        from_startup == shortcut | {"Arguments": f'"{run.run_centrum}" "--no-browser"'},
        "the Autostart shortcut is the desktop one with --no-browser, so Centrum starts at login without a tab",
    )
