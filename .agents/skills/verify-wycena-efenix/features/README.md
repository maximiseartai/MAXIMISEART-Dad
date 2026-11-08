# Wycena w efenix fault map

This map lists the axes of faults that `explore_wycena_efenix.py` drives through a real Wycena w efenix on the Atrapa
efenix. Each axis is a `--variant`; second runs with Dad's changes in efenix (`wznowienie`) follow every axis. Pick an
axis and a request role (`--rola`) to check one place while you work on it; CI runs them all.

## Baseline preconditions

- `.venv` of the checkout with the `dev` extra and Playwright's Chromium (`python -m playwright install chromium`).
- `explore_wycena_efenix.py --doctor` prints `DOCTOR OK`.
- No real efenix and no Dad's files: the Plik zbiorczy and the orders are synthetic (`tests/fixtures/efenix.py`).

## Driving conventions

- The window talks to the proxy of `awarie_efenix.py`, never to the Atrapa directly; the proxy breaks one request and
  counts clicks on buttons the window must never use.
- A request is named by method, path, kind of search and occurrence (`POST action_save_index.php #2`), and its role by
  `Role` in the explorer; `EXPECTED_CALLS` lists them for one run without a fault.
- Every expected outcome comes from the table in `expected()`, written from the docstrings and `GLOSSARY.md`, never
  from a run.

## Proof and skip reporting

- The last line is the verdict: `WYCENA EFENIX OK` (also with `, ZNANE USTALENIA: n` or `, ZAAKCEPTOWANE RYZYKA: m`),
  `WYCENA EFENIX: NOWE NARUSZENIE (n)`, `WYCENA EFENIX: LUKA MODELU (n)` or `WYCENA EFENIX: ZNALEZISKO ZNIKNĘŁO (n)`.
- Evidence stays in `<run dir>/evidence/<id>/`: `raport.txt`, `przebieg-bez-awarii.txt` and one JSON per
  counterexample in `kontrprzyklady/` (requests with the fault marked, efenix before and after, Znaczniki, Logi).
- A run with `--variant` or `--rola` narrowed, or one part of `MUTACJE_CZESC`, does not report a vanished finding.

## Features

- [Odcięcia](./odciecia.md) covers the network failing from one request on: cut, torn, stalled, slow.
- [Odpowiedzi](./odpowiedzi.md) covers one wrong answer: HTTP 4xx and 5xx, logout, redirect, a hung answer, the login page.
- [Granica czasu](./granica-czasu.md) covers an answer just before and just after the window's time limit.
- [Zamknięte okno](./zamkniete-okno.md) covers Dad closing the efenix tab while a request is on its way.
- [Logowanie](./logowanie.md) covers Dad logging in, or closing the tab, while the window waits for his login.
- [Zabity proces](./zabity-proces.md) covers the tool killed right before or right after efenix ran a request.
- [Wznowienie](./wznowienie.md) covers the second Uruchomienie after a stop, with and without Dad's changes in efenix.
