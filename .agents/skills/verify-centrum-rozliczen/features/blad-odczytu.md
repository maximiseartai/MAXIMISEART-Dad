# Błąd odczytu

Every page that reads from the server shows a failed read the same way: the
alert `Nie udało się odczytać <what>` with the Komunikat and the button
`Spróbuj ponownie`. The button reads once more; a successful read replaces the
alert with the page, a re-read on its way makes the button wait with a spinner,
and a second failure keeps the alert and gives the button back. One shared
component draws it (`frontend/src/components/load-failure.tsx`), so a page
without it is a dead end this feature catches. A page with several reads
(Okresy: Ustawienia taty, the board, the key numbers) shows one alert, and its
button reads every failed one again. The card `Uporządkowanie INTERMAX`
(`/api/intermax`) and the card `Kopie INTERMAX` (`/api/intermax/copies`) use the same
component, but this feature does not drive their failed reads.

## Sub-features

- `blad-odczytu-ustawienia`: Ustawienia taty that fail at the tab's start leave Okresy with `Nie udało się odczytać okresów`; `Spróbuj ponownie` reads them and the Tablica okresów appears.
- `blad-odczytu-tablica`: a failed read of the Tablica okresów on Okresy, then the board after `Spróbuj ponownie`.
- `blad-odczytu-okresy-jednym-kliknieciem`: Ustawienia taty, the Tablica okresów and the metrics all fail at the tab's start; Okresy shows one alert, and one `Spróbuj ponownie` reads all three again and brings back the board and the key numbers.
- `blad-odczytu-uruchomienia`: a failed read of what Uruchomienia needs to start (`Nie udało się odczytać Uruchomień`), then the combobox `Okres`.
- `blad-odczytu-historia`: a failed read of the Historia tab on Uruchomienia (`Nie udało się odczytać historii`), then the table `Historia Uruchomień procesu`.
- `blad-odczytu-metryki`: a failed read of Metryki (`Nie udało się odczytać metryk`), then the history table.
- `blad-odczytu-konfiguracja`: a failed read of Konfiguracja (`Nie udało się odczytać konfiguracji`), then the list `Wykonawcy`.
- `blad-odczytu-ponowna-porazka`: on Konfiguracja, Enter on `Spróbuj ponownie` while the re-read is held on its way leaves the button named the same, `aria-disabled` and in focus, and a second Enter reads nothing; failing again keeps the alert and gives the button back, still in focus; the next try reads the page.
- `blad-odczytu-aktualizacja`: a failed read of Aktualizacja narzędzia on Konfiguracja is the status `Nie udało się odczytać stanu aktualizacji.` with the Komunikat in the card `Narzędzie`; the next entry reads it and the sentence is gone.
- `blad-odczytu-powiadomienia`: a failed read of Powiadomienia behind the bell (`Nie udało się odczytać Powiadomień`), then the list or the card of a new Wydanie.
- `blad-odczytu-uwaga`: in `Napisz do Maksa` → `Do Uruchomienia`, a failed read of the Uruchomienia to pin (`Nie udało się odczytać Uruchomień`), then the radio group `Uruchomienie` or the calm `Nie ma jeszcze Uruchomień z Centrum.`

- `blad-odczytu-uzupelnienie`: a failed read of the summary of Uzupełnienie pliku zbiorczego (`Nie udało się odczytać okresu`) has `Spróbuj ponownie`, which reads it again; once Centrum answers, the summary comes back by itself or after the click.
- `blad-odczytu-uzupelnienie-rodzaj`: the same on the page of a kind (`#/uzupelnienie/<okres>/without_rule`): its click reads the kind again, and its heading `Wiersze bez reguły` comes back.
- `blad-odczytu-strumien`: an event of the Uruchomienia stream outside the contract (a tab of an older Centrum) gives Uruchomienia the alert `Podgląd przestał się aktualizować` with `Centrum rozliczeń odpowiedziało w nieoczekiwany sposób. Odśwież kartę.` instead of a skeleton that never ends; with a readable stream the page starts as usual.

## How to get to it (user POV)

- Any page of the sidebar, the bell `Powiadomienia`, or the dialog `Napisz do Maksa`, while Centrum does not answer (a stopped server, a busy laptop). Dad sees the alert in place of the page and presses `Spróbuj ponownie` once Centrum answers again.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, and no Uruchomienie procesu runs. The drive sets the folder okresów and the Rejestr zleceń when a feature before has not (`ensure_files_set`).
- The harness makes a read fail with `page.route("**<path>", lambda route: route.abort())` (the server is unreachable for that read, labelled in `drive.txt`); the browser then says `Centrum rozliczeń nie odpowiada.`

- **Every page.** For each sub-feature: route its path to abort, open the page, find `get_by_role("alert")` with `Nie udało się odczytać <what>`, check it holds `Centrum rozliczeń nie odpowiada.`, that the page's content is absent and that the alert's button `Spróbuj ponownie` is enabled, and capture. Remove the route, click `Spróbuj ponownie` while counting `GET <path>` with `page.on("request")`: at least one read goes out, the content appears, and the alert is gone. Paths and pages:
  - `/api/settings`: `page.goto(<url>#/okresy)` then `page.reload()`; content: table `Tablica okresów`; screenshot `139`.
  - `/api/periods`: link `Metryki`, then link `Okresy`; content: table `Tablica okresów`; screenshot `142`.
- **Whole Okresy.** Route `/api/settings`, `/api/periods` and `/api/metrics` to abort, `page.goto(<url>#/okresy)` then `page.reload()`, and wait until each of the three was aborted. Exactly one `alert` with `Nie udało się odczytać` holds `Centrum rozliczeń nie odpowiada.`; capture `153`. Remove the route and click its `Spróbuj ponownie` once, counting `GET /api/*`: table `Tablica okresów` appears, group `Najważniejsze liczby` shows `<n> OK` and no `Centrum rozliczeń nie odpowiada.`, no alert is left, and all three paths were read; capture `154`.
  - `/api/runs/setup`: link `Okresy`, then link `Uruchomienia`; content: combobox `Okres`; screenshot `143`.
  - `/api/metrics`: tab `Historia` on Uruchomienia; content: table `Historia Uruchomień procesu`; screenshot `144`.
  - `/api/metrics`: link `Okresy`, then link `Metryki`; content: the same table; screenshot `145`.
  - `/api/configuration`: link `Okresy`, then link `Konfiguracja`; content: list `Wykonawcy`; screenshot `146`.
  - `/api/notifications`: button `Powiadomienia` in the header; content: list `Powiadomienia` or region `Nowa wersja …`; screenshot `147`.
  - `/api/dad-notes/runs`: button `Napisz do Maksa`, then button `Do Uruchomienia` in group `Dotyczy`; content: radio group `Uruchomienie` or the text `Nie ma jeszcze Uruchomień z Centrum.`; screenshot `148`; Escape closes the dialog.
- **Aktualizacja narzędzia.** Right after the second failure, route `**/api/tool-update` to abort, link `Okresy`, then link `Konfiguracja`: a `status` with `Nie udało się odczytać stanu aktualizacji.` holds `Centrum rozliczeń nie odpowiada.`; capture `148b`. Remove the route and enter Konfiguracja the same way: list `Wykonawcy` is visible and the status is gone.
- **Uzupełnienie.** Last but one, route `**/api/periods/<needs_check>/quantities-to-fill` to abort (`fixture.json` → `settlement.needs_check`) and `page.goto(<url>#/uzupelnienie/<needs_check>)`: the alert `Nie udało się odczytać okresu` holds `Centrum rozliczeń nie odpowiada.`, button `Gotowe, rozlicz pracowników` is absent and `Spróbuj ponownie` is enabled. The live page re-reads a failed read every 3 s by itself while the tab is visible, so hide the tab first (`HIDE_TAB`, harness): a re-read already on its way meets the abort. Then replace the route with one that holds the request, wait for the entrance to end and click `Spróbuj ponownie`: it waits, disabled, and exactly one read is held, which only the click sent; capture `148c` with `live=True`. Let the held requests through, remove the route and show the tab again (`SHOW_TAB`): button `Gotowe, rozlicz pracowników` appears and the alert is gone. Then the same with `/quantities-to-fill/without_rule` and `#/uzupelnienie/<needs_check>/without_rule`: content: heading `Wiersze bez reguły` (level 2) in `main`, screenshot `148e`.
- **Stream.** Last, route `**/api/runs/events` to `route.fulfill` with `Content-Type: text/event-stream` and the body `data: {"view": {"state": "nieznany"}}` (harness: an event outside the contract), then `page.goto(<url>#/uruchomienia)` and `page.reload()`: the alert `Podgląd przestał się aktualizować` holds `Centrum rozliczeń odpowiedziało w nieoczekiwany sposób.` and combobox `Okres` is absent; capture `148d`. Remove the route and reload: combobox `Okres` is visible and the alert is gone.
- **Second failure.** On Konfiguracja with `/api/configuration` aborted, replace the route with one that holds the request (harness: an answer that takes its time) then focus `Spróbuj ponownie` and press Enter: the button keeps its name, is disabled (`aria-disabled`) and keeps the focus, and a second Enter sends no second request; capture `141` with `live=True` (the spinner turns). Abort the held request: the alert stays with `Centrum rozliczeń nie odpowiada.` and `Spróbuj ponownie` is enabled and still focused. Remove the route and click it: list `Wykonawcy` appears.
- **Proof.** Screenshots `139`, `141`–`148`, `148b`–`148e`, `153` and `154` and the checks in `drive.txt`.

## Gotchas

- Ustawienia taty are read once per tab start and on a return to the tab, so their failure needs a reload, not a menu click. A failed read of Ustawienia shows on Okresy only; Uruchomienia reads what it needs to start on its own.
- A page Dad has already seen shows its last data at once and reads again behind it. The failed read replaces that data with the alert, so a step must wait for the alert, not for the absence of old content first.
- `/api/metrics` is read on Okresy as well (its key numbers): leaving the route on while passing through Okresy fails that read too, which is harmless and not checked.
- The Spinner inside the waiting button turns forever while the request is held, so its capture uses `live=True`, and the held route must be answered in `finally`. Pressing Enter waits for the alert's entrance to end first, or `141` catches it half faded.
- The button has no `aria-busy`: in Centrum that attribute marks a loading skeleton, which `index.css` keeps transparent for its first 120 ms, so `141` would show no button.
- Powiadomienia mark new rows read on entry, which reads them once more after the click; the step counts at least one read, not exactly one.
