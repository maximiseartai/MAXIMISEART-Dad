"""Drive features/przebieg-rozliczen.md."""

from __future__ import annotations

import json
from pathlib import Path
import re

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import Page, expect

from drive.common import (
    FOCUS,
    Run,
    active_run_signs,
    current_run,
    figure,
    finished_result,
    history_rows,
    last_opened_is,
    next_step_names_current_step,
    period_choice,
    period_files,
    period_row,
    priced_in_efenix,
    read_bytes,
    remove,
    start_card_warns_while_open,
    stop_banner,
)
from drive.waiting import Budget, until
from harness import Log, Pace
from atrapy.scenariusz_centrum import LAST_COMPLETE, ROW_MARKER, UNKNOWN_WORKER
from atrapy.workbooks import excel_lock

SETTLEMENT = "przebieg-rozliczen"
WORKER_SETTLEMENTS = f"Rozliczenie pracowników {LAST_COMPLETE}"
# serve_centrum.py waits this long before each Szablon pracownika while the pacing file exists.
TEMPLATE_PACING_MS = 2500
# Where Dad types quantities in his Plik zbiorczy: a deliberate copy (docs/agents/skille.md, „Co wyrocznia bierze z
# src”) and not rozliczenia.collective_layout, because the drive plays Dad and the fixture builds his files by hand.
WORKER_COLUMN, QUANTITY_COLUMN, FIRST_DATA_ROW = 8, 14, 18  # H (WYKONAWCA), N (first quantity), row 18
NAMES_ROW = re.compile(r"\bWiersz \d+\b")
REMINDER = "Zapisz i zamknij Plik zbiorczy w Excelu"
# Counts Dad's returns to the window, so a step can show that a new read came without one.
COUNT_RETURNS = (
    "() => { window.__returns = 0; const count = () => window.__returns++;"
    " window.addEventListener('focus', count); document.addEventListener('visibilitychange', count) }"
)


def _settlement_records(run: Run, name: str) -> list[dict[str, object]]:
    """Valid records of the Przebieg rozliczeń metrics file as the server reads them, newest first."""

    runs = run.api("/api/metrics", name)["runs"]
    assert isinstance(runs, list)
    return [entry for entry in runs if entry["process"] == "settlement"]


def _fill_readiness(collective_file: Path) -> int:
    """Gotowość as Dad reaches it in Excel: a quantity in N of every Wiersz danych, saved and closed.

    Excel is not driven; the harness edits the workbook like Dad would and leaves no lock file.
    Returns the number of filled Wiersze danych, never a cell value.
    """

    workbook = load_workbook(collective_file)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    filled = 0
    for row in range(FIRST_DATA_ROW, sheet.max_row + 1):
        if sheet.cell(row, WORKER_COLUMN).value:
            sheet.cell(row, QUANTITY_COLUMN).value = 1
            filled += 1
    workbook.save(collective_file)
    return filled


def _setup_choice(run: Run, name: str) -> dict[str, object]:
    processes = run.api("/api/runs/setup", name)["processes"]
    assert isinstance(processes, list)
    [setup] = [process for process in processes if process["process"] == "settlement"]
    [choice] = [choice for choice in setup["periods"] if choice["token"] == LAST_COMPLETE]
    assert isinstance(choice, dict)
    return choice


def _template_lock_left_behind(run: Run, page: Page) -> None:
    """A lock file left by Excel next to the Wzorzec rozliczenia pracownika, then deleted while a result is shown.

    The footer does not send Dad to the Plik zbiorczy, which does not block, and „Nowe Uruchomienie procesu” reads
    the files again without Dad's return to the window.
    """

    template = Path(run.fixture["configuration"]["worker_template"])
    lock = excel_lock(template)
    warning = (
        "Wzorzec rozliczenia pracownika jest otwarty w Excelu. Zamknij go bez zapisywania zmian. Jeśli Excel jest "
        f"zamknięty, usuń z tego samego folderu pozostawiony plik {lock.name}."
    )
    warned = page.get_by_role("alert").filter(has_text=warning)
    start = page.get_by_role("button", name="Uruchom", exact=True)
    reminder = page.get_by_text(REMINDER, exact=True)

    lock.touch()
    print(f"  harness: Excel crashed and left {lock.name} next to the Wzorzec; Dad returns to Centrum", flush=True)
    try:
        page.evaluate(FOCUS)
        expect(warned).to_have_text(warning)
        expect(start).to_be_disabled()
        expect(reminder).to_have_count(0)
        choice = _setup_choice(run, "przebieg-wzorzec-otwarty-w-excelu")
        run.check(
            (choice["open_in_excel"], choice["reminder"]) == ([warning], None),
            "only the Wzorzec blocks Uruchom, so the footer does not tell Dad to close the Plik zbiorczy",
        )
        run.capture(page, "4c-przebieg-wzorzec-otwarty-w-excelu")

        # The card reads the files again once the Uruchomienie ends; that read must see the lock file, not race it.
        with page.expect_response(lambda response: response.url.endswith("/api/runs/setup")):
            page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(stop_banner(page)).to_contain_text(f"pozostawiony plik {lock.name}")
        page.evaluate(COUNT_RETURNS)
    finally:
        remove(lock, missing_ok=True)
    print(f"  harness: Dad deletes {lock.name} while Centrum keeps the focus", flush=True)
    page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(LAST_COMPLETE)
    expect(warned).to_have_count(0)
    expect(start).to_be_enabled()
    expect(reminder).to_be_visible()
    choice = _setup_choice(run, "przebieg-wzorzec-zamkniety")
    run.check(
        page.evaluate("() => window.__returns") == 0 and (choice["open_in_excel"], choice["reminder"]) == ([], REMINDER),
        "Nowe Uruchomienie procesu shows the files as they are now, without Dad's return to the window",
    )
    run.capture(page, "4d-przebieg-nowe-uruchomienie-bez-blokady")


def drive(run: Run, page: Page) -> None:
    feature = SETTLEMENT
    internal_settlement, collective_file = period_files(run)
    period_folder = collective_file.parent
    worker_settlements = period_folder / WORKER_SETTLEMENTS
    workers = run.fixture["workers"]
    files = [f"Rozliczenie {LAST_COMPLETE} - {worker}.xlsx" for worker in workers]
    orders = run.fixture["settlement"]["rows_per_worker"]
    expected_settlements = [
        {"worker": worker, "file": file, "orders": count, "empty": count == 0}
        for worker, file, count in zip(workers, files, orders, strict=True)
    ]
    [empty_worker] = [worker for worker, count in zip(workers, orders, strict=True) if count == 0]
    needs_check = run.fixture["settlement"]["needs_check"]

    run.step(feature, "przebieg-gotowosc")
    filled = _fill_readiness(collective_file)
    run.check(
        filled == len(workers) - 1 and not excel_lock(collective_file).exists(),
        "Gotowość (Excel simulated by the harness): quantities typed into every Wiersz danych, saved and closed",
    )

    run.step(feature, "przebieg-wybor-okresu")
    page.goto(run.url)
    page.get_by_role("button", name=f"Utwórz rozliczenia pracowników, okres {LAST_COMPLETE}", exact=True).click()
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    expect(page.get_by_role("radio", name="Przebieg rozliczeń")).to_be_checked()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period_choice(LAST_COMPLETE, "ostatni pełny"))
    expect(page.get_by_role("group", name="Plik zbiorczy")).to_contain_text(collective_file.name)
    expect(page.get_by_text(REMINDER, exact=True)).to_be_visible()
    processes = run.api("/api/runs/setup", "przebieg-wybor-okresu")["processes"]
    assert isinstance(processes, list)
    [setup] = [process for process in processes if process["process"] == "settlement"]
    run.check(
        setup["preselected_period"] == LAST_COMPLETE
        and [choice["token"] for choice in setup["periods"]] == [LAST_COMPLETE, needs_check]
        and setup["blocker"] is None,
        "only periods with Status Plik zbiorczy przygotowany are offered; the Plik zbiorczy follows from the period",
    )
    run.capture(page, "40-przebieg-nowe-uruchomienie")

    run.step(feature, "przebieg-plik-zbiorczy-otwarty-w-excelu")
    start_card_warns_while_open(
        run,
        page,
        process="settlement",
        workbook=collective_file,
        warning=(
            "Plik zbiorczy jest otwarty w Excelu. Zapisz go i zamknij. Jeśli Excel jest zamknięty, usuń z tego samego "
            f"folderu pozostawiony plik ~${collective_file.name}."
        ),
        reminder=REMINDER,
        name="przebieg-plik-zbiorczy",
        shots=("4a-przebieg-plik-zbiorczy-otwarty-w-excelu", "4b-przebieg-plik-zbiorczy-zamkniety"),
    )

    run.step(feature, "przebieg-wzorzec-pozostawiony-plik-blokady")
    _template_lock_left_behind(run, page)

    run.step(feature, "przebieg-podglad")
    records_before = len(_settlement_records(run, "przebieg-metryki-przed"))
    page.goto(run.url)
    next_step = next_step_names_current_step(run, page, LAST_COMPLETE, "Uzupełnienie w Excelu")
    expect(next_step.get_by_role("button", name="Podgląd bez zapisu")).to_have_count(0)
    run.capture(page, "4e-przebieg-krok-uzupelnienie")
    with priced_in_efenix(run, LAST_COMPLETE, "WYMAGA_SPRAWDZENIA"):
        page.reload()
        next_step_names_current_step(run, page, LAST_COMPLETE, "Wycena w efenix")
        run.capture(page, "4f-przebieg-krok-wycena")
    with priced_in_efenix(run, LAST_COMPLETE):
        page.reload()
        next_step_names_current_step(run, page, LAST_COMPLETE, "Rozliczenia pracowników")
        path = next_step.get_by_role("list", name="Droga okresu")
        expect(path.get_by_role("img", name="zrobione")).to_have_count(3)
        run.check(
            True,
            "Następny krok offers Przebieg rozliczeń once the Wycena w efenix of the period ended OK (harness: its "
            "record in the Historia); before it, Uzupełnij and then Wyceń w efenix",
        )
        run.capture(page, "4g-przebieg-krok-rozliczenia")
        next_step.get_by_role("button", name="Podgląd bez zapisu").click()
        live = page.get_by_role("region", name="Podgląd na żywo")
        expect(live).to_contain_text("Podgląd gotowy · nic nie zapisano")
    result = finished_result(run, "przebieg-podglad")
    summary = result["summary"]
    assert isinstance(summary, dict)
    run.check(
        result["result"] == "OK" and summary["worker_settlements"] == expected_settlements,
        "the DRY-RUN plans one Rozliczenie pracownika per Wykonawca with his orders, the one without orders empty",
    )
    plan = live.get_by_role("table", name="Plan plików")
    expect(plan.get_by_role("row")).to_have_count(len(files))
    expect(plan.get_by_role("row").first.get_by_role("cell")).to_have_text([workers[0], files[0], "1 zlecenie"])
    expect(plan.get_by_role("row").last.get_by_role("cell")).to_have_text(
        [empty_worker, files[-1], "pusty 0 zleceń w tym tygodniu"]
    )
    expect(plan.get_by_role("button")).to_have_count(0)
    run.check(True, "the plan names each Wykonawca, his file and orders, marks the empty one, and opens nothing")
    run.check(not worker_settlements.exists(), "the DRY-RUN created no Folder rozliczeń pracowników")
    records = _settlement_records(run, "przebieg-metryki-podglad")
    run.check(
        len(records) == records_before + 1 and records[0]["mode"] == "DRY-RUN",
        "the DRY-RUN appended one record to the Przebieg rozliczeń metrics file",
    )
    run.capture(page, "41-przebieg-podglad")

    run.step(feature, "przebieg-potwierdzenie")
    live.get_by_role("button", name="Uruchom", exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    expect(confirm).to_contain_text(REMINDER)
    expect(confirm).to_contain_text("„Uruchom” potwierdza Gotowość Pliku zbiorczego")
    expect(confirm.get_by_text("Nie było podglądu bez zapisu")).to_have_count(0)
    without_quantity = run.api(f"/api/periods/{LAST_COMPLETE}/without-quantity", "przebieg-potwierdzenie-wiersze")
    sentence = without_quantity.get("sentence")
    # Gotowość types only N, which does not make a row without rule done, so those rows stay listed.
    assert isinstance(sentence, str), without_quantity
    expect(confirm).to_contain_text(sentence)
    run.check(
        True,
        "Uruchom asks to confirm the write; the click is Dad's confirmation of Gotowość, and the result card's "
        f"dialog lists the rows without quantity: {sentence}",
    )
    run.capture(page, "42-przebieg-potwierdzenie")
    pacing = Pace.TEMPLATES.set(run.root, TEMPLATE_PACING_MS)
    confirm.get_by_role("button", name="Uruchom", exact=True).click()

    run.step(feature, "przebieg-na-zywo")
    try:
        expect(live.get_by_role("progressbar", name="Szablony pracowników")).to_be_visible()
        expect(live).to_contain_text(f"Szablony pracowników · {workers[0]}")
        counters = live.locator('dl[aria-label="Liczniki"]')
        expect(counters).to_contain_text("Zapisane szablony0")
        # The second Szablon pracownika is paced, so the counters stay at one written while it runs.
        expect(live).to_contain_text(f"Szablony pracowników · {workers[1]}", timeout=Budget.SCREEN.ms)
        expect(counters).to_contain_text("Zapisane szablony1")
        view = current_run(run, "przebieg-na-zywo")
        progress = view["progress"]
        assert isinstance(progress, dict)
        run.check(
            view["state"] == "running" and progress["template_total"] == len(workers),
            "the live view shows the Szablony pracowników progress from the projection (harness pacing on)",
        )
        rows = figure(progress, "Wiersze danych")
        expect(counters).to_contain_text(f"Wiersze danych{rows}")
        run.check(
            figure(progress, "Zapisane szablony") == 1 and rows == run.fixture["settlement"]["rows_per_worker"][0],
            "the live counters (Wiersze danych, Zapisane szablony) update from the projection during the run",
        )
        run.check(
            run.post("/api/shutdown", "przebieg-zamkniecie-odmowa").status == 409,
            "closing Centrum is refused while the Przebieg rozliczeń runs",
        )
        run.capture(page, "43-przebieg-na-zywo", live=True)

        run.step(feature, "przebieg-znak-uruchomienia")
        menu_sign, header_link = active_run_signs(page, "Trwa Uruchomienie")
        page.get_by_role("link", name="Okresy", exact=True).click()
        expect(page.get_by_role("heading", name="Okresy", level=1)).to_be_visible()
        expect(menu_sign).to_be_visible()
        expect(header_link).to_be_visible()
        run.check(
            current_run(run, "przebieg-znak-uruchomienia")["state"] == "running",
            "on Okresy during the RUN the menu and the header show „Trwa Uruchomienie” (harness pacing on)",
        )
        run.capture(page, "155-przebieg-znak-uruchomienia", live=True)  # the sign's spinner turns while it runs
        header_link.click()
        expect(live).to_be_visible()
        expect(header_link).to_have_count(0)
        run.check(page.url.endswith("#/uruchomienia"), "the header link leads back to the live view; there it is gone")
    finally:
        remove(pacing, missing_ok=True)

    run.step(feature, "przebieg-zapisane")
    outcome = page.get_by_label("Wynik")
    expect(outcome).to_contain_text("Rozliczenia pracowników gotowe", timeout=Budget.SLOWED.ms)
    result = finished_result(run, "przebieg-zapisane")
    summary = result["summary"]
    assert isinstance(summary, dict)
    run.check(
        result["result"] == "OK"
        and (figure(summary, "Zapisane szablony"), figure(summary, "Puste szablony")) == (len(workers) - 1, 1)
        and summary["worker_settlements"] == expected_settlements,
        "the RUN finished OK and lists every written Rozliczenie pracownika, the one without orders empty",
    )
    run.check(
        sorted(path.name for path in worker_settlements.iterdir()) == sorted(files),
        "the Folder rozliczeń pracowników holds one Rozliczenie pracownika per Wykonawca",
    )
    run.check(
        sorted(path.name for path in period_folder.iterdir())
        == sorted([internal_settlement.name, collective_file.name, WORKER_SETTLEMENTS]),
        "no staging folder is left in the Folder okresu: the folder was published at once",
    )
    records = _settlement_records(run, "przebieg-metryki-zapisane")
    run.check(
        len(records) == records_before + 2
        and [(record["mode"], record["result"], record["origin"]) for record in records[:2]]
        == [("RUN", "OK", "centrum"), ("DRY-RUN", "OK", "centrum")],
        "both Uruchomienia appended one record each to the process's metrics file, marked as started from Centrum",
    )
    log = run.log()
    run.check(
        f"uruchomienie-koniec proces=settlement tryb=RUN okres={LAST_COMPLETE} wynik=OK koniec=finished" in log
        and ROW_MARKER not in log,
        "the Centrum log records the Przebieg rozliczeń with safe facts only",
    )
    settlements = live.get_by_role("table", name="Rozliczenia pracowników")
    expect(live.get_by_role("heading", name=f"Rozliczenia pracowników ({len(workers)})")).to_be_visible()
    expect(settlements.get_by_role("row")).to_have_count(len(workers))
    expect(settlements.get_by_role("row").first.get_by_role("cell")).to_have_text([workers[0], "1 zlecenie", "Otwórz"])
    expect(settlements.get_by_role("row").last.get_by_role("cell")).to_have_text(
        [empty_worker, "pusty 0 zleceń w tym tygodniu", "Otwórz"]
    )
    run.check(True, "the result lists the Rozliczenia pracowników without a click and marks the empty one pusty")
    run.capture(page, "44-przebieg-zapisane")

    run.step(feature, "przebieg-otwieranie")
    opened_before = len(run.lines(Log.OPENED))
    for file in files:
        settlements.get_by_role("button", name=f"Otwórz {file}", exact=True).click()
        until(last_opened_is(run, worker_settlements / file), f"Otwórz opens {file}")
    outcome.get_by_role("button", name="Otwórz folder rozliczeń pracowników", exact=True).click()
    until(last_opened_is(run, worker_settlements), "the main action opens the Folder rozliczeń pracowników")
    run.check(
        run.lines(Log.OPENED)[opened_before:]
        == [{"path": str(worker_settlements / file)} for file in files] + [{"path": str(worker_settlements)}],
        "each Otwórz opens exactly its Wykonawca's Rozliczenie pracownika, the main action the folder, one per click",
    )
    outside = {"worker": f"../{empty_worker}"}
    open_path = f"/api/periods/{LAST_COMPLETE}/worker-settlements/open"
    refused = run.post(open_path, "przebieg-otwieranie-spoza-folderu", outside).status
    run.check(
        refused == 404 and len(run.lines(Log.OPENED)) == opened_before + len(files) + 1,
        "a Wykonawca name leading out of the Folder rozliczeń pracowników is refused and opens nothing",
    )
    run.capture(page, "49-przebieg-otwieranie", full_page=False)

    run.step(feature, "przebieg-odczyt-po-uruchomieniu")
    # Same tab, no reload: the history and the period choice Centrum showed before the RUN are read again.
    page.get_by_role("tab", name="Historia", exact=True).click()
    newest, previous = history_rows(page).nth(1), history_rows(page).nth(2)
    expect(newest).to_contain_text("Przebieg rozliczeń")
    expect(newest).not_to_contain_text("DRY-RUN")
    expect(previous).to_contain_text("Przebieg rozliczeń")
    expect(previous).to_contain_text("DRY-RUN")
    run.check(True, "the Historia tab shows the finished RUN and its preview at the top")
    page.get_by_role("tab", name="Uruchomienie", exact=True).click()
    page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(needs_check)
    processes = run.api("/api/runs/setup", "przebieg-odczyt-po-uruchomieniu")["processes"]
    assert isinstance(processes, list)
    [setup] = [process for process in processes if process["process"] == "settlement"]
    run.check(
        [choice["token"] for choice in setup["periods"]] == [needs_check],
        "the period choice is read again: the closed period is no longer offered",
    )
    run.capture(page, "48-przebieg-odczyt-po-uruchomieniu")

    run.step(feature, "przebieg-status-okresu")
    page.goto(run.url)
    expect(period_row(page, LAST_COMPLETE)).to_contain_text("Rozliczenia pracowników gotowe")
    expect(page.get_by_role("region", name="Następny krok")).to_contain_text("Okres zamknięty")
    board = run.api("/api/periods", "przebieg-status-okresu")["periods"]
    assert isinstance(board, list)
    [row] = [row for row in board if row["token"] == LAST_COMPLETE]
    run.check(
        row["status"] == "worker_settlements_ready"
        and [file["count"] for file in row["files"] if file["target"] == "worker_settlements_folder"] == [len(workers)],
        "the Status okresu is Rozliczenia pracowników gotowe with a Rozliczenie pracownika per Wykonawca",
    )
    run.capture(page, "45-przebieg-status-okresu")

    run.step(feature, "przebieg-nienadpisywanie")
    before = {path.name: read_bytes(path) for path in worker_settlements.iterdir()}
    start = {"process": "settlement", "period": LAST_COMPLETE, "mode": "RUN"}
    started = run.post("/api/runs", "przebieg-nienadpisywanie-start", start).status
    run.check(started == 200, "a second RUN of the closed period starts (the Okres list no longer offers it)")
    page.goto(run.url + "#/uruchomienia")
    stop = page.get_by_label("Zatrzymanie")
    expect(stop).to_contain_text("Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany.")
    expect(stop).to_contain_text(f"folder {LAST_COMPLETE}\\{WORKER_SETTLEMENTS}")
    result = finished_result(run, "przebieg-nienadpisywanie")
    stops = result["stops"]
    assert isinstance(stops, list)
    [message] = stops
    assert isinstance(message, dict)
    run.check(
        result["ending"] == "stop"
        and all(message[part] for part in ("what", "where", "action"))
        and str(run.root) not in json.dumps(result, ensure_ascii=False),
        "the stop has three parts and no full path",
    )
    run.check(
        {path.name: read_bytes(path) for path in worker_settlements.iterdir()} == before,
        "Nienadpisywanie: the Rozliczenia pracowników are unchanged",
    )
    run.capture(page, "46-przebieg-nienadpisywanie")

    run.step(feature, "przebieg-wymaga-sprawdzenia")
    page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(needs_check)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    outcome = page.get_by_label("Wynik")
    expect(outcome).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    expect(outcome.get_by_role("button", name="Uruchom ponownie")).to_be_visible()
    expect(page.get_by_label("Ostrzeżenie")).to_contain_text("Nieznany identyfikator WYKONAWCA")
    result = finished_result(run, "przebieg-wymaga-sprawdzenia")
    run.check(
        (result["result"], result["next_action"]) == ("WYMAGA_SPRAWDZENIA", "rerun"),
        "a Wykonawca missing from the Lista Wykonawców gives Wymaga sprawdzenia, not a success",
    )
    run.check(
        not (Path(run.fixture["periods_directory"]) / needs_check / f"Rozliczenie pracowników {needs_check}").exists(),
        "the preview wrote nothing",
    )
    run.capture(page, "47-przebieg-wymaga-sprawdzenia")

    run.step(feature, "przebieg-nieznany-wykonawca")
    preview_warnings = result["warnings"]
    assert isinstance(preview_warnings, list)
    page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(needs_check)
    page.get_by_role("button", name="Uruchom", exact=True).click()
    page.get_by_role("alertdialog", name="Uruchomić z zapisem?").get_by_role("button", name="Uruchom", exact=True).click()
    stop = stop_banner(page)
    # The unknown login and column H, not a copy of the Komunikat's sentence: its wording has one owner, the Komunikat
    # catalog with its samples in tests/expected/komunikaty.txt, and a copy here drifted from it (#1529 r1).
    expect(stop).to_contain_text(UNKNOWN_WORKER)
    expect(stop.get_by_text("lista problemów pokaże wiersze")).to_have_count(0)
    result = finished_result(run, "przebieg-nieznany-wykonawca")
    stops = result["stops"]
    assert isinstance(stops, list)
    [message] = stops
    assert isinstance(message, dict)
    expect(stop).to_contain_text(str(message["action"]))
    run.check(
        result["ending"] == "stop"
        and UNKNOWN_WORKER in str(message["what"])
        and str(message["action"]).startswith("Popraw WYKONAWCĘ w kolumnie H"),
        "the RUN stops naming the Wykonawca missing from the Lista Wykonawców and Co zrobić starts with column H",
    )
    run.check(
        bool(preview_warnings) and not any(NAMES_ROW.search(str(warning["what"])) for warning in preview_warnings),
        "Co zrobić sends Dad to no Podgląd bez zapisu for rows: the preview of the same Plik zbiorczy names none",
    )
    run.check(
        not (Path(run.fixture["periods_directory"]) / needs_check / f"Rozliczenie pracowników {needs_check}").exists(),
        "the stopped RUN wrote nothing",
    )
    run.capture(page, "47b-przebieg-nieznany-wykonawca")
