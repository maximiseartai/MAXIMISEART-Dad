# Granica czasu

efenix runs the request and answers 0.6 s before or 0.6 s after the window's time limit (`LIMIT_MS`, 3 s in the
checker, 30 s at Dad's).

## Sub-features

- Just before: the run ends like the reference, or stops on the time limit; never with another cause.
- Just after: a stop on the time limit at that request's order.

## How to get to it (user POV)

efenix is slow on a busy day; one answer takes almost, or a little more than, the window's patience (#802).

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant granica-czasu [--rola <rola>]`.

## Gotchas

- A page and its files share one time limit (`goto` waits for `load`), so a late page file just before the limit may
  still stop the run; both outcomes are allowed.
