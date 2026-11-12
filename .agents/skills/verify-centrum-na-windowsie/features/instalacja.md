# Instalacja

Maks installs the tool once on Dad's computer (README, `Instalacja lokalna`): a Git clone whose `main` is reset to
the newest Wydanie (ADR 0014) with README's PowerShell, Dad's own konfiguracja wykonawców and Wzorce copied into
`config/`, the libraries installed with `py -3 -m pip install -r requirements.txt`, and the shortcut „Centrum rozliczeń” on
the desktop and in the Autostart folder, both made by `py -3 install_centrum_shortcut.py` (ADR 0030). The tool lives on Dad's `C:` in his user folder, whose name
has a space and a Polish letter, and so does the tool's folder here.

## Sub-features

- `klon`: README's PowerShell lines up to `git reset --hard $wydanie`, run in Windows PowerShell in `<root>\Users\Józef Kowalski`, exit 0 and leave the clone in `<root>\Users\Józef Kowalski\MAXIMISEART-Dad` on `first` (the newest Wydanie `v0.1.0`, while the origin's `main` is on `newest`), on branch `main`, with `origin` the tool's GitHub address.
- `pliki-taty`: Dad's `worker_mapping.yaml` and three Wzorce in `config/` leave `git status --porcelain --untracked-files=all` empty (Git ignores them), so an update never sees them as local changes.
- `biblioteki`: `py -3 -m pip install --disable-pip-version-check -r requirements.txt` in the tool's folder exits 0.
- `skrot`: `install_centrum_shortcut.py --folder <root>\Pulpit --folder-autostartu <root>\Autostart` exits 0, prints `Utworzono skrót „Centrum rozliczeń”: <folder>…`, makes exactly one `.lnk` there, named `Centrum rozliczeń.lnk` when the machine's ANSI code page can write `ń` (Dad's 1250), and the `.lnk` starts `pythonw.exe` beside this Python with the argument `"<tool>\run_centrum.py"`, works in the tool's folder, and has the icon `<tool>\src\rozliczenia\centrum\centrum-rozliczen.ico,0`.
- `autostart`: the same step prints `Utworzono skrót „Centrum rozliczeń” w Autostarcie (start po zalogowaniu, bez karty): <folder>…` and makes exactly one `.lnk` in `<root>\Autostart`, with the desktop shortcut's name, and that `.lnk` is the desktop one with the arguments `"<tool>\run_centrum.py" "--no-browser"`, so Centrum starts at Dad's login without a tab.

## How to get to it (user POV)

- Dad never does this himself; Maks does it once at Dad's computer, following README `Instalacja lokalna`. Dad sees only the shortcut on his desktop, and Centrum already running after he logs in to Windows.

## Driving it with the Windows harness

Preconditions:

- A fresh run root from `windows_tool.prepare`; the tool's folder does not exist yet.

- **Clone.** Take README's `powershell` block of `Instalacja lokalna`; its last line must be `py -3 -m pip install -r requirements.txt` and the one before `git reset --hard …`, or the step fails. Write the lines before pip to `<root>\instalacja.ps1` and run it with `powershell -File` in `<root>\Users\Józef Kowalski`, with this machine's Git configuration and the boundaries (its `git clone https://github.com/…` reaches the origin). The output is printed as `README: …`. `git rev-parse HEAD` is `versions.first`, `git branch --show-current` is `main`, `git config --get remote.origin.url` is the GitHub address (`git remote get-url` would show the rewritten origin).
- **Dad's files.** Copy every path of `dad_config` (`windows.json`) into `<tool>\config\`. `git status --porcelain --untracked-files=all` is empty.
- **Libraries.** README's pip line, run as `<python> -m pip install --disable-pip-version-check -r requirements.txt` in the tool's folder (labelled `harness:`); exit 0. Output goes to `state/pip-instalacja.txt`.
- **Shortcut.** Run `<python> install_centrum_shortcut.py --folder <root>\Pulpit --folder-autostartu <root>\Autostart` in the tool's folder; exit 0 and the printed line. List the folder's `.lnk` files and print the ANSI code page (`GetACP`). When that code page cannot write the name, the one `.lnk` there is the shortcut (labelled `harness:`), and later features start that one. Read the `.lnk` through `WScript.Shell` (`state/skrot.json`): `TargetPath`, `Arguments`, `WorkingDirectory`, `IconLocation` as in the sub-feature.
- **Autostart.** List `<root>\Autostart`'s `.lnk` files: exactly one, with the name of the desktop shortcut. Read it through `WScript.Shell` (`state/skrot-autostart.json`): every field equals the desktop shortcut's except `Arguments`, which adds `"--no-browser"`.
- **Proof.** `drive.txt` steps `instalacja | …`, `state/skrot.json`, `state/skrot-autostart.json`, `state/pip-instalacja.txt`.

## Gotchas

- The shortcuts go to `<root>\Pulpit` and `<root>\Autostart`, never to the real desktop or `shell:startup`: on a developer's Windows machine the real `Centrum rozliczeń.lnk` would be overwritten, and a login would start Centrum from a run root the cleanup removed.
- The origin's `main` is one version past its Wydanie, so a clone that skipped README's choice of the Wydanie would stand on `newest` and fail `klon`.
- README's `powershell` block runs as written except its pip line; a README change that moves or splits the block changes this step, and the step fails rather than guess.
- `<python>` is the Python that runs the drive. On GitHub it comes from `actions/setup-python`, not from python.org through `py -3` like Dad's. That gap is listed in `SKILL.md` and stays unverified.
- `WScript.Shell`, which `shortcut.py` uses, writes the shortcut's paths through the ANSI code page. GitHub's runner has 1252, which has no `ń`, so there the shortcut is `Centrum rozliczen.lnk` and the step says so; Dad's Polish Windows has 1250. A path character outside Dad's code page would break his shortcut the same way, which is why the tool's folder here uses `ó`, a letter both code pages have.
- Child output is captured with `PYTHONIOENCODING=utf-8`, what Dad's console shows; without it a pipe on an English runner (code page 1252) cannot encode `ś` and the step would fail for a reason Dad never meets.
