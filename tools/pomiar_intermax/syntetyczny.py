# mypy: ignore-errors
"""Syntetyczny INTERMAX w skali taty (fixture testów, bez danych klientów): ~44 tys. uporządkowanych wierszy i wklejenie.

Użycie (z korzenia repozytorium): python syntetyczny.py WYJŚCIE [WIERSZE]
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from tests.fixtures.intermax import Intermax, Order

out = Path(sys.argv[1])
rows = int(sys.argv[2]) if len(sys.argv) > 2 else 44_000
per_day = 85
start = datetime(2026, 10, 25) - timedelta(days=rows // per_day + 1)
ordered = tuple(
    Order(start + timedelta(days=index // per_day, hours=8, minutes=(index % per_day) * 6), f"wykonawca.{(index % per_day) // 6:02d}", index)
    for index in range(rows)
)
raw = tuple(
    Order(datetime(2026, 10, 26, 8) + timedelta(minutes=(7 * index) % 600), f"wykonawca.{index % 14:02d}", 900_000 + index)
    for index in range(84)
)
Intermax(ordered=ordered, raw=raw).write(out)
print(out, out.stat().st_size)
