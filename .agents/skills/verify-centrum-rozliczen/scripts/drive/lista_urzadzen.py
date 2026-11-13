"""Drive features/lista-urzadzen.md."""

from __future__ import annotations

import json
import re
from typing import Any
import urllib.request

from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import DAD_VIEWPORT, Run, close_settings, open_settings, read_text, settings_title, settings_window

FEATURE = "lista-urzadzen"
NARROW: ViewportSize = {"width": 420, "height": 860}
RULES_URL = "/api/settings/quantity-rules"
SUGGESTIONS_URL = "/api/settings/devices/suggestions"
# The row marker of the fixture's URZĄDZENIA (atrapy.scenariusz_centrum.ROW_MARKER) as the engine reads it: lowercase.
MARKER = re.compile(r"centrum-syn-row\S*", re.IGNORECASE)
MASK = "<znacznik wiersza>"
TAKEN = "Zapis „zyxel” ma już składnik „gateway”. Jeden zapis należy do jednego składnika."
NEEDED = "Składnika „technicolor” potrzebuje reguła: Jeśli URZĄDZENIA zawierają „technicolor”"


def _masked(text: str) -> str:
    return MARKER.sub(MASK, text)


def _suggestions(run: Run, name: str) -> list[dict[str, Any]]:
    """The server's suggestions; the evidence keeps them with the row markers masked (workbook content)."""

    with urllib.request.urlopen(run.url.rstrip("/") + SUGGESTIONS_URL, timeout=30) as response:
        answer: dict[str, Any] = json.load(response)
    shown = json.dumps(answer, ensure_ascii=False, indent=2)
    (run.evidence / "api" / f"{name}.json").write_text(_masked(shown) + "\n", encoding="utf-8")
    suggestions = answer["suggestions"]
    assert isinstance(suggestions, list)
    return suggestions


def _devices(run: Run, name: str) -> list[dict[str, Any]]:
    devices = run.api(RULES_URL, name)["devices"]
    assert isinstance(devices, list)
    return devices


def _capture(run: Run, page: Page, name: str) -> None:
    """Screenshot of the window as Dad sees it; its ARIA snapshot keeps the row markers out, like the saved suggestions."""

    run.capture(page, name, full_page=False)
    snapshot = run.evidence / "aria" / f"{name}.txt"
    snapshot.write_text(_masked(read_text(snapshot)), encoding="utf-8")


def _edit(window: Locator, name: str) -> Locator:
    """Dad's pencil at the component ``name``; the form stands in place of its row."""

    window.get_by_role("button", name=f"Zmień {name}", exact=True).click()
    form = window.get_by_role("listitem", name=f"Zmiana {name}", exact=True)
    expect(form).to_be_visible()
    return form


def drive(run: Run, page: Page) -> None:
    before = _devices(run, "urzadzenia-przed")
    suggested = _suggestions(run, "urzadzenia-podpowiedzi-przed")

    run.step(FEATURE, "lista-urzadzen-podpowiedzi")
    page.goto(run.url + "#/okresy")
    window = open_settings(page, "Urządzenia")
    region = window.get_by_role("region", name="Z ostatnich okresów", exact=True)
    expect(region.get_by_role("listitem")).to_have_count(len(suggested))
    run.check(
        len(suggested) == 2 and all(item["orders"] == 1 for item in suggested),
        "the two Wiersze danych with a component outside the list are two suggestions, the one from the description none",
    )
    region.scroll_into_view_if_needed()
    _capture(run, page, "370-urzadzenia-podpowiedzi")

    run.step(FEATURE, "lista-urzadzen-inny-zapis")
    form = _edit(window, "gateway")
    form.get_by_role("button", name="Dodaj zapis", exact=True).click()
    form.get_by_role("textbox", name="Inny zapis 2", exact=True).fill("Nowy Router")
    form.get_by_role("button", name="Zapisz", exact=True).click()
    expect(window.get_by_role("listitem", name="gateway", exact=True)).to_contain_text("Też: zyxel, nowy router")
    gateway = next(device for device in _devices(run, "urzadzenia-po-zapisie") if device["id"] == "gateway")
    run.check(gateway["other_spellings"] == ["zyxel", "nowy router"], "„Zapisz” adds the other spelling as the engine reads it")
    _capture(run, page, "371-urzadzenia-inny-zapis")

    run.step(FEATURE, "lista-urzadzen-odmowa")
    form = _edit(window, "nokia")
    form.get_by_role("button", name="Dodaj zapis", exact=True).click()
    form.get_by_role("textbox", name="Inny zapis 1", exact=True).fill("zyxel")
    form.get_by_role("button", name="Zapisz", exact=True).click()
    expect(form.get_by_role("alert")).to_have_text(TAKEN)
    run.check(True, "a spelling of another component is one sentence at its field, naming that component")
    _capture(run, page, "372-urzadzenia-zapis-innego-skladnika")
    form.get_by_role("button", name="Anuluj", exact=True).click()
    form = _edit(window, "technicolor")
    form.get_by_role("button", name="Usuń składnik", exact=True).click()
    expect(form.get_by_role("alert")).to_contain_text(NEEDED)
    run.check(
        [device["id"] for device in _devices(run, "urzadzenia-po-odmowie")] == [device["id"] for device in before],
        "removing a component a rule needs is refused with that rule's sentence, and the list stays",
    )
    _capture(run, page, "373-urzadzenia-skladnik-potrzebny-regule")
    form.get_by_role("button", name="Anuluj", exact=True).click()

    run.step(FEATURE, "lista-urzadzen-dodaj-podpowiedz")
    first = region.get_by_role("listitem").first
    first.get_by_role("button", name="Dodaj", exact=True).click()
    added = window.get_by_role("listitem", name="Nowy składnik", exact=True)
    expect(added.get_by_role("combobox", name="Dodaj jako", exact=True)).to_contain_text("Nowy składnik")
    added.get_by_role("button", name="Zapisz", exact=True).click()
    expect(region.get_by_role("listitem")).to_have_count(1)
    after = _suggestions(run, "urzadzenia-podpowiedzi-po")
    run.check(
        len(after) == 1 and len(_devices(run, "urzadzenia-po-podpowiedzi")) == len(before) + 1,
        "„Dodaj” and „Zapisz” add the suggestion as a new component, and it leaves the suggestions",
    )
    region.scroll_into_view_if_needed()
    _capture(run, page, "374-urzadzenia-po-podpowiedzi")

    run.step(FEATURE, "lista-urzadzen-historia")
    window = open_settings(page, "Historia")
    changes = window.get_by_role("list", name="Zmiany")
    expect(changes.get_by_role("listitem").first).to_contain_text("Lista Urządzeń")
    expect(changes.get_by_role("listitem").first).to_contain_text("Dodano: Składnik „")
    expect(changes.get_by_role("listitem").nth(1)).to_contain_text("Po: Składnik „gateway”, też „zyxel”, „nowy router”, grupa router.")
    run.check(True, "Historia reads each change of the list as the component's sentence before and after")
    _capture(run, page, "375-urzadzenia-historia")
    # Both changes undone: the features after this one find the Lista Urządzeń of the Release.
    for row in (0, 2):
        changes.get_by_role("listitem").nth(row).get_by_role("button", name="Cofnij: Lista Urządzeń", exact=True).click()
        expect(changes.get_by_role("listitem").first).to_contain_text("Usunięto:" if row == 0 else "Przed:")
    run.check(
        _devices(run, "urzadzenia-po-cofnieciu") == before,
        "„Cofnij” of both changes in Historia brings the Lista Urządzeń of the Release back",
    )
    close_settings(page)

    run.step(FEATURE, "lista-urzadzen-waskie-okno")
    page.set_viewport_size(NARROW)
    try:
        page.goto(run.url + "#/ustawienia/urzadzenia")
        window = settings_window(page)
        expect(settings_title(page)).to_have_text("Ustawienia/Urządzenia")
        _edit(window, "gateway")
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the form of a component wraps without a horizontal scroll")
        _capture(run, page, "376-urzadzenia-waskie")
        window.get_by_role("button", name="Anuluj", exact=True).click()
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
