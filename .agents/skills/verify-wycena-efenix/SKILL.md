---
name: verify-wycena-efenix
description: Exhaustively break each request of a real Wycena w efenix (the window `efenix_browser.window` in Playwright's Chromium on the Atrapa efenix, behind a fault proxy) with every kind of fault (network cut, torn, stalled or slow; HTTP 4xx and 5xx; logout; redirect; a „Załaduj do zlecenia” refused with a 200 answer; a hung answer; an answer just before or after the window's time limit; the login page under an order address; a closed tab; Dad's login wait; the tool killed) and check the Zatrzymanie's cause and Komunikat, the efenix state, the Znaczniki efenix and the Logi, and what a killed tool leaves, then resume each stop and kill with and without Dad's changes in efenix and check that the second run completes every order to the file only upwards. Use when a change touches `efenix_browser`, `efenix_pricing`, `efenix_positions`, `efenix_marking` or another `efenix_*` module, the Dziennik Wyceny w efenix, the Atrapa efenix, or when `explore_wycena_efenix.py` or the explorer tests in `tests/test_centrum_logi_uruchomienia.py` fail.
pilnuje:
  - src/rozliczenia/efenix_*.py
  - src/rozliczenia/centrum/logs_disk.py
  - src/rozliczenia/centrum/efenix_chrome.py
  - tools/lib/atrapy/atrapa_efenix.py
  - tools/lib/atrapy/model_efenix.py
  - tests/fixtures/okno_w_procesie.py
  - tools/lib/atrapy/efenix.py
  - tools/lib/eksplorator.py
ci: .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py
ci-czesci: 8
---

# Verify Wycena w efenix

## What CI runs and what stays local

CI runs `explore_wycena_efenix.py` (the `ci:` key) in Mutation checks whenever a change touches this skill, in up to
`ci-czesci` parts: part k of n (`MUTACJE_CZESC=k/n`) runs the run without a fault and the k-th of n consecutive slices
of the cases (`--lista` prints them), with the second runs of its own stops and kills. The whole space (468 cases since
#908 added `REFUSED_NO_PROPOSAL`, 35 of them kills checked on the reference's states, and 68 distinct second runs) took
517 s on Maks's Mac, and the 8 parts took 63 to 85 s each, so `ci-czesci` stays 8 (2026-11-05, PR #916, Evidence).
No accepted risk (none since #960) and no known finding is left (`scripts/explore_wycena_efenix.py:701`), so first
runs that left the same state share one second run (`_resumes`, `scripts/explore_wycena_efenix.py:1508`). The whole
space in two parts gave 217 and 216 first runs and 34 and 36 states after a kill in 229 and 278 s, `WYCENA EFENIX OK`
with no first run excused (2026-11-05, PR #965, Evidence). On Windows in CI the two parts of n=2 took 259 and 338 s (run
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

- **PRZYCZYNA**: a Zatrzymanie names the fault the way `efenix_browser` and `efenix_window.WindowCause` sort it, at
  the order of the faulted request. A broken network or a late answer is a browser failure with a named operation (or
  `EfenixUnreachable` before the list opened: „Lista zleceń, której okno nie otworzyło przy starcie … to
  `EfenixUnreachable`”; „Czy to zerwane połączenie, wolny czy zmieniony efenix, okno nie zgaduje”). An error page
  of efenix (4xx, 5xx) the window waits for is `HttpStatus` (#808, #878), a logout or a login form under the order
  address is a logout, a closed tab is `WindowClosed` „cokolwiek zgłosił wtedy Playwright”, a tab closed while the
  window waits for Dad's login is a closed window at once (#758), and an error page of the list after his login is
  `HttpStatus` at once (#891). A „Załaduj do zlecenia” efenix answers with 200 and `result: nok` in a valid session
  leaves the reloaded page without any quantity, which is `Shape.EMMETT_NOT_LOADED`, a Zatrzymanie of the window and
  not a logout (#889), unless Emmett proposed nothing, which the window knows only from an empty Emmett dialog after a
  proposal that came whole with 2xx; so the same refusal after the proposal of that order failed with HTTP 500
  (`REFUSED_NO_PROPOSAL`, two faults at one order) is `Shape.EMMETT_NOT_LOADED` too (`efenix_pricing._emmett`: „Strona
  bez ilości po każdej innej propozycji, także po pustym oknie Emmetta po padniętej propozycji, to `UnexpectedPage` z
  `Shape.EMMETT_NOT_LOADED`”, #908); an expired session there stays a logout. Only
  a page efenix really sent in another shape (a redirect elsewhere) may be a shape.
  A run that does not stop ends like the reference or leaves the faulted order to Dad (a date efenix did
  not save is `DateRefused.NOT_SAVED`); it never makes an order gotowe that differs from one run without a fault.
  Harm: Maks chases a changed efenix that never changed, or Dad gets a Znacznik on an order nobody checked with Emmett.
- **BEZ_ZMIANY_STATUSU**: every run of the explorer is a Wycena in the mode without Przekazanie (`PricingMode.FILL`, the
  default), in which the window never changes an order's status (`status_changes == 0`), never clicks Przekazanie do
  akceptacji, anulowanie or their „Tak” (the proxy's click watcher), and sends only requests of `EXPECTED_CALLS` and the
  login page (`GLOSSARY.md`, Wycena w efenix: „bez Przekazania gotowe zlecenie oznacza Znacznikiem efenix”, ADR 0027).
  The mode with Przekazanie is outside the explorer (see Outside the explorer).
- **ZMIANA_ZE_SLADEM**: every order that changed in efenix has the action that changed it in its trace in the result or
  the Zatrzymanie, and a „zaczynam” entry in the dziennik; a Komunikat that says nothing changed in efenix is true; the
  Znaczniki efenix are exactly the gotowe orders; a gotowe order has the file's quantities, `Kwota` (AU) and the date
  (`GLOSSARY.md`, Znacznik efenix). What a killed tool leaves has a „zaczynam” entry in the dziennik for each order
  changed in efenix (`logs_disk`: „przed każdym zapisem w efenix”), no Znaczniki efenix (`efenix_pricing`: „na
  końcu Znaczniki efenix”) and the file's pricing for each order the dziennik ended gotowe. Harm: Dad and Maks cannot
  tell what the tool did to efenix.
- **WZNOWIENIE**: the second Uruchomienie keeps the promises of the model `verify-wznowienie-wyceny-efenix` and the
  Wycena w efenix of `GLOSSARY.md` (ADR 0026, #960). It never loads Emmett into an order with a quantity
  (NieCzysciWycenyTaty) and never lowers or clears a quantity in efenix (NieObnizaIlosci). An order Dad changed by hand
  ends as `completed` gives it from what he left: each position where efenix has less than the file gets the file's
  quantity, a position with more stays, and the order is an Ostrzeżenie Emmetta with such a position and gotowe
  without it (ZmianaTatyZostaje). Every order Dad did not change ends like one run (BladTylkoPoZmianieTaty), also the
  one a stop or a kill cut between „Załaduj do zlecenia” and reading the reloaded page or before efenix saved a
  quantity (the accepted risks #774 and #864 before #960). Like one run means the same quantities, date and status,
  with Wycena Emmetta loaded and never over a pricing other than itself (`like_one_run`); how many times efenix loaded
  it does not count, because after a torn answer Chromium sends „Załaduj do zlecenia” again and efenix loads Emmett
  twice into the same order (CI run 42058117564 on Windows, #965), which replaces nothing. The Atrapa counts the loads
  over another pricing apart (`emmett_over_pricing`). An order Dad emptied has no pricing, so it is priced like a new
  one. Harm: the tool wipes or lowers Dad's work in efenix, or leaves him an order it started.
- **BEZ_DANYCH**: the Logi (orders, Zatrzymanie, Komunikaty, as `run_logs` builds them) and the dziennik have no order
  number, efenix identifier or address (ADR 0025).
- **BEZ_WYJATKU** and **BEZ_AWARII**: a run ends with a result or a Zatrzymanie of the window within `CASE_LIMIT_S`, a
  second run ends with a result, and one run without a fault ends as `GLOSSARY.md` says (`REFERENCE_FINAL`).

Each stop and each kill gets a second run after Dad logs in and the network is back: once as it was, and once after each
change Dad could make by hand to the order it stopped at (`Edit`: he finished it, removed a quantity of Emmett's or one
the tool added, or priced the empty order himself). First runs that left the same state (efenix and the Plik zbiorczy)
share one second run only when they broke in the place and way of the same accepted risks (`RiskShape.window`, none
today), so a break outside a risk's window never shares a second run, nor its risk, with one inside it. `REFUSED_NO_PROPOSAL` (#908) stops in place of loading Emmett and leaves the order as it was,
so its second run, with the proposal whole, finishes that order like one run (the model's `Zatrzymanie` in place of
`ZaladujEmmetta`). The model checks the same promises over every order of steps without a browser; this axis
checks them on the real window and the Atrapa.

## Launch

No server to keep: each run starts its own Atrapa efenix (`tools/lib/atrapy/atrapa_efenix.py`) and proxy
(`scripts/awarie_efenix.py`) on free ports of `127.0.0.1`, and each worker its own headless Chromium of Playwright.
The scenario is two synthetic orders (`file_orders()`): order 1 (row 18) ends gotowe after the date, Emmett (with T one
less than the file, like the S of #960) and two quantities, T over Emmett's and AG; order 2 (row 19) ends with an
Ostrzeżenie Emmetta, because Emmett has more than the file in T. The window's time limit is 4 s (3 s and the 1 s reload after „Załaduj do zlecenia”, which it
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
- The last line is the verdict: `WYCENA EFENIX OK` or `WYCENA EFENIX OK, ZNANE USTALENIA: n, ZAAKCEPTOWANE RYZYKA: m`
  (a count of zero left out; exit 0), `WYCENA EFENIX: NOWE NARUSZENIE (n)` (exit 1), `WYCENA EFENIX: LUKA MODELU (n)`
  (the window sends requests `EXPECTED_CALLS` does not know: the space is stale; exit 2) or `WYCENA EFENIX: ZNALEZISKO
  ZNIKNĘŁO (n)` (a run or a part ran a case after which a known finding or accepted risk always shows, and it did not;
  exit 1).

## Evidence

`<run dir>/evidence/<id>/` (`--run-dir`, default `.verification` of the checkout): `raport.txt` (the report with the
verdict), `przebieg-bez-awarii.txt` (the requests of the reference run with times) and `kontrprzyklady/<case>.json` for
each case with a violation, a known finding or an accepted risk: the rules it broke, the Zatrzymanie, efenix before and
after, the Znaczniki, the requests with the fault marked (`← HTTP_4XX`) and the Logi. Evidence has no real
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

A known finding is a violation the code has today, in `KNOWN_FINDINGS` as an `Excuse` of `tools/lib/eksplorator.py`
with the story after which it is excused and its `RiskShape` (Accepted risks below); it does not fail the check. One that is sure to show names in `after` the first runs after which it showed in every whole
run. Each of them counts on its own: a run or CI part that runs one of them and does not show the finding after
that very case ends with `ZNALEZISKO ZNIKNĘŁO`, naming the cases, also while the finding still shows after the others
(a fix of the list only). Narrow the entry there and here to the cases after which it still shows, or delete it. A name outside the space is `LUKA MODELU`. A `flaky` one (a race) names none and never reports
that; its match is the race's exact shape, so any other outcome of the same fault is a new violation.

None today. The race of #895 (the answer of „Załaduj do zlecenia” read after the reload dropped it) ended with #899:
the window no longer reads that answer, and no entry excuses it.

## Outside the explorer

- **The mode with Przekazanie (ADR 0027).** The explorer runs every case without Przekazanie, so a
  fault at the request `action_change_status.php`, at the search that confirms it or at the reload after it is not
  swept, and neither is a kill between Przekazanie and the Znaczniki. What covers it instead: the window contract
  (`tests/test_atrapa_efenix.py`, rows `przekazanie`, `przekazanie-bez-zmiany-statusu`, `przekazanie-odmowa-efenix`,
  `przekazanie-odmowa-tekstem-spoza-listy` and a logout before the status change), the guard tests on the Atrapa efenix,
  the refusal of Przekazanie in efenix's information dialog for each of its four texts and one outside the list
  (`test_odmowa_przekazania_przez_efenix_to_blad_zlecenia_bez_znacznika_a_nastepne_gotowe_zlecenie_jest_przekazane`), and a resume from the state a kill after Przekazanie leaves (an order „Do
  akceptacji” with a Znacznik efenix) on the window in process (`tests/test_wycena_efenix.py`, „Przekazanie do
  akceptacji”), and the model `verify-wznowienie-wyceny-efenix`
  (actions `Przekaz` and `Szukaj` under every Zatrzymanie and switch-off). Extending `Fault`, `expected()` and the
  second runs to the mode with Przekazanie is open work.

## Accepted risks

An accepted risk is a violation of WZNOWIENIE the model accepts as a known finding, and the report lists it apart from
new violations without failing. It names in `after` the first runs after which it always shows, or is `flaky`, as a
known finding does. Each entry of `ACCEPTED_RISKS` and `KNOWN_FINDINGS` has a `RiskShape` whose four parts
are all required, so an entry cannot match on fewer of them (#920):

- **step**: the window's step at which run 1 broke (`interrupted_at`): that of its last request as the proxy saw it, a
  page with its files counting as one step, without a request Chromium sends again after a cut and without what efenix
  sent the browser to (the page after a redirect, the login page); for a kill, the step of the request it was killed at;
- **way**: how it broke (`Interruption`: a logout, or another stop or a kill);
- **left**: what run 1 left of the order, its page in efenix;
- **second run**: how the second run ended the order (page before and after, and the fault of its error).

Each part of each entry also has a broken variant just outside it in `BOUNDARIES` of
`check_wycena_efenix_mutations.py`, the same harm with that one part other than the story says, which must give a new
violation; `tests/test_mutacje_skilli.py` reds an entry with a part without one. A part that admits every member of its
enum restricts nothing and has none.

None today. Until #960 there were two, both from the Ślad Wyceny Emmetta: `#774` (a stop or a kill between „Załaduj do
zlecenia” and reading the reloaded page left Emmett in efenix without a Ślad entry, and the second run gave
`EFENIX_WYCENA_INNA`) and `przerwanie-przed-zapisem-ilosci` (#864: a quantity the Ślad had ahead and efenix did not).
Since #960 the second run completes both orders to the file like one run (ADR 0026): the whole space ran without an
excused first run (above, in „What CI runs”).

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
applies each broken variant to a temporary copy of the checkout (`tools/lib/silnik_mutacji.py`) and must end with `MUTACJE OK`.
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
- #960: Wycena Emmetta loaded also into an order with quantities; a pricing that already is only compared instead of
  completed to the file; the file's quantity entered only in positions empty on the page (the rule before #960, which
  leaves Emmett's S below the file); the file's quantity entered also where efenix has more (lowering it); no
  Ostrzeżenie Emmetta for a position with more than the file;
- #965: Wycena Emmetta loaded into an order with quantities on resume also on the axis `odciecia` at
  `propozycja-emmetta` and `ilosc`, where a torn answer can make efenix load Emmett twice;
- the window clicking Przekazanie do akceptacji; a Komunikat that always says nothing changed; a Zatrzymanie without the Znaczniki of orders gotowe before it.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its anchor and replacement against the new code
so that it breaks the same rule again.
