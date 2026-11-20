---
name: verify-urwane-uruchomienie
description: Model-check with TLA+ (TLC) the trail of a Wycena w efenix that a switched-off Centrum cut short, across the next starts of Centrum, through the Dziennik Wyceny, the Logi Urwanego Uruchomienia, the progress comment and the end of a Wycena, up to the Kolejka wysyłki (`Outbox.post`) - that Maks learns of every cut Wycena and its order in progress, that its Logi pass the guard and match the file at Dad's, never replace the Logi with the result, and that the journals get cleared. Use when `tools/skille_dla_zmiany.py` names it, or when `sprawdz_urwane_uruchomienie.py` fails.
pilnuje:
  - src/rozliczenia/centrum/run_logs.py
  - src/rozliczenia/centrum/run_logs_guard.py
  - src/rozliczenia/centrum/comment_versions.py
  - src/rozliczenia/centrum/run_comments.py
  - src/rozliczenia/centrum/logs_disk.py
  - src/rozliczenia/file_state.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/process_kind.py
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/process_run.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
ci-czesci: 2
---

# Verify Urwane Uruchomienie (TLA+)

## What CI runs and what stays local

CI runs the `ci:` check in Mutation checks whenever a change touches `pilnuje:` or this folder.
`scripts/check_model_urwanego_mutations.py` runs on a pull request that changes `model/` or either script, and in full
CI and nightly on `main` after a change of this folder.
Run them locally only while you bring the model in line or to reproduce a red Mutation checks step.

CI and `tools/szybko.py` catch drift: covered code that differs from its digests in `model/definicje.json`
(`ROZJAZD MODELU Z KODEM | <skill>: …`).
They cannot tell whether your change to the model is right, so „Bring the model in line” stays with you on every
change to the covered code.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

Each promise is an invariant of `model/UrwaneUruchomienie.tla`, and `Zbieganie` its liveness property; the docstring
of `logs_disk.py` promises them. Each with what it states and its harm when it breaks:

- **DziennikPoKolejce**: a journal of an Urwane Uruchomienie (with its first line, without a result) disappears only
  once its Logi are the newest version the queue accepted; with Zbieganie, a send at least once. Harm: Maks never learns that a Wycena stopped half-way and which order was in progress in efenix
  (D2 of #875: after the clock went back the progress was newer and the queue dropped the Logi).
- **BezUrwanychPoWyniku**: Logi Urwanego Uruchomienia exist only for a Wycena that did not reach its result. Harm:
  Maks reads „Centrum zamknęło się w trakcie” about a Wycena that finished, and in the
  Skrzynka these Logi replace the Logi with the result (same `run_id` and label, newer version).
- **TeSameZnaki**: Logi from a journal go to the queue with the same characters as the Logs file on Dad's disk. Harm:
  the file in the Archiwum Logów okresu and the file at Dad's differ, so a replay from either (#847)
  sees another Uruchomienie.
- **PrzezStraznika**: Logi from a journal go to the queue only after the guard of the data rule of this Centrum work.
  Harm: a phone number or a street from an efenix page leaves Dad's computer (ADR 0025).
- **NicPrzedWznowieniem**: nothing goes to the queue before this Centrum work called `Outbox.resume`. Harm: a version
  reaches the queue outside what the model of `verify-kolejka-skrzynki` checks,
  which takes this promise as given for every `post`.
- **ZaczeteWLogach**: every order an Urwana Wycena changed in efenix is in its Logi, finished or started without a
  result. Harm: Maks does not know which order may be half-priced in efenix.
- **WersjaKoncowa**: a Wycena that may have sent a progress has a journal with its first line on disk, which disappears
  only once the newest accepted version of the comment of its Uruchomienie is an end version (Logi with the result,
  Logi Urwanego Uruchomienia or a result without Logi); with Zbieganie, after the next start every Wycena that sent a
  progress has an end version in the Skrzynka, not the progress. Harm: Maks reads „Wynik: jeszcze nie ma, Uruchomienie trwa” forever about a Wycena that ended or was
  cut (W2 of #875, #910).
- **LogiZostaja**: the newest version of the comment with Logi (with the result or Urwanego Uruchomienia) never gives
  way to a progress or a result without Logi, and Logi with the result never to Logi Urwanego Uruchomienia. Harm: the
  newer version replaces the Logi in the queue and in the Skrzynka, so Maks loses the summary and
  the link to the full Logi, and without the network the full Logi (#871, W1 of round 3 of #846).
- **Zbieganie**: once failures stop and Dad opens and closes Centrum, every journal disappears. Harm:
  `logs/dzienniki-wyceny/` grows forever, or every start sends the same Logi again.

## Does the change touch it?

The check runs a hand-written TLA+ model, not the code, and the model describes the code only while you keep the two
in step. It follows a Wycena w efenix that a switched-off Centrum cut short across the next starts of Centrum: the
Dziennik Wyceny (`logs_disk.py`: `Journal`, `LogsOnDisk.left_behind`; `run_comments.py`: `RunComments.close_left_behind`
and `send_left_behind`, `comment_versions.close`), the Logi Urwanego Uruchomienia (`RecordMaker.interrupted`,
`run_logs_guard.py` `guard_logs`) and their way to the Kolejka wysyłki (`Outbox.post`), beside the Logi of a Wycena
that reached its result and the end entry in its journal, and the progress comment of a Wycena
(`RunComments._progress`, #846), which the end version turns into the summary: the Logi with the result, or, when the
queue did not accept them in the work of the Uruchomienie, the stand-in version of the next start (#910). Each action of
`model/UrwaneUruchomienie.tla` is one indivisible step of this code (`src/rozliczenia/centrum/` unless named otherwise),
and the row names each branch by what it stands for in the code, in the order of the model:

| Model action | Code |
| --- | --- |
| `Start` | a start of Centrum: `launcher._start` takes the port (`_listen_when_released`), then `create_app` builds the app, in which `RunComments.close_left_behind()` → `LogsOnDisk.left_behind` goes through the journals of `sorted(glob("*.jsonl"))` one by one. Memory is new, and the versions in the queue are from an earlier work; while Centrum was closed the computer's clock may have gone back, so the moments of this work may be earlier than those of every version already in the queue (`cofniety`) |
| `Czytaj` | `RunComments.close_left_behind` → `close(left)` for the journal at `kursor`: `LogsOnDisk.left_behind` reads it (`_read_journal`) and its Logs file (`LogsOnDisk.logs`, `_read_logs`) in one step, because nothing else in `create_app` writes these files; the start reads no Historia. Branches: `glob` does not return a journal that does not exist; `except OSError` of `left_behind` or `close_left_behind` (a read of the journal or of the Logs, or a listing of an existing Logs folder, `Refused`, which `close` raises on): `pricing_journal_unavailable(where="start")`, `continue`, and the journal stays for the next start; `_read_journal` gives `None` (no first line) → `Drop` → `remove_journal`; `Found`: the Logi from the file (with the result, whose acceptance by the queue nobody recorded, or Logi Urwanego Uruchomienia a previous start wrote and did not send); `read.end` without a Logs file: `WithoutLogsVersion` (the result from the end entry, the orders from the journal), with no file; no Logs file and no end entry: `StandInLogs(guard_logs(interrupted(read), forbidden))`. A journal with a first line stayed because the queue did not accept the Logi with the result in the work of the Uruchomienie (`RunComments.run_ended`) or because it is an Urwane Uruchomienie, so the start closes it with a stand-in version (`Rank.STAND_IN`) and removes only a journal without one |
| `ZapiszLogi` | `close_left_behind`: `self._disk.write(logs)` → `replace_atomically` (a temporary file, `os.replace`); an `OSError` goes only to the Centrum log, and the Logi go to `_pending` anyway |
| `UsunDziennik` | `close`: `if closed is None: _remove(path, ...)`, only a journal without a first line, to which no progress went |
| `Wznow` | `app.py` `lifespan`: `outbox.resume()` before the stand-in versions and before the first HTTP request (uvicorn ends the start of `lifespan` before it accepts a request from the socket's queue) |
| `WysylkaStartu` | `server.py` `serve` after the `start` entry (the step `AFTER_START`, which `lifespan` yields after `outbox.resume()`): `RunComments.send_left_behind` takes all of `_pending` under the lock (`pending, self._pending = self._pending, []`) before the first HTTP request (`_Server.startup` calls it before the event loop accepts a request) |
| `Wyslij` | `send_left_behind`: `journal_after(version, accepted=self._queue.post(post_of(version)))` → `Outbox.post` of the stand-in version (`post_of`, `Rank.STAND_IN`): Logi or a result without Logi; `journal_after` gives „usuń” when the queue file exists and „zostaw” when `post` returned False, and the journal waits for the next start. An exception of `post` or of `remove_journal` goes to the Centrum log (`unexpected_failure`), leaves the journal and goes on with the next version, as a failure of the queue or of the removal |
| `UsunPoWysylce` | `send`: `_remove(path, ...)` after the queue accepted |
| `StartWyceny` | Dad starts a Wycena w efenix: `RunHost.start` → `RunComments.run_started` → `LogsOnDisk.started` → `Journal._run_started` (the start in memory, `_header`) before the thread starts; the first line goes to disk in the same call (`ZapiszStart`). The request comes after the server started, so after the stand-in versions were sent. An `OSError` of the last-start file goes out to `RunHost.start` before the progress |
| `ZapiszStart` | `Journal._run_started` → `_append_locked(start)`: the first line alone in one `write`, `flush` and `fsync` (#846), before the thread of the Wycena starts. Branches: written; `OSError`, after which `_header` stays, so the first line goes with the next entry, and the Wycena goes on; `OSError` from `flush` or `fsync` after a `write` that left the whole first line on disk. A switch-off during this write leaves a torn first line (`Zgasniecie` in phase `start`). A progress goes only without `_header` (`postepMozliwy`) |
| `WpisZaczete` | `efenix_pricing.py` `save`: `journal.begun(order.row, ...)` before `efenix_trace.traced` and `_outcome`, through `Wpis` |
| `ZmianaWEfenix` | `_outcome`: the first action of the efenix window that changes the order (the execution date, Wycena Emmetta, a quantity) |
| `WpisSkonczone` | `save`: `results.append(result)`, `journal.ended(result)` through `Wpis`, then the next order or the end of the pass |
| `Zatrzymanie` | `save`: a Zatrzymanie at an order after `journal.begun` and before `journal.ended` (the efenix window stops: an error page, a logout, a closed window); `save` marks the ready orders and raises `StopError` on, and `run_process` returns a result with the Zatrzymanie. That order has no „zlecenie skończone”, so the journal may reach the result with one entry. The window also stops before the first `journal.begun` (closed during Dad's login, phase `zaczete`), so the journal reaches the result with its first line only, or without it |
| `Postep` | `RunComments.run_started` (the start of the Wycena) or the timer `_refresh` every `PROGRESS_S` → `RunComments._progress`: `Outbox.post` of the progress from the journal (`post_of(ProgressVersion)`, `Rank.DRAFT`) when `Journal.progress` gives one (without `_header`), and until `RunComments.run_ended` marked the Wycena ended (`_Watched.ended`, under the same lock). The model counts a progress possible from the moment the first line is on disk (`postepMozliwy`); a progress the queue did not accept changes nothing, so the action has only an accepted one, and one that replaces the newest version with Logi is an event of LogiZostaja (`Przyjmij`) |
| `Wynik` | `runs.Run.work` → `PreparedRun.conduct` → `process_run.run_process`: the engine reached its result, `MetricsStore(...).append(record)` writes the metrics record (the Historia row) or not (`OSError`, `UnicodeError`, `ValueError`: `metrics_saved = False`), and `run_process` returns with the result. The start does not read the Historia row, so the model has none. `process_kind.startable` before `conduct` and in it changes no state, and the object of `Catalog.prepared` always passes it |
| `WpisKonca` | `RunHost.after` → `RunComments.run_ended`, the first action after the result (`after_run` in `create_app`), step 1 in the shield `_step`: `Journal.end`. Branches: `self._header` with no file (another process, or every write failed without a trace on disk); `if header: _remove(path, ...)`: no write confirmed the first line, so `_remove` removes what a failed write left on disk (without a file `unlink` raises `FileNotFoundError`, which `_remove` skips) and there was no progress, and a failed `unlink` leaves the journal without an end entry; `else: self._write(_RunEnded(...))`, the end entry with the result (`write`, `flush`, `fsync`); `_write` raises `OSError`: the end entry is lost and the journal stays, which step 4 of `run_ended` removes once the queue accepts the Logi with the result, or the next start after the stand-in version |
| `LogiWyniku` | `RunComments.run_ended` after step 1: `_Watched.ended` under the lock (the end of the progress), then in the shield `_step` the Logi with the result (`_own`: `RecordMaker.of`, `guard_logs`, `OwnLogs` with the Wzorce of the process; a Wycena w efenix uses no Wzorzec, so its `OwnLogs` have none) and `_keep`: `LogsOnDisk.write` (`replace_atomically`); a failed write leaves `_keep` only after the send (`finally`), and `_step` writes its type to the Centrum log |
| `WyslijWynik` | `_keep`, `finally` also after a failed write of the file: `post_of(version)` of the `OwnLogs` of `_own` to `Outbox.post`, whose result is `accepted`; an exception of `post` leaves no `accepted`, as a `post` that returned False. Then step 4 of `run_ended` (phase `zaLogami`) |
| `UsunPoLogach` | `RunComments.run_ended`, step 4 in the shield `_step`: `Journal.remove` when `journal_after(OwnLogs, accepted)` gives „usuń”: a journal with its first line on disk disappears once the queue accepted the Logi with the result in this Centrum work (`accepted`), and `Journal.end` already removed a journal without it (`_header`). Otherwise it stays for the next start |
| `KoniecUruchomienia` | the rest of `after_run` after `RunComments` (`QuantityCheckAfterRun`, `filling`), then the end of the Uruchomienie (`end`): the next one may start |
| `Zgasniecie` | none: Centrum switches off at any moment (a power cut, a killed process, the console window closed); memory is gone, the disk and the queue stay. An entry being written may be torn: a torn first line is a journal without a start (`_read_journal`: `None`), a torn end entry a journal without it. A cut Wycena that changed something in efenix without a journal with a first line gets no Logi: an event of ZaczeteWLogach, which misses every order changed in efenix. A switch-off after the result and before the end entry leaves the journal of a Wycena with a result without its end entry (`bezKonca`). A progress of a Wycena whose journal never had its first line on disk would get no end version: an event of WersjaKoncowa |
| `Zamkniecie` | Dad closes Centrum („Zamknij Centrum rozliczeń”): `Shutdown` accepts it only while no Uruchomienie runs (`runs.shutdown_refusal`), and the request came after the server started |

Definitions the actions share:

| Model definition | Code |
| --- | --- |
| `Tresci` | the content of Logi Urwanego Uruchomienia: the orders finished before the switch-off (`efenix_orders`), the order started without a result (`interruption.row`; 0 when it switched off between orders) and whether the text passed the guard of the data rule |
| `PlikiLogow` | the Logs file of an Uruchomienie (`logs/uruchomienia/<file>.json`): none, Logi with the result (`RunLog.ending` other than `interrupted`) or Logi Urwanego Uruchomienia with their content |
| `Wpisy` | the journal entries „zaczynam zlecenie”, „zlecenie skończone” and „koniec Uruchomienia” (`_RunEnded`, whose order means nothing) |
| `Rodzaje`, `RodzajeWersji`, `ZLogami` | the end versions of the comment of an Uruchomienie the queue accepts: Logi with the result, Logi Urwanego Uruchomienia and a result without Logi (`comment_versions.ResultWithoutLogs`: the start has the end entry and no Logs file); the progress (`RunComments._progress`) is a version of the same wysyłka without a Logs file, which the model keeps only as the newest version, and `brak` is no accepted version; the kinds with full Logi |
| `StopienPostepu`, `StopienZeStartu`, `StopienWlasny` | the rank of a version (`outbox.py` `Rank`, `Post.rank`), chosen by the sender, not by the clock; the queue compares the rank first and the moment from the file name only within one rank (`outbox.py` `Version`). `RunComments._progress` → `post_of(ProgressVersion)`: `rank_of` gives `Rank.DRAFT`; `RunComments.send_left_behind` → `post_of` of a stand-in version: `Rank.STAND_IN`; `RunComments._keep` → `post_of(OwnLogs)`: `Rank.OWN` |
| `Wersje` | the newest accepted version of the comment of an Uruchomienie: its kind, its rank, whether it came in this Centrum work, and whether the clock went back at a start since (then its moment may be later than the moments of the new work) |
| `Rekordy`, `Oczekujace` | the Logs file a start writes (`LogsOnDisk.write`) and the stand-in version it sends: kind and content; `RunComments._pending`: a stand-in version, its journal and whether its Logs file failed to write |
| `PrzedKoncemPostepu` | the phases in which `RunComments._progress` still sends a progress: before the end mark in `RunComments.run_ended` (`_Watched.ended`, after the end entry) |
| `ZWynikiem(r)`, `WynikPrzyjety(r)`, `Zakonczony(r)` | Wycena `r` reached its result (`run_process` returned; the Historia row may be missing); the queue accepted its Logi with the result in the work of its Uruchomienie; `logs_disk._read_journal`: its journal has „koniec Uruchomienia” (`read.end`) |
| `Przyjete(r)`, `Koncowa(r)` | the Logi Urwanego Uruchomienia of `r` are the newest version the queue accepted (`Outbox.post` returned True), so they reach the Skrzynka (Logi behind which the queue has a newer version it marks and removes without sending); the newest accepted version is an end version, so the comment in the Skrzynka does not stay a progress |
| `Wyparcie(stary, nowy)` | a change of the newest version that loses Logi: Logi (with the result or Urwanego Uruchomienia) to a progress or a result without Logi, and Logi with the result also to Logi Urwanego Uruchomienia (#871) |
| `Przyjmij(r, rodzaj, s)` | `Outbox.post` accepted a version of kind `rodzaj` and rank `s`. A version in the queue is its rank, then the moment and number from the file name (`outbox.py` `Version`): the higher rank is newer, and within one rank the later moment. In one Centrum work the moment grows with each wysyłka also after the clock went back (`Outbox.post`), and a version of an earlier work has an earlier moment unless the clock went back at a start since (`cofniety`), when the moment of a new wysyłka may be earlier. The queue and the Skrzynka keep the newest version (`_superseded`, `_settle`, the model of `verify-kolejka-skrzynki`), so the model keeps only it; a version that loses the Logi of the newest is an event of LogiZostaja |
| `Niepokryte(r, t)`, `Pokrywa(r, t)`, `PoWpisach(r, brakujace)` | the orders Wycena `r` changed in efenix that the Logi `t` have neither as finished nor as started without a result; the finding `wpis-nieudany` covers only orders whose own entry was lost, so a missing order whose entries were written is a new violation |
| `ZDziennika(r)` | `logs_disk._read_journal`: the orders of the entries „zlecenie skończone”, and the order started without a result from the last entry when that is „zaczynam zlecenie”; `RecordMaker.interrupted` → `RunLog.interrupted`. The text of the orders' trail is raw until it passes the guard |
| `Straz(t)`, `Odczytane(odczytany)`, `Zbuduj(r)` | `guard_logs` → `guarded` in `comment_versions.close`, the guard of the data rule of this Centrum work; `close`: `StandInLogs(guard_logs(record, forbidden))` (`GuardedLogs`), then the Logs file (`ZapiszLogi`); `close` of a journal without an end entry and without a Logs file: Logi Urwanego Uruchomienia of a Wycena that reached its result are an event of BezUrwanychPoWyniku, whose causes are why the journal lacks its end entry (`bezKonca`), with „przed-wpisem-konca” only when the queue did not accept its Logi with the result (a switch-off before the end entry is before the Logi); the branch of the Logi from the file reads such a file later and does not repeat the event |
| `PoPoscie(h)` | the events at each `Outbox.post` of a stand-in version `h` from a journal: Logi with other characters than their file, a text without the guard, a send before `Outbox.resume`, and in Logi Urwanego Uruchomienia an order changed in efenix without a trace |
| `UsunPlik(r, przyczyny)` | `logs_disk._remove`: `file_state.remove_file` (`unlink`); no file does nothing, an `OSError` leaves the journal (a Centrum log line). A journal of an Urwane Uruchomienie (a first line, no result) whose Logi are not the newest version in the queue disappears: an event of DziennikPoKolejce with the causes of the decision. A journal of a Wycena that may have sent a progress, whose newest version in the queue is not an end version, disappears: an event of WersjaKoncowa |
| `Wpis(rodzaj)` | `Journal._write` → `_append_locked`: the first line (while it is not on disk: `_header`) and the entry in one `write`, `flush` and `fsync`, without it the entry alone, so an entry without a first line on disk gives a journal without a start. Branches: written; `OSError`: the entry is lost, `_header` stays, the Wycena goes on, and the next entry `_write` tries again (`_failed` only silences the Centrum log line); `OSError` from `flush` or `fsync` after a `write` that left the whole first line (the entry lost or torn): the journal has a start although `_header` stays |
| `Dalej` | the next stand-in version of the list of `send_left_behind`, or its end |
| `Init` | before the first start nothing exists; with `StareLogi` Wycena 1 is already cut, its journal has order 1 finished, and a Centrum work from before the guard wrote the file of its Logi Urwanego Uruchomienia and switched off before sending them. Its progress counts as possible, so the model also checks the end version of its comment |
| `Sprawiedliwosc` | running code takes its next step, Dad opens Centrum while none runs and at some point closes it while nothing runs (Centrum does not run forever), and he starts Wyceny when he likes. A progress depends on the timer and a Wycena reaches its result without it, so `Postep` needs no fairness |

Each constant is a way to fail or a bound of a configuration (`stale` in `model/konfiguracje.json`):

| Constant | Meaning |
| --- | --- |
| `Wyceny` | Uruchomienia of Wycena w efenix, one after another (Centrum runs one at a time) |
| `LiczbaZlecen` | orders in each Wycena, in order |
| `MaxZgasniec` | switch-offs of Centrum: a power cut, a killed process, the console window closed |
| `MaxZatrzyman` | Zatrzymania of a Wycena at an order: it reaches its result without „zlecenie skończone” |
| `MaxAwariiWpisu` | `Journal._append_locked` raises `OSError` (the entry is lost, the Wycena goes on), also for the first line at start and for the end entry; after `write` the whole first line may stay (`flush` or `fsync` raises) |
| `MaxAwariiOdczytu` | `RunComments.close_left_behind`: `OSError` of a read of the journal, of the file or of the folder of Logs (the journal stays) |
| `MaxAwariiLogow` | `LogsOnDisk.write` (`replace_atomically`) raises `OSError`: no Logs file, or the previous one stays |
| `MaxAwariiKolejki` | `Outbox.post` returns False (the queue file could not be written) |
| `MaxAwariiUsuniecia` | `_remove`: `OSError` of `unlink` (the journal stays), at start, after the result and after the Logi |
| `MaxCofniecZegara` | the computer's clock goes back while Centrum is closed (the CMOS battery after a power cut, which Windows does not correct without the network): the moment in the name of a queue file may be earlier than in the previous Centrum work |
| `TekstDoMaski` | the orders' trail in the journal has text the guard of the data rule masks (a phone, a street) |
| `StareLogi` | before the first start Wycena 1 is cut, and a Centrum work from before the guard (#851) wrote its Logi Urwanego Uruchomienia without the mask but did not send them |
| `Wybaczone…` | the causes of known findings that the `…PozaZnanymi` variant of each promise skips; the script sets them |

| Variable | Meaning |
| --- | --- |
| `dziennik`, `wpisy`, `logi`, `efenix`, `kolejka`, `najnowsza` | Dad's disk and the Kolejka wysyłki, which outlive a switch-off: the journal of Wycena `r` (none, `bezStartu` with a torn first line, or present); its entries after the first line, in order, without torn ones; the Logs file of Uruchomienie `r`; the orders Wycena `r` already changed in efenix; the end versions `Outbox.post` accepted (`bieg`, kind, content); the newest version of the comment of Uruchomienie `r` the queue accepted (`Wersje`), which the Skrzynka has in the end, because the queue replaces an older one (`_superseded`) and the Skrzynka takes no older one (`_settle`) |
| `centrum`, `wznowiona` | the memory of one Centrum work, gone with a switch-off and a close: Centrum stands, closes the journals left behind (`create_app`: `close`, then `lifespan`), sends after the start (`send`) or runs; `lifespan` of this work already called `Outbox.resume` |
| `kursor`, `krokZamykania`, `rekord`, `oczekujace`, `doWyslania`, `krokWysylki` | which journal of `sorted(glob)` `close` reads; its step (read, write the Logs file, remove the journal); the Logi (from the file or Urwanego Uruchomienia) `close` writes to the file; `RunComments._pending`: the stand-in versions to send and their journals; what `send_left_behind` took from `_pending`; its step (`post`, or remove the journal after the queue accepted) |
| `bieg`, `faza`, `zlecenie`, `naglowekCzeka`, `wKolejce`, `nastepny` | the Wycena running in this work (0: none); where it is (`start`, `zaczete`, `efenix`, `skonczone`, `wynik`, `koniec`, `logi`, `post`, `zaLogami` for step 4 of `run_ended`, `po` for the rest after the result); its current order; `Journal._header`: the first line is not on disk yet (at start or with an entry); `accepted` in `RunComments.run_ended`: the queue accepted the Logi with the result of the current Wycena; the next Wycena Dad may start |
| `zgasniecia`, `zatrzymania`, `awarieWpisu`, `awarieOdczytu`, `awarieLogow`, `awarieKolejki`, `awarieUsuniecia`, `cofniecia` | the counters of the `Max…` constants |
| `zapisanyStart`, `postepMozliwy`, `wynik`, `przepadle`, `bezKonca` | helper variables with no counterpart in the code, only for the promises: the journal of `r` once had its first line; Wycena `r` may have sent a progress, so its comment in the Skrzynka may say it runs: the first line of its journal is on disk without `_header` (`Journal.progress` gives a progress, and `RunComments` sends it at the start of the Wycena and then every `PROGRESS_S`), counted from that moment; Wycena `r` reached its result (`run_process` returned with it, with or without a Historia row); the orders of Wycena `r` whose own journal entry was lost (`OSError`); why the journal of Wycena `r` with a result stayed on disk without its end entry |
| `zgubiony`, `poWyniku`, `inneZnaki`, `bezStrazy`, `przedWznowieniem`, `bezZlecenia`, `bezWersji`, `wyparty` | the history variable of each promise: the set of causes at the moment of each event that breaks it |

Names in the table that `model/definicje.json` leaves out on purpose:
`_refresh` and `_Watched` (they only decide when `RunComments._progress` runs, and the model lets a progress come at
any step it allows; `_progress` itself reads `ended` under the lock), `guard_text` (the text of a version without
Logi), `RunLog` as a whole (the schema of the Logs file, which changes with every new field; the model reads only
`ending`, whose values are `LoggedEnding`), `_outcome`, `efenix_trace.traced` and `StopError` (`ZmianaWEfenix` and
`Zatrzymanie` need only their place in `save` after `journal.begun` and before `journal.ended`), `metrics_saved` and
the Historia (no step of this path reads them since #870/#871: `RunCards` and the metrics files are the card's,
ADR 0017), `process_kind.startable` and `Catalog.prepared` (they change no state, and the prepared object always
passes the check), `RecordMaker.of` (the content of the Logi with the result, which the model leaves empty), `_settle`
(the Skrzynka keeps the newest version, which `verify-kolejka-skrzynki` checks), and `create_app` as a whole.
The list lives in data, not in the script, because a path named in the script would make the change-impact selection
(`tools/lib/wplyw_zmiany.py`) run the test of the script on every change of `app.py` or `atomic_file.py`, although that
test builds its own files.

Three changes move the model without changing a definition, so look for them in the diff:

- a call of `comments.send_left_behind()` in `create_app` other than the `AFTER_START` step that `lifespan` yields
  after `outbox.resume()`;
- the `journal` that `create_app` puts in `HostParts` (`parts.journal`, `disk.journal`, which the efenix entry gives
  the Wycena): another journal or none, and the Wycena writes no entries that the start reads;
- a new caller of `RunComments`, of `comment_versions.close`, of `Journal.end` or of `Journal.remove` outside these
  definitions, or a progress that reaches the queue another way than `RunComments._progress`.

Add such code to the table and to `model/definicje.json`.

The digests in `model/definicje.json` were taken when every action was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests. To see
what changed since:

```sh
git diff $(git log -1 --format=%h -- .agents/skills/verify-urwane-uruchomienie/model/definicje.json) -- <files of model/definicje.json>
```

## Run

```sh
.venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
py -3 .agents\skills\verify-urwane-uruchomienie\scripts\sprawdz_urwane_uruchomienie.py
```

The whole check takes 2–3 min on Maks's Mac (2 min 23 s on 2026-11-05, 23 TLC runs).

The last line is the verdict (`tools/lib/model_tlc.py` defines each):

- `URWANE URUCHOMIENIE OK` or `… OK, ZNANE ZNALEZISKA: n`: every configuration ends as `model/konfiguracje.json` says.
- `URWANE URUCHOMIENIE: NOWE NARUSZENIE (n)`: read the counterexample as „Read a result” says.
- `URWANE URUCHOMIENIE: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change under „Known
  findings” and remove it from `znane` of its configuration.
- `URWANE URUCHOMIENIE: BŁĄD MODELU (n)`: the model, not the code, is broken; this also covers a counterexample whose
  story does not know an action of `Next` (`_STEPS` in the script).
- `UWAGA: kod opisany modelem zmienił się: …` above the verdict: drift; the verdict means nothing until you bring the
  model in line.

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
or a journal written with `left_journal` (`tools/lib/atrapy/dziennik_wyceny.py`), as in
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
A switch-off before any step of the end of a Wycena that writes (`WpisKonca`, `LogiWyniku`, `WyslijWynik`,
`UsunPoLogach`) is `PowerCut` in `tests/test_komentarz_logow_uruchomienia.py`: Logi na dysku and a queue that raise
`SwitchedOff` before that write, then a new `RunComments` on the same folder
(`test_centrum_zgaszone_przed_kazdym_krokiem_konca_wyceny_daje_nastepnemu_startowi_wersje_zastepcza_z_tego_co_zapisalo`);
what the queue does with two versions of one comment is `tests/test_kolejka_skrzynki_zgloszen.py`. A clock that went
back is a queue file whose name has a later moment than any wysyłka of the next work
(`test_cofniety_zegar_komputera_nie_daje_postepowi_w_kolejce_pierwszenstwa_przed_logami_urwanego_uruchomienia`).
A path that does not happen on the code means the model is wrong until you show it is not.

## Known findings

Each known finding stands in `znane` of its configurations in `model/konfiguracje.json` with its promise, its cause and
what it is. All four were replayed on the code; this is why each is accepted and how it was replayed.

1. **`przed-wpisem-konca`, BezUrwanychPoWyniku (accepted in #870/#871).** The end entry and the metrics record are two
   files, so one order leaves a window; the other order (the end entry before the metrics record, the mutation „wpis
   końca przed rekordem metryk”) makes the journal of a Wycena cut in that window disappear without any Logi, which
   breaks DziennikPoKolejce. The card after the start also shows the Urwane Uruchomienie instead of the result from the
   Historia (ADR 0017). Replayed with a journal without its end entry (`journals_at_result` in
   `tests/test_centrum_logi_uruchomienia.py`), the Logs file and the queue folder removed, the metrics record kept: the
   start writes and sends Logi with `ending` `interrupted`, and the card after it is the Urwane Uruchomienie.
2. **`wpis-nieudany`, ZaczeteWLogach (accepted).** Only the order of the lost entry: `_write` tries every next entry
   again (`_failed` only silences the second line in the Centrum log). Replayed with a file in place of
   `logs/dzienniki-wyceny` and a real Centrum process killed after the Atrapa had a change: after the restart there is
   no journal and no Logs file.
3. **`wpis-konca-nieudany`, BezUrwanychPoWyniku (accepted in #870/#871, changed in #910).** A failed end entry plus a
   switch-off in the milliseconds before the Logs, or three failures. Before #910 a failed end entry removed the
   journal and left „Uruchomienie trwa” forever; now the comment gets these Logi, and the card after the start shows the
   Urwane Uruchomienie instead of the result. Replayed with `Path.open` mode `"a"` of the journal raising after the
   metrics record and `Path.unlink` of the journal raising during the Wycena, before #910: the journal stays with
   „zlecenie skończone” last and the Centrum log has `dziennik-wyceny-niedostepny typ=PermissionError miejsce=wpis`
   twice; with a file in place of `logs/uruchomienia` too, the only comment of Logs in the Skrzynka changed from
   `ending` `finished` to `interrupted` after the start, which the rank now prevents.
4. **`zapis-logow-nieudany`, TeSameZnaki (open, cannot happen at Dad's yet).** No Wydanie has the journal (#845)
   without the guard (v0.4.3 has neither). Logi written by a guard that masks less are the same case: a Wydanie with the
   journal and the guard from before #863 would leave a phone `48600123456` in the file and `[telefon]` in the Archiwum
   after a failed `write`. Replayed with such a file and a folder in place of its `.tmp`: the file has `600 123 456`,
   the file in the Archiwum `[telefon]`. Decide it with Maks; when the code changes, the check says
   `ZNALEZISKO ZNIKNĘŁO`.

Gone from the known findings: `po-wpisie-konca` (WersjaKoncowa, fixed in #910: the start now sends a stand-in version
between the progress and the Logi with the result), and `wiersz-pozniejszej-wyceny`, `historia-nieczytelna` and
`historia-niezapisana` (fixed in #870/#871: the journal says itself that its Uruchomienie reached its result, so the
start reads no Historia, and `historia-nieczytelna` has no path left). `tests/test_centrum_logi_uruchomienia.py`
replays the others, and the window of `po-wpisie-konca`, the clock that went back (D2 of #875) and both paths of #870/#871
fail on `main` before their fix.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, and write the code's names in its row of
   the table above, not in a comment: the model has none, and a new action, branch, definition, constant or variable
   gets its own row or its place in one. TLA+ strings must be ASCII. Never weaken a promise or narrow a configuration to
   make the check pass.
3. A new way to fail gets a constant with its row, a branch guarded by it, and a value in `stale` of every configuration in
   `model/konfiguracje.json`. A new action of `Next` gets its words in `_STEPS` of the script.
4. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_urwanego_mutations.py` with the code counterpart in its name.
5. Run the check. A new violation is a finding: replay it on the code („Read a result”) before you call it a bug,
   report it with the path, and change product code only when asked.
6. Run `tools/przesun_model.py verify-urwane-uruchomienie` only after every action describes the code, and write in the
   commit message, in one sentence, what changed in the model and why.

## After changing the model

`.venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/check_model_urwanego_mutations.py` must end with
`MUTACJE OK`; each of its mutations removes from the model a guard the code has.
`RunComments._progress` without the check of `ended`, or `_Watched.ended` set after `_keep`, has no mutation because it
breaks no promise since #910: a progress after the Logi with the result has a lower rank and changes nothing. `ended`
still ends the progress timer, which
`test_postep_wyceny_w_efenix_ktorego_budzik_dzwoni_gdy_jej_logi_sa_juz_w_kolejce_nie_cofa_podsumowania` checks.

## Scope

Verified: the nine promises over every order of the model's actions within the bounds of each configuration (one or
two Wyceny started one after the other, one or two orders each, one or two switch-offs, at most one Zatrzymanie at an
order or before the first and at most one failure of each kind), with Dad opening and closing Centrum as often as he
likes.

This model ends where the model of `verify-kolejka-skrzynki` begins: at `Outbox.post` accepting a version. It keeps
only the newest version of each comment the queue accepted; what the queue then does with an older version posted later
is that model's (its configuration `starsza`). One model for both would multiply a state space that already takes
45 s.

Assumed, each a reason the check can pass while the code is wrong:

- **`os.replace` is atomic** (`replace_atomically`): a switch-off leaves the old Logs file or the new one.
- **One Centrum at a time builds the app**: `_listen_when_released` takes the port before `create_app`, and the old
  Centrum, which may still finish requests for `_GRACEFUL_SHUTDOWN_S` after it released the port, runs no Uruchomienie
  then (`shutdown_refusal`). A second process that bypassed the port would close the journal of a Wycena still running.
- **`send_left_behind` runs atomically** in the `AFTER_START` step, which `_Server.startup` runs after `lifespan` and
  the `start` entry, before it gives the event loop back to accept the first request, so it comes before any Wycena of
  that work.
- **The guard is idempotent**: Logs that passed `guard` pass it again unchanged, so rereading a file written by
  `close_left_behind` changes nothing; only Logs written without the guard (`StareLogi`) change. A number the guard
  masked becomes the text of its mask, which it leaves as it is. Idempotent means one version of the guard: Logs written
  by a Centrum whose guard masked less (before #851 nothing, before #863 the phone with `48` without `+`) are
  `StareLogi` for a newer one. It also means the memory of a start: the start guards before it reads any file of Dad's
  (ADR 0025). With the memory that wrote the Logs, a value equal to a field name in the place of a guard note is masked
  again in that note (5 of the words of the full Logs in the test of #936, 6 before it), but no step guards Logs twice
  with one memory.
- **A journal without its end entry is an Urwane Uruchomienie or one of the known findings `przed-wpisem-konca` and
  `wpis-konca-nieudany`.** A journal written by a build between #845 and #870/#871 has no end entry either, so a Wycena
  of such a build that reached its result without a Logs file gets Logi Urwanego Uruchomienia; no Wydanie has such a
  build (v0.4.3 has no journal), so only Maks's computers can have such a journal. Every Uruchomienie that reached its
  result reaches `RunHost.after` (`Run.work` catches an exception of `run_process` and goes on).
- **The queue keeps the newest version by `Version`** (rank, then the moment), as `verify-kolejka-skrzynki` checks, so
  the model keeps only the newest version each comment got (`najnowsza`). Its moments are abstract: a later `post` in one
  Centrum work has a later moment (`Outbox.post`), and a version of an earlier work an earlier one, unless the clock
  went back at a start since then (`cofniety`), when the order is either. Two versions of one rank compare by the moment
  only within one Centrum work (progresses; the Logi with the result and the Diagnoza, which the model leaves out) or
  between stand-in versions of one journal from two starts (a failed `unlink`), which have the same kind.
- **A progress is possible from the first line on the disk on**: the model counts it from `ZapiszStart` or the first
  successful `Wpis` to the end of the Wycena, the earliest `RunComments._progress` can send it, so every journal that
  may have a progress in the Skrzynka is checked; a progress that did not come yet only makes the check stricter.
- **`RunLog.model_validate_json(text).text == text`** for a file `close_left_behind` wrote, and two builds of the same
  journal give Logs with the same orders; their environment, tool and Dad's actions may differ, which the model leaves
  out. A rebuild happens only when the file is missing, so the file and the newest accepted Logi have the same orders,
  whichever of two stand-in versions of one journal the clock makes newer.

Left out: a glob of `logs/dzienniki-wyceny/` that fails (it skips every journal, like one failed read per journal), a
Logs file that cannot be parsed (truncated by hand, a schema from a newer version after a rollback: `close` sends the
result without Logi, `"nieczytelne"`), a torn entry in the middle of a journal (counted in `omitted`), a failed write
that left a torn first line (`run_ended` removes it like a whole one, and a start removes a journal without a start), the
Historia (no step of this path reads it), exceptions other than `OSError` in `close_left_behind`, and in `run_ended` an
exception outside a write (one in `_own` leaves the Logi with the result out of the queue, like `post` False: the
journal stays for the stand-in version), the text of the progress and of the result without Logi, the Diagnoza (a newer
version of the Logi with the result, of their rank and Centrum work), Dad's actions and the Centrum log in the Logs
(`DadActionJournal.take`, `CentrumLog.take_for_logs`), and the karta after the start (`RunCards.last`, which shows the Urwane Uruchomienie for
`przed-wpisem-konca` and `wpis-konca-nieudany`).
