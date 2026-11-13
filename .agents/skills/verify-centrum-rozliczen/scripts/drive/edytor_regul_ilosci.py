"""Drive features/edytor-regul-ilosci.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.request

from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import DAD_VIEWPORT, Run, close_settings, open_settings, read_text, settings_title, settings_window

FEATURE = "edytor-regul-ilosci"
NARROW: ViewportSize = {"width": 420, "height": 860}
URL = "/api/settings/quantity-rules"
# Column V in N17:AP17 of the fixture's Wzorzec pliku zbiorczego (PRICE_LIST of atrapy.scenariusz_centrum).
V_NAME = "Dojazd do klienta"
# Dad's new rule: every order gets 2 in V; with the rule of the Release „Wpisz 1 w V.” for an order with a component
# outside the list, such an order has V = 3 from two rules.
RULE = {
    "scope": "every",
    "conditions": [],
    "action": {"kind": "fill", "writes": [{"column": "V", "value": 2, "multiplier": "once", "component": None}]},
}
SENTENCE = f"Wpisz 2 w {V_NAME} V."
RELEASE_V = f"Wpisz 1 w {V_NAME} V."


def _preview(run: Run, edit: dict[str, object]) -> dict[str, Any]:
    """The server's preview of ``edit``; the evidence keeps it without the texts of the rows (workbook content)."""

    request = urllib.request.Request(
        run.url.rstrip("/") + URL + "/preview",
        data=json.dumps(edit).encode(),
        method="POST",
        headers={"Origin": run.url.rstrip("/"), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        answer: dict[str, Any] = json.load(response)
    shown = {**answer, "rows": [{**row, "devices": "<tekst wiersza>", "activities": "<tekst wiersza>"} for row in answer.get("rows", [])]}
    (run.evidence / "api" / "edytor-podglad.json").write_text(json.dumps(shown, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return answer


def _capture(run: Run, page: Page, name: str, answer: dict[str, Any], *, full_page: bool = True) -> None:
    """Screenshot with the preview; its ARIA snapshot keeps the row texts out, like the saved answer."""

    run.capture(page, name, full_page=full_page)
    snapshot = run.evidence / "aria" / f"{name}.txt"
    text = read_text(snapshot)
    for row in answer.get("rows", []):
        for value in (row["devices"], row["activities"]):
            if value:
                text = text.replace(value, "<tekst wiersza>")
    snapshot.write_text(text, encoding="utf-8")


def _choose(page: Page, scope: Locator, combobox: str, option: str) -> None:
    scope.get_by_role("combobox", name=combobox, exact=True).click()
    page.get_by_role("option", name=option, exact=True).click()


def _rules(run: Run, name: str) -> list[dict[str, Any]]:
    rules = run.api(URL, name)["rules"]
    assert isinstance(rules, list)
    return rules


def drive(run: Run, page: Page) -> None:
    before = _rules(run, "edytor-reguly-przed")
    rules_file = Path(run.config) / "reguly-ilosci.yaml"

    run.step(FEATURE, "edytor-nowa-regula")
    page.goto(run.url + "#/okresy")
    window = open_settings(page, "Reguły ilości")
    window.get_by_role("button", name="Dodaj regułę", exact=True).click()
    expect(window.get_by_role("heading", name="Nowa reguła", exact=True)).to_be_visible()
    preview = window.get_by_role("list", name="Podgląd")
    expect(preview).to_contain_text("Wybierz, co reguła ma zrobić")
    run.check(True, "a new rule starts without an action, and the preview says to choose one")
    _choose(page, window, "Zakres reguły", "Każde zlecenie")
    _choose(page, window, "Działanie", "Wpisz w kolumnę")
    _choose(page, window, "Kolumna", f"{V_NAME} (V)")
    value = window.get_by_role("spinbutton", name="Wartość", exact=True)
    value.fill("2")
    expect(preview.get_by_role("listitem", name="Reguła", exact=True)).to_have_text(SENTENCE)
    answer = _preview(run, {"kind": "add", "rule": RULE})
    run.check(
        answer["state"] == "ready" and answer["changed"] > 0 and len(answer["rows"]) > 0,
        f"the server's preview changes {answer.get('changed')} rows of the last settled Pliki zbiorcze",
    )
    expect(preview.get_by_role("listitem", name="Skutek", exact=True)).to_contain_text(
        f"Zmieni się {answer['changed']} "
    )
    expect(preview.get_by_role("listitem", name="Skutek", exact=True)).to_contain_text(
        f"różnice z Kontroli ilości: {answer['differences_before']} → {answer['differences_after']}"
    )
    expect(preview.get_by_role("listitem", name=f"Wiersz {answer['rows'][0]['row']}", exact=True)).to_be_visible()
    run.check(True, "the preview shows the server's count of changed rows, the Kontrola differences and the rows")
    summed = preview.get_by_role("listitem", name=f"Wiersz {answer['rows'][0]['row']}", exact=True)
    expect(summed).to_contain_text(f"{V_NAME} (V) = 3, bo reguły:")
    expect(summed).to_contain_text(RELEASE_V)
    expect(summed).to_contain_text(SENTENCE)
    run.check(True, "two rules into V show their sum with both rules („V = 3, bo reguły …”)")
    summed.scroll_into_view_if_needed()
    _capture(run, page, "380-edytor-podglad-szerokie", answer, full_page=False)

    run.step(FEATURE, "edytor-zla-regula")
    value.fill("")
    window.get_by_role("button", name="Zapisz", exact=True).click()
    column = window.get_by_role("listitem", name="Kolumna 1", exact=True)
    expect(column.get_by_role("alert")).to_have_text("Wartość musi być liczbą całkowitą od 1 do 999.")
    run.check(not rules_file.exists(), "a rule the server refuses is one sentence at its field, and nothing is saved")
    _capture(run, page, "381-edytor-zla-wartosc", answer, full_page=False)
    value.fill("2")

    run.step(FEATURE, "edytor-niezapisany")
    page.keyboard.press("Escape")
    leaving = page.get_by_role("alertdialog")
    expect(leaving).to_contain_text("Zamknąć bez zapisu?")
    _capture(run, page, "382-edytor-zamkniecie-bez-zapisu", answer, full_page=False)
    leaving.get_by_role("button", name="Wróć", exact=True).click()
    expect(window.get_by_role("heading", name="Nowa reguła", exact=True)).to_be_visible()
    run.check(True, "closing the window with an unsaved rule asks first, and „Wróć” keeps the form")

    run.step(FEATURE, "edytor-zapis")
    window.get_by_role("button", name="Zapisz", exact=True).click()
    group = window.get_by_role("region", name="Każde zlecenie", exact=True)
    expect(group.get_by_role("listitem").filter(has_text=SENTENCE)).to_have_count(1)
    after = _rules(run, "edytor-reguly-po-zapisie")
    run.check(
        [rule["id"] for rule in after] == [*(rule["id"] for rule in before), "regula-1"] and rules_file.exists(),
        "„Zapisz” adds the rule at the end of the server's rules and writes the file of Reguły ilości",
    )
    run.capture(page, "383-edytor-zapisana")

    run.step(FEATURE, "edytor-historia")
    window = open_settings(page, "Historia")
    newest = window.get_by_role("list", name="Zmiany").get_by_role("listitem").first
    expect(newest).to_contain_text("Reguła ilości")
    expect(newest).to_contain_text(f"Dodano: {SENTENCE}")
    run.check(True, "Historia reads the change of a rule as its sentence, not the file's text")
    run.capture(page, "384-edytor-historia", full_page=False)
    newest.get_by_role("button", name="Cofnij: Reguła ilości", exact=True).click()
    expect(window.get_by_role("list", name="Zmiany").get_by_role("listitem").first).to_contain_text(f"Usunięto: {SENTENCE}")
    run.check(
        [rule["id"] for rule in _rules(run, "edytor-reguly-po-cofnieciu")] == [rule["id"] for rule in before],
        "„Cofnij” in Historia brings the earlier rules back",
    )
    close_settings(page)

    run.step(FEATURE, "edytor-waskie-okno")
    page.set_viewport_size(NARROW)
    try:
        page.goto(run.url + "#/ustawienia/reguly-ilosci")
        window = settings_window(page)
        expect(settings_title(page)).to_have_text("Ustawienia/Reguły ilości")
        window.get_by_role("listitem").filter(has_text=RELEASE_V).get_by_role("button", name="Zmień regułę").click()
        expect(window.get_by_role("heading", name="Zmiana reguły", exact=True)).to_be_visible()
        shown = window.get_by_role("list", name="Podgląd")
        expect(shown.get_by_role("listitem", name="Reguła", exact=True)).to_have_text(RELEASE_V)
        expect(shown.get_by_role("listitem", name="Skutek", exact=True)).to_contain_text("Żaden wiersz się nie zmieni.")
        run.check(True, "a rule opened without a change has its sentence and changes no row")
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the editor and its preview wrap without a horizontal scroll")
        run.capture(page, "385-edytor-waskie", full_page=False)
        window.get_by_role("button", name="Anuluj", exact=True).click()
        expect(window.get_by_role("button", name="Dodaj regułę", exact=True)).to_be_visible()
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
