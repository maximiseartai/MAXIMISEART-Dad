"""Aktualizacja narzędzia on Windows: Centrum started by the shortcut updates its clone, closes, and comes back.

Everything after Dad's click is production code on this computer: Git for Windows moves the clone, pip installs the
new requirements with Centrum's own ``pythonw.exe``, the restart guardian runs detached from its copy and starts the
new version without a console, and rolls back a version that does not start. Only GitHub is local
(``windows_tool.boundaries``).
"""

from __future__ import annotations

import time

from playwright.sync_api import Page, expect

from windows_drive.common import Run, open_settings, settings_section, wait_for
from windows_drive.start_skrotem import check_windowless, start_dialogs
import windows_desktop
import windows_tool
from rozliczenia.centrum.tool_update import JOURNAL, RESULT_FILE
from rozliczenia.tool_files import config_dir

FEATURE = "aktualizacja"
BUTTON = "Zaktualizuj narzędzie"
UPDATED = "Zaktualizowano"
NEW_VERSION_FAILED = "Nowa wersja narzędzia nie wystartowała."
TO_MAKS = "Narzędzie działa dalej w poprzedniej wersji. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
# The guardian waits up to 60 s for the old Centrum to free the port and 60 s for the new one to answer.
RESTART_TIMEOUT_MS = 150_000
MARKER = "window.przedPonownymStartem"


def _guardian_ended(run: Run, centrum: int) -> None:
    def ended() -> bool | None:
        rest = [p for p in windows_desktop.processes_mentioning(str(run.tool)) if p.pid != centrum]
        return True if rest == [] else None

    wait_for(ended, timeout_s=60, what="the restart guardian (and Git, pip) to end")
    print("  ok: only Centrum runs from the tool's folder; the restart guardian ended", flush=True)


def _update_entries(run: Run) -> list[str]:
    lines = run.log_lines()
    starts = [index for index, line in enumerate(lines) if " aktualizacja-start " in line]
    return lines[starts[-1] :] if starts else []


def _stop_before_start(run: Run, entries: list[str]) -> None:
    events = [line.split(" ")[1] for line in entries]
    run.check(
        "stop" in events and "start" in events and events.index("stop") < events.index("start"),
        "the old Centrum logged stop before the new Centrum's start",
    )


def _started_without_console(run: Run, entries: list[str]) -> None:
    """The guardian gives the Centrum it starts ``NUL`` streams, so its log must not claim a console."""

    starts = [line for line in entries if " start " in line]
    run.check(len(starts) == 1, "the Centrum the guardian started logged one start")
    run.check("konsola=nie" in starts[0], f"the Centrum the guardian started logs no console: {starts[0].split(' start ')[1]!r}")


def _click_update(run: Run, page: Page) -> tuple[dict[str, object], int]:
    """Dad opens Ustawienia with the gear on a freshly loaded tab and clicks the update in the section Narzędzie."""

    health = run.health()
    pid = run.centrum_process().pid
    page.goto(run.url)
    page.reload()
    section = open_settings(page, "Narzędzie")
    expect(
        section,
        "the button needs the real GitHub API to name a Wydanie the run's clone lacks (ADR 0014, #319); "
        "`Nie sprawdzono` means no network or GitHub's hourly limit",
    ).to_contain_text("Jest nowsza wersja")
    expect(section.get_by_role("button", name=BUTTON, exact=True)).to_be_enabled()
    page.evaluate(f"{MARKER} = true")
    section.get_by_role("button", name=BUTTON, exact=True).click()
    return health, pid


def _clone_as_before(run: Run, commit: str, config: dict[str, str]) -> None:
    run.check(run.git("rev-parse", "HEAD") == commit, f"the clone stands on {commit[:7]}")
    run.check(run.git("status", "--porcelain") == "", "the clone has no changed tracked file")
    run.check(run.config_bytes() == config, "every file in config/ (Dad's and Centrum's) has its bytes from before")
    leftovers = [name for name in (RESULT_FILE, JOURNAL) if (config_dir(run.tool) / name).exists()]
    run.check(leftovers == [], "no update result or journal is left in config/")


def drive(run: Run, page: Page) -> None:
    versions = run.facts["versions"]
    first, newest, not_starting = versions["first"], versions["newest"], versions["not_starting"]
    config = run.config_bytes()

    run.step(FEATURE, "zaktualizowano")
    run.harness("GitHub's newest Wydanie (the run's origin) is one version ahead, with changed requirements")
    windows_tool.release(run.facts, "newest")
    before, old_pid = _click_update(run, page)
    toast = page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)
    expect(toast).to_be_visible(timeout=RESTART_TIMEOUT_MS)
    expect(toast).to_contain_text(f"Centrum działa w wersji {newest[:7]}.")
    run.check(page.evaluate(f"{MARKER} === undefined"), "the tab reloaded by itself")
    run.capture(page, "zaktualizowano")
    after = run.health()
    run.record("health-po-aktualizacji", after)
    run.check(after.get("commit") == newest[:7] and after.get("instance") != before.get("instance"), "a new Centrum answers in the new commit")
    process = run.centrum_process()
    run.check(process.pid != old_pid, "the new Centrum is another process")
    check_windowless(run, process, by_guardian=True)
    _guardian_ended(run, process.pid)
    _clone_as_before(run, newest, config)
    entries = _update_entries(run)
    print("  log:\n    " + "\n    ".join(entries), flush=True)
    run.check(f"aktualizacja-start przed={first}" in entries[0], "the log has the update's start from the first version")
    finished = f"aktualizacja-koniec wynik=ok przed={first} po={newest} biblioteki=tak"
    run.check(any(finished in line for line in entries), f"the log has {finished!r} (pip ran under pythonw.exe)")
    run.check(any(" zamkniecie z=aktualizacja" in line for line in entries), "the old Centrum closed itself for the update")
    _stop_before_start(run, entries)
    _started_without_console(run, entries)
    # The tab reloads on the address it had, so Ustawienia is open again on Narzędzie.
    version = settings_section(page).get_by_role("listitem", name="Wersja narzędzia")
    expect(version).to_contain_text(newest[:7])
    run.capture(page, "ustawienia-nowa-wersja")
    run.check(start_dialogs() == [], "no native window appeared")

    run.step(FEATURE, "nie-wystartowala")
    run.harness("GitHub's newest Wydanie is a version whose Centrum fails at once")
    windows_tool.release(run.facts, "not_starting")
    before, old_pid = _click_update(run, page)
    alert = page.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)
    expect(alert.first).to_be_visible(timeout=RESTART_TIMEOUT_MS)
    expect(alert.first).to_contain_text(TO_MAKS)
    run.check(page.evaluate(f"{MARKER} === undefined"), "the tab reloaded by itself on the old version")
    expect(page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)).to_have_count(0)
    run.capture(page, "nowa-wersja-nie-wystartowala")
    after = run.health()
    run.record("health-po-cofnieciu", after)
    run.check(after.get("commit") == newest[:7] and after.get("instance") != before.get("instance"), "the old version answers again, restarted")
    process = run.centrum_process()
    check_windowless(run, process, by_guardian=True)
    _guardian_ended(run, process.pid)
    _clone_as_before(run, newest, config)
    entries = _update_entries(run)
    print("  log:\n    " + "\n    ".join(entries), flush=True)
    failed = f"aktualizacja-koniec wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={newest} po={not_starting} biblioteki=nie"
    run.check(any(failed in line for line in entries), f"the log has {failed!r}")
    _stop_before_start(run, entries)
    _started_without_console(run, entries)
    time.sleep(2)
    run.check(start_dialogs() == [], "no native window appeared: the old version took over")
    run.harness("GitHub's newest Wydanie is the newest version again")
    windows_tool.release(run.facts, "newest")
