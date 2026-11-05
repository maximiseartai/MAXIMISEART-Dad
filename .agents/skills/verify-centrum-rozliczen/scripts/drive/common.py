"""The drive's shared run state and the helpers more than one feature uses."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import FloatRect, Locator, Page, Request, expect
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

    def capture(
        self, page: Page, name: str, *, full_page: bool = True, live: bool = False, clip: FloatRect | None = None
    ) -> None:
        """Screenshot and ARIA snapshot after every running transition has finished.

        ``live`` captures while a stage runs: its indeterminate bar loops forever, so do not wait.
        ``clip`` takes a close-up of that part of the viewport instead of the page.
        """

        number = name.split("-", 1)[0]
        owner = self._number_owners.setdefault(number, self.feature)
        if owner != self.feature:
            raise DriveFailure(f"screenshot {name} of {self.feature} uses number {number}, which belongs to {owner}")
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


# How long every helper below (`remove`, `remove_tree`, `remove_empty_folder`, `move`, `replace_file`) retries a file
# the server holds open on Windows; the server reads the harness's files in milliseconds, so this only bounds a change
# that will never succeed.
RETRY_OPEN_S = 10.0


def _while_open(action: Callable[[], object]) -> None:
    """Run ``action`` on a file of the run, retrying while the server holds it open, for at most ``RETRY_OPEN_S``.

    The server reads the run's files from its own threads at any moment (pacing, the scripted GitHub, the queue of
    the skrzynka Zgłoszeń, the settings, metrics and Wzorce while a page refreshes), and on Windows a file another
    process has open can be neither deleted nor renamed (``WinError 32``, #921)."""

    deadline = time.monotonic() + RETRY_OPEN_S
    while True:
        try:
            action()
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def remove(path: Path, *, missing_ok: bool = False) -> None:
    """Harness: remove a file of the run, even while the server reads it (``_while_open``).

    The drive deletes, moves and replaces files and folders only through ``remove``, ``remove_tree``,
    ``remove_empty_folder``, ``move`` and ``replace_file``; ``centrum_self_test.py`` fails on the forms of the table of
    its ``_removals`` anywhere else in ``drive/``."""

    _while_open(lambda: path.unlink(missing_ok=missing_ok))


def remove_tree(folder: Path, *, missing_ok: bool = False) -> None:
    """Harness: remove a folder of the run with its content, even while the server reads a file in it.

    A retry after a refusal removes what the first try left; after ``RETRY_OPEN_S`` the refusal is raised, never
    swallowed, so a folder that stays is a failure of the drive, not a quiet difference in later steps."""

    if missing_ok and not folder.exists():
        return
    _while_open(lambda: shutil.rmtree(folder))


def remove_empty_folder(folder: Path) -> None:
    """Harness: remove an empty folder of the run, even while the server looks into it; fails when it is not empty."""

    _while_open(folder.rmdir)


def move(source: Path, target: Path | str) -> None:
    """Harness: rename a file or folder of the run, even while the server reads it (``_while_open``)."""

    _while_open(lambda: Path(source).rename(target))


def replace_file(source: Path, target: Path) -> None:
    """Harness: put ``source`` in place of ``target`` at once, like Excel saving a whole file, even while the server
    reads ``target``."""

    _while_open(lambda: os.replace(source, target))


def edit_issue(box: Path, number: object, **changes: object) -> None:
    """Harness: Maks edits issue ``number`` of the skrzynka Zgłoszeń (closes it), and GitHub shows the edit at once.

    The server reads the issue's file from its own threads, so the edited file takes its place whole (``replace_file``):
    a plain write leaves it empty for a moment, as the skrzynka's own writes did on Windows (#963)."""

    path = box / f"{number}.json"
    edited = path.with_name(f"{path.name}.edycja")
    issue = {**json.loads(path.read_text(encoding="utf-8")), **changes}
    edited.write_text(json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_file(edited, path)


def drop_report_key(key_file: Path, *, missing_ok: bool = False) -> None:
    """Harness: Maks takes the key to the skrzynka Zgłoszeń away by leaving its file empty, never deleting it.

    The server reads the key whenever the queue or the Powiadomienia ask the skrzynka, and an empty file is no key
    for it (``read_report_key``), the same as no file. Rewriting succeeds while the server reads it on Windows, where
    a removal fails (``WinError 32``, #921), as Python opens files sharing read and write. Without ``missing_ok`` the
    step must have written a key, as the removal it replaces required its file."""

    if not missing_ok and not (key_file.is_file() and key_file.read_bytes().strip()):
        raise DriveFailure(f"the harness takes away a key that was never written: {key_file.name} is missing or empty")
    key_file.write_bytes(b"")


# The Wycena w efenix metrics file of the run (`serve_centrum.py`): its Historia, from which the Droga okresu counts it.
EFENIX_METRICS = ".wycena-efenix-metrics.jsonl"


@contextmanager
def priced_in_efenix(run: Run, token: str, result: str = "OK") -> Iterator[None]:
    """Harness: a Wycena w efenix of ``token`` with ``result`` (OK or WYMAGA_SPRAWDZENIA) in the run's Historia (one
    record of metrics schema 2, which the reader still takes), and the file's content as it was afterwards, so later
    features count the same history.

    A missing file comes back empty, not deleted: the server reads the file while the page refreshes, and on Windows a
    file another process has open cannot be deleted (``WinError 32``, part 2/4 of #863), while it can be rewritten,
    as Python opens files sharing read and write. The metrics reader takes an empty file as no history."""

    path = run.root / EFENIX_METRICS
    before = path.read_bytes() if path.exists() else b""
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
