# Wydajność

Measures how fast Centrum rozliczeń feels on Dad's laptop and compares it with
the baseline in `wydajnosc-baseline.json`: cold start of three pages of the menu (Okresy, Uruchomienia, Metryki), reopening
the tab, two laps through the sidebar with the time a skeleton was visible, the
interactions Dad uses (theme in the section Wygląd of Ustawienia, Metryki filters, the Wykres/Tabela and
Uruchomienie/Historia tabs, collapsing the sidebar, returning to the tab), the
API requests of each scenario, the bundle size, and CPU traces of the cold start
of Okresy and Metryki. It is the hill-climbing loop for frontend changes: every
change that makes Centrum faster or slower updates the baseline in its own PR.
It runs only when named (`--feature wydajnosc`), never in `all`: it takes a few
minutes and holds the machine alone. Raporty (the fifth menu page, with no budget in the baseline yet,
`MEASURED_PAGES` in `drive/wydajnosc.py`), Powiadomienia (the header bell) and the dialog `Napisz do Maksa`
are not measured.
Every scenario runs in Chromium at CPU 4× (the reference profile of Dad's laptop) and 6× (the pessimistic
one), five times each by default.

## Sub-features

Printed by `scripts/sub_features.py --feature wydajnosc` from the drive's steps and checks; refresh the section with it.

- `wydajnosc-rok-pracy`: the Tablica okresów holds the year: … periods, … with Rozliczenia pracowników; Metryki read … records of the year.
- `wydajnosc-na-zywo`: the year's … has a Plik zbiorczy of … rows.
- `wydajnosc-pomiar`.
- `wydajnosc-porownanie`: every scenario is within its budget and sends the expected API requests.

## How to get to it (user POV)

Maks, not Dad, runs it by name (Windows: `py -3 .agents\skills\verify-centrum-rozliczen\scripts\run_centrum_verification.py --feature wydajnosc`).
`--baseline <file>` compares with another baseline (for example a deliberately broken one), and `--powtorzenia <n>`
changes the repetitions (fewer for a quick look, never for a baseline). The scenarios are Dad's own paths: opening
Centrum on a page, clicking through the sidebar, switching the theme, filtering Metryki, switching tabs, collapsing
the sidebar, returning to the browser tab.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wydajnosc`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP wydajnosc` in `drive.txt`, screenshots `84`–`86`, `api/wydajnosc-*.json`, `wydajnosc/raport.txt` and
`wydajnosc/raport.json` (every scenario and profile with median, baseline, budget and verdict, then the API requests,
the bundle, the CPU traces and the failures), `wydajnosc/baseline-kandydat.json` and the CPU traces
`wydajnosc/slad-*.json` (open them in Chrome DevTools → Performance).

## Gotchas

- The built frontend in `src/rozliczenia/centrum/static/` is the one under test: run `npm run build` in `frontend/`
  after a frontend change, or the measurement proves the old build.
- The multipliers 4× and 6× and the baseline hold for a Mac with M4 Max (`docs/agents/komputer-taty.md`); on another
  developer computer they do not apply.
- Noise: medians move about ±20 ms at 6× on a quiet machine. The second measurement absorbs a single noisy series
  without widening the margin, which would hide small regressions; a machine busy for the whole run (tests,
  benchmarks, another verification) can still fail both, so rerun on a quiet CPU before believing a failure on a
  change that does not touch that page.
- The measurement takes about five minutes with five repetitions; `--powtorzenia 1` is for a quick look or a
  deliberately broken expectation, as one sample is too noisy for a baseline.
- Update `wydajnosc-baseline.json` only in the PR whose change moves the numbers (a frontend change that makes Centrum
  faster, or a deliberate change in API requests), and only from a run with the default five repetitions on a quiet
  CPU: copy the candidate over it, review `git diff` (only the scenarios the change touches should move beyond the
  noise; keep `margines` unless the noise itself changed), and put the before/after medians in the PR description.
  Never update it to make a slower change pass.
- After a change to the comparison, copy the baseline, multiply every median by 10, break one expectation (one
  scenario's median to `100`, or one count in its `zapytania_api`), and run with `--baseline <copy> --powtorzenia 1`:
  `VERIFY FAIL` with exactly that scenario under `porażki` (`ponad budżet` or `inna liczba`).
- The browser's own measurement (`POST /api/view-timings`, `pomiar-u-taty.md`) counts among the API requests: one per
  ready view is expected, and a second one in a scenario means the view was measured twice.
- The local server answers in milliseconds; Dad's OneDrive does not. The measurement covers the browser, not
  OneDrive; server times at Dad's come from the Centrum log.
- A fresh run root starts dark (no theme saved): driving `drive_centrum.py --feature wydajnosc` by hand against a
  Centrum left in light fails its check of the dark start.
- Event stream: `GET /api/runs/events` stays open while the tab is visible (headless Chromium reports every tab as
  visible) and counts as one request of a cold start or reopened tab.
