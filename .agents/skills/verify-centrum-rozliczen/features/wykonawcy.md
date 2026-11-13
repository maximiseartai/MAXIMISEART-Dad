# Wykonawcy

Dad keeps the Lista Wykonawców himself in the section Wykonawcy of the window Ustawienia (ADR 0032): he adds a
Wykonawca with the login from INTERMAX, the name of his Rozliczenie pracownika and addresses, changes a Wykonawca with
`Edytuj` and `Zapisz` (name, addresses, a second login), switches Przypomnienia o raporcie and Nieaktywny at once, and
removes a Wykonawca whose login no period has. A saved login has no text field: it can only go (×) or get a second one
beside it. Each rule is the server's: a bad value comes back as a sentence at its field, a Wykonawca or login with
orders in the Rejestr zleceń or a Plik zbiorczy stays with a sentence that proposes Nieaktywny, and a new name while a
Rozliczenie pracownika with the old one lies in a period asks first. Closing Ustawienia with an unsaved form asks
`Zamknąć bez zapisu?`. The change itself, its Historia row and the processes are tested through the API
(`tests/test_centrum_rozliczen.py`, `tests/test_centrum_wpisanie_raportow.py`).

## Sub-features

- `wykonawcy-dodanie`: `Dodaj Wykonawcę` opens an empty form; with a login, a name and one address, `Zapisz` puts the Wykonawca on the list, active and with Przypomnienia (wide screenshot of the form).
- `wykonawcy-odmowa-przy-polu`: an address another Wykonawca has stays unsaved, with the server's sentence under that address field.
- `wykonawcy-zamkniecie-bez-zapisu`: Esc with a changed form asks `Zamknąć bez zapisu?`; `Wróć` keeps the window and what Dad typed.
- `wykonawcy-stara-nazwa`: a new name for a Wykonawca whose Rozliczenie pracownika lies in `22_28_09_2026` asks `Zmienić nazwę?` with the period and saves nothing until `Zmień nazwę`; Dad's files keep their names.
- `wykonawcy-odmowa-usuniecia`: `Usuń Wykonawcę` for a Wykonawca with orders in the Rejestr zleceń is refused with the sentence and `Oznacz jako nieaktywnego` next to it.
- `wykonawcy-przelaczniki`: `Oznacz jako nieaktywnego` and the switch `Przypomnienia` save at once; the Nieaktywny Wykonawca moves below the active ones.
- `wykonawcy-waskie-okno`: at 420×860 the form and the list fit without a horizontal scroll.
- `wykonawcy-usuniecie-i-powrot`: a Wykonawca without orders anywhere is removed; the feature then brings the Lista Wykonawców back to the fixture's bytes.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer, section Wykonawcy (`#/ustawienia/wykonawcy`).

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. The fixture's Lista Wykonawców has `Wykonawca Testowy A`–`D` with
  logins `wykonawca.a`–`wykonawca.d` and addresses `<login>@przyklad.invalid`; the Rejestr zleceń has orders of
  `wykonawca.a`–`wykonawca.c`, D has none, and `22_28_09_2026` has the Rozliczenia pracowników of A–C. The feature
  points the folder okresów and the Rejestr zleceń in Ustawienia (`ensure_files_set`) when no feature before did.

- **Add.** Open Wykonawcy. Button `Dodaj Wykonawcę`, form `Nowy Wykonawca`: textbox `Login` = `wykonawca.e`, label
  `Nazwa w Rozliczeniu pracownika` = `Wykonawca Testowy E`, `Dodaj adres`, textbox `Adres 1` =
  `wykonawca.e@przyklad.invalid`. Screenshot `380`. Button `Zapisz Wykonawcę`: list item `Wykonawca Testowy E` shows the
  address, the form is gone; `GET /api/settings` (`api/wykonawcy-dodany.json`) has the Wykonawca active with
  Przypomnienia, and `config/wykonawcy.yaml` has the login.
- **Refused at the field.** `Dodaj Wykonawcę` with login `wykonawca.f`, name `Wykonawca Testowy F` and `Adres 1` =
  `wykonawca.a@przyklad.invalid`; `Zapisz Wykonawcę`: the form's alert reads
  `Ten adres jest już na Liście Wykonawców. Jeden adres należy do jednego Wykonawcy.`, `Adres 1` is `aria-invalid`, and
  the file keeps its bytes. Screenshot `381`. `Anuluj`.
- **Unsaved form.** `Edytuj: Wykonawca Testowy A`, name `Wykonawca Testowy A2`, Esc: alertdialog `Zamknąć bez zapisu?`.
  Screenshot `382`. `Wróć`: the window stays and the name field still holds `Wykonawca Testowy A2`.
- **Old name.** `Zapisz Wykonawcę`: alertdialog `Zmienić nazwę?` contains
  `Rozliczenie pracownika ze starą nazwą jest już w okresie 22_28_09_2026.`, and `GET /api/settings`
  (`api/wykonawcy-przed-potwierdzeniem.json`) still has the old name. Screenshot `383`. `Zmień nazwę`: list item
  `Wykonawca Testowy A2`; the Folder rozliczeń pracowników of `22_28_09_2026` lists the same file names as before.
- **Removal refused.** `Edytuj: Wykonawca Testowy B`, `Usuń Wykonawcę`: the form's alert contains
  `Wykonawca ma zlecenia w Rejestrze zleceń, więc zostaje na Liście Wykonawców.` and `Oznacz jako nieaktywnego` is
  there; B is still listed (`api/wykonawcy-odmowa-usuniecia.json`). Screenshot `384`. `Anuluj`.
- **Switches.** `Edytuj: Wykonawca Testowy D`, `Oznacz jako nieaktywnego`: its list item shows `Nieaktywny`; `Anuluj`.
  Switch `Przypomnienia: Wykonawca Testowy C`: unchecked. `GET /api/settings` (`api/wykonawcy-przelaczniki.json`) has D
  inactive and C without Przypomnienia, and D is the last list item. Screenshot `385`.
- **Narrow window.** Viewport 420×860 with the window open: combobox `Sekcja Ustawień` names Wykonawcy;
  `Edytuj: Wykonawca Testowy E`: no horizontal scroll. Screenshot `386`; `Anuluj`; screenshot `387`. The viewport goes back to 1440×1000 (also in `finally`).
- **Removal and way back.** `Edytuj: Wykonawca Testowy E`, `Usuń Wykonawcę`: the list item is gone
  (`api/wykonawcy-usuniety.json`). Then the same changes the other way: A2 renamed back to A (no question, no file has
  the name A2), D `Oznacz jako aktywnego`, C's switch on; `config/wykonawcy.yaml` has the fixture's bytes again. ✕ (`Zamknij Ustawienia`) closes the window; Esc
  would first close the notification „Zapisano · Cofnij” of the last switch.
- **Proof.** Screenshots `380`–`387`, `api/wykonawcy-*.json` and the checks in `drive.txt`.

## Gotchas

- Removal checks every Plik zbiorczy of the folder okresów, so the button shows `Sprawdzam okresy…` until the server
  answers; wait for the list item or the alert, never a fixed time.
- The window Ustawienia is a modal: `Zamknąć bez zapisu?` and `Zmienić nazwę?` are alertdialogs above it, found on the
  page, not inside the window.
