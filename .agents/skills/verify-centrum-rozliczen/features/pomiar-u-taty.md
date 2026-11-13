# Pomiar u taty

Centrum measures its own speed on Dad's computer without Dad seeing anything:
every API answer carries `Server-Timing` with the handling time only, and after
every ready view (the cold start of a page, a menu click, a click on the header bell) the browser sends one
measurement that the server appends to the Centrum log as a `pomiar` entry. The
entry holds the page id (`PageId`, the five pages of the menu, Powiadomienia and the Uzupełnienie page `#/uzupelnienie/<okres>`, which this feature does not drive), the times in milliseconds, and for each
API request the operation name from the contract with the browser and server
time, so Maks can tell slow OneDrive reads from a slow browser. No address,
path, period token or content reaches the log.

## Sub-features

- `pomiar-zimny-start`: opening the window Ustawienia afresh on `#/ustawienia/wzorce` logs one entry, `strona=ustawienia` with `getConfiguration` among its requests, and none for the start page it hides; opening each of the five pages afresh (Powiadomienia, then the four of the menu) logs `pomiar widok=zimny-start strona=<id>` with `gotowe_ms`, `fcp_ms`, `szkielet_ms`, and `zapytania` where every request is `<operation>:<browser ms>/<server ms>`.
- `pomiar-server-timing`: every API answer the browser got during those cold starts has `Server-Timing: centrum;dur=<ms>` and nothing more.
- `pomiar-przejscia-w-menu`: clicking Uruchomienia, Raporty, Metryki, Okresy in the sidebar logs one `widok=przejscie-w-menu` entry per click, in order, without `fcp_ms`, each request with its server time; Metryki, whose data the tab still has from its cold start, shows at once: `szkielet_ms=0` and no `zapytania`; the header bell, which is no sidebar link, then logs `widok=przejscie-w-menu strona=powiadomienia` without `fcp_ms`.
- `pomiar-szkielet-widoczny`: opening Ustawienia on Wzorce from Okresy, with the read of the configuration held by the harness for 600 ms, logs `strona=ustawienia` with `szkielet_ms` only for the time the skeleton was visible, about 120 ms less than the read.
- `pomiar-wiele-zapytan`: a view with more API requests than one measurement carries (the contract's `ViewTiming.requests` limit, 20) is still logged, with its newest requests, ending with the read that made the view ready; the harness holds the tool card's read of Aktualizacja narzędzia until the measurement is logged, because the view does not wait for it and its answer could otherwise land between the ready view and the sent measurement; the browser remembers no more requests than that limit.
- `pomiar-bez-sladu`: the page shows no alert, dialog or toast; the `pomiar` entries hold no path, `/api/` address or period token.
- `pomiar-obcy-origin`: a measurement from a foreign `Origin` is refused with 403 and adds no entry.

## How to get to it (user POV)

- None: Dad opens and clicks through Centrum as always. Maks reads the `pomiar` entries in `logs/centrum-rozliczen.log` on Dad's computer.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. The drive points Centrum to the fixture's folder okresów and Rejestr zleceń unless a feature before did (`ensure_files_set`), so Okresy and Uruchomienia read real synthetic files.

- **Cold start.** Go to `about:blank`, then to `<url>#/ustawienia/wzorce`; list `Wzorce` in dialog `Ustawienia` is visible. Within 10 s the log gains exactly one `pomiar` entry, `widok=zimny-start strona=ustawienia`, with every request as below and `getConfiguration` among them. Then for each page id `powiadomienia`, `okresy`, `uruchomienia`, `raporty`, `metryki` (in this order, so Metryki's data is the tab's for the menu clicks): go to `about:blank`, then to `<url>#/<id>`; heading `<title>` (level 1) is visible. Within 10 s the log gains exactly one `pomiar` entry with `widok=zimny-start strona=<id>`, numeric `gotowe_ms`, `fcp_ms`, `szkielet_ms`, and `zapytania` matching `<operation>:<n>/<n>` for every request.
- **Server-Timing.** Every `/api/` response the page received during the cold starts (`page.on("response")`, `api/pomiar-server-timing.json`) has header `server-timing` matching `centrum;dur=<n>[.<n>]`.
- **Menu clicks.** Click links `Uruchomienia`, `Raporty`, `Metryki`, `Okresy` (exact), waiting for each heading and 300 ms. The log gains four entries `widok=przejscie-w-menu` with `strona=` `uruchomienia`, `raporty`, `metryki`, `okresy` in that order, none with `fcp_ms`, each with server times except `metryki`: its last data from the cold start before shows at once, so its entry has `szkielet_ms=0` and no `zapytania` (the read in the background ends after the content). Then click the header's button `Powiadomienia` (its name gains `, są nowe` with the red dot, so not exact): heading `Powiadomienia`, and one more entry `widok=przejscie-w-menu strona=powiadomienia` without `fcp_ms`.
- **Visible skeleton.** Go to `about:blank`, then `<url>#/okresy`. Hold `/api/configuration` for 600 ms with `page.route` (harness, labelled in `drive.txt`) and set `location.hash` to `#/ustawienia/wzorce`; list `Wzorce` appears in dialog `Ustawienia`. The new entry has `strona=ustawienia`, `gotowe_ms` ≥ 600 and `0 < szkielet_ms ≤ gotowe_ms − 100`: the skeleton was in the DOM from the click but visible only after about 120 ms.
- **Many requests.** Go to `about:blank`, then `<url>#/okresy`. Hold only the first `/api/configuration` for 600 ms, and every `/api/tool-update` until the entry is logged (harness: the answer of the section Narzędzie could land between the measurement and its post), then set `location.hash` to `#/ustawienia/narzedzie` from a script that, 50 ms after the `hashchange`, dispatches `focus` on the window 25 times (limit + 5): every return to the tab reads the settings, the configuration and the Powiadomienia again. The new entry has exactly `maxItems` of `ViewTiming.requests` in `frontend/src/api/openapi.json` (20) requests, the last one the read the page got last before it sent the measurement (`page.on("requestfinished")`, operation from the contract's `GET` paths): every return to the tab reads the settings too, so the configuration is not always that read. Before #164 the browser remembered 50 and the contract refused the measurement, so the view was lost.
- **No trace.** Esc closes Ustawienia; no `alert` and no `dialog` on the page; capture `80`. `api/pomiar-dziennik.txt` holds every `pomiar` entry of the run; none contains the run root, `/api/` or a period token (`\d{2}_\d{2}_\d{2}_\d{4}`).
- **Foreign Origin.** `POST /api/view-timings` with `Origin: http://zly.example` and a valid body answers 403 (`api/pomiar-obcy-origin.json`); the log gains no `pomiar` entry.
- **Proof.** Screenshot `80`, `api/pomiar-*.{json,txt}`, `state/centrum-rozliczen.log`.

## Gotchas

- Playwright's `page.goto` to the same URL with another `#/<id>` changes only the hash, which Centrum counts as a menu click. Go to `about:blank` first for a real cold start.
- The browser sends the measurement after the next frame, so wait for the log entry before leaving the page; a navigation right after the heading appears can drop it.
- The measurement counts only requests finished before the content was ready; a refresh in the background that ends later is not in `zapytania`. A page already visited in the same tab shows its last data at once, so its menu-click entry usually has no `zapytania`; only a new document (`about:blank` first, or a reload) forgets them.
- This feature proves the measurement, not the speed: its times come from a busy verification run and are not compared with anything.
