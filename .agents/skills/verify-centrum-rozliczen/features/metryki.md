# Metryki

Metryki show the history of every Uruchomienie procesu of the five processes of the catalog
(Przygotowanie pliku zbiorczego, Przebieg rozliczeń, Wycena w efenix, Uporządkowanie INTERMAX, Wpisanie raportów),
including those started outside Centrum (the former `.cmd` launchers, Maks's
tools), read from the metrics files of the processes on every request:
P50/P95 per process and mode from five completed observations, the result
distribution, a stage-times chart, the interrupted runs with their phase times,
and a sortable, filterable history table, whose rows carry the button of the Karta Uruchomienia
(`karta-z-logow.md`) and, for a Centrum Uruchomienie with a run id, `Napisz do Maksa o tym Uruchomieniu` (`uwaga-taty.md`). Okresy shows three key numbers above
the Tablica okresów. Records the metrics reader skips are skipped here too, and
no metrics files mean an empty state, not an error.

## Sub-features

Printed by `scripts/sub_features.py --feature metryki` from the drive's steps and checks; refresh the section with it.

- `metryki-karty-okresow`: the server reads every valid record of both metrics files; the history holds both processes, and the records the metrics reader skips are absent; Okresy shows the last prepared period, the last Uruchomienie procesu and the recent results.
- `metryki-karty-okresow-bez-odczytu`: a failed read of the metrics leaves „Ostatnie tygodnie” without a number and „nie udało się odczytać”; the next read of the metrics brings back „Ostatnie … tygodni”.
- `metryki-p50-p95`: Przygotowanie RUN has five completed observations, so P50/P95 exist; the strip shows the server's P50/P95 and result counts for Przygotowanie RUN.
- `metryki-wykres`: …: … bars oldest first, a segment per lasting phase, … marked ✕, legend …; the stage-times chart stacks the measured phases of each shown run for every Proces and Tryb; …: … bars …–… px wide (at most …), the smallest gap between them … px.
- `metryki-wykres-waski`: …: … bars …–… px wide (at most …), the smallest gap between them … px.
- `metryki-wykres-szczegoly`: hovering a bar opens its details with „zatrzymano”; leaving the chart and Escape close them; tapping a bar with a finger opens its details, tapping another switches, tapping beside closes; Tab reaches the newest bar with its details, arrows move between bars, Escape closes them; the bar details read the same in the light theme.
- `metryki-tabela-etapow`: the table view lists each run's phase times with per-phase P50/P95 from the server, … stops with their word.
- `metryki-za-malo-obserwacji`: Przygotowanie DRY-RUN has fewer than five completed observations; below five completed observations P50/P95 show a dash and the count.
- `metryki-przerwane`: an interrupted Uruchomienie procesu shows its phase times until the interruption; the fixture's interrupted runs have both tones; Przerwane: a red icon only for the stop „do Maksa”, a calm one for „dla taty” and the old record.
- `metryki-historia`: the history sorts by time, filters by process and shows older runs on demand.
- `metryki-rodzaj-zatrzymania`: the fixture has every kind of stop: …; Historia: „Zatrzymano” outlined for „dla taty” and the old record, „Błąd” red for „do Maksa”.
- `metryki-nowy-rekord-spoza-centrum`: the machine script stopped (no Rejestr zleceń) and wrote its metrics record; the record carries the Rodzaj Zatrzymania and the Komunikat code only: …; the next read includes the record from outside Centrum without restarting it; the reloaded page shows the DRY-RUN from outside Centrum as the newest Uruchomienie procesu.
- `metryki-pusty-stan`: no metrics files is an empty list.

## How to get to it (user POV)

- Sidebar `Metryki` (`#/metryki`).
- Sidebar `Uruchomienia` (`#/uruchomienia`), tab `Historia`: the same history card.
- Sidebar `Okresy` (`#/okresy`): the `Najważniejsze liczby` strip between `Następny krok` and `Tablica okresów`, once the folder okresów is set.
- Returning to the tab or reloading it reads the metrics files again.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature metryki`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/metryki*.json`.

## Gotchas

- Filter and sort state is lost on reload.
- Every fixture run is marked `.cmd`: the metrics schema has no origin field, so Centrum takes `origin` from its own
  `centrum-uruchomienia.jsonl`, and Metryki runs before any feature that starts an Uruchomienie procesu from Centrum.
  Runs Centrum started carry `origin: centrum`, their `run_id` from the same file (`null` for `.cmd` runs and Centrum
  lines from before Uwagi taty) and no badge; only a row with a `run_id` has the button `Napisz do Maksa o tym
  Uruchomieniu` in the last column (header `Karta Uruchomienia i Uwaga`, for screen readers only), so Metryki never
  shows it and `uwaga-taty` drives it. So `--feature metryki` on a run root where they already ran fails the `.cmd`
  count.
- Bars and details render without animation; a capture right after a filter click is still stable.
