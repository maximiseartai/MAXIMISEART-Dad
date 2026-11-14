# Uporządkowanie INTERMAX

The third process. Dad pastes one day of Surowe zlecenia from the company app at the bottom of INTERMAX (the Rejestr
zleceń) and starts Uporządkowanie INTERMAX in Centrum rozliczeń; outside Centrum it runs as `tools/uruchom_proces.py
intermax`. It has no period and no preview without saving: it saves a Kopia INTERMAX, then replaces INTERMAX with
the pasted day ordered by Wykonawca and hour.

## Sub-features

Printed by `scripts/workflow_sub_features.py --feature order-intermax` from the steps of the workflow and the checks of its helpers; refresh the section with it.

Variants: `intermax`.

- `fixture` runs `create_intermax_fixture.py` and expects exit 0.
- `run` runs `tools/uruchom_proces.py intermax` and expects exit 0.
- `assert-run` runs `assert_intermax.py` and expects exit 0. It fails when:
  - process step evidence is missing
  - … carries row content besides the identifier it names
  - process result contains row content
  - process step printed no JSON result
  - process result does not match the contract ProcessResult: …
  - process result reports its metrics record as not saved
  - result is not OK without a stop and warnings
  - result has no summary
  - summary figures are not Zlecenia … and Wykonawcy …
  - summary.intermax_copy is not the name of a Kopia INTERMAX before ordering
  - summary does not match the ordered day pon 26.10.2026 of the synthetic INTERMAX
  - progress does not report the four stages completed in order
  - progress reports Szablony pracowników
  - … does not hold exactly the Kopia INTERMAX the summary names
  - Kopia INTERMAX is not INTERMAX as it was before the run
  - Kopia INTERMAX is not named after a moment of this run in the computer's clock
  - INTERMAX was not written
  - the pasted day is not ordered by Wykonawca alphabetically and by hour
  - rows of the ordered days above the pasted day changed
  - … does not contain exactly …
  - … record is not a completed run of the period
  - … contains row content or a filesystem path
  - evidence cannot be read: …
  - metrics counters are not the orders and Wykonawcy of the pasted day

  It prints `ASSERT OK | intermax=true | orders=… | workers=… | intermax_copy=before_run | ordered_by_worker_and_hour=true | earlier_days_unchanged=true | metrics_safe=true` when no check fails.

## How to get to it (user POV)

Dad starts it on the card „Uporządkuj INTERMAX” in Centrum rozliczeń, which takes INTERMAX from Ustawienia Centrum;
`verify-centrum-rozliczen` drives that route.

## Driving it with PowerShell and the machine script

Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant intermax` from the repository root
(macOS: `.venv/bin/python`). The proof is in the evidence folder that `VERIFY OK` names: `run.json`,
`run-metrics.jsonl` and `assert-run.txt`.

## Gotchas

- The variant reaches no stop, no write under Excel or OneDrive and no look of the ordered rows:
  `tests/test_uporzadkowanie_intermax.py` proves the stops and the look, `verify-zapis-intermax` the write.
- Run by hand, the machine script without `--copies` writes the Kopia INTERMAX to the tool's own folder of Kopie, so
  pass one outside Dad's computer.
- On a pull request the E2E step runs `--variant all` only when the change touches `src/`; a change to this skill
  alone reaches it on `main`.
