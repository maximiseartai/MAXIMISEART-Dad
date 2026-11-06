---
name: verify-kolejka-skrzynki
description: Exhaustively check that the Kolejka Skrzynki Zgłoszeń (`Outbox` in `src/rozliczenia/centrum/outbox.py`) delivers every part of every wysyłka (Zgłoszenie, Kontrola ilości, Logi Uruchomienia, Uwaga taty) and the file of the Logi in the Archiwum Logów okresu exactly once, lets a newer version of a wysyłka (Logi Uruchomienia after a Diagnoza or after the progress of a Wycena w efenix; the version is its rank, then its moment, so a stand-in version from the next start of Centrum is older than the Logi with the result although it is posted later) change its comments and replace the file of an older one still in the queue, while an older one that arrives after it changes nothing, keeps one issue per problem and per period, and empties the queue, under every order of network failures, answers lost after the Skrzynka acted, file errors, a killed Centrum and GitHub's lists that show a new issue or Archiwum seconds late. Use when a change touches `_deliver*` (also `_deliver_archive`, `_asset_label`, `_asset_version`), `_settle`, `_seen`, `_put_all`, `_put`, `_mark`, `_marks`, `_version`, `_version_of`, `Rank`, `Version`, `Outbox.post`, `_comment_all`, `_waiting`, `Outbox._drain`, `_send_all`, `_read`, `_superseded`, `_archive_waits`, `_remove`, `resume`, the folder lock (`_folder_lock`) or the delivery marker in `outbox.py`, the box calls in `keyed_box.py` (also `archive`, `open_archive`, `upload`, `remove`, and its list after its own writes in `_ready`, `_held`, `_settled`, `_notes`, `_noted`, `_Notes` and `_parsed`) or `newest_with_line` in `report_box.py`, `replace_atomically` in `atomic_file.py`, adds a new `Target`, or when `explore_outbox.py` or `sprawdz_model_kolejki.py` fails. A TLA+ model of the same queue (TLC) adds the interleavings the checker leaves out (a wysyłka posted during a pass, the `RETRY_S` wake, two queues of one folder in `_claimed` and in the folder lock, a second Centrum whose port the old one already released, a switch-off at the temporary file and at the rename, and an older version of a wysyłka sent after a newer one).
pilnuje:
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/keyed_box.py
  - src/rozliczenia/centrum/report_box.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/server.py
  - .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_kolejke.py
ci-czesci: 3
---

# Verify Kolejka Skrzynki Zgłoszeń

## What CI runs and what stays local

CI runs `sprawdz_kolejke.py` (the `ci:` key) in Mutation checks whenever a change touches this skill:
it runs the checker of the real code (`explore_outbox.py`) and the TLA+ model (`sprawdz_model_kolejki.py`, TLC,
as the `ci:` of `verify-aktualizacja-narzedzia` does), each to its end. Its units (`UNITS` in
`sprawdz_kolejke.py`) are the scopes `archiwum` and `archiwum-diagnoza` together, the scopes `watek-okresu` and
`watek-okresu-lista`, the scopes `diagnoza`, `diagnoza-odczyt`, `archiwum-puste-repo` and `archiwum-lista` together, the
other six scopes with `postep`, and the model; CI runs them in up to `ci-czesci` parts (`MUTACJE_CZESC=k/n`, consecutive
units per part). On Maks's Mac (2026-11-05, after #911) the two scopes of the Archiwum take about 67 s together, the
scopes of the issue okresu about 26 s, the third unit about 39 s, the other scopes with `postep` about 35 s and the model
about 65 s, so with three parts the first runs the scopes of the Archiwum, the second the next two units and the third
the rest and the model. On Windows CI the same units took about 7 times as long before #911 (1163 s, 304 s, 505 s and
355 s in run 41993938633 against 145 s, 40 s, 69 s and 57 s on the Mac). A
pull request runs the parts of one n, and the night on `main` runs every part of every n up to `ci-czesci`. The model unit
fails with `MODEL KOLEJKI: ROZJAZD MODELU Z KODEM` when covered code changed since the Sync commit,
but it cannot tell whether a change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_outbox_mutations.py` and
`check_model_kolejki_mutations.py` run in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`)
after a change of this skill's folder. `check_model_kolejki_mutations.py` also runs on a pull request that changes a
file in `model/`, the script itself or `sprawdz_model_kolejki.py` (ADR 0021), so a model change that leaves a mutation
with `BŁĄD MODELU` turns the pull request red. Run them locally only to reproduce a red Mutation checks step or the
night's issue, or one `--scope` or `--config` while you work on it. What stays with you on every change to the covered code is „Does the
change touch it?” and „Bring the model in line”: read each commit since the sync commit against both
tables, change the model, break the new path in it, and move the sync commit. A change that adds a new
way to the Skrzynka (a new `Target`, a second writer of queue files, a box call outside `KeyedBox`)
passes both checks without being checked. Sorting a red run as „When the check fails” and „Real bug
or modeling error?” say also stays with you.

## The promise

- **DOKLADNIE_RAZ**: once the Skrzynka answers again, every part of the newest
  version of every wysyłka in the queue is in the Skrzynka exactly once, in an
  issue of its target, and no text of an older version of it is left there.
  ADR 0015 (note of #840) and the docstring of `outbox.py`: „Wysyłka jest
  dokładnie raz”. Harm: a missing part means Maks never sees the rest of Logi
  Uruchomienia, a Kontrola ilości or a Zgłoszenie, and nobody knows it is
  missing, because the queue file is gone; a part twice fills the issue okresu
  with copies; an older version left means Maks reads Logi without their
  Diagnoza. A wysyłka with a file for the Archiwum Logów okresu (`ArchiveFile`,
  #844) has exactly one whole file of its name in the Archiwum (GitHub Release)
  of its tag, with the text of its newest version, and the queue never removed a
  whole file of its version or a newer one to send it again. Harm: the link in
  the comment leads nowhere or to Logi without their Diagnoza. While the
  Archiwum refuses until Maks changes something (a repository without a commit,
  where GitHub answers 409 to every new Release), the file waits in the queue
  with the marker of its parts, and every part of every wysyłka still arrives: a
  refusal of the Archiwum stops only the file, never the wysyłki after it (#860).
  Harm: a Zgłoszenie or an Uwaga taty behind the Logi waits until Maks adds a
  commit, and Dad's card says it waits for the internet.
  A comment of a part carries the note that the file waits (`_waiting_note`)
  only after the Archiwum refused a step (a refused step, or a repository
  without a commit). Harm: the note stays in the issue for good and says the
  Token lacks a permission it has.
- **NAJNOWSZA_WERSJA**: once a newer version of a wysyłka is in the queue, the
  Skrzynka gets no text of an older one: the pass that reads the newer file marks
  the file of the older one delivered and removes it unsent (`_superseded`, #846;
  the docstring of `outbox.py`: „bez sieci w kolejce zostaje tylko najnowszy
  postęp”). Harm: a Wycena w efenix without the network queues a progress every
  5 minutes, and once the network is back Maks's comment would change once for
  each of them before the newest. Judged only in schedules in which no read of a
  queue file failed: a pass that cannot read the newer file sends the older one,
  and the newer then changes its comment, as DOKLADNIE_RAZ asks.
- **JEDNO_ISSUE**: one problem has one open Zgłoszenie, one period has one issue
  okresu, and one Uwaga taty opens one issue, also while GitHub's list of issues
  does not show an issue opened a few seconds before (#879). Harm: Maks gets the
  same problem in several issues, and the Powiadomienie follows only one of them.
- **KOLEJKA_PUSTA**: once failures stop, no file without its delivery marker
  is left in the queue folder (`config/zgloszenia/kolejka/`): the `RETRY_S`
  wake that `_drain` arms runs the queue again until it is sent. Harm: a
  wysyłka waits until Centrum restarts or something new is sent, after the
  network came back. A delivered file whose removal failed may wait for the
  next start: it has its marker and is never sent again.
- **BEZ_WYJATKU**: no pass of the queue ends in an exception that `_drain` logs
  as `nieoczekiwany-wyjatek` „wysyłka do Skrzynki Zgłoszeń”.

A Zgłoszenie (`ReportIssue`) always has one part, so DOKLADNIE_RAZ holds
when a retry takes over, without comments, the Zgłoszenie whose body has the
mark of that part (`_settle`: the attempt before it opened the issue and was cut
off before the delivery marker). Any other open Zgłoszenie with its odcisk line
gets the part as one comment headed „Zgłoszenie wróciło” (`returned_report`,
#820), with the same mark. Two
guards keep it to one part (#724): `Post`
raises `ValueError` for a `ReportIssue` with more
(`test_zgloszenie_w_wiecej_niz_jednej_czesci_to_blad_programu`), and
`reports.py` fits the body into `PART_LIMIT` (`outbox.py`), first by dropping
the first frames of the call trace, then the oldest entries of the Centrum log
(the `bardzo_dlugim` tests in `tests/test_centrum_uchwyt_zgloszenia.py`). The
checker's scope `zgloszenie` and the model's `ASSUME` take one part as given.

## How the queue knows what is already there

Every text the queue writes to the Skrzynka (an issue body, a comment) ends with
a hidden line, the mark of its wysyłka (`_mark`, an HTML comment GitHub does not
show): the label and `run_id` of the wysyłka (its identifier), the number of the
part (0: the header) and the version (`Version`): the rank its sender picked
(`Post.rank`, `Rank`, #910), then the moment and number from the name of its
queue file (`_version`), which sort as the queue does. The mark of rank `OWN`
has the moment and number alone, as before #910, and a lower rank writes its
number before them (`1:20261105T…Z-0001`). Before it sends to an
issue it found, the queue reads the issue's comments (`_settle`): an issue with a
mark of this wysyłka in a newer version, in its body or in a comment, gets
nothing from this version; otherwise a part whose mark is in the issue's body,
or in a comment in this version, is not sent again; a comment of the part in an
older version gets this version's text (`_put`, `edit_comment`); every other part
is a new comment, in order; and a comment of a part this version no longer has
gets `_RETIRED`, unless it has it from this version already. A `NewIssue` finds
its issue by the mark in the body (`_deliver_new_issue`).

A pass reads every queue file at its start (`_read`). A file for which the same
pass read a readable file of a newer version of the same wysyłka (the same
target and `run_id`, `_superseded`), before or after it in the order of the
queue, gets the delivery marker without being sent and is removed
(`_mark_delivered`), so one whose removal fails does not wait without a marker. Without the network only the newest progress of a Wycena w
efenix waits (`pricing_progress.py`, #846), and the Logi with their last
Diagnoza. The progress is a version of the Logi of its Uruchomienie of the
lowest rank (`DRAFT`), without a file for the Archiwum; the Logi at the end of
the Wycena (`OWN`), or the stand-in version of the next start (`STAND_IN`: the
Logi from the file, of an Urwane Uruchomienie or the result without Logi), turn
its comment into the summary, and the stand-in version never replaces the Logi
with the result, though it is posted later.

A wysyłka to an issue okresu may carry a file for the Archiwum Logów okresu
(`Post.archive`, only with one part: the Logi Uruchomienia). It goes right before
the parts (`_deliver_archive`), in a found issue only when the issue has no newer
version of the wysyłka (`_seen`, `_newer`). The queue finds the Archiwum by its tag
(`archive`) or opens it (`open_archive`); the label of each file carries the version
of its wysyłka (`_asset_label`, `_asset_version`), so a file of this version or a
newer one stays, and a file of an older version, or one whose upload broke off
(`uploaded` false), is removed (`remove`) right before this version is uploaded
(`upload`). GitHub keeps one file of one name, so an upload over a file that is
there is `Rejected`. A refusal of any step of the Archiwum (`Refused`: a key
without the permission to write the repository's contents, or `Rejected`, also
GitHub's 409 to a new Release in a repository without a commit, which
`GitHubReportBox.open_archive` reads as `Rejected`) is `ArchiveWaits`: the parts go with `_waiting_note`, the queue file gets the marker
of its parts only (`delivered_parts`, `archived` false), and the pass asks the
Archiwum no more (`_archive_refused`) and arms the `RETRY_S` wake. Such a file
later goes only through `_deliver_archive`, without reading the issue. So a Diagnoza, which
queues the Logi Uruchomienia again with the same identifier, changes the comment
of its Uruchomienie, and an older queue file that arrives after a newer one
(read once with an `OSError`) changes and adds nothing, even when it has more
parts. The moment orders only versions of one rank, which come from one Centrum
process (only the last Uruchomienie of a process has a Diagnoza, `run_logs.py`,
and only the running Wycena a progress), where `Outbox.post` gives every name a
moment after the one before, also when the computer's clock went back, or are
stand-in versions of one journal from two starts, which have the same kind. The queue never edits an issue body. The delivery marker and `_undeleted` now only spare a retry its requests
and keep a delivered Kontrola ilości from a new issue okresu after Maks closed
the old one (`closed="new_issue"`), which neither check models.

GitHub's lists lag behind a write by seconds: the list of issues behind a new
issue (`verify-github-skrzynki`, 3.0–6.8 s), the list of Releases behind a new
Archiwum (#887, 2.8 s). The queue looks on a list for what an earlier attempt
may have written, so `KeyedBox` reads its lists after the writes (#879). Every
write whose effect only a list shows (opening an issue of a label, opening the
Archiwum of a tag, uploading or removing a file of the Archiwum) is first noted
with its moment and an identifier in the file `skrzynka-zakladanie.txt` next to
the key (`OPENING_FILE`, `_ready`, `_noted`); the answer with its effect
replaces it there by the effect with the moment of the answer, and a refusal
(`Refused`, `Rejected`) restores the file, because nothing changed (`_settled`).
The list of issues of a label and the Archiwum of a tag with its files show the
effects of the last `LIST_LAG_S` (30 s; `_Notes.opened`, `archives`, `uploads`,
`removals`), also those another `KeyedBox` wrote, so a new Centrum after a
switch-off or a restart knows what the old one wrote and got an answer for. A
list without closed issues leaves out an issue Maks closed: an effect it lacks
is added only when the list with closed issues does not have it closed. A write
of a kind is held, `Unreachable` without a request, while the file has a write
of that kind without an answer (a lost answer, or another Centrum that still
finishes its pass) and the last list of that kind in this thread was asked for
less than `LIST_LAG_S` after it (`_held`, `_listed_at`). The time of the list
counts, not of the write: between the list and the write the queue may still
send the file of the Archiwum; and only the list of the queue's own thread
counts, not a later list of the preview or of Powiadomienia. A held write stops
the pass, and the `RETRY_S` wake (60 s) comes after the hold. The moment is from
Centrum's clock (`time.monotonic`, shared by the processes of one computer until
it restarts). Only the queue writes to the Skrzynka, inside a pass with the
folder lock, so one process at a time reads and writes the file; without the
lock a second process could list before the first one's write and open after
its answer, which the hold does not see (configuration `dwa-procesy`). The file
is replaced atomically (`NotesFile.replace`, `replace_atomically` from `create_app`) and keeps only the effects of the
last `LIST_LAG_S` and the writes without an answer of the last `PENDING_KEPT_S`
(an hour).
A file that cannot be read (`OSError`, an antivirus holding it) cannot rule
out a write `KeyedBox` does not know, so a write and a list follow one rule
(#909): a write is held while the file could not be read at it or at the last
list of its kind in this thread (`_listed_at` is `None`), and the next list of
that kind that reads the file lifts the hold; the list itself shows only what
GitHub shows. Content that is not UTF-8 is content in another form (no
writes), which the next write replaces. A file that can never be read or
written holds every write: the queue waits as without a network and retries at
every wake, and the Centrum log gets `skrzynka-zapisy-niedostepne typ=<error>`
once per Centrum run (`NotesFile.unavailable`, `CentrumLog.box_notes_unavailable`).

## Does the change touch it?

The check runs the real `Outbox` and `KeyedBox`. Each row is one indivisible
step of this code that the checker can fail, lose or kill:

| Step in the checker | Code |
| --- | --- |
| a box read | `keyed_box.py` `KeyedBox.labelled_issues` (with `newest_with_line` and the body of the issue found, and the issues `KeyedBox` adds after its own writes), called by `_deliver_report`, `_deliver_to_period` and `_deliver_new_issue` in `outbox.py` and, through `KeyedBox.known_issue`, by `_deliver_to_known`, and `KeyedBox.comments`, called by `_seen` (`_settle`, `_deliver_to_period`) |
| a box write | `KeyedBox.open_issue`, `comment` and `edit_comment`, called by `_deliver_new_issue`, `_deliver_report`, `_deliver_to_period`, `_comment_all` and `_put_all` (`_put`, `_RETIRED`; also the one comment of a Zgłoszenie that returned) |
| a read of the Archiwum | `KeyedBox.archive` in `_deliver_archive` (with the Archiwum and files `KeyedBox` adds after its own writes): it answers, the network fails, the key lacks the permission (GitHub's 403, as the real `GitHubReportBox` reads it), or the process dies |
| a write to the Archiwum | `KeyedBox.open_archive`, `remove` and `upload` in `_deliver_archive`: as a box write, or refused (GitHub's 403 through the real `GitHubReportBox`); an upload may also break off in the middle of the file, which leaves it not whole (`uploaded` false), counted as a network failure; in a repository without a commit (`archiwum-puste-repo`) every `open_archive` GitHub answers gets 409, which `GitHubReportBox.open_archive` reads |
| a read of a queue file | `Outbox._send_all`: `_read` (`_queued`) of every file at the start of the pass, whose `OSError` (`read_text`) sets `_read_failed`, skips the file to the `RETRY_S` wake and keeps it from replacing an older version (`_superseded`); it fails only in a scope with a read bound (`diagnoza-odczyt`, `archiwum-diagnoza`) |
| a later wysyłka | `Outbox.post` of a scope's later wysyłka (a Diagnoza, the next progress of a Wycena w efenix, its Logi at the end) between two passes, at a moment the schedule picks; the code queues it on its own (`RunLogs.diagnosed`, `pricing_progress.ProgressComment`), so the checker writes it with the real `replace_atomically` |
| the delivery marker | `Outbox._send_all`: `replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))` in `suppress(OSError)` (`_mark_delivered`), also on the file of a superseded version |
| the removal of a queue file | `Outbox._remove` (`path.unlink`, `_undeleted`) |
| a pass of the queue | `Outbox._drain` (`_claimed`, `_folder_lock`, `_send_all`, `_released`), run only when the real `Outbox.send_in_background` starts the queue thread (called by `Outbox.post`, `Outbox.resume` and `Outbox._woken`); the checker replaces only `threading.Thread` in `outbox.py`, which hands it the target, and runs one Centrum at a time, so the pass always gets the folder lock |
| the marker of the parts | `Outbox._send_all` after `Delivered` with `archive_waits`: `_archive_waits`, then `replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts), archived=False))` in `suppress(OSError)` |
| the `RETRY_S` wake | `Outbox._drain`: `self._clock.after(RETRY_S, self._woken)` when `_stopped_on`, `_read_failed`, `_archive_refused` or `_locked_out` is set and no wake is armed; the checker calls an armed wake when nothing else asked for a pass, moves its clock by `RETRY_S` first (the only time that passes), and a restart drops it with its process |
| a held write | `KeyedBox._ready` (`_notes`, `_held`, `_noted`) before `open_issue`, `open_archive`, `upload` and `remove`: `Unreachable` without a request; the checker never fails the read or write of `OPENING_FILE`, which it keeps in memory for the schedule (`_NotesInMemory`, #911) and which survives a restart: the model fails both (`bledyPliku`: the read in `Szukaj` and `CzytajArchiwum`, `OdczytyZapisow`, the note and the answer in `Zaloz`), and the unit tests in `test_klucz_zgloszen.py` and `test_kolejka_skrzynki_zgloszen.py` fail the read at a list and for good (#909) |
| a held decision `Gone` | `KeyedBox.known_issue` in `_deliver_to_known`: a list without the known number is `Gone` only when a write with its label would not be held (`_held`), else `Unreachable` without a decision (#915). Every list in the checker reads `OPENING_FILE`, whose effects show the issue, so it never reaches the hold: the model does (`znane` with `OpoznienieListy`: a failed read at the list, or a write without an answer because the answer's write failed), and `test_komentarz_do_swiezego_issue_ktorego_lista_nie_pokazuje_czeka_zamiast_porzucenia` in `test_kolejka_skrzynki_zgloszen.py` runs both on the real code |
| a restart of Centrum | a new `Outbox` and `KeyedBox` on the same folder, then `Outbox.resume` |

Covered files: `src/rozliczenia/centrum/outbox.py`,
`src/rozliczenia/centrum/keyed_box.py`, in
`src/rozliczenia/centrum/report_box.py` `newest_with_line`, by which
the queue finds the issue of a Zgłoszenie or a period, and the reading of
GitHub's answers to the steps of the Archiwum in `GitHubReportBox`, which the
checker takes from the real adapter (`_github` in `explore_outbox.py`), and
`src/rozliczenia/centrum/atomic_file.py` `replace_atomically`, which writes
every queue file and its marker (the model only). The model's `Start`, `Zamknij`
and `KoniecProcesu`, which let an old and a new Centrum process share the queue
folder (configuration `dwa-procesy`), also cover three definitions in files
that Centrum changes often: `lifespan` in `app.py`, `listen_locally` and
`_listen_when_released` in `launcher.py`, and `_GRACEFUL_SHUTDOWN_S`, `serve`
and `_Server` in `server.py`. `model/definicje.json` lists the four covered files as whole files and these three
by their definitions: only a change to these definitions, not to the rest of their files, is drift.

**Sync commit: `6908b5c3a`** (2026-11-05, #919 merged with `main` after #910, #924
and #949). The checker and the model share it: at this commit both were
confirmed to describe the code above. The model holds the order of versions of
#910 (`Nr`, `czytane`, `NowszyDalej` in `Plik`) and the branches `Unreachable`
and `Gone` of #915 in `Szukaj`; `znane` sets `StarszaPozniej` and `Postep`
FALSE and `OpoznienieListy` TRUE. The checker is that of #949: `OPENING_FILE`
lives in memory (`_NotesInMemory`, handed to `KeyedBox` through `NotesFile`),
and `znane-issue` asks `known_issue`, which reads that file at every list. At it
`sprawdz_model_kolejki.py` gave `MODEL KOLEJKI OK` on all 15 configurations,
`check_model_kolejki_mutations.py` 51 of 51 `WYKRYTA`, `explore_outbox.py`
`KOLEJKA OK` on all 15 scopes and `check_outbox_mutations.py` `MUTACJE OK` in
all 3 parts. What earlier syncs confirmed is in the history of this file and in
the messages of their commits. To see whether the checker and the model need
another look:

```bash
git log --oneline <Sync commit>..HEAD -- src/rozliczenia/centrum/outbox.py src/rozliczenia/centrum/keyed_box.py src/rozliczenia/centrum/report_box.py src/rozliczenia/centrum/atomic_file.py
```

A change to the three definitions above shows as a `UWAGA:` line of
`sprawdz_model_kolejki.py` (in CI as the drift verdict).
Read each listed commit against this table and the model's table below. A change matters when it adds,
removes or reorders a box call, changes what a retry does with an issue it
finds, changes how a text carries its mark or how `_settle` reads one, changes how a file in the Archiwum carries
its version or when it is removed and uploaded, changes when the marker is written or the file removed, changes which
failure stops a pass (`_waiting`), or adds a `Target` or a field of `Post` that goes to the Skrzynka. A new `Target` also needs
a scope in `SCOPES` and a branch in `_check` in `explore_outbox.py`. Changes to
the text of a wysyłka, the log lines, the `Listener`, `delivered`, `wait_delivered`
and the addresses file do not matter here. Move the sync commit forward only
after the checker and the model match the code at the new commit and both
checks and their mutations pass there.

## Run

```bash
.venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py
```

On Windows use `py -3` instead of `.venv/bin/python`. In a worktree, create its
`.venv` first (`python3 tools/setup_worktree.py`). It needs nothing beyond the
repo's Python and takes about 30 to 80 s, depending on the machine. `--scope NAME` runs one scope,
`--strict` counts known findings and accepted risks as violations too, and `--stop-at-new` ends at the first schedule
with a new violation, so its counterexample is not the shortest one (the mutation commands use it).

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `KOLEJKA OK` | 0 | Every rule holds in every schedule. |
| `KOLEJKA OK, ZNANE USTALENIA: n, ZAAKCEPTOWANE RYZYKA: m` | 0 | Only the known findings and accepted risks below, each printed with its shortest counterexample. A count of zero is left out. |
| `KOLEJKA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below. The counterexample is printed. |
| `KOLEJKA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding or accepted risk no longer happens. If a change fixed it, delete it from `KNOWN_FINDINGS` or `ACCEPTED_RISKS` and from this file. |

## How it works and what it covers

`explore_outbox.py` writes the wysyłki of a scope into a real queue folder in a
temporary directory with `Outbox.post`, then runs passes of the real queue
(`_drain`) in its own thread. Only the start of the queue thread is replaced:
the real `send_in_background` decides, from `_draining`, whether a thread
starts, and the checker runs the target of each started thread. Behind `KeyedBox` stands `MemoryBox`, GitHub's
issues, labels, bodies and comments in memory. The file of `KeyedBox`'s writes (`OPENING_FILE`) and the Centrum log stay
in memory too, and between two schedules the checker removes only the files of the run directory, not its folders: the
checker fails none of them, and on disk they only took time (#911: from 91 s to 41 s for `archiwum-diagnoza` on Maks's
Mac on 2026-11-05, with the same 19 874 schedules). Before each step in the table
the checker picks one option:

- a box read: it answers, the network fails (`Unreachable`), or the process dies;
- a box write (`open_issue`, `comment`, `edit_comment`): it is accepted, the
  network fails before the Skrzynka sees it, the Skrzynka accepts it and the
  answer is lost (`Unreachable` after the effect, as a timed-out POST or PATCH to
  GitHub), or the process dies before it;
- a read of the Archiwum (`archive`) or a write to it (`open_archive`, `remove`,
  `upload`): as a box read or write, or the step is refused (GitHub's 403, in a
  scope with a refusal bound); an upload may also break off in the middle of the
  file, which leaves it in the Archiwum not whole. In a scope whose repository
  has no commit, every `open_archive` GitHub answers is its 409. The checker
  hands each refusal to the real `GitHubReportBox` (`_github`), so the outcome
  the queue gets is the code's reading of GitHub's answer;
- the marker or the removal: it works, raises `OSError` (Windows, antivirus or
  OneDrive holding the file), or the process dies before it;
- a read of a queue file, in a scope with a read bound: it works or raises
  `OSError` (antivirus or OneDrive holding the file), so the files after it go
  first;
- before a pass, while the scope has a later wysyłka the code has not posted
  yet: it arrives now (`Outbox.post`) or not yet; it arrives anyway when nothing
  else is left to move the queue;
- when files are left and nothing asked for a pass: the `RETRY_S` wake fires,
  if the code armed one, or Centrum restarts. Without an armed wake, the queue
  may also stay as it is until the next start. When the wake or the start does
  not ask for a pass either, the schedule ends there, and the rules judge what
  is left.

With `list_lag` a list catches up only when the `RETRY_S` wake moves the clock,
the longest lag `KeyedBox` allows for; a restart takes no time. `watek-okresu-lista`
and `archiwum-lista` run with 1 network failure, 1 lost answer and 1 killed or
restarted Centrum (`watek-okresu-lista` also 1 file error; with `BOUNDS` it also
passes, 11 827 schedules in 40 s on Maks's Mac on 2026-11-05). Bounds in every scope: at most 2 network failures, 1 lost answer, 1 file error
and 1 killed or restarted Centrum, and no refused step of the Archiwum;
`archiwum` runs with 1 network failure (an upload that breaks off counts as one)
and 1 refused step of the Archiwum (with 2 network failures it also passes,
93 960 schedules in 188 s instead of 15 210 in 28 s on Maks's Mac on 2026-11-04),
`archiwum-diagnoza` with no network failure, 1 lost answer, no file error, 1
killed or restarted Centrum, 1 failed read of a queue file and 1 refused step of
the Archiwum (17 086 schedules in 55 s on Maks's Mac on 2026-11-05),
`archiwum-puste-repo` with 1 network failure, 1 lost answer, 1 file
error and 1 killed or restarted Centrum, and an Archiwum that refuses every time
(5 337 schedules in 16 s on Maks's Mac on 2026-11-05); `diagnoza` runs with 1 network failure,
`diagnoza-odczyt` with 1 network failure, 1 lost
answer, 1 failed read of a queue file, 1 killed or restarted Centrum and no file
error (`diagnoza` checks the file error with two versions), and `postep` with 1
network failure, no lost answer, 1 file error and 1 killed or restarted Centrum
(with 1 lost answer too it also passes, in 218 s instead of 30 s on Maks's Mac on
2026-11-05; `diagnoza` and `archiwum-diagnoza` check the lost answer with two
versions). After the failures run out the queue gets 3 more passes to empty
itself, and one more for each later wysyłka. The checker re-runs the code from scratch for
every schedule. A schedule that reaches a pass boundary already explored stops
there: the code is deterministic, and the state decides every future and how
its breaks are judged. The state is the Skrzynka, the queue files, the files
`_remove` could not delete, the faults so far and those left, the passes left
and the exceptions so far, the later wysyłki not posted yet and whether the
Skrzynka got a text of a superseded version. The version in the marks of the Skrzynka's texts
counts as the place of its wysyłka in the scope, because every schedule posts
the wysyłki anew at another moment. `_state` in `explore_outbox.py` names what
it leaves out and why.

| Scope | Wysyłki |
| --- | --- |
| `zgloszenie` | one Zgłoszenie (`ReportIssue`) in one part, as every Zgłoszenie is |
| `zgloszenie-wrocilo` | one Zgłoszenie in one part whose odcisk already has an open Zgłoszenie in the Skrzynka: the part goes to it as a comment |
| `watek-okresu` | two Kontrole ilości to one issue okresu (`PeriodThread`), in two and one part |
| `nowe-issue` | one Uwaga taty (`NewIssue`) in two parts |
| `znane-issue` | a comment in two parts to the existing issue of an Uwaga taty (`KnownIssue`) |
| `diagnoza` | Logi Uruchomienia (`PeriodThread` with a header) in two parts, then, as a later wysyłka, their Diagnoza, a newer version of the same wysyłka in one part: it changes part 1 and retires part 2, and while the Logi still wait it replaces their file in the queue |
| `diagnoza-odczyt` | the same Logi and Diagnoza, both queued at the start, and one queue file can be unreadable once: the Diagnoza goes first, and the Logi that arrive after it change and add nothing |
| `archiwum` | Logi Uruchomienia in one comment with a file for the Archiwum Logów okresu (`PeriodThread` with a header and `archive`): the file goes before the comment, and a refused step of the Archiwum leaves the file in the queue and the comment with its note |
| `archiwum-diagnoza` | those Logi and, as a later wysyłka, their Diagnoza, a newer version that replaces the file (`remove`, then `upload`) and changes the comment; the older queue file can be unreadable once, arrives after the newer one and changes nothing |
| `postep` | the progress of a Wycena w efenix (Logi of its Uruchomienie in one comment without a file for the Archiwum), then, as later wysyłki, a newer progress and the Logi with a file for the Archiwum: one comment of the Uruchomienie, the summary at the end, and a newer version in the queue replaces the file of an older one |
| `archiwum-puste-repo` | those Logi and after them a Zgłoszenie, in a repository without a commit: GitHub answers 409 to every `open_archive`, so the Logi file waits in the queue with the marker of its parts, while the comment of the Logi and the Zgłoszenie arrive |
| `watek-okresu-lista` | the two Kontrole of `watek-okresu`, and GitHub's list of issues shows a new issue only `LIST_LAG_S` after it was opened (`list_lag`): the second Kontrola in the same pass, a retry after a lost answer and a start of Centrum come before the list shows the issue okresu |
| `nowe-issue-lista` | the Uwaga taty of `nowe-issue` with `list_lag` |
| `zgloszenie-lista` | the Zgłoszenie of `zgloszenie` with `list_lag` |
| `archiwum-lista` | Logi of two Uruchomienia of one period, each with a file for the Archiwum, and the list of Releases shows a new Archiwum only `LIST_LAG_S` after it was opened (#887): the second Logi in the same pass and a retry after a lost answer add their file to the Archiwum that is there, with no refusal of a second Archiwum and no note that the file waits |

Not covered: a key that is missing or refused (`NoKey`, `Refused`: the pass
stops, nothing is sent, and `KeyedBox` keeps a refusal for `REFUSED_KEPT_S`), a
step of the Archiwum `Rejected` for its content (it is `ArchiveWaits` like a
refusal, which the scopes of the Archiwum check), the Archiwum of another period,
Maks deleting the Archiwum or a file in it,
content the Skrzynka rejects (`Rejected`: the file waits for the next start,
and the same content would be rejected again), Maks closing or deleting an
issue (`Gone`, `closed="reuse"`; after Maks closed the issue of a Kontrola
ilości, a delivered file without its delivery marker would open a new issue
okresu with the whole Kontrola), a failed read of a queue file outside
`diagnoza-odczyt` and `archiwum-diagnoza` (the model's `odczyt` and `diagnoza` have it), a later wysyłka posted in the
middle of a pass (it arrives only between passes; the model's `Nadaj` has it), a clock that
goes back between two wysyłki (every schedule posts in order with the real
clock; `test_logi_z_diagnoza_po_cofnieciu_zegara_komputera_zmieniaja_komentarz_uruchomienia`
checks `Outbox.post`), a
delivered file with its marker that waits for the next start, two queues on one folder (`_claimed`,
`_folder_lock`), a process killed in the middle of `replace_atomically` (it leaves a `.tmp` that
`resume` removes), `prepare` holding a wysyłka back, a queue thread running at
the same time as `post` or `wait_delivered` (the checker runs each thread to its
end), the `Listener` (Sprawy taty) and the wysyłki it returns, and
a lag of the list of an Archiwum's files or of an issue's comments (neither was
measured; the files `KeyedBox` adds after its own writes cover the first in one
Centrum), a list that lags longer than `LIST_LAG_S`, a failed read or write of
`OPENING_FILE` (also the held decision `Gone` about a fresh known issue, #915,
which only such a failure reaches; the model's `znane` has it), and
more wysyłki or failures than the bounds above. The TLA+ model below checks, on its
own abstraction of this code, two queues on one folder, also in two Centrum
processes, a process killed in the middle of `replace_atomically`, a queue thread running at the same time
as `post`, refused content and two file errors in a row.

## Known findings

None. The former finding `przejecie` (a retried Zgłoszenie in several parts
lost its later parts) is gone since a Zgłoszenie always has one part (above).

A known finding lives in `KNOWN_FINDINGS` in `explore_outbox.py`, with the
faults after which it is excused. When a code change fixes it, the check ends
with `ZNALEZISKO ZNIKNĘŁO`: delete the entry there and here.

## Accepted risks

None. The former risk of a second issue of an Uwaga taty after the connection
broke (ADR 0015 before its note of #840) is gone: the retry finds the issue by
the mark in its body (`_deliver_new_issue`).

An accepted risk lives in `ACCEPTED_RISKS` in `explore_outbox.py` with the
decision it rests on and the faults after which it is accepted.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a box call
in the code's words (`open_issue`, `comment(#n, część k/n)`, `edit_comment(#n, część k/n)`, `labelled_issues`, `comments(#n)`),
what the Skrzynka did, a file step of `_send_all`, or a pass or restart. Then
sort it:

- **Real bug**: every step can happen at Dad's (a network that drops, a POST
  whose answer is lost, Windows holding a file, Centrum closed), and the end
  state breaks the rule as stated above. Report it with the story. Fix the
  product code only if the user asks. If the user accepts the risk instead,
  record the decision in an ADR and add an entry to `ACCEPTED_RISKS` naming it.
- **Modeling error**: a step the code cannot take or GitHub would not do, for
  example `MemoryBox` returning an issue with another label, or a failure at a
  step the table does not list. Fix `MemoryBox`, `Scheduler` or
  `_intercepted`, and say what was wrong.
- **BEZ_WYJATKU**: a pass raised. The printed type and message name the
  exception; find where `_send_all` lets it out.

Never shrink a bound, a scope or a rule to make a real counterexample go away.

## After changing the checker or an intended change to the queue

CI proves the check can still fail: the night on `main` runs
`.agents/skills/verify-kolejka-skrzynki/scripts/check_outbox_mutations.py`
after a change of this skill's folder. It applies each broken variant of
`outbox.py` to a temporary copy of the checkout (`tools/mutacje.py`) and must end
with `MUTACJE OK`. Each mutation runs one scope with `--stop-at-new`, because it needs only the verdict, while
its base, the same command without the mutation, still explores every schedule of the scope. Run to the end, a
mutation explored every schedule after its violation: the one of `archiwum-diagnoza` 23 787 after a violation in
the first, and with eight mutations at once on the four vCPU of Windows CI it ran over the 600 s limit (#963). On
Maks's Mac on 2026-11-05, with six of them at once, the slowest mutation took 7.7 s with the stop instead of 61.7 s,
and every one ended with the same verdict and only rules its full run reports.
Each of these gives `KOLEJKA: NOWE NARUSZENIE`:

- a failed comment skipped, in `_comment_all` (`nowe-issue`) and in `_settle` (`znane-issue`);
- a Zgłoszenie that returned taken over without a comment (`zgloszenie-wrocilo`);
- a found issue okresu missing part 1;
- an issue okresu opened without looking for it;
- a known issue missing part 1;
- no check of the identifier before sending: `_put` sends a part that is already there (`znane-issue`);
- a Diagnoza that adds a comment instead of changing it (`diagnoza`);
- a part the newer version lacks left in place instead of `_RETIRED` (`diagnoza`);
- an older version that arrives after a newer one and adds its part, `_settle`
  without the check of a newer version (`diagnoza-odczyt`);
- an Uwaga taty that does not look for its issue by the mark (`nowe-issue`);
- a file in the Archiwum without the check of the version in its label: the queue removes its own whole file and
  sends it again (`archiwum-lista`: `archiwum` catches it too, but after 38 024 schedules instead of 4 130);
- a file whose upload broke off taken as sent, without `uploaded` (`archiwum`);
- a wysyłka without the step of the Archiwum (`archiwum`);
- a file of an older version that is not removed before the upload of the newer one (`archiwum-diagnoza`);
- an older version that arrives after a newer one and replaces its file (`seen == version`, `archiwum-diagnoza`);
- no replacement of an older version in the queue (`_superseded`): every progress goes to the Skrzynka (`postep`,
  NAJNOWSZA_WERSJA); the stand-in version of a lower rank posted after the Logi with the result is out of the
  checker's scopes, and the model's configuration `starsza` and the tests of `tests/test_centrum_logi_uruchomienia.py`
  (#910) check it;
- a replacement by the target alone, without `run_id`: the second Kontrola ilości of a period removes the first
  (`watek-okresu`);
- a superseded file removed without its delivery marker, so one whose removal fails waits without it (`postep`);
- a file the Archiwum refused that gets the whole marker and leaves the queue (`archiwum`);
- a list of issues without the issues `KeyedBox` just opened (`keyed_box.py`, `watek-okresu-lista`);
- a write to the Skrzynka without the hold after a write without an answer (`_held`, `nowe-issue-lista`);
- the writes kept only in memory, so a new Centrum does not know them (`OPENING_FILE`, `nowe-issue-lista`);
- an Archiwum without the Archiwum `KeyedBox` just opened (`archiwum-lista`);
- an upload to the Archiwum without the hold after an upload without an answer (`archiwum-lista`);
- a refusal of the Archiwum that arms no `RETRY_S` wake (`archiwum`);
- GitHub's 409 to a new Release in a repository without a commit read as `Unreachable`, as
  `GitHubReportBox.open_archive` did before #860 r2, so the pass stops at the Logi and the Zgłoszenie after them never
  arrives (`report_box.py`, `archiwum-puste-repo`);
- a network failure that skips the file instead of stopping the pass;
- an Uwaga taty that opens two issues;
- no `RETRY_S` wake after a pass that stopped;
- a `RETRY_S` wake that does not ask for a pass (`_woken`);
- a start that does not ask for a pass (`resume`);
- a new wysyłka that does not ask for a pass (`post`);
- a pass that does not clear `_draining`, so later requests only set `_again`;
- `send_in_background` that never starts the queue thread.

No mutation removes the delivery marker or writes it after the removal: since
#840 neither breaks a rule here, because a retry finds every part by its mark
(How the queue knows what is already there). A mutation reported as `NIEAKTUALNA` no longer
matches `outbox.py`: rewrite its `anchor` and `replacement` against the new code
so that it breaks the same rule again.

## The TLA+ model

`model/KolejkaSkrzynki.tla` is a hand-written TLA+ model of the same queue,
which TLC checks in every order of steps and failures. It describes the code
only while you keep the two in step (Sync commit above). It adds what the
checker cannot run: threads that interleave (a wysyłka posted during a pass,
the `RETRY_S` wake, a second queue of one folder, a second Centrum process),
the temporary file and the rename of `replace_atomically` as separate failure
points, a switch-off at every step, refused content (`Rejected`), a queue file
that cannot be read, two file errors in a row, the Diagnoza of Logi as a
newer version of the same wysyłka, one part shorter, also sent before the older
one, the progress of a Wycena w efenix as an older version of its Logi
without a file for the Archiwum, whose file a newer version in the queue
replaces, and GitHub's lists that catch up with a new issue or Archiwum at any
step (`OpoznienieListy`), also between the list and the write.

### The model's promise

- **JednoIssue**: one period and one problem of a Zgłoszenie have one issue,
  a comment to a known issue opens none, one Uwaga taty has one issue (a
  retry finds the issue an interrupted attempt opened by the mark in its body),
  and one period has one Archiwum Logów okresu (`wydania`). Harm as JEDNO_ISSUE.
- **DokladnieRaz**: a queue file disappears or gets its delivery marker only
  when every part of it is in the Skrzynka, in its version or a newer one of
  the same wysyłka, with its file in the Archiwum (a file whose wysyłka has a
  newer version in the queue may go without them), a queue file gets the marker
  of its parts (`"skomentowany"`) only when every part is there, no part of any
  wysyłka is in the Skrzynka twice, in one version or two, the Archiwum has at
  most one file of a wysyłka, the queue never removes a file of its version or a
  newer one to send it again (`podwojny`), and once a version was sent no
  comment or file of an older version of it is left, and no part goes with the
  note that the file waits because GitHub refused a second Archiwum of the tag
  (422, ghost `falszywe`). Harm as DOKLADNIE_RAZ.
- **CzesciWKolejnosci**: in every issue, part k > 1 of a wysyłka has part
  k-1 of the same wysyłka (in any version) before it, so the issue reads in
  order. Harm: a Kontrola ilości or an Uwaga taty in several parts that does not read in order.
- **Zbieganie** (liveness): once failures stop, no file without its marker
  (also none with the marker of its parts only) is left of a wysyłka that `post` wrote to the queue, except a file whose
  content the Skrzynka refused (`Rejected`, waits for the next start) or a
  sent file `_remove` could not delete (`_undeleted`, every part in the
  Skrzynka). In a repository without a commit (`PusteRepo`), whose Archiwum
  never comes, a file with the marker of its parts may stay, but none without
  it: a refusal of the Archiwum stops only the file, not the parts of this or the
  next wysyłka. A file that was deleted, lost after `post` accepted it, or got
  its marker without every part breaks DokladnieRaz, so Zbieganie looks only at files without a marker,
  and every known finding breaks one promise. Harm as KOLEJKA_PUSTA.

Each element of an issue in the model is the mark of one text, `<<w, k>>`: part
`k` (0: the header) of wysyłka `w`, and `Nr(w)` is its place in the order of the versions (`Version`), the order of
the queue files. With `Diagnoza` the wysyłka 2 is a newer version of the
wysyłka 1 (`Id`) in `CzesciNowszej` parts: its comments replace theirs in place,
as `edit_comment` does, and the comment of a part it lacks gets its mark, as
`_RETIRED` does. `archiwum` is the files of the one Archiwum Logów okresu, each as
the version `w` of the wysyłka it belongs to; GitHub's one file per name makes an
upload over a file of the same wysyłka `Rejected`.

### Model action and code

Each action is one indivisible step of the code in `src/rozliczenia/centrum/`.
The comment above each action and branch in the model names the same code.

| Model action | Code |
| --- | --- |
| `Start` | `app.py` `lifespan` → `outbox.py` `Outbox.resume`: unlink every `*.tmp` (also one that the old process still writes: its `post` returns `False`, its marker is lost), then `send_in_background`; its `KeyedBox` has no list of its thread yet (`odczyt`), and the file of `KeyedBox` (`zakladanie`, `pamiec`, `pamiecWydania`) stays. Only a process with the port starts (`launcher.py` `listen_locally`); a second queue of one process starts while the first runs |
| `Nadaj` | `outbox.py` `Outbox.post`: the name from the moment and `next(self._sequence)`, `replace_atomically` (`write_text` of `.json.tmp`, then `replace`; `OSError` → `False`, also the `FileNotFoundError` of `replace` when `resume` of a new process removed the `.tmp`), then `send_in_background` |
| `Petla` | `Outbox._drain`: `_claimed` (taken → ask for another pass and skip `_send_all`), then `_folder_lock` without waiting (held by a queue of another process → `_locked_out` and skip `_send_all`), then `_read_failed = False` and `sorted(glob("*.json"))` in `_send_all` |
| `Plik` | `Outbox._send_all` for one file: `_undeleted` → `_remove`, `_rejected` → skip, `_queued` (an `OSError` or a missing file → `_read_failed` and `_skip_unreadable`), `delivered` → `_remove`, a newer version (`Nr`) of the same wysyłka that the pass read at its start (`czytane`, `Nowszy`, `_superseded`), before or after this file in the list → the marker without sending (`Znacznik`, `_mark_delivered`), or, when the newer file is later in the list and cannot be read (`NowszyDalej`, `_read` at the start of the pass, `_read_failed`), this one as usual and the newer one out of the list, as `_skip_unreadable` skips it to the `RETRY_S` wake, `commented` → `_deliver_archive` alone, else `_deliver`; the end of the list sets `_stopped_on = None`. `Znacznik` also sets `stopped` to FALSE after a superseded file, which the code does not: the pass then either stops on a later file, which sets it again, or ends with `_stopped_on = None` |
| `Szukaj` | `keyed_box.py` `KeyedBox.labelled_issues` (`report_box.py` `newest_with_line`; the list shows the issues `GitHub` lists and those any `KeyedBox` opened with an answer, from the file, `Widoczne`, and records whether a write without an answer in the file is less than `LIST_LAG_S` before this list, `odczyt`, `_listed_at` of the queue thread; a read of the file that fails, `zna` FALSE in `OdczytyZapisow`, shows only GitHub's list and sets `odczyt`, so the next opening is held) in `_deliver_to_period`, `_deliver_report` (a found Zgłoszenie gets the part as a comment `returned_report`), `_deliver_to_known` (`KeyedBox.known_issue`: the issue on the list → `Czytaj`; without it a list at which a write would be held, `~zna` or `Swieze`, → `Unreachable` (`Stop`), any other → `Gone`, `_remove` without sending, #915) and `_deliver_new_issue` (the newest issue whose body has a mark of the wysyłka) |
| `Czytaj` | `KeyedBox.comments` in `_seen` (`_settle`, `_deliver_to_period`), then its plan: nothing when the issue has a mark of the wysyłka in a newer version (`Nowsza`); otherwise a part with its mark in the body, or in its first comment in this version or a newer one, is skipped (a Zgłoszenie whose body has the mark of its part is `Delivered(found, ())`), a comment in an older version is changed, the rest is a new comment, and then the comment of each part this version lacks gets `_RETIRED` (`Wycofaj`) |
| `Zaloz` | `KeyedBox.open_issue` in `_deliver_new_issue`, `_deliver_report`, `_deliver_to_period`, with `Post.opening` and the marks (`_opening`): held (`_held`, `Wstrzymane`) → `Unreachable` without a request; the note of the write fails (`_noted`, `OSError`) → `Unreachable` without a request; otherwise the write in the file and the request (`Zapis`): `Sent` replaces it by the issue (`pamiec`), unless writing the file then fails (`_settled`, `OSError`: the write without an answer stays), no answer keeps it, `Rejected` restores the file (`_settled`) |
| `CzytajArchiwum` | `KeyedBox.archive` in `_deliver_archive` (the Archiwum is on the list of Releases or is one a `KeyedBox` opened with an answer, `_Notes.archives`, `pamiecWydania`; records `odczyt` and a failed read of the file as `Szukaj` does), after `Szukaj` without an issue okresu or after `Czytaj` without a newer version (`_newer`), or alone for a `commented` file; `archive_open` false (`_archive_refused`) → `ArchiveWaits` without asking; a file of this version or newer stays, an older one → `UsunPlik`, none → `WyslijPlik`, no Archiwum → `ZalozArchiwum`; `Refused` → `ArchiveWaits` |
| `ZalozArchiwum` | `KeyedBox.open_archive` in `_deliver_archive`, held and noted as `Zaloz`; a Release of the tag already there → GitHub's 422 → `Rejected` → `ArchiveWaits` (ghost `falszywe`); `Refused` or `Rejected` → `ArchiveWaits`; with `PusteRepo` every answer is GitHub's 409, which `report_box.py` `GitHubReportBox.open_archive` reads as `Rejected` → `ArchiveWaits` (`OdmowaPustegoRepo`) |
| `UsunPlik` | `KeyedBox.remove` of the file of an older version in `_deliver_archive`, right before `upload`; `Refused` → `ArchiveWaits` |
| `WyslijPlik` | `KeyedBox.upload` with `_asset_label` in `_deliver_archive`; a file of the wysyłka already there → `Rejected` (GitHub) → `ArchiveWaits`, as `Refused` |
| `Komentuj` | `KeyedBox.comment` in `_comment_all` and `_settle` (`_put`), or `KeyedBox.edit_comment` in `_settle` (`_put`: the comment of an older version gets this version's text in place; `_RETIRED` in the comment of a part this version lacks), one part per step; the first failure ends the wysyłka |
| `Stop`, `Odrzuc` | `_waiting`: `Unreachable`, `Refused`, `NoKey` → `_stopped_on` and `return`; `Rejected` → `_rejected` and the next file |
| `Znacznik`, `Zamiana` | `_send_all` after `Delivered`: `_stopped_on = None`, then the marker in `suppress(OSError)`: `atomic_file.py` `replace_atomically` (`write_text` of `.json.tmp`, then `replace`; an `OSError` unlinks the `.tmp`); with `archive_waits` `_archive_waits` (`_archive_refused`) and the marker of the parts (`"skomentowany"`), and the next file without `_remove`; a `commented` file the Archiwum refused again only `_archive_waits` |
| `Usun` | `Outbox._remove`: `unlink(missing_ok=True)`, an `OSError` adds the name to `_undeleted` |
| `Zwolnij` | `Outbox._drain`: the end of `_folder_lock` (the lock file closed), then `finally` with `_released`; a request of the other queue sets `_again` |
| `Decyzja` | `Outbox._drain` under `_changed`: `_again` → another pass, else `_draining = False` and `clock.after(RETRY_S, _woken)` when `_stopped_on`, `_read_failed`, `_archive_refused` or `_locked_out` is set and no wake is armed |
| `Budzenie` | `Outbox._woken` (`_retry_armed = False`, `send_in_background`), also in a process that already closed its port |
| `Zamknij`, `KoniecProcesu` | `server.py` `serve`: uvicorn closes the socket, waits up to `_GRACEFUL_SHUTDOWN_S` (5 s) for open connections, then the process ends and the daemon queue thread dies with it |
| `Wylacz` | none: the computer switches off or the process dies; the queue folder, the file `OPENING_FILE` and the Skrzynka stay |
| `Nadaza`, `NadazaWydanie` | none: GitHub's list of issues shows a new issue, its list of Releases a new Archiwum |
| `Przedawnienie` | `keyed_box.py` `_held`: a write without an answer in the file is `LIST_LAG_S` old, which happens only once its list shows every write of its kind (assumption below); a list asked for earlier keeps holding (`odczyt`) |

Ghost variables have no counterpart in the code and serve only the promises:
`zakolejkowane` (`post` returned `True`), `odrzucone` (the Skrzynka answered
`Rejected` for this wysyłka), `podwojny` (`UsunPlik` removed a file of the
wysyłka's version or a newer one, so the queue sends that file again), `slady`
(causes of the known findings, none now) and `krok` (the counterexample's words).

### Bring the model in line, then run

1. Read the diff of the covered files since the Sync commit
   (`git diff <sync commit> -- <covered files>`) and find each hunk's row in
   both tables.
2. Change the matching action so that one action stays one indivisible step
   of the code, and keep the comment that names the code. TLA+ strings must be
   ASCII; comments may use Polish letters.
3. A new way to fail gets a constant, a branch guarded by it, and a line in
   every `.cfg`.
4. Before you trust a pass on a new path, break that path in the model and
   see the check fail; add the break to `check_model_kolejki_mutations.py`
   with the code it mirrors. A new guard in the model needs a counterpart in
   the code; name it in the guard's comment.
5. Move the Sync commit forward only when the checker and every row of both
   tables match the code at the new commit. Rewrite the Sync paragraph for the
   new commit instead of adding to it, and put what changed since the previous
   sync in the commit message.

Run one configuration while you work:

```bash
.venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py --config okres
```

On Windows use `py -3`. It takes Java and `tla2tools.jar` from
`verify-aktualizacja-narzedzia` (`sprawdz_aktualizacje.py` downloads them
once into its ignored cache, no system Java needed); `TLC_JAVA` and `TLC_JAR`
replace them. All configurations take about 45 s on Maks's Mac (2026-11-04), `archiwum` about 18 s of it; with the
lagging lists (#879) about 107 s under load on 2026-11-05, `archiwum` 24 s, `okres` 14 s and `archiwum-lista` 11 s of it; with the failed read of the file of `KeyedBox` (#909) `okres` took 14 s and `archiwum-lista` 24 s under load on 2026-11-05. `--strict`
makes known findings exit 1.

| Last line | Exit | Meaning |
| --- | --- | --- |
| `MODEL KOLEJKI OK` | 0 | Every promise holds in every configuration. |
| `MODEL KOLEJKI OK, ZNANE ZNALEZISKA: n` | 0 | Only the known findings below break a promise, each only its own and after its cause; each is printed with its counterexample, and with every known finding excused the configuration passes. |
| `MODEL KOLEJKI: NOWE NARUSZENIE (n)` | 1 | A promise breaks in a way no known finding explains: another promise than the finding's, or its promise without its cause in `slady`. The counterexample is printed. |
| `MODEL KOLEJKI: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding no longer happens. If a change fixed it, set `"wynik": "przechodzi"` in `model/oczekiwane.json` and remove it below. |
| `MODEL KOLEJKI: BŁĄD MODELU (n)` | 2 | TLC gave no verdict (a syntax error) or `TypeOK` broke. Nothing is known about the promise. |
| `MODEL KOLEJKI: ROZJAZD MODELU Z KODEM` | 1 | Only in CI: covered code changed since the Sync commit. Outside CI the same is a `UWAGA:` line above the verdict, and the verdict means nothing until you bring the model in line. |

Each known finding in `model/oczekiwane.json` names the promise it breaks
(`obietnica`) and its cause (`przyczyna`), a mark in `slady` that only the step
of the code it names sets. It runs twice, as in `verify-aktualizacja-narzedzia`.
First excusing every other known finding: it must break exactly its promise,
and the last state of the counterexample must have its cause in `slady`;
another promise, or the right one without the cause, is `NOWE NARUSZENIE`.
Then excusing every known finding: it must pass. A finding excuses only its
own promise (`Wybaczone<promise>`, the `<promise>PozaZnanymi` variant), and
only in a behaviour in which its cause happened; every other promise of its
configuration is checked in full.

### Configurations

| Config | Wysyłki and failures | Expected |
| --- | --- | --- |
| `okres` | two Kontrole ilości to one issue okresu, 2 parts each; 1 network failure, 1 lost answer, 1 file error, 1 switch-off | passes |
| `logi` | Logi Uruchomienia with a header, 2 parts; 2 network failures, 1 lost answer, 2 file errors, 1 switch-off | passes |
| `nowe` | two Uwagi taty, 2 parts each; 1 network failure, 1 lost answer, 2 file errors, 1 switch-off | passes |
| `zgloszenie` | two Zgłoszenia of one odcisk in 1 part each, the second as a comment to the issue of the first; 2 network failures, 1 lost answer, 2 file errors, 1 switch-off | passes |
| `znane` | a comment in 2 parts to the known issue of an Uwaga that the queue just opened, so GitHub's list may not show it yet (`OpoznienieListy`, `Swiezo`: the file of `KeyedBox` has its effect or a write without an answer, #915); 2 network failures, 1 lost answer, 2 file errors (also a failed read of the file of `KeyedBox` at the list), 1 switch-off | passes |
| `dwie-kolejki` | two queues of one folder in one process, one Kontrola in 2 parts; 1 network failure, 1 file error, 1 switch-off | passes |
| `dwa-procesy` | one Kontrola; the old Centrum closes its port and the new one starts before the old process ends; no other failure | passes |
| `odczyt` | one Kontrola; 1 network failure, 1 read error of the queue file, 1 switch-off | passes |
| `odmowa-tresci` | one Uwaga in 2 parts; 2 refused contents, 1 file error, 1 switch-off | passes |
| `diagnoza` | Logi Uruchomienia with a header, 2 parts, and their Diagnoza in 1 part, a newer version of the same wysyłka (`Diagnoza = TRUE`, `CzesciNowszej = 1`); 1 network failure, 1 lost answer, 1 file error or read error of the queue file, 1 switch-off | passes |
| `archiwum` | Logi Uruchomienia with a header in 1 part with a file for the Archiwum (`Archiwum = TRUE`) and their Diagnoza, a newer version that replaces the file; 1 network failure, 1 lost answer, 1 refused step of the Archiwum, 1 file error or read error of the queue file, 1 switch-off | passes |
| `puste-repo` | the Logi of two Uruchomienia of one period, each with a file for the Archiwum, in a repository without a commit (`PusteRepo = TRUE`): every `open_archive` gets 409; 1 network failure, 1 lost answer, 1 file error, 1 switch-off | passes |
| `postep` | the progress of a Wycena w efenix in 1 part without a file for the Archiwum, then the Logi of its Uruchomienie in 1 part with a file, a newer version of the same wysyłka (`Postep = TRUE`); 1 network failure, 1 lost answer, 1 refused step of the Archiwum, 1 file error or read error of the queue file, 1 switch-off | passes |
| `starsza` | the Logi of an Uruchomienie in 1 part with a file for the Archiwum, then a stand-in version of the same wysyłka with a file, posted later but older (`StarszaPozniej = TRUE`, #910); 1 network failure, 1 lost answer, 1 refused step of the Archiwum, 1 file error or read error of the queue file, 1 switch-off | passes |
| `archiwum-lista` | the Logi of two Uruchomienia of one period, each with a file for the Archiwum, and GitHub's lists lag (`OpoznienieListy = TRUE`): the second Logi in one pass and a retry after a lost answer find the Archiwum the first opened; 1 lost answer, 1 file error (also a failed read of the file of `KeyedBox` at a list, #909), 1 switch-off | passes |

`OpoznienieListy = TRUE` (GitHub's lists lag, #879, #887) in `okres`,
`dwa-procesy`, `archiwum-lista` and `znane` (#915, about 6 s on Maks's Mac on 2026-11-05). Without it the lists show every write at
once, the hold could only delay a write, and the model leaves out the hold and
the file of `KeyedBox` (`Zapis`, `pamiec`, `pamiecWydania`, the failed note
or answer of a write and the failed read at a list stay unchanged), which keeps the other configurations as small as
before; `nowe`, `zgloszenie` and `archiwum` with the lag took 29 s, 17 s and over
600 s on Maks's Mac under load (2026-11-05), and the checker's `*-lista` scopes run
those targets.

Every configuration checks `TypeOK`, `JednoIssue`, `DokladnieRaz`,
`CzesciWKolejnosci` and `Zbieganie`. `Zbieganie` holds only under the
fairness in `Sprawiedliwosc`: running code takes its next step, an armed
wake fires, an HTTP request finishes its `post`, an old process ends, Dad
starts Centrum when none runs, and every failure happens at most as often as
its bound.

### Known findings of the model

None. The former finding `przejecie` is gone with the checker's (above): the
model takes a Zgłoszenie in one part as `ASSUME Cel = "zgloszenie" => Czesci = 1`,
whose counterpart is the `ValueError` of `Post`.

A known finding lives in `model/oczekiwane.json` with the promise it breaks
and the cause it is excused after. When a change fixes it, the check ends with `ZNALEZISKO ZNIKNĘŁO`.

### Real bug or modeling error?

Read the counterexample as steps in the code's words and check each step
against its row. If every step can happen in the code in that order, and the
end state (`pliki kolejki`, `Skrzynka`) is what the disk and GitHub would
hold, it is a real bug: report it with the counterexample, and change product
code only if the user asks. If a step cannot happen in the code, fix the
action and cite the line that proves it. `TypeOK` breaking is always a
modeling error. Never shrink a bound, add a guard without a counterpart in the
code, or widen `Wybaczone` to make a real counterexample go away.

### What the model leaves out

Checked only with the bounds in the configurations. Assumed and not checked:

- A second Centrum with the port while another has it: `launcher.py`
  `listen_locally` excludes it, and `Start` takes it as given.
- A lock file that cannot be opened (no queue folder yet): `_folder_lock`
  lets the pass go without the lock. The model's folder always exists.
- `_claimed` guards no promise of the model: the folder lock keeps two queues
  of one process apart too, because each opens the lock file on its own.
  `_claimed` only spares the second queue the `RETRY_S` wait, time the model
  does not have; `test_przejscie_pominiete_przez_druga_kolejke_robi_pierwsza_po_swoim`
  checks that hand-over.
- Every box call returns (`Watek` is weakly fair). A call that hangs holds the
  folder lock only until its process ends: `KoniecProcesu` does not wait for
  the queue thread, as `serve` does not.
- `Nadaj` starts a `post` only in a process with the port. An HTTP request
  that the old Centrum received before it closed its socket may call `post`
  only after the new Centrum's `resume`; when the old process ends before its
  queue sends that file, the file waits for the new Centrum's next wysyłka or
  start. Removing `*.tmp` in `resume` only under the folder lock would let a
  `post` that the old Centrum began before the new one started end the same
  way inside the model (TLC's counterexample in `dwa-procesy`, `Zbieganie`),
  so `resume` removes every `*.tmp` as before, and such a `post` returns
  `False`.
- GitHub's lists catch up within `LIST_LAG_S` (30 s) of a write's moment,
  including the request itself (up to `report_box._TIMEOUT_S`, 15 s): measured
  3.0–6.8 s for issues and 2.8 s for Releases (`verify-github-skrzynki`,
  2026-11-05). `Przedawnienie` takes it as given. The list of an Archiwum's files
  does not lag in the model, so it leaves out the hold of uploads and removals
  (`_file_kind`), which the checker's `archiwum-lista` runs; with the Archiwum
  only through `_Notes.archives` the model shows all its files, as `KeyedBox` shows
  the uploads in the file. The note and the answer of `open_archive` never fail
  to write the file in the model (`Zaloz` has both), and closed issues are not
  modelled, so neither is the list with closed issues of `labelled_issues`.
- `os.replace` is atomic: a switch-off leaves the old file or the new one.
- Only the Logi Uruchomienia have a newer version (`ASSUME Diagnoza => ...`):
  `RunLogs.diagnosed` and the progress of a Wycena w efenix (`RunLogs.progress`,
  then the Logi at its end) are the only callers that queue a wysyłka again with
  the same identifier, in the Centrum process that queued the older one; the Logi
  of an Urwane Uruchomienie or the result without Logi, which replace its
  progress, come from the next process, as a stand-in version (#910). The
  model's order of the versions is `Nr`: the order of the wysyłki, which
  `Outbox.post` keeps also after the clock went back within one process, except
  `StarszaPozniej`, where the later wysyłka is the older version, as a stand-in
  version after the Logi with the result. Which rank each sender picks is the
  model's of `verify-urwane-uruchomienie`. Only the
  configuration `diagnoza` has versions with different numbers of parts, and
  there the newer one is shorter; a longer newer version, whose extra parts
  are new comments, is not checked.
- The queue never edits an issue body, so the model never changes `tresc[1]`.
- NAJNOWSZA_WERSJA is the checker's: the model checks that marking and removing
  a superseded file loses nothing (DokladnieRaz, Zbieganie), not that the older
  version stays out of the Skrzynka. `postep` has one progress before the Logi
  (`Wysylek = 2`); the checker's scope `postep` has two.
- The Archiwum: one per configuration (one period); every file in it is whole
  (an upload that breaks off, which `_deliver_archive` removes by `uploaded`, is
  the checker's); `Refused` and `Rejected` of a step are one bounded failure
  (`MaxOdmowArchiwum`), and `Unreachable` of a step is a network failure; a second
  Archiwum of one tag, which GitHub would reject, counts in `wydania` instead.
  Only configurations with `Archiwum` send a file, and their wysyłki have one part.
  A repository without a commit (`PusteRepo`) lasts the whole behaviour: Maks
  adding the first commit is not modelled, and what GitHub answers is the
  model's word for the reading of `GitHubReportBox.open_archive`, which the
  checker runs for real.
- More than 1 000 comments of an issue: `GitHubReportBox.comments` reads at most
  ten pages, and a mark after them is not seen.
- `Refused`, `NoKey` and `Unreachable` are one failure (`Stop`); the refusal
  memory of `KeyedBox` (`REFUSED_KEPT_S`) is not modelled.
- Not modelled: Maks deleting a known issue (the model's `Gone` is only the
  wrong decision about a fresh issue, which breaks DokladnieRaz), closed issues
  (`closed="new_issue"` or `"reuse"`), the `Listener` (`prepare`, `delivered`
  and `rejected`), the addresses file, more than 1 000 issues of a label, and
  Python exceptions (BEZ_WYJATKU stays with the checker).
- No promise looks at `.tmp` files, so the model does not check that
  `resume` removes them.
- Guards without a counterpart in the code, which only bound the run: one
  port closing per run (`zamkniecia < 1`), a second queue of one process only
  while the first runs (no code in `src/` makes two; a restart in one process
  would), a wysyłka that starts its `post` only after the one before it
  started (its name, from the moment and `_sequence`, sorts after it), and
  `Port`: in one process with two queues (`dwie-kolejki`) every `post` goes to
  the first. Not checked through it: a `post` whose `send_in_background` wakes
  the second queue while the first sleeps. With two processes only one has
  the port at a time, so there `Port` is no choice.

### After changing the model

CI proves the model can still fail: the night on `main` runs
`.agents/skills/verify-kolejka-skrzynki/scripts/check_model_kolejki_mutations.py`
after a change of this skill's folder. Each mutation removes from the model
one guard or step whose code it names, on a copy of the checkout
(`tools/mutacje.py`), and must end with `MODEL KOLEJKI: NOWE NARUSZENIE`:

- JednoIssue: an issue okresu opened without looking for it; an Archiwum opened
  without looking for it (`archiwum`; GitHub refuses the second with 422, so it
  breaks DokladnieRaz through `falszywe`); a Zgłoszenie
  opened without looking for it; `_claimed` that always lets a queue send
  together with a folder lock that is always free (`dwie-kolejki`), and a pass
  without the folder lock (`dwa-procesy`); an
  Uwaga that opens two issues; an Uwaga that does not look for its issue by
  the mark (`nowe`).
- JednoIssue (#879): a list of issues without the issues `KeyedBox` opened
  (`Widoczne` without `pamiec`); a write without the hold; the hold judged at the
  write instead of at the list; the writes kept only in memory, so a new Centrum
  does not know them; a new Centrum without the effects of the old one, whose
  answered writes no longer hold it; a failed write of an effect that drops the
  write without an answer (all `okres`).
- DokladnieRaz (#915): a list without the known issue read as `Gone` although
  the file of `KeyedBox` could not be read at it, and although a write without
  an answer waits in the file (`known_issue` without `_held`, both `znane`).
- DokladnieRaz: an Archiwum without the one `KeyedBox` opened, and an opening of
  the Archiwum without the hold, so the second Logi get GitHub's 422 and the note
  that the file waits (`archiwum-lista`, #887); no check of
  the identifier before sending, every part a new
  comment (`okres`); a file in the Archiwum without the check of its version, so
  the queue removes its own file and sends it again, and a file the Archiwum
  refused that gets the whole marker (`archiwum`); an older version that arrives after a newer one and adds
  its part (`_settle` without the check of a newer version), a Diagnoza that adds
  a comment instead of changing it, and a part the newer version lacks left in
  place instead of `_RETIRED` (`diagnoza`); a failed comment
  skipped instead of ending the wysyłka; a
  Zgłoszenie that returned taken over without a comment (`zgloszenie`); and, in
  the configurations with a refused comment or a read error, a refused
  comment that removes the file instead of `_rejected` (`odmowa-tresci`) and
  an unreadable file removed instead of skipped by `_skip_unreadable`
  (`odczyt`); a `post` that returns True although
  `os.replace` raised OSError (`okres`) or although `resume` of the new
  Centrum removed its `.json.tmp` (`dwa-procesy`); a file marked without being
  sent although no newer version of its wysyłka follows it (`_superseded`
  without the target and `run_id`, `okres`); `_superseded` that takes the
  last name for the newest version, `_settle` and `_put` that compare the
  moment without the rank, and `_deliver_archive` that reads the version of a
  file in the Archiwum without the rank (`starsza`: the stand-in version
  replaces the Logi with the result in the queue, in the issue or in the
  Archiwum).
- CzesciWKolejnosci: comments posted from the last part.
- Zbieganie: a network failure that skips the file to the next start; a pass
  that stops without `_stopped_on`; no `RETRY_S` wake; no `RETRY_S` wake after a
  refusal of the Archiwum (`_archive_refused`) and an upload of the newer file
  without removing the older one, which GitHub keeps rejecting (`archiwum`); GitHub's 409 of a repository without a
  commit read as `Unreachable` (`OdmowaPustegoRepo` as `Stop`, `puste-repo`); no `RETRY_S` wake after
  an unreadable file (`_read_failed`, `odczyt`) or after a folder lock held by
  another process (`_locked_out`, `dwa-procesy`); a wake that does not
  ask for a pass (`_woken`); `post` without `send_in_background`; `_again`
  ignored; a pass that does not clear `_draining`; `resume` without
  `send_in_background`; a superseded file removed without its delivery marker
  (`diagnoza`); a newer version whose read failed skipped without
  `_read_failed`, so the Logi with their Diagnoza wait without a wake
  (`diagnoza`).
