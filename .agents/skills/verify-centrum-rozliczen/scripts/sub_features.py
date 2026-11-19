from __future__ import annotations

import argparse
from pathlib import Path
import sys

from drive import FEATURES

OPIS = """Prints the section ``## Sub-features`` of a feature file from the evidence of a run that drove the feature.

``drive_centrum.py`` builds the section from the steps and checks the drive ran (``sections`` there) and writes it to
``<evidence>/sekcje-z-biegu/<feature>.md``; ``run_centrum_verification.py --feature <feature>`` prints the evidence
directory as ``EVIDENCE <dir>``, and so does the artifact of a CI run.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feature", required=True, choices=[each.name for each in FEATURES])
    parser.add_argument("--evidence", required=True, type=Path, help="The evidence directory of a run that drove the feature.")
    args = parser.parse_args()
    section = args.evidence / "sekcje-z-biegu" / f"{args.feature}.md"
    if not section.is_file():
        raise SystemExit(f"{section} is missing; run run_centrum_verification.py --feature {args.feature} and pass its EVIDENCE")
    # Bytes, so the Windows console (cp1252) neither refuses Polish letters nor turns line ends into CRLF.
    sys.stdout.buffer.write(section.read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
