---
name: verify-urwane-uruchomienie
description: Model-check with TLA+ (TLC) the trail of a Wycena w efenix that a switched-off Centrum cut short, across the next starts of Centrum, the Dziennik Wyceny in `logs/dzienniki-wyceny/` (`Journal` in `logs_disk.py`, `pricing_journal.py`), the Logi Urwanego Uruchomienia (`RunComments.close_left_behind`, `send_left_behind` and `RecordMaker.interrupted` in `run_comments.py`, `close` in `comment_versions.py`) and their way into the Kolejka wysyłki (`Outbox.post`), next to the progress comment of the Wycena (#846, `RunLogs.progress`). It checks that a journal disappears only after its Logi are the newest version the queue accepted, that the journal of a Wycena that may have sent a progress disappears only after the newest version of its comment the queue accepted is final (the Logi with the result, or a stand-in version from the next start, which is the Logi from the file, the Logi Urwanego Uruchomienia or the result without Logi, #910), that no newer version replaces Logi with a progress or a version without Logi, also after the computer's clock went back (the rank of a version, `outbox.Rank`), that a Wycena with a result never gets Logi Urwanego Uruchomienia, that the Logs file and what goes to the queue have the same characters and passed the guard, that nothing reaches the queue before `Outbox.resume`, and that every order the Wycena changed in efenix is in its Logi, under every order of switch-offs and failed reads and writes. Use when a change touches `JournalAtResult` or `JournalAfterLogs` in `src/rozliczenia/centrum/pricing_journal.py`, `RunComments` or `RecordMaker` in `run_comments.py`, the journal in `logs_disk.py` (`Journal`: its first line through `LogsOnDisk.started`, `progress`, its end entry `end`, `remove`; `_RunEnded`, `_read_journal`, `_remove`, `LogsOnDisk.left_behind`, `remove_journal`), `RunLogs` (also `progress`, `_ended` and `queued`), `RunLog.interrupted`, `guarded`, `guard_logs` or `GuardedLogs` in `run_logs.py`, the versions of the comment of an Uruchomienie in `comment_versions.py` (`post_of`, `rank_of`, `journal_after`, `close`, `Drop`, `ResultWithoutLogs` and the version types), the read and the write of a Logs file (`LogsOnDisk.logs`, `_read_logs`, `_names`, `_NAME`, `LogsOnDisk.write`) in `logs_disk.py`, `Rank`, `Version` or `_superseded` in `outbox.py`, `ProgressComment` in `pricing_progress.py`, `lifespan`, `send_interrupted` or the order of `after_run` in `app.py`, `_Run.work` or `RunHost.after` in `runs.py`, `run_process` in `process_run.py` (the result), the journal calls in `efenix_pricing.py` `save`, or when the check of this skill fails.
pilnuje:
  - src/rozliczenia/centrum/pricing_journal.py
  - src/rozliczenia/centrum/run_logs.py
  - src/rozliczenia/centrum/comment_versions.py
  - src/rozliczenia/centrum/run_comments.py
  - src/rozliczenia/centrum/logs_disk.py
  - src/rozliczenia/centrum/pricing_progress.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/process_run.py
  - .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
---

# Verify Urwane Uruchomienie (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_urwane_uruchomienie.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step. It fails with `URWANE URUCHOMIENIE: ROZJAZD MODELU Z KODEM` when a definition the model describes
(`model/definicje.json`) changed since the Sync commit, but it cannot tell whether your change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_model_urwanego_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_urwane_uruchomienie.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line”: read the diff against the table,
change the model, break the new path in it, replay each new counterexample on the code, and move the Sync commit.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

Wycena w efenix runs up to an hour and a half, and the Logi Uruchomienia exist only at its end. When Centrum switches
off in the middle (power cut, a closed console, a killed process), the only trace of what the tool already changed in
efenix is the Dziennik Wyceny w efenix, one file per Uruchomienie. The next start of Centrum turns it into Logi Urwanego
Uruchomienia and sends them to Maks through the Kolejka wysyłki. During the Wycena its comment of the Uruchomienie in the
Skrzynka shows the progress from the journal (#846), a version of its Logi of the lowest rank, so the journal is also
the trace of a comment that may still say „Uruchomienie trwa”, and the Logi with the result or a stand-in version from
the next start turn it into the summary. Every version of one wysyłka carries a rank that its sender picks
(`outbox.Rank`, #910), and the queue compares the rank first and the moment from the file name only within one rank:
the progress (`DRAFT`) < the stand-in version the start sends from the journal (`STAND_IN`: the Logi from the file,
the Logi Urwanego Uruchomienia or the result without Logi, `ResultWithoutLogs`) < the Logi of the Uruchomienie's own
Centrum work (`OWN`: with the result, with the Diagnoza). The docstrings of `logs_disk.py`, `pricing_journal.py`,
`run_comments.py`, `pricing_progress.py` and `outbox.py` promise, and the model checks over every order of steps:

- **DziennikPoKolejce**: a journal of an Urwane Uruchomienie (it has its first line and the Wycena did not reach its
  result) disappears only after its Logi are the newest version that `Outbox.post` accepted, so they reach the
  Skrzynka. With **Zbieganie** this is „wysyłka co najmniej raz”. Harm: Maks never learns that a Wycena stopped
  half-way and which order was in progress in efenix (D2 of #875: after the clock went back the progress was newer and
  the queue dropped the Logi).
- **BezUrwanychPoWyniku**: Logi Urwanego Uruchomienia are made only for a Wycena that did not reach its result
  (`run_process` returned with a result, whether or not its Historia row was written); the journal of a Wycena with a
  result is removed, because it says so itself: „koniec Uruchomienia” (`_RunEnded`) is on the disk before its Logi with
  the result. Harm: Maks reads „Centrum zamknęło się w trakcie” about a Wycena that
  finished, and in the Skrzynka these Logi replace the Logi with the result (same `run_id` and label, newer version).
- **TeSameZnaki**: the Logi go to the queue with the same characters as the Logs file on Dad's disk. Harm: the file in
  the Archiwum Logów okresu and the file at Dad's differ, so a replay from either (#847) sees another Uruchomienie.
- **PrzezStraznika**: the Logi go to the queue only after the guard of the data rule (`guard_logs` in
  `comment_versions.close`, ADR 0025).
  Harm: a phone number or a street from an efenix page leaves Dad's computer.
- **NicPrzedWznowieniem**: nothing goes to the queue in a Centrum work before its `Outbox.resume`. This is the
  precondition the model of `verify-kolejka-skrzynki` assumes for every `post`.
- **ZaczeteWLogach**: every order the Urwana Wycena changed in efenix is in its Logi, as finished or as the order begun
  without a result (`interruption`). Harm: Maks does not know which order may be half-priced in efenix.
- **WersjaKoncowa**: a Wycena that may have sent a progress (its first line is on the disk without `_header`, so
  `Journal.progress` gives one) has a journal, and the journal disappears only after the newest version of the
  comment of its Uruchomienie that `Outbox.post` accepted is final (the Logi with the result, the Logi Urwanego
  Uruchomienia or the result without Logi). With **Zbieganie** every Wycena that sent a progress has its summary in the
  Skrzynka after the next start. Harm: Maks reads „Wynik: jeszcze nie ma, Uruchomienie trwa” forever about a Wycena that
  ended or was cut (W2 of #875, #910).
- **LogiZostaja**: once the newest version of the comment of an Uruchomienie the queue accepted has Logi (with the
  result or of an Urwane Uruchomienie), no newer version replaces them with a progress or a version without Logi, and
  Logi with the result also not with Logi Urwanego Uruchomienia. Harm: the newer version replaces the Logi in the queue
  and in the Skrzynka, so Maks loses the summary and the link to the full Logi, and without the network the full Logi
  (#871, W1 of round 3 of #846).
- **Zbieganie** (liveness): once failures stop and Dad keeps closing and opening Centrum, every journal disappears.
  Harm: `logs/dzienniki-wyceny/` grows forever, or every start sends the same Logi again.

## Why a model of its own

The model of `verify-kolejka-skrzynki` checks what happens to a queue file until the Skrzynka has it exactly once. This
path ends where that one begins: at `Outbox.post` returning True. Here the queue is a set of accepted wysyłki, and the
state is the journals, Logs files and Historia rows on Dad's disk across Centrum starts. Putting both in one model would
multiply a state space that already takes 45 s, so the two models meet at one step: this one checks that the journal
path calls `post` only after `Outbox.resume` and keeps the journal until `post` accepted, and the queue model checks
the rest, which also replaces an older version of the same wysyłka with a newer one in the order of `Version`, also when
the older one was posted later (configuration `starsza` there). This model keeps only the newest version of each
comment the queue accepted (`najnowsza`) and which of them the rank and the clock make newer (`Przyjmij`). The Historia is not
in the model: since #870/#871 the start decides from the journal and the Logs file only.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/UrwaneUruchomienie.tla`, not the code. It describes the code only
while you keep the two in step. Each model action is one indivisible step of this code (`src/rozliczenia/centrum/`
unless named otherwise):

| Model action | Code |
| --- | --- |
| `Start` | `launcher.py` `_start`: `_listen_when_released` takes the port, then `create_app`; in it `closed = comments.close_left_behind()` (`run_comments.py` `RunComments`) takes `logs_disk.py` `LogsOnDisk.left_behind()`, which lists `sorted(glob("*.jsonl"))` and yields one journal at a time. Only the process with the port builds the app, so two closes never run at once. The clock may have gone back while Centrum was closed (`MaxCofniecZegara`): the moments of this work may then be earlier than those of any version already in the queue |
| `Czytaj` | `RunComments.close_left_behind` → `comment_versions.close(left, forbidden, records.interrupted)` for one journal of `LogsOnDisk.left_behind`, which read it with `_read_journal` (no first line → `None`, `Drop`) and then `LogsOnDisk.logs(run_id)` → `_read_logs` of the file whose name (`_names`, `_NAME`, `_RUN_ID`) has the run's identifier, matched in `close` (`Found` → `StandInLogs` of those Logi, with the result or Urwane; `Unreadable` → `WithoutLogsVersion` of `ResultWithoutLogs` `"nieczytelne"`, which the model leaves out; `Missing` with the end entry `_RunEnded` (`read.end`) → `WithoutLogsVersion` of `ResultWithoutLogs` `"niezapisane"`; `Missing` without it → `StandInLogs` of `RecordMaker.interrupted`); every Logi through `guard_logs` and every text through `guard_text` inside `close`. The Historia is not read. An `OSError` from the journal (caught by `left_behind`), from the Logs file, or from listing the Logs folder for another reason than no folder (`Refused`, which `close` raises again and `close_left_behind` catches) leaves the journal; the model's read failure is each of them. One step, because nothing else writes these files while `create_app` runs |
| `ZapiszLogi` | `close_left_behind`, for `StandInLogs(logs)`: `LogsOnDisk.write(logs)` (the `GuardedLogs` of `guard_logs`) → `atomic_file.replace_atomically`; `OSError` only to the Centrum log, and the version still goes to `_pending` |
| `UsunDziennik` | `close_left_behind`: `case Drop(): self._disk.remove_journal(left.key)` → `logs_disk._remove`, a journal without its first line (`unlink`; `OSError` leaves the journal) |
| `Wznow` | `app.py` `lifespan`: `outbox.resume()` before uvicorn accepts the first request |
| `PierwszeZapytanie` | `app.py` `send_interrupted`, a dependency of every API route, → `RunComments.send_left_behind`: `pending, self._pending = self._pending, []` |
| `Wyslij` | `send_left_behind`: `self._queue.post(post_of(version))` → `outbox.py` `Outbox.post` of the stand-in version, `comment_versions.post_of` of `StandInLogs` or of `WithoutLogsVersion` (its text guarded by `guard_text` in `close`), in the rank `rank_of` gives (`Rank.STAND_IN`); `journal_after` gives „usuń” once the queue file exists, and „zostaw” after False leaves the journal for the next start |
| `UsunPoWysylce` | `send_left_behind`: `self._disk.remove_journal(key)` after „usuń” |
| `StartWyceny` | `runs.py` `RunHost.start` → `app.py` `run_started` → `logs_disk.py` `LogsOnDisk.started` → `Journal._run_started` (start in memory, `_header` set) |
| `ZapiszStart` | `Journal._run_started` → `_append_locked(start)` with `_first_line(start)`: the first line alone in one `write`, `flush`, `fsync`, before the thread of the Wycena starts (#846); `OSError` leaves `_header` set, so the first line goes with the next entry, and an `OSError` from `flush` or `fsync` after `write` may leave the whole first line on the disk while `_header` stays. Without `_header` `Journal.progress` gives a progress, so from here the model counts a progress as possible (`postepMozliwy`) |
| `WpisZaczete` | `efenix_pricing.py` `save`: `journal.begun(...)` before `efenix_trace.traced` and `_outcome` → `Journal._write` → `_append_locked` (the first line, while `_header` is set, and the entry in one `write`, `flush`, `fsync`, else the entry alone; `OSError` drops the entry, `_header` stays; an `OSError` from `flush` or `fsync` after `write` may leave the whole first line on the disk, so the journal has its start while `_header` stays) |
| `ZmianaWEfenix` | `_outcome`: the first window action that changes the order (execution date, Wycena Emmetta, a quantity) |
| `WpisSkonczone` | `save`: `journal.ended(result, ...)` after the result → `Journal._write` |
| `Zatrzymanie` | `save`: a `StopError` after `journal.begun` of an order and before its `journal.ended` (the window stops), or before the first `journal.begun` (the window closed while it waits for Dad's login); `save` marks the ready orders and raises it on, and `run_process` returns with the Zatrzymanie, so the Wycena reaches its result without „zlecenie skończone” of that order |
| `Postep` | `pricing_progress.py` `ProgressComment` (at the start of the Wycena and every `PROGRESS_S`) → `RunLogs.progress`: `Outbox.post(post_of(ProgressVersion(...)))` (`Rank.DRAFT`, `rank_of`) when `Journal.progress` gives a progress (no `_header`) and the Uruchomienie is not in `_ended`, both under the lock of `RunLogs`. The model counts the progress as possible from the first line on the disk (`postepMozliwy`); a progress the queue accepted becomes the newest version of the comment when it is newer (`Przyjmij`), a refused one changes nothing |
| `Wynik` | `runs.py` `_Run.work` → `process_run.py` `run_process`: the engine reached its result, the metrics record (the Historia row) is written or not (`metrics_saved`), and `run_process` returns; when it raises, `_Run.work` goes on with a Stop. Nothing on the journal path reads the Historia row, so the model has none |
| `WpisKonca` | `_Run.work` → `RunHost.after` → `pricing_journal.py` `JournalAtResult.run_ended` → `Journal.end`, the first of `after_run` in `create_app` (assignment `runs`): when no write confirmed the first line (`self._header`, and a failed write may have left it), `_remove(path, ...)` (`unlink`; no file, or a file in place of the folder, leaves nothing to remove; `OSError` leaves the journal without its end entry); otherwise `_write(_RunEnded(..., result=result))` (`write`, `flush`, `fsync`), whose `OSError` leaves the journal without its end entry |
| `LogiWyniku` | `RunHost.after` → `RunLogs.run_ended`, the next of `after_run`: `_ended.add` under the lock (the end of the progress), then `guard_logs` and `_keep`: `LogsOnDisk.write` of the Logs with the result |
| `WyslijWynik` | `_keep`: `finally:` `Outbox.post(post_of(OwnLogs(logs)))` (`Rank.OWN`, `rank_of`), and `self._queued.add(...)` when `journal_after` gives „usuń”, i.e. the post returned True |
| `UsunPoLogach` | `RunHost.after` → `JournalAfterLogs.run_ended`, the next of `after_run`: `if self.run_logs.queued(run.info.id): self.journal.remove(run.info.id)`, which removes the journal of this run (`_remove`) unless `_header`; otherwise the journal stays until the next start |
| `KoniecUruchomienia` | the rest of `after_run` (`QuantityCheckAfterRun`, `filling`), then the end of the Uruchomienie |
| `Zgasniecie` | none: Centrum switches off at any step; memory is gone, disk and queue stay; an entry being written may be torn, a torn first line is a journal without a start, and a torn end entry is a journal without one (`_read_journal` counts it in `omitted`); a Wycena with a possible progress whose journal never had its first line on the disk would keep its progress (an event of WersjaKoncowa) |
| `Zamkniecie` | „Zamknij Centrum rozliczeń”: `RunHost.shutdown_refusal` accepts it only when no Uruchomienie runs, and the request passed `send_interrupted` first |

The script compares these definitions with the Sync commit (`model/definicje.json`: file → names, `Class.method` is a
method): `JournalAtResult`, `JournalAfterLogs` in `pricing_journal.py`; `RunLog.interrupted`, `guarded`,
`RunLogs.run_ended`, `_keep`, `queued`, `progress`, `LoggedEnding`, `guard_logs`, `GuardedLogs` in `run_logs.py`;
`ResultWithoutLogs`, `ProgressVersion`, `OwnLogs`, `StandInLogs`, `WithoutLogsVersion`, `rank_of`, `journal_after`,
`post_of`, `Drop`, `close` in `comment_versions.py`; `RunComments.close_left_behind`, `send_left_behind`,
`RecordMaker.interrupted` in `run_comments.py`; `LogsOnDisk.logs`, `_read_logs`, `_names`, `_NAME`, `_RUN_ID`, `LogsRead`, `Journal`, `_first_line`, `_RunEnded`,
`JournalRead`, `_read_journal`, `_remove`, `LogsOnDisk.started`, `left_behind`, `remove_journal`, `write` in `logs_disk.py`;
`lifespan`, `send_interrupted`, the assignments `app`, `disk`, `comments`, `closed` and `runs` (its `after_run` puts
`JournalAtResult`, `run_logs` and `JournalAfterLogs` in this order, and its `previous` is `cards.last(closed)`) and
`run_started` in `app.py`; `_Run.work`, `RunHost.start`, `RunHost.after`, `RunHost.shutdown_refusal` in `runs.py`;
`Outbox.post`, `Outbox.resume`, `Rank`, `Version`, `_version_of`, `_superseded` in `outbox.py`; `_start`,
`_listen_when_released` in `launcher.py`; `replace_atomically` in `atomic_file.py`; `save` in `efenix_pricing.py`;
`run_process` in `process_run.py`. Every code name in the table above is one of them, except six left out on purpose:
`ProgressComment` (it only decides when `RunLogs.progress` runs, and the model lets a progress come at any step it
allows), `guard_text` (the text of a version without Logi), `RunLog` as a whole (the schema of the Logs file, which changes with every new field; the model
reads only `ending`, whose values are `LoggedEnding`), `_outcome`, `efenix_trace.traced` and `StopError`
(`ZmianaWEfenix` and `Zatrzymanie` need only their place in `save` after `journal.begun` and before `journal.ended`,
which `save` holds), `metrics_saved` and the Historia (no step of this path reads
them since #870/#871: `RunCards` and the metrics files are the card's, ADR 0017), and `create_app` (see below). Three
changes move the model without changing a definition, so look for them in the diff: a call of
`comments.send_left_behind()` in `create_app` outside the dependency `send_interrupted`, the `journal` that `create_app`
hands to `EfenixEntry` in `entries` (`disk.journal`; another journal or none, and the Wycena writes no entries that the start reads),
and a new caller of `RunComments`, of `comment_versions.close`, of `Journal.end` or of `RunLogs.progress`
outside these definitions, or a progress that reaches the queue another way than `RunLogs.progress`. Add such code to the table and to `model/definicje.json`. The table lives in data, not in the script, because a path named in the script would make the
change-impact selection (`tools/lib/wplyw_zmiany.py`) run the test of the script on every change of `app.py` or
`atomic_file.py`, although that test builds its own files.

Sync commit: `8537da18d` (2026-11-07, review of #1038, round 2). Every row of the table was checked against the code
at this commit. Since the Sync commit `a78b703c5` `GuardedLogs` has no subclasses (`final`, `__init_subclass__` raises),
and the four version types and `_write` raise `TypeError` for anything but `GuardedLogs` or `GuardedText`, which
`guard`, `guard_logs` and `guard_text` always give on these paths, so the new raise is no step. No step and no order
changed, so no action changed.

Earlier Sync commits, each checked the same way:
- `a78b703c5`: `GuardedLogs` is a class with slots instead of a frozen dataclass, so `dataclasses.replace`, a copy or a
  changed field no longer gives Logi that skipped `guard_logs`; it holds the same Logi after the guard and the same
  Logi before it for the Diagnoza, and `ZapiszLogi` still writes `logs.text`. No action changed.
- `6bdeaf76c`: every version of the comment of an Uruchomienie is a type in `comment_versions.py` (`ProgressVersion`,
  `OwnLogs`, `StandInLogs`, `WithoutLogsVersion`) that carries only Logi or text after the guard (`GuardedLogs` from
  `guard_logs`, `GuardedText` from `guard_text`), and `post_of` gives it the rank of the old `progress_post` and
  `logi_post` (`rank_of`); `journal_after` says „usuń” exactly when `post` returned True, so `_keep` and
  `InterruptedPricings.send` keep their conditions. `ResultWithoutLogs` moved there unchanged, and `RunLogs.send` still
  guards its text when it sends it. Only the names in the table changed and no action changed.
- `b50a4edad`: the journal moved from `pricing_journal.py` into `logs_disk.py` (`Journal`, `_read_journal`,
  `LogsOnDisk.started`, `left_behind`, `remove_journal`, `JournalAtResult`) with the same bytes and order. No action
  changed.
- `68aafac28`: the Komunikat of a Zatrzymanie in `save` asks `_kept` with the results and the trace of the current
  order instead of the window's `sent_change`; `journal.begun` and `journal.ended` kept their place. No action changed.
- `fa352a225`: listing the Logs folder fails with `Refused` unless the folder is missing, and `_closed` raises it again,
  so the read failure of `Czytaj` (`awarieOdczytu`) also stands for a folder the system does not list; an identifier
  that Centrum does not give (`_RUN_ID`) is `Missing` without the disk. No action changed.
- `7cfe46274`: the read of the Logs file in `Czytaj` moved into `logs_disk.py` (`LogsOnDisk.logs`), and `create_app`
  builds `disk` for `InterruptedPricings` and the last-start file. No action changed.
- `ed73f88ce` (#960): `save` no longer reads the Ślad Wyceny Emmetta and stops only on a window stop; `journal.begun`
  and `journal.ended` kept their place. No action changed.
- `ba4092817` (#936 merged with `main` after #910 and #916): `guarded` leaves the fields of tool words and moments
  (`TOOL_FIELDS`) unmasked, and the model has no step in which the guard masks. Since `917cf6fc6` #910 gave a version
  of a wysyłka a rank before its moment (`Rank`, `Version`, `_version_of`, `_superseded`, `progress_post`, `logi_post`,
  `_logs_post`, `RunLogs.send`), the end entry the result, a failed end entry leaves the journal, `JournalAfterLogs`
  removes the journal once the queue accepted the Logi with the result, and the start closes every journal with its
  first line with a stand-in version (`_closed`, `ResultWithoutLogs`). The model got the newest version of each comment
  (`najnowsza`, `Przyjmij` with the rank and the clock, `MaxCofniecZegara`), `Postep`, `UsunPoLogach`, the stand-in
  version in `Czytaj` and `Wyslij`, the promise LogiZostaja in place of WynikZostaje and the configuration `zegar`; the
  known finding `po-wpisie-konca` is gone.
- `917cf6fc6` (since `2b2af53e4`, #846 after its split): a mask in a typed field of the Logs empties it or drops its
  list element, and a top-level field without `None` raises `UnrepresentableLogs`. No action changed.

## Run

```sh
.venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
py -3 .agents\skills\verify-urwane-uruchomienie\scripts\sprawdz_urwane_uruchomienie.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. Java and `tla2tools.jar` come from
`verify-aktualizacja-narzedzia` (`sprawdz_aktualizacje.py` installs pinned `jdk4py` and the jar into `.verification/`
on first use; `TLC_JAVA` and `TLC_JAR` override them). The whole check took 2 min 23 s on Maks's Mac on 2026-11-05
(#910, 15 known findings in 23 TLC runs, with other runs on the machine).

The last line is the verdict:

- `URWANE URUCHOMIENIE OK` or `URWANE URUCHOMIENIE OK, ZNANE ZNALEZISKA: n`: every configuration ends as
  `model/oczekiwane.json` says (n counts each known finding in each configuration). Exit 0 (1 with `--strict` and
  known findings).
- `URWANE URUCHOMIENIE: NOWE NARUSZENIE (n)`: a promise breaks on a path that is not a known finding, or Zbieganie
  breaks. Exit 1.
- `URWANE URUCHOMIENIE: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change below and
  remove it from `model/oczekiwane.json`. Exit 1.
- `URWANE URUCHOMIENIE: BŁĄD MODELU (n)`: TLC gave no verdict (a syntax error, a deadlock) or `TypeOK` broke. Exit 2.
- `URWANE URUCHOMIENIE: ROZJAZD MODELU Z KODEM` (CI only): a definition in `model/definicje.json` changed since the
  Sync commit.
  Outside CI the same is a `UWAGA:` line above the verdict.

Each counterexample is told as numbered steps in the code's words, a failure named after its step („odczyt dziennika
Wyceny 1 rzuca OSError”), and ends with the journals, Logs files, Historia rows and the queue.

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/UrwaneUruchomienie.tla` and one configuration
with the `Wybaczone…` constants as they are (empty), and a view whose regions are Centrum and each Wycena. It shows each
broken promise as its shortest path in plain words; for a configuration of one Wycena with one order and one switch-off
(about 115 states) it also draws the whole chart of how the trail of one Wycena moves between „biegnie”, „dziennik na
dysku”, „Logi Urwanego Uruchomienia w kolejce” and „bez śladu”.

Then tell a real bug from a modeling error: replay the path on the code, one step per action, as a test in the style of
`tests/test_centrum_logi_uruchomienia.py`. A Centrum switched off during a Wycena is either a real kill
(`centrum_process(...)` and `process.kill()`, as in
`test_centrum_zgaszone_w_trakcie_wyceny_w_efenix_po_starcie_wysyla_logi_urwanego_uruchomienia_ze_zleceniami_sprzed_zgasniecia`)
or a journal written with `left_journal` (`tests/fixtures/dziennik_wyceny.py`), as in
`test_logi_urwanego_uruchomienia_w_pliku_i_w_skrzynce_przechodza_przez_straznika_reguly_danych`. A start is
`centrum.restart()`, which builds the app with `create_app` in the test process, so a failed read during one start is
`monkeypatch` of `Path.read_text` (journal) or `Path.open` with mode `"r"` (the efenix metrics file,
`centrum.engines.metrics.efenix`) for that path only, around `restart()`. A failed write is a file in place of the
folder (`logs/uruchomienia`, `logs/dzienniki-wyceny`) or a folder in place of the temporary file
(`<Logs file>.tmp`), a failed metrics record is `monkeypatch` of `MetricsStore.append` raising `OSError` during the
Wycena, and a failed end entry is `Path.open` with mode `"a"` of a journal raising once the efenix metrics file exists
(every order entry comes before the metrics record, the end entry after it). A failed write that leaves its first line
is the first journal file opened with mode `"a"` whose `fileno` raises `OSError` after `write` and `flush`, and a
Zatrzymanie at an order is an Atrapa order with an HTTP error page (both in
`test_wycena_z_wynikiem_ktorej_jedyny_wpis_dziennika_zawiodl_po_zapisie_pierwszej_linii_nie_dostaje_logow_urwanego_uruchomienia`).
The progress comment of a Wycena is the comment of its Uruchomienie in the issue Logów okresu of a box without
`background` (`pricing` in `tests/test_centrum_logi_uruchomienia.py`, a minute of the Centrum clock per efenix request).
A switch-off between the end entry and the accepted Logi with the result holds `RunLogs.run_ended` before `_keep`
(`test_centrum_zgaszone_po_wpisie_konca_a_przed_logami_z_wynikiem_konczy_komentarz_postepu_wynikiem_bez_logow`) or after
it (`test_centrum_zgaszone_zaraz_po_wyslaniu_logow_z_wynikiem_wyceny_w_efenix_nie_zastepuje_ich_logami_urwanego_uruchomienia`),
then `centrum.restart()`. A clock that went back is a queue file whose name has a later moment than any wysyłka of the
next work (`test_cofniety_zegar_komputera_nie_daje_postepowi_w_kolejce_pierwszenstwa_przed_logami_urwanego_uruchomienia`).
A path that does not happen on the code means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two Wyceny of two orders, two switch-offs anywhere, no other failure | known `przed-wpisem-konca` |
| `odczyt` | two Wyceny of one order, one switch-off, one start that cannot read a journal | known `przed-wpisem-konca` |
| `logi-i-kolejka` | two Wyceny, one switch-off, one failed write of a Logs file, one `post` False, one failed `unlink` | known `przed-wpisem-konca` |
| `koniec` | two Wyceny, one switch-off, one Zatrzymanie at an order or before the first, one journal write that fails (the first line, an entry or the end entry, or after the first line is on the disk), one failed `unlink`, one failed write of a Logs file | known `przed-wpisem-konca`, `wpis-konca-nieudany`, `wpis-nieudany` |
| `wpisy` | one Wycena of two orders, one switch-off, one journal write that fails | known `przed-wpisem-konca`, `wpis-konca-nieudany`, `wpis-nieudany` |
| `stare-logi` | Wycena 1 already cut, its Logi Urwanego Uruchomienia written without the guard and not sent, one more Wycena, one switch-off, one failed write of a Logs file | known `przed-wpisem-konca`, `zapis-logow-nieudany` |
| `wszystko` | two Wyceny of two orders, one switch-off, one Zatrzymanie at an order or before the first and one failure of every kind | the three known findings of `koniec` |
| `zegar` | two Wyceny of one order, one switch-off, the clock goes back once while Centrum is closed, one failed write of a Logs file, one `post` False, one failed `unlink` | known `przed-wpisem-konca` |

## Known findings

A configuration forgives only the findings `model/oczekiwane.json` lists for it, each only for its promise and only
for an event that happened with its cause (the history variables `zgubiony`, `poWyniku`, `inneZnaki`, `bezZlecenia`,
`bezWersji` and `wyparty` record the causes at every event, and `bezKonca` why the journal of a Wycena with a result has no end entry); any other
path is a new violation. Each cause is pinned to what the finding is about: `wpis-nieudany` to the orders whose own
entry failed (`przepadle`), so an order missing from the Logi whose entries were written is a new violation;
`przed-wpisem-konca` and `wpis-konca-nieudany` to a Wycena without a Logs file with its result, and
`przed-wpisem-konca` also to a Wycena whose Logi with the result the queue did not accept (a switch-off before the end
entry is before the Logi). WersjaKoncowa and LogiZostaja have no known finding. Each finding has its own run without the
other known findings of its configuration, and the configuration one run without all of them. All four were replayed on
the code.

1. **`przed-wpisem-konca`, BezUrwanychPoWyniku (accepted in #870/#871).** Centrum switches off after `run_process`
   returned with a result and before `Journal.end` wrote „koniec Uruchomienia” (in between: the metrics
   record, `CentrumRuns.remember`, the card; milliseconds of local work). The next start finds the journal without the
   end entry and without Logs and closes it as Logi Urwanego Uruchomienia, although the Historia has the Wycena's row.
   Harm: Maks reads „Centrum zamknęło się w trakcie” with every order of the Wycena finished, and the card after the
   start shows the Urwane Uruchomienie instead of the result from the Historia (ADR 0017). Its Logi with the result
   never existed and never went to the queue (`after_run` writes the end entry first), so nothing in the Skrzynka is
   replaced. Why accepted: the end entry and the metrics record are two files, so one order leaves a window; the other
   order (the end entry before the metrics record, mutation „wpis końca przed rekordem metryk”) makes the journal of a
   Wycena cut in that window disappear without any Logi, which breaks DziennikPoKolejce. Replayed with a journal
   without its end entry (the last line removed after a Wycena, as `_pricing_cut_before_result` in
   `tests/test_centrum_logi_uruchomienia.py` does), the Logs file and the queue folder removed, the metrics record
   kept: the start writes and sends Logi with `ending` `interrupted`, and the card after it is the Urwane Uruchomienie.
2. **`wpis-nieudany`, ZaczeteWLogach (accepted).** A journal entry that fails (`OSError`) loses the entry, the Wycena
   goes on and changes the order in efenix, and when Centrum switches off then, no Logi name that order (or no journal
   exists at all). Only the order of the lost entry: `_write` tries every next entry again (`_failed` only silences
   the second line in the Centrum log), so every other order the Wycena changed is in the Logi. The docstring of `logs_disk.py` accepts it: „Nieudany zapis wpisu to jedna linia dziennika
   Centrum na Uruchomienie, a Wycena biegnie dalej: ślad jest dla Maksa, a nie warunkiem pracy taty”. Replayed with a
   file in place of `logs/dzienniki-wyceny`, a real Centrum process killed after the Atrapa had a change: after the
   restart there is no journal and no Logs file.
3. **`wpis-konca-nieudany`, BezUrwanychPoWyniku (accepted in #870/#871, changed in #910).** The end entry fails
   (`OSError`), so the journal stays without it, and the queue did not accept the Logi with the result in that Centrum
   work (a switch-off before `JournalAfterLogs`, or `post` False), and there is no Logs file with the result (a
   switch-off before it or its `_write` failed): the start cannot know that the Wycena reached its result and closes the
   journal as Logi Urwanego Uruchomienia. A failed end entry plus a switch-off in the milliseconds before the Logs, or
   three failures. When the queue had accepted the Logi with the result, they are a version of a higher rank, so these
   Logi change nothing in the queue or in the Skrzynka; the comment gets them instead of „Uruchomienie trwa” forever,
   which is what a failed end entry left before #910 (it removed the journal), and the card after the start shows the
   Urwane Uruchomienie instead of the result. A Wycena whose first line no write confirmed (`_header`) gets the same
   finding only through a failed `unlink`: a failed write may have left the journal with its first line (a Zatrzymanie
   before the first order or at it then ends the Wycena with that line alone), and `run_ended` removes it. Replayed with
   `Path.open` mode `"a"` of the journal raising after the metrics record and `Path.unlink` of the journal raising
   during the Wycena, before #910: the journal stays with „zlecenie skończone” last and the Centrum log has
   `dziennik-wyceny-niedostepny typ=PermissionError miejsce=wpis` twice; with a file in place of `logs/uruchomienia`
   too, the only comment of Logs in the Skrzynka changed from `ending` `finished` to `interrupted` after the start,
   which the rank now prevents.
4. **`zapis-logow-nieudany`, TeSameZnaki (open, cannot happen at Dad's yet).** Logi Urwanego Uruchomienia written by a
   Centrum work before the guard (#851) and not sent: the start guards them, `LogsOnDisk.write` fails (`OSError`), and the
   queue gets the masked text while the file keeps the phone number. No Wydanie has the journal (#845) without the
   guard (v0.4.3 has neither), so no such file exists at Dad's. Logi written by a guard that masks less are the same
   case: a Wydanie with the journal and the guard from before #863 would leave a phone `48600123456` in the file and
   `[telefon]` in the Archiwum after a failed `write`. Replayed with such a file and a folder in place of its
   `.tmp`: the file has `600 123 456`, the file in the Archiwum `[telefon]`.

Decide 4 with Maks; when the code changes, the finding disappears and the check says `ZNALEZISKO ZNIKNĘŁO`.

Fixed in #910, gone from `model/oczekiwane.json`: `po-wpisie-konca` (WersjaKoncowa: a Wycena whose Logi with the result
did not reach the queue after the end entry kept the progress „Uruchomienie trwa” forever, because the start removed a
journal with the end entry without sending anything, so as not to replace Logi with the result the queue might have
accepted). The start now sends a stand-in version of a rank between the progress and the Logi with the result, and
`JournalAfterLogs` removes the journal once the Logi are accepted, so the start sends it only when they may not be.
`tests/test_centrum_logi_uruchomienia.py` replays the window, the Logi accepted without their file with and without the
network, and the clock that went back (D2 of #875), and the first and the last fail on `main` before the fix.

Fixed in #870/#871, gone from `model/oczekiwane.json`: `wiersz-pozniejszej-wyceny` (DziennikPoKolejce: the start removed
the journal of an Urwana Wycena it had once failed to read, because `RunCards._row` matched the Historia row of a later
Wycena), `historia-nieczytelna` and `historia-niezapisana` (BezUrwanychPoWyniku: a Wycena with a result and without a
Logs file got Logi Urwanego Uruchomienia, which replaced its Logi with the result in the Skrzynka, when the start could
not read the Historia or the metrics record had failed). The journal now says itself that its Uruchomienie reached its
result, so the start reads no Historia; `tests/test_centrum_logi_uruchomienia.py` replays the three paths and fails on
`main` before the fix.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   TLA+ strings must be ASCII; comments may use Polish letters. Never weaken a promise or narrow a configuration to make
   the check pass.
3. A new way to fail gets a constant, a branch guarded by it, and a line in every `.cfg`.
4. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_urwanego_mutations.py` with the code counterpart in its name.
5. Run the check. A new violation is a finding: replay it on the code (Read a result) before you call it a bug, report
   it with the path, and do not change product code unless asked.
6. Move the Sync commit forward only after every row of the table describes the code at the new commit, and write in
   one sentence what changed in the model and why.

## After changing the model

`.venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/check_model_urwanego_mutations.py` applies each
broken variant of the model to a copy of the checkout (`tools/mutacje.py`) and must end with `MUTACJE OK`; run it only
to reproduce a red Mutation checks step or while you change the model. Each mutation removes a guard the code has, and
each gives `URWANE URUCHOMIENIE: NOWE NARUSZENIE`:

- DziennikPoKolejce: the journal removed although `post` returned False (`send_left_behind` without `if
  journal_after(...) == "usuń"`, `logi-i-kolejka`); the end entry written before the metrics record (in `save` or in
  `run_process` before `MetricsStore.append`: a journal cut between the two disappears without Logi); the version only
  from the moment, without a rank, after the clock went back (`zegar`: the progress in the queue is newer than the Logi
  Urwanego Uruchomienia of the start, which the queue drops, D2 of #875).
- BezUrwanychPoWyniku: `close` without `read.end`; no end entry at all (`after_run` without `JournalAtResult`); `after_run`
  with `run_logs` before `JournalAtResult` (`koniec`: Logi with the result accepted without their file, a switch-off before the
  end entry, and the start gives the Wycena Logi Urwanego Uruchomienia); `Journal.end` returning on `self._header` without
  `_remove` (`koniec`: the first entry fails after its first line is on the disk, the Wycena stops at that order, and
  the start gives it Logi Urwanego Uruchomienia).
- TeSameZnaki: the Logs file written before the guard (`write` before `guard_logs`, which mypy rejects: `write` takes
  only `GuardedLogs`).
- PrzezStraznika: `close` without `guard_logs` (2ff78b6b3, which mypy rejects too: `StandInLogs` and `write` take only
  `GuardedLogs`, and the guard is inside `close`, so the shell that calls it cannot leave it out).
- NicPrzedWznowieniem: the stand-in version sent in `create_app` right after `close_left_behind`, not in the dependency
  of the first request.
- ZaczeteWLogach: `_read_journal` without the order begun without a result; `journal.begun` after the first window action;
  `Journal._write` starting with `if self._failed: return` (`wpisy`: after one failed entry the journal writes
  nothing more, so an order without a failed entry of its own is missing from the Logi).
- WersjaKoncowa: `Journal.progress` without `self._header` (`wpisy`: the write of the first line at the start
  fails, the progress goes, Centrum switches off before the next entry, and no journal can finish the comment, W1 of
  round 1 of #846); `_append_locked` clearing `_header` also after `OSError` (`wpisy`); a failed end entry that removes
  the journal (`Journal.end` as in #888, `wpisy`); the start that removes a journal with a Logs file without sending it
  (`close` giving `Drop` as the start on `main` before #910, `zwykle`); `JournalAfterLogs` without `RunLogs.queued` (`logi-i-kolejka`: `post` of
  the Logi with the result returns False, and the journal disappears); the progress of the rank of the stand-in version
  (`rank_of` giving `ProgressVersion` `Rank.STAND_IN`, `zegar`); the whole start of `main` before #910 (`zwykle`: the
  start removes a journal with the end entry without sending anything, W2 of #875).
- LogiZostaja: the version only from the moment, without a rank (`logi-i-kolejka`: the Logs file failed, the queue
  took the Logi with the result, Centrum switches off before `JournalAfterLogs`, and the result without Logi of the start
  is newer, W1 of round 3 of #846); the stand-in version of the rank of the Logi with the result (`rank_of` giving
  `StandInLogs` `Rank.OWN`, `logi-i-kolejka`).
- Zbieganie: `send_left_behind` without `remove_journal(key)`; `close_left_behind` without `remove_journal(left.key)`
  for `Drop`.

`RunLogs.progress` without `if run_id in self._ended: return False`, or `_ended.add` after `_keep`, breaks no promise
since #910: a progress after the Logi with the result has a lower rank and changes nothing. `_ended` still ends the
progress timer, which the test
`test_postep_wyceny_w_efenix_ktorego_budzik_dzwoni_gdy_jej_logi_sa_juz_w_kolejce_nie_cofa_podsumowania` checks.

A mutation reported as `NIEAKTUALNA` no longer matches the model: rewrite its anchor against the new model so that it
breaks the same rule again.

## Scope

Verified: the nine promises over every order of the actions above within the bounds of each configuration (one or two
Wyceny started one after the other, one or two orders each, one or two switch-offs, at most one Zatrzymanie at an
order or before the first and at most one failure of each kind), with Dad opening and closing Centrum as often as he likes. Assumed, each a
reason the check can pass while the code is wrong:

- **`os.replace` is atomic** (`replace_atomically`): a switch-off leaves the old Logs file or the new one.
- **One Centrum at a time builds the app**: `_listen_when_released` takes the port before `create_app`, and the old
  Centrum, which may still finish requests for `_GRACEFUL_SHUTDOWN_S` after it released the port, runs no Uruchomienie
  then (`shutdown_refusal`). A second process that bypassed the port would close the journal of a Wycena still running.
- **`send_left_behind` runs atomically** on the event loop (`async def` without `await`), and the first request of a work comes
  before any Wycena of that work, because every route has the dependency.
- **The guard is idempotent**: Logs that passed `guard` pass it again unchanged, so rereading a file written by `close_left_behind`
  changes nothing; only Logs written without the guard (`StareLogi`) change. A number the guard masked becomes the text
  of its mask, which it leaves as it is. Idempotent means one version of the guard: Logs written by a Centrum whose
  guard masked less (before #851 nothing, before #863 the phone with `48` without `+`) are `StareLogi` for a newer one.
  It also means the memory of a start: the start guards before it reads any file of Dad's (ADR 0025). With the memory
  that wrote the Logs, a value equal to a field name in the place of a guard note is masked again in that note (5 of the
  words of the full Logs in the test of #936, 6 before it), but no step guards Logs twice with one memory.
- **A journal without its end entry is an Urwane Uruchomienie or one of the known findings `przed-wpisem-konca` and
  `wpis-konca-nieudany`.** A journal written by a build between #845 and #870/#871 has no end entry either, so a Wycena
  of such a build that reached its result without a Logs file gets Logi Urwanego Uruchomienia; no Wydanie has such a
  build (v0.4.3 has no journal), so only Maks's computers can have such a journal. Every Uruchomienie that reached its
  result reaches `RunHost.after` (`_Run.work` catches an exception of `run_process` and goes on).
- **The queue keeps the newest version by `Version`** (rank, then the moment), as `verify-kolejka-skrzynki` checks, so
  the model keeps only the newest version each comment got (`najnowsza`). Its moments are abstract: a later `post` in one
  Centrum work has a later moment (`Outbox.post`), and a version of an earlier work an earlier one, unless the clock
  went back at a start since then (`cofniety`), when the order is either. Two versions of one rank compare by the moment
  only within one Centrum work (progresses; the Logi with the result and the Diagnoza, which the model leaves out) or
  between stand-in versions of one journal from two starts (a failed `unlink`), which have the same kind.
- **A progress is possible from the first line on the disk on**: the model counts it from `ZapiszStart` or the first
  successful `Wpis` to the end of the Wycena, the earliest `ProgressComment` can send it, so every journal that may have
  a progress in the Skrzynka is checked; a progress that did not come yet only makes the check stricter.
- **`RunLog.model_validate_json(text).text == text`** for a file `close_left_behind` wrote, and two builds of the same journal give
  Logs with the same orders; their environment, tool and Dad's actions may differ, which the model leaves out. A rebuild
  happens only when the file is missing, so the file and the newest accepted Logi have the same orders, whichever of
  two stand-in versions of one journal the clock makes newer.

Left out: a glob of `logs/dzienniki-wyceny/` that fails (it skips every journal, like one failed read per journal), a
Logs file that cannot be parsed (truncated by hand, a schema from a newer version after a rollback: `close` sends the
result without Logi, `"nieczytelne"`), a torn entry in the middle of a journal (counted in `omitted`), a failed write
that left a torn first line (`run_ended` removes it like a whole one, and a start removes a journal without a start), the
Historia (no step of this path reads it), exceptions other than `OSError` in `close_left_behind`, `send_left_behind` or `run_ended` (one in
`RunLogs.run_ended` leaves the Logi with the result out of the queue, like `post` False: the journal stays for the
stand-in version), the text of the progress and of the result without Logi, the Diagnoza (a newer version of the Logi
with the result, of their rank and Centrum work), Dad's actions in the Logs (`DadActionJournal.take`), and the karta after
the start (`RunCards.last`, which shows the Urwane Uruchomienie for `przed-wpisem-konca` and `wpis-konca-nieudany`).

## Files

- `model/UrwaneUruchomienie.tla`: the model, with the code each action describes.
- `model/*.cfg`: the configurations (first line describes it), `model/oczekiwane.json`: the expected result,
  `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_urwane_uruchomienie.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_urwanego_mutations.py`: proves the check fails when the model loses a guard the code has.
