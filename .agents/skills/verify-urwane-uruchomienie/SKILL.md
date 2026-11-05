---
name: verify-urwane-uruchomienie
description: Model-check with TLA+ (TLC) the trail of a Wycena w efenix that a switched-off Centrum cut short, across the next starts of Centrum, the Dziennik Wyceny in `logs/dzienniki-wyceny/` (`pricing_journal.py`), the Logi Urwanego Uruchomienia (`RunLogs.interrupted`, `guard`, `close`, `send` in `run_logs.py`) and their way into the Kolejka wysyłki (`Outbox.post`). It checks that a journal disappears only after the queue accepted its Logi, that a Wycena with a result never gets Logi Urwanego Uruchomienia, that the Logs file and what goes to the queue have the same characters and passed the guard, that nothing reaches the queue before `Outbox.resume`, and that every order the Wycena changed in efenix is in its Logi, under every order of switch-offs and failed reads and writes. Use when a change touches `PricingJournal` (its end entry `run_ended`), `RunEnded`, `_read`, `_remove` or `InterruptedPricings` in `src/rozliczenia/centrum/pricing_journal.py`, `RunLogs` or `RunLog.interrupted` or `guarded` in `run_logs.py`, `lifespan`, `send_interrupted` or the order of `after_run` in `app.py`, `_Run.work` or `RunHost.after` in `runs.py`, `run_process` in `process_run.py` (the result), the journal calls in `efenix_pricing.py` `save`, or when the check of this skill fails.
pilnuje:
  - src/rozliczenia/centrum/pricing_journal.py
  - src/rozliczenia/centrum/run_logs.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/process_run.py
  - .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
  - tools/lib/rozjazd_modelu.py
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
Uruchomienia and sends them to Maks through the Kolejka wysyłki. The docstring of `pricing_journal.py` promises, and the
model checks over every order of steps:

- **DziennikPoKolejce**: a journal of an Urwane Uruchomienie (it has its first line and the Wycena did not reach its
  result) disappears only after `Outbox.post` accepted its Logi. With **Zbieganie** this is „wysyłka co najmniej raz”.
  Harm: Maks never learns that a Wycena stopped half-way and which order was in progress in efenix.
- **BezUrwanychPoWyniku**: Logi Urwanego Uruchomienia are made only for a Wycena that did not reach its result
  (`run_process` returned with a result, whether or not its Historia row was written); the journal of a Wycena with a
  result is removed, because it says so itself: „koniec Uruchomienia” (`RunEnded`) is on the disk before its Logi with
  the result. Harm: Maks reads „Centrum zamknęło się w trakcie” about a Wycena that
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
the rest. The Historia is not in the model: since #870/#871 the start decides from the journal and the Logs file only.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/UrwaneUruchomienie.tla`, not the code. It describes the code only
while you keep the two in step. Each model action is one indivisible step of this code (`src/rozliczenia/centrum/`
unless named otherwise):

| Model action | Code |
| --- | --- |
| `Start` | `launcher.py` `_start`: `_listen_when_released` takes the port, then `create_app`; in it `InterruptedPricings(...).close()` lists `sorted(glob("*.jsonl"))`. Only the process with the port builds the app, so two closes never run at once |
| `Czytaj` | `InterruptedPricings.close` → `_closed(path)` for one journal: `pricing_journal._read` (no first line or the end entry `RunEnded`, `read.ended` → `None`), `RunLogs.file_of` and `RunLog.model_validate_json` (`ending != "interrupted"` → `None`; `"interrupted"` → the record from the file), else `RunLogs.interrupted`; then `RunLogs.guard`. The Historia is not read. An `OSError` from the journal or the Logs file is caught by `close`, which leaves the journal. One step, because nothing else writes these files while `create_app` runs |
| `ZapiszLogi` | `_closed`: `RunLogs.close(record)` → `_write` → `atomic_file.replace_atomically`; `OSError` only to the Centrum log, and the record still goes to `_pending` |
| `UsunDziennik` | `close`: `if closed is None: _remove(path, ...)` (`unlink`; `OSError` leaves the journal) |
| `Wznow` | `app.py` `lifespan`: `outbox.resume()` before uvicorn accepts the first request |
| `PierwszeZapytanie` | `app.py` `send_interrupted`, a dependency of every API route, → `InterruptedPricings.send`: `pending, self._pending = self._pending, []` |
| `Wyslij` | `send`: `self._run_logs.send(record)` → `outbox.py` `Outbox.post(logi_post(record))`: True once the queue file exists, False leaves the journal for the next start |
| `UsunPoWysylce` | `send`: `_remove(path, ...)` after True |
| `StartWyceny` | `runs.py` `RunHost.start` → `app.py` `run_started` → `PricingJournal.run_started` (start in memory, first line pending) |
| `WpisZaczete` | `efenix_pricing.py` `save`: `journal.begun(...)` before `efenix_trace.traced` and `_priced` → `PricingJournal._write` (first line and entry in one `write`, `flush`, `fsync`; `OSError` drops the entry, `_header` stays; an `OSError` from `flush` or `fsync` after `write` may leave the whole first line on the disk, so the journal has its start while `_header` stays) |
| `ZmianaWEfenix` | `_priced` → `_outcome`: the first window action that changes the order (execution date, Wycena Emmetta, a quantity) |
| `WpisSkonczone` | `save`: `journal.ended(result, ...)` after the result → `PricingJournal._write` |
| `Zatrzymanie` | `save`: a `StopError` after `journal.begun` of an order and before its `journal.ended` (the window stops, or the Ślad Wyceny Emmetta did not save a quantity written ahead, #881); `save` marks the ready orders and raises it on, and `run_process` returns with the Zatrzymanie, so the Wycena reaches its result without „zlecenie skończone” of that order |
| `Wynik` | `runs.py` `_Run.work` → `process_run.py` `run_process`: the engine reached its result, the metrics record (the Historia row) is written or not (`metrics_saved`), and `run_process` returns; when it raises, `_Run.work` goes on with a Stop. Nothing on the journal path reads the Historia row, so the model has none |
| `WpisKonca` | `_Run.work` → `RunHost.after` → `PricingJournal.run_ended`, the first of `after_run` in `create_app` (assignment `runs`): when the journal has its first line (`not self._header`), `_write(RunEnded(...))` (`write`, `flush`, `fsync`); when no entry was written (`self._header`, and a failed write may have left the first line) or `_write` returns False, `_remove(path, ...)` (`unlink`; no file, or a file in place of the folder, leaves nothing to remove; `OSError` leaves the journal without its end entry) |
| `LogiWyniku` | `RunHost.after` → `RunLogs.run_ended`, the next of `after_run` → `_keep`: `_write` of the Logs with the result |
| `WyslijWynik` | `_keep`: `finally: self._outbox.post(logi_post(kept))`, then the end of the Uruchomienie; the journal stays with its end entry until the next start |
| `Zgasniecie` | none: Centrum switches off at any step; memory is gone, disk and queue stay; an entry being written may be torn, a torn first line is a journal without a start, and a torn end entry is a journal without one (`_read` counts it in `omitted`) |
| `Zamkniecie` | „Zamknij Centrum rozliczeń”: `RunHost.shutdown_refusal` accepts it only when no Uruchomienie runs, and the request passed `send_interrupted` first |

The script compares these definitions with the Sync commit (`model/definicje.json`: file → names, `Class.method` is a
method): `PricingJournal`, `RunEnded`, `_read`, `_remove`, `InterruptedPricings` in `pricing_journal.py`;
`RunLog.interrupted`, `guarded`, `RunLogs.run_ended`, `_keep`, `interrupted`, `file_of`, `guard`, `close`, `_write`,
`send`, `LoggedEnding`, `logi_post` in `run_logs.py`; `lifespan`, `send_interrupted`, the assignments `app`, `journal`,
`interrupted` and `runs` (its `after_run` puts `journal` before `run_logs`) and `run_started` in `app.py`; `_Run.work`,
`RunHost.start`, `RunHost.after`, `RunHost.shutdown_refusal` in `runs.py`; `Outbox.post`, `Outbox.resume` in
`outbox.py`; `_start`, `_listen_when_released` in `launcher.py`; `replace_atomically` in `atomic_file.py`; `save` in
`efenix_pricing.py`; `run_process` in `process_run.py`. Every code name in the table above is one of them, except four
left out on purpose: `RunLog` as a whole (the schema of the Logs file, which changes with every new field; the model
reads only `ending`, whose values are `LoggedEnding`), `_priced` and `_outcome` (`ZmianaWEfenix` needs only that `save`
calls `journal.begun` before them, which `save` holds), `metrics_saved` and the Historia (no step of this path reads
them since #870/#871: `RunCards` and the metrics files are the card's, ADR 0017), and `create_app` (see below). Three
changes move the model without changing a definition, so look for them in the diff: the call `interrupted.close()` in
`create_app` leaving its place right after `interrupted = InterruptedPricings(...)`, the `journal` that `create_app`
hands to `EfenixEntry` in `entries` (another journal or none, and the Wycena writes no entries that the start reads),
and a new caller of `InterruptedPricings`, of `PricingJournal.run_ended` or of `RunLogs.send` outside these
definitions. Add such code to the table and to `model/definicje.json`. The table lives in data, not in the script, because a path named in the script would make the
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
on first use; `TLC_JAVA` and `TLC_JAR` override them). The whole check took 48 s on Maks's Mac on 2026-11-05 (round 2
of #888, 13 known findings in 20 TLC runs); the run of `wszystko` with its three known findings excused has 1 097 470
distinct states in 22 s, and with two switch-offs instead of one it also passes, 4.52 million distinct states in 85 s.

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
(`<Logs file>.tmp`), a failed metrics record is `monkeypatch` of `MetricsStore.append` raising `OSError` during the
Wycena, and a failed end entry is `Path.open` with mode `"a"` of a journal raising once the efenix metrics file exists
(every order entry comes before the metrics record, the end entry after it). A failed write that leaves its first line
is the first journal file opened with mode `"a"` whose `fileno` raises `OSError` after `write` and `flush`, and a
Zatrzymanie at an order is an Atrapa order with an HTTP error page (both in
`test_wycena_z_wynikiem_ktorej_jedyny_wpis_dziennika_zawiodl_po_zapisie_pierwszej_linii_nie_dostaje_logow_urwanego_uruchomienia`).
A path that does not happen on the code means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two Wyceny of two orders, two switch-offs anywhere, no other failure | known `przed-wpisem-konca` |
| `odczyt` | two Wyceny of one order, one switch-off, one start that cannot read a journal | known `przed-wpisem-konca` |
| `logi-i-kolejka` | two Wyceny, one switch-off, one failed write of a Logs file, one `post` False, one failed `unlink` | known `przed-wpisem-konca` |
| `koniec` | two Wyceny, one switch-off, one Zatrzymanie at an order, one journal entry that fails (the end entry too, or after its first line is on the disk), one failed `unlink`, one failed write of a Logs file | known `przed-wpisem-konca`, `wpis-konca-nieudany`, `wpis-nieudany` |
| `wpisy` | one Wycena of two orders, one switch-off, one journal entry that fails | known `przed-wpisem-konca`, `wpis-nieudany` |
| `stare-logi` | Wycena 1 already cut, its Logi Urwanego Uruchomienia written without the guard and not sent, one more Wycena, one switch-off, one failed write of a Logs file | known `przed-wpisem-konca`, `zapis-logow-nieudany` |
| `wszystko` | two Wyceny of two orders, one switch-off, one Zatrzymanie at an order and one failure of every kind | the three known findings of `koniec` |

## Known findings

A configuration forgives only the findings `model/oczekiwane.json` lists for it, each only for its promise and only
for an event that happened with its cause (the history variables `zgubiony`, `poWyniku`, `inneZnaki`, `bezZlecenia`
record the causes at every event, and `bezKonca` why the journal of a Wycena with a result has no end entry); any other
path is a new violation. Each cause is pinned to what the finding is about: `wpis-nieudany` to the orders whose own
entry failed (`przepadle`), so an order missing from the Logi whose entries were written is a new violation;
`przed-wpisem-konca` and `wpis-konca-nieudany` to a Wycena without a Logs file with its result, and
`przed-wpisem-konca` also to a Wycena whose Logi with the result the queue did not accept, so Logi Urwanego Uruchomienia
that would replace accepted Logi with the result after a plain switch-off are a new violation. Each finding has its own
run without the other known findings of its configuration, and the configuration one run without all of them. All four
were replayed on the code.

1. **`przed-wpisem-konca`, BezUrwanychPoWyniku (accepted in #870/#871).** Centrum switches off after `run_process`
   returned with a result and before `PricingJournal.run_ended` wrote „koniec Uruchomienia” (in between: the metrics
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
   the second line in the Centrum log), so every other order the Wycena changed is in the Logi. The docstring of `pricing_journal.py` accepts it: „Nieudany zapis wpisu to jedna linia dziennika
   Centrum na Uruchomienie, a Wycena biegnie dalej: ślad jest dla Maksa, a nie warunkiem pracy taty”. Replayed with a
   file in place of `logs/dzienniki-wyceny`, a real Centrum process killed after the Atrapa had a change: after the
   restart there is no journal and no Logs file.
3. **`wpis-konca-nieudany`, BezUrwanychPoWyniku (accepted in #870/#871).** The end entry fails (`OSError`) and so does
   `_remove` of the journal after it, and there is no Logs file with the result (Centrum switched off before it or its
   `_write` failed): the start closes the journal as Logi Urwanego Uruchomienia, and when the Logi with the result went
   to the queue without their file, these Logi replace them in the Skrzynka. Two failures of the journal at once and a
   third event; with a full disk, the most likely shared cause, `unlink` succeeds and frees space, so the journal is
   gone. The shortest path TLC shows (both journal failures, then a switch-off before the Logs) replaces nothing. A
   Wycena no entry of which was written (`_header`) gets the same finding only through a failed `unlink`: a failed
   write may have left the journal with its first line (a Zatrzymanie at the first order then ends the Wycena with that
   line alone), and `run_ended` removes it.
   Replayed with `Path.open` mode `"a"` of the journal raising after the metrics record and `Path.unlink` of the
   journal raising during the Wycena: the journal stays with „zlecenie skończone” last and the Centrum log has
   `dziennik-wyceny-niedostepny typ=PermissionError miejsce=wpis` twice; with a file in place of `logs/uruchomienia`
   too, the only comment of Logs in the Skrzynka changes from `ending` `finished` to `interrupted` after the start.
4. **`zapis-logow-nieudany`, TeSameZnaki (open, cannot happen at Dad's yet).** Logi Urwanego Uruchomienia written by a
   Centrum work before the guard (#851) and not sent: the start guards them, `RunLogs.close` fails (`OSError`), and the
   queue gets the masked text while the file keeps the phone number. No Wydanie has the journal (#845) without the
   guard (v0.4.3 has neither), so no such file exists at Dad's. Logi written by a guard that masks less are the same
   case: a Wydanie with the journal and the guard from before #863 would leave a phone `48600123456` in the file and
   `[telefon]` in the Archiwum after a failed `close`. Replayed with such a file and a folder in place of its
   `.tmp`: the file has `600 123 456`, the file in the Archiwum `[telefon]`.

Decide 4 with Maks; when the code changes, the finding disappears and the check says `ZNALEZISKO ZNIKNĘŁO`.

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

- DziennikPoKolejce: the journal removed although `post` returned False (`send` without `if
  self._run_logs.send(record)`, `logi-i-kolejka`); Logi Urwanego Uruchomienia from the file taken for Logi with a
  result (`_closed` without `logged.ending != "interrupted"`); the end entry written before the metrics record (in
  `save` or in `run_process` before `MetricsStore.append`: a journal cut between the two disappears without Logi).
- BezUrwanychPoWyniku: `_closed` without `read.ended`; no end entry at all (`after_run` without `journal`);
  `after_run` with `run_logs` before `journal` (`koniec`: Logi with the result accepted without their file, a
  switch-off before the end entry, and Logi Urwanego Uruchomienia replace them); `run_ended` without `_remove` after a
  failed end entry (`koniec`); `run_ended` returning on `self._header` without `_remove` (`koniec`: the first entry
  fails after its first line is on the disk, the Wycena stops at that order, and the start gives it Logi Urwanego
  Uruchomienia); `_closed` without `return None` for Logs with a result (`koniec`: a Wycena whose end
  entry and `unlink` failed gets Logi Urwanego Uruchomienia although its Logs with the result exist).
- TeSameZnaki: the Logs file written before the guard (`guard` after `RunLogs.close`).
- PrzezStraznika: `_closed` without `record = self._run_logs.guard(record)`.
- NicPrzedWznowieniem: the Logi sent in `create_app` right after `close`, not in the dependency of the first request.
- ZaczeteWLogach: `_read` without the order begun without a result; `journal.begun` after the first window action;
  `PricingJournal._write` starting with `if self._failed: return` (`wpisy`: after one failed entry the journal writes
  nothing more, so an order without a failed entry of its own is missing from the Logi).
- Zbieganie: `send` without `_remove(path, ...)`; `close` without `if closed is None: _remove(path, ...)`.

A mutation reported as `NIEAKTUALNA` no longer matches the model: rewrite its anchor against the new model so that it
breaks the same rule again.

## Scope

Verified: the seven promises over every order of the actions above within the bounds of each configuration (one or two
Wyceny started one after the other, one or two orders each, one or two switch-offs, at most one Zatrzymanie at an
order and at most one failure of each kind), with Dad opening and closing Centrum as often as he likes. Assumed, each a
reason the check can pass while the code is wrong:

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
- **A journal without its end entry is an Urwane Uruchomienie or one of the known findings `przed-wpisem-konca` and
  `wpis-konca-nieudany`.** A journal written by a build between #845 and #870/#871 has no end entry either, so a Wycena
  of such a build that reached its result without a Logs file gets Logi Urwanego Uruchomienia; no Wydanie has such a
  build (v0.4.3 has no journal), so only Maks's computers can have such a journal. Every Uruchomienie that reached its
  result reaches `RunHost.after` (`_Run.work` catches an exception of `run_process` and goes on), and `run_ended`
  removes the journal it gives no end entry (a failed end entry, or no entry written at all), so only a switch-off
  before `run_ended` or a failed `unlink` leaves the journal of a Wycena with a result without its end entry.
- **`RunLog.model_validate_json(text).text == text`** for a file `close` wrote, and two builds of the same journal give
  Logs with the same orders; their environment, tool and Dad's actions may differ, which the model leaves out. A rebuild
  happens only when the file is missing, so the file and the newest accepted Logi stay the same, unless the clock went
  back between two Centrum works (the queue's version order, `verify-kolejka-skrzynki`).

Left out: a glob of `logs/dzienniki-wyceny/` that fails (it skips every journal, like one failed read per journal), a
Logs file that cannot be parsed (truncated by hand, a schema from a newer version after a rollback: `close` takes it as
a result and removes the journal), a torn entry in the middle of a journal (counted in `omitted`), a failed write that
left a torn first line (`run_ended` removes it like a whole one, and a start removes a journal without a start), a
Zatrzymanie before the first order (no entry, no journal), the Historia (no step of this path reads it), exceptions
other than `OSError` in `close`, `send` or `run_ended`, Dad's actions in the Logs (`DadActionJournal.take`), and the
karta after the start (`RunCards.last`, which shows the Urwane Uruchomienie for `przed-wpisem-konca`).

## Files

- `model/UrwaneUruchomienie.tla`: the model, with the code each action describes.
- `model/*.cfg`: the configurations (first line describes it), `model/oczekiwane.json`: the expected result,
  `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_urwane_uruchomienie.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_urwanego_mutations.py`: proves the check fails when the model loses a guard the code has.
