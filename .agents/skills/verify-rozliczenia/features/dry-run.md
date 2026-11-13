# Dry-run planning

Dry-run validates and previews the full set of worker workbooks without creating
the target folder or any output workbook. It reads the source, worker mapping,
and shared Wzorzec rozliczenia pracownika, then appends a new local metrics record, creating the
metrics file and parent directory if needed.

## Sub-features

- `dry-run-validation` checks the source name and location, destination absence,
  mapping shape, Wzorzec rozliczenia pracownika workbook, source header, and worker identifiers.
- `dry-run-plan` lists one named output per configured worker with its rows,
  including workers with no source rows, and the planned and empty counts.
- `dry-run-no-write` leaves the source and Wzorzec rozliczenia pracownika unchanged and creates no
  target folder.
- `dry-run-metrics` records a `DRY-RUN` telemetry entry without customer row
  contents or filesystem paths.

## How to get to it (user POV)

- Dad's dry-run is `Podgląd bez zapisu` in Centrum rozliczeń, which
  `verify-centrum-rozliczen` drives.
- Here run `py -3 tools\uruchom_proces.py settlement --source <source> --wykonawcy <wykonawcy.yaml> --worker-template <worker-template> --metrics <metrics> --dry-run`.
  Without `--config` and `--worker-template` the script takes the files Centrum uses from `config/`.

## Driving it with PowerShell and the machine script

Preconditions:

- Use a synthetic source, mapping, and Wzorzec rozliczenia pracownika; the target folder must not
  exist before dry-run.
- The orchestrator creates unique fixture, evidence, and cleanup paths.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. The orchestrator returns `0` after a successful proof; `--variant unmapped` records exit `2` in `dry-run.json` and checks the mapping warning.
- **Check the plan and communication.** The assertion compares `summary` with
  the expected plan: figures `Wiersze danych` 3, `Planowane szablony` 2,
  `Puste szablony` 1, and `worker_settlements` with each Wykonawca, output filename, his orders and `empty`
  (Kamil's 0 and empty). It requires result `OK` with no `warnings` and `Problemy` 0, or
  for `--variant unmapped` result `WYMAGA_SPRAWDZENIA` with one warning
  `BRAK_MAPOWANIA` whose "Co się stało" names `unknown.synthetic`, and
  `Problemy` 1. No row value appears anywhere else in the JSON.
- **Check no workbook write.** `assert-dry-run.txt` confirms the target folder
  was not created and source/Wzorzec rozliczenia pracownika hashes still match the fixture manifest.
- **Check telemetry.** `assert-dry-run.txt` reports `metrics_safe=true`: exactly
  one completed `DRY-RUN` record (result `OK`, or `WYMAGA_SPRAWDZENIA` for
  `--variant unmapped`) with no row content or scratch path.

## Gotchas

- Dry-run reads the source and Wzorzec rozliczenia pracownika and writes local metrics; it is not a
  zero-I/O simulation.
- An existing destination folder, invalid mapping, or missing/invalid
  Wzorzec rozliczenia pracownika stops the run before any output workbook is created.
- An unmapped source identifier, or a Wiersz danych with an empty `WYKONAWCA`
  (`BRAK_WYKONAWCY`), is reported without printing the identifier or row
  contents; dry-run returns warning code `2` while showing the full plan.
- The default fixture has mapped workers only and returns `0`; use
  `--variant unmapped` to verify the warning path.
- A dry-run proves the preview path, not the later write path; the default
  verifier follows it with a real run through the same script.
