# Centrum rozliczeń verification map

This directory is the maintained source for verifying what Dad can do in
Centrum rozliczeń. Read these conventions before driving, then use the
feature's own file as the recipe: the feature `<feature>` of `--feature` lives
in `<feature>.md` next to this file, driven by the skill's
`scripts/drive/<feature>.py`, whose module name has `_` for `-`.

## Baseline preconditions

- The built frontend in `src/rozliczenia/centrum/static/` matches `frontend/`
  (`npm run build` in `frontend/` after any frontend change).
- Playwright for Python and Chromium are installed, and on Windows `tzdata` (see `SKILL.md`, Launch).
- The computer may run in any time zone: a check of the screen counts dates in
  Dad's (`Europe/Warsaw`, the browser's), a check of the server's text in the computer's own.
- `run_centrum_verification.py` created a fresh run root with
  `create_centrum_fixture.py`, `serve_centrum.py` is serving it, and
  `centrum_doctor.py` reported `DOCTOR OK`.
- The fixture's "today" is Monday `2026-10-19`, so the last complete period is
  `06_12_10_2026`, whose Folder okresu does not exist. The folder okresów
  `INEA` holds `29_05_10_2026` (Plik zbiorczy przygotowany; its Plik zbiorczy
  has a Wykonawca missing from the Lista Wykonawców), `22_28_09_2026`
  (Rozliczenia pracowników gotowe, three files), `15_21_09_2026` (empty Folder
  okresu), and `Archiwum` (not a period).
- `<root>/Załączniki` holds Dad's layout for `uklad-folderow-taty`: weeks in
  `Rozliczenia 2026\{miesiąc}\INEA` of September, October, and November, with
  `06_12_10_2026` and `29_05_10_2026` prepared in October.
- `<root>/metrics/` holds both metrics files in the metrics schema: 18 valid
  synthetic Uruchomienia procesu (Przygotowanie pliku zbiorczego: 6 completed
  RUN, 1 RUN stopped in an old schema-1 record without its Rodzaj Zatrzymania,
  3 completed DRY-RUN; Przebieg rozliczeń: 5 completed RUN, one of them
  WYMAGA_SPRAWDZENIA, 1 RUN stopped „do Maksa” with `BLAD_NIEOCZEKIWANY`, 1 RUN
  stopped „dla taty” with `PLIK_ZBIORCZY_OTWARTY`, 1 DRY-RUN) and one record
  per file that the reader skips.
- The synthetic Rejestr zleceń has four orders in `06_12_10_2026`, the last on
  Saturday, so a RUN of Przygotowanie pliku zbiorczego asks about an
  incomplete period; its order cells carry the row marker.
  Centrum reads these, never the tool's own history.
- No settings are set when a run starts.
- Only for `wydajnosc`, the fixture is created with `--wariant rok-pracy`: `<root>/Rok pracy/Załączniki` holds 52 periods in Dad's layout and the metrics files hold a year of records (see `wydajnosc.md`).
- `<root>/aktualizacja/` holds the run's tool for `aktualizacja`: a clone (`klon`) on the first synthetic commit, with Dad's files in its `config/`, and a bare local "origin" (`origin.git`) one commit ahead that stops tracking his changed old Wykonawcy file (`worker_mapping.yaml`), plus a branch `biblioteki` one commit later that needs a library pip cannot install offline and a branch `nie-startuje` whose Centrum does not start. Centrum's own commit is the clone's `HEAD`, and Aktualizacja narzędzia moves only this clone. The clone's `run_centrum.py` serves the run's scripted Centrum, so the Centrum the restart guardian starts after an update is again this run's.
- The run's `config/` holds a synthetic Lista Wykonawców `wykonawcy.yaml` (three Wykonawcy)
  and the three Wzorce, valid for the engine's Sprawdzanie; the configuration read of Ustawienia reads
  these, never Dad's `config/`.

## Driving conventions

- Drive through the browser with `drive_centrum.py`. Find elements by ARIA role
  and accessible name; the names are Polish UI text, so copy them exactly
  (`exact=True`: Playwright otherwise matches case-insensitive substrings, and
  `Wskaż folder okresów` differs from `Wskaż Folder okresów` only in case).
- Open the window Ustawienia with `open_settings` (`drive/common.py`), point a file with `point_in_settings` and close the
  window with `close_settings`: the window is a modal, so the menu and the page under it take no click while it is open.
- Name a period in combobox `Okres` with `period_choice` (`drive/common.py`): its days from the token, its Status okresu, and the token, as in `wt 06.10 – pon 12.10 · ostatni pełny · 06_12_10_2026`.
- Answer a native picker by writing the path to `<root>/picker/answer.txt`
  before the click. Leave the file absent to cancel.
- Read side effects from the run root: `config/centrum-ustawienia.yaml`,
  `dialogs.jsonl`, `opened.jsonl`, and `logs/uruchomienia/`.
- The harness of `drive/common.py` is the one way for what more than one feature does:
  close, start and kill Centrum (`close_centrum`, `start_centrum`, `kill_centrum`, `answers`);
  read any file (`read_text`, `read_bytes`, `read_json`), which wait while the server puts it in place on Windows (#1087), and `centrum_self_test.py` fails on any other `read_text` or `read_bytes` in `drive/` (`_direct_reads`);
  read the skrzynka Zgłoszeń and its queue (`box_issues`, `queued`, `queued_posts`);
  read the Centrum log (`Run.log`, `Run.log_entries`, `log_entries`);
  send a POST as the tab does (`Run.post`; a foreign `Origin` or `Host` goes through `Run.refused`);
  move Centrum's clock (`advance_clock`), which fails, as a wait that times out does, once the clock's wake-up thread has died (`check_clock_alarm`);
  open a second window like Dad's (`dad_tab`);
  reach the start card after a reload (`open_setup`);
  and wait for the result of an Uruchomienie Dad starts (`result_of_start`, `run_again` for `Uruchom ponownie`), because the server shows the previous one as finished until the tab's request arrives.
  Wait for the server's answer to a page's read (`reload_with_answer`) instead of a longer timeout when the page shows it.
- Change files on disk only inside the run root, and restore what a step moved.
  Delete, move and replace files and folders only with `remove`, `remove_tree`, `remove_empty_folder`, `move` and
  `replace_file` (`drive/common.py`), which retry while the server holds the file open: on Windows that refuses the
  change (`WinError 32`, #921).
  `centrum_self_test.py` fails on a drive that does it otherwise in a form of the table in
  [Guard of deletions in the drive](#guard-of-deletions-in-the-drive), and review checks the guard's boundary (#934).
  Take the key away with `drop_report_key`, which leaves the file empty and, without `missing_ok`,
  fails when the step never wrote a key.
- Capture with `Run.capture`, which waits for running transitions; a screenshot
  taken mid-transition shows content at partial opacity. A close-up is
  `Run.capture` with `clip`, so its number is checked like every other one;
  `tests/test_limit_drive_centrum.py` fails on any other `screenshot`
  call in `drive/`.

### Guard of deletions in the drive

`centrum_self_test.py` reads every `drive/*.py`, except the bodies of the five helpers above in `common.py`, and
fails on each deletion, move or replacement of a file or folder in these forms (the docstring of `_removals` has
the same tables, and the self-test fails when they differ).
Ruff `TID251` (`drive/ruff.toml`) already rejects each name it resolves to a deletion or move of `os`, `shutil` or a
pathlib class (`os.remove`, `import os as system; system.replace(p, q)`, `from shutil import rmtree`,
`Path.replace(p, q)`); `common.py`, whose helpers own these names, has `TID251` in `per-file-ignores` of `pyproject.toml`.
The guard catches only the forms ruff cannot resolve, and knows a module only by a name an `import` binds, never by
an assignment.

| Form | The guard catches | Example |
|---|---|---|
| 1 | an attribute `unlink`, `rename`, `rmdir`, `rmtree`, `removedirs`, `renames` or `move_into` on anything, called or not | `p.unlink(missing_ok=True)`, `p.rename(target=q)`, `os.renames(p, q)`, `shutil.rmtree(p)`, `drop = Path.unlink`, `fs = os; fs.unlink(p)` |
| 2 | a call `x.replace(…)` or `x.move(…)` with one positional argument and no named one, or with only `target=`, where `x` is not a name that an `import` binds | `p.replace(q)`, `p.move(target=q)`, `Path(p).replace(q)` |
| 3 | `getattr(x, "<name>", …)` with a constant name of form 1, `remove`, `replace` or `move` | `getattr(p, "unlink")()`, `getattr(os, "remove")(p)` |

Its boundary, which review checks:

| Boundary | Passes the guard |
|---|---|
| a module or pathlib class through a name that no import binds (forms 1 and 2 still catch on it) | `fs = os; fs.remove(p)`, `s: ModuleType = os; s.replace(p, q)`, `Q = Path; Q.replace(p, q)`, `self.files = shutil` |
| `replace` or `move` of an object kept or passed instead of called (form 2 takes only a call) | `swap = p.replace; swap(q)`, `retry(p.move, q)` |
| a call of form 2 with unpacked arguments | `p.replace(*args)`, `p.move(**named)` |
| a call of form 2 on a name that an `import` in the file also binds | `import time` and elsewhere `time = p; time.replace(q)` |
| a pathlib class from an expression | `type(p).replace(p, q)`, `p.__class__.move(p, q)` |
| another module | `posix`, `nt`, `_winapi`, `ctypes` |
| a name computed at run time, or a name in a string outside `getattr` | `getattr(p, name)`, `operator.methodcaller("unlink")`, `vars(os)["remove"]`, `sys.modules["os"]`, `importlib`, `__import__`, `eval` |
| another process | `subprocess` with `rm`, `del`, `Remove-Item` or `move`, `os.system` |
| no deletion or move | a copy onto a file the server reads (`shutil.copy2`, `copyfile`, `copytree(…, dirs_exist_ok=True)`), a write (`open(p, "w")`, `write_bytes`, `workbook.save`), `tempfile` cleanup |
| code outside `drive/*.py` | `drive_centrum.py`, `create_centrum_fixture.py`, `serve_centrum.py` |

A false alarm is loud and names the helpers: form 1 on an object that is no file (`frame.rename(columns=…)`),
form 2 on any object with a one-argument `replace` or `move` (`moment.replace(2026)`), form 3 on any object.

## Slow runner mode

`run_centrum_verification.py --wolny-runner --feature <feature>` drives as a slow CI runner would, with delays
injected instead of load, so a check that depends on time fails on every run (#1539):

| Delay | Value | Owner | Class it shows |
|---|---|---|---|
| animations of every page of `dad_context` (CDP `Animation.setPlaybackRate`) | `SLOW_ANIMATIONS` 0.2 | `drive/common.py` | a check of a state visible for a moment (#1534) |
| each write (`fetch` other than GET) of the tab leaves it late | `LATE_WRITE_MS` 1500 | `drive/waiting.py`, put into the tab by `dad_context` of `drive/common.py` | a read right after a click, before its request arrives (#1570) |
| each request of `/api/` waits before Centrum takes it | `API_DELAY_S` 0.3 | `serve_centrum.py` | a fixed sleep or limit shorter than the server's answer |

Every delay stays inside the drive's budgets (`drive/waiting.py`): a wait or an assertion on a condition passes, a single read or a fixed sleep does not.
The drive waits for a condition only through `until` of `drive/waiting.py`, for the screen through its `expect`, and lets the page run through `quiet_for`.
No other way to wait for a condition is left to copy (`Run.wait_for` is gone, #1539). Ruff refuses `time.sleep` outside `drive/waiting.py` and `drive/common.py`, in `drive/common.py` the test of `OWNERS` in `tests/test_zakazy_ruff.py` does, and `page.wait_for_timeout` passes both (`ZNANE_LUKI_SNU`); a new function that wraps `until` around a condition it takes, nothing refuses today.
The drive stops at its first failure, so drive one feature per run to find each failing place.
The mode is a manual proof and runs neither in CI nor at night.

## Proof and skip reporting

- Every step records its action, the screen (`screenshots/`, `aria/`), the
  server's answer (`api/`), and the side effect on disk (`state/`, checks in
  `drive.txt`).
- Report a feature as verified only when its steps ran in this run. A feature
  left out with `--feature` is a skip; report it as one.
- `VERIFY FAIL` keeps `screenshots/zz-failure.png` and the evidence of every
  step before the failure.
- Evidence contains synthetic paths only; workbook content never appears.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible
behaviour, then exactly these H2s in order:

1. `Sub-features`: short IDs with one line each; the IDs match the
   `STEP <feature> | <id>` lines in `drive.txt`, and a section that names
   `scripts/sub_features.py --feature <feature>` is that command's output, which `tests/test_mapy_funkcji.py` compares.
   The command reads only `run.step(feature, "<id>")` and `run.check(condition, message)`
   called in the body of `drive(run, page)`. It refuses, with the file and the line,
   every other form of them and every other `.step` or `.check` attribute in the
   module, on whatever object. It does not see a check reached without such an
   attribute, as `getattr(run, "check")`. A field of an f-string message prints
   as `…`, except a module constant, which prints its value. A line with the ID
   alone is a step without its own `run.check`: what it waits for (`until`,
   `expect`) stands in the drive, and the file's opening paragraph says it for Dad.
2. `How to get to it (user POV)`: every entry point Dad has.
3. `Driving it with Playwright for Python`: the one command that drives the
   feature and where its proof stands in the evidence. A file whose
   `Sub-features` is not yet the command's output keeps `Preconditions:` and
   labelled bullets pairing each action with the exact handle and the
   observable result, until #1629 and #1630 move it.
4. `Gotchas`: traps that waste or invalidate a run.

When a slice adds a feature, add its file in this directory, its module in
`scripts/drive/` with `drive(run, page)`, and its `Feature` (screenshots,
`needs`) in `FEATURES` of `scripts/drive/__init__.py`, in the same PR. This
file lists no features: `tests/test_mapy_funkcji.py` matches the feature files
with `FEATURES` in both directions.
