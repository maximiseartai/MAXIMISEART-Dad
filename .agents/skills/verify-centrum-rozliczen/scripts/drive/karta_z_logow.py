"""Drive features/karta-z-logow.md."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from playwright.sync_api import Page, expect

from drive.common import (
    LAST_COMPLETE,
    Run,
    close_centrum,
    current_run,
    ensure_files_set,
    finished_view,
    history_rows,
    kill_centrum,
    local_time,
    move,
    remove_tree,
    start_centrum,
)

FEATURE = "karta-z-logow"
LOGS = "logs/uruchomienia"
LAST_STARTED = "logs/ostatnie-uruchomienie.json"
# What the live card has and the Logi do not hold: order_notes carry the order numbers and Wykonawcy of Wycena w efenix.
LIVE_ONLY = ("diagnosis", "report", "files_unchanged", "opens", "order_notes")
# What Dad could read about the Logi: the word in any of its cases, or their folder.
ABOUT_LOGS = re.compile(r"\bLog(i|ów|ach|ami)\b|uruchomienia/")
INTERRUPTED_WHAT = "Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku."
WRITE_ADVICE = "Uruchom ponownie. Pliki okresu, które zdążyły powstać, Centrum zostawi i powie, co z nimi zrobić."
MISSING = "Karty tego Uruchomienia nie ma"
WITHOUT_DETAILS = "Centrum zamknęło się tuż po wyniku, więc szczegółów nie ma"

Json = dict[str, Any]


def _logged(run: Run) -> dict[str, Json]:
    directory = run.root / LOGS
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in paths}


def _restored(view: Json, started_at: str) -> Json:
    result = {key: value for key, value in view["result"].items() if key not in LIVE_ONLY}
    return {
        "state": "restored",
        "run": view["run"],
        "started_at": started_at,
        "phases": view["progress"]["phases"],
        "result": result,
    }


def _metrics_count(run: Run) -> int:
    runs = run.api("/api/metrics", "karta-metryki")["runs"]
    assert isinstance(runs, list)
    return len(runs)


def _unfinished_starts(run: Run) -> int:
    events = [entry.event for entry in run.log_entries()]
    return events.count("uruchomienie-start") - events.count("uruchomienie-koniec")


def _uruchomienia(run: Run, page: Page) -> None:
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()


def _nothing_about_logs(run: Run, page: Page, where: str) -> None:
    text = page.locator("body").inner_text()
    run.check(ABOUT_LOGS.search(text) is None, f"{where}: Dad reads nothing about the Logi")


def _new_run(page: Page, process: str) -> None:
    """The setup card for ``process``: after an Uruchomienie it is behind `Nowe Uruchomienie procesu`."""

    new = page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True)
    radio = page.get_by_role("radio", name=process)
    expect(new.or_(radio).first).to_be_visible()
    if new.is_visible():
        new.click()
    radio.click()


def drive_run_card_from_logs(run: Run, page: Page) -> None:
    needs_check = run.fixture["settlement"]["needs_check"]

    run.step(FEATURE, "karta-po-zamknieciu")
    page.goto(run.url)
    ensure_files_set(run, page)
    before = set(_logged(run))
    page.goto(run.url + "#/uruchomienia")
    _new_run(page, "Przebieg rozliczeń")
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(needs_check)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    live = finished_view(run, "karta-przed-zamknieciem")
    new = [record for name, record in _logged(run).items() if name not in before]
    run.check(len(new) == 1, "the preview left one file of Logi")
    [record] = new
    run.capture(page, "210-karta-przed-zamknieciem")

    close_centrum(run, page)
    start_centrum(run, "karta-start-po-zamknieciu")
    _uruchomienia(run, page)
    card = page.get_by_role("region", name="Ostatnie Uruchomienie")
    note = f"Ostatnie Uruchomienie · {local_time(record['started_at'])} · Centrum było od tego czasu zamknięte"
    expect(card.get_by_text(note, exact=True)).to_be_visible()
    expect(card.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    for warning in live["result"]["warnings"]:
        message = card.get_by_label("Ostrzeżenie").filter(has_text=warning["what"])
        expect(message).to_contain_text(warning["where"])
        expect(message).to_contain_text(warning["action"])
    expect(card.get_by_role("button", name=re.compile(r"^Plan plików \(\d+\)$"))).to_be_visible()
    for name in ("Uruchom ponownie", "Nowe Uruchomienie procesu", "Napisz do Maksa o tym Uruchomieniu"):
        expect(card.get_by_role("button", name=name, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Diagnoza", exact=True)).to_have_count(0)
    _nothing_about_logs(run, page, "the card after the start")
    after = current_run(run, "karta-po-starcie")
    run.check(
        after == {"state": "idle", "previous": _restored(live, record["started_at"])},
        "after the start Centrum is without an Uruchomienie and its last one is the card before closing, "
        "without Diagnoza and Zgłoszenie",
    )
    previous = after["previous"]
    assert isinstance(previous, dict)
    logged = [
        {part: message[part] for part in ("what", "where", "action")} for message in record["messages"]
    ]
    run.check(
        previous["result"]["stops"] + previous["result"]["warnings"] == logged,
        "the card's Komunikaty are the Komunikaty of the newest file of Logi",
    )
    run.capture(page, "211-karta-po-zamknieciu")

    run.step(FEATURE, "karta-bez-szczegolow")
    history = run.api("/api/metrics", "karta-historia-podgladu")["runs"]
    assert isinstance(history, list)
    [row] = [entry for entry in history if entry["run_id"] == live["run"]["id"]]
    close_centrum(run, page)
    [name] = [name for name, logged in _logged(run).items() if logged["run_id"] == live["run"]["id"]]
    aside_logs = run.root / "odlozone" / name
    print("  harness: the preview's file of Logi is moved aside, as if Centrum died after the Historia row", flush=True)
    aside_logs.parent.mkdir(exist_ok=True)
    move(run.root / LOGS / name, aside_logs)
    try:
        start_centrum(run, "karta-start-bez-logow")
        _uruchomienia(run, page)
        card = page.get_by_role("region", name="Ostatnie Uruchomienie")
        note = f"Ostatnie Uruchomienie · {local_time(row['started_at'])} · {WITHOUT_DETAILS}"
        expect(card.get_by_text(note, exact=True)).to_be_visible()
        expect(card.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
        for button in ("Uruchom ponownie", "Nowe Uruchomienie procesu", "Napisz do Maksa o tym Uruchomieniu"):
            expect(card.get_by_role("button", name=button, exact=True)).to_be_visible()
        expect(card.get_by_label("Ostrzeżenie")).to_have_count(0)
        expect(card.get_by_text(INTERRUPTED_WHAT)).to_have_count(0)
        _nothing_about_logs(run, page, "the card without the Logi")
        recorded = current_run(run, "karta-bez-szczegolow")
        run.check(
            recorded
            == {
                "state": "idle",
                "previous": {
                    "state": "recorded",
                    "run": live["run"],
                    "started_at": row["started_at"],
                    "result": live["result"]["result"],
                    "headline": live["result"]["headline"],
                    "next_action": live["result"]["next_action"],
                },
            },
            "without its file of Logi the last Uruchomienie shows its result from the Historia row, not an Urwane "
            "Uruchomienie",
        )
        run.capture(page, "211b-karta-bez-szczegolow")
    finally:
        if aside_logs.exists():
            move(aside_logs, run.root / LOGS / name)

    run.step(FEATURE, "karta-przerwana")
    period_folder = Path(run.fixture["periods_directory"]) / LAST_COMPLETE
    aside = run.root / "odlozone" / LAST_COMPLETE
    if period_folder.exists():
        print(f"  harness: the Folder okresu {LAST_COMPLETE} is moved aside so the incomplete-period Decyzja comes", flush=True)
        aside.parent.mkdir(exist_ok=True)
        move(period_folder, aside)
    try:
        metrics_before, starts_before, logs_before = _metrics_count(run), _unfinished_starts(run), set(_logged(run))
        _new_run(page, "Przygotowanie pliku zbiorczego")
        expect(page.get_by_role("combobox", name="Okres")).to_contain_text(LAST_COMPLETE)
        page.get_by_role("button", name="Uruchom", exact=True).click()
        page.get_by_role("alertdialog", name="Uruchomić z zapisem?").get_by_role("button", name="Uruchom", exact=True).click()
        expect(page.get_by_role("alertdialog", name="Kontynuować mimo niepełnego okresu?")).to_be_visible()
        waiting = current_run(run, "karta-decyzja")
        run.check(waiting["state"] == "awaiting_decision", "the RUN waits for Dad's Decyzja")
        killed = waiting["run"]
        assert isinstance(killed, dict)

        kill_centrum(run)
        start_centrum(run, "karta-start-po-zabiciu")
        _uruchomienia(run, page)
        card = page.get_by_role("region", name="Ostatnie Uruchomienie")
        expect(card.get_by_text(re.compile(r"^Ostatnie Uruchomienie · .* · Centrum zamknęło się w trakcie$"))).to_be_visible()
        message = card.get_by_label("Ostrzeżenie")
        expect(message).to_contain_text(INTERRUPTED_WHAT)
        expect(message).to_contain_text(f"Przygotowanie pliku zbiorczego, okres {LAST_COMPLETE}")
        expect(message).to_contain_text(WRITE_ADVICE)
        expect(card.get_by_text("Z zapisem", exact=True)).to_be_visible()
        expect(card.get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
        expect(card.get_by_role("button", name="Napisz do Maksa o tym Uruchomieniu", exact=True)).to_have_count(0)
        interrupted = current_run(run, "karta-przerwana")
        previous = interrupted["previous"]
        assert isinstance(previous, dict)
        started = json.loads((run.root / LAST_STARTED).read_text(encoding="utf-8"))
        run.check(
            (interrupted["state"], previous["state"], previous["run"], previous["started_at"])
            == ("idle", "interrupted", killed, started["started_at"]),
            "after the start the last Uruchomienie is the killed RUN, named after its start",
        )
        run.check(set(_logged(run)) == logs_before, "the killed RUN left no file of Logi")
        run.check(_metrics_count(run) == metrics_before, "the killed RUN left no metrics record")
        run.check(
            _unfinished_starts(run) == starts_before + 1,
            "the Centrum log has the start of the killed RUN without its end",
        )
        run.capture(page, "212-karta-przerwana")
        card.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
        expect(page.get_by_role("radio", name="Przygotowanie pliku zbiorczego")).to_be_visible()
        run.check(current_run(run, "karta-po-nowym")["state"] == "idle", "Nowe Uruchomienie procesu starts nothing")
    finally:
        if aside.exists():
            remove_tree(period_folder, missing_ok=True)
            move(aside, period_folder)

    run.step(FEATURE, "karta-z-historii")
    page.get_by_role("tab", name="Historia", exact=True).click()
    rows = history_rows(page)
    newest = rows.nth(1)
    expect(newest).to_contain_text(needs_check)
    newest.get_by_role("button", name="Karta Uruchomienia", exact=True).click()
    sheet = page.get_by_role("dialog")
    expect(sheet.get_by_text(f"Uruchomienie z {local_time(record['started_at'])}", exact=True)).to_be_visible()
    expect(sheet.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    for name in ("Uruchom ponownie", "Uruchom", "Nowe Uruchomienie procesu", "Folder okresu"):
        expect(sheet.get_by_role("button", name=name, exact=True)).to_have_count(0)
    _nothing_about_logs(run, page, "the card of the Historia row")
    from_history = run.api(f"/api/runs/{live['run']['id']}/card", "karta-historia")
    run.check(
        from_history == _restored(live, record["started_at"]),
        "the Historia row opens the card of its Uruchomienie, the same as after the start",
    )
    run.capture(page, "213-karta-z-historii", full_page=False)
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)

    older = page.get_by_role("button", name="Pokaż starsze", exact=True)
    while older.count() > 0:
        older.click()
    machine = rows.filter(has_text=".cmd").first
    machine.get_by_role("button", name="Karta Uruchomienia", exact=True).click()
    expect(sheet.get_by_text(MISSING, exact=True)).to_be_visible()
    expect(sheet.get_by_text("Wystartowało spoza Centrum rozliczeń albo jego wynik nie został zachowany.")).to_be_visible()
    run.capture(page, "214-karta-bez-logow", full_page=False)
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
