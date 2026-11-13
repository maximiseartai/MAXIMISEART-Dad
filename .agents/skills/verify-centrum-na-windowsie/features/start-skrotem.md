# Start skrótem

Dad double-clicks „Centrum rozliczeń” on his desktop. Centrum starts on `http://127.0.0.1:47811/` as the tool's
`pythonw.exe`, without a console window, and opens the tab in his browser. A second double click, while it runs,
only opens the tab again: one Centrum, no window, `juz-dziala` in the Centrum log.

## Sub-features

- `start`: `health` answers within 60 s as `centrum-rozliczen` on the tool's commit (`versions.first[:7]`); the port owner is `pythonw.exe` beside the drive's Python, running `<tool>\run_centrum.py`, with no visible window and no `conhost.exe` child; the browser recorder got exactly `http://127.0.0.1:47811/`; the log has one `start port=47811 … konsola=nie`.
- `karta`: the tab shows heading `Okresy` and link `Ustaw w Ustawieniach` to `#/ustawienia/foldery` (first start, no settings); the gear opens Ustawienia, whose section Narzędzie has list item `Wersja narzędzia` with `<first[:7]>` (the row also shows the version's date and the freshness from the real GitHub API, which this feature does not check); Esc leaves Okresy.
- `drugie-klikniecie`: a second double click adds the same address to the recorder, the log gains `juz-dziala`, no `Centrum rozliczeń` message box appears, the first process still holds the port, and the second start ends within 15 s.

## How to get to it (user POV)

- Double-click the desktop shortcut „Centrum rozliczeń”; double-click it again while Centrum runs.

## Driving it with the Windows harness

Preconditions:

- `instalacja` ran; nothing listens on `47811`.

- **Start.** `windows_desktop.start_shortcut(.lnk)`. Poll `GET /api/health` (`api/health-start.json`). Read the port owner (`Get-NetTCPConnection`) and its `Win32_Process` row (`state/proces-start.json`). Check the windows and children of that pid, the recorder file and the log as in the sub-feature.
- **Tab.** Playwright opens the URL; heading `Okresy` (exact) is visible and link `Ustaw w Ustawieniach` (exact) has `href` `#/ustawienia/foldery`; capture `pierwszy-start`. Click link `Ustawienia` (exact), then link `Narzędzie` (exact) in dialog `Ustawienia` (heading `Ustawienia/Narzędzie`); list item `Wersja narzędzia` in `[data-slot=settings-section]` contains `<first[:7]>`; capture `ustawienia-wersja`; Esc: the dialog is gone and heading `Okresy` is visible.
- **Second double click.** `start_shortcut` again; within 30 s the recorder holds the URL twice; within 15 s the log after the click has `juz-dziala`; after 3 s no `Centrum rozliczeń` message box; the port owner's pid is unchanged; within 15 s no other process runs `<tool>\run_centrum.py`.
- **Doctor.** The runner then writes `doctor-start-skrotem.txt`, which must be `DOCTOR OK`.
- **Proof.** `screenshots/` and `pulpit/` `pierwszy-start`, `ustawienia-wersja`, `api/health-start.json`, `state/proces-start.json`, `state/otwarte-adresy.txt`.

## Gotchas

- `os.startfile` on the `.lnk` makes the shell start its target in the drive's environment; that is how `BROWSER` reaches Centrum. Starting `pythonw.exe` by hand would skip the shortcut, which is the point of this feature.
- The recorder is Dad's browser for this run: Windows' default browser is never opened, so this proves the address, not that Edge or Chrome shows it.
