# Logowanie

The efenix session ends when the window opens the list, so the window waits for Dad's login (`LOGIN_LIMIT_MS`, 4 s in
the checker, 15 min at Dad's). Then Dad logs in (`LOGIN_LATER`) or closes the tab (`LOGIN_CLOSED`); a login that never
comes is `LOGGED_OUT` at the list in `odpowiedzi`.

## Sub-features

- A login in time lets the run end like the reference.
- A closed tab is `EFENIX_OKNO_ZAMKNIETE` at once (`Closed.DURING_LOGIN`), not a logout after the wait (#758).

## How to get to it (user POV)

Centrum opens the efenix window, Dad sees the login page, and either logs in or closes it.

## Driving it with the explorer

`.venv/bin/python .agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py --variant logowanie`.
The login page gets a script from the proxy that asks for `__tata` 0.3 s after it shows; the browser side acts then.

## Gotchas

- Only the list at the start has these faults (`applies()`): later logouts are not waited for.
