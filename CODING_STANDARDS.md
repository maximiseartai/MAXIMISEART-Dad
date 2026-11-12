# Coding Standards

Rules for writing and reviewing code and tests in a repository where agents write every line.
A rule that a check enforces sits in its section's table, one row per rule, beside the check that guards it, only when the check's message does not already say it or the check misses forms that review must catch (its docstring names them); the reviewer does not repeat a check.
A bullet is a judgement call that no check makes: the reviewer reports a broken bullet as Drobne, and as Ważne only with the behaviour defect it causes, proved as the skill [`przeglad`](.agents/skills/przeglad/SKILL.md) asks.

## Fixing a Mistake Class

A mistake is a class once it has happened twice: two review findings, two red runs, or a correction from Maks that repeats an earlier one.
Fix a class at the highest rung of the ladder (a)–(d) in `AGENTS.md` that works, and say in the PR why a higher rung did not.
Turn a ruff or mypy rule on when it has no violation left, like the rules under `# Zapadki` in `pyproject.toml`.
A ratchet in `tests/test_zapadki.py`, only for a pattern that is already common, states its literal boundary in its docstring and raises nothing on the whole tree.
A new check fails on the commit of the PR whose review found the mistake, raises no false alarm on a few recent merged PRs (`--ostatnie 5`, one of them with Windows-only code), and the PR body shows both runs (`tools/na_scalonych_pr.py`, skill `pr`).
Fix the class, not the instance: when a review finds one case, look for every case of the same fault in the change and in the repository, and fix them together.
When a fix of a rule keeps growing a list of exceptions, replace the list with the shape the code accepts.

## Domain Language

- Name tests after the domain behaviour they protect, in the terms of `GLOSSARY.md`.
  Use an implementation name only when the test intentionally protects that module's interface.
- Write identifiers in `src/` in English, and docstrings, test names and every text tata or Maks reads in Polish, with the terms of `GLOSSARY.md` and no synonym of a defined term.

## Design

- Give each decision one owner: a rule, a limit or a mapping lives in one module, and every caller asks that module instead of keeping its own copy, which drifts.
- Keep a coordinator responsible for sequencing, not for the details of the workbook it coordinates.
- A module with one main operation exposes that operation as its seam and keeps layout constants and helper functions private, so callers do not know how a workbook is loaded, repaired, or saved atomically.
- Model a domain variation as data: a new case is a new member of an Enum, a row of a table or a variant of a union, not one more branch in an `if` chain repeated across files.
- Read text the program did not write (a shell command, Markdown, HTML, a cell of Dad's file) with a real parser or the tool that owns the format, such as `gh api markdown` for GitHub Markdown, and accept only the forms the code lists: an unknown form fails closed.
  Hand-written parsers that grew by listing bad forms failed review 15 times on 7 PRs in October 2026 (#496, #624, #636, #648).
- A gate or a checker passes only on the result it expects: it lists the units it must see, and a missing unit, a crash or any other outcome is a failure (#445, #479, #554, #667).
- A best-effort step (a cleanup, a kill with a deadline, a notification) returns and records its failure, and never raises into its caller (#447, fixed in #458).
- When a change adds a new way to do something, it moves every caller to it and deletes the old way.

| Rule | Guard |
|---|---|
| The import graph of `src/`, tools, tests and skill scripts keeps the boundaries listed in the docstring of its guard: the engine never imports Centrum rozliczeń, the process core never reaches the workbook layer, and only `Catalog.prepared` builds a `PreparedRun`. | `tests/test_granice_importow.py` |
| Code outside `tests/` (`src/`, `tools/` with its libraries, CI scripts and hooks, skill scripts and the Python files in the root) never imports the package `tests`. | `tests/test_granice_importow.py::test_kod_spoza_testow_nie_importuje_testow` (boundary: docstring of `_tests_imports`) |

## Error Ownership

- Workbook code (`workbook_files`, `template_file`) raises `WorkbookError`, and the catalog of the process that called it translates the error into a Komunikat.
  The files that Sprawdzanie reads go through `input_checks`, which translates their reader errors once for both processes, the Diagnoza and the Konfiguracja; the Rejestr zleceń of the Przygotowanie goes through `preparation_register`, which reads it once for the Sprawdzanie, the Odczyt danych and the Diagnoza.
  A catalog gives `workbook_messages.unusable` a `WorkbookMessages`, one Komunikat for each `Problem`, so a new `Problem` is a new field that mypy asks of every catalog, and the one `match` on `Problem` ends with `assert_never`.
  The sentences about Dad's file open in Excel, its Excel lock file `~$…` and a file OneDrive has not handed over come only from `workbook_messages`.
  Other code calls its catalog's factories directly, and a process summary reports its problems as warning Komunikaty in `warnings`.
- A failure that can invalidate a workbook write, reading or restoring `xl/externalLinks/*` included, raises `WorkbookSaveError` with its `SaveProblem` (`workbook_save.py`), not a generic error.
- Preserve `Nienadpisywanie`: existing input data is reported and never replaced automatically.
- Pass `check=True` to `subprocess.run` unless the code after it reads `returncode`, and never write `check=False` only to silence ruff's PLW1510.

| Rule | Guard |
|---|---|
| A refusal of a Centrum rozliczeń API request (`Refusal`) is created only in the refusal catalog `src/rozliczenia/centrum/refusal.py`, and every public function of it has a sample. | `test_odmowe_api_centrum_tworzy_tylko_katalog_odmow` and `test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu` in `tests/test_komunikaty_expect.py`, mypy and ruff `TID251` on the proof `refusal._CATALOG` (boundary: docstrings of the first test and of `_CATALOG`) |
| A file or folder of Dad's in a bad state (corrupt, with a BOM, in UTF-16, without access) gives a Komunikat that names it, and a file without access is „niedostępny” in it, never „uszkodzony”: read a workbook through `file_bytes`, a file of Dad's through `DadFiles.read`, and a period folder through `reading`. | `tests/test_uszkodzone_wejscia.py`, ruff `TID251` (`src/ruff.toml`), `tests/test_jeden_odczyt_skoroszytu.py` (boundary: its module docstring) |
| Code in `src/` asks whether a file or folder is there only through `src/rozliczenia/file_state.py`. | `tests/test_zapadki.py::test_stan_pliku_w_src_tylko_przez_file_state` (boundary: docstring of `bare_file_state`) |
| Code in `src/` keeps the response of every navigation of a browser tab. | `tests/test_zapadki.py::test_odpowiedz_nawigacji_karty_w_src_nie_jest_odrzucona` (boundary: docstring of `dropped_navigation`) |
| `zip` takes `strict=True` when both sides must have the same length, `strict=False` only with a comment naming the check that already reports a different length, and successive pairs come from `itertools.pairwise`. | ruff `B905`, `RUF007` |

## Test Surface

- Judge a test by two edits: break the behaviour it names and it fails, restructure the internals with the same observable result and it passes.
  Take the expected value from `GLOSSARY.md`, the ADR or the requirement, never from a run of the code under test.
- Test each process through its operation (`run_settlements()`, `prepare_collective_file()`, `order_register()`).
  Give a module with one entry point (one operation or the HTTP API of Centrum rozliczeń) its own tests only for behaviour that entry point cannot reach.
- A module whose interface at least two entry points call (two processes, or a process and Centrum rozliczeń) is a seam: test its rule matrix once, on its interface.
  Each entry point that uses it has one translation test (module error → that entry point's Komunikat) and does not repeat the matrix.
- Test a decision of Wycena w efenix (the execution date, Wycena Emmetta, the completion to the file, the checks of an order, a new Uruchomienie after Dad's change) through the Uruchomienie procesu on the window in process (`_run_in_process` in `tests/test_wycena_efenix.py`, `tests/fixtures/okno_w_procesie.py`), without a browser.
  Keep in Chromium on the Atrapa efenix what only the browser window shows (the page and its build, a failure, a closed window, login, pace) and a few decision runs as smoke tests.
  The window contract in `tests/test_atrapa_efenix.py` shows that both windows give the same run only on its rows, so a new branch of the window in process gets its row there.
- Test Centrum rozliczeń through its HTTP API, the way the browser sees it: responses, the event stream, files on disk, metrics records.
  Prove UI behaviour in the browser with `verify-centrum-rozliczen`, not with component unit tests.
- Make the Rejestr zleceń or a Wzorzec fail in a test through a failing adapter, not by patching a module attribute: the byte source of Dad's files (`DadFiles.source`, in Centrum `create_app(source=...)`) for the Rejestr, the Sprawdzanie of a Wzorzec (`run_context.TemplateCheck`, in Centrum `create_app(template_check=...)`) for a Wzorzec.
  The same adapters reach the Uruchomienie procesu, the Diagnoza and the Konfiguracja, so the fault reaches all three.
- Use synthetic workbook fixtures only, shaped like Dad's real file in what the code reads (a row's style, a merged cell, the format Excel shows), not only in its values.
  Cover both successful and failure paths for each operation's behaviour matrix.
- The test that owns a workbook write verifies every column the write touches (`A:AT` for the Rozliczenie pracownika), preserved formulas and formatting, atomic replacement, and every entry under `xl/externalLinks/*`.
  Other tests assert only the behaviour they name.
- Before a change runs on real files, run the Przygotowanie pliku zbiorczego and the Przebieg rozliczeń as `Podgląd bez zapisu`; Uporządkowanie INTERMAX has no preview and saves a Kopia INTERMAX before it replaces the file.
- Keep tests free of client addresses, order numbers, and row contents in output or logs.
  The one exception is the Zatrzymanie about gaps in `SKUTECZNE` (`ZLE_SKUTECZNE`, ADR 0004): its tests use synthetic `SKUTECZNE` values, because the Komunikat shows the exact cell content.
- Name a file that a test reads or runs with a literal path (`ROOT / "docs" / "adr"`), not a path built from a variable.
  `tools/szybko.py` selects tests from imports and such literals, so a path built at run time hides the dependency.
- Test a rule that matches text from Dad's files (a word or phrase in `URZĄDZENIA` or `CZYNNOŚCI`, an operator name, a period token) with a Hypothesis property, not only with examples: the text anywhere in the cell, glued to punctuation, in any letter case and with Polish letters, two words of the rule in one cell, and the word inside a longer word.
  Take the expected result from `GLOSSARY.md`, the ADR or the docstring, and keep the examples deterministic with `derandomize=True` and `database=None`, as `tests/test_wlasnosci_dopasowania_tekstu.py` does.
- A test leaves no thread, process, lock or open file behind, and passes alone and in any order, because the xdist shards on the Mac and in CI hold different neighbours.
- A test holds on Windows and on Python 3.11: `time.monotonic()` on Windows under Python 3.11 advances in steps of about 15.6 ms, a Windows path inside JSON escapes its backslashes, and the Windows console encodes in cp1252.
- A refactor that splits a shared path gives each new branch a test that fails when that branch breaks, because tests that reached it only through the old shared path stop covering it without failing.
- Prove that a new test or check fails on the broken code it guards with `tools/mutacje.py`, the command line of the repository's one mutation engine (`tools/lib/silnik_mutacji.py`): use it rather than writing another.
  Run it once for each test or check added or changed in a round of work.
  A rebase, or a fix that leaves the test unchanged, does not need a new run.

| Rule | Guard |
|---|---|
| Only `tests/conftest.py` puts `tools`, `tools/lib` and `tools/ci` on the `sys.path` of tests, and a test or fixture imports a tool from its own module. | ruff `TID251` (`tests/ruff.toml`), `tests/test_struktura_testow.py::test_tylko_conftest_kladzie_narzedzia_na_sys_path_testow` (boundary: docstring of `_tools_on_path`) |
| A test, and a shared Atrapa in `tools/lib/atrapy`, substitutes the bytes of Dad's files through the byte source of `DadFiles`, never by patching `workbook_files`. | `tests/test_jeden_odczyt_skoroszytu.py` (boundary: its module docstring) |
| A test and a shared Atrapa in `tools/lib/atrapy` name a thread of the tool by its constant in `src/`, never by a copy of its text. | `tests/test_struktura_testow.py::test_testy_i_atrapy_nazywaja_watek_narzedzia_stala_a_nie_kopia_jego_nazwy` (boundary: its docstring) |
| A test checks that a text does not contain an order number or another value of Dad's only through `zawiera_wartosc` (`tests/fixtures/wyciek.py`). | `tests/test_zapadki.py::test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc` (boundary: docstring of `order_number_oracle`) |
| A test asks about the threads of the pytest worker process only through `tests/fixtures/linie_watkow.py`. | ruff `TID251` (`tests/ruff.toml`), `tests/test_zapadki.py::test_watki_testu_tylko_przez_linie_watkow` (boundary: docstring of `worker_threads`); the order of tests across CI parts (#575, #643) needs a test of the behaviour |

## Tools and Platforms

| Rule | Guard |
|---|---|
| The files that the system Python runs before `.venv` (the list in `per-file-target-version` in `pyproject.toml`) work under the Python 3.9 of macOS. | ruff `per-file-target-version`, `tests/test_systemowy_python.py` |
| Dependencies between `tools/` folders point one way: a tool, a module in `tools/lib/` and a hook never reach a script of `tools/ci/`, and a module in `tools/lib/` never reaches a tool from `tools/*.py` (ADR 0022). | `tests/test_spis_narzedzi.py::test_narzedzie_biblioteka_ani_hook_nie_siega_do_skryptow_ci`, `tests/test_spis_narzedzi.py::test_biblioteka_narzedzi_nie_importuje_narzedzia_z_tools` (boundary: docstring of `_library_reaches_tools`) |
| A tool in `tools/` runs `gh` only through `gh` and `gh_bajty` of [`tools/lib/github.py`](tools/lib/github.py), and the names it shares with CI (`REQUIRED`, `MERGE`, `SQUASH`) come from that module. | `tests/test_spis_narzedzi.py::test_narzedzie_uruchamia_gh_tylko_przez_github`; the shared names only review |
| A string that one CI tool writes and another reads is written in `tools/` and in skill scripts only by its owner. | `tests/test_spis_narzedzi.py::test_kontrakt_napisow_miedzy_narzedziami_ci_ma_jednego_wlasciciela` (boundary: its docstring) |

## Frontend

- The browser holds no domain logic: it displays what the server returns and sends tata's choices back.
  A rule needed in the UI belongs in the engine.
- Change the contract on the server, and keep hand-written types for the UI's own state only: the states of an Uruchomienie procesu come from the contract's `RunView` union (`frontend/src/api/centrum.ts`).
- Use components from the official `@shadcn` registry and semantic theme tokens.
  Write all UI text in Polish, in the vocabulary of `GLOSSARY.md` and the user guide.
- Take limits and value sets shared with the server from the generated schemas, never from a repeated literal.
  Key a cache or a remount by exactly the fields whose change requires a new read (tata's files, not the theme).
- Build new UI to the accepted [v3 brief](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/90#issuecomment-6257321289) with the `emil-design-eng` skill.

| Rule | Guard |
|---|---|
| The UI never branches on a process name, outside the files `PROCESS_COMPARISON_FILES` lists with their reasons. | `npm run rules` (boundary: comment of rule 2 in `frontend/scripts/rules.mjs`) |
| A text of the UI that a Komunikat quotes in „…” stands as that text in its frontend file listed in `UI_TEXTS`, and every other quote of a Komunikat has its reason in `QUOTES_OUTSIDE_UI`. | `tests/test_komunikaty_expect.py::test_napis_przycisku_cytowany_w_komunikacie_stoi_w_ui_centrum` (boundary: its docstring) |

## Documents and Claims

- A docstring, `--help`, ADR, `SKILL.md` or document states what the code does now, and only what a check or a run shows: a number names the run or the command it came from.
- A change that makes a sentence of `AGENTS.md`, this file, `GLOSSARY.md`, a skill or an ADR untrue fixes that sentence in the same change.

## Review Context

- Treat ADR 0001 as the constraint that Python remains the single source of settlement rules, with no VBA adapter (ADR 0011).
- Treat ADR 0004 as the constraint that Centrum rozliczeń is an adapter of Uruchomienie procesu, not a second process: it talks to the same core as the Skrypt dla maszyn, keeps no rules of its own, renders only the progress projection's snapshots and the process's shared messages as three-part structures.
  Review every Centrum change for localhost-only listening, `Host`/`Origin` checks, and file actions limited to paths the server derived from the periods folder.
- E2E, the timing guard and the benchmark run the processes through the Skrypt dla maszyn `tools/uruchom_proces.py`, which uses the same core as Centrum rozliczeń and prints the Centrum contract as JSON.

| Rule | Guard |
|---|---|
| A TODO, FIXME, XXX or HACK is finished in the same change or named in the report for Maks, never left in the code. | ruff `FIX001`–`FIX004` |
