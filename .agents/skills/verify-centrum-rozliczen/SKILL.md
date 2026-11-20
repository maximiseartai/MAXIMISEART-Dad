---
name: verify-centrum-rozliczen
description: Verify Centrum rozliczeń, Dad's local browser app, end to end; Playwright for Python drives the real server in Chromium on a synthetic folder okresów and pairs each screen with the API answer and the effect on disk, keeping screenshots. Use when `tools/skille_dla_zmiany.py` names it, when its Mutation checks job or night issue is red, when asked to verify a Centrum screen or feature, and before and after a change that can make the frontend faster or slower (`--feature wydajnosc`). Before changing Centrum, read ADR 0004 (`docs/adr/0004-centrum-rozliczen-adapter.md`).
pilnuje:
  - src/rozliczenia/centrum/*
  - src/rozliczenia/report_entering.py
  - frontend/*
  - run_centrum.py
  - tools/lib/atrapy/scenariusz_centrum.py
  - tools/lib/atrapy/preparation.py
  - tools/lib/atrapy/settlement.py
  - tools/lib/atrapy/scenariusz_rozliczen.py
  - tools/lib/atrapy/efenix.py
  - tools/lib/atrapy/atrapa_efenix.py
  - tools/lib/atrapy/serwer_http.py
  - tools/lib/atrapy/intermax.py
  - tools/lib/atrapy/baza_zlecen.py
  - tools/lib/atrapy/model_efenix.py
  - tools/lib/atrapy/pliki_taty.py
  - tools/lib/atrapy/skrzynka.py
  - tools/lib/atrapy/skrzynka_raportow.py
  - tools/lib/atrapy/widok_skrzynki.py
  - tools/lib/atrapy/workbooks.py
ci: .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature all
ci-czesci: 8
---

# Verify Centrum rozliczeń

Centrum rozliczeń is a FastAPI server on `127.0.0.1` that serves the committed frontend build from `src/rozliczenia/centrum/static/` (ADR 0004).
Dad opens it in his browser.
This skill launches the real app on a synthetic fixture, clicks Dad's path in headless Chromium, and checks every visible result against the server's answer and the files on disk.
Before driving, read `features/README.md` for the conventions, then the chosen feature's `features/<feature>.md` for its recipe.

## What CI runs and what stays local

CI runs `run_centrum_verification.py --feature all` (the `ci:` key) in Mutation checks on Windows whenever a change touches this skill, in up to `ci-czesci` parts: part k of n (`MUTACJE_CZESC=k/n`) drives the k-th of n consecutive runs of the order of `all` (`FEATURES` in `scripts/drive/__init__.py`) on its own fixture and Centrum.
Each feature drives a new browser window (`FeatureWindows` in `scripts/drive_centrum.py`), and every window of the browser closes when the feature ends, so a window, dialog, route, listener, clock, size, tab or browser window an earlier feature left reaches no later one; the disk, the server and the browser window's cookies and `localStorage` carry over.
So a feature must also pass right after the fixture or after any earlier feature of that order: a feature that finds an earlier feature's state on disk, on the server or in `localStorage` names it in `needs` of its `Feature`, and the drive drives that one first when it has not yet (`powiadomienia` needs `zgloszenie` and `uwaga-taty`).
A pull request runs the parts of one n, and the night on `main` runs every part of every n up to `ci-czesci` after a change that picks this check on a pull request.
A red run leaves its evidence in the `evidence-<job id>-<attempt>` artifact (e.g. `evidence-mutacje-2-1`), and its job name in the plan says which part.
Every run fails on a section `Sub-features` that differs from the run; after a change of a drive, refresh it as `features/README.md` (Feature entry contract) says.
The `check_centrum_<feature>_mutations.py` scripts run in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`) after a change of this skill's folder.
Run `all` and the mutations locally only to reproduce a red Mutation checks step or the night's issue.

What stays with you: drive the feature you change and look at its screenshots after a UI change, because a passing run does not judge visual quality.
A change of a shared element also drives every feature that sees it, not only your own: a section of the window Ustawienia drives `okno-ustawien` (it lists every section) and `ustawienia`, and the window, menu, toasts or dialogs also `uwaga-taty`.
`wydajnosc` is never part of `all` and runs only locally (`features/wydajnosc.md`).
The real-mailbox review of Wpisanie raportów never runs in CI either: it needs Dad's real Gmail and the access file, and runs at every Wydanie (`features/wpisanie-raportow.md`, section Real mailbox).

## Launch

Run from the repository root (Windows: `py -3`; macOS/Linux: `.venv/bin/python`); `--run-dir` can point anywhere:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\run_centrum_verification.py
```

`--feature okno-ustawien`, `--feature ustawienia`, `--feature reguly-ilosci`, `--feature roznice-z-kontroli`, `--feature edytor-regul-ilosci`, `--feature lista-urzadzen`, `--feature legenda-czynnosci`, `--feature tablica-okresow`, `--feature tablica-skrocona`, `--feature uklad-folderow-taty`, `--feature konfiguracja`, `--feature wykonawcy`, `--feature wysylka-rozliczen`, `--feature aktualizacja`, `--feature metryki`, `--feature blad-odczytu`, `--feature przygotowanie-pliku-zbiorczego`, `--feature uzupelnienie`, `--feature przebieg-rozliczen`, `--feature uporzadkowanie-intermax`, `--feature kopie-intermax`, `--feature kontrola-ilosci`, `--feature diagnoza`, `--feature aktualnosc-i-onedrive`, `--feature zgloszenie`, `--feature uwaga-taty`, `--feature logi-uruchomienia`, `--feature karta-z-logow`, `--feature powiadomienia`, `--feature pomiar-u-taty`, `--feature wpisanie-raportow`, `--feature wycena-w-efenix`, `--feature stanowisko-andrzeja`, or `--feature start-i-zamykanie` drives one feature; the default `all` drives every feature in `features/` except `wydajnosc`, ending with `start-i-zamykanie`, which closes Centrum through its own button.
In `all`, Dad's whole week runs in order: Przygotowanie pliku zbiorczego, the summary of Uzupełnienie pliku zbiorczego, Gotowość, and Przebieg rozliczeń up to the Status okresu `Rozliczenia pracowników gotowe`.

`--feature wydajnosc` measures how fast Centrum is in Dad's CPU profiles against the baseline in `wydajnosc-baseline.json` and takes minutes.
When a change can make the frontend faster or slower, measure it before and after and update the baseline as `features/wydajnosc.md` says.
The runner holds the machine for it (`tools/quiet_machine.py`): a measurement waits at most 3 minutes for a quiet CPU (no other run, measurement or test run) and holds the machine only while it measures, about 5 minutes; every other run waits at most 15 minutes for a measurement in progress and never for a measurement still waiting for a quiet CPU.
`MASZYNA ZAJĘTA | …` lines say what a run or measurement waits for.
Run `wydajnosc` in the background, wait for its end in the same turn and read its last line instead of piping it through `tail`; do the same with any run while `tools/quiet_machine.py --status` shows `pomiar`, because waiting for it can outlast a 10-minute command limit.
Anything but `VERIFY OK | features=… | evidence=… | scratch_removed=true` is a failure, reported as `VERIFY FAIL | …`.

The runner creates `<run dir>/runs/centrum-<id>` with `scripts/create_centrum_fixture.py`, then starts `scripts/serve_centrum.py` on a free port.
Readiness is `<root>/server.json` (written only after the port is bound) plus a `200` from `/api/health`.

Preconditions, checked by the runner before launching:

- the built frontend exists (`src/rozliczenia/centrum/static/index.html`); after frontend changes run `npm ci` and `npm run build` in `frontend/` first, or the run proves the old build;
- Playwright for Python and Chromium are installed: `py -3 -m pip install -e ".[dev]"` then `py -3 -m playwright install chromium`.
  On Windows `.[dev]` also installs `tzdata`, the time zone database Python lacks there.

`serve_centrum.py` runs the production app (`create_app` and `serve`), not a test double, with run-local inputs and a scripted adapter for Dad's computer, GitHub, OneDrive, the skrzynka Zgłoszeń, pip and efenix; its `--help` says how each boundary answers, and `scripts/harness.py` names the run-root file that steers it.
The drive turns on the Szablony pacing (`<root>/pacing/szablony-ms.txt`) for one Przebieg rozliczeń RUN only, so the live progress and the refused closing can be observed.
Wpisanie raportów reads its Skrzynka raportów from the run's folder of `.eml` mails `<root>/maile/` (`FolderInbox`), never Dad's Gmail, and keeps its files (pamięć, wynik for the view Raporty, decisions of „Zostaw moją”) in the run's `config/`.
Uporządkowanie INTERMAX keeps its Kopie INTERMAX in `<root>/Kopie INTERMAX`, and its clock is the fixture's "today" at the computer's time of day.
A comment of the skrzynka Zgłoszeń has the address `skrzynka-zgloszen/<number>.json#komentarz-<k>`, never a full path; the skrzynka never holds the key.
The real Windows and macOS adapters are covered by `tests/test_centrum_launcher.py` (real process, real browser opening), on Windows end to end by `verify-centrum-na-windowsie`, and by hand.

Instances are isolated by port and run root, so two runs can proceed side by side.
Drive only a Centrum this run started.
Dad's own Centrum (port `47811`, `config/centrum-ustawienia.yaml`) is never touched.

## Doctor

The runner runs the doctor before driving and keeps the result in `doctor.txt`; what `DOCTOR OK` checks is in its `--help`.
To check an instance by hand:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\centrum_doctor.py --root "$runRoot"
```

## Drive

`scripts/drive_centrum.py` is the harness, with each feature's steps in `scripts/drive/<feature>.py`: Playwright for Python, sync API, Chromium at 1440×1000, locale `pl-PL`.
It finds elements by ARIA role and accessible name, the same Polish names Dad reads.
To drive one feature against a running instance:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\drive_centrum.py --root "$runRoot" --url "$url" --evidence "$evidenceRoot" --feature tablica-okresow
```

## Evidence

Evidence lives in `<run dir>/evidence/centrum-<id>/` and survives cleanup:

- `fixture.txt`, `server.txt` (server console, with a `REQUEST` line per answered request: method, path without query, status), `doctor.txt`, `drive.txt` (every step and check), `cleanup.txt`, `self-test.txt`;
- `zadania-strony.txt`: each failed request (not one the page gave up itself), answer of 400 or more and page without its stylesheet, of every page of the drive.
  A page without its stylesheet fails the drive with `the page got no stylesheet`, before the error it caused.
  CI keeps only the log, so a failed drive also prints each line as `PAGE LOST |` with the server's last `REQUEST` line for its path before it (or `no answered REQUEST`);
- `screenshots/NN-<step>.png` and `aria/NN-<step>.txt` for each step, captured after transitions finish; on failure, also `screenshots/zz-failure.png`.
  `NN` belongs to one feature only (feature files and PRs cite it alone; views of one step, such as `225-…-1280px` and `225-…-jasny`, share it): the drive fails on a screenshot that is not among its feature's `screenshots` in `FEATURES`, and the runner when the screenshots of two features share a number;
- `api/*.json` with the server's answers, including the refused foreign `Origin` and `Host` requests, and `api/start-*.txt` with the real launcher's console output;
- `wydajnosc/` for `wydajnosc` (`features/wydajnosc.md`);
- `state/` with `opened.jsonl`, `dialogs.jsonl`, the settings file, the Centrum log (`centrum-rozliczen.log`), and the Logi Uruchomienia (`uruchomienia/`) as the run left them.

Proof standards:

- Drive Dad's path through the UI.
  A screen state alone is not proof: pair it with the API answer and the side effect (settings file, picker log, opened path).
- Treat the scripted platform adapter, GitHub, and OneDrive as the only stand-ins for Dad's computer.
  Harness steps are labelled in `drive.txt`: Gotowość, where the drive edits the Plik zbiorczy instead of Excel, the Szablony pacing, a server unreachable for one read, a re-read held on its way, a picker held open like Dad's native window, and a stream that delivers late.
- Evidence holds synthetic paths only.
  The self-test fails if the fixture's workbook row marker reaches evidence, which would mean Centrum read workbook content.

## Cleanup

The runner's `finally` terminates the process it started and runs `scripts/centrum_cleanup.py`, whose `--help` says what it stops and removes.
It refuses a directory that the fixture did not create (no `.katalog-runu` file).
After a runner that was itself killed:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\centrum_cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists.

## Helpers

- `scripts/create_centrum_fixture.py --root "$runRoot"`: the synthetic run root (its `--help`; what the features rely on: `features/README.md`, Baseline preconditions); `--wariant rok-pracy` adds Dad's year of work for `wydajnosc`.
- `scripts/serve_centrum.py --root "$runRoot" --port 47900`: serves Centrum for the run.
- `scripts/centrum_self_test.py --evidence-root "$evidenceRoot"`: skill package check (with the `wydajnosc` gate on made-up numbers) and evidence hygiene check; the machine lock is tested in `tests/test_cicha_maszyna.py`.
- `scripts/check_centrum_<feature>_mutations.py`, one script per feature: shows the drive of that feature fails on broken variants of Centrum, each mutation on its own copy of the checkout, and ends with `MUTACJE OK`:
  `scripts/check_centrum_aktualizacja_mutations.py`,
  `scripts/check_centrum_diagnoza_mutations.py`,
  `scripts/check_centrum_karta_z_logow_mutations.py`,
  `scripts/check_centrum_kopie_intermax_mutations.py`,
  `scripts/check_centrum_przebieg_rozliczen_mutations.py`,
  `scripts/check_centrum_przygotowanie_pliku_zbiorczego_mutations.py`,
  `scripts/check_centrum_uporzadkowanie_intermax_mutations.py`,
  `scripts/check_centrum_uwaga_taty_mutations.py`,
  `scripts/check_centrum_uzupelnienie_mutations.py`,
  `scripts/check_centrum_wycena_w_efenix_mutations.py`,
  `scripts/check_centrum_zgloszenie_mutations.py`.
  A mutation goes into the script of the feature its command drives (`--feature …`), so parallel PRs on different features do not edit one table.
  A new feature with mutations adds its own `check_centrum_<feature>_mutations.py` and its line here.
  Paths of Centrum files and the `--feature` commands live in `scripts/cele_mutacji_centrum.py`, in alphabetical order.
- `tools/quiet_machine.py --status`: what holds the machine now (a measurement, other verification runs, test runs or benchmarks).

Each Centrum slice adds its feature file and drive steps in the same PR as the feature (`features/README.md`); keep the map honest with `/pstack:maintain-verification-skill`.
