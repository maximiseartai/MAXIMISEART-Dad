"""Drive features/uklad-folderow-taty.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect

from drive.common import Run, last_opened_is, next_step_names_current_step, period_row
from atrapy.scenariusz_centrum import LAST_COMPLETE


def _choose_folder(run: Run, page: Page, path: str) -> None:
    """Points Centrum to ``path``: from the empty state when run alone, through the settings card otherwise."""

    run.answer_picker(path)
    unset = run.api("/api/settings", "uklad-taty-ustawienia")["periods_directory"] == {"state": "not_set"}
    name = "Wskaż folder okresów" if unset else "Zmień Folder okresów"
    page.get_by_role("button", name=name, exact=True).click()
    run.wait_for(lambda: run.remembered("folder_okresow") == path, f"the settings file remembers {Path(path).name}")


def drive(run: Run, page: Page) -> None:
    feature = "uklad-folderow-taty"
    dad = run.fixture["dad_layout"]

    run.step(feature, "taty-tygodnie-ze-wszystkich-miesiecy")
    page.goto(run.url)
    _choose_folder(run, page, dad["periods_directory"])
    rows = run.api("/api/periods", "uklad-taty-tablica")["periods"]
    assert isinstance(rows, list)
    run.check(
        [[row["token"], row["status"], row["last_complete"]] for row in rows] == dad["board"],
        "the server finds every Folder okresu in Rozliczenia {rok}\\{miesiąc}\\INEA, newest first",
    )
    table_rows = page.get_by_role("table", name="Tablica okresów").get_by_role("row")
    expect(table_rows).to_have_count(len(dad["on_screen"]) + 1)
    for index, token in enumerate(dad["on_screen"], start=1):
        expect(table_rows.nth(index)).to_contain_text(token)
    expect(period_row(page, LAST_COMPLETE)).to_contain_text("Plik zbiorczy przygotowany")
    run.check(
        True,
        "the screen lists the same weeks except the one that has not started; folders that are not periods "
        "(Podpisane, Nowe rozliczenia) are absent",
    )
    run.capture(page, "15-uklad-taty-tablica")

    run.step(feature, "taty-nastepny-krok")
    next_step = next_step_names_current_step(run, page, LAST_COMPLETE, "Uzupełnienie w Excelu")
    expect(next_step).not_to_contain_text("Brak Folderu okresu")
    run.check(True, "Następny krok sees the prepared Plik zbiorczy of the last complete period in its month folder")

    run.step(feature, "taty-otwieranie")
    page.get_by_role("button", name=f"Plik zbiorczy, okres {LAST_COMPLETE}", exact=True).click()
    run.wait_for(last_opened_is(run, Path(dad["opened"])), "the Plik zbiorczy opens from the October INEA folder")
    run.capture(page, "16-uklad-taty-otwieranie", full_page=False)

    run.step(feature, "taty-przywrocenie")
    _choose_folder(run, page, run.fixture["periods_directory"])
    expect(period_row(page, "15_21_09_2026")).to_be_visible()
    run.check(True, "pointing back to the flat INEA folder restores the board the next features expect")
