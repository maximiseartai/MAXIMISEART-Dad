# mypy: ignore-errors
# ruff: noqa: E401, E402, E702, E731
"""Mierzy Uporządkowanie INTERMAX w procesie (jak Centrum) na kopii wklejonego INTERMAX.

Użycie: mierz.py REPO PLIK N  → JSON: mediana i zakres czasu całości i etapów, liczby, błędy, odcisk wyniku.
Odcisk to sha256 rozpakowanych części wyniku (bez zależności od poziomu kompresji).
"""
import hashlib, json, shutil, statistics, sys, tempfile, time, zipfile
from datetime import datetime
from pathlib import Path

repo, source, n = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
sys.path.insert(0, str(repo / "src"))
from rozliczenia import intermax_ordering
from rozliczenia.intermax_replace import Waiting

NOW = datetime(2026, 11, 7, 9, 0).astimezone()
totals, phases, errors, prints, counts = [], {}, 0, set(), set()
for i in range(n):
    work = Path(tempfile.mkdtemp(prefix="hc-intermax-"))
    register = work / "ZLECENIA INTERMAX.xlsx"
    shutil.copyfile(source, register)
    try:
        t = time.perf_counter()
        summary = intermax_ordering.order_register(register, work / "kopie", now=lambda: NOW, waiting=Waiting())
        totals.append((time.perf_counter() - t) * 1000)
    except Exception as error:  # noqa: BLE001
        errors += 1
        print("błąd", type(error).__name__, error, file=sys.stderr)
        continue
    for phase, ms in summary.phase_durations_ms.items():
        phases.setdefault(phase.value, []).append(ms)
    counts.add((summary.order_count, summary.worker_count))
    with zipfile.ZipFile(register) as z:
        digest = hashlib.sha256()
        for info in z.infolist():
            digest.update(info.filename.encode()); digest.update(z.read(info))
    prints.add(digest.hexdigest()[:16])
    shutil.rmtree(work)
med = lambda xs: round(statistics.median(xs)) if xs else None
print(json.dumps({
    "n": n, "errors": errors, "total_ms": med(totals), "range_ms": [round(min(totals)), round(max(totals))] if totals else None,
    "phases_ms": {k: med(v) for k, v in phases.items()}, "orders_workers": sorted(counts), "output": sorted(prints),
}, ensure_ascii=False))
