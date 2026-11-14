"""Drive features/przygotowanie-pliku-zbiorczego.md."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, Request, expect

from drive.common import (
    HIDE_TAB,
    SHOW_TAB,
    read_bytes,
    Run,
    active_run_signs,
    current_run,
    ensure_files_set,
    error_toasts,
    figure,
    finished_result,
    frontend_ms,
    history_rows,
    last_opened_is,
    next_step_names_current_step,
    period_choice,
    period_files,
    period_row,
    sent_requests,
    settle,
    start_card_warns_while_open,
)
from drive.teksty import FILES_UNCHANGED
from drive.uzupelnienie import drive_result_card
from drive.waiting import quiet_for
from atrapy.scenariusz_centrum import LAST_COMPLETE, ROW_MARKER
from harness import Log

# An older period with no successful DRY-RUN in the fixture's metrics; its confirmation keeps the no-preview warning.
NOT_PREVIEWED = "08_14_09_2026"
PREPARATION = "przygotowanie-pliku-zbiorczego"
INCOMPLETE_PERIOD_WHAT = "Ostatnie zlecenie okresu jest z soboty 10.10.2026"
COLLECTIVE_FILE = f"Rozliczenie {LAST_COMPLETE} - zbiorcze.xlsx"


def _rows(rows: list[int]) -> str:
    return f"wiersz {rows[0]}" if len(rows) == 1 else f"wiersze {', '.join(str(row) for row in rows)}"


def _quantity_warnings(run: Run) -> tuple[tuple[str, str], ...]:
    """Ilości usług warnings of the fixture's Plik zbiorczy rows (``preparation.rows`` of fixture.json): "Co się
    stało" and "Gdzie"."""

    rows = run.fixture["preparation"]["rows"]
    return (
        ("Narzędzie nie zna urządzenia z kolumny URZĄDZENIA", f"plik {COLLECTIVE_FILE}, {_rows(rows['without_rule'])}"),
        ("rozlicza się z opisu technika", f"plik {COLLECTIVE_FILE}, {_rows(rows['from_description'])}"),
        ("Ilości, które wynikają z opisu technika", f"plik {COLLECTIVE_FILE}, kolumny Y, AB, AD, AJ, AK, AL i AM"),
    )


def _started_once(run: Run, page: Page, sent: list[Request], what: str) -> None:
    """One ``POST /api/runs`` for Dad's repeated click on ``what`` and no error toast next to the Uruchomienie."""

    run.check(len(sent) == 1, f"a double click on {what} starts one Uruchomienie procesu ({len(sent)} requests)")
    run.check(error_toasts(page).count() == 0, f"no error toast after the double click on {what}")


def _quantity_warnings_shown(run: Run, page: Page, result: dict[str, object], label: str) -> None:
    """The result shows each Ilości usług warning in three parts, with Plik zbiorczy rows and no row content."""

    card = page.get_by_role("region", name="Podgląd na żywo")
    expected = _quantity_warnings(run)
    for what, where in expected:
        expect(card.get_by_label("Ostrzeżenie").filter(has_text=what).filter(has_text=where)).to_be_visible()
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    shown = [(warning["what"], warning["where"]) for warning in warnings]
    run.check(
        all(any(what in text and place == where for text, place in shown) for what, where in expected)
        and ROW_MARKER not in json.dumps(warnings, ensure_ascii=False),
        f"{label} shows the Ilości usług warnings with Plik zbiorczy rows and no row content",
    )


def _preparation_records(run: Run, name: str) -> list[dict[str, object]]:
    """Valid records of the Przygotowanie metrics file as the server reads them, newest first."""

    runs = run.api("/api/metrics", name)["runs"]
    assert isinstance(runs, list)
    return [entry for entry in runs if entry["process"] == "preparation"]


def drive(run: Run, page: Page) -> None:
    feature = PREPARATION
    expected = run.fixture["preparation"]
    period_folder = period_files(run)[0].parent
    register_name = Path(run.fixture["order_register"]).name
    records_before = len(_preparation_records(run, "przygotowanie-metryki-przed"))

    run.step(feature, "przygotowanie-wybor-okresu")
    page.goto(run.url)
    ensure_files_set(run, page)
    page.reload()
    page.get_by_role("button", name=f"Przygotuj plik zbiorczy, okres {LAST_COMPLETE}", exact=True).click()
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    run.check(page.url.endswith("#/uruchomienia"), "the row's next step opens Uruchomienia")
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period_choice(LAST_COMPLETE, "ostatni pełny"))
    expect(page.get_by_role("group", name="Rejestr zleceń")).to_contain_text(register_name)
    expect(page.get_by_text("Zapisz i zamknij Rejestr zleceń w Excelu", exact=True)).to_be_visible()
    setup = run.api("/api/runs/setup", "przygotowanie-wybor-okresu")["processes"]
    assert isinstance(setup, list)
    run.check(
        setup[0]["preselected_period"] == LAST_COMPLETE and setup[0]["blocker"] is None,
        "the server preselects the last complete period and nothing is missing",
    )
    run.capture(page, "30-przygotowanie-nowe-uruchomienie")

    run.step(feature, "przygotowanie-rejestr-otwarty-w-excelu")
    start_card_warns_while_open(
        run,
        page,
        process="preparation",
        workbook=Path(run.fixture["order_register"]),
        warning=(
            "Rejestr zleceń jest otwarty w Excelu. Zapisz go i zamknij. Jeśli Excel jest zamknięty, usuń z tego samego "
            f"folderu pozostawiony plik ~${Path(run.fixture['order_register']).name}."
        ),
        reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
        name="przygotowanie-rejestr",
        shots=("3c-przygotowanie-rejestr-otwarty-w-excelu", "3d-przygotowanie-rejestr-zamkniety"),
    )

    run.step(feature, "przygotowanie-podglad")
    page.goto(run.url)
    with sent_requests(page, "POST", "/api/runs") as sent:
        page.get_by_role("region", name="Następny krok").get_by_role("button", name="Podgląd bez zapisu").dblclick()
        live = page.get_by_role("region", name="Podgląd na żywo")
        expect(live).to_contain_text("Podgląd gotowy · nic nie zapisano")
        settle(page, sent)
    _started_once(run, page, sent, "Podgląd bez zapisu on Następny krok")
    result = finished_result(run, "przygotowanie-podglad")
    summary = result["summary"]
    assert isinstance(summary, dict)
    run.check(
        result["result"] == "OK"
        and figure(summary, "Zlecenia okresu") == expected["period_order_count"]
        and figure(summary, "Zlecenia skuteczne") == expected["successful_order_count"]
        and [day["count"] for day in summary["counts"]["counts"]] == expected["orders_per_day"],
        "the DRY-RUN plan has the Rejestr zleceń's counts and Zlecenia na dzień",
    )
    expect(live.get_by_role("listitem", name="sob 10.10.2026: 1", exact=True)).to_be_visible()
    expect(live.get_by_label("Ostrzeżenie").filter(has_text=INCOMPLETE_PERIOD_WHAT)).to_be_visible()
    period_file_list = live.get_by_role("list", name="Pliki okresu")
    expect(period_file_list).to_contain_text(f"Rozliczenie {LAST_COMPLETE} - zbiorcze.xlsx")
    expect(period_file_list.get_by_role("button")).to_have_count(0)
    run.check(True, "after the preview the period file names are plain text: the files do not exist yet")
    _quantity_warnings_shown(run, page, result, "the preview")
    run.check(not period_folder.exists(), "the DRY-RUN created neither files nor the Folder okresu")
    records = _preparation_records(run, "przygotowanie-metryki-podglad")
    run.check(
        len(records) == records_before + 1 and records[0]["mode"] == "DRY-RUN",
        "the DRY-RUN appended one record to the process's metrics file",
    )
    run.capture(page, "31-przygotowanie-podglad")
    preview_warnings = result["warnings"]
    assert isinstance(preview_warnings, list)

    run.step(feature, "przygotowanie-podglad-po-odswiezeniu")
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    no_preview = confirm.get_by_text("Nie było podglądu bez zapisu", exact=True)
    page.reload()
    page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period_choice(LAST_COMPLETE, "ostatni pełny"))
    page.get_by_role("button", name="Uruchom", exact=True).click()
    expect(confirm).to_be_visible()
    expect(no_preview).to_have_count(0)
    confirm.get_by_role("button", name="Anuluj").click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=period_choice(NOT_PREVIEWED, "Brak plików okresu"), exact=True).click()
    page.get_by_role("button", name="Uruchom", exact=True).click()
    expect(no_preview).to_be_visible()
    setup = run.api("/api/runs/setup", "przygotowanie-podglad-po-odswiezeniu")["processes"]
    assert isinstance(setup, list)
    previewed = {choice["token"]: choice["previewed"] for choice in setup[0]["periods"]}
    run.check(
        previewed[LAST_COMPLETE] is True and previewed[NOT_PREVIEWED] is False,
        "the server remembers the successful preview per period from the metrics history",
    )
    run.check(
        True,
        "after a reload the confirmation warns only for the period without a preview, not for the previewed one",
    )
    run.capture(page, "39-przygotowanie-bez-podgladu")
    confirm.get_by_role("button", name="Anuluj").click()

    run.step(feature, "przygotowanie-potwierdzenie")
    # „Nowe Uruchomienie procesu” is the tab's own choice; a reload shows the finished preview again.
    page.reload()
    expect(live).to_contain_text("Podgląd gotowy · nic nie zapisano")
    live.get_by_role("button", name="Uruchom", exact=True).click()
    expect(confirm).to_contain_text("Zapisz i zamknij Rejestr zleceń w Excelu")
    expect(no_preview).to_have_count(0)
    run.check(True, "Uruchom asks to confirm the write and reminds to close the Rejestr zleceń")
    run.capture(page, "32-przygotowanie-potwierdzenie")
    decision = page.get_by_role("alertdialog", name="Kontynuować mimo niepełnego okresu?")
    with sent_requests(page, "POST", "/api/runs") as sent:
        # The second click lands on the confirmation's „Uruchom” while the dialog is closing.
        confirm.get_by_role("button", name="Uruchom", exact=True).dblclick()
        expect(decision).to_be_visible()
        settle(page, sent)
    _started_once(run, page, sent, "the confirmation's Uruchom")

    run.step(feature, "przygotowanie-decyzja")
    expect(decision).to_contain_text(INCOMPLETE_PERIOD_WHAT)
    expect(decision.get_by_role("listitem", name="pon 12.10.2026: 0", exact=True)).to_be_visible()
    expect(decision.get_by_role("button", name="Przerwij bez zapisu")).to_be_focused()
    view = current_run(run, "przygotowanie-decyzja")
    run.check(view["state"] == "awaiting_decision", "the server waits for Dad's decision")
    progress = view["progress"]
    assert isinstance(progress, dict)
    counters = page.locator('dl[aria-label="Liczniki"]')
    expect(counters).to_contain_text(f"Ostrzeżenia{figure(progress, 'Ostrzeżenia')}")
    run.check(
        figure(progress, "Ostrzeżenia") == len(preview_warnings),
        "the live counters show the projection's Ostrzeżenia (as many as the preview's warnings) while the decision waits",
    )
    second = {"process": "preparation", "period": LAST_COMPLETE, "mode": "DRY-RUN"}
    run.check(run.post("/api/runs", "przygotowanie-trwa-juz", second).status == 409, "a second Uruchomienie procesu is refused")
    run.check(
        run.post("/api/shutdown", "przygotowanie-zamkniecie-odmowa").status == 409,
        "closing Centrum is refused while the Uruchomienie procesu waits for the decision",
    )
    page.reload()
    expect(decision).to_be_visible()
    run.check(True, "the decision survives a reload of the tab")
    run.capture(page, "33-przygotowanie-decyzja")

    run.step(feature, "przygotowanie-znak-decyzji")
    menu_sign, header_link = active_run_signs(page, "Czeka na decyzję")
    page.goto(run.url + "#/okresy")
    expect(page.get_by_role("heading", name="Okresy", level=1)).to_be_visible()
    expect(decision).to_have_count(0)
    expect(menu_sign).to_be_visible()
    expect(header_link).to_be_visible()
    run.check(True, "on Okresy, where the decision dialog does not open, the header says „Czeka na decyzję”")
    run.capture(page, "149-przygotowanie-znak-decyzji")
    header_link.click()
    expect(decision).to_be_visible()
    # The open dialog hides the rest of the page from the accessibility tree, so the header is read as text.
    expect(page.locator("header").get_by_text("Czeka na decyzję")).to_have_count(0)
    run.check(
        page.url.endswith("#/uruchomienia"), "the header link leads to Uruchomienia, where the decision waits; there it is gone"
    )

    run.step(feature, "przygotowanie-przerwij")
    decision.get_by_role("button", name="Przerwij bez zapisu").click()
    stop = page.get_by_label("Zatrzymanie po odmowie", exact=True)
    expect(stop).to_contain_text("Przerwano")
    expect(stop).to_contain_text(FILES_UNCHANGED)
    expect(stop).to_contain_text("Przerwano z powodu niepełnego okresu")
    expect(stop).to_contain_text("Jeśli okres jest pełny, przy decyzji wybierz „Kontynuuj”.")
    run.check(
        "text-destructive" not in (stop.get_attribute("class") or ""),
        "the refusal in Dad's decision is calm, not a red error",
    )
    result = finished_result(run, "przygotowanie-przerwij")
    stops = result["stops"]
    assert isinstance(stops, list)
    run.check(
        (result["ending"], result["stop_kind"], result["headline"], result["diagnosis"]) == ("declined", "declined", "Przerwano", None)
        and (result["files_unchanged"], result["opens"]) == (True, "order_register")
        and len(stops) == 1,
        "the refusal is a declined stop with the three-part message, no Diagnoza and the Rejestr zleceń to open",
    )
    run.check(not period_folder.exists(), "Przerwij bez zapisu wrote nothing")
    run.capture(page, "34-przygotowanie-zatrzymanie")
    opened_before = len(run.lines(Log.OPENED))
    with sent_requests(page, "POST", "/api/settings/register/open") as sent:
        stop.get_by_role("button", name="Otwórz Rejestr zleceń", exact=True).click()
        settle(page, sent)
    run.check(
        len(sent) == 1 and run.lines(Log.OPENED)[opened_before:] == [{"path": run.fixture["order_register"]}],
        "Otwórz Rejestr zleceń opens the Rejestr zleceń from Dad's settings",
    )

    run.step(feature, "przygotowanie-podwojne-klikniecie")
    with sent_requests(page, "POST", "/api/runs") as sent:
        stop.get_by_role("button", name="Uruchom ponownie").dblclick()
        expect(decision).to_be_visible()
        settle(page, sent)
    _started_once(run, page, sent, "Uruchom ponownie")
    page.evaluate(HIDE_TAB)
    run.check(True, "harness: the stream's next view arrives late (the page reports itself hidden), as at CPU 6×")
    try:
        with sent_requests(page, "POST", "/api/runs/*/decision") as decided:
            decision.get_by_role("button", name="Kontynuuj").click()
            settle(page, decided)
            # Dad's next clicks come after the decision's answer, while the dialog still waits for the stream.
            decision.get_by_role("button", name="Kontynuuj").click(click_count=2, force=True)
            settle(page, decided)
        run.check(len(decided) == 1, f"Kontynuuj clicked three times sends one decision ({len(decided)} requests)")
        run.check(error_toasts(page).count() == 0, "no error toast after Kontynuuj clicked three times")
        run.check(
            all(decision.get_by_role("button", name=name).is_disabled() for name in ("Kontynuuj", "Przerwij bez zapisu")),
            "the decision's buttons wait until the stream shows that the Uruchomienie no longer waits",
        )
        run.capture(page, "3a-przygotowanie-podwojne-klikniecie")
    finally:
        page.evaluate(SHOW_TAB)
    expect(decision).to_have_count(0)
    expect(page.get_by_label("Wynik")).to_contain_text("Plik zbiorczy przygotowany · wymaga sprawdzenia")
    run.check(True, "with the stream back, the dialog closes on the result")
    internal_settlement, collective_file = period_files(run)
    opened_before = len(run.lines(Log.OPENED))
    with sent_requests(page, "POST", f"/api/periods/{LAST_COMPLETE}/open") as sent:
        page.get_by_label("Wynik").get_by_role("button", name="Otwórz Plik zbiorczy", exact=True).dblclick()
        settle(page, sent)
    run.check(
        len(sent) == 1 and run.lines(Log.OPENED)[opened_before:] == [{"path": str(collective_file)}],
        f"a double click on the result's main action Otwórz Plik zbiorczy opens the Plik zbiorczy once ({len(sent)} requests)",
    )

    run.step(feature, "przygotowanie-kontynuuj")
    result = finished_result(run, "przygotowanie-kontynuuj")
    run.check(
        result["result"] == "WYMAGA_SPRAWDZENIA"
        and result["headline"] == "Plik zbiorczy przygotowany · wymaga sprawdzenia"
        and result["warnings"] == preview_warnings,
        "the RUN needs review only for the preview's warnings: Dad completes the written Plik zbiorczy",
    )
    _quantity_warnings_shown(run, page, result, "the written Plik zbiorczy's result")
    run.check(all(path.is_file() for path in period_files(run)), "both period files are in the Folder okresu")
    records = _preparation_records(run, "przygotowanie-metryki-zapisane")
    run.check(
        len(records) == records_before + 3
        and [(record["mode"], record["result"]) for record in records[:3]]
        == [("RUN", "WYMAGA_SPRAWDZENIA"), ("RUN", "BLAD_KRYTYCZNY"), ("DRY-RUN", "OK")],
        "every Uruchomienie procesu appended one record to the process's metrics file",
    )
    log = run.log()
    run.check(
        f"uruchomienie-koniec proces=preparation tryb=RUN okres={LAST_COMPLETE} wynik=WYMAGA_SPRAWDZENIA koniec=finished" in log
        and "uruchomienie-start proces=preparation tryb=RUN" in log
        and ROW_MARKER not in log,
        "the Centrum log records the start and end of each Uruchomienie procesu with safe facts only",
    )
    run.capture(page, "35-przygotowanie-zapisane")
    drive_result_card(run, page)

    run.step(feature, "przygotowanie-otwieranie")
    # The tab drops a repeat of the same file for a while after the server's answer, with nothing on screen; the Plik
    # zbiorczy was opened by the double click above.
    quiet_for(page, frontend_ms("pages/periods/open-period-path.ts", "REPEAT_IGNORED_MS") + 100)
    period_file_list = page.get_by_role("list", name="Pliki okresu")
    opened_before = len(run.lines(Log.OPENED))
    for path in (internal_settlement, collective_file):
        period_file_list.get_by_role("button", name=path.name, exact=True).click()
        run.wait_for(last_opened_is(run, path), f"the period file name opens {path.name}")
    run.check(
        run.lines(Log.OPENED)[opened_before:] == [{"path": str(internal_settlement)}, {"path": str(collective_file)}],
        "each period file name in the result opens its own file, one per click",
    )
    run.capture(page, "3b-przygotowanie-otwieranie", full_page=False)

    run.step(feature, "przygotowanie-status-okresu")
    page.goto(run.url)
    expect(period_row(page, LAST_COMPLETE)).to_contain_text("Plik zbiorczy przygotowany")
    next_step_names_current_step(run, page, LAST_COMPLETE, "Uzupełnienie w Excelu")
    run.check(True, "the Status okresu on Tablica okresów is Plik zbiorczy przygotowany, and the next step Uzupełnij plik zbiorczy")
    run.capture(page, "36-przygotowanie-status-okresu")

    run.step(feature, "przygotowanie-nienadpisywanie")
    before = [read_bytes(path) for path in period_files(run)]
    page.goto(run.url + "#/uruchomienia")
    page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("button", name="Uruchom", exact=True).click()
    page.get_by_role("alertdialog", name="Uruchomić z zapisem?").get_by_role("button", name="Uruchom", exact=True).click()
    expect(page.get_by_label("Zatrzymanie do poprawy", exact=True)).to_contain_text(
        "Plik tego okresu już istnieje, więc nie został nadpisany."
    )
    result = finished_result(run, "przygotowanie-nienadpisywanie")
    run.check(
        (result["stop_kind"], result["headline"], result["opens"]) == ("for_tata", "Do poprawy", None),
        "Nienadpisywanie is a stop Dad fixes himself, with no file of his to open",
    )
    run.check([read_bytes(path) for path in period_files(run)] == before, "Nienadpisywanie: both files are unchanged")
    run.capture(page, "37-przygotowanie-nienadpisywanie")

    run.step(feature, "przygotowanie-historia")
    page.get_by_role("tab", name="Historia").click()
    history = run.api("/api/metrics", "przygotowanie-historia")["runs"]
    assert isinstance(history, list)
    run.check(
        [entry["origin"] for entry in history[:4]] == ["centrum"] * 4,
        "the metrics history marks the four Uruchomienia from Centrum without a schema change",
    )
    newest = history_rows(page).nth(1)
    expect(newest).to_contain_text(LAST_COMPLETE)
    expect(newest).not_to_contain_text(".cmd")
    run.check(True, "the Historia tab shows the newest Uruchomienie without the .cmd badge")
    run.capture(page, "38-przygotowanie-historia")
