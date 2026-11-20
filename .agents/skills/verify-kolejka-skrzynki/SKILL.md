---
name: verify-kolejka-skrzynki
description: Exhaustively check, on the real code and in a TLA+ model (TLC), that the Kolejka Skrzynki Zgłoszeń (`Outbox` in `src/rozliczenia/centrum/outbox.py`) delivers every part of every wysyłka and the file of the Logi in the Archiwum Logów okresu exactly once, lets a newer version of a wysyłka replace an older one and an older one that arrives later change nothing, keeps one issue per problem and per period, and empties the queue, under every order of network failures, lost answers, file errors, a killed Centrum and GitHub's lagging lists. Use when `tools/skille_dla_zmiany.py` names it, when a change adds a new way to the Skrzynka (a new `Target`, a second writer of queue files, a box call outside `KeyedBox`), or when `explore_outbox.py` or `sprawdz_model_kolejki.py` fails.
pilnuje:
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/keyed_box.py
  - src/rozliczenia/centrum/report_box.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/tool_files.py
  - src/rozliczenia/centrum/run_comments.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
  - tools/lib/eksplorator.py
ci: .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_kolejke.py
ci-czesci: 6
---

# Verify Kolejka Skrzynki Zgłoszeń

Two checks, one queue: `scripts/explore_outbox.py` runs the real `Outbox` and `KeyedBox` under every schedule of
failures within a scope's bounds, and `model/KolejkaSkrzynki.tla` adds the interleavings the checker cannot run.

## What CI runs and what stays local

CI runs the `ci:` command (both checks, each to its end) in Mutation checks whenever a change touches this skill.
`check_outbox_mutations.py` and `check_model_kolejki_mutations.py` run in full CI on `main` and nightly on `main`
(`mutacje-nocne.yml`) after a change of this skill's folder; `check_model_kolejki_mutations.py` also runs on a pull
request that changes a file in `model/`, the script itself or `sprawdz_model_kolejki.py` (ADR 0021), so a model change
that leaves a mutation with `BŁĄD MODELU` turns the pull request red.
Run them locally only to reproduce a red Mutation checks step or the night's issue, or one `--scope` or `--config` while
you work on it.

CI and `tools/szybko.py` catch drift: a covered file or definition that differs from its digest in
`model/definicje.json` (`ROZJAZD MODELU Z KODEM | <skill>: …`).
They cannot tell whether a change to the checker or the model is right, so on every change to the covered code
„Does the change touch it?” and „Bring the model in line” stay with you, and so does sorting a red run („When the check
fails”, „Real bug or modeling error?”).
A change that adds a new way to the Skrzynka (a new `Target`, a second writer of queue files, a box call outside
`KeyedBox`) passes both checks without being checked.

## The promise

The checker's rules live in `scripts/explore_outbox.py`. Their harm:

- **DOKLADNIE_RAZ**: a missing part means Maks never sees the rest of Logi Uruchomienia, a Kontrola ilości or a
  Zgłoszenie, and nobody knows it is missing, because the queue file is gone; a part twice fills the issue okresu with
  copies; an older version left means Maks reads Logi without their Diagnoza. A broken file in the Archiwum: the link
  in the comment leads nowhere or to Logi without their Diagnoza. A refusal of the Archiwum that stops the wysyłki after
  it: a Zgłoszenie or an Uwaga taty behind the Logi waits until Maks adds a commit, and Dad's card says it waits for the
  internet (#860).
  The rule also judges that a comment of a part carries the note that the file waits (`_waiting_note`) only after the
  Archiwum refused a step; otherwise the note stays in the issue for good and says the Token lacks a permission it has.
- **NAJNOWSZA_WERSJA**: a Wycena w efenix without the network queues a progress every 5 minutes, and once the network
  is back Maks's comment would change once for each of them before the newest.
- **JEDNO_ISSUE**: Maks gets the same problem in several issues, and the Powiadomienie follows only one of them; this
  holds also while GitHub's list of issues does not show an issue opened a few seconds before (#879).
- **KOLEJKA_PUSTA**: a wysyłka waits until Centrum restarts or something new is sent, after the network came back; the
  `RETRY_S` wake that `_drain` arms runs the queue again until it is sent.
- **BEZ_WYJATKU**: a pass ends in an exception that `_drain` logs as `nieoczekiwany-wyjatek` „wysyłka do Skrzynki
  Zgłoszeń”.

A Zgłoszenie always has one part, which both checks take as given (the scope `zgloszenie`, the model's `ASSUME`), so
DOKLADNIE_RAZ holds when a retry takes over, without comments, the Zgłoszenie whose body has the mark of that part.
Two guards keep it to one part (#724): `Post` raises `ValueError` for an `OpenIssue` with more
(`test_zgloszenie_w_wiecej_niz_jednej_czesci_to_blad_programu`), and `reports.py` fits the body into `PART_LIMIT`
(`outbox.py`), first by dropping the first frames of the call trace, then the oldest entries of the Centrum log (the
`bardzo_dlugim` tests in `tests/test_centrum_uchwyt_zgloszenia.py`).

## How the queue knows what is already there

A wysyłka (`Post`) goes to a file in `config/zgloszenia/kolejka/` (`Outbox.post`), and one thread of the queue
(`Outbox._drain`, `_send_all`) sends the files in order, marks a sent file with the delivery marker and removes it.
Each text of the queue in the Skrzynka carries the mark of its wysyłka (`outbox.py` `_mark`): element `<<w, k>>` of an
issue in the model is part k of wysyłka w, and w is also its version (the order of the queue files). A Diagnoza is the
second version of the same wysyłka (`Id` in the model), which corrects the comments of the first (`edit_comment`) and
empties the comment of a part it does not have (`_RETIRED`); an older version that arrives after a newer one changes
nothing in the issue.

A wysyłka to the issue okresu may carry a file to the Archiwum okresu (a GitHub Release, #844): the file goes before the
parts, a refusal of the Archiwum leaves the queue file with the marker of the parts (the parts are there, the file
waits), and the Archiwum has at most one file of a wysyłka, in a version no older than the one sent. A refusal of the
Archiwum that lasts (a repository without a commit: 409) stops only the file, and the parts of every wysyłka arrive
(`Zbieganie` with `PusteRepo`). A file whose newer version of the same wysyłka the pass read the queue marks and removes
without sending (`_superseded`, #846); the progress of a Wycena w efenix is an older version of the Logi without a file
to the Archiwum. A version is the rank, then the moment (#910, `outbox.py` `Version`), so the stand-in version of a
start of Centrum, sent after the Logi with the result, may be older than them (`StarszaPozniej`): the order of versions
is `Nr` in the model, not the order of the wysyłki.

GitHub's lists (issues, Releases) show a new issue and the Archiwum late (#879, #887): `KeyedBox` adds to the lists
what it or another `KeyedBox` opened with an answer (the file beside the key, `keyed_box.py` `OPENING_FILE`), and opens
nothing while the file has an opening without an answer and the last list came less than `LIST_LAG_S` after it. Read
this and the tables of the model under „Does the change touch it?” next to `outbox.py` and `keyed_box.py` before you
judge a counterexample.

What the model leaves out of this:

- The mark of rank `OWN` has the moment and number alone, as before #910, and a lower rank writes its number before
  them (`1:20261105T…Z-0001`).
- A list without closed issues leaves out an issue Maks closed: an effect it lacks is added only when the list with
  closed issues does not have it closed.
- Only the list of the queue's own thread counts for the hold (`_held`, `_listed_at`), not a later list of the preview
  or of Powiadomienia. The time of the list counts, not of the write: between the list and the write the queue may
  still send the file of the Archiwum.
- The moment of a write is Centrum's clock (`time.monotonic`, shared by the processes of one computer until it
  restarts). The file keeps only the effects of the last `LIST_LAG_S` and the writes without an answer of the last
  `PENDING_KEPT_S` (an hour).
- Content of the file that is not UTF-8 is content in another form (no writes), which the next write replaces. A file
  that can never be read or written holds every write: the queue waits as without a network and retries at every wake,
  and the Centrum log gets `skrzynka-zapisy-niedostepne typ=<error>` once per Centrum run
  (`NotesFile.unavailable`, `CentrumLog.box_notes_unavailable`).
- The delivery marker and `_undeleted` now only spare a retry its requests and keep a delivered Kontrola ilości from a
  new issue okresu after Maks closed the old one (`closed="new_issue"`), which neither check models.

## Does the change touch it?

The checker runs the real `Outbox` and `KeyedBox`. Each row is one indivisible step of this code that the checker can
fail, lose or kill; `MemoryBox`, `Bounds` and `Scope` in `explore_outbox.py` decide what it may do at each.

| Step in the checker | Code |
| --- | --- |
| a box read | `keyed_box.py` `KeyedBox.labelled_issues` (only the listed issues of this Stanowisko, `_listed` with `box_prefix.owns`; with `newest_with_line` and the body of the issue found, and the issues `KeyedBox` adds after its own writes), called by `_deliver_open_issue`, `_deliver_to_period` and `_deliver_new_issue` in `outbox.py` and, through `KeyedBox.known_issue`, by `_deliver_to_known`, and `KeyedBox.comments`, called by `_seen` (`_settle`, `_deliver_to_period`) |
| a box write | `KeyedBox.open_issue`, `comment` and `edit_comment`, called by `_deliver_new_issue`, `_deliver_open_issue`, `_deliver_to_period`, `_comment_all` and `_put_all` (`_put`, `_RETIRED`; also the one comment of a Zgłoszenie that returned) |
| a read of the Archiwum | `KeyedBox.archive` in `_deliver_archive` (with the Archiwum and files `KeyedBox` adds after its own writes) |
| a write to the Archiwum | `KeyedBox.open_archive`, `remove` and `upload` in `_deliver_archive`; GitHub's 403 and 409 go through the real `GitHubReportBox` |
| a read of a queue file | `Outbox._send_all`: `_read` (`_queued`, `QueueDisk.read`) of every file at the start of the pass, whose `OSError` sets `_read_failed`, skips the file to the `RETRY_S` wake and keeps it from replacing an older version (`_superseded`) |
| a later wysyłka | `Outbox.post` of a scope's later wysyłka between two passes; the code queues it on its own (`RunComments.diagnosed`, `RunComments._progress`) |
| the delivery marker | `Outbox._send_all`: `self._disk.write(path, _queue_text(post, delivered_parts=len(post.parts)))` (`QueueDisk.write`) in `suppress(OSError)` (`_mark_delivered`), also on the file of a superseded version |
| the removal of a queue file | `Outbox._remove` (`QueueDisk.remove`, `_undeleted`) |
| a pass of the queue | `Outbox._drain` (`_claimed`, `_folder_lock`, `_send_all`, `_released`), started by `Outbox.send_in_background` (called by `Outbox.post`, `Outbox.resume` and `Outbox._woken`); one Centrum at a time, so the pass always gets the folder lock |
| the marker of the parts | `Outbox._send_all` after `Delivered` with `archive_waits`: `_archive_waits`, then `self._disk.write(path, _queue_text(post, delivered_parts=len(post.parts), archived=False))` in `suppress(OSError)` |
| the `RETRY_S` wake | `Outbox._drain`: `self._clock.after(RETRY_S, self._woken)` when `_stopped_on`, `_read_failed`, `_archive_refused` or `_locked_out` is set and no wake is armed; a restart drops it with its process |
| a held write | `KeyedBox._ready` (`_notes`, `_held`, `_noted`) before `open_issue`, `open_archive`, `upload` and `remove`: `Unreachable` without a request. The checker never fails the read or write of `OPENING_FILE`: the model fails both (`bledyPliku`), and the unit tests in `test_klucz_zgloszen.py` and `test_kolejka_skrzynki_zgloszen.py` fail the read at a list and for good (#909) |
| a held decision `Gone` | `KeyedBox.known_issue` in `_deliver_to_known`: a list without the known number is `Gone` only when a write with its label would not be held (`_held`), else `Unreachable` without a decision (#915). Every list in the checker reads `OPENING_FILE`, so it never reaches the hold: the model does (`znane`), and `test_komentarz_do_swiezego_issue_ktorego_lista_nie_pokazuje_czeka_zamiast_porzucenia` in `test_kolejka_skrzynki_zgloszen.py` runs both on the real code |
| a restart of Centrum | a new `Outbox` and `KeyedBox` on the same folder, then `Outbox.resume` |

`model/definicje.json` lists the files the checker covers whole, the definitions in `app.py`, `launcher.py`,
`tool_files.py` and `server.py` that only the model covers (two Centrum processes sharing the queue folder,
configuration `dwa-procesy`), and in `run_comments.py` the two callers that queue a later wysyłka (`ASSUME Diagnoza`
below): a change to the rest of those five files is no drift. `RunComments.send_left_behind` and
`_CaseDelivery.delivered`, which the tables of the model name as where a stand-in version and a fresh Uwaga come from,
have no digest here: `verify-urwane-uruchomienie` and `verify-sprawy-taty` hold them.
Each action of `model/KolejkaSkrzynki.tla` is one step of the code: one request to the Skrzynka, one write of a
temporary file, one replace of a file, one removal, one decision under a lock (`src/rozliczenia/centrum/` unless named
otherwise):

| Model action | Code |
| --- | --- |
| `Watek(q)` | any step of the thread `skrzynka-kolejka` of queue `q` while its process lives: one of the actions from `Petla(q)` to `Decyzja(q)` below |
| `Petla(q)` | `Outbox._drain`: the start of the `while` loop, `_claimed`, then `_folder_lock`. A queue that finds a pass of another queue of this folder in its process only asks for the next one (`_PASSES` true) and sends nothing. A claiming queue takes the folder lock without waiting (`_locked`); when a queue of another process holds it, `_locked_out` and the pass ends without `_send_all`. With the lock it clears `_read_failed` and takes the files by name (`PlikiPrzejscia`). `_claimed` and `_locked` are two code steps in one action: only this process sees `_PASSES`, and only a queue of another process can take the lock between them, which gives the same state as its lock taken before `_claimed` |
| `Plik(q)` | `Outbox._send_all`, one file: `_undeleted` (`_remove`), `_rejected` (skipped), `_queued` (the read: a file that cannot be read or that another process removed is skipped, and an `OSError` sets `_read_failed`), `delivered` (`_remove`), a file whose newer version the pass read, before or after it (`_superseded`: `_mark_delivered` without a send; when the newer one after it cannot be read, this one goes as usual and the newer one waits for the wake), `commented` (`_deliver_archive`, only the file to the Archiwum), then `_deliver`, which for every target first asks the Skrzynka for the issue with the label (`Szukaj`). The end of the list is `self._stopped_on = None`. A file whose read at the start of the pass (`_read`) gave `None` supersedes no older version; when the read of a newer version further on the list failed, the newer one does not supersede this file, and when the pass reaches it `_skip_unreadable` skips it to the `RETRY_S` wake (`_read_failed`), so the model takes it off the list at once; a newer version before this file on the list already has its read behind it (`czytane`) |
| `Szukaj(q)` | `keyed_box.py` `KeyedBox.labelled_issues` (only the listed issues of this Stanowisko, `_listed` with `box_prefix.owns`; with `report_box.py` `newest_with_line`), called by `outbox.py` `_deliver_to_period`, `_deliver_open_issue`, `_deliver_to_known` and `_deliver_new_issue`; the read changes nothing in the Skrzynka, a found issue gets the parts through `_settle` (`Czytaj`), a new one through `open_issue` (`Zaloz`). The list sets `_listed_at`, the moment of this list against a write in the file (`_held` at an opening); without a read of the file it is `None`, so `_held` holds openings until a list at which the file reads (#909). By target: `_deliver_to_period` without an issue okresu takes the step of the Archiwum, then a new issue, and in a found one `_settle` with each part (the step of the Archiwum after the comments are read, in `Czytaj`); `_deliver_open_issue` without an open Zgłoszenie with the fingerprint opens a new issue with the only part, and in a found one `_settle` with that part as a comment with the header „again”, while a Zgłoszenie whose body has the mark of this part was opened by an interrupted try of this wysyłka, so `_settle` takes it over without a comment; `_deliver_to_known` (`KeyedBox.known_issue`) with the issue on the list (also from the file of writes) takes `_settle` with each part, and without it a list at which a write with the label would be held (`_held`: the file could not be read or holds a write without an answer, #915) is `Unreachable` without a decision, and any other list is `Gone`: `box_post_dropped` and `_remove` without a send (nobody removes the issue of an Uwaga in the model, so `Gone` breaks DokladnieRaz); `_deliver_new_issue` sends the rest of the parts through `_settle` to the issue whose body has the mark of this Uwaga (the newest, also closed), and opens a new issue without one |
| `Czytaj(q)` | `keyed_box.py` `KeyedBox.comments` in `outbox.py` `_settle`: the comments of the found issue before the send, and from them and the issue's body the plan: nothing when the issue already has a newer version of this wysyłka (`newest > version`), otherwise the parts the Skrzynka does not have yet or has in an older version, then `_RETIRED` in the comments of the parts this version does not have. The read changes nothing in the Skrzynka. In `_deliver_to_period` an issue with a newer version gets nothing, also in the Archiwum (`_newer`); otherwise the step of the Archiwum (`_deliver_archive`), then the parts (`_put_all`) |
| `Zaloz(q)` | `keyed_box.py` `KeyedBox.open_issue`, called by `outbox.py` `_deliver_new_issue`, `_deliver_open_issue` and `_deliver_to_period` with `Post.opening` (the body: the header or part 1, and the identifying line). First `_held`: a moment of an opening in the file less than `LIST_LAG_S` old, without an answer, after which no list came, gives `Unreachable` without a request; then `_noted` writes the moment of this opening (`OSError`: `Unreachable` without a request), and a refusal (`Rejected`) restores the file from before the write. A new issue may not show on GitHub's list yet; when the answer `Sent` came but `_settled` cannot write the effect to the file (`OSError`), the write without an answer stays |
| `Komentuj(q)` | `keyed_box.py` `KeyedBox.comment` (`_comment_all`, `_settle` through `_put`) or `KeyedBox.edit_comment` (`_put`: the comment of a part in an older version gets the text of this version in the same place of the issue; `_settle`: the comment of a part this version does not have gets `_RETIRED` with the mark of this version), one after another; the first failure ends the wysyłka |
| `CzytajArchiwum(q)` | `keyed_box.py` `KeyedBox.archive` (`report_box.py` `GitHubReportBox.archive`: the Release with the tag and its files) in `_deliver_archive`; with `archive_open = False` (`_archive_refused`) `ArchiveWaits` without asking. The steps of the Archiwum end in „jest” or „czeka” and go on to `po`; no network stops the pass (`Stop`); a refusal of any step (`Refused`: no permission to the repository's contents; `Rejected`: the content) is `ArchiveWaits` (`Czeka`). The list sets `_listed_at` of the Archiwum and its files against a write in the file of openings (`_held`), `None` without a read of the file, so `_held` holds the writes of the Archiwum until a read at the next list (#909). The Archiwum comes from the list of Releases or from an effect in the file of writes (`_Notes.archives`), shared by every `KeyedBox`; without a read of the file, from the list alone |
| `WyslijWzorzec(q)` | `keyed_box.py` `KeyedBox.upload` of a Wzorzec in `outbox.py` `_deliver_template`, before the Logs file: the name is a digest of the bytes, so a Wzorzec already there stays (no `CzytajArchiwum` here), and an upload when GitHub already has a file of that name (a second queue) is `Rejected`. A refused Wzorzec (`Refused`, `Rejected`) does not stop the Logs file: `template_waits`, and the step goes on to the Logs file (`PlikLogow`). A Wzorzec cut during its upload (`Asset.uploaded` false) is not in the model, like a cut Logs file |
| `ZalozArchiwum(q)` | `keyed_box.py` `KeyedBox.open_archive` (a Release with the period's tag, no files) in `_deliver_archive`, held like an opening of an issue (`_held`, `_noted`, `Zapis`). In a repository without a commit (`PusteRepo`) GitHub opens no Release and answers 409 „Git Repository is empty.”, which `report_box.py` `GitHubReportBox.open_archive` gives as `Rejected` and `_deliver_archive` as `ArchiveWaits`: the parts go with the note, and the pass goes on to the next files (`OdmowaPustegoRepo`). When a Release of the tag already exists, GitHub answers 422 (`Rejected`): `ArchiveWaits`, although the Archiwum would take the file (the ghost `falszywe`) |
| `UsunPlik(q)` | `keyed_box.py` `KeyedBox.remove` of the file of an older version in `_deliver_archive`, before the upload of this version; the ghost `podwojny`: the removed file was in this version or newer, so the queue would send the file twice |
| `WyslijPlik(q)` | `keyed_box.py` `KeyedBox.upload` of the file of this version (the label with the version, `_asset_label`) in `_deliver_archive`; GitHub keeps no two files of one name, so an upload when the file of this wysyłka is there is `Rejected` without an effect (`ArchiveWaits`) |
| `Znacznik(q)` | `outbox.py` `_send_all` after `Delivered`: `_stopped_on = None`, `listener.delivered` (and the `post` of its wysyłki), `_first_comments`, `_remember_address` (whose `OSError` goes only to the log), then the delivery marker: `replace_atomically(path, _queue_text(...))` in `suppress(OSError)`. This step is `atomic_file.py` `replace_atomically`: `temporary.write_text`, whose `OSError` removes the temporary file and leaves through the `suppress`. A file whose Archiwum did not take it (`archive_waits`): `_archive_waits`, `_archive_refused`, then the marker of the parts (`archived` false) and the next file without `_remove`; a file that already had the marker of the parts waits on without a write. A known difference from the code: `Znacznik` clears `stopped` on every path, while `_send_all` leaves `_stopped_on` after a file a newer version superseded (`_superseded`: only `_mark_delivered`) and after a `commented` file the Archiwum waits for (`ArchiveWaits`: only `_archive_waits`). It is harmless: only `Decyzja` reads `stopped`, after the end of the pass, and the pass either stops later at another file (`_stop` sets `_stopped_on` again) or ends the list with `self._stopped_on = None` |
| `Zamiana(q)` | `atomic_file.py` `replace_atomically`: `temporary.replace(path)` (retried after `PermissionError`; the last `OSError` removes the temporary file). Without the temporary file (`resume` of another process removed it) `replace` raises `FileNotFoundError`, an `OSError` in the `suppress` too |
| `Usun(q)` | `Outbox._remove`: `path.unlink(missing_ok=True)`; an `OSError` (Windows, an antivirus or OneDrive holds the file) adds the name to `_undeleted`, and the next pass of this Centrum work removes the file without a send |
| `Zwolnij(q)` | `Outbox._drain` after `_send_all`: the end of the block of `_folder_lock` (closing the file releases the lock when this queue holds it), then `finally` with `_released`; another queue's request for a pass is `_again`. Two code steps in one action, as in `Petla` |
| `Decyzja(q)` | `Outbox._drain` under `self._changed`: with `_again` the next pass; without it `_draining = False` and, when the pass stopped (`_stopped_on`), skipped a file it could not read (`_read_failed`), met a refusal of the Archiwum (`_archive_refused`) or the folder lock of another process (`_locked_out`), and no wake is armed, `clock.after(RETRY_S, _woken)` |
| `Budzenie(q)` | `Outbox._woken`: the wake of `clock.after` (the clock's thread, also in a process that closed its port) |
| `Nadaj(w)` | `Outbox.post`: the text of the file from `_queue_text` (no disk; a wysyłka or a text of another type is a `TypeError`, which Centrum's wysyłki never give), the name from the moment and `next(self._sequence)`, then `replace_atomically` of the new file (`write_text` of the `.json.tmp` file, then the replace); an `OSError` is False (the wysyłka is lost, the type of the exception goes to the log), then `send_in_background`. The number of a wysyłka is the order of the names: wysyłka `w` starts after `w-1`, and their writes may interleave. When the `.json.tmp` file is gone (`resume` of a new process removed it), `temporary.replace` raises `FileNotFoundError`, an `OSError`, and `post` returns False. Only the queue of the process with the port takes requests (`MaPort`: only that process serves HTTP); in one process with two queues every `post` goes to the first (`Port`), a guard with no counterpart in the code (see What the model leaves out) |
| `Start(q)` | `app.py` `lifespan`: `Outbox.resume` before the first HTTP request removes the `*.tmp` files (each in `suppress(OSError)`) and calls `send_in_background`. Only one process has the port (`listen_locally`); a second queue of the same process appears while the first runs. A new process starts also while the old one still finishes after it closed its socket (`server.py` `serve`: `_GRACEFUL_SHUTDOWN_S`, and the thread of the queue goes on), and its `resume` may remove a `.json.tmp` file that a `post` or a pass of the old process still replaces (`Nadaj`, `Zamiana`). A new `KeyedBox` has no moment of a list; the file of writes stays on disk |
| `Zamknij(q)` | Dad closes Centrum or the restart guardian restarts it: uvicorn closes the socket (the port is free for a new Centrum), and the process still finishes its work |
| `KoniecProcesu(q)` | the process ends after it closed its port, and its daemon threads die with it |
| `Wylacz` | none: the computer switches off or the process of Centrum dies; the disk and the Skrzynka stay (`Zabij`) |
| `Nadaza` | GitHub: the list of issues (`labelled_issues`) starts to show a new issue (`verify-github-skrzynki`: after 3.0–6.8 s) |
| `NadazaWydanie` | GitHub: the list of Releases (`archive`) starts to show a new Archiwum (`verify-github-skrzynki`, #887: after 2.8 s) |
| `Przedawnienie(r)` | `keyed_box.py` `_held`: a write in the file gets old `LIST_LAG_S` after its moment (`0 <= now - moment`), and a list of a request asked later already shows it. Assumed (What the model leaves out): a request within `report_box._TIMEOUT_S` and the lag of the list fit in `LIST_LAG_S`, and each write first writes its moment, so it gets old only when its list shows every write of its kind; a list that came earlier (`odczyt`) holds on |

Definitions the actions share:

| Model definition | Code |
| --- | --- |
| `ASSUME Cel = "zgloszenie" => Czesci = 1` | `outbox.py` `Post.__post_init__`: a Zgłoszenie (`OpenIssue`) in more than one part is a `ValueError` (#724) |
| `ASSUME Diagnoza => …`, `ASSUME CzesciNowszej …` | only the Diagnoza of the Logi Uruchomienia gives a newer version of a wysyłka: an issue okresu with a header; without a Diagnoza every wysyłka has `Czesci` parts |
| `ASSUME Archiwum => …`, `ASSUME PusteRepo => Archiwum` | `Post.__post_init__`: a file to the Archiwum goes only with one part to the issue okresu (the Logi with a header); a repository without a commit refuses only the opening of the Archiwum, so it matters only with a file |
| `ASSUME Postep => …`, `ASSUME StarszaPozniej => …`, `ASSUME Wzorzec => …` | a progress is an older version of the Logi (the same `run_id` and label), and the full Logi at the end carry the file to the Archiwum; a stand-in version is a version of the Logi with a file to the Archiwum (`run_comments.py` `RunComments.send_left_behind`) after the Logi with the result; only the Logi of a Centrum work carry Wzorce (`comment_versions.py` `OwnLogs`), the progress and the stand-in version none |
| `Id(w)`, `Liczba(w)`, `MaPlik(w)`, `Nr(w)` | the id of wysyłka `w` (the label and `run_id` in the mark; with `Diagnoza` wysyłka 2 is a version of 1); its parts (`Post.parts`; a newer version may have more or fewer than an older one); it carries a file to the Archiwum (`Post.archive`; the progress of a Wycena w efenix, wysyłka 1 with `Postep`, has none); the place of its version in the order of versions (`outbox.py` `Version`: the rank, then the moment and number from the file name): the order of the wysyłki, and with `StarszaPozniej` wysyłka 2 is older than 1. The mark of a part and the label of a file in the Archiwum carry the wysyłka, and the queue compares their `Nr` (`_settle`, `_put`, `_deliver_archive`, `_superseded`) |
| `Proc(q)` | the process of queue `q`: each its own with `DwaProcesy`, otherwise both in one (a shared `_PASSES`) |
| `Rodzaje` | the kinds of writes whose effect shows only on a list (`keyed_box.py`: the label of an issue, `_archive_kind`); uploads and removals of an Archiwum file (`_file_kind`) the model does not hold, because the list of files has no lag here |
| `Swiezo`, `Init` | `KnownIssue`: the issue of an Uwaga taty to which the link to the Logi goes already exists (number 1). With `OpoznienieListy` (#915) the queue has just opened that Uwaga with an answer (`case_delivery.py` `_CaseDelivery.delivered`), so GitHub's list may not show it yet, and the file of writes has its effect or, when the write of the answer raised `OSError` (`keyed_box.py` `_settled`), a write without an answer |
| `Cialo(w)` | `Post.opening`: the body of a new issue is the header or part 1, and the other parts are comments |
| `Widoczne(q, zna)`, `Najnowsze(q, zna)` | `keyed_box.py` `KeyedBox.labelled_issues` of queue `q`: the issues of GitHub's list and the effects from the file of writes (`pamiec`, `_Notes.opened`), shared by every `KeyedBox`, also of a new process, and without a read of the file (`zna` false) the list alone; `report_box.py` `newest_with_line` on that list: the newest issue with the line, 0 for `None` |
| `Moj(e, w)`, `Swoje(w, q, zna)` | the mark `e` belongs to wysyłka `w` (`outbox.py` `_marks`: the same label and `run_id`, any version); `_deliver_new_issue`: the newest issue on the list of queue `q` whose body has the mark of `w`, 0 for none |
| `OdczytyZapisow` | `keyed_box.py` `_notes` at a list (`labelled_issues`, `archive`): the read of the file of writes succeeds or raises `OSError` (one of `bledyPliku`); without `OpoznienieListy` the lists show every write at once, so the file changes nothing |
| `Ma(i, w, k)`, `WIssue(w)`, `Pliki(w)`, `WArchiwum(w)`, `Dostarczona(w)` | part `k` of wysyłka `w` is in issue `i` in this version or newer (a Diagnoza corrected it); each part of `w` is in one issue, in the body or a comment, in this version or newer; the files of `w` in the Archiwum (each version), and whether one is in this version or newer; `w` is in the Skrzynka whole: each part in an issue and the file in the Archiwum |
| `Zastapiona(w)`, `BezStarszych(w)`, `Miejsca(w, k)` | `w` has a newer version in the queue (a Diagnoza), so its file may disappear without its parts, because the Skrzynka is owed the newer one; no comment of `w` (a part `k > 0`; the queue does not change the header in the issue's body) is in a version older than `w`; the places in the Skrzynka where part `k` of `w` is, in any version |
| `Odrzucona(w)`, `Pamieta(w)` | the file waits for the next start of Centrum because the Skrzynka rejected its content (`Rejected`, `_rejected`), or it was sent and only its removal failed (`_undeleted`) |
| `Budz(q)` | `Outbox.send_in_background`: a running thread gets `_again`; otherwise `_draining` and a new thread |
| `Stop(q, opis)`, `Odrzuc(q, w, opis)` | `_waiting` gives „stop” (no network, a refused key, no key): `_stopped_on` and return from `_send_all`; „next” (a refused content): the file goes to `_rejected` until the next start, and the pass goes on |
| `Dopisz(ks)` | each part of the list as a new comment: the comments of a new issue, and of a found one before its comments are read |
| `PoArchiwum(q, dalej, opis)`, `Czeka(q, opis)` | `_deliver_to_period`: with a file to the Archiwum the step of the Archiwum first (`_deliver_archive`), then the next step; `_deliver_archive` gives `ArchiveWaits` (a refused permission or content): the parts go with the note (`_note`), and the queue file gets the marker of the parts (`Znacznik`) |
| `Swieze(q, r)`, `Wstrzymane(q, r)`, `Zapis(q, r, zna)` | a write of kind `r` in the file is fresh and without an answer (the queue does not matter: the file is shared); `keyed_box.py` `_held`: the moment of the last list (`odczyt`) decides, and a write without an answer after it always holds; `_noted` before the request and `_settled` after it: without an answer (`zna` false) the write of kind `r` stays in the file and other queues have a list from before it, while an answer with an effect replaces it in the file with the effect (`pamiec`, `pamiecWydania`), so it holds nobody. The write and the answer are one step, because they go in one pass under the folder lock (`_folder_lock`); without it a second queue would open after its list from before the write (JednoIssue). Without `OpoznienieListy` the lists show every write at once, so the hold only delays, and the model leaves it out |
| `PlikiPrzejscia` | `sorted(glob("*.json"))` in `_send_all`: the queue files by name, without `*.json.tmp` and `przejscie.lock` |
| `Nowszy(q, w)`, `NowszyDalej(q, w)` | `outbox.py` `_superseded`: the pass read at its start (`_read`) a file of a newer version of the same wysyłka (the same target and `run_id`: `Id`), outside `_rejected` and `_undeleted`, also a file before `w` on the list (a stand-in version after the Logi with the result); the file of the newer version is further on the list, so the pass has not handled it, and the model decides its read now |
| `WTresci(i, w, k)`, `Komentarze(i, w, k)`, `Krok(i, w, k)`, `Wycofaj(i, w)`, `Nowsza(i, w)` | what `_settle` does with part `k` of `w` in issue `i` (`outbox.py` `_settle` and `_put`): there, when the mark of this part stands in the issue's body or in the first comment with it in this version or newer; correct, when that comment has an older version; otherwise add. `_settle` gives `_RETIRED` to the comment of a part that version `w` does not have (nor the body) in an older version (`part not in wanted and seen < version`), after the parts of this version; the mark of `w` in a newer version in the body or a comment of issue `i` (`newest > version`) |
| `PlikLogow(q, czeka)` | `outbox.py` `_deliver_logs_file`: the Logs file after the Wzorce, from the same list of Archiwum files (the list of files has no lag here, so it is the state of the Archiwum). A file of this wysyłka in this version or newer stays (`_asset_version` from the label), a file of an older version gives way (`remove`), and without a file `upload`. `czeka`: a Wzorzec waited in this step (`template_waits`), so a Logs file that is there gives `ArchiveWaits(logs=False)` instead of `InArchive` |
| `Zabij(S)` | the memory of the queues of `S` after their process ends; an HTTP request during `post` dies with it: the `.json.tmp` file stays and the wysyłka is lost (`post` did not return True), and a file already replaced waits for `resume`. The end of a process closes its files, and with them the system releases the folder lock; the effects of writes are in `OPENING_FILE`, so they stay, and only the moment of the thread's list is lost. An interruption between the Skrzynka's acceptance of a part and the delivery marker leaves the file without a marker, and the next try finds that part by the mark of the wysyłka (`_settle`), so no cause goes to `slady` |
| `Sprawiedliwosc` | running code takes its next step, the wake comes, an HTTP request finishes `post`, an old process ends at some point, and Dad starts Centrum when nothing runs; the computer switches off and the Skrzynka fails finitely many times (`Max…`), so after the last failure the steps that succeed remain |
| `Po(wybaczone)`, `ZbieganiePozaZnanymi` | a cause of a known finding of the promise already happened; `slady` only grows, so `<>Po(…)` is a run in which such a cause happened at some point |

Each constant is a way to fail or a bound of a configuration (`stale` in `model/konfiguracje.json`):

| Constant | Meaning |
| --- | --- |
| `Cel` | the target of the wysyłka (`outbox.py` `Target`): `okres` (`PeriodThread`), `nowe` (`NewIssue`), `zgloszenie` (`OpenIssue`), `znane` (`KnownIssue`: the issue of a known number exists; with `OpoznienieListy` the queue just opened it, and GitHub's list may not show it yet) |
| `Czesci`, `CzesciNowszej` | the parts of one wysyłka (`Post.parts`; a text over `COMMENT_LIMIT` is split when its `Post` is made); the parts of the newer version (wysyłka 2 with `Diagnoza`), since a Diagnoza changes the length of the Logi |
| `Naglowek` | `Post.header`: the body of a new issue is the header, and each part goes as a comment (the Logi) |
| `Wysylek` | wysyłki to the same target, one after another (the same identifying line) |
| `MaxBrakSieci` | `Unreachable`, `Refused` or `NoKey` before the effect: `_waiting` gives „stop” |
| `MaxZgubionych` | `Unreachable` after the effect: the Skrzynka took the write and the answer was lost (a POST past `_TIMEOUT_S`) |
| `MaxOdmowTresci` | `Rejected` (400, 413 and 422 in `report_box._REJECTIONS`): `_waiting` gives „next” |
| `MaxBledowPliku` | `OSError` from the disk: a write of the temporary file, the replace, a removal (`atomic_file`, `_remove`); with `OpoznienieListy` also a write and a read of the file of writes of `KeyedBox` (`_noted`, `_settled`, `_notes`) |
| `AwariaOdczytu` | `OSError` also from a read of a queue file (`outbox.py` `_queued`) |
| `MaxWylaczen` | the computer switches off or the process dies at any step |
| `Kolejki`, `DwaProcesy` | 1 or 2: two queues of one folder (`_claimed`, `_released`); the second queue in a new process, after the old one closed its port while its thread still sends |
| `Diagnoza` | wysyłka 2 is a newer version of wysyłka 1 (the same `run_id` and label: the Logi after a Diagnoza, `run_comments.py` `RunComments.diagnosed`), not a separate wysyłka |
| `Archiwum`, `Wzorzec` | the wysyłka carries a file to the Archiwum okresu (`outbox.py` `Post.archive`, `ArchiveFile`: the Logi Uruchomienia); the file also carries a Wzorzec (`ArchiveFile.templates`, `template_archive.ArchivedTemplate`), the same in each wysyłka, because its name in the Archiwum is a digest of its bytes (`wzorzec-<SHA-256>.xlsx`) |
| `MaxOdmowArchiwum` | `Refused` or `Rejected` from a step of the Archiwum (a Token without the permission to the repository's contents): `ArchiveWaits` |
| `PusteRepo` | the repository of the Skrzynka has no commit during the whole run: GitHub answers 409 „Git Repository is empty.” to each opening of the Archiwum (`report_box.py` `GitHubReportBox.open_archive`: `Rejected`) |
| `Postep` | wysyłka 1 is the progress of a Wycena w efenix, an older version of the Logi of wysyłka 2 without a file to the Archiwum (`comment_versions.py` `ProgressVersion`, `run_comments.py` `RunComments._progress`) |
| `StarszaPozniej` | wysyłka 2 is the stand-in version of a start of Centrum (`Rank.STAND_IN`: the Logi from the file), older than the Logi with the result of wysyłka 1 (`Rank.OWN`), although its queue file came later (#910) |
| `OpoznienieListy` | GitHub's lists (`labelled_issues`, `archive`) show a new issue and the Archiwum after a few seconds |
| `Wybaczone…` | the causes of known findings that the `…PozaZnanymi` variant of each promise skips (the other promises of the run are checked whole); the script sets them |

| Variable | Meaning |
| --- | --- |
| `plik`, `tmp`, `zakladanie`, `pamiec`, `pamiecWydania` | Dad's disk, which outlives a switch-off: the queue file `<moment>-<n>-<label>-<run>.json` of wysyłka `w`: `nadejdzie` (`post` has not written it yet), `przepadl` (`post` returned False or died before the replace), `czeka` (no marker), `skomentowany` (`delivered_parts = len(parts)` with `archived` false: it waits only for the Archiwum), `oznaczony` (every part and the file in the Archiwum) or `usuniety`; the wysyłki whose `<name>.json.tmp` lies in the folder (`replace_atomically` cut); the file `keyed_box.py` `OPENING_FILE` by kind (issue, Archiwum): fresh while it has a write without an answer less than `LIST_LAG_S` old, otherwise none (an old write, one with an answer, or none); its effects (`_Notes.opened`), the issues a `KeyedBox` opened with an answer, which each `KeyedBox`, also of a new process, adds to a list that does not show them; `_Notes.archives`, the same for the Archiwum and `archive` |
| `issues`, `archiwum`, `wydania`, `niewidoczne`, `wydanieNiewidoczne`, `falszywe` | the Skrzynka Zgłoszeń (GitHub), which outlives everything: the issues by number, each a key (`L`: the identifying line of the period or the fingerprint of a Zgłoszenie; `N`: an Uwaga taty, without a line; `Z`: an issue of a known number) and its content, the body then the comments, each a mark `<<wysyłka, part>>` (0: the header); the files of the Archiwum okresu (the assets of the Release), each the version of its wysyłka (GitHub keeps no two files of one name, so an upload when the file of the wysyłka is there is `Rejected`); the Releases with the period's tag (Archiwa okresu) the queue opened; the issues GitHub's list (`labelled_issues`) does not show yet; the list of Releases (`archive`) does not show the Archiwum yet; a ghost: GitHub refused a second Archiwum of the tag (422), and the parts went with the note that the file waits |
| `zyje`, `pc`, `draining`, `again`, `armed`, `stopped`, `nieczytany`, `bezBlokady`, `undeleted`, `rejected` | the memory of a process, gone with it: the process of queue `q`, none, running (it has the port and takes HTTP requests) or closed (uvicorn closed the socket and the process still finishes: `_GRACEFUL_SHUTDOWN_S`); the step of the thread `skrzynka-kolejka` of queue `q` (`spi` while it does not run); `Outbox._draining`, `_again`, `_retry_armed`, `_stopped_on is not None`; `Outbox._read_failed` (the pass skipped a file it could not read); `Outbox._locked_out` (the pass found the folder lock held by a queue of another process); `Outbox._undeleted` and `_rejected` (file names) |
| `lista`, `czytane`, `biez`, `nr`, `kom`, `arch`, `po`, `odmowaArch`, `bezZnacznika` | the files of this pass not handled yet (`PlikiPrzejscia`); the files the pass read at its start (the reads in `_send_all`, without `_undeleted` and `_rejected`), from which `_superseded` takes the newest version of each wysyłka; the file the pass sends now; the issue number of this wysyłka (opened or found); the parts to write in order, each to add (`comment`, `_comment_all`), to correct (`edit_comment` in `_put`) or to retire (`edit_comment` with `_RETIRED`); the result of the step of the Archiwum of this wysyłka (`_deliver_archive`): none (not yet, or no file), there (`InArchive`) or waiting (`ArchiveWaits`: the parts go with the note, the queue file `skomentowany`); the step after the Archiwum: open (`_deliver_to_period` without an issue), comment (`_put_all`) or delivered (nothing to write in the issue, or only the file to the Archiwum); `Outbox._archive_refused`: the Archiwum refused in this pass, so `archive_open = False` from then on; the write of the marker failed (`suppress(OSError)` in `_send_all`) |
| `passes`, `blokada`, `zamkniecia`, `odczyt` | `_PASSES[folder]` of a process: free, taken (false) or asked again (true); the queue that holds the system lock of the folder's file `przejscie.lock` (`_folder_lock`; 0: none), which each queue opens on its own and which closing the file and the end of the process release; the times the old process closed its port; `KeyedBox._listed_at` of the thread of queue `q` by kind: the last list came less than `LIST_LAG_S` after a write without an answer from the file (or before it), so `_held` holds openings |
| `nadawca`, `przez`, `zakolejkowane`, `odrzucone` | the HTTP requests that make wysyłki (`Outbox.post`): the step of `post` of wysyłka `w` (waiting, replace, wake, end); the queue whose `post` writes `w`; the wysyłki for which `post` returned True (the file waits on disk); a ghost: the wysyłki whose content the Skrzynka once rejected (`Rejected`) |
| `wzorce`, `wzCzeka`, `podwojny` | the files of the Wzorzec (one name) in the Archiwum okresu (an upload when the Wzorzec is there is `Rejected`); `outbox.py` `_deliver_archive`: `template_waits`, the Archiwum did not take the Wzorzec in this step of the Archiwum; a ghost: the queue removed from the Archiwum the file of the wysyłka in the version it sends or newer, so it would send the file twice (`_deliver_archive` removes only the file of an older version) |
| `sieci`, `zgubione`, `odmowy`, `odmowyArchiwum`, `bledyPliku`, `wylaczenia` | the failures that already happened, the counters of the `Max…` constants |
| `krok`, `slady` | the last step in the code's words, from which the counterexample is told; the causes of known findings that already happened |

The digests in `model/definicje.json` were taken when the checker and the model were last confirmed to describe the
code (`tools/przesun_model.py`); what that confirmation found is in the message of the commit that changed the digests.
To see what changed since:

```bash
git diff $(git log -1 --format=%h -- .agents/skills/verify-kolejka-skrzynki/model/definicje.json) -- src/rozliczenia/centrum/outbox.py src/rozliczenia/centrum/keyed_box.py src/rozliczenia/centrum/report_box.py src/rozliczenia/centrum/atomic_file.py
```

Read each change against the tables above. A change matters when it adds, removes or reorders
a box call, changes what a retry does with an issue it finds, changes how a text carries its mark or how `_settle`
reads one, changes how a file in the Archiwum carries its version or when it is removed and uploaded, changes when the
marker is written or the file removed, changes which failure stops a pass (`_waiting`), or adds a `Target` or a field of
`Post` that goes to the Skrzynka. A new `Target` also needs a scope in `SCOPES` and a branch in `_check` in
`explore_outbox.py`. Changes to the text of a wysyłka, the log lines, the `Listener`, `delivered`, `wait_delivered` and
the addresses file do not matter here. Recompute the digests only after the checker and the model match the code and
both checks and their mutations pass on it.

## Run the checker

```bash
.venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py
```

On Windows use `py -3` instead of `.venv/bin/python`. It takes about 30 to 80 s, depending on the machine.

| Last line | Exit | Meaning |
| --- | --- | --- |
| `KOLEJKA OK` | 0 | Every rule holds in every schedule. |
| `KOLEJKA OK, ZNANE USTALENIA: n, ZAAKCEPTOWANE RYZYKA: m` | 0 | Only the entries of `KNOWN_FINDINGS` and `ACCEPTED_RISKS` (none today), each printed with its shortest counterexample. |
| `KOLEJKA: NOWE NARUSZENIE (n)` | 1 | A rule breaks; read the printed counterexample as „When the check fails” says. |
| `KOLEJKA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding or accepted risk did not show in a scope of its `after`. If a change fixed it, delete its entry. |

## What the checker covers

The scopes, their wysyłki and their bounds are `SCOPES` in `explore_outbox.py`. Measurements behind the bounds that the
script does not record (Maks's Mac): `archiwum` with 2 network failures also passes, 93 960 schedules in 188 s instead of
15 210 in 28 s (2026-11-04); `archiwum-diagnoza` takes 17 086 schedules in 55 s and `archiwum-puste-repo` 5 337 in 16 s
(2026-11-05). Keeping `OPENING_FILE` and the Centrum log in memory took `archiwum-diagnoza` from 91 s to 41 s with the
same 19 874 schedules (#911). A Wzorzec before the file of the Logi in `archiwum` (ADR 0025, „Wzorce w Archiwum Logów
okresu”) gives 29 677 schedules in 62 s (2026-11-18); the other scopes of the Archiwum carry no Wzorzec, because each
box call doubles the schedules of a scope, and the model's `Wzorzec` runs in `archiwum` and `archiwum-lista`.

At a pass boundary the checker takes from the queue only `Outbox.state` (`QueueState`), because the rest of the queue's
memory reaches nothing a scope runs: no scope has a `Listener`, which reads `delivered` and `rejected` (`_first_comments`,
`_rejected_posts`), or content the Skrzynka rejects (`_rejected`); every pass sets `_read_failed` and `_locked_out`
anew, and the wake they arm is `retry_armed`; `_unreadable` and `_archive_logged` only spare the log lines; and
`_sequence` and `_last_moment` only give the name of the next wysyłka, whose version the checker counts as its place
among the scope's wysyłki (`versions`).

Not covered: a key that is missing or refused (`NoKey`, `Refused`: the pass stops, nothing is sent, and `KeyedBox`
keeps a refusal for `REFUSED_KEPT_S`), a step of the Archiwum `Rejected` for its content (it is `ArchiveWaits` like a
refusal, which the scopes of the Archiwum check), the Archiwum of another period, Maks deleting the Archiwum or a file
in it, content the Skrzynka rejects (`Rejected`: the file waits for the next start, and the same content would be
rejected again), Maks closing or deleting an issue (`Gone`, `closed="reuse"`; after Maks closed the issue of a Kontrola
ilości, a delivered file without its delivery marker would open a new issue okresu with the whole Kontrola), a failed
read of a queue file outside `diagnoza-odczyt` and `archiwum-diagnoza` (the model's `odczyt` and `diagnoza` have it), a
later wysyłka posted in the middle of a pass (it arrives only between passes; the model's `Nadaj` has it), a clock that
goes back between two wysyłki (every schedule posts in order with the real clock;
`test_logi_z_diagnoza_po_cofnieciu_zegara_komputera_zmieniaja_komentarz_uruchomienia` checks `Outbox.post`), a
delivered file with its marker that waits for the next start, two queues on one folder (`_claimed`, `_folder_lock`), a
process killed in the middle of `replace_atomically` (it leaves a `.tmp` that `resume` removes), `prepare` holding a
wysyłka back, a queue thread running at the same time as `post` or `wait_delivered` (the checker runs each thread to its
end), the `Listener` (Sprawy taty) and the wysyłki it returns, a lag of the list of an Archiwum's files or of an issue's
comments (neither was measured; the files `KeyedBox` adds after its own writes cover the first in one Centrum), a list
that lags longer than `LIST_LAG_S`, a failed read or write of `OPENING_FILE` (also the held decision `Gone` about a
fresh known issue, #915, which only such a failure reaches; the model's `znane` has it), and more wysyłki or failures
than the bounds. The model checks, on its own abstraction of this code, two queues on one folder, also in two Centrum
processes, a process killed in the middle of `replace_atomically`, a queue thread running at the same time as `post`,
refused content and two file errors in a row.

Known findings and accepted risks: none. The former finding `przejecie` (a retried Zgłoszenie in several parts lost its
later parts) is gone since a Zgłoszenie always has one part, and the former risk of a second issue of an Uwaga taty
after the connection broke (ADR 0015 before its note of #840) is gone since the retry finds the issue by the mark in its
body (`_deliver_new_issue`). A risk the user accepts gets an ADR and an entry in `ACCEPTED_RISKS` that names it.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a box call in the code's words (`open_issue`,
`comment(#n, część k/n)`, `edit_comment(#n, część k/n)`, `labelled_issues`, `comments(#n)`), what the Skrzynka did, a
file step of `_send_all`, or a pass or restart. Then sort it:

- **Real bug**: every step can happen at Dad's (a network that drops, a POST whose answer is lost, Windows holding a
  file, Centrum closed), and the end state breaks the rule. Report it with the story. Fix the product code only if the
  user asks. If the user accepts the risk instead, record the decision in an ADR and add an entry to `ACCEPTED_RISKS`
  naming it.
- **Modeling error**: a step the code cannot take or GitHub would not do, for example `MemoryBox` returning an issue
  with another label, or a failure at a step the table does not list. Fix `MemoryBox`, `Scheduler` or `_intercepted`,
  and say what was wrong.
- **BEZ_WYJATKU**: a pass raised. The printed type and message name the exception; find where `_send_all` lets it out.

Never shrink a bound, a scope or a rule to make a real counterexample go away.

## After changing the checker or an intended change to the queue

`.agents/skills/verify-kolejka-skrzynki/scripts/check_outbox_mutations.py` proves the checker can still fail: it must
end with `MUTACJE OK`. No mutation removes the delivery marker or writes it after the removal: since #840 neither breaks
a rule here, because a retry finds every part by its mark. The stand-in version of a lower rank posted after the Logi
with the result is out of the checker's scopes; the model's configuration `starsza` and the tests of
`tests/test_centrum_logi_uruchomienia.py` (#910) check it.

## The TLA+ model

`model/KolejkaSkrzynki.tla` is a hand-written TLA+ model of the same queue, which TLC checks in every order of steps and
failures. It describes the code only while you keep the two in step. It adds what the checker cannot run: threads that
interleave (a wysyłka posted during a pass, the `RETRY_S` wake, a second queue of one folder, a second Centrum process),
the temporary file and the rename of `replace_atomically` as separate failure points, a switch-off at every step,
refused content (`Rejected`), a queue file that cannot be read, two file errors in a row, a newer version of a wysyłka
also sent before the older one, and GitHub's lists that catch up with a new issue or Archiwum at any step
(`OpoznienieListy`), also between the list and the write.

Its promises, whose harm is that of JEDNO_ISSUE, DOKLADNIE_RAZ and KOLEJKA_PUSTA, and for `CzesciWKolejnosci` a
Kontrola ilości or an Uwaga taty in several parts that does not read in order:

- **JednoIssue**: one issue per period, per problem of a Zgłoszenie and per Uwaga taty; an Uwaga taty (`NewIssue`) has
  one issue because the next try finds the issue of an interrupted one by the mark in its body.
- **DokladnieRaz**: a file disappears from the queue, is lost or gets its marker only once the Skrzynka has each of its
  parts and its file in the Archiwum in its version or newer (the file of a version that a newer one in the queue
  replaced may disappear without them), and the marker of the parts once it has each part; no part of any wysyłka is
  in the Skrzynka twice (nor in two versions), the Archiwum has at most one file of a wysyłka, the queue never sends a
  file to the Archiwum twice, and after it sent a version the Skrzynka has no text or file of an older one.
- **CzesciWKolejnosci**: part k > 1 in an issue has part k-1 of the same wysyłka before it, so an issue reads in order.
- **Zbieganie**: once failures stop, no file is without a marker unless the Skrzynka rejected its content or it was sent
  and only its removal failed. A file that disappeared or has a marker while the Skrzynka lacks its parts already breaks
  DokladnieRaz, so Zbieganie looks only at files without a marker, and each finding breaks one promise. In a repository
  without a commit (`PusteRepo`) the file to the Archiwum never arrives, so a file with the marker of the parts stays
  (each part is in the Skrzynka), but none without it: a refusal of the Archiwum stops only the file, not the parts of
  this wysyłka or of later ones.

### Bring the model in line, then run

1. Read the diff of the covered files since their digests (the `git diff` above; the drift line names each changed
   file and definition) and find each hunk's step in the checker's table and in the tables of the model.
2. Change the matching action so that one action stays one indivisible step of the code, and write the code's names in
   its row of the model's table, not in a comment: the model has none, and a new action of `Next`, constant or variable
   gets its own row or its place in one, and a new branch or definition gets one when it models code. TLA+ strings must
   be ASCII.
3. A new way to fail gets a constant with its row, a branch guarded by it, and a value in `stale` of every configuration in
   `model/konfiguracje.json`.
4. Before you trust a pass on a new path, break that path in the model and see the check fail; add the break to
   `check_model_kolejki_mutations.py` with the code it mirrors. A new guard in the model needs a counterpart in the code;
   name it in the row of its action.
5. Run `tools/przesun_model.py verify-kolejka-skrzynki` only when the checker and the tables of the model match the code,
   and put what changed in the model and the definitions it prints in the commit message.

Run one configuration while you work:

```bash
.venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py --config okres
```

On Windows use `py -3`. All configurations take about 45 s on Maks's Mac (2026-11-04) and about 107 s under load with
the lagging lists (2026-11-05). The verdicts are those of every skill with a TLA+ model (`tools/lib/model_tlc.py`):

| Last line | Exit | Meaning |
| --- | --- | --- |
| `MODEL KOLEJKI OK` | 0 | Every promise holds in every configuration. |
| `MODEL KOLEJKI OK, ZNANE ZNALEZISKA: n` | 0 | Only the known findings in `znane` break a promise (none today). |
| `MODEL KOLEJKI: NOWE NARUSZENIE (n)` | 1 | Read the counterexample as „Real bug or modeling error?” says. |
| `MODEL KOLEJKI: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding no longer happens. If a change fixed it, remove it from `znane` of its configuration. |
| `MODEL KOLEJKI: BŁĄD MODELU (n)` | 2 | The model, not the code, is broken; nothing is known about the promises. |

`OpoznienieListy` stays out of `nowe`, `zgloszenie` and `archiwum`: with the lag they took 29 s, 17 s and over 600 s
on Maks's Mac under load (2026-11-05), and the checker's `*-lista` scopes run those targets.

### Real bug or modeling error?

Read the counterexample as steps in the code's words and check each step against the comment of its action. If every
step can happen in the code in that order, and the end state (`pliki kolejki`, `Skrzynka`) is what the disk and GitHub
would hold, it is a real bug: report it with the counterexample, and change product code only if the user asks. If a
step cannot happen in the code, fix the action and cite the line that proves it. `TypeOK` breaking is always a modeling
error. Never shrink a bound, add a guard without a counterpart in the code, or widen `Wybaczone` to make a real
counterexample go away.

### What the model leaves out

Checked only with the bounds in the configurations. Assumed and not checked:

- A second Centrum with the port while another has it: `tool_files.py` `listen_locally` excludes it, and `Start` takes
  it as given.
- A lock file that cannot be opened (no queue folder yet): `_folder_lock` lets the pass go without the lock. The
  model's folder always exists.
- `_claimed` guards no promise of the model: the folder lock keeps two queues of one process apart too, because each
  opens the lock file on its own. `_claimed` only spares the second queue the `RETRY_S` wait, time the model does not
  have; `test_przejscie_pominiete_przez_druga_kolejke_robi_pierwsza_po_swoim` checks that hand-over.
- Every box call returns (`Watek` is weakly fair). A call that hangs holds the folder lock only until its process ends:
  `KoniecProcesu` does not wait for the queue thread, as `serve` does not.
- `Nadaj` starts a `post` only in a process with the port. An HTTP request that the old Centrum received before it
  closed its socket may call `post` only after the new Centrum's `resume`; when the old process ends before its queue
  sends that file, the file waits for the new Centrum's next wysyłka or start. Removing `*.tmp` in `resume` only under
  the folder lock would let a `post` that the old Centrum began before the new one started end the same way inside the
  model (TLC's counterexample in `dwa-procesy`, `Zbieganie`), so `resume` removes every `*.tmp` as before, and such a
  `post` returns `False`.
- GitHub's lists catch up within `LIST_LAG_S` (30 s) of a write's moment, including the request itself (up to
  `report_box._TIMEOUT_S`, 15 s): measured 3.0–6.8 s for issues and 2.8 s for Releases (`verify-github-skrzynki`,
  2026-11-05). `Przedawnienie` takes it as given. The list of an Archiwum's files does not lag in the model, so it
  leaves out the hold of uploads and removals (`_file_kind`), which the checker's `archiwum-lista` runs; with the
  Archiwum only through `_Notes.archives` the model shows all its files, as `KeyedBox` shows the uploads in the file.
  The note and the answer of `open_archive` never fail to write the file in the model (`Zaloz` has both), and closed
  issues are not modelled, so neither is the list with closed issues of `labelled_issues`.
- `os.replace` is atomic: a switch-off leaves the old file or the new one.
- Only the Logi Uruchomienia have a newer version (`ASSUME Diagnoza => ...`): `RunComments.diagnosed` and the progress
  of a Wycena w efenix (`RunComments._progress`, then the Logi at its end) are the only callers that queue a wysyłka
  again with the same identifier, in the Centrum process that queued the older one; the Logi of an Urwane Uruchomienie
  or the result without Logi, which replace its progress, come from the next process, as a stand-in version (#910). The
  model's order of the versions is `Nr`: the order of the wysyłki, which `Outbox.post` keeps also after the clock went
  back within one process, except `StarszaPozniej`, where the later wysyłka is the older version, as a stand-in version
  after the Logi with the result. Which rank each sender picks is the model's of `verify-urwane-uruchomienie`. Only the
  configuration `diagnoza` has versions with different numbers of parts, and there the newer one is shorter; a longer
  newer version, whose extra parts are new comments, is not checked.
- The queue never edits an issue body, so the model never changes `tresc[1]`.
- One Stanowisko per Skrzynka: `KeyedBox._listed` drops every listed issue whose title has another Stanowisko's prefix
  (`box_prefix.owns`), and the issues it adds after its own writes are its own, so the issues of the other Stanowisko
  never reach the queue and the model's Skrzynka holds only this Stanowisko's. `test_logi_i_kontrola_ilosci_obu_stanowisk_z_jednego_okresu_ida_do_osobnych_issue_i_archiwow`
  in `tests/test_centrum_logi_w_skrzynce.py` runs two Stanowiska on one Skrzynka.
- NAJNOWSZA_WERSJA is the checker's: the model checks that marking and removing a superseded file loses nothing
  (DokladnieRaz, Zbieganie), not that the older version stays out of the Skrzynka. `postep` has one progress before the
  Logi (`Wysylek = 2`); the checker's scope `postep` has two.
- The Archiwum: one per configuration (one period); every file in it is whole (an upload that breaks off, which
  `_deliver_archive` removes by `uploaded`, is the checker's); `Refused` and `Rejected` of a step are one bounded
  failure (`MaxOdmowArchiwum`), and `Unreachable` of a step is a network failure; a second Archiwum of one tag, which
  GitHub would reject, counts in `wydania` instead. Only configurations with `Archiwum` send a file, and their wysyłki
  have one part. A repository without a commit (`PusteRepo`) lasts the whole behaviour: Maks adding the first commit is
  not modelled, and what GitHub answers is the model's word for the reading of `GitHubReportBox.open_archive`, which the
  checker runs for real.
- More than 1 000 comments of an issue: `GitHubReportBox.comments` reads at most ten pages, and a mark after them is
  not seen.
- `Refused`, `NoKey` and `Unreachable` are one failure (`Stop`); the refusal memory of `KeyedBox` (`REFUSED_KEPT_S`)
  is not modelled.
- Not modelled: Maks deleting a known issue (the model's `Gone` is only the wrong decision about a fresh issue, which
  breaks DokladnieRaz), closed issues (`closed="new_issue"` or `"reuse"`), the `Listener` (`prepare`, `delivered` and
  `rejected`), the addresses file, more than 1 000 issues of a label, and Python exceptions (BEZ_WYJATKU stays with the
  checker).
- No promise looks at `.tmp` files, so the model does not check that `resume` removes them.
- Guards without a counterpart in the code, which only bound the run: one port closing per run (`zamkniecia < 1`), a
  second queue of one process only while the first runs (no code in `src/` makes two; a restart in one process would),
  a wysyłka that starts its `post` only after the one before it started (its name, from the moment and `_sequence`,
  sorts after it), and `Port`: in one process with two queues (`dwie-kolejki`) every `post` goes to the first. Not
  checked through it: a `post` whose `send_in_background` wakes the second queue while the first sleeps. With two
  processes only one has the port at a time, so there `Port` is no choice.

### After changing the model

`.agents/skills/verify-kolejka-skrzynki/scripts/check_model_kolejki_mutations.py` proves the model can still fail: each
mutation removes from the model one guard or step whose code it names, and must end with
`MODEL KOLEJKI: NOWE NARUSZENIE`.
