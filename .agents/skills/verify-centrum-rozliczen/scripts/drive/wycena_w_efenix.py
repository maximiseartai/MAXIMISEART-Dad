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
    ended_run_shown,
    finished_result,
    last_opened_is,
    period_choice,
)

FEATURE = "wycena-w-efenix"
PROCESS = "Wycena w efenix"
PERIOD = "08_14_09_2026"
COLLECTIVE_FILE = f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
LOGIN = "Zaloguj się w oknie efenix"
DONE = "Wycena w efenix gotowa · wymaga sprawdzenia"
# serve_centrum.EFENIX_ORDERS: row → (order number, Wykonawca); 18 is ready, 19 unknown to efenix, 20 differs from Emmett.
ORDERS = {18: ("QX9001", "adrian.testowy"), 19: ("QX9002", "beata.testowa"), 20: ("QX9003", "celina.testowa")}
# Znacznik efenix (rozliczenia.efenix_mark.MARK_RGB), the light purple of ADRES in a ready order's row.
MARK_RGB = "E0CCFF"

Json = dict[str, Any]


def _live(page: Page) -> Locator:
    return page.get_by_role("region", name="Podgląd na żywo")


def _logs(run: Run) -> list[Json]:
    directory = run.root / "logs" / "uruchomienia"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*-efenix-*.json"))]


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

    address = (run.root / "efenix" / "adres.txt").read_text(encoding="utf-8")
    login = address.rsplit("/", 1)[0] + "/page_login.php"
    print("  harness: Dad logs in to the Atrapa efenix (the form of page_login.php)", flush=True)
    request = urllib.request.Request(login, data=b"field_signum=tata&field_password=haslo", method="POST")
    with urllib.request.urlopen(request, timeout=10) as answer:
        answer.read()


def drive_efenix_pricing(run: Run, page: Page) -> None:
    run.step(FEATURE, "przycisk")
    settings = run.api("/api/settings", "efenix-ustawienia")
    if settings["periods_directory"] == {"state": "not_set"}:
        page.goto(run.url + "#/")
        choose_periods_directory(run, page)
    period_folder = Path(run.fixture["periods_directory"]) / PERIOD
    print(f"  harness: the Folder okresu {PERIOD} with a Plik zbiorczy of the Atrapa's orders, as after Uzupełnienie", flush=True)
    shutil.copytree(run.root / "efenix" / PERIOD, period_folder)
    source = period_folder / COLLECTIVE_FILE
    try:
        _price(run, page, source)
    finally:
        shutil.rmtree(period_folder)


def _price(run: Run, page: Page, source: Path) -> None:
    logs_before = len(_logs(run))
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    if ended_run_shown(current_run(run, "efenix-przed-karta")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name=PROCESS).click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=period_choice(PERIOD, "Plik zbiorczy przygotowany")).click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(PERIOD)
    expect(page.get_by_role("group", name="Plik zbiorczy")).to_contain_text(COLLECTIVE_FILE)
    expect(page.get_by_role("button", name="Podgląd bez zapisu")).to_have_count(0)
    setup = run.api("/api/runs/setup", "efenix-karta-startu")
    processes = setup["processes"]
    assert isinstance(processes, list)
    [efenix] = [process for process in processes if process["process"] == "efenix"]
    run.check(
        efenix["preview_hint"] is None and PERIOD in [period["token"] for period in efenix["periods"]],
        "the setup card offers Wycena w efenix for the period with a Plik zbiorczy, with Uruchom and no Podgląd bez zapisu",
    )
    run.capture(page, "260-efenix-karta-startu")

    run.step(FEATURE, "logowanie")
    page.get_by_role("button", name="Uruchom", exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    expect(confirm).to_contain_text(f"{PROCESS} · okres {PERIOD}")
    expect(confirm.get_by_text("Nie było podglądu bez zapisu")).to_have_count(0)
    confirm.get_by_role("button", name="Uruchom", exact=True).click()
    live = _live(page)
    expect(live.get_by_role("status", name="Krok")).to_have_text(LOGIN, timeout=30_000)
    waiting = current_run(run, "efenix-logowanie")
    progress = waiting["progress"]
    assert isinstance(progress, dict)
    other = urllib.request.Request(
        run.url.rstrip("/") + "/api/runs",
        data=json.dumps({"process": "settlement", "period": PERIOD, "dry_run": True}).encode(),
        method="POST",
        headers={"Origin": run.url.rstrip("/"), "Content-Type": "application/json"},
    )
    run.check(
        waiting["state"] == "running" and progress["step"]["label"] == LOGIN,
        "the Uruchomienie waits for Dad's login in the efenix window and says so on the card",
    )
    run.check(run.refused(other, "efenix-drugie-uruchomienie") == 409, "no other Uruchomienie starts while it waits")
    run.capture(page, "261-efenix-logowanie", live=True)
    _log_in(run)

    run.step(FEATURE, "postep")
    bar = live.get_by_role("progressbar", name="Zlecenia")
    expect(bar).to_be_visible(timeout=30_000)
    expect(live).to_contain_text("Zlecenia · ")
    step = current_run(run, "efenix-postep")["progress"]
    assert isinstance(step, dict)
    run.check(
        step["step"] is None or step["step"]["total"] in (0, len(ORDERS)),
        "the live progress counts the orders of the Plik zbiorczy with the current Wykonawca",
    )
    run.capture(page, "262-efenix-postep", live=True)

    run.step(FEATURE, "karta")
    result: Json = finished_result(run, "efenix-wynik")
    expect(page.get_by_label("Wynik")).to_contain_text(DONE, timeout=30_000)
    toast = page.get_by_role("region", name="Notifications").get_by_role("dialog", name=DONE)
    expect(toast).to_contain_text(f"Okres {PERIOD}")
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    skipped = {count["label"]: count["count"] for count in result["summary"]["counts"]["counts"]}
    run.check(
        (result["result"], figures, skipped)
        == (
            "WYMAGA_SPRAWDZENIA",
            {"Zlecenia w zakresie": 3, "Gotowe do przekazania": 1, "Błędy zleceń": 1, "Ostrzeżenia Emmetta": 1},
            {"Ze zdjęciami": 0, "Usterki": 0, "Nieznalezione w efenix": 1},
        ),
        "the card counts the ready, the errors, Emmett's warnings and the skipped orders",
    )
    for title, row in (("Błędy", 19), ("Ostrzeżenia Emmetta", 20)):
        table = page.get_by_role("table", name=title)
        number, worker = ORDERS[row]
        expect(table.get_by_role("row")).to_have_count(1)
        expect(table.get_by_role("row").first.get_by_role("cell").nth(0)).to_have_text(f"wiersz {row}")
        expect(table.get_by_role("row").first.get_by_role("cell").nth(1)).to_have_text(number)
        expect(table.get_by_role("row").first.get_by_role("cell").nth(2)).to_have_text(worker)
    expect(page.get_by_role("table", name="Błędy")).to_contain_text("efenix nie zna zlecenia o numerze z NUMER ZL.")
    expect(page.get_by_role("table", name="Ostrzeżenia Emmetta")).to_contain_text("Emmett 2, plik 1")
    run.check(True, "the card lists each error and warning with its row, order number, Wykonawca and sentence, and a toast")
    run.capture(page, "263-efenix-karta")

    run.step(FEATURE, "plik-i-logi")
    fills = _address_fills(source)
    run.check(fills == {18: MARK_RGB, 19: None, 20: None}, "only the ready order's ADRES has the Znacznik efenix")
    board = run.api("/api/periods", "efenix-status-okresu")["periods"]
    assert isinstance(board, list)
    run.check(
        [row["status"] for row in board if row["token"] == PERIOD] == ["collective_file_prepared"],
        "the Status okresu stays Plik zbiorczy przygotowany",
    )
    logs = _logs(run)
    run.check(len(logs) == logs_before + 1, "the Uruchomienie wrote one file of Logi Uruchomienia of efenix")
    record = logs[-1]
    text = json.dumps(record, ensure_ascii=False)
    traced = [(order["row"], order["outcome"]) for order in record["efenix_orders"]]
    private = [marker for number, worker in ORDERS.values() for marker in (number, worker) if marker in text]
    run.check(
        traced == [(18, "gotowe"), (19, "błąd"), (20, "ostrzeżenie Emmetta")] and private == [],
        "the Logi trace every order by its row, without its order number or the Wykonawca's login",
    )
    live.get_by_role("button", name="Otwórz Plik zbiorczy").click()
    run.wait_for(last_opened_is(run, source), "Otwórz Plik zbiorczy opens it")
    run.check(True, "Otwórz Plik zbiorczy opens the Plik zbiorczy with the Znaczniki efenix")
