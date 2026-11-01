---
name: verify-rozliczenia
description: Verify MAXIMISEART-Dad's processes (Przebieg rozliczeń, Przygotowanie pliku zbiorczego) through the machine script `tools/uruchom_proces.py`, each alone and chained from Rejestr zleceń to Rozliczenia pracowników, with synthetic Excel files, workbook side-effect checks, and retained evidence; use after process, workbook, or safety-rule changes.
pilnuje:
  - src/rozliczenia/__init__.py
  - src/rozliczenia/call_trace.py
  - src/rozliczenia/collective_*.py
  - src/rozliczenia/decision.py
  - src/rozliczenia/domain.py
  - src/rozliczenia/efenix_mark.py
  - src/rozliczenia/engine.py
  - src/rozliczenia/highlights.py
  - src/rozliczenia/hyperlinks.py
  - src/rozliczenia/inea_only_quantities.py
  - src/rozliczenia/input_checks.py
  - src/rozliczenia/intermax_*.py
  - src/rozliczenia/message.py
  - src/rozliczenia/order_facts.py
  - src/rozliczenia/period_folder.py
  - src/rozliczenia/phase_runner.py
  - src/rozliczenia/preparation_*.py
  - src/rozliczenia/process_run.py
  - src/rozliczenia/progress.py
  - src/rozliczenia/quantit*.py
  - src/rozliczenia/raw_orders.py
  - src/rozliczenia/row_look.py
  - src/rozliczenia/settlement_*.py
  - src/rozliczenia/telemetry.py
  - src/rozliczenia/template_*.py
  - src/rozliczenia/workbook_*.py
  - src/rozliczenia/worker_config.py
  - tools/uruchom_proces.py
ci: .agents/skills/verify-rozliczenia/scripts/quantity_rules_conformance.py
---

# Verify rozliczenia

Dad starts both processes in Centrum rozliczeń, verified by
`verify-centrum-rozliczen`
([ADR 0010](../../../docs/adr/0010-centrum-jedynym-wejsciem-taty.md)). This
harness starts them outside Centrum through the machine script
`tools/uruchom_proces.py`: `settlement` runs Przebieg rozliczeń and
`preparation` runs Przygotowanie pliku zbiorczego, through the same core
(`run_process`) and the same Uruchomienie view as Centrum. Each run prints one
JSON result in the shape of the Centrum contract and exits `0` (OK), `2`
(Wymaga sprawdzenia), or `1` (Zatrzymanie). The script's docstring is the
reference for its parameters and fields. Verification uses synthetic `.xlsx` files
and never uses a real customer workbook; the only exceptions are the local
`preparation-real-templates` and `chain-real-templates` variants, which copy
the real Wzorce from `config/`.

## What CI runs and what stays local

CI runs `run_verification.py --variant all` in the E2E step of pytest on Windows, and
`quantity_rules_conformance.py` (the `ci:` key) in Mutation checks, and
`check_quantity_rules_mutations.py` in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`). Run
them locally only to reproduce a red CI step or the night's issue, or the one variant you work on. What stays
with you on the Mac, as background commands: `preparation-real-templates` and `chain-real-templates`
on the real Wzorce in `config/` after changes to formatting or template handling, because CI has no
real Wzorce.

## Launch

Run the proof in PowerShell from the repository root (the script path is relative to it):

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py
```

The runner creates a scratch run root in `<run dir>\runs\<id>` and evidence in
`<run dir>\evidence\<id>`. The run dir is `.verification` of the checkout, or
any path given with `--run-dir`, e.g. a folder under `~/.t3/notes/<run>/`. It sets UTF-8
environment variables, creates the synthetic fixture, runs the doctor, drives
the machine script through dry-run and write modes, checks the JSON results and
workbook side effects, and cleans the scratch directory in `finally`. A successful run prints
`VERIFY OK`, an evidence path, and `scratch_removed=true`. The default fixture
contains only mapped synthetic workers, so dry-run and write both return `0`.

Use these variants for publication and safety-gate features. `--variant`
takes one or more variants and runs them in order:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing locked unmapped
```

`existing` creates a conflicting output folder after the doctor and dry-run, then
verifies it is unchanged. `locked` locks the Wzorzec rozliczenia pracownika before the real run.
`unmapped` adds an unknown synthetic WYKONAWCA and verifies that no output is
published.

Use this variant after changes to Przygotowanie pliku zbiorczego:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation
```

`preparation` builds a synthetic Rejestr zleceń and both Wzorce, drives
`tools/uruchom_proces.py preparation` through dry-run and write, and checks
both period files, including the Rejestr Hiperłącze of every written `NUMER ZL.` cell.
Its route and counts are in `features/prepare-collective-file.md`.

When `config/` holds the real Wzorce, also run the local variant on the Mac, as a
background command, after changes to formatting or template handling in
Przygotowanie pliku zbiorczego:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation-real-templates
```

It drives the same synthetic Rejestr into byte copies of both real Wzorce and
checks that the copies stay byte-identical, that every written Wiersz danych
has the Wygląd Wiersza danych in A:M (Rozliczenie wewnętrzne) and A:L (Plik
zbiorczy): its header's font face and size, left and centre alignment,
wrapping only for text with a line break, a thin automatic border and no
stored row height, that every written ADRES has the fill of that order's ADRES in the Rejestr, that every Wzorzec cell value outside the written rows is unchanged, and that `xl/externalLinks/*` stay byte-identical. The
Wzorce are git-ignored, so CI and `--variant all` leave this variant out. In a
worktree whose own `config/` holds no Wzorzec the runner reads the main
checkout's `config/` itself;
`--templates-dir` overrides that. Without both Wzorce the runner prints
`VERIFY SKIP` and exits `3`; report that as a skip, never as a proof.
A list with a skipped variant and no failed one ends with `VERIFY SKIP | ok=… | skipped=…` and exit `3`, never `VERIFY OK`; a failed variant makes it `VERIFY FAIL`.

Use this variant after changes to either process, to the Plik zbiorczy layout,
or to the hand-over between the processes:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain
```

`chain` walks Dad's whole path in one run: Przygotowanie pliku zbiorczego from
the synthetic Rejestr zleceń (dry-run, then write), a Gotowość step that types
quantities into `N:AP` and charges and remarks into `AQ:AT` of three Wiersze
danych of the resulting Plik zbiorczy, then Przebieg rozliczeń on that file
(dry-run, then write). It checks that every Rozliczenie pracownika holds only
its Wykonawca's Zlecenia skuteczne in Plik zbiorczy order, with `A:AT` equal to
the Plik zbiorczy row, Gotowość entries included, except the Ilości tylko dla
INEA (ADR 0018): `AP` of the synthetic `gniazdo` order and `AK` of the
`Technicolor 3*globo` order are empty while the Plik zbiorczy holds a value
there. Every cell keeps the Wyróżnienia of its Plik zbiorczy cell and, unless
emptied, its Hiperłącze; A:L also keep the number format and get the Wygląd
Wiersza danych; every `NUMER ZL.` cell keeps the
Hiperłącze of its Rejestr cell. `chain-real-templates` runs
the same path on byte copies of all three real Wzorce, including the Wzorzec
rozliczenia pracownika; like `preparation-real-templates` it is local only,
takes `--templates-dir`, and prints `VERIFY SKIP` without them. Route and
counts are in `features/prepare-and-settle.md`.

CI runs every CI variant in one command in its E2E step on Windows (Python 3.11 and
3.14), so run it locally only to reproduce a red E2E step:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant all
```

On macOS or Linux, replace `py -3` with `.venv/bin/python`; README.md covers
the `.venv` setup.

In a worktree, create its own `.venv` with `tools/setup_worktree.py` first:
the main checkout's `.venv` is an editable install of the main checkout's
`src`, so ad-hoc `python -c` there silently imports `main`'s code.

There is no server, port, login, seed database, or persistent instance. The
runner's subprocess timeout is 120 seconds; a timed-out child is terminated by
the process handle and the scratch cleanup still runs.

## Doctor

The runner always executes the read-only doctor before driving the application.
The result is retained in `doctor.txt` under the printed evidence directory.
`DOCTOR OK` means Python is at least 3.11, the checked-out build reports the
version in `pyproject.toml`, the source name and period folder agree, the source
has `WYKONAWCA` in `H17`, the local mapping and shared Wzorzec rozliczenia pracownika are readable,
and the target folder does not yet exist.

The `preparation` variant runs `preparation_doctor.py` instead. `DOCTOR OK`
there means the Rejestr has a sheet with all required headers, both Wzorce are
unlocked with their expected headers, the Wzorzec pliku zbiorczego has
`xl/externalLinks/*` parts, the mapping is readable, and the Folder okresu does
not yet exist. The `chain` variants pass `--with-worker-template`, which also
validates the Wzorzec rozliczenia pracownika the way Przebieg rozliczeń does.

For targeted debugging of a fixture that already exists, invoke the primitive
directly:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\doctor.py --root "$runRoot" --expected-version "0.1.0"
```

The doctor reads only; it does not start the app, alter a workbook, or write
metrics. Never drive a fixture that this run did not create.

## Drive

Use `run_verification.py` as the harness entry point. It launches
`tools/uruchom_proces.py` as a separate process with the same Python
interpreter as the harness; it never imports `rozliczenia`, uses test-only
helpers, or calls the settlement engine directly. Every input path is passed
explicitly, so no run reads `config/`. Its ordered stages are:

1. Create a disposable source workbook, a shared Wzorzec rozliczenia pracownika, and a local
   three-entry mapping. The target folder is absent.
2. Run the read-only doctor.
3. Run `settlement --dry-run` with the synthetic Wzorzec rozliczenia
   pracownika and assert the complete plan, no target folder, unchanged
   source/Wzorzec rozliczenia pracownika, and no row content.
4. Run `settlement` without `--dry-run`; the default fixture requires exit code
   `0` and asserts exactly three workbooks, routed values, the Hiperłącze of
   every `NUMER ZL.` cell, preserved formulas/formatting, an empty worker
   workbook, and an unchanged Wzorzec rozliczenia pracownika.
5. For `existing`, `locked`, or `unmapped`, require exit code `1`, the stop's
   Komunikat code, no partial output (or an existing folder left unchanged),
   and a metrics record whose `stop` is `{"kind": "for_tata", "code": <the
   stop's code>}`: each of these stops is one Dad removes himself.
6. Invoke cleanup in `finally`, then run the mechanical self-test against the
   retained evidence.

The `preparation` variant follows the same stages with its own primitives:
`create_preparation_fixture.py`, `preparation_doctor.py`,
`preparation --dry-run`, `assert_preparation.py --expect dry-run`,
`preparation`, then `assert_preparation.py --expect run`. The dry-run requires
exit code `0` and the write `2` (Wymaga sprawdzenia): Dad completes the Ilości
usług its warnings name in the written Plik zbiorczy.

The `chain` variants run, in order: `create_preparation_fixture.py
--with-worker-template`, `preparation_doctor.py --with-worker-template`, the four
preparation steps above under a `preparation-` prefix with their own
`preparation-metrics.jsonl`, `fill_readiness.py` (Gotowość), `settlement --source
<the Plik zbiorczy written by Przygotowanie> --dry-run`, `assert_chain.py
--expect dry-run`, `settlement` on the same file, then `assert_chain.py --expect
run`. Every run requires exit code `0`, except the Przygotowanie write (`2`).

The assertions read the result through the contract model it is printed
from (`ProcessResult` in `tools/uruchom_proces.py`), never as a raw dict, so a
field renamed or dropped in the contract fails the proof instead of passing it
unchecked. They check the contract fields Dad sees on the Uruchomienie card:
`result`, the plan or summary in `summary` (figures, `worker_settlements`, period
files, Zlecenia na dzień), `warnings` and `stop` by their Komunikat `code`,
and `progress` (the four stages completed in order, Szablony pracowników
completed of total, written and empty). The default fixture plans and writes
two mapped workbooks and one empty one with no Problemy, and its progress ends
at three of three Szablony pracowników. The `unmapped` variant proves that the
dry-run warns with `BRAK_MAPOWANIA` and the real run stops with
`NIEZNANY_WYKONAWCA` and publishes nothing; both name the unknown WYKONAWCA,
and it appears nowhere else in the result.

## Reguły ilości

After a change to `src/rozliczenia/quantity_rules.py` or to its conformance
test `tests/test_ilosci_uslug.py`, the night on `main` proves that the test
still catches a single broken rule. Run it locally only to reproduce a red
Mutation checks step or the night's issue, or after you rewrite a mutation:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\check_quantity_rules_mutations.py
```

It must end with `MUTACJE OK`. Each mutation breaks one rule of Dad's
instruction on a copy of the checkout, and `quantity_rules_conformance.py` must
fail on it: TV devices in Z instead of Q and P once per router, the 45 zł
surcharge (its amount, the 17:00 threshold, its days, only for a usterka),
S not as the sum O+P+Q+AG, single components, a known name (`usterka hurt`,
`wizja`) becoming unknown, pieces from `CZYNNOŚCI`, T from the first word of
`UMOWA`, `prewencja` without quantities, O from `akt int` in `CZYNNOŚCI`
only for `nokia` without a router (also with a TV device), once per order,
in any letter case and outside S, spelling
variants (`XG`, spaces around `*` and before `szt`), and rows without a rule. The check first runs
unbroken, so a red baseline fails the script instead of counting as detection.
It takes about 6 s on a Mac. CI runs it in the `mutations` job. A mutation
reported as `NIEAKTUALNA` no longer matches `quantity_rules.py`: rewrite its
anchor and replacement so it breaks the same rule in the new code. A new rule
gets a case in the test and a mutation here.

## Evidence

Evidence is written under `<run dir>\evidence\` and survives cleanup. Each
Uruchomienie procesu leaves `<step>.json` with the command, exit code, JSON
result, and stderr, and `<step>-metrics.jsonl`, the metrics file right after
that step. Every other step leaves `<step>.txt` with its command, stdout,
stderr, and exit code. A successful default run contains:

- `fixture.txt` with fixture creation output.
- `doctor.txt` with the read-only preflight result.
- `dry-run.json` and `dry-run-metrics.jsonl` from the dry-run.
- `assert-dry-run.txt` with the plan and no-write assertion and exit code `0`.
- `run.json` and `run-metrics.jsonl` from the real run; the metrics file holds
  the `DRY-RUN` and the `RUN` record, with no source path or row content.
- `assert-run.txt` with result, progress, and workbook side-effect assertions
  and exit code `0`.
- `cleanup.txt` with cleanup output and exit code `0`.
- `self-test.txt` with the skill and evidence invariant check.

The `chain` variants name the steps of each process instead:
`preparation-dry-run`, `preparation-run`, `settlement-dry-run`, and
`settlement-run`, each with its `.json`, `-metrics.jsonl`, and `assert-*.txt`,
plus `readiness.txt`. Each process keeps its own metrics history, so
`preparation-run-metrics.jsonl` and `settlement-run-metrics.jsonl` each hold
exactly one `DRY-RUN` and one `RUN` record.

The proof pairs every JSON result with the filesystem side effects. The
dry-run still reads workbooks and writes local metrics, so those effects are
asserted instead of inferred from the mode name. Mocks are not used.

## Self-test

The complete runner invokes the mechanical skill check after cleanup. To check
an existing proof directly, run:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\self_test.py --evidence-root "$evidenceRoot"
```

It checks the frontmatter, required feature-map headings, every documented
helper path, helper `--help` execution, strict UTF-8 evidence decoding, and
that cleanup preserves a separate evidence file. It also rejects the synthetic
fixture's source-row markers if they appear in evidence. The check reports only
file names and invariant failures, never the offending row value.

## Cleanup

The runner owns cleanup and invokes `cleanup.py` from a `finally` block after
both successful and failed workflow stages. It removes only a run root that a
fixture created, marked by its `.katalog-runu` file; it never removes evidence.
Do not kill processes by name.

If the runner itself is force-terminated before its `finally` block executes,
run the primitive against the abandoned run root discovered under
`<run dir>\runs\`:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists. A normal runner completion
already performs both checks and prints `scratch_removed=true`.

## Helpers

- `scripts/run_verification.py` is the one-command orchestrator. Invocation:
  `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`.
- `scripts/create_fixture.py` creates the isolated synthetic workbooks.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\create_fixture.py --root "$runRoot"`.
- `scripts/doctor.py` performs the read-only fixture and build check.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\doctor.py --root "$runRoot" --expected-version "0.1.0"`.
- `scripts/assert_results.py` checks the JSON result of a Przebieg rozliczeń
  step (`--result`) and workbook state after either mode; `--expected-stop`
  names the stop's Komunikat code for `no-publish` and `existing-output`, and
  `--expected-what` text its "Co się stało" must contain.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_results.py --root "$runRoot" --expect run --result "$evidenceRoot\run.json"`.
- `scripts/create_preparation_fixture.py` creates the synthetic Rejestr zleceń,
  both Wzorce, and the mapping for the `preparation` variant;
  `--with-worker-template` adds the Wzorzec rozliczenia pracownika for `chain`, and
  `--templates-from "$templatesDir"` copies the real Wzorce instead.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\create_preparation_fixture.py --root "$runRoot"`.
- `scripts/preparation_doctor.py` performs the read-only preflight for that fixture;
  `--with-worker-template` also validates the Wzorzec rozliczenia pracownika.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\preparation_doctor.py --root "$runRoot" --expected-version "0.1.0"`.
- `scripts/assert_preparation.py` checks the Folder okresu, both period files,
  their Hiperłącza, external links, inputs, the JSON result, and metrics; `--templates config` swaps
  the synthetic Wzorzec checks for the generic real-Wzorzec checks, and
  `--metrics` reads a history other than `<root>\metrics.jsonl`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_preparation.py --root "$runRoot" --expect run --result "$evidenceRoot\run.json"`.
- `scripts/fill_readiness.py` is the Gotowość step of `chain`: it fills `N:AT`
  in three Wiersze danych of the Plik zbiorczy, keeps every other cell and the
  external links, and records the period files' hashes for `assert_chain.py`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\fill_readiness.py --root "$runRoot"`.
- `scripts/assert_chain.py` checks the Przebieg rozliczeń of `chain` against
  the Plik zbiorczy it read: worker routing and order, `A:AT` equality of values apart from the empty Ilości tylko dla INEA,
  Wyróżnienia and Hiperłącza, the number format and Wygląd Wiersza danych in A:L, the Rejestr Hiperłącze in `NUMER ZL.`, Gotowość entries, no Zlecenie nieskuteczne, the preserved Wzorzec rozliczenia
  pracownika, unchanged inputs and period files, the JSON result, and metrics.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_chain.py --root "$runRoot" --expect run --result "$evidenceRoot\settlement-run.json"`.
- `scripts/wynik_uruchomienia.py` is what the three `assert_*.py` share: it
  loads a step's JSON result as `ProcessResult` and holds the metrics,
  Hiperłącza, and external-link readers. Alone it checks one evidence file and
  names the fields that do not match the contract, never their values.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\wynik_uruchomienia.py --result "$evidenceRoot\run.json"`.
- `scripts/cleanup.py` removes only a run root that a fixture created.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\cleanup.py --root "$runRoot"`.
- `scripts/self_test.py` checks the skill package and evidence hygiene.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\self_test.py --evidence-root "$evidenceRoot"`.
- `scripts/quantity_rules_conformance.py` runs the test of every line of Dad's
  instruction in `tests/test_ilosci_uslug.py` and ends with `ILOŚCI USŁUG OK`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\quantity_rules_conformance.py`.
- `scripts/check_quantity_rules_mutations.py` is the mutation table of Reguły
  ilości (see that section). Invocation:
  `py -3 .agents\skills\verify-rozliczenia\scripts\check_quantity_rules_mutations.py`.

Read `features/README.md` before choosing a feature. Keep the feature map
updated when routes, script parameters, contract fields, or workbook rules
change. Use `/maintain-verification-skill` for the maintenance loop.
