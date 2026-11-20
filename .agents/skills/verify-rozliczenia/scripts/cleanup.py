from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import Parser, remove_run_root

OPIS = """Remove one disposable verification run without touching its evidence."""


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=OPIS)
    parser.add_root("run root a fixture of this skill created")
    args = parser.parse_args(argv)
    try:
        remove_run_root(args.root)
    except (OSError, ValueError) as exc:
        print(f"CLEANUP FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"CLEANUP OK | removed={args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
