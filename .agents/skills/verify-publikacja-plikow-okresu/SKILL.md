---
name: verify-publikacja-plikow-okresu
description: Exhaustively check that Przygotowanie pliku zbiorczego publishes Rozliczenie wewnętrzne and Plik zbiorczy together or not at all, and never overwrites another file, under every order of a second run, Dad's actions, filesystem errors, and a killed process. Use when a change touches `write_period_files`, `_publish`, `ensure_period_files_absent` in `src/rozliczenia/preparation_files.py`, or `test_publikacja_plikow_okresu` fails.
pilnuje:
  - src/rozliczenia/preparation_files.py
  - src/rozliczenia/collective_preparation.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/eksplorator.py
ci: .agents/skills/verify-publikacja-plikow-okresu/scripts/explore_publication.py
---

# Verify publikacja plików okresu

## What CI runs and what stays local

CI runs `explore_publication.py` (the `ci:` key) and `tests/test_publikacja_plikow_okresu.py` whenever
a change touches this skill, and `check_publication_mutations.py` in full CI on `main` and nightly on
`main` (`mutacje-nocne.yml`). Run them locally only to reproduce a red CI step or the night's issue, or
one scope while you work on it. What stays with you: „Does the change
touch it?” (a change that makes Przygotowanie publish around `write_period_files` escapes the check
altogether), bringing the model in line when the drift says so, and sorting a red run as „When the check fails”
says.

## The promise

- **NIENADPISYWANIE**: publishing the period files never removes, replaces, or
  moves away a file or folder that someone else made. Harm: Dad loses a Plik
  zbiorczy he already filled in for Gotowość.
- **RAZEM_ALBO_ZADEN**: after an Uruchomienie procesu ends, its Folder okresu
  holds both period files or neither. A success leaves both. A stop leaves
  neither, because its message says „Nie utworzono żadnego pliku”. The one
  exception, as in `GLOSSARY.md`: a stop may leave a file when its message names
  every file left and does not say that no file was created
  (`BLAD_ZAPISU_POZOSTAL_PLIK` after a failed rollback). Harm: with only one file
  in place and no word about it, the next run stops on `PLIK_OKRESU_ISTNIEJE` and
  Dad has to find and delete a file by hand. One break is an accepted risk, listed
  below.

## Does the change touch it?

The check covers `preparation_files.write_period_files()` from the staging
directory onwards: `staged_directory.mkdir()`, both staged writes,
`_publish()`, `ensure_period_files_absent()` and the rollback. Run it when a diff
touches any of these, or the exception mapping in `write_period_files`, or makes
`prepare_collective_file()` publish without going through `write_period_files`.
Changes to workbook content (`_create_file`, styles, Rejestr reading) do
not matter here: the check gives `write_period_files` its own `preparation_files.Disk`,
whose workbook writing is one step that creates the staged file and returns a route,
as `_create_file` returns it for the metrics record (`RouteCounts`).

The parts modelled by hand are the defaults of `preparation_files.Disk` that the
check's `period_disk()` replaces: `_make_staging`, `_create_file` and
`_remove_staging` of `preparation_files.py`, whose digests are in
`model/definicje.json`. When one of them changes, `explore_publication.py` fails in CI with
`PUBLIKACJA: ROZJAZD MODELU Z KODEM` before the check, and prints the drift as an
`UWAGA:` line above the verdict elsewhere; `tools/szybko.py` fails on the same
drift before you push (step `rozjazd modelu`).

## Bring the model in line

When `_make_staging`, `_create_file` or `_remove_staging` changes:

1. Read the diff: the drift line names the changed definition.
2. Change its step in `period_disk()` of `explore_publication.py` so that it does what the code does: what it
   returns (the staging directory, the route for the metrics record), what it raises, and which files it creates or
   removes.
3. Run the check and `--strict`. A new violation is a finding: replay it on the code before you call it a bug.
4. Run `tools/przesun_model.py verify-publikacja-plikow-okresu` only after the harness describes the code, and write
   in the commit message what changed in the harness and why.

## Run

```powershell
py -3 .agents\skills\verify-publikacja-plikow-okresu\scripts\explore_publication.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`. It takes about 5 s on a
Mac, needs nothing beyond the repo's `.venv`, and runs in CI as
`tests/test_publikacja_plikow_okresu.py`. In a worktree the script checks the
worktree's own `src`.

The script has no step limit of its own, so a hang in the code under check (a
loop that makes no filesystem call) leaves a manual run waiting until you press
Ctrl+C. Under pytest the `timeout = 120` of `pyproject.toml` ends it: on Linux
and macOS as `Failed: Timeout` of the test, on Windows by killing the xdist
worker. The CI `pytest` job has no `timeout-minutes`, so that limit is the only
one there. The check does not tell a hang from a slow runner and does not name
the step that hung: look at the stack that pytest-timeout prints.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `PUBLIKACJA OK` | 0 | Both rules hold in every schedule. |
| `PUBLIKACJA OK, ZNANE USTALENIA: n, ZAAKCEPTOWANE RYZYKA: m` | 0 | Only the known findings and accepted risks below, each printed with its counterexample. A count of zero is left out. |
| `PUBLIKACJA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below, or `BRAK_PUBLIKACJI`: with no errors, kills, or Dad actions, nothing was ever published. |
| `PUBLIKACJA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding or accepted risk did not show in a scope of its `after`. If a change fixed it, narrow or delete it in `KNOWN_FINDINGS` or `ACCEPTED_RISKS` and below. |
| `PUBLIKACJA: ROZJAZD MODELU Z KODEM` | 1 | Only in CI, before the check: `_make_staging`, `_create_file` or `_remove_staging` differs from its digest in `model/definicje.json` (see „Bring the model in line”). |
| `PUBLIKACJA: LUKA MODELU (n)` | 2 | The code made a filesystem call the in-memory disk does not model. No verdict on the rules. |

`--scope jedno-uruchomienie` or `--scope dwa-uruchomienia` runs one scope.
`--strict` counts known findings and accepted risks as violations too.

## How it works and what it covers

The script runs the real `write_period_files()` in modelled runs against an in-memory
disk with Windows semantics. Each run is a greenlet on the script's one OS thread, so a busy
CI runner slows the check only by its share of a CPU, not by a kernel thread switch at every
step. On the disk `os.rename` never replaces an existing target, and
`os.replace` replaces a file but never a folder. Every filesystem call is one
indivisible step, the same as one call in the code. Before each step the
checker tries every possibility: the other run moves first, Dad acts first, the
call fails with `PermissionError` (Excel, antivirus, or OneDrive holding the
file), or the process is killed (Dad closes the console window). Schedules that
reach a state already seen are cut short. This is sound because the code is
deterministic: a state means the disk, what each run has observed so far, and
the bounds left. A read observes whether its path holds nothing, a file or a folder,
not the answer of the `os` call that asked: `Path.is_symlink` asks `os.lstat` on Python
3.11 and 3.12 but `os.path.islink` on 3.14, and with the answer in the state 3.14
explored 6640 schedules of `dwa-uruchomienia` instead of 9798. The tree is the same
on every Python.

| Scope | Runs at once | Initial Folder okresu | Dad's actions | Failed calls | Kills |
| --- | --- | --- | --- | --- | --- |
| `jedno-uruchomienie` | 1 | absent, empty, with Dad's file named like either period file | ≤ 2 | ≤ 2 | ≤ 1 |
| `dwa-uruchomienia` (Centrum and a machine-script run at once) | 2 | same four | ≤ 1 | ≤ 1 | ≤ 1 |

Dad's actions are: create the Folder okresu, or save his own file under a
period file's name. Failures are injected only into calls that change the
disk. Removing the staging directory is one such call, so it can fail
as when OneDrive holds the folder; the process is not killed right before it,
because the run's outcome is already decided then. Before exploring, a probe confirms that `Path.exists`, `is_symlink`,
`mkdir`, `rename`, `unlink` and `os.rename` reach the in-memory disk on the
running Python. CI runs the probe on 3.11 and 3.14. Native fast paths that skip
the patched `os` functions, such as `_winapi.CopyFile2` inside `shutil.copyfile`
on Windows with Python 3.14, still raise an audit event. A `sys.addaudithook`
turns any real filesystem call on an in-memory path into LUKA MODELU.
Otherwise it would fail on the missing real path as an ordinary `OSError`.

Not covered: the steps before Zapisywanie (Sprawdzanie, Odczyt danych,
Planowanie), workbook content, POSIX rename semantics (macOS and Linux replace
an existing target, so there only the re-check in `_publish` guards, with a race
window after it), symlinks,
network drives whose rename is not atomic, more than two runs or the bounds
above, and Przebieg rozliczeń's own folder publication in `settlement_files.py`.

## Known findings

None at present: `KNOWN_FINDINGS` in `explore_publication.py` is empty.

A known finding is a real defect in the current code. It is reported on every
run until the code is fixed. When a code change fixes it, the check ends with
`ZNALEZISKO ZNIKNĘŁO`: delete its entry from `KNOWN_FINDINGS` and from this list.

## Accepted risks

A break of a rule that a recorded decision accepts. It is printed as
`ZAAKCEPTOWANE RYZYKO` on every run and does not fail the check:

1. **Proces zamknięty w trakcie publikacji**
   ([ADR 0005](../../../docs/adr/0005-przerwana-publikacja-plikow-okresu.md)).
   When the Folder okresu already exists, `_publish` moves the two files with
   two separate `os.rename` calls. If the process dies between them, or after
   the second `os.rename` failed (a file system error or Dad's own file of that
   name) and before the rollback's `os.unlink` removed the first file, only
   Rozliczenie wewnętrzne is left. ADR 0005 accepts both. The next run stops on
   `PLIK_OKRESU_ISTNIEJE`, and Dad's instructions say how to recognise and
   remove the leftover file. The check prints it twice, once for each step the
   process died before.

An entry lives in `ACCEPTED_RISKS` in `explore_publication.py` as an `Excuse` of
`tools/lib/eksplorator.py`: it names its decision, names in `after` the scopes
after which it always shows (both, today), and has its shape (`RiskShape`, each
part required, #920): the steps
of `_publish` before which the kill of the process ended the run
(`killed_before`), the run's period files left, exactly (`left`), and no failed
`os.unlink` of the run (`unlink_failed`): a rollback whose `os.unlink` failed is
issue #92's case, which ADR 0005 does not cover. A run that was not killed, that
left other files, or whose `os.unlink` failed breaks the rule anew. Each part has a broken variant just
outside it in `BOUNDARIES` of `check_publication_mutations.py`, which must give
a new violation; `tests/test_mutacje_skilli.py` reds an entry with a part
without one. If a change to the publication code makes it disappear, the check
ends with `ZNALEZISKO ZNIKNĘŁO`: delete the entry here and there, and mark the ADR
as superseded.

## When the check fails

Read the counterexample as a story. Each numbered line is one step:
`u1`/`u2` are the runs, `tata` is Dad, and `[preparation_files.py:LINE function]`
is the code that made the call. Then sort it into one of three cases:

- **Real bug**: the story is something that can happen to Dad on Windows, and
  the end state breaks the rule as stated above. Report it with the story in
  those words. Fix the product code only if the user asks. If the user accepts
  the risk instead, record the decision in an ADR, add to `ACCEPTED_RISKS` an
  entry naming the ADR with the shape of its story (`RiskShape`) and the scopes
  it shows in (`after`), add to
  `BOUNDARIES` a broken variant just outside each part of it, and add it to
  Accepted risks here.
- **Modeling error**: the story contains a step Windows would not do, such as a
  rename that replaces a file, or a step the code cannot reach. Fix the
  in-memory disk (`VirtualDisk`) or `period_disk()`, then rerun the mutations below.
- **LUKA MODELU**: the code started using a call the disk does not model (for
  example `shutil.move`, `open`, `os.scandir`). Model the call in `intercepted()`
  and `VirtualDisk` with its Windows behaviour, or ask whether the code should
  avoid it. Never reword a rule or shrink a scope to make a real counterexample
  disappear.

## After changing the checker or an intended change to the publication code

CI proves the check can still fail: the night on `main` runs the script below after
a change of this skill's folder. Run it locally only to reproduce a red Mutation checks
step or the night's issue, or after you rewrite a mutation. It applies the broken variants to a temporary
copy of the checkout (`tools/mutacje.py`), never to the checkout:

```powershell
py -3 .agents\skills\verify-publikacja-plikow-okresu\scripts\check_publication_mutations.py
```

It must end with `MUTACJE OK`: `os.replace` instead of `os.rename`, a removed
rollback (`BOUNDARIES`: a run that is not killed, outside `killed_before`), the
period files moved in the reverse order (`BOUNDARIES`: only the Plik zbiorczy
left, outside `left`), a rollback that retries a failed `os.unlink`
(`BOUNDARIES`: killed before the retry, outside `unlink_failed`), a failed
rollback reported as plain `BLAD_ZAPISU`, recording a file
for rollback before it is moved, and a failed staging cleanup after publication
raised as a stop all give `NOWE NARUSZENIE`. `shutil.move` gives `LUKA MODELU`. A mutation reported as
`NIEAKTUALNA` no longer matches `preparation_files.py`. Rewrite its `anchor` and
`replacement` in `check_publication_mutations.py` against the new code so it breaks the same
rule again. If the publication code moves to another file, update
`VERIFIED_FILE` and the harness in `explore_publication.py`, and update this
skill's description.
