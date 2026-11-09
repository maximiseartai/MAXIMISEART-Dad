"""Stop the Centrum this verification run started and remove its run root; evidence is never touched.

The server is stopped only when its record (``harness.File.SERVER``) names it and its URL
still answers with Centrum's identity, so a reused PID or another program is
never killed. Processes are never killed by name.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import Parser, remove_run_root, require_run_root
from harness import File
from atrapy.pliki_taty import SERVICE


def _answers_as_centrum(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as response:
            return bool(json.load(response).get("service") == SERVICE)
    except (OSError, ValueError):
        return False


def _stop_server(root: Path) -> str:
    server_file = File.SERVER.file(root)
    if not server_file.exists():
        return "no server recorded"
    server = json.loads(server_file.read_text(encoding="utf-8"))
    url, pid = str(server["url"]), int(server["pid"])
    if not _answers_as_centrum(url):
        return "recorded server already stopped"
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while _answers_as_centrum(url):
        if time.monotonic() > deadline:
            raise OSError(f"Centrum at {url} (pid {pid}) did not stop")
        time.sleep(0.1)
    return f"stopped pid {pid}"


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_root("run root create_centrum_fixture.py created")
    root = parser.parse_args(argv).root
    try:
        stopped = _stop_server(require_run_root(root)) if root.exists() else "no run root"
        remove_run_root(root)
    except (OSError, ValueError) as exc:
        print(f"CLEANUP FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"CLEANUP OK | {stopped} | removed={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
