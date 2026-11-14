"""Drive features/kontrola-ilosci.md."""

from __future__ import annotations

import json
import time

from playwright.sync_api import Page, expect

from drive.common import (
    REPORT_KEY,
    box_issues,
    close_centrum,
    drop_report_key,
    queued,
    read_json,
    remove,
    Run,
    start_centrum,
)
from drive.waiting import Budget, until
from harness import Pace, Switch
from atrapy.scenariusz_centrum import LAST_COMPLETE, ROW_MARKER
from atrapy.pliki_taty import REPORT_KEY_FILE

FEATURE = "kontrola-ilosci"
LABEL = "kontrola-ilosci"
# Long enough to load Okresy in the tab while the skrzynka still holds the Kontrola sent again at start.
BOX_PACING_MS = 4000


def _offline_waits(run: Run) -> int:
    return sum(
        entry.event == "skrzynka-czeka" and entry.facts.get("przyczyna") == "brak-sieci" for entry in run.log_entries()
    )


def _open_periods(page: Page, run: Run) -> None:
    """Dad's tab after the start: the closed screen stays until the page loads again."""

    page.goto(run.url + "#/okresy")
    page.reload()
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()


def drive(run: Run, page: Page) -> None:
    config = run.config
    key_file = config / REPORT_KEY_FILE
    offline = Switch.BOX_OFFLINE.file(run.root)
    checks_before = len(box_issues(run, LABEL))

    run.step(FEATURE, "kontrola-w-kolejce")
    [waiting] = queued(run, LABEL)
    document = read_json(waiting)
    run.check(
        document["target"]["label"] == LABEL and document["period"] == LAST_COMPLETE,
        f"the RUN of {LAST_COMPLETE} left its Kontrola ilości in config/zgloszenia/kolejka",
    )
    run.check(
        f" skrzynka-w-kolejce etykieta={LABEL} okres={LAST_COMPLETE}\n" in run.log(),
        "the Centrum log says the Kontrola ilości of the RUN went into the queue",
    )
    run.check(
        any(" skrzynka-czeka " in line and line.endswith(" przyczyna=brak-klucza") for line in run.log().splitlines()),
        "without a key the Centrum log says the queue waits (one line per pass, naming its first file), with no content",
    )
    run.check(
        sorted(path.name for path in run.queue.parent.iterdir()) == [run.queue.name],
        "no Zgłoszenie file for Dad next to the queue: the Kontrola is not an unsent Zgłoszenie",
    )
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    run.check("skrzynka" not in page.content().lower(), "Dad's tab says nothing about the skrzynka Zgłoszeń")
    run.capture(page, "150-kontrola-w-kolejce")

    run.step(FEATURE, "kontrola-bez-sieci-po-starcie")
    print("  harness: Maks writes the key; Dad's internet is down", flush=True)
    key_file.write_text(REPORT_KEY + "\n", encoding="utf-8")
    Switch.BOX_OFFLINE.on(run.root)
    close_centrum(run, page)
    waited = _offline_waits(run)
    start_centrum(run, "kontrola-start-bez-sieci")
    # The first failure ends the pass, and the Logi Uruchomienia queued before the Kontrola go first.
    until(
        lambda: _offline_waits(run) > waited, "at start Centrum tries the queue again and the Kontrola keeps waiting"
    )
    run.check(queued(run, LABEL) == [waiting], "the Kontrola file stays after another failure")
    run.check(len(box_issues(run, LABEL)) == checks_before, "nothing reached the skrzynka")
    _open_periods(page, run)
    expect(page.get_by_role("alert")).to_have_count(0)
    run.capture(page, "151-kontrola-bez-sieci-po-starcie")

    run.step(FEATURE, "kontrola-wyslana-po-starcie")
    print(f"  harness: the internet is back; the skrzynka answers after {BOX_PACING_MS} ms", flush=True)
    remove(offline)
    pacing = Pace.REPORT_BOX.set(run.root, BOX_PACING_MS)
    try:
        close_centrum(run, page)
        sent_before = run.log().count(f"skrzynka-wyslano etykieta={LABEL}")
        started = time.monotonic()
        start_centrum(run, "kontrola-start-wysylka")
        _open_periods(page, run)
        shown_after_s = time.monotonic() - started
        run.check(
            run.log().count(f"skrzynka-wyslano etykieta={LABEL}") == sent_before,
            f"Okresy is shown {shown_after_s:.1f} s after the start, before the skrzynka took the Kontrola",
        )
        run.capture(page, "152-kontrola-start-bez-czekania")
        until(
            lambda: f"skrzynka-wyslano etykieta={LABEL} okres={LAST_COMPLETE}" in run.log(),
            "the Kontrola sent again at start reaches the skrzynka in the background",
            Budget.WORK,
        )
    finally:
        remove(pacing, missing_ok=True)
    checks = box_issues(run, LABEL)
    run.check(len(checks) == checks_before + 1, "the skrzynka got exactly one Kontrola ilości")
    sent = checks[-1]
    body = str(sent["body"])
    (run.evidence / "api" / "kontrola-skrzynka.json").write_text(
        json.dumps(
            {key: sent[key] for key in ("number", "title", "labels", "state")} | {"first_line": body.splitlines()[0]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run.check(
        str(sent["title"]).startswith(f"Kontrola ilości {LAST_COMPLETE}: ")
        and body.splitlines()[0] == f"- Kontrola ilości okresu: {LAST_COMPLETE}",
        "the issue is the period's Kontrola ilości, labelled kontrola-ilosci",
    )
    run.check(
        f"- Uruchomienie: {document['run_id']}" in body.splitlines(), "it is the Kontrola of the RUN from the queue"
    )
    until(lambda: queued(run, LABEL, leaving=True) == [], "the sent Kontrola file is removed")
    log = run.log()
    run.check(REPORT_KEY not in log and ROW_MARKER not in log, "the Centrum log has neither the key nor workbook content")
    run.check(REPORT_KEY not in body, "the key is not in the Kontrola")
    drop_report_key(key_file)
