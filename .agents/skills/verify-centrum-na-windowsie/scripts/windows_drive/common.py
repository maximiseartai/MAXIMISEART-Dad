"""The drive's shared run state: steps and checks, browser and desktop captures, Centrum's answers and log."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, TypeVar
import urllib.request

from playwright.sync_api import Locator, Page, expect

import windows_desktop
import windows_tool
from atrapy.pliki_taty import CONFIG_DIRECTORY, LOG_FILE, SETTINGS_FILE

T = TypeVar("T")


class DriveFailure(Exception):
    pass


class Run:
    def __init__(self, root: Path, evidence: Path) -> None:
        self.root = root
        self.evidence = evidence
        self.facts = windows_tool.load(root)
        self.tool = Path(self.facts["tool"])
        self.url: str = self.facts["url"]
        self._shots = 0
        for name in ("screenshots", "pulpit", "api", "state"):
            (evidence / name).mkdir(parents=True, exist_ok=True)

    def step(self, feature: str, name: str) -> None:
        print(f"STEP {feature} | {name}", flush=True)

    def harness(self, what: str) -> None:
        print(f"  harness: {what}", flush=True)

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise DriveFailure(message)
        print(f"  ok: {message}", flush=True)

    def _number(self) -> str:
        self._shots += 1
        return f"{self._shots:02d}"

    def capture(self, page: Page, name: str) -> None:
        """The tab after its transitions, and the whole desktop with every native window on it."""

        page.wait_for_load_state("networkidle")
        number = self._number()
        page.screenshot(path=str(self.evidence / "screenshots" / f"{number}-{name}.png"), full_page=True)
        self.desktop(name, number=number)

    def desktop(self, name: str, *, number: str | None = None) -> None:
        windows_desktop.screenshot(self.evidence / "pulpit" / f"{number or self._number()}-{name}.png")

    def get(self, path: str, record: str | None = None) -> Any:
        with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=10) as response:
            body = json.load(response)
        if record is not None:
            self.record(record, body)
        return body

    def record(self, name: str, body: Any) -> None:
        (self.evidence / "api" / f"{name}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def health(self, *, timeout_s: float = 60) -> dict[str, Any]:
        def answer() -> dict[str, Any] | None:
            try:
                body = self.get("/api/health")
            except OSError:
                return None
            return body if isinstance(body, dict) else None

        return wait_for(answer, timeout_s=timeout_s, what="Centrum answering /api/health")

    @property
    def log(self) -> Path:
        """The Centrum log of the installed tool, which Dad hands Maks (docs/tata-instrukcja.md)."""

        return self.tool / LOG_FILE

    @property
    def config(self) -> Path:
        """The tool's ``config/``, where Maks puts Dad's files and Centrum keeps its own across Wydania."""

        return self.tool / CONFIG_DIRECTORY

    @property
    def settings(self) -> Path:
        """Ustawienia Centrum in the tool's ``config/``, by the name README gives them."""

        return self.tool / SETTINGS_FILE

    def log_lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.is_file() else []

    @property
    def shortcut(self) -> Path:
        return Path(self.facts["shortcut"])

    @property
    def run_centrum(self) -> Path:
        return self.tool / "run_centrum.py"

    def centrum_process(self) -> windows_desktop.Process:
        """The process listening on Dad's port; it must be this run's tool."""

        pid = windows_desktop.port_owner(self.facts["port"])
        self.check(pid is not None, f"a process listens on port {self.facts['port']}")
        found = [process for process in windows_desktop.processes() if process.pid == pid]
        self.check(len(found) == 1, f"the port owner {pid} is a running process")
        return found[0]

    def git(self, *args: str) -> str:
        """Git in the tool's clone with this computer's configuration, as Centrum sees the clone."""

        return windows_tool.git(self.tool, *args, machine=True)

    def config_bytes(self) -> dict[str, str]:
        """Every file in the tool's ``config/`` (Dad's files and Centrum's own) by its SHA-256."""

        config = self.config
        return {
            path.relative_to(config).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(config.rglob("*"))
            if path.is_file()
        }

    def opened_addresses(self) -> list[str]:
        opened = Path(self.facts["opened"])
        return [line.strip() for line in opened.read_text(encoding="utf-8").splitlines()] if opened.is_file() else []


def settings_window(page: Page) -> Locator:
    """The window Ustawienia over the page (ADR 0032), where Dad points his files and updates the tool."""

    return page.get_by_role("dialog", name="Ustawienia")


def settings_title(page: Page) -> Locator:
    """The title of the window Ustawienia, its path ``Ustawienia/<section>``: the heading that names the window, not the
    title of a notification („Zapisano”, „Cofnięto”), which stands in the window as a heading of its own (#1534)."""

    return settings_window(page).get_by_role("heading", name=re.compile(r"^Ustawienia "))


def settings_section(page: Page) -> Locator:
    """The open section of Ustawienia; the menu of sections has lists of the same names (its group Narzędzie)."""

    return settings_window(page).locator("[data-slot=settings-section]")


def open_settings(page: Page, section: str) -> Locator:
    """Dad opens Ustawienia with the gear in the menu's footer, unless open, and goes to ``section`` (its title);
    returns that section."""

    window = settings_window(page)
    if not window.is_visible():
        page.get_by_role("link", name="Ustawienia", exact=True).click()
    expect(window).to_be_visible()
    window.get_by_role("link", name=section, exact=True).click()
    expect(settings_title(page)).to_have_text(f"Ustawienia/{section}")
    return settings_section(page)


def close_settings(page: Page) -> None:
    """Dad closes Ustawienia with Esc; the page under it stays."""

    page.keyboard.press("Escape")
    expect(settings_window(page)).to_have_count(0)


def wait_for(probe: Callable[[], T | None], *, timeout_s: float, what: str, every_s: float = 0.25) -> T:
    deadline = time.monotonic() + timeout_s
    while True:
        found = probe()
        if found is not None:
            return found
        if time.monotonic() > deadline:
            raise DriveFailure(f"timed out after {timeout_s:.0f} s waiting for {what}")
        time.sleep(every_s)


def same_path(left: str | Path, right: str | Path) -> bool:
    return str(Path(left)).casefold() == str(Path(right)).casefold()
