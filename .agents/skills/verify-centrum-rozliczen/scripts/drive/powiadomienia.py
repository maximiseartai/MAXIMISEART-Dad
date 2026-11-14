"""Drive features/powiadomienia.md."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import subprocess
import sys

from playwright.sync_api import Locator, Page, expect

from drive import uwaga_taty, zgloszenie
from drive.common import (
    PAGES,
    REPORT_KEY,
    advance_clock,
    box_issues,
    drop_report_key,
    edit_issue,
    error_toasts,
    read_json,
    read_text,
    release_only,
    remove,
    Run,
    toggle_theme,
)
from drive.waiting import Budget, until
from drive.teksty import BELL_FRESH, UPDATE_BUTTON, UP_TO_DATE, WRITE
from atrapy.pliki_taty import DAD_CASES_FILE, NOTIFICATIONS_FILE, REPORT_KEY_FILE
from harness import File, Log, Switch

FEATURE = "powiadomienia"
BELL = "Powiadomienia"
RESOLVED = "Rozwiązana. Będzie w następnej wersji."
READ = "Maks przeczytał."
SENT_NOTE = "Uwaga wysłana do Maksa."
CLOSED_AT = "2026-10-19T09:15:00Z"
INTRO = "Ta wersja przyspiesza rozliczenia."
POINTS = (
    "Plik zbiorczy ma kolumnę z kilometrami.",
    "Rozliczenia pracowników przy dużym okresie są dwa razy szybsze.",
    "Centrum rozliczeń pokazuje „Co nowego” jako listę punktów.",
)
# The note „Co nowego” as the skill `wydanie` writes it: an optional intro sentence, then one point per `- ` line.
SUMMARY = "\n".join([INTRO, "", *(f"- {point}" for point in POINTS)])
WHATS_NEW = "Co nowego"
FIRST_SUMMARY = "Pierwsza wersja z Powiadomieniami. Tutaj zobaczysz, co Maks zrobił z Twoimi Uwagami i Zgłoszeniami."
# A Wydanie GitHub names as the newest on `main` that the update does not take: the clone never had this commit.
DORMANT_RELEASE = "e" * 40
CASE_LABELS = ("zgloszenie", "uwaga-taty")
# Centrum's state files in `config/` that Powiadomienia write: Dad's cases and the read Powiadomienia.
STATE_FILES = (DAD_CASES_FILE, NOTIFICATIONS_FILE)


def _release(tag: str, body: str, published_at: str) -> dict[str, object]:
    """One entry of GitHub's list of Releases, in GitHub's shape."""

    return {"tag_name": tag, "body": body, "published_at": published_at, "draft": False, "prerelease": False}


def _publish(run: Run, newest_tag: str, newest_commit: str | None, releases: list[dict[str, object]]) -> None:
    """The scripted GitHub: the newest Wydanie on `main` (``None``: the tool's own commit) and the list of Releases."""

    File.RELEASE_TAG.write(run.root, newest_tag)
    if newest_commit is None:
        remove(File.MAIN_COMMIT.file(run.root), missing_ok=True)
    else:
        File.MAIN_COMMIT.write(run.root, newest_commit)
    File.RELEASES.write(run.root, json.dumps(releases, ensure_ascii=False, indent=2) + "\n")


def _release_questions(run: Run) -> int:
    return len(run.lines(Log.RELEASE_QUESTIONS))


def _expect_points(item: Locator) -> None:
    """The card or row of v0.2.0 shows the heading „Co nowego”, its intro, and each point as its own list item."""

    whats_new = item.get_by_role("region", name=WHATS_NEW, exact=True)
    expect(whats_new.get_by_role("heading", name=WHATS_NEW, exact=True)).to_be_visible()
    expect(whats_new.get_by_role("paragraph")).to_have_text(INTRO)
    expect(whats_new.get_by_role("listitem")).to_have_text(list(POINTS))


def _versions(run: Run, name: str) -> list[tuple[object, object, object]]:
    items = run.api("/api/notifications", name)["items"]
    assert isinstance(items, list)
    return [(item["version"], item["update_offered"], item["unread"]) for item in items if item["kind"] == "nowa_wersja"]


def _asked(run: Run) -> list[str]:
    """Labels of every question about Dad's cases, closed ones included; Logi Uruchomienia ask the same way."""

    return [label for label in (record["label"] for record in run.lines(Log.REPORT_QUESTIONS)) if label in CASE_LABELS]


def _close_issue(run: Run, number: int, reason: str) -> None:
    """Maks closes issue ``number`` in the skrzynka with GitHub's ``state_reason``."""

    edit_issue(run, number, state="closed", state_reason=reason, closed_at=CLOSED_AT)


def _bell(page: Page) -> Locator:
    return page.locator("header").get_by_role("button", name=BELL, exact=False)


def _row(page: Page, kind: str, name: str) -> Locator:
    return page.get_by_role("list", name=BELL).get_by_role("listitem", name=f"{kind}: {name}", exact=True)


def _enter(page: Page, run: Run, page_id: str, heading: str) -> None:
    page.goto(run.url + f"#/{page_id}")
    page.reload()
    expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")


def drive(run: Run, page: Page) -> None:
    config = run.config
    key_file = config / REPORT_KEY_FILE
    box = run.box
    key_file.write_text(REPORT_KEY + "\n", encoding="utf-8")
    notes = box_issues(run, uwaga_taty.LABEL)
    reports = zgloszenie.reports(run)
    note, report = notes[-1], next(issue for issue in reports if issue["state"] == "open")
    report_what = str(report["title"]).split(": ", 1)[1]

    run.step(FEATURE, "powiadomienia-dzwonek")
    advance_clock(run, 10, "the next read may ask the skrzynka again")
    for page_id, heading in PAGES.items():
        _enter(page, run, page_id, heading)
        bell, write = _bell(page), page.get_by_role("button", name=WRITE, exact=True)
        expect(bell).to_be_visible()
        bell_box, write_box = bell.bounding_box(), write.bounding_box()
        run.check(
            bell_box is not None and write_box is not None and write_box["x"] < bell_box["x"],
            f"{heading}: the bell sits right of „{WRITE}”",
        )
    answer = run.api("/api/notifications", "powiadomienia-wyslane")
    items = answer["items"]
    assert isinstance(items, list)
    run.check(
        {"kind": "uwaga", "title": note["title"], "state": {"state": "sent"}, "unread": False}.items()
        <= next(item for item in items if item.get("title") == note["title"]).items(),
        "the sent Uwaga is a Powiadomienie, sent and not new",
    )
    run.check(
        any(item.get("what") == report_what and item["state"] == {"state": "sent"} for item in items),
        "the open Zgłoszenie is a Powiadomienie named by its „Co się stało”, without the code",
    )
    run.check(answer["unread"] == sum(item["unread"] for item in items), "the unread count is the new Powiadomienia")
    run.capture(page, "180-powiadomienia-dzwonek")

    run.step(FEATURE, "powiadomienia-zamkniete")
    print(f"  harness: Maks closes Uwaga #{note['number']} as completed and Zgłoszenie #{report['number']} as not planned", flush=True)
    _close_issue(run, int(str(note["number"])), "completed")
    _close_issue(run, int(str(report["number"])), "not_planned")
    advance_clock(run, 10, "the next read may ask the skrzynka again")
    asked = len(_asked(run))
    _enter(page, run, "okresy", "Okresy")
    expect(_bell(page)).to_have_accessible_name(BELL_FRESH)
    run.check(len(_asked(run)) <= asked + 2, "the 10 minutes passed, so Centrum asks once per kind of case")
    after_first = len(_asked(run))
    run.check(after_first > asked, "Centrum asked the skrzynka about Dad's open cases")
    _enter(page, run, "uruchomienia", "Uruchomienia")
    run.check(len(_asked(run)) == after_first, "a second read within 10 minutes does not ask the skrzynka again")
    run.capture(page, "181-powiadomienia-kropka")
    header = page.locator("header").first.bounding_box()
    assert header is not None
    run.capture(
        page,
        "181b-powiadomienia-kropka-zblizenie",
        clip={"x": header["x"] + header["width"] - 240, "y": header["y"], "width": 240, "height": header["height"]},
    )

    run.step(FEATURE, "powiadomienia-oznaczenie-bez-odpowiedzi")
    page.route("**/api/notifications/read", lambda route: route.abort())
    try:
        _bell(page).click()
        expect(page.get_by_role("heading", name=BELL, exact=True)).to_be_visible()
        expect(error_toasts(page)).to_contain_text("Centrum rozliczeń nie odpowiada.")
        run.check(True, "marking the Powiadomienia read without an answer (unreachable, harness) says so in a notification")
        run.capture(page, "181c-powiadomienia-oznaczenie-bez-odpowiedzi")
    finally:
        page.unroute("**/api/notifications/read")
    run.check(
        int(str(run.api("/api/notifications", "powiadomienia-nieoznaczone")["unread"])) > 0,
        "the Powiadomienia stay new on the server, so the dot on the bell is true",
    )
    _enter(page, run, "okresy", "Okresy")
    expect(_bell(page)).to_have_accessible_name(BELL_FRESH)

    run.step(FEATURE, "powiadomienia-widok")
    _bell(page).click()
    expect(page.get_by_role("heading", name=BELL, exact=True)).to_be_visible()
    run.check(page.url.endswith("#/powiadomienia"), "the bell opens the view Powiadomienia in the same tab")
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    expect(menu.get_by_role("link", name=BELL)).to_have_count(0)
    expect(menu.locator("[aria-current=page]")).to_have_count(0)
    # The Zgłoszenie that zgloszenie closed has the same „Co się stało”; the state tells the two rows apart.
    note_row = _row(page, "Uwaga", str(note["title"])).filter(has_text=RESOLVED)
    report_row = _row(page, "Zgłoszenie", report_what).filter(has_text=READ)
    expect(note_row).to_have_count(1)
    expect(report_row).to_have_count(1)
    for row in (note_row, report_row):
        expect(row.get_by_label("nowe", exact=True)).to_be_visible()
        run.check(row.get_attribute("data-fresh") == "true", "a new row keeps its light background while Dad stays")
    expect(_bell(page)).to_have_accessible_name(BELL)
    until(
        lambda: run.api("/api/notifications", "powiadomienia-przeczytane")["unread"] == 0,
        "entering the view marks every Powiadomienie read",
    )
    stored = read_json(config / NOTIFICATIONS_FILE)
    run.check(stored["schema_version"] == 1 and len(stored["przeczytane"]) >= 2, f"config/{NOTIFICATIONS_FILE} keeps them")
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(error_toasts(page)).to_have_count(0)
    run.capture(page, "182-powiadomienia-widok")
    toggle_theme(page)
    expect(note_row.get_by_label("nowe", exact=True)).to_be_visible()
    run.capture(page, "183-powiadomienia-widok-drugi-motyw")
    toggle_theme(page)

    run.step(FEATURE, "powiadomienia-po-wyjsciu")
    page.get_by_role("link", name="Okresy", exact=True).click()
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    _bell(page).click()
    expect(page.get_by_role("heading", name=BELL, exact=True)).to_be_visible()
    expect(page.get_by_role("list", name=BELL).get_by_label("nowe", exact=True)).to_have_count(0)
    expect(_bell(page)).to_have_accessible_name(BELL)

    run.step(FEATURE, "powiadomienia-brak-sieci")
    offline = Switch.BOX_OFFLINE.on(run.root)
    try:
        _close_issue(run, int(str(notes[0]["number"])), "completed")
        advance_clock(run, 10, "the next read may ask the skrzynka again")
        asked = len(_asked(run))
        _enter(page, run, "powiadomienia", BELL)
        run.check(len(_asked(run)) > asked, "after 10 minutes Centrum asks again")
        expect(_row(page, "Uwaga", str(notes[0]["title"]))).to_contain_text(SENT_NOTE)
        expect(page.get_by_role("alert")).to_have_count(0)
        expect(error_toasts(page)).to_have_count(0)
        expect(_bell(page)).to_have_accessible_name(BELL)
        run.capture(page, "184-powiadomienia-brak-sieci")
    finally:
        remove(offline, missing_ok=True)
    try:
        _drive_new_version(run, page, note, report, report_what)
    finally:
        for scripted in (File.RELEASE_TAG, File.MAIN_COMMIT, File.RELEASES, Switch.GITHUB_OFFLINE):
            remove(scripted.file(run.root), missing_ok=True)
    _drive_unavailable_files(run, page, config, box)
    log = run.log()
    run.check(REPORT_KEY not in log and REPORT_KEY not in page.content(), "the key is neither in the Centrum log nor in the browser")
    drop_report_key(key_file)


def _drive_new_version(run: Run, page: Page, note: dict[str, object], report: dict[str, object], what: str) -> None:
    run.step(FEATURE, "powiadomienia-nowa-wersja")
    notes = "\n".join(
        [
            SUMMARY,
            "",
            "## Rozwiązane sprawy taty",
            "",
            f"- Uwaga taty #{note['number']}: {note['title']}",
            f"- Zgłoszenie #{report['number']}: {report['title']}",
            "- Uwaga taty #999: Uwaga z innego komputera",
        ]
    )
    print(
        "  harness: GitHub's newest Wydanie on `main` is v0.2.0 on a commit the update does not take, with v0.1.0"
        " before it and v0.3.0 published from outside `main`",
        flush=True,
    )
    releases = [
        _release("v0.3.0", "Wydanie spoza main.", "2026-10-23T08:00:00Z"),
        _release("v0.2.0", notes, "2026-10-22T08:00:00Z"),
        _release("v0.1.0", FIRST_SUMMARY, "2026-10-08T08:00:00Z"),
    ]
    _publish(run, "v0.2.0", DORMANT_RELEASE, releases)
    advance_clock(run, 10, "the next read may ask the skrzynka again")
    asked = _release_questions(run)
    _enter(page, run, "okresy", "Okresy")
    expect(_bell(page)).to_have_accessible_name(BELL_FRESH)
    _enter(page, run, "uruchomienia", "Uruchomienia")
    run.check(_release_questions(run) == asked + 1, "after 10 minutes Centrum asks GitHub for the Wydania once")
    _bell(page).click()
    card = page.get_by_role("region", name="Nowa wersja 0.2.0", exact=True)
    _expect_points(card)
    solved = card.get_by_role("list", name="Rozwiązane sprawy").get_by_role("listitem")
    expect(solved).to_have_text([f"Uwaga: {note['title']}", f"Zgłoszenie: {what}"])
    expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_enabled()
    # In `all` the features before this one leave `Masz najnowszą wersję.` from an older Wydanie (#373).
    run.check(
        run.api("/api/tool-update", "powiadomienia-nowa-wersja-aktualizacja")["state"] != "up_to_date",
        "the button of a newer Wydanie has no earlier `Masz najnowszą wersję.`",
    )
    expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_have_count(0)
    expect(card.get_by_label("nowe", exact=True)).to_be_visible()
    listed = page.get_by_role("list", name=BELL)
    card_box, list_box = card.bounding_box(), listed.bounding_box()
    run.check(card_box is not None and list_box is not None and card_box["y"] < list_box["y"], "the card stands above the list")
    older = listed.get_by_role("listitem", name="Nowa wersja 0.1.0", exact=True)
    # A note without points (every Wydanie before this card) stays one paragraph under the heading.
    expect(older.get_by_role("region", name=WHATS_NEW, exact=True).get_by_role("paragraph")).to_have_text(FIRST_SUMMARY)
    expect(older.get_by_role("listitem")).to_have_count(0)
    expect(older.get_by_role("button")).to_have_count(0)
    expect(page.get_by_text("Nowa wersja 0.3.0")).to_have_count(0)
    expect(page.get_by_text("Uwaga z innego komputera")).to_have_count(0)
    until(
        lambda: run.api("/api/notifications", "powiadomienia-nowa-wersja-przeczytane")["unread"] == 0,
        "entering the view marks the Wydania read",
    )
    run.check(
        _versions(run, "powiadomienia-nowa-wersja") == [("0.2.0", True, False), ("0.1.0", False, False)],
        "the newest Wydanie on `main` offers the update, the older one does not, the one from outside `main` is no"
        " Powiadomienie, and entering the view marked both read",
    )
    expect(page.get_by_role("alert")).to_have_count(0)
    run.capture(page, "185-powiadomienia-nowa-wersja")
    toggle_theme(page)
    expect(card).to_be_visible()
    run.capture(page, "186-powiadomienia-nowa-wersja-drugi-motyw")
    toggle_theme(page)

    run.step(FEATURE, "powiadomienia-aktualizacja")
    tool = run.fixture["tool"]
    clone = Path(tool["clone"])
    head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    print("  harness: the newest Wydanie in the local origin is the clone's own commit", flush=True)
    release_only(Path(tool["origin"]), head)
    updates = run.log().count("aktualizacja-koniec")
    card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
    until(
        lambda: run.log().count("aktualizacja-koniec") == updates + 1,
        "the card's button starts the Aktualizacja narzędzia",
    )
    expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_be_visible()
    last = run.log_entries()[-1]
    run.check(
        last.event == "aktualizacja-koniec" and last.facts.get("wynik") == "AKTUALNA",
        "the update does not take a Wydanie that never was the tip of `main`, so the tool stays where it is",
    )
    run.check(
        subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        == head,
        "the clone stays on its commit",
    )
    run.capture(page, "187-powiadomienia-aktualizacja")

    run.step(FEATURE, "powiadomienia-wydanie-aktualne")
    print("  harness: the newest Wydanie on `main` is v0.2.0 on the tool's own commit (Dad is on it)", flush=True)
    _publish(run, "v0.2.0", None, releases)
    advance_clock(run, 10, "the next read may ask the skrzynka again")
    _enter(page, run, "powiadomienia", BELL)
    expect(page.get_by_role("region", name="Nowa wersja 0.2.0", exact=True)).to_have_count(0)
    current = page.get_by_role("list", name=BELL).get_by_role("listitem", name="Nowa wersja 0.2.0", exact=True)
    _expect_points(current)
    expect(current.get_by_role("button")).to_have_count(0)
    expect(current.get_by_label("nowe", exact=True)).to_have_count(0)
    expect(_bell(page)).to_have_accessible_name(BELL)
    run.check(
        _versions(run, "powiadomienia-wydanie-aktualne") == [("0.2.0", False, False), ("0.1.0", False, False)],
        "a Wydanie Dad is on stays in the history, read, without the button",
    )
    run.capture(page, "188-powiadomienia-wydanie-aktualne")

    run.step(FEATURE, "powiadomienia-wydania-brak-sieci")
    Switch.GITHUB_OFFLINE.on(run.root)
    advance_clock(run, 10, "the next read may ask the skrzynka again")
    asked = _release_questions(run)
    _enter(page, run, "powiadomienia", BELL)
    run.check(_release_questions(run) == asked + 1, "after 10 minutes Centrum asks GitHub again")
    expect(page.get_by_role("list", name=BELL).get_by_role("listitem", name="Nowa wersja 0.2.0", exact=True)).to_be_visible()
    expect(page.get_by_role("list", name=BELL).get_by_role("listitem", name="Nowa wersja 0.1.0", exact=True)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(error_toasts(page)).to_have_count(0)
    expect(_bell(page)).to_have_accessible_name(BELL)
    run.check(
        _versions(run, "powiadomienia-wydania-brak-sieci") == [("0.2.0", False, False), ("0.1.0", False, False)],
        "without network the Powiadomienia about Wydania stay as they were, with no Komunikat",
    )
    run.capture(page, "189-powiadomienia-wydania-brak-sieci")


@contextmanager
def _locked(files: Sequence[Path]) -> Iterator[None]:
    """Harness: another program holds ``files``, so Centrum cannot rename its new content onto them; always undone."""

    if sys.platform == "win32":
        # Python opens without FILE_SHARE_DELETE, so Windows refuses os.replace onto the file, as with Dad's antivirus.
        print("  harness: the drive holds the files open", flush=True)
        with ExitStack() as handles:
            for path in files:
                handles.enter_context(path.open("rb"))
            yield
    elif sys.platform == "darwin":
        print("  harness: the files are immutable (chflags uchg)", flush=True)
        try:
            subprocess.run(["chflags", "uchg", *map(str, files)], check=True)
            yield
        finally:
            subprocess.run(["chflags", "nouchg", *map(str, files)], check=True)
    else:
        # Linux has no per-file lock without root (chattr +i); a read-only folder refuses Centrum's temporary file.
        folder = files[0].parent
        mode = folder.stat().st_mode
        print("  harness: the config folder is read-only", flush=True)
        try:
            folder.chmod(0o555)
            yield
        finally:
            folder.chmod(mode)


def _drive_unavailable_files(run: Run, page: Page, config: Path, box: Path) -> None:
    run.step(FEATURE, "powiadomienia-plik-niedostepny")
    files = [config / name for name in STATE_FILES]
    note = next(issue for issue in box_issues(run, uwaga_taty.LABEL) if issue["state"] == "open")
    print(f"  harness: Maks closes Uwaga #{note['number']} while another program holds both state files", flush=True)
    _close_issue(run, int(str(note["number"])), "completed")
    advance_clock(run, 10, "the next read may ask the skrzynka again")
    with _locked(files):
        before = [read_text(path) for path in files]
        _enter(page, run, "powiadomienia", BELL)

        def both_named() -> bool:
            message = run.api("/api/notifications", "powiadomienia-plik-niedostepny")["message"]
            return isinstance(message, dict) and all(name in str(message["where"]) for name in STATE_FILES)

        until(both_named, "Powiadomienia name both state files Centrum could not save", Budget.SLOWED)
        answer = run.api("/api/notifications", "powiadomienia-plik-niedostepny")
        message, items = answer["message"], answer["items"]
        assert isinstance(message, dict) and isinstance(items, list)
        read_ids = {
            str(item["id"])
            for item in items
            if item["kind"] == "uwaga" and item["title"] == note["title"] and item["state"] == {"state": "resolved"}
        }
        run.check(bool(read_ids), "Centrum learned that Maks closed the Uwaga")
        page.reload()
        expect(page.get_by_role("heading", name=BELL, exact=True)).to_be_visible()
        notice = page.get_by_label("Komunikat", exact=True)
        for part in ("what", "where", "action"):
            expect(notice).to_contain_text(str(message[part]))
        for name in STATE_FILES:
            expect(notice).to_contain_text(name)
        expect(notice).to_contain_text("niedostępn")
        run.check("uszkodzon" not in notice.inner_text(), "a held file is niedostępny, never uszkodzony")
        expect(_row(page, "Uwaga", str(note["title"])).filter(has_text=RESOLVED)).to_have_count(1)
        expect(error_toasts(page)).to_have_count(0)
        run.check(
            [read_text(path) for path in files] == before,
            "while the files are held, Centrum does not pretend it saved them",
        )
        run.capture(page, "201-powiadomienia-plik-niedostepny")
    print("  harness: the other program lets the files go", flush=True)
    _enter(page, run, "powiadomienia", BELL)
    expect(page.get_by_label("Komunikat", exact=True)).to_have_count(0)
    run.check(
        run.api("/api/notifications", "powiadomienia-plik-zapisany")["message"] is None,
        "the next read of Powiadomienia saves both files and the Komunikat is gone",
    )
    stored = read_json(config / NOTIFICATIONS_FILE)
    run.check(read_ids <= set(stored["przeczytane"]), f"config/{NOTIFICATIONS_FILE} now keeps the Uwaga read")
    cases = read_json(config / DAD_CASES_FILE)["sprawy"]
    run.check(
        any(case["number"] == note["number"] and (case["closure"] or {}).get("reason") == "completed" for case in cases),
        f"config/{DAD_CASES_FILE} now keeps Maks's closing of the Uwaga",
    )
    run.capture(page, "202-powiadomienia-plik-zapisany")
