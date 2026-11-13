"""Drive features/roznice-z-kontroli.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import (
    DAD_VIEWPORT,
    QUANTITY_DIFFERENCES as URL,
    Run,
    capture_quantity_rules,
    close_settings,
    open_settings,
    read_text,
    settings_title,
    settings_window,
    without_row_texts,
)

FEATURE = "roznice-z-kontroli"
NARROW: ViewportSize = {"width": 420, "height": 860}
RULES_URL = "/api/settings/quantity-rules"
TITLE = "Tu wpisałeś inaczej niż reguła"


def _differences(run: Run, name: str) -> dict[str, Any]:
    """The server's list; the evidence keeps it without the texts of the rows (workbook content)."""

    answer: dict[str, Any] = run.api(URL, name)
    texts = [difference[key] for difference in answer.get("differences", []) for key in ("devices", "activities")]
    shown = without_row_texts(json.dumps(answer, ensure_ascii=False, indent=2), texts)
    (run.evidence / "api" / f"{name}.json").write_text(shown + "\n", encoding="utf-8")
    return answer


def _item(window: Locator, difference: dict[str, Any]) -> Locator:
    column = difference["column"] if difference["name"] is None else f"{difference['name']} ({difference['column']})"
    return window.get_by_role("region", name=TITLE, exact=True).get_by_role(
        "listitem", name=f"{column}, wiersz {difference['row']}", exact=True
    )


def _ids(run: Run, name: str) -> list[str]:
    return [difference["id"] for difference in _differences(run, name).get("differences", [])]


def drive(run: Run, page: Page) -> None:
    rules_file = Path(run.config) / "reguly-ilosci.yaml"
    exceptions_file = Path(run.config) / "wyjatki-ilosci.yaml"
    rules_before = run.api(RULES_URL, "roznice-reguly-przed")["rules"]
    rules_file_before = read_text(rules_file) if rules_file.exists() else None

    run.step(FEATURE, "roznice-lista")
    page.goto(run.url + "#/okresy")
    answer = _differences(run, "roznice-lista")
    run.check(
        answer["state"] == "ready" and len(answer["differences"]) > 0,
        f"the server lists {len(answer.get('differences', []))} differences of the Kontrola ilości of the settled period",
    )
    window = open_settings(page, "Reguły ilości")
    first = answer["differences"][0]
    item = _item(window, first)
    expect(item).to_contain_text(f"reguła {first['rule']} · wpisałeś {first['tata']}")
    expect(item).to_contain_text(f"{first['period']} · wiersz {first['row']} · {first['when']}")
    run.check(True, "the first difference shows the server's column, rule value, Dad's entry and row, without UMOWA")
    capture_quantity_rules(run, page, "400-roznice-lista-szerokie", full_page=False)

    run.step(FEATURE, "roznice-popraw-regule")
    item.get_by_role("button", name="Popraw regułę", exact=True).click()
    expect(window.get_by_role("heading", name="Nowa reguła", exact=True)).to_be_visible()
    conditions = window.get_by_role("list", name="Warunki")
    expect(conditions.get_by_role("listitem", name="Warunek 1", exact=True)).to_be_visible()
    expect(conditions.get_by_role("listitem", name=f"Warunek {len(first['draft']['conditions']) + 1}", exact=True)).to_have_count(0)
    run.check(True, "„Popraw regułę” opens a new rule with the conditions of the server's form for this difference")
    expect(window.get_by_role("button", name="Zapisz", exact=True)).to_be_enabled()
    run.check(True, "the form from a difference is unsaved from the start, so „Zapisz” takes it as it is")
    capture_quantity_rules(run, page, "401-roznice-popraw-regule", full_page=False)
    window.get_by_role("button", name="Anuluj", exact=True).click()
    expect(window.get_by_role("region", name=TITLE, exact=True)).to_be_visible()
    run.check(
        run.api(RULES_URL, "roznice-reguly-po-anuluj")["rules"] == rules_before
        and (read_text(rules_file) if rules_file.exists() else None) == rules_file_before,
        "the rule from a difference is not saved until Dad presses „Zapisz”",
    )

    run.step(FEATURE, "roznice-wyjatek")
    _item(window, first).get_by_role("button", name="To był wyjątek", exact=True).click()
    expect(_item(window, first)).to_have_count(0)
    run.check(first["id"] not in _ids(run, "roznice-po-wyjatku"), "„To był wyjątek” hides the difference on the server")
    run.check(
        exceptions_file.exists() and first["id"] in read_text(exceptions_file),
        "the exception is a setting in config/wyjatki-ilosci.yaml",
    )
    saved = window.locator("[data-slot=toast]:not([data-ending-style])").filter(has=page.get_by_text("Zapisano", exact=True))
    expect(saved.get_by_role("button", name="Cofnij", exact=True)).to_be_visible()
    run.check(True, "the exception says „Zapisano” with „Cofnij” like every change of Ustawienia")
    capture_quantity_rules(run, page, "402-roznice-wyjatek", full_page=False)

    run.step(FEATURE, "roznice-historia")
    window = open_settings(page, "Historia")
    newest = window.get_by_role("list", name="Zmiany").get_by_role("listitem").first
    expect(newest).to_contain_text("Wyjątek Kontroli ilości")
    expect(newest).to_contain_text(f"Dodano: To był wyjątek: okres {first['period']}, wiersz {first['row']}")
    run.check(True, "Historia reads the exception as a sentence with the period, the row and the column")
    run.capture(page, "403-roznice-historia", full_page=False)
    newest.get_by_role("button", name="Cofnij: Wyjątek Kontroli ilości", exact=True).click()
    expect(window.get_by_role("list", name="Zmiany").get_by_role("listitem").first).to_contain_text("Usunięto: To był wyjątek")
    run.check(first["id"] in _ids(run, "roznice-po-cofnieciu"), "„Cofnij” in Historia brings the difference back")
    close_settings(page)

    run.step(FEATURE, "roznice-waskie-okno")
    page.set_viewport_size(NARROW)
    try:
        page.goto(run.url + "#/ustawienia/reguly-ilosci")
        window = settings_window(page)
        expect(settings_title(page)).to_have_text("Ustawienia/Reguły ilości")
        expect(_item(window, first)).to_be_visible()
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the list of differences wraps without a horizontal scroll")
        _item(window, first).scroll_into_view_if_needed()
        capture_quantity_rules(run, page, "404-roznice-waskie", full_page=False)
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
