"""The drive's one way to wait until a file or a state of the run is ready, the budgets that limit a wait, and the
drive's ``expect`` of Playwright, whose assertions wait a budget too, the drive's one quiet: a time in which the page
runs with nothing to wait for (``quiet_for``), and the one late answer of a route (``answer_late``). Ruff refuses
``time.sleep`` in the rest of ``drive/``, but for the retry of ``while_open`` in ``drive/common.py``.

The server and its threads write the run's files at any moment, so a read inside a wait can meet a file that does not
exist yet, is empty, half written, or refused for a moment on Windows while it is put in place. Each of those is
``NOT_YET``: the wait reads again, as it does after a ``None`` or ``False``. Any other error is a defect of the drive
or of Centrum and ends the wait at once.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import json
import os
import time
from typing import TypeVar

from playwright.sync_api import Expect, Page, Route
import yaml

from harness import SLOW_RUNNER

# A file of the run in a state the server or the harness has not finished: missing, refused for a moment (Windows,
# #1087), or empty or half written as JSON, JSON Lines, YAML or UTF-8 text (#963, #1195, #1651).
NOT_YET: tuple[type[Exception], ...] = (
    FileNotFoundError,
    PermissionError,
    json.JSONDecodeError,
    UnicodeDecodeError,
    yaml.YAMLError,
)

# How often a wait reads again.
POLL_S = 0.1
# Dad double-clicks out of habit and double-taps the touch screen: the second click comes within milliseconds,
# so a repeated request is sent well within this, and an answer reaches the screen (a refusal as a toast) too.
REPEAT_SETTLE_MS = 300
# In the mode „wolny runner” (SLOW_RUNNER) each write of the tab leaves it this late (``dad_context`` of
# ``drive/common.py``), as the start of #1570 did.
LATE_WRITE_MS = 1500


class Budget(Enum):
    """The longest a wait may take, in seconds, named by what the drive waits for.

    One name per value: two names of one value would be one member of the ``Enum``, so a wait with the value of a budget
    is named by what it shares with that budget's waits, and a wait whose value changes gets a name of its own.
    """

    # One question whether Centrum answers at all, inside a wait that asks again.
    PROBE = 2.0
    # A state the screen shows for a few seconds: shorter than the 5 s in which a notification closes itself (`timeout` of
    # Base UI's `ToastProvider`), so a notification covered for good fails with the sentence of its step.
    TRANSIENT = 3.0
    # An assertion of ``expect`` sees the state it names on the screen: Playwright's own default, which every assertion
    # of the drive without ``timeout=`` has waited; a longer one would lengthen each failure of a mutant of the drive.
    ASSERTION = 5.0
    # Centrum, or a server of the harness such as the Atrapa efenix, answers on its screen, through its API or in the
    # run's files to what Dad or the harness has just done.
    SCREEN = 10.0
    # Centrum sends to the skrzynka what Dad wrote, and the window waits for the skrzynka's answer.
    SEND = 15.0
    # Work the harness slows on purpose answers: a step after the pacing of the harness (Git, pip or the guardian of
    # Aktualizacja narzędzia, Szablony pracowników), a tab on a processor as slow as Dad's, or a save onto state files
    # another program holds.
    SLOWED = 20.0
    # Centrum answers after work heavier than a screen: its start, the queue it sends at its start, a step of the efenix
    # window, or a read of the latest Pliki zbiorcze.
    WORK = 30.0
    # Work of many steps, of which the drive sees only the end, finishes on its own: Centrum started again by
    # Aktualizacja narzędzia (its guardian waits up to 60 s, and the tab reloads when it answers), a whole Wycena through
    # the efenix window (5.6–5.9 s on Maks's Mac, past 10 s on the Windows runner of CI, #1296), the queue delivered to
    # the skrzynka in the background, or the launcher of Centrum (``run_centrum.py``).
    BACKGROUND = 60.0
    # A process of the tool outside Centrum (``tools/uruchom_proces.py``) ends.
    PROCESS = 120.0

    @property
    def ms(self) -> float:
        """The budget in milliseconds, the unit of a limit of Playwright."""

        return self.value * 1000


# The drive's ``expect``: an assertion without ``timeout=`` waits ``Budget.ASSERTION``. An instance of its own, so that
# ``expect`` imported straight from Playwright keeps Playwright's default.
expect = Expect()
expect.set_options(timeout=Budget.ASSERTION.ms)


class TimedOut(Exception):
    """A wait outlasted its budget; the message names what the drive waited for and the last state it read."""


T = TypeVar("T")


def until(ready: Callable[[], T | None], what: str, budget: Budget | float = Budget.SCREEN, *, page: Page | None = None) -> T:
    """Read ``ready`` until it gives something other than ``None`` or ``False``, and return that; ``what`` names it.

    An error of ``NOT_YET`` from ``ready`` is a state not ready yet, read again; any other error leaves at once. After
    ``budget`` (a number of seconds is a limit that a call of ``Run.wait_for`` still names itself) the wait fails with
    ``TimedOut``, naming the error of ``NOT_YET`` the last read raised, if it raised one, so a file that stays half
    written is a failure that names its state.

    A wait on what ``page`` sends waits inside Playwright, whose sync client delivers the page's events (a request, a
    route) only during its own calls: after ``time.sleep`` their record stays as it was (#1682).
    """

    limit_s = budget.value if isinstance(budget, Budget) else budget
    deadline = time.monotonic() + limit_s
    while True:
        last: Exception | None = None
        try:
            value = ready()
        except NOT_YET as not_yet:
            last, value = not_yet, None
        if value is not None and value is not False:
            print(f"  ok: {what}", flush=True)
            return value
        if time.monotonic() > deadline:
            state = "" if last is None else f"; the last read was not ready: {type(last).__name__}: {last}"
            raise TimedOut(f"timed out: {what}{state}") from last
        if page is None:
            time.sleep(POLL_S)
        else:
            page.wait_for_timeout(POLL_S * 1000)


def quiet_for(page: Page, ms: float = REPEAT_SETTLE_MS) -> None:
    """Let ``page`` run ``ms`` with nothing on its screen or in its requests to wait for: a click that should send nothing
    more, a hidden tab that should ask nothing, a time of the page that passes with nothing on screen.

    In the mode „wolny runner” a write of the tab leaves ``LATE_WRITE_MS`` late, so the quiet is that much longer and a
    write that should not come still falls inside it, instead of leaving after the drive counted the requests.
    """

    page.wait_for_timeout(ms + (LATE_WRITE_MS if SLOW_RUNNER in os.environ else 0))


def answer_late(route: Route, seconds: float, answer: Callable[[Route], None] = Route.continue_) -> None:
    """From inside the handler of ``route``, answer it with ``answer`` ``seconds`` later, as a server that answers late.

    The wait holds the drive's thread, so Playwright delivers no other event of the page before the answer.
    """

    time.sleep(seconds)
    answer(route)
