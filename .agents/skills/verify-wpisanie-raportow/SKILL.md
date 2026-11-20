---
name: verify-wpisanie-raportow
description: Model-check with TLA+ (TLC) one report cell of Wpisanie raportów z maili (ADR 0028, spec #1224) across Dad's click „Wpisz raporty z maili”, the cell rules, the three files in `config/` (memory of own entries, the result for the Raporty view and the „Zostaw moją” decisions, whose failed write waits in memory), „Zostaw moją” from another tab, Dad or his worker changing the cell in Excel, a new mail, a Plik zbiorczy that closes and reopens the period, an OneDrive conflict copy, a refused INTERMAX write and Centrum switching off at any step. It checks that the tool never overwrites a value Dad typed, that „Zostaw moją” keeps the difference out of the view, that the tool's own entry never shows as a manual difference, and that a conflict copy stops the click. Use when `tools/skille_dla_zmiany.py` names it, when a change adds a writer of one of the three files, a caller of `reconcile` or `keep`, or a step between `write_cells` and `save_memory`, or when `sprawdz_wpisanie_raportow.py` fails.
pilnuje:
  - src/rozliczenia/worker_reports/_cells.py
  - src/rozliczenia/worker_reports/_model.py
  - src/rozliczenia/worker_reports/__init__.py
  - src/rozliczenia/worker_reports/_memory.py
  - src/rozliczenia/worker_reports/_operation.py
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
CI and `tools/szybko.py` catch drift: covered code that differs from its digests in `model/definicje.json`
(`ROZJAZD MODELU Z KODEM | <skill>: …`); they cannot tell whether your change to the model is right.
`check_model_wpisania_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_wpisanie_raportow.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line”.
A change whose model nobody brought in line is not verified, whatever CI says.

## The promises

Dad clicks „Wpisz raporty z maili” when his worker is not in INTERMAX. Each click reads every Raport wykonawcy from the
open days again and writes `tak`/`nie` and the activities into `SKUTECZNE` and `CZYNNOŚCI ZREALIZOWANE`. ADR 0028:
„Pamięta tylko to, co samo wpisało, bo bez tego nie odróżni własnego wpisu od ręcznego” and „pisze tylko do pustej
komórki albo do własnego wcześniejszego wpisu, którego nikt potem nie zmienił”. Three files in `config/` carry the
state between clicks (the docstring of `centrum/report_entering_state.py` names them), each with one writer, each written atomically, and a write that fails waits in the memory of
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
| `KlikWolny` | none: no click runs (the Uruchomienie ended or has not read the files yet) |
| `NowyMail` | a Raport wykonawcy with another content of the Wpis for this order arrives; the latest mail wins (`enter_reports`) |
| `ZamkniecieOkresu`, `OtwarcieOkresu` | the Plik zbiorczy of the period appears (Przygotowanie) or Dad removes it; `report_entering.closed_periods` gives `Window.of` the closed tokens through `EnteringMemory.window` and `Window.opens` leaves the order out of `orders` in `enter_reports` |
| `PojawiaSieKopia`, `TataUsuwaKopie` | OneDrive puts a conflict copy beside INTERMAX (a change of the worker and a replace by the tool at once); Dad merges it into INTERMAX and removes it, and what he copies over are his changes of the cell (`TataZmienia`) |
| `Sprawdzanie` | Dad clicks „Wpisz raporty z maili”, or „Wpisz do INTERMAX” (Wpis na życzenie) at a Wpis of the last result, at a problem or at an order with a Wpis of a report with a faulty subject (`ReportEnteringEntry.on_request` looks for the offer with the identity of the clicked cell, `Offer.token`, in `ShownResult.offers` of `files.shown()` outside any lock, else `request_gone`, and `prepare` puts the offer's decision, `Offer.decide`, into `ReportEnteringParts.requested`; for the one cell it is one more content of the newest Wpis, like `NowyMail`); `RunHost.start` (one Uruchomienie at a time), `enter_from_mail` `check`: `EnteringMemory` of `parts.state`, the one load of the click, `FileReportState.load`, which reads the memory through `_TextFile.text` (`StateFile.retry` first, then the waiting text or the file) and `kept()` the same way, then `onedrive_conflicts.beside` (:276), whose copy is a Zatrzymanie before the mailbox |
| `Zapis` | `read` (mailbox, `register_file.read`), `plan` (`EnteringMemory.enter` → `enter_reports` → `_cells.reconcile` on the snapshot of the memory and `kept` from `check`, then `_cells.with_added`; a memory file older than version 4 goes through `OlderOwnEntries.upgraded` first, Left out) and `save` (`write_cells` with the changes, the Przeniesienia zleceń and the Zlecenia dopisane z raportu of the click) as one step: without any of them `write_cells` returns `CellsWritten(0)` and replaces nothing; `Refusal` or `Rejected` is a Zatrzymanie with INTERMAX untouched and neither memory nor result written. The window between the read of INTERMAX and its replace is known finding 1 of `verify-zapis-intermax`; the snapshot of the click is needed only in the plan, so it is gone after this step |
| `ZapiszPamiec` | `parts.state.save_memory` (the memory with Dad's decisions of Wpis na życzenie, `EnteringMemory.requested`) → `FileReportState.save_memory` → `_TextFile.write` → `StateFile.write`; also with no cell written; an `OSError` keeps the text waiting and the process gives only the warning `memory_not_saved` and goes on |
| `ZapiszWynik` | :383 `parts.state.save_result` (the `ClickResult` with `ManualDifference` among its problems) → `_TextFile.write` (an `OSError` keeps the text waiting, and the view shows it from memory), then :385 `onedrive_conflicts.beside`: a copy is the Zatrzymanie `conflict_after_save` with the summary, otherwise the summary, and the Uruchomienie ends; one step, because nothing between them writes a file or INTERMAX, so a switch-off there loses only what a switch-off after the end loses, and a copy that appears there appears before it |
| `Odswiez` | a tab reads the Raporty view: `ReportEnteringEntry.view` → `FileReportState.shown` and `kept`, each `_TextFile.text` retries a waiting write; the Lista Wykonawców it reads from the Ustawienia snapshot only gives an unknown sender the login it was assigned to (#1475), and a list the system cannot read now counts as empty, so the sender stays unknown; no cell of the model depends on it |
| `ZostawSprawdz` | „Zostaw moją” on tab k: `ReportEnteringEntry.keep` checks `files.shown()` outside any lock (`report_entering_run.py` :125-129): the difference with this content is in the result of the last click, else `difference_gone` |
| `ZostawCzytaj` | `FileReportState.keep` under `_deciding` (`report_entering_state.py` :440-441): `self.kept()`, the old decisions |
| `ZostawZapisz` | still under `_deciding` (:442-444): `decisions.write` of the old decisions with the new one; `keep` ignores its result, so Dad gets the view without the difference also when the decision only waits in memory |
| `Zgasniecie` | none: Centrum switches off at any step and Dad opens it again; the Uruchomienie, the requests of „Zostaw moją” and every waiting text (`StateFile._waiting`, `_TextFile._written`) are gone; the files on disk, not the memory this work computed or kept waiting, and INTERMAX stay (`replace_atomically` is atomic) |

Definitions the actions share:

| Model definition | Code |
| --- | --- |
| `Wpisy`, `Reczne`, `Pamieci` | the content of the Wpis raportu for the cell from the newest mail of the Wykonawca; the values Dad or his worker types in Excel, each equal to some Wpis; the memory of the cell: no entry, or the value the tool itself wrote |
| `PamiecEfektywna` | `_TextFile.text`: the waiting text wins while the file is unavailable, otherwise the text on disk |
| `PamiecWlasciwa` | the memory this Centrum work takes as right: the one the click computed after the INTERMAX write and before `save_memory`, otherwise the waiting text or the file |
| `MozeZawiesc(z, czeka, awarie, max)` | `StateFile._save`: a write of a file whose text already waits goes without pauses and may fail again (`OSError`) without taking a new failure from the pool, like a failed retry |
| `BezZmian`, `Zmiana`, `Roznica`, `NowaPamiec` | the rules of one cell, `worker_reports/_cells.py` `reconcile`, on the click's snapshot (`migPamiec`, `migDecyzje`) and INTERMAX as read. An order of a day of a closed period is not in `orders` (`enter_reports`: `window.opens`), so it gets no Wpis and no difference, and the memory drops it (`own`: the value must be in `current[cell]`); `if value is None or (cell is not None and normalize_text(cell) == normalize_text(value)): continue`; `if cell is None or cell == remembered.get((order.key, column))`: a Wpis into an empty cell or the tool's own entry; `elif Kept(order.key, column, value) not in kept`: `ManualDifference`; `own = {cell: value for cell, value in remembered.items() if value in current[cell]}`, then `own[...] = value` |
| `PrzyczynaNadpisania` | the causes of an overwritten manual value, from the history, not the code: Dad restored the value the tool last wrote and no click whose memory survived saw the cell without it (the memory compares values, not authors), or he typed it after a switch-off that lost a newer memory (every value of the cell is a content of a Wpis, so each is or may be an old value of the tool) |
| `Widoczna` | ZostawUcisza: the Raporty view (`_view`: problems without a decision from `kept`) shows the difference although Dad got the view without it |

Each constant is a way to fail or a bound of a configuration (`stale` in `model/konfiguracje.json`):

| Constant | Meaning |
| --- | --- |
| `Karty` | tabs of the Raporty view from which Dad clicks „Zostaw moją” at once (1 or 2) |
| `MaxZgasniec` | switch-offs of Centrum (a power cut, a killed process); a text waiting in memory is lost |
| `MaxAwariiIntermax` | `write_cells` gives `Refusal` or `Rejected` (Excel, OneDrive, a failed write), INTERMAX untouched |
| `MaxAwariiPamieci`, `MaxAwariiWyniku`, `MaxAwariiDecyzji` | `StateFile.write` of the memory, the result and the decisions: `OSError` of `replace_atomically` of the file in `config/`; a file whose write failed may fail at every retry (`StateFile.retry`) and write (`StateFile.write`) while its text waits, without more failures from this pool |
| `MozeOtworzyc` | Dad removes the Plik zbiorczy of a period that was already closed, so the period is open again |
| `MozeKopia` | OneDrive puts a conflict copy beside INTERMAX (`onedrive_conflicts.beside`) |
| `Wybaczone…` | the causes of known findings that the `…PozaZnanymi` variant of each promise skips; the script sets them |

| Variable | Meaning |
| --- | --- |
| `komorka`, `autor`, `wpis`, `okresOtwarty`, `kopia` | Dad's world: the value of the cell in INTERMAX; a ghost of who typed it (nobody: empty, the tool, Dad or his worker); the content of the newest Wpis for the cell from the Skrzynka raportów (none without a Wpis); the period of the order's day has no Plik zbiorczy (`Window.opens`); a conflict copy of OneDrive lies beside INTERMAX |
| `pamiec`, `pamiecCzeka`, `pamiecOdlozona`; `wynik`, `wynikCzeka`, `wynikOdlozony`; `decyzje`, `decyzjeCzeka`, `decyzjeOdlozone` | each file in `config/`: its text on disk, whether a text waits in the memory of this Centrum work (`StateFile.unavailable`) and which; the result holds the difference with a manual value (none or a content of a Wpis), the decisions the contents at which Dad clicked „Zostaw moją” |
| `faza`, `migPamiec`, `migDecyzje`, `kopiaPrzySprawdzaniu`, `plan…` | the click of „Wpisz raporty z maili” (one at a time: `RunHost.start`): its phase, its snapshot of the memory and the decisions, a copy seen at `check`, and its plan |
| `etap`, `tresc`, `odczyt`, `blokada` | „Zostaw moją” from the tabs: the stage of the request, the content of the difference, the decisions read under the lock, the lock `_deciding` |
| `ostatniWlasny`, `zapomniala`, `zapomnialaCzeka`, `utrataPamieci`, `bezPamieci`, `upuszczona`, `zostawione` | ghosts, the history from which the promises take the causes of known findings: the value the tool last wrote into the cell; the memory on disk no longer has it because a click saw the cell without it; the same only in the waiting text; a switch-off left a memory other than `PamiecWlasciwa` on disk and the tool has not written since; why the memory lacks a value the tool wrote that still stands in the cell; the memory dropped an own entry that stands in the cell because the period was closed; the contents at which „Zostaw moją” returned the view without the difference to Dad |
| `zgasniecia`, `awarieIntermax`, `awariePamieci`, `awarieWyniku`, `awarieDecyzji` | the counters of the `Max…` constants |
| `nadpisane`, `falszywe`, `bezDecyzji`, `przeoczonaKopia` | the history variable of each promise: the set of causes at the moment of each event that breaks it |

The script compares the definitions in `model/definicje.json` with their digests; among them is the assignment
`create_app.report_files` in `centrum/app.py` (one `FileReportState` for the process and the view, so the waiting text
is shared). Every code name in the table is one of them, except
`onedrive_conflicts.beside` (the model needs only where `enter_from_mail` calls it), `OlderOwnEntries.upgraded` (Left
out) and `register_file.read` and the bytes of the write (`verify-zapis-intermax`). Look in the diff also for a new writer of one of the three files, a new
caller of `reconcile` or `keep`, and a step between `write_cells` and `save_memory`; add such code to the table and to
`model/definicje.json`.

The digests in `model/definicje.json` were taken when every row of the table was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests.

## Run

```sh
.venv/bin/python .agents/skills/verify-wpisanie-raportow/scripts/sprawdz_wpisanie_raportow.py
py -3 .agents\skills\verify-wpisanie-raportow\scripts\sprawdz_wpisanie_raportow.py
```

The run of TLC, the verdict and the known findings are `tools/lib/model_tlc.py`; Java and `tla2tools.jar` come from `tools/lib/narzedzia_tlc.py`. The whole
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
2. Change the model so each action is again one indivisible step of the code, and write the code's names in its row of
   the table above, not in a comment: the model has none, and a new action, definition, constant or variable gets its
   own row. TLA+ strings must be ASCII. Never weaken a promise or narrow a configuration to make the check pass.
3. A new way to fail gets a constant with its row, a branch guarded by it, and a value in `stale` of every configuration
   in `model/konfiguracje.json`. A new action of `Next` gets its words in `_STEPS` of the script.
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
Wpisy with another day; an order of a number the tool added counts for none, `_matching.Board._added`, #1374 r4, but
the day of that order still picks the route, so a Wpis never moves it from a day that is not open, #1374 r5)
only decides which order the Wpis reaches, and a Raport wykonawcy whose day lies in a period
with a Plik zbiorczy reaches an order of an open day only that way, so both are `NowyMail` too. Dad's change of
`WYKONAWCA` or of the day (the memory of the number `OwnMove`, found by `_model.memories_of`, and the rule
`_model.may_move`, whose transition table `tests/test_rdzen_raportow.py` checks as a property) only leaves an older
Wpis in force, which `NowyMail` also covers. A number the process reads in several rows (several orders, a closed day
or one after today too, or an order and a row the core makes no order from, `RegisterWindow.present`, #1374 r4) moves
none of them and reaches only the sender's one order in the day of the subject (`_matching.Board`), otherwise a
problem, which also only leaves an older Wpis in force. A number in several orders keeps no own entries in the memory
(`_cells.reconcile`, #1367 r4: Excel does not tell which row of the number is which after Dad deletes, merges or swaps
them), so after the click that wrote it the tool's own entry counts as Dad's value, as after `TataZmienia`: a later
Wpis with another content gives a `ManualDifference` at the tool's own entry, which BezFalszywejRoznicy forbids for
the model's one cell. The model leaves that cell out by design (direction safe: NieNadpisuje holds; decision for Maks
in #1367). A memory file older than version 4 (Wydania v0.7.0 and v0.8.0, `main` before #1367) loads as
`OlderOwnEntries`, whose writer kept entries at a number of several orders too, so the process keeps such an entry
only at the number's one order with the same day and Wykonawca as when it was saved and otherwise drops it, which
makes its cell Dad's value as above (`OlderOwnEntries.upgraded`, #1367 r5); the model starts from a memory this code
wrote. A Zlecenie dopisane z raportu (#1354) is, for the one cell, the empty cell that `Zapis` fills with the Wpis and
remembers as the tool's own entry (`_cells.with_added`); only a number no row the process reads holds becomes one
(`RegisterWindow.present`, also a Surowe zlecenie, a row the core makes no order from: without `WYKONAWCA`, with the
date as text, pasted from the app between ordered rows, and a row from the week before the first open day, before the
rollout day too: `Window.numbers_since`), so it never doubles a number of any row the process read. Dad
deleting the added row leaves no value of his that a write could overwrite, and the click after it adds the row again
only for a fresher mail (`_model.may_move` with the memory of the number), which the model's write into an empty cell
over-approximates. The rollout day (it only moves the start of the window later, which leaves cells out), the reading
of the mailbox and its problems other than `ManualDifference`, `Rejected` and `UnsupportedShape` (the same Zatrzymanie as a
`Refusal`), a Kopia INTERMAX restored by Dad, the text of the view and of the Komunikaty, and the result file's failed
write (Configurations).
