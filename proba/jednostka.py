"""Próba: cała jednostka verify-urwane-uruchomienie/ci z model_tlc z main (seq) albo równoległym (par, par2).

python proba/jednostka.py <wariant>... ; drukuje czas jednostki, werdykt i czas oraz stany każdego przebiegu.
"""
import contextlib
import io
import os
import re
import runpy
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/lib"))
SKRYPT = ROOT / ".agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py"
ZRODLO = {"seq": ROOT / "proba/model_tlc_main.py", "par": ROOT / "tools/lib/model_tlc.py", "par2": ROOT / "tools/lib/model_tlc.py"}
FINAL = '"auto",\n                "-lncheck",\n                "final",'


def load(name: str):
    base = name.removesuffix("f")
    src = ZRODLO[base].read_text(encoding="utf-8")
    if name.endswith("f"):
        assert '"auto",' in src
        src = src.replace('"auto",', FINAL, 1)
    mod = types.ModuleType("model_tlc")
    mod.__file__ = str(ZRODLO[base])
    sys.modules["model_tlc"] = mod
    exec(compile(src, str(ZRODLO[base]), "exec"), mod.__dict__)  # noqa: S102
    name = base
    if name == "par2":
        mod.os = type("os2", (), {"cpu_count": staticmethod(lambda: 2), "environ": os.environ})
    original = mod.tlc

    def timed(java, jar, spec, cfg_name, text, *rest):
        t = time.monotonic()
        out = original(java, jar, spec, cfg_name, text, *rest)
        found = re.findall(r"(\d+) states generated, (\d+) distinct states found", out)
        key = ";".join(sorted(x.strip() for x in text.splitlines() if "Wybaczone" in x and "{}" not in x)) or "-"
        verdict = "ok" if "No error has been found" in out else (re.search(r"Invariant \w+ is violated|Temporal properties were violated", out) or ["?"])[0]
        print(f"PRZEBIEG\t{name}\t{cfg_name}\t{key[:70]}\t{time.monotonic() - t:.1f}\t{found[-1] if found else '?'}\t{verdict}\tposrednie {out.count('for the current state space')}", file=sys.stderr, flush=True)
        return out

    mod.tlc = timed


for wariant in sys.argv[1:]:
    load(wariant)
    sys.argv = [str(SKRYPT), *(["--config", os.environ["PROBA_CONFIG"]] if os.environ.get("PROBA_CONFIG") else [])]
    buf = io.StringIO()
    t = time.monotonic()
    with contextlib.redirect_stdout(buf):
        try:
            runpy.run_path(str(SKRYPT), run_name="__main__")
        except SystemExit as done:
            code = done.code
    print(f"JEDNOSTKA\t{wariant}\t{time.monotonic() - t:.1f}\tkod {code}\t{buf.getvalue().strip().splitlines()[-1]}", file=sys.stderr, flush=True)
