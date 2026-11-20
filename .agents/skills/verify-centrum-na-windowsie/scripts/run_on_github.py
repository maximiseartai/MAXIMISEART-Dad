from __future__ import annotations

from contextlib import suppress
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

import github
from skrypt_skilla import Parser

OPIS = """Run verify-centrum-na-windowsie on GitHub's Windows machine from any computer, and bring the evidence home.

    .venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py [--feature all] [--ref <branch>]
    .venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py --run <run id>

Without ``--run`` it dispatches the workflow ``verify-centrum-na-windowsie.yml`` on ``--ref`` (default: the current
branch, which must be pushed; the workflow must already be on ``main`` for a dispatch). With ``--run`` it waits for
an existing run, e.g. the one a pull request started. Either way it waits for the run, downloads its evidence to
``<run dir>/evidence/github-<run id>/`` (``--run-dir``, default ``.verification``) and prints the run's own ``VERIFY OK``/``VERIFY FAIL`` line, exiting 0
only for ``VERIFY OK``. A run takes about 10 minutes: start this as a background command.

The verdict is about the local ``HEAD``: a run of another commit (``headSha``) gives ``VERIFY FAIL``, and the verdict
line names the run's commit (``head=``). A dispatch refuses to start when ``origin/<ref>`` is not ``HEAD`` and accepts
only a dispatched run of that commit.
"""

REPO_ROOT = Path(__file__).resolve().parents[4]

WORKFLOW = "verify-centrum-na-windowsie.yml"


def _gh(*args: str) -> str:
    try:
        return github.gh(*args, limit_s=None).strip()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"VERIFY FAIL | gh {' '.join(args)}: {error.stderr.strip()}") from None


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"VERIFY FAIL | git {' '.join(args)}: {' '.join(result.stderr.split())}")
    return result.stdout.strip()


def _dispatch(ref: str, feature: str, head: str) -> str:
    _git("fetch", "--quiet", "origin", ref)
    pushed = _git("rev-parse", f"origin/{ref}")
    if pushed != head:
        raise SystemExit(f"VERIFY FAIL | origin/{ref} is {pushed}, not HEAD {head}: push HEAD to {ref} first | head={head}")
    started = time.time()
    _gh("workflow", "run", WORKFLOW, "--ref", ref, "-f", f"feature={feature}")
    for _ in range(60):
        runs = json.loads(
            _gh("run", "list", "--workflow", WORKFLOW, "--branch", ref, "--event", "workflow_dispatch",
                "--limit", "5", "--json", "databaseId,createdAt,headSha")
        )
        for run in runs:
            created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00")).timestamp()
            if created >= started - 60 and run["headSha"] == head:
                return str(run["databaseId"])
        time.sleep(5)
    raise SystemExit(f"VERIFY FAIL | the dispatched run of {head} did not appear within 5 minutes | head={head}")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=OPIS)
    parser.add_run_dir()
    parser.add_argument("--feature", default="all")
    parser.add_argument("--ref", default=None)
    parser.add_argument("--run", default=None, help="Wait for this existing run instead of dispatching one.")
    args = parser.parse_args(argv)
    head = _git("rev-parse", "HEAD")
    run_id = args.run
    if run_id is None:
        ref = args.ref or _git("branch", "--show-current")
        run_id = _dispatch(ref, args.feature, head)
    print(f"RUN {run_id} | https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/{run_id}", flush=True)
    with suppress(subprocess.CalledProcessError):
        github.gh("run", "watch", run_id, "--interval", "30", limit_s=None)
    run = json.loads(_gh("run", "view", run_id, "--json", "conclusion,headSha"))
    conclusion, checked = run["conclusion"], run["headSha"]
    evidence = args.run_dir / "evidence" / f"github-{run_id}"
    evidence.mkdir(parents=True, exist_ok=True)
    with suppress(subprocess.CalledProcessError):
        github.gh("run", "download", run_id, "--dir", str(evidence), limit_s=None)
    verdicts = [
        line
        for drive in sorted(evidence.rglob("drive.txt"))
        for line in drive.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(("VERIFY OK", "VERIFY FAIL"))
    ]
    verdict = verdicts[-1] if verdicts else f"VERIFY FAIL | no verdict in the evidence (run {conclusion})"
    if checked != head:
        verdict = f"VERIFY FAIL | the run checked {checked}, not HEAD {head}"
    print(f"{verdict} | run={run_id} | head={checked} | conclusion={conclusion} | downloaded={evidence}", flush=True)
    return 0 if verdict.startswith("VERIFY OK") and conclusion == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
