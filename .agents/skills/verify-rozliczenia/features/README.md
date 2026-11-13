# Rozliczenia verification map

This is the maintained source for verifying the user-facing MAXIMISEART-Dad
processes through the machine script `tools/uruchom_proces.py` (`settlement`
for Przebieg rozliczeń, `preparation` for Przygotowanie pliku zbiorczego,
`intermax` for Uporządkowanie INTERMAX). Dad starts them in Centrum rozliczeń; the script runs the same core outside Centrum
and prints the Centrum contract as JSON, which the assertions read as its
contract model `ProcessResult`.

## Baseline preconditions

- Run on Windows PowerShell from the repository root; `--root` and `--run-dir` can point anywhere.
- Python 3.13 or newer and `requirements.txt` are installed.
- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`; it creates fresh roots and runs the doctor before driving.
- Use `--variant existing`, `locked`, or `unmapped` for the corresponding publication and safety-gate proof; `--variant` takes several at once.
- Use `--variant preparation` for Przygotowanie pliku zbiorczego.
- Use `--variant preparation-real-templates` locally when `config/` holds the real Wzorce; it is outside CI and `--variant all`, and prints `VERIFY SKIP` without them.
- Use `--variant chain` for the whole path from Rejestr zleceń through both processes to the Rozliczenia pracowników; `--variant chain-real-templates` is its local-only twin on the three real Wzorce, with the same skip rule.
- Use `--variant intermax` for Uporządkowanie INTERMAX.
- Centrum rozliczeń is Dad's route to the processes; it is covered by `verify-centrum-rozliczen`, not by this map.
- Never use real customer workbooks or a fixture owned by another verification run. The real Wzorce enter only as byte copies inside the run root.

## Driving conventions

- The one-command orchestrator verifies each process through the machine script (`settlement`, `preparation` for `--variant preparation`, both in turn for `--variant chain`, or `intermax` for `--variant intermax`).
- Read each run's command, exit code, and JSON result from `<step>.json` and its metrics file from `<step>-metrics.jsonl` in the UTF-8 evidence directory.
- Recognise a warning or a stop by its Komunikat `code`.
- Use workbook reads only for post-action assertions; do not call internal engine functions as proof.
- The orchestrator runs `--dry-run` before a real run, checks the complete plan,
  and verifies that it writes metrics but creates no destination folder or
  output workbook. Uporządkowanie INTERMAX has no dry-run: `--variant
  intermax` runs it once and checks the Kopia INTERMAX it saved first. The real run creates and atomically publishes all worker
  workbooks from the Wzorzec rozliczenia pracownika.
- Evidence stays in `<run dir>\evidence\` (`--run-dir`, default `.verification`); cleanup removes only a run root that a fixture created.

## Proof and skip reporting

- A JSON result alone is insufficient: pair it with workbook state and metrics.
- Keep row values, Wzorzec cell values, customer addresses, and order numbers out of evidence and metrics. The only paths in evidence are the synthetic scratch paths and, for the `*-real-templates` variants, the Wzorce directory in each step's `command`; metrics carry no path at all.
- The default fixture returns `0`; `--variant unmapped` separately verifies a
  dry-run warning and a failed real run with no published folder.
- `VERIFY SKIP` from `preparation-real-templates` or `chain-real-templates` is a skip: report it as one.
- Run cleanup after every failed iteration and confirm the evidence directory still exists.

## Features

- [Workbook preparation](./prepare-workbooks.md) covers Wzorzec rozliczenia pracownika copies and all-or-nothing publication.
- [Dry-run planning](./dry-run.md) covers safe inspection before writing.
- [Worker settlement](./settle-workbooks.md) covers fan-out into mapped templates and preserved formulas.
- [Safety gates](./safety-gates.md) covers unknown workers, the Wzorzec rozliczenia pracownika, existing data, Excel locks, and the stop on an unreadable Plik zbiorczy.
- [Progress and telemetry](./progress-and-metrics.md) covers observable phases, counters, exit semantics, and safe metrics.
- [Przygotowanie pliku zbiorczego](./prepare-collective-file.md) covers the Rejestr zleceń to Rozliczenie wewnętrzne and Plik zbiorczy process, and its dry-run.
- [From Rejestr zleceń to Rozliczenia pracowników](./prepare-and-settle.md) covers both processes in turn, and the Gotowość hand-over.
- [Uporządkowanie INTERMAX](./order-intermax.md) covers the JSON result of `intermax`, its Kopia INTERMAX, and the ordered pasted day.
