# Ustawienia

Dad points Centrum once to his Rejestr zleceń and his folder okresów through
the native picker, in the section Foldery of the window Ustawienia, the only
place Centrum chooses files (ADR 0032). Centrum remembers both, plus the light
or dark theme of the section Wygląd, in a local settings file outside git, and
says plainly when a remembered path no longer exists. The window itself (gear,
closing, addresses, narrow window) is `okno-ustawien.md`.

## Sub-features

- `ustawienia-pusty-stan`: with no settings file, Okresy asks for the folder okresów with the link `Ustaw w Ustawieniach`, and nothing is set.
- `ustawienia-jedno-okno-wyboru`: a double click on `Wskaż Folder okresów` in Foldery opens one picker, and while it is open both picker buttons of Foldery wait, also after the window is closed and opened again over Uruchomienia.
- `ustawienia-folder-okresow`: from the empty Okresy, `Ustaw w Ustawieniach` and the folder picker set the folder okresów, and Tablica okresów appears once the window is closed.
- `ustawienia-rejestr-zlecen`: before the Rejestr zleceń is set, Uruchomienia says it is missing and its group links to Foldery; that link and the file picker set it.
- `ustawienia-braki-do-startu`: closing the window shows Uruchomienia without the alert and without the link: pointing it reads again what the start needs.
- `ustawienia-motyw-bez-odczytu`: switching the theme in Wygląd over Uruchomienia does not read again what the start needs: the theme is not one of Dad's files.
- `ustawienia-anulowanie`: a cancelled picker changes nothing.
- `ustawienia-nieistniejaca-sciezka`: a remembered Rejestr zleceń that is gone shows `Nie ma już: <name>` in Foldery.
- `ustawienia-nieczytelny-plik`: while the settings file cannot be read, both paths show `Nie da się teraz odczytać Ustawień Centrum`, not `Nie wskazano`.
- `ustawienia-niedostepna-sciezka`: a Rejestr zleceń and a folder okresów in a folder Dad cannot open now show `Nie da się teraz odczytać: <name>`, not `Nie ma już`.
- `ustawienia-motyw`: `Jasny` under Motyw in Wygląd switches to light, and the choice survives a reload.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer, section Foldery: `Wskaż`/`Zmień` next to `Rejestr zleceń` and `Folder okresów`; section Wygląd: Motyw `Jasny`/`Ciemny`.
- `Ustaw w Ustawieniach` on the empty Okresy and next to an unset file on Uruchomienia (groups `Rejestr zleceń`, `Folder okresów`, `INTERMAX`) and Raporty (group `INTERMAX`) opens `#/ustawienia/foldery`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run and `DOCTOR OK`; no settings file exists yet.

- **Empty state.** Open the URL. The text `Wskaż folder okresów` and the link `Ustaw w Ustawieniach` are visible, and `GET /api/settings` returns `not_set` for both paths (`api/ustawienia-przed.json`).
- **One picker at a time.** Click `Ustaw w Ustawieniach`. With no answer file, hold every `**/api/settings/*/choose` request with `page.route` (harness: Dad's native window stays open until he picks or closes it, labelled in `drive.txt`) and double-click button `Wskaż Folder okresów` (exact) in dialog `Ustawienia`. One picker request is held; the button shows `Czekam na wybór…` and both `Wskaż Rejestr zleceń` and `Wskaż Folder okresów` are disabled; capture `19`. Esc, link `Uruchomienia`, open Foldery again: both still wait, and still one request is held. Release the request: `dialogs.jsonl` gains exactly one line, both buttons are enabled again, and nothing is set. Esc, link `Okresy`.
- **Folder okresów.** Click `Ustaw w Ustawieniach` (heading `Ustawienia/Foldery`), write the `INEA` path to `picker/answer.txt`, click `Wskaż Folder okresów` until the settings file has the path, Esc. Table `Tablica okresów` appears, the last line of `dialogs.jsonl` is `Wybierz folder okresów (np. Załączniki albo INEA)`; capture `02`.
- **Rejestr zleceń.** Click link `Uruchomienia`: alert `Najpierw wskaż Rejestr zleceń.` is visible, group `Rejestr zleceń` reads `Rejestr zleceń: nie wskazano` with link `Ustaw w Ustawieniach` to `#/ustawienia/foldery`. Click it, write the Rejestr path, click `Wskaż Rejestr zleceń`. List item `Rejestr zleceń` shows `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, `dialogs.jsonl` ends with `Wybierz plik Rejestru zleceń`, and the settings file contains the path; capture `03`.
- **What the start needs.** Esc. `Nowe Uruchomienie procesu` is shown without the alert `Najpierw wskaż Rejestr zleceń.` and without a link in group `Rejestr zleceń`, button `Podgląd bez zapisu` is enabled, and `GET /api/runs/setup` (`api/ustawienia-braki-do-startu.json`) has no `blocker` for Przygotowanie pliku zbiorczego; capture `18`. Still there, open Wygląd and click `Jasny`, then `Ciemny` in group `Motyw`, each until it is pressed and the settings file has the theme, and wait 400 ms; Esc: no `GET /api/runs/setup` is sent and `Podgląd bez zapisu` stays enabled (before #164 the second read came from remounting the start on every settings answer). Click link `Okresy`.
- **Cancel.** With no answer file, open Foldery and click `Zmień Rejestr zleceń`. `dialogs.jsonl` gains one line, the button becomes enabled again, and the settings file is byte-identical.
- **Path gone.** Rename the Rejestr file, then reload (the window opens again on `#/ustawienia/foldery`). List item `Rejestr zleceń` shows `Nie ma już: ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, and `GET /api/settings` reports `order_register.state` = `missing` (`api/ustawienia-brak-rejestru.json`); capture `04`. Rename it back.
- **Settings file unreadable.** Harness: the system refuses to read the settings file (chmod 0; on Windows a byte-range lock, as when an antivirus holds it). Reload. List items `Rejestr zleceń` and `Folder okresów` show `Nie da się teraz odczytać Ustawień Centrum`, and `GET /api/settings` reports both paths `unreadable` (`api/ustawienia-nieczytelny-plik.json`); capture `275`. Harness: access back, reload, the Rejestr name is shown again.
- **Path without access.** Harness: folder `OneDrive` in the run root with a copy of the Rejestr zleceń and an empty `INEA`. Point both with `Zmień Rejestr zleceń` and `Zmień Folder okresów` until the settings file has them. Harness: `OneDrive` has no permissions (chmod 0). Reload. List item `Rejestr zleceń` shows `Nie da się teraz odczytać: ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx` and `Folder okresów` shows `Nie da się teraz odczytać: INEA`; capture `276`. `GET /api/settings` reports both `inaccessible` with their paths (`api/ustawienia-niedostepna-sciezka.json`). Harness: access back, point the fixture's Rejestr zleceń and `INEA` again, remove `OneDrive`, reload. On Windows chmod does not take away access to a folder (`NO_ACCESS_ON_WINDOWS` in the tests), so there the harness gives the page, through `page.route`, the answer of `GET /api/settings` for the fixture's paths in such a folder (`api/ustawienia-przed-niedostepna-sciezka.json` is the real answer it changes), and the drive checks the two texts and capture `276` only.
- **Theme.** Open Wygląd and click `Jasny` in group `Motyw`. `<html>` loses class `dark` and the settings file gets `motyw: light`. After a reload `Jasny` is still pressed and the page light; capture `05`. Click `Ciemny` to return to dark, Esc.
- **Proof.** Screenshots `01`–`05`, `18`, `19`, `275`, and `276`, and `state/centrum-ustawienia.yaml`.

## Gotchas

- `Wskaż folder okresów` (the empty state's title) and `Wskaż Folder okresów` (the button in Foldery) differ only in case. Use `exact=True`.
- The picker request blocks until the picker answers. Write `answer.txt` before the click, never after.
- The scripted picker answers at once, while Dad's native window stays open for seconds. A step about what happens while a picker is open holds the request with `page.route` and continues it afterwards; without that, the window is over before the second click.
- A waiting picker button spins forever, so capture that state with `live=True`, or `Run.capture` waits for the spinner until it times out.
- The picker that is open belongs to the tab, not to the window: closing and opening Ustawienia keeps both picker buttons waiting until it answers.
- Centrum reads the remembered Rejestr zleceń when Przygotowanie pliku zbiorczego, Uporządkowanie INTERMAX or Wpisanie raportów runs or a Diagnoza checks it, and for the day row of `Uporządkuj INTERMAX`; without it, starting such an Uruchomienie is refused with `Najpierw wskaż …`. A remembered Rejestr zleceń that is gone does not stop the start: `Podgląd bez zapisu` stays enabled, and the missing file surfaces in the Uruchomienie or its Diagnoza.
- Settings reload when the tab regains focus, so a missing path can also appear without a manual reload.
