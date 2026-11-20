---
name: verify-aktualizacja-narzedzia
description: Model-check with TLA+ (TLC) that Aktualizacja narzędzia leaves Dad with a version that starts and with his own file in `config/`, that the restart guardian rolls back only a new version that really does not start, that Dad always ends with Centrum or a dialog, that the card says „Narzędzie zaktualizowane” only on the new version, and that the new version's card shows no failure of an earlier try, under every order of failures - fetch, git, pip, file copy, the result file, restart guardian, a new version that will not start, the computer switching off, and Dad clicking the desktop shortcut during the restart. Use when `tools/skille_dla_zmiany.py` lists it, when its Mutation checks step is red, or when asked whether an update can leave Dad without a working tool.
pilnuje:
  - src/rozliczenia/centrum/tool_update.py
  - src/rozliczenia/centrum/tool_updates.py
  - src/rozliczenia/centrum/restart_guardian.py
  - src/rozliczenia/centrum/launcher.py
  - src/rozliczenia/tool_files.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
---

# Verify Aktualizacja narzędzia (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_aktualizacje.py` (the `ci:` key) in Mutation checks on Windows whenever a change
touches this skill, so run it locally only while you bring the model in line or to reproduce a red
Mutation checks step. In CI the Mutation checks step does not start while covered code differs from its digests in `model/definicje.json`: it fails with a `ROZJAZD MODELU Z KODEM | <skill>: …` line, but it cannot tell whether your change to the model is right.
Run by hand, the script prints the same drift as an `UWAGA:` line above the verdict (Run).
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request.
What stays with you on every change to the covered code is „Bring the model in
line, then run”: read the diff against the table, change the model, break a new path in it, and run
the check while you do. A change whose model nobody brought in line is not verified, whatever CI says.

## The promise

**TataMaDzialajacaWersje**: whenever no Aktualizacja narzędzia is in progress
(it finished, failed, or the computer switched off in the middle), either the
tool's clone stands on a version that starts from Dad's desktop shortcut and
Dad's file in `config/` (today `worker_mapping.yaml`, with his real names) has
his content, or the journal „Aktualizacja w toku” is still on disk and Dad's
content is on disk too, in the clone or in the journal's copy.

**Postep**: a journal in progress always disappears. The shortcut, the guardian,
Centrum or Dad's next click finishes the update or rolls it back. When it disappears with
nothing in progress, `TataMaDzialajacaWersje` again demands a version that
starts and Dad's content in the clone.

**OpiekunCofaTylkoNieudana**: the restart guardian rolls the clone back from
a new version (`restart_guardian.main`, `_rolled_back` after `_answers(new, …,
after)`) only when that version really would not start, also when Dad clicks
the desktop shortcut while the guardian restarts Centrum.

**OkienkoTylkoGdyNicNieDziala**: the restart guardian shows its native dialog
`not_started_after_update` only when no Centrum runs. After a rollback, the
port may already belong to the old version that Dad started from the shortcut,
and then the guardian ends without the dialog (`_runs(…, before)`, #368), also
after a rollback when the port was never released (#726).

**TataNieZostajeBezOdpowiedzi**: when nothing runs any more (no update, no
guardian, no Centrum), Dad sees a native dialog with a Komunikat or a computer
that switched off, never only a card that no longer answers. The docstring of
`restart_guardian.py` and the docstring of `main` promise it: „karta nie ma już
z kim rozmawiać, więc tata widzi jedno okienko zamiast ciszy”.

**KartaNieKlamie**: the card says „Narzędzie zaktualizowane” only while
Centrum runs in the new version. Every Centrum reads the result file
(`config/centrum-aktualizacja.json`) once at start
(`ToolUpdates._after_restart`), and the docstring of `launcher._roll_back`
says the card of a rolled-back version must show the failure even when the
file already said „ok”.

**KartaNieStraszy**: the card of the new version, while it runs, shows no
failure of the update. A failure in the result file comes from the guardian or
the shortcut after it rolled the clone back to `przed`, so a Centrum in another
commit finds an old result: `_after_restart` logs `aktualizacja-wynik-stary`
and the card says nothing (#725).

Harm: Dad clicks `Zaktualizuj narzędzie` in the middle of a settlement week and
is left with a tool that will not start, or with names that have turned back
into the repository's sample, and only Maks can repair it. For the second
promise: Dad loses an update that worked, sees `NOWA_WERSJA_NIE_WYSTARTOWALA`,
and Maks gets a Zgłoszenie about a version that starts fine. For the third:
Dad sees „Centrum rozliczeń nie wystartowało” while Centrum works. For the
fourth: nothing starts and nothing tells Dad why. For the fifth: Dad sees
„Narzędzie zaktualizowane” on the old version, and Maks gets no Zgłoszenie
about a version that does not start. For the sixth: Dad sees „Nowa wersja
narzędzia nie wystartowała” on the version that started, and Maks gets a
Zgłoszenie about it.

ADR 0009 promises this as „Wszystko albo nic”, including the journal paragraph,
and „Opiekun … gdy nowa wersja nie wystartuje, cofa klon i uruchamia starą”
(#196).

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/AktualizacjaNarzedzia.tla`,
not the code. It describes the code only while you keep the two in step. Each
model action is one step of this code that ends before the next begins (one Git
command, one `shutil.copy2`, one run of pip, one guardian process):

| Model action | Code (`src/rozliczenia/centrum/`) |
| --- | --- |
| `Klik` | `tool_updates.py` `ToolUpdates.start` after `RunHost.begin_update` took the place of the one Uruchomienie at a time (its refusals are left out, see Scope), `_result` (`restart_guardian.prepare` copies the guardian into a new temporary folder before the clone changes); the card shows the progress. A click while a journal is in progress does not count toward `MaxKlikniec` (see Scope). The route `start` in `tool_update_router` refuses (`refusal.update_without_port`) before `ToolUpdates.start` when the server gives no TCP port of this Centrum, so nothing changes, as without a click |
| `Pobranie` | `tool_update.py` `ToolClone.update`: `_Journal.read`, and when no guardian may run (`guardian_may_run`) `_moved_back` before anything else (`cofa = "klik"`, `ROLLBACK_FAILED` when it fails); otherwise `_Git.fetch` of `main` and the Wydanie tags, `MainLine.newest()`, which is `newest_on_main` over `_main_tips`, the first-parent line of `main` (Wydania not on it are skipped; none left is `AKTUALNA`), `_Git.is_ancestor` (a clone that already contains the newest Wydanie is `AKTUALNA`), then up to `_DadFiles.leaving`, `_has_local_commits`, `_changed_tracked_files`; these refusals change nothing in the clone, like a failed fetch, so the model does not tell them apart |
| `KopiaPlikow` | `tool_update.py` `_Journal.begin`: `JournalKept` when a journal is in progress (only with a guardian's lease, since `Pobranie` rolls back any other), else copy and `fsync` of Dad's files into `pliki-taty`, then `stan.json` (`_write`: a temporary file, `fsync`, `os.replace`); `JournalKept` is `NIEOCZEKIWANY_BLAD` before anything changes |
| `CheckoutHead` | `tool_update.py` `_DadFiles.set_aside` before `yield`, `git checkout HEAD --` of Dad's file in `try`: a non-zero exit is `_NotSetAside`; past its time limit `_Git.run` raises `TimeoutExpired` instead, and on Windows `_run_tree` can raise `OSError` (no Job Object, `_join` failed, or the tree outlived `_KILL_TIMEOUT_S`) |
| `Scalanie` | `tool_update.py` `ToolClone.update`, `git merge --ff-only`, and `if not moved` (`journal.end()`) when Git refuses. `TimeoutExpired` or `OSError` from `_Git.run` (`_run_tree`) leaves `moved = False` and passes both `except` with the journal kept; the clone stays on `before` (Git never ran or was killed first) or on `after` (killed after the merge, e.g. in its `gc --auto`) |
| `PrzywroceniePoOdmowie`, `PrzywroceniePoScaleniu` | `tool_update.py` `_DadFiles.set_aside` `finally` (`_put_back`; its `OSError` becomes `_NotPutBack`) and `except _NotPutBack` in `ToolClone.update`: after the merge it calls `_moved_back`, before it returns `ROLLBACK_FAILED` and keeps the journal. After a refused merge or `except _NotSetAside` (`git checkout HEAD --` failed), `journal.end()`. |
| `PrzywroceniePoWyjatku` | `tool_update.py` `_DadFiles.set_aside` `finally` after `TimeoutExpired` or `OSError` from `git checkout HEAD --` or `git merge --ff-only`: `_put_back`, then the exception passes both `except` in `ToolClone.update` to `ToolUpdates._result` (`NIEOCZEKIWANY_BLAD`), and the journal stays; an `OSError` from `_put_back` is `_NotPutBack` and, with `moved = False`, `ROLLBACK_FAILED`, also with the journal kept |
| `Instalacja`, `InstalacjaKoniec` | `tool_update.py` `ToolClone._install_libraries` (`_Git.changed`, `pip_install`), the `try`/`except Exception` around it, and the `if installed is False` branch after it (both through `_moved_back`) |
| `CofanieUsun`, `CofanieReset`, `CofaniePrzywroc` | `tool_update.py` `_roll_back` (`_Journal.read` and `rev-parse HEAD` first, the clone on `przed` or `po`; when `rev-parse` raises, or the `unlink` of Dad's file before the `try` raises `OSError`, nothing changes and the rollback fails, while `unlink(missing_ok=True)` of a missing file does not raise; the old version tracks Dad's file, so `reset --keep` writes its content from the repository (`wzor`), and the libraries stay; a `reset --keep` that raises fails the rollback after `finally` puts Dad's file back, also when the clone already stood on `before`), called by `ToolClone.update` through `_moved_back` or by `tool_updates.py` `ToolUpdates._moved_back` through `ToolClone.roll_back` (`cofa = "centrum"`), by `restart_guardian._rolled_back` through `ToolClone.roll_back` (`cofa = "opiekun"`, or `"opiekun_bez_portu"` when the port was never released), by `launcher._roll_back` through `ToolClone.roll_back` (`cofa = "skrot"`), or by `ToolClone.update` before fetching through `_moved_back` (`cofa = "klik"`) |
| `KoniecDziennika` | `tool_update.py` `_Journal.end` (`stan.json` first, then the folder with the copy) at the end of `_roll_back` and in `ToolClone.update` after a refusal; then the guardian goes on to `OpiekunWynik`, the shortcut to `SkrotWynik`, and for `cofa = "klik"` `ToolClone.update` goes on to `rev-parse HEAD` and the fetch |
| `SkrotWynik` | `launcher.py` `_roll_back` after `ToolClone.roll_back`: `write_result` (`NIEOCZEKIWANY_BLAD`), then `subprocess.call(restart_from_disk)` in `launcher._start`, whose Centrum reads that result. An `OSError` from the write goes to `launcher.main`: the dialog `unexpected_start_failure`, nothing starts, and the old result file stays |
| `Restart` | `tool_updates.py` `ToolUpdates._update` (restarts only on `UPDATED`), `_restart` (`ToolClone.leased_to_guardian` around `restart_guardian.launch`: it writes the lease, and an `OSError` from that write leaves `stan.json` without it; it removes the lease when `launch` raises, and that removal can fail too), and `_moved_back` when either raises |
| `OpiekunPort`, `OpiekunStart` | `restart_guardian.py` `main`: `_port_released` (waits while a shortcut holds the port), `_record(restart, UPDATED)` (`write_result` in `suppress(OSError)`: a refused write leaves the file as it was, and the guardian goes on), `start_centrum` (the `start` of `main`, by default `_start_centrum`: `run_centrum.py --bez-okienek`, which skips the journal), `_answers(new, …, after)`, then `_stop`; without the port straight to `_rolled_back`, with no „ok” written. `OpiekunPort` takes `_port_released` and `_record` as one step, because only a starting Centrum reads the result file. `OpiekunStart` is the moment the new Centrum takes the port in `launcher._listen_when_released` and reads the result file: with `--bez-okienek` it retries `listen_locally` for `_SHORTCUT_HOLDS_PORT_S`, so it waits while a shortcut holds the port (#246) |
| `OpiekunKoniec` | `restart_guardian.py` `main`: `ToolClone.confirm_update` after `_answers(new, …, after)`; the journal disappears (`_Journal.end`) |
| `OpiekunWycofanie` | `restart_guardian.py` `main` after `_stop(new)`: `restart.result.unlink(missing_ok=True)` in `suppress(OSError)`, then `_rolled_back`. A refused removal leaves „ok”, which the old version's card shows as a failure (`StartCentrumZ`) |
| `OpiekunWynik` | `restart_guardian.py` `main` after `_rolled_back`: `_record` with `NEW_VERSION_FAILED` or `ROLLBACK_FAILED` (a refused write leaves the file, and the guardian goes on), then the old version when the rollback succeeded (`if rolled_back`), also after a port that was never released (#726), otherwise `OpiekunOkienko` |
| `OpiekunPortStara`, `OpiekunStartStara` | `restart_guardian.py` `main` after a successful rollback of a version that did not answer or of a port that was never released: `_port_released` (fails also while the old Centrum that did not close holds the port, which the model treats like another program) (fails while a Centrum started from the shortcut holds the port), `start_centrum` (with `--bez-okienek`, so the old version waits for the shortcut's port like the new one), `_answers(…, before)` (also answered by that Centrum), then `_runs(…, before)`, which ends without a dialog when that Centrum holds the port. Every guardian path that ends in the dialog goes through `OpiekunOkienko` |
| `OpiekunOkienko` | `restart_guardian.py` `main`: `show_problem` with `not_started_after_update`, then `return 1`. It follows `OpiekunWynik` after a failed rollback, a port held by another program after a rollback (`OpiekunPortStara`), and an old version that does not answer (`OpiekunStartStara`) |
| `Wylacz` | none: the computer switches off; the journal, its copy and the result file stay on disk |
| `DzierzawaMija` | none: `GUARDIAN_LEASE_S` passes after `lease_to_guardian` (`InterruptedUpdate.guardian_may_run`) |
| `Skrot` | `launcher.py` `_start` from the shortcut while nothing runs, as one step, since nothing else contends for the port: `listen_locally`, `ToolClone.interrupted_update` before the libraries load, then the dialog `update_finishing` while `guardian_may_run` (`_refuse`), `launcher._roll_back`, or the normal start (only "does it start") |
| `SkrotWTrakcie` | `launcher.py` `_start` from the shortcut while the guardian runs and no Centrum holds the port: `listen_locally` succeeds and the shortcut holds the port. When a Centrum holds it, `listen_locally` raises and the shortcut only asks `running_centrum`; nothing on disk changes, so the model leaves that case out |
| `SkrotOddajePort` | `launcher.py` `_start` after `listen_locally`: `ToolClone.interrupted_update`, `guardian_may_run`, then `listener.close()` and `update_finishing`; with no journal left (the guardian already rolled back) the normal start, which keeps the port |

Every action that starts a Centrum (`Skrot`, `SkrotOddajePort`, `SkrotWynik`,
`OpiekunStart`, `OpiekunStartStara`) also runs `tool_updates.py`
`ToolUpdates._after_restart` (`StartCentrumZ` in the model): `read_result`;
„ok” while the running commit (`self._commit()`, read when Centrum started) is
not its `po` becomes `NIEOCZEKIWANY_BLAD` (#490; in the model every „ok” has
`po` = `"nowa"`, so „ok” on `head = "stara"` is a failure);
a failure while the running commit is not its `przed` is old: the log gets
`aktualizacja-wynik-stary`, the file is removed in `suppress(OSError)`, and
the card says nothing (#725; in the model every update starts on `head =
"stara"`, so a failure on `head = "nowa"` says nothing);
`CentrumLog.update_awaits` (#491) lets the result through only when the
Centrum log cannot be read or has no `aktualizacja-start`, or its last update entry is
`aktualizacja-start` with the result's `przed`, or `aktualizacja-koniec
wynik=ok` with the result's `przed` and `po` and a result other than „ok” (the
new version wrote „ok”, then the guardian rolled it back); any other result
(already reported, also when a later click failed with the same commits, or of
an older Aktualizacja) is skipped and its file removed in
`suppress(OSError)`; otherwise the log gets `aktualizacja-koniec`, `unlink`
(a refused removal keeps the file and logs `aktualizacja-wynik-zostaje`, and
the next start skips it), and the card from `_view_of`. The model does not
hold the Centrum log, so it lets every start skip the result: the card then
says nothing, never „updated”.

Definitions the actions share:

| Model definition | Code |
| --- | --- |
| `Program` | the steps of the code: Centrum, the guardian, and the shortcut that rolls back or gives back the port |
| `Startuje(wersja)` | whether `run_centrum.py` of the clone starts from Dad's shortcut: the new version only with its libraries and `nowaStartuje`, the old one with any libraries (Scope) |
| `NieudaneCofniecie(opis)` | a `_roll_back` that raised: the journal stays. In Centrum `_moved_back` returns False and the result is `COFNIECIE_NIEUDANE`; the guardian (`_rolled_back` returns False) writes it (`OpiekunWynik`), shows the dialog and ends; the shortcut ends with the dialog `NIEOCZEKIWANY_BLAD_STARTU` (the exception of `launcher._roll_back` reaches `launcher.main`, `_refuse`) and starts nothing |
| `Cofaj(kto, opis)` | entering `_roll_back`; `cofa` decides what follows it |
| `PoOdmowie(opis)` | the clone did not move and Dad's files are back: `ToolClone.update` removes the journal |
| `KartaZ(w)`, `StartCentrumZ(w)` | `ToolUpdates._after_restart` (`read_result`, `_view_of`) of a Centrum that starts on `head` with the result file `w`, as the paragraph after the table says |
| `DzialaOpiekun` | the guardian runs (from `Restart` to its last step) and the port is free: the old Centrum closed, the new one has not taken it yet |
| `Idz`, `Slad` | a step of the update or the guardian, which leaves a shortcut clicked meanwhile (`skrot`) alone; `Slad` also adds the cause of a known finding to `slady` |
| `TrescTatyNaDysku`, `Po(wybaczone)` | Dad's content is on disk, in the clone or in the journal's copy (without a copy the rollback does not touch the clone's file); a run in which a cause of `Wybaczone…` happened, and since `slady` only grows, `<>Po(…)` in `PostepPozaZnanymi` |

Each constant is a way to fail or a bound of a configuration (`stale` in `model/konfiguracje.json`):

| Constant | Meaning |
| --- | --- |
| `MaxKlikniec` | Dad's clicks of „Zaktualizuj narzędzie” |
| `OdmowaScalenia` | `merge --ff-only` refuses before anything changes: `ZMIANY_NA_KOMPUTERZE` |
| `AwariaPobrania` | `_Git.fetch` fails (no network, login): `BRAK_POLACZENIA`, `LOGOWANIE` |
| `AwariaBibliotek` | `pip_install` returns False (pip error, time limit): `INSTALACJA_BIBLIOTEK` |
| `AwariaOpiekuna` | `restart_guardian.launch` raises, or the old Centrum does not release the port within `PORT_TIMEOUT_S` |
| `AwariaGita` | `git checkout HEAD --` (`set_aside`) exits non-zero (`_NotSetAside`); `git diff` (`changed`), `rev-parse HEAD` and `git reset --keep` (`_roll_back`) raise `GitFailed`; and each of `git checkout HEAD --`, `git merge --ff-only`, `git diff`, `rev-parse HEAD` and `git reset --keep` raises `TimeoutExpired` past its time limit or `OSError` from `_run_tree` (no Windows job, or a tree that outlives `_KILL_TIMEOUT_S`) |
| `AwariaKopiowania` | `OSError` from the disk (disk, antivirus, OneDrive): `shutil.copy2` of Dad's file, a write of `stan.json` (also of the lease), a write (`write_result`) or removal of the result file, the removal of Dad's file from the clone in `_roll_back` |
| `NieudanyStart` | the new version does not answer within `START_TIMEOUT_S`, although it has its libraries |
| `Wylaczenie` | the computer switches off or a process dies at any step |
| `MaxSkrotowWTrakcie` | Dad's clicks of the desktop shortcut while the restart guardian runs |
| `Wybaczone…` | the causes of known findings that the `…PozaZnanymi` variant of each promise skips; the script sets them |

| Variable | Meaning |
| --- | --- |
| `head`, `plikTaty`, `kopia`, `biblioteki`, `dziennik`, `dzierzawa` (`dysk`) | Dad's disk, which outlives Centrum and a switch-off: the clone's commit (`stara` before the click, `nowa` the newest Wydanie); `config/worker_mapping.yaml` in the clone (Dad's, `wzor` from the repository's HEAD, or none); the copy of Dad's file in the journal (`centrum-aktualizacja-w-toku/pliki-taty`); Dad's Python libraries (old, partial after a killed or failed pip, new); the journal „Aktualizacja w toku” (`stan.json`); its `opiekun_do`, valid while the restart guardian may run |
| `nowaUsuwaPlikTaty`, `nowaZmieniaWymagania`, `nowaStartuje` | the new version, chosen once: it removes or stops tracking Dad's file (`_DadFiles.leaving` finds it), it changes `requirements.txt` (`_Git.changed`), it answers `/api/health` with its libraries |
| `centrum`, `pc`, `krok` | the version of the running Centrum (or none), the step of the update (`spoczynek` while none runs), and the last step in the code's words, from which the counterexample is told |
| `slady` | the causes of known findings that already happened |
| `klikniecia` | the counter of the `MaxKlikniec` constant |
| `skrot`, `skrotyWTrakcie` | a shortcut clicked while the guardian runs holds the port from `listen_locally` to `listener.close()`; how many such clicks Dad made |
| `cofa` | who calls `_roll_back`: `centrum` (`ToolClone.update`, `ToolUpdates._moved_back`, also after a refused merge), `klik` (`ToolClone.update` before the fetch, on a journal without a guardian's lease), `opiekun` (`restart_guardian._rolled_back` after a new version that does not answer), `opiekun_bez_portu` (the same when the port was never released) or `skrot` (`launcher._roll_back` at start) |
| `wynik` | `config/centrum-aktualizacja.json` (`write_result`): none, „ok” (`UPDATED`) or a failure (any other code) |
| `karta` | what the card of the running Centrum says from the result file (`ToolUpdates._after_restart`): nothing, „zaktualizowano” or a failure; results Centrum has on its own are left out |
| `widzi` | what Dad has in front of him: Centrum, nothing (Centrum closed, nothing started), the native dialog with a Komunikat startu, or a switched-off computer |

Covered files, each as a whole file (`model/definicje.json`): `src/rozliczenia/centrum/tool_update.py`,
`src/rozliczenia/centrum/tool_updates.py`,
`src/rozliczenia/centrum/restart_guardian.py`,
`src/rozliczenia/centrum/launcher.py`, and in `src/rozliczenia/tool_files.py` the port
(`listen_locally`, `port_free`, `_bound`), the guardian's start command (`start_command`,
`centrum_script`) and the clone's `config_dir`.

The digests in `model/definicje.json` were taken when every row of the table was last checked
against the code (`tools/przesun_model.py`); what that check found is in the message of the commit
that changed the digests. To see what changed since:

```bash
git diff $(git log -1 --format=%h -- .agents/skills/verify-aktualizacja-narzedzia/model/definicje.json) -- src/rozliczenia/centrum/tool_update.py src/rozliczenia/centrum/tool_updates.py src/rozliczenia/centrum/restart_guardian.py src/rozliczenia/centrum/launcher.py src/rozliczenia/tool_files.py
```

A change matters when it changes the order of these steps, adds or removes a
step that touches the clone, Dad's files, the libraries, the result file or the
running Centrum, changes which exception is caught where, or adds a new way to
fail. Changes to Komunikaty text, the log or Zgłoszenia do not matter here, and
the card matters only where it reads the result file (`_after_restart`,
`_view_of`).

## Bring the model in line, then run

Do this for your own change and for a change you review. Update the model
before you trust a verdict. With an outdated model the check passes on code it
no longer describes.

1. Read the diff of the covered files since their digests (the `git diff`
   above; the drift line names each changed file and definition). For each
   hunk, find its row in the table.
2. Change the matching actions so that one action stays one indivisible step
   of the code, and write the code's names in its row of the table, not in a
   comment: the model has none, and a new action, definition, constant or
   variable gets its own row. TLA+ strings must be ASCII (no Polish letters
   inside `"…"`).
3. A new way to fail gets a `CONSTANT` with its row, a branch guarded by it, and a value in
   `stale` of every configuration in `model/konfiguracje.json`. Turn it on in the
   configuration whose theme fits, or give it its own configuration there.
4. Run the check (next section).
5. Before you trust a pass on a new code path, break that path in the model
   (drop its rollback, say) and see the check fail. Before you trust a
   failure, read it as described in „Real bug or modeling error?”.
6. If the change rewrites the code behind a known finding, rewrite that
   finding below and its `znalezisko` in `model/konfiguracje.json` in the same
   change.
7. Run `tools/przesun_model.py verify-aktualizacja-narzedzia` only after you
   have checked every row of the table against the code, and commit the new
   digests with the model and that code.

## Run

```bash
.venv/bin/python .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
```

On Windows use `py -3 .agents\skills\verify-aktualizacja-narzedzia\scripts\sprawdz_aktualizacje.py`.
No system Java is needed: the first run downloads a pinned Java runtime packaged for pip (about 50 MB) and `tla2tools.jar` into `.verification/formal-aktualizacja/`, which Git ignores.
After that a run takes about 6 s, offline.
The pins, the download, its retries and its CI cache live in `tools/lib/narzedzia_tlc.py`, and the run of TLC, the verdict and the known findings in `tools/lib/model_tlc.py`, which every skill with a TLA+ model shares.
A last line `BŁĄD POBIERANIA NARZĘDZIA TLC` is a failed download, not a model verdict.
A jar in the folder with another SHA-256 is downloaded again.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `AKTUALIZACJA OK` | 0 | The promise holds in every configuration. |
| `AKTUALIZACJA OK, ZNANE ZNALEZISKA: n` | 0 | Only the known findings below break the promise. Each is printed with its counterexample, and every other path passes. |
| `AKTUALIZACJA: NOWE NARUSZENIE (n)` | 1 | The promise breaks in a way that is not a known finding. The counterexample is printed. |
| `AKTUALIZACJA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding no longer happens. If you fixed it, remove it from `znane` of its configuration in `model/konfiguracje.json` and from the findings below. |
| `AKTUALIZACJA: BŁĄD MODELU (n)` | 2 | TLC gave no verdict (a syntax error in the model), an invariant outside the promises such as `TypeOK` broke, or `model/konfiguracje.json` has another shape. Nothing is known about the promise. |

`UWAGA: kod opisany modelem zmienił się: …` means a covered file differs from its
digest. Until you have done „Bring the model in line”, the verdict above
it means nothing.

## Configurations

Each configuration in `model/konfiguracje.json` (its `opis`, its constants in
`stale` and its known findings in `znane`) turns on a set of failures, and the
script writes its `.cfg` with `TypeOK` and every promise. TLC explores every order of
steps and failures, for every kind of new version: it does or does not drop
Dad's file, it does or does not change `requirements.txt`, and (in every
configuration except `zwykle-awarie`) it does or does not start, so the
guardian's rollback meets every other failure too.

| Config | Failures on | Expected |
| --- | --- | --- |
| `zwykle-awarie` | merge refused (`ZMIANY_NA_KOMPUTERZE`), fetch fails (`BRAK_POLACZENIA`), pip fails (`INSTALACJA_BIBLIOTEK`), guardian does not start or the port is not released | passes |
| `git` | the above + a new version that may not start + `GitFailed` from `git checkout HEAD --`, `git diff`, `git reset --keep`, and `TimeoutExpired` or `OSError` (`_run_tree`) from `git checkout HEAD --`, `git merge --ff-only`, `git diff`, `rev-parse HEAD` and `git reset --keep` in `_roll_back` | passes |
| `kopiowanie` | the above without git + `OSError` from `shutil.copy2` of Dad's file, a write of `stan.json` (also the lease), a write or removal of the result file, or the `unlink` of Dad's file in `_roll_back` | passes |
| `nieudany-start` | `zwykle-awarie` + the new version does not answer in `START_TIMEOUT_S` | passes |
| `wylaczenie` | `nieudany-start` + the computer switches off at any step | passes |
| `wylaczenie-i-dysk` | `wylaczenie` + the disk failures of `kopiowanie` | passes |
| `skrot-w-trakcie` | `nieudany-start` + Dad clicks the desktop shortcut up to twice (`MaxSkrotowWTrakcie = 2`) while the guardian runs | passes |

Every configuration checks the invariants `TataMaDzialajacaWersje`,
`OpiekunCofaTylkoNieudana`, `OkienkoTylkoGdyNicNieDziala`,
`TataNieZostajeBezOdpowiedzi`, `KartaNieKlamie` and `KartaNieStraszy` and the liveness property
`Postep`, under the fairness in `Sprawiedliwosc` (see Scope). A broken invariant prints
`naruszone <name>:` and its harm in one sentence.
A broken `Postep` prints `naruszone Postep` and a counterexample that ends in a
loop: `(dalej nic się nie dzieje)` or `(stąd znów krok n i tak bez końca)`.

A known finding names the promise it breaks (`obietnica`) and its cause (`przyczyna`), a tag that `Slad(...)` adds to `slady` and `Po(...)` checks.
How each known finding runs on its own and excused (`…PozaZnanymi`, `Wybaczone<promise>`) is in `tools/lib/model_tlc.py`; the `…PozaZnanymi` variants are `obietnice` of `MODEL` in the script.

## Known findings

None. A new one goes here with its configuration, the invariant it breaks, its
counterexample in the code's words, and its harm.

Fixed:

- #725 (`kopiowanie`, `wylaczenie-i-dysk`, breaks `KartaNieStraszy`): the new
  version that runs showed „Nowa wersja narzędzia nie wystartowała”. The
  guardian rolled back the first try without the port and wrote the failure,
  the disk refused the old version's card the removal of the file, the second
  click worked, and the disk refused the guardian the write of „ok”. In
  `wylaczenie-i-dysk` a switch-off and the shortcut's `NIEOCZEKIWANY_BLAD` gave
  the same end. `_after_restart` now compares a failure's `przed` with the
  running commit. With `KartaZ` back to „a failure is shown on any version”,
  both configurations report a new violation.
- #726 (`skrot-w-trakcie`, breaks `OkienkoTylkoGdyNicNieDziala` without its
  former exception for `cofa = "opiekun_bez_portu"`): the guardian rolled back
  without the port, the old Centrum let the port go during the rollback, Dad's
  shortcut started the old version, and the guardian showed the dialog without
  asking the port. After that rollback the guardian now goes on like after a
  released port (`_port_released`, `_answers(…, before)`, `_runs(…, before)`).
  With `OpiekunWynik` back to the dialog after `opiekun_bez_portu`, the check
  reports a new violation.
- #490 (`kopiowanie`, `wylaczenie`, `wylaczenie-i-dysk`, breaks
  `KartaNieKlamie`): „ok” stayed on disk and the old version said „Narzędzie
  zaktualizowane”. `ok_po_dwoch_odmowach`: the new version did not answer, and
  the disk refused the guardian both the removal of „ok” and the write of the
  failure. `skrot_gasnie_przed_wynikiem`: the computer switched off before the
  new Centrum read „ok” and again between the shortcut's rollback and its
  `write_result`. Mixed: one switch-off and one refused `write_result` in
  `launcher._roll_back` gave the same end. `_after_restart` now compares „ok”
  with the running commit, so the old version shows `NIEOCZEKIWANY_BLAD`. With
  `KartaZ` back to „ok” is „updated”, `kopiowanie`, `wylaczenie` and
  `wylaczenie-i-dysk` report a new violation.
- `bd7c9ff8` (`kopiowanie`, `wylaczenie`, `skrot-w-trakcie`): a refused
  `write_result` ended `restart_guardian.main` with nothing started and no
  dialog (`TataNieZostajeBezOdpowiedzi`), and „ok” stayed on disk through the
  rollback, so in the model a Centrum started from the shortcut, or after a
  switch-off, said „Narzędzie zaktualizowane” on the old version
  (`KartaNieKlamie`). The
  guardian now goes on after a refused write and removes „ok” right after
  `_stop`. With either change undone in the model, the check reports a new
  violation.

- #246 (`skrot_zajmuje_port`, `skrot-w-trakcie`): Dad clicked the desktop
  shortcut while the guardian restarted Centrum. The shortcut held the port
  between `listen_locally` and `listener.close()`, the new Centrum ended with
  `PORT_ZAJETY`, and the guardian rolled back a version that works. Centrum
  started with `--bez-okienek` now retries `listen_locally` for
  `_SHORTCUT_HOLDS_PORT_S` (10 s); the old version after a rollback starts
  the same way.
- #212 (`bez_opiekuna`): Centrum rolls the clone back when
  `restart_guardian.launch` raises, and the guardian rolls it back when the
  port is not released, then shows the dialog.
- #213 (`wylaczenie`): the journal „Aktualizacja w toku” survives a
  switch-off, and the next start from the shortcut rolls the clone back from
  it before it loads any library.
- #210 (`reset`) and #211 (`kopiowanie`): a failed `git reset --keep` or
  `copy2` in Centrum keeps the journal, and Dad's next click rolls the clone
  back from it before it fetches. Before, that click answered `AKTUALNA` on
  the new commit, and nothing in Centrum finished the journal.

## Real bug or modeling error?

Read the counterexample as steps in the code's words, then check each step
against its row in the table:

- If every step is something the code can do, in that order, and the end state
  (`klon na wersji …, plik taty: …, biblioteki: …`) is what the disk would
  hold, it is a real bug. Report it with the counterexample. Do not weaken
  `TataMaDzialajacaWersje`, remove a failure, widen a `Wybaczone…`, or change product
  code unless the user asks.
- If a step cannot happen in the code (an exception the code catches, an order
  the code does not allow, two code steps merged into one), the model is
  wrong. Fix the action and cite the line that proves it.
- `TypeOK` breaking is always a modeling error.

## Scope

Verified, with `MaxKlikniec = 2` and one newer `main` that does not move again
during the run: the result file and what the card says from it (updated or a
failure), and whether Dad ends with Centrum, a dialog or a switched-off
computer, under every order of the failures above, across both clicks, a
shortcut start after a failure or a switch-off (also a switch-off during the
shortcut's own rollback), up to two shortcut clicks while the guardian runs
(`skrot-w-trakcie`, with the guardian's failures and a new version that may not
start, but without switch-offs or Git and copy failures), and all eight kinds
of new version.

`Postep` holds only under these assumptions (`Sprawiedliwosc` and the premise
of `Postep`):

- Running code takes its next step, Dad clicks again while Centrum runs and
  he has clicks left, and he starts the shortcut while Centrum is not running.
- After `COFNIECIE_NIEUDANE` Dad clicks again, as the Komunikat tells him.
  These clicks do not count toward `MaxKlikniec`; with them counted, two
  clicks used before a failed rollback leave the journal for good.
- Git and copy failures are transient: a rollback retried without end
  succeeds at some point (strong fairness on `CofanieUsunUdane`,
  `CofanieResetUdane` and `CofaniePrzywrocUdane`). A disk that fails for good leaves the journal and
  a Komunikat startu at every start.
- The computer switches off finitely many times.
- `GUARDIAN_LEASE_S` (10 minutes) passes at some point, also while Dad keeps
  clicking (strong fairness), and only when no code runs and no shortcut
  holds the port (it holds it for a moment). The guardian takes at most twice `PORT_TIMEOUT_S` plus twice
  `START_TIMEOUT_S` plus a rollback, well under 10 minutes. A shortcut start
  while the guardian runs is modelled (`skrot-w-trakcie`, at most
  `MaxSkrotowWTrakcie` clicks, so `Postep` does not have to survive endless
  clicking). Not covered: a computer that sleeps longer than the lease while
  the guardian waits, after which a shortcut start could roll back under the
  guardian.

Assumed, and not checked:

- Deleting `stan.json` (`_Journal.end`) succeeds. If it raises, every caller
  handles it like a failed rollback, and the journal stays for the next start.
- The clone stands on the journal's `przed` or `po` whenever it is read.
  Anything else (Maks changed the clone) is `JournalKept`: nothing is rolled
  back and the shortcut shows `NIEOCZEKIWANY_BLAD_STARTU`.

- Each Git command, each `copy2` and the guardian are indivisible. A switch-off
  in the middle of `git merge` (a half-updated working tree) is not modelled;
  the shortcut's `git reset --keep` would then meet a half-updated tree.
  Since `c89f75c0` (#401) a Git tree that outlives `_KILL_TIMEOUT_S` raises
  `OSError` while Git may still run. The model ends the Git step there, so a
  merge or reset that finishes later, after `_put_back` or during the next
  click's rollback, is not modelled. That rollback most likely fails on Git's
  `index.lock` and keeps the journal (a guess, not checked).
- The old version starts with any libraries, because in `requirements.txt`
  the libraries Centrum imports have lower bounds, and Centrum does not check
  the one upper bound (Playwright `<1.65`, #1242) when it starts, so the old
  version also starts with a newer Playwright left by rolling back an update
  that lifted that bound; the one exact pin is a test library (`hypothesis`)
  that Centrum does not import. Pip killed between uninstalling and installing
  a library could break this, so the `wylaczenie` model is optimistic.
- Dad has one file in `config/`. His untracked files (Wzorce, Ustawienia Centrum,
  the Zgłoszenia key, the log, metrics, period files, and in `config/` the
  read Powiadomienia, the Sprawy taty and the outbox addresses) are not
  modelled. Git does not touch them while no Wydanie tracks their path. When
  a Wydanie tracks one, it depends on `.gitignore`. For a file that is not
  ignored (`config/powiadomienia.json`, `config/sprawy-taty.json`,
  `config/skrzynka-adresy.jsonl`), `merge` refuses. Git treats an ignored file
  (`*.xlsx`, `logs/`, `config/centrum-ustawienia.yaml` and the rest of
  `.gitignore`) as expendable, so `git merge --ff-only` overwrites Dad's file
  without refusing (Git 2.50). When the digests were last taken, no tracked file matched
  `.gitignore` (`git ls-files -ci --exclude-standard` was empty).
- A shortcut clicked while the guardian runs gives the port back within
  `_SHORTCUT_HOLDS_PORT_S` (10 s), because between `listen_locally` and
  `listener.close()` it only reads the journal on the local disk. The model
  lets `OpiekunStart` and `OpiekunStartStara` wait for it without a limit. A
  shortcut process that stalls longer brings `skrot_zajmuje_port` back. No
  promise checks the wait in `OpiekunStartStara`: without it the old version
  ends with `PORT_ZAJETY`, and `_runs(…, before)` still finds the shortcut's
  Centrum, so Dad sees no dialog either way.
- An old Centrum that still holds the port after `PORT_TIMEOUT_S` does not
  answer `health`. `uvicorn.Server.shutdown` closes the listening sockets
  before it waits for open connections (read in the installed uvicorn, after
  `_Server.shutdown` logs `stop`), and `main_loop` notices `should_exit` every
  0.1 s, so a Centrum that keeps the port has an event loop that never got
  there and does not answer either. If it did answer in commit `before`, the
  guardian would end without the dialog after a rollback without the port, and
  Dad would see a dead card once that Centrum closes. The model treats that
  holder like another program (`OpiekunPortStara`). Not checked against a
  running Centrum.
- The guardian shows the dialog right after it decides on it (`_runs`
  returns, then `show_problem`), so `DzialaOpiekun` leaves out
  `pc = "okienko"` and no shortcut click falls between the two. With
  `"okienko"` in `DzialaOpiekun`, the check breaks on a shortcut that starts
  Centrum in that microsecond gap.
- `write_result` writes a temporary file and replaces the result file with
  `os.replace`, so a refused write leaves the old content. A Centrum reads the
  result file in the same step as it takes the port. A new version that reads
  „ok” and then does not answer is one that does not start, so the model
  never lets it read the file; its card dies with it.
- `TataNieZostajeBezOdpowiedzi` counts the dialog `update_finishing` of a
  shortcut clicked while the guardian runs as nothing, because the guardian
  goes on and decides what Dad sees last.
- `git checkout HEAD --` killed at its time limit may or may not have
  rewritten Dad's file; the model allows both. `git merge --ff-only` that
  raises leaves the clone on `before` or `after`; a merge killed in the middle
  of the working tree is not modelled, like a switch-off there.
- An `OSError` from a Git command in `Pobranie` (before the journal) goes to
  `ToolUpdates._result` as `NIEOCZEKIWANY_BLAD`, also from `fetch`, which
  catches only `TimeoutExpired`. The clone does not change, so the model does
  not tell it from `BRAK_POLACZENIA`.
- A shortcut whose `listen_locally` fails only asks `running_centrum` and
  changes nothing on disk, so the model leaves it out. Its wrong Komunikaty
  are not checked: `PORT_ZAJETY` when Centrum is still starting and does not
  answer `health` in 5 s, `INNA_WERSJA_CENTRUM` while the old Centrum is still
  closing.
- Not covered: what the card shows beyond „updated” or a failure from the
  result file (its own results such as `AKTUALNA`, the progress, the
  Zgłoszenie), the text of a Komunikat, the Centrum log (the model lets every
  start skip the result, as if the log already had it, so whether a failure is
  shown at all is not checked), `RunHost` refusals
  during an Uruchomienie procesu, an unreadable result file (`read_result`
  returns `None`, like no file), and whether the browser reconnects. For those
  use `verify-centrum-rozliczen` with `--feature aktualizacja`.
