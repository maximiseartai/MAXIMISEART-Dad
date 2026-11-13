---
name: verify-urwane-uruchomienie
description: Model-check with TLA+ (TLC) the trail of a Wycena w efenix that a switched-off Centrum cut short, across the next starts of Centrum, through the Dziennik Wyceny, the Logi Urwanego Uruchomienia, the progress comment of the Wycena and the end of a Wycena, up to the Kolejka wysyłki (`Outbox.post`). Use when `tools/skille_dla_zmiany.py` names it, when a change touches a definition in its `model/definicje.json` (`RunComments` and `RecordMaker` in `run_comments.py`, `Journal` and `LogsOnDisk` in `logs_disk.py`, `comment_versions.py`, `guard_logs`, `Rank` and `Version` in `outbox.py`, `create_app` in `app.py`, `Run.work` and `RunHost` in `runs.py`, `save` in `efenix_pricing.py`, `run_process`), or when the check of this skill fails.
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

Each promise is an invariant of `model/UrwaneUruchomienie.tla` (after `Obietnice`), and `Zbieganie` its liveness
property; the comment above each states it.
Its harm, which the model does not state:

- **DziennikPoKolejce**: Maks never learns that a Wycena stopped half-way and which order was in progress in efenix
  (D2 of #875: after the clock went back the progress was newer and the queue dropped the Logi).
- **BezUrwanychPoWyniku**: Maks reads „Centrum zamknęło się w trakcie” about a Wycena that finished, and in the
  Skrzynka these Logi replace the Logi with the result (same `run_id` and label, newer version).
- **TeSameZnaki**: the file in the Archiwum Logów okresu and the file at Dad's differ, so a replay from either (#847)
  sees another Uruchomienie.
- **PrzezStraznika**: a phone number or a street from an efenix page leaves Dad's computer (ADR 0025).
- **NicPrzedWznowieniem**: a version reaches the queue outside what the model of `verify-kolejka-skrzynki` checks,
  which takes this promise as given for every `post`.
- **ZaczeteWLogach**: Maks does not know which order may be half-priced in efenix.
- **WersjaKoncowa**: Maks reads „Wynik: jeszcze nie ma, Uruchomienie trwa” forever about a Wycena that ended or was
  cut (W2 of #875, #910).
- **LogiZostaja**: the newer version replaces the Logi in the queue and in the Skrzynka, so Maks loses the summary and
  the link to the full Logi, and without the network the full Logi (#871, W1 of round 3 of #846).
- **Zbieganie**: `logs/dzienniki-wyceny/` grows forever, or every start sends the same Logi again.

## Does the change touch it?

The check runs a hand-written TLA+ model, not the code, and the model describes the code only while you keep the two
in step.
Each action of `model/UrwaneUruchomienie.tla` is one indivisible step of the code, and the comment above the action
and its branches names that code; `model/definicje.json` holds a digest of every definition those comments name.

Three code steps carry more than their action's comment says:

- `StartWyceny`: an `OSError` of the last-start file goes out to `RunHost.start` before the progress.
- `Wyslij`: an exception of `post` or of `remove_journal` goes to the Centrum log (`unexpected_failure`), leaves the
  journal and goes on with the next version, as a failure of the queue or of the removal.
- `WyslijWynik`: an exception of `post` leaves no `accepted`, as a `post` that returned False.

Names in the comments that `model/definicje.json` leaves out on purpose:
`_refresh` and `_Watched` (they only decide when `RunComments._progress` runs, and the model lets a progress come at
any step it allows; `_progress` itself reads `ended` under the lock), `guard_text` (the text of a version without
Logi), `RunLog` as a whole (the schema of the Logs file, which changes with every new field; the model reads only
`ending`, whose values are `LoggedEnding`), `_outcome`, `efenix_trace.traced` and `StopError` (`ZmianaWEfenix` and
`Zatrzymanie` need only their place in `save` after `journal.begun` and before `journal.ended`), `metrics_saved` and
the Historia (no step of this path reads them since #870/#871: `RunCards` and the metrics files are the card's,
ADR 0017), and `create_app` as a whole.
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

Add such code to the model's comments and to `model/definicje.json`.

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

`--config NAME` runs one configuration of `model/konfiguracje.json`, `--strict` fails also on known findings.
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

1. Read the diff against the comments of the model's actions. Find each action whose code changed, or the new step that
   has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   TLA+ strings must be ASCII; comments may use Polish letters. Never weaken a promise or narrow a configuration to make
   the check pass.
3. A new way to fail gets a constant, a branch guarded by it, and a value in `stale` of every configuration in
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
version of the Logi with the result, of their rank and Centrum work), Dad's actions in the Logs
(`DadActionJournal.take`), and the karta after the start (`RunCards.last`, which shows the Urwane Uruchomienie for
`przed-wpisem-konca` and `wpis-konca-nieudany`).
