# Archiwum Logów okresu

The Kolejka wysyłki puts the full Logi Uruchomień of a period into the Archiwum Logów okresu: a GitHub Release with
the tag `logi-<okres>` in the Skrzynka repository, one `.gz` file per Uruchomienie, labelled with the version of the
wysyłka, and a comment in the period's Logi issue that links to the file (`archive_url`) before it arrives
(`outbox._deliver_archive`, ADR 0015 with the #844 note). A Release needs a commit, so this feature drives the real
client in the second trial repository `MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba-archiwum`, which has one
commit (README on `main`); the empty trial repository keeps the case of the Skrzynka without a commit
(`skrzynka`: `archiwum-w-pustym-repo`).

## Sub-features

- `archiwum-brak`: `archive` of the run's tag in the repository with a commit → `None`.
- `zalozenie`: `open_archive` → `Archive(id, ())`.
- `zalozenie-tego-samego-tagu`: once GitHub's Release list shows it, `open_archive` of the same tag → `Rejected`, and
  `archive` of the tag → that one Archiwum without files.
- `znalezienie-po-tagu`: with two Archiwa, `archive` of each tag → its own Archiwum.
- `wysylka-pliku`: `upload` of the gzip packed Logi file with its label → `Asset` with the name, the label and
  `uploaded`; the Archiwum lists that one file. The file is the Logi file of `ArchiveFile.packed` in `portable_gzip`,
  the same bytes on every machine, because the recording holds the hash of the body.
- `plik-tej-samej-nazwy`: `upload` of a newer version under the same name → `Rejected`, and the first version stays.
- `pliki-strony`: 101 files in one Archiwum → all of them from two pages of the file list.
- `podmiana-pliku`: `remove` of the older file → `Removed` and only the other file is left; the newer version under the
  same name then arrives next to it.
- `adres-pobrania`: `ArchiveFile.link` (`archive_url`) is the `browser_download_url` GitHub gives the file, and the file
  downloaded from GitHub is byte for byte the one sent and unpacks to the Logi file.
- `zly-klucz`: `archive`, `open_archive`, `upload` and `remove` with a key GitHub does not know → `Refused`, and both
  files stay.

## How to get to it (user POV)

- Dad runs a Przebieg or a Diagnoza; the Kolejka wysyłki sends its Logi, and Maks opens the link in the comment of the
  period's Logi issue.

## Driving it with the GitHub harness

Preconditions:

- `doctor --feature archiwum` is `DOCTOR OK` with the key you mean to record: the archive trial repository is private,
  `gh` is its admin, it has a commit and no Release, tag or leftover of a run.

- **Run.** `github_skrzynki.py na-zywo --feature archiwum [--klucz-plik <file>] --zapisz-nagrania --run-dir
  ~/.t3/notes/verify-github-skrzynki` in the background, waiting for its end in the same turn; about 115 writes (101 for `pliki-strony`), one per second.
- **Read.** Each `PRZYPADEK archiwum-<key>/<case>` line. `zalozenie-tego-samego-tagu` and `znalezienie-po-tagu` carry
  `nadazylo_po_s` in their facts: how long GitHub's Release list took to show the new Archiwum. `zalozenie-tego-samego-tagu`
  carries `najnowsze_id`, the Release GitHub answers for `releases/latest`, and `adres-pobrania` carries
  `strona_z_kluczem_status`, what `github.com/…/releases/download/…` of the private repository answers to a request
  with a key and no browser session.
- **Proof.** `przebieg.txt` ending in `VERIFY OK`, `sprzatanie.txt` ending in `SPRZĄTANIE OK | … | repo_wrocilo=true`
  (both trial repositories: labels, issues, Releases and tags as before the run), and `nagrania/archiwum-<key>.json`.

## Gotchas

- GitHub's Release list lags behind a new Release: on 2026-11-05 `archive` right after `open_archive` (201) got an
  empty list (first live run, `archiwum-1-fg.log`), and the second Archiwum showed after 2.8 s. The cases wait for the
  list (`settle_releases`, up to 90 s) before they call the client, so a client that lists right after it opened an
  Archiwum, as the Kolejka does for a second Logi file of a new period in the same pass, is not driven
  (`NIESPRAWDZONE | lista-zaraz-po-zalozeniu`): the 422 on `open_archive` of the same tag (`Rejected`) is recorded only
  after the list showed the Archiwum (`zalozenie-tego-samego-tagu`, `nadazylo_po_s` 2.8).
- `make_latest: "false"` does not keep the Archiwum out of `releases/latest`: with the Archiwum as the only Release
  GitHub answered it there on 2026-11-05 (`najnowsze_id`). The cases record it and do not judge it: Centrum and the
  Wydanie tool read Wydania only from the public tool repository (GLOSSARY, Archiwum Logów okresu).
- `github.com/<repo>/releases/download/<tag>/<name>` of the private repository answers 404 to a request with a key
  and no browser session (`strona_z_kluczem_status`, 2026-11-05), so the case compares `archive_url` with the file's
  `browser_download_url` and downloads through the API.
- GitHub's 422 bodies: a tag that has a Release gives `already_exists` on `tag_name` (resource `Release`), a file
  name in the Release `already_exists` on `name` (resource `ReleaseAsset`); the fake `GitHubOnTransport` gives both.
- The harness downloads the file as Maks's account does without a browser: the API answer for the asset with `Accept:
  application/octet-stream` is a redirect to a signed address under `githubusercontent.com`, fetched without the key.
  It never follows a redirect with the key.
- Deleting a Release deletes its files, but its tag stays: cleanup deletes the run's tags (`logi-verify-<run>…`)
  separately, and leaves a marked Release whose file lacks the run id in its name (`repo_wrocilo=false`).
- A key without the Contents permission is not driven (`NIESPRAWDZONE`): Maks has no key for the trial repositories
  without it, so only the unknown key (401) is.
