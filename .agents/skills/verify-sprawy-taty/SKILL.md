---
name: verify-sprawy-taty
description: Model-check with TLA+ (TLC) the Sprawy taty (`DadCases` in `dad_cases.py`), the Zgłoszenie of one problem from „Wyślij do Maksa” to Maks's answer (`ReportHandle` and `Reports` in `reports.py`), the Uwaga taty (`send` in `dad_notes.py`) and what a delivery of the Kolejka wysyłki means for them (`_CaseDelivery` in `case_delivery.py`), under every order of the HTTP request, the queue thread `skrzynka-kolejka`, the thread `zgloszenie-skrzynka` of the Diagnoza, the Powiadomienia, failures of the Skrzynka, of `config/sprawy-taty.json` and of `Outbox.post`, and a Centrum that switches off at any step. It checks that every case that waits has its file in the queue, that a card never says „czeka w kolejce” about a Zgłoszenie whose text the Skrzynka rejected, and that once failures stop the card says what the Sprawy taty and the Skrzynka know. Use when a change touches `DadCases` (`add`, `withdraw`, `forget`, `numbered`, `rejected`, `queued`, `state`, `ask_box`, `_change`, `_load`), `ReportHandle` or `Reports` in `reports.py` (`send`, `prepare`, `_ask`, `_queue`, `_pending`, `_heard`, `_state_of`, `_ask_box`), `send` in `dad_notes.py`, `_CaseDelivery` or `case_outbox` in `case_delivery.py`, `Outbox.post`, `wait_delivered`, `resume` or `_send_all` in `outbox.py`, `StateFile` in `atomic_file.py`, `Notifications.view` or `_ask_box` in `notifications.py`, or when the check of this skill fails.
pilnuje:
  - src/rozliczenia/centrum/dad_cases.py
  - src/rozliczenia/centrum/reports.py
  - src/rozliczenia/centrum/dad_notes.py
  - src/rozliczenia/centrum/case_delivery.py
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/centrum/notifications.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-sprawy-taty/scripts/sprawdz_sprawy_taty.py
---

# Verify Sprawy taty (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_sprawy_taty.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's `pilnuje:`
or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks step.
In CI the Mutation checks step does not start while covered code differs from its digests in `model/definicje.json`: it fails with a `ROZJAZD MODELU Z KODEM | <skill>: …` line, but it cannot tell whether your change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_model_spraw_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_sprawy_taty.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line”: read the diff against the table,
change the model, break the new path in it, replay each new counterexample on the code, and recompute the digests.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

Dad clicks „Wyślij do Maksa” on the card of a Zatrzymanie, or „Wyślij” on an Uwaga taty. Centrum writes a case
without an issue number to `config/sprawy-taty.json` (`DadCases.add`), puts the text in its own file in
`config/zgloszenia/kolejka/` (`Outbox.post`), and the queue thread `skrzynka-kolejka` delivers it; the delivery gives
the case its issue number (`_CaseDelivery.delivered` → `DadCases.numbered`), and a rejected text stays in the memory of
this Centrum work (`DadCases.rejected`), because the queue tries it again only at the next start. The card shows
the state of the `ReportHandle`, and the Powiadomienia show `DadCases.state`. The docstrings promise, and the model
checks over every order of steps:

- **CzekaMaPlik**: every case that waits (no issue number, „czeka” on the card and in the Powiadomienia) has its file in
  the Kolejka wysyłki, except during the one request between `DadCases.add` and the write of its file or its
  withdrawal. Source: the `finally` of `Reports._queue` („sprawa bez pliku kolejki czekałaby wiecznie, a tata nie
  mógłby kliknąć jeszcze raz”) and the docstring of `dad_cases.py` (an Uwaga „bez numeru czeka w kolejce Skrzynki,
  dopóki `numbered` nie dopisze numeru”). Harm: the Zgłoszenie never reaches Maks, the card says „czeka w kolejce”
  forever, and `_pending` turns every later click and every return of the problem into that same answer, without a
  new file.
- **OdrzuconaNieCzeka**: once the Sprawy taty know that the Skrzynka rejected the text of the waiting Zgłoszenie in this
  Centrum work and the handle has heard it, the card does not say „czeka w kolejce”. Source: the docstring of
  `reports.py` („Zgłoszenie, którego treść Skrzynka odrzuciła, nie czeka na nic, co mógłby naprawić tata albo
  internet”) and GLOSSARY, Kolejka wysyłki (a rejected text stays until the next start; Dad should contact Maks).
  Harm: Dad waits for the internet instead of calling Maks, and `_done` returns „czeka w kolejce” for every click.
- **Zbieganie** (liveness): once failures and switch-offs stop and Centrum keeps running, the card says what the Sprawy
  taty and the Skrzynka know (a waiting case: „czeka w kolejce” or „odrzucone”; no waiting case: neither, except
  „odrzucone” about a Zgłoszenie file the Skrzynka rejected in this work), and every case with a file in the queue gets
  its issue number or the rejection. Harm: the card keeps an old state although the Skrzynka answered.

A rejected text that waits again after a start is not a broken promise: the queue tries it again (GLOSSARY), so the card says
„czeka w kolejce” until the queue's first pass of that start rejects it again.

## Why a model of its own

The model of `verify-kolejka-skrzynki` checks what happens to a queue file until the Skrzynka has it exactly once
(DOKLADNIE_RAZ, JEDNO_ISSUE, KOLEJKA_PUSTA). This path is what the queue's result means for Dad: the case in
`config/sprawy-taty.json`, its number, its rejection and the card. Here the queue is a set of files, `Outbox.post` is
one step with the result True, False or an exception, and a pass of the queue is the delivery of the oldest file the
work has not rejected, with `_settle` finding a part that is already in the Skrzynka by its mark (the box keeps
`znaczniki`). Putting both in one model would multiply two state spaces; they meet at `Outbox.post` and at the
listener calls.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/SprawyTaty.tla`, not the code. It describes the code only while you
keep the two in step. Each model action is one indivisible step of this code (`src/rozliczenia/centrum/`):

| Model action | Code |
| --- | --- |
| `Podglad` | `ReportHandle.prepare`: `_preview`, and the thread `zgloszenie-skrzynka` (`REPORT_THREAD`) starts `_ask` with the current `_sends` |
| `Pytanie` | `Reports._ask_box`: `within(search_deadline_s, _find_open)`; no answer (`Unreachable`, `NoKey`, `Refused`, the deadline) changes nothing, and an answer is dropped when `_numbered` changed meanwhile; otherwise `_open[F]` |
| `Decyzja` | `ReportHandle._ask` under `_changed`: an answer to a question from before a send is dropped (`sends != self._sends`); `_show(self._state if self._done else _state_of)`; a `StopReport` preview whose problem waits for a fix (`ReportWaiting`) goes to `Reports._queue` as a return of the problem, once (`_returned`, `_sending`) |
| `Klik` | `ReportHandle.send`: waits while `_sending`; `_done` (Sent, Queued) returns the card without a send; otherwise `_sending`, `_sends += 1` |
| `Sprawdz` | `Reports._queue`: `_pending` → `DadCases.queued`; otherwise `DadCases.add` of a `Case` without a number (`_change`: memory, then `StateFile.write`) |
| `Post` | `Reports._queue`: `self._outbox.post(post)`: True (the queue file is written), False (`OSError` in `Outbox.post`) or an exception |
| `Wycofaj` | `Reports._queue`, `finally: if not queued: self._cases.withdraw(case)`; then `ReportNotQueued`, or the exception goes up and `send` clears `_sending` without a new state |
| `Czekaj` | `Reports._queue`: `Outbox.wait_delivered(... DELIVERY_WAIT_S)` → Sent, else `DadCases.queued` (checks `_rejected` under the lock, then `KeyedBox.judge`) |
| `Pokaz` | `ReportHandle.send` under `_changed`: `_sending = False`; Queued with `not _pending` → Sent; `_show(state)` |
| `UwagaWyslij` | `dad_notes.send`: `cases.add(note)` |
| `UwagaPost` | `dad_notes.send`: `outbox.post(note_post(...))`; after True `wait_delivered` and `queued` give the state only to Dad's request |
| `UwagaZapomnij` | `dad_notes.send`: `cases.forget(NOTE, note.id)` after False, then `refusal.note_not_queued` |
| `Doreczenie` | `Outbox._send_all` for the oldest file not in `_rejected`: `_deliver` (with `_settle`); a failure that stops the pass (`_stop`, `RETRY_S`); a rejected text (`_rejected`, `_rejected_posts`, `Listener.rejected` → `_CaseDelivery.rejected` → `DadCases.rejected`: `_rejected` under the lock); a delivery (`Listener.delivered` → `_CaseDelivery.delivered` → `_case` → `DadCases.numbered` with its `_change`) |
| `Uslyszane` | `DadCases._tell` in the queue thread, outside the lock of the cases: `Reports._heard` (`_open`, `_numbered`) and every live handle of the problem: `ReportHandle._delivered` or `_rejected` |
| `Oznacz` | `_send_all` after `delivered`: `_first_comments` (wakes `wait_delivered`), `_mark_delivered`, `_remove` |
| `Powiadomienia` | `Notifications.view`: `StateFile.retry`, and the thread of the check (`_start_check_if_due`) runs `Notifications._ask_box` → `DadCases.ask_box` → `_close` through `_change` |
| `MaksZamyka` | Maks closes an issue in the Skrzynka |
| `Zgasniecie` | none: Centrum switches off at any step and Dad opens it again: memory is gone (`DadCases._rejected`, `Outbox._rejected`, `_first_comments` of this work, the handle), `DadCases._load` reads `config/sprawy-taty.json`, `Outbox.resume`, and the card of a Zatrzymanie of this problem gets a new handle with `Reports._state_of`. No code reconciles the cases with the queue files after a start |

`model/definicje.json` holds the digests of the definitions the table names: `CaseKind`, `Case`, `DadCases.add`,
`withdraw`, `forget`, `find`, `numbered`, `rejected`, `_tell`, `queued`, `state`, `ask_box`, `_close`, `_change` and
`_load` in `dad_cases.py`; `ReportHandle.__init__`, `prepare`, `_ask`, `send`, `_rejected`, `_delivered`, `_done`,
`_show`, `Reports.__init__`, `handle`, `_heard`, `_queue`, `_pending`, `_ask_box` and `_state_of` in `reports.py`; `send`
in `dad_notes.py`; `case_outbox`, `_CaseDelivery.delivered`, `_CaseDelivery.rejected` and `_case` in `case_delivery.py`;
`Outbox.resume`, `post`, `wait_delivered`, `_send_all` and `_mark_delivered` in `outbox.py`; `StateFile` in
`atomic_file.py`; `Notifications.view` and `_ask_box` in `notifications.py`. Left out on purpose: the text of a
Zgłoszenie and of an Uwaga (`_preview`, `note_issue`, the guard), `_CaseDelivery.prepare` (the line of the Logs in a
pinned Uwaga, which changes no case), `KeyedBox.judge` (which of „na internet” and „na Token” the waiting case shows),
and `Reports._find_open` (one call of the Skrzynka). Two changes move the model without changing a definition, so look for
them in the diff: a new caller of `DadCases.add`, `withdraw`, `forget` or `numbered` outside these definitions, and a
second handle of one problem in one Centrum work (`stops.py` makes one per Zatrzymanie, `tool_updates.py` one per failed
Aktualizacja). Add such code to the table and to `model/definicje.json`.

The digests in `model/definicje.json` were taken when every row of the table was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests. To see what
changed since: `git diff $(git log -1 --format=%h -- .agents/skills/verify-sprawy-taty/model/definicje.json) --
<files of model/definicje.json>`.

## Run

```sh
.venv/bin/python .agents/skills/verify-sprawy-taty/scripts/sprawdz_sprawy_taty.py
py -3 .agents\skills\verify-sprawy-taty\scripts\sprawdz_sprawy_taty.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. The run of TLC, the verdict and the
known findings are `tools/lib/model_tlc.py`; Java and `tla2tools.jar` come from `tools/lib/narzedzia_tlc.py`. The whole
check took 24 s on Maks's Mac on 2026-11-12 (11 known findings in 16 TLC runs).

The last line is the verdict:

- `SPRAWY TATY OK` or `SPRAWY TATY OK, ZNANE ZNALEZISKA: n`: every configuration ends as `model/konfiguracje.json` says
  (n counts each known finding in each configuration). Exit 0 (1 with `--strict` and known findings).
- `SPRAWY TATY: NOWE NARUSZENIE (n)`: a promise breaks on a path that is not a known finding, or Zbieganie breaks. Exit 1.
- `SPRAWY TATY: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change below and remove it
  from `znane` of its configuration in `model/konfiguracje.json`. Exit 1.
- `SPRAWY TATY: BŁĄD MODELU (n)`: TLC gave no verdict, `TypeOK` broke, `model/konfiguracje.json` has another shape, or
  the script's story does not know every action of `Next`. Exit 2.
- `UWAGA: kod opisany modelem zmienił się: …` above the verdict: a definition in `model/definicje.json` differs from its
  digest there, and the verdict means nothing until you bring the model in line.

Each counterexample is told as numbered steps in the code's words, with every change of the card, and ends with the
card, the cases in memory and in `config/sprawy-taty.json`, and the queue.

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/SprawyTaty.tla` and one configuration with the
`Wybaczone…` constants as they are (empty), and a view whose regions are Centrum, the card and the queue. It shows each
broken promise as its shortest path in plain words; for a configuration of one click, no Uwaga and one switch-off it
also draws the whole chart of how one Zgłoszenie moves between „gotowe”, „czeka w kolejce”, „wysłane”, „odrzucone” and
„czeka na naprawę”.

Then tell a real bug from a modeling error: replay the path on the code, one step per action. The tests of the handle in
`tests/test_centrum_uchwyt_zgloszenia.py` build one Centrum work without the app (`Computer.reports()`: `DadCases`,
`case_outbox`, `Reports` on a `FakeReportBox`); a second call is the next start. A switch-off inside a step is a process
of its own that ends with `os._exit` at that step (for the write of the queue file: `Path.write_text` of a path in
`config/zgloszenia/kolejka`), and the next start is the same folder in a new process. A failed write of
`config/sprawy-taty.json` is a folder in place of `sprawy-taty.json.tmp`. A step of the queue thread between two steps of
a request is the `KeyedBox.judge` of `DadCases.queued` replaced for the test, as in
`test_dostarczenie_tuz_po_koncu_czekania_na_skrzynke_daje_stan_wyslane`; a rejected text is `Rejected()` in
`FakeReportBox.outcomes`. A path that does not happen on the code means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two clicks, one Uwaga, one switch-off, the Skrzynka once without an answer, Maks closes one issue | known `zgasniecie-w-wysylce-zgloszenia`, `zgasniecie-w-wysylce-uwagi` |
| `odrzucona` | two clicks, one switch-off, the Skrzynka once without an answer, one text the Skrzynka rejects | known `zgasniecie-w-wysylce-zgloszenia`, `pokaz-po-odrzuceniu` |
| `plik-stanu` | one click, one Uwaga, one switch-off, one failed write of `config/sprawy-taty.json` | known `zgasniecie-w-wysylce-zgloszenia`, `zgasniecie-w-wysylce-uwagi`, `plik-stanu-niedostepny` |
| `kolejka` | two clicks, one Uwaga, one switch-off, `Outbox.post` once False and once an exception | known `zgasniecie-w-wysylce-zgloszenia`, `zgasniecie-w-wysylce-uwagi` |
| `powrot` | two clicks, two switch-offs, the Skrzynka once without an answer, one rejected text, Maks closes one issue: the return of the problem after a start | known `zgasniecie-w-wysylce-zgloszenia`, `pokaz-po-odrzuceniu` |

## Known findings

A configuration forgives only the findings `model/konfiguracje.json` lists for it (`znane`), each only for its promise
and only for an event that happened with its cause (the history variables `bezPliku` and `odrzuconaCzeka` record the
causes at every event). Zbieganie forgives only a card whose one disagreement is a forgiven `pokaz-po-odrzuceniu`
(`KartaZnana`). All four findings were replayed on the code on 2026-11-12 (main at d0cefa5ef), each with a scratch script
outside the repository: a first Centrum work in its own process, killed with `os._exit` at the step, and a second start
on the same folder.

1. **`zgasniecie-w-wysylce-zgloszenia`, CzekaMaPlik (open).** Dad clicks „Wyślij do Maksa”; `Reports._queue` runs
   `self._cases.add(case)`, which writes the case without a number to `config/sprawy-taty.json`, and Centrum switches off
   before `self._outbox.post(post)` wrote the queue file (or after False and before `withdraw`). The `finally` does not
   run in a dead process. After the start the case waits without a file: `Reports._state_of` gives „czeka w kolejce”,
   `send` returns it at once (`_done`), a new handle's `_queue` stops at `_pending` and returns `DadCases.queued`, and
   the return of the problem after a Diagnoza stops there too. Nothing after a start compares the cases with the queue.
   Harm: this problem never reaches Maks again from this computer, and the card says „czeka w kolejce, wyjdzie samo”
   forever. The window is the write of the queue file (`replace_atomically`, on Windows up to 0.75 s of pauses on a
   refused rename). Replayed: card after the start `{'state': 'queued', 'waits_for': 'internet'}`, „Wyślij do Maksa”
   the same, no queue file, no Zgłoszenie in the Skrzynka.
2. **`zgasniecie-w-wysylce-uwagi`, CzekaMaPlik (open).** The same window in `dad_notes.send` between `cases.add(note)`
   and `outbox.post(...)`. The Uwaga waits in the Powiadomienia forever, and its text is nowhere: the case keeps only the
   title. Dad can write a new Uwaga, so nothing is blocked. Replayed: after the start the Powiadomienie of the Uwaga is
   `queued`, no queue file, no issue.
3. **`plik-stanu-niedostepny`, CzekaMaPlik (open).** The queue delivers the Zgłoszenie or the Uwaga, `DadCases.numbered`
   cannot write `config/sprawy-taty.json` (`StateFile` keeps the number in memory and retries at the next change or
   view of the Powiadomienia), the queue removes the delivered file, and Centrum switches off before the next write.
   After the start the case waits without a file, as in 1, although Maks has the issue; the card never shows Maks's
   answer. A failed write plus a switch-off before the next change. Replayed for a Zgłoszenie with a folder in place of
   `sprawy-taty.json.tmp`: the Skrzynka has the Zgłoszenie, the file still says `"number": null`, the card after the start
   is `queued`.
4. **`pokaz-po-odrzuceniu`, OdrzuconaNieCzeka (open).** `ReportHandle.send` gets „czeka w kolejce” from
   `DadCases.queued` (the text was not rejected yet), the queue thread rejects the text and the handle shows
   „odrzucone” (`_rejected`), and then `send` takes `_changed` and shows its older result: it checks `_pending` for a
   delivery that came meanwhile, but not `_rejected`. The card says „czeka w kolejce” until the next start, and every
   click returns it (`_done`). Replayed by replacing `KeyedBox.judge` (called by `DadCases.queued` after `_rejected`) with
   one that lets the queue reject the text first: the card showed `ready`, `rejected`, `queued`; the second click
   returned `queued`; `DadCases.queued` said `rejected`. Without such a hook the window is microseconds.

Decide 1–4 with Maks; when the code changes, the finding disappears and the check says `ZNALEZISKO ZNIKNĘŁO`.

One path is no finding: after a switch-off between the delivery of a Zgłoszenie file and its removal, the next start
delivers that old file again (`_settle` finds its mark in issue N), and `DadCases.numbered` gives N to the newest
waiting case of the problem, which disappears because another case already has N; when that newer case's own file has a
rejected text, the card says „odrzucone” while the Sprawy taty have no waiting case. The card tells the truth about the
Skrzynka, so `KartaZgodna` allows „odrzucone” while such a file is in the queue.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   TLA+ strings must be ASCII; comments may use Polish letters. Never weaken a promise or narrow a configuration to make
   the check pass.
3. A new way to fail gets a constant, a branch guarded by it, and a value in `stale` of every configuration in
   `model/konfiguracje.json`. A new action of `Next` gets its words in `_STEPS` of the script.
4. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_spraw_mutations.py` with the code counterpart in its name.
5. Run the check. A new violation is a finding: replay it on the code (Read a result) before you call it a bug, report
   it with the path, and do not change product code unless asked.
6. Run `tools/przesun_model.py verify-sprawy-taty` only after every row of the table describes the code, and write in
   the commit message, in one sentence, what changed in the model and why.

## After changing the model

`.venv/bin/python .agents/skills/verify-sprawy-taty/scripts/check_model_spraw_mutations.py` applies each broken variant
of the model to a copy of the checkout (`tools/lib/silnik_mutacji.py`) and must end with `MUTACJE OK`; run it only to
reproduce a red Mutation checks step or while you change the model. Each mutation removes a guard the code has, and
each gives `SPRAWY TATY: NOWE NARUSZENIE`:

- CzekaMaPlik: `Reports._queue` without `finally` (`kolejka`); `dad_notes.send` without `cases.forget` (`kolejka`);
  `_CaseDelivery.delivered` without `DadCases.numbered` (`zwykle`).
- OdrzuconaNieCzeka: `DadCases.queued` without `_rejected` (`odrzucona`); `ReportHandle._rejected` without `_show`
  (`odrzucona`).
- Zbieganie: `ReportHandle._delivered` without `_show` (`zwykle`); `ReportHandle.send` without the `_pending` check after
  the wait (`zwykle`: the number comes between `DadCases.queued` and the end of `send`).

## Scope

Verified: the three promises over every order of the actions above within the bounds of each configuration (one
problem with one handle per Centrum work, at most two clicks, at most one Uwaga, one or two switch-offs, at most one
failure of each kind, one rejected text, one closure by Maks). Assumed, each a reason the check can pass while the code
is wrong:

- **The queue delivers as `verify-kolejka-skrzynki` checks**: a file with no mark in the Skrzynka gets one issue
  (JEDNO_ISSUE), a file whose mark is there gets the same number (`_settle`), a rejected text is rejected again at every
  start, and the oldest file goes first.
- **`os.replace` is atomic** (`StateFile`, queue files): a switch-off leaves the old file or the new one.
- **One handle of the problem per Centrum work.** Two Zatrzymania of one problem in one work give two handles whose
  `_queue` may both pass `_pending` before either adds its case; the model has one.
- **`DadCases._tell` reaches the handle in the queue thread before `_first_comments`**, as `_send_all` calls the listener
  first.

Left out: the text of a Zgłoszenie or an Uwaga and its guard, which of „na internet” and „na Token” a waiting case shows,
the Logs line of a pinned Uwaga (`_CaseDelivery.prepare` and the comment after rejected Logs), an unreadable queue file
(it stays, so the case keeps its file), a queue file whose removal failed, an unreadable `config/sprawy-taty.json` (no
cases at all: their files are delivered and number nothing), the old files before one store (`OLD_REPORTS_FILE`,
`OLD_NOTES_FILE`), an exception other than `OSError` from `Outbox.post` in `dad_notes.send` (no `finally` there; no
known path raises one), and Maks reopening an issue.

## Files

- `model/SprawyTaty.tla`: the model, with the code each action describes.
- `model/konfiguracje.json`: the configurations (description, constants and known findings; the script writes each
  `.cfg` with `TypeOK` and every promise), `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_sprawy_taty.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_spraw_mutations.py`: proves the check fails when the model loses a guard the code has.
