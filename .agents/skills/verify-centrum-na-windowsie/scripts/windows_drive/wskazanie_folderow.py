"""Wskazanie folderów: Dad picks the folder okresów and the Rejestr zleceń in Windows' own windows, then opens a folder.

The pickers are the production tkinter dialogs of ``_TkPlatform``, opened by Centrum in its request thread. The drive
answers them the way Dad does, by typing the path into the dialog's name box and confirming; Explorer is the real
one that ``os.startfile`` opens.
"""

from __future__ import annotations

from pathlib import Path
import time

from playwright.sync_api import Page, expect
import yaml

from windows_drive.common import DriveFailure, Run, same_path, wait_for
import windows_desktop

FEATURE = "wskazanie-folderow"
OPENED_FOLDER = "15_21_09_2026"
# The titles of Centrum's pickers, as Dad reads them.
PERIODS_DIALOG = "Wybierz folder okresów (np. Załączniki albo INEA)"
REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"


def _settings(run: Run) -> dict[str, object]:
    path = run.tool / "config" / "centrum-ustawienia.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    return document if isinstance(document, dict) else {}


def _pick(run: Run, title: str, path: Path, name: str) -> None:
    """Answers Centrum's native dialog ``title`` with ``path``.

    When the first confirm only opened the folder in the dialog, an empty name box confirms the open folder.
    """

    centrum = run.centrum_process().pid
    dialog = wait_for(
        lambda: next(
            (w for w in windows_desktop.visible_windows([centrum]) if w.cls == windows_desktop.DIALOG and w.title == title),
            None,
        ),
        timeout_s=30,
        what=f"Centrum's native window {title!r}",
    )
    print(f"  ok: Centrum's own process shows the native window {title!r}", flush=True)
    run.desktop(f"{name}-okno")
    for attempt in (1, 2):
        windows_desktop.answer_file_dialog(dialog, str(path) if attempt == 1 else "")
        if windows_desktop.wait_until_gone(dialog, timeout_s=5):
            print(f"  ok: the window closed after confirm {attempt}", flush=True)
            return
        run.harness(f"the window is still open after confirm {attempt} (it opened the folder); confirming again")
    raise DriveFailure(f"the native window {title!r} did not close after two confirms")


def drive(run: Run, page: Page) -> None:
    periods = Path(run.facts["periods_directory"])
    register = Path(run.facts["order_register"])

    run.step(FEATURE, "folder-okresow")
    page.goto(run.url)
    page.get_by_role("button", name="Wskaż folder okresów", exact=True).click()
    _pick(run, PERIODS_DIALOG, periods, "folder-okresow")
    table = page.get_by_role("table", name="Tablica okresów")
    expect(table).to_be_visible(timeout=20_000)
    # The last complete period depends on today's date, so only the periods with a folder on disk are checked.
    for token in run.facts["board"]:
        if (periods / token).is_dir():
            expect(table.get_by_role("row").filter(has_text=token)).to_have_count(1)
    run.check(same_path(str(_settings(run).get("folder_okresow")), periods), "the settings file holds the picked folder okresów")
    run.record("ustawienia-folder", run.get("/api/settings"))
    run.capture(page, "tablica-okresow")

    run.step(FEATURE, "rejestr-zlecen")
    page.get_by_role("button", name="Wskaż Rejestr zleceń", exact=True).click()
    _pick(run, REGISTER_DIALOG, register, "rejestr-zlecen")
    group = page.get_by_role("group", name="Rejestr zleceń")
    expect(group).to_contain_text(register.name, timeout=20_000)
    run.check(same_path(str(_settings(run).get("rejestr_zlecen")), register), "the settings file holds the picked Rejestr zleceń")
    run.record("ustawienia-rejestr", run.get("/api/settings"))
    run.capture(page, "rejestr-zlecen")

    run.step(FEATURE, "otwarcie-folderu")
    before = {window.handle for window in windows_desktop.visible_windows() if window.cls == windows_desktop.EXPLORER}
    page.get_by_role("button", name=f"Folder okresu, okres {OPENED_FOLDER}", exact=True).click()
    toast = page.get_by_role("region", name="Notifications").get_by_role("dialog", name="Otwieram")
    expect(toast.filter(has_text=OPENED_FOLDER)).to_have_count(1)

    def new_explorer() -> windows_desktop.Window | None:
        for window in windows_desktop.visible_windows():
            if window.cls == windows_desktop.EXPLORER and window.handle not in before and OPENED_FOLDER in window.title:
                return window
        return None

    try:
        explorer = wait_for(new_explorer, timeout_s=30, what=f"an Explorer window on {OPENED_FOLDER}")
    except DriveFailure:
        print(f"  windows now: {[(w.cls, w.title) for w in windows_desktop.visible_windows()]}", flush=True)
        raise
    print(f"  ok: Explorer shows {explorer.title!r}", flush=True)
    time.sleep(1)
    run.desktop("eksplorator")
    windows_desktop.close(explorer)
    run.check(windows_desktop.wait_until_gone(explorer, timeout_s=10), "the Explorer window closes")
