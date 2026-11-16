"""Drive features/legenda-czynnosci.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.request

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import (
    DAD_VIEWPORT,
    Run,
    close_settings,
    open_settings,
    period_files,
    put_bytes,
    read_bytes,
    read_text,
    remove,
    settings_title,
    settings_window,
)
from drive.waiting import Budget
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
# Dad's editor: a spelling the workers write (instrg6 for instwewrg6), a spelling of another code, a new code.
WITH_SPELLING = "instwewrg6#m (też instrg6#m): # od 1 do 10 →"
TAKEN = "Zapis „inst#m” ma już kod „inst#m”."
NEW_CODE = "listwa#m: # od 1 do 15 → 1 w "
# The preview of a change: the harness writes codes into CZYNNOŚCI ZREALIZOWANE of the Wiersze danych of the Plik
# zbiorczy that Przebieg rozliczeń settled, with Dad's values as he types them; spawpg has his 1 in AB and 70 in AS but
# no red AS. Dad changes the amount of spawpg to 80, so that row changes and differs from what he typed.
COMPLETED_HEADER = "CZYNNOŚCI ZREALIZOWANE"
CODED_ROWS: dict[int, tuple[str, dict[str, int]]] = {
    18: ("inst20m", {"Y": 1}),
    19: ("spawpg listwy", {"AB": 1, "AS": 70}),
    20: ("rt2", {"AK": 1}),
}
SPAWPG_ROW = 19


def _codes(window: Locator) -> Locator:
    return window.get_by_role("list", name="Kody czynności").get_by_role("listitem")


def _edit(window: Locator, spellings: str) -> Locator:
    """Dad's pencil at the code shown as ``spellings``; the form stands in place of its row."""

    window.get_by_role("button", name=f"Zmień {spellings}", exact=True).click()
    form = window.get_by_role("listitem", name=f"Zmiana {spellings}", exact=True)
    expect(form).to_be_visible()
    return form


def _choose(page: Page, form: Locator, field: str, option: str) -> None:
    form.get_by_role("combobox", name=field, exact=True).click()
    page.get_by_role("option", name=option, exact=True).click()


def _close_saved(page: Page) -> None:
    """Dad closes the toast „Zapisano · Cofnij”, which stands over the last rows of the list in the window's corner."""

    saved = page.locator("[data-slot=toast]:not([data-ending-style])").filter(has=page.get_by_text("Zapisano", exact=True))
    expect(saved.get_by_role("button", name="Cofnij", exact=True)).to_be_visible()
    saved.locator("[data-slot=toast-close]").click()
    expect(saved).to_have_count(0)


def _write_codes(collective_file: Path) -> None:
    """Dad's Plik zbiorczy with codes in CZYNNOŚCI ZREALIZOWANE (harness: openpyxl edits the run's file, no lock file)."""

    workbook = load_workbook(collective_file)
    try:
        sheet = workbook.active
        assert isinstance(sheet, Worksheet)
        [column] = [cell.column for cell in sheet[17] if cell.value == COMPLETED_HEADER]
        for row, (text, values) in CODED_ROWS.items():
            sheet.cell(row, column).value = text
            for letter, value in values.items():
                sheet[f"{letter}{row}"].value = value
        workbook.save(collective_file)
    finally:
        workbook.close()


def _preview(run: Run, edit: dict[str, object]) -> dict[str, Any]:
    """The server's preview of ``edit``; the evidence keeps it without the technicians' descriptions (workbook content)."""

    request = urllib.request.Request(
        run.url.rstrip("/") + URL + "/preview",
        data=json.dumps(edit).encode(),
        method="POST",
        headers={"Origin": run.url.rstrip("/"), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=Budget.WORK.value) as response:
        answer: dict[str, Any] = json.load(response)
    shown = {**answer, "rows": [{**row, "description": "<tekst wiersza>"} for row in answer.get("rows", [])]}
    (run.evidence / "api" / "legenda-czynnosci-podglad.json").write_text(json.dumps(shown, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return answer


def _capture(run: Run, page: Page, name: str, answer: dict[str, Any]) -> None:
    """Screenshot with the preview; its ARIA snapshot keeps the descriptions out, like the saved answer."""

    run.capture(page, name, full_page=False)
    snapshot = run.evidence / "aria" / f"{name}.txt"
    text = read_text(snapshot)
    for row in answer.get("rows", []):
        text = text.replace(row["description"], "<tekst wiersza>")
    snapshot.write_text(text, encoding="utf-8")


def _spellings(run: Run, name: str) -> dict[str, str]:
    codes = run.api(URL, name)["codes"]
    assert isinstance(codes, list)
    return {code["id"]: code["spellings"] for code in codes}


def drive(run: Run, page: Page) -> None:
    read = run.api(URL, "legenda-czynnosci")
    codes, columns = read["codes"], read["columns"]
    assert isinstance(codes, list) and isinstance(columns, list)
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
    remove(legend)
    window = open_settings(page, SECTION)
    expect(_codes(window)).to_have_count(len(codes))

    run.step(FEATURE, "legenda-dopisany-zapis")
    form = _edit(window, "instwewrg6#m")
    form.get_by_role("button", name="Dodaj zapis", exact=True).click()
    form.get_by_role("textbox", name="Zapis 2", exact=True).fill("instrg6#m")
    form.get_by_role("button", name="Zapisz", exact=True).click()
    expect(_codes(window).filter(has_text="instwewrg6#m")).to_contain_text(WITH_SPELLING)
    run.check(
        _spellings(run, "legenda-czynnosci-dopisany-zapis")["instwewrg6"] == "instwewrg6#m (też instrg6#m)",
        "the pencil, „Dodaj zapis” and „Zapisz” add the spelling the workers write to the code",
    )
    run.capture(page, "424-legenda-czynnosci-dopisany-zapis", full_page=False)

    run.step(FEATURE, "legenda-odmowa")
    window.get_by_role("button", name="Dodaj kod", exact=True).click()
    form = window.get_by_role("listitem", name="Nowy kod", exact=True)
    form.get_by_role("textbox", name="Zapis 1", exact=True).fill("inst#m")
    _choose(page, form, "Ilość usług", "W jedną kolumnę, liczba bez znaczenia")
    form.get_by_role("combobox", name="Kolumna", exact=True).click()
    options = page.get_by_role("option")
    expect(options.filter(has_text="Spawanie w mufie (AB)")).to_have_count(1)
    shown = [text.strip() for text in options.all_inner_texts()]
    run.check(
        len(shown) == len(columns) and not {"P", "Q", "S", "AS"} & {text.rsplit("(", 1)[-1].rstrip(")") for text in shown},
        f"the column of a code is chosen by its price-list name, only from the {len(shown)} columns the legend writes",
    )
    run.capture(page, "425-legenda-czynnosci-kolumny", full_page=False)
    page.keyboard.press("Escape")
    form.get_by_role("button", name="Zapisz", exact=True).click()
    expect(form.get_by_role("alert")).to_have_text(TAKEN)
    run.check(len(_spellings(run, "legenda-czynnosci-po-odmowie")) == len(codes), "a spelling of another code is one sentence at its field, and the legend stays")
    run.capture(page, "426-legenda-czynnosci-odmowa", full_page=False)

    run.step(FEATURE, "legenda-nowy-kod")
    form.get_by_role("textbox", name="Zapis 1", exact=True).fill("listwa#m")
    _choose(page, form, "Ilość usług", "Kolumna według liczby w kodzie")
    form.get_by_role("spinbutton", name="Kwota w AS", exact=True).fill("30")
    form.get_by_role("button", name="Dodaj kolor", exact=True).click()
    form.get_by_role("button", name="Zapisz", exact=True).click()
    expect(_codes(window).last).to_contain_text(NEW_CODE)
    expect(_codes(window).last).to_contain_text("30 w Uwagi - kwota AS")
    run.check(
        _spellings(run, "legenda-czynnosci-nowy-kod")["listwa"] == "listwa#m",
        "a new code with a range of the number, an amount in AS and a colour is one more sentence of the legend",
    )
    run.capture(page, "427-legenda-czynnosci-nowy-kod", full_page=False)
    _close_saved(page)

    run.step(FEATURE, "legenda-usuniecie-cofnij")
    _edit(window, "listwa#m").get_by_role("button", name="Usuń kod", exact=True).click()
    expect(_codes(window)).to_have_count(len(codes))
    close_settings(page)
    window = open_settings(page, "Historia")
    changes = window.get_by_role("list", name="Zmiany").get_by_role("listitem")
    expect(changes.first).to_contain_text("Legenda czynności")
    expect(changes.first).to_contain_text("Usunięto: listwa#m")
    run.capture(page, "428-legenda-czynnosci-historia-edytora", full_page=False)
    changes.first.get_by_role("button", name="Cofnij: Legenda czynności", exact=True).click()
    expect(changes.first).to_contain_text("Dodano: listwa#m")
    run.check(
        "listwa" in _spellings(run, "legenda-czynnosci-po-cofnieciu"),
        "removing a code is a row of Historia, and its „Cofnij” brings the code back",
    )
    close_settings(page)
    # The features after this one find the legend of the Release, as without Dad's file.
    remove(legend)
    window = open_settings(page, SECTION)
    expect(_codes(window)).to_have_count(len(codes))
    close_settings(page)

    _preview_and_save(run, page, legend, len(codes))

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
        _edit(window, "instutp#m")
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the form of a code with ranges wraps without a horizontal scroll")
        run.capture(page, "429-legenda-czynnosci-waski-formularz", full_page=False)
        window.get_by_role("button", name="Anuluj", exact=True).click()
        close_settings(page)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)


def _preview_and_save(run: Run, page: Page, legend: Path, count: int) -> None:
    collective_file = period_files(run)[1]
    original = read_bytes(collective_file)
    try:
        run.step(FEATURE, "legenda-podglad")
        print("  harness: codes typed into CZYNNOŚCI ZREALIZOWANE of rows 18–20 of the settled Plik zbiorczy", flush=True)
        _write_codes(collective_file)
        window = open_settings(page, SECTION)
        form = _edit(window, "spawpg")
        preview = form.get_by_role("list", name="Podgląd")
        run.check(preview.count() == 0, "an unchanged form of a code has no preview")
        form.get_by_role("spinbutton", name="Kwota w AS", exact=True).fill("80")
        spawpg = next(code["code"] for code in run.api(URL, "legenda-czynnosci-przed-podgladem")["codes"] if code["id"] == "spawpg")
        answer = _preview(run, {"kind": "change", "code_id": "spawpg", "code": {**spawpg, "amount": 80}})
        [row] = [row for row in answer["rows"] if row["row"] == SPAWPG_ROW]
        run.check(
            answer["state"] == "ready" and answer["changed"] == 1 and answer["changed_as_tata"] == 0
            and answer["differences_after"] > answer["differences_before"]
            and [(cell["column"], cell["legend"], cell["tata"]) for cell in row["cells"] if cell["kind"] == "value"] == [("AS", 80, 70)],
            "the server's preview counts with the Kontrola's row check: spawpg at 80 changes 1 row, which differs from Dad's 70 in AS",
        )
        summary = preview.get_by_role("listitem", name="Skutek", exact=True)
        expect(summary).to_contain_text("Zmieni się 1 wiersz, w 0 będzie tak, jak wpisałeś.")
        expect(summary).to_contain_text(
            f"różnice legendy z Kontroli ilości: {answer['differences_before']} → {answer['differences_after']}"
        )
        shown = preview.get_by_role("listitem", name=f"Wiersz {SPAWPG_ROW}", exact=True)
        expect(shown).to_contain_text("CZYNNOŚCI ZREALIZOWANE spawpg listwy")
        expect(shown).to_contain_text("Uwagi - kwota · legenda 80")
        expect(shown).to_contain_text("wpisałeś 70")
        run.check(True, "the preview shows the server's counts, the row with its description, the legend's 80 and Dad's 70 in AS")
        shown.scroll_into_view_if_needed()
        _capture(run, page, "430-legenda-czynnosci-podglad", answer)

        run.step(FEATURE, "legenda-zapis-przy-roznicach")
        form.get_by_role("button", name="Zapisz", exact=True).click()
        expect(_codes(window).filter(has_text="spawpg:")).to_contain_text("80 w Uwagi - kwota AS")
        saved = next(code["code"] for code in run.api(URL, "legenda-czynnosci-zapis-przy-roznicach")["codes"] if code["id"] == "spawpg")
        run.check(saved["amount"] == 80, "„Zapisz” saves the change although the preview shows a difference from Dad")
        run.capture(page, "431-legenda-czynnosci-zapis-przy-roznicach", full_page=False)
        _close_saved(page)
        close_settings(page)
    finally:
        collective_file.write_bytes(original)
        remove(legend, missing_ok=True)
    window = open_settings(page, SECTION)
    expect(_codes(window)).to_have_count(count)
    close_settings(page)
