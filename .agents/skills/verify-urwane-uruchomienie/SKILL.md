---
name: verify-urwane-uruchomienie
description: Model-check with TLA+ (TLC) the trail of a Wycena w efenix that a switched-off Centrum cut short, across the next starts of Centrum, the Dziennik Wyceny in `logs/dzienniki-wyceny/` (`pricing_journal.py`), the Logi Urwanego Uruchomienia (`RunLogs.interrupted`, `guard`, `close`, `send` in `run_logs.py`) and their way into the Kolejka wysyłki (`Outbox.post`). It checks that a journal disappears only after the queue accepted its Logi, that a Wycena with a result never gets Logi Urwanego Uruchomienia, that the Logs file and what goes to the queue have the same characters and passed the guard, that nothing reaches the queue before `Outbox.resume`, and that every order the Wycena changed in efenix is in its Logi, under every order of switch-offs and failed reads and writes. Use when a change touches `PricingJournal`, `_read` or `InterruptedPricings` in `src/rozliczenia/centrum/pricing_journal.py`, `RunLogs` or `RunLog.interrupted` or `guarded` in `run_logs.py`, `RunCards.recorded` or `_row` in `run_cards.py`, `lifespan` or `send_interrupted` in `app.py`, `_Run.work` in `runs.py`, `run_process` in `process_run.py` or `MetricsStore.append` in `telemetry.py` (the Historia row), the journal calls in `efenix_pricing.py` `save`, or when the check of this skill fails.
pilnuje:
  - src/rozliczenia/centrum/pricing_journal.py
  - src/rozliczenia/centrum/run_logs.py
  - src/rozliczenia/centrum/run_cards.py
  - src/rozliczenia/centrum/metrics.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/process_run.py
  - src/rozliczenia/telemetry.py
  - .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
ci: .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
---

# Verify Urwane Uruchomienie (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_urwane_uruchomienie.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step. It fails with `URWANE URUCHOMIENIE: ROZJAZD MODELU Z KODEM` when a definition the model describes
(`model/definicje.json`) changed since the Sync commit, but it cannot tell whether your change to the model is right.
`check_model_urwanego_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_urwane_uruchomienie.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line”: read the diff against the table,
change the model, break the new path in it, replay each new counterexample on the code, and move the Sync commit.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

Wycena w efenix runs up to an hour and a half, and the Logi Uruchomienia exist only at its end. When Centrum switches
off in the middle (power cut, a closed console, a killed process), the only trace of what the tool already changed in
efenix is the Dziennik Wyceny w efenix, one file per Uruchomienie. The next start of Centrum turns it into Logi Urwanego
Uruchomienia and sends them to Maks through the Kolejka wysyłki. The docstring of `pricing_journal.py` promises, and the
model checks over every order of steps:

- **DziennikPoKolejce**: a journal of an Urwane Uruchomienie (it has its first line and the Wycena has no Historia row)
  disappears only after `Outbox.post` accepted its Logi. With **Zbieganie** this is „wysyłka co najmniej raz”.
  Harm: Maks never learns that a Wycena stopped half-way and which order was in progress in efenix.
- **BezUrwanychPoWyniku**: Logi Urwanego Uruchomienia are made only for a Wycena that did not reach its result
  (`run_process` returned with a result, whether or not its Historia row was written); the journal of a Wycena with a
  result is removed. Harm: Maks reads „Centrum zamknęło się w trakcie” about a Wycena that
  finished, and in the Skrzynka these Logi replace the Logi with the result (same `run_id` and label, newer version).
- **TeSameZnaki**: the Logi go to the queue with the same characters as the Logs file on Dad's disk. Harm: the file in
  the Archiwum Logów okresu and the file at Dad's differ, so a replay from either (#847) sees another Uruchomienie.
- **PrzezStraznika**: the Logi go to the queue only after the guard of the data rule (`RunLogs.guard`, ADR 0025).
  Harm: a phone number or a street from an efenix page leaves Dad's computer.
- **NicPrzedWznowieniem**: nothing goes to the queue in a Centrum work before its `Outbox.resume`. This is the
  precondition the model of `verify-kolejka-skrzynki` assumes for every `post`.
- **ZaczeteWLogach**: every order the Urwana Wycena changed in efenix is in its Logi, as finished or as the order begun
  without a result (`interruption`). Harm: Maks does not know which order may be half-priced in efenix.
- **Zbieganie** (liveness): once failures stop and Dad keeps closing and opening Centrum, every journal disappears.
  Harm: `logs/dzienniki-wyceny/` grows forever, or every start sends the same Logi again.

## Why a model of its own

The model of `verify-kolejka-skrzynki` checks what happens to a queue file until the Skrzynka has it exactly once. This
path ends where that one begins: at `Outbox.post` returning True. Here the queue is a set of accepted wysyłki, and the
state is the journals, Logs files and Historia rows on Dad's disk across Centrum starts. Putting both in one model would
multiply a state space that already takes 45 s, so the two models meet at one step: this one checks that the journal
path calls `post` only after `Outbox.resume` and keeps the journal until `post` accepted, and the queue model checks
the rest.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/UrwaneUruchomienie.tla`, not the code. It describes the code only
while you keep the two in step. Each model action is one indivisible step of this code (`src/rozliczenia/centrum/`
unless named otherwise):

| Model action | Code |
| --- | --- |
| `Start` | `launcher.py` `_start`: `_listen_when_released` takes the port, then `create_app`; in it `InterruptedPricings(...).close()` lists `sorted(glob("*.jsonl"))`. Only the process with the port builds the app, so two closes never run at once |
| `Czytaj` | `InterruptedPricings.close` → `_closed(path)` for one journal: `pricing_journal._read` (no first line → `None`), `RunLogs.file_of` and `RunLog.model_validate_json` (`ending != "interrupted"` → `None`; `"interrupted"` → the record from the file), else `RunCards.recorded` → `_row` (earliest Historia row of the process with `started_at >=` the journal's start; `OSError` → no row), else `RunLogs.interrupted`; then `RunLogs.guard`. An `OSError` from the journal or the Logs file is caught by `close`, which leaves the journal. One step, because nothing else writes these files while `create_app` runs |
| `ZapiszLogi` | `_closed`: `RunLogs.close(record)` → `_write` → `atomic_file.replace_atomically`; `OSError` only to the Centrum log, and the record still goes to `_pending` |
| `UsunDziennik` | `close`: `if closed is None: self._remove(path)` (`unlink`; `OSError` leaves the journal) |
| `Wznow` | `app.py` `lifespan`: `outbox.resume()` before uvicorn accepts the first request |
| `PierwszeZapytanie` | `app.py` `send_interrupted`, a dependency of every API route, → `InterruptedPricings.send`: `pending, self._pending = self._pending, []` |
| `Wyslij` | `send`: `self._run_logs.send(record)` → `outbox.py` `Outbox.post(logi_post(record))`: True once the queue file exists, False leaves the journal for the next start |
| `UsunPoWysylce` | `send`: `self._remove(path)` after True |
| `StartWyceny` | `runs.py` `RunHost.start` → `app.py` `run_started` → `PricingJournal.run_started` (start in memory, first line pending) |
| `WpisZaczete` | `efenix_pricing.py` `save`: `journal.begun(...)` before `efenix_trace.traced` and `_priced` → `PricingJournal._write` (first line and entry in one `write`, `flush`, `fsync`; `OSError` drops the entry, `_header` stays) |
| `ZmianaWEfenix` | `_priced` → `_outcome`: the first window action that changes the order (execution date, Wycena Emmetta, a quantity) |
| `WpisSkonczone` | `save`: `journal.ended(result, ...)` after the result → `PricingJournal._write` |
| `Historia` | `runs.py` `_Run.work` → `process_run.py` `run_process`: the engine reached its result, and `MetricsStore(...).append(record)` (`telemetry.py`) writes the metrics record (the Historia row) before `run_process` returns; `OSError`, `UnicodeError` or `ValueError` from `append` is caught (`metrics_saved = False`), and `run_process` returns its result without a Historia row |
| `LogiWyniku` | `_Run.work` → `RunHost.after` → `RunLogs.run_ended` → `_keep`: `_write` of the Logs with the result |
| `WyslijWynik` | `_keep`: `finally: self._outbox.post(logi_post(kept))`, then the end of the Uruchomienie; the journal stays until the next start |
| `Zgasniecie` | none: Centrum switches off at any step; memory is gone, disk and queue stay; an entry being written may be torn, and a torn first line is a journal without a start |
| `Zamkniecie` | „Zamknij Centrum rozliczeń”: `RunHost.shutdown_refusal` accepts it only when no Uruchomienie runs, and the request passed `send_interrupted` first |

The script compares these definitions with the Sync commit (`model/definicje.json`: file → names, `Class.method` is a
method): `PricingJournal`, `_read`, `InterruptedPricings` in `pricing_journal.py`;
`RunLog.interrupted`, `guarded`, `RunLogs.run_ended`, `_keep`, `interrupted`, `file_of`, `guard`, `close`, `_write`,
`send`, `LoggedEnding`, `logi_post` in `run_logs.py`; `RunCards.recorded`, `_row` in `run_cards.py`; `read_runs`,
`_records`, `_runs`, `_run` in `metrics.py` (the Historia that `_row` reads); `lifespan`, `send_interrupted`, the
assignments `app` and `interrupted` and `run_started` in `app.py`; `_Run.work`, `RunHost.start`, `RunHost.after`,
`RunHost.shutdown_refusal` in `runs.py`; `Outbox.post`, `Outbox.resume` in `outbox.py`; `_start`,
`_listen_when_released` in `launcher.py`; `replace_atomically` in `atomic_file.py`; `save` in `efenix_pricing.py`;
`run_process` in `process_run.py`; `MetricsStore.append`, `MetricsStore.read` in `telemetry.py`. Every code name in the
table above is one of them, except three left out on purpose: `RunLog` as a whole (the schema of the Logs file, which
changes with every new field; the model reads only `ending`, whose values are `LoggedEnding`), `_priced` and `_outcome`
(`ZmianaWEfenix` needs only that `save` calls `journal.begun` before them, which `save` holds), and `create_app` (see
below). A change elsewhere in these files does not move the model. Two
changes move it without changing a definition, so look for them in the diff: the call `interrupted.close()` in
`create_app` leaving its place right after `interrupted = InterruptedPricings(...)`, and a new caller of
`InterruptedPricings` or of `RunLogs.send` outside these definitions. Add such code to the table and to
`model/definicje.json`. The table lives in data, not in the script, because a path named in the script would make the
change-impact selection (`tools/lib/wplyw_zmiany.py`) run the test of the script on every change of `app.py` or
`atomic_file.py`, although that test builds its own files.

Sync commit: `ef64b4a67` (2026-11-05, PR #863 after its merge of `main` with #883).
Every row of the table was checked against the code at this commit. The model did not change: #863 makes `guarded` mask
also numbers in the fields with values from Dad's cells (`READ_VALUES`) and the phone with `48` without `+`, and puts
the notes about the Kopia wejścia in `input_copy_notes`, but `RunLogs.guard` still calls it in one step and it stays
idempotent (`Straz`). The fix of #881 (#883) changed `save` only in what it passes to `_priced` (the pace, which
`_priced` now puts over its write-ahead window) and in the facts of a Zatrzymanie, while `journal.begun` still comes
before `efenix_trace.traced` and `_priced`, and `journal.ended` after the result. Each known finding below was replayed
at `5e1905142` (`historia-niezapisana` on `main` 86677b151, whose `src/` is the same); #863 changes none of the code
they run through except the guard, which only masks more.

## Run

```sh
.venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
py -3 .agents\skills\verify-urwane-uruchomienie\scripts\sprawdz_urwane_uruchomienie.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. Java and `tla2tools.jar` come from
`verify-aktualizacja-narzedzia` (`sprawdz_aktualizacje.py` installs pinned `jdk4py` and the jar into `.verification/`
on first use; `TLC_JAVA` and `TLC_JAR` override them). The whole check took 27 s on Maks's Mac on 2026-11-05, most of
it the five TLC runs of `wszystko` (647 737 distinct states in 14 s in the run with its four known findings excused;
with two switch-offs instead of one it also passes, 2.42 million distinct states in 45 s).

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
or a journal written with `JournalStarted`, `OrderBegun` and `OrderEnded`, as in
`test_logi_urwanego_uruchomienia_w_pliku_i_w_skrzynce_przechodza_przez_straznika_reguly_danych`. A start is
`centrum.restart()`, which builds the app with `create_app` in the test process, so a failed read during one start is
`monkeypatch` of `Path.read_text` (journal) or `Path.open` with mode `"r"` (the efenix metrics file,
`centrum.engines.metrics.efenix`) for that path only, around `restart()`. A failed write is a file in place of the
folder (`logs/uruchomienia`, `logs/dzienniki-wyceny`) or a folder in place of the temporary file
(`<Logs file>.tmp`), and a failed metrics record is `monkeypatch` of `MetricsStore.append` raising `OSError` during the
Wycena. A path that does not happen on the code means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two Wyceny of two orders, two switch-offs anywhere, no other failure | passes |
| `odczyt` | two Wyceny of one order, one switch-off, one start that cannot read a journal | known `wiersz-pozniejszej-wyceny` |
| `logi-i-kolejka` | two Wyceny, one switch-off, one failed write of a Logs file, one `post` False, one failed `unlink` | known `wiersz-pozniejszej-wyceny` |
| `historia` | two Wyceny, one switch-off, one start that cannot read the Historia, one failed write of the metrics record, one failed write of a Logs file | known `historia-nieczytelna`, `historia-niezapisana` |
| `wpisy` | one Wycena of two orders, one switch-off, one journal entry that fails | known `wpis-nieudany` |
| `stare-logi` | Wycena 1 already cut, its Logi Urwanego Uruchomienia written without the guard and not sent, one more Wycena, one switch-off, one failed write of a Logs file | known `zapis-logow-nieudany` |
| `wszystko` | two Wyceny of two orders, one switch-off and one failure of every kind | the four known findings of `odczyt`, `historia`, `wpisy` |

## Known findings

A configuration forgives only the findings `model/oczekiwane.json` lists for it, each only for its promise and only
for an event that happened with its cause (the history variables `zgubiony`, `poWyniku`, `inneZnaki`, `bezZlecenia`
record the causes at every event); any other path is a new violation. Each cause is pinned to what the finding is
about: `wpis-nieudany` to the orders whose own entry failed (`przepadle`), so an order missing from the Logi whose
entries were written is a new violation; `historia-nieczytelna` and `historia-niezapisana` to a Wycena without a Logs
file with its result, so a Wycena whose Logs with the result exist and still gets Logi Urwanego Uruchomienia is a new
violation. Each finding has its own run without the other known findings of its configuration, and the configuration
one run without all of them. All five were replayed on the code.

1. **`wiersz-pozniejszej-wyceny`, DziennikPoKolejce (open, a real defect, #870).** Path (`odczyt`): Wycena 1 writes
   „zaczynam zlecenie”, Centrum switches off; the next start cannot read journal 1 (`OSError`, `close` leaves it for
   the next start, line `dziennik-wyceny-niedostepny miejsce=start`); in that Centrum work Wycena 2 reaches its result
   (Historia row, Logs, `post`); the start after that finds journal 1 without Logs, and `RunCards.recorded` →
   `_row` returns Wycena 2's Historia row, because its start is later than Wycena 1's; `close` removes journal 1.
   No Logi Urwanego Uruchomienia of Wycena 1 exist on the disk or in the Skrzynka. The same happens after a failed
   write of the Logs file together with `post` False in one start (`logi-i-kolejka`). The rule „first row from the
   start” in `_row` is right for the last started Uruchomienie (ADR 0017), but `close` applies it to every journal.
   Replayed with a journal of Wycena 1 written by hand, `Path.read_text` of that journal raising `PermissionError`
   during one `restart()`, a real Wycena 2 on the Atrapa efenix, and another `restart()`: the journal is gone, the only
   Logs file and the only comment of Logs are Wycena 2's, the queue folder is empty. Without the failed read the
   replay diverges at step 2 (Wycena 1's Logi reach the Skrzynka).
2. **`wpis-nieudany`, ZaczeteWLogach (accepted).** A journal entry that fails (`OSError`) loses the entry, the Wycena
   goes on and changes the order in efenix, and when Centrum switches off then, no Logi name that order (or no journal
   exists at all). Only the order of the lost entry: `_write` tries every next entry again (`_failed` only silences
   the second line in the Centrum log), so every other order the Wycena changed is in the Logi. The docstring of `pricing_journal.py` accepts it: „Nieudany zapis wpisu to jedna linia dziennika
   Centrum na Uruchomienie, a Wycena biegnie dalej: ślad jest dla Maksa, a nie warunkiem pracy taty”. Replayed with a
   file in place of `logs/dzienniki-wyceny`, a real Centrum process killed after the Atrapa had a change: after the
   restart there is no journal and no Logs file.
3. **`historia-nieczytelna`, BezUrwanychPoWyniku (open, a real defect, #871).** A Wycena has its Historia row but no Logs file (Centrum
   switched off between the metrics record and the Logs, or `_write` failed), and the next start cannot read the
   Historia (`_row`: `OSError` → no row), so `close` makes Logi Urwanego Uruchomienia of a Wycena with a result.
   Replayed with a file in place of `logs/uruchomienia` during Wycena 1 (its Logs with the result reach the Skrzynka
   through `_keep`'s `finally`), then `Path.open` of the efenix metrics file raising `PermissionError` during one
   `restart()`: the Skrzynka's only comment of Logs of Wycena 1 now leads to Logi with `ending` `interrupted` and
   `result` `None`, and the Logs file on the disk says the same.
4. **`zapis-logow-nieudany`, TeSameZnaki (open, cannot happen at Dad's yet).** Logi Urwanego Uruchomienia written by a
   Centrum work before the guard (#851) and not sent: the start guards them, `RunLogs.close` fails (`OSError`), and the
   queue gets the masked text while the file keeps the phone number. No Wydanie has the journal (#845) without the
   guard (v0.4.3 has neither), so no such file exists at Dad's. Logi written by a guard that masks less are the same
   case: a Wydanie with the journal and the guard from before #863 would leave a phone `48600123456` in the file and
   `[telefon]` in the Archiwum after a failed `close`. Replayed with such a file and a folder in place of its
   `.tmp`: the file has `600 123 456`, the file in the Archiwum `[telefon]`.

5. **`historia-niezapisana`, BezUrwanychPoWyniku (open, a real defect, #871).** Same harm as 3, another cause: no
   start fails to read anything. `run_process` catches the failed write of the metrics record (`MetricsStore.append`
   raises `OSError`, `UnicodeError` or `ValueError`, `metrics_saved = False`) and returns the result without a
   Historia row, and the Logs file with the result is not there either (`_write` failed, or Centrum switched off before
   it). The next ordinary start finds the journal without Logs and without a Historia row, takes the Wycena for an
   Urwane Uruchomienie and sends its Logi with the same `run_id`. Replayed with `MetricsStore.append` raising
   `OSError(28)` and a file in place of `logs/uruchomienia` during Wycena 1 (its Logs with the result reach the
   Skrzynka through `_keep`'s `finally`), then a plain `restart()`: the Skrzynka's only comment of Logs of Wycena 1
   leads to Logi with `ending` `interrupted` and `result` `None`, and so does the Logs file. With the metrics record
   written the same steps keep the Logs with the result and remove the journal.

Decide 1 (#870), 3 and 5 (#871) and 4 with Maks; when the code changes, the finding disappears and the check says
`ZNALEZISKO ZNIKNĘŁO`.

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

- DziennikPoKolejce: the journal removed although `post` returned False (`send` without `if
  self._run_logs.send(record)`, `logi-i-kolejka`); Logi Urwanego Uruchomienia from the file taken for Logi with a
  result (`_closed` without `logged.ending != "interrupted"`).
- BezUrwanychPoWyniku: `_closed` without `elif self._recorded(...)`; `_closed` without `return None` for Logs with a
  result, so the Historia decides alone (`historia`: a Wycena whose metrics record failed or whose Historia the start
  cannot read gets Logi Urwanego Uruchomienia although its Logs with the result exist).
- TeSameZnaki: the Logs file written before the guard (`guard` after `RunLogs.close`).
- PrzezStraznika: `_closed` without `record = self._run_logs.guard(record)`.
- NicPrzedWznowieniem: the Logi sent in `create_app` right after `close`, not in the dependency of the first request.
- ZaczeteWLogach: `_read` without the order begun without a result; `journal.begun` after the first window action;
  `PricingJournal._write` starting with `if self._failed: return` (`wpisy`: after one failed entry the journal writes
  nothing more, so an order without a failed entry of its own is missing from the Logi).
- Zbieganie: `send` without `self._remove(path)`; `close` without `if closed is None: self._remove(path)`.

A mutation reported as `NIEAKTUALNA` no longer matches the model: rewrite its anchor against the new model so that it
breaks the same rule again.

## Scope

Verified: the seven promises over every order of the actions above within the bounds of each configuration (one or two
Wyceny started one after the other, one or two orders each, one or two switch-offs, at most one failure of each kind),
with Dad opening and closing Centrum as often as he likes. Assumed, each a reason the check can pass while the code is
wrong:

- **`os.replace` is atomic** (`replace_atomically`): a switch-off leaves the old Logs file or the new one.
- **One Centrum at a time builds the app**: `_listen_when_released` takes the port before `create_app`, and the old
  Centrum, which may still finish requests for `_GRACEFUL_SHUTDOWN_S` after it released the port, runs no Uruchomienie
  then (`shutdown_refusal`). A second process that bypassed the port would close the journal of a Wycena still running.
- **`send` runs atomically** on the event loop (`async def` without `await`), and the first request of a work comes
  before any Wycena of that work, because every route has the dependency.
- **The guard is idempotent**: Logs that passed `guard` pass it again unchanged, so rereading a file written by `close`
  changes nothing; only Logs written without the guard (`StareLogi`) change. A number the guard masked becomes the text
  of its mask, which it leaves as it is. Idempotent means one version of the guard: Logs written by a Centrum whose
  guard masked less (before #851 nothing, before #863 the phone with `48` without `+`) are `StareLogi` for a newer one.
- **`RunLog.model_validate_json(text).text == text`** for a file `close` wrote, and two builds of the same journal give
  Logs with the same orders; their environment, tool and Dad's actions may differ, which the model leaves out. A rebuild
  happens only when the file is missing, so the file and the newest accepted Logi stay the same, unless the clock went
  back between two Centrum works (the queue's version order, `verify-kolejka-skrzynki`).

Left out: a glob of `logs/dzienniki-wyceny/` that fails (it skips every journal, like one failed read per journal), a
Logs file that cannot be parsed (truncated by hand, a schema from a newer version after a rollback: `close` takes it as
a result and removes the journal), a torn entry in the middle of a journal (counted in `omitted`), a Zatrzymanie of the
window (the Wycena reaches its result either way), Wyceny started from the Skrypt dla maszyn (Historia rows without a
journal; at Dad's every Uruchomienie runs from Centrum, ADR 0017), exceptions other than `OSError` in `close` or `send`, Dad's
actions in the Logs (`DadActionJournal.take`), and the karta after the start (`RunCards.last`).

## Files

- `model/UrwaneUruchomienie.tla`: the model, with the code each action describes.
- `model/*.cfg`: the configurations (first line describes it), `model/oczekiwane.json`: the expected result,
  `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_urwane_uruchomienie.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_urwanego_mutations.py`: proves the check fails when the model loses a guard the code has.
