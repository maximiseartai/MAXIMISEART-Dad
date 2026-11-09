"""Read-only doctor: is the Centrum on Dad's port this run's, started from its tool, and answering?

    py -3 .agents\\skills\\verify-centrum-na-windowsie\\scripts\\windows_doctor.py --root <run root>

Prints ``DOCTOR OK | pid=… | commit=… | process=… | tool=…`` or ``DOCTOR FAIL | <reason>`` (exit code 1).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.request

import windows_desktop
import windows_tool

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import Parser
from atrapy.pliki_taty import SERVICE


def diagnose(root: Path) -> str:
    if sys.platform != "win32":
        return "DOCTOR FAIL | this skill drives Windows only"
    if not (root / windows_tool.FACTS).is_file():
        return f"DOCTOR FAIL | no {windows_tool.FACTS} in {root}: not a run root"
    facts = windows_tool.load(root)
    tool = Path(facts["tool"])
    if not (tool / ".git").is_dir():
        return f"DOCTOR FAIL | the tool's clone {tool} does not exist (instalacja did not run)"
    pid = windows_desktop.port_owner(facts["port"])
    if pid is None:
        return f"DOCTOR FAIL | nothing listens on port {facts['port']}"
    found = [process for process in windows_desktop.processes() if process.pid == pid]
    if not found or str(tool / "run_centrum.py").casefold() not in found[0].command_line.casefold():
        return f"DOCTOR FAIL | port {facts['port']} belongs to pid {pid}, not to this run's tool: {found}"
    try:
        with urllib.request.urlopen(facts["url"] + "api/health", timeout=5) as response:
            health = json.load(response)
    except OSError as failure:
        return f"DOCTOR FAIL | /api/health does not answer: {failure}"
    head = windows_tool.git(tool, "rev-parse", "HEAD", machine=True)
    if health.get("service") != SERVICE or health.get("commit") != head[:7]:
        return f"DOCTOR FAIL | /api/health {health} is not Centrum on the clone's commit {head[:7]}"
    return f"DOCTOR OK | pid={pid} | commit={head[:7]} | process={found[0].name} | tool={tool}"


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root of this Windows run")
    verdict = diagnose(parser.parse_args(argv).root)
    print(verdict, flush=True)
    return 0 if verdict.startswith("DOCTOR OK") else 1


if __name__ == "__main__":
    raise SystemExit(main())
