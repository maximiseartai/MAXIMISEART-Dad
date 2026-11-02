---
name: wydanie
description: Release a new Wydanie of the tool to Dad when Maks writes „wydaj nową wersję” (or asks for a release, a new version, or an urgent PATCH) - plan it from the newest green `main` commit with `tools/wydanie.py`, write the „Co nowego” note in Dad's language, run the `verify-*` skills on Dad's real files on Maks's Mac, show Maks the number, the note and the verification, and publish the tag and GitHub Release only after his explicit yes.
---

# Wydanie

A Wydanie is the only version that reaches Dad's computer (ADR 0014,
`GLOSSARY.md`): a tag `v0.MINOR.PATCH` on a `main` commit with a green
`Required CI status`, and a GitHub Release whose note Dad reads in Centrum's
Powiadomienie o nowej wersji. The tag is immutable and Dad's update never goes
back, so a bad Wydanie is fixed only by the next one. That is why Maks's
explicit yes is the gate, and nothing before it creates anything.

`tools/wydanie.py` does every mechanical step and every check; this skill is
the judgement around it. Work from Maks's main checkout
(`/Users/Max/MAXIMISEART-Dad`, which has `gh` logged in and Dad's real
Wzorce in `config/`) after `git -C /Users/Max/MAXIMISEART-Dad pull --ff-only`,
so the tool is the one on `main`, and keep run files in
`~/.t3/notes/wydanie/<tag>/`.

## 1. Plan

```bash
.venv/bin/python tools/wydanie.py plan --plik ~/.t3/notes/wydanie/plan.json
```

The last line is `PLAN OK | <tag> | <commit> | plik=…`; the lines above it list
the previous Wydanie, newer `main` commits skipped for red, running or missing
CI, every merged PR with its bump, and Dad's solved cases (Uwagi taty and
Zgłoszenia closed as completed in the Skrzynka Zgłoszeń since the previous
Wydanie). `WYDANIE ODMOWA | <reason>` means the tool refused (nothing green to
release yet, no access to the Skrzynka, `gh` logged out, a failed fetch); tell
Maks the reason and stop.

The proposed number is a proposal. `feat` PRs that change `src/` (what runs at
Dad's) bump MINOR, everything else PATCH, the first Wydanie is `0.1.0`. Read
the PR list yourself: a PR titled `fix` that Dad will clearly notice as new is
a reason to propose MINOR to Maks, and the other way round. An urgent repair
goes out as PATCH with the same steps.

## 2. Write „Co nowego”

Write the note to `~/.t3/notes/wydanie/<tag>/co-nowego.txt` for Dad: an
optional short intro sentence, an empty line, then 3-6 points, each one line
starting with `- ` and one sentence of what he will see or no longer have to
do:

```text
Ta wersja oszczędza Ci wpisywania.

- Przygotowanie pliku zbiorczego samo wpisuje ilości usług.
- Rozliczenia pracowników przy dużym okresie są dwa razy szybsze.
- Centrum rozliczeń pokazuje „Co nowego” jako listę.
```

Centrum's card `Nowa wersja` shows them under the heading `Co nowego` as the
intro and a bulleted list, one point under another
(`release_notes.whats_new`); a paragraph after the points makes the whole note
one paragraph again, so put nothing below them. Use the words of
`GLOSSARY.md` and his user guide (`Rozliczenie pracownika`, `Plik zbiorczy`,
`Centrum rozliczeń`), never PR numbers, module names or English. Leave the
list of his cases out:
the tool appends it from the plan in the one format Centrum reads
(`src/rozliczenia/centrum/release_notes.py`). The Release is public, so the
note names a case only by the title Dad gave it, never its content.

Preview the whole note exactly as it will be published; this creates nothing:

```bash
.venv/bin/python tools/wydanie.py wydaj --plan ~/.t3/notes/wydanie/plan.json \
  --co-nowego ~/.t3/notes/wydanie/<tag>/co-nowego.txt [--numer 0.x.y]
```

## 3. Verify the commit on Dad's real files

Verify the release commit itself, not your checkout: create a detached
worktree of the plan's `commit` and its own `.venv` (`git worktree add
--detach ~/.t3/worktrees/wydanie-<tag> <commit>`, then
`python3 tools/setup_worktree.py` inside it). From that worktree run, one heavy
run at a time:

- `verify-rozliczenia` with `--variant all chain-real-templates
  preparation-real-templates`: Dad's whole path, then the two variants on
  byte copies of his real Wzorce from the main checkout's `config/`.
- `verify-skoroszyty-w-excelu` with `--wzorce prawdziwe`: the files open in
  real Excel with his real Wzorce, links and row heights intact.
- `verify-centrum-rozliczen`: Centrum in the browser, the only way Dad starts
  either process.
- Every other `verify-*` skill that `tools/skille_dla_zmiany.py
  <previous Wydanie's commit>` names for this worktree, so the release diff
  gets the checks its files call for. For the first Wydanie that is every
  `verify-*` skill.

Load each skill and follow its own workflow. Record each verdict line. A
`VERIFY SKIP` (for example Wzorce missing from `config/`) is not a pass:
report it as a skip. Remove the worktree when the runs are done.

## 4. Ask Maks

Show Maks, in one message: the tag and commit, why this number (the bump and
the PRs that caused it, plus your own view if it differs), the skipped newer
commits and any higher Wydania off `main`, the full note from the preview, and
every verification verdict with its evidence path. Point him at the case list
as public text: a Zgłoszenie title is `<kod>: <Co się stało>` and can name a
Wykonawca, and Dad's own Uwaga titles are his words. Then wait for his
explicit yes to this number and this note, written by Maks himself; a yes
relayed by another agent does not count. A change to the number or the note after his answer goes back through
the preview and gets a new yes.

## 5. Publish

Only after Maks's yes:

```bash
.venv/bin/python tools/wydanie.py wydaj --plan ~/.t3/notes/wydanie/plan.json \
  --co-nowego ~/.t3/notes/wydanie/<tag>/co-nowego.txt [--numer 0.x.y] --potwierdzone-przez-maksa
```

It checks again that the commit is on `main`'s first-parent line with green
CI and that the number is higher than the newest Wydanie, creates the
annotated tag, pushes it (the pre-push gate lets only this tool push `v*`
tags) and creates the GitHub Release. The last line is `WYDANIE OK | <tag> |
<commit> | <Release URL>`; give Maks the URL. After a failure, run the same
`wydaj` command with the same plan again: it finishes the same Wydanie and
creates no second tag or Release. A fresh `plan` at that point would already
count the pushed tag as the previous Wydanie and find nothing to release.
