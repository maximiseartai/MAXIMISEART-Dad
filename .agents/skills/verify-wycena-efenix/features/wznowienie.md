# Wznowienie

After each stop and each kill, Dad logs in, the network is back, and Dad starts the Wycena w efenix again: once as it
was, and once after each change he could make by hand in efenix to the order the run stopped at (`Edit`).

## Sub-features

- Without Dad's change in an order: efenix and the Plik zbiorczy end like one run without a fault
  (`BladTylkoPoZmianieTaty` of `verify-wznowienie-wyceny-efenix`), also after a stop or a kill between „Załaduj do
  zlecenia” and reading the reloaded page or before efenix saved a quantity: the second run completes the order to the
  file without loading Emmett again (ADR 0026; the accepted risks #774 and #864 before #960).
- `FINISHED`, `REMOVED_EMMETT`, `REMOVED_ADDED`, `OWN`: the second run completes the order Dad changed to the file only
  upwards (`completed` in the explorer, `ZmianaTatyZostaje`): a quantity he removed comes back from the file, one above
  the file stays and gives an Ostrzeżenie Emmetta.
- No quantity in efenix is lower after the second run than before it (`NieObnizaIlosci`), and an order with a quantity
  gets no new „Załaduj do zlecenia” (`NieCzysciWycenyTaty`).

## How to get to it (user POV)

Dad sees the Zatrzymanie, maybe fixes something in efenix himself, and clicks Wycena w efenix again.

## Driving it with the explorer

Every axis resumes its stops; `--variant zabity-proces` alone gives the most states, and `--variant odpowiedzi --rola
ilosc` the logout at a quantity.

## Gotchas

- An order Dad emptied has no pricing, so the second run prices it like a new one, with Wycena Emmetta.
- Two first runs that left the same state share one second run only when they broke in the step and way of the same
  accepted risks (`RiskShape.window`); with none today, equal states share one second run.
- A fault the window goes on after breaks it at a later step: a logout at the stylesheet of the page after Emmett breaks
  at the first quantity, and a torn script of that page breaks at the save of a quantity, which then sends nothing.
