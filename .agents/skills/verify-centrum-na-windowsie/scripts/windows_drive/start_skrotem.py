"""Start skrótem: Dad double-clicks „Centrum rozliczeń”, Centrum starts without a console and opens his tab."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

from playwright.sync_api import Page, expect

from windows_drive.common import Run, same_path, wait_for
import windows_desktop
from rozliczenia.centrum import start_problems
from atrapy.pliki_taty import SERVICE

FEATURE = "start-skrotem"


def check_windowless(run: Run, process: windows_desktop.Process, *, by_guardian: bool = False) -> None:
    """Centrum on Dad's port is this tool's ``pythonw.exe`` with no window of its own (no console)."""

    windowless = Path(sys.executable).with_name("pythonw.exe")
    run.check(same_path(process.executable, windowless), f"Centrum runs in {windowless}")
    run.check(str(run.run_centrum).casefold() in process.command_line.casefold(), "Centrum runs the tool's run_centrum.py")
    if by_guardian:
        run.check("--bez-okienek" in process.command_line, "the restart guardian started it without dialogs")
    windows = windows_desktop.visible_windows([process.pid])
    run.check(windows == [], f"Centrum's process shows no window (no console): {windows}")
    consoles = [child for child in windows_desktop.processes() if child.parent == process.pid and child.name.lower() == "conhost.exe"]
    run.check(consoles == [], "Centrum's process has no console host")


def start_dialogs() -> list[windows_desktop.Window]:
    return [
        window
        for window in windows_desktop.visible_windows()
        if window.cls == windows_desktop.DIALOG and window.title == start_problems.TITLE
    ]


def drive(run: Run, page: Page) -> None:
    facts = run.facts
    port, url = facts["port"], run.url

    run.step(FEATURE, "start")
    run.check(windows_desktop.port_owner(port) is None, f"nothing listens on port {port} before the double click")
    windows_desktop.start_shortcut(run.shortcut)
    health = run.health()
    run.record("health-start", health)
    run.check(health.get("service") == SERVICE, "Centrum rozliczeń answers on Dad's port")
    run.check(health.get("commit") == facts["versions"]["first"][:7], "Centrum runs the tool's commit")
    process = run.centrum_process()
    (run.evidence / "state" / "proces-start.json").write_text(json.dumps(asdict(process), ensure_ascii=False, indent=2), encoding="utf-8")
    check_windowless(run, process)
    addresses = wait_for(lambda: run.opened_addresses() or None, timeout_s=30, what="Centrum opening Dad's tab")
    run.check(addresses == [url], f"Centrum opened {url} in Dad's browser")
    starts = [line for line in run.log_lines() if " start " in line]
    run.check(
        len(starts) == 1 and f"port={port}" in starts[0] and "konsola=nie" in starts[0],
        "the Centrum log has one start on Dad's port without a console",
    )

    run.step(FEATURE, "karta")
    page.goto(url)
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Wskaż folder okresów", exact=True)).to_be_visible()
    run.capture(page, "pierwszy-start")
    page.get_by_role("link", name="Konfiguracja", exact=True).click()
    card = page.get_by_role("region", name="Narzędzie", exact=True)
    expect(card).to_contain_text(f"Wersja {facts['versions']['first'][:7]}")
    run.capture(page, "konfiguracja-wersja")
    page.get_by_role("link", name="Okresy", exact=True).click()

    run.step(FEATURE, "drugie-klikniecie")
    log_before = len(run.log_lines())
    windows_desktop.start_shortcut(run.shortcut)
    addresses = wait_for(
        lambda: run.opened_addresses() if len(run.opened_addresses()) >= 2 else None,
        timeout_s=30,
        what="the second double click opening the tab again",
    )
    run.check(addresses == [url, url], "the second double click only opens Dad's tab again")
    wait_for(
        lambda: True if any(" juz-dziala " in line for line in run.log_lines()[log_before:]) else None,
        timeout_s=15,
        what="juz-dziala in the Centrum log",
    )
    print("  ok: the Centrum log has juz-dziala", flush=True)
    time.sleep(3)
    run.check(start_dialogs() == [], "no native window of Centrum appears")
    run.check(run.centrum_process().pid == process.pid, "the first Centrum still holds the port")
    def second_ended() -> bool | None:
        rest = [other for other in windows_desktop.processes_mentioning(str(run.run_centrum)) if other.pid != process.pid]
        return True if rest == [] else None

    wait_for(second_ended, timeout_s=15, what="the second start to end")
    print("  ok: the second start ended; one Centrum runs", flush=True)
