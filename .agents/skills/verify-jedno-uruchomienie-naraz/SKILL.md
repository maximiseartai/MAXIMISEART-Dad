---
name: verify-jedno-uruchomienie-naraz
description: Exhaustively check that Centrum rozliczeń runs one Uruchomienie procesu, Aktualizacja narzędzia or przywrócenie Kopii INTERMAX at a time and never closes during one (also while it waits for Dad's Decyzja), under every interleaving of browser tabs, Dad and the server. Use when a change touches `RunHost` or `Run` in `src/rozliczenia/centrum/runs.py`, `Shutdown` in `shutdown.py`, `stop_when_asked` in `server.py`, the `refuse_while` wiring in `app.py`, `ToolUpdates.start` or `_update` in `tool_updates.py`, adds another action that must wait for a running Uruchomienie, or `test_jedno_uruchomienie_naraz` fails.
pilnuje:
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/shutdown.py
  - src/rozliczenia/centrum/threads.py
  - src/rozliczenia/centrum/process_kind.py
  - src/rozliczenia/centrum/catalog.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/tool_updates.py
  - src/rozliczenia/centrum/intermax_run.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/eksplorator.py
ci: .agents/skills/verify-jedno-uruchomienie-naraz/scripts/explore_runs.py
---

# Verify jedno Uruchomienie naraz

## What CI runs and what stays local

CI runs `explore_runs.py` whole (the `ci:` key) and `tests/test_jedno_uruchomienie_naraz.py` whenever
a change touches this skill, and `check_runs_mutations.py` in full CI on `main` and nightly on `main`
(`mutacje-nocne.yml`). Run them locally only to reproduce a red CI step or the night's issue, or one
`--scope` while you work on it. `explore_runs.py` fails with `URUCHOMIENIA: ROZJAZD MODELU Z KODEM` in CI, before it
explores, when a part modelled by hand (`model/definicje.json`) differs from its digest there; outside CI the same is a
`UWAGA:` line above the verdict. `tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`), and
one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both. What stays with you on every change
to the covered code is „Does the change touch it?”: read the diff since the digests against the
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
  Uruchomienie's result and its actions after the result (`RunHost.after`: the
  Logi Uruchomienia `logs`, then the `after_run` list in `create_app`). Harm: the Logi Uruchomienia of every
  Uruchomienie and the Kontrola ilości of a Przebieg rozliczeń land in their files
  in those actions; a shutdown or update accepted in between kills the thread
  before the files exist, and Maks never gets them.
- **WYNIK_NA_KARCIE**: the result of every Uruchomienie (its `finished` view) reaches
  the card, also when a second tab clicks „Uruchom” right after its end. A card's
  event stream reads `RunHost.events_after` every 50 ms, so the result must stay
  among the views after the one the card read when that Uruchomienie started.
  Harm: the card jumps from „trwa” straight to the next Uruchomienie and never
  shows the result; Dad finds it only in Historia (#723).

An Uruchomienie is in progress from the moment `RunHost.start` creates its `Run`
until `RunHost.finished` has written its end to the Centrum log. The checker
tracks this itself, not through the code's `ended` flag. An Aktualizacja is in
progress from a successful `RunHost.begin_update` until `end_update` returns or,
after a new version, until the restart guardian has started and
`Shutdown.close_for_update` may end the server.

## Does the change touch it?

| Covered code | What the check relies on |
| --- | --- |
| `runs.py` `RunHost.start`, `shutdown_refusal`, `decide`, `finished`, `publish` | check and claim of `_run` under `_lock`; refusal while a run has not ended; an accepted shutdown sets `_closing` under the same lock; the start file (`logs.run_started`, `logs_disk.LogsOnDisk.started`) written outside the lock, after the claim and before the thread; `start` keeps the last view (the previous result) in `_events` |
| `runs.py` `RunHost.begin_update`, `end_update`, `_busy_locked` | check and claim of `_updating` under `_lock`; refusal while closing, updating, restoring or running |
| `runs.py` `RunHost.begin_restore`, `end_restore`; `start` | check and claim of `_restoring` under `_lock`; `start` refuses while restoring |
| `intermax_run.py` `intermax_copies_router` | modelled by hand: `begin_restore`, the restore as one step inside the request, then `end_restore` |
| `runs.py` `Run.work`, `RunHost.end`, `confirm`, `answer` | `ended` set only in `RunHost.end`, under `_lock` together with the result; after-run actions (`RunHost.after`) before `finished`; waiting for the Decyzja on `_decided` |
| `shutdown.py` `Shutdown.request`, `wait`, `refuse_while`, `close_for_update` | refusal check, then `_requested.set()`; `close_for_update` sets it without the check |
| `tool_updates.py` `ToolUpdates.start`, `_update`, `_restart` | modelled by hand: `begin_update`, a log entry, the thread; then either `end_update` or the guardian and `close_for_update` |
| `app.py` `create_app`: `shutdown.refuse_while(runs.shutdown_refusal)` | the wiring the harness copies |
| `server.py` `serve.stop_when_asked` and uvicorn graceful shutdown | modelled by hand (see below) |

`model/definicje.json` holds a digest of each part modelled by hand: `ToolUpdates.start`, `_update` and `_restart`,
`intermax_copies_router` and `serve.stop_when_asked` (a name is a path from the module). The rest of the table runs as
real code, and `create_app` is left out on purpose: it changes with every new endpoint, so look in its diff for the
`refuse_while` wiring and for a new action that must wait for the slot. The digests were taken when the harness was last
confirmed to describe the code (`tools/przesun_model.py`); what that confirmation found is in the message of the commit
that changed them. To see what changed since:

```bash
git diff $(git log -1 --format=%h -- .agents/skills/verify-jedno-uruchomienie-naraz/model/definicje.json) -- src/rozliczenia/centrum/runs.py src/rozliczenia/centrum/shutdown.py src/rozliczenia/centrum/server.py src/rozliczenia/centrum/app.py src/rozliczenia/centrum/tool_updates.py src/rozliczenia/centrum/intermax_run.py
```

Changes to process content, progress views, Diagnoza or Zgłoszenia
do not matter here: the checker replaces the engine with fixed steps. Neither do
the actions after the result themselves (`logs` and `after_run` in `app.py`): the checker
replaces them with one step, and their network work runs on a thread outside
`runs.py` that holds nothing. The same holds for the start-time retry of that
queue (`outbox.resume()` in `lifespan`).

## Bring the model in line

When a part modelled by hand changes, or the diff above touches a row of the table:

1. Read the diff against the table; the drift line names each changed part.
2. Change the harness in `explore_runs.py` so that it does what the code does, step for step, and the table row with it.
3. Run the check and `--strict` on the scope you changed. A new violation is a finding: replay it on the code before
   you call it a bug.
4. Run `tools/przesun_model.py verify-jedno-uruchomienie-naraz` only after the harness and the table describe the code,
   and write in the commit message what changed in the harness and why.

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
| `URUCHOMIENIA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding did not show in a scope of its `after` that ran to the end. If a change fixed it, narrow or delete it in `KNOWN_FINDINGS` and below. |
| `URUCHOMIENIA: ROZJAZD MODELU Z KODEM` | 1 | Only in CI, before the check: a part modelled by hand differs from its digest in `model/definicje.json` (see „Bring the model in line”). |
| `URUCHOMIENIA: LUKA MODELU (n)` | 2 | `RunHost`, `Run` or `Shutdown` uses its `threads` seam in a way the model does not cover (for example `RLock`, `Condition`, `wait(timeout=...)`), `RunHost` takes no lock from it, or a modelled thread waits on something outside the model. No verdict on the rules. |

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
Nothing in the verified modules is replaced: `RunHost`, its `Run` and `Shutdown`
get model primitives through their `threads` seam (`threads.Threading`, the
`threading` module by default), so entering
`RunHost._lock`, each `Event.set`/`clear`/`wait` and starting the Uruchomienie
thread is one indivisible step, as is each Centrum log entry and
`CentrumRuns.remember` (file writes in the real code). Before each step the
checker lets any thread whose step can go now go first, and it tries every such
order. A lock entry can go only while the lock is free, and `wait()` only once the
Event is set. The actions after the result (`AfterRun`) are one step that
writes nothing. A card's event stream is not a modelled thread: at the end of
every schedule the checker reads `RunHost`'s views (`events_after`, between steps,
so without a step of the lock) as a card would
next read them, from the view it read when each Uruchomienie started (`RunHost`'s
`created` hook hands over each new `Run` with the last view before it), and finds
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
`Shutdown.close_for_update`. Replaced: the last Uruchomienie before Centrum's start (`previous`) by none, and the Logi Uruchomienia (`logs`: the
start file of `run_started` and the actions after the result) by one step each that writes nothing. Replaced: `run_process` by an engine with one work step, an optional Decyzja
through the real `Run.confirm` (both variants are explored) and an end step, as the engine of the catalog
(`Catalog.with_engine`) whose `Catalog.prepared` gives the Uruchomienie every tab starts, so the real
`PreparedRun.conduct` runs. Every
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

Not covered: Zatrzymania and errors inside the engine (`Run.work`'s `except`
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
here, as an `Excuse` of `tools/lib/eksplorator.py`: its `name`, the rule, one
line naming the decision, a `shape` (a dataclass whose fields are the parts of
its story and whose `holds` judges the violation's signature) and in `after` the
scopes after which it always shows; a scope of `after` that runs to the end
without it ends the check with `ZNALEZISKO ZNIKNĘŁO`. The mutation script then
needs `BOUNDARIES` with a broken variant just outside each part
(`tests/test_mutacje_skilli.py`, #920).

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
- **LUKA MODELU**: model the new use of the `threads` seam in `ModelThreading` with its
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
skips a run waiting for its Decyzja, `ended` set at the start of `Run.work`,
the actions after the result moved below `RunHost.end`, `ended` set under `_lock`
before the result is published outside it, `start` clearing the previous result from `_events`,
`Shutdown.request` without the refusal, an accepted shutdown that does not set
`_closing`, `begin_update` without the closing or the running check, `start`
without the updating check, `begin_restore` without the running check,
`start` without the restoring check, and `_busy_locked` blind to a restore. `RLock` in `RunHost` gives `LUKA MODELU`,
and so do a `RunHost` lock from `threading` beside the `threads` seam, the Uruchomienie thread from `threading` beside
it, a real lock outside `threading` held across a step of `start`, and a `PreparedRun.conduct` that waits on a real Event
before the engine.
CI runs this in the `mutations` job. A mutation reported as `NIEAKTUALNA` no longer matches its file.
Rewrite its `anchor` and `replacement` in `check_runs_mutations.py` so it breaks
the same rule again in the new code.
