"""The drive's shared run state and the helpers more than one feature uses."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from fnmatch import fnmatchcase
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, Request, expect
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
# Pages of the sidebar menu in its order: contract id (`#/<id>`, `PageId`) and the heading Dad reads.
PAGES = {"okresy": "Okresy", "uruchomienia": "Uruchomienia", "metryki": "Metryki", "konfiguracja": "Konfiguracja"}
# Dad's computer runs on Polish time; dates in Centrum are shown in the browser's time zone.
DAD_TIME_ZONE = ZoneInfo("Europe/Warsaw")
# The fixture's last complete period, without a Folder okresu.
LAST_COMPLETE = "06_12_10_2026"
# The fixture puts this marker in every synthetic workbook row; it must never reach the Centrum log.
ROW_MARKER = "CENTRUM-SYN-ROW"
# Dad double-clicks out of habit and double-taps the touch screen: the second click comes within milliseconds,
# so a repeated request is sent well within this, and an answer reaches the screen (a refusal as a toast) too.
REPEAT_SETTLE_MS = 300
# Dad's return to Centrum's window: the pages read the server again (`useResource`).
FOCUS = "window.dispatchEvent(new Event('focus'))"


class DriveFailure(Exception):
    pass


class Run:
    def __init__(self, root: Path, url: str, evidence: Path) -> None:
        self.root = root
        self.url = url
        self.evidence = evidence
        self.fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
        self.feature = ""
        # Feature files and PRs cite a screenshot by its number, so one number belongs to one feature.
        self._number_owners: dict[str, str] = {}
        for name in ("screenshots", "aria", "api", "state"):
            (evidence / name).mkdir(parents=True, exist_ok=True)

    def step(self, feature: str, name: str) -> None:
        self.feature = feature
        print(f"STEP {feature} | {name}", flush=True)

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise DriveFailure(message)
        print(f"  ok: {message}", flush=True)

    def capture(self, page: Page, name: str, *, full_page: bool = True, live: bool = False) -> None:
        """Screenshot and ARIA snapshot after every running transition has finished.

        ``live`` captures while a stage runs: its indeterminate bar loops forever, so do not wait.
        """

        number = name.split("-", 1)[0]
        owner = self._number_owners.setdefault(number, self.feature)
        if owner != self.feature:
            raise DriveFailure(f"screenshot {name} of {self.feature} uses number {number}, which belongs to {owner}")
        if not live:
            page.wait_for_function(
                "document.getAnimations().every((animation) => animation.playState !== 'running')"
            )
        page.screenshot(path=self.evidence / "screenshots" / f"{name}.png", full_page=full_page)
        snapshot = page.locator("body").aria_snapshot()
        (self.evidence / "aria" / f"{name}.txt").write_text(snapshot + "\n", encoding="utf-8")

    def api(self, path: str, name: str) -> dict[str, object]:
        with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=10) as response:
            body = json.load(response)
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert isinstance(body, dict)
        return body

    def refused(self, request: urllib.request.Request, name: str) -> int:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, body = int(response.status), response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        record = {"status": status, "body": json.loads(body or b"null")}
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return status

    def answer_picker(self, path: str) -> None:
        (self.root / "picker" / "answer.txt").write_text(path, encoding="utf-8")

    def lines(self, name: str) -> list[dict[str, str]]:
        log = self.root / name
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]

    def settings_text(self) -> str:
        settings = Path(self.fixture["settings"])
        return settings.read_text(encoding="utf-8") if settings.exists() else ""

    def remembered(self, key: str) -> object:
        """One value of the settings file as Centrum wrote it (``folder_okresow``, ``rejestr_zlecen``, ``motyw``)."""

        document = yaml.safe_load(self.settings_text()) or {}
        assert isinstance(document, dict)
        return document.get(key)

    def wait_for(self, condition: Callable[[], bool], message: str, timeout_s: float = 10) -> None:
        deadline = time.monotonic() + timeout_s
        while not condition():
            if time.monotonic() > deadline:
                raise DriveFailure(f"timed out: {message}")
            time.sleep(0.1)
        print(f"  ok: {message}", flush=True)


def choose_periods_directory(run: Run, page: Page) -> None:
    run.answer_picker(run.fixture["periods_directory"])
    page.get_by_role("button", name="Wskaż folder okresów", exact=True).click()
    expect(page.get_by_role("table", name="Tablica okresów")).to_be_visible()


def ensure_files_set(run: Run, page: Page) -> None:
    """Points Centrum to the fixture's folder okresów and Rejestr zleceń unless a feature before did."""

    settings = run.api("/api/settings", "ustawienia-przed-uruchomieniem")
    if settings["periods_directory"] == {"state": "not_set"}:
        choose_periods_directory(run, page)
    if settings["order_register"] == {"state": "not_set"}:
        run.answer_picker(run.fixture["order_register"])
        page.get_by_role("button", name="Wskaż Rejestr zleceń", exact=True).click()
        run.wait_for(lambda: run.remembered("rejestr_zlecen") == run.fixture["order_register"], "Rejestr zleceń set")


def period_choice(token: str, status: str) -> str:
    """A period in the combobox ``Okres`` as Dad reads it: ``wt 06.10 – pon 12.10 · ostatni pełny · 06_12_10_2026``.

    The days come from the token itself (the Monday's day, month and year; the Tuesday six days earlier), not from
    the server's answer, so a wrong date on screen fails the drive.
    """

    _, monday_day, month, year = token.split("_")
    monday = date(int(year), int(month), int(monday_day))
    tuesday = monday - timedelta(days=6)
    return f"wt {tuesday:%d.%m} – pon {monday:%d.%m} · {status} · {token}"


def period_row(page: Page, token: str) -> Locator:
    return page.get_by_role("table", name="Tablica okresów").get_by_role("row").filter(has_text=token)


# The Wycena w efenix metrics file of the run (`serve_centrum.py`): its Historia, from which the Droga okresu counts it.
EFENIX_METRICS = ".wycena-efenix-metrics.jsonl"


@contextmanager
def priced_in_efenix(run: Run, token: str) -> Iterator[None]:
    """Harness: a Wycena w efenix of ``token`` with the result OK in the run's Historia (one record of metrics schema 2,
    which the reader still takes), and the file as it was afterwards, so later features count the same history."""

    path = run.root / EFENIX_METRICS
    before = path.read_bytes() if path.exists() else None
    counters = dict.fromkeys(("orders", "ready", "errors", "emmett_warnings", "with_photos", "defects"), 0)
    record = {
        "schema_version": 2, "started_at": "2026-10-13T10:00:00+02:00", "mode": "RUN", "period": token,
        "completed": True, "result": "OK", "total_duration_ms": 1000,
        "phase_durations_ms": dict.fromkeys(("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"), 0),
        "counters": counters, "stop": None,
    }
    path.write_bytes((before or b"") + json.dumps(record).encode() + b"\n")
    try:
        yield
    finally:
        if before is None:
            path.unlink()
        else:
            path.write_bytes(before)


def last_opened_is(run: Run, path: Path) -> Callable[[], bool]:
    return lambda: run.lines("opened.jsonl")[-1:] == [{"path": str(path)}]


def history_rows(page: Page) -> Locator:
    return page.get_by_role("table", name="Historia Uruchomień procesu").get_by_role("row")


def period_files(run: Run) -> list[Path]:
    folder = Path(run.fixture["periods_directory"]) / LAST_COMPLETE
    return [
        folder / f"Rozliczenie wew. {LAST_COMPLETE}.xlsx",
        folder / f"Rozliczenie {LAST_COMPLETE} - zbiorcze.xlsx",
    ]


def current_run(run: Run, name: str) -> dict[str, object]:
    view = run.api("/api/runs/current", name)
    assert isinstance(view, dict)
    return view


def ended_run_shown(view: dict[str, object]) -> bool:
    """Uruchomienia shows an ended Uruchomienie instead of the setup card: one that finished, or the last one from
    before Centrum's start (``RunIdle.previous``); `Nowe Uruchomienie procesu` sets it aside."""

    return view["state"] == "finished" or (view["state"] == "idle" and view["previous"] is not None)


def finished_result(run: Run, name: str) -> dict[str, object]:
    # One answer for both the state and the result: a second read could already see the next Uruchomienie.
    seen: dict[str, object] = {}

    def finished() -> bool:
        seen.clear()
        seen.update(current_run(run, name))
        return seen["state"] == "finished"

    run.wait_for(finished, "the Uruchomienie procesu finished")
    result = seen["result"]
    assert isinstance(result, dict)
    return result


def figure(shown: object, label: str) -> int:
    """Value of the number labelled ``label`` in a server view's ``figures`` (live progress or result summary)."""

    assert isinstance(shown, dict)
    [value] = [entry["value"] for entry in shown["figures"] if entry["label"] == label]
    assert isinstance(value, int)
    return value


def active_run_signs(page: Page, label: str) -> tuple[Locator, Locator]:
    """The sign of the current Uruchomienie beside `Uruchomienia` in the menu and the header's link to it."""

    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    header = page.locator("header").first
    return menu.get_by_role("img", name=label, exact=True), header.get_by_role("link", name=label, exact=True)


def stop_banner(page: Page) -> Locator:
    """The three-part stop banner of the Uruchomienie procesu shown on Uruchomienia."""

    return page.get_by_role("region", name="Podgląd na żywo").get_by_label("Zatrzymanie")


def start_card_warns_while_open(
    run: Run,
    page: Page,
    *,
    process: str,
    workbook: Path,
    warning: str,
    reminder: str,
    name: str,
    shots: tuple[str, str],
) -> None:
    """The start card warns while ``workbook``, the process's data file, is open in Excel and stops when Dad closes it.

    The card shows the server's ``open_in_excel`` for the chosen period (``LAST_COMPLETE``), turns off „Uruchom”,
    keeps „Podgląd bez zapisu” and the footer's ``reminder`` about that file. Excel is not driven: the harness adds
    and removes its lock file ``~$<name>``, then fires ``focus`` as Dad's return to the window does.
    """

    lock = workbook.with_name(f"~${workbook.name}")
    warned = page.get_by_role("alert").filter(has_text=warning)
    start = page.get_by_role("button", name="Uruchom", exact=True)
    preview = page.get_by_role("button", name="Podgląd bez zapisu", exact=True)

    def shown(answer: str) -> tuple[object, object]:
        processes = run.api("/api/runs/setup", answer)["processes"]
        assert isinstance(processes, list)
        [setup] = [setup for setup in processes if setup["process"] == process]
        [choice] = [choice for choice in setup["periods"] if choice["token"] == LAST_COMPLETE]
        return choice["open_in_excel"], choice["reminder"]

    lock.touch()
    print(f"  harness: Excel opens {workbook.name}, so its lock file is next to it; Dad returns to Centrum", flush=True)
    try:
        page.evaluate(FOCUS)
        expect(warned).to_have_text(warning)
        expect(start).to_be_disabled()
        expect(preview).to_be_enabled()
        expect(page.get_by_text(reminder, exact=True)).to_be_visible()
        run.check(
            shown(f"{name}-otwarty-w-excelu") == ([warning], reminder),
            f"the start card names {workbook.name} open in Excel; Uruchom is off, Podgląd bez zapisu stays on, and "
            "the footer still reminds to close it",
        )
        run.capture(page, shots[0])
    finally:
        lock.unlink(missing_ok=True)
    print(f"  harness: Excel closes {workbook.name}, so its lock file is gone; Dad returns to Centrum", flush=True)
    page.evaluate(FOCUS)
    expect(warned).to_have_count(0)
    expect(start).to_be_enabled()
    run.check(
        shown(f"{name}-zamkniety") == ([], reminder),
        f"after {workbook.name} is closed the warning is gone without a reload and Uruchom is on again",
    )
    run.capture(page, shots[1])


def diagnosis_answer(run: Run, run_id: str, name: str) -> dict[str, object]:
    """The server's Diagnoza for ``run_id`` as the browser gets it, kept in ``api/``."""

    request = urllib.request.Request(
        run.url.rstrip("/") + f"/api/runs/{run_id}/diagnosis",
        data=b"",
        method="POST",
        headers={"Origin": run.url.rstrip("/")},
    )
    run.check(run.refused(request, name) == 200, "the server answers the Diagnoza")
    record = json.loads((run.evidence / "api" / f"{name}.json").read_text(encoding="utf-8"))
    body = record["body"]
    assert isinstance(body, dict)
    return body


@contextmanager
def sent_requests(page: Page, method: str, path: str) -> Iterator[list[Request]]:
    """Requests the page sends with ``method`` to ``path`` (a glob such as ``/api/runs/*/decision``) in the block."""

    sent: list[Request] = []

    def record(request: Request) -> None:
        if request.method == method and fnmatchcase(urlsplit(request.url).path, path):
            sent.append(request)

    page.on("request", record)
    try:
        yield sent
    finally:
        page.remove_listener("request", record)


@contextmanager
def unreadable(path: Path) -> Iterator[None]:
    """Harness: the system refuses to read ``path`` without changing its bytes, size or modification time; always undone."""

    if sys.platform == "win32":
        import msvcrt

        # A byte-range lock makes every other read of the file fail, as when another program holds it.
        print(f"  harness: the drive locks the bytes of {path.name}", flush=True)
        size = path.stat().st_size
        with path.open("rb") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, size)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, size)
    else:
        print(f"  harness: {path.name} has no permissions (chmod 0)", flush=True)
        mode = path.stat().st_mode
        path.chmod(0)
        try:
            yield
        finally:
            path.chmod(mode)


def settle(page: Page, sent: list[Request]) -> int:
    """Waits until a repeated click would have sent its request and every answer reached the screen; the count."""

    page.wait_for_timeout(REPEAT_SETTLE_MS)
    for request in list(sent):
        request.response()
    page.wait_for_timeout(REPEAT_SETTLE_MS)
    return len(sent)


def error_toasts(page: Page) -> Locator:
    """Error notifications („Nie udało się …”), also those stacked behind the newest one."""

    return page.get_by_role("region", name="Notifications").get_by_role("dialog", name="Nie udało się")


def served_version(run: Run) -> tuple[str, str | None]:
    """The tool commit the served Centrum runs and the day the run's tool clone moved to it, as Git reports them.

    The commit is the clone's ``HEAD`` unless a feature pinned another one in
    ``<root>/github/tool-commit.txt``. The day (``YYYY-MM-DD``) is the last ``HEAD`` reflog entry's, in that entry's
    time zone, when that entry leads to the commit, else ``None``. Neither depends on how Centrum reads ``.git``.
    """

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", run.fixture["tool"]["clone"], *arguments], capture_output=True, text=True, check=True
        ).stdout.strip()

    pinned = run.root / "github" / "tool-commit.txt"
    commit = pinned.read_text(encoding="utf-8").strip() if pinned.exists() else git("rev-parse", "HEAD")
    entry_commit, _, selector = git("log", "--walk-reflogs", "-1", "--date=short", "--format=%H %gd").partition(" ")
    return commit, selector.removeprefix("HEAD@{").removesuffix("}") if entry_commit == commit else None


def version_line(commit: str, since: str | None) -> str:
    """The version line Dad reads in the card ``Narzędzie``: ``Wersja 1a2b3c4 od 20.10.2026``."""

    if since is None:
        return f"Wersja {commit[:7]}"
    year, month, day = since.split("-")
    return f"Wersja {commit[:7]} od {day}.{month}.{year}"


def release_only(origin: Path, commit: str) -> None:
    """GitHub's only Wydanie, as Centrum's Aktualizacja narzędzia sees it, is ``commit``: tag ``v0.1.0`` in ``origin``.

    A real Wydanie never moves; the harness withdraws every tag instead, so one tag is always the newest. ``main``
    moves to ``commit`` too, because Centrum refuses a Wydanie that is not on ``main`` and the run's versions sit on
    side branches of the origin.
    """

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(origin), *args], capture_output=True, text=True, check=True).stdout

    tags = git("tag", "--list", "v*").split()
    if tags:
        git("tag", "--delete", *tags)
    git("tag", "v0.1.0", commit)
    git("update-ref", "refs/heads/main", commit)
