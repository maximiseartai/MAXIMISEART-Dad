# Wznowienie

After each stop and each kill, Dad logs in, the network is back, and Dad starts the Wycena w efenix again: once as it
was, and once after each change he could make by hand in efenix to the order the run stopped at (`Edit`).

## Sub-features

- Without Dad's change: efenix and the Plik zbiorczy end like one run without a fault, except #774 (an order stopped
  between „Załaduj do zlecenia” and reading the reloaded page is left to Dad).
- `FINISHED`, `REMOVED_EMMETT`, `REMOVED_ADDED`, `OWN`: the second run never changes an order Dad left with a pricing.
- A pricing that already is gets completed only when the Ślad has it as „Emmett załadowany” and the page is as the
  process leaves it after Emmett, only by adding quantities in empty positions, never by loading Emmett again.

## How to get to it (user POV)

Dad sees the Zatrzymanie, maybe fixes something in efenix himself, and clicks Wycena w efenix again.

## Driving it with the explorer

Every axis resumes its stops; `--variant zabity-proces` alone gives the most states.

## Gotchas

- An order Dad emptied (amount 0) has no pricing (`efenix_pricing`: „Zlecenie z kwotą w efenix różną od 0 ma już
  wycenę”), so the second run may price it like a new one.
