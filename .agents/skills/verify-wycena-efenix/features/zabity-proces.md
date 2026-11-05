# Zabity proces

The tool's process dies right before or right after efenix ran a request. Nothing runs after it: no Znaczniki, no Logi.
The checker takes what the run without a fault had at that moment (Atrapa orders, Plik zbiorczy, Ślad, dziennik) and
starts the second run from it.

## Sub-features

- Before and after each request of the reference run (70 states; equal states run once).
- Every order changed in efenix before the kill has a „zaczynam” entry in the dziennik.

## How to get to it (user POV)

Centrum goes out (power, crash, Windows update) during a Wycena w efenix, and Dad starts it again later (#845).

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant zabity-proces [--rola <rola>]`.

## Gotchas

- The snapshot is the real kill's state only for what the tool persists (efenix, files); its memory is gone anyway.
