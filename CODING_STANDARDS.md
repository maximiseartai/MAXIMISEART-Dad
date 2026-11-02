# Coding Standards

Rules for writing and reviewing code and tests in a repository where agents write every line.
A rule that a check enforces sits in its section's table, one row per rule, beside the check that guards it: the reviewer does not repeat that check.
A bullet is a judgement call that no check makes: the reviewer reports a broken bullet as Drobne, and as Ważne only with the behaviour defect it causes, proved as the skill [`przeglad`](.agents/skills/przeglad/SKILL.md) asks.

## Fixing a Mistake Class

A mistake is a class once it has happened twice: two review findings, two red runs, or a correction from Maks that repeats an earlier one.
Fix a class at the highest level that works, and say in the PR why a higher level did not:

1. Architecture: one owner for each decision and one supported way for each task, internals hidden so the wrong import fails, and the old way deleted so no agent copies it.
2. A type, a lint rule or a structure test whose error names the file, type or function to use instead.
   Turn a rule on when it has no violation left, like the Zapadki in `pyproject.toml`, and when the pattern is already common, fail only when a change adds more.
3. A test of the behaviour.
4. A bullet in this file, last, because nothing fails when an agent skips it.

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
| A concept retired by an ADR (CLI, terminal, Rich, `run.py`, Dad's `.cmd` launchers) stays retired. | `tests/test_wycofane_pojecia.py` |

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
| The engine (`src/rozliczenia/*.py`) never imports Centrum rozliczeń, the modules in `STDLIB_ONLY` import only the standard library and each other when loaded, and the modules of the restart guardian's copy (`_COPIED` in `restart_guardian.py`) import only the standard library and `_COPIED`. | `tests/test_granice_importow.py` |
| A `match` handles every variant of its subject or ends with `case _`, a condition is never a value that is always true (an Enum member, a `Path`, a dataclass, an `Iterable`), and a `# type: ignore` names its error code. | mypy codes `exhaustive-match`, `truthy-bool`, `truthy-iterable` and `ignore-without-code` (`enable_error_code` in `pyproject.toml`), for both systems in `tools/ci_lokalnie.py` |
| In `src/`, a signature names its type instead of `Any`: the concrete type, `object`, or a `TypeVar`. | ruff `ANN401` (`pyproject.toml`) |

## Error Ownership

- Workbook code (`workbook_files`, `template_file`) raises `WorkbookError`, and the catalog of the process that called it translates the error into a Komunikat.
  The files that Sprawdzanie reads go through `input_checks`, which translates their reader errors once for both processes, the Diagnoza and the Konfiguracja.
  `preparation_messages` ends its `match` on `Problem` with `assert_never`, so mypy rejects a new `Problem` until it is handled.
  Other code calls its catalog's factories directly, and a process summary reports its problems as warning Komunikaty in `warnings`.
- A failure that can invalidate a workbook write, reading or restoring `xl/externalLinks/*` included, raises `WorkbookSaveError` with its `SaveProblem` (`workbook_save.py`), not a generic error.
- Preserve `Nienadpisywanie`: existing input data is reported and never replaced automatically.
- Pass `check=True` to `subprocess.run` unless the code after it reads `returncode`, and never write `check=False` only to silence ruff's PLW1510.

| Rule | Guard |
|---|---|
| A Komunikat is created only in a catalog module listed in `CATALOGS` or `OUTSIDE_CATALOGS` (`tests/test_komunikaty_expect.py`), and every public function of a catalog has a sample in `tests/expected/komunikaty.txt`. | `test_kazde_miejsce_tworzace_komunikat_ma_probke_w_pliku_expect` and `test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu` in `tests/test_komunikaty_expect.py` |
| A file or folder of Dad's in a bad state (corrupt, with a BOM, in UTF-16, without access) gives a Komunikat that names it, and a file without access is „niedostępny” in it, never „uszkodzony”: read a workbook through `_file_bytes` (`workbook_files.py`) and a period folder through `reading` (`period_folder.py`). | `tests/test_uszkodzone_wejscia.py`, `tests/test_jeden_odczyt_skoroszytu.py` |
| Only `template_file.py`, `template_copy.py`, `row_look.py`, `workbook_save.py`, `efenix_marking.py`, `intermax_file.py` and `intermax_replace.py` write a workbook. | `tests/test_jeden_zapis_skoroszytu.py` |
| The engine decides on the facts of a process's plan, never on a Komunikat's code: one place per process (`collective_preparation`, `engine`, `intermax_ordering`) translates the facts into warnings, Zatrzymania, the result and Decyzja taty. No code in `src/`, Centrum rozliczeń included, compares or matches a Komunikat's code, whether as a literal, a module or class constant, or in a set, tuple, list or dict. | `tests/test_decyzje_na_faktach.py`: `test_silnik_nie_decyduje_na_kodzie_komunikatu` for the engine, `test_kod_nie_porownuje_kodu_komunikatu` for all of `src/` |
| An error that becomes a Komunikat carries facts, not a sentence for tata: its `__init__` takes no `str`, and an error without its own `__init__` is not a parameter of a Komunikat factory. | `test_blad_ktory_proces_tlumaczy_na_komunikat_niesie_fakty_a_nie_tekst` in `tests/test_komunikaty_expect.py` |
| Code in `src/` does not `print`, because Dad never sees a console and a problem reaches him as a Komunikat; only `launcher.py` and `shortcut.py` print to the start console. | ruff `T201` (`per-file-ignores` in `pyproject.toml`) |
| `zip` takes `strict=True` when both sides must have the same length, `strict=False` only with a comment naming the check that already reports a different length, and successive pairs come from `itertools.pairwise`. | ruff `B905`, `RUF007` |
| Every current day or moment names its time zone: `datetime.now(timezone.utc)` for a moment that is stored or compared, and `datetime.now().astimezone().date()` for tata's local day. | ruff `DTZ` codes in `pyproject.toml` |

## Test Surface

- Judge a test by two edits: break the behaviour it names and it fails, restructure the internals with the same observable result and it passes.
  Take the expected value from `GLOSSARY.md`, the ADR or the requirement, never from a run of the code under test.
- Test each process through its operation (`run_settlements()`, `prepare_collective_file()`, `order_register()`).
  Give a module with one entry point (one operation or the HTTP API of Centrum rozliczeń) its own tests only for behaviour that entry point cannot reach.
- A module whose interface at least two entry points call (two processes, or a process and Centrum rozliczeń) is a seam: test its rule matrix once, on its interface.
  Each entry point that uses it has one translation test (module error → that entry point's Komunikat) and does not repeat the matrix.
- Test Centrum rozliczeń through its HTTP API, the way the browser sees it: responses, the event stream, files on disk, metrics records.
  Prove UI behaviour in the browser with `verify-centrum-rozliczen`, not with component unit tests.
- Make the Rejestr zleceń or a Wzorzec fail in a test through a failing adapter of `input_checks.Readers`, not by patching a module attribute.
  The same `Readers` reach the Uruchomienie procesu, the Diagnoza and the Konfiguracja, so the fault reaches all three.
- Use synthetic workbook fixtures only, shaped like Dad's real file in what the code reads (a row's style, a merged cell, the format Excel shows), not only in its values.
  Cover both successful and failure paths for each operation's behaviour matrix.
- The test that owns a workbook write verifies every column the write touches (`A:AT` for the Rozliczenie pracownika), preserved formulas and formatting, atomic replacement, and every entry under `xl/externalLinks/*`.
  Other tests assert only the behaviour they name.
- Before a change runs on real files, run the Przygotowanie pliku zbiorczego and the Przebieg rozliczeń as `Podgląd bez zapisu`; Uporządkowanie INTERMAX has no preview and saves a Kopia INTERMAX before it replaces the file.
- Keep tests free of client addresses, order numbers, and row contents in output or logs.
  The one exception is the Zatrzymanie about gaps in `SKUTECZNE` (`ZLE_SKUTECZNE`, ADR 0004): its tests use synthetic `SKUTECZNE` values, because the Komunikat shows the exact cell content.
- Name a file that a test reads or runs with a literal path (`ROOT / "docs" / "adr"`), not a path built from a variable.
  `tools/szybko.py` selects tests from imports and such literals, so a path built at run time hides the dependency.
- Use an expect test (`assert_expected` in `tests/fixtures/expect.py`) for behaviour a human reads, such as Komunikaty and traces: it compares the text with a file in `tests/expected/`, named by a literal path.
  Write the new file with the command the failing test prints, `ZAPISZ_EXPECT=1 .venv/bin/python -m pytest '<test>'` in sh or `$env:ZAPISZ_EXPECT=1; .venv\Scripts\python.exe -m pytest '<test>'; Remove-Item Env:ZAPISZ_EXPECT` in PowerShell on Windows, and commit it with the change; CI never writes it.
- Test a rule that matches text from Dad's files (a word or phrase in `URZĄDZENIA` or `CZYNNOŚCI`, an operator name, a period token) with a Hypothesis property, not only with examples: the text anywhere in the cell, glued to punctuation, in any letter case and with Polish letters, two words of the rule in one cell, and the word inside a longer word.
  Take the expected result from `GLOSSARY.md`, the ADR or the docstring, and keep the examples deterministic with `derandomize=True` and `database=None`, as `tests/test_wlasnosci_dopasowania_tekstu.py` does.
- A test leaves no thread, process, lock or open file behind, and passes alone and in any order, because the xdist shards on the Mac and in CI hold different neighbours.
- A test holds on Windows and on Python 3.11: `time.monotonic()` on Windows under Python 3.11 advances in steps of about 15.6 ms, a Windows path inside JSON escapes its backslashes, and the Windows console encodes in cp1252.
- A refactor that splits a shared path gives each new branch a test that fails when that branch breaks, because tests that reached it only through the old shared path stop covering it without failing.
- Prove that a new test or check fails on the broken code it guards with `tools/mutacje.py`, the repository's one mutation engine: use it rather than writing another.
  Run it once for each test or check added or changed in a round of work.
  A rebase, or a fix that leaves the test unchanged, does not need a new run.
- A surviving mutation gets the test that catches it, or its line in the issue `Przeżyte mutacje z #N` answers `MUTACJA <id> | nie warto, bo <reason>`.
  Only a mutation that leaves the behaviour unchanged gets `# mutacje-zmiany: <reason> | do YYYY-MM-DD | zgoda <who>` on its line, with Maks's approval.

| Rule | Guard |
|---|---|
| Every changed line of `src/` and `tools/` has a test that fails when the line is broken, or its line in the issue `Przeżyte mutacje z #N` says why the test is not worth it (`nie warto, bo …`); after the merge, the nightly run files each mutation no test catches (and, for an operator mutation that is not a hunk reverted to the base, that ruff and mypy of both systems do not reject either: the type gate of `tools/mutacje.py`) as a line `MUTACJA <id>` in the issue `Przeżyte mutacje z #N` of the PR that last changed the line (ADR 0021, `docs/agents/pr-i-ci.md`). | `tools/mutacje_nocne.py` (nightly workflow `mutacje-nocne.yml`), `tests/test_mutacje_nocne.py` |
| A change to a Komunikat's text changes `tests/expected/komunikaty.txt` in the same PR. | `tests/test_komunikaty_expect.py` |
| A test module imports helpers only from `tests/fixtures`. | `tests/test_struktura_testow.py` |
| A test waits for a state with `wait_for` (`tests/fixtures/potomne.py`), never for a fixed number of seconds, and checks the time of the code under test by equality on the fake clock `ManualClock` (`tests/fixtures/clock.py`), never by a fixed number of milliseconds. | `tests/test_struktura_testow.py` |
| A test runs an interleaving explorer of a `verify-*` skill (`.agents/skills/*/scripts/explore_*.py`) in a new interpreter of its own (`subprocess`) with a time limit and never executes its code in the pytest process, where a child started by `fork` (`multiprocessing`) counts as the pytest process because it inherits the guard, outside the explorers `IN_PROCESS_EXPLORERS` lists with their reasons, because a model thread the explorer abandons keeps its real lock until the process ends (#651). | audit hook of the plugin `tests/fixtures/eksplorator_w_procesie.py` (loaded by `tests/conftest.py`), `tests/test_eksplorator_w_procesie.py`: in a test that runs, any execution of an explorer's code in the pytest process or an xdist worker fails the test step or the collection that ran it, whatever the form of loading, a symbolic link to the explorer or its folder included; it misses a test that does not run, the explorer's code copied outside `.agents/skills/*/scripts/` or compiled under another file name, and the time limit of the own process |
| Git in tests has one configuration, the same on every computer: a test builds `env=` from `os.environ` and leaves `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM` alone, sets a computer configuration with something more through `computer_git_config` (`tests/fixtures/git_config.py`), and a process of the tool's code (`src/`) has an empty `user.name` and `user.email`, so its `git commit` fails as it does at Dad's. | fixture `git_bez_konfiguracji_komputera` in `tests/conftest.py`, `tests/test_git_w_testach.py` |
| A test named in a rules table (this file, `AGENTS.md`, `docs/agents/pr-i-ci.md`, `docs/agents/skille.md`) that checks the whole repository runs on every `tools/szybko.py`. | `tests/test_szybko.py` |
| `pytest.raises` of a broad exception (`ValueError`, `OSError`) takes `match=` on its message, and its block holds the one statement that raises. | ruff `PT011`, `PT012` |

## Tools and Platforms

| Rule | Guard |
|---|---|
| Check the operating system with `sys.platform == "win32"`. | ruff `TID251` (`pyproject.toml`), mypy for both systems in `tools/ci_lokalnie.py` |
| A command of a tool in `tools/` that takes time or starts its own processes runs through `potomne.run`, and a copy of a commit comes from `potomne.commit_copy` ([`tools/lib/potomne.py`](tools/lib/potomne.py)), because they die together with the tool, even one killed by SIGKILL. | `tests/test_potomne.py` |
| A concurrent mutation run (`tools/mutacje.py --rownolegle`, a skill's `check_all`) runs at most `PARALLEL` mutations at once and gives each mutation's command `PYTEST_XDIST_AUTO_NUM_WORKERS=1` unless the caller set it, so a test's nested `pytest -n auto` does not multiply over the cores of the Mac that agents share. | `tests/test_mutacje.py` |
| The files that the system Python runs before `.venv` (the list in `per-file-target-version` in `pyproject.toml`) work under the Python 3.9 of macOS. | ruff `per-file-target-version`, `tests/test_systemowy_python.py` |
| A tool or skill script that runs as its own process adds `src` to `sys.path` itself, because CI on Windows does not install the package. | `tests/test_skrypty_bez_instalacji.py` |
| `tools/` holds only the tools an agent or a human runs, and each opens its docstring with one line of 80–160 characters that says what it does and when to use it, which the generated `## Narzędzia` block of `AGENTS.md` lists; a script that only a workflow runs lives in `tools/ci/`, a module without an entry point of its own in `tools/lib/`, and neither `AGENTS.md` nor a skill points to `tools/ci/`, and no command in `docs/agents/`, `README.md` or a tool's docstring runs a script from `tools/ci/`, because a script the agent runs itself belongs in `tools/` and its list. | `tests/test_spis_narzedzi.py` |
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
| Every field of the contract's schemas (`frontend/src/api/openapi.json`) is used in `frontend/src` outside `generated/`, or `FIELDS_OUTSIDE_UI` lists it with its reason. | `npm run rules` (rule 1 in `frontend/scripts/rules.mjs`) in CI job `Frontend` |
| The UI never branches on a process name, outside the files `PROCESS_COMPARISON_FILES` lists with their reasons. | `npm run rules` (rule 2 in `frontend/scripts/rules.mjs`) in CI job `Frontend` |
| The frontend reaches the server (`fetch`, `EventSource`, `WebSocket`, `XMLHttpRequest`, `sendBeacon`) and calls `JSON.parse` only in the files of `NETWORK_FILES`, which parse every server response and stream event with a schema generated from the server models. | `npm run rules` (rule 3 in `frontend/scripts/rules.mjs`) in CI job `Frontend` |
| After a change to the server models, and after a merge or a rebase, regenerate the contract and the Centrum build (`npm run regen` in `frontend/`), because the `merge=wygenerowane` driver keeps the current HEAD's version of them. | step „Require the committed contract and build to be fresh” of CI job `Frontend` |

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
