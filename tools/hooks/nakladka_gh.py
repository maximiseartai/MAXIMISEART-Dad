from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from nakladka import NAKLADKI, ZMIENNA_SESJI

SESSION = re.compile(r"[A-Za-z0-9._-]+")


def main() -> int:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return 0
    try:
        session = json.load(sys.stdin).get("session_id")
    except (ValueError, AttributeError, OSError):
        return 0
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        return 0
    with open(env_file, "a", encoding="utf-8") as env:
        env.write(f'export PATH={shlex.quote(str(NAKLADKI))}:"$PATH"\n')
        env.write(f"export {ZMIENNA_SESJI}={shlex.quote(session)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
