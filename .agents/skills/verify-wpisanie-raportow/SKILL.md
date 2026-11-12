---
name: verify-wpisanie-raportow
description: Model-check with TLA+ (TLC) one report cell of Wpisanie raportów z maili (ADR 0028, spec #1224) across Dad's click „Wpisz raporty z maili” (`enter_from_mail` in `src/rozliczenia/report_entering.py`), the cell rules (`reconcile` in `src/rozliczenia/worker_reports/_cells.py`), the three files in `config/` (memory of own entries `wpisanie-raportow-stan.json`, the result for the Raporty view `wpisanie-raportow-wynik.json` and the „Zostaw moją” decisions `wpisanie-raportow-decyzje.json`, written through `FileReportState` and `_TextFile` in `src/rozliczenia/centrum/report_entering_state.py` on `StateFile` in `atomic_file.py`, whose failed write waits in memory), „Zostaw moją” from another tab (`ReportEnteringEntry.keep` in `report_entering_run.py`, `FileReportState.keep` under `_deciding`), Dad or his worker changing the cell in Excel, a new mail, a Plik zbiorczy that closes and reopens the period, an OneDrive conflict copy, a refused INTERMAX write and Centrum switching off at any step. It checks that the tool never overwrites a value Dad typed, that „Zostaw moją” keeps the difference out of the view, that the tool's own entry never shows as a manual difference, and that a conflict copy stops the click. Use when a change touches `reconcile`, `enter_reports`, `Window.of` or `Window.opens`, `OwnEntries` or `Kept`, `enter_from_mail` (the order of `write_cells`, `save_memory`, `save_result` and the conflict checks), `_closed`, `SavedState`, `write_cells` (what it returns), `_TextFile`, `FileReportState` (`load`, `save_memory`, `save_result`, `shown`, `kept`, `keep`, `of_work`), `ReportEnteringEntry.keep` or `view`, `_view`, `StateFile`, the assignment `report_files` in `create_app`, `RunHost.start`, or when the check of this skill fails.
pilnuje:
  - src/rozliczenia/worker_reports/_cells.py
  - src/rozliczenia/worker_reports/_model.py
  - src/rozliczenia/worker_reports/__init__.py
  - src/rozliczenia/report_entering.py
  - src/rozliczenia/intermax_cells.py
  - src/rozliczenia/centrum/report_entering_state.py
  - src/rozliczenia/centrum/report_entering_run.py
  - src/rozliczenia/centrum/atomic_file.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/runs.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-wpisanie-raportow/scripts/sprawdz_wpisanie_raportow.py
---

# Verify Wpisanie raportów (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_wpisanie_raportow.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step.
In CI the Mutation checks step does not start while covered code differs from its digests in `model/definicje.json`: it fails with a `ROZJAZD MODELU Z KODEM | <skill>: …` line, but it cannot tell whether your change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_model_wpisania_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_wpisanie_raportow.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line”: read the diff against the table,
change the model, break the new path in it, replay each new counterexample on the code, and recompute the digests.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

Dad clicks „Wpisz raporty z maili” when his worker is not in INTERMAX. Each click reads every Raport wykonawcy from the
open days again and writes `tak`/`nie` and the activities into `SKUTECZNE` and `CZYNNOŚCI ZREALIZOWANE`. ADR 0028:
„Pamięta tylko to, co samo wpisało, bo bez tego nie odróżni własnego wpisu od ręcznego” and „pisze tylko do pustej
komórki albo do własnego wcześniejszego wpisu, którego nikt potem nie zmienił”. Three files in `config/` carry the
state between clicks, each with one writer, each written atomically, and a write that fails waits in the memory of
this Centrum work (`StateFile`, `_TextFile`) until a later write or read retries it. The model checks, over every
order of steps:

- **NieNadpisuje**: a Wpis replaces only an empty cell or the tool's own earlier entry; never a value Dad or his worker
  typed (docstring of `reconcile`: „wartość ręczna równa Wpisowi do pamięci nie trafia, żeby późniejsza poprawka nie
  nadpisała taty”). Harm: Dad's correction disappears from INTERMAX and from the Rozliczenia, and there is no Kopia
  INTERMAX to bring it back (ADR 0028: „Bez Kopii INTERMAX”).
- **ZostawUcisza**: once „Zostaw moją” returned the Raporty view without the difference, the view never shows that
  difference (the same cell and the same content of the Wpis) again (docstring of `Kept`: „różnica z tą treścią nie
  wraca”; `report_entering_run.py`: „różnica … znika z widoku od razu”). „Zostaw moją” never writes INTERMAX by
  construction (`keep` has no write), and the Wpis never replaces Dad's value after it, which is NieNadpisuje. Harm: Dad
  decides the same difference again, or stops trusting the view.
- **BezFalszywejRoznicy**: a difference with a manual value (`ManualDifference`) stands only at a value Dad or his worker
  typed, never at the tool's own entry. Harm: Dad sees „ręczna wartość zostaje” about a value he never typed, and a
  worker's correction of a report never reaches INTERMAX (direction safe: nothing is overwritten).
- **KopiaZatrzymuje**: a click does not read the mailbox while an OneDrive conflict copy lies beside INTERMAX
  (`report_entering.py` :276), and a copy that appeared until the end of the write ends the click with a Zatrzymanie
  for Dad, not a summary (:385; ADR 0028: „Gdy po zapisie obok INTERMAX pojawi się kopia konfliktu OneDrive, następuje
  Zatrzymanie dla taty”). Harm: the worker's change sits only in the copy, Dad does not learn it, and the Rozliczenia go
  out without it.

## Why a model of its own

`verify-zapis-intermax` checks the bytes of the INTERMAX write: that `write_cells` replaces only the bytes it read and
leaves exactly the planned cells changed (DOKLADNIE_WPISANE, BEZ_KOPII). Here that write is one indivisible step that
succeeds or is refused, and the state is what lies around it: the cell's value and who typed it, the newest Wpis, the
three files with their waiting texts, the click's snapshot and the „Zostaw moją” requests. One cell is enough, because
`reconcile`, the memory and the decisions work per cell (`OrderKey`, `ReportColumn`): two cells never share an entry.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/WpisanieRaportow.tla`, not the code. It describes the code only while
you keep the two in step. Each model action is one indivisible step of this code (`src/rozliczenia/` unless named
otherwise):

| Model action | Code |
| --- | --- |
| `TataZmienia` | Dad or his worker (through OneDrive) types a value into the cell or clears it and saves INTERMAX |
| `NowyMail` | a Raport wykonawcy with another content of the Wpis for this order arrives; the latest mail wins (`enter_reports`) |
| `ZamkniecieOkresu`, `OtwarcieOkresu` | the Plik zbiorczy of the period appears (Przygotowanie) or Dad removes it; `report_entering._closed` gives `Window.of` the closed tokens and `Window.opens` leaves the order out of `orders` in `enter_reports` |
| `PojawiaSieKopia`, `TataUsuwaKopie` | OneDrive puts a conflict copy beside INTERMAX; Dad merges it and removes it |
| `Sprawdzanie` | Dad clicks; `RunHost.start` (one Uruchomienie at a time), `enter_from_mail` `check`: `FileReportState.load`, which reads the memory through `_TextFile.text` (`StateFile.retry` first, then the waiting text or the file) and `kept()` the same way, then `onedrive_conflicts.beside` (:276), whose copy is a Zatrzymanie before the mailbox |
| `Zapis` | `read` (mailbox, `register_file.read`), `plan` (`enter_reports` → `_cells.reconcile` on the snapshot `saved.memory`, `saved.kept`) and `save` (`write_cells` with the changes and the Przeniesienia zleceń of the click) as one step: without changes and Przeniesienia `write_cells` returns `CellsWritten(0)` and replaces nothing; `Refusal` or `Rejected` is a Zatrzymanie with INTERMAX untouched and neither memory nor result written |
| `ZapiszPamiec` | :382 `parts.state.save_memory` → `FileReportState.save_memory` → `_TextFile.write` → `StateFile.write`; an `OSError` keeps the text waiting and the process gives only the warning `memory_not_saved` |
| `ZapiszWynik` | :383 `parts.state.save_result` (the `ClickResult` with `ManualDifference` among its problems) → `_TextFile.write`, then :385 `onedrive_conflicts.beside`: a copy is the Zatrzymanie `conflict_after_save`, otherwise the summary; one step, because nothing between them writes a file or INTERMAX |
| `Odswiez` | a tab reads the Raporty view: `ReportEnteringEntry.view` → `FileReportState.shown` and `kept`, each `_TextFile.text` retries a waiting write |
| `ZostawSprawdz` | „Zostaw moją” on tab k: `ReportEnteringEntry.keep` checks `files.shown()` outside any lock (`report_entering_run.py` :125-129), else `difference_gone` |
| `ZostawCzytaj` | `FileReportState.keep` under `_deciding`: `self.kept()` |
| `ZostawZapisz` | still under `_deciding`: `decisions.write` of the old decisions with the new one; `keep` ignores its result, so Dad gets the view without the difference also when the decision only waits in memory |
| `Zgasniecie` | none: Centrum switches off at any step and Dad opens it again; the Uruchomienie, the requests and every waiting text are gone, files on disk and INTERMAX stay (`replace_atomically` is atomic) |

The script compares these definitions with their digests (`model/definicje.json`: file → name → digest): `reconcile` in
`worker_reports/_cells.py`; `Window.of`, `Window.opens`, `OwnEntries`, `Kept` in `worker_reports/_model.py`;
`enter_reports` in `worker_reports/__init__.py`; `enter_from_mail`, `_closed`, `SavedState` in `report_entering.py`;
`write_cells` in `intermax_cells.py`; `_TextFile`, `FileReportState.of_work`, `load`, `save_memory`, `save_result`,
`shown`, `kept`, `keep` in `centrum/report_entering_state.py`; `ReportEnteringEntry.keep`, `ReportEnteringEntry.view`,
`_view` in `centrum/report_entering_run.py`; `StateFile` in `centrum/atomic_file.py`; the assignment
`create_app.report_files` in `centrum/app.py` (one `FileReportState` for the process and the view, so the waiting text
is shared); `RunHost.start` in `centrum/runs.py`. Every code name in the table is one of them, except
`onedrive_conflicts.beside` (the model needs only where `enter_from_mail` calls it) and `register_file.read` and the
bytes of the write (`verify-zapis-intermax`). Look in the diff also for a new writer of one of the three files, a new
caller of `reconcile` or `keep`, and a step between `write_cells` and `save_memory`; add such code to the table and to
`model/definicje.json`.

The digests in `model/definicje.json` were taken when every row of the table was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests.

## Run

```sh
.venv/bin/python .agents/skills/verify-wpisanie-raportow/scripts/sprawdz_wpisanie_raportow.py
py -3 .agents\skills\verify-wpisanie-raportow\scripts\sprawdz_wpisanie_raportow.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. The run of TLC, the verdict and the
known findings are `tools/lib/model_tlc.py`; Java and `tla2tools.jar` come from `tools/lib/narzedzia_tlc.py`. The whole
check took 54 s on Maks's Mac on 2026-11-12 (six configurations, 15 known findings in 21 TLC runs, about 9.6 million
states in the six full runs) under a load average of 19 from other runs.

The last line is the verdict: `WPISANIE RAPORTÓW OK` or `WPISANIE RAPORTÓW OK, ZNANE ZNALEZISKA: n` (exit 0, 1 with
`--strict`), `WPISANIE RAPORTÓW: NOWE NARUSZENIE (n)` or `ZNALEZISKO ZNIKNĘŁO (n)` (exit 1), `BŁĄD MODELU (n)` (exit
2: no TLC verdict, `TypeOK` broken, another shape of `model/konfiguracje.json`, or an action of `Next` the story in the
script does not know). A line `UWAGA: kod opisany modelem zmienił się: …` above it means the verdict says nothing until
you bring the model in line. Each counterexample is told as numbered steps in the code's words and ends with the cell,
who typed it, the files and their waiting texts.

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/WpisanieRaportow.tla` and one configuration with
the `Wybaczone…` constants empty. It shows each broken promise as its shortest path in plain words, and for `kopia`
or `okres` it draws how one cell moves between „pusta”, „wpisana przez narzędzie”, „ręczna równa”, „ręczna różna” and
„zostawiona”.

Then tell a real bug from a modeling error: replay the path on the code, one step per action, in the style of
`tests/test_centrum_wpisanie_raportow.py` (`entering_centrum`, `_tata_writes`, `report`, `/api/report-entering/keep`).
A switch-off is a new app on the same tool folder (`centrum_app` with the same `ToolDirectory`, register, inbox and
`intermax_disk`), so `create_app` builds a new `FileReportState` without the waiting texts. A switch-off between
`write_cells` and `save_memory` is the disk state after it: INTERMAX after the click, the memory and result files from
before it. A failed write of a file in `config/` is a folder in its place during the mailbox read
(`fake_inbox.during`, as in `test_pamiec_wpisow_niezapisana_czeka_w_centrum_na_nastepne_klikniecie`); for the
decisions file, whose read must keep working, `replace_atomically` of `atomic_file` raising `PermissionError` for that
path only. A closed period is the Plik zbiorczy in the period folder (`Rozliczenie <okres> - zbiorcze.xlsx`). Remember
that the window starts at the rollout day from the memory file: a replay whose first click lost its memory reads
nothing of earlier days, so start it with one successful click. A path that does not happen on the code means the
model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | one tab, one switch-off, one refused INTERMAX write | known `przywrocona-wartosc`, `przywrocona-ze-starej-pamieci`, `przed-pamiecia` |
| `pamiec` | one tab, one switch-off, one failed write of the memory file, which may fail again while its text waits | the three of `zwykle` and `pamiec-odlozona` |
| `decyzje` | one tab, one switch-off, one failed write of the decisions file, which may fail again while its text waits | the three of `zwykle` and `decyzja-odlozona` |
| `dwie-karty` | two tabs with „Zostaw moją” at once, no switch-off, no failure | known `przywrocona-wartosc` |
| `okres` | the period closes with a Plik zbiorczy and opens again | known `przywrocona-wartosc`, `okres-otwarty-ponownie` |
| `kopia` | a conflict copy appears and goes at any moment | known `przywrocona-wartosc` |

Every configuration lets Dad change the cell, the worker send another Wpis and Dad click as often as they like; the
values are an empty cell and two contents of a Wpis (`A`, `B`), which Dad can type too. A failed write of the result
file (`MaxAwariiWyniku`) is in the model but in no configuration: no promise depends on it (the view then shows the
previous click, which was true when it was made), and the configuration `wynik` with it passed with the known
findings of `zwykle` on 2026-11-12 before it was dropped to keep the check under a minute.

## Known findings

A configuration forgives only the findings `model/konfiguracje.json` lists for it (`znane`), each only for its promise
and only for an event that happened with its cause. The causes come from history variables, not from the code:
`ostatniWlasny` (the value the tool last wrote), `zapomniala` and `zapomnialaCzeka` (a click whose memory survived saw
the cell without that value), `utrataPamieci` (a switch-off left on disk a memory other than the one this Centrum work
held for right, `PamiecWlasciwa`: the text the click computed after its INTERMAX write, else the waiting text; cleared
when the tool writes the cell again), `bezPamieci` (why the memory lacks the tool's value that still stands in the
cell), `upuszczona` (the memory dropped it in a closed period) and `zostawione` (what „Zostaw moją” confirmed to Dad).
Each finding was replayed on the code (Read a result), with a scratch test that is not in `tests/`.

1. **`przywrocona-wartosc`, NieNadpisuje (open, breaks ADR 0028 and 0029, decide with Maks).** The tool wrote `tak`;
   Dad (or his worker) clears the cell and types `tak` again, or changes it and changes it back, before any click; a
   corrected Raport says `nie`; the next click finds `cell == remembered` in `reconcile` and writes `nie` over Dad's
   `tak`. The memory compares values, not who typed them, so it cannot tell. Replayed: after the second click INTERMAX
   has `nie` and the click has no problem. Harm is small (Dad's value equals the old report), but it breaks the promise: ADR 0028 writes only „do
   własnego wcześniejszego wpisu, którego nikt potem nie zmienił”, and Dad did change it; ADR 0029 („a od tamtej pory
   nikt tego nie ruszył. Gdy tata przeniesie zlecenie z powrotem, Centrum go nie przenosi drugi raz”) decides the same
   „back again” case against overwriting. Forgiven only so the check stays green without a product change; no ADR or
   decision of Maks accepts it.
2. **`przywrocona-ze-starej-pamieci`, NieNadpisuje (open).** The memory file is older than INTERMAX: Centrum switched off
   between `write_cells` (:369) and `save_memory` (:382), or `save_memory` failed and Centrum switched off before a retry,
   and the memory the click computed differs from the one on disk (a switch-off that loses nothing is not this cause).
   The tool wrote `tak`, then `nie` over its own `tak` in the click whose memory was lost; Dad types `tak`; the next click
   with the mail still `nie` finds `tak` in the old memory and writes `nie` over Dad's value. With the right memory
   (`nie`) it would have shown a difference. Replayed: memory and result files restored to the first click after the
   second, a new app, Dad's `tak`, third click: INTERMAX `nie`, no problem.
3. **`przed-pamiecia`, BezFalszywejRoznicy (open, direction safe).** Centrum switches off after `write_cells` replaced
   INTERMAX and before `save_memory`: the memory has no own entries of that click, and when the worker sends a correction
   the Raporty view shows the tool's own `tak` and activities as manual values that „zostają”. Replayed: after a first
   click without reports (rollout 9.11) the click writes `tak`, `wymiana routera`; memory and result restored, a new
   app, a correction `nie klient nieobecny`: two `manual_difference` problems with `manual` `tak` and `wymiana routera`,
   INTERMAX unchanged.
4. **`pamiec-odlozona`, BezFalszywejRoznicy (open, direction safe; the review candidate).** `save_memory` fails
   (`OSError`), the process gives only the warning, whose action says „narzędzie zapisze ją przy następnym kliknięciu”,
   and Centrum switches off before the retry: the waiting memory is gone and the next correction shows the own entries
   as manual differences. The warning's promise does not hold across a restart. Replayed with a folder in place of
   `wpisanie-raportow-stan.json` during the mailbox read, then the old file back and a new app: the same two problems.
5. **`decyzja-odlozona`, ZostawUcisza (open).** The write of the decisions file in `FileReportState.keep` fails;
   `keep` ignores the result of `decisions.write` and returns the view without the difference, and Centrum switches off
   before any view or click retries it: the decision is gone and the difference is back. Replayed with
   `replace_atomically` raising `PermissionError` for the decisions file: `keep` returns 200, the view has no problem,
   the file does not exist; after a new app the view shows the same difference with its „Zostaw moją” button.
6. **`okres-otwarty-ponownie`, BezFalszywejRoznicy (open, direction safe).** A Plik zbiorczy closes the period, so the
   next click does not read its orders and `reconcile` drops their own entries from the memory (`own` keeps an entry
   only if its value is in `current`); when Dad removes the Plik zbiorczy, the own entries of that period come back as
   manual differences at the next correction. Replayed: the memory after the click in the closed period has `own: []`,
   and after the Plik zbiorczy is removed the correction gives the two problems.

Not a violation of these promises, noted from the code: `Kept` is never pruned (`keep` only adds), so the decisions file
grows with every „Zostaw moją” for good; a lost first memory also loses the rollout day, so a later click reads no
days before it (the cells of those days are neither written nor shown).

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   TLA+ strings must be ASCII; comments may use Polish letters. Never weaken a promise or narrow a configuration to make
   the check pass.
3. A new way to fail gets a constant, a branch guarded by it, and a value in `stale` of every configuration in
   `model/konfiguracje.json`. A new action of `Next` gets its words in `_STEPS` of the script.
4. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_wpisania_mutations.py` with the code counterpart in its name.
5. Run the check. A new violation is a finding: replay it on the code (Read a result) before you call it a bug, report
   it with the path, and do not change product code unless asked.
6. Run `tools/przesun_model.py verify-wpisanie-raportow` only after every row of the table describes the code, and
   write in the commit message, in one sentence, what changed in the model and why.

## After changing the model

`.venv/bin/python .agents/skills/verify-wpisanie-raportow/scripts/check_model_wpisania_mutations.py` applies each
broken variant of the model to a copy of the checkout (`tools/lib/silnik_mutacji.py`) and must end with `MUTACJE OK`;
run it only to reproduce a red Mutation checks step or while you change the model. Each mutation but the last removes a
guard the code has, and each gives `WPISANIE RAPORTÓW: NOWE NARUSZENIE`:

- NieNadpisuje: `reconcile` without `cell is None or cell == remembered` (`zwykle`); `own` without `if value in
  current[cell]`, so the memory keeps an own entry Dad changed (`zwykle`).
- BezFalszywejRoznicy: `reconcile` without `own[order.key, column] = value` (`okres`); `_TextFile.text` without the
  waiting text, so the next click of the same Centrum work reads the old memory (`pamiec`).
- ZostawUcisza: `FileReportState.keep` without `_deciding` (`dwie-karty`: two tabs read the old decisions and one
  decision is lost); `keep` without `self.kept() |` (`dwie-karty`); `kept()` in `keep` without the waiting text
  (`decyzje`); `_view` without `if problem.difference not in kept` (`dwie-karty`).
- KopiaZatrzymuje: `check` without `onedrive_conflicts.beside`; the end of `enter_from_mail` without it (`kopia`).

The last one removes the cause of three known findings instead: a switch-off that leaves on disk the memory this work
held for right (as if `save_memory` were part of the INTERMAX write and nothing waited in memory) must give
`WPISANIE RAPORTÓW: ZNALEZISKO ZNIKNĘŁO (3)` in `pamiec`, so `przywrocona-ze-starej-pamieci`, `przed-pamiecia` and
`pamiec-odlozona` all go. A history variable that marks a cause the event did not have would leave one of them standing.

A mutation reported as `NIEAKTUALNA` no longer matches the model: rewrite its anchor against the new model so that it
breaks the same rule again.

## Scope

Verified: the four promises over every order of the actions above within the bounds of each configuration (one cell,
two contents of a Wpis, one or two tabs, at most one switch-off and one failure of each kind), with Dad, his worker and
the mail changing the cell and the Wpis as often as they like. Assumed, each a reason the check can pass while the code
is wrong:

- **The read, the plan and the INTERMAX write are one step.** A change Dad or his worker saves between `register_file.read`
  and the replace is lost with the whole file; that is known finding 1 of `verify-zapis-intermax`, not repeated here.
- **The cell value the tool reads back is the text it wrote** (`DOKLADNIE_WPISANE` of `verify-zapis-intermax`), and
  `normalize_text` equality is plain equality of the two abstract values.
- **`replace_atomically` is atomic**: a switch-off leaves the old file or the new one.
- **One `FileReportState` per Centrum work** (`create_app.report_files`), shared by the process and the API, and one
  Uruchomienie at a time (`RunHost.start`).
- **A file that failed its write may keep failing every retry and every write while its text waits**
  (`StateFile._save` then writes without pauses), with no limit after the one first failure its configuration allows;
  a read of the file itself never fails (a file that cannot be read is `StateUnreadable` or `DecisionsUnreadable`, a
  Zatrzymanie or a refusal that changes nothing).

Left out: Przeniesienia zleceń (ADR 0029, #1347, #1350): a Wpis of another Wykonawca or with another day moves the
order to them or to the day of the subject, and the cell's own entries go with the row to the `OrderKey` it has after
the click, after a Przeniesienie and after Dad's change of `WYKONAWCA` or of the day alike, only while the number has
one order in the days the process reads, after today too (`_moves._carried`), so for the one cell the model has it is
the newest Wpis of `NowyMail`, whoever sent it and whichever day its subject has; a mistaken subject (two or more
Wpisy with another day) only decides which order the Wpis reaches, and a Raport wykonawcy whose day lies in a period
with a Plik zbiorczy reaches an order of an open day only that way, so both are `NowyMail` too. Dad's change of
`WYKONAWCA` or of the day (the memory of the number `OwnMove`, found by `_model.memories_of`, and the rule
`_model.may_move`, whose transition table `tests/test_rdzen_raportow.py` checks as a property) only leaves an older
Wpis in force, which `NowyMail` also covers. A number the read days hold in several orders (a closed day or one after
today too) moves none of them and reaches only the sender's one order in the day of the subject (`_matching.Board`),
otherwise a problem, which also only leaves an older Wpis in force. Its cells keep no own entries in the memory
(`_cells.reconcile`, #1367 r4: Excel does not tell which row of the number is which after Dad deletes, merges or swaps
them), so after the click that wrote it the tool's own entry counts as Dad's value, as after `TataZmienia`: a later
Wpis with another content gives a `ManualDifference` at the tool's own entry, which BezFalszywejRoznicy forbids for
the model's one cell. The model leaves that cell out by design (direction safe: NieNadpisuje holds; decision for Maks
in #1367). The rollout day (it only moves the start of the window later, which leaves cells out), the reading of the
mailbox and its problems other than `ManualDifference`, `Rejected` and `UnsupportedShape` (the same Zatrzymanie as a
`Refusal`), a Kopia INTERMAX restored by Dad, the text of the view and of the Komunikaty, and the result file's failed
write (Configurations).

## Files

- `model/WpisanieRaportow.tla`: the model, with the code each action describes.
- `model/konfiguracje.json`: the configurations (description, constants and known findings; the script writes each
  `.cfg` with `TypeOK` and every promise), `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_wpisanie_raportow.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_wpisania_mutations.py`: proves the check fails when the model loses a guard the code has.
