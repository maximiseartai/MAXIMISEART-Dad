"""Próba: drogi przebieg TLC (konfiguracja bez znanych znalezisk) w wariantach flag, przeplatanych na jednej maszynie.

python proba/tlc_warianty.py <konfiguracja> <wariant>... ; drukuje TSV i fazy z własnych znaczników czasu TLC.
"""
import datetime
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/lib"))
import model_tlc  # noqa: E402
import narzedzia_tlc  # noqa: E402

SKRYPT = ROOT / ".agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py"
GC = ["-XX:+UseParallelGC"]
WARIANTY = {
    "baza": (GC, None, "auto"),
    "dtemp": (GC, "RUNNER_TEMP", "auto"),
    "xms8": ([*GC, "-Xms8g", "-Xmx8g"], None, "auto"),
    "w3": (GC, None, "3"),
    "w2": (GC, None, "2"),
}
TS = r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)"


def ts(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def phases(out: str, started: datetime.datetime) -> str:
    start = re.search(r"Starting\.\.\. \(" + TS, out)
    complete = re.search(r"complete state space with \d+ total distinct states at \(" + TS, out)
    live = re.findall(r"Finished checking temporal properties in (\S+) at", out)
    inter = len(re.findall(r"for the current state space", out))
    if not (start and complete):
        return "fazy ?"
    jvm = (ts(start[1]) - started).total_seconds()
    bfs = (ts(complete[1]) - ts(start[1])).total_seconds()
    return f"jvm+parse ~{jvm:.0f}\tbfs {bfs:.0f}\tliveness {live[-1] if live else '?'}\tposrednie {inter}"


def main() -> None:
    config_name, variants = sys.argv[1], sys.argv[2:]
    spec = importlib.util.spec_from_file_location("m", SKRYPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    model = mod.MODEL
    config = next(c for c in model_tlc.konfiguracje(model) if c.nazwa == config_name)
    text = model_tlc.cfg(model, config, frozenset((f.obietnica, f.przyczyna) for f in config.znane))
    cache = ROOT / narzedzia_tlc.KATALOG
    java, jar = narzedzia_tlc.java(cache), Path(narzedzia_tlc.jar(cache))
    tla = model.skill / "model" / model.specyfikacja
    print(f"cpu {os.cpu_count()} TEMP {tempfile.gettempdir()} RUNNER_TEMP {os.environ.get('RUNNER_TEMP')}", flush=True)
    for name in variants:
        opts, root_env, workers = WARIANTY[name]
        root = os.environ.get(root_env) if root_env else None
        with tempfile.TemporaryDirectory(prefix="tlc-", dir=root) as work:
            shutil.copy2(tla, work)
            Path(work, f"{config_name}.cfg").write_text(text, encoding="utf-8")
            cmd = [java, *opts, f"-Djava.io.tmpdir={work}", "-cp", str(jar), "tlc2.TLC", "-workers", workers,
                   "-metadir", str(Path(work, "stany")), "-config", f"{config_name}.cfg", tla.name]
            started = datetime.datetime.now().replace(microsecond=0)
            t = time.monotonic()
            r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
            s = time.monotonic() - t
        out = r.stdout + r.stderr
        found = re.findall(r"(\d+) states generated, (\d+) distinct states found", out)
        gen, dist = found[-1] if found else ("?", "?")
        verdict = "ok" if "No error has been found" in out else "BLAD"
        print(f"WYNIK\t{name}\t{s:.1f}\t{gen}\t{dist}\t{verdict}\t{phases(out, started)}", flush=True)
        for line in out.splitlines():
            if re.match(r"(Running|Starting|Checking temporal|Finished checking|Finished in|Progress)", line):
                print("   " + line[:200], flush=True)
        if verdict != "ok":
            print(out[-3000:], flush=True)


main()
