"""Drive features/zgloszenie.md."""

from __future__ import annotations

import json
from pathlib import Path
import re

from playwright.sync_api import Locator, Page, expect

from drive import kontrola_ilosci
from drive.common import (
    ROW_MARKER,
    Run,
    current_run,
    drop_report_key,
    edit_issue,
    ended_run_shown,
    ensure_files_set,
    finished_result,
    move,
    period_choice,
    remove,
    stop_banner,
)

FEATURE = "zgloszenie"
# The period of features/diagnoza.md: no Folder okresu and no orders, so no Uruchomienie here writes a file.
PERIOD = "08_14_09_2026"
TEMPLATE_MISSING = "Nie znaleziono wzorca, z którego powstają pliki okresu."
NOT_FOUND = "Nie znalazłem przyczyny na tym komputerze."
TITLE = f"BRAK_WZORCA: {TEMPLATE_MISSING} Nie utworzono żadnego pliku."
# The one element of Uwaga taty, Zgłoszenie and Powiadomienia when the Token do Zgłoszeń is missing or refused (Q17).
FOR_KEY = "Token do Zgłoszeń nie działa. Skontaktuj się z Maksem."
FOR_INTERNET = "Zgłoszenie czeka na internet. Wyśle się samo."
REJECTED = "Tego Zgłoszenia nie da się wysłać. Skontaktuj się z Maksem."
SENT = "Zgłoszenie wysłane do Maksa. Poczekaj na naprawę."
WAITING = "Zgłoszenie tego problemu już jest wysłane i czeka na naprawę."
# Heading of the comment the queue adds to the open Zgłoszenie when its problem returns (ADR 0007, #820).
RETURNED = "## Zgłoszenie wróciło\n\n"
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"


def _stop_for_maks(run: Run, page: Page, name: str, missing: str = "internal_template") -> str:
    """A stop „do Maksa” whose cause is gone again: the Wzorzec ``missing`` was missing during the run.

    Another Wzorzec gives the same code with other three parts, so another problem.
    """

    configuration = run.fixture["configuration"]
    assert isinstance(configuration, dict)
    template = Path(configuration[missing])
    aside = template.with_name(f"{template.name}.odlozony")
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    if ended_run_shown(current_run(run, f"{name}-przed")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
    page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
    page.get_by_role("combobox", name="Okres").click()
    page.get_by_role("option", name=period_choice(PERIOD, "Brak plików okresu"), exact=True).click()
    move(template, aside)
    try:
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(stop_banner(page)).to_contain_text(TEMPLATE_MISSING)
        result = finished_result(run, name)
    finally:
        move(aside, template)
    run.check(result["stop_kind"] == "for_maks", "the stop without its Wzorzec is „do Maksa”")
    view = current_run(run, name)["run"]
    assert isinstance(view, dict)
    return str(view["id"])


def _report_state(run: Run, name: str) -> object:
    return finished_result(run, name)["report"]


def _issues(box: Path) -> list[dict[str, object]]:
    """This feature's Zgłoszenia (``BRAK_WZORCA``) in the skrzynka by number.

    A Kontrola ilości from features/kontrola-ilosci.md takes numbers too, and the Zgłoszenie features/diagnoza.md
    left in the queue goes out once this feature writes the key.
    """

    issues = [json.loads(path.read_text(encoding="utf-8")) for path in box.glob("*.json")]
    ours = (issue for issue in issues if issue["labels"] == ["zgloszenie"] and str(issue["title"]).startswith("BRAK_WZORCA:"))
    return sorted(ours, key=lambda issue: int(str(issue["number"])))


def _queued_reports(queue: Path) -> list[dict[str, object]]:
    """Zgłoszenia waiting in the queue of the skrzynka, oldest first (the Logi of each Uruchomienie wait beside them)."""

    posts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(queue.glob("*-zgloszenie-*.json"))]
    return [post for post in posts if str(post["target"]["title"]).startswith("BRAK_WZORCA:")]


def _queued_text(post: dict[str, object]) -> tuple[object, str]:
    """A queued Zgłoszenie as it will reach the skrzynka: the issue title and the parts joined."""

    target, parts = post["target"], post["parts"]
    assert isinstance(target, dict) and isinstance(parts, list)
    return target["title"], "".join(str(part) for part in parts)


def _advance_clock(run: Run) -> None:
    """Centrum's clock moves a minute on, so the queue of the skrzynka wakes and tries again at once."""

    moved = run.root / "zegar" / "przesuniecie-min.txt"
    moved.parent.mkdir(exist_ok=True)
    before = float(moved.read_text(encoding="utf-8")) if moved.exists() else 0.0
    moved.write_text(str(before + 1), encoding="utf-8")
    print("  harness: Centrum's clock moves a minute on, past the queue's retry", flush=True)


def _sent(config: Path) -> list[dict[str, object]]:
    """Sent Zgłoszenia from the local state of Dad's cases; the fingerprint is their ``id``."""

    cases = json.loads((config / "sprawy-taty.json").read_text(encoding="utf-8"))["sprawy"]
    return [case for case in cases if case["kind"] == "zgloszenie"]


def _shown_report(page: Page) -> tuple[str, str]:
    """The Zgłoszenie as the tab shows it under „Co zostanie wysłane”: title and Markdown body."""

    shown: Locator = page.get_by_role("figure", name="Treść Zgłoszenia")
    return shown.locator("figcaption").inner_text(), shown.locator("pre").inner_text()


def drive_report(run: Run, page: Page) -> None:
    config = Path(run.fixture["settings"]).parent
    key_file = config / "zgloszenia-klucz.txt"
    queue = config / "zgloszenia" / "kolejka"
    box = run.root / "skrzynka-zgloszen"
    diagnosis = page.get_by_role("region", name="Diagnoza")
    drop_report_key(key_file, missing_ok=True)

    run.step(FEATURE, "zgloszenie-podglad")
    page.goto(run.url)
    ensure_files_set(run, page)
    first_run = _stop_for_maks(run, page, "zgloszenie-podglad")
    run.check(_report_state(run, "zgloszenie-podglad") == {"state": "ready"}, "the stop offers a Zgłoszenie not sent yet")
    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
    send = diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)
    expect(send).to_be_visible()
    diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
    title, body = _shown_report(page)
    run.check(title == TITLE, "the Zgłoszenie title is the code and „Co się stało”")
    lines = body.splitlines()
    run.check(
        all(line in lines for line in ("- Kod: BRAK_WZORCA", f"- Okres: {PERIOD}", "- Tryb: DRY-RUN")),
        "the preview holds the Komunikat code, the period, and the mode",
    )
    run.check(
        any(line.startswith("| Aktualność narzędzia |") for line in lines)
        and any(line.startswith("- Commit: ") for line in lines),
        "the preview holds the tool commit and every check of the Diagnoza",
    )
    run.check(
        ROW_MARKER not in body and str(run.root) not in body and run.root.as_posix() not in body,
        "the preview holds no workbook row and no full path",
    )
    run.check(
        f"- Logi: jeszcze niewysłane, Uruchomienie {first_run}" in lines,
        "without a key the Logi of this Uruchomienie wait in the queue, and the preview says so with its identifier",
    )
    run.capture(page, "60-zgloszenie-podglad")

    run.step(FEATURE, "zgloszenie-bez-klucza")
    send.click()
    expect(diagnosis.get_by_role("status").filter(has_text=FOR_KEY)).to_be_visible()
    expect(page.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_have_count(0)
    expect(page.get_by_label("Ostrzeżenie")).to_have_count(0)
    [queued] = _queued_reports(queue)
    run.check(_queued_text(queued) == (title, body), "the queued Zgłoszenie is exactly the preview")
    run.check(
        [path.name for path in (config / "zgloszenia").iterdir()] == ["kolejka"],
        "the folder zgloszenia holds only the queue, no Markdown file",
    )
    run.check(_issues(box) == [], "without a key nothing reaches the skrzynka Zgłoszeń")
    run.check(
        _report_state(run, "zgloszenie-bez-klucza") == {"state": "queued", "waits_for": "key"},
        "the server keeps the queued state, waiting for the key, in the result",
    )
    run.capture(page, "61-zgloszenie-bez-klucza")
    page.locator("header").get_by_role("button", name="Powiadomienia", exact=False).click()
    rows = page.get_by_role("list", name="Powiadomienia").get_by_role("listitem", name=f"Zgłoszenie: {title.split(': ', 1)[1]}")
    expect(rows.filter(has_text=FOR_KEY)).to_have_count(1)
    run.capture(page, "61b-zgloszenie-bez-klucza-powiadomienia")

    run.step(FEATURE, "zgloszenie-konfiguracja")
    page.get_by_role("link", name="Konfiguracja", exact=True).click()
    expect(page.get_by_text("Zgłoszenia: brak tokenu", exact=True)).to_be_visible()
    run.capture(page, "62-zgloszenie-konfiguracja-brak-klucza")
    print("  harness: Maks writes the key to config/zgloszenia-klucz.txt", flush=True)
    key_file.write_text(KEY + "\n", encoding="utf-8")
    page.reload()
    expect(page.get_by_text("Zgłoszenia: gotowe", exact=True)).to_be_visible()
    configuration = run.api("/api/configuration", "zgloszenie-konfiguracja")
    run.check(configuration["reports"] == "ready", "Konfiguracja reports the key as ready")
    run.check(KEY not in json.dumps(configuration) and KEY not in page.content(), "the key value never reaches the browser")
    run.capture(page, "63-zgloszenie-konfiguracja-gotowe")
    refusing = box / "odmawia-klucza"
    print("  harness: the skrzynka refuses the key Maks writes next (an expired token)", flush=True)
    box.mkdir(exist_ok=True)  # run alone, nothing reached the skrzynka yet
    refusing.touch()
    key_file.write_text(KEY + "_WYGASLY\n", encoding="utf-8")
    page.reload()
    expect(page.get_by_text("Zgłoszenia: token odrzucony", exact=True)).to_be_visible()
    refused = run.api("/api/configuration", "zgloszenie-konfiguracja-odrzucony")
    run.check(refused["reports"] == "refused_key", "Konfiguracja reports the refused key")
    run.capture(page, "63b-zgloszenie-konfiguracja-odrzucony")
    print("  harness: Maks writes a new key the skrzynka accepts", flush=True)
    remove(refusing)
    key_file.write_text(KEY + "\n", encoding="utf-8")
    page.reload()
    expect(page.get_by_text("Zgłoszenia: gotowe", exact=True)).to_be_visible()

    run.step(FEATURE, "zgloszenie-wyslane")
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    _advance_clock(run)
    expect(page.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    expect(page.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_have_count(0)
    run.wait_for(lambda: _queued_reports(queue) == [], "the delivered Zgłoszenie leaves the queue")
    [issue] = _issues(box)
    number = issue["number"]
    (run.evidence / "api" / "zgloszenie-skrzynka.json").write_text(
        json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(
        (issue["title"], issue["body"], issue["labels"]) == (title, body, ["zgloszenie"]),
        "the skrzynka got exactly the preview, labelled zgloszenie",
    )
    sent = _sent(config)
    run.check(
        [entry["number"] for entry in sent if f"- Odcisk problemu: {entry['id']}" in body.splitlines()] == [number],
        "the local sent state keeps the fingerprint and, once delivered, the issue number",
    )
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    run.check(
        f"skrzynka-wyslano etykieta=zgloszenie okres={PERIOD} numer={number}" in log, "the Centrum log records the sending"
    )
    run.check(KEY not in log and KEY not in json.dumps(issue), "the key is neither in the log nor in the Zgłoszenie")
    run.capture(page, "64-zgloszenie-wyslane")

    run.step(FEATURE, "zgloszenie-po-odswiezeniu")
    page.reload()
    expect(page.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    run.check(_report_state(run, "zgloszenie-po-odswiezeniu") == {"state": "sent"}, "the confirmation survives a reload")
    run.capture(page, "65-zgloszenie-po-odswiezeniu")

    run.step(FEATURE, "zgloszenie-kolejne-uruchomienie")
    again = _stop_for_maks(run, page, "zgloszenie-kolejne-uruchomienie")
    expect(page.get_by_role("status").filter(has_text=WAITING)).to_be_visible()
    run.check(
        _report_state(run, "zgloszenie-kolejne-uruchomienie") == {"state": "waiting"},
        "the same problem in a new Uruchomienie shows it is already sent and waits for the fix",
    )
    _logs_sent(run, queue, again)
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
    expect(diagnosis.get_by_role("status").filter(has_text=WAITING)).to_be_visible()
    expect(page.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_have_count(0)
    run.wait_for(
        lambda: _issues(box)[0].get("comments", []) != [], "the return of the problem reaches the open Zgłoszenie with no click"
    )
    issues = _issues(box)
    (run.evidence / "api" / "zgloszenie-skrzynka-powrot.json").write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(len(issues) == 1, "no second Zgłoszenie of the same problem")
    [returned] = issues
    comments = returned.get("comments", [])
    assert isinstance(comments, list)
    returned_body = str(comments[0]).removeprefix(RETURNED)
    fingerprint = [line for line in body.splitlines() if line.startswith("- Odcisk problemu: ")]
    run.check(
        len(comments) == 1
        and str(comments[0]).startswith(RETURNED + "Zgłoszenie z Centrum rozliczeń.\n")
        and [line for line in returned_body.splitlines() if line.startswith("- Odcisk problemu: ")] == fingerprint
        and "## Diagnoza" in returned_body.splitlines(),
        "the open Zgłoszenie has one comment „Zgłoszenie wróciło” with the whole Zgłoszenie of the returned problem",
    )
    _check_logs_link(run, box, returned_body, again)
    run.check(
        _report_state(run, "zgloszenie-kolejne-uruchomienie-po-diagnozie") == {"state": "waiting"},
        "Dad still sees that the Zgłoszenie waits for the fix",
    )
    run.capture(page, "66-zgloszenie-kolejne-uruchomienie")
    _one_open_report(run, page, box, config)
    drop_report_key(key_file)


def _logs_sent(run: Run, queue: Path, run_id: str) -> None:
    """Waits until the Logi of Uruchomienie ``run_id`` left the queue, so the next Diagnoza links their comment."""

    run.wait_for(
        lambda: not list(queue.glob(f"*-logi-uruchomienia-{run_id[:8]}.json")),
        "with the key the Logi of this Uruchomienie reach the skrzynka",
        timeout_s=60,
    )


def _check_logs_link(run: Run, box: Path, body: str, run_id: str) -> None:
    """The Zgłoszenie ``body`` links the comment of the Logi of Uruchomienie ``run_id`` in the skrzynka."""

    links = [line.removeprefix("- Logi: ") for line in body.splitlines() if line.startswith("- Logi: ")]
    run.check(
        len(links) == 1 and re.fullmatch(r"skrzynka-zgloszen/\d+\.json#komentarz-\d+", links[0]) is not None,
        f"the Zgłoszenie has one Logi line with the address of a comment in the skrzynka: {links}",
    )
    thread, _, comment = links[0].removeprefix("skrzynka-zgloszen/").partition(".json#komentarz-")
    logs = json.loads((box / f"{thread}.json").read_text(encoding="utf-8"))
    run.check(
        logs["labels"] == ["logi-uruchomienia"]
        and f"- Uruchomienie: {run_id}," in logs["comments"][int(comment) - 1],
        f"the Zgłoszenie links the comment of the Logi of its own Uruchomienie ({links[0]})",
    )


def _one_open_report(run: Run, page: Page, box: Path, config: Path) -> None:
    """Maks closes the Zgłoszenie, the problem returns: a new Zgłoszenie links the previous one."""

    diagnosis = page.get_by_role("region", name="Diagnoza")

    run.step(FEATURE, "zgloszenie-zamkniete")
    [first] = _issues(box)
    number = first["number"]
    print(f"  harness: Maks closes Zgłoszenie {number} in the skrzynka Zgłoszeń", flush=True)
    edit_issue(box, number, state="closed")
    run_id = _stop_for_maks(run, page, "zgloszenie-zamkniete")
    expect(page.get_by_role("status").filter(has_text=WAITING)).to_be_visible()
    _logs_sent(run, config / "zgloszenia" / "kolejka", run_id)
    run.capture(page, "68-zgloszenie-zamkniete-przed-diagnoza")
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    send = diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)
    expect(send).to_be_visible()
    expect(page.get_by_role("status").filter(has_text=WAITING)).to_have_count(0)
    run.check(
        _report_state(run, "zgloszenie-zamkniete") == {"state": "ready"},
        "after the Diagnoza asked the skrzynka, the closed Zgłoszenie lets Dad send again",
    )
    diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
    title, body = _shown_report(page)
    run.check(f"- Poprzednie Zgłoszenie: #{number}" in body.splitlines(), "the new Zgłoszenie links the previous one")
    _check_logs_link(run, box, body, run_id)
    run.capture(page, "69-zgloszenie-zamkniete-po-diagnozie")

    run.step(FEATURE, "zgloszenie-nowe-z-odnosnikiem")
    send.click()
    expect(page.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    issues = _issues(box)
    (run.evidence / "api" / "zgloszenie-skrzynka-nowe.json").write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(
        [(issue["number"], issue["state"]) for issue in issues] == [(number, "closed"), (issues[-1]["number"], "open")]
        and (issues[1]["title"], issues[1]["body"]) == (title, body),
        "the skrzynka got exactly the new preview as a second Zgłoszenie next to the closed one",
    )
    sent = _sent(config)
    run.check(
        {issue["number"] for issue in issues} <= {entry["number"] for entry in sent},
        "the local sent state keeps both Zgłoszenia",
    )
    run.capture(page, "70-zgloszenie-nowe-z-odnosnikiem")

    run.step(FEATURE, "zgloszenie-inny-problem")
    _stop_for_maks(run, page, "zgloszenie-inny-problem", missing="collective_template")
    run.check(
        _report_state(run, "zgloszenie-inny-problem") == {"state": "ready"},
        "another problem (other three parts) is not waiting for the open Zgłoszenie",
    )
    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_be_visible()
    run.check(len(_issues(box)) == 2, "asking the skrzynka sends nothing")
    run.capture(page, "71-zgloszenie-inny-problem")

    run.step(FEATURE, "zgloszenie-bez-sieci")
    diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
    title, body = _shown_report(page)
    offline = box / "brak-sieci"
    print("  harness: the network goes down", flush=True)
    offline.touch()
    try:
        diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True).click()
        expect(diagnosis.get_by_role("status").filter(has_text=FOR_INTERNET)).to_be_visible()
        run.check(
            _report_state(run, "zgloszenie-bez-sieci") == {"state": "queued", "waits_for": "internet"},
            "without network the Zgłoszenie waits in the queue for the internet",
        )
        run.check(len(_issues(box)) == 2, "without network nothing reaches the skrzynka")
        run.capture(page, "72-zgloszenie-bez-sieci")
    finally:
        print("  harness: the network comes back", flush=True)
        remove(offline)
    _advance_clock(run)
    expect(diagnosis.get_by_role("status").filter(has_text=SENT)).to_be_visible()
    issues = _issues(box)
    run.check(
        len(issues) == 3 and (issues[-1]["title"], issues[-1]["body"]) == (title, body),
        "once the network is back the Zgłoszenie sends itself, exactly the preview, with no click",
    )
    run.capture(page, "73-zgloszenie-bez-sieci-wyslane")
    _rejected_report(run, page, box, config)


def _notification_ids(run: Run, name: str) -> set[str]:
    items = run.api("/api/notifications", name)["items"]
    assert isinstance(items, list)
    return {str(item["id"]) for item in items}


def _rejected_report(run: Run, page: Page, box: Path, config: Path) -> None:
    """The skrzynka rejects the content of a Zgłoszenie: Dad is told to contact Maks, and the next start retries it."""

    diagnosis = page.get_by_role("region", name="Diagnoza")
    queue = config / "zgloszenia" / "kolejka"

    run.step(FEATURE, "zgloszenie-odrzucone")
    newest = _issues(box)[-1]
    print(f"  harness: Maks closes Zgłoszenie {newest['number']}; the skrzynka rejects the content of every Zgłoszenie", flush=True)
    edit_issue(box, newest["number"], state="closed")
    rejecting = box / "odrzuca-zgloszenie"
    rejecting.touch()
    try:
        _stop_for_maks(run, page, "zgloszenie-odrzucone", missing="collective_template")
        page.reload()
        stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
        diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
        title, body = _shown_report(page)
        diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True).click()
        status = diagnosis.get_by_role("status").filter(has_text=REJECTED)
        expect(status).to_be_visible()
        run.check(status.locator("svg").count() == 1, "the rejection shows the error icon beside its sentence")
        expect(diagnosis.get_by_text(FOR_INTERNET, exact=True)).to_have_count(0)
        run.check(
            _report_state(run, "zgloszenie-odrzucone") == {"state": "rejected"},
            "the server says the skrzynka rejected the Zgłoszenie, not that it waits for the internet",
        )
        run.check([_queued_text(post) for post in _queued_reports(queue)] == [(title, body)], "the rejected Zgłoszenie stays in the queue")
        run.check(len(_issues(box)) == 3, "the skrzynka got no new Zgłoszenie")
        run.capture(page, "74-zgloszenie-odrzucone")
        page.locator("header").get_by_role("button", name="Powiadomienia", exact=False).click()
        rows = page.get_by_role("list", name="Powiadomienia").get_by_role("listitem", name=f"Zgłoszenie: {title.split(': ', 1)[1]}")
        expect(rows.filter(has_text=REJECTED)).to_have_count(1)
        run.capture(page, "74b-zgloszenie-odrzucone-powiadomienia")
    finally:
        remove(rejecting, missing_ok=True)

    run.step(FEATURE, "zgloszenie-odrzucone-po-starcie")
    kontrola_ilosci._close(run, page)
    kontrola_ilosci._start(run, "zgloszenie-start-po-odrzuceniu")
    run.wait_for(lambda: _queued_reports(queue) == [], "at the next start the queue tries the rejected Zgłoszenie again", timeout_s=30)
    issues = _issues(box)
    run.check(
        len(issues) == 4 and (issues[-1]["title"], issues[-1]["body"]) == (title, body),
        "once the skrzynka takes it, the Zgłoszenie is exactly the preview",
    )
    sent_id = f"zgloszenie-{issues[-1]['number']}-wyslana"
    run.wait_for(
        lambda: sent_id in _notification_ids(run, "zgloszenie-odrzucone-po-starcie"),
        "Powiadomienia show the Zgłoszenie the skrzynka took after the start as sent",
    )
    page.goto(run.url + "#/powiadomienia")
    page.reload()
    expect(page.get_by_role("list", name="Powiadomienia")).to_be_visible()
    expect(rows.filter(has_text=REJECTED)).to_have_count(0)
    run.capture(page, "75-zgloszenie-odrzucone-po-starcie")
