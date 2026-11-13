"""Drive features/tablica-skrocona.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect

from drive.common import Run, choose_periods_directory, remove_tree

# The fixture's "today" is Monday 2026-10-19: its period 13_19_10_2026 is the current one, the two after it have not
# started yet. Together with the fixture's four rows (06_12_10_2026 without a Folder okresu) the board has seven
# started periods, newest first.
CURRENT = "13_19_10_2026"
NOT_STARTED = ("27_02_11_2026", "20_26_10_2026")
OLDER = ("08_14_09_2026", "01_07_09_2026")
RECENT = (CURRENT, "06_12_10_2026", "29_05_10_2026", "22_28_09_2026", "15_21_09_2026")
SHOW_ALL = "Pokaż wszystkie"


def _tokens_on_screen(page: Page, expected: tuple[str, ...]) -> None:
    """The table shows exactly ``expected`` in that order, below its header row."""

    rows = page.get_by_role("table", name="Tablica okresów").get_by_role("row")
    expect(rows).to_have_count(len(expected) + 1)
    for index, token in enumerate(expected, start=1):
        expect(rows.nth(index)).to_contain_text(token)


def drive(run: Run, page: Page) -> None:
    feature = "tablica-skrocona"
    periods = Path(run.fixture["periods_directory"])
    added = [periods / token for token in (*NOT_STARTED, CURRENT, *OLDER)]
    show_all = page.get_by_role("button", name=SHOW_ALL, exact=True)

    run.step(feature, "tablica-skrocona-biezacy-i-4-poprzednie")
    page.goto(run.url)
    if run.api("/api/settings", "tablica-skrocona-ustawienia")["periods_directory"] == {"state": "not_set"}:
        choose_periods_directory(run, page)
    for folder in added:
        folder.mkdir()
    try:
        page.reload()
        rows = run.api("/api/periods", "tablica-skrocona")["periods"]
        assert isinstance(rows, list)
        run.check(
            [(row["token"], row["board_place"]) for row in rows]
            == [
                *[(token, "not_started") for token in NOT_STARTED],
                *[(token, "recent") for token in RECENT],
                *[(token, "older") for token in OLDER],
            ],
            "the server places the current period and the 4 before it at once, older ones after Pokaż wszystkie, "
            "and periods that have not started nowhere",
        )
        _tokens_on_screen(page, RECENT)
        expect(show_all).to_be_visible()
        run.check(True, f"the board shows {CURRENT} on top and the 4 periods before it, with {SHOW_ALL} below")
        run.capture(page, "297-tablica-skrocona")

        run.step(feature, "tablica-skrocona-pokaz-wszystkie")
        show_all.click()
        _tokens_on_screen(page, (*RECENT, *OLDER))
        expect(show_all).to_have_count(0)
        run.check(True, f"{SHOW_ALL} adds the older periods below; periods that have not started stay hidden")
        run.capture(page, "298-tablica-rozwinieta")

        run.step(feature, "tablica-skrocona-po-przeladowaniu")
        page.reload()
        _tokens_on_screen(page, RECENT)
        expect(show_all).to_be_visible()
        run.check(True, "after a reload the board is short again")

        run.step(feature, "tablica-skrocona-piec-zaczetych")
        for folder in (periods / token for token in OLDER):
            remove_tree(folder)
        page.reload()
        _tokens_on_screen(page, RECENT)
        expect(show_all).to_have_count(0)
        run.check(True, f"with five started periods and two not started the board has no {SHOW_ALL}")
        run.capture(page, "299-tablica-piec-zaczetych")
    finally:
        for folder in added:
            remove_tree(folder, missing_ok=True)
    page.reload()
    _tokens_on_screen(page, tuple(token for token, *_ in run.fixture["board"]))
    run.check(True, "the board is the fixture's again for the next features")
