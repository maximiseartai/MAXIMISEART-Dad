# Centrum rozliczeń na Windowsie: verification map

This directory is the maintained source for verifying what Dad does with Centrum on his Windows computer outside
the tab: install it, start it from the desktop, answer Windows' own windows, and update it. Read these conventions
before driving, then use the feature's own file as the recipe: the feature `<feature>` of `--feature` lives in
`<feature>.md` next to this file, driven by the skill's `scripts/windows_drive/<feature>.py`, whose module name has
`_` for `-`. Screens inside the tab belong to `verify-centrum-rozliczen`; add a feature here only when Windows itself
is part of the behaviour.

## Baseline preconditions

- A Windows machine with nothing on port `47811` and a Python that has `pythonw.exe` beside it (GitHub's
  `windows-latest` with `actions/setup-python` in the workflow).
- `run_windows_verification.py` created a fresh run root with `windows_tool.prepare`: `dane/` (folder okresów `INEA`
  with `29_05_10_2026`, `22_28_09_2026`, `15_21_09_2026` and `Archiwum`; the last complete period `06_12_10_2026`
  has no folder yet; Rejestr zleceń `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`; Dad's `config/` with the Lista
  Wykonawców and three Wzorce), the origin `origin.git` with the only Wydanie `v0.1.0` on `first` and `main` on
  `newest`, and `windows.json`.
- The drive's environment carries `windows_tool.boundaries` (browser recorder, GitHub address rewritten to the
  origin); Centrum inherits it through the shortcut.
- No settings file exists before `wskazanie-folderow`.

## Driving conventions

- Start Centrum only with the run's shortcut (`windows_desktop.start_shortcut`), never with `python run_centrum.py`.
- Find native windows by class and exact title, and require that Centrum's own process (the port owner) owns a
  picker; never click by coordinates.
- Find tab elements by ARIA role and exact Polish accessible name, as in `verify-centrum-rozliczen`.
- Change GitHub's newest Wydanie only with `windows_tool.release`, and put it back to `newest` when a feature ends.

## Proof and skip reporting

- Every step records the action, the tab (`screenshots/`) or the desktop (`pulpit/`), and the effect: process facts,
  the Centrum log, Dad's settings, the clone.
- Report a feature as verified only when the verdict lists it under `features=`; `przygotowanie=` is not proof of a
  feature, and a feature left out is a skip.
- `VERIFY FAIL` keeps `zz-failure.png` of the tab and the desktop and every step before the failure.
- Evidence holds synthetic paths only.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible behaviour, then exactly these H2s in
order: `Sub-features` (IDs matching `STEP <feature> | <id>` in `drive.txt`), `How to get to it (user POV)`,
`Driving it with the Windows harness` (starting with `Preconditions:`), and `Gotchas`. A new feature adds its file
here, its module in `scripts/windows_drive/`, its entry in `windows_drive.FEATURES` and `PREREQUISITES` and in
`run_windows_verification._drive`, in the same PR. This file lists no features: `tests/test_mapy_funkcji.py`
matches the feature files with `windows_drive.FEATURES` and the modules of `scripts/windows_drive/` in both
directions.
