# Odcięcia

From one request of the run on, the network fails until the end of the run: the connection is cut before the
request runs (`CUT`), the answer is torn in the middle (`TORN`), it stops in the middle (`STALLED`), or efenix runs the
request and answers only after the window gave up (`SLOW`).

## Sub-features

- `CUT` at each request: a browser failure with a named operation, and `EFENIX_NIEDOSTEPNY` only before the list opened.
- `TORN`, `STALLED`, `SLOW`: the same, with the time limit (`TimeoutError`) for the last three.
- The Komunikat says that nothing changed in efenix only when nothing did.

## How to get to it (user POV)

Dad's network drops or slows down in the middle of a Wycena w efenix that he started in Centrum rozliczeń.

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant odciecia [--rola <rola>]`.
A stop is PRZYCZYNA-checked against `expected()`, then resumed (see `wznowienie`).

## Gotchas

- A torn or stalled order page may never fire `load`; the window then fails on the time limit, which is the network.
- An outage that starts at the search the list sends by itself stops the window at its own search, one request later.
