"""DIAGNOSTYKA #975 (do usunięcia przed końcem PR): ile par socket.socketpair() (otwórz i zamknij, jak pętla zdarzeń)
przechodzi na tym runnerze, zanim pierwsza padnie albo zawiśnie, i z jakim błędem."""

import socket
import subprocess
import time

# Bez limitu accept() w socketpair() czeka bez końca, gdy połączenie nie dojdzie (pierwsza sonda wisiała > 5 min).
socket.setdefaulttimeout(5)
start = time.monotonic()
made = 0
error = "brak"
slowest = 0.0
while made < 40000 and time.monotonic() - start < 120:
    began = time.monotonic()
    try:
        a, b = socket.socketpair()
    except OSError as exc:
        error = repr(exc)
        break
    slowest = max(slowest, time.monotonic() - began)
    a.close()
    b.close()
    made += 1
    if made % 1000 == 0:
        print(f"DIAG975 SONDA postęp | par {made} w {time.monotonic() - start:.1f} s | najdłuższa {slowest:.3f} s", flush=True)
print(f"DIAG975 SONDA | par {made} w {time.monotonic() - start:.1f} s | błąd {error} | najdłuższa {slowest:.3f} s", flush=True)
try:
    netstat = subprocess.run(["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, check=True, timeout=60).stdout
    print(f"DIAG975 SONDA | TIME_WAIT {sum('TIME_WAIT' in line for line in netstat.splitlines())}", flush=True)
except subprocess.TimeoutExpired:
    print("DIAG975 SONDA | netstat bez odpowiedzi w 60 s", flush=True)
