---
name: verify-wycena-efenix
description: Exhaustively break each request of a real Wycena w efenix (the window `efenix_browser.window` in Playwright's Chromium on the Atrapa efenix, behind a fault proxy) with every kind of fault (network cut, torn, stalled or slow; HTTP 4xx and 5xx; logout; redirect; a hung answer; an answer just before or after the window's time limit; the login page under an order address; a closed tab; Dad's login wait; the tool killed) and check the Zatrzymanie's cause and Komunikat, the efenix state, the Znaczniki efenix, the Logi and the Ślad Wyceny Emmetta, then resume each stop with and without Dad's changes in efenix. Use when a change touches `efenix_browser`, `efenix_pricing`, `efenix_emmett_trace`, `efenix_marking` or another `efenix_*` module, the Dziennik Wyceny w efenix, the Atrapa efenix, or when `explore_wycena_efenix.py` or the explorer tests in `tests/test_centrum_logi_uruchomienia.py` fail.
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
of the cases (`--lista` prints them), with the second runs of its own stops. The whole space (463 cases, 30 distinct
second runs) took 345 s on Maks's Mac with 4 browsers, and parts 1/8 and 5/8 took 45 s and 50 s (2026-11-05, reports in
`~/.t3/notes/verify-wycena-efenix/`); windows-latest is about 3 times slower (`tools/lib/zakres_runu.py`), so a part takes
about 2.5 min there. A
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
  instead of the order page is `HttpStatus` (#808), a logout or a login form under the order address is a logout, a
  closed tab is `WindowClosed` „cokolwiek zgłosił wtedy Playwright”, and a tab closed while the window waits for Dad's
  login is a closed window at once (#758). Only a page efenix really sent in another shape (a redirect elsewhere) may
  be a shape. A run that does not stop ends like the reference or leaves the faulted order to Dad (a date efenix did
  not save is `DateRefused.NOT_SAVED`); it never makes an order gotowe that differs from one run without a fault.
  Harm: Maks chases a changed efenix that never changed, or Dad gets a Znacznik on an order nobody checked with Emmett.
- **BEZ_ZMIANY_STATUSU**: the window never changes an order's status (`status_changes == 0`), never clicks Przekazanie
  do akceptacji, anulowanie or their „Tak” (the proxy's click watcher), and sends only requests of `EXPECTED_CALLS`
  and the login page (`GLOSSARY.md`, Przekazanie do akceptacji: „Robi je tylko tata”).
- **ZMIANA_ZE_SLADEM**: every order that changed in efenix has the action that changed it in its trace in the result or
  the Zatrzymanie, and a „zaczynam” entry in the dziennik; a Komunikat that says nothing changed in efenix is true; the
  Znaczniki efenix are exactly the gotowe orders; a gotowe order has the file's quantities, `Kwota` (AU) and the date
  (`GLOSSARY.md`, Znacznik efenix). Harm: Dad and Maks cannot tell what the tool did to efenix.
- **WZNOWIENIE**: a second Uruchomienie never changes an order Dad left with a pricing after changing it by hand;
  changes a pricing that already is only when the Ślad has it as „Emmett załadowany” and the page has only Emmett's
  quantities and the file's quantities in positions empty at Emmett (`GLOSSARY.md`, Ślad Wyceny Emmetta), only by
  adding quantities in empty positions, never by loading Emmett again; and without Dad's change ends like one run.
  An order Dad emptied has no pricing (`efenix_pricing`: „Zlecenie z kwotą w efenix różną od 0 ma już wycenę”), so it
  may be priced like a new one. Harm: the tool writes over Dad's work in efenix (#757).
- **BEZ_DANYCH**: the Logi (orders, Zatrzymanie, Komunikaty, as `run_logs` builds them), the dziennik and the Ślad
  have no order number, efenix identifier or address (ADR 0025, `efenix_emmett_trace`).
- **BEZ_WYJATKU** and **BEZ_AWARII**: a run ends with a result or a Zatrzymanie of the window within `CASE_LIMIT_S`, a
  second run ends with a result, and one run without a fault ends as `GLOSSARY.md` says (`REFERENCE_FINAL`).

## Launch

No server to keep: each run starts its own Atrapa efenix (`tests/fixtures/atrapa_efenix.py`) and proxy
(`scripts/awarie_efenix.py`) on free ports of `127.0.0.1`, and each worker its own headless Chromium of Playwright.
The scenario is two synthetic orders (`file_orders()`): order 1 (row 18) ends gotowe after the date, Emmett and two
quantities; order 2 (row 19) ends with an Ostrzeżenie Emmetta. The window's time limit is 3 s and the login wait 4 s.

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
  (default). The map in `features/` describes each axis; second runs follow every axis.
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
does not fail the check. Each names in `after` the first runs after which it showed in every whole run (three on
2026-11-05), and any run or CI part that runs one of them without the finding ends with `ZNALEZISKO ZNIKNĘŁO`: delete the
entry there and here. A name outside the space is `LUKA MODELU`. A `flaky` one (a race) names none and never reports
that; its match is the race's exact shape, so any other outcome of the same fault is a new violation.

| Name | Counterexample | Story |
|---|---|---|
| `blad-http-poza-strona-zlecenia` | `HTTP_4XX przy POST action_fill_orders.php (okno) #1`: `EFENIX_OKNO_ZATRZYMANE (RESULTS, OtherShape(NO_TABLE))`; the same for `GET index.php` (`ElementCount(#field_numer, 0)`) and `action_save_index.php` (`ANSWER_NOT_JSON`), 4xx and 5xx | `_read_order` names the HTTP status only for the order page (#808); an error answer to the list, the search or a quantity is called a page in another shape, so Maks sees a changed efenix on a server error. |
| `gotowe-bez-wyceny-emmetta` | `HTTP_4XX przy POST action_load_emmett.php #2`: order 2, whose Emmett contradicts the file, ends gotowe with `Emmett 0x` and a Znacznik efenix instead of an Ostrzeżenie Emmetta; also `REDIRECT` and order 1 | efenix refuses „Załaduj do zlecenia”, its page script reloads anyway, and the window reads the empty page as the Wycena Emmetta: the Ślad gets an empty Emmett and the process adds the file's quantities. |
| `karta-zamknieta-w-nawigacji` (flaky) | `TAB_CLOSED przy GET page_order_edit.php #3`: `EFENIX_OKNO_ZATRZYMANE (EMMETT, BrowserFailure(Error, RELOAD))`; also `BrowserFailure(Error, OPEN)` at the list again and the order page; 3 to 6 of the 8 closes at a navigation (of 35 tab closes) in each of three whole runs, never another error type or operation | the navigation error reaches the window before `Page.is_closed()` is true, so `_action` does not see the closed tab. Excused only as Playwright's plain `Error` at the operation that opens that page (`_RACE`: `OPEN` at the list and the order page, `RELOAD` after Emmett), so a `TargetClosedError`, an answer, a date, a search or a quantity with a closed tab stays a new violation. A regression that gives exactly this error at every navigation passes as the race: 8 of 35 tab closes are navigations, and some race in every run, so no share of them can tell the two apart. |
| `wznowienie-dopisuje-usunieta-ilosc` | `TORN przy POST action_save_index.php #2 → ponownie, tata usunął ilość dopisaną przez proces`: `[012=1, 019=2]` → `[012=1, 015=1, 019=2]` | the page looks as before the process added the quantity, and the Ślad keeps only „Emmett załadowany”, not the added quantities. This is #864 (after a normal end the same edit of Dad's gives `EFENIX_WYCENA_INNA`, #757); after its fix every run or part with `TORN` at `action_save_index.php` ends with `ZNALEZISKO ZNIKNĘŁO`, so the PR of that fix deletes this entry here and in `KNOWN_FINDINGS`. |

## Accepted risks

| Name | Story |
|---|---|
| `#774` | A stop between „Załaduj do zlecenia” and reading the reloaded page leaves the order with Emmett only and outside the Ślad; the second run gives an error of that order alone, which Dad finishes himself (accepted in #774, „Wyjątek” in `tests/test_wycena_efenix.py`). |

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
- a tab closed during the window's action not seen at all (`_action` without its closed check), which the race entry
  `karta-zamknieta-w-nawigacji` must not excuse;
- #757: „Emmett załadowany” written before „Załaduj do zlecenia”; a resume without checking that the page is as the
  process left it after Emmett; a pricing without a Ślad completed like one after Emmett;
- the window clicking Przekazanie do akceptacji; the Ślad keyed by the order number; a Komunikat that always says
  nothing changed; a Zatrzymanie without the Znaczniki of orders gotowe before it.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its anchor and replacement against the new code
so that it breaks the same rule again.
