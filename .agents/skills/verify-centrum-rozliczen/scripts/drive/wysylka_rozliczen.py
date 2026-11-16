"""Drive features/wysylka-rozliczen.md."""

from __future__ import annotations

from datetime import date, datetime, time
import email
import email.policy
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, expect

from drive.common import Run, close_settings, ensure_files_set, open_settings, put_bytes, read_bytes, remove
from drive.waiting import until
from harness import INBOX_ADDRESS, INBOX_PASSWORD, File

FEATURE = "wysylka-rozliczen"
READY_PERIOD = "22_28_09_2026"
# The sentences and words the server gives, copied on purpose (skille.md: the oracle does not import what it checks).
LABEL = "22–28 września 2026"
DEFAULT_SUBJECT = f"Rozliczenie za {LABEL}"
REPORT_WORD = "Temat nie może mieć słowa „raport”: odpowiedź Wykonawcy Centrum wzięłoby za jego raport."
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Json = dict[str, Any]


def _period(run: Run, name: str) -> Json:
    view = run.api("/api/settlement-mailing", name)
    run.check(view["state"] == "ready" and view["mailbox"] == {"state": "ready"}, "the page reads the skrzynka raportów")
    periods = view["periods"]
    assert isinstance(periods, list)
    [period] = [found for found in periods if found["token"] == READY_PERIOD]
    assert isinstance(period, dict)
    return period


def _mails(root: Path) -> list[EmailMessage]:
    folder = File.SENT_MAILS.file(root)
    found = []
    for path in sorted(folder.glob("*.eml")) if folder.is_dir() else []:
        message = email.message_from_bytes(read_bytes(path), policy=email.policy.default)
        assert isinstance(message, EmailMessage)
        found.append(message)
    return found


def _row(table: Locator, worker: str) -> Locator:
    return table.get_by_role("row").filter(has_text=worker)


def drive(run: Run, page: Page) -> None:
    page.goto(run.url + "#/okresy")
    ensure_files_set(run, page)
    access = run.config / "skrzynka-raportow.txt"
    before_access = read_bytes(access) if access.exists() else None
    # Harness: Maks's access file to the served atrapa skrzynka raportów, never Dad's Gmail.
    put_bytes(access, f"{INBOX_ADDRESS}\r\n{INBOX_PASSWORD}\r\n".encode("utf-8-sig"))
    try:
        _send(run, page)
        _settings(run, page)
    finally:
        if before_access is None:
            remove(access)
        else:
            put_bytes(access, before_access)


def _settled_before_today(run: Run) -> Path:
    """Harness: the served Centrum's clock is the fixture's day (2026-10-19), while the fixture wrote the Rozliczenia
    pracowników now; a mail sent at the fixture's day would be older than its file, so the files get the fixture's
    midnight as their time of change, as after a Przebieg rozliczeń that morning."""

    folder = Path(str(run.fixture["periods_directory"])) / READY_PERIOD / f"Rozliczenie pracowników {READY_PERIOD}"
    midnight = datetime.combine(date.fromisoformat(str(run.fixture["today"])), time()).astimezone().timestamp()
    for path in folder.glob("*.xlsx"):
        os.utime(path, (midnight, midnight))
    return folder


def _send(run: Run, page: Page) -> None:
    folder = _settled_before_today(run)
    run.step(FEATURE, "strona")
    period = _period(run, "wysylka-przed")
    rows = {str(row["worker"]): row for row in period["rows"]}
    to_send = [worker for worker, row in rows.items() if row["preselected"]]
    run.check(
        bool(to_send) and all(rows[worker]["state"] == {"state": "to_send"} for worker in to_send),
        "the files of the settled period that never went are „do wysłania” and ticked",
    )
    page.goto(run.url + "#/wysylka")
    expect(page.get_by_role("heading", name="Wysyłka rozliczeń", level=1)).to_be_visible()
    page.get_by_role("button").filter(has_text=LABEL).click()
    table = page.get_by_role("table")
    for worker in rows:
        expect(_row(table, worker)).to_be_visible()
    for worker in to_send:
        expect(_row(table, worker).get_by_role("checkbox")).to_be_checked()
        expect(_row(table, worker)).to_contain_text("Do wysłania")
    run.check(True, "each Rozliczenie pracownika of the period has its row, ticked when it waits")
    send = page.get_by_role("button", name=f"Wyślij {len(to_send)} rozlicz", exact=False)
    expect(send).to_be_enabled()
    run.capture(page, "500-wysylka-przed", full_page=False)

    run.step(FEATURE, "potwierdzenie")
    send.click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text(f"Podgląd maila 1 z {len(to_send)}")).to_be_visible()
    expect(dialog).to_contain_text(DEFAULT_SUBJECT)
    expect(dialog).to_contain_text(str(rows[to_send[0]]["file"]))
    run.check(_mails(run.root) == [], "the window only previews: no mail went yet")
    run.capture(page, "501-wysylka-potwierdzenie", full_page=False)
    if len(to_send) > 1:
        dialog.get_by_role("button", name="Następny mail").click()
        expect(dialog.get_by_text(f"Podgląd maila 2 z {len(to_send)}")).to_be_visible()
        expect(dialog).to_contain_text(str(rows[to_send[1]]["file"]))
        run.check(True, "the next mail previews the next Wykonawca's file")

    run.step(FEATURE, "po-wysylce")
    dialog.get_by_role("button", name=f"Wyślij {len(to_send)}", exact=True).click()
    expect(page.get_by_text(f"Wysłano {len(to_send)} rozlicz", exact=False)).to_be_visible()
    for worker in to_send:
        expect(_row(table, worker)).to_contain_text("Wysłane")
    mails = until(lambda: (found if len(found := _mails(run.root)) == len(to_send) else None), "the atrapa SMTP took every mail")
    for worker, message in zip(to_send, mails, strict=True):
        [attachment] = list(message.iter_attachments())
        row = rows[worker]
        run.check(
            (message["To"], message["Subject"], attachment.get_content_type(), attachment.get_filename())
            == (", ".join(row["addresses"]), DEFAULT_SUBJECT, XLSX, row["file"])
            and attachment.get_content() == read_bytes(folder / str(row["file"])),
            "each Wykonawca gets his own file, byte for byte, on his addresses, with the subject from Ustawienia",
        )
    after = _period(run, "wysylka-po")
    run.check(
        all(row["state"]["state"] == "sent" for row in after["rows"] if row["worker"] in to_send) and after["to_send"] == 0,
        "the server reads every mail from „Wysłane” as sent by Centrum",
    )
    log = run.log()
    run.check(
        log.count(f"rozliczenie-wyslane okres={READY_PERIOD}") == len(to_send)
        and not [worker for worker in rows if worker in log],
        "the Centrum log has one line per mail with the period token, without names",
    )
    run.capture(page, "502-wysylka-po", full_page=False)

    run.step(FEATURE, "bez-powtorki")
    again = run.post(f"/api/settlement-mailing/{READY_PERIOD}/send", "wysylka-powtorka", {"worker": to_send[0], "resend": False})
    run.check(
        again.status == 200 and again.body["sent_now"] is False and len(_mails(run.root)) == len(to_send),
        "a second send of a file already sent and unchanged sends nothing",
    )


def _settings(run: Run, page: Page) -> None:
    run.step(FEATURE, "ustawienia")
    window = open_settings(page, "Wysyłka rozliczeń")
    subject = window.get_by_role("textbox", name="Temat maila z rozliczeniem")
    expect(subject).to_have_value("Rozliczenie za {okres}")
    subject.fill("Raport za {okres}")
    window.get_by_role("button", name="Zapisz wysyłkę rozliczeń").click()
    expect(window.get_by_role("alert")).to_have_text(REPORT_WORD)
    run.check(not (run.config / "wysylka-rozliczen.yaml").exists(), "a subject with „raport” is refused and nothing is saved")
    subject.fill("Rozliczenie {wykonawca} za {okres}")
    window.get_by_role("button", name="Zapisz wysyłkę rozliczeń").click()
    expect(window.get_by_role("alert")).to_have_count(0)
    preview = window.get_by_role("region", name="Podgląd maila z rozliczeniem")
    expect(preview).to_contain_text("Rozliczenie Wykonawca Testowy A za")
    saved = run.api("/api/settings", "wysylka-ustawienia")["settlement_mail"]
    assert isinstance(saved, dict)
    run.check(saved["subject"] == "Rozliczenie {wykonawca} za {okres}", "the subject is saved and the preview fills its fields")
    run.capture(page, "503-wysylka-ustawienia", full_page=False)
    close_settings(page)
