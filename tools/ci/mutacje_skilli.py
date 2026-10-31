"""Uruchamia po kolei każdy krok skilli weryfikacji, jak pełne CI ``main`` (push): podstawy ``ci:`` i skrypty mutacji.

Krok to podstawa ``ci:`` skilla albo jeden jego skrypt mutacji ``.agents/skills/<skill>/scripts/check_<co>_mutations.py``
(``tools/lib/kroki_skilli.py``). Podstawa biegnie przed skryptami mutacji swojego skilla i przechodzi z kodem 0. Skrypt
mutacji dowodzi, że sprawdzenie skilla pada na zepsutych wariantach kodu, i kończy się linią ``MUTACJE OK``. Polecenie
podstawy, które wybrany skrypt mutacji i tak uruchamia bez mutacji (podstawa ``check_all``), nie biegnie drugi raz.
Które kroki biegną w runie CI (push, pull request, noc) i dlaczego, rozstrzyga zakres runu
(``tools/lib/zakres_runu.py``); ten skrypt uruchamia zakres pushu, a plan CI (``tools/plan_ci.py``) dzieli kroki
zakresu swojego zdarzenia między zadania Mutation checks i uruchamia je tym samym ``run``, część skryptu z
``MUTACJE_CZESC`` (``tools/mutacje.py``).

Skrypt nie może zgubić się po cichu. FAIL dostaje plik ``.py`` w skillu z ``mutation`` w nazwie, który nie pasuje do
wzorca, skrypt mutacji wskazany w ``SKILL.md`` skilla, którego nie ma, i zły klucz ``ci:`` albo ``ci-czesci:``. FAIL
dostaje też skrypt, który przekroczył limit czasu, skończył się kodem innym niż 0 albo nie wydrukował na końcu
``MUTACJE OK``. Skrypt biegnie przez ``tools/lib/potomne.py``: jego procesy potomne giną po jego końcu i po limicie, a
cały skrypt ginie razem z runnerem, choćby zabitym przez SIGKILL. Kończy się ``MUTACJE SKILLI OK`` albo
``MUTACJE SKILLI FAIL | <skrypty>``.

    py -3 tools/ci/mutacje_skilli.py                  # Windows
    .venv/bin/python tools/ci/mutacje_skilli.py       # macOS i Linux
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from kroki_skilli import ROOT, Step
import potomne
from zakres_runu import Zdarzenie, zakres

# Najdłuższy skrypt trwał w CI na Windows 770 s; limit łapie zawieszenie, a nie wolny runner.
LIMIT_S = 30 * 60


def run(step: Step, limit_s: float = LIMIT_S, env: Mapping[str, str] | None = None) -> str | None:
    """Uruchamia krok z echem wyjścia i zmiennymi ``env``; zwraca powód porażki albo ``None``.

    Skrypt mutacji kończy się linią ``VERDICT``, podstawie wystarczy kod 0. Plan CI daje części skryptu
    ``MUTACJE_CZESC`` przez ``env``.
    """

    command = step.command
    try:
        done = potomne.run(
            [sys.executable, str(ROOT / command[0]), *command[1:]],
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})},
            timeout=limit_s,
            echo=True,
        )
    except subprocess.TimeoutExpired:
        return f"przekroczył limit {limit_s:.0f} s"
    if done.returncode != 0:
        return f"kod wyjścia {done.returncode}"
    if step.verdict is not None and [line.strip() for line in done.stdout.splitlines() if line.strip()][-1:] != [step.verdict]:
        return f"brak końcowej linii {step.verdict}"
    return None



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-s", type=float, default=LIMIT_S, help="Limit czasu jednego skryptu w sekundach.")
    args = parser.parse_args(argv)
    praca = zakres(Zdarzenie.PUSH, frozenset(), ROOT)
    failed = dict(praca.bledy)
    for name, why in praca.bledy:
        print(f"FAIL {name}: {why}", flush=True)
    # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
    for wybrany in praca.wybrane:
        step = wybrany.krok
        shown = step.name if step.verdict else f"{step.name}: {' '.join(step.command)}"
        print(f"== {shown}", flush=True)
        started = time.monotonic()
        reason = run(step, args.limit_s)
        elapsed = f"({time.monotonic() - started:.0f} s)"
        print(f"OK   {step.name} {elapsed}" if reason is None else f"FAIL {step.name} {elapsed}: {reason}", flush=True)
        if reason is not None:
            failed[step.name] = reason
    if failed:
        print(f"MUTACJE SKILLI FAIL | {', '.join(sorted(failed))}")
        return 1
    print("MUTACJE SKILLI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
