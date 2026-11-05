# Zamknięte okno

Dad closes the efenix tab when the browser sends a request of the run. The browser side routes every request
(`page.route`) and calls `page.close()` from the route of the faulted one: a page it opens closes while Chromium holds
it, any other request after it went on to efenix.

## Sub-features

- Each request: `EFENIX_OKNO_ZAMKNIETE` (`WindowClosed`) at that request's order, gotowe orders before it marked.

## How to get to it (user POV)

Dad closes the Chrome window of the tool in the middle of the Wycena w efenix.

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant zamkniete-okno [--rola <rola>]`.

## Gotchas

- Closing the whole browser is not separate: the window sees a closed page either way (`BrowserEfenix.closed`).
- The `request` event of the reload the efenix script starts after „Załaduj do zlecenia”, and a `page.close()` sent
  while that navigation goes on, sometimes reached Chromium only when the context closed: the case then did not close
  the tab in 4 tries and ended `LUKA MODELU` (review of round 2 of #867). A held route closes it every time.
