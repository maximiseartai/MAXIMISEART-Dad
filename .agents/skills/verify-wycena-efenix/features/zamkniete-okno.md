# Zamknięte okno

Dad closes the efenix tab when the browser sends a request of the run (the browser side calls `page.close()` from its
`request` event).

## Sub-features

- Each request: `EFENIX_OKNO_ZAMKNIETE` (`WindowClosed`) at that request's order, gotowe orders before it marked.

## How to get to it (user POV)

Dad closes the Chrome window of the tool in the middle of the Wycena w efenix.

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant zamkniete-okno [--rola <rola>]`.

## Gotchas

- Closing the whole browser is not separate: the window sees a closed page either way (`BrowserEfenix.closed`).
