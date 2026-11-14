"""The drive's shared run state and the helpers more than one feature uses."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
from typing import Any, NamedTuple
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Browser, BrowserContext, ConsoleMessage, FloatRect, Locator, Page, Request, Response, ViewportSize
import yaml

from drive import feature
from drive.waiting import LATE_WRITE_MS, Budget, expect, quiet_for, until, while_open
from harness import SLOW_RUNNER, File, Log, issue_file, report_box
from atrapy.scenariusz_centrum import LAST_COMPLETE
from atrapy.pliki_taty import QUEUE_DIRECTORY, RUN_LOGS_DIRECTORY
from rozliczenia.centrum.case_delivery import queue_directory
from rozliczenia.centrum.outbox import queue_file_pattern
from rozliczenia.tool_files import log_path
from atrapy.workbooks import excel_lock

REPO_ROOT = Path(__file__).resolve().parents[5]
SERVE = REPO_ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "serve_centrum.py"
# Pages of the sidebar menu in its order: contract id (`#/<id>`, `PageId`) and the heading Dad reads.
PAGES = {
    "okresy": "Okresy",
    "uruchomienia": "Uruchomienia",
    "raporty": "Raporty",
    "metryki": "Metryki",
}
# Dad's computer runs on Polish time; dates in Centrum are shown in the browser's time zone.
DAD_TIME_ZONE = ZoneInfo("Europe/Warsaw")
# Dad's screen: the drive's tab and every other tab it opens unless a feature needs another window.
DAD_VIEWPORT: ViewportSize = {"width": 1440, "height": 1000}
# Dad's return to Centrum's window: the pages read the server again (`useResource`).
FOCUS = "window.dispatchEvent(new Event('focus'))"
# Harness: the page reports itself hidden, so the Uruchomienia stream pauses and its next view arrives late.
HIDE_TAB = (
    "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});"
    "document.dispatchEvent(new Event('visibilitychange'))"
)
SHOW_TAB = "delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange'))"
# Synthetic Token do Zgłoszeń Maks would write; it must never reach the skrzynka, the log, an answer, or the browser.
REPORT_KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ"


class DriveFailure(Exception):
    pass


class Answer(NamedTuple):
    status: int
    body: Any


@dataclass(frozen=True)
class LogEntry:
    """One line of the Centrum log: ``<moment> <event> key=value …``, a value with a space in quotes (``log.py``).

    ``text`` is the line without its moment, as written.
    """

    event: str
    facts: dict[str, str]
    text: str


_FACT = re.compile(r'([^\s=]+)=("[^"]*"|\S*)')


def log_entries(path: Path) -> list[LogEntry]:
    """The entries of the Centrum log at ``path`` in order; no log yet has none."""

    lines = read_text(path).splitlines() if path.exists() else []
    entries = []
    for line in lines:
        _, _, text = line.partition(" ")
        event, _, facts = text.partition(" ")
        values = {key: value[1:-1] if value.startswith('"') else value for key, value in _FACT.findall(facts)}
        entries.append(LogEntry(event, values, text))
    return entries


class Run:
    def __init__(self, root: Path, url: str, evidence: Path) -> None:
        self.root = root
        self.url = url
        self.evidence = evidence
        self.fixture = read_json(File.FIXTURE.file(root))
        self.feature = ""
        for name in ("screenshots", "aria", "api", "state"):
            (evidence / name).mkdir(parents=True, exist_ok=True)

    @property
    def config(self) -> Path:
        """The run's ``config/`` beside Dad's settings file: the key, the queue and Centrum's state files."""

        return Path(self.fixture["settings"]).parent

    @property
    def box(self) -> Path:
        """The scripted skrzynka Zgłoszeń: one ``<number>.json`` per issue (``serve_centrum.py``)."""

        return report_box(self.root)

    @property
    def queue(self) -> Path:
        """The queue of the skrzynka Zgłoszeń: one file per post waiting to be sent, which the next Wydanie sends."""

        return self.config / QUEUE_DIRECTORY

    @property
    def run_logs_dir(self) -> Path:
        """The Logi Uruchomienia beside the Centrum log (ADR 0015): one file per Uruchomienie procesu."""

        return self.log_path.parent / RUN_LOGS_DIRECTORY

    @property
    def log_path(self) -> Path:
        return log_path(self.root)

    def log(self) -> str:
        """The Centrum log as written so far; no log yet is an empty one."""

        return read_text(self.log_path) if self.log_path.exists() else ""

    def log_entries(self) -> list[LogEntry]:
        return log_entries(self.log_path)

    def step(self, feature: str, name: str) -> None:
        self.feature = feature
        print(f"STEP {feature} | {name}", flush=True)

    def check(self, condition: bool, message: str, /) -> None:
        if not condition:
            raise DriveFailure(message)
        print(f"  ok: {message}", flush=True)

    def capture(
        self, page: Page, name: str, *, full_page: bool = True, live: bool = False, clip: FloatRect | None = None
    ) -> None:
        """Screenshot and ARIA snapshot after every running transition has finished.

        ``live`` captures while a stage runs: its indeterminate bar loops forever, so do not wait.
        ``clip`` takes a close-up of that part of the viewport instead of the page. ``name`` is one of the current
        feature's ``screenshots`` in ``FEATURES``, which give each number to one feature.
        """

        if name not in feature(self.feature).screenshots:
            raise DriveFailure(f"screenshot {name} is not among the screenshots of {self.feature} in drive/__init__.py")
        if not live:
            page.wait_for_function(
                "document.getAnimations().every((animation) => animation.playState !== 'running')"
            )
        page.screenshot(
            path=self.evidence / "screenshots" / f"{name}.png", full_page=full_page and clip is None, clip=clip
        )
        snapshot = page.locator("body").aria_snapshot()
        (self.evidence / "aria" / f"{name}.txt").write_text(snapshot + "\n", encoding="utf-8")

    def api(self, path: str, name: str) -> dict[str, object]:
        with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=Budget.SCREEN.value) as response:
            body = json.load(response)
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert isinstance(body, dict)
        return body

    def refused(self, request: urllib.request.Request, name: str) -> int:
        """The status of ``request``, which the drive builds itself (a foreign ``Origin`` or ``Host``)."""

        return self._send(request, name).status

    def post(self, path: str, name: str, body: object = None) -> Answer:
        headers = {"Origin": self.url.rstrip("/")} | ({} if body is None else {"Content-Type": "application/json"})
        data = b"" if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url.rstrip("/") + path, data=data, method="POST", headers=headers)
        return self._send(request, name)

    def _send(self, request: urllib.request.Request, name: str) -> Answer:
        try:
            with urllib.request.urlopen(request, timeout=Budget.SCREEN.value) as response:
                status, body = int(response.status), response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        answer = Answer(status, json.loads(body or b"null"))
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(answer._asdict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return answer

    def answer_picker(self, path: str) -> None:
        File.PICKER_ANSWER.write(self.root, path)

    def lines(self, log: Log) -> list[dict[str, str]]:
        """The records the served Centrum appended to ``log``, none before the first."""

        path = log.file(self.root)
        if not path.exists():
            return []
        return [json.loads(line) for line in read_text(path).splitlines() if line]

    def settings_text(self) -> str | None:
        """The settings file as the server last put it in place (``read_text``), ``None`` before Centrum wrote it."""

        settings = Path(self.fixture["settings"])
        return read_text(settings) if settings.exists() else None

    def remembered(self, key: str) -> object:
        """One value of the settings file as Centrum wrote it (``folder_okresow``, ``rejestr_zlecen``, ``motyw``)."""

        document = yaml.safe_load(self.settings_text() or "") or {}
        assert isinstance(document, dict)
        return document.get(key)


# The width from which the window Ustawienia lists its sections on the left instead of a combobox (Tailwind `md`).
NARROW_WINDOW_PX = 768


# Whether the element's centre takes a click: the topmost element there is the element or part of it, so nothing (the
# blurred page, another window, a notification) stands over it. One read is the page at that moment, which is the check
# when even a short cover is the defect (a notification over „Wyślij”); an element that slides in, like a notification,
# is visible before its centre is clear, so wait for it with `until` (#1518).
CENTRE_TAKES_CLICK = """element => {
    const box = element.getBoundingClientRect()
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
    return hit !== null && element.contains(hit)
}"""


def settings_window(page: Page) -> Locator:
    """The window Ustawienia over the page (``dialog`` named ``Ustawienia``)."""

    return page.get_by_role("dialog", name="Ustawienia")


def settings_title(page: Page) -> Locator:
    """The title of the window Ustawienia, its path ``Ustawienia/<section>``: the heading that names the window, not the
    title of a notification („Zapisano”, „Cofnięto”), which stands in the window as a heading of its own (#1534)."""

    return settings_window(page).get_by_role("heading", name=re.compile(r"^Ustawienia "))


def settings_section(page: Page) -> Locator:
    """The open section of Ustawienia; the menu of sections has lists of the same names (its group Narzędzie)."""

    return settings_window(page).locator("[data-slot=settings-section]")


def open_settings(page: Page, section: str) -> Locator:
    """Dad opens Ustawienia with the gear in the menu's footer, unless open, and goes to ``section`` (its title).

    The window's address opens it (``#/ustawienia/<section>``). On any other address a window that an earlier feature
    left open is closing, still visible while it fades out, so the gear waits until it is gone: no feature depends on how
    the one before it ended (#1589).
    """

    window = settings_window(page)
    if not _on_settings_address(page):
        expect(window).to_have_count(0)
        page.get_by_role("link", name="Ustawienia", exact=True).click()
    expect(window).to_be_visible()
    # Below 768 px (`useIsMobile`, Tailwind `md`) the list of sections is hidden and Dad picks from the combobox.
    viewport = page.viewport_size
    if viewport is None or viewport["width"] >= NARROW_WINDOW_PX:
        window.get_by_role("link", name=section, exact=True).click()
    else:
        window.get_by_role("combobox", name="Sekcja Ustawień").click()
        page.get_by_role("option", name=section, exact=True).click()
    expect(settings_title(page)).to_have_text(f"Ustawienia/{section}")
    return window


def _on_settings_address(page: Page) -> bool:
    """Whether the page is on the window Ustawienia's address, ``#/ustawienia`` with or without a section."""

    return urlsplit(page.url).fragment.split("/")[1:2] == ["ustawienia"]


def close_settings(page: Page) -> None:
    """Dad closes Ustawienia with Esc; the page under it stays."""

    page.keyboard.press("Escape")
    expect(settings_window(page)).to_have_count(0)


QUANTITY_DIFFERENCES = "/api/settings/quantity-rules/differences"
"""The list „Tu wpisałeś inaczej niż reguła” above the Reguły ilości: rows of the settled Pliki zbiorcze."""
ROW_TEXT = "<tekst wiersza>"
"""What the evidence keeps instead of URZĄDZENIA and CZYNNOŚCI of a synthetic Plik zbiorczy (workbook content)."""


def capture_quantity_rules(
    run: Run, page: Page, name: str, *, full_page: bool = True, texts: tuple[str, ...] = ()
) -> None:
    """Screenshot of the section Reguły ilości, whose list of differences of the Kontrola ilości shows URZĄDZENIA and
    CZYNNOŚCI of the settled Pliki zbiorcze: its ARIA snapshot gets those row texts, and ``texts`` (rows of a preview),
    replaced (``without_row_texts``), as the saved answers do, or ``centrum_self_test.py`` fails on the fixture's row
    marker."""

    run.capture(page, name, full_page=full_page)
    with urllib.request.urlopen(run.url.rstrip("/") + QUANTITY_DIFFERENCES, timeout=Budget.SCREEN.value) as response:
        listed: dict[str, Any] = json.load(response)
    shown = (*texts, *(difference[key] for difference in listed.get("differences", []) for key in ("devices", "activities")))
    snapshot = run.evidence / "aria" / f"{name}.txt"
    snapshot.write_text(without_row_texts(read_text(snapshot), shown), encoding="utf-8")


def without_row_texts(text: str, texts: Iterable[str]) -> str:
    """``text`` with each of ``texts`` (URZĄDZENIA, CZYNNOŚCI of a synthetic Plik zbiorczy) as ``ROW_TEXT``, also in the
    form the rules read it (small letters, single spaces), as the form „Popraw regułę” has it."""

    shown = {value for value in texts if value}
    shown |= {" ".join(value.casefold().split()) for value in shown}
    for value in sorted(shown, key=len, reverse=True):
        text = text.replace(value, ROW_TEXT)
    return text


def point_in_settings(run: Run, page: Page, label: str, path: str) -> None:
    """Dad points ``label`` (``Rejestr zleceń`` or ``Folder okresów``) to ``path`` in the section Foldery of Ustawienia,
    the only place Centrum chooses files (ADR 0032), and closes the window once the settings file has it."""

    key = {"Rejestr zleceń": "rejestr_zlecen", "Folder okresów": "folder_okresow"}[label]
    window = open_settings(page, "Foldery")
    run.answer_picker(path)
    window.get_by_role("button", name=re.compile(rf"^(Wskaż|Zmień) {label}$")).click()
    until(lambda: run.remembered(key) == path, f"{label} set in Ustawienia")
    expect(window.get_by_role("button", name=re.compile(rf"^(Wskaż|Zmień) {label}$"))).to_be_enabled()
    close_settings(page)


def choose_periods_directory(run: Run, page: Page, path: str | None = None) -> None:
    """Dad points Centrum to the folder okresów ``path`` (the fixture's without it) in Ustawienia from the empty
    Tablica okresów, whose „Ustaw w Ustawieniach” opens the section Foldery."""

    page.get_by_role("link", name="Ustaw w Ustawieniach", exact=True).first.click()
    expect(settings_title(page)).to_have_text("Ustawienia/Foldery")
    point_in_settings(run, page, "Folder okresów", run.fixture["periods_directory"] if path is None else path)
    expect(page.get_by_role("table", name="Tablica okresów")).to_be_visible()


def ensure_files_set(run: Run, page: Page, periods_directory: str | None = None) -> None:
    """Points Centrum to the folder okresów ``periods_directory`` (the fixture's without it) and the fixture's Rejestr
    zleceń in Ustawienia unless a feature before did."""

    settings = run.api("/api/settings", "ustawienia-przed-uruchomieniem")
    if settings["periods_directory"] == {"state": "not_set"}:
        point_in_settings(
            run, page, "Folder okresów", run.fixture["periods_directory"] if periods_directory is None else periods_directory
        )
    if settings["order_register"] == {"state": "not_set"}:
        point_in_settings(run, page, "Rejestr zleceń", run.fixture["order_register"])


def frontend_ms(source: str, name: str) -> int:
    """A time of the page, ``const <name> = <ms>`` in ``frontend/src/<source>``, for a wait with nothing on screen to
    wait for, so the wait follows the page when its time changes."""

    [ms] = re.findall(rf"^const {name} = (\d+)$", read_text(REPO_ROOT / "frontend" / "src" / source), re.M)
    return int(ms)


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


def remove(path: Path, *, missing_ok: bool = False) -> None:
    """Harness: remove a file of the run, even while the server reads it (``while_open``).

    The drive deletes, moves and replaces files and folders only through ``remove``, ``remove_tree``,
    ``remove_empty_folder``, ``move`` and ``replace_file``; ``centrum_self_test.py`` fails on the forms of the table of
    its ``_removals`` anywhere else in ``drive/``."""

    while_open(lambda: path.unlink(missing_ok=missing_ok))


def remove_tree(folder: Path, *, missing_ok: bool = False) -> None:
    """Harness: remove a folder of the run with its content, even while the server reads a file in it.

    A retry after a refusal removes what the first try left; after ``RETRY_OPEN_S`` the refusal is raised, never
    swallowed, so a folder that stays is a failure of the drive, not a quiet difference in later steps."""

    if missing_ok and not folder.exists():
        return
    while_open(lambda: shutil.rmtree(folder))


def remove_empty_folder(folder: Path) -> None:
    """Harness: remove an empty folder of the run, even while the server looks into it; fails when it is not empty."""

    while_open(folder.rmdir)


def move(source: Path, target: Path | str) -> None:
    """Harness: rename a file or folder of the run, even while the server reads it (``while_open``)."""

    while_open(lambda: Path(source).rename(target))


def replace_file(source: Path, target: Path) -> None:
    """Harness: put ``source`` in place of ``target`` at once, like Excel saving a whole file, even while the server
    reads ``target``."""

    while_open(lambda: os.replace(source, target))


def put_text(path: Path, text: str) -> None:
    """Harness: write ``text`` as ``path`` whole (``replace_file``), for a file the server reads from its own threads:
    a plain write leaves it empty for a moment, as the skrzynka's own writes did on Windows (#963, #1124)."""

    written = path.with_name(f"{path.name}.zapis")
    written.write_text(text, encoding="utf-8")
    replace_file(written, path)


def edit_issue(run: Run, number: int, **changes: object) -> None:
    """Harness: Maks edits issue ``number`` of the skrzynka Zgłoszeń (closes it), and GitHub shows the edit at once.

    The server reads the issue's file from its own threads, so the edited file takes its place whole (``put_text``)."""

    path = issue_file(run.root, number)
    issue = {**read_json(path), **changes}
    put_text(path, json.dumps(issue, ensure_ascii=False, indent=2) + "\n")


def drop_report_key(key_file: Path, *, missing_ok: bool = False) -> None:
    """Harness: Maks takes the key to the skrzynka Zgłoszeń away by leaving its file empty, never deleting it.

    The server reads the key whenever the queue or the Powiadomienia ask the skrzynka, and an empty file is no key
    for it (``read_report_key``), the same as no file. Rewriting succeeds while the server reads it on Windows, where
    a removal fails (``WinError 32``, #921), as Python opens files sharing read and write. Without ``missing_ok`` the
    step must have written a key, as the removal it replaces required its file."""

    if not missing_ok and not (key_file.is_file() and read_bytes(key_file).strip()):
        raise DriveFailure(f"the harness takes away a key that was never written: {key_file.name} is missing or empty")
    key_file.write_bytes(b"")


def read_text(path: Path) -> str:
    """Harness: the UTF-8 text of a file, read once the server has put it in place (``while_open``).

    The server puts its files in place whole (``os.replace``) from its own threads at any moment, and Windows refuses
    to open a file for that moment (#1087), so the drive reads files only through ``read_text``, ``read_bytes`` and
    ``read_json``; ``centrum_self_test.py`` fails on any other ``read_text`` or ``read_bytes`` in ``drive/``
    (``_direct_reads``)."""

    return while_open(lambda: path.read_text(encoding="utf-8"))


def read_bytes(path: Path) -> bytes:
    """Harness: the bytes of a file, read once the server has put it in place (``read_text``)."""

    return while_open(path.read_bytes)


def read_json(path: Path) -> Any:
    """Harness: a JSON file, read once the server has put it in place (``read_text``)."""

    return json.loads(read_text(path))


def box_issues(run: Run, label: str) -> list[dict[str, Any]]:
    """The issues of the skrzynka Zgłoszeń labelled only ``label``, by number; other features' issues take numbers too."""

    issues = [read_json(path) for path in run.box.glob("*.json")]
    return sorted((issue for issue in issues if issue["labels"] == [label]), key=lambda issue: int(str(issue["number"])))


def queued(run: Run, label: str, run_id: str | None = None, *, leaving: bool = False) -> list[Path]:
    """The files waiting in the queue of the skrzynka with ``label``, oldest first; with ``run_id``, only those of that
    Uruchomienie (a file's name ends with the first 8 characters of its id).

    A check that a file waits reads ``Run.queue``, the deliberate copy. A check that files left the queue passes
    ``leaving`` and reads the queue where src puts them: on the copy, a queue renamed in src would look empty at once.
    """

    queue = queue_directory(run.config) if leaving else run.queue
    return sorted(queue.glob(queue_file_pattern(label) if run_id is None else queue_file_pattern(label, run_id)))


def queued_posts(run: Run, label: str, run_id: str | None = None, *, leaving: bool = False) -> list[dict[str, Any]]:
    """The posts of ``queued``; a file the queue delivers and removes meanwhile no longer waits, so it is left out."""

    posts = []
    for path in queued(run, label, run_id, leaving=leaving):
        try:
            posts.append(read_json(path))
        except FileNotFoundError:
            continue
    return posts


def run_logs(run: Run, process: str | None = None) -> dict[str, dict[str, Any]]:
    """The files of Logi of ``process`` (every one without it) by name, oldest first, as the name starts with the start.

    The server puts a file of Logi in place whole, also when it adds a Diagnoza, so each is read with ``read_json``."""

    pattern = "*.json" if process is None else f"*-{process}-*.json"
    return {path.name: read_json(path) for path in sorted(run.run_logs_dir.glob(pattern))}


def check_clock_alarm(run: Run) -> None:
    """Fails once the wake-up thread of Centrum's clock has died (``File.CLOCK_DIED`` of ``ScriptedClock``):
    no wake-up on that clock, such as the queue's retry, fires any more, so a wait for one would only time out."""

    died = File.CLOCK_DIED.file(run.root)
    if died.exists():
        raise DriveFailure(f"the wake-up thread of Centrum's clock died, so no wake-up fires any more:\n{read_text(died)}")


def advance_clock(run: Run, minutes: float, why: str) -> None:
    """Harness: Centrum's clock moves ``minutes`` on (``File.CLOCK_MOVE``), so ``why``.

    The clock's wake-up thread reads the file every 0.2 s, so it takes its place whole (``put_text``); a move wakes
    nothing once that thread has died (``check_clock_alarm``)."""

    check_clock_alarm(run)
    moved = File.CLOCK_MOVE.file(run.root)
    moved.parent.mkdir(exist_ok=True)
    before = float(read_text(moved)) if moved.exists() else 0.0
    put_text(moved, str(before + minutes))
    print(f"  harness: Centrum's clock moves {minutes:g} min on, so {why}", flush=True)


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=Budget.PROBE.value):
            return True
    except OSError:
        return False


def close_centrum(run: Run, page: Page) -> None:
    """Dad closes Centrum from the sidebar in the evening, as in features/start-i-zamykanie.md."""

    page.goto(run.url)
    page.get_by_role("button", name="Zamknij Centrum rozliczeń", exact=True).click()
    page.get_by_role("button", name="Zamknij Centrum", exact=True).click()
    expect(page.get_by_role("heading", name="Centrum rozliczeń jest zamknięte", exact=True)).to_be_visible()
    until(lambda: not answers(run.url), "Centrum stops serving")


def start_centrum(run: Run, name: str) -> None:
    """The next morning Dad clicks the shortcut.

    Harness: the shortcut's launcher would start Dad's own Centrum, so the drive starts this run's scripted Centrum
    on the same port (``serve_centrum.py``, as the restart guardian's shim does after an update), its console in
    ``api/<name>-server.txt``. Cleanup stops it through ``server.json``.
    """

    port = read_json(File.SERVER.file(run.root))["port"]
    print("  harness: Dad starts Centrum again (this run's scripted Centrum on the same port)", flush=True)
    with (run.evidence / "api" / f"{name}-server.txt").open("wb") as console:
        subprocess.Popen(
            [sys.executable, str(SERVE), "--root", str(run.root), "--port", str(port)],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=console,
            stderr=subprocess.STDOUT,
        )
    until(lambda: answers(run.url), "Centrum answers again after the start", Budget.WORK)


def kill_centrum(run: Run) -> None:
    """Centrum dies with its process mid-work, like a closed console window or a power cut.

    Harness: the drive kills this run's server through the pid in ``server.json`` (on Windows ``TerminateProcess``).
    """

    pid = int(read_json(File.SERVER.file(run.root))["pid"])
    print("  harness: Centrum dies mid-run (its process is killed)", flush=True)
    if sys.platform == "win32":
        os.kill(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGKILL)
    until(lambda: not answers(run.url), "Centrum stops serving")


def local_time(moment: str) -> str:
    """The UI's date text of an ISO ``moment`` in Dad's time zone (``06.10.2026, 08:21``)."""

    return datetime.fromisoformat(moment).astimezone(DAD_TIME_ZONE).strftime("%d.%m.%Y, %H:%M")


# The browser of the mode „wolny runner” (SLOW_RUNNER): animations run at this rate, so a notification that closes stays
# on the screen five times longer (#1534), and each write of the tab leaves it LATE_WRITE_MS late.
SLOW_ANIMATIONS = 0.2
LATE_WRITES = """(() => {
    const send = window.fetch
    window.fetch = (input, init) => {
        const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase()
        if (method === "GET") return send(input, init)
        return new Promise(resolve => setTimeout(resolve, %d)).then(() => send(input, init))
    }
})()"""


PAGE_REQUESTS = "zadania-strony.txt"
"""The file beside ``drive.txt`` with one line per failed request, answer of 400 or more and page without its
stylesheet, of every page of the drive (``PageRequests``)."""
# A page whose stylesheet of its own origin has no rule it can read after its load says so on its console with this
# prefix and the sheet's address. Chromium gives a failed request an empty sheet whose rules it refuses to read
# (SecurityError) and an error answer or an empty one a sheet without rules; a sheet of another origin is never readable,
# so it is left out. The condition does not depend on the theme.
NO_STYLESHEET = "drive: no stylesheet: "
# A request the page itself gave up, as the event stream of Uruchomienia on each navigation: no answer was lost.
ABANDONED = "net::ERR_ABORTED"
STYLESHEET_CHECK = """addEventListener("load", () => {
    for (const link of document.querySelectorAll('link[rel="stylesheet"]')) {
        if (new URL(link.href).origin !== location.origin) continue
        let rules = 0
        try { rules = link.sheet?.cssRules.length ?? 0 } catch {}
        if (rules === 0) console.warn(%s + link.href)
    }
})""" % json.dumps(NO_STYLESHEET)


class PageRequests:
    """What the drive's pages lost on the way from Centrum, in ``PAGE_REQUESTS`` of the evidence (#1539).

    Without ``index.css`` the window of Base UI has no place above its own backdrop, so a click in Ustawienia waited
    10 s behind ``data-base-ui-inert`` and named nothing (run 43561009106). ``dad_context`` hands every context it opens
    to ``watch``, so each page and tab of the drive writes here; the query of an address is left out, as it may carry a
    value of a file.
    """

    def __init__(self) -> None:
        self._file: Path | None = None
        self._without_stylesheet: list[str] = []

    @contextmanager
    def recording(self, evidence: Path) -> Iterator[None]:
        """Contexts opened in this block write to ``evidence``; after it the drive's contexts write nothing."""

        self._file = evidence / PAGE_REQUESTS
        self._file.write_text("", encoding="utf-8")
        self._without_stylesheet = []
        try:
            yield
        finally:
            self._file = None

    def watch(self, context: BrowserContext) -> None:
        if self._file is None:
            return
        context.add_init_script(STYLESHEET_CHECK)
        context.on("requestfailed", self._failed)
        context.on("response", self._answered)
        context.on("console", self._console)

    def check(self, cause: Exception | None = None) -> None:
        """Fails naming each stylesheet a page of the drive did not get, before ``cause``, the failure it led to: a click
        that waits behind a backdrop names only the backdrop."""

        if not self._without_stylesheet:
            return
        sheets = ", ".join(dict.fromkeys(self._without_stylesheet))
        failure = DriveFailure(
            f"the page got no stylesheet ({sheets}), so Base UI windows lie under their backdrop; "
            f"its failed requests and error answers are in {PAGE_REQUESTS}"
        )
        if cause is not None:
            for note in (str(cause), *getattr(cause, "__notes__", ())):
                failure.add_note(note)
        raise failure from cause

    def _failed(self, request: Request) -> None:
        if request.failure != ABANDONED:
            self._write(f"{request.method} {_address(request.url)} failed: {request.failure}")

    def _answered(self, response: Response) -> None:
        if response.status >= 400:
            self._write(f"{response.request.method} {_address(response.url)} answered {response.status}")

    def _console(self, message: ConsoleMessage) -> None:
        if message.text.startswith(NO_STYLESHEET):
            sheet = _address(message.text.removeprefix(NO_STYLESHEET))
            self._without_stylesheet.append(sheet)
            self._write(f"page without stylesheet {sheet}")

    def _write(self, line: str) -> None:
        if self._file is not None:
            with self._file.open("a", encoding="utf-8") as record:
                record.write(f"{datetime.now(UTC).isoformat(timespec='milliseconds')} {line}\n")


def _address(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else parts.path


page_requests = PageRequests()


def dad_context(browser: Browser, *, viewport: ViewportSize = DAD_VIEWPORT, touch: bool = False) -> BrowserContext:
    """A browser window like Dad's: Polish, on Polish time, ``viewport`` large, with a touch screen when ``touch``; in the
    mode „wolny runner” its pages run animations slowly and send writes late. Its pages write what they lost to
    ``page_requests``."""

    context = browser.new_context(viewport=viewport, locale="pl-PL", timezone_id=DAD_TIME_ZONE.key, has_touch=touch)
    page_requests.watch(context)
    if SLOW_RUNNER in os.environ:
        # A late write in the page, not in context.route: a handler of the sync client that sleeps holds the drive too.
        context.add_init_script(LATE_WRITES % LATE_WRITE_MS)

        def slow_animations(page: Page) -> None:
            context.new_cdp_session(page).send("Animation.setPlaybackRate", {"playbackRate": SLOW_ANIMATIONS})

        context.on("page", slow_animations)
    return context


@contextmanager
def dad_tab(
    page: Page,
    *,
    viewport: ViewportSize = DAD_VIEWPORT,
    touch: bool = False,
    cpu: int = 1,
    timeout_ms: float = Budget.SCREEN.ms,
) -> Iterator[Page]:
    """A second window of the drive's browser (``dad_context``), its processor ``cpu`` times slower; closed after."""

    browser = page.context.browser
    assert browser is not None
    context = dad_context(browser, viewport=viewport, touch=touch)
    try:
        tab = context.new_page()
        tab.set_default_timeout(timeout_ms)
        if cpu != 1:
            context.new_cdp_session(tab).send("Emulation.setCPUThrottlingRate", {"rate": cpu})
        yield tab
    finally:
        context.close()


def shown_theme(page: Page) -> str:
    """The theme on screen, ``jasny`` or ``ciemny`` (the class ``dark`` of the page)."""

    return "ciemny" if "dark" in str(page.locator("html").get_attribute("class") or "").split() else "jasny"


def choose_theme(page: Page, theme: str) -> None:
    """Dad picks ``theme`` (``jasny`` or ``ciemny``) under Motyw in the section Wygląd of Ustawienia and closes it."""

    window = open_settings(page, "Wygląd")
    window.get_by_role("group", name="Motyw").get_by_role("button", name=theme.capitalize(), exact=True).click()
    expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b") if theme == "ciemny" else re.compile(r"^(?!.*\bdark\b)"))
    close_settings(page)


def toggle_theme(page: Page) -> str:
    """Dad switches to the other theme in Ustawienia; the theme it switched to (``jasny`` or ``ciemny``)."""

    theme = "ciemny" if shown_theme(page) == "jasny" else "jasny"
    choose_theme(page, theme)
    return theme


def switch_theme(page: Page, theme: str) -> bool:
    """Switches to ``theme`` (``jasny`` or ``ciemny``) unless it is shown; whether it switched."""

    if shown_theme(page) == theme:
        return False
    choose_theme(page, theme)
    return True


def reload_with_answer(run: Run, page: Page, path: str, name: str) -> Any:
    """Reloads ``page`` and returns the server's answer to its read of ``path`` (GET), the one it shows, in ``api/``.

    A page shows what it read only after the server answered, and the server may take seconds (#1091: Konfiguracja
    reads the Wzorce and asks GitHub and the skrzynka), so the drive waits for that answer, not for a guessed time."""

    def read(response: Response) -> bool:
        return response.request.method == "GET" and urlsplit(response.url).path == path

    with page.expect_response(read) as answer:
        page.reload()
    body = answer.value.json()
    (run.evidence / "api" / f"{name}.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return body


@contextmanager
def priced_in_efenix(run: Run, token: str, result: str = "OK") -> Iterator[None]:
    """Harness: a Wycena w efenix of ``token`` with ``result`` (OK or WYMAGA_SPRAWDZENIA) in the run's Historia, the
    Wycena metrics file ``metrics.efenix`` of fixture.json, from which the Droga okresu counts it (one
    record of metrics schema 2, which the reader still takes), and the file's content as it was afterwards, so later
    features count the same history.

    A missing file comes back empty, not deleted: the server reads the file while the page refreshes, and on Windows a
    file another process has open cannot be deleted (``WinError 32``, part 2/4 of #863), while it can be rewritten,
    as Python opens files sharing read and write. The metrics reader takes an empty file as no history."""

    path = Path(run.fixture["metrics"]["efenix"])
    before = read_bytes(path) if path.exists() else b""
    counters = dict.fromkeys(("orders", "ready", "errors", "emmett_warnings", "with_photos", "defects"), 0)
    record = {
        "schema_version": 2, "started_at": "2026-10-13T10:00:00+02:00", "mode": "RUN", "period": token,
        "completed": True, "result": result, "total_duration_ms": 1000,
        "phase_durations_ms": dict.fromkeys(("Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"), 0),
        "counters": counters, "stop": None,
    }
    path.write_bytes(before + json.dumps(record).encode() + b"\n")
    try:
        yield
    finally:
        path.write_bytes(before)


# The current step of the Droga okresu → the heading of card Następny krok, its main (first) button, and the main
# (last) button of the period's row in column Następny krok of Tablica okresów.
CARD_STEPS = {
    "Plik zbiorczy": ("Przygotuj plik zbiorczy", "Podgląd bez zapisu", "Przygotuj plik zbiorczy"),
    "Uzupełnienie w Excelu": ("Uzupełnij plik zbiorczy", "Uzupełnij", "Uzupełnij"),
    "Wycena w efenix": ("Wyceń w efenix", "Wyceń w efenix", "Wyceń w efenix"),
    "Rozliczenia pracowników": ("Utwórz rozliczenia pracowników", "Podgląd bez zapisu", "Utwórz rozliczenia pracowników"),
}


def next_step_names_current_step(run: Run, page: Page, token: str, current: str) -> Locator:
    """Card Następny krok of ``token``: its heading, the current step of its Droga okresu and its main button name the
    same step, and so does the main (last) button of the period's row in column Następny krok of Tablica okresów."""

    heading, button, row_button = CARD_STEPS[current]
    card = page.get_by_role("region", name="Następny krok")
    expect(card).to_contain_text(token)
    expect(card.get_by_role("heading", level=2)).to_have_text(heading)
    expect(card.get_by_role("list", name="Droga okresu").locator('[aria-current="step"]')).to_contain_text(current)
    expect(card.get_by_role("button").first).to_have_accessible_name(button)
    row_step = period_row(page, token).get_by_role("cell").last.get_by_role("button").last
    expect(row_step).to_have_accessible_name(f"{row_button}, okres {token}")
    run.check(
        True,
        f"Następny krok of {token}: heading {heading}, current step {current} and main button {button} name one step, "
        "as the main button of its row in Tablica okresów does",
    )
    return card


def last_opened_is(run: Run, path: Path) -> Callable[[], bool]:
    return lambda: run.lines(Log.OPENED)[-1:] == [{"path": str(path)}]


def history_rows(page: Page) -> Locator:
    return page.get_by_role("table", name="Historia Uruchomień procesu").get_by_role("row")


def period_files(run: Run) -> list[Path]:
    folder = Path(run.fixture["periods_directory"]) / LAST_COMPLETE
    return [
        folder / f"Rozliczenie wew. {LAST_COMPLETE}.xlsx",
        folder / f"Rozliczenie {LAST_COMPLETE} - zbiorcze.xlsx",
    ]


def current_run(run: Run, name: str) -> dict[str, Any]:
    view = run.api("/api/runs/current", name)
    assert isinstance(view, dict)
    return view


def ended_run_shown(view: dict[str, object]) -> bool:
    """Uruchomienia shows an ended Uruchomienie instead of the setup card: one that finished, or the last one from
    before Centrum's start (``RunIdle.previous``); `Nowe Uruchomienie procesu` sets it aside."""

    return view["state"] == "finished" or (view["state"] == "idle" and view["previous"] is not None)


def finished_view(
    run: Run, name: str, *, replacing: str | None = None, timeout_s: Budget = Budget.SCREEN
) -> dict[str, Any]:
    """The current Uruchomienie once it finished, the one answer kept in ``api/<name>.json``.

    ``replacing`` is the id of the Uruchomienie the drive just started again (`Uruchom ponownie`): a click does not wait
    for the tab's request, so the server can still show the one before it as finished, and only another id is the new
    Uruchomienie. ``timeout_s`` is the budget of the wait for the end (``until``)."""

    # One answer for both the state and the result: a second read could already see the next Uruchomienie.
    seen: dict[str, Any] = {}

    def finished() -> bool:
        seen.clear()
        seen.update(current_run(run, name))
        return bool(seen["state"] == "finished" and seen["run"]["id"] != replacing)

    until(finished, "the Uruchomienie procesu finished", timeout_s)
    return seen


def finished_result(
    run: Run, name: str, *, replacing: str | None = None, timeout_s: Budget = Budget.SCREEN
) -> dict[str, Any]:
    result = finished_view(run, name, replacing=replacing, timeout_s=timeout_s)["result"]
    assert isinstance(result, dict)
    return result


def start_new(run: Run, name: str, start: Callable[[], object]) -> str | None:
    """Dad's click ``start``, which starts an Uruchomienie; the id of the one shown before it (``api/<name>-przed.json``),
    ``None`` when none was.

    A click does not wait for the tab's start request, so the server can still show that one, even finished, however
    soon the drive reads it (#1570): only another id is the new Uruchomienie, so pass the id as ``replacing``."""

    before = current_run(run, f"{name}-przed")
    start()
    return str(before["run"]["id"]) if "run" in before else None


def result_of_start(run: Run, name: str, start: Callable[[], object]) -> dict[str, Any]:
    """The result of the Uruchomienie that ``start`` (Dad's click) starts, once it finished (``start_new``)."""

    return finished_result(run, name, replacing=start_new(run, name, start))


def run_again(run: Run, outcome: Locator, name: str) -> dict[str, Any]:
    """Dad clicks `Uruchom ponownie` in ``outcome`` (the stop banner or the result); the new Uruchomienie's result."""

    return result_of_start(run, name, outcome.get_by_role("button", name="Uruchom ponownie", exact=True).click)


def open_setup(run: Run, page: Page, process: str, name: str, *, period: tuple[str, str] | None = None) -> None:
    """Dad's way to the start card of ``process`` after a reload of Uruchomienia: `Nowe Uruchomienie procesu` when an
    ended Uruchomienie is shown (``ended_run_shown``, read as ``api/<name>-przed.json``), the process and, when given,
    the period ``(token, Status okresu)`` in the combobox ``Okres``."""

    page.goto(run.url + "#/uruchomienia")
    page.reload()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    if ended_run_shown(current_run(run, f"{name}-przed")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name=process).click()
    if period is not None:
        page.get_by_role("combobox", name="Okres").click()
        page.get_by_role("option", name=period_choice(*period), exact=True).click()


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

    lock = excel_lock(workbook)
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
        remove(lock, missing_ok=True)
    print(f"  harness: Excel closes {workbook.name}, so its lock file is gone; Dad returns to Centrum", flush=True)
    page.evaluate(FOCUS)
    expect(warned).to_have_count(0)
    expect(start).to_be_enabled()
    run.check(
        shown(f"{name}-zamkniety") == ([], reminder),
        f"after {workbook.name} is closed the warning is gone without a reload and Uruchom is on again",
    )
    run.capture(page, shots[1])


def diagnosis_answer(run: Run, run_id: str, name: str) -> dict[str, Any]:
    """The server's Diagnoza for ``run_id`` as the browser gets it, kept in ``api/``."""

    answer = run.post(f"/api/runs/{run_id}/diagnosis", name)
    run.check(answer.status == 200, "the server answers the Diagnoza")
    assert isinstance(answer.body, dict)
    return answer.body


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


def settle(page: Page, sent: list[Request], at_least: int = 1) -> int:
    """Waits until a repeated click would have sent its request and every answer reached the screen; the count."""

    until(lambda: len(sent) >= at_least, f"the click sends {at_least} request(s) (a write of the tab can leave late)", page=page)
    quiet_for(page)
    for request in list(sent):
        request.response()
    quiet_for(page)
    return len(sent)


def error_toasts(page: Page) -> Locator:
    """Error notifications („Nie udało się …”), also those stacked behind the newest one."""

    return page.get_by_role("region", name="Notifications").get_by_role("dialog", name="Nie udało się")


def served_version(run: Run) -> tuple[str, str | None]:
    """The tool commit the served Centrum runs and the day the run's tool clone moved to it, as Git reports them.

    The commit is the clone's ``HEAD`` unless a feature pinned another one in
    ``File.TOOL_COMMIT``. The day (``YYYY-MM-DD``) is the last ``HEAD`` reflog entry's, in that entry's
    time zone, when that entry leads to the commit, else ``None``. Neither depends on how Centrum reads ``.git``.
    """

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", run.fixture["tool"]["clone"], *arguments], capture_output=True, text=True, check=True
        ).stdout.strip()

    pinned = File.TOOL_COMMIT.file(run.root)
    commit = read_text(pinned).strip() if pinned.exists() else git("rev-parse", "HEAD")
    entry_commit, _, selector = git("log", "--walk-reflogs", "-1", "--date=short", "--format=%H %gd").partition(" ")
    return commit, selector.removeprefix("HEAD@{").removesuffix("}") if entry_commit == commit else None


def version_line(commit: str, since: str | None) -> str:
    """The version Dad reads under Wersja narzędzia in the section Narzędzie of Ustawienia: ``1a2b3c4 od 20.10.2026``."""

    if since is None:
        return commit[:7]
    year, month, day = since.split("-")
    return f"{commit[:7]} od {day}.{month}.{year}"


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
