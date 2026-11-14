"""Drive features/wycena-w-efenix.md."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any
import urllib.request

from openpyxl import load_workbook
from playwright.sync_api import Locator, Page, expect

from drive.common import (
    Run,
    choose_periods_directory,
    current_run,
    finished_result,
    last_opened_is,
    open_setup,
    period_choice,
    read_text,
    remove_tree,
    result_of_start,
    run_logs,
    start_new,
    stop_banner,
)
from drive.teksty import BELL_FRESH
from drive.waiting import Budget, until
from atrapy.efenix import FIRST_ROW, SOURCE_NAME
from atrapy.scenariusz_centrum import EFENIX_ADDRESS_MARKERS, EFENIX_ORDERS, EFENIX_PERIOD
from harness import File, efenix_files

FEATURE = "wycena-w-efenix"
PROCESS = "Wycena w efenix"
PERIOD = EFENIX_PERIOD
COLLECTIVE_FILE = SOURCE_NAME
LOGIN = "Zaloguj się w oknie efenix"
DONE = "Wycena w efenix gotowa · wymaga sprawdzenia"
# Row → (order number, Wykonawca) of EFENIX_ORDERS; 18 is ready, 19 unknown to efenix, 20 differs from Emmett,
# 21 is „Rozliczone” in efenix.
ORDERS = {
    row: (order.number.removeprefix("#"), order.worker) for row, order in enumerate(EFENIX_ORDERS, start=FIRST_ROW)
}
# Znacznik efenix, the light purple of ADRES in a ready order's row, and the Znacznik przekazania, the darker purple of
# an order the Wycena with Przekazanie forwarded to acceptance: the colours of ADR 0027, a deliberate copy
# (docs/agents/skille.md, „Co wyrocznia bierze z src”) and not taken from rozliczenia.efenix_mark, because the tests take
# them from there and this drive is what checks them.
MARK_RGB = "E0CCFF"
FORWARDED_RGB = "B48AFF"
# The two buttons of the setup card in Dad's words, „zapis” being the green „Zapisz” in efenix, with their captions.
FILL = "Uzupełnij bez zapisu"
FORWARD = "Uzupełnij i zapisz"
FILL_HINT = "Zielony „Zapisz” w efenix klikasz sam"
FORWARD_HINT = "Zielony „Zapisz” przy gotowych klika Centrum"
DONE_OK_FORWARDED = "Przekazane do akceptacji"
# The tab sends the next start request this late, once: the server still shows the Wycena before it, finished, when the
# drive reads it first, as on the Windows runner of CI on main 5f6940a61 (#1570), and not only there.
LATE_START_MS = 1500
LATE_START = """delay => {
    const send = window.fetch
    window.fetch = (input, init) => {
        // Read without new Request(input): it would take the body of a Request passed as input.
        const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase()
        const url = new URL(input instanceof Request ? input.url : String(input), location.href)
        if (method !== "POST" || url.pathname !== "/api/runs") return send(input, init)
        window.fetch = send
        window.startSentLate = true
        return new Promise(resolve => setTimeout(resolve, delay)).then(() => send(input, init))
    }
}"""

Json = dict[str, Any]


def _live(page: Page) -> Locator:
    return page.get_by_role("region", name="Podgląd na żywo")


def _logs(run: Run) -> list[Json]:
    return list(run_logs(run, "efenix").values())


def _address_fills(source: Path) -> dict[int, str | None]:
    workbook = load_workbook(source)
    try:
        sheet = workbook.active
        assert sheet is not None
        fills: dict[int, str | None] = {}
        for row in ORDERS:
            fill = sheet[f"B{row}"].fill
            fills[row] = str(fill.fgColor.rgb)[-6:].upper() if fill.fill_type == "solid" else None
        return fills
    finally:
        workbook.close()


def _log_in(run: Run) -> None:
    """Harness: Dad logs in to efenix in the window Centrum opened (the Atrapa's login form, posted from here)."""

    address = read_text(File.EFENIX_ADDRESS.file(run.root))
    # The form of page_login.php posts to action_login.php with a hidden fingerprint, as in efenix.
    login = address.rsplit("/", 1)[0] + "/action_login.php"
    print("  harness: Dad logs in to the Atrapa efenix (the login form, posted to action_login.php)", flush=True)
    request = urllib.request.Request(login, data=b"field_signum=tata&field_password=haslo&fingerprint=", method="POST")
    with urllib.request.urlopen(request, timeout=Budget.SCREEN.value) as answer:
        answer.read()


def drive(run: Run, page: Page) -> None:
    run.step(FEATURE, "przycisk")
    settings = run.api("/api/settings", "efenix-ustawienia")
    if settings["periods_directory"] == {"state": "not_set"}:
        page.goto(run.url + "#/")
        choose_periods_directory(run, page)
    period_folder = Path(run.fixture["periods_directory"]) / PERIOD
    print(f"  harness: the Folder okresu {PERIOD} with a Plik zbiorczy of the Atrapa's orders, as after Uzupełnienie", flush=True)
    shutil.copytree(efenix_files(run.root) / PERIOD, period_folder)
    source = period_folder / COLLECTIVE_FILE
    try:
        _price(run, page, source)
    finally:
        remove_tree(period_folder)


def _price(run: Run, page: Page, source: Path) -> None:
    logs_before = len(_logs(run))
    open_setup(run, page, PROCESS, "efenix-karta", period=(PERIOD, "Plik zbiorczy przygotowany"))
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(PERIOD)
    expect(page.get_by_role("group", name="Plik zbiorczy")).to_contain_text(COLLECTIVE_FILE)
    expect(page.get_by_role("button", name="Podgląd bez zapisu")).to_have_count(0)
    expect(page.get_by_role("button", name="Uruchom", exact=True)).to_have_count(0)
    fill, forward = (page.get_by_role("button", name=name, exact=True) for name in (FILL, FORWARD))
    expect(fill).to_have_accessible_description(FILL_HINT)
    expect(forward).to_have_accessible_description(FORWARD_HINT)
    setup = run.api("/api/runs/setup", "efenix-karta-startu")
    processes = setup["processes"]
    assert isinstance(processes, list)
    [efenix] = [process for process in processes if process["process"] == "efenix"]
    run.check(
        efenix["preview_hint"] is None
        and efenix["pricing_modes"] == ["bez Przekazania", "z Przekazaniem"]
        and PERIOD in [period["token"] for period in efenix["periods"]],
        "the setup card offers Wycena w efenix for the period with a Plik zbiorczy, with the two modes and no Podgląd "
        "bez zapisu",
    )
    boxes = [button.bounding_box() for button in (fill, forward)]
    assert boxes[0] is not None and boxes[1] is not None
    looks = [button.get_attribute("class") or "" for button in (fill, forward)]
    run.check(
        looks[0] == looks[1]
        and "bg-primary" not in looks[0]
        and (boxes[0]["y"], boxes[0]["width"], boxes[0]["height"]) == (boxes[1]["y"], boxes[1]["width"], boxes[1]["height"])
        and boxes[0]["x"] < boxes[1]["x"],
        "the two buttons stand side by side with one look and size, and neither is the primary one",
    )
    run.capture(page, "260-efenix-karta-startu")

    run.step(FEATURE, "logowanie")
    fill.click()
    confirm = page.get_by_role("alertdialog", name="Uzupełnić bez zapisu?")
    expect(confirm).to_contain_text(f"{PROCESS} · okres {PERIOD}")
    expect(confirm).to_contain_text(FILL_HINT)
    expect(confirm.get_by_text("Nie było podglądu bez zapisu")).to_have_count(0)
    confirm.get_by_role("button", name=FILL, exact=True).click()
    live = _live(page)
    expect(live.get_by_role("status", name="Krok")).to_have_text(LOGIN, timeout=Budget.WORK.ms)
    waiting = current_run(run, "efenix-logowanie")
    progress = waiting["progress"]
    assert isinstance(progress, dict)
    started = waiting["run"]
    assert isinstance(started, dict)
    run.check(
        waiting["state"] == "running" and progress["step"]["label"] == LOGIN and started["pricing"] == "bez Przekazania",
        "the Uruchomienie without Przekazanie waits for Dad's login in the efenix window and says so on the card",
    )
    other = {"process": "settlement", "period": PERIOD, "mode": "DRY-RUN"}
    run.check(
        run.post("/api/runs", "efenix-drugie-uruchomienie", other).status == 409,
        "no other Uruchomienie starts while it waits",
    )
    run.capture(page, "261-efenix-logowanie", live=True)
    _log_in(run)

    run.step(FEATURE, "postep")
    bar = live.get_by_role("progressbar", name="Zlecenia")
    expect(bar).to_be_visible(timeout=Budget.WORK.ms)
    expect(live).to_contain_text("Zlecenia · ")
    step = current_run(run, "efenix-postep")["progress"]
    assert isinstance(step, dict)
    run.check(
        step["step"] is None or step["step"]["total"] in (0, len(ORDERS)),
        "the live progress counts the orders of the Plik zbiorczy with the current Wykonawca",
    )
    run.capture(page, "262-efenix-postep", live=True)

    run.step(FEATURE, "karta")
    result: Json = finished_result(run, "efenix-wynik", timeout_s=Budget.BACKGROUND)
    expect(page.get_by_label("Wynik")).to_contain_text(DONE, timeout=Budget.WORK.ms)
    toast = page.get_by_role("region", name="Notifications").get_by_role("dialog", name=DONE)
    expect(toast).to_contain_text(f"Okres {PERIOD}")
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    skipped = {count["label"]: count["count"] for count in result["summary"]["counts"]["counts"]}
    run.check(
        (result["result"], figures, skipped)
        == (
            "WYMAGA_SPRAWDZENIA",
            {
                "Zlecenia w zakresie": 4,
                "Gotowe do przekazania": 1,
                DONE_OK_FORWARDED: 0,
                "Rozliczone": 1,
                "Błędy zleceń": 1,
                "Ostrzeżenia Emmetta": 1,
            },
            {"Ze zdjęciami": 0, "Usterki": 0, "Nieznalezione w efenix": 1},
        ),
        "the card counts the ready, the settled, the errors, Emmett's warnings and the skipped orders",
    )
    for title, row in (("Błędy zleceń", 19), ("Ostrzeżenia Emmetta", 20), ("Rozliczone", 21)):
        table = page.get_by_role("table", name=title)
        number, worker = ORDERS[row]
        expect(table.get_by_role("row")).to_have_count(1)
        expect(table.get_by_role("row").first.get_by_role("cell").nth(0)).to_have_text(f"wiersz {row}")
        expect(table.get_by_role("row").first.get_by_role("cell").nth(1)).to_have_text(number)
        expect(table.get_by_role("row").first.get_by_role("cell").nth(2)).to_have_text(worker)
    expect(page.get_by_role("table", name="Błędy zleceń")).to_contain_text("efenix nie zna zlecenia o numerze z NUMER ZL.")
    expect(page.get_by_role("table", name="Ostrzeżenia Emmetta")).to_contain_text("efenix 2, plik 1")
    expect(page.get_by_role("table", name="Rozliczone").get_by_role("row").first.get_by_role("cell").nth(3)).to_have_text("")
    expect(page.get_by_role("table", name=DONE_OK_FORWARDED)).to_have_count(0)
    run.check(
        True,
        "the card lists each error and warning with its row, order number, Wykonawca and sentence, each Zlecenie "
        "rozliczone with its row, order number and Wykonawca, and a toast",
    )
    _one_mode_word(run, live, "Bez zapisu")
    _labels_in_one_line(run, live)
    run.capture(page, "263-efenix-karta")

    run.step(FEATURE, "plik-i-logi")
    fills = _address_fills(source)
    run.check(
        fills == {18: MARK_RGB, 19: None, 20: None, 21: None},
        "only the ready order's ADRES has the Znacznik efenix, the Zlecenie rozliczone's has none",
    )
    board = run.api("/api/periods", "efenix-status-okresu")["periods"]
    assert isinstance(board, list)
    run.check(
        [row["status"] for row in board if row["token"] == PERIOD] == ["collective_file_prepared"],
        "the Status okresu stays Plik zbiorczy przygotowany",
    )
    [priced] = [row for row in board if row["token"] == PERIOD]
    run.check(
        [step["stage"] for step in priced["path"]] == ["done", "done", "now", "later"]
        and (priced["next_step"]["action"], priced["secondary_step"]["action"])
        == ("price_in_efenix", "create_worker_settlements"),
        "a Wycena w efenix that needs checking leaves its step of the Droga okresu current and the next step, with "
        "Przebieg rozliczeń reachable beside it",
    )
    logs = _logs(run)
    run.check(len(logs) == logs_before + 1, "the Uruchomienie wrote one file of Logi Uruchomienia of efenix")
    record = logs[-1]
    trace = json.dumps(record["efenix_orders"], ensure_ascii=False)
    whole = json.dumps(record, ensure_ascii=False)
    traced = [(order["row"], order["outcome"]) for order in record["efenix_orders"]]
    private = [number for number, _worker in ORDERS.values() if number in trace]
    private += [address for address in EFENIX_ADDRESS_MARKERS if address in whole]
    run.check(
        traced == [(18, "gotowe"), (19, "błąd"), (20, "ostrzeżenie Emmetta"), (21, "rozliczone")] and private == [],
        "the Logi trace every order by its row, the Zlecenie rozliczone as rozliczone, the trace without its order "
        "number, and no part of the Logi has the address",
    )
    copied = {row["row"]: row["cells"] for file in record["input_copy"] for sheet in file["sheets"] for row in sheet["rows"]}
    run.check(
        sorted(copied) == sorted(ORDERS)
        and all(number in str(copied[row].get("F")) and copied[row].get("H") == worker for row, (number, worker) in ORDERS.items())
        and all("B" not in cells for cells in copied.values()),
        "the Kopia wejścia of the Logi holds rows 18–21 of the Plik zbiorczy with NUMER ZL. and WYKONAWCA, without ADRES",
    )
    steps = {order["row"]: order["steps"] for order in record["efenix_orders"]}
    opened = steps[18][1]
    run.check(
        (steps[19][0]["found"], steps[19][0]["results"]) == (0, [])
        and steps[21][0]["results"] == [{"same_number": True, "status": "Rozliczone", "realizator": ORDERS[21][1], "address": []}]
        and (opened["action"], opened["status"], opened["realizator"], opened["quantities"]["012"])
        == ("otwarcie zlecenia", "Do wyceny", ORDERS[18][1], 0),
        "the Logi read every efenix page (#843): the search results with status, realizator and differing address parts, "
        "and the opened order's status, realizator and every position's quantity",
    )
    live.get_by_role("button", name="Otwórz Plik zbiorczy").click()
    until(last_opened_is(run, source), "Otwórz Plik zbiorczy opens it")
    run.check(True, "Otwórz Plik zbiorczy opens the Plik zbiorczy with the Znaczniki efenix")
    _notification(run, page, result)
    _forward(run, page, source)
    _rerun_after_stop(run, page, source)


def _one_mode_word(run: Run, live: Locator, badge: str) -> None:
    """The card of a Wycena names its mode with one meaning of „zapis”, the green „Zapisz” in efenix."""

    expect(live.get_by_text(badge, exact=True)).to_be_visible()
    other = "Z zapisem" if badge == "Bez zapisu" else "Bez zapisu"
    expect(live.get_by_text(other, exact=True)).to_have_count(0)
    run.check(True, f"the card has the badge {badge} and no other word of „zapis” for its mode")


def _labels_in_one_line(run: Run, live: Locator) -> None:
    """#1067 saw „Przekazane do akceptacji” break into two lines in the strip of figures of the card."""

    heights = {
        label: box["height"]
        for label in (DONE_OK_FORWARDED, "Rozliczone")
        if (box := live.get_by_role("term").filter(has_text=label).first.bounding_box()) is not None
    }
    run.check(
        len(heights) == 2 and heights[DONE_OK_FORWARDED] == heights["Rozliczone"],
        "the label Przekazane do akceptacji stands in one line, as high as Rozliczone",
    )


def _forward(run: Run, page: Page, source: Path) -> None:
    """A second Wycena of the same period with „Uzupełnij i zapisz”: the ready order of the first one is forwarded."""

    run.step(FEATURE, "z-zapisem")
    live = _live(page)
    page.goto(run.url + "#/uruchomienia")
    expect(live).to_be_visible()
    live.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name=PROCESS).click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=period_choice(PERIOD, "Plik zbiorczy przygotowany")).click()
    page.get_by_role("button", name=FORWARD, exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uzupełnić i zapisać?")
    expect(confirm).to_contain_text(FORWARD_HINT)
    run.capture(page, "267-efenix-z-zapisem-potwierdzenie")
    page.evaluate(LATE_START, LATE_START_MS)
    first = start_new(run, "efenix-z-zapisem", confirm.get_by_role("button", name=FORWARD, exact=True).click)
    print(f"  harness: the tab sends the start request {LATE_START_MS} ms after the click", flush=True)
    # The window of the first Wycena kept Dad's session in its profile; it asks for the login only when it lost it.
    asks = [False]

    def login_or_end() -> bool:
        view = current_run(run, "efenix-z-zapisem-start")
        # Only another id than the first Wycena's is this one (start_new), so the wait for the end below is its own.
        if view.get("run", {}).get("id") in (None, first):
            return False
        progress = view.get("progress")
        step = progress.get("step") if isinstance(progress, dict) else None
        asks[0] = isinstance(step, dict) and step.get("label") == LOGIN
        return asks[0] or view["state"] == "finished" or (isinstance(step, dict) and step.get("total", 0) > 0)

    until(login_or_end, "the Wycena with Przekazanie asks for the login or works", Budget.WORK)
    run.check(page.evaluate("() => window.startSentLate === true"), "harness: the start request left the tab late")
    if asks[0]:
        _log_in(run)
    result: Json = finished_result(run, "efenix-z-zapisem-wynik", timeout_s=Budget.BACKGROUND)
    shown = current_run(run, "efenix-z-zapisem-karta")["run"]
    assert isinstance(shown, dict)
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    run.check(
        (shown["pricing"], figures["Gotowe do przekazania"], figures[DONE_OK_FORWARDED], figures["Rozliczone"])
        == ("z Przekazaniem", 0, 1, 1),
        "the Wycena with Przekazanie forwards the ready order: none ready, one forwarded, the settled one stays",
    )
    expect(page.get_by_label("Wynik")).to_contain_text(DONE, timeout=Budget.WORK.ms)
    table = page.get_by_role("table", name=DONE_OK_FORWARDED)
    number, worker = ORDERS[18]
    expect(table.get_by_role("row")).to_have_count(1)
    expect(table.get_by_role("row").first.get_by_role("cell")).to_have_text(["wiersz 18", number, worker, ""])
    _one_mode_word(run, live, "Z zapisem")
    _labels_in_one_line(run, live)
    run.capture(page, "268-efenix-z-zapisem-karta")
    run.check(
        _address_fills(source) == {18: FORWARDED_RGB, 19: None, 20: None, 21: None},
        "the forwarded order's ADRES has the Znacznik przekazania instead of the Znacznik efenix",
    )
    record = _logs(run)[-1]
    run.check(
        (record["pricing"], [(order["row"], order["outcome"]) for order in record["efenix_orders"]])
        == ("z Przekazaniem", [(18, "przekazane"), (19, "błąd"), (20, "ostrzeżenie Emmetta"), (21, "rozliczone")]),
        "the Logi have the mode in their start facts and trace the forwarded order as przekazane",
    )
    answer = run.api("/api/notifications", "efenix-z-zapisem-powiadomienia")
    items = answer["items"]
    assert isinstance(items, list)
    [notification] = [item for item in items if item["kind"] == "wycena_w_efenix" and item["run_id"] == shown["id"]]
    run.check(
        (notification["pricing"], notification["orders"])
        == (
            "z Przekazaniem",
            [
                {"label": "Gotowe do przekazania", "count": 0},
                {"label": DONE_OK_FORWARDED, "count": 1},
                {"label": "Rozliczone", "count": 1},
                {"label": "Błędy zleceń", "count": 1},
                {"label": "Ostrzeżenia Emmetta", "count": 1},
            ],
        ),
        "the Powiadomienie has the mode and counts the forwarded order",
    )
    page.locator("header").get_by_role("button", name="Powiadomienia", exact=False).click()
    row = page.get_by_role("list", name="Powiadomienia").get_by_role("listitem").first
    expect(row.get_by_text("Z zapisem", exact=True)).to_be_visible()
    expect(row.get_by_role("term")).to_have_text(
        ["Gotowe do przekazania", DONE_OK_FORWARDED, "Rozliczone", "Błędy zleceń", "Ostrzeżenia Emmetta"]
    )
    expect(row.get_by_role("definition")).to_have_text(["0", "1", "1", "1", "1"])
    run.check(True, "the Powiadomienie row names the mode and the forwarded count")
    run.capture(page, "269-efenix-z-zapisem-powiadomienie")


def _notification(run: Run, page: Page, result: Json) -> None:
    """The Powiadomienie under the bell, which Dad finds when he comes back to Centrum after the Wycena."""

    run.step(FEATURE, "powiadomienie")
    shown = current_run(run, "efenix-po-wyniku")["run"]
    assert isinstance(shown, dict)
    bell = page.locator("header").get_by_role("button", name="Powiadomienia", exact=False)
    expect(bell).to_have_accessible_name(BELL_FRESH)
    answer = run.api("/api/notifications", "efenix-powiadomienia")
    items = answer["items"]
    assert isinstance(items, list)
    [notification] = [item for item in items if item["kind"] == "wycena_w_efenix" and item["run_id"] == shown["id"]]
    run.check(
        notification["unread"] is True
        and (notification["headline"], notification["period"], notification["orders"], notification["stopped"])
        == (
            result["headline"],
            PERIOD,
            [
                {"label": "Gotowe do przekazania", "count": 1},
                {"label": DONE_OK_FORWARDED, "count": 0},
                {"label": "Rozliczone", "count": 1},
                {"label": "Błędy zleceń", "count": 1},
                {"label": "Ostrzeżenia Emmetta", "count": 1},
            ],
            None,
        )
        and notification["pricing"] == "bez Przekazania",
        "the ended Wycena is a new Powiadomienie with the result, the period and the ready, settled, error and warning "
        "counts",
    )
    run.capture(page, "264-efenix-dzwonek")
    bell.click()
    expect(page.get_by_role("heading", name="Powiadomienia", exact=True)).to_be_visible()
    row = page.get_by_role("list", name="Powiadomienia").get_by_role("listitem", name=f"{PROCESS}: {DONE}", exact=True)
    expect(row).to_have_count(1)
    expect(row.get_by_label("nowe", exact=True)).to_be_visible()
    expect(row).to_contain_text(f"Okres {PERIOD}")
    counts = row.get_by_role("definition")
    expect(counts).to_have_text(["1", "0", "1", "1", "1"])
    expect(row.get_by_role("term")).to_have_text(
        ["Gotowe do przekazania", DONE_OK_FORWARDED, "Rozliczone", "Błędy zleceń", "Ostrzeżenia Emmetta"]
    )
    expect(row.get_by_text("Bez zapisu", exact=True)).to_be_visible()
    run.capture(page, "265-efenix-powiadomienie")
    row.get_by_role("button", name="Karta Uruchomienia", exact=True).click()
    sheet = page.get_by_role("dialog")
    expect(sheet.get_by_label("Wynik")).to_contain_text(DONE)
    run.check(True, "the Powiadomienie opens the card of this Uruchomienie from its Logi in the side panel")
    run.capture(page, "266-efenix-powiadomienie-karta")
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    until(
        lambda: run.api("/api/notifications", "efenix-powiadomienia-przeczytane")["unread"] == 0,
        "entering the view marks the Powiadomienie read",
    )


def _rerun_after_stop(run: Run, page: Page, source: Path) -> None:
    """„Uruchom ponownie” after a stopped Wycena opens the setup card with its process and period and starts nothing,
    because Dad picks the mode at every start (ADR 0027)."""

    run.step(FEATURE, "uruchom-ponownie")
    print("  harness: the Plik zbiorczy saved without Excel, so no Kwota (AU) has a computed value", flush=True)
    workbook = load_workbook(source)
    try:
        workbook.save(source)
    finally:
        workbook.close()
    live = _live(page)
    page.goto(run.url + "#/uruchomienia")
    expect(live).to_be_visible()
    live.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name=PROCESS).click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=period_choice(PERIOD, "Plik zbiorczy przygotowany")).click()
    page.get_by_role("button", name=FILL, exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uzupełnić bez zapisu?").get_by_role("button", name=FILL, exact=True)
    result = result_of_start(run, "efenix-zatrzymanie", confirm.click)
    stopped = current_run(run, "efenix-zatrzymanie-karta")["run"]
    assert isinstance(stopped, dict)
    rerun = stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)
    expect(rerun).to_be_visible()
    run.check(
        (result["ending"], stopped["process"], stopped["period"]) == ("stop", "efenix", PERIOD),
        "the Wycena of a Plik zbiorczy without the computed Kwota (AU) stops and offers Uruchom ponownie",
    )
    rerun.click()
    expect(page.get_by_role("radio", name=PROCESS)).to_be_checked()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(PERIOD)
    for name in (FILL, FORWARD):
        expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()
    expect(page.get_by_role("alertdialog")).to_have_count(0)
    after = current_run(run, "efenix-po-uruchom-ponownie")
    shown = after.get("run")
    run.check(
        after["state"] == "finished" and isinstance(shown, dict) and shown["id"] == stopped["id"],
        "Uruchom ponownie of a Wycena opens the setup card with Wycena w efenix and its period, and starts nothing",
    )
    run.capture(page, "270-efenix-uruchom-ponownie")
