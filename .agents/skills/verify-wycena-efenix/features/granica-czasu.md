# Granica czasu

efenix runs the request and answers 0.6 s before or 0.6 s after the window's time limit (`LIMIT_MS`, 4 s in the
checker, 30 s at Dad's). The answer to „Załaduj do zlecenia”, to the page reloaded after it and to that page's files
comes 1 s earlier still, because the window waits for them and the 1 s reload in one time limit (`early_s`).

## Sub-features

- Just before: the run ends like the reference, or stops on the time limit; never with another cause. At „Załaduj do
  zlecenia” it ends like the reference only, because nothing but the answer and the reload shares its time limit.
- Just after: a stop on the time limit at that request's order.

## How to get to it (user POV)

efenix is slow on a busy day; one answer takes almost, or a little more than, the window's patience (#802).

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant granica-czasu [--rola <rola>]`.

## Gotchas

- A page and its files share one time limit (`goto` waits for `load`), so a late page file just before the limit may
  still stop the run; both outcomes are allowed.
