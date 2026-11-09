# Ustawienia

Dad points Centrum once to his Rejestr zleceń and his folder okresów through
the native picker. Centrum remembers both, plus the light or dark theme, in a
local settings file outside git, and says plainly when a remembered path no
longer exists.

## Sub-features

- `ustawienia-pusty-stan`: with no settings file, Okresy asks for the folder okresów and nothing is set.
- `ustawienia-jedno-okno-wyboru`: a double click on `Wskaż folder okresów` opens one picker, and while it is open every picker button waits, also on Uruchomienia and back on Okresy.
- `ustawienia-folder-okresow`: the folder picker sets the folder okresów, and Tablica okresów appears.
- `ustawienia-rejestr-zlecen`: the file picker sets the Rejestr zleceń; before that, Uruchomienia says it is missing for the start.
- `ustawienia-braki-do-startu`: back on Uruchomienia from the menu, the Rejestr zleceń is no longer missing: pointing it reads again what the start needs.
- `ustawienia-motyw-bez-odczytu`: switching the theme on Uruchomienia does not read again what the start needs: the theme is not one of Dad's files.
- `ustawienia-anulowanie`: a cancelled picker changes nothing.
- `ustawienia-nieistniejaca-sciezka`: a remembered Rejestr zleceń that is gone shows `Nie ma już: <name>`.
- `ustawienia-nieczytelny-plik`: while the settings file cannot be read, both paths show `Nie da się teraz odczytać Ustawień taty`, not `Nie wskazano`.
- `ustawienia-niedostepna-sciezka`: a Rejestr zleceń and a folder okresów in a folder Dad cannot open now show `Nie da się teraz odczytać: <name>`, not `Nie ma już`.
- `ustawienia-motyw`: the theme icon switches to light, and the choice survives a reload.

## How to get to it (user POV)

- Okresy with no folder okresów: the `Wskaż folder okresów` button in the empty state.
- Okresy, card `Ustawienia`: `Wskaż`/`Zmień` next to `Rejestr zleceń` and `Folder okresów`.
- Uruchomienia: the setup card has the same `Rejestr zleceń` and `Folder okresów` groups and buttons (for Przebieg rozliczeń, group `Plik zbiorczy` replaces the Rejestr); the drive uses Okresy.
- The sun/moon icon in the header (`Włącz motyw jasny` / `Włącz motyw ciemny`).

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run and `DOCTOR OK`; no settings file exists yet.

- **Empty state.** Open the URL. The text `Wskaż folder okresów` is visible, and `GET /api/settings` returns `not_set` for both paths (`api/ustawienia-przed.json`).
- **One picker at a time.** With no answer file, hold every `**/api/settings/*/choose` request with `page.route` (harness: Dad's native window stays open until he picks or closes it, labelled in `drive.txt`) and double-click button `Wskaż folder okresów` (exact). One picker request is held; the button shows `Czekam na wybór…` (its name stays `Wskaż folder okresów`, like the settings card's buttons) and is disabled, and so are `Wskaż Rejestr zleceń` and `Wskaż Folder okresów` in card `Ustawienia`; capture `19`. Click link `Uruchomienia`: the setup card's `Wskaż Rejestr zleceń` and `Wskaż Folder okresów` are disabled. Click link `Okresy`: all three still wait, and still one request is held. Release the request: `dialogs.jsonl` gains exactly one line, every picker button is enabled again, and nothing is set.
- **Folder okresów.** Write the `INEA` path to `picker/answer.txt`, then click button `Wskaż folder okresów` (exact). Table `Tablica okresów` appears, the last line of `dialogs.jsonl` is `Wybierz folder okresów (np. Załączniki albo INEA)`, and the settings file contains the `INEA` path.
- **Rejestr zleceń.** Click link `Uruchomienia`: alert `Najpierw wskaż Rejestr zleceń.` is visible. Click link `Okresy`, write the Rejestr path, then click button `Wskaż Rejestr zleceń`. Group `Rejestr zleceń` shows `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, `dialogs.jsonl` ends with `Wybierz plik Rejestru zleceń`, and the settings file contains the path.
- **What the start needs.** Click link `Uruchomienia`. `Nowe Uruchomienie procesu` is shown without the alert `Najpierw wskaż Rejestr zleceń.`, button `Podgląd bez zapisu` is enabled, and `GET /api/runs/setup` (`api/ustawienia-braki-do-startu.json`) has no `blocker` for Przygotowanie pliku zbiorczego; capture `18`. Still there, click `Włącz motyw jasny`, then `Włącz motyw ciemny`, each until the settings file has the theme, and wait 400 ms: no `GET /api/runs/setup` is sent and `Podgląd bez zapisu` stays enabled (before #164 the second read came from remounting the start on every settings answer). Click link `Okresy`.
- **Cancel.** With no answer file, click button `Zmień Rejestr zleceń`. `dialogs.jsonl` gains one line, the button becomes enabled again, and the settings file is byte-identical.
- **Path gone.** Rename the Rejestr file, then reload. Group `Rejestr zleceń` shows `Nie ma już: ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, and `GET /api/settings` reports `order_register.state` = `missing` (`api/ustawienia-brak-rejestru.json`). Rename it back.
- **Settings file unreadable.** Harness: the system refuses to read the settings file (chmod 0; on Windows a byte-range lock, as when an antivirus holds it). Reload. Groups `Rejestr zleceń` and `Folder okresów` show `Nie da się teraz odczytać Ustawień taty`, and `GET /api/settings` reports both paths `unreadable` (`api/ustawienia-nieczytelny-plik.json`); capture `275`. Harness: access back, reload, the Rejestr name is shown again.
- **Path without access.** Harness: folder `OneDrive` in the run root with a copy of the Rejestr zleceń and an empty `INEA`. Point both with `Zmień Rejestr zleceń` and `Zmień Folder okresów` until the settings file has them. Harness: `OneDrive` has no permissions (chmod 0). Reload. Group `Rejestr zleceń` shows `Nie da się teraz odczytać: ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx` and group `Folder okresów` shows `Nie da się teraz odczytać: INEA`; capture `276`. `GET /api/settings` reports both `inaccessible` with their paths (`api/ustawienia-niedostepna-sciezka.json`). Harness: access back, point the fixture's Rejestr zleceń and `INEA` again, remove `OneDrive`, reload. On Windows chmod does not take away access to a folder (`NO_ACCESS_ON_WINDOWS` in the tests), so there the harness gives the page, through `page.route`, the answer of `GET /api/settings` for the fixture's paths in such a folder (`api/ustawienia-przed-niedostepna-sciezka.json` is the real answer it changes), and the drive checks the two texts and capture `276` only.
- **Theme.** Click button `Włącz motyw jasny`. `<html>` loses class `dark` and the settings file gets `motyw: light`. After a reload the page is still light and the button reads `Włącz motyw ciemny`. Click it to return to dark.
- **Proof.** Screenshots `01`–`05`, `18`, `19`, `275`, and `276`, and `state/centrum-ustawienia.yaml`.

## Gotchas

- `Wskaż folder okresów` (empty state) and `Wskaż Folder okresów` (settings card) differ only in case. Use `exact=True`.
- The picker request blocks until the picker answers. Write `answer.txt` before the click, never after.
- The scripted picker answers at once, while Dad's native window stays open for seconds. A step about what happens while a picker is open holds the request with `page.route` and continues it afterwards; without that, the window is over before the second click.
- A waiting picker button spins forever, so capture that state with `live=True`, or `Run.capture` waits for the spinner until it times out.
- The picker that is open belongs to the tab, not to a page: navigating away and back keeps every picker button waiting until it answers.
- Centrum reads the remembered Rejestr zleceń only when Przygotowanie pliku zbiorczego runs or its Diagnoza checks it; without it, starting that Uruchomienie is refused with `Najpierw wskaż …`. A remembered Rejestr zleceń that is gone does not stop the start: `Podgląd bez zapisu` stays enabled, and the missing file surfaces in the Uruchomienie or its Diagnoza.
- Settings reload when the tab regains focus, so a missing path can also appear without a manual reload.
