---
name: verify-skoroszyty-w-excelu
description: Verify in real Microsoft Excel for Mac (AppleScript) that the files of MAXIMISEART-Dad's processes open without a dialog, keep their external link, formulas, Wyróżnienia and Wygląd Wiersza danych (row heights Excel auto-fits, DATA as in the Plik zbiorczy), and that a Gotowość typed and saved in Excel reaches the Rozliczenia pracowników; use after changes to how workbooks are written or read, external links, Wyróżnienia, the Wzorce, or Gotowość. Local only, because it needs this Mac's Excel.
pilnuje:
  - src/rozliczenia/collective_layout.py
  - src/rozliczenia/workbook_files.py
  - src/rozliczenia/template_file.py
  - src/rozliczenia/workbook_save.py
  - src/rozliczenia/template_copy.py
  - src/rozliczenia/row_look.py
  - src/rozliczenia/workbook_parts.py
  - src/rozliczenia/highlights.py
  - src/rozliczenia/hyperlinks.py
  - src/rozliczenia/collective_file.py
  - src/rozliczenia/preparation_register.py
  - src/rozliczenia/register_columns.py
  - src/rozliczenia/preparation_files.py
  - src/rozliczenia/preparation_process.py
  - src/rozliczenia/quantity_engine.py
  - src/rozliczenia/quantity_rules_file.py
  - src/rozliczenia/reguly_ilosci_domyslne.yaml
  - src/rozliczenia/lista_urzadzen_domyslna.yaml
  - src/rozliczenia/engine.py
  - src/rozliczenia/inea_only_quantities.py
  - src/rozliczenia/period_folder.py
  - tools/lib/atrapy/scenariusz_rozliczen.py
  - tools/syntetyczne_wzorce.py
  - tools/lib/atrapy/wzorce.py
  - tools/lib/atrapy/pliki_taty.py
  - requirements.txt
---

# Verify skoroszyty w Excelu

Dad never sees a workbook through openpyxl: he opens the Plik zbiorczy in
Excel, types quantities and charges, saves, and later opens each Rozliczenie
pracownika. `verify-rozliczenia` proves the processes on file contents and
simulates Gotowość with openpyxl; this skill proves the same path in the real
Excel. Its failures are Excel's view: a repair dialog, a dropped link, a formula
showing `#N/D`, a Gotowość that Przebieg rozliczeń does not carry over.

Excel for Mac stands in for Dad's Excel for Windows. What it cannot prove:
Windows-only dialogs (Protected View, Windows links prompts), Dad's locale
parsing typed text (`25,5`), and his real Słownik behind the external link.
The Hiperłącza in `A:AT` (one on each `NUMER ZL.`) are checked in the bytes Excel saved and
Przebieg rozliczeń wrote, not as Excel shows them or opens them on a click.

## What CI runs and what stays local

CI runs only `check_excel_cleanup_mutations.py` (the mutations of the sweep and the quit), in full
CI on `main` and nightly on `main` (`mutacje-nocne.yml`). Everything else needs Excel on the Mac: drive it yourself whenever
`tools/skille_dla_zmiany.py` lists this skill.

## Launch

From the repository root, after `tools/setup_worktree.py` in a worktree:

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py
```

One command runs the whole path. It ends with `VERIFY OK | wzorce=prawdziwe |
steps=32 | … | scratch_removed=true | evidence_kept=true | evidence=<dir>`
(`steps=34` with `--kontrola-naprawy`). On Maks's Mac with Excel 16.114.1 it
took 1:14 with Dad's Wzorce and 1:55 with `syntetyczne` (2026-10-24).

- `--wzorce prawdziwe` (default) copies Dad's three Wzorce from `config/`, in a
  worktree from the main checkout's `config/` (`--templates-dir` overrides).
  Without all three it prints `VERIFY SKIP` and exits `3`: report it as a skip, never a proof.
- `--wzorce syntetyczne` builds Wzorce of Dad's shape with
  `tools/syntetyczne_wzorce.py`; use it when the real Wzorce are absent.
- `--kontrola-naprawy` adds `features/okno-naprawy.md`; it is the only step
  that needs a human click.

The Rejestr zleceń, Wykonawcy and orders are always the synthetic ones of
`verify-rozliczenia`'s `create_preparation_fixture.py`, so no customer data
enters a run; the runner and the doctor take the facts of that scenario from
`tools/lib/atrapy/scenariusz_rozliczen.py`, as `verify-rozliczenia` does.

Excel is a shared, single-instance app. Before it looks at Excel, the runner
locks `~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja/excel.lock`,
one lock for the whole Mac, so a run from any worktree refuses to start with
`VERIFY FAIL | ExcelBusy: … (pid <n>, <worktree>)` while another drives Excel.
The kernel drops the lock when its process ends, so a killed run blocks no
one. The runner starts Excel itself when Excel is not running (`excel.launch`)
and waits at most 90 s until Excel answers AppleScript and `pgrep -x` names its
one process. On Maks's Mac a start from a stopped Excel 16.114.3 took 1.4 to
2.4 s in 5 starts at a load average of 8.6 to 9.0 on 16 cores, its files already
in the system's cache, and a whole run from a stopped Excel took 0:50
(2026-11-02, #780). The id does not come from
`lsappinfo`: macOS 27.2 changed its output, and its old parser made every start
wait out the 90 s. At the end it
quits Excel whenever Excel holds no workbook, also an Excel that ran before the
run: one Excel process grows with every workbook it opened and closed (2.4 GB to
4.2 GB with no workbook open between 15:05 and 16:30 on 2026-10-24, after it hung
at about 10 GB that night). An Excel with any workbook (the user's) or a dialog
stays. Workbooks of the user stay untouched: every call addresses a workbook by
its full path on the desk.

### The desk

Every workbook Excel opens is a byte copy on the **desk**,
`~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja/<run>/`,
inside Excel's sandbox container. This is what makes the run need no human:

- a file outside the container opened from AppleScript waits on Excel's
  sandbox panel `Otwórz`;
- a file opened through Finder (`open -a`) asks `Ten skoroszyt zawiera linki
  do innych zewnętrznych źródeł danych…` with `Nie aktualizuj` / `Aktualizuj`;
- a file on the desk opened with `open workbook … update links do not update
  links` asks nothing.

The Plik zbiorczy saved by Excel on the desk is copied back into the Folder
okresu, so Przebieg rozliczeń reads exactly the bytes Excel wrote.

## Doctor

The runner runs the doctor after creating the fixture; its output is
`doctor.txt` in the evidence. To check by hand:

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel_doctor.py --root <run root> --desk <desk>
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py status
```

`DOCTOR OK` means: macOS, Python 3.13 or newer, Excel installed, Excel's
container exists, the desk is inside it and empty, the fixture has the Rejestr,
`wykonawcy.yaml` and `INEA`, both linked Wzorce have an external link used by a formula, the fixture
has no Folder okresu yet, and a running Excel answers AppleScript with no dialog
and holds no workbook named like this run's (Excel refuses two workbooks of the
same name). `excel.py status` is the read-only check of Excel alone.

`excel.py` names an AppleScript failure by its number. `-1743` raises
`ExcelNotPermitted`: macOS denies the app running the agent control of Excel,
and the run says so at once, also while it starts Excel. In System Settings →
Prywatność i ochrona → Automatyzacja, switch Microsoft Excel on for that app.
`-1708` and `-1712` raise `ExcelDialog`. When AppleScript gets no answer at
all (`-1712` even for Finder), macOS lost the Automatyzacja consent prompt;
the same setting fixes it.

## Drive

`run_excel_verification.py` runs, in order:

1. `tools/syntetyczne_wzorce.py` (only `syntetyczne`), then
   `create_preparation_fixture.py --with-worker-template --templates-from …`
   into `<run root>/okres`.
2. The doctor.
3. Przygotowanie pliku zbiorczego through `tools/uruchom_proces.py
   preparation` (JSON result, exit `2` Wymaga sprawdzenia: Przygotowanie ends a
   write so only for the Ilości usług warnings).
4. Both Wzorce opened in Excel as the reference: their link names and the R1C1
   formulas of `AU18:AY18`.
5. [Otwarcie plików okresu](features/otwarcie-plikow-okresu.md).
6. [Gotowość w Excelu](features/gotowosc-w-excelu.md).
7. Przebieg rozliczeń through `tools/uruchom_proces.py settlement` on the
   Plik zbiorczy Excel saved.
8. [Rozliczenia pracowników w Excelu](features/rozliczenia-pracownikow-w-excelu.md).
9. With `--kontrola-naprawy`, [Okno naprawy](features/okno-naprawy.md).

Each behaviour prints `STEP <feature> | <id> | OK`. The first failing check
ends the run with `VERIFY FAIL | <reason>`; the reason names the file, row and
column, never a value. `features/README.md` holds the feature map and its
conventions.

Drive Excel only through `scripts/excel.py`; it encodes the traps below.

- `tell wb to save` saves; `save wb` returns without error and saves nothing.
- AppleScript gives numbers in the system locale (`305,75`) and a formula
  error as an empty text: find errors with `special cells … value errors`
  (`excel.error_cells`), never by reading values.
- Every entry recalculates the whole workbook (some 50 000 formulas in Dad's
  Wzorce), so type one row per call (`excel.type_row`); typed cell by cell,
  the first row of the synthetic Wzorce ran past the 60 s call limit.
- While a dialog is up, Excel lists its workbooks as `missing value`
  (`excel.open_paths`) or fails a call with `-1708`, and both raise
  `ExcelDialog`; `excel.dialogs()` lists its untitled windows on screen,
  and none while Excel is hidden (Cmd+H). The titles need Screen Recording
  for the app running the agent: on macOS 10.15 and later, without it every
  window of Excel comes back untitled, so `dialogs()` would count each
  workbook window as a dialog. T3 Code has it on Maks's Mac
  (`CGPreflightScreenCaptureAccess()` true, 2026-10-24); a run without it is
  unchecked.

## Evidence

`<run dir>/evidence/excel-<id>/` survives cleanup (`--run-dir`, default
`.verification` of the checkout):

- `drive.txt`: every `STEP` line.
- `excel.json`: Excel version, which Wzorce, whether Excel ran before, per
  workbook the seconds to open and what it counted (links, rows, Wyróżnienia),
  the SHA-256 of the Plik zbiorczy Excel saved, and on failure its reason.
  Also Excel's memory (`excel_rss_mb_before`, `_end` just before the quit,
  `_after`, `null` when Excel is not running), its workbook count before and
  after, and what the start sweep closed (`stale_workbooks_closed`,
  `stale_desks_removed`).
- `przygotowanie.json`, `przebieg.json`: the process results of
  `tools/uruchom_proces.py`.
- `fixture.txt`, `doctor.txt` (and `wzorce.txt` for `syntetyczne`),
  `cleanup.txt`.

Evidence carries names, counts, addresses and timings; the runner fails when a
file of it holds a synthetic row marker. There are no screenshots: Excel's own
view is read through AppleScript instead.

## Cleanup

At its start, under the lock and before the doctor, the runner sweeps: it closes,
without saving, every workbook Excel holds below `maximiseart-weryfikacja/` and
removes every desk there but its own. Under the lock no other run is alive, so
these are left by runs killed before their `finally` (SIGKILL, a closed
session). Workbooks outside that folder are not touched. A dialog in Excel ends
the run here with `VERIFY FAIL | ExcelDialog …`, before it opens anything.

The runner's `finally` closes, without saving, every workbook on the desk, quits
Excel when it holds no workbook (`excel_quit=true`; Launch says when it stays),
removes the desk and the run root, writes `cleanup.txt`, and releases the lock;
evidence stays. If a dialog keeps Excel from closing and this run
started Excel, it stops that process by its id, then starts Excel once more and
quits it, so macOS does not reopen the run's windows at the next start. A dialog
in an Excel that was already running stays for its owner to answer
(`excel_dialog_left=true`), and so does one in the Excel this run started when
Excel names a workbook outside the run's desk (the user opened it during the
run). Behind a modal dialog Excel names no workbook, so then the run stops it
without knowing.

Excel may not answer the quit or the stop, for example because a dialog came up
after the check, an AppleEvent timed out (`-1712`), Excel refused it (`-1708`),
or Excel ended between the check and the stop. The cleanup then says
`excel_quit_failed=<exception type>` (the type only, not the AppleScript number)
and still writes the evidence and removes the desk and the run root by the rules
here. After a failed quit the run's workbooks are closed, so the note alone does
not fail the run. The Excel that stays is like one that holds a workbook of the
user (`excel_quit=false`). A failed stop comes with a dialog, so the cleanup
usually also says `close_failed` and the run ends `VERIFY FAIL`. The desk then
stays (`desk_kept`) while Excel still runs, as the next paragraph says, and goes
when Excel has ended.
Look at Excel. Answer a dialog if one is up, or quit Excel by hand, so it does
not grow from run to run. Only `tests/test_sprzatanie_excela.py` proves this
path; no real Excel failed its quit in a run yet.

While a dialog is up Excel cannot list its workbooks, so the cleanup cannot know
whether the run's workbooks are closed. It then says `close_failed=ExcelDialog`
and `desk_kept=<desk>`, keeps the desk under the workbooks Excel may still hold,
never reports `scratch_removed=true`, and the run ends `VERIFY FAIL`. Answer
the dialog in Excel; the next run's sweep closes those workbooks and removes the
desk. Proven in Excel 16.114.1 on 2026-10-24: a run killed by SIGKILL with
the Plik zbiorczy open left it and its desk; the next run reported
`stale_workbooks_closed=1`, `stale_desks_removed=1` and left an unsaved
workbook of the user open and unchanged. An Excel started with no workbook
ended `excel_quit=true`. Excel started by `open` (also `excel.launch`) holds
its blank `Zeszyt1`, which it replaces by the first workbook opened, so
`excel_workbooks_before=1` after such a start is no workbook of the user. This path (a dialog left in an Excel that ran before the run, e.g.
`--kontrola-naprawy` not answered in 10 minutes) is proven by
`tests/test_sprzatanie_excela.py` only, not in Excel yet: prove it at the next
`--kontrola-naprawy` with Maks at the Mac.

To clean up by hand without a run:

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py close-under --root ~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja
rm -rf ~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja/<run>
.venv/bin/python .agents/skills/verify-rozliczenia/scripts/cleanup.py --root <run dir>/runs/<run>
```

The sweep and the quit are guarded by mutations that CI runs on `main` and at night;
run them locally only to reproduce a red Mutation checks step or the night's issue
(a few seconds, it ends with `MUTACJE OK`):

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/check_excel_cleanup_mutations.py
```

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its
anchor so it breaks the same rule in the new code.

## Helpers

- `scripts/run_excel_verification.py`: the one-command runner (Launch).
- `scripts/excel_doctor.py --root <run root> --desk <desk>`: the read-only
  doctor.
- `scripts/excel.py status | close-under --root <dir>`: Excel's state, and
  closing stranded workbooks; as a module, every Excel call of the runner.
- `tests/test_weryfikacja_w_excelu.py`: the error naming, the start of Excel
  and the Mac-wide lock, with a fake `osascript`, `open` and `pgrep`; part of
  `pytest`, so no Excel is needed.
- `tests/test_sprzatanie_excela.py`: the start sweep, the cleanup under a
  dialog, the quit of an idle Excel and the memory in `excel.json`, with fake
  Excel calls; it runs on Windows too, for the mutation job.
- `scripts/check_excel_cleanup_mutations.py`: the mutations of the sweep and
  the cleanup (Cleanup).
- `scripts/excel_windows.js`: Excel's on-screen windows, run as
  `osascript -l JavaScript scripts/excel_windows.js`; a window without a title
  is a dialog, which holds only with Screen Recording (Drive).

Keep the feature map in step with what the runner checks; use
`/pstack:maintain-verification-skill` for that loop.
