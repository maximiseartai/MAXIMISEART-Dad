from __future__ import annotations

import json
from pathlib import Path, PurePath
import shutil
import tempfile
from typing import Final

import odpalenia_ast_grep
import potomne

FRONTEND: Final = "frontend"
RULE: Final = "repo/no-comments"
CODE: Final = "repo(no-comments)"
PLUGIN: Final = ("tools", "oxlint", "repo", "index.ts")
CONFIG: Final = ".oxlintrc.json"
INSTALL: Final = "brak oxlint z zależności frontendu: uruchom npm ci w frontend/"


def oxlint(frontend: Path) -> str | None:
    return shutil.which("oxlint", path=str(frontend / "node_modules" / ".bin"))


def comments_on_added_lines(root: Path, base: str) -> list[odpalenia_ast_grep.Finding]:
    added: dict[str, set[int]] = {}
    for path, number, _ in odpalenia_ast_grep.Changes(root, base, FRONTEND).added():
        added.setdefault(path, set()).add(number)
    if not added:
        return []
    frontend = root / FRONTEND
    if (program := oxlint(frontend)) is None:
        raise odpalenia_ast_grep.ScanFailed(INSTALL)
    ignored = json.loads((frontend / CONFIG).read_text(encoding="utf-8")).get("ignorePatterns", [])
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder, CONFIG)
        only_rule = {"jsPlugins": [{"name": "repo", "specifier": str(frontend.joinpath(*PLUGIN))}], "rules": {RULE: "error"}}
        config.write_text(json.dumps(only_rule), encoding="utf-8")
        lint = potomne.run([program, "-c", str(config), "-A", "all", *(f"--ignore-pattern={pattern}" for pattern in ignored), "--format", "json"], cwd=frontend)
    if lint.returncode not in (0, 1):
        raise odpalenia_ast_grep.ScanFailed(f"oxlint zakończył się kodem {lint.returncode}:\n{lint.stderr}")
    found = []
    for diagnostic in json.loads(lint.stdout)["diagnostics"]:
        path = f"{FRONTEND}/{PurePath(diagnostic['filename']).as_posix()}"
        if diagnostic.get("code") != CODE:
            raise odpalenia_ast_grep.ScanFailed(f"oxlint nie sprawdził komentarzy {path}: {diagnostic['message']}")
        span = diagnostic["labels"][0]["span"]
        text = (root / path).read_bytes()
        first = text[: span["offset"]].count(b"\n") + 1
        lines = range(first, first + text[span["offset"] : span["offset"] + span["length"]].count(b"\n") + 1)
        if hits := sorted(added.get(path, set()).intersection(lines)):
            found.append(odpalenia_ast_grep.Finding(path, hits[0], RULE, diagnostic["message"]))
    return sorted(found)
