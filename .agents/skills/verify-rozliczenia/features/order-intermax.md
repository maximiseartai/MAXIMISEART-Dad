# Uporządkowanie INTERMAX

The third process. Dad pastes one day of Surowe zlecenia from the company app
at the bottom of INTERMAX (the Rejestr zleceń) and starts Uporządkowanie
INTERMAX in Centrum rozliczeń; outside Centrum it runs as
`tools/uruchom_proces.py intermax`. It has no period and no preview without
saving: it saves a Kopia INTERMAX, then replaces INTERMAX with the pasted day
ordered.

## Sub-features

- `intermax-result` prints `OK` (exit `0`) with no warnings and no stop; `summary.figures` are `Zlecenia` 6 and `Wykonawcy` 3 (unit `count`), `summary.counts` is `Uporządkowany dzień` with `pon 26.10.2026` 6, `files` is empty and `worker_settlements` is `null`.
- `intermax-copy` names the Kopia INTERMAX in `summary.intermax_copy` (`INTERMAX przed uporządkowaniem RRRR-MM-DD GG-MM-SS.xlsx`); it is the only file in `--copies`, holds INTERMAX's bytes from before the run, and its moment lies between the fixture's creation and the check, in the computer's clock.
- `intermax-ordered` writes INTERMAX: the `NUMER ZL.` values below the last ordered day are the pasted day by Wykonawca alphabetically and, within one, from the earliest hour; columns `B:UWAGI` of the earlier days equal the Kopia INTERMAX.
- `intermax-progress` reports `Sprawdzanie`, `Odczyt danych`, `Planowanie` and `Zapisywanie` completed in order and no Szablony pracowników.
- `intermax-metrics` appends one completed `RUN` record, `OK`, in the Okres rozliczeniowy of the Kopia's day, with counters `orders` 6 and `workers` 3 and no row content or path.

## How to get to it (user POV)

- Dad starts it on the card „Uporządkuj INTERMAX” in Centrum rozliczeń, which takes INTERMAX from Ustawienia Centrum; `verify-centrum-rozliczen` drives that route.
- The machine script never reads Ustawienia Centrum: `py -3 tools\uruchom_proces.py intermax --register <INTERMAX> --copies <folder Kopii> --metrics <metrics>`. Without `--copies` it writes the Kopia INTERMAX to the tool's own folder of Kopie, so always pass one outside Dad's computer.

## Driving it with PowerShell and the machine script

Preconditions:

- The orchestrator builds the synthetic INTERMAX with `tools/lib/atrapy/intermax.py` (ordered days of 19 and 20.10.2026 in Calibri 8, Dad's yellow row, and six Surowe zlecenia of Monday 26.10.2026 for `anna.kowalska`, `bartek.zielinski` and `jan.nowak`, in the look from the app with the first row shifted two columns left and no two orders of one Wykonawca at the same hour) and an empty `Kopie INTERMAX` folder under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant intermax`. It runs `create_intermax_fixture.py`, `tools/uruchom_proces.py intermax`, `assert_intermax.py`, cleanup, and the self-test. Success prints `VERIFY OK | variant=intermax`.
- **Read the proof.** `run.json` holds the command, exit code `0` and the JSON result; `assert-run.txt` ends with `ASSERT OK | intermax=true | orders=6 | workers=3 | intermax_copy=before_run | ordered_by_worker_and_hour=true | earlier_days_unchanged=true | metrics_safe=true`. A failure names the check, never a row value.
- **Drive stops, the write under Excel and OneDrive, and the look.** The variant reaches none of them. The stops and the ordered look are in `tests/test_uporzadkowanie_intermax.py`; the write, the Kopie INTERMAX and their removal under failures are `verify-zapis-intermax`.

## Gotchas

- The process runs on the computer's clock: the Kopia's name and the metrics period come from it, so the assertion accepts any moment of the run and takes the period from the Kopia's day instead of a fixed token.
- The fixture values (`ZL-782…`, `example.invalid/zlecenie`) are row content: the self-test fails when they reach the evidence.
- On a pull request the E2E step runs `--variant all` only when the change touches `src/`; a change to this skill alone reaches it on `main`.
