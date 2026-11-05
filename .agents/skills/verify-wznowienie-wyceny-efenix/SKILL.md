---
name: verify-wznowienie-wyceny-efenix
description: Model-check with TLA+ (TLC) that Wycena w efenix, across the Uruchomienia of one period, never loads Wycena Emmetta over an order that has quantities, never writes into an order with a pricing that Dad changed by hand (also never adds back a quantity he removed), puts a Znacznik efenix only beside an order priced as in the file, and gives Dad „wycena już jest i się różni” only for an order he changed, under every order of window Zatrzymania, Centrum switching off, failed writes of the Ślad Wyceny Emmetta (also the write ahead of each quantity) and Dad's own changes in efenix between Uruchomienia. Use when a change touches `save`, `_priced`, `_outcome`, `_after_emmett`, `_entered`, `_WrittenAhead`, `_TraceNotSaved`, `_mark` or `_efenix_stops` in `src/rozliczenia/efenix_pricing.py`, `EmmettTrace` in `src/rozliczenia/efenix_emmett_trace.py`, `as_left_after_emmett`, `to_enter`, `priced_differently` in `src/rozliczenia/efenix_positions.py`, or `load_emmett`, `enter_quantity` in `src/rozliczenia/efenix_browser.py`, or when a resumed Wycena w efenix changed an order it should only have compared.
pilnuje:
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/efenix_emmett_trace.py
  - src/rozliczenia/efenix_positions.py
  - src/rozliczenia/efenix_browser.py
  - .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
  - tools/lib/rozjazd_modelu.py
ci: .agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py
---

# Verify wznowienie Wyceny w efenix (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_wznowienie_wyceny.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step. It fails with `WZNOWIENIE WYCENY: ROZJAZD MODELU Z KODEM` when a definition the model describes
(`model/definicje.json`) changed since the model's Sync commit, but it cannot tell whether your change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_model_wznowienia_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_wznowienie_wyceny.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line, then run”: read the diff against
the table, change the model, break the new path in it, and run the check while you do. A change whose model nobody
brought in line is not verified, whatever CI says.

## The promises

Wycena w efenix writes on a server Dad works on every day: a quantity is saved the moment the field loses focus, and
„Załaduj do zlecenia” (Wycena Emmetta) wipes every quantity of the order (ADR 0024). Between Uruchomienia only the Ślad
Wyceny Emmetta (`config/slad-wyceny-emmetta/<okres>.json`) tells the tool which pricing it started itself and which
quantities it may have entered. The model checks four promises over every order of steps:

- **NieCzysciWycenyTaty**: the tool loads Wycena Emmetta only into an order with no quantity, so it never wipes a
  pricing, Dad's or its own.
- **ZmianaTatyZostaje**: in an order with a pricing in which Dad changed, added or removed something by hand, the tool
  writes nothing; it does not add back a quantity he removed. That page is the error „wycena już jest i się różni” with
  no change (`_outcome` docstring, #757).
- **ZnacznikTylkoNaWycenionym**: a Znacznik efenix appears in `ADRES` only beside an order whose pricing in efenix equals
  the file at the moment of marking.
- **BladTylkoPoZmianieTaty**: Dad gets „wycena już jest i się różni” (`EFENIX_WYCENA_INNA`) only for an order he
  changed himself; an order the tool started is finished by the next Uruchomienie.

Harm: for the first, Dad's or the tool's work on an order disappears from efenix and the company sees an empty or
Emmett-only pricing. For the second, a quantity Dad deliberately removed goes back to the company with his name on
it, and the Uruchomienie says OK and marks the order. For the third, Dad trusts a Znacznik and skips an order that is
wrong in efenix. For the fourth, Dad has to finish by hand an order the tool left half-done.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/WznowienieWyceny.tla`, not the code. It describes the code only while
you keep the two in step. Each model action is one indivisible step of this code:

| Model action | Code |
| --- | --- |
| `Start` | `efenix_pricing.py` `price_orders.save`: `EmmettTrace(trace_file)` reads the trace file once (`_read`, `_read_secret`; a missing or unreadable file or key, or an entry without `entering`, is no trace), then the orders of the scope in order |
| `Otworz` | `_outcome`: `efenix.search`, `listing`, `open_order`, then the decision on the page: amount 0 goes to Wycena Emmetta; `priced_differently(...) is None` is `Ready`; `emmett is None or ... not as_left_after_emmett(emmett, trace.entered(number), ...)` (`efenix_positions.py`: the page has exactly Emmett's quantities and the quantities the trace has as `entering`, every other position empty) is `OrderError(differs)`; otherwise `_after_emmett` with `to_enter` of the page |
| `ZaladujEmmetta` | `_outcome`: `efenix.load_emmett()` up to the click of „Załaduj do zlecenia”, after which efenix holds Wycena Emmetta (`efenix_browser.BrowserEfenix.load_emmett`, `_answer(_LOAD_EMMETT, …)`); an answer that refuses it (redirect, 4xx/5xx, `result: nok`) raises before the page is read, so it is `Zatrzymanie` in place of this step when efenix did not load Wycena Emmetta, and `Zatrzymanie` right after it (known finding 1) when efenix loaded it and still answered 5xx (#877) |
| `OdczytPoEmmetcie` | `load_emmett` reads the reloaded page (`_read_order`), then `trace.loaded(number, emmett)` (`EmmettTrace.loaded`, `_save`: state „Emmett załadowany” with an empty `entering`); a failed write does not stop |
| `BrakPozycji` | `_outcome`: `missing_positions(..., PageRead.AFTER_EMMETT)` is `OrderError` after `load_emmett` and before `trace.loaded` |
| `Zapowiedz` | `_WrittenAhead.enter_quantity` (the window `_priced` builds under the paced window of `Pacing.window`, so after the human-pace pause before the quantity): `trace.entering(number, position, quantity)` (`EmmettTrace.entering`, `_save`) right before the window's `enter_quantity`; when it returns `False`, `_TraceNotSaved` (cause `trace.failure`) without the quantity, which `_efenix_stops` turns into `StopError(messages.emmett_trace_not_saved(...), facts=PricingStopped(...))`, and `save` (`except StopError`) calls `_mark` |
| `Wpisz` | `_WrittenAhead.enter_quantity` → the traced window's `enter_quantity(position, quantity)` up to the moment efenix saved the quantity (`BrowserEfenix.enter_quantity`, `_answer(_SAVE_QUANTITY, …)`) |
| `Odmowa` | `_WrittenAhead.enter_quantity`: `except LoggedOut: trace.not_entered(number, position)` and `raise`; `BrowserEfenix.enter_quantity` raises `LoggedOut` only for a save answer redirected to the login page or with `result: nok`, so efenix did not save the quantity |
| `Potwierdz` | `enter_quantity` after the save: the JSON answer and the amount on the page; after the last position `_entered` compares the amount with `Kwota` (`same_amount`) |
| `KoniecZlecenia` | `_priced`: `trace.finished(number)` after `_outcome` returned (`EmmettTrace.finished` writes „gotowe” only for an order in state „Emmett załadowany”), then `journal.ended` and the next order |
| `Zatrzymanie` | `LoggedOut`, `UnexpectedPage`, `WindowClosed`, `EfenixUnreachable` from any window action: the window's exception passes through `_priced` without `trace.finished`, `_efenix_stops` in `save` turns it into `StopError`, and `save` (`except StopError`) calls `_mark` with the results before it |
| `Znaczniki` | `save`: `_mark` (`mark_ready` for every `Ready` row), also after `StopError`, then the end of the Uruchomienie |
| `Zgasniecie` | none: Centrum switches off or is killed; memory is gone, the trace file and efenix stay, no Znaczniki |
| `Tata` | none: Dad changes a quantity in efenix by hand while no Uruchomienie runs (`AtrapaEfenix.edit` in the tests) |
| `Udany`, `Nieudany` (`Zapisz`) | `EmmettTrace._save` returns whether it wrote: `_replace` (temporary file and `os.replace`) of the whole trace from memory, which returns its `OSError` (kept in `failure`); when it fails, `self._path.unlink` in `suppress(OSError)`, and when that fails too, the previous file stays |

The script compares these definitions with the Sync commit (`model/definicje.json`):
`save`, `_mark`, `_efenix_stops`, `_priced`, `_outcome`, `_after_emmett`, `_entered`, `_TraceNotSaved`, `_WrittenAhead`
in `src/rozliczenia/efenix_pricing.py`; `EmmettTrace`, `_replace`, `_read_secret`, `_read`, `_is_entry` in
`src/rozliczenia/efenix_emmett_trace.py`; `as_left_after_emmett`, `to_enter`, `priced_differently`, `same_amount`,
`emmett_conflicts` in `src/rozliczenia/efenix_positions.py`; `load_emmett`, `enter_quantity` in
`src/rozliczenia/efenix_browser.py`. A change elsewhere in these files (Sprawdzanie, Odczyt danych, Logi, the window's
classification of other failures) does not move the model. A change that makes another function write in efenix,
write the trace file or decide whether an order is finished does, though no definition above changes: add it to the
table and to `model/definicje.json`.

Sync commit: `c490d2497` (2026-11-05, the fix of #881 on top of #877). Every row of the table was checked against the
code at this commit. The model did not change, only the code names in its comments: the write ahead and its withdrawal
moved from `_entered` to the window `_WrittenAhead`, which the paced window wraps, so the write ahead comes after the
human-pace pause instead of before it, and a failed write ahead stops through `_efenix_stops` with `PricingStopped`; the
model has no time, so `Zapowiedz` and `Wpisz` stay two steps with a stop between (known finding 3). On the previous
Sync commit `ba0b16db8` (#877) only `load_emmett` changed: a refused „Załaduj do zlecenia” stops before the page is
read instead of reading the reloaded page as an empty Wycena Emmetta, which is the `Zatrzymanie` the model already has
in place of `ZaladujEmmetta`, or right after it when efenix loaded Wycena Emmetta anyway. On `dde575566` (the fix of
#864 and #865) the model gained the write ahead of each quantity (`Zapowiedz`), its withdrawal after `LoggedOut`
(`Odmowa`), the strict `JakPoEmmetcie` and a third position, and each path below was replayed on that code with the
Atrapa efenix.

## Run

```sh
.venv/bin/python .agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py
py -3 .agents\skills\verify-wznowienie-wyceny-efenix\scripts\sprawdz_wznowienie_wyceny.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. Java and `tla2tools.jar` come from
`verify-aktualizacja-narzedzia` (`sprawdz_aktualizacje.py` installs pinned `jdk4py` and the jar into `.verification/`
on first use; `TLC_JAVA` and `TLC_JAR` override them). The whole check takes about 10 s.

The last line is the verdict:

- `WZNOWIENIE WYCENY OK` or `WZNOWIENIE WYCENY OK, ZNANE ZNALEZISKA: n`: every configuration ends as
  `model/oczekiwane.json` says. Exit 0 (1 with `--strict` and known findings).
- `WZNOWIENIE WYCENY: NOWE NARUSZENIE (n)`: a promise breaks on a path that is not a known finding. Exit 1.
- `WZNOWIENIE WYCENY: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change below and
  remove it from `model/oczekiwane.json`. Exit 1.
- `WZNOWIENIE WYCENY: BŁĄD MODELU (n)`: TLC gave no verdict or `TypeOK` broke. Exit 2.
- `WZNOWIENIE WYCENY: ROZJAZD MODELU Z KODEM` (CI only): a definition in `model/definicje.json` changed since the Sync commit.

Each counterexample is told as numbered steps in the code's words, with the quantities in efenix
(`[A |-> …, B |-> …, C |-> …]` per order) and the trace file on disk per order (`zaladowany {B}`: „Emmett załadowany”
with B written ahead).

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/WznowienieWyceny.tla` and one configuration with
the `Wybaczone…` constants as they are (empty), and it shows each broken promise as its shortest path in plain words.

Then tell a real bug from a modeling error: replay the path on the code, one step per action, as a test with the
Atrapa efenix (`tests/test_wycena_efenix.py`: `_run(..., window=...)` to stop the window after a server write,
`expire_after=(SAVE_QUANTITY, n)` for a refused save, `atrapa.edit` for Dad, `monkeypatch` of
`efenix_emmett_trace._replace` and `Path.unlink` for a failed trace write). A path that does not happen on the code
means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two orders, three Uruchomienia, one change by Dad, no failures | passes |
| `przerwania` | two orders, three Uruchomienia, Zatrzymanie, refused save and switch-off at every step, no change by Dad | known `przerwanie-po-zaladuj`, `przerwanie-przed-zapisem-ilosci` |
| `tata-po-przerwaniu` | one order, three Uruchomienia, Zatrzymanie, refused save and switch-off, one change by Dad | known `przerwanie-po-zaladuj`, `przerwanie-przed-zapisem-ilosci`, `tata-wpisal-ilosc-ze-sladu` |
| `slad` | two orders, three Uruchomienia, two failed trace writes (with and without a failed `unlink`), one change by Dad | known `slad-nie-zapisany` |
| `wszystko` | everything above at once, one failed trace write, a page after Emmett without a position | the five known findings |

Each order has three positions: Emmett fills A, the tool enters B and C.

## Known findings

Each finding is forgiven only for its promise and only when its cause happened in the same order before the event
that breaks it (the variable `slady`, one set per order); any other path is a new violation. All five are accepted:
each leaves efenix unchanged or keeps everything Dad entered or removed.

1. **`przerwanie-po-zaladuj`, BladTylkoPoZmianieTaty.** A Zatrzymanie or switch-off between the click of „Załaduj do
   zlecenia” and the read of the reloaded page leaves Emmett in efenix and no trace, so the next Uruchomienie only
   compares and gives `EFENIX_WYCENA_INNA`. The docstring of `efenix_emmett_trace.py` accepts this, and
   `test_przerwanie_po_zaladuj_do_zlecenia_przed_odczytem_wyceny_emmetta_daje_przy_ponownym_uruchomieniu_blad_tylko_tego_zlecenia`
   pins it. It is the safe direction: nothing changes in efenix.
2. **`slad-nie-zapisany`, BladTylkoPoZmianieTaty.** A failed trace write leaves on disk no „Emmett załadowany” of an
   order, or one without its latest write ahead (the file removed by `unlink`, or the previous file kept); when the
   Uruchomienie ends before that order does (also the Zatrzymanie after a failed write ahead,
   `EFENIX_SLAD_NIEZAPISANY`), the next one only compares it. Same direction as 1;
   `test_slad_wyceny_emmetta_ktorego_nie_da_sie_zastapic_znika_z_dysku_a_wznowienie_staje_bez_ilosci_bez_zapisu_z_wyprzedzeniem`
   pins it.
3. **`przerwanie-przed-zapisem-ilosci`, BladTylkoPoZmianieTaty.** A Zatrzymanie other than `LoggedOut`, or a
   switch-off, after the write ahead of a quantity and before efenix saved it leaves in the trace a quantity efenix does
   not have. The page cannot tell it from a quantity Dad removed, so the next Uruchomienie gives `EFENIX_WYCENA_INNA` and
   changes nothing. `test_odciecie_efenix_od_kazdego_zadania_wyceny_…[12-action_save_index.php-CUT]` pins it. Since
   #881 the write ahead comes after the human-pace pause (`efenix_pace`, 2 s), right before the window's save action
   (`_WrittenAhead` under `Pacing.window`), so a switch-off in the pause no longer causes this finding:
   `test_zgasniecie_centrum_w_przerwie_tempa_przed_iloscia_daje_wznowienie_ktore_konczy_zlecenie_jak_jeden_przebieg`
   resumes such an order like one run. The window is now the save action itself: the field fill, Enter and the request.
   A tab Dad closes in the pause still causes it, because the window learns of the closed tab only in that action
   (`WindowClosed` with `Closed.DURING_ACTION`, which cannot tell a closed tab before the request from one during it).
   The model has no time, so it is unchanged: `Zapowiedz` and `Wpisz` were and stay two steps with a stop between.
4. **`tata-wpisal-ilosc-ze-sladu`, ZmianaTatyZostaje.** After the stop of 3, Dad enters by hand exactly the quantity the
   tool was about to enter in that position: the page is the same as after the tool's own save, so the next Uruchomienie
   enters the remaining quantities of the file. Nothing Dad entered or removed changes; the two pages cannot be told
   apart.
5. **`brak-pozycji-po-emmetcie`, BladTylkoPoZmianieTaty.** A page after „Załaduj do zlecenia” without a position that
   has a quantity in the file ends the order with an error before `trace.loaded`, so Emmett stays in efenix with no
   trace. In the code the next Uruchomienie stops at the same check when it opens the order (`EFENIX_BRAK_POZYCJI`), and
   only compares once the position is back; the model tells both as „wycena już jest i się różni”. Nothing changes in
   efenix.

Fixed on the Sync commit by the write ahead and the strict `as_left_after_emmett`: `przerwanie-po-ilosci` (#864: a
Zatrzymanie after efenix saved a quantity and before `trace.finished`, then Dad removes it, and the next Uruchomienie
entered it again) and `slad-zostal-po-gotowe` (#865: the write of „gotowe” and the `unlink` both fail, and the stale
„Emmett załadowany” let the next Uruchomienie add back a quantity Dad removed). A stale „Emmett załadowany” now has
every quantity the tool may have entered, so completing an order from it writes nothing over Dad's changes. With three
positions the model also found that the loose rule before the fix (a position empty at Emmett could hold the file's
quantity) completed a pricing to which Dad had added a quantity by hand after a stop; the strict rule closes it.

`trace.finished` and the `unlink` after a failed write still keep a finished order from being completed after Dad
changes the Plik zbiorczy (outside the model, see Scope), but no promise of the model depends on them any more, so
`check_model_wznowienia_mutations.py` has no mutation for them; the tests
`test_ostrzezenie_emmetta_konczy_zlecenie_wiec_po_zmianie_pliku_na_ilosc_emmetta_ponowne_uruchomienie_tylko_porownuje`
and `test_slad_wyceny_emmetta_ktorego_nie_da_sie_zastapic_znika_z_dysku_a_wznowienie_staje_bez_ilosci_bez_zapisu_z_wyprzedzeniem`
fail without them.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   Never weaken a promise or narrow a configuration to make the check pass.
3. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_wznowienia_mutations.py` with the code counterpart in its name.
4. Run the check. A new violation is a finding: replay it on the code (see Read a result) before you call it a bug,
   report it with the path, and do not change product code unless asked.
5. Move the Sync commit forward only after every row of the table describes the code at the new commit, and write in
   one sentence what changed in the model and why.

## Scope

Verified: the four promises over every order of the actions above for the bounds of each configuration (one or two
orders, three positions, quantities 0..2, three Uruchomienia, one change by Dad, up to two failed trace writes). An
order is the same in any scope: the tool handles one at a time and the trace keeps them apart, so two orders show the
interplay of one trace file.

Left out, each a reason the check can pass while the code is wrong:

- **Dad changing efenix during an Uruchomienie.** Every configuration has `TataWTrakcie = FALSE`. With `TRUE`, TLC
  breaks NieCzysciWycenyTaty: Dad enters a quantity between `open_order` and „Załaduj do zlecenia”, and Emmett wipes
  it (and ZnacznikTylkoNaWycenionym: he changes the order between its result and `_mark`). efenix has no
  check-and-load, so this is a limit of the design (ADR 0024: the tool works in Dad's session while he does not work
  in efenix), not a finding of this check.
- **A power loss right after a trace write.** The model treats a successful write as on disk. `_replace` replaces the
  file atomically but flushes neither the file nor the folder, so after a power loss in the seconds after a write the
  file system may show the previous trace, without the latest write ahead; a killed or closed Centrum keeps every
  write, because the operating system finishes it.
- **The execution date** (`set_execution_date`, `DateRefused`) and the checks before the page (`listing`, statuses,
  `missing_positions` at opening and after the date): they change nothing in efenix that a later Uruchomienie decides
  on, except the date, whose write before Emmett is harmless (amount stays 0). `missing_positions` after Emmett is
  `BrakPozycji`.
- **Emmett contradicting the file** (`EmmettWarning`): the model's Emmett agrees with the file.
- **The window's classification of failures** (which exception for which HTTP answer): every failure is one
  `Zatrzymanie`, except `LoggedOut` from `enter_quantity`, which is `Odmowa`. The Atrapa tests in
  `tests/test_wycena_efenix.py` (`SWEEP`) drive that.
- **`mark_ready` refusing** (Excel holds the file, the file changed): the model marks always; a refusal only leaves
  ready orders unmarked until the next Uruchomienie.
- **Dad editing the Plik zbiorczy** between Uruchomienia, and the Dziennik Wyceny (`pricing_journal.py`), which only
  records.

## Files

- `model/WznowienieWyceny.tla`: the model, with the code each action describes.
- `model/*.cfg`: the configurations (first line describes it), `model/oczekiwane.json`: the expected result.
- `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_wznowienie_wyceny.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_wznowienia_mutations.py`: proves the check fails when the model loses a guard the code has;
  run it through `.venv/bin/python .agents/skills/verify-wznowienie-wyceny-efenix/scripts/check_model_wznowienia_mutations.py`
  only to reproduce a red Mutation checks step or while you change the model.
