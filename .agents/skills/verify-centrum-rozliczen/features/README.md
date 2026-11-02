# Centrum rozliczeń verification map

This directory is the maintained source for verifying what Dad can do in
Centrum rozliczeń. Read these conventions before driving, then use the
feature's own file as the recipe: the feature `<feature>` of `--feature` lives
in `<feature>.md` next to this file, driven by the skill's
`scripts/drive/<feature>.py`, whose module name has `_` for `-`.

## Baseline preconditions

- The built frontend in `src/rozliczenia/centrum/static/` matches `frontend/`
  (`npm run build` in `frontend/` after any frontend change).
- Playwright for Python and Chromium are installed, and on Windows `tzdata` (see `SKILL.md`, Launch).
- The computer may run in any time zone: a check of the screen counts dates in
  Dad's (`Europe/Warsaw`, the browser's), a check of the server's text in the computer's own.
- `run_centrum_verification.py` created a fresh run root with
  `create_centrum_fixture.py`, `serve_centrum.py` is serving it, and
  `centrum_doctor.py` reported `DOCTOR OK`.
- The fixture's "today" is Monday `2026-10-19`, so the last complete period is
  `06_12_10_2026`, whose Folder okresu does not exist. The folder okresów
  `INEA` holds `29_05_10_2026` (Plik zbiorczy przygotowany; its Plik zbiorczy
  has a Wykonawca missing from the konfiguracja wykonawców), `22_28_09_2026`
  (Rozliczenia pracowników gotowe, three files), `15_21_09_2026` (empty Folder
  okresu), and `Archiwum` (not a period).
- `<root>/Załączniki` holds Dad's layout for `uklad-folderow-taty`: weeks in
  `Rozliczenia 2026\{miesiąc}\INEA` of September, October, and November, with
  `06_12_10_2026` and `29_05_10_2026` prepared in October.
- `<root>/metrics/` holds both metrics files in the metrics schema: 18 valid
  synthetic Uruchomienia procesu (Przygotowanie pliku zbiorczego: 6 completed
  RUN, 1 RUN stopped in an old schema-1 record without its Rodzaj Zatrzymania,
  3 completed DRY-RUN; Przebieg rozliczeń: 5 completed RUN, one of them
  WYMAGA_SPRAWDZENIA, 1 RUN stopped „do Maksa” with `BLAD_NIEOCZEKIWANY`, 1 RUN
  stopped „dla taty” with `PLIK_ZBIORCZY_OTWARTY`, 1 DRY-RUN) and one record
  per file that the reader skips.
- The synthetic Rejestr zleceń has four orders in `06_12_10_2026`, the last on
  Saturday, so a RUN of Przygotowanie pliku zbiorczego asks about an
  incomplete period; its order cells carry the row marker.
  Centrum reads these, never the tool's own history.
- No settings are set when a run starts.
- Only for `wydajnosc`, the fixture is created with `--wariant rok-pracy`: `<root>/Rok pracy/Załączniki` holds 52 periods in Dad's layout and the metrics files hold a year of records (see `wydajnosc.md`).
- `<root>/aktualizacja/` holds the run's tool for `aktualizacja`: a clone (`klon`) on the first synthetic commit, with Dad's files in its `config/`, and a bare local "origin" (`origin.git`) one commit ahead that stops tracking his changed konfiguracja wykonawców, plus a branch `biblioteki` one commit later that needs a library pip cannot install offline and a branch `nie-startuje` whose Centrum does not start. Centrum's own commit is the clone's `HEAD`, and Aktualizacja narzędzia moves only this clone. The clone's `run_centrum.py` serves the run's scripted Centrum, so the Centrum the restart guardian starts after an update is again this run's.
- The run's `config/` holds a synthetic `worker_mapping.yaml` (three Wykonawcy)
  and the three Wzorce, valid for the engine's Sprawdzanie; Konfiguracja reads
  these, never Dad's `config/`.

## Driving conventions

- Drive through the browser with `drive_centrum.py`. Find elements by ARIA role
  and accessible name; the names are Polish UI text, so copy them exactly
  (`exact=True`: Playwright otherwise matches case-insensitive substrings, and
  `Wskaż folder okresów` differs from `Wskaż Folder okresów` only in case).
- Name a period in combobox `Okres` with `period_choice` (`drive/common.py`): its days from the token, its Status okresu, and the token, as in `wt 06.10 – pon 12.10 · ostatni pełny · 06_12_10_2026`.
- Answer a native picker by writing the path to `<root>/picker/answer.txt`
  before the click. Leave the file absent to cancel.
- Read side effects from the run root: `config/centrum-ustawienia.yaml`,
  `dialogs.jsonl`, `opened.jsonl`, and `logs/uruchomienia/`.
- Change files on disk only inside the run root, and restore what a step moved.
- Capture with `Run.capture`, which waits for running transitions; a screenshot
  taken mid-transition shows content at partial opacity. A close-up is
  `Run.capture` with `clip`, so its number is checked like every other one;
  `tests/test_limit_drive_centrum.py` fails on any other `screenshot`
  call in `drive/`.

## Proof and skip reporting

- Every step records its action, the screen (`screenshots/`, `aria/`), the
  server's answer (`api/`), and the side effect on disk (`state/`, checks in
  `drive.txt`).
- Report a feature as verified only when its steps ran in this run. A feature
  left out with `--feature` is a skip; report it as one.
- `VERIFY FAIL` keeps `screenshots/zz-failure.png` and the evidence of every
  step before the failure.
- Evidence contains synthetic paths only; workbook content never appears.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible
behaviour, then exactly these H2s in order:

1. `Sub-features`: short IDs with one line each; the IDs match the
   `STEP <feature> | <id>` lines in `drive.txt`.
2. `How to get to it (user POV)`: every entry point Dad has.
3. `Driving it with Playwright for Python`: starts with `Preconditions:`, then
   labelled bullets pairing each action with the exact handle and the
   observable result.
4. `Gotchas`: traps that waste or invalidate a run.

When a slice adds a feature, add its file in this directory, its module in
`scripts/drive/` and an entry in `drive_centrum.py`, and its screenshots in
`REQUIRED_SCREENSHOTS` of `run_centrum_verification.py`, in the same PR. This
file lists no features: `tests/test_mapy_funkcji.py` matches the feature files
with the features of `drive_centrum.py` in both directions.
