"""The drive's one way to wait until a file or a state of the run is ready, and the budgets that limit a wait.

The server and its threads write the run's files at any moment, so a read inside a wait can meet a file that does not
exist yet, is empty, half written, or refused for a moment on Windows while it is put in place. Each of those is
``NOT_YET``: the wait reads again, as it does after a ``None`` or ``False``. Any other error is a defect of the drive
or of Centrum and ends the wait at once.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import json
import time
from typing import TypeVar

import yaml

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


class Budget(Enum):
    """The longest a wait may take, in seconds, named by what the drive waits for."""

    # Centrum answers on its screen, through its API or in the run's files to what Dad or the harness has just done.
    SCREEN = 10.0


class TimedOut(Exception):
    """A wait outlasted its budget; the message names what the drive waited for and the last state it read."""


T = TypeVar("T")


def until(ready: Callable[[], T | None], what: str, budget: Budget | float = Budget.SCREEN) -> T:
    """Read ``ready`` until it gives something other than ``None`` or ``False``, and return that; ``what`` names it.

    An error of ``NOT_YET`` from ``ready`` is a state not ready yet, read again; any other error leaves at once. After
    ``budget`` (a number of seconds is a limit that a call of ``Run.wait_for`` still names itself) the wait fails with
    ``TimedOut``, naming the error of ``NOT_YET`` the last read raised, if it raised one, so a file that stays half
    written is a failure that names its state.
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
        time.sleep(POLL_S)
