"""Drive features/uzupelnienie.md."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import urllib.request

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import Locator, Page, Request, expect

from drive.common import (
    HIDE_TAB,
    SHOW_TAB,
    LogEntry,
    read_bytes,
    read_text,
    Run,
    close_centrum,
    frontend_ms,
    last_opened_is,
    move,
    next_step_names_current_step,
    period_files,
    period_row,
    remove,
    remove_empty_folder,
    start_centrum,
    switch_theme,
)
from drive.waiting import Budget, quiet_for, until
from atrapy.scenariusz_centrum import LAST_COMPLETE, PRICE_LIST, ROW_MARKER
from atrapy.workbooks import excel_lock

FEATURE = "uzupelnienie"
SUMMARY = f"#/uzupelnienie/{LAST_COMPLETE}"
API = f"/api/periods/{LAST_COMPLETE}/quantities-to-fill"
VERSION_API = f"/api/periods/{LAST_COMPLETE}/collective-file-version"
# How often the page asks about the saved version of the Plik zbiorczy; a full read follows a change.
POLL_MS = frontend_ms("lib/use-live-file.ts", "POLL_MS")
# Three of the page's checks and the full read after the last.
LIVE_TIMEOUT_MS = 3 * POLL_MS + 1_000
KIND_TITLES = {"without_rule": "Wiersze bez reguły", "from_description": "Wiersze z opisu"}
# Dad's value goes into a column from the technician's description: it is outside V, T and N, so it also makes
# its row without rule done, and it moves that column's counter.
DAD_COLUMN = "Y"
# The pinned column headers of a kind's table (the row number, then the Plik zbiorczy columns of the row texts the
# server names in ``text_columns``) and each row state's words.
PINNED = ("Nr", "WYKONAWCA", "URZĄDZENIA", "CZYNNOŚCI", "CZYNNOŚCI ZREALIZOWANE")
ROW_LABELS = {"to_fill": "do uzupełnienia", "done": "zrobiony", "without_quantity": "bez ilości"}
# A row number on the summary reads its state's words after the number; a row to fill reads none.
CHIP_LABELS = {"to_fill": "", "done": " zrobiony", "without_quantity": " bez ilości"}
# Dad's 15,6" 1920×1080 touch screen scaled 150% and 125%, in CSS pixels; the narrower must fit 10 columns N:AP.
DAD_WIDTHS = (1280, 1536)
# A period whose Folder okresu holds no Plik zbiorczy.
EMPTY_PERIOD = "15_21_09_2026"


def _expected_rows(run: Run) -> dict[str, list[int]]:
    """The fixture's Plik zbiorczy rows of each kind after Przygotowanie (``preparation.rows`` of fixture.json)."""

    rows = run.fixture["preparation"]["rows"]
    assert isinstance(rows, dict)
    return rows


def _in_rows(rows: int) -> str:
    return "nic nie wpisano" if rows == 0 else f"wpisane w {rows} {'wierszu' if rows == 1 else 'wierszach'}"


def _ready(run: Run, name: str) -> dict[str, object]:
    answer = run.api(API, name)
    run.check(answer["state"] == "ready", f"{name}: the server read the Plik zbiorczy")
    return answer


def _without_read(answer: dict[str, object]) -> dict[str, object]:
    """The answer without its read stamp: the time of every read differs."""

    return {key: value for key, value in answer.items() if key != "read"}


def _rows(answer: dict[str, object]) -> dict[str, list[tuple[int, bool]]]:
    """Each kind's rows as (row number, done)."""

    return {kind: [(row, state == "done") for row, state in rows] for kind, rows in _states(answer).items()}


def _states(answer: dict[str, object]) -> dict[str, list[tuple[int, str]]]:
    """Each kind's rows as (row number, row state)."""

    kinds = answer["kinds"]
    assert isinstance(kinds, list)
    return {kind["kind"]: [(row["row"], row["state"]) for row in kind["rows"]] for kind in kinds}


def _columns(answer: dict[str, object]) -> dict[str, int]:
    columns = answer["description_columns"]
    assert isinstance(columns, list)
    return {column["column"]: column["rows"] for column in columns}


def _check_screen(run: Run, page: Page | Locator, answer: dict[str, object], where: str) -> None:
    """The summary in ``page`` shows every kind's counter and row numbers and every column counter of the answer."""

    kinds = answer["kinds"]
    assert isinstance(kinds, list)
    undone = "Bez ilości" if answer["settled"] else "Do uzupełnienia"
    for kind in kinds:
        rows = [(row["row"], row["state"]) for row in kind["rows"]]
        section = page.get_by_role("region", name=KIND_TITLES[kind["kind"]], exact=True)
        if rows:
            expect(section).to_contain_text(f"{sum(state == 'done' for _, state in rows)} z {len(rows)}")
        else:
            expect(section).to_contain_text("Nie ma takich wierszy.")
        expect(section.get_by_role("img", name="Zrobione" if kind["done"] else undone)).to_be_visible()
        expect(section.get_by_role("listitem")).to_have_text([f"{row}{CHIP_LABELS[state]}" for row, state in rows])
    columns = _columns(answer)
    reminder = page.get_by_role("region", name="Kolumny z opisu technika", exact=True)
    expect(reminder.locator("dt")).to_have_text(list(columns))
    expect(reminder.locator("dd")).to_have_text([_in_rows(rows) for rows in columns.values()])
    run.check(True, f"{where}: counters, row numbers with their done state, and column counters match the server")


# Every text the result card's summary shows from now on, so a short-lived old copy cannot slip between two checks.
WATCH_RESULT_SUMMARY = """() => {
  window.__resultSummaries = []
  const seen = () => {
    const summary = document.querySelector('[aria-label="Uzupełnienie pliku zbiorczego"]')
    if (summary !== null) window.__resultSummaries.push(summary.textContent)
  }
  window.__resultSummaryObserver = new MutationObserver(seen)
  window.__resultSummaryObserver.observe(document.body, { subtree: true, childList: true, characterData: true })
}"""
SHOWN_RESULT_SUMMARIES = "() => { window.__resultSummaryObserver.disconnect(); return window.__resultSummaries }"


def drive_result_card(run: Run, page: Page) -> None:
    """Entry from Przygotowanie: the written Plik zbiorczy's result card shows the summary and leads to it.

    Then the card after a restart of Centrum, from Logi: the last Uruchomienie is this written Przygotowanie only here.
    """

    run.step(FEATURE, "uzupelnienie-wynik")
    card = page.get_by_role("region", name="Podgląd na żywo")
    filling = card.get_by_role("region", name="Uzupełnienie pliku zbiorczego", exact=True)
    expect(filling.get_by_role("heading", name="Do uzupełnienia w Excelu")).to_be_visible()
    answer = _ready(run, "uzupelnienie-wynik")
    run.check(
        _rows(answer) == {kind: [(row, False) for row in rows] for kind, rows in _expected_rows(run).items()},
        "right after Przygotowanie the server lists rows 18 and 20 without rule and row 19 from the description",
    )
    _check_screen(run, filling, answer, "on the Przygotowanie result card")
    run.capture(page, "250-uzupelnienie-wynik")
    # The summary first shows the card's copy and reads again in the background; that read ends before the file
    # changes, so the page's copy is surely older than the file below.
    with page.expect_response(lambda response: response.url.endswith(API)):
        filling.get_by_role("button", name="Uzupełnij", exact=True).click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}")
    # The address changes before the page handles it: until then the result card, with the same counters, is still
    # shown, and Wstecz would leave it mounted with its copy from before the file changes.
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    _check_screen(run, page, answer, "on the summary opened from the result card")

    run.step(FEATURE, "uzupelnienie-wynik-bez-starej-kopii")
    collective_file = period_files(run)[1]
    original = read_bytes(collective_file)
    # The summary asks for the file's version every 3 s and would read the new file into its copy before Wstecz.
    before = run.api(VERSION_API, "uzupelnienie-wynik-znacznik-przed-wpisem")["version"]
    page.route(f"**{VERSION_API}", lambda route: route.fulfill(json={"version": before}))
    try:
        run.check(True, "harness: the summary's version checks answer the version from before, so its copy stays the one read before")
        _write_dad_value(collective_file, _expected_rows(run)["without_rule"][0])
        run.check(True, f"harness: one value typed into column {DAD_COLUMN} of row 18 while the summary is open")
        page.evaluate(WATCH_RESULT_SUMMARY)
        page.go_back()
        expect(filling).to_contain_text("1 z 2")
        changed = _ready(run, "uzupelnienie-wynik-po-wpisie")
        _check_screen(run, filling, changed, "on the result card after Dad's value")
        shown = page.evaluate(SHOWN_RESULT_SUMMARIES)
        assert isinstance(shown, list)
        run.check(
            not any("0 z 2" in text for text in shown),
            "back on the result card the summary waits for its read instead of the summary page's older copy",
        )
    finally:
        page.unroute(f"**{VERSION_API}")
        collective_file.write_bytes(original)
    run.check(True, "Uzupełnij on the result card opens the same summary, and Wstecz returns to the result")

    run.step(FEATURE, "uzupelnienie-wynik-na-zywo")
    _live_result_card(run, page, filling, collective_file)

    run.step(FEATURE, "uzupelnienie-wynik-po-przebiegu")
    _settled_result_card(run, page, filling, collective_file)

    run.step(FEATURE, "uzupelnienie-wynik-bez-odpowiedzi")
    _unanswered_result_card(run, page, filling)

    run.step(FEATURE, "uzupelnienie-wynik-bez-centrum")
    _silent_result_card(run, page, filling)

    run.step(FEATURE, "uzupelnienie-wynik-po-starcie")
    close_centrum(run, page)
    start_centrum(run, "uzupelnienie-start-po-zamknieciu")
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    restored = page.get_by_role("region", name="Ostatnie Uruchomienie")
    expect(restored.get_by_label("Wynik")).to_contain_text("Plik zbiorczy przygotowany · wymaga sprawdzenia")
    summary = restored.get_by_role("region", name="Uzupełnienie pliku zbiorczego", exact=True)
    expect(summary.get_by_role("heading", name="Do uzupełnienia w Excelu")).to_be_visible()
    _check_screen(run, summary, _ready(run, "uzupelnienie-wynik-po-starcie"), "on the card from Logi after a restart")
    run.capture(page, "252-uzupelnienie-wynik-po-starcie")


# Every return to the tab the page could read on instead of its own checks of the saved version.
WATCH_RETURNS = """() => {
  window.__bez_przeladowania = true
  window.__powroty = 0
  window.addEventListener("focus", () => { window.__powroty += 1 })
  document.addEventListener("visibilitychange", () => { window.__powroty += 1 })
}"""
# Longer than two of the page's version checks.
HIDDEN_MS = 2 * POLL_MS + 1_000


def _live_result_card(run: Run, page: Page, filling: Locator, collective_file: Path) -> None:
    """Excel next to Centrum: the result card shows Dad's values by itself, and asks nothing while the tab is hidden."""

    asked: list[str] = []

    def record(request: Request) -> None:
        asked.append(urlsplit(request.url).path)

    page.on("request", record)
    original = read_bytes(collective_file)
    section = filling.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True)
    try:
        page.evaluate(WATCH_RETURNS)
        for row in _expected_rows(run)["without_rule"]:
            _write_dad_value(collective_file, row)
        run.check(True, f"harness: Dad's values typed into column {DAD_COLUMN} of rows 18 and 20 and saved")
        expect(section).to_contain_text("2 z 2", timeout=LIVE_TIMEOUT_MS)
        run.check(
            page.evaluate("() => window.__bez_przeladowania === true && window.__powroty === 0")
            and asked.count(VERSION_API) >= 1,
            f"the card shows 2 z 2 without a click, focus, tab switch or reload, after {asked.count(VERSION_API)} "
            "check(s) of the saved version",
        )
        _check_screen(run, filling, _ready(run, "uzupelnienie-wynik-na-zywo"), "on the result card, live")
        expect(filling).to_contain_text("Nie widzisz zmian? Zapisz w Excelu (Ctrl+S).")
        run.check(True, "the card has the summary page's hint about saving in Excel")
        run.capture(page, "255-uzupelnienie-wynik-na-zywo")

        page.evaluate(HIDE_TAB)
        hidden_from = len(asked)
        quiet_for(page, HIDDEN_MS)
        hidden = asked[hidden_from:]
        run.check(
            VERSION_API not in hidden and API not in hidden,
            f"with the tab hidden for {HIDDEN_MS} ms the card asks nothing about the Plik zbiorczy ({hidden})",
        )
        page.evaluate(SHOW_TAB)
        with page.expect_request(lambda request: urlsplit(request.url).path == VERSION_API, timeout=LIVE_TIMEOUT_MS):
            pass
        run.check(True, "back in the tab the card checks the saved version again")
    finally:
        page.evaluate("() => { delete document.visibilityState }")
        page.remove_listener("request", record)
        collective_file.write_bytes(original)
    expect(section).to_contain_text("0 z 2", timeout=LIVE_TIMEOUT_MS)
    run.check(True, "with the file back as it was the card goes back to 0 z 2 by itself")


# Dad comes back to Centrum from Excel or Eksplorator: the card reads the Plik zbiorczy again.
RETURN_TO_TAB = "() => window.dispatchEvent(new Event('focus'))"


def _settled_result_card(run: Run, page: Page, filling: Locator, collective_file: Path) -> None:
    """After Przebieg rozliczeń the result card is a preview like the summary: „bez ilości”, no hint about saving."""

    hint = filling.get_by_text("Nie widzisz zmian?")
    expect(hint).to_have_count(1)
    worker_settlements = collective_file.with_name(f"Rozliczenie pracowników {LAST_COMPLETE}")
    worker_settlements.mkdir()
    try:
        run.check(
            True,
            "harness: the Folder rozliczeń pracowników a Przebieg rozliczeń creates exists, removed after this step",
        )
        page.evaluate(RETURN_TO_TAB)
        section = filling.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True)
        expect(section.get_by_role("listitem")).to_have_text(["18 bez ilości", "20 bez ilości"])
        answer = _ready(run, "uzupelnienie-wynik-po-przebiegu")
        run.check(answer["settled"] is True, "after Przebieg the server's answer is settled")
        _check_screen(run, filling, answer, "on the result card after Przebieg")
        expect(hint).to_have_count(0)
        run.check(True, "after Przebieg the result card has no hint about saving in Excel")
        run.capture(page, "256-uzupelnienie-wynik-po-przebiegu")
    finally:
        remove_empty_folder(worker_settlements)
    page.evaluate(RETURN_TO_TAB)
    expect(hint).to_have_count(1)
    run.check(True, "without the Folder rozliczeń pracowników the hint is back on the card")


def _unanswered_result_card(run: Run, page: Page, filling: Locator) -> None:
    """The server gives no answer about the Plik zbiorczy: the card says so instead of going blank, then recovers."""

    page.route(f"**{API}", lambda route: route.abort())
    try:
        run.check(True, "harness: the card's reads of the Plik zbiorczy get no answer from the server")
        page.evaluate(RETURN_TO_TAB)
        failure = filling.get_by_role("alert")
        expect(failure).to_contain_text("Nie udało się odczytać Pliku zbiorczego")
        expect(failure.get_by_role("button", name="Spróbuj ponownie")).to_be_visible()
        run.check(True, "without an answer the result card says it could not read the Plik zbiorczy, never blank")
        run.capture(page, "257-uzupelnienie-wynik-bez-odpowiedzi")
    finally:
        page.unroute(f"**{API}")
    section = filling.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True)
    expect(section).to_contain_text("0 z 2", timeout=LIVE_TIMEOUT_MS)
    expect(filling.get_by_role("alert")).to_have_count(0)
    run.check(True, "once the server answers again the card shows the summary by itself")


def _silent_result_card(run: Run, page: Page, filling: Locator) -> None:
    """Centrum stops answering while the card is open: after one version check the card says it could not read the
    Plik zbiorczy instead of showing the old summary as live, then recovers."""

    for path in (VERSION_API, API):
        page.route(f"**{path}", lambda route: route.abort())
    try:
        run.check(True, "harness: neither the version checks nor the reads of the Plik zbiorczy get an answer")
        failure = filling.get_by_role("alert")
        expect(failure).to_contain_text("Nie udało się odczytać Pliku zbiorczego", timeout=LIVE_TIMEOUT_MS)
        run.check(True, "a version check without an answer reads the file, so the card shows the failure, not old data")
        run.capture(page, "258-uzupelnienie-wynik-bez-centrum")
    finally:
        for path in (VERSION_API, API):
            page.unroute(f"**{path}")
    section = filling.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True)
    expect(section).to_contain_text("0 z 2", timeout=LIVE_TIMEOUT_MS)
    expect(filling.get_by_role("alert")).to_have_count(0)
    run.check(True, "once Centrum answers again the card shows the summary by itself")


def _drive_entries(run: Run, page: Page) -> None:
    """Entries from Okresy: the Tablica okresów row and Droga okresu of the card Następny krok."""

    run.step(FEATURE, "uzupelnienie-tablica")
    page.goto(run.url)
    row = period_row(page, LAST_COMPLETE)
    expect(row).to_contain_text("Plik zbiorczy przygotowany")
    fill = row.get_by_role("button", name=f"Uzupełnij, okres {LAST_COMPLETE}", exact=True)
    others = page.get_by_role("table", name="Tablica okresów").get_by_role("button", name="Uzupełnij, okres", exact=False)
    board = run.api("/api/periods", "uzupelnienie-tablica")
    periods = board["periods"]
    assert isinstance(periods, list)
    prepared = [period["token"] for period in periods if period["status"] == "collective_file_prepared"]
    expect(others).to_have_count(len(prepared))
    for token in prepared:
        expect(period_row(page, token).get_by_role("button", name=f"Uzupełnij, okres {token}", exact=True)).to_be_visible()
    run.check(
        LAST_COMPLETE in prepared and len(prepared) < len(periods),
        f"exactly the rows with Status okresu Plik zbiorczy przygotowany ({', '.join(prepared)}) offer Uzupełnij",
    )
    run.capture(page, "251-uzupelnienie-tablica")
    fill.click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}")
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    _check_screen(run, page, _ready(run, "uzupelnienie-z-tablicy"), "on the summary opened from Tablica okresów")

    run.step(FEATURE, "uzupelnienie-droga")
    page.go_back()
    path = page.get_by_role("region", name="Następny krok").get_by_role("list", name="Droga okresu")
    current = path.locator('[aria-current="step"]')
    expect(current).to_have_count(1)
    expect(current).to_contain_text("Uzupełnienie w Excelu")
    expect(path.get_by_role("img", name="zrobione")).to_have_count(1)
    steps = path.get_by_role("listitem")
    expect(steps).to_have_count(4)
    expect(steps).to_contain_text(["Plik zbiorczy", "Uzupełnienie w Excelu", "Wycena w efenix", "Rozliczenia pracowników"])
    run.check(
        True,
        "Droga okresu has four steps, with Wycena w efenix before Rozliczenia pracowników, and shows Uzupełnienie w "
        "Excelu as the current step after Plik zbiorczy",
    )


def _shown(cell: dict[str, object]) -> str:
    """A quantity cell's text as the table renders it, screen-reader words included."""

    value = cell["value"]
    if value == 0:
        return ""
    if value == "nieliczbowa":
        return "? nieliczbowa"
    return f"{value} narzędzie" if cell["source"] == "tool" else str(value)


def _without_texts(answer: dict[str, object]) -> dict[str, object]:
    """The answer with the four row texts replaced: what is left must not carry any workbook content."""

    rows = answer["rows"]
    assert isinstance(rows, list)
    return {**answer, "rows": [{**row, "texts": ["<tekst wiersza>" for _ in row["texts"]]} for row in rows]}


def _completed(answer: dict[str, object], row: dict[str, object]) -> str:
    """The row's CZYNNOŚCI ZREALIZOWANE: its text under that header of ``text_columns``."""

    headers, texts = answer["text_columns"], row["texts"]
    assert isinstance(headers, list) and isinstance(texts, list)
    return str(dict(zip(headers, texts, strict=True))["CZYNNOŚCI ZREALIZOWANE"])


def _kind_answer(run: Run, kind: str, name: str | None = None) -> dict[str, object]:
    """The kind's table from the server; the evidence keeps it without the row texts, which are workbook content."""

    with urllib.request.urlopen(f"{run.url.rstrip('/')}{API}/{kind}", timeout=Budget.SCREEN.value) as response:
        answer = json.load(response)
    assert isinstance(answer, dict)
    (run.evidence / "api" / f"{name or f'uzupelnienie-tabela-{kind}'}.json").write_text(
        json.dumps(_without_texts(answer), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return answer


def _capture(run: Run, page: Page, name: str, answer: dict[str, object]) -> None:
    """Screenshot of a kind page; its ARIA snapshot keeps the row texts out, like the saved answer."""

    run.capture(page, name)
    rows = answer["rows"]
    assert isinstance(rows, list)
    snapshot = run.evidence / "aria" / f"{name}.txt"
    text = read_text(snapshot)
    for row in rows:
        for value in row["texts"]:
            if value:
                text = text.replace(value, "<tekst wiersza>")
    snapshot.write_text(text, encoding="utf-8")


def _measured(entry: LogEntry, operation: str) -> bool:
    """A measurement of a view of page uzupelnienie (``pomiar`` in the Centrum log) that carries ``operation``."""

    return (
        entry.event == "pomiar"
        and entry.facts.get("strona") == "uzupelnienie"
        and f"{operation}:" in entry.facts.get("zapytania", "")
    )


def _drive_kind(run: Run, page: Page, kind: str, shot: str) -> dict[str, object]:
    """From the summary, open the kind's table and check it against the server; returns the server's answer."""

    title = KIND_TITLES[kind]
    since = len(run.log_entries())
    page.get_by_role("region", name=title, exact=True).get_by_role("link").click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}/{kind}")
    table = page.get_by_role("table", name="Wiersze Pliku zbiorczego", exact=True)
    expect(table).to_be_visible()
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    expect(page.get_by_role("main").get_by_role("heading", level=2)).to_have_text([title])
    answer = _kind_answer(run, kind)
    rows = answer["rows"]
    columns = answer["columns"]
    assert isinstance(rows, list) and isinstance(columns, list)
    run.check(
        answer["state"] == "ready" and [row["row"] for row in rows] == _expected_rows(run)[kind],
        f"{title}: the server lists only this kind's rows, ascending",
    )
    run.check(
        ROW_MARKER not in json.dumps(_without_texts(answer), ensure_ascii=False)
        and all(ROW_MARKER in _completed(answer, row) for row in rows),
        f"{title}: the answer carries the row texts and no address, order number or UMOWA",
    )
    run.check(
        answer["text_columns"] == list(PINNED[1:]),
        f"{title}: the server names the row texts by their Plik zbiorczy headers",
    )
    run.check(
        [column["name"] for column in columns] == list(PRICE_LIST),
        f"{title}: every column N:AP carries its price-list name from row 17 of the Plik zbiorczy",
    )

    expect(table.get_by_role("columnheader")).to_have_count(len(PINNED) + len(columns))
    expect(table.get_by_role("columnheader")).to_have_text(
        [*PINNED, *(re.compile(f"^{column['column']}{re.escape(column['name'])}$") for column in columns)]
    )
    expect(table.get_by_role("rowheader")).to_have_text([f"{row['row']} {ROW_LABELS[row['state']]}" for row in rows])
    for row in rows:
        line = table.locator(f"tr[data-state='{row['state']}']", has=page.get_by_role("rowheader", name=str(row["row"])))
        expect(line.locator("td[data-source]")).to_have_text([_shown(cell) for cell in row["cells"]])
        expect(line.locator("td[data-source='tata']")).to_have_count(
            sum(cell["source"] == "tata" for cell in row["cells"])
        )
    run.check(True, f"{title}: row numbers, row states and every N:AP cell on screen equal the server's answer")

    [first] = columns[:1]
    table.get_by_role("button", name=f"{first['column']}: {first['name']}", exact=True).click()
    expect(page.locator("[data-slot=popover-content]")).to_contain_text(first["name"])
    page.keyboard.press("Escape")
    expect(page.locator("[data-slot=popover-content]")).to_have_count(0)
    completed = _completed(answer, rows[0])
    table.get_by_role("button", name=f"CZYNNOŚCI ZREALIZOWANE: {completed}", exact=True).click()
    expect(page.locator("[data-slot=popover-content]")).to_contain_text(completed)
    run.check(True, f"{title}: a tap on a column header or on CZYNNOŚCI ZREALIZOWANE shows the full text")
    until(
        lambda: any(
            _measured(entry, "getKindTable") for entry in run.log_entries()[since:]
        ),
        f"{title}: the view is measured as page uzupelnienie with its getKindTable request",
    )
    _capture(run, page, f"{shot}-otwarty-opis", answer)
    page.keyboard.press("Escape")
    original = page.viewport_size
    for width in DAD_WIDTHS:
        page.set_viewport_size({"width": width, "height": 800})
        visible = table.evaluate(
            """table => {
                const right = table.parentElement.getBoundingClientRect().right
                return [...table.querySelectorAll("thead th")].slice(5)
                    .filter((th) => th.getBoundingClientRect().right <= right + 0.5).length
            }"""
        )
        run.check(
            width > DAD_WIDTHS[0] or visible >= 10,
            f"{title}: at {width} px with the menu open {visible} columns N:AP fit next to the pinned texts",
        )
        _capture(run, page, f"{shot}-{width}px", answer)
    if original is not None:
        page.set_viewport_size(original)
    switched = switch_theme(page, "jasny")
    _capture(run, page, f"{shot}-jasny", answer)
    if switched:
        switch_theme(page, "ciemny")

    number = table.get_by_role("rowheader").first
    before = number.bounding_box()
    table.locator("xpath=..").evaluate("box => { box.scrollLeft = box.scrollWidth }")
    expect(table.get_by_role("columnheader", name=re.compile("^AP")).first).to_be_in_viewport()
    after = number.bounding_box()
    run.check(
        before is not None and after is not None and before["x"] == after["x"],
        f"{title}: the row number stays in place while the quantity columns scroll sideways",
    )
    # Column Y (Dad's value in row 18) right after the pinned columns, as Dad would scroll to it.
    table.evaluate(
        """table => {
            const [n, y] = ["N", "Y"].map((letter) =>
                [...table.querySelectorAll("thead th")].find((th) => th.textContent.startsWith(letter))
            )
            table.parentElement.scrollLeft = y.offsetLeft - n.offsetLeft
        }"""
    )
    _capture(run, page, f"{shot}-przewiniete", answer)

    page.get_by_role("main").get_by_role("link", name="Podsumowanie", exact=True).click()
    expect(page.get_by_role("region", name="Kolumny z opisu technika", exact=True)).to_be_visible()
    return answer


def _live_kind_cell(run: Run, page: Page, collective_file: Path, table_answer: dict[str, object]) -> None:
    """Dad types the missing quantity of row 20 while its kind's table is open, then deletes it again.

    ``table_answer`` is the kind's earlier answer: the row texts it hides in the ARIA snapshot have not changed.
    """

    row = _expected_rows(run)["without_rule"][1]
    page.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True).get_by_role("link").click()
    table = page.get_by_role("table", name="Wiersze Pliku zbiorczego", exact=True)
    line = table.locator("tr", has=page.get_by_role("rowheader", name=str(row)))
    expect(line).to_have_attribute("data-state", "to_fill")
    page.evaluate("() => { window.__bez_przeladowania = true }")
    _write_dad_value(collective_file, row)
    expect(line).to_have_attribute("data-state", "done", timeout=LIVE_TIMEOUT_MS)
    expect(line.locator("td[data-source='tata']")).to_have_text(["1"])
    run.check(
        page.evaluate("() => window.__bez_przeladowania === true"),
        f"harness typed 1 into {DAD_COLUMN}{row}: the row turns done with Dad's green value without a click or reload",
    )
    _capture(run, page, "227-uzupelnienie-tabela-na-zywo", table_answer)
    _write_dad_value(collective_file, row, None)
    expect(line).to_have_attribute("data-state", "to_fill", timeout=LIVE_TIMEOUT_MS)
    run.check(True, f"harness deleted {DAD_COLUMN}{row} again: the row is to fill again by itself")
    page.get_by_role("main").get_by_role("link", name="Podsumowanie", exact=True).click()
    expect(page.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True)).to_contain_text("1 z 2")


def _write_dad_value(collective_file: Path, row: int, value: int | None = 1) -> None:
    """Dad types one quantity in Excel and saves (harness: openpyxl edits the run's Plik zbiorczy, no lock file)."""

    workbook = load_workbook(collective_file)
    try:
        sheet = workbook.active
        assert isinstance(sheet, Worksheet)
        sheet.cell(row, column_index_from_string(DAD_COLUMN)).value = value
        workbook.save(collective_file)
    finally:
        workbook.close()


def drive(run: Run, page: Page) -> None:
    _, collective_file = period_files(run)
    original = read_bytes(collective_file)
    lock = excel_lock(collective_file)
    try:
        _drive(run, page, collective_file, lock)
    finally:
        # The harness's value must not reach Przebieg rozliczeń, which continues from this Plik zbiorczy.
        collective_file.write_bytes(original)
        remove(lock, missing_ok=True)

    run.step(FEATURE, "uzupelnienie-bez-pliku")
    page.goto(f"{run.url.rstrip('/')}/#/uzupelnienie/{EMPTY_PERIOD}")
    answer = run.api(f"/api/periods/{EMPTY_PERIOD}/quantities-to-fill", "uzupelnienie-bez-pliku")
    message = answer["message"]
    assert isinstance(message, dict)
    notice = page.get_by_label("Komunikat", exact=True)
    for part in ("what", "where", "action"):
        expect(notice).to_contain_text(message[part])
    run.check(
        answer["state"] == "problem" and page.get_by_role("alert").filter(has_text="Nie udało się").count() == 0,
        "a period without a Plik zbiorczy shows the server's three-part Komunikat, calm and not as a failure",
    )
    # Alone the period has no Plik zbiorczy; in `all`, tablica-okresow has left one there.
    on_disk = (Path(run.fixture["periods_directory"]) / EMPTY_PERIOD / f"Rozliczenie {EMPTY_PERIOD} - zbiorcze.xlsx").is_file()
    expect(page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True)).to_have_count(1 if on_disk else 0)
    run.check(
        answer["collective_file_exists"] is on_disk,
        f"Otwórz Plik zbiorczy is there only when the Plik zbiorczy is in the Folder okresu ({on_disk=})",
    )
    page.goto(f"{run.url.rstrip('/')}/#/uzupelnienie/{EMPTY_PERIOD}/without_rule")
    expect(page.get_by_label("Komunikat", exact=True)).to_contain_text(str(message["what"]))
    expect(page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True)).to_have_count(1 if on_disk else 0)
    run.check(True, "the kind page of the same period follows the same rule")
    page.go_back()
    run.check(
        any(
            entry.event == "uzupelnienie-odczyt-nieudany" and entry.facts.get("okres") == EMPTY_PERIOD
            for entry in run.log_entries()
        ),
        "the failed read is in the Centrum log with the period",
    )
    run.capture(page, "224-uzupelnienie-bez-pliku")

    run.step(FEATURE, "uzupelnienie-gotowe-bez-okresu")
    # In `all` the file tablica-okresow left makes the period one Przebieg rozliczeń offers; set it aside meanwhile.
    left = Path(run.fixture["periods_directory"]) / EMPTY_PERIOD / f"Rozliczenie {EMPTY_PERIOD} - zbiorcze.xlsx"
    aside = left.with_name(f".{left.name}.na-bok")
    if on_disk:
        move(left, aside)
        run.check(True, f"harness: the Plik zbiorczy tablica-okresow left in {EMPTY_PERIOD} is set aside for this step")
    try:
        page.get_by_role("button", name="Gotowe, rozlicz pracowników", exact=True).click()
        expect(page.get_by_role("radio", name="Przebieg rozliczeń")).to_be_checked()
        expect(page.get_by_role("combobox", name="Okres")).to_contain_text(LAST_COMPLETE)
        expect(page.get_by_role("alert").filter(has_text=f"Okresu {EMPTY_PERIOD} nie ma do wyboru")).to_contain_text(
            f"wybrany jest {LAST_COMPLETE}"
        )
        run.check(True, f"Gotowe of {EMPTY_PERIOD}, which Przebieg rozliczeń does not offer, says aloud which period it chose")
        run.capture(page, "254-uzupelnienie-gotowe-bez-okresu")
    finally:
        if on_disk:
            move(aside, left)
    page.goto(run.url)
    page.reload()


def _drive(run: Run, page: Page, collective_file: Path, lock: Path) -> None:
    _drive_entries(run, page)
    run.step(FEATURE, "uzupelnienie-karta")
    page.goto(run.url)
    next_step = next_step_names_current_step(run, page, LAST_COMPLETE, "Uzupełnienie w Excelu")
    fill = next_step.get_by_role("button", name="Uzupełnij", exact=True)
    expect(fill).to_be_visible()
    expect(next_step.get_by_role("button", name="Wyceń w efenix", exact=True)).to_be_visible()
    board = run.api("/api/periods", "uzupelnienie-karta")
    periods = board["periods"]
    assert isinstance(periods, list)
    [last] = [period for period in periods if period["last_complete"]]
    run.check(
        last["token"] == LAST_COMPLETE and last["status"] == "collective_file_prepared",
        "Następny krok offers Uzupełnij for the last complete period with Plik zbiorczy przygotowany, "
        "with Wyceń w efenix next to it",
    )
    run.capture(page, "220-uzupelnienie-karta")

    run.step(FEATURE, "uzupelnienie-podsumowanie")
    since = len(run.log_entries())
    fill.click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}")
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    expect(page.get_by_role("main").get_by_text(LAST_COMPLETE, exact=True)).to_be_visible()
    before = _ready(run, "uzupelnienie-podsumowanie")
    run.check(
        _rows(before) == {kind: [(row, False) for row in rows] for kind, rows in _expected_rows(run).items()},
        "the server lists rows 18 and 20 without rule and row 19 from the description, none done yet",
    )
    _check_screen(run, page, before, "after Uzupełnij")
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    expect(menu.get_by_role("link", name="Okresy", exact=True)).to_have_attribute("data-active", "")
    until(
        lambda: any(
            _measured(entry, "getQuantitiesToFill") for entry in run.log_entries()[since:]
        ),
        "the view is measured as page uzupelnienie with its getQuantitiesToFill request",
    )
    run.capture(page, "221-uzupelnienie-podsumowanie")

    run.step(FEATURE, "uzupelnienie-wpis-taty")
    row = _expected_rows(run)["without_rule"][0]
    asked: list[str] = []
    page.on("request", lambda request: asked.append(urlsplit(request.url).path))
    page.evaluate("() => { window.__bez_przeladowania = true }")
    _write_dad_value(collective_file, row)
    run.check(not lock.exists(), f"harness: one value typed into column {DAD_COLUMN} of row {row}, saved and closed")
    region = page.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True)
    expect(region).to_contain_text("1 z 2", timeout=LIVE_TIMEOUT_MS)
    run.check(
        page.evaluate("() => window.__bez_przeladowania === true") and asked.count(VERSION_API) >= 1,
        f"the counter changed to 1 z 2 without a click or reload, after {asked.count(VERSION_API)} "
        "check(s) of the saved version",
    )
    after = _ready(run, "uzupelnienie-po-wpisie")
    columns_before, columns_after = _columns(before), _columns(after)
    run.check(
        _rows(after) == {**_rows(before), "without_rule": [(18, True), (20, False)]}
        and columns_after == {**columns_before, DAD_COLUMN: columns_before[DAD_COLUMN] + 1},
        f"row {row} is done and only column {DAD_COLUMN} counts one more row",
    )
    views = asked.count(API)
    for _ in range(2):
        with page.expect_request(lambda request: urlsplit(request.url).path == VERSION_API, timeout=LIVE_TIMEOUT_MS):
            pass
    run.check(asked.count(API) == views, "two more checks of the unchanged saved version read nothing again")
    _check_screen(run, page, after, "after Dad's value")
    switched = switch_theme(page, "jasny")
    run.capture(page, "222-uzupelnienie-po-wpisie")
    if switched:
        switch_theme(page, "ciemny")

    run.step(FEATURE, "uzupelnienie-tabela-bez-reguly")
    without_rule = _drive_kind(run, page, "without_rule", "225-uzupelnienie-bez-reguly")
    rows = without_rule["rows"]
    assert isinstance(rows, list)
    dad_cells = {row["row"]: [cell for cell in row["cells"] if cell["source"] == "tata"] for row in rows}
    run.check(
        [row["state"] for row in rows] == ["done", "to_fill"] and dad_cells == {18: [{"source": "tata", "value": 1}], 20: []},
        f"Dad's value in {DAD_COLUMN}18 comes back green with his value and makes row 18 done; row 20 stays to fill",
    )

    run.step(FEATURE, "uzupelnienie-tabela-z-opisu")
    _drive_kind(run, page, "from_description", "226-uzupelnienie-z-opisu")

    run.step(FEATURE, "uzupelnienie-tabela-na-zywo")
    _live_kind_cell(run, page, collective_file, without_rule)

    run.step(FEATURE, "uzupelnienie-blokada-excela")
    lock.write_bytes(b"\x00" * 165)
    page.reload()
    held = _ready(run, "uzupelnienie-blokada-excela")
    held_read = held["read"]
    assert isinstance(held_read, dict)
    expect(page.get_by_role("status").filter(has_text="Stan z")).to_have_count(0)
    run.check(
        held_read["retrying"] is False and _without_read(held) == _without_read(after),
        "with Excel's lock file next to the Plik zbiorczy the server reads its last saved version unchanged",
    )
    _check_screen(run, page, held, "with Excel's lock file")
    run.capture(page, "223-uzupelnienie-blokada-excela")

    run.step(FEATURE, "uzupelnienie-odczyt-nieudany")
    remove(lock)
    saved = read_bytes(collective_file)
    collective_file.write_bytes(b"Excel zapisuje")
    status = page.get_by_role("status").filter(has_text="Stan z")
    expect(status).to_be_visible(timeout=LIVE_TIMEOUT_MS)
    kept = _ready(run, "uzupelnienie-odczyt-nieudany")
    read = kept["read"]
    assert isinstance(read, dict)
    run.check(
        read["retrying"] is True and _without_read(kept) == _without_read(held),
        "a Plik zbiorczy Centrum cannot read keeps the last good state, marked as retried",
    )
    _check_screen(run, page, kept, "while the read fails")
    expect(page.get_by_label("Komunikat", exact=True)).to_have_count(0)
    run.capture(page, "229-uzupelnienie-odczyt-nieudany")
    collective_file.write_bytes(saved)
    expect(status).to_have_count(0, timeout=LIVE_TIMEOUT_MS)
    run.check(True, "once the file reads again the time disappears, without a click")

    run.step(FEATURE, "uzupelnienie-otworz")
    page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True).click()
    until(last_opened_is(run, collective_file), "Otwórz Plik zbiorczy opened the period's Plik zbiorczy")
    expect(page.get_by_text(collective_file.name, exact=True).last).to_be_visible()

    run.step(FEATURE, "uzupelnienie-powrot")
    page.get_by_role("main").get_by_role("link", name="Okresy", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Okresy")
    page.go_back()
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    run.check(True, "the link Okresy leads back, and Wstecz returns to the summary of the same period")

    run.step(FEATURE, "uzupelnienie-gotowe")
    # `uzupelnienie-odczyt-nieudany` already removed it.
    remove(lock, missing_ok=True)
    run.check(not lock.exists(), "harness: Dad closed Excel, so no lock file keeps Uruchom disabled")
    expected = _without_quantity(_ready(run, "uzupelnienie-gotowe-podsumowanie"))
    answer = _go_to_settlement(run, page, LAST_COMPLETE, "uzupelnienie-gotowe")
    run.check(
        answer == {"state": "read", "sentence": "2 wiersze bez ilości: 19, 20"} and expected == [19, 20],
        "the period's rows without quantity are 19 and 20, the summary's rows not done",
    )
    run.capture(page, "215-uzupelnienie-gotowe")

    run.step(FEATURE, "uzupelnienie-gotowe-potwierdzenie")
    page.get_by_role("button", name="Uruchom", exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    expect(confirm).to_contain_text("„Uruchom” potwierdza Gotowość Pliku zbiorczego")
    expect(confirm).to_contain_text("2 wiersze bez ilości: 19, 20")
    expect(confirm.get_by_role("button", name="Uruchom", exact=True)).to_be_enabled()
    run.check(True, "the confirm dialog lists the rows without quantity, and Dad may still start")
    run.capture(page, "216-uzupelnienie-gotowe-potwierdzenie")
    confirm.get_by_role("button", name="Anuluj", exact=True).click()
    expect(confirm).to_have_count(0)

    run.step(FEATURE, "uzupelnienie-gotowe-po-podgladzie")
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    live = page.get_by_role("region", name="Podgląd na żywo")
    expect(live).to_contain_text("Podgląd gotowy · nic nie zapisano")
    live.get_by_role("button", name="Uruchom", exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    expect(confirm).to_contain_text("2 wiersze bez ilości: 19, 20")
    expect(confirm.get_by_role("button", name="Uruchom", exact=True)).to_be_enabled()
    run.check(True, "after the preview, the result card's Uruchom dialog lists the same rows, Dad's usual path")
    run.capture(page, "218-uzupelnienie-gotowe-po-podgladzie")
    confirm.get_by_role("button", name="Anuluj", exact=True).click()
    expect(confirm).to_have_count(0)

    run.step(FEATURE, "uzupelnienie-gotowe-bez-odczytu")
    other = run.fixture["settlement"]["needs_check"]
    assert isinstance(other, str)
    other_file = Path(str(run.fixture["periods_directory"])) / other / f"Rozliczenie {other} - zbiorcze.xlsx"
    saved = read_bytes(other_file)
    try:
        other_file.write_bytes(b"to nie jest skoroszyt")
        run.check(True, f"harness: the Plik zbiorczy of {other} is damaged for this step and restored after it")
        page.goto(f"{run.url.rstrip('/')}/#/uzupelnienie/{other}")
        expect(page.get_by_role("main").get_by_text(other, exact=True)).to_be_visible()
        answer = _go_to_settlement(run, page, other, "uzupelnienie-gotowe-bez-odczytu")
        run.check(
            answer == {"state": "unread"},
            f"Gotowe on the summary of {other} selects it, not the preselected {LAST_COMPLETE}, and its rows "
            "without quantity answer although its Plik zbiorczy cannot be read",
        )
        page.get_by_role("button", name="Uruchom", exact=True).click()
        confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
        expect(confirm).to_contain_text("Nie udało się sprawdzić wierszy bez ilości")
        expect(confirm.get_by_role("button", name="Uruchom", exact=True)).to_be_enabled()
        run.check(True, "the dialog says the rows could not be checked instead of staying silent, and Dad may start")
        run.capture(page, "217-uzupelnienie-gotowe-bez-odczytu")
        confirm.get_by_role("button", name="Anuluj", exact=True).click()
    finally:
        other_file.write_bytes(saved)
    # The draft of the Przebieg form lives in the page; the next feature must start without it.
    page.goto(run.url)
    page.reload()

    _drive_after_settlement(run, page, collective_file)


def _row_colour(page: Page, state: str) -> str:
    """Background of the row number of the kind page's row in ``state``."""

    table = page.get_by_role("table", name="Wiersze Pliku zbiorczego", exact=True)
    colour = table.locator(f"tr[data-state='{state}'] th").evaluate("th => getComputedStyle(th).backgroundColor")
    assert isinstance(colour, str)
    return colour


def _on_screen(label: Locator) -> bool:
    """The words take real room on the screen: a screen-reader-only text is one pixel wide."""

    box = label.bounding_box()
    return box is not None and box["width"] >= 20 and box["height"] >= 6


def _drive_after_settlement(run: Run, page: Page, collective_file: Path) -> None:
    run.step(FEATURE, "uzupelnienie-po-przebiegu")
    page.goto(f"{run.url.rstrip('/')}/{SUMMARY}/without_rule")
    expect(page.get_by_role("rowheader", name="20 do uzupełnienia", exact=True)).to_be_visible()
    yellow = _row_colour(page, "to_fill")
    worker_settlements = collective_file.with_name(f"Rozliczenie pracowników {LAST_COMPLETE}")
    worker_settlements.mkdir()
    try:
        run.check(
            True,
            "harness: the Folder rozliczeń pracowników a Przebieg rozliczeń creates exists, removed after this step",
        )
        page.goto(run.url)
        expect(period_row(page, LAST_COMPLETE)).to_contain_text("Rozliczenia pracowników gotowe")
        page.goto(f"{run.url.rstrip('/')}/{SUMMARY}")
        expect(page.get_by_role("status").filter(has_text="Przebieg rozliczeń się odbył")).to_be_visible()
        answer = _ready(run, "uzupelnienie-po-przebiegu")
        run.check(
            answer["settled"] is True
            and _states(answer)
            == {"without_rule": [(18, "done"), (20, "without_quantity")], "from_description": [(19, "without_quantity")]},
            "after Przebieg the summary says so, Dad's row 18 stays done and rows 19 and 20 are without quantity",
        )
        _check_screen(run, page, answer, "after Przebieg")
        chips = [
            page.get_by_role("list", name=f"Numery wierszy: {KIND_TITLES[kind]}").get_by_role("listitem").filter(has_text=f"{row} bez ilości")
            for kind, row in (("without_rule", 20), ("from_description", 19))
        ]
        run.check(
            all(_on_screen(chip.get_by_text("bez ilości", exact=True)) for chip in chips),
            "rows 19 and 20 read „bez ilości” on the screen next to their number, not only for a screen reader",
        )
        expect(page.get_by_role("button", name="Gotowe, rozlicz pracowników", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True)).to_be_visible()
        expect(page.get_by_text("Nie widzisz zmian?")).to_have_count(0)
        run.check(True, "after Przebieg the summary is a preview: no Gotowe, no hint about saving, Otwórz Plik zbiorczy stays")
        run.capture(page, "253-uzupelnienie-po-przebiegu")

        page.get_by_role("region", name=KIND_TITLES["without_rule"], exact=True).get_by_role("link").click()
        table = page.get_by_role("table", name="Wiersze Pliku zbiorczego", exact=True)
        expect(table.get_by_role("rowheader")).to_have_text(["18 zrobiony", "20 bez ilości"])
        expect(page.get_by_role("status").filter(has_text="Przebieg rozliczeń się odbył")).to_be_visible()
        expect(page.get_by_role("main")).to_contain_text("Szare zostały bez ilości.")
        expect(page.get_by_text("Nie widzisz zmian?")).to_have_count(0)
        kind = _kind_answer(run, "without_rule", "uzupelnienie-po-przebiegu-tabela-without_rule")
        grey, green = _row_colour(page, "without_quantity"), _row_colour(page, "done")
        run.check(
            kind["settled"] is True and grey not in (yellow, green),
            f"row 20 is no longer yellow ({yellow} before Przebieg) but grey ({grey}), and not green like row 18",
        )
        run.check(
            _on_screen(table.get_by_role("rowheader", name="20 bez ilości").get_by_text("bez ilości", exact=True)),
            "row 20 reads „bez ilości” on the screen under its number",
        )
        _capture(run, page, "253-uzupelnienie-po-przebiegu-bez-reguly", kind)
        switched = switch_theme(page, "jasny")
        _capture(run, page, "253-uzupelnienie-po-przebiegu-bez-reguly-jasny", kind)
        if switched:
            switch_theme(page, "ciemny")
    finally:
        remove_empty_folder(worker_settlements)
    page.goto(run.url)


def _without_quantity(answer: dict[str, object]) -> list[int]:
    return sorted(row for rows in _rows(answer).values() for row, done in rows if not done)


def _go_to_settlement(run: Run, page: Page, period: str, name: str) -> dict[str, object]:
    """Clicks Gotowe on the summary: Przebieg rozliczeń with the period chosen; returns the server's answer on the period's rows without quantity."""

    page.get_by_role("button", name="Gotowe, rozlicz pracowników", exact=True).click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/#/uruchomienia")
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    expect(page.get_by_role("radio", name="Przebieg rozliczeń")).to_be_checked()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)
    processes = run.api("/api/runs/setup", name)["processes"]
    assert isinstance(processes, list)
    [setup] = [process for process in processes if process["process"] == "settlement"]
    run.check(
        processes[0]["process"] != "settlement"
        and setup["preselected_period"] == LAST_COMPLETE
        and period in [choice["token"] for choice in setup["periods"]],
        f"Gotowe chose Przebieg rozliczeń and {period}; without it the form shows the first process",
    )
    return run.api(f"/api/periods/{period}/without-quantity", f"{name}-wiersze")
