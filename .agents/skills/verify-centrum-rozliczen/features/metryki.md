# Metryki

Metryki show the history of every Uruchomienie procesu of the three processes
(Przebieg rozliczeń, Przygotowanie pliku zbiorczego, Uporządkowanie INTERMAX),
including those started outside Centrum (the former `.cmd` launchers, Maks's
tools), read from the metrics files of the processes on every request:
P50/P95 per process and mode from five completed observations, the result
distribution, a stage-times chart, the interrupted runs with their phase times,
and a sortable, filterable history table, whose rows of a Centrum Uruchomienie
with a run id carry `Napisz do Maksa o tym Uruchomieniu` (`uwaga-taty.md`). Okresy shows three key numbers above
the Tablica okresów. Records the metrics reader skips are skipped here too, and
no metrics files mean an empty state, not an error.

## Sub-features

- `metryki-karty-okresow`: Okresy shows the last prepared period, the last Uruchomienie procesu with its result, and the results of the last 8 weeks, matching `/api/periods` and `/api/metrics`.
- `metryki-karty-okresow-bez-odczytu`: when `/api/metrics` fails, the card `Ostatnie tygodnie` names no number of weeks (only the server knows it, `recent.weeks`) and shows `nie udało się odczytać`; the next read brings the number back.
- `metryki-p50-p95`: the `Statystyki` strip shows the server's P50/P95 and result counts for Przygotowanie RUN.
- `metryki-wykres`: the stage-times chart, drawn by Centrum (no chart library), has one bar per shown run of every Proces and Tryb, one segment per phase that lasted, `✕` at the date of a stop, and a legend of the measured phases.
- `metryki-wykres-waski`: in a phone-sized window the bars get narrower than 28 px instead of overlapping (like recharts' `maxBarSize`).
- `metryki-wykres-szczegoly`: a bar's details (date, period, `zatrzymano`, phase times) open on hover, on a finger tap, and on keyboard focus, and close when the mouse leaves, on a tap beside the chart, and on Escape, in both themes.
- `metryki-tabela-etapow`: the `Tabela` tab lists each run's phase times with P50/P95 rows per phase.
- `metryki-za-malo-obserwacji`: below five completed observations (Przygotowanie DRY-RUN), P50/P95 show `–` and `od 5 ukończonych (jest N)`.
- `metryki-przerwane`: an interrupted run shows its phase times until the interruption.
- `metryki-historia`: the history lists the runs of every process newest first, marks DRY-RUN with the eye icon and runs from outside Centrum with `.cmd`, sorts by `Czas`, filters by process, and shows older runs on demand.
- `metryki-rodzaj-zatrzymania`: a stop „dla taty” and an old stop without a kind (metrics schema 1) have a calm outlined `Zatrzymano` badge; a stop „do Maksa” has a red `Błąd`.
- `metryki-nowy-rekord-spoza-centrum`: a record that the machine script (`tools/uruchom_proces.py`) appends appears after a reload, without restarting Centrum.
- `metryki-pusty-stan`: with no metrics files the API returns an empty list and the page shows `Jeszcze nie ma metryk`.

## How to get to it (user POV)

- Sidebar `Metryki` (`#/metryki`).
- Sidebar `Okresy` (`#/okresy`): the `Najważniejsze liczby` strip between `Następny krok` and `Tablica okresów`, once the folder okresów is set.
- Returning to the tab or reloading it reads the metrics files again.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`; the doctor also confirms the server reads this run's metrics files (`<root>/metrics/`), not Dad's history next to the tool. If the folder okresów is not set yet, the drive sets it through `Wskaż folder okresów` (see `ustawienia.md`).
- The fixture's history is in metrics schema 2: completed runs have `stop: null`, and the two Przebieg rozliczeń stops of `2026-09-17T15:40Z` („do Maksa”, `BLAD_NIEOCZEKIWANY`) and `2026-10-01T15:40Z` („dla taty”, `PLIK_ZBIORCZY_OTWARTY`) carry their `stop`. The Przygotowanie stop of `2026-08-25` is an old schema 1 record without a kind, as Dad's older records are.
- `fixture.json` → `metrics` names both files, the number of valid records (`runs`), the oldest record, and the interrupted run's period and measured phase times. The Przygotowanie file also holds a record with Przebieg rozliczeń counters, and the Przebieg file ends with a torn line; both must be skipped.
- The browser context uses the time zone `Europe/Warsaw`, so dates read as on Dad's computer (`06.10.2026, 08:21` for `06:21Z`).

- **Karty na Okresach.** Open `#/okresy`. `GET /api/metrics` (`api/metryki.json`) has `fixture.metrics.runs` runs of both processes. Group `Najważniejsze liczby` → group `Ostatni przygotowany okres` shows the newest token whose `files` in `/api/periods` has an existing `collective_file`; group `Ostatnie uruchomienie` shows `OK` and `<process_label> · <date>` of `runs[0]`; group `Ostatnie 8 tygodni` shows `<ok> OK` and `<needs_review> do sprawdzenia · <stopped> zatrzymane · <failed> błąd|błędy|błędów` from `recent`.
- **Karty bez odczytu.** Abort `**/api/metrics` with `page.route` and reload: group `Ostatnie tygodnie` (exact) shows `nie udało się odczytać`, and no card names a number of weeks (screenshot `2c`). Remove the route and reload: group `Ostatnie <recent.weeks> tygodni` is back. Before #1098 the failed card read `Ostatnie 8 tygodni`, a number the browser made up.
- **P50/P95.** Click link `Metryki`. Group `Statystyki` → groups `P50`, `P95`, `Wyniki` show the server's `statistics` for (`preparation`, `RUN`), durations as tenths of a second rounded half up (`7250` → `7,3 s`).
- **Wykres.** For each Proces (`Przebieg`, `Przygotowanie`) and Tryb (`DRY-RUN`, `RUN`) in the header groups, figure `Wykres czasów etapów` has one `button` per shown run (the newest 12 of that process and mode, oldest on the left), each named with its details (`06.10.2026, 08:21 · okres 29_05_10_2026. Sprawdzanie 0,4 s, Odczyt danych 7,6 s, …`, `· zatrzymano` after the period of a stop, `· błąd` for a stop „do Maksa”) and holding one segment (`[data-phase]`) per phase that lasted, 28 px wide at 1440 px; the dates of stops end in `✕`; the list `Etapy` names the phases that lasted in at least one shown run (a DRY-RUN has no `Zapisywanie`). The drive ends on Przygotowanie RUN.
- **Wąski wykres.** In a second context at 320×640 (the smallest phone; at 390 px the fixture's seven bars still fit at 28 px), open `#/metryki`, choose `Przygotowanie` and `RUN`: every bar's segments are narrower than 28 px and each bar ends before the next one starts (left and right edges of the `[data-phase]` segments); capture `2a`. Before #164 every bar was 28 px wide, more than its 24 px share there, so neighbours overlapped.
- **Szczegóły słupka.** The page is dark. Hover the stop's bar: `tooltip` shows the date, `okres <token> · zatrzymano`, and every measured phase with its time; moving the mouse away and Escape remove it. In a second context with `has_touch=True`, `tap()` the newest bar, then the stop's bar: the `tooltip` follows; tapping heading `Metryki` removes it. With the keyboard: click tab `Wykres`, press Tab until the newest bar is focused (its details show), ArrowLeft focuses the previous bar with its details, Escape closes them and keeps the focus. In the light theme the stop's bar shows the same details; the drive switches back to dark.
- **Tabela.** Click tab `Tabela`. Table `Czasy etapów` has a header, one row per shown run, and rows `P50`/`P95` whose cells match `percentiles` and `percentiles.phases`.
- **Za mało obserwacji.** In group `Tryb` click `DRY-RUN`. Group `P50` shows `od 5 ukończonych (jest 3)`; the API has `percentiles: null` and `completed_runs: 3`.
- **Przerwane.** Region `Przerwane` contains the interrupted period and `Sprawdzanie 0,4 s · Odczyt danych 1,3 s` plus `do przerwania 1,7 s`.
- **Historia.** Table `Historia Uruchomień procesu` shows 10 rows, newest first; the screen-reader text `DRY-RUN` appears once per DRY-RUN row and `.cmd` once per row. Click button `Czas`: the longest run is first and the column header has `aria-sort="descending"`. In group `Proces w historii` click `Przebieg`: only `Przebieg rozliczeń` rows. Click `Wszystkie`, then `Pokaż starsze`: up to 20 rows.
- **Rodzaj Zatrzymania.** With every row shown, each `BLAD_KRYTYCZNY` run of `/api/metrics` has its badge in its history row: `stop_kind: for_maks` is `Błąd` with `data-variant="destructive"`, `for_tata` and `null` (the old record) are `Zatrzymano` with `data-variant="outline"`. The fixture holds all three (screenshot `2b`).
- **Nowy rekord spoza Centrum.** Run `tools/uruchom_proces.py preparation --register <root>/brak-rejestru.xlsx --periods-directory <INEA> --period 06_12_10_2026 --dry-run --metrics <fixture.metrics.preparation>`; it exits `1` with stop code `BRAK_REJESTRU` and `metrics_saved: true` in its JSON, after appending a `BLAD_KRYTYCZNY` record whose `stop` is `{"kind": "for_tata", "code": "BRAK_REJESTRU"}`, with no Komunikat text. `/api/metrics` (`api/metryki-spoza-centrum.json`) has one more run; after a reload the first history row shows `06_12_10_2026`, an outlined `Zatrzymano` and `.cmd` (screenshot `26`).
- **Pusty stan.** Rename both metrics files; `/api/metrics` returns `runs: []` (`api/metryki-brak-plikow.json`) and the page shows `Jeszcze nie ma metryk`. The drive renames them back.
- **Proof.** Screenshots `20`–`29`, `2a`, `2b` and `2c` (`2a`: the narrow chart; `2c`: the cards after a failed read of the metrics; `2b`: the whole history with every kind of stop; `28`: details after a tap, dark; `29`: details on hover, light), `api/metryki*.json`.

## Gotchas

- Statistics are per process and mode. A `BLAD_KRYTYCZNY` record is not a completed observation, but `WYMAGA_SPRAWDZENIA` is. The counts split `BLAD_KRYTYCZNY` into `stopped` („dla taty” and old records without a kind) and `failed` („do Maksa”).
- The filters offer `INTERMAX` too, and for it `Tryb` has only RUN, because the server gives each process its modes (`app.py`, `GET /api/metrics`). The drive never selects `INTERMAX`: `uporzadkowanie-intermax` runs after this feature.
- The header filter (`Proces`, `Tryb`) drives the strip and the chart only; the history card has its own filters (`Proces w historii`, `Tryb w historii`). Filter and sort state is lost on reload.
- Every fixture run is marked `.cmd`: the metrics schema has no origin field, so Centrum takes `origin` from its own `centrum-uruchomienia.jsonl`, and Metryki runs before any feature that starts an Uruchomienie procesu from Centrum. Runs Centrum started carry `origin: centrum`, their `run_id` from the same file (`null` for `.cmd` runs and Centrum lines from before Uwagi taty) and no badge; only a row with a `run_id` has the button `Napisz do Maksa o tym Uruchomieniu` in the last column (header `Uwaga`, for screen readers only), so Metryki never shows it and `uwaga-taty` drives it. So `--feature metryki` on a run root where they already ran fails the `.cmd` count.
- The step outside Centrum writes a record with the real current time, so it is the newest run; it uses the run-local metrics file, never the tool's.
- Bars and details render without animation; a capture right after a filter click is still stable.
- `tap()` needs a context with `has_touch=True`; the drive's own context has none, so the tap runs in a second context on the same Centrum.
- The details are one `tooltip` for the whole chart; every bar's accessible name already carries them, so a screen reader reads them on focus.
