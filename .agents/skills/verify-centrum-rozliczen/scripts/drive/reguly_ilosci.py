"""Drive features/reguly-ilosci.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import FloatRect, Locator, Page, ViewportSize, expect

from drive.common import DAD_VIEWPORT, Run, close_settings, move, open_settings, settings_window

FEATURE = "reguly-ilosci"
NARROW: ViewportSize = {"width": 420, "height": 860}
URL = "/api/settings/quantity-rules"
NEXT_PREPARATION = "Reguły działają przy następnym Przygotowaniu pliku zbiorczego. Gotowe Pliki zbiorcze się nie zmieniają."
SCOPES = ("Gdy Lista Urządzeń zna każdy składnik", "Gdy jest składnik spoza listy", "Każde zlecenie")
# Column Z in N17:AP17 of the fixture's Wzorzec pliku zbiorczego (PRICE_LIST of atrapy.scenariusz_centrum).
Z_NAME = "Montaż ONT"
NOKIA = "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nokia” w "


def _group(window: Locator, scope: str) -> Locator:
    group = window.get_by_role("region", name=scope, exact=True)
    expect(group).to_be_visible()
    return group


def _box(locator: Locator) -> FloatRect:
    box = locator.bounding_box()
    assert box is not None
    return box


def _nokia(window: Locator) -> Locator:
    return window.get_by_role("listitem").filter(has_text=NOKIA)


def drive(run: Run, page: Page) -> None:
    answer = run.api(URL, "reguly-ilosci")
    rules, devices = answer["rules"], answer["devices"]
    assert isinstance(rules, list) and isinstance(devices, list)
    template = Path(run.fixture["configuration"]["collective_template"])

    run.step(FEATURE, "reguly-zdania")
    page.goto(run.url + "#/okresy")
    window = open_settings(page, "Reguły ilości")
    expect(window.get_by_text(NEXT_PREPARATION, exact=True)).to_be_visible()
    tops = [_box(_group(window, scope))["y"] for scope in SCOPES]
    run.check(tops == sorted(tops), f"the rules stand in the three groups of their scope, in order ({tops})")
    shown = [text.strip() for scope in SCOPES for text in _group(window, scope).get_by_role("listitem").all_inner_texts()]
    run.check(
        len(shown) == len(rules) and all(text.endswith(".") for text in shown),
        f"each of the {len(rules)} rules of the server is one sentence on screen ({len(shown)})",
    )
    expect(_nokia(window)).to_contain_text(f"{NOKIA}{Z_NAME}")
    run.check(True, f"column Z shows its price-list name „{Z_NAME}” next to the letter")
    run.capture(page, "316-reguly-ilosci-szerokie")

    run.step(FEATURE, "reguly-bez-wzorca")
    aside = template.with_name(f"{template.stem} (obok){template.suffix}")
    move(template, aside)
    try:
        close_settings(page)
        window = open_settings(page, "Reguły ilości")
        expect(_nokia(window)).to_have_text(f"{NOKIA}Z.")
        run.check(True, "without a readable Wzorzec pliku zbiorczego the column is its letter alone")
        run.capture(page, "317-reguly-ilosci-bez-wzorca")
    finally:
        move(aside, template)
    close_settings(page)

    run.step(FEATURE, "urzadzenia")
    window = open_settings(page, "Urządzenia")
    items = window.get_by_role("list", name="Lista Urządzeń").get_by_role("listitem")
    expect(items).to_have_count(len(devices))
    gateway = window.get_by_role("listitem", name="gateway", exact=True)
    expect(gateway).to_contain_text("Też: zyxel")
    expect(gateway).to_contain_text("Router")
    run.check(True, f"the Lista Urządzeń shows its {len(devices)} components with other spellings and group")
    run.capture(page, "318-urzadzenia-szerokie")
    close_settings(page)

    run.step(FEATURE, "waskie-okno")
    page.set_viewport_size(NARROW)
    try:
        # On a narrow window the menu with the gear is folded away; the address opens the section, as a bookmark does.
        page.goto(run.url + "#/ustawienia/reguly-ilosci")
        window = settings_window(page)
        expect(window.get_by_role("heading")).to_have_text("Ustawienia/Reguły ilości")
        on_screen = sum(_group(window, scope).get_by_role("listitem").count() for scope in SCOPES)
        run.check(on_screen == len(rules), f"the narrow window shows every rule ({on_screen})")
        page.wait_for_function(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        run.check(True, "on a narrow window the sentences wrap without a horizontal scroll")
        run.capture(page, "319-reguly-ilosci-waskie", full_page=False)
        window = open_settings(page, "Urządzenia")
        expect(window.get_by_role("list", name="Lista Urządzeń").get_by_role("listitem")).to_have_count(len(devices))
        run.capture(page, "320-urzadzenia-waskie", full_page=False)
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
