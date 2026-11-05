---
name: verify-wycena-efenix
description: Exhaustively break each request of a real Wycena w efenix (the window `efenix_browser.window` in Playwright's Chromium on the Atrapa efenix, behind a fault proxy) with every kind of fault (network cut, torn, stalled or slow; HTTP 4xx and 5xx; logout; redirect; a „Załaduj do zlecenia” refused with a 200 answer; a hung answer; an answer just before or after the window's time limit; the login page under an order address; a closed tab; Dad's login wait; the tool killed) and check the Zatrzymanie's cause and Komunikat, the efenix state, the Znaczniki efenix, the Logi and the Ślad Wyceny Emmetta, and what a killed tool leaves, then resume each stop and kill with and without Dad's changes in efenix. Use when a change touches `efenix_browser`, `efenix_pricing`, `efenix_emmett_trace`, `efenix_marking` or another `efenix_*` module, the Dziennik Wyceny w efenix, the Atrapa efenix, or when `explore_wycena_efenix.py` or the explorer tests in `tests/test_centrum_logi_uruchomienia.py` fail.
pilnuje:
  - src/rozliczenia/efenix_*.py
  - src/rozliczenia/centrum/pricing_journal.py
  - src/rozliczenia/centrum/efenix_run.py
  - tests/fixtures/atrapa_efenix.py
  - tests/fixtures/efenix.py
ci: .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py
ci-czesci: 8
---

# Verify Wycena w efenix

## What CI runs and what stays local

CI runs `explore_wycena_efenix.py` (the `ci:` key) in Mutation checks whenever a change touches this skill, in up to
`ci-czesci` parts: part k of n (`MUTACJE_CZESC=k/n`) runs the run without a fault and the k-th of n consecutive slices
of the cases (`--lista` prints them), with the second runs of its own stops and kills. The whole space (468 cases since
#908 added `REFUSED_NO_PROPOSAL`, 35 of them kills checked on the reference's states, and 68 distinct second runs) took
517 s on Maks's Mac with 4 browsers under a load of about 8 to 10, and the 8 parts, four at a time under a load of 15 to
18, took 63 to 85 s each (2026-11-05, reports in `~/.t3/notes/wycena-wznowienie-901/r3/`; without second runs the
parts took 57 to 75 s, so `ci-czesci` stays 8). Since the step of `przerwanie-przed-zapisem-ilosci` is any step (#920), the stops share second
runs by other windows: the whole space gives 73 distinct second runs in 518 s, with the same 52 first runs excused
(`~/.t3/notes/920/full-head/`). On Windows in CI the two parts of n=2 took 259 and 338 s (run
41985714991), about as long as on the Mac, so a part of n=8 takes about 1 to 1.5 min there. A
pull request runs the parts of one n, and the night on `main` runs every part of every n up to `ci-czesci`.
`tests/test_centrum_logi_uruchomienia.py` runs one small scope through every phase in pytest. `check_wycena_efenix_mutations.py`
runs in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`) after a change of this skill's folder. Run them
locally only to reproduce a red CI step or the night's issue, or one `--variant` and `--rola` while you work on it.

What stays with you on every change to the covered code: „Does the change touch it?” (a new request of the window, a new
action, a new kind of answer efenix gives: the explorer reports `LUKA MODELU` for a new request, but a new kind of fault
passes unchecked until `Fault` and `expected()` have it), sorting a red run as „When the check fails” says, and reading
the known findings below against the change.

## The promise

Each rule has its domain sentence, and the expected outcome of every fault comes from `expected()`, a table written
from these sentences, never from a run:

- **PRZYCZYNA**: a Zatrzymanie names the fault the way `efenix_browser` and `efenix_pricing.WindowCause` sort it, at
  the order of the faulted request. A broken network or a late answer is a browser failure with a named operation (or
  `EfenixUnreachable` before the list opened: „Lista zleceń, której okno nie otworzyło przy starcie … to
  `EfenixUnreachable`”; „Czy to zerwane połączenie, wolny czy zmieniony efenix, okno nie zgaduje”). An error page
  of efenix (4xx, 5xx) the window waits for is `HttpStatus` (#808, #878), a logout or a login form under the order
  address is a logout, a closed tab is `WindowClosed` „cokolwiek zgłosił wtedy Playwright”, a tab closed while the
  window waits for Dad's login is a closed window at once (#758), and an error page of the list after his login is
  `HttpStatus` at once (#891). A „Załaduj do zlecenia” efenix answers with 200 and `result: nok` in a valid session
  leaves the reloaded page with amount 0, which is `Shape.EMMETT_NOT_LOADED`, a Zatrzymanie of the window and not a
  logout (#889), unless Emmett proposed nothing, which the window knows only from an empty Emmett dialog after a
  proposal that came whole with 2xx; so the same refusal after the proposal of that order failed with HTTP 500
  (`REFUSED_NO_PROPOSAL`, two faults at one order) is `Shape.EMMETT_NOT_LOADED` too („Strona z kwotą 0 po każdej innej
  propozycji, także po pustym oknie Emmetta po padniętej propozycji, to `UnexpectedPage` z
  `Shape.EMMETT_NOT_LOADED`”, #908); an expired session there stays a logout. Only
  a page efenix really sent in another shape (a redirect elsewhere) may be a shape.
  The Zatrzymanie after a failed write of the Ślad ahead of a quantity (`EFENIX_SLAD_NIEZAPISANY`, with the facts of
  the Wycena and `AheadNotSaved`) is never the cause of a fault in efenix, because no fault of this checker touches
  the disk. A run that does not stop ends like the reference or leaves the faulted order to Dad (a date efenix did
  not save is `DateRefused.NOT_SAVED`); it never makes an order gotowe that differs from one run without a fault.
  Harm: Maks chases a changed efenix that never changed, or Dad gets a Znacznik on an order nobody checked with Emmett.
- **BEZ_ZMIANY_STATUSU**: the window never changes an order's status (`status_changes == 0`), never clicks Przekazanie
  do akceptacji, anulowanie or their „Tak” (the proxy's click watcher), and sends only requests of `EXPECTED_CALLS`
  and the login page (`GLOSSARY.md`, Przekazanie do akceptacji: „Robi je tylko tata”).
- **ZMIANA_ZE_SLADEM**: every order that changed in efenix has the action that changed it in its trace in the result or
  the Zatrzymanie, and a „zaczynam” entry in the dziennik; a Komunikat that says nothing changed in efenix is true; the
  Znaczniki efenix are exactly the gotowe orders; a gotowe order has the file's quantities, `Kwota` (AU) and the date
  (`GLOSSARY.md`, Znacznik efenix). What a killed tool leaves has a „zaczynam” entry in the dziennik for each order
  changed in efenix (`pricing_journal`: „przed każdym zapisem w efenix”), no Znaczniki efenix (`efenix_pricing`: „na
  końcu Znaczniki efenix”) and the file's pricing for each order the dziennik ended gotowe. Harm: Dad and Maks cannot
  tell what the tool did to efenix.
- **WZNOWIENIE**: the second Uruchomienie keeps the promises of the model `verify-wznowienie-wyceny-efenix` and the
  Ślad Wyceny Emmetta of `GLOSSARY.md`. It never changes an order Dad left with a pricing after changing it by hand
  (ZmianaTatyZostaje). It changes a pricing that already is only when the Ślad has it as „Emmett załadowany” and the
  page has exactly Emmett's quantities and the quantities the tool started entering, every other position empty
  („Ponowne uruchomienie dokańcza tylko wycenę zlecenia w stanie „Emmett załadowany”, gdy strona ma dokładnie te
  ilości Emmetta i te ilości narzędzia, a każdą inną pozycję pustą”), only by adding quantities in empty positions,
  never by loading Emmett again (NieCzysciWycenyTaty). Every order Dad did not change ends like one run (BladTylkoPoZmianieTaty),
  except the two accepted risks below. An order Dad emptied has no pricing (`efenix_pricing`: „Zlecenie z kwotą w
  efenix różną od 0 ma już wycenę”), so it may be priced like a new one. The Ślad is read as `efenix_emmett_trace`
  says: an entry without `entering` makes the whole file no trace. Harm: the tool writes over Dad's work in efenix
  (#757, #864), or leaves him an order it started.
- **BEZ_DANYCH**: the Logi (orders, Zatrzymanie, Komunikaty, as `run_logs` builds them), the dziennik and the Ślad
  have no order number, efenix identifier or address (ADR 0025, `efenix_emmett_trace`).
- **BEZ_WYJATKU** and **BEZ_AWARII**: a run ends with a result or a Zatrzymanie of the window within `CASE_LIMIT_S`, a
  second run ends with a result, and one run without a fault ends as `GLOSSARY.md` says (`REFERENCE_FINAL`).

Each stop and each kill gets a second run after Dad logs in and the network is back: once as it was, and once after each
change Dad could make by hand to the order it stopped at (`Edit`: he finished it, removed a quantity of Emmett's or one
the tool added, or priced the empty order himself). First runs that left the same state (efenix, the Plik zbiorczy and
the Ślad, where no Ślad file is not a file without the order) share one second run only when they broke in the place
and way of the same accepted risks (`RiskShape.window`), so a break outside a risk's window never shares a second run,
nor its risk, with one inside it. `REFUSED_NO_PROPOSAL` (#908) stops in place of loading Emmett and leaves the order as it was,
so its second run, with the proposal whole, finishes that order like one run (the model's `Zatrzymanie` in place of
`ZaladujEmmetta`). The model checks the same promises over every order of steps without a browser; this axis
checks them on the real window and the Atrapa.

## Launch

No server to keep: each run starts its own Atrapa efenix (`tests/fixtures/atrapa_efenix.py`) and proxy
(`scripts/awarie_efenix.py`) on free ports of `127.0.0.1`, and each worker its own headless Chromium of Playwright.
The scenario is two synthetic orders (`file_orders()`): order 1 (row 18) ends gotowe after the date, Emmett and two
quantities; order 2 (row 19) ends with an Ostrzeżenie Emmetta. The window's time limit is 4 s (3 s and the 1 s reload after „Załaduj do zlecenia”, which it
waits for in the same limit) and the login wait 4 s.
The Atrapa reloads the page 1 s after „Załaduj do zlecenia”, as efenix does (`EFENIX_EMMETT_RELOAD_MS`), not after the
200 ms of its tests.

## Doctor

```sh
.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --doctor
```

`DOCTOR OK` means Chromium starts and the list of orders shows through the proxy. Without Chromium:
`.venv/bin/python -m playwright install chromium`.

## Drive

```sh
.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py [--variant <axis> ...] [--rola <role> ...] [--rownolegle 4]
```

- `--variant`: `odciecia`, `odpowiedzi`, `granica-czasu`, `zamkniete-okno`, `logowanie`, `zabity-proces`, or `all`
  (default). The map in `features/` describes each axis; second runs follow every axis. An answer just before the window's time limit to „Załaduj do
  zlecenia”, to the page reloaded after it or to that page's files comes earlier by the 1 s reload (`early_s`), because
  the window waits for all of them in one time limit; at „Załaduj do zlecenia” it ends like the run without a fault.
- `--rola`: the request roles of `Role` (`strona-zlecenia`, `zaladuj-do-zlecenia`, `ilosc`, …).
- `--lista` prints the cases of this part (`MUTACJE_CZESC`) without a browser; `--zostaw-run` keeps the run files.
- The last line is the verdict: `WYCENA EFENIX OK`, `WYCENA EFENIX: NOWE NARUSZENIE (n)`, `WYCENA EFENIX: LUKA MODELU
  (n)` (the window sends requests `EXPECTED_CALLS` does not know: the space is stale) or `WYCENA EFENIX: ZNALEZISKO
  ZNIKNĘŁO (n)` (a run or a part ran a case after which a known finding always shows, and it did not).

## Evidence

`<run dir>/evidence/<id>/` (`--run-dir`, default `.verification` of the checkout): `raport.txt` (the report with the
verdict), `przebieg-bez-awarii.txt` (the requests of the reference run with times) and `kontrprzyklady/<case>.json` for
each case with a violation, a known finding or an accepted risk: the rules it broke, the Zatrzymanie, efenix before and
after, the Znaczniki, the Ślad, the requests with the fault marked (`← HTTP_4XX`) and the Logi. Evidence has no real
data: orders, addresses and numbers are synthetic.

## Cleanup

The explorer removes its run root (`<run dir>/runs/<id>`, marked `.katalog-runu`) at the end, also after a failure,
and keeps the evidence. Its browsers, Atrapas and proxies end with it. A run killed from outside leaves its run root:
remove that folder (only one with `.katalog-runu`).

## Helpers

- `scripts/explore_wycena_efenix.py`: the explorer (above).
- `scripts/awarie_efenix.py`: the proxy and `Fault`; imported by the explorer, not run alone.
- `scripts/check_wycena_efenix_mutations.py`: the mutation table (below).

## Known findings

A known finding is a violation the code has today, in `KNOWN_FINDINGS` with the story after which it is excused and its
`RiskShape` (Accepted risks below); it does not fail the check. One that is sure to show names in `after` the first runs after which it showed in every whole
run. Each of them counts on its own: a run or CI part that runs one of them and does not show the finding after
that very case ends with `ZNALEZISKO ZNIKNĘŁO`, naming the cases, also while the finding still shows after the others
(a fix of the list only). Narrow the entry there and here to the cases after which it still shows, or delete it. A name outside the space is `LUKA MODELU`. A `flaky` one (a race) names none and never reports
that; its match is the race's exact shape, so any other outcome of the same fault is a new violation.

None today. The race of #895 (the answer of „Załaduj do zlecenia” read after the reload dropped it) ended with #899:
the window no longer reads that answer, and no entry excuses it.

## Accepted risks

An accepted risk is a violation of WZNOWIENIE the model accepts as a known finding, and the report lists it apart from
new violations without failing. Each entry of `ACCEPTED_RISKS` and `KNOWN_FINDINGS` has a `RiskShape` whose four parts
are all required, so an entry cannot match on fewer of them (#920):

- **step**: the window's step at which run 1 broke (`interrupted_at`): that of its last request as the proxy saw it, a
  page with its files counting as one step, without a request Chromium sends again after a cut and without what efenix
  sent the browser to (the page after a redirect, the login page); for a kill, the step of the request it was killed at;
- **way**: how it broke (`Interruption`: a logout, or another stop or a kill);
- **left**: what run 1 left of the order, its page in efenix and its Ślad entry;
- **second run**: how the second run ended the order (page before and after, and the fault of its error).

Each part of each entry also has a broken variant just outside it in `BOUNDARIES` of
`check_wycena_efenix_mutations.py`, the same harm with that one part other than the story says, which must give a new
violation; `tests/test_mutacje_skilli.py` reds an entry with a part without one. A part that admits every member of its
enum restricts nothing and has none: the way of `#774`, and the step of `przerwanie-przed-zapisem-ilosci`, whose place
is its state, because the Ślad has a quantity ahead only after the window read the reloaded page; a step outside it
takes a request outside `EXPECTED_CALLS` or an order run 1 went past, which other checks report.

| Name | Step | Way | Left | Second run | Story |
|---|---|---|---|---|---|
| `#774` | `zaladuj-do-zlecenia`, `strona-po-emmetcie` | any | page with exactly Emmett's quantities, no Ślad entry (`emmett_outside_trace`) | unchanged, `PricedDifferently` (`only_compared`) | A stop or a kill between „Załaduj do zlecenia” and reading the reloaded page leaves Emmett in efenix and no trace, so the second run only compares and gives `EFENIX_WYCENA_INNA` for that order alone, which Dad finishes himself (the model's finding 1 `przerwanie-po-zaladuj`). In the whole run of 2026-11-05, 37 first runs in two second runs (`także po` in their counterexamples): `TORN` from Emmett's proposal on (the window breaks at the page efenix reloads after the „Załaduj do zlecenia” it ran), `TORN`, `STALLED`, `HTTP_5XX`, `HUNG`, `SLOW`, `LATE_AFTER` and a closed tab at „Załaduj do zlecenia”, every fault of the reloaded page that stops the window, `STALLED`, `SLOW`, `HUNG`, `LATE_AFTER` and a closed tab at its files, and the kills from after „Załaduj do zlecenia” to its files. A logout at the page's file breaks at the first quantity, outside this step. |
| `przerwanie-przed-zapisem-ilosci` | any of this order | not a logout | page with Emmett's quantities and a part of those the Ślad has ahead, nothing else (`unsaved_ahead`) | unchanged, `PricedDifferently` (`only_compared`) | A stop other than a logout, or a kill, after the Ślad got a quantity ahead and before efenix saved it leaves in the Ślad a quantity efenix does not have; the page cannot tell it from one Dad removed, so the second run gives `EFENIX_WYCENA_INNA` for that order alone and changes nothing in it (#864; the model's finding 3). The step is the save of a quantity, or the page after Emmett when its script did not load, so the save sends nothing. In the whole run of 2026-11-05, 15 first runs in three second runs: `CUT` and `TORN` at that page's stylesheet, those and `HTTP_4XX`, `HTTP_5XX` and `REDIRECT` at its script, `CUT`, `HTTP_4XX` and `REDIRECT` at either `action_save_index.php`, and the kills before them. After a logout the Ślad withdraws the quantity (`trace.not_entered`), so the same state there is a new violation. |

## When the check fails

Read the counterexample JSON as a story: the requests with the fault, what efenix had before and after, and the
Zatrzymanie or result. Then sort it:

- **Real bug**: the fault can happen at Dad's (his network, a slow or failing efenix, Dad closing the window or changing
  an order by hand) and the outcome breaks the rule as stated above. Report it with the story; fix the product only if
  the user asks, otherwise add it to the known findings with its counterexample, its `RiskShape` and a broken
  variant just outside each part of it in `BOUNDARIES`.
- **Modeling error**: a fault efenix or Chromium would not produce, or an expectation the domain sentence does not
  give. Fix `Fault`, `applies()` or `expected()` and say which sentence was wrong. Never widen an expectation to make
  a real counterexample pass.
- **`LUKA MODELU`**: the window sends other requests than `EXPECTED_CALLS`; add the new ones with their `Role`, give
  each fault an expectation, and check the map in `features/`.

## After changing the checker or an intended change to the window

CI proves the check can still fail. The night on `main` runs
`.agents/skills/verify-wycena-efenix/scripts/check_wycena_efenix_mutations.py` after a change of this skill's folder; it
applies each broken variant to a temporary copy of the checkout (`tools/mutacje.py`) and must end with `MUTACJE OK`.
Each gives `WYCENA EFENIX: NOWE NARUSZENIE`:

- #808: an HTTP error page instead of the order page read as a page shape; the page reloaded after Emmett read
  without its response; the login form under the order address read as a page shape;
- #802: a browser failure without the window's operation; the window waiting for the headers of an answer instead of
  the whole answer (a stalled answer hangs the run);
- #758: a tab closed during Dad's login wait not seen until the wait ends;
- #891: an error page of the list after Dad's login read as more waiting for his login;
- a tab closed during the window's action not seen at all (`_action` without its closed check);
- #895: the answer of „Załaduj do zlecenia” read after the reload at every Emmett;
- #889: amount 0 after „Załaduj do zlecenia” always read as Emmett proposing nothing, so a refusal with 200
  `result: nok` lets the window enter the file's quantities without Emmett;
- #908: an empty Emmett dialog after a failed proposal read as Emmett proposing nothing, so `REFUSED_NO_PROPOSAL`
  lets the window enter the file's quantities without Emmett;
- the window waiting for the reload after „Załaduj do zlecenia” 1 s shorter than for its answer, which only the answer
  just before the time limit meets;
- a „zaczynam” entry of the dziennik written only after the window's actions at an order;
- #757: „Emmett załadowany” written before „Załaduj do zlecenia”; a resume without checking that the page is as the
  process left it after Emmett; a pricing without a Ślad completed like one after Emmett;
- #864: a quantity entered in efenix without its write ahead in the Ślad (`_WrittenAhead`); a resume that takes an
  empty position the Ślad has ahead for one efenix did not save (the rule before the fix, which adds back a quantity
  Dad removed);
- `BOUNDARIES`, each just outside one part of the shape of an accepted risk: for `#774` a logout at the first quantity
  that removes the order from the Ślad (outside its step), a Ślad „Emmett załadowany” without Emmett's quantities
  written before „Załaduj do zlecenia” (outside what it left), and a second run that gives another error than
  `EFENIX_WYCENA_INNA` (outside its second run); for `przerwanie-przed-zapisem-ilosci` a quantity efenix did not save
  after a logout kept in the Ślad (`trace.not_entered` skipped, outside its way), a Ślad „gotowe” after a Zatrzymanie
  (outside what it left), and the same other error (outside its second run);
- the window clicking Przekazanie do akceptacji; the Ślad keyed by the order number; a Komunikat that always says
  nothing changed; a Zatrzymanie without the Znaczniki of orders gotowe before it.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its anchor and replacement against the new code
so that it breaks the same rule again.
