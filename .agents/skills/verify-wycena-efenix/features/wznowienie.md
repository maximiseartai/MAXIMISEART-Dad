# Wznowienie

After each stop and each kill, Dad logs in, the network is back, and Dad starts the Wycena w efenix again: once as it
was, and once after each change he could make by hand in efenix to the order the run stopped at (`Edit`).

## Sub-features

- Without Dad's change in an order: efenix and the Plik zbiorczy end like one run without a fault
  (`BladTylkoPoZmianieTaty` of `verify-wznowienie-wyceny-efenix`), except #774 (an order stopped between „Załaduj do
  zlecenia” and reading the reloaded page is left to Dad) and `przerwanie-przed-zapisem-ilosci` (an order stopped
  after the Ślad got a quantity ahead and before efenix saved it is left to Dad, #864), the latter only after a stop
  other than a logout or a kill: after a logout the Ślad withdraws that quantity (`trace.not_entered`).
- `FINISHED`, `REMOVED_EMMETT`, `REMOVED_ADDED`, `OWN`: the second run never changes an order Dad left with a pricing
  (`ZmianaTatyZostaje`); `REMOVED_ADDED` after a quantity efenix saved is the path of #864.
- A pricing that already is gets completed only when the Ślad has it as „Emmett załadowany” and the page has exactly
  Emmett's quantities and those the Ślad has ahead (`entering`), only by adding quantities in empty positions, never
  by loading Emmett again (`GLOSSARY.md`, Ślad Wyceny Emmetta; `NieCzysciWycenyTaty`).

## How to get to it (user POV)

Dad sees the Zatrzymanie, maybe fixes something in efenix himself, and clicks Wycena w efenix again.

## Driving it with the explorer

Every axis resumes its stops; `--variant zabity-proces` alone gives the most states, and `--variant odpowiedzi --rola
ilosc` the logout at a quantity.

## Gotchas

- An order Dad emptied (amount 0) has no pricing (`efenix_pricing`: „Zlecenie z kwotą w efenix różną od 0 ma już
  wycenę”), so the second run may price it like a new one.
- Two first runs that left the same state share one second run only after the same kind of interruption
  (`Interruption`: a logout, or another stop or a kill), so a logout never borrows the accepted risk of another stop.
