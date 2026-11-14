# Start i zamykanie Centrum

Dad starts Centrum from the desktop shortcut; a second click only opens the tab
of the Centrum already running, and a port held by another program gives a
three-part start message instead of a second server. Tabs gathered from many
clicks keep working: a tab in the background gives back its connection to
Centrum (the browser allows 6 for all tabs together) and reconnects when it
comes to the front. Closing a browser tab leaves Centrum running; Dad stops the
server only with `Zamknij Centrum rozliczeń` in the sidebar, which asks first
and leaves a page saying `Centrum rozliczeń jest zamknięte` (an Aktualizacja
narzędzia also closes it, `aktualizacja.md`). During an Uruchomienie procesu or an
update the server refuses to close (409) and the tab shows the notification
`Nie zamknięto Centrum rozliczeń` with the reason; the drives of
`przygotowanie-pliku-zbiorczego`, `przebieg-rozliczen` and `aktualizacja` check
the refusal at the API only. Every start, recognised second start, start failure, shutdown and
stop leaves a safe line in the Centrum log (`logs/centrum-rozliczen.log`).

## Sub-features

Printed by `scripts/sub_features.py --feature start-i-zamykanie` from the drive's steps and checks; refresh the section with it.

- `start-gotowosc`: health names Centrum rozliczeń, the tool's commit it runs, and this start; the Centrum log starts with a start entry; the start entry names the port.
- `start-druga-instancja`: a second launch on the same port exits 0; it says Centrum is already running; it only opens the tab; its log records the recognised running Centrum; the first Centrum keeps serving.
- `start-obcy-program`: a launch on a port held by another program exits 1; the console shows the three-part start message; no exception text, only the message; the log records the start failure.
- `karty-w-tle`: in the background the drive's tab gives its stream back (tabs hidden by the harness); each of … more tabs shows Uruchomienia from the API and the stream; back in front, the drive's tab connects to the stream again.
- `zamykanie-karta`: closing a tab leaves Centrum running.
- `zamykanie-potwierdzenie`: Anuluj leaves Centrum running.
- `zamykanie`.

## How to get to it (user POV)

Dad clicks the desktop shortcut „Centrum rozliczeń” to start Centrum or to open its tab again, and stops it with
`Zamknij Centrum rozliczeń` in the sidebar's footer, on every page.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature start-i-zamykanie`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP start-i-zamykanie` in `drive.txt`, screenshots `90`–`92`, `api/start-health.json`, `api/start-*.txt` and
`state/centrum-rozliczen.log`.

## Gotchas

- The drive runs the console path of the launcher. The shortcut's path (`pythonw`, no console, start messages in a
  native dialog Playwright cannot click) is `tests/test_centrum_launcher.py` and `verify-centrum-na-windowsie`, and a
  Centrum of another version on the port (`INNA_WERSJA_CENTRUM`) is not driven.
