---
name: verify-karta-efenix
description: Interleave Dad's clicks in the tool's efenix tab (he opens another order, goes back to the list, reloads the page) with every write of a real Wycena w efenix (the window `efenix_browser.window` in Playwright's Chromium on the Atrapa efenix) and check that each write (execution date, „Załaduj do zlecenia”, quantity, Przekazanie do akceptacji) reaches efenix with the order the process read (`_order_id`) and that no other order changes. Use when a change touches `open_order`, `set_execution_date`, `load_emmett`, `enter_quantity`, `forward_to_accept`, `guard`, `_blocked_cause`, `_go` or `_reloaded` in `src/rozliczenia/efenix_browser.py`, the pauses in `src/rozliczenia/efenix_pace.py`, the order of writes in `src/rozliczenia/efenix_pricing.py`, how the Atrapa efenix page script picks the order of a request, or when a write of Wycena w efenix landed in an order the tool never read.
pilnuje:
  - src/rozliczenia/efenix_browser.py
  - src/rozliczenia/efenix_page.py
  - src/rozliczenia/efenix_pace.py
  - src/rozliczenia/efenix_pricing.py
  - src/rozliczenia/efenix_window.py
  - tools/lib/atrapy/atrapa_efenix.py
  - tools/lib/atrapy/model_efenix.py
  - tools/lib/atrapy/efenix.py
  - tools/lib/eksplorator.py
  - tools/lib/rozjazd_modelu.py
ci: .agents/skills/verify-karta-efenix/scripts/explore_karta_efenix.py
---

# Verify karta efenix

## What CI runs and what stays local

CI runs `explore_karta_efenix.py` (the `ci:` key) in Mutation checks whenever a change touches this skill's `pilnuje:`
or folder, and `check_karta_efenix_mutations.py` in full CI on `main` and nightly on `main` after a change of this
skill's folder. Run them locally only to reproduce a red CI step or the night's issue, or one `--przypadek` while you
work on it. In CI the step does not start while code in `model/definicje.json` differs from its digests (line
`ROZJAZD MODELU Z KODEM | verify-karta-efenix: …`), and `tools/szybko.py` fails on the same drift before you push.
What stays with you: „Does the change touch it?” (a new way for the window to write in efenix, a new thing Dad can do in
the tab), bringing the model in line when the drift says so, and sorting a red run as „When the check fails” says.

## The promise

- **ZAPIS_W_PRZECZYTANYM**: every write of Wycena w efenix in efenix (the execution date, „Załaduj do zlecenia” of
  Wycena Emmetta, a quantity, Przekazanie do akceptacji) reaches efenix with the identifier of the order the process
  read (`open_order` sets `_order_id`), and no other order changes, also when Dad clicks in the tool's tab between
  the steps: he opens another order, goes back to the list of orders, or reloads the page. A write the window cannot
  aim at its order must end in a Zatrzymanie, not elsewhere.
  Harm: „Załaduj do zlecenia” in someone else's order wipes its pricing (ADR 0024), which Dad does not see, and the
  order the tool was pricing gets a result (even gotowe with a Znacznik efenix) computed from the other page.

Two more rules keep the check honest: **PRZEBIEG_WZORCOWY**, a run without Dad ends order A gotowe (mode without
Przekazanie) or przekazane (mode with it) with the file's quantities and date in efenix, so the scenario reaches every
write; and **BEZ_WYJATKU**, a run ends with a result or a Zatrzymanie of kind `stop`, never with an unexpected error: neither an exception escaping `run_process` nor the Zatrzymanie `EFENIX_BLAD_NIEOCZEKIWANY` that `run_process` makes of one.

## Why an explorer and not a TLA+ model

Where a write lands is decided by two facts of the code and the page, not by an order of abstract steps: the window
clicks a button or field of whatever page the tab shows (`set_execution_date`, `load_emmett`, `enter_quantity` read
no URL and no order identifier), and the page script of efenix takes the order of each request from that page
(`data-record-id` of `#button-calendar` for `action_set_date_of_instalation.php`, the `order_id` attribute of
`#button_emmett` for `action_fill_emmett.php` and `action_load_emmett.php`, the `order_id` attribute of the field for
`action_save_index.php`, `#main_id` for `action_change_status.php`; copy of the efenix script from the reconnaissance
of 1.11.2026, which the Atrapa follows). A TLA+ model would have to assume exactly these facts. The space of Dad's
interleavings is small and finite (three actions at six points), so the explorer runs the real process, window, page
scripts and requests for every one of them in about 15 s.

## Does the change touch it?

The explorer runs the real code, so a change of the window, the pricing or the Atrapa page script is checked as it is.
Two parts are modelled by hand, and their code is in `model/definicje.json`:

| Hand-made part | Code it stands for |
| --- | --- |
| Dad acts in each pause before a write: `Pace.sleep` is his hook | `Pacing.before_write`, `_PacedEfenix._paced` in `src/rozliczenia/efenix_pace.py`: the pause `ACTION_PAUSE_S` before each write (date, Emmett, quantity, Przekazanie) |
| Dad acts during the reload after „Załaduj do zlecenia”: the `requestfinished` of `action_load_emmett.php` | the efenix script reloads the page after the answer (`EFENIX_EMMETT_RELOAD_MS`, about 1 s), and `BrowserEfenix.load_emmett` reads the page the navigation brings, which `BrowserEfenix._reloaded` waits for |
| The known finding below | `BrowserEfenix.open_order`, `set_execution_date`, `load_emmett`, `enter_quantity`, `_blocked_cause`, and `_go` and `_reloaded`, through which the window navigates, in `src/rozliczenia/efenix_browser.py` |

A change that makes the window write in efenix in a new way (a new request with an order, a new action) is checked only
if its request is in `WRITES` of the explorer: add it there with the field that carries the order.

## Run

```sh
.venv/bin/python .agents/skills/verify-karta-efenix/scripts/explore_karta_efenix.py
py -3 .agents\skills\verify-karta-efenix\scripts\explore_karta_efenix.py
```

`--lista` prints the cases, `--przypadek NAME` runs the two runs without Dad and one case, `--strict` counts the known
finding as a violation, `--przegladarki N` sets how many Chromium browsers run at once (default up to 4). The whole run,
2 runs without Dad and 18 cases, took 12.4 s on Maks's Mac with 4 browsers (2026-11-12). It needs Playwright's
Chromium (`playwright install chromium`).

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `KARTA EFENIX OK` or `KARTA EFENIX OK, ZNANE USTALENIA: n` | 0 | Every case keeps the rules, or breaks them only as the known finding below, printed with its counterexample. |
| `KARTA EFENIX: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below. |
| `KARTA EFENIX: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | The known finding did not show in a case of its `after`. If a change fixed it, narrow or delete it in `KNOWN_FINDINGS` and below. |
| `KARTA EFENIX: LUKA MODELU (n)` | 2 | The run without Dad has a write with no pause before it (Dad has no point there), or Dad never reached his point: no verdict on the rules. |

An `UWAGA:` line above the verdict means code in `model/definicje.json` changed: the verdict means nothing until you
bring the model in line.

## How it works and what it covers

Order A (synthetic Plik zbiorczy, one row) has an empty pricing and an empty execution date in the Atrapa; Emmett
gives 1 in T where the file has 2. Without Dad the process searches A, opens it, sets the date and opens it again,
loads Wycena Emmetta (the efenix script reloads the page after 1 s, as efenix does), enters T and AG over Emmett's and
ends A gotowe, and in the mode with Przekazanie forwards A and finds it „Do akceptacji”. Order B is someone else's
order with Dad's pricing (`012: 3, 016: 2`) and a date, which the process never reads.

The points are taken from the two runs without Dad: the pause right before each write (`przed-data`,
`przed-emmett`, `przed-ilosc-1`, `przed-ilosc-2`, and `przed-przekazanie` in the mode with Przekazanie) and the reload
after „Załaduj do zlecenia” (`w-przeladowaniu-po-zaladuj`). At each point Dad does one of `inne-zlecenie` (opens B in
the tab, as a link from the list does), `lista` (goes back to the list of orders) or `przeladowanie` (reloads the
tab). A case is `<action>@<point>`. The check reads every request the Atrapa received: a write whose order field is not
A is a stray write, and B must be as it was.

Result on the current code (2026-11-12): `lista` at every point ends in a Zatrzymanie (the window does not find the
element it clicks), `przeladowanie` at every point ends as the run without Dad, `inne-zlecenie@przed-przekazanie`
ends in a Zatrzymanie (the guard aborts `action_change_status.php` with B's `order_id`, `StatusChangeBlocked.OTHER_ORDER`),
and `inne-zlecenie` at the five other points is the known finding.

Not covered, each a way the check can pass while the code is wrong:

- **Clicks inside a window action.** Dad acts only in the pauses and in the reload after „Załaduj do zlecenia”, the
  windows in which he has time (2 s before each write, about 1 s for the reload). Between two browser steps of one
  action (the Emmett dialog shown and „Załaduj do zlecenia” clicked, a quantity filled and Enter) the window waits
  milliseconds; such a click is not explored.
- **Dad's clicks inside the page of A** (he types a quantity, clicks Emmett himself): that is Dad changing efenix
  during an Uruchomienie, which `verify-wznowienie-wyceny-efenix` leaves out by design (`TataWTrakcie = FALSE`).
- **Other tabs and windows.** The window's page is one tab; a tab Dad opens himself does not move it. Closing the tab
  is `verify-wycena-efenix` (`WindowClosed`).
- **More than one order in the Plik zbiorczy**: each order starts with `search` (which returns to the list) and
  `open_order` (which navigates to its own address), so a click before the next order is undone by them; only the
  points before writes matter.
- **The real efenix.** The Atrapa follows the copy of the efenix page script from 1.11.2026 in where each request takes
  its order. The calendar button `#button-calendar` is in the Atrapa on every order page; efenix shows it most likely
  only with an empty date (`tools/zgodnosc_efenix.py`, `DATE_BUTTON_BY_HAND`), so at Dad's the stray date needs an
  order B with an empty date. The fields `INDEKS_NNN_078` have the same identifier in every order (copy of the efenix
  page from the reconnaissance; `tools/zgodnosc_efenix.py` compares full codes with the Atrapa's and gave no difference on
  the live efenix on 8.11.2026), so `enter_quantity` finds its field on B's page.

## Known findings

1. **`zapis-w-zleceniu-z-karty`, ZAPIS_W_PRZECZYTANYM.** `set_execution_date`, `load_emmett` and `enter_quantity`
   check neither the URL nor the order of the tab: they click the button or field of the page that is there, and the
   page script takes the order from that page. `enter_quantity` matches the answer only by `index`
   (`params.get("index") == [field_id]`), which is the same in every order. Only Przekazanie is guarded
   (`_blocked_cause` compares `order_id` with `_order_id`). Counterexamples, each reproduced on the Atrapa efenix
   (`--przypadek`):
   - `inne-zlecenie@przed-emmett`: `open_order` sets `_order_id` = A; in the pause before „Załaduj do zlecenia” Dad
     opens B; `load_emmett` clicks `#button_emmett` of B, `action_load_emmett.php` goes with `order_id` = B and wipes
     Dad's pricing of B (`012: 3, 016: 2` → Emmett's `012: 1`); the window reads B's reloaded page, `_completed` enters
     A's file quantities into B (`015: 1`, `019: 2`), and A ends **gotowe** with a Znacznik efenix while A has no
     quantity in efenix. A ends gotowe here because B's Emmett gives `012: 1` like A's, so B's amount equals A's
     `Kwota`; with another Emmett A ends with an error about another amount, and B's pricing is wiped all the same.
   - `inne-zlecenie@w-przeladowaniu-po-zaladuj`: „Załaduj do zlecenia” lands in A, but Dad opens B during the reload;
     `load_emmett` reads B's page, `enter_quantity` writes `015` and `019` into B, and A ends with an Ostrzeżenie
     Emmetta made of B's quantities.
   - `inne-zlecenie@przed-ilosc-1` and `@przed-ilosc-2`: `enter_quantity` writes into B's field with the same id;
     A ends with an error about another amount, B keeps A's quantities.
   - `inne-zlecenie@przed-data`: `set_execution_date` saves A's date into B (`action_set_date_of_instalation.php`
     with `id` = B); A ends with `EFENIX_DATA_NIEZAPISANA`.

   The entry is an `Excuse` of `tools/lib/eksplorator.py` with its shape `StrayShape`: the writes that land elsewhere
   (`writes`: date, Emmett, quantity, not Przekazanie) and where (`targets`: the order Dad opened in the tab). Each part
   has a broken variant just outside it in `BOUNDARIES` of `check_karta_efenix_mutations.py`: the guard without the
   order comparison (Przekazanie of B) and an Atrapa script that sends a quantity with an order nobody opened. When a
   change fixes the finding, the check ends with `ZNALEZISKO ZNIKNĘŁO`: delete the entry here and in `KNOWN_FINDINGS`.

## When the check fails

Read the counterexample as numbered steps: Dad's action, then each write after it with the field that carried its
order and the order it landed in, then the result of A and the state of A and B in efenix. Then sort it:

- **Real bug**: the story can happen to Dad in his Chrome window, and a write landed in another order or B changed.
  Replay it with `--przypadek` and report it with the story. Fix the product code only if the user asks.
- **Modelling error**: the story has a step Dad cannot do in the tab, or the Atrapa page script takes the order from
  somewhere efenix does not (compare with `tools/zgodnosc_efenix.py` and the reconnaissance copy of the script). Fix the
  explorer or the Atrapa, then rerun the mutations.
- **LUKA MODELU**: a write without a pause before it, or a point Dad never reached. Give Dad a point before the new
  write (a new hook in the explorer at a public seam), or ask whether the write should have its pause. Never shrink the
  cases to make a real counterexample disappear.

## Bring the model in line

When a definition from `model/definicje.json` changes:

1. Read the diff against the table in „Does the change touch it?”: does Dad still get a point before each write, and
   does the known finding's story still describe the window?
2. Change the explorer where it no longer describes the code: Dad's hook (`sleep` and `finished` in `run_once`),
   `WRITES`, or the story and shape of `KNOWN_FINDINGS` and the list above. Never weaken the rule to make it pass.
3. Run the check and `--strict`. A new violation is a finding: replay it with `--przypadek` before you call it a bug.
4. Run `tools/przesun_model.py verify-karta-efenix` only after the explorer describes the code, and write in the commit
   message, in one sentence, what changed in the explorer and why.

## After changing the checker

CI proves the check can still fail: the night on `main` runs the script below after a change of this skill's folder.
Run it locally only to reproduce a red step or the night's issue, or after you rewrite a mutation:

```sh
.venv/bin/python .agents/skills/verify-karta-efenix/scripts/check_karta_efenix_mutations.py
```

It must end with `MUTACJE OK` (30 s on Maks's Mac, 2026-11-12): the guard without the order comparison and the Atrapa
script with a quantity for an order nobody opened give `NOWE NARUSZENIE` (`BOUNDARIES`), a Wycena that enters no
quantity gives `NOWE NARUSZENIE` (PRZEBIEG_WZORCOWY), a quantity saved without its pause gives `LUKA MODELU`, and a
window that checks the order of its tab before the date, Emmett, after the reload and before each quantity gives
`ZNALEZISKO ZNIKNĘŁO`. A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its anchor against the
new code so it breaks the same thing again.

## Files

- `scripts/explore_karta_efenix.py`: the explorer (scenario, Dad, rules, known finding, report).
- `scripts/check_karta_efenix_mutations.py`: the broken variants and `BOUNDARIES`.
- `model/definicje.json`: the definitions of the code the hand-made parts describe.
