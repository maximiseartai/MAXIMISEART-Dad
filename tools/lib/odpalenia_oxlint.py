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
        added.setdefault(PurePath(path).relative_to(FRONTEND).as_posix(), set()).add(number)
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
        no_ignore_file = Path(folder, "pusty-ignore")
        no_ignore_file.write_text("", encoding="utf-8")
        rule_only = [program, "-c", str(config), "-A", "all"]
        listing = potomne.run(
            [*rule_only, f"--ignore-path={no_ignore_file}", *(f"--ignore-pattern={pattern}" for pattern in ignored), "--debug=files", "--", *sorted(added)],
            cwd=frontend,
        )
        linted = listing.stdout.splitlines()
        if listing.returncode != 0 or not set(linted) <= added.keys():
            raise odpalenia_ast_grep.ScanFailed(f"oxlint --debug=files zakończył się kodem {listing.returncode}:\n{listing.stdout}{listing.stderr}")
        if not linted:
            return []
        paths = {str(frontend / name): name for name in linted}
        lint = potomne.run([*rule_only, "--no-ignore", "--format", "json", "--", *paths], cwd=Path(folder))
    if lint.returncode not in (0, 1):
        raise odpalenia_ast_grep.ScanFailed(f"oxlint zakończył się kodem {lint.returncode}:\n{lint.stderr}")
    found = []
    for diagnostic in json.loads(lint.stdout)["diagnostics"]:
        if (name := paths.get(diagnostic["filename"])) is None:
            raise odpalenia_ast_grep.ScanFailed(f"oxlint zgłosił plik spoza listy {diagnostic['filename']}: {diagnostic['message']}")
        if diagnostic.get("code") != CODE:
            raise odpalenia_ast_grep.ScanFailed(f"oxlint nie sprawdził komentarzy {FRONTEND}/{name}: {diagnostic['message']}")
        span = diagnostic["labels"][0]["span"]
        text = (frontend / name).read_bytes()
        first = text[: span["offset"]].count(b"\n") + 1
        lines = range(first, first + text[span["offset"] : span["offset"] + span["length"]].count(b"\n") + 1)
        if hits := sorted(added[name].intersection(lines)):
            found.append(odpalenia_ast_grep.Finding(f"{FRONTEND}/{name}", hits[0], RULE, diagnostic["message"]))
    return sorted(found)
