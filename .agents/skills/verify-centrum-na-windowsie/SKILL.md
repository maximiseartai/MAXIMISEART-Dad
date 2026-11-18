---
name: verify-centrum-na-windowsie
description: Verify Centrum rozliczeń on Windows the way Dad installs, starts and updates it - the tool cloned into a user folder with a space and a Polish letter, the desktop shortcut and pythonw.exe without a console, the native start-problem window, the native tkinter pickers, Explorer, and Aktualizacja narzędzia with the restart guardian - on GitHub's windows-latest runner (or any Windows machine), with desktop screenshots, the Centrum log and process facts as evidence. Use when `tools/skille_dla_zmiany.py` names it, when its workflow `verify-centrum-na-windowsie` is red, and when something works on the Mac but may not on Dad's Windows.
pilnuje:
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/platform.py
  - src/rozliczenia/centrum/shortcut.py
  - src/rozliczenia/centrum/centrum-rozliczen.ico
  - src/rozliczenia/centrum/start_problems.py
  - src/rozliczenia/centrum/log.py
  - src/rozliczenia/centrum/restart_guardian.py
  - src/rozliczenia/centrum/tool_update.py
  - src/rozliczenia/centrum/tool_updates.py
  - src/rozliczenia/centrum/tool_freshness.py
  - src/rozliczenia/centrum/configuration_router.py
  - src/rozliczenia/centrum/period_board.py
  - src/rozliczenia/centrum/update_messages.py
  - src/rozliczenia/centrum/version.py
  - src/rozliczenia/centrum/opener.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/centrum/shutdown.py
  - src/rozliczenia/centrum/settings/*.py
  - src/rozliczenia/centrum/settings_router.py
  - run_centrum.py
  - install_centrum_shortcut.py
  - frontend/src/lib/tool-update.tsx
  - src/rozliczenia/centrum/static/**
  - requirements.txt
  - .github/workflows/verify-centrum-na-windowsie.yml
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
  - tools/lib/atrapy/workbooks.py
  - .agents/skills/verify-centrum-rozliczen/scripts/create_centrum_fixture.py
  - .agents/skills/verify-centrum-rozliczen/scripts/drive/common.py
---

# Verify Centrum rozliczeń na Windowsie

Dad's computer is a Windows laptop (`docs/agents/komputer-taty.md`).
`verify-centrum-rozliczen` proves Centrum's screens on the Mac with a scripted platform adapter; this skill proves what only Windows can: the production launcher started from the `.lnk` through `pythonw.exe`, Windows' own message box and file dialogs, Explorer, and Aktualizacja narzędzia where Git for Windows, pip and the detached restart guardian replace a running `pythonw`.
Nothing on Dad's side is scripted: the only stand-ins are GitHub (a local "origin") and Dad's browser (a recorder of the address Centrum opens).
The drive answers native windows through user32 and drives the tab with Playwright.
Before driving, read `features/README.md` for the conventions, then the chosen feature's `features/<feature>.md` for its recipe.

## Launch

From macOS (or anywhere with `gh`), run it on GitHub's Windows machine and bring the evidence home.
A run takes about 10 minutes, as long as a foreground command may take, so start it in the background, wait for its end in the same turn and read its last line:

```bash
.venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py            # dispatch on the current, pushed branch
.venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py --run <id> # wait for a run a PR or push started
```

The workflow `.github/workflows/verify-centrum-na-windowsie.yml` also runs by itself on every pull request and push to `main` that touches a file of `pilnuje:` (`tests/test_skille_dla_zmiany.py` keeps its `paths` equal to it), among them the committed frontend build `src/rozliczenia/centrum/static/**`, which every change of the tab's menu, pages or window Ustawienia rewrites and the drive clicks through, and the server's answers the section Narzędzie shows (`configuration_router.py`, `tool_freshness.py`).
`run_on_github.py --help` says what a dispatch needs and why the verdict is about your local `HEAD`; a dispatch runs the pushed branch with that branch's skill.
To wait for a PR's own run, pass it with `--run` (`gh run list --workflow verify-centrum-na-windowsie.yml --branch <branch>`).

On a Windows machine (a disposable one: the run installs `requirements.txt` into this Python, as Dad's installation does), from the repository root, with the `dev` extras and Chromium installed (`py -3 -m pip install -e ".[dev]"`, `py -3 -m playwright install chromium`):

```powershell
py -3 .agents\skills\verify-centrum-na-windowsie\scripts\run_windows_verification.py [--feature <feature>]
```

`--feature instalacja`, `--feature komunikat-startu`, `--feature start-skrotem`, `--feature wskazanie-folderow`, or `--feature aktualizacja` drives one feature; the default `all` drives them all.
A single feature first drives its prerequisites (`PRZYGOTOWANIE <feature>` in `drive.txt`), which the verdict lists as `przygotowanie=`, not as verified.
Success prints `VERIFY OK | features=… | przygotowanie=… | evidence=… | scratch_removed=true`; anything else is `VERIFY FAIL | …`.

The runner refuses to start (`VERIFY FAIL | preflight`) off Windows, without the built frontend (`src/rozliczenia/centrum/static/index.html`), with a Python that has no `pythonw.exe` beside it (uv and venv Pythons are not Dad's), or while anything listens on Dad's port `47811`.
The port is fixed in the shortcut, so **one run per machine**, and never on a computer whose own Centrum is running.

It creates `<run dir>/runs/windows-<id>` with `windows_tool.prepare`, whose docstring lists the run's world (what the features rely on: `features/README.md`, Baseline preconditions); the feature `instalacja` installs the tool in it as Maks does.
Ready means the doctor's `DOCTOR OK` after `start-skrotem`.

Centrum inherits the run's boundaries from the drive's environment (`windows_tool.boundaries`), because the drive opens the `.lnk` with `os.startfile` like Explorer does for Dad:

- `BROWSER` is `<root>\przegladarka.cmd`, which appends the address to `<root>\otwarte-adresy.txt`;
- `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0` set `url.<origin>.insteadOf` for the tool's fixed GitHub address, so README's `git clone` and Aktualizacja narzędzia run against the run's origin.
  Diagnoza and the section Narzędzie of Ustawienia still ask the real GitHub API for the newest Wydanie, so the section's freshness depends on the network; `aktualizacja` needs it to read `Jest nowsza wersja` (see its Gotchas).

`CENTRUM_GITHUB_TOKEN` (the workflow's read-only `github.token`) leaves the drive's environment before anything starts, and `instalacja` writes it as Maks's `config\zgloszenia-klucz.txt`: Centrum asks GitHub's API with it, within the token's limit, instead of sharing the runner address's 60 requests an hour.
On GitHub the drive refuses to start without it; by hand on another Windows machine it runs without the file.
The Skrzynka Zgłoszeń refuses this token (it has no access to the Zgłoszenia repository), so the section Zgłoszenia of Ustawienia reads `Token odrzucony`; no feature here sends a Zgłoszenie.

## Doctor

The runner runs it after `start-skrotem` and after `aktualizacja` (`doctor-<feature>.txt`).
By hand:

```powershell
py -3 .agents\skills\verify-centrum-na-windowsie\scripts\windows_doctor.py --root "$runRoot"
```

`DOCTOR OK | pid=… | commit=… | process=pythonw.exe | tool=…` means port `47811` belongs to a process running this run's `run_centrum.py`, `/api/health` answers as `centrum-rozliczen`, and its commit is the clone's `HEAD`.

## Drive

`scripts/windows_drive/<feature>.py` holds each feature's steps; `windows_desktop.py` is the desktop harness (native windows through user32, processes and the port owner through PowerShell, desktop screenshots with `System.Drawing`).
The tab is Playwright for Python's headless Chromium at 1440×1000, `pl-PL`, on `http://127.0.0.1:47811/`, with the helpers of the window Ustawienia from `verify-centrum-rozliczen`'s `drive/common.py`.

## Evidence

`<run dir>/evidence/windows-<id>/` survives cleanup; on GitHub it is the artifact `verify-centrum-na-windowsie-<run id>-<attempt>`, which `run_on_github.py` downloads to `<run dir>/evidence/github-<run id>/`:

- `drive.txt`: every `STEP <feature> | <id>`, harness step (`harness:`), check (`ok:`), the log lines of each update, and the verdict; `doctor-*.txt`, `cleanup.txt`;
- `screenshots/NN-<step>.png` (the tab) and `pulpit/NN-<step>.png` (the whole desktop, with native windows); on failure `screenshots/zz-failure.png` and `pulpit/zz-failure.png`;
- `api/*.json`: `health` at each start and the settings after each picker;
- `state/`: the Centrum log, Dad's settings file, `otwarte-adresy.txt`, `skrot.json`, `proces-start.json`, `pip-instalacja.txt`, `git-log.txt` and `windows.json`.

Proof standards:

- Dad's path only: the `.lnk`, the tab, native windows, Explorer.
  A screen is proof together with the process facts, the Centrum log and the files Centrum wrote (settings, the clone's `HEAD`, `config/` bytes).
- The stand-ins are the browser recorder and the local origin; both are labelled `harness:` in `drive.txt`.
- Look at `pulpit/` after a change to a native window: a passing run does not judge how it looks.
- GitHub's runner is a stand-in for Dad's laptop.
  It does not prove: Dad's Polish Windows (code page 1250; the runner is English, 1252, so only `ó` can be the Polish letter in the tool's path, while the shortcut's own name `Centrum rozliczeń.lnk` is the same in both code pages), OneDrive's online-only files, Python from python.org via `py -3` (the runner's comes from `actions/setup-python`), Git for Windows installed outside `PATH`, Excel as the program for `.xlsx` (the runner has none, so the drive opens only a folder), a touch screen, and the real desktop.
  Those stay unverified until Dad's computer runs them.

## Cleanup

The runner's `finally` keeps the state in the evidence, then runs `scripts/windows_cleanup.py`, whose `--help` says what it stops and closes.
It removes the run root (making Git's read-only objects writable first) and refuses a directory that `windows_tool.prepare` did not create (no `.katalog-runu` file).
After a runner that was itself killed:

```powershell
py -3 .agents\skills\verify-centrum-na-windowsie\scripts\windows_cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists.

## Helpers

- `scripts/windows_tool.py`: the run's world (`prepare`, `boundaries`, `release`), imported by the drive.
- `scripts/windows_desktop.py`: native windows, processes, port owner, screenshots, imported by the drive.

Keep the map honest with `/pstack:maintain-verification-skill`.
