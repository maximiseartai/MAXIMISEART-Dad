"""Drive features/legenda-czynnosci.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import DAD_VIEWPORT, Run, close_settings, open_settings, put_bytes, remove, settings_title, settings_window
from rozliczenia.centrum.settings.activity_legend import LEGEND_FILE

FEATURE = "legenda-czynnosci"
NARROW: ViewportSize = {"width": 420, "height": 860}
URL = "/api/settings/activity-legend"
SECTION = "Legenda czynności"
NEXT_PREPARATION = (
    "Kody z opisu technika działają przy następnym Przygotowaniu pliku zbiorczego. Gotowe Pliki zbiorcze się nie "
    "zmieniają. # w kodzie to dowolna liczba, np. inst20m."
)
# Column AB in N17:AP17 of the fixture's Wzorzec pliku zbiorczego (PRICE_LIST of atrapy.scenariusz_centrum); the amount
# stands in AS, named „Uwagi - kwota”, and a filled column is its letter alone.
SPAWPG = "spawpg: 1 w Spawanie w mufie AB, 70 w Uwagi - kwota AS, AS na czerwono."
# Dad's file of the legend changed outside Centrum: inst gives 2 in AA (a good file), then spawez also has the spelling
# spawpg, which belongs to spawpg (a bad file).
GOOD = b"""schema_version: 1
kody:
  - {id: inst, zapisy: ["inst{n}m"], kolumna: AA, wartosc: 2}
  - {id: spawpg, zapisy: [spawpg], kolumna: AB, kwota: 70, wypelnienia: [{kolumna: AS, kolor: czerwony}]}
  - {id: spawez, zapisy: [spawez], kolumna: AB}
"""
BAD = GOOD.replace(b"zapisy: [spawez]", b"zapisy: [spawez, spawpg]")
INST_AA = "inst#m: 2 w Przyłącze doziemne AA."
REFUSED = f"Plik {LEGEND_FILE} w folderze config: Zapis „spawpg” ma już kod „spawpg”."


def _codes(window: Locator) -> Locator:
    return window.get_by_role("list", name="Kody czynności").get_by_role("listitem")


def drive(run: Run, page: Page) -> None:
    codes = run.api(URL, "legenda-czynnosci")["codes"]
    assert isinstance(codes, list)
    legend = Path(run.fixture["settings"]).parent / LEGEND_FILE

    run.step(FEATURE, "legenda-zdania")
    page.goto(run.url + "#/okresy")
    window = open_settings(page, SECTION)
    expect(window.get_by_text(NEXT_PREPARATION, exact=True)).to_be_visible()
    expect(_codes(window)).to_have_count(len(codes))
    shown = [text.strip() for text in _codes(window).all_inner_texts()]
    run.check(
        all(text.endswith(".") for text in shown),
        f"each of the {len(codes)} codes of the Release is one sentence on screen ({len(shown)})",
    )
    expect(_codes(window).filter(has_text="spawpg:")).to_have_text(SPAWPG)
    run.check(True, "column AB shows its price-list name next to the letter, the amount stands in „Uwagi - kwota” AS")
    run.capture(page, "420-legenda-czynnosci-szerokie")
    close_settings(page)

    run.step(FEATURE, "legenda-zly-plik")
    print("  harness: Dad's file of the legend changes outside Centrum, first good, then bad", flush=True)
    put_bytes(legend, GOOD)
    window = open_settings(page, SECTION)
    expect(_codes(window).first).to_have_text(INST_AA)
    close_settings(page)
    put_bytes(legend, BAD)
    window = open_settings(page, SECTION)
    expect(window.get_by_role("alert")).to_have_text(REFUSED)
    expect(_codes(window)).to_have_count(3)
    expect(_codes(window).first).to_have_text(INST_AA)
    answer = run.api(URL, "legenda-czynnosci-zly-plik")
    run.check(
        answer["problem"] == {"field": None, "message": REFUSED},
        "a bad file of the legend is a bad setting in one sentence over the last good legend, which Centrum counts",
    )
    run.capture(page, "421-legenda-czynnosci-zly-plik")
    close_settings(page)

    run.step(FEATURE, "legenda-historia")
    window = open_settings(page, "Historia")
    changes = window.get_by_role("list", name="Zmiany").get_by_role("listitem")
    expect(changes.first).to_contain_text(f"Nie przyjęto: {REFUSED}")
    expect(changes.nth(1)).to_contain_text("Legenda czynności")
    expect(changes.nth(1)).to_contain_text(f"Po: {INST_AA}")
    run.check(True, "Historia has both changes outside Centrum, the good one as the code's sentence before and after")
    run.capture(page, "422-legenda-czynnosci-historia", full_page=False)
    close_settings(page)
    # The features after this one find the legend of the Release, as without Dad's file.
    remove(legend)
    window = open_settings(page, SECTION)
    expect(_codes(window)).to_have_count(len(codes))
    close_settings(page)

    run.step(FEATURE, "legenda-waskie-okno")
    page.set_viewport_size(NARROW)
    try:
        page.goto(run.url + "#/ustawienia/legenda-czynnosci")
        window = settings_window(page)
        expect(settings_title(page)).to_have_text(f"Ustawienia/{SECTION}")
        expect(_codes(window)).to_have_count(len(codes))
        run.check(True, f"the narrow window shows every code ({len(codes)})")
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the sentences wrap without a horizontal scroll")
        run.capture(page, "423-legenda-czynnosci-waskie", full_page=False)
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
