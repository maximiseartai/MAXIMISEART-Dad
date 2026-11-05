---
name: verify-wycena-efenix
description: Exhaustively break each request of a real Wycena w efenix (the window `efenix_browser.window` in Playwright's Chromium on the Atrapa efenix, behind a fault proxy) with every kind of fault (network cut, torn, stalled or slow; HTTP 4xx and 5xx; logout; redirect; a hung answer; an answer just before or after the window's time limit; the login page under an order address; a closed tab; Dad's login wait; the tool killed) and check the Zatrzymanie's cause and Komunikat, the efenix state, the Znaczniki efenix, the Logi and the Ślad Wyceny Emmetta, and what a killed tool leaves. Use when a change touches `efenix_browser`, `efenix_pricing`, `efenix_emmett_trace`, `efenix_marking` or another `efenix_*` module, the Dziennik Wyceny w efenix, the Atrapa efenix, or when `explore_wycena_efenix.py` or the explorer tests in `tests/test_centrum_logi_uruchomienia.py` fail.
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
of the cases (`--lista` prints them). The whole space (463 cases then, now 464 with `LOGIN_ERROR`; 35 of them kills
checked on the reference's states) took 396 s on Maks's Mac with 4 browsers under a load of 10 to 17, and parts 1/8,
5/8 and 8/8 took 45 s, 61 s and 63 s (2026-11-05, reports in `~/.t3/notes/verify-wycena-efenix/r4-podzial/`); windows-latest is about 3 times slower
(`tools/lib/zakres_runu.py`), so a part takes about 3 min there. A
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
  `HttpStatus` at once (#891). Only a page efenix really sent in another shape (a redirect elsewhere) may be a shape.
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
- **BEZ_DANYCH**: the Logi (orders, Zatrzymanie, Komunikaty, as `run_logs` builds them), the dziennik and the Ślad
  have no order number, efenix identifier or address (ADR 0025, `efenix_emmett_trace`).
- **BEZ_WYJATKU** and **BEZ_AWARII**: a run ends with a result or a Zatrzymanie of the window within `CASE_LIMIT_S`,
  and one run without a fault ends as `GLOSSARY.md` says (`REFERENCE_FINAL`).

The second Uruchomienie after a stop, with and without Dad's changes in efenix, is checked by the model of
`verify-wznowienie-wyceny-efenix`, and its axis on the Atrapa comes back in a separate pull request.

## Launch

No server to keep: each run starts its own Atrapa efenix (`tests/fixtures/atrapa_efenix.py`) and proxy
(`scripts/awarie_efenix.py`) on free ports of `127.0.0.1`, and each worker its own headless Chromium of Playwright.
The scenario is two synthetic orders (`file_orders()`): order 1 (row 18) ends gotowe after the date, Emmett and two
quantities; order 2 (row 19) ends with an Ostrzeżenie Emmetta. The window's time limit is 3 s and the login wait 4 s.
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
  (default). The map in `features/` describes each axis.
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

A known finding is a violation the code has today, in `KNOWN_FINDINGS` with the story after which it is excused; it
does not fail the check. One that is sure to show names in `after` the first runs after which it showed in every whole
run. Each of them counts on its own: a run or CI part that runs one of them and does not show the finding after
that very case ends with `ZNALEZISKO ZNIKNĘŁO`, naming the cases, also while the finding still shows after the others
(a fix of the list only). Narrow the entry there and here to the cases after which it still shows, or delete it. A name outside the space is `LUKA MODELU`. A `flaky` one (a race) names none and never reports
that; its match is the race's exact shape, so any other outcome of the same fault is a new violation.

| Name | Counterexample | Story |
|---|---|---|
| `odczyt-tresci-po-przeladowaniu` (flaky, #895) | `HUNG przy GET css/efenix.css #8 [plik-strony-po-emmetcie]` and `LATE_AFTER przy GET js/page_order_edit.js #5 [plik-strony-po-dacie]` on windows-latest (run 41963463871, part 2/2 on 2026-11-05): `EFENIX_OKNO_ZATRZYMANE (EMMETT, BrowserFailure(Error, ANSWER))` at order 1 right after `action_load_emmett.php` and the reload `page_order_edit.php #3`, before the faulted request was sent | `load_emmett` reads the body of the answer to „Załaduj do zlecenia” (since #882), and when the reload the efenix script starts after it comes first, Chromium has dropped that body (`Response.text`: „Network.getResponseBody: No resource with given identifier found”); a read 0.3 s late breaks it on the 200 ms reload of the Atrapa's tests, so the explorer's Atrapa reloads after 1 s, as efenix does. Excused only as exactly this cause, at `EMMETT`, in a first run whose faulted request never reached the proxy and whose fault is not one the browser makes (a closed tab, Dad's login), so any other cause, or this one after a fault, stays a new violation; the run without a fault stays strict, so a read after the reload at every Emmett fails it. |

## When the check fails

Read the counterexample JSON as a story: the requests with the fault, what efenix had before and after, and the
Zatrzymanie or result. Then sort it:

- **Real bug**: the fault can happen at Dad's (his network, a slow or failing efenix, Dad closing the window or changing
  an order by hand) and the outcome breaks the rule as stated above. Report it with the story; fix the product only if
  the user asks, otherwise add it to the known findings with its counterexample.
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
- #895: the answer of „Załaduj do zlecenia” read after the reload at every Emmett, which the race entry
  `odczyt-tresci-po-przeladowaniu` must not excuse;
- a „zaczynam” entry of the dziennik written only after the window's actions at an order;
- the window clicking Przekazanie do akceptacji; the Ślad keyed by the order number; a Komunikat that always says
  nothing changed; a Zatrzymanie without the Znaczniki of orders gotowe before it.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its anchor and replacement against the new code
so that it breaks the same rule again.
