# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in [maximiseartai/MAXIMISEART-Dad](https://github.com/maximiseartai/MAXIMISEART-Dad); use `gh` inside this clone.
Zgłoszenie, Kontrola ilości or Logi Uruchomienia from Dad's computer: before you read one or fix what it shows, read [`skrzynka-zgloszen.md`](skrzynka-zgloszen.md), because they live in a private repository and carry Dad's data.

## Conventions

- This repository is public: a public issue may name a worker of Dad's by first name alone, never by surname, login or address, and repository files say „pracownik taty” ([ADR 0007](../adr/0007-zgloszenia-do-maksa-w-prywatnym-repo.md)).
- Read an issue with its comments with `gh issue view <number> --json title,body,comments --jq '.title, .body, (.comments[] | "--- \(.author.login) \(.createdAt)\n\(.body)")'`; `--comments` alone prints only the comments when its output is piped, as in an agent's shell.
- PRs as a request surface: no.

## Decisions for Maks

An open decision that only Maks can make lives as an issue labelled `decyzja-maksa` ([ADR 0034](../adr/0034-kod-jest-pamiecia.md)).

- Create one without asking Maks, once ADRs, merged PRs and issue comments show the decision is still open.
  This standing consent covers only issues labelled `decyzja-maksa`; tickets of a spec still wait for Maks's yes.
- A decision issue is not a ticket: no parent spec, no `ready-for-agent`, no triage label.
  Its body is exactly this template, every line a fact or a link:

  ```markdown
  ## Pytanie
  <one question Maks answers in one sentence>

  ## Opcje
  - **A. <name>:** <what happens after this answer>

  ## Rekomendacja
  <option>: <one sentence why>, or `brak`: <what is missing to recommend>

  ## Co czeka na decyzję
  - <issue, PR, ADR or work that moves after the answer>
  ```

- Every term, trial and number the question rests on is defined in the body or linked to an ADR, PR or issue; run notes and agent memory are never its source ([ADR 0034](../adr/0034-kod-jest-pamiecia.md), „Notatki biegów”).
- The body holds public facts only: Dad's data, names, logins, addresses, firm names, home paths and Zgłoszenie content stay out ([ADR 0007](../adr/0007-zgloszenia-do-maksa-w-prywatnym-repo.md)).
  A decision that rests on such a fact names its subject and links the public issue or file that holds its context.
- Close it with a link to where the answer took effect (ADR, PR or ticket).
- A read-out due on a date (a card check, a measurement after N days) stays a scheduled T3 task.

## Specs, sub-issues, and dependencies

- A published spec is the parent issue, and each ticket derived from it is a native GitHub sub-issue of that parent, not a standalone issue with only a textual parent link.
  A `/wayfinder` map is such a parent: its tickets are its sub-issues.
- Publish tickets in dependency order, blockers first, and add each blocking edge to the blocked ticket as a native dependency: `gh issue create --parent <spec> ...`, then `gh issue edit <blocked> --add-blocked-by <blocker>`.
  A `gh` without these flags takes `gh api repos/{owner}/{repo}/issues/<spec>/sub_issues --method POST --field sub_issue_id=<id>` and `gh api repos/{owner}/{repo}/issues/<blocked>/dependencies/blocked_by --method POST --field issue_id=<id>`, where `<id>` is the numeric issue ID from `gh api repos/{owner}/{repo}/issues/<number> --jq .id`, a 64-bit value passed without narrowing it to a 32-bit integer.
- Keep a human-readable `Blocked by` section in each ticket body as documentation only: the native sub-issue and dependency relationships are the source of truth.
- Publishing is done once `gh issue view <spec> --json subIssues` lists every ticket and `gh issue view <ticket> --json blockedBy` lists every blocker of each ticket.
