"""Drive features/kontrola-ilosci.md."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import Page, expect

from drive import przebieg_rozliczen
from drive.common import LAST_COMPLETE, REPO_ROOT, ROW_MARKER, Run, drop_report_key, remove

FEATURE = "kontrola-ilosci"
LABEL = "kontrola-ilosci"
# Synthetic key Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"
SERVE = REPO_ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "serve_centrum.py"
# Long enough to load Okresy in the tab while the skrzynka still holds the Kontrola sent again at start.
BOX_PACING_MS = 4000


def _queued(config: Path) -> list[Path]:
    """Kontrole ilości in the queue; the Logi Uruchomienia of every Uruchomienie wait there in their own files."""

    return sorted((config / "zgloszenia" / "kolejka").glob(f"*-{LABEL}-*.json"))


def _log(run: Run) -> str:
    path = run.root / "logs" / "centrum-rozliczen.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _offline_waits(run: Run) -> int:
    lines = _log(run).splitlines()
    return sum(" skrzynka-czeka " in line and line.endswith(" przyczyna=brak-sieci") for line in lines)


def _checks_in_box(box: Path) -> list[dict[str, object]]:
    issues = [json.loads(path.read_text(encoding="utf-8")) for path in box.glob("*.json")]
    return sorted((issue for issue in issues if issue["labels"] == [LABEL]), key=lambda issue: int(str(issue["number"])))


def _answers(run: Run) -> bool:
    try:
        with urllib.request.urlopen(run.url.rstrip("/") + "/api/health", timeout=2):
            return True
    except OSError:
        return False


def _close(run: Run, page: Page) -> None:
    """Dad closes Centrum from the sidebar in the evening, as in features/start-i-zamykanie.md."""

    page.goto(run.url)
    page.get_by_role("button", name="Zamknij Centrum rozliczeń", exact=True).click()
    page.get_by_role("button", name="Zamknij Centrum", exact=True).click()
    expect(page.get_by_role("heading", name="Centrum rozliczeń jest zamknięte", exact=True)).to_be_visible()
    run.wait_for(lambda: not _answers(run), "Centrum stops serving")


def _start(run: Run, name: str) -> None:
    """The next morning Dad clicks the shortcut.

    Harness: the shortcut's launcher would start Dad's own Centrum, so the drive starts this run's scripted Centrum
    on the same port (``serve_centrum.py``, as the restart guardian's shim does after an update). Cleanup stops it
    through ``server.json``.
    """

    port = json.loads((run.root / "server.json").read_text(encoding="utf-8"))["port"]
    print("  harness: Dad starts Centrum again (this run's scripted Centrum on the same port)", flush=True)
    with (run.evidence / "api" / f"{name}-server.txt").open("wb") as console:
        subprocess.Popen(
            [sys.executable, str(SERVE), "--root", str(run.root), "--port", str(port)],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=console,
            stderr=subprocess.STDOUT,
        )
    run.wait_for(lambda: _answers(run), "Centrum answers again after the start", timeout_s=30)


def _open_periods(page: Page, run: Run) -> None:
    """Dad's tab after the start: the closed screen stays until the page loads again."""

    page.goto(run.url + "#/okresy")
    page.reload()
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()


def drive_quantity_check(run: Run, page: Page) -> None:
    config = Path(run.fixture["settings"]).parent
    key_file = config / "zgloszenia-klucz.txt"
    box = run.root / "skrzynka-zgloszen"
    offline = box / "brak-sieci"
    pacing = run.root / "pacing" / "skrzynka-ms.txt"
    if not _queued(config):
        print("  harness: no Kontrola ilości waits yet, so przebieg-rozliczen runs first", flush=True)
        przebieg_rozliczen.drive_settlement(run, page)
    checks_before = len(_checks_in_box(box))

    run.step(FEATURE, "kontrola-w-kolejce")
    [waiting] = _queued(config)
    document = json.loads(waiting.read_text(encoding="utf-8"))
    run.check(
        document["target"]["label"] == LABEL and document["period"] == LAST_COMPLETE,
        f"the RUN of {LAST_COMPLETE} left its Kontrola ilości in config/zgloszenia/kolejka",
    )
    run.check(
        f" skrzynka-w-kolejce etykieta={LABEL} okres={LAST_COMPLETE}\n" in _log(run),
        "the Centrum log says the Kontrola ilości of the RUN went into the queue",
    )
    run.check(
        any(" skrzynka-czeka " in line and line.endswith(" przyczyna=brak-klucza") for line in _log(run).splitlines()),
        "without a key the Centrum log says the queue waits (one line per pass, naming its first file), with no content",
    )
    run.check(
        sorted(path.name for path in (config / "zgloszenia").iterdir()) == ["kolejka"],
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
    key_file.write_text(KEY + "\n", encoding="utf-8")
    offline.parent.mkdir(exist_ok=True)
    offline.touch()
    _close(run, page)
    waited = _offline_waits(run)
    _start(run, "kontrola-start-bez-sieci")
    # The first failure ends the pass, and the Logi Uruchomienia queued before the Kontrola go first.
    run.wait_for(
        lambda: _offline_waits(run) > waited, "at start Centrum tries the queue again and the Kontrola keeps waiting"
    )
    run.check(_queued(config) == [waiting], "the Kontrola file stays after another failure")
    run.check(len(_checks_in_box(box)) == checks_before, "nothing reached the skrzynka")
    _open_periods(page, run)
    expect(page.get_by_role("alert")).to_have_count(0)
    run.capture(page, "151-kontrola-bez-sieci-po-starcie")

    run.step(FEATURE, "kontrola-wyslana-po-starcie")
    print(f"  harness: the internet is back; the skrzynka answers after {BOX_PACING_MS} ms", flush=True)
    remove(offline)
    pacing.parent.mkdir(exist_ok=True)
    pacing.write_text(str(BOX_PACING_MS), encoding="utf-8")
    try:
        _close(run, page)
        sent_before = _log(run).count(f"skrzynka-wyslano etykieta={LABEL}")
        started = time.monotonic()
        _start(run, "kontrola-start-wysylka")
        _open_periods(page, run)
        shown_after_s = time.monotonic() - started
        run.check(
            _log(run).count(f"skrzynka-wyslano etykieta={LABEL}") == sent_before,
            f"Okresy is shown {shown_after_s:.1f} s after the start, before the skrzynka took the Kontrola",
        )
        run.capture(page, "152-kontrola-start-bez-czekania")
        run.wait_for(
            lambda: f"skrzynka-wyslano etykieta={LABEL} okres={LAST_COMPLETE}" in _log(run),
            "the Kontrola sent again at start reaches the skrzynka in the background",
            timeout_s=30,
        )
    finally:
        remove(pacing, missing_ok=True)
    checks = _checks_in_box(box)
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
    run.wait_for(lambda: _queued(config) == [], "the sent Kontrola file is removed")
    log = _log(run)
    run.check(KEY not in log and ROW_MARKER not in log, "the Centrum log has neither the key nor workbook content")
    run.check(KEY not in body, "the key is not in the Kontrola")
    drop_report_key(key_file)
