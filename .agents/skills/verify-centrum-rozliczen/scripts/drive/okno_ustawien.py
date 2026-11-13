"""Drive features/okno-ustawien.md."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Page, Request, ViewportSize, expect

from drive.common import DAD_VIEWPORT, Run, close_settings, settings_title, settings_window

FEATURE = "okno-ustawien"
# The groups of sections in the order of ADR 0032 that have a section now; Ilości has none yet.
SHOWN_GROUPS = ("Praca", "Pliki", "Połączenia", "Narzędzie", "Historia")
HIDDEN_GROUPS = ("Ilości",)
SECTIONS = (
    "Foldery",
    "Wykonawcy",
    "Przypomnienia",
    "Wzorce",
    "Kopie INTERMAX",
    "Skrzynka raportów",
    "Zgłoszenia",
    "Narzędzie",
    "Wygląd",
    "Historia",
)
FOLDERS = "#/ustawienia/foldery"
# Dad's narrow browser window, where the window Ustawienia fills the screen.
NARROW: ViewportSize = {"width": 420, "height": 860}


def _hash(page: Page) -> str:
    return "#" + urlsplit(page.url).fragment


def _page_under(page: Page, page_id: str) -> None:
    """The page ``page_id`` is still under the window: its heading stays in the document (the window makes it inert)."""

    expect(page.locator(f'h1[data-page="{page_id}"]')).to_have_count(1)


def drive(run: Run, page: Page) -> None:
    window = settings_window(page)
    title = settings_title(page)
    gear = page.get_by_role("link", name="Ustawienia", exact=True)

    run.step(FEATURE, "okno-stopka-menu")
    page.goto(run.url + "#/okresy")
    expect(page.get_by_role("heading", name="Okresy", level=1)).to_be_visible()
    close_centrum = page.get_by_role("button", name="Zamknij Centrum rozliczeń", exact=True)
    gear_box, close_box = gear.bounding_box(), close_centrum.bounding_box()
    run.check(
        gear_box is not None and close_box is not None and gear_box["y"] + gear_box["height"] <= close_box["y"],
        "the gear Ustawienia stands in the menu's footer right above „Zamknij Centrum rozliczeń”",
    )
    expect(page.get_by_role("link", name="Konfiguracja", exact=True)).to_have_count(0)
    run.check(True, "the menu has no Konfiguracja")
    run.capture(page, "300-okno-stopka-menu", full_page=False)

    run.step(FEATURE, "okno-nad-strona")
    page.get_by_role("link", name="Metryki", exact=True).click()
    expect(page.get_by_role("heading", name="Metryki", level=1)).to_be_visible()
    metrics_reads: list[str] = []

    def count_metrics(request: Request) -> None:
        if urlsplit(request.url).path == "/api/metrics":
            metrics_reads.append(request.method)

    page.on("request", count_metrics)
    try:
        gear.click()
        expect(window).to_be_visible()
        expect(title).to_have_text("Ustawienia/Foldery")
        run.check(_hash(page) == "#/ustawienia", f"the gear opens the window at #/ustawienia ({_hash(page)})")
        _page_under(page, "metryki")
        nav = window.get_by_role("list")
        labels = [label.strip() for label in window.locator("[data-slot=sidebar-group-label]").all_inner_texts()]
        run.check(labels == list(SHOWN_GROUPS), f"the groups with a section show in the order of ADR 0032 ({labels})")
        for group in HIDDEN_GROUPS:
            expect(window.get_by_text(group, exact=True)).to_have_count(0)
        run.check(True, "Ilości has no section yet, so it does not show")
        links = [link.strip() for link in nav.get_by_role("link").all_inner_texts()]
        run.check(links == list(SECTIONS), f"the sections stand in their groups ({links})")
        run.capture(page, "301-okno-szerokie", full_page=False)

        run.step(FEATURE, "okno-zamykanie")
        closes: tuple[tuple[str, Callable[[], None]], ...] = (
            ("Esc", lambda: page.keyboard.press("Escape")),
            ("✕", lambda: window.get_by_role("button", name="Zamknij Ustawienia", exact=True).click()),
            # Outside the window, on the blurred Centrum: its left edge is at 15 % of Dad's screen.
            ("a click on the backdrop", lambda: page.mouse.click(40, DAD_VIEWPORT["height"] // 2)),
        )
        for how, close in closes:
            if not window.is_visible():
                gear.click()
                expect(title).to_have_text("Ustawienia/Foldery")
            close()
            expect(window).to_have_count(0)
            expect(page.get_by_role("heading", name="Metryki", level=1)).to_be_visible()
            run.check(_hash(page) == "#/metryki", f"{how} closes the window back to Metryki ({_hash(page)})")
    finally:
        page.remove_listener("request", count_metrics)
    run.check(metrics_reads == [], f"opening and closing the window leaves Metryki as it was ({len(metrics_reads)} reads)")
    page.go_back()
    expect(page.get_by_role("heading", name="Okresy", level=1)).to_be_visible()
    run.check(_hash(page) == "#/okresy", f"after the window is closed, Back goes to Okresy, before Metryki ({_hash(page)})")

    run.step(FEATURE, "okno-adres-sekcji")
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    expect(page.get_by_role("heading", name="Uruchomienia", level=1)).to_be_visible()
    page.evaluate("location.hash = '#/ustawienia/wzorce'")
    expect(title).to_have_text("Ustawienia/Wzorce")
    expect(window.get_by_role("link", name="Wzorce", exact=True)).to_have_attribute("aria-current", "page")
    _page_under(page, "uruchomienia")
    run.check(True, "#/ustawienia/wzorce opens the window on Wzorce over Uruchomienia")
    window.get_by_role("link", name="Narzędzie", exact=True).click()
    expect(title).to_have_text("Ustawienia/Narzędzie")
    run.check(_hash(page) == "#/ustawienia/narzedzie", f"another section changes the address ({_hash(page)})")
    page.go_back()
    expect(window).to_have_count(0)
    expect(page.get_by_role("heading", name="Uruchomienia", level=1)).to_be_visible()
    run.check(True, "Back in the browser closes the window instead of going through its sections")
    # A new tab: `goto` to another fragment of the same page would only change the address, so the drive reloads.
    page.goto(run.url + "#/ustawienia/kopie-intermax")
    page.reload()
    expect(title).to_have_text("Ustawienia/Kopie INTERMAX")
    _page_under(page, "okresy")
    run.check(True, "a new tab on #/ustawienia/kopie-intermax opens that section over the start page Okresy")
    close_settings(page)
    expect(page.get_by_role("heading", name="Okresy", level=1)).to_be_visible()
    page.goto(run.url + "#/ustawienia/nie-ma-takiej")
    expect(title).to_have_text("Ustawienia/Foldery")
    run.check(True, "an unknown section opens the first one, Foldery")
    close_settings(page)

    run.step(FEATURE, "okno-stara-konfiguracja")
    for how in ("a bookmark of", "a link to"):
        page.goto(run.url + "#/konfiguracja")
        if how == "a bookmark of":
            page.reload()
        expect(title).to_have_text("Ustawienia/Foldery")
        run.check(_hash(page) == "#/ustawienia", f"{how} the old address of Konfiguracja opens Ustawienia ({_hash(page)})")
        close_settings(page)

    run.step(FEATURE, "okno-foldery")
    page.get_by_role("link", name="Ustaw w Ustawieniach", exact=True).click()
    expect(title).to_have_text("Ustawienia/Foldery")
    run.check(_hash(page) == FOLDERS, f"„Ustaw w Ustawieniach” on Okresy opens Foldery ({_hash(page)})")
    for label in ("Rejestr zleceń", "Folder okresów"):
        row = window.get_by_role("listitem", name=label)
        expect(row).to_contain_text("Nie wskazano")
        expect(row.get_by_role("button", name=f"Wskaż {label}", exact=True)).to_be_enabled()
    run.capture(page, "302-okno-foldery", full_page=False)
    close_settings(page)

    run.step(FEATURE, "okno-linki-do-folderow")
    for page_id, title_text, groups in (
        ("okresy", "Okresy", ()),
        ("uruchomienia", "Uruchomienia", ("Rejestr zleceń", "Folder okresów", "INTERMAX")),
        ("raporty", "Raporty", ("INTERMAX",)),
    ):
        page.get_by_role("link", name=title_text, exact=True).click()
        expect(page.get_by_role("heading", name=title_text, level=1)).to_be_visible()
        for label in groups:
            link = page.get_by_role("group", name=label).first.get_by_role("link", name="Ustaw w Ustawieniach", exact=True)
            expect(link).to_have_attribute("href", FOLDERS)
        expect(page.get_by_role("main").get_by_role("button", name=re.compile(r"^(Wskaż|Zmień) "))).to_have_count(0)
        run.check(True, f"{title_text} chooses no file, an unset one links to Foldery ({', '.join(groups) or 'empty state'})")
        if page_id == "raporty":
            page.get_by_role("group", name="INTERMAX").get_by_role("link", name="Ustaw w Ustawieniach").click()
            expect(title).to_have_text("Ustawienia/Foldery")
            _page_under(page, "raporty")
            run.capture(page, "303-okno-z-raportow", full_page=False)
            close_settings(page)
            expect(page.get_by_role("heading", name="Raporty", level=1)).to_be_visible()
    register = Path(run.fixture["order_register"])
    answer = run.api("/api/settings", "okno-ustawien-przed-wskazanym-plikiem")
    answer["order_register"] = {"state": "ready", "path": str(register), "name": register.name}
    page.route("**/api/settings", lambda route: route.fulfill(json=answer))
    try:
        page.reload()
        intermax = page.get_by_role("group", name="INTERMAX")
        expect(intermax).to_contain_text(register.name)
        expect(intermax.get_by_role("link", name="Ustaw w Ustawieniach")).to_have_count(0)
        run.check(True, "a chosen INTERMAX on Raporty shows its name without „Ustaw w Ustawieniach”")
        for state, shown in (("missing", "Nie ma już"), ("inaccessible", "Nie da się teraz odczytać")):
            answer["order_register"] = {"state": state, "path": str(register), "name": register.name}
            page.reload()
            expect(intermax).to_contain_text(f"{shown}: {register.name}")
            expect(intermax.get_by_role("link", name="Ustaw w Ustawieniach", exact=True)).to_have_attribute("href", FOLDERS)
            run.check(True, f"a chosen INTERMAX in state {state} on Raporty links to Foldery")
    finally:
        page.unroute("**/api/settings")
    page.reload()
    expect(page.get_by_role("group", name="INTERMAX").get_by_role("link", name="Ustaw w Ustawieniach")).to_be_visible()

    run.step(FEATURE, "okno-waskie")
    page.set_viewport_size(NARROW)
    try:
        page.goto(run.url + FOLDERS)
        expect(title).to_have_text("Ustawienia/Foldery")
        # The window grows from 95 % as it opens, so its size is measured once the entrance has finished.
        page.wait_for_function("document.getAnimations().every((animation) => animation.playState !== 'running')")
        box = window.bounding_box()
        run.check(
            box is not None and box["x"] == 0 and box["y"] == 0 and box["width"] == NARROW["width"]
            and box["height"] == NARROW["height"],
            f"on a narrow window Ustawienia fill the screen ({box})",
        )
        expect(window.get_by_role("link", name="Wzorce", exact=True)).to_be_hidden()
        sections = window.get_by_role("combobox", name="Sekcja Ustawień")
        expect(sections).to_contain_text("Foldery")
        run.capture(page, "304-okno-waskie", full_page=False)
        sections.click()
        for group in SHOWN_GROUPS:
            expect(page.get_by_role("listbox").get_by_role("group", name=group, exact=True)).to_be_visible()
        run.capture(page, "305-okno-waskie-wybor", full_page=False)
        page.get_by_role("option", name="Wzorce", exact=True).click()
        expect(title).to_have_text("Ustawienia/Wzorce")
        run.check(_hash(page) == "#/ustawienia/wzorce", f"the combobox goes to the section ({_hash(page)})")
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
