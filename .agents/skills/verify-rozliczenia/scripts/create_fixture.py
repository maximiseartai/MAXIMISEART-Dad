"""Create disposable synthetic workbooks for the rozliczenia verification skill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from skrypt_skilla import Parser, create_run_root

from atrapy.scenariusz_rozliczen import (
    SETTLEMENT_ADDRESS,
    SETTLEMENT_CITY,
    SETTLEMENT_ORDER_LINK,
    SETTLEMENT_ROWS,
    UNMAPPED_ROW,
    WORKER_TEMPLATE_NAME,
)
from atrapy.pliki_taty import WORKER_CONFIG_NAME
from atrapy.settlement import (
    PERIOD,
    SOURCE_NAME,
    WORKERS,
    SourceRow,
    link_order_numbers,
    write_mapping,
    write_source_rows,
    write_template,
)


def _write_source(path: Path, *, include_unmapped: bool) -> None:
    rows = [*SETTLEMENT_ROWS, UNMAPPED_ROW] if include_unmapped else SETTLEMENT_ROWS
    write_source_rows(path, [SourceRow(SETTLEMENT_CITY, SETTLEMENT_ADDRESS, worker, marker) for worker, marker in rows])
    link_order_numbers(path, SETTLEMENT_ORDER_LINK)


def _write_fixture(root: Path, *, include_unmapped: bool) -> None:
    period_directory = root / PERIOD
    period_directory.mkdir(parents=True, exist_ok=False)
    source = period_directory / SOURCE_NAME
    worker_template = root / WORKER_TEMPLATE_NAME
    _write_source(source, include_unmapped=include_unmapped)
    write_mapping(root / WORKER_CONFIG_NAME)
    write_template(worker_template)
    manifest = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "worker_template_sha256": hashlib.sha256(worker_template.read_bytes()).hexdigest(),
        "include_unmapped": include_unmapped,
    }
    (root / "fixture_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root to create; absent or empty")
    parser.add_argument("--include-unmapped", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = create_run_root(args.root)
        _write_fixture(root, include_unmapped=args.include_unmapped)
    except (OSError, ValueError) as exc:
        print(f"FIXTURE FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"FIXTURE_READY root={root} period={PERIOD} workers={len(WORKERS)} unmapped={args.include_unmapped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
