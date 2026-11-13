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

## Sub-features

- `wydajnosc-rok-pracy`: Centrum points to Dad's year of work (52 periods in his layout, 51 with Rozliczenia pracowników of 14 Wykonawcy, about 260 extra metrics records) through the UI, and the four measured pages are captured.
- `wydajnosc-na-zywo`: the year's last period gets a synthetic Plik zbiorczy of Dad's size (430 rows), so the live summary of Uzupełnienie (#419) reads a real file.
- `wydajnosc-pomiar`: every scenario runs in Chromium at CPU 4× (reference) and 6× (pessimistic), five times each by default.
- `wydajnosc-porownanie`: the report gives each scenario's median, baseline and budget per profile and fails when a median exceeds its budget in the measurement and in the second measurement of that scenario, when a scenario's API requests differ from the expected ones, when a skeleton is visible in the second sidebar lap, or when the bundle exceeds its budget.

## How to get to it (user POV)

- Maks, not Dad: `py -3 .agents\skills\verify-centrum-rozliczen\scripts\run_centrum_verification.py --feature wydajnosc` (macOS: `.venv/bin/python …/run_centrum_verification.py --feature wydajnosc`).
- `--baseline <file>` compares with another baseline (e.g. a deliberately broken one); `--powtorzenia <n>` changes the repetitions (fewer for a quick look, never for a baseline).
- The scenarios are Dad's own paths: opening Centrum on a page, clicking through the sidebar, switching the theme, filtering Metryki, switching tabs, collapsing the sidebar, returning to the browser tab.

## Driving it with Playwright for Python

Preconditions:

- The runner creates the fixture with `--wariant rok-pracy`: on top of the usual fixture, `<root>/Rok pracy/Załączniki` holds 52 periods up to `06_12_10_2026` in `Rozliczenia {rok}\{miesiąc}\INEA`, and both metrics files hold 258 more records (Przygotowanie: preview and two RUNs per week; Przebieg rozliczeń: preview and RUN per week before the last). `fixture.json` → `year_of_work` names them.
- The built frontend in `src/rozliczenia/centrum/static/` is the one under test: run `npm run build` in `frontend/` after a frontend change, or the measurement proves the old build.
- Quiet CPU, held by the runner: it waits until no other Centrum verification run or `benchmark_przebiegu.py freeze` is registered and, on macOS and Linux, no pytest, other verification or Playwright browser runs, then takes the machine's measurement lock; `benchmark_przebiegu.py measure` takes the same lock and waits the same way. It prints `MASZYNA ZAJĘTA | …` every minute and `MASZYNA WOLNA | czekano N s` when it starts, and fails after 3 minutes with what kept the machine busy. Those runs do not wait while it waits for a quiet CPU; once it holds the lock they wait for it at most 15 minutes, three times a measurement, then fail with `zajmuje ją: pomiar (pid …)`. Load that starts during the measurement (a test run, editors, browsers) is not stopped and still adds noise.
- Profiles follow `docs/agents/komputer-taty.md`: `Emulation.setCPUThrottlingRate` 4× and 6× on a Mac with M4 Max. On another developer computer the multipliers and the baseline do not apply.

- **Rok pracy.** On the drive's tab, answer the picker with `year_of_work.periods_directory` and point it in Foldery of Ustawienia (`ensure_files_set`), then the fixture's Rejestr zleceń the same way. `/api/periods` (`api/wydajnosc-tablica.json`) holds at least 52 periods, 51 `worker_settlements_ready`; `/api/metrics` (`api/wydajnosc-metryki.json`) has `fixture.metrics.runs` runs. Screenshots `84`–`86` show the three measured pages on the year. The tab then goes to `about:blank`, so its event stream does not run during the measurement.
- **Ready view.** A view is ready when the `h1` in `[data-slot="sidebar-inset"]` is the page title and no `[data-slot="skeleton"]` or `[aria-busy="true"]` is in the page. A `MutationObserver` from an init script records the time of every change of that state and of the last DOM change.
- **Visible skeleton.** A skeleton is in the DOM from the first render but transparent until its animation starts about 120 ms into the read (`index.css`), and a skeleton the browser never painted never starts it. The init script counts a skeleton as visible from the first `animationstart` of a `[data-slot="skeleton"]` or `[aria-busy="true"]` element until no such element is left in the page. The browser's own measurement counts `szkielet_ms` the same way (`pomiar-u-taty.md`).
- **Scenarios** (each in a fresh context at 1440×1000, `pl-PL`, `Europe/Warsaw`, without HTTP or code cache unless stated):
  - `<strona>/zimny-start`: `#/<strona>` from navigation start to the ready view; details FCP, script time (`Performance.getMetrics`), long tasks.
  - `<strona>/ponowne-otwarcie` (Okresy, Metryki): a new tab in the same context, after two warm-up visits (V8 code cache).
  - `menu/<okrążenie>/<strona>`: from the click on the sidebar link to the ready view, laps Uruchomienia → Metryki → Okresy twice after a cold Okresy; `…/szkielet` is the time a skeleton was visible in between. In the second lap every page shows its last data at once (cache of the tab), so a visible skeleton there fails at once, in either profile, without a second measurement.
  - Interactions (`okresy/motyw-jasny`, `okresy/motyw-ciemny`: `Jasny` and `Ciemny` of group `Motyw` in Wygląd of Ustawienia opened over Okresy, the opening not measured; `metryki/proces-*`, `metryki/tryb-*`, `metryki/zakladka-tabela`, `metryki/zakladka-wykres`, `uruchomienia/zakladka-*`, `menu-boczne/zwin`, `menu-boczne/rozwin`): the longest Event Timing duration of the input (input to next paint, as INP). Below Event Timing's 16 ms threshold the value is 16.
  - Uzupełnienie na żywo (#419), on the summary of `06_12_10_2026` with its 430-row Plik zbiorczy: `uzupelnienie/pytanie-o-zapis` is the median duration of three checks of the saved version of an unchanged file (`GET …/collective-file-version`, request start to answer; detail `skrypt_ms`, the main thread's script time per check), and `uzupelnienie/zmiana-pliku` is the time from the answer of the check that saw Dad's save (the harness toggles O18 and replaces the whole file, like Excel) to the new counter on screen, which is the full read and the render (detail `odczyt_ms`, the duration of `GET …/quantities-to-fill`). The polling interval of 3 s (`frontend/src/lib/use-live-file.ts`) rests on these numbers; the PR of #419 explains them.
  - `<strona>/powrot-do-karty` (Okresy, Metryki): a `focus` event on the window, until the last API answer or DOM change it caused.
  - CPU traces: one DevTools trace of the cold start of Okresy and Metryki per profile (`wydajnosc/slad-<strona>-<n>x.json`, open in Chrome DevTools → Performance); the report sums the main thread's time per event kind.
- **API requests.** Every `/api/` request of the scenario's context (method and path) is counted per repetition, the event stream and writes included, and so are the background reads of the header (`GET /api/notifications` on every page change and return to the tab) and of the section `Narzędzie` of Ustawienia (`GET /api/tool-update`). Every repetition in both profiles must match the baseline's `zapytania_api` exactly; the cold start of Uruchomienia sends `GET /api/runs/setup` once (#167; it sent it twice before). The browser's own measurement (`POST /api/view-timings`, see `pomiar-u-taty.md`) counts too: one per ready view is part of the expected cost, and a second one in a scenario means the view was measured twice.
- **Budget.** `max(baseline × (1 + margines.wzgledny), baseline + margines.minimalny_ms)` per scenario and profile; the bundle (decoded JS and CSS of a cold start) may grow by `margines.bundle_wzgledny`. A scenario missing from the baseline, or a baseline scenario that was not measured, fails too.
- **Gate.** A median over budget does not fail at once: right after the measurement, the routine that produced it (that page's cold start or reopened tab, the menu laps, or the interactions) runs again with the same repetitions in that profile, and the scenario fails only if the second median is over budget too (`ok w ponownym pomiarze` otherwise, with the second median in brackets). Both profiles gate. Decision: on a machine with other load, medians at 6× drift a few percent over budget in one series and not the next (seen at 1–6% over), while a real regression stays over in both; a second measurement filters that noise without widening the margin, which would hide small regressions. API request counts and the bundle are deterministic and fail on the first difference.
- **Report.** `wydajnosc/raport.txt` lists every scenario and profile with median, baseline, budget and verdict (`ok`, `ponad budżet`, `brak w baseline`), the details in brackets, then the API requests per scenario (with the expected ones on a difference), the bundle, the CPU traces, and the failures. `wydajnosc/raport.json` holds the same plus every sample. `drive.txt` repeats the text report. `VERIFY OK` means no failure; `VERIFY FAIL | … drive returned 1` with `DRIVE FAIL | wydajnosc: N porażek` means read the failures at the end of `raport.txt`.
- **Proving the checks.** `centrum_self_test.py`, run after every verification, checks the gate on made-up numbers without a browser: a median within budget passes, a median over budget is measured again and passes only if the second median is within budget, and another number of API requests fails. After a change to the comparison, also copy the baseline, multiply every median by 10, then break one expectation (one scenario's median to `100`, or one count in its `zapytania_api`), and run with `--baseline <copy> --powtorzenia 1`: `VERIFY FAIL` with exactly that scenario under `porażki` (`ponad budżet` or `inna liczba`).
- **Updating the baseline.** Every run writes `wydajnosc/baseline-kandydat.json` in the baseline's format. Update the baseline only in the PR whose change moves the numbers (a frontend change that makes Centrum faster, or a deliberate change in API requests such as one `/api/runs/setup`), and only from a run with the default five repetitions on a quiet CPU: copy the candidate over `wydajnosc-baseline.json`, review `git diff` (only the scenarios the change touches should move beyond the noise; keep `margines` unless the noise itself changed), and put the before/after medians in the PR description. Never update it to make a slower change pass.
- **Proof.** Screenshots `84`–`86`, `api/wydajnosc-*.json`, `wydajnosc/raport.txt`, `wydajnosc/raport.json`, `wydajnosc/baseline-kandydat.json`, `wydajnosc/slad-*.json`.

## Gotchas

- Noise: medians move about ±20 ms at 6× on a quiet machine. The second measurement absorbs a single noisy series; a machine busy for the whole run (tests, benchmarks, another verification) can still fail both, so rerun on a quiet CPU before believing a failure on a change that does not touch that page.
- The measurement takes about five minutes with five repetitions; the runner allows the drive 30 minutes.
- `--powtorzenia 1` is for a quick look or a deliberately broken expectation; one sample is too noisy for a baseline.
- The local server answers in milliseconds; Dad's OneDrive does not. The measurement covers the browser, not OneDrive; server times at Dad's come from the Centrum log.
- The theme interaction switches to light and back; a fresh run root starts dark (no theme saved). Driving `drive_centrum.py --feature wydajnosc` by hand against a Centrum left in light fails its check of the dark start.
- Event stream: `GET /api/runs/events` stays open while the tab is visible (headless Chromium reports every tab as visible) and counts as one request of a cold start or reopened tab.
