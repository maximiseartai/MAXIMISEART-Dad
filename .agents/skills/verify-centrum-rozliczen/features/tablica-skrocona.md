# Tablica skrócona

Tablica okresów shows at once the five newest periods that have started: the current period (the one containing
Dad's today) and the 4 before it. `Pokaż wszystkie` below the table adds the older ones until the page is reloaded.
Periods that have not started yet, the empty future weeks Dad creates ahead, never show, also after `Pokaż
wszystkie`. With five or fewer started periods the button is absent. The server decides where each period goes
(`board_place` in `/api/periods`: `recent`, `older`, `not_started`); the browser only shows it. A folder whose name
is not a period token is no Folder okresu and never reaches the board.

## Sub-features

Printed by `scripts/sub_features.py --feature tablica-skrocona` from the drive's steps and checks; refresh the section with it.

- `tablica-skrocona-biezacy-i-4-poprzednie`: the server places the current period and the 4 before it at once, older ones after Pokaż wszystkie, and periods that have not started nowhere; the board shows 13_19_10_2026 on top and the 4 periods before it, with Pokaż wszystkie below.
- `tablica-skrocona-pokaz-wszystkie`: Pokaż wszystkie adds the older periods below; periods that have not started stay hidden.
- `tablica-skrocona-po-przeladowaniu`: after a reload the board is short again.
- `tablica-skrocona-piec-zaczetych`: with five started periods and two not started the board has no Pokaż wszystkie; the board is the fixture's again for the next features.

## How to get to it (user POV)

Dad sees the board on `Okresy`, the start page of Centrum (`#/okresy`), once his folder okresów is set in Ustawienia.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature tablica-skrocona`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP tablica-skrocona` in `drive.txt`, screenshots `297`–`299` and `api/tablica-skrocona.json`.

## Gotchas

None known that the drive does not handle.
