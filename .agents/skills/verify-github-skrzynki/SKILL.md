---
name: verify-github-skrzynki
description: Verify Centrum's two GitHub clients against the real GitHub - Skrzynka Zgłoszeń (`GitHubReportBox` and `KeyedBox` - issues, comments, edits, labelled lists with paging and `include_closed`, Archiwum okresu as a Release, bad key, deleted issue, content limits) on the private trial repository `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba`, and Aktualność narzędzia (`tool_freshness` - tags with paging, the newest Wydanie on `main`, GitHub Releases, compare and the first-parent line) by reading the public tool repository - with every exchange recorded, a verdict on outcomes expected from the domain, an offline replay of the recordings, and a check that the test fakes answer like the recorded GitHub. Use after a change to `report_box.py`, `keyed_box.py`, `tool_freshness.py`, their test fakes, or when a review asks what GitHub really answers.
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

- Writes go only to the trial repository `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba` (private, empty: no
  commit, no Release). The client transport (`github_wymiana.LiveTransport`) moves each request from the Skrzynka
  address (`report_box.REPOSITORY`) to the trial repository and raises `OutsideTrial` for any other address; the
  harness (`Admin`) refuses writes outside it. `src/` is not changed: the client gets the transport, as in the tests.
- The real Skrzynka `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia` is never asked. The public tool repository
  `maximiseartai/MAXIMISEART-Dad` is only read (GET through `GitHubProxy`).
- Keys: the client key is `gh auth token` (OAuth, `gho_`) or `--klucz-plik <file>`, Maks's fine-grained token for the
  trial repository like Dad's (Issues RW, Contents RW, Metadata R): `~/.config/maximiseart/token-repo-probne.txt`. The
  script reads the file and never prints it; evidence and recordings name only the kind of key. Cleanup and the
  harness always use the `gh` key (admin of the trial repository: only it can delete issues).
- Aktualność asks without a key, like Centrum. GitHub allows 60 such requests per hour per address and the agents on
  this Mac share it; `--aktualnosc-z-kluczem` asks with the `gh` key instead, and the verdict then says so in
  `NIESPRAWDZONE`.

## Doctor

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py doctor [--feature skrzynka|aktualnosc] [--klucz-plik <file>] [--aktualnosc-z-kluczem]
```

Read only. `DOCTOR OK | klucz=<kind> | sprzatanie=<kind> | repo=… prywatne | limit=… | pozostalosci=0 |
limit_aktualnosci=…` means: the client key sees the trial repository, the `gh` key is its admin, it is private and
has no issue, label or Release with a run marker, none of the Skrzynka labels exists yet, and both rate limits leave
room for a run. `DOCTOR FAIL | <reasons>` (exit 2) names what to fix; `na-zywo` runs the doctor first and stops on it.

## Launch and drive

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py na-zywo --feature all --zapisz-nagrania --run-dir ~/.t3/notes/verify-github-skrzynki
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py na-zywo --feature skrzynka --klucz-plik ~/.config/maximiseart/token-repo-probne.txt --zapisz-nagrania --run-dir ~/.t3/notes/verify-github-skrzynki
```

`--feature skrzynka` drives the Skrzynka Zgłoszeń, `--feature aktualnosc` Aktualność narzędzia, `all` both; each
live run ends with `--feature wiernosc-atrap` on the new recordings. A Skrzynka run takes about 8 minutes (it creates
101 issues and 101 comments for the paging cases, one write per second as GitHub asks), so start it as a background
command and wait for its notification. Keep `--run-dir` out of `/tmp`. On 2026-11-05 the third Skrzynka run within 25 minutes
got `Unreachable()` already in preparation, with no answer from GitHub in its log, and a run an hour later passed. The
cause is not confirmed (GitHub's limit on content one account creates is a guess), so leave about an hour between
Skrzynka runs, also between the two keys, and treat a preparation `Unreachable` soon after another run as that.

Each feature is a table of cases (`CASES` in `github_przypadki_skrzynki.py` and `github_przypadki_aktualnosci.py`). A
case prepares the trial repository through the harness or the client without recording (labels, closing an issue as
Maks does, deleting one, the 101 issues), calls the client once with recording, and judges the outcome. The expected
outcome comes from `GLOSSARY.md`, ADR 0007 and 0014 and the docstrings of `report_box`, `keyed_box` and
`tool_freshness`, never from a run; Aktualność takes its truth from Git (`git ls-remote` and `git log --first-parent`).
The recipes and the expected outcome of each case are in `features/<feature>.md`.

## Replay

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py odtworz [--feature skrzynka|aktualnosc|wiernosc-atrap|all]
```

Offline: every recording in `nagrania/` (`skrzynka-<kind of key>.json` for each key that ran, `aktualnosc.json`)
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
Dad's: only synthetic run text, issue numbers and comment ids of the trial repository, and tags and commits of the
public tool repository.

## Cleanup

A live run cleans up in its `finally`. By hand, after a run that was killed:

```bash
.venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_sprzatanie.py --root <run dir>/runs/github-<id>
```

It deletes only what carries this run's marker: issues whose body has `<!-- verify-github-skrzynki run=<id> -->`
(GraphQL `deleteIssue`, because a closed issue would stay in the next run's `include_closed` list), labels whose
description has `verify-github-skrzynki run=<id>`, the label GitHub created for the run's issue (only when the run's
ledger recorded it and the state before the run did not have it), and Releases with the marker and their tag. It asks
each issue of the run's ledger directly too, because GitHub's issue list lags behind (see the Skrzynka gotchas), and
retries until the list matches the state before the run. Then it removes the run directory (`.katalog-runu`) and
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
`Link` without its next page, a 404 of compare taken as no answer, any merged PR taken as the tip of `main`, and a
fake of the deleted issue that answers 410 all end the replay in `VERIFY FAIL`. A mutation reported as `NIEAKTUALNA`
no longer matches its file: rewrite its anchor against the new code so it breaks the same behaviour again.

## Helpers

- `scripts/github_skrzynki.py doctor|na-zywo|odtworz [--feature …]`: the runner.
- `scripts/github_sprzatanie.py --root <run root>`: cleanup of one run.
- `scripts/github_wymiana.py`: transports, proxy, harness, recordings and the boundary guards.
- `scripts/github_przypadki_skrzynki.py`, `scripts/github_przypadki_aktualnosci.py`: the case tables.
- `scripts/github_wiernosc.py`: the fake-fidelity check and its mapping of recorded situations to tests (`MAPPING`).

Read `features/README.md` for the conventions, then the chosen feature's file, and keep the map honest with
`/pstack:maintain-verification-skill`.
