---
name: verify-kolejka-skrzynki
description: Exhaustively check, on the real code and in a TLA+ model (TLC), that the Kolejka Skrzynki Zgłoszeń (`Outbox` in `src/rozliczenia/centrum/outbox.py`) delivers every part of every wysyłka and the file of the Logi in the Archiwum Logów okresu exactly once, lets a newer version of a wysyłka replace an older one and an older one that arrives later change nothing, keeps one issue per problem and per period, and empties the queue, under every order of network failures, lost answers, file errors, a killed Centrum and GitHub's lagging lists. Use when `tools/skille_dla_zmiany.py` names it, when a change touches `outbox.py`, the box calls in `keyed_box.py`, `newest_with_line` or `GitHubReportBox` in `report_box.py`, `replace_atomically` in `atomic_file.py`, a definition in its `model/definicje.json`, or adds a new `Target`, or when `explore_outbox.py` or `sprawdz_model_kolejki.py` fails.
pilnuje:
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/keyed_box.py
  - src/rozliczenia/centrum/report_box.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/tool_files.py
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

The checker's rules are stated in the docstring of `scripts/explore_outbox.py`. Their harm, which the docstring does
not state:

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

The header of `model/KolejkaSkrzynki.tla` and the comments of its actions describe how the queue finds what an earlier
attempt already wrote: the mark of a wysyłka in each text, the order of versions (rank, then moment), `_settle`, the
step of the Archiwum before the parts, `_superseded`, and the file of `KeyedBox`'s writes that holds a write while
GitHub's list may not show an earlier one. Read them next to `outbox.py` and `keyed_box.py` before you judge a
counterexample.

What the model's comments leave out:

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
fail, lose or kill; the docstrings of `explore_outbox.py`, `MemoryBox`, `Bounds` and `Scope` say what it may do at each.

| Step in the checker | Code |
| --- | --- |
| a box read | `keyed_box.py` `KeyedBox.labelled_issues` (with `newest_with_line` and the body of the issue found, and the issues `KeyedBox` adds after its own writes), called by `_deliver_open_issue`, `_deliver_to_period` and `_deliver_new_issue` in `outbox.py` and, through `KeyedBox.known_issue`, by `_deliver_to_known`, and `KeyedBox.comments`, called by `_seen` (`_settle`, `_deliver_to_period`) |
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

`model/definicje.json` lists the files the checker covers whole, and the definitions in `app.py`, `launcher.py`,
`tool_files.py` and `server.py` that only the model covers (two Centrum processes sharing the queue folder,
configuration `dwa-procesy`): a change to the rest of those four files is no drift.
Each action of `model/KolejkaSkrzynki.tla` is one indivisible step of the code, and the comment above the action and
each branch names that code.

The digests in `model/definicje.json` were taken when the checker and the model were last confirmed to describe the
code (`tools/przesun_model.py`); what that confirmation found is in the message of the commit that changed the digests.
To see what changed since:

```bash
git diff $(git log -1 --format=%h -- .agents/skills/verify-kolejka-skrzynki/model/definicje.json) -- src/rozliczenia/centrum/outbox.py src/rozliczenia/centrum/keyed_box.py src/rozliczenia/centrum/report_box.py src/rozliczenia/centrum/atomic_file.py
```

Read each change against the table above and the model's comments. A change matters when it adds, removes or reorders
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

On Windows use `py -3` instead of `.venv/bin/python`. It takes about 30 to 80 s, depending on the machine; `--help`
lists `--scope`, `--strict` and `--stop-at-new`.

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
same 19 874 schedules (#911).

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

Its promises (`JednoIssue`, `DokladnieRaz`, `CzesciWKolejnosci`, `Zbieganie`) are stated above each in the model; their
harm is that of JEDNO_ISSUE, DOKLADNIE_RAZ and KOLEJKA_PUSTA, and for `CzesciWKolejnosci` a Kontrola ilości or an Uwaga
taty in several parts that does not read in order.

### Bring the model in line, then run

1. Read the diff of the covered files since their digests (the `git diff` above; the drift line names each changed
   file and definition) and find each hunk's step in the checker's table and in the model's comments.
2. Change the matching action so that one action stays one indivisible step of the code, and keep the comment that
   names the code. TLA+ strings must be ASCII; comments may use Polish letters.
3. A new way to fail gets a constant, a branch guarded by it, and a value in `stale` of every configuration in
   `model/konfiguracje.json`.
4. Before you trust a pass on a new path, break that path in the model and see the check fail; add the break to
   `check_model_kolejki_mutations.py` with the code it mirrors. A new guard in the model needs a counterpart in the code;
   name it in the guard's comment.
5. Run `tools/przesun_model.py verify-kolejka-skrzynki` only when the checker and the model's comments match the code,
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
