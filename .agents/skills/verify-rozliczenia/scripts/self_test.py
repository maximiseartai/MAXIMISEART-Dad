"""Check the verification skill package and its evidence hygiene."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from create_intermax_fixture import ROW_MARKERS as INTERMAX_ROW_MARKERS
from skrypt_skilla import Parser, create_run_root, new_run

from tests.fixtures.scenariusz_rozliczen import ROW_CONTENT_MARKERS as SCENARIO_ROW_MARKERS

SCRIPT = Path(__file__).resolve()
SKILL_ROOT = SCRIPT.parents[1]
REPO_ROOT = SCRIPT.parents[4]
FEATURES_ROOT = SKILL_ROOT / "features"
SCRIPTS_ROOT = SKILL_ROOT / "scripts"
HELPER_REFERENCE = re.compile(r"scripts[\\/]([A-Za-z0-9_.-]+\.py)")

REQUIRED_FRONTMATTER = ("name", "description")
REQUIRED_MAP_HEADINGS = (
    "# Rozliczenia verification map",
    "## Baseline preconditions",
    "## Driving conventions",
    "## Proof and skip reporting",
    "## Features",
)
REQUIRED_FEATURE_HEADINGS = (
    "## Sub-features",
    "## How to get to it (user POV)",
    "## Driving it with PowerShell and the machine script",
    "## Gotchas",
)

# Row content of every fixture the skill creates; none may reach the evidence.
ROW_CONTENT_MARKERS = (*SCENARIO_ROW_MARKERS, *INTERMAX_ROW_MARKERS)


def _read_utf8(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _check_frontmatter(errors: list[str]) -> None:
    path = SKILL_ROOT / "SKILL.md"
    try:
        lines = _read_utf8(path).splitlines()
    except (OSError, UnicodeDecodeError):
        errors.append("SKILL.md is not readable as UTF-8")
        return

    if not lines or lines[0].strip() != "---":
        errors.append("SKILL.md is missing opening frontmatter")
        return
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        errors.append("SKILL.md is missing closing frontmatter")
        return

    values: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    for key in REQUIRED_FRONTMATTER:
        if not values.get(key):
            errors.append(f"SKILL.md frontmatter is missing {key}")
    if values.get("name") != "verify-rozliczenia":
        errors.append("SKILL.md frontmatter has the wrong name")


def _check_headings(errors: list[str]) -> None:
    map_path = FEATURES_ROOT / "README.md"
    feature_files = sorted(path for path in FEATURES_ROOT.glob("*.md") if path.name != "README.md")
    if not map_path.is_file():
        errors.append("feature map README.md is missing")
        return
    if not feature_files:
        errors.append("feature map has no feature documents")

    try:
        map_lines = _read_utf8(map_path).splitlines()
    except (OSError, UnicodeDecodeError):
        errors.append("feature map README.md is not readable as UTF-8")
    else:
        headings = {line.strip() for line in map_lines if line.startswith("#")}
        for heading in REQUIRED_MAP_HEADINGS:
            if heading not in headings:
                errors.append(f"feature map is missing heading {heading}")

    for path in feature_files:
        try:
            headings = {line.strip() for line in _read_utf8(path).splitlines() if line.startswith("#")}
        except (OSError, UnicodeDecodeError):
            errors.append(f"feature document is not readable as UTF-8: {path.name}")
            continue
        for heading in REQUIRED_FEATURE_HEADINGS:
            if heading not in headings:
                errors.append(f"{path.name} is missing heading {heading}")


def _helper_references() -> set[str]:
    references: set[str] = set()
    documents = [SKILL_ROOT / "SKILL.md", *sorted(FEATURES_ROOT.glob("*.md"))]
    for path in documents:
        references.update(HELPER_REFERENCE.findall(_read_utf8(path)))
    return references


def _check_helpers(errors: list[str]) -> None:
    try:
        references = _helper_references()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"could not read helper references: {exc.__class__.__name__}")
        return

    available = {path.name for path in SCRIPTS_ROOT.glob("*.py")}
    for name in sorted(references - available):
        errors.append(f"referenced helper path is missing: {name}")
    for name in sorted(available - references):
        errors.append(f"helper is not referenced by the skill: {name}")

    for name in sorted(references & available):
        path = SCRIPTS_ROOT / name
        try:
            result = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            errors.append(f"helper cannot execute: {name}")
            continue
        if result.returncode != 0:
            errors.append(f"helper --help failed: {name}")


def _check_evidence(errors: list[str], evidence_root: Path) -> None:
    if not evidence_root.is_dir():
        errors.append("evidence root is missing")
        return
    files = sorted(path for path in evidence_root.rglob("*") if path.is_file())
    if not files:
        errors.append("evidence root is empty")
        return
    for path in files:
        try:
            content = _read_utf8(path)
        except (OSError, UnicodeDecodeError):
            errors.append(f"evidence is not UTF-8: {path.relative_to(evidence_root)}")
            continue
        if any(marker in content for marker in ROW_CONTENT_MARKERS):
            errors.append(f"source row content found in evidence: {path.relative_to(evidence_root)}")


def _check_cleanup_preserves_evidence(errors: list[str], run_dir: Path) -> None:
    run = new_run(run_dir, f"self-test-{uuid.uuid4().hex}")
    run_root, evidence_root = run.root, run.evidence
    evidence_file = evidence_root / "proof.txt"
    marker = "dowod zachowany: ŻÓŁĆ\n".encode("utf-8")
    try:
        create_run_root(run_root)
        (run_root / "disposable.txt").write_text("scratch\n", encoding="utf-8")
        evidence_file.write_bytes(marker)
        cleanup = SCRIPTS_ROOT / "cleanup.py"
        try:
            result = subprocess.run(
                [sys.executable, str(cleanup), "--root", str(run_root)],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            errors.append("cleanup helper could not execute for the evidence probe")
            return
        if result.returncode != 0:
            errors.append("cleanup helper failed for the evidence probe")
            return
        if run_root.exists():
            errors.append("cleanup left disposable run data behind")
        try:
            preserved = evidence_file.read_bytes()
            preserved.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append("cleanup removed or corrupted evidence")
        else:
            if preserved != marker:
                errors.append("cleanup changed preserved evidence")
    except OSError:
        errors.append("could not create the cleanup evidence probe")
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
        shutil.rmtree(evidence_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_run_dir()
    args = parser.parse_args(argv)

    errors: list[str] = []
    _check_frontmatter(errors)
    _check_headings(errors)
    _check_helpers(errors)
    _check_evidence(errors, args.evidence_root.expanduser().resolve())
    _check_cleanup_preserves_evidence(errors, args.run_dir)

    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: {error}", file=sys.stderr)
        return 1
    print("SELF-TEST OK | frontmatter=true | feature_map=true | helpers=true | evidence_utf8=true | cleanup_preserves_evidence=true | row_contents_logged=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
