---
name: verify-kolejka-skrzynki
description: Exhaustively check that the Kolejka Skrzynki Zgłoszeń (`Outbox` in `src/rozliczenia/centrum/outbox.py`) delivers every part of every wysyłka (Zgłoszenie, Kontrola ilości, Logi Uruchomienia, Uwaga taty) at least once, keeps one issue per problem and per period, and empties the queue, under every order of network failures, answers lost after the Skrzynka acted, file errors and a killed Centrum. Use when a change touches `_deliver*`, `_comment_all`, `_waiting`, `Outbox._drain`, `_send_all`, `_remove`, `resume`, the folder lock (`_folder_lock`) or the delivery marker in `outbox.py`, the box calls in `keyed_box.py` or `newest_with_line` in `report_box.py`, `replace_atomically` in `atomic_file.py`, adds a new `Target`, or when `explore_outbox.py` or `sprawdz_model_kolejki.py` fails. A TLA+ model of the same queue (TLC) adds the interleavings the checker leaves out (a wysyłka posted during a pass, the `RETRY_S` wake, two queues of one folder in `_claimed` and in the folder lock, a second Centrum whose port the old one already released, and a switch-off at the temporary file and at the rename).
pilnuje:
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/keyed_box.py
  - src/rozliczenia/centrum/report_box.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/server.py
  - .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
ci: .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_kolejke.py
ci-czesci: 2
---

# Verify Kolejka Skrzynki Zgłoszeń

## What CI runs and what stays local

CI runs `sprawdz_kolejke.py` (the `ci:` key) in Mutation checks whenever a change touches this skill:
it runs the checker of the real code (`explore_outbox.py`) and the TLA+ model (`sprawdz_model_kolejki.py`, TLC,
as the `ci:` of `verify-aktualizacja-narzedzia` does), each to its end. Its units (`UNITS` in
`sprawdz_kolejke.py`) are the scope `watek-okresu`, the other three scopes, and the model; CI runs them in up to
`ci-czesci` parts (`MUTACJE_CZESC=k/n`, consecutive units per part). `watek-okresu` alone takes about as long
as the other two units together (in CI about 190 s of 340 s), so with two parts it gets its own, and no part
is longer than it: below that the wall of the job does not go without splitting that scope's schedules. A
pull request runs the parts of one n, and the night on `main` runs every part of every n up to `ci-czesci`. The model unit
fails with `MODEL KOLEJKI: ROZJAZD MODELU Z KODEM` when covered code changed since the Sync commit,
but it cannot tell whether a change to the model is right. `check_outbox_mutations.py` and
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

- **WSZYSTKIE_CZESCI**: once the Skrzynka answers again, every part of every
  wysyłka in the queue is in the Skrzynka, in an issue of its target. ADR 0015
  (decision 12) and the docstring of `outbox.py`: „Wysyłka jest co najmniej
  raz”. Harm: Maks never sees the rest of Logi Uruchomienia, a Kontrola ilości
  or a Zgłoszenie, and nobody knows it is missing, because the queue file is
  gone.
- **JEDNO_ISSUE**: one problem has one open Zgłoszenie, one period has one issue
  okresu, and one Uwaga taty opens one issue. Harm: Maks gets the same problem
  in several issues, and the Powiadomienie follows only one of them.
- **KOLEJKA_PUSTA**: once failures stop, no file without its delivery marker
  is left in the queue folder (`config/zgloszenia/kolejka/`): the `RETRY_S`
  wake that `_drain` arms runs the queue again until it is sent. Harm: a
  wysyłka waits until Centrum restarts or something new is sent, after the
  network came back. A delivered file whose removal failed may wait for the
  next start: it has its marker and is never sent again.
- **BEZ_WYJATKU**: no pass of the queue ends in an exception that `_drain` logs
  as `nieoczekiwany-wyjatek` „wysyłka do Skrzynki Zgłoszeń”.

A Zgłoszenie (`ReportIssue`) always has one part, so WSZYSTKIE_CZESCI holds
when a retry takes over the Zgłoszenie it finds by its odcisk line without
comments (`_deliver_report`). Two guards keep it to one part (#724): `Post`
raises `ValueError` for a `ReportIssue` with more
(`test_zgloszenie_w_wiecej_niz_jednej_czesci_to_blad_programu`), and
`reports.py` fits the body into `PART_LIMIT` (`outbox.py`), first by dropping
the first frames of the call trace, then the oldest entries of the Centrum log
(the `bardzo_dlugim` tests in `tests/test_centrum_uchwyt_zgloszenia.py`). The
checker's scope `zgloszenie` and the model's `ASSUME` take one part as given.

## Does the change touch it?

The check runs the real `Outbox` and `KeyedBox`. Each row is one indivisible
step of this code that the checker can fail, lose or kill:

| Step in the checker | Code |
| --- | --- |
| a box read | `keyed_box.py` `KeyedBox.labelled_issues` and `find_issue` (`newest_with_line`), called by `_deliver_report`, `_deliver_to_period`, `_deliver_to_known` in `outbox.py` |
| a box write | `KeyedBox.open_issue` and `comment`, called by `_deliver_new_issue`, `_deliver_report`, `_deliver_to_period`, `_comment_all` |
| the delivery marker | `Outbox._send_all`: `replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))` in `suppress(OSError)` |
| the removal of a queue file | `Outbox._remove` (`path.unlink`, `_undeleted`) |
| a pass of the queue | `Outbox._drain` (`_claimed`, `_folder_lock`, `_send_all`, `_released`), run only when the real `Outbox.send_in_background` starts the queue thread (called by `Outbox.post`, `Outbox.resume` and `Outbox._woken`); the checker replaces only `threading.Thread` in `outbox.py`, which hands it the target, and runs one Centrum at a time, so the pass always gets the folder lock |
| the `RETRY_S` wake | `Outbox._drain`: `self._clock.after(RETRY_S, self._woken)` when `_stopped_on`, `_read_failed` or `_locked_out` is set and no wake is armed; the checker calls an armed wake when nothing else asked for a pass, and a restart drops it with its process |
| a restart of Centrum | a new `Outbox` and `KeyedBox` on the same folder, then `Outbox.resume` |

Covered files: `src/rozliczenia/centrum/outbox.py`,
`src/rozliczenia/centrum/keyed_box.py`, in
`src/rozliczenia/centrum/report_box.py` `newest_with_line`, by which
`KeyedBox.find_issue` finds the issue of a Zgłoszenie or a period, and
`src/rozliczenia/centrum/atomic_file.py` `replace_atomically`, which writes
every queue file and its marker (the model only). The model's `Start`, `Zamknij`
and `KoniecProcesu`, which let an old and a new Centrum process share the queue
folder (configuration `dwa-procesy`), also cover three definitions in files
that Centrum changes often: `lifespan` in `app.py`, `listen_locally` and
`_listen_when_released` in `launcher.py`, and `_GRACEFUL_SHUTDOWN_S`, `serve`
and `_Server` in `server.py` (`DEFINITIONS` in `sprawdz_model_kolejki.py`). Only a change to these definitions, not to the
rest of their files, is drift. Name these three files here without their
`src/…` path in backticks: such a path makes the whole file covered.

**Sync commit: `a27e0695`** (2026-10-31). The checker and the model share it:
at this commit both were confirmed to describe the code above. Since the
previous sync `05430811` only `a27e0695` (#718) changed a covered file:
`Outbox` takes one `Listener` (`prepare`, `delivered`, `rejected`) instead
of `prepare`, `on_delivered` and `on_rejected`, and `_send_all` queues the
wysyłki that `Listener.delivered` returns with `post` at the place where the
old `on_delivered` of the Sprawy taty called `post` itself; `ReportIssue`
carries the fingerprint, its line comes from it, and the queue file keeps the
line as before. No box call, retry, marker, removal or `_waiting` changed and
no `Target` was added, so neither check changed: the checker passes a
listener that changes nothing, and the model leaves the listener out as
before. At `05430811`, since the
previous sync `b23f4180` only `73d7f1ba8` (tools to `tools/ci` and
`tools/lib`) changed a covered file, a comment in `app.py` outside `lifespan`,
and the import path of `sprawdz_kolejke.py`; neither check changed. At
`b23f4180` (#666) a pass of the queue started to hold the system lock of
`przejscie.lock` in the queue folder, `_folder_lock`, and a queue that finds it
held by another Centrum process arms the `RETRY_S` wake. The checker runs one
Centrum at a time and always gets the lock, so #666 changed only the model. Before it, `2900e8c2` (#664
merged with `main` after #665: a queue file that `_queued` cannot read arms
the `RETRY_S` wake, and after a refused comment the queue file keeps the
number of the Uwaga's issue) was the sync of both; the checker never fails a
read and leaves `Rejected` out, so neither fix changed its schedules. Before
them, `6f94edb8` was the sync of both, and since the checker's earlier sync
`8122ab4c` only `15362856` changed a covered file: `Outbox` calls
`on_rejected` after a refused content, which neither the checker nor the
model describes. To see whether they need another look:

```bash
git log --oneline a27e0695..HEAD -- src/rozliczenia/centrum/outbox.py src/rozliczenia/centrum/keyed_box.py src/rozliczenia/centrum/report_box.py src/rozliczenia/centrum/atomic_file.py
```

A change to the three definitions above shows as a `UWAGA:` line of
`sprawdz_model_kolejki.py` (in CI as the drift verdict).
Read each listed commit against this table and the model's table below. A change matters when it adds,
removes or reorders a box call, changes what a retry does with an issue it
finds, changes when the marker is written or the file removed, changes which
failure stops a pass (`_waiting`), or adds a `Target`. A new `Target` also needs
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
repo's Python and takes about 30 to 80 s, depending on the machine. `--scope NAME` runs one scope, and
`--strict` counts known findings and accepted risks as violations too.

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
issues, labels, bodies and comments in memory. Before each step in the table
the checker picks one option:

- a box read: it answers, the network fails (`Unreachable`), or the process dies;
- a box write: it is accepted, the network fails before the Skrzynka sees it,
  the Skrzynka accepts it and the answer is lost (`Unreachable` after the
  effect, as a timed-out POST to GitHub), or the process dies before it;
- the marker or the removal: it works, raises `OSError` (Windows, antivirus or
  OneDrive holding the file), or the process dies before it;
- when files are left and nothing asked for a pass: the `RETRY_S` wake fires,
  if the code armed one, or Centrum restarts. Without an armed wake, the queue
  may also stay as it is until the next start. When the wake or the start does
  not ask for a pass either, the schedule ends there, and the rules judge what
  is left.

Bounds in every scope: at most 2 network failures, 1 lost answer, 1 file error
and 1 killed or restarted Centrum. After the failures run out the queue gets
3 more passes to empty itself. The checker re-runs the code from scratch for
every schedule. A schedule that reaches a pass boundary already explored stops
there: the code is deterministic, and the state decides every future and how
its breaks are judged. The state is the Skrzynka, the queue files, the files
`_remove` could not delete, the faults so far and those left, the passes left
and the exceptions so far. `_state` in `explore_outbox.py` names what it leaves
out and why.

| Scope | Wysyłki |
| --- | --- |
| `zgloszenie` | one Zgłoszenie (`ReportIssue`) in one part, as every Zgłoszenie is |
| `watek-okresu` | two Kontrole ilości to one issue okresu (`PeriodThread`), in two and one part |
| `nowe-issue` | one Uwaga taty (`NewIssue`) in two parts |
| `znane-issue` | a comment in two parts to the existing issue of an Uwaga taty (`KnownIssue`) |

Not covered: a key that is missing or refused (`NoKey`, `Refused`: the pass
stops, nothing is sent, and `KeyedBox` keeps a refusal for `REFUSED_KEPT_S`),
content the Skrzynka rejects (`Rejected`: the file waits for the next start,
and the same content would be rejected again; after a refused comment to the issue
of an Uwaga it opened, the file keeps that issue's number, `Opened`), Maks closing or deleting an
issue (`Gone`, `closed="reuse"`), a part posted twice (after a lost comment
answer or a restart, accepted as at least once and not a rule here), a
delivered file with its marker that waits for the next start, two queues on one folder (`_claimed`,
`_folder_lock`), a process killed in the middle of `replace_atomically` (it leaves a `.tmp` that
`resume` removes), `prepare` holding a wysyłka back, a queue thread running at
the same time as `post` or `wait_delivered` (the checker runs each thread to its
end), the `Listener` (Sprawy taty) and the wysyłki it returns, and
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

1. **`nowe-issue`, JEDNO_ISSUE: a second issue of an Uwaga taty after the
   connection broke.** The Skrzynka opens the issue, then the answer is lost or
   a comment fails, and the next pass opens a second issue with the whole Uwaga.
   ADR 0015 accepts it: „Wysyłka jest co najmniej raz: zerwane połączenie po
   utworzeniu issue może dać drugie issue”. The docstring of `outbox.py` accepts
   the same after a process killed after the Skrzynka took the wysyłka and
   before its marker was on disk. A `NewIssue` has no line to find its issue by.

   The risk excuses JEDNO_ISSUE only after those faults
   (`_connection_broke_after_issue`): a lost answer to `open_issue`, any fault
   at a `comment`, or a process killed at a `comment`, at the marker, or at the
   removal after the marker failed. A second issue after any other schedule is a
   new violation. That is how the check holds the delivery marker to its
   promise: a file whose marker is on disk is never sent again, also when
   `_remove` could not delete it, or the process died while removing it.

An accepted risk lives in `ACCEPTED_RISKS` in `explore_outbox.py` with the
decision it rests on and the faults after which it is accepted.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a box call
in the code's words (`open_issue`, `comment(#n, część k/n)`, `labelled_issues`),
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
with `MUTACJE OK`. Each of these gives `KOLEJKA: NOWE NARUSZENIE`:

- a failed comment skipped;
- a found issue okresu missing part 1;
- an issue okresu opened without looking for it;
- a known issue missing part 1;
- a network failure that skips the file instead of stopping the pass;
- an Uwaga taty that opens two issues;
- no delivery marker;
- no `RETRY_S` wake after a pass that stopped;
- the queue file removed before its marker is written;
- a `RETRY_S` wake that does not ask for a pass (`_woken`);
- a start that does not ask for a pass (`resume`);
- a new wysyłka that does not ask for a pass (`post`);
- a pass that does not clear `_draining`, so later requests only set `_again`;
- `send_in_background` that never starts the queue thread.

The Uwaga, marker and removal mutations break the same rule as an accepted
risk, in a schedule it does not excuse. A mutation reported as `NIEAKTUALNA` no longer
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
that cannot be read, and two file errors in a row.

### The model's promise

- **JednoIssue**: one period and one problem of a Zgłoszenie have one issue,
  a comment to a known issue opens none, and one Uwaga taty has one issue,
  except after the risk ADR 0015 and the docstring of `outbox.py` accept
  (below). Harm as JEDNO_ISSUE.
- **WszystkieCzesci**: a queue file disappears or gets its delivery marker
  only when every part of it is in the Skrzynka. Harm: a wysyłka is lost and
  nobody knows, because its file is gone.
- **CzesciWKolejnosci**: in every issue, part k > 1 of a wysyłka has part
  k-1 of the same wysyłka before it, so the issue reads in order. A repeated
  part (after a lost answer or a restart) is allowed. Harm: Logi Uruchomienia
  whose JSON blocks do not join into the file.
- **Zbieganie** (liveness): once failures stop, no file without its marker
  is left of a wysyłka that `post` wrote to the queue, except a file whose
  content the Skrzynka refused (`Rejected`, waits for the next start) or a
  sent file `_remove` could not delete (`_undeleted`, every part in the
  Skrzynka). A file that was deleted, lost after `post` accepted it, or got
  its marker without every part breaks WszystkieCzesci, so Zbieganie looks only at files without a marker,
  and every known finding breaks one promise. Harm as KOLEJKA_PUSTA.

A second issue of an Uwaga taty is possible, and nothing in the code detects
it: a `NewIssue` has no line to find its issue by. JednoIssue accepts it after
the causes ADR 0015 („zerwane połączenie po utworzeniu issue może dać drugie
issue”) and the docstring of `outbox.py` („Przerwanie między wysłaniem a
znacznikiem powtarza wysyłkę”) name, each recorded in `slady` where it
happens: a lost answer to `open_issue`, a network failure or a lost answer
at a `comment`, a switch-off at a `comment`, at the issue number after a
refused comment, at the marker or at `_remove` after the marker failed
(`zerwane_po_zalozeniu`), the end of a Centrum run that leaves a sent file
whose marker and removal both failed (`bez_znacznika`, the comment in
`_send_all`: „bez znacznika chroni już tylko _undeleted, do końca tej pracy
Centrum”), and the end of a Centrum run that leaves an Uwaga whose comment
the Skrzynka refused and whose issue number could not be written
(`bez_numeru`, the comment in `_send_all`: „chroni wtedy już tylko
_rejected, do końca tej pracy Centrum”). A period and a Zgłoszenie
have their line, so `find_issue` keeps them to one issue in one Centrum
process, also after these causes and with two queues of one folder. A part
posted twice is at least once and nothing detects it either.

### Model action and code

Each action is one indivisible step of the code in `src/rozliczenia/centrum/`.
The comment above each action and branch in the model names the same code.

| Model action | Code |
| --- | --- |
| `Start` | `app.py` `lifespan` → `outbox.py` `Outbox.resume`: unlink every `*.tmp` (also one that the old process still writes: its `post` returns `False`, its marker is lost), then `send_in_background`. Only a process with the port starts (`launcher.py` `listen_locally`); a second queue of one process starts while the first runs |
| `Nadaj` | `outbox.py` `Outbox.post`: the name from the moment and `next(self._sequence)`, `replace_atomically` (`write_text` of `.json.tmp`, then `replace`; `OSError` → `False`, also the `FileNotFoundError` of `replace` when `resume` of a new process removed the `.tmp`), then `send_in_background` |
| `Petla` | `Outbox._drain`: `_claimed` (taken → ask for another pass and skip `_send_all`), then `_folder_lock` without waiting (held by a queue of another process → `_locked_out` and skip `_send_all`), then `_read_failed = False` and `sorted(glob("*.json"))` in `_send_all` |
| `Plik` | `Outbox._send_all` for one file: `_undeleted` → `_remove`, `_rejected` → skip, `_queued` (an `OSError` or a missing file → `_read_failed` and `_skip_unreadable`), `delivered` → `_remove`, else `_deliver` (with the file's issue number, `_deliver_to_known`); the end of the list sets `_stopped_on = None` |
| `Szukaj` | `keyed_box.py` `KeyedBox.labelled_issues` / `find_issue` (`report_box.py` `newest_with_line`) in `_deliver_to_period`, `_deliver_report` (a found Zgłoszenie is `Delivered(found, ())`), `_deliver_to_known` (also for the issue number in the file: the comments of `Post.opening`) |
| `Zaloz` | `KeyedBox.open_issue` in `_deliver_new_issue`, `_deliver_report`, `_deliver_to_period`, with `Post.opening` |
| `Komentuj` | `KeyedBox.comment` in `_comment_all`, one part per step; the first failure ends the wysyłka |
| `Stop`, `Odrzuc` | `_waiting`: `Unreachable`, `Refused`, `NoKey` → `_stopped_on` and `return`; `Rejected` → `_rejected` and the next file |
| `ZapiszNumer`, `ZamienNumer` | `_send_all` after `Opened` (`_deliver_new_issue`: a `Rejected` comment after `open_issue`): the issue number in suppress(OSError), `replace_atomically(path, _queue_text(..., issue=...))` as for the marker, then `Rejected` |
| `Znacznik`, `Zamiana` | `_send_all` after `Delivered`: `_stopped_on = None`, then the marker in `suppress(OSError)`: `atomic_file.py` `replace_atomically` (`write_text` of `.json.tmp`, then `replace`; an `OSError` unlinks the `.tmp`) |
| `Usun` | `Outbox._remove`: `unlink(missing_ok=True)`, an `OSError` adds the name to `_undeleted` |
| `Zwolnij` | `Outbox._drain`: the end of `_folder_lock` (the lock file closed), then `finally` with `_released`; a request of the other queue sets `_again` |
| `Decyzja` | `Outbox._drain` under `_changed`: `_again` → another pass, else `_draining = False` and `clock.after(RETRY_S, _woken)` when `_stopped_on`, `_read_failed` or `_locked_out` is set and no wake is armed |
| `Budzenie` | `Outbox._woken` (`_retry_armed = False`, `send_in_background`), also in a process that already closed its port |
| `Zamknij`, `KoniecProcesu` | `server.py` `serve`: uvicorn closes the socket, waits up to `_GRACEFUL_SHUTDOWN_S` (5 s) for open connections, then the process ends and the daemon queue thread dies with it |
| `Wylacz` | none: the computer switches off or the process dies; the queue folder and the Skrzynka stay |

Ghost variables have no counterpart in the code and serve only the promises:
`zakolejkowane` (`post` returned `True`), `odrzucone` (the Skrzynka answered
`Rejected` for this wysyłka), `bezOchrony` (a sent file whose marker and
removal both failed, or an Uwaga whose issue number could not be written), `slady` (causes of the accepted risk and of the known
findings) and `krok` (the counterexample's words).

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
   tables match the code at the new commit.

Run one configuration while you work:

```bash
.venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py --config okres
```

On Windows use `py -3`. It takes Java and `tla2tools.jar` from
`verify-aktualizacja-narzedzia` (`sprawdz_aktualizacje.py` downloads them
once into its ignored cache, no system Java needed); `TLC_JAVA` and `TLC_JAR`
replace them. All configurations take about 20 to 40 s on Maks's Mac. `--strict`
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
| `zgloszenie` | one Zgłoszenie in 1 part; 2 network failures, 1 lost answer, 2 file errors, 1 switch-off | passes |
| `znane` | a comment in 2 parts to the known issue of an Uwaga; 2 network failures, 1 lost answer, 2 file errors, 1 switch-off | passes |
| `dwie-kolejki` | two queues of one folder in one process, one Kontrola in 2 parts; 1 network failure, 1 file error, 1 switch-off | passes |
| `dwa-procesy` | one Kontrola; the old Centrum closes its port and the new one starts before the old process ends; no other failure | passes |
| `odczyt` | one Kontrola; 1 network failure, 1 read error of the queue file, 1 switch-off | passes |
| `odmowa-tresci` | one Uwaga in 2 parts; 2 refused contents, 1 file error, 1 switch-off | passes |

Every configuration checks `TypeOK`, `JednoIssue`, `WszystkieCzesci`,
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
code, or widen `Wybaczone` or the accepted risk to make a real counterexample
go away.

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
- `labelled_issues` sees an issue right after `open_issue` returned. A list
  that lags behind could let a retry open a second issue okresu or
  Zgłoszenie; the next retry comes `RETRY_S` later.
- `os.replace` is atomic: a switch-off leaves the old file or the new one.
- `Refused`, `NoKey` and `Unreachable` are one failure (`Stop`); the refusal
  memory of `KeyedBox` (`REFUSED_KEPT_S`) is not modelled.
- Not modelled: `Gone` (a known issue Maks deleted), closed issues
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

- JednoIssue: an issue okresu opened without looking for it; a Zgłoszenie
  opened without looking for it; `_claimed` that always lets a queue send
  together with a folder lock that is always free (`dwie-kolejki`), and a pass
  without the folder lock (`dwa-procesy`); an
  Uwaga that opens two issues; no delivery marker; a file in `_undeleted`
  sent again in the same Centrum run; a refused comment after `open_issue`
  that does not write the issue number, and a file with the number that opens
  an issue again (`odmowa-tresci`); and, as a model check without code, the
  accepted risk removed from JednoIssue (the risk is reachable).
- WszystkieCzesci: a failed comment skipped instead of ending the wysyłka; and, in
  the configurations with a refused comment or a read error, a refused
  comment that removes the file instead of `_rejected` (`odmowa-tresci`) and
  an unreadable file removed instead of skipped by `_skip_unreadable`
  (`odczyt`); a `post` that returns True although
  `os.replace` raised OSError (`okres`) or although `resume` of the new
  Centrum removed its `.json.tmp` (`dwa-procesy`).
- CzesciWKolejnosci: comments posted from the last part.
- Zbieganie: a network failure that skips the file to the next start; a pass
  that stops without `_stopped_on`; no `RETRY_S` wake; no `RETRY_S` wake after
  an unreadable file (`_read_failed`, `odczyt`) or after a folder lock held by
  another process (`_locked_out`, `dwa-procesy`); a wake that does not
  ask for a pass (`_woken`); `post` without `send_in_background`; `_again`
  ignored; a pass that does not clear `_draining`; `resume` without
  `send_in_background`.
