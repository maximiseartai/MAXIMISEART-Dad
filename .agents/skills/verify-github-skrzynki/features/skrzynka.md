# Skrzynka Zgłoszeń

Centrum writes to Maks only through the Skrzynka Zgłoszeń: an issue per Zgłoszenie, Kontrola ilości, Logi or Uwaga
taty with its label, comments and their edits, the labelled lists that the Kolejka Skrzynki and Powiadomienia read,
the Archiwum okresu as a GitHub Release, and the verdict on Dad's key (`KeyedBox`). Each answer of GitHub must become
the outcome the domain names: `Sent`, `Commented`, a list, `Refused` (the key), `Rejected` (this content) or
`Unreachable` (network, rate limit). Here the real client drives the trial repository, which is empty like the real
Skrzynka was on 2026-11-04.

## Sub-features

- `zalozenie`: `open_issue` with label `zgloszenie` → `Sent(n)`.
- `lista-bez-etykiety`: `labelled_issues` of a label the repository does not have → `()`.
- `zalozenie-bez-etykiety-w-repo`: `open_issue` with label `uwaga-taty`, which the repository does not have → `Sent`.
- `etykieta-z-githuba`: that issue is in the list with `uwaga-taty`, and GitHub created the label.
- `zalozenie-na-limicie`, `zalozenie-ponad-limit`: 65 536 characters → `Sent`, 65 537 → `Rejected`.
- `komentarz`, `komentarz-na-limicie`, `komentarz-na-limicie-bajtow`, `komentarz-ponad-limit`: a comment → `Commented` with
  `…/issues/<n>#issuecomment-<id>`; 65 536 four-byte characters and 262 144 ASCII bytes → `Commented`; 262 145 bytes
  → `Rejected`.
- `komentarz-brak-issue`, `poprawka-brak-komentarza`, `komentarze-brak-issue`: issue 999 999 or comment 1 that the
  repository does not have → `Refused`.
- `poprawka`, `poprawka-ponad-limit`: `edit_comment` → `Commented` with the same id and address; 262 145 bytes →
  `Rejected`.
- `komentarze`, `komentarze-strony`: `comments` in order with the edited text; 101 comments over two pages.
- `lista-strony`: 101 issues of `kontrola-ilosci` over two pages, exactly those.
- `lista-zamkniete`: `include_closed=False` only the open one; `True` also the issues Maks closed as `not_planned` and
  `completed`, each with its reason and a time with a zone.
- `szukanie-odcisku`: `KeyedBox.find_issue` of the fingerprint line → the open Zgłoszenie; with closed → the newest.
- `klucz-przyjety`, `zly-klucz`: `KeyedBox.judge` → `accepted`; with a key GitHub does not know every operation,
  Archiwum included, → `Refused` and `judge` → `refused`.
- `usuniete-issue`: comment, comments and edit of an issue Maks deleted → `Refused`.
- `archiwum-brak`, `archiwum-w-pustym-repo`: `archive` of a tag → `None`; `open_archive` in the repository without a
  commit → `Rejected`, and still no Archiwum.

## How to get to it (user POV)

- Dad clicks „Wyślij do Maksa”, or a Przebieg sends a Kontrola ilości or Logi by itself; the Kolejka Skrzynki opens
  the issue or comments on the one it finds by the fingerprint line.
- Powiadomienia list Dad's matters with `include_closed`; Konfiguracja and Diagnoza show the key as „gotowe” or
  „klucz odrzucony”.

## Driving it with the GitHub harness

Preconditions:

- `doctor --feature skrzynka` is `DOCTOR OK` with the key you mean to record (`gh` or `--klucz-plik`).
- The run creates the labels `zgloszenie`, `kontrola-ilosci` and `logi-uruchomienia` with its marker in the
  description, as Maks did in the Skrzynka, and leaves `uwaga-taty` out.

- **Run.** `github_skrzynki.py na-zywo --feature skrzynka [--klucz-plik <file>] --zapisz-nagrania --run-dir
  ~/.t3/notes/verify-github-skrzynki` in the background; about 8 minutes.
- **Read.** Each `PRZYPADEK skrzynka-<key>/<case>` line: the statuses GitHub gave, the client's outcome, the domain's.
  `etykieta-z-githuba`, `lista-strony` and `lista-zamkniete` carry `nadazylo_po_s` in their facts in the recording:
  how long GitHub's list took to show what the preparation created.
- **Proof.** `przebieg.txt` ending in `VERIFY OK`, `sprzatanie.txt` ending in `SPRZĄTANIE OK | … | repo_wrocilo=true`,
  and `nagrania/skrzynka-<key>.json`.

## Gotchas

- GitHub's issue list lags behind a new or closed issue by seconds: on 2026-11-05 a list right after creating 101
  issues had 98, and a list right after closing missed one closed issue. Cases that list first wait for the list
  (`settle`, up to 90 s); a client that lists right after it opened an issue (the Kolejka searching for the
  fingerprint) can miss it.
- The comment limit is in bytes (262 144), the issue limit in characters (65 536): a comment of 65 537 ASCII characters
  is accepted.
- An issue opened with a label the repository does not have gets the label: GitHub creates it (with an OAuth key and
  with the fine-grained key, both recorded). Cleanup removes it only because the run's ledger saw it appear.
- `open_archive` in a repository without a commit: 422 `Repository is empty.` with both keys on 2026-11-05, while
  the constant `_EMPTY_REPOSITORY` in `report_box.py` says 409 `Git Repository is empty.` (#860, the real Skrzynka
  2026-11-04); the docstring of `open_archive` names both answers, and the fake `GitHubOnTransport` plays both
  (`EMPTY_REPOSITORY_ANSWERS` in `tests/test_skrzynka_zgloszen_github.py`). Both give `Rejected`. Why the real
  Skrzynka answered 409 is not settled.
- The Archiwum's files (upload, a list of files over a page, a file of the same name, removal, the download link) need
  a Release, and a Release needs a commit, so the feature `archiwum` drives them in the second trial repository, which
  has one.
- Editing another account's comment and GitHub's rate limits are not driven (`NIESPRAWDZONE`).
