"""DIAGNOSTYKA #975 (do usunięcia przed końcem PR): ile par socket.socketpair() (otwórz i zamknij, jak pętla zdarzeń)
przechodzi na tym runnerze, zanim pierwsza padnie, i z jakim błędem."""

import socket
import subprocess
import time

start = time.monotonic()
made = 0
error = "brak"
while made < 40000 and time.monotonic() - start < 150:
    try:
        a, b = socket.socketpair()
    except OSError as exc:
        error = repr(exc)
        break
    a.close()
    b.close()
    made += 1
netstat = subprocess.run(["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, check=True).stdout
time_wait = sum("TIME_WAIT" in line for line in netstat.splitlines())
print(f"DIAG975 SONDA | par {made} w {time.monotonic() - start:.1f} s | błąd {error} | TIME_WAIT {time_wait}")
