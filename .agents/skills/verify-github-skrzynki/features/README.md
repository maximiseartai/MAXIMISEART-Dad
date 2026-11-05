# GitHub Skrzynki: verification map

This directory is the maintained source for verifying what Centrum asks GitHub and what it makes of the answers. The
user here is Centrum itself on Dad's computer: the Kolejka Skrzynki, Powiadomienia, Diagnoza and Konfiguracja call the
two clients, and Dad sees the outcome as „wysłane”, „czeka na internet”, „klucz odrzucony” or „Jest nowsza wersja”.
The feature `<feature>` of `--feature` lives in `<feature>.md` next to this file and in `FEATURES` of
`scripts/github_skrzynki.py`; its cases are the table `CASES` of its `scripts/github_przypadki_*.py`.

## Baseline preconditions

- The trial repository `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba` is private and empty: no commit, no Release,
  only GitHub's ten default labels and no issue (`doctor`: `pozostalosci=0`).
- `gh` is logged in as MAXIMISEART-AI (admin of the trial repository); the fine-grained key file, when used, holds one
  line.
- The public tool repository `maximiseartai/MAXIMISEART-Dad` has at least one Wydanie (a `v*` tag with a GitHub
  Release) on the first-parent line of `main`, and `main` has a merge commit and a commit pushed without a PR.

## Driving conventions

- Call the client the way Centrum does: `GitHubReportBox` with a transport, `KeyedBox` with a key and a clock,
  `tool_freshness` functions with an API address. Never call `urllib` or `gh` for a client case.
- Prepare through the harness (`Admin`), which does what Maks does by hand (labels, closing, deleting an issue), or
  through the client without recording; record only the client calls the case judges.
- Wait for GitHub's issue list to show what the preparation created (`SkrzynkaLive.settle`) before the client lists.
- Every body the run writes starts with the run marker, so cleanup finds it.

## Proof and skip reporting

- A case is verified only by a `PRZYPADEK … | OK` line of a run whose last line is `VERIFY OK`.
- `NIESPRAWDZONE` lines name what no run checks; a replay checks the client against the recorded answers, not today's
  GitHub, and its `NAGRANIE` lines say when and with which key the answers were recorded.
- Evidence holds synthetic text and the trial repository's numbers only; never a key.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the behaviour, then exactly these H2s in order:
`Sub-features` (the case ids of its table), `How to get to it (user POV)`, `Driving it with the GitHub harness`
(starting with `Preconditions:`), and `Gotchas`. A new feature adds its file here, its name to `FEATURES`, its table
and its replay in `github_skrzynki.py`, in the same PR. This file lists no features: `tests/test_mapy_funkcji.py`
matches the feature files with `FEATURES` in both directions.
