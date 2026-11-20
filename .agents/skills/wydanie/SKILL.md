---
name: wydanie
description: Wydanie (release) of the tool to Dad - plan, „Co nowego” note, `verify-*` on Dad's real files, publish after Maks's explicit yes. Use when Maks writes „wydaj nową wersję” or asks for a release, a new version or an urgent PATCH.
---

# Wydanie

A Wydanie is the only version that reaches Dad's computer (ADR 0014, `GLOSSARY.md`): a tag `v0.MINOR.PATCH` on a `main` commit with a green `Required CI status`, and a GitHub Release whose note Dad reads in Centrum's Powiadomienie o nowej wersji.
The tag is immutable and Dad's update never goes back, so a bad Wydanie is fixed only by the next one.
That is why Maks's explicit yes is the gate, and nothing before it creates anything.

`tools/wydanie.py` does every mechanical step and every check (its `--help` says what `plan` and `wydaj` do); this skill is the judgement around it.
Work from Maks's main checkout (`/Users/Max/MAXIMISEART-Dad`, which has `gh` logged in and Dad's real Wzorce in `config/`) after `git -C /Users/Max/MAXIMISEART-Dad pull --ff-only`, so the tool is the one on `main`, and keep run files in `~/.t3/notes/wydanie/<tag>/`.

## 1. Plan

```bash
.venv/bin/python tools/wydanie.py plan --plik ~/.t3/notes/wydanie/plan.json
```

The last line is `PLAN OK | <tag> | <commit> | plik=…`; the lines above it list the previous Wydanie, skipped newer `main` commits, every merged PR with its bump, and Dad's solved cases.
`WYDANIE ODMOWA | <reason>` means the tool refused; tell Maks the reason and stop.

The proposed number is a proposal.
`feat` PRs that change `src/` (what runs at Dad's) bump MINOR, everything else PATCH, the first Wydanie is `0.1.0`.
Read the PR list yourself: a PR titled `fix` that Dad will clearly notice as new is a reason to propose MINOR to Maks, and the other way round.
An urgent repair goes out as PATCH with the same steps.

## 2. Write „Co nowego”

Write the note to `~/.t3/notes/wydanie/<tag>/co-nowego.txt` for Dad: an optional short intro sentence, an empty line, then 3-6 points, each one line starting with `- ` and one sentence of what he will see or no longer have to do:

```text
Ta wersja oszczędza Ci wpisywania.

- Przygotowanie pliku zbiorczego samo wpisuje ilości usług.
- Rozliczenia pracowników przy dużym okresie są dwa razy szybsze.
- Centrum rozliczeń pokazuje „Co nowego” jako listę.
```

Centrum's card `Nowa wersja` shows the intro and the points as a bulleted list (`release_notes.whats_new`), and a paragraph after the points makes the whole note one paragraph again, so put nothing below them.
Use the words of `GLOSSARY.md` and his user guide (`Rozliczenie pracownika`, `Plik zbiorczy`, `Centrum rozliczeń`), never PR numbers, module names or English.
Leave the list of his cases out: the tool appends it from the plan in the one format Centrum reads (`src/rozliczenia/centrum/release_notes.py`).
The Release is public, so the note names a case only by the title Dad gave it, never its content.

Preview the whole note exactly as it will be published; this creates nothing:

```bash
.venv/bin/python tools/wydanie.py wydaj --plan ~/.t3/notes/wydanie/plan.json \
  --co-nowego ~/.t3/notes/wydanie/<tag>/co-nowego.txt [--numer 0.x.y]
```

## 3. Verify the commit on Dad's real files

Verify the release commit itself, not your checkout: create a detached worktree of the plan's `commit` and its own `.venv` (`git worktree add --detach ~/.t3/worktrees/wydanie-<tag> <commit>`, then `python3 tools/setup_worktree.py` inside it).
From that worktree run, one heavy run at a time:

- `verify-rozliczenia` with `--variant all chain-real-templates preparation-real-templates`: Dad's whole path, then the two variants on byte copies of his real Wzorce from the main checkout's `config/`.
- `verify-skoroszyty-w-excelu` with `--wzorce prawdziwe`: the files open in real Excel with his real Wzorce, links and row heights intact.
- `verify-centrum-rozliczen`: Centrum in the browser, the only way Dad starts either process.
- Every other `verify-*` skill that `tools/skille_dla_zmiany.py <previous Wydanie's commit>` names for this worktree, so the release diff gets the checks its files call for.
  For the first Wydanie that is every `verify-*` skill.
- Both probes of Dad's real mailbox, below.

Load each skill and follow its own workflow.
Record each verdict line.
A `VERIFY SKIP` (for example Wzorce missing from `config/`) is not a pass: report it as a skip.
A FAIL of a `verify-*` skill or of a probe stops the Wydanie: step 4 shows it, and this commit is not published.
Remove the worktree when the runs are done.

### Probes of Dad's real mailbox

Every Wydanie runs both probes, like the `verify-*` skills, without asking Maks (his decision of 19.11.2026): `tools/proba_skrzynki_raportow.py` reads Dad's Gmail read-only, and `tools/proba_przypomnien.py` sends one reminder to Maks's own address only.
They run from the release worktree on the machine whose main checkout holds the access file `config/skrzynka-raportow.txt`, today only Maks's Mac; elsewhere both are a skip with the reason „brak pliku dostępu”.
The data rules stay: never open the access file, keep every file of the probes in `~/.t3/notes/wydanie/<tag>/proby/` (rights `0700`), and only stdout lines, counts and forms rebuilt from synthetic data leave it.

Since 19.11.2026 the Mac's `config/` (`/Users/Max/MAXIMISEART-Dad/config`) holds what both probes read: the Lista Wykonawców from the Zmiany z Wydania, Ustawienia przypomnień with a probe footer and the switch off, and Ustawienia naming an INTERMAX copy and an empty folder okresów in `~/.t3/notes/proba-przypomnien-mac/`.
The switch stays off because a Centrum started from the main checkout sends reminders to Dad's real Wykonawcy; the probe turns them on in its own memory only (`--wlaczone-od`).

1. Apply the newest Zmiany z Wydania to that `config/`, as a Centrum start from the main checkout would: `/Users/Max/MAXIMISEART-Dad/.venv/bin/python -I ~/.t3/notes/config-migracja-2026-11-19/migruj.py`.
   It builds `CentrumSettings` as `src/rozliczenia/centrum/app.py` does and calls `apply_release_changes()`; `logs/centrum-rozliczen.log` of the main checkout says `zastosowano` or `bez-zmian` per change.
2. Create the folder of the probes, `install -d -m 700 ~/.t3/notes/wydanie/<tag>/proby`, because the IMAP probe refuses a review file without its folder.
   Then run the IMAP probe with its review, as `verify-centrum-rozliczen` `features/wpisanie-raportow.md`, section „Real mailbox”, says, with `--config /Users/Max/MAXIMISEART-Dad/config --przeglad ~/.t3/notes/wydanie/<tag>/proby/wpisy.txt`, and save stdout as `proby/imap.txt`.
3. Run `.venv/bin/python tools/proba_przypomnien.py --config /Users/Max/MAXIMISEART-Dad/config --wlaczone-od "$(date -v-3d +%F)" --do "$(cat ~/.t3/notes/wydanie/adres-maksa-do-proby.txt)"` and save stdout as `proby/przypomnienia.txt`.
   The address is Maks's own, kept only in that local note, because the repository is public; with the note missing, ask Maks for his address once and save it there (`0600`).
   Outside the reminder hours the probe sends the reminder for yesterday, so it runs at any hour.
   The INTERMAX copy has no orders in the last days, so the counts are zero, and the probe still checks the way: mailbox, „Wysłane”, text, footer, SMTP.

The verdicts are the last lines `PROBA IMAP OK|FAIL | …` and `PROBA PRZYPOMNIEN OK|FAIL | …`; the report of step 4 gets both lines, the review's counts per checklist item, and each finding as its synthetic form.

## 4. Ask Maks

Show Maks, in one message: the tag and commit, why this number (the bump and the PRs that caused it, plus your own view if it differs), the skipped newer commits and any higher Wydania off `main`, the full note from the preview, and every verification verdict with its evidence path.
Point him at the case list as public text: a Zgłoszenie title is `<kod>: <Co się stało>` and can name a Wykonawca, and Dad's own Uwaga titles are his words.
Then wait for his explicit yes to this number and this note, written by Maks himself; a yes relayed by another agent does not count.
A change to the number or the note after his answer goes back through the preview and gets a new yes.

## 5. Publish

Only after Maks's yes:

```bash
.venv/bin/python tools/wydanie.py wydaj --plan ~/.t3/notes/wydanie/plan.json \
  --co-nowego ~/.t3/notes/wydanie/<tag>/co-nowego.txt [--numer 0.x.y] --potwierdzone-przez-maksa
```

The last line is `WYDANIE OK | <tag> | <commit> | <Release URL>`; give Maks the URL.
After a failure, run the same `wydaj` command with the same plan again: it finishes the same Wydanie.
A fresh `plan` at that point would already count the pushed tag as the previous Wydanie and find nothing to release.
