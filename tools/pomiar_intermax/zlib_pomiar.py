# mypy: ignore-errors
# ruff: noqa: E401, E702
"""Czas zlib (i isal, zlib-ng, gdy są) na arkuszu zleceń syntetycznego INTERMAX: kompresja 1 i 6, rozpakowanie."""
import importlib, json, statistics, sys, time, zipfile

xml = zipfile.ZipFile(sys.argv[1]).read("xl/worksheets/sheet2.xml")
out = {"xml_bytes": len(xml)}
for name in ("zlib", "isal.isal_zlib", "zlib_ng.zlib_ng"):
    try:
        mod = importlib.import_module(name)
    except ImportError:
        out[name] = "brak"
        continue
    row = {}
    for level in (1, 2, 6):
        if name.startswith("isal") and level > 3:
            continue
        times = []
        for _ in range(3):
            t = time.perf_counter()
            c = mod.compressobj(level, mod.DEFLATED, -15)
            data = c.compress(xml) + c.flush()
            times.append(time.perf_counter() - t)
        row[f"L{level}_ms"] = round(statistics.median(times) * 1000)
        row[f"L{level}_bytes"] = len(data)
    times = []
    for _ in range(3):
        t = time.perf_counter()
        mod.decompress(data, -15)
        times.append(time.perf_counter() - t)
    row["inflate_ms"] = round(statistics.median(times) * 1000)
    out[name] = row
t = time.perf_counter(); zipfile.ZipFile(sys.argv[1]).read("xl/worksheets/sheet2.xml"); out["zipfile_read_ms"] = round((time.perf_counter() - t) * 1000)
print(json.dumps(out))
