# Start i zamykanie Centrum

Dad starts Centrum from the desktop shortcut; a second click only opens the tab
of the Centrum already running, and a port held by another program gives a
three-part start message instead of a second server. Tabs gathered from many
clicks keep working: a tab in the background gives back its connection to
Centrum (the browser allows 6 for all tabs together) and reconnects when it
comes to the front. Closing a browser tab leaves Centrum running; Dad stops the
server only with `Zamknij Centrum rozliczeń` in the sidebar (an Aktualizacja
narzędzia also closes it, `aktualizacja.md`). During an Uruchomienie procesu or an
update the server refuses to close (409) and the tab shows the notification
`Nie zamknięto Centrum rozliczeń` with the reason; the drives of
`przygotowanie-pliku-zbiorczego`, `przebieg-rozliczen` and `aktualizacja` check
the refusal at the API only. Every start, recognised second start, start failure, shutdown and
stop leaves a safe line in the Centrum log (`logs/centrum-rozliczen.log`).

## Sub-features

- `start-gotowosc`: the served Centrum answers `health` with its identity, the tool's commit it runs, and this start, and the Centrum log starts with a `start` line naming the port.
- `start-druga-instancja`: the real launcher on the same port says `Centrum rozliczeń już działa`, opens only the tab, logs `juz-dziala`, and the first Centrum keeps serving.
- `start-obcy-program`: the real launcher on a port held by another program exits 1 with the three-part message and logs `blad-startu`.
- `karty-w-tle`: a tab in the background closes its event stream; with 7 more tabs (more than the browser's 6 connections to one address) each new tab still shows Uruchomienia, and the first tab reconnects when it comes back to the front.
- `zamykanie-karta`: closing a tab does not stop Centrum.
- `zamykanie-potwierdzenie`: `Zamknij Centrum rozliczeń` asks `Zamknąć Centrum rozliczeń?`; `Anuluj` leaves Centrum running.
- `zamykanie`: `Zamknij Centrum` shows `Centrum rozliczeń jest zamknięte`, the server process stops, and the log ends with `zamkniecie`, `stop`.

## How to get to it (user POV)

- The desktop shortcut „Centrum rozliczeń” (created by `py -3 install_centrum_shortcut.py`) starts Centrum without a console; clicking it again opens the tab. When a Centrum of another version holds the port, the click opens its tab and still exits 1 with `INNA_WERSJA_CENTRUM` (not driven).
- The sidebar footer button `Zamknij Centrum rozliczeń`, on every page.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. This feature closes it, so it runs last in `all`; nothing can be driven after it.
- The launcher steps copy the tool into `<root>/narzedzie` so the real launcher's log stays in the run root. The copy's `.git/HEAD` names the served Centrum's commit (the tool clone's `HEAD`, or `<root>/github/tool-commit.txt` when a feature pinned one), so it is the same version. The steps set `BROWSER` to a recorder that appends to `<root>/browser.txt`.

- **Readiness.** `GET /api/health` (`api/start-health.json`) has exactly `service` `centrum-rozliczen`, the served Centrum's commit shortened to 7 characters, and a non-empty `instance`; `<root>/logs/centrum-rozliczen.log` starts with `start … port=<port>`.
- **Second start.** Run `<root>/narzedzie/run_centrum.py --port <port>`. It exits 0, prints `Centrum rozliczeń już działa: <url>` (`api/start-druga-instancja.txt`), `browser.txt` holds exactly the URL, the copy's log holds `juz-dziala`, and `health` still answers.
- **Foreign program.** Bind a socket on a free port, then run the launcher on it. It exits 1, prints the lines `Co się stało`, `Gdzie`, `Co zrobić` with `zajmuje inny program`, nothing on stderr (`api/start-obcy-program.txt`), and the copy's log ends with `blad-startu`.
- **Tabs in the background.** The drive's tab opens `#/uruchomienia` and waits until heading `Uruchomienia` shows and the skeleton `Wczytywanie Uruchomień` is gone, which needs both the run setup (API) and the current Uruchomienie (stream). The harness sends it to the background (`document.visibilityState` `hidden` and a `visibilitychange` event, as the browser does for a tab left behind); its `/api/runs/events` request fails with `net::ERR_ABORTED`. Seven times: open a new tab (`context.new_page()`) on `#/uruchomienia` and wait up to 5 s for the same, then send it to the background before the next one. Capture `90` (the seventh tab). Bring the drive's tab back to the front: its new `/api/runs/events` request answers `200`. Close the seven tabs.
- **Tab close.** Open the URL in a second tab (`context.new_page()`), wait for heading `Okresy`, close it; `health` still answers.
- **Confirmation.** Click button `Zamknij Centrum rozliczeń` (exact). Alert dialog `Zamknąć Centrum rozliczeń?` shows `Wrócisz skrótem „Centrum rozliczeń” na pulpicie.`; capture `91`. Click `Anuluj`; the dialog closes and the log has no new `zamkniecie` (in `all`, aktualizacja already logged one).
- **Close.** Click `Zamknij Centrum rozliczeń`, then `Zamknij Centrum`. Heading `Centrum rozliczeń jest zamknięte` appears, `health` stops answering, the log ends with `zamkniecie`, `stop`; capture `92`.
- **Proof.** Screenshots `90`–`92`, `api/start-health.json`, `api/start-*.txt`, `state/centrum-rozliczen.log`. The copy's log under `<root>/narzedzie` goes with the run root.

## Gotchas

- Run this feature last: after `zamykanie` the server is gone, and cleanup reports `recorded server already stopped`, which is expected.
- `--feature start-i-zamykanie` alone works on a fresh run; no settings are needed.
- The shortcut path (`pythonw`, no console) shows start messages in a native dialog that Playwright cannot click. This skill drives the console path of the same launcher; the windowless path is covered by `tests/test_centrum_launcher.py` (a simulated `pythonw` on macOS/Linux, the real `pythonw.exe` and the `.lnk` on Windows) and end to end on Windows, with the native window, by `verify-centrum-na-windowsie`.
- The foreign-program step waits up to 5 seconds: the launcher gives a program that accepts the connection but never answers `health` that long before deciding it is not Centrum.
- Headless Chromium reports every tab as `visible`, so without the harness's visibility switch every tab keeps its stream and the seventh tab never loads; that is the bug this step guards against, not a harness fault. A real browser hides background tabs and the tabs of a minimised window; 6 or more Centrum tabs visible at once (separate windows side by side) would still exhaust the connections.
- Name the buttons exactly: `Zamknij Centrum rozliczeń` (sidebar) and `Zamknij Centrum` (dialog) differ only by the last word.
