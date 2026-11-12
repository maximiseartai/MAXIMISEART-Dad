# Coding Standards

Rules for writing and reviewing code and tests in a repository where agents write every line.
A rule that a check enforces sits in its section's table, one row per rule, beside the check that guards it, only when the check's message does not already say it; the reviewer does not repeat a check.
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

| Rule | Guard |
|---|---|
| An ADR number is unique and matches the file's heading. | `tests/test_adr.py` |

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
| Code outside `tests/` (`src/`, `tools/` with its libraries, CI scripts and hooks, skill scripts and the Python files in the root) never imports the package `tests`, because tools and skills change rarely and test files most often: the fakes of the outside world and Dad's synthetic files that tests share with tools and skills live in `tools/lib/atrapy/`, and `tests/fixtures` holds only helpers of tests, such as the operations that run a process (`tests/fixtures/operacje.py`). | `tests/test_granice_importow.py::test_kod_spoza_testow_nie_importuje_testow` catches exactly the forms listed in the docstring of `_tests_imports`, with no exceptions; a name or path built at run time, `spec_from_file_location`, `runpy`, `exec` and `sys.modules` only review |
| In `src/`, a signature names its type instead of `Any`: the concrete type, `object`, or a `TypeVar`. | ruff `ANN401` (`pyproject.toml`) |

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
| A refusal of a Centrum rozliczeń API request (`Refusal`: HTTP code and sentence for tata) is created only in the refusal catalog `src/rozliczenia/centrum/refusal.py`, and every public function of it has a sample in `tests/expected/komunikaty.txt`. | `test_odmowe_api_centrum_tworzy_tylko_katalog_odmow` and `test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu` in `tests/test_komunikaty_expect.py`: outside the catalog `Refusal` (by name, module import alias or module attribute) passes only as a type: a parameter, return, field or variable annotation, `[...]` of a generic and `|` union in a module or class statement outside a call or lambda (an alias such as `Callable[[], Refusal | None]`), `except`, the second argument of `isinstance`/`issubclass` and an argument of `exception_handler`; any other reference fails, including a call, an argument such as `partial(Refusal, 500)`, an assignment to a name (also local), a collection element, a default value, a base class, anything inside a call or lambda and `[...]` or `|` in a function body (`make = Refusal | Refusal`); mypy (the proof `refusal._CATALOG`, `@final`) also rejects a subclass and `type(refusal)(…)` without the proof, and ruff `TID251` the proof outside the catalog, except on a line with `# noqa: TID251`; `getattr` with a string, an import inside a function, `type(refusal)(…)` with a proof typed `Any` or imported with `# noqa: TID251`, a call of `_refused` imported with `# noqa: TID251`, `copy` of a ready refusal and a class taken out of a module type alias with no reference to `Refusal` at that place only review |
| A file or folder of Dad's in a bad state (corrupt, with a BOM, in UTF-16, without access) gives a Komunikat that names it, and a file without access is „niedostępny” in it, never „uszkodzony”: read a workbook through `file_bytes` (`workbook_files.py`), a file of Dad's through `DadFiles.read` (`dad_files.py`), and a period folder through `reading` (`period_folder.py`). | `tests/test_uszkodzone_wejscia.py`; ruff `TID251` (`src/ruff.toml`): an import or module attribute of `file_bytes`, `template_content` or `open_workbook` in `src/` outside `workbook_files.py` and lines with `# noqa: TID251 - <reason>`; `tests/test_jeden_odczyt_skoroszytu.py`: a call of `file_bytes`, `workbook_content`, `template_content` or `open_workbook` by name or import alias outside the places its `ONLY` and `EXCEPTIONS` list, also a call of a name imported with `# noqa: TID251`, which ruff does not see; a function taken into a variable by name, direct assignment, `patch.dict`, `getattr` with a string or a raw `open(path, "rb")` only review |
| Code in `src/` asks whether a file or folder is there only through `src/rozliczenia/file_state.py` (`file_state`, `path_state`, `path_taken`, `folder_entries` and `entry_kind` for its entries), the one owner of which file system error means absence and which means a file without access, because a bare `.exists()` or `.is_file()` raises `PermissionError` on Python 3.11–3.13 where the caller expects an answer and answers „missing” on 3.14 (#729, #1190). | `tests/test_zapadki.py::test_stan_pliku_w_src_tylko_przez_file_state` fails only on lines a change adds in `src/` outside `file_state.py`, runs on every `tools/szybko.py` (`ZAPADKI`) and not in CI, and catches only `.exists()`, `.is_file()` and `.is_dir()` without arguments and `os.path.exists`, `lexists`, `isfile` and `isdir`, as the docstring of `bare_file_state` lists; `.iterdir()`, `os.listdir`, `stat` with a hand-written `except OSError` and a method taken into a variable only review |
| Code in `src/` keeps the response of every navigation of a browser tab: the efenix window opens a page only through `BrowserEfenix._go`, waits for a reload only through `BrowserEfenix._reloaded` (`src/rozliczenia/efenix_browser.py`) and asks `_error_page` about a page it could not read, and only Przekazanie (`forward_to_accept`) drops the response of its reload. | `tests/test_zapadki.py::test_odpowiedz_nawigacji_karty_w_src_nie_jest_odrzucona` (boundary: docstring of `dropped_navigation`) |
| Code in `src/` does not `print`, because Dad never sees a console and a problem reaches him as a Komunikat; only `launcher.py` and `shortcut.py` print to the start console. | ruff `T201` (`per-file-ignores` in `pyproject.toml`) |
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
| Only `tests/conftest.py` puts `tools`, `tools/lib` and `tools/ci` on the `sys.path` of tests, and a test or fixture imports a tool from its own module (`import potomne`), never through a fixture that re-exports it nor by loading its file (`spec_from_file_location`), which gives a second copy of the module outside `sys.modules`. | ruff `TID251` (`tests/ruff.toml`): every use of `sys.path` in `tests/` outside lines with `# noqa: TID251 - <reason>`; `tests/test_struktura_testow.py::test_tylko_conftest_kladzie_narzedzia_na_sys_path_testow` catches exactly the forms listed in the docstring of `_tools_on_path`: a call whose name ends in `syspath_prepend` (path as the first argument or `path=`) or in `spec_from_file_location` (a `.py` file directly in `tools`, `tools/lib` or `tools/ci` as the second argument or `location=`), with the path from constant strings, names the module assigns at its level (also with an annotation) and positional arguments of calls; every other form only review, among them an insert in the code string of a subprocess, a path composed at run time, a call through a variable, a tool loaded by `runpy`, `exec` or a loader class and a re-export without an insert |
| A test, and a shared Atrapa in `tools/lib/atrapy`, substitutes the bytes of Dad's files through the byte source of `DadFiles`: in Centrum `create_app(source=...)` (`Surroundings(source=...)` in tests), in an engine test `RunContext(files=DadFiles(source=...))`, never by patching `workbook_files`. | `tests/test_jeden_odczyt_skoroszytu.py`: `setattr`, `delattr`, `patch`, `patch.object` and `patch.multiple` on the module named directly, through an import alias, as `rozliczenia.workbook_files` or as the string `"rozliczenia.workbook_files…"`; the module bound to a variable or through `importlib`, direct assignment to its attribute, an alias of the patcher (`patch as p`) and `patch.dict` only review |
| A test and a shared Atrapa in `tools/lib/atrapy` name a thread of the tool by its constant in `src/` (`QUEUE_THREAD`, `RUN_THREAD_PREFIX`), never by a copy of its text, so a renamed thread fails the test instead of leaving it waiting for nothing. | `tests/test_struktura_testow.py`: the values of the constants `*_THREAD` and `*_THREAD_PREFIX` of `src/` and the texts `name=` of `Thread(...)` and of `within(...)` (`centrum/deadline.py`) there, as a whole string outside docstrings, with exceptions in `NOT_THREADS`; a name composed at run time, a piece of an f-string and a part of a name only review |
| Git in tests has one configuration, the same on every computer: a test builds `env=` from `os.environ` and leaves `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM` alone, sets a computer configuration with something more through `computer_git_config` (`tests/fixtures/git_config.py`), and a process of the tool's code (`src/`) has an empty `user.name` and `user.email`, so its `git commit` fails as it does at Dad's. | fixture `git_bez_konfiguracji_komputera` in `tests/conftest.py`, `tests/test_git_w_testach.py` |
| A test checks that a text does not contain an order number or another value of Dad's only through `zawiera_wartosc` (`tests/fixtures/wyciek.py`), which asks the data rule's guard `ForbiddenValues.guard`, never with its own pattern around the number's digits, because four such patterns in a row disagreed with the guard and one turned `main` red when a random HMAC hex held the number. | `tests/test_zapadki.py::test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc` fails only on lines a change adds in `tests/` since the merge-base with `tools/szybko.py --baza`, runs on every `tools/szybko.py` (`ZAPADKI`) and not in CI, whose shallow checkout has no base, and catches only the text `(?<!` followed by an optional `[` and then `\d` with one backslash or `0-9`, as the docstring of `order_number_oracle` lists; `tests/test_struktura_testow.py::test_zapadki_nie_zglaszaja_zadnej_linii_testow` proves that no form of a zapadka hits a line of today's `tests/`; `"(?<!\\d)"`, a class such as `[a-f0-9]`, `\b` around a number, a number literal before `not in`, a number from a variable, `find`, `count` and a pattern built over several lines only review |
| A test asks about the threads of the pytest worker process only through `tests/fixtures/linie_watkow.py` (`new_line` and `threads_since` for the threads still alive, `started_threads` for the threads started in a block), never by comparing `threading.enumerate()` before and after or by replacing `threading.Thread.start` itself, because the worker also holds the threads of earlier tests and the pytest-timeout timer, which such a count took for the test's own (#495, #633, #1072). | ruff `TID251` (`tests/ruff.toml`): `threading.Thread.start` and `threading.active_count` in code of `tests/`, except on a line with `# noqa: TID251 - <reason>`; `tests/test_zapadki.py::test_watki_testu_tylko_przez_linie_watkow` fails only on lines a change adds in `tests/` outside `linie_watkow.py` and the ruff samples, runs on every `tools/szybko.py` (`ZAPADKI`) and not in CI, and catches only `active_count(`, `Thread.start` as a whole name and `Thread,` followed by the string `"start"`, as the docstring of `worker_threads` lists, also in a comment and in the code string of a child process; `threading.enumerate()` before and after (added without a FAIL round by #1297 and #1308, so a ratchet on it alarms on merged history), `threading._active`, a class in a variable, replacing `Thread.run` and a `setattr` call broken over several lines only review; the order of tests across CI parts (#575, #643) needs a test of the behaviour |

## Tools and Platforms

| Rule | Guard |
|---|---|
| The files that the system Python runs before `.venv` (the list in `per-file-target-version` in `pyproject.toml`) work under the Python 3.9 of macOS. | ruff `per-file-target-version`, `tests/test_systemowy_python.py` |
| Dependencies between `tools/` folders point one way: a tool in `tools/`, a module in `tools/lib/` and a hook never import a script from `tools/ci/` or put `tools/ci` on `sys.path`, and a module in `tools/lib/` never imports a tool from `tools/*.py` or puts `tools` on `sys.path`, so shared code lives in `tools/lib/`, a tool stays a thin command line over it, and a change to a workflow script or a tool's command line cannot break a library that other tools, skills and tests import (ADR 0022). | `tests/test_spis_narzedzi.py::test_narzedzie_biblioteka_ani_hook_nie_siega_do_skryptow_ci`; `tests/test_spis_narzedzi.py::test_biblioteka_narzedzi_nie_importuje_narzedzia_z_tools` catches exactly the forms listed in the docstring of `_library_reaches_tools`, and an import through the `tools` package (`import tools.X`, `from tools import X`), `importlib`, `runpy`, `spec_from_file_location` and a path built at run time only review |
| A script that a workflow runs with the runner's system `python3`, and everything it imports from `tools/`, uses only the standard library, because that interpreter has none of the project's dependencies. | `tests/test_spis_narzedzi.py::test_skrypt_workflow_na_systemowym_python3_importuje_tylko_biblioteke_standardowa` |
| A tool in `tools/` runs `gh` only through `gh` and `gh_bajty` of [`tools/lib/github.py`](tools/lib/github.py) (in the checkout, with a time limit, `gh` found on `PATH`), and the names it shares with CI (`REQUIRED`, the merge subjects `MERGE` and `SQUASH`) come from that module. | `tests/test_spis_narzedzi.py::test_narzedzie_uruchamia_gh_tylko_przez_github`; the shared names only review |
| A string that one CI tool writes and another reads is written in `tools/` and in skill scripts only by its owner, and every other module builds and parses it through the owner: the key of a plan unit (`pytest:`, `krok:`, `skill:`, `narzut:`, with a part `#k/n`) and the part variable `MUTACJE_CZESC` through `Klucz` and `Czesc` of [`tools/lib/jednostka.py`](tools/lib/jednostka.py), the start of a last line that another tool, a hook or CI reads (`MUTACJE OK`, `SKILLE VERIFY`, `AKTUALIZACJA:`, `CI LOKALNIE OK`/`FAIL`) through [`tools/lib/ostatnie_linie.py`](tools/lib/ostatnie_linie.py), and `MUTACJE ZMIANY OK` through `tools/mutacje_zmiany.py`, because a change of the string on one side alone left the other with a silent „nieznane” (the guard on main 2855f0215 found 98 copies in 16 files). | `tests/test_spis_narzedzi.py::test_kontrakt_napisow_miedzy_narzedziami_ci_ma_jednego_wlasciciela`; a string built at run time and a part `#k/n` glued to a key outside the owner only review |
| A tool whose parser requires a subcommand (`add_subparsers(required=True)`) names at least one of its subcommands in brackets in the first sentence of its docstring, the line the `## Narzędzia` block lists, as in `(plan --baza origin/main)`, because in the measurement of 30–31 October 2026 agents that knew the tool only from the list ran it without one, and a bare word does not tell the subcommand from the same Polish word in the sentence (ADR 0022). | `tests/test_spis_narzedzi.py::test_pierwsze_zdanie_narzedzia_z_obowiazkowa_podkomenda_ja_wymienia` |

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
| The UI never branches on a process name, outside the files `PROCESS_COMPARISON_FILES` lists with their reasons. | `npm run rules` (rule 2 in `frontend/scripts/rules.mjs`) in CI job `Frontend` |
| A text of the UI that a Komunikat quotes in „…” (a button tata must click, such as „Wyślij do Maksa”) stands as that text in its frontend file listed in `UI_TEXTS`, and every other quote of a Komunikat has its reason in `QUOTES_OUTSIDE_UI`, so a renamed button fails a test instead of leaving tata a Komunikat about a button that is gone. | `tests/test_komunikaty_expect.py::test_napis_przycisku_cytowany_w_komunikacie_stoi_w_ui_centrum`: quotes from the samples of every catalog, and the test fails when the file has the text in none of these forms: a JSX child, a `label="…"` or `label={"…"}` prop, or a `label: "…"` property, and a button text in another form (such as a branch of a condition) has its reason in `QUOTES_OUTSIDE_UI`; whether a match is really the text of a button (a heading or an example in a comment match too) and a quote only in a branch of a Komunikat that no sample reaches only review |

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
