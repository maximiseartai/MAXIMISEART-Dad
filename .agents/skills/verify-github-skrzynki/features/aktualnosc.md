# Aktualność narzędzia

Diagnoza and Konfiguracja tell Dad whether a newer Wydanie exists („Jest nowsza wersja”, „Aktualna”, „Nie
sprawdzono”), and Powiadomienia show the published Wydania with their notes. Centrum asks the public tool repository
with the Token do Zgłoszeń when Dad has the key file, and without a key otherwise: the tags (paged by `Link`), the tip of `main`, compare and the PRs of a commit to decide whether a
Wydanie lies on the first-parent line of `main` (ADR 0014), and the list of GitHub Releases. Here the real
`tool_freshness` asks the real repository through a recording proxy, and Git says what the answer must be.

## Sub-features

- `tagi-strony`: `tag_commits` with a small page size → every tag with its commit as in `git ls-remote`, from at
  least two pages.
- `najnowsze-wydanie`: `releases_from` → the commit and tag of the highest `vX.Y.Z` tag on the first-parent line of
  `main` by `git log --first-parent`.
- `opublikowane`: `published_from` → a non-empty list of Wydanie tags, newest publication first, with the newest
  Wydanie, at most `PUBLISHED_PAGE`.
- `linia-scalenie-pr`: a merge commit of a PR on the line → `True` (one compare and one PR question).
- `linia-bez-pr`: a commit pushed to `main` without a PR → `True` by binary search.
- `poza-linia`: the second parent of a merge (a branch commit) → `False`.
- `nie-przodek`: the tip compared with an older commit of the line → `None`.
- `przed-poczatkiem`: compare with `tip~k` beyond the first commit → 404, `NotFound`.

## How to get to it (user POV)

- Dad opens Konfiguracja (card `Narzędzie`) or runs the Diagnoza; Centrum asks GitHub and shows the freshness.

## Driving it with the GitHub harness

Preconditions:

- `doctor --feature aktualnosc` is `DOCTOR OK`: at least 40 requests left without a key (or `--aktualnosc-z-kluczem`).
- `git ls-remote` and `git fetch` of `main` reach GitHub (the oracle).

- **Run.** `github_skrzynki.py na-zywo --feature aktualnosc --zapisz-nagrania --run-dir
  ~/.t3/notes/verify-github-skrzynki`; under a minute, about 25 requests.
- **Read.** Each `PRZYPADEK aktualnosc/<case>` line; the facts in the recording hold the oracle's answer (tags, tip,
  chosen commits).
- **Proof.** `przebieg.txt` ending in `VERIFY OK` and `nagrania/aktualnosc.json`.

## Gotchas

- The binary search on the real `main` asks for `tip~k` past the start of the first-parent line, because `ahead_by`
  counts merged branches too, and GitHub answers 404 there (`linia-bez-pr` on 2026-11-05: `tip~830` → 404 with a line
  of 471). The code takes 404 as "older"; the fake „daleko” never gives 404, the fake of the first commit does.
- The newest tag pages are `/repositories/<id>/tags?…` in `Link`, not `/repos/<owner>/<name>/…`; the proxy lets
  both through.
- The 60 requests per hour without a key are shared by every agent on this Mac and were used up on 2026-11-05 at
  night; then run with `--aktualnosc-z-kluczem` and the verdict says the run asked with a key.
- The cases pick their commits from today's `main`, so a replay checks the recorded `main`, not today's.
