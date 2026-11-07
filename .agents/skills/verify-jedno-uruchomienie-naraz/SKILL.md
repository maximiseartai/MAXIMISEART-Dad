---
name: verify-jedno-uruchomienie-naraz
description: Exhaustively check that Centrum rozliczeń runs one Uruchomienie procesu, Aktualizacja narzędzia or przywrócenie Kopii INTERMAX at a time and never closes during one (also while it waits for Dad's Decyzja), under every interleaving of browser tabs, Dad and the server. Use when a change touches `RunHost` or `_Run` in `src/rozliczenia/centrum/runs.py`, `Shutdown` in `shutdown.py`, `stop_when_asked` in `server.py`, the `refuse_while` wiring in `app.py`, `ToolUpdates.start` or `_update` in `tool_updates.py`, adds another action that must wait for a running Uruchomienie, or `test_jedno_uruchomienie_naraz` fails.
pilnuje:
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/shutdown.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/tool_updates.py
  - src/rozliczenia/centrum/intermax_run.py
ci: .agents/skills/verify-jedno-uruchomienie-naraz/scripts/explore_runs.py
---

# Verify jedno Uruchomienie naraz

## What CI runs and what stays local

CI runs `explore_runs.py` whole (the `ci:` key) and `tests/test_jedno_uruchomienie_naraz.py` whenever
a change touches this skill, and `check_runs_mutations.py` in full CI on `main` and nightly on `main`
(`mutacje-nocne.yml`). Run them locally only to reproduce a red CI step or the night's issue, or one
`--scope` while you work on it. What stays with you on every change
to the covered code is „Does the change touch it?”: read each commit since the sync commit against the
table, above all the parts modelled by hand, whose change the check cannot see.

## The promise

- **JEDNO_NARAZ**: Centrum never has two Uruchomienia procesu in progress at once,
  nor an Uruchomienie and an Aktualizacja narzędzia, nor two Aktualizacje, nor a
  przywrócenie Kopii INTERMAX beside any of them or beside another przywrócenie. Harm: two
  engines work on the same Folder okresu and metrics file, and Dad gets two results
  that contradict each other; or Git and pip change the tool under a running engine;
  or a przywrócenie replaces INTERMAX under a running Uporządkowanie INTERMAX, whose
  replace then puts the old day back over it.
- **BEZ_ZAMKNIECIA_W_TRAKCIE**: Centrum's server never ends while an Uruchomienie
  procesu is in progress, including one waiting for Dad's Decyzja. Harm: the
  Uruchomienie thread is a daemon, so the end of the Python process kills it
  mid-work. Dad saw it start and then gets no result; its metrics record and the
  end entry in the Centrum log are missing; a temporary folder can stay behind; a
  kill between the two moves of publication, or after a failed second move and
  before its rollback removed the first file, is the
  [ADR 0005](../../../docs/adr/0005-przerwana-publikacja-plikow-okresu.md) case.
  The same holds for an Aktualizacja narzędzia until its restart guardian has
  started: killed mid-Git or mid-pip, it leaves the clone for the next start to
  roll back.
- **PO_WYNIKU_PRZED_KONCEM**: Centrum's server never ends between an
  Uruchomienie's result and its actions after the result (`RunHost.after`, the
  `after_run` list in `create_app`). Harm: the Logi Uruchomienia of every
  Uruchomienie and the Kontrola ilości of a Przebieg rozliczeń land in their files
  in those actions; a shutdown or update accepted in between kills the thread
  before the files exist, and Maks never gets them.
- **WYNIK_NA_KARCIE**: the result of every Uruchomienie (its `finished` view) reaches
  the card, also when a second tab clicks „Uruchom” right after its end. A card's
  event stream reads `RunHost.events_after` every 50 ms, so the result must stay
  among the views after the one the card read when that Uruchomienie started.
  Harm: the card jumps from „trwa” straight to the next Uruchomienie and never
  shows the result; Dad finds it only in Historia (#723).

An Uruchomienie is in progress from the moment `RunHost.start` creates its `_Run`
until `RunHost.finished` has written its end to the Centrum log. The checker
tracks this itself, not through the code's `ended` flag. An Aktualizacja is in
progress from a successful `RunHost.begin_update` until `end_update` returns or,
after a new version, until the restart guardian has started and
`Shutdown.close_for_update` may end the server.

## Does the change touch it?

| Covered code | What the check relies on |
| --- | --- |
| `runs.py` `RunHost.start`, `shutdown_refusal`, `decide`, `finished`, `publish` | check and claim of `_run` under `_lock`; refusal while a run has not ended; an accepted shutdown sets `_closing` under the same lock; the start file (`run_started`, `logs_disk.LogsOnDisk.started`) written outside the lock, after the claim and before the thread; `start` keeps the last view (the previous result) in `_events` |
| `runs.py` `RunHost.begin_update`, `end_update`, `_busy_locked` | check and claim of `_updating` under `_lock`; refusal while closing, updating, restoring or running |
| `runs.py` `RunHost.begin_restore`, `end_restore`; `start` | check and claim of `_restoring` under `_lock`; `start` refuses while restoring |
| `intermax_run.py` `intermax_copies_router` | modelled by hand: `begin_restore`, the restore as one step inside the request, then `end_restore` |
| `runs.py` `_Run.work`, `RunHost.end`, `confirm`, `answer` | `ended` set only in `RunHost.end`, under `_lock` together with the result; after-run actions (`RunHost.after`) before `finished`; waiting for the Decyzja on `_decided` |
| `shutdown.py` `Shutdown.request`, `wait`, `refuse_while`, `close_for_update` | refusal check, then `_requested.set()`; `close_for_update` sets it without the check |
| `tool_updates.py` `ToolUpdates.start`, `_update`, `_restart` | modelled by hand: `begin_update`, a log entry, the thread; then either `end_update` or the guardian and `close_for_update` |
| `app.py` `create_app`: `shutdown.refuse_while(runs.shutdown_refusal)` | the wiring the harness copies |
| `server.py` `serve.stop_when_asked` and uvicorn graceful shutdown | modelled by hand (see below) |

**Sync commit: `05430811`** (main, 2026-10-31). At this commit the checker was confirmed to describe
the covered code. From the previous sync commit `ef1eff19` (#472), `runs.py`, `shutdown.py`, `server.py` and
`intermax_run.py` did not change. `tool_updates.py` changed only outside the slot: the result after a restart is
judged in `_after_restart` at Centrum's start (#490, #491), and a failure's next action comes from
`update_messages.UpdateFailure`; `start` still claims the slot with `begin_update` before its thread, and `_update`
still calls `end_update` in its `finally` or `close_for_update` after the guardian. `app.py` changed only in the
Skrzynka wiring (`on_rejected`, the box passed to `dad_notes_router`) and a comment. The Centrum's POST and PUT
endpoints are the same as at `ef1eff19`, so no new action has to wait for the slot. To see whether
it needs another look:

```bash
git log --oneline 05430811..HEAD -- src/rozliczenia/centrum/runs.py src/rozliczenia/centrum/shutdown.py src/rozliczenia/centrum/server.py src/rozliczenia/centrum/app.py src/rozliczenia/centrum/tool_updates.py src/rozliczenia/centrum/intermax_run.py
```

For every listed commit, read its diff against the table. Move the sync commit
forward (here and in nothing else) only after you have confirmed that the
harness still matches the code at the new commit and the check and the mutations
pass there. Changes to process content, progress views, Diagnoza or Zgłoszenia
do not matter here: the checker replaces the engine with fixed steps. Neither do
the actions after the result themselves (`after_run` in `app.py`): the checker
replaces them with one step, and their network work runs on a thread outside
`runs.py` that holds nothing. The same holds for the start-time retry of that
queue (`outbox.resume()` in `lifespan`).

## Run

```powershell
py -3 .agents\skills\verify-jedno-uruchomienie-naraz\scripts\explore_runs.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`. It takes about 5 s on a
Mac and runs in CI as `tests/test_jedno_uruchomienie_naraz.py`. In a worktree the
script checks the worktree's own `src`.

| Last line | Exit | Meaning |
| --- | --- | --- |
| `URUCHOMIENIA OK` | 0 | All four rules hold in every schedule. |
| `URUCHOMIENIA OK, ZNANE USTALENIA: n` | 0 | Only the known findings below, each printed with its counterexample. |
| `URUCHOMIENIA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below, or a scope never reached a behaviour it must reach (`BRAK_ZAMKNIECIA`, `BRAK_ODMOWY_ZAMKNIECIA`, `BRAK_WYNIKU`, `BRAK_ODMOWY_STARTU`, `BRAK_DRUGIEGO_WYNIKU`), so the check would prove nothing. |
| `URUCHOMIENIA: LUKA MODELU (n)` | 2 | `runs.py` or `shutdown.py` uses `threading` in a way the model does not cover (for example `RLock`, `Condition`, `wait(timeout=...)`), or a modelled thread waits on something outside the model. No verdict on the rules. |

A modelled thread that waits on a real lock or Event, or on `time.sleep`, outside the model ends the check about
10 s after its last step, not at pytest's 120 s limit, with a line like
`LUKA MODELU: karta Uruchom 2: po kroku „żądanie POST /api/runs dociera do serwera” wątek modelu przez 10 s nie doszedł do kolejnego i stoi w runs.py:350 start (with _REAL, self._lock:), …`
and the schedule up to that step.

`--scope zamknij-w-trakcie`, `--scope dwie-karty`, `--scope aktualizacja` or `--scope przywracanie` runs one scope. `--strict`
counts known findings as violations too: use it to confirm a fix.

## How it works and what it covers

The script runs the real `RunHost` and `Shutdown`, wired as in `create_app`, in
modelled threads. FastAPI runs the sync handlers `startRun`, `decideRun` and `closeCentrum`
in a thread pool, so tabs really do run in parallel. Each modelled thread is a
greenlet on one OS thread of the script, so a busy CI runner slows the check only by
its share of a CPU, not by a kernel thread switch at every step (#565). The script watches that
thread from outside: 10 s without a step means a modelled thread that waits outside the model,
because a busy runner stretches the gap between two steps only to a fraction of a second. That thread stays
blocked, with every lock it holds, until its process ends: the script's process ends by itself after the report (the
thread is a daemon). So every test runs `explore` on the real code in a process of its own with a time limit, even a
test whose stand-in releases what the thread waits on: code under check can stall on a lock of its own first, and in
the pytest worker that lock stopped every later test of Centrum while the session hung with no LUKA in its log (#651).
Inside `runs.py` and
`shutdown.py`, `threading` is replaced by model primitives: entering
`RunHost._lock`, each `Event.set`/`clear`/`wait` and starting the Uruchomienie
thread is one indivisible step, as is each Centrum log entry and
`CentrumRuns.remember` (file writes in the real code). Before each step the
checker lets any thread whose step can go now go first, and it tries every such
order. A lock entry can go only while the lock is free, and `wait()` only once the
Event is set. The actions after the result (`AfterRun`) are one step that
writes nothing. A card's event stream is not a modelled thread: at the end of
every schedule the checker reads `RunHost`'s views (`_events`) as a card would
next read them, from the view it read when each Uruchomienie started, and finds
there the result of every Uruchomienie whose thread finished its work. In
`dwie-karty` that holds only if a second Uruchomienie started after the first
result (`BRAK_DRUGIEGO_WYNIKU` otherwise). Schedules that reach a state already
seen are cut short; the state includes those views.

Replaced: `intermax_copies_router` by a „Przywróć tę kopię” tab that calls the real
`begin_restore`, takes one step for the Kopia and the replace of INTERMAX (`intermax_restore.restore`,
which [`verify-zapis-intermax`](../verify-zapis-intermax/SKILL.md) checks) and calls the real `end_restore`,
all inside its request, so uvicorn's graceful shutdown waits for it.
Replaced: `ToolUpdates` by a „Zaktualizuj narzędzie” tab that calls the real
`begin_update`, logs and starts the update thread, and a thread whose Git, pip and
guardian work is one step ending either without a new version (or in a failure),
then `end_update`, or with the guardian started, then the real
`Shutdown.close_for_update`. Replaced: the last Uruchomienie before Centrum's start (`previous`) by none, and the start file (`run_started`)
by one step that writes nothing. Replaced: `run_process` by an engine with one work step, an optional Decyzja
through the real `_Run.confirm` (both variants are explored) and an end step. Every
Uruchomienie ends in success. Modelled by hand: after `Shutdown.wait()` returns,
the server may end at any moment when no HTTP request is in flight. This is
uvicorn's `should_exit` tick (≤ 0.1 s), during which new requests are still
accepted, followed by its graceful shutdown, which serves requests already
received.

| Scope | „Uruchom” tabs | „Zamknij Centrum rozliczeń” clicks | Dad's Decyzje |
| --- | --- | --- | --- |
| `zamknij-w-trakcie` | 1 | ≤ 2 (a refused click is retried) | ≤ 1 |
| `dwie-karty` | 2 | ≤ 1 | ≤ 2 |
| `aktualizacja` | 1, plus 2 „Zaktualizuj narzędzie” tabs | ≤ 1 | ≤ 1 |
| `przywracanie` | 1, plus 2 „Przywróć tę kopię” tabs | ≤ 1 | ≤ 1 |

Not covered: Zatrzymania and errors inside the engine (`_Run.work`'s `except`
path), `tools/uruchom_proces.py` or a second Centrum process on another port,
Windows logoff, the SSE stream itself (`_event_stream`, read through `RunHost`'s views), Diagnoza and Zgłoszenie (`diagnose`/`send_report`), more tabs or clicks than
above, and what Aktualizacja narzędzia does to the clone (the
[`verify-aktualizacja-narzedzia`](../verify-aktualizacja-narzedzia/SKILL.md) model
covers it). When another action that must not run during an Uruchomienie lands,
add it as an actor in `_drive` with a rule that it never overlaps an Uruchomienie
or a shutdown, and add a mutation for it.

## Known findings

None. The two earlier ones (a „Uruchom” between the refusal check and the
accepted shutdown, and a „Uruchom” after it) went away when `shutdown_refusal`
started closing `RunHost` to new Uruchomienia and Aktualizacje under its lock.
A finding the user accepts goes into `KNOWN_FINDINGS` in `explore_runs.py` and
here, as an entry with a `name`, one line naming the decision and a `shape`: a
dataclass whose fields are the parts of its story, not the printed signature.
The mutation script then needs `BOUNDARIES` with a broken variant just outside
each part (`tests/test_mutacje_skilli.py`, #920).

## When the check fails

Read the counterexample as a story. Each numbered line is one step:
`karta Uruchom n`, `karta Zaktualizuj n`, `karta Zamknij` and `tata` are browser
requests, `wątek Uruchomienie n` is the thread `RunHost.start` spawned,
`wątek Aktualizacja n` the one `ToolUpdates.start` spawned, `serwer` is
`stop_when_asked`, and `[runs.py:LINE function]` is the code that took the step
(`[model]` marks a harness step). Then sort it into one of three cases:

- **Real bug**: the story can happen with two Centrum tabs on Dad's computer,
  and the end state breaks a rule as stated above. Report it with the story in
  those words. Fix the product code only if the user asks. If the user accepts
  it instead, add it to `KNOWN_FINDINGS` as Known findings above says, and add it
  to Known findings here.
- **Modeling error**: the story contains a step the real system cannot take,
  such as a request arriving after uvicorn stopped accepting, or a thread
  passing a lock another thread holds. Fix the model primitives or the actors in
  `explore_runs.py`, then rerun the mutations below.
- **LUKA MODELU**: model the new `threading` use in `ModelThreading` with its
  real semantics (a step per entry or signal, and a step that can go only when
  it would not block), or ask whether the code should avoid it. For a thread
  that waits outside the model, the printed line names the wait to model or avoid. Never reword a
  rule or shrink a scope to make a real counterexample disappear.

## After changing the checker or an intended change to the covered code

CI proves the check can still fail: the night on `main` runs the script below after a
change of this skill's folder. Run it locally only to reproduce a red Mutation checks step
or the night's issue, or after you rewrite a mutation. It applies broken variants to a temporary copy
of `src`, never to the checkout, each in the one scope that catches it (about
45 s on a Mac):

```powershell
py -3 .agents\skills\verify-jedno-uruchomienie-naraz\scripts\check_runs_mutations.py
```

It must end with `MUTACJE OK`. These all give `NOWE NARUSZENIE`: the check and
claim in `start` under two lock entries (two Uruchomienia at once), a refusal that
skips a run waiting for its Decyzja, `ended` set at the start of `_Run.work`,
the actions after the result moved below `RunHost.end`, `ended` set under `_lock`
before the result is published outside it, `start` clearing the previous result from `_events`,
`Shutdown.request` without the refusal, an accepted shutdown that does not set
`_closing`, `begin_update` without the closing or the running check, `start`
without the updating check, `begin_restore` without the running check,
`start` without the restoring check, and `_busy_locked` blind to a restore. `RLock` in `RunHost` gives `LUKA MODELU`,
and so does a real lock outside `threading` held across a step of `start`.
CI runs this in the `mutations` job. A mutation reported as `NIEAKTUALNA` no longer matches its file.
Rewrite its `anchor` and `replacement` in `check_runs_mutations.py` so it breaks
the same rule again in the new code. Then move the sync commit forward as above.
