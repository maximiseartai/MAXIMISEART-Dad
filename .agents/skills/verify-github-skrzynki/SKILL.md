---
name: verify-github-skrzynki
description: Verify Centrum's two GitHub clients against the real GitHub - Skrzynka Zgłoszeń (`GitHubReportBox` and `KeyedBox` - issues, comments, edits, labelled lists with paging and `include_closed`, bad key, deleted issue, content limits) on the private empty trial repository `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba`, the Archiwum Logów okresu (`archive`, `open_archive`, `upload`, `remove` and `archive_url` - a Release with files over a page, a tag or file of the same name, the replaced file, the download link) on the trial repository with a commit `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba-archiwum`, and Aktualność narzędzia (`tool_freshness` - tags with paging, the newest Wydanie on `main`, GitHub Releases, compare and the first-parent line) by reading the public tool repository - with every exchange recorded, a verdict on outcomes expected from the domain, an offline replay of the recordings, and a check that the test fakes answer like the recorded GitHub. Use after a change to `report_box.py`, `keyed_box.py`, `tool_freshness.py`, their test fakes, or when a review asks what GitHub really answers.
pilnuje:
  - src/rozliczenia/centrum/report_box.py
  - src/rozliczenia/centrum/keyed_box.py
  - src/rozliczenia/centrum/tool_freshness.py
  - tests/test_skrzynka_zgloszen_github.py
  - tests/test_aktualnosc_narzedzia.py
ci: .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py odtworz
---

# Verify GitHub Skrzynki

Both GitHub clients of Centrum know GitHub only from answers that the tests' authors wrote (`ScriptedTransport` and
`GitHubOnTransport` in `tests/test_skrzynka_zgloszen_github.py`, the server `_GitHub` in
`tests/test_aktualnosc_narzedzia.py`). This skill drives the real client code against the real GitHub, records what
GitHub answered, judges each outcome against what the domain says it must be, and keeps the recordings so CI replays
the same client on real answers and checks the fakes against them, as `tools/zgodnosc_efenix.py` does for efenix.

## What CI runs and what stays local

CI runs `github_skrzynki.py odtworz` (the `ci:` key) in Mutation checks whenever a change touches a file in `pilnuje:`
or this skill's folder: the client replayed offline on `nagrania/` and the fake-fidelity check (`--feature
wiernosc-atrap`). `check_github_skrzynki_mutations.py` runs in full CI on `main` and nightly on `main`. Run them locally
only to reproduce a red CI step or the night's issue, or while you work on one feature.
What stays with you is the live run (`na-zywo`): it needs the network, the `gh` login and the trial repository, so CI
never runs it. Run it when a change alters what a client sends (a new request, a new field read, a new status mapped),
because the replay refuses any request it has no recording for, and then commit the new recordings with
`--zapisz-nagrania`. Run it with both keys (below), and read the verdict lines yourself: a new answer from GitHub is a
finding for the PR, not something to make pass.

## Boundaries

- Writes go only to the two trial repositories (`github_wymiana.TRIALS`, both private): `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba`
  (empty: no commit, no Release) for `skrzynka`, and `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba-archiwum` (one
  commit, README on `main`) for `archiwum`, because a Release needs a commit. The client transport
  (`github_wymiana.LiveTransport`) moves each request from the Skrzynka address (`report_box.REPOSITORY`) to its
  feature's trial repository and raises `OutsideTrial` for any other address; the harness (`Admin`) refuses writes
  outside them and follows no redirect with a key. `src/` is not changed: the client gets the transport, as in the
  tests.
- The real Skrzynka `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia` is never asked. The public tool repository
  `maximiseartai/MAXIMISEART-Dad` is only read (GET through `GitHubProxy`).
- Keys: the client key is `gh auth token` (OAuth, `gho_`) or `--klucz-plik <file>`, Maks's fine-grained token for the
  trial repositories like Dad's (Issues RW, Contents RW, Metadata R): `~/.config/maximiseart/token-repo-probne.txt`. The
  script reads the file and never prints it; evidence and recordings name only the kind of key. Cleanup and the
  harness always use the `gh` key (admin of both trial repositories: only it can delete issues and tags).
- Aktualność asks without a key, like Centrum. GitHub allows 60 such requests per hour per address and the agents on
  this Mac share it; `--aktualnosc-z-kluczem` asks with the `gh` key instead, and the verdict then says so in
  `NIESPRAWDZONE`.

## Doctor

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py doctor [--feature skrzynka|archiwum|aktualnosc] [--klucz-plik <file>] [--aktualnosc-z-kluczem]
```

Read only. `DOCTOR OK | klucz=<kind> | sprzatanie=<kind> | repo=… prywatne | limit=… | pozostalosci=0 |
limit_aktualnosci=…` means: the client key sees the feature's trial repository, the `gh` key is its admin, it is
private, neither trial repository has an issue, label, Release or tag of a run, none of the Skrzynka labels exists yet
(`skrzynka`), the archive trial repository has a commit and no Release or tag at all (`archiwum`), and both rate
limits leave room for a run. `DOCTOR FAIL | <reasons>` (exit 2) names what to fix; `na-zywo` runs the doctor first and stops on it.

## Launch and drive

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py na-zywo --feature all --zapisz-nagrania --run-dir ~/.t3/notes/verify-github-skrzynki
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py na-zywo --feature skrzynka --klucz-plik ~/.config/maximiseart/token-repo-probne.txt --zapisz-nagrania --run-dir ~/.t3/notes/verify-github-skrzynki
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py na-zywo --feature archiwum --klucz-plik ~/.config/maximiseart/token-repo-probne.txt --zapisz-nagrania --run-dir ~/.t3/notes/verify-github-skrzynki
```

`--feature skrzynka` drives the Skrzynka Zgłoszeń, `--feature archiwum` the Archiwum Logów okresu,
`--feature aktualnosc` Aktualność narzędzia, `all` all three; each live run ends with `--feature wiernosc-atrap` on the new
recordings. A Skrzynka run takes about 8 minutes (it creates 101 issues and 101 comments for the paging cases, one
write per second as GitHub asks) and an Archiwum run about 3 (101 files for the paging case), so start them as
background commands and wait for the notification. Keep `--run-dir` out of `/tmp`. On 2026-11-05 the third Skrzynka run within 25 minutes
got `Unreachable()` already in preparation, with no answer from GitHub in its log, and a run an hour later passed. The
cause is not confirmed (GitHub's limit on content one account creates is a guess), so leave about an hour between
Skrzynka runs, also between the two keys, and treat a preparation `Unreachable` soon after another run as that.

Each feature is a table of cases (`CASES` in `github_przypadki_skrzynki.py`, `github_przypadki_archiwum.py` and
`github_przypadki_aktualnosci.py`). A
case prepares the trial repository through the harness or the client without recording (labels, closing an issue as
Maks does, deleting one, the 101 issues), calls the client once with recording, and judges the outcome. The expected
outcome comes from `GLOSSARY.md`, ADR 0007, 0014 and 0015 and the docstrings of `report_box`, `keyed_box`,
`outbox._deliver_archive` and `tool_freshness`, never from a run; Aktualność takes its truth from Git (`git ls-remote` and `git log --first-parent`).
The recipes and the expected outcome of each case are in `features/<feature>.md`.

## Replay

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py odtworz [--feature skrzynka|aktualnosc|wiernosc-atrap|all]
```

Offline: every recording in `nagrania/` (`skrzynka-<kind of key>.json` and `archiwum-<kind of key>.json` for each
key that ran, `aktualnosc.json`)
through the same cases with `ReplayTransport` or a replaying `GitHubProxy`. A request the recording does not have, in
another order or with another body, and a recorded request the client no longer sends, are failures.

## Evidence and verdict

`<run dir>/evidence/github-<id>/` survives cleanup: `doctor.txt`, `przebieg.txt` (every line below), `harness.txt`
(every harness request with its status), `sprzatanie.txt` (what cleanup removed, the state before and after) and
`nagrania/`. A replay writes `<run dir>/evidence/odtworzenie-<id>/przebieg.txt`.

- `PRZYPADEK <recording>/<case> | GitHub: <method path → status, …> | klient: <outcome> | oczekiwane: <domain> | OK`
  or `| ROZJAZD: …`: what GitHub answered and what the client made of it.
- `WIERNOŚĆ | <case> | <kind> | OK` or `RÓŻNICA | wiernosc-atrap | …`; `BEZ ATRAPY | <case> | <kind> <status>` lists a
  recorded answer no mapped fake models (information, not a failure).
- `NIESPRAWDZONE | …`: what the run does not check, always printed.
- Last line `VERIFY OK | features=… | przypadki=n/n | klucze=… | evidence=…` (exit 0) only when every case of every
  table gave its expected outcome, every fidelity row agrees and the trial repository is back to its state before the
  run; anything else is `VERIFY FAIL | rozjazdy=… | …` (exit 1). A case missing from a recording is a failure.

Recordings hold method, path without host (uploads keep `uploads.github.com`), SHA-256 and length of the request
body (no headers, so no key), status, `Link` and the response body cut to the fields the clients read and GitHub's
error fields (`github_wymiana.KEPT`); texts over 2000 characters become their length and hash. They hold no data of
Dad's: only synthetic run text, issue numbers, comment, Release and file ids of the trial repositories, and tags and
commits of the public tool repository.

## Cleanup

A live run cleans up in its `finally`. By hand, after a run that was killed:

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_sprzatanie.py --root <run dir>/runs/github-<id>
```

It deletes only what carries this run's marker: issues whose body has `<!-- verify-github-skrzynki run=<id> -->`
(GraphQL `deleteIssue`, because a closed issue would stay in the next run's `include_closed` list), labels whose
description has `verify-github-skrzynki run=<id>`, the label GitHub created for the run's issue (only when the run's
ledger recorded it and the state before the run did not have it), Releases with the marker in their description
together with their files (only when every file has the run id in its name), and tags named `logi-verify-<id>…`. It
asks each issue and Release of the run's ledger directly too, because GitHub's lists lag behind (see the Skrzynka
gotchas), and retries until labels, issues, Releases and tags of both trial repositories match the state before the
run. Then it removes the run directory (`.katalog-runu`) and
keeps the evidence. It never cleans by name.

## When the check fails

- A `ROZJAZD` in a live run is either a client defect (the domain says X, GitHub answered Y, the client made Z of it)
  or a wrong expectation in the case table. Decide from the domain source the case names, never from the run; fix
  the client only if the user asks, and report the GitHub answer either way.
- A `RÓŻNICA` means a test fake answers a situation differently from GitHub: fix the fake (it is the claim that is
  wrong) or, when GitHub answers differently for different keys, model both.
- A replay failure after a change to a client means the client now sends something else: run `na-zywo` again with
  both keys and commit the new recordings with the change.

## After changing the checker or a client

CI proves the replay can still fail: the night on `main` runs the script below after a change of this skill's folder.
Run it locally only to reproduce a red Mutation checks step or the night's issue, or after you rewrite a mutation:

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/check_github_skrzynki_mutations.py
```

It must end with `MUTACJE OK`: 401 taken as Rejected, 404 not a refusal, 422 not a rejection, the second page of a
list lost, `include_closed` ignored, the close reason read from `state`, a refused list that does not refuse the key,
the second page of the Archiwum's files lost, `remove` of another file, the first Release taken as the Archiwum of the
tag, a file that arrived read as cut off, the file's label lost, the download link without `/download/`, `Link`
without its next page, a 404 of compare taken as no answer, any merged PR taken as the tip of `main`, a fake of the
deleted issue that answers 410 and a fake of a file of the same name that answers 400 all end the replay in `VERIFY
FAIL`. A mutation reported as `NIEAKTUALNA`
no longer matches its file: rewrite its anchor against the new code so it breaks the same behaviour again.

## Helpers

- `scripts/github_skrzynki.py doctor|na-zywo|odtworz [--feature …]`: the runner.
- `scripts/github_sprzatanie.py --root <run root>`: cleanup of one run.
- `scripts/github_wymiana.py`: transports, proxy, harness, recordings and the boundary guards.
- `scripts/github_przypadki_skrzynki.py`, `scripts/github_przypadki_aktualnosci.py`: the case tables.
- `scripts/github_wiernosc.py`: the fake-fidelity check and its mapping of recorded situations to tests (`MAPPING`).

Read `features/README.md` for the conventions, then the chosen feature's file, and keep the map honest with
`/pstack:maintain-verification-skill`.
