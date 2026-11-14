"""Drive features/ustawienia.md."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit

from playwright.sync_api import Locator, Page, Request, Route, ViewportSize, expect

from drive.common import (
    CENTRE_TAKES_CLICK,
    DAD_VIEWPORT,
    Run,
    choose_periods_directory,
    close_settings,
    error_toasts,
    move,
    open_settings,
    put_text,
    read_bytes,
    read_text,
    remove,
    remove_tree,
    sent_requests,
    settings_title,
    settings_window,
    settle,
    unreadable,
)
from drive.waiting import Budget, answer_late, quiet_for, until
from harness import INBOX_ADDRESS, INBOX_PASSWORD, File, Log, Switch


FOLDERS = "#/ustawienia/foldery"
POLISH_LETTERS = "Hasło aplikacji ma tylko litery i cyfry, bez polskich znaków."


FEATURE = "ustawienia"
# The narrow browser window of the window Ustawienia (full screen, sections in a combobox).
NARROW: ViewportSize = {"width": 420, "height": 860}
AUTOSTART = "Uruchamiaj Centrum razem z Windows"


def drive(run: Run, page: Page) -> None:
    feature = FEATURE
    register_name = Path(run.fixture["order_register"]).name
    window = settings_window(page)
    register = window.get_by_role("listitem", name="Rejestr zleceń")
    periods = window.get_by_role("listitem", name="Folder okresów")

    run.step(feature, "ustawienia-pusty-stan")
    page.goto(run.url)
    expect(page.get_by_text("Wskaż folder okresów", exact=True).first).to_be_visible()
    expect(page.get_by_role("link", name="Ustaw w Ustawieniach", exact=True)).to_be_visible()
    settings = run.api("/api/settings", "ustawienia-przed")
    run.check(
        settings["order_register"] == {"state": "not_set"} and settings["periods_directory"] == {"state": "not_set"},
        "no settings file means nothing is set",
    )
    run.capture(page, "01-ustawienia-pusty-stan")

    run.step(feature, "ustawienia-jedno-okno-wyboru")
    dialogs = len(run.lines(Log.DIALOGS))
    before = run.settings_text()
    pickers = ("Wskaż Rejestr zleceń", "Wskaż Folder okresów")
    page.get_by_role("link", name="Ustaw w Ustawieniach", exact=True).click()
    folder_picker = window.get_by_role("button", name="Wskaż Folder okresów", exact=True)
    held: list[Route] = []
    # Harness: each picker request is held, as Dad's native window stays open until he picks or closes it.
    page.route("**/api/settings/*/choose", lambda route: held.append(route))
    try:
        folder_picker.dblclick()
        until(lambda: len(held) >= 1, "the double click on Wskaż Folder okresów asks for a picker", page=page)
        quiet_for(page)
        run.check(len(held) == 1, f"a double click on Wskaż Folder okresów opens one picker ({len(held)} requests)")
        expect(folder_picker).to_contain_text("Czekam na wybór…")
        for name in pickers:
            expect(window.get_by_role("button", name=name, exact=True)).to_be_disabled()
        run.check(True, "while the picker is open (held, harness), both picker buttons of Foldery wait for it")
        run.capture(page, "19-ustawienia-jedno-okno-wyboru", live=True)  # the waiting spinner turns forever
        close_settings(page)
        page.get_by_role("link", name="Uruchomienia", exact=True).click()
        expect(page.get_by_role("heading", name="Uruchomienia", level=1)).to_be_visible()
        open_settings(page, "Foldery")
        for name in pickers:
            expect(window.get_by_role("button", name=name, exact=True)).to_be_disabled()
        run.check(True, "closed and opened again over Uruchomienia, Foldery still waits for the open picker")
        run.check(len(held) == 1, f"no button opened a second picker ({len(held)} requests)")
    finally:
        for route in held:
            route.continue_()
        page.unroute("**/api/settings/*/choose")
    until(lambda: len(run.lines(Log.DIALOGS)) == dialogs + 1, "Dad closed the one picker (cancel)")
    for name in pickers:
        expect(window.get_by_role("button", name=name, exact=True)).to_be_enabled()
    run.check(run.settings_text() == before, "after the cancelled picker every picker button works again, nothing set")
    close_settings(page)
    page.get_by_role("link", name="Okresy", exact=True).click()

    run.step(feature, "ustawienia-folder-okresow")
    choose_periods_directory(run, page)
    run.check(
        run.lines(Log.DIALOGS)[-1]["title"] == "Wybierz folder okresów (np. Załączniki albo INEA)",
        "the folder picker opened with its title",
    )
    run.check(
        run.remembered("folder_okresow") == run.fixture["periods_directory"],
        "the settings file remembers the folder okresów",
    )
    run.capture(page, "02-ustawienia-folder-okresow")

    run.step(feature, "ustawienia-rejestr-zlecen")
    missing_register = page.get_by_role("alert").filter(has_text="Najpierw wskaż Rejestr zleceń.")
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    expect(missing_register).to_be_visible()
    unset = page.get_by_role("group", name="Rejestr zleceń")
    expect(unset).to_contain_text("Rejestr zleceń: nie wskazano")
    expect(unset.get_by_role("link", name="Ustaw w Ustawieniach", exact=True)).to_have_attribute("href", FOLDERS)
    run.check(True, "before the Rejestr zleceń is set, Uruchomienia says it is missing and links to Foldery")
    unset.get_by_role("link", name="Ustaw w Ustawieniach", exact=True).click()
    expect(settings_title(page)).to_have_text("Ustawienia/Foldery")
    run.answer_picker(run.fixture["order_register"])
    window.get_by_role("button", name="Wskaż Rejestr zleceń", exact=True).click()
    expect(register.get_by_text(register_name)).to_be_visible()
    run.check(run.lines(Log.DIALOGS)[-1]["title"] == "Wybierz plik Rejestru zleceń", "the file picker opened")
    run.check(
        run.remembered("rejestr_zlecen") == run.fixture["order_register"],
        "the settings file remembers the Rejestr zleceń",
    )
    run.capture(page, "03-ustawienia-rejestr-zlecen")

    run.step(feature, "ustawienia-braki-do-startu")
    close_settings(page)
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    expect(missing_register).to_have_count(0)
    expect(page.get_by_role("group", name="Rejestr zleceń").get_by_role("link")).to_have_count(0)
    expect(page.get_by_role("button", name="Podgląd bez zapisu", exact=True)).to_be_enabled()
    processes = run.api("/api/runs/setup", "ustawienia-braki-do-startu")["processes"]
    assert isinstance(processes, list)
    run.check(
        [process["blocker"] for process in processes if process["process"] == "preparation"] == [None],
        "the Rejestr zleceń pointed in Ustawienia is no longer missing on Uruchomienia under it: its start is read again",
    )
    run.capture(page, "18-ustawienia-braki-do-startu")

    run.step(feature, "ustawienia-motyw-bez-odczytu")
    setup_reads: list[str] = []

    def count_setup(request: Request) -> None:
        if urlsplit(request.url).path == "/api/runs/setup":
            setup_reads.append(request.method)

    page.on("request", count_setup)
    try:
        themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw")
        with sent_requests(page, "PUT", "/api/settings/theme") as saves:
            for click, theme in (("Jasny", "light"), ("Ciemny", "dark")):
                themes.get_by_role("button", name=click, exact=True).click()
                expect(themes.get_by_role("button", name=click, exact=True)).to_have_attribute("aria-pressed", "true")
                until(lambda: run.remembered("motyw") == theme, f"the settings file remembers {theme}")
            # A remount on the server's answer would read the start again once that answer reached the page.
            settle(page, saves)
        close_settings(page)
    finally:
        page.remove_listener("request", count_setup)
    expect(page.get_by_role("button", name="Podgląd bez zapisu", exact=True)).to_be_enabled()
    run.check(
        setup_reads == [], f"switching the theme over Uruchomienia does not read the start again ({len(setup_reads)} reads)"
    )
    page.get_by_role("link", name="Okresy", exact=True).click()

    run.step(feature, "ustawienia-anulowanie")
    before = run.settings_text()
    dialogs = len(run.lines(Log.DIALOGS))
    open_settings(page, "Foldery").get_by_role("button", name="Zmień Rejestr zleceń", exact=True).click()
    until(lambda: len(run.lines(Log.DIALOGS)) == dialogs + 1, "the cancelled picker was shown")
    expect(window.get_by_role("button", name="Zmień Rejestr zleceń", exact=True)).to_be_enabled()
    expect(register.get_by_text(register_name)).to_be_visible()
    run.check(run.settings_text() == before, "a cancelled picker leaves the settings file unchanged")

    run.step(feature, "ustawienia-nieistniejaca-sciezka")
    moved = Path(run.fixture["order_register"] + ".przeniesiony")
    move(Path(run.fixture["order_register"]), moved)
    try:
        page.reload()
        expect(register.get_by_text(f"Nie ma już: {register_name}")).to_be_visible()
        run.check(run.api("/api/settings", "ustawienia-brak-rejestru")["order_register"] == {
            "state": "missing",
            "path": run.fixture["order_register"],
            "name": register_name,
        }, "a remembered Rejestr zleceń that is gone is reported as missing")
        run.capture(page, "04-ustawienia-brak-rejestru")
    finally:
        move(moved, run.fixture["order_register"])
    page.reload()
    expect(register.get_by_text(register_name, exact=True)).to_be_visible()

    run.step(feature, "ustawienia-nieczytelny-plik")
    with unreadable(Path(run.fixture["settings"])):
        page.reload()
        for row in (register, periods):
            expect(row.get_by_text("Nie da się teraz odczytać Ustawień Centrum", exact=True)).to_be_visible()
        settings = run.api("/api/settings", "ustawienia-nieczytelny-plik")
        run.check(
            settings["order_register"] == settings["periods_directory"] == {"state": "unreadable"},
            "a settings file that cannot be read now is reported as unreadable, not as nothing chosen",
        )
        run.capture(page, "275-ustawienia-nieczytelny-plik")
    page.reload()
    expect(register.get_by_text(register_name, exact=True)).to_be_visible()

    run.step(feature, "ustawienia-niedostepna-sciezka")
    with _without_access(run, page) as (register_path, periods_path):
        page.reload()
        for row, path in ((register, register_path), (periods, periods_path)):
            expect(row.get_by_text(f"Nie da się teraz odczytać: {path.name}", exact=True)).to_be_visible()
        run.capture(page, "276-ustawienia-niedostepna-sciezka")
    page.reload()
    expect(register.get_by_text(register_name, exact=True)).to_be_visible()
    expect(periods.get_by_text(Path(run.fixture["periods_directory"]).name, exact=True)).to_be_visible()

    run.step(feature, "ustawienia-motyw")
    themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw")
    themes.get_by_role("button", name="Jasny", exact=True).click()
    expect(page.locator("html")).not_to_have_class("dark")
    until(lambda: run.remembered("motyw") == "light", "the settings file remembers the light theme")
    page.reload()
    expect(themes.get_by_role("button", name="Jasny", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.locator("html")).not_to_have_class("dark")
    run.capture(page, "05-ustawienia-motyw-jasny")
    themes.get_by_role("button", name="Ciemny", exact=True).click()
    expect(page.locator("html")).to_have_class("dark")
    until(lambda: run.remembered("motyw") == "dark", "the dark theme is remembered again")
    close_settings(page)

    _saved_and_undo(run, page)
    _failure_in_window(run, page)
    _failure_after_window(run, page)
    _failure_keeps_next_choice(run, page)
    _history(run, page)
    _history_release(run, page)
    _refusal_at_field(run, page)
    _typed_keeps_other(run, page)
    _bad_settings_file(run, page)
    _autostart(run, page)
    _inbox_password(run, page)
    _reminders(run, page)


def _toast(scope: Page | Locator, title: str) -> Locator:
    """The toast ``title`` on screen, on the page or in a window of it (``scope``); a toast it replaced stays in the
    document while it slides out."""

    # `has` is matched inside each toast, so it is built on the page, not on the window.
    page = scope if isinstance(scope, Page) else scope.page
    return scope.locator("[data-slot=toast]:not([data-ending-style])").filter(has=page.get_by_text(title, exact=True))


def _saved_and_undo(run: Run, page: Page) -> None:
    """„Zapisano · Cofnij” after a switch, wide and narrow; „Cofnij” in the toast takes the change back."""

    run.step(FEATURE, "ustawienia-zapisano-cofnij")
    for viewport, capture in ((DAD_VIEWPORT, "306-ustawienia-zapisano-cofnij"), (NARROW, "307-ustawienia-zapisano-waskie")):
        # The gear is in the menu, which a narrow window hides: the window opens wide and the browser narrows.
        themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw")
        page.set_viewport_size(viewport)
        try:
            themes.get_by_role("button", name="Jasny", exact=True).click()
            until(lambda: run.remembered("motyw") == "light", "the switch saves at once")
            saved = _toast(page, "Zapisano")
            expect(saved.get_by_role("button", name="Cofnij", exact=True)).to_be_visible()
            run.check(True, f"the switch shows „Zapisano · Cofnij” ({viewport['width']} px)")
            run.capture(page, capture, full_page=False)
            # The toast's title is a heading in the window too: the window's own title still reads one path (#1534).
            open_settings(page, "Wygląd")
            saved.get_by_role("button", name="Cofnij", exact=True).click()
            # „Cofnięto” stands in the window Ustawienia, over its blurred page, like „Zapisano”.
            expect(_toast(settings_window(page), "Cofnięto")).to_be_visible()
            expect(page.locator("html")).to_have_class("dark")
            expect(themes.get_by_role("button", name="Ciemny", exact=True)).to_have_attribute("aria-pressed", "true")
            until(lambda: run.remembered("motyw") == "dark", "„Cofnij” in the toast takes the theme back")
            close_settings(page)
        finally:
            page.set_viewport_size(DAD_VIEWPORT)


# How late the failed save answers: after the two frames in which the theme switch turns transitions off, as a save
# at tata's answers, so the notification slides in from under the window's edge (400 ms) instead of standing at once.
LATE_ANSWER_S = 0.3


def _failure_in_window(run: Run, page: Page) -> None:
    """A save that fails shows its notification in the window Ustawienia, over its content, not under the blurred page."""

    run.step(FEATURE, "ustawienia-blad-w-oknie")
    theme = "**/api/settings/theme"
    themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw")

    def late_failure(route: Route) -> None:
        answer_late(route, LATE_ANSWER_S, lambda failed: failed.fulfill(status=500, body=""))

    page.route(theme, late_failure)
    try:
        themes.get_by_role("button", name="Jasny", exact=True).click()
        failure = settings_window(page).get_by_role("dialog", name="Nie udało się")
        expect(failure).to_be_visible()
        expect(error_toasts(page)).to_have_count(1)
        # Sliding in, the notification is visible while its centre is still under the window's edge (#1518).
        until(
            lambda: failure.evaluate(CENTRE_TAKES_CLICK),
            "a failed save is a notification in the window Ustawienia that nothing covers",
            Budget.TRANSIENT,
        )
        run.capture(page, "315-ustawienia-blad-w-oknie", full_page=False)
        expect(page.locator("html")).to_have_class("dark")
        expect(themes.get_by_role("button", name="Ciemny", exact=True)).to_have_attribute("aria-pressed", "true")
        run.check(True, "after the failed save the page is back in the theme of the settings file, without a reload")
    finally:
        page.unroute(theme)
    close_settings(page)
    page.reload()
    expect(page.locator("html")).to_have_class("dark")
    run.check(run.remembered("motyw") == "dark", "the failed save left the theme as it was")


def _failure_after_window(run: Run, page: Page) -> None:
    """A save that fails after Dad closed the window Ustawienia shows its notification over the page instead of nowhere."""

    run.step(FEATURE, "ustawienia-blad-po-zamknieciu")
    theme = "**/api/settings/theme"
    themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw")
    held: list[Route] = []
    # Harness: the save is held, as a save at tata's can answer after he closed the window.
    page.route(theme, lambda route: held.append(route))
    try:
        themes.get_by_role("button", name="Jasny", exact=True).click()
        until(lambda: len(held) >= 1, "the click on Jasny saves Motyw", page=page)
        quiet_for(page)
        run.check(len(held) == 1, f"the save of Motyw waits for its answer ({len(held)} requests, held)")
        close_settings(page)
        held.pop().fulfill(status=500, body="")
        expect(error_toasts(page)).to_have_count(1)
        expect(error_toasts(page)).to_be_visible()
        run.check(True, "a save that fails after the window Ustawienia closed is a notification over the page")
        run.capture(page, "341-ustawienia-blad-po-zamknieciu", full_page=False)
    finally:
        for route in held:
            route.continue_()
        page.unroute(theme)
    expect(page.locator("html")).to_have_class("dark")
    run.check(run.remembered("motyw") == "dark", "the save that failed after the window closed left the theme as it was")


def _failure_keeps_next_choice(run: Run, page: Page) -> None:
    """A failed save of Motyw takes the page back to the theme of the settings file only when it was Dad's last choice:
    while his next choice still waits for its answer, the page keeps that one (review #1535 r1, D1)."""

    run.step(FEATURE, "ustawienia-blad-zostawia-nastepny-wybor")
    theme = "**/api/settings/theme"
    themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw")
    held: list[Route] = []
    # Harness: the saves are held, as three quick clicks at tata's can wait for their answers together.
    page.route(theme, lambda route: held.append(route))
    try:
        for click in ("Jasny", "Ciemny", "Jasny"):
            themes.get_by_role("button", name=click, exact=True).click()
        until(lambda: len(held) >= 3, "each click on Motyw saves it", page=page)
        quiet_for(page)
        run.check(len(held) == 3, f"each click on Motyw is a save that waits for its answer ({len(held)} requests, held)")
        held.pop(1).fulfill(status=500, body="")
        expect(error_toasts(page)).to_have_count(1)
        quiet_for(page)
        dark = page.evaluate("document.documentElement.classList.contains('dark')")
        pressed = themes.get_by_role("button", name="Jasny", exact=True).get_attribute("aria-pressed")
        run.check(
            (dark, pressed) == (False, "true"),
            f"the failed save of Ciemny keeps Dad's next choice Jasny, which still waits (dark={dark}, Jasny={pressed})",
        )
    finally:
        for route in held:
            route.fulfill(status=500, body="")
        page.unroute(theme)
    expect(page.locator("html")).to_have_class("dark")
    expect(error_toasts(page)).to_have_count(0, timeout=Budget.SCREEN.ms)
    close_settings(page)
    run.check(run.remembered("motyw") == "dark", "the failed saves left the theme as it was")


def _history(run: Run, page: Page) -> None:
    """Historia lists every change with before and after, a change outside Centrum too, and „Cofnij” is a new change."""

    run.step(FEATURE, "ustawienia-historia")
    settings = Path(run.fixture["settings"])
    periods = run.fixture["periods_directory"]
    attachments = run.root / "Załączniki"
    # Harness: Maks changes the folder okresów in the settings file by hand, outside Centrum.
    put_text(settings, (run.settings_text() or "").replace(periods, str(attachments)))
    window = open_settings(page, "Historia")
    rows = window.get_by_role("list", name="Zmiany").get_by_role("listitem")
    outside = rows.first
    expect(outside).to_contain_text("Folder okresów")
    expect(outside).to_contain_text("INEA → Załączniki")
    expect(outside).to_contain_text("spoza Centrum")
    run.check(True, "a change of the settings file outside Centrum is the newest row, marked „spoza Centrum”")
    expect(rows.nth(1)).to_contain_text("Ciemny")
    expect(rows.nth(1)).to_contain_text("cofnięcie")
    history = run.api("/api/settings/history", "ustawienia-historia")["rows"]
    assert isinstance(history, list)
    run.check(
        [row["source"] for row in history[:2]] == ["outside", "tata"] and history[1]["undoes"] is not None,
        "the server's Historia has the change outside Centrum, then the undo from the toast",
    )
    run.capture(page, "308-ustawienia-historia", full_page=False)

    outside.get_by_role("button", name="Cofnij: Folder okresów", exact=True).click()
    expect(rows.first).to_contain_text("Załączniki → INEA")
    expect(rows.first).to_contain_text("cofnięcie")
    until(lambda: run.remembered("folder_okresow") == periods, "„Cofnij” points the folder okresów back to INEA")
    run.check(True, "the undo is a new row on top, and the row it undid stays")

    with unreadable(settings):
        rows.first.get_by_role("button", name="Cofnij: Folder okresów", exact=True).click()
        expect(rows.first.get_by_role("alert")).to_contain_text("Nie udało się zapisać Ustawień Centrum")
    run.check(run.remembered("folder_okresow") == periods, "an undo the server refuses is one sentence under its row")
    close_settings(page)

    open_settings(page, "Historia")
    page.set_viewport_size(NARROW)
    try:
        expect(rows.first).to_contain_text("Załączniki → INEA")
        run.capture(page, "309-ustawienia-historia-waska", full_page=False)
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)


def _history_release(run: Run, page: Page) -> None:
    """A row of Historia whose change came with a Release reads „Wydanie <version>”, so Dad knows it was not him."""

    run.step(FEATURE, "ustawienia-historia-wydanie")
    answer = run.api("/api/settings/history", "ustawienia-historia-wydanie")
    rows = answer["rows"]
    assert isinstance(rows, list) and rows
    # Harness: a Release change with this Centrum's real row shape on top; pytest drives the start that writes it.
    answer["rows"] = [
        {
            **rows[0],
            "id": "harness-wydanie",
            "source": "release",
            "release": {"version": "0.9.0", "commit": "abc1234", "change": "2026-11-motyw"},
            "undoes": None,
            "file": "centrum-ustawienia.yaml",
            "section": "wyglad",
            "changes": [{"key": "wyglad.motyw", "before": "light", "after": "dark"}],
            "secret": False,
            "undoable": True,
            "refused": False,
            "removed": False,
            "reason": None,
        },
        *rows,
    ]
    print("  harness: the page gets Historia with a Release change on top (page.route)", flush=True)
    page.route("**/api/settings/history", lambda route: route.fulfill(json=answer))
    try:
        window = open_settings(page, "Historia")
        release = window.get_by_role("list", name="Zmiany").get_by_role("listitem").first
        expect(release).to_contain_text("Motyw")
        expect(release).to_contain_text("Jasny → Ciemny")
        expect(release).to_contain_text("Wydanie 0.9.0")
        expect(release.get_by_role("button", name="Cofnij: Motyw", exact=True)).to_be_visible()
        run.check(True, "a change from a Release reads „Wydanie 0.9.0” in its row of Historia, with „Cofnij”")
        run.capture(page, "340-ustawienia-historia-wydanie", full_page=False)
        close_settings(page)
    finally:
        page.unroute("**/api/settings/history")


def _refusal_at_field(run: Run, page: Page) -> None:
    """A wrong value is not saved: its one sentence stands under its field, typed or picked."""

    run.step(FEATURE, "ustawienia-odmowa-przy-polu")
    sentence = "Rejestr zleceń to plik Excel .xlsx podany pełną ścieżką. Wybierz go oknem wyboru."
    before = run.settings_text()
    for viewport, capture in ((DAD_VIEWPORT, "310-ustawienia-odmowa-przy-polu"), (NARROW, "311-ustawienia-odmowa-waska")):
        window = open_settings(page, "Foldery")
        page.set_viewport_size(viewport)
        try:
            register = window.get_by_role("listitem", name="Rejestr zleceń")
            register.get_by_role("button", name="Wpisz Rejestr zleceń", exact=True).click()
            typed = register.get_by_role("textbox", name="Ścieżka: Rejestr zleceń", exact=True)
            typed.fill("ZLECENIA.txt")
            typed.press("Enter")
            expect(register.get_by_role("alert")).to_have_text(sentence)
            expect(typed).to_have_attribute("aria-invalid", "true")
            run.check(run.settings_text() == before, f"a wrong typed path is not saved ({viewport['width']} px)")
            run.capture(page, capture, full_page=False)
            typed.press("Escape")
            expect(typed).to_have_count(0)
            expect(register.get_by_role("alert")).to_have_count(0)
            expect(window).to_be_visible()
            run.check(True, "Esc in the field goes back from the field and leaves the window open")
            close_settings(page)
        finally:
            page.set_viewport_size(DAD_VIEWPORT)

    register = open_settings(page, "Foldery").get_by_role("listitem", name="Rejestr zleceń")
    run.answer_picker(str(run.root / "ZLECENIA.txt"))
    register.get_by_role("button", name="Zmień Rejestr zleceń", exact=True).click()
    expect(register.get_by_role("alert")).to_have_text(sentence)
    run.check(run.settings_text() == before, "a wrong file from the picker is refused under its field, not saved")

    close_settings(page)


def _typed_keeps_other(run: Run, page: Page) -> None:
    """„Wpisz” saves the one path typed: the other path stays as it was, and quotes from Explorer go."""

    run.step(FEATURE, "ustawienia-wpisz-druga-bez-zmiany")
    window = open_settings(page, "Foldery")
    register_path, periods_path = run.fixture["order_register"], run.fixture["periods_directory"]
    # Dad pastes each path as Explorer copies it, in quotes; it is the path already remembered.
    for title, key, path, other, kept in (
        ("Rejestr zleceń", "rejestr_zlecen", register_path, "folder_okresow", periods_path),
        ("Folder okresów", "folder_okresow", periods_path, "rejestr_zlecen", register_path),
    ):
        row = window.get_by_role("listitem", name=title)
        row.get_by_role("button", name=f"Wpisz {title}", exact=True).click()
        row.get_by_role("textbox", name=f"Ścieżka: {title}", exact=True).fill(f'"{path}"')
        row.get_by_role("button", name=f"Zapisz {title}", exact=True).click()
        # The field closes once the server has saved.
        expect(row.get_by_role("textbox")).to_have_count(0)
        expect(row.get_by_role("alert")).to_have_count(0)
        run.check(run.remembered(key) == path, f"a {title} pasted from Explorer in quotes is saved without them")
        run.check(run.remembered(other) == kept, f"typing the {title} leaves the other path ({other}) as it was")
    close_settings(page)


def _bad_settings_file(run: Run, page: Page) -> None:
    """A wrong setting in the settings file stands as the server's one sentence: under its field, or above the list
    Foldery for the whole file; Historia shows each such content without „Cofnij”, and the good file comes back."""

    run.step(FEATURE, "ustawienia-zle-ustawienie")
    settings = Path(run.fixture["settings"])
    good = run.settings_text() or ""
    window = open_settings(page, "Foldery")
    folders = window.get_by_role("list", name="Foldery")
    register = folders.get_by_role("listitem", name="Rejestr zleceń")
    periods = folders.get_by_role("listitem", name="Folder okresów")
    # Harness: Maks writes a relative folder okresów into the settings file by hand.
    put_text(settings, good.replace(run.fixture["periods_directory"], "INEA"))
    page.reload()
    problem = run.api("/api/settings", "ustawienia-zle-pole")["folders_problem"]
    assert isinstance(problem, dict)
    run.check(problem["field"] == "folder_okresow", f"the server names the wrong field ({problem['field']})")
    expect(periods.get_by_role("alert")).to_have_text(problem["message"])
    expect(window.get_by_role("alert")).to_have_count(1)
    run.check(True, "a wrong folder okresów in the file is the server's one sentence under its field, nowhere else")
    run.capture(page, "312-ustawienia-zle-pole", full_page=False)

    # Harness: the settings file loses its end (a copy cut off), so no field is to blame.
    put_text(settings, "schema_version: [\n")
    page.reload()
    problem = run.api("/api/settings", "ustawienia-zly-plik")["folders_problem"]
    assert isinstance(problem, dict)
    run.check(problem["field"] is None, f"a damaged file names no field ({problem['field']})")
    sentence = window.get_by_role("alert")
    expect(sentence).to_have_text(problem["message"])
    expect(folders.get_by_role("alert")).to_have_count(0)
    above, below = sentence.bounding_box(), folders.bounding_box()
    assert above is not None and below is not None
    run.check(above["y"] + above["height"] <= below["y"], "the sentence about the whole file stands above the list Foldery")
    run.capture(page, "313-ustawienia-zly-plik", full_page=False)

    run.step(FEATURE, "ustawienia-historia-bez-cofniecia")
    window.get_by_role("link", name="Historia", exact=True).click()
    rows = window.get_by_role("list", name="Zmiany").get_by_role("listitem")
    history = run.api("/api/settings/history", "ustawienia-historia-bez-cofniecia")["rows"]
    assert isinstance(history, list)
    expect(rows).to_have_count(len(history))
    refused = [index for index, row in enumerate(history) if row["refused"]]
    run.check(
        refused[:2] == [0, 1] and not any(history[index]["undoable"] for index in refused),
        "the server's Historia has both wrong contents on top, neither of them undoable",
    )
    for index in refused:
        expect(rows.nth(index)).to_contain_text("Nie przyjęto")
        expect(rows.nth(index).get_by_role("button")).to_have_count(0)
    undoable = next(index for index, row in enumerate(history) if row["undoable"])
    expect(rows.nth(undoable).get_by_role("button")).to_have_text("Cofnij")
    run.check(True, "a row of Historia that cannot be undone has no „Cofnij”, while a change of Dad's has")
    run.capture(page, "314-ustawienia-historia-bez-cofniecia", full_page=False)

    put_text(settings, good)
    window.get_by_role("link", name="Foldery", exact=True).click()
    page.reload()
    expect(register.get_by_text(Path(run.fixture["order_register"]).name, exact=True)).to_be_visible()
    expect(window.get_by_role("alert")).to_have_count(0)
    run.check(run.api("/api/settings", "ustawienia-dobry-plik")["folders_problem"] is None, "the good file is back")
    close_settings(page)


def _autostart(run: Run, page: Page) -> None:
    """The switch in Narzędzie writes or removes Centrum's shortcut in the Autostart folder and shows whether it is
    there: a shortcut removed by hand is off with a row „spoza Centrum”, and a computer without Windows Autostart shows
    the switch disabled with the server's one sentence."""

    run.step(FEATURE, "ustawienia-autostart")
    shortcut = File.AUTOSTART_SHORTCUT.file(run.root)
    window = open_settings(page, "Narzędzie")
    row = window.get_by_role("listitem", name=AUTOSTART)
    switch = row.get_by_role("switch", name=AUTOSTART, exact=True)
    expect(switch).not_to_be_checked()
    switch.click()
    until(shortcut.exists, "the switch writes Centrum's shortcut in the Autostart folder")
    expect(switch).to_be_checked()
    expect(_toast(page, "Zapisano").get_by_role("button", name="Cofnij", exact=True)).to_be_visible()
    shown = run.api("/api/settings", "ustawienia-autostart-wlaczony")["autostart"]
    run.check(shown == {"state": "on", "reason": None}, f"the server says the shortcut is there ({shown})")
    run.capture(page, "330-ustawienia-autostart", full_page=False)
    page.set_viewport_size(NARROW)
    try:
        expect(switch).to_be_checked()
        run.capture(page, "331-ustawienia-autostart-waskie", full_page=False)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)

    # Harness: someone removes the shortcut from the Autostart folder by hand, outside Centrum.
    remove(shortcut)
    page.reload()
    expect(switch).not_to_be_checked()
    run.check(True, "a shortcut removed by hand is the switch off")
    window.get_by_role("link", name="Historia", exact=True).click()
    outside = window.get_by_role("list", name="Zmiany").get_by_role("listitem").first
    expect(outside).to_contain_text("Start razem z Windows")
    expect(outside).to_contain_text("Włączony → Wyłączony")
    expect(outside).to_contain_text("spoza Centrum")
    run.check(True, "the removed shortcut is the newest row of Historia, marked „spoza Centrum”")
    run.capture(page, "332-ustawienia-autostart-spoza", full_page=False)
    outside.get_by_role("button", name="Cofnij: Start razem z Windows", exact=True).click()
    until(shortcut.exists, "„Cofnij” on that row writes the shortcut back")
    window.get_by_role("link", name="Narzędzie", exact=True).click()
    expect(switch).to_be_checked()
    switch.click()
    until(lambda: not shortcut.exists(), "the switch off removes the shortcut")
    expect(switch).not_to_be_checked()

    run.step(FEATURE, "ustawienia-autostart-bez-windows")
    without_windows = Switch.NO_AUTOSTART.on(run.root)
    try:
        page.reload()
        shown = run.api("/api/settings", "ustawienia-autostart-bez-windows")["autostart"]
        assert isinstance(shown, dict)
        run.check(shown["state"] == "unsupported", f"a computer without Windows Autostart is unsupported ({shown})")
        expect(switch).to_be_disabled()
        expect(row).to_contain_text(shown["reason"])
        run.check(True, "the switch is disabled with the server's one sentence why")
        run.capture(page, "333-ustawienia-autostart-bez-windows", full_page=False)
    finally:
        remove(without_windows)
    page.reload()
    expect(switch).to_be_enabled()
    close_settings(page)


def _inbox_password(run: Run, page: Page) -> None:
    """A new password of the skrzynka raportów in a field that never shows the old one, and one login that says whether
    the skrzynka took it: rejected, accepted, no network (the served atrapa IMAP, never Dad's Gmail)."""

    run.step(FEATURE, "ustawienia-haslo-skrzynki")
    access = run.config / "skrzynka-raportow.txt"
    # An old password Google never gives (a Polish letter): Dad replaces it, the address stays Maks's.
    old = "stare hasło maksa"
    # Harness: Maks's access file as Notepad writes it (BOM UTF-8, CRLF).
    access.write_bytes(f"{INBOX_ADDRESS}\r\n{old}\r\n".encode("utf-8-sig"))
    page.reload()
    window = open_settings(page, "Skrzynka raportów")
    row = window.get_by_role("listitem", name="Hasło aplikacji")
    expect(row).to_contain_text(INBOX_ADDRESS)
    expect(row.get_by_role("alert")).to_have_text(POLISH_LETTERS)
    expect(row.get_by_role("button", name="Zmień hasło", exact=True)).to_be_enabled()
    run.check(True, "a wrong old password shows its sentence under the address and leaves „Zmień hasło” on")
    run.capture(page, "319-ustawienia-zle-stare-haslo", full_page=False)
    field = row.get_by_role("textbox", name="Nowe hasło aplikacji")

    def save(password: str) -> None:
        row.get_by_role("button", name="Zmień hasło", exact=True).click()
        expect(field).to_have_value("")
        expect(field).to_have_attribute("type", "password")
        field.fill(password)
        row.get_by_role("button", name="Zapisz hasło", exact=True).click()
        expect(field).to_be_hidden()

    save("zle haslo")
    expect(row.get_by_role("alert")).to_have_text("Skrzynka nie przyjęła hasła. Sprawdź je i wpisz jeszcze raz.")
    run.check(
        read_bytes(access) == f"{INBOX_ADDRESS}\r\nzlehaslo\r\n".encode("utf-8-sig"),
        "a password the skrzynka rejects is still saved, only its line changes and the file keeps BOM and CRLF",
    )
    save("nowe haslo taty")
    expect(row.get_by_role("status")).to_have_text("Skrzynka przyjęła hasło.")
    run.check(INBOX_PASSWORD in read_text(access), "the password the skrzynka took is in the file")
    run.capture(page, "316-ustawienia-haslo-przyjete", full_page=False)
    offline = Switch.INBOX_OFFLINE.on(run.root)
    try:
        save("nowe haslo taty")
        expect(row.get_by_role("status")).to_have_text("Hasło zapisane, ale skrzynka nie odpowiada. Sprawdź internet.")
    finally:
        remove(offline)
    run.check(True, "with no network the password is saved and the section says the skrzynka does not answer")
    settings = run.api("/api/settings", "ustawienia-skrzynka")
    history = run.api("/api/settings/history", "ustawienia-historia-skrzynki")
    answers = json.dumps([settings, history])
    run.check(
        settings["inbox"] == {"address": INBOX_ADDRESS, "password": True}
        and not [
            word for word in (old, old.replace(" ", ""), "zle haslo", "zlehaslo", INBOX_PASSWORD, "nowe haslo") if word in answers
        ],
        "neither GET /api/settings nor the Historia carries any password",
    )

    rows = open_settings(page, "Historia").get_by_role("list", name="Zmiany").get_by_role("listitem")
    expect(rows.first).to_contain_text("Hasło skrzynki raportów")
    expect(rows.first).to_contain_text("zmieniono")
    expect(rows.first.get_by_role("button")).to_have_count(0)
    run.check(True, "Historia says only that the password changed, without „Cofnij”")
    run.capture(page, "317-ustawienia-historia-hasla", full_page=False)

    open_settings(page, "Skrzynka raportów")
    page.set_viewport_size(NARROW)
    try:
        row.get_by_role("button", name="Zmień hasło", exact=True).click()
        field.fill("hasło")
        row.get_by_role("button", name="Zapisz hasło", exact=True).click()
        expect(row.get_by_role("alert")).to_have_text(POLISH_LETTERS)
        expect(field).to_have_attribute("aria-invalid", "true")
        run.check(INBOX_PASSWORD in read_text(access), "a password with Polish letters is not saved")
        run.capture(page, "318-ustawienia-haslo-waskie", full_page=False)
        field.press("Escape")
        expect(field).to_be_hidden()
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)


def _reminders(run: Run, page: Page) -> None:
    """Przypomnienia o raporcie: pory that overlap are refused at their field and nothing is saved; the preview shows the
    fixed subject and the mail with Dad's first sentence and footer before saving; „Zapisz” and the switch save with
    „Zapisano · Cofnij”, the first switch-on remembers today, and Historia names the change."""

    run.step(FEATURE, "ustawienia-przypomnienia")
    reminders = run.config / "przypomnienia.yaml"
    window = open_settings(page, "Przypomnienia")
    switch = window.get_by_role("switch", name="Przypomnienia o raporcie", exact=True)
    preview = window.get_by_role("region", name="Podgląd przypomnienia")
    expect(switch).not_to_be_checked()
    expect(preview).to_contain_text("Przypomnienie: raport za dzień")
    expect(preview).to_contain_text("Temat jest stały: po nim Centrum poznaje odpowiedzi Wykonawców.")
    expect(preview).to_contain_text("Poproszę o wysłanie raportu za dzień")
    expect(preview).to_contain_text("12345679 nie brak klienta")
    run.check(not reminders.exists(), "with no file the section shows the values of ADR 0030, switched off")

    morning_end = window.get_by_label("Pora poranna do", exact=True)
    morning_end.fill("19:00")
    window.get_by_role("button", name="Zapisz przypomnienia", exact=True).click()
    evening = window.get_by_role("listitem", name="Pora wieczorna")
    expect(evening.get_by_role("alert")).to_have_text(
        "Pory zachodzą na siebie: wieczorna może zacząć się dopiero wtedy, gdy kończy się poranna."
    )
    expect(window.get_by_label("Pora wieczorna od", exact=True)).to_have_attribute("aria-invalid", "true")
    run.check(not reminders.exists(), "pory that overlap are refused under Pora wieczorna and nothing is saved")
    run.capture(page, "360-ustawienia-przypomnienia-odmowa", full_page=False)

    morning_end.fill("12:00")
    window.get_by_label("Treść przypomnienia", exact=True).fill("Dzień dobry, czekam na raport za {dzień}.")
    window.get_by_label("Stopka przypomnienia", exact=True).fill("Pozdrawiam\nTata Testowy")
    expect(evening.get_by_role("alert")).to_have_count(0)
    expect(preview).to_contain_text("Dzień dobry, czekam na raport za ")
    expect(preview).to_contain_text("Tata Testowy")
    run.check(not reminders.exists(), "the preview shows Dad's sentence and footer before anything is saved")
    preview.scroll_into_view_if_needed()
    run.capture(page, "361-ustawienia-przypomnienia-podglad", full_page=False)

    window.get_by_role("button", name="Zapisz przypomnienia", exact=True).click()
    expect(_toast(window, "Zapisano")).to_be_visible()
    until(lambda: reminders.exists() and "'12:00'" in read_text(reminders), "the file has the new morning")
    switch.click()
    expect(switch).to_be_checked()

    def saved() -> bool:
        shown = run.api("/api/settings", "ustawienia-przypomnienia")["reminders"]
        return (
            isinstance(shown, dict)
            and shown["enabled"] is True
            and shown["since"] is not None
            and shown["morning"] == {"start": "08:00", "end": "12:00"}
            and shown["footer"] == "Pozdrawiam\nTata Testowy"
        )

    # The switch shows its state at once, before its save reaches Centrum.
    until(saved, "the switch and the form are saved: on since today, morning 08:00–12:00, Dad's footer")
    expect(window.get_by_role("listitem", name="Przypomnienia o raporcie")).to_contain_text("Idą od ")
    run.capture(page, "362-ustawienia-przypomnienia", full_page=False)

    rows = open_settings(page, "Historia").get_by_role("list", name="Zmiany").get_by_role("listitem")
    expect(rows.first).to_contain_text("Przypomnienia o raporcie")
    expect(rows.nth(1)).to_contain_text("Pora poranna")
    expect(rows.nth(1)).to_contain_text("08:00 – 17:00")
    expect(rows.nth(1)).to_contain_text("08:00 – 12:00")
    run.check(True, "Historia names the switch and the morning with before → after")

    open_settings(page, "Przypomnienia")
    page.set_viewport_size(NARROW)
    try:
        expect(switch).to_be_checked()
        run.capture(page, "363-ustawienia-przypomnienia-waskie", full_page=False)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
    # The step leaves the reminders as it found them, switched off: switched on, their work writes to config in its
    # pora, and a later feature of the same run (aktualizacja) expects config untouched by anything but itself.
    switch.click()
    expect(switch).not_to_be_checked()

    def switched_off() -> bool:
        after = run.api("/api/settings", "ustawienia-przypomnienia-wylaczone")["reminders"]
        return isinstance(after, dict) and after["enabled"] is False

    until(switched_off, "the step switches the reminders off again, so their work leaves config alone for the rest of the run")
    close_settings(page)


@contextmanager
def _without_access(run: Run, page: Page) -> Iterator[tuple[Path, Path]]:
    """Harness: Dad's Rejestr zleceń and folder okresów lie in a folder he cannot open now (OneDrive not running,
    access taken away); yields their paths and leaves the fixture's paths pointed again.

    chmod on Windows does not take away access to a folder (``NO_ACCESS_ON_WINDOWS`` in the tests), so there the page
    gets the server's answer for such a folder from ``page.route``; elsewhere the folder really has no permissions and
    ``GET /api/settings`` must report both paths ``inaccessible``.
    """

    if sys.platform == "win32":
        register = Path(run.fixture["order_register"])
        periods = Path(run.fixture["periods_directory"])
        answer = run.api("/api/settings", "ustawienia-przed-niedostepna-sciezka")
        answer["order_register"] = {"state": "inaccessible", "path": str(register), "name": register.name}
        answer["periods_directory"] = {"state": "inaccessible", "path": str(periods), "name": periods.name}
        print("  harness: the page gets the answer for a folder without access (page.route)", flush=True)
        page.route("**/api/settings", lambda route: route.fulfill(json=answer))
        try:
            yield register, periods
        finally:
            page.unroute("**/api/settings")
        return
    onedrive = run.root / "OneDrive"
    onedrive.mkdir()
    register = onedrive / Path(run.fixture["order_register"]).name
    shutil.copyfile(run.fixture["order_register"], register)
    periods = onedrive / Path(run.fixture["periods_directory"]).name
    periods.mkdir()
    print(f"  harness: a copy of the Rejestr zleceń and an empty folder okresów in {onedrive.name}", flush=True)
    _point(run, page, "Rejestr zleceń", "rejestr_zlecen", str(register))
    _point(run, page, "Folder okresów", "folder_okresow", str(periods))
    with unreadable(onedrive):
        yield register, periods
        settings = run.api("/api/settings", "ustawienia-niedostepna-sciezka")
        run.check(
            settings["order_register"] == {"state": "inaccessible", "path": str(register), "name": register.name}
            and settings["periods_directory"] == {"state": "inaccessible", "path": str(periods), "name": periods.name},
            "a Rejestr zleceń and a folder okresów in a folder without access are reported as inaccessible, not missing",
        )
    _point(run, page, "Rejestr zleceń", "rejestr_zlecen", run.fixture["order_register"])
    _point(run, page, "Folder okresów", "folder_okresow", run.fixture["periods_directory"])
    remove_tree(onedrive)


def _point(run: Run, page: Page, label: str, key: str, path: str) -> None:
    """Dad points ``path`` with „Zmień <label>” in the open section Foldery, until the settings file has it."""

    run.answer_picker(path)
    settings_window(page).get_by_role("button", name=f"Zmień {label}", exact=True).click()
    until(lambda: run.remembered(key) == path, f"the settings file remembers {Path(path).name} ({key})")
