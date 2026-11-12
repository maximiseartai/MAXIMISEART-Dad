---
name: verify-zapis-intermax
description: Exhaustively check that Uporządkowanie INTERMAX (`order_register` in `src/rozliczenia/intermax_ordering.py`) and Przywracanie Kopii INTERMAX (`restore` in `src/rozliczenia/intermax_restore.py`), which both replace through `replace_register` in `src/rozliczenia/intermax_replace.py`, and Wpisanie raportów (`write_cells` in `src/rozliczenia/intermax_cells.py`), which replaces through `replace_without_copy` in the same sequence without a Kopia, replace the Rejestr zleceń only over the bytes they read, keep a Kopia INTERMAX with exactly the bytes they replaced and the 10 newest Kopie of both names with the earlier ones byte for byte, put exactly the chosen Kopia into INTERMAX, put exactly the written cells into INTERMAX and leave the Kopie alone in Wpisanie raportów, and leave INTERMAX, its folder and the Kopie as they were when they stop, under every order of a worker's change arriving through OneDrive, Dad opening INTERMAX in Excel, OneDrive refusing the replace, failed file steps, a failed write check and a killed process. Use when a change touches `intermax_replace` (`replace_register`, `replace_without_copy`, their one sequence `_replacement` with its retried replace, `Disk`, `Waiting`, the Kopia and its cleanup), the save phase of `order_register`, `intermax_restore.restore`, `intermax_cells.write_cells`, `intermax_copies.named`, `listed` or `outdated`, `register_file.read`, `intermax_file.check` or `intermax_file.check_cells`, `workbook_save.write_atomically`, `workbook_files` reading or the Excel lock, adds another writer of INTERMAX or of the Kopie folder, or when `explore_intermax.py` fails.
pilnuje:
  - src/rozliczenia/intermax_replace.py
  - src/rozliczenia/intermax_ordering.py
  - src/rozliczenia/intermax_restore.py
  - src/rozliczenia/intermax_cells.py
  - src/rozliczenia/intermax_copies.py
  - src/rozliczenia/intermax_file.py
  - src/rozliczenia/register_file.py
  - src/rozliczenia/dad_files.py
  - src/rozliczenia/register_columns.py
  - src/rozliczenia/workbook_save.py
  - src/rozliczenia/workbook_files.py
  - src/rozliczenia/file_state.py
  - tools/lib/eksplorator.py
ci: .agents/skills/verify-zapis-intermax/scripts/explore_intermax.py
---

# Verify zapis INTERMAX

## What CI runs and what stays local

CI runs `explore_intermax.py` (the `ci:` key) in Mutation checks whenever a change touches this skill,
and `check_intermax_mutations.py` in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`). Run
them locally only to reproduce a red Mutation checks step or the night's issue, or while you work on the
checker. What stays with you on every change to the covered code is „Does the
change touch it?”: a new step between the read and the replace, a third writer of INTERMAX or of the
Kopie folder (beside Uporządkowanie, Przywracanie Kopii INTERMAX, #472, and Wpisanie raportów, #1226) or a new file next to INTERMAX
passes the check without being checked until the checker has a point for it. Sorting a red run as „When the
check fails” says also stays with you.

## The promise

INTERMAX is the only record of orders since 2021, in OneDrive, and the
workers edit it on their own computers (ADR 0019). Three processes
replace it: Uporządkowanie INTERMAX and Przywracanie Kopii INTERMAX from
Konfiguracja (#472), both through `replace_register` (#716), and Wpisanie
raportów (#1226), through `replace_without_copy` without a Kopia INTERMAX
(ADR 0028). Both functions run one sequence (`_replacement`) and differ only
in the Kopia. A rule holds for each process unless it names its processes;
„the run” is any of them.

- **BEZ_UTRATY_ZMIAN**: when the run replaces INTERMAX, it replaces the bytes
  it read. ADR 0019: Uporządkowanie „zmienia tylko Surowe zlecenia”, and every
  other part and row „zostają bajt w bajt”. Harm: a worker's change saved on
  another computer during the run is gone, and nobody sees it go.
- **KOPIA_ZASTAPIONEGO**: when Uporządkowanie or the restore replaces INTERMAX, a Kopia INTERMAX holds
  exactly the bytes it replaced (ADR 0019: „Przed każdą podmianą powstaje Kopia
  INTERMAX”). Harm: restoring the Kopia does not bring back what was there.
- **ZATRZYMANIE_BEZ_SLADU**: a run that stops, or ends in any other
  exception before the replace, leaves INTERMAX as it was, no temporary file next to it, and the
  same Kopie, names and bytes, as before
  (docstring of `intermax_replace`: „Po każdej `Refusal` i po każdym innym
  wyjątku INTERMAX, folder obok niego i folder Kopii są takie, jak były”). Harm: a stray file in Dad's OneDrive, a
  Kopia of a change that never happened, or Dad's earlier Kopie gone.
- **SUKCES**: a run that returns a summary has replaced INTERMAX and left no
  temporary file.
- **PRZYWROCONA_KOPIA**: a restore that returns has replaced INTERMAX with
  exactly the bytes of the chosen Kopia (#472: „INTERMAX jest bajt w bajt
  wybraną Kopią”). Harm: Dad clicks „Przywróć tę kopię” and still has the
  broken INTERMAX.
- **KOPIE_NAJNOWSZE**: after a summary of Uporządkowanie or the restore the Kopie folder holds the
  `intermax_copies.KEPT` (10) newest Kopie of both names (`przed
  uporządkowaniem`, `przed przywróceniem`) by the moment in their name, the new
  one among them, unless removing older ones failed, which the code turns into
  a warning, and every Kopia that was there before the run and is still there
  has the same bytes as before, also after that warning (`_create` in
  `intermax_replace` makes a Kopia only as a new file, `O_EXCL`). Harm: Dad
  loses the Kopia he needs, the folder grows forever, or a Kopia he kept holds
  another state than its name says.
- **DOKLADNIE_WPISANE**: when Wpisanie raportów replaces INTERMAX, INTERMAX is
  the bytes it read with exactly the written cells changed: every cell value
  openpyxl reads is as read but those cells, which hold their text, and every
  part but the order sheet and the styles is byte for byte the same (#1226:
  „INTERMAX jest nietknięty albo ma dokładnie wpisane komórki”). The oracle is
  openpyxl on the file, not the product's writer or its write check. Harm: Dad's
  INTERMAX broken or with other cells changed, and no Kopia to bring it back.
- **BEZ_KOPII**: Wpisanie raportów leaves the Kopie folder with the same Kopie,
  names and bytes, however it ends (ADR 0028: „Bez Kopii INTERMAX”). Harm: Kopie
  fill Dad's disk, or the limit of 10 removes the Kopia he needs.
- **BEZ_WYJATKU**: the run ends with a summary or a `StopError`, or the process
  dies; no other exception escapes. Wpisanie raportów has no process of its own
  yet (#1227), so the checker reads INTERMAX with `register_file.read` as its
  process will, and counts a fact of `write_cells` (`Rejected`, a `Refusal`) or a
  `WorkbookError` of the read as its stop. Harm: Dad sees an unexpected error
  instead of a Komunikat that tells him what to do.

## Does the change touch it?

The checker runs the real `order_register`, the real
`intermax_restore.restore` and the real `intermax_cells.write_cells` after
`register_file.read`, gives each its own `Disk` and `Waiting` (the real steps,
each behind a point), and wraps nine steps to choose, before each, what
happens first. Wpisanie raportów has no Kopia, so it never reaches the points of
the Kopia's name, the Kopia and the old Kopie. Each is one indivisible step of this code:

| Point in the checker | Code (`src/rozliczenia/`) |
| --- | --- |
| after the read | `register_file.read` (`DadFiles.read`), called in `order_register.read` and before `write_cells`; in the restore the first `workbook_content` of INTERMAX |
| the Excel lock check | `workbook_files.is_open_in_excel` on INTERMAX, in `ensure_available` (`check`, `register_file.read`, `workbook_content`), before the Kopia in `replace_register` and after a refused replace |
| the temporary file | `Disk.write` of the temporary file in `_replacement`, inside `workbook_save.write_atomically`; may raise `OSError` (`Refusal.WRITE_FAILED`), and in Wpisanie raportów may write only the first half of the bytes (a torn write, which only the write check sees) |
| the write check | `intermax_file.check` on the re-read temporary file, which Uporządkowanie gives `replace_register` as `check`, and `intermax_file.check_cells`, which `write_cells` gives `replace_without_copy`; may find a mismatch (`WriteMismatch`). The restore compares bytes and has no such point |
| the Kopia's name | `Disk.exists` of the Kopia's name in `replace_register`, after the write check and the Excel lock check; may raise `OSError` when the Kopie folder cannot be searched (`Refusal.COPY_FAILED`, as `file_state.path_taken` does for a folder without access on every Python) |
| the Kopia | `Disk.create` of the Kopia with the bytes read (`current`), after the name; may raise `OSError`, and raises `FileExistsError` (`O_EXCL`) when a Kopia of that name exists (`Refusal.COPY_EXISTS`, which `intermax_messages.refused` names `PRZYWRACANIE_PRZED_CHWILA` for the restore), also one written after `Disk.exists`; a Kopia of a name that was taken is never removed |
| the replace | `Disk.replace` of the temporary file over INTERMAX in the `replace` that `_replacement` gives `workbook_save.write_atomically`; may raise `OSError`, may be refused by OneDrive (`PermissionError` without the `~$` lock, which it retries), and raises `PermissionError` while the `~$` lock exists, as Windows does for a file Excel holds |
| the pause before a retry | `waiting.pause` in that `replace`, after a refusal and before it reads INTERMAX again (`Disk.read`) and retries; may last the whole retry time (`RETRY_S`), so the next refusal ends in `Refusal.ONEDRIVE_HOLDS`. The checker's `Waiting` clock moves only in this pause and never sleeps |
| the old Kopie | `Disk.remove` of a Kopia older than the `KEPT` newest after the replace; may raise `OSError`, which `replace_register` returns as `Replaced.old_copies_kept` and both processes turn into a warning |

At each point, before the step, a worker may save a change on another
computer, which OneDrive puts in place as a new INTERMAX (not while Excel holds
INTERMAX: OneDrive then keeps a conflict copy beside it, which the checker
leaves out), Dad may open INTERMAX in Excel (the `~$` lock file), the step may
fail, or the process may die.

Covered files: `src/rozliczenia/intermax_replace.py` (`replace_register`, `replace_without_copy`, `_replacement`,
`Disk`, `LOCAL_DISK`, `Waiting`), `src/rozliczenia/intermax_ordering.py` (`order_register`),
`src/rozliczenia/intermax_restore.py` (`restore`), `src/rozliczenia/intermax_cells.py` (`write_cells`),
`src/rozliczenia/intermax_copies.py` (`named`, `listed`, `outdated`),
`src/rozliczenia/register_file.py` (`read`) and `src/rozliczenia/dad_files.py` (`DadFiles.read`),
`src/rozliczenia/intermax_file.py` (`check`, `check_cells`),
`src/rozliczenia/workbook_save.py` (`write_atomically`), and
`src/rozliczenia/workbook_files.py` (`workbook_content`, `ensure_available`,
`is_open_in_excel`, `excel_lock_file`) and `src/rozliczenia/file_state.py` (`file_state`, `path_state`, `_ABSENT`: missing
versus inaccessible behind `ensure_available`).

The steps the points stand for have digests in `model/definicje.json`: `intermax_replace.py` and
`intermax_copies.py` whole, and the read, the save phase of `order_register`, `restore`, `write_cells` and the Excel
lock check of the files above. When one of them changes, `tools/szybko.py` fails before you push (step `rozjazd modelu`), and this
skill's Mutation checks step fails before it starts (line `ROZJAZD MODELU Z KODEM`), until you have done
„Bring the model in line”. `intermax_file.check` and `check_cells` have no digest: what they compare does not matter here (DOKLADNIE_WPISANE
has its own oracle), and a change to how they are called ends the check with BEZ_WYJATKU.

## Bring the model in line

When `tools/szybko.py` names a changed definition of `model/definicje.json`:

1. Read the diff against the table above. It matters when it adds, removes or reorders a step between the read and
   the replace, changes what the Kopia is made from or when it or older Kopie disappear, adds another writer of
   INTERMAX or of the Kopie folder, or catches different exceptions. Changes to recognising and ordering the Surowe
   zlecenia (`raw_orders`, `intermax_file.ordered`, what `intermax_file.check` compares, how `register_file`
   recognises the order sheets), to which rows `write_cells` accepts and to Komunikaty do not matter here.
2. If it matters, change `_points`, `World` or `act` in `explore_intermax.py` and the table above so that each point
   stands before the step it names, and add a definition the steps now go through to `model/definicje.json`.
3. Run the check (below). A new violation is a finding: replay it on the code before you call it a bug.
4. Run `tools/przesun_model.py verify-zapis-intermax` only after the checker describes the code, and write in the
   commit message what changed in the checker and why.

## Run

```bash
.venv/bin/python .agents/skills/verify-zapis-intermax/scripts/explore_intermax.py
```

On Windows use `py -3` instead of `.venv/bin/python`. In a worktree, create its
`.venv` first (`python3 tools/setup_worktree.py`). It needs nothing beyond the
repo's Python, writes only into a temporary directory, and takes a few seconds.
`--strict` counts known findings as violations too.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `INTERMAX OK` | 0 | Every rule holds in every schedule. |
| `INTERMAX OK, ZNANE USTALENIA: n` | 0 | Only the known findings below, each printed with its shortest counterexample. |
| `INTERMAX: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below. The counterexample is printed. |
| `INTERMAX: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding did not show in a run of its `after`. If a change fixed it, delete it from `KNOWN_FINDINGS` and from this file. |

## How it works and what it covers

`explore_intermax.py` writes three synthetic INTERMAX files with
`tools/lib/atrapy/intermax.py`: the original, with a day of Surowe zlecenia at the
bottom, the version a worker saves on another computer, with one more
ordered order above them, and an earlier one with one ordered order fewer.
Wpisanie raportów writes `SKUTECZNE` of row 2 and `CZYNNOŚCI ZREALIZOWANE` of
row 5, ordered orders in the original and in the worker's version. For
every schedule it puts the original into a fresh folder, fills the Kopie folder
with 10 older Kopie (earlier days, alternately `przed przywróceniem` and `przed
uporządkowaniem`, so that their order by name differs from their order in time;
the oldest holds the earlier INTERMAX, the others their own bytes), runs
`order_register`, `restore` of the oldest Kopia or `write_cells`, and picks at every point in
the table. A third start runs the restore as a second one in the same second: the
Kopie folder also holds `INTERMAX przed przywróceniem` with the run's own moment,
so `Disk.create` raises `FileExistsError` and the restore must stop with that Kopia
and every other one as they were. It re-runs the code from scratch for every schedule.

Bounds: at most one worker's change, one Excel opening, one failed file step,
one failed write check, two OneDrive refusals of the replace, one pause that
lasts the whole retry time, one torn write (Wpisanie raportów only) and one
killed process per run. That is 2531
schedules: 1032 of Uporządkowanie, 776 of the restore, 147 of the second
restore in the same second and 576 of Wpisanie raportów (explorer run of
2026-11-09, #1226). The restore had 885 before #716: it read the Excel
lock once more while it sorted a failed replace, a point the one sequence no
longer has, because it reads the lock at the step that failed. Before the
point at `Disk.exists` they were 895, 663 and 99.

Not covered:

- the content of the ordered day (`raw_orders`, `intermax_file.ordered`, what
  `intermax_file.check` compares), which `tests/test_uporzadkowanie_intermax.py`
  covers, and the look of the written cells, which rows and columns
  `write_cells` refuses and where a Przeniesienie zlecenia (`OrderMove`, #1347) puts
  its row (`raw_orders.plan_moves`), which `tests/test_wpisanie_komorek_intermax.py`
  covers: a Przeniesienie only changes the bytes the write builds before the
  temporary file, not a step between the read and the replace;
- the Excel lock check right before the replace (`is_open_in_excel` in
  `_replacement`): the checker's replace fails while the `~$` lock exists, as on
  Windows, and the refused replace reads the lock again, so INTERMAX stays as it
  was without it (a variant without it gives `INTERMAX OK` on 2026-11-09);
  `tests/test_podmiana_intermax.py` shows it for all three processes, where the
  Mac's replace succeeds over an open file;
- a worker's change between two steps inside one point (the checker treats
  `os.replace` as atomic, as it is on NTFS);
- `Disk.remove` of the run's own Kopia failing after a failed replace, which
  `tests/test_podmiana_intermax.py` covers (the fact still comes back);
- two runs at once (Centrum runs one Uruchomienie at a time,
  `verify-jedno-uruchomienie-naraz`), so also a Kopia of the same name written
  between `Disk.exists` and `Disk.create`, which `tests/test_podmiana_intermax.py`
  covers (it stays);
- what a killed process leaves: the checker kills by raising at a point, so
  `finally` blocks still run and remove the temporary file, which a real kill
  would leave in OneDrive with a Kopia of a replace that never happened. After
  a kill only BEZ_UTRATY_ZMIAN and KOPIA_ZASTAPIONEGO are checked, when the
  replace happened;
- the restore's own checks before its first step (the Kopia missing, open in
  Excel or not a workbook), which `tests/test_centrum_przywracanie_kopii_intermax.py`
  covers, and a restore running beside an Uruchomienie, which `RunHost` refuses
  (`verify-jedno-uruchomienie-naraz`);
- the order of Kopie by the moment in their name around a clock change;
- a second Uporządkowanie in the same second (its `Refusal.COPY_EXISTS` becomes the
  ordinary Zatrzymanie `KOPIA_INTERMAX_NIEUDANA`): after an Uporządkowanie no Surowe
  zlecenia are left to order;
- the order of the write check before the Kopia: the one cleanup removes a
  Kopia after any failure, so a Kopia made before the check leaves no trace the
  checker sees; `tests/test_podmiana_intermax.py` shows that a mismatch never
  calls `Disk.create`.

## Known findings

1. **BEZ_UTRATY_ZMIAN and KOPIA_ZASTAPIONEGO: a worker's change that arrives
   during the run is lost.** The same holds for the restore, whose Kopia of the
   current state is made from the bytes it read (`current`), and BEZ_UTRATY_ZMIAN
   for Wpisanie raportów, whose cells go into the bytes it read (ADR 0028: Dad
   clicks only when his worker is not working in INTERMAX). The steps:
   1. `register_file.read` reads INTERMAX;
   2. `replace_register` writes the Kopia INTERMAX from the bytes read (`current`);
   3. a worker saves a change on another computer, and OneDrive replaces
      INTERMAX with it;
   4. `os.replace` puts the ordered file, made from the bytes read in step 1,
      over the worker's version;
   5. `order_register` returns its summary.

   The worker's change is in neither INTERMAX nor the Kopia. The window runs
   from the read to the first attempt of the replace: planning, writing the
   temporary file and reading it back, and the Kopia, seconds for Dad's 6.5 MB
   file. Nothing between them compares INTERMAX on disk with
   the bytes read. After OneDrive refuses the replace, `replace_register` waits, reads
   INTERMAX again and retries only over the bytes it read, so the window of a
   retry runs from that re-read to the retried `os.replace`. The checker shows
   the finding there too, because a point sits between them. No `os.replace` on
   Windows replaces only a file that is unchanged.

   Both are excused only in the shape of this story (`FindingShape`, each part
   required, #920): the worker's change came after the read before one of the
   run's points up to the replace, not in the pause before a retry
   (`came_before`), and OneDrive refused the replace no more after it
   (`refusals_after` 0). A worker's change followed by a refusal is one the run
   had a pause to see, and one that arrived in that pause is one the re-read
   after it sees, so losing either is a new violation. The run read the
   original and its replace put its file over the worker's change (`lost`), not
   over the run's own bytes or over a change it read. KOPIA_ZASTAPIONEGO also
   needs a Kopia of the bytes the run read (`copy`, `current` of
   `replace_register`); a Kopia of other bytes, such as the run's new file when
   INTERMAX changed before the Kopia, is a new violation. BEZ_UTRATY_ZMIAN says
   nothing of the Kopia, so its shape admits any. The same rules broken in any
   other schedule are a new violation.

   Each part that restricts has a broken variant just outside it in
   `BOUNDARIES` of `check_intermax_mutations.py`, which must give a new
   violation;
   `tests/test_mutacje_skilli.py` reds a finding with a part without one.

A known finding lives in `KNOWN_FINDINGS` in `explore_intermax.py` as an `Excuse`
of `tools/lib/eksplorator.py`, with the story after which it is excused, its
shape and in `after` the runs after which it always shows: both findings show in
Uporządkowanie and in the first restore, not in the second restore in the same
second (explorer run of 2026-11-08 on 1f7719a31), and BEZ_UTRATY_ZMIAN also in
Wpisanie raportów, which has no Kopia (explorer run of 2026-11-09, #1226). When a code change fixes one,
the check ends with `ZNALEZISKO ZNIKNĘŁO` naming the run: narrow or delete the
entry there and here.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a step of
`order_register` in the code's words, a worker's change or Dad opening Excel,
a failed step, or a dead process. Then sort it:

- **Real bug**: every step can happen at Dad's (OneDrive replacing the file
  with a worker's version, Excel's `~$` lock, a locked file or full disk,
  Centrum closed), and the end state breaks the rule as stated above. Report it
  with the story. Fix the product code only if the user asks.
- **Modeling error**: a step Windows or OneDrive would not do, or a point the
  code cannot reach. Fix `_points`, `World` or `act` in `explore_intermax.py`,
  and say what was wrong.
- **BEZ_WYJATKU**: the printed type and message name the exception; find where
  `replace_register`, `order_register` or `restore` lets it out.

Never shrink a bound or a rule to make a real counterexample go away.

## After changing the checker or an intended change to the save

CI proves the check can still fail. The night on `main` runs
`.agents/skills/verify-zapis-intermax/scripts/check_intermax_mutations.py`
after a change of this skill's folder. It applies each broken variant to a
temporary copy of the checkout (`tools/lib/silnik_mutacji.py`) and must end with
`MUTACJE OK`. Each of these gives `INTERMAX: NOWE NARUSZENIE`:

- a replace without a Kopia;
- a Kopia of other bytes than those read;
- a Kopia left after a failed replace (Excel, OneDrive or any other failure,
  in both processes, since #716 one cleanup);
- a Kopia of a name that was taken removed after its write fails, so the
  second restore in the same second removes the Kopia of the first;
- an `OSError` from checking the Kopia's name that escapes;
- an `OSError` from removing older Kopie that escapes;
- a temporary file left after a failed replace;
- older Kopie sorted the wrong way round;
- one Kopia kept instead of 10;
- a failed replace that removes every Kopia;
- a retried replace that does not read INTERMAX again after the pause;
- a retried replace that reads INTERMAX again before the pause instead of
  after it (`BOUNDARIES`: outside `came_before` of both findings);
- a retried replace that compares INTERMAX read after the pause with the bytes
  read right after OneDrive's refusal instead of those the run read
  (`BOUNDARIES`: outside `refusals_after` of both findings);
- a replace that, when INTERMAX changed after the read, first writes the run's
  new file over it and puts it back if the replace fails (`BOUNDARIES`: outside
  `lost` of both findings);
- a Kopia of the run's new file when INTERMAX changed before the Kopia
  (`BOUNDARIES`: outside `copy` of KOPIA_ZASTAPIONEGO);
- Kopie sorted by name instead of by the moment in their name;
- a Kopia that overwrites a Kopia of the same name (no `O_EXCL`): the second
  restore in the same second overwrites the Kopia of the first, and then stops
  with it rewritten (ZATRZYMANIE_BEZ_SLADU) or, after its replace, fails on
  `made[0]` with no Kopia of its own (BEZ_WYJATKU), so it never returns a
  summary;
- the same with a taken name that does not stop the run: the second restore in
  the same second returns a summary over the rewritten Kopia of the first
  (KOPIE_NAJNOWSZE);
- a restore that replaces INTERMAX with the bytes it read instead of the
  chosen Kopia;
- Wpisanie raportów without the write check (`check_cells`): a torn write of the
  temporary file replaces INTERMAX (DOKLADNIE_WPISANE).

Before #716 each process had its own copy of the Kopia and its cleanup, so
„a restore without the Kopia of the current state” and „the Kopia of the
current state left after a failed restore” were mutations of their own; now the
first two mutations above break both processes at once. „The Kopia made before
the write check” left the list with them: the one cleanup removes such a Kopia
after a mismatch, so only `tests/test_podmiana_intermax.py` sees the order.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its
`anchor` and `replacement` against the new code so that it breaks the same
rule again.
