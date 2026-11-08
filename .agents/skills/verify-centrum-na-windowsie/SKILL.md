---
name: verify-centrum-na-windowsie
description: Verify Centrum rozliczeń on Windows the way Dad installs, starts and updates it - the tool cloned into a user folder with a space and a Polish letter, the desktop shortcut and pythonw.exe without a console, the native start-problem window, the native tkinter pickers, Explorer, and Aktualizacja narzędzia with the restart guardian - on GitHub's windows-latest runner (or any Windows machine), with desktop screenshots, the Centrum log and process facts as evidence. Use after changes to `launcher.py`, `platform.py`, `shortcut.py`, `restart_guardian.py`, `tool_update.py`, `tool_updates.py`, `version.py`, `start_problems.py`, `log.py`, `update_messages.py`, `server.py`, `shutdown.py`, `centrum/settings.py`, `run_centrum.py`, `install_centrum_shortcut.py`, `frontend/src/lib/tool-update.tsx` or `requirements.txt`, or when something works on the Mac but may not on Dad's Windows.
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
  - src/rozliczenia/centrum/update_messages.py
  - src/rozliczenia/centrum/version.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/centrum/shutdown.py
  - src/rozliczenia/centrum/settings.py
  - run_centrum.py
  - install_centrum_shortcut.py
  - frontend/src/lib/tool-update.tsx
  - requirements.txt
  - .github/workflows/verify-centrum-na-windowsie.yml
  - tests/fixtures/scenariusz_centrum.py
  - .agents/skills/verify-centrum-rozliczen/scripts/create_centrum_fixture.py
---

# Verify Centrum rozliczeń na Windowsie

Dad's computer is a Windows laptop (`docs/agents/komputer-taty.md`). `verify-centrum-rozliczen` proves Centrum's
screens on the Mac with a scripted platform adapter; this skill proves what only Windows can: the production
launcher started from the `.lnk` through `pythonw.exe`, Windows' own message box and file dialogs, Explorer, and
Aktualizacja narzędzia where Git for Windows, pip and the detached restart guardian replace a running `pythonw`.
Nothing on Dad's side is scripted: the only stand-ins are GitHub (a local "origin") and Dad's browser (a recorder of
the address Centrum opens). The drive answers native windows through user32 and drives the tab with Playwright.

## Launch

From macOS (or anywhere with `gh`), run it on GitHub's Windows machine and bring the evidence home. A run takes
about 10 minutes, as long as a foreground command may take, so start it in the background, wait for its end in the
same turn and read its last line:

```bash
.venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py            # dispatch on the current, pushed branch
.venv/bin/python .agents/skills/verify-centrum-na-windowsie/scripts/run_on_github.py --run <id> # wait for a run a PR or push started
```

The workflow `.github/workflows/verify-centrum-na-windowsie.yml` also runs by itself on every pull request and push
to `main` that touches the files in the description. A dispatch needs the workflow on `main` and then runs any pushed
branch (`--ref`, default the current one) with that branch's skill. To wait for a PR's own run instead, pass it with
`--run` (`gh run list --workflow verify-centrum-na-windowsie.yml --branch <branch>`).
The verdict is about your local `HEAD`: a run of another commit ends in `VERIFY FAIL`, the last line names the run's
commit (`head=`), and a dispatch refuses to start until `origin/<ref>` is your `HEAD`.

On a Windows machine (a disposable one: the run installs `requirements.txt` into this Python, as Dad's
installation does), from the repository root, with the `dev` extras and Chromium installed
(`py -3 -m pip install -e ".[dev]"`, `py -3 -m playwright install chromium`):

```powershell
py -3 .agents\skills\verify-centrum-na-windowsie\scripts\run_windows_verification.py [--feature <feature>]
```

`--feature instalacja`, `--feature komunikat-startu`, `--feature start-skrotem`, `--feature wskazanie-folderow`, or
`--feature aktualizacja` drives one feature, whose recipe is `features/<feature>.md`; the default `all` drives them all. A single
feature first drives its prerequisites (`PRZYGOTOWANIE <feature>` in `drive.txt`), which the verdict lists as
`przygotowanie=`, not as verified. Success prints `VERIFY OK | features=… | przygotowanie=… | evidence=… | scratch_removed=true`; anything
else is `VERIFY FAIL | …`.

The runner refuses to start (`VERIFY FAIL | preflight`) off Windows, without the built frontend
(`src/rozliczenia/centrum/static/index.html`), with a Python that has no `pythonw.exe` beside it (uv and venv
Pythons are not Dad's), or while anything listens on Dad's port `47811`. The port is fixed in the shortcut, so
**one run per machine**, and never on a computer whose own Centrum is running.

It creates `<run dir>/runs/windows-<id>` (`windows_tool.prepare`; `--run-dir`, default `.verification`): Dad's synthetic folder okresów `INEA`,
Rejestr zleceń and `config/` from `verify-centrum-rozliczen`'s fixture, and a bare "origin" with three versions of
the tool built from this checkout's working tree (tracked and untracked files): `first`, `newest` (only
`requirements.txt` changes, so the update installs libraries with nothing new to fetch) and `not_starting`. Its only
Wydanie `v0.1.0` is `first` and its `main` is one version ahead on `newest`. The feature `instalacja` runs README's
PowerShell, which clones the tool into `<root>\Users\Józef Kowalski\MAXIMISEART-Dad` and resets it to the newest
Wydanie, and makes the shortcut in `<root>\Pulpit`, never on the real desktop. Ready means the doctor's `DOCTOR OK` after `start-skrotem`.

Centrum inherits the run's boundaries from the drive's environment (`windows_tool.boundaries`), because the drive
opens the `.lnk` with `os.startfile` like Explorer does for Dad:

- `BROWSER` is `<root>\przegladarka.cmd`, which appends the address to `<root>\otwarte-adresy.txt`;
- `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0` set `url.<origin>.insteadOf` for the tool's fixed GitHub
  address, so README's `git clone` and Aktualizacja narzędzia run against the run's origin. Diagnoza and
  Konfiguracja still ask the real GitHub API for the newest Wydanie, so the card's freshness depends on the network;
  `aktualizacja` needs it to read `Jest nowsza wersja` (see its Gotchas).

Teardown is the runner's `finally`: it keeps the state in the evidence, then runs the cleanup.

## Doctor

The runner runs it after `start-skrotem` and after `aktualizacja` (`doctor-<feature>.txt`). By hand:

```powershell
py -3 .agents\skills\verify-centrum-na-windowsie\scripts\windows_doctor.py --root "$runRoot"
```

`DOCTOR OK | pid=… | commit=… | process=pythonw.exe | tool=…` means port `47811` belongs to a process running this
run's `run_centrum.py`, `/api/health` answers as `centrum-rozliczen`, and its commit is the clone's `HEAD`. It only
reads.

## Drive

`scripts/windows_drive/<feature>.py` holds each feature's steps; `windows_desktop.py` is the desktop harness:

- native windows by class and title, owned by Centrum's process: the message box (`#32770`, title
  `Centrum rozliczeń`), the pickers (`#32770`, titles `Wybierz folder okresów (np. Załączniki albo INEA)` and
  `Wybierz plik Rejestru zleceń`), Explorer (`CabinetWClass`, title with the folder's name);
- a picker is answered like Dad answers it: the path typed into the dialog's name box (control `1148`) and its
  confirm button (control `1`) clicked; a message box closes with `WM_CLOSE`, like its X;
- processes and the port owner from `Win32_Process` and `Get-NetTCPConnection`; desktop screenshots with
  `System.Drawing`.

The tab is Playwright for Python's headless Chromium at 1440×1000, `pl-PL`, on `http://127.0.0.1:47811/`, with the
same ARIA handles as `verify-centrum-rozliczen`: buttons `Wskaż folder okresów`, `Wskaż Rejestr zleceń`,
`Folder okresu, okres 15_21_09_2026`, `Zaktualizuj narzędzie`; table `Tablica okresów`; group `Rejestr zleceń`;
region `Narzędzie`; dialog `Zaktualizowano` in region `Notifications`. Recipes are in `features/`.

## Evidence

`<run dir>/evidence/windows-<id>/` survives cleanup; on GitHub it is the artifact
`verify-centrum-na-windowsie-<run id>-<attempt>`, which `run_on_github.py` downloads to
`<run dir>/evidence/github-<run id>/`:

- `drive.txt`: every `STEP <feature> | <id>`, harness step (`harness:`), check (`ok:`), the log lines of each update,
  and the verdict; `doctor-*.txt`, `cleanup.txt`;
- `screenshots/NN-<step>.png` (the tab) and `pulpit/NN-<step>.png` (the whole desktop, with native windows); on
  failure `screenshots/zz-failure.png` and `pulpit/zz-failure.png`;
- `api/*.json`: `health` at each start and the settings after each picker;
- `state/`: the Centrum log, Dad's settings file, `otwarte-adresy.txt`, `skrot.json`, `proces-start.json`,
  `pip-instalacja.txt`, `git-log.txt` and `windows.json`.

Proof standards:

- Dad's path only: the `.lnk`, the tab, native windows, Explorer. A screen is proof together with the process facts,
  the Centrum log and the files Centrum wrote (settings, the clone's `HEAD`, `config/` bytes).
- The stand-ins are the browser recorder and the local origin; both are labelled `harness:` in `drive.txt`.
- Look at `pulpit/` after a change to a native window: a passing run does not judge how it looks.
- GitHub's runner is a stand-in for Dad's laptop. It does not prove: Dad's Polish Windows (code page 1250; the runner
  is English, 1252, so `WScript.Shell` writes the shortcut as `Centrum rozliczen.lnk` and only `ó` can be the
  Polish letter in the tool's path), OneDrive's online-only files, Python from python.org via `py -3` (the runner's comes from
  `actions/setup-python`), Git for Windows installed outside `PATH`, Excel as the program for `.xlsx` (the runner has
  none, so the drive opens only a folder), a touch screen, and the real desktop. Those stay unverified until Dad's
  computer runs them.

## Cleanup

The runner calls `scripts/windows_cleanup.py` in `finally`. It stops only processes whose command line contains the
run root (Centrum from the run's tool, the restart guardian, Git and pip below them), closes Explorer windows on the
run's folders, and removes the run root (making Git's read-only objects writable first). It refuses a directory that
`windows_tool.prepare` did not create (no `.katalog-runu` file). It never kills by process name and never touches the
evidence. After a runner that was itself killed:

```powershell
py -3 .agents\skills\verify-centrum-na-windowsie\scripts\windows_cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists.

## Helpers

- `scripts/run_on_github.py [--feature …] [--ref …] | --run <id>`: run on GitHub's Windows and download the evidence.
- `scripts/run_windows_verification.py [--feature …]`: the one-command orchestrator on Windows.
- `scripts/windows_doctor.py --root <run root>`: the read-only doctor.
- `scripts/windows_cleanup.py --root <run root>`: stop and remove one run.
- `scripts/windows_tool.py`: the run's world (`prepare`, `boundaries`, `release`), imported by the drive.
- `scripts/windows_desktop.py`: native windows, processes, port owner, screenshots, imported by the drive.

Read `features/README.md` for the conventions, then the chosen feature's `features/<feature>.md`, and keep the map
honest with `/pstack:maintain-verification-skill`.
