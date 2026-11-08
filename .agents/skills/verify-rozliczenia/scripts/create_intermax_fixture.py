"""Create a disposable synthetic INTERMAX (Rejestr zleceń) with one day of Surowe zlecenia for Uporządkowanie INTERMAX.

The workbook comes from the INTERMAX fixture of the tests (``tests/fixtures/intermax.py``), shaped like Dad's
file: ordered days in Calibri 8, his yellow row, and below it one pasted day of Surowe zlecenia with the look from
the company app, the first row shifted two columns left. The empty ``Kopie INTERMAX`` folder sits next to it. The
manifest keeps the INTERMAX bytes' hash, its last ordered row and the moment the fixture was written, for
``assert_intermax.py``. Every value is synthetic.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from skrypt_skilla import Parser, create_run_root

from tests.fixtures.intermax import Intermax, Order
from tests.fixtures.scenariusz_rozliczen import REGISTER_NAME

COPIES_DIRECTORY = "Kopie INTERMAX"
MANIFEST_NAME = "intermax_manifest.json"
# One pasted day (Monday 26.10.2026) of three Wykonawcy in the order the company app gave them, no two at one hour.
RAW_ORDERS = (
    Order(datetime(2026, 10, 26, 14), "jan.nowak", 78201),
    Order(datetime(2026, 10, 26, 10), "anna.kowalska", 78202),
    Order(datetime(2026, 10, 26, 16), "anna.kowalska", 78203),
    Order(datetime(2026, 10, 26, 8), "jan.nowak", 78204),
    Order(datetime(2026, 10, 26, 11), "anna.kowalska", 78205),
    Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 78206),
)
# Values of the fixture's rows (NUMER ZL., NUMER UMOWY, ADRES, Hiperłącze); none may reach a result or evidence.
ROW_MARKERS = ("ZL-782", "UM-782", "Ulica 782", "example.invalid/zlecenie")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root to create; absent or empty")
    args = parser.parse_args(argv)
    created_at = datetime.now().astimezone().replace(microsecond=0)
    try:
        root = create_run_root(args.root)
        register = root / REGISTER_NAME
        layout = Intermax(raw=RAW_ORDERS).write(register)
        (root / COPIES_DIRECTORY).mkdir()
    except (OSError, ValueError) as exc:
        print(f"FIXTURE FAILED: {exc}", file=sys.stderr)
        return 1
    manifest = {
        "register_sha256": hashlib.sha256(register.read_bytes()).hexdigest(),
        "last_ordered_row": layout.last_ordered,
        "created_at": created_at.isoformat(),
    }
    (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    workers = len({order.worker for order in RAW_ORDERS})
    print(f"FIXTURE OK | intermax=true | raw_orders={len(RAW_ORDERS)} | workers={workers} | copies=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
