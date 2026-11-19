# Ustawienia

Dad points Centrum once to his Rejestr zleceń and his folder okresów through
the native picker, in the section Foldery of the window Ustawienia, the only
place Centrum chooses files (ADR 0032). Centrum remembers both, plus the light
or dark theme of the section Wygląd, in a local settings file outside git, and
says plainly when a remembered path no longer exists. Every change shows
`Zapisano` with `Cofnij` for a moment and is a row of the section Historia,
where any change can be undone; a wrong value is not saved and its one sentence
stands under its field. The window itself (gear, closing, addresses, narrow
window) is `okno-ustawien.md`.

## Sub-features

Printed by `scripts/sub_features.py --feature ustawienia` from the drive's steps and checks; refresh the section with it.

- `ustawienia-pusty-stan`: no settings file means nothing is set.
- `ustawienia-jedno-okno-wyboru`: a double click on Wskaż Folder okresów opens one picker (… requests); while the picker is open (held, harness), both picker buttons of Foldery wait for it; closed and opened again over Uruchomienia, Foldery still waits for the open picker; no button opened a second picker (… requests); after the cancelled picker every picker button works again, nothing set.
- `ustawienia-folder-okresow`: the folder picker opened with its title; the settings file remembers the folder okresów.
- `ustawienia-rejestr-zlecen`: before the Rejestr zleceń is set, Uruchomienia says it is missing and links to Foldery; the file picker opened; the settings file remembers the Rejestr zleceń.
- `ustawienia-braki-do-startu`: the Rejestr zleceń pointed in Ustawienia is no longer missing on Uruchomienia under it: its start is read again.
- `ustawienia-motyw-bez-odczytu`: switching the theme over Uruchomienia does not read the start again (… reads).
- `ustawienia-anulowanie`: a cancelled picker leaves the settings file unchanged.
- `ustawienia-nieistniejaca-sciezka`: a remembered Rejestr zleceń that is gone is reported as missing.
- `ustawienia-nieczytelny-plik`: a settings file that cannot be read now is reported as unreadable, not as nothing chosen; the theme of an unreadable settings file is unknown, and the page keeps the light theme it remembers (theme=…, shown …).
- `ustawienia-niedostepna-sciezka`: a Rejestr zleceń and a folder okresów in a folder without access read „Nie da się teraz odczytać”, not „Nie ma już”.
- `ustawienia-motyw`: after a reload the page reads the light theme from the settings file and drops the dark class.
- `ustawienia-zapisano-cofnij`: the switch shows „Zapisano · Cofnij” (… px).
- `ustawienia-blad-w-oknie`: after the failed save the page is back in the theme of the settings file, without a reload; the failed save left the theme as it was.
- `ustawienia-blad-po-zamknieciu`: the save of Motyw waits for its answer (… requests, held); a save that fails after the window Ustawienia closed is a notification over the page; the save that failed after the window closed left the theme as it was.
- `ustawienia-blad-zostawia-nastepny-wybor`: each click on Motyw is a save that waits for its answer (… requests, held); the failed save of Ciemny keeps Dad's next choice Jasny, which still waits (dark=…, Jasny=…); the failed saves left the theme as it was.
- `ustawienia-historia`: a change of the settings file outside Centrum is the newest row, marked „spoza Centrum”; the server's Historia has the change outside Centrum, then the undo from the toast; the undo is a new row on top, and the row it undid stays; an undo the server refuses is one sentence under its row.
- `ustawienia-historia-wydanie`: a change from a Release reads „Wydanie 0.9.0” in its row of Historia, with „Cofnij”.
- `ustawienia-odmowa-przy-polu`: a wrong typed path is not saved (… px); Esc in the field goes back from the field and leaves the window open; a wrong file from the picker is refused under its field, not saved.
- `ustawienia-wpisz-druga-bez-zmiany`: a … pasted from Explorer in quotes is saved without them; typing the … leaves the other path (…) as it was.
- `ustawienia-zle-ustawienie`: the server names the wrong field (…); a wrong folder okresów in the file is the server's one sentence under its field, nowhere else; a damaged file names no field (…); the sentence about the whole file stands above the list Foldery.
- `ustawienia-historia-bez-cofniecia`: the server's Historia has both wrong contents on top, neither of them undoable; a row of Historia that cannot be undone has no „Cofnij”, while a change of Dad's has; the good file is back.
- `ustawienia-autostart`: the server says the shortcut is there (…); a shortcut removed by hand is the switch off; the removed shortcut is the newest row of Historia, marked „spoza Centrum”.
- `ustawienia-autostart-bez-windows`: a computer without Windows Autostart is unsupported (…); the switch is disabled with the server's one sentence why.
- `ustawienia-haslo-skrzynki`: a wrong old password shows its sentence under the address and leaves „Zmień hasło” on; a password the skrzynka rejects is still saved, only its line changes and the file keeps BOM and CRLF; the password the skrzynka took is in the file; with no network the password is saved and the section says the skrzynka does not answer; neither GET /api/settings nor the Historia carries any password; Historia says only that the password changed, without „Cofnij”; a password with Polish letters is not saved.
- `ustawienia-przypomnienia`: with no file the section shows the values of ADR 0030, switched off; pory that overlap are refused under Pora wieczorna and nothing is saved; the preview shows Dad's sentence and footer before anything is saved; Historia names the switch and the morning with before → after.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer, section Foldery: `Wskaż`/`Zmień` and `Wpisz` next to `Rejestr zleceń` and `Folder okresów`; section Wygląd: Motyw `Jasny`/`Ciemny`; section Narzędzie: the switch `Uruchamiaj Centrum razem z Windows`; section Historia: the changes with `Cofnij`; section Skrzynka raportów: `Zmień hasło` next to `Hasło aplikacji`; section Przypomnienia: the switch `Przypomnienia o raporcie`, the pory, `Pierwsze przypomnienie`, `Treść`, `Stopka`, `Zapisz` and the preview below; section Wysyłka rozliczeń: `Temat`, `Treść`, the `Stopka` link to Przypomnienia, `Zapisz wysyłkę rozliczeń` and the preview below (driven by `wysylka-rozliczen`).
- The toast `Zapisano` after each change, with `Cofnij`.
- `Ustaw w Ustawieniach` on the empty Okresy and next to an unset file on Uruchomienia (groups `Rejestr zleceń`, `Folder okresów`, `INTERMAX`) and Raporty (group `INTERMAX`) opens `#/ustawienia/foldery`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature ustawienia`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/ustawienia-*.json`.

## Gotchas

- A folder without access is a real chmod only off Windows: there the drive waits for `GET /api/settings` to report both paths `inaccessible`. On Windows chmod takes no access away, so the page gets that answer from `page.route` and only the screen is checked.
- `Wskaż folder okresów` (the empty state's title) and `Wskaż Folder okresów` (the button in Foldery) differ only in case. Use `exact=True`.
- The picker request blocks until the picker answers. Write `answer.txt` before the click, never after.
- Centrum reads the remembered Rejestr zleceń when Przygotowanie pliku zbiorczego, Uporządkowanie INTERMAX or Wpisanie raportów runs or a Diagnoza checks it, and for the day row of `Uporządkuj INTERMAX`; without it, starting such an Uruchomienie is refused with `Najpierw wskaż …`. A remembered Rejestr zleceń that is gone does not stop the start: `Podgląd bez zapisu` stays enabled, and the missing file surfaces in the Uruchomienie or its Diagnoza.
- Settings reload when the tab regains focus, so a missing path can also appear without a manual reload.
- The toasts of a change of Ustawienia (`Zapisano`, `Cofnięto`, a failure) live in the window Ustawienia and go with it; other notifications stay under the window, as before it.
- A toast that a newer one replaced stays in the document while it slides out: find the toast on screen with `[data-slot=toast]:not([data-ending-style])`.
- The sidebar group `Historia` is itself a list named `Historia`; the changes are the list `Zmiany`.
