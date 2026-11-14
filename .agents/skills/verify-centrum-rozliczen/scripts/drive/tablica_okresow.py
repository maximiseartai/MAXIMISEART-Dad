"""Drive features/tablica-okresow.md."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import urllib.request

from playwright.sync_api import Locator, Page, expect

from drive.common import (
    dad_tab,
    Run,
    choose_periods_directory,
    error_toasts,
    last_opened_is,
    next_step_names_current_step,
    period_row,
    remove,
    remove_tree,
    sent_requests,
    settle,
)
from drive.waiting import until
from atrapy.scenariusz_centrum import NEEDS_CHECK
from harness import Log


def _worker_settlement_count(row: dict[str, object]) -> int:
    """Rozliczenia pracownika on the period's Folder rozliczeń pracowników button; 0 without that folder."""

    files = row["files"]
    assert isinstance(files, list)
    [count] = [file["count"] for file in files if file["target"] == "worker_settlements_folder"]
    return int(count or 0)


def drive(run: Run, page: Page) -> None:
    feature = "tablica-okresow"
    periods = Path(run.fixture["periods_directory"])

    run.step(feature, "tablica-kolejnosc-i-status")
    page.goto(run.url)
    if run.api("/api/settings", "tablica-ustawienia")["periods_directory"] == {"state": "not_set"}:
        choose_periods_directory(run, page)
    board = run.api("/api/periods", "tablica-okresow")
    rows = board["periods"]
    assert isinstance(rows, list)
    expected = run.fixture["board"]
    run.check(
        [[row["token"], row["status"], _worker_settlement_count(row), row["last_complete"]] for row in rows]
        == expected,
        "the server lists every Folder okresu newest first with its Status okresu",
    )
    table_rows = page.get_by_role("table", name="Tablica okresów").get_by_role("row")
    expect(table_rows).to_have_count(len(expected) + 1)
    labels = {"no_period_files": "Brak plików okresu", "collective_file_prepared": "Plik zbiorczy przygotowany",
              "worker_settlements_ready": "Rozliczenia pracowników gotowe"}
    for index, (token, status, _, last_complete) in enumerate(expected, start=1):
        row = table_rows.nth(index)
        expect(row).to_contain_text(token)
        expect(row).to_contain_text(labels[status])
        if last_complete:
            expect(row).to_have_attribute("data-state", "selected")
            expect(row).to_contain_text("ostatni pełny okres")
    run.check(True, "the screen shows the same order, Status okresu, and highlighted last complete period")
    run.check(
        all(
            ("preview_hint" in row["next_step"])
            == (row["next_step"]["action"] not in ("none", "fill_collective_file"))
            for row in rows
        ),
        "every process step carries its Podgląd bez zapisu hint; Uzupełnienie w Excelu and a closed period have none",
    )
    run.capture(page, "06-tablica-okresow")

    run.step(feature, "tablica-droga-okresu")
    steps = {row["token"]: row for row in rows}
    run.check(
        [step["label"] for step in steps[NEEDS_CHECK]["path"]]
        == ["Plik zbiorczy", "Uzupełnienie w Excelu", "Wycena w efenix", "Rozliczenia pracowników"]
        and [step["stage"] for step in steps[NEEDS_CHECK]["path"]] == ["done", "now", "later", "later"]
        and [step["stage"] for step in steps["22_28_09_2026"]["path"]] == ["done", "done", "not_done", "done"],
        "Droga okresu has four steps; a closed period without Wycena w efenix shows that step as not done",
    )
    filling = steps[NEEDS_CHECK]["next_step"]
    run.check(
        (filling["action"], filling["label"], filling["then"]["action"], filling["then"]["preview_hint"])
        == ("fill_collective_file", "Uzupełnij plik zbiorczy", "price_in_efenix", None)
        and steps[NEEDS_CHECK]["secondary_step"]["action"] == "create_worker_settlements"
        and all(row["secondary_step"] is None for row in rows if row["token"] != NEEDS_CHECK),
        "with a Plik zbiorczy and no Wycena w efenix, the next step is Uzupełnij plik zbiorczy, then Wycena w efenix "
        "(no preview), and Przebieg rozliczeń stays reachable beside it",
    )
    prepared = period_row(page, NEEDS_CHECK)
    row_steps = prepared.get_by_role("cell").last.get_by_role("button")
    names = ["Utwórz rozliczenia pracowników", "Wyceń w efenix", "Uzupełnij"]
    expect(row_steps).to_have_count(len(names))
    for index, name in enumerate(names):
        expect(row_steps.nth(index)).to_have_accessible_name(f"{name}, okres {NEEDS_CHECK}")
    run.check(
        True,
        f"the row of {NEEDS_CHECK} offers Uzupełnij and, beside it, Wyceń w efenix and Utwórz rozliczenia pracowników",
    )
    prepared.get_by_role("button", name=f"Wyceń w efenix, okres {NEEDS_CHECK}", exact=True).click()
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    expect(page.get_by_role("radio", name="Wycena w efenix")).to_be_checked()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(NEEDS_CHECK)
    run.check(True, "Wyceń w efenix opens a new Uruchomienie with the tile Wycena w efenix and that period chosen")
    # A reload forgets the chosen tile, so later features start from the default Nowe Uruchomienie procesu.
    page.goto(run.url + "#/okresy")
    page.reload()
    expect(page.get_by_role("table", name="Tablica okresów")).to_be_visible()

    run.step(feature, "tablica-nastepny-krok")
    next_step = next_step_names_current_step(run, page, expected[0][0], "Plik zbiorczy")
    expect(next_step).to_contain_text("Brak Folderu okresu")
    expect(next_step.get_by_role("button", name="Podgląd bez zapisu", exact=True)).to_be_visible()
    run.check(True, "Następny krok targets the last complete period, whose Folder okresu does not exist")

    run.step(feature, "tablica-otwieranie")
    opened_before = len(run.lines(Log.OPENED))
    clicks = [
        (f"Plik zbiorczy, okres {NEEDS_CHECK}", periods / NEEDS_CHECK / f"Rozliczenie {NEEDS_CHECK} - zbiorcze.xlsx"),
        ("Rozliczenie wewnętrzne, okres 22_28_09_2026", periods / "22_28_09_2026" / "Rozliczenie wew. 22_28_09_2026.xlsx"),
        ("Folder okresu, okres 15_21_09_2026", periods / "15_21_09_2026"),
        ("Folder rozliczeń pracowników: 3, okres 22_28_09_2026",
         periods / "22_28_09_2026" / "Rozliczenie pracowników 22_28_09_2026"),
    ]
    for name, path in clicks:
        page.get_by_role("button", name=name, exact=True).click()
        until(last_opened_is(run, path), f"{name} opened {path.name}")
        expect(page.get_by_text(path.name, exact=True).last).to_be_visible()
    run.check(len(run.lines(Log.OPENED)) == opened_before + len(clicks), "one open per click, nothing else")
    run.capture(page, "07-tablica-otwieranie", full_page=False)
    missing = page.get_by_role("button", name="Plik zbiorczy, okres 15_21_09_2026", exact=True)
    expect(missing).to_be_disabled()
    run.check(True, "a period file that does not exist cannot be opened")

    run.step(feature, "tablica-brakujacy-plik")
    hint = page.get_by_text("Plik zbiorczy: jeszcze nie ma", exact=True)
    opened_before = len(run.lines(Log.OPENED))
    missing.hover()
    expect(hint).to_be_visible()
    run.capture(page, "156-tablica-brakujacy-plik", full_page=False)
    with sent_requests(page, "POST", "/api/periods/*/open") as sent:
        missing.click(force=True)
        settle(page, sent, at_least=0)
    expect(hint).to_be_visible()
    run.check(
        len(sent) == 0 and len(run.lines(Log.OPENED)) == opened_before,
        "hovering the missing Plik zbiorczy shows „jeszcze nie ma”; a click keeps the hint and opens nothing",
    )
    page.mouse.move(4, 4)
    expect(hint).to_have_count(0)
    page.get_by_role("button", name="Rozliczenie wewnętrzne, okres 15_21_09_2026", exact=True).focus()
    page.keyboard.press("Tab")
    expect(missing).to_be_focused()
    expect(hint).to_be_visible()
    run.check(True, "Tab reaches the missing file's button and shows the same hint")
    page.keyboard.press("Escape")
    with dad_tab(page, touch=True) as touch:
        touch.goto(run.url + "#/okresy")
        touch_hint = touch.get_by_text("Plik zbiorczy: jeszcze nie ma", exact=True)
        # Playwright taps only enabled elements; the button is aria-disabled on purpose, so the tap is forced.
        touch.get_by_role("button", name="Plik zbiorczy, okres 15_21_09_2026", exact=True).tap(force=True)
        expect(touch_hint).to_be_visible()
        run.capture(touch, "157-tablica-brakujacy-plik-dotyk", full_page=False)
        touch.get_by_role("heading", name="Okresy", exact=True).tap()
        expect(touch_hint).to_have_count(0)
        run.check(len(run.lines(Log.OPENED)) == opened_before, "a finger tap shows the hint, a tap beside hides it")

    run.step(feature, "tablica-podwojne-klikniecie")
    closed = periods / "22_28_09_2026"
    notifications = page.get_by_role("region", name="Notifications")
    repeated_clicks: list[tuple[str, Path, str, Callable[[Locator], None]]] = [
        ("Folder okresu, okres 22_28_09_2026", closed, "a double click", lambda button: button.dblclick()),
        ("Plik zbiorczy, okres 22_28_09_2026", closed / "Rozliczenie 22_28_09_2026 - zbiorcze.xlsx",
         "a fast triple click", lambda button: button.click(click_count=3)),
    ]
    for name, path, how, click in repeated_clicks:
        opened_before = len(run.lines(Log.OPENED))
        with sent_requests(page, "POST", "/api/periods/22_28_09_2026/open") as sent:
            click(page.get_by_role("button", name=name, exact=True))
            settle(page, sent)
        run.check(len(sent) == 1, f"{how} on {name} asks the server once ({len(sent)} requests)")
        run.check(run.lines(Log.OPENED)[opened_before:] == [{"path": str(path)}], f"{how} opens {path.name} once")
        confirmations = notifications.get_by_role("dialog", name="Otwieram").filter(
            has=page.get_by_text(path.name, exact=True)
        )
        expect(confirmations.first).to_be_visible()
        run.check(confirmations.count() == 1, f"{how} shows one Otwieram for {path.name} ({confirmations.count()})")
    run.check(error_toasts(page).count() == 0, "no error toast after the repeated clicks")
    run.capture(page, "1a-tablica-podwojne-klikniecie", full_page=False)

    run.step(feature, "tablica-zmiana-na-dysku")
    changed = periods / "15_21_09_2026"
    outside = [changed / name for name in ("Rozliczenie wew. 15_21_09_2026.xlsx", "Rozliczenie 15_21_09_2026 - zbiorcze.xlsx")]
    for path in outside:
        path.write_bytes(b"")
    page.reload()
    expect(period_row(page, "15_21_09_2026")).to_contain_text("Plik zbiorczy przygotowany")
    run.check(True, "after a reload the board shows a Plik zbiorczy added outside Centrum")
    (changed / "Rozliczenie pracowników 15_21_09_2026").mkdir()
    # Headless Chromium keeps every tab visible, so returning to the tab is simulated with the
    # `focus` event the browser fires then; the page itself is not touched.
    page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
    expect(period_row(page, "15_21_09_2026")).to_contain_text("Rozliczenia pracowników gotowe")
    run.check(True, "a (simulated) return to the tab shows a Folder rozliczeń pracowników added outside Centrum")
    run.capture(page, "08-tablica-po-zmianie-na-dysku")

    run.step(feature, "tablica-powrot-z-menu")
    added = changed / "Rozliczenie pracowników 15_21_09_2026" / "Rozliczenie 15_21_09_2026 - Wykonawca.xlsx"
    page.get_by_role("link", name="Metryki", exact=True).click()
    expect(page.get_by_role("heading", name="Metryki", level=1)).to_be_visible()
    added.write_bytes(b"")
    try:
        page.get_by_role("link", name="Okresy", exact=True).click()
        expect(page.get_by_role("button", name="Folder rozliczeń pracowników: 1, okres 15_21_09_2026", exact=True)).to_be_visible()
        run.check(True, "back on Okresy from the menu, the board is read again: a Rozliczenie pracownika added meanwhile counts")
    finally:
        remove(added)

    run.step(feature, "tablica-odczyt-w-tle-nieudany")
    page.get_by_role("link", name="Metryki", exact=True).click()
    expect(page.get_by_role("heading", name="Metryki", level=1)).to_be_visible()
    # Harness: the server stops answering /api/periods (the request fails like an unreachable Centrum).
    page.route("**/api/periods", lambda route: route.abort())
    try:
        page.get_by_role("link", name="Okresy", exact=True).click()
        failure = page.get_by_role("alert").filter(has_text="Nie udało się odczytać okresów")
        expect(failure).to_contain_text("Centrum rozliczeń nie odpowiada.")
        expect(page.get_by_role("table", name="Tablica okresów")).to_have_count(0)
        run.check(True, "a failed read behind the last board (unreachable server, harness) shows the Komunikat, not the old board")
        run.capture(page, "17-tablica-odczyt-nieudany")
    finally:
        page.unroute("**/api/periods")
    page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
    expect(period_row(page, "15_21_09_2026")).to_contain_text("Rozliczenia pracowników gotowe")
    run.check(True, "once the server answers, a (simulated) return to the tab shows the board again")
    # The period goes back to the fixture's: its empty Plik zbiorczy is unreadable, and a later feature of the run reads
    # every Plik zbiorczy (the check of periods before Dad removes a Wykonawca), #1589.
    remove_tree(changed / "Rozliczenie pracowników 15_21_09_2026")
    for path in outside:
        remove(path)

    run.step(feature, "tablica-podpowiedz")
    period_row(page, NEEDS_CHECK).get_by_text("Wyceń w efenix").hover()
    expect(page.get_by_text("Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.")).to_be_visible()
    run.capture(page, "09-tablica-podpowiedz", full_page=False)
    period_row(page, NEEDS_CHECK).get_by_text("Uzupełnij", exact=True).hover()
    expect(page.get_by_text("Uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.", exact=True)).to_be_visible()
    period_row(page, NEEDS_CHECK).get_by_text("Utwórz rozliczenia pracowników").hover()
    expect(page.get_by_text("Możesz je utworzyć także bez Wyceny w efenix, na przykład gdy efenix nie działa.")).to_be_visible()
    run.check(
        True,
        "Wyceń w efenix, Uzupełnij and Utwórz rozliczenia pracowników in the row explain themselves in tooltips",
    )
    preview_hint = rows[0]["next_step"]["preview_hint"]
    page.get_by_role("region", name="Następny krok").get_by_role("button", name="Podgląd bez zapisu", exact=True).hover()
    expect(page.get_by_text(preview_hint, exact=True)).to_be_visible()
    run.check(True, "Podgląd bez zapisu on Następny krok shows the hint the board sent for its period")

    run.step(feature, "tablica-ochrona")
    opened = len(run.lines(Log.OPENED))
    open_url = run.url.rstrip("/") + "/api/periods/22_28_09_2026/open"
    payload = json.dumps({"target": "collective_file"}).encode()
    foreign_origin = urllib.request.Request(
        open_url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Origin": "http://zly.example"},
    )
    foreign_host = urllib.request.Request(run.url.rstrip("/") + "/api/health", headers={"Host": "zly.example"})
    run.check(run.refused(foreign_origin, "odmowa-obcy-origin") == 403, "an action from a foreign Origin is refused")
    run.check(run.refused(foreign_host, "odmowa-obcy-host") == 403, "a request with a foreign Host is refused")
    run.check(len(run.lines(Log.OPENED)) == opened, "a refused request opens nothing")
