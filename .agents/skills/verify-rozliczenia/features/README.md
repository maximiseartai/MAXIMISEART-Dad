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

## Feature entry contract

A feature file has the four H2 `## Sub-features`, `## How to get to it (user POV)`, `## Driving it with PowerShell
and the machine script` and `## Gotchas`, in this order. In a file whose section names
`scripts/workflow_sub_features.py --feature <feature>`, the section is that command's output, and
`tests/test_mapy_funkcji.py` fails when it differs. It is the plan of each variant of the feature's process
(`WorkflowProcess` in `run_verification.py`): the workflow runs, but every step and every change it makes to the run
root between steps is recorded instead of run, with the run's folders as `<run-root>`, `<evidence>`, `<templates>`
and `<run-dir>`. So it lists what a variant runs, in order, `cleanup` and `self-test` included, each step with its
command and the exit code it expects. A real run fails when the steps it ran differ from its plan, so CI proves the
plan of every variant it runs; nothing compares the plan of a variant on the real Wzorce with a run. A step
`assert-*` fails on the messages its script appends to `errors` and on an exception its script raises: `main` prints
the exceptions it catches as `ASSERT FAIL: …`, and any other ends the step with its traceback. The section names the
script and its mode, and both ways are read in that script, not in the map. Everything outside the section is prose
the command does not confirm: `How to get to it` is a few sentences from Dad's point of view, `Driving it` the one
command and where its evidence is, and `Gotchas` only traps the code does not handle, such as what the variant does
not reach and which test proves it. Every feature file's section comes from the command; `tests/test_mapy_funkcji.py`
fails on a feature file that README does not link or that does not name the command.

## Features

- [Przebieg rozliczeń](./settlement.md) covers the Plik zbiorczy to Rozliczenia pracowników process, its dry-run, and the stops for an existing folder, a locked Wzorzec and an unmapped WYKONAWCA.
- [Przygotowanie pliku zbiorczego](./prepare-collective-file.md) covers the Rejestr zleceń to Rozliczenie wewnętrzne and Plik zbiorczy process, and its dry-run.
- [From Rejestr zleceń to Rozliczenia pracowników](./prepare-and-settle.md) covers both processes in turn, and the Gotowość hand-over.
- [Uporządkowanie INTERMAX](./order-intermax.md) covers the JSON result of `intermax`, its Kopia INTERMAX, and the ordered pasted day.
