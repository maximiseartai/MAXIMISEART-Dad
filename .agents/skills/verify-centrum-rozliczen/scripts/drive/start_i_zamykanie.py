"""Drive features/start-i-zamykanie.md."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import urllib.parse

from playwright.sync_api import Page, Request, Response, expect

from drive.common import REPO_ROOT, Run, answers, log_entries, read_text, served_version
from drive.waiting import Budget, until
from atrapy.pliki_taty import LOG_FILE, SERVICE

# Every click on the shortcut opens one more tab; the browser keeps at most 6 connections to Centrum for all tabs.
_SHORTCUT_TABS = 7
# Headless Chromium reports every tab as visible. A real browser hides the tab left behind when a new one comes
# to the front (and every tab of a minimised window); the drive does that for it.
_TO_BACKGROUND = """() => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" })
  Object.defineProperty(document, "hidden", { configurable: true, get: () => true })
  document.dispatchEvent(new Event("visibilitychange"))
}"""
_TO_FRONT = """() => {
  delete document.visibilityState
  delete document.hidden
  document.dispatchEvent(new Event("visibilitychange"))
}"""


def _copy_tool(run: Run) -> Path:
    """A copy of the tool inside the run root, so the real launcher logs there and never in Dad's ``logs``.

    Its ``.git/HEAD`` names the served Centrum's commit: the copy is the same version of the tool.
    """

    tool = run.root / "narzedzie"
    if not tool.exists():
        tool.mkdir()
        shutil.copy2(REPO_ROOT / "run_centrum.py", tool)
        shutil.copytree(REPO_ROOT / "src", tool / "src", ignore=shutil.ignore_patterns("__pycache__"))
        (tool / ".git").mkdir()
        (tool / ".git" / "HEAD").write_text(served_version(run)[0] + "\n", encoding="utf-8")
    return tool


def _browser_recorder(run: Run) -> tuple[Path, Path]:
    """Stands in for the browser (``BROWSER``) and appends each opened address to ``browser.txt``."""

    record = run.root / "browser.txt"
    if sys.platform == "win32":
        recorder = run.root / "browser.cmd"
        recorder.write_text(f'@echo %~1>>"{record}"\r\n', encoding="utf-8")
    else:
        recorder = run.root / "browser.sh"
        recorder.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{record}"\n', encoding="utf-8")
        recorder.chmod(0o755)
    return recorder, record


def _launch(run: Run, port: int, name: str) -> subprocess.CompletedProcess[str]:
    """The real launcher (``run_centrum.py``, the console path) from the run's copy of the tool."""

    tool = _copy_tool(run)
    recorder, _ = _browser_recorder(run)
    environment = os.environ | {"PYTHONUTF8": "1", "BROWSER": str(recorder)}
    result = subprocess.run(
        [sys.executable, str(tool / "run_centrum.py"), "--port", str(port)],
        cwd=tool, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=Budget.BACKGROUND.value,
        check=False,
    )
    (run.evidence / "api" / f"{name}.txt").write_text(
        f"exit_code={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}", encoding="utf-8"
    )
    return result


def _log_events(path: Path) -> list[str]:
    return [entry.event for entry in log_entries(path)]


def _is_stream(message: Request | Response) -> bool:
    return urllib.parse.urlsplit(message.url).path == "/api/runs/events"


def _expect_runs_shown(tab: Page) -> None:
    """Uruchomienia leaves its skeleton only once the tab has the run setup (API) and the current Uruchomienie (stream)."""

    expect(tab.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    expect(tab.get_by_label("Wczytywanie Uruchomień", exact=True)).to_have_count(0)


def drive(run: Run, page: Page) -> None:
    feature = "start-i-zamykanie"
    port = int(urllib.parse.urlsplit(run.url).port or 0)
    served_log = run.log_path
    # The log the start script writes in its default place, which Dad hands Maks (docs/tata-instrukcja.md).
    tool_log = run.root / "narzedzie" / LOG_FILE

    run.step(feature, "start-gotowosc")
    health = run.api("/api/health", "start-health")
    commit, _ = served_version(run)
    run.check(
        health.keys() == {"service", "commit", "instance"}
        and (health["service"], health["commit"]) == (SERVICE, commit[:7])
        and bool(health["instance"]),
        "health names Centrum rozliczeń, the tool's commit it runs, and this start",
    )
    run.check(_log_events(served_log)[:1] == ["start"], "the Centrum log starts with a start entry")
    run.check(f"port={port}" in read_text(served_log), "the start entry names the port")

    run.step(feature, "start-druga-instancja")
    again = _launch(run, port, "start-druga-instancja")
    run.check(again.returncode == 0, "a second launch on the same port exits 0")
    run.check(f"Centrum rozliczeń już działa: {run.url}" in again.stdout, "it says Centrum is already running")
    run.check(read_text(run.root / "browser.txt").split() == [run.url], "it only opens the tab")
    run.check(_log_events(tool_log) == ["juz-dziala"], "its log records the recognised running Centrum")
    run.check(answers(run.url), "the first Centrum keeps serving")

    run.step(feature, "start-obcy-program")
    with socket.socket() as foreign_program:
        foreign_program.bind(("127.0.0.1", 0))
        foreign_program.listen()
        foreign_port = foreign_program.getsockname()[1]
        refused = _launch(run, foreign_port, "start-obcy-program")
    run.check(refused.returncode == 1, "a launch on a port held by another program exits 1")
    run.check(
        [line.split(":", 1)[0] for line in refused.stdout.splitlines()] == ["Co się stało", "Gdzie", "Co zrobić"],
        "the console shows the three-part start message",
    )
    run.check("zajmuje inny program" in refused.stdout and refused.stderr == "", "no exception text, only the message")
    run.check(_log_events(tool_log)[-1:] == ["blad-startu"], "the log records the start failure")

    run.step(feature, "karty-w-tle")
    page.goto(run.url + "#/uruchomienia")
    _expect_runs_shown(page)
    with page.expect_event("requestfailed", predicate=_is_stream):
        page.evaluate(_TO_BACKGROUND)
    run.check(True, "in the background the drive's tab gives its stream back (tabs hidden by the harness)")
    shortcut_tabs: list[Page] = []
    for _ in range(_SHORTCUT_TABS):
        if shortcut_tabs:
            shortcut_tabs[-1].evaluate(_TO_BACKGROUND)
        shortcut_tabs.append(tab := page.context.new_page())
        tab.goto(run.url + "#/uruchomienia")
        _expect_runs_shown(tab)
    run.check(True, f"each of {_SHORTCUT_TABS} more tabs shows Uruchomienia from the API and the stream")
    run.capture(shortcut_tabs[-1], "90-start-i-zamykanie-karty-w-tle")
    shortcut_tabs[-1].evaluate(_TO_BACKGROUND)
    with page.expect_response(_is_stream) as reconnected:
        page.evaluate(_TO_FRONT)
    run.check(reconnected.value.status == 200, "back in front, the drive's tab connects to the stream again")
    for tab in shortcut_tabs:
        tab.close()

    run.step(feature, "zamykanie-karta")
    page.goto(run.url)
    other_tab = page.context.new_page()
    other_tab.goto(run.url)
    expect(other_tab.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    other_tab.close()
    run.check(answers(run.url), "closing a tab leaves Centrum running")

    run.step(feature, "zamykanie-potwierdzenie")
    # In `all`, Centrum already closed once for aktualizacja (`zamkniecie z=aktualizacja`) and was restarted.
    closings = _log_events(served_log).count("zamkniecie")
    close_button = page.get_by_role("button", name="Zamknij Centrum rozliczeń", exact=True)
    close_button.click()
    dialog = page.get_by_role("alertdialog", name="Zamknąć Centrum rozliczeń?")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Wrócisz skrótem „Centrum rozliczeń” na pulpicie.")
    run.capture(page, "91-start-i-zamykanie-potwierdzenie", full_page=False)
    dialog.get_by_role("button", name="Anuluj", exact=True).click()
    expect(dialog).to_be_hidden()
    run.check(
        answers(run.url) and _log_events(served_log).count("zamkniecie") == closings, "Anuluj leaves Centrum running"
    )

    run.step(feature, "zamykanie")
    close_button.click()
    page.get_by_role("button", name="Zamknij Centrum", exact=True).click()
    expect(page.get_by_role("heading", name="Centrum rozliczeń jest zamknięte", exact=True)).to_be_visible()
    until(lambda: not answers(run.url), "the Centrum process stops serving")
    until(lambda: _log_events(served_log)[-2:] == ["zamkniecie", "stop"], "the log ends with zamkniecie, stop")
    run.capture(page, "92-start-i-zamykanie-zamkniete")
