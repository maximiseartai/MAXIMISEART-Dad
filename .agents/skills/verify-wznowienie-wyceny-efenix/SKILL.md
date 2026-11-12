---
name: verify-wznowienie-wyceny-efenix
description: Model-check with TLA+ (TLC) that Wycena w efenix, across the Uruchomienia of one period, completes every order to the Plik zbiorczy only upwards (ADR 0026), never loads Wycena Emmetta over an order that has quantities, never lowers or clears a quantity in efenix, ends an order Dad changed with an Ostrzeżenie Emmetta exactly when it holds more than the file, puts a Znacznik efenix only beside an order priced as in the file and a Znacznik przekazania only beside such an order that is „Do akceptacji”, forwards to acceptance only a gotowe order and only in the mode with Przekazanie (ADR 0027), never changes an order „Do akceptacji”, and leaves Dad an error or an Ostrzeżenie Emmetta only for an order he changed, under every order of window Zatrzymania, Centrum switching off, efenix refusing a Przekazanie, both modes and Dad's own changes in efenix between Uruchomienia. Use when a change touches `save`, `_outcome`, `_priced_outcome`, `_forwarded`, `_priced`, `_emmett`, `_dated`, `_completed`, `_mark` or `_efenix_stops` in `src/rozliczenia/efenix_pricing.py`, `listing` in `src/rozliczenia/efenix_checks.py`, `Mark.replaces` in `src/rozliczenia/efenix_mark.py`, `completion` or `same_amount` in `src/rozliczenia/efenix_positions.py`, or `load_emmett`, `_came_whole`, `enter_quantity`, `forward_to_accept`, `_refusal`, `_status_answer`, `_go`, `_reloaded` in `src/rozliczenia/efenix_browser.py`, or when a resumed Wycena w efenix lowered, cleared or wiped a quantity in efenix or forwarded an order that was not gotowe.
pilnuje:
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/efenix_positions.py
  - src/rozliczenia/efenix_browser.py
  - src/rozliczenia/efenix_window.py
  - src/rozliczenia/efenix_checks.py
  - src/rozliczenia/efenix_mark.py
  - tools/lib/model_tlc.py
  - tools/lib/rozjazd_modelu.py
  - tools/lib/narzedzia_tlc.py
ci: .agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py
---

# Verify wznowienie Wyceny w efenix (TLA+)

## What CI runs and what stays local

CI runs `sprawdz_wznowienie_wyceny.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's
`pilnuje:` or folder, so run it locally only while you bring the model in line or to reproduce a red Mutation checks
step. In CI the Mutation checks step does not start while covered code differs from its digests in `model/definicje.json`: it fails with a `ROZJAZD MODELU Z KODEM | <skill>: …` line, but it cannot tell whether your change to the model is right.
`tools/szybko.py` fails on the same drift before you push (step `rozjazd modelu`, without TLC) whenever the change would run this check on a pull request; one module, `tools/lib/rozjazd_modelu.py`, decides what drift is for both.
`check_model_wznowienia_mutations.py` runs on a pull request that changes a file in `model/`, the script itself or
`sprawdz_wznowienie_wyceny.py`, and in full CI and nightly on `main` after a change of this skill's folder.
What stays with you on every change to the covered code is „Bring the model in line, then run”: read the diff against
the table, change the model, break the new path in it, and run the check while you do. A change whose model nobody
brought in line is not verified, whatever CI says.

## The promises

Wycena w efenix writes on a server Dad works on every day: a quantity is saved the moment the field loses focus, and
„Załaduj do zlecenia” (Wycena Emmetta) wipes every quantity of the order (ADR 0024). Since #960 the tool completes every
order to the Plik zbiorczy only upwards (ADR 0026): in each position where efenix has less than the file it enters the
file's quantity, also over Emmett's and in a pricing that already is, and a position where efenix has more stays and
gives an Ostrzeżenie Emmetta. The decision depends only on the file and the page, so the tool keeps nothing between
Uruchomienia. Since ADR 0027 Dad picks a mode for each Uruchomienie: without Przekazanie (as before) or with it, in which
the tool forwards a gotowe order to acceptance (the green „Zapisz”) and confirms it by searching again; an order „Do
akceptacji” on the list is an Zlecenie przekazane in both modes, which the tool does not open. The model checks seven
promises over every order of steps:

- **NieCzysciWycenyTaty**: the tool loads Wycena Emmetta only into an order with no quantity, so it never wipes a
  pricing, Dad's or its own.
- **NieObnizaIlosci**: the tool never lowers or clears a quantity in efenix: every quantity it writes (Emmett's on
  „Załaduj do zlecenia”, the file's with `enter_quantity`) is at least the one it replaces.
- **ZmianaTatyZostaje**: an order in which Dad changed a quantity by hand ends with an Ostrzeżenie Emmetta when it holds
  more than the file (his quantity stays), and is gotowe otherwise: a quantity he lowered or removed below the file the
  tool raises back to the file (ADR 0026, #960).
- **ZnacznikTylkoNaWycenionym**: a Znacznik efenix appears in `ADRES` only beside an order whose pricing in efenix equals
  the file at the moment of marking, a Znacznik przekazania only beside such an order that is also „Do akceptacji”, a
  Znacznik efenix never replaces a Znacznik przekazania, and no Znacznik disappears.
- **BladTylkoPoZmianieTaty**: Dad gets an error or an Ostrzeżenie Emmetta only for an order he changed himself; an
  order the tool started, also one a Zatrzymanie or a switch-off cut, the next Uruchomienie finishes as gotowe (or
  przekazane).
- **PrzekazujeTylkoGotowe**: the tool forwards an order to acceptance only when its pricing in efenix equals the file
  (no excess, amount equal to `Kwota` (AU)) and only in an Uruchomienie with Przekazanie.
- **NieZmieniaPrzekazanego**: in an order „Do akceptacji” the tool changes nothing: no Wycena Emmetta, no quantity and
  no second Przekazanie.

Until #960, **ZmianaTatyZostaje** read: „in an order with a pricing in which Dad changed, added or removed something by
hand, the tool writes nothing; it does not add back a quantity he removed. That page is the error „wycena już jest i
się różni” with no change”. Dad answered after the run of 4.11.2026 that the Plik zbiorczy is right, not efenix, so a
change of his below the file is no longer protected (ADR 0026); one above it is, by NieObnizaIlosci and the Ostrzeżenie
Emmetta.

Harm: for the first, Dad's or the tool's work on an order disappears from efenix and the company sees an empty or
Emmett-only pricing. For the second, the company gets less than Dad did, with his name on it. For the third, a
quantity Dad raised on purpose is either lost or passes without a word and the order is marked. For the fourth, Dad
trusts a Znacznik and skips an order that is wrong in efenix. For the fifth, Dad has to finish by hand an order the tool
left half-done (49 orders after the run of 4.11.2026, #960). For the sixth, the company gets for acceptance an order
that differs from the file, or one Dad did not want forwarded, and the tool cannot take it back. For the seventh, the
tool changes an order the company already checks.

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/WznowienieWyceny.tla`, not the code. It describes the code only while
you keep the two in step. Each model action is one indivisible step of this code:

| Model action | Code |
| --- | --- |
| `Start` | `efenix_pricing.py` `price_orders.save`: the orders of the scope in order |
| `Otworz` | `_outcome` → `_priced_outcome`: `efenix.search` and `listing`; an order „Do akceptacji” is `Forwarded` without `open_order` (result `przekazane`). Otherwise `open_order`, `_dated` when the execution date is empty (on a page with or without quantities; it writes only the date, which the model leaves out), then the decision on the page: a page without any quantity (`not _priced(opened)`) goes to Wycena Emmetta; a page with quantities goes straight to `_completed` (`completion` in `efenix_positions.py`: `to_enter` where the page has less than the file, `excess` where it has more), with the result at once when nothing is to be entered |
| `ZaladujEmmetta` | `_outcome`: `efenix.load_emmett(_emmett)` up to the click of „Załaduj do zlecenia”, after which efenix holds Wycena Emmetta (`efenix_browser.BrowserEfenix.load_emmett`, `_answer(LOAD_EMMETT, …)`); before the click the window counts the Emmett dialogs, waits until one is visible and applies `efenix_page.emmett_window_fault` (exactly one dialog, then exactly one proposal in it; otherwise `UnexpectedPage` with `ElementCount` before the click, so `Zatrzymanie` in place of this step), and reads whether the Emmett dialog shows a proposal (`#emmett-propozycja`, `efenix_page.emmett_window`) and whether the answer to `action_fill_emmett.php` came whole with 2xx (`_came_whole`, #908) into a `Proposal`, and it never reads the body of the answer to „Załaduj do zlecenia” (#895). An answer that refuses it raises: a redirect in `load_emmett` and a 4xx/5xx in `_finished` (`_ErrorAnswer`, #878) before the page is read, and a 2xx after which the Wycena's verdict `_emmett`, which the window runs inside its action on its `EmmettLoad`, finds the reloaded page (`_read_order`) without any quantity (`not _priced(load.page)`, also with an amount other than 0 from a card with an entered price) although Emmett did not propose nothing (`Proposal.NOTHING`; `Shape.EMMETT_NOT_LOADED`, #889, #908). When efenix did not load Wycena Emmetta that is `Zatrzymanie` in place of this step; when it loaded it and still answered with an error (a 5xx after the load) it is this step and then `Zatrzymanie` before `OdczytPoEmmetcie` |
| `OdczytPoEmmetcie` | `load_emmett` reads the reloaded page (`_read_order`) and `_emmett` accepts it, then `_completed` on it: `completion` from Emmett's quantities |
| `BrakPozycji` | `_outcome`: `missing_positions(..., PageRead.AFTER_EMMETT)` is `OrderError` after `load_emmett`, before `_completed` |
| `Wpisz` | `_completed` → the window's `enter_quantity(position, quantity)` with the file's quantity, up to the moment efenix saved it (`BrowserEfenix.enter_quantity`, `_answer(SAVE_QUANTITY, …)`) |
| `Potwierdz` | `enter_quantity` after the save: the JSON answer and the amount on the page; after the last position `_completed` gives `EmmettWarning(plan.excess)` when `excess` is not empty, and otherwise compares the amount with `Kwota` (`same_amount`); a `Ready` in the mode with Przekazanie (`mode is PricingMode.FORWARD` in `_outcome`) goes on to `Przekaz` instead of the result (the same after `Otworz` and `OdczytPoEmmetcie` when nothing is to be entered) |
| `Przekaz` | `_forwarded`: the window's `forward_to_accept` up to the moment efenix changed the status (`BrowserEfenix.forward_to_accept`, the click of „Tak” and `_status_answer`, the only `action_change_status.php` request the window's guard lets through) |
| `OdmowaPrzekazania` | `_forwarded`: the window's `forward_to_accept`, in which efenix shows its information dialog `#dialog_info` instead of the status dialog after the green „Zapisz” (`BrowserEfenix._refusal`: the window waits for one of the two dialogs, reads the text into a `ForwardRefusal`, closes the dialog and clicks no „Tak”, so nothing reaches efenix); `_forwarded` returns `OrderError(refusal)` without the search, and the order has no Znacznik |
| `Szukaj` | `_forwarded` after the answer: the reload of the page, `efenix.search` again and `listing`: „Do akceptacji” is `Forwarded` (result `przekazane`), any other list `OrderError(OrderProblem.NOT_FORWARDED)` |
| `KoniecZlecenia` | `save`: the result goes to `results` and `journal.ended`, then the next order |
| `Zatrzymanie` | `LoggedOut`, `UnexpectedPage`, `WindowClosed`, `EfenixUnreachable` from any window action, also `LoggedOut` from `enter_quantity` (efenix did not save the quantity: step `wpisz`), a stop after efenix saved it (step `potwierdz`), a Przekazanie efenix did not get (step `przekaz`, also one the window's guard aborted, `StatusChangeBlocked`) and a stop in the search after it (step `szukaj`): the window's exception passes through `_outcome`, `_efenix_stops` in `save` turns it into `StopError`, and `save` (`except StopError`) calls `_mark` with the results before it; the order the window stopped at has no result, so no Znacznik |
| `Znaczniki` | `save`: `_mark` (`mark_orders` with `Mark.READY` for every `Ready` row and `Mark.FORWARDED` for every `Forwarded` row; `Mark.replaces`: a Znacznik przekazania replaces a Znacznik efenix, never the other way), also after `StopError`, then the end of the Uruchomienie |
| `Zgasniecie` | none: Centrum switches off or is killed; memory is gone, efenix stays, no Znaczniki |
| `Tata` | none: Dad changes a quantity of an order „Do wyceny” in efenix by hand while no Uruchomienie runs (`StanEfenix.edit` in the tests) |

The script compares these definitions with their digests (`model/definicje.json`, a name is a path from the module):
`price_orders.save`, `_mark`, `_efenix_stops`,
`_outcome`, `_priced_outcome`, `_forwarded`, `_priced`, `_emmett`, `_dated`, `_completed` in
`src/rozliczenia/efenix_pricing.py`; `listing` in `src/rozliczenia/efenix_checks.py`; `Mark.replaces` in
`src/rozliczenia/efenix_mark.py`; `completion`, `same_amount` in `src/rozliczenia/efenix_positions.py`;
`BrowserEfenix.load_emmett`, `_came_whole`, `BrowserEfenix.enter_quantity`, `BrowserEfenix._finished`,
`BrowserEfenix.forward_to_accept`, `BrowserEfenix._refusal`,
`BrowserEfenix._status_answer`, `BrowserEfenix._go`, `BrowserEfenix._reloaded` in `src/rozliczenia/efenix_browser.py`. A change elsewhere in these files (Sprawdzanie, Odczyt danych, Logi, the window's
classification of other failures) does not move the model. A change that makes another function write in efenix or
decide whether an order is finished does, though no definition above changes: add it to the table and to
`model/definicje.json`.
The window's exceptions (`LoggedOut`, `UnexpectedPage`, `WindowClosed`, `EfenixUnreachable`) and `WindowStop.sent`, which
`Zatrzymanie` reads, live in `src/rozliczenia/efenix_window.py`, in `pilnuje:` but not in `model/definicje.json`: a change of
when a window action counts as sent moves the model, though no definition above changes.

The digests in `model/definicje.json` were taken when every row of the table was last checked against the code
(`tools/przesun_model.py`); what that check found is in the message of the commit that changed the digests. Check what
changed since: `git diff $(git log -1 --format=%h -- .agents/skills/verify-wznowienie-wyceny-efenix/model/definicje.json)
-- src/rozliczenia/efenix_pricing.py src/rozliczenia/efenix_positions.py src/rozliczenia/efenix_browser.py
src/rozliczenia/efenix_checks.py src/rozliczenia/efenix_mark.py`.

## Run

```sh
.venv/bin/python .agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py
py -3 .agents\skills\verify-wznowienie-wyceny-efenix\scripts\sprawdz_wznowienie_wyceny.py
```

`--config NAME` runs one configuration, `--strict` fails also on known findings. The run of TLC, the verdict and the
known findings are `tools/lib/model_tlc.py`, which every skill with a TLA+ model shares; Java and `tla2tools.jar` come
from `tools/lib/narzedzia_tlc.py` (pinned `jdk4py` and the jar in `.verification/` on first use; `TLC_JAVA` and
`TLC_JAR` override them). The whole check took 3.5 s on Maks's Mac (2026-11-05).

The last line is the verdict:

- `WZNOWIENIE WYCENY OK` or `WZNOWIENIE WYCENY OK, ZNANE ZNALEZISKA: n`: every configuration ends as
  `model/konfiguracje.json` says. Exit 0 (1 with `--strict` and known findings).
- `WZNOWIENIE WYCENY: NOWE NARUSZENIE (n)`: a promise breaks on a path that is not a known finding. Exit 1.
- `WZNOWIENIE WYCENY: ZNALEZISKO ZNIKNĘŁO (n)`: a known finding no longer happens. Describe the change below and
  remove it from `znane` of its configuration in `model/konfiguracje.json`. Exit 1.
- `WZNOWIENIE WYCENY: BŁĄD MODELU (n)`: TLC gave no verdict, an invariant outside the promises such as `TypeOK` broke,
  `model/konfiguracje.json` has another shape, or the counterexample's story in the script does not know every action
  of `Next`. Exit 2.
- `UWAGA: kod opisany modelem zmienił się: …` above the verdict: a definition in `model/definicje.json` differs from its
  digest there, and the verdict means nothing until you bring the model in line. CI does not run the check then.

Each counterexample is told as numbered steps in the code's words, with the quantities in efenix
(`[A |-> …, B |-> …, C |-> …]` per order) and the result of each order in this Uruchomienie.

## Read a result

Read every result with the pstack `/statechart` skill: give it `model/WznowienieWyceny.tla` and one configuration with
the `Wybaczone…` constants as they are (empty), and it shows each broken promise as its shortest path in plain words.

Then tell a real bug from a modeling error: replay the path on the code, one step per action, as a test in
`tests/test_wycena_efenix.py`: on the window in process (`_run_in_process` with `StanEfenix(..., expire_after=(Action.QUANTITY, n))`
for a refused save and `StanEfenix.edit` for Dad), or with the Atrapa efenix in Chromium (`_run(..., window=...)`) to stop
the window after a server write. A path that does not happen on the code means the model is wrong until you show it is not.

## Configurations

| Configuration | What can happen | Expected |
| --- | --- | --- |
| `zwykle` | two orders, three Uruchomienia in either mode, one change by Dad, no failures | passes |
| `przerwania` | two orders, three Uruchomienia, Zatrzymanie and switch-off at every step, no change by Dad | passes |
| `tata-po-przerwaniu` | one order, three Uruchomienia, Zatrzymanie and switch-off, one change by Dad | passes |
| `wszystko` | everything above at once, a page after Emmett without a position, efenix refusing a Przekazanie | known `brak-pozycji-po-emmetcie`, `odmowa-przekazania` |

Every configuration lets Dad pick either mode at each Uruchomienie (`MozePrzekazac = TRUE`).
Each order has three positions; the Plik zbiorczy has 1 in A and C and 2 in B. Emmett gives A as the file and B one less
than the file and leaves C empty, so the tool enters B over Emmett's quantity and C. Only Dad puts more than the file
into efenix (2 in A or C).

## Known findings

Each finding is forgiven only for its promise and only when its cause happened in the same order before the event
that breaks it (the variable `slady`, one set per order); any other path is a new violation.

1. **`brak-pozycji-po-emmetcie`, BladTylkoPoZmianieTaty.** A page after „Załaduj do zlecenia” without a position that
   has a quantity in the file ends the order with an error (`EFENIX_BRAK_POZYCJI`), so Emmett stays in efenix. In the
   code the next Uruchomienie stops at the same check when it opens the order, and finishes the order to the file once
   the position is back. Nothing in efenix is lowered; Dad prices such an order himself.
2. **`odmowa-przekazania`, BladTylkoPoZmianieTaty and ZmianaTatyZostaje.** efenix refuses the green „Zapisz” of a gotowe
   order in its information dialog (no photos, no length of the connection, no pricing or no execution date, page script
   from the reconnaissance), so the order ends with an error (`EFENIX_ODMOWA_PRZEKAZANIA`) without a Znacznik, also an
   order Dad did not change. Nothing reaches efenix; the next Uruchomienie with Przekazanie tries again. Accepted by the
   coordinator's decision of 7.11.2026: Dad fills in what efenix lacks.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table above. Find each action whose code changed, or the new step that has none.
2. Change the model so each action is again one indivisible step of the code, with the code's names in its comment.
   Never weaken a promise or narrow a configuration to make the check pass. A new action of `Next` gets its words in
   `_STEPS` of the script, or the check ends with `BŁĄD MODELU` before TLC.
3. Break the new path in the model on purpose (remove the guard you just added) and see the check fail; add that break
   to `scripts/check_model_wznowienia_mutations.py` with the code counterpart in its name.
4. Run the check. A new violation is a finding: replay it on the code (see Read a result) before you call it a bug,
   report it with the path, and do not change product code unless asked.
5. Run `tools/przesun_model.py verify-wznowienie-wyceny-efenix` only after every row of the table describes the code,
   and write in the commit message, in one sentence, what changed in the model and why.

## Scope

Verified: the seven promises over every order of the actions above for the bounds of each configuration (one or two
orders, three positions, quantities 0..2, three Uruchomienia, each in either mode, one change by Dad). An order is the same in any scope: the
tool handles one at a time and decides from its page alone, so two orders show the interplay of one Uruchomienie.

Left out, each a reason the check can pass while the code is wrong:

- **A Przekazanie efenix answers without changing the status, and the company sending an order back „Do wyceny”.**
  In the model the status always changes, so `Szukaj` always gives przekazane and an order „Do akceptacji” never comes
  back. The error `NOT_FORWARDED` without a Znacznik is driven by
  `test_przekazanie_ktorego_efenix_nie_pokazuje_potem_jako_do_akceptacji_to_blad_zlecenia_bez_znacznika`, and a
  Znacznik przekazania beside an order that is gotowe again (it stays) by
  `test_znacznik_przekazania_zastepuje_znacznik_efenix_a_znacznik_efenix_nigdy_nie_zastepuje_znacznika_przekazania`.
- **The window's guard of status changes** (`BrowserEfenix.guard`): every request it aborts is one `Zatrzymanie` at step
  `przekaz` (or at the step it came in); that no aborted request reaches efenix is driven on the Atrapa efenix in
  `tests/test_wycena_efenix.py` (`StatusChange`).

- **Dad changing efenix during an Uruchomienie.** Every configuration has `TataWTrakcie = FALSE`. With `TRUE`, TLC
  breaks NieCzysciWycenyTaty: Dad enters a quantity between `open_order` and „Załaduj do zlecenia”, and Emmett wipes
  it, NieObnizaIlosci on the same path (TLC, 2026-11-05, each promise in a configuration of its own), and
  ZnacznikTylkoNaWycenionym: he changes the order between its result and `_mark`. efenix has no check-and-write, so this is a limit of the design (ADR 0024: the tool works in Dad's session
  while he does not work in efenix), not a finding of this check.
- **The execution date** (`set_execution_date`, `DateRefused`) and the checks before the page (`listing`, statuses,
  `missing_positions` at opening and after the date): they change nothing in efenix that a later Uruchomienie decides
  on, except the date. Since Maks's decision of 5.11.2026 `_dated` sets an empty date from `DATA` on a page with or
  without quantities before Emmett and `_completed`; it writes no quantity, a refused date ends the order before any
  quantity changes, and a later Uruchomienie accepts the date it wrote (`date_problem`), so none of the five promises
  depends on it. `missing_positions` after Emmett is `BrakPozycji`.
- **Emmett with more than the file.** The model's Emmett never exceeds the file (in the Logs of 4.11.2026 none of 108
  loads did); an excess from Dad takes the same path through `completion`, and
  `test_pozycja_z_wieksza_iloscia_w_efenix_niz_w_pliku_zostaje_a_reszta_zlecenia_jest_dopisana_z_ostrzezeniem_emmetta`
  drives Emmett's excess on the Atrapa efenix.
- **Several prices.** Every position costs 1, so an amount equal to `Kwota` (AU) with no excess means the file's
  quantities; `same_amount` with real prices is covered by the tests of `tests/test_wycena_efenix.py`.
- **The window's classification of failures** (which exception for which HTTP answer): every failure is one
  `Zatrzymanie`. The Atrapa tests in `tests/test_wycena_efenix.py` (`SWEEP`) drive that.
- **`mark_ready` refusing** (Excel holds the file, the file changed): the model marks always; a refusal only leaves
  ready orders unmarked until the next Uruchomienie.
- **Dad editing the Plik zbiorczy** between Uruchomienia, and the Dziennik Wyceny (`Journal` in `logs_disk.py`), which only
  records. The tool reads the file anew in each Uruchomienie, so a change of the file only changes what `completion`
  aims at (`test_po_ostrzezeniu_emmetta_tata_poprawia_plik_…`).

## Files

- `model/WznowienieWyceny.tla`: the model, with the code each action describes.
- `model/konfiguracje.json`: the configurations (description, constants and known findings; the script writes each
  `.cfg` with `TypeOK` and every promise).
- `model/definicje.json`: the definitions of the code the model describes.
- `scripts/sprawdz_wznowienie_wyceny.py`: runs TLC on every configuration and tells each counterexample.
- `scripts/check_model_wznowienia_mutations.py`: proves the check fails when the model loses a guard the code has;
  run it through `.venv/bin/python .agents/skills/verify-wznowienie-wyceny-efenix/scripts/check_model_wznowienia_mutations.py`
  only to reproduce a red Mutation checks step or while you change the model.
