"""Drive features/uklad-folderow-taty.md."""

from __future__ import annotations

from pathlib import Path
import re

from playwright.sync_api import Page, expect

from drive.common import (
    Run,
    close_settings,
    last_opened_is,
    next_step_names_current_step,
    open_settings,
    period_row,
    point_in_settings,
)
from drive.waiting import until
from atrapy.scenariusz_centrum import LAST_COMPLETE


def _choose_folder(run: Run, page: Page, path: str) -> None:
    """Points Centrum to ``path`` in the section Foldery of Ustawienia, over Okresy."""

    point_in_settings(run, page, "Folder okresów", path)


def drive(run: Run, page: Page) -> None:
    feature = "uklad-folderow-taty"
    dad = run.fixture["dad_layout"]

    run.step(feature, "taty-wskazany-tydzien")
    page.goto(run.url)
    window = open_settings(page, "Foldery")
    run.answer_picker(dad["week"])
    window.get_by_role("button", name=re.compile(r"^(Wskaż|Zmień) Folder okresów$")).click()
    until(
        lambda: run.remembered("folder_okresow") == dad["periods_directory"],
        "a week folder chosen in Foldery is saved as Załączniki, the root of Dad's layout",
    )
    settings = run.api("/api/settings", "uklad-taty-ustawienia")
    run.check(
        settings["periods_directory"] == {"state": "ready", "path": dad["periods_directory"], "name": "Załączniki"}
        and settings["periods_all_years"] is True,
        "the server describes the folder okresów as Załączniki of all years",
    )
    expect(window.get_by_text("Załączniki – wszystkie lata", exact=True)).to_be_visible()
    run.check(True, "section Foldery shows Załączniki with „wszystkie lata”, not the week Dad pointed to")
    run.capture(page, "102-uklad-taty-foldery")
    close_settings(page)

    run.step(feature, "taty-tygodnie-ze-wszystkich-miesiecy")
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
    until(last_opened_is(run, Path(dad["opened"])), "the Plik zbiorczy opens from the October INEA folder")
    run.capture(page, "16-uklad-taty-otwieranie", full_page=False)

    run.step(feature, "taty-przywrocenie")
    _choose_folder(run, page, run.fixture["periods_directory"])
    expect(period_row(page, "15_21_09_2026")).to_be_visible()
    run.check(True, "pointing back to the flat INEA folder restores the board the next features expect")
