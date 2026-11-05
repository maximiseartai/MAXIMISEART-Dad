# Odpowiedzi

One answer of efenix is wrong while the network is fine: HTTP 4xx without running the request (404 for a page file,
403 otherwise), HTTP 500 after running it, efenix logging out at that request, a redirect to the list of orders, 200
with `result: nok` without running „Załaduj do zlecenia” (`REFUSED`, #889), the same refusal after the proposal of
that order came back as HTTP 500 (`REFUSED_NO_PROPOSAL`, two faults at one order, #908), an answer that never comes after the
request ran, and the login page under the address of an order page.

## Sub-features

- An error page instead of an order page names its status (`HttpStatus`), never a page shape (#808).
- An error answer to an action (search, date, Emmett, quantity) names the status or the network, never a page shape.
- A logout is `EFENIX_WYLOGOWANY` (or the login form under the order address, `Shape.LOGIN_FORM`).
- A date efenix did not save leaves the order to Dad (`DateRefused.NOT_SAVED`).
- A refused „Załaduj do zlecenia” stops or leaves the order to Dad; it never ends gotowe without Emmett.
- „Załaduj do zlecenia” refused with 200 `result: nok` in a valid session is `EFENIX_OKNO_ZATRZYMANE` with
  `Shape.EMMETT_NOT_LOADED` (the reloaded page has amount 0 after a dialog that showed a proposal), never a logout.
- The same refusal after a failed proposal, whose empty Emmett dialog looks like Emmett proposing nothing, is
  `Shape.EMMETT_NOT_LOADED` too: only a proposal that came whole with 2xx makes amount 0 an empty Wycena Emmetta (#908).

## How to get to it (user POV)

efenix has a bad moment: a server error, an expired session, a page file that does not load.

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant odpowiedzi [--rola <rola>]`.

## Gotchas

- A broken stylesheet does not stop anything, and a broken page script stops the next action on the time limit.
- The search the list sends by itself is not the window's: one wrong answer to it ends the run like the reference.
