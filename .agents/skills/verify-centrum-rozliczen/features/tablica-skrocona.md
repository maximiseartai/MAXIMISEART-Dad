# Tablica skrócona

Tablica okresów shows at once the five newest periods that have started: the current period (the one containing
Dad's today) and the 4 before it. `Pokaż wszystkie` below the table adds the older ones until the page is reloaded.
Periods that have not started yet, the empty future weeks Dad creates ahead, never show, also after `Pokaż
wszystkie`. With five or fewer started periods the button is absent. The server decides where each period goes
(`board_place` in `/api/periods`: `recent`, `older`, `not_started`); the browser only shows it. A folder whose name
is not a period token is no Folder okresu and never reaches the board.

## Sub-features

- `tablica-skrocona-biezacy-i-4-poprzednie`: with seven started and two future periods, `/api/periods` places them as `recent`, `older` and `not_started`, and the table shows the five `recent` ones with `Pokaż wszystkie` below.
- `tablica-skrocona-pokaz-wszystkie`: the button adds the two older periods and disappears; the future ones stay hidden.
- `tablica-skrocona-po-przeladowaniu`: a reload shows the short board with the button again.
- `tablica-skrocona-piec-zaczetych`: with five started and two future periods the board has no button.

## How to get to it (user POV)

- Sidebar `Okresy` (the start page, `#/okresy`), once the folder okresów is set.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`; the fixture's "today" is Monday `2026-10-19`. If the folder okresów is not set yet, the drive sets it through `Wskaż folder okresów`. It passes right after the fixture or after `tablica-okresow`, which leaves the same period folders.

- **Short board.** Create the empty Folders okresu `27_02_11_2026` and `20_26_10_2026` (not started), `13_19_10_2026` (current), `08_14_09_2026` and `01_07_09_2026` (older) in `INEA`, then reload. `GET /api/periods` (`api/tablica-skrocona.json`) gives, newest first, the two future periods `not_started`, `13_19_10_2026`, `06_12_10_2026`, `29_05_10_2026`, `22_28_09_2026`, `15_21_09_2026` `recent`, and the two older `older`. Table `Tablica okresów` shows exactly the five `recent` rows in that order and button `Pokaż wszystkie`; capture `297`.
- **Show all.** Click `Pokaż wszystkie`: the table shows the seven started periods, the future ones are absent, and the button is gone; capture `298`.
- **Reload.** Reload: the five rows and the button are back.
- **Five started.** Remove the two older folders and reload: five rows, no button; capture `299`. Remove the rest; after a reload the table shows the fixture's board.
- **Proof.** Screenshots `297`–`299`, `api/tablica-skrocona.json`.

## Gotchas

- The folders are removed in `finally`, so a failed run leaves the fixture's board for whatever runs next.
- Counting is by rows the server lists: the last complete period `06_12_10_2026` has no Folder okresu and still counts.
- The fixture's "today" is a Monday, so `20_26_10_2026` starts the next day and is `not_started`; the Tuesday boundary itself is tested in `tests/test_centrum_rozliczen.py`.
