# Wykonawcy

Dad keeps the Lista Wykonawców himself in the section Wykonawcy of the window Ustawienia (ADR 0032): he adds a
Wykonawca with the login from INTERMAX, the name of his Rozliczenie pracownika and addresses, changes a Wykonawca with
`Edytuj` and `Zapisz` (name, addresses, a second login), switches Przypomnienia o raporcie and Nieaktywny at once, and
removes a Wykonawca whose login no period has. A saved login has no text field: it can only go (×) or get a second one
beside it. Each rule is the server's: a bad value comes back as a sentence at its field, a Wykonawca or login with
orders in the Rejestr zleceń or a Plik zbiorczy stays with a sentence that proposes Nieaktywny, and a new name while a
Rozliczenie pracownika with the old one lies in a period asks first. Closing Ustawienia with an unsaved form asks
`Zamknąć bez zapisu?`. Under the list the section suggests the logins of the ordered orders of the current period and
the 4 before it in the Rejestr zleceń that no Wykonawca has, each with `Dodaj Wykonawcę`, and says in one sentence when
the Rejestr is not set or cannot be read (#1475). The change itself, its Historia row and the processes are tested
through the API (`tests/test_centrum_rozliczen.py`, `tests/test_centrum_wpisanie_raportow.py`).

## Sub-features

Printed by `scripts/sub_features.py --feature wykonawcy` from the drive's steps and checks; refresh the section with it.

- `wykonawcy-podpowiedz`: the login of today's order that no Wykonawca has is the one suggestion, with its number of orders; on a narrow window the suggestion fits without a horizontal scroll.
- `wykonawcy-dodanie-z-podpowiedzi`: the suggestion opens the form and saves nothing before Zapisz; after Zapisz the Wykonawca is on the list and the suggestion is gone.
- `wykonawcy-rejestr-nieczytelny`: a Rejestr zleceń that cannot be read is a sentence in the section, not an empty list of suggestions.
- `wykonawcy-dodanie`: the new Wykonawca is on the list, active and with Przypomnienia o raporcie; the Lista Wykonawców file has the new login.
- `wykonawcy-odmowa-przy-polu`: an address of another Wykonawca is not saved.
- `wykonawcy-zamkniecie-bez-zapisu`: closing Ustawienia with an unsaved form asks first, and Wróć keeps what Dad typed.
- `wykonawcy-stara-nazwa`: nothing is saved before Dad confirms; the Rozliczenie pracownika with the old name stays as it was: Centrum renames none of Dad's files.
- `wykonawcy-odmowa-usuniecia`: a Wykonawca with orders in the Rejestr zleceń stays.
- `wykonawcy-przelaczniki`: the Nieaktywny Wykonawca stands below the active ones (…).
- `wykonawcy-waskie-okno`: on a narrow window the form fits without a horizontal scroll.
- `wykonawcy-usuniecie-i-powrot`: a Wykonawca whose login no period has is removed.

## How to get to it (user POV)

Dad opens Ustawienia with the gear in the menu's footer and chooses the section Wykonawcy; a bookmark of
`#/ustawienia/wykonawcy` opens it too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wykonawcy`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP wykonawcy` in `drive.txt`, screenshots `390`–`397` and `410`–`413`, and `api/wykonawcy-*.json`.

## Gotchas

- A suggestion's button is named `Dodaj Wykonawcę: <login>`, so `Dodaj Wykonawcę` alone stays the one under the list.
- Removal checks every Plik zbiorczy of the folder okresów, so the button shows `Sprawdzam okresy…` until the server
  answers; wait for the list item or the alert, never a fixed time.
- The window Ustawienia is a modal: `Zamknąć bez zapisu?` and `Zmienić nazwę?` are alertdialogs above it, found on the
  page, not inside the window.
