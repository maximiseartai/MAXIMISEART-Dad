---
name: verify-centrum-rozliczen
description: Verify Centrum rozliczeń, MAXIMISEART-Dad's local browser app, end to end in Chromium (Playwright for Python) on a synthetic folder okresów, checking screens, API answers, and effects on disk, with retained screenshots; use after changes to the Centrum server, frontend, contract, or launcher, and read ADR 0004 (`docs/adr/0004-centrum-rozliczen-adapter.md`) before making them. When a change can make the frontend faster or slower, measure it before and after with `--feature wydajnosc` and update the baseline as `features/wydajnosc.md` says.
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
  - tools/lib/atrapy/intermax.py
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

Centrum rozliczeń is a FastAPI server on `127.0.0.1` that serves the committed
frontend build from `src/rozliczenia/centrum/static/` (ADR 0004). Dad opens it
in his browser. This skill launches the real app on a synthetic fixture, clicks
Dad's path in headless Chromium, and checks every visible result against the
server's answer and the files on disk.

## What CI runs and what stays local

CI runs `run_centrum_verification.py --feature all` (the `ci:` key) in Mutation checks on Windows whenever a change
touches this skill, in up to `ci-czesci` parts: part k of n (`MUTACJE_CZESC=k/n`) drives the k-th of n consecutive runs of
the order of `all` (`FEATURES` in `scripts/drive/__init__.py`) on its own fixture and Centrum, so a feature must also pass
right after the fixture or after any earlier feature of that order: a feature that finds an earlier feature's state
names it in `needs` of its `Feature`, and the drive drives that one first when it has not yet (`powiadomienia` needs
`zgloszenie` and `uwaga-taty`). A pull
request runs the parts of one n, and the night on `main` runs every part of every n up to `ci-czesci` after a change that
picks this check on a pull request. A red run leaves its evidence in the `evidence-<job id>-<attempt>` artifact (e.g.
`evidence-mutacje-2-1`), and its job name in the plan says which part.
The `check_centrum_<feature>_mutations.py` scripts run in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`)
after a change of this skill's folder. Run `all` and the mutations locally only to reproduce a red Mutation checks step
or the night's issue. What stays with you: drive the feature you change and look at its
screenshots after a UI change, because a passing run does not judge visual
quality. A change of a shared element also drives every feature that sees it, not only your own: a section of the window
Ustawienia drives `okno-ustawien` (it lists every section) and `ustawienia`, and the window, menu, toasts or dialogs also
`uwaga-taty`. `wydajnosc` is never part of `all` and runs only locally (`features/wydajnosc.md`).
The real-mailbox review of Wpisanie raportów never runs in CI either: it needs Dad's real Gmail, the access file and
Maks's consent (`features/wpisanie-raportow.md`, section Real mailbox).

## Launch

Run from the repository root (Windows: `py -3`; macOS/Linux: `.venv/bin/python`); `--run-dir` can point anywhere:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\run_centrum_verification.py
```

`--feature okno-ustawien`, `--feature ustawienia`, `--feature reguly-ilosci`, `--feature roznice-z-kontroli`, `--feature edytor-regul-ilosci`, `--feature lista-urzadzen`, `--feature tablica-okresow`, `--feature tablica-skrocona`, `--feature uklad-folderow-taty`, `--feature konfiguracja`, `--feature wykonawcy`, `--feature aktualizacja`,
`--feature metryki`, `--feature blad-odczytu`, `--feature przygotowanie-pliku-zbiorczego`, `--feature uzupelnienie`,
`--feature przebieg-rozliczen`, `--feature uporzadkowanie-intermax`, `--feature kopie-intermax`, `--feature kontrola-ilosci`, `--feature diagnoza`, `--feature aktualnosc-i-onedrive`, `--feature zgloszenie`, `--feature uwaga-taty`, `--feature logi-uruchomienia`, `--feature karta-z-logow`, `--feature powiadomienia`, `--feature pomiar-u-taty`, `--feature wpisanie-raportow`, `--feature wycena-w-efenix`, or `--feature start-i-zamykanie` drives one
feature; the default `all` drives every feature in `features/` except `wydajnosc`, ending
with `start-i-zamykanie`, which closes Centrum through its own button. In `all`,
Dad's whole week runs in order: Przygotowanie pliku zbiorczego, the summary of
Uzupełnienie pliku zbiorczego, Gotowość, and
Przebieg rozliczeń up to the Status okresu `Rozliczenia pracowników gotowe`;
`uzupelnienie` and `przebieg-rozliczen` alone drive Przygotowanie first, and `logi-uruchomienia` alone drives
`przebieg-rozliczen` first. `--feature wydajnosc`
measures how fast Centrum is in Dad's CPU profiles against the baseline in
`wydajnosc-baseline.json`; it is never part of `all` and takes minutes
(`--baseline` and `--powtorzenia` apply to it only; see
`features/wydajnosc.md`). The runner holds the machine for it
(`tools/quiet_machine.py`). A measurement waits at most 3 minutes for a quiet
CPU (no other run, measurement or test run) and holds the machine only while it
measures, about 5 minutes. Every other run waits at most 15 minutes for a
measurement in progress and never for a measurement still waiting for a quiet
CPU. `MASZYNA ZAJĘTA | …` lines say what a run or measurement waits for. Run
`wydajnosc` in the background, wait for its end in the same turn and read its last line instead of piping it
through `tail`; do the same with any run while
`tools/quiet_machine.py --status` shows `pomiar`, because waiting for it can
outlast a 10-minute command limit. Success prints
`VERIFY OK | features=… | evidence=… | scratch_removed=true`; anything else is a
failure, reported as `VERIFY FAIL | …`.

The runner creates `<run dir>/runs/centrum-<id>` with
`scripts/create_centrum_fixture.py`, then starts `scripts/serve_centrum.py` on a
free port. Readiness is `<root>/server.json` (written only after the port is
bound) plus a `200` from `/api/health`. Teardown is the runner's `finally`: it
terminates the process it started and runs cleanup.

Preconditions, checked by the runner before launching:

- the built frontend exists (`src/rozliczenia/centrum/static/index.html`); after
  frontend changes run `npm ci` and `npm run build` in `frontend/` first, or the
  run proves the old build;
- Playwright for Python and Chromium are installed:
  `py -3 -m pip install -e ".[dev]"` then `py -3 -m playwright install chromium`.
  On Windows `.[dev]` also installs `tzdata`, the time zone database Python
  lacks there. The drive reads dates on screen in Dad's time zone
  (`Europe/Warsaw`, the browser's) and dates in the server's text in the
  computer's own, so it passes on a machine in any time zone.

`serve_centrum.py` runs the production app (`create_app` and `serve`), not a
test double. Its inputs are run-local: the settings file and both metrics files
live in the run root, and the platform adapter (Dad's computer) is scripted. A native picker answers
with the path in `<root>/picker/answer.txt` (no file means Dad cancelled) and
logs its title to `<root>/dialogs.jsonl`. Opening a file in Excel or a folder in
Explorer appends the path to `<root>/opened.jsonl` instead of launching an
application. While `<root>/pacing/szablony-ms.txt` exists, each Szablon
pracownika of a Przebieg rozliczeń RUN waits that many milliseconds, so the
live progress and the refused closing can be observed; the drive turns it on
for one RUN only. Wpisanie raportów reads its Skrzynka raportów from the run's folder of `.eml` mails `<root>/maile/`
(`FolderInbox`), never Dad's Gmail, and keeps its files (pamięć, wynik for the view Raporty, decisions of „Zostaw moją”)
in the run's `config/`. Uporządkowanie INTERMAX keeps its Kopie INTERMAX in `<root>/Kopie INTERMAX`, and its clock is the
fixture's "today" at the computer's time of day. Wycena w efenix never reaches efenix.pl: its window is Playwright's
headless Chromium on the tests' Atrapa efenix, which `serve_centrum.py` serves on a free port while Centrum runs
(address in `<root>/efenix/adres.txt`, logged out until a form is posted to its `page_login.php`), with the
browser profile in `<root>/przegladarka-efenix`. The Diagnoza never reaches GitHub: the commit of the newest Wydanie on `main` is the
tool's own unless `<root>/github/main-commit.txt` names another, its tag is in `<root>/github/wydanie.txt`, the published Wydania with their notes are `<root>/github/wydania.json` in GitHub's shape, `<root>/github/brak-sieci`
means no network, and a full path listed in `<root>/onedrive/tylko-w-chmurze.txt` is a
OneDrive file „tylko online” on every system. Zgłoszenia never reach GitHub
either: the skrzynka Zgłoszeń is `<root>/skrzynka-zgloszen/`, one `<number>.json`
per issue with its label and comments (Zgłoszenie, Kontrola ilości, Logi Uruchomienia of a period; never the key, `state` editable to `closed`; a comment's address is `skrzynka-zgloszen/<number>.json#komentarz-<k>`, never a full path), unreachable while
`<root>/skrzynka-zgloszen/brak-sieci` exists, refusing the key for every question while `<root>/skrzynka-zgloszen/odmawia-klucza` exists, rejecting the content of every new issue with a label and of every comment to one while `<root>/skrzynka-zgloszen/odrzuca-<label>` exists, and slow while `<root>/pacing/skrzynka-ms.txt` exists; `<root>/github/tool-commit.txt` stands for
the tool after an update, and `<root>/zegar/przesuniecie-min.txt` moves Centrum's clock
forward past the 10-minute limit on asking the skrzynka and past the queue's one-minute retry, which then fires at once. The tool itself is the run's synthetic Git clone
`<root>/aktualizacja/klon` (its commit is the tool's own commit): Aktualizacja narzędzia moves only that clone,
fetching from the local "origin" `<root>/aktualizacja/origin.git`, never from GitHub, and while
`<root>/pacing/aktualizacja-ms.txt` exists each update waits that many milliseconds first (`<root>/pacing/instalacja-ms.txt`: before pip starts). Pip runs with `PIP_NO_INDEX=1`, never reaching PyPI. After a successful
update Centrum restarts itself: the restart guardian runs the clone's `run_centrum.py`, a shim that serves this
run's scripted Centrum again on the same port (it rewrites `server.json`), waiting first while
`<root>/pacing/ponowny-start-ms.txt` exists. When the new version does not answer, the guardian moves the clone back and starts the old version's shim the same way. The adapter is the production boundary for those actions; the real
Windows and macOS adapters are covered by `tests/test_centrum_launcher.py` (real
process, real browser opening), on Windows end to end by `verify-centrum-na-windowsie`, and by hand.

Instances are isolated by port and run root, so two runs can proceed side by
side. Drive only a Centrum this run started. Dad's own Centrum (port `47811`,
`config/centrum-ustawienia.yaml`) is never touched.

## Doctor

The runner runs the doctor before driving and keeps the result in `doctor.txt`.
To check an instance by hand:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\centrum_doctor.py --root "$runRoot"
```

`DOCTOR OK` means `server.json` exists, the URL is on `127.0.0.1`, `/api/health`
returns Centrum's identity, the commit of this run's tool clone, and an identifier of this start, `/` serves the
built frontend, and the settings and metrics files belong to this run. The doctor only reads.

## Drive

`scripts/drive_centrum.py` is the harness, with each feature's steps in `scripts/drive/<feature>.py`: Playwright for Python, sync API,
Chromium at 1440×1000, locale `pl-PL`. It finds elements by ARIA role and
accessible name, the same Polish names Dad reads: the link `Ustawienia` in the
menu's footer and the dialog `Ustawienia` it opens, buttons such as
`Zmień Rejestr zleceń` (section Foldery) and `Plik zbiorczy, okres 29_05_10_2026`;
the table `Tablica okresów`; the region `Następny krok`; the groups
`Rejestr zleceń` and `Folder okresów` of Uruchomienia; in Ustawienia the list items
named after each Wzorzec and the list `Wykonawcy`. The recipes
and their exact handles are in the feature files. To drive one feature against
a running instance:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\drive_centrum.py --root "$runRoot" --url "$url" --evidence "$evidenceRoot" --feature tablica-okresow
```

## Evidence

Evidence lives in `<run dir>/evidence/centrum-<id>/` and survives cleanup. The
run dir is `.verification` of the checkout, or any path given with `--run-dir`:

- `fixture.txt`, `server.txt` (server console, with a `REQUEST` line per answered request: method, path without
  query, status), `doctor.txt`, `drive.txt` (every step and check), `cleanup.txt`, `self-test.txt`;
- `zadania-strony.txt`: each failed request (not one the page gave up itself), answer of 400 or more and page
  without its stylesheet, of every page of the drive. A page without its stylesheet fails the drive with `the page got no stylesheet`, before the error it
  caused;
- `screenshots/NN-<step>.png` and `aria/NN-<step>.txt` for each step, captured
  after transitions finish; on failure, also `screenshots/zz-failure.png`.
  `NN` belongs to one feature only (feature files and PRs cite it alone; views of one
  step, such as `225-…-1280px` and `225-…-jasny`, share it): the drive fails on a
  screenshot that is not among its feature's `screenshots` in `FEATURES`, and the
  runner when the screenshots of two features share a number;
- `api/*.json` with the server's answers, including the refused foreign
  `Origin` and `Host` requests, and `api/start-*.txt` with the real launcher's
  console output;
- `wydajnosc/` for `wydajnosc`: `raport.txt`, `raport.json`,
  `baseline-kandydat.json`, and the CPU traces `slad-<strona>-<n>x.json`;
- `state/` with `opened.jsonl`, `dialogs.jsonl`, the settings file, the
  Centrum log (`centrum-rozliczen.log`), and the Logi Uruchomienia
  (`uruchomienia/`) as the run left them.

Proof standards:

- Drive Dad's path through the UI. A screen state alone is not proof: pair it
  with the API answer and the side effect (settings file, picker log, opened
  path).
- Treat the scripted platform adapter, GitHub, and OneDrive as the only
  stand-ins for Dad's computer.
  Harness steps are labelled in `drive.txt`: Gotowość, where the drive
  edits the Plik zbiorczy instead of Excel, the Szablony pacing, a server
  unreachable for one read, a re-read held on its way, a picker held open
  like Dad's native window, and a stream that delivers late.
- Look at the screenshots after a UI change; a passing run does not judge
  visual quality.
- Evidence holds synthetic paths only. The self-test fails if the fixture's
  workbook row marker reaches evidence, which would mean Centrum read workbook
  content.

## Cleanup

The runner calls `scripts/centrum_cleanup.py` in `finally`. It stops the server
recorded in `server.json` only if that URL still answers as Centrum, then
removes the run root. It refuses a directory that the fixture did not create
(no `.katalog-runu` file). It never touches evidence and never kills by process
name. After a runner that was itself killed:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\centrum_cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists.

## Helpers

- `scripts/run_centrum_verification.py`: the one-command orchestrator (above).
- `scripts/create_centrum_fixture.py --root "$runRoot"`: synthetic folder
  okresów `INEA` (one period per Status okresu, one Plik zbiorczy with a
  Wykonawca missing from the Lista Wykonawców, plus a non-period folder),
  synthetic Rejestr zleceń, a `config/` with a synthetic Lista Wykonawców
  and the three Wzorce, both metrics files with a synthetic history,
  `fixture.json` with "today" `2026-10-19`, the expected Tablica okresów, the
  expected Wykonawcy, and the metrics facts the drive checks. `--wariant
  rok-pracy` adds Dad's year of work for `wydajnosc` (52 periods in his layout,
  about 260 more metrics records).
- `scripts/serve_centrum.py --root "$runRoot" --port 47900`: serves Centrum for
  the run.
- `scripts/centrum_doctor.py --root "$runRoot"`: the read-only doctor.
- `scripts/drive_centrum.py --root "$runRoot" --url "$url" --evidence "$evidenceRoot"`:
  the Playwright drive.
- `scripts/centrum_cleanup.py --root "$runRoot"`: stop and remove one run.
- `scripts/centrum_self_test.py --evidence-root "$evidenceRoot"`: skill package
  check (with the `wydajnosc` gate on made-up numbers) and evidence hygiene check;
  the machine lock is tested in `tests/test_cicha_maszyna.py`.
- `scripts/check_centrum_<feature>_mutations.py`, one script per feature: shows the drive of
  that feature fails on broken variants of Centrum, each mutation on its own copy of the checkout;
  each ends with `MUTACJE OK`, and CI runs them in its Mutation checks jobs (full CI on `main` and
  the night), so run one locally only to reproduce a red Mutation checks step or the night's issue:
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
  A mutation goes into the script of the feature its command drives (`--feature …`), so parallel
  PRs on different features do not edit one table. A new feature with mutations adds its own
  `check_centrum_<feature>_mutations.py` and its line here. Paths of Centrum files and the
  `--feature` commands live in `scripts/cele_mutacji_centrum.py`, in alphabetical order.
- `tools/quiet_machine.py --status`: what holds the machine now (a
  measurement, other verification runs, test runs or benchmarks).

Read `features/README.md` for the conventions, then the chosen feature's
`features/<feature>.md`. Each Centrum slice adds
its feature file and drive steps in the same PR as the feature; keep the map
honest with `/maintain-verification-skill`.
